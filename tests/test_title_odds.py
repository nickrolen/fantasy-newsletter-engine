"""Title odds, Phase 1: the betting lines' week engine over the whole
regular season (HANDOFF_TITLE_ODDS_2026-10-20).

Nick, 10-21: "If you drop someone and pick someone up on the wire, your title
odds change slightly. It was supposed to be the same thing as betting lines,
but for the whole season." Test 2 below is that sentence.
"""
import inspect
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from modules import fun_facts_generator as ff
from modules import simulator_betting as sb
from modules import season_sim as ss
from modules import simulator_title_odds as sto
from modules.data_loader import FantasyData, MANAGERS, Record
from modules.projections import PlayerProjection, TeamProjections

TEAMS = ["BOS", "NYK", "LAL", "GSW", "MIA", "DEN", "PHX", "DAL", "MIL", "OKC"]
POS = ["PG", "SG", "SF", "PF", "C", "PG,SG", "SF,PF", "PF,C"]
MON = date(2026, 10, 26)
PAIRS = [[("Nick", "Hayden"), ("Benton", "Garrett")], [("Nick", "Benton"), ("Hayden", "Garrett")],
         [("Nick", "Garrett"), ("Hayden", "Benton")]]
WEEKS = 15


def _world(seed=0):
    rng = random.Random(seed)
    weeks, games = [], []
    for w in range(1, WEEKS + 1):
        d0 = MON + timedelta(days=7 * (w - 1))
        weeks.append({"week": w, "start_date": d0.isoformat(),
                      "end_date": (d0 + timedelta(days=6)).isoformat(),
                      "matchups": [{"manager_a": a, "manager_b": b} for a, b in PAIRS[(w - 1) % 3]]})
        for k in range(7):
            playing = rng.sample(TEAMS, 2 * rng.randint(2, 5))
            games += [{"date": (d0 + timedelta(days=k)).isoformat(), "home": playing[j],
                       "away": playing[j + 1]} for j in range(0, len(playing), 2)]
    teams = {}
    for i, m in enumerate(MANAGERS):
        ps = {}
        for j in range(13):
            n = f"{m}{j}"
            ps[n] = PlayerProjection(player_name=n, nba_team=rng.choice(TEAMS),
                                     positions=rng.choice(POS).split(","),
                                     projected_fppg=round(rng.uniform(12, 50) + 0.3 * i, 1), projected_gp=70.0)
        teams[m] = TeamProjections(m, ps, weekly_std_dev=140.0)
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games}, current_week=0)
    data.get_manager_record = lambda m, include_playoffs=False: Record()
    return data, teams


def _odds(data, teams, seed=7, n=400, statuses=None):
    """Most tests here compare one run against another EXACTLY -- same seed,
    swapped rosters, a reseeded stdlib random -- and an exact comparison is
    worth the same at any n, so n is pure cost. 400 keeps the file inside a
    suite that has to run in one command; the two tests that assert a
    MAGNITUDE rather than an equality pass their own, larger n.
    """
    return sto.run_title_odds_simulation(data, n, seed, statuses, teams)


def _swap(teams, manager, drop, add):
    out = dict(teams)
    tp = teams[manager]
    ps = {n: p for n, p in tp.players.items() if n != drop}
    ps[add.player_name] = add
    out[manager] = TeamProjections(manager, ps, weekly_std_dev=tp.weekly_std_dev)
    return out


def _capture(monkeypatch):
    """Spy on the matrices title odds actually reads. Since Phase 2 title
    odds is a readout of the season pass, which draws its weeks through
    season_sim's week_score_matrices -- so that is where the spy goes."""
    seen = []
    real = ss.week_score_matrices

    def spy(*a, **k):
        out = real(*a, **k)
        seen.append(out)
        return out
    monkeypatch.setattr(ss, "week_score_matrices", spy)
    return seen


@pytest.fixture(autouse=True)
def _six_week_regular_season(monkeypatch):
    monkeypatch.setattr(sto, "regular_season_weeks_for", lambda season: WEEKS)


