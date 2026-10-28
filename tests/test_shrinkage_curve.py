"""One shrinkage curve instead of a cliff (HANDOFF_SHRINKAGE_CURVE_2026-10-28).

effective_fppg = w * actual + (1 - w) * projection, w = k / (k + k0), with k0
(projection_shrinkage.k0_games) in config. The old rule went to pure actuals
at ten games -- the engine's single worst cutoff -- and switched the per-game
spread to a measurement that is mostly noise.
"""
import pytest

from modules import data_loader as dl
from modules import projections as pj
from modules.projections import PlayerProjection

PROJ, ACT = 30.0, 42.0


def _p(k, actual=ACT, actual_std=99.0):
    return PlayerProjection(player_name="A", nba_team="BOS", positions=["PG"],
                            projected_fppg=PROJ, projected_gp=70.0,
                            actual_fppg=actual, actual_games=k, actual_std=actual_std)


def test_k0_is_the_configured_twenty():
    assert pj.shrinkage_k0() == 20.0


# 1 -- exactly k/(k+k0), and never pure actuals
@pytest.mark.parametrize("k", [0, 1, 3, 10, 20, 40])
def test_effective_fppg_is_the_curve_exactly(k):
    w = k / (k + 20.0)
    assert _p(k).effective_fppg == pytest.approx(w * ACT + (1 - w) * PROJ, abs=1e-12)


@pytest.mark.parametrize("k", [1, 10, 40, 82, 1000])
def test_the_projection_never_drops_out(k):
    assert _p(k).effective_fppg != ACT
    assert PROJ < _p(k).effective_fppg < ACT


# 2 -- the threshold is gone by name
def test_min_games_for_actual_is_gone():
    assert not hasattr(pj, "MIN_GAMES_FOR_ACTUAL")
    import inspect
    body = inspect.getsource(pj.PlayerProjection.effective_fppg.fget).split('"""')[2]
    assert "MIN_GAMES_FOR_ACTUAL" not in body                 # only the docstring names it


# 3 -- the spread is the projection's at every k
@pytest.mark.parametrize("k", [0, 1, 10, 20, 40])
def test_effective_std_is_std_dev_at_every_k(k):
    p = _p(k, actual_std=3.0)
    assert p.effective_std == p.std_dev == pytest.approx(PROJ * pj.DEFAULT_PLAYER_VARIANCE)


def test_default_player_variance_is_unchanged():
    assert pj.DEFAULT_PLAYER_VARIANCE == 0.35


# 4 -- k0 comes from config; a missing key raises
def test_a_missing_k0_raises_rather_than_defaulting(monkeypatch):
    cfg = {k: v for k, v in dl._LEAGUE_CONFIG.items() if k != "projection_shrinkage"}
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", cfg)
    with pytest.raises(dl.UnspecifiedRule, match="projection_shrinkage"):
        _ = _p(5).effective_fppg


def test_k0_follows_the_config(monkeypatch):
    cfg = dict(dl._LEAGUE_CONFIG, projection_shrinkage={"k0_games": 13})
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", cfg)
    assert _p(10).effective_fppg == pytest.approx((10 / 23) * ACT + (13 / 23) * PROJ)


def test_a_non_positive_k0_is_refused(monkeypatch):
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", dict(dl._LEAGUE_CONFIG,
                                                    projection_shrinkage={"k0_games": 0}))
    with pytest.raises(ValueError, match="k0_games"):
        _ = _p(5).effective_fppg


# 5 -- no games, the projection
def test_no_actual_games_is_the_projection(monkeypatch):
    assert _p(0).effective_fppg == PROJ
    assert _p(0, actual=None).effective_fppg == PROJ
    # and it does not even need the config: nothing to shrink
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", {})
    assert _p(0).effective_fppg == PROJ


def test_the_consumers_see_the_curve():
    """game_fp_params (every simulated game) and marginal_value read the same
    properties -- nothing of their own."""
    p = _p(10, actual_std=3.0)
    mean, sd = pj.game_fp_params(p, 1.0)
    assert mean == pytest.approx(p.effective_fppg) and sd == pytest.approx(p.std_dev)
