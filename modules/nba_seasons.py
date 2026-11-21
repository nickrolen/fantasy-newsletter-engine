"""
nba_seasons.py -- every player's NBA seasons, in this league's eleven stats
(4a4 Phase A, 11-20; claude/HANDOFF_4A4_NBA_HISTORY_OVR_ARCHETYPES_2026-11-20.md).

WHY IT EXISTS
    OVR and POT's history was the league log (HISTORICAL_PLAYERLOG.json): only
    the days a player sat on a league roster, so a veteran nobody here rostered
    had none and a short stint stood in for a career. This file holds every
    player's whole NBA seasons, rostered or not, so Phase B can build the prior
    from his body of work (Nick, 11-20).

THE FILE (data/historical/NBA_SEASONS.json; public NBA stats, NOT state:
committed to the engine so the cloud runner has it)
    {"version", "about", "stats": [the league's eleven, config order],
     "provenance": {season: {"source", "game_key", "status", "next_start",
                             "pool", "fetched_at", "reason", "rejected",
                             "no_stats" (players Yahoo listed with no stats
                             at all for the season: counted, not stored)}},
     "players": {yahoo player id: {"name", "seasons": {season: {"gp",
                 "stats": {stat: season total}}}}}}
      - status: "complete" (every page of the season's pool came back),
        "partial" (a run stopped; next_start is where the next run resumes),
        "unavailable" (Yahoo could not serve it: reason says why; the next
        run tries again). Readers refuse anything but "complete" (load()).
      - gp: Yahoo stat 0, games played. A season with gp 0 is kept for a
        player who played in another season of the file (a year lost to
        injury is real for availability); a player with gp 0 in every
        season is dropped once every season is complete. A gp-0 season is
        Yahoo's word that he was in that season's player pool and played
        no game: it does not say whether he was injured or unsigned.
      - NO TEAM (version 2, Nick 11-20): Yahoo's editorial_team_abbr is the
        player's team TODAY in every season's game (the first fetch had
        LeBron at PHI in 2014-15), so it is not stored. Phase B's
        availability uses league-wide team-game counts, not a team field.
        A version-1 file is migrated on read (its "team" dropped).
      - A SEASON WITH NO GAMES IS NOT A SEASON (11-20): the first fetch got
        every player of 2014-15 to 2021-22 with every stat "-", and stored
        them as 0 games, "complete". Now a season's pool in which fewer than
        MIN_PLAYED players have a game is "unavailable", its entries are not
        kept, and the summary says why; a file holding such a season as
        "complete" is corrected on read (the season becomes unavailable and
        its entries go, so the next run fetches it again).
      - name: from his most recent season in the file.
      - Deterministic: players by numeric id, seasons ascending, stats in
        config order; one player per line (a yearly diff reads cleanly).
      - One writer (scripts/fetch_nba_seasons.py); every write atomic.

THE SOURCE (Yahoo, the engine's own client; Nick runs the fetch at his desk)
    - Game keys: config yahoo.historical_league_keys gives 2017-18 on (the
      league key's prefix). Older seasons are looked up in the same run with
      one call, games;game_codes=nba;seasons=..., which also returns the
      seasons config covers: those must agree with config, or the run RAISES
      before any page is fetched (the lookup is read wrong).
    - Per season, the WHOLE player pool of that season's game, 25 a call:
      game/{key}/players;start={s};count=25/stats;type=season;season={year}.
    - OLD SEASONS (11-20, Nick's --debug-raw): for 2014-15 to 2021-22 every
      request through the season's own game lists the pool but sends every
      stat as "-"; the same players asked for BY KEY THROUGH TODAY'S GAME
      (players;player_keys={today}.p.{id},.../stats;type=season;season={year})
      send the real season. So a season whose own game lists the pool with
      fewer than MIN_PLAYED players who played is fetched again that way
      (provenance "method"), from the ids the listing gave: 25 keys a call;
      a refused batch is retried once, then split into fives, then singles,
      and an id today's game will not serve (a retired player) is named in
      "unserved", never guessed. After ten single refusals in a row the run
      asks for LeBron James: served, the refusals are real and it goes on;
      refused, it stops (Yahoo or the connection, not ten players). Resumable in both
      phases ("phase", "next_start", "key_next", "listing" while running).
    - CROSS-CHECK (11-20): for every season the league played (config
      historical_league_keys), the league-scoped request gives Yahoo's own
      fantasy points for the season's top 3 (by this file's numbers at
      today's scoring); provenance "cross_check" keeps both. A difference
      means the stats are wrong OR the league scored that season
      differently: the summary says CROSS-CHECK DIFFERS and the run exits 1.
      Not a top-N by fantasy points: it covers the top N, every player ever
      on a league roster and today's Players tab at once, needs no sort order
      to be trusted, and avoids per-id batches (one id unknown to a past
      season's game fails the whole batch). It costs ~25-45 calls a season.
    - Each response must state coverage "season" for the season asked, or the
      run RAISES. The stats come by Yahoo stat id (GP 0, FGA 3, FGM 4, FTA 6,
      FTM 7, 3PTM 10, PTS 12, REB 15, AST 16, ST 17, BLK 18, TO 19), or the
      composites 9004003 "FGM/FGA" and 9007006 "FTM/FTA"; a stat in neither
      form RAISES, naming the ids the response did carry.
    - A player-season that fails a box-score identity (PTS = 2 FGM + 3PTM +
      FTM; FGM <= FGA; FTM <= FTA; 3PTM <= FGM; counts on gp 0) is not
      stored: it is listed under its season's "rejected", by name.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

RELPATH = Path("data") / "historical" / "NBA_SEASONS.json"
VERSION = 2                  # 2 (11-20): no "team"; 1 is migrated on read
READS = (1, 2)
PAGE = 25
GP_ID = "0"
YAHOO_IDS = {"FGM": "4", "FGA": "3", "FTM": "7", "FTA": "6", "3PTM": "10", "PTS": "12",
             "REB": "15", "AST": "16", "ST": "17", "BLK": "18", "TO": "19"}
COMPOSITES = {"9004003": ("FGM", "FGA"), "9007006": ("FTM", "FTA")}
MIN_PLAYED = 300             # a season's pool with fewer players who played a game is not served
                             # (every NBA season since 2014-15 had about 490+; Yahoo's 2022-23 to
                             # 2025-26 pools measured 537-582, 11-20)
SEASON_METHOD = "the season's own game"
TODAY_METHOD = "today's game, by player key (the season's own game sent no stats)"
KEY_CHUNK = 5               # a refused batch of 25 is split into fives, then singles
OUTAGE = 10                 # single refusals in a row that stop the run
CROSS_N = 3                 # players per season cross-checked against the league's own points
GP_MAX = 90                  # a season's games over this: misread (82, plus a traded player's few)
FIRST_SEASON = "2014-15"     # the back-test's earliest season (2017-18) has three seasons before it
LAST_SEASON = "2025-26"
RETRY_WAIT = 2.0
ABOUT = ("Every player's NBA seasons from Yahoo: games played and the league's eleven scoring stats "
         "(season totals). Public NBA stats, not league state. Written by scripts/fetch_nba_seasons.py.")


class SeasonsError(RuntimeError):
    """The file, the config or a Yahoo response is not what it must be. Never defaulted."""


class ShapeError(SeasonsError):
    """A Yahoo response has a shape this code does not read."""


# =============================================================================
# seasons, config
# =============================================================================

def season_year(label: str) -> int:
    m = re.fullmatch(r"(\d{4})-(\d{2})", label or "")
    if not m or (int(m.group(1)) + 1) % 100 != int(m.group(2)):
        raise SeasonsError(f"{label!r} is not a season like 2017-18")
    return int(m.group(1))


def season_label(year: int) -> str:
    return f"{year}-{(year + 1) % 100:02d}"


def seasons_between(first: str, last: str) -> List[str]:
    a, b = season_year(first), season_year(last)
    if a > b:
        raise SeasonsError(f"--first {first} is after --last {last}")
    return [season_label(y) for y in range(a, b + 1)]


def _config(base) -> dict:
    p = Path(base) / "config" / "league_config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SeasonsError(f"{p} is unreadable ({type(e).__name__})") from e


def stat_order(base) -> List[str]:
    """The league's scoring stats in config yahoo_settings.stat_values order. Required."""
    sv = (_config(base).get("yahoo_settings") or {}).get("stat_values")
    if not isinstance(sv, dict) or not sv:
        raise SeasonsError("config/league_config.json yahoo_settings.stat_values is missing: "
                           "the stats to keep come from it")
    unknown = [k for k in sv if k not in YAHOO_IDS]
    if unknown:
        raise SeasonsError(f"config yahoo_settings.stat_values has {unknown}, which this fetch has no "
                           f"Yahoo stat id for (it knows {sorted(YAHOO_IDS)})")
    return list(sv)


