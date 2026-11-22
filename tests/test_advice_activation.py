"""
tests/test_advice_activation.py -- 4c3 s.2.2: the IL activation step, priced
(claude/HANDOFF_4C3_MARKET_ADVICE_2026-11-18.md; advice_v2.price_activation),
beside H53's tests/test_advice_plan.py.

THE MEASURE: the plan as it stands (the plan's own rule activates the
returners and drops whom it drops) against DOING NOTHING -- the returners
stay in their IL slots through the horizon, nobody is dropped, no other move
is made (roster_plan's "il_hold"; LEAGUE_RULES rule 3: legal, and while a
healthy player sits in IL the team can make no roster move).

A. The baseline is do-nothing: the hold plan keeps him in IL at both horizon
   windows with no drop, no add, no placement; a hold that cannot apply
   raises.
B. The steps' numbers are unchanged by pricing the activation; the activation
   plus the steps sum to the plan priced directly (1e-9 / 1e-6), and step 1's
   baseline is the activation's result.
C. A negative activation is reported as it is (the engine never clamps it).
D. "Needed before any add" is the activation's reason only when steps follow.
E. Determinism and manager order.
F. The outputs: advice_latest's activation (step 0, numbers, texts), the
   history row, the summary, advice_show, the run log's seconds.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import advice_v2_scenarios as S
from modules import advice_live as al
from modules import advice_v2 as av
from modules import roster_plan as rp
from test_advice_v2 import FAST, WEEKS6, _every_week, chat_inputs
from test_il_returns import returner_fixture, payload


def _act(inp, m="Nick"):
    return av.price_activation(inp, m, FAST)


# =============================================================================
# A. the baseline: do nothing
# =============================================================================

@pytest.mark.slow
def test_the_baseline_holds_him_in_il_with_no_drop_and_no_move():
    inp = chat_inputs(returner_fixture())
    step = av.activation_step(inp, "Nick")
    assert step["back"] == ["Hurt"] and step["drops"] == ["Weak"]
    w1, w2 = inp.horizon
    hold = av._hold_plan(inp, "Nick", step)
    P0 = av._plan(inp)
    for w in (w1, w2):
        v = hold[w]["Nick"]
        assert "Hurt" in v["il"] and "Hurt" not in v["active"] and v["held"] == ["Hurt"]
        assert v["activated"] == [] and v["activation_drops"] == [] and v["dropped"] == [] and v["added"] == []
    assert "Weak" in hold[w1]["Nick"]["active"]                          # nobody dropped
    assert "Hurt" in P0[w1]["Nick"]["active"] and "Weak" not in P0[w1]["Nick"]["active"]   # the plan's step
    # the opponents are untouched by his hold
    for m in ("Hayden", "Benton", "Garrett"):
        assert hold[w1][m]["active"] == P0[w1][m]["active"]
    a = _act(inp)
    b = av._price_base(inp, "Nick", FAST, base_plan=hold)
    assert a.wp_base == b["wp_base"] and a.step == step


def _rp_build(known, il=None):
    """test_roster_plan's league (start week 2, locked) with known moves."""
    import test_roster_plan as T
    from modules.data_loader import MANAGERS, PlayerIndex
    players, rosters = T._league()
    return rp.build(start_week=2, il_slots=il or {}, rosters=rosters, windows=T.WINDOWS,
                    players=PlayerIndex(players), statuses={n: "HEALTHY" for n in players}, rules=T.RULES,
                    standin_gp=T.GP, order=list(MANAGERS), drops=T.activation_ctx(players), known=known)


def test_the_roster_plans_hold_keeps_him_in_il_and_makes_no_move_there():
    il = {"Nick": ["Nick_0"]}                                        # healthy: the plan activates him at 3
    base = _rp_build(None, il)
    assert base[3]["Nick"]["activated"] == ["Nick_0"]
    held = _rp_build({3: {"Nick": {"il_hold": ["Nick_0"]}}}, il)
    v = held[3]["Nick"]
    assert v["held"] == ["Nick_0"] and v["il"] == ["Nick_0"] and v["activated"] == [] and v["added"] == []
    assert sorted(v["active"]) == sorted(base[2]["Nick"]["active"])  # nothing moved
    assert held[4]["Nick"]["activated"] == ["Nick_0"]                # after the hold, the plan's own rule
    for m in ("Hayden", "Benton", "Garrett"):
        assert held[3][m]["active"] == base[3][m]["active"]


