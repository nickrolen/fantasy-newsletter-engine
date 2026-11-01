"""
price_lock.py -- prices lock while games are on.

THE RULE (Nick, 10-31; claude/SELF_RUNNING_DESIGN.md s.4.1, invariant 16).
Lines and title odds do not re-price from the first scheduled tip of a league
day until that league day ends: a re-price mid-game would treat games in
progress as unplayed and look live while being wrong, and would move a line
on in-game news while that game is still on. Entries are still recorded at
once; only pricing waits. So:

    is_locked(now)    true from the first tip of league_today(now) until that
                      league day ends. The 12:01 AM run, already on the next
                      league day, is unlocked until that day's first tip. A
                      day with no games is never locked.
    window_close(day) the Monday window's end: five minutes before that
                      night's last tip (LEAGUE_RULES rule 4).

This module is the only place either is decided, and the only reader of the
schedule's tip_utc (scripts/fetch_nba_schedule.py writes it). Nothing that
prices a line or a season reads a tip time (tests/test_price_lock.py).

REFUSALS, NEVER GUESSES. A league day with games where any game has no tip
time (tip_utc null, or a schedule fetched before tips were kept) raises
TipTimeMissing naming the day and the game -- for is_locked and for
window_close alike. A wrong lock is worse than a refused run: the run fails
loudly, the previous line stays, and the schedule gets refetched.

Every day and time here is on the league's clock (modules/league_clock).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .league_clock import league_now, league_tz

WINDOW_CLOSE_BEFORE_LAST_TIP = timedelta(minutes=5)
LOCK_MESSAGE = ("Lines locked while games are on. {n} change{s} waiting; "
                "priced after tonight's games.")


class TipTimeMissing(RuntimeError):
    """A league day with games where a game has no tip time."""


class NoGames(RuntimeError):
    """window_close asked for a day with no NBA games: there is no last tip."""


def _games(schedule):
    """The schedule given (a run passes data.nba_schedule), else the configured
    file (league_config season.nba_schedule_file). A run must lock on the same
    schedule it prices on, so callers pass theirs."""
    if schedule is None:
        from pathlib import Path
        from .data_loader import NBA_SCHEDULE_FILE, load_nba_schedule
        if not NBA_SCHEDULE_FILE:
            raise TipTimeMissing("league_config season.nba_schedule_file is not set")
        schedule = load_nba_schedule(Path(__file__).resolve().parent.parent / NBA_SCHEDULE_FILE)
    return (schedule or {}).get("games", [])


def _on(day: date, schedule) -> list:
    d = day.isoformat()
    return [g for g in _games(schedule) if str(g.get("date", ""))[:10] == d]


def tips(league_day: date, schedule=None) -> list:
    """Every tip of the league day as an aware datetime (league time), sorted.
    [] on a day with no games. Raises TipTimeMissing if any game lacks one."""
    games = _on(league_day, schedule)
    out, missing = [], []
    for g in games:
        raw = g.get("tip_utc")
        if not raw:
            missing.append(f"{g.get('away')} @ {g.get('home')}")
            continue
        t = datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        out.append(t.astimezone(league_tz()))
    if missing:
        raise TipTimeMissing(
            f"{league_day}: no tip time for {', '.join(missing)} -- the lock and the Monday "
            "window cannot be placed without every game's tip. Refetch the schedule "
            "(python scripts/fetch_nba_schedule.py --source bbref --tips-only); a game with "
            "no time yet is stored as null and refuses until it has one")
    return sorted(out)


def first_tip(league_day: date, schedule=None):
    t = tips(league_day, schedule)
    return t[0] if t else None


def last_tip(league_day: date, schedule=None):
    t = tips(league_day, schedule)
    return t[-1] if t else None


def _league(now) -> datetime:
    now = now if now is not None else league_now()
    if now.tzinfo is None:
        raise ValueError("price_lock needs an aware datetime (league_now()), not a naive one")
    return now.astimezone(league_tz())


def is_locked(now=None, schedule=None) -> bool:
    """True from the first tip of now's league day until that day ends."""
    now = _league(now)
    first = first_tip(now.date(), schedule)
    return first is not None and now >= first


def window_close(day: date, schedule=None) -> datetime:
    """The Monday window's end on `day`: five minutes before the last tip."""
    last = last_tip(day, schedule)
    if last is None:
        raise NoGames(f"{day} has no NBA games: the window has no last tip to close on")
    return last - WINDOW_CLOSE_BEFORE_LAST_TIP


def lock_message(n_waiting: int) -> str:
    return LOCK_MESSAGE.format(n=n_waiting, s="" if n_waiting == 1 else "s")


def status(now=None, schedule=None) -> dict:
    """{"locked", "league_day", "now", "first_tip"} for the run deciding
    whether it may price. Raises TipTimeMissing as is_locked does."""
    now = _league(now)
    first = first_tip(now.date(), schedule)
    return {"locked": first is not None and now >= first, "league_day": now.date().isoformat(),
            "now": now.isoformat(timespec="seconds"),
            "first_tip": first.isoformat(timespec="minutes") if first else None}
