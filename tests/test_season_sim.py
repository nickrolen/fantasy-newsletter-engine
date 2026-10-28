"""Phase 2: one season, four races (HANDOFF_SEASON_SIM_2026-10-26.md).

One pass over weeks 1-23; title odds, the bracket and the Cup are readouts
of it. Every invariant here is checked PER ITERATION, not on the means: a
ledger that balances on average and not in each imagined season is wrong.
"""
import inspect
import random
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from modules import season_sim as ss
from modules import simulator_betting as sb
from modules import simulator_playoff_odds as spo
from modules.data_loader import FantasyData, MANAGERS, Record, league_rule
from modules.projections import PlayerProjection, TeamProjections

TEAMS = ["BOS", "NYK", "LAL", "GSW", "MIA", "DEN", "PHX", "DAL", "MIL", "OKC"]
POS = ["PG", "SG", "SF", "PF", "C", "PG,SG", "SF,PF", "PF,C"]
FIRST = date(2026, 10, 19)
ROTATION = [[("Nick", "Garrett"), ("Hayden", "Benton")],
            [("Nick", "Benton"), ("Hayden", "Garrett")],
            [("Nick", "Hayden"), ("Benton", "Garrett")]]
SEED_PAIRS = [[1, 4], [2, 3]]


def _world(recorded_through=8, seed=0, strength=None):
    """A synthetic 2026-27: 23 weeks, round-robin regular season, weeks
    1..recorded_through in RECORDS. Real FantasyData, real projections."""
    rng = random.Random(seed)
    weeks, games = [], []
    for w in range(1, 24):
        d0 = FIRST + timedelta(days=7 * (w - 1))
        entry = {"week": w, "start_date": d0.isoformat(),
                 "end_date": (d0 + timedelta(days=6)).isoformat()}
        if w <= 15:
            entry["matchups"] = [{"manager_a": a, "manager_b": b} for a, b in ROTATION[(w - 1) % 3]]
        weeks.append(entry)
        for k in range(7):
            playing = rng.sample(TEAMS, 2 * rng.randint(1, 3))     # <82 games a team over 23 weeks
            games += [{"date": (d0 + timedelta(days=k)).isoformat(), "home": playing[j],
                       "away": playing[j + 1]} for j in range(0, len(playing), 2)]
    strength = strength or {}
    teams = {}
    for m in MANAGERS:
        ps = {}
        for j in range(13):
            n = f"{m}{j}"
            ps[n] = PlayerProjection(player_name=n, nba_team=rng.choice(TEAMS),
                                     positions=rng.choice(POS).split(","),
                                     projected_fppg=round(rng.uniform(15, 45) * strength.get(m, 1.0), 1),
                                     projected_gp=70.0)
        teams[m] = TeamProjections(m, ps, weekly_std_dev=140.0)
    scores = {m: [{"week": w, "score": round(rng.uniform(1100, 1700), 1)}
                  for w in range(1, recorded_through + 1)] for m in MANAGERS}
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games},
                       records={"weekly_scores": scores}, current_week=recorded_through)
    return data, teams


def _pass(data, teams, n=400, seed=11, through="cup", monkeypatch=None):
    return ss.run_season(data, num_simulations=n, seed=seed, team_projections=teams, through=through)


@pytest.fixture(scope="module")
def season():
    mp = pytest.MonkeyPatch()
    mp.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world()
    sp = _pass(data, teams)
    mp.undo()
    return sp


def _idx(sp, m):
    return sp.managers.index(m)


# ---------------------------------------------------------------------------
# The money, per iteration
# ---------------------------------------------------------------------------

def _split(sp, i):
    """(league dollars, playoff dollars) for iteration i, rebuilt from the
    finish arrays the readouts publish -- not from sp.dollars."""
    lg = np.zeros(4)
    po = np.zeros(4)
    lg[sp.reg_finish[i, 0]] += 180
    lg[sp.reg_finish[i, 2]] -= 90
    lg[sp.reg_finish[i, 3]] -= 90
    po[sp.playoff_finish[i, 0]] += 90
    for j in sp.semi_losers[i]:
        po[j] -= 45
    return lg, po


def test_the_payouts_are_the_ones_this_ledger_was_written_for():
    rules = ss.payout_rules()
    assert rules == {"league_total": 180.0, "league_per_payer": 90.0,
                     "playoff_total": 90.0, "playoff_per_payer": 45.0}


