"""The Cup: weeks 22-23, seeded on POINTS, and the winner keeps a sixth player.

The Cup is the one result in this league that changes next season's rules, so
two things have to hold:

  * seeding is total points over weeks 1-21 -- the regular season AND the
    playoff bracket -- not the standings. A manager who lost in the
    semifinals can still be the #1 Cup seed, and reusing the playoff seeds
    here would quietly produce the wrong bracket.
  * the winner has to be recorded, because data_loader.keepers_for() refuses
    to guess who gets the extra keeper.
"""
from types import SimpleNamespace

import pytest

import modules.simulator_cup_odds as cup
import modules.data_loader as dl
from modules.data_loader import MANAGERS


SEMI = cup.CUP_SEMIFINAL_ROUND
FINAL = cup.CUP_FINAL_ROUND


def _data(weekly_scores=None, weeks=None, current_week=99):
    return SimpleNamespace(
        schedule={"weeks": weeks or []},
        records={"weekly_scores": weekly_scores or {}},
        current_week=current_week,
        get_manager_record=lambda m: (0, 0),
    )


def _scores(per_manager_per_week):
    """{manager: [{week, score}, ...]} from {manager: {week: score}}."""
    return {m: [{"week": w, "score": s} for w, s in weeks.items()]
            for m, weeks in per_manager_per_week.items()}


def _matrices(scores_by_week, calls=None):
    """A stand-in for week_score_matrices: every simulation of week w scores
    scores_by_week[w] (a callable gets (week, manager, n) for noisy weeks)."""
    import numpy as np

    def fake(data, projections, weeks, injury_statuses=None, seed=None, num_simulations=1, **kw):
        if calls is not None:
            calls.append(list(weeks))
        if callable(scores_by_week):
            return {w: {m: scores_by_week(w, m, num_simulations) for m in MANAGERS} for w in weeks}
        return {w: {m: np.full(num_simulations, float(scores_by_week[w][m])) for m in MANAGERS}
                for w in weeks}
    return fake


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_the_cup_is_two_weeks_of_single_games():
    rounds = cup.cup_rounds()
    assert rounds[SEMI] == (22, 22)
    assert rounds[FINAL] == (23, 23)
    assert cup.cup_weeks() == [22, 23]
    for name, (first, last) in rounds.items():
        assert first == last, f"{name} is a single game, not a series"


def test_no_cup_before_2026_27():
    assert cup.cup_rounds("2025-26") == {}
    assert cup.cup_weeks("2025-26") == []


def test_running_a_cup_for_a_season_that_has_none_is_an_error(monkeypatch):
    monkeypatch.setattr(cup, "cup_rounds", lambda season=None: {})
    with pytest.raises(ValueError, match="no Cup configured"):
        cup.run_cup_odds_simulation(_data())


# ---------------------------------------------------------------------------
# Seeding is points, over weeks 1-21
# ---------------------------------------------------------------------------

def test_seeding_window_is_everything_before_the_cup():
    assert cup.cup_seeding_weeks() == (1, 21), (
        "the Cup is seeded on weeks 1-21: the regular season plus the bracket")


def test_seeding_ignores_the_cup_weeks_themselves():
    """Week 22 points must not feed back into week 22's own seeding."""
    data = _data(_scores({
        "Nick":    {1: 100, 21: 100, 22: 9999},
        "Hayden":  {1: 150, 21: 150},
        "Benton":  {1: 120, 21: 120},
        "Garrett": {1: 110, 21: 110},
    }))
    points = cup.cup_seeding_points(data)
    assert points["Nick"] == 200, "week 22 leaked into the seeding"
    assert cup.get_cup_seeds(data)["Nick"] == 4


def test_seeding_is_points_not_record():
    """The manager with the most points seeds #1 even having lost every week.

    Nick scores the most every week but is scheduled against whoever scores
    second, so his record is irrelevant here -- and that is the point.
    """
    data = _data(_scores({
        "Nick":    {1: 300, 2: 300},
        "Hayden":  {1: 10,  2: 10},
        "Benton":  {1: 20,  2: 20},
        "Garrett": {1: 30,  2: 30},
    }))
    seeds = cup.get_cup_seeds(data)
    assert seeds == {"Nick": 1, "Garrett": 2, "Benton": 3, "Hayden": 4}


