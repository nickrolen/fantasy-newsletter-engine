"""
simulator_title_odds.py -- the regular-season title race, simulated.

Title odds are the betting lines run over every remaining regular-season
week (Nick, 10-21: "the same thing as betting lines, but for the whole
season"). Each remaining week is ONE keyed matrix from
simulator_betting.week_score_matrices -- the same engine, draws and keys as
the betting lines and the playoff and Cup brackets -- so the real NBA
schedule, the 10-a-day cap, legal positions (A4), absence blocks (A2) and
the live tags are all in it. Simulation i reads column i of every week,
plays the fantasy schedule's matchups on those scores, and ranks the season
with data_loader.standings_order (a T is half a win).

WHAT THE NUMBER IS CONDITIONAL ON: today's rosters, frozen. "Given no
further moves, here is where you finish." That is deliberate: it is what
makes a waiver counterfactual readable -- drop one player, add another, and
the odds move by exactly that move (common random numbers), not by noise.
Modelling future adds (A5) would wash that signal out, so A5 stays deferred
by design. For the same reason simulated season point totals run LOW: every
injury absorbed is never replaced.

This file used to carry its own week model (a per-manager games count from
PLAYERLOG with a 1500-point default when PLAYERLOG was empty, never reading
the NBA schedule) and seven stdlib `random` sites. Both are gone: nothing
here draws from the global stream.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

from .data_loader import SEASON_SIMS
from .data_loader import (
    FantasyData,
    CURRENT_SEASON,
    MANAGERS,
    NUM_TEAMS,
    regular_season_weeks_for,
    Record,
    standings_order,
    week_outcome,
)
from .projections import load_all_team_projections
from .simulator_betting import week_score_matrices, scores_at


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = SEASON_SIMS   # config simulations.season_sims


# =============================================================================
# DATA CLASSES
# =============================================================================

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
    final_records: dict[str, Record]  # manager -> W-L-T
    final_points: dict[str, float]  # manager -> total points
    h2h_records: dict[str, dict[str, Record]]  # manager -> {opponent: W-L-T}
    champion: str
    finish_order: list[str]  # 1st to 4th


@dataclass
class TitleOddsResult:
    """Complete title odds simulation results."""
    num_simulations: int
    current_week: int
    
    # Core results
    title_odds: dict[str, float]  # manager -> % chance of winning
    expected_record: dict[str, tuple[float, float, float]]  # manager -> (exp W, exp L, exp T)
    finish_distribution: dict[str, dict[int, float]]  # manager -> {position: probability}
    
    # Supporting data
    magic_numbers: dict[str, Optional[int]]  # manager -> wins to clinch (None if N/A)
    current_records: dict[str, Record]
    h2h_records: dict[str, dict[str, Record]]
    
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
    23-game scale when the regular season is 15.

    The boundary comes from league_config. It used to come from SCHEDULE.json,
    which is the previous season's file for the whole preseason -- so this
    function did exactly what the paragraph above forbids, projecting a
    21-game race that does not exist.
    """
    max_week = regular_season_weeks_for(CURRENT_SEASON)
    remaining = []
    for week_data in data.schedule.get("weeks", []):
        if week_data["week"] > current_week and week_data["week"] <= max_week:
            remaining.append(week_data)
    return remaining


# =============================================================================
# SIMULATION CORE
# =============================================================================

def simulate_matchup(
    scores: dict[str, float],
    matchup_def: dict,
    week: int,
) -> SimulatedMatchup:
    """One matchup, read off one simulated week's scores {manager: score}."""
    manager_a = matchup_def["manager_a"]
    manager_b = matchup_def["manager_b"]
    
    score_a = scores[manager_a]
    score_b = scores[manager_b]
    
    # A tied regular-season week is a T for both, not a win for anyone
    # (tiebreaker_rules.regular_season_week; Nick, 10-20). winner None.
    # This used to coin-flip, on a convention overruled on 10-07.
    outcome = week_outcome(score_a, score_b)
    winner = manager_a if outcome == "a" else (manager_b if outcome == "b" else None)
    
    return SimulatedMatchup(
        week=week,
        manager_a=manager_a,
        manager_b=manager_b,
        score_a=score_a,
        score_b=score_b,
        winner=winner,
    )


def apply_tiebreakers(
    records: dict[str, Record],
    h2h: dict[str, dict[str, Record]],
    points: dict[str, float],
) -> list[str]:
    """Final standings, 1st to 4th: data_loader.standings_order -- the one
    ranking rule (winning percentage with a T as half a win, head-to-head
    among the tied, total points)."""
    return standings_order(records, h2h, points, list(records))


