"""
player_actuals.py -- every rostered player's actual fantasy points and games
played, one finished league day at a time, cached (Step 1b; Nick, 11-02) --
and, since 40b (11-13), every non-rostered player the hub names.

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

THE OTHER PLAYERS THE HUB NAMES (40b, 11-13: update_extras)
    The player cards show every carded player's NBA season (ONE FPPG
    EVERYWHERE), so the cache also covers every NON-ROSTERED player the hub
    names: the free agents, the stash, the trade block, the moves feed and
    advice. The same cache and the same rules: finished days only, fetched
    once, never rewritten; a player new to the set is backfilled from the
    season's first day, once; a day is written only when every player asked
    for on it came back.
      - WHICH NAMES: the previous run's output/hub_state.json (every name it
        shows, hub_cards.shown_names), less tonight's rostered players. The
        actuals step runs before the hub step, so tonight's names are not
        known yet: a newly listed player is fetched by the next run (one
        night's lag; his card says "fetched from tonight" meanwhile). A
        player dropped since the previous run is in that payload, so he
        stays covered with no gap; a player the hub no longer names is no
        longer fetched, and his cached days stay.
      - IDS: move_ledger.yahoo_ids, the engine's one id rule (PLAYERLIST's
        yahoo_id, then the transaction log's Yahoo player keys); a name in
        neither has no id and is never guessed (his card says why).
      - THE CAP: config actuals.extra_players_max. More players to fetch
        than the cap RAISES, naming the count; no name is dropped quietly.
      - A SEPARATE PASS, after the rostered one: its own batches, so the
        rostered players' calls are exactly what they were, and a failure
        here never costs a rostered day. The nightly records its failure
        loudly and goes on (the cards it feeds fail softly too); the desk
        script exits 1. extra_names records the last pass's set.

READERS
    hub_state (FPPG, L14; rostered players only, by roster_names); the cards
    (card_lines, any player the cache covers); the newsletter's Keeper Watch
    cards (rostered players). season_performers is unchanged.
"""

from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

CACHE_RELPATH = Path("data") / "player_actuals.json"
HUB_STATE_RELPATH = Path("output") / "hub_state.json"       # the previous run's names (40b)
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
    for name, pid in (blob.get("extra_names") or {}).items():
        if str(pid) not in blob["players"]:
            raise ActualsError(f"{path}: extra name {name!r} points at id {pid}, not cached")
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
        lg = getattr(source, "lg", None) or sp.get_yahoo_league(base)
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
    # "ids" and "source": the extras pass (update_extras) runs after this one
    # with the same Yahoo session and leaves these players to it
    return {"days_fetched": done_days, "through": last.isoformat(), "calls":
            getattr(source, "calls", 0) - calls0, "seconds": seconds,
            "backfilled": new_players, "player_days": per_player_days,
            "players": len(ids), "ids": names_now, "source": source}


# =============================================================================
# the other players the hub names (40b, 11-13)
# =============================================================================

def calls_for(todo: Dict[date, List[int]]) -> int:
    """Yahoo calls a plan costs: two requests (league- and game-scoped) per
    batch of BATCH players per day -- YahooSource.day's own loop (and
    yahoo_fantasy_api's player_stats chunks at 25 too)."""
    return sum(2 * math.ceil(len(pids) / BATCH) for pids in todo.values())


def extras_cap(base_path=".") -> int:
    """config actuals.extra_players_max: required, an int of at least 1."""
    cfg = json.loads((Path(base_path) / "config" / "league_config.json").read_text(encoding="utf-8"))
    v = (cfg.get("actuals") or {}).get("extra_players_max")
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise ActualsError(f"config/league_config.json actuals.extra_players_max is {v!r}: "
                           "a whole number of at least 1 is required")
    return v


def hub_names(base_path=".") -> Tuple[List[str], str]:
    """(every player name the previous run's hub shows, in page order, its
    generated_at). Raises when there is no payload: nothing is assumed."""
    p = Path(base_path) / HUB_STATE_RELPATH
    if not p.is_file():
        raise ActualsError(f"{HUB_STATE_RELPATH.as_posix()} is missing: the free agents to fetch are the "
                           "names the previous hub showed (run python scripts/build_hub_state.py)")
    payload = json.loads(p.read_text(encoding="utf-8"))
    from .hub_cards import CardsError, shown_names
    try:
        names = [n for n, _k in shown_names(payload)]
    except (CardsError, KeyError, TypeError) as e:
        raise ActualsError(f"the names in {HUB_STATE_RELPATH.as_posix()} cannot be read: "
                           f"{type(e).__name__}: {e}") from None
    return list(dict.fromkeys(names)), str(payload.get("generated_at"))


