"""
consistency_score.py

Computes Consistency/Volatility Scores for each manager and their players.

Measures how predictable a team's scoring output is week-to-week using
Coefficient of Variation (CV) on weekly FPPG. Lower CV = more consistent.

TEAM-LEVEL METRICS:
    - Weekly FPPG (total FP / games started that week) to normalize across weeks
    - CV = std_dev / mean (as percentage) -- the core metric
    - Recent trend: last 5 weeks CV vs full season CV
    - Boom/bust counts: weeks > 1 SD above/below mean FPPG
    - Floor (worst FPPG week) and ceiling (best FPPG week)
    - Rating label: "Rock Solid", "Steady", "Variable", "Boom-or-Bust"

PLAYER-LEVEL METRICS:
    - Per-player game-by-game CV (min 10 started games)
    - Most consistent and most volatile starter per team

DESTINATION:
    - Section 3 (Betting Lines): predictability context per matchup
    - Section 7 (Power Rankings): stability input

INTEGRATION POINTS:
    - report_builder.py: build_stats_report() calls build_consistency_scores()
    - format_stats_report.py: renders in Section 3 and/or Section 7
"""

from dataclasses import dataclass, field
from typing import Optional
import math

from .data_loader import FantasyData, MANAGERS, CURRENT_SEASON_LONG


# =============================================================================
# CONFIGURATION
# =============================================================================

# Minimum weeks required for meaningful CV calculation
MIN_WEEKS_FOR_CV = 4

# Minimum started games for player-level CV
MIN_PLAYER_GAMES = 10

# Recent window size (weeks) for trend calculation
RECENT_WINDOW = 5

# CV thresholds for team ratings (percentage)
# These are calibrated for fantasy weekly FPPG variance
CV_THRESHOLDS = {
    "Rock Solid": 8.0,      # CV < 8% -- very tight range
    "Steady": 14.0,         # CV 8-14% -- normal variance
    "Variable": 20.0,       # CV 14-20% -- noticeable swings
    # Anything above 20% = "Boom-or-Bust"
}

# Boom/bust threshold: weeks where FPPG is > 1 SD from mean
BOOM_BUST_SD_THRESHOLD = 1.0


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class WeekFPPG:
    """Single week's normalized scoring."""
    week: int
    total_fp: float
    games_started: int
    fppg: float              # total_fp / games_started
    days: int = 7            # length of the fantasy week


@dataclass
class PlayerConsistency:
    """Consistency metrics for a single player."""
    player_name: str
    manager: str
    games_started: int = 0
    total_fp: float = 0.0
    mean_fp: float = 0.0
    std_dev: float = 0.0
    cv: float = 0.0          # coefficient of variation (%)
    min_fp: float = 0.0
    max_fp: float = 0.0
    q25: float = 0.0         # 25th percentile (IQR lower bound)
    q75: float = 0.0         # 75th percentile (IQR upper bound)
    rating: str = ""

    def to_dict(self) -> dict:
        return {
            "player_name": self.player_name,
            "manager": self.manager,
            "games_started": self.games_started,
            "total_fp": round(self.total_fp, 2),
            "mean_fp": round(self.mean_fp, 2),
            "std_dev": round(self.std_dev, 2),
            "cv": round(self.cv, 1),
            "min_fp": round(self.min_fp, 2),
            "max_fp": round(self.max_fp, 2),
            "q25": round(self.q25, 1),
            "q75": round(self.q75, 1),
            "rating": self.rating,
        }