def stat_values(base) -> Dict[str, float]:
    sv = (_config(base).get("yahoo_settings") or {}).get("stat_values")
    return {k: float(v) for k, v in sv.items()}


def config_game_keys(base) -> Dict[str, str]:
    """{season: game key} from config yahoo.historical_league_keys (the
    league key's prefix). Required."""
    hk = (_config(base).get("yahoo") or {}).get("historical_league_keys")
    if not isinstance(hk, dict) or not hk:
        raise SeasonsError("config/league_config.json yahoo.historical_league_keys is missing")
    out = {}
    for s, k in hk.items():
        season_year(s)
        if not isinstance(k, str) or not re.fullmatch(r"\d+\.l\.\d+", k):
            raise SeasonsError(f"config yahoo.historical_league_keys[{s}] is {k!r}, not a league key")
        out[s] = k.split(".")[0]
    return out


# =============================================================================
# the file
# =============================================================================

def path(base=".") -> Path:
    return Path(base) / RELPATH


def empty(stats: List[str]) -> dict:
    return {"version": VERSION, "about": ABOUT, "stats": list(stats), "provenance": {}, "players": {}}


def read(base=".", *, stats: List[str]) -> dict:
    """The file as it stands (partial or not) for the fetch to continue, or
    a new one. A file of another version or other stats RAISES."""
    p = path(base)
    if not p.is_file():
        return empty(stats)
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SeasonsError(f"{RELPATH} is unreadable ({type(e).__name__}): move it aside and fetch again") from e
    if blob.get("version") not in READS:
        raise SeasonsError(f"{RELPATH} is version {blob.get('version')!r}; this code reads {READS}")
    if blob.get("stats") != list(stats):
        raise SeasonsError(f"{RELPATH} stores stats {blob.get('stats')}, but config yahoo_settings.stat_values "
                           f"is now {list(stats)}: refetch with --refetch for every season")
    for k in ("provenance", "players"):
        if not isinstance(blob.get(k), dict):
            raise SeasonsError(f"{RELPATH} has no {k}")
    migrate(blob)
    audit(blob)
    return blob


def migrate(blob: dict) -> dict:
    """Version 1 -> 2: drop each season's "team" (it was the player's team
    today, not that season's)."""
    for r in blob["players"].values():
        for e in r["seasons"].values():
            e.pop("team", None)
    for p in blob["provenance"].values():
        p.setdefault("no_stats", 0)
        p.setdefault("unserved", [])
        p.setdefault("method", SEASON_METHOD if p.get("status") == "complete" else None)
    blob["version"] = VERSION
    return blob


def played_count(blob: dict, season: str) -> int:
    return sum(1 for r in blob["players"].values() if (r["seasons"].get(season) or {}).get("gp", 0) > 0)


def no_games_reason(season: str, pool: int, played: int, unserved: int = 0) -> str:
    what = "none" if played == 0 else f"only {played}"
    extra = f" (and {unserved} it would not serve)" if unserved else ""
    return (f"Yahoo listed {pool} players for {season} and {what} with a game played{extra} (fewer than "
            f"{MIN_PLAYED}): the season's stats did not come")


def short_of_games(blob: dict, season: str) -> bool:
    """No player with a game, or fewer than MIN_PLAYED counting the players
    Yahoo would not serve as possible players (they are named, not missing)."""
    p = blob["provenance"][season]
    n = played_count(blob, season)
    return n == 0 or n + len(p.get("unserved") or []) < MIN_PLAYED


def _clear_season(blob: dict, season: str) -> None:
    for r in blob["players"].values():
        r["seasons"].pop(season, None)
    for pid in [pid for pid, r in blob["players"].items() if not r["seasons"]]:
        del blob["players"][pid]


def audit(blob: dict) -> List[str]:
    """A season stored "complete" with fewer than MIN_PLAYED players who
    played becomes "unavailable" (reason named) and its entries go, so it is
    fetched again. Returns the seasons it changed."""
    changed = []
    for s, p in blob["provenance"].items():
        if p.get("status") != "complete" or p.get("source", "yahoo") != "yahoo":
            continue
        if short_of_games(blob, s):
            n = played_count(blob, s)
            reason = no_games_reason(s, p.get("pool", 0), n, len(p.get("unserved") or []))
            _clear_season(blob, s)
            key = p.get("game_key")
            p.clear()
            p.update(fresh(key), status="unavailable", reason=reason)
            changed.append(s)
    return changed


def fresh(game_key: Optional[str]) -> dict:
    """A season's provenance before its first page."""
    return {"source": "yahoo", "game_key": game_key, "method": None, "status": "pending", "next_start": 0,
            "pool": 0, "fetched_at": None, "reason": None, "rejected": [], "no_stats": 0, "unserved": []}


