"""5f item 5: the two seasons before the Yahoo data, in full (Nick, 11-23;
LEAGUE_RULES "Season numbering"): each manager's team, W-L, regular-season
finish and Yahoo's points, and the bracket with its scores, in config
(league_config pre_data_era.seasons), read through ONE function
(league.pre_era_season(s)) that RAISES on a missing or contradictory fact.
Champions shows the champion's team and the final's score, and says
"Standings and brackets only: no weekly scores or stats"."""
import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from league_state import needs_state
from modules.data_loader import _LEAGUE_CONFIG, SEASON_STRUCTURE
from modules.hub_v2 import league as L

ROOT = Path(__file__).resolve().parents[1]
MGRS = ["Nick", "Hayden", "Benton", "Garrett"]


def pre():
    return copy.deepcopy(_LEAGUE_CONFIG["pre_data_era"])


def test_the_real_config_reads_as_league_rules_has_it():
    ss = L.pre_era_seasons()
    assert list(ss) == ["2014-15", "2016-17"]
    a = ss["2014-15"]
    assert [(x["finish"], x["manager"], x["team"], x["record"], x["pts"]) for x in a["standings"]] == [
        (1, "Nick", "Russell Eastbrook", "15-6", 23092.85), (2, "Benton", "Serge I-Block-Ya", "12-9", 23200.5),
        (3, "Garrett", "The Birdmen", "10-11", 22540.2), (4, "Hayden", "Giant KIllers", "5-16", 20167.6)]
    assert a["bracket"]["final"]["score"] == "1,296.00–1,249.25" and a["bracket"]["final"]["winner"] == "Nick"
    assert a["bracket"]["third_place"]["winner"] == "Garrett"
    b = L.pre_era_season("2016-17")
    assert b["teams"] == {"Hayden": "Hayden's Rad Team", "Nick": "3Js", "Benton": "Serge I-Block-Ya",
                          "Garrett": "Trump University"}
    s1 = next(x for x in b["bracket"]["semifinals"] if x["winner"] == "Garrett")
    assert s1["loser"] == "Hayden" and sorted(s1["seeds"]) == [1, 4]            # 4 over 1
    assert b["bracket"]["final"]["winner"] == "Benton" and b["bracket"]["third_place"]["winner"] == "Hayden"
    with pytest.raises(L.LeagueError, match="not a pre-Yahoo season"):
        L.pre_era_season("2015-16")                                           # not played


def _bad(fn, match):
    p = pre()
    fn(p["seasons"])
    with pytest.raises(L.LeagueError, match=match):
        L.pre_era_seasons(p)


def test_each_season_is_21_games_per_manager():
    def f(s):
        s["2014-15"]["standings"][0]["w"] = 16
    _bad(f, "Nick is 16-6, 22 games, not 21")


def test_the_finish_follows_the_records():
    def f(s):
        st = s["2016-17"]["standings"]
        st[2]["w"], st[2]["l"], st[1]["w"], st[1]["l"] = 12, 9, 8, 13        # Benton 3rd at 12-9, Nick 2nd at 8-13
    _bad(f, "the finish follows the records")


def test_the_regular_seasons_first_is_the_league_champion():
    def f(s):
        s["2014-15"]["league_champion"], s["2014-15"]["league_runner_up"] = "Benton", "Nick"
    p = pre()
    f(p["seasons"])
    p["titles_won"] = {"Benton": 1, "Hayden": 1}
    with pytest.raises(L.LeagueError, match="are not league_champion"):
        L.pre_era_seasons(p)


def test_the_brackets_winners_are_the_playoff_champion_and_runner_up():
    def f(s):
        fin = s["2016-17"]["bracket"]["final"]
        fin["a_pts"], fin["b_pts"] = fin["b_pts"], fin["a_pts"]               # Garrett would win it
    _bad(f, "are not playoff_champion / playoff_runner_up")


