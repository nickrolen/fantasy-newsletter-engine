"""
hub_v2/team_value.py -- ENGINE SIDE of the roster table's Value group (4c2,
claude/HANDOFF_4C2_TEAMS_MATCHUPS_2026-11-18.md s.1): Team value and Title
delta, per rostered player, built inside hub_state.build.

TEAM VALUE: the points a player adds to his manager's optimal daily lineups
over the next two fantasy weeks, against the best available free agent:

    TV(P) = total(R) - max_F total(R - P + F)

  R        the manager's ACTIVE roster now (his IL slots are not in it: an IL
           occupant gets no Team value, his row says why);
  total    marginal_value.roster_totals: per day, the exact daily fill of the
           players who will be available (the absence model: tags anchored at
           their fetch day, injury entries, the baseline hazard), the starters'
           expected FPPG, summed over the window, averaged over SIMS keyed
           simulations (common random numbers: an unchanged player's draws
           never move);
  window   advice's horizon (advice_v2.horizon_for): before Monday's window
           closes, this week and next; after it, next week and the week after
           (a move made now joins at the next window, rule 7). The two weeks
           advice prices a move over, so the two speak of the same weeks;
  F        the free agents (the hub's own pool: PLAYERLIST free agents minus
           the chat's claims, plus the chat's drops), screened to the
           SHORTLIST best by projected FPPG x his team's games in the window,
           then each tried exactly in P's place; the best one is the
           replacement.

  Positive: he is worth more to this lineup than any free agent would be.

TITLE DELTA: TV x the causal price of a point (injured_drop.point_value_parts,
the stakes file's near-tie leverage x the margin density: the one price advice
uses), as title-odds POINTS of the phase's top prize (the regular-season title
through week 15, the championship after, as advice shows it). One price per
manager, the mean of the window's two weekly prices, so TITLE DELTA HAS TEAM
VALUE'S SIGN BY CONSTRUCTION (a price below zero RAISES). This is the
linearised twin of advice's horizon term for the move "drop him, add the best
free agent": advice prices that move's win-chance change x the leverage;
d(win) ~ density x d(points) for a small change, so the two agree to first
order, and exactly in sign.

RAISES (TeamValueError) on a missing input. A missing stakes file (the
bootstrap) is not raised: Title delta then shows a dash and says why.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Dict, List, Optional

SIMS = 48            # advice's screen sims (advice_v2.Settings.screen_sims): the same precision
SEED = 20261118
SHORTLIST = 8        # free agents tried in each player's place


class TeamValueError(RuntimeError):
    """An input Team value needs is missing or inconsistent; named."""


def horizon(now: datetime, week: int, wk_dates: dict, nba_schedule) -> tuple:
    """(kind, (w1, w2 or None)) -- advice's horizon at `now`."""
    from .. import price_lock
    from ..advice_v2 import horizon_for
    wk = {int(w): list(v) for w, v in wk_dates.items()}
    close = price_lock.window_close(wk[int(week)][0], nba_schedule)
    hz = horizon_for(now, int(week), wk, close)
    if hz is None:
        return None, ()
    return hz.kind, tuple(w for w in hz.weeks if w is not None)