def load(base=".", *, seasons: Optional[List[str]] = None) -> dict:
    """For readers (Phase B): the file, every season in it (or every season
    asked for) "complete". Missing, unreadable or incomplete RAISES, naming
    the file and the fix."""
    p = path(base)
    if not p.is_file():
        raise SeasonsError(f"{RELPATH} is missing: run python scripts/fetch_nba_seasons.py")
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SeasonsError(f"{RELPATH} is unreadable ({type(e).__name__}): "
                           "run python scripts/fetch_nba_seasons.py --refetch") from e
    if blob.get("version") not in READS or not isinstance(blob.get("provenance"), dict) \
            or not isinstance(blob.get("players"), dict):
        raise SeasonsError(f"{RELPATH} is not a version {READS} file: run python scripts/fetch_nba_seasons.py")
    migrate(blob)
    audit(blob)
    prov = blob["provenance"]
    want = seasons if seasons is not None else sorted(prov)
    bad = [s for s in want if (prov.get(s) or {}).get("status") != "complete"]
    if bad:
        raise SeasonsError(f"{RELPATH}: seasons {bad} are not complete: run python scripts/fetch_nba_seasons.py")
    return blob


def dumps(blob: dict) -> str:
    """Deterministic text: players by numeric id, one per line; seasons
    ascending; stats in the file's order."""
    stats = blob["stats"]
    head = {"version": blob["version"], "about": blob["about"], "stats": stats,
            "provenance": {s: blob["provenance"][s] for s in sorted(blob["provenance"])}}
    lines = []
    for pid in sorted(blob["players"], key=int):
        rec = blob["players"][pid]
        seas = {}
        for s in sorted(rec["seasons"]):
            e = rec["seasons"][s]
            seas[s] = {"gp": e["gp"], "stats": {k: e["stats"][k] for k in stats}}
        lines.append(json.dumps(str(pid)) + ":" + json.dumps({"name": rec["name"], "seasons": seas},
                                                               ensure_ascii=False, separators=(",", ":")))
    h = json.dumps(head, ensure_ascii=False, indent=1)
    return h[:-2] + ',\n "players": {\n' + ",\n".join(lines) + "\n }\n}\n"


def write(base, blob: dict) -> None:
    """Atomically: a .tmp beside it, then os.replace."""
    p = path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(blob)
    json.loads(text)                                  # never write what does not read back
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, p)


# =============================================================================
# Yahoo's shapes
# =============================================================================

_SECRET = re.compile(r"(?i)(access_token|refresh_token|consumer_secret|consumer_key|client_secret|"
                     r"authorization|bearer|oauth_[a-z_]+|token)([\"'\s:=]+)([^\s\"',&}]+)")


_BEARER = re.compile(r"(?i)bearer\s+[^\s\"',&}]+")


def redact(text) -> str:
    """An error's text, safe to print: anything that looks like a credential
    is replaced, and it is cut to 300 characters."""
    s = _BEARER.sub("Bearer <redacted>", str(text))
    s = _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", s)
    return s if len(s) <= 300 else s[:297] + "..."


def _merge(x) -> dict:
    """Yahoo gives a resource as a dict or as a list of dicts (and empty lists)."""
    if isinstance(x, dict):
        return x
    out = {}
    if isinstance(x, list):
        for item in x:
            if isinstance(item, dict):
                out.update(item)
            elif isinstance(item, list):
                out.update(_merge(item))
    return out


def _numbered(block) -> List:
    """A Yahoo collection {"0": .., "1": .., "count": n} (or [] when empty), in order."""
    if block in ([], None, {}):
        return []
    if not isinstance(block, dict):
        raise ShapeError(f"a collection is {type(block).__name__}, not Yahoo's numbered dict")
    keys = sorted((k for k in block if k != "count"), key=lambda k: int(k))
    return [block[k] for k in keys]


def lookup_uri(years: List[int]) -> str:
    return "games;game_codes=nba;seasons=" + ",".join(str(y) for y in years)


def parse_lookup(raw: dict) -> Dict[int, str]:
    """{season year: game key} for Yahoo's full NBA games. Two games for one
    season RAISE."""
    try:
        games = raw["fantasy_content"]["games"]
    except (KeyError, TypeError):
        raise ShapeError("Yahoo's games lookup has no fantasy_content.games")
    out: Dict[int, str] = {}
    for g in _numbered(games):
        meta = _merge((g or {}).get("game"))
        if meta.get("code") != "nba":
            continue
        if meta.get("type") not in (None, "full"):
            continue
        try:
            yr, key = int(meta["season"]), str(meta["game_key"])
        except (KeyError, TypeError, ValueError):
            raise ShapeError(f"Yahoo's games lookup: a game without season or game_key ({sorted(meta)})")
        if yr in out and out[yr] != key:
            raise SeasonsError(f"Yahoo's games lookup returned two NBA games for {yr}: {out[yr]} and {key}")
        out[yr] = key
    return out


def page_uri(game_key: str, start: int, year: int) -> str:
    return f"game/{game_key}/players;start={start};count={PAGE}/stats;type=season;season={year}"


def _coverage(ps: dict) -> Tuple[Optional[str], Optional[str]]:
    for src in (ps, ps.get("0") if isinstance(ps.get("0"), dict) else {}):
        if "coverage_type" in src:
            return str(src.get("coverage_type")), (None if src.get("season") is None else str(src.get("season")))
    return None, None


def _count(v, what: str) -> Optional[int]:
    """A whole count, "-" / "" as None (nothing recorded)."""
    if v in ("-", "", None):
        return None
    try:
        x = float(str(v))
    except ValueError:
        raise ValueError(f"{what} is {v!r}, not a count")
    if x < 0 or x != int(x):
        raise ValueError(f"{what} is {v!r}, not a count")
    return int(x)


def players_block(raw: dict):
    """The players collection of a game-, league- or players-scoped response."""
    fc = raw.get("fantasy_content") if isinstance(raw, dict) else None
    if not isinstance(fc, dict):
        raise ShapeError("Yahoo's response has no fantasy_content")
    for k in ("game", "league"):
        if k in fc:
            blk = _merge(fc[k]).get("players")
            if blk is None:
                raise ShapeError(f"Yahoo's {k}-scoped response has no players block (keys: {sorted(_merge(fc[k]))})")
            return blk
    if "players" in fc:
        return fc["players"]
    raise ShapeError(f"Yahoo's response has no players block (keys: {sorted(fc)})")


def keys_uri(game_key: str, pids: List[str], year: int) -> str:
    return (f"players;player_keys={','.join(f'{game_key}.p.{p}' for p in pids)}"
            f"/stats;type=season;season={year}")


def cross_uri(league_key: str, game_key: str, pids: List[str]) -> str:
    return f"league/{league_key}/players;player_keys={','.join(f'{game_key}.p.{p}' for p in pids)}/stats;type=season"


