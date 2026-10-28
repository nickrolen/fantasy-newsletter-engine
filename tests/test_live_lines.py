"""B2: the as-of betting line (HANDOFF_LIVE_LINES_2026-10-20).

spread = (banked_a - banked_b) + E[remaining_a - remaining_b], and the
remainder is insensitive to what already happened -- with keyed draws, a
bit-identity, not a statistical claim.
"""
import inspect
from pathlib import Path
from dataclasses import asdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from modules import simulator_betting as sb
from modules import roster_plan
from modules import week_state as ws
from modules.data_loader import FantasyData
from modules.projections import PlayerProjection, TeamProjections

MON = date(2026, 10, 26)
D = [MON + timedelta(days=k) for k in range(7)]
SCHED = {"BOS": [D[0], D[1], D[3], D[5]], "NYK": [D[0], D[2], D[4]],
         "LAL": [D[1], D[3], D[6]], "MIA": [D[2], D[5]], "DEN": [D[0], D[3], D[6]]}
OPP = {"BOS": "ZZA", "NYK": "ZZB", "LAL": "ZZC", "MIA": "ZZD", "DEN": "ZZE"}
ROSTERS = {
    "Nick":    [("Nikola Jokić", "BOS", 55.0), ("N2", "NYK", 30.0), ("N3", "LAL", 25.0), ("N4", "MIA", 20.0)],
    "Benton":  [("B1", "BOS", 45.0), ("B2", "NYK", 35.0), ("B3", "DEN", 28.0), ("B4", "LAL", 15.0)],
    "Hayden":  [("H1", "DEN", 50.0), ("H2", "MIA", 33.0), ("H3", "NYK", 22.0)],
    "Garrett": [("G1", "LAL", 40.0), ("G2", "BOS", 30.0), ("G3", "MIA", 26.0)],
}
SEED, N = 11, 2000


def _teams():
    return {m: TeamProjections(m, {n: PlayerProjection(player_name=n, nba_team=t, positions=["PG"],
                                                       projected_fppg=fp, projected_gp=80.0)
                                   for n, t, fp in ps}, weekly_std_dev=120.0)
            for m, ps in ROSTERS.items()}


def _logs(through, points=None, log_spelling=None, drop=()):
    """LINEUPS and PLAYERLOG for days before `through`, as update_fantasy_logs writes them.
    points: {(player, date): fp} overrides; drop: {(manager, date)} rows left out."""
    points = points or {}
    log_spelling = log_spelling or {}
    lu, pl = [], []
    for d in D:
        if d >= through:
            break
        for m, ps in ROSTERS.items():
            if (m, d) in drop:
                continue
            for i, (n, t, fp) in enumerate(ps):
                name = log_spelling.get(n, n)
                plays = d in SCHED[t]
                pts = points.get((n, d), fp) if plays else None
                slot = "UTIL"
                base = {"season_year": "2026-27", "week": 2, "date": d.isoformat(), "manager": m,
                        "fantasy_team": m, "player_name": name, "nba_team": t, "positions": "PG",
                        "source": "test", "notes": "", "opponent_manager": ""}
                lu.append({**base, "slot": slot, "nba_opponent": OPP[t] if plays else "",
                           "fantasy_points": pts if plays else ""})
                if plays:
                    pl.append({**base, "nba_opponent": OPP[t], "fantasy_points": pts,
                               "is_injured": pts == 0.0, "started": True})
    cols_pl = ["season_year", "week", "date", "manager", "fantasy_team", "player_name", "nba_team",
               "positions", "nba_opponent", "fantasy_points", "opponent_manager", "source", "notes",
               "is_injured", "started"]
    return pd.DataFrame(lu), pd.DataFrame(pl, columns=cols_pl)


def _data(through=MON, current_week=1, **kw):
    lu, pl = _logs(through, **kw)
    games = [{"date": d.isoformat(), "home": t, "away": OPP[t]} for t, ds in SCHED.items() for d in ds]
    week = {"week": 2, "start_date": MON.isoformat(), "end_date": D[6].isoformat(),
            "matchups": [{"manager_a": "Nick", "manager_b": "Benton"},
                         {"manager_a": "Hayden", "manager_b": "Garrett"}]}
    data = FantasyData(schedule={"weeks": [week]}, nba_schedule={"games": games},
                       playerlog=pl, lineups=lu, current_week=current_week)
    # This world's IL state, stated: nobody in an IL slot (roster_plan reads
    # data/IL_SLOTS.json otherwise, and refuses when it is missing).
    data.il_slots = roster_plan.no_il(2)
    return data, week


