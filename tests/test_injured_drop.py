"""Task 18b: the simulator drops an injured player when a manager would.

INJURED_DROP_DESIGN.md s.3-6; HANDOFF_18B_INJURED_DROP / HANDOFF_18B_REFIT_AND_WIRE
(2026-11-04). The decision is modules/injured_drop (pure); its inputs come
from modules/drop_inputs; modules/roster_plan calls it at every future window.

  A. the decision function: pure, deterministic, top-4 never dropped, the
     two "little left" rules, the config required and commented;
  B. Nick's scenarios at the configured M, F and K, on every seed: the
     pinned answers, the direction checks, and the values away from the
     region's edges;
  C. the plan: untouched when nobody needs a decision; drop, hold, IL by
     value, no add left, protected keepers, order-free;
  D. the stakes file: the bootstrap (missing / other season / schema 1) and
     everything else raising; the notes in the run record;
  E. a fixture team with a third long injury: dropping moves its title
     odds up.
"""
import importlib
import inspect
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from modules import data_loader as dl
from modules import drop_inputs as di
from modules import injured_drop as idr
from modules import roster_plan as rp
from modules.data_loader import MANAGERS, PlayerIndex

import injured_drop_scenarios as sc
from test_roster_plan import GP, RULES, WINDOWS, _build, _league, _p, NO_STAKES

ROOT = Path(__file__).resolve().parent.parent
CFG = idr.from_rules()
LA = ZoneInfo("America/Los_Angeles")


# =============================================================================
# A. the decision function
# =============================================================================

def _stakes(window=4, lev=0.3, weeks=range(4, 22), rs_title=0.3, champion=0.25, last_reg=15,
            lev_after=None, back=None):
    """A team's stakes: `lev` every week (lev_after from week `back` on)."""
    out = {}
    for w in weeks:
        v = lev if (back is None or w < back or lev_after is None) else lev_after
        out[w] = idr.WeekStake(w, v if w <= last_reg else None, None if w <= last_reg else v, 0.0, 250.0)
    return idr.TeamStakes(window, window <= last_reg, rs_title, champion, out, max(weeks))


def _cand(fppg=40.0, window=4, back=8, standin=35.2, last=21):
    return idr.Candidate("P", back, sc.points(fppg, window, back) if last == 21 else {},
                         sc.points(standin, window, window))


def test_the_decision_reads_no_file_and_draws_nothing():
    src = inspect.getsource(idr)
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]                           # past the module docstring
    for banned in ("open(", "read_text", "Path(", "json.", "import os", "numpy", "random",
                   "pandas", "load_all_data"):
        assert banned not in body, banned
    # the only import of the package is data_loader, inside from_rules (the config)
    assert [ln.strip() for ln in body.splitlines() if "import" in ln and "from ." in ln] == \
        ["from .data_loader import league_rule"]


def test_the_decision_is_deterministic():
    st, c, keep = _stakes(), _cand(), sc.keep_for(None)
    assert idr.decide("A", c, st, keep, CFG) == idr.decide("A", c, st, keep, CFG)


@pytest.mark.parametrize("rank", [1, 2, 3, 4])
def test_a_top_4_keeper_is_never_dropped_whatever_the_numbers(rank):
    st = _stakes(lev=1.0, lev_after=0.0, back=5)
    c = idr.Candidate("P", None, sc.points(60, 4, None), sc.points(35.2, 4, 4))   # OFS, huge cost
    d = idr.decide("A", c, st, sc.keep_for(rank), CFG)
    assert d.action == "hold" and "top-4" in d.reason and d.cost_hold > 0.1
    assert idr.decide("A", c, st, sc.keep_for(7), CFG).action == "drop"           # unprotected: drops


def test_little_left_is_the_rs_title_before_the_playoffs_and_the_playoff_title_from_them():
    assert idr.little_left(_stakes(window=12, rs_title=0.04, champion=0.9), CFG)
    assert not idr.little_left(_stakes(window=12, rs_title=0.06, champion=0.01), CFG)
    late = _stakes(window=17, weeks=range(17, 22), rs_title=0.0, champion=0.3)
    assert not idr.little_left(late, CFG)                      # not both: the RS title is gone
    assert idr.little_left(_stakes(window=17, weeks=range(17, 22), rs_title=1.0, champion=0.04), CFG)


