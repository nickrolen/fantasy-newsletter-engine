"""
advice_v2.py -- advice v2's engine: Monday-window adds and drops (V1 prototype).

claude/ADVICE_V2_DESIGN.md decisions 1-3 and 7; the calibration job is
claude/HANDOFF_ADVICE_V1_WORTH_CHECK_2026-11-05.md. Not wired into the nightly
run, the hub or the newsletter.

    recommend(inputs, manager, settings, weighting) -> Recommendation

PURE. Nothing here opens a file (RETRO_SIM_REQUIREMENTS R2; a source test pins
it): the caller passes the world, the rosters, the projections, the tags and
the stakes. The 2025-26 replay (modules/advice_replay.py) and the live
2026-27 path build the same MondayInputs from different sources.

THE MOVES (decision 2, Monday window only in V1):
    add_drop   add a free agent, drop an unprotected active player
    add_open   add into an open ACTIVE spot (an open IL slot is never one)
    il_add     an O/OFS active player into an open IL slot, then add
    il_swap    drop an unprotected IL occupant, an O/OFS active player into
               his slot, then add
A move is valued from its effective week over two matchups (decision 1), so a
midweek chat move (V2) is the same code with horizon = (next week, the week
after) -- MondayInputs.horizon, not a different engine.

THE UNIT (decision 2.4): startable games under the exact daily fill
(lineup_fill via marginal_value and simulator_betting), O days removed by the
absence model, an overflow game (an 11th healthy player with a game that day,
or no seat his positions fit) worth nothing.

HOW A MOVE IS PRICED (decision 7: screen, then price the finalists):
  1. SCREEN, marginal_value over the two horizon weeks at screen_sims:
     each unprotected drop's points lost; every free agent against the
     roster minus the cheapest drop; the best adds x the cheapest drops.
  2. PRICE the finalists:
     - dwp[k]: the change in the manager's win chance in horizon week k
       against his ACTUAL opponent, simulator_betting.simulate_week_matrix
       with keyed common random numbers (one KeyedDraws per call: the same
       seed and inputs give the same numbers, and an unchanged player's
       draws never move). A 14-day week is one matchup.
     - dT_horizon: sum_k leverage_k x dwp[k], in injured_drop's stake units
       (rs_weight x P(regular-season title) + playoff_weight x P(champion)).
     - dT_later: the title-odds change from the weeks after the horizon,
       sum_w injured_drop.point_value(stake_w) x dpts_w -- the per-manager
       sensitivity of decision 7, read off the stakes the season pass
       already writes; dpts_w from marginal_value over those weeks, ABOVE
       REPLACEMENT (C2's lesson): with A = the roster after the move,
       Ar = A with the add swapped for the replacement-level free agent r
       and B = the roster as it is, dpts_w = max(A_w, Ar_w) - max(B_w, Ar_w).
       A streamer is worth 0 beyond the horizon; a dropped player above
       replacement costs his margin over r; a gem is worth his margin over r.
  3. RANK by a Weighting (decision 1 leaves the combination open; the
     replay calibrates it).
  4. THE LAST ADD: with one add left, a move must clear settings.last_add_bar
     (its insurance value) as well as zero.

PROTECTION (decision 3a): the manager's top `protected` by keep chance are
never a suggested drop (injured_drop.keep_rank orders them, ties by name).
Everyone else is priced, IL occupants included.

IL PLACEMENT IS NOT FREE (decision 2): a player put into an IL slot scores
nothing for the rest of that week (simulator_betting's il_mask). If he is
expected back the week after (no OFS, no override covering it), the next
week's roster has him back and the plan's follow-up drop (the unprotected
active player worth least that week) leaves -- a two-step plan, shown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Mapping, Optional, Sequence

import numpy as np

from . import absence, injured_drop
from . import marginal_value as mv
from . import simulator_betting as sb
from .data_loader import PlayerIndex
from .projections import DEFAULT_WEEKLY_STD_DEV, PlayerProjection, TeamProjections

IL_TAGS = frozenset({"O", "OFS"})          # LEAGUE_RULES 2026-27 IL rule 2
KINDS = ("add_drop", "add_open", "il_add", "il_swap")


# =============================================================================
# The world: what simulator_betting reads off `data`, passed in explicitly
# =============================================================================

class World:
    """A FantasyData stand-in built from explicit inputs (R2).

    simulator_betting reads exactly these off `data`: nba_schedule ({"games":
    [{date, home, away}]}), schedule ({"weeks": [{week, start_date,
    end_date}]}), get_nba_games_for_date, current_week, durability_prior,
    and it caches on __dict__. Nothing else."""

    def __init__(self, nba_schedule: dict, schedule_weeks: Sequence[dict], current_week: int,
                 durability_prior=None):
        games = [dict(g) for g in (nba_schedule or {}).get("games", [])
                 if g.get("home") and g.get("away")]
        self.nba_schedule = {"games": games}
        self.schedule = {"weeks": [dict(w) for w in schedule_weeks]}
        self.current_week = int(current_week)
        self.durability_prior = durability_prior
        self._by_date: dict = {}
        for g in games:
            self._by_date.setdefault(str(g["date"])[:10], []).append(g)
        self._weeks = {int(w["week"]): dict(w) for w in schedule_weeks}

    def get_nba_games_for_date(self, d: date) -> list:
        ds = d.strftime("%Y-%m-%d")
        return [{"date": ds, "home_team": g["home"], "away_team": g["away"]}
                for g in self._by_date.get(ds, [])]

    def week(self, w: int) -> dict:
        if int(w) not in self._weeks:
            raise KeyError(f"week {w} is not in the world's schedule")
        out = dict(self._weeks[int(w)])
        out.pop("matchups", None)
        out["week"] = int(w)
        return out

    def dates(self, w: int) -> list:
        wd = self.week(w)
        d0 = date.fromisoformat(str(wd["start_date"])[:10])
        d1 = date.fromisoformat(str(wd["end_date"])[:10])
        return [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]

    def teams_on(self, d: date) -> frozenset:
        return frozenset(t for g in self._by_date.get(d.isoformat(), [])
                         for t in (g["home"], g["away"]))


# =============================================================================
# Inputs
# =============================================================================

@dataclass(frozen=True)
class Settings:
    seed: int = 20261105
    screen_sims: int = 48       # marginal_value, the screen
    price_sims: int = 1000      # simulate_week_matrix, the finalists
    long_sims: int = 16         # marginal_value over the weeks after the horizon
    adds_screen: int = 25       # free agents kept by the add screen
    drops_screen: int = 6       # cheapest drops kept by the drop screen
    finalists: int = 12         # moves priced in full, per manager
    protected: int = 4          # decision 3a
    replacement_rank: int = 12  # r = the k-th best free agent, k = adds x managers (C2)
    # The insurance value of a last add, in score units (win chance summed over
    # the two weeks), from the 2025-26 replay (V1 result s.4): P(a roster player
    # is newly O by next Monday) 0.575 x the median one-week gain of a top pick
    # 0.056 x a 1-in-4 chance that claiming his replacement early in the chat
    # beats Monday's race (four managers, a deep pool) = 0.008, rounded up.
    # It withheld no Monday pick in the replay; it is for V2's smaller chat moves.
    last_add_bar: float = 0.01


@dataclass(frozen=True)
class Weighting:
    """How the two weekly gains and the title-odds term combine (decision 1).

    mode "wins":  w1 x dwp[0] + w2 x dwp[1] + lam x dT_later / lbar
                  (lbar: the manager's mean stake per win over the horizon,
                  so lam = 1 values a stake unit after the horizon like one
                  inside it);
    mode "title": dT_horizon + lam x dT_later (lam = 1: the title-odds
                  change alone, every week by its leverage);
    mode "wins_penalty": as "wins", but the title term counts only when it is
                  NEGATIVE: it can stop a move that costs long-run value (a
                  keeper cut for games, an injured star dropped before his
                  return) but never buys a "gem" on projection alone. The
                  2025-26 replay's recommendation (V1 result s.3): with the full
                  term, more title weight made both the two-week and the
                  rest-of-season outcomes WORSE, because long-run value is the
                  projection's level times many weeks, and the projection's
                  level error (breakouts, rookies, decline) dominates it."""
    name: str
    mode: str = "wins"
    w1: float = 1.0
    w2: float = 1.0
    lam: float = 0.0

    def score(self, p: "Priced") -> float:
        if self.mode == "title":
            return p.dT_horizon + self.lam * p.dT_later
        if self.mode not in ("wins", "wins_penalty"):
            raise ValueError(f"unknown weighting mode {self.mode!r}")
        t = min(0.0, p.dT_later) if self.mode == "wins_penalty" else p.dT_later
        later = (self.lam * t / p.lbar) if (self.lam and p.lbar) else 0.0
        return self.w1 * p.dwp[0] + self.w2 * p.dwp[1] + later


RECOMMENDED = Weighting("wins + 0.5 title penalty", "wins_penalty", 1, 1, 0.5)

WEIGHTINGS = (
    RECOMMENDED,
    Weighting("wins only", "wins", 1, 1, 0.0),
    Weighting("wins + 0.5 title", "wins", 1, 1, 0.5),
    Weighting("wins + 1 title", "wins", 1, 1, 1.0),
    Weighting("wins + 2 title", "wins", 1, 1, 2.0),
    Weighting("this week only", "wins", 1, 0, 0.0),
    Weighting("title odds only", "title", lam=1.0),
)


@dataclass(frozen=True)
class ManagerState:
    manager: str
    active: tuple                 # on the 15 (13 before 2025-26 week 16) active spots
    il: tuple                     # in IL slots, fixed for the week
    active_capacity: int
    il_capacity: int
    adds_left: int
    keep: Mapping[str, float]     # keep chance for every real player on the roster
    opponents: Mapping[int, str]  # horizon week -> opponent

    def roster(self) -> tuple:
        return tuple(self.active) + tuple(self.il)


@dataclass
class MondayInputs:
    season: str
    horizon: tuple                     # (effective week, the week after)
    world: World
    projections: dict                  # name -> PlayerProjection: rostered and pool
    statuses: dict                     # name -> tag (O, OFS, Q, D, ...); absent = HEALTHY
    managers: dict                     # manager -> ManagerState
    pool: tuple                        # free agents, in a stable order
    anchor: date                       # the tags' anchor: the window's first day
    stakes: dict = field(default_factory=dict)   # manager -> injured_drop.TeamStakes
    drop_config: Optional[injured_drop.Config] = None
    banked: dict = field(default_factory=dict)   # (manager, week) -> points already scored
    weekly_sd: dict = field(default_factory=dict)  # manager -> weekly std dev
    _sims: dict = field(default_factory=dict, repr=False)
    _ctx: dict = field(default_factory=dict, repr=False)

    def status(self, name: str) -> str:
        return absence.normalised_tag(self.statuses.get(name, "HEALTHY"))

    def check(self) -> None:
        """Raise on inputs that would make a silent wrong answer."""
        if len(self.horizon) != 2:
            raise ValueError("the horizon is two matchups")
        seen = {}
        for m, st in self.managers.items():
            if len(st.active) > st.active_capacity:
                raise ValueError(f"{m}: {len(st.active)} active players over {st.active_capacity}")
            if len(st.il) > st.il_capacity:
                raise ValueError(f"{m}: {len(st.il)} in IL slots over {st.il_capacity}")
            for n in st.roster():
                if n in seen:
                    raise ValueError(f"{n} is on {seen[n]}'s and {m}'s rosters")
                seen[n] = m
                if n not in self.projections:
                    raise KeyError(f"{m}'s {n} has no projection")
            for w in self.horizon:
                if w not in st.opponents:
                    raise KeyError(f"{m} has no opponent in week {w}")
        for n in self.pool:
            if n in seen:
                raise ValueError(f"free agent {n} is on {seen[n]}'s roster")
            if n not in self.projections:
                raise KeyError(f"free agent {n} has no projection")


# =============================================================================
# Moves and their prices
# =============================================================================

@dataclass(frozen=True)
class Move:
    manager: str
    kind: str
    add: str
    drop: Optional[str] = None
    to_il: Optional[str] = None
    screen_points: float = 0.0
    screen_starts: float = 0.0

    def describe(self) -> str:
        parts = [f"add {self.add}"]
        if self.drop:
            parts.append(f"drop {self.drop}")
        if self.to_il:
            parts.append(f"{self.to_il} to IL")
        return ", ".join(parts)


@dataclass(frozen=True)
class Priced:
    move: Move
    dwp: tuple              # win-chance change, horizon week 1 and 2
    wp_base: tuple          # the manager's win chance with no move
    dpts: tuple             # mean points change, horizon weeks
    dstarts: tuple          # mean started-games change, horizon weeks
    dT_horizon: float       # stake units
    dT_later: float         # stake units
    dpts_later: float       # points above replacement after the horizon
    lbar: float             # mean stake per win over the horizon (0: no stakes)
    followup_drop: Optional[str] = None
    dpts_later_by_week: tuple = ()    # ((week, points above replacement), ...)

    def reason(self) -> str:
        s = f"{self.dstarts[0] + self.dstarts[1]:+.1f} starts"
        s += f"; win chance {100 * self.dwp[0]:+.1f}% this week, {100 * self.dwp[1]:+.1f}% next"
        if self.lbar:
            s += f"; title {self.dT_horizon + self.dT_later:+.4f}"
        if self.followup_drop:
            s += f"; next week drop {self.followup_drop} when {self.move.to_il} returns"
        return s


@dataclass(frozen=True)
class Recommendation:
    manager: str
    top: Optional[Priced]          # None: no move clears the bar
    ranked: tuple                  # (score, Priced), best first
    weighting: str
    bar: float
    note: str = ""


# =============================================================================
# helpers
# =============================================================================

def protected(state: ManagerState, n: int) -> frozenset:
    """The top n by keep chance (decision 3a), via injured_drop.keep_rank.
    A roster player with no keep chance RAISES (keep_rank)."""
    keep = dict(state.keep)
    out = set()
    for name in state.roster():
        rank, _c = injured_drop.keep_rank(name, keep)
        if rank <= n:
            out.add(name)
    return frozenset(out)


def back_next_week(inputs: MondayInputs, name: str, week: int) -> bool:
    """Expected available from `week`'s window: no OFS, no override covering it."""
    p = inputs.projections[name]
    if absence.season_out(inputs.status(name)):
        return False
    if week in (p.out_weeks or []):
        return False
    if p.return_week is not None and p.return_week > week:
        return False
    return True


