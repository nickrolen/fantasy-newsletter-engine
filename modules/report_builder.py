"""
report_builder.py

Assembles all computed statistics into a final JSON report.
This is the output that gets fed to the LLM for newsletter generation.
"""

import json
import math
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Any

from .data_loader import FantasyData, MANAGERS, MANAGER_TO_TEAM, CURRENT_SEASON, classify_position_group
from .weekly_stats import (
    WeeklyReport,
    compute_weekly_report,
    load_waiver_adds,
)
from .projections import load_all_team_projections, get_underperformers
from .records_tracker import (
    update_records_from_weekly_report,
    RecordUpdate,
    get_current_streaks,
    get_season_series,
    get_h2h_streak,
)
from .simulator_title_odds import run_title_odds_simulation, TitleOddsResult
from .simulator_playoff_odds import run_playoff_odds_simulation, PlayoffOddsResult, rank_managers_by_standings
from .simulator_betting import generate_weekly_betting_lines, WeeklyBettingLines
from .what_if_analyzer import analyze_weekly_what_if, WeeklyWhatIf
from .fun_facts_generator import generate_fun_facts, FunFact
from .rumor_mill_analyzer import generate_rumor_mill_analysis, RumorMillAnalysis
from .season_performers import build_season_performers
from .luck_index import build_luck_index, build_historical_luck
from .waiver_roi import build_waiver_roi
from .schedule_strength import build_schedule_strength
from .consistency_score import build_consistency_scores
from .keepability_v2 import build_keepability_report


# =============================================================================
# JSON SERIALIZATION HELPERS
# =============================================================================