def extra_ids(base_path, names: Iterable[str]) -> Tuple[Dict[str, int], List[str]]:
    """({name: Yahoo id}, [names with none]) by the engine's one id rule,
    move_ledger.yahoo_ids: PLAYERLIST's yahoo_id, then the transaction log's
    Yahoo player keys (the PlayerIndex rules). Never guessed."""
    base = Path(base_path)
    if not (base / "data" / "PLAYERLIST.xlsx").is_file():
        raise ActualsError("data/PLAYERLIST.xlsx is missing: the free agents' Yahoo ids come from it")
    from .move_ledger import yahoo_ids
    from .transaction_log import transactions
    idx = yahoo_ids(base, transactions(base))
    ids, none = {}, []
    for n in names:
        pid = idx.get(n)
        if pid is None:
            none.append(n)
        else:
            ids[n] = int(pid)
    return ids, none


def extras_set(base_path, rostered: Dict[str, int], *, names: List[str] = None,
               generated_at: str = None) -> dict:
    """The non-rostered players to fetch: {"ids": {name: id} (one name per id,
    page order), "no_id": [names], "from": the payload's generated_at, "cap"}.
    `rostered`: tonight's {roster name: id} (update's "ids"); a hub name that
    is one of them, by spelling or by id, is the rostered pass's. RAISES over
    the cap, naming the count."""
    from .data_loader import PlayerIndex
    if names is None:
        names, generated_at = hub_names(base_path)
    ridx = PlayerIndex(dict(rostered))
    rids = {int(v) for v in rostered.values()}
    rest = [n for n in names if ridx.get(n) is None]
    ids, none = extra_ids(base_path, rest)
    out, seen = {}, set()
    for n in rest:
        pid = ids.get(n)
        if pid is None or pid in rids or pid in seen:
            continue
        seen.add(pid)
        out[n] = pid
    cap = extras_cap(base_path)
    if len(out) > cap:
        raise ActualsError(f"the hub names {len(out)} non-rostered players with a Yahoo id, more than "
                           f"actuals.extra_players_max ({cap}) in config/league_config.json: none fetched; "
                           f"check why the list grew ({HUB_STATE_RELPATH.as_posix()} built {generated_at}), "
                           "then raise the cap")
    return {"ids": out, "no_id": list(dict.fromkeys(none)), "from": generated_at, "cap": cap}


def update_extras(base_path=".", *, source, rostered: Dict[str, int], today: date = None,
                  extras: dict = None, dry_run: bool = False) -> dict:
    """Fetch every finished league day the cache lacks for every non-rostered
    player the hub names (extras_set), in their own batches after the rostered
    pass, and write each completed day. RAISES (ActualsError) on the first
    failure, after keeping the days that completed; a partial day is never
    written. dry_run: the plan and its calls, no Yahoo call, nothing written."""
    base = Path(base_path)
    from .league_clock import league_today
    today = today or league_today()
    last = today - timedelta(days=1)
    blob = load(base)
    first = date.fromisoformat(blob["first_day"])
    ex = extras or extras_set(base, rostered)
    ids = ex["ids"]
    names = {pid: n for n, pid in ids.items()}
    for n, pid in ids.items():
        blob["players"].setdefault(str(pid), {"name": n, "days": {}})
    have = {n: len(blob["players"][str(pid)]["days"]) for n, pid in ids.items()}
    new_players = sorted(n for n, k in have.items() if k == 0)
    todo = plan(blob, ids, first, last) if last >= first else {}
    missing = {}
    for pids in todo.values():
        for pid in pids:
            missing[names[pid]] = missing.get(names[pid], 0) + 1
    out = {"through": last.isoformat(), "players": len(ids), "no_id": ex["no_id"], "from": ex["from"],
           "cap": ex["cap"], "backfilled": new_players, "missing_days": missing,
           "planned_days": len(todo), "planned_calls": calls_for(todo), "days_fetched": [], "calls": 0,
           "seconds": 0.0}
    if dry_run:
        return out
    t0 = time.time()
    calls0 = getattr(source, "calls", 0)
    names_now = {n: int(p) for n, p in sorted(ids.items())}
    from .league_clock import league_now
    for d, pids in todo.items():
        got = source.day(pids, d, names)
        for pid, v in got.items():
            blob["players"][str(pid)]["days"][d.isoformat()] = v
        blob["extra_names"] = names_now
        blob["updated_at"] = league_now().isoformat(timespec="seconds")
        write(base, blob, today)
        out["days_fetched"].append(d.isoformat())
    if not todo and blob.get("extra_names") != names_now:
        blob["extra_names"] = names_now
        blob["updated_at"] = league_now().isoformat(timespec="seconds")
        write(base, blob, today)
    out["calls"] = getattr(source, "calls", 0) - calls0
    out["seconds"] = round(time.time() - t0, 1)
    return out


