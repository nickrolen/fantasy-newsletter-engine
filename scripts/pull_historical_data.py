"""
pull_historical_data.py (IMPROVED v2)

Pulls comprehensive historical data from Yahoo Fantasy API for all seasons.
Now with better debugging and more robust parsing.

Usage:
    python pull_historical_data.py                    # Normal mode
    python pull_historical_data.py --debug           # Debug mode (shows raw API responses)
    python pull_historical_data.py --season 2024-25  # Single season only
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import (
    HISTORICAL_LEAGUE_KEYS, MANAGER_ALIASES, YAHOO_GAME_CODE, CURRENT_SEASON,
)

# =============================================================================
# CONFIGURATION (loaded from config/league_config.json via data_loader)
# =============================================================================

# Historical seasons only (not current season -- that's tracked in RECORDS.json)
LEAGUE_KEYS = {k: v for k, v in HISTORICAL_LEAGUE_KEYS.items() if k != CURRENT_SEASON}

OUTPUT_DIR = "data/historical"
DEBUG = False

# =============================================================================
# HELPERS
# =============================================================================

def normalize_manager(name):
    """Normalize manager name to canonical form."""
    if not name:
        return "Unknown"
    name_lower = name.lower().strip()
    for alias, canonical in MANAGER_ALIASES.items():
        if alias in name_lower:
            return canonical
    return name.title()


def safe_float(val):
    """Safely convert to float."""
    try:
        return float(val) if val else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def safe_int(val):
    """Safely convert to int."""
    try:
        return int(val) if val else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def debug_print(msg, data=None):
    """Print debug info if DEBUG mode is on."""
    if DEBUG:
        print(f"    [DEBUG] {msg}")
        if data is not None:
            if isinstance(data, (dict, list)):
                print(f"    [DEBUG] {json.dumps(data, indent=2)[:1000]}")
            else:
                print(f"    [DEBUG] {str(data)[:500]}")


# =============================================================================
# MERGE / CHECKPOINT HELPERS
# =============================================================================

def _load_json_or_default(path, default):
    """Load JSON file if it exists, otherwise return the default value."""
    p = Path(path)
    if not p.exists():
        return default
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"    WARNING: Failed to load {path} ({e}); starting from default.")
        return default


def _merge_season_list(existing: list, new_entries: list, season: str) -> list:
    """Replace all entries for `season` in `existing` with `new_entries`.

    `existing` and `new_entries` are list-of-dicts where each dict has a
    'season' key. This makes the write idempotent: re-pulling a season
    replaces only that season's rows.
    """
    if not isinstance(existing, list):
        existing = []
    existing = [e for e in existing if e.get("season") != season]
    existing.extend(new_entries)
    return existing


def _save_json(path, data):
    """Write data to JSON atomically (write to .tmp then rename)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(p)


def checkpoint_season(season: str, matchups: list, standings: list,
                      trades: list, drafts: list, teams_map: dict) -> None:
    """Merge a single season's pulled data into the on-disk files immediately.

    Called after each season is successfully pulled, so an API failure
    halfway through the run does not lose previously-pulled seasons and
    does not overwrite the other seasons already in the files.
    """
    matchups_path = f"{OUTPUT_DIR}/all_matchups.json"
    standings_path = f"{OUTPUT_DIR}/all_standings.json"
    trades_path = f"{OUTPUT_DIR}/all_trades.json"
    drafts_path = f"{OUTPUT_DIR}/all_drafts.json"
    teams_path = f"{OUTPUT_DIR}/all_teams.json"

    # List-of-dicts files: merge by season key
    _save_json(matchups_path, _merge_season_list(
        _load_json_or_default(matchups_path, []), matchups, season))
    _save_json(standings_path, _merge_season_list(
        _load_json_or_default(standings_path, []), standings, season))
    _save_json(trades_path, _merge_season_list(
        _load_json_or_default(trades_path, []), trades, season))
    _save_json(drafts_path, _merge_season_list(
        _load_json_or_default(drafts_path, []), drafts, season))

    # Dict-of-seasons file: merge by season key
    existing_teams = _load_json_or_default(teams_path, {})
    if not isinstance(existing_teams, dict):
        existing_teams = {}
    existing_teams[season] = teams_map
    _save_json(teams_path, existing_teams)

    print(f"    [CHECKPOINT] {season} merged into data/historical/*.json")


# =============================================================================
# DATA EXTRACTION FUNCTIONS
# =============================================================================

