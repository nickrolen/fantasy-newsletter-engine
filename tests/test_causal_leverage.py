"""The causal price of a point (HANDOFF_CAUSAL_LEVERAGE_2026-11-12 s.1).

The stakes file (schema 3) carries, per team and week, the leverage among
NEAR-TIE iterations of the season pass -- what winning the week causes -- as
well as the old all-iteration leverage, kept for reference only. A point is
priced in exactly one place, injured_drop.point_value (a win in
injured_drop.win_value_parts), and that place reads the causal leverage.
"""
import json
import re
from pathlib import Path

import numpy as np
import pytest

from modules import drop_inputs as di
from modules import injured_drop as idr
from modules import title_odds_run as tor

ROOT = Path(__file__).resolve().parents[1]
RULES = {"band": 25, "wider": [50, 75], "min_n": 300, "boot": 200}


def _confounded(n=60000, seed=3, effect=0.0):
    """A season-long strength s drives both the week's margin and the title;
    the week itself moves the title by `effect` (0: not at all). The
    all-iteration leverage sees the strength; the near-tie one should not."""
    rng = np.random.default_rng(seed)
    s = rng.standard_normal(n)
    margin = 150.0 * s + 200.0 * rng.standard_normal(n)
    won = (margin > 0).astype(float)
    p = 1.0 / (1.0 + np.exp(-(1.5 * s))) * 0.6 + effect * won
    title = rng.random(n) < np.clip(p, 0, 1)
    return won, title, margin


# =============================================================================
# the estimate
# =============================================================================

def test_the_near_tie_leverage_removes_season_long_strength():
    won, title, margin = _confounded(effect=0.0)
    old = tor.leverage(won, title)["leverage"]
    c = tor.causal_leverage(won, title, margin, rules=RULES, seed=[1])
    assert old > 0.15                                   # strong teams win weeks: not causal
    assert abs(c["leverage"]) < 3 * c["se"] + 0.01      # the week itself does nothing
    assert c["band"] == 25 and min(c["n_win"], c["n_loss"]) >= 300 and c["why"] is None


def test_the_near_tie_leverage_finds_a_real_effect():
    won, title, margin = _confounded(effect=0.15)
    c = tor.causal_leverage(won, title, margin, rules=RULES, seed=[1])
    assert c["leverage"] == pytest.approx(0.15, abs=3 * c["se"] + 0.01)


def test_it_is_deterministic_bounded_and_draws_nothing_from_numpy_global_state():
    won, title, margin = _confounded()
    np.random.seed(7)
    before = np.random.random()
    np.random.seed(7)
    a = tor.causal_leverage(won, title, margin, rules=RULES, seed=[11, 0, 5, 0])
    assert np.random.random() == before                 # the global stream is untouched
    b = tor.causal_leverage(won, title, margin, rules=RULES, seed=[11, 0, 5, 0])
    assert a == b and -1.0 <= a["leverage"] <= 1.0 and a["se"] > 0


def test_too_few_near_ties_widens_the_band_and_says_so():
    won, title, margin = _confounded(n=6000)        # ~240 a side within 25 points (margin SD 250)
    c = tor.causal_leverage(won, title, margin, rules=RULES, seed=[1])
    assert c["band"] in (50, 75) and "widened to" in c["why"] and "fewer than 300" in c["why"]
    assert min(c["n_win"], c["n_loss"]) >= 300


def test_too_few_even_at_the_widest_band_is_null_never_the_old_leverage():
    """The rule (s.1): never a silent fallback to the all-iteration leverage."""
    won, title, margin = _confounded(n=2000)
    old = tor.leverage(won, title)["leverage"]
    c = tor.causal_leverage(won, title, margin, rules={**RULES, "min_n": 5000}, seed=[1])
    assert old is not None
    assert c["leverage"] is None and c["band"] is None and c["se"] is None
    assert "no causal leverage" in c["why"] and "worth 0 per point" in c["why"]


