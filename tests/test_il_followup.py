"""44b: the 44a follow-up (claude/HANDOFF_44B_IL_FOLLOWUP_2026-11-13.md).

s.1 the long-run value at 200 simulations with a TIE BAND (2 SEs of the
    paired difference; a tie goes to the lower projection, then the name);
s.2 Monday's window is OPEN until price_lock.window_close: the plan plays its
    start week as a window (known moves first, then steps 1-3);
s.3 a keeper-watch failure falls back, loudly, to the lowest-projection rule;
s.4 a mid-week returner is activated at the window when that is worth more
    than waiting, by the same measure (a tie keeps him in IL);
s.5 advice's chat-move IL rule is the plan's (roster_plan.out_all_week);
s.6 a team with little left to play for protects its keeper candidates.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest

import advice_v2_scenarios as S
from modules import advice_v2 as av
from modules import injured_drop as idr
from modules import roster_plan as rp
from modules.data_loader import MANAGERS, PlayerIndex
from test_roster_plan import GP, RULES, WINDOWS, _build, _league, _p, activation_ctx, proj_value
from test_il_returns import returner_fixture
from test_advice_v2 import FAST, chat_inputs

ROOT = Path(__file__).parent.parent
LA = ZoneInfo("America/Los_Angeles")
MON5 = date(2026, 11, 16)                # week 5's window day (the real calendar)


def _draws_of(table):
    """value(roster) as per-simulation draws: the sum of each player's fixed draws."""
    return lambda r: sum(table[n] for n in r)


# =============================================================================
# s.1 precision
# =============================================================================

def test_the_long_run_settings_are_required_config():
    assert rp.longrun_rules() == {"sims": 200, "band": 2.0}
    assert av.Settings().long_sims == 200
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))["roster_moves"]
    assert "44b" in cfg["_longrun_sims"] and "44b" in cfg["_activation_tie_band"]


def test_a_planted_near_tie_goes_to_the_lower_projection():
    """A and B cost 10.0 and 11.0 long-run on average, noisily (SD 30 over 200
    sims): the 1.0 is well inside 2 SEs of the paired difference, so they are
    tied and the lower projection (B, 20 FPPG) goes, though A is cheaper."""
    rng = np.random.default_rng(7)
    t = {"A": 10 + 30 * rng.standard_normal(200), "B": 11 + 30 * rng.standard_normal(200),
         "K": np.full(200, 99.0), "R": np.full(200, 50.0)}
    t["A"] += 10 - t["A"].mean()
    t["B"] += 11 - t["B"].mean()
    proj = {"A": 30.0, "B": 20.0, "K": 40.0, "R": 35.0}
    d, det = rp.activation_drops(manager="Nick", week=5, active=list(t), il=[], back=["R"], n=1,
                                 chance=lambda x: {"K": 0.9}.get(x, 0.0), protected_n=1,
                                 value=_draws_of(t), proj=lambda x: proj[x], band=2.0)
    assert det[0]["cheapest"] == "A" and det[0]["tied"] == ["A", "B"] and d == ["B"]


def test_a_clear_gap_goes_to_the_measure():
    """A costs 10, B 100 (small noise): no tie. A goes, though B's projection is lower."""
    rng = np.random.default_rng(8)
    t = {"A": 10 + rng.standard_normal(200), "B": 100 + rng.standard_normal(200),
         "K": np.full(200, 99.0), "R": np.full(200, 50.0)}
    proj = {"A": 30.0, "B": 20.0, "K": 40.0, "R": 35.0}
    d, det = rp.activation_drops(manager="Nick", week=5, active=list(t), il=[], back=["R"], n=1,
                                 chance=lambda x: {"K": 0.9}.get(x, 0.0), protected_n=1,
                                 value=_draws_of(t), proj=lambda x: proj[x], band=2.0)
    assert det[0]["tied"] == ["A"] and d == ["A"]


def test_the_paired_se_is_the_difference_of_the_draws():
    rng = np.random.default_rng(9)
    common = 50 * rng.standard_normal(200)
    a, b = common + 1.0, common + rng.standard_normal(200)        # common noise cancels when paired
    se = rp.paired_se(a - b)
    assert se == pytest.approx(np.std(a - b, ddof=1) / np.sqrt(200)) and se < 0.2
    assert rp.paired_se(5.0) == 0.0 and rp.within_band(np.zeros(3), 2.0)