@dataclass
class ManagerConsistency:
    """Full consistency profile for a manager."""
    manager: str

    # Weekly FPPG series
    weekly_fppg: list[WeekFPPG] = field(default_factory=list)

    # Core stats on weekly FPPG
    mean_fppg: float = 0.0
    std_dev_fppg: float = 0.0
    cv: float = 0.0                   # coefficient of variation (%)
    rating: str = ""

    # Floor / ceiling
    floor_fppg: float = 0.0           # worst week FPPG
    floor_week: int = 0
    ceiling_fppg: float = 0.0         # best week FPPG
    ceiling_week: int = 0

    # Boom / bust counts
    boom_weeks: int = 0               # weeks > +1 SD above mean
    bust_weeks: int = 0               # weeks > -1 SD below mean
    boom_week_numbers: list[int] = field(default_factory=list)
    bust_week_numbers: list[int] = field(default_factory=list)

    # Recent trend
    recent_cv: float = 0.0            # CV over last N weeks
    recent_mean_fppg: float = 0.0
    recent_trend: str = ""            # "Getting steadier", "Getting wilder", "Stable"
    recent_window: int = RECENT_WINDOW

    # Player-level
    most_consistent_player: Optional[PlayerConsistency] = None
    most_volatile_player: Optional[PlayerConsistency] = None
    player_consistencies: list[PlayerConsistency] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "manager": self.manager,
            "mean_fppg": round(self.mean_fppg, 2),
            "std_dev_fppg": round(self.std_dev_fppg, 2),
            "cv": round(self.cv, 1),
            "rating": self.rating,
            "floor_fppg": round(self.floor_fppg, 2),
            "floor_week": self.floor_week,
            "ceiling_fppg": round(self.ceiling_fppg, 2),
            "ceiling_week": self.ceiling_week,
            "boom_weeks": self.boom_weeks,
            "bust_weeks": self.bust_weeks,
            "boom_week_numbers": self.boom_week_numbers,
            "bust_week_numbers": self.bust_week_numbers,
            "recent_cv": round(self.recent_cv, 1),
            "recent_mean_fppg": round(self.recent_mean_fppg, 2),
            "recent_trend": self.recent_trend,
            "recent_window": self.recent_window,
            "weekly_fppg_series": [
                {
                    "week": wf.week,
                    "total_fp": round(wf.total_fp, 2),
                    "games_started": wf.games_started,
                    "fppg": round(wf.fppg, 2),
                }
                for wf in self.weekly_fppg
            ],
        }

        if self.most_consistent_player:
            d["most_consistent_player"] = self.most_consistent_player.to_dict()
        if self.most_volatile_player:
            d["most_volatile_player"] = self.most_volatile_player.to_dict()

        # All player consistencies (for cross-referencing in Section 8)
        d["all_players"] = [pc.to_dict() for pc in self.player_consistencies]

        return d


