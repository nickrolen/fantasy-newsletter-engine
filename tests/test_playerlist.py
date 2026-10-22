"""PLAYERLIST: the projections every simulator runs on.

This file used to be rebuilt by hand each week -- paste Yahoo's table into an
LLM, have it parse five fields, compute FPPG, carry ages forward and
cross-check the rosters -- and nothing downstream checked the result. The
rules lived in WEEKLY_WORKFLOW Step 2.5 and were enforced by a prompt.

Every failure mode is silent:

    a rostered player missing   -> 0.0 FPPG in every simulation that week
    a column shifted by one     -> plausible numbers against wrong players
    the file not regenerated    -> last week's projections, quietly
    an accented name            -> no match, so 0.0 FPPG

The last one was live: Yahoo writes Jokic, Doncic, Sengun, Demin and Nurkic
with diacritics -- five in the top 150 -- and every lookup was exact string
equality.
"""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from modules.data_loader import normalize_player_name

PROJECT_ROOT = Path(__file__).parent.parent

COLUMNS = ["player_name", "player_nba_team", "player_position(s)",
           "player_total_proj_FP", "player_proj_GP", "projectedFPPG", "age"]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def check(tmp_path, monkeypatch):
    mod = _load("check_playerlist")
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    # A real tree always has the durability prior the hazard reads and a
    # SCHEDULE that says when week 1 starts; the GP-shape check compares the
    # file against that date (HANDOFF_DURABILITY_PRIOR_2026-10-22).
    import shutil
    from modules.data_loader import DURABILITY_PRIOR
    (tmp_path / "config" / "snapshots").mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / DURABILITY_PRIOR["snapshot"],
                 tmp_path / DURABILITY_PRIOR["snapshot"])
    shutil.copy2(PROJECT_ROOT / "config" / "SCHEDULE.json",
                 tmp_path / "config" / "SCHEDULE.json")
    monkeypatch.setattr(mod, "PLAYERLIST", tmp_path / "PLAYERLIST.xlsx")
    monkeypatch.setattr(mod, "ROSTERS", tmp_path / "ROSTERS.json")
    monkeypatch.setattr(mod, "SNAPSHOTS", tmp_path / "snapshots")
    return mod


def _rows(n=6, fppg=30.0, gp=50):
    """GP varies by row: a pre-season column has a durability haircut spread
    across players, and a flat one is the in-season meaning the GP-shape check
    refuses before week 1."""
    return [{
        "player_name": f"Player {i}", "player_nba_team": "DEN",
        "player_position(s)": "PG",
        "player_total_proj_FP": round(fppg * (gp - i % 5), 2),
        "player_proj_GP": gp - i % 5, "projectedFPPG": fppg, "age": 25,
    } for i in range(n)]


def _write(mod, rows):
    pd.DataFrame(rows, columns=COLUMNS).to_excel(mod.PLAYERLIST, index=False)


def _snapshot(mod, rows, stamp="2026-01-01"):
    mod.SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLUMNS).to_excel(
        mod.SNAPSHOTS / f"PLAYERLIST_{stamp}.xlsx", index=False)


def _run(mod, argv=("c",)):
    import sys
    old = sys.argv
    sys.argv = list(argv)
    try:
        return mod.main()
    finally:
        sys.argv = old


# ---------------------------------------------------------------------------
# Accented names -- the failure that was live
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("yahoo,roster", [
    ("Nikola Jokić", "Nikola Jokic"),
    ("Luka Dončić", "Luka Doncic"),
    ("Alperen Şengün", "Alperen Sengun"),
    ("Jusuf Nurkić", "Jusuf Nurkic"),
    ("Egor Dëmin", "Egor Demin"),
])
def test_accented_yahoo_names_match_plain_roster_names(yahoo, roster):
    assert normalize_player_name(yahoo) == normalize_player_name(roster)


