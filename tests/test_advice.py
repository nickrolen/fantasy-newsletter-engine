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
