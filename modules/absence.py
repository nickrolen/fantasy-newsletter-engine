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
Each tag is an absorbing chain -- once he plays, the absence is over:

            P(play g1)   P(play g2 | missed g1)   P(play g3 | missed g1,g2)   g4+
    O          0.00             0.50                      0.75                1.00
    GTD        0.60             0.55                      0.75                1.00

GTD's g2 is LOWER than its g1 on purpose: a questionable player who then
actually sat is in worse shape than the tag said.

These six numbers (five free; O's g1 is the definition of the tag) are NICK'S
STATED JUDGEMENT, approved 2026-10-19. THEY ARE NOT MEASURED. See CALIBRATION.

THE THREE-GAME CAP IS A DESIGN INVARIANT, NOT A MEDICAL CLAIM
--------------------------------------------------------------
An absence longer than three games is a KNOWN absence and belongs in
INJURY_OVERRIDES. The two inputs partition the space, so a tag alone never
costs more than MAX_TAG_GAMES games.

ONE DRAW, NOT A WALK
--------------------
The chain collapses to a distribution over k = games missed, and the missed
games are always the FIRST k, contiguous. So: draw k once per (simulation,
player, tag), mark his first k team games out. Blocks by construction, no
state carried across days. The distribution is DERIVED from the chain in
code (missed_distribution) -- never typed in a second time.

PRECEDENCE (callers implement steps 1-2 and 4; this module owns 3)
------------------------------------------------------------------
  1. INJURY_OVERRIDES out_weeks / out_from -> out. The tag does not apply.
  2. return_date in return_week            -> out before the date.
  3. otherwise a GTD/O tag                  -> the chain.
  4. otherwise the caller's per-game rate.
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

TAGS
----
GTD and O drive the chain. HEALTHY, INJ, IL and IL+ are explicitly no-effect
(INJ: "has a tag, expected to play" -- INJURY_OVERRIDES carries real outs;
IL/IL+ are roster slots, not designations). ANY OTHER TAG RAISES
UnmodelledTag. Yahoo now returns Q (questionable) in place of GTD and P
(probable); the old code silently treated both as healthy. Nick mapped them
2026-10-19: Q -> the GTD chain, P -> healthy (TAG_ALIASES).

CALIBRATION (not done; do not guess)
------------------------------------
data/historical/HISTORICAL_PLAYERLOG.json (87,181 daily rows, is_injured and
had_game) and claude/ABSENCE_PROFILES_REFERENCE.json (82 players classified
by block structure) make the block lengths after a tag recoverable. Measure
P(play g_k | missed g1..g_{k-1}) by tag from those and replace CHAIN_PLAY.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional, Sequence

import numpy as np

from . import crn

# Nick's stated judgement, approved 2026-10-19. NOT MEASURED -- see CALIBRATION.
# P(play g_k | missed every earlier game in the chain), k = 1, 2, 3.
CHAIN_PLAY = {
    "O":   (0.00, 0.50, 0.75),
    "GTD": (0.60, 0.55, 0.75),
}

# Design invariant: a tag alone never costs more than this many games.
MAX_TAG_GAMES = 3

# Tags that are explicitly not an absence signal.
NO_EFFECT_TAGS = frozenset({"HEALTHY", "INJ", "IL", "IL+"})

# Yahoo tag -> chain. Nick, 2026-10-19: Yahoo replaced "GTD" with "Q"
# (questionable) and added "P" (probable), which is healthy. "O" is unchanged.
# Anything not listed here or below (e.g. DTD) still raises -- add it here.
TAG_ALIASES: dict = {"Q": "GTD", "P": "HEALTHY"}


class UnmodelledTag(ValueError):
    """A Yahoo tag the absence model has no rule for."""


def chain_tag(status) -> Optional[str]:
    """'GTD' or 'O' if the tag drives the chain, None if it is no-effect.

    Raises UnmodelledTag for anything else -- a silent HEALTHY is how Q tags
    went unmodelled before A2.
    """
    s = str(status if status is not None else "HEALTHY").upper().strip() or "HEALTHY"
    s = TAG_ALIASES.get(s, s)
    if s in CHAIN_PLAY:
        return s
    if s in NO_EFFECT_TAGS:
        return None
    raise UnmodelledTag(
        f"injury tag {status!r} has no absence rule. Add it to "
        f"modules/absence.py TAG_ALIASES (e.g. 'Q': 'GTD'), or to NO_EFFECT_TAGS.")


def check_tags(statuses: dict, players: Iterable[str]) -> None:
    """Raise once, naming every simulated player whose tag is unmodelled."""
    bad = []
    for n in players:
        if n not in statuses:
            continue
        try:
            chain_tag(statuses[n])
        except UnmodelledTag:
            bad.append(f"{n} ({statuses[n]})")
    if bad:
        raise UnmodelledTag(
            "no absence rule for these tags: " + ", ".join(sorted(bad)) +
            ". Map them in modules/absence.py TAG_ALIASES.")


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


def _validate_chain(probs: Sequence[float]) -> None:
    assert len(probs) == MAX_TAG_GAMES, probs
    assert all(0.0 <= p <= 1.0 for p in probs), probs


def missed_distribution(tag: str, observed: Sequence[bool] = ()) -> tuple:
    """P(he misses exactly r MORE games from the tag), r = 0..MAX_TAG_GAMES.

    Derived from CHAIN_PLAY. `observed` is played/missed for g1..gn in order,
    already resolved (B2). With no observations this is the full distribution
    of games missed, the first r games, contiguous.
    """
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
#   rate = (remaining team games - projected_gp) / remaining team games
# player_proj_GP is Yahoo's "Remaining Games (proj)" (fetch_playerlist), so
# the denominator is his team's REMAINING games from the anchor -- not 82,
# and not the roster's maximum projected GP (marginal_value's old
# denominator, about 71). Remaining counts the NBA Cup games the schedule
# file does not list yet (absence_baseline.nba_games_per_team).
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
#       rate = (remaining - gp - override misses) / (remaining - governed games)
#     Total expected misses stay exactly remaining - gp (override_absence).


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


def baseline_rate(projected_gp: float, remaining: int, override: tuple = (0, 0.0)) -> float:
    """Per-game miss probability on the games no override governs.

    override = (games governed by INJURY_OVERRIDES, expected games those
    entries take), from override_absence. A projection above the remaining
    games (a PLAYERLIST a few days stale) is no misses, never a negative rate.
    """
    governed, override_missed = override
    open_games = remaining - governed
    if open_games <= 0:
        return 0.0
    return min(1.0, max(0.0, (remaining - float(projected_gp) - override_missed) / open_games))


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
    """

    def __init__(self, seed, season: str, player: str, team_dates: Iterable[date],
                 anchor: date, projected_gp: float, n: int, params: BaselineParams,
                 override: tuple = (0, 0.0)):
        self.player = player
        self.dates = sorted(set(team_dates))
        self._index = {d: i for i, d in enumerate(self.dates)}
        self.remaining = remaining_team_games(self.dates, anchor, params)
        self.override = override
        self.rate = baseline_rate(projected_gp, self.remaining, override)
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
