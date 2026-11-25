"""
tests/hub_v2_market_fixture.py -- the synthetic league's Market tab (4c3),
made by the REAL engine path (modules/hub_v2/market.build) on made-up inputs:
a free agent with his game days, a stash row, and an advice file whose
strings come from advice_live's own functions (v2_texts, numbers_text,
v2_weeks, PLAN_LABELS, EMPTY_V2), so the page is tested on what the engine
writes. Made-up names and numbers only.

    Marcus  the IL activation (priced), then two steps; step 2's add is in
            Tyler's plan too (the flag); the plan line; a backup
    Tyler   one step (its add in Marcus's plan: flagged); a backup
    Dana    standing pat (adds left)
    Jordan  no adds left
"""

from __future__ import annotations

import copy
from datetime import date

from modules import advice_live as al
from modules.hub_v2 import market

FA_NAME, FA_KEY = "Free Guy", "free-guy"
WEEKS = {9: [date(2026, 12, 3), date(2026, 12, 5)],
         10: [date(2026, 12, 7), date(2026, 12, 9), date(2026, 12, 11)],
         11: [date(2026, 12, 14), date(2026, 12, 15), date(2026, 12, 17), date(2026, 12, 19)]}
HZ = {"kind": "chat", "label": "Chat move (effective Mon 12-07)", "weeks": [10, 11], "effective": "2026-12-07",
      "budget_week": 9, "closes": "2026-12-07T15:00"}


class FaAv:
    """The free agents' availability, made up: he plays every listed day but
    the ones in `out`."""

    def __init__(self, out=None):
        self.out = out or {}
        self.info = {FA_NAME: {"nba_team": "AAA"}, "Stash Guy": {"nba_team": "BBB"}}

    def playable(self, name, days):
        return [d for d in days if d not in self.out.get(name, ())]

    def has_game(self, name, d):
        return True


def col_specs() -> list:
    return [{"w": 9, "label": "Wk 9", "sub": "rest", "days": WEEKS[9], "long": False},
            {"w": 10, "label": "Wk 10", "sub": "", "days": WEEKS[10], "long": False},
            {"w": 11, "label": "Wk 11", "sub": "", "days": WEEKS[11], "long": False}]


def free_agents() -> dict:
    return {"rows": [{"name": FA_NAME, "pos": "SF,PF", "nba": "AAA", "proj": "31.0", "g1": "2", "g2": "3",
                      "g3": "4", "pts": "279.0", "tags": [], "status": "healthy", "card": FA_KEY}],
            "aside": "by projected points, weeks 9, 10 and 11", "pts_label": "Pts (3 wks)", "mode": "this",
            "cols": ["GL", "Wk 10", "Wk 11"], "weeks": [9, 10, 11],
            "empty": "No pickup joins a roster again this season.", "note": "n"}


def stash() -> dict:
    return {"rows": [{"name": "Stash Guy", "pos": "C", "nba": "BBB", "proj": "28.0",
                      "tags": [{"text": "O \u00b7 back 01-13", "kind": "out"}], "status": "override",
                      "season": False, "season_note": "", "card": ""}],
            "aside": "OFS, or O with an injury entry, by projection", "open_il": "Open IL slots now: Dana 1.",
            "empty": "No free agent is OFS, or tagged O with an injury entry.", "note": "Long absences only."}


def _move(add, drop, dwp, dpts, dstarts, title, *, kind="add_drop", to_il=None, flat=False) -> dict:
    return {"kind": kind, "add": add, "drop": drop, "to_il": to_il, "followup_drop": None,
            "followup_standin": False, "describe": f"add {add}", "score": 0.05, "flat": flat,
            "dwp": list(dwp), "wp_base": [0.5, 0.5], "dpts": list(dpts), "dstarts": list(dstarts),
            "dT_horizon": 0.01, "dT_later": 0.0, "dT_rs": 0.01, "dT_po": 0.0, "dpts_later": 0.0,
            "title_odds": title, "title_label": "title odds", "reason": "r"}