def test_normalisation_does_not_collapse_different_players():
    assert normalize_player_name("Jaren Jackson Jr.") != normalize_player_name("Jaren Jackson")
    assert normalize_player_name("Gary Payton II") != normalize_player_name("Gary Payton")


def test_the_projection_lookup_uses_the_normalised_name():
    """FantasyData.get_player_projection did exact ==; Jokic returned None."""
    from modules.data_loader import FantasyData, load_playerlist
    import tempfile, os
    frame = pd.DataFrame([{
        "player_name": "Nikola Jokić", "player_nba_team": "DEN",
        "player_position(s)": "C", "player_total_proj_FP": 4366.9,
        "player_proj_GP": 71, "projectedFPPG": 61.51, "age": 31}])
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "PLAYERLIST.xlsx"
        frame.to_excel(path, index=False)
        data = FantasyData(playerlist=load_playerlist(path))
    assert data.get_player_projection("Nikola Jokic") == pytest.approx(61.51)
    assert data.get_player_projection("Nikola Jokić") == pytest.approx(61.51)
    assert data.get_player_projection("Nobody At All") is None


def test_team_projections_resolve_an_accented_playerlist_name():
    """The roster join that silently produced projected_fppg=0.0."""
    from modules.projections import resolve_projection
    class P:
        def __init__(self, v): self.projected_fppg = v
    projections = {"Nikola Jokić": P(61.5), "LeBron James": P(40.0)}
    assert resolve_projection(projections, "Nikola Jokic").projected_fppg == 61.5
    assert resolve_projection(projections, "LeBron James").projected_fppg == 40.0
    assert resolve_projection(projections, "Nobody") is None


# ---------------------------------------------------------------------------
# The validator catches each silent failure
# ---------------------------------------------------------------------------

def test_a_clean_file_passes(check):
    _write(check, _rows())
    assert _run(check) == 0


def test_an_empty_file_fails(check):
    pd.DataFrame(columns=COLUMNS).to_excel(check.PLAYERLIST, index=False)
    assert _run(check) == 1


def test_a_missing_rostered_player_fails(check, capsys):
    rows = _rows(3)
    _write(check, rows)
    check.ROSTERS.write_text(json.dumps({"rosters": {
        "Nick": ["Player 0", "Player 1", "Nikola Jokic"]}}), encoding="utf-8")
    assert _run(check) == 1
    out = capsys.readouterr().out
    assert "rostered player(s) missing" in out and "Nikola Jokic" in out


def test_a_rostered_player_spelled_with_an_accent_is_NOT_a_failure(check):
    """The file says Jokic with a diacritic; the roster says plain. Same man."""
    rows = _rows(2) + [{
        "player_name": "Nikola Jokić", "player_nba_team": "DEN",
        "player_position(s)": "C", "player_total_proj_FP": 4366.9,
        "player_proj_GP": 71, "projectedFPPG": 61.51, "age": 31}]
    _write(check, rows)
    check.ROSTERS.write_text(json.dumps({"rosters": {
        "Nick": ["Player 0", "Nikola Jokic"]}}), encoding="utf-8")
    assert _run(check) == 0


def test_broken_fppg_arithmetic_fails(check, capsys):
    rows = _rows(4)
    rows[2]["projectedFPPG"] = 12.0          # no longer total / GP
    _write(check, rows)
    assert _run(check) == 1
    assert "does not equal total/GP" in capsys.readouterr().out


def test_a_file_that_was_not_regenerated_fails(check, capsys):
    rows = _rows()
    _write(check, rows)
    _snapshot(check, rows)
    assert _run(check) == 1
    assert "not regenerated" in capsys.readouterr().out