def test_a_hold_that_cannot_apply_raises():
    with pytest.raises(ValueError, match="not in an IL slot"):
        _rp_build({3: {"Nick": {"il_hold": ["Nick_3"]}}})
    with pytest.raises(ValueError, match="locked window"):
        _rp_build({2: {"Nick": {"il_hold": ["Nick_0"]}}}, {"Nick": ["Nick_0"]})


def test_merge_known_carries_the_hold_only_where_given():
    a = av.known_for(av.Move("Nick", "add_drop", "X", drop="Y"), 2)
    assert "il_hold" not in av.merge_known(a)[2]["Nick"]
    h = {2: {"Nick": {"il_place": [], "drop": [], "add": [], "il_activate": [], "il_hold": ["Hurt"]}}}
    assert av.merge_known(a, h)[2]["Nick"]["il_hold"] == ["Hurt"]


# =============================================================================
# B. the steps unchanged; telescoping with the activation
# =============================================================================

@pytest.mark.slow
def test_the_steps_numbers_do_not_move_and_the_activation_telescopes(monkeypatch):
    fx = returner_fixture()
    inp = chat_inputs(fx)
    pl = av.plan_for(inp, "Nick", FAST, av.RECOMMENDED, 2)
    assert pl.activation is not None and len(pl.steps) == 2
    # the same plan with the activation unpriced (as before 4c3): the steps are identical
    monkeypatch.setattr(av, "price_activation", lambda *a, **k: None)
    old = av.plan_for(chat_inputs(fx), "Nick", FAST, av.RECOMMENDED, 2)
    monkeypatch.undo()
    for s, o in zip(pl.steps, old.steps):
        assert s.priced.move == o.priced.move
        for f in ("dwp", "wp_base", "dpts", "dstarts", "dT_horizon", "dT_later", "dT_rs", "dT_po", "dpts_later"):
            assert getattr(s.priced, f) == getattr(o.priced, f), f
    a, t = pl.activation, pl.total
    rows = [a] + [s.priced for s in pl.steps]
    for k in (0, 1):
        assert sum(r.dwp[k] for r in rows) == pytest.approx(t.dwp[k], abs=1e-9)
        assert sum(r.dpts[k] for r in rows) == pytest.approx(t.dpts[k], abs=1e-6)
        assert sum(r.dstarts[k] for r in rows) == pytest.approx(t.dstarts[k], abs=1e-6)
        assert pl.steps[0].priced.wp_base[k] == pytest.approx(a.wp_base[k] + a.dwp[k], abs=1e-9)
        assert t.wp_base[k] == a.wp_base[k]                               # the total's baseline: doing nothing
    for f in ("dT_horizon", "dT_later", "dT_rs", "dT_po", "dpts_later"):
        assert sum(getattr(r, f) for r in rows) == pytest.approx(getattr(t, f), abs=1e-6), f
    # the total is measured against doing nothing either way (plan_total reads the step, not its price)
    assert old.total == t


@pytest.mark.slow
def test_no_returner_no_activation_and_the_total_is_unchanged():
    fx = returner_fixture(hurt=False, weak=True)
    inp = chat_inputs(fx)
    assert av.activation_step(inp, "Nick") is None and _act(inp) is None
    pl = av.plan_for(inp, "Nick", FAST, av.RECOMMENDED, 2)
    assert pl.activation is None
    if pl.steps:
        assert sum(s.priced.dwp[0] for s in pl.steps) == pytest.approx(pl.total.dwp[0], abs=1e-9)


# =============================================================================
# C. a negative activation, as it is
# =============================================================================