def test_league_money_and_playoff_money_each_sum_to_zero_every_iteration(season):
    for i in range(season.num_simulations):
        lg, po = _split(season, i)
        assert lg.sum() == 0 and po.sum() == 0, i
        assert sorted(lg) == [-90, -90, 0, 180]          # 2nd is square
        assert sorted(po) == [-45, -45, 0, 90]
        assert np.array_equal(season.dollars[i], lg + po), i


def test_nobody_ever_nets_more_than_270_or_less_than_minus_135(season):
    assert season.dollars.max() <= 270 and season.dollars.min() >= -135
    assert np.all(season.dollars.sum(axis=1) == 0)


def test_win_the_regular_season_lose_the_semifinal_is_exactly_plus_135(season):
    led = season.ledger()
    hits = 0
    for i in range(season.num_simulations):
        top = season.reg_finish[i, 0]
        if top in season.semi_losers[i]:
            hits += 1
            assert season.dollars[i, top] == 135
    for m in season.managers:
        j = _idx(season, m)
        joint = np.mean([(season.reg_finish[i, 0] == j) and (j in season.semi_losers[i])
                         for i in range(season.num_simulations)])
        assert led[m]["dollars"]["p_win_regular_season_lose_semifinal"] == pytest.approx(joint)
    assert hits > 0, "a 1-seed never lost a semifinal in 400 seasons: the world is too lopsided to test"


def test_the_cup_and_the_third_place_series_move_no_money():
    rules = ss.payout_rules()
    order, losers = list(MANAGERS), ["Benton", "Garrett"]
    a = ss.dollars_for(order, losers, "Nick", "Benton", list(MANAGERS), rules)
    b = ss.dollars_for(order, losers, "Nick", "Garrett", list(MANAGERS), rules)
    assert a == b, "the third-place winner moved money"
    assert "cup" not in inspect.signature(ss.dollars_for).parameters


def test_dollars_do_not_depend_on_the_cup(season):
    """Two iterations identical except for the Cup winner have equal dollars."""
    key = lambda i: (tuple(season.reg_finish[i]), tuple(sorted(season.semi_losers[i])),
                     int(season.playoff_finish[i, 0]))
    by_key = {}
    pairs = 0
    for i in range(season.num_simulations):
        for k in by_key.get(key(i), []):
            if season.cup_finish[k, 0] != season.cup_finish[i, 0]:
                pairs += 1
                assert np.array_equal(season.dollars[k], season.dollars[i])
        by_key.setdefault(key(i), []).append(i)
    assert pairs > 0


def test_stopping_before_the_cup_changes_no_dollar(monkeypatch):
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world()
    full = _pass(data, teams, n=150)
    bracket = _pass(data, teams, n=150, through="playoffs")
    for k in ("dollars", "reg_finish", "playoff_finish", "semi_losers"):
        assert np.array_equal(getattr(full, k), getattr(bracket, k)), k


# ---------------------------------------------------------------------------
# The playoff liability: the semifinal rule, and where the config diverges
# ---------------------------------------------------------------------------

def test_liability_is_settled_at_the_semifinal():
    """Both semifinal losers pay whoever wins the third-place series --
    LEAGUE_RULES.md: win your semi and you are clear."""
    rules = ss.payout_rules()
    for third in ("Benton", "Garrett"):
        d = dict(zip(MANAGERS, ss.dollars_for(["Nick", "Hayden", "Benton", "Garrett"],
                                              ["Benton", "Garrett"], "Nick", third,
                                              list(MANAGERS), rules)))
        assert d["Benton"] == -90 - 45 and d["Garrett"] == -90 - 45
        assert d["Hayden"] == 0


def test_the_config_wording_and_the_semifinal_rule_diverge_once_third_place_has_a_stake():
    """payouts.playoff_champion.paid_by says '3rd and 4th ... as decided by the
    third-place series'. Today that names the same two people as the
    semifinal rule, because both losers pay the same and third place carries
    nothing. A stake on the third-place series is where they part -- and no
    rule says how it moves -- so the ledger refuses rather than pick one."""
    assert "third-place series" in league_rule("payouts", "playoff_champion", "paid_by")
    assert float(league_rule("payouts", "playoff_third_place", "total")) == 0
    p = league_rule("payouts")
    staked = dict(p, playoff_third_place=dict(p["playoff_third_place"], total=20, per_payer=20))
    with pytest.raises(ValueError, match="semifinal"):
        ss.payout_rules(staked)
    cup_money = dict(p, cup_champion=dict(p["cup_champion"], total=50))
    with pytest.raises(ValueError, match="keeper"):
        ss.payout_rules(cup_money)


