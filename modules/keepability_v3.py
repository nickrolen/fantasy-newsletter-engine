"""Keepability v3: the chance a player's manager keeps him next offseason.

KEEPABILITY_V3_DESIGN.md (revised 10-29); HANDOFF_KEEPABILITY_B_FIT_2026-10-29.

THE MODEL. Each manager keeps K of the N players on his roster. Every player
gets a score s = beta . x, and the K kept are a draw from

    P(S) = exp(sum of s over S) / sum over every K-subset T of exp(sum over T)

-- the conditional logit for choosing K of N (the multivariate noncentral
hypergeometric; close to, but not the same as, Plackett-Luce's unordered
top-K). Its normalizer is the K-th elementary
symmetric polynomial of w = exp(s), computed exactly by recursion, so the fit
is exact maximum likelihood (Newton's method, analytic Hessian) and a player's
keep probability is EXACT, not sampled:

    pi_i = w_i * e_{K-1}(w without i) / e_K(w)

and every roster's probabilities sum to K by construction. Fitted with numpy
alone (no scipy in the build environment).

EARLY IN A SEASON some eventual keepers are not on the roster yet. The fit
conditions on the keepers who were (K_r of them); a prediction for a K-keeper
offseason averages over how many of the K come from today's roster, using how
many were missing at that point in the seasons fitted (missing_keepers).

The weekly build never refits: predict() reads config/keepability_v3_params.json,
which scripts/fit_keepability_v3.py writes once a season, after the keepers are
chosen. A missing or malformed file RAISES.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PARAMS_FILE = ROOT / "config" / "keepability_v3_params.json"
POINTS = ("week2", "mid", "end")
AGE_CENTER = 27.0
RANK_CENTER = 36.0   # log_draft_rank is 0 at the 36th player taken, so "kept" and
                     # "undrafted" read against a mid-draft pick, not pick 1
YOUNG_AGE = 23


# ---------------------------------------------------------------------------
# the level's prior (step B2): one season, or several, games-weighted
# ---------------------------------------------------------------------------

PRIOR_SPECS = {
    "P1":  {"seasons": 1, "min_games": 10, "recency": None,
            "text": "last season's FPPG, if he played 10+ games then (step B)"},
    "P2":  {"seasons": 2, "min_games": 1, "recency": None,
            "text": "the last two seasons, games-weighted"},
    "P3":  {"seasons": 3, "min_games": 1, "recency": None,
            "text": "the last three seasons, games-weighted"},
    "P3r": {"seasons": 3, "min_games": 1, "recency": (3, 2, 1),
            "text": "the last three seasons, games x recency 3:2:1 (stated before fitting, not tuned)"},
}


class PriorError(KeyError):
    pass


def prior_from_lines(season: str, lines: Sequence, spec: str) -> tuple:
    """(prior FPPG or None, [(season, games, fppg) used]) from a player's
    previous seasons in the log (keeper_history.previous_lines: newest first,
    seasons he appeared in). Only seasons BEFORE `season`, within the spec's
    window counted in calendar seasons; each weighted by its games (and, for
    P3r, by recency). None: nothing in the window -- the caller falls back to
    the league mean."""
    if spec not in PRIOR_SPECS:
        raise PriorError(f"unknown prior spec {spec!r}")
    cfg = PRIOR_SPECS[spec]
    used, num, den = [], 0.0, 0.0
    for ls, games, fppg in lines:
        back = int(season[:4]) - int(str(ls)[:4])
        if back < 1:
            raise ValueError(f"prior line {ls} is not before {season}")
        if back > cfg["seasons"] or games < cfg["min_games"]:
            continue
        w = games * (cfg["recency"][back - 1] if cfg["recency"] else 1)
        num += w * fppg
        den += w
        used.append((ls, games, fppg))
    return (num / den if den else None), used


def level_config(params: Optional[dict]) -> dict:
    """{spec, k0_prior, k0_league_mean} from the parameters file's
    "level_prior". Missing or incomplete RAISES: each spec's k0 is measured
    and recorded, never a code constant."""
    lp = (params or {}).get("level_prior")
    if not isinstance(lp, dict):
        raise PriorError("the parameters have no level_prior (spec and its measured k0)")
    need = [k for k in ("spec", "k0_prior", "k0_league_mean") if not isinstance(lp.get(k), (str, int, float))]
    if need or lp["spec"] not in PRIOR_SPECS:
        raise PriorError(f"level_prior is incomplete or unknown: missing {need}, spec {lp.get('spec')!r}")
    for k in ("k0_prior", "k0_league_mean"):
        if not (isinstance(lp[k], (int, float)) and lp[k] > 0):
            raise PriorError(f"level_prior.{k} must be a positive number, got {lp[k]!r}")
    return lp


def level_of(c, lp: dict) -> tuple:
    """(level, prior, k0, prior kind, seasons used) for one candidate: FPPG so
    far shrunk toward the spec's prior, w = k / (k + k0), k = games so far
    (bench games count); the prior itself at zero games."""
    prior, used = prior_from_lines(c.season, c.prev_lines, lp["spec"])
    if prior is None:
        if c.league_mean is None:
            raise ValueError(f"{c.player}: no prior and no league mean")
        prior, k0, kind = float(c.league_mean), float(lp["k0_league_mean"]), "league mean"
    else:
        k0, kind = float(lp["k0_prior"]), lp["spec"]
    k = int(c.games or 0)
    w = k / (k + k0)
    return ((w * float(c.fppg) + (1 - w) * prior) if k else prior), prior, k0, kind, used


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

def _undrafted(c) -> bool:
    return (not c.kept) and c.draft_rank is None


FEATURES = {
    "kept":            lambda c, m: float(c.kept),
    "log_draft_rank":  lambda c, m: (math.log(c.draft_rank / RANK_CENTER)
                                     if (c.draft_rank and not c.kept) else 0.0),
    "undrafted":       lambda c, m: float(_undrafted(c)),
    "undrafted_trade": lambda c, m: float(_undrafted(c) and c.acquired == "trade"),
    "level":           lambda c, m: float(level_of(c, m["level_prior"])[0]),
    "availability":    lambda c, m: float(c.availability) if c.availability is not None else m["availability"],
    "age":             lambda c, m: float(c.age) - AGE_CENTER,
    "young":           lambda c, m: float(c.age <= YOUNG_AGE),
    "age_sq":          lambda c, m: (float(c.age) - AGE_CENTER) ** 2 / 10.0,
    "fppg_rank":       lambda c, m: float(c.fppg_rank),
}
FEATURE_TEXT = {
    "kept": "kept this season (carried on a trade); 0 for everyone in 2021-22",
    "log_draft_rank": "log(overall draft rank / 36) -- rank = players kept league-wide + pick -- for drafted non-keepers; 0 otherwise",
    "undrafted": "neither kept nor drafted this season",
    "undrafted_trade": "undrafted and arrived by trade",
    "level": "FPPG so far shrunk toward the prior, w = k/(k+k0); k0 13 (last season) or 4.7 (league mean)",
    "availability": "games / his team's games while rostered so far; missing -> that snapshot's mean",
    "age": f"age that season - {AGE_CENTER:g}",
    "young": f"age {YOUNG_AGE} or under",
    "age_sq": f"(age - {AGE_CENTER:g})^2 / 10",
    "fppg_rank": "FPPG rank on his roster so far (variant only)",
}


def fill_values(cands, level_prior: Optional[dict] = None) -> dict:
    """Snapshot-level values for missing inputs (point-in-time: from the same
    snapshot), and the level's prior configuration."""
    av = [c.availability for c in cands if c.availability is not None]
    return {"availability": float(np.mean(av)) if av else 1.0, "level_prior": level_prior}


