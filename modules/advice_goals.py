"""
advice_goals.py -- Advice goals: what the manager is playing for
(claude/HANDOFF_ADVICE_GOALS_2026-11-24.md; Nick's 5D_NOTES item 15).

STATUS (2026-11-25, the builder's pause for Nick's mock answers): the engine
pieces below are built and checked on the synthetic league; NOTHING CALLS
THIS MODULE YET. It is not in the nightly, not in advice_live.run_step and not
in the hub, so a run today is exactly as before. Wiring (the "goals" key of
advice_latest.json, the lazy hub parts, the run row's soft failure) comes
after Nick's answers (handoff Part C.1, C.6, C.7 and Part D).

PURE, like advice_v2: nothing here opens a file. The caller passes the
MondayInputs (advice_live.build), every week's opponent and tie value, and the
league config.

THE GOALS (each one's definition in code is its `target`):
    balanced   advice_v2.RECOMMENDED, unchanged (the default). Its plan is
               advice_v2.plan_for's; this module never re-ranks it.
    next       "Wk N": sum of the win-chance change in the move's first week
               (target "wins" over (N,)).
    next2/3    "Wks N-M": the expected matchups won over 2 / 3 weeks from the
               move's first week: the sum of the weeks' win-chance changes.
    ros        "Rest of season": the League Championship alone: the change in
               P(League Champion), advice_v2's dT_rs / rs_weight (target
               "rs_title"). Hidden after week 15 (ranges hides it).
    semis      the semifinal series; finals the Playoff Championship (needs
    finals     the semi); cup the Cup. NOT PRICED YET: they need per-week
    cup        leverage on P(win the semifinal), P(Playoff Champion) and
               P(Cup winner) from the season pass (title_odds_run.stakes),
               which carries only the League Championship's and P(champion)'s
               today, and nothing for the Cup weeks. Their Goal is listed
               (target "semifinal" / "playoff_title" / "cup") and pricing one
               RAISES GoalNotPriced -- never a stand-in number.
    week:K     "Wk K": the win-chance change in week K against its scheduled
               opponent (target "wins" over (K,)); K from the move's first
               week + 1 through the last regular-season week.
The weeks are counted from the MOVE'S FIRST WEEK (advice_v2.horizon_for),
never the calendar, and the range goals' weeks and hiding come from
hub_v2.ranges.ranges() -- the same ranges Market uses, never a second
definition.

HOW A GOAL IS PRICED. The same candidates' machinery, the same roster plan,
seed and common random numbers as Balanced:
  screen   advice_v2.candidate_moves with screen_weeks = the goal's weeks
           (a goal for week 12 screens week 12's points), finalists as ever;
  price    each finalist's plan is the season pass's plan rebuilt with the
           move (advice_v2.known_for, its follow-up and the activation step:
           price()'s own encoding). Each goal week w: the manager's score
           draws on the plan's roster for w and on the baseline's
           (advice_v2._scores: simulate_week_matrix, KeyedDraws -- an unchanged
           player's draws never move), against his opponent's on the plan
           without his own steps; the per-draw win indicator difference is
           kept, so every comparison carries its own paired standard error.
           A week whose opponent is None (no matchup) adds nothing; a goal
           whose every week has none is HIDDEN for that manager.
  rank     (target, the goal weeks' points) like advice_v2.rank_key: a target
           under advice_v2.FLAT_WIN is noise and ranks on points; standing
           pat is (0, 0); advice_v2.qualifies with the last add's bar.
  plan     up to his adds left (and advice.plan_steps_max), each step priced
           after the one before it (advice_v2.apply_step) -- the rules bind
           every goal: the same add budget, windows, IL rules and last-add bar.
           When Balanced's plan keeps a returner in IL this week (H54, a hold
           blocks every move), no goal may move either.

THE NOISE BAR (Part C.3). A goal shows a move different from Balanced's only
when its gain over BALANCED'S PLAN on the goal's own target clears
    bar = max(z x SE, floor + per_week x h)
SE is the comparison's own paired standard error at price_sims (each goal
week's per-draw win difference between the two plans, the weeks' variances
summed); h is the weeks from the move's first week to the goal's first week
(0 for the near goals). Below the bar: "same" (Balanced's plan stands) when
Balanced moves, "noise" (the standing-pat line) when it doesn't. The numbers
are config advice.goals (required; proposed in the mock doc, for Nick).

THE COST (Part C.4): the goal's plan minus Balanced's plan, in the card's
units, every week from the move's first week through the goal's last (the
in-between weeks included), the League Championship odds (always shown),
the adds each plan uses, and for a goal past the horizon the weeks a pickup
holds a roster spot before the goal's first week.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import numpy as np

from . import advice_v2 as av

NEAR, NIGHTLY = "move", "nightly"
BRACKET_TARGETS = {"semis": "semifinal", "finals": "playoff_title", "cup": "cup"}


class GoalError(RuntimeError):
    """A goal's input is missing or inconsistent; the input is named."""


