#!/usr/bin/env python3
"""
fetch_nba_schedule.py

Fetch the NBA schedule for a given season and save a trimmed version
containing only the data needed for fantasy projections.

Usage:
    python scripts/fetch_nba_schedule.py --season 2025-26
    python scripts/fetch_nba_schedule.py --season 2025-26 --output data/nba_schedule.json

The script fetches from the NBA's official schedule API and trims the response
from ~7MB to ~120KB by keeping only:
- Game date
- Home team abbreviation  
- Away team abbreviation

SOURCES
    nba    cdn.nba.com's scheduleLeagueV2.json. The original source, and the
           one to prefer when it works.
    bbref  basketball-reference.com month pages. Added Sep 2026 because
           cdn.nba.com began returning HTTP 403 (an Akamai block) to
           everything we could point at it -- the cloud container, the local
           VM, and an ordinary browser on a home connection. bbref answers
           normally from all three.
    auto   try nba, fall back to bbref. The default.

For manual download:
    The NBA schedule can be downloaded from:
    https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json
    
    Then run with --input to trim an existing file:
    python scripts/fetch_nba_schedule.py --input raw_schedule.json --output data/nba_schedule.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import (  # noqa: E402
    CURRENT_SEASON, NBA_SCHEDULE_FILE,
)

# Where the schedule goes is a config question, not a thing to retype.
# It used to be three different answers: this script defaulted to
# data/nba_schedule.json, WEEKLY_WORKFLOW told you to write
# data/nba_schedule_2025-26.json, and league_config read
# data/nba_schedule_2026-27.json. Only the third was ever loaded, so
# following the documented command refreshed a file nothing reads and
# left the live one frozen -- silently, since both files exist.
DEFAULT_OUTPUT = Path(NBA_SCHEDULE_FILE or "data/nba_schedule.json")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"

BBREF_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_games-{month}.html"
BBREF_MONTHS = ["october", "november", "december", "january", "february",
                "march", "april", "may", "june"]

# basketball-reference uses its own abbreviations for three franchises.
# Everything else already matches the NBA's tricodes, which are what
# PLAYERLOG and the projections key off.
BBREF_TO_NBA = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_nba_schedule() -> dict:
    """Fetch the full NBA schedule from the official API."""
    if not HAS_REQUESTS:
        raise RuntimeError("the 'requests' library is required for the nba source")
    
    print(f"Fetching schedule from {NBA_SCHEDULE_URL}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    
    response = requests.get(NBA_SCHEDULE_URL, headers=headers, timeout=30)
    response.raise_for_status()
    
    return response.json()


def _season_end_year(season: str) -> int:
    """"2026-27" -> 2027. basketball-reference files a season under its end year."""
    import re as _re
    match = _re.fullmatch(r"(\d{4})-(\d{2})", str(season or "").strip())
    if not match:
        raise SystemExit(
            f"--season must look like 2026-27 to use the bbref source, got {season!r}")
    return int(match.group(1)) + 1


def _parse_bbref_month(html: str, year: int) -> list:
    """[{date, home, away}] from one basketball-reference month page.

    Team codes come out of the /teams/XXX/ links rather than the visible
    names, so a franchise rename or relocation does not silently drop games.
    """
    import re as _re
    from datetime import datetime

    table = _re.search(r'<table[^>]+id="schedule".*?</table>', html, _re.S)
    if not table:
        return []

    def cell(row, stat):
        found = _re.search(r'data-stat="%s"[^>]*>(.*?)</t[hd]>' % stat, row, _re.S)
        return found.group(1) if found else None

    def tricode(cell_html):
        found = _re.search(r"/teams/([A-Z]{3})/", cell_html or "")
        if not found:
            return None
        return BBREF_TO_NBA.get(found.group(1), found.group(1))

    games = []
    for row in _re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), _re.S):
        raw_date = cell(row, "date_game")
        away = tricode(cell(row, "visitor_team_name"))
        home = tricode(cell(row, "home_team_name"))
        if not raw_date or not away or not home:
            continue
        text = _re.sub(r"<[^>]+>", "", raw_date).strip()
        try:
            parsed = datetime.strptime(text, "%a, %b %d, %Y")
        except ValueError:
            continue
        games.append({
            "date": parsed.strftime("%Y-%m-%dT00:00:00Z"),
            "home": home,
            "away": away,
        })
    return games


def fetch_from_bbref(season: str) -> dict:
    """Build the trimmed schedule from basketball-reference month pages.

    Returns the already-trimmed shape, so trim_schedule() passes it through.
    """
    import time
    import urllib.error
    import urllib.request

    year = _season_end_year(season)
    print(f"Fetching {season} schedule from basketball-reference "
          f"(NBA_{year}_games-*)...")

    games = []
    for i, month in enumerate(BBREF_MONTHS):
        url = BBREF_URL.format(year=year, month=month)
        request = urllib.request.Request(url, headers=BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                html = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Not every season has a May/June page at fetch time.
                continue
            print(f"  {month}: HTTP {e.code}")
            continue
        except Exception as e:
            print(f"  {month}: {e}")
            continue

        found = _parse_bbref_month(html, year)
        print(f"  {month}: {len(found)} games")
        games.extend(found)
        if i < len(BBREF_MONTHS) - 1:
            # basketball-reference rate-limits aggressively.
            time.sleep(3)

    if not games:
        print("\nNo games parsed. basketball-reference may have changed its "
              "table markup, or the season is not published yet.")
        sys.exit(1)

    # Same game can appear twice if a month page overlaps; keep it unique.
    seen = set()
    unique = []
    for g in sorted(games, key=lambda g: (g["date"], g["away"], g["home"])):
        key = (g["date"], g["away"], g["home"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(g)
    return {"games": unique}


def load_schedule_from_file(path: Path) -> dict:
    """Load schedule from a local JSON file."""
    print(f"Loading schedule from {path}...")
    with open(path) as f:
        return json.load(f)


def trim_schedule(full_schedule: dict) -> dict:
    """
    Trim the full NBA schedule to only essential fields.
    
    Input format (NBA API):
        {
            "leagueSchedule": {
                "gameDates": [
                    {
                        "gameDate": "...",
                        "games": [
                            {
                                "gameDateEst": "2025-10-22T00:00:00Z",
                                "homeTeam": {"teamTricode": "BOS", ...},
                                "awayTeam": {"teamTricode": "NYK", ...},
                                ... (30+ other fields)
                            }
                        ]
                    }
                ]
            }
        }
    
    Output format (trimmed):
        {
            "games": [
                {"date": "2025-10-22T00:00:00Z", "home": "BOS", "away": "NYK"},
                ...
            ]
        }
    """
    games = []
    
    # Handle full NBA API format
    if "leagueSchedule" in full_schedule:
        for game_date_obj in full_schedule["leagueSchedule"].get("gameDates", []):
            for game in game_date_obj.get("games", []):
                # Skip preseason games
                if game.get("gameLabel", "").lower() == "preseason":
                    continue
                if game.get("gameSubtype", "").lower() == "preseason":
                    continue
                    
                games.append({
                    "date": game.get("gameDateEst", ""),
                    "home": game.get("homeTeam", {}).get("teamTricode", ""),
                    "away": game.get("awayTeam", {}).get("teamTricode", ""),
                })
    
    # Handle already-trimmed format (just validate/pass through)
    elif "games" in full_schedule:
        for game in full_schedule["games"]:
            games.append({
                "date": game.get("date", ""),
                "home": game.get("home", game.get("home_team", "")),
                "away": game.get("away", game.get("away_team", "")),
            })
    
    else:
        print("Warning: Unrecognized schedule format")
        return full_schedule
    
    return {"games": games}


def _report_team_counts(trimmed: dict) -> None:
    """Warn when a team does not have a full 82-game slate.

    A schedule published before the NBA Cup group stage finishes carries only
    80 games per team: the last two depend on how the Cup shakes out and are
    announced in December. That is normal and not an error -- but the file
    has to be refetched then, or the projections lose two games per team for
    the back half of the season.
    """
    from collections import Counter
    counts = Counter()
    for g in trimmed.get("games", []):
        counts[g["home"]] += 1
        counts[g["away"]] += 1
    if not counts:
        return

    off = sorted((team, n) for team, n in counts.items() if n != 82)
    print(f"\n  {len(counts)} teams", end="")
    if not off:
        print(", all with 82 games.")
        return

    sizes = sorted({n for _, n in off})
    print(f"; {len(off)} not at 82 games (have: {sizes}).")
    if sizes == [80] and len(off) == len(counts):
        print("  This is expected for a schedule published before the NBA Cup")
        print("  knockout round is set -- every team's last two games are TBD.")
        print("  REFETCH THIS FILE in mid-December once those are announced.")
    else:
        for team, n in off[:10]:
            print(f"    {team}: {n}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and trim NBA schedule for fantasy basketball projections."
    )
    parser.add_argument(
        "--season",
        default=CURRENT_SEASON,
        help=f"Season to fetch (default: {CURRENT_SEASON}, from league_config). "
             f"Honoured by the bbref source; the nba source always returns "
             f"the current season.",
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        help="Input file path (skip fetching, trim existing file)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output file path (default: {DEFAULT_OUTPUT}, the file "
             f"league_config.season.nba_schedule_file actually reads)",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "nba", "bbref"],
        default="auto",
        help="where to fetch from (default: auto -- cdn.nba.com, then bbref)",
    )
    parser.add_argument(
        "--keep-full",
        action="store_true",
        help="Also save the full (untrimmed) schedule",
    )
    
    args = parser.parse_args()
    
    # Get the schedule
    if args.input:
        full_schedule = load_schedule_from_file(args.input)
    elif args.source == "bbref":
        full_schedule = fetch_from_bbref(args.season)
    elif args.source == "nba":
        full_schedule = fetch_nba_schedule()
    else:
        try:
            full_schedule = fetch_nba_schedule()
        except Exception as e:
            print(f"cdn.nba.com failed ({e}); falling back to basketball-reference.")
            full_schedule = fetch_from_bbref(args.season)
    
    # Optionally save full version
    if args.keep_full:
        full_path = args.output.parent / f"{args.output.stem}_full.json"
        with open(full_path, "w") as f:
            json.dump(full_schedule, f)
        full_size = full_path.stat().st_size
        print(f"Saved full schedule: {full_path} ({full_size:,} bytes)")
    
    # Trim and save
    trimmed = trim_schedule(full_schedule)
    
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(trimmed, f, indent=2)
    
    trimmed_size = args.output.stat().st_size
    game_count = len(trimmed.get("games", []))

    _report_team_counts(trimmed)
    
    print(f"Saved trimmed schedule: {args.output}")
    print(f"  {game_count} games, {trimmed_size:,} bytes ({trimmed_size/1024:.1f} KB)")
    
    # Show sample
    if game_count > 0:
        print(f"\nSample games:")
        for g in trimmed["games"][:3]:
            print(f"  {g['date'][:10]}: {g['away']} @ {g['home']}")


if __name__ == "__main__":
    main()
