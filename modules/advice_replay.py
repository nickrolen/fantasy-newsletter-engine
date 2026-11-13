"""
advice_replay.py -- the 2025-26 replay's point-in-time inputs and its scoring
(claude/HANDOFF_ADVICE_V1_WORTH_CHECK_2026-11-05.md, phase 2).

Builds advice_v2.MondayInputs for a 2025-26 Monday from what was known before
it, and scores a move on what really happened. Nothing here opens a file:
scripts/advice_v1_replay.py reads the sources and passes them in.

THE SOURCES (phase 0)
    rosters      data/historical/HISTORICAL_PLAYERLOG.json, every slot every
                 day; the decision roster is the last logged day BEFORE the
                 Monday (Sunday night, before the window opens)
    box scores   basketball-reference's daily pages, every player who logged
                 minutes; fantasy points by FANTASY_WEIGHTS, which reproduce
                 Yahoo's own points to the cent on 99.7% of the log's
                 player-games (12 of 4,0xx differ by at most 2: stat
                 corrections). The NBA Cup final (2025-12-16) scores nothing.
    schedule     data/nba_schedule_2025-26.json as published (the Cup final
                 dropped: not a regular-season game)
    matchups     data/historical/all_matchups.json
    prior        basketball-reference per-game 2024-25 (FPPG, games) and 2023-24
                 (games); the league's 2025-26 draft for players with no 2024-25

NO LOOKAHEAD (RETRO_SIM_REQUIREMENTS R1). Every input is read through
BoxBefore, which holds only box rows dated before the cutoff and RAISES if
asked for a later date; Actuals is the only reader of later games and is
used by score() alone. tests/test_advice_replay.py deletes every later row
from a fixture and checks that the inputs do not change by a byte.

THE STAND-INS (stated limits)
    projection   PlayerProjection with projected_fppg = his 2024-25 FPPG (no
                 2024-25 row: drafted in the league's 2025-26 draft, the median
                 of the veterans picked within 3 picks of him; else
                 PRIOR_UNKNOWN_PCTL of the 2024-25 distribution)
                 and actual_fppg / actual_games = season to date, so
                 effective_fppg is the engine's own k / (k + k0) blend. Used
                 by the engine AND by both simple rules.
    durability   projected_gp = YAHOO_GP applied to the mean of his 2023-24 and
                 2024-25 games (Yahoo-like pre-season GP; none: the median).
    injury       O if his team played in the 7 days before the Monday and he
                 played none of those games (absence's 3-game cap applies);
                 and if he also missed every game of the 21 days before, with
                 at least LONG_TEAM_GAMES of them, an override-like out for
                 both horizon weeks -- the stand-in for the override Nick
                 would enter. Everyone else healthy. No OFS.
    keep chance  the top 4 by effective FPPG on the roster stand in for the
                 top 4 by keep chance (no point-in-time keepability).
    positions    Yahoo's, from the log, for anyone ever rostered; else
                 basketball-reference's listed position (narrower than
                 Yahoo's eligibility). The same for all three rules.
"""

from __future__ import annotations

import bisect
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Optional, Sequence

import numpy as np

from . import absence
from . import advice_v2 as av
from . import injured_drop, roster_plan
from .data_loader import PlayerIndex
from .lineup_fill import exact_fill
from .projections import DEFAULT_WEEKLY_STD_DEV, PlayerProjection

FANTASY_WEIGHTS = {"pts": 1.0, "fga": -0.45, "ft": 0.5, "fta": -0.75, "fg3": 2.5,
                   "trb": 1.5, "ast": 2.0, "stl": 3.0, "blk": 3.0, "tov": -2.0}