def extract_team_info(lg, season):
    """Extract team/manager mapping for a season."""
    teams = {}
    try:
        teams_data = lg.teams()
        debug_print("Raw teams() response:", teams_data)
        
        for team_key, data in teams_data.items():
            manager_name = "Unknown"
            if 'managers' in data:
                managers = data['managers']
                if isinstance(managers, list) and len(managers) > 0:
                    mgr = managers[0]
                    if isinstance(mgr, dict) and 'manager' in mgr:
                        manager_name = mgr['manager'].get('nickname', 'Unknown')
                    elif isinstance(mgr, dict):
                        manager_name = mgr.get('nickname', 'Unknown')
            
            teams[team_key] = {
                "team_name": data.get('name', 'Unknown'),
                "manager": normalize_manager(manager_name),
                "team_key": team_key,
            }
            
        print(f"    Found teams: {[t['manager'] for t in teams.values()]}")
    except Exception as e:
        print(f"    Error extracting teams: {e}")
    return teams


def extract_matchups(lg, season, teams):
    """Extract all matchup results by parsing the nested Yahoo API response."""
    matchups = []
    seen = set()
    
    try:
        end_week = lg.end_week()
        current_week = lg.current_week()
        max_week = min(end_week, current_week)
        
        print(f"    Extracting matchups for weeks 1-{max_week}...")
        
        for week in range(1, max_week + 1):
            try:
                raw = lg.matchups(week=week)
                
                if week == 1:
                    debug_print(f"Raw matchups(week=1) response:", raw)
                
                # Navigate: fantasy_content > league[1] > scoreboard > '0' > matchups
                fc = raw.get('fantasy_content', {})
                league_list = fc.get('league', [])
                
                if len(league_list) < 2:
                    continue
                
                scoreboard_wrapper = league_list[1].get('scoreboard', {})
                matchups_wrapper = scoreboard_wrapper.get('0', {}).get('matchups', {})
                
                # Iterate through matchups (keys are '0', '1', etc. and 'count')
                matchup_count = matchups_wrapper.get('count', 0)
                
                for i in range(matchup_count):
                    matchup_data = matchups_wrapper.get(str(i), {}).get('matchup', {})
                    
                    if not matchup_data:
                        continue
                    
                    # Get teams from matchup > '0' > teams
                    teams_wrapper = matchup_data.get('0', {}).get('teams', {})
                    team_count = teams_wrapper.get('count', 0)
                    
                    if team_count < 2:
                        continue
                    
                    # Extract both teams' data
                    team_a_data = teams_wrapper.get('0', {}).get('team', [])
                    team_b_data = teams_wrapper.get('1', {}).get('team', [])
                    
                    def parse_team(team_data):
                        """Parse team info from the nested list structure."""
                        team_key = None
                        team_name = None
                        manager = None
                        points = 0.0
                        
                        if not isinstance(team_data, list) or len(team_data) < 2:
                            return None
                        
                        # First element is a list of team metadata dicts
                        meta_list = team_data[0] if isinstance(team_data[0], list) else []
                        for item in meta_list:
                            if isinstance(item, dict):
                                if 'team_key' in item:
                                    team_key = item['team_key']
                                if 'name' in item:
                                    team_name = item['name']
                                if 'managers' in item:
                                    mgrs = item['managers']
                                    if isinstance(mgrs, list) and len(mgrs) > 0:
                                        mgr = mgrs[0].get('manager', {})
                                        manager = mgr.get('nickname', '')
                        
                        # Second element has team_points
                        if len(team_data) > 1 and isinstance(team_data[1], dict):
                            tp = team_data[1].get('team_points', {})
                            points = safe_float(tp.get('total', 0))
                        
                        return {
                            'team_key': team_key,
                            'team_name': team_name,
                            'manager': normalize_manager(manager),
                            'points': points,
                        }
                    
                    team_a = parse_team(team_a_data)
                    team_b = parse_team(team_b_data)
                    
                    if not team_a or not team_b:
                        continue
                    
                    # Use teams dict to fill in manager if not found
                    if team_a['manager'] == 'Unknown' and team_a['team_key'] in teams:
                        team_a['manager'] = teams[team_a['team_key']]['manager']
                    if team_b['manager'] == 'Unknown' and team_b['team_key'] in teams:
                        team_b['manager'] = teams[team_b['team_key']]['manager']
                    
                    # Skip duplicates
                    matchup_key = (week, tuple(sorted([team_a['manager'], team_b['manager']])))
                    if matchup_key in seen:
                        continue
                    seen.add(matchup_key)
                    
                    score_a = team_a['points']
                    score_b = team_b['points']
                    
                    if score_a > 0 or score_b > 0:
                        matchups.append({
                            "season": season,
                            "week": week,
                            "manager_a": team_a['manager'],
                            "manager_b": team_b['manager'],
                            "score_a": score_a,
                            "score_b": score_b,
                            "winner": team_a['manager'] if score_a > score_b else team_b['manager'],
                            "loser": team_b['manager'] if score_a > score_b else team_a['manager'],
                            "margin": abs(score_a - score_b),
                        })
                
                time.sleep(0.3)
                
            except Exception as e:
                print(f"      Week {week} error: {e}")
                continue
                
    except Exception as e:
        print(f"    Error extracting matchups: {e}")
        import traceback
        traceback.print_exc()
    
    return matchups


