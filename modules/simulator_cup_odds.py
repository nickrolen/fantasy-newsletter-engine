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

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

from .data_loader import SEASON_SIMS
from .data_loader import (
    FantasyData, MANAGERS, CURRENT_SEASON,
    cup_winner, keepers_for, stage_rounds, stage_weeks,
)
from .projections import TeamProjections, load_all_team_projections
from .simulator_betting import week_score_matrices, scores_at
from .simulator_playoff_odds import (
    _matches_seeding, _seeded_pairs, _week_entry, _week_winner,
    resolve_completed_week,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = SEASON_SIMS   # config simulations.season_sims

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

    A tie on total points goes to the better regular-season finish
    (tiebreaker_rules.cup_seeding). This used to break on best single week
    and then on NAME -- a rule nobody made, invented so two runs agreed.
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
    from modules.data_loader import league_rule
    rule = league_rule("tiebreaker_rules", "cup_seeding")
    if rule != "regular_season_finish":
        raise ValueError(f"unknown cup_seeding tiebreak {rule!r}")
    finish = {m: 0 for m in MANAGERS}
    if len(set(totals[m] for m in MANAGERS)) < len(MANAGERS):
        from modules.simulator_playoff_odds import rank_managers_by_standings
        finish = {m: i for i, m in enumerate(rank_managers_by_standings(data))}
    ranked = sorted(MANAGERS, key=lambda m: (-totals[m], finish[m]))
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

def _play_week(pairs, week, seeds, decided, simulated, scores_by_week):
    """One single-elimination week; returns [(winner, loser), ...] per pair.
    `simulated` is this iteration's {week: {manager: score}}; a played week
    (`decided`) is never rolled."""
    if week in decided:
        scores = decided[week]
    elif week in simulated:
        scores = simulated[week]
    else:
        raise KeyError(f"Cup week {week} is neither decided nor simulated")
    scores_by_week[week] = scores

    # The Cup has its own tie rule key; a tied single game goes to the
    # higher seed, same as the bracket but read separately so the two
    # competitions cannot drift onto one shared value.
    from modules.data_loader import league_rule
    tie_rule = league_rule("tiebreaker_rules", "cup_game")

    out = []
    for pair in pairs:
        winner = _week_winner(pair, scores, seeds, tie_rule)
        out.append((winner, pair[1] if winner == pair[0] else pair[0]))
    return out


def simulate_cup(
    semi_pairs: list,
    seeds: dict,
    simulated: dict,
    decided: dict = None,
) -> CupSimResult:
    """Play one Cup: the two semifinals, then the final.

    The two managers knocked out in week 22 still play each other in week 23 --
    Yahoo pairs all four every week and the points count toward season
    totals -- but that game decides nothing about the Cup, so it only settles
    3rd from 4th.
    """
    decided = decided or {}
    rounds = cup_rounds()
    scores_by_week = {}

    semi_week = rounds[CUP_SEMIFINAL_ROUND][0]
    semis = _play_week(semi_pairs, semi_week, seeds, decided, simulated, scores_by_week)
    semi_winners = [w for w, _ in semis]
    semi_losers = [l for _, l in semis]

    final_week = rounds[CUP_FINAL_ROUND][0]
    final_pairs = [tuple(semi_winners), tuple(semi_losers)]
    finals = _play_week(final_pairs, final_week, seeds, decided, simulated, scores_by_week)
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
    """The Cup: a READOUT of the season pass (season_sim.run_season), and what
    each manager is playing for. Every iteration seeds its Cup on THAT
    iteration's points over weeks 1-21, ties to the better regular-season
    finish. seed is required: the run's one seed."""
    if seed is None:
        raise ValueError("run_cup_odds_simulation needs an explicit seed: one seed per run, chosen by the caller (generate_stats_report picks it) so every simulator prices the same week from the same draws")
    _require_cup()
    from .season_sim import run_season
    return run_season(data, num_simulations, seed, injury_statuses, through="cup").cup_result()


def _require_cup():
    rounds = cup_rounds()
    if not rounds:
        raise ValueError(
            f"{CURRENT_SEASON} has no Cup configured. The Cup starts in "
            "2026-27; for an earlier season there is nothing to simulate. "
            "See postseason_format in config/league_config.json.")
    for required in (CUP_SEMIFINAL_ROUND, CUP_FINAL_ROUND):
        if required not in rounds:
            raise ValueError(f"postseason_format.cup is missing '{required}'")
    return rounds


def keeper_stakes() -> dict:
    """What the Cup is for: the winner keeps one more player next season."""
    next_season = _next_season(CURRENT_SEASON)
    base = keepers_for(next_season)
    return {
        "season_affected": next_season,
        "base_keepers": min(base.values()) if base else None,
        "winner_keepers": (min(base.values()) + 1) if base else None,
        "recorded_winner": cup_winner(CURRENT_SEASON),
        "note": ("Record the winner in league_config keeper_rules.cup_winners "
                 f"['{CURRENT_SEASON}'] or the {next_season} draft will be "
                 "built with one keeper missing."),
    }


def cup_readout(sp) -> CupOddsResult:
    """CupOddsResult from a season pass. seeds / semi_matchups describe the
    MOST LIKELY Cup bracket (share in pairing_probability, win probabilities
    conditional on it); seeding_points is each manager's expected points over
    the seeding window -- his actual total once weeks 1-21 are played."""
    import numpy as np
    from .simulator_playoff_odds import modal_seeding
    rounds = _require_cup()
    data, n, managers = sp.data, sp.num_simulations, sp.managers
    wins = np.bincount(sp.cup_finish[:, 0], minlength=len(managers))
    cup_odds = {m: float(wins[j]) / n * 100 for j, m in enumerate(managers)}
    finish = {}
    for j, m in enumerate(managers):
        places = (sp.cup_finish == j).argmax(axis=1)
        counts = np.bincount(places, minlength=4)
        finish[m] = {pos + 1: float(counts[pos]) / n * 100 for pos in range(4)}
    seeds, share, mask = modal_seeding(sp.cup_seeds, managers)
    seed_pairs = [[1, 4], [2, 3]]
    for rnd in stage_rounds(CURRENT_SEASON, "cup"):
        if rnd["name"] == CUP_SEMIFINAL_ROUND:
            seed_pairs = rnd.get("seeds", seed_pairs)
            break
    source = ("points over weeks 1-21" if share == 1.0 else
              f"season pass: the most likely Cup bracket, {share:.1%} of simulated seasons")
    winners_in = sp.cup_semi_winners[mask]
    semi_matchups = []
    for a, b in _seeded_pairs(seeds, seed_pairs):
        ia, ib = managers.index(a), managers.index(b)
        semi_matchups.append({
            "manager_a": a, "manager_b": b,
            "win_prob_a": round(float((winners_in == ia).any(axis=1).mean()) * 100, 1),
            "win_prob_b": round(float((winners_in == ib).any(axis=1).mean()) * 100, 1),
            "seed_a": seeds[a], "seed_b": seeds[b],
            "weeks": list(rounds[CUP_SEMIFINAL_ROUND]),
            "format": "single game",
            "pairing_source": source,
            "pairing_probability": round(share * 100, 1),
        })
    cup_odds_delta = {}
    last = data.records.get("cup_odds_history", {}).get(f"week_{sp.current_week - 1}")
    if isinstance(last, dict):
        for m in MANAGERS:
            if m in last:
                cup_odds_delta[m] = cup_odds[m] - last[m]
    weeks_counted = max(len(cup_weeks()), 1)
    return CupOddsResult(
        num_simulations=n,
        current_week=sp.current_week,
        cup_round=cup_round_for_week(sp.current_week),
        cup_odds=cup_odds,
        finish_distribution=finish,
        semi_matchups=semi_matchups,
        seeds=seeds,
        seeding_points={m: float(sp.cup_points[:, j].mean()) for j, m in enumerate(managers)},
        seeding_weeks=cup_seeding_weeks(),
        round_weeks={nm: list(w) for nm, w in rounds.items()},
        keeper_stakes=keeper_stakes(),
        expected_scores={m: float(sp.cup_week_points[:, j].mean()) / weeks_counted
                         for j, m in enumerate(managers)},
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
