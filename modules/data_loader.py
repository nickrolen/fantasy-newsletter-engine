"""
data_loader.py

Loads and validates all input files for the fantasy basketball newsletter system.
Provides a centralized data access layer for all other modules.
"""

import json as _json_mod
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import date, datetime

import pandas as pd


# =============================================================================
# LEAGUE CONFIG (loaded from config/league_config.json)
# =============================================================================

def _load_league_config():
    """Load league configuration from config/league_config.json."""
    config_path = Path(__file__).parent.parent / "config" / "league_config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"League config not found at {config_path}. "
            f"Copy config/league_config.json.example and fill in your league details."
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return _json_mod.load(f)

_LEAGUE_CONFIG = _load_league_config()

# --- League identity (from config) ---
MANAGERS = _LEAGUE_CONFIG["managers"]
MANAGER_TO_TEAM = _LEAGUE_CONFIG["manager_to_team"]
TEAM_TO_MANAGER = {v: k for k, v in MANAGER_TO_TEAM.items()}
MANAGER_COLORS = _LEAGUE_CONFIG.get("manager_colors", {})
MANAGER_ALIASES = _LEAGUE_CONFIG.get("manager_aliases", {})
LEAGUE_NAME = _LEAGUE_CONFIG.get("league_name", "Fantasy Basketball League")
LEAGUE_NAME_SHORT = _LEAGUE_CONFIG.get("league_name_short", "Fantasy League")
BRAND_COLORS = _LEAGUE_CONFIG.get("brand_colors", {})
NUM_TEAMS = len(MANAGERS)

# --- Yahoo config (from config) ---
YAHOO_GAME_CODE = _LEAGUE_CONFIG.get("yahoo", {}).get("game_code", "nba")
LEAGUE_KEY = _LEAGUE_CONFIG.get("yahoo", {}).get("current_league_key", "")
HISTORICAL_LEAGUE_KEYS = _LEAGUE_CONFIG.get("yahoo", {}).get("historical_league_keys", {})

# --- League structure (from config) ---
LEAGUE_STRUCTURE = _LEAGUE_CONFIG.get("league_structure", {})
KEEPER_ERA_START = LEAGUE_STRUCTURE.get("keeper_era_start", "2021-22")

# --- Season config (from config) ---
SEASON_CONFIG = _LEAGUE_CONFIG.get("season", {})
CURRENT_SEASON = SEASON_CONFIG.get("current", "")
CURRENT_SEASON_LONG = SEASON_CONFIG.get("current_long", "")
REGULAR_SEASON_WEEKS = SEASON_CONFIG.get("regular_season_weeks", 21)
PLAYOFF_START_WEEK = SEASON_CONFIG.get("playoff_start_week", 22)
TOTAL_WEEKS = SEASON_CONFIG.get("total_weeks", 23)
SEASON_NUMBER = SEASON_CONFIG.get("season_number", 1)
NBA_SCHEDULE_FILE = SEASON_CONFIG.get("nba_schedule_file", "")

# --- Pre-data-era history (from config) ---
PRE_DATA_ERA = _LEAGUE_CONFIG.get("pre_data_era", {})

# --- Tiebreaker rules (from config) ---
TIEBREAKER_RULES = _LEAGUE_CONFIG.get("tiebreaker_rules", {})


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_PATHS = {
    "playerlog": "data/PLAYERLOG.xlsx",
    "lineups": "data/LINEUPS.xlsx",
    "playerlist": "data/PLAYERLIST.xlsx",
    "leaguehistory": "data/LEAGUEHISTORY.xlsx",
    "schedule": "config/SCHEDULE.json",
    "injury_overrides": "config/INJURY_OVERRIDES.json",
    "records": "config/RECORDS.json",
    "nba_schedule": NBA_SCHEDULE_FILE or "data/nba_schedule.json",
    "league_history_detailed": "data/LEAGUE_HISTORY_DETAILED.json",
    "all_matchups": "data/historical/all_matchups.json",
    "historical_playerlog": "data/historical/HISTORICAL_PLAYERLOG.json",
}

STARTER_SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "UTIL"]
BENCH_SLOTS = ["BN"]
IL_SLOTS = ["IL", "IL+"]

SLOT_ELIGIBILITY = {
    "PG": ["PG"],
    "SG": ["SG"],
    "G": ["PG", "SG"],
    "SF": ["SF"],
    "PF": ["PF"],
    "F": ["SF", "PF"],
    "C": ["C"],
    "UTIL": ["PG", "SG", "SF", "PF", "C"],
    "BN": ["PG", "SG", "SF", "PF", "C"],
    "IL": ["PG", "SG", "SF", "PF", "C"],
    "IL+": ["PG", "SG", "SF", "PF", "C"],
}

