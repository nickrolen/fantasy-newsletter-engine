"""
tests/test_advice_plan.py -- H53: advice as a plan, up to the manager's adds
left, each move priced after the one before it
(claude/HANDOFF_53_ADVICE_PLAN_2026-11-18.md; modules/advice_v2.plan_for).

A. The plan's pricing: C2's founding example (two streamers who fill the same
   crowded day: step 2's gain is below its standalone gain, and the plan picks
   the add that fills another day); the numbers add up (the steps' gains sum
   to the plan priced as one).
B. The stop rules: never more steps than adds left (or advice.plan_steps_max);
   stop when nothing beats standing pat; the step that would spend the last
   add clears last_add_bar or is not taken.
C. Never undo: a later step never drops an earlier step's add (the lock is
   what keeps it out: without it the screen offers it), never re-adds an
   earlier drop; protected players are never dropped in any step, with the
   keepers protected and with them unprotected (scenario 5's pattern).
D. Step 1 is today's top move on scenarios 1-7; determinism and manager
   order; "also wanted by" on every step; the backup is in nobody's plan.
E. The outputs: move == plan[0]; the cumulative numbers; the history row
   carries the plan; the summary line; the hub card ("1.", "2. Then",
   "Plan:"); advice_show's steps and --runs line; a file from before 53 (no
   plan) still renders on the hub and in advice_show; the config switch.
F. A real-state run (slow; skipped without the league's state): every
   manager's plan is legal and step 1 equals the current top move.
"""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import advice_v2_scenarios as S
from modules import advice_live as al
from modules import advice_v2 as av

ROOT = Path(__file__).resolve().parents[1]
FAST = av.Settings(price_sims=600, screen_sims=32, long_sims=8)
NO_OTHERS = {"Hayden": 0, "Benton": 0, "Garrett": 0}


def plan(fx_or_inputs, manager="Nick", settings=FAST, max_steps=None, **kw):
    inp = fx_or_inputs.inputs(**kw) if isinstance(fx_or_inputs, S.Fixture) else fx_or_inputs
    return inp, av.plan_for(inp, manager, settings, av.RECOMMENDED, max_steps)


def moves(pl):
    return [(s.priced.move.add, s.priced.move.drop) for s in pl.steps]


# =============================================================================
# A. pricing
# =============================================================================

@pytest.mark.slow
def test_two_streamers_on_the_same_crowded_day_the_second_add_fills_another_day():
    inp, pl = plan(S.scenario_plan_streamers(), adds=NO_OTHERS)
    assert [a for a, _d in moves(pl)][:2] == ["Streamer A", "Streamer C"]
    # B alone starts 4 and beats C; after A has the last Friday seat he starts 2
    stage2 = pl.stages[1]
    drop = pl.steps[1].priced.move.drop
    b = av.Move("Nick", "add_drop", "Streamer B", drop=drop)
    c = av.Move("Nick", "add_drop", "Streamer C", drop=drop)
    alone_b, alone_c = av.price(inp, "Nick", [b, c], FAST)
    after_b, after_c = av.price(stage2, "Nick", [b, c], FAST)
    # net of the spare's one Sunday start: B alone +4 - 1, after A +2 - 1
    assert sum(alone_b.dstarts) == pytest.approx(3.0, abs=0.05)
    assert sum(after_b.dstarts) == pytest.approx(1.0, abs=0.05)
    assert sum(after_b.dpts) < sum(alone_b.dpts)                     # step 2's gain below its standalone gain
    assert sum(alone_b.dpts) > sum(alone_c.dpts)                     # alone, B is the better second add
    assert sum(after_c.dpts) > sum(after_b.dpts)                     # after A, C is
    assert sum(after_c.dpts) == pytest.approx(sum(alone_c.dpts), abs=1.0)    # C's days were never contested


