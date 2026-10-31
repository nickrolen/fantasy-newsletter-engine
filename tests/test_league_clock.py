"""The league's clock is Portland's (Nick, 10-30; LEAGUE_RULES rule 0).

Every date taken from "now" or from a Yahoo timestamp must be the league's
day, whatever clock the machine running the engine keeps: Nick's desktop is
on Phoenix time, a cloud runner on UTC. These tests run the same moves on
both and require the same answer.
"""

import copy
import importlib.util
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from modules import data_loader as dl
from modules import league_clock as lc
from modules import roster_plan

ROOT = Path(__file__).resolve().parent.parent
LA = ZoneInfo("America/Los_Angeles")
PHX = ZoneInfo("America/Phoenix")


def _ts(dt: datetime) -> int:
    return int(dt.timestamp())


@pytest.fixture(params=["UTC", "America/Phoenix", "America/New_York"])
def machine_clock(request):
    """Run the test as if the machine's own clock were this zone."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX-only; the zone-independence check runs in CI")
    old = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield request.param
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_config_states_portland_time():
    assert dl.league_rule("league_structure", "time_zone") == "America/Los_Angeles"


def test_a_missing_zone_raises_never_defaults(monkeypatch):
    cfg = copy.deepcopy(dl._LEAGUE_CONFIG)
    del cfg["league_structure"]["time_zone"]
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", cfg)
    with pytest.raises(dl.UnspecifiedRule):
        lc.league_tz()
    with pytest.raises(dl.UnspecifiedRule):
        lc.league_today()


@pytest.mark.parametrize("when, league_day", [
    # Sunday 11:30 PM Pacific, standard time (after the 11-01 fall-back).
    (datetime(2026, 11, 1, 23, 30, tzinfo=LA), date(2026, 11, 1)),
    # Sunday 11:30 PM Pacific, daylight time.
    (datetime(2026, 10, 25, 23, 30, tzinfo=LA), date(2026, 10, 25)),
    # 12:30 AM Monday in Phoenix in winter is still Sunday in the league.
    (datetime(2026, 11, 2, 0, 30, tzinfo=PHX), date(2026, 11, 1)),
    # 12:01 AM Monday Pacific is Monday.
    (datetime(2026, 11, 2, 0, 1, tzinfo=LA), date(2026, 11, 2)),
])
def test_a_timestamp_is_dated_on_the_league_clock(machine_clock, when, league_day):
    assert lc.league_date_of_timestamp(_ts(when)) == league_day


def test_the_fantasy_week_follows_the_league_day(machine_clock):
    schedule = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    sunday_late = lc.league_date_of_timestamp(_ts(datetime(2026, 11, 2, 0, 30, tzinfo=PHX)))
    monday = lc.league_date_of_timestamp(_ts(datetime(2026, 11, 2, 0, 1, tzinfo=LA)))
    assert roster_plan.fantasy_week_on(schedule, sunday_late) == 2
    assert roster_plan.fantasy_week_on(schedule, monday) == 3


def test_a_timestamp_that_is_not_a_number_raises():
    for bad in (None, "", "yesterday"):
        with pytest.raises(ValueError):
            lc.league_date_of_timestamp(bad)


def test_league_now_is_aware_and_pacific():
    now = lc.league_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == now.astimezone(LA).utcoffset()


def _sync_transactions():
    spec = importlib.util.spec_from_file_location(
        "sync_transactions_under_test", ROOT / "scripts" / "sync_transactions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sync_dates_transactions_on_the_league_clock(machine_clock):
    st = _sync_transactions()
    ts = _ts(datetime(2026, 11, 2, 0, 30, tzinfo=PHX))
    assert st.parse_transaction_date(ts) == date(2026, 11, 1)


def test_sync_refuses_an_unparseable_date_instead_of_calling_it_today():
    st = _sync_transactions()
    with pytest.raises(ValueError):
        st.parse_transaction_date("not a date")


# Every module that decides a league day: none may ask the machine's clock.
LEAGUE_DAY_FILES = [
    "scripts/sync_transactions.py",
    "scripts/refresh_service.py",
    "scripts/refresh_lines.py",
    "scripts/render_live_lines.py",
    "scripts/update_fantasy_logs.py",
    "scripts/overrides.py",
    "modules/roster_plan.py",
    "modules/season_performers.py",
]
MACHINE_CLOCK = re.compile(r"\bdate\.today\(\)|\bdatetime\.now\(\)|\.fromtimestamp\(")


@pytest.mark.parametrize("rel", LEAGUE_DAY_FILES)
def test_no_league_day_module_reads_the_machine_clock(rel):
    hits = [f"{rel}:{n}: {line.strip()}"
            for n, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1)
            if MACHINE_CLOCK.search(line)]
    assert not hits, "use modules/league_clock.py:\n" + "\n".join(hits)


def test_requirements_carry_tzdata_for_windows():
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^tzdata\b", reqs, re.M)
