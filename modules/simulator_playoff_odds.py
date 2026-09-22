"""
simulator_playoff_odds.py

Monte Carlo simulation for PLAYOFF championship odds.

THE BRACKET IS SIX WEEKS LONG, NOT TWO
--------------------------------------
Through 2025-26 the postseason was two single games: a semifinal week then a
final week, always the last two weeks of the season. From 2026-27 it is:

    weeks 16-18   Semifinals, best-of-3       (#1 vs #4, #2 vs #3)
    weeks 19-21   Final and Third Place, best-of-3
    weeks 22-23   The Cup -- a SEPARATE competition, simulated in
                  simulator_cup_odds.py, not here

Every week of a series is played even after the series is decided, so a 2-0
lead still plays its third week. The series winner is whoever won more of the
three weeks; with three games a series cannot be drawn.

None of those week numbers are written down in this module. They come from
data_loader.stage_weeks()/stage_rounds(), which read league_config's
postseason_format, so the shape can change again in one file.

Seeding comes from the FINAL REGULAR-SEASON standings and is frozen there --
in this league the regular-season winner is the League Champion and the
bracket winner is the separate Playoff Champion, so bracket results must
never feed back into seeding.

Uses the same high-fidelity engine as the betting lines
(simulator_betting.py): day-by-day NBA schedule, position-aware lineups,
injury overrides, partial returns, and Yahoo injury statuses.

COST: a full bracket is six simulated weeks rather than two, so a run is
roughly 3x what it used to be. num_simulations is the knob.
"""

import random
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