def test_the_bracket_is_seeded_and_wired():
    def seeds(s):
        sf = s["2014-15"]["bracket"]["semifinals"]
        sf[0]["b"], sf[1]["b"] = sf[1]["b"], sf[0]["b"]                       # 1 v 3, 2 v 4
    _bad(seeds, "not 1 v 4 and 2 v 3")

    def third(s):
        s["2014-15"]["bracket"]["third_place"]["b"] = "Nick"
    _bad(third, "not the semifinals' losers")

    def tie(s):
        s["2014-15"]["bracket"]["final"]["b_pts"] = 1296.00
    _bad(tie, "tie at 1,296.00")


@pytest.mark.parametrize("key", ["standings", "bracket", "regular_season_games"])
def test_a_missing_fact_raises(key):
    def f(s):
        del s["2016-17"][key]
    _bad(f, f"lacks '{key}'")


def test_a_missing_team_name_raises():
    def f(s):
        s["2016-17"]["standings"][1]["team"] = " "
    _bad(f, "Nick has no team name")


def test_the_careers_check_raises_on_any_difference():
    ss = L.pre_era_seasons()
    lh = [{"manager_name": m, "regular_season_record": r} for m, r in
          (("Nick", "(27-15)"), ("Hayden", "(22-20)"), ("Benton", "(20-22)"), ("Garrett", "(15-27)"))]
    L.check_pre_era_careers(ss, lh, [], MGRS)                                 # no Yahoo season: the totals
    yahoo = [{"season": "2017-18", "manager": m, "reg_wins": 10, "reg_losses": 11} for m in MGRS]
    lh2 = [dict(x, regular_season_record=f"({int(x['regular_season_record'][1:3]) + 10}-"
                                         f"{int(x['regular_season_record'][4:6]) + 11})") for x in lh]
    L.check_pre_era_careers(ss, lh2, yahoo, MGRS)
    lh2[0]["regular_season_record"] = "(38-25)"
    with pytest.raises(L.LeagueError, match="Nick: the pre-Yahoo seasons say 27-15, LEAGUEHISTORY minus "
                                            "the Yahoo seasons says 28-14"):
        L.check_pre_era_careers(ss, lh2, yahoo, MGRS)


# --- the real league ---------------------------------------------------------------

def _real_inp():
    lh = pd.read_excel(ROOT / "data" / "LEAGUEHISTORY.xlsx")
    lh = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()}
          for r in lh.to_dict("records")]
    hist = ROOT / "data" / "historical"
    return {"managers": MGRS, "season": "2026-27", "reg_weeks": 15, "cup_winners": {},
            "season_structure": SEASON_STRUCTURE, "pre_data_era": _LEAGUE_CONFIG["pre_data_era"],
            "leaguehistory": lh, "all_standings": json.loads((hist / "all_standings.json").read_text("utf-8")),
            "all_teams": json.loads((hist / "all_teams.json").read_text("utf-8")), "season_teams": {}}


@pytest.mark.real
@needs_state("data/LEAGUEHISTORY.xlsx", "data/historical/all_standings.json",
             why="the careers check reads the real LEAGUEHISTORY")
def test_the_real_seasons_reconcile_with_leaguehistory_and_champions_shows_them():
    inp = _real_inp()
    L.check_pre_era_careers(L.pre_era_seasons(), inp["leaguehistory"], inp["all_standings"], MGRS)
    c = L.champions(inp)
    rows = {r["season"]: r for r in c["rows"]}
    a, b = rows["2014-15"], rows["2016-17"]
    assert (a["who"], a["team"]) == ("Nick", "Russell Eastbrook")
    assert a["lines"] == [{"k": "Runner-up", "t": "Benton (Serge I-Block-Ya)"},
                          {"k": "Playoff champion",
                           "t": "Nick (Russell Eastbrook), over Benton, 1,296.00–1,249.25"},
                          {"k": "Standings and brackets only", "t": "no weekly scores or stats"}]
    assert (b["who"], b["team"]) == ("Hayden", "Hayden's Rad Team")
    assert b["lines"][1]["t"] == "Benton (Serge I-Block-Ya), over Garrett, 1,499.50–1,168.00"
    assert "2015-16" not in rows and "2015-16 was not played" in c["note"]
    assert "records only" not in c["note"].lower()
