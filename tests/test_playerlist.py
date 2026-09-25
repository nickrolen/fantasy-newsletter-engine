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
    monkeypatch.setattr(mod, "PLAYERLIST", tmp_path / "PLAYERLIST.xlsx")
    monkeypatch.setattr(mod, "ROSTERS", tmp_path / "ROSTERS.json")
    monkeypatch.setattr(mod, "SNAPSHOTS", tmp_path / "snapshots")
    return mod


def _rows(n=6, fppg=30.0, gp=50):
    return [{
        "player_name": f"Player {i}", "player_nba_team": "DEN",
        "player_position(s)": "PG", "player_total_proj_FP": round(fppg * gp, 2),
        "player_proj_GP": gp, "projectedFPPG": fppg, "age": 25,
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


def test_games_remaining_going_up_fails(check, capsys):
    """The signature of a misaligned column.

    Rest-of-season games can only burn down. A column shifted by one puts
    somebody else's number in the GP cell, and it goes up.
    """
    before = _rows(5, gp=50)
    after = _rows(5, gp=50)
    after[1]["player_proj_GP"] = 60
    after[1]["player_total_proj_FP"] = round(30.0 * 60, 2)
    _write(check, after)
    _snapshot(check, before)
    assert _run(check) == 1
    out = capsys.readouterr().out
    assert "MORE games remaining" in out and "misaligned column" in out


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
  <td><a href="https://sports.yahoo.com/nba/players/5352/" class="name">Nikola Joki&#263;</a>
      <span class="Fz-xxs">DEN - C</span></td>
  <td>Big Nik Energy</td>
  <td>71</td>
  <td>4,366.90</td>
  <td>2</td>
  <td>1</td>
</tr>
'''


def test_the_parser_reads_the_fields_the_spreadsheet_needs():
    fetch = _load("fetch_playerlist")
    rows = fetch.parse_rows(YAHOO_ROW, {"Big Nik Energy", "Saboner"})
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
