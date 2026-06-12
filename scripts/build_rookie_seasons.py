#!/usr/bin/env python3
"""
build_rookie_seasons.py

One-time script to build config/ROOKIE_SEASONS.json by looking up NBA debut
seasons for all players in the dataset via Basketball Reference.

Usage:
    python scripts/build_rookie_seasons.py              # First time (full build)
    python scripts/build_rookie_seasons.py --dry-run    # Preview without requests
    python scripts/build_rookie_seasons.py --update     # Only look up new players
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = Path(__file__).parent.parent
ROOKIE_SEASONS_FILE = PROJECT_ROOT / "config" / "ROOKIE_SEASONS.json"
HISTORICAL_PLAYERLOG_FILE = PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
PLAYERLOG_FILE = PROJECT_ROOT / "data" / "PLAYERLOG.xlsx"

# Rate limit: seconds between requests to Basketball Reference
RATE_LIMIT_SECONDS = 3.0


def load_existing_rookie_seasons() -> dict:
    """Load existing ROOKIE_SEASONS.json if it exists."""
    if ROOKIE_SEASONS_FILE.exists():
        with open(ROOKIE_SEASONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_all_player_names() -> list:
    """Extract all unique player names from historical + current playerlog."""
    names = set()

    # Historical playerlog (JSON)
    if HISTORICAL_PLAYERLOG_FILE.exists():
        with open(HISTORICAL_PLAYERLOG_FILE, "r", encoding="utf-8") as f:
            historical = json.load(f)
        for row in historical:
            name = row.get("player_name", "").strip()
            if name:
                names.add(name)
        print(f"  Loaded {len(historical)} rows from HISTORICAL_PLAYERLOG.json")
    else:
        print(f"  WARNING: {HISTORICAL_PLAYERLOG_FILE} not found -- using current season only")

    # Current season playerlog (Excel)
    if PLAYERLOG_FILE.exists():
        import pandas as pd
        df = pd.read_excel(PLAYERLOG_FILE)
        if "player_name" in df.columns:
            current_names = df["player_name"].dropna().str.strip().unique()
            names.update(current_names)
            print(f"  Loaded {len(current_names)} unique players from PLAYERLOG.xlsx")
    else:
        print(f"  WARNING: {PLAYERLOG_FILE} not found")

    result = sorted(names)
    print(f"  Total unique players: {len(result)}")
    return result


def normalize_season_format(season_str: str) -> str:
    """
    Normalize a season string to 'YYYY-YY' format.

    Examples:
        '2025-26' -> '2025-26'
        '2025-2026' -> '2025-26'
        '2024-25 NBA' -> '2024-25'
    """
    # Strip extra text
    season_str = season_str.strip()
    # Match YYYY-YYYY or YYYY-YY
    match = re.match(r"(\d{4})-(\d{2,4})", season_str)
    if match:
        start = match.group(1)
        end = match.group(2)
        if len(end) == 4:
            end = end[2:]
        return f"{start}-{end}"
    return season_str


def lookup_debut_season(player_name: str) -> str | None:
    """
    Look up a player's NBA debut season from Basketball Reference.

    Returns season in 'YYYY-YY' format, or None if not found.
    """
    import requests
    from bs4 import BeautifulSoup

    # Search Basketball Reference
    search_url = f"https://www.basketball-reference.com/search/search.fcgi?search={quote(player_name)}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(search_url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"    ERROR: Request failed for '{player_name}': {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Check if we were redirected directly to a player page
    # (happens when search has an exact match)
    if "/players/" in resp.url and "/search/" not in resp.url:
        return _extract_debut_from_player_page(soup, player_name)

    # Otherwise parse search results
    search_results = soup.select("div.search-item-name")
    if not search_results:
        # Try the search results table
        search_results = soup.select("#players .search-item-name")

    if not search_results:
        print(f"    WARNING: No search results for '{player_name}'")
        return None

    # Find the best matching player link
    for item in search_results:
        link = item.find("a")
        if link and "/players/" in link.get("href", ""):
            player_url = "https://www.basketball-reference.com" + link["href"]
            # Follow the link to the player page
            time.sleep(RATE_LIMIT_SECONDS)
            try:
                resp2 = requests.get(player_url, headers=headers, timeout=15)
                resp2.raise_for_status()
                soup2 = BeautifulSoup(resp2.text, "html.parser")
                return _extract_debut_from_player_page(soup2, player_name)
            except Exception as e:
                print(f"    ERROR: Failed to load player page for '{player_name}': {e}")
                return None

    print(f"    WARNING: No player link found for '{player_name}'")
    return None


def _extract_debut_from_player_page(soup, player_name: str) -> str | None:
    """Extract debut season from a Basketball Reference player page."""
    # Method 1: Look for 'NBA Debut' in the info box
    info_items = soup.select("#info p, #meta p")
    for p in info_items:
        text = p.get_text()
        if "NBA Debut" in text or "Debut" in text:
            # Extract date, convert to season
            match = re.search(r"(\w+ \d{1,2}, (\d{4}))", text)
            if match:
                year = int(match.group(2))
                # NBA season: if debut month is Oct-Dec, season is YYYY-(YY+1)
                # If Jan-Jun, season is (YYYY-1)-YY
                month_match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)", text)
                if month_match:
                    month = month_match.group(1)
                    if month in ("October", "November", "December"):
                        return f"{year}-{str(year + 1)[2:]}"
                    else:
                        return f"{year - 1}-{str(year)[2:]}"
                # Default: assume Oct-Dec
                return f"{year}-{str(year + 1)[2:]}"

    # Method 2: Find first row in career stats table (per_game or totals)
    for table_id in ["per_game", "totals", "per_minute"]:
        table = soup.find("table", id=table_id)
        if table:
            tbody = table.find("tbody")
            if tbody:
                rows = tbody.find_all("tr", class_=lambda c: c != "thead")
                for row in rows:
                    th = row.find("th", {"data-stat": "season"})
                    if th:
                        season_text = th.get_text().strip()
                        if re.match(r"\d{4}-\d{2}", season_text):
                            return normalize_season_format(season_text)

    print(f"    WARNING: Could not extract debut for '{player_name}'")
    return None


def save_rookie_seasons(data: dict) -> None:
    """Save ROOKIE_SEASONS.json."""
    # Ensure directory exists
    ROOKIE_SEASONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ROOKIE_SEASONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    print(f"\nSaved {len(data)} entries to {ROOKIE_SEASONS_FILE}")


def main():
    parser = argparse.ArgumentParser(
        description="Build ROOKIE_SEASONS.json from Basketball Reference lookups"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be looked up without making requests"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="Only look up players not already in the file"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("BUILD ROOKIE SEASONS")
    print("=" * 60)

    # Load existing data
    existing = load_existing_rookie_seasons()
    print(f"Existing entries: {len(existing)}")

    # Get all player names
    print("\nCollecting player names...")
    all_names = get_all_player_names()

    # Determine which players to look up
    if args.update:
        to_lookup = [n for n in all_names if n not in existing]
        print(f"\nUpdate mode: {len(to_lookup)} new players to look up "
              f"({len(all_names) - len(to_lookup)} already in file)")
    else:
        to_lookup = all_names
        print(f"\nFull build: {len(to_lookup)} players to look up")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        for name in to_lookup:
            status = "(already in file)" if name in existing else "(NEW)"
            print(f"  Would look up: {name} {status}")
        print(f"\nTotal requests that would be made: {len(to_lookup)}")
        est_time = len(to_lookup) * RATE_LIMIT_SECONDS
        print(f"Estimated time: {est_time / 60:.1f} minutes")
        return

    if not to_lookup:
        print("No players to look up. Done!")
        return

    # Start lookups
    result = dict(existing)  # Start with existing data
    failed = []
    total = len(to_lookup)

    print(f"\nStarting lookups ({total} players, ~{total * RATE_LIMIT_SECONDS / 60:.1f} min)...")
    print("-" * 60)

    for i, name in enumerate(to_lookup, 1):
        print(f"  [{i}/{total}] Looking up: {name}...", end=" ", flush=True)
        debut = lookup_debut_season(name)

        if debut:
            result[name] = debut
            print(f"-> {debut}")
        else:
            failed.append(name)
            print("-> FAILED")

        # Rate limit
        if i < total:
            time.sleep(RATE_LIMIT_SECONDS)

        # Save periodically (every 25 players)
        if i % 25 == 0:
            save_rookie_seasons(result)
            print(f"  (checkpoint saved: {len(result)} entries)")

    # Final save
    save_rookie_seasons(result)

    # Report
    print("\n" + "=" * 60)
    print(f"COMPLETE: {len(result)} entries saved")
    if failed:
        print(f"\nFAILED LOOKUPS ({len(failed)}) -- needs manual review:")
        for name in failed:
            print(f"  - {name}")
        print("\nTo add manually, edit config/ROOKIE_SEASONS.json:")
        print('  "Player Name": "YYYY-YY"')


if __name__ == "__main__":
    main()