def _real():
    from modules import data_loader as dl, tag_records
    from modules.projections import load_all_team_projections
    data = dl.load_all_data(ROOT)
    try:
        rp.load_il_slots(ROOT, data)
    except rp.ILSlotsError as e:
        pytest.skip(f"needs this week's IL file: {e}")
    return data, load_all_team_projections(data), tag_records.as_tags(tag_records.latest(ROOT))


def _events(plan):
    return [(w, m, v.get("activated"), v.get("activation_drops"),
             [(x["player"], x["activate"]) for x in v.get("midweek") or []])
            for w in sorted(plan) for m, v in plan[w].items() if v.get("activated") or v.get("midweek")]


def test_the_seed_does_not_change_a_decision_on_the_real_state():
    """The whole real plan rebuilt with the long-run measure at two seeds
    (200 sims, the band): every activation, drop and mid-week decision is the
    same. (Five seeds in 44B_RESULT s.1.)"""
    from modules import tag_records
    from modules.data_loader import CURRENT_SEASON
    data, tps, tags = _real()
    run = rp.for_run(data, tps, tags)
    ev = []
    for seed in (20261105, 3):
        lr = rp.LongRun(nba_schedule=data.nba_schedule, schedule_weeks=data.schedule["weeks"],
                        durability_prior=data.durability_prior, season=CURRENT_SEASON,
                        statuses=dict(run.args["statuses"]),
                        anchor=date.fromisoformat(tag_records.latest(ROOT)["league_day"]),
                        first_week=run.start_week + 1, last_week=23, seed=seed)
        ev.append(_events(rp.build(**{**run.args, "drops": replace(run.args["drops"], longrun=lr.draws)})))
    assert ev[0] == ev[1] and ev[0]


# =============================================================================
# s.2 Monday's window is open until it closes
# =============================================================================

def _calendar():
    """The real calendar (SCHEDULE.json and the NBA schedule with tip times)."""
    from modules.nba_schedule import schedule_path
    sched = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    nba = json.loads(schedule_path(ROOT).read_text(encoding="utf-8"))
    return SimpleNamespace(schedule=sched, nba_schedule=nba)


def test_the_window_is_open_on_its_day_until_the_close_the_ledgers_close():
    from modules import price_lock
    cal = _calendar()
    close = price_lock.window_close(MON5, cal.nba_schedule)
    assert rp.window_open(cal, 5, datetime(2026, 11, 16, 0, 5, tzinfo=LA)) == MON5      # the 12:01 run
    assert rp.window_open(cal, 5, close - timedelta(minutes=1)) == MON5
    assert rp.window_open(cal, 5, close) is None                                       # closed: locked
    assert rp.window_open(cal, 5, datetime(2026, 11, 17, 0, 5, tzinfo=LA)) is None     # Tuesday
    assert rp.window_open(cal, 4, datetime(2026, 11, 16, 0, 5, tzinfo=LA)) is None     # another week
    src = inspect.getsource(rp.window_open)
    assert "price_lock.window_close" in src and "timedelta" not in src                   # one close


def _benton():
    """A Benton-like 11-16: two IL occupants with no entries (Reaves, Murphy:
    back at the next window), a full 15 active; start week 5 (the IL file's)."""
    players, rosters = _league()
    for n in ("Reaves", "Murphy"):
        players[n] = _p(n, 38.0)
        rosters["Benton"].append(n)
    return players, rosters, {"Benton": ["Reaves", "Murphy"]}


def _plan5(players, rosters, il, open_day=None, known=None, used=None, statuses=None):
    tags = {n: "HEALTHY" for n in players}
    tags.update(statuses or {})
    return rp.build(start_week=5, il_slots=il, rosters=rosters,
                    windows=[(w, d) for w, d in WINDOWS if w > 5], players=PlayerIndex(players),
                    statuses=tags, rules=RULES, standin_gp=GP, drops=activation_ctx(players),
                    known=known, open_day=open_day, start_adds_used=used)


