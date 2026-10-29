#!/usr/bin/env python3
"""
enrich_historical_playerlog.py

Enriches HISTORICAL_PLAYERLOG.json with NBA team, opponent, and injury data
by cross-referencing the NBA API's LeagueGameLog endpoint.

For each row in the historical playerlog, this script determines:
  - nba_team: The NBA team the player was on for that game/date
  - nba_opponent: The opponent team (if the player's team had a game)
  - had_game: Whether the player's NBA team had a game scheduled that day
  - is_injured: Whether the player missed a scheduled game (had_game=True + FP=0)

Data source: nba_api LeagueGameLog (player-level), 1 API call per season,
cached under data/.cache/ so a re-run is offline and identical. A failed or
empty fetch RAISES: it used to return [] and the season went on with every
row "no game".

MID-SEASON NBA MOVES (fixed 2026-10-29, HANDOFF_HISTORY_FIXES). The game log
gives the right team on days he PLAYED. On every other day this script used
to try each team he played for that season, in no particular order, and take
the first one with a game -- so after a trade his OLD team's games kept
landing on him as misses, and on off days it wrote sorted(teams)[-1], the
alphabetically last team, not the latest. Durant 2022-23 read PHX from
opening night and BKN/PHX day by day after February 9; 2017-18 through
2024-25 all had it (50 player-seasons). Now each player-season is a list of
dated STINTS: one team per day, switching once per move, on the move's date
from basketball-reference's transactions page (the trade, or the signing /
waiver claim that brought him to the new team), cached; a move that cannot
be dated from that page RAISES with the players listed. Checked after
enrichment: no player's team changes more often than he moved, and no row
claims a team game that team did not play.

Usage:
    cd <project_root>
    python scripts/enrich_historical_playerlog.py
    python scripts/enrich_historical_playerlog.py --dry-run       # Preview without saving
    python scripts/enrich_historical_playerlog.py --seasons 2023-24 2024-25  # Specific seasons only

Output:
    Overwrites data/historical/HISTORICAL_PLAYERLOG.json with enriched data.
    Creates a backup at data/historical/HISTORICAL_PLAYERLOG_BACKUP.json first.
"""

import argparse
import json
import os
import shutil
import sys
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
# Works whether you run from newsletter/ root or from scripts/ subdirectory
SCRIPT_DIR = Path(__file__).resolve().parent
if SCRIPT_DIR.name == "scripts":
    PROJECT_ROOT = SCRIPT_DIR.parent
else:
    PROJECT_ROOT = SCRIPT_DIR

HIST_FILE = PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
BACKUP_FILE = PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG_BACKUP.json"
CACHE_DIR = PROJECT_ROOT / "data" / ".cache"          # gitignored (.cache/)
BBREF_TX_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_transactions.html"

# Add project root to path for config imports
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import HISTORICAL_LEAGUE_KEYS, CURRENT_SEASON

# All seasons in the historical data (derived from config, excluding current season)
ALL_SEASONS = sorted(k for k in HISTORICAL_LEAGUE_KEYS if k != CURRENT_SEASON)

# Maps season_year format (from HISTORICAL_PLAYERLOG) -> season_key format (for NBA API)
# e.g., "2017-2018" -> "2017-18"
def to_season_key(season_year: str) -> str:
    """Convert '2017-2018' to '2017-18' format."""
    if "-" in season_year and len(season_year) == 7:
        # Already in short format like "2017-18"
        return season_year
    if "-" in season_year and len(season_year) >= 9:
        # Long format like "2017-2018"
        parts = season_year.split("-")
        return f"{parts[0]}-{parts[1][2:]}"
    return season_year


def to_nba_api_season(season_key: str) -> str:
    """Convert '2017-18' to '2017' format that nba_api expects for the season param."""
    # LeagueGameLog wants just the start year as a string
    return season_key.split("-")[0]


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """
    Normalize a player name for matching between Yahoo and NBA API data.

    Steps:
      1. Unicode NFD decomposition to strip accents/diacritics
         e.g., Doncic (with caron) -> Doncic
      2. Lowercase
      3. Strip extra whitespace
      4. Remove periods (for "P.J." vs "PJ" cases)
      5. Remove apostrophes/curly quotes (for De'Aaron -> DeAaron)

    Examples:
      "Luka Doncic"  (with diacritics) -> "luka doncic"
      "LeBron James"                    -> "lebron james"
      "P.J. Washington"                -> "pj washington"
      "De'Aaron Fox"                   -> "deaaron fox"
      "Nikola Vucevic" (with diacritics) -> "nikola vucevic"
    """
    # Step 1: Decompose Unicode and strip combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_stripped = "".join(c for c in nfkd if not unicodedata.combining(c))

    # Step 2-5: Lowercase, strip punctuation, normalize whitespace
    result = ascii_stripped.lower()
    result = result.replace(".", "").replace("'", "").replace("\u2019", "").replace("'", "")
    result = " ".join(result.split())  # Collapse whitespace

    return result


# Manual alias map for names that can't be resolved by normalization alone.
# Format: normalized_nba_api_name -> normalized_yahoo_name
# Add entries here if the matching report shows unresolved players.
MANUAL_ALIASES = {
    # Example: "nene hilario": "nene",
    # Most cases are handled automatically by normalize_name().
    # This dict is a safety net for truly weird edge cases.
}


# ---------------------------------------------------------------------------
# NBA API fetching with rate limiting
# ---------------------------------------------------------------------------