def negative_fixture():
    """Nick's 14 fillers each start (two a night, every night: no spare), Weak
    starts on the free night (5 FPPG, the least long-run value, so the one
    rule drops him), and Hurt returns at week 2's window but his NBA team
    plays no game in week 2: activating him costs week 2 Weak's starts and
    gains nothing until week 3."""
    fx = S.Fixture(weeks=WEEKS6)
    for i in range(14):
        fx.player(f"Filler {i}", _every_week(i % 7), 20.0, manager="Nick", keep=0.9 - 0.01 * i)
    fx.player("Weak", _every_week(0, 3), 5.0, manager="Nick", keep=0.0)
    fx.player("Hurt", [(w, d) for w in WEEKS6 if w != 2 for d in (5, 6)], 35.0, manager="Nick", il=True,
              keep=0.05, status="O")
    S.opponents_flat(fx, {"Hayden": 18.0, "Benton": 18.0, "Garrett": 18.0})
    for i in range(6):
        fx.player(f"Wire {i}", _every_week(0), 15.0 - i, fa=True)
    return fx


@pytest.mark.slow
def test_a_negative_activation_is_reported_as_it_is():
    inp = chat_inputs(negative_fixture())
    step = av.activation_step(inp, "Nick")
    assert step is not None and step["back"] == ["Hurt"] and step["drops"] == ["Weak"]
    a = _act(inp)
    assert a.dpts[0] < 0 and a.dstarts[0] < 0                          # week 2: Weak's starts, lost
    assert a.dpts[1] > 0                                               # week 3: Hurt plays
    d = payload(negative_fixture(), inp)["managers"]["Nick"]["activation"]
    t = {x["label"]: x for x in d["texts"]["v2"]["tiles"]}
    assert d["dpts"][0] < 0 and d["texts"]["v2"]["why"].startswith(("\u2212", "+"))
    assert t["Exp. starts"]["value"].startswith(("\u2212", "+"))


# =============================================================================
# D. the reason: "needed before any add" only when steps follow
# =============================================================================

@pytest.mark.slow
def test_needed_before_any_add_only_when_steps_follow():
    fx = returner_fixture()
    with_steps = payload(fx, chat_inputs(fx))["managers"]["Nick"]
    assert with_steps["plan"] and with_steps["activation"]["texts"]["v2"]["why"] == al.FIRST_TEXT
    inp = chat_inputs(fx)
    inp = replace(inp, managers={**inp.managers, "Nick": replace(inp.managers["Nick"], adds_left=0)})
    none = payload(fx, inp)["managers"]["Nick"]
    assert not none["plan"] and none["activation"]["step"] == 0
    assert none["activation"]["texts"]["v2"]["why"] != al.FIRST_TEXT
    assert "lineup start" in none["activation"]["texts"]["v2"]["why"]
    assert none["v2_empty"] == al.EMPTY_V2["adds"]


# =============================================================================
# E. determinism and manager order
# =============================================================================

@pytest.mark.slow
def test_same_inputs_same_activation_in_any_manager_order():
    fx = returner_fixture()
    a = av.advise_all(chat_inputs(fx), FAST, av.RECOMMENDED)
    inp = chat_inputs(fx)
    rev = {m: av.plan_for(inp, m, FAST) for m in sorted(inp.managers, reverse=True)}
    assert rev["Nick"].activation == a["Nick"].plan.activation
    assert a["Nick"].plan.activation == av.advise_all(chat_inputs(fx), FAST, av.RECOMMENDED)["Nick"].plan.activation


# =============================================================================
# F. the outputs
# =============================================================================

