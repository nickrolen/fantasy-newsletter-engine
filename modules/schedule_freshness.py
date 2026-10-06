"""
schedule_freshness.py -- A3: the NBA schedule cannot go stale silently.

The NBA schedule moves under the engine all season: postponements, makeup
games, and the two NBA Cup games per team that are TBD until December. Every
startable-games count, betting line and title-odds run reads it. A file that
quietly stops being refreshed keeps producing numbers that look fine.

Three pieces, all pure so they can be tested without a network:

  stamp            fetch_nba_schedule writes fetched_at and source into the
                   file, so its age is a fact about the data, not about a
                   filesystem mtime that a copy or a git checkout resets.
  diff_schedules   what a refresh changed -- added, removed, moved -- so a
                   refresh is reviewable rather than a blind overwrite.
  stale_problem    the guard. In season, a schedule older than
                   MAX_AGE_DAYS stops Step 6 unless overridden.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

MAX_AGE_DAYS = 8          # weekly cadence plus a day of slack
SHRINK_LIMIT = 0.90       # a refresh that loses >10% of games is refused


def _game_date(g: dict) -> str:
    return str(g.get("date", ""))[:10]


def stamp(trimmed: dict, source: str, now: Optional[datetime] = None) -> dict:
    out = dict(trimmed)
    out["fetched_at"] = (now or datetime.now()).isoformat(timespec="seconds")
    out["source"] = source
    return out


def fetched_on(schedule: dict, path: Optional[Path] = None) -> tuple[Optional[date], str]:
    """(date the schedule was fetched, how we know). Falls back to mtime."""
    raw = (schedule or {}).get("fetched_at")
    if raw:
        try:
            return datetime.fromisoformat(str(raw)).date(), "fetched_at"
        except ValueError:
            pass
    if path is not None and Path(path).is_file():
        return datetime.fromtimestamp(os.path.getmtime(path)).date(), "file mtime"
    return None, "unknown"


def diff_schedules(old: dict, new: dict) -> dict:
    """Games added, removed and moved between two trimmed schedules.

    A game is its (home, away) pair. Same pair on the same date: unchanged.
    A pair that appears on different dates in old and new is MOVED, matched
    nearest-date first. What is left over is removed (postponed with no new
    date yet, or cancelled) or added (Cup knockout games, makeups).
    """
    def by_pair(sched):
        d = defaultdict(list)
        for g in (sched or {}).get("games", []):
            d[(g.get("home"), g.get("away"))].append(_game_date(g))
        return d

    o, n = by_pair(old), by_pair(new)
    added, removed, moved = [], [], []
    for pair in sorted(set(o) | set(n), key=lambda p: (str(p[0]), str(p[1]))):
        od, nd = sorted(o.get(pair, [])), sorted(n.get(pair, []))
        for d in list(od):
            if d in nd:
                od.remove(d)
                nd.remove(d)
        while od and nd:
            src = od.pop(0)
            dst = min(nd, key=lambda x: abs(date.fromisoformat(x) - date.fromisoformat(src)).days
                      if x and src else 0)
            nd.remove(dst)
            moved.append({"home": pair[0], "away": pair[1], "from": src, "to": dst})
        removed += [{"home": pair[0], "away": pair[1], "date": d} for d in od]
        added += [{"home": pair[0], "away": pair[1], "date": d} for d in nd]
    key = lambda g: (g.get("date") or g.get("from") or "", g["home"] or "")
    return {"added": sorted(added, key=key), "removed": sorted(removed, key=key),
            "moved": sorted(moved, key=key),
            "old_games": len((old or {}).get("games", [])),
            "new_games": len((new or {}).get("games", []))}


def changes_within(diff: dict, start: date, days: int = 14) -> list[str]:
    """Human lines for changes touching [start, start+days] -- the ones that
    move this week's or next week's lines."""
    end = start + timedelta(days=days)

    def near(*ds):
        return any(d and start <= date.fromisoformat(d) <= end for d in ds)

    out = []
    for m in diff["moved"]:
        if near(m["from"], m["to"]):
            out.append(f"moved   {m['away']}@{m['home']}  {m['from']} -> {m['to']}")
    for g in diff["removed"]:
        if near(g["date"]):
            out.append(f"removed {g['away']}@{g['home']}  {g['date']}")
    for g in diff["added"]:
        if near(g["date"]):
            out.append(f"added   {g['away']}@{g['home']}  {g['date']}")
    return out


def shrink_problem(diff: dict) -> Optional[str]:
    old, new = diff["old_games"], diff["new_games"]
    if old and new < old * SHRINK_LIMIT:
        return (f"the new schedule has {new} games against {old} in the file "
                f"it would replace (-{old - new}). A partial fetch -- a month "
                "page that failed -- looks exactly like this.")
    return None


def stale_problem(
    schedule: dict,
    path: Optional[Path],
    season_window: Optional[tuple[date, date]],
    today: Optional[date] = None,
    max_age_days: int = MAX_AGE_DAYS,
) -> Optional[str]:
    """Why this schedule must not be simulated on today, or None.

    Only in season: preseason and after the last week nothing publishes
    from it weekly.
    """
    today = today or date.today()
    if season_window is None:
        return None
    week1, season_end = season_window
    if not (week1 <= today <= season_end):
        return None
    when, how = fetched_on(schedule, path)
    if when is None:
        return "the NBA schedule has no fetch date and no file to date it by"
    age = (today - when).days
    if age > max_age_days:
        return (f"the NBA schedule was fetched {when} ({how}), {age} days ago; "
                f"the limit in season is {max_age_days}. Run "
                "py scripts\\fetch_nba_schedule.py (Step 0).")
    return None


def season_window_from(schedule_json: dict) -> Optional[tuple[date, date]]:
    """(week-1 start, last-week end) from a SCHEDULE.json dict."""
    try:
        weeks = sorted(schedule_json.get("weeks", []), key=lambda w: w["week"])
        return (date.fromisoformat(weeks[0]["start_date"]),
                date.fromisoformat(weeks[-1]["end_date"]))
    except Exception:
        return None
