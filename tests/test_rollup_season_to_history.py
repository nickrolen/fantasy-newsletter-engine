"""Tests for the season rollup -- the one irreversible step in the reset.

start_new_season.py Phase 2 truncates PLAYERLOG.xlsx to a header row. If the
rollup silently drops rows, mangles a name, or writes the wrong schema, the
damage lands in the permanent record and the source is gone. So the bar here
is higher than "it runs".
"""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).parent.parent

HISTORY_FIELDS = [
    "season_year", "season_key", "week", "date", "manager", "fantasy_team",
    "player_name", "player_id", "positions", "slot", "fantasy_points",
    "started", "nba_team", "nba_opponent", "had_game", "is_injured",
]


def _load():
    spec = importlib.util.spec_from_file_location(
        "rollup_season_to_history",
        PROJECT_ROOT / "scripts" / "rollup_season_to_history.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def roll(tmp_path, monkeypatch):
    """The script pointed at throwaway fixture data."""
    mod = _load()

    history = [{
        "season_year": "2024-2025", "season_key": "2024-25", "week": 1,
        "date": "2024-10-22", "manager": "Nick", "fantasy_team": "Luka my Balls",
        "player_name": "LeBron James", "player_id": 3704, "positions": "SF,PF",
        "slot": "SF", "fantasy_points": 42.5, "started": True,
        "nba_team": "LAL", "nba_opponent": "MIN", "had_game": True,
        "is_injured": False,
    }]
    hist_path = tmp_path / "HISTORICAL_PLAYERLOG.json"
    hist_path.write_text(json.dumps(history), encoding="utf-8")

    # One clean row, one misspelled name, one zero-FP row with an opponent.
    pd.DataFrame([
        {"season_year": "2025-2026", "week": 1, "date": "2025-10-21",
         "manager": "Nick", "fantasy_team": "Luka my Balls",
         "player_name": "LeBron James", "nba_team": "LAL", "positions": "SF,PF",
         "nba_opponent": "GSW", "fantasy_points": 38.0, "started": True,
         "is_injured": False, "source": "yahoo", "notes": ""},
        {"season_year": "2025-2026", "week": 1, "date": "2025-10-22",
         "manager": "Nick", "fantasy_team": "Luka my Balls",
         "player_name": "Lebron James", "nba_team": "LAL", "positions": "SF,PF",
         "nba_opponent": "PHX", "fantasy_points": 0.0, "started": True,
         "is_injured": True, "source": "yahoo", "notes": ""},
        {"season_year": "2025-2026", "week": 1, "date": "2025-10-22",
         "manager": "Nick", "fantasy_team": "Luka my Balls",
         "player_name": "Cooper Flagg", "nba_team": "DAL", "positions": "PF",
         "nba_opponent": "", "fantasy_points": 0.0, "started": False,
         "is_injured": False, "source": "yahoo", "notes": ""},
    ]).to_excel(tmp_path / "PLAYERLOG.xlsx", index=False)

    pd.DataFrame([
        {"date": "2025-10-21", "manager": "Nick", "player_name": "LeBron James", "slot": "SF"},
        {"date": "2025-10-22", "manager": "Nick", "player_name": "LeBron James", "slot": "SF"},
        {"date": "2025-10-22", "manager": "Nick", "player_name": "Cooper Flagg", "slot": "BN"},
    ]).to_excel(tmp_path / "LINEUPS.xlsx", index=False)

    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLAYERLOG_XLSX", tmp_path / "PLAYERLOG.xlsx")
    monkeypatch.setattr(mod, "LINEUPS_XLSX", tmp_path / "LINEUPS.xlsx")
    monkeypatch.setattr(mod, "HISTORY_JSON", hist_path)
    mod._history = history
    return mod


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def test_season_key_derivation(roll):
    assert roll.season_key_from_long("2025-2026") == "2025-26"
    assert roll.season_key_from_long("2017-2018") == "2017-18"


def test_had_game_follows_nba_opponent(roll):
    rows, _ = roll.build_rows("2025-26", roll._history)
    by_player_date = {(r["player_name"], r["date"]): r for r in rows}
    assert by_player_date[("LeBron James", "2025-10-21")]["had_game"] is True
    # No opponent -> no game scheduled, so not an injury absence
    flagg = by_player_date[("Cooper Flagg", "2025-10-22")]
    assert flagg["had_game"] is False
    assert flagg["is_injured"] is False


def test_is_injured_is_had_game_and_zero_points(roll):
    rows, _ = roll.build_rows("2025-26", roll._history)
    zero_with_opponent = [
        r for r in rows if r["had_game"] and r["fantasy_points"] == 0.0
    ]
    assert zero_with_opponent, "fixture should contain one such row"
    assert all(r["is_injured"] for r in zero_with_opponent)


def test_slot_is_joined_from_lineups(roll):
    rows, report = roll.build_rows("2025-26", roll._history)
    assert {r["slot"] for r in rows} == {"SF", "BN"}
    assert report["no_slot_match"] == []


# ---------------------------------------------------------------------------
# The corruption this script exists to prevent
# ---------------------------------------------------------------------------

def test_misspelled_name_is_canonicalized(roll):
    """'Lebron James' must not become a second player in the record."""
    rows, report = roll.build_rows("2025-26", roll._history)
    names = {r["player_name"] for r in rows}
    assert "Lebron James" not in names
    assert "LeBron James" in names
    assert report["renamed"] == {"Lebron James": "LeBron James"}


def test_canonicalized_row_inherits_the_existing_player_id(roll):
    rows, _ = roll.build_rows("2025-26", roll._history)
    lebron = [r for r in rows if r["player_name"] == "LeBron James"]
    assert len(lebron) == 2
    assert all(r["player_id"] == 3704 for r in lebron), (
        "a corrected name must pick up the id it already had in history"
    )


def test_genuinely_new_player_gets_null_id_not_a_wrong_one(roll):
    rows, report = roll.build_rows("2025-26", roll._history)
    flagg = [r for r in rows if r["player_name"] == "Cooper Flagg"][0]
    assert flagg["player_id"] is None
    assert "Cooper Flagg" in report["new_players"]


# ---------------------------------------------------------------------------
# Schema and safety
# ---------------------------------------------------------------------------

def test_appended_rows_match_the_historical_schema_exactly(roll):
    rows, _ = roll.build_rows("2025-26", roll._history)
    for r in rows:
        assert list(r.keys()) == HISTORY_FIELDS


def test_workflow_only_columns_are_dropped(roll):
    rows, _ = roll.build_rows("2025-26", roll._history)
    for junk in ("source", "notes", "opponent_manager"):
        assert all(junk not in r for r in rows)


def test_refuses_a_season_already_in_the_record(roll, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["rollup", "--execute", "--season", "2024-25"]
    )
    assert roll.main() == 1
    assert "already in" in capsys.readouterr().out


def test_dry_run_writes_nothing(roll, monkeypatch):
    before = roll.HISTORY_JSON.read_text(encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["rollup", "--season", "2025-26"])
    assert roll.main() == 0
    assert roll.HISTORY_JSON.read_text(encoding="utf-8") == before


def test_execute_appends_and_verifies(roll, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rollup", "--execute", "--season", "2025-26"])
    assert roll.main() == 0
    data = json.loads(roll.HISTORY_JSON.read_text(encoding="utf-8"))
    assert len(data) == 4  # 1 historical + 3 appended
    new = [r for r in data if r["season_key"] == "2025-26"]
    assert len(new) == 3
    assert roll.HISTORY_JSON.with_suffix(".json.bak").exists(), "must back up first"


def test_execute_is_idempotent_by_refusing_the_second_run(roll, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rollup", "--execute", "--season", "2025-26"])
    assert roll.main() == 0
    assert roll.main() == 1, "a second run must refuse rather than duplicate rows"
    data = json.loads(roll.HISTORY_JSON.read_text(encoding="utf-8"))
    assert len([r for r in data if r["season_key"] == "2025-26"]) == 3


def test_force_replaces_rather_than_duplicates(roll, monkeypatch):
    monkeypatch.setattr("sys.argv", ["rollup", "--execute", "--season", "2025-26"])
    assert roll.main() == 0
    monkeypatch.setattr(
        "sys.argv", ["rollup", "--execute", "--force", "--season", "2025-26"]
    )
    assert roll.main() == 0
    data = json.loads(roll.HISTORY_JSON.read_text(encoding="utf-8"))
    assert len([r for r in data if r["season_key"] == "2025-26"]) == 3
    assert len(data) == 4
