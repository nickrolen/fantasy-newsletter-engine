"""
tests/test_advice_replay.py -- the 2025-26 replay's inputs and scoring
(modules/advice_replay), on a small synthetic season.

  - NO LOOKAHEAD: a Monday's inputs (pool, projections, injury stand-ins,
    rosters) do not change by a byte when every box score on or after that
    Monday is deleted; BoxBefore raises on a later date; scoring (Actuals) is
    the only reader of later games.
  - the three rules see the same pool and the same rosters;
  - the fantasy-points formula; basketball-reference's team codes; the
    stand-ins' rules; the season pass is deterministic.
"""

from __future__ import annotations

import inspect
import json
from datetime import date, timedelta

import pytest

from modules import advice_replay as ar
from modules import advice_v2 as av

MANAGERS = ("Benton", "Garrett", "Hayden", "Nick")
START = date(2025, 10, 20)           # a Monday: week 1
TEAMS = ["T%02d" % i for i in range(8)]
FAST = av.Settings(price_sims=200, screen_sims=16, long_sims=4)


def _box(name, pid, d, team, pts):
    return {"date": d.isoformat(), "player": name, "bbref_id": pid, "team": team, "opp": "X",
            "mp": 30.0, "fg": 5, "fga": 10, "fg3": 1, "fg3a": 3, "ft": 2, "fta": 2, "orb": 1, "drb": 4,
            "trb": 5, "ast": 3, "stl": 1, "blk": 0, "tov": 2, "pf": 2, "pts": pts}


def world(weeks=23):
    """4 managers x 6 players and 10 free agents, 8 teams; every team plays Mon/Wed/Fri (69 games);
    everyone plays every game except 'Hurt Guy' (out from
    the start of week 3) and 'Late FA' (no game until week 3)."""
    days = [START + timedelta(days=k) for k in range(7 * weeks)]
    games = [{"date": d.isoformat() + "T00:00:00Z", "home": TEAMS[i], "away": TEAMS[i + 1]}
             for d in days if d.weekday() in (0, 2, 4) for i in range(0, 8, 2)]
    players = {}
    k = 0
    for m in MANAGERS:
        for j in range(6):
            players[f"{m} P{j}"] = (TEAMS[k % 8], m)
            k += 1
    for j in range(10):
        players[f"FA {j}"] = (TEAMS[j % 8], None)
    players["Hurt Guy"] = (TEAMS[0], "Nick")
    players["Late FA"] = (TEAMS[1], None)
    log, box = [], []
    for d in days:
        w = (d - START).days // 7 + 1
        for name, (team, m) in players.items():
            if m:
                log.append({"season_key": "2025-26", "week": w, "date": d.isoformat(), "manager": m,
                            "player_name": name, "positions": "PG,SG,SF,PF,C", "slot": "BN",
                            "nba_team": team, "had_game": d.weekday() in (0, 2, 4)})
            if d.weekday() in (0, 2, 4):
                if name == "Hurt Guy" and w >= 3:
                    continue
                if name == "Late FA" and w < 3:
                    continue
                box.append(_box(name, name.lower().replace(" ", ""), d, team, 10 + (hash(name) % 15)))
    matchups = []
    for w in range(1, weeks + 1):
        a, b, c, e = (("Nick", "Hayden", "Benton", "Garrett") if w % 3 == 1 else
                      ("Nick", "Benton", "Hayden", "Garrett") if w % 3 == 2 else
                      ("Nick", "Garrett", "Hayden", "Benton"))
        for x, y in ((a, b), (c, e)):
            matchups.append({"season": "2025-26", "week": w, "manager_a": x, "manager_b": y,
                             "score_a": 1000.0 + w, "score_b": 990.0})
    prior = [{"player": n, "games": 70, "pts": 15, "fga": 10, "ft": 2, "fta": 2, "fg3": 1, "trb": 5,
              "ast": 3, "stl": 1, "blk": 0, "tov": 2} for n in players]
    return log, box, {"games": games}, matchups, prior, [{"player": n, "pos": "SF"} for n in players]


def season(box_filter=None, weeks=23):
    log, box, sched, mu, prior, pos = world(weeks)
    if box_filter:
        box = [r for r in box if box_filter(r)]
    return ar.Season.build(log, box, sched, mu, prior, pos)


def snapshot(mon: ar.Monday) -> str:
    """Every input of a Monday, as bytes."""
    inp = mon.inputs
    proj = {n: (p.nba_team, list(p.positions), p.projected_fppg, p.projected_gp, list(p.out_weeks),
                p.actual_fppg, p.actual_games) for n, p in sorted(inp.projections.items())}
    rost = {m: (s.active, s.il, s.active_capacity, s.il_capacity, sorted(s.keep.items()),
                sorted(s.opponents.items())) for m, s in sorted(inp.managers.items())}
    return json.dumps({"proj": proj, "statuses": sorted(inp.statuses.items()), "pool": list(inp.pool),
                       "rosters": rost, "anchor": inp.anchor.isoformat(), "o": sorted(mon.o_tags),
                       "long": mon.long_out, "day": mon.decision_day.isoformat()}, sort_keys=True,
                      default=str)


# =============================================================================
# no lookahead
# =============================================================================

@pytest.mark.parametrize("week", [3, 4, 6])
def test_inputs_do_not_change_when_later_box_scores_are_deleted(week):
    full = season()
    cut = full.monday(week)
    trimmed = season(box_filter=lambda r: date.fromisoformat(r["date"]) < cut)
    a = snapshot(ar.build_monday(full, week, FAST))
    b = snapshot(ar.build_monday(trimmed, week, FAST))
    assert a == b


