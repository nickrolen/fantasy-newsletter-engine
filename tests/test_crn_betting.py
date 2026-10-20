"""Common random numbers in the betting simulator (HANDOFF_CRN_BETTING_2026-10-20).

Before this, every draw came off one global stream, so anything that changed
how many draws happened -- a tag on Hayden, a different matchup order --
moved Nick vs Benton. Measured on live week 1 at 500 sims: tagging Jokic O
on Hayden moved Nick vs Benton from +13.5 to +24.5.
"""
import copy
import hashlib
import random
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from modules import absence, crn
from modules import simulator_betting as sb
from modules.data_loader import FantasyData
from modules.projections import PlayerProjection, TeamProjections

MON = date(2026, 10, 26)
TEAMS = ["BOS", "NYK", "LAL", "GSW", "MIA", "DEN", "PHX", "DAL", "MIL", "OKC", "SAS", "MIN"]
MANAGERS = ["Nick", "Hayden", "Benton", "Garrett"]


def _world(seed=0, roster=12):
    """Four rosters, a one-week schedule, and the FantasyData that holds it."""
    rng = random.Random(seed)
    games = []
    for k in range(7):
        playing = rng.sample(TEAMS, 2 * rng.randint(2, 5))
        games += [{"date": (MON + timedelta(days=k)).isoformat(), "home": playing[j],
                   "away": playing[j + 1]} for j in range(0, len(playing), 2)]
    week = {"week": 2, "start_date": MON.isoformat(),
            "end_date": (MON + timedelta(days=6)).isoformat(),
            "matchups": [{"manager_a": "Nick", "manager_b": "Benton"},
                         {"manager_a": "Hayden", "manager_b": "Garrett"}]}
    data = FantasyData(schedule={"weeks": [week]}, nba_schedule={"games": games}, current_week=1)
    teams = {}
    for i, m in enumerate(MANAGERS):
        players = {}
        for j in range(roster):
            n = f"{m}{j}"
            players[n] = PlayerProjection(player_name=n, nba_team=rng.choice(TEAMS),
                                          positions=[rng.choice(["PG", "SF", "C"])],
                                          projected_fppg=round(rng.uniform(10, 50), 1),
                                          projected_gp=70.0)
        teams[m] = TeamProjections(m, players, weekly_std_dev=150.0)
    return data, week, teams


def _line(data, week, teams, a="Nick", b="Benton", n=400, seed=7, statuses=None):
    return asdict(sb.run_matchup_simulation(data, teams, week, a, b, n, statuses, seed=seed))


def _with_player(teams, manager, player):
    out = dict(teams)
    out[manager] = copy.copy(teams[manager])
    out[manager].players = dict(teams[manager].players)
    out[manager].players[player.player_name] = player
    return out


# 1 -- the regression test for the actual bug
def test_changing_haydens_roster_leaves_nick_vs_benton_identical():
    data, week, teams = _world()
    # a player who plays every day: under the old stream this was extra draws
    star = PlayerProjection(player_name="Star", nba_team="BOS", positions=["PG"],
                            projected_fppg=60.0, projected_gp=80.0)
    data.nba_schedule["games"] += [{"date": (MON + timedelta(days=k)).isoformat(),
                                     "home": "BOS", "away": "XXX"} for k in range(7)]
    base = _line(data, week, teams)
    assert _line(data, week, _with_player(teams, "Hayden", star)) == base
    # removing one, and tagging one, likewise
    fewer = dict(teams); fewer["Hayden"] = copy.copy(teams["Hayden"])
    fewer["Hayden"].players = dict(list(teams["Hayden"].players.items())[1:])
    assert _line(data, week, fewer) == base
    assert _line(data, week, teams, statuses={"Hayden0": "O", "Hayden3": "Q"}) == base