@pytest.mark.slow
@pytest.mark.parametrize("mk", [S.scenario_plan_streamers, S.scenario_plan_last_add])
def test_the_steps_gains_sum_to_the_plan_priced_as_one(mk):
    _inp, pl = plan(mk(), adds=NO_OTHERS)
    assert len(pl.steps) >= 2
    t = pl.total
    for k in (0, 1):
        assert sum(s.priced.dwp[k] for s in pl.steps) == pytest.approx(t.dwp[k], abs=1e-9)
        assert sum(s.priced.dpts[k] for s in pl.steps) == pytest.approx(t.dpts[k], abs=1e-6)
        assert sum(s.priced.dstarts[k] for s in pl.steps) == pytest.approx(t.dstarts[k], abs=1e-6)
    for f in ("dT_horizon", "dT_later", "dT_rs", "dT_po", "dpts_later"):
        assert sum(getattr(s.priced, f) for s in pl.steps) == pytest.approx(getattr(t, f), abs=1e-6), f
    # each step's baseline is the roster after the steps before it
    for a, b in zip(pl.steps, pl.steps[1:]):
        for k in (0, 1):
            assert b.priced.wp_base[k] == pytest.approx(a.priced.wp_base[k] + a.priced.dwp[k], abs=1e-9)


# =============================================================================
# B. the stop rules
# =============================================================================

@pytest.mark.slow
@pytest.mark.parametrize("adds,cap", [(3, None), (2, None), (1, None), (3, 2), (3, 1)])
def test_never_more_steps_than_adds_left_or_the_cap(adds, cap):
    inp, pl = plan(S.scenario_plan_streamers(), max_steps=cap, adds=dict(NO_OTHERS, Nick=adds))
    assert 1 <= len(pl.steps) <= min(adds, cap or adds)
    if cap is not None and cap < adds:
        assert len(pl.steps) == cap and pl.stop == "cap"
    for k, s in enumerate(pl.steps):
        assert pl.stages[k].managers["Nick"].adds_left == adds - k


@pytest.mark.slow
def test_the_plan_stops_when_nothing_beats_standing_pat():
    inp, pl = plan(S.scenario_1(), adds=NO_OTHERS)
    assert moves(pl)[0] == ("Cedric Coward", "Julius Randle")
    last = pl.stages[len(pl.steps)] if len(pl.stages) > len(pl.steps) else None
    if len(pl.steps) < 3:
        assert pl.stop in ("pat", "bar") and last is not None
        r = av.recommend(last, "Nick", FAST)
        assert r.top is None


@pytest.mark.slow
def test_the_add_that_spends_the_last_one_clears_the_bar_or_is_not_taken():
    _i, three = plan(S.scenario_plan_last_add(), adds=NO_OTHERS)
    _i, two = plan(S.scenario_plan_last_add(), adds=dict(NO_OTHERS, Nick=2))
    assert moves(three)[0][0] == moves(two)[0][0] == "FA Good"
    # with three adds the marginal second move leaves one add: no bar, it is taken
    assert len(three.steps) >= 2 and three.steps[1].priced.move.add == "FA Marginal"
    assert 0 < three.steps[1].score < FAST.last_add_bar
    # with two it would be the last add: below the bar, not taken
    assert len(two.steps) == 1 and two.stop == "bar"
    # and every step that did spend a last add cleared the bar
    for pl, adds in ((three, 3), (two, 2)):
        for k, s in enumerate(pl.steps):
            if adds - k == 1:
                assert s.score > FAST.last_add_bar


# =============================================================================
# C. never undo
# =============================================================================

def _assert_never_undone(inp, pl, manager, prot):
    added, dropped, placed = set(), set(), set()
    for s in pl.steps:
        mo = s.priced.move
        assert mo.drop not in added | placed, f"step {s.step} drops an earlier step's player: {mo.describe()}"
        assert mo.to_il not in added | placed
        assert s.priced.followup_drop not in added | placed
        assert mo.add not in dropped, f"step {s.step} adds back an earlier drop: {mo.describe()}"
        assert mo.drop not in prot and s.priced.followup_drop not in prot
        added.add(mo.add)
        dropped |= {x for x in (mo.drop, s.priced.followup_drop) if x}
        placed |= {x for x in (mo.to_il,) if x}