NBA_API_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def fetch_season_game_logs(season_key: str, max_retries: int = 4, base_delay: float = 3.0) -> list[dict]:
    """
    Fetch ALL player game logs for one NBA season via LeagueGameLog.

    Returns a list of dicts, each with:
      - player_name (str): Player's full name (may include diacritics)
      - date (str): Game date in YYYY-MM-DD format
      - team (str): Team abbreviation (e.g., "LAL", "BOS")
      - opponent (str): Opponent abbreviation
      - matchup (str): Full matchup string (e.g., "LAL vs. BOS")
      - fantasy_pts (float): NBA.com fantasy points (for cross-reference, not used directly)

    Uses exponential backoff on failure, matching the pattern in season_performers.py.
    """
    cache = CACHE_DIR / f"nba_game_logs_{season_key}.json"
    if cache.is_file():
        results = json.loads(cache.read_text(encoding="utf-8"))
        print(f"  {season_key}: {len(results):,} game entries (cached {cache.name})")
        return results

    from nba_api.stats.endpoints import LeagueGameLog

    nba_season = to_nba_api_season(season_key)
    print(f"  Fetching {season_key} (nba_api season={nba_season})...", end=" ", flush=True)

    df = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"\n    Retry {attempt}/{max_retries - 1} after {delay:.0f}s...", end=" ", flush=True)
                time.sleep(delay)

            lg = LeagueGameLog(
                season=nba_season,
                player_or_team_abbreviation="P",
                season_type_all_star="Regular Season",
                headers=NBA_API_HEADERS,
                timeout=60,
            )
            df = lg.get_data_frames()[0]
            break

        except Exception as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"NBA game logs for {season_key}: failed after {max_retries} "
                                   f"attempts ({type(e).__name__}: {e}). Nothing was written.") from e

    if df is None or df.empty:
        raise RuntimeError(f"NBA game logs for {season_key}: empty response. Nothing was written.")

    # Parse matchup to extract opponent
    # Matchup format: "LAL vs. BOS" (home) or "LAL @ BOS" (away)
    results = []
    for _, row in df.iterrows():
        matchup = str(row.get("MATCHUP", ""))
        team = str(row.get("TEAM_ABBREVIATION", ""))

        # Extract opponent from matchup string
        opponent = ""
        if " vs. " in matchup:
            opponent = matchup.split(" vs. ")[-1].strip()
        elif " @ " in matchup:
            opponent = matchup.split(" @ ")[-1].strip()

        # Parse date -> YYYY-MM-DD
        raw_date = str(row.get("GAME_DATE", ""))
        # NBA API returns dates like "2024-10-22" already, but just in case:
        game_date = raw_date[:10]

        results.append({
            "player_name": str(row.get("PLAYER_NAME", "")),
            "date": game_date,
            "team": team,
            "opponent": opponent,
            "matchup": matchup,
            "fantasy_pts": float(row.get("FANTASY_PTS", 0) or 0),
        })

    print(f"{len(results):,} game entries, {df['PLAYER_NAME'].nunique()} players")
    results.sort(key=lambda g: (g["date"], g["player_name"], g["team"]))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cache)
    return results


def fetch_all_seasons(season_keys: list[str], delay_between: float = 5.0) -> dict:
    """
    Fetch player game logs for all requested seasons.

    Returns a nested lookup dict:
      {
        normalized_player_name: {
          "YYYY-MM-DD": {"team": "LAL", "opponent": "BOS"},
          ...
        },
        ...
      }

    Also returns a reverse mapping for name resolution:
      {normalized_name: original_nba_api_name}
    """
    # Master lookup: normalized_name -> {date -> {team, opponent}}
    player_game_lookup = defaultdict(dict)
    # Track original names for debugging
    name_map = {}  # normalized -> original NBA API name

    for i, season_key in enumerate(season_keys):
        games = fetch_season_game_logs(season_key)          # raises on failure

        for g in games:
            norm_name = normalize_name(g["player_name"])
            name_map[norm_name] = g["player_name"]

            player_game_lookup[norm_name][g["date"]] = {
                "team": g["team"],
                "opponent": g["opponent"],
            }

        # Rate limit between seasons (not needed when every season is cached)
        if i < len(season_keys) - 1 and not (CACHE_DIR / f"nba_game_logs_{season_keys[i + 1]}.json").is_file():
            print(f"    (waiting {delay_between:.0f}s before next season...)")
            time.sleep(delay_between)

    return player_game_lookup, name_map


# ---------------------------------------------------------------------------
# Mid-season moves: basketball-reference transactions, and dated stints
# ---------------------------------------------------------------------------

# basketball-reference codes that differ from the NBA API's (the log's)
BBREF_TEAM = {"BRK": "BKN", "PHO": "PHX", "CHO": "CHA"}


# A player who moved can pass the 82: his old team's games before the move
# plus his new team's after. Never by much; the flips this replaced read
# 105-124.
TRADE_SLACK = 6


class UnplaceableMove(ValueError):
    """A mid-season team change no transaction dates."""


def _bbref_team(code: str) -> str:
    return BBREF_TEAM.get(code, code)


