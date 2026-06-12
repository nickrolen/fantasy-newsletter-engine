#!/usr/bin/env python3
"""
sync_transactions.py

Pull recent transactions from Yahoo Fantasy API and:
1. Create waivers_week{N}.txt with transactions from that week ONLY
2. Update ROSTERS.json with ALL transactions (including after that week)

This script helps bridge the gap between when ROSTERS.json is generated
(from Sunday's lineups) and when the stats report is run (Monday).

Usage:
    python scripts/sync_transactions.py --week 13              # Process week 13 (dry run)
    python scripts/sync_transactions.py --week 13 --apply      # Apply changes to ROSTERS.json
"""

import argparse
import json
import datetime as dt
import sys
from pathlib import Path
from typing import Optional

from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import unicodedata

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import LEAGUE_KEY, TEAM_TO_MANAGER, YAHOO_GAME_CODE


# ---------- CONFIGURATION ----------

FANTASY_TEAM_TO_MANAGER = TEAM_TO_MANAGER

ROSTERS_JSON_PATH = "config/ROSTERS.json"
SCHEDULE_JSON_PATH = "config/SCHEDULE.json"
WAIVERS_PATH_TEMPLATE = "data/waivers_week{week}.txt"


# ---------- HELPERS ----------

def load_schedule(base_path: Path) -> dict:
    """Load SCHEDULE.json."""
    schedule_path = base_path / SCHEDULE_JSON_PATH
    if not schedule_path.exists():
        return {}
    with open(schedule_path) as f:
        return json.load(f)


def get_week_date_range(schedule: dict, week: int) -> tuple[dt.date, dt.date]:
    """Get start and end dates for a specific week from SCHEDULE.json."""
    for week_data in schedule.get("weeks", []):
        if week_data["week"] == week:
            start = dt.datetime.strptime(week_data["start_date"], "%Y-%m-%d").date()
            end = dt.datetime.strptime(week_data["end_date"], "%Y-%m-%d").date()
            return start, end
    raise ValueError(f"Week {week} not found in schedule")


def strip_accents(text: str) -> str:
    """Return ASCII-only version of a name."""
    if not isinstance(text, str):
        return text
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def get_league(oauth: OAuth2) -> yfa.League:
    """Return League object for your NBA league."""
    return yfa.League(oauth, LEAGUE_KEY)


def parse_transaction_date(date_str: str) -> dt.date:
    """Parse Yahoo's transaction date format."""
    if isinstance(date_str, (int, float)):
        return dt.datetime.fromtimestamp(date_str).date()
    try:
        return dt.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return dt.date.today()


class TransactionsAPIError(RuntimeError):
    """Raised when the Yahoo transactions API call fails.

    Caught at the top level so we can refuse to write a misleading
    "No waiver adds this week" artifact based on a silently-swallowed error.
    """


