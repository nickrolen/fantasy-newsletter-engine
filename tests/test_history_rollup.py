"""The historical files must all describe the same seasons, and agree.

Four of them -- all_matchups, all_standings, all_teams, all_trades -- sat a
season behind while HISTORICAL_PLAYERLOG and all_drafts moved on, because the
rollup only covered those two. Nothing failed; the all-time tables just
quietly answered for eight seasons instead of nine.

The class of bug is "derived file silently stale", so the tests here are
cross-checks between files rather than assertions about any one of them.
"""
import json
from collections import defaultdict
from pathlib import Path

import pytest

from modules.data_loader import is_regular_season_week, regular_season_weeks_for

PROJECT_ROOT = Path(__file__).parent.parent
HIST = PROJECT_ROOT / "data" / "historical"


def _load(name):
    return json.loads((HIST / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matchups():
    return _load("all_matchups.json")


@pytest.fixture(scope="module")
def standings():
    return _load("all_standings.json")


@pytest.fixture(scope="module")
def records():
    return json.loads(
        (PROJECT_ROOT / "config" / "RECORDS.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def roll():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rollup", PROJECT_ROOT / "scripts" / "rollup_season_to_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The files agree on which seasons exist
# ---------------------------------------------------------------------------

def test_the_season_tables_all_cover_the_same_seasons(matchups, standings):
    """The actual bug: four files a season behind two others."""
    seasons = {
        "all_matchups.json": {r["season"] for r in matchups},
        "all_standings.json": {r["season"] for r in standings},
        "all_teams.json": set(_load("all_teams.json")),
        "all_drafts.json": {r["season"] for r in _load("all_drafts.json")},
        "HISTORICAL_PLAYERLOG.json": {r["season_key"]
                                      for r in _load("HISTORICAL_PLAYERLOG.json")},
    }
    reference = seasons["all_matchups.json"]
    behind = {name: sorted(reference - s) for name, s in seasons.items()
              if reference - s}
    assert behind == {}, f"these files are missing seasons: {behind}"


def test_all_trades_is_allowed_to_be_short_but_not_beyond_the_latest_season(matchups):
    """Some seasons genuinely had no trades; none may be NEWER than the record."""
    trades = _load("all_trades.json")
    latest_played = max(r["season"] for r in matchups)
    traded = {r["season"] for r in trades}
    assert traded <= {r["season"] for r in matchups}
    assert max(traded) <= latest_played


def test_the_summary_is_not_stale(matchups):
    """historical_summary.json is derived; left alone it reports old totals."""
    summary = _load("historical_summary.json")
    assert sorted(summary["seasons_processed"]) == sorted({r["season"] for r in matchups})
    assert summary["total_matchups"] == len(matchups)
    assert summary["total_draft_picks"] == len(_load("all_drafts.json"))


def test_every_season_has_a_full_slate_of_matchups(matchups):
    """4 managers means 2 matchups a week; a short week means a lost result."""
    by_season = defaultdict(set)
    for r in matchups:
        by_season[r["season"]].add(r["week"])
    per_week = defaultdict(lambda: defaultdict(int))
    for r in matchups:
        per_week[r["season"]][r["week"]] += 1
    for season, weeks in by_season.items():
        assert weeks == set(range(1, max(weeks) + 1)), f"{season} has a gap"
        short = {w: n for w, n in per_week[season].items() if n != 2}
        assert short == {}, f"{season} weeks without exactly 2 matchups: {short}"


# ---------------------------------------------------------------------------
# The rebuild reproduces what is stored
# ---------------------------------------------------------------------------

def test_build_standings_reproduces_every_stored_rank(roll, matchups, standings):
    """If the reconstruction can reproduce eight seasons written by a
    different code path, it can be trusted to write the ninth."""
    by_season = defaultdict(list)
    for r in matchups:
        by_season[r["season"]].append(r)
    stored = {(r["season"], r["manager"]): r for r in standings}

    checked = 0
    for season, rows in by_season.items():
        for computed in roll.build_standings(season, rows):
            want = stored.get((season, computed["manager"]))
            if not want:
                continue
            checked += 1
            tag = f"{season} {computed['manager']}"
            assert computed["rank"] == want["rank"], tag
            assert computed["wins"] == want["wins"], tag
            assert computed["losses"] == want["losses"], tag
            # points_for is a sum of ~23 two-decimal scores; it drifts from
            # the season total by a rounding unit.
            assert abs(computed["points_for"] - want["points_for"]) < 0.5, tag
    assert checked >= 32


def test_rank_is_the_all_games_record_not_the_title(standings):
    """Named explicitly because it is neither champion nor playoff champion.

    2025-26 is the clean example: Nick has rank 1 on an all-games record,
    regular_season_rank 1 (he IS the League Champion), and playoff_rank 4 --
    he lost both bracket games. Three different numbers, one row.
    """
    row = next(r for r in standings
               if r["season"] == "2025-26" and r["manager"] == "Nick")
    assert row["rank_basis"] == "all_games_record"
    assert row["regular_season_rank"] == 1
    assert row["playoff_rank"] == 4
    assert (row["reg_wins"], row["reg_losses"]) == (17, 4)


def test_every_standing_row_names_its_rank_basis(standings):
    for r in standings:
        assert r.get("rank_basis"), f"{r['season']} {r['manager']} has no rank_basis"
        assert r.get("regular_season_rank"), f"{r['season']} {r['manager']}"
        assert "reg_wins" in r and "reg_losses" in r


def test_the_regular_season_tiebreaker_is_head_to_head_within_the_tied_group(roll, matchups):
    """2025-26: Benton and Garrett both finished 10-11.

    Benton won the season series 4-3, so Benton seeds 2nd -- which is what
    the Week 21 newsletter recorded at the time. Garrett scored more points
    over the season, so a tiebreaker that falls through to points puts him
    2nd instead, and that rank sets the draft order.
    """
    rows = [r for r in matchups if r["season"] == "2025-26"]
    st = {r["manager"]: r for r in roll.build_standings("2025-26", rows)}
    assert st["Benton"]["reg_wins"] == st["Garrett"]["reg_wins"] == 10
    assert st["Garrett"]["points_for"] > st["Benton"]["points_for"]
    assert st["Benton"]["regular_season_rank"] == 2
    assert st["Garrett"]["regular_season_rank"] == 3


def test_2025_26_champions_match_what_was_published(roll, matchups):
    rows = [r for r in matchups if r["season"] == "2025-26"]
    st = roll.build_standings("2025-26", rows)
    league = next(r["manager"] for r in st if r["regular_season_rank"] == 1)
    playoff = next(r["manager"] for r in st if r.get("playoff_rank") == 1)
    assert league == "Nick", "the Week 21 newsletter had Nick 17-4 as the #1 seed"
    assert playoff == "Garrett"


# ---------------------------------------------------------------------------
# RECORDS.json agrees with the matchup record
# ---------------------------------------------------------------------------

def _regular_season_tally(matchups):
    wl = defaultdict(lambda: [0, 0])
    h2h = defaultdict(lambda: defaultdict(int))
    for r in matchups:
        if not r.get("winner"):
            continue
        if not is_regular_season_week(r["season"], r["week"]):
            continue
        wl[r["winner"]][0] += 1
        wl[r["loser"]][1] += 1
        key = "_vs_".join(sorted((r["manager_a"], r["manager_b"])))
        h2h[key][r["winner"].lower()] += 1
        h2h[key].setdefault(r["loser"].lower(), 0)
    return wl, h2h


def test_career_records_are_regular_season_only(records, matchups):
    """They were not. The stored totals were every manager's regular-season
    record PLUS their postseason record -- Nick 120-77 where the regular
    season alone says 113-68. records_tracker's own docstring says regular
    season only; the guard was added after the totals had accumulated and
    they were never rebuilt. Career win % is printed from these.
    """
    wl, _ = _regular_season_tally(matchups)
    careers = records["all_time"]["manager_careers"]
    for manager, (wins, losses) in wl.items():
        got = careers[manager]
        assert (got["total_wins"], got["total_losses"]) == (wins, losses), (
            f"{manager}: stored {got['total_wins']}-{got['total_losses']}, "
            f"regular season only says {wins}-{losses}")
        assert got["games_played"] == wins + losses
        assert got["games_scope"] == "regular_season"
        assert abs(got["win_pct"] - wins / (wins + losses) * 100) < 0.1


def test_all_time_h2h_is_regular_season_only(records, matchups):
    _, h2h = _regular_season_tally(matchups)
    stored = {k: {kk.lower(): vv for kk, vv in v.items() if isinstance(vv, int)}
              for k, v in records["all_time"]["h2h"].items()}
    assert stored == {k: dict(v) for k, v in h2h.items()}


def test_career_games_equal_the_sum_of_every_seasons_regular_season(records, matchups):
    """An independent route to the same number, so a shared bug shows up."""
    expected = sum(regular_season_weeks_for(s)
                   for s in {r["season"] for r in matchups})
    for manager, got in records["all_time"]["manager_careers"].items():
        assert got["games_played"] == expected, (
            f"{manager} played {got['games_played']} regular-season games; the "
            f"season lengths on file add up to {expected}")
