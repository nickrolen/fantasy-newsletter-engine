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

def _night_firings(day):
    """The nightly cron's firings ('1,31 7-11 * * *', UTC) on a UTC day."""
    return [datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc)
            for h in range(7, 12) for m in (1, 31)]


def test_one_run_a_night_every_night_of_the_season(tmp_path):
    """11-05: GitHub never fired the first scheduled night. Firings every 30
    minutes; the guard admits the first one after midnight (league clock)
    that finds tonight's run hasn't happened, and none after it once the
    run succeeds -- on every night, across both DST changes."""
    from modules import nightly as N
    rg = N.run_guard()
    day, marker, admitted_at = date(2026, 10, 1), None, {}
    while day <= date(2027, 4, 30):
        for f in _night_firings(day):
            if rg.nightly_decision(f, LA, marker)[0]:
                league_day = f.astimezone(LA).date()
                assert league_day not in admitted_at, (league_day, f)
                admitted_at[league_day] = f.astimezone(LA)
                marker = {"league_day": league_day, "attempts": 1, "ok": True}
        day += timedelta(days=1)
    for d in (date(2026, 10, 2), date(2026, 11, 1), date(2026, 11, 2), date(2027, 3, 14), date(2027, 3, 15)):
        t = admitted_at[d]
        assert t.date() == d and (t.hour, t.minute) in ((0, 1), (0, 31)), (d, t)
    assert len(admitted_at) >= 210


def test_a_late_or_dropped_firing_only_delays_the_night():
    from modules import nightly as N
    rg = N.run_guard()
    f = datetime(2026, 11, 6, 10, 31, tzinfo=timezone.utc)        # 2:31 AM PST, the earlier ones lost
    assert rg.nightly_decision(f, LA, {"league_day": date(2026, 11, 5), "attempts": 1, "ok": True})[0]
    assert not rg.nightly_decision(f, LA, {"league_day": date(2026, 11, 6), "attempts": 1, "ok": True})[0]
    six = datetime(2026, 11, 6, 14, 1, tzinfo=timezone.utc)       # 6:01 AM PST: too late
    assert not rg.nightly_decision(six, LA, None)[0]


def test_a_failed_night_is_retried_once():
    from modules import nightly as N
    rg = N.run_guard()
    f = datetime(2026, 11, 6, 9, 1, tzinfo=timezone.utc)
    d = date(2026, 11, 6)
    assert rg.nightly_decision(f, LA, {"league_day": d, "attempts": 1, "ok": False})[0]
    assert not rg.nightly_decision(f, LA, {"league_day": d, "attempts": 2, "ok": False})[0]


def test_a_marker_from_the_future_or_malformed_raises(tmp_path):
    from modules import nightly as N
    rg = N.run_guard()
    f = datetime(2026, 11, 6, 9, 1, tzinfo=timezone.utc)
    with pytest.raises(rg.GuardError):
        rg.nightly_decision(f, LA, {"league_day": date(2026, 11, 7), "attempts": 1, "ok": True})
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "nightly_last.json").write_text('{"league_day": "2026-11-06"}', encoding="utf-8")
    with pytest.raises(rg.GuardError):
        rg.read_marker(tmp_path)


def test_record_night_counts_attempts_and_keeps_success(tmp_path):
    from modules import nightly as N
    at = lambda h, m=0: datetime(2026, 11, 6, h, m, tzinfo=LA)
    m1 = N.record_night(tmp_path, {"run_id": "a"}, ok=False, now=at(0, 1))
    assert (m1["attempts"], m1["ok"]) == (1, False)
    m2 = N.record_night(tmp_path, {"run_id": "b"}, ok=True, now=at(0, 31))
    assert (m2["attempts"], m2["ok"]) == (2, True)
    m3 = N.record_night(tmp_path, {"run_id": "c"}, ok=False, now=at(7, 40))   # a forced run later that day
    assert (m3["attempts"], m3["ok"]) == (3, True)
    m4 = N.record_night(tmp_path, {"run_id": "d"}, ok=True, now=datetime(2026, 11, 7, 0, 1, tzinfo=LA))
    assert (m4["league_day"], m4["attempts"]) == ("2026-11-07", 1)
    assert N.run_guard().read_marker(tmp_path)["league_day"] == date(2026, 11, 7)


def test_the_marker_is_league_state_and_ignored():
    import subprocess
    from modules import state_manifest as sm
    root = Path(__file__).resolve().parents[1]
    rel = "output/nightly_last.json"
    assert sm.load(root).contains(rel)
    r = subprocess.run(["git", "check-ignore", "--no-index", rel], cwd=str(root), capture_output=True, text=True)
    assert r.stdout.split() == [rel]


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
    # stopped at the refusal (task 49: the trade block's upkeep follows the sync)
    assert called == ["engine", "logs", "sync", "trade_block", "settings"]
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


def test_a_child_that_prints_an_accented_name_does_not_die_on_the_code_page(tmp_path, monkeypatch):
    """11-03, Nick's machine: fetch_playerlist died printing an accented name
    into the pipe (Windows writes a pipe in cp1252). Force the worst case --
    the parent's environment asking for cp1252 -- and the child must still
    print it, and the parent must read it back intact."""
    from modules import nightly
    script = tmp_path / "child.py"
    script.write_text('print("Nikola Joki\\u0107")\n', encoding="utf-8")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    out = nightly._subprocess(tmp_path, [str(script)], "child")
    assert "Joki\u0107" in out
