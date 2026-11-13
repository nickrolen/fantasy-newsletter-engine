"""44c: four small IL fixes (claude/HANDOFF_44C_SMALL_FIXES_2026-11-13.md s.2;
44b's questions 3, 4, 7 and 8, Nick's answers via the reviewing session).

s.2.1 an early activation's step names the return day;
s.2.2 at the OPEN Monday window, today's O/OFS tag holds an IL occupant with
      no injury entry (Q/D/healthy is activated, as before);
s.2.3 the little-left check raises when nothing states it (no default top 4);
s.2.4 18b's hold-or-drop decision falls back on a keeper-watch failure:
      decide() without the keeper term (K = 0), in the same KEEPER WATCH
      FAILED line, and the run stays ok.
"""
from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import advice_v2_scenarios as S
from modules import advice_live as al
from modules import advice_v2 as av
from modules import injured_drop as idr
from modules import roster_plan as rp
from modules.data_loader import PlayerIndex
from test_advice_v2 import FAST, chat_inputs
from test_il_followup import MON5, _benton, _plan5
from test_il_returns import payload, returner_fixture
from test_injured_drop import CFG, _ctx, _keep_low, _plan_stakes, _three_out
from test_roster_plan import GP, RULES, WINDOWS, _build, _league, _p, activation_ctx

LA = ZoneInfo("America/Los_Angeles")


# =============================================================================
# s.2.1 the step names the return day of an early activation
# =============================================================================

def test_the_step_text_names_the_day_only_for_an_early_activation():
    early = {"week": 5, "back": ["Tyrese Haliburton"], "drops": ["Joel Embiid"],
             "returns": {"Tyrese Haliburton": "2026-11-21"}}
    assert al.step_text(early) == ("Tyrese Haliburton is back Saturday 11-21, for week 5: activate him "
                                   "and drop Joel Embiid. It costs no add.")
    plain = {**early, "returns": {}}
    assert al.step_text(plain) == ("Tyrese Haliburton is back for week 5: activate him and drop Joel "
                                   "Embiid. It costs no add.")
    both = {"week": 5, "back": ["Austin Reaves", "Trey Murphy III"], "drops": ["A", "B"],
            "returns": {"Austin Reaves": "2026-11-17", "Trey Murphy III": "2026-11-17"}}
    assert al.step_text(both).startswith("Austin Reaves and Trey Murphy III are back Tuesday 11-17, "
                                         "for week 5: activate them and drop A and B.")
    mixed = {**both, "returns": {"Trey Murphy III": "2026-11-19"}}
    assert al.step_text(mixed).startswith("Austin Reaves and Trey Murphy III are back for week 5 "
                                          "(Trey Murphy III from Thursday 11-19): activate them")
    with pytest.raises(KeyError):
        al.step_text({k: v for k, v in early.items() if k != "returns"})      # raise, don't default


def test_a_midweek_returner_activated_early_is_named_with_his_day_everywhere():
    """The chat fixture's Hurt returns on week 2's Wednesday and the plan
    activates him at week 2's window (44b s.4): the step carries his return
    date and the payload's text names the day."""
    fx = returner_fixture(hurt_out=[1], hurt_return=S.day(2, 2))
    inp = chat_inputs(fx)
    step = av.activation_step(inp, "Nick")
    wed = S.day(2, 2)
    assert step["returns"] == {"Hurt": wed.isoformat()}
    assert av.window_day(inp.plan, 2) == S.day(2, 0) < wed
    act = payload(fx, inp)["managers"]["Nick"]["activation"]
    want = (f"Hurt is back {wed.strftime('%A')} {wed.strftime('%m-%d')}, for week 2: activate him "
            f"and drop {step['drops'][0]}. It costs no add.")
    assert act["text"] == want and act["returns"] == {"Hurt": wed.isoformat()}


