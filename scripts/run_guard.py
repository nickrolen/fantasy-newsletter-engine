#!/usr/bin/env python3
"""
run_guard.py -- does this scheduled firing run? (step 1c-ii)

    python scripts/run_guard.py nightly     the night's run: admitted from 12:00 to
                                            5:59 AM league time, until the night's run
                                            has happened (output/nightly_last.json)
    python scripts/run_guard.py pretip      Monday's pre-tip run: admitted only in
                                            [first tip - 45 min, first tip) on a
                                            window day (a fantasy week's first day)

STANDARD LIBRARY ONLY, ON PURPOSE (HANDOFF_STEP1C2 s.2). Most firings do
nothing: the nightly cron fires every 30 minutes through the early morning
(GitHub delays or drops scheduled firings under load: on 11-05 the first
scheduled night never fired at all), and only the first firing of the night
that finds no run recorded for tonight goes; every Monday pre-tip firing
outside its 45 minutes does nothing too. The
workflow's guard job runs this on the runner's own Python, before anything is
installed, with only these files checked out of the engine:
    config/league_config.json        league_structure.time_zone, season.nba_schedule_file
    config/SCHEDULE.json             the fantasy weeks (each week's first day is its window)
    data/nba_schedule_<season>.json  every game's tip_utc
so an idle firing costs seconds. tests/test_cloud_run.py runs it with every
module outside the standard library refused (tzdata excepted: zoneinfo's
database on a machine without one).

ONE DEFINITION. This file is the guard. modules/nightly.py's --scheduled
calls admits_nightly / admits_pretip from here; nothing else decides. The tip
times it reads must agree with modules/price_lock.first_tip on every window
day, and its zone with modules/league_clock.league_tz (both tested).

RAISE, NEVER GUESS. A missing config key, a missing file, or a window day with
a game that has no tip time raises GuardError (exit 1): the workflow's guard
job fails and the failure issue opens. A day that is not a window day never
reads a tip.

    --now 2026-11-09T23:30:00Z   decide for that instant (tests and rehearsals)
    --base-path DIR              the engine checkout (default: this repo)
    --state-dir DIR              where output/nightly_last.json is (the private
                                 checkout in the workflow; default: --base-path)

THE NIGHT'S MARKER (output/nightly_last.json, league state): {"league_day",
"attempts", "ok", "run_id", "finished_at"}, written by modules/nightly.py after
every nightly-mode run. The guard admits a nightly firing when the league
clock is in [00:00, NIGHTLY_LAST_HOUR) and the marker is missing, is for an
earlier league day, or records a failed night with fewer than
NIGHTLY_MAX_ATTEMPTS attempts. A malformed marker raises.

Prints the decision and why. Exit 0 either way; when $GITHUB_OUTPUT is set it
also writes go=true|false there for the workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
PRETIP_LEAD = timedelta(minutes=45)
NIGHTLY_LAST_HOUR = 6          # league clock: no nightly firing is admitted from 6:00 AM
NIGHTLY_MAX_ATTEMPTS = 2       # a failed night is retried once, then waits for Nick
MARKER_REL = "output/nightly_last.json"
MODES = ("nightly", "pretip")


class GuardError(RuntimeError):
    """The guard cannot decide: a file or key is missing, or a tip time is."""


_CACHE = {}


def _read(base, rel: str) -> dict:
    """The JSON file, parsed; re-read whenever the file changes (keyed on its
    path, size and modification time), so one process can ask many times."""
    p = Path(base) / rel
    if not p.is_file():
        raise GuardError(f"{rel} is missing under {base}: the guard reads it")
    st = p.stat()
    key = (str(p.resolve()), st.st_size, st.st_mtime_ns)
    if key not in _CACHE:
        _CACHE[key] = json.loads(p.read_text(encoding="utf-8"))
    return _CACHE[key]


def _key(blob: dict, *path, where: str):
    node = blob
    for k in path:
        if not isinstance(node, dict) or k not in node or node[k] in (None, ""):
            raise GuardError(f"{where} does not specify {'.'.join(path)}: the guard will not guess it")
        node = node[k]
    return node


def league_zone(base=ROOT) -> ZoneInfo:
    """league_structure.time_zone (the same key modules/league_clock reads)."""
    name = str(_key(_read(base, "config/league_config.json"), "league_structure", "time_zone",
                    where="config/league_config.json"))
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as e:
        raise GuardError(f"time zone {name!r} cannot be loaded ({e}); on a machine with no "
                         "time-zone database install tzdata") from None


def window_days(base=ROOT) -> list:
    """Every fantasy week's first day (its Monday window), from SCHEDULE.json."""
    weeks = _read(base, "config/SCHEDULE.json").get("weeks")
    if not weeks:
        raise GuardError("config/SCHEDULE.json has no weeks")
    return sorted(date.fromisoformat(str(w["start_date"])[:10]) for w in weeks)


def _games_on(base, day: date) -> list:
    rel = str(_key(_read(base, "config/league_config.json"), "season", "nba_schedule_file",
                   where="config/league_config.json"))
    d = day.isoformat()
    return [g for g in _read(base, rel).get("games", []) if str(g.get("date", ""))[:10] == d]


