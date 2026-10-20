"""A2: the absence model (modules/absence.py) and its three callers.

The brief's ten tests, plus the guards that keep the old model out of the
tree. Test 4 (schedule-shift invariance) is the regression test for the bug
A2 fixes: the old curve was indexed on the calendar, so the NBA schedule
decided how hurt a player was.
"""
import random
from datetime import date, timedelta

import numpy as np
import pytest

from modules import absence
from modules import marginal_value as mv
from modules import projections
from modules import simulator_betting as sb
from modules.data_loader import FantasyData
from modules.projections import PlayerProjection, TeamProjections

MON = date(2026, 10, 26)                     # a Monday; week 2 in the worlds below
WEEK = [MON + timedelta(days=k) for k in range(7)]
MWF = [WEEK[0], WEEK[2], WEEK[4]]            # BOS
TTS = [WEEK[1], WEEK[3], WEEK[5]]            # NYK: same three games, shifted a day


def _proj(name, team, fppg=30.0, gp=80.0, pos="PG", **kw):
    return PlayerProjection(player_name=name, nba_team=team, positions=pos.split(","),
                            projected_fppg=fppg, projected_gp=gp, **kw)


def _games(team_dates):
    """{'games': [...]} with each team playing a dummy opponent on its dates."""
    opp = {"BOS": "MIA", "NYK": "DEN", "LAL": "PHX"}
    return {"games": [{"date": d.isoformat() + "T00:00:00Z", "home": t, "away": opp[t]}
                      for t, ds in team_dates.items() for d in ds]}