def test_a_return_by_the_window_day_reads_as_before():
    """Back by week 2's window (an entry out for week 1 only): no day named."""
    fx = returner_fixture(hurt_out=[1])
    inp = chat_inputs(fx)
    step = av.activation_step(inp, "Nick")
    assert step["back"] == ["Hurt"] and step["returns"] == {}
    assert payload(fx, inp)["managers"]["Nick"]["activation"]["text"].startswith("Hurt is back for week 2:")


def test_the_window_day_is_the_open_days_at_an_open_start_week():
    plan = av.PlanSpec({"known": {}, "start_week": 5, "open_day": MON5,
                        "windows": [(6, date(2026, 11, 23))]})
    assert av.window_day(plan, 5) == MON5 and av.window_day(plan, 6) == date(2026, 11, 23)
    with pytest.raises(KeyError):
        av.window_day(plan, 7)


# =============================================================================
# s.2.2 today's O tag holds an IL occupant with no entry at the OPEN window
# =============================================================================

def test_an_o_or_ofs_occupant_with_no_entry_stays_in_il_at_the_open_window():
    """Benton-like, open Monday window: Reaves O and Murphy OFS today, no
    entries. Yahoo keeps them in IL, so the plan does too, at week 5; the
    no-entry rule brings them back at week 6's window."""
    players, rosters, il = _benton()
    op = _plan5(players, rosters, il, open_day=MON5, statuses={"Reaves": "O", "Murphy": "OFS"})
    v = op[5]["Benton"]
    assert v["activated"] == [] and v["il"] == ["Murphy", "Reaves"] and not v["activation_drops"]
    assert op[6]["Benton"]["activated"] == ["Murphy", "Reaves"]


def test_a_q_d_or_healthy_occupant_with_no_entry_is_activated_at_the_open_window_as_before():
    """Benton's real case on 11-12's tags (Reaves Q, Murphy D): both
    activated at the open window, with the one rule's drops (44b)."""
    players, rosters, il = _benton()
    for tags in ({"Reaves": "Q", "Murphy": "D"}, {}):
        v = _plan5(players, rosters, il, open_day=MON5, statuses=tags)[5]["Benton"]
        assert v["activated"] == ["Murphy", "Reaves"] and v["activation_drops"] == ["Benton_14", "Benton_13"]
        assert not v["il"]


def test_one_held_one_activated():
    players, rosters, il = _benton()
    v = _plan5(players, rosters, il, open_day=MON5, statuses={"Reaves": "O", "Murphy": "Q"})[5]["Benton"]
    assert v["activated"] == ["Murphy"] and v["il"] == ["Reaves"] and v["activation_drops"] == ["Benton_14"]


def test_with_an_entry_the_entry_decides_whatever_todays_tag():
    """O today but an entry has him back by the window day: activated (the
    entry is Nick's statement, as at every window); an entry out all week:
    in IL, as before."""
    players, rosters, il = _benton()
    players["Reaves"] = _p("Reaves", 38.0, out=[4], ret=MON5.isoformat())
    players["Murphy"] = _p("Murphy", 38.0, out=[4, 5], ret="2026-11-23")
    v = _plan5(players, rosters, il, open_day=MON5, statuses={"Reaves": "O", "Murphy": "O"})[5]["Benton"]
    assert v["activated"] == ["Reaves"] and v["il"] == ["Murphy"]


def test_later_windows_keep_the_no_entry_rule():
    """Locked start week (after the close): today's O tag decides nothing at
    a later window -- no entry, back at week 6's window, as before 44c."""
    players, rosters, il = _benton()
    lk = _plan5(players, rosters, il, statuses={"Reaves": "O", "Murphy": "OFS"})
    assert lk[5]["Benton"]["il"] == ["Murphy", "Reaves"]
    assert lk[6]["Benton"]["activated"] == ["Murphy", "Reaves"]