# ---------------------------------------------------------------------------
# One champion each; the bracket is THIS iteration's
# ---------------------------------------------------------------------------

def test_exactly_one_champion_of_each_kind(season):
    for arr in (season.reg_finish, season.playoff_finish, season.cup_finish):
        for row in arr:
            assert sorted(row) == [0, 1, 2, 3]
    for i in range(season.num_simulations):
        assert season.playoff_finish[i, 0] in season.semi_winners[i]
        assert season.cup_finish[i, 0] in season.cup_semi_winners[i]
        assert set(season.semi_winners[i]) | set(season.semi_losers[i]) == {0, 1, 2, 3}


def test_every_bracket_is_seeded_from_that_iterations_standings(season):
    names = season.managers
    for i in range(season.num_simulations):
        seeds = {names[j]: k + 1 for k, j in enumerate(season.reg_finish[i])}
        assert all(season.seeds[i, _idx(season, m)] == s for m, s in seeds.items())
        assert list(season.semi_pairs[i]) == spo._seeded_pairs(seeds, SEED_PAIRS), i
        pts = {m: season.cup_points[i, _idx(season, m)] for m in names}
        cup_order = sorted(names, key=lambda m: (-pts[m], seeds[m]))
        cseeds = {m: k + 1 for k, m in enumerate(cup_order)}
        assert list(season.cup_semi_pairs[i]) == spo._seeded_pairs(cseeds, SEED_PAIRS), i
    assert len(set(season.semi_pairs)) > 1, "one bracket in every season: nothing was tested"


def test_wins_losses_and_ties_add_up_to_fifteen_games(season):
    total = season.reg_wins + season.reg_losses + season.reg_ties
    assert np.all(total == 15)


# ---------------------------------------------------------------------------
# The ledger: two currencies, never summed
# ---------------------------------------------------------------------------

def test_the_ledger_keeps_dollars_and_the_keeper_apart(season):
    led = season.ledger()
    for m, row in led.items():
        assert set(row) == {"dollars", "keeper"}
        assert set(row["keeper"]) == {"p_sixth_keeper_next_season"}
        d = row["dollars"]
        assert d["expected"] == pytest.approx(season.dollars[:, _idx(season, m)].mean())
        assert sum(d["distribution"].values()) == pytest.approx(1.0)
        assert -135 <= d["min"] <= d["max"] <= 270
    assert sum(r["keeper"]["p_sixth_keeper_next_season"] for r in led.values()) == pytest.approx(1.0)
    assert sum(r["dollars"]["expected"] for r in led.values()) == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Clinch and elimination: arithmetic, and what the sample may and may not say
# ---------------------------------------------------------------------------

R = Record


def test_title_clinch_needs_every_rival_unable_to_reach_even_a_tie():
    pairs = [("Nick", "Hayden"), ("Benton", "Garrett")]
    ex = ss.regular_season_exact({"Nick": R(12, 2), "Hayden": R(11, 3), "Benton": R(5, 9),
                                  "Garrett": R(0, 14)}, pairs)
    assert ex["Nick"]["title"] == "alive"           # Hayden beats him and ties him at 12
    ex = ss.regular_season_exact({"Nick": R(13, 1), "Hayden": R(11, 3), "Benton": R(5, 9),
                                  "Garrett": R(0, 14)}, pairs)
    assert ex["Nick"]["title"] == "clinched"


def test_a_tie_is_half_a_win_in_the_arithmetic():
    pairs = [("Nick", "Hayden"), ("Benton", "Garrett")]
    ex = ss.regular_season_exact({"Nick": R(12, 1, 1), "Hayden": R(11, 2, 1), "Benton": R(5, 9),
                                  "Garrett": R(0, 14)}, pairs)
    assert ex["Nick"]["title"] == "alive"           # 12.5 vs Hayden's best 12.5: a tie
    ex = ss.regular_season_exact({"Nick": R(12, 1, 1), "Hayden": R(11, 3), "Benton": R(5, 9),
                                  "Garrett": R(0, 14)}, pairs)
    assert ex["Nick"]["title"] == "clinched"        # 12.5 > 12


