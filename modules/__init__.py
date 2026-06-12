"""
Fantasy Basketball Newsletter - Modules

Core computational modules for the newsletter system.
"""

from .data_loader import (
    FantasyData,
    load_all_data,
    save_records,
    MANAGERS,
    MANAGER_TO_TEAM,
    TEAM_TO_MANAGER,
    MANAGER_COLORS,
    MANAGER_ALIASES,
    LEAGUE_NAME,
    LEAGUE_NAME_SHORT,
    BRAND_COLORS,
    NUM_TEAMS,
    YAHOO_GAME_CODE,
    LEAGUE_KEY,
    HISTORICAL_LEAGUE_KEYS,
    LEAGUE_STRUCTURE,
    KEEPER_ERA_START,
    CURRENT_SEASON,
    CURRENT_SEASON_LONG,
    REGULAR_SEASON_WEEKS,
    PLAYOFF_START_WEEK,
    TOTAL_WEEKS,
    SEASON_NUMBER,
    NBA_SCHEDULE_FILE,
    PRE_DATA_ERA,
    TIEBREAKER_RULES,
    STARTER_SLOTS,
    BENCH_SLOTS,
    IL_SLOTS,
    ROSTER_SLOTS,
    SLOT_ELIGIBILITY,
    get_position_list,
    classify_position_group,
    player_eligible_for_slot,
    parse_record_string,
)

from .weekly_stats import (
    PlayerWeekStats,
    PositionalStats,
    ManagerWeekStats,
    MatchupStats,
    WeeklyReport,
    compute_player_week_stats,
    compute_manager_week_stats,
    compute_matchup_stats,
    compute_weekly_report,
    load_waiver_adds,
)

from .projections import (
    PlayerProjection,
    TeamProjections,
    load_player_projections,
    load_team_projections,
    load_all_team_projections,
    compute_team_weekly_std_dev,
    get_player_availability_betting,
    get_injury_availability_decayed,
    get_player_availability_ros,
    is_player_available,
    sample_player_game_fp,
    compute_underperformance_index,
    get_underperformers,
    INJURY_AVAILABILITY,
    INJURY_DECAY,
    ROS_DEFAULT_AVAILABILITY,
)

# Optional: fetch_injury_statuses (requires yahoo_oauth)
try:
    from .fetch_injury_statuses import (
        fetch_injury_statuses,
        fetch_injury_statuses_safe,
        normalize_injury_status,
    )
    _FETCH_INJURIES_AVAILABLE = True
except ImportError:
    _FETCH_INJURIES_AVAILABLE = False
    # Create placeholder functions that return empty/default values
    def fetch_injury_statuses(*args, **kwargs):
        return {}
    def fetch_injury_statuses_safe(*args, **kwargs):
        return {}
    def normalize_injury_status(status):
        return "HEALTHY" if not status else str(status).upper()

# Content freshness tracking
try:
    from .content_freshness import (
        FreshnessTracker,
        make_fact_key,
        get_fact_value,
        filter_fresh_facts,
        record_shown_facts,
        make_trade_key,
        filter_fresh_trades,
        record_shown_trades,
        filter_fresh_fa_targets,
        record_shown_fa_targets,
        filter_fresh_drop_candidates,
        record_shown_drop_candidates,
        COOLDOWN_PERIODS,
        CHANGE_THRESHOLDS,
        TRADE_IDEA_COOLDOWN,
        FA_TARGET_COOLDOWN,
        DROP_CANDIDATE_COOLDOWN,
    )
    _FRESHNESS_AVAILABLE = True
except ImportError:
    _FRESHNESS_AVAILABLE = False

# Luck Index (All-Play expected wins)
from .luck_index import (
    ManagerLuckIndex,
    LuckIndexReport,
    compute_luck_index,
    build_luck_index,
)

# Waiver Wire ROI (season-long transaction value)
from .waiver_roi import (
    build_waiver_roi,
)

# Stats Corner visualizations (HTML rendering for newsletter)
from .stats_corner_viz import (
    render_stats_corner_visualizations,
    get_stats_corner_css,
    get_stats_corner_js,
)

