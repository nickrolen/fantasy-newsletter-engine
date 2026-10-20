"""A4: simulated lineups are legal lineups (HANDOFF_A4_POSITIONS_2026-10-20).

PG SG G SF PF F C C UTIL UTIL. The simulators used to start the ten best
available by projection, which scores lineups nobody could field.
"""
import inspect
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from modules import simulator_betting as sb
from modules import simulator_title_odds as sto
from modules.data_loader import FantasyData
from modules.lineup_fill import exact_fill, max_starters
from modules.projections import PlayerProjection, TeamProjections

MON = date(2026, 10, 26)
WEEK = {"week": 2, "start_date": MON.isoformat(), "end_date": (MON + timedelta(days=6)).isoformat(),
        "matchups": [{"manager_a": "Nick", "manager_b": "Benton"}]}


def _p(name, pos, fp, team="BOS"):
    return PlayerProjection(player_name=name, nba_team=team, positions=pos.split(","),
                            projected_fppg=fp, projected_gp=80.0)


def _data(teams_days=None):
    teams_days = teams_days or {"BOS": range(7)}
    games = [{"date": (MON + timedelta(days=k)).isoformat(), "home": t, "away": "ZZZ"}
             for t, ks in teams_days.items() for k in ks]
    return FantasyData(schedule={"weeks": [WEEK]}, nba_schedule={"games": games}, current_week=1)


def _center_heavy():
    """Six centres among the top ten: two C seats and two UTIL seats take four."""
    ps = [_p(f"C{i}", "C", 50 - i) for i in range(6)]
    ps += [_p("PG1", "PG", 30), _p("SG1", "SG", 29), _p("SF1", "SF", 28), _p("PF1", "PF", 27),
           _p("G1", "PG,SG", 20), _p("F1", "SF,PF", 19)]
    return TeamProjections("Nick", {p.player_name: p for p in ps}, weekly_std_dev=100.0)


def _flexible():
    ps = [_p(f"X{i}", "PG,SG,SF,PF,C", 50 - 2 * i) for i in range(13)]
    return TeamProjections("Benton", {p.player_name: p for p in ps}, weekly_std_dev=100.0)


def _universal(tp):
    """The same roster with every player eligible everywhere: the old top ten."""
    out = TeamProjections(tp.manager, {}, weekly_std_dev=tp.weekly_std_dev)
    for n, p in tp.players.items():
        out.players[n] = PlayerProjection(player_name=n, nba_team=p.nba_team,
                                          positions=["PG", "SG", "SF", "PF", "C"],
                                          projected_fppg=p.projected_fppg, projected_gp=80.0)
    return out


def _sim(teams, n=400, seed=3, statuses=None, data=None):
    return sb.simulate_week_matrix(data or _data(), teams, WEEK, statuses, sb.KeyedDraws(seed, n),
                                   managers=list(teams))


# 1 -- no simulated lineup is ever illegal
def test_every_simulated_lineup_fits_the_slots(monkeypatch):
    seen = []
    real = sb.legal_starters

    def spy(avail, entries, fills):
        out = real(avail, entries, fills)
        seen.append((avail.copy(), out.copy(), entries))
        return out
    monkeypatch.setattr(sb, "legal_starters", spy)
    teams = {"Nick": _center_heavy(), "Benton": _flexible()}
    _sim(teams, statuses={"C0": "Q", "PG1": "O", "X0": "Q"})
    assert seen
    for avail, starters, entries in seen:
        for i in range(len(avail)):
            started = [entries[j] for j in range(len(entries)) if starters[i, j]]
            assert not (starters[i] & ~avail[i]).any()                     # only available players
            assert len(started) <= 10
            assert max_starters([e[5] for e in started]) == len(started)   # they all fit at once
            best = exact_fill([(e[0], e[5], e[6]) for j, e in enumerate(entries) if avail[i, j]])[0]
            assert {e[0] for e in started} == set(best)                    # and it is THE optimal fill


# 2 -- never more than ten; an unfillable day fields fewer
def test_a_roster_that_cannot_field_ten_does_not_score_ten():
    only_c = TeamProjections("Nick", {f"C{i}": _p(f"C{i}", "C", 40 - i) for i in range(12)})
    res = _sim({"Nick": only_c}, n=50)
    assert (res["Nick"]["games"] == 4 * 7).all()        # C, C, UTIL, UTIL -- every day


def test_starters_never_exceed_ten():
    big = TeamProjections("Nick", {f"X{i}": _p(f"X{i}", "PG,SG,SF,PF,C", 40 - i) for i in range(16)})
    res = _sim({"Nick": big}, n=50)
    assert (res["Nick"]["games"] <= 10 * 7).all()