def serialize_date(obj):
    """JSON serializer for date objects."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def dataclass_to_dict(obj) -> Any:
    """Convert dataclass objects to dicts recursively."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: dataclass_to_dict(v) for k, v in asdict(obj).items()}
    elif isinstance(obj, dict):
        return {k: dataclass_to_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [dataclass_to_dict(item) for item in obj]
    elif isinstance(obj, (date, datetime)):
        return obj.isoformat()
    else:
        return obj


# =============================================================================
# REPORT STRUCTURE
# =============================================================================

def get_notable_injuries(
    manager: str,
    week: int,
    injury_overrides: dict,
    rosters: dict[str, list[str]],
    exclude_season_long: bool = True,
) -> list[dict]:
    """
    Get notable injuries for a manager in a given week.
    
    Args:
        manager: Manager name
        week: Week number to check
        injury_overrides: INJURY_OVERRIDES data dict
        rosters: Dict mapping manager -> list of player names
        exclude_season_long: If True, exclude players out for 18+ weeks (season-long injuries)
    
    Returns:
        List of dicts with 'player' and 'notes' keys
    """
    injuries = []
    manager_roster = rosters.get(manager, [])
    
    for player_entry in injury_overrides.get("players", []):
        player_name = player_entry.get("player_name", "")
        out_weeks = player_entry.get("out_weeks", [])
        notes = player_entry.get("notes", "")
        
        # Check if this player is on the manager's roster
        if player_name not in manager_roster:
            continue
        
        # Check if player is out for this week
        if week not in out_weeks:
            continue
        
        # Optionally exclude season-long injuries (18+ weeks typically means full season)
        if exclude_season_long and len(out_weeks) >= 18:
            continue
        
        injuries.append({
            "player": player_name,
            "notes": notes,
        })
    
    return injuries


def get_rosters_from_lineups(lineups_df) -> dict[str, list[str]]:
    """
    Get current rosters, preferring ROSTERS.json over LINEUPS.
    
    Returns dict mapping manager -> list of player names.
    """
    # Try ROSTERS.json first (source of truth for current rosters)
    from pathlib import Path
    import json
    
    rosters_file = Path(__file__).parent.parent / "config" / "ROSTERS.json"
    if rosters_file.exists():
        try:
            with open(rosters_file, "r") as f:
                config_data = json.load(f)
            config_rosters = config_data.get("rosters", config_data)
            # Filter to only manager entries (lists of players)
            rosters = {
                manager: players
                for manager, players in config_rosters.items()
                if isinstance(players, list)
            }
            if rosters:
                return rosters
        except (json.JSONDecodeError, KeyError):
            pass  # Fall through to LINEUPS method
    
    # Fall back to LINEUPS
    max_date = lineups_df['date'].max()
    recent = lineups_df[lineups_df['date'] == max_date]
    
    rosters = {}
    for manager in MANAGERS:
        players = recent[recent['manager'] == manager]['player_name'].unique().tolist()
        rosters[manager] = players
    
    return rosters


def build_matchup_summary(
    report: WeeklyReport,
    records: dict,
    data: FantasyData = None,
    week: int = None,
) -> list[dict]:
    """
    Build matchup summaries section.
    
    Args:
        report: WeeklyReport with matchup results
        records: Records dict with H2H data
        data: FantasyData container (optional, for injuries and H2H streaks)
        week: Week number (optional, for injuries and H2H streaks)
    """
    summaries = []
    
    # Get all-time H2H data
    all_time_h2h = records.get("all_time", {}).get("h2h", {})
    
    # Get rosters and injury overrides if data is provided
    rosters = {}
    injury_overrides = {}
    all_matchups = []
    current_season_h2h = records.get("h2h_season", {})
    
    if data is not None:
        rosters = get_rosters_from_lineups(data.lineups)
        injury_overrides = data.injury_overrides
        all_matchups = data.all_matchups
    
    for matchup in report.matchups:
        stats_a = report.manager_stats[matchup.manager_a]
        stats_b = report.manager_stats[matchup.manager_b]
        
        # Get season series
        series_a, series_b = get_season_series(records, matchup.manager_a, matchup.manager_b)
        
        # Get all-time series
        h2h_key = f"{min(matchup.manager_a, matchup.manager_b)}_vs_{max(matchup.manager_a, matchup.manager_b)}"
        all_time_record = all_time_h2h.get(h2h_key, {})
        all_time_a = all_time_record.get(matchup.manager_a.lower(), 0)
        all_time_b = all_time_record.get(matchup.manager_b.lower(), 0)
        
        # Get H2H streak (if data available)
        h2h_streak_holder = ""
        h2h_streak_length = 0
        h2h_streak_last_loss_season = ""
        
        if all_matchups and week is not None:
            current_season = records.get("season_records", {}).get("season", CURRENT_SEASON)
            # Use weekly_scores + schedule for accurate current season H2H tracking
            weekly_scores = records.get("weekly_scores", {})
            h2h_streak = get_h2h_streak(
                all_matchups,
                matchup.manager_a,
                matchup.manager_b,
                current_season=current_season,
                current_season_h2h=current_season_h2h,
                weekly_scores=weekly_scores,
                schedule=data.schedule if data else None,
            )
            h2h_streak_holder = h2h_streak.get("streak_holder", "") or ""
            h2h_streak_length = h2h_streak.get("streak_length", 0)
            h2h_streak_last_loss_season = h2h_streak.get("last_loss_season", "") or ""
        
        # Get notable injuries (if data available)
        notable_injuries_a = []
        notable_injuries_b = []
        
        if injury_overrides and rosters and week is not None:
            notable_injuries_a = get_notable_injuries(
                matchup.manager_a, week, injury_overrides, rosters
            )
            notable_injuries_b = get_notable_injuries(
                matchup.manager_b, week, injury_overrides, rosters
            )
        
        summary = {
            "manager_a": matchup.manager_a,
            "manager_b": matchup.manager_b,
            "score_a": matchup.score_a,
            "score_b": matchup.score_b,
            "winner": matchup.winner,
            "margin": matchup.margin,
            "season_series": {
                matchup.manager_a: series_a,
                matchup.manager_b: series_b,
            },
            "all_time_series": {
                matchup.manager_a: all_time_a,
                matchup.manager_b: all_time_b,
            },
            # H2H streak info
            "h2h_streak_holder": h2h_streak_holder,
            "h2h_streak_length": h2h_streak_length,
            "h2h_streak_last_loss_season": h2h_streak_last_loss_season,
            # Notable injuries
            "notable_injuries_a": notable_injuries_a,
            "notable_injuries_b": notable_injuries_b,
            "stats_a": {
                "total_fp": stats_a.total_fp,
                "efficiency_pct": stats_a.efficiency_pct,
                "games_lost_to_injury": stats_a.games_lost_to_injury,
                "injury_breakdown": stats_a.injury_breakdown,
                "guard_fp": stats_a.guard_stats.total_fp,
                "forward_fp": stats_a.forward_stats.total_fp,
                "center_fp": stats_a.center_stats.total_fp,
                "best_performers": [
                    {
                        "name": p.player_name,
                        "fp": p.total_fp,
                        "games": p.games_started,
                    }
                    for p in stats_a.best_performers
                ],
                "worst_performer": {
                    "name": stats_a.worst_healthy_performer.player_name if stats_a.worst_healthy_performer else None,
                    "fppg": stats_a.worst_healthy_performer.fppg if stats_a.worst_healthy_performer else 0,
                    "games": stats_a.worst_healthy_performer.games_started if stats_a.worst_healthy_performer else 0,
                } if stats_a.worst_healthy_performer else None,
            },
            "stats_b": {
                "total_fp": stats_b.total_fp,
                "efficiency_pct": stats_b.efficiency_pct,
                "games_lost_to_injury": stats_b.games_lost_to_injury,
                "injury_breakdown": stats_b.injury_breakdown,
                "guard_fp": stats_b.guard_stats.total_fp,
                "forward_fp": stats_b.forward_stats.total_fp,
                "center_fp": stats_b.center_stats.total_fp,
                "best_performers": [
                    {
                        "name": p.player_name,
                        "fp": p.total_fp,
                        "games": p.games_started,
                    }
                    for p in stats_b.best_performers
                ],
                "worst_performer": {
                    "name": stats_b.worst_healthy_performer.player_name if stats_b.worst_healthy_performer else None,
                    "fppg": stats_b.worst_healthy_performer.fppg if stats_b.worst_healthy_performer else 0,
                    "games": stats_b.worst_healthy_performer.games_started if stats_b.worst_healthy_performer else 0,
                } if stats_b.worst_healthy_performer else None,
            },
        }
        summaries.append(summary)
    
    return summaries


def build_report_cards(report: WeeklyReport, what_if: "WeeklyWhatIf" = None) -> list[dict]:
    """
    Build manager report cards section using the original grading formula.
    
    Components:
    - Efficiency score: Based on team performance vs projections
    - Management score: Based on bench decisions, blunders, missed flips, scheduled games
    - Waiver score: Based on waiver wire activity and production
    - Overall: Weighted combination of the above
    """
    cards = []
    
    # Get team efficiency % from weekly_stats (already correctly calculated)
    # Efficiency = actual FP from healthy starters / projected FPPG from healthy starters
    # This measures performance vs projection, NOT roster utilization
    team_eff_pcts = {}
    for manager in MANAGERS:
        stats = report.manager_stats[manager]
        # Convert from percentage (e.g., 106.3%) to delta from 100 (e.g., +6.3%)
        # Used in grading formula where positive = outperformed projections
        team_eff_pcts[manager] = stats.efficiency_pct - 100.0
    
    # Calculate scheduled games z-scores for each manager
    scheduled_games_data = {}
    all_scheduled = [report.manager_stats[m].total_scheduled_games for m in MANAGERS]
    avg_scheduled = sum(all_scheduled) / len(all_scheduled) if all_scheduled else 0
    
    # Calculate standard deviation
    if len(all_scheduled) > 1:
        variance = sum((x - avg_scheduled) ** 2 for x in all_scheduled) / len(all_scheduled)
        std_scheduled = variance ** 0.5
    else:
        std_scheduled = 1  # Avoid division by zero
    
    for manager in MANAGERS:
        sched = report.manager_stats[manager].total_scheduled_games
        z_score = (sched - avg_scheduled) / std_scheduled if std_scheduled > 0 else 0
        scheduled_games_data[manager] = {
            "scheduled_games": sched,
            "league_avg": avg_scheduled,
            "z_score": z_score,
        }
    
    # Build cards
    for manager in MANAGERS:
        stats = report.manager_stats[manager]
        eff_pct = team_eff_pcts.get(manager, 0.0)
        
        # -------------------------
        # Efficiency score: 0% -> 75, +20% (or higher) -> 100; very negative can go to 0
        # -------------------------
        eff_pct_capped = min(eff_pct, 20)
        eff_score = 75 + eff_pct_capped * 1.25
        eff_score = max(0, min(100, eff_score))
        
        # -------------------------
        # Management score
        # -------------------------
        bench_left = stats.games_left_on_bench
        
        # Get missed flip/big swings and blunders from what_if if available
        miss_flip = 0
        miss_big = 0
        blunders = 0
        blunder_points = 0.0
        if what_if and manager in what_if.manager_analysis:
            analysis = what_if.manager_analysis[manager]
            # Count matchup-flipping swaps as missed flips
            if analysis.would_flip_matchup:
                miss_flip = 1
            # Count swaps with gain > 20 as "big swings"
            for swap in analysis.swaps:
                if swap.gain > 20:
                    miss_big += 1
            # Blunders: bench games where a starter slot was available
            blunders = analysis.total_blunders
            blunder_points = analysis.total_blunder_points
        
        # Penalties:
        #   -2 per game left on bench (unavoidable overflow is mild)
        #   -5 per blunder (manager negligence -- avoidable points left on table)
        #   -9 per missed matchup flip
        #   -3 per missed big swing (>20 pt swap)
        mgmt_score = 95 - 2 * bench_left - 5 * blunders - 9 * miss_flip - 3 * miss_big
        mgmt_score = max(0, min(100, mgmt_score))
        
        # Scheduled-games adjustment: +1 SD -> +10 points; -1 SD -> -10; cap at -> 15
        sg = scheduled_games_data[manager]
        games_adj = max(-15.0, min(15.0, sg["z_score"] * 10.0))
        mgmt_score = max(0, min(100, mgmt_score + games_adj))
        
        # -------------------------
        # Waiver score
        # -------------------------
        # Scoring philosophy:
        #   - 75 = no waiver activity (neutral, didn't help or hurt)
        #   - 80 = average waiver week (~100 FP per add, ~30 FPPG)
        #   - 90 = good waiver week (~130 FP per add, ~40 FPPG)
        #   - 100 = excellent waiver week (~160+ FP per add, ~50+ FPPG)
        #   - 60 = poor waiver week (~40 FP per add, ~15 FPPG)
        #   - Below 50 = disaster (waiver adds were bench-worthy)
        #
        # Formula: Linear scale centered at 80 for 100 FP/add
        #   waiver_score = 80 + (fp_per_add - 100) / 3
        #   This gives: 40 FP -> 60, 100 FP -> 80, 130 FP -> 90, 160 FP -> 100
        
        adds_count = len(stats.waiver_adds)
        waiver_fp = stats.waiver_fp
        
        if adds_count == 0:
            waiver_score = 75.0  # Neutral - no waiver activity
            fp_per_add = 0.0
        else:
            fp_per_add = waiver_fp / adds_count
            # Linear scale: 100 FP/add = 80 score, +/- 3 FP = +/- 1 point
            waiver_score = 80 + (fp_per_add - 100) / 3
            waiver_score = max(0, min(100, waiver_score))
        
        # -------------------------
        # Overall formula
        # -------------------------
        overall = 35 + 1.5 * eff_pct + 0.35 * mgmt_score + 0.15 * waiver_score
        overall = max(0, min(100, overall))
        
        # Letter grade ladder
        def letter(x):
            if x >= 97:
                return "A+"
            if x >= 93:
                return "A"
            if x >= 90:
                return "A-"
            if x >= 86:
                return "B+"
            if x >= 82:
                return "B"
            if x >= 78:
                return "B-"
            if x >= 74:
                return "C+"
            if x >= 70:
                return "C"
            if x >= 66:
                return "C-"
            if x >= 62:
                return "D+"
            if x >= 58:
                return "D"
            if x >= 54:
                return "D-"
            return "F"
        
        cards.append({
            "manager": manager,
            "team_name": stats.fantasy_team,
            "letter_grade": letter(overall),
            "overall_score": round(overall, 1),
            "efficiency_score": round(eff_score, 1),
            "management_score": round(mgmt_score, 1),
            "waiver_score": round(waiver_score, 1),
            "efficiency_pct": round(stats.efficiency_pct, 1),  # Actual efficiency (e.g., 106.3%)
            "team_efficiency_pct": round(eff_pct, 1),  # Delta from 100% (e.g., +6.3%)
            "weekly_fp": stats.total_fp,
            "games_left_on_bench": bench_left,
            "blunders": blunders,
            "blunder_points": round(blunder_points, 1),
            "games_lost_to_injury": stats.games_lost_to_injury,
            "injury_breakdown": stats.injury_breakdown,
            "missed_flip_swings": miss_flip,
            "missed_big_swings": miss_big,
            "waiver_adds_count": adds_count,
            "waiver_fp_total": waiver_fp,
            "waiver_games": stats.waiver_games,
            "waiver_fppg": round(waiver_fp / stats.waiver_games, 2) if stats.waiver_games > 0 else 0.0,
            "fp_per_add": round(fp_per_add, 1),
            "scheduled_games": sg["scheduled_games"],
            "scheduled_games_league_avg": round(sg["league_avg"], 1),
            "scheduled_games_z_score": round(sg["z_score"], 2),
            "scheduled_games_adjustment": round(games_adj, 1),
            "total_starter_games": stats.total_healthy_starter_games,
            "record": stats.record_str,
        })
    
    # Sort by overall score descending
    cards.sort(key=lambda r: (-r["overall_score"], r["manager"]))
    return cards


def build_power_rankings(
    title_odds: TitleOddsResult,
    records: dict,
    leaguehistory: "pd.DataFrame" = None,
    keeper_watch: dict = None,
) -> list[dict]:
    """Build power rankings section.
    
    When keeper_watch is provided (V2 keepability data), a keeper_quality
    score is computed for each team (average keepability of top 5 rostered
    players) and blended into the ranking at 20% weight.
    """
    from .data_loader import MANAGER_TO_TEAM
    
    rankings = []
    
    # Get career stats from all-time records
    career_stats = records.get("all_time", {}).get("manager_careers", {})
    
    # Get championships from leaguehistory
    championships = {}
    if leaguehistory is not None and not leaguehistory.empty:
        for _, row in leaguehistory.iterrows():
            manager = row.get("manager_name")
            titles = row.get("titles_won", 0)
            if manager:
                championships[manager] = int(titles) if titles else 0
    
    # Compute keeper quality scores per manager (if V2 data available)
    keeper_quality = {}
    top_5_keepers = {}
    if keeper_watch:
        for manager in MANAGERS:
            mgr_players = [
                p for p in keeper_watch.get("players", [])
                if p.get("manager") == manager
            ]
            mgr_players.sort(key=lambda x: -x.get("keepability_score", 0))
            top_5 = mgr_players[:5]
            
            if top_5:
                avg_score = sum(p.get("keepability_score", 0) for p in top_5) / len(top_5)
                keeper_quality[manager] = round(avg_score, 1)
                top_5_keepers[manager] = [p["player_name"] for p in top_5]
            else:
                keeper_quality[manager] = 0.0
                top_5_keepers[manager] = []
    
    # Sort by title odds (optionally blended with keeper quality)
    # If keeper data available: 80% title odds + 20% keeper quality (normalized)
    def sort_key(m):
        base_odds = title_odds.title_odds[m]
        if keeper_quality:
            # Normalize keeper quality to same scale as title odds (0-100)
            kq = keeper_quality.get(m, 0)
            blended = 0.80 * base_odds + 0.20 * kq
            return (blended, title_odds.expected_record[m][0])
        return (base_odds, title_odds.expected_record[m][0])
    
    sorted_managers = sorted(MANAGERS, key=sort_key, reverse=True)
    
    for rank, manager in enumerate(sorted_managers, 1):
        wins, losses = title_odds.current_records[manager]
        exp_wins, exp_losses = title_odds.expected_record[manager]
        
        delta = title_odds.title_odds_delta.get(manager)
        if delta is not None:
            if delta > 1:
                trend = "up"
            elif delta < -1:
                trend = "down"
            else:
                trend = "flat"
            trend_value = abs(delta)
        else:
            trend = "flat"
            trend_value = 0
        
        # Career record for this manager
        career = career_stats.get(manager, {})
        career_wins = career.get("total_wins", 0)
        career_losses = career.get("total_losses", 0)
        career_win_pct = career.get("win_pct", 0)
        
        rankings.append({
            "rank": rank,
            "manager": manager,
            "team_name": MANAGER_TO_TEAM.get(manager, manager),
            "record": f"{wins}-{losses}",
            "title_odds": title_odds.title_odds[manager],
            "trend": trend,
            "trend_value": trend_value,
            "expected_record": f"{exp_wins:.1f}-{exp_losses:.1f}",
            "magic_number": title_odds.magic_numbers.get(manager),
            "finish_distribution": title_odds.finish_distribution[manager],
            "career_record": f"{career_wins}-{career_losses}" if career_wins > 0 else None,
            "career_win_pct": career_win_pct,
            "championships": championships.get(manager, 0),
            # Playoff bracket championships -- distinct from regular-season titles.
            "playoff_championships": career.get("playoff_titles", 0),
            "keeper_quality": keeper_quality.get(manager),
            "top_5_keepers": top_5_keepers.get(manager, []),
        })
    
    return rankings


def build_best_worst(report: WeeklyReport, data: FantasyData, week: int) -> dict:
    """Build best/worst of the week section."""
    # Best single games
    all_games = []
    for ps in report.all_player_stats:
        for game in ps.game_logs:
            if game["started"] and not game["is_injured"]:
                all_games.append({
                    "player_name": ps.player_name,
                    "nba_team": ps.nba_team,
                    "manager": ps.manager,
                    "date": game["date"],
                    "fantasy_points": game["fantasy_points"],
                    "nba_opponent": game.get("nba_opponent", ""),
                })
    
    all_games.sort(key=lambda x: x["fantasy_points"], reverse=True)
    best_games = all_games[:5]
    worst_games = sorted(all_games, key=lambda x: x["fantasy_points"])[:5]
    
    # Best waiver pickups (from report)
    waiver_performances = []
    for manager in MANAGERS:
        stats = report.manager_stats[manager]
        for waiver_player in stats.waiver_adds:
            if waiver_player in stats.player_stats:
                ps = stats.player_stats[waiver_player]
                if ps.games_started > 0:
                    waiver_performances.append({
                        "player_name": waiver_player,
                        "nba_team": ps.nba_team,
                        "manager": manager,
                        "games": ps.games_started,
                        "total_fp": ps.total_fp,
                        "fppg": ps.fppg,
                    })
    
    # Sort by total FP descending (most productive first)
    waiver_performances.sort(key=lambda x: x["total_fp"], reverse=True)
    
    # All waivers included - no limit
    best_waivers = waiver_performances
    
    # Best available free agents with game counts
    free_agents = data.get_free_agents()
    best_fa = []
    
    # Get date ranges for NEXT week and the week after (for FA pickup recommendations)
    # When reporting on week N, we want to show games for week N+1 and N+2
    this_week_dates = []  # Actually next week (week + 1)
    next_week_dates = []  # Week after (week + 2)
    for w in data.schedule.get("weeks", []):
        if w["week"] == week + 1:
            from datetime import datetime, timedelta
            start = datetime.strptime(w["start_date"], "%Y-%m-%d").date()
            end = datetime.strptime(w["end_date"], "%Y-%m-%d").date()
            current = start
            while current <= end:
                this_week_dates.append(current)
                current += timedelta(days=1)
        elif w["week"] == week + 2:
            from datetime import datetime, timedelta
            start = datetime.strptime(w["start_date"], "%Y-%m-%d").date()
            end = datetime.strptime(w["end_date"], "%Y-%m-%d").date()
            current = start
            while current <= end:
                next_week_dates.append(current)
                current += timedelta(days=1)
    
    # Count games per team for this week and next week
    def count_team_games(dates_list):
        team_games = {}
        for d in dates_list:
            games = data.get_nba_games_for_date(d)
            for game in games:
                home = game.get("home_team", "")
                away = game.get("away_team", "")
                if home:
                    team_games[home] = team_games.get(home, 0) + 1
                if away:
                    team_games[away] = team_games.get(away, 0) + 1
        return team_games
    
    this_week_team_games = count_team_games(this_week_dates)
    next_week_team_games = count_team_games(next_week_dates)
    
    # Build set of injured player names from INJURY_OVERRIDES
    injured_players = set()
    for player in data.injury_overrides.get("players", []):
        player_name = player.get("player_name", "")
        out_weeks = player.get("out_weeks", [])
        # Exclude if player has ANY weeks they're out for
        if player_name and out_weeks:
            injured_players.add(player_name)
    
    if not free_agents.empty:
        # Filter out injured players before sorting
        if injured_players:
            free_agents = free_agents[~free_agents["player_name"].isin(injured_players)]
        
        fa_sorted = free_agents.sort_values("projectedFPPG", ascending=False)
        for _, row in fa_sorted.head(5).iterrows():
            nba_team = row.get("player_nba_team", "")
            best_fa.append({
                "player_name": row["player_name"],
                "positions": row.get("player_position(s)", ""),
                "nba_team": nba_team,
                "projected_fppg": row.get("projectedFPPG", 0),
                "games_this_week": this_week_team_games.get(nba_team, 0),
                "games_next_week": next_week_team_games.get(nba_team, 0),
            })
    
    return {
        "best_games": best_games,
        "worst_games": worst_games,
        "best_waivers": best_waivers,
        "best_free_agents": best_fa,
    }


def build_team_stats(report: WeeklyReport) -> list[dict]:
    """Build team stats section with FPPG and positional breakdown."""
    stats = []
    
    for manager in MANAGERS:
        ms = report.manager_stats[manager]
        
        # Calculate team FPPG
        team_fppg = ms.total_fp / ms.total_healthy_starter_games if ms.total_healthy_starter_games > 0 else 0
        
        # Calculate positional FPPG
        guard_fppg = ms.guard_stats.total_fp / ms.guard_stats.games if ms.guard_stats.games > 0 else 0
        forward_fppg = ms.forward_stats.total_fp / ms.forward_stats.games if ms.forward_stats.games > 0 else 0
        center_fppg = ms.center_stats.total_fp / ms.center_stats.games if ms.center_stats.games > 0 else 0
        
        stats.append({
            "manager": manager,
            "team_name": MANAGER_TO_TEAM.get(manager, manager),
            "weekly_fp": ms.total_fp,
            "games_played": ms.total_healthy_starter_games,
            "team_fppg": round(team_fppg, 2),
            "scheduled_games": ms.total_scheduled_games,
            "games_lost_to_injury": ms.games_lost_to_injury,
            "games_left_on_bench": ms.games_left_on_bench,
            "efficiency_pct": ms.efficiency_pct,
            "positional_stats": {
                "guard": {
                    "total_fp": ms.guard_stats.total_fp,
                    "games": ms.guard_stats.games,
                    "fppg": round(guard_fppg, 2),
                    "players": ms.guard_stats.players,
                },
                "forward": {
                    "total_fp": ms.forward_stats.total_fp,
                    "games": ms.forward_stats.games,
                    "fppg": round(forward_fppg, 2),
                    "players": ms.forward_stats.players,
                },
                "center": {
                    "total_fp": ms.center_stats.total_fp,
                    "games": ms.center_stats.games,
                    "fppg": round(center_fppg, 2),
                    "players": ms.center_stats.players,
                },
            },
        })
    
    # Sort by total FP descending
    stats.sort(key=lambda x: x["weekly_fp"], reverse=True)
    return stats


def build_player_of_week(report: WeeklyReport) -> dict:
    """Determine Player of the Week with best game details."""
    # Get all qualified players (min 2 GP, healthy starter)
    candidates = []
    
    for ps in report.all_player_stats:
        if ps.games_started < 2:
            continue
        
        # Calculate efficiency contribution (% of team's total points)
        manager_stats = report.manager_stats[ps.manager]
        efficiency_contribution = (ps.total_fp / manager_stats.total_fp * 100) if manager_stats.total_fp > 0 else 0
        
        # Get actual player efficiency (vs projection) as delta from 100%
        # e.g., if efficiency_pct is 111.3%, player_efficiency_delta is +11.3%
        player_efficiency_delta = None
        if ps.efficiency_pct is not None:
            player_efficiency_delta = ps.efficiency_pct - 100.0
        
        # Get best game details
        best_game_info = None
        if ps.best_game:
            bg = ps.best_game
            best_game_info = {
                "date": bg.get("date", ""),
                "opponent": bg.get("nba_opponent", ""),
                "fantasy_points": bg.get("fantasy_points", 0),
            }
        
        candidates.append({
            "player_name": ps.player_name,
            "manager": ps.manager,
            "total_fp": ps.total_fp,
            "fppg": ps.fppg,
            "games": ps.games_started,
            "efficiency_contribution": efficiency_contribution,  # % of team total (for selection tiers)
            "efficiency_pct": player_efficiency_delta,  # Delta from 100% (e.g., +11.3 means 111.3%)
            "nba_team": ps.nba_team,
            "best_game": best_game_info,
        })
    
    if not candidates:
        return None
    
    # Sort by total FP, then FPPG
    candidates.sort(key=lambda x: (x["total_fp"], x["fppg"]), reverse=True)
    
    # Apply qualification tiers
    top_total = sorted(candidates, key=lambda x: x["total_fp"], reverse=True)
    top_fppg = sorted(candidates, key=lambda x: x["fppg"], reverse=True)
    
    top_4_total = set(c["player_name"] for c in top_total[:4])
    top_4_fppg = set(c["player_name"] for c in top_fppg[:4])
    top_8_total = set(c["player_name"] for c in top_total[:8])
    
    winner = None
    
    # Tier 1: Top 4 total AND top 4 FPPG AND efficiency_contribution >= 15%
    for c in candidates:
        if (c["player_name"] in top_4_total and 
            c["player_name"] in top_4_fppg and 
            c["efficiency_contribution"] >= 15):
            winner = c
            break
    
    # Tier 2: Top 8 total AND top 4 FPPG AND efficiency_contribution >= 15%
    if not winner:
        for c in candidates:
            if (c["player_name"] in top_8_total and 
                c["player_name"] in top_4_fppg and 
                c["efficiency_contribution"] >= 15):
                winner = c
                break
    
    # Tier 3: Top 4 total AND efficiency_contribution >= 10%
    if not winner:
        for c in candidates:
            if c["player_name"] in top_4_total and c["efficiency_contribution"] >= 10:
                winner = c
                break
    
    # Fallback: Highest total FP
    if not winner:
        winner = candidates[0]
    
    # Get honorable mentions
    honorable = [c for c in candidates if c["player_name"] != winner["player_name"]][:2]
    
    return {
        "winner": winner,
        "honorable_mentions": honorable,
    }


def build_scoring_trends(records: dict, current_week: int) -> dict:
    """
    Build scoring trends section showing each manager's recent trajectory.
    
    Returns dict with:
    - last_5_weeks: list of scores
    - last_5_avg: average of last 5 weeks
    - last_3_avg: average of last 3 weeks (more recent trend)
    - season_avg: full season average
    - trend: "hot", "cold", or "stable"
    - trend_description: human-readable description
    """
    weekly_scores = records.get("weekly_scores", {})
    
    trends = {}
    for manager, scores_list in weekly_scores.items():
        if not scores_list:
            continue
        
        # Extract just the scores, sorted by week
        sorted_scores = sorted(scores_list, key=lambda x: x["week"])
        all_scores = [s["score"] for s in sorted_scores]
        
        # Calculate averages
        season_avg = sum(all_scores) / len(all_scores) if all_scores else 0
        
        last_5 = all_scores[-5:] if len(all_scores) >= 5 else all_scores
        last_5_avg = sum(last_5) / len(last_5) if last_5 else 0
        
        last_3 = all_scores[-3:] if len(all_scores) >= 3 else all_scores
        last_3_avg = sum(last_3) / len(last_3) if last_3 else 0
        
        # Determine trend based on last 3 vs season average
        if season_avg > 0:
            pct_diff = (last_3_avg - season_avg) / season_avg * 100
            
            if pct_diff >= 8:
                trend = "hot"
                trend_desc = f"averaging {last_3_avg:.0f} over last 3 weeks, {pct_diff:.0f}% above season average"
            elif pct_diff <= -8:
                trend = "cold"
                trend_desc = f"averaging {last_3_avg:.0f} over last 3 weeks, {abs(pct_diff):.0f}% below season average"
            else:
                trend = "stable"
                trend_desc = f"averaging {last_3_avg:.0f} over last 3 weeks, in line with season average"
        else:
            trend = "stable"
            trend_desc = "insufficient data"
        
        # Get week-over-week trajectory
        if len(all_scores) >= 2:
            recent_trajectory = []
            for i in range(max(0, len(all_scores) - 3), len(all_scores)):
                if i > 0:
                    diff = all_scores[i] - all_scores[i-1]
                    # Use Unicode escape sequences for arrows
                    if diff > 50:
                        recent_trajectory.append("^")  # up arrow
                    elif diff < -50:
                        recent_trajectory.append("v")  # down arrow
                    else:
                        recent_trajectory.append("->")  # right arrow
            trajectory_str = "".join(recent_trajectory)
        else:
            trajectory_str = ""
        
        trends[manager] = {
            "last_5_weeks": last_5,
            "last_5_avg": round(last_5_avg, 1),
            "last_3_avg": round(last_3_avg, 1),
            "season_avg": round(season_avg, 1),
            "trend": trend,
            "trend_description": trend_desc,
            "trajectory": trajectory_str,
            "current_week_score": all_scores[-1] if all_scores else 0,
            "weeks_played": len(all_scores),
        }
    
    return trends


def build_rosters(data: FantasyData) -> dict:
    """
    Build a simple roster mapping for each manager.
    
    Returns dict mapping manager name to list of player names.
    Used by LLM to connect NBA news to fantasy implications.
    
    Uses config/ROSTERS.json if it exists, otherwise falls back to LINEUPS.
    """
    from .projections import load_rosters_from_config
    
    # Try loading from config file first
    config_rosters = load_rosters_from_config()
    if config_rosters:
        return config_rosters
    
    # Fall back to LINEUPS
    rosters = {}
    
    # Get the most recent week's lineups to determine current rosters
    max_week = data.lineups['week'].max()
    recent_lineups = data.lineups[data.lineups['week'] == max_week]
    
    for manager in MANAGERS:
        # Get all unique players on this manager's roster from recent lineups
        manager_players = recent_lineups[
            recent_lineups['manager'] == manager
        ]['player_name'].unique().tolist()
        
        rosters[manager] = sorted(manager_players)
    
    return rosters


def build_current_streaks(records: dict) -> dict:
    """
    Build current win/loss streaks for each manager, plus season-longest streaks.
    
    Returns dict mapping manager -> {win_streak, loss_streak, season_longest_win, season_longest_loss}.
    
    Handles both old format (current_win_streak/current_loss_streak dicts)
    and new format (current_streaks with win/loss keys per manager).
    """
    season_records = records.get("season_records", {})
    
    # Get season-longest streaks
    season_longest_win = season_records.get("season_longest_win_streak", {})
    season_longest_loss = season_records.get("season_longest_loss_streak", {})
    
    # Check for new format first
    if "current_streaks" in season_records:
        streaks = {}
        for manager in MANAGERS:
            mgr_streaks = season_records["current_streaks"].get(manager, {})
            longest_win = season_longest_win.get(manager, {})
            longest_loss = season_longest_loss.get(manager, {})
            streaks[manager] = {
                "win_streak": mgr_streaks.get("win", 0),
                "loss_streak": mgr_streaks.get("loss", 0),
                "season_longest_win_streak": longest_win.get("length", 0),
                "season_longest_win_weeks": f"{longest_win.get('start_week', 0)}-{longest_win.get('end_week', 0)}" if longest_win.get("length", 0) > 0 else None,
                "season_longest_loss_streak": longest_loss.get("length", 0),
                "season_longest_loss_weeks": f"{longest_loss.get('start_week', 0)}-{longest_loss.get('end_week', 0)}" if longest_loss.get("length", 0) > 0 else None,
            }
        return streaks
    
    # Fall back to old format
    win_streaks = season_records.get("current_win_streak", {})
    loss_streaks = season_records.get("current_loss_streak", {})
    
    streaks = {}
    for manager in MANAGERS:
        longest_win = season_longest_win.get(manager, {})
        longest_loss = season_longest_loss.get(manager, {})
        streaks[manager] = {
            "win_streak": win_streaks.get(manager, 0),
            "loss_streak": loss_streaks.get(manager, 0),
            "season_longest_win_streak": longest_win.get("length", 0),
            "season_longest_win_weeks": f"{longest_win.get('start_week', 0)}-{longest_win.get('end_week', 0)}" if longest_win.get("length", 0) > 0 else None,
            "season_longest_loss_streak": longest_loss.get("length", 0),
            "season_longest_loss_weeks": f"{longest_loss.get('start_week', 0)}-{longest_loss.get('end_week', 0)}" if longest_loss.get("length", 0) > 0 else None,
        }
    
    return streaks


def build_season_injury_burden(data: FantasyData) -> dict:
    """
    Build season-long injury burden statistics from LINEUPS.
    
    SLOT TREATMENT:
    - IL+ is treated identically to BN (just another bench slot).
    - IL means the player is injured. ANY IL row with an nba_opponent
      counts as an IL Injury Game, regardless of fantasy_points.
    
    Three metrics are calculated:
    
    1. Non-IL Injury Burden %: What % of non-IL scheduled games were lost to injury?
       - Non-IL slots = starters, Util, BN, and IL+ (IL+ treated as bench)
       - Injury = has_game AND fantasy_points == 0.0
       - Measures unexpected injuries and roster management pain
    
    2. Total Injury Burden %: What % of ALL scheduled games were lost to injury?
       - Combines non-IL injury games + ALL IL scheduled games
       - Measures true injury luck across the entire roster
    
    3. IL Injury Games: How many scheduled games occurred in IL slots?
       - Every IL row with an nba_opponent counts (the slot itself = injured)
       - Shows who's been forced to use IL most
       - In a perfectly healthy season, this would be 0
    
    Returns:
        Dict mapping manager -> injury burden stats
    """
    lineups = data.lineups.copy()
    
    # Derive has_game
    lineups['has_game'] = (
        lineups['nba_opponent'].notna() & 
        (lineups['nba_opponent'].astype(str).str.strip() != '')
    )
    
    injury_burden = {}
    
    for manager in MANAGERS:
        mgr_df = lineups[lineups['manager'] == manager]
        
        # All games with opponent (any slot)
        all_games = mgr_df[mgr_df['has_game'] == True]
        total_all_games = len(all_games)
        
        # --- IL slot: ANY scheduled game = injury game ---
        il_games = all_games[all_games['slot'] == 'IL']
        il_injury_games = len(il_games)  # ALL IL scheduled games count
        
        # --- Non-IL slots (starters, Util, BN, IL+): injury = fp == 0.0 ---
        non_il_games = all_games[all_games['slot'] != 'IL']
        total_non_il = len(non_il_games)
        non_il_injuries = len(non_il_games[non_il_games['fantasy_points'] == 0.0])
        
        # --- Totals ---
        total_all_injuries = non_il_injuries + il_injury_games
        
        # Calculate percentages
        non_il_pct = (non_il_injuries / total_non_il * 100) if total_non_il > 0 else 0.0
        total_pct = (total_all_injuries / total_all_games * 100) if total_all_games > 0 else 0.0
        
        # Get top injured players (non-IL only, for the "surprise" injuries)
        non_il_injury_rows = mgr_df[
            (mgr_df['has_game'] == True) &
            (mgr_df['slot'] != 'IL') &
            (mgr_df['fantasy_points'] == 0.0)
        ]
        top_non_il_injured = (
            non_il_injury_rows
            .groupby('player_name')
            .size()
            .reset_index(name='games')
            .sort_values('games', ascending=False)
            .head(5)
        )
        
        # Get IL slot breakdown (who's been stashed)
        # ALL IL scheduled games count, not just fp == 0.0
        il_all_rows = mgr_df[
            (mgr_df['has_game'] == True) &
            (mgr_df['slot'] == 'IL')
        ]
        il_players = (
            il_all_rows
            .groupby('player_name')
            .size()
            .reset_index(name='games')
            .sort_values('games', ascending=False)
        )
        
        injury_burden[manager] = {
            # Non-IL metrics (unexpected injuries in starter/BN/IL+ slots)
            "non_il_injury_burden_pct": round(non_il_pct, 1),
            "non_il_injury_games": non_il_injuries,
            "total_non_il_games": total_non_il,
            "top_non_il_injured": [
                {"player": row['player_name'], "games": int(row['games'])}
                for _, row in top_non_il_injured.iterrows()
            ],
            # Total metrics (non-IL injuries + ALL IL scheduled games)
            "total_injury_burden_pct": round(total_pct, 1),
            "total_injury_games": total_all_injuries,
            "total_scheduled_games": total_all_games,
            # IL usage (every IL scheduled game counts)
            "il_injury_games": il_injury_games,
            "il_players": [
                {"player": row['player_name'], "games": int(row['games'])}
                for _, row in il_players.iterrows()
            ],
        }
    
    return injury_burden


def build_current_team_health(
    data: FantasyData,
    week: int,
    injury_overrides: dict = None,
) -> dict:
    """
    Build current team health snapshot for the upcoming week.
    
    This measures each team's health at the TIME of newsletter generation,
    showing what percentage of their projected production is available.
    
    Unlike season_injury_burden (which tracks historical injury impact),
    this shows the CURRENT state - useful for matchup previews and
    identifying teams that are "finally getting healthy" vs "still decimated".
    
    Args:
        data: FantasyData container
        week: Current week number (health is calculated for week+1)
        injury_overrides: INJURY_OVERRIDES data dict (optional, uses data.injury_overrides if not provided)
    
    Returns:
        Dict with team health data and rankings
    """
    # Use data.injury_overrides if not explicitly provided
    if injury_overrides is None:
        injury_overrides = data.injury_overrides if data.injury_overrides else {"players": []}
    
    # Load player projections from PLAYERLIST
    playerlist = data.playerlist
    proj_by_player = {}
    for _, row in playerlist.iterrows():
        name = row['player_name']
        proj_fppg = row.get('projectedFPPG', 0) or 0
        proj_by_player[name] = float(proj_fppg)
    
    # Get rosters
    rosters = {}
    if hasattr(data, 'get_current_rosters'):
        rosters = data.get_current_rosters()
    else:
        # Fall back to extracting from lineups
        rosters = get_rosters_from_lineups(data.lineups)
    
    # Build injury lookup: player -> {out_weeks, notes, return fields}
    injury_lookup = {}
    for entry in injury_overrides.get("players", []):
        player_name = entry.get("player_name", "")
        injury_lookup[player_name] = {
            "out_weeks": entry.get("out_weeks", []),
            "notes": entry.get("notes", ""),
            "return_week": entry.get("return_week"),
            "return_games": entry.get("return_games"),
            "total_week_games": entry.get("total_week_games"),
            "return_notes": entry.get("return_notes", ""),
        }
    
    # Calculate health for next week (week + 1)
    target_week = week + 1
    
    teams = {}
    returning_players = []  # Track players returning this week across all teams
    
    for manager in MANAGERS:
        roster = rosters.get(manager, [])
        
        total_fppg = 0.0
        injured_fppg = 0.0
        injured_players = []
        
        for player in roster:
            proj = proj_by_player.get(player, 0)
            total_fppg += proj
            
            if player not in injury_lookup:
                continue
            
            injury_info = injury_lookup[player]
            out_weeks = injury_info["out_weeks"]
            return_week = injury_info["return_week"]
            return_games = injury_info["return_games"]
            total_week_games = injury_info["total_week_games"]
            
            # Case 1: Player is fully out this week
            if target_week in out_weeks:
                injured_fppg += proj
                
                # Calculate remaining weeks
                remaining_weeks = sum(1 for w in out_weeks if w >= target_week)
                
                # Determine if season-long (18+ weeks out)
                is_season_long = len(out_weeks) >= 18
                
                injured_players.append({
                    "player": player,
                    "proj_fppg": round(proj, 1),
                    "notes": injury_info["notes"],
                    "remaining_weeks": remaining_weeks,
                    "is_season_long": is_season_long,
                    "status": "out",
                    "availability_pct": 0,
                })
            
            # Case 2: Player is returning this week with partial availability
            elif return_week == target_week and return_games and total_week_games:
                availability_pct = (return_games / total_week_games) * 100
                unavailable_fppg = proj * (1 - return_games / total_week_games)
                injured_fppg += unavailable_fppg
                
                injured_players.append({
                    "player": player,
                    "proj_fppg": round(proj, 1),
                    "notes": injury_info["return_notes"] or injury_info["notes"],
                    "remaining_weeks": 0,
                    "is_season_long": False,
                    "status": "returning",
                    "availability_pct": round(availability_pct, 0),
                    "return_games": return_games,
                    "total_week_games": total_week_games,
                })
                
                returning_players.append({
                    "player": player,
                    "manager": manager,
                    "proj_fppg": round(proj, 1),
                    "return_games": return_games,
                    "total_week_games": total_week_games,
                    "return_notes": injury_info["return_notes"],
                })
        
        healthy_fppg = total_fppg - injured_fppg
        health_pct = (healthy_fppg / total_fppg * 100) if total_fppg > 0 else 100.0
        
        # Sort injured players by proj_fppg descending
        injured_players.sort(key=lambda x: -x["proj_fppg"])
        
        teams[manager] = {
            "health_pct": round(health_pct, 1),
            "injured_players": injured_players,
            "injured_fppg": round(injured_fppg, 1),
            "healthy_fppg": round(healthy_fppg, 1),
            "total_fppg": round(total_fppg, 1),
            "num_injured": len(injured_players),
        }
    
    # Create rankings (sorted by health_pct descending)
    rankings = sorted(MANAGERS, key=lambda m: -teams[m]["health_pct"])
    
    return {
        "as_of_week": target_week,
        "teams": teams,
        "rankings": rankings,
        "healthiest": rankings[0],
        "most_injured": rankings[-1],
        "returning_players": returning_players,  # Players with confirmed partial returns
    }


# =============================================================================
# POSITIONAL SCORING BREAKDOWN
# =============================================================================


def build_positional_breakdown(data: FantasyData, week: int) -> dict:
    """
    Build positional scoring breakdown (G/F/C) per manager for the season.

    Uses PLAYERLOG started games to aggregate Total FP, GP, and FPPG
    by classified position group for each manager.

    Position classification uses classify_position_group() from data_loader
    (majority voting on Yahoo position tags, ties go to bigger position).

    Returns:
        {
            "managers": {
                "Nick": {
                    "G": {"gp": 80, "total_fp": 2500.5, "fppg": 31.26},
                    "F": {"gp": 90, "total_fp": 2800.0, "fppg": 31.11},
                    "C": {"gp": 45, "total_fp": 1600.0, "fppg": 35.56},
                    "total_gp": 215, "total_fp": 6900.5
                },
                ...
            },
            "league_totals": {
                "G": {"gp": ..., "total_fp": ..., "fppg": ...},
                "F": {...}, "C": {...}
            }
        }
    """
    import pandas as pd

    plog = data.playerlog
    # Filter to started games in completed weeks with actual production
    mask = (
        (plog["started"] == True)
        & (plog["week"] <= week)
        & (plog["fantasy_points"].notna())
        & (plog["fantasy_points"] != 0.0)
        & (plog["nba_opponent"].notna())
    )
    started = plog[mask].copy()

    # Classify each row using the shared function
    started["pos_group"] = started["positions"].apply(classify_position_group)

    managers_data = {}
    for mgr in MANAGERS:
        mgr_rows = started[started["manager"] == mgr]
        mgr_entry = {}
        total_gp = 0
        total_fp = 0.0
        for pos in ("G", "F", "C"):
            pos_rows = mgr_rows[mgr_rows["pos_group"] == pos]
            gp = len(pos_rows)
            fp = pos_rows["fantasy_points"].sum()
            fppg = round(fp / gp, 2) if gp > 0 else 0.0
            mgr_entry[pos] = {
                "gp": gp,
                "total_fp": round(fp, 1),
                "fppg": fppg,
            }
            total_gp += gp
            total_fp += fp
        mgr_entry["total_gp"] = total_gp
        mgr_entry["total_fp"] = round(total_fp, 1)
        managers_data[mgr] = mgr_entry

    # League totals
    league_totals = {}
    for pos in ("G", "F", "C"):
        pos_rows = started[started["pos_group"] == pos]
        gp = len(pos_rows)
        fp = pos_rows["fantasy_points"].sum()
        league_totals[pos] = {
            "gp": gp,
            "total_fp": round(fp, 1),
            "fppg": round(fp / gp, 2) if gp > 0 else 0.0,
        }

    return {
        "managers": managers_data,
        "league_totals": league_totals,
    }


# =============================================================================
# BENCH REPORT
# =============================================================================


def build_bench_report(data: FantasyData, week: int) -> dict:
    """
    Build season-long bench report per manager.

    Tracks FP left on bench (BN/IL+ rows with production) and blunder
    counts from RECORDS.json. Blunders are the subset of bench games
    where a starter slot was available.

    Returns:
        {
            "managers": {
                "Nick": {
                    "bench_gp": 26,
                    "bench_fp": 924.9,
                    "bench_fp_per_week": 57.8,
                    "blunders": 10,
                },
                ...
            }
        }
    """
    import pandas as pd

    lineups = data.lineups
    bench_mask = (
        (lineups["slot"].isin(["BN", "IL+"]))
        & (lineups["fantasy_points"] > 0)
        & (lineups["nba_opponent"].notna())
        & (lineups["week"] <= week)
    )
    bench = lineups[bench_mask]

    blunders = data.records.get("cumulative_blunders", {})

    managers_data = {}
    for mgr in MANAGERS:
        mgr_bench = bench[bench["manager"] == mgr]
        bench_gp = len(mgr_bench)
        bench_fp = round(mgr_bench["fantasy_points"].sum(), 1)
        bench_fp_per_week = round(bench_fp / week, 1) if week > 0 else 0.0

        managers_data[mgr] = {
            "bench_gp": bench_gp,
            "bench_fp": bench_fp,
            "bench_fp_per_week": bench_fp_per_week,
            "blunders": blunders.get(mgr, 0),
        }

    return {"managers": managers_data}


# =============================================================================
# RECORD BOOK SNAPSHOT
# =============================================================================


def _patch_cumulative_records(all_time: dict, data) -> None:
    """
    Patch cumulative all-time records with live current-season PLAYERLOG data.

    The backfill script stores ``historical_fp`` (all seasons except current) on
    career tables.  This function recomputes the current-season portion from the
    live PLAYERLOG and updates ``total_fp`` and ``gp`` so the Record Book stays
    fresh between backfill runs.
    """
    if not hasattr(data, "playerlog") or data.playerlog is None or data.playerlog.empty:
        return

    pl = data.playerlog
    if "started" in pl.columns:
        started = pl[pl["started"] == True]
    else:
        started = pl
    started = started[started["fantasy_points"].notna() & (started["fantasy_points"] != 0)]

    if started.empty:
        return

    # Current-season FP per (player, manager)
    current_fp_by_mgr = (
        started.groupby(["player_name", "manager"])
        .agg(fp=("fantasy_points", "sum"), gp=("fantasy_points", "size"))
        .to_dict("index")
    )
    # Current-season FP per player (pure, across all managers)
    current_fp_pure = (
        started.groupby("player_name")
        .agg(fp=("fantasy_points", "sum"), gp=("fantasy_points", "size"))
        .to_dict("index")
    )

    # Patch by-manager career tables
    for key in ["career_total_fp_by_manager_top10", "franchise_player_top10"]:
        entries = all_time.get(key, [])
        if not entries:
            continue
        updated = False
        for e in entries:
            hist_fp = e.get("historical_fp")
            if hist_fp is None:
                continue
            player = e.get("player_name", "")
            manager = e.get("manager", "")
            live = current_fp_by_mgr.get((player, manager), {"fp": 0.0, "gp": 0})
            e["total_fp"] = round(hist_fp + live["fp"], 1)
            e["gp"] = e.get("historical_gp", 0) + live["gp"]
            if e["gp"] > 0:
                e["fppg"] = round(e["total_fp"] / e["gp"], 2)
            updated = True
        if updated:
            entries.sort(key=lambda x: x.get("total_fp", 0), reverse=True)

    # Patch pure career tables (career_total_fp, career_fppg)
    for key in ["career_total_fp_top10", "career_fppg_top10"]:
        entries = all_time.get(key, [])
        if not entries:
            continue
        updated = False
        for e in entries:
            hist_fp = e.get("historical_fp")
            if hist_fp is None:
                continue
            player = e.get("player_name", "")
            live = current_fp_pure.get(player, {"fp": 0.0, "gp": 0})
            e["total_fp"] = round(hist_fp + live["fp"], 1)
            e["gp"] = e.get("historical_gp", 0) + live["gp"]
            if e["gp"] > 0:
                e["fppg"] = round(e["total_fp"] / e["gp"], 2)
            updated = True
        if updated:
            sort_key = "fppg" if "fppg" in key else "total_fp"
            entries.sort(key=lambda x: x.get(sort_key, 0), reverse=True)


def _merge_current_season_into_alltime(all_time: dict, data) -> None:
    """
    Merge current-season matchup results into all-time top-10 lists.

    all_matchups.json only covers historical seasons, so matchup-derived
    all-time tables (weekly scores, streaks, blowouts, etc.) are missing
    2025-26 data. This function reconstructs current-season matchups from
    PLAYERLOG + SCHEDULE and injects qualifying entries.
    """
    import json
    from collections import defaultdict

    cs = CURRENT_SEASON

    # Need PLAYERLOG and SCHEDULE
    if not hasattr(data, "playerlog") or data.playerlog is None or data.playerlog.empty:
        return
    if not hasattr(data, "schedule") or data.schedule is None:
        return

    pl = data.playerlog
    if "started" in pl.columns:
        started = pl[pl["started"] == True]
    else:
        started = pl
    started = started[started["fantasy_points"].notna() & (started["fantasy_points"] != 0)]
    if started.empty:
        return

    # Compute weekly team scores
    weekly = (
        started.groupby(["manager", "week"])
        .agg(score=("fantasy_points", "sum"), games=("fantasy_points", "size"))
        .reset_index()
    )
    weekly_dict = {}
    for _, row in weekly.iterrows():
        weekly_dict[(row["manager"], int(row["week"]))] = {
            "score": round(float(row["score"]), 2),
            "games": int(row["games"]),
        }

    # Get matchup pairings from SCHEDULE
    schedule = data.schedule
    if isinstance(schedule, dict):
        weeks = schedule.get("weeks", [])
    else:
        return

    # Reconstruct matchup results
    matchup_results = []
    for wk_data in weeks:
        wk = wk_data.get("week", 0)
        for m in wk_data.get("matchups", []):
            ma, mb = m.get("manager_a", ""), m.get("manager_b", "")
            sa_info = weekly_dict.get((ma, wk))
            sb_info = weekly_dict.get((mb, wk))
            if sa_info is None or sb_info is None:
                continue
            sa, sb = sa_info["score"], sb_info["score"]
            winner = ma if sa > sb else mb if sb > sa else None
            loser = mb if sa > sb else ma if sb > sa else None
            margin = round(abs(sa - sb), 2)
            matchup_results.append({
                "week": wk, "manager_a": ma, "manager_b": mb,
                "score_a": sa, "score_b": sb,
                "winner": winner, "loser": loser, "margin": margin,
            })

    if not matchup_results:
        return

    # --- Inject weekly team scores ---
    all_weekly = []
    for mr in matchup_results:
        for side, score_key in [("manager_a", "score_a"), ("manager_b", "score_b")]:
            mgr = mr[side]
            info = weekly_dict.get((mgr, mr["week"]), {})
            gc = info.get("games", 0)
            all_weekly.append({
                "score": mr[score_key], "manager": mgr, "season": cs,
                "week": mr["week"], "games": gc,
                "fppg": round(mr[score_key] / gc, 1) if gc > 0 else 0,
            })

    def _merge_top10(key, new_entries, sort_key, reverse=True):
        existing = all_time.get(key, [])
        # Remove any existing current-season entries to avoid dupes on re-run
        existing = [e for e in existing if e.get("season") != cs]
        combined = existing + new_entries
        combined.sort(key=lambda x: x.get(sort_key, 0), reverse=reverse)
        all_time[key] = combined[:10]

    _merge_top10("highest_weekly_score_top10", all_weekly, "score", True)
    _merge_top10("lowest_weekly_score_top10",
                 [s for s in all_weekly if s["score"] > 0], "score", False)

    # --- Inject blowouts and closest games ---
    cs_margins = [
        {"margin": mr["margin"], "winner": mr["winner"], "loser": mr["loser"],
         "season": cs, "week": mr["week"]}
        for mr in matchup_results if mr["winner"]
    ]
    _merge_top10("biggest_blowout_top10", cs_margins, "margin", True)
    _merge_top10("closest_game_top10", cs_margins, "margin", False)

    # --- Inject streaks ---
    sorted_mrs = sorted(matchup_results, key=lambda x: x["week"])
    cw, cl = defaultdict(int), defaultdict(int)
    all_win_streaks, all_loss_streaks = [], []
    for mr in sorted_mrs:
        w, lo = mr.get("winner"), mr.get("loser")
        if not w or not lo:
            continue
        cw[w] += 1
        if cl[w] > 0:
            all_loss_streaks.append({"length": cl[w], "manager": w, "season": cs})
        cl[w] = 0
        cl[lo] += 1
        if cw[lo] > 0:
            all_win_streaks.append({"length": cw[lo], "manager": lo, "season": cs})
        cw[lo] = 0
    # Flush active streaks
    for mgr, length in cw.items():
        if length > 0:
            all_win_streaks.append({"length": length, "manager": mgr, "season": cs})
    for mgr, length in cl.items():
        if length > 0:
            all_loss_streaks.append({"length": length, "manager": mgr, "season": cs})

    _merge_top10("longest_win_streak_top10", all_win_streaks, "length", True)
    _merge_top10("longest_loss_streak_top10", all_loss_streaks, "length", True)

    # --- Inject manager seasons ---
    ms = defaultdict(lambda: {"wins": 0, "losses": 0, "total_fp": 0.0, "weeks": 0})
    for mr in matchup_results:
        for side, score_key in [("manager_a", "score_a"), ("manager_b", "score_b")]:
            mgr = mr[side]
            ms[mgr]["total_fp"] += mr[score_key]
            ms[mgr]["weeks"] += 1
        if mr["winner"]:
            ms[mr["winner"]]["wins"] += 1
        if mr["loser"]:
            ms[mr["loser"]]["losses"] += 1
    cs_ms = [
        {"manager": mgr, "season": cs, "wins": d["wins"], "losses": d["losses"],
         "total_fp": round(d["total_fp"], 1), "weeks": d["weeks"],
         "fppg_per_week": round(d["total_fp"] / d["weeks"], 1) if d["weeks"] > 0 else 0}
        for mgr, d in ms.items()
    ]
    # Filter for "worst" leaderboards - require 18+ weeks to exclude incomplete seasons
    MIN_WEEKS_FOR_WORST = 18
    cs_ms_complete = [x for x in cs_ms if x["weeks"] >= MIN_WEEKS_FOR_WORST]
    
    # Total FP leaderboards
    _merge_top10("best_manager_season_top10", cs_ms, "total_fp", True)
    _merge_top10("worst_manager_season_top10", cs_ms_complete, "total_fp", False)
    # FP/week leaderboards
    _merge_top10("best_manager_season_fpweek_top10", cs_ms, "fppg_per_week", True)
    _merge_top10("worst_manager_season_fpweek_top10", cs_ms_complete, "fppg_per_week", False)

    # --- Inject H2H from current season ---
    # backfill_player_records.py stores historical-only H2H in "head_to_head_historical".
    # We compute totals as: historical baseline + current season from h2h_season.
    # This avoids double-counting on re-runs since we always start from the historical baseline.
    historical_h2h = all_time.get("head_to_head_historical", all_time.get("head_to_head", {}))
    existing_h2h = {k: v for k, v in historical_h2h.items()}  # Copy to avoid mutating
    
    # Add current season H2H from h2h_season in data.records (updated by weekly_stats)
    # FIXED: Use MANAGERS lookup instead of .capitalize() so multi-word names
    # like "Mary Jane" are not mangled to "Mary jane".
    _mgr_by_lower = {m.lower(): m for m in MANAGERS}
    h2h_season = data.records.get("h2h_season", {})
    for key, val in h2h_season.items():
        parts = key.split('_vs_')
        m1, m2 = parts[0], parts[1]
        for mgr_lower, wins in val.items():
            mgr = _mgr_by_lower.get(mgr_lower.lower(), mgr_lower)
            opponent_raw = m2 if mgr.lower() == m1.lower() else m1
            opponent = _mgr_by_lower.get(opponent_raw.lower(), opponent_raw)
            h2h_key = f'{mgr}_vs_{opponent}'
            existing_h2h[h2h_key] = existing_h2h.get(h2h_key, 0) + wins
    
    if "managers" not in existing_h2h:
        existing_h2h["managers"] = sorted(set(
            m["manager_a"] for m in matchup_results
        ) | set(m["manager_b"] for m in matchup_results))
    all_time["head_to_head"] = existing_h2h


def build_record_book(data) -> dict:
    """
    Build the expanded Record Book with 6 categories for tabbed display.

    Categories:
        1. Team Records (16): scores, blowouts, close games, streaks,
           team FPPG, daily scores, duos (day/week/season), hot/cold weeks
        2. Player Records (14): single game, season FPPG/total, weekly FP,
           outperformance, consistency, most games under 20, Mr. Monday Night,
           Mr. 4th Quarter, career total FP, career FPPG, career FP by mgr,
           longest player tenure
        3. Rookie Records (4): if ROOKIE_SEASONS.json exists
        4. Manager Milestones (with franchise player badge) + H2H +
           best/worst manager season + Most Total Injury Games
        5. Draft & Trades: draft class (total + FPPG), steal/bust (FPPG + TFP),
           trade acquisition (FP + FPPG), waiver pickup (FPPG + FP)

    Each record has a ranked entries list (up to 10) for both viz and LLM.

    Returns:
        {
            "team_records": [...],
            "player_records": [...],
            "rookie_records": [...],
            "manager_milestones": [...],
            "draft_records": [...],
            "manager_records": [...]
        }
    """
    records = data.records
    all_time = records.get("all_time", {})
    season = records.get("season_records", {})
    current_season = CURRENT_SEASON

    # Patch cumulative records with live current-season data
    _patch_cumulative_records(all_time, data)
    # Merge current-season matchup results into all-time top-10s
    _merge_current_season_into_alltime(all_time, data)

    result = {}

    # =========================================================================
    # 1. TEAM RECORDS
    # =========================================================================
    team_records = []

    # --- Highest Weekly Team Score ---
    team_records.append(_build_team_record(
        record_name="Highest Weekly Team Score",
        top10_key="highest_weekly_score_top10",
        single_key="highest_weekly_score",
        all_time=all_time,
        season_rec=season.get("highest_weekly_team_score", {}),
        value_field="score",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', '?')} games, {e.get('fppg', 0):.1f} FPPG" if e.get('games') else f"Wk {e.get('week', '?')}",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FP",
    ))

    # --- Lowest Weekly Team Score ---
    team_records.append(_build_team_record(
        record_name="Lowest Weekly Team Score",
        top10_key="lowest_weekly_score_top10",
        single_key="lowest_weekly_score",
        all_time=all_time,
        season_rec=season.get("lowest_weekly_team_score", {}),
        value_field="score",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', '?')} games, {e.get('fppg', 0):.1f} FPPG" if e.get('games') else f"Wk {e.get('week', '?')}",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FP",
    ))

    # --- Highest Team FPPG (Week) ---
    team_records.append(_build_team_record(
        record_name="Highest Team FPPG (Week)",
        top10_key="team_fppg_week_high_top10",
        single_key="team_fppg_week_high",
        all_time=all_time,
        season_rec={},
        value_field="avg_fppg",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', 0)} games, {e.get('total_fp', 0):,.1f} total FP",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FPPG",
        note="Avg FP per started game across a fantasy week",
    ))

    # --- Lowest Team FPPG (Week) ---
    team_records.append(_build_team_record(
        record_name="Lowest Team FPPG (Week)",
        top10_key="team_fppg_week_low_top10",
        single_key="team_fppg_week_low",
        all_time=all_time,
        season_rec={},
        value_field="avg_fppg",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', 0)} games, {e.get('total_fp', 0):,.1f} total FP",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FPPG",
        note="Avg FP per started game across a fantasy week",
    ))

    # --- Biggest Blowout ---
    team_records.append(_build_team_record(
        record_name="Biggest Blowout",
        top10_key="biggest_blowout_top10",
        single_key="biggest_blowout",
        all_time=all_time,
        season_rec=season.get("biggest_blowout", {}),
        value_field="margin",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}",
        holder_fn=lambda e: f"{e.get('winner', '')} over {e.get('loser', '')}",
    ))

    # --- Closest Game ---
    team_records.append(_build_team_record(
        record_name="Closest Game",
        top10_key="closest_game_top10",
        single_key="closest_game",
        all_time=all_time,
        season_rec=season.get("closest_matchup", {}),
        value_field="margin",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}",
        holder_fn=lambda e: f"{e.get('winner', '')} over {e.get('loser', '')}",
    ))

    # --- Longest Win Streak ---
    team_records.append(_build_streak_record(
        record_name="Longest Win Streak",
        top10_key="longest_win_streak_top10",
        per_manager_key="longest_win_streak",
        season_key="season_longest_win_streak",
        all_time=all_time,
        season_recs=season,
        current_season=current_season,
    ))

    # --- Longest Loss Streak ---
    team_records.append(_build_streak_record(
        record_name="Longest Loss Streak",
        top10_key="longest_loss_streak_top10",
        per_manager_key="longest_loss_streak",
        season_key="season_longest_loss_streak",
        all_time=all_time,
        season_recs=season,
        current_season=current_season,
    ))

    result["team_records"] = team_records

    # --- Best Daily Team FPPG (single day) ---
    team_records.append(_build_team_record(
        record_name="Best Daily Team FPPG",
        top10_key="best_daily_team_fppg_top10",
        single_key="best_daily_team_fppg",
        all_time=all_time,
        season_rec=season.get("best_collective_team_game", {}),
        value_field="avg_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('date', '?')}, {e.get('starters', 0)} starters, {e.get('total_fp', 0):,.1f} total",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FPPG",
        note="Avg FP per starter on a single day (min 5 starters)",
    ))

    # Worst Daily Team FPPG (single day)
    team_records.append(_build_team_record(
        record_name="Worst Daily Team FPPG",
        top10_key="worst_daily_team_fppg_top10",
        single_key="worst_daily_team_fppg",
        all_time=all_time,
        season_rec=season.get("worst_collective_team_game", {}),
        value_field="avg_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('date', '?')}, {e.get('starters', 0)} starters, {e.get('total_fp', 0):,.1f} total",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FPPG",
        note="Avg FP per starter on a single day (min 5 starters)",
    ))

    # --- Highest Daily Team Score (total FP on a single day) ---
    team_records.append(_build_team_record(
        record_name="Highest Daily Team Score",
        top10_key="highest_daily_team_score_top10",
        single_key="highest_daily_team_score",
        all_time=all_time,
        season_rec={},
        value_field="total_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('date', '?')}, {e.get('starters', 0)} starters",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FP",
        note="Total FP from all starters on a single day",
    ))

    # --- Best Combined Duo (Day) ---
    team_records.append(_build_team_record(
        record_name="Best Combined Duo (Day)",
        top10_key="best_duo_day_top10",
        single_key="best_duo_day",
        all_time=all_time,
        season_rec={},
        value_field="combined_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('player1', '?')} ({e.get('player1_fp', 0):.1f}) + {e.get('player2', '?')} ({e.get('player2_fp', 0):.1f}), {e.get('date', '?')}",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FP",
        note="Top 2 players combined FP on a single day",
    ))

    # Best Combined Duo (Week)
    team_records.append(_build_team_record(
        record_name="Best Combined Duo (Week)",
        top10_key="best_duo_week_top10",
        single_key="best_duo_week",
        all_time=all_time,
        season_rec=season.get("best_duo_output", {}),
        value_field="combined_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('player1', '?')} ({e.get('player1_fp', 0):.1f}) + {e.get('player2', '?')} ({e.get('player2_fp', 0):.1f}), Wk {e.get('week', '?')}",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FP",
    ))

    # Best Combined Duo (Season)
    team_records.append(_build_team_record(
        record_name="Best Combined Duo (Season)",
        top10_key="best_duo_season_top10",
        single_key="best_duo_season",
        all_time=all_time,
        season_rec={},
        value_field="combined_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('player1', '?')} ({e.get('player1_fp', 0):,.1f}) + {e.get('player2', '?')} ({e.get('player2_fp', 0):,.1f})",
        holder_fn=lambda e: e.get("manager", ""),
        unit="FP",
        note="Top 2 players combined season total FP",
    ))

    # Most Games 40+ FP (Week)
    team_records.append(_build_team_record(
        record_name="Most Games 40+ FP (Week)",
        top10_key="most_40plus_games_week_top10",
        single_key="most_40plus_games_week",
        all_time=all_time,
        season_rec=season.get("most_40plus_fp_week", {}),
        value_field="count",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('total_games', 0)} total games",
        holder_fn=lambda e: e.get("manager", ""),
        unit="games",
        note="Individual games scoring 40+ FP in a single fantasy week",
    ))

    # Most Games Sub-20 FP (Week)
    team_records.append(_build_team_record(
        record_name="Most Games Sub-20 FP (Week)",
        top10_key="most_sub20_games_week_top10",
        single_key="most_sub20_games_week",
        all_time=all_time,
        season_rec={},
        value_field="count",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('total_games', 0)} total games",
        holder_fn=lambda e: e.get("manager", ""),
        unit="games",
        note="Individual games scoring under 20 FP in a single fantasy week",
    ))

    # =========================================================================
    # 2. PLAYER RECORDS
    # =========================================================================
    player_records = []

    # --- Highest Single Game ---
    player_records.append(_build_player_record(
        record_name="Highest Single Game",
        top10_key="highest_single_game_top10",
        all_time=all_time,
        value_field="fantasy_points",
        current_season=current_season,
        unit="FP",
    ))

    # --- Lowest Single Game ---
    player_records.append(_build_player_record(
        record_name="Lowest Single Game",
        top10_key="lowest_single_game_top10",
        all_time=all_time,
        value_field="fantasy_points",
        current_season=current_season,
        unit="FP",
    ))

    # --- Best Player Season FPPG ---
    player_records.append(_build_player_record(
        record_name="Best Player Season",
        top10_key="best_season_fppg_top10",
        all_time=all_time,
        value_field="fppg",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('gp', 0)} GP, {e.get('total_fp', 0):,.1f} FP",
        min_gp=30,
        unit="FPPG",
        note="Min 30 GP. Fantasy points per game (started games only)",
    ))

    # --- Best Player Season Total FP ---
    player_records.append(_build_player_record(
        record_name="Best Player Season",
        top10_key="best_season_total_fp_top10",
        all_time=all_time,
        value_field="total_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('gp', 0)} GP, {e.get('fppg', 0):.2f} FPPG",
        unit="FP",
    ))

    # --- Most FP in Single Week ---
    player_records.append(_build_player_record(
        record_name="Most FP in Single Week",
        top10_key="most_fp_single_week_top10",
        all_time=all_time,
        value_field="weekly_fp",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', 0)} games",
        unit="FP",
    ))

    # --- Best FPPG in Single Week ---
    player_records.append(_build_player_record(
        record_name="Best FPPG in Single Week",
        top10_key="best_fppg_single_week_top10",
        all_time=all_time,
        value_field="weekly_fppg",
        current_season=current_season,
        detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', 0)} games, {e.get('weekly_fp', 0):,.1f} FP",
        unit="FPPG",
        note="Min 3 games. Avg FP per game in a single fantasy week",
    ))

    # --- Biggest Single-Game Outperformance ---
    player_records.append(_build_player_record(
        record_name="Biggest Outperformance",
        top10_key="biggest_outperformance_top10",
        all_time=all_time,
        value_field="delta",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('game_fp', 0):.1f} FP vs {e.get('season_avg', 0):.1f} avg, {e.get('date', '')}",
        unit="FP above avg",
        note="Single-game FP minus player's season FPPG",
    ))

    # --- Most Consistent Player (lowest std dev) ---
    player_records.append(_build_player_record(
        record_name="Most Consistent Player",
        top10_key="most_consistent_player_top10",
        all_time=all_time,
        value_field="std_dev",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('avg_fp', 0):.1f} avg, {e.get('gp', 0)} GP",
        min_gp=30,
        unit="sigma (std dev)",
        note="Min 30 GP. Lower = more consistent game-to-game scoring",
    ))

    # --- Most Games Over 40 FP ---
    player_records.append(_build_player_record(
        record_name="Most Games Over 40 FP (Season)",
        top10_key="most_games_over_40_top10",
        all_time=all_time,
        value_field="count",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('gp', 0)} GP, {100 * e.get('count', 0) / e.get('gp', 1):.0f}% rate",
        unit="games",
        note="Started games scoring 40+ FP in a season",
    ))

    # --- Most Games Under 20 FP ---
    player_records.append(_build_player_record(
        record_name="Most Games Under 20 FP (Season)",
        top10_key="most_games_under_20_top10",
        all_time=all_time,
        value_field="under_20_count",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('total_starts', 0)} starts, {e.get('pct', 0):.0f}% rate",
        unit="games",
        note="Started games scoring under 20 FP in a season (min 20 GP)",
    ))

    # --- Mr. Monday Night ---
    player_records.append(_build_player_record(
        record_name="Mr. Monday Night",
        top10_key="mr_monday_night_top10",
        all_time=all_time,
        value_field="avg_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('monday_games', 0)} Monday games",
        unit="FPPG",
        note="Avg FP in Monday games only (min 5 Monday starts)",
    ))

    # --- Mr. 4th Quarter (Sundays) ---
    player_records.append(_build_player_record(
        record_name="Mr. 4th Quarter",
        top10_key="mr_4th_quarter_top10",
        all_time=all_time,
        value_field="avg_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('sunday_games', 0)} Sunday games",
        unit="FPPG",
        note="Avg FP in Sunday games only (min 5 Sunday starts)",
    ))

    # --- Best Player Career Total FP ---
    player_records.append(_build_player_record(
        record_name="Best Player Career",
        top10_key="career_total_fp_top10",
        all_time=all_time,
        value_field="total_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('gp', 0)} GP, {e.get('seasons', 0)} seasons, {e.get('fppg', 0):.1f} FPPG",
        unit="FP",
        note="Cumulative career FP across all managers",
    ))

    # --- Best Player Career FPPG ---
    player_records.append(_build_player_record(
        record_name="Best Player Career",
        top10_key="career_fppg_top10",
        all_time=all_time,
        value_field="fppg",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('gp', 0)} GP, {e.get('total_fp', 0):,.1f} FP",
        unit="FPPG",
        note="Min 150 GP. Career fantasy points per game",
    ))

    # --- Best Player Career Total FP (By Manager) ---
    player_records.append(_build_player_record(
        record_name="Best Player Career (By Manager)",
        top10_key="career_total_fp_by_manager_top10",
        all_time=all_time,
        value_field="total_fp",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('gp', 0)} GP, {e.get('seasons', 0)} seasons, {e.get('fppg', 0):.1f} FPPG",
        unit="FP",
        note="Cumulative FP a player produced for a specific manager",
    ))

    # --- Longest Player Tenure ---
    player_records.append(_build_player_record(
        record_name="Longest Player Tenure",
        top10_key="longest_player_tenure_top10",
        all_time=all_time,
        value_field="consecutive_seasons",
        current_season=current_season,
        detail_fn=lambda e: f"{e.get('start_season', '?')} to {e.get('end_season', '?')}" + (" (active)" if e.get('active') else ""),
        unit="seasons",
        note="Most consecutive seasons a player stayed with the same manager",
    ))

    result["player_records"] = player_records

    # =========================================================================
    # 3. ROOKIE RECORDS (only if data exists)
    # =========================================================================
    # Check if any rookie top-10 keys exist in all_time
    has_rookie_data = any(
        k.startswith("best_rookie_") and k.endswith("_top10")
        for k in all_time
    )
    # Also check season_records for rookie data
    has_rookie_season = any(
        k.startswith("best_rookie_") for k in season
    )

    if has_rookie_data or has_rookie_season:
        rookie_records = []

        rookie_records.append(_build_player_record(
            record_name="Highest Rookie Single Game",
            top10_key="best_rookie_single_game_top10",
            all_time=all_time,
            value_field="fantasy_points",
            current_season=current_season,
            unit="FP",
        ))

        rookie_records.append(_build_player_record(
            record_name="Best Rookie Season",
            top10_key="best_rookie_season_fppg_top10",
            all_time=all_time,
            value_field="fppg",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('gp', 0)} GP, {e.get('total_fp', 0):,.1f} FP",
            min_gp=30,
            unit="FPPG",
            note="Min 30 GP. Fantasy points per game in NBA rookie season",
        ))

        rookie_records.append(_build_player_record(
            record_name="Best Rookie Season",
            top10_key="best_rookie_season_total_fp_top10",
            all_time=all_time,
            value_field="total_fp",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('gp', 0)} GP, {e.get('fppg', 0):.2f} FPPG",
            unit="FP",
        ))

        rookie_records.append(_build_player_record(
            record_name="Most Rookie FP in Single Week",
            top10_key="best_rookie_fantasy_week_top10",
            all_time=all_time,
            value_field="weekly_fp",
            current_season=current_season,
            detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', 0)} games",
            unit="FP",
        ))

        rookie_records.append(_build_player_record(
            record_name="Best Rookie FPPG in Single Week",
            top10_key="best_rookie_fppg_week_top10",
            all_time=all_time,
            value_field="weekly_fppg",
            current_season=current_season,
            detail_fn=lambda e: f"Wk {e.get('week', '?')}, {e.get('games', 0)} games, {e.get('weekly_fp', 0):,.1f} FP",
            unit="FPPG",
            note="Min 3 games. Avg FP per game in a single fantasy week",
        ))

        result["rookie_records"] = rookie_records

    # =========================================================================
    # 4. MANAGER MILESTONES
    # =========================================================================
    careers = all_time.get("manager_careers", {})
    milestones = []

    # Get titles from LEAGUEHISTORY (primary) or manager_careers (fallback)
    titles_map = {}
    if hasattr(data, "leaguehistory") and data.leaguehistory is not None:
        lh = data.leaguehistory
        if not lh.empty and "titles_won" in lh.columns:
            for _, row in lh.iterrows():
                mgr = row.get("manager_name", "")
                titles_map[mgr] = int(row.get("titles_won", 0))

    # Fallback: titles may be stored in manager_careers by backfill
    if not titles_map:
        for mgr, stats in careers.items():
            if "titles" in stats:
                titles_map[mgr] = stats["titles"]

    for mgr, stats in careers.items():
        wins = stats.get("total_wins", 0)
        losses = stats.get("total_losses", 0)
        milestones.append({
            "manager": mgr,
            "career_wins": wins,
            "career_losses": losses,
            "win_pct": stats.get("win_pct", 0),
            "career_points": round(stats.get("total_points_scored", 0), 2),
            "titles": titles_map.get(mgr, 0),
            # Playoff championships (won the 2-week playoff bracket) -- tracked
            # separately from regular-season titles. Historical values may be
            # placeholder 0s (see all_time._notes.playoff_titles_backfill).
            "playoff_titles": stats.get("playoff_titles", 0),
            "seasons": (wins + losses) // 21 if (wins + losses) > 0 else 0,
        })

    milestones.sort(key=lambda x: x["career_wins"], reverse=True)
    result["manager_milestones"] = milestones

    # =========================================================================
    # 5. DRAFT & TRADES RECORDS
    # =========================================================================
    draft_records = []
    for key, name, val_field, dfn, unit, note in [
        ("best_draft_class_top10", "Best Draft Class", "total_fp",
         lambda e: f"{e.get('player_count', 0)} picks, {e.get('total_gp', 0)} GP",
         "FP", "Total FP from top 7 draft picks (keepers excluded). *2021-22 onward only"),
        ("best_draft_class_fppg_top10", "Best Draft Class", "avg_fppg",
         lambda e: f"{e.get('player_count', 0)} qualifying picks, {e.get('total_gp', 0)} GP",
         "FPPG", "Avg FPPG across top 7 draft picks (min 20 GP, keepers excluded). *2021-22 onward only"),
        ("biggest_draft_steal_top10", "Biggest Draft Steal", "delta",
         lambda e: f"P{e.get('pick_number', '?')} (R{e.get('round', '?')}): {e.get('fppg', 0):.1f} actual vs {e.get('expected_fppg', 0):.1f} expected",
         "FPPG above expected", "FPPG minus expected FPPG for draft pick (min 20 GP, keepers excluded). *2021-22 onward only"),
        ("biggest_draft_bust_top10", "Biggest Draft Bust", "delta",
         lambda e: f"P{e.get('pick_number', '?')} (R{e.get('round', '?')}): {e.get('fppg', 0):.1f} actual vs {e.get('expected_fppg', 0):.1f} expected",
         "FPPG below expected", "FPPG minus expected FPPG for draft pick (min 20 GP, keepers excluded). *2021-22 onward only"),
        ("biggest_draft_steal_totalfp_top10", "Biggest Draft Steal", "delta",
         lambda e: f"P{e.get('pick_number', '?')} (R{e.get('round', '?')}): {e.get('total_fp', 0):,.1f} actual vs {e.get('expected_total_fp', 0):,.1f} expected",
         "FP above expected", "Total FP minus expected Total FP for draft pick (min 20 GP, keepers excluded). *2021-22 onward only"),
        ("biggest_draft_bust_totalfp_top10", "Biggest Draft Bust", "delta",
         lambda e: f"P{e.get('pick_number', '?')} (R{e.get('round', '?')}): {e.get('total_fp', 0):,.1f} actual vs {e.get('expected_total_fp', 0):,.1f} expected",
         "FP below expected", "Total FP minus expected Total FP for draft pick (min 20 GP, keepers excluded). *2021-22 onward only"),
        ("trade_winner_top10", "Best Trade Acquisition", "post_trade_fp",
         lambda e: f"from {e.get('from_manager', '?')}, {e.get('gp', 0)} GP post-trade",
         "FP", "Total FP produced after trade for acquiring manager within that season"),
        ("trade_winner_fppg_top10", "Best Trade Acquisition", "fppg",
         lambda e: f"from {e.get('from_manager', '?')}, {e.get('gp', 0)} GP, {e.get('post_trade_fp', 0):,.1f} FP post-trade",
         "FPPG", "FPPG after trade for acquiring manager (min 25 GP post-trade)"),
        ("best_waiver_pickup_top10", "Best Waiver Pickup", "fppg",
         lambda e: f"{e.get('gp', 0)} GP, {e.get('total_fp', 0):,.1f} FP",
         "FPPG", "FPPG after waiver acquisition (min 10 GP). *Waiver data available from 2025-26 onward only"),
        ("best_waiver_pickup_totalfp_top10", "Best Waiver Pickup", "total_fp",
         lambda e: f"{e.get('gp', 0)} GP, {e.get('fppg', 0):.1f} FPPG",
         "FP", "Total FP after waiver acquisition (min 10 GP). *Waiver data available from 2025-26 onward only"),
    ]:
        if all_time.get(key):
            draft_records.append(_build_player_record(
                record_name=name,
                top10_key=key,
                all_time=all_time,
                value_field=val_field,
                current_season=current_season,
                detail_fn=dfn,
                unit=unit,
                note=note,
            ))

    result["draft_records"] = draft_records

    # =========================================================================
    # 6. MANAGER RECORDS
    # =========================================================================
    manager_records = []

    # Add franchise player badge to milestones (enriched with detail)
    badges = all_time.get("franchise_badges", {})
    by_mgr_top10 = all_time.get("career_total_fp_by_manager_top10", [])
    # Build lookup: (player, manager) -> detail dict
    franchise_detail = {}
    for e in by_mgr_top10:
        key = (e.get("player_name", ""), e.get("manager", ""))
        franchise_detail[key] = e

    for m in milestones:
        mgr = m["manager"]
        badge = badges.get(mgr, {})
        if not badge:
            stats = careers.get(mgr, {})
            badge = {"player": stats.get("franchise_player", ""), "total_fp": stats.get("franchise_player_fp", 0)}
        fp_name = badge.get("player", "")
        m["franchise_player"] = fp_name
        m["franchise_player_fp"] = badge.get("total_fp", 0)
        # Enrich with detail from career_total_fp_by_manager_top10
        detail = franchise_detail.get((fp_name, mgr), {})
        m["franchise_gp"] = detail.get("gp", 0)
        m["franchise_seasons"] = detail.get("seasons", 0)
        m["franchise_fppg"] = round(detail.get("fppg", 0), 1)

    # Head-to-Head matrix
    h2h = all_time.get("head_to_head", {})
    if h2h and h2h.get("managers"):
        result["head_to_head"] = h2h

    # Best Manager Season (by Total FP)
    if all_time.get("best_manager_season_top10"):
        manager_records.append(_build_team_record(
            record_name="Best Manager Season",
            top10_key="best_manager_season_top10",
            single_key="best_manager_season",
            all_time=all_time,
            season_rec={},
            value_field="total_fp",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('wins', 0)}-{e.get('losses', 0)}, {e.get('fppg_per_week', 0):,.1f} FP/week, {e.get('weeks', 0)} weeks",
            holder_fn=lambda e: e.get("manager", ""),
            unit="Total FP",
            note="Total fantasy points scored in a season",
        ))

    # Worst Manager Season (by Total FP)
    if all_time.get("worst_manager_season_top10"):
        manager_records.append(_build_team_record(
            record_name="Worst Manager Season",
            top10_key="worst_manager_season_top10",
            single_key="worst_manager_season",
            all_time=all_time,
            season_rec={},
            value_field="total_fp",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('wins', 0)}-{e.get('losses', 0)}, {e.get('fppg_per_week', 0):,.1f} FP/week, {e.get('weeks', 0)} weeks",
            holder_fn=lambda e: e.get("manager", ""),
            unit="Total FP",
            note="Total fantasy points scored in a season",
            min_weeks=18,
        ))

    # Best Manager Season (by FP/week)
    if all_time.get("best_manager_season_fpweek_top10"):
        manager_records.append(_build_team_record(
            record_name="Best Manager Season",
            top10_key="best_manager_season_fpweek_top10",
            single_key="best_manager_season_fpweek",
            all_time=all_time,
            season_rec={},
            value_field="fppg_per_week",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('wins', 0)}-{e.get('losses', 0)}, {e.get('total_fp', 0):,.0f} total FP, {e.get('weeks', 0)} weeks",
            holder_fn=lambda e: e.get("manager", ""),
            unit="FP/week",
            note="Average fantasy points per matchup week in a season",
        ))

    # Worst Manager Season (by FP/week)
    if all_time.get("worst_manager_season_fpweek_top10"):
        manager_records.append(_build_team_record(
            record_name="Worst Manager Season",
            top10_key="worst_manager_season_fpweek_top10",
            single_key="worst_manager_season_fpweek",
            all_time=all_time,
            season_rec={},
            value_field="fppg_per_week",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('wins', 0)}-{e.get('losses', 0)}, {e.get('total_fp', 0):,.0f} total FP, {e.get('weeks', 0)} weeks",
            holder_fn=lambda e: e.get("manager", ""),
            unit="FP/week",
            note="Average fantasy points per matchup week in a season",
            min_weeks=18,
        ))

    # Best Manager Season (by FP/game)
    if all_time.get("best_manager_season_fppg_top10"):
        manager_records.append(_build_team_record(
            record_name="Best Manager Season",
            top10_key="best_manager_season_fppg_top10",
            single_key="best_manager_season_fppg",
            all_time=all_time,
            season_rec={},
            value_field="fppg",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('wins', 0)}-{e.get('losses', 0)}, {e.get('total_fp', 0):,.0f} total FP, {e.get('games', 0)} games",
            holder_fn=lambda e: e.get("manager", ""),
            unit="FP/game",
            note="Average fantasy points per game started in a season",
        ))

    # Worst Manager Season (by FP/game)
    if all_time.get("worst_manager_season_fppg_top10"):
        manager_records.append(_build_team_record(
            record_name="Worst Manager Season",
            top10_key="worst_manager_season_fppg_top10",
            single_key="worst_manager_season_fppg",
            all_time=all_time,
            season_rec={},
            value_field="fppg",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('wins', 0)}-{e.get('losses', 0)}, {e.get('total_fp', 0):,.0f} total FP, {e.get('games', 0)} games",
            holder_fn=lambda e: e.get("manager", ""),
            unit="FP/game",
            note="Average fantasy points per game started in a season",
            min_weeks=18,
        ))

    # Most Total Injury Games (Season) -- current season onward only
    if all_time.get("most_total_injury_games_top10"):
        manager_records.append(_build_team_record(
            record_name="Most Total Injury Games (Season)",
            top10_key="most_total_injury_games_top10",
            single_key="most_total_injury_games",
            all_time=all_time,
            season_rec={},
            value_field="total_injury_games",
            current_season=current_season,
            detail_fn=lambda e: f"{e.get('non_il_injuries', 0)} in starter slots + {e.get('il_games', 0)} IL, {e.get('burden_pct', 0):.1f}% burden",
            holder_fn=lambda e: e.get("manager", ""),
            unit="games",
            note="Games lost to injury (0 FP w/ opponent) + IL slot games. *2025-26 onward only",
        ))

    result["manager_records"] = manager_records

    return result


