"""The playoff bracket is six weeks of best-of-3 series, not two single games.

Three things in here have to be right or the odds are worse than useless:

  * a series is decided by WEEK WINS, not by total points. A manager can lose
    a series 2-1 while outscoring their opponent over the three weeks.
  * every week of a series is played even after the series is decided. The
    league does this deliberately, and those points still count toward the
    Cup seeding, so a sim that stops at 2-0 loses real games.
  * weeks that have already happened must be read, not re-rolled. Mid-series
    is now a six-week window rather than a one-week one, so this is the
    normal state of the world rather than an edge case.
"""
from types import SimpleNamespace

import pytest

import modules.simulator_playoff_odds as spo
from modules.data_loader import MANAGERS, Record


SEMI = spo.SEMIFINAL_ROUND
FINAL = spo.FINAL_ROUND
THIRD = spo.THIRD_PLACE_ROUND

SEEDS = {"Nick": 1, "Hayden": 2, "Benton": 3, "Garrett": 4}
PAIRS = [("Nick", "Garrett"), ("Hayden", "Benton")]


def _data(weeks=None, current_week=99):
    return SimpleNamespace(
        schedule={"weeks": weeks or []},
        records={},
        current_week=current_week,
        get_manager_record=lambda m: Record(),
    )


def _matrices(scores_by_week, n=1, calls=None):
    """A stand-in for week_score_matrices: every simulation of week w scores
    scores_by_week[w]. Records which weeks it was asked to simulate."""
    import numpy as np

    def fake(data, projections, weeks, injury_statuses=None, seed=None, num_simulations=1, **kw):
        if calls is not None:
            calls.append(list(weeks))
        return {w: {m: np.full(num_simulations, float(scores_by_week[w][m])) for m in MANAGERS}
                for w in weeks}
    return fake


def _run(monkeypatch, scores, decided=None, n=3):
    """run_playoff_odds_simulation on scripted weeks; returns (result, calls)."""
    calls = []
    monkeypatch.setattr(spo, "load_all_team_projections", lambda data: {})
    monkeypatch.setattr(spo, "_decided_weeks", lambda data: dict(decided or {}))
    monkeypatch.setattr(spo, "get_playoff_seeds", lambda data: dict(SEEDS))
    monkeypatch.setattr(spo, "get_semifinal_matchups", lambda data, seeds: (
        [{"manager_a": a, "manager_b": b} for a, b in PAIRS], "test"))
    monkeypatch.setattr(spo, "week_score_matrices", _matrices(scores, calls=calls))
    return spo.run_playoff_odds_simulation(_data(current_week=15), num_simulations=n, seed=1), calls


def _flat(week_scores):
    """{week: {manager: score}} from {week: {manager: score}} shorthand."""
    return {w: dict(s) for w, s in week_scores.items()}


# ---------------------------------------------------------------------------
# Best-of-3, not best-of-1, and not total points
# ---------------------------------------------------------------------------

def test_a_series_is_won_on_week_wins_not_total_points(monkeypatch):
    """Nick wins weeks 17 and 18 narrowly; Garrett wins week 16 by a mile.

    Garrett outscores Nick 300 to 210 across the series and still loses it
    2-1. Summing points would hand him the series and the wrong manager the
    championship odds.
    """
    scores = {
        16: {"Nick": 50,  "Garrett": 200, "Hayden": 100, "Benton": 90},
        17: {"Nick": 80,  "Garrett": 50,  "Hayden": 100, "Benton": 90},
        18: {"Nick": 80,  "Garrett": 50,  "Hayden": 100, "Benton": 90},
        19: {"Nick": 100, "Garrett": 10,  "Hayden": 50,  "Benton": 10},
        20: {"Nick": 100, "Garrett": 10,  "Hayden": 50,  "Benton": 10},
        21: {"Nick": 100, "Garrett": 10,  "Hayden": 50,  "Benton": 10},
    }
    r = spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(scores))

    assert sum(scores[w]["Garrett"] for w in (16, 17, 18)) > \
           sum(scores[w]["Nick"] for w in (16, 17, 18))
    assert "Nick" in r.semi_winners and "Garrett" in r.semi_losers

    semi = [s for s in r.series if s.round_name == SEMI and s.manager_a == "Nick"][0]
    assert semi.games == "2-1"


def test_every_week_of_a_decided_series_is_still_played(monkeypatch):
    """A 2-0 lead does not end the series: week 18 is played anyway."""
    # Every manager needs a DISTINCT score. The old fixture gave Nick and
    # Hayden 100 each and Garrett and Benton 1 each, so the Final and the
    # third-place series were tied every week -- and a tied SIMULATED week is
    # a coin flip by project convention (see _play_series), not a seed
    # lookup. Both tied series had to sweep by chance for the 3-0 assertion
    # to hold, about a 6% pass rate. The test was flaky, not the bracket.
    scores = {w: {"Nick": 100, "Hayden": 90, "Benton": 10, "Garrett": 1}
              for w in range(16, 22)}
    r = spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(scores))

    assert sorted(r.scores_by_week) == [16, 17, 18, 19, 20, 21], "all six weeks must be played"
    for s in r.series:
        assert len(s.week_winners) == 3, f"{s.round_name} played {len(s.week_winners)} weeks"
        assert s.games == "3-0"


