"""Tip times and the price lock (step 1a; design s.4.1, invariant 16).

Lines and title odds do not re-price from the first tip of a league day until
that day ends (Nick, 10-31). modules/price_lock.py decides it, from each
game's tip time, which scripts/fetch_nba_schedule.py now keeps. Every test
here runs the REAL lock (marker real_price_lock; tests/conftest.py gives
every other test unlocked prices so none depends on the hour it runs at).
"""
import ast
import copy
import importlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from modules import price_lock as pl                      # noqa: E402
from league_state import needs_state                      # noqa: E402

fns = importlib.import_module("fetch_nba_schedule")
rl = importlib.import_module("refresh_lines")
rs = importlib.import_module("refresh_service")

pytestmark = pytest.mark.real_price_lock

LA, NY = ZoneInfo("America/Los_Angeles"), ZoneInfo("America/New_York")
UTC = timezone.utc


def tip(day, hh, mm=0, zone=LA):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone).astimezone(UTC) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")


def g(day, home, away, t):
    return {"date": f"{day.isoformat()}T00:00:00Z", "home": home, "away": away, "tip_utc": t}


SAT, SUN, MON, WED = date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 4)
MON30 = date(2026, 11, 30)
SCHED = {"games": [
    g(SAT, "BOS", "NYK", tip(SAT, 16, 30)), g(SAT, "LAL", "GSW", tip(SAT, 19, 30)),
    g(SAT, "DEN", "PHX", tip(SAT, 18, 0)),
    g(SUN, "ORL", "BOS", tip(SUN, 12, 30)), g(SUN, "LAL", "TOR", tip(SUN, 18, 0)),
    g(MON, "CLE", "OKC", tip(MON, 16, 0)), g(MON, "POR", "SAC", tip(MON, 19, 0)),
    g(MON30, "MIA", "ATL", tip(MON30, 16, 30)), g(MON30, "LAC", "DAL", tip(MON30, 19, 30)),
]}                                                        # no games on WED


def at(day, hh, mm=0, zone=LA):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone)


# ======================================================== 1. tip times at fetch

@pytest.mark.parametrize("day, text, want", [
    (date(2026, 10, 31), "7:30p", "2026-10-31T23:30:00Z"),   # EDT, before the 11-01 change
    (date(2026, 11, 2), "7:30p", "2026-11-03T00:30:00Z"),    # EST, after it
    (date(2027, 3, 13), "7:00p", "2027-03-14T00:00:00Z"),    # EST, before the 03-14 change
    (date(2027, 3, 15), "7:00p", "2027-03-15T23:00:00Z"),    # EDT, after it
    (date(2026, 11, 1), "12:00p", "2026-11-01T17:00:00Z"),   # noon
    (date(2026, 11, 1), "10:30p", "2026-11-02T03:30:00Z"),   # late: still 11-01 in Portland
])
def test_bbref_start_times_go_through_the_zone_database(day, text, want):
    assert fns.bbref_tip_utc(day, text) == want
    assert fns.tip_league_date(want) == day


@pytest.mark.parametrize("text", ["", "TBD", "  ", "<span></span>"])
def test_a_game_with_no_time_is_null_never_guessed(text):
    assert fns.bbref_tip_utc(date(2026, 12, 9), text) is None


@pytest.mark.parametrize("text", ["7:30", "19:30", "noon", "7:75p"])
def test_an_unrecognised_time_raises(text):
    with pytest.raises(fns.TipCheckFailed):
        fns.bbref_tip_utc(date(2026, 12, 9), text)


def test_a_tip_off_its_listed_date_raises_naming_the_game():
    games = [g(SAT, "BOS", "NYK", tip(SAT, 16)), g(SAT, "LAL", "GSW", tip(SUN, 16))]
    with pytest.raises(fns.TipCheckFailed, match="GSW @ LAL listed 2026-10-31"):
        fns.check_tips(games)


def test_the_bbref_parser_keeps_every_games_time_and_a_page_without_times_raises():
    row = ('<tr><th data-stat="date_game"><a>Mon, Nov 2, 2026</a></th>'
           '<td data-stat="game_start_time">7:00p</td>'
           '<td data-stat="visitor_team_name"><a href="/teams/OKC/2027.html">OKC</a></td>'
           '<td data-stat="home_team_name"><a href="/teams/CLE/2027.html">CLE</a></td></tr>')
    page = f'<table id="schedule">{row}{row.replace("7:00p", "")}</table>'
    games = fns._parse_bbref_month(page, 2027)
    assert [x["tip_utc"] for x in games] == ["2026-11-03T00:00:00Z", None]
    with pytest.raises(fns.TipCheckFailed, match="no Start"):
        fns._parse_bbref_month(page.replace('data-stat="game_start_time"', 'data-stat="x"'), 2027)


