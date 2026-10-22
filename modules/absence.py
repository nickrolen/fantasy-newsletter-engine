"""
absence.py -- A2, the absence model. The one implementation.

simulator_betting (and through week_score_matrices the playoff and Cup
simulators) and marginal_value all call this module. Nothing else in the tree
turns a Yahoo injury tag into missed games.

WHAT IT REPLACES
----------------
INJURY_DECAY, a per-CALENDAR-DAY availability curve drawn independently each
day. It let a player tagged OUT play his next game 20% of the time, made the
same tag cost a Tue/Thu/Sat team less than a Mon/Wed/Fri team, and produced
play-miss-play weeks no real absence has.

THE MODEL
---------
Count the player's OWN TEAM'S games from the tag's anchor date: g1, g2, g3.
Each chain tag is an absorbing chain -- once he plays, the absence is over --
given by P(play g_k | he missed every earlier game), k = 1, 2, 3:

    config/league_config.json absence_chain     Q (least severe), D, O

The numbers live THERE, not here, with their provenance: they are NICK'S
STATED JUDGEMENT (Q and O 2026-10-19, D 2026-10-22) and are NOT MEASURED.
Q's g2 is LOWER than its g1 on purpose: a questionable player who then
actually sat is in worse shape than the tag said. O's g1 is 0.00 by
definition of the tag. See CALIBRATION.

THE THREE-GAME CAP IS A DESIGN INVARIANT, NOT A MEDICAL CLAIM
--------------------------------------------------------------
An absence longer than three games is a KNOWN absence and belongs in
INJURY_OVERRIDES. The two inputs partition the space, so a CHAIN tag alone
never costs more than MAX_TAG_GAMES games. OFS is the one designation that
is not a short-horizon signal, and it is deliberately exempt: it is not a
chain at all (TAGS below).

ONE DRAW, NOT A WALK
--------------------
The chain collapses to a distribution over k = games missed, and the missed
games are always the FIRST k, contiguous. So: draw k once per (simulation,
player, tag), mark his first k team games out. Blocks by construction, no
state carried across days. The distribution is DERIVED from the chain in
code (missed_distribution) -- never typed in a second time.

PRECEDENCE (callers implement steps 1-2 and 5; this module owns 3-4)
------------------------------------------------------------------
  0. an OFS tag                            -> out, every remaining game.
  1. INJURY_OVERRIDES out_weeks / out_from -> out. The tag does not apply.
  2. return_date in return_week            -> out before the date.
  3. otherwise a Q/D/O tag                 -> the chain.
  4. otherwise the caller's per-game rate.
OFS is step 0, ahead of the overrides, because "out for season" is not a week
an override can hand back -- and an override that states a RETURN for him is
a contradiction between the two inputs, so it raises
(check_season_out_override) rather than either input quietly winning.
An override entry that touches the tag's week (out_weeks contains it, it is
the return_week, or out_from falls in it) SUPPRESSES the tag entirely:
Nick's file is the better-informed input (tag_suppressed).

OBSERVED TRUNCATION (for B2's as-of re-simulation)
---------------------------------------------------
Mid-week, the log says what already happened to g1..gn. missed_distribution
takes those outcomes and returns the chain conditioned on them:
  - played some g_j          -> absorbing healthy: 0 more missed;
  - missed g1..gn (n < 3)    -> restart the chain at g_{n+1};
  - missed three or more     -> the chain is spent: 0 more from the tag.
A FRESH tag from a later Yahoo fetch is a new anchor and restarts at g1; the
caller does that by passing the new anchor and no observations.
An O player observed PLAYING g1 is a zero-probability event under the model;
the observation wins and he is healthy.

TAGS -- THE 2026-27 VOCABULARY
------------------------------
Yahoo retired the old designations for 2026-27. The injury set is now
P, Q, D, O, OFS, and only O or OFS may occupy an IL slot. Measured against
the live API on 2026-10-22 (460 players): HEALTHY 390, O 37, Q 30, D 3, and
no GTD, DTD, INJ, IL or IL+ anywhere. Nick ruled on the new set 2026-10-22:

    Q, D, O   drive the chain (config absence_chain), least to most severe
    P         healthy
    OFS       out for season: not a chain at all. A hard out for every
              remaining game, applied by setting his REMAINING PROJECTED GP
              to 0 (effective_projected_gp), so absence_baseline's rate is
              (remaining - 0) / remaining = 1.0 and he misses everything.
              That reuses the hazard instead of adding a special case, and
              it nets against the projection with no double charge.
              MAX_TAG_GAMES DOES NOT APPLY TO IT: that invariant was written
              when every tag was a short-horizon signal, and OFS is the
              first that is not (season_out; missed_distribution refuses it).
    SUSP, NA  no-effect, and LOGGED (NOTE_TAGS). They are not injury
              designations, and the old code mapped both to O -- charging an
              injury-shaped three-game recovery for a suspension, or for a
              player not on an NBA roster at all. Their absence is already
              carried by the baseline hazard, which reads
              (remaining team games - projected_gp): a suspended or
              unrostered player carries a reduced GP, so the hazard charges
              those games automatically, block-shaped, with no tag rule.
              INJURY_OVERRIDES is the backstop when Yahoo's GP has not
              caught up -- which is why each one is named in the build
              output and the report metadata rather than passed over.
    retired   GTD, DTD, INJ, IL, IL+ RAISE, naming the vocabulary change:
              seeing one now means the data source changed.
    anything
    else      RAISES UnmodelledTag. A silent HEALTHY is how Q went
              unmodelled before A2, and how D would halt the 10-26 build.

WHY INJURY_OVERRIDES MATTERS MORE UNDER THIS VOCABULARY
-------------------------------------------------------
A player a week into a six-week injury still shows only O, or even D, and
the chain caps at three games. Measured against the live API 2026-10-22,
free agents that appear in PLAYERLIST, by Yahoo's projected remaining GP:

    HEALTHY   100 players   mean 69.6   range 59-82
    Q           9 players   mean 69.1   range 65-75   <- no discount at all
    O           5 players   mean 64.2   range 55-78   <- about 5 games

So Yahoo's GP partly absorbs an O absence (and the baseline hazard charges
those games), but a Q tag moves it by NOTHING. For a questionable player the
chain's three games are therefore the ENTIRE absence signal in the system,
and a long absence showing as Q is invisible to the engine without an
INJURY_OVERRIDES entry. WEEKLY_WORKFLOW.md says so where that file is
updated.

CALIBRATION (not done; do not guess)
------------------------------------
The chain probabilities are Nick's stated judgement, in config
absence_chain with their provenance. Measuring them from
data/historical/HISTORICAL_PLAYERLOG.json is NOT a measurement waiting to
be taken: the log records is_injured, not the tag that was showing, and the
tags those seasons carried are the retired vocabulary -- so recovering Q and
D from it needs an assumption about how GTD and DTD map onto them. That is
a judgement for Nick (handoff 2026-10-22 sec.5), not this module's to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Sequence

import numpy as np

from . import crn

# Design invariant: a CHAIN tag alone never costs more than this many games.
# OFS is exempt by construction -- it is not a chain (see TAGS above).
MAX_TAG_GAMES = 3

# Out for season: a hard out for every remaining game, carried by the
# baseline hazard at projected GP 0, never by the chain.
SEASON_OUT_TAGS = frozenset({"OFS"})

# Not an absence signal.
NO_EFFECT_TAGS = frozenset({"HEALTHY"})

# No-effect, but named in the build output and the report metadata: not
# injury designations, and the baseline hazard already carries their games
# through projected GP. Nick, 2026-10-22.
NOTE_TAGS = frozenset({"SUSP", "NA"})

# Retired when Yahoo replaced the vocabulary for 2026-27. These RAISE: one
# of them now means the data source changed, which is worth knowing loudly.
RETIRED_TAGS = frozenset({"GTD", "DTD", "INJ", "IL", "IL+"})

# P (probable) is healthy. Nick, 2026-10-19.
TAG_ALIASES: dict = {"P": "HEALTHY"}


def _validate_chain(probs: Sequence[float]) -> None:
    assert len(probs) == MAX_TAG_GAMES, probs
    assert all(0.0 <= p <= 1.0 for p in probs), probs


def chain_play(config: dict = None) -> dict:
    """config absence_chain: tag -> (p1, p2, p3). Missing raises; there is no
    default, and the probabilities are not duplicated in code."""
    if config is None:
        from .data_loader import _LEAGUE_CONFIG as config
    try:
        raw = config["absence_chain"]
    except KeyError:
        raise KeyError("config/league_config.json has no absence_chain; the chain "
                       "probabilities have no built-in default") from None
    out = {}
    for tag, probs in raw.items():
        if tag.startswith("_"):
            continue
        probs = tuple(float(x) for x in probs)
        _validate_chain(probs)
        out[tag.upper()] = probs
    if not out:
        raise KeyError("config/league_config.json absence_chain lists no tags")
    return out


# P(play g_k | missed every earlier game in the chain), k = 1, 2, 3.
CHAIN_PLAY = chain_play()


class UnmodelledTag(ValueError):
    """A Yahoo tag the absence model has no rule for."""


class SeasonOutConflict(ValueError):
    """OFS says the season is over for him; an override says he is coming back."""


def normalised_tag(status) -> str:
    """The tag as the model names it: upper-case, trimmed, aliases applied."""
    s = str(status if status is not None else "HEALTHY").upper().strip() or "HEALTHY"
    return TAG_ALIASES.get(s, s)


def tag_kind(status) -> str:
    """'chain', 'season_out' or 'none'. Anything else RAISES."""
    s = normalised_tag(status)
    if s in CHAIN_PLAY:
        return "chain"
    if s in SEASON_OUT_TAGS:
        return "season_out"
    if s in NO_EFFECT_TAGS or s in NOTE_TAGS:
        return "none"
    if s in RETIRED_TAGS:
        raise UnmodelledTag(
            f"injury tag {status!r} was retired when Yahoo replaced the injury "
            f"vocabulary for 2026-27. The designations are now "
            f"{', '.join(sorted(CHAIN_PLAY) + sorted(SEASON_OUT_TAGS) + ['P']) }, with "
            f"{', '.join(sorted(NOTE_TAGS))} separate and no-effect. Seeing {s} now means "
            "the data source changed: check modules/fetch_injury_statuses.py "
            "(normalize_injury_status) before mapping it to anything.")
    raise UnmodelledTag(
        f"injury tag {status!r} has no absence rule. The 2026-27 designations are "
        f"{', '.join(sorted(CHAIN_PLAY) + sorted(SEASON_OUT_TAGS) + ['P'])}; "
        f"{', '.join(sorted(NOTE_TAGS))} are no-effect. Add it to config "
        "absence_chain (a chain), or to modules/absence.py SEASON_OUT_TAGS, "
        "NO_EFFECT_TAGS, NOTE_TAGS or TAG_ALIASES.")


def chain_tag(status) -> Optional[str]:
    """The chain this tag drives, or None.

    None means NO CHAIN, which is not the same as no absence: OFS returns
    None here and is a season-long out through the baseline hazard
    (season_out, effective_projected_gp). Raises UnmodelledTag for a tag with
    no rule -- a silent HEALTHY is how Q went unmodelled before A2.
    """
    return normalised_tag(status) if tag_kind(status) == "chain" else None


def season_out(status) -> bool:
    """He plays no more games this season (OFS)."""
    return tag_kind(status) == "season_out"


def effective_projected_gp(status, projected_gp) -> float:
    """His pre-season projected GP, or 0 for a season-long out.

    This is the whole of OFS's implementation: at 0 the durability miss rate
    is 1.0, so he misses every remaining game, and his expected misses are
    exactly his remaining games -- with no double charge.
    """
    return 0.0 if season_out(status) else float(projected_gp or 0.0)


def noted_tags(statuses: dict) -> list:
    """['Player (SUSP)', ...] -- the no-effect tags that are not injury
    designations. Not fatal; named so Nick can judge whether an
    INJURY_OVERRIDES entry is warranted (2026-10-22)."""
    out = []
    for name in (statuses or {}):
        if normalised_tag(statuses[name]) in NOTE_TAGS:
            out.append(f"{name} ({str(statuses[name]).strip().upper()})")
    return sorted(out)


def _stated_return(return_week=None, return_date=None, return_games=None) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in
                     (("return_week", return_week), ("return_date", return_date),
                      ("return_games", return_games)) if v)


SEASON_OUT_FLAG = "--allow-season-out-conflict"


def _season_out_conflict_message(lines) -> str:
    return (
        "out-for-season tag against a stated return in config/INJURY_OVERRIDES.json: " +
        "; ".join(lines) + ". One of the two inputs is stale, and nothing here guesses "
        f"which. If Yahoo has not caught up -- a player cleared to return whose tag still "
        f"says OFS -- pass {SEASON_OUT_FLAG}: the OVERRIDE WINS (the better-informed "
        "input, as everywhere else in the precedence chain), the run continues, and the "
        "conflict is recorded in the report metadata and the point-in-time capture. If the "
        "season really is over for him, clear the return from the overrides file instead.")


def season_out_conflict_line(player: str, status, return_week=None, return_date=None,
                             return_games=None) -> str:
    return (f"{player} is tagged {str(status).strip().upper()} but the overrides file returns "
            f"him ({_stated_return(return_week, return_date, return_games)})")


def check_season_out_override(player: str, status, return_week=None,
                              return_date=None, return_games=None) -> None:
    """OFS plus an INJURY_OVERRIDES entry that returns him is a contradiction
    between the two inputs. Raise rather than silently pick one: a plain
    `out_weeks` entry agrees with OFS and is fine, a stated RETURN does not.

    This is the engines' backstop. A build resolves the conflict at its
    boundary instead (resolve_season_out_conflicts), where the escape flag and
    the recording live, so by the time a simulator runs there is nothing left
    to raise about.
    """
    if not season_out(status):
        return
    if return_week is None and return_date is None and not return_games:
        return
    raise SeasonOutConflict(_season_out_conflict_message(
        [season_out_conflict_line(player, status, return_week, return_date, return_games)]))


def season_out_conflicts(statuses: dict, projections) -> list:
    """Every OFS tag an INJURY_OVERRIDES entry states a return for.

    projections: name -> anything carrying return_week / return_date /
    return_games (a PlayerProjection, an MVPlayer). Names resolve through
    PlayerIndex, so a Yahoo respelling cannot hide a conflict.
    """
    from .data_loader import PlayerIndex
    idx = projections if isinstance(projections, PlayerIndex) else PlayerIndex(projections or {})
    out = []
    for name in (statuses or {}):
        if not season_out(statuses[name]):
            continue
        p = idx.get(name)
        if p is None:
            continue
        rw, rd, rg = (getattr(p, "return_week", None), getattr(p, "return_date", None),
                      getattr(p, "return_games", None))
        if rw is None and rd is None and not rg:
            continue
        out.append({
            "player": str(idx.canonical(name) or name),
            "status_key": name,
            "tag": str(statuses[name]).strip().upper(),
            "stated_return": _stated_return(rw, rd, rg),
            "resolution": ("the override wins: the tag was dropped for this run, so "
                           "config/INJURY_OVERRIDES.json governs his absence"),
            "line": season_out_conflict_line(name, statuses[name], rw, rd, rg),
        })
    return sorted(out, key=lambda c: c["player"])


def resolve_season_out_conflicts(statuses: dict, projections, allow: bool = False) -> tuple:
    """(statuses to simulate, conflicts). Raises unless `allow`.

    When allowed, the OFS tag is DROPPED for the run -- replaced by HEALTHY, so
    the overrides file alone decides his absence and the baseline hazard carries
    the rest of his season from his projected GP. Dropping the key instead would
    read as "Yahoo gave no status for him", which is a different fact.
    """
    conflicts = season_out_conflicts(statuses, projections)
    if not conflicts:
        return statuses, []
    if not allow:
        raise SeasonOutConflict(_season_out_conflict_message([c["line"] for c in conflicts]))
    from .data_loader import PlayerIndex
    plain = dict(dict.items(statuses))
    for c in conflicts:
        # replace the key AS STORED, so one spelling does not become two
        plain[c["status_key"]] = "HEALTHY"
    return PlayerIndex(plain), conflicts


def check_tags(statuses: dict, players: Iterable[str]) -> None:
    """Raise once, naming every simulated player whose tag is unmodelled."""
    bad, why = [], []
    for n in players:
        if n not in statuses:
            continue
        try:
            tag_kind(statuses[n])
        except UnmodelledTag as e:
            bad.append(f"{n} ({statuses[n]})")
            why.append(str(e))
    if bad:
        raise UnmodelledTag(
            "no absence rule for these tags: " + ", ".join(sorted(bad)) + ". " + why[0])


class UnresolvedTagName(ValueError):
    """A tag whose player name matches no rostered player."""


def resolve_tags(statuses: dict, rostered: Iterable[str]) -> tuple:
    """(statuses keyed by the ROSTER's spelling, healthy names that matched
    nobody, rostered players with no status).

    Every name goes through data_loader.PlayerIndex -- accents, suffixes and
    Yahoo's initials ("S. Gilgeous-Alexander", 10-05). A NON-HEALTHY tag whose
    name resolves to no rostered player RAISES: dropping it would price that
    player healthy, which is how the 10-21 spelling bug hid. A HEALTHY name
    that matches nobody costs nothing and is returned for the record, as are
    rostered players Yahoo gave no status (a roster file out of sync).
    """
    from .data_loader import PlayerIndex
    roster = PlayerIndex({n: n for n in rostered})
    out = PlayerIndex()
    bad, unmatched, clash = [], [], []
    for name, status in (statuses or {}).items():
        key = roster.canonical(name)
        st = str(status if status is not None else "HEALTHY").upper().strip() or "HEALTHY"
        if key is None:
            (unmatched if st == "HEALTHY" else bad).append(f"{name} ({status})" if st != "HEALTHY" else name)
            continue
        if key in dict.keys(out) and str(dict.__getitem__(out, key)).upper() != st:
            clash.append(f"{key}: {dict.__getitem__(out, key)} vs {status} (from {name})")
        out[key] = status
    if bad or clash:
        msg = []
        if bad:
            msg.append("injury tags for players matching no rostered player: " + ", ".join(sorted(bad)) +
                       ". Either the spelling is beyond data_loader.PlayerIndex (add the case) or "
                       "config/ROSTERS.json is missing the player (sync transactions).")
        if clash:
            msg.append("two Yahoo names resolve to one rostered player with different tags: " +
                       "; ".join(clash))
        raise UnresolvedTagName(" ".join(msg))
    missing = sorted(n for n in dict.keys(roster) if n not in dict.keys(out))
    return out, sorted(unmatched), missing


def missed_distribution(tag: str, observed: Sequence[bool] = ()) -> tuple:
    """P(he misses exactly r MORE games from the tag), r = 0..MAX_TAG_GAMES.

    Derived from CHAIN_PLAY. `observed` is played/missed for g1..gn in order,
    already resolved (B2). With no observations this is the full distribution
    of games missed, the first r games, contiguous.
    """
    if tag not in CHAIN_PLAY:
        raise UnmodelledTag(
            f"{tag!r} is not a chain tag, so it has no games-missed distribution. "
            f"OFS is a season-long out carried by the baseline hazard "
            f"(effective_projected_gp), deliberately exempt from MAX_TAG_GAMES.")
    probs = CHAIN_PLAY[tag]
    _validate_chain(probs)
    n = 0
    for played in observed:
        if played:                          # absorbing: the absence is over
            return (1.0,) + (0.0,) * MAX_TAG_GAMES
        n += 1
    if n >= MAX_TAG_GAMES:                  # chain spent; g4 onward is 1.00
        return (1.0,) + (0.0,) * MAX_TAG_GAMES
    out = [0.0] * (MAX_TAG_GAMES + 1)
    still_out = 1.0
    for r, k in enumerate(range(n, MAX_TAG_GAMES)):
        out[r] = still_out * probs[k]       # plays g_{k+1} after r more misses
        still_out *= 1.0 - probs[k]
    out[MAX_TAG_GAMES - n] += still_out     # missed through g3; g4 is certain
    total = sum(out)
    assert abs(total - 1.0) < 1e-12, (tag, observed, out)
    return tuple(out)


def expected_missed(tag: str, observed: Sequence[bool] = ()) -> float:
    return sum(r * p for r, p in enumerate(missed_distribution(tag, observed)))


def missed_from_uniform(u, tag: str, observed: Sequence[bool] = ()):
    """Inverse CDF: uniform(s) in [0,1) -> games missed. Scalar or ndarray."""
    cdf = np.cumsum(missed_distribution(tag, observed))
    cdf[-1] = 1.0
    k = np.searchsorted(cdf, np.asarray(u, dtype=float), side="right")
    k = np.minimum(k, MAX_TAG_GAMES)
    return int(k) if np.ndim(k) == 0 else k


def keyed_uniforms(seed, player: str, anchor: date, n: int) -> np.ndarray:
    """Common random numbers: n uniforms keyed by (seed, "absence", player,
    anchor), via modules/crn.py -- the one CRN implementation. The anchor
    stands for the tag's week; the iteration is the array position.
    """
    return crn.keyed_uniforms(seed, "absence", player, anchor, n=n)


def team_games_from(anchor: date, team_dates: Iterable[date]) -> list:
    """The team's game dates on or after the anchor, ascending."""
    return sorted(d for d in set(team_dates) if d >= anchor)