def test_benton_1116_open_plays_reaves_and_murphy_from_monday_and_locked_waits():
    """Open (Monday before the close): both activated at week 5 with 44a's
    drops (the lowest projected unprotected: Benton_14, Benton_13), and no IL
    mask for week 5. Locked (after the close, Tuesday): in IL all of week 5,
    activated at week 6."""
    players, rosters, il = _benton()
    op = _plan5(players, rosters, il, open_day=MON5)
    v = op[5]["Benton"]
    assert v["activated"] == ["Murphy", "Reaves"] and v["activation_drops"] == ["Benton_14", "Benton_13"]
    assert not v["il"] and {"Reaves", "Murphy"} <= set(v["active"])
    lk = _plan5(players, rosters, il)
    assert lk[5]["Benton"]["il"] == ["Murphy", "Reaves"] and lk[6]["Benton"]["activated"] == ["Murphy", "Reaves"]
    run = rp.Run(start_week=5, plan=op, players=PlayerIndex(players))
    assert run.il_for(5).get("Benton") == set()


def test_a_manager_who_already_activated_is_not_activated_twice():
    """A poll's sync shows Reaves activated (Benton_14 dropped): the IL file
    lists Murphy only, and the open plan activates Murphy alone."""
    players, rosters, il = _benton()
    rosters["Benton"].remove("Benton_14")
    il = {"Benton": ["Murphy"]}
    v = _plan5(players, rosters, il, open_day=MON5)[5]["Benton"]
    assert v["activated"] == ["Murphy"] and v["activation_drops"] == ["Benton_13"]
    assert v["active"].count("Reaves") == 1


def test_a_known_chat_move_at_the_window_applies_first():
    """The ledger's IL-Reaves -Benton_10 at week 5: applied first (step 0);
    the plan's own step 1 then activates Murphy only."""
    players, rosters, il = _benton()
    known = {5: {"Benton": {"il_place": [], "drop": ["Benton_10"], "add": [], "il_activate": ["Reaves"]}}}
    v = _plan5(players, rosters, il, open_day=MON5, known=known)[5]["Benton"]
    assert v["known"] == ["-Benton_10", "IL-Reaves"] and v["activated"] == ["Murphy"]
    assert v["activation_drops"] == ["Benton_14"] and "Benton_10" not in v["active"]


def test_the_open_windows_stand_ins_use_the_weeks_remaining_adds_and_its_tags():
    """An entry out all of week 5: placed in IL at the open window only when
    tagged O today (rule 2, the tag known); its stand-in counts against the
    adds left (2 used: 1 left)."""
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[5, 6], ret="2026-11-30")
    players["Nick_1"] = _p("Nick_1", 39.0, out=[5, 6], ret="2026-11-30")
    op = _plan5(players, rosters, {}, open_day=MON5, used={"Nick": 2},
                statuses={"Nick_0": "O", "Nick_1": "O"})
    v = op[5]["Nick"]
    assert v["il"] == ["Nick_0", "Nick_1"] and len(v["added"]) == 1 and v["waiting"] == 1
    q = _plan5(players, rosters, {}, open_day=MON5, statuses={"Nick_0": "Q", "Nick_1": "O"})[5]["Nick"]
    assert q["il"] == ["Nick_1"], "Q today: Yahoo refuses the IL slot at this window"
    lk = _plan5(players, rosters, {})
    assert 5 not in [w for w in lk if w > 5] and lk[6]["Nick"]["il"] == ["Nick_0", "Nick_1"]


def test_the_open_window_applies_the_midweek_choice_too():
    """s.2 with s.4: Nick_0 back Tuesday 11-17 (6/7 of 40 > 26): activated at
    the open week-5 window; locked, he waits for week 6."""
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-17")
    rosters_il = {"Nick": ["Nick_0"]}
    rosters["Nick"] = [n for n in rosters["Nick"]]
    players["Nick_15"] = _p("Nick_15", 26.5)
    rosters["Nick"] = [n for n in rosters["Nick"] if n != "Nick_0"] + ["Nick_15", "Nick_0"]
    op = _plan5(players, rosters, rosters_il, open_day=MON5)
    assert op[5]["Nick"]["midweek"][0]["activate"] is True and "Nick_0" in op[5]["Nick"]["active"]
    lk = _plan5(players, rosters, rosters_il)
    assert "Nick_0" in lk[5]["Nick"]["il"] and "midweek" not in lk[5]["Nick"]


