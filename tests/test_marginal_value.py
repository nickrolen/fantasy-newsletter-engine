"""C1: marginal_value. The design doc's test list, items 1-6 and 8.
(7, fill optimality, is in test_games_grid; 9 is a validation script run on
real post-draft rosters: scripts/validate_marginal_value.py.)"""
import builtins
import random
from datetime import date, timedelta

import numpy as np
import pytest

from modules import marginal_value as mv
from modules.projections import PlayerProjection

TEAMS = ["BOS", "NYK", "LAL", "GSW", "MIA", "DEN", "PHX", "DAL", "MIL", "OKC",
         "SAS", "MIN", "CLE", "ORL", "HOU", "MEM"]
POS = ["PG", "SG", "SF", "PF", "C", "PG,SG", "SF,PF", "PF,C", "SG,SF"]


def _proj(name, team, pos, fppg, gp=70.0, **kw):
    return PlayerProjection(player_name=name, nba_team=team, positions=pos.split(","),
                            projected_fppg=fppg, projected_gp=gp, **kw)


def _world(seed=0, n_players=90, weeks=2):
    rng = random.Random(seed)
    projs = {f"P{i}": _proj(f"P{i}", rng.choice(TEAMS), rng.choice(POS),
                            round(rng.uniform(8, 55), 1), gp=rng.uniform(40, 80))
             for i in range(n_players)}
    names = list(projs)
    rosters = {m: names[i * 15:(i + 1) * 15] for i, m in enumerate(["Nick", "Hayden", "Benton", "Garrett"])}
    start = date(2026, 10, 26)
    sched_weeks, games = [], []
    for w in range(weeks):
        d0 = start + timedelta(days=7 * w)
        sched_weeks.append({"week": 2 + w, "start_date": d0.isoformat(),
                            "end_date": (d0 + timedelta(days=6)).isoformat()})
        for k in range(7):
            playing = rng.sample(TEAMS, 2 * rng.randint(3, 8))
            games += [{"date": (d0 + timedelta(days=k)).isoformat() + "T00:00:00Z",
                       "home": playing[j], "away": playing[j + 1]}
                      for j in range(0, len(playing), 2)]
    return projs, rosters, {"games": games}, sched_weeks, names[60:]


def _ctx(world, window="this_week", sims=300, seed=7, **kw):
    projs, rosters, nba, weeks, fas = world
    kw.setdefault("extra_players", fas)
    return mv.build_context(projs, rosters, nba, weeks, window, current_week=1,
                            sims=sims, seed=seed, **kw)


@pytest.fixture(autouse=True)
def _two_week_regular_season(monkeypatch):
    """Windows read the season structure; pin it for the synthetic world."""
    spans = {"regular_season": (1, 3), "playoffs": (4, 5), "cup": (6, 7)}
    monkeypatch.setattr(mv, "stage_weeks", lambda season, stage: spans.get(stage))


# 1 ---------------------------------------------------------------------------
def test_same_question_twice_same_answer_exactly():
    w = _world()
    a = mv.marginal_value(_ctx(w), "Nick", adds=["P70"], drops=["P3"])
    b = mv.marginal_value(_ctx(w), "Nick", adds=["P70"], drops=["P3"])
    assert a == b


def test_asking_other_questions_first_changes_nothing():
    """Keyed draws: no shared stream for an earlier call to advance."""
    w = _world()
    fresh = mv.marginal_value(_ctx(w), "Nick", adds=["P70"], drops=["P3"])
    ctx = _ctx(w)
    for fa in ("P61", "P62", "P80"):
        mv.marginal_value(ctx, "Hayden", adds=[fa], drops=["P20"])
    assert mv.marginal_value(ctx, "Nick", adds=["P70"], drops=["P3"]) == fresh


# 2 ---------------------------------------------------------------------------
def test_common_random_numbers_shrink_the_error():
    w = _world(seed=3)
    crn = _ctx(w, sims=400)
    roster = crn.rosters["Nick"]
    changed = [n for n in roster if n != "P5"] + ["P75"]
    p0, _, _ = mv.roster_totals(crn, roster)
    p1, _, _ = mv.roster_totals(crn, changed)
    indep = _ctx(w, sims=400, seed=999)
    q1, _, _ = mv.roster_totals(indep, changed)
    se_crn = (p1 - p0).std(ddof=1)
    se_ind = (q1 - p0).std(ddof=1)
    assert se_crn < 0.5 * se_ind, (se_crn, se_ind)


# 3 ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(10))
def test_a_pure_add_is_never_negative_in_any_simulation(seed):
    w = _world(seed=seed)
    ctx = _ctx(w, sims=200)
    for fa in w[4][:6]:
        roster = ctx.rosters["Benton"]
        p0, _, _ = mv.roster_totals(ctx, roster)
        p1, _, _ = mv.roster_totals(ctx, roster + [fa])
        assert (p1 - p0 >= -1e-9).all()


