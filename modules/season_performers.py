"""
season_performers.py

Generate season-to-date best/worst performer tables using Yahoo Fantasy API.

This module pulls season stats directly from Yahoo API rather than PLAYERLOG,
which ensures we get accurate stats even for players recently added to rosters.

Tables generated:
1. Best Performers (Total FP, This Season) - Top 30 by Total FP
2. Best Performers (FPPG, This Season) - Top 30 by FPPG (min 50% GP)
3. Biggest Duds (Total FP, This Season) - Bottom 30 by Total FP  
4. Biggest Duds (FPPG, This Season) - Bottom 30 by FPPG (min 50% GP)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import time
import warnings

import pandas as pd

# Suppress pandas FutureWarnings (groupby deprecation, etc.)
warnings.filterwarnings('ignore', category=FutureWarning, module='pandas')
warnings.filterwarnings('ignore', message='Could not infer format')

# Yahoo API imports are lazy-loaded to allow the module to be imported
# even when yahoo_oauth is not available (e.g., in testing environments)
yfa = None
OAuth2 = None

def _ensure_yahoo_imports():
    """Lazy-load Yahoo API dependencies."""
    global yfa, OAuth2
    if yfa is None:
        from yahoo_oauth import OAuth2 as _OAuth2
        import yahoo_fantasy_api as _yfa
        OAuth2 = _OAuth2
        yfa = _yfa


# =============================================================================
# CONFIGURATION
# =============================================================================

from .data_loader import (
    YAHOO_GAME_CODE, LEAGUE_KEY, CURRENT_SEASON,
    MANAGER_TO_TEAM, TEAM_TO_MANAGER, NBA_SCHEDULE_FILE,
)

# Alias for backwards compatibility
NBA_SEASON = CURRENT_SEASON


# =============================================================================
# DATA LOADING HELPERS
# =============================================================================

def get_yahoo_league(base_path: Path) -> "yfa.League":
    """Initialize Yahoo Fantasy API connection."""
    _ensure_yahoo_imports()
    oauth_file = base_path / 'oauth2.json'
    from .yahoo_auth import build_oauth  # fail-fast: never prompts interactively
    oauth = build_oauth(oauth_file, OAuth2=OAuth2)
    return yfa.League(oauth, LEAGUE_KEY)


def load_rosters(base_path: Path) -> Dict[str, List[str]]:
    """Load current rosters from config/ROSTERS.json."""
    rosters_path = base_path / 'config' / 'ROSTERS.json'
    with open(rosters_path) as f:
        data = json.load(f)
    return data.get('rosters', {})


def load_playerlist(base_path: Path) -> pd.DataFrame:
    """Load data/PLAYERLIST.xlsx with projections."""
    return pd.read_excel(base_path / 'data' / 'PLAYERLIST.xlsx')


def load_schedule(base_path: Path) -> dict:
    """Load fantasy schedule from config/SCHEDULE.json."""
    with open(base_path / 'config' / 'SCHEDULE.json') as f:
        return json.load(f)


def load_nba_schedule(base_path: Path) -> List[dict]:
    """Load NBA game schedule from the configured schedule file."""
    with open(base_path / NBA_SCHEDULE_FILE) as f:
        return json.load(f).get('games', [])


def get_week_end_date(schedule: dict, week: int) -> datetime:
    """Get the end date for a given fantasy week."""
    for w in schedule.get('weeks', []):
        if w['week'] == week:
            return datetime.strptime(w['end_date'], '%Y-%m-%d')
    raise ValueError(f"Week {week} not found in schedule")


def calculate_team_games(nba_schedule: List[dict], through_date: datetime) -> Dict[str, int]:
    """Calculate games played per NBA team through a given date."""
    team_games = {}
    for game in nba_schedule:
        game_date = datetime.fromisoformat(game['date'].replace('Z', '+00:00')).replace(tzinfo=None)
        if game_date <= through_date:
            for team in [game['home'], game['away']]:
                team_games[team] = team_games.get(team, 0) + 1
    return team_games


# =============================================================================
# YAHOO API FUNCTIONS
# =============================================================================

def normalize_name_for_search(name: str) -> str:
    """Normalize player name for Yahoo API search."""
    # Remove apostrophes and other special characters that cause issues
    normalized = name.replace("'", "").replace("'", "").replace("'", "")
    return normalized


def get_search_variations(name: str) -> List[str]:
    """Generate search variations for a player name."""
    variations = []
    
    # Original name
    variations.append(name)
    
    # Remove apostrophes
    no_apos = name.replace("'", "").replace("'", "").replace("'", "")
    if no_apos != name:
        variations.append(no_apos)
    
    # Just last name (for unique last names)
    parts = name.split()
    if len(parts) >= 2:
        variations.append(parts[-1])  # Last name only
    
    # First name + last name initial patterns
    # e.g., "De'Aaron Fox" -> "DeAaron Fox", "Aaron Fox"
    if "'" in name or "'" in name:
        # Try removing the prefix before apostrophe
        for char in ["'", "'"]:
            if char in name:
                idx = name.index(char)
                after_apos = name[idx+1:]
                variations.append(after_apos)
    
    return variations


def get_player_ids_from_yahoo(lg, player_names: List[str]) -> Dict[str, int]:
    """Look up Yahoo player IDs for a list of player names."""
    player_ids = {}
    
    for name in player_names:
        found = False
        search_variations = get_search_variations(name)
        
        for search_name in search_variations:
            if found:
                break
            try:
                results = lg.player_details(search_name)
                
                if results:
                    # Find exact or closest match
                    normalized_name = normalize_name_for_search(name).lower()
                    for p in results:
                        full_name = p.get('name', {}).get('full', '')
                        normalized_full = normalize_name_for_search(full_name).lower()
                        if normalized_full == normalized_name:
                            player_ids[name] = int(p['player_id'])
                            found = True
                            break
                    
                    if not found and results:
                        # Use first result if no exact match
                        player_ids[name] = int(results[0]['player_id'])
                        found = True
                        
                time.sleep(0.1)  # Rate limiting
            except Exception as e:
                # Try next variation
                continue
        
        if not found:
            print(f"  Warning: Could not find player ID for {name}")
    
    return player_ids


def get_season_stats_from_yahoo(
    lg, 
    player_ids: List[int]
) -> Dict[int, dict]:
    """
    Get season stats for players from Yahoo API.
    
    Returns dict of player_id -> stats dict with keys like:
    - GP, MIN, total_points (fantasy points), etc.
    """
    stats_by_id = {}
    
    # Yahoo API has limits, batch requests
    batch_size = 25
    for i in range(0, len(player_ids), batch_size):
        batch = player_ids[i:i + batch_size]
        try:
            stats_list = lg.player_stats(batch, 'season')
            for row in stats_list:
                pid = int(row.get('player_id', 0))
                if pid:
                    stats_by_id[pid] = row
            time.sleep(0.5)  # Rate limiting between batches
        except Exception as e:
            print(f"  Warning: Error fetching stats for batch: {e}")
    
    return stats_by_id


# =============================================================================
# NBA API FUNCTIONS (for accurate GP% with trades)
# =============================================================================

# Custom headers to mimic a real browser - helps avoid NBA.com blocking
NBA_API_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
    'Connection': 'keep-alive',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

# Track consecutive failures to enable early bailout
_nba_api_consecutive_failures = 0
_nba_api_max_consecutive_failures = 5  # After this many failures, skip remaining calls


def get_player_game_logs_from_nba_api(
    player_name: str,
    through_date: datetime,
    max_retries: int = 3,
    base_delay: float = 2.0
) -> Tuple[int, Dict[str, int], Optional[float]]:
    """
    Get game logs for a player from nba_api to calculate accurate GP per team.
    
    Includes retry logic with exponential backoff for handling NBA.com rate limits.
    
    Args:
        player_name: Full name of the player
        through_date: Only include games on or before this date
        max_retries: Number of times to retry on failure (default 3)
        base_delay: Base delay between retries in seconds (doubles each retry)
    
    Returns:
        Tuple of (total_gp, dict of team_abbr -> games_with_that_team, avg_mpg)
    """
    global _nba_api_consecutive_failures
    
    # Early bailout if we've had too many consecutive failures
    # (NBA.com is probably blocking us)
    if _nba_api_consecutive_failures >= _nba_api_max_consecutive_failures:
        return 0, {}, None
    
    try:
        from nba_api.stats.static import players
        from nba_api.stats.endpoints import PlayerGameLog
        
        # First, find the player ID (this uses local data, no API call)
        player_matches = players.find_players_by_full_name(player_name)
        if not player_matches:
            # Try partial match
            player_matches = [p for p in players.get_players() 
                           if player_name.lower() in p['full_name'].lower()]
        
        if not player_matches:
            return 0, {}, None
        
        player_id = player_matches[0]['id']
        
        # Get game logs for this season with retry logic
        season_year = NBA_SEASON.split('-')[0]
        
        df = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Add delay before retry (exponential backoff)
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))
                    print(f"      Retry {attempt}/{max_retries-1} for {player_name} after {delay:.1f}s...")
                    time.sleep(delay)
                
                # Make the API call with custom headers and longer timeout
                logs = PlayerGameLog(
                    player_id=player_id,
                    season=season_year,
                    season_type_all_star='Regular Season',
                    headers=NBA_API_HEADERS,
                    timeout=60  # Increase timeout to 60 seconds
                )
                df = logs.get_data_frames()[0]
                
                # Success! Reset failure counter
                _nba_api_consecutive_failures = 0
                break
                
            except Exception as e:
                last_error = e
                error_type = type(e).__name__
                
                # Check if it's a retryable error
                retryable = any(x in str(e).lower() for x in [
                    'timeout', 'connection', 'reset', 'refused', 'aborted'
                ])
                
                if not retryable or attempt == max_retries - 1:
                    # Not retryable or final attempt
                    _nba_api_consecutive_failures += 1
                    if _nba_api_consecutive_failures >= _nba_api_max_consecutive_failures:
                        print(f"    nba_api: {_nba_api_consecutive_failures} consecutive failures - disabling for remaining players")
                    raise
        
        if df is None or df.empty:
            return 0, {}, None
        
        # Filter to games through our date
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        df = df[df['GAME_DATE'] <= through_date]
        
        if df.empty:
            return 0, {}, None
        
        # Count games per team
        # Extract team abbreviation from MATCHUP (e.g., "HOU vs. LAL" or "HOU @ LAL")
        # The first 3 chars are always the player's team
        team_abbrs = df['MATCHUP'].str[:3].unique()
        team_games = {}
        for team in team_abbrs:
            team_games[team] = len(df[df['MATCHUP'].str.startswith(team)])
        
        total_gp = len(df)
        
        # Get average minutes - MIN might be string like "32:45"
        if 'MIN' in df.columns and len(df) > 0:
            try:
                # Try to convert MIN to float (might be minutes as decimal or "MM:SS" format)
                min_vals = pd.to_numeric(df['MIN'], errors='coerce')
                avg_min = min_vals.mean() if not min_vals.isna().all() else None
            except:
                avg_min = None
        else:
            avg_min = None
        
        return total_gp, team_games, avg_min
        
    except Exception as e:
        print(f"    nba_api ERROR for {player_name}: {type(e).__name__}: {e}")
        return 0, {}, None


def reset_nba_api_failure_counter():
    """Reset the consecutive failure counter (call at start of batch processing)."""
    global _nba_api_consecutive_failures
    _nba_api_consecutive_failures = 0


def calculate_gp_pct_with_trades(
    player_team_games: Dict[str, int],
    nba_team_totals: Dict[str, int]
) -> float:
    """
    Calculate GP% accounting for trades.
    
    If a player played 20 games for ATL (41 total) and 10 games for WAS (38 total),
    their possible GP is calculated based on the teams they were actually on.
    """
    if not player_team_games:
        return 0.0
    
    total_played = sum(player_team_games.values())
    
    # Sum up games for each team the player was on
    total_possible = sum(
        nba_team_totals.get(team, 0) 
        for team in player_team_games.keys()
    )
    
    if total_possible == 0:
        return 0.0
    
    # Cap at 100% - can't play more than possible
    return min(100.0, (total_played / total_possible) * 100)


# =============================================================================
# MAIN AGGREGATION FUNCTION
# =============================================================================

def aggregate_stats_from_yahoo(
    lg,
    rosters: Dict[str, List[str]],
    playerlist: pd.DataFrame,
    nba_team_games: Dict[str, int],
    week_end: datetime,
    use_nba_api_for_gp: bool = True
) -> pd.DataFrame:
    """
    Aggregate season stats using Yahoo API.
    
    Returns DataFrame with columns:
    - player_name, fantasy_team, nba_team
    - total_fp, fppg, gp, gp_pct, mpg
    - eff_pct, proj_fp_ros, proj_fppg_ros
    """
    # Build roster lookup
    all_players = []
    player_to_team = {}
    for manager, players in rosters.items():
        fantasy_team = MANAGER_TO_TEAM.get(manager, manager)
        for player in players:
            all_players.append(player)
            player_to_team[player] = fantasy_team
    
    # Get Yahoo player IDs
    print("  Looking up player IDs from Yahoo...")
    player_ids = get_player_ids_from_yahoo(lg, all_players)
    print(f"  Found {len(player_ids)}/{len(all_players)} players")
    
    # Get season stats from Yahoo
    print("  Fetching season stats from Yahoo...")
    yahoo_stats = get_season_stats_from_yahoo(lg, list(player_ids.values()))
    print(f"  Retrieved stats for {len(yahoo_stats)} players")
    
    # Debug: Print keys from first player's stats
    if yahoo_stats:
        first_pid = list(yahoo_stats.keys())[0]
        first_stats = yahoo_stats[first_pid]
        print(f"  DEBUG - Sample stats keys: {list(first_stats.keys())}")
        print(f"  DEBUG - Sample stats values: GP={first_stats.get('GP')}, total_points={first_stats.get('total_points')}")
    
    # Build stats DataFrame
    rows = []
    players_processed = 0
    
    for player_name, player_id in player_ids.items():
        stats = yahoo_stats.get(player_id, {})
        
        # Extract total fantasy points from Yahoo
        total_fp = float(stats.get('total_points', 0) or 0)
        
        # Get NBA team from stats or playerlist
        nba_team = stats.get('editorial_team_abbr', '')
        if not nba_team:
            pl_match = playerlist[playerlist['player_name'] == player_name]
            if not pl_match.empty:
                nba_team = pl_match.iloc[0]['player_nba_team']
        
        # Get GP and MPG from nba_api (Yahoo doesn't provide GP!)
        gp = 0
        mpg = None
        gp_pct = 0.0
        
        if use_nba_api_for_gp and total_fp > 0:
            # Debug: show first player's nba_api call
            if players_processed == 0:
                print(f"  DEBUG - Calling nba_api for first player: {player_name}")
            
            actual_gp, team_breakdown, nba_mpg = get_player_game_logs_from_nba_api(
                player_name, week_end
            )
            
            if players_processed == 0:
                print(f"  DEBUG - nba_api returned: GP={actual_gp}, teams={team_breakdown}, mpg={nba_mpg}")
            
            if actual_gp > 0:
                gp = actual_gp
                gp_pct = calculate_gp_pct_with_trades(team_breakdown, nba_team_games)
                if nba_mpg is not None:
                    mpg = nba_mpg
            time.sleep(1.5)  # Rate limit nba_api (increased from 0.6s due to NBA.com restrictions)
        
        # Calculate FPPG
        fppg = total_fp / gp if gp > 0 else 0
        
        # Ensure GP% is reasonable (cap at 100%, floor at 0%)
        gp_pct = max(0.0, min(100.0, gp_pct))
        
        rows.append({
            'player_name': player_name,
            'fantasy_team': player_to_team.get(player_name, ''),
            'nba_team': nba_team,
            'total_fp': round(total_fp, 1),
            'fppg': round(fppg, 2),
            'gp': int(gp),
            'gp_pct': round(gp_pct, 1),
            'mpg': round(mpg, 1) if mpg is not None else None,
        })
        
        players_processed += 1
        if players_processed % 10 == 0:
            print(f"  Processed {players_processed}/{len(player_ids)} players...")
    
    df = pd.DataFrame(rows)
    
    # Add projection data from PLAYERLIST
    proj_lookup = playerlist.set_index('player_name').to_dict('index')
    
    df['proj_fppg_ros'] = df['player_name'].map(
        lambda x: proj_lookup.get(x, {}).get('projectedFPPG', 0)
    ).round(2)
    
    df['proj_fp_ros'] = df['player_name'].map(
        lambda x: proj_lookup.get(x, {}).get('player_total_proj_FP', 0)
    ).round(1)
    
    # Calculate Efficiency % as +/- vs projection
    # e.g., 121.5% efficiency becomes +21.5%, 86.6% becomes -13.4%
    df['eff_pct'] = (((df['fppg'] / df['proj_fppg_ros']) - 1) * 100).round(1)
    df.loc[df['proj_fppg_ros'] == 0, 'eff_pct'] = 0
    
    return df


# =============================================================================
# PUBLIC API
# =============================================================================

def generate_season_performers_data(
    week: int,
    base_path: Path,
    min_gp_pct: float = 50.0,
    use_nba_api_for_gp: bool = True
) -> Dict:
    """
    Generate season performer data as a dict (for inclusion in stats report).
    
    Args:
        week: Fantasy week number
        base_path: Path to project root directory
        min_gp_pct: Minimum GP% required for FPPG tables (default 50%)
        use_nba_api_for_gp: Whether to use nba_api for accurate GP% with trades
    
    Returns:
        Dict with keys:
        - best_total_fp: list of top 30 by total FP
        - best_fppg: list of top 30 by FPPG (qualified)
        - worst_total_fp: list of bottom 30 by total FP
        - worst_fppg: list of bottom 30 by FPPG (qualified)
        - min_gp_pct_threshold: the threshold used
    """
    base = Path(base_path)
    
    print(f"Generating season performers data for Week {week}...")
    
    # Load local data
    rosters = load_rosters(base)
    playerlist = load_playerlist(base)
    schedule = load_schedule(base)
    nba_schedule = load_nba_schedule(base)
    
    # Calculate team games through week end
    week_end = get_week_end_date(schedule, week)
    nba_team_games = calculate_team_games(nba_schedule, week_end)
    print(f"  Week {week} ends: {week_end.date()}")
    
    # Initialize Yahoo API
    lg = get_yahoo_league(base)
    
    # Reset nba_api failure counter before starting batch
    reset_nba_api_failure_counter()
    
    # Aggregate stats
    stats = aggregate_stats_from_yahoo(
        lg, rosters, playerlist, nba_team_games, week_end, use_nba_api_for_gp
    )
    
    # Helper to convert row to dict
    def row_to_dict(row):
        return {
            'player_name': row['player_name'],
            'fantasy_team': row['fantasy_team'],
            'nba_team': row['nba_team'],
            'total_fp': row['total_fp'],
            'fppg': row['fppg'],
            'gp': row['gp'],
            'gp_pct': row['gp_pct'],
            'mpg': row['mpg'],
            'eff_pct': row['eff_pct'],
            'proj_fp_ros': row['proj_fp_ros'],
            'proj_fppg_ros': row['proj_fppg_ros'],
        }
    
    # Filter for qualified players (min GP%)
    print(f"  Stats DataFrame shape: {stats.shape}")
    print(f"  GP values - min: {stats['gp'].min()}, max: {stats['gp'].max()}, mean: {stats['gp'].mean():.1f}")
    print(f"  GP% values - min: {stats['gp_pct'].min()}, max: {stats['gp_pct'].max()}, mean: {stats['gp_pct'].mean():.1f}")
    print(f"  Players with GP > 0: {len(stats[stats['gp'] > 0])}")
    print(f"  Players with GP% >= {min_gp_pct}: {len(stats[stats['gp_pct'] >= min_gp_pct])}")
    
    qualified = stats[stats['gp_pct'] >= min_gp_pct].copy()
    
    # If no qualified players, lower the threshold and warn
    if len(qualified) == 0:
        print(f"  Warning: No players met {min_gp_pct}% GP threshold, using all players with GP > 0")
        qualified = stats[stats['gp'] > 0].copy()
    
    # Generate lists (top 30 for paginated display in newsletter)
    # Best tables use all players (high totals are meaningful even with few games)
    best_total = stats.nlargest(30, 'total_fp')
    best_fppg = qualified.nlargest(30, 'fppg')
    
    # Worst tables require GP > 0 (exclude injured/out players)
    played_games = stats[stats['gp'] > 0].copy()
    worst_total = played_games.nsmallest(30, 'total_fp')
    worst_fppg = qualified.nsmallest(30, 'fppg')
    
    print(f"  Generated tables: {len(best_total)} best by total, {len(best_fppg)} best by FPPG")
    print(f"                    {len(worst_total)} worst by total, {len(worst_fppg)} worst by FPPG")
    
    return {
        'best_total_fp': [row_to_dict(row) for _, row in best_total.iterrows()],
        'best_fppg': [row_to_dict(row) for _, row in best_fppg.iterrows()],
        'worst_total_fp': [row_to_dict(row) for _, row in worst_total.iterrows()],
        'worst_fppg': [row_to_dict(row) for _, row in worst_fppg.iterrows()],
        'min_gp_pct_threshold': min_gp_pct,
    }


def build_season_performers(base_path: Path, week: int) -> Optional[Dict]:
    """
    Build season performers section for stats report.
    
    This is the function called by report_builder.py.
    
    Args:
        base_path: Path to project root
        week: Fantasy week number
        
    Returns:
        Season performers dict, or None if generation fails
    """
    try:
        return generate_season_performers_data(
            week=week,
            base_path=base_path,
            min_gp_pct=50.0,
            use_nba_api_for_gp=True  # Set to False for faster runs
        )
    except Exception as e:
        print(f"Warning: Could not generate season performers: {e}")
        import traceback
        traceback.print_exc()
        return None
