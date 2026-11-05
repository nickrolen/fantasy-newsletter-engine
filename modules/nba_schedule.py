"""
nba_schedule.py -- the NBA schedule the engine reads: which file, and the
stand-ins for games the NBA has not scheduled yet (tasks 46 and 33, 11-05).

WHICH FILE (task 33). The schedule lives in two places:
  the engine's file   league_config season.nba_schedule_file
                      (data/nba_schedule_2026-27.json): public, committed,
                      changed only by a commit and set-engine. The seed.
  the refetched copy  the same name with ".refetched" before ".json"
                      (data/nba_schedule_2026-27.refetched.json): STATE,
                      listed in config/STATE_MANIFEST.json, written by the
                      nightly run's refetch (and by fetch_nba_schedule.py on
                      a desk), pushed with the rest of the state.
  schedule_path() is the copy when it exists, else the engine's file. Every
  reader goes through it: data_loader, price_lock, check_playerlist,
  update_fantasy_logs, generate_stats_report's freshness check;
  season_performers repeats the rule on its own NBA_SCHEDULE_FILE (tests point
  it at fixtures); scripts/run_guard.py (standard library only) repeats it
  too, looking in the state checkout first. tests/test_nba_schedule.py pins
  that they agree.

STAND-INS (task 46). Each NBA team plays `games_per_team` (82) regular-season
games. Before the NBA Cup group stage ends the NBA has published only 80 per
team: the last two go into the Cup knockout window (Dec 4-11, 2026: quarter-
finals Dec 4-5, semifinals Dec 8-9, the final Dec 11, which is not a regular-
season game) and are posted after group play (11-27). Until then the engine
would count every team two games short in fantasy week 7. So the loader adds
a stand-in for every game owed:
  - owed = games_per_team - the team's stored games;
  - each stand-in is dated inside the configured window and marked
    "tbd": true; it has no tip time;
  - deterministic: the same schedule and window always give the same stand-ins;
  - spread evenly over the window's days (one day never holds two more
    stand-ins than another), no team twice on one day, never on a day the team
    already has a stored game;
  - OPPONENTS: two teams that both owe a game are paired. Three counters
    (schedule_strength.count_nba_team_games and get_daily_nba_schedule,
    marginal_value._teams_by_date) drop a game with no home or away, so an
    "unknown" opponent would vanish from exactly the counts the stand-ins are
    for. The one reader that treats an opponent as a fact --
    update_fantasy_logs, which writes nba_opponent into the logs -- reads the
    file without stand-ins (read_raw). Everything else that reads a pair uses
    it only to say which teams play (simulator_betting's team -> opponent map
    is read for its keys; week_state's fingerprint changes when the real
    games replace the stand-ins, which is right). Nothing shows an NBA
    opponent from the schedule.

RAISE, NEVER DEFAULT (StandInError):
  - the config block is missing or malformed;
  - a team owes games and no window is configured;
  - a team owes more games than the window has days it is free;
  - a team has more than games_per_team games;
  - the window is not inside this schedule's season (a stale config after the
    season reset);
  - stand-ins are still needed on or after the window's first day: the NBA
    posted those games a week before; refetch. (A stand-in on a day already
    played would be counted as a game nobody logged.)

The stand-ins are never written to any file: they are made at load.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

REFETCH_SUFFIX = ".refetched"
WINDOW_KEY = "nba_unscheduled_window"         # under league_config "season"


class StandInError(RuntimeError):
    """The unscheduled games cannot be stood in for; the reason is named."""


class RefetchRefused(RuntimeError):
    """A refetched schedule that must not replace the stored one."""


# =============================================================================
# which file
# =============================================================================

def engine_relpath(cfg: dict = None) -> str:
    from .data_loader import _LEAGUE_CONFIG
    season = (cfg or _LEAGUE_CONFIG).get("season") or {}
    rel = season.get("nba_schedule_file")
    if not rel:
        raise StandInError("league_config.json season.nba_schedule_file is not set")
    return str(rel).replace("\\", "/")


def refetched_relpath(engine_rel: str) -> str:
    """data/nba_schedule_2026-27.json -> data/nba_schedule_2026-27.refetched.json"""
    p = Path(engine_rel)
    if p.suffix != ".json":
        raise StandInError(f"season.nba_schedule_file {engine_rel!r} is not a .json file")
    return (p.parent / f"{p.stem}{REFETCH_SUFFIX}.json").as_posix()


def engine_path(base, cfg: dict = None) -> Path:
    return Path(base) / engine_relpath(cfg)


def refetched_path(base, cfg: dict = None) -> Path:
    return Path(base) / refetched_relpath(engine_relpath(cfg))


def schedule_path(base, cfg: dict = None) -> Path:
    """The schedule every reader reads: the refetched copy if it exists, else
    the engine's file."""
    r = refetched_path(base, cfg)
    return r if r.is_file() else engine_path(base, cfg)