def test_a_little_left_team_holds_every_keeper_candidate_and_only_those():
    st = _stakes(window=12, weeks=range(12, 22), rs_title=0.0, lev=0.5, lev_after=0.0, back=14)
    c = idr.Candidate("P", 14, sc.points(40, 12, 14), sc.points(35.2, 12, 12))
    assert idr.decide("A", c, st, sc.keep_for(6), CFG).reason.startswith("little left")
    assert idr.decide("A", c, st, sc.keep_for(7), CFG).action == "drop"


def test_a_null_leverage_is_worth_nothing_and_a_zero_sd_raises():
    assert idr.point_value(idr.WeekStake(3, None, None, 0.0, 250.0), CFG) == 0.0
    with pytest.raises(idr.StakesError):
        idr.point_value(idr.WeekStake(3, 0.2, None, 0.0, 0.0), CFG)


def test_a_week_with_no_stake_raises():
    st = _stakes(weeks=range(4, 21))                            # week 21 missing
    c = _cand()
    st = idr.TeamStakes(4, True, 0.3, 0.25, st.weeks, 21)
    with pytest.raises(idr.StakesError, match="week 21"):
        idr.decide("A", c, st, sc.keep_for(None), CFG)


@pytest.mark.parametrize("key", idr.KEYS)
def test_every_config_key_is_required(monkeypatch, key):
    cfg = dict(dl._LEAGUE_CONFIG)
    cfg["injured_drop"] = {k: v for k, v in cfg["injured_drop"].items() if k != key}
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", cfg)
    with pytest.raises(dl.UnspecifiedRule, match=key):
        idr.from_rules()


def test_every_config_value_has_a_comment_naming_its_scenarios():
    block = dl._LEAGUE_CONFIG["injured_drop"]
    for key in idr.KEYS:
        note = block.get(f"_{key}")
        assert note and ("cenario" in note), key


# =============================================================================
# B. Nick's scenarios at the configured values, every seed
# =============================================================================

@pytest.fixture(scope="module")
def numbers_by_seed():
    return {sd: {n.sid: n for n in sc.numbers(CFG, sd)} for sd in sc.SEEDS}


def _passes(nums: dict, M, F, K) -> list:
    """What fails at (M, F, K): pinned answers and directions."""
    bad = []
    for n in nums.values():
        if n.answer and sc.gives(n, M, F, K) != n.answer:
            bad.append(f"{n.sid}: {sc.gives(n, M, F, K)}, not {n.answer}")
    for weak, strong in sc.DIRECTIONS:
        if sc.gives(nums[weak], M, F, K) == "drop" and sc.gives(nums[strong], M, F, K) == "hold":
            bad.append(f"{weak} drops but {strong} holds")
    return bad


def test_every_pinned_answer_and_direction_holds_on_every_seed(numbers_by_seed):
    assert len(sc.SEEDS) >= 5
    for sd, nums in numbers_by_seed.items():
        assert _passes(nums, CFG.margin, CFG.floor, CFG.keeper_weight) == [], sd


# the common region of the six seeds (tests/injured_drop_scenarios.fit, 11-04):
# M 0-1.10, K 0-0.36, F 0-0.122. A box of 15% of each extent around the
# configured point must lie inside it on every seed.
EXTENT = {"M": 1.10, "K": 0.36, "F": 0.122}


def test_the_configured_values_are_away_from_the_regions_edges(numbers_by_seed):
    dM, dK, dF = (0.15 * EXTENT[k] for k in "MKF")
    M, F, K = CFG.margin, CFG.floor, CFG.keeper_weight
    assert min(M - dM, K - dK, F - dF) >= 0
    for sd, nums in numbers_by_seed.items():
        for m in (M - dM, M, M + dM):
            for k in (K - dK, K, K + dK):
                for f in (F - dF, F, F + dF):
                    assert _passes(nums, m, f, k) == [], (sd, m, k, f)


def test_the_fits_shortcut_is_the_decision_itself(numbers_by_seed):
    """sc.gives (the fit's sweep) and idr.decide agree on every scenario."""
    for s in sc.scenarios():
        d = idr.decide("A", s.candidate(), s.stakes(sc.SEED), s.keep(), CFG)
        n = numbers_by_seed[sc.SEED][s.sid]
        assert d.action == sc.gives(n, CFG.margin, CFG.floor, CFG.keeper_weight), s.sid