def test_a_same_day_rerun_is_not_mistaken_for_a_stale_file(check, capsys):
    """Re-running twice in one day is a re-run, not a missed rebuild.

    Yahoo's projections do not move between two runs an hour apart, so an
    identical file is exactly what a same-day re-run should produce. The
    staleness check only means something against an EARLIER day.
    """
    from datetime import date
    rows = _rows()
    _write(check, rows)
    _snapshot(check, rows, stamp=date.today().isoformat())
    assert _run(check) == 0
    assert "same-day re-run" in capsys.readouterr().out


def test_a_stale_file_still_fails_against_an_earlier_day(check, capsys):
    """The check above must not have weakened this one."""
    from datetime import date, timedelta
    rows = _rows()
    _write(check, rows)
    _snapshot(check, rows,
              stamp=(date.today() - timedelta(days=7)).isoformat())
    assert _run(check) == 1
    assert "not regenerated" in capsys.readouterr().out


def test_a_few_players_gaining_games_is_a_refresh_not_a_failure(check, capsys):
    """2026-10-13: Yahoo refreshed and six of 168 players gained games
    remaining (Kyrie 57 -> 60) as injury outlooks improved. The old rule
    failed the file on any one of them."""
    before = _rows(40, gp=60)
    after = _rows(40, gp=60)
    for i in range(3):                       # a few up...
        after[i]["player_proj_GP"] = 63
        after[i]["player_total_proj_FP"] = round(30.0 * 63, 2)
    for i in range(3, 9):                    # ...more down
        after[i]["player_proj_GP"] = 55
        after[i]["player_total_proj_FP"] = round(30.0 * 55, 2)
    _write(check, after)
    _snapshot(check, before)
    _run(check)
    out = capsys.readouterr().out
    assert "shifted against names" not in out
    assert "games remaining up for 3 of 40" in out


def test_stats_shifted_against_names_fail(check, capsys):
    """The real misalignment: every row's numbers belong to the row above.
    About half the players gain games, half lose them."""
    import random
    rng = random.Random(4)
    before = _rows(40)
    for r in before:
        r["player_proj_GP"] = rng.randint(50, 80)
        r["player_total_proj_FP"] = round(r["projectedFPPG"] * r["player_proj_GP"], 2)
    after = [dict(r) for r in before]
    for i in range(len(after)):
        src = before[i - 1]
        for c in ("player_proj_GP", "player_total_proj_FP", "projectedFPPG"):
            after[i][c] = src[c]
    _write(check, after)
    _snapshot(check, before)
    assert _run(check) == 1
    assert "shifted against names" in capsys.readouterr().out


def test_games_remaining_beyond_a_season_fail(check, capsys):
    rows = _rows(5)
    rows[0]["player_proj_GP"] = 90
    rows[0]["player_total_proj_FP"] = round(30.0 * 90, 2)
    _write(check, rows)
    assert _run(check) == 1
    assert "outside 0-82" in capsys.readouterr().out


def test_a_big_fppg_move_warns_but_does_not_block(check, capsys):
    before = _rows(5, fppg=30.0)
    after = _rows(5, fppg=30.0)
    after[0]["projectedFPPG"] = 50.0
    after[0]["player_total_proj_FP"] = round(50.0 * 50, 2)
    _write(check, after)
    _snapshot(check, before)
    assert _run(check) == 0, "a real projection can move; this is a warning"
    assert "moved more than" in capsys.readouterr().out


def test_implausible_fppg_fails(check, capsys):
    rows = _rows(4)
    rows[1]["projectedFPPG"] = 250.0
    rows[1]["player_total_proj_FP"] = 250.0 * 50
    _write(check, rows)
    assert _run(check) == 1
    assert "above" in capsys.readouterr().out


def test_duplicate_players_fail(check, capsys):
    rows = _rows(3)
    rows.append(dict(rows[0]))
    _write(check, rows)
    assert _run(check) == 1
    assert "duplicate" in capsys.readouterr().out


def test_missing_ages_warn_but_do_not_block(check, capsys):
    rows = _rows(4)
    rows[2]["age"] = None
    _write(check, rows)
    assert _run(check) == 0
    assert "no age" in capsys.readouterr().out