# 4 ---------------------------------------------------------------------------
def test_no_games_in_the_window_is_worth_exactly_zero():
    w = _world()
    projs, rosters, nba, weeks, fas = w
    projs["Idle"] = _proj("Idle", "ZZZ", "PG", 60.0)
    r = mv.marginal_value(_ctx(w, extra_players=fas + ["Idle"]), "Nick", adds=["Idle"])
    assert r.points == 0.0 and r.se == 0.0 and r.starts == 0.0


# 5 ---------------------------------------------------------------------------
def test_on_an_empty_roster_value_is_projection_times_games_times_availability():
    projs = {"Solo": _proj("Solo", "BOS", "C", 20.0, gp=80.0),
             "New": _proj("New", "NYK", "PG", 30.0, gp=60.0)}
    d0 = date(2026, 10, 26)
    weeks = [{"week": 2, "start_date": d0.isoformat(), "end_date": (d0 + timedelta(days=6)).isoformat()}]
    nba = {"games": [{"date": (d0 + timedelta(days=k)).isoformat(), "home": "NYK", "away": "MIA"}
                     for k in (0, 2, 4)]}
    ctx = mv.build_context(projs, {"Nick": ["Solo"]}, nba, weeks, "this_week", 1,
                           extra_players=["New"], sims=4000)
    r = mv.marginal_value(ctx, "Nick", adds=["New"])
    expected = 30.0 * 3 * (60.0 / 80.0)          # rate relative to max rostered GP
    assert abs(r.points - expected) < 4 * r.se + 1e-6, (r.points, expected, r.se)
    assert abs(r.starts - 3 * 0.75) < 0.1


def test_injury_override_weeks_are_hard_outs():
    w = _world()
    projs = w[0]
    projs["P70"].out_weeks = [2]
    r = mv.marginal_value(_ctx(w), "Nick", adds=["P70"])
    assert r.points == 0.0


# 6 ---------------------------------------------------------------------------
def test_swapping_back_is_exactly_the_negative():
    w = _world(seed=5)
    ctx = _ctx(w, window="regular_season")
    there = mv.marginal_value(ctx, "Garrett", adds=["P66"], drops=["P50"])
    ctx.rosters["Garrett"] = [n for n in ctx.rosters["Garrett"] if n != "P50"] + ["P66"]
    back = mv.marginal_value(ctx, "Garrett", adds=["P50"], drops=["P66"])
    assert there.points == -back.points
    assert there.starts == -back.starts


# 8 ---------------------------------------------------------------------------
def test_reads_no_files(monkeypatch):
    w = _world()

    def no_open(*a, **k):
        raise AssertionError(f"marginal_value opened a file: {a[:1]}")
    monkeypatch.setattr(builtins, "open", no_open)
    r = mv.marginal_value(_ctx(w), "Nick", adds=["P70"], drops=["P3"])
    assert r.sims == 300


# Contract ---------------------------------------------------------------------
def test_unknown_players_raise_instead_of_reading_as_worthless():
    w = _world()
    ctx = _ctx(w)
    with pytest.raises(KeyError):
        mv.marginal_value(ctx, "Nick", drops=["P70"])        # not his
    with pytest.raises(KeyError):
        mv.marginal_value(ctx, "Nick", adds=["Nobody"])


def test_respelled_names_resolve():
    w = _world()
    projs = w[0]
    projs["Nikola Jokic"] = _proj("Nikola Jokic", "DEN", "C", 60.0)
    w[1]["Nick"].append("Nikola Jokic")
    ctx = _ctx(w)
    r = mv.marginal_value(ctx, "Nick", drops=["Nikola Jokić"])  # accented input
    assert r.drops == ("Nikola Jokic",) and r.points <= 0


def test_unprojected_players_are_named():
    w = _world()
    w[1]["Nick"].append("Deep Guy")
    ctx = _ctx(w, fallback_info={"Deep Guy": ("BOS", "SF")})
    r = mv.marginal_value(ctx, "Nick", drops=["Deep Guy"])
    assert r.unprojected == ("Deep Guy",) and r.points == 0.0


def test_windows_come_from_the_season_structure():
    assert mv.window_weeks("this_week", 1) == [2]
    assert mv.window_weeks("regular_season", 1) == [2, 3]
    assert mv.window_weeks("cup_seeding", 1) == [2, 3, 4, 5]
    assert mv.window_weeks("regular_season", 3) == []           # season over
    with pytest.raises(ValueError):
        mv.window_weeks("ros", 1)


def _weeks(k):
    """k weeks of Nick v Garrett and Hayden v Benton: Nick and Hayden never meet."""
    return [("Nick", "Garrett"), ("Hayden", "Benton")] * k