def _mv_ctx(inputs: MondayInputs, weeks: Sequence[int], sims: int, seed: int):
    """A marginal_value context from the horizon's first week through the last
    of `weeks`, every relevant player in it. It always STARTS at the horizon:
    marginal_value anchors the tag chains and the baseline hazard at a
    context's first day, so a context of later weeks alone would charge a
    Monday O tag's games in a later week. Callers read the weeks they want
    off roster_totals' by_week."""
    span = list(range(int(inputs.horizon[0]), max(int(max(weeks)), int(inputs.horizon[1])) + 1))
    ck = (tuple(span), sims, seed)
    hit = inputs._ctx.get(ck)
    if hit is not None:
        return hit
    names = list(dict.fromkeys([n for st in inputs.managers.values() for n in st.roster()]
                               + list(inputs.pool)))
    rosters = {m: list(st.active) for m, st in inputs.managers.items()}
    ctx = mv.build_context({n: inputs.projections[n] for n in names}, rosters,
                           inputs.world.nba_schedule, inputs.world.schedule["weeks"],
                           "this_week", span[0] - 1, injury_statuses=inputs.statuses,
                           extra_players=names, durability_prior=inputs.world.durability_prior,
                           sims=sims, seed=seed, season=inputs.season)
    ctx.weeks = span
    ctx.days = [(d, w, inputs.world.teams_on(d)) for w in span for d in inputs.world.dates(w)]
    if ctx.days and ctx.days[0][0] != inputs.anchor:
        raise ValueError(f"the horizon starts {ctx.days[0][0]}, not at the tags' anchor "
                         f"{inputs.anchor}: a chat move (V2) must pass its own anchor")
    inputs._ctx[ck] = ctx
    return ctx


