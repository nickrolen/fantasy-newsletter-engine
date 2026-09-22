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

    # A complete 2026-27 season in the format the league actually plays:
    # 15 regular-season weeks, a best-of-3 bracket in 16-21, and the Cup in
    # 22-23. The fixture used to model the OLD shape (a two-week bracket at
    # 22-23), which is precisely what derive_outcomes now refuses to read as
    # a bracket -- weeks 22-23 are the Cup.
    #
    # Regular season: Nick 13-2, Benton 8-7, Hayden 5-10, Garrett 4-11.
    # Bracket: Garrett beats Nick and Hayden beats Benton in the semis, then
    # Garrett beats Hayden in the final while Benton takes third off Nick.
    # Cup: Nick wins it.
    #
    # So the three titles land on three different managers, which is the
    # whole point -- League Champion Nick, Playoff Champion Garrett, Cup
    # Champion Nick.
    ROTATION = [
        [("Nick", "Hayden"), ("Benton", "Garrett")],
        [("Nick", "Benton"), ("Hayden", "Garrett")],
        [("Nick", "Garrett"), ("Hayden", "Benton")],
    ]
    # winners per pair over their five regular-season meetings
    REG_WINS = {
        ("Hayden", "Nick"): {"Nick": 4, "Hayden": 1},
        ("Benton", "Nick"): {"Nick": 4, "Benton": 1},
        ("Garrett", "Nick"): {"Nick": 5, "Garrett": 0},
        ("Garrett", "Hayden"): {"Garrett": 3, "Hayden": 2},
        ("Benton", "Hayden"): {"Benton": 3, "Hayden": 2},
        ("Benton", "Garrett"): {"Benton": 4, "Garrett": 1},
    }
    remaining = {k: dict(v) for k, v in REG_WINS.items()}

    weeks, winners_by_week = [], {}
    for wk in range(1, 16):
        pairs = ROTATION[(wk - 1) % 3]
        result = []
        for a, b in pairs:
            key = tuple(sorted((a, b)))
            pick = a if remaining[key].get(a, 0) > 0 else b
            remaining[key][pick] -= 1
            result.append((pick, b if pick == a else a))
        winners_by_week[wk] = result
        weeks.append({"week": wk, "matchups": [
            {"manager_a": w, "manager_b": l} for w, l in result]})

    POST = {
        16: [("Garrett", "Nick"), ("Hayden", "Benton")],
        17: [("Nick", "Garrett"), ("Hayden", "Benton")],
        18: [("Garrett", "Nick"), ("Benton", "Hayden")],
        19: [("Garrett", "Hayden"), ("Benton", "Nick")],
        20: [("Hayden", "Garrett"), ("Nick", "Benton")],
        21: [("Garrett", "Hayden"), ("Benton", "Nick")],
        22: [("Nick", "Hayden"), ("Benton", "Garrett")],
        23: [("Nick", "Benton"), ("Hayden", "Garrett")],
    }
    for wk, result in POST.items():
        winners_by_week[wk] = result
        weeks.append({"week": wk, "matchups": [
            {"manager_a": w, "manager_b": l} for w, l in result]})

    weekly_scores = {m: [] for m in ("Nick", "Hayden", "Benton", "Garrett")}
    for wk, result in sorted(winners_by_week.items()):
        for w, l in result:
            weekly_scores[w].append({"week": wk, "score": 200.0})
            weekly_scores[l].append({"week": wk, "score": 100.0})

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEADERS)
    # name, seasons, reg, po, titles, champs, pts_td, pts_cur, mv_td, mv_cur, rec_cur, blunders
    ws.append(["Nick",    10, "(100-60)", "(5-5)", 3, 2, 300000.0, 40000.0, 400, 50, "(17-6)",  10])
    ws.append(["Hayden",  10, "(80-80)",  "(6-4)", 2, 3, 290000.0, 38000.0, 300, 20, "(9-14)",  19])
    ws.append(["Benton",  10, "(75-85)",  "(4-6)", 1, 1, 280000.0, 37000.0, 350, 15, "(12-11)", 25])
    ws.append(["Garrett", 10, "(70-90)",  "(5-5)", 0, 2, 270000.0, 37500.0, 200, 30, "(8-15)",  12])
    lh = tmp_path / "LEAGUEHISTORY.xlsx"
    wb.save(lh)

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    records = tmp_path / "RECORDS.json"
    records.write_text(json.dumps({
        "manager_season_totals": {
            "Nick":    {"wins": 13, "losses": 2,  "total_points": 40000.0},
            "Hayden":  {"wins": 5,  "losses": 10, "total_points": 38000.0},
            "Benton":  {"wins": 8,  "losses": 7,  "total_points": 37000.0},
            "Garrett": {"wins": 4,  "losses": 11, "total_points": 37500.0},
        },
        "weekly_scores": weekly_scores,
    }), encoding="utf-8")
    schedule = tmp_path / "SCHEDULE.json"
    schedule.write_text(json.dumps({"weeks": weeks}), encoding="utf-8")

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
    # Every manager plays 23 weeks: 15 regular season, then 8 postseason
    # (six bracket weeks and two Cup weeks), so each postseason split is 4-4.
    # Nick 17-6 = regular 13-2 + postseason 4-4
    assert rows["Nick"]["regular_season_record"] == "(113-62)"
    assert rows["Nick"]["playoff_record"] == "(9-9)"
    # Hayden 9-14 = regular 5-10 + postseason 4-4
    assert rows["Hayden"]["regular_season_record"] == "(85-90)"
    assert rows["Hayden"]["playoff_record"] == "(10-8)"
    # Garrett 8-15 = regular 4-11 + postseason 4-4
    assert rows["Garrett"]["regular_season_record"] == "(74-101)"
    assert rows["Garrett"]["playoff_record"] == "(9-9)"
    # Benton 12-11 = regular 8-7 + postseason 4-4
    assert rows["Benton"]["regular_season_record"] == "(83-92)"
    assert rows["Benton"]["playoff_record"] == "(8-10)"


