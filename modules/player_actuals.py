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
    {"version", "season", "first_day", "cats": {"order", "values"},
    "players": {yahoo id: {"name", "days": {YYYY-MM-DD: [points, games]},
    "cat_days": {YYYY-MM-DD: [one count per cats.order]},
    "cat_corrections": {YYYY-MM-DD: Yahoo's total when the categories came}}},
    "roster_names": {ROSTERS.json spelling: yahoo id}, "extra_names",
    "rosters_from", "updated_at"}.
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

THE CATEGORIES (4a2, 11-14: version 2; the card's grade tiles and the archetype)
    The league-scoped line the nightly already fetches carries the league's
    eleven scoring categories (yahoo_settings.stat_values: FGM FGA FTM FTA
    3PTM PTS REB AST ST BLK TO), so from version 2 each fetched day keeps them
    too, at no extra call.
      - SHAPE: a separate map beside "days" ("cat_days"), so [points, games]
        and every reader of it are exactly what they were. Each day is a list
        of whole counts in the file's own "cats.order" (stored once at the top
        with "cats.values", the points each is worth): a list, not a dict, at a
        third of the size, and the file names its own order.
      - VERSION 1 (before 4a2) still reads: it has no categories. A day with
        no categories is simply absent from cat_days (never zeros);
        category_season says "loading" for him.
      - A DAY HE DID NOT PLAY (games 0, points 0): eleven zeros, Yahoo's own
        "-" read as nothing done. Never on a day he played.
      - CHECKS (validate, on every load; and on every fetch): the counts x
        cats.values equal the day's cached points to the cent, PTS = 2 FGM +
        3PTM + FTM, FGM <= FGA, FTM <= FTA, 3PTM <= FGM. A mismatch RAISES,
        naming the player and the day: it would mean the scoring changed or
        the categories are misread.
      - A STAT CORRECTION: the backfill fetches a day weeks later, after any
        NBA stat correction. When Yahoo's total now differs from the cached
        points AND the categories score exactly Yahoo's total now, the day's
        points stay as cached (fetched once, never rewritten) and the new
        total is kept in "cat_corrections" so the check still holds. Any
        other mismatch raises.
      - THE NIGHTLY'S DAY: categories from the same rows as the points. A
        category problem never costs the points: that day's categories are
        left out and the error is returned ("cat_errors") for the run to
        record; the backfill retries the day.
      - THE BACKFILL (backfill_categories, the nightly only): days cached
        without categories, oldest first, for the players the last passes
        tracked (roster_names and extra_names), at most config
        actuals.category_backfill_calls_max calls a night. Only the
        league-scoped request (1 call per 25 players who played that day);
        the players who did not play get zeros with no call. A day is
        written only when every player asked for on it came back. Its
        failure is soft and loud: the nightly records it and goes on.

THE MINUTES (4a3, 11-19: the roster's MIN and MIN delta, the card's last
5 games, Compare)
    The GAME-scoped daily line the nightly already fetches for games played
    (stat 0) carries stat 2, minutes, in the same response, so from 4a3 each
    fetched day keeps them too, at no extra call (both passes: the extras
    pass makes the same request).
      - SHAPE: "min_days" beside "days" and "cat_days", {YYYY-MM-DD: whole
        minutes}. Still version 2: the map is optional, every reader of
        "days" and "cat_days" is unchanged, and code from before 4a3 reads
        and rewrites a file that has it (it keeps the map and adds no
        minutes), so rolling the engine back needs no downgrade.
      - AN ENTRY ON EVERY CACHED DAY, like cat_days: the minutes on a day
        he played (games 1; a cameo with no time recorded is a legal 0),
        and 0 on a day he did not (games 0). The cache's "days" already
        stores a DNP and a day with no team game alike ([0, 0]; Yahoo's
        "-" is read as 0 at the fetch), so the minutes cannot tell them
        apart either; no reader needs to (MIN counts the games he played).
        "Is this day complete" is then: min_days has the day.
      - FORMAT (parse_minutes): Yahoo's "30" or "30:12" (whole minutes,
        seconds rounded half up: "30:30" is 31), or "-" / absent / "0" on a
        day he did not play. CHECKS that RAISE (MinutesError), naming the
        player and the day: minutes over 0 with games played 0; games
        played 1 with no minutes; over MIN_MAX (70) minutes; anything else.
        validate() checks every stored entry the same way.
      - THE NIGHTLY'S DAY: minutes from the same game-scoped rows as stat 0.
        A minutes problem never costs the day's points or categories: that
        day's minutes are left out for the pass and the error is returned
        ("min_errors") for the run to record (MINUTES FAILED); the backfill
        retries the day.
      - THE BACKFILL (backfill_minutes, the nightly only): days cached
        without minutes, oldest first, for the tracked players (roster_names
        and extra_names), at most config actuals.minutes_backfill_calls_max
        calls a night. Only the game-scoped request (1 call per 25 players
        who played that day); a player who did not play gets 0 with no call.
        A day is written only when every player asked for on it came back,
        still with games played 1. Its failure is soft and loud.
      - A PHANTOM GAME (5c, 11-20): Yahoo's line for a day can say games
        played 1 with every stat empty when the day is fetched, and games
        played 0 later (Donovan Mitchell and Evan Mobley on 2026-11-14, Austin
        Reaves on 2026-11-18: each game was final hours before the 12:05 AM
        fetch, so it was Yahoo's line, not an early fetch). When the backfill
        reads games played 0 for a day the cache holds as EXACTLY a phantom
        -- 0 points, 1 game, its categories cached and every one 0 --
        it is Yahoo's correction: the day is rewritten as a day he did not
        play (0 points, 0 games; categories eleven zeros and minutes 0, the
        cache's shape for such a day, so neither backfill asks for it again),
        recorded in the run's "corrections", and the backfill goes on (is_phantom,
        correct_phantom). Any other disagreement (points, a category, or no
        categories cached yet) still RAISES, as before. This is the only
        place the cache's games count is read back from Yahoo: the daily
        passes fetch a day once, and the category backfill's league-scoped
        line carries no games played.

LATE-FILLED LINES AND HELD LINES (5d1, 11-21; config actuals.recheck_days)
    - AN INCOMPLETE LINE (Zion Williamson 2026-11-14): a day cached as 0
      points in 1 game whose categories now score a non-zero total. Yahoo
      filled the stats in late; it is not a stat correction. The day is
      rewritten with Yahoo's total and its categories, kept in the player's
      "late_filled" ({day: {"was", "now"}}), and recorded (LATE STAT LINE
      FILLED). It is caught by the backfill (a day with no categories yet),
      by recheck_recent (the nightly re-checks the last recheck_days days for
      any day cached as 0 points in 1 game), and, with no call, by
      settle_recorded_late_lines for one the old rule kept as a correction.
      A phantom (Yahoo now says games played 0) is still 5c's rule. Any other
      late change to a saved day is a stat correction, never rewritten.
    - A HELD LINE (Nickeil Alexander-Walker 2026-11-20: PTS 19 is not 2 FGM
      + 3PTM + FTM, the same line ~5 and ~19 hours after the final): one
      player's line that doesn't add up holds back only him. The others'
      categories are written; his day goes in "cat_pending" ({day: why},
      CATEGORIES PENDING) and is retried while it is within recheck_days of
      today. When Yahoo's line adds up, it is written (and his points, if
      Yahoo's total differs, as a late-filled line: they came from the line
      that didn't add up). Past the window, it goes in "cat_missing" ({day:
      "Yahoo's line never added up: ..."}), recorded once, and is never asked
      for again. category_season leaves a held or missing day's game out of
      the totals (never "loading" for it). When EVERY player asked for fails
      (two or more), it is the whole day's error, as before: nothing is held;
      the backfill records it and goes on to the next day.
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
    cards (rostered players); ratings (category_season, 4a2); the new hub's
    MIN, MIN delta and the card's last-5 minutes (minutes_games, 4a3). None
    of the points readers reads cat_days or min_days. season_performers is
    unchanged.
"""

from __future__ import annotations

import inspect
import json
import math
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

CACHE_RELPATH = Path("data") / "player_actuals.json"
HUB_STATE_RELPATH = Path("output") / "hub_state.json"       # the previous run's names (40b)
VERSION = 2                 # 4a2: per-day categories (cat_days)
READS = (1, 2)              # version 1 has no categories and still reads
BATCH = 25
CAT_TOL = 0.011             # counts x values vs total points: to the cent
GP_STAT = "0"               # Yahoo NBA stat id 0: games played
MIN_STAT = "2"              # Yahoo NBA stat id 2: minutes (4a3; the same game-scoped response)
MIN_MAX = 70                # minutes in one game over this RAISE: misread (4a3; 70, not 65, so a
                            # quadruple-overtime game, up to ~68, never stalls a day: 11-19 review)
L14_DAYS = 14


class ActualsError(RuntimeError):
    """A fetch, a parse or the cache is not what it must be. Never defaulted."""


class ActualsStale(ActualsError):
    """The cache does not cover the days a reader needs."""


class CategoryError(ActualsError):
    """A day's category line is missing, malformed, or does not score the
    day's points (4a2). Names the player and the day."""


class MinutesError(ActualsError):
    """A day's minutes are missing, malformed, or disagree with games played
    (4a3). Names the player and the day."""


# =============================================================================
# the cache
# =============================================================================

def cache_path(base_path=".") -> Path:
    return Path(base_path) / CACHE_RELPATH


def empty(season: str, first_day: date, header: Optional[dict] = None) -> dict:
    """A new cache: version 2 with the categories' header, or (no header: a
    source with no categories) version 1, which ensure_cats upgrades."""
    blob = {"version": 1, "season": season, "first_day": first_day.isoformat(),
            "players": {}, "roster_names": {}, "rosters_from": None, "updated_at": None}
    return ensure_cats(blob, header) if header is not None else blob


def validate(blob: dict, path="data/player_actuals.json") -> dict:
    """The cache as written, or ActualsError naming what is wrong."""
    for k in ("version", "season", "first_day", "players", "roster_names"):
        if k not in blob:
            raise ActualsError(f"{path} has no {k!r}")
    if blob["version"] not in READS:
        raise ActualsError(f"{path} is version {blob['version']}, this code reads {READS}")
    date.fromisoformat(blob["first_day"])
    header = blob.get("cats")
    if blob["version"] == 1 and header is not None:
        raise ActualsError(f"{path} is version 1 but has categories")
    if blob["version"] >= 2:
        _check_header(header, path)
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
        _check_cat_days(rec, header, path)
        _check_min_days(rec, path)
        _check_held_days(rec, path)
    for name, pid in blob["roster_names"].items():
        if str(pid) not in blob["players"]:
            raise ActualsError(f"{path}: roster name {name!r} points at id {pid}, not cached")
    for name, pid in (blob.get("extra_names") or {}).items():
        if str(pid) not in blob["players"]:
            raise ActualsError(f"{path}: extra name {name!r} points at id {pid}, not cached")
    return blob


def _check_header(header, path) -> None:
    ok = (isinstance(header, dict) and isinstance(header.get("order"), list)
          and isinstance(header.get("values"), list) and header["order"]
          and len(header["order"]) == len(header["values"])
          and all(isinstance(c, str) and c for c in header["order"])
          and len(set(header["order"])) == len(header["order"])
          and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in header["values"]))
    if not ok:
        raise ActualsError(f"{path}: \"cats\" must be {{\"order\": [names], \"values\": [numbers]}}, "
                           f"one value per name; it is {header!r}")