def test_trimming_keeps_the_tip_and_the_nba_source_sets_it():
    assert fns.trim_schedule({"games": [g(SAT, "BOS", "NYK", "2026-10-31T20:30:00Z")]}) \
        ["games"][0]["tip_utc"] == "2026-10-31T20:30:00Z"
    nba = {"leagueSchedule": {"gameDates": [{"games": [
        {"gameDateEst": "2026-11-02T00:00:00Z", "gameDateTimeUTC": "2026-11-03T00:00:00Z",
         "homeTeam": {"teamTricode": "CLE"}, "awayTeam": {"teamTricode": "OKC"}},
        {"gameDateEst": "2026-12-09T00:00:00Z", "gameDateTimeUTC": "2026-12-09T00:00:00Z",
         "gameStatusText": "TBD", "homeTeam": {"teamTricode": "X"},
         "awayTeam": {"teamTricode": "Y"}}]}]}}
    out = fns.trim_schedule(nba)["games"]
    assert out[0]["tip_utc"] == "2026-11-03T00:00:00Z" and out[1]["tip_utc"] is None


def test_tips_only_changes_nothing_but_the_new_field():
    old = {"fetched_at": "2026-10-29T16:35:10", "source": "bbref",
           "games": [{"date": "2026-10-31T00:00:00Z", "home": "BOS", "away": "NYK"},
                     {"date": "2026-11-02T00:00:00Z", "home": "CLE", "away": "OKC"}]}
    new = {"games": [g(MON, "CLE", "OKC", tip(MON, 16)), g(SAT, "BOS", "NYK", None)]}
    merged, problems = fns.add_tips_only(old, new)
    assert problems == []
    assert [{k: v for k, v in x.items() if k != "tip_utc"} for x in merged["games"]] == old["games"]
    assert [x["tip_utc"] for x in merged["games"]] == [None, tip(MON, 16)]
    assert merged["fetched_at"] == old["fetched_at"]


def test_tips_only_stops_on_any_moved_added_or_removed_game():
    old = {"games": [{"date": "2026-10-31T00:00:00Z", "home": "BOS", "away": "NYK"},
                     {"date": "2026-11-02T00:00:00Z", "home": "CLE", "away": "OKC"}]}
    moved = {"games": [g(SAT, "BOS", "NYK", None), g(WED, "CLE", "OKC", None),
                       g(WED, "MIA", "ATL", None)]}
    _, problems = fns.add_tips_only(old, moved)
    assert any("not in the refetch: 2026-11-02 OKC @ CLE" in p for p in problems)
    assert any("not in the file: 2026-11-04 OKC @ CLE" in p for p in problems)
    assert any("not in the file: 2026-11-04 ATL @ MIA" in p for p in problems)


# ============================================================== 2. the lock

def test_locked_from_the_first_tip_until_the_league_day_ends():
    assert pl.first_tip(SAT, SCHED) == at(SAT, 16, 30)
    assert not pl.is_locked(at(SAT, 16, 29), SCHED)
    assert pl.is_locked(at(SAT, 16, 30), SCHED)
    assert pl.is_locked(at(SAT, 20, 15), SCHED)          # mid-evening
    assert pl.is_locked(at(SAT, 23, 59), SCHED)          # after the last game, still the day


def test_the_1201_run_is_unlocked_on_both_sides_of_the_11_01_change():
    sun_0001 = datetime(2026, 11, 1, 0, 1, tzinfo=LA)    # PDT, before 2 AM falls back
    mon_0001 = datetime(2026, 11, 2, 0, 1, tzinfo=LA)    # PST
    assert sun_0001.utcoffset() == timedelta(hours=-7) and mon_0001.utcoffset() == timedelta(hours=-8)
    assert not pl.is_locked(sun_0001, SCHED) and not pl.is_locked(mon_0001, SCHED)
    # judged on the league clock whatever zone the caller's datetime is in
    assert not pl.is_locked(mon_0001.astimezone(ZoneInfo("America/Phoenix")), SCHED)
    assert pl.is_locked(datetime(2026, 11, 3, 4, 0, tzinfo=UTC), SCHED)   # Mon 8 PM PST


