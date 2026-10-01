"""Career honours: titles and playoff championships.

The league played two seasons under earlier rules. They are deliberately
excluded from the data and deliberately still counted in the honour roll, so
LEAGUEHISTORY.xlsx is the only file that knows the real totals -- 11 titles
and 10 playoff championships across 11 seasons, with 2019-20 never awarded.

That asymmetry is fine. Quoting the two scopes in the same breath is not,
and it happened twice:

  report_builder fell back from LEAGUEHISTORY to manager_careers for titles.
  Nine seasons instead of eleven turns 6 into 5 and 3 into 2 -- smaller
  numbers that still look like numbers.

  playoff_championships came from manager_careers, which the backfill never
  populated. The 2025-26 week-22 report shipped 1, 0, 0, 0 against a true
  3, 2, 3, 2, in the same power-rankings row as correct 11-season titles.
"""
import importlib.util
import json

import pandas as pd
import pytest

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# LEAGUEHISTORY as it really is, which is also the correct answer.
TRUTH = [
    {"manager_name": "Nick",    "titles_won": 6, "playoff_championships": 3, "seasons_completed": 11},
    {"manager_name": "Hayden",  "titles_won": 3, "playoff_championships": 2, "seasons_completed": 11},
    {"manager_name": "Benton",  "titles_won": 2, "playoff_championships": 3, "seasons_completed": 11},
    {"manager_name": "Garrett", "titles_won": 0, "playoff_championships": 2, "seasons_completed": 11},
]

# What RECORDS.json actually held at the end of 2025-26.
SHIPPED = {
    "Nick":    {"titles": 6, "playoff_titles": 0},
    "Hayden":  {"titles": 3, "playoff_titles": 0},
    "Benton":  {"titles": 2, "playoff_titles": 0},
    "Garrett": {"titles": 0, "playoff_titles": 1},
}


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rb():
    from modules import report_builder
    return report_builder


@pytest.fixture(scope="module")
def verify():
    return _load("scripts/verify_project_integrity.py", "verify_project_integrity")


# ---------------------------------------------------------------------------
# Reading the honour roll
# ---------------------------------------------------------------------------

def test_both_honours_come_from_the_same_row(rb):
    honors = rb.career_honors(pd.DataFrame(TRUTH))
    assert honors["Nick"] == {"titles": 6, "playoff_titles": 3, "seasons_completed": 11}
    assert honors["Garrett"] == {"titles": 0, "playoff_titles": 2, "seasons_completed": 11}


def test_the_totals_reconcile_against_eleven_seasons(rb):
    honors = rb.career_honors(pd.DataFrame(TRUTH))
    assert sum(h["titles"] for h in honors.values()) == 11
    # 2019-20 was never awarded a playoff champion -- the COVID season.
    assert sum(h["playoff_titles"] for h in honors.values()) == 10


def test_an_absent_league_history_yields_nothing_not_zero(rb):
    """Unknown and zero are different claims. Zero titles is a statement."""
    assert rb.career_honors(None) == {}
    assert rb.career_honors(pd.DataFrame()) == {}
    honors = rb.career_honors(None)
    assert honors.get("Nick", {}).get("titles") is None


def test_a_missing_column_is_not_filled_in_with_zero(rb):
    frame = pd.DataFrame([{"manager_name": "Nick", "titles_won": 6}])
    assert rb.career_honors(frame)["Nick"] == {
        "titles": 6, "playoff_titles": None, "seasons_completed": None}


def test_there_is_no_fallback_to_the_nine_season_record():
    """The fallback is the bug. Its absence is the fix."""
    src = (PROJECT_ROOT / "modules" / "report_builder.py").read_text(encoding="utf-8")
    assert 'stats["titles"]' not in src
    assert 'career.get("playoff_titles"' not in src
    assert 'stats.get("playoff_titles"' not in src


def test_seasons_completed_is_read_not_divided_by_21():
    """21 games a season was true until this one, when it became 15."""
    src = (PROJECT_ROOT / "modules" / "report_builder.py").read_text(encoding="utf-8")
    assert "// 21" not in src


# ---------------------------------------------------------------------------
# The guard that would have caught it
# ---------------------------------------------------------------------------

def _tree(tmp_path, verify, monkeypatch, careers):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(TRUTH).to_excel(tmp_path / "data" / "LEAGUEHISTORY.xlsx", index=False)
    (tmp_path / "config" / "RECORDS.json").write_text(
        json.dumps({"all_time": {"manager_careers": careers}}), encoding="utf-8")
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify, "CONFIG_DIR", tmp_path / "config")


def test_the_values_that_shipped_last_season_are_now_caught(
        tmp_path, verify, monkeypatch):
    _tree(tmp_path, verify, monkeypatch, SHIPPED)
    failures = verify._check_career_honors_agree([])
    flagged = {m for m in SHIPPED if any(m in f for f in failures)}
    assert flagged == {"Nick", "Hayden", "Benton", "Garrett"}
    assert any("playoff_titles=0" in f and "says 3" in f for f in failures)


def test_records_matching_league_history_passes(tmp_path, verify, monkeypatch):
    good = {r["manager_name"]: {"titles": r["titles_won"],
                                "playoff_titles": r["playoff_championships"]}
            for r in TRUTH}
    _tree(tmp_path, verify, monkeypatch, good)
    assert verify._check_career_honors_agree([]) == []


def test_an_empty_career_block_is_not_a_failure(tmp_path, verify, monkeypatch):
    """After the season reset manager_careers is empty. That is correct."""
    _tree(tmp_path, verify, monkeypatch, {})
    assert verify._check_career_honors_agree([]) == []


def test_more_titles_than_seasons_is_impossible(tmp_path, verify, monkeypatch):
    rows = [dict(r) for r in TRUTH]
    rows[0]["titles_won"] = 9          # 14 titles across 11 seasons
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_excel(tmp_path / "data" / "LEAGUEHISTORY.xlsx", index=False)
    (tmp_path / "config" / "RECORDS.json").write_text(
        json.dumps({"all_time": {"manager_careers": {}}}), encoding="utf-8")
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify, "CONFIG_DIR", tmp_path / "config")
    failures = verify._check_career_honors_agree([])
    assert any("cannot be more than one per season" in f for f in failures)


def test_a_manager_absent_from_league_history_is_flagged(
        tmp_path, verify, monkeypatch):
    _tree(tmp_path, verify, monkeypatch, {"Somebody": {"titles": 1}})
    failures = verify._check_career_honors_agree([])
    assert any("Somebody" in f for f in failures)