CUP_FINAL = (date(2025, 12, 16), frozenset({"NYK", "SAS"}))
# basketball-reference's franchise codes -> the schedule's (and Yahoo's)
BBREF_TEAM = {"PHO": "PHX", "BRK": "BKN", "CHO": "CHA"}
REGULAR_THROUGH = 21                       # league_config season_structure 2025-26
BRACKET = (22, 23)                         # semifinals 22, final and 3rd place 23
WEEK16 = 16                                # 2026-02-02: IL+ became bench (LEAGUE_RULES)
SHAPE = {"before": (13, 4), "from": (15, 2)}   # (active, IL incl. IL+)
POOL_SIZE = 175                            # ~Yahoo's visible free-agent list (C2 doc)
PRIOR_UNKNOWN_PCTL = 25
LONG_TEAM_GAMES = 8
DRAFT_WINDOW = 3
# Yahoo's pre-season projected GP against the two seasons' games played before
# it: fitted on Yahoo's 2026-27 pre-season snapshot (148 players with both
# 2024-25 and 2025-26 lines; corr 0.75), a property of Yahoo's method applied
# here to 2025-26's priors -- never 2025-26's own outcomes. Raw games played
# charged a ~39% miss rate at the median and ran the simulated means 213
# points a week under what the same rosters really scored (V1 result s.2).
YAHOO_GP = (51.08, 0.286)
SEASON_SIMS = 4000


def fantasy_points(row: Mapping) -> float:
    return round(sum(w * float(row.get(k, 0) or 0) for k, w in FANTASY_WEIGHTS.items()), 2)


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'\-]", " ", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def strip_accents(name: str) -> str:
    return unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()


# =============================================================================
# names
# =============================================================================

class Names:
    """One canonical name per player: the log's (Yahoo's, accents stripped)
    for anyone the league ever rostered, else basketball-reference's with
    accents stripped. Two basketball-reference ids on one normalised name
    RAISE unless one is the log's player (then the other is suffixed with
    his id)."""

    def __init__(self, log_names: Sequence[str], box_rows: Sequence[Mapping]):
        self.by_norm = {}
        for n in log_names:
            self.by_norm.setdefault(norm(n), strip_accents(n))
        ids = defaultdict(set)
        names = {}
        for r in box_rows:
            ids[norm(r["player"])].add(r["bbref_id"])
            names[r["bbref_id"]] = strip_accents(r["player"])
        self.by_id = {}
        for k, idset in ids.items():
            ordered = sorted(idset)
            for i, pid in enumerate(ordered):
                if len(ordered) == 1:
                    self.by_id[pid] = self.by_norm.get(k, names[pid])
                else:
                    self.by_id[pid] = f"{names[pid]} ({pid})"
        self.collisions = {k: sorted(v) for k, v in ids.items() if len(v) > 1}

    def of_box(self, row: Mapping) -> str:
        return self.by_id[row["bbref_id"]]

    def of_log(self, name: str) -> str:
        return self.by_norm.get(norm(name), strip_accents(name))


# =============================================================================
# box scores: before a cutoff (inputs) and after (scoring only)
# =============================================================================

@dataclass(frozen=True)
class Game:
    player: str
    date: date
    team: str
    fp: float
    minutes: float


def games_from_box(box_rows: Sequence[Mapping], names: Names) -> list:
    out = []
    for r in box_rows:
        d = date.fromisoformat(r["date"])
        if d == CUP_FINAL[0] and r["team"] in CUP_FINAL[1]:
            continue
        team = BBREF_TEAM.get(r["team"], r["team"])
        out.append(Game(names.of_box(r), d, team, fantasy_points(r), float(r.get("mp", 0) or 0)))
    out.sort(key=lambda g: (g.date, g.player))
    return out


class LookaheadError(RuntimeError):
    """An input asked for a game on or after its cutoff."""


