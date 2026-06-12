"""
simulator_playoff_odds.py

Monte Carlo simulation for PLAYOFF championship odds.
Runs N simulations of the 2-week playoff bracket (semifinals + finals)
to produce championship probability, finish distribution (1st-4th),
and matchup win probabilities for each team.

Uses the same high-fidelity simulation engine as the betting lines
(simulator_betting.py): day-by-day NBA schedule, position-aware lineups,
injury overrides, partial returns, and Yahoo injury statuses.

Architecture:
  - Semifinal matchups come from SCHEDULE.json week 22.
  - Finals matchups are determined dynamically: semi winners play for
    the championship, semi losers play the consolation game.
"""

import random
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

from .data_loader import (
    FantasyData, MANAGERS,
    REGULAR_SEASON_WEEKS, PLAYOFF_START_WEEK, TOTAL_WEEKS,
    TIEBREAKER_RULES,
)
from .projections import (
    TeamProjections,
    load_all_team_projections,
)
from .simulator_betting import simulate_week_hifi


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = 10000
SEMIFINAL_WEEK = PLAYOFF_START_WEEK
FINALS_WEEK = TOTAL_WEEKS


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PlayoffSimResult:
    """Result of one simulated playoff bracket."""
    # Semifinal results
    semi_scores: dict  # {manager: score} for each semi
    semi_winners: list[str]  # 2 winners
    semi_losers: list[str]   # 2 losers
    
    # Finals results
    champ_winner: str
    champ_loser: str
    consolation_winner: str
    consolation_loser: str
    
    # Final placement 1-4
    finish_order: list[str]  # [1st, 2nd, 3rd, 4th]
    
    # Week-23 (finals week) scores for all managers, {manager: score}
    final_scores: dict


@dataclass
class PlayoffOddsResult:
    """Complete playoff odds simulation results."""
    num_simulations: int
    current_week: int
    playoff_round: str  # "pre_semis", "pre_finals"
    
    # Core results -- same interface as TitleOddsResult for compatibility
    title_odds: dict[str, float]         # manager -> % chance of winning championship
    finish_distribution: dict[str, dict[int, float]]  # manager -> {1: %, 2: %, 3: %, 4: %}
    
    # Semifinal matchup probabilities
    semi_matchups: list[dict]  # [{manager_a, manager_b, win_prob_a, win_prob_b, seed_a, seed_b}]
    
    # Championship game probability (who's most likely to meet in the finals)
    championship_matchup_probs: dict[str, float]  # "A_vs_B" -> probability they meet in finals
    
    # Expected scores per round
    expected_semi_scores: dict[str, float]  # manager -> avg simulated semi score
    expected_final_scores: dict[str, float]  # manager -> avg simulated final score (when they make it)
    
    # Regular season records (for context)
    current_records: dict[str, tuple[int, int]]
    
    # Seeding
    seeds: dict[str, int]  # manager -> seed (1-4)
    
    # Change from last week (if available)
    title_odds_delta: dict[str, float] = field(default_factory=dict)
    
    # Compatibility fields so power_rankings can consume this
    expected_record: dict[str, tuple[float, float]] = field(default_factory=dict)
    magic_numbers: dict[str, Optional[int]] = field(default_factory=dict)
    h2h_records: dict[str, dict[str, int]] = field(default_factory=dict)
    title_odds_history: dict = field(default_factory=dict)


# =============================================================================
# HELPERS
# =============================================================================