def missed_dates(games_from_anchor: Sequence[date], k: int) -> frozenset:
    """The first k of his team's games -- the block he misses."""
    return frozenset(list(games_from_anchor)[:int(k)])


# --- overrides (precedence steps 1-2) ---------------------------------------

def parse_out_from(value) -> Optional[date]:
    """INJURY_OVERRIDES out_from: YYYY-MM-DD or null. A malformed date RAISES
    (return_date's silent ignore is the trap this field does not repeat)."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"INJURY_OVERRIDES out_from {value!r} is not YYYY-MM-DD")


def out_from_applies(d: date, week_start: date, out_from: Optional[date]) -> bool:
    """out_from: unavailable on and after it, within ITS fantasy week.

    True when out_from falls in the week that starts at week_start and d is
    on or after it. The mirror of return_date; together they bound any
    within-week window.
    """
    return out_from is not None and week_start <= out_from <= d


def tag_suppressed(week: int, week_dates: Sequence[date], out_weeks=(),
                   return_week=None, out_from: Optional[date] = None) -> bool:
    """An INJURY_OVERRIDES entry touching the tag's week overrides the tag."""
    if week in set(out_weeks or ()):
        return True
    if return_week is not None and return_week == week:
        return True
    if out_from is not None and week_dates and min(week_dates) <= out_from <= max(week_dates):
        return True
    return False


