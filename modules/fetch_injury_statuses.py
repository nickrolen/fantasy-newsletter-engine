#!/usr/bin/env python3
"""
fetch_injury_statuses.py

Fetches current injury statuses for all rostered players from Yahoo Fantasy API.
Returns a dict mapping player_name -> injury status (e.g., "GTD", "O", "HEALTHY").

Used by generate_stats_report.py to provide accurate injury data to betting simulations.
"""

import unicodedata
from pathlib import Path
from typing import Optional

try:
    from yahoo_oauth import OAuth2
    import yahoo_fantasy_api as yfa
    YAHOO_API_AVAILABLE = True
except ImportError:
    YAHOO_API_AVAILABLE = False


# ---------- CONFIGURATION (from league_config.json via data_loader) ----------

from .data_loader import LEAGUE_KEY, TEAM_TO_MANAGER, YAHOO_GAME_CODE

# Alias for backwards compatibility
FANTASY_TEAM_TO_MANAGER = TEAM_TO_MANAGER


# ---------- HELPERS ----------

def strip_accents(text: str) -> str:
    """Return ASCII-only version of a name (e.g., 'Don??i??' -> 'Doncic')."""
    if not isinstance(text, str):
        return text
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def get_league(oauth) -> "yfa.League":
    """Return League object for your NBA league."""
    return yfa.League(oauth, LEAGUE_KEY)


def normalize_injury_status(status: Optional[str]) -> str:
    """
    Normalize Yahoo injury status to standard format.
    
    Yahoo returns various formats like:
    - "GTD" (Game Time Decision)
    - "O" (Out)
    - "INJ" (Injured)
    - "IL" (Injured List)
    - "IL+" (Injured List Plus)
    - None or "" (Healthy)
    
    Returns uppercase normalized status or "HEALTHY" if no injury.
    """
    if not status or str(status).strip() == "":
        return "HEALTHY"
    
    status_upper = str(status).strip().upper()
    
    # Map common variations
    status_map = {
        "GTD": "GTD",
        "GAME TIME DECISION": "GTD",
        "DTD": "DTD",
        "DAY TO DAY": "DTD",
        "DAY-TO-DAY": "DTD",
        "O": "O",
        "OUT": "O",
        "INJ": "INJ",
        "INJURED": "INJ",
        "IL": "IL",
        "IL+": "IL+",
        "SUSP": "O",  # Suspended treated as Out
        "NA": "O",    # Not Available treated as Out
    }
    
    return status_map.get(status_upper, status_upper)


def fetch_injury_statuses(
    oauth_file: str = "oauth2.json",
    verbose: bool = False,
) -> dict[str, str]:
    """
    Fetch current injury statuses for all rostered players.
    
    Args:
        oauth_file: Path to Yahoo OAuth2 credentials file
        verbose: If True, print progress information
    
    Returns:
        Dict mapping player_name -> injury status
        Status is one of: "HEALTHY", "GTD", "DTD", "O", "INJ", "IL", "IL+"
    """
    if not YAHOO_API_AVAILABLE:
        if verbose:
            print("Warning: yahoo_oauth/yahoo_fantasy_api not installed.")
            print("Cannot fetch real-time injury statuses.")
        return {}
    
    # Check if oauth file exists
    if not Path(oauth_file).exists():
        if verbose:
            print(f"Warning: OAuth file not found at {oauth_file}")
            print("Cannot fetch real-time injury statuses.")
        return {}
    
    # Authenticate (fail-fast, never prompts; injury data is optional so we
    # degrade gracefully to an empty mapping if creds are unusable).
    try:
        from .yahoo_auth import build_oauth, YahooAuthError
        try:
            oauth = build_oauth(oauth_file, OAuth2=OAuth2)
        except YahooAuthError as e:
            if verbose:
                print(f"Skipping injury fetch (Yahoo auth unavailable): {e}")
            return {}
    except Exception as e:
        if verbose:
            print(f"Warning: OAuth authentication failed: {e}")
        return {}
    
    lg = get_league(oauth)
    
    if verbose:
        print("Fetching injury statuses from Yahoo...")
    
    # Get all teams
    teams_json = lg.teams()
    
    injury_statuses = {}
    all_player_ids = []
    player_id_to_name = {}
    
    # First pass: collect all player IDs from rosters
    for team_key, team_data in teams_json.items():
        team_name = team_data["name"]
        team_obj = lg.to_team(team_key)
        
        # Get current roster
        roster = team_obj.roster()
        
        for player in roster:
            player_id = int(player["player_id"])
            player_name = strip_accents(player["name"])
            
            all_player_ids.append(player_id)
            player_id_to_name[player_id] = player_name
            
            # Get injury status from roster data if available
            # Yahoo sometimes includes status in roster response
            status = player.get("status")
            if status:
                injury_statuses[player_name] = normalize_injury_status(status)
    
    # Second pass: get detailed player info for more accurate injury status
    # player_details() often has more up-to-date injury info
    if all_player_ids:
        try:
            details = lg.player_details(all_player_ids)
            
            for player_detail in details:
                player_id = int(player_detail["player_id"])
                player_name = player_id_to_name.get(player_id)
                
                if player_name:
                    # Check multiple possible status fields
                    status = (
                        player_detail.get("status") or 
                        player_detail.get("injury_status") or
                        player_detail.get("status_full")
                    )
                    
                    normalized = normalize_injury_status(status)
                    
                    # Only update if we found a non-healthy status
                    # (roster endpoint might have already caught it)
                    if normalized != "HEALTHY" or player_name not in injury_statuses:
                        injury_statuses[player_name] = normalized
                        
        except Exception as e:
            if verbose:
                print(f"Warning: Could not fetch player details: {e}")
                print("Using roster-level injury data only.")
    
    # Ensure all players have a status (default to HEALTHY)
    for player_name in player_id_to_name.values():
        if player_name not in injury_statuses:
            injury_statuses[player_name] = "HEALTHY"
    
    if verbose:
        # Count by status
        status_counts = {}
        for status in injury_statuses.values():
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print(f"Fetched statuses for {len(injury_statuses)} players:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")
        
        # Show non-healthy players
        non_healthy = {k: v for k, v in injury_statuses.items() if v != "HEALTHY"}
        if non_healthy:
            print("\nNon-healthy players:")
            for player, status in sorted(non_healthy.items()):
                print(f"  {player}: {status}")
    
    return injury_statuses


def fetch_injury_statuses_safe(
    oauth_file: str = "oauth2.json",
    verbose: bool = False,
) -> dict[str, str]:
    """
    Safe wrapper around fetch_injury_statuses that returns empty dict on failure.
    
    Use this in generate_stats_report.py to gracefully handle API failures.
    """
    try:
        return fetch_injury_statuses(oauth_file=oauth_file, verbose=verbose)
    except Exception as e:
        if verbose:
            print(f"Warning: Failed to fetch injury statuses: {e}")
            print("Continuing without real-time injury data.")
        return {}


# ---------- MAIN ----------

if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(
        description="Fetch current injury statuses from Yahoo Fantasy API"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path for JSON (optional, prints to stdout if not specified)",
    )
    parser.add_argument(
        "--oauth-file",
        type=str,
        default="oauth2.json",
        help="Path to Yahoo OAuth2 credentials file",
    )
    
    args = parser.parse_args()
    
    statuses = fetch_injury_statuses(oauth_file=args.oauth_file, verbose=True)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(statuses, f, indent=2)
        print(f"\nSaved to {args.output}")
    else:
        print("\nJSON output:")
        print(json.dumps(statuses, indent=2))
