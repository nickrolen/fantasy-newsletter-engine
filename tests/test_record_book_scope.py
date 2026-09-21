"""One meaning per number in the record book.

The 2026-27 format change broke an ambiguity that had been harmless for nine
seasons. Season leaderboards store a W-L next to the volume figure they rank
on, and that W-L has always counted EVERY matchup played, postseason
included. Through 2025-26 it differed from the regular-season record by two
games. From 2026-27 it differs by eight, and the competitive season is 15
weeks against 21 before -- so the same "19-4" now means two very different
things depending on which one the reader assumes.

The fix is not a new window. It is saying which span each number covers:

    volume       every week played (23 in both eras) -- stays comparable
    competitive  weeks 1-15 now, 1-21 before -- the title race
    rates        unaffected by season length either way

and publishing the denominator so a reader can see why two eras differ.
"""
import json
from pathlib import Path

import pytest

import modules.report_builder as rb
from modules.data_loader import MANAGERS, is_regular_season_week

PROJECT_ROOT = Path(__file__).parent.parent

TOP10_KEYS = [
    "best_manager_season_top10",
    "worst_manager_season_top10",
    "best_manager_season_fpweek_top10",
    "worst_manager_season_fpweek_top10",
    "best_manager_season_fppg_top10",
    "worst_manager_season_fppg_top10",
]


