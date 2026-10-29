"""
advice.py -- C2 (waivers) and C3 (trades), built on marginal_value (C1).

Design and decisions: claude/C2_C3_DESIGN.md in the project. The short form:

WHY
  In a four-team league with a deep wire, availability is not scarce, fit
  is. "Who plays most" is the same answer for everyone (the cut streamer
  board). What a move is worth to THIS roster is not.

THE BAR -- proportional to the window
  A recommendation must clear BOTH:
    points > 2 SE                      (it is not Monte Carlo noise)
    points >= 10 per week of window    (it is worth acting on)
  A flat 10 would be a real move in one week and 0.67 a week over fifteen,
  and 2 SE on a season-long value is itself 4-16 points, so a flat floor let
  meaningless season-long recs through. Floor = FLOOR_PER_WEEK x weeks.

C2 -- WAIVERS, per manager
  this_week       a PLAN of up to the remaining adds: best (add, drop), apply
                  it, choose the next on the new roster -- two streamers who
                  fill the same Tuesday are worth less together.
  regular_season  the top three (add, drop) pairs.
  Drops never touch the protected keepers, derived THIS run from this run's
  keepability (never a stored list); no keepability -> no drop advice.
  CONTESTED: the add window opens 12:01 Monday and the newsletter lands in
  it, in front of all four managers at once. A player recommended to more
  than one manager is labelled with who else he was recommended to, and
  each rec carries the best alternative -- the section never promises one
  player to four people.

C3 -- TRADES, all six pairs, published automatically
  Gains are measured against NOT trading, a baseline nobody competes on.
  Every trade shows both sides' gains AND the differential: in a four-team
  league a trade is a two-on-two move, and both parties gain on the two
  managers not in it. Nothing calls a trade fair. Eligibility: both sides
  clear the bar. Order: min(gain) -- an ACCEPTABILITY heuristic (the
  reluctant side decides), labelled as such. One trade per pair, four shown,
  and every eligible trade not shown is counted out loud.

AGES
  A still-best recommendation is shown again with its age ("on the table
  since week 3"). Absent two or more weeks, the age restarts.

Nothing here opens a file. Inputs arrive built (marginal_value contexts,
rosters, keepability, standings).
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence

from . import marginal_value as mv
from .data_loader import PlayerIndex, add_budget_for

FLOOR_PER_WEEK = 10.0
SE_MULT = 2.0
SHORTLIST_ADDS = 10
SHORTLIST_DROPS = 3
SHOWN_TRADES = 4
TRADES_RESCORED_PER_PAIR = 20
TWO_FOR_ONE_SEEDS = 10
TWO_FOR_ONE_EXTRA = 6
AGE_RESET_GAP = 2          # absent this many weeks or more -> age restarts
REPLACEMENT_DROP_CANDIDATES = 5


def replacement_k(season: str, managers: Sequence[str]) -> int:
    """How picked-over the wire is assumed to be: one week of everyone's adds.

    add_budget_for(season) x managers, derived -- never a written number
    (the 3-add rule is one offseason old). A season with no add budget has
    no defined replacement level; raise rather than invent one.

    Direction of error (Nick, 10-06): managers rarely use every add, so this
    assumes a MORE picked-over wire than reality -> lower replacement level
    -> higher drop cost -> an engine LESS willing to cut good players.
    That is the safe way to be wrong.
    """
    budget = add_budget_for(season)
    if not budget:
        raise ValueError(f"no weekly add budget for {season}; replacement level "
                         "is undefined -- pass replacement_k explicitly")
    return int(budget) * len(list(managers))


def floor_for(ctx: mv.MVContext) -> float:
    return FLOOR_PER_WEEK * len(ctx.weeks)


def clears(res: mv.MVResult, ctx: mv.MVContext) -> bool:
    return res.points > SE_MULT * res.se and res.points >= floor_for(ctx)


# =============================================================================
# Records
# =============================================================================

@dataclass
class Rec:
    manager: str
    window: str
    add: str
    drop: Optional[str]
    points: float
    se: float
    starts: float
    per_week: float
    floor: float
    step: int = 1
    runner_up: Optional[dict] = None       # best alternative add (different player)
    contested_with: list = field(default_factory=list)
    first_shown_week: Optional[int] = None


@dataclass
class WaiverPlan:
    manager: str
    adds_remaining: int
    this_week: list
    regular_season: list
    protected: list
    protected_asof_week: Optional[int]
    note: str = ""


@dataclass
class Trade:
    manager_a: str
    manager_b: str
    a_sends: list
    b_sends: list
    b_drops: Optional[str]          # forced drop when B receives two for one
    a_drops: Optional[str]
    gain_a: float
    se_a: float
    gain_b: float
    se_b: float
    differential: float             # gain_a - gain_b: who moves ahead of whom
    acceptability: float            # min(gain_a, gain_b): ORDER only, not fairness
    window: str = "regular_season"
    cup: Optional[dict] = None      # {"gain_a","gain_b","differential"} when live
    keepability_delta_a: Optional[float] = None
    keepability_delta_b: Optional[float] = None
    keeper_flags: list = field(default_factory=list)
    involves_commissioner: bool = False
    first_shown_week: Optional[int] = None


@dataclass
class Advice:
    ran: bool
    reason: str
    week: int
    plans: list
    trades: list
    counts: dict
    runtime_s: float
    bar: dict


# =============================================================================
# Protected keepers -- derived, dated, checked
# =============================================================================

def protected_keepers(keeper_watch: Optional[dict], week: int, rosters: dict,
                      keeper_counts: dict) -> tuple[Optional[dict], Optional[int]]:
    """{manager: [names]} = each manager's top-K by THIS run's keepability.

    Raises if keeper_watch is stamped for a different week -- a stale
    keepability table is the rot this replaces. Returns (None, None) when
    there is no keepability at all; callers then give no drop advice.
    """
    if not keeper_watch or not keeper_watch.get("players"):
        return None, None
    stamped = keeper_watch.get("week")
    if stamped != week:
        raise ValueError(f"keeper_watch is for week {stamped}, report is week {week}: "
                         "protected keepers would come from a stale table")
    by_mgr: dict = {m: [] for m in rosters}
    for p in keeper_watch["players"]:
        if p.get("manager") in by_mgr:
            by_mgr[p["manager"]].append((p.get("keepability_score") or 0.0, p["player_name"]))
    out = {}
    for m, scored in by_mgr.items():
        k = int(keeper_counts.get(m, 0))
        on_roster = PlayerIndex({n: n for n in rosters[m]})
        keep = [on_roster[n] for _s, n in sorted(scored, reverse=True) if n in on_roster][:k]
        out[m] = keep
    return out, week


def keepability_index(keeper_watch: Optional[dict]) -> PlayerIndex:
    idx = PlayerIndex()
    for p in (keeper_watch or {}).get("players", []):
        idx[p["player_name"]] = float(p.get("keepability_score") or 0.0)
    return idx


# =============================================================================
# C2 -- waivers
# =============================================================================

def _with_roster(ctx: mv.MVContext, manager: str, roster: list):
    """Temporarily evaluate against `roster` (restored by the caller)."""
    saved = ctx.rosters[manager]
    ctx.rosters[manager] = list(roster)
    return saved


@dataclass
class _Scored:
    """MVResult-shaped: what clears() and _rec() read."""
    points: float
    se: float
    starts: float


REFILL_SCREEN_EXTRA = 8


class Refill:
    """One concept, one implementation: what an OPEN roster slot is worth.

    The value of refilling a slot is the marginal value of the k-th best free
    agent FOR THIS ROSTER with that slot open -- ranked by marginal value, so
    position fit comes through the optimal fill. k = replacement_k().

    Two callers, same function:
      C2  a streaming drop's cost above replacement
              cost(d) = max(0, -MV(roster: add r_k, drop d)), r_k ranked on roster - d
      C3  a two-for-one: the side GIVING two ends one active spot short and
          is credited MV(roster_after: add r_k). (The side taking two has no
          spot to refill -- it is one over the 15 active spots and must drop,
          and the incoming player takes that spot -- so its full drop cost is
          correct.)

    Screen: candidates are each manager's top k + REFILL_SCREEN_EXTRA free
    agents by marginal value against his roster as given. The k-th best of a
    subset can never beat the k-th best of the full set, so the screen can
    only LOWER the refill value: a higher C2 drop cost, a lower C3 credit --
    both err toward missing advice, never toward bad advice. That bound is
    proved, not asserted, which is why it is the only approximation here.

    Rankings are re-done for every roster actually evaluated (cached by the
    exact roster), so the plan's own earlier moves are reflected exactly.
    """

    def __init__(self, short: mv.MVContext, full: mv.MVContext, fas: Sequence[str], k: int):
        self.short, self.full, self.fas, self.k = short, full, list(fas), int(k)
        self._screen: dict = {}
        self._kth: dict = {}
        self._mv: dict = {}

    def _eval(self, ctx, manager, roster, adds=(), drops=()):
        key = (id(ctx), manager, tuple(sorted(roster)), tuple(adds), tuple(drops))
        if key not in self._mv:
            saved = _with_roster(ctx, manager, roster)
            try:
                self._mv[key] = mv.marginal_value(ctx, manager, adds=list(adds), drops=list(drops))
            finally:
                ctx.rosters[manager] = saved
        return self._mv[key]

    def screen(self, manager, roster) -> list:
        if manager not in self._screen:
            ranked = sorted(self.fas, key=lambda f: (-self._eval(self.short, manager, roster, adds=[f]).points, f))
            self._screen[manager] = ranked[: self.k + REFILL_SCREEN_EXTRA]
        return self._screen[manager]

    def kth(self, manager, roster_open, exclude=(), screen_roster=None) -> Optional[str]:
        """k-th best free agent for `roster_open` (a roster with a slot open)."""
        excl = frozenset(exclude) | frozenset(roster_open)
        key = (manager, tuple(sorted(roster_open)), excl)
        if key not in self._kth:
            pool = [f for f in self.screen(manager, screen_roster or roster_open) if f not in excl]
            ranked = sorted(pool, key=lambda f: (-self._eval(self.short, manager, roster_open, adds=[f]).points, f))
            self._kth[key] = ranked[min(self.k, len(ranked)) - 1] if ranked else None
        return self._kth[key]

    def drop_cost(self, manager, roster, d, exclude=(), screen_roster=None):
        """C2: (cost >= 0, se, r_k) of dropping d, above replacement."""
        open_ = [p for p in roster if p != d]
        r_k = self.kth(manager, open_, exclude, screen_roster or roster)
        if r_k is None:
            res = self._eval(self.full, manager, roster, drops=[d])
            return max(0.0, -res.points), res.se, None
        res = self._eval(self.full, manager, roster, adds=[r_k], drops=[d])
        return max(0.0, -res.points), res.se, r_k

    def credit(self, manager, roster_after, exclude=(), screen_roster=None):
        """C3: (gain >= 0, se, r_k) of refilling the open slot in roster_after."""
        r_k = self.kth(manager, roster_after, exclude, screen_roster)
        if r_k is None:
            return 0.0, 0.0, None
        res = self._eval(self.full, manager, roster_after, adds=[r_k])
        return max(0.0, res.points), res.se, r_k


def _best_pairs(short: mv.MVContext, full: mv.MVContext, manager: str,
                roster: list, fas: Sequence[str], drop_pool: Optional[list],
                refill: Optional[Refill] = None, plan_adds=(), base_roster=None) -> list:
    """Full-sim results for the shortlisted (add, drop) pairs, best first.
    With `refill` (the this_week plan, rest-of-season contexts) each drop is
    charged its value above replacement on the CURRENT roster -- exact for
    the plan's own earlier moves; plan_adds are off the wire."""
    s_saved = _with_roster(short, manager, roster)
    f_saved = _with_roster(full, manager, roster)
    try:
        adds = sorted(fas, key=lambda f: -mv.marginal_value(short, manager, adds=[f]).points)
        adds = adds[:SHORTLIST_ADDS]
        if drop_pool is None:
            pairs = [(a, None) for a in adds]
        else:
            pool = list(drop_pool)
            if refill is not None:
                # Screen by value WITHOUT replacement credit (the metric the
                # replacement fix removed, back as a pre-filter): may miss a
                # drop whose position refills easily -> missed advice, never
                # bad advice.
                pool = sorted(pool, key=lambda d: -refill._eval(refill.short, manager, roster,
                                                                drops=[d]).points)
                pool = pool[:REPLACEMENT_DROP_CANDIDATES]

            def drop_cost(d):
                c = mv.marginal_value(short, manager, drops=[d]).points
                if refill is not None:
                    c -= refill.drop_cost(manager, roster, d, plan_adds, base_roster)[0]
                return c
            drops = sorted(pool, key=lambda d: -drop_cost(d))
            pairs = [(a, d) for a in adds for d in drops[:SHORTLIST_DROPS]]
        scored = []
        for a, d in pairs:
            r = mv.marginal_value(full, manager, adds=[a], drops=[d] if d else [])
            if refill is not None and d is not None:
                cost, cse, _rk = refill.drop_cost(manager, roster, d,
                                                  list(plan_adds) + [a], base_roster)
                if cost:
                    r = _Scored(points=round(r.points - cost, 2),
                                se=round((r.se ** 2 + cse ** 2) ** 0.5, 2),
                                starts=r.starts)
            scored.append((r, a, d))
        scored.sort(key=lambda t: -t[0].points)
        return scored
    finally:
        short.rosters[manager] = s_saved
        full.rosters[manager] = f_saved