def test_a_day_with_no_games_is_never_locked():
    for hh in (0, 12, 19, 23):
        assert not pl.is_locked(at(WED, hh), SCHED)
    assert pl.first_tip(WED, SCHED) is None and pl.last_tip(WED, SCHED) is None


def test_a_null_tip_raises_naming_the_day_and_the_game():
    s = copy.deepcopy(SCHED)
    s["games"][1]["tip_utc"] = None
    with pytest.raises(pl.TipTimeMissing, match=r"2026-10-31: no tip time for GSW @ LAL"):
        pl.is_locked(at(SAT, 9), s)
    s["games"][6].pop("tip_utc")                         # a file fetched before tips were kept
    with pytest.raises(pl.TipTimeMissing, match=r"2026-11-02: no tip time for SAC @ POR"):
        pl.window_close(MON, s)


def test_a_naive_time_is_refused():
    with pytest.raises(ValueError, match="aware"):
        pl.is_locked(datetime(2026, 10, 31, 20, 0), SCHED)


@pytest.mark.parametrize("day, last", [(MON, (19, 0)), (MON30, (19, 30))])
def test_the_window_closes_five_minutes_before_mondays_last_tip(day, last):
    assert pl.window_close(day, SCHED) == at(day, *last) - timedelta(minutes=5)


def test_window_close_on_a_day_without_games_raises():
    with pytest.raises(pl.NoGames):
        pl.window_close(WED, SCHED)


def _real_schedule():
    from modules.data_loader import NBA_SCHEDULE_FILE
    return json.loads((ROOT / NBA_SCHEDULE_FILE).read_text(encoding="utf-8"))