def extract_standings(lg, season, teams):
    """Extract final standings for a season with multiple parsing strategies."""
    standings = []
    
    try:
        standings_data = lg.standings()
        debug_print("Raw standings() response:", standings_data)
        
        for team in standings_data:
            team_key = team.get('team_key')
            manager = teams.get(team_key, {}).get('manager', 'Unknown')
            
            # Try multiple paths for standings data
            team_standings = team.get('team_standings', {})
            
            # Primary: outcome_totals
            outcomes = team_standings.get('outcome_totals', {})
            
            # Alternative: direct on team_standings
            wins = safe_int(outcomes.get('wins')) or safe_int(team_standings.get('wins'))
            losses = safe_int(outcomes.get('losses')) or safe_int(team_standings.get('losses'))
            ties = safe_int(outcomes.get('ties')) or safe_int(team_standings.get('ties'))
            
            # Try to get points_for/against from multiple locations
            points_for = safe_float(team_standings.get('points_for')) or safe_float(team.get('points_for'))
            points_against = safe_float(team_standings.get('points_against')) or safe_float(team.get('points_against'))
            
            # Rank
            rank = safe_int(team_standings.get('rank')) or safe_int(team.get('rank'))
            
            standings.append({
                "season": season,
                "manager": manager,
                "team_name": team.get('name', 'Unknown'),
                "rank": rank,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "points_for": points_for,
                "points_against": points_against,
            })
            
    except Exception as e:
        print(f"    Error extracting standings: {e}")
    
    return standings


def extract_trades(lg, season, teams):
    """Extract all trades for a season."""
    trades = []
    
    try:
        # Try different parameter formats
        trans_data = None
        try:
            trans_data = lg.transactions('trade', 100)
        except Exception:
            try:
                trans_data = lg.transactions(tran_types='trade')
            except Exception:
                pass
        
        if not trans_data:
            debug_print("No trades found or transactions() call failed")
            return trades
        
        debug_print(f"Raw transactions('trade') response ({len(trans_data)} items):", 
                   trans_data[0] if trans_data else None)
        
        for t in trans_data:
            # Structure from diagnostic: direct dict with trade info
            trade = {
                "season": season,
                "timestamp": t.get('timestamp', ''),
                "trader_team": t.get('trader_team_name', ''),
                "tradee_team": t.get('tradee_team_name', ''),
                "players": [],
            }
            
            # Get trader/tradee managers from teams dict
            trader_key = t.get('trader_team_key', '')
            tradee_key = t.get('tradee_team_key', '')
            trade["trader_manager"] = teams.get(trader_key, {}).get('manager', '') or normalize_manager(trade["trader_team"])
            trade["tradee_manager"] = teams.get(tradee_key, {}).get('manager', '') or normalize_manager(trade["tradee_team"])
            
            # Parse players involved - try multiple structures
            # Structure 1: 'picks' array
            picks = t.get('picks', [])
            if picks:
                for pick in picks:
                    player_info = {
                        "from_team": pick.get('source_team_name', ''),
                        "to_team": pick.get('destination_team_name', ''),
                        "from_manager": teams.get(pick.get('source_team_key', ''), {}).get('manager', ''),
                        "to_manager": teams.get(pick.get('destination_team_key', ''), {}).get('manager', ''),
                    }
                    if 'player_name' in pick:
                        player_info['player_name'] = pick['player_name']
                    trade["players"].append(player_info)
            
            # Structure 2: 'players' array (if no picks)
            if not trade["players"]:
                players = t.get('players', [])
                if isinstance(players, dict):
                    players = list(players.values())
                for p in players:
                    player = p.get('player', p)
                    player_name = "Unknown"
                    from_mgr = ""
                    to_mgr = ""
                    
                    if isinstance(player, list):
                        for item in player:
                            if isinstance(item, dict):
                                if 'name' in item:
                                    name_data = item['name']
                                    if isinstance(name_data, dict):
                                        player_name = name_data.get('full', 'Unknown')
                                    else:
                                        player_name = str(name_data)
                                if 'transaction_data' in item:
                                    td = item['transaction_data']
                                    if isinstance(td, list):
                                        td = td[0] if td else {}
                                    from_mgr = teams.get(td.get('source_team_key', ''), {}).get('manager', '')
                                    to_mgr = teams.get(td.get('destination_team_key', ''), {}).get('manager', '')
                    elif isinstance(player, dict):
                        name_data = player.get('name', {})
                        if isinstance(name_data, dict):
                            player_name = name_data.get('full', 'Unknown')
                        td = player.get('transaction_data', {})
                        if isinstance(td, list):
                            td = td[0] if td else {}
                        from_mgr = teams.get(td.get('source_team_key', ''), {}).get('manager', '')
                        to_mgr = teams.get(td.get('destination_team_key', ''), {}).get('manager', '')
                    
                    trade["players"].append({
                        "player_name": player_name,
                        "from_manager": from_mgr,
                        "to_manager": to_mgr,
                    })
            
            trades.append(trade)
            
    except Exception as e:
        print(f"    Error extracting trades: {e}")
        import traceback
        traceback.print_exc()
    
    return trades


