"""
injured_drop.py -- does a team drop an injured player, or hold him? (task 18b)

claude/INJURED_DROP_DESIGN.md s.3 (Nick, 11-03), as one PURE function that
the roster plan calls at every future window and that advice v2 will call
unchanged:

    decide(team, player, stakes, keep, config) -> Decision (hold | drop, why)

No file is read here and nothing is drawn: the caller passes every number
(tests/test_injured_drop.py pins both by a source check and by repetition).

THE UNIT. Everything is in STAKE UNITS: the change in

        rs_weight x P(regular-season title) + playoff_weight x P(champion)

(2 and 1, Nick 11-03, as the money: $180 and $90). A point scored in week w
is worth

        s_w = (rs_weight x RS leverage_w + playoff_weight x playoff leverage_w)
              x density_w

where the leverages are the CAUSAL ones, P(title | wins week w) - P(title |
loses week w) among the previous run's near-tie iterations (the stakes
title_odds_run writes, schema 3; drop_inputs maps rs_leverage_causal to
WeekStake.rs_leverage -- the all-iteration leverage carries season-long luck
and overstated a point by ~1.4x, HANDOFF_CAUSAL_LEVERAGE_2026-11-12; a
regular-season week has only RS leverage, a bracket week only playoff
leverage) and density_w is
HOW MUCH ONE POINT MOVES THAT WEEK'S WIN CHANCE: the density at zero of his
margin that week, from a normal fit to the pass's own simulated margins,

        density_w = phi(margin_mean / margin_sd) / margin_sd.

THIS IS THE ONE PLACE A POINT -- OR A WIN -- IS PRICED. win_value_parts()
is a week's stake per win, by race; point_value_parts() is that x density_w,
point_value() their sum. The roster plan's 18b costs and the advice's title
term (horizon weeks: win_value_parts x the change in win chance; later weeks:
point_value_parts x points) both go through them (tests pin it by source).

(The builder's choice, task 18b item 4. A close matchup has a high density, a
lopsided one a low density; the leverage says what the week is worth, the
density how much a point can change it.) A week whose leverage is null --
the team never wins, or never loses, it in the pass -- is worth 0 per point:
one point cannot change a result the simulation never sees change.

THE COMPARISON (s.3.2), over the weeks from this window to the last week
the stakes cover (the Cup weeks carry no stake, s.4):
  cost of holding  = sum over the weeks he is OUT (before back_week) of
                     s_w x (stand-in's points_w - his points_w)
                     -- a dead active spot; a midweek return counts his part;
  cost of dropping = sum over the weeks he is BACK of
                     s_w x (his points_w - stand-in's points_w)
                     + the keeper term.
His points carry his projection and his durability (age and health enter
there, through the caller's projection and miss rate).

KEEPERS (s.3.3):
  - his team's top `protected_keepers` (4) by keep chance are NEVER dropped;
  - a keeper CANDIDATE (top `keeper_candidates`, 6) adds keep chance x
    keeper_weight (K) to the cost of dropping, in stake units;
  - LITTLE LEFT TO PLAY FOR: before the playoffs a regular-season title
    chance under rs_little_left (5%); from the playoffs on a playoff title
    chance under playoff_little_left (5%) -- one or the other, never both. Such
    a team holds every keeper candidate.

INERTIA (s.3.4): drop only when
        cost of holding >= (1 + M) x cost of dropping      (the margin)
    and cost of holding -  cost of dropping >= F           (the floor).

value_after_return() is the cost of dropping: what the IL slots are ranked
by (s.3.5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

HOLD, DROP = "hold", "drop"


class StakesError(RuntimeError):
    """A stake the decision needs is missing or malformed."""


# =============================================================================
# the inputs
# =============================================================================

@dataclass(frozen=True)
class Config:
    """league_config.json injured_drop, every key required (from_rules)."""
    rs_weight: float
    playoff_weight: float
    rs_little_left: float
    playoff_little_left: float
    protected_keepers: int
    keeper_candidates: int
    margin: float           # M
    floor: float            # F, stake units
    keeper_weight: float    # K, stake units per unit of keep chance

    def __post_init__(self):
        for k in ("rs_weight", "playoff_weight", "margin", "floor", "keeper_weight"):
            if not (isinstance(getattr(self, k), (int, float)) and getattr(self, k) >= 0):
                raise ValueError(f"injured_drop.{k} must be a number >= 0, not {getattr(self, k)!r}")
        for k in ("rs_little_left", "playoff_little_left"):
            if not (0.0 <= float(getattr(self, k)) <= 1.0):
                raise ValueError(f"injured_drop.{k} is a probability, not {getattr(self, k)!r}")
        if not (1 <= int(self.protected_keepers) <= int(self.keeper_candidates)):
            raise ValueError("injured_drop: need 1 <= protected_keepers <= keeper_candidates")


KEYS = ("rs_weight", "playoff_weight", "rs_little_left", "playoff_little_left",
        "protected_keepers", "keeper_candidates", "margin", "floor", "keeper_weight")


def from_rules() -> Config:
    """The config, from league_config.json injured_drop. A missing key raises
    UnspecifiedRule (league_rule): nothing here has a default."""
    from .data_loader import league_rule
    vals = {k: league_rule("injured_drop", k) for k in KEYS}
    for k in ("protected_keepers", "keeper_candidates"):
        vals[k] = int(vals[k])
    for k in set(KEYS) - {"protected_keepers", "keeper_candidates"}:
        vals[k] = float(vals[k])
    return Config(**vals)


@dataclass(frozen=True)
class WeekStake:
    """One remaining week, for one team."""
    week: int
    rs_leverage: Optional[float]          # a regular-season week; None: never wins / never loses
    playoff_leverage: Optional[float]     # a bracket week; None as above
    margin_mean: float
    margin_sd: float

    def density(self) -> float:
        """How much one point moves the week's win chance: the margin's
        density at zero, normal fit."""
        if not (self.margin_sd and self.margin_sd > 0 and math.isfinite(self.margin_sd)):
            raise StakesError(f"week {self.week}: margin_sd {self.margin_sd!r} gives no density")
        z = float(self.margin_mean) / float(self.margin_sd)
        return math.exp(-0.5 * z * z) / (math.sqrt(2.0 * math.pi) * float(self.margin_sd))


@dataclass(frozen=True)
class TeamStakes:
    """One team's stakes as a window opens.
    regular_season: the window is before the playoffs (its week is a
    regular-season week). rs_title / champion: P(regular-season title) and
    P(champion) from the stakes run. weeks: every week the stakes cover from
    the window on -- a week the decision needs that is not here RAISES."""
    window_week: int
    regular_season: bool
    rs_title: float
    champion: Optional[float]
    weeks: Mapping[int, WeekStake]
    last_week: int                        # the last week with a stake (21: the final)


@dataclass(frozen=True)
class Candidate:
    """An injured player, as the window opens.
    points / standin_points: expected fantasy points per week, his if he stays
    on the roster (0 while out; his part of a midweek-return week) and a
    replacement-level stand-in's, for every week from the window through
    TeamStakes.last_week.
    back_week: the first week he is available from its window (None: not
    this season). The weeks before it are his OUT weeks."""
    name: str
    back_week: Optional[int]
    points: Mapping[int, float]
    standin_points: Mapping[int, float]


@dataclass(frozen=True)
class Decision:
    action: str                 # "hold" | "drop"
    reason: str
    cost_hold: float
    cost_drop: float            # keeper term included
    keeper_term: float
    keep_rank: Optional[int]
    keep_chance: Optional[float]
    little_left: bool
    detail: dict = field(default_factory=dict, compare=False)


# =============================================================================
# the arithmetic
# =============================================================================

def win_value_parts(ws: WeekStake, config: Config) -> tuple:
    """(rs part, playoff part) of the week's stake per WIN, stake units:
    rs_weight x RS leverage, playoff_weight x playoff leverage (the causal
    leverages; a null one is 0)."""
    return (config.rs_weight * float(ws.rs_leverage or 0.0),
            config.playoff_weight * float(ws.playoff_leverage or 0.0))


def point_value_parts(ws: WeekStake, config: Config) -> tuple:
    """(rs part, playoff part) of s_w: stake units per POINT scored this week."""
    rs, po = win_value_parts(ws, config)
    if rs == 0.0 and po == 0.0:
        return 0.0, 0.0
    d = ws.density()
    return rs * d, po * d


def point_value(ws: WeekStake, config: Config) -> float:
    """s_w: stake units per point scored in this week."""
    return sum(point_value_parts(ws, config))


def keep_rank(name: str, keep: Mapping[str, float]) -> tuple:
    """(his rank on his team by keep chance, 1 = most likely kept; his
    chance). Ties go by name, so the rank never depends on dict order."""
    if name not in keep:
        raise KeyError(f"no keep chance for {name}: the decision needs his team's keep chances")
    order = sorted(keep, key=lambda n: (-float(keep[n]), n))
    return order.index(name) + 1, float(keep[name])


def little_left(stakes: TeamStakes, config: Config) -> bool:
    """s.3.3: before the playoffs, the regular-season title under 5%; from the
    playoffs on, the playoff title under 5%. Never both."""
    if stakes.regular_season:
        return float(stakes.rs_title) < config.rs_little_left
    if stakes.champion is None:
        raise StakesError("a playoff window needs the team's playoff title chance (champion)")
    return float(stakes.champion) < config.playoff_little_left


def _weeks(stakes: TeamStakes, player: Candidate) -> list:
    weeks = list(range(int(stakes.window_week), int(stakes.last_week) + 1))
    for w in weeks:
        if w not in player.points or w not in player.standin_points:
            raise KeyError(f"{player.name}: no expected points for week {w}")
    return weeks


def costs(player: Candidate, stakes: TeamStakes, keep: Mapping[str, float],
          config: Config) -> dict:
    """{cost_hold, cost_drop, keeper_term, keep_rank, keep_chance, by_week}."""
    hold = back = 0.0
    by_week = {}
    back_week = player.back_week
    for w in _weeks(stakes, player):
        ws = stakes.weeks.get(w)
        if ws is None:
            raise StakesError(f"week {w} has no stake for this team: the stakes file does not "
                              f"cover it (window {stakes.window_week})")
        s = point_value(ws, config)
        diff = float(player.points[w]) - float(player.standin_points[w])
        if back_week is None or w < back_week:
            hold += s * -diff
        else:
            back += s * diff
        by_week[w] = (s, diff)
    rank, chance = keep_rank(player.name, keep)
    kterm = chance * config.keeper_weight if rank <= config.keeper_candidates else 0.0
    return {"cost_hold": hold, "cost_drop": back + kterm, "keeper_term": kterm,
            "keep_rank": rank, "keep_chance": chance, "by_week": by_week}


def value_after_return(player: Candidate, stakes: TeamStakes, keep: Mapping[str, float],
                       config: Config) -> float:
    """What an IL slot is ranked by (s.3.5): the cost of dropping him."""
    return costs(player, stakes, keep, config)["cost_drop"]


def decide(team: str, player: Candidate, stakes: TeamStakes, keep: Mapping[str, float],
           config: Config) -> Decision:
    """Hold or drop `player`, an injured player of `team` with no IL slot.
    keep: {name: keep chance} for every real player on his team."""
    c = costs(player, stakes, keep, config)
    ll = little_left(stakes, config)
    args = dict(cost_hold=c["cost_hold"], cost_drop=c["cost_drop"], keeper_term=c["keeper_term"],
                keep_rank=c["keep_rank"], keep_chance=c["keep_chance"], little_left=ll,
                detail={"by_week": c["by_week"]})
    rank = c["keep_rank"]
    if rank <= config.protected_keepers:
        return Decision(HOLD, f"top-{config.protected_keepers} keeper ({team}'s no. {rank})", **args)
    if ll and rank <= config.keeper_candidates:
        return Decision(HOLD, f"little left to play for; keeper candidate no. {rank}", **args)
    edge = c["cost_hold"] - c["cost_drop"]
    if c["cost_hold"] < (1.0 + config.margin) * c["cost_drop"]:
        return Decision(HOLD, f"holding costs less than {1.0 + config.margin:g} x dropping", **args)
    if edge < config.floor:
        return Decision(HOLD, f"the edge {edge:.4f} is under the floor {config.floor:g}", **args)
    return Decision(DROP, f"holding costs {edge:.4f} more than dropping", **args)
