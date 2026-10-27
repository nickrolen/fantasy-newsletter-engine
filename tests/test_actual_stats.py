"""A missed game is not a game played (HANDOFF_DNP_FIX_2026-10-23).

compute_actual_stats averaged lineup SLOTS: a player in the lineup whose team
played and who sat scored 0.0, and that 0.0 went into actual_fppg, actual_std
and actual_games. The engine already prices whether he plays (tags,
INJURY_OVERRIDES, the baseline hazard), so that was every absence charged
twice -- Nikola Jokic read 0.00 after one missed game.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules.data_loader import FantasyData
from modules.projections import (
    PlayerProjection, appearances, compute_actual_stats, populate_actual_stats,
)

ROOT = Path(__file__).parent.parent


def _log(rows):
    """rows: (player, fantasy_points, started, is_injured[, had_game])."""
    cols = ["player_name", "fantasy_points", "started", "is_injured", "had_game"]
    full = [r if len(r) == 5 else (*r, True) for r in rows]
    df = pd.DataFrame(full, columns=cols)
    return df


def _live_shape(df):
    """The live PLAYERLOG has no had_game column: it only holds game days."""
    return df.drop(columns=["had_game"])


MIXED = [
    ("A", 40.0, True, False), ("A", 0.0, True, True), ("A", 30.0, True, False),
    ("A", 0.0, True, True), ("A", 50.0, True, False),
    ("A", 22.0, False, False),            # benched appearance: not a started game
    ("B", 0.0, True, True), ("B", 0.0, True, True),
    ("C", 35.5, True, False),
]


# 1 -- actual_fppg never counts a game he did not play; games is appearances
@pytest.mark.parametrize("shape", ["live", "historical"])
def test_actual_stats_are_per_game_played(shape):
    df = _log(MIXED)
    if shape == "live":
        df = _live_shape(df)
    stats = compute_actual_stats(FantasyData(playerlog=df))
    played = np.array([40.0, 30.0, 50.0])
    assert stats["A"]["games"] == 3
    assert stats["A"]["actual_fppg"] == pytest.approx(played.mean())
    assert stats["A"]["std"] == pytest.approx(played.std(ddof=1))
    assert stats["A"]["total_fp"] == pytest.approx(played.sum())
    assert stats["C"]["games"] == 1 and stats["C"]["actual_fppg"] == 35.5
    # B never played: no appearances, so no actual record at all
    assert "B" not in stats


def test_historical_off_day_rows_are_not_games():
    """The historical log carries had_game=False rows scoring 0.0 (21,811 of
    them). A FantasyData built from those must not count them."""
    df = _log([("A", 40.0, True, False, True), ("A", 0.0, True, False, False),
               ("A", 0.0, True, False, False), ("A", 20.0, True, False, True)])
    stats = compute_actual_stats(FantasyData(playerlog=df))
    assert stats["A"]["games"] == 2
    assert stats["A"]["actual_fppg"] == pytest.approx(30.0)


def test_no_is_injured_column_refuses_rather_than_averaging_slots():
    df = _log(MIXED).drop(columns=["is_injured"])
    with pytest.raises(ValueError, match="is_injured"):
        compute_actual_stats(FantasyData(playerlog=df))


def _proj(stats_rows, projected=30.0):
    p = {"A": PlayerProjection("A", "XXX", ["PG"], projected_fppg=projected)}
    populate_actual_stats(p, FantasyData(playerlog=_live_shape(_log(stats_rows))))
    return p["A"]


# 2 -- one appearance and one miss: strictly above what a zero would imply
def test_one_appearance_one_miss_is_priced_above_the_zero():
    p = _proj([("A", 40.0, True, False), ("A", 0.0, True, True)])
    # what the slot average produced: mean 20 over "2 games", weight 0.2
    with_zero = 0.2 * 20.0 + 0.8 * 30.0
    assert p.effective_fppg > with_zero
    # and exactly the one game he played, at weight 1/10
    assert p.actual_games == 1
    assert p.effective_fppg == pytest.approx(0.1 * 40.0 + 0.9 * 30.0)


# 3 -- misses only: no appearances, so the projection
def test_misses_without_an_appearance_return_the_projection():
    p = _proj([("A", 0.0, True, True), ("A", 0.0, True, True)], projected=61.51)
    assert p.actual_games == 0
    assert p.effective_fppg == 61.51
    assert p.effective_std == pytest.approx(61.51 * 0.35)


def test_live_log_no_player_is_marked_down_by_a_miss():
    """Reality check on the real PLAYERLOG: every player's actual_fppg is the
    mean of the started games he scored in, and nobody with a miss reads
    lower than his own appearances."""
    path = ROOT / "data" / "PLAYERLOG.xlsx"
    if not path.exists():
        pytest.skip("no live PLAYERLOG")
    df = pd.read_excel(path)
    stats = compute_actual_stats(FantasyData(playerlog=df))
    started = df[df["started"] == True]
    missed = set(started.loc[started["is_injured"] == True, "player_name"])
    assert missed, "the live log has no misses; this test checks nothing"
    for name, grp in started.groupby("player_name"):
        played = grp.loc[grp["fantasy_points"] != 0, "fantasy_points"]
        if played.empty:
            assert name not in stats
            continue
        assert stats[name]["games"] == len(played)
        assert stats[name]["actual_fppg"] == pytest.approx(played.mean())
