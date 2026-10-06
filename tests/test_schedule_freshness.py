"""A3: the NBA schedule cannot go stale, or be half-replaced, silently."""
import importlib.util
import json
import os
from datetime import date, datetime
from pathlib import Path

import pytest

from modules import schedule_freshness as sf

ROOT = Path(__file__).parent.parent
SEASON = (date(2026, 10, 20), date(2027, 4, 4))


def g(d, home, away):
    return {"date": f"{d}T00:00:00Z", "home": home, "away": away}


def test_diff_finds_added_removed_and_moved():
    old = {"games": [g("2026-11-01", "BOS", "NYK"), g("2026-11-02", "LAL", "GSW"),
                     g("2026-11-03", "MIA", "ORL")]}
    new = {"games": [g("2026-11-01", "BOS", "NYK"), g("2026-11-09", "LAL", "GSW"),
                     g("2026-12-15", "DEN", "PHX")]}
    d = sf.diff_schedules(old, new)
    assert d["moved"] == [{"home": "LAL", "away": "GSW", "from": "2026-11-02", "to": "2026-11-09"}]
    assert d["removed"] == [{"home": "MIA", "away": "ORL", "date": "2026-11-03"}]
    assert d["added"] == [{"home": "DEN", "away": "PHX", "date": "2026-12-15"}]


def test_a_pair_meeting_twice_moves_the_right_game():
    """Same home/away pair, two meetings: only the one that changed moves."""
    old = {"games": [g("2026-11-01", "BOS", "NYK"), g("2027-02-01", "BOS", "NYK")]}
    new = {"games": [g("2026-11-01", "BOS", "NYK"), g("2027-02-05", "BOS", "NYK")]}
    assert sf.diff_schedules(old, new)["moved"] == [
        {"home": "BOS", "away": "NYK", "from": "2027-02-01", "to": "2027-02-05"}]


def test_identical_schedules_have_no_changes():
    s = {"games": [g("2026-11-01", "BOS", "NYK")]}
    d = sf.diff_schedules(s, s)
    assert d["added"] == d["removed"] == d["moved"] == []


def test_changes_near_today_are_singled_out():
    d = {"added": [g("2027-03-01", "BOS", "NYK") | {"date": "2027-03-01"}],
         "removed": [{"home": "LAL", "away": "GSW", "date": "2026-11-05"}],
         "moved": [{"home": "MIA", "away": "ORL", "from": "2026-12-20", "to": "2026-11-04"}]}
    near = sf.changes_within(d, date(2026, 11, 1), days=14)
    assert len(near) == 2 and not any("2027-03-01" in x for x in near)


def test_a_partial_fetch_is_refused():
    old = {"games": [g("2026-11-01", "BOS", "NYK")] * 100}
    assert sf.shrink_problem(sf.diff_schedules(old, {"games": old["games"][:85]}))
    assert sf.shrink_problem(sf.diff_schedules(old, {"games": old["games"][:95]})) is None


def test_stamp_dates_the_data_not_the_file(tmp_path):
    s = sf.stamp({"games": []}, "bbref", now=datetime(2026, 11, 2, 8, 0))
    path = tmp_path / "s.json"
    path.write_text(json.dumps(s))
    os.utime(path, (0, 0))                   # a copy / checkout resets mtime
    assert sf.fetched_on(s, path) == (date(2026, 11, 2), "fetched_at")


def test_unstamped_file_falls_back_to_mtime(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{}")
    when, how = sf.fetched_on({}, path)
    assert how == "file mtime" and when == date.today()


@pytest.mark.parametrize("fetched,today,stale", [
    ("2026-10-01", date(2026, 10, 10), False),   # preseason: not checked
    ("2026-10-25", date(2026, 11, 2), False),    # 8 days: allowed
    ("2026-10-24", date(2026, 11, 2), True),     # 9 days: refused
    ("2027-03-01", date(2027, 4, 20), False),    # season over
])
def test_stale_guard_only_bites_in_season(fetched, today, stale):
    s = {"games": [], "fetched_at": f"{fetched}T09:00:00"}
    assert bool(sf.stale_problem(s, None, SEASON, today=today)) == stale


def test_no_season_window_means_no_guard():
    assert sf.stale_problem({"games": []}, None, None, today=date(2026, 11, 2)) is None


def test_step6_refuses_and_records_the_override():
    src = (ROOT / "scripts/generate_stats_report.py").read_text()
    assert "--allow-stale-schedule" in src
    assert "None if args.repro else stale_problem(" in src
    assert '"stale_schedule_override": stale' in src


def test_fetch_refuses_a_shrink_without_force():
    src = (ROOT / "scripts/fetch_nba_schedule.py").read_text()
    assert "problem and not args.force" in src
    assert "trimmed = stamp(trimmed, source)" in src


def test_integrity_warns_on_a_stale_schedule(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "vpi", ROOT / "scripts" / "verify_project_integrity.py")
    vpi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vpi)
    monkeypatch.setattr(vpi, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config/SCHEDULE.json").write_text(json.dumps({
        "season_year": "2026-2027",
        "weeks": [{"week": 1, "start_date": "2026-10-20", "end_date": "2026-10-25"},
                  {"week": 23, "start_date": "2027-03-29", "end_date": "2027-04-04"}]}))
    (tmp_path / "data/nba.json").write_text(json.dumps(
        {"games": [], "fetched_at": "2026-10-01T09:00:00"}))
    cfg = {"season": {"current_long": "2026-2027", "nba_schedule_file": "data/nba.json"}}
    warnings = []
    assert vpi._check_nba_schedule_fresh(cfg, warnings, today=date(2026, 11, 2)) == []
    assert len(warnings) == 1 and "Step 6 will refuse" in warnings[0]