def design(cands, features: Sequence[str], fill: Optional[dict] = None,
           level_prior: Optional[dict] = None) -> np.ndarray:
    fill = fill or fill_values(cands, level_prior)
    if "level" in features:
        level_config({"level_prior": fill.get("level_prior")})          # raises if missing
    unknown = [f for f in features if f not in FEATURES]
    if unknown:
        raise KeyError(f"unknown features {unknown}")
    missing_age = [c.player for c in cands if c.age is None]
    if missing_age and any(f in features for f in ("age", "young", "age_sq")):
        raise ValueError(f"no age for {missing_age}")
    return np.array([[FEATURES[f](c, fill) for f in features] for c in cands], dtype=float)


# ---------------------------------------------------------------------------
# the choose-K-of-N likelihood, exactly
# ---------------------------------------------------------------------------

class Rosters:
    """Rosters padded into arrays: X (R, N, p), mask (R, N), chosen (R, N), K (R,)."""

    def __init__(self, Xs: list, chosen: list, K: Sequence[int], labels: Optional[list] = None):
        R, p = len(Xs), (Xs[0].shape[1] if Xs else 0)
        N = max(x.shape[0] for x in Xs) if Xs else 0
        self.X = np.zeros((R, N, p))
        self.mask = np.zeros((R, N), dtype=bool)
        self.chosen = np.zeros((R, N), dtype=bool)
        for r, (x, ch) in enumerate(zip(Xs, chosen)):
            self.X[r, :len(x)] = x
            self.mask[r, :len(x)] = True
            self.chosen[r, :len(x)] = ch
        self.K = np.asarray(K, dtype=int)
        self.labels = labels or [None] * R
        if np.any(self.K > self.mask.sum(1)):
            raise ValueError("a roster has K above its size")