def test_for_run_judges_the_window_at_the_runs_clock_and_the_closing_line_is_locked():
    """for_run reads now, else data.plan_now (set by the pricing entry points),
    else the league clock; the closing line sets plan_now to its own now, which
    is never before the close: its plans are the locked week's."""
    import modules.closing_line as cl
    import modules.title_odds_run as tor
    import modules.hub_state as hs
    from modules import advice_live as al
    assert inspect.getsource(cl.price).count("plan_now = now") == 2
    assert "data.plan_now = now" in inspect.getsource(tor.price)
    assert "data.plan_now = now" in inspect.getsource(hs.build)
    assert "data.plan_now = now" in (ROOT / "scripts" / "refresh_service.py").read_text(encoding="utf-8")
    assert "now=now" in inspect.getsource(al.build)
    src = inspect.getsource(rp.for_run)
    assert 'getattr(data, "plan_now", None)' in src and "window_open(data, start, now)" in src


def test_monday_open_on_the_real_state_activates_bentons_returners():
    """Real, unstubbed (the changed run path): today's state with the IL file
    moved to week 5 (as the 12:01 AM sync of 11-16 will write it, the same
    slots), the plan built at Monday 11-16 00:05 (open) and at the close
    (locked). Open: Reaves and Murphy play week 5 with the one rule's drops;
    locked: they sit week 5."""
    from modules import price_lock
    data, tps, tags = _real()
    il = json.loads((ROOT / "data" / "IL_SLOTS.json").read_text(encoding="utf-8"))
    if sorted(il["slots"].get("Benton", [])) != ["Austin Reaves", "Trey Murphy III"]:
        pytest.skip("the 11-12 state (Reaves and Murphy in Benton's IL slots) has moved on")
    data.il_slots = {**il, "fantasy_week": 5}
    data.start_adds_used = {}
    op = rp.for_run(data, tps, tags, now=datetime(2026, 11, 16, 0, 5, tzinfo=LA))
    assert op.open_day == MON5
    v = op.plan[5]["Benton"]
    assert v["activated"] == ["Austin Reaves", "Trey Murphy III"] and len(v["activation_drops"]) == 2
    close = price_lock.window_close(MON5, data.nba_schedule)
    lk = rp.for_run(data, tps, tags, now=close)
    assert lk.open_day is None and set(lk.plan[5]["Benton"]["il"]) == {"Austin Reaves", "Trey Murphy III"}


# =============================================================================
# s.3 the keeper watch fails: fall back, loudly
# =============================================================================

def _broken(players):
    def boom(m):
        raise rp.KeeperWatchFailed("AgeNotFound: no age for Somebody")
    return replace(activation_ctx(players), keep=boom)


def test_a_broken_keeper_watch_falls_back_to_the_lowest_projection_loudly():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-16")
    base = rp.DropContext(config=idr.from_rules(), note=lambda: "x", stakes=None,
                          keep=lambda m: {"Nick_14": 0.99} if m == "Nick" else {}, games=None,
                          availability=None)
    good = _build(players, rosters, drops=base)
    assert good[5]["Nick"]["activation_drops"] == ["Nick_13"] and "activation_rule" not in good[5]["Nick"]
    rp.take_notes()
    bad = rp.build(start_week=2, il_slots={}, rosters=rosters, windows=WINDOWS, players=PlayerIndex(players),
                   statuses={n: "HEALTHY" for n in players}, rules=RULES, standin_gp=GP,
                   drops=_broken(players))
    v = bad[5]["Nick"]
    assert v["activation_drops"] == ["Nick_14"] and v["activation_rule"].startswith("fallback: AgeNotFound")
    notes = rp.take_notes()
    assert any(n.startswith("KEEPER WATCH FAILED: AgeNotFound") and "lowest-projection rule" in n for n in notes)


def test_drop_inputs_turns_any_keeper_watch_error_into_one_failure_kept_for_the_run(monkeypatch):
    from modules import drop_inputs as di
    calls = []

    def kc(*a, **k):
        calls.append(1)
        raise ValueError("the keeper watch has no keep chance for X")
    monkeypatch.setattr(di, "keep_chances", kc)
    ctx = di.context(SimpleNamespace(), ".", keep_week=4)
    for _ in range(2):
        with pytest.raises(rp.KeeperWatchFailed, match="ValueError: the keeper watch"):
            ctx.keep("Nick")
    assert len(calls) == 1


