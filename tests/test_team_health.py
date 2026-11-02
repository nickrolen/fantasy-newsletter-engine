"""Current Team Health counts IL slots and tags, not only overrides
(STATUS task 20; claude/HANDOFF_SECTION10_OFF_AND_BUDGET_WEEK_2026-11-02.md
part 5).

The week 2 issue printed "Garrett ... enters week 3 at 100.0% health" with
Kon Knueppel in Garrett's IL slot for all of week 3 (tagged O, no override):
build_current_team_health read INJURY_OVERRIDES only. Now, for week N+1:
an IL slot is out all week; an override counts as before; a Q/D/O tag with
no override costs the games the absence model (absence.missed_distribution,
the simulators' chain) expects him to miss; OFS is out for the season.
"""
from types import SimpleNamespace

import pandas as pd
import pytest

from modules import absence
from modules import report_builder as rb
from modules.fetch_injury_statuses import Tags

WEEKS = {"weeks": [{"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01"},
                   {"week": 3, "start_date": "2026-11-02", "end_date": "2026-11-08"},
                   {"week": 4, "start_date": "2026-11-09", "end_date": "2026-11-15"}]}
# week 3 game days per NBA team (each listed date is one game)
GAMES = {"CHA": ["2026-11-03", "2026-11-05", "2026-11-07", "2026-11-08"],
         "WAS": ["2026-11-02", "2026-11-04", "2026-11-06"],
         "BOS": ["2026-11-03", "2026-11-06"],
         "OKC": ["2026-11-02", "2026-11-04", "2026-11-06", "2026-11-08"],
         "MIN": ["2026-11-03", "2026-11-05", "2026-11-07"],
         "NYK": ["2026-11-02", "2026-11-05"]}
PLAYERS = [  # name, team, projected FPPG, manager
    ("Kon Knueppel", "CHA", 37.3, "Garrett"), ("Alex Sarr", "WAS", 28.7, "Garrett"),
    ("Jaylen Brown", "BOS", 44.0, "Garrett"), ("Garrett Guy", "NYK", 30.0, "Garrett"),
    ("Chet Holmgren", "OKC", 40.2, "Hayden"), ("Hayden Guy", "NYK", 30.0, "Hayden"),
    ("Anthony Edwards", "MIN", 42.8, "Nick"), ("Nick Guy", "NYK", 30.0, "Nick"),
    ("Benton Guy", "NYK", 30.0, "Benton")]


def world(il_week=3, slots=None, overrides=()):
    games = {}
    for team, days in GAMES.items():
        for i, d in enumerate(days):
            games.setdefault(d, []).append({"date": d, "home": team, "away": f"X{i}{team}"})
    rosters = {}
    for n, _t, _p, m in PLAYERS:
        rosters.setdefault(m, []).append(n)
    data = SimpleNamespace(
        schedule=WEEKS, nba_schedule={"games": [g for v in games.values() for g in v]},
        playerlist=pd.DataFrame([{"player_name": n, "player_nba_team": t, "projectedFPPG": p}
                                 for n, t, p, _m in PLAYERS]),
        injury_overrides={"players": list(overrides)},
        il_slots={"fantasy_week": il_week, "fetched_at": None,
                  "slots": slots if slots is not None else {"Garrett": ["Kon Knueppel"]}},
        base_path=".", lineups=None)
    data.get_current_rosters = lambda: rosters
    data.get_nba_games_for_date = lambda d: games.get(d.isoformat(), [])
    return data


def health(data, tags):
    return rb.build_current_team_health(data, 2, injury_statuses=tags)


def by_player(h, m):
    return {p["player"]: p for p in h["teams"][m]["injured_players"]}


def test_an_il_slot_player_with_no_override_and_no_tag_is_out_all_week():
    h = health(world(), Tags({}))
    k = by_player(h, "Garrett")["Kon Knueppel"]
    assert (k["status"], k["availability_pct"], k["why"], k["source"]) == ("out", 0, "IL slot", "il_slot")
    total = 37.3 + 28.7 + 44.0 + 30.0
    assert h["teams"]["Garrett"]["injured_fppg"] == 37.3
    assert h["teams"]["Garrett"]["health_pct"] == round((total - 37.3) / total * 100, 1)