def _texts(d: dict, opps: dict, k: int, n: int, show: bool) -> dict:
    d["text"] = {"move": al.move_text(d), "step": al.step_move_text(d, k, n),
                 "numbers": al.numbers_text(d, HZ, opps, show_title=show), "reason": al.reason_text(d, HZ),
                 "followup": al.followup_text(d, HZ), "v2": al.v2_texts(d, HZ, opps, show_title=show)}
    return d


def advice_latest(*, show_title: bool = True, act_dwp=(0.061, 0.053), pre_4c3: bool = False) -> dict:
    """An advice_latest.json for the made-up league (see the module docstring).
    act_dwp: the activation's two win-% changes (a negative one renders as it
    is). pre_4c3: the file as written before 4c3 (no v2 strings, no
    activation numbers, plan_total without the activation)."""
    opps = {"Marcus": {"10": "Tyler", "11": "Dana"}, "Tyler": {"10": "Marcus", "11": "Jordan"},
            "Dana": {"10": "Jordan", "11": "Marcus"}, "Jordan": {"10": "Dana", "11": "Tyler"}}
    m = {}
    # Marcus: the activation, then two steps
    act = {"week": 10, "back": ["Marcus Hurt"], "drops": ["Marcus Bench"], "returns": {},
           "text": "Marcus Hurt is back for week 10: activate him and drop Marcus Bench. It costs no add.",
           "step": 0, "kind": "activate", "baseline": "hold", "dwp": list(act_dwp), "wp_base": [0.44, 0.47],
           "dpts": [21.0, 30.5], "dstarts": [0.6, 0.9], "dT_horizon": 0.004, "dT_later": 0.0, "dT_rs": 0.004,
           "dT_po": 0.0, "dpts_later": 0.0, "flat": False, "title_odds": 0.007, "title_label": "title odds"}
    v2 = al.v2_texts(act, HZ, opps["Marcus"], show_title=show_title)
    v2["why"] = al.FIRST_TEXT
    act["texts"] = {"numbers": al.numbers_text(act, HZ, opps["Marcus"], show_title=show_title),
                    "reason": al.reason_text(act, HZ), "v2": v2}
    s1 = _texts(_move(FA_NAME, "Marcus Wing", (0.046, 0.040), (31.4, 26.8), (0.7, 0.7), 0.009),
                opps["Marcus"], 1, 2, show_title)
    s2 = _texts(_move("Wire Guy", "Marcus Bench Two", (0.042, 0.018), (33.0, 19.4), (0.8, 0.1), 0.006),
                opps["Marcus"], 2, 2, show_title)
    s1.update(step=1, also_wanted_by=[])
    s2.update(step=2, also_wanted_by=["Tyler"])
    tot = {"dwp": [0.149, 0.111], "wp_base": [0.44, 0.47], "dpts": [85.4, 76.7], "dstarts": [2.1, 1.7],
           "dT_horizon": 0.02, "dT_later": 0.0, "dT_rs": 0.02, "dT_po": 0.0, "dpts_later": 0.0,
           "title_odds": 0.026, "title_label": "title odds", "includes_activation": True}
    tot["text"] = al.plan_text(tot, HZ, opps["Marcus"], show_title=show_title)
    tot["v2"] = {"weeks": al.v2_weeks(tot, HZ, opps["Marcus"]), "label": al.PLAN_LABELS[3], "rows": 3,
                 "title": "title odds +2.6%" if show_title else None}
    bk = _texts(_move("Back Guy", "Marcus Wing", (0.025, 0.045), (20.0, 21.0), (1.0, 0.7), 0.004),
                opps["Marcus"], 1, 1, show_title)
    m["Marcus"] = {"adds_left": 2, "opponents": opps["Marcus"], "also_wanted_by": [], "activation": act,
                   "move": s1, "backup": bk, "note": "", "bar": 0.0, "plan": [s1, s2], "plan_total": tot,
                   "plan_stop": {"code": "adds", "text": "uses every add left"}}
    # Tyler: one step, its add in Marcus's plan
    t1 = _texts(_move("Wire Guy", "Tyler Bench", (0.087, 0.024), (50.8, 23.0), (1.9, 1.4), 0.012),
                opps["Tyler"], 1, 1, show_title)
    t1.update(step=1, also_wanted_by=["Marcus"])
    tbk = _texts(_move("Other Guy", "Tyler Bench", (0.041, 0.038), (30.0, 28.0), (0.9, 1.4), 0.004),
                 opps["Tyler"], 1, 1, show_title)
    ttot = dict(t1, includes_activation=False)
    ttot["text"] = al.plan_text(ttot, HZ, opps["Tyler"], show_title=show_title)
    ttot["v2"] = {"weeks": al.v2_weeks(ttot, HZ, opps["Tyler"]), "label": "", "rows": 1, "title": None}
    m["Tyler"] = {"adds_left": 1, "opponents": opps["Tyler"], "also_wanted_by": ["Marcus"], "activation": None,
                  "move": t1, "backup": tbk, "note": "", "bar": 0.01, "plan": [t1], "plan_total": ttot,
                  "plan_stop": {"code": "adds", "text": "uses every add left"}}
    m["Dana"] = {"adds_left": 2, "opponents": opps["Dana"], "also_wanted_by": [], "activation": None,
                 "move": None, "backup": None, "note": "standing pat beats every move", "bar": 0.0, "plan": [],
                 "plan_total": None, "plan_stop": None, "empty": "No move beats standing pat",
                 "v2_empty": al.EMPTY_V2["pat"]}
    m["Jordan"] = {"adds_left": 0, "opponents": opps["Jordan"], "also_wanted_by": [], "activation": None,
                   "move": None, "backup": None, "note": "no adds left", "bar": None, "plan": [],
                   "plan_total": None, "plan_stop": None, "empty": "No adds left this week (week 9's budget)",
                   "v2_empty": al.EMPTY_V2["adds"]}
    out = {"schema": al.SCHEMA, "run_id": "syn", "mode": "nightly", "cause": None, "cause_text": "the nightly run",
           "as_of": "2026-12-02T00:04:00-08:00", "updated_text": "Updated 12:04 AM after the nightly run.",
           "league_day": "2026-12-02", "horizon": HZ, "weighting": "x", "settings": {}, "inputs": {},
           "seconds": {}, "show_title_odds": show_title, "managers": m, "error": None}
    if pre_4c3:
        out = copy.deepcopy(out)
        for e in out["managers"].values():
            if e["activation"]:
                e["activation"] = {k: e["activation"][k] for k in ("week", "back", "drops", "returns", "text")}
            for d in (e["plan"] or []) + ([e["backup"]] if e["backup"] else []):
                d["text"].pop("v2", None)
            e.pop("v2_empty", None)
            if e["plan_total"]:
                e["plan_total"].pop("v2", None)
                e["plan_total"].pop("includes_activation", None)
    return out


