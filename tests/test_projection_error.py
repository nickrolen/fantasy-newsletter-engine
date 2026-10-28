"""The engine is sometimes wrong about who is good (HANDOFF_PERSISTENT_ERROR_2026-10-28).

One multiplier m per player per simulated season, m = exp(tau z - tau^2/2),
tau derived from the shrinkage curve's own constants. Mean-preserving,
persistent, keyed by the player alone, invisible to lineup choice.
"""
import math

import numpy as np
import pytest

from modules import data_loader as dl
from modules import projections as pj
from modules import simulator_betting as sb
from modules.data_loader import MANAGERS
from test_season_sim import _world

TAU0 = 0.35 / math.sqrt(20)


def _cfg(monkeypatch, **pe):
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", dict(dl._LEAGUE_CONFIG, projection_error=pe))


# 5 -- the width, derived
def test_tau_at_zero_is_derived_from_the_curve_constants():
    assert pj.projection_error_sd(0) == pytest.approx(TAU0)
    assert pj.projection_error_sd(0) == pytest.approx(0.0783, abs=1e-4)


@pytest.mark.parametrize("k, expect", [(0, 1.0), (20, math.sqrt(0.5)), (60, 0.5), (5, math.sqrt(0.8))])
def test_tau_narrows_with_appearances_exactly(k, expect):
    assert pj.projection_error_sd(k) == pytest.approx(TAU0 * expect)


def test_tau_follows_the_scale_and_k0(monkeypatch):
    _cfg(monkeypatch, scale=2.0)
    assert pj.projection_error_sd(0) == pytest.approx(2 * TAU0)
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", dict(dl._LEAGUE_CONFIG,
                                                    projection_shrinkage={"k0_games": 13}))
    assert pj.projection_error_sd(0) == pytest.approx(2 * 0.35 / math.sqrt(13))


# 7 -- required
def test_a_missing_scale_raises(monkeypatch):
    cfg = {k: v for k, v in dl._LEAGUE_CONFIG.items() if k != "projection_error"}
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", cfg)
    with pytest.raises(dl.UnspecifiedRule, match="projection_error"):
        pj.projection_error_sd(0)


def test_a_negative_scale_is_refused(monkeypatch):
    _cfg(monkeypatch, scale=-1)
    with pytest.raises(ValueError, match="scale"):
        pj.projection_error_sd(0)


# 1 -- mean-preserving
def test_the_multiplier_has_mean_one_and_the_derived_spread():
    data, teams = _world()
    tp = teams["Nick"]
    draws = sb.KeyedDraws(7, 200_000)
    m = sb._projection_error_multipliers(draws, tp, list(tp.players))
    allm = np.concatenate(list(m.values()))
    se = allm.std() / math.sqrt(len(allm))
    assert abs(allm.mean() - 1.0) < 4 * se
    assert np.log(allm).std() == pytest.approx(TAU0, rel=0.01)


def _week(data, teams, seed=3, n=4000, week=9):
    return sb.simulate_week_matrix(data, teams, sb.schedule_week(data, week), None, sb.KeyedDraws(seed, n))


def test_expected_points_do_not_move(monkeypatch):
    data, teams = _world()
    _cfg(monkeypatch, scale=1.0)
    on = _week(data, teams)
    _cfg(monkeypatch, scale=0.0)
    data2, teams2 = _world()
    off = _week(data2, teams2)
    for mgr in MANAGERS:
        diff = on[mgr]["score"] - off[mgr]["score"]          # paired: same draws otherwise
        se = diff.std() / math.sqrt(len(diff))
        assert abs(diff.mean()) < 4 * se, mgr
        assert on[mgr]["score"].std() > off[mgr]["score"].std()   # and the week widens


def test_scale_zero_is_the_engine_without_it_bit_for_bit(monkeypatch):
    """m = exp(0) = 1.0 exactly, so the old engine is the scale-0 engine."""
    _cfg(monkeypatch, scale=0.0)
    data, teams = _world()
    a = _week(data, teams)
    monkeypatch.setattr(sb, "_projection_error_multipliers",
                        lambda d, tp, keys: {k: np.ones(d.n) for k in keys})
    data2, teams2 = _world()
    b = _week(data2, teams2)
    for mgr in MANAGERS:
        assert np.array_equal(a[mgr]["score"], b[mgr]["score"])


# 2 -- persistent: one draw per player per season, keyed by the player alone
def test_the_draw_is_keyed_by_the_player_only_and_shared_by_every_week(monkeypatch):
    data, teams = _world()
    draws = sb.KeyedDraws(5, 500)
    seen = []
    real = draws.normals

    def spy(namespace, *key):
        if namespace == "projection_error":
            seen.append(key)
        return real(namespace, *key)
    draws.normals = spy
    for w in (9, 10, 14):
        sb.simulate_week_matrix(data, teams, sb.schedule_week(data, w), None, draws)
    assert seen and all(len(k) == 1 and isinstance(k[0], str) for k in seen)
    rostered = {n for tp in teams.values() for n in tp.players}
    assert {k[0] for k in seen} <= rostered
    # one array per player, whichever week asked: the same m in weeks 9, 10, 14
    m1 = sb._projection_error_multipliers(draws, teams["Nick"], ["Nick0"])["Nick0"]
    m2 = sb._projection_error_multipliers(sb.KeyedDraws(5, 500), teams["Nick"], ["Nick0"])["Nick0"]
    assert np.array_equal(m1, m2)
    assert m1.std() > 0.05                                    # and it differs across iterations


def test_a_player_keeps_his_draw_when_he_changes_rosters():
    data, teams = _world()
    draws = sb.KeyedDraws(5, 300)
    a = sb._projection_error_multipliers(draws, teams["Nick"], ["Nick3"])["Nick3"]
    moved = dict(teams["Hayden"].players, Nick3=teams["Nick"].players["Nick3"])
    tp = sb.TeamProjections("Hayden", moved, weekly_std_dev=140.0)
    b = sb._projection_error_multipliers(sb.KeyedDraws(5, 300), tp, ["Nick3"])["Nick3"]
    assert np.array_equal(a, b)


# 6 -- lineup choice never sees m
def test_the_starters_are_the_same_with_and_without_it(monkeypatch):
    data, teams = _world()
    _cfg(monkeypatch, scale=1.0)
    on = _week(data, teams)
    _cfg(monkeypatch, scale=0.0)
    data2, teams2 = _world()
    off = _week(data2, teams2)
    for mgr in MANAGERS:
        assert np.array_equal(on[mgr]["games"], off[mgr]["games"]), mgr


# 3 and 4 are the Phase 2 invariants, already held with this draw in place by
# test_season_sim: test_a_week_in_the_pass_is_the_betting_lines_week and
# test_one_managers_roster_never_moves_another_managers_week.
def test_the_phase_2_invariants_are_exercised_with_the_draw_on():
    import inspect
    import test_season_sim as tss
    assert "simulate_week_matrix" in inspect.getsource(tss.test_a_week_in_the_pass_is_the_betting_lines_week)
    assert pj.projection_error_sd(0) > 0