def _remainder(as_of, statuses=None, anchors=None, **kw):
    data, week = _data(through=as_of, **kw)
    teams = _teams()
    st = ws.week_state(data, 2, as_of, teams)
    return sb.simulate_week_remainder(data, teams, week, st, SEED, N, statuses, anchors), st


# 1 -- insensitivity, the invariant that defines correctness
def test_yesterdays_results_move_banked_and_not_one_bit_of_the_remainder():
    a, sa = _remainder(D[3])
    b, sb_ = _remainder(D[3], points={("Nikola Jokić", D[1]): 7.0, ("B2", D[2]): 81.5})
    assert sa.banked != sb_.banked
    for m in ROSTERS:
        for k in ("score", "games", "G", "F", "C"):
            assert np.array_equal(a.remaining[m][k], b.remaining[m][k]), (m, k)
    for la, lb in zip(a.lines, b.lines):
        assert la.remaining_mean_a == lb.remaining_mean_a
        assert la.remaining_mean_b == lb.remaining_mean_b
    nick_a, nick_b = a.lines[0], b.lines[0]
    assert nick_b.banked_a - nick_a.banked_a == pytest.approx(7.0 - 55.0)
    assert nick_b.banked_b - nick_a.banked_b == pytest.approx(81.5 - 35.0)


def test_insensitive_for_a_tagged_player_too():
    """His observations condition his chain, but the remaining DRAWS are the
    same; a changed POINT total on a day he played moves nothing."""
    st = {"Nikola Jokić": "Q"}
    a, _ = _remainder(D[3], st, {"Nikola Jokić": MON})
    b, _ = _remainder(D[3], st, {"Nikola Jokić": MON}, points={("Nikola Jokić", D[0]): 70.0})
    assert np.array_equal(a.remaining["Nick"]["score"], b.remaining["Nick"]["score"])


# 2 -- as_of = the first day is the pre-week line, exactly
def test_as_of_the_first_day_reproduces_the_full_week_line_exactly():
    for statuses in (None, {"Nikola Jokić": "O", "H1": "Q"}):
        res, st = _remainder(MON, statuses, {"Nikola Jokić": MON, "H1": MON} if statuses else None)
        assert st.completed == () and all(v == 0.0 for v in st.banked.values())
        data, week = _data()
        teams = _teams()
        for line in res.lines:
            full = sb.run_matchup_simulation(data, teams, week, line.manager_a, line.manager_b, N,
                                             statuses, seed=SEED)
            assert asdict(line) == asdict(full)


# 3 -- after the last game: the banked difference, 100/0
def test_after_the_last_day_the_line_is_the_banked_difference():
    res, st = _remainder(D[6] + timedelta(days=1))
    assert st.remaining == ()
    for line in res.lines:
        assert line.remaining_mean_a == 0.0 and line.remaining_mean_b == 0.0
        diff = line.banked_a - line.banked_b
        assert line.spread_a == -round(diff / sb.SPREAD_GRANULARITY) * sb.SPREAD_GRANULARITY
        assert line.std_dev_a == 0.0 and line.std_dev_b == 0.0
        assert {line.win_prob_a, line.win_prob_b} == {0.0, 100.0}
        assert (line.win_prob_a == 100.0) == (diff > 0)


def test_a_decided_tie_raises_instead_of_flipping_a_coin():
    pts = {}
    # make Hayden and Garrett finish level: zero everyone on both teams
    for m in ("Hayden", "Garrett"):
        for n, t, _ in ROSTERS[m]:
            for d in SCHED[t]:
                pts[(n, d)] = 0.0
    with pytest.raises(sb.DecidedTie):
        _remainder(D[6] + timedelta(days=1), points=pts)


# 4 -- monotonicity
def test_as_of_advancing_never_adds_games_or_removes_banked_points():
    prev = None
    for k in range(9):
        as_of = MON + timedelta(days=k)
        data, _ = _data(through=as_of)
        st = ws.week_state(data, 2, as_of, _teams())
        if prev is not None:
            for p, g in st.games_remaining.items():
                assert g <= prev.games_remaining[p]
            for m, v in st.banked.items():
                assert v >= prev.banked[m]
            assert len(st.remaining) <= len(prev.remaining)
        prev = st


