"""
player_actuals.py -- every rostered player's actual fantasy points and games
played, one finished league day at a time, cached (Step 1b; Nick, 11-02).

WHY IT EXISTS
    The hub's roster table shows each player's actual season FPPG and his
    FPPG over the last 14 days. Nothing on disk had either for every rostered
    player: PLAYERLOG only covers games while a player is on a league roster
    (a pickup's earlier games are missing), PLAYERLIST has projections only,
    and the Monday report's season-performers tables are frozen at the week's
    end and cover the top and bottom 30. Nick chose (11-02) Yahoo's daily
    lines, cached per (date, player), so a night costs one day's fetch.

WHERE EVERY NUMBER COMES FROM
    points  the league-scoped daily line's total_points (the league's own
            scoring) -- the same number season_performers sums.
    games   the GAME-scoped daily line's stat 0, Yahoo's "games played": 1 on
            a day he played, cameos with an all-zero stat line included; 0 on
            a DNP; '-' when his team had no game. The league-scoped line
            carries only the league's eleven scoring categories, so it cannot
            tell a DNP from a zero-stat appearance; the game-scoped one can.
            Measured 11-02: Luka Doncic 2026-10-21 -> stat 0 = "1", stat 2
            (minutes) = "30"; Anthony Edwards 2026-10-30 (out) -> "0".

THE CACHE (data/player_actuals.json, private state)
    {"version", "season", "first_day", "players": {yahoo id: {"name",
    "days": {YYYY-MM-DD: [points, games]}}}, "roster_names": {ROSTERS.json
    spelling: yahoo id}, "rosters_from", "updated_at"}.
      - A league day that has FINISHED (before today, Pacific) is fetched once
        and never again. Today's partial lines are never cached: a day on or
        after today refuses to be written.
      - The nightly run fetches only the day just finished. A player new to a
        roster (no cached days) is backfilled from the season's first day,
        once.
      - Every requested player must come back with total_points and stat 0,
        or the whole run REFUSES naming the date and the player. A day is
        written only when every player asked for on it came back: a partial
        day never reaches the cache. Days already complete stay written.

READERS
    hub_state (FPPG, L14). Never the newsletter (season_performers is
    unchanged; whether it could read this file is a later decision).
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

CACHE_RELPATH = Path("data") / "player_actuals.json"
VERSION = 1
BATCH = 25
GP_STAT = "0"               # Yahoo NBA stat id 0: games played
L14_DAYS = 14


class ActualsError(RuntimeError):
    """A fetch, a parse or the cache is not what it must be. Never defaulted."""


class ActualsStale(ActualsError):
    """The cache does not cover the days a reader needs."""


# =============================================================================
# the cache
# =============================================================================

def cache_path(base_path=".") -> Path:
    return Path(base_path) / CACHE_RELPATH


def empty(season: str, first_day: date) -> dict:
    return {"version": VERSION, "season": season, "first_day": first_day.isoformat(),
            "players": {}, "roster_names": {}, "rosters_from": None, "updated_at": None}


def validate(blob: dict, path="data/player_actuals.json") -> dict:
    """The cache as written, or ActualsError naming what is wrong."""
    for k in ("version", "season", "first_day", "players", "roster_names"):
        if k not in blob:
            raise ActualsError(f"{path} has no {k!r}")
    if blob["version"] != VERSION:
        raise ActualsError(f"{path} is version {blob['version']}, this code reads {VERSION}")
    date.fromisoformat(blob["first_day"])
    for pid, rec in blob["players"].items():
        if not str(pid).isdigit() or "name" not in rec or not isinstance(rec.get("days"), dict):
            raise ActualsError(f"{path}: player {pid!r} is malformed")
        for d, v in rec["days"].items():
            date.fromisoformat(d)
            if (not isinstance(v, list) or len(v) != 2 or not isinstance(v[0], (int, float))
                    or v[1] not in (0, 1)):
                raise ActualsError(f"{path}: {rec['name']} {d} is {v!r}, not [points, 0|1]")
            if v[1] == 0 and v[0] != 0:
                raise ActualsError(f"{path}: {rec['name']} {d} has {v[0]} points and no game")
    for name, pid in blob["roster_names"].items():
        if str(pid) not in blob["players"]:
            raise ActualsError(f"{path}: roster name {name!r} points at id {pid}, not cached")
    return blob


def load(base_path=".", *, required: bool = True) -> Optional[dict]:
    p = cache_path(base_path)
    if not p.is_file():
        if required:
            raise ActualsError(f"{CACHE_RELPATH} is missing: run python scripts/fetch_player_actuals.py")
        return None
    return validate(json.loads(p.read_text(encoding="utf-8")), CACHE_RELPATH)


def write(base_path, blob: dict, today: date) -> None:
    """Atomically. Refuses a day on or after `today` (a league day not yet
    finished) -- the one guard against caching partial lines."""
    for rec in blob["players"].values():
        late = [d for d in rec["days"] if date.fromisoformat(d) >= today]
        if late:
            raise ActualsError(f"refusing to cache {rec['name']} {late}: on or after today "
                               f"({today}), a league day that has not finished")
    validate(blob)
    from .data_loader import atomic_write_json
    atomic_write_json(cache_path(base_path), blob, indent=1)


# =============================================================================
# Yahoo
# =============================================================================

def _num(x) -> Optional[float]:
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x))
    except (TypeError, ValueError):
        return None


def parse_game_lines(raw: dict) -> Dict[int, str]:
    """{yahoo id: stat 0's raw value} from a game-scoped players/stats
    response. Raises on a shape it does not recognise."""
    try:
        players = raw["fantasy_content"]["players"]
    except (KeyError, TypeError):
        raise ActualsError("Yahoo's game-scoped stats response has no players block")
    out = {}
    for k, v in players.items():
        if k == "count":
            continue
        parts = v.get("player") if isinstance(v, dict) else None
        if not isinstance(parts, list) or len(parts) < 2:
            raise ActualsError(f"Yahoo's game-scoped stats: player entry {k} is malformed")
        pid = None
        for item in parts[0]:
            if isinstance(item, dict) and "player_id" in item:
                pid = int(item["player_id"])
        if pid is None:
            raise ActualsError(f"Yahoo's game-scoped stats: player entry {k} has no player_id")
        gp = None
        stats = ((parts[1] or {}).get("player_stats") or {}).get("stats") or []
        for s in stats:
            st = s.get("stat") or {}
            if str(st.get("stat_id")) == GP_STAT:
                gp = st.get("value")
        out[pid] = gp
    return out


def games_value(raw_value, who: str, d: date) -> int:
    if raw_value in ("1", 1):
        return 1
    if raw_value in ("0", 0, "-"):
        return 0
    raise ActualsError(f"Yahoo's {d} games-played stat for {who} is {raw_value!r}, not 0, 1 or '-'")


class YahooSource:
    """The two daily requests, one batch at a time. `lg` is a
    yahoo_fantasy_api League. Counts its calls."""

    def __init__(self, lg):
        self.lg = lg
        self.game_key = str(lg.league_id).split(".")[0]
        self.calls = 0

    def day(self, pids: List[int], d: date, names: Dict[int, str]) -> Dict[int, list]:
        """{pid: [points, games]} for every pid on day d, or ActualsError
        naming the date and the player."""
        out = {}
        for i in range(0, len(pids), BATCH):
            chunk = pids[i:i + BATCH]
            try:
                rows = self.lg.player_stats(chunk, "date", date=d)
                self.calls += 1
                keys = ",".join(f"{self.game_key}.p.{p}" for p in chunk)
                raw = self.lg.yhandler.get(f"players;player_keys={keys}/stats;type=date;date={d.isoformat()}")
                self.calls += 1
            except ActualsError:
                raise
            except Exception as e:                     # network, auth, parse
                raise ActualsError(f"Yahoo request for {d} failed ({type(e).__name__}: {e}) "
                                   f"for {', '.join(names[p] for p in chunk)}") from e
            pts = {}
            for r in rows:
                pid = int(r.get("player_id", 0))
                if pid in chunk:
                    if "total_points" not in r:
                        raise ActualsError(f"Yahoo's {d} line for {names[pid]} has no total_points")
                    v = _num(r["total_points"])
                    pts[pid] = 0.0 if v is None else v
            gps = parse_game_lines(raw)
            for pid in chunk:
                if pid not in pts:
                    raise ActualsError(f"Yahoo returned no {d} league line for {names[pid]}")
                if pid not in gps or gps[pid] is None:
                    raise ActualsError(f"Yahoo returned no {d} games-played stat for {names[pid]}")
                g = games_value(gps[pid], names[pid], d)
                if g == 0 and pts[pid] != 0:
                    raise ActualsError(f"Yahoo's {d} line for {names[pid]}: {pts[pid]} points "
                                       "and no game played")
                out[pid] = [round(pts[pid], 2), g]
        return out


# =============================================================================
# the update
# =============================================================================

def days_between(first: date, last: date) -> List[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def plan(blob: dict, ids: Dict[str, int], first: date, last: date) -> Dict[date, List[int]]:
    """{day: [ids missing it]} over [first, last]."""
    want: Dict[date, List[int]] = {}
    for pid in sorted(set(ids.values())):
        have = (blob["players"].get(str(pid)) or {}).get("days") or {}
        for d in days_between(first, last):
            if d.isoformat() not in have:
                want.setdefault(d, []).append(pid)
    return dict(sorted(want.items()))


def update(base_path=".", *, source=None, ids: Dict[str, int] = None, yahoo_names=None,
           today: date = None, first_day: date = None, season: str = None,
           echo: Callable = print) -> dict:
    """Fetch every finished league day the cache lacks for every rostered
    player, write each completed day, and report. RAISES (ActualsError) on the
    first failure, after keeping the days that completed."""
    base = Path(base_path)
    from .league_clock import league_today
    today = today or league_today()
    last = today - timedelta(days=1)
    if season is None or first_day is None:
        from .data_loader import CURRENT_SEASON
        from . import season_performers as sp
        season = season or CURRENT_SEASON
        first_day = first_day or sp.season_first_day(sp.load_nba_schedule(base))
    blob = load(base, required=False) or empty(season, first_day)
    if blob["season"] != season or blob["first_day"] != first_day.isoformat():
        raise ActualsError(f"{CACHE_RELPATH} is for {blob['season']} from {blob['first_day']}, "
                           f"not {season} from {first_day}: a new season starts a new file")
    if source is None or ids is None:
        from . import season_performers as sp
        lg = sp.get_yahoo_league(base)
        source = source or YahooSource(lg)
        if ids is None:
            ids, failures = sp.roster_player_ids(lg, sp.load_rosters(base))
            if failures:
                raise ActualsError("rostered players with no Yahoo id: " + "; ".join(failures))
    names = {pid: n for n, pid in ids.items()}
    for n, pid in ids.items():
        rec = blob["players"].setdefault(str(pid), {"name": n, "days": {}})
        rec["name"] = n
    new_players = sorted(n for n, pid in ids.items() if not blob["players"][str(pid)]["days"])
    todo = plan(blob, ids, first_day, last) if last >= first_day else {}
    t0 = time.time()
    calls0 = getattr(source, "calls", 0)
    done_days = []
    per_player_days: Dict[str, int] = {}
    for d, pids in todo.items():
        got = source.day(pids, d, names)
        for pid, v in got.items():
            blob["players"][str(pid)]["days"][d.isoformat()] = v
            per_player_days[names[pid]] = per_player_days.get(names[pid], 0) + 1
        blob["roster_names"] = {n: int(p) for n, p in sorted(ids.items())}
        blob["rosters_from"] = "config/ROSTERS.json"
        from .league_clock import league_now
        blob["updated_at"] = league_now().isoformat(timespec="seconds")
        write(base, blob, today)
        done_days.append(d.isoformat())
    names_now = {n: int(p) for n, p in sorted(ids.items())}
    if not todo and blob["roster_names"] != names_now:
        # a roster change whose players are all cached already (a re-add)
        blob["roster_names"] = names_now
        blob["rosters_from"] = "config/ROSTERS.json"
        from .league_clock import league_now
        blob["updated_at"] = league_now().isoformat(timespec="seconds")
        write(base, blob, today)
    # nothing fetched and nothing renamed: the file is left exactly as it was
    seconds = round(time.time() - t0, 1)
    return {"days_fetched": done_days, "through": last.isoformat(), "calls":
            getattr(source, "calls", 0) - calls0, "seconds": seconds,
            "backfilled": new_players, "player_days": per_player_days,
            "players": len(ids)}


# =============================================================================
# the readers
# =============================================================================

def player_days(blob: dict, roster_name: str) -> dict:
    """His cached days, by the ROSTERS.json spelling. Raises if he is not in
    the last fetch's rosters (a pickup since: run the fetch)."""
    from .data_loader import PlayerIndex
    pid = PlayerIndex(blob["roster_names"]).get(roster_name)
    if pid is None:
        raise ActualsStale(f"{roster_name} is not in {CACHE_RELPATH} (a roster change since the "
                           "last fetch): run python scripts/fetch_player_actuals.py")
    return blob["players"][str(pid)]["days"]


def window(blob: dict, roster_name: str, first: date, last: date) -> Tuple[float, int]:
    """(points, games) over [first, last]; ActualsStale if any day is missing."""
    days = player_days(blob, roster_name)
    pts, gp, missing = 0.0, 0, []
    for d in days_between(first, last):
        v = days.get(d.isoformat())
        if v is None:
            missing.append(d.isoformat())
            continue
        pts += v[0]
        gp += v[1]
    if missing:
        raise ActualsStale(f"{CACHE_RELPATH} lacks {roster_name} on {missing[0]}"
                           + (f" and {len(missing) - 1} more day(s)" if len(missing) > 1 else "")
                           + ": run python scripts/fetch_player_actuals.py")
    return round(pts, 2), gp


def season(blob: dict, roster_name: str, through: date) -> Tuple[float, int]:
    return window(blob, roster_name, date.fromisoformat(blob["first_day"]), through)


def last14(blob: dict, roster_name: str, through: date) -> Tuple[float, int]:
    """The last 14 finished league days ending `through`, clipped to the
    season's first day."""
    first = max(date.fromisoformat(blob["first_day"]), through - timedelta(days=L14_DAYS - 1))
    return window(blob, roster_name, first, through)


def fppg_text(points: float, games: int) -> str:
    """One decimal, or an em dash with no games in the window."""
    return "\u2014" if games == 0 else f"{points / games:.1f}"


# =============================================================================
# the player cards' NBA numbers (11-12, Nick: "one FPPG everywhere", option c)
# =============================================================================

NOTE_NEVER = ("No NBA numbers: the engine fetches Yahoo's daily lines only for rostered players, "
              "and has none for him")
NOTE_SINCE = ("No NBA numbers: the engine fetches Yahoo's daily lines only for rostered players, "
              "and has his only through {last}")


def find_days(blob: dict, name: str) -> Optional[dict]:
    """His cached days by any spelling (PlayerIndex rules): the last fetch's
    roster names first, then every name the cache has held -- a player
    dropped since keeps his days up to the drop. None: never in the cache."""
    from .data_loader import PlayerIndex
    pid = PlayerIndex(blob["roster_names"]).get(name)
    if pid is None:
        pid = PlayerIndex({rec["name"]: p for p, rec in blob["players"].items()}).get(name)
    if pid is None:
        return None
    return blob["players"][str(pid)]["days"]


def card_lines(blob: dict, names: Iterable[str], through: date, *, required: Iterable[str] = ()) -> dict:
    """Each card player's NBA season, every game he played from the season's
    first day through `through` -- the numbers the hub's roster table shows
    (season(): the same cache, the same days, the same sums).

    Returns {"through": iso, "first_day": iso, "lines": {name: [[iso, points,
    games], ...] (every day, in order) or None}, "notes": {name: why None}}.
    A player is covered only when the cache has EVERY day of the window: a
    partial window is not his season. `required` (the rostered players): one
    not covered RAISES (ActualsStale), as the roster table does -- never a
    note standing in for a fetch gap. Every player is found by any spelling
    the cache has held (find_days): the newsletter's report week can name a
    player dropped since, whose days through that week are all there."""
    first = date.fromisoformat(blob["first_day"])
    req = set(required)
    lines, notes = {}, {}
    for n in names:
        days = find_days(blob, n)
        if days is None:
            if n in req:
                raise ActualsStale(f"{n} is not in {CACHE_RELPATH} (a roster change since the last "
                                   "fetch): run python scripts/fetch_player_actuals.py")
            lines[n], notes[n] = None, NOTE_NEVER
            continue
        want = days_between(first, through) if through >= first else []
        gaps = [d.isoformat() for d in want if d.isoformat() not in days]
        if gaps:
            if n in req:
                raise ActualsStale(f"{CACHE_RELPATH} lacks {n} on {gaps[0]}"
                                   + (f" and {len(gaps) - 1} more day(s)" if len(gaps) > 1 else "")
                                   + ": run python scripts/fetch_player_actuals.py")
            have = sorted(d for d in days if d <= through.isoformat())
            lines[n] = None
            notes[n] = NOTE_SINCE.format(last=_md_text(have[-1])) if have else NOTE_NEVER
            continue
        lines[n] = [[d.isoformat()] + list(days[d.isoformat()]) for d in want]
    return {"through": through.isoformat(), "first_day": first.isoformat(), "lines": lines, "notes": notes}


def _md_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"
