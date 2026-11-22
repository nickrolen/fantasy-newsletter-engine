"""5d1 s.10a (H56 Part 2, decision 1): the steal/bust records' actual counts
the same games as the round values' expected: the drafter's regular-season
starts on days he played (modules/draft_values.pick_game, one shared rule).
"""
import inspect
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import draft_values as DV                        # noqa: E402
import backfill_player_records as B                           # noqa: E402


def _row(**kw):
    r = {"started": True, "week": 3, "had_game": True, "is_injured": False}
    r.update(kw)
    return r


def test_the_one_rule_is_a_regular_season_start_on_a_day_he_played():
    assert DV.pick_game(_row(), 19)
    assert not DV.pick_game(_row(started=False), 19)                     # bench
    assert not DV.pick_game(_row(week=20), 19)                           # playoffs
    assert not DV.pick_game(_row(is_injured=True), 19)                   # the 0.0 injured row
    assert not DV.pick_game(_row(had_game=False), 19)                    # no game
    with pytest.raises(ValueError):
        DV.pick_game({"started": True, "week": 3}, 19)                   # a missing flag raises, never "played"


def test_both_sides_count_through_the_same_function():
    assert "pick_game(r, inp[\"reg\"])" in inspect.getsource(DV.pick_lines)
    assert "_dv.pick_game(row, through(s))" in inspect.getsource(B.pick_game_rows)
    assert "_dv.pick_game(r, through(s))" in inspect.getsource(B.pick_game_rows)
    with pytest.raises(ValueError, match="pick_games"):
        B.compute_draft_manager_leaderboards([{"player_name": "x"}], [{"season": "2024-25"}])
    with pytest.raises(DV.DraftValuesError):
        DV.regular_through("1999-00")


def test_pick_game_rows_keeps_only_the_rule_s_games():
    hist = [dict(_row(), season_key="2024-25", player_name="A", manager="Nick", fantasy_points=30.0),
            dict(_row(week=22), season_key="2024-25", player_name="A", manager="Nick", fantasy_points=50.0),
            dict(_row(started=False), season_key="2024-25", player_name="A", manager="Nick", fantasy_points=40.0)]
    cur = pd.DataFrame([{"season_year": "2026-2027", "week": 2, "player_name": "B", "manager": "Hayden",
                         "fantasy_points": 20.0, "started": True, "is_injured": False, "nba_opponent": "@LAL"},
                        {"season_year": "2026-2027", "week": 2, "player_name": "B", "manager": "Hayden",
                         "fantasy_points": 0.0, "started": True, "is_injured": True, "nba_opponent": "LAL"}])
    got = B.pick_game_rows(hist, cur)
    assert [(g["player_name"], g["fantasy_points"]) for g in got] == [("A", 30.0), ("B", 20.0)]


@pytest.mark.slow
def test_on_the_real_league_the_records_actual_equals_the_curves_games():
    if not (ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").exists():
        pytest.skip("no league log")
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        pg = B.pick_game_rows(B.load_historical_playerlog(), pd.DataFrame())
    agg = defaultdict(lambda: [0, 0.0])
    for g in pg:
        a = agg[(g["player_name"], g["manager"], g["season"])]
        a[0] += 1
        a[1] += g["fantasy_points"]
    lines = DV.pick_lines(ROOT)
    assert lines
    checked = 0
    for ln in lines:
        k = (ln["player"], ln["manager"], ln["season"])
        if k not in agg and ln["starts"] == 0:
            continue
        assert k in agg, k
        assert agg[k][0] == ln["starts"] and abs(agg[k][1] - ln["fp"]) < 0.01, (k, agg[k], ln)
        checked += 1
    assert checked >= 40