def test_strict_turns_warnings_into_failures(check):
    rows = _rows(4)
    rows[2]["age"] = None
    _write(check, rows)
    assert _run(check, ("c", "--strict")) == 1


# ---------------------------------------------------------------------------
# The scraper's parser
# ---------------------------------------------------------------------------

YAHOO_ROW = '''
<tr class="player-row">
  <td><span class="icon"></span></td>
  <td><span class="icon"></span></td>
  <td><a href="https://sports.yahoo.com/nba/players/5352/" class="name">Nikola Joki&#263;</a>
      <span class="Fz-xxs">DEN - C</span></td>
  <td></td>
  <td>Big Nik Energy</td>
  <td>71</td>
  <td>4,366.90</td>
  <td>2</td>
  <td>1</td>
</tr>
'''

# The header row, which lines up index-for-index with those cells: two icon
# columns, then Players, Opp, Roster Status, GP*, Fan Pts and the two rank
# columns. Yahoo marks the sorted column with a private-use glyph.
YAHOO_HEADER = '''
<tr>
  <th></th><th></th><th>Players</th><th>Opp: 9/25</th><th>Roster Status</th>
  <th>GP*</th><th>Fan Pts</th><th>Pre-Season</th><th>Current\ue002</th>
</tr>
'''

# The same table with the two rank columns moved ahead of GP -- the cosmetic
# reshuffle that would silently feed a rank into proj_gp if the parser were
# still taking the first two numeric cells in the row.
YAHOO_RESHUFFLED = '''
<tr>
  <th></th><th></th><th>Players</th><th>Opp: 9/25</th><th>Roster Status</th>
  <th>Pre-Season</th><th>Current</th><th>GP*</th><th>Fan Pts</th>
</tr>
<tr class="player-row">
  <td><span class="icon"></span></td>
  <td><span class="icon"></span></td>
  <td><a href="https://sports.yahoo.com/nba/players/5352/" class="name">Nikola Joki&#263;</a>
      <span class="Fz-xxs">DEN - C</span></td>
  <td></td>
  <td>Big Nik Energy</td>
  <td>2</td>
  <td>1</td>
  <td>71</td>
  <td>4,366.90</td>
</tr>
'''


def test_the_parser_reads_the_fields_the_spreadsheet_needs():
    fetch = _load("fetch_playerlist")
    rows = fetch.parse_rows(YAHOO_HEADER + YAHOO_ROW,
                            {"Big Nik Energy", "Saboner"})
    assert len(rows) == 1
    row = rows[0]
    assert row["yahoo_id"] == "5352"
    assert row["player_name"] == "Nikola Jokić"
    assert row["nba_team"] == "DEN"
    assert row["positions"] == "C"
    assert row["proj_gp"] == "71"
    assert row["total_fp"] == "4,366.90"
    assert row["owner"] == "Big Nik Energy"


def test_the_parser_ignores_rows_with_no_player_link():
    fetch = _load("fetch_playerlist")
    assert fetch.parse_rows("<tr><td>Rankings</td><td>Rosters</td></tr>", set()) == []


def test_fppg_is_derived_not_parsed():
    """The LLM used to do this division. It is arithmetic with no upside."""
    fetch = _load("fetch_playerlist")
    src = (PROJECT_ROOT / "scripts" / "fetch_playerlist.py").read_text(encoding="utf-8")
    assert "fp / gp" in src
    assert fetch.to_number("4,366.90") == pytest.approx(4366.90)
    assert fetch.to_number("-") is None


def test_the_league_id_comes_out_of_the_league_key():
    fetch = _load("fetch_playerlist")
    assert fetch.league_id_from_key("478.l.16778") == "16778"
    assert fetch.league_id_from_key("466.l.42309") == "42309"
    assert fetch.league_id_from_key("") == ""