class BoxBefore:
    """Only the games dated before `cutoff`. Asking for anything on or after
    it raises (R1)."""

    def __init__(self, games: Sequence[Game], cutoff: date):
        self.cutoff = cutoff
        self._games = [g for g in games if g.date < cutoff]
        self._by_player = defaultdict(list)
        for g in self._games:
            self._by_player[g.player].append(g)

    def _guard(self, d: date):
        if d >= self.cutoff:
            raise LookaheadError(f"asked about {d}, on or after the cutoff {self.cutoff}")

    def player_games(self, name: str, since: Optional[date] = None, until: Optional[date] = None) -> list:
        until = until or self.cutoff - timedelta(days=1)
        self._guard(until)
        return [g for g in self._by_player.get(name, ()) if (since is None or g.date >= since)
                and g.date <= until]

    def players(self) -> list:
        return sorted(self._by_player)

    def last_team(self, name: str) -> Optional[str]:
        gs = self._by_player.get(name)
        return gs[-1].team if gs else None


class Actuals:
    """Every game, for scoring. Only score() reads it."""

    def __init__(self, games: Sequence[Game]):
        self.fp = {(g.player, g.date): g.fp for g in games}

    def played(self, name: str, d: date) -> Optional[float]:
        return self.fp.get((name, d))


# =============================================================================
# the season's fixed facts
# =============================================================================

@dataclass
class Season:
    names: Names
    games: list                     # [Game], every game of the season
    log: list                       # the 2025-26 log rows (rosters)
    schedule: dict                  # {"games": [...]}, the Cup final dropped
    weeks: list                     # [{"week", "start_date", "end_date"}]
    matchups: list                  # 2025-26 rows of all_matchups.json
    prior: dict                     # canonical name -> (fppg, gp) for 2024-25
    positions: dict                 # canonical name -> [positions]
    prior_unknown: float = 0.0
    gp_median: float = 60.0
    draft_priored: list = None      # players whose prior came from the draft

    @classmethod
    def build(cls, log_rows, box_rows, nba_schedule, matchups, prior_rows, pos_rows,
              prev_rows=(), draft_rows=()):
        """prior_rows: 2024-25 per-game (FPPG and games); prev_rows: 2023-24
        per-game (games only: the durability prior is the mean of the two
        seasons' games, capped at 82); draft_rows: the league's 2025-26 draft
        (all_drafts.json), pre-season information -- a drafted player with no
        2024-25 line gets the median 2024-25 FPPG of the veterans picked
        within DRAFT_WINDOW picks of him."""
        log = [r for r in log_rows if r["season_key"] == "2025-26"]
        names = Names([r["player_name"] for r in log_rows], box_rows)
        games = games_from_box(box_rows, names)
        sched = {"games": [g for g in nba_schedule["games"] if g.get("home") and g.get("away")
                           and not (str(g["date"])[:10] == CUP_FINAL[0].isoformat()
                                    and {g["home"], g["away"]} == set(CUP_FINAL[1]))]}
        teams = {t for g in sched["games"] for t in (g["home"], g["away"])}
        unknown = sorted({g.team for g in games} - teams)
        if unknown:
            raise ValueError(f"box-score teams not in the schedule: {unknown} (map them in BBREF_TEAM)")
        wk = defaultdict(list)
        for r in log:
            wk[int(r["week"])].append(r["date"])
        weeks = [{"week": w, "start_date": min(v), "end_date": max(v)} for w, v in sorted(wk.items())]
        # weeks run Monday to Sunday: widen to whole calendar spans (a day with no
        # log rows, e.g. no games, still belongs to its week)
        for i, w in enumerate(weeks):
            if i + 1 < len(weeks):
                nxt = date.fromisoformat(weeks[i + 1]["start_date"])
                w["end_date"] = (nxt - timedelta(days=1)).isoformat()
        prev_gp = {names.of_log(r["player"]): float(r["games"]) for r in prev_rows}
        prior, gps = {}, []
        for r in prior_rows:
            n = names.of_log(r["player"])
            g = [float(r["games"])] + ([prev_gp[n]] if n in prev_gp else [])
            prior[n] = (fantasy_points(r), yahoo_like_gp(float(np.mean(g))))
            gps.append(prior[n][1])
        picks = sorted((int(r["pick_number"]), names.of_log(r["player_name"])) for r in draft_rows
                       if r.get("season") == "2025-26" and not r.get("is_keeper"))
        draft_prior = {}
        for pk, n in picks:
            if n in prior:
                continue
            near = [prior[m][0] for q, m in picks if abs(q - pk) <= DRAFT_WINDOW and m in prior]
            if near:
                draft_prior[n] = float(np.median(near))
        fp_all = sorted(v[0] for v in prior.values() if v[1] >= 20)
        unknown = float(np.percentile(fp_all, PRIOR_UNKNOWN_PCTL)) if fp_all else 15.0
        positions = {}
        for r in pos_rows:
            positions.setdefault(names.of_log(r["player"]), _bbref_positions(r["pos"]))
        for r in sorted(log, key=lambda r: r["date"]):
            positions[names.of_log(r["player_name"])] = [p.strip() for p in str(r["positions"]).split(",")
                                                       if p.strip() in ("PG", "SG", "SF", "PF", "C")]
        gp_median = float(np.median(gps)) if gps else 60.0
        for n, f in draft_prior.items():
            prior[n] = (f, gp_median)
        return cls(names, games, log, sched, weeks, [m for m in matchups if m["season"] == "2025-26"],
                   prior, positions, unknown, gp_median, sorted(draft_prior))

    def week_of(self, w: int) -> dict:
        return next(x for x in self.weeks if x["week"] == w)

    def monday(self, w: int) -> date:
        return date.fromisoformat(self.week_of(w)["start_date"])

    def opponents(self, w: int) -> dict:
        out = {}
        for m in self.matchups:
            if int(m["week"]) == w:
                out[m["manager_a"]] = m["manager_b"]
                out[m["manager_b"]] = m["manager_a"]
        return out

    def margin(self, manager: str, w: int) -> Optional[float]:
        for m in self.matchups:
            if int(m["week"]) == w:
                if m["manager_a"] == manager:
                    return float(m["score_a"]) - float(m["score_b"])
                if m["manager_b"] == manager:
                    return float(m["score_b"]) - float(m["score_a"])
        return None