def _esp(w: np.ndarray, kmax: int) -> np.ndarray:
    """e[r, j] = j-th elementary symmetric polynomial of w[r, :], j = 0..kmax."""
    R, N = w.shape
    e = np.zeros((R, kmax + 1))
    e[:, 0] = 1.0
    for l in range(N):
        for j in range(kmax, 0, -1):
            e[:, j] += w[:, l] * e[:, j - 1]
    return e


def _esp_without(w: np.ndarray, kmax: int) -> np.ndarray:
    """e[r, i, j]: the j-th ESP of w[r, :] without position i."""
    R, N = w.shape
    e = np.zeros((R, N, kmax + 1))
    e[:, :, 0] = 1.0
    for l in range(N):
        keep = np.ones(N)
        keep[l] = 0.0
        wl = w[:, l][:, None] * keep[None, :]
        for j in range(kmax, 0, -1):
            e[:, :, j] += wl * e[:, :, j - 1]
    return e


def _esp_without_pairs(w: np.ndarray, kmax: int) -> np.ndarray:
    """e[r, i, k, j]: the j-th ESP of w[r, :] without positions i and k."""
    R, N = w.shape
    e = np.zeros((R, N, N, kmax + 1))
    e[:, :, :, 0] = 1.0
    for l in range(N):
        keep = np.ones((N, N))
        keep[l, :] = 0.0
        keep[:, l] = 0.0
        wl = w[:, l][:, None, None] * keep[None]
        for j in range(kmax, 0, -1):
            e[:, :, :, j] += wl * e[:, :, :, j - 1]
    return e


def _weights(ros: Rosters, beta: np.ndarray) -> np.ndarray:
    s = ros.X @ beta
    s = np.where(ros.mask, s, -np.inf)
    top = np.max(np.where(ros.mask, s, -np.inf), axis=1, keepdims=True)
    return np.where(ros.mask, np.exp(s - top), 0.0), np.where(ros.mask, s - top, 0.0)


def loglik(ros: Rosters, beta: np.ndarray) -> np.ndarray:
    """Per-roster log P(chosen set | K)."""
    w, s = _weights(ros, beta)
    e = _esp(w, int(ros.K.max()))
    eK = e[np.arange(len(ros.K)), ros.K]
    return (s * ros.chosen).sum(1) - np.log(eK)


