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

import numpy as np
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
from .season_sim import (  # noqa: F401  (re-exported: the regular-season rules layer)
    SimulatedMatchup, SimulatedSeason, apply_tiebreakers, run_season,
    simulate_full_season, simulate_matchup,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = SEASON_SIMS   # config simulations.season_sims


# =============================================================================
# DATA CLASSES
# =============================================================================

# SimulatedMatchup, SimulatedSeason, simulate_matchup, apply_tiebreakers and
# simulate_full_season live in season_sim now (Phase 2 lifted them there to
# carry the season past week 15); imported back below under the same names.

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
# MAIN SIMULATION
# =============================================================================

def compute_magic_numbers(
    current_records: dict,
    remaining_games,
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
    # remaining_games: {manager: regular-season games he has left}, computed
    # off the season pass (Phase 2). It used to be one int, len(matchups) // 2
    # per week -- right only for four teams who all play every week. An int
    # is still accepted and means the same count for everyone.
    if not isinstance(remaining_games, dict):
        remaining_games = {m: int(remaining_games) for m in managers}
    magic_numbers = {}
    max_wins = max(r.standing for r in current_records.values())

    for manager in managers:
        current_wins = current_records[manager].standing
        games_left = remaining_games.get(manager, 0)

        if title_odds.get(manager, 0.0) < 0.1:  # Essentially eliminated
            magic_numbers[manager] = None
        elif current_wins == max_wins:
            # The threat is the best total a RIVAL can still reach -- his
            # standing plus HIS games left. Each own win or threat loss
            # closes one; clinched once the leader's standing is strictly
            # past it. With one count for everyone this was the old
            # games_left - lead + 1; with per-manager counts the leader's
            # own games are the wrong ones (Phase 2: a rival with a game in
            # hand was called clinched against).
            threat = max(
                (r.standing + remaining_games.get(m2, 0)
                 for m2, r in current_records.items() if m2 != manager),
                default=0,
            )
            magic_numbers[manager] = max(0, math.floor(threat - current_wins) + 1)
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
    """The regular-season title race: a READOUT of the season pass
    (season_sim.run_season), stopped after the regular season -- a later
    stage cannot move it. Conditional on today's rosters, frozen.

    seed is required: the same keyed draws as the betting lines and brackets.
    team_projections: rosters to simulate (default: today's). Pass a changed
    copy to price a move -- drop one player, add another -- on the same draws.
    """
    if seed is None:
        raise ValueError("run_title_odds_simulation needs an explicit seed: one seed per run, "
                         "chosen by the caller (generate_stats_report picks it)")
    return run_season(data, num_simulations, seed, injury_statuses, team_projections,
                      through="regular").title_result()


def title_readout(sp) -> TitleOddsResult:
    """TitleOddsResult from a season pass: the regular-season marginals."""
    data, n, managers = sp.data, sp.num_simulations, sp.managers
    current_week = sp.current_week
    current_records = {m: data.get_manager_record(m) for m in MANAGERS}
    first = np.bincount(sp.reg_finish[:, 0], minlength=len(managers))
    title_odds = {m: float(first[j]) / n * 100 for j, m in enumerate(managers)}
    expected_record = {m: (float(sp.reg_wins[:, j].mean()), float(sp.reg_losses[:, j].mean()),
                           float(sp.reg_ties[:, j].mean())) for j, m in enumerate(managers)}
    finish_distribution = {}
    for j, m in enumerate(managers):
        places = (sp.reg_finish == j).argmax(axis=1)
        counts = np.bincount(places, minlength=NUM_TEAMS)
        finish_distribution[m] = {pos + 1: float(counts[pos]) / n * 100 for pos in range(NUM_TEAMS)}
    magic_numbers = compute_magic_numbers(current_records, sp.remaining_games, title_odds, MANAGERS)
    title_odds_delta = {}
    last_odds = data.records.get("title_odds_history", {}).get(f"week_{current_week - 1}")
    if last_odds:
        for manager in MANAGERS:
            if manager in last_odds:
                title_odds_delta[manager] = title_odds[manager] - last_odds[manager]
    return TitleOddsResult(
        num_simulations=n,
        current_week=current_week,
        title_odds=title_odds,
        expected_record=expected_record,
        finish_distribution=finish_distribution,
        magic_numbers=magic_numbers,
        current_records=current_records,
        h2h_records={m: dict(h) for m, h in sp.current_h2h.items()},
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
