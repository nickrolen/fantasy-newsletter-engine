#!/usr/bin/env python3
"""
run_guard.py -- does this scheduled firing run? (step 1c-ii)

    python scripts/run_guard.py nightly     the night's run: admitted from 12:00 to
                                            5:59 AM league time, until the night's run
                                            has happened (output/nightly_last.json)
    python scripts/run_guard.py pretip      Monday's pre-tip run: admitted only in
                                            [first tip - 45 min, first tip) on a
                                            window day (a fantasy week's first day);
                                            outside it, while the Monday window is
                                            open, the :00 and :30 firings POLL
                                            (step 3b, monday_decision)
    python scripts/run_guard.py afternoon   the afternoon tag check (step 3b): the
                                            fixed firing (config live_refresh) that
                                            falls in [first tip - 90, first tip - 30],
                                            on a game day that is not a window day

STEP 3b. The pre-tip job fires every 15 minutes through Monday. A firing
the pre-tip window does not admit becomes a POLL when (a) the day is a window
day with games, (b) the window is open: 12:01 AM to the last tip - 5 minutes
(rule 4; price_lock.window_close), and (c) its slot minute is in
live_refresh.monday_poll_slots (:00 and :30), so at most one poll every 30
minutes. The guard tells them apart by the clock alone: a firing in
[first tip - 45, first tip) is the pre-tip run, whatever its minute. The CLI
writes go=true for a pre-tip run and poll=true for a poll; the workflow's poll
steps then read Yahoo's transactions (scripts/monday_poll.py) and run the
refresh only when one is new. Outside the window nothing polls: moves cannot
happen then.

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
                                 checkout in the workflow; default: --base-path),
                                 and the refetched NBA schedule when there is one
                                 (schedule_file; task 33)

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
NIGHTLY_LAST_HOUR = 6          # league clock: the night's window always runs at least to 6:00 AM
NIGHTLY_LATEST_HOUR = 12       # ... and, for a late firing, at most to noon (11-07)
NIGHTLY_TIP_MARGIN = timedelta(minutes=60)   # ... and never past the day's first tip less this
NIGHTLY_MAX_ATTEMPTS = 2       # a failed night is retried once, then waits for Nick
MARKER_REL = "output/nightly_last.json"
MODES = ("nightly", "pretip", "afternoon")


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


REFETCH_SUFFIX = ".refetched"      # modules/nba_schedule.REFETCH_SUFFIX (tests pin the two agree)


def schedule_file(base, state_dir=None) -> tuple:
    """(root, relative path) of the NBA schedule the run reads: the refetched
    copy (state, task 33: <nba_schedule_file stem>.refetched.json) when there
    is one -- in the state checkout first, then in the engine tree (where the
    overlay puts it on the runner and on a desk) -- else the engine's file.
    modules/nba_schedule.schedule_path's rule; this module cannot import it."""
    rel = str(_key(_read(base, "config/league_config.json"), "season", "nba_schedule_file",
                   where="config/league_config.json")).replace("\\", "/")
    p = Path(rel)
    if p.suffix != ".json":
        raise GuardError(f"season.nba_schedule_file {rel!r} is not a .json file")
    copy = (p.parent / f"{p.stem}{REFETCH_SUFFIX}.json").as_posix()
    for root in ([state_dir] if state_dir is not None else []) + [base]:
        if (Path(root) / copy).is_file():
            return Path(root), copy
    return Path(base), rel


def _games_on(base, day: date, state_dir=None) -> list:
    root, rel = schedule_file(base, state_dir)
    d = day.isoformat()
    return [g for g in _read(root, rel).get("games", []) if str(g.get("date", ""))[:10] == d]


def first_tip(base, day: date, tz: ZoneInfo = None, state_dir=None):
    """The day's first tip on the league clock, or None on a day with no games.
    Raises GuardError when any game that day has no tip time."""
    tz = tz or league_zone(base)
    games = _games_on(base, day, state_dir)
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


