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

from modules.data_loader import LEAGUE_KEY, TEAM_TO_MANAGER, YAHOO_GAME_CODE, manager_for_team
from modules.league_clock import league_date_of_timestamp, league_now


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
    with open(schedule_path, encoding="utf-8") as f:
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
    """Parse Yahoo's transaction date format. A Unix timestamp is dated on the
    league's clock (modules/league_clock.py), never the machine's. Anything
    unparseable raises: it used to become "today", which filed an undated
    transaction under whatever week the sync happened to run in."""
    if isinstance(date_str, (int, float)):
        return league_date_of_timestamp(date_str)
    try:
        return dt.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ValueError(f"unparseable Yahoo transaction date: {date_str!r}") from None


class TransactionsAPIError(RuntimeError):
    """Raised when the Yahoo transactions API call fails.

    Caught at the top level so we can refuse to write a misleading
    "No waiver adds this week" artifact based on a silently-swallowed error.
    """


YAHOO_FETCH_COUNT = 250


def fetch_raw(lg) -> list:
    """Yahoo's transaction log as Yahoo returns it, newest first: ONE call of
    up to YAHOO_FETCH_COUNT rows. The nightly sync (step 1c) parses this once
    for the transaction log and once for the adds files and rosters. A full
    page may have cut older transactions off: transaction_log.sync refuses
    one that does not overlap what is already logged (a possible gap).
    Raises TransactionsAPIError."""
    try:
        raw = lg.transactions(tran_types="add,drop,trade", count=YAHOO_FETCH_COUNT)
    except Exception as e:
        raise TransactionsAPIError(str(e)) from e
    return list(raw or [])


def get_recent_transactions(lg: yfa.League, since_date: Optional[dt.date] = None, until_date: Optional[dt.date] = None,
                            raw: Optional[list] = None) -> list[dict]:
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
        raw_transactions = raw if raw is not None else fetch_raw(lg)
        
        # Debug: show what we got back
        print(f"  [DEBUG] API returned {len(raw_transactions) if raw_transactions else 0} raw transactions")
        
        # Show dates of first and last transactions for debugging
        if raw_transactions:
            first_ts = raw_transactions[0].get("timestamp")
            last_ts = raw_transactions[-1].get("timestamp")
            if first_ts:
                print(f"  [DEBUG] Newest transaction: {league_date_of_timestamp(first_ts)}")
            if last_ts:
                print(f"  [DEBUG] Oldest transaction: {league_date_of_timestamp(last_ts)}")
        
        for txn in raw_transactions:
            txn_type = txn.get("type", "").lower()
            txn_timestamp = txn.get("timestamp")
            
            if not txn_timestamp:
                # Used to be dated "today". Refuse instead: an undated move
                # cannot be put in a fantasy week without guessing.
                raise TransactionsAPIError(
                    f"Yahoo transaction {txn.get('transaction_key', '?')} has no timestamp; "
                    "refusing to guess its date")
            txn_date = league_date_of_timestamp(txn_timestamp)
            
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
                
                # Determine the action and team (by KEY first: a key survives
                # a rename, data_loader.manager_for_team)
                dest_key = txn_data.get("destination_team_key")
                source_key = txn_data.get("source_team_key")
                if action_type == "add":
                    fantasy_team = dest_team_name
                    manager = manager_for_team(fantasy_team, dest_key)
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
                    manager = manager_for_team(fantasy_team, source_key)
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
                        manager = manager_for_team(dest_team_name, dest_key)
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
                        manager = manager_for_team(source_team_name, source_key)
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
    
    with open(rosters_path, encoding="utf-8") as f:
        return json.load(f)


def save_rosters(rosters_data: dict, base_path: Path):
    """Save updated ROSTERS.json."""
    rosters_path = base_path / ROSTERS_JSON_PATH
    
    with open(rosters_path, 'w', encoding="utf-8") as f:
        json.dump(rosters_data, f, indent=2)


