"""Keyed draws in the playoff and Cup odds (HANDOFF_KEYED_BRACKET_DRAWS_2026-10-20).

The brackets used to re-simulate every week on every iteration, off the global
`random` stream: a roster change for one manager moved every number for every
manager. Now each bracket week is one keyed matrix, computed once, read at
index i -- the same week, column for column, that a betting line prices.
"""
import inspect
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from modules import roster_plan
from modules import simulator_betting as sb
from modules import simulator_cup_odds as cup
from modules import simulator_playoff_odds as spo
from modules.data_loader import FantasyData, MANAGERS, Record
from modules.projections import PlayerProjection, TeamProjections

TEAMS = ["BOS", "NYK", "LAL", "GSW", "MIA", "DEN", "PHX", "DAL", "MIL", "OKC"]
POS = ["PG", "SG", "SF", "PF", "C", "PG,SG", "SF,PF", "PF,C"]
FIRST = date(2027, 2, 1)                      # week 16 in this synthetic season
SEEDS = {"Nick": 1, "Hayden": 2, "Benton": 3, "Garrett": 4}
PAIRS = [("Nick", "Garrett"), ("Hayden", "Benton")]


def _world(seed=0):
    rng = random.Random(seed)
    weeks, games = [], []
    for w in range(16, 24):
        d0 = FIRST + timedelta(days=7 * (w - 16))
        weeks.append({"week": w, "start_date": d0.isoformat(),
                      "end_date": (d0 + timedelta(days=6)).isoformat(),
                      "matchups": [{"manager_a": a, "manager_b": b} for a, b in PAIRS]})
        for k in range(7):
            playing = rng.sample(TEAMS, 2 * rng.randint(2, 5))
            games += [{"date": (d0 + timedelta(days=k)).isoformat(), "home": playing[j],
                       "away": playing[j + 1]} for j in range(0, len(playing), 2)]
    teams = {}
    for m in MANAGERS:
        ps = {}
        for j in range(15):          # a full 15: the roster plan has no spot to fill
            n = f"{m}{j}"
            ps[n] = PlayerProjection(player_name=n, nba_team=rng.choice(TEAMS),
                                     positions=rng.choice(POS).split(","),
                                     projected_fppg=round(rng.uniform(12, 50), 1), projected_gp=70.0)
        teams[m] = TeamProjections(m, ps, weekly_std_dev=140.0)
    scores = {m: [{"week": 1, "score": 1000.0 + 10 * i}] for i, m in enumerate(MANAGERS)}
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games},
                       records={"weekly_scores": scores}, current_week=15)
    data.il_slots = roster_plan.no_il(16)       # this world's IL state: nobody in a slot
    return data, teams


@pytest.fixture
def world(monkeypatch):
    """The synthetic league with its regular season decided (weeks 1-15
    recorded, seeds = SEEDS). Since Phase 2 the bracket and the Cup are
    readouts of one season pass, which seeds every iteration from that
    iteration's standings -- so the world carries the standings, not a
    patched get_playoff_seeds."""
    import modules.projections as proj
    data, teams = _world()
    data.records["weekly_scores"] = {
        m: [{"week": w, "score": 1000.0 + 10 * i} for w in range(1, 16)]
        for i, m in enumerate(MANAGERS)}
    standings = {"Nick": Record(12, 3, 0), "Hayden": Record(9, 6, 0),
                 "Benton": Record(6, 9, 0), "Garrett": Record(3, 12, 0)}
    data.get_manager_record = lambda m, include_playoffs=False: standings[m]
    data.regular_season_results = lambda include_playoffs=False: (
        dict(standings), {m: {} for m in MANAGERS},
        {m: 15 * (1000.0 + 10 * i) for i, m in enumerate(MANAGERS)})
    box = {"teams": teams}
    monkeypatch.setattr(proj, "load_all_team_projections", lambda d: box["teams"])
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    return data, box


def _playoff(data, n=400, seed=5):
    r = spo.run_playoff_odds_simulation(data, num_simulations=n, seed=seed)
    return r.title_odds, r.finish_distribution


def _cup(data, n=400, seed=5):
    r = cup.run_cup_odds_simulation(data, num_simulations=n, seed=seed)
    return r.cup_odds, r.finish_distribution


def _stronger(teams, manager):
    out = dict(teams)
    tp = teams[manager]
    out[manager] = TeamProjections(manager, {n: PlayerProjection(
        player_name=n, nba_team=p.nba_team, positions=p.positions,
        projected_fppg=p.projected_fppg * 1.3, projected_gp=70.0) for n, p in tp.players.items()},
        weekly_std_dev=tp.weekly_std_dev)
    return out


# Isolation -- the point of the port
def test_another_managers_roster_never_moves_your_week():
    data, teams = _world()
    weeks = list(range(16, 22))
    a = sb.week_score_matrices(data, teams, weeks, None, seed=9, num_simulations=500)
    b = sb.week_score_matrices(data, _stronger(teams, "Nick"), weeks, None, seed=9, num_simulations=500)
    for w in weeks:
        assert not np.array_equal(a[w]["Nick"], b[w]["Nick"])
        for m in ("Hayden", "Benton", "Garrett"):
            assert np.array_equal(a[w][m], b[w][m]), (w, m)


def test_a_series_without_the_changed_manager_is_decided_identically():
    """Odds of OTHER managers can move -- they play Nick -- but a series Nick
    is not in comes out the same in every iteration."""
    data, teams = _world()
    weeks = list(range(16, 22))
    a = sb.week_score_matrices(data, teams, weeks, None, seed=9, num_simulations=300)
    b = sb.week_score_matrices(data, _stronger(teams, "Nick"), weeks, None, seed=9, num_simulations=300)
    for i in range(300):
        ra = spo.simulate_playoff_bracket(PAIRS, SEEDS, sb.scores_at(a, i))
        rb = spo.simulate_playoff_bracket(PAIRS, SEEDS, sb.scores_at(b, i))
        hb = lambda r: [s for s in r.series if {s.manager_a, s.manager_b} == {"Hayden", "Benton"}][0]
        assert hb(ra).week_winners == hb(rb).week_winners


