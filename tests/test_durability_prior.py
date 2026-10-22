"""The durability prior (HANDOFF_DURABILITY_PRIOR_2026-10-22).

PLAYERLIST's player_proj_GP column changes MEANING when the season starts:
projected games of 82 with a haircut on everyone becomes games of those
remaining, marked down only for a known absence. The baseline hazard reads
(82 - gp) / 82, so taking it live in season drops the rate from ~16% a game
to ~1.5%, the injury model switches itself off, and the level bias comes
back. Measured 2026-10-22: stored snapshots sd 4.9, 31% of players within one
game of the median; a fresh fetch sd 2.74, 96% within one game.

Test 1 is the point of the change: the reality check holds across a refresh.
"""
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules import absence
from modules import marginal_value as mv
from modules import simulator_betting as sb
from modules.data_loader import (DURABILITY_PRIOR, FLAT_GP_SHARE_MAX, DurabilityPrior,
                                 DurabilityPriorError, FantasyData, MANAGERS,
                                 gp_column_is_flat, gp_dispersion, load_durability_prior)
from modules.projections import PlayerProjection, TeamProjections

ROOT = Path(__file__).parent.parent
SEED = 20262027
P = absence.baseline_params()
MON = date(2026, 10, 26)
PRESEASON_GP = [82, 78, 75, 73, 70, 69, 68, 66, 62, 55]      # a haircut, spread
INSEASON_GP = [78] * 9 + [60]                                # games remaining


# =============================================================================
# the shape of a GP column
# =============================================================================

def test_dispersion_tells_the_two_meanings_apart():
    pre = gp_dispersion(PRESEASON_GP * 18)
    post = gp_dispersion(INSEASON_GP * 18)
    assert pre["share"] < FLAT_GP_SHARE_MAX < post["share"]
    assert not gp_column_is_flat(PRESEASON_GP * 18)[0]
    assert gp_column_is_flat(INSEASON_GP * 18)[0]
    assert gp_dispersion([])["share"] is None


def test_every_stored_snapshot_is_pre_season_shaped_and_the_limit_sits_between():
    """3: the guard passes all three stored snapshots. Their measured share is
    0.31 and a fresh in-season fetch is 0.96, so 0.80 is not a near miss."""
    shares = {}
    for path in sorted((ROOT / "config" / "snapshots").glob("PLAYERLIST_*.xlsx")):
        flat, shape = gp_column_is_flat(pd.read_excel(path)["player_proj_GP"])
        shares[path.name] = round(shape["share"], 3)
        assert not flat, (path.name, shape)
    assert len(shares) >= 3, shares
    assert max(shares.values()) < 0.5, shares
    assert FLAT_GP_SHARE_MAX == DURABILITY_PRIOR["flat_gp_share_max"] == 0.80


# =============================================================================
# 1 -- the reality check survives a refreshed PLAYERLIST
# =============================================================================

@pytest.fixture(scope="module")
def live():
    if not (ROOT / "data" / "PLAYERLIST.xlsx").is_file():
        pytest.skip("no PLAYERLIST")
    from modules.data_loader import load_all_data
    from modules.projections import load_all_team_projections
    data = load_all_data()
    return data, load_all_team_projections(data)


def _refreshed(team_projections, gp=77.7):
    """The same rosters with an IN-SEASON GP column: games remaining, flat."""
    import copy
    out = {}
    rng = np.random.default_rng(0)
    for m, t in team_projections.items():
        t2 = copy.copy(t)
        t2.players = {}
        for n, p in t.players.items():
            q = copy.copy(p)
            q.projected_gp = float(np.clip(rng.normal(gp, 2.74), 60, 82))
            t2.players[n] = q
        out[m] = t2
    return out


def _season(data, teams, n=400):
    draws = sb.KeyedDraws(SEED, n)
    anchor = sb.hazard_anchor(data)
    rates, G = [], []
    base = sb.baseline_blocks(data, teams, draws, anchor, MANAGERS)
    rates = [base[n_].rate for m in MANAGERS for n_ in teams[m].players]
    for w in range(1, 16):
        r = sb.simulate_week_matrix(data, teams, sb.schedule_week(data, w), {}, draws,
                                    managers=MANAGERS, tag_anchor=anchor)
        G.append(np.stack([r[m]["games"] for m in MANAGERS]))
    return float(np.mean(rates)), float(np.stack(G, 2).mean())


def test_the_reality_check_holds_when_playerlist_is_refreshed(live):
    """Started games per manager-week stays in the historical 40.5-42.6 band
    with the live file AND with an in-season refreshed one -- and leaves it
    without the prior, which is the defect this change exists to stop."""
    data, teams = live
    kept = data.durability_prior
    try:
        rate_now, games_now = _season(data, teams)
        rate_fresh, games_fresh = _season(data, _refreshed(teams))
        assert 40.5 <= games_now <= 42.6, games_now
        assert 40.5 <= games_fresh <= 42.6, games_fresh
        assert rate_fresh == pytest.approx(rate_now, abs=1e-9)
        data.durability_prior = DurabilityPrior({}, "")       # the defect
        rate_off, games_off = _season(data, _refreshed(teams))
        assert rate_off < 0.07 < rate_now
        assert games_off > 42.6
    finally:
        data.durability_prior = kept