def parse_transactions(html_text: str) -> list:
    """[{date, player, to, from, kind}] for every move on one season's
    basketball-reference transactions page: each side of a trade (the
    "traded X to the B" clause, and "for Y" back to the trading team), each
    signing or waiver claim (an arrival), and each waiver (a departure: to
    ""). Parentheticals (the later-selected player of a traded pick) are
    dropped first."""
    import html as html_lib
    import re
    from datetime import datetime
    player = re.compile(r'<a href="/players/[^"]+">([^<]+)</a>')
    out = []
    for day_raw, body in re.findall(r"<li><span>([^<]+)</span>(.*?)</li>", html_text, re.S):
        try:
            day = datetime.strptime(day_raw.strip(), "%B %d, %Y").date().isoformat()
        except ValueError:
            continue
        for para in re.findall(r"<p>(.*?)</p>", body, re.S):
            text = re.sub(r"\([^()]*\)", "", para)
            # a multi-team trade is clauses: "...; the X traded ...; and the Y traded ..."
            for clause in re.split(r";\s+(?:and\s+)?(?=the\s+<a)", text):
                m = re.search(r'data-attr-from="(\w+)"[^>]*>[^<]*</a>\s+traded\s+(.*?)\s+to the\s+'
                              r'<a data-attr-to="(\w+)"[^>]*>[^<]*</a>(.*)', clause, re.S)
                if m:
                    frm, sent, to, rest = m.groups()
                    for n in player.findall(sent):
                        out.append({"date": day, "player": html_lib.unescape(n),
                                    "to": _bbref_team(to), "from": _bbref_team(frm), "kind": "trade"})
                    back = re.match(r"\s*for\s+(.*)", rest, re.S)
                    if back:
                        for n in player.findall(back.group(1)):
                            out.append({"date": day, "player": html_lib.unescape(n),
                                        "to": _bbref_team(frm), "from": _bbref_team(to), "kind": "trade"})
                    continue
                m = re.search(r'<a data-attr-from="(\w+)"[^>]*>[^<]*</a>\s+waived\s+(.*)', clause, re.S)
                if m:
                    frm, rest = m.groups()
                    for n in player.findall(rest):
                        out.append({"date": day, "player": html_lib.unescape(n),
                                    "to": "", "from": _bbref_team(frm), "kind": "waived"})
                    continue
                m = re.search(r'<a data-attr-to="(\w+)"[^>]*>[^<]*</a>\s+(signed|claimed)\s+(.*)',
                              clause, re.S)
                if m:
                    to, kind, rest = m.groups()
                    if "extension" in rest:
                        continue         # an extension with the team he is on moves no one
                    rest = rest.split(" on waivers")[0].split(" to a ")[0]
                    for n in player.findall(rest):
                        out.append({"date": day, "player": html_lib.unescape(n),
                                    "to": _bbref_team(to), "from": "", "kind": kind})
    # by date; within a day, the page's own order (a stable sort)
    return sorted(out, key=lambda e: e["date"])


def fetch_transactions(season_key: str, fetch=None, refresh: bool = False) -> dict:
    """{url, events}: one season's arrivals (parse_transactions). The RAW page
    is cached under data/.cache/ (so a parser fix needs no re-fetch) and parsed
    on every load. A failed fetch, or a page that parses to nothing, RAISES."""
    from datetime import date as _date
    cache = CACHE_DIR / f"bbref_transactions_{season_key}.json"
    year = int(season_key[:4]) + 1
    url = BBREF_TX_URL.format(year=year)
    blob = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() and not refresh else {}
    if "html" not in blob:
        try:
            if fetch is not None:
                text = fetch(url)
            else:
                import urllib.request
                from fetch_nba_schedule import BROWSER_HEADERS
                req = urllib.request.Request(url, headers=BROWSER_HEADERS)
                with urllib.request.urlopen(req, timeout=45) as resp:
                    text = resp.read().decode("utf-8", "replace")
        except Exception as e:
            raise RuntimeError(f"{url}: {type(e).__name__}: {e}. Nothing was written.") from e
        blob = {"url": url, "fetched": _date.today().isoformat(), "html": text}
        if parse_transactions(text):
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache)
    events = parse_transactions(blob["html"])
    if not events:
        raise RuntimeError(f"{url} parsed to no transactions: the page changed. Nothing was written.")
    return {"url": url, "fetched": blob.get("fetched"), "events": events}


_SUFFIXES = ("jr", "sr", "ii", "iii", "iv")


def move_key(norm_name: str) -> str:
    """The key moves are matched on: the normalized name without a
    generational suffix -- basketball-reference writes "Jimmy Butler" where
    the NBA's log writes "Jimmy Butler III"."""
    parts = norm_name.split()
    while len(parts) > 2 and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def moves_by_player(tx: dict) -> dict:
    """{move_key: [(date, to_team, from_team)]} from fetch_transactions();
    to_team "" is a waiver."""
    out = defaultdict(list)
    for e in tx["events"]:
        n = normalize_name(e["player"])
        out[move_key(n)].append((e["date"], e["to"], e.get("from", "")))
    return out


def _season_of(date_str: str) -> str:
    year, month = int(date_str[:4]), int(date_str[5:7])
    start = year if month >= 8 else year - 1
    return f"{start}-{str(start + 1)[2:]}"