def override_governs(week, week_dates: Sequence[date], out_weeks=(), return_week=None,
                     out_from: Optional[date] = None) -> bool:
    """An INJURY_OVERRIDES entry touches this week, so it -- not the tag, not
    the baseline -- decides the player's availability in it."""
    return tag_suppressed(week, week_dates, out_weeks, return_week, out_from)


# =============================================================================
# THE BASELINE HAZARD -- untagged absences
# =============================================================================
#
# Tags and INJURY_OVERRIDES cover the absences someone has announced. Every
# other game a player misses -- the rest night, the ankle he turns on
# Wednesday, the six weeks he loses in January -- is this. Without it nobody
# in the simulator ever misses a game (handoff 2026-10-21): +6 started games
# a manager-week, +24% points, and a subsidy to whoever rosters the least
# durable players.
#
# THE LEVEL IS THE PROJECTION, NOT A PARAMETER
#   miss rate per team game = (82 - PRE-SEASON projected GP) / 82
# and the expected misses over a window are that rate times the window's
# team games. 82 is absence_baseline.nba_games_per_team, which counts the
# NBA Cup games the schedule file does not list yet.
#
# The GP comes from data_loader.DurabilityPrior -- a PRE-SEASON snapshot,
# named in config -- and NOT from the live PLAYERLIST, whose GP column stops
# meaning "games of 82 he will play" the moment the season starts and starts
# meaning "games of those remaining", marked down only for a known absence
# (measured 2026-10-22: sd 4.9 pre-season against 2.74 live, and taking it
# live would drop this rate from about 16% to about 1.5%). It is also not
# the roster's maximum projected GP, which was marginal_value's old
# denominator, about 71.
#
# A RATE, not a count of games, is also what makes a mid-season anchor
# right: with 40 games left a pre-season projection of 69 is not "69 of the
# 40 remaining", it is a durability of 69/82 applied to those 40.
#
# THE SHAPE IS MEASURED (config absence_baseline)
# Absences are blocks. A two-state chain over the player's TEAM GAMES:
#   healthy -> absent with probability h per game, the absence short or long
#   (short_share), each game of a short/long absence ends it with
#   1/short_mean_games / 1/long_mean_games. h is solved so the stationary
#   share of games missed is exactly the rate; the chain starts in its
#   stationary distribution, so every game -- the first included -- is
#   missed with probability `rate`.
#
# ONE SEASON PER ITERATION
# The chain runs over the player's whole season, keyed by
# (seed, "baseline", season, player) -- never by week or by who is asking.
# So simulation i's absences are the same blocks in every week that reads
# them: a betting line for week 6 and the season pass's week 6 see the same
# injury, and a long absence in week 5 is still there in week 6. That
# persistence is the dispersion the engine was missing; a hazard redrawn
# each week would fix the level and not the variance.
#
# NO DOUBLE CHARGE (precedence step 4)
# On a game an override or a tag decides, the baseline does not apply.
#   - A TAG is news Yahoo's GP projection has not absorbed: his expected
#     misses are the tag's block plus `rate` times the games it does not
#     cover. The rate is not reduced (handoff 3.4).
#   - An INJURY_OVERRIDES absence is a known absence the GP projection
#     already counts (Nick, 10-21: Knueppel, out weeks 1-2, 70 GP). So the
#     override's expected missed games come OUT of the projection's misses,
#     and the rest are spread over the games no override governs:
#       rate = (miss rate x remaining - override misses) / (remaining - governed)
#     Total expected misses stay exactly miss rate x remaining
#     (override_absence).


