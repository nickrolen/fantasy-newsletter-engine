"""
backtest_metrics.py

Scoring rules and calibration statistics for the betting-line backtest.

Every function here is pure: it takes numbers, returns numbers, touches no
files, reads no config, and imports nothing outside the standard library.
That is deliberate -- these are the claims the newsletter makes about its own
accuracy, so they need to be testable in isolation.

WHAT IS BEING MEASURED
    The engine publishes, for each upcoming matchup, a projected score for
    both teams and a win probability. Three separate things can be wrong:

      1. LEVEL      -- are the projected team scores right on average?
                       (measured by score_error_stats)
      2. DIFFERENCE -- is the projected margin right on average?
                       (measured by margin_error_stats)
      3. CONFIDENCE -- is the stated uncertainty honest? A model can predict
                       the mean perfectly and still lie about how sure it is.
                       (measured by dispersion_ratio)

    (1) and (2) can disagree: if both teams are over-projected by the same
    amount the errors cancel in the margin and survive in the total. That is
    exactly what this league's data shows, which is why they are separate.

ON RECOVERING THE MODEL'S IMPLIED UNCERTAINTY
    The published newsletter prints projected scores and a win probability,
    but not the simulator's standard deviation. Under the simulator's own
    normal approximation the two are linked:

        P(A wins) = Phi(mu / sigma)   =>   sigma = mu / Phi^-1(p)

    so the uncertainty can be recovered from published numbers alone. This
    matters: the stored per-week JSON was overwritten by later re-runs, so
    the newsletter HTML is the only faithful record of what was predicted.

DESTINATION: scripts/backtest_report.py, and the Model Validation section of
the README.

INTEGRATION POINTS:
    - scripts/backtest_extract.py: produces the CSV these functions consume
    - scripts/backtest_report.py: calls every function here
"""

import math
from statistics import NormalDist, fmean, stdev
from typing import Optional, Sequence


# =============================================================================
# DISTRIBUTION HELPERS (stdlib only -- no scipy dependency)
# =============================================================================

_STD_NORMAL = NormalDist()