@pytest.fixture(scope="module")
def records():
    return json.loads(
        (PROJECT_ROOT / "config" / "RECORDS.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def all_time(records):
    return records["all_time"]


@pytest.fixture(scope="module")
def built(records):
    return rb.build_all_time_records(records)


# ---------------------------------------------------------------------------
# The label
# ---------------------------------------------------------------------------

def test_a_scoped_entry_says_regular_season():
    label = rb._season_wl({"wins": 19, "losses": 4,
                           "reg_wins": 17, "reg_losses": 4, "reg_weeks": 21})
    assert label == "17-4 regular season (21 wks)"


def test_an_unscoped_entry_says_all_games_rather_than_guessing():
    """Falling back to the all-games pair unlabelled is the actual bug."""
    assert rb._season_wl({"wins": 19, "losses": 4}) == "19-4 all games"


def test_every_label_names_its_span():
    for entry in ({"wins": 5, "losses": 5},
                  {"wins": 5, "losses": 5, "reg_wins": 4, "reg_losses": 3,
                   "reg_weeks": 7},
                  {}):
        label = rb._season_wl(entry)
        assert "regular season" in label or "all games" in label, label


def test_the_detail_line_puts_the_record_before_the_volume():
    line = rb._season_detail(
        {"reg_wins": 13, "reg_losses": 2, "reg_weeks": 15},
        "1,761.3 FP/week over 23 weeks played")
    assert line.startswith("13-2 regular season (15 wks),")
    assert "23 weeks played" in line


def test_no_leaderboard_prints_a_bare_win_loss_pair():
    """Guard against the old detail_fn pattern coming back."""
    import re
    src = (PROJECT_ROOT / "modules" / "report_builder.py").read_text(encoding="utf-8")
    bad = re.findall(
        r"detail_fn=lambda e: f\"\{e\.get\('wins'.{0,40}\}-\{e\.get\('losses'", src)
    assert bad == [], (
        "a season leaderboard is printing wins-losses with no scope named; "
        "use _season_detail() instead")


# ---------------------------------------------------------------------------
# The stored data
# ---------------------------------------------------------------------------

def test_every_stored_season_entry_carries_its_competitive_record(all_time):
    missing = [
        f"{key}: {e.get('season')} {e.get('manager')}"
        for key in TOP10_KEYS for e in all_time.get(key, [])
        if not e.get("reg_weeks")
    ]
    assert missing == [], (
        "run scripts/backfill_season_record_scope.py -- these entries would "
        f"render as 'all games' next to scoped ones:\n  " + "\n  ".join(missing))


def test_the_competitive_record_is_a_subset_of_the_all_games_record(all_time):
    for key in TOP10_KEYS:
        for e in all_time.get(key, []):
            tag = f"{key} {e.get('season')} {e.get('manager')}"
            assert e["reg_weeks"] <= e["weeks"], tag
            assert e["reg_wins"] <= e["wins"], tag
            assert e["reg_losses"] <= e["losses"], tag
            assert e["reg_wins"] + e["reg_losses"] <= e["reg_weeks"], tag


def test_the_competitive_span_matches_that_seasons_configured_boundary(all_time):
    """21 weeks for a normal old season, 20 for 2021-22, 16 for 2020-21."""
    from modules.data_loader import regular_season_weeks_for
    for key in TOP10_KEYS:
        for e in all_time.get(key, []):
            assert e["reg_weeks"] <= regular_season_weeks_for(e["season"]), (
                f"{e['season']} {e['manager']}: {e['reg_weeks']} regular-season "
                f"weeks, but that season only had "
                f"{regular_season_weeks_for(e['season'])}")


def test_backfill_agrees_with_an_independent_recount(all_time):
    """Recompute from all_matchups.json and compare, rather than trusting it."""
    rows = json.loads((PROJECT_ROOT / "data" / "historical" /
                       "all_matchups.json").read_text(encoding="utf-8"))
    tally = {}
    for r in rows:
        if not is_regular_season_week(r["season"], r["week"]):
            continue
        for who, field in ((r.get("winner"), "w"), (r.get("loser"), "l")):
            if who:
                tally.setdefault((r["season"], who), {"w": 0, "l": 0})[field] += 1

    checked = 0
    for e in all_time["best_manager_season_top10"]:
        want = tally.get((e["season"], e["manager"]))
        if not want:
            continue  # season not in all_matchups (e.g. 2025-26, from archive)
        checked += 1
        assert (e["reg_wins"], e["reg_losses"]) == (want["w"], want["l"]), (
            f"{e['season']} {e['manager']}: stored {e['reg_wins']}-"
            f"{e['reg_losses']}, recount says {want['w']}-{want['l']}")
    assert checked > 0, "nothing was actually cross-checked"


# ---------------------------------------------------------------------------
# Denominators
# ---------------------------------------------------------------------------

def test_career_standings_publish_their_denominator(built):
    for row in built["career_standings"]:
        assert row["games_played"] == row["wins"] + row["losses"]
        assert row["games_scope"] == "regular_season"
        if row["games_played"]:
            assert abs(row["win_pct"]
                       - row["wins"] / row["games_played"] * 100) < 0.11


def test_manager_cards_show_the_games_played(built):
    """The card said "Record"; it now has to say which record."""
    src = (PROJECT_ROOT / "modules" / "stats_corner_viz.py").read_text(encoding="utf-8")
    assert "Reg. season ({games} g)" in src, (
        "the career card must name its span and denominator")


# ---------------------------------------------------------------------------
# Head-to-head leads with the rate
# ---------------------------------------------------------------------------

def test_h2h_carries_a_rate_and_a_denominator(built):
    h2h = built["h2h_records"]
    assert h2h, "no all-time h2h to check"
    for key, entry in h2h.items():
        a, b = key.split("_vs_")
        wins = {a.lower(): entry[a.lower()], b.lower(): entry[b.lower()]}
        assert entry["games"] == sum(wins.values())
        assert abs(sum(entry["pct"].values()) - 100.0) < 0.2, key
        for who, w in wins.items():
            assert abs(entry["pct"][who] - w / entry["games"] * 100) < 0.11


def test_h2h_rate_is_what_survives_the_shorter_season():
    """5 meetings a season instead of 7 changes the count, not the rate."""
    old_era = {"nick": 42, "hayden": 21}          # 63 games, 7/season x 9
    new_era = {"nick": 42 + 10, "hayden": 21 + 5}  # 5/season added
    built_old = rb.build_all_time_records(
        {"all_time": {"h2h": {"Hayden_vs_Nick": dict(old_era)}}})
    built_new = rb.build_all_time_records(
        {"all_time": {"h2h": {"Hayden_vs_Nick": dict(new_era)}}})
    assert built_old["h2h_records"]["Hayden_vs_Nick"]["games"] == 63
    assert built_new["h2h_records"]["Hayden_vs_Nick"]["games"] == 78
    # the rate barely moves; the count moved a lot
    assert abs(built_old["h2h_records"]["Hayden_vs_Nick"]["pct"]["nick"]
               - built_new["h2h_records"]["Hayden_vs_Nick"]["pct"]["nick"]) < 0.5


def test_the_h2h_table_leads_with_the_rate():
    src = (PROJECT_ROOT / "scripts" / "format_stats_report.py").read_text(encoding="utf-8")
    assert "| Matchup | Leader | Record | Games |" in src
    assert "regular season only" in src


# ---------------------------------------------------------------------------
# What must NOT have changed
# ---------------------------------------------------------------------------

def test_volume_records_still_span_every_week_played(all_time):
    """The fix must not quietly narrow the leaderboards to 21 weeks.

    Season TOTAL FP is comparable across the format change precisely because
    it counts every week played -- 23 in both eras. Restricting it would
    invalidate nine seasons of stored leaderboards to solve a problem the
    code does not have.
    """
    for e in all_time["best_manager_season_top10"]:
        if e["season"] in ("2019-20", "2020-21", "2021-22"):
            continue  # genuinely short seasons
        assert e["weeks"] >= 23, (
            f"{e['season']} {e['manager']} counts only {e['weeks']} weeks; "
            "the volume leaderboard must span the whole season")


def test_rate_records_have_the_same_denominator_in_both_eras(all_time):
    for e in all_time["best_manager_season_fpweek_top10"]:
        assert abs(e["fppg_per_week"] - e["total_fp"] / e["weeks"]) < 0.11