ROSTER_SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "UTIL", "UTIL",
                "BN", "BN", "BN", "IL", "IL", "IL+", "IL+"]


@dataclass
class FantasyData:
    """Container for all loaded fantasy data."""

    playerlog: pd.DataFrame = field(default_factory=pd.DataFrame)
    lineups: pd.DataFrame = field(default_factory=pd.DataFrame)
    playerlist: pd.DataFrame = field(default_factory=pd.DataFrame)
    leaguehistory: pd.DataFrame = field(default_factory=pd.DataFrame)

    schedule: dict = field(default_factory=dict)
    injury_overrides: dict = field(default_factory=dict)
    records: dict = field(default_factory=dict)
    nba_schedule: dict = field(default_factory=dict)
    league_history_detailed: Optional[dict] = None
    all_matchups: list = field(default_factory=list)
    historical_playerlog: list = field(default_factory=list)

    season_year: str = ""
    current_week: int = 0
    base_path: Path = field(default_factory=lambda: Path("."))

    def get_manager_record(self, manager: str, include_playoffs: bool = False) -> tuple[int, int]:
        """
        Get current season record for a manager as (wins, losses).

        By default, returns REGULAR-SEASON-ONLY records (weeks 1 through
        REGULAR_SEASON_WEEKS). Playoff weeks do not inflate the W-L --
        the league treats regular-season and playoff records as separate.

        Records are computed from RECORDS.json weekly_scores +
        SCHEDULE.json matchups so the result is correct regardless of
        what LEAGUEHISTORY.xlsx contains (manually entered, may already
        include playoff games).
        """
        if include_playoffs:
            max_week = TOTAL_WEEKS
        else:
            max_week = self.schedule.get("regular_season_weeks", REGULAR_SEASON_WEEKS)

        weekly_scores = self.records.get("weekly_scores", {})
        if isinstance(weekly_scores, dict) and weekly_scores:
            scores_by_week: dict[int, dict[str, float]] = {}
            for mgr, entries in weekly_scores.items():
                if not isinstance(entries, list):
                    continue
                for e in entries:
                    wk = e.get("week")
                    if wk is None or wk > max_week:
                        continue
                    scores_by_week.setdefault(wk, {})[mgr] = e.get("score", 0.0)

            wins = 0
            losses = 0
            for wk, mgr_scores in scores_by_week.items():
                for matchup in self.get_week_matchups(wk):
                    ma, mb = matchup["manager_a"], matchup["manager_b"]
                    if manager not in (ma, mb):
                        continue
                    sa = mgr_scores.get(ma)
                    sb = mgr_scores.get(mb)
                    if sa is None or sb is None:
                        continue
                    # Tie convention for W-L records: a tie counts as
                    # neither a win nor a loss. This is the standard W-L
                    # bookkeeping convention (matches Yahoo's own record
                    # display). Ties are essentially impossible with
                    # fractional scoring, but the rule is explicit.
                    if manager == ma:
                        if sa > sb:
                            wins += 1
                        elif sb > sa:
                            losses += 1
                    else:
                        if sb > sa:
                            wins += 1
                        elif sa > sb:
                            losses += 1
            if wins or losses:
                return (wins, losses)

        row = self.leaguehistory[self.leaguehistory["manager_name"] == manager]
        if row.empty:
            return (0, 0)
        record_str = row.iloc[0]["record_current_season"]
        record_str = record_str.strip("()")
        parts = record_str.split("-")
        try:
            return (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return (0, 0)

    def get_week_dates(self, week: int) -> tuple[date, date]:
        """Get start and end dates for a fantasy week."""
        for w in self.schedule.get("weeks", []):
            if w["week"] == week:
                start = datetime.strptime(w["start_date"], "%Y-%m-%d").date()
                end = datetime.strptime(w["end_date"], "%Y-%m-%d").date()
                return (start, end)
        raise ValueError(f"Week {week} not found in schedule")

    def get_week_matchups(self, week: int) -> list[dict]:
        """Get matchups for a given week."""
        for w in self.schedule.get("weeks", []):
            if w["week"] == week:
                return w["matchups"]
        return []

    def get_player_projection(self, player_name: str) -> Optional[float]:
        """Get projected FPPG for a player from PLAYERLIST."""
        row = self.playerlist[self.playerlist["player_name"] == player_name]
        if row.empty:
            return None
        return row.iloc[0]["projectedFPPG"]

    def get_player_injury_weeks(self, player_name: str) -> list[int]:
        """Get weeks a player is out due to injury override."""
        for player in self.injury_overrides.get("players", []):
            if player["player_name"].lower() == player_name.lower():
                return player.get("out_weeks", [])
        return []

    def get_player_return_info(self, player_name: str) -> dict:
        """Get return info for a player if they have a confirmed return."""
        for player in self.injury_overrides.get("players", []):
            if player["player_name"].lower() == player_name.lower():
                return_week = player.get("return_week")
                if return_week:
                    return {
                        "return_week": return_week,
                        "return_games": player.get("return_games"),
                        "total_week_games": player.get("total_week_games"),
                        "return_notes": player.get("return_notes", ""),
                        "return_date": player.get("return_date"),
                    }
        return {}

    def is_player_available(self, player_name: str, week: int) -> bool:
        """Check if player is available for a given week."""
        out_weeks = self.get_player_injury_weeks(player_name)
        return week not in out_weeks

    def get_roster_for_date(self, manager: str, game_date: date) -> pd.DataFrame:
        """Get a manager's roster for a specific date from LINEUPS."""
        date_str = game_date.strftime("%Y-%m-%d")
        mask = (
            (self.lineups["manager"] == manager) &
            (self.lineups["date"].astype(str) == date_str)
        )
        return self.lineups[mask].copy()

    def get_nba_games_for_date(self, game_date: date) -> list[dict]:
        """Get all NBA games scheduled for a date."""
        date_str = game_date.strftime("%Y-%m-%d")
        games = []

        if "leagueSchedule" in self.nba_schedule:
            for game_date_obj in self.nba_schedule["leagueSchedule"].get("gameDates", []):
                for game in game_date_obj.get("games", []):
                    game_date_est = game.get("gameDateEst", "")
                    if game_date_est.startswith(date_str):
                        if game.get("gameLabel", "").lower() == "preseason":
                            continue
                        games.append({
                            "date": date_str,
                            "home_team": game.get("homeTeam", {}).get("teamTricode", ""),
                            "away_team": game.get("awayTeam", {}).get("teamTricode", ""),
                        })
        else:
            for game in self.nba_schedule.get("games", []):
                game_date_raw = game.get("date", "")
                if game_date_raw.startswith(date_str):
                    games.append({
                        "date": date_str,
                        "home_team": game.get("home", game.get("home_team", "")),
                        "away_team": game.get("away", game.get("away_team", "")),
                    })

        return games

    def get_teams_playing_on_date(self, game_date: date) -> set[str]:
        """Get set of NBA team abbreviations playing on a date."""
        teams = set()
        for game in self.get_nba_games_for_date(game_date):
            home = game.get("home_team", game.get("home", "")).upper()
            away = game.get("away_team", game.get("away", "")).upper()
            if home:
                teams.add(home)
            if away:
                teams.add(away)
        return teams

    def get_free_agents(self) -> pd.DataFrame:
        """Get players who are in PLAYERLIST but not on any roster."""
        rosters_file = Path(__file__).parent.parent / "config" / "ROSTERS.json"
        if rosters_file.exists():
            try:
                import json
                with open(rosters_file, "r") as f:
                    config_data = json.load(f)
                config_rosters = config_data.get("rosters", config_data)
                rostered = set()
                for manager, players in config_rosters.items():
                    if isinstance(players, list):
                        rostered.update(players)
                return self.playerlist[~self.playerlist["player_name"].isin(rostered)].copy()
            except (json.JSONDecodeError, KeyError):
                pass

        most_recent_date = self.lineups["date"].max()
        rostered = self.lineups[self.lineups["date"] == most_recent_date]["player_name"].unique()
        return self.playerlist[~self.playerlist["player_name"].isin(rostered)].copy()

    def get_current_rosters(self) -> dict[str, list[str]]:
        """Get current rosters from ROSTERS.json."""
        rosters_file = Path(__file__).parent.parent / "config" / "ROSTERS.json"
        if rosters_file.exists():
            try:
                import json
                with open(rosters_file, "r") as f:
                    config_data = json.load(f)
                config_rosters = config_data.get("rosters", config_data)
                return {
                    manager: players
                    for manager, players in config_rosters.items()
                    if isinstance(players, list)
                }
            except (json.JSONDecodeError, KeyError):
                pass

        most_recent_date = self.lineups["date"].max()
        current = self.lineups[self.lineups["date"] == most_recent_date]
        rosters = {}
        for manager in MANAGERS:
            players = current[current["manager"] == manager]["player_name"].tolist()
            rosters[manager] = players
        return rosters


# =============================================================================
# LOADING FUNCTIONS
# =============================================================================

def normalize_manager_name(name: str) -> str:
    """Normalize manager name to canonical form using MANAGER_ALIASES from config."""
    name = str(name).strip()
    return MANAGER_ALIASES.get(name.lower(), name)


def load_excel_file(path: Path, required_columns: list[str] = None) -> pd.DataFrame:
    """Load an Excel file and validate required columns."""
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    if required_columns:
        missing = set(required_columns) - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns in {path.name}: {missing}")

    return df


def load_json_file(path: Path) -> dict:
    """Load a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_playerlog(path: Path) -> pd.DataFrame:
    """Load and validate PLAYERLOG.xlsx."""
    required = [
        "season_year", "week", "date", "manager", "fantasy_team",
        "player_name", "nba_team", "positions", "nba_opponent",
        "fantasy_points", "is_injured", "started"
    ]
    df = load_excel_file(path, required)
    df["manager"] = df["manager"].apply(normalize_manager_name)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["is_injured"] = df["is_injured"].fillna(False).astype(bool)
    df["started"] = df["started"].fillna(False).astype(bool)
    df["fantasy_points"] = pd.to_numeric(df["fantasy_points"], errors="coerce").fillna(0.0)
    return df


def load_lineups(path: Path) -> pd.DataFrame:
    """Load and validate LINEUPS.xlsx."""
    required = [
        "season_year", "week", "date", "manager", "fantasy_team",
        "player_name", "nba_team", "positions", "slot"
    ]
    df = load_excel_file(path, required)
    df["manager"] = df["manager"].apply(normalize_manager_name)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["slot"] = df["slot"].astype(str).str.upper()
    return df


def load_playerlist(path: Path) -> pd.DataFrame:
    """Load and validate PLAYERLIST.xlsx."""
    required = [
        "player_name", "player_nba_team", "player_position(s)",
        "player_total_proj_FP", "player_proj_GP", "projectedFPPG"
    ]
    df = load_excel_file(path, required)
    df["projectedFPPG"] = pd.to_numeric(df["projectedFPPG"], errors="coerce").fillna(0.0)
    return df


def load_leaguehistory(path: Path) -> pd.DataFrame:
    """Load and validate LEAGUEHISTORY.xlsx."""
    required = ["manager_name", "record_current_season", "total_points_current_season"]
    df = load_excel_file(path, required)
    df["manager_name"] = df["manager_name"].apply(normalize_manager_name)
    return df


def load_schedule(path: Path) -> dict:
    """Load and validate SCHEDULE.json."""
    data = load_json_file(path)
    required_keys = ["season_year", "total_weeks", "weeks"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"SCHEDULE.json missing required key: {key}")
    for week in data["weeks"]:
        if "week" not in week or "start_date" not in week or "end_date" not in week:
            raise ValueError(f"Invalid week entry in SCHEDULE.json: {week}")
    return data


def load_injury_overrides(path: Path) -> dict:
    """Load INJURY_OVERRIDES.json."""
    if not path.exists():
        return {"players": [], "last_updated": None}
    return load_json_file(path)


# =============================================================================
# TIE CONVENTIONS (project-wide)
# =============================================================================
# Fractional scoring (two decimal places) makes exact ties essentially
# impossible in real games, but the codebase still needs explicit rules
# for the rare edge case and -- more importantly -- for simulated weeks.
# Conventions:
#   * Simulations (title odds, playoff bracket, betting lines):
#         coin flip (random tiebreak). A simulated tie should resolve
#         either way with equal probability -- this is statistically
#         honest. See simulator_title_odds.py, simulator_playoff_odds.py,
#         simulator_betting.py.
#   * Actual completed games (playoff bracket resolution, historical
#         h2h reconstruction): "higher seed wins", implemented by
#         awarding the tie to manager_a (which is the higher-seeded
#         entry in SCHEDULE.json playoff matchups). Deterministic and
#         consistent. See simulator_playoff_odds.py:resolve_completed_week,
#         records_tracker.py.
#   * Luck index (all-play schedule-luck calc): split credit 0.5 wins
#         and 0.5 losses to each side. Mathematically correct for the
#         expected-wins comparison. See luck_index.py.
#   * W-L records (RECORDS.json, get_manager_record): tie counts as
#         neither a win nor a loss. Standard W-L bookkeeping convention.
# =============================================================================


def load_records(path: Path) -> dict:
    """Load RECORDS.json."""
    if not path.exists():
        return {
            "season_year": CURRENT_SEASON_LONG,
            "last_updated_week": 0,
            "title_odds_history": {},
            "season_records": {},
            "h2h_season": {},
            "cumulative_bench_points": {m: 0.0 for m in MANAGERS},
            "weekly_scores": []
        }
    return load_json_file(path)


def load_nba_schedule(path: Path) -> dict:
    """Load NBA schedule JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"NBA schedule file not found: {path}")
    return load_json_file(path)