def night_cutoff(base, day: date, tz: ZoneInfo, state_dir=None) -> tuple:
    """(cutoff, why): the end of `day`'s nightly window on the league clock.

    GitHub's scheduler delays firings by hours and drops most of them (11-05,
    11-06: none, then one at 6:49 AM Pacific), so a late firing should still
    do the night's work while that is harmless: the window runs to the day's
    first tip less NIGHTLY_TIP_MARGIN (before the price lock), at most to
    NIGHTLY_LATEST_HOUR, and never ends before NIGHTLY_LAST_HOUR (the old
    fixed cutoff). A day with no games runs to NIGHTLY_LATEST_HOUR. If the
    first tip can't be placed (a game with no tip time), the old 6:00 cutoff
    applies and the reason says so: the nightly run is never refused for it."""
    base_cut = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(hour=NIGHTLY_LAST_HOUR)
    latest = base_cut.replace(hour=NIGHTLY_LATEST_HOUR)
    try:
        tip = first_tip(base, day, tz, state_dir)
    except GuardError as e:
        return base_cut, f"the first tip can't be placed ({e}); window to {base_cut:%H:%M}"
    if tip is None:
        return latest, f"no games today; window to {latest:%H:%M}"
    cut = max(base_cut, min(latest, tip - NIGHTLY_TIP_MARGIN))
    return cut, f"first tip {tip:%H:%M}; window to {cut:%H:%M}"


def nightly_decision(now_utc: datetime, tz: ZoneInfo, marker: dict = None, cutoff: datetime = None,
                     cutoff_why: str = None) -> tuple:
    """(admitted, why). Admitted when the league clock is in [00:00, cutoff)
    and tonight's run has not happened: no marker, a marker for an earlier
    league day, or a failed night with attempts left. `cutoff` (night_cutoff)
    defaults to NIGHTLY_LAST_HOUR on the league clock."""
    now = _aware(now_utc).astimezone(tz)
    if cutoff is None:
        cutoff = now.replace(hour=NIGHTLY_LAST_HOUR, minute=0, second=0, microsecond=0)
    if now >= cutoff.astimezone(tz):
        return False, (f"league clock {now:%Y-%m-%d %H:%M %Z}: outside the night's window "
                       f"(00:00-{cutoff.astimezone(tz):%H:%M}{'; ' + cutoff_why if cutoff_why else ''})")
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


def pretip_window(base, day: date, tz: ZoneInfo = None, state_dir=None):
    """(start, end) = [first tip - 45 min, first tip) on a window day; None on
    any other day, or a window day with no games."""
    tz = tz or league_zone(base)
    if day not in window_days(base):
        return None
    tip = first_tip(base, day, tz, state_dir)
    return None if tip is None else (tip - PRETIP_LEAD, tip)


def admits_pretip(now_utc: datetime, base=ROOT, state_dir=None) -> tuple:
    """(admitted, why)."""
    tz = league_zone(base)
    now = _aware(now_utc).astimezone(tz)
    win = pretip_window(base, now.date(), tz, state_dir)
    if win is None:
        return False, f"{now.date()} is not a window day with games"
    start, end = win
    if start <= now < end:
        return True, (f"in the pre-tip window {start:%H:%M}-{end:%H:%M} {end:%Z} "
                      f"(first tip {end:%H:%M})")
    return False, f"outside the pre-tip window {start:%H:%M}-{end:%H:%M} {end:%Z}"


# =============================================================================
# step 3b: Monday polling and the afternoon tag check
# =============================================================================

WINDOW_CLOSE_BEFORE_LAST_TIP = timedelta(minutes=5)   # rule 4; modules/price_lock's (tests pin it)