def get_recent_transactions(lg: yfa.League, since_date: Optional[dt.date] = None, until_date: Optional[dt.date] = None) -> list[dict]:
    """
    Fetch recent transactions from Yahoo.

    Args:
        lg: Yahoo League object
        since_date: Only include transactions on or after this date
        until_date: Only include transactions on or before this date

    Returns a list of transaction dicts with:
        - type: 'add', 'drop', or 'trade'
        - player_name: player involved
        - manager: manager who made the move
        - fantasy_team: team name
        - date: when it happened
        - details: raw transaction data

    Raises:
        TransactionsAPIError: if the Yahoo API call itself fails. We refuse
        to return an empty list silently because callers would then publish
        a false "no transactions" artifact.
    """
    transactions = []

    try:
        # Get transactions - increase count to get older transactions
        # API returns newest-first, so we need enough to reach back to our target week
        raw_transactions = lg.transactions(tran_types="add,drop,trade", count=250)
        
        # Debug: show what we got back
        print(f"  [DEBUG] API returned {len(raw_transactions) if raw_transactions else 0} raw transactions")
        
        # Show dates of first and last transactions for debugging
        if raw_transactions:
            first_ts = raw_transactions[0].get("timestamp")
            last_ts = raw_transactions[-1].get("timestamp")
            if first_ts:
                print(f"  [DEBUG] Newest transaction: {dt.datetime.fromtimestamp(int(first_ts)).date()}")
            if last_ts:
                print(f"  [DEBUG] Oldest transaction: {dt.datetime.fromtimestamp(int(last_ts)).date()}")
        
        for txn in raw_transactions:
            txn_type = txn.get("type", "").lower()
            txn_timestamp = txn.get("timestamp")
            
            if txn_timestamp:
                txn_date = dt.datetime.fromtimestamp(int(txn_timestamp)).date()
            else:
                txn_date = dt.date.today()
            
            # Skip if before our start cutoff
            if since_date and txn_date < since_date:
                continue
            
            # Skip if after our end cutoff
            if until_date and txn_date > until_date:
                continue
            
            # Process players in this transaction
            # Structure: players = {'0': {'player': [[info_dicts...], {transaction_data}]}, 'count': 1}
            players_dict = txn.get("players", {})
            
            for key, player_entry in players_dict.items():
                # Skip 'count' and other non-player keys
                if key == 'count' or not isinstance(player_entry, dict):
                    continue
                
                # Get the player data list
                player_data = player_entry.get('player', [])
                if not player_data or len(player_data) < 2:
                    print(f"  [DEBUG] Skipping - player_data too short: {player_data}")
                    continue
                
                # First element is a list of info dicts, second has transaction_data
                info_list = player_data[0] if isinstance(player_data[0], list) else []
                txn_data_wrapper = player_data[1] if len(player_data) > 1 else {}
                
                # Extract player name from info list
                player_name = "Unknown"
                for info_dict in info_list:
                    if isinstance(info_dict, dict) and 'name' in info_dict:
                        name_data = info_dict['name']
                        if isinstance(name_data, dict):
                            player_name = strip_accents(name_data.get('full', 'Unknown'))
                        break
                
                # Get transaction_data - handle both list and dict structures
                txn_data_raw = txn_data_wrapper.get('transaction_data', [])
                if isinstance(txn_data_raw, list) and len(txn_data_raw) > 0:
                    txn_data = txn_data_raw[0]
                elif isinstance(txn_data_raw, dict):
                    # Could be {'0': {...}} format
                    if '0' in txn_data_raw:
                        txn_data = txn_data_raw['0']
                    else:
                        txn_data = txn_data_raw
                else:
                    print(f"  [DEBUG] Could not parse txn_data_raw: {type(txn_data_raw)} = {txn_data_raw}")
                    txn_data = {}
                
                action_type = txn_data.get("type", "").lower()
                
                # Get team names directly from transaction_data (no need to look up)
                dest_team_name = txn_data.get("destination_team_name", "")
                source_team_name = txn_data.get("source_team_name", "")
                
                # Debug: show what we parsed for this player
                print(f"  [DEBUG] {txn_date} | {action_type.upper():5} | {player_name} | dest={dest_team_name} src={source_team_name}")
                
                # Determine the action and team
                if action_type == "add":
                    fantasy_team = dest_team_name
                    manager = FANTASY_TEAM_TO_MANAGER.get(fantasy_team, "")
                    transactions.append({
                        "type": "add",
                        "player_name": player_name,
                        "manager": manager,
                        "fantasy_team": fantasy_team,
                        "date": txn_date,
                        "timestamp": int(txn_timestamp) if txn_timestamp else 0,
                        "details": txn_data,
                    })
                elif action_type == "drop":
                    fantasy_team = source_team_name
                    manager = FANTASY_TEAM_TO_MANAGER.get(fantasy_team, "")
                    transactions.append({
                        "type": "drop",
                        "player_name": player_name,
                        "manager": manager,
                        "fantasy_team": fantasy_team,
                        "date": txn_date,
                        "timestamp": int(txn_timestamp) if txn_timestamp else 0,
                        "details": txn_data,
                    })
                elif action_type == "trade":
                    # For trades, we record both sides
                    if dest_team_name:
                        manager = FANTASY_TEAM_TO_MANAGER.get(dest_team_name, "")
                        transactions.append({
                            "type": "add",
                            "player_name": player_name,
                            "manager": manager,
                            "fantasy_team": dest_team_name,
                            "date": txn_date,
                            "timestamp": int(txn_timestamp) if txn_timestamp else 0,
                            "details": {"via": "trade"},
                        })
                    if source_team_name:
                        manager = FANTASY_TEAM_TO_MANAGER.get(source_team_name, "")
                        transactions.append({
                            "type": "drop",
                            "player_name": player_name,
                            "manager": manager,
                            "fantasy_team": source_team_name,
                            "date": txn_date,
                            "timestamp": int(txn_timestamp) if txn_timestamp else 0,
                            "details": {"via": "trade"},
                        })
    
    except Exception as e:
        print(f"ERROR fetching transactions: {e}")
        import traceback
        traceback.print_exc()
        # Re-raise so the caller does NOT write a false "no transactions"
        # waivers file based on a silently-swallowed API error.
        raise TransactionsAPIError(str(e)) from e

    # Debug: show how many we parsed
    if transactions:
        adds = len([t for t in transactions if t["type"] == "add"])
        drops = len([t for t in transactions if t["type"] == "drop"])
        print(f"  [DEBUG] Parsed {len(transactions)} transactions ({adds} adds, {drops} drops)")
    
    # Sort by timestamp, oldest first (so we apply in chronological order)
    # Using timestamp (Unix epoch) instead of date gives correct intra-day ordering
    # (e.g., add at 10am then drop at 11am, not reversed)
    transactions.sort(key=lambda x: x.get("timestamp", 0))
    
    return transactions