# =========================================================================
# HELPER FUNCTIONS (add these just above build_record_book or after it)
# =========================================================================


def _build_team_record(
    record_name: str,
    top10_key: str,
    single_key: str,
    all_time: dict,
    season_rec: dict,
    value_field: str,
    current_season: str,
    detail_fn=None,
    holder_fn=None,
    unit: str = "",
    note: str = "",
    min_weeks: int = 0,
) -> dict:
    """Build a team record entry with top-10 leaderboard."""
    if detail_fn is None:
        detail_fn = lambda e: f"Wk {e.get('week', '?')}"
    if holder_fn is None:
        holder_fn = lambda e: e.get("manager", "")

    top10_raw = all_time.get(top10_key, [])
    
    # Filter by minimum weeks if specified (for "Worst" leaderboards)
    if min_weeks > 0:
        top10_raw = [e for e in top10_raw if e.get("weeks", 0) >= min_weeks][:10]

    entries = []
    for i, e in enumerate(top10_raw):
        is_current = e.get("season", "") == current_season
        entries.append({
            "rank": i + 1,
            "value": round(e.get(value_field, 0), 2),
            "holder": holder_fn(e),
            "season": e.get("season", ""),
            "detail": detail_fn(e),
            "is_current_season": is_current,
        })

    # Determine if current season holds the #1 spot
    is_new_record = False
    if entries and entries[0].get("is_current_season", False):
        is_new_record = True

    result = {
        "record": record_name,
        "entries": entries,
        "is_new_record": is_new_record,
    }
    if unit:
        result["unit"] = unit
    if note:
        result["note"] = note

    return result