@dataclass(frozen=True)
class BaselineParams:
    games_per_team: int
    short_share: float
    short_mean: float
    long_mean: float

    def __post_init__(self):
        if not (0.0 < self.short_share < 1.0):
            raise ValueError(f"absence_baseline.short_share {self.short_share} not in (0, 1)")
        if self.short_mean < 1.0 or self.long_mean < 1.0:
            raise ValueError("absence_baseline means are in games and must be >= 1")
        if int(self.games_per_team) <= 0:
            raise ValueError("absence_baseline.nba_games_per_team must be positive")

    @property
    def mean_length(self) -> float:
        return self.short_share * self.short_mean + (1 - self.short_share) * self.long_mean


def baseline_params(config: dict = None) -> BaselineParams:
    """league_config's absence_baseline. Missing raises: there is no default."""
    if config is None:
        from .data_loader import _LEAGUE_CONFIG as config
    try:
        c = config["absence_baseline"]
        return BaselineParams(int(c["nba_games_per_team"]), float(c["short_share"]),
                              float(c["short_mean_games"]), float(c["long_mean_games"]))
    except KeyError as e:
        raise KeyError(f"config/league_config.json absence_baseline is missing {e}; "
                       "the baseline hazard has no built-in default") from None


def remaining_team_games(team_dates: Iterable[date], anchor: date, params: BaselineParams) -> int:
    """His team's regular-season games from the anchor: scheduled ones on or
    after it, plus the ones the schedule does not list yet."""
    dates = set(team_dates)
    unscheduled = params.games_per_team - len(dates)
    if unscheduled < 0:
        raise ValueError(f"the schedule lists {len(dates)} games for one team, more than "
                         f"absence_baseline.nba_games_per_team ({params.games_per_team})")
    return sum(1 for d in dates if d >= anchor) + unscheduled


