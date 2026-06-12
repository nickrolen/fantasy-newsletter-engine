"""
projections.py

Handles player projections, variance modeling, and availability calculations.
Used by both betting line and title odds simulations.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import date
import random
import math

import pandas as pd
import numpy as np

from .data_loader import FantasyData, MANAGERS


# =============================================================================
# CONFIGURATION
# =============================================================================

# Injury status availability probabilities (for betting lines sim)
# These represent the probability a player plays on any given game day
# based on their current injury designation from Yahoo
#
# NOTE: INJURY_OVERRIDES out_weeks is the source of truth for who's actually OUT.
# Yahoo's INJ tag just means they have an injury designation, not that they're missing games.
# If a player is INJ but not in out_weeks, they're expected to play.
#
# Only actual injury DESIGNATIONS are included here (not roster slots like IL/IL+/BN)
INJURY_AVAILABILITY = {
    "HEALTHY": 1.0,   # 100% - no injury designation
    "GTD": 0.80,      # 80% - Game Time Decision (legacy flat rate)
    "O": 0.60,        # 60% - Out for current game (legacy flat rate)
    "INJ": 1.0,       # 100% - has injury tag but expected to play (INJURY_OVERRIDES handles actual outs)
}

# Decay-based injury availability for betting simulation.
# Yahoo injury tags are a Monday snapshot.  A "GTD" or "O" designation
# carries the most weight on the day it is set and fades as the week
# progresses, because most soft-tissue issues and rest days resolve
# within 1-3 days.
#
# Key is (status, days_from_week_start) -> availability probability.
# Days beyond the last explicit entry use the final value.
#
# Expected games for a Mon/Wed/Fri schedule (days 0/2/4):
#   GTD: 0.70 + 0.90 + 1.00 = 2.60 out of 3  ("usually plays 2-3")
#   O:   0.20 + 0.60 + 0.85 = 1.65 out of 3  ("usually plays 0-2")
INJURY_DECAY = {
    "GTD": [
        # day 0   1     2     3     4     5+
        0.70, 0.80, 0.90, 0.95, 1.00, 1.00,
    ],
    "O": [
        # day 0   1     2     3     4     5+
        0.20, 0.40, 0.60, 0.75, 0.85, 0.95,
    ],
}

# Default availability for ROS sim (everyone not in overrides)
ROS_DEFAULT_AVAILABILITY = 0.90

# Default standard deviation for weekly scoring (used weeks 1-4)
DEFAULT_WEEKLY_STD_DEV = 150.0

# Default player game variance (as fraction of projection).
# Calibrated to observed game-to-game CV measured in keepability_v2.py:
# CV ranges roughly 24-42% across players, with a league median ~33%.
# We use 0.35 -- slightly above the median to account for projection
# uncertainty layered on top of intrinsic game-to-game variance.
# (Was 0.80 prior to June 2026 sampling-engine recalibration; that value
# roughly doubled real variance, inflated upset probabilities, and combined
# with zero-truncation to add a ~4% positive bias to expected scores.)
DEFAULT_PLAYER_VARIANCE = 0.35

# Minimum games for using actual FPPG instead of projection
MIN_GAMES_FOR_ACTUAL = 10

# Path to editable rosters file
from pathlib import Path
DEFAULT_ROSTERS_FILE = Path(__file__).resolve().parent.parent / "config" / "ROSTERS.json"
# Backwards-compat alias (other modules may import ROSTERS_FILE)
ROSTERS_FILE = DEFAULT_ROSTERS_FILE


# =============================================================================
# ROSTER LOADING
# =============================================================================

def _resolve_rosters_file(rosters_file: Path | str | None) -> Path:
    """Return an absolute Path for the rosters config file."""
    if rosters_file is None:
        return ROSTERS_FILE
    return Path(rosters_file)


def _validate_rosters_payload(payload: object) -> dict[str, list[str]]:
    """
    Validate the shape of ROSTERS.json.

    Expected:
      { "rosters": { "<manager>": ["Player A", "Player B", ...], ... }, ... }

    Returns the validated "rosters" dict.
    Raises ValueError on any schema issues.
    """
    if not isinstance(payload, dict):
        raise ValueError("ROSTERS.json must contain a JSON object at the top level.")

    rosters = payload.get("rosters")
    if not isinstance(rosters, dict):
        raise ValueError('ROSTERS.json must contain a top-level key "rosters" as an object/dict.')

    validated: dict[str, list[str]] = {}
    for mgr, players in rosters.items():
        if not isinstance(mgr, str) or not mgr.strip():
            raise ValueError("ROSTERS.json roster keys must be non-empty strings (manager names).")
        if not isinstance(players, list) or not all(isinstance(p, str) and p.strip() for p in players):
            raise ValueError(f'ROSTERS.json rosters["{mgr}"] must be a list of non-empty strings (player names).')
        validated[mgr] = players

    return validated


def load_rosters_from_config(
    rosters_file: Path | str | None = None,
    *,
    strict: bool = True,
) -> dict[str, list[str]] | None:
    """
    Load rosters from config/ROSTERS.json if it exists.

    Returns:
        Dict mapping manager -> list of player names, or None if file doesn't exist.

    Notes:
        - If the file exists but is invalid JSON or fails schema validation, this
          will raise a ValueError by default (strict=True). This is intentional:
          silently ignoring a corrupted roster file leads to quietly-wrong sims.
        - For legacy behavior (return None on errors), call with strict=False.
    """
    import json

    path = _resolve_rosters_file(rosters_file)

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return _validate_rosters_payload(payload)
    except Exception as e:
        if not strict:
            return None
        raise ValueError(f"Invalid rosters config at {path}: {e}") from e


def generate_rosters_file(
    data: FantasyData,
    rosters_file: Path | str | None = None,
) -> None:
    """
    Generate/regenerate config/ROSTERS.json from LINEUPS.

    Call this to create a fresh ROSTERS.json based on the most recent
    week's lineups, which you can then manually edit.

    Args:
        data: FantasyData container
        rosters_file: Optional override path for where to write the file.
    """
    import json

    path = _resolve_rosters_file(rosters_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Get most recent week's lineups
    max_week = int(data.lineups["week"].max())
    recent = data.lineups[data.lineups["week"] == max_week]

    rosters: dict[str, list[str]] = {}
    for manager in MANAGERS:
        players = recent[recent["manager"] == manager]["player_name"].unique().tolist()
        rosters[manager] = sorted(players)

    output = {
        "_comment": (
            "Edit this file to reflect current rosters before running simulations. "
            f"Auto-generated from LINEUPS week {max_week}"
        ),
        "_generated_from_week": max_week,
        "rosters": rosters,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Generated {path}")
    for mgr, players in rosters.items():
        print(f"  {mgr}: {len(players)} players")


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PlayerProjection:
    """Projection data for a single player."""
    player_name: str
    nba_team: str
    positions: list[str]
    projected_fppg: float
    projected_gp: float = 0.0
    projected_total_fp: float = 0.0

    # Variance modeling
    std_dev: float = 0.0  # Standard deviation for sampling

    # Current status
    injury_status: str = "HEALTHY"
    out_weeks: list[int] = None  # From injury overrides

    # Partial return fields (from INJURY_OVERRIDES)
    return_week: int = None  # Week player is returning
    return_games: int = None  # Expected games in return week
    total_week_games: int = None  # Total team games in return week
    return_date: str = None  # Specific date player returns (YYYY-MM-DD)

    # Actual season performance (populated from PLAYERLOG)
    actual_fppg: float = None  # Actual FPPG from this season
    actual_games: int = 0  # Games played this season
    actual_std: float = None  # Actual standard deviation

    def __post_init__(self):
        if self.out_weeks is None:
            self.out_weeks = []
        if self.std_dev == 0.0:
            self.std_dev = self.projected_fppg * DEFAULT_PLAYER_VARIANCE

    @property
    def return_availability(self) -> float:
        """Get availability percentage for return week (0.0 to 1.0)."""
        if self.return_week and self.return_games and self.total_week_games:
            return self.return_games / self.total_week_games
        return 1.0  # Fully available if no return info

    @property
    def effective_fppg(self) -> float:
        """
        Get the FPPG to use for simulations.

        Uses actual season FPPG if player has MIN_GAMES_FOR_ACTUAL games,
        otherwise uses projection (or blend for players with some games).
        """
        if self.actual_fppg is None or self.actual_games == 0:
            return self.projected_fppg

        if self.actual_games >= MIN_GAMES_FOR_ACTUAL:
            # Use actual performance
            return self.actual_fppg
        else:
            # Blend: weight toward actual as games increase
            weight = self.actual_games / MIN_GAMES_FOR_ACTUAL
            return weight * self.actual_fppg + (1 - weight) * self.projected_fppg

    @property
    def effective_std(self) -> float:
        """Get the standard deviation to use for simulations."""
        if self.actual_std is not None and self.actual_games >= MIN_GAMES_FOR_ACTUAL:
            return self.actual_std
        return self.std_dev


@dataclass
class TeamProjections:
    """Projections for an entire team/manager."""
    manager: str
    players: dict[str, PlayerProjection]  # player_name -> projection

    # Team-level variance (from historical weekly scores)
    weekly_std_dev: float = DEFAULT_WEEKLY_STD_DEV
    weekly_scores: list[float] = None  # Historical weekly scores

    def __post_init__(self):
        if self.weekly_scores is None:
            self.weekly_scores = []

    def get_player(self, name: str) -> Optional[PlayerProjection]:
        """Get projection for a player by name."""
        return self.players.get(name)

    @property
    def total_projected_fppg(self) -> float:
        """Sum of all player projected FPPG."""
        return sum(p.projected_fppg for p in self.players.values())


# =============================================================================
# ACTUAL PERFORMANCE LOADING
# =============================================================================

def compute_actual_stats(data: FantasyData) -> dict[str, dict]:
    """
    Compute actual season stats from PLAYERLOG.

    Only counts games where player started (was in active lineup).

    Returns dict mapping player_name -> {
        'actual_fppg': float,
        'games': int,
        'std': float,
        'total_fp': float,
    }
    """
    # Filter to started games only
    started = data.playerlog[data.playerlog['started'] == True].copy()

    if started.empty:
        return {}

    # Group by player
    stats = started.groupby('player_name')['fantasy_points'].agg(['mean', 'count', 'std', 'sum'])
    stats.columns = ['actual_fppg', 'games', 'std', 'total_fp']

    # Convert to dict
    result = {}
    for player_name, row in stats.iterrows():
        result[player_name] = {
            'actual_fppg': row['actual_fppg'],
            'games': int(row['games']),
            'std': row['std'] if pd.notna(row['std']) else 0.0,
            'total_fp': row['total_fp'],
        }

    return result


def populate_actual_stats(
    player_projections: dict[str, PlayerProjection],
    data: FantasyData,
) -> None:
    """
    Populate actual season stats into PlayerProjection objects.

    Modifies projections in place.
    """
    actual_stats = compute_actual_stats(data)

    for name, proj in player_projections.items():
        if name in actual_stats:
            stats = actual_stats[name]
            proj.actual_fppg = stats['actual_fppg']
            proj.actual_games = stats['games']
            proj.actual_std = stats['std']


# =============================================================================
# PROJECTION LOADING
# =============================================================================

def load_player_projections(data: FantasyData) -> dict[str, PlayerProjection]:
    """
    Load projections for all players from PLAYERLIST.

    Returns dict mapping player_name -> PlayerProjection
    """
    projections = {}

    for _, row in data.playerlist.iterrows():
        name = row["player_name"]

        # Get positions
        positions_str = row.get("player_position(s)", "")
        if pd.isna(positions_str):
            positions = []
        else:
            positions = [p.strip() for p in str(positions_str).split(",")]

        # Get injury override weeks if any
        out_weeks = data.get_player_injury_weeks(name)

        # Get return info if any
        return_info = data.get_player_return_info(name) or {}

        proj = PlayerProjection(
            player_name=name,
            nba_team=str(row.get("player_nba_team", "")),
            positions=positions,
            projected_fppg=float(row.get("projectedFPPG", 0)),
            projected_gp=float(row.get("player_proj_GP", 0)),
            projected_total_fp=float(row.get("player_total_proj_FP", 0)),
            out_weeks=out_weeks,
            return_week=return_info.get("return_week"),
            return_games=return_info.get("return_games"),
            total_week_games=return_info.get("total_week_games"),
            return_date=return_info.get("return_date"),
        )

        projections[name] = proj

    return projections


def load_team_projections(
    data: FantasyData,
    manager: str,
    player_projections: dict[str, PlayerProjection] = None,
    rosters_override: dict[str, list[str]] = None,
) -> TeamProjections:
    """
    Load projections for a manager's roster.

    Args:
        data: FantasyData container
        manager: Manager name
        player_projections: Pre-loaded player projections (optional)
        rosters_override: Dict of manager -> player list to use instead of LINEUPS
                         If None, will check config/ROSTERS.json first, then fall back to LINEUPS
    """
    if player_projections is None:
        player_projections = load_player_projections(data)

    # Determine roster source: override > config file > lineups
    roster_players = None

    if rosters_override and manager in rosters_override:
        roster_players = rosters_override[manager]
    else:
        # Try loading from config/ROSTERS.json
        config_rosters = load_rosters_from_config()
        if config_rosters and manager in config_rosters:
            roster_players = config_rosters[manager]

    if roster_players:
        # Use roster from config file or override
        team_players = {}
        for name in roster_players:
            if name in player_projections:
                team_players[name] = player_projections[name]
            else:
                # Player not in PLAYERLIST - create basic projection
                # Try to get positions from lineups if available
                player_lineups = data.lineups[data.lineups['player_name'] == name]
                if not player_lineups.empty:
                    positions_str = player_lineups.iloc[0].get('positions', '')
                    nba_team = str(player_lineups.iloc[0].get('nba_team', ''))
                else:
                    positions_str = ''
                    nba_team = ''

                if pd.isna(positions_str):
                    positions = []
                else:
                    positions = [p.strip() for p in str(positions_str).split(",")]

                # Get injury override weeks if any (important for simulation accuracy)
                out_weeks = data.get_player_injury_weeks(name)

                team_players[name] = PlayerProjection(
                    player_name=name,
                    nba_team=nba_team,
                    positions=positions,
                    projected_fppg=0.0,  # Unknown projection
                    out_weeks=out_weeks,
                )
    else:
        # Fall back to LINEUPS (original behavior)
        most_recent = data.lineups["date"].max()
        roster_df = data.lineups[
            (data.lineups["manager"] == manager) &
            (data.lineups["date"] == most_recent)
        ]

        team_players = {}
        for _, row in roster_df.iterrows():
            name = row["player_name"]

            if name in player_projections:
                team_players[name] = player_projections[name]
            else:
                # Player not in PLAYERLIST - create basic projection
                positions_str = row.get("positions", "")
                if pd.isna(positions_str):
                    positions = []
                else:
                    positions = [p.strip() for p in str(positions_str).split(",")]

                # Get injury override weeks if any (important for simulation accuracy)
                out_weeks = data.get_player_injury_weeks(name)

                team_players[name] = PlayerProjection(
                    player_name=name,
                    nba_team=str(row.get("nba_team", "")),
                    positions=positions,
                    projected_fppg=0.0,  # Unknown projection
                    out_weeks=out_weeks,
                )

    # Calculate weekly std dev from historical scores
    weekly_std_dev = compute_team_weekly_std_dev(data, manager)

    # Get historical weekly scores
    weekly_scores = get_historical_weekly_scores(data, manager)

    return TeamProjections(
        manager=manager,
        players=team_players,
        weekly_std_dev=weekly_std_dev,
        weekly_scores=weekly_scores,
    )


def load_all_team_projections(data: FantasyData) -> dict[str, TeamProjections]:
    """Load projections for all managers, including actual season performance."""
    player_projections = load_player_projections(data)

    # Populate actual season stats from PLAYERLOG
    populate_actual_stats(player_projections, data)

    return {
        manager: load_team_projections(data, manager, player_projections)
        for manager in MANAGERS
    }


# =============================================================================
# VARIANCE MODELING
# =============================================================================

def compute_team_weekly_std_dev(data: FantasyData, manager: str) -> float:
    """
    Compute standard deviation of a manager's weekly scores.

    Uses actual weekly totals from PLAYERLOG.
    Returns DEFAULT_WEEKLY_STD_DEV if not enough data (< 4 weeks).
    """
    # Group by week and sum fantasy points for healthy starters
    mask = (
        (data.playerlog["manager"] == manager) &
        (data.playerlog["started"] == True) &
        (data.playerlog["is_injured"] == False)
    )

    weekly_totals = (
        data.playerlog[mask]
        .groupby("week")["fantasy_points"]
        .sum()
    )

    if len(weekly_totals) < 4:
        return DEFAULT_WEEKLY_STD_DEV

    return float(weekly_totals.std())


def get_historical_weekly_scores(data: FantasyData, manager: str) -> list[float]:
    """Get list of historical weekly scores for a manager."""
    mask = (
        (data.playerlog["manager"] == manager) &
        (data.playerlog["started"] == True) &
        (data.playerlog["is_injured"] == False)
    )

    weekly_totals = (
        data.playerlog[mask]
        .groupby("week")["fantasy_points"]
        .sum()
        .sort_index()
    )

    return weekly_totals.tolist()


# =============================================================================
# AVAILABILITY CALCULATIONS
# =============================================================================

def get_injury_availability_decayed(
    status: str,
    days_offset: int,
) -> float:
    """
    Get injury availability using the decay model.

    Yahoo tags are a point-in-time snapshot (typically Monday).  Impact
    is strongest on tag day and fades as the week progresses.

    Args:
        status: Injury status string ("GTD", "O", "HEALTHY", "INJ", ...)
        days_offset: Days since the start of the fantasy week (0 = Monday).

    Returns:
        Probability the player is available (0.0 to 1.0).
    """
    status_upper = str(status).upper().strip()

    curve = INJURY_DECAY.get(status_upper)
    if curve is None:
        # HEALTHY, INJ, or anything unrecognised -> 100%
        return 1.0

    idx = min(days_offset, len(curve) - 1)
    idx = max(idx, 0)
    return curve[idx]


def get_player_availability_betting(
    player: PlayerProjection,
    injury_status: str = None,
    days_offset: int = None,
) -> float:
    """
    Get player availability probability for betting lines simulation.

    When *days_offset* is supplied the decay model is used (recommended
    for the daily Monte Carlo).  Without it, falls back to the legacy
    flat constants in INJURY_AVAILABILITY for backward compatibility.

    Args:
        player: Player projection.
        injury_status: Yahoo API status override (default: player.injury_status).
        days_offset: Days since week start for decay model.
    """
    if injury_status is None:
        injury_status = player.injury_status

    status_upper = str(injury_status).upper().strip()

    # Decay model (preferred)
    if days_offset is not None:
        return get_injury_availability_decayed(status_upper, days_offset)

    # Legacy flat model
    if status_upper in INJURY_AVAILABILITY:
        return INJURY_AVAILABILITY[status_upper]

    return INJURY_AVAILABILITY["HEALTHY"]


def get_player_availability_ros(
    player: PlayerProjection,
    week: int,
    availability_rate: float = None,
) -> float:
    """
    Get player availability probability for ROS title odds simulation.

    Uses projection-based model:
    - If week is in player's out_weeks (from INJURY_OVERRIDES) -> 0%
    - Otherwise -> availability_rate (computed from projected_GP / remaining_games)

    Args:
        player: PlayerProjection
        week: Current week number
        availability_rate: Pre-computed rate from projected_GP / remaining_games.
                          If None, uses default 90%.
    """
    if week in player.out_weeks:
        return 0.0

    if availability_rate is not None:
        return availability_rate

    return ROS_DEFAULT_AVAILABILITY


def is_player_available(availability: float) -> bool:
    """Coin flip based on availability probability."""
    return random.random() < availability


# =============================================================================
# SCORE SAMPLING
# =============================================================================

def sample_player_game_fp(
    player: PlayerProjection,
    variance_factor: float = 1.0,
) -> float:
    """
    Sample a player's fantasy points for a single game.

    Uses a normal distribution centered on the player's *effective* FPPG --
    a games-weighted blend of actual season performance and preseason
    projection (see PlayerProjection.effective_fppg). Early in the season
    this is essentially the projection; mid-/late-season it heavily weights
    observed performance, so a player who is actually averaging 40 FPPG on
    a 30-FPPG projection gets simulated near their real rate.

    Standard deviation is the player's effective_std when available, which
    is calibrated against the observed game-to-game CV from keepability_v2
    (24-42% range, median ~33%). DEFAULT_PLAYER_VARIANCE (0.35) is used as
    the fallback for players without enough games for an empirical std.

    Negative samples are allowed: real game logs include them (DNPs after
    a starter check-in, fouled-out blowouts, etc.) and clamping at zero
    introduces a small positive expected-value bias. Team-level totals are
    still floored at zero downstream in the simulators.

    Args:
        player: Player projection
        variance_factor: Multiplier for std dev (increase for more randomness)

    Returns:
        Sampled fantasy points (can be negative; not clamped here)
    """
    # Prefer effective_fppg (blends actual season performance with projection).
    # Falls back to projected_fppg when there's no actual data yet.
    mean = player.effective_fppg
    if mean is None or mean <= 0:
        mean = player.projected_fppg
    if mean <= 0:
        return 0.0

    # Prefer effective_std (calibrated from actuals when available),
    # otherwise the projection-derived std_dev.
    base_std = player.effective_std if player.effective_std else player.std_dev
    std_dev = base_std * variance_factor

    sampled = random.gauss(mean, std_dev)
    return sampled


def sample_team_weekly_variance(team: TeamProjections) -> float:
    """
    Sample additional variance to add to a team's weekly score.

    This captures team-level randomness beyond individual player variance.
    Uses team's historical std dev.
    """
    # Use a fraction of the team std dev since player-level variance
    # already captures some of this
    team_noise = random.gauss(0, team.weekly_std_dev * 0.3)
    return team_noise


# =============================================================================
# UNDERPERFORMANCE INDEX (for Rumor Mill)
# =============================================================================

def compute_underperformance_index(
    data: FantasyData,
    player_name: str,
    manager: str,
    weeks_lookback: int = 4,
) -> Optional[float]:
    """
    Compute underperformance index for a player.

    Index = (actual FPPG - projected FPPG) / projected FPPG * 100

    Negative values indicate underperformance.

    Args:
        data: FantasyData container
        player_name: Player to analyze
        manager: Manager who owns the player
        weeks_lookback: Number of weeks to look back (default: 4)

    Returns:
        Underperformance index (percentage), or None if not enough data
    """
    current_week = data.current_week
    min_week = max(1, current_week - weeks_lookback + 1)

    # Get player's games in lookback period
    mask = (
        (data.playerlog["player_name"] == player_name) &
        (data.playerlog["manager"] == manager) &
        (data.playerlog["week"] >= min_week) &
        (data.playerlog["week"] <= current_week) &
        (data.playerlog["started"] == True) &
        (data.playerlog["is_injured"] == False)
    )

    games = data.playerlog[mask]

    if len(games) < 2:
        return None

    actual_fppg = games["fantasy_points"].mean()
    projected_fppg = data.get_player_projection(player_name)

    if projected_fppg is None or projected_fppg <= 0:
        return None

    return ((actual_fppg - projected_fppg) / projected_fppg) * 100


def get_underperformers(
    data: FantasyData,
    threshold: float = -15.0,
    weeks_lookback: int = 4,
) -> list[dict]:
    """
    Get list of underperforming players.

    Args:
        data: FantasyData container
        threshold: Underperformance index threshold (e.g., -15 = 15% below projection)
        weeks_lookback: Number of weeks to look back (default: 4)

    Returns:
        List of dicts with player info and underperformance index
    """
    underperformers = []

    # Use ROSTERS.json as source of truth for current rosters
    current_rosters = data.get_current_rosters()

    for manager, players in current_rosters.items():
        for player in players:
            index = compute_underperformance_index(
                data, player, manager, weeks_lookback
            )

            if index is not None and index < threshold:
                underperformers.append({
                    "player_name": player,
                    "manager": manager,
                    "underperformance_index": index,
                    "projected_fppg": data.get_player_projection(player),
                })

    # Sort by underperformance (most negative first)
    underperformers.sort(key=lambda x: x["underperformance_index"])

    return underperformers


def get_overperformers(
    data: FantasyData,
    threshold: float = 15.0,
    weeks_lookback: int = 4,
) -> list[dict]:
    """
    Get list of overperforming players (hot streaks).

    Args:
        data: FantasyData container
        threshold: Overperformance index threshold (e.g., 15 = 15% above projection)
        weeks_lookback: Number of weeks to look back (default: 4)

    Returns:
        List of dicts with player info and overperformance index
    """
    overperformers = []

    # Use ROSTERS.json as source of truth for current rosters
    current_rosters = data.get_current_rosters()

    for manager, players in current_rosters.items():
        for player in players:
            index = compute_underperformance_index(
                data, player, manager, weeks_lookback
            )

            if index is not None and index > threshold:
                overperformers.append({
                    "player_name": player,
                    "manager": manager,
                    "overperformance_index": index,
                    "projected_fppg": data.get_player_projection(player),
                })

    # Sort by overperformance (most positive first)
    overperformers.sort(key=lambda x: x["overperformance_index"], reverse=True)

    return overperformers




# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    
    print(f"Loading data from: {base.absolute()}")
    print("-" * 50)
    
    data = load_all_data(base)
    
    # Load all team projections
    team_projections = load_all_team_projections(data)
    
    print("\nTeam Projections:")
    for manager in MANAGERS:
        tp = team_projections[manager]
        print(f"\n{manager}:")
        print(f"  Roster size: {len(tp.players)}")
        print(f"  Total projected FPPG: {tp.total_projected_fppg:.1f}")
        print(f"  Weekly std dev: {tp.weekly_std_dev:.1f}")
        
        # Show top 3 projected players
        sorted_players = sorted(
            tp.players.values(),
            key=lambda p: p.projected_fppg,
            reverse=True
        )[:3]
        print(f"  Top 3: {', '.join(p.player_name for p in sorted_players)}")
    
    print("\n" + "-" * 50)
    print("Underperformers (< -15%):")
    
    underperformers = get_underperformers(data, threshold=-15.0)
    for up in underperformers[:5]:
        print(f"  {up['player_name']} ({up['manager']}): {up['underperformance_index']:.1f}%")
