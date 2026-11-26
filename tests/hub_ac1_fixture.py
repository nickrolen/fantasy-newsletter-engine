"""
tests/hub_ac1_fixture.py -- AC1 (the Advice card around days): an advice file
on the made-up league of tests/hub_5d2_world.py (Tue 11-24, week 6, after
Monday's close: a chat move joins Mon 11-30, weeks 7-8), so each card's day
strip is counted by the REAL range source (Team > Schedule's day_fill through
ranges.move_days). Every string is advice_live's own. Made-up names only.

    Marcus  two steps (step 2's add is in Tyler's plan too: the flag); a backup;
            goals: Wk 7, Wks 7-9 and Rest of season pick other moves, Wks 7-8
            is the same, Wk 9 (far) picks a stash, Wk 11 (far) is the noise line
    Tyler   one step whose days barely move but whose win % does: the depth line
    Dana    standing pat
    Jordan  no adds left

    advice()            advice_latest.json, with "goals" (far goals public)
    advice_view(p)      p["v2"]["market"]["advice"] rebuilt on the world (the
                        page's other segments are tests/hub_v2_market_fixture's)
"""

from __future__ import annotations

from datetime import date

import hub_5d2_world as W
import hub_v2_market_fixture as MF
from modules import advice_live as al

TODAY = date(2026, 11, 24)
HZ = {"kind": "chat", "label": "Chat move (effective Mon 11-30)", "weeks": [7, 8], "effective": "2026-11-30",
      "budget_week": 6, "closes": "2026-11-30T18:55-08:00"}
PAIRS = {7: [("Marcus", "Tyler"), ("Dana", "Jordan")], 8: [("Marcus", "Dana"), ("Tyler", "Jordan")],
         9: [("Marcus", "Jordan"), ("Tyler", "Dana")], 10: [("Marcus", "Tyler"), ("Dana", "Jordan")],
         11: [("Marcus", "Dana"), ("Tyler", "Jordan")]}
KEEP = {}                              # filled by world(): the made-up keep chances of the dropped players


def opp(m: str, w: int) -> str:
    for a, b in PAIRS[w]:
        if m in (a, b):
            return b if m == a else a
    raise KeyError((m, w))


def world() -> dict:
    w = W.world(today=TODAY)
    fa = w["fa"]
    act = {m: [n for n in w["next_av"].rosters[m] if n not in (w["next_av"].il.get(m) or {})] for m in W.MGRS}
    names = {"m_add1": fa[5], "m_drop1": act["Marcus"][-3], "m_add2": fa[7], "m_drop2": act["Marcus"][-2],
             "m_bk": fa[6], "t_add": fa[7], "t_drop": act["Tyler"][-3],
             "g_next": fa[6], "g_next3": fa[1], "g_ros": fa[5], "g_ros_drop": act["Marcus"][-2],
             "g_w9": fa[2], "g_w9_drop": act["Marcus"][-1]}
    KEEP.clear()
    KEEP.update({names["m_drop1"]: "4%", names["m_drop2"]: "11%", names["t_drop"]: "2%",
                 names["g_w9_drop"]: "6%"})
    return {"w": w, "names": names}


def _step(add, drop, dwp, dpts, dstarts, title, opps, k, n, **extra) -> dict:
    d = MF._move(add, drop, dwp, dpts, dstarts, title)
    d["text"] = {"move": al.move_text(d), "step": al.step_move_text(d, k, n),
                 "numbers": al.numbers_text(d, HZ, opps, show_title=True), "reason": al.reason_text(d, HZ),
                 "followup": al.followup_text(d, HZ), "v2": al.v2_texts(d, HZ, opps, show_title=True)}
    d.update(step=k, **extra)
    return d


