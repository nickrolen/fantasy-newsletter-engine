"""
A synthetic league for modules/advice_goals (claude/HANDOFF_ADVICE_GOALS_2026-11-24.md),
built with tests/advice_v2_scenarios.Fixture, where each goal's right answer is
known by construction. Made-up players only.

Three weeks, a Monday move in week 1 (horizon 1-2). Nick's ten core players
play only one crowded day a week; four bench players play three days every
week; Spare (10 FPPG, one week-1 game) is the cheap drop. Benton is his
opponent in weeks 2 and 3, balanced to his week-2 level, so weeks 2 and 3 are
close; Hayden in week 1. The free agents:
    Now Guy    31 FPPG, games in week 1 only (now_games of them)
    Both Guy   27 FPPG, three games in week 1 and three in week 2
    Stash Guy  stash_fppg, six games in week 3 only
    Wire 0-2   20 FPPG, two games in weeks 1 and 2
"""

from __future__ import annotations

import advice_v2_scenarios as S

OPP = {"Nick": {1: "Hayden", 2: "Benton", 3: "Benton"}, "Benton": {1: "Garrett", 2: "Nick", 3: "Nick"},
       "Hayden": {1: "Nick", 2: "Garrett", 3: "Garrett"}, "Garrett": {1: "Benton", 2: "Hayden", 3: "Hayden"}}
# the fixture's season: regular season weeks 1-3, then a made-up bracket and Cup
CFG = {"postseason_format": {"stages": {"regular_season": {"weeks": [1, 3]},
                                        "playoffs": {"rounds": [{"name": "Semifinals", "weeks": [4, 4]},
                                                                {"name": "Final", "weeks": [5, 5]}]},
                                        "cup": {"weeks": [6, 6]}}},
       "advice": {"goals": {"noise_z": 2.0, "noise_floor": 0.01, "noise_per_week": 0.01,
                            "noise_title_floor": 0.005, "far_public": False}}}


def fixture(stash_fppg: float = 31.0, now_games: int = 6, returner: bool = False) -> S.Fixture:
    """returner: Nick also has Hurt Guy in an IL slot (O now, out in week 1
    only) and Out Guy on his active roster (O, out all three weeks: a legal IL
    placement) in Bench 3's place -- with a chat move (returner_inputs) the
    plan activates Hurt Guy at week 2's window and drops Spare: the
    activation step every goal's plan is built after."""
    fx = S.Fixture(weeks=(1, 2, 3))
    S.nick_core(fx, crowded=((1, 1), (2, 3), (3, 3)))
    for i in range(3 if returner else 4):
        fx.player(f"Bench {i}", [(w, d) for w in (1, 2, 3) for d in (0, 2, 5)], 33.0, manager="Nick", keep=0.3)
    if returner:
        fx.player("Out Guy", [(w, d) for w in (1, 2, 3) for d in (0, 3)], 30.0, manager="Nick", keep=0.5,
                  status="O", out_weeks=[1, 2, 3])
        fx.player("Hurt Guy", [(w, d) for w in (1, 2, 3) for d in (1, 4)], 40.0, manager="Nick", il=True,
                  keep=0.6, status="O", out_weeks=[1])
    fx.player("Spare", [(1, 6)], 10.0, manager="Nick", keep=0.0)
    days = [(w, d) for w in (1, 2, 3) for d in range(7)]
    for m in ("Hayden", "Benton", "Garrett"):
        fx.filler(m, 15, 18.0, days)
    fx.player("Now Guy", [(1, d) for d in (0, 2, 3, 4, 5, 6)][:now_games], 31.0, fa=True)
    fx.player("Both Guy", [(1, 0), (1, 3), (1, 4), (2, 0), (2, 4), (2, 6)], 27.0, fa=True)
    fx.player("Stash Guy", [(3, d) for d in (0, 2, 3, 4, 5, 6)], stash_fppg, fa=True)
    for i in range(3):
        fx.player(f"Wire {i}", [(1, 4), (1, 6), (2, 4), (2, 6)], 20.0, fa=True)
    return fx


def inputs(fx: S.Fixture, nick_adds: int = 1):
    """Nick's Monday move; nobody else has an add (only his plan is priced)."""
    return fx.inputs(horizon=(1, 2), opponents=OPP,
                     adds={"Nick": nick_adds, "Hayden": 0, "Benton": 0, "Garrett": 0})


def returner_inputs(fx: S.Fixture, nick_adds: int = 2):
    """A chat move (Thursday of week 1, after the close): horizon weeks 2-3."""
    return fx.inputs(opponents=OPP, now=S.at(1, 3), adds={"Nick": nick_adds, "Hayden": 0, "Benton": 0, "Garrett": 0})


def opponents(m: str = "Nick") -> tuple:
    return dict(OPP[m]), {w: 0.5 for w in OPP[m]}


FLIP_OPP = {m: {**v, 4: v[3]} for m, v in OPP.items()}


