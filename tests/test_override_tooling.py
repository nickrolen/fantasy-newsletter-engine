"""Overrides that are easy to write and hard to get wrong, and tags for
everyone (HANDOFF_OVERRIDE_TOOLING_2026-10-28).

THE POLICY: the overrides file describes injuries, not rosters
(STATUS_2026-10-28). scripts/overrides.py writes and checks entries;
modules/injury_entries.py computes and checks them; modules/nba_reference.py
says who is an NBA player; free agents carry Yahoo tags (Tags.free_agents)
and the roster plan refuses an untagged one.
"""
import importlib
import importlib.util
import json
import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from modules import absence
from modules import injury_entries as ie
from modules import nba_reference as nr
from modules import roster_plan as rp
from modules.data_loader import MANAGERS, PlayerIndex
from modules.projections import PlayerProjection

ROOT = Path(__file__).parent.parent
fis = importlib.import_module("modules.fetch_injury_statuses")


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ov = _script("overrides")
SCHEDULE = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))


def _games(*days):
    return {"games": [{"date": f"{d}T00:00:00Z", "home": "AAA", "away": "ZZZ"} for d in days]}


# Team AAA: week 5 (Mon 11-16 .. Sun 11-22) plays Mon, Wed, Fri; week 7 (14 days,
# 11-30 .. 12-13) plays 12-01, 12-05, 12-08, 12-12; week 22 three games.
AAA = ie.team_games(_games("2026-11-16", "2026-11-18", "2026-11-20",
                           "2026-12-01", "2026-12-05", "2026-12-08", "2026-12-12",
                           "2027-03-29", "2027-03-31", "2027-04-02"))


# 1 -- what add computes
@pytest.mark.parametrize("back,week,games,total,out_weeks", [
    ("2026-11-17", 5, 2, 3, [3, 4]),         # a Tuesday return: Monday's game missed
    ("2026-11-16", 5, 3, 3, [3, 4]),         # a Monday return: the whole week
    ("2026-12-07", 7, 2, 4, [3, 4, 5, 6]),   # inside week 7, 14 days: one week, its last 2 games
])
def test_add_computes_the_schedule_fields(back, week, games, total, out_weeks):
    entry, _ = ie.compute("Somebody", "AAA", date(2026, 11, 3), date.fromisoformat(back), False,
                          SCHEDULE, AAA)
    assert entry["out_weeks"] == out_weeks and entry["return_week"] == week
    assert (entry["return_games"], entry["total_week_games"]) == (games, total)
    assert entry["return_date"] == back and entry["nba_team"] == "AAA"


def test_season_is_out_through_the_last_fantasy_week_with_no_return():
    """Nick, 10-28: --season is out for the rest of the season. Williams and
    Wallace are NOT this -- they are back for the Cup, an ordinary --back."""
    entry, said = ie.compute("Somebody", "AAA", date(2026, 11, 3), None, True, SCHEDULE, AAA)
    assert entry["out_weeks"] == list(range(3, 24))
    for k in ("return_week", "return_date", "return_games", "total_week_games"):
        assert k not in entry
    assert "last fantasy week" in said[0]
    back, _ = ie.compute("Jalen Williams", "AAA", date(2026, 10, 20), date(2027, 3, 29), False,
                         SCHEDULE, AAA)
    assert back["out_weeks"] == list(range(1, 22)) and back["return_week"] == 22


