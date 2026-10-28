"""A world whose regular season is over, for the bracket and Cup readouts.

Since Phase 2 (season_sim.run_season) the playoff and Cup odds are readouts
of ONE season pass: each iteration seeds its bracket from that iteration's
regular-season standings and its Cup from that iteration's points over
weeks 1-21. So a test of the bracket or the Cup can no longer hand the
driver "today's seeds" -- it builds the world those seeds come from.

decided_world() is that world: weeks 1-15 recorded for all four managers,
the standings Nick 12-3, Hayden 9-6, Benton 6-9, Garrett 3-12 (seeds 1-4,
semifinals Nick-Garrett and Hayden-Benton). Every iteration replays that
regular season, so the bracket every iteration plays is the real one.

It patches the three seams the pass reads through:
  * season_sim.week_score_matrices          -- the scripted weeks
  * simulator_playoff_odds.resolve_completed_week -- what is already played
    (bracket AND Cup weeks: _decided_weeks and the Cup both read it)
  * projections.load_all_team_projections    -- no rosters needed
"""
from types import SimpleNamespace

import numpy as np

from modules import roster_plan
from modules.data_loader import MANAGERS, Record

STANDINGS = {"Nick": Record(12, 3, 0), "Hayden": Record(9, 6, 0),
             "Benton": Record(6, 9, 0), "Garrett": Record(3, 12, 0)}
POINTS = {"Nick": 24000.0, "Hayden": 23000.0, "Benton": 22000.0, "Garrett": 21000.0}


def matrices(scores_by_week, calls=None):
    """A stand-in for week_score_matrices: every simulation of week w scores
    scores_by_week[w] (a callable gets (week, manager, n) for noisy weeks).
    Records which weeks it was asked to simulate."""
    def fake(data, projections, weeks, injury_statuses=None, seed=None, num_simulations=1, **kw):
        if calls is not None:
            calls.append(list(weeks))
        if callable(scores_by_week):
            return {w: {m: scores_by_week(w, m, num_simulations) for m in MANAGERS} for w in weeks}
        return {w: {m: np.full(num_simulations, float(scores_by_week[w][m])) for m in MANAGERS}
                for w in weeks}
    return fake


def decided_world(monkeypatch, scores_by_week, decided=None, calls=None,
                  standings=None, points=None):
    """Patch the pass's seams and return a data object whose regular season is
    decided. scores_by_week: {week: {manager: score}} or callable(w, m, n);
    decided: {week: {manager: score}} for bracket/Cup weeks already played."""
    import modules.projections as proj
    import modules.season_sim as ss
    import modules.simulator_playoff_odds as spo

    standings = dict(standings or STANDINGS)
    points = dict(points or POINTS)
    decided = dict(decided or {})
    monkeypatch.setattr(proj, "load_all_team_projections", lambda data: {})
    monkeypatch.setattr(spo, "resolve_completed_week", lambda data, week: decided.get(week))
    monkeypatch.setattr(ss, "week_score_matrices", matrices(scores_by_week, calls))
    return SimpleNamespace(
        schedule={"weeks": []},
        records={"weekly_scores": {m: [{"week": w, "score": points[m] / 15} for w in range(1, 16)]
                                   for m in MANAGERS}},
        current_week=15,
        regular_season_results=lambda include_playoffs=False: (
            dict(standings), {m: {} for m in MANAGERS}, dict(points)),
        get_manager_record=lambda m: standings[m],
        il_slots=roster_plan.no_il(16),      # this world's IL state: nobody in a slot
    )