def test_an_o_tagged_player_with_no_override_costs_the_models_expected_games():
    """Sarr's team has 3 games in week 3: O misses g1 surely, then the
    chain; expected = sum P(r) * min(r, 3) -- a tag alone, at most 3 games."""
    h = health(world(slots={}), Tags({"Alex Sarr": "O"}))
    s = by_player(h, "Garrett")["Alex Sarr"]
    dist = absence.missed_distribution("O")
    want = sum(p * min(r, 3) for r, p in enumerate(dist))
    assert s["expected_missed"] == round(want, 2) and s["week_games"] == 3
    assert s["why"] == f"O tag, expected to miss ~{want:.1f} of 3 games"
    assert s["status"] == "tagged" and 0 < s["availability_pct"] < 100
    assert h["teams"]["Garrett"]["injured_fppg"] == round(28.7 * want / 3, 1)


def test_a_q_tag_on_a_two_game_team_never_charges_more_than_his_games():
    h = health(world(slots={}), Tags({"Jaylen Brown": "D"}))
    b = by_player(h, "Garrett")["Jaylen Brown"]
    assert b["week_games"] == 2 and b["expected_missed"] <= 2


def test_an_override_still_counts_as_today_and_suppresses_the_tag():
    ov = [{"player_name": "Chet Holmgren", "nba_team": "OKC", "out_weeks": [2, 3, 4],
           "notes": "Knee", "return_week": 5, "return_games": 3, "total_week_games": 3,
           "return_notes": "", "return_date": "2026-11-17"},
          {"player_name": "Anthony Edwards", "nba_team": "MIN", "out_weeks": [2],
           "notes": "Knee", "return_week": 3, "return_games": 2, "total_week_games": 3,
           "return_notes": "back Thursday", "return_date": "2026-11-05"}]
    h = health(world(slots={}, overrides=ov), Tags({"Chet Holmgren": "O", "Anthony Edwards": "O"}))
    c = by_player(h, "Hayden")["Chet Holmgren"]
    assert (c["status"], c["remaining_weeks"], c["why"]) == ("out", 2, "override, back 11-17")
    e = by_player(h, "Nick")["Anthony Edwards"]
    assert (e["status"], e["availability_pct"]) == ("returning", 67)
    assert e["why"] == "override, back 11-05 (2 of 3 games)"
    assert h["teams"]["Nick"]["injured_fppg"] == round(42.8 / 3, 1)     # not the tag's games
    assert [r["player"] for r in h["returning_players"]] == ["Anthony Edwards"]


def test_ofs_is_out_for_the_season():
    h = health(world(slots={}), Tags({"Jaylen Brown": "OFS"}))
    b = by_player(h, "Garrett")["Jaylen Brown"]
    assert b["is_season_long"] and b["availability_pct"] == 0 and b["why"] == "OFS tag, out for the season"


def test_a_stale_il_file_raises():
    with pytest.raises(rb.TeamHealthInputError, match="fantasy week 2"):
        health(world(il_week=2), Tags({}))


def test_no_statement_about_the_tags_raises():
    with pytest.raises(rb.TeamHealthInputError, match="injury tags"):
        health(world(), None)


def test_a_run_priced_without_tags_says_the_tags_were_not_counted():
    h = health(world(), Tags.none())
    assert h["counted"]["tags"].startswith("not counted")
    assert "Kon Knueppel" in by_player(h, "Garrett")                # IL slots still count


def test_garrett_on_the_11_02_shape_is_below_100():
    """Knueppel in Garrett's IL slot for week 3, tagged O, no override; Sarr Q."""
    h = health(world(), Tags({"Kon Knueppel": "O", "Alex Sarr": "Q"}))
    g = h["teams"]["Garrett"]
    assert g["health_pct"] < 100.0
    assert by_player(h, "Garrett")["Kon Knueppel"]["why"] == "IL slot"       # the slot wins
    assert by_player(h, "Garrett")["Alex Sarr"]["why"].startswith("Q tag, expected to miss ~")
    assert h["teams"]["Benton"]["health_pct"] == 100.0


def test_the_report_passes_the_runs_tags():
    import inspect
    src = inspect.getsource(rb.build_stats_report)
    assert "build_current_team_health(data, week,\n" in src and "injury_statuses=injury_statuses)" in src


def test_the_formatter_prints_the_reason():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "fsr", Path(__file__).parent.parent / "scripts" / "format_stats_report.py")
    f = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(f)
    h = health(world(), Tags({"Alex Sarr": "Q"}))
    for p in h["teams"]["Garrett"]["injured_players"]:
        assert f._health_why(p) == p["why"]
    old = {"player": "X", "proj_fppg": 10.0, "remaining_weeks": 3, "status": "out"}
    assert f._health_why(old) == "3 weeks remaining, status: out"       # pre-11-02 reports