def test_an_entry_with_no_return_is_accepted_everywhere(tmp_path):
    """Shape checks, the absence code and the OFS backstop all take an entry
    with out_weeks and no return; a rostered OFS tag raises no conflict."""
    p = _project(tmp_path)
    assert _add(p, "Alpha Player", back=None, season=True, notes="season") == 0
    entry = json.loads((p / "config" / "INJURY_OVERRIDES.json").read_text())["players"][-1]
    assert entry["out_weeks"] == list(range(3, 24)) and "return_week" not in entry
    assert ie.shape_problems(entry, SCHEDULE, AAA, date(2026, 10, 28)) == ([], [])
    absence.check_season_out_override("Alpha Player", "OFS", entry.get("return_week"),
                                      entry.get("return_date"), entry.get("return_games"))
    proj = PlayerProjection(player_name="Alpha Player", nba_team="AAA", positions=["PG"],
                            projected_fppg=30.0, projected_gp=70.0, out_weeks=entry["out_weeks"])
    assert absence.season_out_conflicts({"Alpha Player": "OFS"}, {"Alpha Player": proj}) == []
    week_dates = {w: [s + timedelta(days=i) for i in range((e - s).days + 1)]
                  for w, s, e in ie.fantasy_weeks(SCHEDULE)}
    governed, missed = absence.override_absence(week_dates, AAA["AAA"], date(2026, 11, 2),
                                                entry["out_weeks"], player="Alpha Player")
    assert governed == missed == len([d for d in AAA["AAA"] if d >= date(2026, 11, 2)])
    from modules import simulator_betting as sb
    assert not sb._eligible(proj, 22, date(2027, 3, 29), date(2027, 3, 29))


def test_an_out_before_week_1_starts_at_week_1_and_says_so():
    entry, said = ie.compute("Somebody", "AAA", date(2026, 9, 1), date(2026, 11, 16), False,
                             SCHEDULE, AAA)
    assert entry["out_weeks"] == [1, 2, 3, 4] and "before week 1" in said[0]