def _week_entry(week=2, start=MON):
    return {"week": week, "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=6)).isoformat()}


def _ctx(projs, rosters, team_dates, statuses, sims=4000, seed=11, weeks=1, **kw):
    sched = [_week_entry(2 + w, MON + timedelta(days=7 * w)) for w in range(weeks)]
    return mv.build_context(projs, rosters, _games(team_dates), sched, "this_week", 1,
                            injury_statuses=statuses, sims=sims, seed=seed, **kw)


def _missed_counts(ctx, name):
    """Per simulation: games missed from the tag, and the mask matrix."""
    m = mv.tag_missed(ctx, ctx.player(name))
    if not m:
        return np.zeros(ctx.sims, dtype=int), np.zeros((ctx.sims, 0), dtype=bool)
    mat = np.stack([m[d] for d in sorted(m)], axis=1)
    return mat.sum(axis=1), mat


# 6 -- the distribution is derived from the chain, and it is the brief's table
@pytest.mark.parametrize("tag,table", [
    ("O", (0.0, 0.5, 0.375, 0.125)),
    ("GTD", (0.6, 0.22, 0.135, 0.045)),
])
def test_derived_distribution_is_the_handoff_table_and_sums_to_one(tag, table):
    dist = absence.missed_distribution(tag)
    assert sum(dist) == pytest.approx(1.0, abs=1e-12)
    assert dist == pytest.approx(table, abs=1e-12)


@pytest.mark.parametrize("tag", ["O", "GTD"])
def test_derived_distribution_matches_walking_the_chain(tag):
    """Walk the absorbing chain game by game; the one-draw table must agree."""
    rng = random.Random(5)
    n, counts = 200_000, [0] * (absence.MAX_TAG_GAMES + 1)
    for _ in range(n):
        k = 0
        for p_play in absence.CHAIN_PLAY[tag]:
            if rng.random() < p_play:
                break
            k += 1
        counts[k] += 1
    for k, p in enumerate(absence.missed_distribution(tag)):
        se = (p * (1 - p) / n) ** 0.5
        assert abs(counts[k] / n - p) <= 5 * se + 1e-9, (tag, k, counts[k] / n, p)


def test_expected_games_missed():
    assert absence.expected_missed("O") == pytest.approx(1.625)
    assert absence.expected_missed("GTD") == pytest.approx(0.625)


def test_inverse_cdf_is_the_distribution():
    u = np.random.default_rng(1).random(400_000)
    for tag in ("O", "GTD"):
        k = absence.missed_from_uniform(u, tag)
        freq = np.bincount(k, minlength=4) / len(u)
        assert freq == pytest.approx(absence.missed_distribution(tag), abs=0.004)


# 1, 2, 3, 5 -- in marginal_value, over thousands of keyed draws
@pytest.fixture
def tagged_world():
    projs = {"Out": _proj("Out", "BOS"), "Gtd": _proj("Gtd", "NYK"),
             "Fine": _proj("Fine", "LAL")}
    dates = {"BOS": MWF + [WEEK[6]], "NYK": TTS + [WEEK[6]], "LAL": MWF}
    ctx = _ctx(projs, {"Nick": list(projs)}, dates, {"Out": "O", "Gtd": "GTD"})
    return ctx


def test_an_out_player_never_plays_his_next_game(tagged_world):
    first = mv.tag_missed(tagged_world, tagged_world.player("Out"))[MWF[0]]
    assert first.all()
    plays = mv._draws(tagged_world, tagged_world.player("Out"), MWF[0], 2)
    assert not plays.any()


def test_a_tag_alone_never_costs_more_than_three_games(tagged_world):
    for name in ("Out", "Gtd"):
        k, mat = _missed_counts(tagged_world, name)
        assert k.max() <= absence.MAX_TAG_GAMES
        assert mat.shape[1] <= absence.MAX_TAG_GAMES       # the 4th game is never masked
        fourth = WEEK[6]
        assert fourth not in mv.tag_missed(tagged_world, tagged_world.player(name))


def test_missed_games_are_a_contiguous_block_from_g1_and_playing_is_absorbing(tagged_world):
    for name in ("Out", "Gtd"):
        k, mat = _missed_counts(tagged_world, name)
        # each row is k Trues then Falses: once he plays, he keeps playing
        expect = np.arange(mat.shape[1])[None, :] < k[:, None]
        assert (mat == expect).all()
        assert (np.diff(mat.astype(int), axis=1) <= 0).all()


def test_a_healthy_player_has_no_tag_block(tagged_world):
    assert mv.tag_missed(tagged_world, tagged_world.player("Fine")) == {}


def test_marginal_value_frequencies_match_the_model(tagged_world):
    for name, tag in (("Out", "O"), ("Gtd", "GTD")):
        k, _ = _missed_counts(tagged_world, name)
        freq = np.bincount(k, minlength=4) / len(k)
        assert freq == pytest.approx(absence.missed_distribution(tag), abs=0.03)


# 4 -- schedule-shift invariance: THE regression test for the bug
def test_same_tag_same_games_different_calendar_days_identical_distribution():
    """Mon/Wed/Fri vs Tue/Thu/Sat, same tag, three games each.

    The old curve gave these 0.20/0.60/0.85 and 0.40/0.75/0.95. Keyed on the
    player only, the realised blocks are identical draw for draw.
    """
    for tag in ("O", "GTD"):
        projs = {"A": _proj("A", "BOS"), "B": _proj("B", "NYK")}
        ctx = _ctx(projs, {"Nick": ["A", "B"]}, {"BOS": MWF, "NYK": TTS},
                   {"A": tag, "B": tag}, sims=3000)
        ka, _ = _missed_counts(ctx, "A")
        kb, _ = _missed_counts(ctx, "B")
        fa = np.bincount(ka, minlength=4) / ctx.sims
        fb = np.bincount(kb, minlength=4) / ctx.sims
        assert fa == pytest.approx(fb, abs=0.04), (tag, fa, fb)
        # exact: same uniforms -> same block length, whatever the weekdays
        u = absence.keyed_uniforms(1, "X", MON, 5000)
        k = absence.missed_from_uniform(u, tag)
        for i in range(0, 5000, 97):
            ma = absence.missed_dates(absence.team_games_from(MON, MWF), k[i])
            mb = absence.missed_dates(absence.team_games_from(MON, TTS), k[i])
            assert len(ma) == len(mb) == k[i]


def test_schedule_shift_invariance_in_the_betting_simulator():
    """Same uniforms, same tag, teams on shifted days: same games missed."""
    data = _betting_data({"BOS": MWF, "NYK": TTS})
    teams = {"Nick": TeamProjections("Nick", {"A": _proj("A", "BOS"), "B": _proj("B", "NYK")})}
    for tag in ("O", "GTD"):
        for u in np.linspace(0.0, 0.999, 41):
            out = sb.tag_blocks(data, teams, {"A": tag, "B": tag}, _Const(u))
            ga, ka = out["A"].games, out["A"].k
            gb, kb = out["B"].games, out["B"].k
            assert (ka == kb).all()
            assert ga == MWF and gb == TTS


# 7 -- common random numbers
def test_a_players_absence_does_not_depend_on_what_else_is_asked():
    projs = {"T": _proj("T", "BOS"), "U": _proj("U", "NYK"), "V": _proj("V", "LAL"),
             "FA": _proj("FA", "NYK")}
    dates = {"BOS": MWF, "NYK": TTS, "LAL": MWF}
    st = {"T": "GTD", "U": "O", "FA": "GTD"}
    alone = _ctx({"T": projs["T"]}, {"Nick": ["T"]}, dates, {"T": "GTD"})
    k_alone, _ = _missed_counts(alone, "T")
    busy = _ctx(projs, {"Nick": ["T", "V"], "Hayden": ["U"]}, dates, st, extra_players=["FA"])
    mv.marginal_value(busy, "Nick", adds=["FA"], drops=["V"])
    mv.marginal_value(busy, "Hayden", adds=["FA"])
    k_busy, _ = _missed_counts(busy, "T")
    assert (k_alone == k_busy).all()


def test_adding_a_player_leaves_the_tagged_players_draws_alone():
    projs = {"T": _proj("T", "BOS"), "FA": _proj("FA", "NYK")}
    ctx = _ctx(projs, {"Nick": ["T"]}, {"BOS": MWF, "NYK": TTS}, {"T": "O"},
               extra_players=["FA"])
    before = mv._draws(ctx, ctx.player("T"), MWF[1], 2).copy()
    mv.marginal_value(ctx, "Nick", adds=["FA"])
    fresh = _ctx(projs, {"Nick": ["T"]}, {"BOS": MWF, "NYK": TTS}, {"T": "O"},
                 extra_players=["FA"])
    assert (mv._draws(fresh, fresh.player("T"), MWF[1], 2) == before).all()


# 8 -- precedence
def test_an_override_hard_out_beats_a_gtd_tag():
    projs = {"H": _proj("H", "BOS", out_weeks=[2])}
    ctx = _ctx(projs, {"Nick": ["H"]}, {"BOS": MWF}, {"H": "GTD"})
    assert mv.tag_missed(ctx, ctx.player("H")) == {}
    assert all(not mv._draws(ctx, ctx.player("H"), d, 2).any() for d in MWF)


def test_a_return_date_override_switches_the_tag_off_for_that_week():
    """return_week == the tag's week: Nick's date governs, not the chain."""
    projs = {"R": _proj("R", "BOS", return_week=2, return_date=MWF[1].isoformat())}
    ctx = _ctx(projs, {"Nick": ["R"]}, {"BOS": MWF}, {"R": "O"})
    assert mv.tag_missed(ctx, ctx.player("R")) == {}
    assert not mv._draws(ctx, ctx.player("R"), MWF[0], 2).any()       # before return
    assert mv._draws(ctx, ctx.player("R"), MWF[1], 2).mean() > 0.9     # rate only after


def test_betting_simulator_respects_override_precedence():
    data = _betting_data({"BOS": MWF})
    hard = {"Nick": TeamProjections("Nick", {"H": _proj("H", "BOS", out_weeks=[1])})}
    assert sb.tag_blocks(data, hard, {"H": "O"}, _Const(0.99)) == {}
    ret = {"Nick": TeamProjections("Nick", {"R": _proj("R", "BOS", return_week=1,
                                                         return_date=MWF[1].isoformat())})}
    assert sb.tag_blocks(data, ret, {"R": "O"}, _Const(0.99)) == {}


def test_suppression_rules():
    assert absence.tag_suppressed(2, WEEK, out_weeks=[2])
    assert absence.tag_suppressed(2, WEEK, return_week=2)
    assert absence.tag_suppressed(2, WEEK, out_from=WEEK[3])
    assert not absence.tag_suppressed(2, WEEK, out_weeks=[3], return_week=4,
                                      out_from=WEEK[0] + timedelta(days=9))


# 9 -- observed truncation (the B2 interface; B2 has not landed)
def test_played_an_earlier_game_is_healthy_for_the_rest_of_the_week():
    for tag in ("O", "GTD"):
        assert absence.missed_distribution(tag, observed=[True]) == (1.0, 0.0, 0.0, 0.0)
        assert absence.missed_distribution(tag, observed=[False, True]) == (1.0, 0.0, 0.0, 0.0)


def test_observed_misses_continue_the_chain_rather_than_restart_it():
    # missed g1 and g2 -> g3 at 0.75, then certain
    assert absence.missed_distribution("O", [False, False]) == pytest.approx((0.75, 0.25, 0, 0))
    assert absence.missed_distribution("GTD", [False, False]) == pytest.approx((0.75, 0.25, 0, 0))
    # GTD missed g1 -> g2 at 0.55, g3 at 0.75
    assert absence.missed_distribution("GTD", [False]) == pytest.approx(
        (0.55, 0.45 * 0.75, 0.45 * 0.25, 0))
    # three misses observed: the tag has nothing left to say
    assert absence.missed_distribution("O", [False] * 3) == (1.0, 0.0, 0.0, 0.0)


def test_an_out_player_seen_playing_g1_is_healthy():
    """Zero probability under the model; the log wins."""
    assert absence.missed_distribution("O", [True]) == (1.0, 0.0, 0.0, 0.0)


# 10 -- out_from
def test_out_from_unavailable_on_and_after_available_before():
    projs = {"F": _proj("F", "BOS", out_from=MWF[1])}
    ctx = _ctx(projs, {"Nick": ["F"]}, {"BOS": MWF}, {})
    assert mv.availability(ctx, ctx.player("F"), MWF[0], 2) > 0
    assert mv.availability(ctx, ctx.player("F"), MWF[1], 2) == 0.0
    assert mv.availability(ctx, ctx.player("F"), MWF[2], 2) == 0.0


def test_out_from_is_bounded_by_its_own_week():
    projs = {"F": _proj("F", "BOS", out_from=MWF[1])}
    nxt = [d + timedelta(days=7) for d in MWF]
    sched = [_week_entry(2, MON), _week_entry(3, MON + timedelta(days=7))]
    ctx = mv.build_context(projs, {"Nick": ["F"]}, _games({"BOS": MWF + nxt}), sched,
                           "regular_season", 1, sims=200, seed=3)
    assert mv.availability(ctx, ctx.player("F"), nxt[0], 3) > 0


def test_out_from_in_the_betting_simulation():
    data = _betting_data({"BOS": MWF}, week=2)
    teams = {"Nick": TeamProjections("Nick", {"F": _proj("F", "BOS", out_from=MWF[1])})}
    res = sb.simulate_week_matrix(data, teams, _week_entry(2), None, sb.KeyedDraws(1, 50),
                                  managers=["Nick"])
    assert (res["Nick"]["games"] == 1).all()          # Monday only


def test_a_malformed_out_from_raises():
    with pytest.raises(ValueError):
        absence.parse_out_from("10/29/2026")
    assert absence.parse_out_from(None) is None
    assert absence.parse_out_from("2026-10-29") == date(2026, 10, 29)


def test_out_from_flows_from_the_overrides_file():
    data = FantasyData(injury_overrides={"players": [
        {"player_name": "Nikola Jokić", "out_weeks": [], "out_from": "2026-10-29"}]})
    assert data.get_player_out_from("Nikola Jokic") == "2026-10-29"
    assert data.get_player_out_from("Nobody") is None


# tags the model has no rule for
def test_yahoo_q_is_the_gtd_chain_and_p_is_healthy():
    """Nick, 2026-10-19: Yahoo's Q replaced GTD; P is new and healthy."""
    assert absence.chain_tag("Q") == "GTD"
    assert absence.chain_tag("q ") == "GTD"
    assert absence.chain_tag("P") is None
    assert absence.chain_tag("O") == "O"


def test_q_in_marginal_value_is_the_gtd_block():
    projs = {"Q1": _proj("Q1", "BOS"), "P1": _proj("P1", "NYK")}
    ctx = _ctx(projs, {"Nick": ["Q1", "P1"]}, {"BOS": MWF, "NYK": TTS}, {"Q1": "Q", "P1": "P"})
    k, _ = _missed_counts(ctx, "Q1")
    assert np.bincount(k, minlength=4) / len(k) == pytest.approx(
        absence.missed_distribution("GTD"), abs=0.03)
    assert mv.tag_missed(ctx, ctx.player("P1")) == {}


def test_an_unmodelled_tag_raises_in_marginal_value():
    projs = {"D1": _proj("D1", "BOS"), "X1": _proj("X1", "NYK")}
    with pytest.raises(absence.UnmodelledTag, match="D1.*X1|X1.*D1"):
        _ctx(projs, {"Nick": ["D1", "X1"]}, {"BOS": MWF, "NYK": TTS}, {"D1": "DTD", "X1": "XYZ"})


def test_an_unmodelled_tag_raises_in_the_betting_simulator():
    data = _betting_data({"BOS": MWF})
    teams = {"Nick": TeamProjections("Nick", {"D1": _proj("D1", "BOS")})}
    with pytest.raises(absence.UnmodelledTag):
        sb.tag_blocks(data, teams, {"D1": "DTD"}, _Const(0.5))


def test_no_effect_tags_cost_nothing():
    for tag in ("HEALTHY", "INJ", "IL", "IL+", None, ""):
        assert absence.chain_tag(tag) is None


# the tag's anchor: a playoff week months away is not touched by today's tag
def test_a_tag_only_reaches_the_first_three_games_from_its_anchor():
    later = [d + timedelta(days=70) for d in MWF]
    data = _betting_data({"BOS": MWF + later})
    teams = {"Nick": TeamProjections("Nick", {"O1": _proj("O1", "BOS")})}
    for u in (0.0, 0.6, 0.9, 0.999):
        blk = sb.tag_blocks(data, teams, {"O1": "O"}, _Const(u))["O1"]
        games, k = blk.games, blk.k
        assert games == MWF and 1 <= int(k[0]) <= 3


# the old model is gone and stays gone
def test_the_calendar_decay_curve_is_not_in_the_tree():
    for name in ("INJURY_DECAY", "get_injury_availability_decayed",
                 "INJURY_AVAILABILITY", "get_player_availability_betting"):
        assert not hasattr(projections, name), name
    import inspect
    assert "days_offset" not in inspect.getsource(sb)
    assert not hasattr(sb, "draw_tag_absences")


class _Const:
    """A draws source returning one fixed uniform for every simulation."""
    n = 4

    def __init__(self, u):
        self.u = u

    def uniforms(self, namespace, *key):
        return np.full(self.n, self.u)


def _betting_data(team_dates, week=1):
    start = MON
    return FantasyData(
        schedule={"weeks": [{"week": week, "start_date": start.isoformat(),
                             "end_date": (start + timedelta(days=6)).isoformat(),
                             "matchups": []}]},
        nba_schedule=_games(team_dates),
        current_week=week - 1,
    )