def _goals(N: dict) -> dict:
    from modules import advice_goals as ag
    G = {"balanced": ag.Goal("balanced", "Balanced", "Weeks 7\u20138", (7, 8), ag.NEAR, "balanced", (7,)),
         "next": ag.Goal("next", "Wk 7", "Week 7 (14 days)", (7,), ag.NEAR, "wins", (7,)),
         "next2": ag.Goal("next2", "Wks 7\u20138", "Weeks 7\u20138 (wk 7 is 14 days)", (7, 8), ag.NEAR, "wins", (7,)),
         "next3": ag.Goal("next3", "Wks 7\u20139", "Weeks 7\u20139 (wk 7 is 14 days)", (7, 8, 9), ag.NEAR, "wins", (7,)),
         "ros": ag.Goal("ros", "Rest of season", "Weeks 7\u201315", tuple(range(7, 16)), ag.NIGHTLY, "rs_title", (7,)),
         "week:9": ag.Goal("week:9", "Wk 9", "Week 9", (9,), ag.NIGHTLY, "wins"),
         "week:11": ag.Goal("week:11", "Wk 11", "Week 11", (11,), ag.NIGHTLY, "wins")}
    as_of = "2026-11-25T00:04:00-08:00"
    opps_h = {m: {"7": opp(m, 7), "8": opp(m, 8)} for m in W.MGRS}

    def entry(g, m, vs, plan=None, cost=None):
        e = {"key": g.key, "target": g.target, "vs_balanced": vs, "plan": plan or [], "stop": "pat", "note": "",
             "gain": 0.05 if vs == "different" else 0.0, "se": 0.01, "bar": 0.02, "cost": cost, "as_of": as_of,
             "refresh": "move" if g.near else "nightly"}
        e["texts"] = al.goal_texts(e, g)
        if not g.near:
            e["texts"]["as_of"] = "As of 12:04 AM."
            e["opponent"] = opp(m, g.weeks[0]) if g.target == "wins" else None
        return e

    def cost(weeks, title=-0.004, holds=None):
        return {"weeks": [{"week": w, "dwp": v, "dpts": 10.0 * v * 100, "in_goal": ig, "days": 14 if w == 7 else 7}
                          for w, v, ig in weeks], "title_odds": title, "adds": 1, "adds_balanced": 2,
                "holds_weeks": holds}
    M = "Marcus"
    mans = {M: {
        "next": entry(G["next"], M, "different",
                      [_step(N["g_next"], N["m_drop1"], (0.071, -0.006), (60.0, -5.0), (1.8, -0.1), 0.003,
                             opps_h[M], 1, 1, target=0.071, target_pts=60.0, weeks={"7": 0.62})],
                      cost([(7, 0.018, True), (8, -0.021, False)])),
        "next2": entry(G["next2"], M, "same"),
        "next3": entry(G["next3"], M, "different",
                       [_step(N["g_next3"], N["m_drop1"], (0.052, 0.047), (44.0, 40.0), (1.0, 0.9), 0.006,
                              opps_h[M], 1, 1, target=0.142, target_pts=128.0,
                              weeks={"7": 0.6, "8": 0.55, "9": 0.58})],
                       cost([(7, -0.004, True), (8, 0.006, True), (9, 0.031, True)])),
        "ros": entry(G["ros"], M, "different",
                     [_step(N["g_ros"], N["g_ros_drop"], (0.031, 0.022), (40.0, 30.0), (0.4, 0.3), 0.019,
                            opps_h[M], 1, 1, target=0.019, target_pts=410.0, weeks={})],
                     cost([(7, -0.012, False), (8, -0.004, False)], title=0.005)),
        "week:9": entry(G["week:9"], M, "different",
                        [_step(N["g_w9"], N["g_w9_drop"], (-0.008, -0.011), (-6.0, -9.0), (-0.2, -0.2), -0.002,
                               opps_h[M], 1, 1, target=0.064, target_pts=52.0, weeks={"9": 0.57})],
                        cost([(7, -0.019, False), (8, -0.024, False), (9, 0.058, True)], title=-0.009, holds=2)),
        "week:11": entry(G["week:11"], M, "noise")}}
    for m, vs in (("Tyler", "same"), ("Dana", "noise"), ("Jordan", "no_adds")):
        mans[m] = {k: entry(g, m, vs) for k, g in G.items() if k != "balanced"}
    picker = [{"key": g.key, "chip": g.chip, "sub": g.sub, "weeks": list(g.weeks), "near": g.near,
               "refresh": g.refresh, "target": g.target, "long_weeks": list(g.long_weeks), "public": True,
               "intro": al.goal_intro(g, None if g.near else "As of 12:04 AM.")} for g in G.values()]
    return {"as_of": as_of, "mode": "nightly", "first_week": 7, "error": None, "far_public": True,
            "goals": picker, "managers": mans, "carried": False}