class GoalNotPriced(GoalError):
    """The goal's target needs a number the engine does not price yet."""


# =============================================================================
# the goals
# =============================================================================

@dataclass(frozen=True)
class Goal:
    key: str              # balanced | next | next2 | next3 | ros | semis | finals | cup | week:K
    chip: str             # "Balanced", "Wk 7", "Wks 7-8", "Rest of season", "Wk 12"
    sub: str              # ranges' sub: "Week 7 (14 days)", "Weeks 16-18"
    weeks: tuple          # the weeks the target counts (the horizon for balanced)
    refresh: str          # NEAR (after every Monday move) | NIGHTLY
    target: str           # balanced | wins | rs_title | semifinal | playoff_title | cup
    long_weeks: tuple = ()  # weeks of more than 7 days among `weeks` (week 7: 14 days)

    @property
    def near(self) -> bool:
        return self.refresh == NEAR


def _chip_weeks(a: int, b: int) -> str:
    return f"Wk {a}" if a == b else f"Wks {a}–{b}"


def goals_for(first_week: int, wk_dates: Mapping[int, Sequence], league_config: dict = None,
              join_day=None) -> list:
    """Every goal a move made now can play for, in the picker's order:
    Balanced, the seven ranges that are not passed (hub_v2.ranges.ranges, the
    same as Market's), then one week goal per week from first_week + 1
    through the last regular-season week. first_week: the move's first week
    (advice_v2.Horizon.weeks[0]); wk_dates: {week: [its days]} (config/
    SCHEDULE.json); join_day: the first day counted (default: that week's
    first day)."""
    from .hub_v2 import ranges as rg
    wk = {int(w): list(v) for w, v in wk_dates.items()}
    first = int(first_week)
    if first not in wk:
        raise GoalError(f"the move's first week {first} is not in the schedule")
    long_of = lambda ws: tuple(w for w in ws if len(wk.get(w) or ()) > 7)
    hz = tuple(w for w in (first, first + 1) if w in wk)
    out = [Goal("balanced", "Balanced", rg._sub(list(hz), wk, False), hz, NEAR, "balanced", long_of(hz))]
    for r in rg.ranges(join_day or wk[first][0], first, wk, league_config):
        if r.key in ("next", "next2", "next3"):
            chip, refresh, target = _chip_weeks(r.weeks[0], r.weeks[-1]), NEAR, "wins"
        elif r.key == "ros":
            chip, refresh, target = r.label, NIGHTLY, "rs_title"
        else:
            chip, refresh, target = r.label, NIGHTLY, BRACKET_TARGETS[r.key]
        out.append(Goal(r.key, chip, r.sub, tuple(r.weeks), refresh, target, long_of(r.weeks)))
    last_reg = rg.stage_weeks_cfg(league_config)["ros"][1]
    for k in range(first + 1, last_reg + 1):
        if k not in wk:
            raise GoalError(f"week {k} (a regular-season week) is not in the schedule")
        out.append(Goal(f"week:{k}", f"Wk {k}", rg._sub([k], wk, False), (k,), NIGHTLY, "wins", long_of((k,))))
    return out


@dataclass(frozen=True)
class NoiseRules:
    z: float              # standard errors a gain must clear
    floor: float          # the near goals' minimum bar, in the target's units
    per_week: float       # added per week between the move's first week and the goal's
    title_floor: float    # rs_title's minimum bar (a probability)

    @staticmethod
    def from_config(cfg: dict = None) -> "NoiseRules":
        """config advice.goals (every key required; missing or not a number >= 0 raises)."""
        if cfg is None:
            from .data_loader import _LEAGUE_CONFIG as cfg
        g = ((cfg or {}).get("advice") or {}).get("goals")
        if not isinstance(g, dict):
            raise GoalError("config advice.goals is missing: the goals' noise bar cannot be read")
        vals = {}
        for k in ("noise_z", "noise_floor", "noise_per_week", "noise_title_floor"):
            v = g.get(k)
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0):
                raise GoalError(f"config advice.goals.{k} must be a number >= 0, not {v!r}")
            vals[k] = float(v)
        return NoiseRules(vals["noise_z"], vals["noise_floor"], vals["noise_per_week"], vals["noise_title_floor"])

    def bar(self, goal: Goal, first_week: int, se: float) -> float:
        h = 0 if goal.near else max(0, int(min(goal.weeks)) - int(first_week))
        floor = self.title_floor if goal.target == "rs_title" else self.floor
        return max(self.z * float(se), floor + self.per_week * h)