def _regular_season_standings(data: FantasyData) -> dict:
    """
    Compute each manager's record and total points over the REGULAR SEASON
    only (weeks 1..regular_season_weeks), from RECORDS weekly_scores +
    SCHEDULE matchups.

    Playoff results must not influence seeding, so we deliberately ignore any
    week beyond regular_season_weeks. Returns {manager: {wins, losses, points}}.
    """
    reg_weeks = data.schedule.get("regular_season_weeks", SEMIFINAL_WEEK - 1)
    weekly_scores = data.records.get("weekly_scores", {})

    # Build {week: {manager: score}} for regular-season weeks only.
    scores_by_week = defaultdict(dict)
    for mgr, entries in weekly_scores.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            wk = e.get("week")
            if wk is not None and wk <= reg_weeks:
                scores_by_week[wk][mgr] = e.get("score", 0.0)

    standings = {m: {"wins": 0, "losses": 0, "points": 0.0} for m in MANAGERS}
    for wk, mgr_scores in scores_by_week.items():
        for m, s in mgr_scores.items():
            if m in standings:
                standings[m]["points"] += s
        for matchup in data.get_week_matchups(wk):
            ma, mb = matchup["manager_a"], matchup["manager_b"]
            sa, sb = mgr_scores.get(ma), mgr_scores.get(mb)
            if sa is None or sb is None:
                continue
            if sa > sb:
                standings[ma]["wins"] += 1
                standings[mb]["losses"] += 1
            elif sb > sa:
                standings[mb]["wins"] += 1
                standings[ma]["losses"] += 1
    return standings


