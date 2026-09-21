"""Tests for the LEAGUEHISTORY season rollover.

This one is dangerous in a quiet way. The player-log rollup fails loudly if it
goes wrong; this writes four rows of cumulative totals that nothing downstream
validates. A bad rollover does not error -- the all-time record just becomes
wrong and stays wrong.
"""
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

PROJECT_ROOT = Path(__file__).parent.parent

HEADERS = [
    "manager_name", "seasons_completed", "regular_season_record",
    "playoff_record", "titles_won", "playoff_championships",
    "total_points_scored_to_date", "total_points_current_season",
    "total_moves_made_to_date", "total_moves_current_season",
    "record_current_season", "total_blunders_current_season",
]


def _load():
    spec = importlib.util.spec_from_file_location(
        "rollover_leaguehistory",
        PROJECT_ROOT / "scripts" / "rollover_leaguehistory.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def roll(tmp_path, monkeypatch):
    mod = _load()

    # Mirrors the real 2025-26 shape: four managers, a two-week bracket where
    # the top regular-season seed loses in the semifinal. A two-manager
    # fixture cannot exercise the "final is between last round's winners"
    # derivation at all.
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    # name, seasons, reg, po, titles, champs, pts_td, pts_cur, mv_td, mv_cur, rec_cur, blunders
    ws.append(["Nick",    10, "(100-60)", "(5-5)",  3, 2, 300000.0, 40000.0, 400, 50, "(17-6)",  10])
    ws.append(["Hayden",  10, "(80-80)",  "(6-4)",  2, 3, 290000.0, 38000.0, 300, 20, "(6-17)",  19])
    ws.append(["Benton",  10, "(75-85)",  "(4-6)",  1, 1, 280000.0, 37000.0, 350, 15, "(11-12)", 25])
    ws.append(["Garrett", 10, "(70-90)",  "(5-5)",  0, 2, 270000.0, 37500.0, 200, 30, "(12-11)", 12])
    lh = tmp_path / "LEAGUEHISTORY.xlsx"
    wb.save(lh)

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    records = tmp_path / "RECORDS.json"
    records.write_text(json.dumps({
        "manager_season_totals": {
            "Nick":    {"wins": 17, "losses": 4,  "total_points": 40000.0},
            "Hayden":  {"wins": 5,  "losses": 16, "total_points": 38000.0},
            "Benton":  {"wins": 10, "losses": 11, "total_points": 37000.0},
            "Garrett": {"wins": 10, "losses": 11, "total_points": 37500.0},
        },
        "weekly_scores": {
            # wk22 semifinals: Hayden beats Nick, Garrett beats Benton
            # wk23 final: Garrett beats Hayden. 3rd place: Benton beats Nick.
            "Nick":    [{"week": 22, "score": 100.0}, {"week": 23, "score": 100.0}],
            "Hayden":  [{"week": 22, "score": 200.0}, {"week": 23, "score": 150.0}],
            "Benton":  [{"week": 22, "score": 110.0}, {"week": 23, "score": 120.0}],
            "Garrett": [{"week": 22, "score": 180.0}, {"week": 23, "score": 300.0}],
        },
    }), encoding="utf-8")
    schedule = tmp_path / "SCHEDULE.json"
    schedule.write_text(json.dumps({"weeks": [
        {"week": 22, "matchups": [
            {"manager_a": "Nick", "manager_b": "Hayden"},
            {"manager_a": "Benton", "manager_b": "Garrett"}]},
        {"week": 23, "matchups": [
            {"manager_a": "Hayden", "manager_b": "Garrett"},
            {"manager_a": "Nick", "manager_b": "Benton"}]},
    ]}), encoding="utf-8")

    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "LEAGUEHISTORY", lh)
    monkeypatch.setattr(mod, "RECORDS", records)
    monkeypatch.setattr(mod, "SCHEDULE", schedule)
    return mod


def _rows(path):
    ws = openpyxl.load_workbook(path).active
    hdr = [c.value for c in ws[1]]
    return {r[0]: dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True)}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_record_parsing_round_trips(roll):
    assert roll.parse_record("(140-83)") == (140, 83)
    assert roll.parse_record("140-83") == (140, 83)
    assert roll.parse_record("( 9 - 11 )") == (9, 11)
    assert roll.fmt_record(9, 11) == "(9-11)"


def test_unparseable_record_raises(roll):
    with pytest.raises(ValueError):
        roll.parse_record("n/a")


# ---------------------------------------------------------------------------
# The split has to reconcile
# ---------------------------------------------------------------------------

