import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import unicodedata

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import (
    LEAGUE_KEY, CURRENT_SEASON, CURRENT_SEASON_LONG,
    TEAM_TO_MANAGER, YAHOO_GAME_CODE, NBA_SCHEDULE_FILE,
)

# ---------- CONFIGURATION ----------

NBA_SEASON = CURRENT_SEASON
SEASON_YEAR_LABEL = CURRENT_SEASON_LONG
FANTASY_TEAM_TO_MANAGER = TEAM_TO_MANAGER

# Reverse mapping: manager -> fantasy team
MANAGER_TO_FANTASY_TEAM = {v: k for k, v in FANTASY_TEAM_TO_MANAGER.items()}

# Path to schedule file (relative to script location or CWD)
SCHEDULE_JSON_PATH = "config/SCHEDULE.json"

LINEUPS_XLSX_PATH = "data/LINEUPS.xlsx"
PLAYERLOG_XLSX_PATH = "data/PLAYERLOG.xlsx"
SOURCE_TAG = "yahoo_api"

# Positions that should NOT appear in the "positions" column
EXCLUDE_FROM_POSITIONS = {"UTIL", "IL", "IL+", "BN", "G", "F"}


# ---------- SCHEDULE LOADING ----------

def load_schedule(base_path: Path = None) -> dict:
    """Load SCHEDULE.json and return the full schedule dict."""
    if base_path is None:
        base_path = Path(".")
    
    schedule_path = base_path / SCHEDULE_JSON_PATH
    
    if not schedule_path.exists():
        print(f"WARNING: Schedule file not found at {schedule_path}")
        return {}
    
    with open(schedule_path, 'r') as f:
        return json.load(f)


def build_matchups_by_week(schedule: dict) -> dict:
    """
    Build a mapping of week -> {fantasy_team -> opponent_fantasy_team}
    from the SCHEDULE.json data.
    
    This replaces the old hardcoded MATCHUPS_BY_WEEK dictionary.
    """
    matchups_by_week = {}
    
    for week_data in schedule.get("weeks", []):
        week_num = week_data["week"]
        week_matchups = {}
        
        for matchup in week_data.get("matchups", []):
            manager_a = matchup["manager_a"]
            manager_b = matchup["manager_b"]
            
            # Convert manager names to fantasy team names
            team_a = MANAGER_TO_FANTASY_TEAM.get(manager_a)
            team_b = MANAGER_TO_FANTASY_TEAM.get(manager_b)
            
            if team_a and team_b:
                # Each team maps to their opponent
                week_matchups[team_a] = team_b
                week_matchups[team_b] = team_a
        
        if week_matchups:
            matchups_by_week[week_num] = week_matchups
    
    return matchups_by_week


# Global matchups dict - loaded once at module import
_SCHEDULE = load_schedule()
MATCHUPS_BY_WEEK = build_matchups_by_week(_SCHEDULE)


# ---------- HELPERS ----------


def get_league(oauth: OAuth2) -> yfa.League:
    """Return League object for your NBA league."""
    return yfa.League(oauth, LEAGUE_KEY)


def find_week_for_date(lg: yfa.League, target_date: dt.date) -> int:
    """Map a calendar date to the Yahoo fantasy week number."""
    end_week = lg.end_week()
    for week in range(1, end_week + 1):
        start, end = lg.week_date_range(week)
        if start <= target_date <= end:
            return week
    raise ValueError(f"{target_date} is not inside any Yahoo week range")


def build_team_meta(lg: yfa.League):
    """Get Yahoo team objects and names."""
    teams_json = lg.teams()
    meta = []
    for team_key, data in teams_json.items():
        name = data["name"]
        team_obj = lg.to_team(team_key)
        meta.append(
            {
                "team_key": team_key,
                "fantasy_team": name,
                "manager": FANTASY_TEAM_TO_MANAGER.get(name, ""),
                "team_obj": team_obj,
            }
        )
    return meta