def load_league_history_detailed(path: Path) -> Optional[dict]:
    """Load LEAGUE_HISTORY_DETAILED.json if it exists."""
    if not path.exists():
        return None
    return load_json_file(path)


def load_all_matchups(path: Path) -> list:
    """Load historical matchup data from all_matchups.json."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_historical_playerlog(path: Path) -> list:
    """Load HISTORICAL_PLAYERLOG.json for multi-year keepability scoring."""
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  Loaded {len(data):,} rows from HISTORICAL_PLAYERLOG.json")
        return data
    except Exception as e:
        print(f"  WARNING: Failed to load HISTORICAL_PLAYERLOG.json: {e}")
        return []


def load_all_data(
    base_path: str | Path = ".",
    paths: dict[str, str] = None,
    season_year: str = None,
    current_week: int = None,
) -> FantasyData:
    """Load all data files and return a FantasyData container."""
    if season_year is None:
        season_year = CURRENT_SEASON_LONG
    base = Path(base_path)
    file_paths = {**DEFAULT_PATHS, **(paths or {})}

    data = FantasyData(
        playerlog=load_playerlog(base / file_paths["playerlog"]),
        lineups=load_lineups(base / file_paths["lineups"]),
        playerlist=load_playerlist(base / file_paths["playerlist"]),
        leaguehistory=load_leaguehistory(base / file_paths["leaguehistory"]),
        schedule=load_schedule(base / file_paths["schedule"]),
        injury_overrides=load_injury_overrides(base / file_paths["injury_overrides"]),
        records=load_records(base / file_paths["records"]),
        nba_schedule=load_nba_schedule(base / file_paths["nba_schedule"]),
        league_history_detailed=load_league_history_detailed(
            base / file_paths["league_history_detailed"]
        ),
        all_matchups=load_all_matchups(base / file_paths["all_matchups"]),
        historical_playerlog=load_historical_playerlog(
            base / file_paths["historical_playerlog"]
        ),
        season_year=season_year,
        current_week=current_week or 0,
        base_path=base,
    )

    if current_week is None:
        max_week = data.playerlog["week"].max()
        data.current_week = int(max_week) if pd.notna(max_week) else 0

    return data


def save_records(records: dict, path: Path) -> None:
    """Save updated RECORDS.json."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_position_list(positions_str: str) -> list[str]:
    """Parse a positions string like 'PG,SG,SF' into a list."""
    if pd.isna(positions_str) or not positions_str:
        return []
    return [p.strip().upper() for p in str(positions_str).split(",")]