def test_a_roster_edited_in_place_is_not_served_from_a_stale_cache():
    data, week, teams = _world(seed=1)
    before = _line(data, week, teams, "Hayden", "Garrett")
    teams["Hayden"].players["Star"] = PlayerProjection(
        player_name="Star", nba_team=next(iter(teams["Hayden"].players.values())).nba_team,
        positions=["PG"], projected_fppg=80.0, projected_gp=80.0)
    after = _line(data, week, teams, "Hayden", "Garrett")
    assert after["avg_score_a"] > before["avg_score_a"]


def test_the_change_does_move_haydens_own_line():
    """Sanity: the isolation is not a simulator that ignores rosters."""
    data, week, teams = _world()
    star = PlayerProjection(player_name="Star", nba_team="BOS", positions=["PG"],
                            projected_fppg=60.0, projected_gp=80.0)
    data.nba_schedule["games"] += [{"date": MON.isoformat(), "home": "BOS", "away": "XXX"}]
    base = _line(data, week, teams, "Hayden", "Garrett")
    moved = _line(data, week, _with_player(teams, "Hayden", star), "Hayden", "Garrett")
    assert moved["avg_score_a"] > base["avg_score_a"]
    assert moved["avg_score_b"] == base["avg_score_b"]          # Garrett untouched


# 2 -- order independence
def test_pricing_matchups_in_another_order_gives_identical_lines():
    data, week, teams = _world(seed=2)
    pairs = [("Nick", "Benton"), ("Hayden", "Garrett")]
    fwd = {p: _line(data, week, teams, *p) for p in pairs}
    rev = {p: _line(data, week, teams, *p) for p in reversed(pairs)}
    assert fwd == rev


def test_a_shared_week_matrix_gives_the_same_line_as_simulating_alone():
    data, week, teams = _world(seed=3)
    shared = sb.simulate_week_matrix(data, teams, week, None, sb.KeyedDraws(7, 400))
    for a, b in [("Nick", "Benton"), ("Hayden", "Garrett")]:
        alone = sb.run_matchup_simulation(data, teams, week, a, b, 400, seed=7)
        cached = sb.run_matchup_simulation(data, teams, week, a, b, 400, seed=7,
                                           week_results=shared)
        assert asdict(alone) == asdict(cached)


def test_swapping_a_and_b_mirrors_the_line_including_ties():
    data, week, teams = _world(seed=4)
    ab = _line(data, week, teams, "Nick", "Benton")
    ba = _line(data, week, teams, "Benton", "Nick")
    assert ab["spread_a"] == ba["spread_b"] and ab["win_prob_a"] == ba["win_prob_b"]
    # an all-zero week is all ties: the coin is keyed on the unordered pair
    empty = FantasyData(schedule=data.schedule, nba_schedule={"games": []}, current_week=1)
    z_ab = _line(empty, week, teams, "Nick", "Benton")
    z_ba = _line(empty, week, teams, "Benton", "Nick")
    assert z_ab["win_prob_a"] == z_ba["win_prob_b"]
    assert 40 < z_ab["win_prob_a"] < 60


# 3, 4 -- reproducible, and still random
def test_same_seed_same_answer():
    data, week, teams = _world()
    assert _line(data, week, teams, seed=11) == _line(data, week, teams, seed=11)


def test_different_seed_different_answer():
    data, week, teams = _world()
    assert _line(data, week, teams, seed=11)["avg_score_a"] != _line(data, week, teams, seed=12)["avg_score_a"]


def test_the_one_iteration_stream_path_is_gone():
    """simulate_week_hifi / StreamDraws drew the brackets off the global
    stream; the brackets now read week_score_matrices. Not kept as a shim."""
    assert not hasattr(sb, "simulate_week_hifi")
    assert not hasattr(sb, "StreamDraws")


