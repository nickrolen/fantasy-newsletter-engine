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

from modules.data_loader import (LEAGUE_STRUCTURE, MANAGERS, CURRENT_SEASON,  # noqa: E402
                                 TOTAL_ROUNDS, keepers_for, live_picks_for,
                                 regular_season_weeks_for)

RECORDS = PROJECT_ROOT / "config" / "RECORDS.json"
SCHEDULE = PROJECT_ROOT / "config" / "SCHEDULE.json"
TRADES = PROJECT_ROOT / "config" / "TRADES.json"
ARCHIVE = PROJECT_ROOT / "archive"


def resolve_season_files(records_path, schedule_path):
    """Use the live files, or fall back to the most recent archived season.

    The draft order is set AFTER the season reset, which clears RECORDS.json.
    The standings that determine the order therefore live in
    archive/<season>/config/ by the time anyone needs them.
    """
    try:
        live = json.loads(records_path.read_text(encoding="utf-8"))
        if live.get("weekly_scores"):
            return records_path, schedule_path, None
    except (OSError, json.JSONDecodeError):
        pass

    if not ARCHIVE.is_dir():
        return records_path, schedule_path, None
    seasons = sorted((d for d in ARCHIVE.iterdir() if d.is_dir()), reverse=True)
    for d in seasons:
        ar, asch = d / "config" / "RECORDS.json", d / "config" / "SCHEDULE.json"
        if ar.is_file() and asch.is_file():
            try:
                if json.loads(ar.read_text(encoding="utf-8")).get("weekly_scores"):
                    return ar, asch, d.name
            except (OSError, json.JSONDecodeError):
                continue
    return records_path, schedule_path, None


def _next_season(season):
    """"2026-27" -> "2027-28". None if it cannot be parsed."""
    import re
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(season or ""))
    if not match:
        return None
    start = int(match.group(1)) + 1
    return f"{start}-{(start + 1) % 100:02d}"


def regular_season_results(records, schedule, season=None):
    """(wins, losses, points, h2h) per manager over the regular season only.

    The boundary comes from the schedule file when it has one, and otherwise
    from that season's entry in league_config. The old fallback here read
    total_draft_rounds -- a ROUND count standing in for a WEEK count, which
    happened to be 21 once and is 9 now.
    """
    reg_weeks = int(schedule.get("regular_season_weeks")
                    or regular_season_weeks_for(season or CURRENT_SEASON))
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
                        help="force a uniform live-round count for every manager "
                             "(default: derived per manager from keeper counts)")
    parser.add_argument("--season", default=None,
                        help="season being drafted FOR (default: the one after "
                             "the season the standings come from)")
    args = parser.parse_args()

    for p in (RECORDS, SCHEDULE, TRADES):
        if not p.exists():
            print(f"ERROR: missing {p.name}")
            return 1

    rec_path, sched_path, from_archive = resolve_season_files(RECORDS, SCHEDULE)
    records = json.loads(rec_path.read_text(encoding="utf-8"))
    schedule = json.loads(sched_path.read_text(encoding="utf-8"))
    trades = json.loads(TRADES.read_text(encoding="utf-8"))

    completed_season = from_archive or CURRENT_SEASON
    upcoming_season = args.season or _next_season(completed_season) or CURRENT_SEASON

    wl, pts, h2h, reg_weeks = regular_season_results(records, schedule,
                                                     completed_season)
    if not wl:
        print("ERROR: no regular-season results found in either config/ or archive/.")
        print("       The season reset clears RECORDS.json; the standings that set")
        print("       the draft order live in archive/<season>/config/RECORDS.json.")
        return 1
    standings, notes = rank_managers(wl, pts, h2h)
    slots = list(reversed(standings))          # worst picks first

    # Live picks are NOT the same for everyone from 2027-28 on: the previous
    # season's Cup winner keeps a sixth player and so drafts one round fewer.
    # One round of the board therefore has three picks in it, not four, and a
    # single `rounds` number cannot describe that.
    if args.rounds:
        expected = {m: int(args.rounds) for m in MANAGERS}
    else:
        expected = live_picks_for(upcoming_season)
    rounds = max(expected.values())
    keeper_counts = keepers_for(upcoming_season)
    ownership_all = trades.get("draft_pick_ownership", {})
    year = args.year or sorted(k for k in ownership_all if k.isdigit())[0]
    owners = {k: v for k, v in ownership_all.get(year, {}).items()
              if not k.startswith("_")}

    print("=" * 68)
    print(f"  DRAFT ORDER -- {year}")
    print("=" * 68)
    if from_archive:
        print(f"\n  Standings read from archive/{from_archive}/ "
              f"(the live RECORDS.json was cleared by the season reset).")
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

    if len(set(expected.values())) > 1:
        print(f"\n  Keepers for {upcoming_season} are NOT uniform:")
        for m in slots:
            print(f"    {m:8} keeps {keeper_counts[m]} "
                  f"(rounds {expected[m] + 1}-{TOTAL_ROUNDS}), "
                  f"drafts rounds 1-{expected[m]}")

    print(f"\n  PICK-BY-PICK, rounds 1-{rounds}:\n")
    n = 0
    tally = defaultdict(int)
    for rnd in range(1, rounds + 1):
        cells = []
        for orig in slots:
            # A manager whose keepers start at this round has no live pick in
            # it. The pick does not move to anyone else -- the round is simply
            # short.
            if rnd > expected[orig]:
                cells.append(f"     (keeper: {orig})")
                continue
            n += 1
            owner = owners.get(f"{rnd}_{orig}", orig)
            tally[owner] += 1
            mark = "" if owner == orig else f" <-{orig}"
            cells.append(f"{n:>3}. {owner}{mark}")
        print(f"    R{rnd:<2} " + " | ".join(f"{c:<18}" for c in cells))

    print(f"\n  Picks per manager across rounds 1-{rounds}:")
    uneven = []
    for m in sorted(tally, key=lambda x: -tally[x]):
        diff = tally[m] - expected[m]
        if diff:
            uneven.append((m, diff))
        print(f"    {m:8} {tally[m]:>2}"
              + (f"  ({diff:+d} vs {expected[m]})" if diff else "  (even)"))

    total = sum(tally.values())
    total_expected = sum(expected.values())
    print(f"\n  Total picks: {total} (expected {total_expected})"
          + ("  OK" if total == total_expected else "  MISMATCH"))

    if uneven:
        roster = int(LEAGUE_STRUCTURE.get("roster_size", 0))
        il = int(LEAGUE_STRUCTURE.get("il_slots", 0))
        print("\n  " + "!" * 62)
        print("  UNEVEN PICK COUNTS -- almost certainly a gap in the trade log.")
        print(f"  The roster has {roster} spots and {il} IL, so {TOTAL_ROUNDS} are filled")
        print(f"  by keepers plus the draft. For {upcoming_season} that means:")
        for m in slots:
            print(f"    {m:8} {keeper_counts[m]} keepers -> must draft {expected[m]}")
        print("  These do not:")
        for m, d in uneven:
            print(f"    {m}: {tally[m]} ({d:+d})")
        print()
        print("  Check TRADES.json for a trade where the two sides send a different")
        print("  number of picks for the SAME draft year. A pick is probably missing")
        print("  from sent_picks rather than the trade having been genuinely lopsided.")
        print("  " + "!" * 62)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