def test_eliminated_is_exact_and_ties_are_alive():
    from modules.data_loader import Record
    rec = {"Nick": Record(9, 1), "Hayden": Record(6, 4), "Benton": Record(4, 6), "Garrett": Record(1, 9)}
    assert not mv.title_eliminated(rec, _weeks(5), "Nick")
    assert not mv.title_eliminated(rec, _weeks(3), "Hayden")     # 9 reachable: tie, alive
    assert mv.title_eliminated(rec, _weeks(2), "Hayden")         # 8 < 9
    assert mv.title_eliminated(rec, _weeks(4), "Benton")


def test_cup_column_fires_for_the_eliminated_manager_too():
    """The manager who most needs the Cup column is not the runaway leader --
    it is the one with no title path left, and that happens earlier."""
    open_race = {"Benton": {1: 2.0, 2: 30.0, 3: 50.0, 4: 18.0}}  # nothing settled
    from modules.data_loader import Record
    rec = {"Nick": Record(8, 1), "Hayden": Record(6, 3), "Benton": Record(3, 6), "Garrett": Record(1, 8)}
    assert not mv.cup_column_live(open_race, ["Benton"])
    assert mv.cup_column_live(open_race, ["Benton"], records=rec, remaining_pairs=_weeks(4))
    assert not mv.cup_column_live(open_race, ["Benton"], records=rec, remaining_pairs=_weeks(5))
    assert not mv.cup_column_live(open_race, ["Benton"], records=rec)      # pairs unknown


def test_cup_column_is_a_condition_not_a_week():
    settled = {"Nick": {1: 93.0, 2: 7.0, 3: 0.0, 4: 0.0}}
    open_race = {"Nick": {1: 55.0, 2: 40.0, 3: 5.0, 4: 0.0},
                 "Hayden": {1: 0.40, 2: 0.45, 3: 0.15, 4: 0.0}}
    assert mv.cup_column_live(settled, ["Nick", "Benton"])
    assert not mv.cup_column_live(open_race, ["Nick", "Hayden"])


# 9 (logic only; the measurement runs on real rosters) -------------------------
def _validator():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "vmv", Path(__file__).parent.parent / "scripts" / "validate_marginal_value.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_premise_thresholds_are_half_the_original_measurement():
    v = _validator()
    assert set(v.THRESHOLDS) == set(v.ORIGINAL)
    for k in v.ORIGINAL:
        assert abs(v.THRESHOLDS[k] - v.ORIGINAL[k] / 2) <= 1, k


def test_a_weak_premise_is_a_nonzero_exit_not_a_footnote(capsys):
    v = _validator()
    weak = {"rank_spread": 3, "gap_points": 300.0, "mutual_gain_swaps": 50,
            "swaps_examined": 1683, "best_mutual": None, "free_agents": 100}
    assert v.verdict(weak) == ["rank_spread"]
    assert v.report(weak) == 2
    assert "Stop and discuss" in capsys.readouterr().out
    strong = dict(weak, rank_spread=15.5)
    assert v.report(strong) == 0


def test_clearing_the_floor_near_it_is_a_conversation_not_a_ship(capsys):
    """Nick, 10-06: 8 / 169 / 24 is a floor, not a green light."""
    v = _validator()
    near_floor = {"rank_spread": 9, "gap_points": 300.0, "mutual_gain_swaps": 50,
                  "swaps_examined": 1683, "best_mutual": None, "free_agents": 100}
    assert v.report(near_floor) == 3
    assert "Conversation, not ship" in capsys.readouterr().out
    for k in v.ORIGINAL:
        assert abs(v.CLEAR[k] - 0.75 * v.ORIGINAL[k]) <= 1, k


def test_2025_26_dry_run_was_clear():
    """15.5 / 300 / 54 on real 2025-26 rosters, against 12 / 253 / 36."""
    v = _validator()
    dry = {"rank_spread": 15.5, "gap_points": 300.0, "mutual_gain_swaps": 54}
    assert all(v.band(dry, k) == "CLEAR" for k in v.ORIGINAL)


def test_premise_stats_runs_end_to_end_on_a_small_world():
    v = _validator()
    w = _world(seed=2, n_players=70)
    projs, rosters, nba, weeks, fas = w
    small = {m: r[:6] for m, r in rosters.items()}
    ctx = mv.build_context(projs, small, nba, weeks, "this_week", 1,
                           extra_players=fas[:8], sims=50)
    stats = v.premise_stats(ctx, small, fas[:8])
    assert stats["swaps_examined"] == 6 * 36
    assert 0 <= stats["rank_spread"] <= 7


