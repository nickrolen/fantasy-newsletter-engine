"""The hazard's gate: the per-game miss rate (HANDOFF_HAZARD_CHECK_2026-10-27).

modules/miss_rate.simulated must be the engine's own availability, not a
second model of it; realized must count misses the way the log does (a team
game with exactly 0.0 points); and an INJURY_OVERRIDES absence must count as
a miss, as a long injury does in the history it is compared with.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from modules import miss_rate as mr
from modules import simulator_betting as sb
from modules.data_loader import FantasyData, MANAGERS
from modules.projections import PlayerProjection, TeamProjections

SEED = 20262027


def _world(n_weeks=4, gp=70.0):
    start = date(2026, 10, 19)
    weeks = [{"week": w, "start_date": (start + timedelta(days=7 * (w - 1))).isoformat(),
              "end_date": (start + timedelta(days=7 * w - 1)).isoformat()} for w in range(1, n_weeks + 1)]
    games = [{"date": (start + timedelta(days=k)).isoformat(), "home": "BOS", "away": "MIA"}
             for k in range(7 * n_weeks)]
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games}, current_week=0)
    teams = {m: TeamProjections(m, {f"P{j}{m}": PlayerProjection(
        player_name=f"P{j}{m}", nba_team="BOS", positions=["PG"], projected_fppg=30.0 - j,
        projected_gp=gp) for j in range(3)}, weekly_std_dev=100.0) for m in MANAGERS}
    return data, teams, weeks


@pytest.mark.slow
def test_simulated_is_the_engines_own_availability():
    data, teams, weeks = _world()
    anchor = date.fromisoformat(weeks[0]["start_date"])
    draws = sb.KeyedDraws(SEED, 2000)
    got = mr.simulated(data, teams, range(1, 5), {"P0Nick": "Q"}, draws, anchor, MANAGERS)
    # the same quantity, by hand, through availability_on
    missed = games = 0
    for w in weeks:
        for d in sb.get_dates_in_week(w):
            for m in MANAGERS:
                for name in teams[m].players:
                    a = sb.availability_on(data, teams, w, {"P0Nick": "Q"}, draws, m, name, d, anchor)
                    missed += 1 - a.mean()
                    games += 1
    assert got["games"] == games
    assert got["rate"] == pytest.approx(missed / games, abs=1e-12)
    # and it is the prior's rate, in expectation: (82 - 70) / 82
    assert got["rate"] == pytest.approx(12 / 82, abs=0.02)


def test_an_override_absence_is_a_miss_and_the_hazard_off_engine_is_near_zero(monkeypatch):
    data, teams, weeks = _world(gp=82.0)                 # nobody misses by durability
    anchor = date.fromisoformat(weeks[0]["start_date"])
    teams["Nick"].players["P0Nick"].out_weeks = [1, 2]   # out two of four weeks
    got = mr.simulated(data, teams, range(1, 5), {}, sb.KeyedDraws(SEED, 500), anchor, MANAGERS)
    assert got["by_manager"]["Nick"] == pytest.approx((14 / 28) / 3)   # one player of three, half the games
    assert got["by_manager"]["Hayden"] == 0.0
    monkeypatch.setattr(sb, "baseline_blocks", lambda *a, **k: {})
    data, teams, weeks = _world(gp=60.0)
    off = mr.simulated(data, teams, range(1, 5), {}, sb.KeyedDraws(SEED, 500), anchor, MANAGERS)
    assert off["rate"] == 0.0


def test_unprojected_players_are_not_counted_as_misses():
    data, teams, weeks = _world()
    teams["Nick"].players["P2Nick"].projected_fppg = 0.0
    anchor = date.fromisoformat(weeks[0]["start_date"])
    got = mr.simulated(data, teams, [1], {}, sb.KeyedDraws(SEED, 200), anchor, MANAGERS)
    assert got["unprojected_games"] == 7 and got["games"] == 7 * 11


def test_realized_is_a_scheduled_game_with_exactly_zero_points():
    lineups = pd.DataFrame([
        {"week": 1, "nba_opponent": "@BOS", "fantasy_points": 0.0},     # a miss
        {"week": 1, "nba_opponent": "MIA", "fantasy_points": 31.5},
        {"week": 1, "nba_opponent": "MIA", "fantasy_points": 0.25},     # played, scored little
        {"week": 1, "nba_opponent": np.nan, "fantasy_points": np.nan},  # no game: not counted
        {"week": 1, "nba_opponent": "", "fantasy_points": ""},
        {"week": 2, "nba_opponent": "DEN", "fantasy_points": 0.0},
    ])
    assert mr.realized(lineups, [1])[:2] == (1, 3)
    assert mr.realized(lineups)[:2] == (2, 4)


def test_the_history_band_is_measured_per_season():
    rows = [{"season_key": s, "week": 1, "had_game": True, "fantasy_points": fp,
             "manager": "Nick", "date": "d", "started": True}
            for s, fps in (("A", [0, 10, 10, 10]), ("B", [0, 0, 10, 10])) for fp in fps]
    assert mr.band(rows, [1]) == (0.25, 0.5)
    assert mr.pooled(rows)[2] == pytest.approx(3 / 8)


# handoff 32: the per-week check -- measured per week, gated only where unplayed
def test_the_band_by_week_is_each_week_s_own_range():
    rows = [{"season_key": s, "week": w, "had_game": True, "fantasy_points": fp}
            for s, w, fp in [("A", 1, 0.0), ("A", 1, 10.0), ("A", 2, 10.0),
                             ("B", 1, 10.0), ("B", 1, 10.0), ("B", 2, 0.0), ("B", 2, 0.0)]]
    assert mr.band_by_week(rows, [1, 2]) == {1: (0.0, 0.5), 2: (0.0, 1.0)}
    with pytest.raises(ValueError, match="no season in the log plays week 3"):
        mr.band_by_week(rows, [3])


def test_the_per_week_check_gates_only_the_weeks_not_yet_played():
    import pandas as pd
    played = mr.played_weeks(pd.DataFrame({"week": [1, 1, 2]}))
    assert played == [1, 2] and mr.played_weeks(None) == []
    rows = mr.check_by_week({1: 0.30, 2: 0.10, 3: 0.12, 4: 0.40, 5: 0.01, 6: 0.01},
                            {w: (0.05, 0.20) for w in range(1, 7)}, played + [6])
    # a gated week checks only the upper edge (Nick, 11-25, S1 option C): week 5 sits under the band
    # and passes; a played week (6) keeps the whole band
    assert [(w, gated, ok) for w, _r, _lo, _hi, gated, ok in rows] == [
        (1, False, False), (2, False, True), (3, True, True), (4, True, False), (5, True, True), (6, False, False)]


# S1 (Nick, 11-25, from 32 sec. 7): the per-week check measures only games no
# INJURY_OVERRIDES entry governs; the weeks 1-15 gate still counts them
def test_the_per_week_check_leaves_out_the_weeks_an_override_governs():
    data, teams, weeks = _world(gp=82.0)                 # nobody misses by durability
    anchor = date.fromisoformat(weeks[0]["start_date"])
    teams["Nick"].players["P0Nick"].out_weeks = [1, 2]   # out two of four weeks
    draws = sb.KeyedDraws(SEED, 500)
    counted = mr.simulated(data, teams, range(1, 5), {}, draws, anchor, MANAGERS)
    assert counted["excluded_games"] == 0 and counted["by_manager"]["Nick"] == pytest.approx((14 / 28) / 3)
    left_out = mr.simulated(data, teams, range(1, 5), {}, draws, anchor, MANAGERS, exclude_governed=True)
    assert left_out["excluded_games"] == 14                  # his two governed weeks
    assert left_out["games"] == counted["games"] - 14
    assert left_out["by_manager"]["Nick"] == 0.0             # the chain's own misses only
    detail = mr.simulated_by_week_detail(data, teams, range(1, 5), {}, draws, anchor, MANAGERS)
    assert [detail[w]["excluded_games"] for w in range(1, 5)] == [7, 7, 0, 0]
    assert mr.simulated_by_week(data, teams, range(1, 5), {}, draws, anchor, MANAGERS) == \
        {w: d["rate"] for w, d in detail.items()} == {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}


def test_a_return_week_and_an_out_from_week_are_governed_too():
    data, teams, weeks = _world(gp=82.0)
    anchor = date.fromisoformat(weeks[0]["start_date"])
    p = teams["Hayden"].players["P1Hayden"]
    p.return_week, p.return_date = 2, weeks[1]["end_date"]       # back on week 2's last day
    q = teams["Benton"].players["P2Benton"]
    q.out_from = date.fromisoformat(weeks[2]["start_date"]) + timedelta(days=3)
    detail = mr.simulated_by_week_detail(data, teams, range(1, 5), {}, sb.KeyedDraws(SEED, 300),
                                         anchor, MANAGERS)
    assert [detail[w]["excluded_games"] for w in range(1, 5)] == [0, 7, 7, 0]
    assert all(detail[w]["rate"] == 0.0 for w in range(1, 5))


def test_a_game_the_plan_drops_for_no_known_reason_raises(monkeypatch):
    data, teams, weeks = _world(gp=82.0)
    anchor = date.fromisoformat(weeks[0]["start_date"])
    real = sb._week_plan

    def lossy(*a, **k):                                  # the plan loses Nick's P0 on every day
        return {m: [(d, [e for e in es if e[8] != "P0Nick"]) for d, es in days]
                for m, days in real(*a, **k).items()}
    monkeypatch.setattr(sb, "_week_plan", lossy)
    with pytest.raises(ValueError, match="no INJURY_OVERRIDES entry governs"):
        mr.simulated(data, teams, [1], {}, sb.KeyedDraws(SEED, 50), anchor, MANAGERS)