def write_waivers_file(transactions: list[dict], week: int, base_path: Path,
                       dry_run: bool = False, partial: bool = False, applied=()):
    """
    Write waivers_week{N}.txt with the week's waiver ADDS only.

    Note: We only track adds in the waivers file (for newsletter purposes).
    Drops are handled separately when updating ROSTERS.json.

    Format:
        - [2026-01-13] Nick: Player Name

    In dry-run mode, the file is NOT written; the would-be contents are
    printed to stdout so the operator can preview them.

    `transactions` have the commissioner's rulings already applied
    (transaction_rulings.apply_to_transactions); `applied` are those rulings,
    recorded in the file's header so a reader knows the voided adds are
    missing on purpose.
    """
    waivers_path = base_path / WAIVERS_PATH_TEMPLATE.format(week=week)

    adds = [t for t in transactions if t["type"] == "add"]

    lines = []
    lines.append(f"# Waiver Adds for Week {week}")
    lines.append(f"# Generated: {league_now().strftime('%Y-%m-%d %H:%M %Z')}"
                 f"{' (PARTIAL -- week still in progress)' if partial else ''}")
    from modules.transaction_rulings import applied_lines, claim_mark, made_in_mark
    lines.extend(applied_lines(list(applied)))
    lines.append("")

    if partial:
        lines.append("# Adds made so far in a week that has not finished. The")
        lines.append("# newsletter reads this to report each team's remaining")
        lines.append("# adds. It is overwritten by the full file when this")
        lines.append("# week is itself synced.")
        lines.append("")

    if adds:
        for t in adds:
            via = t["details"].get("via", "")
            via_str = f" (via {via})" if via else ""
            # A group-chat claim from an earlier week (a claim_week ruling):
            # listed here, in its Yahoo week, counted in its claim week.
            claim = claim_mark(t["claim_week"]) if t.get("claim_week") else ""
            # An effective-date add listed in its effective week but made in
            # an earlier one, whose budget it uses (Nick, 11-01).
            if t.get("made_on"):
                claim += made_in_mark(t["made_on"], week, load_schedule(base_path))
            lines.append(f"- [{t['date']}] {t['manager']}: {t['player_name']}{via_str}{claim}")
        lines.append("")
    else:
        lines.append("No waiver adds this week.")
        lines.append("")

    if dry_run:
        print(f"[DRY RUN] Would write {waivers_path}:")
        for line in lines:
            print(f"  | {line}")
        return

    with open(waivers_path, 'w', encoding="utf-8") as f:
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
    rosters_data["_last_sync"] = league_now().isoformat(timespec="seconds")
    
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
        required=False,
        help="Fantasy week number to process (required unless --il-only)",
    )
    parser.add_argument(
        "--nightly",
        action="store_true",
        help="the nightly run's sync (step 1c): append Yahoo's log to "
             "data/transaction_log.jsonl, write the CURRENT week's partial adds "
             "file, refresh ROSTERS.json (checked against Yahoo's live rosters) "
             "and data/IL_SLOTS.json. Never rewrites a finished week's adds file.",
    )
    parser.add_argument(
        "--il-only",
        action="store_true",
        help="only refresh data/IL_SLOTS.json (who sits in an IL slot now) from "
             "Yahoo's live rosters; ROSTERS.json and the waivers files are untouched",
    )
    
    args = parser.parse_args()
    base_path = Path(args.base_path)
    if args.il_only:
        return write_il_file(base_path)
    if args.nightly:
        try:
            nightly_sync(base_path)
        except Exception as e:                       # noqa: BLE001 -- a refusal, said plainly
            print(f"REFUSED: {type(e).__name__}: {e}")
            return 1
        return 0
    if args.week is None:
        parser.error("--week is required unless --il-only")
    
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

    # The commissioner's rulings (config/TRANSACTION_RULINGS.json): a voided
    # add is still in Yahoo's log, so without this every sync counted it
    # again. Validated before anything is written.
    from modules.transaction_rulings import load_rulings, apply_to_transactions, RulingError
    try:
        rulings = load_rulings(base_path)
    except (RulingError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1
    if rulings:
        print(f"Commissioner's rulings on file: {len(rulings)}")
    
    # ========================================
    # PART 1: Get transactions for THIS WEEK ONLY (for waivers file)
    # ========================================
    print(f"\nFetching transactions for Week {args.week} only ({week_start} to {week_end})...")
    try:
        # A day of slack before the week: an add Yahoo stamped the day before
        # its effective date (transaction_rulings) still has to be seen to be
        # moved into this week. apply_to_transactions cuts back to the week.
        week_transactions = get_recent_transactions(
            lg, since_date=week_start - dt.timedelta(days=1), until_date=week_end)
    except TransactionsAPIError as e:
        print(f"ERROR: Yahoo API call failed: {e}")
        print(
            "Waivers file NOT written to prevent a false "
            "'no transactions' artifact from being published in the newsletter."
        )
        return 2

    shown = [t for t in week_transactions if t["date"] >= week_start]   # not the slack day
    if shown:
        print(f"Found {len(shown)} transaction(s) in Week {args.week}:")
        adds = [t for t in shown if t["type"] == "add"]
        drops = [t for t in shown if t["type"] == "drop"]
        
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
    
    # Rulings dated in this week: each must match exactly one transaction.
    # They change counting and listing only; ROSTERS.json below still follows
    # Yahoo's log (a ruling does not undo a roster move unless one says so,
    # and none can yet -- transaction_rulings).
    try:
        week_counted, week_applied = apply_to_transactions(
            week_transactions, rulings, since=week_start, until=week_end)
    except RulingError as e:
        print(f"ERROR: {e}")
        print("Waivers file NOT written.")
        return 1

    # Write waivers file (skipped in dry-run mode; dry_run prints contents only)
    write_waivers_file(week_counted, args.week, base_path, dry_run=not args.apply,
                       applied=week_applied)

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

    # These belong to the week that just opened, and they are the only
    # record of it at newsletter time -- the newsletter is written on the
    # Monday morning, inside the free-add window, before any game tips.
    # They used to be printed to the console and thrown away, so nothing
    # downstream could say how many adds anyone had left.
    # Only week N+1's own transactions go in its file. Run for an older week
    # (--week 1 once week 3 has opened), an open-ended window put week 3's
    # adds into week 2's file too, where every reader raised on them (found
    # 2026-11-02). The last week of the schedule has no next week to cap at.
    try:
        next_end = get_week_date_range(schedule, args.week + 1)[1]
    except ValueError:
        next_end = None
    try:
        # From every transaction since the week opened, so an effective-date
        # ruling can move an add stamped inside the week into the next one.
        post_counted, post_applied = apply_to_transactions(
            all_transactions, rulings,
            since=week_end + dt.timedelta(days=1), until=next_end)
    except RulingError as e:
        print(f"ERROR: {e}")
        print(f"Partial waivers file for week {args.week + 1} and ROSTERS.json NOT written.")
        return 1
    write_waivers_file(post_counted, args.week + 1, base_path,
                       dry_run=not args.apply, partial=True, applied=post_applied)
    
    # Load and update rosters
    rosters_data = load_rosters(base_path)
    
    if not rosters_data:
        return 1
    
    gen_week = rosters_data.get("_generated_from_week", "?")
    print(f"\nCurrent ROSTERS.json generated from week {gen_week}")
    
    updated_rosters, changes = apply_transactions(rosters_data, all_transactions)
    
    if not changes:
        print("\nNo changes to apply to ROSTERS.json.")
        return write_il_file(base_path) if args.apply else 0
    
    print(f"\nChanges to apply to ROSTERS.json ({len(changes)}):")
    for change in changes:
        print(f"  {change}")
    
    if args.apply:
        save_rosters(updated_rosters, base_path)
        print(f"\nYes ROSTERS.json updated successfully!")
    else:
        print(f"\n[DRY RUN] Run with --apply to save changes to ROSTERS.json")
    
    if not args.apply:
        # Show final roster counts (no IL file is written on a dry run, so
        # active and IL cannot be told apart: say so rather than guess)
        print("\nRoster counts (dry run: IL slots not read):")
        for manager, players in updated_rosters.get("rosters", {}).items():
            print(f"  {manager}: {len(players)} players")
        return 0
    rc = write_il_file(base_path)
    if rc == 0:
        _print_roster_counts(updated_rosters.get("rosters", {}), base_path)
    return rc


def roster_count_lines(rosters: dict, il_slots: dict) -> list:
    """"Benton: 15 active, 1 IL" per manager (STATUS task 20c): the active
    roster and the IL slots counted apart, as the rules count them (rule 1:
    15 active, 2 IL). A player in an IL slot who is not on the roster raises."""
    from modules.data_loader import PlayerIndex
    out = []
    for manager, players in rosters.items():
        idx = PlayerIndex({n: n for n in players})
        il = list((il_slots or {}).get(manager) or [])
        stray = [n for n in il if idx.get(n) is None]
        if stray:
            raise ValueError(f"{manager}'s IL slot holds {stray}, who are not on his roster")
        out.append(f"{manager}: {len(players) - len(il)} active, {len(il)} IL")
    return out


def _print_roster_counts(rosters: dict, base_path: Path) -> None:
    il = json.loads((base_path / "data" / "IL_SLOTS.json").read_text(encoding="utf-8"))
    print("\nRoster counts:")
    for line in roster_count_lines(rosters, il.get("slots") or {}):
        print(f"  {line}")


# =============================================================================
# the nightly mode (step 1c)
# =============================================================================

class RosterMismatch(RuntimeError):
    """ROSTERS.json after the transactions is not Yahoo's live roster."""


def nightly_sync(base_path, *, run_id: str = None, now=None, raw=None, live=None,
                 echo=print) -> dict:
    """The nightly run's sync (design s.4 step 3; HANDOFF_STEP1C1 s.2):

      1. one read of Yahoo's transaction log, appended to
         data/transaction_log.jsonl (modules/transaction_log);
      2. THE CURRENT WEEK's partial adds file, data/waivers_week{N}.txt, as
         the --week N-1 sync writes it for N. A finished week's file is never
         written here (only the Monday --week N --apply run does that);
      3. ROSTERS.json: the transactions since the previous week opened,
         applied as the weekly sync applies them, then CHECKED against
         Yahoo's live rosters -- a difference raises and nothing is written;
      4. data/IL_SLOTS.json from the same live rosters.

    raw: Yahoo's transactions (tests); live: {manager: {"players", "il"}}
    (tests). Raises on any refusal; writes nothing before every check passed,
    except the transaction log, which only ever appends Yahoo's facts."""
    from modules import transaction_log as tlog
    from modules import roster_plan
    from modules.data_loader import PlayerIndex
    from modules.transaction_rulings import load_rulings, apply_to_transactions
    base_path = Path(base_path)
    now = now or league_now()
    today = now.date()
    schedule = load_schedule(base_path)
    if not schedule:
        raise RuntimeError("config/SCHEDULE.json is missing or empty")
    week = roster_plan.fantasy_week_on(schedule, today)
    week_start, week_end = get_week_date_range(schedule, week)
    if week_end < today:
        raise RuntimeError(f"week {week} ended {week_end}: the nightly sync never writes a "
                           "finished week's adds file")
    rulings = load_rulings(base_path)
    if raw is None:
        oauth = OAuth2(None, None, from_file=str(base_path / "oauth2.json"))
        if not oauth.token_is_valid():
            oauth.refresh_access_token()
        raw = fetch_raw(get_league(oauth))

    # 1. the log
    logged = tlog.sync(base_path, raw, manager_of=lambda name, key: manager_for_team(name, key),
                       week_of=lambda d: tlog.week_containing(schedule, d), rulings=rulings,
                       run_id=run_id, now=now, page_full=len(raw) >= YAHOO_FETCH_COUNT)
    echo(f"  transaction log: {logged['appended']} new, {logged['rulings_rows']} rulings row(s), "
         f"{logged['total']} logged")

    # 2. the current week's partial adds file
    parsed = get_recent_transactions(None, since_date=None, until_date=None, raw=raw)
    counted, applied = apply_to_transactions(parsed, rulings, since=week_start, until=week_end,
                                             echo=lambda *_: None)
    path = base_path / WAIVERS_PATH_TEMPLATE.format(week=week)

    # 3. ROSTERS.json: from the previous week's opening (Monday's run must
    # still see Sunday's moves), the weekly sync's own apply
    prev_start = week_start
    try:
        prev_start = get_week_date_range(schedule, week - 1)[0]
    except ValueError:
        pass
    since = [t for t in parsed if t["date"] >= prev_start]
    rosters_data = load_rosters(base_path)
    if not rosters_data:
        raise RuntimeError("config/ROSTERS.json is missing")
    updated, changes = apply_transactions(json.loads(json.dumps(rosters_data)), since)
    if live is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "check_rosters", Path(__file__).resolve().parent / "check_rosters.py")
        cr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cr)
        live = cr.live_rosters(base_path / "oauth2.json")
    diffs = []
    ros = updated.get("rosters", {})
    if sorted(ros) != sorted(live):
        diffs.append(f"managers {sorted(ros)} vs Yahoo {sorted(live)}")
    for m in sorted(set(ros) & set(live)):
        mine, yahoo = PlayerIndex({n: n for n in ros[m]}), PlayerIndex({n: n for n in live[m]["players"]})
        extra = [n for n in ros[m] if yahoo.get(n) is None]
        missing = [n for n in live[m]["players"] if mine.get(n) is None]
        if extra or missing:
            diffs.append(f"{m}: ROSTERS.json also has {extra}, Yahoo also has {missing}")
    if diffs:
        raise RosterMismatch("after the transactions, ROSTERS.json is not Yahoo's live roster -- "
                             + "; ".join(diffs) + ". Nothing was written but the transaction log; "
                             "run python scripts\\sync_transactions.py --week N --apply and check.")

    # every check passed: write
    write_waivers_file(counted, week, base_path, partial=True, applied=applied)
    save_rosters(updated, base_path)
    il = {m: v["il"] for m, v in live.items()}
    roster_plan.write_il_slots(base_path, il, week, now)
    counts = roster_count_lines(ros, il)
    for line in counts:
        echo(f"  {line}")
    return {"week": week, "log": logged, "adds_file": path.as_posix(), "roster_changes": changes,
            "il": {m: v for m, v in il.items() if v}, "counts": counts}