def _check_cat_days(rec: dict, header: Optional[dict], path) -> None:
    cd = rec.get("cat_days")
    corr = rec.get("cat_corrections") or {}
    if cd is None:
        if corr:
            raise ActualsError(f"{path}: {rec['name']} has cat_corrections and no cat_days")
        return
    if header is None:
        raise ActualsError(f"{path}: {rec['name']} has categories but the file has no \"cats\" header")
    if not isinstance(cd, dict) or not isinstance(corr, dict):
        raise ActualsError(f"{path}: {rec['name']}'s cat_days or cat_corrections is malformed")
    n = len(header["order"])
    for d, v in cd.items():
        if d not in rec["days"]:
            raise ActualsError(f"{path}: {rec['name']} has categories on {d}, a day with no points cached")
        if (not isinstance(v, list) or len(v) != n
                or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in v)):
            raise ActualsError(f"{path}: {rec['name']} {d} categories are {v!r}, not {n} whole counts")
        pts, games = rec["days"][d]
        if games == 0 and any(v):
            raise ActualsError(f"{path}: {rec['name']} {d} has categories {v} and no game")
        c = corr.get(d)
        if c is not None and not isinstance(c, (int, float)):
            raise ActualsError(f"{path}: {rec['name']} {d} correction is {c!r}")
        check_cats(v, header, pts, rec["name"], d, corrected=c)
    for d in corr:
        if d not in cd:
            raise ActualsError(f"{path}: {rec['name']} has a correction on {d} and no categories that day")


def _check_held_days(rec: dict, path) -> None:
    """5d1: "cat_pending" (a line that didn't add up, retried) and
    "cat_missing" (given up) are {day: reason} on a cached day he played,
    with no categories that day; "late_filled" is {day: {"was", "now"}} on a
    cached day whose points are "now"."""
    for k in ("cat_pending", "cat_missing"):
        m = rec.get(k)
        if m is None:
            continue
        if not isinstance(m, dict):
            raise ActualsError(f"{path}: {rec['name']}'s {k} is malformed")
        for d, why in m.items():
            v = rec["days"].get(d)
            if v is None or v[1] != 1 or not isinstance(why, str) or not why:
                raise ActualsError(f"{path}: {rec['name']} {k} {d} is not a played, cached day with a reason")
            if d in (rec.get("cat_days") or {}):
                raise ActualsError(f"{path}: {rec['name']} {d} is in {k} and has categories")
    lf = rec.get("late_filled")
    if lf is not None:
        if not isinstance(lf, dict):
            raise ActualsError(f"{path}: {rec['name']}'s late_filled is malformed")
        for d, e in lf.items():
            v = rec["days"].get(d)
            if (v is None or not isinstance(e, dict) or set(e) != {"was", "now"}
                    or abs(float(v[0]) - float(e["now"])) > CAT_TOL):
                raise ActualsError(f"{path}: {rec['name']} late_filled {d} is {e!r}, not the day's points")