def test_both_pairings_share_one_simulation_per_week(monkeypatch):
    """One week is one roll of the world, not one per matchup -- and now one
    precompute for the whole run, not one per iteration."""
    scores = {w: {m: 10 + i for i, m in enumerate(MANAGERS)} for w in range(16, 22)}
    _r, calls = _run(monkeypatch, scores, n=50)
    assert calls == [[16, 17, 18, 19, 20, 21]], "simulated once, every week, for all 50 iterations"


# ---------------------------------------------------------------------------
# Played weeks are read, not re-rolled
# ---------------------------------------------------------------------------

def test_completed_weeks_are_never_re_simulated(monkeypatch):
    decided = _flat({
        16: {"Nick": 200, "Garrett": 1, "Hayden": 200, "Benton": 1},
        17: {"Nick": 200, "Garrett": 1, "Hayden": 200, "Benton": 1},
        18: {"Nick": 200, "Garrett": 1, "Hayden": 200, "Benton": 1},
    })
    scores = {w: {"Nick": 100, "Garrett": 100, "Hayden": 1, "Benton": 1}
              for w in range(19, 22)}
    r = spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(scores), decided=decided)
    assert set(r.semi_winners) == {"Nick", "Hayden"}
    assert r.champ_winner == "Nick"
    _r, calls = _run(monkeypatch, scores, decided=decided)
    assert calls == [[19, 20, 21]], "the played semifinal weeks were rolled again"


def test_a_decided_week_beats_a_simulated_one_for_the_same_week():
    decided = _flat({16: {"Nick": 1, "Garrett": 500, "Hayden": 500, "Benton": 1}})
    sim = {w: {"Nick": 100, "Garrett": 1, "Hayden": 1, "Benton": 100} for w in range(16, 22)}
    r = spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(sim), decided=decided)
    assert r.scores_by_week[16] == decided[16]


def test_a_week_neither_decided_nor_simulated_raises():
    sim = {w: {m: 10 for m in MANAGERS} for w in range(16, 21)}      # 21 missing
    with pytest.raises(KeyError, match="21"):
        spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(sim))


def test_an_eliminated_manager_cannot_win_the_bracket(monkeypatch):
    """The reason the lock above matters, stated as an outcome."""
    decided = _flat({w: {"Nick": 200, "Garrett": 1, "Hayden": 200, "Benton": 1}
                     for w in (16, 17, 18)})
    scores = {w: {"Garrett": 999, "Benton": 999, "Nick": 1, "Hayden": 1}
              for w in range(19, 22)}
    r = spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(scores), decided=decided)
    assert r.champ_winner in ("Nick", "Hayden")
    assert r.finish_order[:2] == ["Nick", "Hayden"] or r.finish_order[:2] == ["Hayden", "Nick"]
    assert set(r.finish_order[2:]) == {"Garrett", "Benton"}


# ---------------------------------------------------------------------------
# Finish order and the third-place series
# ---------------------------------------------------------------------------

def test_third_place_is_a_series_in_the_same_weeks_as_the_final(monkeypatch):
    scores = {w: {"Nick": 100, "Garrett": 1, "Hayden": 100, "Benton": 1}
              for w in range(16, 22)}
    r = spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(scores))

    by_round = {s.round_name: s for s in r.series}
    assert by_round[THIRD].weeks == by_round[FINAL].weeks == (19, 21)
    assert {by_round[THIRD].manager_a, by_round[THIRD].manager_b} == set(r.semi_losers)
    assert r.finish_order == [r.champ_winner, r.champ_loser,
                              r.consolation_winner, r.consolation_loser]
    assert sorted(r.finish_order) == sorted(MANAGERS)


def test_series_scores_are_round_totals_not_single_weeks(monkeypatch):
    scores = {w: {m: 10 for m in MANAGERS} for w in range(16, 22)}
    r = spo.simulate_playoff_bracket(PAIRS, SEEDS, _flat(scores))
    assert r.semi_scores["Nick"] == 30, "three weeks at 10 points"
    assert r.final_scores["Nick"] == 30
    assert sorted(r.scores_by_week) == [16, 17, 18, 19, 20, 21]


# ---------------------------------------------------------------------------
# Ties
# ---------------------------------------------------------------------------

def test_a_tied_week_goes_to_the_higher_seed():
    assert spo._week_winner(("Nick", "Garrett"), {"Nick": 50, "Garrett": 50},
                            SEEDS, "higher_seed") == "Nick"
    assert spo._week_winner(("Benton", "Hayden"), {"Benton": 50, "Hayden": 50},
                            SEEDS, "higher_seed") == "Hayden"