def test_rivals_who_play_each_other_cannot_both_win():
    """The leader-only bound (marginal_value.title_eliminated) calls Benton
    alive: 8 + 3 = 11 reaches Nick's 10. But Nick and Hayden play each other
    twice, so one of them reaches 11 -- and Benton then needs the rest. The
    flow over the real pairings sees it."""
    recs = {"Nick": R(10, 2), "Hayden": R(10, 2), "Benton": R(8, 4), "Garrett": R(0, 12)}
    pairs = [("Nick", "Hayden"), ("Benton", "Garrett"),
             ("Nick", "Hayden"), ("Benton", "Garrett"),
             ("Nick", "Hayden"), ("Benton", "Garrett")]
    from modules.marginal_value import title_eliminated
    assert not title_eliminated(recs, 3, "Benton")
    assert ss.regular_season_exact(recs, pairs)["Benton"]["title"] == "eliminated"
    # Nick and Hayden split 3 games: someone reaches 11.5 at least; Benton's best is 11
    recs["Benton"] = R(9, 3)                       # best 12: alive (Nick 2-1 -> 12 ties)
    assert ss.regular_season_exact(recs, pairs)["Benton"]["title"] == "alive"


def test_safe_from_and_certain_to_pay_the_league_pot():
    pairs = [("Nick", "Hayden"), ("Benton", "Garrett")]
    ex = ss.regular_season_exact({"Nick": R(13, 1), "Hayden": R(12, 2), "Benton": R(3, 11),
                                  "Garrett": R(0, 14)}, pairs)
    assert ex["Nick"]["league_pot"] == ex["Hayden"]["league_pot"] == "safe"
    assert ex["Benton"]["league_pot"] == ex["Garrett"]["league_pot"] == "will_pay"


def _scripted(monkeypatch, recs, weeks, scores):
    """A pass over a world whose remaining regular weeks score as `scores`
    in every iteration (constant matrices)."""
    import modules.projections as proj
    monkeypatch.setattr(proj, "load_all_team_projections", lambda d: {})
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)

    def fake(data, projections, wks, injury_statuses=None, seed=None, num_simulations=1, **kw):
        return {w: {m: np.full(num_simulations, float(scores.get(w, {}).get(m, 100.0)))
                    for m in MANAGERS} for w in wks}
    monkeypatch.setattr(ss, "week_score_matrices", fake)
    last = 15 - len(weeks)
    return SimpleNamespace(
        schedule={"weeks": weeks},
        records={"weekly_scores": {m: [{"week": w, "score": 100.0} for w in range(1, last + 1)]
                                   for m in MANAGERS}},
        current_week=last,
        regular_season_results=lambda include_playoffs=False: (
            dict(recs), {m: {} for m in MANAGERS}, {m: 1000.0 for m in MANAGERS}),
        get_manager_record=lambda m: recs[m],
    )


def test_an_exact_clinch_is_a_sampled_one_and_an_exact_elimination_a_sampled_zero(monkeypatch):
    data, teams = _world(recorded_through=12)
    level = {"Nick": 2000.0, "Hayden": 1500.0, "Benton": 1400.0, "Garrett": 1000.0}
    data.records["weekly_scores"] = {m: [{"week": w, "score": level[m]} for w in range(1, 13)]
                                     for m in MANAGERS}       # 12-0, 8-4, 4-8, 0-12
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    recs, _h, _p = data.regular_season_results()
    sp = _pass(data, teams, n=400)
    ex = sp.exact()
    first = {m: float((sp.reg_finish[:, 0] == _idx(sp, m)).mean()) for m in sp.managers}
    pays = {m: float(np.isin(sp.reg_finish[:, 2:4], _idx(sp, m)).any(axis=1).mean())
            for m in sp.managers}
    settled = 0
    for m in sp.managers:
        if ex[m]["title"] == "clinched":
            assert first[m] == 1.0; settled += 1
        if ex[m]["title"] == "eliminated":
            assert first[m] == 0.0; settled += 1
        if ex[m]["league_pot"] == "safe":
            assert pays[m] == 0.0; settled += 1
        if ex[m]["league_pot"] == "will_pay":
            assert pays[m] == 1.0; settled += 1
    # every race is settled here: Nick clinched + safe; Hayden out + safe;
    # Benton and Garrett out + will pay
    assert settled == 8, (ex, recs)