def read_raw(path) -> dict:
    """The file as stored: no stand-ins. For the readers that need real games
    only (update_fantasy_logs' opponents; the refetch's comparison)."""
    import json
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"NBA schedule file not found: {p}")
    with open(p, encoding="utf-8") as f:
        blob = json.load(f)
    if not isinstance(blob, dict) or not isinstance(blob.get("games"), list):
        raise StandInError(f"{p}: not a trimmed schedule (no 'games' list)")
    return blob


# =============================================================================
# the window (config)
# =============================================================================

def window_config(cfg: dict = None) -> dict:
    """season.nba_unscheduled_window, checked. Required. "from"/"to" (and
    "cup_final") may all be null: no window, so any team short of
    games_per_team raises."""
    from .data_loader import _LEAGUE_CONFIG
    season = (cfg or _LEAGUE_CONFIG).get("season") or {}
    if WINDOW_KEY not in season:
        raise StandInError(f"league_config.json season.{WINDOW_KEY} is missing (required: the NBA's "
                           "unscheduled-games window, or null dates for none)")
    w = season[WINDOW_KEY]
    if not isinstance(w, dict):
        raise StandInError(f"season.{WINDOW_KEY} must be an object")
    for k in ("from", "to", "cup_final", "games_per_team", "source"):
        if k not in w:
            raise StandInError(f"season.{WINDOW_KEY}.{k} is missing")
    g = w["games_per_team"]
    if isinstance(g, bool) or not isinstance(g, int) or g < 1:
        raise StandInError(f"season.{WINDOW_KEY}.games_per_team must be a positive whole number, "
                           f"not {g!r}")
    ab = ((cfg or _LEAGUE_CONFIG).get("absence_baseline") or {}).get("nba_games_per_team")
    if ab is not None and ab != g:
        raise StandInError(f"season.{WINDOW_KEY}.games_per_team ({g}) and "
                           f"absence_baseline.nba_games_per_team ({ab}) disagree: one season length")
    if not isinstance(w["source"], str) or not w["source"].strip():
        raise StandInError(f"season.{WINDOW_KEY}.source must name where the dates come from")
    dates = {}
    for k in ("from", "to", "cup_final"):
        v = w[k]
        if v is None:
            dates[k] = None
            continue
        try:
            dates[k] = date.fromisoformat(str(v))
        except ValueError:
            raise StandInError(f"season.{WINDOW_KEY}.{k} {v!r} is not a date (YYYY-MM-DD)") from None
    if (dates["from"] is None) != (dates["to"] is None):
        raise StandInError(f"season.{WINDOW_KEY}: from and to are both dates or both null")
    if dates["from"] is not None and dates["from"] > dates["to"]:
        raise StandInError(f"season.{WINDOW_KEY}: from {dates['from']} is after to {dates['to']}")
    return {"from": dates["from"], "to": dates["to"], "cup_final": dates["cup_final"],
            "games_per_team": g, "source": w["source"].strip()}