def test_a_simulated_tied_week_is_not_a_coin_flip():
    """It used to be, on a project-wide convention for simulated results.
    The league rule decides a tied week outright, so a simulated tie has to
    resolve the way a played one does: 200 rolls, one answer. A coin flip
    gave the lower seed half of a week the rules award to the higher one."""
    seen = {spo._week_winner(("Nick", "Garrett"), {"Nick": 50, "Garrett": 50},
                             SEEDS, "higher_seed") for _ in range(200)}
    assert seen == {"Nick"}


def test_an_unknown_tied_week_rule_raises():
    """Code never guesses a tiebreak."""
    with pytest.raises(ValueError):
        spo._week_winner(("Nick", "Garrett"), {"Nick": 50, "Garrett": 50},
                         SEEDS, "coin_flip")


def test_both_competitions_read_their_own_tie_rule():
    """series_week drives the bracket, cup_game the Cup. Same value today;
    separate keys so they cannot drift onto one shared rule."""
    from modules.data_loader import league_rule
    assert league_rule("tiebreaker_rules", "series_week") == "higher_seed"
    assert league_rule("tiebreaker_rules", "cup_game") == "higher_seed"


# ---------------------------------------------------------------------------
# Pairings
# ---------------------------------------------------------------------------

def test_semifinal_pairs_fall_back_to_seeding_when_no_schedule_exists(monkeypatch):
    """Before the bracket is entered there is no SCHEDULE.json entry."""
    monkeypatch.setattr(spo, "get_playoff_seeds", lambda data: SEEDS)
    pairs, source = spo.get_semifinal_matchups(_data(weeks=[]), SEEDS)
    assert {(p["manager_a"], p["manager_b"]) for p in pairs} == \
           {("Nick", "Garrett"), ("Hayden", "Benton")}, "should be 1v4 and 2v3"
    assert "seeding" in source


def test_the_schedule_wins_only_when_it_holds_the_seeded_bracket():
    """SCHEDULE.json is authoritative once the real bracket is in it."""
    sched = [{"week": 16, "matchups": [
        {"manager_a": "Nick", "manager_b": "Garrett"},
        {"manager_a": "Hayden", "manager_b": "Benton"}]}]
    pairs, source = spo.get_semifinal_matchups(_data(weeks=sched), SEEDS)
    assert {(p["manager_a"], p["manager_b"]) for p in pairs} == \
           {("Nick", "Garrett"), ("Hayden", "Benton")}
    assert "SCHEDULE.json" in source


def test_a_round_robin_in_the_bracket_weeks_does_not_become_the_bracket():
    """The real case, and the reason the rule changed.

    Yahoo generates an ordinary round robin for weeks 16-21 -- it does not
    know this league plays a bracket there. Taking those pairings would
    preview #1 vs #2 and #3 vs #4, with the seed labels in the table visibly
    contradicting the matchup.
    """
    sched = [{"week": 16, "matchups": [
        {"manager_a": "Nick", "manager_b": "Benton"},     # 1 vs 3
        {"manager_a": "Hayden", "manager_b": "Garrett"}]}]  # 2 vs 4
    pairs, source = spo.get_semifinal_matchups(_data(weeks=sched), SEEDS)
    assert {(p["manager_a"], p["manager_b"]) for p in pairs} == \
           {("Nick", "Garrett"), ("Hayden", "Benton")}, "seeding must win"
    assert "not the seeded bracket" in source, (
        "the report has to say which pairing it used and why")


# ---------------------------------------------------------------------------
# The shape comes from config, not from this module
# ---------------------------------------------------------------------------

def test_no_week_numbers_are_hardcoded_in_the_simulator():
    import inspect
    import re
    src = inspect.getsource(spo)
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    # strip docstrings crudely: they are the only triple-quoted blocks
    body = re.sub(r'""".*?"""', "", body, flags=re.S)
    offenders = re.findall(r"\b(?:week|WEEK)\w*\s*=\s*(1[5-9]|2[0-3])\b", body)
    assert offenders == [], (
        f"week numbers must come from bracket_rounds(), found {offenders}")


def test_bracket_shape_matches_config():
    rounds = spo.bracket_rounds()
    assert rounds[SEMI] == (16, 18)
    assert rounds[FINAL] == (19, 21)
    assert rounds[THIRD] == (19, 21)
    assert spo.bracket_weeks() == [16, 17, 18, 19, 20, 21], (
        "the Final and Third Place share weeks; they must not be counted twice")


def test_legacy_seasons_still_describe_a_two_week_bracket():
    assert spo.bracket_rounds("2025-26") == {
        SEMI: (22, 22), FINAL: (23, 23), THIRD: (23, 23)}
    assert spo.bracket_weeks("2025-26") == [22, 23]
    assert spo.bracket_rounds("2019-20") == {}, "no bracket was played"


@pytest.mark.parametrize("week,expected", [
    (1, "pre_playoffs"), (15, "pre_playoffs"),
    (16, "semifinals"), (18, "semifinals"),
    (19, "final"), (21, "final"),
    (22, "complete"), (23, "complete"),
])
def test_playoff_round_labels(week, expected):
    assert spo.playoff_round_for_week(week) == expected
