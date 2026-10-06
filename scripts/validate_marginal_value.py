#!/usr/bin/env python3
"""
validate_marginal_value.py -- C1 test 9: is the premise under C2 and C3 real?

C2 (personalised waivers) and C3 (the trade finder) exist because handoff
7.2 measured player value as strongly roster-relative, on a SIMULATED draft:

    median spread of one free agent's rank across the four managers   16 places
    median gap between the manager he helps most and least           337 points
    one-for-one swaps that make BOTH managers better off          48 of 1,350

The names depended on that simulated draft; the magnitudes were the claim.
This re-measures them with marginal_value on real rosters. Run it once the
real draft is in (after Oct 11), and again whenever rosters have turned over.

THRESHOLDS -- each is half the original measurement. Below one, the premise
is materially weaker than measured. That is not a footnote: stop and talk
before building C2/C3 on it. Exit code 2.

Definitions, matched to 7.2 as closely as the record allows: window
regular_season from the run's current week; an FA's value to a manager is
marginal_value of adding him (no drop, so the ranking is pure fit); rank is
his position among all free agents for that manager.

    py scripts\\validate_marginal_value.py               # live data
    py scripts\\validate_marginal_value.py --sims 200
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ORIGINAL = {"rank_spread": 16, "gap_points": 337, "mutual_gain_swaps": 48}
THRESHOLDS = {"rank_spread": 8, "gap_points": 169, "mutual_gain_swaps": 24}


def premise_stats(ctx, rosters: dict, free_agents: list) -> dict:
    """The three 7.2 magnitudes, measured with marginal_value."""
    from modules import marginal_value as mv
    managers = list(rosters)
    value = {m: {f: mv.marginal_value(ctx, m, adds=[f]).points for f in free_agents}
             for m in managers}
    rank = {m: {f: r for r, f in enumerate(sorted(free_agents, key=lambda f: -value[m][f]), 1)}
            for m in managers}
    spreads = [max(rank[m][f] for m in managers) - min(rank[m][f] for m in managers)
               for f in free_agents]
    gaps = [max(value[m][f] for m in managers) - min(value[m][f] for m in managers)
            for f in free_agents]

    mutual, total, best = 0, 0, None
    for a, b in itertools.combinations(managers, 2):
        for x, y in itertools.product(rosters[a], rosters[b]):
            ga = mv.marginal_value(ctx, a, adds=[y], drops=[x]).points
            gb = mv.marginal_value(ctx, b, adds=[x], drops=[y]).points
            total += 1
            if ga > 0 and gb > 0:
                mutual += 1
                if best is None or ga + gb > best[0]:
                    best = (round(ga + gb, 1), a, x, b, y)
    return {
        "rank_spread": statistics.median(spreads) if spreads else 0,
        "gap_points": round(statistics.median(gaps), 1) if gaps else 0.0,
        "mutual_gain_swaps": mutual, "swaps_examined": total, "best_mutual": best,
        "free_agents": len(free_agents),
    }


def verdict(stats: dict) -> list[str]:
    """Names of the measurements below threshold."""
    return [k for k, t in THRESHOLDS.items() if stats[k] < t]


def report(stats: dict) -> int:
    print(f"\n  {'measure':22} {'7.2 (simulated draft)':>22} {'now':>10} {'threshold':>10}")
    for k in THRESHOLDS:
        flag = "  <-- BELOW" if stats[k] < THRESHOLDS[k] else ""
        print(f"  {k:22} {ORIGINAL[k]:>22} {stats[k]:>10} {THRESHOLDS[k]:>10}{flag}")
    print(f"\n  ({stats['free_agents']} free agents; {stats['mutual_gain_swaps']} of "
          f"{stats['swaps_examined']} one-for-one swaps help both sides; best "
          f"{stats['best_mutual']})")
    low = verdict(stats)
    if low:
        print(f"\n  PREMISE CHECK: {', '.join(low)} below half the original "
              "measurement. Roster-relative value is weaker than C2/C3 were "
              "scoped on. Discuss before building on it.")
        return 2
    print("\n  Premise holds: value is at least half as roster-relative as measured.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--week", type=int, default=None,
                    help="current (completed) week; default from the data")
    args = ap.parse_args()

    from modules.data_loader import load_all_data, free_agents
    from modules.marginal_value import build_context
    from modules.projections import load_player_projections

    data = load_all_data(Path("."))
    rosters = data.get_current_rosters()
    if not any(rosters.values()):
        print("No rosters yet (config/ROSTERS.json is empty). Run after the draft.")
        return 1
    fas = free_agents(data.playerlist, rosters)["player_name"].tolist()
    week = args.week if args.week is not None else (data.current_week or 0)
    ctx = build_context(load_player_projections(data), rosters, data.nba_schedule,
                        data.schedule.get("weeks", []), "regular_season", week,
                        extra_players=fas, sims=args.sims)
    return report(premise_stats(ctx, rosters, fas))


if __name__ == "__main__":
    sys.exit(main())
