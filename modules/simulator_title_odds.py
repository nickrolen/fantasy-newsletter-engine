"""
simulator_title_odds.py

Monte Carlo simulation for rest-of-season title odds.
Runs 10,000 simulations of remaining season to compute championship probabilities.

Uses simplified lineup model (top 10 by projection) for efficiency.
Availability is computed from projected_GP / remaining_team_games.
"""

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from collections import defaultdict

from .data_loader import (
    FantasyData,
    MANAGERS,
    NUM_TEAMS,
    REGULAR_SEASON_WEEKS,
    TIEBREAKER_RULES,
    parse_record_string,
)
from .projections import (
    PlayerProjection,
    TeamProjections,
    load_all_team_projections,
    get_player_availability_ros,
    is_player_available,
    sample_player_game_fp,
    ROS_DEFAULT_AVAILABILITY,
)
from .lineup_optimizer import AvailablePlayer, select_top_n_players


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = 10000
MAX_STARTERS_PER_DAY = 10


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SimulatedWeek:
    """Result of simulating one week for one manager."""
    manager: str
    week: int
    score: float
    games_played: int


@dataclass
class SimulatedMatchup:
    """Result of simulating a single matchup."""
    week: int
    manager_a: str
    manager_b: str
    score_a: float
    score_b: float
    winner: Optional[str]


@dataclass
class SimulatedSeason:
    """Result of simulating an entire season."""
    final_records: dict[str, tuple[int, int]]  # manager -> (wins, losses)
    final_points: dict[str, float]  # manager -> total points
    h2h_records: dict[str, dict[str, int]]  # manager -> {opponent: wins}
    champion: str
    finish_order: list[str]  # 1st to 4th


@dataclass
class TitleOddsResult:
    """Complete title odds simulation results."""
    num_simulations: int
    current_week: int
    
    # Core results
    title_odds: dict[str, float]  # manager -> % chance of winning
    expected_record: dict[str, tuple[float, float]]  # manager -> (exp wins, exp losses)
    finish_distribution: dict[str, dict[int, float]]  # manager -> {position: probability}
    
    # Supporting data
    magic_numbers: dict[str, Optional[int]]  # manager -> wins to clinch (None if N/A)
    current_records: dict[str, tuple[int, int]]
    h2h_records: dict[str, dict[str, int]]
    
    # Change from last week
    title_odds_delta: dict[str, float] = field(default_factory=dict)


# =============================================================================
# SCHEDULE HELPERS
# =============================================================================

def get_remaining_weeks(data: FantasyData, current_week: int) -> list[dict]:
    """Get schedule data for remaining REGULAR-SEASON weeks.

    The title odds simulator models the regular-season championship race only.
    Playoff weeks (> REGULAR_SEASON_WEEKS) must not be counted here -- otherwise
    expected_record, magic_numbers, and finish-distribution would all be on a
    23-game scale when the regular season is 21 games.
    """
    max_week = data.schedule.get("regular_season_weeks", REGULAR_SEASON_WEEKS)
    remaining = []
    for week_data in data.schedule.get("weeks", []):
        if week_data["week"] > current_week and week_data["week"] <= max_week:
            remaining.append(week_data)
    return remaining