def test_seeds_pair_one_four_and_two_three():
    data = _data(_scores({
        "Nick":    {1: 400}, "Garrett": {1: 300},
        "Benton":  {1: 200}, "Hayden":  {1: 100},
    }))
    seeds = cup.get_cup_seeds(data)
    pairs, _ = cup.get_cup_semifinal_matchups(data, seeds)
    assert {(p["manager_a"], p["manager_b"]) for p in pairs} == \
           {("Nick", "Hayden"), ("Garrett", "Benton")}


def test_the_schedule_wins_only_when_it_holds_the_seeded_cup():
    data = _data(_scores({
        "Nick":    {1: 400}, "Garrett": {1: 300},
        "Benton":  {1: 200}, "Hayden":  {1: 100},
    }))
    seeds = cup.get_cup_seeds(data)          # Nick 1, Garrett 2, Benton 3, Hayden 4
    sched = [{"week": 22, "matchups": [
        {"manager_a": "Nick", "manager_b": "Hayden"},
        {"manager_a": "Garrett", "manager_b": "Benton"}]}]
    data.schedule = {"weeks": sched}
    pairs, source = cup.get_cup_semifinal_matchups(data, seeds)
    assert "SCHEDULE.json" in source
    assert {(p["manager_a"], p["manager_b"]) for p in pairs} == \
           {("Nick", "Hayden"), ("Garrett", "Benton")}


def test_a_round_robin_in_the_cup_weeks_does_not_become_the_cup():
    """Yahoo cannot generate this bracket -- the Cup is seeded on POINTS."""
    data = _data(_scores({
        "Nick":    {1: 400}, "Garrett": {1: 300},
        "Benton":  {1: 200}, "Hayden":  {1: 100},
    }))
    seeds = cup.get_cup_seeds(data)
    data.schedule = {"weeks": [{"week": 22, "matchups": [
        {"manager_a": "Nick", "manager_b": "Benton"},
        {"manager_a": "Garrett", "manager_b": "Hayden"}]}]}
    pairs, source = cup.get_cup_semifinal_matchups(data, seeds)
    assert "points seeding" in source and "not the seeded Cup bracket" in source
    assert {(p["manager_a"], p["manager_b"]) for p in pairs} == \
           {("Nick", "Hayden"), ("Garrett", "Benton")}


# ---------------------------------------------------------------------------
# Single elimination
# ---------------------------------------------------------------------------

SEEDS = {"Nick": 1, "Hayden": 2, "Benton": 3, "Garrett": 4}
PAIRS = [("Nick", "Garrett"), ("Hayden", "Benton")]


def test_one_bad_week_ends_it(monkeypatch):
    """No second chance: the Cup is single games, unlike the bracket."""
    scores = {
        22: {"Nick": 1, "Garrett": 100, "Hayden": 100, "Benton": 1},
        23: {"Garrett": 100, "Hayden": 1, "Nick": 500, "Benton": 500},
    }
    r = cup.simulate_cup(PAIRS, SEEDS, scores)

    assert sorted(r.scores_by_week) == [22, 23]
    assert r.cup_winner == "Garrett", "the #4 seed wins it in two games"
    assert r.finish_order[0] == "Garrett" and r.finish_order[1] == "Hayden"
    assert set(r.finish_order[2:]) == {"Nick", "Benton"}, (
        "the week-22 losers place 3rd and 4th no matter how much they score")


def test_the_week_22_losers_still_play_but_cannot_win(monkeypatch):
    scores = {
        22: {"Nick": 100, "Garrett": 1, "Hayden": 100, "Benton": 1},
        23: {"Nick": 1, "Hayden": 2, "Garrett": 999, "Benton": 998},
    }
    r = cup.simulate_cup(PAIRS, SEEDS, scores)
    assert r.cup_winner == "Hayden"
    assert r.finish_order[2] == "Garrett", "the consolation game orders 3rd/4th"
    assert r.finish_order[3] == "Benton"


def test_a_played_cup_week_is_not_re_rolled(monkeypatch):
    decided = {22: {"Nick": 200, "Garrett": 1, "Hayden": 200, "Benton": 1}}
    scores = {23: {"Nick": 100, "Hayden": 1, "Garrett": 5, "Benton": 4}}
    r = cup.simulate_cup(PAIRS, SEEDS, scores, decided=decided)
    assert r.cup_winner == "Nick"
    # and the run only simulates the week still to come
    calls = []
    monkeypatch.setattr(cup, "load_all_team_projections", lambda data: {})
    monkeypatch.setattr(cup, "resolve_completed_week", lambda data, week: decided.get(week))
    monkeypatch.setattr(cup, "week_score_matrices", _matrices(scores, calls))
    data = _data(_scores({m: {1: 100 + i} for i, m in enumerate(MANAGERS)}))
    cup.run_cup_odds_simulation(data, num_simulations=4, seed=1)
    assert calls == [[23]], "the played Cup week was rolled again"