def parse_points(raw: dict, year: int) -> Dict[str, float]:
    """{player id: Yahoo's league fantasy points for the season} from a
    league-scoped players/stats response. RAISES on another shape."""
    out = {}
    for i, entry in enumerate(_numbered(players_block(raw))):
        parts = (entry or {}).get("player") if isinstance(entry, dict) else None
        if not isinstance(parts, list) or len(parts) < 2:
            raise ShapeError(f"Yahoo's league-scoped response: player entry {i} is not [meta, stats]")
        meta, rest = _merge(parts[0]), _merge(parts[1:])
        pp = rest.get("player_points") or {}
        ctype, cseason = _coverage(pp) if isinstance(pp, dict) else (None, None)
        if "player_id" not in meta or "total" not in pp or (ctype, cseason) != ("season", str(year)):
            raise ShapeError(f"Yahoo's league-scoped response: player entry {i} has no season {year} "
                             f"player_points total (keys {sorted(rest)})")
        out[str(int(meta["player_id"]))] = float(pp["total"])
    return out


def config_league_keys(base) -> Dict[str, str]:
    hk = (_config(base).get("yahoo") or {}).get("historical_league_keys") or {}
    return {s: k for s, k in hk.items() if isinstance(k, str)}


def current_game_key(base) -> str:
    """Today's game, from config yahoo.current_league_key. Required."""
    k = (_config(base).get("yahoo") or {}).get("current_league_key")
    if not isinstance(k, str) or not re.fullmatch(r"\d+\.l\.\d+", k):
        raise SeasonsError(f"config yahoo.current_league_key is {k!r}, not a league key: the old seasons "
                           "are fetched through today's game")
    return k.split(".")[0]


def parse_page(raw: dict, year: int, stats: List[str]) -> List[dict]:
    """[{"pid", "name", "gp", "stats", "error", "no_stats"}] from one page of a
    season's pool. A shape this code does not read RAISES ShapeError naming
    what the response did carry. A player whose numbers do not read gets
    "error" (he is rejected by name, not stored)."""
    players = players_block(raw)
    out = []
    for i, entry in enumerate(_numbered(players)):
        parts = (entry or {}).get("player") if isinstance(entry, dict) else None
        if not isinstance(parts, list) or len(parts) < 2:
            raise ShapeError(f"Yahoo's season page: player entry {i} is not [meta, player_stats]")
        meta = _merge(parts[0])
        ps = _merge(parts[1:]).get("player_stats")
        if "player_id" not in meta:
            raise ShapeError(f"Yahoo's season page: player entry {i} has no player_id ({sorted(meta)})")
        if not isinstance(ps, dict):
            raise ShapeError(f"Yahoo's season page: player {meta['player_id']} has no player_stats")
        ctype, cseason = _coverage(ps)
        if ctype != "season" or cseason != str(year):
            raise ShapeError(f"Yahoo's season page: player {meta['player_id']} stats cover {ctype!r} "
                             f"{cseason!r}, not season {year} (player_stats keys {sorted(ps)})")
        raw_stats = {}
        for s in ps.get("stats") or []:
            st = (s or {}).get("stat") or {}
            raw_stats[str(st.get("stat_id"))] = st.get("value")
        name = (meta.get("name") or {}).get("full") if isinstance(meta.get("name"), dict) else None
        rec = {"pid": str(int(meta["player_id"])), "name": name,
               "gp": None, "stats": None, "error": None, "no_stats": False}
        if not raw_stats:
            # Yahoo gave him no stats at all for the season: he recorded nothing.
            # Counted (provenance no_stats), not stored, not guessed as zeros.
            rec["no_stats"] = True
            out.append(rec)
            continue
        missing = [GP_ID] if GP_ID not in raw_stats else []
        for k in stats:
            if YAHOO_IDS[k] not in raw_stats and not any(k in pair and cid in raw_stats
                                                         for cid, pair in COMPOSITES.items()):
                missing.append(f"{YAHOO_IDS[k]} ({k})")
        if missing:
            raise ShapeError(f"Yahoo's season {year} stats for player {rec['pid']} carry no stat {missing}; "
                             f"they carry ids {sorted(raw_stats, key=lambda x: int(x) if x.isdigit() else 0)}")
        if not name:
            rec["error"] = "no name"
            out.append(rec)
            continue
        try:
            gp = _count(raw_stats[GP_ID], "games played") or 0
            got = {}
            for cid, (a, b) in COMPOSITES.items():
                v = raw_stats.get(cid)
                if v in (None, "-", "", "-/-"):
                    continue
                m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", str(v))
                if not m:
                    raise ValueError(f"{a}/{b} is {v!r}")
                got[a], got[b] = int(m.group(1)), int(m.group(2))
            vals = {}
            for k in stats:
                own = _count(raw_stats[YAHOO_IDS[k]], k) if YAHOO_IDS[k] in raw_stats else None
                if own is not None and k in got and own != got[k]:
                    raise ValueError(f"{k} is {own} alone and {got[k]} in its composite")
                v = own if own is not None else got.get(k)
                if v is None:
                    if gp > 0:
                        raise ValueError(f"{k} is blank on {gp} games played")
                    v = 0
                vals[k] = v
            rec["gp"], rec["stats"] = gp, vals
            rec["error"] = identity_error(gp, vals)
        except ValueError as e:
            rec["error"] = str(e)
        out.append(rec)
    return out


def identity_error(gp: int, s: Dict[str, int]) -> Optional[str]:
    if gp > GP_MAX:
        return f"{gp} games played, over {GP_MAX}"
    if gp == 0 and any(s.values()):
        return f"stats {s} on 0 games played"
    g = s.get
    if all(k in s for k in ("PTS", "FGM", "3PTM", "FTM")) and g("PTS") != 2 * g("FGM") + g("3PTM") + g("FTM"):
        return f"PTS {g('PTS')} is not 2 x FGM {g('FGM')} + 3PTM {g('3PTM')} + FTM {g('FTM')}"
    for a, b in (("FGM", "FGA"), ("FTM", "FTA"), ("3PTM", "FGM")):
        if a in s and b in s and g(a) > g(b):
            return f"{a} {g(a)} is more than {b} {g(b)}"
    return None


# =============================================================================
# the fetch
# =============================================================================

class YahooGet:
    """The engine's own client (season_performers.get_yahoo_league: fail-fast
    OAuth, never prompts). get(uri) counts every request, retries included."""

    def __init__(self, base="."):
        from . import season_performers as sp
        self.lg = sp.get_yahoo_league(Path(base))
        self.calls = 0

    def get(self, uri: str) -> dict:
        self.calls += 1
        return self.lg.yhandler.get(uri)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _store(blob: dict, season: str, rec: dict) -> Optional[str]:
    """Store one player-season. The same player twice in a season's pool with
    different numbers is returned as an error (the caller rejects him by
    name); twice with the same numbers is stored once."""
    pid = rec["pid"]
    entry = {"gp": rec["gp"], "stats": rec["stats"]}
    p = blob["players"].setdefault(pid, {"name": rec["name"], "seasons": {}})
    have = p["seasons"].get(season)
    if have is not None:
        return None if have == entry else "appears twice in the season's pool with different numbers"
    if not p["seasons"] or season >= max(p["seasons"]):
        p["name"] = rec["name"]
    p["seasons"][season] = entry
    return None


