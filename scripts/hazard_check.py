#!/usr/bin/env python3
"""
hazard_check.py -- is the injury hazard charging the right number of absences?

THE GATE is the per-game miss rate: the share of rostered team games a player
misses, simulated over weeks 1-15, against the range real seasons of this
league produced over the same weeks (HISTORICAL_PLAYERLOG). An engine where
nobody is hurt sits near zero; an over-charging one sits above every season.

STARTED GAMES is printed, never gated. 2026-27 runs five bench slots and depth
absorbs absences, so it can no longer see the hazard (modules/miss_rate.py,
HANDOFF_HAZARD_CHECK_2026-10-27). It still belongs in every before/after -- it
is how two zeroed-out players were spotted.

Both are also shown like for like on the weeks already played: this season's
realized numbers (LINEUPS / PLAYERLOG) against the engine on those same weeks.

USAGE
    py scripts/hazard_check.py
    py scripts/hazard_check.py --sims 2000 --seed 20262027

EXIT CODES
    0 = the simulated miss rate is inside the range real seasons produced
    1 = it is not
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules import miss_rate as mr  # noqa: E402
from modules import simulator_betting as sb  # noqa: E402
from modules.data_loader import MANAGERS, load_all_data  # noqa: E402
from modules.projections import load_all_team_projections  # noqa: E402


def engine(data, teams, weeks, seed, sims, anchor, hazard=True):
    """(started scoring games per manager-day, simulated miss rate)."""
    orig = sb.baseline_blocks
    if not hazard:
        sb.baseline_blocks = lambda *a, **k: {}
    try:
        draws = sb.KeyedDraws(seed, sims)
        games = days = 0
        for w in weeks:
            wd = sb.schedule_week(data, w)
            r = sb.simulate_week_matrix(data, teams, wd, {}, draws, managers=MANAGERS,
                                        tag_anchor=anchor)
            games += float(np.mean([r[m]["games"].mean() for m in MANAGERS]))
            days += len(sb.get_dates_in_week(wd))
        miss = mr.simulated(data, teams, weeks, {}, draws, anchor, MANAGERS)["rate"]
    finally:
        sb.baseline_blocks = orig
    return games / days, miss


def main():
    ap = argparse.ArgumentParser(description="Check the injury hazard against reality.")
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20262027)
    args = ap.parse_args()

    data = load_all_data(PROJECT_ROOT)
    teams = load_all_team_projections(data)
    rows = data.historical_playerlog or json.loads(
        (PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").read_text(encoding="utf-8"))
    anchor = date.fromisoformat(sb.schedule_week(data, 1)["start_date"])
    lo, hi = mr.band(rows, mr.HISTORY_WEEKS)
    w1lo, w1hi = mr.band(rows, [1])
    season = range(1, 16)

    lineups = pd.read_excel(PROJECT_ROOT / "data" / "LINEUPS.xlsx") \
        if (PROJECT_ROOT / "data" / "LINEUPS.xlsx").is_file() else None
    played = sorted(int(w) for w in lineups["week"].unique()) if lineups is not None and len(lineups) else []

    print("=" * 66)
    print(f"  HAZARD CHECK -- seed {args.seed}, {args.sims} sims, no tags")
    print("=" * 66)

    on_day, on_miss = engine(data, teams, season, args.seed, args.sims, anchor)
    off_day, off_miss = engine(data, teams, season, args.seed, args.sims, anchor, hazard=False)

    print("\n  PER-GAME MISS RATE (the gate)")
    print(f"    history, every rostered team game: {mr.pooled(rows)[2]:.2%}")
    print(f"    history, weeks 1-15, range of real seasons: {lo:.2%} - {hi:.2%}")
    print(f"    engine, weeks 1-15: {on_miss:.2%}    (hazard off: {off_miss:.2%})")
    if played:
        m, g, rate = mr.realized(lineups, played)
        _, sim_played = engine(data, teams, played, args.seed, args.sims, anchor)
        print(f"    this season so far (weeks {played[0]}-{played[-1]}), realized: {rate:.2%} "
              f"({m}/{g})  |  engine, same weeks: {sim_played:.2%}  |  "
              f"history, week 1 only: {w1lo:.2%} - {w1hi:.2%}")

    history = mr.started_per_manager_day(rows)
    realized_day = None
    if played:
        log = pd.read_excel(PROJECT_ROOT / "data" / "PLAYERLOG.xlsx")
        started = log[(log["started"] == True) & (log["fantasy_points"] != 0) & log["week"].isin(played)]
        mdays = lineups[lineups["week"].isin(played)][["manager", "date"]].drop_duplicates()
        realized_day = len(started) / len(mdays) if len(mdays) else None
    print()
    for line in mr.report_started_games(history, None, on_day, off_day):
        print("  " + line.replace("engine ", "engine, weeks 1-15 "))
    if played and realized_day is not None:
        p_on, _ = engine(data, teams, played, args.seed, args.sims, anchor)
        p_off, _ = engine(data, teams, played, args.seed, args.sims, anchor, hazard=False)
        print(f"    weeks played so far: actual {realized_day:.3f} | engine {p_on:.3f} | "
              f"engine with no hazard {p_off:.3f}  (today's rosters, not the ones that played)")

    ok = lo <= on_miss <= hi
    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'} -- the simulated miss rate {on_miss:.2%} is "
          f"{'inside' if ok else 'OUTSIDE'} the {lo:.2%}-{hi:.2%} real seasons produced.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
