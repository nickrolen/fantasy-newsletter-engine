"""The hazard's check: the per-game miss rate, simulated against realized.

WHY THIS AND NOT STARTED GAMES (HANDOFF_HAZARD_CHECK_2026-10-27)
--------------------------------------------------------------
The baseline hazard's reality check used to be started scoring games per
manager-week inside [nine-season mean, last-two-season mean]. 2026-27 runs FIVE
bench slots; most historical seasons ran three (2025-26 switched midseason).
Depth absorbs absences -- a starter sits, a bench player fills the slot, the
game is still started -- so started games stopped seeing the thing it was
built to see. Per manager-DAY, so week length drops out:

                                        started scoring games / manager-day
    nine seasons                        5.566
    last two                            5.761
    best season (2023-24)               5.841
    2026-27 week 1, actual              6.708
    engine, 10-27 (42.83 a week)        6.12
    engine with NO hazard (48.6 a week) 6.94

Reality now sits 3.5% under the no-injury ceiling, so any upper edge loose
enough to pass a correct engine also passes one in which nobody is ever hurt.
No threshold restores that. So started games is REPORTED (report_started_games)
and never gates.

What the hazard models is the chance a rostered player misses a game his team
plays. Bench depth cannot mask that, and an engine with nobody hurt has a rate
near zero at any depth. That is the gate:

    historical   every rostered team game in HISTORICAL_PLAYERLOG
                 (8,609 / 42,122 = 20.44%), and per season over the weeks the
                 engine simulates -- weeks 1-15 ranged 14.6% to 23.9%
    realized     this season, from LINEUPS: every rostered player every day,
                 a team game where he scored 0.0 is a miss (the log's own
                 definition of is_injured). PLAYERLOG only holds started rows
                 (171 of week 1's 175), so it answers "started someone who sat",
                 not "unavailable"
    simulated    the same quantity from the engine: every rostered player with a
                 projection, every date his team plays, through the one
                 availability model (simulator_betting.entry_available, as
                 availability_on); a game an INJURY_OVERRIDES entry rules out is a
                 miss, as a long injury is in the log
"""
from __future__ import annotations

import collections
from datetime import date
from typing import Iterable, Optional

import numpy as np

HISTORY_WEEKS = range(1, 16)


# ---------------------------------------------------------------- history
def historical(rows: list, weeks: Optional[Iterable[int]] = None) -> dict:
    """{season: (missed, team games)} over rostered team games in `weeks`."""
    weeks = set(weeks) if weeks is not None else None
    out = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if not r["had_game"] or (weeks is not None and r["week"] not in weeks):
            continue
        cell = out[r["season_key"]]
        cell[1] += 1
        cell[0] += r["fantasy_points"] == 0
    return {s: (m, g) for s, (m, g) in sorted(out.items())}


def band(rows: list, weeks: Iterable[int] = HISTORY_WEEKS) -> tuple:
    """(lowest, highest) per-season miss rate over `weeks`: the range real
    seasons of this league actually produced. Measured, never typed in."""
    rates = [m / g for m, g in historical(rows, weeks).values() if g]
    return min(rates), max(rates)


def pooled(rows: list, weeks: Optional[Iterable[int]] = None) -> tuple:
    by = historical(rows, weeks).values()
    m, g = sum(v[0] for v in by), sum(v[1] for v in by)
    return m, g, (m / g if g else float("nan"))


# ---------------------------------------------------------------- this season
def realized(lineups, weeks: Optional[Iterable[int]] = None) -> tuple:
    """(missed, team games, rate) this season from LINEUPS. A team game is a
    row with an NBA opponent; a miss is one where he scored 0.0."""
    if lineups is None or len(lineups) == 0:
        return 0, 0, float("nan")
    df = lineups
    if weeks is not None:
        df = df[df["week"].isin(list(weeks))]
    opp = df["nba_opponent"].astype(str).str.strip()
    played = df[df["nba_opponent"].notna() & (opp != "") & (opp.str.lower() != "nan")]
    fp = played["fantasy_points"].astype(float)
    missed, games = int((fp == 0).sum()), int(len(played))
    return missed, games, (missed / games if games else float("nan"))