def _totals(ctx, roster) -> tuple:
    pts, starts, by_week = mv.roster_totals(ctx, list(roster))
    return float(pts.mean()), float(starts.mean()), {w: float(np.mean(v)) for w, v in by_week.items()}


def replacement(inputs: MondayInputs, settings: Settings) -> Optional[str]:
    """r: the replacement_rank-th best healthy free agent by expected points
    per team game (effective FPPG x (1 - his durability miss rate))."""
    params = absence.baseline_params()
    def val(n):
        p = inputs.projections[n]
        rate = absence.durability_miss_rate(absence.effective_projected_gp(
            inputs.status(n), p.projected_gp), params)
        return p.effective_fppg * (1.0 - rate)
    healthy = [n for n in inputs.pool if inputs.status(n) not in IL_TAGS]
    if not healthy:
        return None
    ranked = sorted(healthy, key=lambda n: (-val(n), n))
    return ranked[min(settings.replacement_rank, len(ranked)) - 1]


# =============================================================================
# 1. The screen
# =============================================================================

def candidate_moves(inputs: MondayInputs, manager: str, settings: Settings) -> list:
    """Every Monday-window move worth pricing, best screen value first."""
    st = inputs.managers[manager]
    prot = protected(st, settings.protected)
    ctx = _mv_ctx(inputs, inputs.horizon, settings.screen_sims, settings.seed)
    R = tuple(st.active)
    base_p, base_s, _ = _totals(ctx, R)

    def gain(roster):
        p, s, _ = _totals(ctx, roster)
        return p - base_p, s - base_s

    moves: list = []
    droppable = [n for n in R if n not in prot]
    dcost = {d: -gain([n for n in R if n != d])[0] for d in droppable}
    drops = sorted(droppable, key=lambda d: (dcost[d], d))[:settings.drops_screen]
    pool = [n for n in inputs.pool]

    def best_adds(against):
        bp, _bs, _ = _totals(ctx, against)
        vals = {}
        for f in pool:
            p, s, _ = _totals(ctx, list(against) + [f])
            vals[f] = (p - bp, s)
        return sorted(pool, key=lambda f: (-vals[f][0], f))[:settings.adds_screen]

    if drops:
        d0 = drops[0]
        adds = best_adds([n for n in R if n != d0])
        for d in drops:
            rest = [n for n in R if n != d]
            for f in adds:
                p, s = gain(rest + [f])
                moves.append(Move(manager, "add_drop", f, drop=d, screen_points=p, screen_starts=s))
    if len(R) < st.active_capacity:                      # an open ACTIVE spot only
        for f in best_adds(list(R)):
            p, s = gain(list(R) + [f])
            moves.append(Move(manager, "add_open", f, screen_points=p, screen_starts=s))
    newly_out = [n for n in R if inputs.status(n) in IL_TAGS]
    if newly_out and len(R) >= st.active_capacity:
        for pl in newly_out:
            rest = [n for n in R if n != pl]
            adds = best_adds(rest)
            if len(st.il) < st.il_capacity:
                for f in adds:
                    p, s = gain(rest + [f])
                    moves.append(Move(manager, "il_add", f, to_il=pl, screen_points=p, screen_starts=s))
            else:
                for x in st.il:
                    if x in prot:
                        continue
                    for f in adds:
                        p, s = gain(rest + [f])
                        moves.append(Move(manager, "il_swap", f, drop=x, to_il=pl,
                                          screen_points=p, screen_starts=s))
    moves.sort(key=lambda mo: (-mo.screen_points, mo.kind, mo.add, mo.drop or "", mo.to_il or ""))
    return moves