def far_public(cfg: dict = None) -> bool:
    """config advice.goals.far_public (required, true or false): whether the FAR
    goals' chips are shown on the hub. While false they are priced and kept in
    output/advice_latest.json and the run row, but hidden (Nick, 11-25: a week
    of real outputs is read first). The near goals are public either way."""
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG as cfg
    g = ((cfg or {}).get("advice") or {}).get("goals")
    if not isinstance(g, dict) or "far_public" not in g:
        raise GoalError("config advice.goals.far_public is missing (true or false)")
    v = g["far_public"]
    if not isinstance(v, bool):
        raise GoalError(f"config advice.goals.far_public must be true or false, not {v!r}")
    return v


def public(goal: "Goal", cfg: dict = None) -> bool:
    """Whether the hub shows the goal's chip: Balanced and the near goals
    always; a far goal only with far_public."""
    return goal.near or far_public(cfg)


# =============================================================================
# pricing a plan on any weeks
# =============================================================================

def _win_draws(mine: np.ndarray, theirs: np.ndarray, tie: float) -> np.ndarray:
    """Per draw: 1 a win, `tie` a tie, 0 a loss (advice_v2._win, unaveraged)."""
    return (mine > theirs).astype(float) + float(tie) * (mine == theirs)


@dataclass
class WeekDraws:
    """One plan in one week: the per-draw win indicator (None: no matchup) and
    the mean score."""
    week: int
    wins: Optional[np.ndarray]
    pts: float


def plan_weeks(inputs: av.MondayInputs, manager: str, P: dict, weeks: Sequence[int],
               settings: av.Settings, opponents: Mapping[int, Optional[str]],
               ties: Mapping[int, float]) -> dict:
    """{week: WeekDraws} for plan P (roster_plan.build's dict) over `weeks`,
    against each week's opponent on the plan WITHOUT the manager's own steps
    (advice_v2._price_base's rule), with the price's seed and draws."""
    Popp = av._plan(inputs, prior=False)
    out = {}
    for w in weeks:
        w = int(w)
        players, il = av.plan_roster(P, manager, w)
        sc, _games = av._scores(inputs, manager, players, il, w, settings)
        if w not in opponents:
            raise GoalError(f"{manager}: no opponent given for week {w} (None means no matchup)")
        o = opponents[w]
        wins = None
        if o is not None:
            osc = av._scores(inputs, o, *av.plan_roster(Popp, o, w), w, settings)[0]
            wins = _win_draws(sc, osc, float(ties.get(w, 0.5)))
        out[w] = WeekDraws(w, wins, float(np.mean(sc)))
    return out


def gain(a: dict, b: dict, weeks: Sequence[int]) -> tuple:
    """(sum of win-chance changes a - b over `weeks`, its paired SE, the points
    change): the weeks with a matchup only."""
    g, var, pts, n = 0.0, 0.0, 0.0, 0
    for w in weeks:
        x, y = a[int(w)], b[int(w)]
        pts += x.pts - y.pts
        if x.wins is None or y.wins is None:
            continue
        d = x.wins - y.wins
        g += float(d.mean())
        n = len(d)
        var += float(d.var(ddof=1)) / len(d) if len(d) > 1 else 0.0
    return g, math.sqrt(var), pts


def matched(goal: Goal, opponents: Mapping[int, Optional[str]]) -> bool:
    """False when the goal has no matchup in any of its weeks (hidden for him)."""
    if goal.target != "wins":
        return True
    return any(opponents.get(int(w)) is not None for w in goal.weeks)


# =============================================================================
# a goal's recommendation and plan
# =============================================================================

@dataclass(frozen=True)
class GoalPriced:
    priced: av.Priced          # advice_v2's own numbers for the move (horizon, title)
    target: float              # the goal's target change (its units)
    pts: float                 # the goal weeks' points change
    weeks: dict = field(default_factory=dict)   # {week: WeekDraws} of the move's plan