def _check_min_days(rec: dict, path) -> None:
    """4a3: each entry is on a cached day, whole minutes from 0 to MIN_MAX,
    and 0 on a day he did not play."""
    md = rec.get("min_days")
    if md is None:
        return
    if not isinstance(md, dict):
        raise ActualsError(f"{path}: {rec['name']}'s min_days is malformed")
    for d, m in md.items():
        if d not in rec["days"]:
            raise ActualsError(f"{path}: {rec['name']} has minutes on {d}, a day with no points cached")
        if not isinstance(m, int) or isinstance(m, bool) or m < 0 or m > MIN_MAX:
            raise ActualsError(f"{path}: {rec['name']} {d} minutes are {m!r}, not whole minutes from 0 to {MIN_MAX}")
        if rec["days"][d][1] == 0 and m != 0:
            raise ActualsError(f"{path}: {rec['name']} {d} has {m} minutes and no game")


def scoring_header(base_path=".") -> dict:
    """{"order": [category], "values": [points each]} from config
    yahoo_settings.stat_values (the scoring yahoo_settings checks against
    Yahoo on every run of record), in its own order. Required."""
    cfg = json.loads((Path(base_path) / "config" / "league_config.json").read_text(encoding="utf-8"))
    sv = (cfg.get("yahoo_settings") or {}).get("stat_values")
    if (not isinstance(sv, dict) or not sv
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in sv.values())):
        raise ActualsError("config/league_config.json yahoo_settings.stat_values is missing or malformed: "
                           "the categories' order and values come from it")
    return {"order": [str(k) for k in sv], "values": [float(v) for v in sv.values()]}


def ensure_cats(blob: dict, header: dict) -> dict:
    """Version 2 with this header; the stored header must be the config's.
    A different one RAISES: the scoring changed mid-season."""
    have = blob.get("cats")
    want = {"order": list(header["order"]), "values": [float(x) for x in header["values"]]}
    if have is None:
        blob["cats"] = want
        blob["version"] = VERSION
    elif (list(have["order"]) != want["order"]
          or [float(x) for x in have["values"]] != want["values"]):
        raise ActualsError(f"{CACHE_RELPATH} stores categories scored {have}, but config yahoo_settings."
                           f"stat_values is now {want}: the scoring changed mid-season; the stored days "
                           "cannot be mixed with new ones")
    return blob


def cat_points(cats: List[int], header: dict) -> float:
    return sum(c * float(v) for c, v in zip(cats, header["values"]))


def check_cats(cats: List[int], header: dict, points: float, who: str, d, corrected=None) -> None:
    """The basketball identities, then counts x values = points (or, after a
    stat correction, = the corrected total). RAISES CategoryError naming him
    and the day."""
    pos = {c: i for i, c in enumerate(header["order"])}

    def g(c):
        return cats[pos[c]]
    if all(c in pos for c in ("PTS", "FGM", "3PTM", "FTM")) and g("PTS") != 2 * g("FGM") + g("3PTM") + g("FTM"):
        raise CategoryError(f"{who} {d}: PTS {g('PTS')} is not 2 x FGM {g('FGM')} + 3PTM {g('3PTM')} + "
                            f"FTM {g('FTM')}: the categories are misread")
    for a, b in (("FGM", "FGA"), ("FTM", "FTA"), ("3PTM", "FGM")):
        if a in pos and b in pos and g(a) > g(b):
            raise CategoryError(f"{who} {d}: {a} {g(a)} is more than {b} {g(b)}: the categories are misread")
    tot = cat_points(cats, header)
    if abs(tot - float(points)) > CAT_TOL and (corrected is None or abs(tot - float(corrected)) > CAT_TOL):
        raise CategoryError(f"{who} {d}: the categories score {tot:.2f} at the league's values but the "
                            f"day's points are {points}"
                            + (f" (corrected {corrected})" if corrected is not None else "")
                            + ": the scoring changed, or the categories are misread")


def parse_cats(row: dict, header: dict, who: str, d, games: int) -> List[int]:
    """One league-scoped row's categories in header order, whole counts.
    Yahoo's "-" is nothing done, accepted only on a day he did not play."""
    out = []
    for c in header["order"]:
        if c not in row:
            raise CategoryError(f"Yahoo's {d} line for {who} has no {c}")
        v = row[c]
        if v in ("-", "", None):
            if games == 0:
                out.append(0)
                continue
            raise CategoryError(f"Yahoo's {d} line for {who}: {c} is {v!r} on a day he played")
        x = _num(v)
        if x is None or x < 0 or x != int(x):
            raise CategoryError(f"Yahoo's {d} line for {who}: {c} is {v!r}, not a count")
        out.append(int(x))
    if games == 0 and any(out):
        raise CategoryError(f"Yahoo's {d} line for {who}: categories {out} on a day he did not play")
    return out


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
    # compact (Nick, 11-14, 4a2 decision 4): no indent, so each day's 11 counts
    # are one short line's worth, not eleven lines (~6.8 MB by April at indent=1).
    # 4a3 review (11-19): and no spaces after separators, about 20% smaller again
    # (~3.9 MB by April with the minutes otherwise).
    atomic_write_json(cache_path(base_path), blob, indent=None, separators=(",", ":"))


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
    return {pid: v[GP_STAT] for pid, v in parse_game_stats(raw).items()}


def parse_game_stats(raw: dict) -> Dict[int, dict]:
    """{yahoo id: {GP_STAT: raw or None, MIN_STAT: raw or None}} from a
    game-scoped players/stats response (4a3: stat 2, minutes, rides in the
    same response). Raises on a shape it does not recognise."""
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
        got = {GP_STAT: None, MIN_STAT: None}
        stats = ((parts[1] or {}).get("player_stats") or {}).get("stats") or []
        for s in stats:
            st = s.get("stat") or {}
            if str(st.get("stat_id")) in got:
                got[str(st.get("stat_id"))] = st.get("value")
        out[pid] = got
    return out


def games_value(raw_value, who: str, d: date) -> int:
    if raw_value in ("1", 1):
        return 1
    if raw_value in ("0", 0, "-"):
        return 0
    raise ActualsError(f"Yahoo's {d} games-played stat for {who} is {raw_value!r}, not 0, 1 or '-'")


_MIN_RE = None


