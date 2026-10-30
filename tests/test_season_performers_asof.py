"""Season performers AS OF week_end (HANDOFF_SEASON_PERFORMERS_ASOF_2026-10-30;
Nick's decisions of 10-30).

  points  Yahoo, the sum of each player's daily lines through week_end --
          never the season total (it runs through NOW, and carries stat
          corrections the daily lines and our weekly scores do not)
  ids     the league's rosters, never a name search
  games   basketball-reference game logs through week_end: GP, MPG, team per game
  FPPG    Yahoo points / bbref GP

An incomplete or failed section refuses the build unless
--allow-incomplete-season-performers, and the page then says so.

No network: Yahoo and basketball-reference are both faked here.
"""
import inspect
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import season_performers as sp   # noqa: E402

WEEK_END = "2026-10-25"
NOW = datetime(2026, 10, 30, 8, 0)


# --------------------------------------------------------------------- fakes

def line(pid, pts=None, zero=False):
    """A Yahoo daily line: pts -> played; zero -> DNP (all 0.0); neither ->
    his team did not play (every stat '-')."""
    cats = {c: "-" for c in sp.YAHOO_CATS}
    if zero:
        cats = {c: 0.0 for c in sp.YAHOO_CATS}
        pts = 0.0
    elif pts is not None:
        cats = {c: 0.0 for c in sp.YAHOO_CATS}
        cats["PTS"] = 10.0
    return {"player_id": pid, "name": "x", "position_type": "P", **cats,
            "total_points": pts if pts is not None else 0}


class League:
    """Yahoo, faked: the rosters, and a daily line per player per day."""

    def __init__(self, rosters, days, drop=()):
        self.rosters, self.days, self.drop = rosters, days, set(drop)
        self.asked = []

    def teams(self):
        return {k: {} for k in self.rosters}

    def to_team(self, k):
        roster = self.rosters[k]
        return type("T", (), {"roster": lambda s: roster})()

    def player_stats(self, ids, kind, date=None):
        assert kind == "date", "the season total must never be read"
        self.asked.append(date)
        d = date.isoformat()
        return [self.days.get(d, {}).get(pid, line(pid)) for pid in ids
                if (pid, d) not in self.drop]


def per_game(players):
    rows = "".join(
        f'<tr><th data-stat="ranker">1</th><td class="left " data-append-csv="{pid}" '
        f'data-stat="name_display" ><a href="/players/{pid[0]}/{pid}.html">{name}</a></td></tr>'
        for name, pid in players)
    return f"<html><table id='per_game_stats'>{rows}</table></html>"


def gamelog(games):
    """games: (date, team, seconds or None for Inactive)."""
    rows = []
    for d, team, secs in games:
        mp = (f'<td class="right " data-stat="mp" csk="{secs}" >{secs // 60}:{secs % 60:02d}</td>'
              if secs is not None else
              '<td class="center " data-stat="is_starter" colspan="1" >Inactive</td>')
        rows.append(f'<tr><th data-stat="ranker">1</th><td class="left " data-stat="date" >'
                    f'<a href="/boxscores/x.html">{d}</a></td><td class="left " '
                    f'data-stat="team_name_abbr" ><a href="/teams/{team}/2027.html">{team}</a></td>'
                    f'{mp}</tr>')
    return ('<html><table id="player_game_log_reg"><thead><tr><th>Date</th></tr></thead>'
            + "".join(rows) + '<tr><td data-stat="date"></td></tr></table></html>')