# =============================================================================
# 2 -- the durability input does not move when the file is refreshed
# =============================================================================

def _world(gp=70.0):
    weeks = [{"week": w, "start_date": (MON + timedelta(days=7 * (w - 1))).isoformat(),
              "end_date": (MON + timedelta(days=7 * w - 1)).isoformat()} for w in range(1, 6)]
    games = [{"date": (MON + timedelta(days=k)).isoformat() + "T00:00:00Z",
              "home": "BOS", "away": "MIA"} for k in range(35)]
    teams = {m: TeamProjections(m, {f"P{m}": PlayerProjection(
        player_name=f"P{m}", nba_team="BOS", positions=["PG"], projected_fppg=30.0,
        projected_gp=gp)}, weekly_std_dev=100.0) for m in MANAGERS}
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games}, current_week=0)
    return data, teams, weeks


def test_a_refresh_changes_scoring_and_not_durability():
    data, teams, weeks = _world(gp=70.0)
    data.durability_prior = DurabilityPrior({f"P{m}": 70.0 for m in MANAGERS}, "snapshot.xlsx")
    fresh = _refreshed(teams, gp=80.0)
    for m in MANAGERS:                      # a refresh also moves the scoring input
        fresh[m].players[f"P{m}"].projected_fppg = 33.0
    draws = sb.KeyedDraws(SEED, 500)
    a = sb.baseline_blocks(data, teams, draws, MON, MANAGERS)["PNick"]
    b = sb.baseline_blocks(data, fresh, sb.KeyedDraws(SEED, 500), MON, MANAGERS)["PNick"]
    assert a.miss_rate == b.miss_rate == pytest.approx((82 - 70) / 82)
    assert np.array_equal(a.season_mask(), b.season_mask())
    # and without a prior the same refresh moves it a long way
    data.durability_prior = None
    c = sb.baseline_blocks(data, fresh, sb.KeyedDraws(SEED, 500), MON, MANAGERS)["PNick"]
    assert c.miss_rate < a.miss_rate / 4


def test_the_prior_is_named_in_config_not_picked_at_runtime():
    assert DURABILITY_PRIOR["snapshot"].startswith("config/snapshots/")
    assert (ROOT / DURABILITY_PRIOR["snapshot"]).is_file()
    prior = load_durability_prior(ROOT)
    assert prior.source == DURABILITY_PRIOR["snapshot"]
    # the newest PRE-SEASON snapshot, and before week 1
    weeks = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))["weeks"]
    week1 = min(str(w["start_date"])[:10] for w in weeks)
    taken = DURABILITY_PRIOR["snapshot"].split("PLAYERLIST_")[1][:10]
    assert taken < week1, (taken, week1)
    others = sorted(p.name for p in (ROOT / "config" / "snapshots").glob("PLAYERLIST_*.xlsx")
                    if p.name.split("PLAYERLIST_")[1][:10] < week1)
    assert DURABILITY_PRIOR["snapshot"].endswith(others[-1])


def test_a_missing_or_in_season_prior_raises_rather_than_falling_back(tmp_path):
    with pytest.raises(DurabilityPriorError, match="not set"):
        load_durability_prior(ROOT, {})
    with pytest.raises(DurabilityPriorError, match="missing"):
        load_durability_prior(tmp_path, {"durability_prior": {"snapshot": "nope.xlsx"}})
    flat = tmp_path / "PLAYERLIST_2026-11-01.xlsx"
    pd.DataFrame({"player_name": [f"P{i}" for i in range(100)],
                  "player_proj_GP": [78] * 95 + [60, 61, 62, 63, 64]}).to_excel(flat, index=False)
    with pytest.raises(DurabilityPriorError, match="not a pre-season file"):
        load_durability_prior(tmp_path, {"durability_prior": {"snapshot": flat.name}})


# =============================================================================
# 3 -- the guard in check_playerlist
# =============================================================================

def test_check_playerlist_guards_the_gp_shape_and_the_configured_prior():
    src = (ROOT / "scripts" / "check_playerlist.py").read_text(encoding="utf-8")
    assert "gp_column_is_flat" in src and "in-season shaped before week 1" in src
    assert "points at the LIVE PLAYERLIST" in src
    assert "is in-season shaped" in src
    # the measured numbers are in the message, not just a threshold
    assert "within one game of the median" in src and "31%" in src
    r = subprocess.run([sys.executable, "scripts/check_playerlist.py"],
                       cwd=ROOT, capture_output=True, text=True, timeout=170)
    assert "GP shape:" in r.stdout and "pre-season shaped" in r.stdout
    assert "durability prior:" in r.stdout
    # the only failure on today's file is its age, not its shape
    for line in r.stdout.splitlines():
        if line.strip().startswith("- "):
            assert "fetched" in line, line