def test_a_week_with_no_game_is_never_near():
    won = np.array([np.nan] * 1000 + [1.0] * 500 + [0.0] * 500)
    margin = np.array([np.nan] * 1000 + [5.0] * 500 + [-5.0] * 500)
    title = np.array([True] * 1000 + [True] * 500 + [False] * 500)
    c = tor.causal_leverage(won, title, margin, rules={**RULES, "min_n": 10}, seed=[1])
    assert (c["n_win"], c["n_loss"], c["leverage"]) == (500, 500, 1.0)


# =============================================================================
# the stakes file, schema 3
# =============================================================================

def _pass(n=40000, seed=5):
    """Two teams, one regular-season week and one bracket week, enough
    iterations for the near-tie estimate."""
    from types import SimpleNamespace
    won, title, margin = _confounded(n=n, seed=seed, effect=0.1)
    w16 = np.where(np.random.default_rng(seed + 1).random(n) < 0.5, 1.0, 0.0)
    m16 = np.where(w16 == 1, 1.0, -1.0) * np.abs(np.random.default_rng(seed + 2).normal(0, 200, n))
    champ = np.where((w16 == 1) ^ (np.random.default_rng(seed + 3).random(n) < 0.3), 0, 1)   # noisy
    reg_first = np.where(title, 0, 1)
    return SimpleNamespace(
        managers=["A", "B"], regular_weeks=(1, 15), through="playoffs", seed=2 ** 62 + 17,
        week_results={3: np.stack([won, 1 - won], axis=1), 16: np.stack([w16, 1 - w16], axis=1)},
        week_margins={3: np.stack([margin, -margin], axis=1), 16: np.stack([m16, -m16], axis=1)},
        reg_finish=np.stack([reg_first, 1 - reg_first], axis=1),
        playoff_finish=np.stack([champ, 1 - champ], axis=1), in_progress={}, data=None)


def test_every_row_has_the_causal_leverage_its_noise_and_the_old_one_renamed():
    st = tor.stakes(_pass(), rules=RULES)
    for team in ("A", "B"):
        for race, pre in (("regular_season", "rs_leverage"), ("playoffs", "playoff_leverage")):
            for row in st[team][race].values():
                assert pre not in row                           # no unqualified name in schema 3
                lev, old = row[pre + "_causal"], row[pre + "_all"]
                assert lev is not None and -1.0 <= lev <= 1.0 and -1.0 <= old <= 1.0
                assert row["causal_band"] == 25 and row["causal_se"] > 0
                assert min(row["causal_n_win"], row["causal_n_loss"]) >= RULES["min_n"]
    a3 = st["A"]["regular_season"]["3"]
    assert a3["rs_leverage_all"] > a3["rs_leverage_causal"] + 3 * a3["causal_se"]   # strength removed
    assert st == tor.stakes(_pass(), rules=RULES)                                    # deterministic


def test_the_schema_is_3_and_the_rules_come_from_config_every_key_required(monkeypatch):
    assert tor.STAKES_SCHEMA == 3
    rules = tor.near_tie_rules()
    assert rules == {"band": 25, "wider": [50, 75], "min_n": 300, "boot": 200}
    from modules import data_loader as dl
    real = dl.league_rule
    for key in ("near_tie_band", "near_tie_wider", "near_tie_min", "causal_bootstrap"):
        def missing(section, k, *a, _key=key, **kw):
            if section == "stakes" and k == _key:
                raise dl.UnspecifiedRule(f"stakes.{k}")
            return real(section, k, *a, **kw)
        monkeypatch.setattr(dl, "league_rule", missing)
        with pytest.raises(dl.UnspecifiedRule):
            tor.near_tie_rules()
        monkeypatch.setattr(dl, "league_rule", real)


def test_the_config_names_how_the_band_was_chosen():
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))["stakes"]
    for k in ("near_tie_band", "near_tie_wider", "near_tie_min", "causal_bootstrap"):
        assert cfg.get(f"_{k}"), k
    assert "development team-weeks" in cfg["_near_tie_band"] and "{25, 50, 75}" in cfg["_near_tie_band"]


# =============================================================================
# the reader and the price
# =============================================================================

