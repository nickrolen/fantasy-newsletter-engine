"""The baseline hazard: untagged absences (HANDOFF_BASELINE_INJURY_2026-10-21).

Before this, nobody in the simulator ever missed a game they were not tagged
for: 48.6 started games a manager-week against 42.6 in reality, +24% points,
weekly dispersion two-thirds of reality's, and a subsidy to the least durable
roster. The Phase 1 tests checked the engine against itself; test 1 here
checks it against nine seasons of what actually happened, and checks that it
FAILS with the hazard switched off.
"""
import ast
import inspect
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from modules import absence
from modules import marginal_value as mv
from modules import miss_rate as mr
from modules import simulator_betting as sb
from modules.data_loader import FantasyData, MANAGERS
from modules.projections import PlayerProjection, TeamProjections

ROOT = Path(__file__).parent.parent
HIST = ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
P = absence.baseline_params()
SEED = 20262027


# =============================================================================
# Live data: the reality check (6.1) and the durability test (6.5)
# =============================================================================

@pytest.fixture(scope="module")
def live():
    if not HIST.exists():
        pytest.skip("no HISTORICAL_PLAYERLOG")
    from modules.data_loader import load_all_data
    from modules.projections import load_all_team_projections
    data = load_all_data()
    return data, load_all_team_projections(data)


@pytest.fixture(scope="module")
def history_bands():
    """The section-5 bands, MEASURED from the log -- not typed in.

    games: [nine-season mean, last-two-season mean] started scoring games a
    manager-week. rel_cv: the range over seasons of the weekly CV of a
    manager's points RELATIVE TO THAT WEEK'S LEAGUE MEAN -- the dispersion
    that is the manager's own. The raw CV (0.151 nine seasons, 0.177 last
    two) also carries how uneven the season's WEEKS are (All-Star and
    holiday weeks): 0.114 of week-length CV in history against 0.072 in
    2026-27's weeks 1-15. That part is the calendar, not injuries, so it is
    taken out on both sides before comparing.
    """
    rows = json.loads(HIST.read_text(encoding="utf-8"))
    mw = {}
    for r in rows:
        if r["started"] and r["had_game"] and r["fantasy_points"] != 0:
            k = (r["season_key"], r["manager"], r["week"])
            g, p = mw.get(k, (0, 0.0))
            mw[k] = (g + 1, p + r["fantasy_points"])
    seasons = sorted({k[0] for k in mw})
    last2 = seasons[-2:]
    games = np.array([v[0] for v in mw.values()])
    games_last2 = np.array([v[0] for k, v in mw.items() if k[0] in last2])
    pts = np.array([v[1] for v in mw.values()])
    by_week = {}
    for (s, m, w), (g, p) in mw.items():
        by_week.setdefault((s, w), {})[m] = p
    per_season = {}
    for s in seasons:
        series = {}
        for (ss, w), ms in sorted(by_week.items()):
            if ss != s or len(ms) != 4:
                continue
            mean = sum(ms.values()) / 4
            for m, p in ms.items():
                series.setdefault(m, []).append(p / mean)
        cvs = [np.std(v, ddof=1) / np.mean(v) for v in series.values() if len(v) > 2]
        per_season[s] = float(np.mean(cvs))
    return {"games": (float(games.mean()), float(games_last2.mean())),
            "ppg": float(pts.sum() / games.sum()),
            "rel_cv": (min(per_season.values()), max(per_season.values())),
            # the hazard's own quantity: per-game miss rate, every rostered
            # team game, weeks 1-15 -- the range real seasons produced
            "miss": mr.band(rows, mr.HISTORY_WEEKS),
            "miss_pooled": mr.pooled(rows)[2],
            "per_day": mr.started_per_manager_day(rows)}