from .data_loader import (
    FantasyData, MANAGERS, CURRENT_SEASON,
    REGULAR_SEASON_WEEKS, TIEBREAKER_RULES,
    stage_weeks, stage_rounds, regular_season_weeks_for,
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

# Round names as they appear in league_config.postseason_format.
SEMIFINAL_ROUND = "Semifinals"
FINAL_ROUND = "Final"
THIRD_PLACE_ROUND = "Third Place"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SeriesResult:
    """One best-of-N series inside a simulated bracket."""
    round_name: str
    weeks: tuple            # inclusive (first, last)
    manager_a: str
    manager_b: str
    week_winners: list      # winner of each week, in week order
    winner: str
    loser: str

    @property
    def games(self) -> str:
        """"2-1" from the winner's point of view."""
        won = self.week_winners.count(self.winner)
        return f"{won}-{len(self.week_winners) - won}"


@dataclass
class PlayoffSimResult:
    """Result of one simulated playoff bracket."""
    # Semifinal round. semi_scores is each manager's TOTAL points across the
    # semifinal series, not one week's score -- the old field name is kept so
    # report_builder and the formatters keep working.
    semi_scores: dict
    semi_winners: list[str]
    semi_losers: list[str]

    # Final round
    champ_winner: str
    champ_loser: str
    consolation_winner: str
    consolation_loser: str

    # Final placement 1-4
    finish_order: list[str]

    # Total points across the final round, per manager
    final_scores: dict

    # Full detail: every series played, and every week's scores
    series: list = field(default_factory=list)
    scores_by_week: dict = field(default_factory=dict)


@dataclass
class PlayoffOddsResult:
    """Complete playoff odds simulation results."""
    num_simulations: int
    current_week: int
    playoff_round: str  # "pre_playoffs", "semifinals", "final", "complete"

    # Core results -- same interface as TitleOddsResult for compatibility
    title_odds: dict[str, float]         # manager -> % chance of winning the bracket
    finish_distribution: dict[str, dict[int, float]]  # manager -> {1: %, 2: %, 3: %, 4: %}

    # Semifinal SERIES probabilities (field name kept for compatibility)
    semi_matchups: list[dict]  # [{manager_a, manager_b, win_prob_a, ..., weeks, format}]

    # Which pairing is most likely to meet in the final
    championship_matchup_probs: dict[str, float]  # "A_vs_B" -> probability

    # Expected points per round (series totals, not single weeks)
    expected_semi_scores: dict[str, float]
    expected_final_scores: dict[str, float]

    # Regular season records (for context)
    current_records: dict[str, tuple[int, int]]

    # Seeding
    seeds: dict[str, int]  # manager -> seed (1-4)

    # Bracket shape, so consumers can label weeks without hardcoding them
    round_weeks: dict = field(default_factory=dict)  # {"Semifinals": (16, 18), ...}

    # How often a series goes the distance, per round
    sweep_probability: dict = field(default_factory=dict)  # round -> % ending 2-0... i.e. 3-0

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
    reg_weeks = regular_season_weeks_for(CURRENT_SEASON)
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
    # Not from SCHEDULE.json: seeds must never move on bracket results, and
    # a stale schedule would let weeks 16-21 into the standings that set them.
    reg_weeks = regular_season_weeks_for(CURRENT_SEASON)
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



# =============================================================================
# BRACKET SHAPE
# =============================================================================

def bracket_rounds(season: str = None) -> dict:
    """{round_name: (first_week, last_week)} for the playoff bracket.

    Read from league_config.postseason_format via data_loader, so the six-week
    shape is never written down here. Empty for a season with no bracket
    (2019-20), which callers must treat as "no playoffs to simulate".
    """
    season = season or CURRENT_SEASON
    return {r["name"]: r["weeks"] for r in stage_rounds(season, "playoffs")}


def bracket_weeks(season: str = None) -> list[int]:
    """Every week of the bracket, in order, with no duplicates.

    The Final and the Third Place series run in the SAME weeks, so a plain
    concatenation of round spans double-counts them.
    """
    span = stage_weeks(season or CURRENT_SEASON, "playoffs")
    return list(range(span[0], span[1] + 1)) if span else []


def _week_entry(data: FantasyData, week: int) -> Optional[dict]:
    """The SCHEDULE.json entry for `week`, if it is there."""
    for entry in data.schedule.get("weeks", []):
        if entry.get("week") == week:
            return entry
    return None


def _seeded_pairs(seeds, seed_pairs):
    """[(manager, manager)] for seed pairings like [[1, 4], [2, 3]]."""
    by_seed = {s: m for m, s in seeds.items()}
    out = []
    for sa, sb in seed_pairs:
        if sa in by_seed and sb in by_seed:
            out.append((by_seed[sa], by_seed[sb]))
    return out


def _matches_seeding(pairs, seeds, seed_pairs):
    """True if `pairs` IS the configured seeded bracket, in any order.

    The schedule file is authoritative once the real bracket has been entered
    -- but until then it holds whatever Yahoo generated, which for this league
    is an ordinary round robin. Taking that as the bracket would preview the
    wrong semifinals, with the seed labels visibly contradicting the pairing.
    So the schedule is used only when it actually forms the configured
    bracket; otherwise the seeds win and the result says so.
    """
    want = {frozenset(p) for p in _seeded_pairs(seeds, seed_pairs)}
    got = {frozenset(p) for p in pairs}
    return bool(want) and want == got


def get_semifinal_matchups(data: FantasyData, seeds: dict = None) -> list[dict]:
    """The two semifinal pairings, and where they came from.

    Returns (pairings, source). The schedule wins ONLY when it already holds
    the configured bracket; otherwise the seeding does. See _matches_seeding.
    """
    rounds = bracket_rounds()
    if SEMIFINAL_ROUND not in rounds:
        return [], "no bracket configured"
    first_week = rounds[SEMIFINAL_ROUND][0]

    seed_pairs = [[1, 4], [2, 3]]
    for rnd in stage_rounds(CURRENT_SEASON, "playoffs"):
        if rnd["name"] == SEMIFINAL_ROUND:
            seed_pairs = rnd.get("seeds", seed_pairs)
            break

    seeds = seeds or get_playoff_seeds(data)
    entry = _week_entry(data, first_week)
    scheduled = [(m["manager_a"], m["manager_b"])
                 for m in (entry or {}).get("matchups", [])]
    if scheduled and _matches_seeding(scheduled, seeds, seed_pairs):
        return ([{"manager_a": a, "manager_b": b} for a, b in scheduled],
                f"SCHEDULE.json week {first_week}")

    pairs = [{"manager_a": a, "manager_b": b}
             for a, b in _seeded_pairs(seeds, seed_pairs)]
    why = ("seeding (the schedule has no bracket yet)" if not scheduled else
           f"seeding -- SCHEDULE.json week {first_week} holds "
           f"{scheduled}, which is not the seeded bracket")
    return pairs, why


# =============================================================================
# COMPLETED WEEKS
# =============================================================================

def resolve_completed_week(data: FantasyData, week: int) -> Optional[dict]:
    """Actual {manager: score} for a week that has been played, else None.

    Uses compute_weekly_report -- the same scoring path as the recaps -- so a
    locked-in series matches what the newsletter says happened.

    This replaces the old fixed_semis/fixed_finals pair. With a six-week
    postseason the bracket can be halfway through a series, so "which weeks
    are decided" is a per-week question, not a per-round one. Re-rolling a
    week that has already been played would hand championship odds to a
    manager who is already eliminated.
    """
    if week > data.current_week:
        return None
    # Lazy import avoids a circular import: report_builder imports this module
    # at load time, so we can only import it back here inside the function.
    from .report_builder import compute_weekly_report
    try:
        report = compute_weekly_report(data, week)
    except Exception:
        return None
    scores = {}
    for m in report.matchups:
        scores[m.manager_a] = m.score_a
        scores[m.manager_b] = m.score_b
    return scores or None


def _decided_weeks(data: FantasyData) -> dict:
    """{week: {manager: score}} for every bracket week already played."""
    out = {}
    for week in bracket_weeks():
        scores = resolve_completed_week(data, week)
        if scores:
            out[week] = scores
    return out


# =============================================================================
# SIMULATION CORE
# =============================================================================

def _week_winner(pair, scores, seeds, simulated):
    """Winner of one week of a series.

    Ties: a SIMULATED tie is a coin flip (project-wide convention for
    simulated results); an ACTUAL tie goes to the higher seed, which is the
    standard rule for a played playoff game. Fractional scoring makes both
    essentially impossible -- the rules exist so the same input always gives
    the same answer.
    """
    a, b = pair
    sa, sb = scores.get(a, 0.0), scores.get(b, 0.0)
    if sa > sb:
        return a
    if sb > sa:
        return b
    if simulated:
        return random.choice([a, b])
    return a if seeds.get(a, 99) <= seeds.get(b, 99) else b


def _play_series(data, team_projections, pairs, weeks, seeds, decided,
                 injury_statuses, scores_by_week):
    """Play one round: every week of it, for both pairings at once.

    `pairs` is [(a, b), (c, d)]. Both pairings play in the same weeks, so the
    week is simulated once and read by both. Every week is played even once a
    series is decided -- the league plays them out, and the points still count
    toward season totals and the Cup seeding.

    Returns [(winner, loser, week_winners), ...] in the order of `pairs`.
    """
    first, last = weeks
    tallies = [defaultdict(int) for _ in pairs]
    week_winner_lists = [[] for _ in pairs]

    for week in range(first, last + 1):
        simulated = week not in decided
        if simulated:
            entry = _week_entry(data, week) or {"week": week}
            week_data = dict(entry)
            week_data["week"] = week
            week_data["matchups"] = [
                {"manager_a": a, "manager_b": b} for a, b in pairs
            ]
            results = simulate_week_hifi(
                data, team_projections, week_data, injury_statuses)
            scores = {m: results[m]["score"] for m in MANAGERS}
        else:
            scores = decided[week]
        scores_by_week[week] = scores

        for i, pair in enumerate(pairs):
            winner = _week_winner(pair, scores, seeds, simulated)
            tallies[i][winner] += 1
            week_winner_lists[i].append(winner)

    out = []
    for i, (a, b) in enumerate(pairs):
        winner = a if tallies[i][a] > tallies[i][b] else b
        loser = b if winner == a else a
        out.append((winner, loser, week_winner_lists[i]))
    return out


def simulate_playoff_bracket(
    data: FantasyData,
    team_projections: dict[str, TeamProjections],
    semi_pairs: list,
    seeds: dict,
    decided: dict = None,
    injury_statuses: dict[str, str] = None,
) -> PlayoffSimResult:
    """Simulate one complete playoff bracket: semifinals, then final.

    semi_pairs is [(a, b), (c, d)]. `decided` maps an already-played week to
    its real {manager: score}; those weeks are used as-is rather than rolled
    again, so an eliminated manager cannot pick up championship odds.
    """
    decided = decided or {}
    rounds = bracket_rounds()
    scores_by_week = {}
    series = []

    # --- Semifinals ---
    semi_weeks = rounds[SEMIFINAL_ROUND]
    semi_out = _play_series(data, team_projections, semi_pairs, semi_weeks,
                            seeds, decided, injury_statuses, scores_by_week)
    semi_winners = [w for w, _, _ in semi_out]
    semi_losers = [l for _, l, _ in semi_out]
    for (a, b), (w, l, wk_winners) in zip(semi_pairs, semi_out):
        series.append(SeriesResult(SEMIFINAL_ROUND, semi_weeks, a, b,
                                   wk_winners, w, l))

    semi_scores = {m: 0.0 for m in MANAGERS}
    for week in range(semi_weeks[0], semi_weeks[1] + 1):
        for m in MANAGERS:
            semi_scores[m] += scores_by_week.get(week, {}).get(m, 0.0)

    # --- Final and Third Place (same weeks) ---
    final_weeks = rounds[FINAL_ROUND]
    final_pairs = [tuple(semi_winners), tuple(semi_losers)]
    final_out = _play_series(data, team_projections, final_pairs, final_weeks,
                             seeds, decided, injury_statuses, scores_by_week)

    champ_winner, champ_loser, champ_weeks = final_out[0]
    consolation_winner, consolation_loser, cons_weeks = final_out[1]
    series.append(SeriesResult(FINAL_ROUND, final_weeks, *final_pairs[0],
                               champ_weeks, champ_winner, champ_loser))
    series.append(SeriesResult(THIRD_PLACE_ROUND, final_weeks, *final_pairs[1],
                               cons_weeks, consolation_winner, consolation_loser))

    final_scores = {m: 0.0 for m in MANAGERS}
    for week in range(final_weeks[0], final_weeks[1] + 1):
        for m in MANAGERS:
            final_scores[m] += scores_by_week.get(week, {}).get(m, 0.0)

    return PlayoffSimResult(
        semi_scores=semi_scores,
        semi_winners=semi_winners,
        semi_losers=semi_losers,
        champ_winner=champ_winner,
        champ_loser=champ_loser,
        consolation_winner=consolation_winner,
        consolation_loser=consolation_loser,
        finish_order=[champ_winner, champ_loser,
                      consolation_winner, consolation_loser],
        final_scores=final_scores,
        series=series,
        scores_by_week=scores_by_week,
    )


# =============================================================================
# MAIN SIMULATION
# =============================================================================

def playoff_round_for_week(week: int, season: str = None) -> str:
    """Where in the postseason `week` sits: for labelling, not for logic."""
    rounds = bracket_rounds(season)
    if not rounds:
        return "pre_playoffs"
    semi = rounds.get(SEMIFINAL_ROUND)
    final = rounds.get(FINAL_ROUND)
    if semi and week < semi[0]:
        return "pre_playoffs"
    if semi and semi[0] <= week <= semi[1]:
        return "semifinals"
    if final and final[0] <= week <= final[1]:
        return "final"
    return "complete"


def run_playoff_odds_simulation(
    data: FantasyData,
    num_simulations: int = DEFAULT_NUM_SIMULATIONS,
    seed: int = None,
    injury_statuses: dict[str, str] = None,
) -> PlayoffOddsResult:
    """Monte Carlo the playoff bracket.

    Simulates the full six-week bracket N times:
      Semifinals (best-of-3)  #1 vs #4, #2 vs #3
      Final / Third Place     semifinal winners, semifinal losers

    Weeks that have already been played are locked to their real results, so
    running this mid-series does not re-roll games that happened.

    Args:
        data: FantasyData container
        num_simulations: number of bracket simulations to run
        seed: random seed for reproducibility
        injury_statuses: player -> injury status (from Yahoo, optional)
    """
    if seed is not None:
        random.seed(seed)

    rounds = bracket_rounds()
    if not rounds:
        raise ValueError(
            f"{CURRENT_SEASON} has no playoff bracket configured. Check "
            "postseason_format / season_structure in config/league_config.json.")
    for required in (SEMIFINAL_ROUND, FINAL_ROUND):
        if required not in rounds:
            raise ValueError(
                f"postseason_format is missing the '{required}' round; "
                f"found {sorted(rounds)}.")

    current_week = data.current_week
    team_projections = load_all_team_projections(data)

    seeds = get_playoff_seeds(data)
    current_records = {m: data.get_manager_record(m) for m in MANAGERS}

    semi_matchup_dicts, pairing_source = get_semifinal_matchups(data, seeds)
    if len(semi_matchup_dicts) != 2:
        raise ValueError(
            f"expected 2 semifinal matchups, got {len(semi_matchup_dicts)}. "
            "Either SCHEDULE.json is missing the bracket weeks or "
            "postseason_format has no seeds for the semifinals.")
    semi_pairs = [(m["manager_a"], m["manager_b"]) for m in semi_matchup_dicts]

    playoff_round = playoff_round_for_week(current_week)
    decided = _decided_weeks(data)

    # --- Run simulations ---
    title_wins = {m: 0 for m in MANAGERS}
    finish_counts = {m: {1: 0, 2: 0, 3: 0, 4: 0} for m in MANAGERS}
    series_wins = {m: 0 for m in MANAGERS}       # semifinal SERIES wins
    champ_matchup_counts = defaultdict(int)
    semi_score_totals = {m: 0.0 for m in MANAGERS}
    final_score_totals = {m: 0.0 for m in MANAGERS}
    final_appearances = {m: 0 for m in MANAGERS}
    sweeps = defaultdict(int)
    series_played = defaultdict(int)

    for _ in range(num_simulations):
        result = simulate_playoff_bracket(
            data, team_projections, semi_pairs, seeds,
            decided=decided, injury_statuses=injury_statuses,
        )

        title_wins[result.champ_winner] += 1
        for pos, manager in enumerate(result.finish_order, 1):
            finish_counts[manager][pos] += 1
        for w in result.semi_winners:
            series_wins[w] += 1

        champ_matchup_counts["_vs_".join(sorted(result.semi_winners))] += 1

        for m in MANAGERS:
            semi_score_totals[m] += result.semi_scores[m]
        for m in result.semi_winners:
            final_appearances[m] += 1
            final_score_totals[m] += result.final_scores[m]

        for s in result.series:
            series_played[s.round_name] += 1
            if s.week_winners.count(s.winner) == len(s.week_winners):
                sweeps[s.round_name] += 1

    # --- Compute results ---
    title_odds = {m: (title_wins[m] / num_simulations) * 100 for m in MANAGERS}
    finish_distribution = {
        m: {pos: (count / num_simulations) * 100 for pos, count in positions.items()}
        for m, positions in finish_counts.items()
    }

    semi_matchups = []
    for (ma, mb) in semi_pairs:
        semi_matchups.append({
            "manager_a": ma,
            "manager_b": mb,
            "win_prob_a": round((series_wins[ma] / num_simulations) * 100, 1),
            "win_prob_b": round((series_wins[mb] / num_simulations) * 100, 1),
            "seed_a": seeds[ma],
            "seed_b": seeds[mb],
            "weeks": list(rounds[SEMIFINAL_ROUND]),
            "format": "best-of-3",
            "pairing_source": pairing_source,
        })

    championship_matchup_probs = {
        key: (count / num_simulations) * 100
        for key, count in champ_matchup_counts.items()
    }

    expected_semi_scores = {m: semi_score_totals[m] / num_simulations for m in MANAGERS}
    expected_final_scores = {
        m: (final_score_totals[m] / final_appearances[m]) if final_appearances[m] else 0.0
        for m in MANAGERS
    }

    sweep_probability = {
        name: (sweeps[name] / series_played[name]) * 100
        for name in series_played if series_played[name]
    }

    title_odds_delta = {}
    last_week_key = f"week_{current_week - 1}"
    if last_week_key in data.records.get("title_odds_history", {}):
        last_odds = data.records["title_odds_history"][last_week_key]
        for manager in MANAGERS:
            if manager in last_odds:
                title_odds_delta[manager] = title_odds[manager] - last_odds[manager]

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
        round_weeks={name: list(weeks) for name, weeks in rounds.items()},
        sweep_probability=sweep_probability,
        title_odds_delta=title_odds_delta,
        expected_record={m: current_records[m] for m in MANAGERS},
        magic_numbers={m: None for m in MANAGERS},
    )


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def _weeks_label(weeks) -> str:
    first, last = weeks[0], weeks[-1]
    return f"Week {first}" if first == last else f"Weeks {first}-{last}"