def test_scenario_8_is_protected_and_6_holds_for_little_left(numbers_by_seed):
    for nums in numbers_by_seed.values():
        assert nums["8"].protected
        assert nums["6r5"].little_left and nums["6r6"].little_left


def test_a_higher_keep_chance_never_makes_a_drop_more_likely():
    s = next(x for x in sc.scenarios() if x.sid == "1a5")
    st = s.stakes(sc.SEED)
    held = False
    for chance in np.linspace(0.0, 0.5, 26):
        keep = sc.keep_for(5, chance=float(chance), above=[0.99, 0.95, 0.9, 0.8])
        a = idr.decide("A", s.candidate(), st, keep, CFG).action
        assert not (held and a == "drop"), chance
        held = held or a == "hold"


# =============================================================================
# C. the plan
# =============================================================================

def _ctx(stakes_for, keep=None, note=None, games=3.5, share=1.0):
    """A DropContext from hand-made stakes: stakes_for(manager, window)."""
    return rp.DropContext(config=CFG, note=lambda: note, stakes=stakes_for,
                          keep=lambda m: keep or {}, games=lambda team, w, d=None: games,
                          availability=lambda p: share)


def _plan_stakes(lev_out=0.5, lev_after=0.0, back=7, champion=0.25, rs_title=0.3, last=10):
    """Hand-made stakes through week `last` (test_roster_plan's windows end at 10)."""
    def f(manager, window):
        weeks = {w: idr.WeekStake(w, lev_out if w < back else lev_after, None, 0.0, 250.0)
                 for w in range(window, last + 1)}
        return idr.TeamStakes(window, True, rs_title, champion, weeks, last)
    return f


def _keep_low(players):
    return {n: 0.01 for n in players}


def _raising():
    def boom(*a, **k):
        raise AssertionError("the plan asked for an input no decision needed")
    return rp.DropContext(config=CFG, note=boom, stakes=boom, keep=boom, games=boom, availability=boom)


def test_no_team_beyond_its_il_slots_changes_and_no_input_is_read():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-16")
    players["Nick_1"] = _p("Nick_1", 39.0, out=[3, 4, 5], ret="2026-11-23")
    players["Hayden_0"] = _p("Hayden_0", 40.0, out=[3], ret="2026-11-09")
    a = _build(players, rosters, drops=_raising())
    assert a == _build(players, rosters, drops=NO_STAKES) == _build(players, rosters)
    assert all(not v["decisions"] for w in a.values() for v in w.values())


def _three_out(ret="2026-11-30", weeks=(3, 4, 5, 6)):
    players, rosters = _league()
    for j in range(3):
        players[f"Nick_{j}"] = _p(f"Nick_{j}", 40.0 - j, out=list(weeks), ret=ret)
    return players, rosters


def test_a_third_long_injury_is_dropped_when_holding_costs_more():
    players, rosters = _three_out()
    keep = _keep_low(rosters["Nick"])
    plan = _build(players, rosters, drops=_ctx(_plan_stakes(), keep))
    v = plan[3]["Nick"]
    assert v["il"] == ["Nick_0", "Nick_1"] and "Nick_2" not in v["active"] and v["dropped"] == ["Nick_2"]
    assert v["added"] == ["Replacement for Nick_0 (27.0)", "Replacement for Nick_1 (27.0)",
                          "Replacement for dropped Nick_2 (27.0)"]
    (d,) = v["decisions"]
    assert (d["player"], d["action"], d["carried_out"]) == ("Nick_2", "drop", True)
    assert d["cost_hold"] > d["cost_drop"]
    for w in range(4, 8):
        assert "Nick_2" not in plan[w]["Nick"]["active"] + plan[w]["Nick"]["il"], "gone for good"
    assert any("Nick_2: drop" in ln for ln in rp.format_plan(plan))


def test_he_is_held_when_the_stakes_make_holding_cheap():
    players, rosters = _three_out()
    keep = _keep_low(rosters["Nick"])
    plan = _build(players, rosters, drops=_ctx(_plan_stakes(lev_out=0.0, lev_after=0.5), keep))
    v = plan[3]["Nick"]
    assert "Nick_2" in v["active"] and v["dropped"] == [] and len(v["added"]) == 2
    assert v["decisions"][0]["action"] == "hold"
    assert plan[4]["Nick"]["decisions"], "re-decided at the next window"