def _build_streak_record(
    record_name: str,
    top10_key: str,
    per_manager_key: str,
    season_key: str,
    all_time: dict,
    season_recs: dict,
    current_season: str,
) -> dict:
    """Build a streak record entry from top-10 or per-manager data."""
    top10_raw = all_time.get(top10_key, [])

    # If top-10 exists, use it
    if top10_raw:
        entries = []
        for i, e in enumerate(top10_raw):
            entries.append({
                "rank": i + 1,
                "value": e.get("length", 0),
                "holder": e.get("manager", ""),
                "season": e.get("season", ""),
                "detail": "",
                "is_current_season": e.get("season", "") == current_season,
            })
    else:
        # Fall back to per-manager dict (legacy format)
        streak_dict = all_time.get(per_manager_key, {})
        flat = []
        for mgr, info in streak_dict.items():
            if isinstance(info, dict):
                flat.append({
                    "length": info.get("length", 0),
                    "manager": mgr,
                    "season": info.get("season", ""),
                })
        flat.sort(key=lambda x: x["length"], reverse=True)
        entries = []
        for i, e in enumerate(flat[:10]):
            entries.append({
                "rank": i + 1,
                "value": e["length"],
                "holder": e["manager"],
                "season": e["season"],
                "detail": "",
                "is_current_season": e["season"] == current_season,
            })

    is_new_record = bool(entries and entries[0].get("is_current_season", False))

    return {
        "record": record_name,
        "entries": entries,
        "is_new_record": is_new_record,
    }


