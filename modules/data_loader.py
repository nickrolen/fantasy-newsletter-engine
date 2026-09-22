"""
data_loader.py

Loads and validates all input files for the fantasy basketball newsletter system.
Provides a centralized data access layer for all other modules.
"""

import json
import re
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
        return json.load(f)

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

# Per-season week layout. REGULAR_SEASON_WEEKS describes only the CURRENT
# season; historical seasons have had different shapes and anything walking
# history must not assume one boundary for all time. See league_config.json
# "season_structure" for the values and the derivation.
SEASON_STRUCTURE = _LEAGUE_CONFIG.get("season_structure", {})
PLAYOFF_START_WEEK = SEASON_CONFIG.get("playoff_start_week", 22)
TOTAL_WEEKS = SEASON_CONFIG.get("total_weeks", 23)
SEASON_NUMBER = SEASON_CONFIG.get("season_number", 1)
NBA_SCHEDULE_FILE = SEASON_CONFIG.get("nba_schedule_file", "")

# --- Pre-data-era history (from config) ---
PRE_DATA_ERA = _LEAGUE_CONFIG.get("pre_data_era", {})

# --- Tiebreaker rules (from config) ---
TIEBREAKER_RULES = _LEAGUE_CONFIG.get("tiebreaker_rules", {})

# --- Postseason format, keeper rules and payouts (from config) ---
# From 2026-27 the season is three stages, not two: a 15-week regular season,
# a six-week best-of-3 playoff bracket, then a two-week Cup. The old rule
# ("the bracket is the last two weeks") describes seasons through 2025-26 only.
POSTSEASON_FORMAT = _LEAGUE_CONFIG.get("postseason_format", {})
KEEPER_RULES = _LEAGUE_CONFIG.get("keeper_rules", {})
PAYOUTS = _LEAGUE_CONFIG.get("payouts", {})

# Total draft rounds is fixed by the roster: you draft into every non-IL spot.
# Unlike total_draft_rounds (live picks) this does not move when keeper counts
# change, so anything iterating rounds should use it.
TOTAL_ROUNDS = LEAGUE_STRUCTURE.get(
    "total_rounds",
    LEAGUE_STRUCTURE.get("roster_size", 17) - LEAGUE_STRUCTURE.get("il_slots", 2))


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

# Current roster shape (2026-27): 10 starters + 5 bench + 2 IL = 17.
# Through Week 15 of 2025-26 it was 10 starters + 3 BN + 2 IL + 2 IL+; the
# league converted the two IL+ slots to bench slots effective Week 16
# (2026-02-02), which is also why the draft grew from 13 rounds to 15.
#
# IL+ is intentionally still handled elsewhere (IL_SLOTS, SLOT_ELIGIBILITY,
# the bench-slot filters in weekly_stats and consistency_score) because every
# season through 2025-26 Week 15 has IL+ rows in its lineup data.
ROSTER_SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "UTIL", "UTIL",
                "BN", "BN", "BN", "BN", "BN", "IL", "IL"]


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
            # Deliberately NOT self.schedule["regular_season_weeks"]: the boundary comes from league_config, not SCHEDULE.json. That file is written per season and is the PREVIOUS season's for the whole preseason, so reading week counts out of it silently applies last year's shape -- 21 regular-season weeks where 2026-27 has 15.
            max_week = regular_season_weeks_for(CURRENT_SEASON)

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


def regular_season_weeks_for(season, default=None):
    """Last regular-season week for `season`.

    The regular/playoff boundary is not a fixed week number. The bracket is
    always the last two fantasy weeks, and how many fantasy weeks a season
    contains varies -- Yahoo stretches any week holding the All-Star break to
    14 days, so a season can cover the same calendar in fewer weeks. Known
    cases: 2019-20 ended at week 19 with no bracket, 2020-21 ran 18 weeks with
    the bracket at 17-18, and 2021-22 ran 22 weeks with the bracket at 21-22.

    Falls back to the current season's value when a season is not listed.
    """
    entry = SEASON_STRUCTURE.get(str(season))
    if isinstance(entry, dict):
        through = entry.get("regular_through")
        if through:
            return int(through)
    return int(REGULAR_SEASON_WEEKS if default is None else default)


def is_regular_season_week(season, week, default=None):
    """True if (season, week) falls in that season's regular season."""
    try:
        return int(week) <= regular_season_weeks_for(season, default)
    except (TypeError, ValueError):
        return False


