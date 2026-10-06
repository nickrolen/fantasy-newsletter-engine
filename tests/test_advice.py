"""C2/C3 engine (modules/advice.py) -- the pieces settled so far.

Not yet wired into Step 6: the this_week drop cost (replacement level) is
an open design question; see C2_C3_DESIGN.md "Open after the first read".
"""
import pytest

from modules import advice as adv
from modules import marginal_value as mv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from test_marginal_value import _world, _ctx  # noqa: E402  (shared builders)


@pytest.fixture(autouse=True)
def _season(monkeypatch):
    spans = {"regular_season": (1, 3), "playoffs": (4, 5), "cup": (6, 7)}
    monkeypatch.setattr(mv, "stage_weeks", lambda season, stage: spans.get(stage))


def _res(points, se):
    return adv._Scored(points=points, se=se, starts=0.0)


def test_the_floor_scales_with_the_window():
    """10 a week: a real move in one week, 0.67 a week over fifteen."""
    w = _world()
    one = _ctx(w, window="this_week")
    two = _ctx(w, window="regular_season")
    assert adv.floor_for(one) == 10.0 and adv.floor_for(two) == 20.0
    assert adv.clears(_res(15.0, 1.0), one)
    assert not adv.clears(_res(15.0, 1.0), two)


def test_two_standard_errors_are_required_too():
    w = _world()
    one = _ctx(w, window="this_week")
    assert not adv.clears(_res(15.0, 8.0), one)


def test_protected_keepers_come_from_this_runs_table():
    rosters = {"Nick": ["A", "B", "C"]}
    kw = {"week": 5, "players": [{"player_name": n, "manager": "Nick", "keepability_score": s}
                                 for n, s in (("A", 10), ("B", 90), ("C", 50))]}
    prot, wk = adv.protected_keepers(kw, 5, rosters, {"Nick": 2})
    assert prot == {"Nick": ["B", "C"]} and wk == 5
    with pytest.raises(ValueError, match="stale"):
        adv.protected_keepers(kw, 6, rosters, {"Nick": 2})
    assert adv.protected_keepers(None, 6, rosters, {"Nick": 2}) == (None, None)


def test_every_shared_recommendation_names_the_others():
    def rec(m, add):
        return adv.Rec(m, "this_week", add, None, 50, 1, 1, 50, 10)
    plans = [adv.WaiverPlan("Nick", 3, [rec("Nick", "Garland")], [], [], 1),
             adv.WaiverPlan("Hayden", 3, [rec("Hayden", "Garland")], [], [], 1),
             adv.WaiverPlan("Benton", 3, [rec("Benton", "Duren")], [], [], 1)]
    adv.mark_contested(plans)
    assert plans[0].this_week[0].contested_with == ["Hayden"]
    assert plans[1].this_week[0].contested_with == ["Nick"]
    assert plans[2].this_week[0].contested_with == []


def test_an_unprojected_player_is_never_the_suggested_drop():
    """C1 values him at 0.0 -- he would always look like the free drop."""
    w = _world()
    projs, rosters, nba, weeks, fas = w
    rosters["Nick"].append("Deep Guy")
    ctxs = {"this_week": (_ctx(w, sims=40, fallback_info={"Deep Guy": ("BOS", "SF")}),
                          _ctx(w, sims=200, fallback_info={"Deep Guy": ("BOS", "SF")}))}
    plan = adv.waiver_plan("Nick", ctxs, fas, protected=[], adds_remaining=3, protected_week=1)
    assert all(r.drop != "Deep Guy" for r in plan.this_week)


def test_the_plan_respects_the_add_budget_and_never_redrops_its_own_add():
    w = _world(seed=4)
    ctxs = {"this_week": (_ctx(w, sims=40), _ctx(w, sims=200))}
    plan = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=2, protected_week=1)
    assert len(plan.this_week) <= 2
    adds = {r.add for r in plan.this_week}
    assert not adds & {r.drop for r in plan.this_week}


def test_no_keepability_means_no_drop_advice_and_says_so():
    w = _world()
    ctxs = {"this_week": (_ctx(w, sims=40), _ctx(w, sims=200))}
    plan = adv.waiver_plan("Nick", ctxs, w[4], protected=None, adds_remaining=1, protected_week=None)
    assert all(r.drop is None for r in plan.this_week)
    assert "no drop advice" in plan.note