def _rec(res, ctx, manager, add, drop, step, alt) -> Rec:
    return Rec(manager=manager, window=ctx.window, add=add, drop=drop,
               points=res.points, se=res.se, starts=res.starts,
               per_week=round(res.points / max(1, len(ctx.weeks)), 1),
               floor=floor_for(ctx), step=step,
               runner_up=({"add": alt[1], "drop": alt[2], "points": alt[0].points}
                          if alt else None))


def waiver_plan(manager: str, ctxs: dict, free_agents: Sequence[str],
                protected: Optional[list], adds_remaining: int,
                protected_week: Optional[int], replacement_rank: Optional[int] = None,
                il: Optional[set] = None) -> WaiverPlan:
    """C2 for one manager. ctxs: {window: (short_ctx, full_ctx)}; the key
    "rest_of_season" (regular season from NEXT week) plus replacement_rank
    turn on the drop-above-replacement charge for the this_week plan.

    il: his players in an IL slot. Never a drop: leaving an IL slot frees no
    ACTIVE spot, so (add X, drop an IL player) would put one more player in
    15 active spots (LEAGUE_RULES 2026-27, rules 1-2). Every (add, drop) is
    active-for-active, so every plan keeps the roster's active count."""
    roster = list(ctxs["this_week"][1].rosters[manager])
    note = ""
    prot = PlayerIndex({p: 1 for p in (protected or [])})
    # A rostered player with no projection is valued at 0.0 by C1, so he
    # would always look like the free drop. We cannot know that; never
    # recommend dropping him.
    unknown = set(ctxs["this_week"][1].unprojected)
    if unknown:
        prot = PlayerIndex({**{p: 1 for p in (protected or [])}, **{p: 1 for p in unknown}})
    if il:
        prot = PlayerIndex({**dict(prot), **{p: 1 for p in il}})
    if protected is None:
        drop_pool = None
        note = ("No keepability this week, so no drop advice: values are before "
                "whatever you drop.")
    else:
        drop_pool = [p for p in roster if p not in prot]

    # this_week: sequential plan. Never drop a protected keeper, and never
    # drop someone this same plan just added.
    short, full = ctxs["this_week"]
    refill = None
    if ctxs.get("rest_of_season") and ctxs["rest_of_season"][1].weeks and drop_pool is not None:
        if replacement_rank is None:
            raise ValueError("rest_of_season given without replacement_rank; "
                             "use replacement_k(season, managers)")
        refill = Refill(*ctxs["rest_of_season"], free_agents, replacement_rank)
    plan, cur, pool, added = [], list(roster), list(free_agents), set()
    for step in range(1, max(0, adds_remaining) + 1):
        dp = None if drop_pool is None else [p for p in cur if p not in prot and p not in added]
        scored = _best_pairs(short, full, manager, cur, pool, dp, refill=refill,
                             plan_adds=sorted(added), base_roster=roster)
        if not scored or not clears(scored[0][0], full):
            break
        best = scored[0]
        alt = next((s for s in scored[1:] if s[1] != best[1]), None)
        plan.append(_rec(best[0], full, manager, best[1], best[2], step, alt))
        cur = [p for p in cur if p != best[2]] + [best[1]]
        pool = [f for f in pool if f != best[1]]
        added.add(best[1])

    # regular_season: top three distinct adds on the current roster
    season = []
    if "regular_season" in ctxs and ctxs["regular_season"][1].weeks:
        short, full = ctxs["regular_season"]
        scored = _best_pairs(short, full, manager, roster, list(free_agents), drop_pool)
        seen = set()
        distinct = []
        for s in scored:
            if s[1] not in seen:
                seen.add(s[1])
                distinct.append(s)
        for i, s in enumerate(distinct[:3]):
            if clears(s[0], full):
                alt = distinct[i + 1] if i + 1 < len(distinct) else None
                season.append(_rec(s[0], full, manager, s[1], s[2], i + 1, alt))
    return WaiverPlan(manager=manager, adds_remaining=adds_remaining, this_week=plan,
                      regular_season=season, protected=list(protected or []),
                      protected_asof_week=protected_week, note=note)