def compute(*, data, now: datetime, week: int, wk_dates: dict, active: Dict[str, List[str]],
            pool: List[str], tag_row: dict, tags: dict, sims: int = SIMS, seed: int = SEED,
            shortlist: int = SHORTLIST, fa: Optional[List[str]] = None) -> dict:
    """{"weeks": [w...], "kind", "seconds", "sims", "values": {manager: {name:
    {"pts", "by_week": {w: pts}, "repl"}}}} or, with no window left this
    season, {"weeks": [], ...} and no values. tags: the hub's rostered tags
    (tag_records.hub_tags over every rostered player, IL slots included).
    fa (5e, "Value to you"): free agents to price for EVERY roster, into
    "fa_values" {manager: {name: {"pts", "by_week", "drop"}}}: the points he
    adds to that manager's best daily lineups over the same window, swapped
    for the active player whose loss costs least (no drop when the active
    roster has an open spot), the mirror of Team value; "fa_error" says why
    when it fails (soft: Team value stands), "fa_seconds" what it cost."""
    from .. import marginal_value as mv
    from ..hub_state import free_agent_tags
    from ..projections import load_player_projections, populate_actual_stats
    t0 = time.perf_counter()
    kind, weeks = horizon(now, week, wk_dates, data.nba_schedule)
    if not weeks:
        return {"weeks": [], "kind": None, "seconds": 0.0, "sims": sims, "values": {}, "fa_values": {},
                "fa_error": None, "fa_seconds": 0.0}
    projs = load_player_projections(data)
    populate_actual_stats(projs, data)
    rostered = [n for v in active.values() for n in v]
    missing = [n for n in rostered if n not in projs]
    if missing:
        raise TeamValueError(f"no projection for {', '.join(missing)} (data/PLAYERLIST.xlsx): no Team value")
    pool = [n for n in pool if n in projs and n not in set(rostered)]
    statuses = {n: t for n, t in tags.items() if n in set(rostered)}   # hub_tags: the hub's own
    statuses.update({n: t for n, t in free_agent_tags(tag_row, pool).items() if t not in (None, "HEALTHY")})
    anchor = date.fromisoformat(str(tag_row["league_day"])[:10])
    names = rostered + pool
    ctx = mv.build_context({n: projs[n] for n in names}, {m: list(v) for m, v in active.items()},
                           data.nba_schedule, data.schedule["weeks"], "this_week", weeks[0] - 1,
                           injury_statuses=statuses, extra_players=pool,
                           durability_prior=getattr(data, "durability_prior", None), sims=sims, seed=seed,
                           tag_anchor=anchor)
    by_week = mv._week_dates(data.schedule["weeks"])
    teams = mv._teams_by_date(data.nba_schedule)
    ctx.weeks = list(weeks)
    ctx.days = [(d, w, frozenset(teams.get(d, ()))) for w in weeks for d in by_week[w]]
    if anchor > ctx.days[0][0]:
        raise TeamValueError(f"the tags' fetch day {anchor} is after the window's first day {ctx.days[0][0]}")

    # the shortlist: projected FPPG x his team's games in the window
    games = {}
    for d, _w, ts in ctx.days:
        for t in ts:
            games[str(t).upper()] = games.get(str(t).upper(), 0) + 1

    def screen(n):
        p = ctx.players[n]
        return p.fppg * games.get(p.team, 0)
    short = sorted(pool, key=lambda n: (-screen(n), n))[:shortlist]
    if not short:
        raise TeamValueError("no free agent with a projection: Team value has nothing to compare against")

    def tot(roster):
        pts, _s, bw = mv.roster_totals(ctx, list(roster))
        return float(pts.mean()), {w: float(bw.get(w, 0.0).mean()) if hasattr(bw.get(w, 0.0), "mean")
                                   else float(bw.get(w, 0.0)) for w in weeks}

    values, bases = {}, {}
    for m, R in active.items():
        base, base_w = tot(R)
        bases[m] = (base, base_w)
        out = {}
        for n in R:
            rest = [x for x in R if x != n]
            best = None
            for f in short:
                v, vw = tot(rest + [f])
                if best is None or v > best[0] or (v == best[0] and f < best[2]):
                    best = (v, vw, f)
            out[n] = {"pts": base - best[0], "by_week": {w: base_w[w] - best[1][w] for w in weeks},
                      "repl": best[2]}
        values[m] = out
    secs = round(time.perf_counter() - t0, 2)
    fa_values, fa_error, t1 = {}, None, time.perf_counter()
    if fa:
        try:
            fa_values = _fa_values(ctx, tot, active, bases, [n for n in fa if n not in set(rostered)], weeks)
        except Exception as e:                       # noqa: BLE001 -- "Value to you" is soft (5e)
            fa_error = f"{type(e).__name__}: {e}".splitlines()[0][:300]
    mv.release_caches(ctx)
    return {"weeks": list(weeks), "kind": kind, "seconds": secs, "sims": sims, "values": values,
            "fa_values": fa_values, "fa_error": fa_error, "fa_seconds": round(time.perf_counter() - t1, 2)}


def _fa_values(ctx, tot, active: Dict[str, List[str]], bases: dict, fa: List[str], weeks) -> dict:
    """5e: each free agent's value to each roster (compute's docstring)."""
    from ..data_loader import LEAGUE_STRUCTURE
    spots = int(LEAGUE_STRUCTURE["starters"]) + int(LEAGUE_STRUCTURE["bench"])
    miss = [n for n in fa if n not in ctx.players]
    if miss:
        raise TeamValueError(f"no projection for the free agents {', '.join(miss)}: no Value to you")
    out = {}
    for m, R in active.items():
        base, base_w = bases[m]
        drops = list(R) + ([None] if len(R) < spots else [])
        vals = {}
        for f in fa:
            best = None
            for p in drops:
                v, vw = tot([x for x in R if x != p] + [f])
                if best is None or v > best[0] or (v == best[0] and str(p) < str(best[2])):
                    best = (v, vw, p)
            vals[f] = {"pts": best[0] - base, "by_week": {w: best[1][w] - base_w[w] for w in weeks},
                       "drop": best[2]}
        out[m] = vals
    return out


def title_prices(base, managers, weeks: List[int]) -> tuple:
    """({manager: title-odds points per point}, phase, note): one price per
    manager, the mean of the window's weekly prices of the phase's top prize
    (injured_drop.point_value_parts / its weight, x 100). ({}, phase, why)
    when the stakes file cannot be used (the bootstrap). A negative price
    RAISES: Title delta must carry Team value's sign."""
    from .. import drop_inputs as di, injured_drop
    from ..data_loader import CURRENT_SEASON, regular_season_weeks_for
    from ..simulator_playoff_odds import bracket_weeks
    last_reg = int(regular_season_weeks_for(CURRENT_SEASON))
    phase = "title" if weeks and int(weeks[0]) <= last_reg else "champion"
    blob, note = di.read_stakes(base)
    if blob is None:
        return {}, phase, note
    cfg = injured_drop.from_rules()
    weight = cfg.rs_weight if phase == "title" else cfg.playoff_weight
    if not weight:
        raise TeamValueError(f"injured_drop's {phase} weight is 0: no title-odds price")
    out = {}
    for m in managers:
        ts = di.team_stakes(blob, m, int(weeks[0]), last_regular=last_reg, bracket=bracket_weeks(),
                            path=str(di.stakes_path(base)))
        ps = []
        for w in weeks:
            ws = ts.weeks.get(int(w))
            if ws is None:
                raise TeamValueError(f"the stakes file has no week {w} for {m}")
            rs, po = injured_drop.point_value_parts(ws, cfg)
            ps.append((rs if phase == "title" else po) / weight)
        p = 100.0 * sum(ps) / len(ps)
        if p < 0:
            raise TeamValueError(f"{m}'s price of a point is negative ({p:.6f}): Title delta would "
                                 "contradict Team value")
        out[m] = p
    return out, phase, None