def yahoo_like_gp(games_mean: float) -> float:
    return float(min(82.0, max(0.0, YAHOO_GP[0] + YAHOO_GP[1] * games_mean)))


def _bbref_positions(pos: str) -> list:
    out = []
    for p in str(pos).replace("G-F", "SG-SF").replace("F-C", "PF-C").split("-"):
        p = p.strip()
        if p == "G":
            out += ["PG", "SG"]
        elif p == "F":
            out += ["SF", "PF"]
        elif p in ("PG", "SG", "SF", "PF", "C"):
            out.append(p)
    return sorted(set(out)) or ["SF"]


# =============================================================================
# a Monday's inputs
# =============================================================================

@dataclass
class Monday:
    week: int
    inputs: av.MondayInputs
    decision_day: date
    o_tags: dict                  # name -> "O" (stand-in)
    long_out: list                # names given the override-like out
    pool_all: int                 # free agents who had played, before the cut to POOL_SIZE


def decision_rosters(season: Season, monday: date) -> tuple:
    """(day, {manager: (active, il)}) from the last logged day before the Monday."""
    days = sorted({r["date"] for r in season.log if r["date"] < monday.isoformat()})
    if not days:
        raise ValueError(f"no logged roster before {monday}")
    d = days[-1]
    ro = defaultdict(lambda: ([], []))
    for r in sorted((r for r in season.log if r["date"] == d), key=lambda r: r["player_name"]):
        name = season.names.of_log(r["player_name"])
        (ro[r["manager"]][1] if r["slot"] in ("IL", "IL+") else ro[r["manager"]][0]).append(name)
    return date.fromisoformat(d), {m: (tuple(a), tuple(i)) for m, (a, i) in ro.items()}


def team_dates(schedule: dict) -> dict:
    out = defaultdict(list)
    for g in schedule["games"]:
        d = date.fromisoformat(str(g["date"])[:10])
        out[g["home"]].append(d)
        out[g["away"]].append(d)
    return {t: sorted(v) for t, v in out.items()}


