"""4c6: the MVP odds (modules/mvp_odds; claude/HANDOFF_4C6_MVP_ODDS_2026-11-19.md).

A. The core (pure): an insurmountable lead is ~100%; identical players get
   equal odds within noise, and exact ties split; the odds sum to 1; the
   future R moves only the simulated part.
B. The pass (test_season_sim's synthetic world): the title odds and every
   other array are BYTE-IDENTICAL with the tally on; the tally is
   deterministic with the seed; a manager's players' started points are his
   team score before the noise; banked + simulated PAR equals banked +
   expected started points above R within noise; the pass and the log must
   meet at one day.
C. The history line's new field (old lines still read), the newsletter's
   favourite, the display strings and the odds chart's model.
D. Real state (slow; skipped without it): today's odds at a small n, from
   the same pass as the title odds, with the title odds unchanged.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from modules import awards as A, mvp_odds as MO
from modules import season_sim as ss, simulator_betting as sb, simulator_playoff_odds as spo, title_odds_run as tor

ROOT = Path(__file__).resolve().parents[1]
CFG = {"awards": {"mvp_odds": {"future_replacement": "current", "contenders_n": 10, "store_min": 0.001,
                               "show_min": 0.01}}}


# =============================================================================
# A. the core
# =============================================================================

def test_an_insurmountable_lead_is_about_100_percent():
    rng = np.random.default_rng(1)
    n = 4000
    g = rng.integers(10, 15, n)                       # at most 14 games of at most 60 above R = 840
    sim = {"Chaser": (g * (20 + rng.uniform(0, 60, n)), g), "Leader": (np.zeros(n), np.zeros(n))}
    p = MO.odds({"Leader": 2000.0, "Chaser": 1000.0}, sim, 20.0, n)
    assert p == {"Leader": 1.0}


def test_identical_players_get_equal_odds_within_noise_and_exact_ties_split():
    rng = np.random.default_rng(2)
    n = 20000
    sim = {k: (rng.normal(500, 80, n), np.full(n, 10)) for k in ("A", "B", "C")}
    p = MO.odds({"A": 100.0, "B": 100.0, "C": 100.0}, sim, 20.0, n)
    se = (1 / 3 * 2 / 3 / n) ** 0.5
    for k in "ABC":
        assert abs(p[k] - 1 / 3) < 4 * se, p
    same = rng.normal(500, 80, n)
    q = MO.odds({"A": 100.0, "B": 100.0}, {"A": (same, np.full(n, 10)), "B": (same.copy(), np.full(n, 10))}, 20.0, n)
    assert q == {"A": 0.5, "B": 0.5}
    # two players who cannot play again, level at the top, split every simulation
    r = MO.odds({"X": 900.0, "Y": 900.0, "Z": 10.0}, {}, 20.0, 50)
    assert r == {"X": 0.5, "Y": 0.5}


def test_the_odds_sum_to_one_with_held_players_and_ties():
    rng = np.random.default_rng(3)
    n = 3000
    sim = {f"P{i}": (rng.normal(300 + 20 * i, 120, n), rng.integers(5, 12, n)) for i in range(8)}
    banked = {**{f"P{i}": float(rng.uniform(0, 300)) for i in range(8)}, "Held": 450.0, "Held2": 450.0, "Low": 5.0}
    p = MO.odds(banked, sim, 22.0, n)
    assert sum(p.values()) == pytest.approx(1.0, abs=1e-12)
    assert "Low" not in p                              # below the best held player: provably 0
    assert p.get("Held", 0) == p.get("Held2", 0)


def test_the_future_replacement_level_moves_only_the_simulated_part():
    res = {"R": {1: {"R": 30.0, "as_of": "2026-10-25"}, 2: {"R": 20.0, "as_of": "2026-11-01"}}}
    assert MO.future_R(res, "current")[0] == 20.0
    assert MO.future_R(res, "season_mean")[0] == 25.0
    n = 1000
    rng = np.random.default_rng(4)
    sim = {"A": (rng.normal(400, 50, n), np.full(n, 10)), "B": (rng.normal(300, 50, n), np.full(n, 4))}
    # B has fewer starts: a higher R costs A more, so B's odds rise with R
    lo, hi = MO.odds({"A": 0, "B": 0}, sim, 10.0, n), MO.odds({"A": 0, "B": 0}, sim, 30.0, n)
    assert hi.get("B", 0) > lo.get("B", 0)
    with pytest.raises(MO.MvpOddsError):
        MO.future_R({"R": {}}, "current")


def test_the_config_raises_on_a_missing_key():
    with pytest.raises(MO.MvpOddsError):
        MO.config({"awards": {}})
    bad = json.loads(json.dumps(CFG))
    del bad["awards"]["mvp_odds"]["show_min"]
    with pytest.raises(MO.MvpOddsError):
        MO.config(bad)
    assert MO.config()["future_replacement"] in MO.RULES        # the league's own block


def test_the_printed_odds():
    assert MO.pct(0.6123) == "61% to win"
    assert MO.pct(0.004) == "under 1% to win" and MO.pct(0.0) == "under 1% to win"
    assert MO.pct(0.996) == "over 99% to win" and MO.pct(1.0) == "over 99% to win"
    assert MO.pct(0.005) == "1% to win" and MO.short_pct(0.41) == "41%" and MO.short_pct(0.001) == "<1%"
    assert MO.pct(None) == ""


# =============================================================================
# B. the pass
# =============================================================================

@pytest.fixture(scope="module")
def world():
    import test_season_sim as TS
    mp = pytest.MonkeyPatch()
    mp.setattr(spo, "resolve_completed_week", lambda d, w: None)
    try:
        data, teams = TS._world()
        kw = dict(num_simulations=200, team_projections=teams, through="regular")
        out = {"off": ss.run_season(data, seed=11, **kw), "on": ss.run_season(data, seed=11, mvp=True, **kw),
               "again": ss.run_season(data, seed=11, mvp=True, **kw),
               "other": ss.run_season(data, seed=12, mvp=True, **kw)}
    finally:
        mp.undo()
    return data, teams, out


def _arrays(sp):
    keys = ("reg_finish", "reg_wins", "reg_losses", "reg_ties", "reg_points", "seeds", "playoff_finish",
            "semi_points", "final_points", "cup_points", "cup_seeds", "cup_finish", "cup_week_points", "dollars")
    out = b"".join(np.asarray(getattr(sp, k)).tobytes() for k in keys)
    for d in (sp.week_results, sp.week_margins):
        out += b"".join(np.asarray(d[w]).tobytes() for w in sorted(d))
    return out


def test_the_title_odds_are_byte_identical_with_the_tally_on(world):
    _d, _t, p = world
    off, on = p["off"], p["on"]
    assert off.mvp is None and on.mvp is not None
    assert _arrays(off) == _arrays(on)
    assert json.dumps(tor.readouts(off), sort_keys=True) == json.dumps(tor.readouts(on), sort_keys=True)
    assert json.dumps(tor.stakes(off), sort_keys=True, default=str) == json.dumps(tor.stakes(on), sort_keys=True,
                                                                                  default=str)


def test_the_title_odds_are_byte_identical_through_the_cup_too(monkeypatch):
    import test_season_sim as TS
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = TS._world(recorded_through=12)
    kw = dict(num_simulations=60, seed=5, team_projections=teams)
    off, on = ss.run_season(data, **kw), ss.run_season(data, mvp=True, **kw)
    assert _arrays(off) == _arrays(on)
    assert on.mvp["weeks"] == [13, 14, 15]               # the regular season only: no bracket or Cup week


def test_the_tally_is_deterministic_with_the_seed(world):
    _d, _t, p = world
    on, again, other = p["on"], p["again"], p["other"]
    assert sorted(on.mvp["players"]) == sorted(again.mvp["players"])
    for k, v in on.mvp["players"].items():
        assert np.array_equal(v[0], again.mvp["players"][k][0]) and np.array_equal(v[1], again.mvp["players"][k][1])
    assert any(not np.array_equal(v[0], other.mvp["players"][k][0]) for k, v in on.mvp["players"].items())


def test_a_managers_started_points_are_his_score_before_the_noise(world):
    """simulate_week_matrix's tally sums to the team score exactly when the
    team noise is zero (weekly_std_dev 0): every started point is someone's."""
    import copy
    data, teams, _p = world
    quiet = {m: copy.copy(t) for m, t in teams.items()}
    for t in quiet.values():
        t.weekly_std_dev = 0.0
    started = {}
    draws = sb.KeyedDraws(7, 150)
    res = sb.simulate_week_matrix(data, quiet, sb.schedule_week(data, 10), None, draws, started=started)
    for m in res:
        mine = [v for v in started.values() if v[2] == m]
        tot = np.sum([v[0] for v in mine], axis=0)
        assert np.allclose(np.maximum(0.0, tot), res[m]["score"], atol=1e-9)
        assert np.array_equal(np.sum([v[1] for v in mine], axis=0), res[m]["games"])
    # and the tally changes nothing it is passed beside
    res2 = sb.simulate_week_matrix(data, quiet, sb.schedule_week(data, 10), None, sb.KeyedDraws(7, 150))
    assert all(np.array_equal(res[m]["score"], res2[m]["score"]) for m in res)