from modules.hub_v2 import ranges as _ranges


def add_market(p: dict, *, advice=None, advice_on: bool = True, show_title: bool = True, fa_av=None) -> dict:
    """payload["free_agents"], ["stash"] and v2["market"] on the made-up league."""
    p["free_agents"] = free_agents()
    rl = _ranges.ranges(WEEKS[9][0], 9, WEEKS)
    p["free_agents"]["ranges"] = {r.key: [FA_NAME] for r in rl}          # 5e: each range's own list
    p["free_agents"]["range_rows"] = []
    p["stash"] = stash()
    p["v2"]["market"] = market.build(p, {
        "fa_av": fa_av or FaAv(), "col_specs": col_specs(), "advice_on": advice_on,
        "advice": advice if advice is not None else advice_latest(show_title=show_title),
        "show_title": show_title, "first_day": date(2026, 10, 20),
        # 5d2 s.4: the ranges over the made-up weeks (only weeks 9-11 exist here)
        "range_list": _ranges.ranges(WEEKS[9][0], 9, WEEKS), "wk_dates": WEEKS, "ranges": None,
        "proj": {FA_NAME: {"projectedFPPG": 31.0}, "Stash Guy": {"projectedFPPG": 28.0}}})
    return p


def goals_block(*, far_public: bool = True, error: str = None) -> dict:
    """advice_latest.json's "goals" for the made-up league (Advice goals, Part
    D): the picker's goals and each manager's entry, every string from
    advice_live's own functions (goal_intro, goal_texts). Marcus: Wk 10 picks a
    different move and week 11 a stash; Tyler: same as Balanced; Dana: the
    noise line; Jordan: no adds left."""
    from modules import advice_goals as ag
    g_next = ag.Goal("next", "Wk 10", "Week 10", (10,), ag.NEAR, "wins")
    g_next2 = ag.Goal("next2", "Wks 10\u201311", "Weeks 10\u201311", (10, 11), ag.NEAR, "wins")
    g_w11 = ag.Goal("week:11", "Wk 11", "Week 11", (11,), ag.NIGHTLY, "wins")
    goals = [ag.Goal("balanced", "Balanced", "Weeks 10\u201311", (10, 11), ag.NEAR, "balanced"), g_next, g_next2, g_w11]
    as_of = "2026-12-02T00:04:00-08:00"
    opps = {"Marcus": "Dana", "Tyler": "Jordan", "Dana": "Marcus", "Jordan": "Tyler"}

    def entry(g, m, vs, plan=None, cost=None):
        e = {"key": g.key, "target": g.target, "vs_balanced": vs, "plan": plan or [], "stop": "pat", "note": "",
             "gain": 0.05 if vs == "different" else 0.0, "se": 0.01, "bar": 0.02, "cost": cost,
             "as_of": as_of, "refresh": "move" if g.near else "nightly"}
        e["texts"] = al.goal_texts(e, g)
        if not g.near:
            e["texts"]["as_of"] = "As of 12:04 AM."
            e["opponent"] = opps[m]
        return e

    def step(add, drop, target, weeks):
        d = _texts(_move(add, drop, (0.03, -0.01), (25.0, 4.0), (0.4, 0.1), -0.002), {"10": "Tyler", "11": "Dana"},
                   1, 1, True)
        d.update(step=1, target=target, target_pts=40.0, weeks=weeks)
        return d
    cost_near = {"weeks": [{"week": 10, "dwp": 0.024, "dpts": 20.0, "in_goal": True, "days": 7},
                           {"week": 11, "dwp": -0.013, "dpts": -8.0, "in_goal": False, "days": 7}],
                 "title_odds": -0.004, "adds": 1, "adds_balanced": 2, "holds_weeks": None}
    cost_far = {"weeks": [{"week": 10, "dwp": -0.021, "dpts": -15.0, "in_goal": False, "days": 7},
                          {"week": 11, "dwp": 0.062, "dpts": 48.0, "in_goal": True, "days": 7}],
                "title_odds": -0.012, "adds": 1, "adds_balanced": 2, "holds_weeks": 1}
    mans = {"Marcus": {"next": entry(g_next, "Marcus", "different", [step("Streak Guy", "Marcus Wing", 0.094, {"10": 0.094})], cost_near),
                       "next2": entry(g_next2, "Marcus", "same"),
                       "week:11": entry(g_w11, "Marcus", "different", [step("Stash Guy", "Marcus Bench Two", 0.062, {"11": 0.062})], cost_far)},
            "Tyler": {k: entry(g, "Tyler", "same") for k, g in (("next", g_next), ("next2", g_next2), ("week:11", g_w11))},
            "Dana": {k: entry(g, "Dana", "noise") for k, g in (("next", g_next), ("next2", g_next2), ("week:11", g_w11))},
            "Jordan": {k: entry(g, "Jordan", "no_adds") for k, g in (("next", g_next), ("next2", g_next2), ("week:11", g_w11))}}
    picker = [{"key": g.key, "chip": g.chip, "sub": g.sub, "weeks": list(g.weeks), "near": g.near, "refresh": g.refresh,
               "target": g.target, "long_weeks": [], "public": g.near or far_public,
               "intro": al.goal_intro(g, None if g.near else "As of 12:04 AM.")} for g in goals]
    return {"as_of": as_of, "mode": "nightly", "first_week": 10, "error": error, "far_public": far_public,
            "goals": picker, "managers": mans, "carried": False}


def advice_with_goals(**kw) -> dict:
    a = advice_latest()
    a["goals"] = goals_block(**kw)
    return a
