"""
league_clock.py -- the league's clock.

THE RULE (Nick, 10-30): "whatever time it is in Portland, Oregon, that is
always going to be the league's clock." Every league day, every Monday window
and every fantasy-week boundary is in that time, daylight saving included.
claude/LEAGUE_RULES.md, rule 0.

WHY THIS EXISTS
    The engine used to ask the machine it ran on: date.today(),
    datetime.now(), datetime.fromtimestamp(ts). On Nick's desktop that is
    Phoenix time, which matches Pacific only while Pacific is on daylight
    saving. From 2026-11-01 to mid-March, Pacific is an hour behind Phoenix,
    so a move made at 12:30 AM Monday Phoenix time -- still Sunday 11:30 PM in
    the league -- was dated Monday and filed under the next fantasy week. On a
    cloud runner (UTC) every evening move would land on the next day.

    So the question "what day is it for the league?" and "what league day did
    this Yahoo transaction happen on?" are answered here and nowhere else.

THE ZONE IS CONFIG, AND REQUIRED
    league_structure.time_zone (an IANA name, "America/Los_Angeles"). A name,
    never a fixed offset, so the clock follows the law if daylight saving ever
    changes. Missing raises UnspecifiedRule (data_loader.league_rule): the
    engine never guesses a clock.

WINDOWS NEEDS tzdata
    Python's zoneinfo reads the operating system's time-zone database. Linux
    and macOS have one; Windows does not, and there zoneinfo needs the
    `tzdata` package (requirements.txt). Without it this module raises with
    the command to install it rather than falling back to the machine clock.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache

from .data_loader import league_rule

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover -- Python < 3.9 is not supported
    raise


class LeagueClockError(RuntimeError):
    """The league's clock cannot be read: a bad zone name or no tz database."""


@lru_cache(maxsize=None)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as e:
        raise LeagueClockError(
            f"Time zone {name!r} (league_structure.time_zone) cannot be loaded: {e}. "
            "On Windows Python has no time-zone database of its own; install it with "
            "`python -m pip install tzdata`. If the name itself is wrong, fix it in "
            "config/league_config.json.") from None


def league_tz() -> ZoneInfo:
    """The league's time zone, from league_structure.time_zone. Raises
    UnspecifiedRule when the config does not state it."""
    return _zone(str(league_rule("league_structure", "time_zone")))


def league_now() -> datetime:
    """Now, on the league's clock (timezone-aware)."""
    return datetime.now(timezone.utc).astimezone(league_tz())


def league_today() -> date:
    """Today's date on the league's clock."""
    return league_now().date()


def league_date_of_timestamp(ts) -> date:
    """The league day a Unix timestamp (seconds, as Yahoo sends it) falls on.
    Raises on anything that is not a number: a transaction with no usable
    time is refused, never dated 'today'."""
    try:
        seconds = int(ts)
    except (TypeError, ValueError):
        raise ValueError(f"not a Unix timestamp: {ts!r}") from None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone(league_tz()).date()
