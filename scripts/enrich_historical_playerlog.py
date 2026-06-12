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

Data source: nba_api LeagueGameLog (player-level), 1 API call per season.
Handles mid-season trades automatically (NBA API returns correct team per game).

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
                print(f"FAILED after {max_retries} attempts: {e}")
                return []

    if df is None or df.empty:
        print("empty response")
        return []

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
        games = fetch_season_game_logs(season_key)
        if not games:
            print(f"    WARNING: No data for {season_key}, skipping")
            continue

        for g in games:
            norm_name = normalize_name(g["player_name"])
            name_map[norm_name] = g["player_name"]

            player_game_lookup[norm_name][g["date"]] = {
                "team": g["team"],
                "opponent": g["opponent"],
            }

        # Rate limit between seasons
        if i < len(season_keys) - 1:
            print(f"    (waiting {delay_between:.0f}s before next season...)")
            time.sleep(delay_between)

    return player_game_lookup, name_map


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
) -> tuple[list[dict], dict]:
    """
    Enrich HISTORICAL_PLAYERLOG rows with nba_team, nba_opponent, had_game, is_injured.

    Args:
        rows: The raw HISTORICAL_PLAYERLOG data (list of dicts).
        player_game_lookup: {normalized_name: {date: {team, opponent}}} from NBA API.
        name_map: {normalized_name: original_nba_api_name} for debugging.
        team_schedule: {date: {team: opponent}} fallback lookup.
        target_seasons: If provided, only enrich rows from these seasons (set of season_key strings).

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

    # Also build a set of all teams each player has been on (from NBA data)
    # for the team_schedule fallback
    player_teams_by_season = defaultdict(lambda: defaultdict(set))
    for norm_name, date_map in player_game_lookup.items():
        for date_str, info in date_map.items():
            # Extract season from date (rough: year of October+ = first year of season)
            year = int(date_str[:4])
            month = int(date_str[5:7])
            if month >= 10:
                season_start = year
            else:
                season_start = year - 1
            season_key = f"{season_start}-{str(season_start + 1)[2:]}"
            player_teams_by_season[norm_name][season_key].add(info["team"])

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
                row["nba_team"] = date_info["team"]
                row["nba_opponent"] = date_info["opponent"]
                row["had_game"] = True
                row["is_injured"] = (fp == 0.0)
                if row["is_injured"]:
                    stats["injury_flagged"] += 1
                stats["matched_by_player"] += 1
            else:
                # Player is in our NBA data, but didn't play on this date.
                # Check if their TEAM had a game (player might have been a DNP
                # that didn't appear in the game log at all).
                teams_this_season = player_teams_by_season.get(lookup_name, {}).get(season_key, set())

                found_team_game = False
                for team in teams_this_season:
                    if date_str in team_schedule and team in team_schedule[date_str]:
                        opponent = team_schedule[date_str][team]
                        row["nba_team"] = team
                        row["nba_opponent"] = opponent
                        row["had_game"] = True
                        row["is_injured"] = (fp == 0.0)
                        if row["is_injured"]:
                            stats["injury_flagged"] += 1
                        stats["matched_by_team_schedule"] += 1
                        found_team_game = True
                        break

                if not found_team_game:
                    # Player's team had no game this day -> off day
                    # Still set nba_team if we know it for this season
                    if teams_this_season:
                        row["nba_team"] = sorted(teams_this_season)[-1]  # Most recent team
                    else:
                        row["nba_team"] = ""
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

    stats["unresolved_names"] = sorted(unresolved_names)
    return rows, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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

    # --- Enrich ---
    print("Enriching rows...")
    rows, stats = enrich_rows(rows, player_game_lookup, name_map, team_schedule, target_seasons)
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

    # --- Save ---
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
        with open(HIST_FILE, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
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

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
