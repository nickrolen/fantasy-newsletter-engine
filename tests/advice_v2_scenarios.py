"""
Nick's scenarios (claude/ADVICE_V2_DESIGN.md s.3a, 1-7) as synthetic worlds
for modules/advice_v2 -- V2's acceptance tests (tests/test_advice_v2.py).

Every player has his own NBA team, so his schedule is exactly the days given;
each game is against a dummy team nobody rosters. GP 82 means no baseline
absences, so availability is deterministic except where a tag is set.

Days are (week, weekday): weekday 0 = Monday. Week 1 starts Monday 2026-11-02.
"""

from __future__ import annotations

from datetime import date, timedelta

from modules import advice_v2 as av
from modules import injured_drop
from modules.projections import PlayerProjection

MON = date(2026, 11, 2)
ALL = ["PG", "SG", "SF", "PF", "C"]
MANAGERS = ("Nick", "Hayden", "Benton", "Garrett")


def day(week: int, wd: int) -> date:
    return MON + timedelta(days=7 * (week - 1) + wd)


class Fixture:
    def __init__(self, weeks=(1, 2, 3), lengths=None):
        self.weeks = list(weeks)
        self.lengths = lengths or {}
        self.games = []
        self.proj = {}
        self.statuses = {}
        self.rosters = {m: {"active": [], "il": []} for m in MANAGERS}
        self.keep = {m: {} for m in MANAGERS}
        self.pool = []
        self._n = 0

    def schedule_weeks(self):
        out, start = [], MON
        for w in self.weeks:
            n = self.lengths.get(w, 7)
            out.append({"week": w, "start_date": start.isoformat(),
                        "end_date": (start + timedelta(days=n - 1)).isoformat()})
            start += timedelta(days=n)
        return out

    def player(self, name, days, fppg, positions=None, gp=82, status=None, out_weeks=(),
               manager=None, il=False, keep=0.0, fa=False):
        self._n += 1
        team = f"T{self._n:02d}"
        for (w, wd) in days:
            self.games.append({"date": day(w, wd).isoformat() + "T00:00:00Z", "home": team,
                               "away": "Z" + team})
        self.proj[name] = PlayerProjection(name, team, list(positions or ALL), float(fppg),
                                           projected_gp=float(gp), out_weeks=list(out_weeks))
        if status:
            self.statuses[name] = status
        if manager:
            self.rosters[manager]["il" if il else "active"].append(name)
            self.keep[manager][name] = float(keep)
        if fa:
            self.pool.append(name)
        return name

    def filler(self, manager, n, fppg, days, keep=0.0, prefix=None):
        return [self.player(f"{prefix or manager} {i}", days, fppg, manager=manager, keep=keep)
                for i in range(n)]

    def stakes(self, lev=0.15, sd=200.0, last=None):
        last = max(self.weeks) if last is None else last
        ws = {w: injured_drop.WeekStake(w, lev, None, 0.0, sd) for w in range(1, last + 1)}
        return injured_drop.TeamStakes(self.weeks[0], True, 0.4, 0.3, ws, last)

    def inputs(self, horizon=(1, 2), opponents=None, adds_left=3, stakes=True, banked=None,
               active_capacity=15, il_capacity=2, sched_weeks=None, balance=True, edge=None):
        """balance: each of Nick's horizon opponents is re-projected so his
        expected score that week equals Nick's with no move (plus edge[week]
        points for the opponent), so the matchups are close and a win-chance
        gain is visible."""
        opponents = opponents or {"Nick": {1: "Hayden", 2: "Benton", 3: "Garrett"},
                                  "Hayden": {1: "Nick", 2: "Garrett", 3: "Benton"},
                                  "Benton": {1: "Garrett", 2: "Nick", 3: "Hayden"},
                                  "Garrett": {1: "Benton", 2: "Hayden", 3: "Nick"}}
        sw = self.schedule_weeks()
        if sched_weeks:
            sw = sw + sched_weeks
        world = av.World({"games": self.games}, sw, horizon[0] - 1)
        states = {m: av.ManagerState(m, tuple(self.rosters[m]["active"]), tuple(self.rosters[m]["il"]),
                                     active_capacity, il_capacity, adds_left, dict(self.keep[m]),
                                     {w: opponents[m][w] for w in horizon})
                  for m in MANAGERS}
        anchor = date.fromisoformat(world.week(horizon[0])["start_date"])
        st = {m: self.stakes() for m in MANAGERS} if stakes else {}
        inp = av.MondayInputs("2026-27", tuple(horizon), world, dict(self.proj), dict(self.statuses),
                              states, tuple(self.pool), anchor, st,
                              injured_drop.Config(2.0, 1.0, 0.05, 0.05, 4, 6, 0.25, 0.04, 0.075),
                              dict(banked or {}))
        inp.check()
        if balance:
            inp = self._balanced(inp, horizon, opponents, edge or {})
        return inp

    def _balanced(self, inp, horizon, opponents, edge):
        from modules import marginal_value as mv
        ctx = av._mv_ctx(inp, horizon, 8, 1)
        _p, _s, by_week = mv.roster_totals(ctx, list(inp.managers["Nick"].active))
        for w in horizon:
            opp = opponents["Nick"][w]
            n_days = len(inp.world.dates(w))
            f = (float(by_week[w].mean()) + float(edge.get(w, 0.0))) / (10.0 * n_days)
            for name in self.rosters[opp]["active"]:
                old = self.proj[name]
                self.proj[name] = PlayerProjection(name, old.nba_team, list(old.positions), f,
                                                   projected_gp=82.0)
        return self.inputs(horizon, opponents, inp.managers["Nick"].adds_left, bool(inp.stakes),
                           inp.banked, inp.managers["Nick"].active_capacity,
                           inp.managers["Nick"].il_capacity, balance=False)


