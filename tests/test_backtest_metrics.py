"""
Unit tests for modules/backtest_metrics.py.

These test the statistics, not the plumbing. Each one pins down a property
that would silently corrupt the published accuracy numbers if it broke:
sign conventions, a scoring rule's known values, the round trip between a
win probability and the uncertainty it implies, and whether the dispersion
statistic actually recognises well-calibrated and badly-calibrated input.
"""

import math
import random

import pytest

from modules.backtest_metrics import (
    norm_ppf,
    chi2_quantile,
    score_error_stats,
    implied_sigma,
    standardized_residuals,
    dispersion_ratio,
    brier_score,
    log_loss,
    brier_skill_score,
    hit_rate,
)


# ---------------------------------------------------------------- helpers ---

def test_norm_ppf_known_values():
    assert norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)
    assert norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-5)
    assert norm_ppf(0.025) == pytest.approx(-1.959964, abs=1e-5)


def test_chi2_quantile_close_to_reference():
    # Reference values from standard chi-square tables.
    assert chi2_quantile(0.95, 12) == pytest.approx(21.026, rel=0.01)
    assert chi2_quantile(0.05, 12) == pytest.approx(5.226, rel=0.02)


def test_chi2_quantile_rejects_bad_df():
    with pytest.raises(ValueError):
        chi2_quantile(0.5, 0)


# ------------------------------------------------------------ level stats ---

def test_score_error_sign_convention():
    """Over-projecting must produce a NEGATIVE bias. Getting this backwards
    would invert the headline claim in the README."""
    stats = score_error_stats(projected=[100.0, 100.0], actual=[90.0, 90.0])
    assert stats["bias"] == pytest.approx(-10.0)
    assert stats["below"] == 2


def test_score_error_perfect_prediction():
    stats = score_error_stats(projected=[10.0, 20.0, 30.0],
                              actual=[10.0, 20.0, 30.0])
    assert stats["bias"] == pytest.approx(0.0)
    assert stats["rmse"] == pytest.approx(0.0)
    assert stats["below"] == 0


def test_score_error_rmse_at_least_mae():
    stats = score_error_stats([0.0, 0.0, 0.0, 0.0], [1.0, -5.0, 2.0, 0.5])
    assert stats["rmse"] >= stats["mae"]


def test_score_error_rejects_ragged_input():
    with pytest.raises(ValueError):
        score_error_stats([1.0, 2.0], [1.0])


# ------------------------------------------------------ implied uncertainty --

def test_implied_sigma_round_trip():
    """Start from a known sigma, derive the win probability the simulator
    would print, then recover sigma from it."""
    mu, sigma = 120.0, 250.0
    p = math.erfc(-(mu / sigma) / math.sqrt(2.0)) / 2.0   # Phi(mu / sigma)
    assert implied_sigma(mu, p) == pytest.approx(sigma, rel=1e-6)


def test_implied_sigma_unidentified_at_coin_flip():
    """A 50% line pins down nothing about sigma; it must return None rather
    than divide by almost zero and invent a number."""
    assert implied_sigma(0.4, 0.5) is None


def test_implied_sigma_drops_unidentified_rows():
    z = standardized_residuals(projected_margin=[0.4, 100.0],
                               actual_margin=[10.0, 150.0],
                               win_prob=[0.5, 0.65])
    assert len(z) == 1


# ---------------------------------------------------------- dispersion ------

def test_dispersion_ratio_detects_calibrated_input():
    rng = random.Random(20260724)
    resid = [rng.gauss(0.0, 1.0) for _ in range(400)]
    out = dispersion_ratio(resid)
    assert out["rms"] == pytest.approx(1.0, abs=0.12)
    assert out["verdict"] == "cannot reject calibration"


def test_dispersion_ratio_detects_overconfidence():
    """Residuals twice as wide as claimed = the model was too sure."""
    rng = random.Random(1)
    resid = [rng.gauss(0.0, 2.0) for _ in range(400)]
    out = dispersion_ratio(resid)
    assert out["rms"] > 1.5
    assert out["verdict"] == "over-confident (intervals too narrow)"


def test_dispersion_ratio_detects_underconfidence():
    rng = random.Random(2)
    resid = [rng.gauss(0.0, 0.4) for _ in range(400)]
    out = dispersion_ratio(resid)
    assert out["verdict"] == "under-confident (intervals too wide)"


def test_dispersion_interval_brackets_the_estimate():
    out = dispersion_ratio([0.5, -1.2, 0.3, 2.0, -0.7, 1.1])
    assert out["ci_low"] < out["rms"] < out["ci_high"]


def test_dispersion_widens_with_small_samples():
    rng = random.Random(7)
    small = dispersion_ratio([rng.gauss(0, 1) for _ in range(12)])
    big = dispersion_ratio([rng.gauss(0, 1) for _ in range(400)])
    assert (small["ci_high"] - small["ci_low"]) > (big["ci_high"] - big["ci_low"])


# ------------------------------------------------------- probability scoring --

def test_brier_coin_flip_is_quarter():
    assert brier_score([0.5] * 4, [1, 0, 1, 0]) == pytest.approx(0.25)


def test_brier_perfect_and_worst():
    assert brier_score([1.0, 0.0], [1, 0]) == pytest.approx(0.0)
    assert brier_score([0.0, 1.0], [1, 0]) == pytest.approx(1.0)


def test_brier_skill_zero_for_coin_flip():
    assert brier_skill_score([0.5] * 4, [1, 0, 1, 0]) == pytest.approx(0.0)


def test_log_loss_coin_flip_is_ln_two():
    assert log_loss([0.5] * 4, [1, 0, 1, 0]) == pytest.approx(math.log(2.0))


def test_log_loss_is_finite_when_certain_and_wrong():
    """A 0.0 forecast on an event that happened must not raise or return inf."""
    assert math.isfinite(log_loss([0.0], [1]))


def test_hit_rate_counts_agreement():
    out = hit_rate([True, True, False], [True, False, False])
    assert out["correct"] == 2 and out["rate"] == pytest.approx(2 / 3)