def test_a_sampled_one_is_not_a_clinch(monkeypatch):
    """§7: 'a sampled 1.0000 is evidence, not proof'. Nick wins every
    simulated week, so the sample says 100% -- but Hayden can still tie
    him on wins, so the arithmetic says alive. The brief's 'exact alive <=>
    strictly below 1.0' cannot hold of a sample; what holds is the one-way
    implication above, and the clinch flag comes from races_exact."""
    recs = {"Nick": R(12, 1), "Hayden": R(11, 2), "Benton": R(2, 11), "Garrett": R(1, 12)}
    weeks = [{"week": w, "matchups": [{"manager_a": "Nick", "manager_b": "Benton"},
                                      {"manager_a": "Hayden", "manager_b": "Garrett"}]}
             for w in (14, 15)]
    data = _scripted(monkeypatch, recs, weeks, {w: {"Nick": 200, "Hayden": 150} for w in (14, 15)})
    sp = ss.run_season(data, num_simulations=50, seed=1, through="regular")
    assert sp.title_result().title_odds["Nick"] == 100.0
    assert sp.exact()["Nick"]["title"] == "alive"


def test_bracket_races_settle_on_week_wins(monkeypatch):
    """Regular season over, Nick 2-0 up in his semi: he is clear of the
    playoff pot and Garrett owes it, whatever week 18 does."""
    from season_world import decided_world
    decided = {w: {"Nick": 200, "Garrett": 100, "Hayden": 150, "Benton": 150.5} for w in (16, 17)}
    sim = {w: {"Nick": 1, "Garrett": 500, "Hayden": 100, "Benton": 90} for w in range(18, 24)}
    data = decided_world(monkeypatch, sim, decided=decided)
    sp = ss.run_season(data, num_simulations=40, seed=3)
    ex = sp.exact()
    assert ex["Nick"]["playoff_pot"] == "safe" and ex["Garrett"]["playoff_pot"] == "will_pay"
    assert ex["Garrett"]["playoff_champion"] == "eliminated"
    assert ex["Benton"]["playoff_pot"] == "safe"            # 150.5 beats 150 twice
    j = _idx(sp, "Garrett")
    assert np.all((sp.semi_losers == j).any(axis=1))
    assert not np.any(sp.playoff_finish[:, 0] == j)


# ---------------------------------------------------------------------------
# Common random numbers
# ---------------------------------------------------------------------------

def _capture(monkeypatch):
    seen = []
    real = ss.week_score_matrices

    def spy(*a, **k):
        out = real(*a, **k)
        seen.append(out)
        return out
    monkeypatch.setattr(ss, "week_score_matrices", spy)
    return seen


def test_one_managers_roster_never_moves_another_managers_week(monkeypatch):
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world()
    seen = _capture(monkeypatch)
    _pass(data, teams, n=200)
    stronger = dict(teams)
    tp = teams["Nick"]
    stronger["Nick"] = TeamProjections("Nick", {n: PlayerProjection(
        player_name=n, nba_team=p.nba_team, positions=p.positions,
        projected_fppg=p.projected_fppg * 1.3, projected_gp=70.0) for n, p in tp.players.items()},
        weekly_std_dev=tp.weekly_std_dev)
    _pass(data, stronger, n=200)
    a, b = seen
    assert sorted(a) == list(range(9, 24))
    for w in a:
        assert not np.array_equal(a[w]["Nick"], b[w]["Nick"])
        for m in ("Hayden", "Benton", "Garrett"):
            assert np.array_equal(a[w][m], b[w][m]), (w, m)


@pytest.mark.parametrize("week", [9, 16, 23])
def test_a_week_in_the_pass_is_the_betting_lines_week(monkeypatch, week):
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world()
    seen = _capture(monkeypatch)
    _pass(data, teams, n=600, seed=20262027)
    entry = sb.schedule_week(data, week)
    line_week = sb.simulate_week_matrix(data, teams, entry, None, sb.KeyedDraws(20262027, 250))
    for m in MANAGERS:
        assert np.array_equal(seen[0][week][m][:250], line_week[m]["score"]), (week, m)


def test_prefix_stability_in_n(monkeypatch):
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world()
    small, big = _pass(data, teams, n=150), _pass(data, teams, n=300)
    for k in ("reg_finish", "playoff_finish", "cup_finish", "dollars", "semi_losers", "cup_points"):
        assert np.array_equal(getattr(small, k), getattr(big, k)[:150]), k