def test_box_before_raises_on_the_cutoff_or_later():
    s = season()
    bb = ar.BoxBefore(s.games, s.monday(4))
    assert all(g.date < s.monday(4) for n in bb.players() for g in bb.player_games(n))
    with pytest.raises(ar.LookaheadError):
        bb.player_games("FA 1", until=s.monday(4))


def test_scoring_is_the_only_reader_of_later_games():
    src = inspect.getsource(ar.build_monday) + inspect.getsource(ar.season_stakes) + \
        inspect.getsource(ar._season_pass)
    assert "Actuals" not in src and "actuals" not in src
    assert "BoxBefore(season.games" in inspect.getsource(ar.build_monday)
    assert "actuals" in inspect.getsource(ar.realised_week)


def test_the_injury_stand_ins():
    s = season()
    m3 = ar.build_monday(s, 4, FAST)
    assert "Hurt Guy" in m3.o_tags              # missed every game of the 7 days before
    assert "Hurt Guy" not in m3.long_out        # but not 8 team games yet
    m6 = ar.build_monday(s, 6, FAST)
    assert "Hurt Guy" in m6.long_out
    assert m6.inputs.projections["Hurt Guy"].out_weeks == [6, 7]
    assert "Late FA" not in ar.build_monday(s, 3, FAST).inputs.pool      # no game before the Monday
    assert "Late FA" in ar.build_monday(s, 4, FAST).inputs.pool


def test_the_three_rules_see_the_same_pool_and_rosters():
    s = season()
    mon = ar.build_monday(s, 5, FAST)
    inp = mon.inputs
    inp.stakes = {m: v for m, v in ar.season_stakes(s, mon, FAST, sims=200).items() if m != "_title"}
    st = inp.managers["Nick"]
    pool, active = set(inp.pool), set(st.active)
    for mo in [av.most_games(inp, "Nick", FAST), av.highest_projection(inp, "Nick", FAST)] + \
            av.candidate_moves(inp, "Nick", FAST):
        if mo is None:
            continue
        assert mo.add in pool
        assert mo.drop is None or mo.drop in active or mo.drop in st.il


# =============================================================================
# the sources' rules
# =============================================================================

def test_the_fantasy_points_formula():
    row = {"pts": 30, "fga": 20, "ft": 6, "fta": 8, "fg3": 3, "trb": 10, "ast": 5, "stl": 2, "blk": 1, "tov": 3}
    assert ar.fantasy_points(row) == pytest.approx(30 - 9 + 3 - 6 + 7.5 + 15 + 10 + 6 + 3 - 6)


def test_basketball_reference_team_codes_are_mapped_and_unknown_ones_raise():
    log, box, sched, mu, prior, pos = world(4)
    sched["games"].append({"date": "2025-10-21T00:00:00Z", "home": "PHX", "away": "T00"})
    box.append(_box("Sun Guy", "sunguy01", date(2025, 10, 21), "PHO", 20))
    s = ar.Season.build(log, box, sched, mu, prior, pos)
    assert {g.team for g in s.games if g.player == "Sun Guy"} == {"PHX"}
    box.append(_box("Odd Guy", "oddguy01", date(2025, 10, 21), "ZZZ", 20))
    with pytest.raises(ValueError, match="ZZZ"):
        ar.Season.build(log, box, sched, mu, prior, pos)


def test_the_cup_final_scores_nothing_and_is_not_scheduled():
    log, box, sched, mu, prior, pos = world(10)
    d = ar.CUP_FINAL[0]
    sched["games"].append({"date": d.isoformat() + "T00:00:00Z", "home": "NYK", "away": "SAS"})
    box.append(_box("Knick", "knick01", d, "NYK", 30))
    box.append(_box("Spur", "spur01", d, "SAS", 30))
    s = ar.Season.build(log, box, sched, mu, prior, pos)
    assert not [g for g in s.games if g.date == d and g.team in ("NYK", "SAS")]
    assert not [g for g in s.schedule["games"] if str(g["date"])[:10] == d.isoformat()
                and {g["home"], g["away"]} == {"NYK", "SAS"}]


def test_the_season_pass_is_deterministic_and_leverage_points_the_right_way():
    s = season()
    mon = ar.build_monday(s, 5, FAST)
    a = ar.season_stakes(s, mon, FAST, sims=400)
    b = ar.season_stakes(s, mon, FAST, sims=400)
    assert a["_title"] == b["_title"]
    for m in MANAGERS:
        ws = a[m].weeks[5]
        assert ws.rs_leverage is None or ws.rs_leverage >= 0


def test_realised_scoring_counts_only_players_who_played_and_no_move_is_zero():
    s = season()
    act = ar.Actuals(s.games)
    mon = ar.build_monday(s, 5, FAST)
    r = ar.realised(s, act, mon.inputs, "Nick", None)
    assert r["pts"] == [0.0, 0.0]
    st = mon.inputs.managers["Nick"]
    pl, il = av.week_roster(mon.inputs, st, None, 0, None)
    total = ar.realised_week(s, act, mon.inputs, pl, il, 5)
    hurt_only = ar.realised_week(s, act, mon.inputs, frozenset({"Hurt Guy"}), frozenset(), 5)
    assert total > 0 and hurt_only == 0.0