def rostered_dry_plan(base_path=".", today: date = None) -> dict:
    """The rostered pass's plan WITHOUT Yahoo (the desk's dry run): ROSTERS.json
    matched to the cache's last-fetch ids (the PlayerIndex rules). A name the
    cache has no id for is a new pickup: the real run reads his id from
    Yahoo's rosters and backfills him from the season's first day."""
    from .data_loader import PlayerIndex
    from .league_clock import league_today
    from . import season_performers as sp
    base = Path(base_path)
    today = today or league_today()
    last = today - timedelta(days=1)
    blob = load(base)
    first = date.fromisoformat(blob["first_day"])
    idx = PlayerIndex(dict(blob["roster_names"]))
    ids, new = {}, []
    for _m, ns in sp.load_rosters(base).items():
        for n in ns:
            pid = idx.get(n)
            if pid is None:
                new.append(n)
            else:
                ids[n] = int(pid)
    todo = plan(blob, ids, first, last) if last >= first else {}
    n_days = len(days_between(first, last)) if last >= first else 0
    # a new pickup: every day, in one batch of his own per day at worst
    new_calls = 2 * n_days * math.ceil(len(new) / BATCH) if new else 0
    return {"through": last.isoformat(), "players": len(ids) + len(new), "ids": ids, "new": new,
            "planned_days": len(todo), "planned_calls": calls_for(todo) + new_calls}


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

# 40b (11-13): every non-rostered player the hub names is fetched too, from
# the previous run's names; so a player not covered is either new to the
# hub's lists (the next run fetches him) or has no Yahoo id
NOTE_NEVER = "No NBA numbers yet: he is new to the hub's lists, and his daily lines are fetched from tonight"
NOTE_SINCE = ("No NBA numbers yet: he is new to the hub's lists, and his daily lines are fetched from tonight "
              "(the engine has them only through {last})")
NOTE_NO_ID = ("No NBA numbers: he is not in Yahoo's player list (nor in the league's transactions), "
              "so the engine has no Yahoo id to fetch his daily lines with")


def find_days(blob: dict, name: str) -> Optional[dict]:
    """His cached days by any spelling (PlayerIndex rules): the last fetch's
    roster names first, then every name the cache has held -- a player
    dropped since keeps his days up to the drop. None: never in the cache.
    (40b: the last extras pass's names come second.)"""
    from .data_loader import PlayerIndex
    pid = PlayerIndex(blob["roster_names"]).get(name)
    if pid is None and blob.get("extra_names"):
        pid = PlayerIndex(dict(blob["extra_names"])).get(name)
    if pid is None:
        pid = PlayerIndex({rec["name"]: p for p, rec in blob["players"].items()}).get(name)
    if pid is None:
        return None
    return blob["players"][str(pid)]["days"]


def card_lines(blob: dict, names: Iterable[str], through: date, *, required: Iterable[str] = (),
               no_id: Iterable[str] = ()) -> dict:
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
    player dropped since, whose days through that week are all there.
    `no_id` (40b): the non-rostered names with no Yahoo id (extra_ids); one
    not covered gets NOTE_NO_ID, any other NOTE_NEVER / NOTE_SINCE."""
    first = date.fromisoformat(blob["first_day"])
    req = set(required)
    noid = set(no_id)
    lines, notes = {}, {}
    for n in names:
        days = find_days(blob, n)
        if days is None:
            if n in req:
                raise ActualsStale(f"{n} is not in {CACHE_RELPATH} (a roster change since the last "
                                   "fetch): run python scripts/fetch_player_actuals.py")
            lines[n], notes[n] = None, (NOTE_NO_ID if n in noid else NOTE_NEVER)
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
            notes[n] = (NOTE_NO_ID if n in noid else
                        NOTE_SINCE.format(last=_md_text(have[-1])) if have else NOTE_NEVER)
            continue
        lines[n] = [[d.isoformat()] + list(days[d.isoformat()]) for d in want]
    return {"through": through.isoformat(), "first_day": first.isoformat(), "lines": lines, "notes": notes}


def _md_text(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"