@pytest.mark.slow
def test_a_later_step_never_drops_an_earlier_add_the_lock_is_what_keeps_it_out():
    inp, pl = plan(S.scenario_plan_streamers(), adds=NO_OTHERS)
    _assert_never_undone(inp, pl, "Nick", av.protected_for(inp, "Nick", FAST))
    stage2 = pl.stages[1]
    first = pl.steps[0].priced.move
    assert first.add in stage2.locked["Nick"]
    assert first.add not in stage2.pool and first.drop not in stage2.pool
    assert not [m for m in av.candidate_moves(stage2, "Nick", FAST) if m.drop == first.add]
    unlocked = replace(stage2, locked={})
    assert [m for m in av.candidate_moves(unlocked, "Nick", FAST) if m.drop == first.add], \
        "without the lock the screen would offer dropping step 1's add: the test would prove nothing"


@pytest.mark.slow
@pytest.mark.parametrize("protected_n", [4, 1])
def test_protected_players_are_never_dropped_in_any_step_keepers_protected_or_not(protected_n):
    """Scenario 5 (Paolo yes, Jalen Johnson no) as a plan: with the top 4
    protected, and with only Luka (the pricing alone must keep Jalen Johnson
    in every step, as scenario 5c checks for step 1)."""
    st = replace(FAST, protected=protected_n)
    for jj in (False, True):
        inp, pl = plan(S.scenario_5(jalen_in_paolos_place=jj), settings=st, adds=NO_OTHERS)
        _assert_never_undone(inp, pl, "Nick", av.protected_for(inp, "Nick", st))
        if jj:
            assert all(s.priced.move.drop != "Jalen Johnson" and s.priced.followup_drop != "Jalen Johnson"
                       for s in pl.steps)
        else:
            assert pl.steps[0].priced.move.kind == "il_swap"


# =============================================================================
# D. step 1, determinism, the contest
# =============================================================================

SCENARIOS = [S.scenario_1, S.scenario_2, lambda: S.scenario_3(), S.scenario_4,
             lambda: S.scenario_5(False), lambda: S.scenario_5(True), S.scenario_6,
             lambda: S.scenario_7(18), lambda: S.scenario_7(45)]


@pytest.mark.slow
@pytest.mark.parametrize("i", range(len(SCENARIOS)))
def test_step_1_is_todays_top_move_on_scenarios_1_to_7(i):
    kw = {"now": S.at(1, 2, 15)} if i == 2 else {}
    inp = SCENARIOS[i]().inputs(**kw)
    top = av.recommend(inp, "Nick", FAST).top
    pl = av.plan_for(inp, "Nick", FAST)
    if top is None:
        assert pl.steps == ()
    else:
        assert pl.steps[0].priced.move == top.move
        assert pl.steps[0].priced.dwp == top.dwp and pl.steps[0].priced.dpts == top.dpts


@pytest.mark.slow
def test_same_inputs_same_plans_in_any_manager_order():
    kw = dict(opponents=S.CONTEST_OPPONENTS, balance=False)
    a = av.advise_all(S.scenario_8().inputs(**kw), FAST)
    inp = S.scenario_8().inputs(**kw)
    rev = {m: av.plan_for(inp, m, FAST) for m in sorted(inp.managers, reverse=True)}
    for m in a:
        key = lambda pl: [(s.priced.move, round(s.score, 12), s.priced.followup_drop) for s in pl.steps]
        assert key(a[m].plan) == key(rev[m]), m
        assert a[m].plan.stop == rev[m].stop


@pytest.mark.slow
def test_also_wanted_by_on_every_step_and_the_backup_is_in_nobodys_plan():
    inp = S.scenario_8().inputs(opponents=S.CONTEST_OPPONENTS, balance=False, adds={"Benton": 0, "Garrett": 0})
    adv = av.advise_all(inp, FAST)
    plans = {m: set(a.plan.adds) for m, a in adv.items()}
    anyone = set().union(*plans.values())
    for m, a in adv.items():
        if a.top is None:
            continue
        assert a.plan.steps[0].priced is a.top
        assert a.also_wanted_by == av.also_wanted(adv, m, a.top.move.add)
        for s in a.plan.steps:
            assert set(av.also_wanted(adv, m, s.priced.move.add)) == \
                {o for o, adds in plans.items() if o != m and s.priced.move.add in adds}
        if a.backup is not None:
            assert a.backup.move.add not in anyone
    assert adv["Nick"].also_wanted_by == ("Hayden",) and adv["Hayden"].also_wanted_by == ("Nick",)