def inclusion(ros: Rosters, beta: np.ndarray, K=None) -> np.ndarray:
    """pi[r, i]: P(player i kept), exactly; sums to K on every roster."""
    K = ros.K if K is None else np.broadcast_to(np.asarray(K, dtype=int), ros.K.shape)
    w, _ = _weights(ros, beta)
    kmax = int(K.max())
    if kmax <= 0:
        return np.zeros_like(w)
    e = _esp(w, kmax)
    em = _esp_without(w, kmax)
    r = np.arange(len(K))
    eK = e[r, K]
    km1 = np.maximum(K - 1, 0)
    pi = w * em[r[:, None], np.arange(w.shape[1])[None, :], km1[:, None]] / eK[:, None]
    return np.where((K[:, None] > 0) & ros.mask, pi, 0.0)


def _grad_hess(ros: Rosters, beta: np.ndarray):
    w, _ = _weights(ros, beta)
    kmax = int(ros.K.max())
    e = _esp(w, kmax)
    em = _esp_without(w, kmax)
    epp = _esp_without_pairs(w, kmax)
    R, N, p = ros.X.shape
    r = np.arange(R)
    eK = e[r, ros.K]
    pi = w * em[r[:, None], np.arange(N)[None, :], np.maximum(ros.K - 1, 0)[:, None]] / eK[:, None]
    pi = np.where(ros.mask, pi, 0.0)
    km2 = np.maximum(ros.K - 2, 0)
    pij = (w[:, :, None] * w[:, None, :]
           * epp[r[:, None, None], np.arange(N)[None, :, None], np.arange(N)[None, None, :], km2[:, None, None]]
           / eK[:, None, None])
    pij = np.where(ros.K[:, None, None] >= 2, pij, 0.0)
    idx = np.arange(N)
    pij[:, idx, idx] = pi
    pij = pij * ros.mask[:, :, None] * ros.mask[:, None, :]
    g = (ros.X * (ros.chosen.astype(float) - pi)[:, :, None]).sum((0, 1))
    cov = pij - pi[:, :, None] * pi[:, None, :]
    H = -np.einsum("rip,rij,rjq->pq", ros.X, cov, ros.X)
    return g, H


class FitError(RuntimeError):
    pass


PRIOR_SCALE = 2.5


def prior_scales(ros: Rosters) -> np.ndarray:
    """Per-feature scale for the weakly informative prior (Gelman et al.
    2008): an indicator as is, a continuous input at two standard deviations
    -- so the prior says the same thing about every feature."""
    X = ros.X[ros.mask]
    out = []
    for j in range(X.shape[1]):
        col = X[:, j]
        binary = set(np.unique(col)) <= {0.0, 1.0}
        out.append(1.0 if binary else 2.0 * float(col.std()) or 1.0)
    return np.array(out)


def fit(ros: Rosters, max_iter: int = 100, tol: float = 1e-9, prior_scale: float = PRIOR_SCALE) -> dict:
    """Maximum a posteriori by Newton's method with step halving, under a
    weakly informative normal prior, sd prior_scale, on each coefficient times
    its feature's scale (prior_scales). Deterministic.

    Why a prior: maximum likelihood alone runs off under quasi-separation.
    At week 2, in five of the six decisions, no undrafted player on a roster
    then was ever kept; plain ML put "undrafted" at -23.7 and called Tyrese
    Maxey's 2024-25 keep (Benton) impossible -- held-out log-likelihood
    -15.6 a roster, worse than guessing. The prior keeps never-seen as rare,
    not impossible, and barely moves a well-identified coefficient. Fixed by
    convention, not tuned. prior_scale=None is plain ML.

    Returns {beta, se, loglik (the data's), iterations, scales}. Raises
    FitError if it does not converge."""
    p = ros.X.shape[2]
    sc = prior_scales(ros)
    prec = np.zeros(p) if prior_scale is None else (sc / prior_scale) ** 2
    beta = np.zeros(p)

    def objective(b):
        return loglik(ros, b).sum() - 0.5 * float(np.sum(prec * b * b))
    ll = objective(beta)
    for it in range(1, max_iter + 1):
        g, H = _grad_hess(ros, beta)
        g = g - prec * beta
        H = H - np.diag(prec)
        try:
            step = np.linalg.solve(H, -g)
        except np.linalg.LinAlgError as e:
            raise FitError(f"singular Hessian at iteration {it}: {e}") from e
        t = 1.0
        while True:
            nb = beta + t * step
            nll = objective(nb)
            if nll >= ll - 1e-12 or t < 1e-8:
                break
            t /= 2
        beta, gain, ll = nb, nll - ll, nll
        if np.max(np.abs(g)) < tol or abs(gain) < tol:
            break
        if np.max(np.abs(beta)) > 50:
            raise FitError(f"coefficients diverging: {beta}")
    else:
        raise FitError(f"no convergence in {max_iter} iterations")
    _, H = _grad_hess(ros, beta)
    cov = np.linalg.inv(-(H - np.diag(prec)))
    return {"beta": beta, "se": np.sqrt(np.clip(np.diag(cov), 0, None)),
            "loglik": float(loglik(ros, beta).sum()), "iterations": it, "scales": sc}