def finalists(moves: Sequence[Move], settings: Settings) -> list:
    """The best `finalists` by screen value, plus the best move of every kind
    (so an IL move is always priced when one exists)."""
    out = list(moves[:settings.finalists])
    for k in KINDS:
        best = next((mo for mo in moves if mo.kind == k), None)
        if best is not None and best not in out:
            out.append(best)
    return out


# =============================================================================
# 2. Pricing
# =============================================================================

def week_roster(inputs: MondayInputs, st: ManagerState, move: Optional[Move], k: int,
                followup: Optional[str]) -> tuple:
    """(players on the roster, players in IL slots) in horizon week k."""
    players = set(st.roster())
    il = set(st.il)
    if move is not None:
        players.add(move.add)
        if move.drop:
            players.discard(move.drop)
            il.discard(move.drop)
        if move.to_il:
            il.add(move.to_il)
        if k == 1 and move.to_il and followup is not None:
            il.discard(move.to_il)
            players.discard(followup)
    return frozenset(players), frozenset(il)


def _scores(inputs: MondayInputs, manager: str, players: frozenset, il: frozenset, week: int,
            settings: Settings) -> tuple:
    key = (manager, players, il, week, settings.price_sims)
    hit = inputs._sims.get(key)
    if hit is not None:
        return hit
    tp = {manager: TeamProjections(manager, {n: inputs.projections[n] for n in sorted(players)},
                                   weekly_std_dev=float(inputs.weekly_sd.get(manager,
                                                                             DEFAULT_WEEKLY_STD_DEV)))}
    draws = sb.KeyedDraws(settings.seed, settings.price_sims)
    res = sb.simulate_week_matrix(inputs.world, tp, inputs.world.week(week), inputs.statuses, draws,
                                  tag_anchor=inputs.anchor, managers=[manager],
                                  il_mask={manager: set(il)})[manager]
    out = (res["score"] + float(inputs.banked.get((manager, week), 0.0)), res["games"])
    inputs._sims[key] = out
    return out


