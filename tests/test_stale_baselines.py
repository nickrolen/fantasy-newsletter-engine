"""Baselines that were computed once and then never advanced.

Three separate places stored "everything up to the current season" as a
number and rebuilt the real figure from it. None of them were advanced when
a season was rolled into history, so each was a season behind and would have
DELETED that season the first time the new season ran with live data:

    all_time.head_to_head_historical   348 games where the record is 362
    historical_fp / historical_gp      Jokic 28,134.7 where his career is 31,975.5
    weekly_scores                      {} read as "no format", flipping the
                                       file to a shape nothing can read

The fix in each case is to derive rather than store. These tests pin that,
and pin the scope confusion the first one was hiding.
"""
import json
from collections import defaultdict
from pathlib import Path

import pytest

import modules.report_builder as rb
from modules.data_loader import CURRENT_SEASON, MANAGERS, is_regular_season_week
from modules.records_tracker import update_weekly_scores

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def records():
    return json.loads(
        (PROJECT_ROOT / "config" / "RECORDS.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matchups():
    return json.loads((PROJECT_ROOT / "data" / "historical" /
                       "all_matchups.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# weekly_scores: an empty dict is still a dict
# ---------------------------------------------------------------------------

def test_an_empty_weekly_scores_stays_manager_keyed():
    """The season reset writes {}. The old predicate -- "a dict with at least
    one manager key" -- was false for it, so the first write of a new season
    converted the file to a legacy list shape that nothing reads, and Week 1
    died with "'list' object has no attribute 'items'".
    """
    records = {"weekly_scores": {}}
    update_weekly_scores(records, 1, {m: 100.0 for m in MANAGERS})
    got = records["weekly_scores"]
    assert isinstance(got, dict), "an empty dict must stay a dict"
    assert set(got) == set(MANAGERS)
    assert got[MANAGERS[0]] == [{"week": 1, "score": 100.0}]


def test_a_missing_weekly_scores_key_is_also_manager_keyed():
    records = {}
    update_weekly_scores(records, 1, {m: 1.0 for m in MANAGERS})
    assert isinstance(records["weekly_scores"], dict)


def test_an_actual_legacy_list_is_still_honoured():
    """Only a real list means the legacy shape; back-compat must survive."""
    records = {"weekly_scores": [{"week": 1, "scores": {"Nick": 5.0}}]}
    update_weekly_scores(records, 2, {m: 2.0 for m in MANAGERS})
    got = records["weekly_scores"]
    assert isinstance(got, list) and len(got) == 2


def test_a_populated_manager_dict_is_appended_not_replaced():
    records = {"weekly_scores": {"Nick": [{"week": 1, "score": 5.0}]}}
    update_weekly_scores(records, 2, {m: 2.0 for m in MANAGERS})
    assert records["weekly_scores"]["Nick"] == [
        {"week": 1, "score": 5.0}, {"week": 2, "score": 2.0}]


# ---------------------------------------------------------------------------
# One scope for head-to-head, derived from the matchup record
# ---------------------------------------------------------------------------

def _regular_season_h2h(matchups, exclude_season=None):
    out = defaultdict(int)
    for r in matchups:
        if not r.get("winner") or r["season"] == exclude_season:
            continue
        if not is_regular_season_week(r["season"], r["week"]):
            continue
        loser = r["manager_a"] if r["winner"] == r["manager_b"] else r["manager_b"]
        out[f"{r['winner']}_vs_{loser}"] += 1
        out.setdefault(f"{loser}_vs_{r['winner']}", 0)
    return dict(out)


def test_the_h2h_matrix_is_derived_not_read_from_a_stored_baseline():
    """_rebuild_head_to_head must not consult head_to_head_historical.

    That key was written once and never advanced; trusting it is what made
    the matrix a season short.
    """
    import inspect
    src = inspect.getsource(rb._rebuild_head_to_head)
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "all_matchups" in code, "the baseline must come from the matchup record"
    # The stored key may only appear as a fallback for a missing matchup file.
    before, marker, _ = code.partition("if not historical_h2h:")
    assert marker, "the fallback guard is gone"
    assert "head_to_head_historical" not in before, (
        "the stored baseline is being read before the derivation")


def test_all_three_h2h_tables_agree_on_scope(records, matchups):
    """h2h, head_to_head and head_to_head_historical were 362 / 394 / 348 --
    regular season, all games, and all games minus a season. The same
    newsletter printed Nick over Garrett as both 43-17 and 46-20."""
    import copy
    from types import SimpleNamespace
    at = copy.deepcopy(records["all_time"])
    data = SimpleNamespace(all_matchups=matchups,
                           records={"h2h_season": {}})
    rb._rebuild_head_to_head(at, data)

    expected = _regular_season_h2h(matchups)
    matrix = {k: v for k, v in at["head_to_head"].items() if isinstance(v, int)}
    assert matrix == expected

    pairs = sum(x for v in at["h2h"].values()
                for x in v.values() if isinstance(x, int))
    assert sum(matrix.values()) == pairs, (
        "the matrix and all_time.h2h must count the same games")


def test_the_matrix_carries_its_manager_list_before_week_one(records, matchups):
    import copy
    from types import SimpleNamespace
    at = copy.deepcopy(records["all_time"])
    rb._rebuild_head_to_head(at, SimpleNamespace(all_matchups=matchups,
                                                 records={"h2h_season": {}}))
    assert at["head_to_head"]["managers"] == sorted(MANAGERS)


# ---------------------------------------------------------------------------
# Career baselines
# ---------------------------------------------------------------------------

def test_career_baselines_are_recomputed_not_trusted():
    import inspect
    src = inspect.getsource(rb._patch_cumulative_records)
    assert "historical_playerlog" in src, (
        "historical_fp/historical_gp must be derived from the player log; "
        "the stored values go stale the moment a season is rolled in")


def test_the_stored_career_baselines_match_the_player_log(records):
    """Even before the derivation runs, they should now agree."""
    rows = json.loads((PROJECT_ROOT / "data" / "historical" /
                       "HISTORICAL_PLAYERLOG.json").read_text(encoding="utf-8"))
    totals = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r.get("season_key") == CURRENT_SEASON:
            continue
        if not (r.get("started") and r.get("had_game")) or r.get("is_injured"):
            continue
        slot = totals[r["player_name"]]
        slot[0] += float(r.get("fantasy_points") or 0.0)
        slot[1] += 1

    checked = 0
    for entry in records["all_time"]["career_total_fp_top10"]:
        want = totals.get(entry["player_name"])
        if not want:
            continue
        checked += 1
        name = entry["player_name"]
        # The baseline is "career through the last completed season". The
        # current season has no data yet, so it must equal total_fp exactly --
        # and the stale version differed by a whole season (Jokic 28,134.7
        # against 31,975.5, 62 games).
        assert abs(entry["historical_fp"] - want[0]) < 1.0, name
        assert entry["historical_gp"] == want[1], name
        assert abs(entry["total_fp"] - entry["historical_fp"]) < 1.0, (
            f"{name}: total_fp and the baseline disagree with no current-season "
            "data to explain it")
    assert checked >= 5


# ---------------------------------------------------------------------------
# Nothing reads the season boundary out of SCHEDULE.json
# ---------------------------------------------------------------------------

def test_no_module_takes_its_week_counts_from_the_schedule_file():
    """SCHEDULE.json is the PREVIOUS season's file for the whole preseason.

    Six modules read week counts out of it, so they applied a 21-week regular
    season to a 15-week one: title odds projected a race that does not exist,
    W-L records ran to week 21, luck index included the bracket, and playoff
    seeds moved on bracket results. league_config is the one source.
    """
    import re
    offenders = []
    pattern = re.compile(
        r'schedule\.get\(\s*"(regular_season_weeks|total_weeks|playoff_start_week)"')
    for f in sorted((PROJECT_ROOT / "modules").glob("*.py")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                offenders.append(f"modules/{f.name}:{i}: {line.strip()}")
    assert offenders == [], (
        "use regular_season_weeks_for(CURRENT_SEASON) / stage_weeks() "
        "instead:\n  " + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# Record-book hygiene
# ---------------------------------------------------------------------------

def test_playoff_titles_match_the_league_history_sheet(records):
    """Stored 0/0/0/1; the sheet says 3/2/3/2, and so does the matchup record."""
    import pandas as pd
    sheet = pd.read_excel(PROJECT_ROOT / "data" / "LEAGUEHISTORY.xlsx")
    want = dict(zip(sheet["manager_name"], sheet["playoff_championships"]))
    got = {m: c.get("playoff_titles")
           for m, c in records["all_time"]["manager_careers"].items()}
    assert got == {m: int(v) for m, v in want.items()}


def test_no_top10_list_holds_a_duplicate(records):
    """A duplicate displaces a legitimate record. longest_loss_streak_top10
    held Benton's 2023-24 8-game streak twice, so the list carried nine
    records in ten slots."""
    offenders = []
    for key, entries in records["all_time"].items():
        if not key.endswith("_top10") or not isinstance(entries, list):
            continue
        seen = set()
        for e in entries:
            if not isinstance(e, dict):
                continue
            ident = tuple(sorted(
                (k, v) for k, v in e.items()
                if isinstance(v, (str, int, float)) and k != "rank"))
            if ident in seen:
                offenders.append(f"{key}: {e}")
            seen.add(ident)
    assert offenders == [], "duplicate entries:\n  " + "\n  ".join(offenders)


def test_leaderboard_records_match_the_final_standings(records):
    """Entries written mid-season and never refreshed: three 2025-26 rows
    carried a week-22 record while the same file's other lists had the
    finished one."""
    standings = {(r["season"], r["manager"]): r for r in json.loads(
        (PROJECT_ROOT / "data" / "historical" / "all_standings.json")
        .read_text(encoding="utf-8"))}
    bad = []
    for key, entries in records["all_time"].items():
        if not key.startswith(("best_manager_season", "worst_manager_season")):
            continue
        if not isinstance(entries, list):
            continue
        for e in entries:
            final = standings.get((e.get("season"), e.get("manager")))
            if final and (e.get("wins"), e.get("losses")) != \
                    (final["wins"], final["losses"]):
                bad.append(f"{key}: {e['season']} {e['manager']} "
                           f"{e.get('wins')}-{e.get('losses')} vs final "
                           f"{final['wins']}-{final['losses']}")
    assert bad == [], "\n  ".join(bad)
