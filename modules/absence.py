"""
absence.py -- A2, the absence model. The one implementation.

simulator_betting (and through simulate_week_hifi the playoff and Cup
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

import hashlib
from datetime import date
from typing import Iterable, Optional, Sequence

import numpy as np

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
    """Common random numbers: n uniforms keyed by (seed, player, anchor).

    Not by iteration order and not from a shared stream -- asking about
    another player can never move this one's absence (C1_DESIGN CRN rule).
    The anchor stands for the tag's week.
    """
    h = hashlib.blake2b(f"{seed}|absence|{player}|{anchor.isoformat()}".encode(),
                        digest_size=8).digest()
    return np.random.default_rng(int.from_bytes(h, "little")).random(n)


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