def _target(goal: Goal, inputs: av.MondayInputs, p: av.Priced, wk: dict, base: dict) -> tuple:
    if goal.target == "wins":
        g, _se, pts = gain(wk, base, goal.weeks)
        return g, pts
    if goal.target == "rs_title":
        cfg = inputs.drop_config
        if cfg is None or not cfg.rs_weight:
            raise GoalError("Rest of season needs the stakes (drop_config.rs_weight)")
        return p.dT_rs / cfg.rs_weight, sum(p.dpts) + p.dpts_later
    raise GoalNotPriced(f"the {goal.key} goal ({goal.target}) is not priced yet: the season pass's "
                        "stakes carry no leverage for it")


def price_goal(inputs: av.MondayInputs, manager: str, goal: Goal, settings: av.Settings,
               opponents: Mapping[int, Optional[str]], ties: Mapping[int, float]) -> list:
    """Every finalist for `goal`, priced: [GoalPriced], screen order."""
    if goal.target in BRACKET_TARGETS.values():
        raise GoalNotPriced(f"the {goal.key} goal is not priced yet")
    screen = None if goal.target == "rs_title" else goal.weeks
    moves = av.finalists(av.candidate_moves(inputs, manager, settings, screen_weeks=screen), settings)
    priced = av.price(inputs, manager, moves, settings)
    w1, w2 = inputs.horizon
    step = av.activation_step(inputs, manager)
    base = plan_weeks(inputs, manager, av._plan(inputs), goal.weeks, settings, opponents, ties) \
        if goal.target == "wins" else {}
    out = []
    for p in priced:
        wk = {}
        if goal.target == "wins":
            P = av._plan(inputs, av.known_for(p.move, w1, p.followup_drop, w2, step=step))
            wk = plan_weeks(inputs, manager, P, goal.weeks, settings, opponents, ties)
        t, pts = _target(goal, inputs, p, wk, base)
        out.append(GoalPriced(p, t, pts, wk))
    return out


def goal_key(gp: GoalPriced) -> tuple:
    """(target, points): a target under FLAT_WIN is noise, ranked on points
    (advice_v2.rank_key's tie-break, on the goal's own weeks)."""
    t = gp.target if abs(gp.target) >= av.FLAT_WIN else 0.0
    return (t, gp.pts)


def _last_add_bar(goal: Goal, inputs: av.MondayInputs, manager: str, settings: av.Settings) -> float:
    """The last add's bar in the goal's units: settings.last_add_bar is in
    win-chance units; for rs_title it is converted at the manager's mean
    regular-season stake per win over the horizon (advice_v2's leverage)."""
    if goal.target == "wins":
        return settings.last_add_bar
    parts = [av._leverage_parts(inputs, manager, w)[0] for w in inputs.weeks()]
    cfg = inputs.drop_config
    lev = float(np.mean(parts)) / cfg.rs_weight if parts and cfg and cfg.rs_weight else 0.0
    return settings.last_add_bar * lev


def recommend_goal(inputs: av.MondayInputs, manager: str, goal: Goal, settings: av.Settings,
                   opponents, ties) -> Optional[GoalPriced]:
    """The goal's best move, or None (standing pat; or the last add's bar)."""
    st = inputs.managers[manager]
    if st.adds_left <= 0:
        return None
    gps = price_goal(inputs, manager, goal, settings, opponents, ties)
    lock = inputs.locked.get(manager, frozenset())
    gps = [g for g in gps if g.priced.followup_drop not in lock]
    ranked = sorted(gps, key=lambda g: (-goal_key(g)[0], -goal_key(g)[1], g.priced.move.kind,
                                        g.priced.move.add, g.priced.move.drop or ""))
    bar = max(0.0, _last_add_bar(goal, inputs, manager, settings)) if st.adds_left == 1 else 0.0
    if ranked and av.qualifies(goal_key(ranked[0]), bar):
        return ranked[0]
    return None


@dataclass(frozen=True)
class GoalPlan:
    goal: Goal
    manager: str
    steps: tuple               # GoalPriced, in order
    stop: str                  # adds | cap | pat | hold | no_adds | hidden
    note: str = ""