def uniform_loglik(ros: Rosters) -> np.ndarray:
    n = ros.mask.sum(1)
    return np.array([-math.log(math.comb(int(a), int(k))) for a, k in zip(n, ros.K)])


def mixture_inclusion(ros: Rosters, beta: np.ndarray, K: int, missing: dict) -> np.ndarray:
    """P(kept) when the offseason keeps K and, as in the seasons fitted,
    m of them may not be on today's roster with probability missing[m]."""
    pi = np.zeros(ros.mask.shape)
    for m, pm in missing.items():
        k_here = np.minimum(np.maximum(K - int(m), 0), ros.mask.sum(1))
        pi += float(pm) * inclusion(ros, beta, k_here)
    return pi


# ---------------------------------------------------------------------------
# the parameters file, and predict
# ---------------------------------------------------------------------------

class ParamsError(ValueError):
    pass


def load_params(path=None) -> dict:
    path = Path(path or PARAMS_FILE)
    if not path.is_file():
        raise ParamsError(f"{path} is missing; run scripts/fit_keepability_v3.py "
                          "(once a season, after the keepers are chosen)")
    try:
        params = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ParamsError(f"{path} is not valid JSON: {e}") from e
    need = ("version", "features", "points", "level_prior", "fitted_on", "dataset_sha256")
    gone = [k for k in need if k not in params]
    if gone or params.get("version") != 3:
        raise ParamsError(f"{path} is malformed: missing {gone} or version != 3")
    try:
        level_config(params)
    except PriorError as e:
        raise ParamsError(f"{path}: {e}") from e
    for pt in POINTS:
        blob = params["points"].get(pt)
        if not isinstance(blob, dict) or "coef" not in blob or "missing_keepers" not in blob:
            raise ParamsError(f"{path}: point {pt!r} is missing or lacks coef / missing_keepers")
        if set(blob["coef"]) != set(params["features"]):
            raise ParamsError(f"{path}: point {pt!r} coefficients {sorted(blob['coef'])} "
                              f"do not match features {params['features']}")
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in blob["coef"].values()):
            raise ParamsError(f"{path}: point {pt!r} has a non-numeric coefficient")
    return params


def predict(rosters: dict, point: str, K: int, params: Optional[dict] = None,
            params_path=None) -> dict:
    """{manager: [(player, keep probability)]}, best first, for an offseason
    keeping K. rosters: {manager: [keeper_history.Candidate]}. Reads the
    parameters file (raises if missing or malformed)."""
    params = params or load_params(params_path)
    blob = params["points"][point]
    feats = params["features"]
    beta = np.array([blob["coef"][f] for f in feats])
    mans = sorted(rosters)
    allc = [c for m in mans for c in rosters[m]]
    fill = fill_values(allc, level_config(params))
    ros = Rosters([design(rosters[m], feats, fill) for m in mans],
                  [np.zeros(len(rosters[m]), dtype=bool) for m in mans], [0] * len(mans))
    missing = {int(k): v for k, v in blob["missing_keepers"].items()}
    pi = mixture_inclusion(ros, beta, K, missing)
    out = {}
    for r, m in enumerate(mans):
        ps = [(c.player, float(pi[r, i])) for i, c in enumerate(rosters[m])]
        out[m] = sorted(ps, key=lambda t: (-t[1], t[0]))
    return out