def test_a_monday_move_shows_no_step_for_an_o_tagged_occupant_with_no_entry():
    """Advice reads the plan: the Monday move's open window holds O-tagged
    Hurt (no entry), so there is no step and the pick keeps him in IL; Q,
    the step (test_il_returns.test_a_monday_move_before_the_close_shows_the_step)."""
    inp = returner_fixture().inputs(horizon=(2, 3), balance=False)          # Hurt O, no entry
    assert inp.kind == av.MONDAY and inp.plan.args["open_day"] == S.day(2, 0)
    assert av.activation_step(inp, "Nick") is None
    P0 = av._plan(inp)
    assert P0[2]["Nick"]["il"] == ["Hurt"] and P0[3]["Nick"]["activated"] == ["Hurt"]


# =============================================================================
# s.2.3 the little-left check: stated, or a raise
# =============================================================================

def _returner_world():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-16")      # back at week 5's window
    return players, rosters


def test_an_unstated_little_left_check_raises():
    players, rosters = _returner_world()
    drops = replace(activation_ctx(players), little_left=None)
    with pytest.raises(rp.ActivationError, match="little-left check"):
        rp.build(start_week=2, il_slots={}, rosters=rosters, windows=WINDOWS, players=PlayerIndex(players),
                 statuses={n: "HEALTHY" for n in players}, rules=RULES, standin_gp=GP, drops=drops)


def test_a_stated_check_decides_the_protection():
    """Stated "no stakes" protects the top 4 (by keep chance); stated
    little-left protects the 6 keeper candidates."""
    players, rosters = _returner_world()
    keep = {f"Nick_{i}": (0.9 - 0.01 * i if i < 4 else 0.1) for i in range(15)}
    keep.update({"Nick_13": 0.5, "Nick_14": 0.49})                      # no. 5 and 6, the lowest projected
    base = rp.DropContext(config=idr.from_rules(), note=lambda: "no stakes (test)", stakes=None,
                          keep=lambda m: keep if m == "Nick" else {}, games=None, availability=None)

    def plan(little):
        return rp.build(start_week=2, il_slots={}, rosters=rosters, windows=WINDOWS,
                        players=PlayerIndex(players), statuses={n: "HEALTHY" for n in players},
                        rules=RULES, standin_gp=GP,
                        drops=replace(activation_ctx(players, base=base), little_left=little))
    four = plan(lambda m, w: None)[5]["Nick"]
    six = plan(lambda m, w: True)[5]["Nick"]
    assert four["activation_detail"][0]["protected_n"] == 4 and six["activation_detail"][0]["protected_n"] == 6
    assert not set(six["activation_drops"]) & {"Nick_13", "Nick_14"}


def test_advice_raises_for_a_manager_with_no_stated_stakes():
    fx = returner_fixture()
    inp = chat_inputs(fx)
    st = dict(inp.stakes)
    assert av.protected_for(inp, "Nick", FAST)                         # the fixture states every manager
    inp.stakes = {m: v for m, v in st.items() if m != "Nick"}
    with pytest.raises(KeyError, match="no stakes for Nick"):
        av.protected_for(inp, "Nick", FAST)
    inp.stakes = {**st, "Nick": None}                                  # stated: none -> the top N
    assert av.protected_for(inp, "Nick", FAST) == av.protected(inp.managers["Nick"], FAST.protected)


def test_the_bootstrap_is_the_one_stated_exception_and_the_replay_states_its_check(tmp_path):
    """drop_inputs: with no usable stakes file (the 18b bootstrap) the check
    is None -- the top 4, as before 44b -- because a raise would stop the run
    that writes the file. The 2025-26 replay's plan states its own check."""
    from modules import advice_replay, drop_inputs as di
    ctx = di.context(SimpleNamespace(), tmp_path, keep_week=4)
    assert ctx.note() is not None and ctx.little_left("Nick", 5) is None
    assert "little_left=little" in inspect.getsource(advice_replay.replay_plan)


# =============================================================================
# s.2.4 18b on a keeper-watch failure: decide() without the keeper term
# =============================================================================

def _broken_keep(m):
    raise rp.KeeperWatchFailed("AgeNotFound: no age for Somebody")


