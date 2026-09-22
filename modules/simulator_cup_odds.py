"""
simulator_cup_odds.py

Monte Carlo simulation for the CUP -- the third and last competition of the
season, new in 2026-27.

    weeks 22-23   single elimination, four managers
                  wk22  #1 vs #4 and #2 vs #3
                  wk23  the two winners play for the Cup

WHAT MAKES THE CUP DIFFERENT FROM THE BRACKET
---------------------------------------------
1. SEEDING IS BY POINTS, NOT BY RECORD. The Cup is seeded on total points
   scored across weeks 1-21 -- the regular season AND the playoff bracket.
   A manager who missed the final can still be the #1 Cup seed.
2. SINGLE GAMES, NOT SERIES. One week per round, so a single bad week ends
   it. The playoff bracket is best-of-3; the Cup is not.
3. THE PRIZE IS A KEEPER, NOT MONEY. The winner keeps a sixth player the
   FOLLOWING season, while everyone else keeps five. That is the only place
   in the league where a result changes next year's rules, so the winner has
   to be recorded in league_config keeper_rules.cup_winners -- see
   data_loader.keepers_for(), which will not guess.

Week numbers and pairings come from league_config.postseason_format via
data_loader, never from constants here.
"""

import random
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

from .data_loader import (
    FantasyData, MANAGERS, CURRENT_SEASON,
    cup_winner, keepers_for, stage_rounds, stage_weeks,
)
from .projections import TeamProjections, load_all_team_projections
from .simulator_betting import simulate_week_hifi
from .simulator_playoff_odds import (
    _matches_seeding, _seeded_pairs, _week_entry, _week_winner,
    resolve_completed_week,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = 10000

CUP_SEMIFINAL_ROUND = "Cup Semifinals"
CUP_FINAL_ROUND = "Cup Final"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CupSimResult:
    """One simulated Cup."""
    semi_winners: list[str]
    semi_losers: list[str]
    cup_winner: str
    runner_up: str
    finish_order: list[str]
    scores_by_week: dict = field(default_factory=dict)


@dataclass
class CupOddsResult:
    """Complete Cup odds simulation results."""
    num_simulations: int
    current_week: int
    cup_round: str  # "pre_cup", "semifinals", "final", "complete"

    cup_odds: dict[str, float]                        # manager -> % chance of the Cup
    finish_distribution: dict[str, dict[int, float]]  # manager -> {1: %, ...}
    semi_matchups: list[dict]

    seeds: dict[str, int]          # manager -> Cup seed (1-4)
    seeding_points: dict[str, float]  # the totals the seeding came from
    seeding_weeks: tuple = (1, 0)     # inclusive window those totals cover
    round_weeks: dict = field(default_factory=dict)

    # What the Cup is actually for.
    keeper_stakes: dict = field(default_factory=dict)

    expected_scores: dict = field(default_factory=dict)
    cup_odds_delta: dict = field(default_factory=dict)


# =============================================================================
# SEEDING
# =============================================================================

def cup_seeding_weeks(season: str = None) -> tuple:
    """Inclusive (first, last) week the Cup seeding is computed over.

    Everything before the Cup starts: the regular season plus the playoff
    bracket. Derived rather than written down so it follows the format.
    """
    season = season or CURRENT_SEASON
    cup = stage_weeks(season, "cup")
    if not cup:
        return (1, 0)
    return (1, cup[0] - 1)


def cup_seeding_points(data: FantasyData, season: str = None) -> dict:
    """{manager: total points} over the Cup seeding window.

    Deliberately NOT the same as the standings: the Cup does not care who won
    their matchups, only who scored.
    """
    first, last = cup_seeding_weeks(season)
    totals = {m: 0.0 for m in MANAGERS}
    for manager, entries in data.records.get("weekly_scores", {}).items():
        if manager not in totals or not isinstance(entries, list):
            continue
        for entry in entries:
            week = entry.get("week")
            if week is not None and first <= week <= last:
                totals[manager] += entry.get("score", 0.0) or 0.0
    return totals


def get_cup_seeds(data: FantasyData, season: str = None) -> dict:
    """{manager: seed} with 1 = most points over weeks 1..cup_start-1.

    Ties break on the manager's single best week in the window, then on name
    so the result is at least stable. An exact tie on season-long fractional
    points is not a real scenario; the rule exists so two runs agree.
    """
    totals = cup_seeding_points(data, season)
    first, last = cup_seeding_weeks(season)
    best_week = {m: 0.0 for m in MANAGERS}
    for manager, entries in data.records.get("weekly_scores", {}).items():
        if manager not in best_week or not isinstance(entries, list):
            continue
        for entry in entries:
            week = entry.get("week")
            if week is not None and first <= week <= last:
                best_week[manager] = max(best_week[manager], entry.get("score", 0.0) or 0.0)
    ranked = sorted(MANAGERS, key=lambda m: (-totals[m], -best_week[m], m))
    return {m: i for i, m in enumerate(ranked, 1)}


# =============================================================================
# BRACKET SHAPE
# =============================================================================

def cup_rounds(season: str = None) -> dict:
    """{round_name: (first_week, last_week)} for the Cup, empty if none."""
    season = season or CURRENT_SEASON
    return {r["name"]: r["weeks"] for r in stage_rounds(season, "cup")}


def cup_weeks(season: str = None) -> list[int]:
    span = stage_weeks(season or CURRENT_SEASON, "cup")
    return list(range(span[0], span[1] + 1)) if span else []


def get_cup_semifinal_matchups(data: FantasyData, seeds: dict = None) -> list[dict]:
    """The two week-22 pairings, and where they came from.

    Same rule as the bracket: the schedule wins only when it already holds the
    seeded Cup pairing. The Cup is seeded on POINTS, so Yahoo could not have
    generated it even if it wanted to.
    """
    rounds = cup_rounds()
    if CUP_SEMIFINAL_ROUND not in rounds:
        return [], "no Cup configured"

    seed_pairs = [[1, 4], [2, 3]]
    for rnd in stage_rounds(CURRENT_SEASON, "cup"):
        if rnd["name"] == CUP_SEMIFINAL_ROUND:
            seed_pairs = rnd.get("seeds", seed_pairs)
            break

    seeds = seeds or get_cup_seeds(data)
    first_week = rounds[CUP_SEMIFINAL_ROUND][0]
    entry = _week_entry(data, first_week)
    scheduled = [(m["manager_a"], m["manager_b"])
                 for m in (entry or {}).get("matchups", [])]
    if scheduled and _matches_seeding(scheduled, seeds, seed_pairs):
        return ([{"manager_a": a, "manager_b": b} for a, b in scheduled],
                f"SCHEDULE.json week {first_week}")

    pairs = [{"manager_a": a, "manager_b": b}
             for a, b in _seeded_pairs(seeds, seed_pairs)]
    why = ("points seeding (the schedule has no Cup bracket yet)"
           if not scheduled else
           f"points seeding -- SCHEDULE.json week {first_week} holds "
           f"{scheduled}, which is not the seeded Cup bracket")
    return pairs, why


def cup_round_for_week(week: int, season: str = None) -> str:
    rounds = cup_rounds(season)
    if not rounds:
        return "pre_cup"
    semi = rounds.get(CUP_SEMIFINAL_ROUND)
    final = rounds.get(CUP_FINAL_ROUND)
    if semi and week < semi[0]:
        return "pre_cup"
    if semi and semi[0] <= week <= semi[1]:
        return "semifinals"
    if final and final[0] <= week <= final[1]:
        return "final"
    return "complete"


# =============================================================================
# SIMULATION CORE
# =============================================================================

def _play_week(data, team_projections, pairs, week, seeds, decided,
               injury_statuses, scores_by_week):
    """One single-elimination week; returns [(winner, loser), ...] per pair."""
    simulated = week not in decided
    if simulated:
        entry = _week_entry(data, week) or {"week": week}
        week_data = dict(entry)
        week_data["week"] = week
        week_data["matchups"] = [{"manager_a": a, "manager_b": b} for a, b in pairs]
        results = simulate_week_hifi(data, team_projections, week_data, injury_statuses)
        scores = {m: results[m]["score"] for m in MANAGERS}
    else:
        scores = decided[week]
    scores_by_week[week] = scores

    out = []
    for pair in pairs:
        winner = _week_winner(pair, scores, seeds, simulated)
        out.append((winner, pair[1] if winner == pair[0] else pair[0]))
    return out


def simulate_cup(
    data: FantasyData,
    team_projections: dict,
    semi_pairs: list,
    seeds: dict,
    decided: dict = None,
    injury_statuses: dict[str, str] = None,
) -> CupSimResult:
    """Simulate one Cup: the two semifinals, then the final.

    The two managers knocked out in week 22 still play each other in week 23 --
    Yahoo pairs all four every week and the points count toward season
    totals -- but that game decides nothing about the Cup, so it only settles
    3rd from 4th.
    """
    decided = decided or {}
    rounds = cup_rounds()
    scores_by_week = {}

    semi_week = rounds[CUP_SEMIFINAL_ROUND][0]
    semis = _play_week(data, team_projections, semi_pairs, semi_week,
                       seeds, decided, injury_statuses, scores_by_week)
    semi_winners = [w for w, _ in semis]
    semi_losers = [l for _, l in semis]

    final_week = rounds[CUP_FINAL_ROUND][0]
    final_pairs = [tuple(semi_winners), tuple(semi_losers)]
    finals = _play_week(data, team_projections, final_pairs, final_week,
                        seeds, decided, injury_statuses, scores_by_week)
    winner, runner_up = finals[0]
    third, fourth = finals[1]

    return CupSimResult(
        semi_winners=semi_winners,
        semi_losers=semi_losers,
        cup_winner=winner,
        runner_up=runner_up,
        finish_order=[winner, runner_up, third, fourth],
        scores_by_week=scores_by_week,
    )


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def run_cup_odds_simulation(
    data: FantasyData,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    seed: int = None,
    injury_statuses: dict[str, str] = None,
) -> CupOddsResult:
    """Monte Carlo the Cup, and report what each manager is playing for."""
    if seed is not None:
        random.seed(seed)

    rounds = cup_rounds()
    if not rounds:
        raise ValueError(
            f"{CURRENT_SEASON} has no Cup configured. The Cup starts in "
            "2026-27; for an earlier season there is nothing to simulate. "
            "See postseason_format in config/league_config.json.")
    for required in (CUP_SEMIFINAL_ROUND, CUP_FINAL_ROUND):
        if required not in rounds:
            raise ValueError(f"postseason_format.cup is missing '{required}'")

    current_week = data.current_week
    team_projections = load_all_team_projections(data)

    seeds = get_cup_seeds(data)
    points = cup_seeding_points(data)
    semi_dicts, pairing_source = get_cup_semifinal_matchups(data, seeds)
    if len(semi_dicts) != 2:
        raise ValueError(f"expected 2 Cup semifinals, got {len(semi_dicts)}")
    semi_pairs = [(m["manager_a"], m["manager_b"]) for m in semi_dicts]

    decided = {}
    for week in cup_weeks():
        scores = resolve_completed_week(data, week)
        if scores:
            decided[week] = scores

    cup_wins = {m: 0 for m in MANAGERS}
    semi_wins = {m: 0 for m in MANAGERS}
    finish_counts = {m: {1: 0, 2: 0, 3: 0, 4: 0} for m in MANAGERS}
    score_totals = {m: 0.0 for m in MANAGERS}

    for _ in range(num_simulations):
        result = simulate_cup(data, team_projections, semi_pairs, seeds,
                              decided=decided, injury_statuses=injury_statuses)
        cup_wins[result.cup_winner] += 1
        for w in result.semi_winners:
            semi_wins[w] += 1
        for pos, manager in enumerate(result.finish_order, 1):
            finish_counts[manager][pos] += 1
        for week_scores in result.scores_by_week.values():
            for m in MANAGERS:
                score_totals[m] += week_scores.get(m, 0.0)

    cup_odds = {m: (cup_wins[m] / num_simulations) * 100 for m in MANAGERS}

    semi_matchups = []
    for (ma, mb) in semi_pairs:
        semi_matchups.append({
            "manager_a": ma, "manager_b": mb,
            "win_prob_a": round((semi_wins[ma] / num_simulations) * 100, 1),
            "win_prob_b": round((semi_wins[mb] / num_simulations) * 100, 1),
            "seed_a": seeds[ma], "seed_b": seeds[mb],
            "weeks": list(rounds[CUP_SEMIFINAL_ROUND]),
            "format": "single game",
            "pairing_source": pairing_source,
        })

    # What the Cup is for: the winner keeps one more player next season.
    next_season = _next_season(CURRENT_SEASON)
    base = keepers_for(next_season)
    keeper_stakes = {
        "season_affected": next_season,
        "base_keepers": min(base.values()) if base else None,
        "winner_keepers": (min(base.values()) + 1) if base else None,
        "recorded_winner": cup_winner(CURRENT_SEASON),
        "note": ("Record the winner in league_config keeper_rules.cup_winners "
                 f"['{CURRENT_SEASON}'] or the {next_season} draft will be "
                 "built with one keeper missing."),
    }

    cup_odds_delta = {}
    history = data.records.get("cup_odds_history", {})
    last = history.get(f"week_{current_week - 1}")
    if isinstance(last, dict):
        for m in MANAGERS:
            if m in last:
                cup_odds_delta[m] = cup_odds[m] - last[m]

    weeks_counted = max(len(cup_weeks()), 1)
    return CupOddsResult(
        num_simulations=num_simulations,
        current_week=current_week,
        cup_round=cup_round_for_week(current_week),
        cup_odds=cup_odds,
        finish_distribution={
            m: {pos: (c / num_simulations) * 100 for pos, c in positions.items()}
            for m, positions in finish_counts.items()
        },
        semi_matchups=semi_matchups,
        seeds=seeds,
        seeding_points=points,
        seeding_weeks=cup_seeding_weeks(),
        round_weeks={name: list(weeks) for name, weeks in rounds.items()},
        keeper_stakes=keeper_stakes,
        expected_scores={m: score_totals[m] / (num_simulations * weeks_counted)
                         for m in MANAGERS},
        cup_odds_delta=cup_odds_delta,
    )


def _next_season(season: str) -> str:
    """"2026-27" -> "2027-28"."""
    import re
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(season))
    if not match:
        return ""
    start = int(match.group(1)) + 1
    return f"{start}-{(start + 1) % 100:02d}"


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_cup_odds_table(result: CupOddsResult) -> str:
    lines = []
    lines.append("CUP ODDS")
    lines.append("=" * 60)
    lines.append("")
    lines.append("SEEDING -- total points, weeks {}-{} (record does not count):".format(
        *cup_seeding_weeks()))
    lines.append("-" * 40)
    for m in sorted(MANAGERS, key=lambda m: result.seeds[m]):
        lines.append(f"  #{result.seeds[m]} {m}: {result.seeding_points[m]:,.1f} pts")
    lines.append("")

    lines.append("CUP SEMIFINALS (Week {}):".format(
        result.round_weeks.get(CUP_SEMIFINAL_ROUND, ["?"])[0]))
    lines.append("-" * 40)
    for semi in result.semi_matchups:
        lines.append(
            f"  #{semi['seed_a']} {semi['manager_a']} ({semi['win_prob_a']:.1f}%) vs "
            f"#{semi['seed_b']} {semi['manager_b']} ({semi['win_prob_b']:.1f}%)")
    lines.append("")

    lines.append("CUP PROBABILITY:")
    lines.append("-" * 40)
    for m in sorted(MANAGERS, key=lambda m: result.cup_odds[m], reverse=True):
        delta = result.cup_odds_delta.get(m)
        delta_str = f" ({delta:+.1f}%)" if delta is not None else ""
        lines.append(f"  #{result.seeds[m]} {m}: {result.cup_odds[m]:.1f}%{delta_str}")
    lines.append("")

    stakes = result.keeper_stakes
    lines.append("AT STAKE:")
    lines.append("-" * 40)
    lines.append(f"  The winner keeps {stakes.get('winner_keepers')} players in "
                 f"{stakes.get('season_affected')}; everyone else keeps "
                 f"{stakes.get('base_keepers')}.")
    lines.append(f"  Winner drafts rounds 1-9; the other three draft 1-10.")
    return "\n".join(lines)


if __name__ == "__main__":
    print("Cup rounds:", cup_rounds())
    print("Seeding window:", cup_seeding_weeks())