def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF. Clamped away from 0 and 1."""
    p = min(max(p, 1e-9), 1.0 - 1e-9)
    return _STD_NORMAL.inv_cdf(p)


def chi2_quantile(p: float, k: int) -> float:
    """
    Quantile of a chi-square distribution with k degrees of freedom.

    Wilson-Hilferty approximation:  X ~ k * (1 - 2/(9k) + z * sqrt(2/(9k)))^3

    Accurate to well under 1% for k >= 5, which is all this backtest needs.
    Used only to put a confidence interval on the dispersion ratio; it is not
    on any path that produces a published number.
    """
    if k <= 0:
        raise ValueError("degrees of freedom must be positive")
    z = norm_ppf(p)
    a = 2.0 / (9.0 * k)
    return k * (1.0 - a + z * math.sqrt(a)) ** 3


# =============================================================================
# 1. LEVEL -- are the team-score projections right on average?
# =============================================================================

def score_error_stats(projected: Sequence[float],
                      actual: Sequence[float]) -> dict:
    """
    Bias, MAE and RMSE of team-score projections.

    Sign convention: error = actual - projected, so a NEGATIVE bias means the
    model projects too high.

    Returns a dict with n, bias, mae, rmse, se_bias, t_stat, below (count of
    observations that landed under projection).
    """
    if len(projected) != len(actual):
        raise ValueError("projected and actual must be the same length")
    if len(projected) < 2:
        raise ValueError("need at least 2 observations")

    errors = [a - p for a, p in zip(actual, projected)]
    n = len(errors)
    bias = fmean(errors)
    se = stdev(errors) / math.sqrt(n)
    return {
        "n": n,
        "bias": bias,
        "mae": fmean(abs(e) for e in errors),
        "rmse": math.sqrt(fmean(e * e for e in errors)),
        "se_bias": se,
        "t_stat": bias / se if se > 0 else float("nan"),
        "below": sum(1 for e in errors if e < 0),
    }


# =============================================================================
# 2. DIFFERENCE -- is the projected margin right on average?
# =============================================================================

def margin_error_stats(projected_margin: Sequence[float],
                       actual_margin: Sequence[float]) -> dict:
    """
    Same statistics as score_error_stats, applied to matchup margins.

    Kept as a separate entry point because the two answer different questions
    and, in this league, give different answers.
    """
    return score_error_stats(projected_margin, actual_margin)


# =============================================================================
# 3. CONFIDENCE -- is the stated uncertainty honest?
# =============================================================================

def implied_sigma(projected_margin: float, win_prob: float,
                  min_edge: float = 1e-3) -> Optional[float]:
    """
    Recover the simulator's implied margin standard deviation from a published
    line, by inverting  P(A wins) = Phi(mu / sigma).

    Returns None when the win probability is within min_edge of 0.5 AND the
    projected margin is near zero -- there sigma is not identified, because
    every sigma produces a coin flip. Callers should drop those observations
    rather than let a divide-by-almost-zero manufacture a number.
    """
    z = norm_ppf(win_prob)
    if abs(z) < min_edge:
        return None
    sigma = projected_margin / z
    return sigma if sigma > 0 else None


def standardized_residuals(projected_margin: Sequence[float],
                           actual_margin: Sequence[float],
                           win_prob: Sequence[float]) -> list:
    """
    z = (actual - projected) / implied_sigma, one per matchup.

    If the simulator's uncertainty is honest these are ~N(0, 1). Observations
    where sigma is not identified are dropped.
    """
    out = []
    for mu, actual, p in zip(projected_margin, actual_margin, win_prob):
        sigma = implied_sigma(mu, p)
        if sigma is not None:
            out.append((actual - mu) / sigma)
    return out


def dispersion_ratio(residuals: Sequence[float], conf: float = 0.95) -> dict:
    """
    Root-mean-square of the standardized residuals, with a chi-square
    confidence interval.

    Interpretation:
        rms == 1  -- the stated uncertainty is about right
        rms >  1  -- OVER-confident: real outcomes are more spread out than
                     the simulator claims, so extreme moneylines are too
                     extreme
        rms <  1  -- UNDER-confident: intervals wider than they need to be

    The verdict field reports "cannot reject calibration" whenever the
    interval covers 1, which at small n is the honest answer.
    """
    n = len(residuals)
    if n < 2:
        raise ValueError("need at least 2 residuals")

    ss = sum(z * z for z in residuals)
    rms = math.sqrt(ss / n)
    alpha = 1.0 - conf
    lo = math.sqrt(ss / chi2_quantile(1.0 - alpha / 2.0, n))
    hi = math.sqrt(ss / chi2_quantile(alpha / 2.0, n))

    if hi < 1.0:
        verdict = "under-confident (intervals too wide)"
    elif lo > 1.0:
        verdict = "over-confident (intervals too narrow)"
    else:
        verdict = "cannot reject calibration"

    return {"n": n, "rms": rms, "mean": fmean(residuals),
            "ci_low": lo, "ci_high": hi, "verdict": verdict}


# =============================================================================
# 4. PROBABILITY SCORING
# =============================================================================

def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error of probabilistic forecasts. 0.25 = always saying 50%."""
    if len(probs) != len(outcomes):
        raise ValueError("probs and outcomes must be the same length")
    return fmean((p - o) ** 2 for p, o in zip(probs, outcomes))


def log_loss(probs: Sequence[float], outcomes: Sequence[int],
             eps: float = 1e-9) -> float:
    """Negative log likelihood. 0.6931 (= ln 2) = always saying 50%."""
    if len(probs) != len(outcomes):
        raise ValueError("probs and outcomes must be the same length")
    total = 0.0
    for p, o in zip(probs, outcomes):
        q = p if o else 1.0 - p
        total -= math.log(max(q, eps))
    return total / len(probs)


def brier_skill_score(probs: Sequence[float], outcomes: Sequence[int],
                      reference: float = 0.25) -> float:
    """
    Fraction of the reference Brier score removed. Positive means the
    forecasts beat the reference; 0 means no skill; negative means worse
    than the reference.
    """
    return 1.0 - brier_score(probs, outcomes) / reference


def hit_rate(predicted_favourite: Sequence[bool],
             favourite_won: Sequence[bool]) -> dict:
    """Straight-up accuracy of the side the model favoured."""
    if len(predicted_favourite) != len(favourite_won):
        raise ValueError("inputs must be the same length")
    correct = sum(1 for a, b in zip(predicted_favourite, favourite_won) if a == b)
    n = len(predicted_favourite)
    return {"n": n, "correct": correct, "rate": correct / n if n else float("nan")}