def test_regular_plus_playoff_equals_the_season_record(roll, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["r", "--execute"])
    assert roll.main() == 0
    rows = _rows(tmp_path / "LEAGUEHISTORY.xlsx")
    # Nick 17-6 = regular 17-4 + playoff 0-2 (lost semi, lost 3rd-place game)
    assert rows["Nick"]["regular_season_record"] == "(117-64)"
    assert rows["Nick"]["playoff_record"] == "(5-7)"
    # Hayden 6-17 = regular 5-16 + playoff 1-1 (won semi, lost final)
    assert rows["Hayden"]["regular_season_record"] == "(85-96)"
    assert rows["Hayden"]["playoff_record"] == "(7-5)"
    # Garrett 12-11 = regular 10-11 + playoff 2-0 (won semi, won final)
    assert rows["Garrett"]["regular_season_record"] == "(80-101)"
    assert rows["Garrett"]["playoff_record"] == "(7-5)"


def test_refuses_when_the_split_cannot_reconcile(roll, tmp_path, monkeypatch, capsys):
    """RECORDS claiming more wins than the season record is a data conflict."""
    r = json.loads((tmp_path / "RECORDS.json").read_text())
    r["manager_season_totals"]["Nick"]["wins"] = 25
    (tmp_path / "RECORDS.json").write_text(json.dumps(r), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["r", "--execute"])
    assert roll.main() == 1
    assert "reconcile" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Accumulation
# ---------------------------------------------------------------------------

def test_totals_and_counters_accumulate(roll, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["r", "--execute"])
    assert roll.main() == 0
    rows = _rows(tmp_path / "LEAGUEHISTORY.xlsx")
    assert rows["Nick"]["total_points_scored_to_date"] == 340000.0
    assert rows["Nick"]["total_moves_made_to_date"] == 450
    assert rows["Nick"]["seasons_completed"] == 11
    assert rows["Garrett"]["seasons_completed"] == 11


def test_winners_get_exactly_one_credit_each(roll, tmp_path, monkeypatch):
    """Nick wins the regular season at 17-4; Garrett wins the bracket at 10-11.

    The two credits are independent -- this is exactly the 2025-26 case, where
    the best record and the championship went to different managers.
    """
    monkeypatch.setattr("sys.argv", ["r", "--execute"])
    assert roll.main() == 0
    rows = _rows(tmp_path / "LEAGUEHISTORY.xlsx")
    assert rows["Nick"]["titles_won"] == 4              # 3 + 1, best record
    assert rows["Nick"]["playoff_championships"] == 2   # unchanged
    assert rows["Garrett"]["titles_won"] == 0           # unchanged
    assert rows["Garrett"]["playoff_championships"] == 3  # 2 + 1, won the final
    # Nobody else gains anything
    assert rows["Hayden"]["titles_won"] == 2
    assert rows["Hayden"]["playoff_championships"] == 3
    assert rows["Benton"]["titles_won"] == 1
    assert rows["Benton"]["playoff_championships"] == 1


def test_champion_override_wins_over_derivation(roll, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["r", "--execute", "--champion", "Nick"])
    assert roll.main() == 0
    rows = _rows(tmp_path / "LEAGUEHISTORY.xlsx")
    assert rows["Nick"]["playoff_championships"] == 3   # override credited Nick
    assert rows["Garrett"]["playoff_championships"] == 2  # derived winner not credited


# ---------------------------------------------------------------------------
# Current-season columns must be cleared, or next season double-counts
# ---------------------------------------------------------------------------

def test_every_current_season_column_is_zeroed(roll, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["r", "--execute"])
    assert roll.main() == 0
    rows = _rows(tmp_path / "LEAGUEHISTORY.xlsx")
    for mgr in ("Nick", "Hayden", "Benton", "Garrett"):
        assert rows[mgr]["total_points_current_season"] == 0
        assert rows[mgr]["total_moves_current_season"] == 0
        assert rows[mgr]["total_blunders_current_season"] == 0
        assert rows[mgr]["record_current_season"] == "(0-0)"


def test_running_twice_refuses_instead_of_double_counting(roll, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["r", "--execute"])
    assert roll.main() == 0
    assert roll.main() == 1
    assert "already" in capsys.readouterr().out
    rows = _rows(tmp_path / "LEAGUEHISTORY.xlsx")
    assert rows["Nick"]["seasons_completed"] == 11, "must not increment twice"


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_dry_run_changes_nothing(roll, tmp_path, monkeypatch):
    before = (tmp_path / "LEAGUEHISTORY.xlsx").read_bytes()
    monkeypatch.setattr("sys.argv", ["r"])
    assert roll.main() == 0
    assert (tmp_path / "LEAGUEHISTORY.xlsx").read_bytes() == before


def test_execute_backs_up_first(roll, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["r", "--execute"])
    assert roll.main() == 0
    assert (tmp_path / "LEAGUEHISTORY.xlsx.bak").exists()


def test_no_module_path_escapes_the_tmp_root(roll, tmp_path):
    escaped = []
    for name in dir(roll):
        if name.startswith("_"):
            continue
        val = getattr(roll, name)
        if isinstance(val, Path) and name not in {"PROJECT_ROOT", "SCRIPT_DIR"}:
            try:
                val.relative_to(tmp_path)
            except ValueError:
                escaped.append(f"{name} -> {val}")
    assert escaped == [], "paths not redirected; tests would write real data:\n" + "\n".join(escaped)