# 3 -- the audit's Hayden week-1 shape: 44 simulated starts that were 42 legal
def test_too_many_centres_lose_their_starts():
    """Today's rosters no longer reproduce Hayden's 44 vs 42 (ROSTERS.json
    was rebuilt on 10-19); this is the same shape built by hand."""
    tp = _center_heavy()
    legal = _sim({"Nick": tp}, n=200)["Nick"]["games"]
    old = _sim({"Nick": _universal(tp)}, n=200)["Nick"]["games"]
    assert (old == 70).all() and (legal == 70).all()    # twelve players: legal ten exist
    tp.players.pop("PG1"); tp.players.pop("G1")          # ten left, no PG at all
    legal = _sim({"Nick": tp}, n=200)["Nick"]["games"]
    old = _sim({"Nick": _universal(tp)}, n=200)["Nick"]["games"]
    # SG1 takes SG; nobody else can play PG or G; SF1, PF1, F1 fill SF, PF, F;
    # four of the six centres take C, C, UTIL, UTIL. Eight a day, not ten.
    assert (old == 70).all() and (legal == 56).all()


# 4 -- the direction: a binding constraint can only lower the projection
def test_where_positions_bind_the_projection_falls():
    tp = _center_heavy()
    tp.players.pop("PG1"); tp.players.pop("G1")
    legal = _sim({"Nick": tp})["Nick"]["score"].mean()
    old = _sim({"Nick": _universal(tp)})["Nick"]["score"].mean()
    assert legal < old


def test_the_maximised_quantity_never_rises(monkeypatch):
    """What a constraint can only lower is what the fill MAXIMISES: the
    projected points of the lineup chosen, in every simulation, on every day.
    NOT each simulation's realised score -- a legal swap can bring in a
    player who outscores the one he replaced on that sampled night -- and
    not the mean once effective_fppg (which scores) differs from
    projected_fppg (which selects)."""
    seen = []
    real = sb.legal_starters

    def spy(avail, entries, fills):
        out = real(avail, entries, fills)
        seen.append((avail, out, entries))
        return out
    monkeypatch.setattr(sb, "legal_starters", spy)
    _sim({"Nick": _center_heavy()}, statuses={"C1": "O", "SF1": "Q", "PG1": "Q"})
    for avail, starters, entries in seen:
        w = np.array([e[6] for e in entries])
        top10 = avail & (np.cumsum(avail, axis=1) <= 10)      # the old rule, for comparison only
        assert ((starters * w).sum(axis=1) <= (top10 * w).sum(axis=1) + 1e-9).all()
        assert (starters.sum(axis=1) <= top10.sum(axis=1)).all()


# 5 -- no change where positions do not bind
def test_where_positions_do_not_bind_nothing_moves():
    tp = _flexible()
    legal = _sim({"Benton": tp})["Benton"]
    old = _sim({"Benton": _universal(tp)})["Benton"]
    for k in ("score", "games"):
        assert np.array_equal(legal[k], old[k])


# the performance route: one fill per distinct availability pattern
def test_exact_fill_runs_once_per_distinct_pattern(monkeypatch):
    calls = []
    real = sb.exact_fill
    monkeypatch.setattr(sb, "exact_fill", lambda ps: calls.append(ps) or real(ps))
    teams = {"Nick": _center_heavy()}
    _sim(teams, n=2000, statuses={"C0": "Q", "PG1": "Q", "SF1": "O"})
    assert 0 < len(calls) < 60                            # not 2000 x 7
    assert len(calls) == len(set(calls))                  # never the same pattern twice


def test_the_bracket_simulators_get_legal_lineups_too():
    only_c = TeamProjections("Nick", {f"C{i}": _p(f"C{i}", "C", 40 - i) for i in range(12)})
    teams = {m: TeamProjections(m, {}) for m in ("Hayden", "Benton", "Garrett")}
    teams["Nick"] = only_c
    random.seed(1)
    out = sb.simulate_week_hifi(_data(), teams, WEEK)
    assert out["Nick"]["games"] == 4 * 7


def test_the_title_odds_daily_path_is_legal_too():
    only_c = TeamProjections("Nick", {f"C{i}": _p(f"C{i}", "C", 40 - i) for i in range(12)})
    random.seed(2)
    _score, games = sto.simulate_manager_daily_score(only_c, {"BOS"}, 2,
                                                     {n: 1.0 for n in only_c.players})
    assert games == 4


# 6 -- the simulators no longer pick an unconstrained top ten
def test_no_simulator_selects_an_unconstrained_top_ten():
    root = Path(__file__).resolve().parent.parent / "modules"
    for name in ("simulator_betting.py", "simulator_title_odds.py", "simulator_cup_odds.py",
                 "simulator_playoff_odds.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "select_top_n_players" not in src, name
        assert "cumsum(avail, axis=1) <= 10" not in src, name