def season_stints(games: dict, moves: list) -> list:
    """[(first_day, team, source)] for one player-season, one team per day.

    games: {date: team} -- the days he PLAYED, from the game log (right by
    construction). Each change of team between consecutive played days A
    (last game for the old team) -> B (first for the new one) is dated by the
    arrivals in `moves` dated after A and no later than B, in order, up to
    the first on the new team -- the trade itself, or the signing / claim
    that brought him there, with any team he passed through on the way.
    The first stint starts at "" (the season's start). No such arrival:
    UnplaceableMove."""
    days = sorted(games)
    if not days:
        return []
    stints = [("", games[days[0]], "first game")]
    for prev, nxt in zip(days, days[1:]):
        old, new = games[prev], games[nxt]
        if old == new:
            continue
        # every arrival between the two games, in order, up to the first on
        # the new team: a trade to a team he never played for (Westbrook,
        # LAL -> UTA 2023-02-09, waived, signed by LAC 02-22) is a stint too
        window = sorted((m for m in moves if prev < m[0] <= nxt), key=lambda m: m[0])
        upto = next((i for i, m in enumerate(window) if m[1] == new), None)
        if upto is None:
            raise UnplaceableMove(f"{old} -> {new} between {prev} and {nxt}")
        for d, to, frm in window[:upto + 1]:
            if to == "" and frm != stints[-1][1]:
                continue                       # waived by a team he had already left
            if to != stints[-1][1]:
                stints.append((d, to, "waived" if to == "" else "transaction"))
    return stints


def bbref_stints(teams_order: list, moves: list, season_start: str) -> list:
    """[(first_day, team, source)] for one player-season from basketball-
    reference alone: his teams in order from the season's per-game page
    (teams_order, the first is where he began), then every move dated on or
    after the season's first game, in order -- an arrival switches him, a
    waiver by his current team leaves him on no team ("") until the next.
    If his first move lands him on the per-game page's first team, that
    team was not his opening one (he was traded before playing): he began on
    the move's "from" team. RAISES UnplaceableMove when the per-game teams
    are not, in order, among the stints' teams."""
    if not teams_order:
        return []
    moves = sorted((m for m in moves if m[0] >= season_start), key=lambda m: m[0])
    start = teams_order[0]
    first = next((m for m in moves if m[1]), None)
    if first is not None and first[1] == start and first[2]:
        start = first[2]
    stints, cur = [("", start, "bbref per-game")], start
    for d, to, frm in moves:
        if to == "":
            if frm == cur:
                cur = ""
                stints.append((d, "", "waived"))
        elif to != cur:
            cur = to
            stints.append((d, to, "transaction"))
    seq, i = [t for _, t, _ in stints if t], 0
    for t in teams_order:
        while i < len(seq) and seq[i] != t:
            i += 1
        if i == len(seq):
            raise UnplaceableMove(f"teams {teams_order} not reached by moves "
                                  f"{[t for _, t, _ in stints]}")
    return stints


def team_on(stints: list, date_str: str) -> str:
    team = stints[0][1]
    for start, t, _ in stints:
        if start <= date_str:
            team = t
    return team


# ---------------------------------------------------------------------------
# basketball-reference as the source (default since 2026-10-29: stats.nba.com
# resets the connection from Nick's machine, a phone hotspot and the cloud)
# ---------------------------------------------------------------------------

BBREF_SEASON_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_{page}.html"


def bbref_get(url: str, cache_name: str, fetch=None, allow_404: bool = False):
    """The raw page, cached under data/.cache/ as fetched. A failed fetch
    RAISES (a 404 returns None only where allow_404 says a page may not
    exist, e.g. a month with no games)."""
    import urllib.error
    import urllib.request
    cache = CACHE_DIR / cache_name
    if cache.is_file():
        text = cache.read_text(encoding="utf-8")
        return None if text == "404" else text
    try:
        if fetch is not None:
            text = fetch(url)
        else:
            from fetch_nba_schedule import BROWSER_HEADERS
            time.sleep(3.2)                                  # basketball-reference: 20 pages a minute
            req = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=45) as resp:
                text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if allow_404 and e.code == 404:
            text = "404"
        else:
            raise RuntimeError(f"{url}: HTTP {e.code}. Nothing was written.") from e
    except Exception as e:
        raise RuntimeError(f"{url}: {type(e).__name__}: {e}. Nothing was written.") from e
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(cache.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache)
    return None if text == "404" else text


def parse_schedule_month(html_text: str) -> list:
    """[(date, away, home, remarks)] from one month page."""
    import re
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S):
        d = re.search(r'data-stat="date_game" csk="(\d{4})(\d{2})(\d{2})', row)
        away = re.search(r'data-stat="visitor_team_name" csk="([A-Z]{3})\.', row)
        home = re.search(r'data-stat="home_team_name" csk="([A-Z]{3})\.', row)
        if not (d and away and home):
            continue
        rem = re.search(r'data-stat="game_remarks"[^>]*>([^<]*)<', row)
        out.append((f"{d.group(1)}-{d.group(2)}-{d.group(3)}", _bbref_team(away.group(1)),
                    _bbref_team(home.group(1)), (rem.group(1) if rem else "").strip()))
    return out


def cup_final(games: list):
    """The NBA Cup final among a season's games, or None. Every Cup game is
    marked ("In-Season Tournament", later "NBA Cup"); the group games,
    quarterfinals and semifinals count as regular-season games, the final
    does NOT -- Yahoo records no fantasy points for it (Nick, 10-29). It is
    the season's last Cup game, alone on its date; anything else RAISES."""
    cup = sorted((d, a, h) for d, a, h, r in games if "Tournament" in r or "Cup" in r)
    if not cup:
        return None
    last = cup[-1][0]
    on_last = [g for g in cup if g[0] == last]
    if len(on_last) != 1:
        raise ValueError(f"the Cup final is not alone on its date: {on_last}")
    return on_last[0]