# a small project: the real schedule, a two-team NBA schedule, a reference
def _project(tmp_path, overrides=None, playerlist=None, rosters=None, il=None):
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHEDULE))
    games = _games("2026-11-16", "2026-11-18", "2026-11-20", "2027-03-29", "2027-03-31")
    games["games"].append({"date": "2026-11-17T00:00:00Z", "home": "BBB", "away": "ZZZ"})
    (tmp_path / "data" / "nba_schedule_2026-27.json").write_text(json.dumps(games))
    (tmp_path / "data" / "NBA_PLAYER_REFERENCE.json").write_text(json.dumps({
        "fetched_at": "2026-10-28T00:00:00+00:00",
        "seasons": {"this_season": {"players": {"Alpha Player": "AAA", "Gamma Guy": None}},
                    "last_completed": {"players": {"Beta Player": "BBB"}}}}))
    pd.DataFrame(playerlist or {"player_name": ["Alpha Player"], "player_nba_team": ["AAA"],
                                "projectedFPPG": [30.0]}).to_excel(
        tmp_path / "data" / "PLAYERLIST.xlsx", index=False)
    (tmp_path / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": rosters or {}}))
    blob = overrides if overrides is not None else {
        "players": [{"player_name": "Zed Existing", "out_weeks": [1], "notes": "keep me",
                     "custom_key": [1, 2]}],
        "last_updated": "2026-10-20", "_comment": "kept"}
    (tmp_path / "config" / "INJURY_OVERRIDES.json").write_text(json.dumps(blob, indent=2))
    if il is not None:
        (tmp_path / "data" / "IL_SLOTS.json").write_text(json.dumps(il))
    return tmp_path


def _add(tmp_path, name, out="2026-11-02", back="2026-11-17", yes=True, today=date(2026, 10, 28),
         answer="y", **kw):
    a = SimpleNamespace(name=name, out=out, back=back, season=kw.get("season", False),
                        team=kw.get("team"), notes=kw.get("notes"), return_notes=None,
                        replace=kw.get("replace", False), yes=yes)
    return ov.cmd_add(a, tmp_path, today=today, ask=lambda _q: answer)


# 2 -- what add refuses, each with a message
@pytest.mark.parametrize("name,kw,needle", [
    ("Alpha Playr", {}, "did you mean 'Alpha Player'"),
    ("Qqq Zzz", {}, "matches no NBA player"),
    ("Alpha Player", {"back": "2026-10-27"}, "in the past"),
    ("Alpha Player", {"back": "2025-11-17"}, "Did you mean 2026-11-17?"),
    ("Alpha Player", {"back": "2027-05-01"}, "outside the 2026-27 fantasy season"),
    ("Alpha Player", {"out": "2026-11-20", "back": "2026-11-18"}, "not after --out"),
    ("Gamma Guy", {}, "pass --team"),
    ("Gamma Guy", {"team": "XYZ"}, "not a team in the NBA schedule"),
    ("Zed Existing", {"team": "AAA"}, "--replace"),
])
def test_add_refuses_with_a_message(tmp_path, capsys, name, kw, needle):
    p = _project(tmp_path)
    if name == "Zed Existing":
        ref = json.loads((p / "data" / "NBA_PLAYER_REFERENCE.json").read_text())
        ref["seasons"]["this_season"]["players"]["Zed Existing"] = "AAA"
        (p / "data" / "NBA_PLAYER_REFERENCE.json").write_text(json.dumps(ref))
    before = (p / "config" / "INJURY_OVERRIDES.json").read_bytes()
    assert _add(p, name, **kw) == 2
    assert needle in capsys.readouterr().out
    assert (p / "config" / "INJURY_OVERRIDES.json").read_bytes() == before


def test_a_missing_reference_refuses_add(tmp_path, capsys):
    p = _project(tmp_path)
    (p / "data" / "NBA_PLAYER_REFERENCE.json").unlink()
    assert _add(p, "Alpha Player") == 2
    assert "refresh-reference" in capsys.readouterr().out


# 3 -- every other entry and key untouched; --replace to overwrite; y/n
def test_add_preserves_everything_else_byte_for_byte(tmp_path):
    p = _project(tmp_path)
    path = p / "config" / "INJURY_OVERRIDES.json"
    original = json.loads(path.read_text())
    from modules.data_loader import atomic_write_json
    atomic_write_json(path, original)                         # the file as the tool writes it
    before = path.read_bytes()
    assert _add(p, "Alpha Player", notes="hamstring") == 0
    after = json.loads(path.read_text())
    assert after["last_updated"] == "2026-10-28"
    new = after["players"].pop()
    assert new == {"player_name": "Alpha Player", "nba_team": "AAA", "out_weeks": [3, 4],
                   "notes": "hamstring", "return_week": 5, "return_games": 2,
                   "total_week_games": 3, "return_date": "2026-11-17"}
    after["last_updated"] = original["last_updated"]
    # written by the same writer, so the platform's newline is the same on
    # both sides (Windows text mode writes CRLF; a plain json.dumps never does)
    again = p / "config" / "rewritten.json"
    atomic_write_json(again, after)
    assert again.read_bytes() == before
    # --replace overwrites in place; without it, refused
    assert _add(p, "Alpha Player", back="2026-11-16") == 2
    assert _add(p, "Alpha Player", back="2026-11-16", replace=True) == 0
    players = json.loads(path.read_text())["players"]
    assert [e["player_name"] for e in players] == ["Zed Existing", "Alpha Player"]
    assert players[1]["return_games"] == 3


def test_add_asks_and_no_means_nothing_written(tmp_path, capsys):
    p = _project(tmp_path)
    before = (p / "config" / "INJURY_OVERRIDES.json").read_bytes()
    assert _add(p, "Alpha Player", yes=False, answer="n") == 2
    out = capsys.readouterr().out
    assert '"return_week": 5' in out and "Not written" in out
    assert (p / "config" / "INJURY_OVERRIDES.json").read_bytes() == before


def test_the_team_comes_from_last_season_only_with_a_warning(tmp_path, capsys):
    p = _project(tmp_path)
    assert _add(p, "Beta Player", back="2026-11-18", yes=False, answer="n") == 2
    assert "LAST season -- confirm" in capsys.readouterr().out


# 4 -- Nick's fourteen hand-written entries, recomputed
def test_nicks_entries_recompute_exactly():
    blob = json.loads((ROOT / "config" / "INJURY_OVERRIDES.json").read_text(encoding="utf-8"))
    games = ie.team_games(json.loads((ROOT / "data" / "nba_schedule_2026-27.json").read_text()))
    mismatches = []
    for e in blob["players"]:
        assert e.get("nba_team"), f"{e['player_name']}: no nba_team (backfilled 10-28)"
        out = ie.week_bounds(SCHEDULE, e["out_weeks"][0])[0]
        got, _ = ie.compute(e["player_name"], e["nba_team"], out,
                            date.fromisoformat(e["return_date"]), False, SCHEDULE, games)
        for k in ("out_weeks", "return_week", "return_games", "total_week_games"):
            if got[k] != e[k]:
                mismatches.append(f"{e['player_name']} {k}: file {e[k]}, computed {got[k]}")
    assert len(blob["players"]) >= 14
    assert not mismatches, mismatches


# 5 -- check: four lists, read-only, exit codes
def test_check_lists_all_four_never_writes_and_exits_as_specified(tmp_path):
    p = _project(tmp_path, overrides={"players": [
        {"player_name": "Alpha Player", "out_weeks": [1], "return_week": 2,
         "return_date": "2026-10-26"},
        {"player_name": "Nobody Atall", "out_weeks": [3]}], "last_updated": "2026-10-28"},
        playerlist={"player_name": ["Alpha Player", "Free Hurt", "Free Healthy"],
                    "player_nba_team": ["AAA", "AAA", "AAA"], "projectedFPPG": [30.0, 25.0, 20.0]},
        rosters={"Nick": ["Alpha Player", "Rostered Hurt"]},
        il={"fantasy_week": 2, "slots": {"Nick": ["Rostered Hurt"]}})
    tags = fis.Tags({"Alpha Player": "O", "Rostered Hurt": "O"},
                    {"Free Hurt": "OFS", "Free Healthy": "HEALTHY"})
    files = {f: f.read_bytes() for f in p.rglob("*") if f.is_file()}
    lists = ov.check_lists(p, tags, today=date(2026, 10, 28))
    assert lists["tagged"][0].startswith("Rostered Hurt (O, rostered")     # rostered first
    assert lists["tagged"][1].startswith("Free Hurt (OFS, free agent")
    assert len(lists["tagged"]) == 2                                       # Alpha is covered
    assert lists["il"] == ["Rostered Hurt (Nick's IL slot, fantasy week 2)"]
    assert lists["passed"] == ["Alpha Player (return_date 2026-10-26)"]
    assert "Nobody Atall" in lists["unknown"][0]
    assert ov.render_check(lists)[1] == 1
    assert {f: f.read_bytes() for f in p.rglob("*") if f.is_file()} == files
    # lists 1 and 2 are review lists (Nick, 10-28): only 3 and 4 fail
    assert ov.render_check(dict(lists, passed=[], unknown=[]))[1] == 0
    assert ov.render_check(dict(lists, unknown=[]))[1] == 1
    assert ov.render_check(dict(lists, passed=[]))[1] == 1


# 6 -- the reference
def test_the_reference_resolves_the_three_and_refuses_the_rest(tmp_path):
    if not (ROOT / nr.CACHE).is_file():
        pytest.skip(f"no {nr.CACHE}: run {nr.REFRESH_COMMAND}")
    ref = nr.Reference(ROOT)
    for name in ("Jimmy Butler III", "Jalen Williams", "Cason Wallace"):
        assert ref.resolve(name) is not None, name
    assert ref.resolve("Bartholomew Zzyzx") is None
    assert "nothing is close" in ref.unknown_message("Bartholomew Zzyzx")
    assert "did you mean 'Cason Wallace'" in ref.unknown_message("Cason Walace")
    with pytest.raises(nr.ReferenceMissing, match="refresh-reference"):
        nr.Reference(tmp_path)


def test_a_failed_refresh_raises_and_keeps_the_old_cache(tmp_path):
    (tmp_path / "data").mkdir()
    old = {"fetched_at": "old", "seasons": {}}
    (tmp_path / nr.CACHE).write_text(json.dumps(old))

    def boom(year):
        raise OSError("no network")
    with pytest.raises(nr.ReferenceFetchError, match="NOT changed"):
        nr.refresh(tmp_path, fetch=boom)
    with pytest.raises(nr.ReferenceFetchError, match="no players"):
        nr.refresh(tmp_path, fetch=lambda year: "<html></html>")
    assert json.loads((tmp_path / nr.CACHE).read_text()) == old


def test_the_page_parser_maps_team_codes_and_takes_the_last_team():
    row = ('<tr><td data-stat="name_display"><a href="x">{n}</a></td>'
           '<td data-stat="team_name_abbr"><a>{t}</a></td></tr>')
    doc = "".join(row.format(n=n, t=t) for n, t in
                  (("Player", "Team"), ("A One", "BRK"), ("B Two", "2TM"), ("B Two", "PHO"),
                   ("B Two", "CHO")))
    assert nr.parse_per_game(doc) == [("A One", "BKN"), ("B Two", None), ("B Two", "PHX"),
                                      ("B Two", "CHA")]


# 7 -- integrity: green today; each shape assertion fails a broken entry
def test_integrity_is_green_on_todays_file():
    vpi = _script("verify_project_integrity")
    if not (ROOT / nr.CACHE).is_file():
        pytest.skip(f"no {nr.CACHE}")
    blob = json.loads((ROOT / "config" / "INJURY_OVERRIDES.json").read_text(encoding="utf-8"))
    warnings = []
    assert vpi._check_override_entries(blob, warnings, date(2026, 10, 28)) == []
    assert any("inert until they reappear" in w for w in warnings)
    src = (ROOT / "scripts" / "verify_project_integrity.py").read_text(encoding="utf-8")
    assert "Remove the entry" not in src and "Cason Wallace 10-27" not in src


GOOD = {"player_name": "X", "nba_team": "AAA", "out_weeks": [3, 4], "return_week": 5,
        "return_games": 2, "total_week_games": 3, "return_date": "2026-11-17"}


@pytest.mark.parametrize("change,needle,kind", [
    ({}, None, None),
    ({"out_weeks": [2, 4]}, "not contiguous", "fail"),
    ({"return_week": 6, "return_date": "2026-11-24"}, "not one after", "fail"),
    ({"return_date": "2026-11-31"}, "is not YYYY-MM-DD", "fail"),
    ({"return_date": "2026-11-25"}, "not inside return_week", "fail"),
    ({"total_week_games": 4}, "total_week_games 4 but AAA plays 3", "fail"),
    ({"return_games": 3}, "return_games 3 but AAA plays 2", "fail"),
    ({"nba_team": None}, "UNVERIFIED", "warn"),
    ({"nba_team": "QQQ"}, "has no games", "fail"),
])
def test_each_shape_assertion(change, needle, kind):
    entry = {**GOOD, **change}
    fail, warn = ie.shape_problems(entry, SCHEDULE, AAA, date(2026, 10, 28))
    if needle is None:
        assert fail == [] and warn == []
    else:
        assert any(needle in x for x in (fail if kind == "fail" else warn)), (fail, warn)
        if kind == "warn":
            assert fail == []


def test_a_passed_return_is_a_warning_not_a_failure():
    fail, warn = ie.shape_problems(GOOD, SCHEDULE, AAA, date(2026, 11, 30))
    assert fail == [] and any("has passed" in w for w in warn)


# 8 -- one parser for return_date, raising with the name, at all five sites
def _bad(name="Bad Date"):
    return PlayerProjection(player_name=name, nba_team="AAA", positions=["PG"],
                            projected_fppg=30.0, projected_gp=70.0, out_weeks=[3],
                            return_week=4, return_date="2026-11-31")


def test_parse_return_date():
    assert absence.parse_return_date("2026-11-17") == date(2026, 11, 17)
    assert absence.parse_return_date("2026-11-17T00:00:00Z") == date(2026, 11, 17)
    assert absence.parse_return_date(None) is None
    with pytest.raises(ValueError, match="Bad Date"):
        absence.parse_return_date("11/17/2026", "Bad Date")


def test_every_site_raises_naming_the_player():
    from modules import simulator_betting as sb, schedule_strength as ss_, marginal_value as mv
    with pytest.raises(ValueError, match="Bad Date"):                   # absence
        absence.override_absence({4: [date(2026, 11, 9)]}, [], date(2026, 11, 2), [3], 4,
                                 "2026-11-31", player="Bad Date")
    with pytest.raises(ValueError, match="Bad Date"):                   # simulator_betting
        sb._eligible(_bad(), 4, date(2026, 11, 9), date(2026, 11, 9))
    with pytest.raises(ValueError, match="Bad Date"):                   # roster_plan
        rp._return_date(_bad())
    with pytest.raises(ValueError, match="Bad Date"):                   # schedule_strength
        ss_._build_for_week_with_lineups(
            4, SCHEDULE["weeks"], {"games": []}, {}, {},
            {"players": [{"player_name": "Bad Date", "return_week": 4,
                          "return_date": "2026-11-31"}]})
    with pytest.raises(ValueError, match="Bad Date"):                   # marginal_value
        mv.build_context({"Bad Date": _bad()}, {"Nick": ["Bad Date"]}, {"games": []},
                         SCHEDULE["weeks"], "week", 3, injury_statuses={"Bad Date": "HEALTHY"})


def test_no_silent_ignore_around_a_return_date_remains():
    pat = re.compile(r"except ValueError:\s*\n\s*pass")
    for path in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        if "return_date" in src:
            assert not pat.search(src), path.name


# 9 -- free agents' tags
def test_tags_keep_the_two_populations_apart():
    t = fis.Tags({"Rostered": "O"}, {"Free": "OFS"})
    assert dict(t) == {"Rostered": "O"} and "Free" not in t
    assert dict(t.free_agents) == {"Free": "OFS"}
    back = fis.Tags.from_json(json.loads(json.dumps(t.to_json())))
    assert dict(back) == dict(t) and dict(back.free_agents) == dict(t.free_agents)
    assert fis.Tags.from_json({"Rostered": "O"}).free_agents is None      # a pre-10-28 file
    assert getattr(dict(t), "free_agents", None) is None                   # a copy loses them


class _League:
    def __init__(self, available):
        self.available = available

    def free_agents(self, position):
        assert position == "P"
        return [{"name": n, "status": s} for n, s in self.available.items()]


def test_every_playerlist_free_agent_gets_a_tag_or_the_fetch_raises():
    lg = _League({"Nikola Jokić": "", "Free Hurt": "O", "Out Forever": "OFS"})
    got = fis.fetch_free_agent_tags(lg, ["Nikola Jokic", "Free Hurt", "Out Forever"])
    assert dict(got) == {"Nikola Jokic": "HEALTHY", "Free Hurt": "O", "Out Forever": "OFS"}
    with pytest.raises(fis.InjuryFetchError, match="Not Listed"):
        fis.fetch_free_agent_tags(lg, ["Free Hurt", "Not Listed"])


def test_the_real_free_agent_list_is_playerlist_minus_the_rosters():
    names = fis.playerlist_free_agents(ROOT)
    rostered = PlayerIndex({n: n for v in json.loads(
        (ROOT / "config" / "ROSTERS.json").read_text(encoding="utf-8"))["rosters"].values()
        for n in v})
    assert names and all(rostered.canonical(n) is None for n in names)


def _pool_world():
    players = {f"{m}_{j}": PlayerProjection(player_name=f"{m}_{j}", nba_team="AAA",
                                            positions=["PG"], projected_fppg=40.0 - j,
                                            projected_gp=70.0)
               for m in MANAGERS for j in range(15)}
    rosters = {m: [f"{m}_{j}" for j in range(15)] for m in MANAGERS}
    for j in range(6):
        players[f"FA_{j}"] = PlayerProjection(player_name=f"FA_{j}", nba_team="AAA",
                                              positions=["PG"], projected_fppg=30.0 - j,
                                              projected_gp=70.0)
    players["Nick_0"].out_weeks, players["Nick_0"].return_date = [3], "2026-11-09"
    return players, rosters


def _plan(players, rosters, statuses, assume=False):
    windows = [(3, date(2026, 11, 2)), (4, date(2026, 11, 9))]
    return rp.build(start_week=2, il_slots={}, rosters=rosters, windows=windows,
                    players=PlayerIndex(players), statuses=statuses,
                    rules={"active_spots": 15, "il_slots": 2, "add_budget": 3,
                           "il_eligible_tags": {"O", "OFS"}, "replacement_rank": 4},
                    standin_gp=69.0, assume_healthy=assume)


def test_the_plan_raises_on_an_untagged_pool_player_and_ofs_never_sets_the_level():
    players, rosters = _pool_world()
    tags = {n: "HEALTHY" for n in players}
    del tags["FA_2"]
    with pytest.raises(rp.UntaggedPoolPlayer, match="FA_2"):
        _plan(players, rosters, tags)
    assert _plan(players, rosters, {}, assume=True)[3]["Nick"]["added"] == \
        ["Replacement for Nick_0 (27.0)"]                     # FA_3 at 27: the 4th
    tags = {n: "HEALTHY" for n in players}
    tags["FA_0"] = "OFS"
    assert _plan(players, rosters, tags)[3]["Nick"]["added"] == \
        ["Replacement for Nick_0 (26.0)"]                     # FA_0 gone: FA_4 is the 4th


def test_for_run_reads_tags_free_agents_and_refuses_a_plain_copy(monkeypatch):
    from test_roster_plan import _moving_world
    data, teams, tags = _moving_world(monkeypatch)
    assert rp.for_run(data, teams, tags).plan[10]["Hayden"]["added"]
    data.__dict__.pop("_roster_plans", None)
    with pytest.raises(rp.UntaggedPoolPlayer):
        rp.for_run(data, teams, dict(tags))
    data.__dict__.pop("_roster_plans", None)
    assert rp.for_run(data, teams, fis.Tags.none()).plan[10]["Hayden"]["added"]


def test_injury_input_carries_the_free_agents_and_a_no_tags_run_states_it():
    raw = fis.Tags({"Rostered A": "O"}, {"Free B": "OFS"})
    got = fis.injury_input(lambda: raw, ["Rostered A"], needed=True)
    assert dict(got.statuses) == {"Rostered A": "O"}
    assert dict(got.statuses.free_agents) == {"Free B": "OFS"}
    assert got.record()["free_agents"] == {"count": 1, "non_healthy": ["Free B (OFS)"],
                                           "assumed_healthy": False}
    none = fis.injury_input(None, ["Rostered A"], needed=False, not_fetched_reason="--fast")
    assert none.statuses.free_agents_assumed_healthy and not none.available


def test_check_sits_in_the_weekly_steps_after_the_sync_and_before_the_build():
    doc = (ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    at = doc.index("python scripts\\overrides.py check")
    assert doc.index("## Step 4: Sync") < at < doc.index("## Step 6: Generate the Stats Report")
    quick = doc[doc.index("## Quick Reference"):]
    assert (quick.index("sync_transactions.py") < quick.index("overrides.py check")
            < quick.index("generate_stats_report.py"))