def test_simulated_par_is_expected_starts_times_projection_less_R_within_noise(world):
    """banked + mean simulated PAR = banked + E[starts] x (mu - R): the
    started points' mean is the projection's mean per start (availability
    and the lineup never see the game draw or the projection error)."""
    from modules.projections import game_fp_params
    _d, teams, p = world
    on = p["on"]
    R = 20.0
    zs = []
    for k, (pts, g, m) in on.mvp["players"].items():
        mu = game_fp_params(teams[m].players[k])[0]
        g = g.astype(float)
        if g.mean() < 1:
            continue
        d = (pts - R * g) - g * (mu - R)
        zs.append(d.mean() / (d.std() / len(d) ** 0.5))
    assert len(zs) > 20
    assert max(abs(z) for z in zs) < 4.5 and abs(float(np.mean(zs))) < 1.0


def _res(data, players, through_week=8):
    from modules.week_state import week_entry
    end = str(week_entry(data, through_week)["end_date"])[:10]
    rows = [{"key": k, "label": k, "m": m, "value": v} for k, (v, m) in players.items()]
    rows.sort(key=lambda r: -r["value"])
    return {"season": "2026-27", "through": end, "week": through_week, "final": False,
            "R": {w: {"R": 20.0, "as_of": end} for w in range(1, through_week + 1)},
            "awards": {"mvp": {"rows": rows}}}