def test_the_columns_are_located_by_their_header_labels():
    fetch = _load("fetch_playerlist")
    assert fetch.find_columns(YAHOO_HEADER) == {"gp": 5, "fp": 6}


def test_a_reshuffled_table_still_reads_the_right_columns():
    """The whole point of binding to headers.

    Rank moves in front of GP. Positionally, proj_gp would become 2 and
    total_fp 1 -- numbers that are individually plausible and completely
    wrong. By label, they stay 71 and 4,366.90.
    """
    fetch = _load("fetch_playerlist")
    assert fetch.find_columns(YAHOO_RESHUFFLED) == {"gp": 7, "fp": 8}
    row = fetch.parse_rows(YAHOO_RESHUFFLED, {"Big Nik Energy"})[0]
    assert row["proj_gp"] == "71"
    assert row["total_fp"] == "4,366.90"
    assert row["player_name"] == "Nikola Jokić"
    # And what the old positional read would have produced from this table:
    blind = fetch.parse_rows(YAHOO_RESHUFFLED, {"Big Nik Energy"},
                             columns={"gp": -1, "fp": -1})[0]
    assert blind["proj_gp"] == ""   # nothing sensible, which is the point


def test_points_scored_is_never_mistaken_for_fan_points():
    """PTS is a real column ten places right of Fan Pts. Matching it would
    put a season point total where a fantasy point total belongs."""
    fetch = _load("fetch_playerlist")
    assert fetch.find_columns(
        "<tr><th>Players</th><th>GP*</th><th>PTS</th><th>REB</th></tr>") is None


def test_an_unreadable_header_is_reported_not_guessed_at():
    fetch = _load("fetch_playerlist")
    assert fetch.find_columns("<tr><th>Player</th><th>Whatever</th></tr>") is None
    assert fetch.find_columns("<tr><td>71</td><td>4,366.90</td></tr>") is None


def test_the_pipeline_refuses_a_table_it_cannot_read(monkeypatch):
    """A redesign must stop the run, not produce a plausible spreadsheet.

    check_playerlist would very likely catch the result anyway, but the
    fetch has no business writing numbers it cannot account for.
    """
    fetch = _load("fetch_playerlist")
    monkeypatch.setattr(fetch, "fetch_page",
                        lambda *a, **k: "<table><tr><td>redesigned</td></tr></table>")
    with pytest.raises(fetch.TableFormatError) as excinfo:
        fetch.collect("16778", "T", 50, "rostered")
    assert "NOT modified" in str(excinfo.value)
    assert "WEEKLY_WORKFLOW" in str(excinfo.value)


def test_a_bare_row_fragment_still_parses_without_a_header():
    """The positional fallback, which exists only for fragments like this."""
    fetch = _load("fetch_playerlist")
    row = fetch.parse_rows(YAHOO_ROW, {"Big Nik Energy"})[0]
    assert row["proj_gp"] == "71"
    assert row["total_fp"] == "4,366.90"


# ---------------------------------------------------------------------------
# STATUS 10-12 sec.3 item 2: the gate failed a correct, fresh file twice over
# ---------------------------------------------------------------------------

def _named(names):
    rows = _rows(len(names))
    for r, n in zip(rows, names):
        r["player_name"] = n
    return rows


def _write_stamped(mod, rows, when):
    from datetime import datetime
    from modules import playerlist_freshness
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return playerlist_freshness.write(frame, mod.PLAYERLIST, "test",
                                      now=datetime.combine(when, datetime.min.time()))