class Bbref:
    def __init__(self, this, last, logs, fail=()):
        self.pages = {sp.BBREF_PER_GAME.format(year=2027): per_game(this),
                      sp.BBREF_PER_GAME.format(year=2026): per_game(last)}
        for pid, games in logs.items():
            self.pages[sp.gamelog_url(pid)] = gamelog(games)
        self.fail = set(fail)
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        if url in self.fail or url not in self.pages:
            raise RuntimeError(f"HTTP 404 {url}")
        return self.pages[url]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Three rostered players over 10-20..10-26 (week 1 ends 10-25):
    Jokic (accents), Jimmy Butler (bbref has him as Butler III), Doncic."""
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config" / "ROSTERS.json").write_text(json.dumps(
        {"rosters": {"Nick": ["Nikola Jokic", "Jimmy Butler"], "Benton": ["Luka Doncic"]}}))
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps({"weeks": [
        {"week": 1, "start_date": "2026-10-20", "end_date": WEEK_END},
        {"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01"}]}))
    games = [("2026-10-20", "DEN", "GSW"), ("2026-10-22", "DEN", "LAL"), ("2026-10-23", "MIA", "DAL"),
             ("2026-10-24", "DEN", "MIA"), ("2026-10-25", "DAL", "PHX"), ("2026-10-26", "DEN", "DAL")]
    (tmp_path / "sched.json").write_text(json.dumps({"games": [
        {"date": f"{d}T00:00:00Z", "home": h, "away": a} for d, h, a in games]}))
    monkeypatch.setattr(sp, "NBA_SCHEDULE_FILE", "sched.json")
    pd.DataFrame([
        {"player_name": "Nikola Jokić", "projectedFPPG": 60.0, "player_total_proj_FP": 4000.0,
         "player_nba_team": "DEN"},
        {"player_name": "Jimmy Butler", "projectedFPPG": 30.0, "player_total_proj_FP": 2000.0,
         "player_nba_team": "MIA"},
        {"player_name": "Luka Dončić", "projectedFPPG": 55.0, "player_total_proj_FP": 3800.0,
         "player_nba_team": "DAL"},
    ]).to_excel(tmp_path / "data" / "PLAYERLIST.xlsx", index=False)
    rosters = {"t1": [{"player_id": 1, "name": "Nikola Jokić"}, {"player_id": 2, "name": "Jimmy Butler"}],
               "t2": [{"player_id": 3, "name": "Luka Dončić"}]}
    days = {
        "2026-10-20": {1: line(1, 50.25)},
        "2026-10-22": {1: line(1, 40.5)},
        "2026-10-23": {2: line(2, 20.1), 3: line(3, 61.35)},
        "2026-10-24": {1: line(1, 33.33), 2: line(2, 18.0)},
        "2026-10-25": {3: line(3, 44.4)},
        "2026-10-26": {1: line(1, 99.0), 3: line(3, 77.0)},     # after week_end
    }
    this = [("Nikola Jokić", "jokicni01"), ("Jimmy Butler III", "butleji01"),
            ("Luka Dončić", "doncilu01")]
    logs = {"jokicni01": [("2026-10-20", "DEN", 2119), ("2026-10-22", "DEN", 2400),
                          ("2026-10-24", "DEN", 1800), ("2026-10-26", "DEN", 2000)],
            "butleji01": [("2026-10-23", "MIA", 1500), ("2026-10-24", "MIA", 2100)],
            "doncilu01": [("2026-10-23", "DAL", 2200), ("2026-10-25", "DAL", 2300),
                          ("2026-10-26", "DAL", 2000)]}
    return {"base": tmp_path, "rosters": rosters, "days": days, "this": this,
            "last": [("Somebody Else", "elseso01")],
            "logs": logs}


def run(w, week=1, league=None, bbref=None, **kw):
    lg = league or League(w["rosters"], w["days"])
    bb = bbref or Bbref(w["this"], w["last"], w["logs"])
    out = sp.generate_season_performers_data(week, w["base"], lg=lg, bbref_fetch=bb, now=NOW, **kw)
    return out, lg, bb


def row(out, name):
    for t in ("best_total_fp", "worst_total_fp"):
        for r in out[t]:
            if r["player_name"] == name:
                return r
    raise KeyError(name)


# ------------------------------------------------------------------- points

def test_a_line_after_week_end_never_reaches_total_fp(world):
    out, lg, _ = run(world)
    assert out["status"]["complete"], sp.problems_of(out["status"])
    jok = row(out, "Nikola Jokic")
    assert jok["total_fp"] == round(50.25 + 40.5 + 33.33, 1)          # not + 99.0 on 10-26
    assert row(out, "Luka Doncic")["total_fp"] == round(61.35 + 44.4, 1)
    assert max(lg.asked) == date(2026, 10, 25)                         # never asked past week_end
    assert min(lg.asked) == date(2026, 10, 20)                         # from the first game day
    assert out["status"]["as_of"] == WEEK_END


def test_the_sum_is_exact_on_a_constructed_season(world):
    pts, lg = sp.yahoo_daily_points(League(world["rosters"], world["days"]),
                                    {"a": 1, "b": 2, "c": 3}, date(2026, 10, 20), date(2026, 10, 26))
    assert pts["a"]["points"] == round(50.25 + 40.5 + 33.33 + 99.0, 2)
    assert pts["b"]["points"] == round(20.1 + 18.0, 2)
    assert pts["c"]["points"] == round(61.35 + 44.4 + 77.0, 2)
    assert pts["a"]["played"] == ["2026-10-20", "2026-10-22", "2026-10-24", "2026-10-26"]
    out, _, _ = run(world)
    jok = row(out, "Nikola Jokic")
    assert jok["gp"] == 3 and jok["fppg"] == round((50.25 + 40.5 + 33.33) / 3, 2)
    assert jok["mpg"] == round((2119 + 2400 + 1800) / 3 / 60, 1)


def test_ids_come_from_the_league_rosters_with_accents_matched(world):
    ids, failures = sp.roster_player_ids(League(world["rosters"], {}),
                                         {"Nick": ["Nikola Jokic", "Jimmy Butler"],
                                          "Benton": ["Luka Doncic", "Nobody Here"]})
    assert ids == {"Nikola Jokic": 1, "Jimmy Butler": 2, "Luka Doncic": 3}
    assert failures == ["Nobody Here (Benton): not on any Yahoo roster in the league"]


def test_a_missing_yahoo_line_is_a_failure_not_a_zero(world):
    lg = League(world["rosters"], world["days"], drop={(2, "2026-10-23")})
    out, _, _ = run(world, league=lg)
    st = out["status"]
    assert not st["complete"] and st["failed"] == 3
    assert any("no 2026-10-23 line" in f for f in st["failures"])
    with pytest.raises(sp.SeasonPerformersIncomplete):
        _strict(world, league=lg)


# -------------------------------------------------------------- the refusal

def _strict(w, allow=False, league=None, bbref=None):
    lg = league or League(w["rosters"], w["days"])
    bb = bbref or Bbref(w["this"], w["last"], w["logs"])
    return sp.build_season_performers(w["base"], 1, allow_incomplete=allow, lg=lg,
                                      bbref_fetch=bb, now=NOW)


def test_a_failed_lookup_is_counted_surfaced_and_refused(world):
    world["rosters"]["t2"] = []                        # Doncic is not on a Yahoo roster
    out, _, _ = run(world)
    st = out["status"]
    assert st["failed"] == 1 and st["counted"] == 2 and not st["complete"]
    assert "Luka Doncic (Benton): not on any Yahoo roster in the league" in st["failures"]
    assert "Luka Doncic" not in [r["player_name"] for r in out["best_total_fp"]]
    with pytest.raises(sp.SeasonPerformersIncomplete) as e:
        _strict(world)
    assert "2/3 players counted" in str(e.value) and "Luka Doncic" in str(e.value)
    assert e.value.status["failed"] == 1
    # the override: built, recorded, and the page says so
    got = _strict(world, allow=True)
    assert got["status"]["override"] == "--allow-incomplete-season-performers"
    note = sp.incomplete_note(got)
    assert "1 of 3 rostered players are missing" in note and WEEK_END in note


def test_a_complete_section_carries_no_override_and_no_note(world):
    got = _strict(world)
    assert got["status"]["complete"] and got["status"]["override"] is None
    assert sp.incomplete_note(got) is None


def test_a_bbref_fetch_failure_refuses(world):
    bb = Bbref(world["this"], world["last"], world["logs"],
               fail={sp.gamelog_url("butleji01")})
    with pytest.raises(sp.SeasonPerformersIncomplete) as e:
        _strict(world, bbref=bb)
    assert "Jimmy Butler: basketball-reference game log" in str(e.value)
    bb = Bbref(world["this"], world["last"], world["logs"],
               fail={sp.BBREF_PER_GAME.format(year=2027)})
    with pytest.raises(sp.SeasonPerformersIncomplete) as e:
        _strict(world, bbref=bb)
    assert "0/3 players counted" in str(e.value)


def test_an_unmatched_bbref_name_is_a_failure_never_a_skip(world):
    world["this"] = [t for t in world["this"] if t[1] != "doncilu01"]
    with pytest.raises(sp.SeasonPerformersIncomplete) as e:
        _strict(world)
    assert "Luka Doncic: not on basketball-reference's per-game page" in str(e.value)


def test_last_seasons_page_finds_a_player_with_no_games_yet(world):
    world["this"] = [t for t in world["this"] if t[1] != "doncilu01"]
    world["last"] = [("Somebody Else", "elseso01"), ("Luka Dončić", "doncilu01")]
    assert _strict(world)["status"]["complete"]


def test_a_failure_in_the_section_is_never_swallowed_to_none(world, monkeypatch):
    def boom(*a, **k):
        raise ValueError("schedule unreadable")
    monkeypatch.setattr(sp, "generate_season_performers_data", boom)
    with pytest.raises(sp.SeasonPerformersIncomplete) as e:
        sp.build_season_performers(world["base"], 1)
    assert "schedule unreadable" in str(e.value)
    got = sp.build_season_performers(world["base"], 1, allow_incomplete=True)
    assert got["status"]["ran"] is False and got["best_total_fp"] == []
    assert "could not be built" in sp.incomplete_note(got)


# --------------------------------------------------------- bbref game logs

def test_the_game_log_parses_appearances_teams_and_minutes():
    g = sp.parse_gamelog(gamelog([("2026-10-21", "BRK", 1830), ("2026-10-23", "CHO", None),
                                  ("2026-10-25", "PHO", 0)]))
    assert g == [{"date": "2026-10-21", "team": "BKN", "appeared": True, "minutes": 30.5},
                 {"date": "2026-10-23", "team": "CHA", "appeared": False, "minutes": None},
                 {"date": "2026-10-25", "team": "PHX", "appeared": True, "minutes": 0.0}]
    with pytest.raises(sp.SourceError):
        sp.parse_gamelog("<html>no table</html>")


def test_bbref_names_match_accents_and_suffixes():
    page = sp.parse_bbref_ids(per_game([("Nikola Jokić", "jokicni01"),
                                        ("Jimmy Butler III", "butleji01"),
                                        ("Alperen Şengün", "sengual01")]))
    ids, failures = sp.bbref_ids_for(["Nikola Jokic", "Jimmy Butler", "Alperen Sengun"], [page])
    assert ids == {"Nikola Jokic": "jokicni01", "Jimmy Butler": "butleji01",
                   "Alperen Sengun": "sengual01"} and failures == []


def test_a_traded_player_counts_each_teams_games():
    team_games = {"DEN": 3, "MIA": 2}
    per_team = {"DEN": 2, "MIA": 2}
    assert sp.calculate_gp_pct_with_trades(per_team, team_games) == pytest.approx(80.0)


# -------------------------------------------------------------- cross-check

def test_a_zero_stat_appearance_is_a_game_and_a_listed_cameo(world):
    world["days"]["2026-10-25"][1] = line(1, zero=True)
    world["logs"]["jokicni01"].insert(3, ("2026-10-25", "DEN", 60))
    out, _, _ = run(world)
    st = out["status"]
    assert st["complete"] and st["cameos"] == {"Nikola Jokic": ["2026-10-25"]}
    assert row(out, "Nikola Jokic")["gp"] == 4


def test_played_day_disagreements_are_findings_and_refuse(world):
    world["days"]["2026-10-22"][2] = line(2, 12.0)       # Yahoo: Butler played 10-22
    out, _, _ = run(world)
    assert out["status"]["findings"] == {
        "Jimmy Butler": ["Yahoo has stats on 2026-10-22; basketball-reference has no appearance"]}
    assert not out["status"]["complete"]
    with pytest.raises(sp.SeasonPerformersIncomplete):
        _strict(world)


def test_a_bbref_appearance_yahoo_never_saw_is_a_finding():
    c, f = sp.cross_check({"played": [], "zero_lines": []},
                          [{"date": "2026-10-22", "team": "DEN", "appeared": True, "minutes": 3.0}])
    assert c == [] and f == ["basketball-reference has an appearance on 2026-10-22; Yahoo has no line"]


# ----------------------------------------------------- wiring and the page

def test_stats_nba_com_and_the_name_search_are_gone():
    src = (ROOT / "modules" / "season_performers.py").read_text(encoding="utf-8")
    for gone in ("nba_api", "NBA_API", "player_details", "search_player", "results[0]",
                 "'season'", "data/.cache"):
        assert gone not in src, gone


def test_step_6_refuses_before_the_build_and_records_the_override():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert '"--allow-incomplete-season-performers"' in src
    fetch = src.index("build_season_performers(\n            base_path, week, "
                      "allow_incomplete=args.allow_incomplete_season_performers)")
    refuse = src.index("except SeasonPerformersIncomplete as e:", fetch)
    assert src.index('print(f"REFUSED: {e}")', refuse) < src.index("sys.exit(1)", refuse)
    assert refuse < src.index('print("Building stats report...")')
    assert "season_performers=season_performers," in src
    assert '"season_performers_override": sp_override,' in src
    rb = (ROOT / "modules" / "report_builder.py").read_text(encoding="utf-8")
    assert '"season_performers": _sp_status,' in rb
    assert "build_season_performers(data.base_path, week)" in rb   # strict for other callers


def test_an_incomplete_section_is_said_in_the_stats_report_and_on_the_page(world):
    got = sp.build_season_performers(
        world["base"], 1, allow_incomplete=True,
        lg=League({"t1": world["rosters"]["t1"], "t2": []}, world["days"]),
        bbref_fetch=Bbref(world["this"], world["last"], world["logs"]), now=NOW)
    import format_stats_report as fsr
    text = fsr.format_section_8_stats_corner({"season_performers": got}, {})
    assert f"Season tables are through {WEEK_END}" in text
    assert "**NOTE -- The season tables through 2026-10-25 are incomplete: 1 of 3" in text
    gen = (ROOT / "scripts" / "newsletter_html_generator.py").read_text(encoding="utf-8")
    assert '_sp_banner = _sp_note((stats_report or {}).get("season_performers"))' in gen
    assert "content_html = f'{_sp_banner}<div class=\"sc-tables-section\">" in gen