def mark_contested(plans: list) -> None:
    """Label every rec whose player is also recommended to another manager
    in the same window. Mutates."""
    for window in ("this_week", "regular_season"):
        holders: dict = {}
        for p in plans:
            for r in getattr(p, window):
                holders.setdefault(r.add, set()).add(p.manager)
        for p in plans:
            for r in getattr(p, window):
                r.contested_with = sorted(holders[r.add] - {p.manager})


# =============================================================================
# C3 -- trades
# =============================================================================

def _least_costly_drop(ctx, manager, exclude) -> Optional[str]:
    pool = [p for p in ctx.rosters[manager] if p not in exclude]
    if not pool:
        return None
    return max(pool, key=lambda d: mv.marginal_value(ctx, manager, drops=[d]).points)


def _side(ctx, mgr, gives, gets, drop):
    return mv.marginal_value(ctx, mgr, adds=list(gets),
                             drops=list(gives) + ([drop] if drop else []))


def find_trades(short: mv.MVContext, full: mv.MVContext, protected: Optional[dict],
                keep_idx: PlayerIndex, commissioner: Optional[str],
                cup_ctx: Optional[mv.MVContext] = None,
                cup_live=lambda a, b: False,
                refill: Optional[Refill] = None, il: Optional[dict] = None) -> tuple[list, dict]:
    """All eligible trades (best first) and the search counts.

    Eligibility: BOTH sides clear the same bar as C2 -- points > 2 SE and
    >= FLOOR_PER_WEEK x weeks (clears()). One bar, stated once.

    Two-for-ones: the side GIVING two ends one active spot short and is
    credited the value of refilling it (Refill.credit -- the same function C2
    charges a drop with). The side TAKING two is one over the 15 active spots
    (LEAGUE_RULES 2026-27, rule 1) and must drop; the incoming player takes
    the spot, so the full drop cost is correct for it.

    IL occupants (il: {manager: names}) are never sent, received or dropped:
    an IL slot holds only an O or OFS player and is fixed for the week, and a
    player leaving one frees no ACTIVE spot (rules 1, 2, 5). With them out,
    a one-for-one keeps both active counts and a two-for-one leaves the taker
    exactly full after his drop -- every trade shown leaves both rosters legal. The credit is
    applied when rescoring, not in the shortlist pass: a two-for-one whose
    giver only clears WITH the credit can be missed -- missed advice, never
    bad advice.
    """
    managers = list(full.rosters)
    prot = {m: PlayerIndex({p: 1 for p in (protected or {}).get(m, [])}) for m in managers}
    on_il = {m: set((il or {}).get(m) or ()) for m in managers}
    considered, candidates = 0, []

    for a, b in itertools.combinations(managers, 2):
        ra = [p for p in short.rosters[a] if p not in on_il[a]]
        rb = [p for p in short.rosters[b] if p not in on_il[b]]
        ones = []
        for x, y in itertools.product(ra, rb):
            ga = _side(short, a, [x], [y], None).points
            gb = _side(short, b, [y], [x], None).points
            considered += 1
            ones.append((min(ga, gb), [x], [y], None, None))
        ones.sort(key=lambda t: -t[0])
        pool = [t for t in ones if t[0] > 0][:TRADES_RESCORED_PER_PAIR]

        # two-for-one, seeded from the best one-for-ones
        for _m, xs, ys, _da, _db in ones[:TWO_FOR_ONE_SEEDS]:
            for giver, taker, give1, get1, extras_from in ((a, b, xs, ys, ra), (b, a, ys, xs, rb)):
                cheap = sorted((p for p in extras_from if p not in give1),
                               key=lambda p: -mv.marginal_value(short, giver, drops=[p]).points)
                for x2 in cheap[:TWO_FOR_ONE_EXTRA]:
                    gives2 = give1 + [x2]
                    excl = (set(get1) | {p for p in short.rosters[taker] if p in prot[taker]}
                            | on_il[taker])
                    d = _least_costly_drop(short, taker, excl)
                    g_giver = _side(short, giver, gives2, get1, None).points
                    g_taker = _side(short, taker, get1, gives2, d).points
                    considered += 1
                    if min(g_giver, g_taker) > 0:
                        if giver == a:
                            pool.append((min(g_giver, g_taker), gives2, get1, None, d))
                        else:
                            pool.append((min(g_giver, g_taker), get1, gives2, d, None))
        pool.sort(key=lambda t: -t[0])
        for _m, a_sends, b_sends, a_drop, b_drop in pool[:TRADES_RESCORED_PER_PAIR]:
            ra_ = _side(full, a, a_sends, b_sends, a_drop)
            rb_ = _side(full, b, b_sends, a_sends, b_drop)
            if refill is not None:
                for side, mgr, gives, gets in (("a", a, a_sends, b_sends), ("b", b, b_sends, a_sends)):
                    if len(gives) > len(gets):     # ends a slot short: refill it
                        after = [p for p in full.rosters[mgr] if p not in gives] + list(gets)
                        c, cse, _rk = refill.credit(mgr, after, screen_roster=full.rosters[mgr])
                        res = ra_ if side == "a" else rb_
                        res = _Scored(points=round(res.points + c, 2),
                                      se=round((res.se ** 2 + cse ** 2) ** 0.5, 2),
                                      starts=res.starts)
                        if side == "a":
                            ra_ = res
                        else:
                            rb_ = res
            if not (clears(ra_, full) and clears(rb_, full)):
                continue
            ka = sum(keep_idx.get(p, 0.0) for p in b_sends) - sum(keep_idx.get(p, 0.0) for p in a_sends)
            flags = [f"{m} gives up keeper-tier {p}" for m, sent in ((a, a_sends), (b, b_sends))
                     for p in sent if p in prot[m]]
            candidates.append(Trade(
                manager_a=a, manager_b=b, a_sends=a_sends, b_sends=b_sends,
                a_drops=a_drop, b_drops=b_drop,
                gain_a=ra_.points, se_a=ra_.se, gain_b=rb_.points, se_b=rb_.se,
                differential=round(ra_.points - rb_.points, 1),
                acceptability=min(ra_.points, rb_.points),
                keepability_delta_a=round(ka, 1) if keep_idx else None,
                keepability_delta_b=round(-ka, 1) if keep_idx else None,
                keeper_flags=flags,
                involves_commissioner=commissioner in (a, b)))

    candidates.sort(key=lambda t: -t.acceptability)
    # de-duplicate identical deals reached two ways
    seen, unique = set(), []
    for t in candidates:
        key = (t.manager_a, t.manager_b, tuple(sorted(t.a_sends)), tuple(sorted(t.b_sends)))
        if key not in seen:
            seen.add(key)
            unique.append(t)

    shown, pairs = [], set()
    for t in unique:
        if (t.manager_a, t.manager_b) in pairs:
            continue
        pairs.add((t.manager_a, t.manager_b))
        shown.append(t)
        if len(shown) == SHOWN_TRADES:
            break
    for t in shown:
        if cup_ctx is not None and cup_ctx.weeks and cup_live(t.manager_a, t.manager_b):
            ca = _side(cup_ctx, t.manager_a, t.a_sends, t.b_sends, t.a_drops)
            cb = _side(cup_ctx, t.manager_b, t.b_sends, t.a_sends, t.b_drops)
            t.cup = {"gain_a": ca.points, "gain_b": cb.points,
                     "differential": round(ca.points - cb.points, 1)}
    counts = {"considered": considered, "eligible": len(unique), "shown": len(shown),
              "not_shown": len(unique) - len(shown),
              "pairs_with_eligible": len({(t.manager_a, t.manager_b) for t in unique})}
    return shown, counts


# =============================================================================
# Ages
# =============================================================================

def trade_key(t: Trade) -> str:
    return "c3:" + "|".join(sorted(t.a_sends + t.b_sends))


def rec_key(r: Rec) -> str:
    return f"c2:{r.manager}:{r.window}:{r.add}"


def stamp_ages(entries: list, keyfn, store: Optional[dict], week: int) -> None:
    """Set first_shown_week from the tracker store and record this week.
    Absent AGE_RESET_GAP weeks or more -> the age restarts."""
    if store is None:
        for e in entries:
            e.first_shown_week = week
        return
    for e in entries:
        k = keyfn(e)
        rec = store.get(k)
        if rec is None or week - rec.get("last_shown_week", week) > AGE_RESET_GAP:
            rec = {"first_shown_week": week, "times_shown": 0}
        if rec.get("last_shown_week") != week:
            rec["times_shown"] = rec.get("times_shown", 0) + 1
        rec["last_shown_week"] = week
        rec.setdefault("first_shown_week", week)
        store[k] = rec
        e.first_shown_week = rec["first_shown_week"]


def to_dict(advice: Advice) -> dict:
    return asdict(advice)