def extract_draft(lg, season, teams):
    """Extract draft results for a season."""
    draft_results = []
    
    try:
        draft_data = lg.draft_results()
        debug_print("Raw draft_results() response:", draft_data[:2] if draft_data else None)
        
        # Collect integer player IDs for batch lookup
        # Yahoo returns player_id (int), NOT player_key (str)
        player_ids = []
        for pick in draft_data:
            dp = pick.get('draft_result', pick)
            pid = dp.get('player_id')
            if pid:
                player_ids.append(int(pid))
        
        debug_print(f"Found {len(player_ids)} player IDs", player_ids[:5])
        
        # Batch fetch player names (25 at a time)
        player_names = {}  # int player_id -> str name
        if player_ids:
            for i in range(0, len(player_ids), 25):
                batch = player_ids[i:i+25]
                try:
                    details = lg.player_details(batch)
                    debug_print(f"player_details batch {i//25} response:", details[:1] if details else None)
                    for pd_entry in details:
                        pid = int(pd_entry.get('player_id', 0))
                        name = pd_entry.get('name', {})
                        if isinstance(name, dict):
                            full_name = name.get('full', 'Unknown')
                        else:
                            full_name = str(name) if name else 'Unknown'
                        player_names[pid] = full_name
                    time.sleep(0.5)
                except Exception as e:
                    print(f"      Batch {i//25} failed: {e}")
                    # Individual fallback
                    for pid in batch:
                        try:
                            details = lg.player_details([pid])
                            if details:
                                pd_entry = details[0]
                                name = pd_entry.get('name', {})
                                full_name = name.get('full', 'Unknown') if isinstance(name, dict) else str(name)
                                player_names[pid] = full_name
                        except Exception:
                            player_names[pid] = 'Unknown'
                        time.sleep(0.3)
        
        resolved = sum(1 for v in player_names.values() if v != 'Unknown')
        print(f"    Resolved {resolved}/{len(player_ids)} player names")
        
        for pick in draft_data:
            dp = pick.get('draft_result', pick)
            team_key = dp.get('team_key', '')
            player_id = int(dp.get('player_id', 0))
            
            draft_results.append({
                "season": season,
                "pick_number": safe_int(dp.get('pick', 0)),
                "round": safe_int(dp.get('round', 0)),
                "manager": teams.get(team_key, {}).get('manager', 'Unknown'),
                "player_key": str(player_id),
                "player_name": player_names.get(player_id, 'Unknown'),
            })
            
    except Exception as e:
        print(f"    Error extracting draft: {e}")
        import traceback
        traceback.print_exc()
    
    return draft_results


# =============================================================================
# MAIN
# =============================================================================