def write_il_file(base_path: Path) -> int:
    """data/IL_SLOTS.json: who sits in an IL slot right now, from Yahoo's live
    selected_position (check_rosters.live_il_names). The simulator's roster
    plan reads this file and nothing else, and refuses one from an earlier
    fantasy week -- so it is written on every --apply sync, changes or not.
    A failed fetch writes nothing and exits non-zero."""
    import importlib.util
    from modules import roster_plan
    spec = importlib.util.spec_from_file_location(
        "check_rosters", Path(__file__).resolve().parent / "check_rosters.py")
    cr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cr)
    try:
        slots = cr.live_il_names(base_path / "oauth2.json")
    except Exception as e:
        print(f"ERROR: could not read the live IL slots from Yahoo ({e}); "
              f"{roster_plan.IL_FILE} NOT written")
        return 2
    now = league_now()
    week = roster_plan.fantasy_week_on(load_schedule(base_path), now.date())
    path = roster_plan.write_il_slots(base_path, slots, week, now)
    on = {m: v for m, v in slots.items() if v}
    print(f"\nWrote {path} (fantasy week {week}): "
          + (", ".join(f"{m}: {', '.join(v)}" for m, v in sorted(on.items())) or "nobody on IL"))
    return 0


if __name__ == "__main__":
    exit(main())