def build_monday(season: Season, week: int, settings: av.Settings) -> Monday:
    """The engine's inputs for the Monday that opens `week`, from games
    before it only (BoxBefore)."""
    M = season.monday(week)
    box = BoxBefore(season.games, M)
    horizon = (week, week + 1)
    dday, ro = decision_rosters(season, M)
    shape = SHAPE["from"] if week >= WEEK16 else SHAPE["before"]
    tdates = team_dates(season.schedule)
    rostered = {n for a, i in ro.values() for n in a + i}
    log_team = {season.names.of_log(r["player_name"]): r["nba_team"] for r in season.log
                if r["date"] == dday.isoformat()}

    def projection(name, out_weeks=()):
        gs = box.player_games(name)
        prior = season.prior.get(name)
        pf = prior[0] if prior else season.prior_unknown
        gp = min(82.0, prior[1]) if prior else season.gp_median
        team = box.last_team(name) or log_team.get(name) or ""
        p = PlayerProjection(name, team, list(season.positions.get(name, ["SF"])), max(0.0, float(pf)),
                             projected_gp=float(gp), out_weeks=list(out_weeks))
        if gs:
            p.actual_games = len(gs)
            p.actual_fppg = float(np.mean([g.fp for g in gs]))
        return p

    def absent(name, days, team):
        since = M - timedelta(days=days)
        tg = [d for d in tdates.get(team, []) if since <= d < M]
        played = {g.date for g in box.player_games(name, since=since)}
        return tg, (len(tg) > 0 and not (played & set(tg)))

    candidates = [n for n in box.players() if n not in rostered]
    proj, statuses, long_out = {}, {}, []
    for name in sorted(rostered | set(candidates)):
        p = projection(name)
        tg7, out7 = absent(name, 7, p.nba_team)
        if out7:
            statuses[name] = "O"
            tg21, out21 = absent(name, 21, p.nba_team)
            if out21 and len(tg21) >= LONG_TEAM_GAMES:
                p = projection(name, out_weeks=horizon)
                long_out.append(name)
        proj[name] = p
    ranked = sorted(candidates, key=lambda n: (-proj[n].effective_fppg, n))
    pool = tuple(ranked[:POOL_SIZE])
    keep_names = set(rostered) | set(pool)
    proj = {n: p for n, p in proj.items() if n in keep_names}
    statuses = {n: s for n, s in statuses.items() if n in keep_names}

    opps = {w: season.opponents(w) for w in horizon}
    world = av.World(season.schedule, season.weeks, week - 1)
    states = {}
    for m, (act, il) in sorted(ro.items()):
        roster = list(act) + list(il)
        top = sorted(roster, key=lambda n: (-proj[n].effective_fppg, n))
        keep = {n: (1.0 - i / 100.0) for i, n in enumerate(top)}
        states[m] = av.ManagerState(m, act, il, max(shape[0], len(act)), max(shape[1], len(il)), 3,
                                    keep, {w: opps[w][m] for w in horizon})
    inp = av.MondayInputs("2025-26", horizon, world, proj, statuses, states, pool, M,
                          drop_config=injured_drop.from_rules())
    inp.plan = replay_plan(season, week, inp, ro, shape)
    inp.check()
    return Monday(week, inp, dday, {n: "O" for n in statuses}, sorted(long_out), len(candidates))