# 1 -- one week, one truth, across all three surfaces
def test_a_title_odds_week_is_the_betting_lines_week(monkeypatch):
    data, teams = _world()
    seen = _capture(monkeypatch)
    statuses = {"Nick0": "O", "Hayden4": "Q"}
    _odds(data, teams, seed=20262027, n=1200, statuses=statuses)
    week1 = data.schedule["weeks"][0]
    line = sb.simulate_week_matrix(data, teams, week1, statuses, sb.KeyedDraws(20262027, 1000))
    for m in MANAGERS:
        assert np.array_equal(seen[0][1][m][:1000], line[m]["score"]), m
    bracket_path = sb.week_score_matrices(data, teams, [3], statuses, 20262027, 1000)
    for m in MANAGERS:
        assert np.array_equal(seen[0][3][m][:1000], bracket_path[3][m]), m


# 2 -- the feature: one wire move moves the number, slightly and reproducibly
def test_one_waiver_move_moves_the_odds_slightly_and_reproducibly():
    """An ordinary wire move in an open race (world 1: Garrett 83%, Benton and
    Nick ~8-9%): Benton drops his worst player for one 4 points a game better
    -- same positions, same NBA team, so it is purely the upgrade. His odds
    rise, by single digits, and by exactly the same amount every run."""
    data, teams = _world(1)
    base = _odds(data, teams, n=600).title_odds
    worst = min(teams["Benton"].players.values(), key=lambda p: p.projected_fppg)
    pickup = PlayerProjection(player_name="WireGuy", nba_team=worst.nba_team, positions=list(worst.positions),
                              projected_fppg=worst.projected_fppg + 4.0, projected_gp=70.0)
    moved = _swap(teams, "Benton", worst.player_name, pickup)
    a = _odds(data, moved, n=600).title_odds
    b = _odds(data, moved, n=600).title_odds
    delta = a["Benton"] - base["Benton"]
    assert 0.0 < delta < 10.0, delta                      # up, and single-digit points
    assert a == b                                         # the identical delta, every time
    assert abs(sum(a.values()) - 100.0) < 1e-9


# 3 -- isolation
def test_a_roster_change_leaves_the_other_managers_weeks_identical(monkeypatch):
    data, teams = _world()
    seen = _capture(monkeypatch)
    _odds(data, teams)
    drop = next(iter(teams["Nick"].players))
    _odds(data, _swap(teams, "Nick", drop, PlayerProjection(
        player_name="X", nba_team="NYK", positions=["C"], projected_fppg=45.0, projected_gp=70.0)))
    before, after = seen
    for w in before:
        for m in ("Hayden", "Benton", "Garrett"):
            assert np.array_equal(before[w][m], after[w][m]), (w, m)
    assert any(not np.array_equal(before[w]["Nick"], after[w]["Nick"]) for w in before)


# 4 -- no global random
def test_stdlib_random_cannot_move_title_odds():
    data, teams = _world()
    random.seed(1); a = _odds(data, teams).title_odds
    random.seed(999); [random.random() for _ in range(13)]
    b = _odds(data, teams).title_odds
    assert a == b


def test_title_odds_imports_no_stdlib_random():
    src = inspect.getsource(sto)
    assert "import random" not in src and "random." not in src


# 5 -- no silent calibration default
def test_no_playerlog_calibration_and_no_1500_point_default():
    """In the CODE (the docstring explains what was removed): nothing reads
    data.playerlog or data.historical_playerlog, and no 1500 literal."""
    import ast
    tree = ast.parse(inspect.getsource(sto))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not {"playerlog", "historical_playerlog"} & attrs
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
              and isinstance(n.value, (int, float))}
    assert 1500 not in consts and 1500.0 not in consts
    assert not hasattr(sto, "compute_historical_weekly_stats")