def advice(goals: bool = True) -> dict:
    """advice_latest.json on the made-up league (see the module docstring)."""
    N = world()["names"]
    opps = {m: {"7": opp(m, 7), "8": opp(m, 8)} for m in W.MGRS}
    M = {}
    s1 = _step(N["m_add1"], N["m_drop1"], (0.058, 0.044), (70.0, 55.0), (2.1, 1.6), 0.011, opps["Marcus"], 1, 2,
               also_wanted_by=[])
    s2 = _step(N["m_add2"], N["m_drop2"], (0.021, 0.012), (18.0, 9.0), (0.6, 0.3), 0.004, opps["Marcus"], 2, 2,
               also_wanted_by=["Tyler"])
    tot = {"dwp": [0.079, 0.056], "wp_base": [0.5, 0.5], "dpts": [88.0, 64.0], "dstarts": [2.7, 1.9],
           "dT_horizon": 0.02, "dT_later": 0.0, "dT_rs": 0.02, "dT_po": 0.0, "dpts_later": 0.0,
           "title_odds": 0.015, "title_label": "title odds", "includes_activation": False}
    tot["text"] = al.plan_text(tot, HZ, opps["Marcus"], show_title=True)
    tot["v2"] = {"weeks": al.v2_weeks(tot, HZ, opps["Marcus"]), "label": al.PLAN_LABELS[2], "rows": 2,
                 "title": "title odds +1.5%"}
    bk = _step(N["m_bk"], N["m_drop1"], (0.031, 0.029), (40.0, 35.0), (1.2, 0.9), 0.006, opps["Marcus"], 1, 1)
    M["Marcus"] = {"adds_left": 2, "opponents": opps["Marcus"], "also_wanted_by": [], "activation": None,
                   "move": s1, "backup": bk, "note": "", "bar": 0.0, "plan": [s1, s2], "plan_total": tot,
                   "plan_stop": {"code": "adds", "text": "uses every add left"}}
    t1 = _step(N["t_add"], N["t_drop"], (0.014, 0.009), (6.0, 4.0), (0.2, 0.1), 0.002, opps["Tyler"], 1, 1,
               also_wanted_by=["Marcus"])
    ttot = dict(t1, includes_activation=False)
    ttot["text"] = al.plan_text(ttot, HZ, opps["Tyler"], show_title=True)
    ttot["v2"] = {"weeks": al.v2_weeks(ttot, HZ, opps["Tyler"]), "label": "", "rows": 1, "title": None}
    M["Tyler"] = {"adds_left": 3, "opponents": opps["Tyler"], "also_wanted_by": ["Marcus"], "activation": None,
                  "move": t1, "backup": None, "note": "", "bar": 0.01, "plan": [t1], "plan_total": ttot,
                  "plan_stop": {"code": "pat", "text": "x"}}
    M["Dana"] = {"adds_left": 2, "opponents": opps["Dana"], "also_wanted_by": [], "activation": None, "move": None,
                 "backup": None, "note": "standing pat beats every move", "bar": 0.0, "plan": [], "plan_total": None,
                 "plan_stop": None, "empty": "No move beats standing pat", "v2_empty": al.EMPTY_V2["pat"]}
    M["Jordan"] = {"adds_left": 0, "opponents": opps["Jordan"], "also_wanted_by": [], "activation": None,
                   "move": None, "backup": None, "note": "no adds left", "bar": None, "plan": [], "plan_total": None,
                   "plan_stop": None, "empty": "No adds left", "v2_empty": al.EMPTY_V2["adds"]}
    out = {"schema": al.SCHEMA, "run_id": "syn-ac1", "mode": "nightly", "cause": None, "cause_text": "the nightly run",
           "as_of": "2026-11-25T00:04:00-08:00", "updated_text": "Updated 12:04 AM after the nightly run.",
           "league_day": "2026-11-25", "horizon": HZ, "weighting": "x", "settings": {}, "inputs": {}, "seconds": {},
           "show_title_odds": True, "managers": M, "error": None}
    if goals:
        out["goals"] = _goals(N)
    return out


def advice_view(p: dict, adv: dict = None, *, keep: dict = None) -> dict:
    """p["v2"]["market"]["advice"] rebuilt from `adv` (default advice()) on the
    world: the real strip (market._strip_fn over the world's range source)."""
    from modules.hub_v2 import market
    wd = world()
    w = wd["w"]
    adv = adv or advice()
    v2 = p["v2"]
    order = list(v2["team_order"])
    team_of = {m: v2["teams"][m]["team"] for m in order}
    strip = market._strip_fn({"ranges": w["src"], "fa_av": w["fa_av"], "wk_dates": w["wk_dates"], "advice": adv})
    k = dict(KEEP if keep is None else keep)
    p["v2"]["market"]["advice"] = market.advice_view(adv, order, team_of, lambda n: "", show_title=True,
                                                     strip=strip, keep=lambda n: k.get(n))
    return p