def resolve_league_key(explicit=None):
    """(league_key, source) for a Yahoo call, or (None, reason) if there is none.

    yahoo.current_league_key is deliberately empty between the season reset
    and Yahoo provisioning the new league -- leaving last season's key there
    would make every script silently pull the wrong season. But an empty key
    still builds a URL: /fantasy/v2/league//settings, which Yahoo rejects.
    A diagnostic that makes that request reads the rejection as a permission
    problem and tells you to rebuild your app, which is what happened.

    So: resolve it explicitly, and say which key is being used and why.
    """
    if explicit:
        return explicit, "passed on the command line"
    if LEAGUE_KEY:
        return LEAGUE_KEY, f"yahoo.current_league_key ({CURRENT_SEASON})"
    if HISTORICAL_LEAGUE_KEYS:
        season = max(HISTORICAL_LEAGUE_KEYS)
        return HISTORICAL_LEAGUE_KEYS[season], (
            f"most recent historical league ({season}) -- "
            "yahoo.current_league_key is empty")
    return None, ("no league key: yahoo.current_league_key is empty and there "
                  "are no historical keys. Pass --league-key.")


def season_had_bracket(season):
    """True if `season` played a postseason bracket (2019-20 did not)."""
    entry = SEASON_STRUCTURE.get(str(season))
    if isinstance(entry, dict) and "bracket" in entry:
        return bool(entry["bracket"])
    return True


# =============================================================================
# SEASON FORMAT (2026-27 onward)
# =============================================================================
# Season keys are "YYYY-YY" and sort correctly as plain strings, which is what
# every _at_or_after comparison below relies on.

def _at_or_after(season, threshold):
    """True if `season` is `threshold` or a later season."""
    if not season or not threshold:
        return False
    return str(season) >= str(threshold)


def uses_three_stage_format(season=None):
    """True if `season` uses the regular / playoffs / cup format.

    Seasons before postseason_format.effective_from played the old shape: a
    single-game, two-week bracket in the final two weeks and nothing after it.
    """
    if season is None:
        season = CURRENT_SEASON
    entry = SEASON_STRUCTURE.get(str(season))
    if isinstance(entry, dict) and entry.get("format"):
        return entry["format"] == POSTSEASON_FORMAT.get("name", "three_stage")
    return _at_or_after(season, POSTSEASON_FORMAT.get("effective_from"))


def _stage(stage):
    return POSTSEASON_FORMAT.get("stages", {}).get(stage, {})


def stage_weeks(season, stage):
    """Inclusive (first_week, last_week) for a stage, or None.

    Stage is "regular_season", "playoffs" or "cup". Returns None when the
    season did not have that stage at all -- every season before 2026-27 has
    no cup, and 2019-20 has no playoffs either.
    """
    season = str(season) if season is not None else CURRENT_SEASON
    entry = SEASON_STRUCTURE.get(season)
    entry = entry if isinstance(entry, dict) else {}

    # A listed season with regular_through explicitly null has no week-level
    # data at all -- 2014-15 and 2015-16 predate Yahoo and survive only as
    # to-date totals in LEAGUEHISTORY.xlsx. Falling back to the current
    # season's week count here would invent a schedule for them.
    if "regular_through" in entry and entry["regular_through"] is None:
        return None

    if stage == "regular_season":
        return (1, regular_season_weeks_for(season))

    if not uses_three_stage_format(season):
        # Legacy shape: the bracket is the two weeks after the regular season,
        # and there is no cup.
        if stage == "cup" or not season_had_bracket(season):
            return None
        last = regular_season_weeks_for(season)
        return (last + 1, last + 2)

    if not season_had_bracket(season) and stage == "playoffs":
        return None
    key = "playoff_weeks" if stage == "playoffs" else "cup_weeks"
    weeks = entry.get(key) or _stage(stage).get("weeks")
    if not weeks:
        return None
    return (int(weeks[0]), int(weeks[-1]))


def phase_for_week(season, week):
    """Which stage (season, week) belongs to: regular_season / playoffs / cup.

    Returns None for a week outside the season entirely.
    """
    try:
        week = int(week)
    except (TypeError, ValueError):
        return None
    for stage in ("regular_season", "playoffs", "cup"):
        span = stage_weeks(season, stage)
        if span and span[0] <= week <= span[1]:
            return stage
    return None


def is_playoff_week(season, week):
    """True if (season, week) is part of the playoff bracket."""
    return phase_for_week(season, week) == "playoffs"


def is_cup_week(season, week):
    """True if (season, week) is part of the Cup."""
    return phase_for_week(season, week) == "cup"


def is_postseason_week(season, week):
    """True for any week after the regular season -- playoffs OR cup.

    Not the same as `not is_regular_season_week(...)`, which is also true for
    a week that falls outside the season altogether.
    """
    return phase_for_week(season, week) in ("playoffs", "cup")


