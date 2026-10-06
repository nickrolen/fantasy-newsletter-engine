"""Point-in-time capture: the inputs behind each week's published lines.

The retro-sim cannot check one published line from before 2026-27 because
nobody saved Yahoo's projections, the injury overrides or the live statuses
the engine priced them with. Each is overwritten in place every week. These
tests pin the capture that stops that gap reopening, the integrity checks
that notice when it does, and the INJURY_OVERRIDES due date.
"""
import importlib.util
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from modules import point_in_time as pit

PROJECT_ROOT = Path(__file__).parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _place(root, rel, content="x"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return path


@pytest.fixture
def project(tmp_path):
    _place(tmp_path, "data/PLAYERLIST.xlsx", "projections v1")
    _place(tmp_path, "config/INJURY_OVERRIDES.json",
           {"players": [{"player_name": "A", "out_weeks": [3, 4]}],
            "last_updated": "2026-11-02"})
    _place(tmp_path, "config/ROSTERS.json", {"Nick": ["A"]})
    _place(tmp_path, "config/SCHEDULE.json", {"weeks": []})
    _place(tmp_path, "data/nba_schedule_2026-27.json", {"games": []})
    return tmp_path


def _capture(root, week=3, statuses=None, attempted=True, **kw):
    return pit.capture_week_inputs(
        root, week, season="2026-27",
        injury_statuses={"A": "O", "B": "HEALTHY"} if statuses is None else statuses,
        injury_fetch_attempted=attempted,
        nba_schedule_file="data/nba_schedule_2026-27.json",
        total_weeks=23, now=datetime(2026, 11, 3, 9, 0), **kw)


# ---------------------------------------------------------------------------
# The capture itself
# ---------------------------------------------------------------------------

def test_capture_copies_every_input_byte_for_byte(project):
    dest = _capture(project)
    assert dest == project / "config/snapshots/point_in_time/report_week03"
    for rel in ["data/PLAYERLIST.xlsx", "config/INJURY_OVERRIDES.json",
                "config/ROSTERS.json", "config/SCHEDULE.json",
                "data/nba_schedule_2026-27.json"]:
        assert (dest / Path(rel).name).read_bytes() == (project / rel).read_bytes()
    statuses = json.loads((dest / "INJURY_STATUSES.json").read_text())
    assert statuses == {"A": "O", "B": "HEALTHY"}


def test_manifest_says_which_week_the_lines_priced(project):
    """Report N is built after week N; its lines cover N+1."""
    _capture(project, week=3)
    m = pit.load_manifest(project, 3)
    assert m["report_week"] == 3
    assert m["lines_cover_week"] == 4
    assert m["injury_overrides_last_updated"] == "2026-11-02"
    assert m["injury_statuses"] == {"fetch_attempted": True, "available": True,
                                    "count": 2, "non_healthy": 1}
    sha = m["files"]["data/PLAYERLIST.xlsx"]["sha256"]
    assert len(sha) == 64


def test_final_week_report_prices_nothing(project):
    _capture(project, week=23)
    assert pit.load_manifest(project, 23)["lines_cover_week"] is None


def test_a_failed_fetch_is_not_recorded_as_everyone_healthy(project):
    _capture(project, statuses={}, attempted=True)
    s = pit.load_manifest(project, 3)["injury_statuses"]
    assert s["fetch_attempted"] is True
    assert s["available"] is False


def test_a_missing_input_is_recorded_not_skipped(project):
    (project / "config/ROSTERS.json").unlink()
    dest = _capture(project)
    assert pit.load_manifest(project, 3)["files"]["config/ROSTERS.json"] == {"present": False}
    assert not (dest / "ROSTERS.json").exists()


def test_rerun_replaces_the_capture_and_counts_it(project):
    """The last normal run before publishing is the published one."""
    _capture(project)
    (project / "data/PLAYERLIST.xlsx").write_text("projections v2")
    dest = _capture(project)
    assert (dest / "PLAYERLIST.xlsx").read_text() == "projections v2"
    assert pit.load_manifest(project, 3)["capture_count"] == 2


def test_missing_captures_lists_report_weeks_without_one(project):
    for w in (1, 2, 3):
        _place(project, f"output/stats_report_week{w}.json", "{}")
    _capture(project, week=2)
    assert pit.missing_captures(project) == [1, 3]


def test_step6_only_captures_on_publishable_runs():
    """--fast skips the injury fetch and the sims; its inputs priced nothing."""
    src = (PROJECT_ROOT / "scripts/generate_stats_report.py").read_text()
    assert "capture_week_inputs(" in src
    assert "if args.dry_run or args.repro or args.fast:" in src


# ---------------------------------------------------------------------------
# Integrity: gaps are noticed
# ---------------------------------------------------------------------------

CFG = {"season": {"current_long": "2026-2027"}}


@pytest.fixture
def verify(project, monkeypatch):
    mod = _load("verify_project_integrity")
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    _place(project, "config/SCHEDULE.json", {
        "season_year": "2026-2027",
        "weeks": [{"week": 1, "start_date": "2026-10-20", "end_date": "2026-10-25"},
                  {"week": 23, "start_date": "2027-03-29", "end_date": "2027-04-04"}]})
    return mod


def test_latest_report_without_capture_is_a_failure(project, verify):
    _place(project, "output/stats_report_week1.json", "{}")
    _place(project, "output/stats_report_week2.json", "{}")
    _capture(project, week=1)
    warnings = []
    failures = verify._check_point_in_time_record(CFG, warnings, today=date(2026, 11, 3))
    assert len(failures) == 1 and "stats_report_week2" in failures[0]


def test_older_gaps_are_warnings_because_they_are_already_lost(project, verify):
    _place(project, "output/stats_report_week1.json", "{}")
    _place(project, "output/stats_report_week2.json", "{}")
    _capture(project, week=2)
    warnings = []
    failures = verify._check_point_in_time_record(CFG, warnings, today=date(2026, 11, 3))
    assert failures == []
    assert any("[1]" in w for w in warnings)


@pytest.mark.parametrize("snap_date,today,warns", [
    ("2026-10-27", date(2026, 11, 3), False),
    ("2026-10-20", date(2026, 11, 3), True),    # 14 days: a week was skipped
    ("2026-09-25", date(2026, 10, 6), False),   # preseason: not checked
])
def test_playerlist_snapshot_cadence(project, verify, snap_date, today, warns):
    _place(project, f"config/snapshots/PLAYERLIST_{snap_date}.xlsx")
    warnings = []
    verify._check_point_in_time_record(CFG, warnings, today=today)
    assert any("PLAYERLIST snapshot" in w for w in warnings) == warns


# ---------------------------------------------------------------------------
# INJURY_OVERRIDES has a date
# ---------------------------------------------------------------------------

def _overrides(project, stamp):
    _place(project, "config/INJURY_OVERRIDES.json", {"players": [], "last_updated": stamp})


@pytest.mark.parametrize("stamp,today,expect", [
    ("", date(2026, 9, 30), "quiet"),          # more than 14 days out
    ("", date(2026, 10, 6), "warn"),           # due Oct 18
    ("", date(2026, 10, 20), "fail"),          # Week 1 has begun
    ("2026-10-17", date(2026, 10, 20), "quiet"),
    ("2026-10-17", date(2026, 11, 3), "warn"),  # 17 days stale in season
    ("2026-03-23", date(2026, 10, 20), "fail"),  # last season's file survived
    ("Oct 17", date(2026, 10, 20), "fail"),     # unparseable stamp
])
def test_injury_overrides_gate(project, verify, stamp, today, expect):
    _overrides(project, stamp)
    warnings = []
    failures = verify._check_injury_overrides_current(CFG, warnings, today=today)
    got = "fail" if failures else ("warn" if warnings else "quiet")
    assert got == expect, (failures, warnings)


def test_injury_due_date_is_oct_18_for_this_season(project, verify):
    _overrides(project, "")
    warnings = []
    verify._check_injury_overrides_current(CFG, warnings, today=date(2026, 10, 6))
    assert "2026-10-18" in warnings[0]


def test_injury_gate_stays_quiet_on_another_seasons_schedule(project, verify):
    _overrides(project, "")
    failures = verify._check_injury_overrides_current(
        {"season": {"current_long": "2027-2028"}}, [], today=date(2026, 11, 3))
    assert failures == []


# ---------------------------------------------------------------------------
# The reset archives the captures instead of crashing on the subdirectory
# ---------------------------------------------------------------------------

def test_reset_archives_nested_captures(project, monkeypatch):
    sns = _load("start_new_season")
    monkeypatch.setattr(sns, "PROJECT_ROOT", project)
    _capture(project, week=3)
    _place(project, "config/snapshots/PLAYERLIST_2026-10-27.xlsx")
    files = sns.get_archive_files()
    assert all(f.is_file() for f in files)
    rels = {sns.rel(f) for f in files}
    assert "config/snapshots/point_in_time/report_week03/manifest.json" in rels
    assert "config/snapshots/PLAYERLIST_2026-10-27.xlsx" in rels
    assert sns.archive_phase("2026-27", project / "archive/2026-27", True, False)
    assert (project / "archive/2026-27/config/snapshots/point_in_time/"
            "report_week03/PLAYERLIST.xlsx").is_file()
    deleted = {sns.rel(f) for f in sns.get_delete_files()}
    assert "config/snapshots/point_in_time/report_week03/manifest.json" in deleted