def get_opponent_manager(fantasy_team: str, week: int) -> str:
    """
    Look up opponent manager for a given fantasy team and week.
    
    Uses the dynamically-loaded MATCHUPS_BY_WEEK from SCHEDULE.json.
    Returns empty string if not found.
    """
    weekly = MATCHUPS_BY_WEEK.get(week)
    if not weekly:
        return ""
    opp_team = weekly.get(fantasy_team)
    if not opp_team:
        return ""
    return FANTASY_TEAM_TO_MANAGER.get(opp_team, "")


def strip_accents(text: str) -> str:
    """Return ASCII-only version of a name (e.g., 'Don??i??' -> 'Doncic')."""
    if not isinstance(text, str):
        return text
    # Normalize, then drop non-ASCII characters
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def get_daily_rosters(lg: yfa.League, target_date: dt.date):
    """
    Pull each team's roster for a specific calendar date.

    Returns:
        roster_rows: list of dicts (one per player slot)
        all_player_ids: sorted list of unique Yahoo player_ids
    """
    team_meta = build_team_meta(lg)
    roster_rows = []
    player_ids = set()

    for tm in team_meta:
        fantasy_team = tm["fantasy_team"]
        manager = tm["manager"]
        team_obj = tm["team_obj"]

        yahoo_roster = team_obj.roster(day=target_date)

        for plyr in yahoo_roster:
            player_id = int(plyr["player_id"])
            name = strip_accents(plyr["name"])
            slot = plyr.get("selected_position")

            # Eligible positions, but drop UTIL / IL / IL+ / BN
            raw_elig = plyr.get("eligible_positions", [])
            if isinstance(raw_elig, list):
                filtered_elig = [
                    p for p in raw_elig
                    if str(p).upper() not in EXCLUDE_FROM_POSITIONS
                ]
                positions = ",".join(filtered_elig)
            else:
                positions = str(raw_elig) if raw_elig is not None else ""

            roster_rows.append(
                {
                    "fantasy_team": fantasy_team,
                    "manager": manager,
                    "player_id": player_id,
                    "player_name": name,
                    "positions": positions,
                    "slot": slot,
                }
            )
            player_ids.add(player_id)

    return roster_rows, sorted(player_ids)


def build_player_team_map(lg: yfa.League, player_ids):
    """Map player_id -> NBA team abbreviation."""
    details = lg.player_details(player_ids)
    by_id = {}
    for p in details:
        pid = int(p["player_id"])
        nba_team = p.get("editorial_team_abbr")
        by_id[pid] = {
            "nba_team": nba_team,
            "raw": p,
        }
    return by_id


def get_player_stats_for_date(lg: yfa.League, player_ids, target_date: dt.date):
    """player_id -> raw stats dict for that date."""
    stats_list = lg.player_stats(player_ids, "date", date=target_date)
    by_id = {}
    for row in stats_list:
        pid = int(row["player_id"])
        by_id[pid] = row
    return by_id


def _get_stat(row: dict, *keys: str) -> float:
    """Safely read a stat value, trying several possible keys."""
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def compute_fantasy_points(stat_row: dict) -> float:
    """
    Use Yahoo's own fantasy points for that date.

    The 'total_points' field in stat_row is the fantasy score for
    your league's scoring settings on that day.
    """
    try:
        return round(float(stat_row.get("total_points", 0.0)), 2)
    except (TypeError, ValueError):
        return 0.0


def build_nba_schedule_map():
    """
    Build (TEAM_ABBREVIATION, date) -> '@OPP' or 'OPP' mapping
    using the local nba_schedule_2025-26.json file (already downloaded
    by fetch_nba_schedule.py).  This avoids calling the flaky NBA stats
    API which frequently drops connections.
    """
    # Locate the schedule file relative to this script.
    # NBA_SCHEDULE_FILE already contains the "data/" prefix (e.g. "data/nba_schedule_2025-26.json"),
    # so join it directly to project_root -- mirrors how data_loader.py resolves the same config value.
    script_dir = Path(__file__).parent          # scripts/
    project_root = script_dir.parent            # newsletter/
    schedule_path = project_root / NBA_SCHEDULE_FILE

    if not schedule_path.exists():
        raise FileNotFoundError(
            f"NBA schedule file not found at {schedule_path}. "
            f"Run: python scripts/fetch_nba_schedule.py --season {CURRENT_SEASON} "
            f"--output {NBA_SCHEDULE_FILE}"
        )

    with open(schedule_path, "r") as f:
        data = json.load(f)

    schedule = {}
    for game in data.get("games", []):
        # Date field is like "2025-10-22T00:00:00Z" -- grab just the date part
        raw_date = game.get("date", "")
        try:
            game_date = dt.date.fromisoformat(raw_date[:10])
        except ValueError:
            continue

        home = str(game.get("home", "")).upper()
        away = str(game.get("away", "")).upper()

        if home and away:
            schedule[(home, game_date)] = away       # home team sees away as opp
            schedule[(away, game_date)] = f"@{home}" # away team sees @home as opp

    return schedule