def _build_player_record(
    record_name: str,
    top10_key: str,
    all_time: dict,
    value_field: str,
    current_season: str,
    detail_fn=None,
    min_gp: int = 0,
    unit: str = "",
    note: str = "",
) -> dict:
    """Build a player/rookie record entry with top-10 leaderboard."""
    if detail_fn is None:
        detail_fn = lambda e: f"Wk {e.get('week', '?')}"

    top10_raw = all_time.get(top10_key, [])

    entries = []
    for i, e in enumerate(top10_raw):
        is_current = e.get("season", "") == current_season
        entries.append({
            "rank": i + 1,
            "value": round(e.get(value_field, 0), 2),
            "player": e.get("player_name", "") or e.get("manager", ""),
            "manager": e.get("manager", ""),
            "season": e.get("season", ""),
            "detail": detail_fn(e),
            "is_current_season": is_current,
        })

    is_new_record = bool(entries and entries[0].get("is_current_season", False))

    record_dict = {
        "record": record_name,
        "entries": entries,
        "is_new_record": is_new_record,
    }
    if min_gp:
        record_dict["min_gp"] = min_gp
    if unit:
        record_dict["unit"] = unit
    if note:
        record_dict["note"] = note

    return record_dict



# =============================================================================
# KEEPER WATCH TABLE
# =============================================================================