def test_a_top_4_keeper_is_held_by_the_plan_too():
    players, rosters = _three_out()
    keep = _keep_low(rosters["Nick"])
    keep.update({"Nick_2": 0.9, "Nick_3": 0.8, "Nick_4": 0.7, "Nick_5": 0.6})   # Nick_2 is the no. 1
    plan = _build(players, rosters, drops=_ctx(_plan_stakes(lev_after=0.0), keep))
    # his keeper term makes him the most valuable: he takes an IL slot, Nick_1 is the excess
    v = plan[3]["Nick"]
    assert "Nick_2" in v["il"]
    assert all(d["player"] != "Nick_2" or d["action"] == "hold" for w in plan.values()
               for x in w.values() for d in x["decisions"] if "player" in d)


def test_il_slots_go_to_value_and_an_il_occupant_can_be_the_one_dropped():
    """Nick's Paolo case (ADVICE_V2 s.2.2): an IL occupant worth little after a
    long absence gives his slot to a newly injured, more valuable player and
    is dropped."""
    players, rosters = _league()
    rosters["Nick"].append("Paolo")
    rosters["Nick"].remove("Nick_14")
    rosters["Nick"].append("Luka")
    players["Paolo"] = _p("Paolo", 36.0, out=list(range(2, 12)), ret="2027-01-11")
    players["Luka"] = _p("Luka", 60.0, out=[3], ret="2026-11-09")
    players["Edwards"] = _p("Edwards", 45.0, out=list(range(2, 12)), ret="2027-01-11")
    rosters["Nick"].append("Edwards")
    keep = _keep_low(rosters["Nick"])
    keep.update({"Luka": 0.99, "Edwards": 0.6})
    plan = _build(players, rosters, il={"Nick": ["Paolo", "Edwards"]},
                  drops=_ctx(_plan_stakes(lev_out=0.5, lev_after=0.3, back=4), keep))
    v = plan[3]["Nick"]
    assert sorted(v["il"]) == ["Edwards", "Luka"], "Luka's slot comes from Paolo"
    assert v["dropped"] == ["Paolo"] and v["added"] == ["Replacement for dropped Paolo (27.0)"]


def test_with_no_add_left_a_drop_is_held_and_says_so():
    players, rosters = _three_out()
    rosters["Nick"] = [n for n in rosters["Nick"] if n not in ("Nick_14",)]    # one open spot
    keep = _keep_low(rosters["Nick"])
    plan = _build(players, rosters, drops=_ctx(_plan_stakes(), keep))
    v = plan[3]["Nick"]
    # 2 covers + 1 open spot use the 3 adds: the drop waits
    assert len(v["added"]) == 3 and "Nick_2" in v["active"]
    (d,) = v["decisions"]
    assert d["action"] == "drop" and not d["carried_out"] and "no add left" in d["reason"]


def test_the_same_inputs_give_the_same_plan_in_any_manager_order():
    players, rosters = _three_out()
    for j in range(3):
        players[f"Hayden_{j}"] = _p(f"Hayden_{j}", 40.0 - j, out=[3, 4, 5, 6], ret="2026-11-30")
    keep = {**_keep_low(rosters["Nick"]), **_keep_low(rosters["Hayden"])}
    ctx = _ctx(_plan_stakes(), keep)
    a = _build(players, rosters, drops=ctx)
    b = _build(players, dict(reversed(list(rosters.items()))), order=list(reversed(MANAGERS)), drops=ctx)
    assert a == b == _build(players, rosters, drops=ctx)
    assert a[3]["Nick"]["dropped"] == ["Nick_2"] and a[3]["Hayden"]["dropped"] == ["Hayden_2"]


def test_a_dropped_players_stand_in_fills_a_roster_spot_in_the_money_section():
    from modules.season_sim import _standins_played
    players, rosters = _three_out()
    plan = _build(players, rosters, drops=_ctx(_plan_stakes(), _keep_low(rosters["Nick"])))
    made = {n: p for w in plan.values() for v in w.values() for n, p in v["standins"].items()}
    run = rp.Run(start_week=2, plan=plan, players=None, standins=made)
    st = {x["name"]: x for x in _standins_played(run, list(MANAGERS))["Nick"]}
    assert st["Replacement for dropped Nick_2 (27.0)"]["covers"] is None
    assert st["Replacement for Nick_0 (27.0)"]["covers"] == "Nick_0"


# =============================================================================
# D. the stakes file and the bootstrap
# =============================================================================