def _win(mine: np.ndarray, theirs: np.ndarray) -> float:
    return float(np.mean(mine > theirs) + 0.5 * np.mean(mine == theirs))


def _leverage(inputs: MondayInputs, manager: str, week: int) -> float:
    ts = inputs.stakes.get(manager)
    if ts is None or inputs.drop_config is None:
        return 0.0
    ws = ts.weeks.get(week)
    if ws is None:
        return 0.0
    c = inputs.drop_config
    return c.rs_weight * float(ws.rs_leverage or 0.0) + c.playoff_weight * float(ws.playoff_leverage or 0.0)


def followup_drop(inputs: MondayInputs, manager: str, move: Move, settings: Settings) -> Optional[str]:
    """Next week's drop when the IL'd player returns: the unprotected active
    player (the add included) worth least from next week through the last
    week the stakes cover (marginal_value; next week alone without stakes),
    so the plan never cuts a long-term asset to save one week. None if he is
    not back next week."""
    if not move.to_il or not back_next_week(inputs, move.to_il, inputs.horizon[1]):
        return None
    st = inputs.managers[manager]
    prot = protected(st, settings.protected)
    players, il = week_roster(inputs, st, move, 0, None)
    active_next = [n for n in players if n not in il] + [move.to_il]
    weeks = [inputs.horizon[1]] + _later_weeks(inputs, manager)
    sims = settings.long_sims if len(weeks) > 1 else settings.screen_sims
    ctx = _mv_ctx(inputs, weeks, sims, settings.seed)

    def value(roster):
        bw = _totals(ctx, roster)[2]
        return sum(bw.get(w, 0.0) for w in weeks)

    bp = value(active_next)
    cands = [n for n in active_next if n not in prot and n != move.to_il]
    if not cands:
        return None
    return min(cands, key=lambda n: (bp - value([x for x in active_next if x != n]), n))


