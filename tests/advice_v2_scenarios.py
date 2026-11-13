"""
Nick's scenarios (claude/ADVICE_V2_DESIGN.md s.3a, 1-7) as synthetic worlds
for modules/advice_v2 -- V2's acceptance tests (tests/test_advice_v2.py).

Every player has his own NBA team, so his schedule is exactly the days given;
each game is against a dummy team nobody rosters. GP 82 means no baseline
absences, so availability is deterministic except where a tag is set.

Days are (week, weekday): weekday 0 = Monday. Week 1 starts Monday 2026-11-02.

Every fixture's inputs go through advice_v2.assemble, the live path's own
assembly, with the season pass's roster plan built from the fixture's own
world (Fixture.plan_spec: roster_plan.build under the league's rules, 15
active, 2 IL, 3 adds, replacement rank 4). Every team carries a full 15-man
active roster, as the plan keeps them, so the plan adds no stand-in the
fixture did not ask for. Fixture.inputs(now=..., close=...) also takes the live path's
horizon: advice_v2.horizon_for decides the Monday move or the chat move from
the clock against the window close, and the tags are anchored at `now`'s day
(their fetch date) -- scenario 3 runs that way (V2 s.8).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from modules import advice_v2 as av
from modules import injured_drop, roster_plan
from modules.data_loader import PlayerIndex
from modules.projections import PlayerProjection

MON = date(2026, 11, 2)
LA = ZoneInfo("America/Los_Angeles")
ALL = ["PG", "SG", "SF", "PF", "C"]
MANAGERS = ("Nick", "Hayden", "Benton", "Garrett")


def day(week: int, wd: int) -> date:
    return MON + timedelta(days=7 * (week - 1) + wd)


def at(week: int, wd: int, hh: int = 12, mm: int = 0) -> datetime:
    """A moment on the league clock."""
    return datetime.combine(day(week, wd), time(hh, mm), tzinfo=LA)


def close_of(week: int) -> datetime:
    """A week's Monday window close, for the fixtures: 7:00 PM Monday."""
    return at(week, 0, 19, 0)


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

    def stakes(self, lev=0.15, sd=200.0, last=None, manager=None):
        """Hand-made stakes; rs_title from self.rs_title[manager] when set (44b
        s.6: a team with little left to play for), else 0.4."""
        last = max(self.weeks) if last is None else last
        ws = {w: injured_drop.WeekStake(w, lev, None, 0.0, sd) for w in range(1, last + 1)}
        rs = (getattr(self, "rs_title", None) or {}).get(manager, 0.4)
        return injured_drop.TeamStakes(self.weeks[0], True, rs, 0.3, ws, last)

    def plan_spec(self, sw, anchor, active_capacity, il_capacity, stakes=None, open_window=False):
        """advice_v2.PlanSpec for this fixture: roster_plan.build's arguments,
        the plan starting at the tags' week (locked), a window at every later
        week's first day. An injured-drop decision RAISES (no fixture needs one;
        a fixture that does must build its own DropContext). An IL return over
        15 active takes the one activation rule (44a) with the fixture's keep
        chances, its stakes (the long-run weeks' end) and the long-run value
        (roster_plan.LongRun) on the fixture's own world, at advice's sims and
        seed: the measure advice's IL follow-up always used."""
        def refuse(*a, **k):
            raise AssertionError("a fixture's roster plan asked for an injured-drop decision")
        weeks = sorted(sw, key=lambda w: w["week"])
        start = next(w["week"] for w in weeks
                     if date.fromisoformat(w["start_date"]) <= anchor <= date.fromisoformat(w["end_date"]))
        lr = roster_plan.LongRun(nba_schedule={"games": self.games}, schedule_weeks=weeks,
                                 durability_prior=None, season="2026-27", statuses=dict(self.statuses),
                                 anchor=anchor, first_week=start if open_window else start + 1,
                                 last_week=weeks[-1]["week"])

        def stakes_for(m, window):
            ts = stakes[m]
            return injured_drop.TeamStakes(int(window), ts.regular_season, ts.rs_title, ts.champion,
                                           {w: v for w, v in ts.weeks.items() if w >= int(window)},
                                           ts.last_week)
        def games(team, w, from_day=None):
            """His NBA team's games in fantasy week w (from from_day): the fixture's own schedule."""
            wk = next(x for x in weeks if int(x["week"]) == int(w))
            lo, hi = date.fromisoformat(wk["start_date"]), date.fromisoformat(wk["end_date"])
            ds = {date.fromisoformat(g["date"][:10]) for g in self.games if team in (g["home"], g["away"])}
            return sum(1 for d in ds if lo <= d <= hi and (from_day is None or d >= from_day))

        def share(proj):
            from modules import absence
            return 1.0 - absence.durability_miss_rate(float(proj.projected_gp), absence.baseline_params())
        # 44b s.2: a Monday move's open window can need an 18b decision (more injured
        # than IL slots at week 1): it runs on the fixture's stakes, games and durability
        drops = roster_plan.DropContext(
            config=injured_drop.from_rules(), note=(lambda: None) if stakes else (lambda: "fixture: no stakes"),
            stakes=stakes_for, keep=lambda m: dict(self.keep[m]), games=games, availability=share,
            longrun=lr.draws,
            little_left=(lambda m, w: injured_drop.little_left(stakes_for(m, w), injured_drop.from_rules()))
            if stakes else (lambda m, w: None))                 # 44c: stated, no stakes -> the top 4
        return av.PlanSpec(dict(
            start_week=start, il_slots={m: list(self.rosters[m]["il"]) for m in MANAGERS},
            rosters={m: list(self.rosters[m]["active"]) + list(self.rosters[m]["il"]) for m in MANAGERS},
            windows=[(w["week"], date.fromisoformat(w["start_date"])) for w in weeks if w["week"] > start],
            players=PlayerIndex(dict(self.proj)),
            statuses={n: self.statuses.get(n, "HEALTHY") for n in self.proj},
            rules={"active_spots": active_capacity, "il_slots": il_capacity, "add_budget": 3,
                   "il_eligible_tags": {"O", "OFS"}, "replacement_rank": 4},
            standin_gp=82.0, drops=drops, known={},
            # 44b s.2: a Monday move is before the close, so the start week's window is open
            open_day=(date.fromisoformat(weeks[[w["week"] for w in weeks].index(start)]["start_date"])
                      if open_window else None), start_adds_used={}))

    def week_dates(self):
        out = {}
        for w in self.schedule_weeks():
            d0 = date.fromisoformat(w["start_date"])
            d1 = date.fromisoformat(w["end_date"])
            out[w["week"]] = [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]
        return out

    def horizon(self, now, close=None):
        """The live path's horizon at `now` (advice_v2.horizon_for)."""
        wd = self.week_dates()
        week = next(w for w, ds in wd.items() if ds[0] <= now.date() <= ds[-1])
        return av.horizon_for(now, week, wd, close or close_of(week))

    def inputs(self, horizon=(1, 2), opponents=None, adds_left=3, stakes=True, banked=None,
               active_capacity=15, il_capacity=2, sched_weeks=None, balance=True, edge=None,
               now=None, close=None, reserved=(), il_eligible=None, adds=None):
        """balance: each of Nick's horizon opponents is re-projected so his
        expected score that week equals Nick's with no move (plus edge[week]
        points for the opponent), so the matchups are close and a win-chance
        gain is visible. now (and close): the live path -- the horizon from the
        clock (horizon_for), the tags anchored at now's day; otherwise a
        Monday move over `horizon` anchored at its first day. adds: {manager:
        adds left}, else adds_left for everyone."""
        opponents = opponents or {"Nick": {1: "Hayden", 2: "Benton", 3: "Garrett", 4: "Hayden"},
                                  "Hayden": {1: "Nick", 2: "Garrett", 3: "Benton", 4: "Nick"},
                                  "Benton": {1: "Garrett", 2: "Nick", 3: "Hayden", 4: "Garrett"},
                                  "Garrett": {1: "Benton", 2: "Hayden", 3: "Nick", 4: "Benton"}}
        sw = self.schedule_weeks()
        if sched_weeks:
            sw = sw + sched_weeks
        if now is not None:
            hz = self.horizon(now, close)
            anchor = now.date()
        else:
            hz = av.Horizon(av.MONDAY, tuple(horizon), horizon[0], day(horizon[0], 0), close_of(horizon[0]))
            anchor = day(horizon[0], 0)
        weeks = [w for w in hz.weeks if w is not None]
        names = [n for m in MANAGERS for n in self.rosters[m]["active"]]
        if il_eligible is None:
            if hz.kind == av.MONDAY:
                il_eligible = av.monday_il_eligible(names, self.statuses)
            else:
                il_eligible = av.chat_il_eligible(names, self.proj, hz.weeks[0])   # 44b s.5
        st = {m: self.stakes(manager=m) for m in MANAGERS} if stakes else {}
        inp = av.assemble(horizon=hz, season="2026-27", nba_schedule={"games": self.games}, schedule_weeks=sw,
                          durability_prior=None, anchor=anchor, projections=self.proj, statuses=self.statuses,
                          rosters={m: (tuple(self.rosters[m]["active"]), tuple(self.rosters[m]["il"]))
                                   for m in MANAGERS},
                          shape=(active_capacity, il_capacity),
                          adds_left={m: (adds or {}).get(m, adds_left) for m in MANAGERS},
                          keep=self.keep, opponents={m: {w: opponents[m][w] for w in weeks} for m in MANAGERS},
                          pool=[n for n in self.pool if n not in set(reserved)], il_eligible=il_eligible,
                          reserved=frozenset(reserved), stakes=st or {m: None for m in MANAGERS},
                          drop_config=injured_drop.Config(2.0, 1.0, 0.05, 0.05, 4, 6, 0.25, 0.04, 0.075),
                          plan=self.plan_spec(sw, anchor, active_capacity, il_capacity, st,
                                              open_window=hz.kind == av.MONDAY))
        inp.banked = dict(banked or {})
        if balance:
            inp = self._balanced(inp, inp.horizon, opponents, edge or {}, now=now, close=close,
                                 reserved=reserved, il_eligible=il_eligible, adds=adds)
        return inp

    def _balanced(self, inp, horizon, opponents, edge, **live):
        from modules import marginal_value as mv
        ctx = av._mv_ctx(inp, inp.weeks(), 8, 1)
        _p, _s, by_week = mv.roster_totals(ctx, list(inp.managers["Nick"].active))
        for w in inp.weeks():
            opp = opponents["Nick"][w]
            n_days = len(inp.world.dates(w))
            f = (float(by_week[w].mean()) + float(edge.get(w, 0.0))) / (10.0 * n_days)
            for name in self.rosters[opp]["active"]:
                old = self.proj[name]
                self.proj[name] = PlayerProjection(name, old.nba_team, list(old.positions), f,
                                                   projected_gp=82.0)
        return self.inputs(horizon, opponents, inp.managers["Nick"].adds_left, bool(inp.stakes),
                           inp.banked, inp.managers["Nick"].active_capacity,
                           inp.managers["Nick"].il_capacity, balance=False, **live)