def test_integrity_fails_a_prior_that_is_missing_in_season_or_too_late(tmp_path, monkeypatch):
    import importlib.util
    import shutil
    spec = importlib.util.spec_from_file_location(
        "vpi", ROOT / "scripts" / "verify_project_integrity.py")
    vpi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vpi)
    # the real config passes
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert vpi._check_durability_prior(cfg, []) == []
    assert vpi._check_durability_prior({"durability_prior": {}}, []) != []
    assert vpi._check_durability_prior(
        {"durability_prior": {"snapshot": "config/snapshots/nope.xlsx"}}, []) != []
    # a prior taken after week 1 started, in a throwaway tree
    monkeypatch.setattr(vpi, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config" / "snapshots").mkdir(parents=True)
    shutil.copy2(ROOT / "config" / "SCHEDULE.json", tmp_path / "config" / "SCHEDULE.json")
    late = "config/snapshots/PLAYERLIST_2026-12-01.xlsx"
    shutil.copy2(ROOT / DURABILITY_PRIOR["snapshot"], tmp_path / late)
    problems = vpi._check_durability_prior({"durability_prior": {"snapshot": late}}, [])
    assert any("on or after week 1" in p for p in problems), problems
    # and an in-season shaped one, whatever its date
    flat = "config/snapshots/PLAYERLIST_2026-09-01.xlsx"
    pd.DataFrame({"player_name": [f"P{i}" for i in range(100)],
                  "player_proj_GP": [78] * 95 + [60, 61, 62, 63, 64]}).to_excel(
        tmp_path / flat, index=False)
    problems = vpi._check_durability_prior({"durability_prior": {"snapshot": flat}}, [])
    assert any("in-season shaped" in p for p in problems), problems


# =============================================================================
# 4 -- a player the snapshot has never heard of
# =============================================================================

def test_a_mid_season_pickup_gets_the_median_and_is_logged():
    prior = DurabilityPrior({"Known": 60.0, "Other": 70.0, "Third": 69.0}, "snapshot.xlsx")
    assert prior.gp_for("Known") == (60.0, False)
    gp, fell_back = prior.gp_for("Pickup")
    assert fell_back and gp == prior.median_gp == 69.0
    assert prior.record()["median_fallbacks"] == ["Pickup"]
    assert absence.durability_miss_rate(gp, P) > 0           # never zero misses
    # a name Yahoo respells still resolves, so it is not a spurious fallback
    p2 = DurabilityPrior({"Shai Gilgeous-Alexander": 73.0, "A": 70.0, "B": 69.0}, "s.xlsx")
    assert p2.gp_for("S. Gilgeous-Alexander") == (73.0, False)
    assert p2.record()["median_fallbacks"] == []


def test_the_fallback_reaches_the_engine_as_the_median_not_perfect_health():
    data, teams, weeks = _world(gp=82.0)     # the live file says "never misses"
    data.durability_prior = DurabilityPrior({"Someone": 70.0, "Else": 69.0, "Third": 68.0},
                                            "snapshot.xlsx")
    draws = sb.KeyedDraws(SEED, 800)
    blocks = sb.baseline_blocks(data, teams, draws, MON, MANAGERS)
    assert blocks["PNick"].miss_rate == pytest.approx((82 - 69) / 82)
    assert blocks["PNick"].season_mask().mean() > 0.1
    assert sorted(data.durability_prior.fallbacks) == [f"P{m}" for m in sorted(MANAGERS)]


# =============================================================================
# both engines, and the record
# =============================================================================

def test_marginal_value_takes_the_prior_from_the_context():
    data, teams, weeks = _world(gp=82.0)
    projs = {n: p for t in teams.values() for n, p in t.players.items()}
    rosters = {m: [f"P{m}"] for m in MANAGERS}
    prior = DurabilityPrior({"Someone": 70.0, "Else": 69.0, "Third": 68.0}, "snapshot.xlsx")
    ctx = mv.build_context(projs, rosters, data.nba_schedule, weeks, "regular_season", 0,
                           sims=400, seed=SEED, durability_prior=prior)
    assert ctx.durability_prior is prior
    assert mv.baseline(ctx, ctx.player("PNick")).miss_rate == pytest.approx((82 - 69) / 82)
    bare = mv.build_context(projs, rosters, data.nba_schedule, weeks, "regular_season", 0,
                            sims=400, seed=SEED)
    assert mv.baseline(bare, bare.player("PNick")).miss_rate == 0.0   # his own GP of 82
    runner = (ROOT / "modules" / "advice_runner.py").read_text(encoding="utf-8")
    assert "durability_prior=getattr(data, \"durability_prior\", None)" in runner


def test_the_build_records_which_snapshot_it_used():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert 'report["metadata"]["durability_prior"] = data.durability_prior.record()' in src
    assert '"durability_prior": (data.durability_prior.record()' in src   # the capture
    assert "Durability prior:" in src                                     # printed
    rec = load_durability_prior(ROOT).record()
    assert set(rec) == {"source", "players", "median_gp", "flat_gp_share", "note",
                        "median_fallbacks"}
    assert rec["source"] == DURABILITY_PRIOR["snapshot"] and rec["players"] > 100
