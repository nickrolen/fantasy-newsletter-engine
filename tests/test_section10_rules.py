"""Section 10 in week 3, on Nick's call, under the league's rules
(HANDOFF_SECTION10_WEEK3_2026-10-29).

The premise gate measured FAIL; Nick decided to publish anyway. The override
lives in config, dated and attributed, and every build says it was used. The
advice must leave every roster legal under the 2026-27 IL and transaction
rules, value the week its moves can first take effect, and claim only what
was measured.
"""
import re
import sys
from pathlib import Path

import pytest

from modules import advice as adv
from modules import advice_render as rr
from modules import advice_runner as ar
from modules import marginal_value as mv

sys.path.insert(0, str(Path(__file__).parent))
from test_marginal_value import _world, _ctx  # noqa: E402

S = "2026-27"
OVERRIDE = {"season": S, "by": "Nick", "date": "2026-10-29",
            "overrides_bands": ["FAIL", "MARGINAL"],
            "reason": "Nick, 10-29: ship Section 10 in week 3; do our best."}


@pytest.fixture(autouse=True)
def _season(monkeypatch):
    spans = {"regular_season": (1, 3), "playoffs": (4, 5), "cup": (6, 7)}
    monkeypatch.setattr(mv, "stage_weeks", lambda season, stage: spans.get(stage))


# 1 -- the override
@pytest.mark.parametrize("gate,publish,why", [
    ({"season": S, "band": "FAIL"}, True, "published on Nick's override of a FAIL premise gate (10-29)"),
    ({"season": S, "band": "MARGINAL"}, True, "override of a MARGINAL premise gate"),
    ({"season": S, "band": "CLEAR"}, True, "published"),
    ({"season": S, "band": "UNSTABLE"}, False, "UNSTABLE"),
    ({"season": S, "band": "UNREADABLE"}, False, "UNREADABLE"),
    (None, False, "has not been run"),
    ({"season": "2025-26", "band": "FAIL"}, False, "2025-26"),
])
def test_the_override_publishes_only_a_measured_band_it_names(gate, publish, why):
    ok, reason = ar.publish_decision(gate, S, 3, 3, ar.premise_override({"advice_premise_override": OVERRIDE}))
    assert ok is publish and why in reason, reason
    assert ar.publish_decision(gate, S, 2, 3, OVERRIDE)[0] is False        # before launch: preview


def test_an_override_for_another_season_or_band_does_nothing():
    other = dict(OVERRIDE, season="2027-28")
    assert ar.publish_decision({"season": S, "band": "FAIL"}, S, 3, 3, other) == \
        (False, "premise check FAIL: not published")
    only_marginal = dict(OVERRIDE, overrides_bands=["MARGINAL"])
    assert ar.publish_decision({"season": S, "band": "FAIL"}, S, 3, 3, only_marginal)[0] is False


def test_no_override_key_behaves_as_before():
    assert ar.premise_override({}) is None
    assert ar.publish_decision({"season": S, "band": "FAIL"}, S, 3, 3, None)[0] is False
    assert "talk, not ship" in ar.publish_decision({"season": S, "band": "MARGINAL"}, S, 3, 3)[1]


@pytest.mark.parametrize("bad", [
    "yes", {}, dict(OVERRIDE, by=""), dict(OVERRIDE, date="10-29"),
    dict(OVERRIDE, overrides_bands=[]), dict(OVERRIDE, overrides_bands=["UNSTABLE"]),
    dict(OVERRIDE, overrides_bands="FAIL"), {k: v for k, v in OVERRIDE.items() if k != "reason"},
])
def test_a_malformed_override_raises(bad):
    with pytest.raises(ValueError, match="advice_premise_override"):
        ar.premise_override({"advice_premise_override": bad})