def test_lines_and_title_odds_still_price_on_a_broken_keeper_watch(monkeypatch, tmp_path):
    """The season pass and the week's line price on a world whose keeper
    watch fails (test_roster_plan's moving world: two returns over 15 at
    week 12); the nightly run row records it and stays ok."""
    import modules.season_sim as ss
    import modules.simulator_betting as sb
    from modules import nightly
    from test_roster_plan import _moving_world
    data, teams, tags = _moving_world(monkeypatch)
    everyone = {n: p for tp in teams.values() for n, p in tp.players.items()}
    data.drop_context = _broken(everyone)
    rp.take_notes()

    def line():
        sp = ss.run_season(data, num_simulations=200, seed=7, team_projections=teams, through="regular",
                           injury_statuses=tags)
        assert sp.title_result().title_odds
        sb.simulate_week_matrix(data, *rp.week_rosters(rp.for_run(data, teams, tags), teams, 12)[:1],
                                sb.schedule_week(data, 12), None, sb.KeyedDraws(7, 50))
        return "priced"
    monkeypatch.setattr(nightly, "RUNS_FILE", tmp_path / "runs.jsonl")
    run = nightly.Run(ROOT, "nightly", now=datetime(2026, 11, 12, 22, 0, tzinfo=LA), echo=lambda *a: None)
    stubs = {s: (lambda: "stub") for s in nightly.STEPS["nightly"]}
    stubs["line"] = line
    row = run.execute(stubs)
    assert row["outcome"] == "ok"
    kw = row["keeper_watch"]
    assert kw["failed"] and kw["steps"] == ["line"] and "lowest-projection rule" in kw["notes"][0]
    assert "KEEPER WATCH FAILED" in next(s["detail"] for s in row["steps"] if s["step"] == "line")
    assert 'row.get("keeper_watch")' in inspect.getsource(nightly.main)


# =============================================================================
# s.4 a mid-week returner can be activated at the window
# =============================================================================

def _midweek(ret, fppg=40.0, low=None):
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", fppg, out=[3, 4], ret=ret)
    if low is not None:
        players["Nick_14"] = _p("Nick_14", low)
    return _build(players, rosters)


def test_an_early_return_is_activated_when_it_is_worth_it():
    """Back Tuesday 11-17: 6/7 of 40 (34.3) beats the 26 the rule drops."""
    plan = _midweek("2026-11-17")
    v = plan[5]["Nick"]
    assert v["midweek"][0]["activate"] is True and "Nick_0" in v["activated"]
    assert v["activation_drops"] == ["Nick_14"] and "Nick_0" in v["active"]


def test_a_late_return_is_not():
    """Back Saturday 11-21: 2/7 of 40 (11.4) does not beat 26: he waits."""
    v = _midweek("2026-11-21")[5]["Nick"]
    assert v["midweek"][0]["activate"] is False and "Nick_0" in v["il"]


def test_a_tie_keeps_him_in_il():
    """Back Wednesday 11-18 at 35 FPPG (5/7 of 35 = 25.0) against a 25.0
    drop: activating now gains exactly nothing, and a tie keeps him in IL."""
    v = _midweek("2026-11-18", fppg=35.0, low=25.0)[5]["Nick"]
    assert v["midweek"][0]["activate"] is False and "Nick_0" in v["il"]


# =============================================================================
# s.5 advice's chat-move IL rule is the plan's
# =============================================================================

def test_the_chat_move_and_the_plan_share_the_entry_rule():
    """Achy is out (entry) for all of week 2 and healthy-tagged today: IL-
    eligible for the chat move (s.5), and the plan's step 2 places such a
    player by the same function."""
    import modules.advice_live as al
    fx = returner_fixture(il_candidate=True, nick_active=13)
    fx.statuses.pop("Achy")                                       # no tag today
    inp = chat_inputs(fx)
    assert "Achy" in inp.il_eligible
    assert inp.il_eligible == {n for st in inp.managers.values() for n in st.active
                               if rp.out_all_week(inp.projections[n], 2)}
    assert "av.chat_il_eligible(actives, proj, hz.weeks[0])" in inspect.getsource(al.build)
    assert "out_all_week(P(n), week)" in inspect.getsource(rp.build)