def format_playoff_odds_table(result: PlayoffOddsResult) -> str:
    """Format playoff odds as a text table."""
    lines = []
    lines.append("PLAYOFF CHAMPIONSHIP ODDS")
    lines.append("=" * 60)
    lines.append("")

    semi_weeks = result.round_weeks.get(SEMIFINAL_ROUND, [])
    label = f" ({_weeks_label(semi_weeks)}, best-of-3)" if semi_weeks else ""
    lines.append(f"SEMIFINAL SERIES{label}:")
    lines.append("-" * 40)
    for semi in result.semi_matchups:
        ma, mb = semi["manager_a"], semi["manager_b"]
        pa, pb = semi["win_prob_a"], semi["win_prob_b"]
        sa, sb = semi["seed_a"], semi["seed_b"]
        lines.append(f"  #{sa} {ma} ({pa:.1f}%) vs #{sb} {mb} ({pb:.1f}%)")
    if result.sweep_probability.get(SEMIFINAL_ROUND) is not None:
        lines.append(f"  sweep (3-0): {result.sweep_probability[SEMIFINAL_ROUND]:.1f}%")
    lines.append("")

    lines.append("PLAYOFF CHAMPIONSHIP PROBABILITY:")
    lines.append("-" * 40)
    for manager in sorted(MANAGERS, key=lambda m: result.title_odds[m], reverse=True):
        odds = result.title_odds[manager]
        seed = result.seeds[manager]
        dist = result.finish_distribution[manager]
        delta = result.title_odds_delta.get(manager)
        delta_str = f" ({delta:+.1f}%)" if delta is not None else ""
        lines.append(
            f"  #{seed} {manager}: {odds:.1f}%{delta_str}"
            f"  [1st: {dist[1]:.1f}% | 2nd: {dist[2]:.1f}% | "
            f"3rd: {dist[3]:.1f}% | 4th: {dist[4]:.1f}%]"
        )
    lines.append("")

    if result.championship_matchup_probs:
        final_weeks = result.round_weeks.get(FINAL_ROUND, [])
        label = f" ({_weeks_label(final_weeks)})" if final_weeks else ""
        lines.append(f"MOST LIKELY FINAL{label}:")
        lines.append("-" * 40)
        for matchup_key, prob in sorted(result.championship_matchup_probs.items(),
                                        key=lambda x: x[1], reverse=True):
            m1, m2 = matchup_key.split("_vs_")
            lines.append(f"  {m1} vs {m2}: {prob:.1f}%")

    lines.append("")
    lines.append("NOTE: this is the PLAYOFF championship. The League Champion is")
    lines.append("      the regular-season winner, already decided. The Cup runs")
    lines.append("      after this -- see simulator_cup_odds.py.")

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
    print(f"Bracket: {bracket_rounds()}")
