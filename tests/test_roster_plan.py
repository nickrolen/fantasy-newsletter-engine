"""The simulator plays the league's IL rules (HANDOFF_ROSTER_SLOTS_2026-10-28;
LEAGUE_RULES.md, "The 2026-27 IL and transaction rules", rules 1-9; Nick's
10-28 decisions: option B stand-ins, the pre-drop pool, fill every open spot).

One move window per FANTASY week (week 7 is 14 days and one window); IL slots
fixed for the week in both directions; every empty active spot filled with a
replacement-level STAND-IN, at most the add budget per week; an IL player is
activated at the first window he is healthy, and a midweek return sits out
the rest of that week.
"""
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from modules import data_loader as dl
from modules import roster_plan as rp
from modules import simulator_betting as sb
from modules.data_loader import MANAGERS, PlayerIndex
from modules.projections import PlayerProjection, TeamProjections, projection_error_sd

ROOT = Path(__file__).parent.parent

# The real 2026-27 calendar for weeks 2-10: week 7 runs 11-30 -> 12-13.
STARTS = {2: "2026-10-26", 3: "2026-11-02", 4: "2026-11-09", 5: "2026-11-16", 6: "2026-11-23",
          7: "2026-11-30", 8: "2026-12-14", 9: "2026-12-21", 10: "2026-12-28"}
WINDOWS = [(w, date.fromisoformat(d)) for w, d in STARTS.items() if w > 2]
RULES = {"active_spots": 15, "il_slots": 2, "add_budget": 3,
         "il_eligible_tags": {"O", "OFS"}, "replacement_rank": 4}
GP = 66.0


def _p(name, fppg, out=(), ret=None, team="BOS", pos=("PG",)):
    return PlayerProjection(player_name=name, nba_team=team, positions=list(pos), projected_fppg=fppg,
                            projected_gp=70.0, out_weeks=list(out), return_date=ret,
                            return_week=(max(out) + 1) if out else None)


def _league(extra=None, fa=12, size=15, top=40.0):
    """Four `size`-man rosters (M_0 .. at `top` FPPG, down by 1) and `fa`
    free agents FA_0 .. at 30 down by 1."""
    players, rosters = {}, {}
    for m in MANAGERS:
        rosters[m] = []
        for j in range(size):
            n = f"{m}_{j}"
            players[n] = _p(n, top - j)
            rosters[m].append(n)
    for j in range(fa):
        players[f"FA_{j}"] = _p(f"FA_{j}", 30.0 - j)
    players.update(extra or {})
    return players, rosters


def _build(players, rosters, il=None, statuses=None, order=None, rules=None):
    return rp.build(start_week=2, il_slots=il or {}, rosters=rosters, windows=WINDOWS,
                    players=PlayerIndex(players), statuses=statuses or {},
                    rules=rules or RULES, standin_gp=GP, order=order or list(MANAGERS))


def _standins(plan):
    return {n: p for w in plan.values() for v in w.values() for n, p in v["standins"].items()}


# 1 and 8 -- pure, and the order of the managers handed in cannot matter
def test_the_plan_is_a_pure_function_and_order_free():
    players, rosters = _league()
    players["Nick_3"] = _p("Nick_3", 37.0, out=[3, 4, 5], ret="2026-11-23")
    players["Hayden_0"] = _p("Hayden_0", 40.0, out=[3, 4], ret="2026-11-16")
    rosters["Garrett"] = rosters["Garrett"][:13]              # two open spots
    a = _build(players, rosters)
    b = _build(players, dict(reversed(list(rosters.items()))), order=list(reversed(MANAGERS)))
    assert a == b == _build(players, rosters)
    assert rp.format_plan(a) == rp.format_plan(b)


# 3 -- a midweek return from IL sits out the rest of the week
def test_a_midweek_return_from_il_sits_out_that_week_and_plays_from_the_next_window():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-18")     # a Wednesday, week 5
    plan = _build(players, rosters)
    assert "Nick_0" in plan[3]["Nick"]["il"]
    assert plan[3]["Nick"]["added"] == ["Replacement for Nick_0 (27.0)"]       # FA_3, the 4th
    assert "Nick_0" in plan[5]["Nick"]["il"], "back on 11-18, a Wednesday: still in the IL slot"
    assert "Nick_0" in plan[6]["Nick"]["active"] and plan[6]["Nick"]["dropped"] == ["Nick_14"]