@pytest.mark.parametrize("monday", [MON, MON30])     # 11-30 opens week 7, the 14-day week
def test_window_close_on_the_real_schedule(monday):
    sched = _real_schedule()
    games = [x for x in sched["games"] if x["date"][:10] == monday.isoformat()]
    if not games or not all("tip_utc" in x for x in games):
        pytest.skip("the schedule file has no tip times yet: refetch with --tips-only")
    last = max(datetime.strptime(x["tip_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
               for x in games)
    assert pl.window_close(monday, sched) == last - timedelta(minutes=5)
    assert pl.window_close(monday, sched).date() == monday


def test_the_message_counts_what_is_waiting():
    assert pl.lock_message(1) == ("Lines locked while games are on. 1 change waiting; "
                                  "priced after tonight's games.")
    assert "3 changes waiting" in pl.lock_message(3)


# ======================================== 3. the re-price paths consult the lock

from test_refresh_service import svc, TAGS          # noqa: E402,F401  (the fixture)
from test_live_lines import D, _data                 # noqa: E402


def _with_tips(schedule, hh=19):
    out = copy.deepcopy(schedule)
    for x in out["games"]:
        d = date.fromisoformat(x["date"][:10])
        x["tip_utc"] = tip(d, hh)
    return out


def test_a_trigger_during_the_lock_prices_nothing_and_writes_nothing(svc):
    svc.box["data"]["nba_schedule"] = _with_tips(_data()[0].nba_schedule)
    assert svc(D[0], now=at(D[0], 0, 30))["outcome"] == "priced"
    first = svc(D[2], now=at(D[2], 0, 30))
    assert first["outcome"] == "priced"
    line, state = svc.line(), svc.state()
    cal_log = (svc.tmp / "data" / "calibration" / "published_lines.json").read_bytes()
    locked = svc(D[2], statuses={**TAGS, "B1": "O"}, now=at(D[2], 20, 15))
    assert (locked["outcome"], locked["exit"]) == ("locked", 0)
    assert locked["waiting"] == ["tags"]
    assert locked["message"] == ("Lines locked while games are on. 1 change waiting; "
                                 "priced after tonight's games.")
    assert svc.line() == line and svc.state() == state
    assert (svc.tmp / "data" / "calibration" / "published_lines.json").read_bytes() == cal_log
    assert not (svc.tmp / "output" / "title_odds_history.jsonl").exists()
    assert svc.runs()["last_outcome"] == "locked"
    # the next unlocked run (12:01 AM, the next league day) prices what waited
    later = svc(D[3], statuses={**TAGS, "B1": "O"}, now=at(D[3], 0, 1))
    assert later["outcome"] == "priced" and "tags" in later["why_priced"]
    assert svc.line() != line


def test_nothing_changed_is_unchanged_even_while_locked(svc):
    svc.box["data"]["nba_schedule"] = _with_tips(_data()[0].nba_schedule)
    svc(D[0], now=at(D[0], 0, 30))
    svc(D[2], now=at(D[2], 0, 30))
    assert svc(D[2], now=at(D[2], 21, 0))["outcome"] == "unchanged"


def test_a_missing_tip_fails_the_run_loudly_and_leaves_the_line(svc):
    svc.box["data"]["nba_schedule"] = _with_tips(_data()[0].nba_schedule)
    svc(D[0], now=at(D[0], 0, 30))
    line = svc.line()
    sched = _with_tips(_data()[0].nba_schedule)
    for x in sched["games"]:
        if x["date"][:10] == D[2].isoformat():
            x["tip_utc"] = None
    svc.box["data"]["nba_schedule"] = sched
    out = svc(D[2], statuses={**TAGS, "B1": "O"}, now=at(D[2], 9, 0))
    assert (out["outcome"], out["exit"]) == ("failed", 1) and "TipTimeMissing" in out["error"]
    assert svc.line() == line


def test_a_manual_refresh_during_the_lock_writes_nothing_and_a_dry_run_still_prints(svc):
    data, _ = _data(through=D[2])
    data.nba_schedule = _with_tips(data.nba_schedule)
    with pytest.raises(rl.PricesLocked, match="1 change waiting|changes waiting"):
        rl.refresh(svc.tmp, week=2, as_of=D[2], sims=200, statuses=TAGS, data=data,
                   now=at(D[2], 20, 0), assume_tags_since_week_start=True)
    assert not (svc.tmp / "output" / "live_lines_week2.json").exists()
    assert not (svc.tmp / "data" / "calibration" / "published_lines.json").exists()
    out = rl.refresh(svc.tmp, week=2, as_of=D[2], sims=200, statuses=TAGS, data=data,
                     now=at(D[2], 20, 0), assume_tags_since_week_start=True, dry_run=True)
    assert out["lines"] and not (svc.tmp / "output" / "live_lines_week2.json").exists()


def _functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _calls(fn):
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", None))
    return out


def test_every_path_that_writes_a_live_price_consults_the_lock():
    """refresh_lines.price is the one writer of a priced live line (and its
    calibration records). Its callers are the manual refresh and the service,
    and each consults price_lock before pricing."""
    callers = []
    for path in [*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        for fn in _functions(path):
            if fn.name == "price" and path.name == "refresh_lines.py":
                continue
            src = ast.get_source_segment(path.read_text(encoding="utf-8"), fn) or ""
            if "price" in _calls(fn) and ("rl.price(" in src or path.name == "refresh_lines.py"):
                callers.append(f"{path.name}:{fn.name}")
                assert _calls(fn) & {"lock_check", "status"}, f"{path.name}:{fn.name}"
    assert sorted(callers) == ["refresh_lines.py:refresh", "refresh_service.py:run"]


def test_only_the_lock_and_the_fetch_read_a_tip_time():
    readers = sorted(p.name for p in [*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py")]
                     if "tip_utc" in p.read_text(encoding="utf-8"))
    assert readers == ["fetch_nba_schedule.py", "price_lock.py"], readers


# ============================== 4. tip times change no price (readers date-only)

@needs_state("data/LINEUPS.xlsx", "data/PLAYERLOG.xlsx", "data/PLAYERLIST.xlsx",
             "config/RECORDS.json", why="prices the real week-2 line and title odds twice")
def test_tip_times_in_the_schedule_change_no_line_and_no_title_odds():
    from modules.data_loader import load_all_data
    from modules.fetch_injury_statuses import Tags
    from modules.simulator_title_odds import run_title_odds_simulation
    data = load_all_data(ROOT, current_week=None)
    plain = copy.deepcopy(data.nba_schedule)

    def price_all():
        p = rl.prepare(ROOT, 2, date(2026, 10, 26), seed=123456789, no_tags=True,
                       dry_run=True, data=data)
        line = rl.price(p, 400, dry_run=True)
        t = run_title_odds_simulation(data, num_simulations=300, seed=20262027,
                                      injury_statuses=Tags.none())
        return line["lines"], line["state_hash"], rl.cache_key(p, 400)["parts"]["schedule"], \
            (t.title_odds, t.expected_record, t.finish_distribution)

    before = price_all()
    timed = copy.deepcopy(plain)
    for x in timed["games"]:
        x["tip_utc"] = tip(date.fromisoformat(x["date"][:10]), 19)
    data.nba_schedule = timed
    after = price_all()
    data.nba_schedule = plain
    assert before == after