def test_compute_on_a_pass_names_every_contender_and_sums_to_one(world):
    data, _t, p = world
    on = p["on"]
    res = _res(data, {"Nick0": (300.0, "Nick"), "Retired Guy": (250.0, "Hayden")})
    blob = MO.compute(on, res, CFG)
    assert blob["sim_from"] == "2026-12-14" and blob["weeks"] == list(range(9, 16))
    assert sum(x["p"] for x in blob["contenders"]) + blob["everyone_else"] == pytest.approx(1.0, abs=1e-5)
    held = next(x for x in blob["contenders"] if x["key"] == "Retired Guy")
    assert held["rostered"] is False and held["sim_starts"] == 0
    assert blob["in_race"] == len(on.mvp["players"]) + 1
    blob["run_id"] = "t"
    MO.write(Path(_tmp := Path(__import__("tempfile").mkdtemp())), blob)
    assert MO.load(_tmp)["contenders"] == blob["contenders"]


def test_the_pass_and_the_log_must_meet_at_one_day(world):
    data, _t, p = world
    res = _res(data, {"Nick0": (300.0, "Nick")}, through_week=7)
    with pytest.raises(MO.MvpOddsError, match="must meet"):
        MO.compute(p["on"], res, CFG)
    with pytest.raises(MO.MvpOddsError, match="did not tally"):
        MO.compute(p["off"], _res(data, {"Nick0": (300.0, "Nick")}), CFG)


# =============================================================================
# C. the history line, the newsletter, the display
# =============================================================================

def _blob(through, ps, season="2026-27"):
    return {"schema": 1, "season": season, "through": through, "week": 5, "final": False, "num_simulations": 100,
            "replacement": {"rule": "current", "R": 20.0, "words": ""}, "run_id": "r",
            "contenders": [{"key": k, "label": k, "m": m, "p": v} for k, (v, m) in ps.items()]}