# =============================================================================
# E. the outputs
# =============================================================================

@pytest.fixture(scope="module")
def streamers_payload():
    """advice_latest.json's payload, end to end, for the streamers fixture."""
    inp = S.scenario_plan_streamers().inputs(adds=NO_OTHERS)
    hz = av.Horizon(av.MONDAY, (1, 2), 1, S.day(1, 0), S.close_of(1))
    adv = av.advise_all(inp, FAST)
    p = al.latest_payload(run_id="r53", mode="nightly", cause=None, now=S.at(1, 0, 0, 1), inputs=inp, hz=hz,
                          meta={"anchor": "2026-11-02"}, advice=adv, weighting=av.RECOMMENDED.name,
                          settings=FAST, seconds={})
    return p


@pytest.mark.slow
def test_move_is_plan_0_and_the_cumulative_numbers_add_up(streamers_payload):
    e = streamers_payload["managers"]["Nick"]
    assert e["move"] is e["plan"][0] and e["plan"][0]["step"] == 1
    assert len(e["plan"]) >= 2
    run = [0.0, 0.0]
    for d in e["plan"]:
        run = [run[k] + d["dwp"][k] for k in (0, 1)]
        assert d["cumulative"]["dwp"] == pytest.approx(run, abs=1e-5)
    assert e["plan_total"]["dwp"] == pytest.approx(run, abs=1e-5)
    assert e["plan"][1]["text"]["step"].startswith("2. Then add Streamer C")
    assert e["plan"][0]["text"]["step"].startswith("1. Add Streamer A")
    assert e["plan_total"]["text"].startswith("Plan: ") and "vs Hayden this week" in e["plan_total"]["text"]
    assert e["plan_stop"]["code"] in ("adds", "pat", "bar")
    json.dumps(streamers_payload)


@pytest.mark.slow
def test_the_history_row_and_the_summary_carry_the_plan(streamers_payload):
    row = al.history_row(streamers_payload, published=True)
    h = row["managers"]["Nick"]
    assert [d["add"] for d in h["plan"]] == [d["add"] for d in streamers_payload["managers"]["Nick"]["plan"]]
    assert h["top"] == {k: v for k, v in h["plan"][0].items() if k not in ("step", "also_wanted_by")}
    for d in h["plan"]:
        for k in ("step", "dwp", "dpts", "dstarts", "dT_later", "score"):
            assert k in d
    assert h["plan_total"]["dwp"] and h["plan_stop"]
    json.dumps(row)
    line = next(l for l in al.summary_lines(streamers_payload) if l.startswith("ADVICE Nick"))
    assert "1) Add Streamer A" in line and "2) Add Streamer C" in line and "-- Plan: " in line
    assert "each step" not in line


@pytest.mark.slow
def test_the_hub_card_numbers_the_steps_then_the_plan_then_the_backup(streamers_payload):
    from test_advice_live import _page, _view
    view = al.hub_view(streamers_payload, [{"manager": m, "team": f"Team {m}"} for m in
                                           ("Nick", "Hayden", "Benton", "Garrett")])
    card = next(c for c in view["cards"] if c["manager"] == "Nick")
    assert card["move"].startswith("1. Add Streamer A")
    assert card["steps"][0]["move"].startswith("2. Then add Streamer C")
    assert card["plan"].startswith("Plan: ")
    _p, page = _page(view)
    v = _view(page)
    i1, i2 = v.index("1. Add Streamer A"), v.index("2. Then add Streamer C")
    ip = v.index("Plan: ")
    assert i1 < i2 < ip
    if card["backup"]:
        assert ip < v.index("is gone: ")
    # the page computes nothing: every number on the view is a payload string
    import re
    from test_hub import payload_strings, visible_text
    known = " ".join(payload_strings(_p["advice"]))
    for n in re.findall(r"\d+(?:[.,:-]\d+)*", visible_text(v)):
        assert n in known, n