def live_cfg(base=ROOT) -> dict:
    """config live_refresh's guard keys, checked. Raises GuardError on a
    missing or malformed one: the guard never guesses a firing time."""
    blob = _read(base, "config/league_config.json")
    where = "config/league_config.json"
    firings = _key(blob, "live_refresh", "afternoon_firings", where=where)
    lead = _key(blob, "live_refresh", "afternoon_lead_minutes", where=where)
    tol = _key(blob, "live_refresh", "firing_tolerance_minutes", where=where)
    slots = _key(blob, "live_refresh", "monday_poll_slots", where=where)
    days = _key(blob, "live_refresh", "afternoon_days", where=where)
    try:
        times = sorted(datetime.strptime(str(f), "%H:%M").time() for f in firings)
        lo, hi = (int(x) for x in lead)
        tol, slots = int(tol), sorted(int(x) for x in slots)
        names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        if any(d not in names for d in days):
            raise ValueError(f"afternoon_days {days} are not day names {names}")
        weekdays = {names.index(d) for d in days}
    except (TypeError, ValueError) as e:
        raise GuardError(f"{where} live_refresh is malformed ({e})") from None
    if not times or len(times) > 3:
        raise GuardError(f"{where} live_refresh.afternoon_firings must hold 1 to 3 times")
    if not 0 < lo < hi or not 0 < tol < 15 or not slots or any(not 0 <= x < 60 for x in slots):
        raise GuardError(f"{where} live_refresh: lead [{lo}, {hi}], tolerance {tol} or slots {slots} "
                         "out of range")
    return {"firings": times, "lead": (timedelta(minutes=lo), timedelta(minutes=hi)),
            "tolerance": timedelta(minutes=tol), "slots": slots, "weekdays": weekdays}


def tip_times(base, day: date, tz: ZoneInfo = None, state_dir=None) -> list:
    """Every tip of the day on the league clock, ascending ([] with no games).
    Raises GuardError when a game that day has no tip time (first_tip's rule)."""
    tz = tz or league_zone(base)
    games = _games_on(base, day, state_dir)
    if not games:
        return []
    first_tip(base, day, tz, state_dir)                 # raises on a missing tip
    return sorted(datetime.strptime(str(g["tip_utc"]), "%Y-%m-%dT%H:%M:%SZ")
                  .replace(tzinfo=timezone.utc).astimezone(tz) for g in games)


def window_open(base, day: date, tz: ZoneInfo = None, state_dir=None):
    """(open from, closes at) for a window day with games: 12:01 AM to the
    last tip - 5 minutes (rule 4). None on any other day."""
    tz = tz or league_zone(base)
    if day not in window_days(base):
        return None
    tips = tip_times(base, day, tz, state_dir)
    if not tips:
        return None
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(minute=1)
    return start, tips[-1] - WINDOW_CLOSE_BEFORE_LAST_TIP


def _slot(now: datetime, cfg: dict):
    """The poll slot minute this firing stands for, or None."""
    for s in cfg["slots"]:
        if 0 <= (now.minute - s) % 60 < cfg["tolerance"].seconds // 60:
            return s
    return None


def monday_decision(now_utc: datetime, base=ROOT, state_dir=None) -> tuple:
    """(kind, why): kind "pretip" (the pre-tip run), "poll" (read Yahoo's
    transactions; refresh if one is new) or None (nothing to do)."""
    tz = league_zone(base)
    now = _aware(now_utc).astimezone(tz)
    ok, why = admits_pretip(now_utc, base, state_dir)
    if ok:
        return "pretip", why
    win = window_open(base, now.date(), tz, state_dir)
    if win is None:
        return None, why
    start, close = win
    if not start <= now < close:
        return None, f"{why}; the Monday window is closed ({start:%H:%M}-{close:%H:%M} {close:%Z})"
    cfg = live_cfg(base)
    slot = _slot(now, cfg)
    if slot is None:
        return None, (f"{why}; the window is open but {now:%H:%M} is not a poll slot "
                      f"(:{', :'.join(f'{s:02d}' for s in cfg['slots'])})")
    return "poll", (f"poll: the Monday window is open ({start:%H:%M}-{close:%H:%M} {close:%Z}) and "
                    f"{now:%H:%M} is the :{slot:02d} slot")