def test_an_il_slot_scores_nothing_all_week_and_is_bit_identical_to_removal():
    from test_season_sim import _world
    data, teams = _world()
    wd = sb.schedule_week(data, 9)
    name = sorted(teams["Nick"].players, key=lambda n: -teams["Nick"].players[n].projected_fppg)[0]
    masked = sb.simulate_week_matrix(data, teams, wd, None, sb.KeyedDraws(4, 600),
                                     il_mask={"Nick": {name}})
    gone = dict(teams, Nick=TeamProjections("Nick", {n: p for n, p in teams["Nick"].players.items()
                                                     if n != name},
                                            weekly_std_dev=teams["Nick"].weekly_std_dev))
    removed = sb.simulate_week_matrix(data, gone, wd, None, sb.KeyedDraws(4, 600))
    for m in MANAGERS:
        assert np.array_equal(masked[m]["score"], removed[m]["score"]), m


# 4 -- week 7 is one fantasy week: one window, one budget
def test_week_7_has_one_window_and_a_return_on_12_07_waits_for_12_14():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4, 5, 6], ret="2026-12-07")
    plan = _build(players, rosters)
    assert [d for w, d in WINDOWS if w == 7] == [date(2026, 11, 30)]
    assert all(d != date(2026, 12, 7) for _w, d in WINDOWS)
    assert "Nick_0" in plan[7]["Nick"]["il"], "12-07 is not a window: he sits out all 14 days"
    assert "Nick_0" in plan[8]["Nick"]["active"]
    real = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    days = [d for _w, d in rp.windows_for(SimpleNamespace(schedule=real), 2)]
    assert date(2026, 11, 30) in days and date(2026, 12, 7) not in days


def test_three_placements_in_one_week_fill_two_slots_and_the_third_stays_active():
    players, rosters = _league()
    for j in range(3):
        players[f"Nick_{j}"] = _p(f"Nick_{j}", 40.0 - j, out=[3, 4], ret="2026-11-16")
    plan = _build(players, rosters)
    assert plan[3]["Nick"]["il"] == ["Nick_0", "Nick_1"]
    assert plan[3]["Nick"]["added"] == ["Replacement for Nick_0 (27.0)", "Replacement for Nick_1 (27.0)"]
    assert "Nick_2" in plan[3]["Nick"]["active"], "no slot left: he stays active and does not play"
    # two back, two lowest go: Nick_14 (26) then Nick_13 (27.0, ties a stand-in; by name)
    assert plan[5]["Nick"]["dropped"] == ["Nick_14", "Nick_13"]


# the add budget: 4 adds needed, 3 taken, the 4th at the next window
def test_a_roster_needing_four_adds_gets_three_and_the_fourth_next_window():
    players, rosters = _league()
    rosters["Nick"] = rosters["Nick"][:11]
    plan = _build(players, rosters)
    assert len(plan[3]["Nick"]["added"]) == 3 and plan[3]["Nick"]["waiting"] == 1
    assert len(plan[3]["Nick"]["active"]) == 14
    # Nick_11..14 are free agents now: the pool is 30, 29, 29, 28 -> level 28.0
    assert plan[4]["Nick"]["added"] == ["Replacement for open spot 4, Nick (28.0)"]
    assert len(plan[4]["Nick"]["active"]) == 15 and plan[4]["Nick"]["waiting"] == 0
    assert any("wait for the next window" in line for line in rp.format_plan(plan))


# 5 -- the current week's IL occupants: locked, no moves
def test_the_current_week_is_locked_as_the_file_says():
    players, rosters = _league()
    rosters["Garrett"].append("Flaggish")
    players["Flaggish"] = _p("Flaggish", 45.0)                  # healthy, sitting in an IL slot
    plan = _build(players, rosters, il={"Garrett": ["Flaggish"]})
    assert plan[2]["Garrett"]["il"] == ["Flaggish"] and not plan[2]["Garrett"]["added"]
    assert "Flaggish" in plan[3]["Garrett"]["active"], "healthy: activated at the next window"
    assert len(plan[3]["Garrett"]["active"]) == 15 and plan[3]["Garrett"]["dropped"] == ["Garrett_14"]


