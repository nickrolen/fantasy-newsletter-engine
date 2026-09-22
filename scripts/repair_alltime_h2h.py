#!/usr/bin/env python3
"""
repair_alltime_h2h.py -- Rebuild all_time.h2h AND manager_careers from the
matchup record, regular season only.

WHY
---
records_tracker documents all-time head-to-head as regular season only, to
match season H2H and get_manager_record(). The stored values do not obey that.
Tested both ways against all nine Yahoo seasons, the stored numbers match a
computation that INCLUDES playoff meetings, 6 pairs out of 6, and match the
regular-season-only computation 0 out of 6.

The guard in update_h2h_records was added after the fact -- its own docstring
says "Previously, playoff matchups inflated the season series" -- but the
already-accumulated numbers were never rebuilt. So the code is right and the
data is wrong.

Two things had to be settled before this could be done correctly:

  * the boundary is per-season, not week 21. The bracket is always the last
    two fantasy weeks, and season lengths vary because Yahoo stretches any
    week containing the All-Star break to 14 days. 2020-21's bracket was
    weeks 17-18, 2021-22's was 21-22, and 2019-20 had none at all.
  * the current season lives in RECORDS.json weekly_scores + SCHEDULE.json,
    not in all_matchups, so it has to be folded in separately.

Both are now handled: cutoffs come from league_config season_structure.

manager_careers has the SAME bug, found later: its docstring in
records_tracker says "Total wins/losses (REGULAR SEASON ONLY)" and the guard
is in the code, but the stored totals were accumulated before that guard
existed and were never rebuilt. Checked: every manager's stored record is
exactly their regular-season record plus their postseason record, across all
eight bracket seasons -- Nick 120-77 stored, 113-68 regular, 7-9 postseason.
Career win %, which the newsletter prints, is computed from those totals.

WHAT CHANGES
------------
all_time.h2h, and all_time.manager_careers total_wins / total_losses /
win_pct / games_played. Every other key in RECORDS.json -- including
total_points_scored, titles, playoff_titles and franchise_player -- is left
untouched.

NOT CHANGED, deliberately: `titles` and `playoff_titles`. LEAGUEHISTORY.xlsx
is the source of truth for those and it includes two pre-Yahoo seasons this
script has no data for.

This visibly changes the record book -- the newsletter's all-time series lines
will read differently. Dry-run first and look at the diff.

USAGE
    py scripts/repair_alltime_h2h.py
    py scripts/repair_alltime_h2h.py --execute
    py scripts/repair_alltime_h2h.py --execute --h2h-only
    py scripts/repair_alltime_h2h.py --execute --careers-only
"""

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import is_regular_season_week  # noqa: E402

RECORDS = PROJECT_ROOT / "config" / "RECORDS.json"
SCHEDULE = PROJECT_ROOT / "config" / "SCHEDULE.json"
ALL_MATCHUPS = PROJECT_ROOT / "data" / "historical" / "all_matchups.json"


def pair_key(a, b):
    return "_vs_".join(sorted([a, b]))


def collect_games(records, schedule, matchups):
    """Every completed matchup as (season, week, winner, loser)."""
    games = []
    for r in matchups:
        w, l = r.get("winner"), r.get("loser")
        if w and l:
            games.append((r["season"], int(r["week"]), w, l))

    seen = {(s, w) for s, w, _, _ in games}
    season = schedule.get("season_year", "")
    # Normalise "2025-2026" -> "2025-26"
    if "-" in season and len(season.split("-")[1]) == 4:
        a, b = season.split("-")
        season = f"{a}-{b[-2:]}"

    scores = {}
    for mgr, rows in records.get("weekly_scores", {}).items():
        for row in rows:
            scores.setdefault(int(row["week"]), {})[mgr] = float(row["score"])
    for wk in schedule.get("weeks", []):
        w = int(wk["week"])
        if (season, w) in seen:
            continue
        for mu in wk.get("matchups", []):
            a, b = mu["manager_a"], mu["manager_b"]
            sa, sb = scores.get(w, {}).get(a), scores.get(w, {}).get(b)
            if sa is None or sb is None:
                continue
            games.append((season, w, a if sa > sb else b, b if sa > sb else a))
    return games


def build(games):
    out = defaultdict(lambda: defaultdict(int))
    kept = dropped = 0
    for season, week, w, l in games:
        if not is_regular_season_week(season, week):
            dropped += 1
            continue
        kept += 1
        k = pair_key(w, l)
        out[k][w.lower()] += 1
        out[k].setdefault(l.lower(), 0)
    return {k: dict(sorted(v.items())) for k, v in out.items()}, kept, dropped


def build_careers(games):
    """{manager: [wins, losses]} over regular-season games only."""
    out = defaultdict(lambda: [0, 0])
    for season, week, w, l in games:
        if not is_regular_season_week(season, week):
            continue
        out[w][0] += 1
        out[l][1] += 1
    return {m: v for m, v in sorted(out.items())}