def _write(tmp_path, blob):
    p = di.stakes_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(blob if isinstance(blob, str) else json.dumps(blob), encoding="utf-8")


def _blob(week=9, season=None, schema=2, first=10, lev=0.5, lev_after=0.0, back=16, managers=MANAGERS):
    rows = lambda race: {str(w): {"rs_leverage" if race == "regular_season" else "playoff_leverage":
                                  (lev if w < back else lev_after), "margin_mean": 0.0,
                                  "margin_sd": 250.0, "n_win": 1, "n_loss": 1, "n_tie": 0}
                         for w in (range(first, 16) if race == "regular_season" else range(16, 22))}
    return {"schema": schema, "season": season or dl.CURRENT_SEASON, "week": week,
            "as_of": "2027-01-04T00:01:00-08:00", "run_id": "t", "kind": "nightly",
            "teams": {m: {"rs_title": 0.3, "champion": 0.25, "regular_season": rows("regular_season"),
                          "playoffs": rows("playoffs")} for m in managers}}


def test_a_missing_file_is_the_bootstrap(tmp_path):
    blob, note = di.read_stakes(tmp_path)
    assert blob is None and note.startswith(di.BOOTSTRAP_NOTE) and "missing" in note


def test_a_schema_1_file_is_the_bootstrap(tmp_path):
    _write(tmp_path, {**_blob(), "schema": 1})
    assert di.read_stakes(tmp_path)[1].startswith(di.BOOTSTRAP_NOTE)


def test_another_seasons_file_is_the_bootstrap(tmp_path):
    _write(tmp_path, _blob(season="2025-26"))
    assert "2025-26" in di.read_stakes(tmp_path)[1]


@pytest.mark.parametrize("bad", ["{not json", json.dumps([1, 2]), json.dumps({**_blob(), "schema": 3}),
                                 json.dumps({k: v for k, v in _blob().items() if k != "teams"})])
def test_a_file_that_exists_and_is_wrong_raises(tmp_path, bad):
    _write(tmp_path, bad)
    with pytest.raises(di.StakesFileError):
        di.read_stakes(tmp_path)


def test_rows_match_future_windows_by_week_and_a_missing_one_raises():
    blob = _blob(first=10)
    st = di.team_stakes(blob, "Nick", 11, last_regular=15, bracket=list(range(16, 22)))
    assert sorted(st.weeks) == list(range(11, 22)) and st.weeks[11].rs_leverage == 0.5
    assert st.weeks[16].playoff_leverage == 0.0 and st.weeks[16].rs_leverage is None
    assert st.regular_season and st.last_week == 21
    with pytest.raises(idr.StakesError, match="week 9"):
        di.team_stakes(blob, "Nick", 9, last_regular=15, bracket=list(range(16, 22)))
    with pytest.raises(di.StakesFileError, match="after the window"):
        di.team_stakes(_blob(week=12), "Nick", 11, last_regular=15, bracket=list(range(16, 22)))


def _moving_three(monkeypatch, tmp_path, ret="2027-02-15"):
    """test_roster_plan's moving world with Hayden's top three out weeks 10-15
    (back for the playoffs), nobody in an IL slot: a decision at week 10."""
    from test_roster_plan import _moving_world
    data, teams, tags = _moving_world(monkeypatch)
    best = sorted(teams["Hayden"].players, key=lambda n: -teams["Hayden"].players[n].projected_fppg)[:3]
    for n in best:
        p = teams["Hayden"].players[n]
        p.out_weeks, p.return_date, p.return_week = list(range(10, 16)), ret, 16
    for m in ("Nick",):
        name = sorted(teams[m].players, key=lambda n: -teams[m].players[n].projected_fppg)[0]
        p = teams[m].players[name]
        p.out_weeks, p.return_date, p.return_week = [], None, None
    data.base_path = tmp_path
    return data, teams, tags, best


def _keep_all(teams, low=()):
    """Everyone 0.5, the players in `low` far below: they rank last on their team."""
    return {m: {n: (0.001 if n in low else 0.5) for n in tp.players} for m, tp in teams.items()}