def _blob(lev_causal=0.1, lev_all=0.9):
    rows = lambda pre, weeks: {str(w): {f"{pre}_causal": lev_causal, f"{pre}_all": lev_all,
                                        "causal_band": 25, "causal_n_win": 900, "causal_n_loss": 900,
                                        "causal_se": 0.01, "causal_why": None, "margin_mean": 30.0,
                                        "margin_sd": 220.0, "n_win": 1, "n_loss": 1, "n_tie": 0}
                                 for w in weeks}
    return {"schema": 3, "season": "2026-27", "week": 4, "as_of": "x", "run_id": "r", "kind": "nightly",
            "teams": {"Nick": {"rs_title": 0.3, "champion": 0.4,
                               "regular_season": rows("rs_leverage", range(5, 16)),
                               "playoffs": rows("playoff_leverage", range(16, 22))}}}


def test_point_value_prices_with_the_causal_leverage_never_the_old_one():
    cfg = idr.from_rules()
    st = di.team_stakes(_blob(), "Nick", 5, last_regular=15, bracket=list(range(16, 22)))
    for w in (5, 12, 18):
        ws = st.weeks[w]
        weight = cfg.rs_weight if w <= 15 else cfg.playoff_weight
        assert idr.point_value(ws, cfg) == pytest.approx(weight * 0.1 * ws.density())
        assert sum(idr.win_value_parts(ws, cfg)) == pytest.approx(weight * 0.1)
        assert sum(idr.point_value_parts(ws, cfg)) == idr.point_value(ws, cfg)


def test_a_null_causal_leverage_is_worth_nothing_per_point():
    b = _blob(lev_causal=None)
    b["teams"]["Nick"]["regular_season"]["5"]["causal_why"] = "fewer than 300 ... no causal leverage"
    ws = di.team_stakes(b, "Nick", 5, last_regular=15, bracket=list(range(16, 22))).weeks[5]
    assert idr.point_value(ws, idr.from_rules()) == 0.0


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("rs_leverage_causal"),                 # no causal key: never the old one instead
    lambda r: r.update(rs_leverage_causal=1.7),            # not a difference of probabilities
])
def test_a_row_without_a_usable_causal_leverage_raises(mutate):
    b = _blob()
    mutate(b["teams"]["Nick"]["regular_season"]["5"])
    with pytest.raises(di.StakesFileError):
        di.team_stakes(b, "Nick", 5, last_regular=15, bracket=list(range(16, 22)))


def test_point_value_is_the_only_place_a_point_or_a_win_is_priced():
    """Source pin (s.1): outside injured_drop (which prices), drop_inputs (which
    maps the file) and title_odds_run (which writes it), no module reads a
    leverage or a margin density, or defines a price of its own."""
    allowed = {"injured_drop.py", "drop_inputs.py", "title_odds_run.py"}
    pat = re.compile(r"rs_leverage|playoff_leverage|\.density\(|def point_value|def win_value")
    hits = {p.name for p in (ROOT / "modules").glob("*.py")
            if pat.search(p.read_text(encoding="utf-8")) and p.name not in allowed}
    assert hits == set(), hits
    src = (ROOT / "modules" / "advice_v2.py").read_text(encoding="utf-8")
    assert "injured_drop.win_value_parts(" in src and "injured_drop.point_value_parts(" in src
    # the old leverage is written for reference and read by nothing that prices
    for p in (ROOT / "modules").glob("*.py"):
        if p.name != "title_odds_run.py":
            assert "_leverage_all" not in p.read_text(encoding="utf-8"), p.name
    assert '"_causal"' in (ROOT / "modules" / "drop_inputs.py").read_text(encoding="utf-8") or \
        "_leverage_causal" in (ROOT / "modules" / "drop_inputs.py").read_text(encoding="utf-8")


def test_the_replay_prices_with_the_same_point_value():
    """V1's replay (modules/advice_replay) builds TeamStakes from its light
    pass, whose weeks are independent draws (its all-iteration leverage is
    causal there), and prices through advice_v2 -> injured_drop like the live
    path: it defines no price of its own."""
    src = (ROOT / "modules" / "advice_replay.py").read_text(encoding="utf-8")
    assert "injured_drop.WeekStake(" in src and "def point_value" not in src and ".density(" not in src