# 6 -- 15 active from week 3's window on (unless the budget binds), <= 2 IL, budget
def test_the_slot_and_budget_invariants_hold_every_week():
    players, rosters = _league()
    rosters["Benton"] = rosters["Benton"][:9]          # 6 open + 2 IL covers: three windows
    for m in MANAGERS:
        for j, ret in ((0, "2026-12-14"), (1, "2026-11-23"), (2, "2026-11-18")):
            out = [w for w in STARTS if w >= 3
                   and (date.fromisoformat(STARTS[w]) + timedelta(days=6)) < date.fromisoformat(ret)]
            players[f"{m}_{j}"] = _p(f"{m}_{j}", 40.0 - j, out=out, ret=ret)
    plan = _build(players, rosters)
    for w, managers in plan.items():
        for m, v in managers.items():
            assert len(v["active"]) <= 15 and len(v["il"]) <= 2 and len(v["added"]) <= 3, (w, m)
            assert not set(v["active"]) & set(v["il"])
            if w >= 3:
                assert len(v["active"]) == 15 or v["waiting"], (w, m)
    assert [plan[w]["Benton"]["waiting"] for w in (3, 4, 5)] == [5, 2, 0]
    assert len(plan[5]["Benton"]["active"]) == 15


# 7 -- replacement level, and what a stand-in is
def test_the_stand_in_is_the_rank_th_level_with_the_injured_players_positions_and_team():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-16", team="LAL", pos=("C",))
    players["FA_1"] = _p("FA_1", 29.0, out=[3])                 # an override covers week 3
    players["FA_5"] = _p("FA_5", 25.0, team="MIA", pos=("SF",))
    rosters["Hayden"] = rosters["Hayden"][:14]                  # one open spot
    players["Hayden_14"] = _p("Hayden_14", 0.0)                 # and not in the pool
    plan = _build(players, rosters, statuses={"FA_0": "OFS"})
    # pool, best first: FA_2 (28), FA_3, FA_4, FA_5 (25) -> the level is 25.0
    s = _standins(plan)
    cover = s["Replacement for Nick_0 (25.0)"]
    assert (cover.projected_fppg, cover.nba_team, cover.positions) == (25.0, "LAL", ["C"])
    spot = s["Replacement for open spot 1, Hayden (25.0)"]
    assert (spot.projected_fppg, spot.nba_team, spot.positions) == (25.0, "MIA", ["SF"])
    for p in s.values():
        assert p.standin and p.projected_gp == GP and p.actual_games == 0 and not p.out_weeks
        assert p.effective_fppg == p.projected_fppg
        assert p.std_dev == pytest.approx(p.projected_fppg * 0.35), "the rule every player has"


def test_two_stand_ins_in_one_window_share_the_level_and_never_a_name():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-16")
    players["Hayden_0"] = _p("Hayden_0", 40.0, out=[3, 4], ret="2026-11-16")
    plan = _build(players, rosters)
    a, b = plan[3]["Nick"]["added"], plan[3]["Hayden"]["added"]
    assert a == ["Replacement for Nick_0 (27.0)"] and b == ["Replacement for Hayden_0 (27.0)"]


def test_the_pool_is_read_before_the_windows_drops():
    """Hayden's drop at week 3 would top the pool; Nick's week-3 level does not
    see it (any order), and his week-4 level does."""
    players, rosters = _league(fa=4)
    for j in range(15):
        players[f"Hayden_{j}"] = _p(f"Hayden_{j}", 60.0 - j)
    rosters["Hayden"].append("Hurt")
    players["Hurt"] = _p("Hurt", 70.0, out=[2], ret="2026-11-02")
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3], ret="2026-11-09")
    players["Nick_1"] = _p("Nick_1", 39.0, out=[4], ret="2026-11-16")
    for order in (list(MANAGERS), list(reversed(MANAGERS))):
        plan = _build(players, rosters, il={"Hayden": ["Hurt"]}, order=order)
        assert plan[3]["Hayden"]["dropped"] == ["Hayden_14"]               # 46.0
        assert plan[3]["Nick"]["added"] == ["Replacement for Nick_0 (27.0)"], "FA_3, pre-drop"
        assert plan[4]["Nick"]["added"] == ["Replacement for Nick_1 (28.0)"], "Hayden_14 now in"


def test_the_pool_must_be_deep_enough_or_it_raises():
    players, rosters = _league(fa=2)
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3], ret="2026-11-09")
    with pytest.raises(ValueError, match="replacement_rank"):
        _build(players, rosters)


# a stand-in never resolves to the player he covers, anywhere a name is looked up
NAMES = ["Replacement for Anthony Edwards (35.2)", "Replacement for Tyrese Haliburton (35.2)",
         "Replacement for open spot 1, Hayden (35.2)", "Replacement for S. Gilgeous-Alexander (35.2)",
         "Replacement for Bobby Portis Jr. (35.2)"]