def stage_rounds(season, stage):
    """Concrete rounds for a stage: [{name, weeks: (first, last), ...}].

    Empty when the season has no such stage. Used by the simulators so the
    bracket shape lives in config rather than in module constants.
    """
    span = stage_weeks(season, stage)
    if span is None:
        return []

    if not uses_three_stage_format(season):
        # Legacy shape: one semifinal week then one final week, and the
        # third-place game shares the final week. The new format's round
        # definitions describe six weeks and must not be applied to a season
        # that only ever played two.
        first, last = span
        return [
            {"name": "Semifinals", "weeks": (first, first), "seeds": [[1, 4], [2, 3]]},
            {"name": "Final", "weeks": (last, last), "field": "semifinal winners"},
            {"name": "Third Place", "weeks": (last, last), "field": "semifinal losers"},
        ]

    rounds = []
    for rnd in _stage(stage).get("rounds", []):
        weeks = rnd.get("weeks")
        if not weeks:
            continue
        out = dict(rnd)
        out["weeks"] = (int(weeks[0]), int(weeks[-1]))
        rounds.append(out)
    return rounds


def series_length(season, stage="playoffs"):
    """Weeks per playoff series: 3 under the new format, 1 under the old."""
    if stage == "cup" or not uses_three_stage_format(season):
        return 1
    fmt = _stage(stage).get("series_format", "best_of_1")
    match = re.search(r"(\d+)", str(fmt))
    return int(match.group(1)) if match else 1


# =============================================================================
# KEEPER COUNTS (per season, and NOT necessarily uniform across managers)
# =============================================================================
# Through 2026-27 every manager keeps the same number, so a single scalar
# (league_structure.keepers_per_team) is enough. From 2027-28 the previous
# season's Cup winner keeps one extra, so the count is per manager and the
# draft has a round with three picks in it instead of four. Anything that
# needs a keeper count must go through keepers_for(); the scalar is kept only
# for the current season and for reading old data.

def keeper_rules_for(season=None):
    """The {base, cup_winner_bonus} rule in force for `season`."""
    if season is None:
        season = CURRENT_SEASON
    season = str(season)
    listed = KEEPER_RULES.get("seasons", {})
    if season in listed and isinstance(listed[season], dict):
        rule = listed[season]
    else:
        rule = KEEPER_RULES.get("default", {})
        if not _at_or_after(season, rule.get("effective_from")):
            # Before the default takes effect and not listed: fall back to the
            # uniform scalar, which is how every pre-2027-28 season worked.
            return {"base": int(LEAGUE_STRUCTURE.get("keepers_per_team", 6)),
                    "cup_winner_bonus": 0}
    return {"base": int(rule.get("base", LEAGUE_STRUCTURE.get("keepers_per_team", 6))),
            "cup_winner_bonus": int(rule.get("cup_winner_bonus", 0))}


def cup_winner(season):
    """Who won `season`'s Cup, or None if unplayed/unrecorded."""
    return KEEPER_RULES.get("cup_winners", {}).get(str(season))


def _prior_season(season):
    """"2027-28" -> "2026-27". Returns None if unparseable."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(season))
    if not match:
        return None
    start = int(match.group(1)) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def keepers_for(season=None, manager=None):
    """Keeper count for `season`.

    With a manager, returns that manager's count as an int. Without one,
    returns {manager: count} for every manager.

    The bonus goes to whoever won the PREVIOUS season's Cup. If that result is
    not recorded in keeper_rules.cup_winners this does not guess -- everyone
    gets the base count, which will be visibly one short rather than silently
    assigned to the wrong manager.
    """
    if season is None:
        season = CURRENT_SEASON
    rule = keeper_rules_for(season)
    counts = {m: rule["base"] for m in MANAGERS}
    if rule["cup_winner_bonus"]:
        holder = cup_winner(_prior_season(season))
        if holder in counts:
            counts[holder] += rule["cup_winner_bonus"]
    if manager is not None:
        return counts.get(manager, rule["base"])
    return counts


def live_picks_for(season=None, manager=None):
    """Drafted (non-keeper) picks for `season`: TOTAL_ROUNDS - keepers.

    With a manager, an int; without one, {manager: count}. In 2026-27 that is
    9 for everybody; in 2027-28 it is 9 for the Cup winner and 10 for the rest.
    """
    keepers = keepers_for(season, manager)
    if manager is not None:
        return TOTAL_ROUNDS - keepers
    return {m: TOTAL_ROUNDS - k for m, k in keepers.items()}


def first_keeper_round(season=None, manager=None):
    """The first round a manager's keepers occupy (keepers take the LAST rounds).

    2026-27: round 10 for everyone. 2027-28: round 10 for the Cup winner,
    round 11 for the other three.
    """
    picks = live_picks_for(season, manager)
    if manager is not None:
        return picks + 1
    return {m: p + 1 for m, p in picks.items()}


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


def atomic_write_json(path, data, indent: int = 2) -> None:
    """
    Write JSON atomically: dump to a .tmp file in the same directory, then
    os.replace() it over the target. A crash mid-write leaves the original
    file intact instead of corrupting it. (Pattern promoted from
    pull_historical_data._save_json so all cumulative state can share it.)
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent)
    tmp.replace(p)


def save_records(records: dict, path: Path) -> None:
    """Save updated RECORDS.json (atomically -- this is the project's only
    cumulative season history; a partial write here is unrecoverable)."""
    atomic_write_json(path, records)


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