def plan_goal(inputs: av.MondayInputs, manager: str, goal: Goal, settings: av.Settings,
              opponents, ties, max_steps: Optional[int] = None, balanced: Optional[av.Plan] = None) -> GoalPlan:
    """The goal's plan: steps like advice_v2.plan_for (each after the one before).
    In order (11-25): a hold blocks every move ("hold"); then no adds left this
    week ("no_adds": the card shows Balanced's own "No adds left" line, never
    the noise line); then a goal with no matchup ("hidden"); then the steps."""
    if balanced is not None and balanced.held:
        return GoalPlan(goal, manager, (), "hold", "a returner kept in IL this week blocks every move")
    if inputs.managers[manager].adds_left <= 0:
        return GoalPlan(goal, manager, (), "no_adds", "no adds left this week")
    if not matched(goal, opponents):
        return GoalPlan(goal, manager, (), "hidden", "no matchup in the goal's weeks")
    st = inputs.managers[manager]
    limit = st.adds_left if max_steps is None else min(st.adds_left, int(max_steps))
    cur, steps, stop = inputs, [], "pat"
    while len(steps) < limit:
        top = recommend_goal(cur, manager, goal, settings, opponents, ties)
        if top is None:
            stop = "pat"
            break
        steps.append(top)
        if len(steps) >= limit:
            stop = "adds" if len(steps) >= st.adds_left else "cap"
            break
        cur = av.apply_step(cur, manager, top.priced, first=len(steps) == 1)
    return GoalPlan(goal, manager, tuple(steps), stop)


# =============================================================================
# against Balanced: the noise bar and the cost
# =============================================================================

def plan_known(inputs: av.MondayInputs, manager: str, moves: Sequence[av.Priced]) -> dict:
    """A plan's steps as known moves (advice_v2.plan_total's encoding)."""
    w1, w2 = inputs.horizon
    step = av.activation_step(inputs, manager)
    return av.merge_known(*[av.known_for(p.move, w1, p.followup_drop, w2, step=step if k == 0 else None)
                            for k, p in enumerate(moves)])


def _adds(moves) -> list:
    return [p.move.add for p in moves]


def compare(inputs: av.MondayInputs, manager: str, gplan: GoalPlan, balanced: av.Plan,
            settings: av.Settings, opponents, ties, rules: NoiseRules) -> dict:
    """The goal's plan against Balanced's: vs_balanced ("same" | "different" |
    "noise" | "hidden" | "hold"), the target gain over Balanced with its SE
    and the bar, and the cost (goal - Balanced) week by week, in title odds,
    adds, and roster weeks held."""
    goal = gplan.goal
    if gplan.stop in ("hidden", "hold", "no_adds"):
        return {"vs_balanced": gplan.stop, "note": gplan.note}
    first = int(inputs.horizon[0])
    g_moves = [s.priced for s in gplan.steps]
    b_moves = [] if balanced is None or balanced.held else [s.priced for s in balanced.steps]
    if [(p.move.kind, p.move.add, p.move.drop, p.move.to_il) for p in g_moves] == \
            [(p.move.kind, p.move.add, p.move.drop, p.move.to_il) for p in b_moves]:
        return {"vs_balanced": "same" if b_moves else "noise", "gain": 0.0, "se": 0.0,
                "bar": None, "cost": None}
    Pg = av._plan(inputs, plan_known(inputs, manager, g_moves)) if g_moves else av._plan(inputs)
    Pb = av._plan(inputs, plan_known(inputs, manager, b_moves)) if b_moves else av._plan(inputs)
    # every week from the move's first through the goal's last, and Balanced's horizon
    # (a Week N goal still shows what it costs week N + 1)
    last = max([int(w) for w in goal.weeks] + [int(w) for w in inputs.weeks()])
    span = list(range(first, last + 1))
    missing = [w for w in span if w not in inputs.world._weeks]
    if missing:
        raise GoalError(f"the goal's weeks {missing} are not in the world's schedule")
    gw = plan_weeks(inputs, manager, Pg, span, settings, opponents, ties)
    bw = plan_weeks(inputs, manager, Pb, span, settings, opponents, ties)
    b0 = av._price_base(inputs, manager, settings)
    mg, mb = av._measure(inputs, manager, settings, b0, Pg), av._measure(inputs, manager, settings, b0, Pb)
    cfg = inputs.drop_config
    title = None if cfg is None or not cfg.rs_weight else (mg["dT_rs"] - mb["dT_rs"]) / cfg.rs_weight
    if goal.target == "wins":
        g, se, _pts = gain(gw, bw, goal.weeks)
    elif goal.target == "rs_title":
        if title is None:
            raise GoalError("Rest of season needs the stakes (drop_config.rs_weight)")
        # the horizon weeks' paired sim noise, at the regular-season stake per win
        _g, se_h, _p = gain(gw, bw, [w for w in inputs.weeks() if w in gw])
        lev = [av._leverage_parts(inputs, manager, w)[0] / cfg.rs_weight for w in inputs.weeks()]
        g, se = title, se_h * (max(lev) if lev else 0.0)
    else:
        raise GoalNotPriced(goal.key)
    bar = rules.bar(goal, first, se)
    weeks_cost = []
    for w in span:
        x, y = gw[w], bw[w]
        d = None if x.wins is None or y.wins is None else float((x.wins - y.wins).mean())
        weeks_cost.append({"week": w, "dwp": d, "dpts": round(x.pts - y.pts, 2),
                           "in_goal": w in goal.weeks, "days": len(inputs.world.dates(w))})
    held = None
    if not goal.near and g_moves:
        held = max(0, int(min(goal.weeks)) - first)
    cost = {"weeks": weeks_cost, "title_odds": title, "adds": len(g_moves), "adds_balanced": len(b_moves),
            "holds_weeks": held}
    if g > bar:
        verdict = "different"
    else:
        verdict = "same" if b_moves else "noise"
    return {"vs_balanced": verdict, "gain": g, "se": se, "bar": bar, "cost": cost}


