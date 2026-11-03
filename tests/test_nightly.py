"""
Step 1c-i: the nightly run (modules/nightly.py, scripts/nightly.py).

Invariants (HANDOFF_STEP1C1 s.7):
  1. a refused step leaves every output of the last good run byte-identical,
     and exits 1;
  2. a lock exits 0 and prices nothing (no line, no title odds, no
     calibration record);
  3. the scheduled guard admits exactly one of the two firings per day,
     across both DST changes;
  9. every new file is classified in the manifest;
 10. logs are pulled across a week boundary (a Monday run pulls Sunday).
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import nightly                  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")


# =============================================================================
# 3. the scheduled guard
# =============================================================================

def test_the_guard_admits_exactly_one_firing_every_day_of_the_season():
    day = date(2026, 10, 1)
    seen = {}
    while day <= date(2027, 4, 30):
        firings = [datetime(day.year, day.month, day.day, h, 1, tzinfo=timezone.utc) for h in (7, 8)]
        admitted = [f for f in firings if nightly.scheduled_guard_admits(f)]
        assert len(admitted) == 1, (day, firings)
        seen[day] = admitted[0].hour
        day += timedelta(days=1)
    # the two DST changes: 11-01-2026 (fall back) and 03-14-2027 (spring forward)
    assert seen[date(2026, 11, 1)] == 7 and seen[date(2026, 11, 2)] == 8
    assert seen[date(2027, 3, 13)] == 8 and seen[date(2027, 3, 14)] == 8 and seen[date(2027, 3, 15)] == 7
    # the admitted firing is 12:01 AM on the league clock
    for d, h in seen.items():
        t = datetime(d.year, d.month, d.day, h, 1, tzinfo=timezone.utc).astimezone(LA)
        assert (t.hour, t.minute) == (0, 1)


def test_the_guard_needs_an_aware_time():
    with pytest.raises(ValueError):
        nightly.scheduled_guard_admits(datetime(2026, 11, 3, 7, 1))


# =============================================================================
# 1. a refused step
# =============================================================================

def _outputs(base: Path) -> dict:
    return {p.relative_to(base).as_posix(): p.read_bytes()
            for p in base.rglob("*") if p.is_file() and p.name != "nightly_runs.jsonl"}


def test_a_refused_step_leaves_the_last_good_outputs_and_exits_1(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    for name in ("live_lines_week3.json", "title_odds_latest.json", "stakes.json", "hub_state.json",
                 "title_odds_history.jsonl"):
        (out / name).write_text(f"last good {name}\n", encoding="utf-8")
    before = _outputs(tmp_path)
    called = []

    def writes(name):
        def fn():
            called.append(name)
            (out / f"{name}.written").write_text("x", encoding="utf-8")
            return "wrote"
        return fn

    def refuse():
        called.append("settings")
        raise nightly.StepRefused("Yahoo setting max_weekly_adds changed from 6 to 4")

    steps = {n: writes(n) for n in nightly.STEPS["nightly"]}
    steps["settings"] = refuse
    run = nightly.Run(tmp_path, "nightly", now=datetime(2026, 11, 4, 0, 1, tzinfo=LA), echo=lambda *a: None)
    row = run.execute(steps)
    assert called == ["engine", "logs", "sync", "settings"]           # stopped at the refusal
    assert (row["exit"], row["outcome"]) == (1, "refused")
    assert "max_weekly_adds" in row["error"]
    assert [s["step"] for s in row["steps"]] == called and row["steps"][-1]["outcome"] == "refused"
    after = _outputs(tmp_path)
    for k, v in before.items():
        assert after[k] == v, k                                       # the last good run's outputs
    for n in ("tags", "line", "title_odds", "actuals", "hub"):
        assert f"output/{n}.written" not in after, n
    rec = [json.loads(ln) for ln in (out / "nightly_runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rec[-1]["run_id"] == row["run_id"] and rec[-1]["exit"] == 1


def test_a_good_run_is_recorded_with_every_step_and_exits_0(tmp_path):
    steps = {n: (lambda n=n: f"{n} done") for n in nightly.STEPS["nightly"]}
    run = nightly.Run(tmp_path, "nightly", now=datetime(2026, 11, 4, 0, 1, tzinfo=LA), echo=lambda *a: None)
    row = run.execute(steps)
    assert (row["exit"], row["outcome"], row["error"]) == (0, "ok", None)
    assert [s["step"] for s in row["steps"]] == list(nightly.STEPS["nightly"])
    assert all(isinstance(s["seconds"], float) for s in row["steps"])
    assert row["started_at"] <= row["finished_at"]


# =============================================================================
# 2. a lock
# =============================================================================

def test_a_lock_exits_0_and_prices_nothing(tmp_path, monkeypatch):
    """The line step reports a lock (refresh_service prices nothing then);
    the title-odds step then prices nothing either, and the run exits 0."""
    from modules import title_odds_run as tor, calibration_log as cal
    calls = []
    monkeypatch.setattr(tor, "price", lambda *a, **k: calls.append("title odds priced"))

    def locked_line():
        run.ctx["locked"] = True
        return "locked"

    steps = {n: (lambda n=n: n) for n in nightly.STEPS["nightly"]}
    steps["line"] = locked_line
    del steps["title_odds"]                     # the real step
    run = nightly.Run(tmp_path, "nightly", now=datetime(2026, 11, 4, 17, 0, tzinfo=LA),
                      echo=lambda *a: None)
    run.week = 3
    row = run.execute(steps)
    assert (row["exit"], row["outcome"]) == (0, "locked")
    assert calls == []
    title = next(s for s in row["steps"] if s["step"] == "title_odds")
    assert title["detail"] == "locked: nothing priced"
    assert not (tmp_path / tor.LATEST_FILE).exists() and not (tmp_path / tor.STAKES_FILE).exists()
    assert not (tmp_path / cal.LOG_RELPATH).exists()


def test_refresh_service_prices_nothing_while_locked():
    """The line step is refresh_service.run, whose lock prices no line and no
    calibration record (1a, tests/test_price_lock.py); the nightly run passes
    its own clock through so the lock is judged at the run's moment."""
    import inspect
    src = inspect.getsource(nightly.Run.step_line)
    assert "now=self.now" in src and "pull_logs=False" in src and "statuses=self.ctx[\"tags\"]" in src