def first_tip(base, day: date, tz: ZoneInfo = None):
    """The day's first tip on the league clock, or None on a day with no games.
    Raises GuardError when any game that day has no tip time."""
    tz = tz or league_zone(base)
    games = _games_on(base, day)
    missing = [f"{g.get('away')} @ {g.get('home')}" for g in games if not g.get("tip_utc")]
    if missing:
        raise GuardError(f"{day}: no tip time for {', '.join(missing)} -- the pre-tip window "
                         "cannot be placed. Refetch the schedule (python scripts/fetch_nba_schedule.py "
                         "--source bbref --tips-only)")
    tips = sorted(datetime.strptime(str(g["tip_utc"]), "%Y-%m-%dT%H:%M:%SZ")
                  .replace(tzinfo=timezone.utc).astimezone(tz) for g in games)
    return tips[0] if tips else None


def _aware(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        raise ValueError("the guard needs an aware time")
    return now_utc


def read_marker(state_dir) -> dict:
    """The night's marker, or None when there is none yet. Raises GuardError
    on a malformed one: the guard never guesses whether tonight has run."""
    p = Path(state_dir) / MARKER_REL
    if not p.is_file():
        return None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
        day = date.fromisoformat(str(m["league_day"]))
        attempts, ok = m["attempts"], m["ok"]
    except (ValueError, KeyError, TypeError) as e:
        raise GuardError(f"{MARKER_REL} is malformed ({e}): fix or remove it") from None
    if not isinstance(attempts, int) or attempts < 1 or not isinstance(ok, bool):
        raise GuardError(f"{MARKER_REL} is malformed: attempts must be a positive int, ok a bool")
    return {**m, "league_day": day}


def nightly_decision(now_utc: datetime, tz: ZoneInfo, marker: dict = None) -> tuple:
    """(admitted, why). Admitted when the league clock is in [00:00,
    NIGHTLY_LAST_HOUR) and tonight's run has not happened: no marker, a marker
    for an earlier league day, or a failed night with attempts left."""
    now = _aware(now_utc).astimezone(tz)
    if now.hour >= NIGHTLY_LAST_HOUR:
        return False, f"league clock {now:%Y-%m-%d %H:%M %Z}: outside the night's window (00:00-{NIGHTLY_LAST_HOUR:02d}:00)"
    if marker is None:
        return True, f"league clock {now:%Y-%m-%d %H:%M %Z}: no night recorded yet"
    if marker["league_day"] < now.date():
        return True, f"league clock {now:%Y-%m-%d %H:%M %Z}: tonight's run has not happened"
    if marker["league_day"] > now.date():
        raise GuardError(f"{MARKER_REL} is for {marker['league_day']}, after today ({now.date()})")
    if marker["ok"]:
        return False, f"tonight's run already happened ({marker.get('run_id')})"
    if marker["attempts"] >= NIGHTLY_MAX_ATTEMPTS:
        return False, f"tonight's run failed {marker['attempts']} time(s); waiting for a run by hand"
    return True, f"tonight's run failed once ({marker.get('run_id')}); one more attempt"


def admits_nightly(now_utc: datetime, tz: ZoneInfo, marker: dict = None) -> bool:
    """nightly_decision's verdict alone."""
    return nightly_decision(now_utc, tz, marker)[0]


def pretip_window(base, day: date, tz: ZoneInfo = None):
    """(start, end) = [first tip - 45 min, first tip) on a window day; None on
    any other day, or a window day with no games."""
    tz = tz or league_zone(base)
    if day not in window_days(base):
        return None
    tip = first_tip(base, day, tz)
    return None if tip is None else (tip - PRETIP_LEAD, tip)


def admits_pretip(now_utc: datetime, base=ROOT) -> tuple:
    """(admitted, why)."""
    tz = league_zone(base)
    now = _aware(now_utc).astimezone(tz)
    win = pretip_window(base, now.date(), tz)
    if win is None:
        return False, f"{now.date()} is not a window day with games"
    start, end = win
    if start <= now < end:
        return True, (f"in the pre-tip window {start:%H:%M}-{end:%H:%M} {end:%Z} "
                      f"(first tip {end:%H:%M})")
    return False, f"outside the pre-tip window {start:%H:%M}-{end:%H:%M} {end:%Z}"


def decide(mode: str, now_utc: datetime, base=ROOT, state_dir=None) -> tuple:
    if mode == "nightly":
        tz = league_zone(base)
        return nightly_decision(now_utc, tz, read_marker(state_dir if state_dir else base))
    if mode == "pretip":
        return admits_pretip(now_utc, base)
    raise ValueError(f"mode must be one of {MODES}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Does this scheduled firing run? (standard library only)")
    ap.add_argument("mode", choices=MODES)
    ap.add_argument("--base-path", default=str(ROOT))
    ap.add_argument("--state-dir", help="where output/nightly_last.json is (default: --base-path)")
    ap.add_argument("--now", help="an ISO instant with its offset (tests); default: now")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    try:
        ok, why = decide(a.mode, now, Path(a.base_path), Path(a.state_dir) if a.state_dir else None)
    except (GuardError, ValueError) as e:
        print(f"GUARD REFUSED ({a.mode}): {e}")
        return 1
    print(f"{a.mode}: {'GO' if ok else 'nothing to do'} -- {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"go={'true' if ok else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