def test_the_history_line_gains_odds_only_on_the_weeks_last_day_and_old_lines_read(tmp_path):
    import awards_fixture as AF
    i = AF.inp()
    lines = A.pending(i, [])
    last = max(int(x["week"]) for x in lines)
    end = next(x["through"] for x in lines if int(x["week"]) == last)
    blob = _blob(end, {"Marcus Star": (0.7, "Marcus"), "Tyler Star": (0.3, "Tyler")})
    out = MO.attach(lines, blob)
    for a, b in zip(lines, out):
        if a["award"] != "mvp":
            assert a == b                               # other awards' lines untouched
        elif int(a["week"]) == last:
            assert b["odds"]["p"][0] == {"key": "Marcus Star", "label": "Marcus Star", "m": "Marcus", "p": 0.7}
            assert "odds_why" not in b
        else:
            assert b["odds"] is None and "not the week's last day" in b["odds_why"]   # no backfill
    assert all(x["odds"] is None for x in MO.attach(lines, None) if x["award"] == "mvp")
    assert all(x["odds"] is None for x in MO.attach(lines, _blob(end, {}, season="2025-26")) if x["award"] == "mvp")
    # old lines (no field) and new ones in one file: both read, the races and the facts take both
    A.append_history(tmp_path, lines[:6])
    A.append_history(tmp_path, [x for x in out[6:]])
    back = A.read_history(tmp_path)
    assert len(back) == len(lines) and "odds" not in back[0] and any(isinstance(x.get("odds"), dict) for x in back)
    f = A.newsletter_facts(back, AF.SEASON, last)["mvp"]
    assert f["favourite"] == "Marcus Star" and f["favourite_odds"] == 0.7 and f["favourite_odds_text"] == "70%"
    g = A.newsletter_facts(back, AF.SEASON, 1)["mvp"]
    assert g["favourite"] is None and g["favourite_why"]


def test_the_mvp_rows_print_the_odds_with_their_day_and_say_why_when_there_are_none():
    import awards_fixture as AF
    i = AF.inp()
    res = A.compute(i, AF.LAST)
    rows = res["awards"]["mvp"]["rows"]
    blob = AF.odds_blob(res)
    r = A.races(res, [], i["cfg"], mvp_odds=blob)["awards"][0]
    assert [x["odds"] for x in r["rows"]] == [MO.pct(c["p"]) for c in blob["contenders"][:5]]
    assert r["odds"]["as_of"].startswith("as of ") and r["odds"]["info"] == MO.INFO and r["odds"]["error"] == ""
    assert "no earlier week has odds" in r["odds"]["history"] and r["odds"]["chart"] is None
    assert all(x["odds"] == "" for a in A.races(res, [], i["cfg"], mvp_odds=blob)["awards"][1:] for x in a["rows"])
    none = A.races(res, [], i["cfg"])["awards"][0]
    assert none["odds"]["error"].startswith("No MVP odds yet") and all(x["odds"] == "" for x in none["rows"])
    bad = A.races(res, [], i["cfg"], mvp_odds_error="ValueError: x")["awards"][0]
    assert "could not be read" in bad["odds"]["error"]
    # a stale blob: its day is printed, and a row it does not name gets no odds
    stale = dict(blob, through="2026-11-08", contenders=blob["contenders"][:2])
    s = A.races(res, [], i["cfg"], mvp_odds=stale)["awards"][0]
    assert "the awards are through" in s["odds"]["as_of"] and [x["odds"] for x in s["rows"]][2:] == ["", "", ""]
    # anyone else at 1% or more is named; everyone else is summed
    extra = dict(blob, contenders=blob["contenders"][:5] + [{"key": "Far Away", "label": "Far Away", "m": "Dana",
                                                             "p": 0.02}])
    e = A.races(res, [], i["cfg"], mvp_odds=extra)["awards"][0]["odds"]
    assert [o["label"] for o in e["others"]] == ["Far Away"] and e["field"].startswith("Everyone else: ")
    assert rows                                         # the fixture has an MVP race


def test_the_odds_chart_needs_two_weeks_with_odds():
    import awards_fixture as AF
    i = AF.inp()
    res = A.compute(i, AF.LAST)
    rec = AF.races(odds=True)
    mvp = rec["races"]["awards"][0]
    ch = mvp["odds"]["chart"]
    assert ch is not None and len(ch["weeks"]) == 2 and ch["ymin"] == 0 and ch["ymax"] == 100
    assert [t["t"] for t in ch["yticks"]] == ["0%", "25%", "50%", "75%", "100%"]
    assert len({s["end"] for s in ch["series"]}) == len(ch["series"])     # alike last names show first names
    one = [x for x in rec["pending"] if not (x["award"] == "mvp" and int(x["week"]) == int(ch["weeks"][0]))]
    assert A.odds_chart(A.races(res, [], i["cfg"])["awards"][0]["rows"], one, AF.SEASON) is None


def test_final_awards_show_no_odds():
    import awards_fixture as AF
    i = AF.inp()
    res = A.compute(i, AF.LAST)
    res = dict(res, final=True)
    r = A.races(res, [], i["cfg"], mvp_odds=AF.odds_blob(res))["awards"][0]
    assert r["odds"] is None and all(x["odds"] == "" for x in r["rows"])


