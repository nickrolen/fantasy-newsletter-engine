#!/usr/bin/env python3
"""
build_draft_order.py -- Produce the pick-by-pick draft order, traded picks
included.

WHY
---
Two things have to be right and neither is obvious by eye.

1. SLOT ORDER is the reverse of the REGULAR-season standings -- not Yahoo's
   final rank, which folds in playoff results. Verified against 2025-26: Yahoo
   ranked Garrett 3rd and Benton 4th, but the regular season had Garrett 5-16
   and Benton 6-15, and Garrett picked first. The draft is linear, not a snake:
   the same slot order repeats every round, confirmed by the keeper rounds.

2. TIES break on head-to-head over the regular season only, then total points.
   This matters: the stored h2h_season in RECORDS.json includes playoff
   meetings, which can turn a 4-3 series into a 4-4 tie and hand the slot to
   the wrong manager. This script recomputes head-to-head from SCHEDULE.json
   and weekly scores, bounded to the regular season, rather than trusting it.

Then TRADES.json draft_pick_ownership is applied. Its format is
"Round_OriginalOwner": "CurrentOwner"; anything unlisted stays with its
original owner.

USAGE
    py scripts/build_draft_order.py
    py scripts/build_draft_order.py --year 2026
    py scripts/build_draft_order.py --rounds 9

EXIT CODES
    0 = order produced
    1 = could not build it
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import LEAGUE_STRUCTURE, MANAGERS  # noqa: E402

RECORDS = PROJECT_ROOT / "config" / "RECORDS.json"
SCHEDULE = PROJECT_ROOT / "config" / "SCHEDULE.json"
TRADES = PROJECT_ROOT / "config" / "TRADES.json"


def regular_season_results(records, schedule):
    """(wins, losses, points, h2h) per manager over the regular season only."""
    reg_weeks = int(schedule.get("regular_season_weeks")
                    or LEAGUE_STRUCTURE.get("total_draft_rounds", 21))
    scores = {}
    for mgr, rows in records.get("weekly_scores", {}).items():
        for row in rows:
            scores.setdefault(int(row["week"]), {})[mgr] = float(row["score"])

    wl = defaultdict(lambda: [0, 0])
    pts = defaultdict(float)
    h2h = defaultdict(lambda: defaultdict(int))
    for wk in schedule.get("weeks", []):
        w = int(wk["week"])
        if w > reg_weeks:
            continue
        for mu in wk.get("matchups", []):
            a, b = mu["manager_a"], mu["manager_b"]
            sa, sb = scores.get(w, {}).get(a), scores.get(w, {}).get(b)
            if sa is None or sb is None:
                continue
            win, lose = (a, b) if sa > sb else (b, a)
            wl[win][0] += 1
            wl[lose][1] += 1
            h2h[win][lose] += 1
    for w, per in scores.items():
        if w > reg_weeks:
            continue
        for mgr, s in per.items():
            pts[mgr] += s
    return wl, pts, h2h, reg_weeks


def rank_managers(wl, pts, h2h):
    """Best-first. Ties: head-to-head, then total points."""
    mgrs = [m for m in MANAGERS if m in wl]

    def sort_key(m):
        return (-wl[m][0], -pts[m])

    ordered = sorted(mgrs, key=sort_key)
    notes = []
    # Resolve two-way ties on identical W-L with head-to-head.
    i = 0
    while i < len(ordered) - 1:
        a, b = ordered[i], ordered[i + 1]
        if wl[a][0] == wl[b][0] and wl[a][1] == wl[b][1]:
            aw, bw = h2h[a][b], h2h[b][a]
            if aw != bw:
                winner = a if aw > bw else b
                if winner == b:
                    ordered[i], ordered[i + 1] = b, a
                notes.append(f"{a} and {b} tied at {wl[a][0]}-{wl[a][1]}; "
                             f"head-to-head {max(aw,bw)}-{min(aw,bw)} to {winner}")
            else:
                notes.append(f"{a} and {b} tied at {wl[a][0]}-{wl[a][1]}; "
                             f"head-to-head split {aw}-{bw}, broken on total points")
        i += 1
    return ordered, notes


def main():
    parser = argparse.ArgumentParser(description="Build the draft order.")
    parser.add_argument("--year", default=None,
                        help="draft_pick_ownership year key (default: next calendar year of the season)")
    parser.add_argument("--rounds", type=int, default=None,
                        help=f"drafted rounds (default {LEAGUE_STRUCTURE.get('total_draft_rounds')})")
    args = parser.parse_args()

    for p in (RECORDS, SCHEDULE, TRADES):
        if not p.exists():
            print(f"ERROR: missing {p.name}")
            return 1

    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    schedule = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    trades = json.loads(TRADES.read_text(encoding="utf-8"))

    wl, pts, h2h, reg_weeks = regular_season_results(records, schedule)
    if not wl:
        print("ERROR: no regular-season results found.")
        return 1
    standings, notes = rank_managers(wl, pts, h2h)
    slots = list(reversed(standings))          # worst picks first

    rounds = args.rounds or int(LEAGUE_STRUCTURE.get("total_draft_rounds", 9))
    ownership_all = trades.get("draft_pick_ownership", {})
    year = args.year or sorted(k for k in ownership_all if k.isdigit())[0]
    owners = {k: v for k, v in ownership_all.get(year, {}).items()
              if not k.startswith("_")}

    print("=" * 68)
    print(f"  DRAFT ORDER -- {year}")
    print("=" * 68)
    print(f"\n  Regular-season standings (weeks 1-{reg_weeks}):")
    for i, m in enumerate(standings, 1):
        print(f"    {i}. {m:8} {wl[m][0]}-{wl[m][1]}   {pts[m]:>10,.2f} pts")
    for n in notes:
        print(f"    tiebreak: {n}")

    print(f"\n  Slot order (reverse standings, linear every round):")
    for i, m in enumerate(slots, 1):
        print(f"    slot {i}: {m}")

    if owners:
        print(f"\n  Traded picks for {year} ({len(owners)}):")
        for k in sorted(owners, key=lambda x: (int(x.split('_')[0]), x)):
            rnd, orig = k.split("_", 1)
            print(f"    R{rnd} {orig}'s pick -> {owners[k]}")

    print(f"\n  PICK-BY-PICK, rounds 1-{rounds}:\n")
    n = 0
    tally = defaultdict(int)
    for rnd in range(1, rounds + 1):
        cells = []
        for orig in slots:
            n += 1
            owner = owners.get(f"{rnd}_{orig}", orig)
            tally[owner] += 1
            mark = "" if owner == orig else f" <-{orig}"
            cells.append(f"{n:>3}. {owner}{mark}")
        print(f"    R{rnd:<2} " + " | ".join(f"{c:<18}" for c in cells))

    print(f"\n  Picks per manager across rounds 1-{rounds}:")
    for m in sorted(tally, key=lambda x: -tally[x]):
        base = rounds
        diff = tally[m] - base
        print(f"    {m:8} {tally[m]:>2}"
              + (f"  ({diff:+d} vs {base})" if diff else "  (even)"))
    total = sum(tally.values())
    print(f"\n  Total picks: {total} (expected {rounds * len(slots)})"
          + ("  OK" if total == rounds * len(slots) else "  MISMATCH"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