def _prune(blob: dict) -> int:
    """Players with 0 games in every season of the file. Only once every
    season is complete (a later season may still add his games)."""
    gone = [pid for pid, r in blob["players"].items() if not any(e["gp"] > 0 for e in r["seasons"].values())]
    for pid in gone:
        del blob["players"][pid]
    return len(gone)


class _Cap(Exception):
    """The call cap: stop cleanly, everything so far saved."""


class _Stop(Exception):
    """A run-stopping failure, named; everything so far saved."""


def fetch(base=".", source=None, *, seasons: List[str], max_calls: Optional[int] = None,
          sleep: float = 0.3, refetch: List[str] = (), now: Callable[[], str] = _now_iso,
          log: Callable[[str], None] = print, sleeper: Callable[[float], None] = time.sleep) -> dict:
    """Fetch every season in `seasons` not yet complete, newest first, saving
    after every request; then cross-check every complete season the league
    played that has no cross-check yet. Returns {"blob", "calls", "stopped"
    (the call cap), "error" (a run-stopping failure, already named),
    "pruned"}."""
    stats = stat_order(base)
    values = stat_values(base)
    blob = read(base, stats=stats)
    for s in refetch:
        season_year(s)
        blob["provenance"].pop(s, None)
        _clear_season(blob, s)
    prov = blob["provenance"]
    want = sorted(seasons, reverse=True)
    leagues = config_league_keys(base)
    todo = [s for s in want if (prov.get(s) or {}).get("status") != "complete"]
    res = {"blob": blob, "calls": 0, "stopped": False, "error": None, "pruned": 0}

    def needs_cross(s):
        p = prov.get(s) or {}
        return s in leagues and p.get("status") == "complete" and "cross_check" not in p

    if not todo and not any(needs_cross(s) for s in want):
        return res
    if source is None:
        source = YahooGet(base)
    start_calls = source.calls
    state = {"refusals": 0}

    def calls():
        return source.calls - start_calls

    def get(uri):
        if max_calls is not None and calls() >= max_calls:
            raise _Cap()
        return source.get(uri)

    def save():
        write(base, blob)

    try:
        # ---- game keys: config for 2017-18 on; one lookup for the rest, which must agree with config
        cfg = config_game_keys(base)
        need = [s for s in todo if not (prov.get(s) or {}).get("game_key")]
        if need:
            try:
                found = parse_lookup(get(lookup_uri(sorted(season_year(s) for s in need))))
            except (_Cap, SeasonsError):
                raise
            except Exception as e:
                raise _Stop(f"Yahoo's games lookup failed ({type(e).__name__}: {redact(e)})")
            for s in need:
                yr = season_year(s)
                if s in cfg and yr in found and found[yr] != cfg[s]:
                    raise SeasonsError(f"Yahoo's games lookup says {s} is game {found[yr]}, config "
                                       f"yahoo.historical_league_keys says {cfg[s]}: the lookup is read wrong; "
                                       "nothing fetched")
                key = found.get(yr) or cfg.get(s)
                p = prov.setdefault(s, fresh(None))
                if key is None:
                    p.update(status="unavailable", reason=f"Yahoo's games lookup returned no NBA game for season "
                                                          f"{yr} ({s}), and config has no key for it")
                else:
                    p.update(game_key=key, reason=None)
            save()

        today = None
        bad_run = 0
        for s in todo:
            p = prov[s]
            if not p.get("game_key"):
                continue
            if p["status"] == "unavailable":
                key = p["game_key"]
                _clear_season(blob, s)
                p.clear()
                p.update(fresh(key))
            for k, v in fresh(p["game_key"]).items():
                p.setdefault(k, v)
            p.setdefault("phase", "list")
            p.setdefault("listing", {})
            yr = season_year(s)
            if p["phase"] == "list":
                _list_season(s, yr, p, blob, stats, get, save, sleep, sleeper, now, log)
                if p["status"] == "unavailable":
                    bad_run += 1
                elif p.get("phase") == "keys":
                    log(f"  {s}: its own game sent no stats ({played_count(blob, s)} of {p['pool']} played): "
                        "fetching the same players through today's game, by player key")
            if p.get("phase") == "keys":
                if today is None:
                    today = current_game_key(base)
                _keys_season(s, yr, p, blob, stats, today, get, save, sleep, sleeper, now, log, state)
                if p["status"] == "unavailable":
                    bad_run += 1
            if p["status"] == "complete":
                bad_run = 0
                log(f"  {s}: complete -- {played_count(blob, s)} played ({p['method']}; {calls()} calls)")
            if bad_run >= 2:
                raise _Stop("two seasons in a row came back unavailable: that looks like Yahoo or the "
                            "connection, not the seasons; stopped (run again to resume; see --debug-raw)")

        # ---- cross-check: Yahoo's own league points for the top 3 of every season the league played
        for s in want:
            if needs_cross(s):
                _cross_check(s, prov[s], blob, leagues[s], values, get, save, log)
    except _Cap:
        res["stopped"] = True
    except _Stop as e:
        res["error"] = str(e)
    if all((prov.get(s) or {}).get("status") == "complete" for s in prov):
        res["pruned"] = _prune(blob)
        if res["pruned"]:
            save()
    res["calls"] = calls()
    return res


def _retrying(get, uri, sleeper):
    """One request, retried once after RETRY_WAIT. (raw, None) or (None, error text)."""
    err = None
    for attempt in (1, 2):
        try:
            return get(uri), None
        except (_Cap, _Stop, SeasonsError):
            raise
        except Exception as e:                        # network, auth, Yahoo's refusal
            err = f"{type(e).__name__}: {redact(e)}"
            if attempt == 1:
                sleeper(RETRY_WAIT)
    return None, err


def _take(blob, s, p, rows, rejected):
    for r in rows:
        if r.get("no_stats"):
            p["no_stats"] = p.get("no_stats", 0) + 1
            continue
        why = r["error"] or _store(blob, s, r)
        if why:
            rejected.append({"player_id": r["pid"], "name": r["name"], "why": why})