# 6 -- reproducible and still random
def test_same_seed_same_odds_different_seed_different_odds():
    """Same seed, identical odds -- that is the reproducibility guarantee.

    A different seed must change the simulation, but the ODDS are a count over
    n, and in this world only two managers have any chance, so two seeds can
    land on the same count: seeds 3 and 4 both give Nick 37.75% at n = 400,
    and 4 and 5 collide at n = 800. Raising n only makes that rarer, never
    impossible, so the second half of the claim is asserted where it is exact
    -- the weeks the odds are built from.
    """
    data, teams = _world()
    assert _odds(data, teams, seed=3).title_odds == _odds(data, teams, seed=3).title_odds
    a = sb.week_score_matrices(data, teams, [1, 2], None, 3, 400)
    b = sb.week_score_matrices(data, teams, [1, 2], None, 4, 400)
    for w in (1, 2):
        for m in MANAGERS:
            assert not np.array_equal(a[w][m], b[w][m]), (w, m)


# 7 -- the dead branch is gone, by name
@pytest.mark.parametrize("name", ["simulate_week", "simulate_manager_daily_score",
                                  "compute_historical_weekly_stats", "simulate_week_historical",
                                  "compute_player_availability_rates", "SimulatedWeek"])
def test_the_old_week_model_is_gone(name):
    assert not hasattr(sto, name)
    assert "use_historical" not in inspect.signature(sto.simulate_full_season).parameters


def test_the_global_random_samplers_are_gone():
    from modules import projections
    for name in ("is_player_available", "sample_player_game_fp", "sample_team_weekly_variance",
                 "get_player_availability_ros", "ROS_DEFAULT_AVAILABILITY"):
        assert not hasattr(projections, name), name


def test_no_module_imports_stdlib_random():
    root = Path(__file__).resolve().parent.parent
    offenders = [str(p.relative_to(root)) for d in ("modules", "scripts")
                 for p in (root / d).glob("*.py")
                 if any(line.strip() in ("import random", "from random import *")
                        or line.strip().startswith("from random import")
                        for line in p.read_text(encoding="utf-8").splitlines())]
    assert offenders == [], offenders


# the shape the four consumers read is unchanged
def test_the_public_shape_is_unchanged():
    data, teams = _world()
    r = _odds(data, teams, n=500)
    assert set(r.title_odds) == set(MANAGERS)
    assert all(len(v) == 3 for v in r.expected_record.values())
    assert all(set(d) == {1, 2, 3, 4} for d in r.finish_distribution.values())
    assert all(abs(sum(d.values()) - 100.0) < 1e-6 for d in r.finish_distribution.values())
    assert set(r.magic_numbers) == set(MANAGERS)
    assert all(isinstance(v, Record) for v in r.current_records.values())
    exp_games = [sum(v) for v in r.expected_record.values()]
    assert all(abs(g - WEEKS) < 1e-9 for g in exp_games)              # W + L + T = games left


def test_tags_reach_title_odds(monkeypatch):
    """An O tag costs at most three of his team's games (MAX_TAG_GAMES), so
    over a 15-week season it moved expected wins by 0.02 -- this test used to
    assert that, which is a noise-sized gap it could fail on either side at
    any n. The tag's effect is large and unambiguous where it actually lands:
    the week it is anchored to. So compare THAT week's simulated points, from
    the matrices title odds itself used."""
    data, teams = _world()
    seen = _capture(monkeypatch)
    star = max(teams["Hayden"].players.values(), key=lambda p: p.projected_fppg).player_name
    _odds(data, teams)
    _odds(data, teams, statuses={star: "O"})
    healthy, tagged = seen
    anchor_week = min(healthy)
    assert tagged[anchor_week]["Hayden"].mean() < healthy[anchor_week]["Hayden"].mean() - 1.0
    for m in ("Nick", "Benton", "Garrett"):               # and nobody else moves
        assert np.array_equal(healthy[anchor_week][m], tagged[anchor_week][m]), m


# 9 -- fun facts: nothing random, nothing reseeded
def test_fun_facts_draw_nothing_and_reseed_nothing():
    src = inspect.getsource(ff)
    assert "random.seed" not in src and "import random" not in src
    assert "seed" not in inspect.signature(ff.generate_fun_facts).parameters