def build_keeper_watch(data: FantasyData, week: int) -> dict:
    """
    Build keeper watch table using keepability v2 multi-year scoring.

    V2 scores players on a 0-100 scale using:
      - Weighted 3-Year FPPG (50%)
      - Peak FPPG career ceiling (20%)
      - 3-Year Availability (15%)
      - Consistency / low volatility (15%)
      - Age curve multiplier (0.95-1.05)
      - Positional scarcity multiplier (1.00-1.03)

    Requires HISTORICAL_PLAYERLOG.json in data.historical_playerlog.
    Falls back to v1 (single-season) if historical data unavailable.

    Returns:
        {
            "players": [
                {
                    "player_name": str,
                    "manager": str,
                    "keeper_tier": str,
                    "keepability_score": float (0-100),
                    "components": {...},
                    "age": int,
                    "pos_group": str,
                    "season_gp": int,
                    "season_fppg": float,
                    "proj_fppg": float,
                    ...
                },
                ...
            ],
        }
    """
    if not data.historical_playerlog:
        print("  WARNING: HISTORICAL_PLAYERLOG not loaded, using v1 keepability")
        return _build_keeper_watch_v1(data, week)

    print(f"  Building keepability v2 scores for {len(data.get_current_rosters())} teams...")
    report = build_keepability_report(
        data=data,
        historical_playerlog=data.historical_playerlog,
        week=week,
        current_season=CURRENT_SEASON,
    )
    print(f"  ✓ Keepability v2 complete ({len(report['players'])} players scored)")
    return report