# ---------------------------------------------------------------------------
# STATUS 10-12 sec.3 item 6: the premise check spent its time resolving names
# (23M PlayerIndex lookups) and recomputing the same baseline roster 3,160
# times. Names now resolve once and totals are cached per roster -- which is
# only safe if the cache cannot be corrupted and spelling cannot split it.
# ---------------------------------------------------------------------------

def test_cached_totals_are_read_only_and_shared_across_orderings():
    ctx = _ctx(_world())
    roster = list(ctx.rosters["Nick"])
    pts, starts, _ = mv.roster_totals(ctx, roster)
    with pytest.raises(ValueError):
        pts += 1                                   # a caller cannot corrupt it
    assert mv.roster_totals(ctx, roster)[0] is pts
    assert mv.roster_totals(ctx, list(reversed(roster)))[0] is pts


def test_a_cached_baseline_gives_the_same_answer_as_a_fresh_context():
    w = _world(seed=5)
    warm = _ctx(w)
    for fa in w[4][:5]:                            # fill the caches first
        mv.marginal_value(warm, "Garrett", adds=[fa])
    fresh = _ctx(w)
    assert (mv.marginal_value(warm, "Garrett", adds=[w[4][7]], drops=["P46"])
            == mv.marginal_value(fresh, "Garrett", adds=[w[4][7]], drops=["P46"]))


# ---------------------------------------------------------------------------
# Nick, 10-21: the gate samples trades instead of evaluating all 1,350 from
# both sides, states the sampling, and reports UNSTABLE rather than picking a
# sample when two samples disagree on the band.
# ---------------------------------------------------------------------------

def test_trade_samples_are_disjoint_keyed_and_reproducible():
    v = _validator()
    rosters = {m: [f"{m}{i}" for i in range(15)] for m in ("Nick", "Hayden", "Benton", "Garrett")}
    swaps, chunks = v.sampled_swaps(rosters, 300, 2, ("2026-27", 0))
    assert len(swaps) == 1350 and [len(c) for c in chunks] == [300, 300]
    assert not set(chunks[0]) & set(chunks[1])
    again = v.sampled_swaps(rosters, 300, 2, ("2026-27", 0))[1]
    assert chunks == again
    assert chunks != v.sampled_swaps(rosters, 300, 2, ("2026-27", 5))[1]
    # asking for every swap (or more than exist) is the full, unsampled set
    assert v.sampled_swaps(rosters, None, 2)[1] == [swaps]
    assert v.sampled_swaps(rosters, 700, 2)[1] == [swaps]


def test_sampled_premise_stats_scale_and_band_each_sample():
    v = _validator()
    w = _world(seed=2, n_players=70)
    projs, rosters, nba, weeks, fas = w
    small = {m: r[:6] for m, r in rosters.items()}
    ctx = mv.build_context(projs, small, nba, weeks, "this_week", 1,
                           extra_players=fas[:8], sims=50)
    full = v.premise_stats(ctx, small, fas[:8])
    st = v.premise_stats(ctx, small, fas[:8], trade_sample=60, samples=2, sample_key=("t",))
    assert "samples" not in full and len(st["samples"]) == 2
    assert st["swaps_examined"] == full["swaps_examined"] == 216
    assert (st["rank_spread"], st["gap_points"]) == (full["rank_spread"], full["gap_points"])
    for c in st["samples"]:
        assert c["examined"] == 60
        assert c["estimate"] == round(c["mutual"] / 60 * 216)
        assert c["interval_95"][0] <= c["estimate"] <= c["interval_95"][1]
        assert c["band"] in ("CLEAR", "MARGINAL", "FAIL")


def test_disagreeing_samples_are_unstable_and_recorded(tmp_path):
    v = _validator()
    base = {"rank_spread": 17, "gap_points": 300.0, "swaps_examined": 1350, "free_agents": 115}
    agree = dict(base, mutual_gain_swaps=40, samples=[
        {"examined": 300, "mutual": 9, "estimate": 40, "interval_95": [15, 66], "band": "CLEAR"},
        {"examined": 300, "mutual": 10, "estimate": 45, "interval_95": [18, 72], "band": "CLEAR"}])
    split = dict(agree, samples=[dict(agree["samples"][0]),
                                 dict(agree["samples"][1], estimate=27, band="MARGINAL")])
    assert v.gate_band(agree) == "CLEAR"
    assert v.gate_band(split) == "UNSTABLE"
    gate = v.write_gate(split, "2026-27", 0, {"Nick": ["a"]}, path=tmp_path / "g.json", sims=3000)
    assert gate["band"] == "UNSTABLE" and gate["sampling"]["stable"] is False
    assert gate["sims"] == 3000 and len(gate["sampling"]["samples"]) == 2
    from modules import advice_runner as ar
    assert ar.publish_decision(gate, "2026-27", 5, 3)[0] is False