def _season(data, teams, n=500, hazard=True, monkeypatch=None):
    """([manager, n, week] scores, started games, the simulated per-game miss
    rate, manager-days) over weeks 1-15, no tags -- one set of draws for all."""
    if not hazard:
        monkeypatch.setattr(sb, "baseline_blocks", lambda *a, **k: {})
    draws = sb.KeyedDraws(SEED, n)
    anchor = date.fromisoformat(sb.schedule_week(data, 1)["start_date"])
    S, G, days = [], [], 0
    for w in range(1, 16):
        wd = sb.schedule_week(data, w)
        r = sb.simulate_week_matrix(data, teams, wd, {}, draws,
                                    managers=MANAGERS, tag_anchor=anchor)
        S.append(np.stack([r[m]["score"] for m in MANAGERS]))
        G.append(np.stack([r[m]["games"] for m in MANAGERS]))
        days += len(sb.get_dates_in_week(wd))
    miss = mr.simulated(data, teams, range(1, 16), {}, draws, anchor, MANAGERS)
    if not hazard:
        monkeypatch.undo()
    return np.stack(S, 2), np.stack(G, 2), miss, days


def _metrics(S, G, miss=None, days=None):
    rel = S / S.mean(axis=0, keepdims=True)
    out = {"games": float(G.mean()),
           "ppg": float(S.sum() / G.sum()),
           "raw_cv": float((S.std(axis=2, ddof=1) / S.mean(axis=2)).mean()),
           "rel_cv": float((rel.std(axis=2, ddof=1) / rel.mean(axis=2)).mean())}
    if miss is not None:
        out["miss"] = miss["rate"]
    if days:
        out["per_day"] = float(G.sum(axis=2).mean() / days)
    return out


@pytest.fixture(scope="module")
def seasons(live):
    data, teams = live
    on = _season(data, teams)
    mp = pytest.MonkeyPatch()
    off = _season(data, teams, hazard=False, monkeypatch=mp)
    return on, off


# 1 -- the reality check
#
# WHY STARTED GAMES IS NO LONGER A GATE (HANDOFF_HAZARD_CHECK_2026-10-27). It
# was: started scoring games per manager-week inside [nine-season mean,
# last-two-season mean]. 2026-27 runs FIVE bench slots, most of the history
# THREE (2025-26 switched midseason), and depth absorbs absences: a starter
# sits, a bench player fills the slot, the game is still started. Per
# manager-day, so week length drops out:
#
#     nine seasons                          5.566
#     last two                              5.761
#     best season ever (2023-24)            5.841
#     2026-27 week 1, actual                6.708
#     engine on 10-27 (42.83 a week)        6.12
#     engine with no hazard (48.6 a week)   6.94
#
# Reality sits 3.5% under the no-injury ceiling, so any upper edge that passes
# a correct engine also passes one where nobody is ever hurt -- the check
# below would stop biting. No threshold fixes that; widening the band to pass
# 42.83 is exactly the wrong repair. Started games is REPORTED (the next test
# prints it); the gate is the per-game MISS RATE, which depth cannot mask.
# Re-derive a started-games band from this season once there are four to six
# weeks of five-bench data.

def test_reality_dispersion_and_points_per_started_game_inside_the_historical_bands(
        seasons, history_bands):
    m = _metrics(*seasons[0])
    lo, hi = history_bands["rel_cv"]
    assert lo <= m["rel_cv"] <= hi, (m, history_bands)
    # points per started game is a roster-strength property (2026-27's
    # rosters project 39.2); it must not drift far from what starters score
    assert abs(m["ppg"] / history_bands["ppg"] - 1) < 0.04, (m, history_bands)


def test_started_games_is_reported_not_gated(seasons, history_bands):
    """Printed in every run (-s shows it; scripts/hazard_check.py prints it
    for a build). Asserted only to be a number, never to sit in a band."""
    on, off = _metrics(*seasons[0]), _metrics(*seasons[1])
    lines = mr.report_started_games(history_bands["per_day"], None, on["per_day"], off["per_day"])
    print("\n".join(lines))
    assert 0 < on["per_day"] < off["per_day"]
    assert "not a gate" in lines[0]


def test_reality_miss_rate_inside_the_range_real_seasons_produced(seasons, history_bands):
    """The hazard checked on what it models: the share of rostered team games
    a player misses, weeks 1-15, against the per-season range of the same
    quantity in nine seasons of the log (measured inside the test)."""
    m = _metrics(*seasons[0])
    lo, hi = history_bands["miss"]
    print(f"\nsimulated miss rate {m['miss']:.4f}; real seasons, weeks 1-15: "
          f"{lo:.4f}-{hi:.4f}; pooled, all weeks: {history_bands['miss_pooled']:.4f}")
    assert lo <= m["miss"] <= hi, (m["miss"], history_bands["miss"])