# 5 -- the missing-day guard
def test_a_completed_game_day_with_no_rows_raises():
    data, _ = _data(through=D[3], drop={(m, D[1]) for m in ROSTERS})
    with pytest.raises(ws.MissingLogDay, match="2026-10-27"):
        ws.week_state(data, 2, D[3], _teams())


def test_one_manager_missing_raises_too():
    data, _ = _data(through=D[3], drop={("Garrett", D[2])})
    with pytest.raises(ws.MissingLogDay, match="Garrett"):
        ws.week_state(data, 2, D[3], _teams())


def test_the_override_is_a_stated_assumption_not_a_silent_zero():
    data, _ = _data(through=D[3], drop={(m, D[1]) for m in ROSTERS})
    st = ws.week_state(data, 2, D[3], _teams(), allow_missing_days=True)
    assert any("ASSUMED" in a and "2026-10-27" in a for a in st.assumptions)


def test_preseason_empty_logs_need_the_override():
    data, _ = _data(through=MON)
    data.lineups = data.lineups.iloc[0:0]
    with pytest.raises(ws.MissingLogDay):
        ws.week_state(data, 2, D[2], _teams())


def test_a_partial_playerlog_raises():
    data, _ = _data(through=D[2])
    pl = data.playerlog
    data.playerlog = pl[~((pl["player_name"] == "B2") & (pl["date"] == MON.isoformat()))]
    with pytest.raises(ws.MissingLogDay, match="partial"):
        ws.week_state(data, 2, D[2], _teams())


def test_lineups_is_the_fallback_when_playerlog_has_no_rows_for_a_day():
    data, _ = _data(through=D[2])
    full = ws.week_state(data, 2, D[2], _teams())
    pl = data.playerlog
    data.playerlog = pl[pl["date"] != MON.isoformat()]
    st = ws.week_state(data, 2, D[2], _teams())
    assert st.banked == pytest.approx(full.banked)
    assert any("LINEUPS" in a for a in st.assumptions)


def test_a_day_without_nba_games_needs_no_rows():
    data, _ = _data(through=D[3])
    no_games = [{"date": d.isoformat(), "home": t, "away": OPP[t]}
                for t, ds in SCHED.items() for d in ds if d != D[1]]
    data.nba_schedule = {"games": no_games}
    lu, pl = data.lineups, data.playerlog
    data.lineups = lu[lu["date"] != D[1].isoformat()]
    data.playerlog = pl[pl["date"] != D[1].isoformat()]
    ws.week_state(data, 2, D[3], _teams())          # no raise


# 6 -- name resolution
def test_an_accent_stripped_log_name_banks_against_the_roster_spelling():
    data, _ = _data(through=D[2], log_spelling={"Nikola Jokić": "Nikola Jokic"})
    st = ws.week_state(data, 2, D[2], _teams())
    assert st.banked_by_player["Nick"]["Nikola Jokić"] == pytest.approx(110.0)   # Mon + Tue
    assert "Nikola Jokić" in st.observed and "Nikola Jokic" not in st.observed


# 7 -- no absence double-charging
def _thursday_miss_rate(points, anchors=None):
    st = {"Nikola Jokić": "O"}
    res, _ = _remainder(D[3], st, anchors or {"Nikola Jokić": MON}, points=points)
    blk = res.tag_blocks["Nikola Jokić"]
    return blk, _rate(blk, D[3]), _rate(blk, D[5])


def _rate(blk, d):
    m = blk.missed(d)
    return 0.0 if m is None else float(m.mean())        # None: not an open chain game


def test_sat_monday_and_tuesday_is_not_charged_again_on_thursday():
    """BOS plays Mon, Tue, Thu, Sat. O anchored Monday, missed both: Thursday
    is g3 at P(play)=0.75, Saturday is g4, certain. Re-anchoring at Thursday
    would make Thursday a certain miss and Saturday a coin flip."""
    blk, thu, sat = _thursday_miss_rate({("Nikola Jokić", MON): 0.0, ("Nikola Jokić", D[1]): 0.0})
    assert blk.start == 2 and "missed" in blk.basis
    assert thu == pytest.approx(0.25, abs=0.03)
    assert sat == 0.0