def test_for_run_with_no_stakes_plans_without_drops_and_says_so(monkeypatch, tmp_path):
    data, teams, tags, best = _moving_three(monkeypatch, tmp_path)
    data.drop_context = di.context(data, tmp_path, keep_week=8, keep=_keep_all(teams, best))
    rp.take_notes()
    run = rp.for_run(data, teams, tags)
    assert run.notes and run.notes[0].startswith(di.BOOTSTRAP_NOTE)
    assert rp.take_notes() == run.notes and rp.take_notes() == []
    v = run.plan[10]["Hayden"]
    assert best[2] in v["active"] and not v["dropped"]           # today's behaviour: held


def test_for_run_with_a_malformed_file_raises(monkeypatch, tmp_path):
    data, teams, tags, best = _moving_three(monkeypatch, tmp_path)
    _write(tmp_path, "{oops")
    data.drop_context = di.context(data, tmp_path, keep_week=8, keep=_keep_all(teams, best))
    with pytest.raises(di.StakesFileError):
        rp.for_run(data, teams, tags)


def test_the_nightly_run_records_the_notes_on_the_step(tmp_path):
    nightly = importlib.import_module("modules.nightly")

    def line():
        rp._NOTES.append(di.BOOTSTRAP_NOTE + " (stakes.json is missing)")
        return "priced"
    steps = {n: (lambda n=n: f"{n} done") for n in nightly.STEPS["nightly"]}
    steps["line"] = line
    shown = []
    run = nightly.Run(tmp_path, "nightly", now=datetime(2026, 11, 4, 0, 1, tzinfo=LA), echo=shown.append)
    row = run.execute(steps)
    detail = {s["step"]: s["detail"] for s in row["steps"]}
    assert detail["line"] == "priced; " + di.BOOTSTRAP_NOTE + " (stakes.json is missing)"
    assert detail["title_odds"] == "title_odds done"
    assert any(di.BOOTSTRAP_NOTE in ln for ln in shown)


def test_only_the_loader_and_the_writer_open_the_stakes():
    srcs = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "modules").glob("*.py")}
    assert {n for n, s in srcs.items() if "STAKES_FILE" in s} == {"title_odds_run.py", "drop_inputs.py"}


# =============================================================================
# E. a third long injury, through the season pass
# =============================================================================

def test_a_third_long_injury_dropped_moves_that_teams_title_odds_up(monkeypatch, tmp_path):
    import modules.season_sim as ss
    out = {}
    for case in ("bootstrap", "drop"):
        data, teams, tags, best = _moving_three(monkeypatch, tmp_path / case)
        if case == "drop":
            _write(tmp_path / case, _blob(week=9, first=10, lev=0.5, lev_after=0.0, back=16))
        data.drop_context = di.context(data, tmp_path / case, keep_week=8, keep=_keep_all(teams, best))
        sp = ss.run_season(data, num_simulations=1500, seed=5, team_projections=teams,
                           through="regular", injury_statuses=tags)
        run = rp.for_run(data, teams, tags)
        wins = float(sp.reg_wins[:, sp.managers.index("Hayden")].mean())
        out[case] = (sp.title_result().title_odds, run.plan[10]["Hayden"], best, wins)
    (odds_b, plan_b, best, wins_b), (odds_d, plan_d, _, wins_d) = out["bootstrap"], out["drop"]
    assert best[2] in plan_b["active"] and plan_d["dropped"] == [best[2]]
    assert plan_d["decisions"][0]["action"] == "drop"
    # direction only (the same seed, so the same draws): a live stand-in in the
    # dead spot for weeks 10-15 wins him more games and lifts his title odds
    assert wins_d > wins_b + 0.05
    assert odds_d["Hayden"] > odds_b["Hayden"]
    rp.take_notes()


def test_todays_real_plan_needs_no_decision_and_reads_no_input():
    """No team has an injured player beyond its IL slots at any window on
    today's inputs (11-04), so the plan never touches the stakes or the keep
    chances -- and today's odds and lines are unchanged (by hash, in
    INJURED_DROP_RESULT_2). Disk-state dependent: skips when the IL file is
    not this week's."""
    from modules.projections import load_all_team_projections
    fis = importlib.import_module("modules.fetch_injury_statuses")
    data = dl.load_all_data(ROOT)
    try:
        rp.load_il_slots(ROOT, data)
    except rp.ILSlotsError as e:
        pytest.skip(f"needs this week's IL file: {e}")
    teams = load_all_team_projections(data)
    data.drop_context = _raising()
    run = rp.for_run(data, teams, fis.Tags.none())
    assert all(not v["decisions"] for w in run.plan.values() for v in w.values())