# =============================================================================
# 10. logs across a week boundary
# =============================================================================

def test_a_monday_run_pulls_sunday_of_the_previous_week(monkeypatch):
    import refresh_service as rs
    from modules import simulator_betting as sb
    from modules.data_loader import MANAGERS
    monkeypatch.setattr(sb, "_playing_teams", lambda data, d: frozenset({"AAA"}))
    weeks = [{"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01"},
             {"week": 3, "start_date": "2026-11-02", "end_date": "2026-11-08"}]
    covered = [date(2026, 10, 26) + timedelta(days=i) for i in range(6)]       # through Saturday 10-31
    lu = pd.DataFrame([{"date": d.isoformat(), "manager": m} for d in covered for m in MANAGERS])
    data = SimpleNamespace(lineups=lu, schedule={"weeks": weeks})
    # Monday 11-02's run: Sunday 11-01 is week 2's last day, and it is pulled
    assert rs.missing_days(data, date(2026, 11, 2)) == [date(2026, 11, 1)]
    # the one-week function the service used before step 1c did not see it
    monkeypatch.setattr(rs.ws, "week_entry", lambda data, w: next(x for x in weeks if x["week"] == w))
    assert rs.days_to_pull(data, 3, date(2026, 11, 2)) == []
    # a manager missing on a day is that day, too
    lu2 = lu[~((lu["date"] == "2026-10-28") & (lu["manager"] == MANAGERS[0]))]
    assert rs.missing_days(SimpleNamespace(lineups=lu2, schedule={"weeks": weeks}), date(2026, 11, 2)) == \
        [date(2026, 10, 28), date(2026, 11, 1)]


def test_the_service_pulls_across_the_week_boundary():
    import inspect
    import refresh_service as rs
    assert "missing_days(data, as_of)" in inspect.getsource(rs.run)


# =============================================================================
# 9. the manifest
# =============================================================================

NEW_FILES = ("output/nightly_runs.jsonl", "data/transaction_log.jsonl", "output/title_odds_latest.json",
             "output/stakes.json", "output/tag_records.jsonl", "output/closing_line_week4.json",
             "config/.leaguehistory_applied_weeks.json")


def test_every_new_file_is_league_state_and_ignored():
    import subprocess
    from modules import state_manifest as sm
    man = sm.load(ROOT)
    for p in NEW_FILES:
        assert man.contains(p), p
    r = subprocess.run(["git", "check-ignore", "--no-index", *NEW_FILES], cwd=str(ROOT),
                       capture_output=True, text=True)
    assert sorted(r.stdout.split()) == sorted(NEW_FILES), r.stdout


def test_the_pretip_run_refuses_off_monday_and_after_the_first_tip(monkeypatch):
    from modules import price_lock, data_loader, week_state
    world = SimpleNamespace(nba_schedule={})
    monkeypatch.setattr(data_loader, "load_all_data", lambda *a, **k: world)
    monkeypatch.setattr(week_state, "week_for_date", lambda data, d: 3)
    monkeypatch.setattr(week_state, "week_entry", lambda data, w: {"start_date": "2026-11-02"})
    monkeypatch.setattr(price_lock, "first_tip",
                        lambda d, s=None: datetime(2026, 11, 2, 16, 0, tzinfo=LA))
    tue = nightly.Run(".", "pretip", now=datetime(2026, 11, 3, 9, 0, tzinfo=LA), echo=lambda *a: None)
    with pytest.raises(nightly.StepRefused, match="window day"):
        tue.step_window()
    late = nightly.Run(".", "pretip", now=datetime(2026, 11, 2, 16, 5, tzinfo=LA), echo=lambda *a: None)
    with pytest.raises(nightly.StepRefused, match="before Monday's first tip"):
        late.step_window()
    ok = nightly.Run(".", "pretip", now=datetime(2026, 11, 2, 15, 0, tzinfo=LA), echo=lambda *a: None)
    assert "week 3" in ok.step_window() and ok.week == 3


def test_the_engine_step_refuses_a_dirty_engine_unless_allowed(monkeypatch):
    from modules import calibration_log as cal
    monkeypatch.setattr(cal, "engine_version", lambda base=".": {"commit": "abc1234", "dirty": True})
    with pytest.raises(nightly.StepRefused, match="dirty"):
        nightly.Run(".", "nightly", echo=lambda *a: None).step_engine()
    assert "allow-dirty" in nightly.Run(".", "nightly", allow_dirty_engine=True,
                                        echo=lambda *a: None).step_engine()
    monkeypatch.setattr(cal, "engine_version", lambda base=".": {"commit": None, "dirty": False})
    with pytest.raises(nightly.StepRefused, match="unknown"):
        nightly.Run(".", "nightly", echo=lambda *a: None).step_engine()
