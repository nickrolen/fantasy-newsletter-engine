#!/usr/bin/env python3
"""
backfill_trades.py

One-time script to re-fetch trade details from Yahoo Fantasy API and rebuild
all_trades.json with accurate player information.

The original pull_historical_data.py failed to parse player names from the
Yahoo API response. This script uses the proven parsing pattern from
sync_transactions.py to correctly extract:
  - Player names for each side of the trade
  - Source and destination teams/managers

Usage:
    python scripts/backfill_trades.py                   # Fetch all seasons
    python scripts/backfill_trades.py --season 2024-25  # Fetch one season
    python scripts/backfill_trades.py --dry-run          # Preview without saving

Requirements:
    - yahoo_oauth + yahoo_fantasy_api installed
    - oauth2.json in project root with valid credentials

Output:
    Overwrites data/historical/all_trades.json
"""

import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import (
    HISTORICAL_LEAGUE_KEYS, MANAGER_ALIASES, YAHOO_GAME_CODE, CURRENT_SEASON,
)


# ---------- CONFIGURATION ----------

# Historical only (exclude current season -- trades tracked in TRADES.json)
LEAGUE_KEYS = {k: v for k, v in HISTORICAL_LEAGUE_KEYS.items() if k != CURRENT_SEASON}

OUTPUT_FILE = os.path.join("data", "historical", "all_trades.json")


# ---------- HELPERS ----------

def strip_accents(text: str) -> str:
    """Return ASCII-only version of a name."""
    if not isinstance(text, str):
        return str(text)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def normalize_manager(name: str) -> str:
    """Normalize manager name to canonical form."""
    if not name:
        return "Unknown"
    name_lower = name.lower().strip()
    for alias, canonical in MANAGER_ALIASES.items():
        if alias in name_lower:
            return canonical
    return name.title()


def resolve_manager_from_team_key(team_key: str, teams: dict) -> str:
    """Look up manager name from a Yahoo team key using the teams dict."""
    if not team_key:
        return ""
    team_info = teams.get(team_key, {})
    return team_info.get("manager", "")


def resolve_manager_from_team_name(team_name: str, teams: dict) -> str:
    """Look up manager name from a team display name."""
    if not team_name:
        return ""
    for _key, info in teams.items():
        if info.get("team_name", "") == team_name:
            return info.get("manager", "")
    # Fallback: try alias matching on the team name itself
    return normalize_manager(team_name)


# ---------- CORE: FETCH AND PARSE TRADES ----------

def fetch_trades_for_season(oauth, season: str, league_key: str, teams: dict) -> list:
    """
    Fetch all trade transactions for a season from Yahoo API.

    Uses the proven parsing pattern from sync_transactions.py:
      players_dict structure: {'0': {'player': [[info_dicts...], {transaction_data}]}, 'count': N}

    Returns a list of trade dicts, each with:
      season, timestamp, date, trader_team, tradee_team, trader_manager, tradee_manager,
      players: [{player_name, from_team, to_team, from_manager, to_manager}]
    """
    trades = []

    try:
        lg = yfa.League(oauth, league_key)
    except Exception as e:
        print(f"    ERROR: Could not connect to league {league_key}: {e}")
        return trades

    # Fetch trade transactions
    raw_transactions = None
    try:
        raw_transactions = lg.transactions(tran_types="trade", count=100)
    except Exception:
        try:
            raw_transactions = lg.transactions("trade", 100)
        except Exception:
            pass

    if not raw_transactions:
        print(f"    No trades found")
        return trades

    print(f"    API returned {len(raw_transactions)} trade transactions")

    for txn in raw_transactions:
        timestamp = txn.get("timestamp", "")
        txn_type = txn.get("type", "").lower()

        if txn_type != "trade":
            continue

        # Parse date from timestamp
        trade_date = ""
        if timestamp:
            try:
                trade_date = datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                trade_date = ""

        # ---- Parse players using sync_transactions pattern ----
        players_in_trade = []
        players_dict = txn.get("players", {})

        for key, player_entry in players_dict.items():
            if key == "count" or not isinstance(player_entry, dict):
                continue

            player_data = player_entry.get("player", [])
            if not player_data or len(player_data) < 2:
                continue

            # Element 0: list of info dicts (contains name)
            # Element 1: dict with transaction_data
            info_list = player_data[0] if isinstance(player_data[0], list) else []
            txn_data_wrapper = player_data[1] if len(player_data) > 1 else {}

            # Extract player name
            player_name = "Unknown"
            for info_dict in info_list:
                if isinstance(info_dict, dict) and "name" in info_dict:
                    name_data = info_dict["name"]
                    if isinstance(name_data, dict):
                        player_name = strip_accents(name_data.get("full", "Unknown"))
                    break

            # Extract transaction_data
            txn_data_raw = txn_data_wrapper.get("transaction_data", [])
            if isinstance(txn_data_raw, list) and len(txn_data_raw) > 0:
                txn_data = txn_data_raw[0]
            elif isinstance(txn_data_raw, dict):
                if "0" in txn_data_raw:
                    txn_data = txn_data_raw["0"]
                else:
                    txn_data = txn_data_raw
            else:
                txn_data = {}

            # Source and destination
            source_team_name = txn_data.get("source_team_name", "")
            dest_team_name = txn_data.get("destination_team_name", "")
            source_team_key = txn_data.get("source_team_key", "")
            dest_team_key = txn_data.get("destination_team_key", "")

            # Resolve managers (prefer team_key lookup, fall back to name)
            from_manager = resolve_manager_from_team_key(source_team_key, teams)
            if not from_manager:
                from_manager = resolve_manager_from_team_name(source_team_name, teams)

            to_manager = resolve_manager_from_team_key(dest_team_key, teams)
            if not to_manager:
                to_manager = resolve_manager_from_team_name(dest_team_name, teams)

            players_in_trade.append({
                "player_name": player_name,
                "from_team": source_team_name,
                "to_team": dest_team_name,
                "from_manager": from_manager,
                "to_manager": to_manager,
            })

        # ---- Build trade record ----
        # Determine trader vs tradee from the first player's direction
        if players_in_trade:
            # "trader" = the team that initiated (source of first player listed)
            first = players_in_trade[0]
            trader_team = first["from_team"]
            trader_manager = first["from_manager"]
            tradee_team = first["to_team"]
            tradee_manager = first["to_manager"]
        else:
            # Fallback to top-level fields if player parsing failed
            trader_team = txn.get("trader_team_name", "")
            tradee_team = txn.get("tradee_team_name", "")
            trader_manager = resolve_manager_from_team_name(trader_team, teams)
            tradee_manager = resolve_manager_from_team_name(tradee_team, teams)

        trade = {
            "season": season,
            "timestamp": str(timestamp),
            "date": trade_date,
            "trader_team": trader_team,
            "tradee_team": tradee_team,
            "trader_manager": trader_manager,
            "tradee_manager": tradee_manager,
            "players": players_in_trade,
        }

        trades.append(trade)

        # Log it
        player_summary = []
        for p in players_in_trade:
            direction = f"{p['from_manager']} -> {p['to_manager']}"
            player_summary.append(f"{p['player_name']} ({direction})")
        summary_str = ", ".join(player_summary) if player_summary else "(no players parsed)"
        print(f"      [{trade_date}] {trader_manager} <-> {tradee_manager}: {summary_str}")

    return trades