def simulate_full_season(
    current_records: dict[str, Record],
    current_h2h: dict[str, dict[str, Record]],
    current_points: dict[str, float],
    remaining_weeks: list[dict],
    week_scores: dict[int, dict[str, float]],
) -> SimulatedSeason:
    """
    Play out the rest of the regular season once.

    week_scores is ONE simulation's {week: {manager: score}} for every
    remaining week -- scores_at(week_score_matrices(...), i). The fantasy
    schedule's matchups are played on those scores; a tied week is a T for
    both (tiebreaker_rules.regular_season_week). Raises if a remaining week
    has no scores rather than skipping it.
    """
    records = dict(current_records)
    h2h = {m: dict(h) for m, h in current_h2h.items()}
    points = dict(current_points)

    for week_data in remaining_weeks:
        week = int(week_data["week"])
        if week not in week_scores:
            raise KeyError(f"no simulated scores for regular-season week {week}")
        scores = week_scores[week]
        for manager, score in scores.items():
            points[manager] = points.get(manager, 0.0) + score
        for matchup_def in week_data["matchups"]:
            matchup = simulate_matchup(scores, matchup_def, week)
            a, b = matchup.manager_a, matchup.manager_b
            if matchup.winner is None:
                ra, rb = "tie", "tie"
            else:
                ra, rb = ("win", "loss") if matchup.winner == a else ("loss", "win")
            records[a] = records.get(a, Record()).add(ra)
            records[b] = records.get(b, Record()).add(rb)
            h2h.setdefault(a, {})[b] = h2h.get(a, {}).get(b, Record()).add(ra)
            h2h.setdefault(b, {})[a] = h2h.get(b, {}).get(a, Record()).add(rb)

    finish_order = apply_tiebreakers(records, h2h, points)
    return SimulatedSeason(
        final_records=dict(records),
        final_points=points,
        h2h_records=h2h,
        champion=finish_order[0],
        finish_order=finish_order,
    )


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def compute_magic_numbers(
    current_records: dict,
    remaining_games: int,
    title_odds: dict,
    managers: list[str],
) -> dict:
    """
    Compute magic numbers for the current leader(s).

    Magic number = remaining_games - lead_over_best_rival + 1, i.e. the number
    of (own wins + best rival losses) that guarantees first place on wins.

    FIXED (co-leader bug): the best rival for each leader is the highest win
    total among all OTHER managers. For co-leaders that is the other co-leader
    (lead = 0), NOT the best team strictly below the lead -- the old logic
    measured tied leaders against 3rd place and understated their magic number.

    Trailing managers get None (they cannot clinch on their own wins alone),
    as do managers who are essentially eliminated (< 0.1% title odds).
    """
    # Standings value, not raw wins: a T is half a win (Record.standing).
    # With a half-game lead the count rounds up: the smallest whole number
    # of (own wins + best rival losses) that puts him strictly ahead.
    magic_numbers = {}
    max_wins = max(r.standing for r in current_records.values())

    for manager in managers:
        current_wins = current_records[manager].standing

        if title_odds.get(manager, 0.0) < 0.1:  # Essentially eliminated
            magic_numbers[manager] = None
        elif current_wins == max_wins:
            # Best rival = highest standing among all OTHER managers
            best_rival_wins = max(
                (r.standing for m2, r in current_records.items() if m2 != manager),
                default=0,
            )
            lead_over_rival = current_wins - best_rival_wins
            magic = math.floor(remaining_games - lead_over_rival) + 1
            magic_numbers[manager] = max(0, min(magic, remaining_games + 1))
        else:
            magic_numbers[manager] = None

    return magic_numbers


