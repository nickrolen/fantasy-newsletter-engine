"""
marginal_value.py -- C1, the valuation primitive.

    marginal_value(ctx, manager, adds, drops) -> MVResult

Expected fantasy points a roster change adds over a named window, for one
manager. Every advice surface is a caller:

    waivers (C2)    +free agent  -drop          on my roster
    trades  (C3)    -mine +theirs, both sides    on both rosters
    keepers (C4)    my roster with and without a player
    schedule luck   (C6)

WHY ROSTER-RELATIVE
-------------------
Lineups are daily and capped at ten. A player's value to a roster is the
points he adds to its OPTIMAL DAILY FILLS: nothing on a night the roster
already fields ten better players, his full projection on a night it has a
hole he fits. Measured on full rosters, the same free agent's rank moves a
median of 16 places across the four managers (handoff 7.2).

THE ESTIMATOR
-------------
For each simulation s and each day d in the window:
  1. availability -- every player is drawn available or not (sampler below);
  2. fill -- lineup_fill.exact_fill on the available players whose NBA team
     plays on d. Exact, because MV is a DIFFERENCE of two fills and a fill
     error lands in it whole;
  3. score -- the starters' EXPECTED FPPG. Game-score noise is not sampled:
     start/sit is decided before tip-off and the noise is independent of it,
     so sampling it adds variance and no information.
MV is the mean over s of total(changed) - total(current).

COMMON RANDOM NUMBERS, KEYED
----------------------------
A player's availability on a date in simulation s is a pure function of
(seed, player, date, s): its own generator, seeded from a hash of the
first three. No shared stream, so adding or dropping one player cannot
shift anyone else's draws, and the same question twice gives exactly the
same answer.

AVAILABILITY -- one model, the simulators'
-------------------------------------------
  - INJURY_OVERRIDES out_weeks: unavailable.
  - return_date in a return week: unavailable before it.
  - otherwise per-game rate = projected_gp / max projected_gp among rostered
    players, capped at 0.98 (simulator_title_odds' reliability model);
  - in the window's first fantasy week a live GTD/O tag multiplies it by the
    betting simulator's decay curve.
It sits behind `availability()` so A2's block-absence model replaces it in
one place. Today it is still the independent coin flip handoff 7.1 calls
the wrong shape -- see RETRO_SIM_REQUIREMENTS.md section 3.

SPEED
-----
Per day, each simulation's available set is encoded as a bitmask (numpy,
vectorised over simulations); only DISTINCT masks are filled, and fills are
memoised by the set of names. Per-day results are cached by the tuple of
roster players with a game that day, so a counterfactual only pays for the
days on which an added or dropped player's team plays.

NO FIXED PATHS
--------------
Nothing here opens a file. build_context() takes projections, rosters,
schedules and statuses as arguments (RETRO_SIM_REQUIREMENTS R2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Sequence

import numpy as np

from .data_loader import PlayerIndex, CURRENT_SEASON, stage_weeks
from .lineup_fill import exact_fill
from .projections import get_injury_availability_decayed

DEFAULT_SIMS = 400
SHORTLIST_SIMS = 40
AVAILABILITY_CAP = 0.98

# Show the Cup-seeding column for a manager once his regular-season finish is
# this settled: one finishing place holds at least this probability in the
# title-odds simulation. A condition, not a week number -- it is right in a
# year somebody clinches by week 8 and in one that goes to the last night.
CUP_COLUMN_SETTLED = 0.90


# =============================================================================
# Windows
# =============================================================================

WINDOWS = ("this_week", "regular_season", "cup_seeding")


def window_weeks(window: str, current_week: int, season: str = None) -> list[int]:
    """Fantasy weeks a window covers, after `current_week` (just completed).

    this_week       the next matchup
    regular_season  through the last regular-season week -> record, $180,
                    next year's draft order
    cup_seeding     through the last week before the Cup -> total points,
                    Cup seeding, the sixth keeper
    Bounds come from league_config's season structure, never a literal.
    """
    season = season or CURRENT_SEASON
    nxt = current_week + 1
    if window == "this_week":
        return [nxt]
    if window == "regular_season":
        span = stage_weeks(season, "regular_season")
        last = span[1] if span else 0
    elif window == "cup_seeding":
        cup = stage_weeks(season, "cup")
        last = (cup[0] - 1) if cup else 0
    else:
        raise ValueError(f"unknown window {window!r}; one of {WINDOWS}")
    return list(range(nxt, last + 1))


def cup_column_live(finish_distribution: dict, managers: Iterable[str]) -> bool:
    """True when any of `managers` has a settled regular-season finish.

    finish_distribution is title-odds' {manager: {place: probability}}, in
    probabilities or percentages. Once a finish is settled the regular-
    season window no longer moves anything for that manager, and Cup
    seeding is the live question.
    """
    for m in managers:
        dist = (finish_distribution or {}).get(m) or {}
        vals = [float(v) for v in dist.values()]
        if not vals:
            continue
        scale = 100.0 if sum(vals) > 1.5 else 1.0
        if max(vals) / scale >= CUP_COLUMN_SETTLED:
            return True
    return False


# =============================================================================
# Context
# =============================================================================

@dataclass(frozen=True)
class MVPlayer:
    name: str
    team: str
    positions: frozenset
    fppg: float
    rate: float                         # per-game availability, healthy
    out_weeks: frozenset = frozenset()
    return_week: Optional[int] = None
    return_date: Optional[date] = None
    status: str = "HEALTHY"
    projected: bool = True              # False: not in PLAYERLIST


@dataclass
class MVContext:
    players: PlayerIndex                # name -> MVPlayer
    rosters: dict                       # manager -> [names]
    window: str
    weeks: list
    days: list                          # [(date, week, frozenset(teams))]
    sims: int
    seed: int
    unprojected: list = field(default_factory=list)
    _avail: dict = field(default_factory=dict, repr=False)
    _fill: dict = field(default_factory=dict, repr=False)
    _day: dict = field(default_factory=dict, repr=False)


def _week_dates(schedule_weeks: Sequence[dict]) -> dict:
    out = {}
    for w in schedule_weeks:
        d0 = date.fromisoformat(str(w["start_date"])[:10])
        d1 = date.fromisoformat(str(w["end_date"])[:10])
        out[int(w["week"])] = [d0 + timedelta(days=k) for k in range((d1 - d0).days + 1)]
    return out


def _teams_by_date(nba_schedule: dict) -> dict:
    out: dict = {}
    for g in (nba_schedule or {}).get("games", []):
        h, a = g.get("home"), g.get("away")
        if not h or not a:
            continue
        try:
            d = datetime.fromisoformat(str(g.get("date", "")).replace("Z", "+00:00")).date()
        except ValueError:
            continue
        out.setdefault(d, set()).update((h, a))
    return out


def build_context(
    projections: dict,
    rosters: dict,
    nba_schedule: dict,
    schedule_weeks: Sequence[dict],
    window: str,
    current_week: int,
    injury_statuses: Optional[dict] = None,
    extra_players: Iterable[str] = (),
    fallback_info: Optional[dict] = None,
    sims: int = DEFAULT_SIMS,
    seed: int = 20261006,
    season: str = None,
) -> MVContext:
    """Everything marginal_value needs, passed in -- no files are read.

    projections:     name -> projections.PlayerProjection (PLAYERLIST, with
                     INJURY_OVERRIDES applied by load_player_projections)
    rosters:         manager -> [names], as of the decision
    extra_players:   candidates not on a roster (free agents) to include
    fallback_info:   name -> (nba_team, positions) for rostered players
                     PLAYERLIST lacks (from LINEUPS); valued at 0.0 and
                     listed in ctx.unprojected
    """
    proj_idx = PlayerIndex(projections)
    statuses = PlayerIndex(injury_statuses or {})
    fallback = PlayerIndex(fallback_info or {})

    rostered = [n for ps in rosters.values() for n in ps]
    gps = [p.projected_gp for n in rostered
           if (p := proj_idx.get(n)) is not None and p.projected_gp > 0]
    max_gp = max(gps) if gps else None

    players, unprojected = PlayerIndex(), []
    for name in list(dict.fromkeys(list(rostered) + list(extra_players))):
        p = proj_idx.get(name)
        if p is None:
            team, pos = fallback.get(name, ("", ""))
            positions = frozenset(x.strip() for x in str(pos or "").split(",") if x.strip())
            players[name] = MVPlayer(name, str(team or ""), positions, 0.0,
                                     AVAILABILITY_CAP, projected=False)
            unprojected.append(name)
            continue
        if max_gp and p.projected_gp > 0:
            rate = min(AVAILABILITY_CAP, p.projected_gp / max_gp)
        else:
            rate = 0.0 if (max_gp and p.projected_gp <= 0) else AVAILABILITY_CAP
        fppg = p.effective_fppg if (p.effective_fppg or 0) > 0 else p.projected_fppg
        players[name] = MVPlayer(
            name=name, team=str(p.nba_team).upper(),
            positions=frozenset(p.positions or []), fppg=float(fppg or 0.0),
            rate=float(rate), out_weeks=frozenset(p.out_weeks or []),
            return_week=p.return_week,
            return_date=(date.fromisoformat(p.return_date) if p.return_date else None),
            status=str(statuses.get(name, "HEALTHY")).upper())

    weeks = window_weeks(window, current_week, season)
    by_week = _week_dates(schedule_weeks)
    teams = _teams_by_date(nba_schedule)
    days = [(d, w, frozenset(teams.get(d, ()))) for w in weeks for d in by_week.get(w, [])]
    return MVContext(players=players, rosters={m: list(v) for m, v in rosters.items()},
                     window=window, weeks=weeks, days=days, sims=sims, seed=seed,
                     unprojected=unprojected)


# =============================================================================
# Availability and fills
# =============================================================================

def availability(ctx: MVContext, p: MVPlayer, d: date, week: int) -> float:
    """Probability p plays on d if his team does. The A2 seam."""
    if week in p.out_weeks:
        return 0.0
    if p.return_date is not None and week == p.return_week and d < p.return_date:
        return 0.0
    a = p.rate
    first_week = ctx.weeks[0] if ctx.weeks else None
    if week == first_week and p.status in ("GTD", "O"):
        week_start = next(dd for dd, w, _t in ctx.days if w == week)
        a *= get_injury_availability_decayed(p.status, (d - week_start).days)
    return a


def _draws(ctx: MVContext, p: MVPlayer, d: date, week: int) -> np.ndarray:
    """Bool over simulations: is p available on d. Keyed, cached."""
    key = (p.name, d)
    hit = ctx._avail.get(key)
    if hit is not None:
        return hit
    a = availability(ctx, p, d, week)
    if a <= 0.0:
        out = np.zeros(ctx.sims, dtype=bool)
    else:
        h = hashlib.blake2b(f"{ctx.seed}|{p.name}|{d.isoformat()}".encode(),
                            digest_size=8).digest()
        rng = np.random.default_rng(int.from_bytes(h, "little"))
        out = rng.random(ctx.sims) < a
    ctx._avail[key] = out
    return out


def _fill_value(ctx: MVContext, names: tuple) -> tuple[float, int]:
    """(projected points, starters) of the optimal lineup of `names`."""
    hit = ctx._fill.get(names)
    if hit is not None:
        return hit
    ps = [ctx.players[n] for n in names]
    started, _b, _a = exact_fill([(p.name, p.positions, p.fppg) for p in ps])
    val = (sum(ctx.players[n].fppg for n in started), len(started))
    ctx._fill[names] = val
    return val


def _day_totals(ctx: MVContext, di: int, playing: tuple) -> tuple[np.ndarray, np.ndarray]:
    """Per-simulation (points, starters) on day di for these players."""
    key = (di, playing)
    hit = ctx._day.get(key)
    if hit is not None:
        return hit
    d, week, _teams = ctx.days[di]
    pts = np.zeros(ctx.sims)
    starts = np.zeros(ctx.sims)
    if playing:
        masks = np.zeros(ctx.sims, dtype=np.int64)
        for bit, n in enumerate(playing):
            masks |= _draws(ctx, ctx.players[n], d, week).astype(np.int64) << bit
        uniq, inverse = np.unique(masks, return_inverse=True)
        vals = np.empty((len(uniq), 2))
        for i, m in enumerate(uniq):
            names = tuple(n for bit, n in enumerate(playing) if (int(m) >> bit) & 1)
            vals[i] = _fill_value(ctx, names)
        pts, starts = vals[inverse, 0], vals[inverse, 1]
    ctx._day[key] = (pts, starts)
    return pts, starts


def roster_totals(ctx: MVContext, roster: Sequence[str]) -> tuple[np.ndarray, np.ndarray, dict]:
    """Per-simulation (points, starters) over the window, and points by week."""
    roster = sorted(set(n for n in roster if n in ctx.players))
    pts = np.zeros(ctx.sims)
    starts = np.zeros(ctx.sims)
    by_week: dict = {}
    for di, (_d, week, teams) in enumerate(ctx.days):
        playing = tuple(n for n in roster if ctx.players[n].team in teams)
        p, s = _day_totals(ctx, di, playing)
        pts += p
        starts += s
        by_week[week] = by_week.get(week, 0.0) + p
    return pts, starts, by_week


# =============================================================================
# The primitive
# =============================================================================

@dataclass
class MVResult:
    manager: str
    adds: tuple
    drops: tuple
    window: str
    points: float          # mean added points over the window
    se: float              # Monte Carlo standard error of `points`
    starts: float          # mean added started games
    by_week: dict          # week -> mean added points
    sims: int
    days: int
    unprojected: tuple     # players in the change valued at 0.0 (no projection)


def marginal_value(
    ctx: MVContext,
    manager: str,
    adds: Sequence[str] = (),
    drops: Sequence[str] = (),
) -> MVResult:
    """Expected points `adds`/`drops` add to `manager` over ctx's window.

    Players are matched through PlayerIndex. A drop that is not on the
    roster, or an add that is unknown to the context, raises -- a silent
    no-op would read as "worth nothing".
    """
    current = list(ctx.rosters[manager])
    on_roster = PlayerIndex({n: n for n in current})
    known = PlayerIndex({n: n for n in ctx.players})
    drop_keys, add_keys = set(), []
    for n in drops:
        if n not in on_roster:
            raise KeyError(f"{n!r} is not on {manager}'s roster")
        drop_keys.add(on_roster[n])
    for n in adds:
        if n not in known:
            raise KeyError(f"{n!r} is not in the context; pass it in extra_players")
        add_keys.append(known[n])
    changed = [n for n in current if n not in drop_keys] + add_keys

    p0, s0, w0 = roster_totals(ctx, current)
    p1, s1, w1 = roster_totals(ctx, changed)
    diff = p1 - p0
    se = float(diff.std(ddof=1) / np.sqrt(ctx.sims)) if ctx.sims > 1 else 0.0
    return MVResult(
        manager=manager, adds=tuple(add_keys), drops=tuple(sorted(drop_keys)),
        window=ctx.window, points=round(float(diff.mean()), 2), se=round(se, 2),
        starts=round(float((s1 - s0).mean()), 3),
        by_week={w: round(float((w1.get(w, 0.0) - w0.get(w, 0.0)).mean()), 2)
                 for w in sorted(set(w0) | set(w1))},
        sims=ctx.sims, days=len(ctx.days),
        unprojected=tuple(n for n in list(add_keys) + list(drop_keys)
                          if not ctx.players[n].projected))