def replay_plan(season: "Season", week: int, inp: av.MondayInputs, ro: Mapping, shape: tuple) -> av.PlanSpec:
    """The roster plan for a replay Monday (advice v2's title term reads every
    week's rosters off one: HANDOFF_ADVICE_TITLE_TERM s.2). roster_plan.build
    on the Monday's own inputs only -- no lookahead:
      - starts at the Monday's week (locked), a window every later Monday;
      - rules: 3 adds, replacement rank 4, O/OFS to IL; the shape the
        Monday's (13 + 4 before week 16, 15 + 2 from it), raised to the
        largest roster the log shows that day (the replay's capacity rule);
        one shape for the season's rest -- the week-16 change is not played
        (stated limit);
      - tags: the replay's O stand-ins; nobody else is tagged, so the pool is
        priced healthy (assume_healthy: the replay has no Yahoo tags);
      - injuries: the override-like outs (out_weeks over the horizon);
      - an IL return over its active spots takes the one activation rule
        (roster_plan.activation_drops, 44a) with the keep stand-ins and the
        long-run value (roster_plan.LongRun) on the Monday's own world, its
        protection count from the replay's stakes once priced (the top 4
        before: stated, 44c);
      - an injured-drop decision reads the replay's own stakes once
        run_week has priced them (inp.stakes), the keep stand-ins, the
        schedule's games and the durability miss rate; before then the plan
        takes roster_plan's bootstrap path and says so."""
    cfg = injured_drop.from_rules()
    params = absence.baseline_params()
    tdates = team_dates(season.schedule)

    def note():
        return None if inp.stakes else "the replay's stakes are not priced yet"

    def stakes(m, window):
        ts = inp.stakes[m]
        return injured_drop.TeamStakes(int(window), int(window) <= REGULAR_THROUGH, ts.rs_title, ts.champion,
                                       {w: v for w, v in ts.weeks.items() if w >= int(window)}, ts.last_week)

    def keep(m):
        return dict(inp.managers[m].keep)

    def games(team, w, from_day=None):
        ds = set(season_dates(season, w))
        return sum(1 for d in tdates.get(str(team).upper(), ()) if d in ds and (from_day is None or d >= from_day))

    def share(p):
        return 1.0 - absence.durability_miss_rate(float(p.projected_gp), params)

    # the one activation rule (44a): the long-run value on the Monday's own world, its tags
    # anchored at the Monday -- the measure advice's IL follow-up always used
    lr = roster_plan.LongRun(nba_schedule=inp.world.nba_schedule, schedule_weeks=inp.world.schedule["weeks"],
                             durability_prior=inp.world.durability_prior, season=inp.season,
                             statuses=dict(inp.statuses), anchor=inp.anchor, first_week=int(week) + 1,
                             last_week=BRACKET[1])
    def little(m, window):
        # 44b s.6's little-left check, stated (44c: an unstated one raises): on the replay's own
        # stakes once priced; before, none -- the top 4, as its decisions take the bootstrap
        return injured_drop.little_left(stakes(m, window), cfg) if inp.stakes else None

    drops = roster_plan.DropContext(config=cfg, note=note, stakes=stakes, keep=keep, games=games,
                                    availability=share, longrun=lr.points, little_left=little)
    active = max([shape[0]] + [len(a) for a, _i in ro.values()])
    il = max([shape[1]] + [len(i) for _a, i in ro.values()])
    return av.PlanSpec(dict(
        start_week=int(week), il_slots={m: list(i) for m, (_a, i) in ro.items()},
        rosters={m: list(a) + list(i) for m, (a, i) in ro.items()},
        windows=[(w, season.monday(w)) for w in range(int(week) + 1, BRACKET[1] + 1)],
        players=PlayerIndex(dict(inp.projections)), statuses=dict(inp.statuses), assume_healthy=True,
        rules={"active_spots": active, "il_slots": il, "add_budget": 3, "il_eligible_tags": {"O", "OFS"},
               "replacement_rank": 4},
        standin_gp=float(season.gp_median), drops=drops, known={}))


# =============================================================================
# the stakes: a light 2025-26 season pass (no lookahead: results before the Monday)
# =============================================================================

