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

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

from .data_loader import SEASON_SIMS
from .data_loader import (
    FantasyData, MANAGERS, CURRENT_SEASON, Record, standings_order,
    REGULAR_SEASON_WEEKS, TIEBREAKER_RULES,
    stage_weeks, stage_rounds, regular_season_weeks_for,
)
from .projections import (
    TeamProjections,
    load_all_team_projections,
)
from .simulator_betting import week_score_matrices, scores_at


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_NUM_SIMULATIONS = SEASON_SIMS   # config simulations.season_sims

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
    current_records: dict[str, Record]

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

def rank_managers_by_standings(data: FantasyData) -> list[str]:
    """
    Managers in regular-season standings order: data_loader.standings_order
    (winning percentage with a T as half a win, then head-to-head among the
    tied, then total points) over the regular season ONLY -- playoff weeks
    never influence seeding.

    Before any regular-season week is in RECORDS it falls back to the live
    records (LEAGUEHISTORY) and the season points totals.
    """
    records, h2h, points = data.regular_season_results()
    if not any(r.games for r in records.values()):
        season_totals = data.records.get("manager_season_totals", {})
        records = {m: data.get_manager_record(m) for m in MANAGERS}
        points = {m: season_totals.get(m, {}).get("total_points", 0.0) for m in MANAGERS}
        h2h = {}
    return standings_order(records, h2h, points, MANAGERS)


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

def _week_winner(pair, scores, seeds, tie_rule):
    """Winner of one week of a series. `tie_rule` comes from the caller's own
    tiebreaker_rules key -- series_week for the bracket, cup_game for the Cup
    -- so the two competitions cannot drift onto one shared rule.

    A tie goes to the higher seed whether the week was simulated or played.
    It used to be a coin flip when simulated, on a project-wide convention
    for simulated results. That convention is wrong here: the league's rule
    decides a tied week outright (Nick, 10-07), so flipping for it simulates
    a league that does not exist and hands the lower seed half of something
    the rules award to the higher one. Fractional scoring makes an exact tie
    almost impossible either way; the rule exists so the same input always
    gives the same answer.
    """
    a, b = pair
    sa, sb = scores.get(a, 0.0), scores.get(b, 0.0)
    if sa > sb:
        return a
    if sb > sa:
        return b
    if tie_rule != "higher_seed":
        raise ValueError(f"unknown tied-week rule {tie_rule!r}")
    return a if seeds.get(a, 99) <= seeds.get(b, 99) else b


def _week_scores(week, decided, simulated):
    """A played week is never rolled: `decided` wins over the simulation."""
    if week in decided:
        return decided[week]
    if week not in simulated:
        raise KeyError(f"bracket week {week} is neither decided nor simulated")
    return simulated[week]


def _play_series(pairs, weeks, seeds, decided, simulated, scores_by_week):
    """Play one round: every week of it, for both pairings at once.

    `pairs` is [(a, b), (c, d)]. Both pairings play in the same weeks, so the
    week is read once by both. Every week is played even once a series is
    decided -- the league plays them out, and the points still count toward
    season totals and the Cup seeding. `simulated` is this iteration's
    {week: {manager: score}} (scores_at of the precomputed matrices).

    Returns [(winner, loser, week_winners), ...] in the order of `pairs`.
    """
    from modules.data_loader import league_rule
    tie_rule = league_rule("tiebreaker_rules", "series_week")

    first, last = weeks
    tallies = [defaultdict(int) for _ in pairs]
    week_winner_lists = [[] for _ in pairs]

    for week in range(first, last + 1):
        scores = _week_scores(week, decided, simulated)
        scores_by_week[week] = scores

        for i, pair in enumerate(pairs):
            winner = _week_winner(pair, scores, seeds, tie_rule)
            tallies[i][winner] += 1
            week_winner_lists[i].append(winner)

    out = []
    for i, (a, b) in enumerate(pairs):
        winner = a if tallies[i][a] > tallies[i][b] else b
        loser = b if winner == a else a
        out.append((winner, loser, week_winner_lists[i]))
    return out


def simulate_playoff_bracket(
    semi_pairs: list,
    seeds: dict,
    simulated: dict,
    decided: dict = None,
) -> PlayoffSimResult:
    """Play one complete playoff bracket: semifinals, then final.

    semi_pairs is [(a, b), (c, d)]. `simulated` is one iteration's
    {week: {manager: score}}; `decided` maps an already-played week to its
    real {manager: score}, used as-is rather than rolled again, so an
    eliminated manager cannot pick up championship odds.
    """
    decided = decided or {}
    rounds = bracket_rounds()
    scores_by_week = {}
    series = []

    # --- Semifinals ---
    semi_weeks = rounds[SEMIFINAL_ROUND]
    semi_out = _play_series(semi_pairs, semi_weeks, seeds, decided, simulated, scores_by_week)
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
    final_out = _play_series(final_pairs, final_weeks, seeds, decided, simulated, scores_by_week)

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
    """The playoff bracket: a READOUT of the season pass
    (season_sim.run_season), stopped after the bracket.

    Every iteration seeds its bracket from THAT iteration's regular-season
    standings, so in weeks 1-14 these are the odds over every bracket the
    season might produce -- not today's seeding held fixed. Once the regular
    season is decided every iteration replays it and the bracket is the real
    one. Played weeks are locked to their real scores (_decided_weeks).

    seed is required: the run's one seed, the same the betting lines get.
    """
    if seed is None:
        raise ValueError("run_playoff_odds_simulation needs an explicit seed: one seed per run, chosen by the caller (generate_stats_report picks it) so every simulator prices the same week from the same draws")
    _require_bracket()
    from .season_sim import run_season
    return run_season(data, num_simulations, seed, injury_statuses,
                      through="playoffs").playoff_result()