def test_decide_without_keepers_is_decide_with_k_zero_and_no_protection():
    """For a player outside every protection, the same answer and costs as
    decide() with K = 0; it records no rank or chance; and a top keeper is
    not protected (nothing ranks him)."""
    st = _plan_stakes()("Nick", 3)
    cand = idr.Candidate("X", 7, {w: 0.0 if w < 7 else 40.0 for w in range(3, 11)},
                         {w: 27.0 for w in range(3, 11)})
    keep = {"X": 0.01, **{f"K{i}": 0.5 for i in range(8)}}               # X is no. 9: unprotected
    k0 = replace(CFG, keeper_weight=0.0)
    a, b = idr.decide("Nick", cand, st, keep, k0), idr.decide_without_keepers("Nick", cand, st, CFG)
    assert (a.action, a.cost_hold, a.cost_drop) == (b.action, b.cost_hold, b.cost_drop)
    assert b.keeper_term == 0.0 and b.keep_rank is None and b.keep_chance is None
    assert "keeper watch failed" in b.reason
    top = idr.decide("Nick", cand, st, {"X": 0.99, "K0": 0.1}, CFG)
    assert top.action == idr.HOLD and "top-4" in top.reason
    assert "top-4" not in idr.decide_without_keepers("Nick", cand, st, CFG).reason
    with pytest.raises(KeyError):
        idr.costs(cand, st, None, CFG)                                 # the strict path still raises


def test_the_plan_decides_without_the_keeper_term_loudly_when_the_watch_fails():
    players, rosters = _three_out()
    keep = _keep_low(rosters["Nick"])
    good = _build(players, rosters, drops=_ctx(_plan_stakes(), keep))
    rp.take_notes()
    bad = _build(players, rosters, drops=replace(_ctx(_plan_stakes(), keep), keep=_broken_keep))
    (dg,), (db,) = good[3]["Nick"]["decisions"], bad[3]["Nick"]["decisions"]
    assert (db["player"], db["action"], db["carried_out"]) == (dg["player"], dg["action"], True)
    assert db["keeper_term"] == 0.0 and db["keep_rank"] is None and db["rule"].startswith("fallback: AgeNotFound")
    assert "rule" not in dg
    assert bad[3]["Nick"]["dropped"] == good[3]["Nick"]["dropped"] == ["Nick_2"]
    notes = rp.take_notes()
    assert notes == [rp.FALLBACK_NOTE.format(err="AgeNotFound: no age for Somebody")]
    assert "18b's hold-or-drop decisions without the keeper term (K = 0)" in notes[0]
    assert "lowest-projection rule" in notes[0]                        # one line for both fallbacks


def test_the_run_stays_ok_and_records_the_line(monkeypatch, tmp_path):
    """The nightly's step that builds an 18b plan on a broken keeper watch:
    ok, with the KEEPER WATCH FAILED line in the run row and the step."""
    from modules import nightly
    from pathlib import Path
    players, rosters = _three_out()
    keep = _keep_low(rosters["Nick"])
    rp.take_notes()

    def line():
        plan = _build(players, rosters, drops=replace(_ctx(_plan_stakes(), keep), keep=_broken_keep))
        assert plan[3]["Nick"]["decisions"][0]["rule"].startswith("fallback")
        return "priced"
    monkeypatch.setattr(nightly, "RUNS_FILE", tmp_path / "runs.jsonl")
    root = Path(__file__).parent.parent
    run = nightly.Run(root, "nightly", now=datetime(2026, 11, 12, 22, 0, tzinfo=LA), echo=lambda *a: None)
    stubs = {s: (lambda: "stub") for s in nightly.STEPS["nightly"]}
    stubs["line"] = line
    row = run.execute(stubs)
    assert row["outcome"] == "ok"
    kw = row["keeper_watch"]
    assert kw["failed"] and kw["steps"] == ["line"] and "K = 0" in kw["notes"][0]
    assert "KEEPER WATCH FAILED" in next(s["detail"] for s in row["steps"] if s["step"] == "line")