def durability_miss_rate(prior_gp: float, params: BaselineParams) -> float:
    """Games missed per team game, from a PRE-SEASON projected GP: the one
    place a player's durability becomes a number.

    (82 - gp) / 82, clamped. A GP above a full season (or a prior that has
    nothing for him and falls back high) is no misses, never a negative rate.
    claude/DURABILITY_BLEND_DESIGN.md replaces this with a posterior that
    learns from the season; everything downstream takes a rate either way.
    """
    full = float(params.games_per_team)
    if full <= 0:
        return 0.0
    return min(1.0, max(0.0, (full - float(prior_gp)) / full))


def baseline_rate(miss_rate: float, remaining: int, override: tuple = (0, 0.0)) -> float:
    """Per-game miss probability on the games no override governs.

    miss_rate is the durability prior (durability_miss_rate), so the expected
    misses over the window are miss_rate x remaining. override = (games
    governed by INJURY_OVERRIDES, expected games those entries take), from
    override_absence; those games come out of the expectation AND out of the
    denominator, so the total stays miss_rate x remaining.
    """
    governed, override_missed = override
    open_games = remaining - governed
    if open_games <= 0:
        return 0.0
    expected = max(0.0, float(miss_rate)) * remaining
    return min(1.0, max(0.0, (expected - override_missed) / open_games))