# =============================================================================
# every goal for every manager (the run's goals pass; advice_live calls it)
# =============================================================================

def _r(x, k=6):
    return None if x is None else round(float(x), k)


def cost_dict(cost: Optional[dict]) -> Optional[dict]:
    if cost is None:
        return None
    return {"weeks": [{**w, "dwp": _r(w["dwp"])} for w in cost["weeks"]], "title_odds": _r(cost["title_odds"]),
            "adds": cost["adds"], "adds_balanced": cost["adds_balanced"], "holds_weeks": cost["holds_weeks"]}


def entry(goal: Goal, gplan: GoalPlan, cmp: dict, move_dict) -> dict:
    """One manager's goal, as advice_latest.json's goals carry it: numbers only
    (advice_live adds the strings). move_dict(priced) -> the move's dict
    (advice_live._move_dict's), so a goal's step reads like Balanced's."""
    steps = []
    for k, s in enumerate(gplan.steps, 1):
        d = move_dict(s.priced)
        d.update({"step": k, "target": _r(s.target), "target_pts": _r(s.pts, 3),
                  "weeks": {str(w): _r(None if x.wins is None else float(x.wins.mean()), 6)
                            for w, x in sorted(s.weeks.items())}})
        steps.append(d)
    return {"key": goal.key, "target": goal.target, "vs_balanced": cmp["vs_balanced"],
            "plan": steps, "stop": gplan.stop, "note": gplan.note or cmp.get("note") or "",
            "gain": _r(cmp.get("gain")), "se": _r(cmp.get("se")), "bar": _r(cmp.get("bar")),
            "cost": cost_dict(cmp.get("cost"))}


def price_all(inputs: av.MondayInputs, balanced: Mapping[str, "av.Advice"], goals: Sequence[Goal],
              settings: av.Settings, opponents: Mapping[str, Mapping[int, Optional[str]]],
              ties: Mapping, rules: NoiseRules, move_dict, max_steps: Optional[int] = None) -> dict:
    """{manager: {goal key: entry, or {"error": ...}}} for every goal except
    Balanced (its plan is the top level). ONE goal failing for ONE manager is
    recorded there and the rest go on (the goals are soft: Balanced never
    depends on them). A goal not priced yet (GoalNotPriced) is recorded as
    {"not_priced": reason}. ties: {(manager, week): tie value}."""
    import time as _time
    out = {}
    for m in sorted(inputs.managers):
        bal = balanced[m].plan
        o = dict(opponents[m])
        tv = {w: float(ties.get((m, w), 0.5)) for w in o}
        out[m] = {}
        for g in goals:
            if g.key == "balanced":
                continue
            t0 = _time.perf_counter()
            try:
                gp = plan_goal(inputs, m, g, settings, o, tv, max_steps=max_steps, balanced=bal)
                c = compare(inputs, m, gp, bal, settings, o, tv, rules)
                e = entry(g, gp, c, move_dict)
            except GoalNotPriced as ex:
                e = {"key": g.key, "not_priced": str(ex)}
            except Exception as ex:                     # noqa: BLE001 -- recorded, never stops the run
                e = {"key": g.key, "error": f"{type(ex).__name__}: {ex}"}
            e["seconds"] = round(_time.perf_counter() - t0, 2)
            out[m][g.key] = e
    return out