# One week, one simulated truth (Nick, 10-20)
@pytest.mark.parametrize("tagged", [False, True])
def test_a_bracket_week_is_the_betting_lines_week(tagged):
    """Week 16 at n = 10,000 through the bracket path; the same week at
    n = 5,000 through the betting path. The first 5,000 columns must agree
    bit for bit -- including a tag reaching that week. A competition or
    round tag in the key would break this."""
    data, teams = _world()
    statuses = {"Nick0": "O", "Hayden3": "Q"} if tagged else None
    bracket = sb.week_score_matrices(data, teams, [16], statuses, seed=20262027, num_simulations=10000)
    week16 = data.schedule["weeks"][0]
    line_week = sb.simulate_week_matrix(data, teams, week16, statuses, sb.KeyedDraws(20262027, 5000))
    for m in MANAGERS:
        assert np.array_equal(bracket[16][m][:5000], line_week[m]["score"]), m
    line = sb.run_matchup_simulation(data, teams, week16, "Nick", "Garrett", 5000, statuses, seed=20262027)
    assert line.remaining_mean_a == float(bracket[16]["Nick"][:5000].mean())


# Pairing independence
def test_who_plays_whom_never_changes_a_simulated_week():
    data, teams = _world()
    wd = dict(data.schedule["weeks"][0])
    other = dict(wd, matchups=[{"manager_a": "Nick", "manager_b": "Hayden"},
                               {"manager_a": "Benton", "manager_b": "Garrett"}])
    none = {k: v for k, v in wd.items() if k != "matchups"}
    outs = [sb.simulate_week_matrix(data, teams, x, None, sb.KeyedDraws(3, 300)) for x in (wd, other, none)]
    for m in MANAGERS:
        assert np.array_equal(outs[0][m]["score"], outs[1][m]["score"])
        assert np.array_equal(outs[0][m]["score"], outs[2][m]["score"])
    assert "matchups" not in sb.schedule_week(data, 16)


# No global random
def test_stdlib_random_cannot_move_the_odds(world):
    data, _ = world
    random.seed(1); p1 = _playoff(data); c1 = _cup(data)
    random.seed(999); [random.random() for _ in range(17)]
    p2 = _playoff(data); c2 = _cup(data)
    assert p1 == p2 and c1 == c2


def test_neither_bracket_module_draws_from_stdlib_random():
    from modules import season_sim
    for mod in (spo, cup, season_sim):
        src = inspect.getsource(mod)
        assert "import random" not in src and "random." not in src.replace("stdlib `random`", ""), mod.__name__


def test_different_seeds_still_differ(world):
    data, _ = world
    assert _playoff(data, seed=1) != _playoff(data, seed=2)


# Order independence
def test_cup_then_playoffs_equals_playoffs_then_cup(world):
    data, _ = world
    p1 = _playoff(data); c1 = _cup(data)
    c2 = _cup(data); p2 = _playoff(data)
    assert p1 == p2 and c1 == c2


# Prefix stability end to end
def test_the_first_n_brackets_are_the_same_at_n_and_2n():
    data, teams = _world()
    weeks = list(range(16, 22))
    small = sb.week_score_matrices(data, teams, weeks, None, seed=4, num_simulations=300)
    big = sb.week_score_matrices(data, teams, weeks, None, seed=4, num_simulations=600)
    for i in range(300):
        a = spo.simulate_playoff_bracket(PAIRS, SEEDS, sb.scores_at(small, i))
        b = spo.simulate_playoff_bracket(PAIRS, SEEDS, sb.scores_at(big, i))
        assert a.finish_order == b.finish_order


def test_odds_at_n_and_2n_agree_within_monte_carlo_error(world):
    data, _ = world
    small, _f = _playoff(data, n=2000, seed=8)
    big, _f = _playoff(data, n=4000, seed=8)
    for m in MANAGERS:
        p = big[m] / 100
        se = (p * (1 - p) / 2000) ** 0.5 * 100
        assert abs(small[m] - big[m]) <= 4 * se + 0.5, (m, small[m], big[m])


# The run simulates each week once, not once per iteration
def test_each_bracket_week_is_simulated_once_per_run(world, monkeypatch):
    data, _ = world
    calls = []
    real = sb.simulate_week_matrix

    def count(*a, **k):
        calls.append(a[2]["week"])
        return real(*a, **k)
    monkeypatch.setattr(sb, "simulate_week_matrix", count)
    spo.run_playoff_odds_simulation(data, num_simulations=500, seed=1)
    cup.run_cup_odds_simulation(data, num_simulations=500, seed=1)
    # Each readout here is its own pass (the playoff one stops after the
    # bracket); within a pass every week is drawn once for all 500
    # iterations. The weekly build makes ONE pass and reads both off it.
    assert calls == [16, 17, 18, 19, 20, 21] + [16, 17, 18, 19, 20, 21, 22, 23]


def test_a_week_missing_from_the_schedule_raises():
    data, teams = _world()
    with pytest.raises(KeyError, match="week 40"):
        sb.week_score_matrices(data, teams, [40], None, seed=1, num_simulations=10)


def test_week_score_matrices_needs_a_seed():
    data, teams = _world()
    with pytest.raises(ValueError, match="seed"):
        sb.week_score_matrices(data, teams, [16], None, seed=None, num_simulations=10)