# Every day of a week, and the crowded days used below.
WEEK1 = [(1, d) for d in range(7)]
WEEK2 = [(2, d) for d in range(7)]


def opponents_flat(fx: Fixture, fppg_by_manager: dict):
    """Each opponent: 10 players with a game every day of weeks 1-3, all starting."""
    days = [(w, d) for w in (1, 2, 3) for d in range(7)]
    for m, f in fppg_by_manager.items():
        fx.filler(m, 10, f, days)


def nick_core(fx: Fixture, crowded=((1, 1), (2, 3)), keep=None):
    """Nick's ten core players: games ONLY on the crowded days (week 1 Tuesday,
    week 2 Thursday), so those days are full and every other day's ten seats
    are open. The core are his top keepers."""
    return [fx.player(f"Core {i}", list(crowded), 150.0, manager="Nick",
                      keep=(0.9 - 0.01 * i) if keep is None else keep)
            for i in range(10)]


def wire(fx: Fixture, n=12, fppg=22.0):
    """Replacement-level free agents: two games a week on open days."""
    return [fx.player(f"Wire {i}", [(1, 4), (1, 6), (2, 4), (2, 6)], fppg, fa=True) for i in range(n)]


def base(fx: Fixture, bench_fppg=33.0, wire_n=12):
    """Core + four valuable bench players + the flat opponents + the wire."""
    nick_core(fx)
    for i in range(4):
        fx.player(f"Bench {i}", [(1, 0), (1, 2), (1, 5), (2, 0), (2, 2), (2, 5)], bench_fppg,
                  manager="Nick", keep=0.3)
    opponents_flat(fx, {"Hayden": 18.0, "Benton": 18.0, "Garrett": 18.0})
    if wire_n:
        wire(fx, wire_n)


# -----------------------------------------------------------------------------
# the scenarios
# -----------------------------------------------------------------------------

def scenario_1():
    """Coward over Randle: Randle 3 + 2 games, Coward 4 + 4, none on the
    crowded days; Coward projects slightly lower."""
    fx = Fixture()
    base(fx)
    fx.player("Julius Randle", [(1, 2), (1, 4), (1, 6), (2, 2), (2, 4)], 31.0, manager="Nick", keep=0.2)
    fx.player("Cedric Coward", [(1, 0), (1, 2), (1, 3), (1, 5), (2, 0), (2, 2), (2, 3), (2, 5)],
              29.5, fa=True)
    return fx


def scenario_2():
    """The overflow trap: X has 4 games, one on the crowded Tuesday; Y has
    4 games that all start. X projects higher."""
    fx = Fixture()
    base(fx)
    fx.player("Spare", [(1, 6)], 10.0, manager="Nick", keep=0.0)
    fx.player("FA Overflow", [(1, 0), (1, 1), (1, 2), (1, 3)], 31.0, fa=True)
    fx.player("FA Clean", [(1, 0), (1, 2), (1, 3), (1, 4)], 30.0, fa=True)
    return fx


def scenario_3():
    """Lillard for Jerome, a chat move effective next Monday: both have 3
    games next week (week 2); Jerome's Thursday is the crowded day."""
    fx = Fixture(weeks=(1, 2, 3))
    nick_core(fx, crowded=((2, 3), (3, 3)))
    for i in range(4):
        fx.player(f"Bench {i}", [(2, 0), (2, 2), (2, 5), (3, 0), (3, 2), (3, 5)], 33.0,
                  manager="Nick", keep=0.3)
    opponents_flat(fx, {"Hayden": 18.0, "Benton": 18.0, "Garrett": 18.0})
    for i in range(12):
        fx.player(f"Wire {i}", [(2, 4), (3, 4)], 20.0, fa=True)
    fx.player("Ty Jerome", [(2, 1), (2, 3), (2, 6), (3, 1), (3, 6)], 30.0, manager="Nick", keep=0.1)
    fx.player("Damian Lillard", [(2, 1), (2, 4), (2, 6), (3, 1), (3, 6)], 30.0, fa=True)
    return fx