# =============================================================================
# s.6 a little-left team protects its keeper candidates
# =============================================================================

def test_scenario_6_a_little_left_team_keeps_its_keeper_candidate():
    """Scenarios 6r5/6r6 (INJURED_DROP_DESIGN s.5), in the advice and the
    plan: Nick's Weak is keeper candidate no. 5 and worth nothing long-run.
    In the race (RS title 40%) only the top 4 are protected and the activation
    step drops him; out of it (1%: little left) the top 6 are, so neither
    the step nor any move drops him."""
    for rank_keep, (rs, dropped) in ((0.865, (0.4, True)), (0.865, (0.01, False)),
                                     (0.855, (0.01, False))):
        fx = returner_fixture(weak_keep=rank_keep)
        fx.rs_title = {"Nick": rs}
        inp = chat_inputs(fx)
        st = inp.managers["Nick"]
        rank = idr.keep_rank("Weak", dict(st.keep))[0]
        assert rank in (5, 6)
        prot = av.protected_for(inp, "Nick", av.Settings())
        assert len(prot) == (4 if rs > 0.05 else 6)
        step = av.activation_step(inp, "Nick")
        assert ("Weak" in step["drops"]) is dropped
        if not dropped:
            assert "Weak" in prot
            assert all(mo.drop != "Weak" for mo in av.candidate_moves(inp, "Nick", FAST))


def test_the_plan_and_advice_protect_the_same_players():
    """The parity: the plan's activation rule ranks with the same function and
    count as advice (roster_plan.protected_players, injured_drop.protected_count)."""
    fx = returner_fixture(weak_keep=0.865)
    fx.rs_title = {"Nick": 0.01}
    inp = chat_inputs(fx)
    st = inp.managers["Nick"]
    det = av._plan(inp)[2]["Nick"]["activation_detail"][0]
    assert det["protected_n"] == 6 == idr.protected_count(True, idr.from_rules())
    keep = dict(st.keep)
    plan_prot = rp.protected_players(st.all_names(), keep.get, det["protected_n"])
    assert plan_prot == av.protected_for(inp, "Nick", av.Settings())
    assert idr.protected_count(False, idr.from_rules()) == 4 == idr.protected_count(None, idr.from_rules())


def test_the_plan_never_undoes_a_known_il_placement_at_the_window():
    """A Monday move (or a ledger entry) puts Short O -- tagged O, no injury
    entry -- into the open IL slot at the open window. By the plan's own
    availability rule he is 'back' at once, but step 1 never activates a
    player placed at this window by a known move: he stays in IL this week
    (rule 5), and the add stays too."""
    players, rosters = _league()
    players["FA_new"] = _p("FA_new", 29.0)
    known = {5: {"Nick": {"il_place": ["Nick_3"], "drop": [], "add": ["FA_new"], "il_activate": []}}}
    v = _plan5(players, rosters, {}, open_day=MON5, known=known, statuses={"Nick_3": "O"})[5]["Nick"]
    assert v["il"] == ["Nick_3"] and "FA_new" in v["active"] and not v["activated"]
    assert v["known"] == ["IL+Nick_3", "+FA_new"]


def test_with_no_add_left_the_open_spots_wait_and_the_pool_is_not_read(monkeypatch):
    """An open window where Nick has used every add this week: his open
    active spot waits for the next window (counted in 'waiting'), nothing is
    added, and the week-5 free-agent pool -- read only to price a stand-in --
    is never read. With an add left, the same spot is filled at week 5."""
    players, rosters = _league()
    rosters["Nick"] = rosters["Nick"][1:]                      # one open spot
    full = {"Nick": RULES["add_budget"]}
    calls = []
    real = rp._pool_at_open
    monkeypatch.setattr(rp, "_pool_at_open", lambda *a, **k: calls.append(a[2]) or real(*a, **k))
    v = _plan5(players, rosters, {}, open_day=MON5, used=full)[5]["Nick"]
    assert v["added"] == [] and v["waiting"] == 1 and 5 not in calls
    calls.clear()
    w = _plan5(players, rosters, {}, open_day=MON5, used={})[5]["Nick"]
    assert len(w["added"]) == 1 and w["waiting"] == 0 and 5 in calls