@pytest.mark.slow
def test_the_hub_cards_annotate_and_strip_the_steps_players(streamers_payload):
    from modules import hub_cards
    view = al.hub_view(streamers_payload, [{"manager": "Nick", "team": "Team Nick"}])
    st = view["cards"][0]["steps"][0]
    assert "Streamer C" in st["players"]["move"]
    # the walk the cards invariant uses names every step's players
    p = {"advice": view, "rosters": {}, "free_agents": {"rows": []}, "stash": {"rows": []},
         "trade_block": {"cards": []}, "moves": {"weeks": []}}
    names = [n for n, _k in hub_cards.shown_names(p)]
    assert "Streamer C" in names
    hub_cards.strip(p)
    assert "move_segs" not in view["cards"][0]["steps"][0]


@pytest.mark.slow
def test_advice_show_prints_numbered_steps_the_total_and_the_runs_line(streamers_payload):
    sys.path.insert(0, str(ROOT / "scripts"))
    show_mod = importlib.import_module("advice_show")
    lines = []
    show_mod.show(streamers_payload, out=lines.append)
    text = "\n".join(lines)
    assert "Step 1: Add Streamer A" in text and "Step 2: Add Streamer C" in text
    assert text.index("Step 2:") < text.index("  Plan: ")
    lines = []
    show_mod.show_runs([al.history_row(streamers_payload, published=False)], 1, out=lines.append)
    assert "Nick: 1) +Streamer A -" in lines[-1] and " 2) +Streamer C -" in lines[-1]


def test_a_file_from_before_53_still_renders_on_the_hub_and_in_advice_show():
    from test_advice_live import _fake_latest, _page, _view
    old = _fake_latest()
    assert "plan" not in old["managers"]["Mgr One"]
    view = al.hub_view(old, [{"manager": "Mgr One", "team": "Team Uno"}, {"manager": "Mgr Two", "team": "Two"}])
    card = view["cards"][0]
    assert card["move"] == "Add Free Guy, drop Yan Beta" and card["steps"] == [] and card["plan"] == ""
    _p, page = _page(view)
    assert '<div class="ad-m">Add Free Guy, drop Yan Beta</div>' in _view(page)
    sys.path.insert(0, str(ROOT / "scripts"))
    show_mod = importlib.import_module("advice_show")
    lines = []
    show_mod.show(old, out=lines.append)
    assert "  Move: Add Free Guy, drop Yan Beta" in lines and "  Backup: Add Backup Guy, drop Yan Beta" in lines
    hist = al.history_row(old, published=False)
    lines = []
    show_mod.show_runs([{**hist, "managers": {m: {k: v for k, v in e.items() if k != "plan"}
                                               for m, e in hist["managers"].items()}}], 1, out=lines.append)
    assert "Mgr One: 1) +Free Guy -Yan Beta" in lines[-1] and "Mgr Two: pat" in lines[-1]


def test_plan_steps_max_is_required_an_integer_within_the_budget():
    from modules.data_loader import UnspecifiedRule
    assert al.plan_steps_max() in (1, 2, 3)
    with pytest.raises(UnspecifiedRule):
        al.plan_steps_max({"advice": {}})
    for bad in (0, 4, "3", 2.0, True, None):
        with pytest.raises(al.AdviceInputError):
            al.plan_steps_max({"advice": {"plan_steps_max": bad}})
    assert al.plan_steps_max({"advice": {"plan_steps_max": 1}}) == 1
    src = Path(al.__file__).read_text(encoding="utf-8")
    assert "max_steps=plan_steps_max()" in src