def _list_season(s, yr, p, blob, stats, get, save, sleep, sleeper, now, log):
    """Phase 1: page the season's own game. Its listing (ids, names) is kept
    for phase 2. At the end: enough players with games -> complete; none or
    too few -> its entries go and phase 2 ("keys") follows; no players at
    all, or a first page Yahoo refuses -> unavailable."""
    while True:
        raw, err = _retrying(get, page_uri(p["game_key"], p["next_start"], yr), sleeper)
        if raw is None:
            if p["next_start"] == 0:
                key = p["game_key"]
                p.clear()
                p.update(fresh(key), status="unavailable",
                         reason=f"Yahoo could not serve the season's first page (game {key}): {err}")
                save()
                log(f"  {s}: UNAVAILABLE -- {p['reason']}")
                return
            raise _Stop(f"{s}: the page at {p['next_start']} failed ({err}); the pages before it are saved: "
                        "run again to resume")
        rows = parse_page(raw, yr, stats)
        if not rows and p["next_start"] == 0:
            key = p["game_key"]
            p.clear()
            p.update(fresh(key), status="unavailable", reason=f"Yahoo returned no players for {s} (game {key})")
            save()
            log(f"  {s}: UNAVAILABLE -- {p['reason']}")
            return
        _take(blob, s, p, rows, p["rejected"])
        for r in rows:
            if r.get("name"):
                p["listing"][r["pid"]] = r["name"]
        p["next_start"] += len(rows)
        p["pool"] += len(rows)
        p["fetched_at"] = now()
        p["rejected"].sort(key=lambda x: (int(x["player_id"]), x["why"]))
        if len(rows) < PAGE:
            if not short_of_games(blob, s):
                p.update(status="complete", method=SEASON_METHOD)
                for k in ("phase", "listing", "key_next"):
                    p.pop(k, None)
            else:
                _clear_season(blob, s)
                p.update(status="partial", phase="keys", key_next=0, rejected=[], no_stats=0, unserved=[],
                         method=TODAY_METHOD)
            save()
            return
        p["status"] = "partial"
        save()
        log(f"  {s}: {p['pool']} players listed")
        if sleep:
            sleeper(sleep)


def _keys_season(s, yr, p, blob, stats, today, get, save, sleep, sleeper, now, log, state):
    """Phase 2: the listing's ids, 25 a call, through today's game. A refused
    batch: retried once, then fives, then singles; an id still refused, or
    one Yahoo leaves out of its answer, is named in "unserved"."""
    ids = sorted(p["listing"], key=int)
    while p["key_next"] < len(ids):
        batch = ids[p["key_next"]:p["key_next"] + PAGE]
        rows, unserved = _keys_batch(batch, yr, p["listing"], stats, today, get, sleeper, state)
        _take(blob, s, p, rows, p["rejected"])
        p["unserved"].extend(unserved)
        p["unserved"].sort(key=lambda x: int(x["player_id"]))
        p["rejected"].sort(key=lambda x: (int(x["player_id"]), x["why"]))
        p["key_next"] += len(batch)
        p["fetched_at"] = now()
        save()
        log(f"  {s}: {p['key_next']} of {len(ids)} players through today's game"
            + (f" ({len(p['unserved'])} not served)" if p["unserved"] else ""))
        if sleep:
            sleeper(sleep)
    if short_of_games(blob, s):
        n = played_count(blob, s)
        reason = no_games_reason(s, p["pool"], n, len(p["unserved"])) + " (through today's game too)"
        _clear_season(blob, s)
        key = p["game_key"]
        p.clear()
        p.update(fresh(key), status="unavailable", reason=reason)
        log(f"  {s}: UNAVAILABLE -- {reason}")
    else:
        p["status"] = "complete"
        for k in ("phase", "listing", "key_next"):
            p.pop(k, None)
    save()


def _keys_batch(batch, yr, listing, stats, today, get, sleeper, state):
    """(rows, unserved) for one batch of ids through today's game."""
    def ask(ids):
        rows = [r for r in parse_page(get(keys_uri(today, ids, yr)), yr, stats) if r["pid"] in ids]
        got = {r["pid"] for r in rows}
        state["refusals"] = 0
        return rows, [{"player_id": i, "name": listing.get(i), "why": "today's game returned no line for him"}
                      for i in ids if i not in got]

    def refused(i, err):
        state["refusals"] += 1
        if state["refusals"] >= OUTAGE:
            # Ten in a row: retired players cluster at low ids, so ask for one player today's game
            # surely serves (LeBron James). Served: the refusals are real; carry on. Refused: stop.
            try:
                get(keys_uri(today, [str(DEBUG_PLAYERS[0])], yr))
                state["refusals"] = 0
            except (_Cap, _Stop, SeasonsError):
                raise
            except Exception as e:
                raise _Stop(f"today's game refused {OUTAGE} single players in a row (last: {listing.get(i)} ({i}): "
                            f"{err}) and then LeBron James ({type(e).__name__}): that is Yahoo or the "
                            "connection; the batches before are saved: run again to resume")
        return {"player_id": i, "name": listing.get(i), "why": f"today's game refused his key ({err})"}

    for attempt in (1, 2):
        try:
            return ask(batch)
        except (_Cap, _Stop, SeasonsError):
            raise
        except Exception:                             # refused: retried once, then split
            if attempt == 1:
                sleeper(RETRY_WAIT)
    rows, unserved = [], []
    for c in range(0, len(batch), KEY_CHUNK):
        chunk = batch[c:c + KEY_CHUNK]
        try:
            r, u = ask(chunk)
            rows += r
            unserved += u
            continue
        except (_Cap, _Stop, SeasonsError):
            raise
        except Exception:
            pass
        for i in chunk:
            try:
                r, u = ask([i])
                rows += r
                unserved += u
            except (_Cap, _Stop, SeasonsError):
                raise
            except Exception as e:
                unserved.append(refused(i, f"{type(e).__name__}: {redact(e)}"))
    return rows, unserved


def _cross_check(s, p, blob, league_key, values, get, save, log):
    """Yahoo's own league points for the season's top CROSS_N (by this
    file's numbers at today's scoring), kept beside the file's figure."""
    top = sorted(((season_fp(r["seasons"][s], values), pid) for pid, r in blob["players"].items()
                  if s in r["seasons"] and r["seasons"][s]["gp"] > 0), reverse=True)[:CROSS_N]
    pids = sorted((pid for _, pid in top), key=int)
    mine = {pid: round(fp, 2) for fp, pid in top}
    try:
        pts = parse_points(get(cross_uri(league_key, p["game_key"], pids)), season_year(s))
        err = None
    except (_Cap, _Stop, SeasonsError):
        raise
    except Exception as e:
        pts, err = {}, f"{type(e).__name__}: {redact(e)}"
    p["cross_check"] = [{"player_id": pid, "name": blob["players"][pid]["name"], "file": mine[pid],
                         "yahoo_league": pts.get(pid)} for pid in pids]
    if err:
        p["cross_check"].append({"error": err})
    save()
    ok, line = cross_ok(p["cross_check"])
    log(f"  {s}: cross-check {line}")