@pytest.mark.parametrize("name", NAMES)
def test_a_stand_in_name_matches_no_real_player(name):
    real = PlayerIndex({"Anthony Edwards": "O", "A. Edwards": "O", "Tyrese Haliburton": "Q",
                        "Hayden": 1, "Shai Gilgeous-Alexander": "HEALTHY", "Bobby Portis": "HEALTHY"})
    assert real.canonical(name) is None, "PlayerIndex resolves every tag, override and prior lookup"


def test_a_stand_in_takes_the_median_prior_and_tau_at_zero_games_and_is_never_a_fallback():
    from test_season_sim import _world
    from modules import absence
    data, teams = _world()
    prior = dl.DurabilityPrior({n: 50.0 + i for i, n in enumerate(p for t in teams.values()
                                                                    for p in t.players)},
                               "snapshot-test")
    data.durability_prior = prior
    gp = rp.standin_gp(data, teams)
    assert gp == prior.median_gp
    like = next(iter(teams["Nick"].players.values()))
    s = rp.standin(f"Replacement for {like.player_name} (35.2)", like, 35.2, gp)
    tp = dict(teams, Nick=TeamProjections("Nick", dict(teams["Nick"].players, **{s.player_name: s}),
                                          weekly_std_dev=teams["Nick"].weekly_std_dev))
    draws = sb.KeyedDraws(3, 200)
    base = sb.baseline_blocks(data, tp, draws, date(2027, 1, 4), ["Nick"],
                              injury_statuses={like.player_name: "O"})
    params = absence.baseline_params()
    assert base[s.player_name].miss_rate == absence.durability_miss_rate(prior.median_gp, params)
    assert s.player_name not in prior.fallbacks and not prior.fallbacks
    m = sb._projection_error_multipliers(draws, tp["Nick"], [s.player_name])[s.player_name]
    tau = projection_error_sd(0)
    z = draws.normals("projection_error", s.player_name)
    assert np.array_equal(m, np.exp(tau * z - 0.5 * tau * tau))


# 9 -- the IL file: missing, stale, or naming a stranger raises
def _data_today(tmp_path):
    real = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    return SimpleNamespace(schedule=real, base_path=tmp_path)


def test_a_missing_il_file_raises(tmp_path):
    with pytest.raises(rp.ILSlotsError, match="missing"):
        rp.load_il_slots(tmp_path, _data_today(tmp_path), today=date(2026, 10, 28))


def test_a_stale_il_file_raises(tmp_path):
    rp.write_il_slots(tmp_path, {"Nick": []}, 2)
    assert rp.load_il_slots(tmp_path, _data_today(tmp_path), today=date(2026, 10, 28))["fantasy_week"] == 2
    with pytest.raises(rp.ILSlotsError, match="re-run the roster sync"):
        rp.load_il_slots(tmp_path, _data_today(tmp_path), today=date(2026, 11, 2))


def test_an_il_name_off_the_roster_raises():
    with pytest.raises(rp.ILSlotsError, match="not on his ROSTERS.json"):
        rp.check_against_rosters({"slots": {"Nick": ["Somebody Else"]}}, {"Nick": ["Luka Doncic"]})


# 10 -- required config
@pytest.mark.parametrize("key", ["il_eligible_tags", "replacement_rank"])
def test_the_roster_moves_keys_are_required(monkeypatch, key):
    cfg = dict(dl._LEAGUE_CONFIG)
    cfg["roster_moves"] = {k: v for k, v in cfg["roster_moves"].items() if k != key}
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", cfg)
    with pytest.raises(dl.UnspecifiedRule, match=key):
        rp.rules()


def test_the_configured_rules():
    r = rp.rules()
    assert r == {"active_spots": 15, "il_slots": 2, "add_budget": 3,
                 "il_eligible_tags": {"O", "OFS"}, "replacement_rank": 4}


# 12 -- drops, pickups and lineups never see m
def test_moves_never_see_the_persistent_error(monkeypatch):
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3], ret="2026-11-09")
    a = _build(players, rosters)
    monkeypatch.setattr(sb, "_projection_error_multipliers",
                        lambda d, tp, keys: {k: np.full(d.n, 9.0) for k in keys})
    assert _build(players, rosters) == a                    # the plan never reads a draw


