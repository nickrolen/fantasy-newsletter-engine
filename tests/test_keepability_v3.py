"""Keepability v3, step B: the model, the fit and the parameters file.

HANDOFF_KEEPABILITY_B_FIT_2026-10-29, section 8.
"""
import itertools
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import keeper_history as kh                    # noqa: E402
from modules import keepability_v3 as M                     # noqa: E402
import fit_keepability_v3 as F                              # noqa: E402


def _synthetic(n_rosters=60, seed=1, beta=(1.2, -0.7, 0.3), k_range=(3, 7)):
    rng = np.random.default_rng(seed)
    Xs, ch, K = [], [], []
    for _ in range(n_rosters):
        n = int(rng.integers(12, 18))
        x = rng.normal(size=(n, len(beta)))
        k = int(rng.integers(*k_range))
        top = np.argsort(-(x @ np.array(beta) + rng.gumbel(size=n)))[:k]
        c = np.zeros(n, bool)
        c[top] = True
        Xs.append(x)
        ch.append(c)
        K.append(k)
    return M.Rosters(Xs, ch, K)


# 1 -- probabilities on every roster sum to K, for K = 5 and K = 6
@pytest.mark.parametrize("K", [5, 6])
def test_keep_probabilities_sum_to_k_on_every_roster(K):
    ros = _synthetic()
    pi = M.inclusion(ros, np.array([0.4, -0.2, 0.9]), K)
    assert np.allclose(pi.sum(1), K) and (pi >= 0).all() and (pi <= 1 + 1e-12).all()
    mix = M.mixture_inclusion(ros, np.array([0.4, -0.2, 0.9]), K, {0: 0.5, 1: 0.3, 2: 0.2})
    assert np.allclose(mix.sum(1), K - (0.3 * 1 + 0.2 * 2))           # E[keepers on the roster]


def test_the_probabilities_are_exact_against_brute_force():
    ros = _synthetic(n_rosters=1)
    x = ros.X[0, :8]
    small = M.Rosters([x], [np.zeros(8, bool)], [3])
    b = np.array([0.5, 0.1, -0.4])
    w = np.exp(x @ b)
    num = np.zeros(8)
    for S in itertools.combinations(range(8), 3):
        num[list(S)] += np.prod(w[list(S)])
    assert np.allclose(M.inclusion(small, b)[0], num / sum(np.prod(w[list(S)]) for S in
                                                            itertools.combinations(range(8), 3)))


def test_the_gradient_and_hessian_are_the_likelihoods():
    ros = _synthetic()
    b = np.array([0.3, 0.1, -0.2])
    g, H = M._grad_hess(ros, b)
    eps = 1e-5
    num_g = [(M.loglik(ros, b + eps * e).sum() - M.loglik(ros, b - eps * e).sum()) / (2 * eps) for e in np.eye(3)]
    num_H = [(M._grad_hess(ros, b + eps * e)[0] - M._grad_hess(ros, b - eps * e)[0]) / (2 * eps) for e in np.eye(3)]
    assert np.allclose(g, num_g, atol=1e-5) and np.allclose(H, num_H, atol=1e-4)


def test_the_prior_keeps_a_never_seen_event_rare_not_impossible():
    ros = _synthetic()
    ros.X[:, :, 2] = 0.0
    for r in range(len(ros.K)):                       # feature 3 on, never chosen: quasi-separation
        off = np.flatnonzero(ros.mask[r] & ~ros.chosen[r])[:2]
        ros.X[r, off, 2] = 1.0
    try:                                              # plain ML runs off (or fails outright)
        assert M.fit(ros, prior_scale=None)["beta"][2] < -10
    except M.FitError:
        pass
    f = M.fit(ros)
    assert -10 < f["beta"][2] < 0


# 2 -- leave one season out never lets the held-out season into its fit
def test_leave_one_out_never_fits_on_the_held_out_season(monkeypatch):
    snaps = F.dataset()
    seen = []
    real = M.fit

    def spy(ros, *a, **k):
        seen.append({lab[0] for lab in ros.labels})
        return real(ros, *a, **k)
    monkeypatch.setattr(M, "fit", spy)
    res = F.loso(snaps, F.SPECS["age linear"], "end", M.load_params()["level_prior"])
    assert list(res) == list(kh.DECISIONS) and len(seen) == len(kh.DECISIONS)
    for held, decisions in zip(kh.DECISIONS, seen):
        assert held not in decisions and decisions == set(kh.DECISIONS) - {held}


# 3 -- point in time: a week-2 prediction reads nothing after week 2
def test_week_2_features_read_nothing_after_week_2():
    inputs = kh.Inputs.load(ROOT)
    ages = kh.load_ages(kh.age_seasons(), ROOT)
    season = kh.prev_season("2025-26")
    day = kh.as_of_point(inputs.log[season], season, "week2")[1]
    cut = kh.Inputs(log={**inputs.log, season: [r for r in inputs.log[season] if r["date"] <= day]},
                    picks=inputs.picks, trades=inputs.trades)
    a = kh.snapshot(inputs, "2025-26", "week2", ages, check=False)
    b = kh.snapshot(cut, "2025-26", "week2", ages, check=False)
    assert [asdict(c) for c in a.candidates] == [asdict(c) for c in b.candidates]
    feats = F.SPECS["age linear"]
    lp = M.load_params()["level_prior"]
    assert np.array_equal(M.design(a.candidates, feats, level_prior=lp),
                          M.design(b.candidates, feats, level_prior=lp))