def test_reality_check_fails_with_nobody_ever_hurt(seasons, history_bands):
    """The check bites, at any bench depth: with the hazard off the only
    misses left are INJURY_OVERRIDES entries, far below any real season."""
    m = _metrics(*seasons[1])
    assert m["miss"] < history_bands["miss"][0] / 3, (m["miss"], history_bands["miss"])
    assert m["rel_cv"] < history_bands["rel_cv"][0]


# 5 -- durability is rewarded: the MECHANISM, on a frozen league
#
# This used to assert on the live rosters that the hazard pulls the managers'
# season totals closer together (spread on < spread off, and under 5%). That
# held for the week-1 rosters only because the less durable rosters were also
# the stronger ones; after the 10-26 roster churn it read 0.183 on against
# 0.144 off. An accident of composition written as an invariant. What the
# hazard must do does not depend on who is rostered: a roster loses the share
# of its points its players miss, so equal rosters that differ only in
# durability end the season apart, in that order, by that much.
# (SUITE_REPAIR_RESULT_2026-10-27 records the live numbers.)
DURABILITY_GP = {"Nick": 66.0, "Hayden": 78.0, "Benton": 72.0, "Garrett": 72.0}


def _durability_league(hazard, monkeypatch, n=2000, n_weeks=4):
    """{manager: mean points over weeks 2..n_weeks}: four identical
    three-guard rosters (BOS, every day, no bench) differing ONLY in
    projected GP."""
    data, teams, weeks = _week_world(n_weeks=n_weeks)
    for m, gp in DURABILITY_GP.items():
        for pp in teams[m].players.values():
            pp.projected_gp = gp
    if not hazard:
        monkeypatch.setattr(sb, "baseline_blocks", lambda *a, **k: {})
    anchor = date.fromisoformat(weeks[0]["start_date"])
    draws = sb.KeyedDraws(SEED, n)
    tot = {m: 0.0 for m in MANAGERS}
    for w in weeks[1:]:
        r = sb.simulate_week_matrix(data, teams, w, {}, draws, managers=MANAGERS, tag_anchor=anchor)
        for m in MANAGERS:
            tot[m] += float(r[m]["score"].mean())
    if not hazard:
        monkeypatch.undo()
    return tot


def test_durability_is_rewarded(monkeypatch):
    off = _durability_league(False, monkeypatch)
    on = _durability_league(True, monkeypatch)
    # without the hazard, durability is worth nothing: identical rosters
    assert max(off.values()) / min(off.values()) - 1 < 0.01, off
    # with it, each roster keeps the share of games its players play
    for m, gp in DURABILITY_GP.items():
        rate = absence.durability_miss_rate(gp, P)
        assert 1 - on[m] / off[m] == pytest.approx(rate, abs=0.015), (m, on, off)
    # so the durable roster gains on the fragile one, in order
    assert on["Hayden"] / on["Nick"] > off["Hayden"] / off["Nick"] + 0.10
    assert on["Hayden"] > on["Benton"] > on["Nick"]


# =============================================================================
# The model (synthetic)
# =============================================================================

def _season_dates(n_games, start=date(2026, 10, 20), every=2):
    return [start + timedelta(days=every * k) for k in range(n_games)]


def _blocks(gp, n_games=82, n=4000, anchor=None, player="X", seed=SEED):
    """Blocks for a player whose PRE-SEASON projected GP is `gp`."""
    dates = _season_dates(n_games)
    return absence.BaselineBlocks(seed, "2026-27", player, dates, anchor or dates[0],
                                  absence.durability_miss_rate(gp, P), n, P)


def test_parameters_live_in_config_and_missing_raises():
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    c = cfg["absence_baseline"]
    assert (P.short_share, P.short_mean, P.long_mean, P.games_per_team) == (
        c["short_share"], c["short_mean_games"], c["long_mean_games"], c["nba_games_per_team"])
    with pytest.raises(KeyError, match="absence_baseline"):
        absence.baseline_params({})
    src = inspect.getsource(absence)
    for v in ("0.75", "1.24", "9.5"):
        assert v not in src.split("class BaselineParams")[1], v