def run_title_odds_simulation(
    data: FantasyData,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    seed: int = None,
    injury_statuses: dict = None,
    team_projections: dict = None,
) -> TitleOddsResult:
    """
    The regular-season title race, Monte Carlo over the remaining weeks.

    Conditional on today's rosters, frozen -- see the module docstring.

    Args:
        data: FantasyData container
        num_simulations: Number of simulations to run
        seed: the run's seed (required): the same keyed draws as the betting
              lines and brackets, so a week is one simulated truth.
        injury_statuses: Yahoo tags, as the betting lines get them (they
              reach the first remaining week's games through absence.py).
        team_projections: rosters to simulate (default: today's, loaded from
              data). Pass a changed copy to price a move -- drop one player,
              add another -- against the same draws.

    Returns:
        TitleOddsResult with all simulation results
    """
    if seed is None:
        raise ValueError("run_title_odds_simulation needs an explicit seed: one seed per run, "
                         "chosen by the caller (generate_stats_report picks it)")

    current_week = data.current_week

    if team_projections is None:
        team_projections = load_all_team_projections(data)

    # Current state, all from the weekly results (data.regular_season_results):
    # records W-L-T, head-to-head W-L-T, and REGULAR-SEASON points -- the
    # points tiebreak in standings_order. Points used to be read from
    # LEAGUEHISTORY total_points_current_season, a different source from
    # every other surface's tiebreak.
    current_records = {m: data.get_manager_record(m) for m in MANAGERS}
    _recs, current_h2h, reg_points = data.regular_season_results()
    current_h2h = {m: dict(current_h2h.get(m, {})) for m in MANAGERS}
    current_points = {m: float(reg_points.get(m, 0.0)) for m in MANAGERS}
    
    # Get remaining weeks
    remaining_weeks = get_remaining_weeks(data, current_week)
    
    if not remaining_weeks:
        # Season is over
        finish_order = apply_tiebreakers(current_records, current_h2h, current_points)
        return TitleOddsResult(
            num_simulations=0,
            current_week=current_week,
            title_odds={m: (100.0 if m == finish_order[0] else 0.0) for m in MANAGERS},
            expected_record={m: (float(current_records[m].wins), float(current_records[m].losses),
                                 float(current_records[m].ties)) for m in MANAGERS},
            finish_distribution={m: {i+1: (100.0 if finish_order[i] == m else 0.0) for i in range(NUM_TEAMS)} for m in MANAGERS},
            magic_numbers={m: 0 if m == finish_order[0] else None for m in MANAGERS},
            current_records=current_records,
            h2h_records=current_h2h,
        )
    
    # Every remaining week simulated ONCE, all iterations at once, by the
    # betting lines' engine. Simulation i reads column i of every week.
    matrices = week_score_matrices(data, team_projections,
                                   [int(w["week"]) for w in remaining_weeks],
                                   injury_statuses, seed, num_simulations)

    # Run simulations
    title_wins = {m: 0 for m in MANAGERS}
    finish_counts = {m: {i: 0 for i in range(1, NUM_TEAMS + 1)} for m in MANAGERS}
    total_wins = {m: 0.0 for m in MANAGERS}
    total_losses = {m: 0.0 for m in MANAGERS}
    total_ties = {m: 0.0 for m in MANAGERS}
    
    for sim in range(num_simulations):
        result = simulate_full_season(current_records, current_h2h, current_points,
                                      remaining_weeks, scores_at(matrices, sim))
        
        # Track title winner
        title_wins[result.champion] += 1
        
        # Track finish positions
        for pos, manager in enumerate(result.finish_order, 1):
            finish_counts[manager][pos] += 1
        
        # Track records
        for manager, rec in result.final_records.items():
            total_wins[manager] += rec.wins
            total_losses[manager] += rec.losses
            total_ties[manager] += rec.ties
    
    # Compute results
    title_odds = {m: (title_wins[m] / num_simulations) * 100 for m in MANAGERS}
    
    expected_record = {
        m: (total_wins[m] / num_simulations, total_losses[m] / num_simulations,
            total_ties[m] / num_simulations)
        for m in MANAGERS
    }
    
    finish_distribution = {
        m: {pos: (count / num_simulations) * 100 for pos, count in positions.items()}
        for m, positions in finish_counts.items()
    }
    
    # Compute magic numbers
    remaining_games = sum(len(w["matchups"]) // 2 for w in remaining_weeks)  # games per manager
    magic_numbers = compute_magic_numbers(
        current_records, remaining_games, title_odds, MANAGERS
    )
    
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

def expected_standing(expected: tuple) -> float:
    """Expected standings value: exp W + tie_win_value * exp T."""
    from .data_loader import regular_season_tie_value
    w, _l, t = expected
    return w + float(regular_season_tie_value()) * t


def format_expected_record(expected: tuple) -> str:
    """'9.3-5.7', or '9.3-5.6-0.1' once expected ties reach a tenth."""
    w, l, t = expected
    return f"{w:.1f}-{l:.1f}" + (f"-{t:.1f}" if round(t, 1) > 0 else "")


def format_title_odds_table(result: TitleOddsResult) -> str:
    """Format title odds as a text table."""
    lines = []
    lines.append("| Rank | Team | Record | Title Odds | Trend | Exp. Record | Magic # |")
    lines.append("|------|------|--------|------------|-------|-------------|---------|")
    
    # Sort by title odds, then by expected wins as tiebreaker
    sorted_managers = sorted(
        MANAGERS,
        key=lambda m: (result.title_odds[m], expected_standing(result.expected_record[m])),
        reverse=True
    )
    
    for rank, manager in enumerate(sorted_managers, 1):
        record = result.current_records[manager]
        odds = result.title_odds[manager]
        
        # Trend
        delta = result.title_odds_delta.get(manager)
        if delta is not None:
            arrow = "[UP]" if delta > 0 else "[DN]" if delta < 0 else "->"
            trend = f"{arrow} {delta:+.1f}%"
        else:
            trend = "-"
        
        # Expected record
        exp_record = format_expected_record(result.expected_record[manager])
        
        # Magic number
        magic = result.magic_numbers.get(manager)
        magic_str = str(magic) if magic is not None else "-"
        
        lines.append(
            f"| {rank} | {manager} | {record} | {odds:.1f}% | {trend} | {exp_record} | {magic_str} |"
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
