"""
backfill_draft_names.py

Backfills player names for ALL seasons in all_drafts.json by re-querying
the Yahoo Fantasy API using integer player_ids (the format that actually works).

The original pull_historical_data.py looked for 'player_key' in draft results,
but Yahoo returns 'player_id' (int). This script fixes that for every season.

Usage:
    python scripts/backfill_draft_names.py                    # All seasons
    python scripts/backfill_draft_names.py --season 2024-25   # Single season
    python scripts/backfill_draft_names.py --debug            # Show raw API responses
    python scripts/backfill_draft_names.py --dry-run          # Preview without saving

Requires:
    - oauth2.json in the working directory
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

from modules.data_loader import HISTORICAL_LEAGUE_KEYS, MANAGER_ALIASES, YAHOO_GAME_CODE

# =============================================================================
# CONFIGURATION (loaded from config/league_config.json via data_loader)
# =============================================================================

LEAGUE_KEYS = HISTORICAL_LEAGUE_KEYS

# Adjust to match your local directory structure
BASE_DIR = Path(__file__).resolve().parent.parent
ALL_DRAFTS_PATH = BASE_DIR / "data" / "historical" / "all_drafts.json"

DEBUG = False


# =============================================================================
# HELPERS
# =============================================================================

def debug_print(label, obj):
    if DEBUG:
        truncated = json.dumps(obj, indent=2, default=str)[:600]
        print(f"    [DEBUG] {label}: {truncated}")


def normalize_manager(name):
    if not name:
        return "Unknown"
    name_lower = name.lower().strip()
    for alias, canonical in MANAGER_ALIASES.items():
        if alias in name_lower:
            return canonical
    return name.title()


def strip_accents(text):
    """Basic accent stripping for player names."""
    import unicodedata
    try:
        nfkd = unicodedata.normalize("NFKD", str(text))
        return "".join(c for c in nfkd if not unicodedata.combining(c))
    except Exception:
        return str(text)


# =============================================================================
# EXTRACTION
# =============================================================================

def extract_teams(lg):
    """Get team_key -> manager name mapping."""
    teams = {}
    try:
        teams_data = lg.teams()
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
        print(f"    ERROR extracting teams: {e}")
    return teams


def extract_draft_with_names(lg, season, teams):
    """
    Extract draft results with player name resolution using int player_ids.
    
    This is the fixed version: Yahoo's draft_results() returns player_id (int),
    and player_details() expects a list of ints.
    """
    results = []

    try:
        draft_data = lg.draft_results()
        debug_print(f"Raw draft_results (first 2)", draft_data[:2] if draft_data else None)
        print(f"    {len(draft_data)} picks found")

        # Collect integer player IDs
        player_ids = []
        for pick in draft_data:
            dp = pick.get("draft_result", pick)
            pid = dp.get("player_id")
            if pid:
                player_ids.append(int(pid))

        print(f"    {len(player_ids)} player IDs to resolve")

        # Batch fetch player names (25 at a time)
        player_names = {}  # int player_id -> str name
        if player_ids:
            for i in range(0, len(player_ids), 25):
                batch = player_ids[i:i + 25]
                try:
                    details = lg.player_details(batch)
                    debug_print(f"Batch {i // 25} response (first entry)", details[:1] if details else None)
                    for pd_entry in details:
                        pid = int(pd_entry.get("player_id", 0))
                        name = pd_entry.get("name", {})
                        if isinstance(name, dict):
                            full_name = strip_accents(name.get("full", "Unknown"))
                        else:
                            full_name = strip_accents(str(name)) if name else "Unknown"
                        player_names[pid] = full_name
                    time.sleep(0.5)
                except Exception as e:
                    print(f"    WARNING: Batch {i // 25} failed: {e}")
                    # Individual fallback
                    for pid in batch:
                        try:
                            details = lg.player_details([pid])
                            if details:
                                pd_entry = details[0]
                                name = pd_entry.get("name", {})
                                full_name = name.get("full", "Unknown") if isinstance(name, dict) else str(name)
                                player_names[pid] = strip_accents(full_name)
                        except Exception:
                            player_names[pid] = "Unknown"
                        time.sleep(0.3)

        resolved = sum(1 for v in player_names.values() if v != "Unknown")
        print(f"    Resolved {resolved}/{len(player_ids)} player names")

        # Build results
        for pick in draft_data:
            dp = pick.get("draft_result", pick)
            team_key = dp.get("team_key", "")
            player_id = int(dp.get("player_id", 0))
            pick_num = int(dp.get("pick", 0))
            round_num = int(dp.get("round", 0))

            results.append({
                "season": season,
                "pick_number": pick_num,
                "round": round_num,
                "manager": teams.get(team_key, "Unknown"),
                "player_key": str(player_id),
                "player_name": player_names.get(player_id, "Unknown"),
            })

    except Exception as e:
        print(f"    ERROR extracting draft: {e}")
        import traceback
        traceback.print_exc()

    return results


# =============================================================================
# MAIN
# =============================================================================

def main():
    global DEBUG

    parser = argparse.ArgumentParser(description="Backfill draft player names from Yahoo API")
    parser.add_argument("--debug", action="store_true", help="Show raw API responses")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--season", type=str, help="Process only this season (e.g., 2024-25)")
    args = parser.parse_args()

    DEBUG = args.debug

    print("=" * 60)
    print("Backfill Draft Player Names")
    print("=" * 60)
    if DEBUG:
        print("*** DEBUG MODE ***")
    if args.dry_run:
        print("*** DRY RUN ***")
    print()

    # Authenticate
    print("Authenticating with Yahoo...")
    oauth = OAuth2(None, None, from_file="oauth2.json")
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    print("  Authenticated!\n")

    # Determine seasons to process
    if args.season:
        if args.season not in LEAGUE_KEYS:
            print(f"ERROR: Season {args.season} not found.")
            print(f"Available: {sorted(LEAGUE_KEYS.keys())}")
            return
        seasons = {args.season: LEAGUE_KEYS[args.season]}
    else:
        seasons = LEAGUE_KEYS

    # Load existing all_drafts.json
    if ALL_DRAFTS_PATH.exists():
        with open(ALL_DRAFTS_PATH) as f:
            all_drafts = json.load(f)
        print(f"Loaded {len(all_drafts)} existing draft entries from {ALL_DRAFTS_PATH}\n")
    else:
        all_drafts = []
        print(f"No existing all_drafts.json found. Starting fresh.\n")

    # Track results
    total_resolved = 0
    total_picks = 0
    seasons_processed = 0
    seasons_failed = []

    for season in sorted(seasons.keys()):
        league_key = seasons[season]
        print(f"{'=' * 50}")
        print(f"Processing {season} ({league_key})")
        print(f"{'=' * 50}")

        try:
            lg = yfa.League(oauth, league_key)

            # Get teams
            teams = extract_teams(lg)
            if not teams:
                print(f"  WARNING: No teams found for {season}, skipping")
                seasons_failed.append(season)
                continue
            print(f"  Teams: {list(teams.values())}")

            # Extract draft with name resolution
            draft = extract_draft_with_names(lg, season, teams)

            if not draft:
                print(f"  WARNING: No draft results for {season}")
                seasons_failed.append(season)
                continue

            unknown = sum(1 for d in draft if d["player_name"] == "Unknown")
            resolved = len(draft) - unknown
            total_resolved += resolved
            total_picks += len(draft)
            seasons_processed += 1

            # Show results
            print(f"\n  Results: {len(draft)} picks, {resolved} resolved, {unknown} unknown")
            for d in draft:
                status = "OK" if d["player_name"] != "Unknown" else "??"
                print(f"    R{d['round']:>2} P{d['pick_number']:>2}: {d['manager']:8s} -> {d['player_name']:30s} [{status}]")

            if not args.dry_run:
                # Remove old entries for this season
                before = len(all_drafts)
                all_drafts = [d for d in all_drafts if d.get("season") != season]
                removed = before - len(all_drafts)
                if removed:
                    print(f"\n  Replaced {removed} old {season} entries")

                # Add new entries
                all_drafts.extend(draft)

            print()
            time.sleep(1)  # Rate limit between seasons

        except Exception as e:
            print(f"  ERROR processing {season}: {e}")
            import traceback
            traceback.print_exc()
            seasons_failed.append(season)
            print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Seasons processed: {seasons_processed}/{len(seasons)}")
    print(f"Total picks: {total_picks}")
    print(f"Names resolved: {total_resolved}/{total_picks}")
    if seasons_failed:
        print(f"Failed seasons: {seasons_failed}")

    if args.dry_run:
        print("\n[DRY RUN] No files modified.")
        return

    # Sort by season then pick number
    all_drafts.sort(key=lambda d: (d.get("season", ""), d.get("pick_number", 0)))

    # Save
    with open(ALL_DRAFTS_PATH, "w") as f:
        json.dump(all_drafts, f, indent=2)
    print(f"\nSaved {len(all_drafts)} total entries to {ALL_DRAFTS_PATH}")
    print("Done!")


if __name__ == "__main__":
    main()