def override_absence(week_dates: dict, team_dates: Iterable[date], anchor: date,
                     out_weeks=(), return_week=None, return_date: Optional[date] = None,
                     out_from: Optional[date] = None, return_games=None,
                     total_week_games=None) -> tuple:
    """(team games on/after the anchor in weeks an override governs, the
    expected number of those he misses because of it).

    week_dates: {fantasy week: [its dates]} for the whole schedule. Mirrors
    the simulators exactly: out_weeks -> out; out_from -> out on and after
    it within its week; return_date -> out before it; return_games without
    a date -> out with probability 1 - return_games / total_week_games.
    """
    teams = set(team_dates)
    if isinstance(return_date, str):
        return_date = date.fromisoformat(return_date[:10])
    governed, missed = 0, 0.0
    for week, dates in week_dates.items():
        if not dates or not override_governs(week, dates, out_weeks, return_week, out_from):
            continue
        start = min(dates)
        for d in dates:
            if d < anchor or d not in teams:
                continue
            governed += 1
            if (week in set(out_weeks or ()) or out_from_applies(d, start, out_from)
                    or (return_week == week and return_date is not None and d < return_date)):
                missed += 1.0
            elif return_week == week and return_date is None and return_games and total_week_games:
                missed += 1.0 - return_games / total_week_games
    return governed, missed