def _build_keeper_watch_v1(data: FantasyData, week: int) -> dict:
    """
    LEGACY FALLBACK: Single-season keepability scoring.

    Only used when HISTORICAL_PLAYERLOG.json is unavailable.
    Uses: blended_fppg * sqrt(availability) * age_factor

    Tiers (in evaluation order):
        Stash       -- OFS player with 0 GP but high projected value
        Lock        -- score >= 40
        Sell High   -- age >= 33, score >= 28: producing but aging out
        Strong Hold -- score >= 30
        Sell High   -- age >= 30, score 20-30: veteran with trade window
        On the Bubble -- score >= 24: borderline keeper
        Dynasty Stash -- age <= 23, proj FPPG >= 28
        Drop        -- below all thresholds
    """
    import pandas as pd

    # V1 threshold constants (kept inline since they're only used here)
    V1_LOCK = 40
    V1_STRONG = 35
    V1_SELL_HIGH_AGE = 33
    V1_SELL_HIGH_VET_AGE = 30
    V1_SELL_HIGH_MIN = 28
    V1_SELL_HIGH_VET_MIN = 25
    V1_BUBBLE = 32
    V1_STASH_PROJ_MIN = 35
    V1_DYNASTY_MAX_AGE = 23
    V1_DYNASTY_PROJ_MIN = 28

    def v1_score(season_fppg, proj_fppg, age, season_gp, week):
        """V1 keepability: blended_fppg * sqrt(availability) * age_factor."""
        if not age:
            age = 27
        proj = proj_fppg or 0.0
        actual = season_fppg or 0.0
        if season_gp >= 10:
            blended = 0.7 * actual + 0.3 * proj
        elif season_gp >= 5:
            w = season_gp / 10.0
            blended = w * actual + (1 - w) * proj
        else:
            blended = proj

        expected_games = int(week * 3.3)
        if expected_games > 0 and season_gp > 0:
            availability = min(1.0, season_gp / expected_games)
            avail_factor = math.sqrt(availability)
        else:
            avail_factor = 1.0

        if age <= 23:
            age_factor = 1.15
        elif age <= 29:
            age_factor = 1.0
        elif age <= 32:
            age_factor = 0.95
        else:
            age_factor = 0.85

        return blended * avail_factor * age_factor

    def v1_tier(season_fppg, proj_fppg, age, season_gp, week, is_ofs):
        """V1 tier assignment."""
        if not age:
            age = 27
        if is_ofs and season_gp == 0:
            return "Stash" if (proj_fppg or 0) >= V1_STASH_PROJ_MIN else "On the Bubble"

        score = v1_score(season_fppg, proj_fppg, age, season_gp, week)
        if score >= V1_LOCK:
            return "Lock"
        if age >= V1_SELL_HIGH_AGE and score >= V1_SELL_HIGH_MIN:
            return "Sell High"
        if score >= V1_STRONG:
            return "Strong Hold"
        if age >= V1_SELL_HIGH_VET_AGE and score >= V1_SELL_HIGH_VET_MIN:
            return "Sell High"
        if score >= V1_BUBBLE:
            return "On the Bubble"
        if age <= V1_DYNASTY_MAX_AGE and (proj_fppg or 0) >= V1_DYNASTY_PROJ_MIN:
            return "Dynasty Stash"
        return "Drop"

    rosters = data.get_current_rosters()
    playerlist = data.playerlist

    pl_lookup = {}
    for _, row in playerlist.iterrows():
        pname = row["player_name"]
        pl_lookup[pname] = {
            "age": int(row["age"]) if pd.notna(row.get("age")) else None,
            "proj_fppg": round(float(row["projectedFPPG"]), 2) if pd.notna(row.get("projectedFPPG")) else None,
            "positions": row.get("player_position(s)", ""),
        }

    plog = data.playerlog
    # Player-level stats include BOTH starter and bench slot games.
    played_mask = (
        (plog["week"] <= week)
        & (plog["fantasy_points"].notna())
        & (plog["fantasy_points"] != 0.0)
        & (plog["nba_opponent"].notna())
    )
    played = plog[played_mask]

    player_season = {}
    for pname, grp in played.groupby("player_name"):
        gp = len(grp)
        total_fp = grp["fantasy_points"].sum()
        fppg = total_fp / gp if gp > 0 else 0.0
        player_season[pname] = {
            "gp": gp,
            "total_fp": round(total_fp, 1),
            "fppg": round(fppg, 2),
        }

    ofs_players = set()
    injured_players = set()
    for inj in data.injury_overrides.get("players", []):
        if inj.get("notes", "").lower().startswith("out for season"):
            ofs_players.add(inj["player_name"])
        out_weeks = inj.get("out_weeks", [])
        if week in out_weeks or (out_weeks and max(out_weeks) >= week):
            injured_players.add(inj["player_name"])

    players = []
    for mgr, roster in rosters.items():
        for pname in roster:
            pl_info = pl_lookup.get(pname, {})
            season = player_season.get(pname, {})
            age = pl_info.get("age")
            proj_fppg = pl_info.get("proj_fppg")
            positions = pl_info.get("positions", "")
            season_fppg = season.get("fppg", 0.0)
            season_gp = season.get("gp", 0)
            is_ofs = pname in ofs_players
            is_injured = pname in injured_players

            pos_group = classify_position_group(positions)

            tier = v1_tier(season_fppg, proj_fppg, age, season_gp, week, is_ofs)

            # Rescue injured players from Drop
            if tier == "Drop" and is_injured and not is_ofs:
                if age and age >= V1_SELL_HIGH_VET_AGE:
                    tier = "Sell High"
                else:
                    tier = "On the Bubble"

            if is_ofs and season_gp == 0:
                keep_score = (proj_fppg or 0.0)
            else:
                keep_score = v1_score(season_fppg, proj_fppg, age, season_gp, week)

            players.append({
                "player_name": pname,
                "manager": mgr,
                "age": age,
                "pos_group": pos_group,
                "season_gp": season_gp,
                "season_fppg": season_fppg,
                "season_total_fp": season.get("total_fp", 0.0),
                "proj_fppg": proj_fppg or 0.0,
                "keeper_tier": tier,
                "keepability_score": round(keep_score, 1),
                "out_for_season": is_ofs,
                "injured": is_injured,
            })

    players.sort(key=lambda x: -x["keepability_score"])
    return {"players": players}


# =============================================================================
# DRAFT VALUE TRACKER
# =============================================================================

# Value label thresholds (deviation from expected mid FPPG)
DRAFT_STEAL_THRESHOLD = 4.0    # actual >= mid + 4 -> Steal
DRAFT_GOOD_THRESHOLD = 1.0     # actual >= mid + 1 -> Good Value
DRAFT_FAIR_LOW = -3.0          # actual >= mid - 3 -> Fair
                                # actual < mid - 3  -> Bust