# 5 -- variance reduction
def test_crn_at_least_halves_the_error_of_an_add():
    """Value an add as (with - without). Same seed for both: CRN. Different
    seeds: independent. The spread of the estimate across repetitions must
    at least halve -- C1_DESIGN's bar."""
    data, week, teams = _world(seed=6)
    fa = PlayerProjection(player_name="FA", nba_team="NYK", positions=["SF"],
                          projected_fppg=45.0, projected_gp=80.0)
    data.nba_schedule["games"] += [{"date": (MON + timedelta(days=k)).isoformat(),
                                     "home": "NYK", "away": "XXX"} for k in (1, 3)]
    added = _with_player(teams, "Nick", fa)
    crn_est, ind_est = [], []
    for s in range(30):
        base = sb.run_matchup_simulation(data, teams, week, "Nick", "Benton", 200, seed=s).avg_score_a
        same = sb.run_matchup_simulation(data, added, week, "Nick", "Benton", 200, seed=s).avg_score_a
        other = sb.run_matchup_simulation(data, added, week, "Nick", "Benton", 200, seed=1000 + s).avg_score_a
        crn_est.append(same - base)
        ind_est.append(other - base)
    assert np.std(crn_est) < 0.5 * np.std(ind_est), (np.std(crn_est), np.std(ind_est))


# 6 -- per-entity isolation
def test_a_players_draws_do_not_depend_on_other_players():
    data, week, teams = _world(seed=8)
    d1 = sb.KeyedDraws(3, 300)
    d2 = sb.KeyedDraws(3, 300)
    d2.normals("game", "Someone", MON); d2.uniforms("avail", "Else", MON)   # other requests first
    assert (d1.normals("game", "Nick0", MON) == d2.normals("game", "Nick0", MON)).all()
    # his tag block is unchanged when another player is added, removed or tagged
    st = {"Nick0": "O"}
    k0 = sb.tag_blocks(data, teams, st, sb.KeyedDraws(3, 300))["Nick0"][1]
    more = _with_player(teams, "Nick", PlayerProjection(player_name="X", nba_team="BOS",
                                                       positions=["C"], projected_fppg=30.0))
    k1 = sb.tag_blocks(data, more, {"Nick0": "O", "X": "Q", "Hayden1": "O"},
                       sb.KeyedDraws(3, 300))["Nick0"][1]
    assert (k0 == k1).all()


def test_the_betting_simulator_and_marginal_value_agree_on_who_is_hurt():
    """Same key ("absence", player, anchor), same seed: same block lengths."""
    data, week, teams = _world(seed=9)
    k_sb = sb.tag_blocks(data, teams, {"Nick0": "O"}, sb.KeyedDraws(42, 500))["Nick0"][1]
    k_abs = absence.missed_from_uniform(absence.keyed_uniforms(42, "Nick0", MON, 500), "O")
    assert (k_sb == k_abs).all()


# the one implementation
def test_a_shorter_run_is_a_prefix_of_a_longer_one():
    assert (crn.keyed_normals(1, "game", "P", MON, n=500) ==
            crn.keyed_normals(1, "game", "P", MON, n=5000)[:500]).all()


def test_marginal_values_existing_key_is_byte_identical():
    """C1's per-date draws were keyed blake2b(f'{seed}|{name}|{date}') inline;
    routing them through crn must not change a single published number."""
    h = hashlib.blake2b(f"7|P3|{MON.isoformat()}".encode(), digest_size=8).digest()
    old = np.random.default_rng(int.from_bytes(h, "little")).random(100)
    assert (crn.keyed_rng(7, "P3", MON).random(100) == old).all()
    h = hashlib.blake2b(f"7|absence|P3|{MON.isoformat()}".encode(), digest_size=8).digest()
    old = np.random.default_rng(int.from_bytes(h, "little")).random(100)
    assert (absence.keyed_uniforms(7, "P3", MON, 100) == old).all()


def test_there_is_exactly_one_crn_implementation():
    root = Path(__file__).resolve().parent.parent / "modules"
    hashers = [p.name for p in root.glob("*.py") if "blake2b" in p.read_text(encoding="utf-8")]
    assert hashers == ["crn.py"], hashers


def test_the_betting_simulator_no_longer_draws_from_the_global_stream():
    import inspect
    src = inspect.getsource(sb)
    for call in ("random.random()", "random.gauss(", "is_player_available(", "sample_player_game_fp("):
        assert call not in src, call