# Every day of a week, and the crowded days used below.
WEEK1 = [(1, d) for d in range(7)]
WEEK2 = [(2, d) for d in range(7)]


def opponents_flat(fx: Fixture, fppg_by_manager: dict):
    """Each opponent: 15 players (a full active roster, as the roster plan
    keeps it) with a game every day of weeks 1-3; ten start every day."""
    days = [(w, d) for w in (1, 2, 3) for d in range(7)]
    for m, f in fppg_by_manager.items():
        fx.filler(m, 15, f, days)


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
        # four games a week, like the pickup: the later weeks repeat his week-1
        # days, and with two he would be a 2-game player all season -- not one of
        # "my top 3 guys". (V1's term hid it: it counted all 17 players, IL
        # included, as active after the horizon; the plan keeps 15.)
        fx.player("Jalen Johnson", [(1, 0), (1, 2), (1, 4), (1, 6), (2, 0), (2, 2), (2, 4), (2, 6)], 46.0,
                  manager="Nick", il=True, keep=0.82, status="O", out_weeks=[1, 2, 3])
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


# -----------------------------------------------------------------------------
# V2's scenarios (claude/HANDOFF_ADVICE_V2_2026-11-11.md s.8)
# -----------------------------------------------------------------------------

CONTEST_OPPONENTS = {"Nick": {1: "Benton", 2: "Garrett", 3: "Benton"},
                     "Hayden": {1: "Garrett", 2: "Benton", 3: "Garrett"},
                     "Benton": {1: "Nick", 2: "Hayden", 3: "Nick"},
                     "Garrett": {1: "Hayden", 2: "Nick", 3: "Hayden"}}