from .lineup_optimizer import (
    PlayerSlot,
    OptimizedLineup,
    AvailablePlayer,
    optimize_lineup,
    select_top_n_players,
    compute_simple_daily_score,
    find_best_swap,
    analyze_what_if_swaps,
    STARTER_SLOTS as LINEUP_STARTER_SLOTS,
    NUM_STARTERS,
    SLOT_POSITIONS,
)

# Keepability V2 (multi-year keeper scoring)
from .keepability_v2 import (
    compute_keepability_v2,
    build_keepability_report,
    assign_keeper_tier,
    assign_keeper_tiers,
)

# Playoff simulator (2-week bracket Monte Carlo)
from .simulator_playoff_odds import (
    run_playoff_odds_simulation,
    PlayoffOddsResult,
)

__all__ = [
    # data_loader
    "FantasyData",
    "load_all_data",
    "save_records",
    "MANAGERS",
    "MANAGER_TO_TEAM",
    "TEAM_TO_MANAGER",
    "MANAGER_COLORS",
    "MANAGER_ALIASES",
    "LEAGUE_NAME",
    "LEAGUE_NAME_SHORT",
    "BRAND_COLORS",
    "NUM_TEAMS",
    "YAHOO_GAME_CODE",
    "LEAGUE_KEY",
    "HISTORICAL_LEAGUE_KEYS",
    "LEAGUE_STRUCTURE",
    "KEEPER_ERA_START",
    "CURRENT_SEASON",
    "CURRENT_SEASON_LONG",
    "REGULAR_SEASON_WEEKS",
    "PLAYOFF_START_WEEK",
    "TOTAL_WEEKS",
    "SEASON_NUMBER",
    "NBA_SCHEDULE_FILE",
    "PRE_DATA_ERA",
    "TIEBREAKER_RULES",
    "STARTER_SLOTS",
    "BENCH_SLOTS",
    "IL_SLOTS",
    "ROSTER_SLOTS",
    "SLOT_ELIGIBILITY",
    "get_position_list",
    "player_eligible_for_slot",
    "parse_record_string",
    # weekly_stats
    "PlayerWeekStats",
    "PositionalStats",
    "ManagerWeekStats",
    "MatchupStats",
    "WeeklyReport",
    "compute_player_week_stats",
    "compute_manager_week_stats",
    "compute_matchup_stats",
    "compute_weekly_report",
    "load_waiver_adds",
    "classify_position_group",
    # projections
    "PlayerProjection",
    "TeamProjections",
    "load_player_projections",
    "load_team_projections",
    "load_all_team_projections",
    "compute_team_weekly_std_dev",
    "get_player_availability_betting",
    "get_injury_availability_decayed",
    "get_player_availability_ros",
    "is_player_available",
    "sample_player_game_fp",
    "compute_underperformance_index",
    "get_underperformers",
    "INJURY_AVAILABILITY",
    "INJURY_DECAY",
    "ROS_DEFAULT_AVAILABILITY",
    # fetch_injury_statuses (optional, requires yahoo_oauth)
    "fetch_injury_statuses",
    "fetch_injury_statuses_safe",
    "normalize_injury_status",
    "_FETCH_INJURIES_AVAILABLE",
    # content_freshness
    "FreshnessTracker",
    "make_fact_key",
    "get_fact_value",
    "filter_fresh_facts",
    "record_shown_facts",
    "COOLDOWN_PERIODS",
    "CHANGE_THRESHOLDS",
    "_FRESHNESS_AVAILABLE",
    # luck_index
    "ManagerLuckIndex",
    "LuckIndexReport",
    "compute_luck_index",
    "build_luck_index",
    # waiver_roi
    "build_waiver_roi",
    # stats_corner_viz
    "render_stats_corner_visualizations",
    "get_stats_corner_css",
    "get_stats_corner_js",
    # lineup_optimizer
    "PlayerSlot",
    "OptimizedLineup",
    "AvailablePlayer",
    "optimize_lineup",
    "select_top_n_players",
    "compute_simple_daily_score",
    "find_best_swap",
    "analyze_what_if_swaps",
    "LINEUP_STARTER_SLOTS",
    "NUM_STARTERS",
    "SLOT_POSITIONS",
    # keepability_v2
    "compute_keepability_v2",
    "build_keepability_report",
    "assign_keeper_tier",
    "assign_keeper_tiers",
    # simulator_playoff_odds
    "run_playoff_odds_simulation",
    "PlayoffOddsResult",
]