def parse_minutes(raw, who: str, d, games: int) -> int:
    """Whole minutes from Yahoo's stat 2 (4a3): "30", "30:12" (seconds
    rounded half up: "30:30" is 31), or "-" / "" / absent on a day he did
    not play (0). RAISES MinutesError naming him and the day: games played 1
    with no minutes; minutes over 0 with games played 0; over MIN_MAX
    minutes; anything else. A cameo (games 1, "0" or "0:20") is a legal 0."""
    global _MIN_RE
    if _MIN_RE is None:
        import re
        _MIN_RE = re.compile(r"^(\d{1,3})(?::([0-5]\d))?$")
    if raw is None or raw in ("-", ""):
        if games == 0:
            return 0
        raise MinutesError(f"Yahoo's {d} line for {who}: games played 1 and no minutes ({raw!r})")
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise MinutesError(f"Yahoo's {d} line for {who}: minutes are {raw!r}, not \"30\", \"30:12\" or \"-\"")
    m = _MIN_RE.match(str(raw).strip())
    if m is None:
        raise MinutesError(f"Yahoo's {d} line for {who}: minutes are {raw!r}, not \"30\", \"30:12\" or \"-\"")
    whole, sec = int(m.group(1)), int(m.group(2) or 0)
    if whole * 60 + sec > MIN_MAX * 60:
        raise MinutesError(f"Yahoo's {d} line for {who}: {raw!r} minutes, over {MIN_MAX}: misread")
    if games == 0 and whole * 60 + sec > 0:
        raise MinutesError(f"Yahoo's {d} line for {who}: {raw!r} minutes and no game played")
    return whole + (1 if sec >= 30 else 0)


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
        return self.day_full(pids, d, names)[0]

    def _game_raw(self, chunk: List[int], d: date) -> dict:
        keys = ",".join(f"{self.game_key}.p.{p}" for p in chunk)
        raw = self.lg.yhandler.get(f"players;player_keys={keys}/stats;type=date;date={d.isoformat()}")
        self.calls += 1
        return raw

    def day_full(self, pids: List[int], d: date, names: Dict[int, str],
                 header: Optional[dict] = None) -> Tuple[Dict[int, list], Optional[dict]]:
        """day_all's first two results (4a2's contract, unchanged)."""
        out, cr, _mr = self.day_all(pids, d, names, header)
        return out, cr

    def day_all(self, pids: List[int], d: date, names: Dict[int, str],
                header: Optional[dict] = None) -> Tuple[Dict[int, list], Optional[dict], dict]:
        """(day()'s result, the categories): with a header, {"cats": {pid:
        counts}, "error": None}, or {"cats": None, "error": why} when any
        player's categories fail (parse_cats, check_cats) -- the points are
        returned either way: a category problem never costs a day's points.
        Without a header, None. The same two requests per batch as day().
        Third (4a3): the minutes, {"minutes": {pid: whole minutes}, "error":
        None}, or {"minutes": None, "error": why} when any player's minutes
        fail (parse_minutes) -- the points and categories are returned either
        way. Stat 2 of the game-scoped response that carries stat 0."""
        out = {}
        cats: Dict[int, List[int]] = {}
        held: Dict[int, str] = {}
        mins: Dict[int, int] = {}
        min_err: Optional[str] = None
        for i in range(0, len(pids), BATCH):
            chunk = pids[i:i + BATCH]
            try:
                rows = self.lg.player_stats(chunk, "date", date=d)
                self.calls += 1
                raw = self._game_raw(chunk, d)
            except ActualsError:
                raise
            except Exception as e:                     # network, auth, parse
                raise ActualsError(f"Yahoo request for {d} failed ({type(e).__name__}: {e}) "
                                   f"for {', '.join(names[p] for p in chunk)}") from e
            pts, rowof = {}, {}
            for r in rows:
                pid = int(r.get("player_id", 0))
                if pid in chunk:
                    if "total_points" not in r:
                        raise ActualsError(f"Yahoo's {d} line for {names[pid]} has no total_points")
                    v = _num(r["total_points"])
                    pts[pid] = 0.0 if v is None else v
                    rowof[pid] = r
            gst = parse_game_stats(raw)
            for pid in chunk:
                if pid not in pts:
                    raise ActualsError(f"Yahoo returned no {d} league line for {names[pid]}")
                if pid not in gst or gst[pid][GP_STAT] is None:
                    raise ActualsError(f"Yahoo returned no {d} games-played stat for {names[pid]}")
                g = games_value(gst[pid][GP_STAT], names[pid], d)
                if g == 0 and pts[pid] != 0:
                    raise ActualsError(f"Yahoo's {d} line for {names[pid]}: {pts[pid]} points "
                                       "and no game played")
                out[pid] = [round(pts[pid], 2), g]
                if header is not None:
                    # 5d1 s.2b: one player's bad line holds back only him (held), never the
                    # others' categories; held lines are retried within the re-check window
                    try:
                        c = parse_cats(rowof[pid], header, names[pid], d, g)
                        check_cats(c, header, out[pid][0], names[pid], d)
                        cats[pid] = c
                    except CategoryError as e:
                        held[pid] = str(e)
                if min_err is None:
                    try:
                        mins[pid] = parse_minutes(gst[pid][MIN_STAT], names[pid], d, g)
                    except MinutesError as e:
                        min_err = str(e)
        mr = {"minutes": None, "error": min_err} if min_err else {"minutes": mins, "error": None}
        if header is None:
            return out, None, mr
        return out, held_result(cats, held, out), mr

    def minutes_day(self, pids: List[int], d: date, names: Dict[int, str],
                    now_zero: Optional[set] = None) -> Dict[int, int]:
        """The minutes backfill's request (4a3): {pid: whole minutes} for
        players who PLAYED on day d (the cache says games 1), from the
        game-scoped line only (1 call per BATCH). Yahoo must still say games
        played 1, and the minutes must parse, or MinutesError naming him and
        the day; any missing player or failed request raises too.
        now_zero (5c): a set the caller passes to judge a "games played 0
        now" itself (a phantom game, backfill_minutes): such a pid is added
        to it and left out of the result instead of raising here."""
        out = {}
        for i in range(0, len(pids), BATCH):
            chunk = pids[i:i + BATCH]
            try:
                raw = self._game_raw(chunk, d)
            except Exception as e:                     # network, auth, parse
                raise ActualsError(f"Yahoo request for {d}'s minutes failed ({type(e).__name__}: {e}) "
                                   f"for {', '.join(names[p] for p in chunk)}") from e
            gst = parse_game_stats(raw)
            for pid in chunk:
                if pid not in gst or gst[pid][GP_STAT] is None:
                    raise ActualsError(f"Yahoo returned no {d} games-played stat for {names[pid]}")
                g = games_value(gst[pid][GP_STAT], names[pid], d)
                if g == 0 and now_zero is not None:
                    now_zero.add(pid)
                    continue
                if g != 1:
                    raise MinutesError(f"Yahoo's {d} line for {names[pid]} now says games played "
                                       f"{gst[pid][GP_STAT]!r}, but the cache has him playing: the day's minutes "
                                       "are not written")
                out[pid] = parse_minutes(gst[pid][MIN_STAT], names[pid], d, 1)
        return out

    def cats_day(self, pids: List[int], d: date, names: Dict[int, str],
                 header: dict, held: Optional[Dict[int, str]] = None) -> Dict[int, tuple]:
        """The backfill's request (4a2): {pid: (counts, Yahoo's total now)}
        for players who PLAYED on day d, from the league-scoped line only
        (1 call per BATCH). The counts must score Yahoo's total now
        (check_cats), or CategoryError: the scoring changed. Any missing
        player or failed request raises, naming the date and the player.
        held (5d1 s.2b): a dict the caller passes to hold back a player whose
        line does not add up (his reason is put in it and he is left out of
        the result) instead of raising for the whole request."""
        out = {}
        for i in range(0, len(pids), BATCH):
            chunk = pids[i:i + BATCH]
            try:
                rows = self.lg.player_stats(chunk, "date", date=d)
                self.calls += 1
            except Exception as e:                     # network, auth, parse
                raise ActualsError(f"Yahoo request for {d}'s categories failed ({type(e).__name__}: {e}) "
                                   f"for {', '.join(names[p] for p in chunk)}") from e
            byid = {int(r.get("player_id", 0)): r for r in rows}
            for pid in chunk:
                r = byid.get(pid)
                if r is None:
                    raise ActualsError(f"Yahoo returned no {d} league line for {names[pid]}")
                if "total_points" not in r or _num(r["total_points"]) is None:
                    raise ActualsError(f"Yahoo's {d} line for {names[pid]} has no total_points")
                total = round(_num(r["total_points"]), 2)
                try:
                    c = parse_cats(r, header, names[pid], d, 1)
                    check_cats(c, header, total, names[pid], d)
                except CategoryError as e:
                    if held is None:
                        raise
                    held[pid] = str(e)
                    continue
                out[pid] = (c, total)
        return out

    def recheck_day(self, pids: List[int], d: date, names: Dict[int, str], header: dict) -> Dict[int, dict]:
        """5d1 s.2: the re-check of a recent day cached as 0 points in 1 game.
        {pid: {"total", "games", "cats" (or None), "error" (or None),
        "minutes" (or None)}}: the league-scoped line (total and categories)
        and the game-scoped one (games played and minutes), 2 calls per
        BATCH. Never raises for one player's line; a failed request raises."""
        out: Dict[int, dict] = {}
        for i in range(0, len(pids), BATCH):
            chunk = pids[i:i + BATCH]
            try:
                rows = self.lg.player_stats(chunk, "date", date=d)
                self.calls += 1
                raw = self._game_raw(chunk, d)
            except Exception as e:                     # network, auth, parse
                raise ActualsError(f"Yahoo request for {d}'s re-check failed ({type(e).__name__}: {e}) "
                                   f"for {', '.join(names[p] for p in chunk)}") from e
            byid = {int(r.get("player_id", 0)): r for r in rows}
            gst = parse_game_stats(raw)
            for pid in chunk:
                r = byid.get(pid)
                if r is None or "total_points" not in r or pid not in gst or gst[pid][GP_STAT] is None:
                    raise ActualsError(f"Yahoo returned no {d} line for {names[pid]} (re-check)")
                total = round(_num(r["total_points"]) or 0.0, 2)
                g = games_value(gst[pid][GP_STAT], names[pid], d)
                e = {"total": total, "games": g, "cats": None, "error": None, "minutes": None}
                try:
                    c = parse_cats(r, header, names[pid], d, g)
                    check_cats(c, header, total, names[pid], d)
                    e["cats"] = c
                except CategoryError as ex:
                    e["error"] = str(ex)
                try:
                    e["minutes"] = parse_minutes(gst[pid][MIN_STAT], names[pid], d, g)
                except MinutesError:
                    pass
                out[pid] = e
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