def test_a_cup_week_neither_decided_nor_simulated_raises():
    with pytest.raises(KeyError, match="23"):
        cup.simulate_cup(PAIRS, SEEDS, {22: {m: 10 + i for i, m in enumerate(MANAGERS)}})


# ---------------------------------------------------------------------------
# What the Cup is for
# ---------------------------------------------------------------------------

def test_the_cup_decides_next_seasons_sixth_keeper(monkeypatch):
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2026-27", "Hayden")
    assert dl.keepers_for("2027-28", "Hayden") == 6
    assert dl.keepers_for("2027-28", "Nick") == 5
    assert dl.live_picks_for("2027-28", "Hayden") == 9
    assert dl.live_picks_for("2027-28", "Nick") == 10


def test_next_season_is_computed_not_hardcoded():
    assert cup._next_season("2026-27") == "2027-28"
    assert cup._next_season("2029-30") == "2030-31"
    assert cup._next_season("2099-00") == "2100-01"


def test_an_unrecorded_cup_winner_is_flagged_loudly(monkeypatch):
    """The sim must say out loud that the result has to be written down."""
    captured = {}

    def fake_run(data, **kw):
        return None

    monkeypatch.setattr(cup, "load_all_team_projections", lambda data: {})
    monkeypatch.setattr(cup, "week_score_matrices",
                        _matrices({22: {m: 10 for m in MANAGERS},
                                   23: {m: 10 for m in MANAGERS}}))
    monkeypatch.setattr(cup, "resolve_completed_week", lambda data, week: None)
    # distinct totals: this test is about the keeper note, not seeding ties
    data = _data(_scores({m: {1: 100 + i} for i, m in enumerate(MANAGERS)}))
    result = cup.run_cup_odds_simulation(data, num_simulations=5)

    stakes = result.keeper_stakes
    assert stakes["season_affected"] == "2027-28"
    assert stakes["recorded_winner"] is None
    assert "cup_winners" in stakes["note"]
    assert stakes["winner_keepers"] == stakes["base_keepers"] + 1


def test_odds_sum_to_one_hundred(monkeypatch):
    monkeypatch.setattr(cup, "load_all_team_projections", lambda data: {})
    monkeypatch.setattr(cup, "resolve_completed_week", lambda data, week: None)
    import numpy as np
    rng = np.random.default_rng(0)
    monkeypatch.setattr(cup, "week_score_matrices",
                        _matrices(lambda w, m, n: rng.uniform(0, 100, n)))

    data = _data(_scores({"Nick": {1: 400}, "Garrett": {1: 300},
                          "Benton": {1: 200}, "Hayden": {1: 100}}))
    result = cup.run_cup_odds_simulation(data, num_simulations=200, seed=7)
    assert abs(sum(result.cup_odds.values()) - 100.0) < 1e-6
    for m in MANAGERS:
        dist = result.finish_distribution[m]
        assert abs(sum(dist.values()) - 100.0) < 1e-6
    assert result.round_weeks[SEMI] == [22, 22]


def test_seeding_tie_goes_to_the_better_regular_season_finish(monkeypatch):
    """Nick, 10-07: Cup seeding tied on total points -> regular-season
    finish. (It used to break on best single week, then on name.)"""
    import modules.simulator_playoff_odds as po
    data = _data(_scores({
        "Nick":    {1: 100, 2: 100},
        "Hayden":  {1: 150, 2: 50},
        "Benton":  {1: 10,  2: 10},
        "Garrett": {1: 5,   2: 5},
    }))
    monkeypatch.setattr(po, "rank_managers_by_standings",
                        lambda d: ["Hayden", "Benton", "Nick", "Garrett"])
    seeds = cup.get_cup_seeds(data)
    assert seeds["Hayden"] == 1 and seeds["Nick"] == 2


def test_unspecified_rules_raise():
    from modules.data_loader import league_rule, UnspecifiedRule
    assert league_rule("tiebreaker_rules", "series_week") == "higher_seed"
    assert league_rule("tiebreaker_rules", "cup_game") == "higher_seed"
    assert league_rule("payouts", "playoff_third_place", "total") == 0
    assert league_rule("payouts", "cup_third_place", "total") == 0
    with pytest.raises(UnspecifiedRule):
        league_rule("tiebreaker_rules", "a_rule_nobody_made")