def get_dates_in_week(week_data: dict) -> list[date]:
    """Get all dates within a fantasy week."""
    start = datetime.strptime(week_data["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(week_data["end_date"], "%Y-%m-%d").date()
    
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    
    return dates


def get_nba_games_on_date(data: FantasyData, game_date: date) -> dict[str, str]:
    """
    Get NBA games on a date.
    
    Returns dict mapping team -> opponent (with @ prefix for away games)
    """
    games_dict = {}
    
    # Use the FantasyData method which handles both schedule formats
    for game in data.get_nba_games_for_date(game_date):
        home = (game.get("home_team") or game.get("home") or "").upper()
        away = (game.get("away_team") or game.get("away") or "").upper()
        if home:
            games_dict[home] = away
        if away:
            games_dict[away] = f"@{home}"
    
    return games_dict


def compute_remaining_team_games(
    data: FantasyData,
    remaining_weeks: list[dict],
) -> dict[str, int]:
    """
    Compute total remaining games for each NBA team.
    
    Returns dict mapping NBA team abbreviation -> number of remaining games.
    """
    team_games = defaultdict(int)
    
    for week_data in remaining_weeks:
        for game_date in get_dates_in_week(week_data):
            for game in data.get_nba_games_for_date(game_date):
                home = (game.get("home_team") or game.get("home") or "").upper()
                away = (game.get("away_team") or game.get("away") or "").upper()
                if home:
                    team_games[home] += 1
                if away:
                    team_games[away] += 1
    
    return dict(team_games)


def compute_player_availability_rates(
    team_projections: dict[str, TeamProjections],
    remaining_team_games: dict[str, int],
    data: FantasyData = None,
    remaining_weeks: list[dict] = None,
) -> dict[str, float]:
    """
    Compute availability rate for each player based on projected GP.
    
    Since projected_GP is for the full NBA season (which extends beyond the 
    fantasy season), we use it as a RELIABILITY indicator:
    
    availability_rate = projected_GP / max_projected_GP
    
    A player projected for 48 GP when the max is 50 is ~96% reliable.
    A player projected for 35 GP when the max is 50 is ~70% reliable.
    
    For players with injury overrides:
    - During out_weeks: 0% (handled in get_player_availability_ros)
    - After return: Same reliability rate applies
    
    Args:
        team_projections: Dict of manager -> TeamProjections
        remaining_team_games: Dict of NBA team -> remaining games (for reference)
        data: FantasyData (optional, for future enhancements)
        remaining_weeks: List of remaining week data (optional)
    
    Returns dict mapping player_name -> availability rate (0.0 to 1.0)
    """
    availability_rates = {}
    
    # Find the max projected GP to establish "fully healthy" baseline
    all_proj_gp = []
    for team in team_projections.values():
        for player in team.players.values():
            if player.projected_gp > 0:
                all_proj_gp.append(player.projected_gp)
    
    max_proj_gp = max(all_proj_gp) if all_proj_gp else 50.0
    
    for manager, team in team_projections.items():
        for player in team.players.values():
            if player.projected_gp <= 0:
                # No projected GP, assume out
                availability_rates[player.player_name] = 0.0
                continue
            
            # Use projected GP as reliability indicator
            # Higher projected GP = more reliable/healthy player
            rate = player.projected_gp / max_proj_gp
            
            # Cap at reasonable bounds (never quite 100%, never below 0%)
            rate = min(0.98, max(0.0, rate))
            
            availability_rates[player.player_name] = rate
    
    return availability_rates


# =============================================================================
# SIMULATION CORE
# =============================================================================

def simulate_manager_daily_score(
    team_proj: TeamProjections,
    playing_teams: set[str],
    week: int,
    availability_rates: dict[str, float] = None,
) -> tuple[float, int]:
    """
    Simulate a manager's score for one day.
    
    Args:
        team_proj: Team projections
        playing_teams: Set of NBA teams playing today
        week: Current week number (for injury override checks)
        availability_rates: Dict mapping player_name -> availability rate.
                           If None, uses default 90%.
    
    Returns:
        (total_score, games_played)
    """
    if availability_rates is None:
        availability_rates = {}
    
    # Find available players who have games today
    available = []
    
    for player in team_proj.players.values():
        # Check if player's team is playing
        if player.nba_team.upper() not in playing_teams:
            continue
        
        # Get player's availability rate (from projected GP / remaining games)
        player_rate = availability_rates.get(player.player_name)
        
        # Check availability (injury overrides + random availability based on rate)
        availability = get_player_availability_ros(player, week, player_rate)
        if not is_player_available(availability):
            continue
        
        available.append(AvailablePlayer(
            name=player.player_name,
            positions=player.positions,
            projected_fp=player.projected_fppg,
        ))
    
    if not available:
        return 0.0, 0
    
    # Select top N players (simplified - no position constraints)
    starters = select_top_n_players(available, MAX_STARTERS_PER_DAY)
    
    # Sample scores for each starter
    total_score = 0.0
    for starter in starters:
        # Get the full projection for sampling
        player_proj = team_proj.players.get(starter.name)
        if player_proj:
            sampled_fp = sample_player_game_fp(player_proj)
            total_score += sampled_fp
        else:
            total_score += starter.projected_fp
    
    return total_score, len(starters)


def simulate_week(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    week_data: dict,
    availability_rates: dict[str, float] = None,
) -> dict[str, SimulatedWeek]:
    """
    Simulate one week for all managers.
    
    Args:
        data: FantasyData container
        team_projections: Dict of manager -> TeamProjections
        week_data: Week schedule data
        availability_rates: Dict of player_name -> availability rate
    
    Returns dict mapping manager -> SimulatedWeek
    """
    week_num = week_data["week"]
    dates = get_dates_in_week(week_data)
    
    # Track weekly totals per manager
    weekly_scores = {m: 0.0 for m in MANAGERS}
    weekly_games = {m: 0 for m in MANAGERS}
    
    for game_date in dates:
        # Get teams playing today
        games = get_nba_games_on_date(data, game_date)
        playing_teams = set(games.keys())
        
        for manager in MANAGERS:
            team_proj = team_projections[manager]
            day_score, day_games = simulate_manager_daily_score(
                team_proj, playing_teams, week_num, availability_rates
            )
            weekly_scores[manager] += day_score
            weekly_games[manager] += day_games
    
    # Add team-level variance
    for manager in MANAGERS:
        team_proj = team_projections[manager]
        noise = random.gauss(0, team_proj.weekly_std_dev * 0.2)
        weekly_scores[manager] = max(0, weekly_scores[manager] + noise)
    
    return {
        manager: SimulatedWeek(
            manager=manager,
            week=week_num,
            score=weekly_scores[manager],
            games_played=weekly_games[manager],
        )
        for manager in MANAGERS
    }


def compute_historical_weekly_stats(data: FantasyData) -> dict[str, dict]:
    """
    Compute historical weekly statistics from PLAYERLOG.
    
    Returns dict mapping manager -> {
        'avg_games': float,  # Average games started per week
        'avg_score': float,  # Average weekly score
        'std_score': float,  # Standard deviation of weekly scores
        'avg_fppg': float,   # Average FPPG across all started games
    }
    """
    plog = data.playerlog
    started = plog[plog['started'] == True]
    
    stats = {}
    for manager in MANAGERS:
        mgr_data = started[started['manager'] == manager]
        
        # Weekly aggregates
        weekly = mgr_data.groupby('week').agg({
            'fantasy_points': ['sum', 'count']
        })
        weekly.columns = ['total_fp', 'games']
        
        if len(weekly) > 0:
            stats[manager] = {
                'avg_games': weekly['games'].mean(),
                'avg_score': weekly['total_fp'].mean(),
                'std_score': weekly['total_fp'].std() if len(weekly) > 1 else 150.0,
                'avg_fppg': mgr_data['fantasy_points'].mean(),
            }
        else:
            stats[manager] = {
                'avg_games': 40.0,
                'avg_score': 1500.0,
                'std_score': 150.0,
                'avg_fppg': 37.0,
            }
    
    return stats


def simulate_week_historical(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    week_data: dict,
    historical_stats: dict[str, dict] = None,
) -> dict[str, SimulatedWeek]:
    """
    Simulate one week with maximum realism.
    
    This simulation accounts for:
    1. Full roster depth (all 16-17 players, not just top 10)
    2. Historical games-per-week patterns (stable across roster turnover)
    3. Injury overrides (players out specific weeks)
    4. Player availability based on projected_gp (injury-prone players play less)
    5. Player-by-player variance using projected FPPG and std dev
    6. Realistic game distribution across roster
    
    Key insight: projected_gp reflects expected availability. A player projected
    for 32 GP vs 48 GP should get proportionally fewer games in our simulation.
    This captures injury risk, rest patterns, and reliability.
    
    Args:
        data: FantasyData container
        team_projections: Dict of manager -> TeamProjections  
        week_data: Week schedule data
        historical_stats: Pre-computed historical stats (optional)
    
    Returns dict mapping manager -> SimulatedWeek
    """
    week_num = week_data["week"]
    
    if historical_stats is None:
        historical_stats = compute_historical_weekly_stats(data)
    
    # Calculate league average games per week
    league_avg_games = sum(h['avg_games'] for h in historical_stats.values()) / len(historical_stats)
    
    # Regression weight: how much to regress toward league average
    # 0.0 = use full historical, 1.0 = use full league average
    # 0.5 = blend 50/50 (assumes outliers will partially normalize)
    REGRESSION_WEIGHT = 0.5
    
    results = {}
    
    for manager in MANAGERS:
        team = team_projections[manager]
        hist = historical_stats[manager]
        
        # Regress this manager's historical games/week toward league average
        # This prevents punishing managers who had early injuries (they'll recover)
        # while still giving credit to managers who consistently get more games
        manager_hist_games = hist['avg_games']
        manager_avg_games = manager_hist_games * (1 - REGRESSION_WEIGHT) + league_avg_games * REGRESSION_WEIGHT
        
        # Get all players available this week (not on injury override)
        all_players = []
        for p in team.players.values():
            is_out = week_num in p.out_weeks
            if not is_out and p.projected_fppg > 0:
                all_players.append(p)
        
        if not all_players:
            results[manager] = SimulatedWeek(manager=manager, week=week_num, score=0.0, games_played=0)
            continue
        
        # Find max projected_gp to establish baseline availability
        max_gp = max(p.projected_gp for p in all_players if p.projected_gp > 0)
        if max_gp == 0:
            max_gp = 50  # Fallback
        
        # Calculate availability rate for each player
        # Higher projected_gp = more reliable = more games
        player_availability = {}
        for p in all_players:
            if p.projected_gp > 0:
                player_availability[p.player_name] = p.projected_gp / max_gp
            else:
                player_availability[p.player_name] = 0.5  # Unknown, assume average
        
        # Sort by availability-weighted FPPG (best effective value first)
        all_players.sort(key=lambda p: p.projected_fppg * player_availability[p.player_name], reverse=True)
        
        # Calculate team's effective strength relative to full availability
        # This affects total games (weaker effective roster = slightly fewer quality starts)
        avg_availability = sum(player_availability[p.player_name] for p in all_players[:10]) / min(10, len(all_players))
        
        # Expected games: this manager's historical average, scaled by availability
        expected_games = manager_avg_games * max(0.90, min(1.0, avg_availability))
        
        # Add variance to total games (week-to-week schedule variance ~8%)
        actual_games = max(25, int(random.gauss(expected_games, expected_games * 0.08)))
        
        # Distribute games across roster
        # Weight by BOTH rank AND availability
        # A highly-available depth player might get more games than an injury-prone star
        
        num_players = len(all_players)
        weights = []
        for i, p in enumerate(all_players):
            # Rank weight: decreases with rank
            rank_weight = 0.95 ** i
            
            # Availability weight: from projected_gp
            avail_weight = player_availability[p.player_name]
            
            # Combined weight: rank matters more, but availability adjusts it
            # A top player at 65% availability gets ~65% of a full-availability top player
            combined_weight = rank_weight * avail_weight
            weights.append(combined_weight)
        
        total_weight = sum(weights)
        if total_weight == 0:
            total_weight = 1  # Avoid division by zero
        
        # First pass: allocate expected games based on weights
        expected_games_list = []
        for i, player in enumerate(all_players):
            expected = actual_games * (weights[i] / total_weight)
            expected_games_list.append(expected)
        
        # Second pass: add variance and cap
        player_games = []
        for i, (player, expected) in enumerate(zip(all_players, expected_games_list)):
            # Add individual variance (more variance for injury-prone players)
            avail = player_availability[player.player_name]
            variance = max(0.5, expected * (0.10 + 0.15 * (1 - avail)))  # More variance if less reliable
            
            game_count = max(0, round(random.gauss(expected, variance)))
            game_count = min(game_count, 7)  # Cap at 7 games per week
            player_games.append([player, game_count])
        
        # Adjust to hit target exactly
        current_total = sum(g for _, g in player_games)
        diff = actual_games - current_total
        
        attempts = 0
        while diff != 0 and attempts < 50:
            if diff > 0:
                # Need more games - add to a player under cap, weighted by availability
                eligible = [i for i, (p, g) in enumerate(player_games) if g < 7]
                if eligible:
                    weights_eligible = [weights[i] for i in eligible]
                    total_w = sum(weights_eligible)
                    if total_w > 0:
                        probs = [w/total_w for w in weights_eligible]
                        idx = random.choices(eligible, weights=probs)[0]
                        player_games[idx][1] += 1
                        diff -= 1
                    else:
                        break
                else:
                    break
            else:
                # Too many games - remove from a player, prefer low-availability players
                eligible = [i for i, (p, g) in enumerate(player_games) if g > 0]
                if eligible:
                    # Inverse weight - remove from less reliable players first
                    weights_eligible = [1.0 / (weights[i] + 0.1) for i in eligible]
                    total_w = sum(weights_eligible)
                    probs = [w/total_w for w in weights_eligible]
                    idx = random.choices(eligible, weights=probs)[0]
                    player_games[idx][1] -= 1
                    diff += 1
                else:
                    break
            attempts += 1
        
        # Simulate each player's contribution
        total_score = 0.0
        total_games_played = 0
        
        for player, num_games in player_games:
            for _ in range(num_games):
                # Sample from player's distribution
                sampled_fp = sample_player_game_fp(player)
                total_score += sampled_fp
                total_games_played += 1
        
        # Add small team-level noise (lineup decisions, late scratches, etc.)
        team_noise = random.gauss(0, hist['std_score'] * 0.15)
        total_score = max(0, total_score + team_noise)
        
        results[manager] = SimulatedWeek(
            manager=manager,
            week=week_num,
            score=total_score,
            games_played=total_games_played,
        )
    
    return results


def simulate_matchup(
    week_results: dict[str, SimulatedWeek],
    matchup_def: dict,
) -> SimulatedMatchup:
    """Simulate a single matchup given weekly scores."""
    manager_a = matchup_def["manager_a"]
    manager_b = matchup_def["manager_b"]
    
    score_a = week_results[manager_a].score
    score_b = week_results[manager_b].score
    
    if score_a > score_b:
        winner = manager_a
    elif score_b > score_a:
        winner = manager_b
    else:
        # Tie - coin flip (project-wide convention for SIMULATED ties).
        # Ties are extremely rare with fractional scoring, but we still need a
        # statistically honest tiebreak: a simulated tie should resolve either
        # way with equal probability. See data_loader.py docstring for the
        # full set of tie conventions.
        winner = random.choice([manager_a, manager_b])
    
    return SimulatedMatchup(
        week=week_results[manager_a].week,
        manager_a=manager_a,
        manager_b=manager_b,
        score_a=score_a,
        score_b=score_b,
        winner=winner,
    )


def apply_tiebreakers(
    records: dict[str, tuple[int, int]],
    h2h: dict[str, dict[str, int]],
    points: dict[str, float],
) -> list[str]:
    """
    Apply tiebreakers to determine final standings using TIEBREAKER_RULES.

    Returns list of managers from 1st to 4th place.

    Tiebreakers (driven by league_config.json):
    1. Record (wins) DESC
    2. Within ties: the configured "standings" rule
       - "h2h_regular_season": combined H2H wins among the tied managers
       - "total_points": skip straight to the fallback
    3. Fallback "fallback" rule
       - "total_points": total simulated points DESC
       - anything else: zero (no fallback)

    This mirrors rank_managers_by_standings() in simulator_playoff_odds.py but
    operates on SIMULATED final standings rather than actual data.
    """
    standings_rule = TIEBREAKER_RULES.get("standings", "h2h_regular_season")
    fallback_rule = TIEBREAKER_RULES.get("fallback", "total_points")

    # Group managers by wins
    by_wins = defaultdict(list)
    for manager, (wins, losses) in records.items():
        by_wins[wins].append(manager)

    final_order = []
    for wins in sorted(by_wins.keys(), reverse=True):
        tied_managers = by_wins[wins]

        if len(tied_managers) == 1:
            final_order.append(tied_managers[0])
            continue

        # Compute the standings-rule value for each tied manager (higher = better).
        if standings_rule == "h2h_regular_season":
            h2h_score = {
                m: sum(
                    h2h.get(m, {}).get(opp, 0)
                    for opp in tied_managers if opp != m
                )
                for m in tied_managers
            }
        else:
            h2h_score = {m: 0 for m in tied_managers}

        # Compute the fallback value (higher = better).
        if fallback_rule == "total_points":
            fallback_val = {m: points.get(m, 0.0) for m in tied_managers}
        else:
            fallback_val = {m: 0.0 for m in tied_managers}

        sorted_tied = sorted(
            tied_managers,
            key=lambda m: (h2h_score[m], fallback_val[m]),
            reverse=True,
        )
        final_order.extend(sorted_tied)

    return final_order


def simulate_full_season(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    current_records: dict[str, tuple[int, int]],
    current_h2h: dict[str, dict[str, int]],
    current_points: dict[str, float],
    remaining_weeks: list[dict],
    availability_rates: dict[str, float] = None,
    historical_stats: dict[str, dict] = None,
    use_historical: bool = True,
) -> SimulatedSeason:
    """
    Simulate the remainder of the season.
    
    Args:
        data: FantasyData container
        team_projections: Projections for all teams
        current_records: Starting records
        current_h2h: Starting H2H records
        current_points: Starting total points
        remaining_weeks: List of week data dicts for remaining weeks
        availability_rates: Dict of player_name -> availability rate
        historical_stats: Pre-computed historical weekly stats
        use_historical: If True, use historical-based simulation (accounts for roster turnover)
    
    Returns:
        SimulatedSeason with final results
    """
    # Copy current state
    records = {m: list(r) for m, r in current_records.items()}  # Make mutable
    h2h = {m: dict(h) for m, h in current_h2h.items()}
    points = dict(current_points)
    
    # Simulate each remaining week
    for week_data in remaining_weeks:
        if use_historical and historical_stats is not None:
            week_results = simulate_week_historical(data, team_projections, week_data, historical_stats)
        else:
            week_results = simulate_week(data, team_projections, week_data, availability_rates)
        
        # Update points
        for manager, result in week_results.items():
            points[manager] += result.score
        
        # Simulate matchups
        for matchup_def in week_data["matchups"]:
            matchup = simulate_matchup(week_results, matchup_def)
            
            winner = matchup.winner
            loser = matchup.manager_a if winner == matchup.manager_b else matchup.manager_b
            
            # Update records
            records[winner][0] += 1  # wins
            records[loser][1] += 1   # losses
            
            # Update H2H
            if winner not in h2h:
                h2h[winner] = {}
            h2h[winner][loser] = h2h[winner].get(loser, 0) + 1
    
    # Convert records back to tuples
    final_records = {m: tuple(r) for m, r in records.items()}
    
    # Apply tiebreakers to determine final order
    finish_order = apply_tiebreakers(final_records, h2h, points)
    champion = finish_order[0]
    
    return SimulatedSeason(
        final_records=final_records,
        final_points=points,
        h2h_records=h2h,
        champion=champion,
        finish_order=finish_order,
    )


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_title_odds_simulation(
    data: FantasyData,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    seed: int = None,
) -> TitleOddsResult:
    """
    Run Monte Carlo simulation for title odds.
    
    Args:
        data: FantasyData container
        num_simulations: Number of simulations to run
        seed: Random seed for reproducibility (optional)
    
    Returns:
        TitleOddsResult with all simulation results
    """
    if seed is not None:
        random.seed(seed)
    
    current_week = data.current_week
    
    # Load team projections
    team_projections = load_all_team_projections(data)
    
    # Get current state
    current_records = {}
    current_points = {}
    for manager in MANAGERS:
        current_records[manager] = data.get_manager_record(manager)
        # Get total points from leaguehistory
        row = data.leaguehistory[data.leaguehistory["manager_name"] == manager]
        if not row.empty:
            current_points[manager] = float(row.iloc[0].get("total_points_current_season", 0))
        else:
            current_points[manager] = 0.0
    
    # Get current H2H from records
    current_h2h = {}
    for manager in MANAGERS:
        current_h2h[manager] = {}
    
    # Parse H2H from RECORDS.json if available
    h2h_data = data.records.get("h2h_season", {})
    for key, record in h2h_data.items():
        parts = key.split("_vs_")
        if len(parts) == 2:
            m1, m2 = parts
            for manager, opponent in [(m1, m2), (m2, m1)]:
                if manager in MANAGERS and opponent in MANAGERS:
                    wins = record.get(manager.lower(), 0)
                    if manager not in current_h2h:
                        current_h2h[manager] = {}
                    current_h2h[manager][opponent] = wins
    
    # Get remaining weeks
    remaining_weeks = get_remaining_weeks(data, current_week)
    
    if not remaining_weeks:
        # Season is over
        finish_order = apply_tiebreakers(current_records, current_h2h, current_points)
        return TitleOddsResult(
            num_simulations=0,
            current_week=current_week,
            title_odds={m: (100.0 if m == finish_order[0] else 0.0) for m in MANAGERS},
            expected_record={m: current_records[m] for m in MANAGERS},
            finish_distribution={m: {i+1: (100.0 if finish_order[i] == m else 0.0) for i in range(NUM_TEAMS)} for m in MANAGERS},
            magic_numbers={m: 0 if m == finish_order[0] else None for m in MANAGERS},
            current_records=current_records,
            h2h_records=current_h2h,
        )
    
    # Compute remaining team games and player availability rates
    remaining_team_games = compute_remaining_team_games(data, remaining_weeks)
    availability_rates = compute_player_availability_rates(
        team_projections, remaining_team_games, data, remaining_weeks
    )
    
    # Compute historical weekly stats for historical simulation method
    historical_stats = compute_historical_weekly_stats(data)
    
    # Run simulations
    title_wins = {m: 0 for m in MANAGERS}
    finish_counts = {m: {i: 0 for i in range(1, NUM_TEAMS + 1)} for m in MANAGERS}
    total_wins = {m: 0.0 for m in MANAGERS}
    total_losses = {m: 0.0 for m in MANAGERS}
    
    for sim in range(num_simulations):
        result = simulate_full_season(
            data,
            team_projections,
            current_records,
            current_h2h,
            current_points,
            remaining_weeks,
            availability_rates,
            historical_stats,
            use_historical=True,  # Use historical-based simulation
        )
        
        # Track title winner
        title_wins[result.champion] += 1
        
        # Track finish positions
        for pos, manager in enumerate(result.finish_order, 1):
            finish_counts[manager][pos] += 1
        
        # Track records
        for manager, (wins, losses) in result.final_records.items():
            total_wins[manager] += wins
            total_losses[manager] += losses
    
    # Compute results
    title_odds = {m: (title_wins[m] / num_simulations) * 100 for m in MANAGERS}
    
    expected_record = {
        m: (total_wins[m] / num_simulations, total_losses[m] / num_simulations)
        for m in MANAGERS
    }
    
    finish_distribution = {
        m: {pos: (count / num_simulations) * 100 for pos, count in positions.items()}
        for m, positions in finish_counts.items()
    }
    
    # Compute magic numbers
    # FIXED: Magic number only makes sense for leaders/co-leaders
    # For trailing managers, they can't "clinch" just by winning - they need the leader to lose
    remaining_games = sum(len(w["matchups"]) // 2 for w in remaining_weeks)  # games per manager
    magic_numbers = {}
    
    # Find current leader(s)
    max_wins = max(r[0] for r in current_records.values())
    
    # Find the best second-place wins (excluding ties for first)
    second_place_wins = 0
    for m, (w, l) in current_records.items():
        if w < max_wins and w > second_place_wins:
            second_place_wins = w
    
    for manager in MANAGERS:
        current_wins, current_losses = current_records[manager]
        
        # Can this manager still win?
        if title_odds[manager] < 0.1:  # Essentially eliminated
            magic_numbers[manager] = None
        elif current_wins == max_wins:
            # Current leader (or tied for lead)
            # Magic number = remaining games - lead + 1
            # This is: wins needed such that even if 2nd place wins all remaining, they can't catch you
            lead_over_second = max_wins - second_place_wins
            magic = remaining_games - lead_over_second + 1
            magic_numbers[manager] = max(0, min(magic, remaining_games + 1))
        else:
            # FIXED: Trailing managers don't have a "magic number"
            # They can't clinch just by winning - they need leader to lose
            # Instead, show "games back" or None
            magic_numbers[manager] = None
    
    # Get delta from last week (if available)
    title_odds_delta = {}
    last_week_key = f"week_{current_week - 1}"
    if last_week_key in data.records.get("title_odds_history", {}):
        last_odds = data.records["title_odds_history"][last_week_key]
        for manager in MANAGERS:
            if manager in last_odds:
                title_odds_delta[manager] = title_odds[manager] - last_odds[manager]
    
    return TitleOddsResult(
        num_simulations=num_simulations,
        current_week=current_week,
        title_odds=title_odds,
        expected_record=expected_record,
        finish_distribution=finish_distribution,
        magic_numbers=magic_numbers,
        current_records=current_records,
        h2h_records=current_h2h,
        title_odds_delta=title_odds_delta,
    )


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_title_odds_table(result: TitleOddsResult) -> str:
    """Format title odds as a text table."""
    lines = []
    lines.append("| Rank | Team | Record | Title Odds | Trend | Exp. Record | Magic # |")
    lines.append("|------|------|--------|------------|-------|-------------|---------|")
    
    # Sort by title odds, then by expected wins as tiebreaker
    sorted_managers = sorted(
        MANAGERS,
        key=lambda m: (result.title_odds[m], result.expected_record[m][0]),
        reverse=True
    )
    
    for rank, manager in enumerate(sorted_managers, 1):
        wins, losses = result.current_records[manager]
        odds = result.title_odds[manager]
        
        # Trend
        delta = result.title_odds_delta.get(manager)
        if delta is not None:
            arrow = "[UP]" if delta > 0 else "[DN]" if delta < 0 else "->"
            trend = f"{arrow} {delta:+.1f}%"
        else:
            trend = "-"
        
        # Expected record
        exp_w, exp_l = result.expected_record[manager]
        exp_record = f"{exp_w:.1f}-{exp_l:.1f}"
        
        # Magic number
        magic = result.magic_numbers.get(manager)
        magic_str = str(magic) if magic is not None else "-"
        
        lines.append(
            f"| {rank} | {manager} | {wins}-{losses} | {odds:.1f}% | {trend} | {exp_record} | {magic_str} |"
        )
    
    return "\n".join(lines)




# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    num_sims = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    
    print(f"Loading data from: {base.absolute()}")
    print(f"Running {num_sims} simulations...")
    print("-" * 50)
    
    data = load_all_data(base)
    result = run_title_odds_simulation(data, num_simulations=num_sims, seed=42)
    
    print(f"\nTitle Odds (Week {result.current_week}):")
    print(format_title_odds_table(result))
    
    print("\nFinish Distribution:")
    for manager in MANAGERS:
        dist = result.finish_distribution[manager]
        print(f"  {manager}: 1st={dist[1]:.1f}% 2nd={dist[2]:.1f}% 3rd={dist[3]:.1f}% 4th={dist[4]:.1f}%")