def _later_weeks(inputs: MondayInputs, manager: str) -> list:
    ts = inputs.stakes.get(manager)
    if ts is None:
        return []
    return [w for w in range(inputs.horizon[1] + 1, int(ts.last_week) + 1) if w in ts.weeks]


def price(inputs: MondayInputs, manager: str, moves: Sequence[Move], settings: Settings) -> list:
    st = inputs.managers[manager]
    base = [week_roster(inputs, st, None, k, None) for k in (0, 1)]
    opp = [week_roster(inputs, inputs.managers[st.opponents[w]], None, k, None)
           for k, w in enumerate(inputs.horizon)]
    base_sc = [_scores(inputs, manager, *base[k], w, settings) for k, w in enumerate(inputs.horizon)]
    opp_sc = [_scores(inputs, st.opponents[w], *opp[k], w, settings)[0]
              for k, w in enumerate(inputs.horizon)]
    wp_base = tuple(_win(base_sc[k][0], opp_sc[k]) for k in (0, 1))
    levs = [_leverage(inputs, manager, w) for w in inputs.horizon]
    lbar = float(np.mean(levs)) if any(levs) else 0.0

    later = _later_weeks(inputs, manager)
    r = replacement(inputs, settings) if later else None
    lctx = _mv_ctx(inputs, later, settings.long_sims, settings.seed) if later else None
    R_all = list(st.roster())

    out = []
    for mo in moves:
        fu = followup_drop(inputs, manager, mo, settings) if mo.to_il else None
        dwp, dpts, dst = [], [], []
        for k, w in enumerate(inputs.horizon):
            players, il = week_roster(inputs, st, mo, k, fu)
            sc, games = _scores(inputs, manager, players, il, w, settings)
            dwp.append(_win(sc, opp_sc[k]) - wp_base[k])
            dpts.append(float(np.mean(sc - base_sc[k][0])))
            dst.append(float(np.mean(games - base_sc[k][1])))
        dT_h = sum(levs[k] * dwp[k] for k in (0, 1))
        dT_l, dpl, by_w = 0.0, 0.0, []
        if later and r is not None:
            gone = {x for x in (mo.drop, fu) if x}
            A = [n for n in R_all if n not in gone] + ([mo.add] if mo.add not in gone else [])
            Ar = [n for n in R_all if n not in gone] + ([r] if r not in R_all else [])
            _p, _s, a_w = _totals(lctx, A)
            _p, _s, ar_w = _totals(lctx, Ar)
            _p, _s, b_w = _totals(lctx, R_all)
            ts = inputs.stakes[manager]
            for w in later:
                d = max(a_w.get(w, 0.0), ar_w.get(w, 0.0)) - max(b_w.get(w, 0.0), ar_w.get(w, 0.0))
                dpl += d
                by_w.append((w, round(d, 3)))
                dT_l += injured_drop.point_value(ts.weeks[w], inputs.drop_config) * d
        out.append(Priced(mo, tuple(dwp), wp_base, tuple(dpts), tuple(dst), dT_h, dT_l, dpl, lbar, fu,
                          tuple(by_w)))
    return out