def test_yahoos_initial_spelling_of_a_rostered_player_is_present(check, capsys):
    """Yahoo's roster endpoint says "Shai Gilgeous-Alexander" and its pool
    endpoint "S. Gilgeous-Alexander", in the same fetch."""
    _write(check, _named(["S. Gilgeous-Alexander", "N. Alexander-Walker", "Josh Hart"]))
    check.ROSTERS.write_text(json.dumps({"rosters": {
        "Hayden": ["Shai Gilgeous-Alexander"],
        "Nick": ["Nickeil Alexander-Walker", "Josh Hart"]}}), encoding="utf-8")
    _run(check)
    out = capsys.readouterr().out
    assert "missing" not in out and "3/3 rostered players present" in out
    assert "Shai Gilgeous-Alexander -> S. Gilgeous-Alexander" in out


def test_a_different_player_with_the_same_initial_is_still_missing(check, capsys):
    """Lonzo is not LaMelo. The initial step needs a real initial on one side."""
    _write(check, _named(["LaMelo Ball", "Josh Hart"]))
    check.ROSTERS.write_text(json.dumps({"rosters": {"Nick": ["Lonzo Ball"]}}),
                             encoding="utf-8")
    assert _run(check) == 1
    assert "Lonzo Ball (Nick)" in capsys.readouterr().out


def test_a_fresh_fetch_with_unchanged_projections_passes(check, capsys):
    """10-12: fetched that morning, identical to 10-05 because Yahoo had not
    moved a projection. Freshness is the fetch date, not whether numbers moved."""
    from datetime import date, timedelta
    rows = _rows()
    _snapshot(check, rows, stamp=(date.today() - timedelta(days=7)).isoformat())
    _write_stamped(check, rows, date.today())
    assert _run(check) == 0
    out = capsys.readouterr().out
    assert "not regenerated" not in out and "projections unchanged since" in out


def test_a_stale_fetch_fails_by_its_stamp(check, capsys):
    from datetime import date, timedelta
    _write_stamped(check, _rows(), date.today() - timedelta(days=10))
    assert _run(check) == 1
    assert "fetched 10 days ago" in capsys.readouterr().out


def test_a_stamp_that_no_longer_describes_the_file_is_ignored(check, capsys):
    """A hand edit after fetching voids the stamp -- and an identical-to-last-
    week file is then judged exactly as an unstamped one: stale."""
    from datetime import date, timedelta
    from openpyxl import load_workbook
    rows = _rows()
    _write_stamped(check, rows, date.today())
    wb = load_workbook(check.PLAYERLIST)
    wb["Sheet1"]["F2"] = 31.0                           # edit a projection
    wb["Sheet1"]["E2"] = 50
    wb["Sheet1"]["D2"] = 1550.0
    wb.save(check.PLAYERLIST)
    edited = pd.read_excel(check.PLAYERLIST)
    _snapshot(check, edited.to_dict("records"),
              stamp=(date.today() - timedelta(days=7)).isoformat())
    assert _run(check) == 1
    out = capsys.readouterr().out
    assert "no longer matches" in out and "not regenerated" in out


def test_an_unstamped_file_says_so(check, capsys):
    _write(check, _rows())
    _run(check)
    assert "no fetch stamp" in capsys.readouterr().out


def test_the_stamp_hash_survives_an_xlsx_round_trip(tmp_path):
    from modules import playerlist_freshness as pf
    frame = pd.DataFrame(_rows(), columns=COLUMNS)
    frame["player_proj_GP"] = frame["player_proj_GP"].astype(int)
    st = pf.write(frame, tmp_path / "p.xlsx", "test")
    back = pd.read_excel(tmp_path / "p.xlsx")
    assert pf.content_hash(back) == st["content_sha256"]
    assert pf.assess(back, pf.read_stamp(tmp_path / "p.xlsx"))["how"] == "stamp"
    # The engine reads the data sheet, not the stamp.
    assert list(back.columns) == COLUMNS


def test_snapshot_cannot_be_taken_of_a_scratch_file(check, tmp_path):
    other = tmp_path / "elsewhere.xlsx"
    pd.DataFrame(_rows(), columns=COLUMNS).to_excel(other, index=False)
    assert _run(check, ("c", "--file", str(other), "--snapshot")) == 1