def test_the_nightly_alone_tallies_and_a_failure_is_soft(tmp_path):
    """Only the nightly mode asks for the tally (pre-tip, refresh, poll and
    afternoon never do); _mvp_record never raises."""
    import inspect
    from modules import nightly
    src = inspect.getsource(nightly.Run.step_title_odds)
    assert 'mvp = self.mode == "nightly"' in src and '**({"mvp": True} if mvp else {})' in src
    run = nightly.Run.__new__(nightly.Run)
    run.base, run.ctx, run.run_id = tmp_path, {}, "t"
    rec = run._mvp_record(type("SP", (), {"mvp": None})())
    assert rec["error"] and run.ctx["mvp_lines"][0].startswith("MVP ODDS FAILED")
    assert not (tmp_path / MO.FILE).exists()


# =============================================================================
# D. real state
# =============================================================================

@pytest.mark.slow
def test_real_mvp_odds_past_awards_and_the_v2_preview():
    """Today's state, unstubbed, at a small n with the latest run's seed: the
    pass with the tally reproduces the pass without it byte for byte, the odds
    meet the awards' log at one day and sum to 1; the past awards build into
    a temp folder; the v2 preview's Awards print the odds and Past winners.
    Writes nothing in the repo. Skips without state."""
    import league_state
    from datetime import datetime
    from modules import keeper_history as kh, tag_records
    from modules.data_loader import load_all_data
    if not (ROOT / tor.LATEST_FILE).is_file() or not (ROOT / "output" / "tag_records.jsonl").is_file():
        pytest.skip("no title-odds run on this machine")
    league_state.skip_if_actuals_behind()
    lat = tor.load_latest(ROOT)
    row = next((r for r in tag_records.read(ROOT) if r["run_id"] == lat["run_id"]), None)
    if row is None:
        pytest.skip("the latest run's tag record is not on file")
    data = load_all_data(str(ROOT), current_week=None)
    data.plan_now = datetime.fromisoformat(lat["as_of"])
    kw = dict(seed=lat["seed"], sims=400, statuses=tag_records.as_tags(row), through="regular",
              tag_anchors=tor.line_anchors(ROOT))
    off, on = tor.run_pass(data, **kw), tor.run_pass(data, mvp=True, **kw)
    assert json.dumps(tor.readouts(off), sort_keys=True) == json.dumps(tor.readouts(on), sort_keys=True)
    inp = A.gather(ROOT, live=kh.live_inputs(ROOT, kh.Inputs.load(ROOT)))
    res = A.compute(inp, inp["days"][-1])
    if on.mvp["weeks"] and on.mvp.get("as_of") and on.mvp["as_of"] != (
            date.fromisoformat(res["through"]) + timedelta(days=1)).isoformat():
        pytest.skip("the log moved since the latest title-odds run")
    blob = MO.compute(on, res)
    assert sum(x["p"] for x in blob["contenders"]) + blob["everyone_else"] == pytest.approx(1.0, abs=1e-5)
    assert blob["contenders"][0]["p"] > 0 and blob["contenders"][0]["banked"] > 0
    blob["run_id"] = "test"
    # the past awards, built into a temp folder (never the repo's file)
    import tempfile
    from modules import awards_past as P, hub_state, team_pictures as tp
    from modules.hub_v2 import data as v2data, view, page
    tmp = Path(tempfile.mkdtemp())
    past = P.build(ROOT)
    assert P.load(tmp) is None and P.write(past, P.FILE, tmp).is_file() and P.load(tmp) == past
    # the v2 preview's Awards, with these odds (hub_state's preview hook; nothing written)
    po, ao = {}, {}
    pl = hub_state.build(ROOT, allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po,
                         awards_out=ao, mvp_odds_blob=blob)
    assert pl["v2_error"] is None and ao["error"] is None and ao["mvp_odds"] == blob["through"]
    v2data.attach_players(pl, po)
    mvp = pl["v2"]["league"]["awards"]["races"][0]
    assert mvp["key"] == "mvp" and all(r["odds"] for r in mvp["rows"]) and mvp["odds"]["error"] == ""
    h = page.render(view.build(pl, mode="preview", now=datetime.fromisoformat(pl["generated_at"]),
                               pictures=tp.data_uris(ROOT, pl["v2"]["team_order"])[0]))
    assert "% to win" in h and "Odds to win" in h and "What the MVP odds mean" in h
    if (ROOT / P.FILE).is_file():
        assert "Past winners" in h and "Best MVP season" in h