def _fetch_day(source, pids, d, names, header):
    """(points by pid, the categories result or None, the minutes result or
    None): a source with day_all (YahooSource) and a header gives categories
    and minutes; one with day_full only, categories; any other source (the
    tests' fakes, a header-less call) gives points and games only."""
    if header is not None and hasattr(source, "day_all"):
        return source.day_all(pids, d, names, header)
    if header is not None and hasattr(source, "day_full"):
        return source.day_full(pids, d, names, header) + (None,)
    return source.day(pids, d, names), None, None


def held_result(cats: Dict[int, List[int]], held: Dict[int, str], asked) -> dict:
    """5d1 s.2b: a day's categories result. One player's line that doesn't add
    up holds back only him ("held"), and the rest are written. When EVERY
    player asked for (two or more) fails, it is the whole day's error, as
    before (the scoring may have changed): nothing is held or written."""
    if held and not cats and len(list(asked)) >= 2:
        return {"cats": None, "error": next(iter(held.values())), "held": {}}
    return {"cats": cats, "error": None, "held": dict(held)}


def _store_cats(blob: dict, d: date, cr: Optional[dict], errors: List[str],
                held_out: Optional[List[str]] = None) -> None:
    if cr is None:
        return
    if cr["error"]:
        errors.append(f"{d.isoformat()}: {cr['error']}")
        return
    iso = d.isoformat()
    for pid, c in cr["cats"].items():
        blob["players"][str(pid)].setdefault("cat_days", {})[iso] = c
    for pid, why in (cr.get("held") or {}).items():     # 5d1 s.2b: categories pending for him alone
        rec = blob["players"][str(pid)]
        rec.setdefault("cat_pending", {})[iso] = why
        line = f"{rec['name']} {iso}: categories pending: {why}"
        (held_out if held_out is not None else errors).append(line)


def _store_minutes(blob: dict, d: date, mr: Optional[dict], errors: List[str]) -> None:
    """4a3: the day's minutes for every player the pass asked for, or none
    (its error recorded; the backfill retries the day)."""
    if mr is None:
        return
    if mr["error"]:
        errors.append(f"{d.isoformat()}: {mr['error']}")
        return
    for pid, m in mr["minutes"].items():
        blob["players"][str(pid)].setdefault("min_days", {})[d.isoformat()] = m


def update(base_path=".", *, source=None, ids: Dict[str, int] = None, yahoo_names=None,
           today: date = None, first_day: date = None, season: str = None,
           echo: Callable = print, header: Optional[dict] = None) -> dict:
    """Fetch every finished league day the cache lacks for every rostered
    player, write each completed day, and report. RAISES (ActualsError) on the
    first failure, after keeping the days that completed. With a source that
    has day_full (YahooSource), each day keeps its categories too (4a2;
    header: config yahoo_settings.stat_values unless given); a category
    problem is returned in "cat_errors", never raised; a minutes problem
    (4a3) in "min_errors", never raised."""
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
    if hasattr(source, "day_full"):
        header = header or scoring_header(base)
        ensure_cats(blob, header)
    else:
        header = None
    cat_errors: List[str] = []
    cat_held: List[str] = []
    min_errors: List[str] = []
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
        got, cr, mr = _fetch_day(source, pids, d, names, header)
        for pid, v in got.items():
            blob["players"][str(pid)]["days"][d.isoformat()] = v
            per_player_days[names[pid]] = per_player_days.get(names[pid], 0) + 1
        _store_cats(blob, d, cr, cat_errors, cat_held)
        _store_minutes(blob, d, mr, min_errors)
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
            "players": len(ids), "ids": names_now, "source": source, "header": header,
            "cat_errors": cat_errors, "cat_held": cat_held, "min_errors": min_errors}


# =============================================================================
# the other players the hub names (40b, 11-13)
# =============================================================================

def calls_for(todo: Dict[date, List[int]]) -> int:
    """Yahoo calls a plan costs: two requests (league- and game-scoped) per
    batch of BATCH players per day -- YahooSource.day's own loop (and
    yahoo_fantasy_api's player_stats chunks at 25 too)."""
    return sum(2 * math.ceil(len(pids) / BATCH) for pids in todo.values())


def _actuals_int(base_path, key: str) -> int:
    cfg = json.loads((Path(base_path) / "config" / "league_config.json").read_text(encoding="utf-8"))
    v = (cfg.get("actuals") or {}).get(key)
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        raise ActualsError(f"config/league_config.json actuals.{key} is {v!r}: "
                           "a whole number of at least 1 is required")
    return v


def extras_cap(base_path=".") -> int:
    """config actuals.extra_players_max: required, an int of at least 1."""
    return _actuals_int(base_path, "extra_players_max")


def backfill_cap(base_path=".") -> int:
    """config actuals.category_backfill_calls_max (4a2): required, an int of at least 1."""
    return _actuals_int(base_path, "category_backfill_calls_max")


def recheck_days(base_path=".") -> int:
    """config actuals.recheck_days (5d1 s.2): required, an int of at least 1:
    how many of the last finished days the nightly re-checks for a late-filled
    line, and how long a held line (categories pending) is retried."""
    return _actuals_int(base_path, "recheck_days")