@dataclass
class ConsistencyReport:
    """Full consistency report across all managers."""
    through_week: int = 0
    managers: dict[str, ManagerConsistency] = field(default_factory=dict)

    # League-wide comparisons
    most_consistent_team: str = ""
    most_volatile_team: str = ""

    def to_dict(self) -> dict:
        # Build flat player lookup: player_name -> consistency dict
        # This allows Section 8 to easily add CV/IQR to performer tables
        player_lookup = {}
        for mgr, mc in self.managers.items():
            for pc in mc.player_consistencies:
                player_lookup[pc.player_name] = pc.to_dict()

        return {
            "through_week": self.through_week,
            "most_consistent_team": self.most_consistent_team,
            "most_volatile_team": self.most_volatile_team,
            "managers": {
                mgr: mc.to_dict() for mgr, mc in self.managers.items()
            },
            "player_lookup": player_lookup,
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_finite_number(x) -> bool:
    """True if x can be treated as a finite float (not NaN/inf/None)."""
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _finite_floats(values: list[float]) -> list[float]:
    """Coerce a list of numeric-ish values to finite floats, dropping NaN/inf/etc."""
    out: list[float] = []
    for v in values:
        if not _is_finite_number(v):
            continue
        out.append(float(v))
    return out


def _compute_stats(values: list[float]) -> tuple[float, float, float]:
    """
    Compute mean, std_dev, and CV for a list of values.

    Returns:
        (mean, std_dev, cv_percent)
    """
    values = _finite_floats(values)

    if len(values) < 2:
        if len(values) == 1:
            return values[0], 0.0, 0.0
        return 0.0, 0.0, 0.0

    n = len(values)
    mean = sum(values) / n
    if (not math.isfinite(mean)) or mean == 0:
        return 0.0, 0.0, 0.0

    variance = sum((v - mean) ** 2 for v in values) / n
    if not math.isfinite(variance) or variance < 0:
        return mean, 0.0, 0.0

    std_dev = math.sqrt(variance)
    denom = abs(mean)
    cv = (std_dev / denom) * 100.0 if denom != 0 else 0.0

    # Final guard: no NaN/inf in outputs
    if not math.isfinite(std_dev):
        std_dev = 0.0
    if not math.isfinite(cv):
        cv = 0.0

    return mean, std_dev, cv


def _percentile(sorted_values: list[float], pct: float) -> float:
    """
    Compute a percentile from a pre-sorted list using linear interpolation.

    This avoids a numpy dependency for a simple calculation.

    Notes:
      - pct is clamped to [0, 100] to avoid IndexError on edge cases.
      - Any non-finite inputs (NaN/inf) should be filtered out BEFORE sorting.
    """
    if not sorted_values:
        return 0.0

    # Clamp pct defensively
    if not _is_finite_number(pct):
        pct = 0.0
    pct = max(0.0, min(100.0, float(pct)))

    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])

    if pct <= 0.0:
        return float(sorted_values[0])
    if pct >= 100.0:
        return float(sorted_values[-1])

    # Position in the sorted list (0-indexed, fractional)
    k = (pct / 100.0) * (n - 1)
    k = max(0.0, min(float(n - 1), k))

    lower = int(math.floor(k))
    upper = int(math.ceil(k))

    # Clamp indices (belt & suspenders)
    lower = max(0, min(n - 1, lower))
    upper = max(0, min(n - 1, upper))

    if lower == upper:
        return float(sorted_values[lower])

    # Linear interpolation
    frac = k - lower
    return float(sorted_values[lower]) + frac * (float(sorted_values[upper]) - float(sorted_values[lower]))


def _rate_cv(cv: float) -> str:
    """Convert a CV percentage into a human-readable rating."""
    if cv < CV_THRESHOLDS["Rock Solid"]:
        return "Rock Solid"
    elif cv < CV_THRESHOLDS["Steady"]:
        return "Steady"
    elif cv < CV_THRESHOLDS["Variable"]:
        return "Variable"
    else:
        return "Boom-or-Bust"


def _rate_player_cv(cv: float) -> str:
    """Rate a player's game-to-game CV. Players are inherently more volatile."""
    if cv < 15.0:
        return "Elite consistency"
    elif cv < 25.0:
        return "Reliable"
    elif cv < 35.0:
        return "Moderate"
    elif cv < 50.0:
        return "Volatile"
    else:
        return "Wildcard"


def _recent_trend_label(full_cv: float, recent_cv: float) -> str:
    """
    Describe the trend in consistency over the recent window.

    If recent CV is meaningfully lower -> getting steadier.
    If recent CV is meaningfully higher -> getting wilder.
    """
    if full_cv == 0:
        return "Stable"

    # Need at least 2 percentage points of difference to call a trend
    diff = recent_cv - full_cv
    if diff < -2.0:
        return "Getting steadier"
    elif diff > 2.0:
        return "Getting wilder"
    else:
        return "Stable"


# =============================================================================
# CORE: BUILD WEEKLY FPPG SERIES
# =============================================================================