def load_rosters(base_path: Path) -> dict:
    """Load current ROSTERS.json."""
    rosters_path = base_path / ROSTERS_JSON_PATH
    
    if not rosters_path.exists():
        print(f"ERROR: {rosters_path} not found")
        return {}
    
    with open(rosters_path) as f:
        return json.load(f)


def save_rosters(rosters_data: dict, base_path: Path):
    """Save updated ROSTERS.json."""
    rosters_path = base_path / ROSTERS_JSON_PATH
    
    with open(rosters_path, 'w') as f:
        json.dump(rosters_data, f, indent=2)


def write_waivers_file(transactions: list[dict], week: int, base_path: Path,
                       dry_run: bool = False):
    """
    Write waivers_week{N}.txt with the week's waiver ADDS only.

    Note: We only track adds in the waivers file (for newsletter purposes).
    Drops are handled separately when updating ROSTERS.json.

    Format:
        - [2026-01-13] Nick: Player Name

    In dry-run mode, the file is NOT written; the would-be contents are
    printed to stdout so the operator can preview them.
    """
    waivers_path = base_path / WAIVERS_PATH_TEMPLATE.format(week=week)

    adds = [t for t in transactions if t["type"] == "add"]

    lines = []
    lines.append(f"# Waiver Adds for Week {week}")
    lines.append(f"# Generated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    if adds:
        for t in adds:
            via = t["details"].get("via", "")
            via_str = f" (via {via})" if via else ""
            lines.append(f"- [{t['date']}] {t['manager']}: {t['player_name']}{via_str}")
        lines.append("")
    else:
        lines.append("No waiver adds this week.")
        lines.append("")

    if dry_run:
        print(f"[DRY RUN] Would write {waivers_path}:")
        for line in lines:
            print(f"  | {line}")
        return

    with open(waivers_path, 'w') as f:
        f.write("\n".join(lines))

    print(f"Yes Wrote {waivers_path}")


def apply_transactions(rosters_data: dict, transactions: list[dict]) -> tuple[dict, list[str]]:
    """
    Apply transactions to rosters data.
    
    Returns:
        - Updated rosters_data
        - List of changes made (for logging)
    """
    rosters = rosters_data.get("rosters", {})
    changes = []
    
    for txn in transactions:
        manager = txn["manager"]
        player_name = txn["player_name"]
        txn_type = txn["type"]
        txn_date = txn["date"]
        
        if not manager or manager not in rosters:
            continue
        
        current_roster = rosters[manager]
        
        if txn_type == "add":
            if player_name not in current_roster:
                current_roster.append(player_name)
                current_roster.sort()
                changes.append(f"[{txn_date}] {manager}: +{player_name}")
            else:
                changes.append(f"[{txn_date}] {manager}: +{player_name} (already on roster, skipped)")
        
        elif txn_type == "drop":
            if player_name in current_roster:
                current_roster.remove(player_name)
                changes.append(f"[{txn_date}] {manager}: -{player_name}")
            else:
                changes.append(f"[{txn_date}] {manager}: -{player_name} (not on roster, skipped)")
    
    rosters_data["rosters"] = rosters
    rosters_data["_last_sync"] = dt.datetime.now().isoformat()
    
    return rosters_data, changes


def main():
    parser = argparse.ArgumentParser(
        description="Sync Yahoo Fantasy transactions to ROSTERS.json and create waivers file"
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default=".",
        help="Base path to project directory",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually apply changes to ROSTERS.json (default: dry run)",
    )
    parser.add_argument(
        "--week",
        type=int,
        required=True,
        help="Fantasy week number to process (required)",
    )
    
    args = parser.parse_args()
    base_path = Path(args.base_path)
    
    # Load schedule to get week date ranges
    schedule = load_schedule(base_path)
    if not schedule:
        print("ERROR: Could not load SCHEDULE.json")
        return 1
    
    try:
        week_start, week_end = get_week_date_range(schedule, args.week)
        print(f"Week {args.week}: {week_start} to {week_end}")
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    
    # Connect to Yahoo
    print("Connecting to Yahoo Fantasy API...")
    oauth = OAuth2(None, None, from_file="oauth2.json")
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    
    lg = get_league(oauth)
    
    # ========================================
    # PART 1: Get transactions for THIS WEEK ONLY (for waivers file)
    # ========================================
    print(f"\nFetching transactions for Week {args.week} only ({week_start} to {week_end})...")
    try:
        week_transactions = get_recent_transactions(lg, since_date=week_start, until_date=week_end)
    except TransactionsAPIError as e:
        print(f"ERROR: Yahoo API call failed: {e}")
        print(
            "Waivers file NOT written to prevent a false "
            "'no transactions' artifact from being published in the newsletter."
        )
        return 2

    if week_transactions:
        print(f"Found {len(week_transactions)} transaction(s) in Week {args.week}:")
        adds = [t for t in week_transactions if t["type"] == "add"]
        drops = [t for t in week_transactions if t["type"] == "drop"]
        
        if adds:
            print("\n  ADDS:")
            for t in adds:
                via = t["details"].get("via", "")
                via_str = f" (via {via})" if via else ""
                print(f"    [{t['date']}] {t['manager']}: +{t['player_name']}{via_str}")
        
        if drops:
            print("\n  DROPS:")
            for t in drops:
                via = t["details"].get("via", "")
                via_str = f" (via {via})" if via else ""
                print(f"    [{t['date']}] {t['manager']}: -{t['player_name']}{via_str}")
    else:
        print(f"No transactions found in Week {args.week}.")
    
    # Write waivers file (skipped in dry-run mode; dry_run prints contents only)
    write_waivers_file(week_transactions, args.week, base_path, dry_run=not args.apply)

    # ========================================
    # PART 2: Get ALL transactions since week start (for ROSTERS.json)
    # This includes any transactions made after the week ended
    # ========================================
    print(f"\n{'=' * 50}")
    print("Fetching ALL transactions since week start (for ROSTERS.json)...")
    try:
        all_transactions = get_recent_transactions(lg, since_date=week_start, until_date=None)
    except TransactionsAPIError as e:
        print(f"ERROR: Yahoo API call failed on second fetch: {e}")
        print("ROSTERS.json NOT modified.")
        return 2
    
    # Check if there are transactions AFTER the week
    post_week_transactions = [t for t in all_transactions if t["date"] > week_end]
    if post_week_transactions:
        print(f"\nNote: Found {len(post_week_transactions)} transaction(s) AFTER Week {args.week}:")
        for t in post_week_transactions:
            sign = "+" if t["type"] == "add" else "-"
            print(f"    [{t['date']}] {t['manager']}: {sign}{t['player_name']}")
    
    # Load and update rosters
    rosters_data = load_rosters(base_path)
    
    if not rosters_data:
        return 1
    
    gen_week = rosters_data.get("_generated_from_week", "?")
    print(f"\nCurrent ROSTERS.json generated from week {gen_week}")
    
    updated_rosters, changes = apply_transactions(rosters_data, all_transactions)
    
    if not changes:
        print("\nNo changes to apply to ROSTERS.json.")
        return 0
    
    print(f"\nChanges to apply to ROSTERS.json ({len(changes)}):")
    for change in changes:
        print(f"  {change}")
    
    if args.apply:
        save_rosters(updated_rosters, base_path)
        print(f"\nYes ROSTERS.json updated successfully!")
    else:
        print(f"\n[DRY RUN] Run with --apply to save changes to ROSTERS.json")
    
    # Show final roster counts
    print("\nRoster counts:")
    for manager, players in updated_rosters.get("rosters", {}).items():
        print(f"  {manager}: {len(players)} players")
    
    return 0


if __name__ == "__main__":
    exit(main())