def main():
    ap = argparse.ArgumentParser(description="Rebuild all_time.h2h, regular season only.")
    ap.add_argument("--execute", action="store_true", help="write (default: dry run)")
    ap.add_argument("--h2h-only", action="store_true",
                    help="rebuild all_time.h2h and leave manager_careers alone")
    ap.add_argument("--careers-only", action="store_true",
                    help="rebuild manager_careers and leave all_time.h2h alone")
    args = ap.parse_args()

    for p in (RECORDS, SCHEDULE, ALL_MATCHUPS):
        if not p.exists():
            print(f"ERROR: missing {p}")
            return 1

    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    schedule = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    matchups = json.loads(ALL_MATCHUPS.read_text(encoding="utf-8"))

    games = collect_games(records, schedule, matchups)
    correct, kept, dropped = build(games)
    stored = {k: {kk.lower(): vv for kk, vv in v.items()}
              for k, v in records.get("all_time", {}).get("h2h", {}).items()}

    seasons = sorted({s for s, _, _, _ in games})
    print("=" * 70)
    print("  REPAIR all_time.h2h -- regular season only, per-season cutoffs")
    print("=" * 70)
    print(f"\n  Seasons covered: {len(seasons)}  ({seasons[0]} .. {seasons[-1]})")
    print(f"  Matchups: {kept} regular season, {dropped} playoff games excluded\n")

    print(f"  {'pair':24} {'stored':>22} {'corrected':>22}  {'removed':>8}")
    changed = 0
    for k in sorted(set(stored) | set(correct)):
        s = stored.get(k, {}); c = correct.get(k, {})
        if s != c:
            changed += 1
        print(f"  {k:24} {str(s):>22} {str(c):>22}  {sum(s.values())-sum(c.values()):>8}")

    careers_correct = build_careers(games)
    stored_careers = records.get("all_time", {}).get("manager_careers", {})
    careers_changed = 0
    if not args.h2h_only:
        print(f"\n  {'manager':10} {'stored W-L':>14} {'regular season only':>22}  "
              f"{'removed':>8}")
        for m in sorted(set(stored_careers) | set(careers_correct)):
            cur = stored_careers.get(m, {})
            sw, sl = cur.get("total_wins", 0), cur.get("total_losses", 0)
            cw, cl = careers_correct.get(m, [0, 0])
            if (sw, sl) != (cw, cl):
                careers_changed += 1
            print(f"  {m:10} {sw:>6}-{sl:<7} {cw:>10}-{cl:<11} "
                  f"{(sw + sl) - (cw + cl):>8}")

    if args.careers_only:
        changed = 0
    if args.h2h_only:
        careers_changed = 0

    if not changed and not careers_changed:
        print("\n  Already correct. Nothing to do.")
        return 0

    if not args.execute:
        print(f"\n  [DRY-RUN] {changed} pair(s) and {careers_changed} career "
              "record(s) would change. Nothing written.")
        print("  This changes the all-time series and career win % the")
        print("  newsletter prints.")
        return 0

    backup = RECORDS.with_suffix(".json.bak")
    shutil.copy2(RECORDS, backup)
    print(f"\n  Backup: {backup.name}")

    if not args.careers_only:
        # Preserve the original capitalisation of manager names.
        case = {}
        for v in records.get("all_time", {}).get("h2h", {}).values():
            for name in v:
                case[name.lower()] = name
        records.setdefault("all_time", {})["h2h"] = {
            k: {case.get(n, n): c for n, c in sorted(v.items())}
            for k, v in sorted(correct.items())
        }

    if not args.h2h_only:
        careers = records.setdefault("all_time", {}).setdefault("manager_careers", {})
        for m, (w, l) in careers_correct.items():
            entry = careers.setdefault(m, {})
            entry["total_wins"] = w
            entry["total_losses"] = l
            entry["games_played"] = w + l
            entry["games_scope"] = "regular_season"
            entry["win_pct"] = round((w / (w + l)) * 100, 1) if (w + l) else 0

    RECORDS.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    check = json.loads(RECORDS.read_text(encoding="utf-8"))
    if not args.careers_only:
        got = {k: {kk.lower(): vv for kk, vv in v.items()}
               for k, v in check["all_time"]["h2h"].items()}
        if got != correct:
            print("  VERIFICATION FAILED (h2h) -- restore from the backup.")
            return 1
    if not args.h2h_only:
        for m, (w, l) in careers_correct.items():
            got = check["all_time"]["manager_careers"][m]
            if (got["total_wins"], got["total_losses"], got["games_played"]) != (w, l, w + l):
                print(f"  VERIFICATION FAILED (careers: {m}) -- restore from the backup.")
                return 1
    print(f"  Wrote and verified {len(correct)} pairs and "
          f"{len(careers_correct)} career records.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