# 4 -- the shrinkage: 13 against last season, 4.7 against the league mean
def test_the_shrinkage_uses_the_measured_constants_and_returns_the_prior_at_zero_games():
    lvl, prior, k0, kind = kh.shrunk_level(50.0, 13, 30.0, 40, 35.0)
    assert (prior, k0, kind) == (30.0, 13.0, "last season") and lvl == pytest.approx(0.5 * 50 + 0.5 * 30)
    lvl, prior, k0, kind = kh.shrunk_level(50.0, 5, 30.0, 9, 35.0)        # 9 games last season: too few
    assert (prior, k0, kind) == (35.0, 4.7, "league mean")
    assert lvl == pytest.approx(5 / 9.7 * 50 + 4.7 / 9.7 * 35)
    assert kh.shrunk_level(None, 0, 30.0, 40, 35.0)[0] == 30.0
    assert kh.shrunk_level(None, 0, None, None, 35.0)[0] == 35.0
    assert (kh.K0_PRIOR_SEASON, kh.K0_LEAGUE_MEAN, kh.PRIOR_MIN_GAMES) == (13.0, 4.7, 10)


# 5 -- the fit is deterministic; the same data gives the same parameters file
def test_refitting_gives_the_same_parameters_file(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for out in (a, b):
        F.main(["--priors", "P1", "P3", "--no-live", "--params", str(out), "--fit-date", "2026-10-29",
                "--baseline", str(tmp_path / "none.json")])
    assert a.read_bytes() == b.read_bytes()
    params = M.load_params(a)
    assert params["level_prior"]["spec"] == "P3" and params["level_prior"]["k0_league_mean"] == 4.7
    assert params["level_prior"]["k0_prior"] == 10.0 and "measured" in params["level_prior"]["k0_prior_source"]
    assert params["fitted_on"] == list(kh.DECISIONS) and len(params["dataset_sha256"]) == 64
    for p in M.POINTS:
        assert set(params["points"][p]["se"]) == set(params["features"])


def test_the_committed_parameters_file_loads_and_predicts():
    params = M.load_params()
    assert params["specification"] == "age linear" and params["level_prior"]["spec"] == "P3"
    snaps = F.dataset()
    by = snaps[("2026-27", "end")].by_manager()
    out = M.predict(by, "end", 6, params)
    for m, ps in out.items():
        assert sum(q for _, q in ps) == pytest.approx(6.0)


# 6 -- predict raises on a missing or malformed parameters file
def test_predict_refuses_a_missing_or_malformed_parameters_file(tmp_path):
    with pytest.raises(M.ParamsError, match="missing"):
        M.load_params(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(M.ParamsError, match="not valid JSON"):
        M.load_params(bad)
    good = M.load_params()
    for breaks in ({"version": 2}, {"points": {}}, {"level_prior": None},
                   {"level_prior": {**good["level_prior"], "k0_prior": None}},
                   {"level_prior": {**good["level_prior"], "spec": "P9"}},
                   {"points": {**good["points"], "end": {**good["points"]["end"], "coef": {"kept": 1.0}}}},
                   {"points": {**good["points"], "mid": {**good["points"]["mid"],
                                                         "coef": {**good["points"]["mid"]["coef"], "age": "x"}}}}):
        bad.write_text(json.dumps({**good, **breaks}), encoding="utf-8")
        with pytest.raises(M.ParamsError):
            M.load_params(bad)
    with pytest.raises(M.ParamsError):
        M.predict({"Nick": []}, "end", 6, params_path=tmp_path / "nope.json")


# 7 -- 2021-22: nobody was kept the season before
def test_in_the_2021_22_decision_no_candidate_was_kept_the_season_before():
    snaps = F.dataset()
    for p in M.POINTS:
        cands = snaps[("2021-22", p)].candidates
        assert cands and not any(c.kept for c in cands)
        assert all(r[0] == 0.0 for r in M.design(cands, ["kept"]))
        assert all(c.draft_rank == c.draft_pick for c in cands if c.draft_rank)   # 2020-21: rank = pick
    later = snaps[("2022-23", "end")].candidates
    assert all(c.draft_rank == 24 + c.draft_pick for c in later if c.draft_rank)


# ---------------------------------------------------------------------------
# step B2: the level's prior over more than one season
# ---------------------------------------------------------------------------
LINES = [("2025-26", 36, 40.9), ("2024-25", 67, 48.1), ("2023-24", 72, 49.1)]


def test_the_prior_is_games_weighted_over_exactly_the_stated_seasons():
    assert M.prior_from_lines("2026-27", LINES, "P1") == (40.9, [LINES[0]])
    p2, used = M.prior_from_lines("2026-27", LINES, "P2")
    assert used == LINES[:2] and p2 == pytest.approx((36 * 40.9 + 67 * 48.1) / 103)
    p3, used = M.prior_from_lines("2026-27", LINES, "P3")
    assert used == LINES and p3 == pytest.approx((36 * 40.9 + 67 * 48.1 + 72 * 49.1) / 175)
    p3r, _ = M.prior_from_lines("2026-27", LINES, "P3r")
    assert p3r == pytest.approx((3 * 36 * 40.9 + 2 * 67 * 48.1 + 72 * 49.1) / (108 + 134 + 72))
    # the window is counted in calendar seasons: a missed season still uses up a place
    gap = [("2024-25", 67, 48.1), ("2023-24", 72, 49.1)]
    assert M.prior_from_lines("2026-27", gap, "P1") == (None, [])
    assert M.prior_from_lines("2026-27", gap, "P2") == (48.1, [gap[0]])
    # P1 keeps step B's 10-game floor; the games-weighted priors take any appearances
    thin = [("2025-26", 4, 30.0)]
    assert M.prior_from_lines("2026-27", thin, "P1")[0] is None
    assert M.prior_from_lines("2026-27", thin, "P3")[0] == 30.0
    with pytest.raises(ValueError, match="not before"):
        M.prior_from_lines("2025-26", LINES, "P3")              # only seasons before the as-of season
    with pytest.raises(M.PriorError):
        M.prior_from_lines("2026-27", LINES, "P4")


def test_previous_lines_are_whole_seasons_before_the_as_of_season():
    inputs = kh.Inputs.load(ROOT)
    lines = kh.previous_lines(inputs, "2026-27")("Domantas Sabonis")
    assert [s for s, _, _ in lines] == ["2025-26", "2024-25", "2023-24"]
    assert lines[0][1] == 19 and lines[0][2] == pytest.approx(33.07, abs=0.01)
    assert all(s < "2026-27" for s, _, _ in lines)
    snaps = F.dataset()
    for (d, p), snap in snaps.items():
        for c in snap.candidates[:20]:
            assert all(s < c.season for s, _, _ in c.prev_lines) and len(c.prev_lines) <= kh.PREV_SEASONS


def _cand(prev, games=0, fppg=None, league_mean=33.0, season="2026-27"):
    return kh.Candidate(decision="2027-28", season=season, point="week2", as_of="x", manager="Nick", player="X",
                        kept_next=False, kept=False, draft_round=None, undrafted=True, acquired="pickup",
                        stint_start="x", games=games, fppg=fppg, fppg_rank=1, team_games=games,
                        availability=None, days_rostered=1, first_day="x", prev_games=None, prev_fppg=None,
                        age=25, prev_lines=prev, league_mean=league_mean)


def test_no_previous_season_takes_the_league_mean_and_its_own_k0():
    lp = {"spec": "P3", "k0_prior": 10.0, "k0_league_mean": 4.7}
    lvl, prior, k0, kind, used = M.level_of(_cand([], games=5, fppg=40.0), lp)
    assert (prior, k0, kind, used) == (33.0, 4.7, "league mean", [])
    assert lvl == pytest.approx(5 / 9.7 * 40 + 4.7 / 9.7 * 33)
    lvl, prior, k0, kind, used = M.level_of(_cand(LINES, games=10, fppg=50.0), lp)
    assert k0 == 10.0 and kind == "P3" and lvl == pytest.approx(0.5 * 50 + 0.5 * prior)
    assert M.level_of(_cand(LINES), lp)[0] == pytest.approx(prior)          # zero games: the prior


def test_each_specs_k0_comes_from_the_parameters_and_a_missing_one_raises():
    params = M.load_params()
    lp = M.level_config(params)
    assert lp["k0_prior"] == 10.0 and lp["spec"] == "P3" and lp["k0_league_mean"] == 4.7
    for broken in ({}, {"level_prior": {"spec": "P3", "k0_league_mean": 4.7}},
                   {"level_prior": {"spec": "P3", "k0_prior": 0, "k0_league_mean": 4.7}}):
        with pytest.raises(M.PriorError):
            M.level_config(broken)
    with pytest.raises(M.PriorError):
        M.design([_cand(LINES)], ["level"])                                   # no prior given
    with pytest.raises(M.PriorError):
        M.design([_cand(LINES)], ["level"], level_prior={"spec": "P3"})
    # the same candidate under another k0 gives another level: nothing is hard-wired
    a = M.design([_cand(LINES, games=4, fppg=30.0)], ["level"], level_prior={**lp, "k0_prior": 10.0})
    b = M.design([_cand(LINES, games=4, fppg=30.0)], ["level"], level_prior={**lp, "k0_prior": 20.0})
    assert a[0, 0] != b[0, 0]


def test_k0_is_measured_the_way_13_was():
    inputs = kh.Inputs.load(ROOT)
    r = F.measure_k0(F.k0_pairs(inputs, "P1"))
    assert 10 <= r["k0"] <= 14 and r["player_seasons_at_k10"] > 400      # 13 measured 10-23 on 401
    pairs = {10: [(40.0, 40.0, 30.0)] * 5}                                 # first-k is right: k0 small
    assert F.measure_k0(pairs)["k0"] == 0.5
