"""
season_sim.py -- one season, four races, one pass (Phase 2).

SEASON_SIM_DESIGN.md is the reasoning; HANDOFF_SEASON_SIM_2026-10-26.md the build.

WHAT IT IS
----------
Title odds, playoff odds and Cup odds used to be three Monte Carlos on three
streams: iteration i of one was not the same imagined season as iteration i
of another, the brackets were seeded from TODAY's standings, and no joint
outcome ("win the regular season, lose your semifinal" -- a real +$135) could
be priced. This is one pass over weeks 1-23:

    1. weeks 1-15, the regular season: every unplayed week from ONE call to
       simulator_betting.week_score_matrices -- the betting lines' function
       and keys, so a week here is bit-identical to that week in a line or
       in Phase 1's title odds. Played weeks come from RECORDS; a week the
       logs have and RECORDS does not yet (in progress, or played and not yet
       built) is B2's simulate_week_remainder: banked from the logs, the rest
       simulated (HANDOFF sec.8 -- it used to be neither banked nor simulated).
    2. final standings per iteration: simulate_full_season (lifted here from
       simulator_title_odds, which re-exports it) -> data_loader.standings_order.
    3. the bracket seeded from THAT iteration's standings, 1v4 and 2v3 per
       postseason_format, and played by simulator_playoff_odds'
       simulate_playoff_bracket (weeks 16-21; a played week is never rolled).
    4. the Cup seeded on THAT iteration's points over weeks 1-21, ties to the
       better regular-season finish (tiebreaker_rules.cup_seeding), played by
       simulator_cup_odds' simulate_cup (weeks 22-23).
    5. the ledger (ledger()).

There is no switch between simulated and actual seeding. As weeks are played
they enter RECORDS / the decided weeks and every iteration replays the same
history, so the distribution collapses onto the real bracket by itself.

The three result shapes -- TitleOddsResult, PlayoffOddsResult, CupOddsResult
-- are readouts of this one object (title_result, playoff_result, cup_result),
with every field they always had.

FROZEN ROSTERS
--------------
No future adds, drops or trades: the pass is "given no further moves". That
keeps a waiver counterfactual readable (one move, same draws). It also means
simulated point totals run LOW -- an injury absorbed is never replaced -- and
the bias falls on all four managers roughly equally, so the odds are fair and
absolute season totals are not. Played weeks replace projected ones as the
season goes, so totals converge on the real figures by the end. Say so
anywhere a projected season total is published.

TWO CURRENCIES
--------------
Dollars come from the regular season and the playoff bracket only. The Cup's
prize is a sixth keeper the following season: reported as a probability,
never as dollars, never summed with them (LEAGUE_RULES.md; payouts.cup_champion
.total = 0). ledger() keeps them apart and a test holds it.
"""
from __future__ import annotations

import math
from itertools import combinations
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np

from .data_loader import (
    CURRENT_SEASON, MANAGERS, NUM_TEAMS, SEASON_SIMS, FantasyData, Record,
    league_rule, regular_season_weeks_for, stage_rounds, standings_order, week_outcome,
)
from .simulator_betting import scores_at, week_score_matrices


# =============================================================================
# THE REGULAR SEASON -- lifted from simulator_title_odds (Phase 1)
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
    """Result of simulating an entire regular season."""
    final_records: dict
    final_points: dict
    h2h_records: dict
    champion: str
    finish_order: list


def simulate_matchup(scores: dict, matchup_def: dict, week: int) -> SimulatedMatchup:
    """One matchup, read off one simulated week's scores {manager: score}.
    A tied regular-season week is a T for both (tiebreaker_rules.
    regular_season_week; Nick, 10-20) -- winner None, never a coin flip."""
    a, b = matchup_def["manager_a"], matchup_def["manager_b"]
    sa, sb = scores[a], scores[b]
    outcome = week_outcome(sa, sb)
    winner = a if outcome == "a" else (b if outcome == "b" else None)
    return SimulatedMatchup(week, a, b, sa, sb, winner)


def apply_tiebreakers(records: dict, h2h: dict, points: dict) -> list:
    """Final standings, 1st to 4th: data_loader.standings_order -- the one
    ranking rule (winning percentage with a T as half a win, head-to-head
    among the tied, total points)."""
    return standings_order(records, h2h, points, list(records))