def window_days(window: dict) -> list:
    if window["from"] is None:
        return []
    n = (window["to"] - window["from"]).days + 1
    return [window["from"] + timedelta(days=i) for i in range(n)]


# =============================================================================
# the stand-ins
# =============================================================================

def _day(g: dict) -> date:
    return date.fromisoformat(str(g.get("date", ""))[:10])


def team_counts(games: list, teams=None) -> Counter:
    """Games per NBA team. A game naming a code that is not an NBA team (an
    All-Star game) is not counted, as schedule_strength's counters skip it."""
    teams = set(teams or _teams())
    c = Counter()
    for g in games:
        h, a = str(g.get("home") or ""), str(g.get("away") or "")
        if h in teams and a in teams:
            c[h] += 1
            c[a] += 1
    return c


def _teams() -> list:
    from .schedule_strength import NBA_TEAMS
    return sorted(NBA_TEAMS)


def owed(raw: dict, window: dict, teams: list = None) -> dict:
    """{team: games owed} (only teams that owe). Raises on a team over
    games_per_team."""
    teams = teams or _teams()
    c = team_counts(raw.get("games", []), teams)
    G = window["games_per_team"]
    over = sorted((t, c[t]) for t in teams if c[t] > G)
    if over:
        raise StandInError(f"more than {G} games for " + ", ".join(f"{t} ({n})" for t, n in over)
                           + ": a non-regular-season game in the schedule (the NBA Cup final?) or a "
                             "double-listed game. Check the fetch before anything is priced")
    return {t: G - c[t] for t in teams if c[t] < G}


def make_standins(raw: dict, window: dict, today: date, teams: list = None) -> list:
    """The stand-in games for `raw` (pure, deterministic). [] when no team owes."""
    teams = teams or _teams()
    need = owed(raw, window, teams)
    if not need:
        return []
    G = window["games_per_team"]
    total = sum(need.values())
    if window["from"] is None:
        raise StandInError(f"{len(need)} team(s) have fewer than {G} games ({total} owed in all; e.g. "
                           f"{', '.join(f'{t} {G - n}' for t, n in sorted(need.items())[:4])}) and no "
                           f"unscheduled-games window is configured (season.{WINDOW_KEY}): refetch "
                           "the schedule, or configure the window")
    days = window_days(window)
    games = raw.get("games", [])
    if not games:
        raise StandInError("the schedule has no games")
    first, last = min(_day(g) for g in games), max(_day(g) for g in games)
    if window["from"] < first or window["to"] > last:
        raise StandInError(f"the unscheduled-games window {window['from']}..{window['to']} is not "
                           f"inside this schedule's season ({first}..{last}): season.{WINDOW_KEY} "
                           "is for another season")
    if today >= window["from"]:
        raise StandInError(f"{total // 2} game(s) in {_range_text(window['from'], window['to'])} are "
                           f"still unscheduled on {today}: the NBA posted these. Refetch the schedule "
                           "(python scripts\\fetch_nba_schedule.py, then python scripts\\state.py "
                           "push), or let tonight's nightly run refetch it")
    busy = {d: set() for d in days}
    for g in games:
        d = _day(g)
        if d in busy:
            busy[d].update((str(g["home"]), str(g["away"])))
    short = sorted((t, n, sum(1 for d in days if t not in busy[d])) for t, n in need.items()
                   if n > sum(1 for d in days if t not in busy[d]))
    if short:
        raise StandInError("more games owed than free days in the window: " + ", ".join(
            f"{t} owes {n}, free on {k} of {len(days)} days" for t, n, k in short))
    if total % 2:
        raise StandInError(f"{total} team-games owed: an odd number cannot be paired into games")
    left = dict(need)
    on_day = {d: 0 for d in days}
    met = set()
    out = []
    while any(left.values()):
        a = sorted((t for t in left if left[t]), key=lambda t: (-left[t], t))[0]
        placed = False
        for d in sorted(days, key=lambda d: (on_day[d], d)):
            if a in busy[d]:
                continue
            cands = [b for b in left if b != a and left[b] and b not in busy[d]]
            if not cands:
                continue
            b = sorted(cands, key=lambda b: (frozenset((a, b)) in met, -left[b], b))[0]
            home, away = sorted((a, b))
            out.append({"date": f"{d.isoformat()}T00:00:00Z", "home": home, "away": away, "tbd": True})
            busy[d].update((a, b))
            on_day[d] += 1
            left[a] -= 1
            left[b] -= 1
            met.add(frozenset((a, b)))
            placed = True
            break
        if not placed:
            raise StandInError(f"could not place {a}'s owed game in {window['from']}..{window['to']} "
                               f"(left: {sorted((t, n) for t, n in left.items() if n)})")
    return out