def test_played_monday_is_healthy_for_the_rest_of_the_week():
    blk, thu, sat = _thursday_miss_rate({("Nikola Jokić", D[1]): 0.0})   # played Mon, sat Tue
    assert thu == 0.0 and sat == 0.0


def test_an_unobserved_player_keeps_his_unconditional_block():
    """Not in the logs (e.g. not rostered then): P(still out at g3) = P(k = 3)."""
    data, week = _data(through=D[3])
    pl = data.playerlog
    data.playerlog = pl[pl["player_name"] != "Nikola Jokić"]
    lu = data.lineups
    data.lineups = lu[lu["player_name"] != "Nikola Jokić"]
    teams = _teams()
    st = ws.week_state(data, 2, D[3], teams)
    res = sb.simulate_week_remainder(data, teams, week, st, SEED, N, {"Nikola Jokić": "O"},
                                     {"Nikola Jokić": MON})
    blk = res.tag_blocks["Nikola Jokić"]
    assert "not observed" in blk.basis and blk.start == 0
    assert _rate(blk, D[3]) == pytest.approx(0.125, abs=0.03)


def test_a_fresh_tag_restarts_the_chain_at_its_own_anchor():
    blk, thu, sat = _thursday_miss_rate({}, anchors={"Nikola Jokić": D[3]})
    assert blk.games[0] == D[3] and thu == 1.0                # O: certain out at g1
    assert sat == pytest.approx(0.5, abs=0.03)


# tags mid-week
def test_reconcile_tags():
    prev = {"Nikola Jokić": {"tag": "Q", "anchor": MON.isoformat()},
            "B1": {"tag": "O", "anchor": MON.isoformat()},
            "G1": {"tag": "Q", "anchor": MON.isoformat()}}
    live = {"Nikola Jokic": "Q", "B1": "Q", "H1": "O", "G1": "P"}
    anchors, events, assumptions = ws.reconcile_tags(prev, live, D[3], MON)
    ev = {e["player"]: e["event"] for e in events}
    assert anchors["Nikola Jokic"] == MON and ev["Nikola Jokic"].startswith("unchanged")
    assert anchors["B1"] == D[3] and "changed O -> Q" in ev["B1"]
    assert anchors["H1"] == D[3] and ev["H1"].startswith("new tag")
    assert ev["G1"] == "cleared" and "G1" not in anchors
    assert assumptions == []


def test_no_tag_history_mid_week_raises_unless_assumed():
    with pytest.raises(ws.TagHistoryMissing):
        ws.reconcile_tags(None, {"H1": "O"}, D[3], MON)
    anchors, events, assumptions = ws.reconcile_tags(None, {"H1": "O"}, D[3], MON,
                                                     assume_since_week_start=True)
    assert anchors == {"H1": MON} and assumptions and "ASSUMED" in assumptions[0]
    anchors, events, _ = ws.reconcile_tags(None, {"H1": "O", "B1": "P"}, MON, MON)
    assert anchors == {"H1": MON} and events[0]["event"] == "baseline"


def test_the_tag_week_does_not_follow_current_week():
    """load_all_data sets current_week to the highest week in PLAYERLOG, so
    it reads 2 as soon as week 2's first rows land. The remainder passes the
    week explicitly; the answer must not depend on current_week."""
    st = {"H1": "Q"}
    a, _ = _remainder(D[3], st, {"H1": MON}, current_week=1)
    b, _ = _remainder(D[3], st, {"H1": MON}, current_week=2)
    assert np.array_equal(a.remaining["Hayden"]["score"], b.remaining["Hayden"]["score"])


def test_an_override_still_suppresses_a_tag_mid_week():
    data, week = _data(through=D[3])
    teams = _teams()
    teams["Nick"].players["Nikola Jokić"].out_weeks = [2]
    st = ws.week_state(data, 2, D[3], teams)
    res = sb.simulate_week_remainder(data, teams, week, st, SEED, N, {"Nikola Jokić": "O"},
                                     {"Nikola Jokić": MON})
    assert res.tag_blocks == {}