def flip_fixture():
    """11-25, Nick's real-data failure: a move that FLIPS the plan's mid-week
    decision. A chat move (horizon weeks 2-3, long-run weeks to 4). Nick's IL
    holds Late (O, back on week 2's Saturday: a mid-week returner). His active
    15: ten core (one crowded day a week), three bench, Streak X (four week-2
    games, nothing after: the least long-run value) and P2 (no week-2 game,
    three games in weeks 3 and 4). As the plan stands, activating Late at week
    2's window costs Streak X's four week-2 games for Late's two: it keeps him
    in IL (activate false). After the move "+ Fresh - Streak X" the cheapest
    drop is P2, who has no week-2 game: activating now wins, and the plan
    would activate Late and drop P2 -- a drop no step priced."""
    fx = S.Fixture(weeks=(1, 2, 3, 4))
    S.nick_core(fx, crowded=((1, 1), (2, 3), (3, 3), (4, 3)))
    for i in range(3):
        fx.player(f"Bench {i}", [(w, d) for w in (1, 2, 3, 4) for d in (0, 2)], 33.0, manager="Nick", keep=0.3)
    fx.player("Streak X", [(1, 0), (2, 0), (2, 1), (2, 2), (2, 4)], 25.0, manager="Nick", keep=0.0)
    fx.player("P2", [(w, d) for w in (3, 4) for d in (0, 2, 4)], 20.0, manager="Nick", keep=0.01)
    fx.player("Late", [(w, d) for w in (1, 2, 3, 4) for d in (5, 6)], 40.0, manager="Nick", il=True,
              keep=0.6, status="O")
    p = fx.proj["Late"]
    p.return_date = S.day(2, 5).isoformat()
    p.return_week = 2
    days = [(w, d) for w in (1, 2, 3, 4) for d in range(7)]
    for m in ("Hayden", "Benton", "Garrett"):
        fx.filler(m, 15, 18.0, days)
    fx.player("Fresh", [(w, d) for w in (1, 2, 3, 4) for d in (1, 4, 6)], 30.0, fa=True)
    for i in range(4):
        fx.player(f"Wire {i}", [(w, d) for w in (2, 3, 4) for d in (4, 6)], 15.0, fa=True)
    return fx


def flip_inputs(fx):
    return fx.inputs(opponents=FLIP_OPP, now=S.at(1, 3), balance=False,
                     adds={"Nick": 2, "Hayden": 0, "Benton": 0, "Garrett": 0})


STASH_OPP = FLIP_OPP
# the injured-stash fixture's season: regular season weeks 1-4 (so week 4 is a goal)
CFG4 = {**CFG, "postseason_format": {"stages": {**CFG["postseason_format"]["stages"],
                                                "regular_season": {"weeks": [1, 4]}}}}


def injured_stash_fixture():
    """11-25, Nick's real data (Holmgren): a free agent with no keep chance
    who is the best stash for a far week. Nick's two IL slots hold Long A and
    Long B (out through week 4); Hurt Star (O now, out weeks 1-3, back for six
    week-4 games) is a free agent -- dropped by another team, so nobody's
    keeper watch has him. A move adding him at week 2's window leaves three
    injured for two IL slots: the plan's injured-drop decision must value him
    as a joining pickup (no keep chance, never protected) instead of raising."""
    fx = S.Fixture(weeks=(1, 2, 3, 4))
    S.nick_core(fx, crowded=((1, 1), (2, 3), (3, 3), (4, 3)))
    for i in range(4):
        fx.player(f"Bench {i}", [(w, d) for w in (1, 2, 3, 4) for d in (0, 2)], 33.0, manager="Nick", keep=0.3)
    fx.player("Spare", [(1, 6)], 10.0, manager="Nick", keep=0.0)
    for nm, k in (("Long A", 0.5), ("Long B", 0.4)):
        fx.player(nm, [(w, d) for w in (1, 2, 3, 4) for d in (5, 6)], 35.0, manager="Nick", il=True, keep=k,
                  status="O", out_weeks=[1, 2, 3, 4])
    days = [(w, d) for w in (1, 2, 3, 4) for d in range(7)]
    for m in ("Hayden", "Benton", "Garrett"):
        fx.filler(m, 15, 18.0, days)
    fx.player("Hurt Star", [(w, d) for w in (1, 2, 3, 4) for d in (0, 1, 2, 4, 5, 6)], 45.0, fa=True,
              status="O", out_weeks=[1, 2, 3])
    for i in range(4):
        fx.player(f"Wire {i}", [(w, d) for w in (2, 3) for d in (4, 6)], 15.0, fa=True)
    return fx


def injured_stash_inputs(fx, nick_adds: int = 2):
    return fx.inputs(opponents=STASH_OPP, now=S.at(1, 3), balance=False,
                     adds={"Nick": nick_adds, "Hayden": 0, "Benton": 0, "Garrett": 0})