def with_standins(raw: dict, window: dict, today: date, teams: list = None) -> dict:
    """The schedule as the engine reads it: the stored games plus the
    stand-ins, and, when there are any, an "unscheduled" block describing
    them. The stored dict is not changed."""
    st = make_standins(raw, window, today, teams)
    out = dict(raw)
    out["games"] = list(raw.get("games", [])) + st
    out.pop("unscheduled", None)
    if st:
        per = team_counts(st, teams)
        out["unscheduled"] = {"from": window["from"].isoformat(), "to": window["to"].isoformat(),
                              "source": window["source"], "games": len(st),
                              "per_team": dict(sorted(per.items())),
                              "days": sorted({g["date"][:10] for g in st})}
    return out


def info(schedule: dict) -> Optional[dict]:
    """The "unscheduled" block of a loaded schedule, or None (no stand-ins)."""
    return (schedule or {}).get("unscheduled")


def standin_team_dates(schedule: dict) -> dict:
    """{team: {dates}} of the stand-ins in a loaded schedule."""
    out = {}
    for g in (schedule or {}).get("games", []):
        if g.get("tbd"):
            for side in ("home", "away"):
                out.setdefault(str(g[side]), set()).add(_day(g))
    return out


def _range_text(a: date, b: date) -> str:
    return (f"{a:%b} {a.day}\u2013{b.day}" if a.month == b.month
            else f"{a:%b} {a.day}\u2013{b:%b} {b.day}")


def note_text(block: dict) -> str:
    """The hub's one line while stand-ins exist."""
    a, b = date.fromisoformat(block["from"]), date.fromisoformat(block["to"])
    per = set(block["per_team"].values())
    rng = _range_text(a, b)
    if len(per) == 1 and len(block["per_team"]) == len(_teams()):
        p = per.pop()
        what = f"{p} game{'' if p == 1 else 's'} per team"
    else:
        n = sum(block["per_team"].values())
        what = f"{n} games of {len(block['per_team'])} teams"
    return f"{what} in {rng} not yet scheduled by the NBA; counted on estimated days."


def warn_from(schedule_json: dict, window: dict) -> Optional[date]:
    """The window day (first day) of the fantasy week holding the window's
    first day: from then on, stand-ins still there are a warning (week 7's
    window, Mon 11-30)."""
    if window["from"] is None:
        return None
    for w in schedule_json.get("weeks", []):
        a = date.fromisoformat(str(w["start_date"])[:10])
        b = date.fromisoformat(str(w["end_date"])[:10])
        if a <= window["from"] <= b:
            return a
    raise StandInError(f"the window's first day {window['from']} is in no fantasy week of "
                       "config/SCHEDULE.json")


# =============================================================================
# the refetch (task 33)
# =============================================================================