def main():
    global DEBUG
    
    parser = argparse.ArgumentParser(description="Pull historical data from Yahoo Fantasy API")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--season", type=str, help="Process only this season (e.g., 2024-25)")
    args = parser.parse_args()
    
    DEBUG = args.debug
    
    print("=" * 60)
    print("Yahoo Fantasy Historical Data Extractor")
    print("=" * 60)
    if DEBUG:
        print("*** DEBUG MODE ENABLED ***")
    print()
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("Authenticating with Yahoo...")
    oauth = OAuth2(None, None, from_file="oauth2.json")
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    print("  Authenticated!")
    print()
    
    # Accumulators -- used only for summary statistics at the end, NOT for
    # the canonical on-disk files (those are merged per-season inside the
    # loop via checkpoint_season). This means that if the run fails halfway
    # through, the on-disk files still contain every successfully-pulled
    # season -- nothing has been wholesale-overwritten.
    all_matchups = []
    all_standings = []
    all_trades = []
    all_drafts = []
    all_teams = {}

    # Determine which seasons to process
    if args.season:
        if args.season not in LEAGUE_KEYS:
            print(f"ERROR: Season {args.season} not found in LEAGUE_KEYS")
            print(f"Available: {list(LEAGUE_KEYS.keys())}")
            return
        seasons_to_process = {args.season: LEAGUE_KEYS[args.season]}
    else:
        seasons_to_process = LEAGUE_KEYS

    failed_seasons = []
    succeeded_seasons = []

    for season, league_key in sorted(seasons_to_process.items()):
        print(f"Processing {season} ({league_key})...")

        try:
            lg = yfa.League(oauth, league_key)

            print("  Extracting team info...")
            teams = extract_team_info(lg, season)
            teams_map = {k: {"manager": v["manager"], "team_name": v["team_name"]}
                         for k, v in teams.items()}
            all_teams[season] = teams_map

            if not teams:
                print("  WARNING: No teams found, skipping season "
                      "(NOT overwriting existing on-disk data for this season)")
                failed_seasons.append(season)
                continue

            print("  Extracting matchups...")
            matchups = extract_matchups(lg, season, teams)
            print(f"    Found {len(matchups)} matchups")

            print("  Extracting standings...")
            standings = extract_standings(lg, season, teams)
            print(f"    Found {len(standings)} standings entries")
            if standings and standings[0].get('wins', 0) == 0:
                print("    WARNING: Standings appear to have no win/loss data")

            print("  Extracting trades...")
            trades = extract_trades(lg, season, teams)
            print(f"    Found {len(trades)} trades")

            print("  Extracting draft results...")
            draft = extract_draft(lg, season, teams)
            print(f"    Found {len(draft)} picks")
            if draft and draft[0].get('player_name', 'Unknown') == 'Unknown':
                print("    WARNING: Draft picks have no player names")

            # Checkpoint immediately: merge this season into the on-disk files.
            # This is the key fix -- previously, all seasons were accumulated
            # in memory and the files were overwritten at the end, which would
            # erase other seasons if you ran with --season X.
            checkpoint_season(season, matchups, standings, trades, draft, teams_map)

            all_matchups.extend(matchups)
            all_standings.extend(standings)
            all_trades.extend(trades)
            all_drafts.extend(draft)
            succeeded_seasons.append(season)

            print(f"  Done with {season}!")
            print()

            time.sleep(1)

        except Exception as e:
            print(f"  ERROR processing {season}: {e}")
            print(f"  (NOT overwriting on-disk data for {season} -- "
                  f"previous values preserved)")
            import traceback
            traceback.print_exc()
            print()
            failed_seasons.append(season)
            continue

    # Per-season files were already written via checkpoint_season().
    # Print a summary of what's on disk now.
    print("=" * 60)
    print("Per-season checkpoints written. Summary:")
    matchups_on_disk = _load_json_or_default(f"{OUTPUT_DIR}/all_matchups.json", [])
    standings_on_disk = _load_json_or_default(f"{OUTPUT_DIR}/all_standings.json", [])
    trades_on_disk = _load_json_or_default(f"{OUTPUT_DIR}/all_trades.json", [])
    drafts_on_disk = _load_json_or_default(f"{OUTPUT_DIR}/all_drafts.json", [])
    teams_on_disk = _load_json_or_default(f"{OUTPUT_DIR}/all_teams.json", {})
    print(f"  all_matchups.json: {len(matchups_on_disk)} entries")
    print(f"  all_standings.json: {len(standings_on_disk)} entries")
    print(f"  all_trades.json: {len(trades_on_disk)} entries")
    print(f"  all_drafts.json: {len(drafts_on_disk)} entries")
    print(f"  all_teams.json: {len(teams_on_disk)} seasons")
    if failed_seasons:
        print(f"  Failed/skipped seasons (not written): {failed_seasons}")
    if succeeded_seasons:
        print(f"  Succeeded (merged into files): {succeeded_seasons}")


if __name__ == "__main__":
    main()