# 2 -- expected misses: team games - projected_gp
@pytest.mark.parametrize("gp", [82, 75, 70, 49, 20, 0])
def test_expected_misses_are_team_games_minus_projected_gp(gp):
    b = _blocks(gp)
    missed = b.season_mask().sum(axis=1)
    assert b.remaining == 82
    assert b.miss_rate == pytest.approx((82 - gp) / 82)
    assert missed.mean() == pytest.approx(82 - gp, abs=max(0.05, 4 * missed.std() / np.sqrt(len(missed))))


def test_the_window_counts_the_unscheduled_cup_games():
    """The file lists 80 of 82 team games; the 2 NBA Cup games are not
    scheduled yet and still count in the window the rate is applied over."""
    dates = _season_dates(80)
    anchor = dates[30]
    b = absence.BaselineBlocks(SEED, "2026-27", "X", dates, anchor,
                               absence.durability_miss_rate(40, P), 4000, P)
    assert b.remaining == 50 + 2
    assert b.rate == pytest.approx((82 - 40) / 82)
    rest = b.season_mask()[:, 30:].sum(axis=1)
    assert rest.mean() == pytest.approx(50 * (82 - 40) / 82, abs=0.5)


def test_a_mid_season_anchor_keeps_the_prior_s_rate():
    """The prior is a RATE out of 82, not a count against the games left: at
    the All-Star break a 69-GP player is still missing ~16% of his games, not
    zero (which is what (remaining - 69) / remaining would have given)."""
    dates = _season_dates(82)
    for anchor_i, remaining in ((0, 82), (42, 40), (72, 10)):
        b = absence.BaselineBlocks(SEED, "2026-27", "X", dates, dates[anchor_i],
                                   absence.durability_miss_rate(69, P), 4000, P)
        assert b.remaining == remaining
        assert b.rate == pytest.approx((82 - 69) / 82, abs=1e-12)
        window = b.season_mask()[:, anchor_i:].sum(axis=1)
        assert window.mean() == pytest.approx(remaining * 13 / 82, abs=0.6)


def test_marginal_value_no_longer_divides_by_the_roster_max():
    """3.2: rate came from projected_gp / max rostered projected_gp (~71).
    A player's availability now depends on his own projection only."""
    sched = [{"week": 1, "start_date": "2026-10-20", "end_date": "2026-10-26"}]
    games = {"games": [{"date": d.isoformat() + "T00:00:00Z", "home": "BOS", "away": "MIA"}
                       for d in _season_dates(80)]}
    def proj(n, gp):
        return PlayerProjection(player_name=n, nba_team="BOS", positions=["PG"], projected_fppg=30.0, projected_gp=gp)
    a = mv.build_context({"A": proj("A", 70.0), "B": proj("B", 76.0)}, {"Nick": ["A", "B"]}, games, sched,
                         "this_week", 0, sims=2000, seed=3)
    b = mv.build_context({"A": proj("A", 70.0), "B": proj("B", 40.0)}, {"Nick": ["A", "B"]}, games, sched,
                         "this_week", 0, sims=2000, seed=3)
    d = date(2026, 10, 22)
    assert np.array_equal(mv._draws(a, a.player("A"), d, 1), mv._draws(b, b.player("A"), d, 1))
    assert mv.baseline(a, a.player("A")).rate == pytest.approx(12 / 82)
    assert not hasattr(mv, "AVAILABILITY_CAP")


# 3 -- blocks, not coin flips
def test_absences_come_in_blocks_not_coin_flips():
    rate = 0.15
    b = _blocks(82 - 82 * rate, n=4000)
    mask = b.season_mask()
    runs = []
    for row in mask:
        k = 0
        for x in row:
            if x:
                k += 1
            elif k:
                runs.append(k)
                k = 0
    runs = np.array(runs)
    # independent per-game flips at p: P(run >= 2) = p, mean run 1/(1-p)
    assert (runs >= 2).mean() > 2 * rate
    assert runs.mean() > 2 * (1 / (1 - rate))
    # most missed games are in the long absences, as in the log (47% of
    # complete-run games are in runs <= 3; under coin flips it would be ~99%)
    in_long = runs[runs >= 4].sum() / runs.sum()
    assert in_long > 0.5
    # and the chain is stationary: every game is missed at the rate
    assert np.abs(mask.mean(axis=0) - rate).max() < 0.03