def simulate_full_season(current_records: dict, current_h2h: dict, current_points: dict,
                         remaining_weeks: list, week_scores: dict) -> SimulatedSeason:
    """Play out the rest of the regular season once.

    week_scores is ONE simulation's {week: {manager: score}} for every
    remaining week. The fantasy schedule's matchups are played on those
    scores. Raises if a remaining week has no scores rather than skipping it.
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
            mu = simulate_matchup(scores, matchup_def, week)
            a, b = mu.manager_a, mu.manager_b
            if mu.winner is None:
                ra, rb = "tie", "tie"
            else:
                ra, rb = ("win", "loss") if mu.winner == a else ("loss", "win")
            records[a] = records.get(a, Record()).add(ra)
            records[b] = records.get(b, Record()).add(rb)
            h2h.setdefault(a, {})[b] = h2h.get(a, {}).get(b, Record()).add(ra)
            h2h.setdefault(b, {})[a] = h2h.get(b, {}).get(a, Record()).add(rb)
    order = apply_tiebreakers(records, h2h, points)
    return SimulatedSeason(dict(records), points, h2h, order[0], order)


# =============================================================================
# WHAT IS ALREADY DECIDED
# =============================================================================

def recorded_weeks(data: FantasyData, last_week: int) -> set:
    """Regular-season weeks RECORDS holds a score for, for every manager."""
    have: dict = {}
    for m, entries in (data.records.get("weekly_scores") or {}).items():
        if m not in MANAGERS or not isinstance(entries, list):
            continue
        for e in entries:
            w = e.get("week")
            if w is not None and 1 <= int(w) <= last_week:
                have.setdefault(int(w), set()).add(m)
    return {w for w, ms in have.items() if set(MANAGERS) <= ms}


def in_progress_weeks(data: FantasyData, last_week: int) -> list:
    """Regular-season weeks the logs have reached and RECORDS has not:
    week <= data.current_week (PLAYERLOG's highest) and not recorded.
    Mid-week these are neither banked nor simulated by Phase 1."""
    done = recorded_weeks(data, last_week)
    upto = min(int(data.current_week or 0), last_week)
    return [w for w in range(1, upto + 1) if w not in done]


def _as_of_for(data: FantasyData, week: int) -> date:
    """The first day of `week` the logs have NOT covered: the day after the
    latest LINEUPS date inside it (LINEUPS has a row for every rostered
    player every day, game or not), or the week's first day."""
    from .week_state import week_entry
    from .simulator_betting import get_dates_in_week
    dates = get_dates_in_week(week_entry(data, week))
    lu = getattr(data, "lineups", None)
    seen = []
    if lu is not None and len(lu):
        isos = set(lu["date"].astype(str).str[:10])
        seen = [d for d in dates if d.isoformat() in isos]
    return (max(seen) + timedelta(days=1)) if seen else dates[0]


# =============================================================================
# THE PASS
# =============================================================================

@dataclass
class SeasonPass:
    """Every iteration of one season. Arrays are [n] or [n, 4]; manager
    columns follow `managers`. Positions are 0-based in the arrays."""
    through: str                    # the last stage played
    num_simulations: int
    seed: int
    current_week: int
    managers: list
    regular_weeks: tuple            # (first, last)
    simulated_weeks: list           # weeks drawn from week_score_matrices
    in_progress: dict               # week -> {"as_of", "banked", "assumptions"}
    decided_bracket: dict           # week -> {manager: score}
    decided_cup: dict
    current_records: dict           # RECORDS-only regular-season records
    current_h2h: dict
    current_points: dict
    remaining_games: dict           # manager -> regular-season games left (incl. in progress)
    remaining_pairs: list           # [(a, b)] every regular-season game left (incl. in progress)
    reg_finish: np.ndarray          # [n, 4] manager index by place
    reg_wins: np.ndarray            # [n, 4] final W / L / T
    reg_losses: np.ndarray
    reg_ties: np.ndarray
    reg_points: np.ndarray          # [n, 4] regular-season points
    seeds: np.ndarray               # [n, 4] playoff seed (1-4) by manager
    semi_pairs: list                # per iteration: ((a, b), (c, d)) manager names
    semi_winners: np.ndarray        # [n, 2] manager index
    semi_losers: np.ndarray
    playoff_finish: np.ndarray      # [n, 4] champion, runner-up, 3rd, 4th
    semi_points: np.ndarray         # [n, 4] points across the semifinal weeks
    final_points: np.ndarray        # [n, 4] points across the final weeks
    sweeps: dict                    # round -> [n] bool per series (two per round)
    cup_points: np.ndarray          # [n, 4] seeding points, weeks 1-21
    cup_seeds: np.ndarray           # [n, 4]
    cup_semi_pairs: list
    cup_semi_winners: np.ndarray    # [n, 2]
    cup_finish: np.ndarray          # [n, 4] winner, runner-up, 3rd, 4th
    cup_week_points: np.ndarray     # [n, 4] points over the Cup weeks
    dollars: np.ndarray             # [n, 4] net dollars, regular season + bracket ONLY
    third_place: np.ndarray         # [n] manager index winning the third-place series
    data: FantasyData = field(repr=False, default=None)

    # ---- readouts --------------------------------------------------------
    def title_result(self):
        from .simulator_title_odds import title_readout
        return title_readout(self)

    def playoff_result(self):
        from .simulator_playoff_odds import playoff_readout
        return playoff_readout(self)

    def cup_result(self):
        from .simulator_cup_odds import cup_readout
        return cup_readout(self)

    def ledger(self) -> dict:
        return ledger(self)

    def exact(self) -> dict:
        """What is settled by arithmetic, race by race (races_exact)."""
        return races_exact(self)


def _seed_pairs(season: str, stage: str, round_name: str) -> list:
    for rnd in stage_rounds(season, stage):
        if rnd["name"] == round_name:
            return [list(p) for p in rnd.get("seeds", [])]
    raise ValueError(f"postseason_format.{stage} has no '{round_name}' round with seeds")


STAGES = ("regular", "playoffs", "cup")
PAYING_PLACES = (3, 4)      # the league pot: 1st collects from 3rd and 4th; 2nd is square


def run_season(data: FantasyData, num_simulations: int = SEASON_SIMS, seed: int = None,
               injury_statuses: dict = None, team_projections: dict = None,
               through: str = "cup") -> SeasonPass:
    """One pass over the season. seed is required: one seed per run, the same
    the betting lines get, so a week is one simulated truth.

    through: the last stage played -- "regular", "playoffs" or "cup" (the
    default, and the only one the weekly build uses). A stage's numbers do not
    depend on what comes after it, so a pass that stops early reads exactly
    the same regular season (same draws, same rules); the later stages' arrays
    are then left at -1 / 0. The title-odds readout stops after the regular
    season so a world with no bracket weeks in its schedule can still be priced."""
    from .projections import load_all_team_projections
    from .simulator_playoff_odds import (
        SEMIFINAL_ROUND, _decided_weeks, _seeded_pairs, bracket_rounds, bracket_weeks,
        resolve_completed_week, simulate_playoff_bracket,
    )
    from .simulator_cup_odds import CUP_SEMIFINAL_ROUND, cup_rounds, cup_weeks, simulate_cup
    from .simulator_betting import simulate_week_remainder

    if seed is None:
        raise ValueError("run_season needs an explicit seed: one seed per run, chosen by the "
                         "caller (generate_stats_report picks it)")
    if through not in STAGES:
        raise ValueError(f"through must be one of {STAGES}, not {through!r}")
    play_bracket = through in ("playoffs", "cup")
    play_cup = through == "cup"
    n = int(num_simulations)
    season = CURRENT_SEASON
    managers = list(MANAGERS)
    idx = {m: i for i, m in enumerate(managers)}
    last_reg = regular_season_weeks_for(season)
    if (play_bracket and not bracket_rounds(season)) or (play_cup and not cup_rounds(season)):
        raise ValueError(f"{season} has no bracket or no Cup configured; a pass through "
                         f"{through!r} needs postseason_format.playoffs and .cup")
    if team_projections is None:
        team_projections = load_all_team_projections(data)

    # --- what is decided ----------------------------------------------------
    recs, h2h, pts = data.regular_season_results()
    cur_records = {m: recs.get(m, Record()) for m in managers}
    cur_h2h = {m: dict(h2h.get(m, {})) for m in managers}
    cur_points = {m: float(pts.get(m, 0.0)) for m in managers}
    done = recorded_weeks(data, last_reg)
    pending = in_progress_weeks(data, last_reg)
    future = [w for w in range(int(data.current_week or 0) + 1, last_reg + 1) if w not in done]
    reg_entries = {int(w["week"]): w for w in data.schedule.get("weeks", [])}
    missing = [w for w in pending + future if w not in reg_entries]
    if missing:
        raise KeyError(f"SCHEDULE.json has no entry for regular-season week(s) {missing}")
    decided_bracket = _decided_weeks(data) if play_bracket else {}
    decided_cup = {}
    for w in (cup_weeks(season) if play_cup else []):
        s = resolve_completed_week(data, w)
        if s:
            decided_cup[w] = s

    # --- the matrices: every unplayed week, one call -------------------------
    to_sim = list(future)
    if play_bracket:
        to_sim += [w for w in bracket_weeks(season) if w not in decided_bracket]
    if play_cup:
        to_sim += [w for w in cup_weeks(season) if w not in decided_cup]
    mats = week_score_matrices(data, team_projections, to_sim, injury_statuses, seed, n) if to_sim else {}

    # --- in-progress regular weeks: B2, banked + the remainder ---------------
    from .week_state import week_state
    in_progress = {}
    for w in pending:
        as_of = _as_of_for(data, w)
        state = week_state(data, w, as_of, team_projections)
        rem = simulate_week_remainder(data, team_projections, reg_entries[w], state, seed, n,
                                      injury_statuses)
        mats[w] = {m: float(state.banked.get(m, 0.0)) + np.asarray(rem.remaining[m]["score"], float)
                   for m in managers}
        in_progress[w] = {"as_of": as_of.isoformat(), "banked": dict(state.banked),
                          "assumptions": list(state.assumptions)}

    reg_weeks = [reg_entries[w] for w in sorted(pending + future)]
    remaining_pairs = [(mu["manager_a"], mu["manager_b"]) for w in reg_weeks
                       for mu in w.get("matchups", [])]
    remaining_games = {m: sum(1 for w in reg_weeks for mu in w.get("matchups", [])
                              if m in (mu["manager_a"], mu["manager_b"])) for m in managers}

    semi_seed_pairs = _seed_pairs(season, "playoffs", SEMIFINAL_ROUND) if play_bracket else []
    cup_seed_pairs = _seed_pairs(season, "cup", CUP_SEMIFINAL_ROUND) if play_cup else []
    b_weeks = bracket_weeks(season) if play_bracket else []
    b_rounds = bracket_rounds(season) if play_bracket else {}
    if play_cup and league_rule("tiebreaker_rules", "cup_seeding") != "regular_season_finish":
        raise ValueError(f"unknown cup_seeding tiebreak "
                         f"{league_rule('tiebreaker_rules', 'cup_seeding')!r}")
    rules = payout_rules() if play_bracket else None

    shape = (n, len(managers))
    out = {k: np.full(shape, -1, dtype=int) for k in
           ("reg_finish", "reg_wins", "reg_losses", "reg_ties", "seeds", "playoff_finish",
            "cup_seeds", "cup_finish")}
    for k in ("reg_points", "semi_points", "final_points", "cup_points", "cup_week_points", "dollars"):
        out[k] = np.zeros(shape)
    out["reg_ties"] = np.zeros(shape)
    semi_w, semi_l, cup_sw = (np.full((n, 2), -1, dtype=int) for _ in range(3))
    third = np.full(n, -1, dtype=int)
    sweeps = {name: np.zeros((n, 2), dtype=bool) for name in b_rounds if name != "Third Place"}
    sweeps["Third Place"] = np.zeros((n, 1), dtype=bool)
    semi_pairs_all, cup_pairs_all = [], []

    s_first, s_last = b_rounds.get(SEMIFINAL_ROUND, (0, -1))
    f_first, f_last = b_rounds.get("Final", (0, -1))
    for i in range(n):
        ws = scores_at(mats, i)
        reg = simulate_full_season(cur_records, cur_h2h, cur_points, reg_weeks, ws)
        order = reg.finish_order
        seeds = {m: k + 1 for k, m in enumerate(order)}
        for k, m in enumerate(order):
            out["reg_finish"][i, k] = idx[m]
        for m in managers:
            j = idx[m]
            r = reg.final_records[m]
            out["reg_wins"][i, j], out["reg_losses"][i, j], out["reg_ties"][i, j] = r.wins, r.losses, r.ties
            out["reg_points"][i, j] = reg.final_points[m]
            out["seeds"][i, j] = seeds[m]
        if not play_bracket:
            continue
        pairs = _seeded_pairs(seeds, semi_seed_pairs)
        br = simulate_playoff_bracket(pairs, seeds, ws, decided=decided_bracket)
        # Cup seeding: points over weeks 1-21, ties to the better regular-season finish
        cpts = {m: reg.final_points[m] + sum(br.scores_by_week[w][m] for w in b_weeks)
                for m in managers}
        ranked = sorted(managers, key=lambda m: (-cpts[m], seeds[m]))
        cseeds = {m: k + 1 for k, m in enumerate(ranked)}
        for m in managers:
            j = idx[m]
            out["cup_points"][i, j] = cpts[m]
            out["semi_points"][i, j] = sum(br.scores_by_week[w][m] for w in range(s_first, s_last + 1))
            out["final_points"][i, j] = sum(br.scores_by_week[w][m] for w in range(f_first, f_last + 1))
        for k, m in enumerate(br.finish_order):
            out["playoff_finish"][i, k] = idx[m]
        semi_w[i] = [idx[m] for m in br.semi_winners]
        semi_l[i] = [idx[m] for m in br.semi_losers]
        third[i] = idx[br.consolation_winner]
        counts = {"Semifinals": 0, "Final": 0, "Third Place": 0}
        for s in br.series:
            swept = s.week_winners.count(s.winner) == len(s.week_winners)
            sweeps[s.round_name][i, counts[s.round_name]] = swept
            counts[s.round_name] += 1
        semi_pairs_all.append(tuple(pairs))
        out["dollars"][i] = dollars_for(order, br.semi_losers, br.champ_winner,
                                        br.consolation_winner, managers, rules)
        if not play_cup:
            continue
        cpairs = _seeded_pairs(cseeds, cup_seed_pairs)
        cr = simulate_cup(cpairs, cseeds, ws, decided=decided_cup)
        for m in managers:
            j = idx[m]
            out["cup_seeds"][i, j] = cseeds[m]
            out["cup_week_points"][i, j] = sum(sc[m] for sc in cr.scores_by_week.values())
        for k, m in enumerate(cr.finish_order):
            out["cup_finish"][i, k] = idx[m]
        cup_sw[i] = [idx[m] for m in cr.semi_winners]
        cup_pairs_all.append(tuple(cpairs))

    return SeasonPass(
        through=through,
        num_simulations=n, seed=int(seed), current_week=int(data.current_week or 0),
        managers=managers, regular_weeks=(1, last_reg), simulated_weeks=sorted(to_sim),
        in_progress=in_progress, decided_bracket=decided_bracket, decided_cup=decided_cup,
        current_records=cur_records, current_h2h=cur_h2h, current_points=cur_points,
        remaining_games=remaining_games, remaining_pairs=remaining_pairs,
        reg_finish=out["reg_finish"], reg_wins=out["reg_wins"], reg_losses=out["reg_losses"],
        reg_ties=out["reg_ties"], reg_points=out["reg_points"], seeds=out["seeds"],
        semi_pairs=semi_pairs_all, semi_winners=semi_w, semi_losers=semi_l,
        playoff_finish=out["playoff_finish"], semi_points=out["semi_points"],
        final_points=out["final_points"], sweeps=sweeps, cup_points=out["cup_points"],
        cup_seeds=out["cup_seeds"], cup_semi_pairs=cup_pairs_all, cup_semi_winners=cup_sw,
        cup_finish=out["cup_finish"], cup_week_points=out["cup_week_points"],
        dollars=out["dollars"], third_place=third, data=data,
    )


# =============================================================================
# THE LEDGER -- two currencies, never summed
# =============================================================================

def payout_rules(config_payouts: dict = None) -> dict:
    """The money rules, from league_config payouts. Raises on anything this
    ledger cannot place rather than guessing (Nick, 10-07: code never guesses).

    THE PLAYOFF LIABILITY RULE IS THE SEMIFINAL ONE (LEAGUE_RULES.md: win your
    semi and you are clear). payouts.playoff_champion.paid_by words it as "3rd
    and 4th in the playoff bracket, as decided by the weeks 19-21 third-place
    series". The two agree only while both semifinal losers pay the same and
    the third-place series carries no stake. A nonzero playoff_third_place
    stake is where they diverge -- and nothing says how that stake moves -- so
    it raises here (tests/test_season_sim.py holds the divergence).
    """
    if config_payouts is None:
        config_payouts = league_rule("payouts")
    p = config_payouts
    for key in ("cup_champion", "playoff_third_place", "cup_third_place"):
        if float((p.get(key) or {}).get("total", 0) or 0) != 0:
            raise ValueError(
                f"payouts.{key}.total is nonzero. "
                + ("The Cup's prize is a keeper and is never money (LEAGUE_RULES.md)."
                   if key == "cup_champion" else
                   "The ledger settles playoff liability at the semifinal; a third-place stake "
                   "would make the config's 'decided by the third-place series' reading and "
                   "LEAGUE_RULES' semifinal reading pay different people, and no rule says how "
                   "the stake moves. Write that rule down before setting it."))
    league = p["league_champion"]
    playoff = p["playoff_champion"]
    if float(league["total"]) != 2 * float(league["per_payer"]):
        raise ValueError("payouts.league_champion: total must be two payers' share")
    if float(playoff["total"]) != 2 * float(playoff["per_payer"]):
        raise ValueError("payouts.playoff_champion: total must be two payers' share")
    return {"league_total": float(league["total"]), "league_per_payer": float(league["per_payer"]),
            "playoff_total": float(playoff["total"]), "playoff_per_payer": float(playoff["per_payer"])}


def dollars_for(reg_order: list, semi_losers: list, playoff_champion: str,
                third_place_winner: str, managers: list, rules: dict) -> list:
    """Net dollars per manager (in `managers` order) for one season.

    League pot: 1st collects from 3rd and 4th; 2nd is square.
    Playoff pot: the champion collects from the two SEMIFINAL losers --
    settled at the semifinal. third_place_winner is taken and deliberately
    ignored: the third-place series moves no money.
    """
    net = {m: 0.0 for m in managers}
    net[reg_order[0]] += rules["league_total"]
    for m in reg_order[PAYING_PLACES[0] - 1:PAYING_PLACES[-1]]:
        net[m] -= rules["league_per_payer"]
    net[playoff_champion] += rules["playoff_total"]
    for m in semi_losers:
        net[m] -= rules["playoff_per_payer"]
    return [net[m] for m in managers]


def ledger(sp: SeasonPass) -> dict:
    """Per manager: dollars (expected, range, distribution) and, SEPARATELY,
    P(the sixth keeper in the following season) from the Cup. No key sums
    the two."""
    n = sp.num_simulations
    out = {}
    for j, m in enumerate(sp.managers):
        d = sp.dollars[:, j]
        vals, counts = np.unique(d, return_counts=True)
        won_reg = sp.reg_finish[:, 0] == j
        lost_semi = (sp.semi_losers == j).any(axis=1)
        out[m] = {
            "dollars": {
                "expected": float(d.mean()),
                "min": float(d.min()), "max": float(d.max()),
                "distribution": {float(v): float(c / n) for v, c in zip(vals, counts)},
                "p_league_champion": float(won_reg.mean()),
                "p_pays_league_pot": float(np.isin(sp.reg_finish[:, 2:4], j).any(axis=1).mean()),
                "p_playoff_champion": float((sp.playoff_finish[:, 0] == j).mean()),
                "p_pays_playoff_pot": float(lost_semi.mean()),
                "p_win_regular_season_lose_semifinal": float((won_reg & lost_semi).mean()),
            },
            "keeper": {
                "p_sixth_keeper_next_season": float((sp.cup_finish[:, 0] == j).mean()),
            },
        }
    return out


# =============================================================================
# CLINCH AND ELIMINATION -- arithmetic, not the sample
# =============================================================================

def _fits_under(caps: dict, games: list) -> bool:
    """Can the games among `caps`' managers be played so that each one GAINS
    at most caps[m] standing from them? Each game hands out exactly one
    standing point to its two players (a W, or a T as half each).

    Hall's condition on a bipartite flow (games -> managers): feasible iff
    every subset T holds at least the games played inside it. In half-points
    everything is integral, so the fractional flow is a real W/L/T outcome."""
    if any(c < 0 for c in caps.values()):
        return False
    ms = list(caps)
    for k in range(1, len(ms) + 1):
        for t in combinations(ms, k):
            ts = set(t)
            if sum(caps[m] for m in t) < sum(1 for a, b in games if a in ts and b in ts):
                return False
    return True


def _can_reach(demands: dict, games: list) -> bool:
    """Can the games among `demands`' managers be played so that each one
    GAINS at least demands[m] from them? Feasible iff every subset T's demand
    is no more than the games touching T (the same flow, the other way)."""
    need = {m: max(0.0, d) for m, d in demands.items()}
    ms = list(need)
    for k in range(1, len(ms) + 1):
        for t in combinations(ms, k):
            ts = set(t)
            if sum(need[m] for m in t) > sum(1 for a, b in games if a in ts or b in ts):
                return False
    return True


def regular_season_exact(records: dict, remaining_pairs: list,
                         paying_places: tuple = PAYING_PLACES) -> dict:
    """{manager: {"title": ..., "league_pot": ...}} from standings and the
    games left, by arithmetic alone (Record.standing: a T is half a win).

    title       "clinched"   no outcome lets any rival reach his standing
                             even if he loses out -- strictly: a reachable
                             tie goes to the tiebreakers and is not a clinch;
                "eliminated" no outcome has every rival at or below his
                             best -- with the rivals' games AGAINST EACH OTHER
                             played (they cannot all win them), which
                             marginal_value.title_eliminated's leader-only
                             bound does not see;
                "alive"      otherwise.
    league_pot  "safe"       no outcome puts enough rivals at or above him
                             to drop him into a paying place;
                "will_pay"   no outcome keeps enough rivals at or below his
                             best to lift him out of one;
                "alive"      otherwise.
    Exact in both directions for these races: each check is a max-flow over
    the actual remaining pairings, not a per-rival bound.
    """
    managers = list(records)
    s = {m: records[m].standing for m in managers}
    g = {m: sum(1 for p in remaining_pairs if m in p) for m in managers}
    safe_k = paying_places[0] - 1                 # finish in the top k and you do not pay
    out = {}
    for m in managers:
        rivals = [o for o in managers if o != m]
        worst, best = s[m], s[m] + g[m]

        def inside(group):
            return [(a, b) for a, b in remaining_pairs if a in group and b in group]

        def all_reach(group):                     # m loses out; can all of `group` reach >= worst?
            gs = set(group)
            dem = {r: worst - (s[r] + sum(1 for p in remaining_pairs
                                          if r in p and not set(p) <= gs)) for r in group}
            return _can_reach(dem, inside(gs))

        def all_held(group):                      # m wins out; can all of `group` stay <= best?
            gs = set(group)
            caps = {r: best - s[r] for r in group}
            return _fits_under(caps, inside(gs))

        if not any(all_reach([r]) for r in rivals):
            title = "clinched"
        elif not all_held(rivals):
            title = "eliminated"
        else:
            title = "alive"
        if not any(all_reach(list(c)) for c in combinations(rivals, safe_k)):
            pot = "safe"
        elif not any(all_held(list(c)) for c in combinations(rivals, len(rivals) - safe_k + 1)):
            pot = "will_pay"
        else:
            pot = "alive"
        out[m] = {"title": title, "league_pot": pot}
    return out


def _series_state(pair, weeks, decided, seeds, tie_rule):
    """(winner, loser) of a series already decided on week wins by the weeks
    played, else None. Unplayed weeks can go either way."""
    from .simulator_playoff_odds import _week_winner
    first, last = weeks
    need = (last - first + 1) // 2 + 1
    tally = {pair[0]: 0, pair[1]: 0}
    for w in range(first, last + 1):
        if w in decided:
            tally[_week_winner(pair, decided[w], seeds, tie_rule)] += 1
    a, b = pair
    if tally[a] >= need:
        return a, b
    if tally[b] >= need:
        return b, a
    return None


def races_exact(sp: SeasonPass) -> dict:
    """Every race the season pass prices, settled or not, by arithmetic.

    {manager: {"title", "league_pot", "playoff_champion", "playoff_pot",
    "cup_champion"}} -- each "clinched"/"safe", "eliminated"/"will_pay" or
    "alive". The sampled probability is evidence; this is proof. Exact
    clinch implies a sampled 1.0, never the other way round (brief s.7: a sampled
    1.0000 is not a clinch). The bracket and Cup races can only settle once
    their seeding is fixed -- before that every manager is alive in them.
    """
    from .simulator_playoff_odds import SEMIFINAL_ROUND, FINAL_ROUND, _seeded_pairs, bracket_rounds
    from .simulator_cup_odds import CUP_SEMIFINAL_ROUND, CUP_FINAL_ROUND, cup_rounds
    out = regular_season_exact(sp.current_records, sp.remaining_pairs)
    for m in out:
        out[m].update(playoff_champion="alive", playoff_pot="alive", cup_champion="alive")
    if sp.remaining_pairs or sp.through == "regular":
        return out
    season = CURRENT_SEASON
    order = apply_tiebreakers(sp.current_records, sp.current_h2h, sp.current_points)
    seeds = {m: k + 1 for k, m in enumerate(order)}
    rounds = bracket_rounds(season)
    rule = league_rule("tiebreaker_rules", "series_week")
    semis = [_series_state(p, rounds[SEMIFINAL_ROUND], sp.decided_bracket, seeds, rule)
             for p in _seeded_pairs(seeds, _seed_pairs(season, "playoffs", SEMIFINAL_ROUND))]
    for res in semis:
        if res:
            out[res[0]]["playoff_pot"] = "safe"
            out[res[1]]["playoff_pot"] = "will_pay"
            out[res[1]]["playoff_champion"] = "eliminated"
    if all(semis):
        final = _series_state((semis[0][0], semis[1][0]), rounds[FINAL_ROUND],
                              sp.decided_bracket, seeds, rule)
        if final:
            out[final[0]]["playoff_champion"] = "clinched"
            out[final[1]]["playoff_champion"] = "eliminated"
    b_weeks = [w for (f, l) in rounds.values() for w in range(f, l + 1)]
    if sp.through != "cup" or not all(w in sp.decided_bracket for w in b_weeks):
        return out
    # Cup seeding is fixed: points over weeks 1-21, ties to the regular-season finish
    cpts = {m: sp.current_points[m] + sum(sp.decided_bracket[w][m] for w in b_weeks) for m in out}
    ranked = sorted(out, key=lambda m: (-cpts[m], seeds[m]))
    cseeds = {m: k + 1 for k, m in enumerate(ranked)}
    crounds = cup_rounds(season)
    crule = league_rule("tiebreaker_rules", "cup_game")
    csemis = [_series_state(p, crounds[CUP_SEMIFINAL_ROUND], sp.decided_cup, cseeds, crule)
              for p in _seeded_pairs(cseeds, _seed_pairs(season, "cup", CUP_SEMIFINAL_ROUND))]
    for res in csemis:
        if res:
            out[res[1]]["cup_champion"] = "eliminated"
    if all(csemis):
        cfinal = _series_state((csemis[0][0], csemis[1][0]), crounds[CUP_FINAL_ROUND],
                               sp.decided_cup, cseeds, crule)
        if cfinal:
            out[cfinal[0]]["cup_champion"] = "clinched"
            out[cfinal[1]]["cup_champion"] = "eliminated"
    return out