def lookup_nba_opponent(nba_team: str, date: dt.date, schedule_map):
    if not nba_team:
        return "", False
    key = (nba_team.upper(), date)
    opp = schedule_map.get(key)
    if opp:
        return opp, True
    return "", False


def build_daily_dataframes(lg: yfa.League, target_date: dt.date):
    week = find_week_for_date(lg, target_date)
    roster_rows, player_ids = get_daily_rosters(lg, target_date)
    player_team_map = build_player_team_map(lg, player_ids)
    stats_by_pid = get_player_stats_for_date(lg, player_ids, target_date)

    schedule_map = build_nba_schedule_map()

    lineups_rows = []
    playerlog_rows = []

    for rr in roster_rows:
        fantasy_team = rr["fantasy_team"]
        manager = rr["manager"]
        player_id = rr["player_id"]
        player_name = rr["player_name"]
        slot = rr["slot"]
        positions = rr["positions"]

        team_info = player_team_map.get(player_id, {})
        nba_team = team_info.get("nba_team")

        nba_opponent, had_game = lookup_nba_opponent(nba_team, target_date, schedule_map)

        stat_row = stats_by_pid.get(player_id, {})
        fantasy_points = compute_fantasy_points(stat_row) if had_game else None
        is_injured = bool(had_game and fantasy_points == 0.0)
        started = slot not in ("BN", "IL", "IL+", None, "")

        opponent_manager = get_opponent_manager(fantasy_team, week)

        lineups_rows.append(
            {
                "season_year": SEASON_YEAR_LABEL,
                "week": week,
                "date": target_date,
                "manager": manager,
                "fantasy_team": fantasy_team,
                "player_name": player_name,
                "nba_team": nba_team,
                "positions": positions,
                "slot": slot,
                "nba_opponent": nba_opponent if had_game else "",
                "fantasy_points": fantasy_points if had_game else "",
                "source": SOURCE_TAG,
                "notes": "",
                "opponent_manager": opponent_manager or "",
            }
        )

        if had_game:
            playerlog_rows.append(
                {
                    "season_year": SEASON_YEAR_LABEL,
                    "week": week,
                    "date": target_date,
                    "manager": manager,
                    "fantasy_team": fantasy_team,
                    "player_name": player_name,
                    "nba_team": nba_team,
                    "positions": positions,
                    "nba_opponent": nba_opponent,
                    "fantasy_points": fantasy_points,
                    "opponent_manager": opponent_manager or "",
                    "source": SOURCE_TAG,
                    "notes": "",
                    "is_injured": is_injured,
                    "started": started,
                }
            )

    lineups_df = pd.DataFrame(lineups_rows)
    playerlog_df = pd.DataFrame(playerlog_rows)

    # Enforce column order to match existing files
    lineups_df = lineups_df[
        [
            "season_year",
            "week",
            "date",
            "manager",
            "fantasy_team",
            "player_name",
            "nba_team",
            "positions",
            "slot",
            "nba_opponent",
            "fantasy_points",
            "source",
            "notes",
            "opponent_manager",
        ]
    ]

    print("DEBUG playerlog_df type:", type(playerlog_df))
    try:
        print("DEBUG playerlog_df shape:", playerlog_df.shape)
        print("DEBUG playerlog_df columns:", list(playerlog_df.columns))
        print("DEBUG head:\n", playerlog_df.head(3))
    except Exception as e:
        print("DEBUG could not introspect playerlog_df:", e)
        print("DEBUG raw playerlog_df:", playerlog_df)

    if playerlog_df.empty:
        playerlog_df = pd.DataFrame(columns=[
            "season_year","week","date","manager","fantasy_team","player_name","nba_team",
            "positions","nba_opponent","fantasy_points","opponent_manager","source","notes",
            "is_injured","started"
        ])

    playerlog_df = playerlog_df[
        [
            "season_year",
            "week",
            "date",
            "manager",
            "fantasy_team",
            "player_name",
            "nba_team",
            "positions",
            "nba_opponent",
            "fantasy_points",
            "opponent_manager",
            "source",
            "notes",
            "is_injured",
            "started",
        ]
    ]

    return lineups_df, playerlog_df