# =============================================================================
# 3. Ranking
# =============================================================================

def recommend(inputs: MondayInputs, manager: str, settings: Settings = Settings(),
              weighting: Weighting = RECOMMENDED, priced: Optional[Sequence[Priced]] = None
              ) -> Recommendation:
    """The manager's best Monday move under `weighting`, or none.

    A move must score above 0 (better than standing pat); with one add left
    it must also clear settings.last_add_bar (decision 2: the last add's
    insurance value). Pass `priced` to re-rank without re-pricing."""
    st = inputs.managers[manager]
    if st.adds_left <= 0:
        return Recommendation(manager, None, (), weighting.name, math.inf, "no adds left")
    if priced is None:
        priced = price(inputs, manager, finalists(candidate_moves(inputs, manager, settings), settings),
                       settings)
    prot = protected(st, settings.protected)
    for p in priced:
        if p.move.drop in prot or p.followup_drop in prot:
            raise AssertionError(f"{p.move.describe()}: drops a protected keeper")
    ranked = tuple(sorted(((weighting.score(p), p) for p in priced),
                          key=lambda t: (-t[0], t[1].move.kind, t[1].move.add, t[1].move.drop or "")))
    bar = max(0.0, settings.last_add_bar) if st.adds_left == 1 else 0.0
    top = ranked[0][1] if ranked and ranked[0][0] > bar else None
    note = "" if top is not None else ("nothing clears the last add's bar" if st.adds_left == 1
                                       else "standing pat beats every move")
    return Recommendation(manager, top, ranked, weighting.name, bar, note)