def cross_ok(cc) -> Tuple[bool, str]:
    if not cc:
        return True, "not run"
    errs = [c["error"] for c in cc if "error" in c]
    diffs = [c for c in cc if "error" not in c and (c["yahoo_league"] is None
                                                       or abs(c["file"] - c["yahoo_league"]) > 0.011)]
    n = sum(1 for c in cc if "error" not in c)
    if errs:
        return False, f"FAILED ({errs[0]})"
    if diffs:
        return False, "DIFFERS: " + "; ".join(f"{c['name']} file {c['file']} vs Yahoo's league {c['yahoo_league']}"
                                               for c in diffs)
    return True, f"{n} of {n} match Yahoo's league points"


# =============================================================================
# --debug-raw (11-20): Yahoo's raw responses for one page, to see why a season
# comes back with no stats. Writes only to the output folder; never the file.
# =============================================================================

DEBUG_PLAYERS = (3704, 4612)       # LeBron James, Stephen Curry: on Yahoo, and playing, 2014-15 to today
_SECRET_KEY = re.compile(r"(?i)token|secret|auth|consumer|cookie|session|password|verifier")


def scrub(x):
    """A raw response, safe to save: any key that looks like a credential has
    its value replaced, and every string passes redact()."""
    if isinstance(x, dict):
        return {k: ("<redacted>" if _SECRET_KEY.search(str(k)) else scrub(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub(v) for v in x]
    if isinstance(x, str):
        return redact(x) if len(x) <= 300 else redact(x[:2000])
    return x


def debug_requests(base, season: str, game_key: str) -> List[Tuple[str, str]]:
    """[(name, uri)]: the request the fetch makes, then the variants that
    could explain an empty season: no season parameter, no type, the same
    players by key in the old game and in today's game, the league-scoped
    request (seasons the league played), and the per-game average type."""
    yr = season_year(season)
    keys = ",".join(f"{game_key}.p.{p}" for p in DEBUG_PLAYERS)
    cfg = _config(base).get("yahoo") or {}
    cur = str(cfg.get("current_league_key") or "").split(".")[0]
    league = (cfg.get("historical_league_keys") or {}).get(season)
    out = [("A_pool_type_season_season", f"game/{game_key}/players;start=0;count=5/stats;type=season;season={yr}"),
           ("B_pool_type_season", f"game/{game_key}/players;start=0;count=5/stats;type=season"),
           ("C_pool_plain_stats", f"game/{game_key}/players;start=0;count=5/stats"),
           ("D_keys_old_game", f"players;player_keys={keys}/stats;type=season;season={yr}")]
    if cur and cur != game_key:
        ck = ",".join(f"{cur}.p.{p}" for p in DEBUG_PLAYERS)
        out.append(("E_keys_current_game", f"players;player_keys={ck}/stats;type=season;season={yr}"))
    if league:
        out.append(("F_league_scoped", f"league/{league}/players;player_keys={keys}/stats;type=season"))
    out.append(("G_keys_average_season", f"players;player_keys={keys}/stats;type=average_season;season={yr}"))
    return out


def _players_in(x, out=None) -> List[list]:
    out = [] if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            if k == "player" and isinstance(v, list):
                out.append(v)
            else:
                _players_in(v, out)
    elif isinstance(x, list):
        for v in x:
            _players_in(v, out)
    return out


def digest(raw) -> str:
    """One line: how many players, and for the first two: id, name, team,
    the stats' coverage, GP (0), PTS (12), total points, how many stats."""
    ps = _players_in(raw)
    bits = [f"{len(ps)} players"]
    for parts in ps[:2]:
        meta = _merge(parts[0]) if parts else {}
        rest = _merge(parts[1:])
        st = rest.get("player_stats") or {}
        ctype, cseason = _coverage(st) if isinstance(st, dict) else (None, None)
        vals = {}
        for x in (st.get("stats") or []) if isinstance(st, dict) else []:
            v = (x or {}).get("stat") or {}
            vals[str(v.get("stat_id"))] = v.get("value")
        tp = (rest.get("player_points") or {}).get("total")
        name = (meta.get("name") or {}).get("full") if isinstance(meta.get("name"), dict) else None
        bits.append(f"{meta.get('player_key')} {name} team={meta.get('editorial_team_abbr')} "
                    f"coverage={ctype}/{cseason} GP={vals.get('0')!r} PTS={vals.get('12')!r} "
                    f"points={tp!r} stats={len(vals)}")
    return " | ".join(bits)


def debug_raw(base, source, seasons: List[str], out_dir, log=print) -> List[str]:
    """Save each request's raw response (scrubbed) as raw_<season>_<name>.json
    in out_dir, print a digest line for each, and write them all to
    raw_digest.txt. Never touches NBA_SEASONS.json."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    blob_prov = {}
    if path(base).is_file():
        try:
            blob_prov = json.loads(path(base).read_text(encoding="utf-8")).get("provenance") or {}
        except (OSError, json.JSONDecodeError):
            blob_prov = {}
    cfg = config_game_keys(base)
    lines = []
    for season in seasons:
        season_year(season)
        gk = (blob_prov.get(season) or {}).get("game_key") or cfg.get(season)
        if not gk:
            raise SeasonsError(f"--debug-raw {season}: no game key in the file or config; fetch it once first")
        for name, uri in debug_requests(base, season, gk):
            f = out_dir / f"raw_{season}_{name}.json"
            try:
                raw = source.get(uri)
                f.write_text(json.dumps(scrub(raw), indent=1, ensure_ascii=False), encoding="utf-8")
                line = f"{season} {name}: {digest(raw)}"
            except Exception as e:                     # Yahoo's refusal is an answer too
                f.write_text(json.dumps({"uri": uri, "error": f"{type(e).__name__}: {redact(e)}"}, indent=1),
                             encoding="utf-8")
                line = f"{season} {name}: ERROR {type(e).__name__}: {redact(e)}"
            lines.append(line)
            log(line)
    (out_dir / "raw_digest.txt").write_text(
        "\n".join(lines + [f"{len(lines)} Yahoo call(s)."]) + "\n", encoding="utf-8")
    return lines


# =============================================================================
# the summary and the coverage check (no Yahoo)
# =============================================================================

def season_fp(entry: dict, values: Dict[str, float]) -> float:
    return sum(entry["stats"][k] * values[k] for k in values)


def coverage(base, blob: dict, *, top_n: int = 300) -> dict:
    """Who the file covers: the league log's player-seasons, today's tracked
    players, and each season's top N by this league's fantasy points."""
    values = stat_values(base)
    prov = blob["provenance"]
    done = {s for s, p in prov.items() if p.get("status") == "complete"}
    players = blob["players"]
    out = {"seasons": {}, "log": None, "today": None}
    for s in sorted(prov, reverse=True):
        rows = sorted(((season_fp(r["seasons"][s], values), pid) for pid, r in players.items() if s in r["seasons"]),
                      reverse=True)
        played = sum(1 for pid, r in players.items() if s in r["seasons"] and r["seasons"][s]["gp"] > 0)
        out["seasons"][s] = {"played": played, "nth": rows[top_n - 1][0] if len(rows) >= top_n else None,
                             "top": {pid for _, pid in rows[:top_n]}}
    log_path = Path(base) / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
    if log_path.is_file():
        pairs = {}
        for row in json.loads(log_path.read_text(encoding="utf-8")):
            if row.get("had_game") and row.get("player_id") is not None and row.get("season_key") in done:
                pairs[(str(int(row["player_id"])), row["season_key"])] = row.get("player_name")
        missing = sorted(((s, n, pid) for (pid, s), n in pairs.items()
                          if not ((players.get(pid) or {}).get("seasons", {}).get(s, {}).get("gp", 0) > 0)))
        outside = sum(1 for (pid, s) in pairs if pid not in out["seasons"][s]["top"])
        out["log"] = {"pairs": len(pairs), "missing": missing, "outside_top": outside}
    act = Path(base) / "data" / "player_actuals.json"
    if act.is_file():
        a = json.loads(act.read_text(encoding="utf-8"))
        ids = {}
        for k in ("roster_names", "extra_names"):
            for n, pid in (a.get(k) or {}).items():
                ids[str(int(pid))] = n
        none = sorted(n for pid, n in ids.items()
                      if not any(e["gp"] > 0 for e in (players.get(pid) or {}).get("seasons", {}).values()))
        out["today"] = {"players": len(ids), "none": none}
    return out


def summary_lines(base, blob: dict, res: Optional[dict] = None, *, seconds: Optional[float] = None,
                  top_n: int = 300, seasons: Optional[List[str]] = None) -> List[str]:
    prov = blob["provenance"]
    want = seasons or sorted(prov)
    done = [s for s in want if (prov.get(s) or {}).get("status") == "complete"]
    cov = coverage(base, blob, top_n=top_n)
    head = (f"NBA_SEASONS: {len(blob['players'])} players, {len(done)} of {len(want)} seasons complete")
    if res is not None:
        head += f", {res['calls']} Yahoo call(s) this run"
    if seconds is not None:
        head += f", {seconds / 60:.1f} min"
    lines = [head + "."]
    for s in sorted(want, reverse=True):
        p = prov.get(s)
        if p is None:
            lines.append(f"  {s}  not fetched")
            continue
        c = cov["seasons"].get(s, {})
        nth = f"#{top_n} {c['nth']:,.0f} FP" if c.get("nth") is not None else f"fewer than {top_n} players"
        lines.append(f"  {s}  game {p.get('game_key') or '?':>4}  {p['status']:<11} pool {p['pool']:>4}  "
                     f"played {c.get('played', 0):>4}  {nth}  no stats {p.get('no_stats', 0)}  rejected {len(p['rejected'])}"
                     + (f"  -- {p['reason']}" if p.get("reason") else ""))
        if p.get("source") == "basketball-reference":
            lines.append(f"      from basketball-reference ({p.get('url')}): {p.get('matched', 0)} matched to Yahoo ids; "
                         f"{len(p.get('unmatched') or [])} unmatched; {len(p.get('ambiguous') or [])} ambiguous")
            for a in p.get("ambiguous") or []:
                lines.append(f"      ambiguous: {a['name']} ({a['bbref_id']}) -> Yahoo {a['yahoo_ids']}: {a['why']}")
            um = p.get("unmatched") or []
            if um:
                lines.append("      unmatched (most games first): " + ", ".join(
                    f"{u['name']} {u['gp']}g" for u in um[:10]) + (f" ... and {len(um) - 10} more" if len(um) > 10 else ""))
        elif p.get("method"):
            lines.append(f"      from {p['method']}"
                         + (f"; phase: {p['phase']}" if p.get("phase") and p["status"] != "complete" else ""))
        for r in p["rejected"][:5]:
            lines.append(f"      rejected: {r['name']} ({r['player_id']}): {r['why']}")
        if len(p["rejected"]) > 5:
            lines.append(f"      ... and {len(p['rejected']) - 5} more")
        un = p.get("unserved") or []
        if un:
            lines.append(f"      not served by today's game: {len(un)} -- "
                         + ", ".join(f"{u['name']} ({u['player_id']})" for u in un[:8])
                         + (f" ... and {len(un) - 8} more" if len(un) > 8 else "")
                         + f" (first reason: {un[0]['why']})")
        if "cross_check" in p:
            ok, line = cross_ok(p["cross_check"])
            lines.append(f"      cross-check: {line}" if ok else f"      CROSS-CHECK {line}")
    gaps = [s for s in want if s not in done]
    differs = [s for s in done if "cross_check" in prov[s] and not cross_ok(prov[s]["cross_check"])[0]]
    if differs:
        lines.append("  CROSS-CHECK DIFFERS in " + ", ".join(differs) + ": the stats are wrong, or the league "
                     "scored that season differently -- look before Phase B uses them")
    lines.append("  GAPS: " + ("none" if not gaps else
                              "; ".join(f"{s} {(prov.get(s) or {}).get('status', 'not fetched')}" for s in gaps)))
    if cov["log"] is None:
        lines.append("  League log: not checked (no data/historical/HISTORICAL_PLAYERLOG.json)")
    else:
        lg = cov["log"]
        lines.append(f"  League log: {lg['pairs']} player-seasons (his team had a game while he was rostered) "
                     f"in complete seasons; "
                     f"{len(lg['missing'])} missing; {lg['outside_top']} outside their season's top {top_n}")
        for s, n, pid in lg["missing"][:15]:
            got = (blob["players"].get(pid) or {}).get("seasons", {}).get(s)
            unserved = {u["player_id"] for u in (prov.get(s) or {}).get("unserved") or []}
            src = (prov.get(s) or {}).get("source", "yahoo")
            why = ("0 games in Yahoo's numbers" if got is not None and src == "yahoo" else
                   "today's game would not serve him" if pid in unserved else
                   "no basketball-reference row matched him" if src == "basketball-reference" else
                   "not in Yahoo's pool")
            lines.append(f"      missing: {n} ({pid}) {s} -- {why}")
        if len(lg["missing"]) > 15:
            lines.append(f"      ... and {len(lg['missing']) - 15} more")
    if cov["today"] is None:
        lines.append("  Today's players: not checked (no data/player_actuals.json)")
    else:
        t = cov["today"]
        lines.append(f"  Today's players: {t['players']}; {t['players'] - len(t['none'])} with NBA games in the "
                     f"file; {len(t['none'])} with none (rookies, or missing): {', '.join(t['none']) or '-'}")
    if res is not None:
        if res.get("pruned"):
            lines.append(f"  Dropped {res['pruned']} player(s) with 0 games in every season.")
        if res.get("stopped"):
            lines.append("  STOPPED at --max-calls: run the same command again to continue.")
        if res.get("error"):
            lines.append(f"  STOPPED: {res['error']}")
    return lines