def bbref_schedule(season_key: str, fetch=None) -> tuple:
    """({date: {team: opponent}}, the Cup final excluded or None) for one
    season, from basketball-reference's month pages."""
    from fetch_nba_schedule import BBREF_MONTHS
    year = int(season_key[:4]) + 1
    games = []
    for month in BBREF_MONTHS + ["july", "august"]:
        url = BBREF_SEASON_URL.format(year=year, page=f"games-{month}")
        text = bbref_get(url, f"bbref_games_{season_key}_{month}.html", fetch, allow_404=True)
        if text:
            games += parse_schedule_month(text)
    if not games:
        raise RuntimeError(f"{season_key}: no games on any basketball-reference month page")
    final = cup_final(games)
    sched = defaultdict(dict)
    for d, away, home, _ in games:
        if final is not None and (d, away, home) == final:
            continue
        sched[d][home] = away
        sched[d][away] = home
    return dict(sched), final


def parse_per_game_teams(html_text: str) -> dict:
    """{player name: [teams in the order he played for them]} from a season's
    per-game page; the combined rows (TOT, 2TM, 3TM) are skipped."""
    import html as html_lib
    import re
    out = {}
    table = re.search(r'<table[^>]+id="per_game_stats".*?</table>', html_text, re.S)
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0) if table else html_text, re.S):
        name = re.search(r'data-stat="(?:name_display|player)"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
        team = re.search(r'data-stat="(?:team_name_abbr|team_id)"[^>]*>(?:<a[^>]*>)?([A-Z0-9]{3})', row)
        if not (name and team) or team.group(1) == "TOT" or re.fullmatch(r"\dTM", team.group(1)):
            continue
        teams = out.setdefault(html_lib.unescape(name.group(1)).strip(), [])
        t = _bbref_team(team.group(1))
        if t not in teams:
            teams.append(t)
    return out


def bbref_teams(season_key: str, fetch=None) -> dict:
    year = int(season_key[:4]) + 1
    text = bbref_get(BBREF_SEASON_URL.format(year=year, page="per_game"),
                     f"bbref_per_game_{season_key}.html", fetch)
    teams = parse_per_game_teams(text)
    if not teams:
        raise RuntimeError(f"{season_key}: the per-game page parsed to no players")
    return teams


def enrich_rows_bbref(rows: list, target_seasons: set, schedules: dict, teams: dict,
                      moves: dict) -> tuple:
    """Every row of `target_seasons` from basketball-reference: his team that
    day (bbref_stints), whether it played and whom (schedules, Cup final
    excluded), is_injured = a team game he scored 0.0 in.

    Checked against the playerlog's own evidence: a row with nonzero points
    is a game he played, so his team must have played that day. A player
    with points who cannot be found on the season's per-game page, or whose
    team that day did not play, RAISES with every case listed -- nothing is
    written. A player who never appears there (out all season) keeps no team
    and no games, as before."""
    stats = {"rows_processed": 0, "had_game": 0, "no_game": 0, "no_team": 0, "injury_flagged": 0}
    stints, problems, unmatched = {}, [], set()
    index = {s: {move_key(normalize_name(n)): n for n in teams[s]} for s in teams}
    starts = {s: min(schedules[s]) for s in schedules}
    for row in rows:
        season = to_season_key(row.get("season_year", ""))
        if season not in target_seasons:
            continue
        stats["rows_processed"] += 1
        name, d = row["player_name"], row["date"]
        norm = normalize_name(name)
        key = (season, norm)
        if key not in stints:
            src = index[season].get(move_key(MANUAL_ALIASES.get(norm, norm)))
            try:
                stints[key] = bbref_stints(teams[season].get(src, []) if src else [],
                                           moves[season].get(move_key(normalize_name(src or name)), []),
                                           starts[season])
            except UnplaceableMove as e:
                problems.append(f"{season} {name}: {e}")
                stints[key] = []
            if not src:
                unmatched.add((season, name))
        st = stints[key]
        team = team_on(st, d) if st else ""
        fp = float(row.get("fantasy_points", 0) or 0)
        opp = schedules[season].get(d, {}).get(team) if team else None
        row["nba_team"] = team
        row["nba_opponent"] = opp or ""
        row["had_game"] = bool(opp)
        row["is_injured"] = bool(opp) and fp == 0.0
        stats["had_game" if opp else ("no_game" if team else "no_team")] += 1
        stats["injury_flagged"] += row["is_injured"]
        if fp != 0.0 and not opp:
            problems.append(f"{season} {name} {d}: scored {fp:g} but "
                            + (f"{team} did not play" if team else "is on no NBA team that day"))
    if problems:
        raise UnplaceableMove(f"{len(problems)} problem(s); nothing was written:\n  "
                              + "\n  ".join(problems[:40]))
    stats["stints"] = stints
    stats["moves"] = sorted(f"{k[0]} {k[1]}: " + " -> ".join(f"{t or '(no team)'} from {d or 'start'}"
                                                            for d, t, _ in v)
                            for k, v in stints.items() if len(v) > 1)
    stats["unmatched_no_points"] = sorted(f"{s} {n}" for s, n in unmatched)
    return rows, stats


def verify_enriched(rows: list, team_schedule: dict, stints: dict, target_seasons) -> None:
    """RAISE if the enrichment broke either invariant:
      - a player's nba_team changes more often than he moved (stints - 1);
      - a row claims a team game his team did not play, or more team games
        than any team played that season."""
    by = defaultdict(list)
    for r in rows:
        if target_seasons and to_season_key(r.get("season_year", "")) not in target_seasons:
            continue
        by[(to_season_key(r["season_year"]), r["player_name"])].append(r)
    season_games = defaultdict(lambda: defaultdict(int))     # season -> team -> games
    for d, teams in team_schedule.items():
        for t in teams:
            season_games[_season_of(d)][t] += 1
    bad = []
    for (season, name), rs in sorted(by.items()):
        rs.sort(key=lambda r: r["date"])
        teams = [r["nba_team"] for r in rs if r["nba_team"]]
        changes = sum(1 for a, b in zip(teams, teams[1:]) if a != b)
        allowed = max(0, len(stints.get((season, normalize_name(name)), [])) - 1)
        if changes > allowed:
            bad.append(f"{season} {name}: team changes {changes} > moves {allowed}")
        g = 0
        for r in rs:
            if r["had_game"]:
                g += 1
                if team_schedule.get(r["date"], {}).get(r["nba_team"]) != r["nba_opponent"]:
                    bad.append(f"{season} {name} {r['date']}: {r['nba_team']} did not play "
                               f"{r['nba_opponent']}")
                    break
        cap = max(season_games[season].values(), default=0) + (TRADE_SLACK if allowed else 0)
        if g > cap:
            bad.append(f"{season} {name}: {g} team games > {cap}, the most any team played"
                       + (f" + {TRADE_SLACK} for a move" if allowed else ""))
    if bad:
        raise AssertionError(f"{len(bad)} enrichment check(s) failed: {bad[:10]}")


# ---------------------------------------------------------------------------
# Team schedule lookup (fallback for players not individually in NBA game logs)
# ---------------------------------------------------------------------------

def build_team_schedule_lookup(player_game_lookup: dict) -> dict:
    """
    Build a {date: {team: opponent}} lookup from the player game logs.

    This covers the case where a player on our fantasy roster wasn't in the
    NBA API's player game log (e.g., a deep bench player who got 0 minutes),
    but their TEAM still had a game that day.

    We reconstruct the team schedule from the player-level data.
    """
    team_schedule = defaultdict(dict)  # date -> {team -> opponent}

    for norm_name, date_map in player_game_lookup.items():
        for date_str, info in date_map.items():
            team = info["team"]
            opponent = info["opponent"]
            if team and opponent:
                team_schedule[date_str][team] = opponent

    return team_schedule


# ---------------------------------------------------------------------------
# Enrichment logic
# ---------------------------------------------------------------------------

def enrich_rows(
    rows: list[dict],
    player_game_lookup: dict,
    name_map: dict,
    team_schedule: dict,
    target_seasons: set[str] | None = None,
    moves: dict | None = None,
) -> tuple[list[dict], dict]:
    """
    Enrich HISTORICAL_PLAYERLOG rows with nba_team, nba_opponent, had_game, is_injured.

    Args:
        rows: The raw HISTORICAL_PLAYERLOG data (list of dicts).
        player_game_lookup: {normalized_name: {date: {team, opponent}}} from NBA API.
        name_map: {normalized_name: original_nba_api_name} for debugging.
        team_schedule: {date: {team: opponent}} fallback lookup.
        target_seasons: If provided, only enrich rows from these seasons (set of season_key strings).
        moves: {season_key: {normalized name: [(date, to_team)]}} (moves_by_player) for
            every season in which a rostered player changed NBA teams; see
            season_stints. A needed season missing here raises.

    Returns:
        (enriched_rows, stats_dict) where stats_dict has match/miss counts.
    """
    stats = {
        "total_rows": len(rows),
        "rows_processed": 0,
        "matched_by_player": 0,       # Player+date found in NBA game log
        "matched_by_team_schedule": 0, # Player not found, but team had a game (via team schedule)
        "no_game": 0,                  # Player's team had no game that day
        "unmatched_player": 0,         # Player name not found in NBA data at all
        "skipped_wrong_season": 0,     # Row not in target_seasons
        "injury_flagged": 0,           # had_game=True, FP=0 -> is_injured=True
    }

    # Pre-compute: for each yahoo player name, find the matching normalized NBA name
    # (This handles the Yahoo "Luka Doncic" -> NBA "Luka Doncic" (with diacritics) mapping)
    yahoo_to_norm = {}
    unresolved_names = set()

    # Each player's games by season: {norm_name: {season_key: {date: team}}}.
    games_by_season = defaultdict(lambda: defaultdict(dict))
    for norm_name, date_map in player_game_lookup.items():
        for date_str, info in date_map.items():
            games_by_season[norm_name][_season_of(date_str)][date_str] = info["team"]
    stints: dict = {}                    # (season_key, norm_name) -> season_stints()
    unplaceable = []

    def stints_for(norm_name, season_key):
        key = (season_key, norm_name)
        if key not in stints:
            games = games_by_season.get(norm_name, {}).get(season_key, {})
            if len(set(games.values())) > 1:
                if moves is None or season_key not in moves:
                    raise UnplaceableMove(f"{season_key}: {name_map.get(norm_name, norm_name)} changed "
                                          "NBA teams, and no transactions were loaded for the season")
                try:
                    stints[key] = season_stints(games, moves[season_key].get(move_key(norm_name), []))
                except UnplaceableMove as e:
                    unplaceable.append(f"{season_key} {name_map.get(norm_name, norm_name)}: {e}")
                    stints[key] = []
            else:
                stints[key] = season_stints(games, [])
        return stints[key]

    for i, row in enumerate(rows):
        # Progress logging every 10K rows
        if i > 0 and i % 10000 == 0:
            print(f"    Processing row {i:,}/{len(rows):,}...")

        season_year = row.get("season_year", "")
        season_key = to_season_key(season_year)

        # Skip if not in target seasons
        if target_seasons and season_key not in target_seasons:
            stats["skipped_wrong_season"] += 1
            continue

        stats["rows_processed"] += 1

        player_name = row.get("player_name", "")
        date_str = row.get("date", "")
        fp = float(row.get("fantasy_points", 0) or 0)

        # Normalize the Yahoo player name
        norm_yahoo = normalize_name(player_name)

        # Check manual aliases first
        lookup_name = MANUAL_ALIASES.get(norm_yahoo, norm_yahoo)

        # Try to find this player in the NBA game lookup
        if lookup_name in player_game_lookup:
            date_info = player_game_lookup[lookup_name].get(date_str)
            if date_info:
                # Direct match: player played in an NBA game on this date
                stints_for(lookup_name, season_key)
                row["nba_team"] = date_info["team"]
                row["nba_opponent"] = date_info["opponent"]
                row["had_game"] = True
                row["is_injured"] = (fp == 0.0)
                if row["is_injured"]:
                    stats["injury_flagged"] += 1
                stats["matched_by_player"] += 1
            else:
                # Player is in our NBA data, but didn't play on this date: his
                # team ON THIS DATE (season_stints) either played -- a miss --
                # or had the day off. Never another team he played for.
                st = stints_for(lookup_name, season_key)
                team = team_on(st, date_str) if st else ""
                opponent = team_schedule.get(date_str, {}).get(team) if team else None
                row["nba_team"] = team
                if opponent:
                    row["nba_opponent"] = opponent
                    row["had_game"] = True
                    row["is_injured"] = (fp == 0.0)
                    if row["is_injured"]:
                        stats["injury_flagged"] += 1
                    stats["matched_by_team_schedule"] += 1
                else:
                    row["nba_opponent"] = ""
                    row["had_game"] = False
                    row["is_injured"] = False
                    stats["no_game"] += 1
        else:
            # Player name not found in NBA data at all
            unresolved_names.add(player_name)
            row["nba_team"] = ""
            row["nba_opponent"] = ""
            row["had_game"] = False
            row["is_injured"] = False
            stats["unmatched_player"] += 1

    if unplaceable:
        raise UnplaceableMove(f"{len(unplaceable)} mid-season move(s) no transaction dates; "
                              "nothing was written:\n  " + "\n  ".join(sorted(unplaceable)))
    stats["unresolved_names"] = sorted(unresolved_names)
    stats["stints"] = stints
    stats["moves"] = sorted(f"{k[0]} {name_map.get(k[1], k[1])}: " + " -> ".join(
        f"{t} from {d or 'start'}" for d, t, _ in v) for k, v in stints.items() if len(v) > 1)
    return rows, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _save(args, rows) -> None:
    if args.dry_run:
        print("DRY RUN -- no files modified.")
        print("Run without --dry-run to save enriched data.")
    else:
        # Backup
        if not args.no_backup:
            print(f"Creating backup: {BACKUP_FILE}")
            shutil.copy2(HIST_FILE, BACKUP_FILE)
            backup_size = BACKUP_FILE.stat().st_size / (1024 * 1024)
            print(f"  Backup size: {backup_size:.1f} MB")

        # Save enriched data
        print(f"Saving enriched data to {HIST_FILE}...")
        # indent=2: the format rollup_season_to_history writes, so a re-run
        # changes only the rows that changed
        tmp = HIST_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        tmp.replace(HIST_FILE)
        new_size = HIST_FILE.stat().st_size / (1024 * 1024)
        print(f"  New file size: {new_size:.1f} MB")
        print()
        print("DONE! HISTORICAL_PLAYERLOG.json has been enriched.")
        print()
        print("New fields added to each row:")
        print("  nba_team     (str)  - Player's NBA team abbreviation")
        print("  nba_opponent (str)  - Opponent team abbreviation (empty if no game)")
        print("  had_game     (bool) - Whether the player's team had a game that day")
        print("  is_injured   (bool) - Whether the player missed a scheduled game (had_game + FP=0)")



def main():
    parser = argparse.ArgumentParser(
        description="Enrich HISTORICAL_PLAYERLOG.json with NBA team/opponent/injury data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without saving. Shows match stats and unresolved names.",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=None,
        help="Only process specific seasons (e.g., --seasons 2023-24 2024-25). Default: all.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds to wait between NBA API calls (default: 5).",
    )
    parser.add_argument(
        "--source",
        choices=("bbref", "nba_api"),
        default="bbref",
        help="basketball-reference (default) or stats.nba.com via nba_api.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a backup file (not recommended).",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("HISTORICAL PLAYERLOG ENRICHMENT")
    print("=" * 70)
    print()

    # --- Load historical playerlog ---
    if not HIST_FILE.exists():
        print(f"ERROR: {HIST_FILE} not found!")
        print("Make sure you're running from the newsletter/ directory.")
        sys.exit(1)

    print(f"Loading {HIST_FILE}...")
    with open(HIST_FILE, "r", encoding="utf-8") as f:
        rows = json.load(f)
    print(f"  {len(rows):,} rows loaded")
    print()

    # --- Determine which seasons to process ---
    if args.seasons:
        target_seasons = set(args.seasons)
        # Validate
        for s in target_seasons:
            if s not in ALL_SEASONS:
                print(f"WARNING: Season '{s}' not in known seasons: {ALL_SEASONS}")
    else:
        target_seasons = set(ALL_SEASONS)

    # Figure out which seasons we actually need to fetch from the NBA API
    # (only seasons that appear in the data AND are in our target list)
    data_seasons = set()
    for row in rows:
        sk = to_season_key(row.get("season_year", ""))
        if sk in target_seasons:
            data_seasons.add(sk)

    seasons_to_fetch = sorted(data_seasons & set(ALL_SEASONS))
    print(f"Seasons to process: {seasons_to_fetch}")
    print()

    if args.source == "bbref":
        print("Loading basketball-reference: schedules, per-game teams, transactions (cached)...")
        schedules, teams, moves = {}, {}, {}
        for sk in seasons_to_fetch:
            schedules[sk], final = bbref_schedule(sk)
            teams[sk] = bbref_teams(sk)
            moves[sk] = moves_by_player(fetch_transactions(sk))
            print(f"  {sk}: {sum(len(v) for v in schedules[sk].values()) // 2:,} games"
                  + (f" (Cup final {final[0]} {final[1]}-{final[2]} excluded)" if final else "")
                  + f", {len(teams[sk]):,} players")
        print()
        print("Enriching rows...")
        rows, stats = enrich_rows_bbref(rows, set(seasons_to_fetch), schedules, teams, moves)
        flat = defaultdict(dict)
        for sk in schedules:
            for d, m in schedules[sk].items():
                flat[d].update(m)
        verify_enriched(rows, flat, stats["stints"], set(seasons_to_fetch))
        print(f"  {stats['rows_processed']:,} rows: {stats['had_game']:,} team games "
              f"({stats['injury_flagged']:,} missed), {stats['no_game']:,} off days, "
              f"{stats['no_team']:,} on no team")
        print("  Checked: every scoring row is a game his team played; no team change "
              "without a move; no team game its team did not play.")
        print(f"  Moves ({len(stats['moves'])}):")
        for line in stats["moves"]:
            print(f"    {line}")
        if stats["unmatched_no_points"]:
            print(f"  Not on that season's per-game page (no points either; no team, no games): "
                  f"{len(stats['unmatched_no_points'])}")
            for line in stats["unmatched_no_points"]:
                print(f"    {line}")
        print()
        _save(args, rows)
        return

    # --- Fetch NBA game logs ---
    print(f"Fetching NBA player game logs ({len(seasons_to_fetch)} seasons)...")
    player_game_lookup, name_map = fetch_all_seasons(seasons_to_fetch, delay_between=args.delay)
    print(f"  Total players in NBA data: {len(player_game_lookup):,}")
    total_games = sum(len(dates) for dates in player_game_lookup.values())
    print(f"  Total player-game entries: {total_games:,}")
    print()

    # --- Build team schedule fallback ---
    print("Building team schedule lookup...")
    team_schedule = build_team_schedule_lookup(player_game_lookup)
    total_team_dates = sum(len(teams) for teams in team_schedule.values())
    print(f"  {len(team_schedule):,} unique dates, {total_team_dates:,} team-date entries")
    print()

    # --- Mid-season moves: basketball-reference transactions (cached) ---
    print("Loading NBA transactions (basketball-reference)...")
    moves = {}
    for sk in seasons_to_fetch:
        tx = fetch_transactions(sk)                       # raises on failure
        moves[sk] = moves_by_player(tx)
        print(f"  {sk}: {len(tx['events']):,} arrivals ({tx['url']})")
    print()

    # --- Enrich ---
    print("Enriching rows...")
    rows, stats = enrich_rows(rows, player_game_lookup, name_map, team_schedule, target_seasons,
                              moves=moves)
    verify_enriched(rows, team_schedule, stats["stints"], target_seasons)   # raises
    print(f"  Checked: no team change without a move; no team game its team did not play.")
    print(f"  Mid-season moves dated ({len(stats['moves'])}):")
    for line in stats["moves"]:
        print(f"    {line}")
    print()

    # --- Report ---
    print("=" * 70)
    print("ENRICHMENT RESULTS")
    print("=" * 70)
    print(f"  Total rows:               {stats['total_rows']:>10,}")
    print(f"  Rows processed:           {stats['rows_processed']:>10,}")
    print(f"  Skipped (other seasons):  {stats['skipped_wrong_season']:>10,}")
    print()
    print(f"  Matched by player+date:   {stats['matched_by_player']:>10,}  (player in NBA game log on that date)")
    print(f"  Matched by team schedule: {stats['matched_by_team_schedule']:>10,}  (player's team played, player was DNP)")
    print(f"  No game that day:         {stats['no_game']:>10,}  (player's team had no game)")
    print(f"  Unmatched player:         {stats['unmatched_player']:>10,}  (player name not found in NBA data)")
    print()
    matched_total = stats["matched_by_player"] + stats["matched_by_team_schedule"]
    if stats["rows_processed"] > 0:
        pct = 100 * matched_total / stats["rows_processed"]
        print(f"  Game-day match rate:      {pct:.1f}%  ({matched_total:,} rows with had_game=True)")
    print(f"  Injuries flagged:         {stats['injury_flagged']:>10,}  (had_game=True + FP=0)")
    print()

    if stats["unresolved_names"]:
        print(f"  UNRESOLVED PLAYERS ({len(stats['unresolved_names'])}):")
        print(f"  These players could not be matched to any NBA API player name.")
        print(f"  Add manual mappings to MANUAL_ALIASES dict in this script if needed.")
        for name in stats["unresolved_names"]:
            print(f"    - {name}")
        print()

    _save(args, rows)
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