def test_the_build_says_every_week_that_it_published_on_the_override(tmp_path, monkeypatch, capsys):
    import json
    import modules.data_loader as dl
    (tmp_path / "config" / "snapshots").mkdir(parents=True)
    (tmp_path / ar.GATE_RELPATH).write_text(json.dumps({"season": S, "band": "FAIL"}))
    monkeypatch.setattr(dl, "SEASON_CONFIG", {"advice_premise_override": OVERRIDE})
    monkeypatch.setattr(ar, "CURRENT_SEASON", S)
    monkeypatch.setattr(ar, "ADVICE_PUBLISH_FROM_WEEK", 3)
    out = ar.run_advice_safely(tmp_path, None, 3, builder=lambda data, week, publish, **k:
                               {"ran": True, "published": publish, "week": week})
    assert out["published"] and out["premise_override"]["by"] == "Nick"
    assert out["publish_reason"] == "published on Nick's override of a FAIL premise gate (10-29)"
    monkeypatch.setattr(dl, "SEASON_CONFIG", {"advice_premise_override": dict(OVERRIDE, date="x")})
    with pytest.raises(ValueError):                       # a config error is not swallowed
        ar.run_advice_safely(tmp_path, None, 3, builder=lambda *a, **k: {"ran": True})
    # report_builder prints "C2/C3 published: <publish_reason>" every build
    import inspect
    from modules import report_builder as rb
    assert "C2/C3 {state}: {out.get('publish_reason')}" in inspect.getsource(rb._run_advice_guarded)


def test_the_live_config_carries_nicks_override_and_it_is_well_formed():
    o = ar.premise_override()
    assert o["by"] == "Nick" and o["date"] == "2026-10-29" and set(o["overrides_bands"]) == {"FAIL", "MARGINAL"}


# 2 -- every plan and trade leaves every roster legal (rules 1-2, 5-6)
def _active(roster, il):
    return [p for p in roster if p not in il]


def test_a_waiver_plan_never_drops_an_il_player_and_keeps_the_active_count():
    w = _world(seed=4)
    projs, rosters = w[0], w[1]
    worst = min(rosters["Hayden"], key=lambda n: projs[n].projected_fppg)
    projs[worst].out_weeks = [2, 3]                      # out: the cheapest drop there is
    ctxs = {"this_week": (_ctx(w, sims=40), _ctx(w, sims=200))}
    free = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3, protected_week=1)
    assert any(r.drop == worst for r in free.this_week), "without IL he is the drop"
    plan = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3,
                           protected_week=1, il={worst})
    assert plan.this_week and all(r.drop != worst for r in plan.this_week)
    roster = list(rosters["Hayden"])
    before = len(_active(roster, {worst}))
    for r in plan.this_week:                             # apply the plan in order
        assert r.drop is not None and r.drop in roster and r.add not in roster
        roster = [p for p in roster if p != r.drop] + [r.add]
        assert len(_active(roster, {worst})) == before <= 15
    assert worst in roster and len(plan.this_week) <= 3


def test_trades_never_move_an_il_player_and_leave_both_rosters_legal():
    w = _world(seed=2, n_players=70)
    projs, rosters, nba, weeks, fas = w
    small = {m: r[:6] for m, r in rosters.items()}
    il = {"Nick": {small["Nick"][0]}, "Hayden": {small["Hayden"][0]}}
    sc = mv.build_context(projs, small, nba, weeks, "regular_season", 1, extra_players=fas, sims=40)
    fc = mv.build_context(projs, small, nba, weeks, "regular_season", 1, extra_players=fas, sims=120)
    shown, counts = adv.find_trades(sc, fc, None, adv.PlayerIndex(), None, il=il)
    moved = {p for t in shown for p in t.a_sends + t.b_sends + [t.a_drops, t.b_drops] if p}
    assert not moved & (il["Nick"] | il["Hayden"])
    for t in shown:
        for m, gives, gets, drop in ((t.manager_a, t.a_sends, t.b_sends, t.a_drops),
                                     (t.manager_b, t.b_sends, t.a_sends, t.b_drops)):
            after = [p for p in small[m] if p not in gives and p != drop] + gets
            assert len(_active(after, il.get(m, set()))) <= len(_active(small[m], il.get(m, set())))


def test_adds_never_exceed_the_weekly_budget():
    w = _world(seed=5)
    ctxs = {"this_week": (_ctx(w, sims=40), _ctx(w, sims=200))}
    for budget in (0, 1, 3):
        plan = adv.waiver_plan("Benton", ctxs, w[4], protected=[], adds_remaining=budget,
                               protected_week=1)
        assert len(plan.this_week) <= budget