def season_stakes(season: Season, mon: Monday, settings: av.Settings, sims: int = SEASON_SIMS,
                  shift: Optional[Mapping] = None) -> dict:
    """manager -> injured_drop.TeamStakes for the weeks from the Monday's week
    through 23, from a team-level season pass: each remaining week's score
    ~ Normal(mu, sd), mu = the manager's expected started points that week
    with his current roster (marginal_value; IL occupants back when the
    absence model has them back), sd = DEFAULT_WEEKLY_STD_DEV x
    sqrt(days / 7); regular season to week 21 by wins, then points; seeds
    1v4 and 2v3 in week 22, the final in week 23. shift: {(manager, week):
    points} added to mu (the full-run check of the title-odds estimate)."""
    inp = mon.inputs
    w0 = mon.week
    weeks = list(range(w0, BRACKET[1] + 1))
    ctx = av._mv_ctx(inp, weeks, settings.long_sims, settings.seed)
    managers = sorted(inp.managers)
    mu = {}
    for m in managers:
        _p, _s, bw = av._totals(ctx, list(inp.managers[m].roster()))
        for w in weeks:
            mu[(m, w)] = bw.get(w, 0.0) + float((shift or {}).get((m, w), 0.0))
    return _season_pass(season, w0, managers, mu, sims, settings.seed, inp.drop_config)


def _season_pass(season, w0, managers, mu, sims, seed, cfg):
    rng = np.random.default_rng(seed + 1000 * w0)
    idx = {m: i for i, m in enumerate(managers)}
    n = len(managers)
    wins = np.zeros((sims, n))
    pts = np.zeros((sims, n))
    for row in season.matchups:
        w = int(row["week"])
        if w >= w0 or w > REGULAR_THROUGH:
            continue
        a, b = idx[row["manager_a"]], idx[row["manager_b"]]
        sa, sb_ = float(row["score_a"]), float(row["score_b"])
        wins[:, a] += 1.0 if sa > sb_ else (0.5 if sa == sb_ else 0.0)
        wins[:, b] += 1.0 if sb_ > sa else (0.5 if sa == sb_ else 0.0)
        pts[:, a] += sa
        pts[:, b] += sb_
    scores = {}
    for w in range(w0, BRACKET[1] + 1):
        days = len(season_dates(season, w))
        sd = DEFAULT_WEEKLY_STD_DEV * math.sqrt(days / 7.0)
        scores[w] = np.stack([mu[(m, w)] + sd * rng.standard_normal(sims) for m in managers], axis=1)
    won = {}       # (manager, week) -> bool[sims]; margin
    margin = {}
    for w in range(w0, REGULAR_THROUGH + 1):
        for a_name, b_name in _pairs(season.opponents(w)):
            a, b = idx[a_name], idx[b_name]
            sa, sb_ = scores[w][:, a], scores[w][:, b]
            wins[:, a] += sa > sb_
            wins[:, b] += sb_ > sa
            pts[:, a] += sa
            pts[:, b] += sb_
            won[(a_name, w)], won[(b_name, w)] = sa > sb_, sb_ > sa
            margin[(a_name, w)], margin[(b_name, w)] = sa - sb_, sb_ - sa
    key = wins * 1e6 + pts
    order = np.argsort(-key, axis=1)                      # seeds 0..3
    seed_of = np.empty_like(order)
    rows = np.arange(sims)[:, None]
    seed_of[rows, order] = np.arange(n)[None, :]
    rs_title = {m: (seed_of[:, idx[m]] == 0) for m in managers}
    s22 = scores[BRACKET[0]]
    s23 = scores[BRACKET[1]]
    champ = np.zeros((sims, n), dtype=bool)
    for i in range(sims):
        t = order[i]
        semi = [(t[0], t[3]), (t[1], t[2])]
        fin = []
        for a, b in semi:
            wa = s22[i, a] > s22[i, b]
            fin.append(a if wa else b)
            for x, y in ((a, b), (b, a)):
                won.setdefault((managers[x], 22), np.zeros(sims, dtype=bool))[i] = s22[i, x] > s22[i, y]
                margin.setdefault((managers[x], 22), np.zeros(sims))[i] = s22[i, x] - s22[i, y]
        a, b = fin
        ch = a if s23[i, a] > s23[i, b] else b
        champ[i, ch] = True
        for x, y in ((a, b), (b, a)):
            won.setdefault((managers[x], 23), np.zeros(sims, dtype=bool))[i] = s23[i, x] > s23[i, y]
            margin.setdefault((managers[x], 23), np.zeros(sims))[i] = s23[i, x] - s23[i, y]
        losers = [x for pair in semi for x in pair if x not in fin]
        for x, y in ((losers[0], losers[1]), (losers[1], losers[0])):
            won.setdefault((managers[x], 23), np.zeros(sims, dtype=bool))[i] = False
            margin.setdefault((managers[x], 23), np.zeros(sims))[i] = s23[i, x] - s23[i, y]
    out = {}
    for m in managers:
        rs = rs_title[m]
        ch = champ[:, idx[m]]
        ws = {}
        for w in range(w0, BRACKET[1] + 1):
            k = (m, w)
            if k not in won:
                continue
            win = won[k]
            lose = ~win
            def lev(target):
                if win.sum() == 0 or lose.sum() == 0:
                    return None
                return float(target[win].mean() - target[lose].mean())
            mg = margin[k]
            ws[w] = injured_drop.WeekStake(
                w, lev(rs) if w <= REGULAR_THROUGH else None,
                lev(ch), float(mg.mean()), float(mg.std()) or 1.0)
        out[m] = injured_drop.TeamStakes(w0, w0 <= REGULAR_THROUGH, float(rs.mean()), float(ch.mean()),
                                         ws, BRACKET[1])
    out["_title"] = {m: (float(rs_title[m].mean()), float(champ[:, idx[m]].mean())) for m in managers}
    return out