def afternoon_plan(base, day: date, tz: ZoneInfo = None, state_dir=None) -> dict:
    """Which afternoon firing runs on `day`: {"day", "first_tip" (HH:MM or
    None), "firing" (HH:MM or None), "why"}. None on a window day (the pre-tip
    runs instead), a day with no games, and a day no firing covers -- that
    day is skipped, and the nightly run names it in its summary."""
    tz = tz or league_zone(base)
    cfg = live_cfg(base)
    names = ", ".join(t.strftime("%H:%M") for t in cfg["firings"])
    if day in window_days(base):
        return {"day": day.isoformat(), "first_tip": None, "firing": None,
                "why": f"{day:%a %m-%d} is a window day: Monday's pre-tip runs instead"}
    tip = first_tip(base, day, tz, state_dir)
    if tip is None:
        return {"day": day.isoformat(), "first_tip": None, "firing": None,
                "why": f"{day:%a %m-%d}: no games"}
    if day.weekday() not in cfg["weekdays"]:
        return {"day": day.isoformat(), "first_tip": tip.strftime("%H:%M"), "firing": None,
                "why": (f"{day:%a %m-%d}: SKIPPED -- first tip {tip:%H:%M}, and the afternoon job does "
                        f"not fire on {day:%A}s")}
    lo, hi = tip - cfg["lead"][1], tip - cfg["lead"][0]
    fits = [datetime.combine(day, t, tzinfo=tz) for t in cfg["firings"]]
    fits = [f for f in fits if lo <= f <= hi]
    if not fits:
        return {"day": day.isoformat(), "first_tip": tip.strftime("%H:%M"), "firing": None,
                "why": (f"{day:%a %m-%d}: SKIPPED -- first tip {tip:%H:%M}, and no firing ({names}) "
                        f"falls in {lo:%H:%M}-{hi:%H:%M}")}
    f = max(fits)
    return {"day": day.isoformat(), "first_tip": tip.strftime("%H:%M"), "firing": f.strftime("%H:%M"),
            "why": f"{day:%a %m-%d}: the {f:%H:%M} firing (first tip {tip:%H:%M})"}


def admits_afternoon(now_utc: datetime, base=ROOT, state_dir=None) -> tuple:
    """(admitted, why): this firing is today's afternoon firing (afternoon_plan)."""
    tz = league_zone(base)
    now = _aware(now_utc).astimezone(tz)
    cfg = live_cfg(base)
    slot = None
    for t in cfg["firings"]:
        f = datetime.combine(now.date(), t, tzinfo=tz)
        if timedelta(0) <= now - f < cfg["tolerance"]:
            slot = f
    if slot is None:
        return False, f"{now:%H:%M} is not one of the afternoon firings ({', '.join(t.strftime('%H:%M') for t in cfg['firings'])})"
    plan = afternoon_plan(base, now.date(), tz, state_dir)
    if plan["firing"] != slot.strftime("%H:%M"):
        return False, f"the {slot:%H:%M} firing does not run today -- {plan['why']}"
    return True, plan["why"]


def decide(mode: str, now_utc: datetime, base=ROOT, state_dir=None) -> tuple:
    if mode == "nightly":
        tz = league_zone(base)
        cut, why = night_cutoff(base, _aware(now_utc).astimezone(tz).date(), tz, state_dir)
        return nightly_decision(now_utc, tz, read_marker(state_dir if state_dir else base), cut, why)
    if mode == "pretip":
        return admits_pretip(now_utc, base, state_dir)
    if mode == "afternoon":
        return admits_afternoon(now_utc, base, state_dir)
    raise ValueError(f"mode must be one of {MODES}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Does this scheduled firing run? (standard library only)")
    ap.add_argument("mode", choices=MODES)
    ap.add_argument("--base-path", default=str(ROOT))
    ap.add_argument("--state-dir", help="where output/nightly_last.json and the refetched schedule "
                                        "are (default: --base-path)")
    ap.add_argument("--now", help="an ISO instant with its offset (tests); default: now")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    base, state = Path(a.base_path), Path(a.state_dir) if a.state_dir else None
    poll = False
    try:
        if a.mode == "pretip":
            kind, why = monday_decision(now, base, state)
            ok, poll = kind == "pretip", kind == "poll"
        else:
            ok, why = decide(a.mode, now, base, state)
    except (GuardError, ValueError) as e:
        print(f"GUARD REFUSED ({a.mode}): {e}")
        return 1
    print(f"{a.mode}: {'GO' if ok else 'POLL' if poll else 'nothing to do'} -- {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"go={'true' if ok else 'false'}\n")
            f.write(f"poll={'true' if poll else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