def test_the_chain_is_exactly_stationary_at_any_rate():
    u = np.random.default_rng(0).random((20000, P.games_per_team + 1))
    for rate in (0.03, 0.2, 0.5, 0.9):
        m = absence.baseline_mask(u, rate, 82, P)
        assert m.mean() == pytest.approx(rate, abs=0.01)
        assert m[:, 0].mean() == pytest.approx(rate, abs=0.015)


# 4 -- persistence within an iteration
def test_an_iterations_absences_persist_across_weeks():
    """The same season chain feeds every week, so a game missed at the end of
    one week makes the next week's first game far likelier missed."""
    b = _blocks(70)
    mask = b.season_mask()
    i = 41                                       # any boundary
    p_after_miss = mask[mask[:, i], i + 1].mean()
    assert p_after_miss > 3 * b.rate
    # and a week asked for on its own reads the same blocks as the season
    d = b.dates[i + 1]
    assert np.array_equal(b.missed(d), mask[:, i + 1])


def _week_world(n_weeks=11, team_gp=None, statuses=None):
    """One team (BOS) playing every day; weeks of seven days."""
    start = date(2026, 10, 19)
    weeks = [{"week": w, "start_date": (start + timedelta(days=7 * (w - 1))).isoformat(),
              "end_date": (start + timedelta(days=7 * w - 1)).isoformat()} for w in range(1, n_weeks + 1)]
    games = [{"date": (start + timedelta(days=k)).isoformat(), "home": "BOS", "away": "MIA"}
             for k in range(7 * n_weeks)]
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games}, current_week=0)
    ps = {f"P{j}": PlayerProjection(player_name=f"P{j}", nba_team="BOS", positions=["PG"],
                                    projected_fppg=30.0 - j, projected_gp=(team_gp or 70.0))
          for j in range(3)}
    teams = {m: TeamProjections(m, {k + m: PlayerProjection(player_name=k + m, nba_team="BOS",
                                                            positions=["PG"], projected_fppg=v.projected_fppg,
                                                            projected_gp=v.projected_gp)
                                    for k, v in ps.items()}, weekly_std_dev=100.0) for m in MANAGERS}
    return data, teams, weeks


def test_a_week_read_alone_equals_the_season_pass():
    data, teams, weeks = _week_world()
    anchor = date.fromisoformat(weeks[0]["start_date"])
    season = sb.KeyedDraws(SEED, 1000)
    for w in (3, 4):
        alone = sb.KeyedDraws(SEED, 1000)
        for d in sb.get_dates_in_week(weeks[w - 1]):
            a = sb.availability_on(data, teams, weeks[w - 1], {}, alone, "Nick", "P0Nick", d, anchor)
            s = sb.availability_on(data, teams, weeks[w - 1], {}, season, "Nick", "P0Nick", d, anchor)
            assert np.array_equal(a, s)