def test_the_run_log_records_each_steps_seconds(tmp_path, monkeypatch):
    """Nick, 11-18: each step's pricing seconds go in the run's advice block
    (the run log) and its detail line. Through run_step, the engine stubbed."""
    from types import SimpleNamespace
    from modules import advice_v2 as av_mod
    src = Path(al.__file__).read_text(encoding="utf-8")
    run = src[src.index("def run_step("):src.index("def _move_players(")]
    assert 'seconds["steps"]' in run and "timings=timings" in run
    hz = av.Horizon(av.MONDAY, (1, 2), 1, S.day(1, 0), S.close_of(1))
    monkeypatch.setattr(al, "build", lambda *a, **k: (SimpleNamespace(), hz, {"week_first_day": "2026-11-02"}))

    def fake_advise_all(inp, settings, weighting, max_steps=None, timings=None):
        timings.update({"Nick": {"steps": [7.1, 5.8, 6.0], "total": 0.0}, "Hayden": {"steps": [0.0], "total": None}})
        return {}
    monkeypatch.setattr(av_mod, "advise_all", fake_advise_all)
    monkeypatch.setattr(al, "latest_payload", lambda **k: {"run_id": "r", "error": None, "managers": {},
                                                           "horizon": {"label": "Monday move", "weeks": [1, 2]}})
    monkeypatch.setattr(al, "write", lambda *a, **k: None)
    monkeypatch.setattr(al, "history_row", lambda *a, **k: {})
    monkeypatch.setattr(al, "summary_lines", lambda p: [])
    out = al.run_step(tmp_path, S.at(1, 0, 0, 1), run_id="r", mode="poll", cause=None)
    assert out["block"]["seconds"]["steps"] == {"Nick": [7.1, 5.8, 6.0], "Hayden": [0.0]}
    assert "Nick 7.1+5.8+6" in out["detail"] and "Hayden" not in out["detail"]


# =============================================================================
# F. the real state (slow; skipped without it)
# =============================================================================

REAL = [ROOT / "output" / "tag_records.jsonl", ROOT / "output" / "stakes.json", ROOT / "config" / "ROSTERS.json",
        ROOT / "data" / "PLAYERLIST.xlsx", ROOT / "data" / "IL_SLOTS.json"]


@pytest.mark.slow
@pytest.mark.skipif(not all(p.is_file() for p in REAL), reason="needs the league's real state")
def test_every_real_plan_is_legal_and_step_1_is_the_current_top_move():
    """The real state, read in place (nothing written), at the latest tag
    fetch's clock: every manager's plan within his adds left, his roster legal
    after every step (15 active, 2 IL), nobody's step undoing an earlier one,
    no claimed player added, and step 1 the top move recommend() gives."""
    import contextlib
    import io
    from datetime import datetime, timedelta
    from modules import tag_records
    now = datetime.fromisoformat(tag_records.latest(ROOT)["taken_at"]) + timedelta(minutes=1)
    with contextlib.redirect_stdout(io.StringIO()):
        inp, hz, _meta = al.build(ROOT, now)
    if json.loads((ROOT / "output" / "stakes.json").read_text(encoding="utf-8")).get("schema") == 2:
        pytest.skip("output/stakes.json predates the causal leverage (schema 2): pull state")
    settings = av.Settings()
    adv = av.advise_all(inp, settings, max_steps=al.plan_steps_max())
    for m, a in adv.items():
        st = inp.managers[m]
        top = av.recommend(inp, m, settings).top
        assert (a.top and a.top.move) == (top and top.move), m
        pl = a.plan
        assert len(pl.steps) <= max(0, st.adds_left)
        _assert_never_undone(inp, pl, m, av.protected_for(inp, m, settings))
        for k, s in enumerate(pl.steps):
            stage = pl.stages[k]
            assert s.priced.move.add in stage.pool and s.priced.move.add not in inp.reserved
            if k + 1 < len(pl.stages):
                nxt = pl.stages[k + 1].managers[m]
                assert len(nxt.active) <= nxt.active_capacity and len(nxt.il) <= nxt.il_capacity
                assert nxt.adds_left == st.adds_left - (k + 1) >= 0