# 3 -- the this_week plan values the week its moves first take effect
def test_this_week_is_the_week_after_the_report_week():
    """Section 10 for report week N lands in week N+1's Monday window, and a
    move made there takes effect that week (rules 4, 7). The this_week
    context is built at N and values exactly week N+1 -- every day of it."""
    w = _world()
    c = _ctx(w, window="this_week", sims=40)              # current_week=1
    assert c.weeks == [2] and mv.window_weeks("this_week", 1) == [2]
    import inspect
    src = inspect.getsource(ar.build_advice)
    assert '"for_week": week + 1' in src and 'ctx("this_week", week, short_n)' in src


# 4 -- no waiver claims in a league with no waivers (rule 8)
CLAIM = re.compile(r"on waivers|waiver (claim|period|wire priority|order)|clears? waivers|"
                   r"\bclaim(ed|s)?\b|priority", re.I)


def _advice():
    rec = {"manager": "Nick", "window": "this_week", "add": "A", "drop": "B", "points": 40.0,
           "se": 5.0, "starts": 1.0, "per_week": 40.0, "floor": 10.0, "step": 1,
           "runner_up": {"add": "C", "drop": "B", "points": 30.0}, "contested_with": ["Hayden"],
           "first_shown_week": 1}
    return {"ran": True, "published": True, "launched": True, "week": 3, "for_week": 4,
            "plans": [{"manager": "Nick", "adds_remaining": 3, "this_week": [rec],
                       "regular_season": [dict(rec, window="regular_season")], "note": ""}],
            "trades": [], "trade_counts": {"not_shown": 0},
            "bar": {"per_week": 10, "se_mult": 2, "this_week_floor": 10, "season_floor": 120}}


def test_no_rendered_string_claims_a_waiver_period():
    a = _advice()
    for text in (rr.render_html(a), rr.render_preview_page(a)):
        assert not CLAIM.search(text), CLAIM.search(text)
    md = rr.render_markdown(a, ["Nick"])
    body = md.split("\n", 1)[1]                          # the drafter's rules may name what NOT to say
    assert not CLAIM.search(body)
    assert "no waivers" in md and "worth far more" in md  # the drafter is told both


# 5 -- a week with no mutual-gain trade says so in one line
def test_no_trade_this_week_is_one_line():
    a = _advice()
    html = rr.render_html(a)
    assert html.count("No trade cleared the bar for both sides this week.") == 1
    md = rr.render_markdown(a, ["Nick"])
    assert md.count("Trades: none cleared the bar for both sides this week.") == 1


# Found in the 10-29 preview: Ivica Zubac, a free agent tagged O, was a
# this-week add for Nick and Hayden -- marginal value read the free agents'
# tags as HEALTHY because Tags keeps them apart.
def test_marginal_value_reads_the_free_agents_tags():
    import importlib
    import inspect
    fis = importlib.import_module("modules.fetch_injury_statuses")
    tags = fis.Tags({"Rostered Guy": "Q"}, {"Ivica Zubac": "O", "Healthy FA": "HEALTHY"})
    merged = ar.advice_statuses(tags)
    assert merged.get("Ivica Zubac") == "O" and merged.get("Rostered Guy") == "Q"
    assert merged.get("Ivica Zubač") == "O"                       # accent-proof
    assert dict(ar.advice_statuses(None)) == {}
    assert dict(ar.advice_statuses({"A": "O"})) == {"A": "O"}     # a plain dict still works
    clash = fis.Tags({"Same Name": "Q"}, {"Same Name": "O"})
    assert ar.advice_statuses(clash).get("Same Name") == "Q"      # the rostered tag wins
    src = inspect.getsource(ar.build_advice)
    assert "injury_statuses=statuses" in src and "advice_statuses(injury_statuses)" in src


def test_an_out_free_agent_is_worth_less_this_week_than_a_healthy_one():
    w = _world(seed=3)
    projs, rosters, nba, weeks, fas = w
    fa = fas[0]
    healthy = mv.marginal_value(_ctx(w, sims=300), "Nick", adds=[fa]).points
    out = mv.marginal_value(_ctx(w, sims=300, injury_statuses=ar.advice_statuses(
        __import__("importlib").import_module("modules.fetch_injury_statuses").Tags({}, {fa: "O"}))),
        "Nick", adds=[fa]).points
    assert out < healthy