def test_ages_persist_and_restart_after_two_weeks_away():
    store = {}
    t = adv.Trade("Nick", "Hayden", ["A"], ["B"], None, None, 100, 1, 90, 1, 10, 90)
    adv.stamp_ages([t], adv.trade_key, store, 3)
    adv.stamp_ages([t], adv.trade_key, store, 5)
    assert t.first_shown_week == 3                       # one week away: same deal
    adv.stamp_ages([t], adv.trade_key, store, 8)
    assert t.first_shown_week == 8                       # three weeks away: restarts


def test_trades_report_both_gains_and_the_differential_never_fairness():
    fields = adv.Trade.__dataclass_fields__
    for f in ("gain_a", "gain_b", "differential", "acceptability"):
        assert f in fields
    assert not any("fair" in f for f in fields)


# ---------------------------------------------------------------------------
# Replacement level (Nick, 10-06)
# ---------------------------------------------------------------------------

def test_replacement_k_is_derived_never_written(monkeypatch):
    monkeypatch.setattr(adv, "add_budget_for", lambda season: 3)
    assert adv.replacement_k("2026-27", ["A", "B", "C", "D"]) == 12
    monkeypatch.setattr(adv, "add_budget_for", lambda season: 2)
    assert adv.replacement_k("2030-31", ["A", "B", "C", "D"]) == 8
    monkeypatch.setattr(adv, "add_budget_for", lambda season: None)
    with pytest.raises(ValueError, match="undefined"):
        adv.replacement_k("2024-25", ["A", "B", "C", "D"])


def _mini(projs, roster, fas, weeks_games):
    """One manager, one team per player, games given per week as team sets."""
    from datetime import date, timedelta
    sched, games = [], []
    d0 = date(2026, 10, 26)
    for i, (wk, teams) in enumerate(weeks_games):
        start = d0 + timedelta(days=7 * i)
        sched.append({"week": wk, "start_date": start.isoformat(),
                      "end_date": (start + timedelta(days=6)).isoformat()})
        for k in range(7):
            ts = sorted(teams)
            for j in range(0, len(ts) - 1, 2):
                games.append({"date": (start + timedelta(days=k)).isoformat(),
                              "home": ts[j], "away": ts[j + 1]})
    return sched, {"games": games}


def test_replacement_is_ranked_for_this_roster_not_the_global_list():
    """Drop the only center and the open seat is C: a 20-FPPG center
    outranks a 40-FPPG guard for THIS roster -- position comes through the
    optimal fill, with no separate positional logic."""
    from test_marginal_value import _proj
    roster = ["C1", "C2"] + [f"G{i}" for i in range(8)]
    projs = {"C1": _proj("C1", "BOS", "C", 30), "C2": _proj("C2", "NYK", "C", 30)}
    projs.update({f"G{i}": _proj(f"G{i}", "MIA", "PG", 30) for i in range(8)})
    projs.update({"BigFA": _proj("BigFA", "LAL", "C", 20), "GuardFA": _proj("GuardFA", "GSW", "PG", 40)})
    sched, nba = _mini(projs, roster, [], [(2, {"BOS", "NYK", "MIA", "LAL", "GSW", "DEN"})])
    c = mv.build_context(projs, {"Nick": roster}, nba, sched, "this_week", 1,
                         extra_players=["BigFA", "GuardFA"], sims=200)
    open_slot = [p for p in roster if p != "C1"]
    assert adv.Refill(c, c, ["BigFA", "GuardFA"], k=1).kth("Nick", open_slot) == "BigFA"
    assert adv.Refill(c, c, ["BigFA", "GuardFA"], k=2).kth("Nick", open_slot) == "GuardFA"