def build_weekly_fppg_series(
    data: FantasyData,
    manager: str,
    through_week: int,
) -> list[WeekFPPG]:
    """
    Build the weekly FPPG series for a manager from LINEUPS data.

    For each week, counts games started in non-bench slots with an
    NBA opponent, and divides total FP by games started to get FPPG.
    This normalizes across weeks with different game counts.
    """
    lineups = data.lineups
    schedule = data.schedule

    # Build week -> days lookup from schedule
    week_days = {}
    for wk in schedule.get("weeks", []):
        week_days[wk["week"]] = wk.get("days", 7)

    # Filter to current season and manager
    season_li = lineups[
        (lineups["season_year"] == CURRENT_SEASON_LONG) &
        (lineups["manager"] == manager)
    ]

    bench_slots = {"BN", "IL", "IL+"}
    series = []

    for week_num in range(1, through_week + 1):
        week_rows = season_li[season_li["week"] == week_num]

        # Starter rows: not bench, has an NBA opponent
        starter_rows = week_rows[
            (~week_rows["slot"].isin(bench_slots)) &
            (week_rows["nba_opponent"].notna())
        ]

        games = len(starter_rows)
        total_fp = float(starter_rows["fantasy_points"].sum()) if games > 0 else 0.0
        if not _is_finite_number(total_fp):
            total_fp = 0.0

        fppg = (total_fp / games) if games > 0 else 0.0
        if not _is_finite_number(fppg):
            fppg = 0.0

        series.append(WeekFPPG(
            week=week_num,
            total_fp=total_fp,
            games_started=games,
            fppg=fppg,
            days=week_days.get(week_num, 7),
        ))

    return series


# =============================================================================
# CORE: COMPUTE PLAYER CONSISTENCY
# =============================================================================

def compute_player_consistency(
    data: FantasyData,
    manager: str,
    through_week: int,
    current_roster: list[str] = None,
    min_games: int = MIN_PLAYER_GAMES,
) -> list[PlayerConsistency]:
    """
    Compute game-by-game consistency for each player on a manager's CURRENT roster.

    Uses ROSTERS.json (via current_roster param) to determine which players
    belong to this manager NOW. Game logs are pulled from LINEUPS across ALL
    managers (a player may have been traded mid-season).

    Only includes players with >= min_games started games.
    """
    lineups = data.lineups
    bench_slots = {"BN", "IL", "IL+"}

    # If no current roster provided, fall back to ROSTERS.json
    if current_roster is None:
        rosters = data.get_current_rosters()
        current_roster = rosters.get(manager, [])

    # All starter games this season (any manager) -- we filter by player name
    season_starters = lineups[
        (lineups["season_year"] == CURRENT_SEASON_LONG) &
        (~lineups["slot"].isin(bench_slots)) &
        (lineups["nba_opponent"].notna()) &
        (lineups["week"] <= through_week)
    ]

    results = []
    for player_name in current_roster:
        player_games = season_starters[
            season_starters["player_name"] == player_name
        ]

        fps = player_games["fantasy_points"].tolist()
        # Filter out injury zeros (fp == 0.0 is likely DNP/injury, not a real game)
        # Also drop any non-finite values (NaN/inf) to avoid poisoning downstream stats.
        active_fps = []
        for fp in fps:
            if not _is_finite_number(fp):
                continue
            fp_f = float(fp)
            if fp_f > 0.0:
                active_fps.append(fp_f)

        if len(active_fps) < min_games:
            continue

        mean, std_dev, cv = _compute_stats(active_fps)

        # IQR: 25th and 75th percentiles
        sorted_fps = sorted(active_fps)
        q25 = _percentile(sorted_fps, 25)
        q75 = _percentile(sorted_fps, 75)

        pc = PlayerConsistency(
            player_name=str(player_name),
            manager=manager,
            games_started=len(active_fps),
            total_fp=sum(active_fps),
            mean_fp=mean,
            std_dev=std_dev,
            cv=cv,
            min_fp=min(active_fps),
            max_fp=max(active_fps),
            q25=q25,
            q75=q75,
            rating=_rate_player_cv(cv),
        )
        results.append(pc)

    # Sort by CV ascending (most consistent first)
    results.sort(key=lambda p: p.cv)
    return results