def _require_bracket():
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
    return rounds


def modal_seeding(seed_rows, managers):
    """(seeds {manager: seed}, share of iterations, mask of those iterations)
    for the seeding that occurs most often in a season pass."""
    import numpy as np
    keys, inverse, counts = np.unique(seed_rows, axis=0, return_inverse=True, return_counts=True)
    top = int(counts.argmax())
    seeds = {m: int(keys[top][j]) for j, m in enumerate(managers)}
    return seeds, float(counts[top]) / len(seed_rows), np.asarray(inverse).reshape(-1) == top


def playoff_readout(sp) -> PlayoffOddsResult:
    """PlayoffOddsResult from a season pass: the bracket's marginals.

    seeds and semi_matchups describe the MOST LIKELY bracket, with
    win_prob_a/b conditional on that bracket happening and its share in
    pairing_probability; until the regular season is decided other brackets
    are possible and are in title_odds and finish_distribution."""
    import numpy as np
    rounds = _require_bracket()
    data, n, managers = sp.data, sp.num_simulations, sp.managers
    name = {j: m for j, m in enumerate(managers)}
    champ = np.bincount(sp.playoff_finish[:, 0], minlength=len(managers))
    title_odds = {m: float(champ[j]) / n * 100 for j, m in enumerate(managers)}
    finish_distribution = {}
    for j, m in enumerate(managers):
        places = (sp.playoff_finish == j).argmax(axis=1)
        counts = np.bincount(places, minlength=4)
        finish_distribution[m] = {pos + 1: float(counts[pos]) / n * 100 for pos in range(4)}

    seeds, share, mask = modal_seeding(sp.seeds, managers)
    seed_pairs = [[1, 4], [2, 3]]
    for rnd in stage_rounds(CURRENT_SEASON, "playoffs"):
        if rnd["name"] == SEMIFINAL_ROUND:
            seed_pairs = rnd.get("seeds", seed_pairs)
            break
    source = ("the final regular-season standings" if share == 1.0 else
              f"season pass: the most likely bracket, {share:.1%} of simulated seasons")
    winners_in = sp.semi_winners[mask]
    semi_matchups = []
    for a, b in _seeded_pairs(seeds, seed_pairs):
        ia, ib = managers.index(a), managers.index(b)
        semi_matchups.append({
            "manager_a": a, "manager_b": b,
            "win_prob_a": round(float((winners_in == ia).any(axis=1).mean()) * 100, 1),
            "win_prob_b": round(float((winners_in == ib).any(axis=1).mean()) * 100, 1),
            "seed_a": seeds[a], "seed_b": seeds[b],
            "weeks": list(rounds[SEMIFINAL_ROUND]),
            "format": "best-of-3",
            "pairing_source": source,
            "pairing_probability": round(share * 100, 1),
        })

    champ_pairs = defaultdict(int)
    for row in sp.semi_winners:
        champ_pairs["_vs_".join(sorted(name[int(k)] for k in row))] += 1
    in_final = np.zeros((n, len(managers)), dtype=bool)
    for k in range(2):
        in_final[np.arange(n), sp.semi_winners[:, k]] = True
    expected_final_scores = {
        m: float(sp.final_points[in_final[:, j], j].mean()) if in_final[:, j].any() else 0.0
        for j, m in enumerate(managers)}

    current_records = {m: data.get_manager_record(m) for m in MANAGERS}
    title_odds_delta = {}
    last_odds = data.records.get("title_odds_history", {}).get(f"week_{sp.current_week - 1}")
    if last_odds:
        for m in MANAGERS:
            if m in last_odds:
                title_odds_delta[m] = title_odds[m] - last_odds[m]

    return PlayoffOddsResult(
        num_simulations=n,
        current_week=sp.current_week,
        playoff_round=playoff_round_for_week(sp.current_week),
        title_odds=title_odds,
        finish_distribution=finish_distribution,
        semi_matchups=semi_matchups,
        championship_matchup_probs={k: v / n * 100 for k, v in champ_pairs.items()},
        expected_semi_scores={m: float(sp.semi_points[:, j].mean()) for j, m in enumerate(managers)},
        expected_final_scores=expected_final_scores,
        current_records=current_records,
        seeds=seeds,
        round_weeks={nm: list(w) for nm, w in rounds.items()},
        sweep_probability={nm: float(arr.mean()) * 100 for nm, arr in sp.sweeps.items()},
        title_odds_delta=title_odds_delta,
        expected_record={m: (float(r.wins), float(r.losses), float(r.ties))
                         for m, r in current_records.items()},
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