def _chain(rate: float, params: BaselineParams):
    """(h, short share, q_short, q_long, P(start healthy), P(start short)).

    With mean absence L, the stationary missed share is hL / (1 + hL), so
    h = rate / (L (1 - rate)). That needs h <= 1, i.e. rate <= L / (1 + L)
    (77% at the fitted shape); a rarer, worse projection lengthens both
    absence kinds by the same factor until it is reachable.
    """
    w = params.short_share
    m_s, m_l = params.short_mean, params.long_mean
    L = params.mean_length
    if rate > L / (1.0 + L):
        s = (rate / (1.0 - rate)) / L
        m_s, m_l, L = m_s * s, m_l * s, L * s
    h = min(1.0, rate / (L * (1.0 - rate)))
    p_h = 1.0 - rate
    p_s = rate * w * m_s / L
    return h, w, 1.0 / m_s, 1.0 / m_l, p_h, p_s


def baseline_mask(u: np.ndarray, rate: float, n_games: int, params: BaselineParams) -> np.ndarray:
    """[n, n_games] bool: missed, per simulation, per team game in order.

    u is [n, >= n_games + 1] uniforms: column 0 places the chain at the first
    game, column g + 1 moves it from game g to g + 1. One uniform per step,
    so a different rate re-reads the same numbers.
    """
    n = u.shape[0]
    if u.shape[1] < n_games + 1:
        raise ValueError(f"{u.shape[1]} uniform columns for {n_games} games")
    if rate <= 0.0 or n_games == 0:
        return np.zeros((n, n_games), dtype=bool)
    if rate >= 1.0:
        return np.ones((n, n_games), dtype=bool)
    h, w, q_s, q_l, p_h, p_s = _chain(rate, params)
    hw = h * w
    # one row per game, contiguous: column access on the [n, games] block is
    # what made this slow
    uT = np.ascontiguousarray(u[:, :n_games + 1].T)
    # state: 0 healthy, 1 short absence, 2 long absence
    u0 = uT[0]
    state = np.where(u0 < p_h, 0, np.where(u0 < p_h + p_s, 1, 2)).astype(np.int8)
    out = np.empty((n_games, n), dtype=bool)
    q_end = np.array([0.0, q_s, q_l])
    for g in range(n_games):
        out[g] = state > 0
        ug = uT[g + 1]
        start = np.where(ug < hw, 1, np.where(ug < h, 2, 0)).astype(np.int8)
        stay = np.where(ug < q_end[state], 0, state).astype(np.int8)
        state = np.where(state == 0, start, stay)
    return out.T