# =============================================================================
# CORE: COMPUTE MANAGER CONSISTENCY
# =============================================================================

def compute_manager_consistency(
    data: FantasyData,
    manager: str,
    through_week: int,
) -> ManagerConsistency:
    """Compute full consistency profile for a single manager."""
    mc = ManagerConsistency(manager=manager)

    # Build weekly FPPG series
    mc.weekly_fppg = build_weekly_fppg_series(data, manager, through_week)

    if len(mc.weekly_fppg) < MIN_WEEKS_FOR_CV:
        return mc

    fppg_values = [wf.fppg if _is_finite_number(wf.fppg) else 0.0 for wf in mc.weekly_fppg]

    # Core stats
    mc.mean_fppg, mc.std_dev_fppg, mc.cv = _compute_stats(fppg_values)
    mc.rating = _rate_cv(mc.cv)

    # Floor and ceiling
    floor_week = min(mc.weekly_fppg, key=lambda wf: wf.fppg)
    ceiling_week = max(mc.weekly_fppg, key=lambda wf: wf.fppg)
    mc.floor_fppg = floor_week.fppg
    mc.floor_week = floor_week.week
    mc.ceiling_fppg = ceiling_week.fppg
    mc.ceiling_week = ceiling_week.week

    # Boom / bust
    boom_threshold = mc.mean_fppg + (BOOM_BUST_SD_THRESHOLD * mc.std_dev_fppg)
    bust_threshold = mc.mean_fppg - (BOOM_BUST_SD_THRESHOLD * mc.std_dev_fppg)

    for wf in mc.weekly_fppg:
        if wf.fppg > boom_threshold:
            mc.boom_weeks += 1
            mc.boom_week_numbers.append(wf.week)
        elif wf.fppg < bust_threshold:
            mc.bust_weeks += 1
            mc.bust_week_numbers.append(wf.week)

    # Recent trend
    recent_fppg = fppg_values[-RECENT_WINDOW:] if len(fppg_values) >= RECENT_WINDOW else fppg_values
    mc.recent_mean_fppg, _, mc.recent_cv = _compute_stats(recent_fppg)
    mc.recent_window = min(RECENT_WINDOW, len(fppg_values))
    mc.recent_trend = _recent_trend_label(mc.cv, mc.recent_cv)

    # Player-level consistency
    mc.player_consistencies = compute_player_consistency(data, manager, through_week)

    if mc.player_consistencies:
        # Most consistent = lowest CV
        mc.most_consistent_player = mc.player_consistencies[0]
        # Most volatile = highest CV
        mc.most_volatile_player = mc.player_consistencies[-1]

    return mc


# =============================================================================
# CORE: BUILD FULL REPORT
# =============================================================================

def compute_consistency_report(
    data: FantasyData,
    through_week: int,
) -> ConsistencyReport:
    """Compute consistency scores for all managers."""
    report = ConsistencyReport(through_week=through_week)

    for manager in MANAGERS:
        mc = compute_manager_consistency(data, manager, through_week)
        report.managers[manager] = mc

    # League-wide comparisons
    valid = {m: mc for m, mc in report.managers.items() if mc.cv > 0}
    if valid:
        report.most_consistent_team = min(valid, key=lambda m: valid[m].cv)
        report.most_volatile_team = max(valid, key=lambda m: valid[m].cv)

    return report


# =============================================================================
# ENTRY POINT FOR REPORT_BUILDER
# =============================================================================