def minutes_cap(base_path=".") -> int:
    """config actuals.minutes_backfill_calls_max (4a3): required, an int of at least 1."""
    return _actuals_int(base_path, "minutes_backfill_calls_max")


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
                  extras: dict = None, dry_run: bool = False, header: Optional[dict] = None) -> dict:
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
    if not dry_run and hasattr(source, "day_full"):
        header = header or scoring_header(base)
        ensure_cats(blob, header)
    else:
        header = None
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
           "seconds": 0.0, "cat_errors": [], "cat_held": [], "min_errors": []}
    if dry_run:
        return out
    t0 = time.time()
    calls0 = getattr(source, "calls", 0)
    names_now = {n: int(p) for n, p in sorted(ids.items())}
    from .league_clock import league_now
    for d, pids in todo.items():
        got, cr, mr = _fetch_day(source, pids, d, names, header)
        for pid, v in got.items():
            blob["players"][str(pid)]["days"][d.isoformat()] = v
        _store_cats(blob, d, cr, out["cat_errors"], out["cat_held"])
        _store_minutes(blob, d, mr, out["min_errors"])
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
# the categories' backfill (4a2, 11-14)
# =============================================================================

def tracked_ids(blob: dict) -> Dict[int, str]:
    """{id: name} of the players the last passes fetched: roster_names and
    extra_names. A player the hub no longer names keeps his days but is not
    backfilled (nothing shows him)."""
    ids = {int(p) for p in blob["roster_names"].values()} | {int(p) for p in (blob.get("extra_names") or {}).values()}
    return {pid: blob["players"][str(pid)]["name"] for pid in sorted(ids)}


def backfill_plan(blob: dict, last: date, key: str = "cat_days") -> Dict[date, dict]:
    """{day: {"played": [ids], "idle": [ids]}}, oldest first: every cached
    day through `last` of a tracked player with no categories (key
    "cat_days"), or no minutes (4a3: key "min_days"). "idle" played no game
    (zeros, no call)."""
    out: Dict[date, dict] = {}
    for pid in tracked_ids(blob):
        rec = blob["players"][str(pid)]
        have = dict(rec.get(key) or {})
        if key == "cat_days":
            have.update(rec.get("cat_missing") or {})     # 5d1 s.2b: given up, never asked again
        for d, v in rec["days"].items():
            if d in have or date.fromisoformat(d) > last:
                continue
            slot = out.setdefault(date.fromisoformat(d), {"played": [], "idle": []})
            slot["played" if v[1] == 1 else "idle"].append(pid)
    return dict(sorted(out.items()))


def backfill_calls(plan_: Dict[date, dict]) -> int:
    """1 league-scoped call per BATCH players who played, per day."""
    return sum(math.ceil(len(p["played"]) / BATCH) for p in plan_.values())


def backfill_categories(base_path=".", *, source=None, today: date = None, cap: int = None,
                        header: dict = None, dry_run: bool = False) -> dict:
    """Fill categories for days cached without them, oldest first, at most
    `cap` calls (config actuals.category_backfill_calls_max). A day is written
    only when every player asked for on it came back (all or nothing); a
    complete day is never asked for again. Stops at the first day that does
    not fit in what is left of the cap. RAISES (ActualsError) on a failure,
    after keeping the days that completed; a day needing more calls than the
    whole cap raises too (it would never finish). dry_run: the plan, no
    Yahoo call, nothing written."""
    base = Path(base_path)
    from .league_clock import league_today, league_now
    today = today or league_today()
    last = today - timedelta(days=1)
    blob = load(base)
    header = header or scoring_header(base)
    ensure_cats(blob, header)
    cap = cap if cap is not None else backfill_cap(base)
    names = tracked_ids(blob)
    todo = backfill_plan(blob, last)
    out = {"days_missing": len(todo), "calls_needed": backfill_calls(todo), "cap": cap,
           "days_done": [], "calls": 0, "corrections": [], "late_filled": [], "held": [], "given_up": [],
           "failed_days": [], "stopped": None, "seconds": 0.0}
    if dry_run:
        out["days_left"] = len(todo)
        return out
    t0 = time.time()
    window_first = None                          # read when a line is held (config actuals.recheck_days)
    takes_held = "held" in inspect.signature(source.cats_day).parameters if todo else False
    for d, want in todo.items():
        need = math.ceil(len(want["played"]) / BATCH)
        if need > cap:
            raise ActualsError(f"{d}'s categories need {need} calls ({len(want['played'])} players played), "
                               f"more than actuals.category_backfill_calls_max ({cap}): that day would never "
                               "be written; raise the cap")
        if out["calls"] + need > cap:
            out["stopped"] = f"the cap ({cap} calls) before {d.isoformat()}"
            break
        calls0 = getattr(source, "calls", 0)
        held: Dict[int, str] = {}
        if not want["played"]:
            got = {}
        elif takes_held:
            got = source.cats_day(want["played"], d, names, header, held=held)
        else:
            got = source.cats_day(want["played"], d, names, header)
        out["calls"] += getattr(source, "calls", 0) - calls0
        iso = d.isoformat()
        if held and not got and len(want["played"]) >= 2:
            # every player asked for failed: the whole day's error, as before (the scoring may
            # have changed). Recorded; the backfill goes on to the next day and retries this one
            out["failed_days"].append(f"{iso}: {next(iter(held.values()))}")
            continue
        for pid in want["played"]:
            if pid not in got and pid not in held:
                raise ActualsError(f"Yahoo returned no {d} categories for {names[pid]}")
        for pid, (c, total) in got.items():
            rec = blob["players"][str(pid)]
            stored = rec["days"][iso][0]
            pending = iso in (rec.get("cat_pending") or {})
            corrected = None
            if abs(float(total) - float(stored)) > CAT_TOL:
                if is_incomplete(rec, iso) or pending:
                    # 5d1 s.2: a line Yahoo filled in late (cached 0 points in 1 game), or one cached
                    # from a line that didn't add up: Yahoo's total and categories replace it
                    out["late_filled"].append(fill_late_line(rec, iso, c, total, header, names[pid]))
                    continue
                corrected = total                       # an NBA stat correction since the night it came
            check_cats(c, header, stored, names[pid], iso, corrected=corrected)
            rec.setdefault("cat_days", {})[iso] = c
            (rec.get("cat_pending") or {}).pop(iso, None)
            if not rec.get("cat_pending"):
                rec.pop("cat_pending", None)
            if corrected is not None:
                rec.setdefault("cat_corrections", {})[iso] = corrected
                out["corrections"].append(f"{names[pid]} {iso}: {stored} cached, {corrected} now")
        for pid, why in sorted(held.items()):
            rec = blob["players"][str(pid)]
            if window_first is None:
                window_first = today - timedelta(days=recheck_days(base))
            if d >= window_first:                   # inside the re-check window: pending, retried
                rec.setdefault("cat_pending", {})[iso] = why
                out["held"].append(f"{names[pid]} {iso}: categories pending: {why}")
            else:                                   # past it: left empty, recorded once, never asked again
                rec.setdefault("cat_missing", {})[iso] = f"Yahoo's line never added up: {why}"
                (rec.get("cat_pending") or {}).pop(iso, None)
                if not rec.get("cat_pending"):
                    rec.pop("cat_pending", None)
                out["given_up"].append(f"{names[pid]} {iso}: Yahoo's line never added up: {why}")
        for pid in want["idle"]:
            blob["players"][str(pid)].setdefault("cat_days", {})[iso] = [0] * len(header["order"])
        blob["updated_at"] = league_now().isoformat(timespec="seconds")
        write(base, blob, today)
        out["days_done"].append(iso)
    out["days_left"] = len(backfill_plan(blob, last)) if out["days_done"] else len(todo)
    out["seconds"] = round(time.time() - t0, 1)
    return out