def exclude_cup_final(games: list, cup_final: Optional[date]) -> tuple:
    """(games without the NBA Cup final, [the excluded game]). The final is
    not a regular-season game (NBA key dates), but basketball-reference lists
    it, marked "NBA Cup" like every Cup game (checked 11-05 on the 2025-26
    pages: the 12-16 final). It is the game on the configured final day whose
    remarks say "NBA Cup"; two such games that day raise. Remarks are dropped."""
    keep, out = [], []
    for g in games:
        g = dict(g)
        remarks = str(g.pop("remarks", "") or "")
        if cup_final is not None and str(g.get("date", ""))[:10] == cup_final.isoformat() \
                and "nba cup" in remarks.lower():
            out.append(g)
            continue
        keep.append(g)
    if len(out) > 1:
        raise RefetchRefused(f"{len(out)} NBA Cup games on the final's day {cup_final}: cannot tell "
                             "which is the final")
    return keep, out


def never_shrinks(old: dict, new: dict) -> list:
    """Why `new` must not replace `old`: fewer games, or any team with fewer
    games than it has stored. [] when it may. Moved dates are allowed."""
    problems = []
    no, nn = len(old.get("games", [])), len(new.get("games", []))
    if nn < no:
        problems.append(f"{nn} games against {no} stored (-{no - nn})")
    co, cn = team_counts(old.get("games", [])), team_counts(new.get("games", []))
    lost = sorted((t, co[t], cn.get(t, 0)) for t in co if cn.get(t, 0) < co[t])
    if lost:
        problems.append("teams with fewer games than stored: "
                        + ", ".join(f"{t} {a} -> {b}" for t, a, b in lost))
    return problems


def refetch(base, today: date, fetch, *, cfg: dict = None, write=True, force: bool = False) -> dict:
    """Fetch the schedule and, if it may replace the stored one, write the
    refetched copy. NEVER RAISES for a failed or refused fetch: the stored
    schedule stays and the outcome says why (a failed fetch doesn't fail the
    night). `fetch()` -> (trimmed schedule, source), tips checked. `force`
    (fetch_nba_schedule.py --force, a person's call; the nightly run never
    passes it) lets a schedule with fewer games through -- a postponement with
    no new date -- and nothing else.

    {"outcome": "updated" | "unchanged" | "failed" | "refused", "why",
     "source", "games", "added", "removed", "moved": [lines], "cup_final":
     [excluded], "from": the file compared with}"""
    from .schedule_freshness import diff_schedules, stamp
    from .data_loader import atomic_write_json
    base = Path(base)
    current = schedule_path(base, cfg)
    rel = current.relative_to(base).as_posix()
    old = read_raw(current)
    try:
        new, source = fetch()
    except BaseException as e:                               # noqa: BLE001 -- SystemExit too
        if isinstance(e, KeyboardInterrupt):
            raise
        return {"outcome": "failed", "why": f"{type(e).__name__}: {e}"[:300], "from": rel}
    window = window_config(cfg)
    try:
        games, final = exclude_cup_final(new.get("games", []), window["cup_final"])
        new = {"games": games}
        shrink = [] if force else never_shrinks(old, new)
        if shrink:
            raise RefetchRefused("; ".join(shrink))
        make_standins(new, window, today)                    # would the loader accept it?
    except (RefetchRefused, StandInError) as e:
        return {"outcome": "refused", "why": str(e)[:400], "source": source, "from": rel}
    diff = diff_schedules(old, new)
    moved = [f"{m['away']}@{m['home']} {m['from']} -> {m['to']}" for m in diff["moved"]]
    same = not (diff["added"] or diff["removed"] or diff["moved"])
    out_blob = stamp({"games": games}, source)        # every game with this fetch's tips
    if write:
        atomic_write_json(refetched_path(base, cfg), out_blob, indent=2)
    return {"outcome": "unchanged" if same else "updated", "why": "", "source": source,
            "games": len(games), "added": len(diff["added"]), "removed": len(diff["removed"]),
            "moved": moved, "cup_final": [f"{g['away']}@{g['home']} {g['date'][:10]}" for g in final],
            "from": rel, "to": refetched_relpath(engine_relpath(cfg))}