def test_refuses_when_the_split_cannot_reconcile(roll, tmp_path, monkeypatch, capsys):
    """RECORDS.json disagreeing with its own week-by-week results is a conflict.

    manager_season_totals keeps a summary W-L; the weekly scores are what
    actually happened. If they disagree, writing either into the permanent
    history is a coin flip, so refuse.
    """
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
    """Nick wins the regular season at 13-2; Garrett wins the bracket at 4-11.

    The two credits are independent, and under the new format they are read
    from two different parts of the season: weeks 1-15 for the title, the
    weeks 19-21 series for the bracket. The Cup (weeks 22-23, won by Nick
    here) credits neither column -- it earns a keeper, not a trophy.
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


# ---------------------------------------------------------------------------
# --zero-only: the case that actually occurred
# ---------------------------------------------------------------------------

def test_zero_only_clears_without_touching_to_date(roll, tmp_path, monkeypatch):
    """The sheet was accumulated by hand; only the current columns need clearing.

    Populated current-season columns do NOT prove the to-date totals are
    missing the season. Running the full rollover in that situation
    double-counts every to-date field, which is exactly what happened to the
    real 2025-26 sheet.
    """
    before = _rows(tmp_path / "LEAGUEHISTORY.xlsx")
    monkeypatch.setattr("sys.argv", ["r", "--zero-only", "--execute"])
    assert roll.main() == 0
    after = _rows(tmp_path / "LEAGUEHISTORY.xlsx")

    for mgr in ("Nick", "Hayden", "Benton", "Garrett"):
        # to-date columns untouched
        for field in ("seasons_completed", "regular_season_record", "playoff_record",
                      "titles_won", "playoff_championships",
                      "total_points_scored_to_date", "total_moves_made_to_date"):
            assert after[mgr][field] == before[mgr][field], f"{mgr}.{field} changed"
        # current-season columns cleared
        assert after[mgr]["total_points_current_season"] == 0
        assert after[mgr]["total_moves_current_season"] == 0
        assert after[mgr]["total_blunders_current_season"] == 0
        assert after[mgr]["record_current_season"] == "(0-0)"


def test_zero_only_dry_run_writes_nothing(roll, tmp_path, monkeypatch):
    before = (tmp_path / "LEAGUEHISTORY.xlsx").read_bytes()
    monkeypatch.setattr("sys.argv", ["r", "--zero-only"])
    assert roll.main() == 0
    assert (tmp_path / "LEAGUEHISTORY.xlsx").read_bytes() == before


def test_accumulate_path_warns_about_double_counting(roll, monkeypatch, capsys):
    """The dry run must say out loud that it ADDS, and point at --zero-only."""
    monkeypatch.setattr("sys.argv", ["r"])
    assert roll.main() == 0
    out = capsys.readouterr().out
    assert "ADDS to the to-date columns" in out
    assert "--zero-only" in out
