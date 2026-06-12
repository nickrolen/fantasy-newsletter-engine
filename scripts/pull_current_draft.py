"""
pull_current_draft.py

Pulls draft results for the current season (2025-26) from Yahoo Fantasy API
and patches all_drafts.json with real player names.

This is a targeted fix for the empty player names issue. The current season's
league object should support player_details() lookups, unlike historical ones.

Usage:
    python scripts/pull_current_draft.py                # Normal mode
    python scripts/pull_current_draft.py --debug        # Show raw API responses
    python scripts/pull_current_draft.py --dry-run      # Show results without saving

Requires:
    - oauth2.json in the working directory (Yahoo OAuth credentials)
    - pip install yahoo_oauth yahoo_fantasy_api
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path

from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import LEAGUE_KEY, CURRENT_SEASON, MANAGER_ALIASES, YAHOO_GAME_CODE

# =============================================================================
# CONFIGURATION (loaded from config/league_config.json via data_loader)
# =============================================================================

SEASON = CURRENT_SEASON

# Adjust these to match your local directory structure
BASE_DIR = Path(__file__).resolve().parent.parent
ALL_DRAFTS_PATH = BASE_DIR / "data" / "historical" / "all_drafts.json"

DEBUG = False


# =============================================================================
# HELPERS
# =============================================================================

def debug_print(label, obj):
    if DEBUG:
        print(f"  [DEBUG] {label}: {json.dumps(obj, indent=2, default=str)[:500]}")


def normalize_manager(name):
    if not name:
        return "Unknown"
    name_lower = name.lower().strip()
    for alias, canonical in MANAGER_ALIASES.items():
        if alias in name_lower:
            return canonical
    return name.title()


# =============================================================================
# EXTRACT
# =============================================================================

def extract_teams(lg):
    """Get team_key -> manager mapping."""
    teams = {}
    try:
        teams_data = lg.teams()
        debug_print("Raw teams() response", teams_data)

        for team_key, data in teams_data.items():
            manager_name = "Unknown"
            if "managers" in data:
                managers = data["managers"]
                if isinstance(managers, list) and len(managers) > 0:
                    mgr = managers[0]
                    if isinstance(mgr, dict) and "manager" in mgr:
                        manager_name = mgr["manager"].get("nickname", "Unknown")
                    elif isinstance(mgr, dict):
                        manager_name = mgr.get("nickname", "Unknown")

            teams[team_key] = normalize_manager(manager_name)
    except Exception as e:
        print(f"  ERROR extracting teams: {e}")
        import traceback
        traceback.print_exc()
    debug_print("Teams", teams)
    return teams


def extract_draft(lg, teams):
    """Extract draft results with player name resolution."""
    results = []

    try:
        draft_data = lg.draft_results()
        debug_print("Raw draft_results (first 2)", draft_data[:2] if draft_data else None)
        print(f"  Found {len(draft_data)} draft picks")

        # Collect player IDs for batch lookup
        # Yahoo API player_details() expects a list of integer IDs
        player_ids = []
        for pick in draft_data:
            dp = pick.get("draft_result", pick)
            pid = dp.get("player_id")
            if pid:
                player_ids.append(int(pid))

        print(f"  Found {len(player_ids)} player IDs to resolve")
        debug_print("First 5 player_ids", player_ids[:5])

        # Batch fetch player names (25 at a time per Yahoo API limits)
        player_names = {}  # player_id (int) -> name (str)
        if player_ids:
            for i in range(0, len(player_ids), 25):
                batch = player_ids[i:i + 25]
                try:
                    details = lg.player_details(batch)
                    debug_print(f"player_details batch {i // 25}", details[:1] if details else None)
                    for pd_entry in details:
                        pid = int(pd_entry.get("player_id", 0))
                        name = pd_entry.get("name", {})
                        if isinstance(name, dict):
                            full_name = name.get("full", "Unknown")
                        else:
                            full_name = str(name) if name else "Unknown"
                        player_names[pid] = full_name
                    time.sleep(0.3)
                except Exception as e:
                    print(f"  WARNING: Batch {i // 25} failed: {e}")
                    # Try individual lookups as fallback
                    for pid in batch:
                        try:
                            details = lg.player_details([pid])
                            if details:
                                pd_entry = details[0]
                                name = pd_entry.get("name", {})
                                full_name = name.get("full", "Unknown") if isinstance(name, dict) else str(name)
                                player_names[pid] = full_name
                        except Exception:
                            pass
                        time.sleep(0.2)

        resolved = sum(1 for v in player_names.values() if v != "Unknown")
        print(f"  Resolved {resolved}/{len(player_ids)} player names")

        # Build results
        for pick in draft_data:
            dp = pick.get("draft_result", pick)
            team_key = dp.get("team_key", "")
            player_id = int(dp.get("player_id", 0))
            player_key = dp.get("player_key", str(player_id))
            pick_num = dp.get("pick", 0)
            round_num = dp.get("round", 0)

            try:
                pick_num = int(pick_num)
            except (ValueError, TypeError):
                pick_num = 0
            try:
                round_num = int(round_num)
            except (ValueError, TypeError):
                round_num = 0

            results.append({
                "season": SEASON,
                "pick_number": pick_num,
                "round": round_num,
                "manager": teams.get(team_key, "Unknown"),
                "player_key": player_key,
                "player_name": player_names.get(player_id, "Unknown"),
            })

    except Exception as e:
        print(f"  ERROR extracting draft: {e}")
        import traceback
        traceback.print_exc()

    return results


# =============================================================================
# MAIN
# =============================================================================

def main():
    global DEBUG

    parser = argparse.ArgumentParser(description="Pull current season draft from Yahoo")
    parser.add_argument("--debug", action="store_true", help="Show raw API responses")
    parser.add_argument("--dry-run", action="store_true", help="Show results without saving")
    args = parser.parse_args()

    DEBUG = args.debug

    print("=" * 60)
    print(f"Pull Draft Results: {SEASON} ({LEAGUE_KEY})")
    print("=" * 60)
    if DEBUG:
        print("*** DEBUG MODE ***")
    print()

    # Authenticate
    print("Authenticating with Yahoo...")
    oauth = OAuth2(None, None, from_file="oauth2.json")
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    print("  Authenticated!")

    # Connect to league
    print(f"\nConnecting to league {LEAGUE_KEY}...")
    lg = yfa.League(oauth, LEAGUE_KEY)

    # Get teams
    print("Extracting team info...")
    teams = extract_teams(lg)
    if not teams:
        print("ERROR: Could not extract teams. Aborting.")
        return

    for tk, mgr in teams.items():
        print(f"  {tk} -> {mgr}")

    # Get draft
    print("\nExtracting draft results...")
    draft = extract_draft(lg, teams)

    if not draft:
        print("ERROR: No draft results returned. Aborting.")
        return

    # Show results
    unknown_count = sum(1 for d in draft if d["player_name"] == "Unknown")
    print(f"\nResults: {len(draft)} picks, {len(draft) - unknown_count} with names, {unknown_count} unknown")
    print()

    print("Draft results:")
    for d in draft:
        status = "OK" if d["player_name"] != "Unknown" else "MISSING"
        print(f"  R{d['round']:>2} P{d['pick_number']:>2}: {d['manager']:8s} -> {d['player_name']:30s} [{status}]")

    if args.dry_run:
        print("\n[DRY RUN] Not saving to file.")
        return

    if unknown_count == len(draft):
        print("\nWARNING: ALL player names are Unknown. API name resolution failed.")
        print("Try running with --debug to see raw API responses.")
        print("Not saving (would overwrite with same bad data).")
        return

    # Patch all_drafts.json
    print(f"\nPatching {ALL_DRAFTS_PATH}...")
    if ALL_DRAFTS_PATH.exists():
        with open(ALL_DRAFTS_PATH) as f:
            all_drafts = json.load(f)

        # Remove any existing 2025-26 entries
        before = len(all_drafts)
        all_drafts = [d for d in all_drafts if d.get("season") != SEASON]
        removed = before - len(all_drafts)
        if removed:
            print(f"  Removed {removed} existing {SEASON} entries")

        # Append new results
        all_drafts.extend(draft)
        print(f"  Added {len(draft)} new {SEASON} entries")

        with open(ALL_DRAFTS_PATH, "w") as f:
            json.dump(all_drafts, f, indent=2)
        print(f"  Saved! Total entries: {len(all_drafts)}")
    else:
        print(f"  WARNING: {ALL_DRAFTS_PATH} not found. Saving as new file.")
        with open(ALL_DRAFTS_PATH, "w") as f:
            json.dump(draft, f, indent=2)
        print(f"  Saved {len(draft)} entries.")

    print("\nDone!")


if __name__ == "__main__":
    main()