# 11 -- one plan for the pass and the line; order cannot move the odds
def _moving_world(monkeypatch):
    from test_season_sim import _world
    data, teams = _world(recorded_through=8)
    data.il_slots = rp.no_il(9)
    for m in ("Hayden", "Nick"):
        name = sorted(teams[m].players, key=lambda n: -teams[m].players[n].projected_fppg)[0]
        p = teams[m].players[name]
        p.out_weeks, p.return_date, p.return_week = [10, 11], "2027-01-04", 12
    monkeypatch.setattr(dl.FantasyData, "get_player_injury_weeks", lambda self, n: [])
    data.playerlist = pd.DataFrame([{"player_name": f"Free{j}", "player_nba_team": "BOS",
                                     "player_position(s)": "PG", "projectedFPPG": 30.0 - j,
                                     "player_proj_GP": 70.0, "player_total_proj_FP": 0.0}
                                    for j in range(8)])
    return data, teams


def test_the_season_pass_and_the_betting_line_read_one_plan(monkeypatch):
    """With moves in play the pass's week equals the line's week, column for column."""
    import modules.season_sim as ss
    data, teams = _moving_world(monkeypatch)
    seen = []
    real = sb.week_score_matrices
    monkeypatch.setattr(ss, "week_score_matrices",
                        lambda *a, **k: seen.append(real(*a, **k)) or seen[-1])
    ss.run_season(data, num_simulations=300, seed=7, team_projections=teams, through="regular")
    run = rp.for_run(data, teams, None)
    assert run.plan[10]["Hayden"]["added"] and run.plan[10]["Nick"]["added"], "the plan moved people"
    tp, mask = rp.week_rosters(run, teams, 10)
    line = sb.simulate_week_matrix(data, tp, sb.schedule_week(data, 10), None,
                                   sb.KeyedDraws(7, 120), il_mask=mask)
    for m in MANAGERS:
        assert np.array_equal(seen[0][10][m][:120], line[m]["score"]), m


def test_reversing_the_manager_order_leaves_the_plan_and_the_odds_bit_identical(monkeypatch):
    import modules.season_sim as ss
    out = []
    for order in (list(MANAGERS), list(reversed(MANAGERS))):
        monkeypatch.setattr(rp, "pick_order", lambda o=order: list(o))
        data, teams = _moving_world(monkeypatch)
        sp = ss.run_season(data, num_simulations=400, seed=11, team_projections=teams,
                           through="regular")
        out.append((rp.for_run(data, teams, None).plan, sp.reg_points, sp.title_result().title_odds))
    (pa, ra, oa), (pb, rb_, ob) = out
    assert pa == pb and pa[10]["Nick"]["added"] and pa[10]["Hayden"]["added"]
    assert np.array_equal(ra, rb_) and oa == ob


# 2 and 8 -- on the real inputs, when the IL file is this week's
def _real():
    data = dl.load_all_data(ROOT)
    from modules.projections import load_all_team_projections
    teams = load_all_team_projections(data)
    try:
        rp.load_il_slots(ROOT, data)
    except rp.ILSlotsError as e:
        pytest.skip(f"real-data check needs this week's IL file: {e}")
    return data, teams


def test_edwards_end_to_end_on_the_real_inputs(monkeypatch):
    data, teams = _real()
    ae = teams["Nick"].players.get("Anthony Edwards")
    if ae is None or str(ae.return_date)[:10] != "2027-01-25":
        pytest.skip("the 10-28 inputs have changed: Edwards' override or roster moved")
    run = rp.for_run(data, teams, {})
    plan = run.plan
    assert "Anthony Edwards" not in plan[2]["Nick"]["il"], "week 2 is locked"
    assert "Anthony Edwards" in plan[3]["Nick"]["il"]
    assert [a.startswith("Replacement for Anthony Edwards (") for a in plan[3]["Nick"]["added"]] == [True]
    cover = run.standins[plan[3]["Nick"]["added"][0]]
    assert (cover.nba_team, cover.positions) == (ae.nba_team, list(ae.positions))
    for w in range(4, 14):
        assert "Anthony Edwards" in plan[w]["Nick"]["il"], w
    assert "Anthony Edwards" in plan[14]["Nick"]["active"]
    low = min(plan[13]["Nick"]["active"], key=lambda n: (run.projection(n).effective_fppg, n))
    assert plan[14]["Nick"]["dropped"] == [low]
    for w in range(3, max(plan) + 1):
        for m, v in plan[w].items():
            assert len(v["active"]) == 15 or v["waiting"], (w, m)
    # every stand-in matches nobody real, and the order cannot move the plan
    for name in run.standins:
        assert run.players.canonical(name) is None
        assert data.durability_prior.gp.canonical(name) is None
    monkeypatch.setattr(rp, "pick_order", lambda: list(reversed(MANAGERS)))
    data.__dict__.pop("_roster_plans", None)
    assert rp.for_run(data, teams, {}).plan == plan