# =============================================================================
# late-filled lines (5d1 s.2, Nick 11-20: Zion Williamson 2026-11-14)
# =============================================================================

def is_incomplete(rec: dict, iso: str) -> bool:
    """5d1 s.2: a day cached as exactly 0 points in 1 game. When Yahoo's line
    for it later scores a non-zero total, it was an incomplete line (Yahoo
    filled the stats in late), not a stat correction."""
    v = (rec.get("days") or {}).get(iso)
    return v is not None and int(v[1]) == 1 and float(v[0]) == 0.0


def fill_late_line(rec: dict, iso: str, cats: List[int], total: float, header: dict, who: str) -> str:
    """Rewrite one day with Yahoo's total and its categories (they must score
    it: check_cats), record it in the day's "late_filled", and return the run
    row's line. Only for an incomplete day (is_incomplete) or a held one
    (cat_pending): anything else RAISES -- a real stat correction is never
    rewritten."""
    if not (is_incomplete(rec, iso) or iso in (rec.get("cat_pending") or {})):
        raise ActualsError(f"{who} {iso} is neither an incomplete line nor a held one: it is not rewritten")
    if abs(float(total)) <= CAT_TOL:
        raise ActualsError(f"{who} {iso}: Yahoo's total is still 0: nothing to fill")
    check_cats(cats, header, total, who, iso)
    was = rec["days"][iso][0]
    rec["days"][iso] = [round(float(total), 2), 1]
    rec.setdefault("cat_days", {})[iso] = list(cats)
    for k in ("cat_corrections", "cat_pending"):
        (rec.get(k) or {}).pop(iso, None)
        if k in rec and not rec[k]:
            rec.pop(k)
    rec.setdefault("late_filled", {})[iso] = {"was": was, "now": round(float(total), 2)}
    return f"{who} {iso}: {was} cached, {round(float(total), 2)} now (Yahoo's line filled in late)"


def settle_recorded_late_lines(blob: dict, header: dict) -> List[str]:
    """5d1 s.2, no call: a day cached as 0 points in 1 game whose categories
    are cached and score a non-zero total kept as a "stat correction" (the
    rule before 5d1: Zion Williamson 2026-11-14, 0.0 cached, 32.8 now) is an
    incomplete line: rewritten with that total. Returns the run row's lines."""
    out = []
    for rec in blob["players"].values():
        for iso, corr in sorted((rec.get("cat_corrections") or {}).items()):
            c = (rec.get("cat_days") or {}).get(iso)
            if c is None or not is_incomplete(rec, iso) or abs(float(corr)) <= CAT_TOL:
                continue
            out.append(fill_late_line(rec, iso, c, corr, header, rec["name"]))
    return out


def recheck_recent(base_path=".", *, source=None, today: date = None, header: dict = None,
                   days: int = None, dry_run: bool = False) -> dict:
    """5d1 s.2 (the nightly only): settle_recorded_late_lines, then re-check
    the last `days` finished days (config actuals.recheck_days) for every
    tracked player cached as 0 points in 1 game (is_incomplete):
      - Yahoo's line now scores a non-zero total that its categories add up
        to: the day is rewritten with it (fill_late_line), LATE STAT LINE
        FILLED;
      - Yahoo now says games played 0 and the day is a phantom (is_phantom):
        5c's rule, the day becomes no game, PHANTOM GAME CORRECTED;
      - anything else (still 0 points; a line that doesn't add up): left as
        it is.
    A day that is not 0 points in 1 game is never asked for, so a complete
    day is never touched. 2 calls per 25 such players a day (the source's
    recheck_day); none when there are none. RAISES (ActualsError) on a failed
    request, after keeping what it settled."""
    base = Path(base_path)
    from .league_clock import league_today, league_now
    today = today or league_today()
    blob = load(base)
    header = header or scoring_header(base)
    ensure_cats(blob, header)
    n = days if days is not None else recheck_days(base)
    out = {"days": n, "settled": settle_recorded_late_lines(blob, header), "late_filled": [], "phantoms": [],
           "asked": 0, "calls": 0, "seconds": 0.0}
    names = tracked_ids(blob)
    todo: Dict[date, List[int]] = {}
    for d in days_between(today - timedelta(days=n), today - timedelta(days=1)):
        iso = d.isoformat()
        for pid in names:
            rec = blob["players"][str(pid)]
            if is_incomplete(rec, iso):
                todo.setdefault(d, []).append(pid)
    out["asked"] = sum(len(v) for v in todo.values())
    if dry_run:
        return out
    t0 = time.time()
    changed = bool(out["settled"])
    n_cats = len(header["order"])
    if todo and not hasattr(source, "recheck_day"):
        out["skipped"] = "the source has no re-check"
        todo = {}
    for d, pids in todo.items():
        calls0 = getattr(source, "calls", 0)
        got = source.recheck_day(pids, d, names, header)
        out["calls"] += getattr(source, "calls", 0) - calls0
        iso = d.isoformat()
        for pid in pids:
            e = got.get(pid)
            rec = blob["players"][str(pid)]
            if e is None:
                raise ActualsError(f"Yahoo returned no {d} line for {names[pid]} (re-check)")
            if e["games"] == 0:
                if is_phantom(rec, iso):
                    correct_phantom(rec, iso, n_cats)
                    out["phantoms"].append(f"{names[pid]} {iso}: a phantom game (games played 1 with no stats "
                                           "when fetched; Yahoo now says 0): rewritten as no game")
                    changed = True
                continue
            if e["cats"] is not None and abs(float(e["total"])) > CAT_TOL:
                out["late_filled"].append(fill_late_line(rec, iso, e["cats"], e["total"], header, names[pid]))
                if e["minutes"] is not None:
                    rec.setdefault("min_days", {})[iso] = e["minutes"]
                changed = True
    if changed:
        blob["updated_at"] = league_now().isoformat(timespec="seconds")
        write(base, blob, today)
    out["seconds"] = round(time.time() - t0, 1)
    return out


# =============================================================================
# the minutes' backfill (4a3, 11-19)
# =============================================================================

def is_phantom(rec: dict, iso: str) -> bool:
    """5c: the day is cached as a phantom game -- 0 points, 1 game, and its
    categories cached with every one 0. Nothing else is (a day with no
    categories cached yet is not: nothing says the stats were empty)."""
    v = (rec.get("days") or {}).get(iso)
    c = (rec.get("cat_days") or {}).get(iso)
    return (v is not None and int(v[1]) == 1 and float(v[0]) == 0.0
            and c is not None and len(c) > 0 and all(int(x) == 0 for x in c)
            and iso not in (rec.get("cat_corrections") or {}))


def correct_phantom(rec: dict, iso: str, n_cats: int) -> None:
    """5c: rewrite a phantom day (is_phantom) as a day he did not play, the
    cache's shape for one: [0.0, 0], eleven zeros, 0 minutes."""
    if not is_phantom(rec, iso):
        raise ActualsError(f"{rec.get('name')} {iso} is not a phantom game: it is not rewritten")
    rec["days"][iso] = [0.0, 0]
    rec.setdefault("cat_days", {})[iso] = [0] * n_cats
    rec.setdefault("min_days", {})[iso] = 0