def scenario_8():
    """Contested: Nick and Hayden have the same shape of roster (ten core
    players on two crowded days, four bench players, a weak spare) and each
    faces a filler team of about his own strength. One clearly best free
    agent, two good ones behind him."""
    fx = Fixture()
    for m in ("Nick", "Hayden"):
        nick_core(fx) if m == "Nick" else [fx.player(f"HCore {i}", [(1, 1), (2, 3)], 150.0, manager="Hayden",
                                                     keep=0.9 - 0.01 * i) for i in range(10)]
        for i in range(4):
            fx.player(f"{m} Bench {i}", [(1, 0), (1, 2), (1, 5), (2, 0), (2, 2), (2, 5)], 33.0,
                      manager=m, keep=0.3)
        fx.player(f"{m} Spare", [(1, 6)], 8.0, manager=m, keep=0.0)
    opponents_flat(fx, {"Benton": 27.0, "Garrett": 27.0})
    wire(fx, 12, fppg=20.0)
    fx.player("FA Star", [(1, 0), (1, 3), (1, 4), (1, 6), (2, 0), (2, 2), (2, 4), (2, 6)], 42.0, fa=True)
    fx.player("FA Second", [(1, 0), (1, 3), (1, 4), (2, 0), (2, 2), (2, 4)], 34.0, fa=True)
    fx.player("FA Third", [(1, 3), (1, 4), (1, 6), (2, 2), (2, 4), (2, 6)], 33.0, fa=True)
    return fx


def scenario_12():
    """Tags anchored at their fetch date: Nick's spare is tagged O on Tuesday
    of week 1 with games Wed and Fri of week 1 and Mon, Wed, Fri of week 2.
    The chat move's horizon starts next Monday: his three-game chain spends
    the two games this week and at most Monday's next week."""
    fx = Fixture()
    base(fx)
    fx.player("Tagged O", [(1, 2), (1, 4), (2, 0), (2, 2), (2, 4)], 26.0, manager="Nick", keep=0.0,
              status="O")
    fx.player("FA Tagged O", [(1, 2), (2, 0), (2, 2), (2, 4), (2, 6)], 30.0, fa=True, status="O")
    return fx
