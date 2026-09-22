#!/usr/bin/env python3
"""
backfill_season_record_scope.py -- add the competitive record to stored
season leaderboards.

WHY
---
`best_manager_season_top10` and its three siblings store a W-L alongside the
volume figure they actually rank on. That W-L has always been the ALL-GAMES
record -- every matchup played, including the postseason. Through 2025-26
that differed from the regular-season record by two games and nobody noticed.

From 2026-27 it differs by eight, and the competitive season is 15 weeks
where it used to be 21. An unlabelled "19-4" on a leaderboard is now the one
number in the record book that can be read two ways.

report_builder writes `reg_wins`/`reg_losses`/`reg_weeks` alongside the
all-games pair from 2026-27 onward. This backfills those three fields onto
the entries already stored, so the leaderboard does not show a labelled
record for new seasons and an unlabelled one for old.

Historical records come from data/historical/all_matchups.json. Seasons that
file does not cover are read from archive/<season>/config/. A season that
neither source can resolve is left alone -- the display falls back to "all
games" for that row, which is true, rather than to a guess.

USAGE
    py scripts/backfill_season_record_scope.py            # dry run
    py scripts/backfill_season_record_scope.py --execute

EXIT CODES
    0 = done (or nothing to do)
    1 = could not run
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import is_regular_season_week  # noqa: E402

RECORDS = PROJECT_ROOT / "config" / "RECORDS.json"
ALL_MATCHUPS = PROJECT_ROOT / "data" / "historical" / "all_matchups.json"
STANDINGS = PROJECT_ROOT / "data" / "historical" / "all_standings.json"
ARCHIVE = PROJECT_ROOT / "archive"

TOP10_KEYS = [
    "best_manager_season_top10",
    "worst_manager_season_top10",
    "best_manager_season_fpweek_top10",
    "worst_manager_season_fpweek_top10",
    "best_manager_season_fppg_top10",
    "worst_manager_season_fppg_top10",
]


def _blank():
    return {"reg_wins": 0, "reg_losses": 0, "reg_weeks": 0}


def from_all_matchups(path: Path) -> dict:
    """{season: {manager: {reg_wins, reg_losses, reg_weeks}}}"""
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    out = defaultdict(lambda: defaultdict(_blank))
    for row in rows:
        season, week = row.get("season"), row.get("week")
        if season is None or week is None:
            continue
        if not is_regular_season_week(season, week):
            continue
        for side in ("manager_a", "manager_b"):
            mgr = row.get(side)
            if mgr:
                out[season][mgr]["reg_weeks"] += 1
        if row.get("winner"):
            out[season][row["winner"]]["reg_wins"] += 1
        if row.get("loser"):
            out[season][row["loser"]]["reg_losses"] += 1
    return {s: dict(m) for s, m in out.items()}


def from_archive(season: str) -> dict:
    """{manager: {...}} for one archived season, or {}."""
    cfg = ARCHIVE / season / "config"
    rec_path, sched_path = cfg / "RECORDS.json", cfg / "SCHEDULE.json"
    if not (rec_path.is_file() and sched_path.is_file()):
        return {}
    try:
        records = json.loads(rec_path.read_text(encoding="utf-8"))
        schedule = json.loads(sched_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    scores = defaultdict(dict)
    for mgr, rows in records.get("weekly_scores", {}).items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            week = row.get("week")
            if week is not None:
                scores[int(week)][mgr] = float(row.get("score", 0.0) or 0.0)

    out = defaultdict(_blank)
    for wk in schedule.get("weeks", []):
        week = wk.get("week")
        if week is None or not is_regular_season_week(season, week):
            continue
        for mu in wk.get("matchups", []):
            a, b = mu.get("manager_a"), mu.get("manager_b")
            sa, sb = scores.get(int(week), {}).get(a), scores.get(int(week), {}).get(b)
            if a is None or b is None or sa is None or sb is None:
                continue
            out[a]["reg_weeks"] += 1
            out[b]["reg_weeks"] += 1
            if sa > sb:
                out[a]["reg_wins"] += 1
                out[b]["reg_losses"] += 1
            elif sb > sa:
                out[b]["reg_wins"] += 1
                out[a]["reg_losses"] += 1
    return dict(out)


def main():
    parser = argparse.ArgumentParser(
        description="Backfill the competitive record onto season leaderboards.")
    parser.add_argument("--execute", action="store_true",
                        help="write the changes (default: dry run)")
    args = parser.parse_args()

    if not RECORDS.is_file():
        print(f"ERROR: missing {RECORDS}")
        return 1

    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    all_time = records.get("all_time", {})

    resolved = from_all_matchups(ALL_MATCHUPS)
    print(f"  all_matchups.json covers: {', '.join(sorted(resolved)) or '(none)'}")

    wanted = {e.get("season") for key in TOP10_KEYS
              for e in all_time.get(key, []) if e.get("season")}
    for season in sorted(wanted - set(resolved)):
        from_arc = from_archive(season)
        if from_arc:
            resolved[season] = from_arc
            print(f"  {season}: read from archive/{season}/config/")

    missing = sorted(wanted - set(resolved))
    if missing:
        print(f"  UNRESOLVED (left as all-games): {', '.join(missing)}")

    # All-games W-L for every season/manager, from the standings file. Some
    # leaderboard entries were written mid-season and never refreshed: three
    # 2025-26 rows in worst_manager_season_fppg_top10 carry a week-22 record
    # (Nick 17-5) while best_manager_season_top10 has the finished one (17-6).
    # Same file, same season, two different records.
    standings = {}
    if STANDINGS.is_file():
        for row in json.loads(STANDINGS.read_text(encoding="utf-8")):
            standings[(row["season"], row["manager"])] = row

    patched = skipped = corrected = 0
    for key in TOP10_KEYS:
        for entry in all_time.get(key, []):
            season, mgr = entry.get("season"), entry.get("manager")

            final = standings.get((season, mgr))
            if final and (entry.get("wins"), entry.get("losses")) != \
                    (final["wins"], final["losses"]):
                print(f"    stale W-L  {key}: {season} {mgr} "
                      f"{entry.get('wins')}-{entry.get('losses')} -> "
                      f"{final['wins']}-{final['losses']}")
                entry["wins"], entry["losses"] = final["wins"], final["losses"]
                corrected += 1

            if entry.get("reg_weeks"):
                continue
            found = resolved.get(season, {}).get(mgr)
            if not found or not found["reg_weeks"]:
                skipped += 1
                continue
            entry.update(found)
            patched += 1

    print()
    print(f"  entries patched: {patched}")
    print(f"  entries left alone: {skipped}")
    print(f"  stale W-L corrected: {corrected}")

    sample = [e for e in all_time.get(TOP10_KEYS[0], []) if e.get("reg_weeks")][:5]
    if sample:
        print("\n  Sample (all-games vs competitive):")
        for e in sample:
            print(f"    {e['season']:8} {e['manager']:8} "
                  f"{e.get('wins', 0):>2}-{e.get('losses', 0):<2} over "
                  f"{e.get('weeks', 0)} wks  ->  "
                  f"{e['reg_wins']:>2}-{e['reg_losses']:<2} over "
                  f"{e['reg_weeks']} reg wks")

    if not args.execute:
        print("\n  DRY RUN -- pass --execute to write config/RECORDS.json")
        return 0
    if not patched and not corrected:
        print("\n  Nothing to write.")
        return 0

    RECORDS.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"\n  Wrote {RECORDS.name}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