def test_a_star_with_no_games_this_week_is_not_cut_to_stream():
    """The LeBron bug. His team is off this week, so the one-week window
    says cutting him for a streamer is pure profit; he plays next week, and
    nothing on the wire replaces him."""
    from test_marginal_value import _proj
    roster = ["Star"] + [f"P{i}" for i in range(9)]
    projs = {"Star": _proj("Star", "LAL", "SF", 60)}
    projs.update({f"P{i}": _proj(f"P{i}", "BOS", ["PG", "SG", "SF", "PF", "C"][i % 5], 25)
                  for i in range(9)})
    fas = [f"F{i}" for i in range(6)]
    projs.update({f: _proj(f, "NYK", "SF", 22) for f in fas})
    weeks = [(2, {"BOS", "NYK", "MIA", "DEN"}),          # Star's team (LAL) off
             (3, {"BOS", "NYK", "LAL", "GSW"})]           # LAL back
    sched, nba = _mini(projs, roster, fas, weeks)
    spans = lambda season, stage: {"regular_season": (1, 3)}.get(stage)
    mv_stage = mv.stage_weeks
    mv.stage_weeks = spans
    try:
        def ctx(window, cw, n):
            return mv.build_context(projs, {"Nick": roster}, nba, sched, window, cw,
                                    extra_players=fas, sims=n)
        ctxs = {"this_week": (ctx("this_week", 1, 40), ctx("this_week", 1, 200)),
                "rest_of_season": (ctx("regular_season", 2, 40), ctx("regular_season", 2, 200))}
        naive = adv.waiver_plan("Nick", {"this_week": ctxs["this_week"]}, fas, [], 1, 1)
        fixed = adv.waiver_plan("Nick", ctxs, fas, [], 1, 1, replacement_rank=2)
    finally:
        mv.stage_weeks = mv_stage
    assert naive.this_week and naive.this_week[0].drop == "Star"      # the bug, reproduced
    assert all(r.drop != "Star" for r in fixed.this_week)             # and fixed


def test_rest_of_season_without_a_replacement_rank_refuses():
    w = _world()
    ctxs = {"this_week": (_ctx(w, sims=40), _ctx(w, sims=100)),
            "rest_of_season": (_ctx(w, window="regular_season", sims=40),
                               _ctx(w, window="regular_season", sims=100))}
    with pytest.raises(ValueError, match="replacement_rank"):
        adv.waiver_plan("Nick", ctxs, w[4], [], 1, 1)


@pytest.mark.parametrize("seed", range(6))
def test_the_refill_screen_can_only_lower_the_refill_value(seed, monkeypatch):
    """k-th best of a subset <= k-th best of the full set. The screen's only
    possible error is a higher C2 drop cost / lower C3 credit."""
    w = _world(seed=seed)
    ctx = _ctx(w, window="regular_season", sims=60)
    roster = ctx.rosters["Benton"]
    open_slot = roster[1:]
    screened = adv.Refill(ctx, ctx, w[4], k=4)
    monkeypatch.setattr(adv, "REFILL_SCREEN_EXTRA", 10_000)
    full = adv.Refill(ctx, ctx, w[4], k=4)
    s_gain = screened.credit("Benton", open_slot, screen_roster=roster)[0]
    f_gain = full.credit("Benton", open_slot, screen_roster=roster)[0]
    assert s_gain <= f_gain + 1e-9


def test_c2_charge_and_c3_credit_are_one_function():
    """The drifted-copy signature: one concept, two implementations, two
    answers. Both callers go through Refill; nothing else ranks a refill."""
    import inspect
    src = inspect.getsource(adv)
    assert "refill.drop_cost(" in inspect.getsource(adv._best_pairs)
    assert "refill.credit(" in inspect.getsource(adv.find_trades)
    assert src.count("class Refill") == 1 and "_Replacement" not in src


def test_drop_cost_is_value_minus_refill_of_the_same_slot():
    """cost(d) = max(0, -MV(add r_k, drop d)) = value of d - refill credit,
    both measured against roster - d."""
    w = _world(seed=1)
    ctx = _ctx(w, window="regular_season", sims=200)
    roster = list(ctx.rosters["Hayden"])
    rf = adv.Refill(ctx, ctx, w[4], k=3)
    d = roster[0]
    cost, _se, r_k = rf.drop_cost("Hayden", roster, d)
    open_slot = [p for p in roster if p != d]
    value_d = rf._eval(ctx, "Hayden", open_slot, adds=[d]).points
    credit = rf._eval(ctx, "Hayden", open_slot, adds=[r_k]).points
    assert abs(cost - max(0.0, value_d - credit)) < 0.02