def backfill_minutes(base_path=".", *, source=None, today: date = None, cap: int = None,
                     dry_run: bool = False) -> dict:
    """Fill minutes for days cached without them, oldest first, at most `cap`
    calls (config actuals.minutes_backfill_calls_max). backfill_categories'
    rules: a day is written only when every player asked for on it came back
    (all or nothing); a complete day is never asked for again; it stops at
    the first day that does not fit in what is left of the cap; a day
    needing more calls than the whole cap raises. Only the game-scoped
    request, for the players who played (source.minutes_day); the others
    get 0 with no call. RAISES (ActualsError) on a failure, after keeping the
    days that completed. dry_run: the plan, no Yahoo call, nothing written."""
    base = Path(base_path)
    from .league_clock import league_today, league_now
    today = today or league_today()
    last = today - timedelta(days=1)
    blob = load(base)
    cap = cap if cap is not None else minutes_cap(base)
    names = tracked_ids(blob)
    todo = backfill_plan(blob, last, key="min_days")
    out = {"days_missing": len(todo), "calls_needed": backfill_calls(todo), "cap": cap,
           "days_done": [], "calls": 0, "corrections": [], "stopped": None, "seconds": 0.0}
    if dry_run:
        out["days_left"] = len(todo)
        return out
    t0 = time.time()
    n_cats = len(((blob.get("cats") or {}).get("order")) or [])
    for d, want in todo.items():
        need = math.ceil(len(want["played"]) / BATCH)
        if need > cap:
            raise ActualsError(f"{d}'s minutes need {need} calls ({len(want['played'])} players played), "
                               f"more than actuals.minutes_backfill_calls_max ({cap}): that day would never "
                               "be written; raise the cap")
        if out["calls"] + need > cap:
            out["stopped"] = f"the cap ({cap} calls) before {d.isoformat()}"
            break
        calls0 = getattr(source, "calls", 0)
        zero: set = set()
        got = source.minutes_day(want["played"], d, names, now_zero=zero) if want["played"] else {}
        out["calls"] += getattr(source, "calls", 0) - calls0
        iso = d.isoformat()
        # 5c: games played 0 now. A phantom game (is_phantom) is Yahoo's
        # correction; anything else is the disagreement it always was
        for pid in sorted(zero):
            rec = blob["players"][str(pid)]
            if not n_cats or not is_phantom(rec, iso):
                v = rec["days"][iso]
                raise MinutesError(f"Yahoo's {d} line for {names[pid]} now says games played '0', but the "
                                   f"cache has him playing ({v[0]} points, categories "
                                   f"{(rec.get('cat_days') or {}).get(iso)}): the day's minutes are not written")
        for pid in want["played"]:
            if pid not in got and pid not in zero:
                raise ActualsError(f"Yahoo returned no {d} minutes for {names[pid]}")
        for pid in sorted(zero):
            correct_phantom(blob["players"][str(pid)], iso, n_cats)
            out["corrections"].append(f"{names[pid]} {iso}: a phantom game (games played 1 with no stats when "
                                      "fetched; Yahoo now says 0): rewritten as no game")
        for pid, m in got.items():
            blob["players"][str(pid)].setdefault("min_days", {})[iso] = m
        for pid in want["idle"]:
            blob["players"][str(pid)].setdefault("min_days", {})[iso] = 0
        blob["updated_at"] = league_now().isoformat(timespec="seconds")
        write(base, blob, today)
        out["days_done"].append(iso)
    out["days_left"] = len(todo) - len(out["days_done"])
    out["seconds"] = round(time.time() - t0, 1)
    return out


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


def find_record(blob: dict, name: str) -> Optional[dict]:
    """His cache record by any spelling (PlayerIndex rules): the last fetch's
    roster names first, then the last extras pass's (40b), then every name
    the cache has held. None: never in the cache."""
    from .data_loader import PlayerIndex
    pid = PlayerIndex(blob["roster_names"]).get(name)
    if pid is None and blob.get("extra_names"):
        pid = PlayerIndex(dict(blob["extra_names"])).get(name)
    if pid is None:
        pid = PlayerIndex({rec["name"]: p for p, rec in blob["players"].items()}).get(name)
    if pid is None:
        return None
    return blob["players"][str(pid)]


def find_days(blob: dict, name: str) -> Optional[dict]:
    """His cached days by any spelling (find_record): a player dropped since
    keeps his days up to the drop. None: never in the cache."""
    rec = find_record(blob, name)
    return None if rec is None else rec["days"]


def category_season(blob: dict, name: str, first: date, through: date) -> dict:
    """His category totals over the games he played in [first, through]
    (4a2; ratings reads it). {"status", "games", "totals": {category: count}
    or None, "day": the first day lacking, or None}:
      "ok"          every day he played has categories
      "loading"     the file has no categories (version 1), or a day he
                    played lacks them (the backfill has not reached it)
      "not_cached"  never in the cache
      "gap"         a day in the window is not cached at all
    5d1 s.2b: a day whose categories are held back (cat_pending) or given
    up (cat_missing) is left out of games and totals, and listed in
    "skipped". Plain data; never raises for a player."""
    header = blob.get("cats")
    rec = find_record(blob, name)
    res = {"status": "ok", "games": 0, "totals": None, "day": None}
    if header is None:
        return dict(res, status="loading")
    if rec is None:
        return dict(res, status="not_cached")
    cd = rec.get("cat_days") or {}
    held = set(rec.get("cat_pending") or {}) | set(rec.get("cat_missing") or {})   # 5d1 s.2b
    totals = [0] * len(header["order"])
    games = 0
    skipped = []
    for d in days_between(first, through) if through >= first else []:
        iso = d.isoformat()
        v = rec["days"].get(iso)
        if v is None:
            return dict(res, status="gap", day=iso)
        if v[1] != 1:
            continue
        c = cd.get(iso)
        if c is None and iso in held:
            skipped.append(iso)                 # Yahoo's line didn't add up: the game is left out
            continue
        if c is None:
            return dict(res, status="loading", day=iso)
        games += 1
        totals = [a + b for a, b in zip(totals, c)]
    return dict(res, games=games, totals=dict(zip(header["order"], totals)), skipped=skipped)


def minutes_games(blob: dict, name: str, first: date, through: date) -> dict:
    """His minutes in each game he played in [first, through] (4a3; the new
    hub's MIN, MIN delta and the card's last 5 read it). {"status", "games":
    [(iso, minutes)] in order, "day": the first day lacking, or None}:
      "ok"          every day he played has minutes
      "loading"     a day he played lacks them (the backfill has not
                    reached it); "games" holds none
      "not_cached"  never in the cache
      "gap"         a day in the window is not cached at all
    Plain data; never raises for a player."""
    rec = find_record(blob, name)
    res = {"status": "ok", "games": [], "day": None}
    if rec is None:
        return dict(res, status="not_cached")
    md = rec.get("min_days") or {}
    games = []
    for d in days_between(first, through) if through >= first else []:
        iso = d.isoformat()
        v = rec["days"].get(iso)
        if v is None:
            return dict(res, status="gap", day=iso)
        if v[1] != 1:
            continue
        m = md.get(iso)
        if m is None:
            return dict(res, status="loading", day=iso)
        games.append((iso, m))
    return dict(res, games=games)


def minutes_on(blob: dict, name: str, isos: Iterable[str]) -> Dict[str, int]:
    """{iso: minutes} of the given days that have minutes stored (4a3: the
    card's last 5 games, which show a game's minutes as soon as that day has
    them, before the backfill reaches his older days)."""
    rec = find_record(blob, name)
    md = (rec or {}).get("min_days") or {}
    return {i: md[i] for i in isos if i in md}


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