@pytest.mark.slow
def test_the_outputs_carry_the_activation_everywhere_the_plan_shows():
    from scripts import advice_show
    fx = returner_fixture()
    inp = chat_inputs(fx)
    pl = payload(fx, inp)
    e = pl["managers"]["Nick"]
    act = e["activation"]
    assert act["step"] == 0 and act["baseline"] == "hold" and act["text"].startswith("Hurt is back for week 2")
    assert act["texts"]["numbers"] == al.numbers_text(act, pl["horizon"], e["opponents"], show_title=pl["show_title_odds"])
    assert e["plan_total"]["includes_activation"] is True
    rows = [act] + e["plan"]
    for k in (0, 1):
        assert sum(r["dwp"][k] for r in rows) == pytest.approx(e["plan_total"]["dwp"][k], abs=2e-6)
        assert e["plan"][-1]["cumulative"]["dwp"][k] == pytest.approx(e["plan_total"]["dwp"][k], abs=2e-6)
    hist = al.history_row(pl, published=False)["managers"]["Nick"]
    assert hist["activation"]["dwp"] == act["dwp"] and "texts" not in hist["activation"]
    assert hist["plan_total"]["includes_activation"] is True
    line = next(l for l in al.summary_lines(pl) if l.startswith("ADVICE Nick"))
    assert f"Step: {act['text']} ({act['texts']['numbers']}) Then: " in line
    out = []
    pl.update(published=False)
    advice_show.show(pl, out=out.append)
    i = out.index(f"  Step: {act['text']}")
    assert out[i + 1] == f"    {act['texts']['numbers']}" and out[i + 3].startswith("    engine: step 0 against holding Hurt")
    assert any("activation + steps summed dwp" in x for x in out)
    card = al.hub_view(pl, [{"manager": "Nick", "team": "Team Nick"}])["cards"][0]
    assert card["step_numbers"] == act["texts"]["numbers"]


def test_a_file_from_before_4c3_prints_its_step_without_numbers():
    from scripts import advice_show
    act = {"week": 2, "back": ["Hurt"], "drops": ["Weak"], "returns": {},
           "text": "Hurt is back for week 2: activate him and drop Weak. It costs no add."}
    blob = {"run_id": "r", "mode": "nightly", "as_of": "x", "updated_text": "u", "error": None,
            "horizon": {"kind": "chat", "label": "Chat move", "weeks": [2, 3], "budget_week": 1, "closes": "c"},
            "inputs": {}, "seconds": {}, "show_title_odds": True,
            "managers": {"Nick": {"adds_left": 0, "opponents": {"2": "Hayden", "3": "Benton"}, "also_wanted_by": [],
                                  "activation": act, "move": None, "backup": None, "plan": [], "plan_total": None,
                                  "plan_stop": None, "note": "no adds left",
                                  "empty": "No adds left this week (week 1's budget)"}}}
    out = []
    advice_show.show(blob, out=out.append)
    i = out.index(f"  Step: {act['text']}")
    assert out[i + 1] == "  No adds left this week (week 1's budget)"
    assert al.history_row(dict(blob, league_day="d", cause=None, schema=1),
                          published=False)["managers"]["Nick"]["activation"] == act
    card = al.hub_view(blob, [{"manager": "Nick", "team": "Team Nick"}])["cards"][0]
    assert "step_numbers" not in card and card["step"] == act["text"]


def test_the_run_log_records_the_activations_seconds(monkeypatch, tmp_path):
    """Through run_step with the engine stubbed: seconds.activation and the
    detail line ("act 1.2+...")."""
    import types
    hz = av.Horizon(av.CHAT, (2, 3), 1, S.day(2, 0), S.close_of(1))

    def fake_build(base, now, data=None):
        return types.SimpleNamespace(), hz, {"week_first_day": S.day(1, 0).isoformat()}

    def fake_advise(inp, settings, weighting, max_steps=None, timings=None):
        timings["Nick"] = {"steps": [2.5], "total": 0.1, "activation": 1.2}
        return {}

    def fake_latest(**kw):
        return {"schema": al.SCHEMA, "run_id": "r", "mode": "nightly", "cause": None, "cause_text": "c",
                "as_of": "a", "league_day": "d", "horizon": {"label": "Chat move", "weeks": [2, 3]},
                "managers": {}, "error": None, "updated_text": "u", "inputs": {}}
    monkeypatch.setattr(al, "build", fake_build)
    monkeypatch.setattr(av, "advise_all", fake_advise)
    monkeypatch.setattr(al, "latest_payload", fake_latest)
    monkeypatch.setattr(al, "write", lambda *a, **k: None)
    monkeypatch.setattr(al, "plan_steps_max", lambda cfg=None: 2)
    out = al.run_step(tmp_path, S.at(1, 2), run_id="r", mode="nightly", cause=None)
    assert out["block"]["seconds"]["activation"] == {"Nick": 1.2}
    assert "Nick act 1.2+2.5" in out["detail"]