def scenario_4():
    """Up 300: A's games are all this week, B's all next week."""
    fx = Fixture()
    base(fx)
    fx.player("Spare", [(1, 6)], 10.0, manager="Nick", keep=0.0)
    fx.player("FA This Week", [(1, 0), (1, 2), (1, 3), (1, 4)], 30.0, fa=True)
    fx.player("FA Next Week", [(2, 0), (2, 2), (2, 3)], 30.0, fa=True)
    return fx


def scenario_5(jalen_in_paolos_place=False):
    """Paolo yes, Jalen Johnson no. Nick's IL holds Paolo (or Jalen Johnson)
    and Edwards, both out for weeks; Luka is newly O (out this week).
    Keep chances as Nick gave them (Luka .99, JJ .82, Edwards .59, Sabonis .50,
    Clingan .45); Paolo is no keeper."""
    fx = Fixture()
    nick_core(fx, keep=0.05)
    fx.player("Luka Doncic", [(1, 0), (1, 2), (1, 4), (2, 0), (2, 2), (2, 4)], 60.0,
              manager="Nick", keep=0.99, status="O", out_weeks=[1])
    if jalen_in_paolos_place:
        fx.player("Jalen Johnson", [(1, 0), (1, 2), (2, 0), (2, 2)], 46.0, manager="Nick", il=True,
                  keep=0.82, status="O", out_weeks=[1, 2, 3])
    else:
        fx.player("Paolo Banchero", [(1, 0), (1, 2), (2, 0), (2, 2)], 31.0, manager="Nick", il=True,
                  keep=0.20, status="O", out_weeks=[1, 2, 3, 4, 5, 6, 7, 8])
    fx.player("Anthony Edwards", [(1, 0), (1, 2), (2, 0), (2, 2)], 50.0, manager="Nick", il=True,
              keep=0.59, status="O", out_weeks=[1, 2])
    fx.player("Domantas Sabonis", [(1, 0), (1, 5), (2, 0), (2, 5)], 44.0, manager="Nick", keep=0.50)
    fx.player("Donovan Clingan", [(1, 2), (1, 5), (2, 2), (2, 5)], 34.0, manager="Nick", keep=0.45)
    fx.player("Bench A", [(1, 0), (1, 2), (1, 5), (1, 6), (2, 0), (2, 2), (2, 5), (2, 6)], 36.0,
              manager="Nick", keep=0.1)
    fx.player("Bench B", [(1, 0), (1, 3), (1, 5), (1, 6), (2, 0), (2, 3), (2, 5), (2, 6)], 36.0,
              manager="Nick", keep=0.1)
    opponents_flat(fx, {"Hayden": 18.0, "Benton": 18.0, "Garrett": 18.0})
    wire(fx)
    fx.player("FA Pickup", [(1, 0), (1, 2), (1, 4), (1, 6), (2, 0), (2, 2), (2, 4), (2, 6)], 31.0, fa=True)
    # the later weeks: everyone keeps his weekly pattern through week 15
    fx.weeks = list(range(1, 16))
    for name, p in list(fx.proj.items()):
        mine = [date.fromisoformat(g["date"][:10]) for g in fx.games if g["home"] == p.nba_team]
        pattern = sorted({d.weekday() for d in mine if d < day(2, 0)})[:4]
        have = {(d - MON).days // 7 + 1 for d in mine}
        for w in range(3, 16):
            if w in have:
                continue
            for wd in pattern:
                fx.games.append({"date": day(w, wd).isoformat() + "T00:00:00Z", "home": p.nba_team,
                                 "away": "Z" + p.nba_team})
    return fx


def scenario_6():
    """The third add: a marginal gain -- a 12-FPPG two-game free agent for a
    20-FPPG one-game spare, about +4 points. No other free agent."""
    fx = Fixture()
    base(fx, wire_n=0)
    fx.player("Spare", [(1, 6)], 20.0, manager="Nick", keep=0.0)
    fx.player("FA Marginal", [(1, 4), (1, 6)], 12.0, fa=True)
    return fx


def scenario_7(pickup_fppg):
    """The short-term O player: tagged O, no override (back within 3 games),
    an open IL slot, a full active roster. The pickup has 4 games this week."""
    fx = Fixture()
    base(fx)
    fx.player("Short O", [(1, 0), (1, 2), (1, 4), (1, 6), (2, 0), (2, 2), (2, 4), (2, 6)], 36.0,
              manager="Nick", keep=0.25, status="O")
    fx.player("FA Pickup", [(1, 0), (1, 3), (1, 5), (1, 6)], float(pickup_fppg), fa=True)
    return fx