def stake_units(st: Mapping, cfg: injured_drop.Config) -> dict:
    return {m: cfg.rs_weight * v[0] + cfg.playoff_weight * v[1] for m, v in st["_title"].items()}


def _pairs(opps: Mapping) -> list:
    seen, out = set(), []
    for a, b in sorted(opps.items()):
        if a not in seen and b not in seen:
            out.append((a, b))
            seen |= {a, b}
    return out


def season_dates(season: Season, w: int) -> list:
    wk = season.week_of(w)
    d0, d1 = date.fromisoformat(wk["start_date"]), date.fromisoformat(wk["end_date"])
    return [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]


# =============================================================================
# scoring: what really happened
# =============================================================================

def realised_week(season: Season, actuals: Actuals, inputs: av.MondayInputs, players, il, week) -> float:
    """Real fantasy points of the roster in `week`: each day, the exact fill
    of the active players who really played, chosen on the Monday's
    projection (start/sit is decided before the games), scoring their real
    points."""
    total = 0.0
    act = [n for n in sorted(players) if n not in il]
    for d in season_dates(season, week):
        playing = [(n, frozenset(inputs.projections[n].positions), inputs.projections[n].effective_fppg)
                   for n in act if actuals.played(n, d) is not None]
        if not playing:
            continue
        started, _b, _a = exact_fill(playing)
        total += sum(actuals.played(n, d) for n in started)
    return total


def realised(season: Season, actuals: Actuals, inputs: av.MondayInputs, manager: str,
             move: Optional[av.Move], followup: Optional[str] = None) -> dict:
    st = inputs.managers[manager]
    out = {"pts": [], "flip": []}
    for k, w in enumerate(inputs.horizon):
        base = realised_week(season, actuals, inputs, *av.week_roster(inputs, st, None, k, None), w)
        if move is None:
            g = 0.0
        else:
            g = realised_week(season, actuals, inputs, *av.week_roster(inputs, st, move, k, followup), w) - base
        out["pts"].append(round(g, 2))
        real = season.margin(manager, w)
        flip = 0
        if real is not None and g:
            if real < 0 <= real + g:
                flip = 1
            elif real >= 0 > real + g:
                flip = -1
        out["flip"].append(flip)
    return out
