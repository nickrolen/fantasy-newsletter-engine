"""The guards in verify_project_integrity, and the ways they used to pass.

Each of these existed and reported success while the thing it guards was
broken. A check that cannot fail is worse than no check, because it is read
as evidence.
"""
import importlib.util
import json

import pytest

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location(
        "verify_project_integrity",
        PROJECT_ROOT / "scripts" / "verify_project_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def test_truncation_is_a_failure_not_a_warning():
    """WEEKLY_WORKFLOW Step 0a says exit 1. It was appending to warnings,
    so a truncated file exited 0 and read as all-clear."""
    src = (PROJECT_ROOT / "scripts" / "verify_project_integrity.py").read_text(
        encoding="utf-8")
    block = src.split("if pct <= -SHRINK_THRESHOLD:")[1].split("elif verbose")[0]
    assert "failures.append(" in block
    assert "warnings.append(" not in block


def test_the_workflow_still_promises_exit_1():
    """If the doc's promise is ever softened instead of the code fixed,
    this is the pair that should be looked at together."""
    doc = (PROJECT_ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    assert "Exit code 1" in doc or "exit code 1" in doc


# ---------------------------------------------------------------------------
# Player of the Week attribution
# ---------------------------------------------------------------------------

def _potw_tree(tmp_path, verify, monkeypatch, credited):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "historical").mkdir(parents=True, exist_ok=True)
    log = [{"season_year": "2025-2026", "week": 8,
            "player_name": "Stephen Curry", "manager": "Hayden"}]
    (tmp_path / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").write_text(
        json.dumps(log), encoding="utf-8")
    (tmp_path / "config" / "POTW_HISTORY.json").write_text(json.dumps(
        {"seasons": {"2025-26": [{"week": 8, "player": "Stephen Curry",
                                  "manager": credited}]}}), encoding="utf-8")
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify, "CONFIG_DIR", tmp_path / "config")


def test_a_misattributed_potw_is_caught(tmp_path, verify, monkeypatch):
    """The value that actually shipped for a year."""
    _potw_tree(tmp_path, verify, monkeypatch, "Garrett")
    failures = verify._check_potw_attribution([])
    assert len(failures) == 1
    assert "Stephen Curry" in failures[0] and "Hayden" in failures[0]


def test_a_correct_potw_passes(tmp_path, verify, monkeypatch):
    _potw_tree(tmp_path, verify, monkeypatch, "Hayden")
    assert verify._check_potw_attribution([]) == []


def test_the_live_potw_history_is_consistent(verify):
    """Against the real files, not a fixture."""
    assert verify._check_potw_attribution([]) == []


# ---------------------------------------------------------------------------
# Golden master resolution
# ---------------------------------------------------------------------------

def test_resolving_the_golden_master_terminates(tmp_path, verify, monkeypatch):
    """It used to end in `return _resolve_golden()` -- itself. With no
    golden report live or archived that recursed until RecursionError."""
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify, "GOLDEN_REPORT", tmp_path / "output" / "x.json")
    resolved = verify._resolve_golden()          # must simply return
    assert not resolved.is_file()


def test_the_golden_check_skips_rather_than_crashing(tmp_path, verify, monkeypatch):
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify, "GOLDEN_REPORT", tmp_path / "output" / "x.json")
    result = verify.check_golden_master()
    assert "SKIPPED" in result["status"]
    assert result["failures"] == []


# ---------------------------------------------------------------------------
# The NBA schedule path
# ---------------------------------------------------------------------------

def test_the_schedule_fetcher_writes_where_config_reads():
    """Three names were in play: the script defaulted to
    data/nba_schedule.json, the workflow said nba_schedule_2025-26.json,
    and config read nba_schedule_2026-27.json. Only the third was loaded."""
    from modules.data_loader import NBA_SCHEDULE_FILE
    src = (PROJECT_ROOT / "scripts" / "fetch_nba_schedule.py").read_text(
        encoding="utf-8")
    assert "DEFAULT_OUTPUT = Path(NBA_SCHEDULE_FILE" in src
    assert "default=DEFAULT_OUTPUT" in src
    assert NBA_SCHEDULE_FILE, "league_config names no NBA schedule file"


def test_the_workflow_no_longer_hardcodes_a_schedule_filename():
    doc = (PROJECT_ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    assert "--output data\\nba_schedule_2025-26.json" not in doc
    assert "fetch_nba_schedule.py --season 2025-26" not in doc