# ---------------------------------------------------------------- the engine
def simulated(data, team_projections, weeks, injury_statuses, draws,
              tag_anchor: Optional[date] = None, managers=None) -> dict:
    """The engine's per-game miss rate over `weeks`, from the same draws a
    week matrix reads. {"games", "missed" (expected), "rate", "by_manager",
    "unprojected_games"} -- rate over rostered players with a projection."""
    from modules import simulator_betting as sb
    managers = list(managers or team_projections.keys())
    statuses = injury_statuses or {}
    blocks = sb.tag_blocks(data, team_projections, statuses, draws, tag_anchor)
    base = sb.baseline_blocks(data, team_projections, draws,
                              sb.hazard_anchor(data, tag_anchor), managers,
                              injury_statuses=statuses or None)
    games = missed = unprojected = 0
    by = {m: [0.0, 0] for m in managers}
    for w in weeks:
        wd = sb.schedule_week(data, w)
        plan = sb._week_plan(data, team_projections, wd, managers)
        for m in managers:
            planned = {(d, e[8]): e for d, es in plan[m] for e in es}
            for d in sb.get_dates_in_week(wd):
                playing = sb._playing_teams(data, d)
                for key, p in team_projections[m].players.items():
                    if p.nba_team.upper() not in playing:
                        continue
                    if (p.projected_fppg or 0) <= 0:
                        unprojected += 1
                        continue
                    e = planned.get((d, key))
                    if e is None:                     # an override rules him out
                        miss = 1.0
                    else:
                        u = draws.uniforms("avail", key, d) if e[4] is not None else None
                        avail = sb.entry_available(draws.n, e, d, u, blocks.get(key), base.get(key))
                        miss = 1.0 - float(avail.mean())
                    games += 1
                    missed += miss
                    by[m][0] += miss
                    by[m][1] += 1
    return {"games": games, "missed": missed, "rate": missed / games if games else float("nan"),
            "by_manager": {m: (v[0] / v[1] if v[1] else float("nan")) for m, v in by.items()},
            "unprojected_games": unprojected}


# ---------------------------------------------------------------- reporting
def started_per_manager_day(rows: list) -> dict:
    """{season: started scoring games per manager-day} from the log, plus
    'nine seasons' and 'last two'. Manager-days are the (manager, date)
    pairs the log covers."""
    started = collections.Counter()
    days = collections.defaultdict(set)
    for r in rows:
        days[r["season_key"]].add((r["manager"], r["date"]))
        if r["started"] and r["had_game"] and r["fantasy_points"] != 0:
            started[r["season_key"]] += 1
    seasons = sorted(days)
    out = {s: started[s] / len(days[s]) for s in seasons}
    out["nine seasons"] = sum(started.values()) / sum(len(v) for v in days.values())
    last2 = seasons[-2:]
    out["last two"] = sum(started[s] for s in last2) / sum(len(days[s]) for s in last2)
    return out


def report_started_games(history: dict, realized_per_day: Optional[float],
                         engine_per_day: float, ceiling_per_day: Optional[float] = None) -> list:
    """Lines for a before/after. Reported, never a gate -- see the module docstring."""
    best = max((v, s) for s, v in history.items() if s not in ("nine seasons", "last two"))
    lines = ["started scoring games per manager-day (REPORTED, not a gate: five bench "
             "slots absorb absences, so this cannot see the hazard)",
             f"  nine seasons {history['nine seasons']:.3f} | last two {history['last two']:.3f} | "
             f"best season ({best[1]}) {best[0]:.3f}"]
    if realized_per_day is not None:
        lines.append(f"  this season, actual {realized_per_day:.3f}")
    lines.append(f"  engine {engine_per_day:.3f}"
                 + (f" | engine with no hazard {ceiling_per_day:.3f}" if ceiling_per_day else ""))
    return lines
