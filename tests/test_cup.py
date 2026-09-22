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


def _scripted(scores_by_week, calls=None):
    def fake(data, projections, week_data, injury_statuses=None):
        week = week_data["week"]
        if calls is not None:
            calls.append(week)
        return {m: {"score": scores_by_week[week][m]} for m in MANAGERS}
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
    calls = []
    monkeypatch.setattr(cup, "simulate_week_hifi", _scripted(scores, calls))
    r = cup.simulate_cup(_data(), {}, PAIRS, SEEDS)

    assert calls == [22, 23]
    assert r.cup_winner == "Garrett", "the #4 seed wins it in two games"
    assert r.finish_order[0] == "Garrett" and r.finish_order[1] == "Hayden"
    assert set(r.finish_order[2:]) == {"Nick", "Benton"}, (
        "the week-22 losers place 3rd and 4th no matter how much they score")


def test_the_week_22_losers_still_play_but_cannot_win(monkeypatch):
    scores = {
        22: {"Nick": 100, "Garrett": 1, "Hayden": 100, "Benton": 1},
        23: {"Nick": 1, "Hayden": 2, "Garrett": 999, "Benton": 998},
    }
    monkeypatch.setattr(cup, "simulate_week_hifi", _scripted(scores))
    r = cup.simulate_cup(_data(), {}, PAIRS, SEEDS)
    assert r.cup_winner == "Hayden"
    assert r.finish_order[2] == "Garrett", "the consolation game orders 3rd/4th"
    assert r.finish_order[3] == "Benton"


def test_a_played_cup_week_is_not_re_rolled(monkeypatch):
    decided = {22: {"Nick": 200, "Garrett": 1, "Hayden": 200, "Benton": 1}}
    scores = {23: {"Nick": 100, "Hayden": 1, "Garrett": 5, "Benton": 4}}
    calls = []
    monkeypatch.setattr(cup, "simulate_week_hifi", _scripted(scores, calls))
    r = cup.simulate_cup(_data(), {}, PAIRS, SEEDS, decided=decided)
    assert calls == [23]
    assert r.cup_winner == "Nick"


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
    monkeypatch.setattr(cup, "simulate_week_hifi",
                        _scripted({22: {m: 10 for m in MANAGERS},
                                   23: {m: 10 for m in MANAGERS}}))
    monkeypatch.setattr(cup, "resolve_completed_week", lambda data, week: None)
    data = _data(_scores({m: {1: 100} for m in MANAGERS}))
    result = cup.run_cup_odds_simulation(data, num_simulations=5)

    stakes = result.keeper_stakes
    assert stakes["season_affected"] == "2027-28"
    assert stakes["recorded_winner"] is None
    assert "cup_winners" in stakes["note"]
    assert stakes["winner_keepers"] == stakes["base_keepers"] + 1


def test_odds_sum_to_one_hundred(monkeypatch):
    monkeypatch.setattr(cup, "load_all_team_projections", lambda data: {})
    monkeypatch.setattr(cup, "resolve_completed_week", lambda data, week: None)
    import random as _r
    def noisy(data, projections, week_data, injury_statuses=None):
        return {m: {"score": _r.uniform(0, 100)} for m in MANAGERS}
    monkeypatch.setattr(cup, "simulate_week_hifi", noisy)

    data = _data(_scores({"Nick": {1: 400}, "Garrett": {1: 300},
                          "Benton": {1: 200}, "Hayden": {1: 100}}))
    result = cup.run_cup_odds_simulation(data, num_simulations=200, seed=7)
    assert abs(sum(result.cup_odds.values()) - 100.0) < 1e-6
    for m in MANAGERS:
        dist = result.finish_distribution[m]
        assert abs(sum(dist.values()) - 100.0) < 1e-6
    assert result.round_weeks[SEMI] == [22, 22]