def test_order_independence_and_no_stdlib_random(monkeypatch):
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world()
    random.seed(1)
    a = _pass(data, teams, n=120)
    random.seed(999); [random.random() for _ in range(17)]
    sb.run_matchup_simulation(data, teams, sb.schedule_week(data, 9), "Nick", "Garrett",
                              300, None, seed=4)          # something else ran first
    b = _pass(data, teams, n=120)
    for k in ("reg_finish", "playoff_finish", "cup_finish", "dollars"):
        assert np.array_equal(getattr(a, k), getattr(b, k)), k
    src = inspect.getsource(ss)
    assert "import random" not in src and "random." not in src


def test_different_seeds_differ(monkeypatch):
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world()
    assert not np.array_equal(_pass(data, teams, n=120, seed=1).dollars,
                              _pass(data, teams, n=120, seed=2).dollars)


# ---------------------------------------------------------------------------
# §8: the gaps this job closes
# ---------------------------------------------------------------------------

def test_the_in_progress_week_is_banked_plus_remainder_not_dropped(monkeypatch):
    """PLAYERLOG has reached week 9, RECORDS has not: week 9 is the banked
    points plus B2's remainder -- not skipped (Phase 1) and not re-drawn
    whole from week_score_matrices."""
    import modules.week_state as wsm
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = _world(recorded_through=8)
    data.current_week = 9
    banked = {"Nick": 900.0, "Hayden": 10.0, "Benton": 10.0, "Garrett": 10.0}
    seen = {}
    monkeypatch.setattr(ss, "_as_of_for", lambda d, w: date(2026, 12, 18))
    monkeypatch.setattr(wsm, "week_state", lambda d, w, as_of, tp=None: SimpleNamespace(
        banked=banked, assumptions=("test",)))

    def remainder(d, tp, entry, state, seed, n, statuses=None, anchors=None):
        seen.update(week=entry["week"], seed=seed, n=n)
        return SimpleNamespace(remaining={m: {"score": np.full(n, 1.0)} for m in MANAGERS})
    monkeypatch.setattr(sb, "simulate_week_remainder", remainder)
    sp = _pass(data, teams, n=60, through="regular")
    assert seen == {"week": 9, "seed": 11, "n": 60}
    assert 9 not in sp.simulated_weeks and 9 in sp.in_progress
    assert sp.in_progress[9]["banked"] == banked
    total = sp.reg_wins + sp.reg_losses + sp.reg_ties
    assert np.all(total == 15)
    # Nick vs Benton in week 9 (ROTATION): 901 to 11, every iteration
    assert sp.remaining_games == {m: 7 for m in MANAGERS}


def test_games_left_come_from_the_pairings_not_a_count_per_week(monkeypatch):
    """compute_magic_numbers used to take len(matchups) // 2 per week for
    everyone. Off the pass it is each manager's own games left."""
    from modules.simulator_title_odds import compute_magic_numbers
    recs = {"Nick": R(11, 2), "Hayden": R(9, 4), "Benton": R(4, 9), "Garrett": R(2, 11)}
    weeks = [{"week": 14, "matchups": [{"manager_a": "Nick", "manager_b": "Benton"},
                                       {"manager_a": "Hayden", "manager_b": "Garrett"}]},
             {"week": 15, "matchups": [{"manager_a": "Hayden", "manager_b": "Benton"}]}]
    data = _scripted(monkeypatch, recs, weeks, {})
    sp = ss.run_season(data, num_simulations=20, seed=1, through="regular")
    assert sp.remaining_games == {"Nick": 1, "Hayden": 2, "Benton": 2, "Garrett": 1}
    # Nick 11, one game left; Hayden 9, two left: Hayden can still reach 11.
    # The threat is the RIVAL's games left, not the leader's: one more Nick
    # win or Hayden loss is needed. Counting Nick's own single game (or one
    # count for everyone) called it clinched.
    assert compute_magic_numbers(recs, sp.remaining_games, {"Nick": 90.0}, list(MANAGERS))["Nick"] == 1
    assert compute_magic_numbers(recs, 1, {"Nick": 90.0}, list(MANAGERS))["Nick"] == 0
    assert sp.exact()["Nick"]["title"] == "alive"