# ---------- MAIN ----------

def main():
    parser = argparse.ArgumentParser(description="Backfill all_trades.json with player details from Yahoo API")
    parser.add_argument("--season", type=str, help="Process only this season (e.g., 2024-25)")
    parser.add_argument("--dry-run", action="store_true", help="Preview trades without saving to file")
    args = parser.parse_args()

    print("=" * 60)
    print("Trade History Backfill")
    print("=" * 60)

    # Load teams data for manager resolution
    teams_path = os.path.join("data", "historical", "all_teams.json")
    if not os.path.exists(teams_path):
        print(f"ERROR: {teams_path} not found. Run pull_historical_data.py first.")
        return

    with open(teams_path) as f:
        all_teams = json.load(f)

    # Authenticate
    print("\nAuthenticating with Yahoo...")
    oauth = OAuth2(None, None, from_file="oauth2.json")
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    print("  Authenticated!\n")

    # Determine seasons
    if args.season:
        if args.season not in LEAGUE_KEYS:
            print(f"ERROR: Season {args.season} not found")
            print(f"Available: {sorted(LEAGUE_KEYS.keys())}")
            return
        seasons = {args.season: LEAGUE_KEYS[args.season]}
    else:
        seasons = LEAGUE_KEYS

    # Fetch trades for each season
    all_trades = []
    for season, league_key in sorted(seasons.items()):
        print(f"  {season} ({league_key})...")
        teams = all_teams.get(season, {})
        if not teams:
            print(f"    WARNING: No team data for {season}, manager resolution may fail")

        season_trades = fetch_trades_for_season(oauth, season, league_key, teams)
        all_trades.extend(season_trades)
        print(f"    {len(season_trades)} trades\n")

        time.sleep(1)  # Rate limit courtesy

    # Summary
    print("=" * 60)
    print(f"Total trades found: {len(all_trades)}")

    trades_with_players = sum(1 for t in all_trades if t["players"])
    trades_without = len(all_trades) - trades_with_players
    print(f"  With player details: {trades_with_players}")
    print(f"  Without player details: {trades_without}")

    if trades_without > 0:
        print("\n  WARNING: Some trades have no player details.")
        print("  This may indicate the Yahoo API did not return player data for older seasons.")
        print("  You can manually fill in the 'players' arrays in the output file.")

    # Count players per trade
    total_players = sum(len(t["players"]) for t in all_trades)
    print(f"  Total players moved: {total_players}")

    # Show per-season breakdown
    print("\n  Per-season breakdown:")
    from collections import Counter
    season_counts = Counter(t["season"] for t in all_trades)
    for s in sorted(season_counts):
        count = season_counts[s]
        players = sum(len(t["players"]) for t in all_trades if t["season"] == s)
        print(f"    {s}: {count} trades, {players} players")

    # Save
    if args.dry_run:
        print("\n[DRY RUN] Skipping file save")
        print(f"Would write to: {OUTPUT_FILE}")
    else:
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

        # Back up existing file
        if os.path.exists(OUTPUT_FILE):
            backup = OUTPUT_FILE + ".bak"
            print(f"\n  Backing up existing file to {backup}")
            with open(OUTPUT_FILE) as f:
                existing = json.load(f)
            with open(backup, "w") as f:
                json.dump(existing, f, indent=2)

        with open(OUTPUT_FILE, "w") as f:
            json.dump(all_trades, f, indent=2)
        print(f"\n  Saved to {OUTPUT_FILE}")

    print("\nDone!")


if __name__ == "__main__":
    main()