# =============================================================================
# The simple rules the replay compares against (decision 6)
# =============================================================================

def _healthy_pool(inputs: MondayInputs) -> list:
    return [n for n in inputs.pool if inputs.status(n) not in IL_TAGS]


def most_games(inputs: MondayInputs, manager: str, settings: Settings,
               drop: Optional[str] = None) -> Optional[Move]:
    """'Add the most games': the free agent with the most startable games
    this week and next (ties: higher projection); the drop is the unprotected
    active player with the fewest (ties: lower projection) unless `drop` is
    given. No move unless it gains startable games."""
    st = inputs.managers[manager]
    prot = protected(st, settings.protected)
    ctx = _mv_ctx(inputs, inputs.horizon, settings.screen_sims, settings.seed)
    R = list(st.active)
    _bp, bs, _ = _totals(ctx, R)
    open_spot = len(R) < st.active_capacity
    if drop is None and not open_spot:
        cands = [n for n in R if n not in prot]
        if not cands:
            return None
        lost = {d: bs - _totals(ctx, [n for n in R if n != d])[1] for d in cands}
        drop = min(cands, key=lambda d: (round(lost[d], 6), inputs.projections[d].effective_fppg, d))
    rest = [n for n in R if n != drop] if drop else R
    _rp, rs, _ = _totals(ctx, rest)
    best, best_key = None, None
    for f in _healthy_pool(inputs):
        s = _totals(ctx, rest + [f])[1] - rs
        k = (round(s, 6), inputs.projections[f].effective_fppg)
        if best_key is None or k > best_key or (k == best_key and f < best):
            best, best_key = f, k
    if best is None:
        return None
    p, s, _ = _totals(ctx, rest + [best])
    if s - bs <= 0:
        return None
    return Move(manager, "add_drop" if drop else "add_open", best, drop=drop,
                screen_points=p - _bp, screen_starts=s - bs)


def highest_projection(inputs: MondayInputs, manager: str, settings: Settings,
                       drop: Optional[str] = None) -> Optional[Move]:
    """'Add the highest projection': the healthy free agent with the highest
    point-in-time projection; the drop is the unprotected active player with
    the lowest, unless `drop` is given. No move unless the add projects higher."""
    st = inputs.managers[manager]
    prot = protected(st, settings.protected)
    R = list(st.active)
    open_spot = len(R) < st.active_capacity
    proj = lambda n: inputs.projections[n].effective_fppg
    if drop is None and not open_spot:
        cands = [n for n in R if n not in prot]
        if not cands:
            return None
        drop = min(cands, key=lambda d: (proj(d), d))
    pool = _healthy_pool(inputs)
    if not pool:
        return None
    add = max(pool, key=lambda f: (proj(f), [-ord(c) for c in f]))
    if drop and proj(add) <= proj(drop):
        return None
    ctx = _mv_ctx(inputs, inputs.horizon, settings.screen_sims, settings.seed)
    bp, bs, _ = _totals(ctx, R)
    rest = [n for n in R if n != drop] if drop else R
    p, s, _ = _totals(ctx, rest + [add])
    return Move(manager, "add_drop" if drop else "add_open", add, drop=drop,
                screen_points=p - bp, screen_starts=s - bs)


def engine_drop(rec: Recommendation, moves: Sequence[Move]) -> Optional[str]:
    """The drop the common-drop variant gives the simple rules: the engine's
    own add/drop drop, else its cheapest screened drop."""
    if rec.top is not None and rec.top.move.kind == "add_drop":
        return rec.top.move.drop
    for _s, p in rec.ranked:
        if p.move.kind == "add_drop":
            return p.move.drop
    return next((mo.drop for mo in moves if mo.kind == "add_drop"), None)