def classify_position_group(positions) -> str:
    """Classify a player into G, F, or C based on Yahoo position tags."""
    if isinstance(positions, str):
        if pd.isna(positions) or not positions.strip():
            return "F"
        tags = [t.strip().upper() for t in positions.split(",")]
    elif isinstance(positions, (list, tuple)):
        tags = [t.strip().upper() for t in positions if t]
    else:
        return "F"

    if not tags:
        return "F"

    g = sum(1 for t in tags if t in ("PG", "SG"))
    f = sum(1 for t in tags if t in ("SF", "PF"))
    c = sum(1 for t in tags if t == "C")
    mx = max(g, f, c)

    if c == mx and c >= f and c >= g:
        return "C"
    if f == mx and f >= g:
        return "F"
    return "G"


def player_eligible_for_slot(player_positions: list[str], slot: str) -> bool:
    """Check if a player can fill a given slot based on position eligibility."""
    eligible = SLOT_ELIGIBILITY.get(slot.upper(), [])
    return any(pos in eligible for pos in player_positions)


def parse_record_string(record_str: str) -> tuple[int, int]:
    """Parse a record string like '(8-3)' into (wins, losses)."""
    record_str = str(record_str).strip("()")
    parts = record_str.split("-")
    if len(parts) != 2:
        return (0, 0)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (0, 0)


if __name__ == "__main__":
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    print(f"Loading data from: {base.absolute()}")
    try:
        data = load_all_data(base)
        for manager in MANAGERS:
            wins, losses = data.get_manager_record(manager)
            print(f"  {manager}: {wins}-{losses}")
    except Exception as e:
        print(f"Error: {e}")
        raise