def build_consistency_scores(data: FantasyData, week: int) -> dict:
    """
    Build Consistency Score section for the stats report.

    Convenience wrapper that takes FantasyData and returns a
    JSON-serializable dict matching the report format.

    Args:
        data: FantasyData container
        week: Current week number (compute through this week)

    Returns:
        Dict ready for inclusion in the stats report JSON
    """
    report = compute_consistency_report(data, through_week=week)
    return report.to_dict()


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path

    # Add parent directory to path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from modules.data_loader import load_all_data

    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    week = int(sys.argv[2]) if len(sys.argv) > 2 else None

    print("Loading data...")
    data = load_all_data(base)

    if week is None:
        week = data.current_week

    print(f"Computing Consistency Scores through Week {week}")
    print("=" * 60)

    result = build_consistency_scores(data, week)

    print(f"\nMost Consistent: {result['most_consistent_team']}")
    print(f"Most Volatile:   {result['most_volatile_team']}")
    print()

    # Team table
    header = (
        f"{'Manager':<10} {'CV':>6} {'Rating':<15} "
        f"{'Mean FPPG':>10} {'Std Dev':>8} "
        f"{'Boom':>5} {'Bust':>5} "
        f"{'Recent CV':>10} {'Trend':<20}"
    )
    print(header)
    print("-" * len(header))

    for manager in MANAGERS:
        m = result["managers"].get(manager, {})
        if not m:
            continue
        print(
            f"{m['manager']:<10} "
            f"{m['cv']:>5.1f}% "
            f"{m['rating']:<15} "
            f"{m['mean_fppg']:>10.2f} "
            f"{m['std_dev_fppg']:>8.2f} "
            f"{m['boom_weeks']:>5} "
            f"{m['bust_weeks']:>5} "
            f"{m['recent_cv']:>9.1f}% "
            f"{m['recent_trend']:<20}"
        )

    # Player highlights
    print("\n\nPlayer Highlights:")
    print("-" * 60)
    for manager in MANAGERS:
        m = result["managers"].get(manager, {})
        if not m:
            continue
        mc_player = m.get("most_consistent_player")
        mv_player = m.get("most_volatile_player")
        print(f"\n{manager}:")
        if mc_player:
            print(
                f"  Most Consistent: {mc_player['player_name']} "
                f"(CV {mc_player['cv']:.1f}%, "
                f"{mc_player['mean_fp']:.1f} avg, "
                f"{mc_player['games_started']} games, "
                f"{mc_player['rating']})"
            )
        if mv_player and mv_player != mc_player:
            print(
                f"  Most Volatile:   {mv_player['player_name']} "
                f"(CV {mv_player['cv']:.1f}%, "
                f"{mv_player['mean_fp']:.1f} avg, "
                f"{mv_player['games_started']} games, "
                f"{mv_player['rating']})"
            )


# =============================================================================
# PLAYER-LEVEL CV FOR KEEPABILITY V2
# =============================================================================

def get_player_consistency_cv(data: FantasyData, week: int) -> dict:
    """
    Calculate coefficient of variation for each player's game-to-game scoring.
    
    Used by keepability_v2 module to reward low-volatility players.
    
    Args:
        data: FantasyData object
        week: Current week number
    
    Returns:
        Dict mapping player_name -> CV (as percentage, e.g., 15.2)
        Lower CV = more consistent
    """
    import statistics
    
    playerlog = data.playerlog
    
    # Filter to started games with FP > 0
    started = playerlog[
        (playerlog["started"] == True)
        & (playerlog["week"] <= week)
        & (playerlog["fantasy_points"].notna())
        & (playerlog["fantasy_points"] > 0)
    ]
    
    player_cvs = {}
    
    for player_name, grp in started.groupby("player_name"):
        fps = grp["fantasy_points"].tolist()
        
        # Need at least MIN_PLAYER_GAMES (10) for meaningful CV
        if len(fps) < MIN_PLAYER_GAMES:
            continue
        
        mean_fp = statistics.mean(fps)
        if mean_fp == 0:
            continue
        
        std_fp = statistics.stdev(fps)
        cv = (std_fp / mean_fp) * 100  # As percentage
        
        player_cvs[player_name] = cv
    
    return player_cvs