# the decomposition and the state hash
def test_projected_final_is_banked_plus_remaining():
    res, st = _remainder(D[3])
    for line in res.lines:
        assert line.projected_final_a == line.banked_a + line.remaining_mean_a == line.avg_score_a
        assert line.banked_a == st.banked[line.manager_a]


def test_remaining_mean_is_the_simulated_mean_with_no_discount():
    """The flat 10% OU_INJURY_DISCOUNT is gone (2026-10-21): absences are
    simulated, so the remaining mean is the simulation's mean, untouched."""
    res, _ = _remainder(D[3])
    line = res.lines[0]
    raw = float(res.remaining[line.manager_a]["score"].mean())
    assert line.remaining_mean_a == raw


def test_state_hash_is_stable_and_moves_with_the_logs():
    d1, _ = _data(through=D[3]); d2, _ = _data(through=D[3])
    d3, _ = _data(through=D[3], points={("N2", MON): 1.0})
    h = [ws.week_state(d, 2, D[3], _teams()).state_hash for d in (d1, d2, d3)]
    assert h[0] == h[1] != h[2]


def test_remainder_needs_an_explicit_seed():
    data, week = _data(through=D[3])
    teams = _teams()
    st = ws.week_state(data, 2, D[3], teams)
    with pytest.raises(ValueError, match="seed"):
        sb.simulate_week_remainder(data, teams, week, st, None, N)


# 8 -- no global random in anything B2 touches
def test_b2_never_draws_from_the_global_random_stream():
    import modules.week_state as mod
    sources = [inspect.getsource(mod), inspect.getsource(sb.simulate_week_remainder),
               inspect.getsource(sb.line_from_scores), inspect.getsource(sb.simulate_week_matrix),
               inspect.getsource(sb.tag_blocks), inspect.getsource(sb.remaining_noise_scale)]
    rl = Path(__file__).resolve().parent.parent / "scripts" / "refresh_lines.py"
    sources.append(rl.read_text(encoding="utf-8"))
    for src in sources:
        assert "random." not in src.replace("np.random.Generator", ""), src[:80]
        assert "import random" not in src


# the manual refresh: seed and tag record persist across a week
@pytest.fixture
def refresh(monkeypatch, tmp_path):
    import importlib, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    rl = importlib.import_module("refresh_lines")
    monkeypatch.setattr(rl, "load_all_team_projections", lambda data: _teams())

    def run(as_of, **kw):
        data, _ = _data(through=as_of)
        kw.setdefault("statuses", {"Nikola Jokić": "O"})
        return rl.refresh(tmp_path, week=2, as_of=as_of, sims=500, data=data, **kw)
    run.rl, run.tmp = rl, tmp_path
    return run


def test_refresh_keeps_one_seed_and_the_tags_original_anchor(refresh):
    mon = refresh(MON)
    assert mon["tag_events"][0]["event"] == "baseline"
    thu = refresh(D[3])
    assert thu["seed"] == mon["seed"]
    ev = thu["tag_events"][0]
    assert ev["event"].startswith("unchanged") and ev["anchor"] == MON.isoformat()
    assert "conditioned" in ev["basis"]
    assert (refresh.tmp / "output" / "live_lines_week2.json").exists()
    line = thu["lines"][0]
    assert line["projected_final_a"] == pytest.approx(line["banked_a"] + line["remaining_mean_a"], abs=0.02)
    assert "→" in line["display_a"]


def test_refresh_refuses_a_new_seed_mid_week(refresh):
    refresh(MON, seed=1)
    with pytest.raises(refresh.rl.SeedChanged):
        refresh(D[2], seed=2)
    out = refresh(D[2], seed=2, reseed=True)
    assert any("RESEEDED" in a for a in out["assumptions"])


def test_refresh_mid_week_without_a_tag_record_raises(refresh):
    with pytest.raises(ws.TagHistoryMissing):
        refresh(D[3])
    out = refresh(D[3], assume_tags_since_week_start=True)
    assert any("ASSUMED" in a for a in out["assumptions"])


def test_refresh_will_not_rewind_the_record(refresh):
    refresh(MON)
    refresh(D[3])
    with pytest.raises(RuntimeError, match="dry-run"):
        refresh(D[2])
    refresh(D[2], dry_run=True)


def test_no_tags_is_said_out_loud(refresh):
    out = refresh(MON, statuses=None, no_tags=True)
    assert any("NO TAGS" in a for a in out["assumptions"])
