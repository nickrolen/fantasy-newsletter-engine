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

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"


def fetch_nba_schedule() -> dict:
    """Fetch the full NBA schedule from the official API."""
    if not HAS_REQUESTS:
        print("Error: 'requests' library required for fetching.")
        print("Install with: pip install requests")
        print("Or download manually and use --input flag.")
        sys.exit(1)
    
    print(f"Fetching schedule from {NBA_SCHEDULE_URL}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    
    response = requests.get(NBA_SCHEDULE_URL, headers=headers, timeout=30)
    response.raise_for_status()
    
    return response.json()


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


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and trim NBA schedule for fantasy basketball projections."
    )
    parser.add_argument(
        "--season",
        help="Season to fetch (e.g., 2025-26). Currently fetches current season from NBA API.",
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        help="Input file path (skip fetching, trim existing file)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/nba_schedule.json"),
        help="Output file path (default: data/nba_schedule.json)",
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
    else:
        full_schedule = fetch_nba_schedule()
    
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
    
    print(f"Saved trimmed schedule: {args.output}")
    print(f"  {game_count} games, {trimmed_size:,} bytes ({trimmed_size/1024:.1f} KB)")
    
    # Show sample
    if game_count > 0:
        print(f"\nSample games:")
        for g in trimmed["games"][:3]:
            print(f"  {g['date'][:10]}: {g['away']} @ {g['home']}")


if __name__ == "__main__":
    main()
