"""
weekly_stats.py

Computes team and player statistics for a given fantasy week.
This is the core stats engine that powers most newsletter sections.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date

import pandas as pd
import numpy as np

from .data_loader import (
    FantasyData,
    MANAGERS,
    get_position_list,
    parse_record_string,
    classify_position_group,
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PlayerWeekStats:
    """Statistics for a single player for one week."""
    player_name: str
    manager: str
    nba_team: str
    positions: list[str]
    
    # Game stats
    games_played: int = 0
    games_started: int = 0
    games_benched: int = 0
    games_injured: int = 0
    
    # Fantasy points
    total_fp: float = 0.0
    fppg: float = 0.0
    
    # Minutes (if available)
    total_minutes: float = 0.0
    fp_per_minute: Optional[float] = None
    
    # Efficiency (vs projection)
    projected_fppg: Optional[float] = None
    efficiency_pct: Optional[float] = None  # actual/projected as percentage
    
    # Individual game logs
    game_logs: list[dict] = field(default_factory=list)
    
    @property
    def best_game(self) -> Optional[dict]:
        """Return the highest-scoring game."""
        if not self.game_logs:
            return None
        return max(self.game_logs, key=lambda g: g.get("fantasy_points", 0))
    
    @property
    def worst_game(self) -> Optional[dict]:
        """Return the lowest-scoring game."""
        if not self.game_logs:
            return None
        return min(self.game_logs, key=lambda g: g.get("fantasy_points", 0))


@dataclass
class PositionalStats:
    """Aggregate stats for a position group (G/F/C)."""
    position: str  # "G", "F", or "C"
    total_fp: float = 0.0
    games: int = 0
    fppg: float = 0.0
    players: list[str] = field(default_factory=list)


@dataclass 
class ManagerWeekStats:
    """Complete statistics for a manager for one week."""
    manager: str
    fantasy_team: str
    week: int
    
    # Record
    wins: int = 0
    losses: int = 0
    
    # Scoring
    total_fp: float = 0.0
    team_fppg: float = 0.0
    
    # Games breakdown
    total_scheduled_games: int = 0
    total_healthy_starter_games: int = 0
    games_lost_to_injury: int = 0
    games_left_on_bench: int = 0
    injury_breakdown: list[dict] = field(default_factory=list)  # [{player, games, dates}, ...]
    
    # Efficiency
    efficiency_pct: float = 0.0  # healthy starter games / scheduled games
    
    # Positional breakdown
    guard_stats: PositionalStats = field(default_factory=lambda: PositionalStats("G"))
    forward_stats: PositionalStats = field(default_factory=lambda: PositionalStats("F"))
    center_stats: PositionalStats = field(default_factory=lambda: PositionalStats("C"))
    
    # Waiver stats
    waiver_adds: list[str] = field(default_factory=list)
    waiver_fp: float = 0.0
    waiver_games: int = 0
    
    # Player breakdown
    player_stats: dict[str, PlayerWeekStats] = field(default_factory=dict)
    
    # Best/worst performers
    best_performers: list = field(default_factory=list)  # Top 3 performers
    worst_healthy_performer: Optional[PlayerWeekStats] = None  # min 2 games
    
    # Backwards compatibility
    @property
    def best_performer(self) -> Optional[PlayerWeekStats]:
        """Return single best performer for backwards compatibility."""
        return self.best_performers[0] if self.best_performers else None
    
    @property
    def record_str(self) -> str:
        """Return record as string like '8-3'."""
        return f"{self.wins}-{self.losses}"


@dataclass
class MatchupStats:
    """Statistics for a head-to-head matchup."""
    week: int
    manager_a: str
    manager_b: str
    
    score_a: float = 0.0
    score_b: float = 0.0
    
    winner: Optional[str] = None
    margin: float = 0.0
    
    stats_a: Optional[ManagerWeekStats] = None
    stats_b: Optional[ManagerWeekStats] = None
    
    # Season series context
    series_record_a: int = 0  # wins by manager_a in season series
    series_record_b: int = 0
    
    @property
    def score_line(self) -> str:
        """Return formatted score line."""
        return f"{self.score_a:.1f} - {self.score_b:.1f}"
    
    @property
    def is_closest_of_season(self) -> bool:
        """Flag set externally if this is closest margin of season."""
        return getattr(self, "_is_closest", False)
    
    @property
    def is_largest_of_season(self) -> bool:
        """Flag set externally if this is largest margin of season."""
        return getattr(self, "_is_largest", False)


@dataclass
class WeeklyReport:
    """Complete weekly statistics report."""
    season_year: str
    week: int
    date_range: tuple[date, date]
    
    # Matchup results
    matchups: list[MatchupStats] = field(default_factory=list)
    
    # Manager stats
    manager_stats: dict[str, ManagerWeekStats] = field(default_factory=dict)
    
    # League-wide stats
    total_league_fp: float = 0.0
    avg_team_fp: float = 0.0
    
    # Best/worst of week (league-wide)
    best_single_game: Optional[dict] = None
    worst_single_game: Optional[dict] = None
    
    # All player stats for the week
    all_player_stats: list[PlayerWeekStats] = field(default_factory=list)
    
    # Context flags
    closest_margin_of_season: float = float("inf")
    largest_margin_of_season: float = 0.0


# =============================================================================
# POSITION CLASSIFICATION
# =============================================================================



# =============================================================================
# COMPUTATION FUNCTIONS
# =============================================================================

def player_season_fppg(data: FantasyData, player_name: str) -> Optional[float]:
    """
    A player's season FPPG: mean fantasy points over their started, healthy
    games across the whole season. Uses the same convention as weekly FPPG --
    started and not injured, which excludes DNPs (FP == 0) while keeping
    legitimate negative games. Returns None if the player has no such games.
    """
    plog = data.playerlog
    rows = plog[
        (plog["player_name"] == player_name)
        & (plog["started"])
        & (~plog["is_injured"])
    ]
    if len(rows) == 0:
        return None
    return float(rows["fantasy_points"].mean())


def projection_baseline(data: FantasyData, player_name: str) -> Optional[float]:
    """
    Baseline used for efficiency (actual FP vs expectation).

    Normally the forward projection (PLAYERLIST projectedFPPG). When that is
    0 or unavailable -- e.g. the final week of the season, when there are no
    upcoming games left to project -- fall back to the player's season FPPG so
    efficiency stays meaningful (actual vs season rate) instead of collapsing
    to zero and dragging report-card grades to None.
    """
    proj = data.get_player_projection(player_name)
    if proj and proj > 0:
        return proj
    return player_season_fppg(data, player_name)


def compute_player_week_stats(
    data: FantasyData,
    player_name: str,
    manager: str,
    week: int,
) -> PlayerWeekStats:
    """Compute stats for a single player for one week."""
    
    # Filter playerlog to this player, manager, week
    mask = (
        (data.playerlog["player_name"] == player_name) &
        (data.playerlog["manager"] == manager) &
        (data.playerlog["week"] == week)
    )
    player_games = data.playerlog[mask].copy()
    
    if player_games.empty:
        return PlayerWeekStats(
            player_name=player_name,
            manager=manager,
            nba_team="",
            positions=[],
        )
    
    # Get basic info from first row
    first_row = player_games.iloc[0]
    nba_team = str(first_row.get("nba_team", ""))
    positions = get_position_list(first_row.get("positions", ""))
    
    # Compute game counts
    games_played = len(player_games)
    games_started = int(player_games["started"].sum())
    games_injured = int(player_games["is_injured"].sum())
    games_benched = games_played - games_started - games_injured
    
    # Compute fantasy points (only count started, non-injured games)
    healthy_games = player_games[~player_games["is_injured"]]
    started_healthy_games = player_games[(player_games["started"]) & (~player_games["is_injured"])]
    total_fp = float(started_healthy_games["fantasy_points"].sum())
    
    # FPPG based on healthy games where player was in lineup
    fppg = float(started_healthy_games["fantasy_points"].mean()) if len(started_healthy_games) > 0 else 0.0
    
    # Minutes if available
    total_minutes = 0.0
    fp_per_minute = None
    if "minutes_played" in player_games.columns:
        total_minutes = float(healthy_games["minutes_played"].sum())
        if total_minutes > 0:
            fp_per_minute = total_fp / total_minutes
    
    # Projection baseline (forward projection, or season FPPG fallback in the
    # final week when there is nothing left to project).
    projected_fppg = projection_baseline(data, player_name)
    
    # Compute efficiency
    efficiency_pct = None
    if projected_fppg and projected_fppg > 0 and len(started_healthy_games) > 0:
        efficiency_pct = (fppg / projected_fppg) * 100
    
    # Build game logs
    game_logs = []
    for _, row in player_games.iterrows():
        game_logs.append({
            "date": row["date"],
            "nba_opponent": row.get("nba_opponent", ""),
            "fantasy_points": float(row["fantasy_points"]),
            "started": bool(row["started"]),
            "is_injured": bool(row["is_injured"]),
            "minutes_played": float(row.get("minutes_played", 0)) if "minutes_played" in row else None,
        })
    
    return PlayerWeekStats(
        player_name=player_name,
        manager=manager,
        nba_team=nba_team,
        positions=positions,
        games_played=games_played,
        games_started=len(started_healthy_games),
        games_benched=games_benched,
        games_injured=games_injured,
        total_fp=total_fp,
        fppg=fppg,
        total_minutes=total_minutes,
        fp_per_minute=fp_per_minute,
        projected_fppg=projected_fppg,
        efficiency_pct=efficiency_pct,
        game_logs=game_logs,
    )


def compute_manager_week_stats(
    data: FantasyData,
    manager: str,
    week: int,
    waiver_players: list[str] = None,
) -> ManagerWeekStats:
    """Compute all stats for a manager for one week."""
    
    # Get team name
    team_row = data.leaguehistory[data.leaguehistory["manager_name"] == manager]
    fantasy_team = ""  # Will get from playerlog
    
    # Filter data to this manager and week
    plog_mask = (data.playerlog["manager"] == manager) & (data.playerlog["week"] == week)
    manager_plog = data.playerlog[plog_mask].copy()
    
    lineups_mask = (data.lineups["manager"] == manager) & (data.lineups["week"] == week)
    manager_lineups = data.lineups[lineups_mask].copy()
    
    if not manager_plog.empty:
        fantasy_team = manager_plog.iloc[0].get("fantasy_team", "")
    
    # Get current record
    wins, losses = data.get_manager_record(manager)
    
    # Get unique players
    players = manager_plog["player_name"].unique()
    
    # Compute stats for each player
    player_stats = {}
    for player in players:
        ps = compute_player_week_stats(data, player, manager, week)
        player_stats[player] = ps
    
    # Aggregate totals
    total_fp = sum(ps.total_fp for ps in player_stats.values())
    
    # =======================================================================
    # GAME COUNTING DEFINITIONS (all from LINEUPS except games_played):
    # - Scheduled: has nba_opponent + has FP value + slot != IL
    # - Games lost to injury: has nba_opponent + FP = 0.0 + slot != IL
    # - Games left on bench: FP > 0 + slot ??? {BN, IL+}
    # - Games played: PLAYERLOG where started=TRUE and is_injured=FALSE
    # =======================================================================
    
    # Ensure fantasy_points is numeric in lineups
    manager_lineups["fantasy_points"] = pd.to_numeric(
        manager_lineups["fantasy_points"], errors="coerce"
    )
    
    # Scheduled games: non-IL slot with opponent AND has a FP value (not NaN)
    scheduled_mask = (
        ~manager_lineups["slot"].isin(["IL"]) &
        manager_lineups["nba_opponent"].notna() &
        (manager_lineups["nba_opponent"].astype(str).str.strip() != "") &
        manager_lineups["fantasy_points"].notna()
    )
    total_scheduled_games = int(scheduled_mask.sum())
    
    # Games played: PLAYERLOG where started=TRUE and is_injured=FALSE
    healthy_starter_mask = (
        (manager_plog["started"] == True) &
        (manager_plog["is_injured"] == False)
    )
    total_healthy_starter_games = int(healthy_starter_mask.sum())
    
    # Games lost to injury: LINEUPS with opponent + FP = 0.0 + slot != IL
    injury_mask = (
        ~manager_lineups["slot"].isin(["IL"]) &
        manager_lineups["nba_opponent"].notna() &
        (manager_lineups["nba_opponent"].astype(str).str.strip() != "") &
        (manager_lineups["fantasy_points"] == 0.0)
    )
    games_lost_to_injury = int(injury_mask.sum())
    
    # Injury breakdown - which players contributed to games_lost_to_injury
    injury_breakdown = []
    injured_rows = manager_lineups[injury_mask]
    if not injured_rows.empty:
        # Group by player
        for player_name, player_injuries in injured_rows.groupby("player_name"):
            dates = player_injuries["date"].tolist()
            # Convert dates to strings if they're date objects
            date_strs = [d.isoformat() if hasattr(d, 'isoformat') else str(d) for d in dates]
            injury_breakdown.append({
                "player": player_name,
                "games": len(dates),
                "dates": date_strs,
            })
        # Sort by games lost descending
        injury_breakdown.sort(key=lambda x: x["games"], reverse=True)
    
    # Games left on bench: LINEUPS with FP > 0 in BN or IL+ slot
    bench_mask = (
        manager_lineups["slot"].isin(["BN", "IL+"]) &
        (manager_lineups["fantasy_points"] > 0)
    )
    games_left_on_bench = int(bench_mask.sum())
    
    # Efficiency percentage
    # Measures performance vs projection for HEALTHY STARTERS ONLY
    # Formula: sum(actual FP) / sum(projected FPPG) for all healthy starter rows
    # Injury games and bench games are NOT included
    healthy_starter_rows = manager_plog[healthy_starter_mask]
    total_actual_fp = healthy_starter_rows["fantasy_points"].sum()
    total_projected_fp = 0.0
    for _, row in healthy_starter_rows.iterrows():
        player_name = row["player_name"]
        proj_fppg = projection_baseline(data, player_name)
        if proj_fppg is not None and proj_fppg > 0:
            total_projected_fp += proj_fppg
    
    efficiency_pct = 0.0
    if total_projected_fp > 0:
        efficiency_pct = (total_actual_fp / total_projected_fp) * 100
    
    # Team FPPG (total / days with games)
    days_with_games = manager_plog["date"].nunique()
    team_fppg = total_fp / days_with_games if days_with_games > 0 else 0.0
    
    # Positional breakdown
    guard_stats = PositionalStats("G")
    forward_stats = PositionalStats("F")
    center_stats = PositionalStats("C")
    
    for ps in player_stats.values():
        pos_group = classify_position_group(ps.positions)
        # Only count healthy started games for positional stats
        started_fp = sum(
            g["fantasy_points"] for g in ps.game_logs 
            if g["started"] and not g["is_injured"]
        )
        started_games = ps.games_started
        
        if pos_group == "G":
            guard_stats.total_fp += started_fp
            guard_stats.games += started_games
            guard_stats.players.append(ps.player_name)
        elif pos_group == "F":
            forward_stats.total_fp += started_fp
            forward_stats.games += started_games
            forward_stats.players.append(ps.player_name)
        else:  # C
            center_stats.total_fp += started_fp
            center_stats.games += started_games
            center_stats.players.append(ps.player_name)
    
    # Calculate positional FPPG
    guard_stats.fppg = guard_stats.total_fp / guard_stats.games if guard_stats.games > 0 else 0.0
    forward_stats.fppg = forward_stats.total_fp / forward_stats.games if forward_stats.games > 0 else 0.0
    center_stats.fppg = center_stats.total_fp / center_stats.games if center_stats.games > 0 else 0.0
    
    # Waiver stats
    waiver_players = waiver_players or []
    waiver_fp = 0.0
    waiver_games = 0
    for player in waiver_players:
        if player in player_stats:
            waiver_fp += player_stats[player].total_fp
            waiver_games += player_stats[player].games_started
    
    # Best performers (top 3 by total FP among starters)
    starters = [ps for ps in player_stats.values() if ps.games_started > 0]
    starters_sorted = sorted(starters, key=lambda ps: ps.total_fp, reverse=True)
    best_performers = starters_sorted[:3] if starters_sorted else []
    
    # Worst healthy performer (min 2 games, by FPPG)
    qualified = [ps for ps in player_stats.values() if ps.games_started >= 2]
    worst_healthy_performer = min(qualified, key=lambda ps: ps.fppg) if qualified else None
    
    return ManagerWeekStats(
        manager=manager,
        fantasy_team=fantasy_team,
        week=week,
        wins=wins,
        losses=losses,
        total_fp=total_fp,
        team_fppg=team_fppg,
        total_scheduled_games=total_scheduled_games,
        total_healthy_starter_games=total_healthy_starter_games,
        games_lost_to_injury=games_lost_to_injury,
        games_left_on_bench=games_left_on_bench,
        injury_breakdown=injury_breakdown,
        efficiency_pct=efficiency_pct,
        guard_stats=guard_stats,
        forward_stats=forward_stats,
        center_stats=center_stats,
        waiver_adds=waiver_players,
        waiver_fp=waiver_fp,
        waiver_games=waiver_games,
        player_stats=player_stats,
        best_performers=best_performers,
        worst_healthy_performer=worst_healthy_performer,
    )


def compute_matchup_stats(
    data: FantasyData,
    week: int,
    manager_a: str,
    manager_b: str,
    stats_a: ManagerWeekStats = None,
    stats_b: ManagerWeekStats = None,
) -> MatchupStats:
    """Compute matchup statistics between two managers."""
    
    # Get or compute manager stats
    if stats_a is None:
        stats_a = compute_manager_week_stats(data, manager_a, week)
    if stats_b is None:
        stats_b = compute_manager_week_stats(data, manager_b, week)
    
    score_a = stats_a.total_fp
    score_b = stats_b.total_fp
    
    # Determine winner
    if score_a > score_b:
        winner = manager_a
    elif score_b > score_a:
        winner = manager_b
    else:
        winner = None  # Tie
    
    margin = abs(score_a - score_b)
    
    # Get season series from records (if available)
    series_key = f"{manager_a}_vs_{manager_b}"
    alt_key = f"{manager_b}_vs_{manager_a}"
    
    h2h = data.records.get("h2h_season", {})
    series_record_a = 0
    series_record_b = 0
    
    if series_key in h2h:
        series_record_a = h2h[series_key].get(manager_a.lower(), 0)
        series_record_b = h2h[series_key].get(manager_b.lower(), 0)
    elif alt_key in h2h:
        series_record_a = h2h[alt_key].get(manager_a.lower(), 0)
        series_record_b = h2h[alt_key].get(manager_b.lower(), 0)
    
    return MatchupStats(
        week=week,
        manager_a=manager_a,
        manager_b=manager_b,
        score_a=score_a,
        score_b=score_b,
        winner=winner,
        margin=margin,
        stats_a=stats_a,
        stats_b=stats_b,
        series_record_a=series_record_a,
        series_record_b=series_record_b,
    )


def compute_weekly_report(
    data: FantasyData,
    week: int,
    waiver_adds: dict[str, list[str]] = None,
) -> WeeklyReport:
    """
    Compute complete weekly statistics report.
    
    Args:
        data: FantasyData container
        week: Fantasy week number
        waiver_adds: Dict mapping manager -> list of waiver add player names
    """
    waiver_adds = waiver_adds or {}
    
    # Get week date range
    start_date, end_date = data.get_week_dates(week)
    
    # Compute stats for each manager
    manager_stats = {}
    for manager in MANAGERS:
        manager_waivers = waiver_adds.get(manager, [])
        manager_stats[manager] = compute_manager_week_stats(
            data, manager, week, manager_waivers
        )
    
    # Compute matchups
    matchups = []
    for matchup_def in data.get_week_matchups(week):
        manager_a = matchup_def["manager_a"]
        manager_b = matchup_def["manager_b"]
        
        matchup = compute_matchup_stats(
            data, week, manager_a, manager_b,
            stats_a=manager_stats.get(manager_a),
            stats_b=manager_stats.get(manager_b),
        )
        matchups.append(matchup)
    
    # League-wide totals
    total_league_fp = sum(ms.total_fp for ms in manager_stats.values())
    avg_team_fp = total_league_fp / len(MANAGERS) if MANAGERS else 0.0
    
    # Collect all player stats
    all_player_stats = []
    for ms in manager_stats.values():
        all_player_stats.extend(ms.player_stats.values())
    
    # Find best/worst single games
    all_games = []
    for ps in all_player_stats:
        for game in ps.game_logs:
            if game["started"] and not game["is_injured"]:
                all_games.append({
                    "player_name": ps.player_name,
                    "manager": ps.manager,
                    "date": game["date"],
                    "fantasy_points": game["fantasy_points"],
                    "nba_opponent": game["nba_opponent"],
                })
    
    best_single_game = max(all_games, key=lambda g: g["fantasy_points"]) if all_games else None
    worst_single_game = min(all_games, key=lambda g: g["fantasy_points"]) if all_games else None
    
    # Check for closest/largest margins (would need historical data to compare)
    # For now, just track this week's margins
    margins = [m.margin for m in matchups]
    closest_margin = min(margins) if margins else float("inf")
    largest_margin = max(margins) if margins else 0.0
    
    return WeeklyReport(
        season_year=data.season_year,
        week=week,
        date_range=(start_date, end_date),
        matchups=matchups,
        manager_stats=manager_stats,
        total_league_fp=total_league_fp,
        avg_team_fp=avg_team_fp,
        best_single_game=best_single_game,
        worst_single_game=worst_single_game,
        all_player_stats=all_player_stats,
        closest_margin_of_season=closest_margin,
        largest_margin_of_season=largest_margin,
    )


def load_waiver_adds(filepath: str) -> dict[str, list[str]]:
    """
    Load waiver adds from a text file.
    
    Expected format (one per line):
        - [YYYY-MM-DD] Manager: Player Name
    
    Also supports legacy format:
        Player Name - Manager
    
    Lines starting with # are treated as comments and ignored.
    
    Returns:
        Dict mapping manager -> list of player names
    """
    import re
    
    waivers = {m: [] for m in MANAGERS}

    # FIXED: Match the manager by looking up against MANAGERS (longest match
    # wins) instead of \w+, so multi-word names like "Mary Jane" are not
    # truncated to "Mary".
    date_prefix_pattern = re.compile(r'^-\s*\[\d{4}-\d{2}-\d{2}\]\s+(.+)$')

    # Try longer manager names before shorter ones to avoid prefix collisions
    # (e.g., "Nick" vs "Nick Jr.").
    sorted_managers = sorted(MANAGERS, key=len, reverse=True)

    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Try new format first: - [date] Manager: Player
                prefix_match = date_prefix_pattern.match(line)
                if prefix_match:
                    rest = prefix_match.group(1)
                    matched = False
                    for mgr in sorted_managers:
                        token = f"{mgr}: "
                        if rest.startswith(token):
                            player = rest[len(token):].strip()
                            waivers[mgr].append(player)
                            matched = True
                            break
                    if matched:
                        continue

                # Fall back to legacy format: Player Name - Manager
                if " - " in line:
                    parts = line.split(" - ")
                    if len(parts) == 2:
                        player = parts[0].strip()
                        manager = parts[1].strip()
                        if manager in waivers:
                            waivers[manager].append(player)
    except FileNotFoundError:
        pass
    
    return waivers


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 11
    
    print(f"Loading data from: {base.absolute()}")
    print(f"Computing stats for week {week}")
    print("-" * 50)
    
    data = load_all_data(base)
    
    # Load waivers if available
    waiver_file = base / f"data/waivers_week{week}.txt"
    waivers = load_waiver_adds(str(waiver_file))
    
    # Compute report
    report = compute_weekly_report(data, week, waivers)
    
    print(f"\nWeek {report.week} Report")
    print(f"Date range: {report.date_range[0]} to {report.date_range[1]}")
    print(f"Total league FP: {report.total_league_fp:.1f}")
    print(f"Avg team FP: {report.avg_team_fp:.1f}")
    print()
    
    # Print matchups
    print("MATCHUPS:")
    for m in report.matchups:
        winner_mark = ""
        print(f"  {m.manager_a} ({m.score_a:.1f}) vs {m.manager_b} ({m.score_b:.1f})")
        print(f"    Winner: {m.winner} by {m.margin:.1f}")
    print()
    
    # Print manager stats
    print("MANAGER STATS:")
    for manager in MANAGERS:
        ms = report.manager_stats[manager]
        print(f"\n  {manager} ({ms.fantasy_team}):")
        print(f"    Total FP: {ms.total_fp:.1f}")
        print(f"    Efficiency: {ms.efficiency_pct:.1f}%")
        print(f"    G: {ms.guard_stats.total_fp:.1f} ({ms.guard_stats.games} games)")
        print(f"    F: {ms.forward_stats.total_fp:.1f} ({ms.forward_stats.games} games)")
        print(f"    C: {ms.center_stats.total_fp:.1f} ({ms.center_stats.games} games)")
        if ms.best_performer:
            print(f"    Best: {ms.best_performer.player_name} ({ms.best_performer.total_fp:.1f} FP)")
        if ms.worst_healthy_performer:
                      print(f"    Worst: {ms.worst_healthy_performer.player_name} ({ms.worst_healthy_performer.total_fp:.1f} FP)")

    print()
    if report.best_single_game:
        bg = report.best_single_game
        print(f"Best game: {bg['player_name']} ({bg['manager']}) - {bg['fantasy_points']:.1f} FP on {bg['date']}")
    if report.worst_single_game:
        wg = report.worst_single_game
        print(f"Worst game: {wg['player_name']} ({wg['manager']}) - {wg['fantasy_points']:.1f} FP on {wg['date']}")