# 6 -- no double charge for a tagged player
def test_a_tagged_player_is_not_charged_twice():
    data, teams, weeks = _week_world()
    anchor = date.fromisoformat(weeks[0]["start_date"])
    draws = sb.KeyedDraws(SEED, 4000)
    statuses = {"P0Nick": "Q"}
    dates = [d for w in weeks for d in sb.get_dates_in_week(w)]
    out = np.stack([~sb.availability_on(data, teams, weeks[(d - anchor).days // 7], statuses, draws,
                                         "Nick", "P0Nick", d, anchor) for d in dates], axis=1)
    tag = sb.tag_blocks(data, teams, statuses, draws, anchor)["P0Nick"]
    base = sb.baseline_blocks(data, teams, draws, anchor, ["Nick"])["P0Nick"]
    # on the chain's games the tag alone decides
    for i, d in enumerate(tag.games):
        assert np.array_equal(out[:, dates.index(d)], tag.missed(d))
    # first game: Q's 40%, not 40% + 60% x rate
    assert out[:, 0].mean() == pytest.approx(0.40, abs=0.025)
    # the rule, in expectation: tag block + rate x the games it does not cover
    expected = absence.expected_missed("Q") + base.rate * (len(dates) - 3)
    double = absence.expected_missed("Q") + base.rate * len(dates)
    got = out.sum(axis=1).mean()
    assert got == pytest.approx(expected, abs=0.5)
    assert abs(got - double) > abs(got - expected) + 0.3


def test_no_baseline_in_a_week_an_override_governs():
    data, teams, weeks = _week_world()
    anchor = date.fromisoformat(weeks[0]["start_date"])
    p = teams["Nick"].players["P0Nick"]
    p.return_week, p.return_date = 2, weeks[1]["start_date"]     # back on day one of week 2
    try:
        draws = sb.KeyedDraws(SEED, 2000)
        for d in sb.get_dates_in_week(weeks[1]):
            assert sb.availability_on(data, teams, weeks[1], {}, draws, "Nick", "P0Nick", d, anchor).all()
        d = sb.get_dates_in_week(weeks[2])[0]
        assert not sb.availability_on(data, teams, weeks[2], {}, draws, "Nick", "P0Nick", d, anchor).all()
    finally:
        p.return_week, p.return_date = None, None


def test_an_override_is_not_charged_twice():
    """Nick, 10-21 (Kon Knueppel: out week 1, back mid-week 2, 70 GP). Yahoo's
    GP already counts a known absence, so the override's games come out of
    the projection's misses: total expected misses stay remaining - gp."""
    data, teams, weeks = _week_world()          # BOS every day: 77 scheduled + 5 unscheduled
    anchor = date.fromisoformat(weeks[0]["start_date"])
    p = teams["Nick"].players["P0Nick"]
    p.out_weeks = [1]
    p.return_week = 2
    p.return_date = (date.fromisoformat(weeks[1]["start_date"]) + timedelta(days=3)).isoformat()
    draws = sb.KeyedDraws(SEED, 4000)
    base = sb.baseline_blocks(data, teams, draws, anchor, ["Nick"])["P0Nick"]
    governed, override_missed = base.override
    assert (governed, override_missed) == (14, 10.0)
    assert base.rate == pytest.approx((82 - 70 - 10) / (82 - 14))
    dates = [d for w in weeks for d in sb.get_dates_in_week(w)]
    out = np.stack([~sb.availability_on(data, teams, weeks[(d - anchor).days // 7], {}, draws,
                                         "Nick", "P0Nick", d, anchor) for d in dates], axis=1)
    got = out.sum(axis=1).mean()
    expected = 10 + base.rate * (77 - 14)
    double = 10 + (82 - 70) / 82 * (77 - 14)
    assert got == pytest.approx(expected, abs=0.4)
    assert abs(got - double) > 1.0
    # over all 82 remaining games that is exactly the projection's 12
    assert 10 + base.rate * (82 - 14) == pytest.approx(82 - 70)


# 7 -- one availability model
def test_marginal_value_and_the_week_engine_agree_on_live_data(live):
    """One availability model. MV is built here exactly as advice_runner
    builds it -- WITH the frozen durability prior. Until 10-27 this test left
    it out, so MV read each player's LIVE projected GP while the week engine
    read the pre-season snapshot. They agreed only while data/PLAYERLIST.xlsx
    was byte-identical to that snapshot; the 10-26 refresh split them
    (Derrick White: 73 -> 77.2 GP, 15 of 300 draws). The same omission was in
    scripts/validate_marginal_value.py, the premise gate -- fixed there, and
    guarded by the next test."""
    data, teams = live
    from modules.projections import load_player_projections
    rosters = {m: list(teams[m].players) for m in MANAGERS}
    tags = {sorted(rosters["Garrett"])[0]: "Q"}      # whoever is rostered today
    ctx = mv.build_context(load_player_projections(data), rosters, data.nba_schedule,
                           data.schedule["weeks"], "regular_season", data.current_week,
                           injury_statuses=tags, sims=300, seed=SEED,
                           durability_prior=data.durability_prior)
    draws = sb.KeyedDraws(SEED, 300)
    checked = unprojected = 0
    for week in (1, 2, 9):
        wd = sb.schedule_week(data, week)
        for d in sb.get_dates_in_week(wd):
            for m in MANAGERS:
                for name in rosters[m]:
                    p = ctx.player(ctx.players.canonical(name))
                    if p.team not in sb._playing_teams(data, d):
                        continue
                    b = sb.availability_on(data, teams, wd, tags, draws, m, name, d)
                    if (teams[m].players[name].projected_fppg or 0) <= 0:
                        # No projection (Yahoo's 0 GP / 0.00 FPPG row: Acuff,
                        # Boozer on 10-27). The week engine leaves him out of
                        # the plan, which availability_on reports as never
                        # available; MV draws his availability but values him
                        # at 0.0. There is no availability to compare -- what
                        # must agree is that NEITHER engine scores him.
                        assert not b.any() and p.fppg == 0.0, (name, d, p.fppg)
                        unprojected += 1
                        continue
                    a = mv._draws(ctx, p, d, week)
                    assert np.array_equal(a, b), (name, d, int((a != b).sum()))
                    checked += 1
    assert checked > 400, (checked, unprojected)


def test_every_real_data_marginal_value_context_reads_the_frozen_prior():
    """build_context's durability_prior=None means "each player's own
    projected GP is his prior" -- right for a synthetic world, wrong for real
    data in season, where that column is games REMAINING. Every caller outside
    the tests must pass it explicitly; the premise gate did not."""
    callers = []
    for f in sorted([*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py")]):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if name == "build_context":
                    callers.append(f.name)
                    assert any(k.arg == "durability_prior" for k in node.keywords), (
                        f"{f.name}:{node.lineno} builds a marginal-value context without "
                        "durability_prior")
    assert {"advice_runner.py", "validate_marginal_value.py"} <= set(callers), callers


def test_tags_and_absences_follow_the_roster_spelling():
    """The roster says Shai Gilgeous-Alexander, PLAYERLIST says
    S. Gilgeous-Alexander. The draws are keyed by the roster's name; before
    10-21 the engine looked his tag up by PLAYERLIST's and never charged it.

    A synthetic two-spelling roster, not the live one: Yahoo respelled him in
    full on 10-26, which made the live premise false and the old test red.
    Whether the guard has a case to bite on must not depend on what Yahoo
    calls people this week."""
    data, teams, weeks = _week_world()
    name, listed = "Shai Gilgeous-Alexander", "S. Gilgeous-Alexander"
    old = teams["Hayden"].players.pop("P0Hayden")
    teams["Hayden"].players[name] = PlayerProjection(
        player_name=listed, nba_team="BOS", positions=["PG"],
        projected_fppg=old.projected_fppg, projected_gp=old.projected_gp)
    assert teams["Hayden"].players[name].player_name != name     # the premise, by construction
    anchor = date.fromisoformat(weeks[0]["start_date"])
    first = sb.get_dates_in_week(weeks[0])[0]
    draws = sb.KeyedDraws(SEED, 300)
    out = sb.availability_on(data, teams, weeks[0], {name: "O"}, draws, "Hayden", name, first, anchor)
    assert not out.any()                                          # the tag is charged
    healthy = sb.availability_on(data, teams, weeks[0], {}, draws, "Hayden", name, first, anchor)
    base = sb.baseline_blocks(data, teams, draws, anchor, ["Hayden"])
    assert name in base and listed not in base                    # keyed by the roster
    assert np.array_equal(healthy, ~base[name].missed(first))


# 8 -- the flat discount is gone
def test_the_flat_injury_discount_is_gone():
    assert not hasattr(sb, "OU_INJURY_DISCOUNT")
    for f in (ROOT / "modules").glob("*.py"):
        assert "OU_INJURY_DISCOUNT" not in f.read_text(encoding="utf-8"), f


# 9 -- CRN survives
def test_baseline_draws_are_prefix_stable():
    small, big = _blocks(70, n=500), _blocks(70, n=5000)
    assert np.array_equal(small.season_mask(), big.season_mask()[:500])


def test_baseline_draws_are_keyed_by_player_not_by_who_asks():
    a1 = _blocks(70, player="A")
    a2 = _blocks(70, player="A")
    b = _blocks(70, player="B")
    assert np.array_equal(a1.season_mask(), a2.season_mask())
    assert not np.array_equal(a1.season_mask(), b.season_mask())


def test_another_managers_roster_change_moves_nothing(live):
    data, teams = live
    from modules.projections import load_player_projections
    from modules.data_loader import free_agents
    allp = load_player_projections(data)
    # chosen at runtime from whoever is rostered and available today -- a
    # named player goes red the day he is dropped (Hartenstein, 10-26)
    drop = sorted(n for n, pp in teams["Nick"].players.items() if (pp.projected_fppg or 0) > 0)[0]
    rosters = {m: list(teams[m].players) for m in MANAGERS}
    pool = [n for n in free_agents(data.playerlist, rosters)["player_name"]
            if n in allp and (allp[n].projected_fppg or 0) > 0]
    add = max(pool, key=lambda n: (allp[n].projected_fppg, n))
    changed = dict(teams)
    import copy
    t = copy.copy(teams["Nick"]); t.players = dict(t.players)
    del t.players[drop]; t.players[add] = allp[add]
    changed["Nick"] = t
    wd = sb.schedule_week(data, 6)
    r0 = sb.simulate_week_matrix(data, teams, wd, {}, sb.KeyedDraws(SEED, 500))
    r1 = sb.simulate_week_matrix(data, changed, wd, {}, sb.KeyedDraws(SEED, 500))
    for m in ("Hayden", "Benton", "Garrett"):
        assert np.array_equal(r0[m]["score"], r1[m]["score"]), m
    assert not np.array_equal(r0["Nick"]["score"], r1["Nick"]["score"])


def test_order_independence_and_one_week_one_truth(live):
    data, teams = live
    wd = sb.schedule_week(data, 7)
    fwd = sb.simulate_week_matrix(data, teams, wd, {}, sb.KeyedDraws(SEED, 400), managers=MANAGERS)
    rev = sb.simulate_week_matrix(data, teams, wd, {}, sb.KeyedDraws(SEED, 400), managers=MANAGERS[::-1])
    mats = sb.week_score_matrices(data, teams, [5, 7], {}, SEED, 800)
    for m in MANAGERS:
        assert np.array_equal(fwd[m]["score"], rev[m]["score"])
        assert np.array_equal(mats[7][m][:400], fwd[m]["score"])


def test_nothing_draws_from_stdlib_random():
    for mod in (absence, sb, mv):
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name != "random" for a in node.names), mod
            if isinstance(node, ast.ImportFrom):
                assert node.module != "random", mod


def test_simulation_counts_are_one_config_value_each():
    """Nick, 10-21: 50,000 season sims (one number for title, playoff and
    Cup -- 'don't split'), and marginal_value raised from 400 so its noise is
    under C2's 10-point floor."""
    from modules import simulator_cup_odds, simulator_playoff_odds, simulator_title_odds
    from modules.data_loader import MARGINAL_VALUE_SIMS, SEASON_SIMS
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))["simulations"]
    assert SEASON_SIMS == cfg["season_sims"] == 50000
    for mod in (simulator_title_odds, simulator_playoff_odds, simulator_cup_odds):
        assert mod.DEFAULT_NUM_SIMULATIONS == SEASON_SIMS, mod
    assert mv.DEFAULT_SIMS == MARGINAL_VALUE_SIMS == cfg["marginal_value_sims"] >= 2000
    # the pre-filter is config too, and not so noisy it hides what the full pass would find
    from modules import advice_runner
    assert mv.SHORTLIST_SIMS == cfg["marginal_value_shortlist_sims"] >= 200
    assert advice_runner.SIMS == (mv.SHORTLIST_SIMS, mv.DEFAULT_SIMS)
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert "args.title_sims = SEASON_SIMS" in src and "default=10000" not in src
    v = (ROOT / "scripts" / "validate_marginal_value.py").read_text(encoding="utf-8")
    assert "args.sims = MARGINAL_VALUE_SIMS" in v