def build_draft_value_tracker(data: FantasyData, week: int) -> dict:
    """
    Build draft value tracker comparing drafted players' actual production
    to their expected value based on draft position.

    Reads:
        - config/DRAFT_PICKS_CURRENT.json for who was picked where
        - config/DRAFT_PICK_VALUES.json for expected FPPG per round
        - PLAYERLOG for actual season stats

    Only grades drafted players (rounds 1-7). Keepers (rounds 8-13) are
    listed separately without a value label.

    Returns:
        {
            "drafted": [
                {
                    "player_name": "Cooper Flagg",
                    "manager": "Garrett",
                    "round": 1,
                    "pick": 1,
                    "expected_fppg": 41.0,
                    "actual_fppg": 38.50,
                    "total_fp": 1540.0,
                    "gp": 40,
                    "value": "Fair",
                    "delta": -2.5,
                    "still_rostered": True,
                    "status": "rostered",   # rostered|traded|claimed|dropped
                    "out_for_season": False,
                },
                ...
            ],
            "keepers": [ ... same fields minus value/delta ... ]
        }
    """
    import pandas as pd

    base = data.base_path

    # Load draft picks
    draft_file = base / "config" / "DRAFT_PICKS_CURRENT.json"
    if not draft_file.exists():
        return {"drafted": [], "keepers": []}
    with open(draft_file) as f:
        draft_data = json.load(f)
    picks = draft_data.get("picks", [])

    # Load pick values
    values_file = base / "config" / "DRAFT_PICK_VALUES.json"
    if not values_file.exists():
        return {"drafted": [], "keepers": []}
    with open(values_file) as f:
        values_data = json.load(f)
    pick_values = values_data.get("pick_values", {})

    # Build season stats from PLAYERLOG (all games where player scored)
    plog = data.playerlog
    played_mask = (
        (plog["week"] <= week)
        & (plog["fantasy_points"].notna())
        & (plog["fantasy_points"] != 0.0)
        & (plog["nba_opponent"].notna())
    )
    played = plog[played_mask]

    player_season = {}
    for pname, grp in played.groupby("player_name"):
        gp = len(grp)
        total_fp = grp["fantasy_points"].sum()
        player_season[pname] = {
            "gp": gp,
            "total_fp": round(total_fp, 1),
            "fppg": round(total_fp / gp, 2) if gp > 0 else 0.0,
        }

    # Get current rosters for status check
    rosters = data.get_current_rosters()
    current_mgr_lookup = {}  # player -> current manager (or "FA")
    for mgr, players in rosters.items():
        for p in players:
            current_mgr_lookup[p] = mgr

    # Load waiver adds to distinguish trades from drop-and-claims
    waiver_adds_set = set()
    waiver_dir = base / "data"
    import glob as _glob
    import re as _re
    # FIXED: Match manager name by MANAGERS lookup so multi-word names
    # (e.g., "Mary Jane") are not truncated to the first word by \w+.
    _date_prefix = _re.compile(r'- \[\d{4}-\d{2}-\d{2}\]\s+(.+)$')
    for wf in sorted(_glob.glob(str(waiver_dir / "waivers_week*.txt"))):
        for line in open(wf):
            prefix_match = _date_prefix.match(line.strip())
            if not prefix_match:
                continue
            rest = prefix_match.group(1)
            for _mgr in MANAGERS:
                token = f"{_mgr}: "
                if rest.startswith(token):
                    player = rest[len(token):].strip()
                    waiver_adds_set.add((_mgr, player))
                    break

    # Load OFS players from INJURY_OVERRIDES
    ofs_players = set()
    overrides_path = base / "config" / "INJURY_OVERRIDES.json"
    if overrides_path.exists():
        with open(overrides_path) as f:
            overrides = json.load(f)
        for inj in overrides.get("players", []):
            if inj.get("notes", "").lower().startswith("out for season"):
                ofs_players.add(inj["player_name"])

    drafted = []

    for pick in picks:
        pname = pick.get("player_name", "Unknown")
        manager = pick.get("manager", "Unknown")
        round_num = pick.get("round", 0)
        pick_num = pick.get("pick_number", 0)

        # Skip keepers (R8-13) -- only grade drafted players
        if round_num >= 8:
            continue

        season = player_season.get(pname, {})
        actual_fppg = season.get("fppg", 0.0)
        total_fp = season.get("total_fp", 0.0)
        gp = season.get("gp", 0)

        # Determine player status: rostered / traded / claimed / dropped
        now_on = current_mgr_lookup.get(pname, "FA")
        if now_on == "FA":
            status = "dropped"
        elif now_on != manager:
            # Changed teams -- check if via waiver claim or trade
            if (now_on, pname) in waiver_adds_set:
                status = "claimed"
            else:
                status = "traded"
        else:
            status = "rostered"

        is_ofs = pname in ofs_players

        # Grade against expected value (pick-level granularity)
        pv = pick_values.get(str(pick_num), {})
        expected = pv.get("expected_projFPPG", {})
        expected_mid = expected.get("mid", 35.0)

        delta = round(actual_fppg - expected_mid, 2)
        value = _compute_draft_value(delta, gp)

        drafted.append({
            "player_name": pname,
            "manager": manager,
            "round": round_num,
            "pick": pick_num,
            "expected_fppg": expected_mid,
            "actual_fppg": actual_fppg,
            "total_fp": total_fp,
            "gp": gp,
            "value": value,
            "delta": delta,
            "still_rostered": status == "rostered",
            "status": status,
            "out_for_season": is_ofs,
        })

    # Sort drafted by delta descending (biggest steals first)
    drafted.sort(key=lambda x: -x["delta"])

    return {"drafted": drafted}


def _compute_draft_value(delta: float, gp: int) -> str:
    """
    Assign a value label based on actual vs expected FPPG delta.

    Players with fewer than 10 games get 'Too Early' instead of
    Steal/Bust since the sample is too small.
    """
    if gp < 10:
        return "Too Early"
    if delta >= DRAFT_STEAL_THRESHOLD:
        return "Steal"
    if delta >= DRAFT_GOOD_THRESHOLD:
        return "Good Value"
    if delta >= DRAFT_FAIR_LOW:
        return "Fair"
    return "Bust"


# =============================================================================
# MAIN REPORT BUILDER
# =============================================================================

def build_stats_report(
    data: FantasyData,
    week: int,
    waiver_adds: dict[str, list[str]] = None,
    run_simulations: bool = True,
    num_title_sims: int = 10000,
    num_betting_sims: int = 5000,
    seed: int = None,
    injury_statuses: dict[str, str] = None,
    freshness_tracker: "FreshnessTracker" = None,
) -> dict:
    """
    Build complete stats report for a week.
    
    Args:
        data: FantasyData container
        week: Week number to report on
        waiver_adds: Dict mapping manager -> list of waiver add player names
        run_simulations: Whether to run Monte Carlo simulations
        num_title_sims: Number of title odds simulations
        num_betting_sims: Number of betting line simulations
        seed: Random seed for reproducibility
        injury_statuses: Dict mapping player_name -> injury status (from Yahoo API)
        freshness_tracker: Optional tracker to filter stale/repetitive content
    
    Returns:
        Complete stats report as dict (JSON-serializable)
    """
    waiver_adds = waiver_adds or {}
    injury_statuses = injury_statuses or {}
    
    # Determine if we should use playoff odds instead of regular title odds.
    # This triggers for actual playoff weeks AND the final regular season week,
    # since by that point standings are locked and the bracket preview is the
    # interesting forward-looking data.
    playoff_start = data.schedule.get("playoff_start_week", 99)
    regular_season_weeks = data.schedule.get("regular_season_weeks", playoff_start - 1)
    is_playoff = week >= playoff_start
    use_playoff_odds = week >= regular_season_weeks
    
    # Compute weekly report
    report = compute_weekly_report(data, week, waiver_adds)

    # Run title/playoff odds simulation
    # NOTE: Must run BEFORE update_records_from_weekly_report() so the title-odds
    # history (used by power-rankings trend arrows) gets written for THIS week.
    title_odds = None
    if run_simulations:
        if use_playoff_odds:
            title_odds = run_playoff_odds_simulation(
                data, num_simulations=num_title_sims, seed=seed,
                injury_statuses=injury_statuses,
            )
        else:
            title_odds = run_title_odds_simulation(
                data, num_simulations=num_title_sims, seed=seed
            )

    # Run betting simulation
    betting_lines = None
    if run_simulations:
        betting_lines = generate_weekly_betting_lines(
            data, num_simulations=num_betting_sims, seed=seed,
            injury_statuses=injury_statuses
        )

    # What-if analysis
    matchup_results = {}
    for matchup in report.matchups:
        matchup_results[matchup.manager_a] = {
            "score": matchup.score_a,
            "opponent_score": matchup.score_b,
        }
        matchup_results[matchup.manager_b] = {
            "score": matchup.score_b,
            "opponent_score": matchup.score_a,
        }
    what_if = analyze_weekly_what_if(data, week, matchup_results)

    # Update records AFTER simulations + what_if so we can pass title_odds,
    # bench_points, and blunders. Doing this earlier would leave
    # title_odds_history empty (freezing the power-rankings trend at "flat")
    # and skip cumulative_blunders updates.
    title_odds_for_records = title_odds.title_odds if title_odds else None
    bench_points_for_records = {
        m: a.total_bench_points for m, a in what_if.manager_analysis.items()
    } if what_if is not None else None
    blunders_for_records = {
        m: a.total_blunders for m, a in what_if.manager_analysis.items()
    } if what_if is not None else None
    record_updates = update_records_from_weekly_report(
        data,
        report,
        title_odds=title_odds_for_records,
        bench_points=bench_points_for_records,
        blunders=blunders_for_records,
    )
    
    # Generate fun facts (compute luck_index early so fun_facts can use it)
    luck_index_data = build_luck_index(data, week)
    fun_facts = generate_fun_facts(
        report, data, record_updates,
        title_odds=title_odds.title_odds if title_odds else None,
        waiver_adds=waiver_adds,
        luck_index=luck_index_data,
        seed=seed,
        freshness_tracker=freshness_tracker,
    )
    
    # Rumor mill analysis (with title odds and keeper_watch for V2 trade values)
    title_odds_dict = None
    if title_odds:
        # title_odds.title_odds is already dict[str, float] with percentages
        title_odds_dict = title_odds.title_odds
    
    # Build keeper_watch early so rumor mill can use V2 keepability scores
    keeper_watch_data = build_keeper_watch(data, week)
    
    rumor_mill = generate_rumor_mill_analysis(
        data, title_odds=title_odds_dict, week=week,
        freshness_tracker=freshness_tracker,
        keeper_watch=keeper_watch_data,
    )
    
    # Build report sections
    stats_report = {
        "metadata": {
            "season_year": data.season_year,
            "week": week,
            "date_range": {
                "start": report.date_range[0].isoformat(),
                "end": report.date_range[1].isoformat(),
            },
            "generated_at": datetime.now().isoformat(),
        },
        
        "matchup_summaries": build_matchup_summary(report, data.records, data=data, week=week),
        
        "team_stats": build_team_stats(report),
        
        "report_cards": build_report_cards(report, what_if),
        
        "looking_ahead": dataclass_to_dict(betting_lines) if betting_lines else None,
        
        "player_of_week": build_player_of_week(report),
        
        "fun_facts": [{"text": f.text, "category": f.category} for f in fun_facts],
        
        "what_if": {
            "manager_analysis": {
                m: {
                    "total_bench_points": a.total_bench_points,
                    "total_potential_gain": a.total_potential_gain,
                    "would_flip_matchup": a.would_flip_matchup,
                    "top_swaps": [s.to_dict() for s in a.swaps[:3]],
                    "blunders": a.total_blunders,
                    "blunder_points": round(a.total_blunder_points, 1),
                    "blunder_details": [b.to_dict() for b in a.blunders],
                }
                for m, a in what_if.manager_analysis.items()
            },
            "notable_swaps": what_if.notable_swaps,
        },
        
        "power_rankings": build_power_rankings(title_odds, data.records, data.leaguehistory, keeper_watch=keeper_watch_data) if title_odds else None,
        
        "best_worst": build_best_worst(report, data, week),
        
        "season_performers": build_season_performers(data.base_path, week),
        
        "rumor_mill": {
            "trade_ideas": [dataclass_to_dict(t) for t in rumor_mill.trade_ideas],
            "free_agent_targets": [dataclass_to_dict(t) for t in rumor_mill.free_agent_targets],
            "hot_streak_candidates": [dataclass_to_dict(h) for h in rumor_mill.hot_streak_candidates],
            "drop_candidates": [dataclass_to_dict(d) for d in rumor_mill.drop_candidates],
        },
        
        "current_standings": [
            {
                "manager": m,
                "record": f"{data.get_manager_record(m)[0]}-{data.get_manager_record(m)[1]}",
            }
            # Use H2H-aware ranker so ties resolve via league tiebreaker_rules
            # (head-to-head regular-season series, then total points), not just
            # raw win count -- which would alphabetize ties.
            for m in rank_managers_by_standings(data)
        ],
        
        "record_updates": [
            {
                "type": u.record_type,
                "description": u.description,
                "value": u.current_value,
            }
            for u in record_updates
        ],
        
        "all_time_records": build_all_time_records(data.records),
        
        "season_fppg_stats": data.records.get("season_fppg_stats", {}),
        
        "scoring_trends": build_scoring_trends(data.records, week),
        
        "rosters": build_rosters(data),
        
        "current_streaks": build_current_streaks(data.records),
        
        "season_injury_burden": build_season_injury_burden(data),
        
        "current_team_health": build_current_team_health(data, week),

        # === NEW FEATURES ===
        "luck_index": luck_index_data,
        "historical_luck": build_historical_luck(data, week, current_season=CURRENT_SEASON),

        "waiver_roi": build_waiver_roi(data, week),

        "schedule_strength": build_schedule_strength(data, week),

        "consistency_scores": build_consistency_scores(data, week),

        "positional_breakdown": build_positional_breakdown(data, week),

        "bench_report": build_bench_report(data, week),

        "record_book": build_record_book(data),

        "keeper_watch": keeper_watch_data,

        "draft_value_tracker": build_draft_value_tracker(data, week),
    }
    
    # Add playoff-specific data when applicable.
    # use_playoff_odds is True for the final regular season week AND actual playoff weeks,
    # so the championship odds section renders for all of them.
    # is_playoff_week tells the formatter to use the playoff section 7 layout.
    stats_report["is_playoff_week"] = use_playoff_odds
    if use_playoff_odds and isinstance(title_odds, PlayoffOddsResult):
        stats_report["playoff_odds"] = {
            "playoff_round": title_odds.playoff_round,
            "semi_matchups": title_odds.semi_matchups,
            "championship_matchup_probs": title_odds.championship_matchup_probs,
            "seeds": title_odds.seeds,
            "finish_distribution": title_odds.finish_distribution,
        }
    
    return stats_report


def build_all_time_records(records: dict) -> dict:
    """Build all-time records section for newsletter."""
    all_time = records.get("all_time", {})
    if not all_time:
        return None
    
    # Career standings
    careers = all_time.get("manager_careers", {})
    career_standings = sorted(
        [
            {
                "manager": m,
                "wins": stats.get("total_wins", 0),
                "losses": stats.get("total_losses", 0),
                "win_pct": stats.get("win_pct", 0),
                "total_points": stats.get("total_points_scored", 0),
            }
            for m, stats in careers.items()
        ],
        key=lambda x: -x["win_pct"]
    )
    
    # H2H records
    h2h_summary = {}
    for key, data in all_time.get("h2h", {}).items():
        # Extract just wins, not the games list
        h2h_summary[key] = {k: v for k, v in data.items() if k != "games"}
    
    # Record book
    return {
        "career_standings": career_standings,
        "h2h_records": h2h_summary,
        "highest_weekly_score": all_time.get("highest_weekly_score"),
        "lowest_weekly_score": all_time.get("lowest_weekly_score"),
        "biggest_blowout": all_time.get("biggest_blowout"),
        "closest_game": all_time.get("closest_game"),
        "longest_win_streaks": {
            m: s for m, s in all_time.get("longest_win_streaks", {}).items()
        },
        "longest_loss_streaks": {
            m: s for m, s in all_time.get("longest_loss_streaks", {}).items()
        },
    }


def save_stats_report(report: dict, output_path) -> None:
    """Save the stats report dict to a JSON file."""
    from pathlib import Path as _Path
    p = _Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)




# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from .data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 11
    
    print(f"Loading data from: {base.absolute()}")
    print(f"Building report for week {week}")
    print("-" * 50)
    
    data = load_all_data(base)
    
    # Load waivers
    waiver_file = base / f"data/waivers_week{week}.txt"
    waivers = load_waiver_adds(str(waiver_file))
    
    # Build report (with fewer simulations for testing)
    report = build_stats_report(
        data, week, waivers,
        run_simulations=True,
        num_title_sims=1000,
        num_betting_sims=500,
        seed=42,
    )
    
    # Save
    output_path = base / f"output/stats_report_week{week}.json"
    save_stats_report(report, output_path)
    
    print(f"\nReport saved to: {output_path}")
    print(f"Report sections: {list(report.keys())}")