def _h2h_records_within_group(
    data: FantasyData, group: list[str]
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Compute head-to-head wins/losses among a tied group of managers, using
    ONLY regular-season matchups between members of the group.

    Returns (h2h_wins, h2h_games) keyed by manager. Matchups against
    managers outside the group are ignored -- the rule is "record between
    the tied managers," not overall record.
    """
    reg_weeks = data.schedule.get("regular_season_weeks", REGULAR_SEASON_WEEKS)
    weekly_scores = data.records.get("weekly_scores", {})

    scores_by_week: dict[int, dict[str, float]] = defaultdict(dict)
    for mgr, entries in weekly_scores.items():
        if not isinstance(entries, list):
            continue
        for e in entries:
            wk = e.get("week")
            if wk is not None and wk <= reg_weeks:
                scores_by_week[wk][mgr] = e.get("score", 0.0)

    group_set = set(group)
    h2h_wins = {m: 0 for m in group}
    h2h_games = {m: 0 for m in group}
    for wk, mgr_scores in scores_by_week.items():
        for matchup in data.get_week_matchups(wk):
            ma, mb = matchup["manager_a"], matchup["manager_b"]
            if ma not in group_set or mb not in group_set:
                continue
            sa, sb = mgr_scores.get(ma), mgr_scores.get(mb)
            if sa is None or sb is None:
                continue
            h2h_games[ma] += 1
            h2h_games[mb] += 1
            if sa > sb:
                h2h_wins[ma] += 1
            elif sb > sa:
                h2h_wins[mb] += 1
    return h2h_wins, h2h_games


def rank_managers_by_standings(data: FantasyData) -> list[str]:
    """
    Rank managers in standings order using the configured tiebreaker rules
    from league_config.json:

        {"standings": "h2h_regular_season", "fallback": "total_points"}

    Order: regular-season wins DESC, then (within ties) the configured
    standings rule, then the fallback. Always returns regular-season only --
    playoff weeks never influence seeding.

    The H2H rule uses each tied manager's record against the OTHER tied
    managers only (not their overall H2H), which is the conventional
    interpretation of "head-to-head among tied teams."
    """
    reg = _regular_season_standings(data)

    # If no regular-season scores yet, fall back to live records via the
    # data_loader path (e.g. preseason or very early in the year).
    if all(reg[m]["wins"] == 0 and reg[m]["losses"] == 0 for m in MANAGERS):
        season_totals = data.records.get("manager_season_totals", {})
        live = []
        for manager in MANAGERS:
            wins, _ = data.get_manager_record(manager)
            total_pts = season_totals.get(manager, {}).get("total_points", 0.0)
            live.append((manager, wins, total_pts))
        live.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [m for m, _, _ in live]

    standings_rule = TIEBREAKER_RULES.get("standings", "h2h_regular_season")
    fallback_rule = TIEBREAKER_RULES.get("fallback", "total_points")

    # Group managers by win count.
    by_wins: dict[int, list[str]] = defaultdict(list)
    for m in MANAGERS:
        by_wins[reg[m]["wins"]].append(m)

    ordered: list[str] = []
    for wins in sorted(by_wins.keys(), reverse=True):
        tied = by_wins[wins]
        if len(tied) == 1:
            ordered.extend(tied)
            continue

        # Break ties.
        if standings_rule == "h2h_regular_season":
            h2h_wins, _ = _h2h_records_within_group(data, tied)
        else:
            h2h_wins = {m: 0 for m in tied}

        if fallback_rule == "total_points":
            fallback_val = {m: reg[m]["points"] for m in tied}
        else:
            fallback_val = {m: 0.0 for m in tied}

        tied.sort(key=lambda m: (h2h_wins[m], fallback_val[m]), reverse=True)
        ordered.extend(tied)
    return ordered


def get_playoff_seeds(data: FantasyData) -> dict[str, int]:
    """
    Determine playoff seeding from the FINAL REGULAR SEASON standings.

    Seeds are frozen at the end of the regular season -- playoff wins and
    losses must NOT change them.

    Returns dict mapping manager -> seed (1=best record, 4=worst).
    Tiebreakers follow tiebreaker_rules in league_config.json (default:
    head-to-head regular-season series, then total points).
    """
    ranked = rank_managers_by_standings(data)
    return {mgr: seed for seed, mgr in enumerate(ranked, 1)}


def get_semifinal_matchups(data: FantasyData) -> list[dict]:
    """
    Get semifinal matchups from SCHEDULE.json week 22.
    
    Returns list of 2 matchup dicts with manager_a, manager_b keys.
    """
    for week_data in data.schedule.get("weeks", []):
        if week_data["week"] == SEMIFINAL_WEEK:
            return week_data["matchups"]
    return []


def get_completed_week_results(data: FantasyData, week_data: dict):
    """
    Read the ACTUAL results of a COMPLETED playoff week from the game logs.

    Uses compute_weekly_report (the same scoring logic the rest of the
    pipeline uses) so the locked-in results match the matchup recaps exactly.

    Returns (winners, losers, scores):
      - winners: [winner of matchup 0, winner of matchup 1]
      - losers:  [loser of matchup 0,  loser of matchup 1]
      - scores:  {manager: actual_score}
    Order follows week_data["matchups"] so finals seeding stays consistent.
    """
    # Lazy import avoids a circular import: report_builder imports this module
    # at load time, so we can only import it back here inside the function.
    from .report_builder import compute_weekly_report

    report = compute_weekly_report(data, week_data["week"])
    score_lookup = {}
    for m in report.matchups:
        score_lookup[(m.manager_a, m.manager_b)] = (m.score_a, m.score_b)

    winners, losers, scores = [], [], {}
    for matchup in week_data["matchups"]:
        ma, mb = matchup["manager_a"], matchup["manager_b"]
        if (ma, mb) in score_lookup:
            sa, sb = score_lookup[(ma, mb)]
        elif (mb, ma) in score_lookup:
            sb, sa = score_lookup[(mb, ma)]
        else:
            sa = sb = 0.0
        scores[ma], scores[mb] = sa, sb
        # Tie convention for ACTUAL completed games: manager_a wins.
        # In SCHEDULE.json, manager_a is the higher seed for playoff matchups,
        # so this is equivalent to "higher seed wins" -- which is the standard
        # tiebreaker for completed playoff games. Real ties are essentially
        # impossible with fractional scoring; the rule exists for consistency.
        if sa >= sb:
            winners.append(ma)
            losers.append(mb)
        else:
            winners.append(mb)
            losers.append(ma)
    return winners, losers, scores


# =============================================================================
# SIMULATION CORE
# =============================================================================

def simulate_playoff_bracket(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    semi_week_data: dict,
    finals_week_data: dict,
    injury_statuses: dict[str, str] = None,
    fixed_semis: tuple = None,
    fixed_finals: tuple = None,
) -> PlayoffSimResult:
    """
    Simulate one complete playoff bracket (semis + finals).
    
    Uses the same high-fidelity simulation as the betting lines:
    day-by-day NBA schedule, injury overrides, partial returns,
    and Yahoo injury status checks.
    
    The semis use the matchups from SCHEDULE.json week 22.
    The finals are determined dynamically: semi winners play the
    championship, semi losers play the consolation game.

    If fixed_semis is provided (winners, losers, scores), the semifinals
    are treated as already decided -- they are NOT re-simulated. This is
    used once the semifinals have actually been played (the pre_finals
    round), so only the finals are randomized.
    """
    # --- Semifinals (Week 22) ---
    if fixed_semis is not None:
        # Semifinals already complete: use real results, don't re-roll them.
        semi_winners, semi_losers, semi_scores = fixed_semis
    else:
        # Semifinals not yet played (pre_semis preview): simulate them.
        semi_results = simulate_week_hifi(
            data, team_projections, semi_week_data, injury_statuses
        )

        semi_scores = {m: semi_results[m]["score"] for m in MANAGERS}

        # Determine semi winners/losers from the simulated scores
        semi_winners = []
        semi_losers = []
        for matchup in semi_week_data["matchups"]:
            ma = matchup["manager_a"]
            mb = matchup["manager_b"]
            if semi_scores[ma] > semi_scores[mb]:
                semi_winners.append(ma)
                semi_losers.append(mb)
            elif semi_scores[mb] > semi_scores[ma]:
                semi_winners.append(mb)
                semi_losers.append(ma)
            else:
                # Exact tie -- coin flip per project-wide SIMULATED-tie
                # convention (extremely rare with fractional scoring).
                winner = random.choice([ma, mb])
                loser = mb if winner == ma else ma
                semi_winners.append(winner)
                semi_losers.append(loser)
    
    # --- Build Finals Matchups (Week 23) ---
    # Championship: semi_winners[0] vs semi_winners[1]
    # Consolation: semi_losers[0] vs semi_losers[1]
    finals_week_dynamic = dict(finals_week_data)  # shallow copy
    finals_week_dynamic["matchups"] = [
        {"manager_a": semi_winners[0], "manager_b": semi_winners[1]},
        {"manager_a": semi_losers[0], "manager_b": semi_losers[1]},
    ]
    
    # --- Finals (Week 23) ---
    if fixed_finals is not None:
        # Finals already complete (post_finals round): use the real results
        # instead of re-simulating a decided championship.
        _, _, finals_scores = fixed_finals
    else:
        finals_results = simulate_week_hifi(
            data, team_projections, finals_week_dynamic, injury_statuses
        )
        finals_scores = {m: finals_results[m]["score"] for m in MANAGERS}
    
    # Championship game
    cw0, cw1 = semi_winners[0], semi_winners[1]
    if finals_scores[cw0] > finals_scores[cw1]:
        champ_winner, champ_loser = cw0, cw1
    elif finals_scores[cw1] > finals_scores[cw0]:
        champ_winner, champ_loser = cw1, cw0
    else:
        champ_winner = random.choice([cw0, cw1])
        champ_loser = cw1 if champ_winner == cw0 else cw0
    
    # Consolation game
    cl0, cl1 = semi_losers[0], semi_losers[1]
    if finals_scores[cl0] > finals_scores[cl1]:
        consolation_winner, consolation_loser = cl0, cl1
    elif finals_scores[cl1] > finals_scores[cl0]:
        consolation_winner, consolation_loser = cl1, cl0
    else:
        consolation_winner = random.choice([cl0, cl1])
        consolation_loser = cl1 if consolation_winner == cl0 else cl0
    
    finish_order = [champ_winner, champ_loser, consolation_winner, consolation_loser]
    
    return PlayoffSimResult(
        semi_scores=semi_scores,
        semi_winners=semi_winners,
        semi_losers=semi_losers,
        final_scores=finals_scores,
        champ_winner=champ_winner,
        champ_loser=champ_loser,
        consolation_winner=consolation_winner,
        consolation_loser=consolation_loser,
        finish_order=finish_order,
    )


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_playoff_odds_simulation(
    data: FantasyData,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    seed: int = None,
    injury_statuses: dict[str, str] = None,
) -> PlayoffOddsResult:
    """
    Run Monte Carlo simulation for playoff championship odds.
    
    Uses the same high-fidelity engine as the betting lines:
    day-by-day NBA schedule, position-aware lineups, injury overrides,
    partial returns, and Yahoo injury status checks.
    
    Simulates the full 2-week bracket N times:
      Week 22 (semis): #1 vs #4, #2 vs #3
      Week 23 (finals): semi winners for championship, semi losers for consolation
    
    Args:
        data: FantasyData container
        num_simulations: Number of bracket simulations to run
        seed: Random seed for reproducibility
        injury_statuses: Player -> injury status mapping (from Yahoo API, optional)
    
    Returns:
        PlayoffOddsResult with championship probabilities and finish distributions
    """
    if seed is not None:
        random.seed(seed)
    
    current_week = data.current_week
    
    # Load projections
    team_projections = load_all_team_projections(data)
    
    # Get the two playoff week schedule entries
    semi_week_data = None
    finals_week_data = None
    for week_data in data.schedule.get("weeks", []):
        if week_data["week"] == SEMIFINAL_WEEK:
            semi_week_data = week_data
        elif week_data["week"] == FINALS_WEEK:
            finals_week_data = week_data
    
    if not semi_week_data or not finals_week_data:
        raise ValueError(
            f"SCHEDULE.json missing playoff weeks. "
            f"Need weeks {SEMIFINAL_WEEK} and {FINALS_WEEK}."
        )
    
    # Get seeds and records
    seeds = get_playoff_seeds(data)
    current_records = {}
    for manager in MANAGERS:
        current_records[manager] = data.get_manager_record(manager)
    
    # Determine playoff round context
    if current_week < SEMIFINAL_WEEK:
        playoff_round = "pre_semis"
    elif current_week == SEMIFINAL_WEEK:
        playoff_round = "pre_finals"
    else:
        playoff_round = "post_finals"

    # If the semifinals have already been played, lock them to their ACTUAL
    # results so we only Monte-Carlo the finals. Without this, decided
    # semifinals get re-rolled on every iteration and eliminated teams
    # wrongly receive championship odds.
    fixed_semis = None
    if playoff_round in ("pre_finals", "post_finals"):
        fixed_semis = get_completed_week_results(data, semi_week_data)

    # For post_finals (the Week 23 recap), the finals are ALSO decided, so
    # lock them too -- the champion should show at 100%, not a re-sim guess.
    fixed_finals = None
    if playoff_round == "post_finals":
        fixed_finals = get_completed_week_results(data, finals_week_data)
    
    # --- Run simulations ---
    title_wins = {m: 0 for m in MANAGERS}
    finish_counts = {m: {1: 0, 2: 0, 3: 0, 4: 0} for m in MANAGERS}
    
    # Track semi win counts for matchup probabilities
    semi_win_counts = {m: 0 for m in MANAGERS}
    
    # Track championship matchup frequency
    champ_matchup_counts = defaultdict(int)
    
    # Track scores for expected score computation
    semi_score_totals = {m: 0.0 for m in MANAGERS}
    final_score_totals = {m: 0.0 for m in MANAGERS}
    final_appearances = {m: 0 for m in MANAGERS}
    
    for sim in range(num_simulations):
        result = simulate_playoff_bracket(
            data, team_projections,
            semi_week_data, finals_week_data,
            injury_statuses,
            fixed_semis=fixed_semis,
            fixed_finals=fixed_finals,
        )
        
        # Title winner
        title_wins[result.champ_winner] += 1
        
        # Finish positions
        for pos, manager in enumerate(result.finish_order, 1):
            finish_counts[manager][pos] += 1
        
        # Semi wins
        for w in result.semi_winners:
            semi_win_counts[w] += 1
        
        # Championship matchup tracking
        champ_key = "_vs_".join(sorted(result.semi_winners))
        champ_matchup_counts[champ_key] += 1
        
        # Score tracking
        for m in MANAGERS:
            semi_score_totals[m] += result.semi_scores[m]
        
        # Finals scores -- only for managers who made the championship game
        for m in result.semi_winners:
            final_appearances[m] += 1
            final_score_totals[m] += result.final_scores[m]
    
    # --- Compute results ---
    title_odds = {m: (title_wins[m] / num_simulations) * 100 for m in MANAGERS}
    
    finish_distribution = {
        m: {pos: (count / num_simulations) * 100 for pos, count in positions.items()}
        for m, positions in finish_counts.items()
    }
    
    # Semifinal matchup probabilities
    semi_matchups = []
    for matchup in semi_week_data["matchups"]:
        ma = matchup["manager_a"]
        mb = matchup["manager_b"]
        win_prob_a = (semi_win_counts[ma] / num_simulations) * 100
        win_prob_b = (semi_win_counts[mb] / num_simulations) * 100
        semi_matchups.append({
            "manager_a": ma,
            "manager_b": mb,
            "win_prob_a": round(win_prob_a, 1),
            "win_prob_b": round(win_prob_b, 1),
            "seed_a": seeds[ma],
            "seed_b": seeds[mb],
        })
    
    # Championship matchup probabilities
    championship_matchup_probs = {
        key: (count / num_simulations) * 100
        for key, count in champ_matchup_counts.items()
    }
    
    # Expected scores
    expected_semi_scores = {
        m: semi_score_totals[m] / num_simulations for m in MANAGERS
    }
    expected_final_scores = {
        m: (final_score_totals[m] / final_appearances[m]) if final_appearances[m] > 0 else 0.0
        for m in MANAGERS
    }
    
    # Delta from last week's title odds (if available)
    title_odds_delta = {}
    last_week_key = f"week_{current_week - 1}"
    if last_week_key in data.records.get("title_odds_history", {}):
        last_odds = data.records["title_odds_history"][last_week_key]
        for manager in MANAGERS:
            if manager in last_odds:
                title_odds_delta[manager] = title_odds[manager] - last_odds[manager]
    
    # Build compatibility fields for power_rankings consumption
    # expected_record stays as the regular season final record
    expected_record = {m: current_records[m] for m in MANAGERS}
    # magic_numbers not applicable in playoffs
    magic_numbers = {m: None for m in MANAGERS}
    
    return PlayoffOddsResult(
        num_simulations=num_simulations,
        current_week=current_week,
        playoff_round=playoff_round,
        title_odds=title_odds,
        finish_distribution=finish_distribution,
        semi_matchups=semi_matchups,
        championship_matchup_probs=championship_matchup_probs,
        expected_semi_scores=expected_semi_scores,
        expected_final_scores=expected_final_scores,
        current_records=current_records,
        seeds=seeds,
        title_odds_delta=title_odds_delta,
        expected_record=expected_record,
        magic_numbers=magic_numbers,
    )


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_playoff_odds_table(result: PlayoffOddsResult) -> str:
    """Format playoff odds as a text table."""
    lines = []
    lines.append("PLAYOFF CHAMPIONSHIP ODDS")
    lines.append("=" * 60)
    lines.append("")

    # Semifinal matchup probabilities
    lines.append("SEMIFINAL MATCHUPS (Week 22):")
    lines.append("-" * 40)
    for semi in result.semi_matchups:
        ma, mb = semi["manager_a"], semi["manager_b"]
        pa, pb = semi["win_prob_a"], semi["win_prob_b"]
        sa, sb = semi["seed_a"], semi["seed_b"]
        lines.append(f"  #{sa} {ma} ({pa:.1f}%) vs #{sb} {mb} ({pb:.1f}%)")
    lines.append("")

    # Championship probabilities
    lines.append("CHAMPIONSHIP PROBABILITY:")
    lines.append("-" * 40)
    sorted_managers = sorted(MANAGERS, key=lambda m: result.title_odds[m], reverse=True)
    for manager in sorted_managers:
        odds = result.title_odds[manager]
        seed = result.seeds[manager]
        dist = result.finish_distribution[manager]
        delta = result.title_odds_delta.get(manager)
        delta_str = f" ({delta:+.1f}%)" if delta is not None else ""
        lines.append(
            f"  #{seed} {manager}: {odds:.1f}%{delta_str}"
            f"  [1st: {dist[1]:.1f}% | 2nd: {dist[2]:.1f}% | 3rd: {dist[3]:.1f}% | 4th: {dist[4]:.1f}%]"
        )
    lines.append("")

    # Most likely championship matchup
    if result.championship_matchup_probs:
        lines.append("MOST LIKELY CHAMPIONSHIP GAME:")
        lines.append("-" * 40)
        sorted_matchups = sorted(
            result.championship_matchup_probs.items(),
            key=lambda x: x[1], reverse=True
        )
        for matchup_key, prob in sorted_matchups:
            m1, m2 = matchup_key.split("_vs_")
            lines.append(f"  {m1} vs {m2}: {prob:.1f}%")

    return "\n".join(lines)


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    week = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    data = load_all_data(Path('.'))
    print(f"Week {week}: playoff odds simulator loaded.")