def append_to_excel(path: str, new_df: pd.DataFrame, key_columns):
    """Append new_df into Excel at path, dropping duplicates on key_columns.

    IMPORTANT: date normalization happens BEFORE drop_duplicates(). Existing rows
    are stored as YYYY-MM-DD strings; incoming rows arrive as datetime.date objects.
    If we deduped first, those would never compare equal and re-pulling an already-
    logged day would append full duplicates (see fix C3).
    """
    try:
        existing = pd.read_excel(path)
    except FileNotFoundError:
        existing = pd.DataFrame(columns=new_df.columns)

    combined = pd.concat([existing, new_df], ignore_index=True)

    # Normalize date column FIRST so dedup compares like-with-like.
    # Store as YYYY-MM-DD string (no time).
    if "date" in combined.columns:
        combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")

    if key_columns:
        combined = combined.drop_duplicates(subset=key_columns, keep="last")

    # Preserve original column order if file already existed
    if not existing.empty:
        combined = combined[existing.columns]

    # Write normally (no date_format kwarg)
    combined.to_excel(path, index=False)


def main():
    parser = argparse.ArgumentParser(description="Append Yahoo stats into LINEUPS/PLAYERLOG.")
    parser.add_argument(
        "--date",
        help="Date to pull (YYYY-MM-DD). If omitted, uses today.",
        default=None,
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default=".",
        help="Base path to project directory (default: current directory)",
    )
    args = parser.parse_args()

    # Reload schedule if base-path is specified
    if args.base_path != ".":
        global _SCHEDULE, MATCHUPS_BY_WEEK
        _SCHEDULE = load_schedule(Path(args.base_path))
        MATCHUPS_BY_WEEK = build_matchups_by_week(_SCHEDULE)

    if args.date:
        target_date = dt.datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = dt.date.today()

    # Show which week we're processing
    print(f"Processing date: {target_date}")
    print(f"Loaded {len(MATCHUPS_BY_WEEK)} weeks of matchups from SCHEDULE.json")
    
    oauth = OAuth2(None, None, from_file="oauth2.json")
    if not oauth.token_is_valid():
        oauth.refresh_access_token()

    lg = get_league(oauth)
    
    # Show the matchup for this week
    week = find_week_for_date(lg, target_date)
    print(f"Fantasy week: {week}")
    if week in MATCHUPS_BY_WEEK:
        print(f"Matchups for week {week}:")
        seen = set()
        for team, opp in MATCHUPS_BY_WEEK[week].items():
            matchup_key = tuple(sorted([team, opp]))
            if matchup_key not in seen:
                seen.add(matchup_key)
                print(f"  {team} vs {opp}")
    print()

    lineups_df, playerlog_df = build_daily_dataframes(lg, target_date)

    # Use base_path for file locations
    base = Path(args.base_path)
    lineups_path = base / LINEUPS_XLSX_PATH
    playerlog_path = base / PLAYERLOG_XLSX_PATH

    append_to_excel(
        str(lineups_path),
        lineups_df,
        key_columns=["season_year", "date", "manager", "player_name", "slot"],
    )
    append_to_excel(
        str(playerlog_path),
        playerlog_df,
        key_columns=["season_year", "date", "manager", "player_name"],
    )

    print(
        f"Done. Wrote {len(lineups_df)} LINEUPS rows and "
        f"{len(playerlog_df)} PLAYERLOG rows for {target_date}."
    )


if __name__ == "__main__":
    main()