class BaselineBlocks:
    """One player's untagged absences over a season, all n simulations.

    team_dates: every scheduled game of his team this season (the chain runs
    over all of them, so its draws do not depend on the anchor). anchor: the
    first day being simulated; only the RATE depends on it.

    miss_rate: his durability as a per-team-game probability
    (durability_miss_rate of a PRE-SEASON projected GP).

    season_out (OFS): he misses every remaining game, overrides included. His
    miss_rate is already 1.0 (effective_projected_gp zeroes his GP first), so
    the mask is all ones; the flag is what tells the callers to skip the
    override gate as well, because "out for season" is not a week an
    INJURY_OVERRIDES entry can hand back (check_season_out_override raises if
    one tries).
    """

    def __init__(self, seed, season: str, player: str, team_dates: Iterable[date],
                 anchor: date, miss_rate: float, n: int, params: BaselineParams,
                 override: tuple = (0, 0.0), season_out: bool = False):
        self.player = player
        self.season_out = bool(season_out)
        self.dates = sorted(set(team_dates))
        self._index = {d: i for i, d in enumerate(self.dates)}
        self.remaining = remaining_team_games(self.dates, anchor, params)
        self.override = override
        self.miss_rate = float(miss_rate)
        self.rate = baseline_rate(miss_rate, self.remaining, override)
        u = crn.keyed_rng(seed, "baseline", season, player).random((int(n), params.games_per_team + 1))
        mask = baseline_mask(u, self.rate, len(self.dates), params)
        self._packed = np.packbits(mask, axis=1)
        self.n = int(n)

    def missed(self, d: date):
        """bool over simulations, or None if his team does not play on d."""
        i = self._index.get(d)
        if i is None:
            return None
        return ((self._packed[:, i >> 3] >> (7 - (i & 7))) & 1).astype(bool)

    def season_mask(self) -> np.ndarray:
        return np.unpackbits(self._packed, axis=1, count=len(self.dates)).astype(bool)
