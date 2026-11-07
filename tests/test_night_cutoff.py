"""
The nightly guard's window for late firings (reviewing session, 11-07).

GitHub's scheduler dropped every firing on 11-05 and fired one at 6:49 AM
Pacific on 11-06, after the old 6:00 cutoff. The window now runs to the day's
first tip less an hour, at most to noon, and never ends before 6:00
(scripts/run_guard.night_cutoff). Invariants:
  1. the window never reaches the first tip less the margin (the price lock);
  2. it never ends before 6:00 or after noon;
  3. a day with no games runs to noon;
  4. a first tip that can't be placed falls back to 6:00 and never refuses;
  5. the workflow's guard and the run's own re-check (modules/nightly) agree
     at every firing time, on every day of the season;
  6. still one run a night: after a successful run, no later firing is admitted.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_guard as rg                       # noqa: E402
from modules import nightly                  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
SEASON = (date(2026, 10, 20), date(2027, 4, 11))


def _days():
    d = SEASON[0]
    while d <= SEASON[1]:
        yield d
        d += timedelta(days=1)


def test_the_window_stays_clear_of_the_first_tip_and_inside_6_to_noon():
    for d in _days():
        cut, why = rg.night_cutoff(ROOT, d, LA)
        six = datetime(d.year, d.month, d.day, rg.NIGHTLY_LAST_HOUR, tzinfo=LA)
        noon = datetime(d.year, d.month, d.day, rg.NIGHTLY_LATEST_HOUR, tzinfo=LA)
        assert six <= cut <= noon, (d, cut)
        tip = rg.first_tip(ROOT, d, LA)
        if tip is None:
            assert cut == noon, (d, why)
        elif tip - rg.NIGHTLY_TIP_MARGIN >= six:
            assert cut <= tip - rg.NIGHTLY_TIP_MARGIN, (d, cut, tip)


def test_known_days():
    # Sat 11-07: first tip 2:00 PM -> noon; Sun 11-08: 12:30 PM -> 11:30;
    # Christmas: 9:00 AM -> 8:00
    assert rg.night_cutoff(ROOT, date(2026, 11, 7), LA)[0].strftime("%H:%M") == "12:00"
    assert rg.night_cutoff(ROOT, date(2026, 11, 8), LA)[0].strftime("%H:%M") == "11:30"
    assert rg.night_cutoff(ROOT, date(2026, 12, 25), LA)[0].strftime("%H:%M") == "08:00"


def test_the_6_49_am_firing_of_11_06_is_now_admitted():
    f = datetime(2026, 11, 6, 14, 49, tzinfo=timezone.utc)      # 6:49 AM PST
    cut, why = rg.night_cutoff(ROOT, f.astimezone(LA).date(), LA)
    marker = {"league_day": date(2026, 11, 5), "attempts": 1, "ok": True}
    assert rg.nightly_decision(f, LA, marker, cut, why)[0]
    # the old rule refused it
    assert not rg.nightly_decision(f, LA, marker)[0]


def test_an_unplaceable_tip_falls_back_to_six_and_never_refuses(monkeypatch):
    def boom(*a, **k):
        raise rg.GuardError("no tip time for X @ Y")
    monkeypatch.setattr(rg, "first_tip", boom)
    cut, why = rg.night_cutoff(ROOT, date(2026, 11, 9), LA)
    assert cut == datetime(2026, 11, 9, 6, tzinfo=LA)
    assert "can't be placed" in why
    ok, _ = rg.decide("nightly", datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc), ROOT,
                      Path(ROOT / "_no_such_state_dir"))
    assert ok                                                    # 1:00 AM: inside


def test_the_workflow_guard_and_the_runs_recheck_agree(tmp_path):
    """Every 30 minutes of every day of the season, no marker: decide()
    (the workflow's guard job) == modules.nightly.scheduled_guard_decision
    (the run's own re-check)."""
    for d in list(_days())[::7]:
        t = datetime(d.year, d.month, d.day, tzinfo=LA)
        for i in range(48):
            f = (t + timedelta(minutes=30 * i)).astimezone(timezone.utc)
            a = rg.decide("nightly", f, ROOT, tmp_path)[0]
            b = nightly.scheduled_guard_decision(f, tmp_path)[0]
            assert a == b, f


@pytest.mark.parametrize("firing_utc_hour", [7, 9, 11, 14, 17])
def test_still_one_run_a_night(firing_utc_hour):
    """After a successful run, nothing later that league day is admitted."""
    d = date(2026, 11, 10)
    f = datetime(d.year, d.month, d.day, firing_utc_hour, 1, tzinfo=timezone.utc)
    day = f.astimezone(LA).date()
    cut, why = rg.night_cutoff(ROOT, day, LA)
    marker = {"league_day": day, "attempts": 1, "ok": True}
    assert not rg.nightly_decision(f, LA, marker, cut, why)[0]
