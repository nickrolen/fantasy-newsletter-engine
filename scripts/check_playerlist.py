#!/usr/bin/env python3
"""
check_playerlist.py -- gate data/PLAYERLIST.xlsx before it reaches the engine.

WHY
---
PLAYERLIST carries the projections every simulator runs on, and until now
nothing checked it. The rules were written down in WEEKLY_WORKFLOW Step 2.5
and enforced by an LLM following a prompt; check_file_health.py never opened
the file. So a bad week looked exactly like a good one.

The failure modes are all quiet:

    a rostered player missing        -> 0.0 FPPG in every simulation
    a column shifted by one          -> plausible numbers, wrong players
    the file not regenerated         -> last week's projections, silently
    an age missing                   -> defaults to 27 in keepability
    GP or FP unparseable             -> the row vanishes

None of those raise. Each of them changes the newsletter.

WHAT IT COMPARES AGAINST
------------------------
Itself, a week ago. config/snapshots/ keeps a copy each time this runs
clean, and the week-over-week comparison is what catches a misaligned paste
or scrape: projected FPPG does not move 40% in a week, and projected games
REMAINING cannot go up.

USAGE
    py scripts/check_playerlist.py
    py scripts/check_playerlist.py --snapshot     # save as this week's baseline
    py scripts/check_playerlist.py --strict       # warnings become failures

EXIT CODES
    0 = usable
    1 = do not generate a newsletter from this
"""

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import normalize_player_name  # noqa: E402

PLAYERLIST = PROJECT_ROOT / "data" / "PLAYERLIST.xlsx"
ROSTERS = PROJECT_ROOT / "config" / "ROSTERS.json"
SNAPSHOTS = PROJECT_ROOT / "config" / "snapshots"

REQUIRED = ["player_name", "player_nba_team", "player_position(s)",
            "player_total_proj_FP", "player_proj_GP", "projectedFPPG"]

# A projection is a forecast, not a measurement, so it moves. These bounds are
# set wide enough that ordinary week-to-week drift is quiet and a structural
# error is not.
FPPG_JUMP = 0.40        # 40% week-over-week change in projected FPPG
FPPG_FLOOR = 5.0        # nobody worth listing projects below this
FPPG_CEILING = 90.0     # nobody projects above this either
GP_GROWTH = 2           # games REMAINING may not rise by more than this


def load_rosters() -> dict:
    if not ROSTERS.is_file():
        return {}
    try:
        blob = json.loads(ROSTERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rosters = blob.get("rosters", blob)
    return {m: p for m, p in rosters.items() if isinstance(p, list)}


def previous_snapshot():
    """The most recent saved PLAYERLIST, or None."""
    if not SNAPSHOTS.is_dir():
        return None, None
    found = sorted(SNAPSHOTS.glob("PLAYERLIST_*.xlsx"), reverse=True)
    if not found:
        return None, None
    try:
        return pd.read_excel(found[0]), found[0]
    except Exception:
        return None, found[0]


def main():
    ap = argparse.ArgumentParser(description="Validate data/PLAYERLIST.xlsx.")
    ap.add_argument("--snapshot", action="store_true",
                    help="save this file as the baseline for next week")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as failures")
    args = ap.parse_args()

    failures, warnings = [], []

    print("=" * 66)
    print("  CHECK PLAYERLIST")
    print("=" * 66)

    if not PLAYERLIST.is_file():
        print("\n  FAIL: data/PLAYERLIST.xlsx does not exist.")
        return 1
    try:
        frame = pd.read_excel(PLAYERLIST)
    except Exception as e:
        print(f"\n  FAIL: could not read it: {e}")
        return 1

    missing_cols = [c for c in REQUIRED if c not in frame.columns]
    if missing_cols:
        print(f"\n  FAIL: missing column(s): {missing_cols}")
        return 1
    if frame.empty:
        print("\n  FAIL: no rows. The season reset empties this file; it has "
              "to be rebuilt before a newsletter can be generated.\n"
              "  Run: py scripts/fetch_playerlist.py --execute")
        return 1

    frame["_key"] = frame["player_name"].apply(normalize_player_name)
    print(f"\n  {len(frame)} players")

    # --- duplicates ---------------------------------------------------------
    dupes = frame[frame["_key"].duplicated(keep=False)]
    if not dupes.empty:
        names = sorted(set(dupes["player_name"]))
        failures.append(f"duplicate players ({len(names)}): {names[:6]}")

    # --- the arithmetic -----------------------------------------------------
    off = []
    for _, row in frame.iterrows():
        gp = pd.to_numeric(row["player_proj_GP"], errors="coerce")
        fp = pd.to_numeric(row["player_total_proj_FP"], errors="coerce")
        fppg = pd.to_numeric(row["projectedFPPG"], errors="coerce")
        if pd.isna(gp) or pd.isna(fp) or pd.isna(fppg):
            failures.append(f"{row['player_name']}: unreadable GP/FP/FPPG")
            continue
        if gp > 0 and abs(fp / gp - fppg) > 0.05:
            off.append(f"{row['player_name']} ({fp:.1f}/{gp:.0f}="
                       f"{fp / gp:.2f} vs {fppg:.2f})")
    if off:
        failures.append(f"projectedFPPG does not equal total/GP for "
                        f"{len(off)}: {off[:4]}")

    # --- plausibility -------------------------------------------------------
    fppg = pd.to_numeric(frame["projectedFPPG"], errors="coerce")
    low = frame[fppg < FPPG_FLOOR]["player_name"].tolist()
    high = frame[fppg > FPPG_CEILING]["player_name"].tolist()
    if low:
        failures.append(f"{len(low)} player(s) below {FPPG_FLOOR} FPPG: {low[:5]}")
    if high:
        failures.append(f"{len(high)} player(s) above {FPPG_CEILING} FPPG: {high[:5]}")
    print(f"  FPPG range: {fppg.min():.1f} - {fppg.max():.1f}")

    # --- roster coverage ----------------------------------------------------
    rosters = load_rosters()
    if rosters:
        have = set(frame["_key"])
        absent = []
        for manager, players in rosters.items():
            for p in players:
                if normalize_player_name(p) not in have:
                    absent.append(f"{p} ({manager})")
        if absent:
            failures.append(
                f"{len(absent)} rostered player(s) missing -- each would "
                f"project 0.0 FPPG: {absent[:8]}")
        else:
            total = sum(len(p) for p in rosters.values())
            print(f"  roster coverage: {total}/{total} rostered players present")
    else:
        warnings.append("config/ROSTERS.json is empty or unreadable, so roster "
                        "coverage was NOT checked. Before the draft this is "
                        "expected.")

    # --- ages ---------------------------------------------------------------
    if "age" in frame.columns:
        ageless = frame[frame["age"].isna()]["player_name"].tolist()
        if ageless:
            warnings.append(
                f"{len(ageless)} player(s) with no age (keepability will "
                f"assume 27): {ageless[:6]}")
    else:
        warnings.append("no age column")

    # --- against last week --------------------------------------------------
    prev, prev_path = previous_snapshot()
    if prev is None:
        warnings.append("no previous snapshot to compare against. Run with "
                        "--snapshot to start the baseline.")
    else:
        prev = prev.copy()
        prev["_key"] = prev["player_name"].apply(normalize_player_name)
        joined = frame.merge(prev, on="_key", suffixes=("", "_prev"))
        print(f"  compared against {prev_path.name} "
              f"({len(joined)} players in both)")

        if len(joined) == len(frame) == len(prev):
            same = frame[REQUIRED].equals(prev[REQUIRED]) if list(prev.columns) else False
            if same:
                failures.append(
                    "identical to the previous snapshot -- this file was not "
                    "regenerated this week")

        jumps, grew = [], []
        for _, row in joined.iterrows():
            a = pd.to_numeric(row["projectedFPPG"], errors="coerce")
            b = pd.to_numeric(row["projectedFPPG_prev"], errors="coerce")
            if pd.notna(a) and pd.notna(b) and b > 0:
                if abs(a - b) / b > FPPG_JUMP:
                    jumps.append(f"{row['player_name']} {b:.1f} -> {a:.1f}")
            g = pd.to_numeric(row["player_proj_GP"], errors="coerce")
            h = pd.to_numeric(row["player_proj_GP_prev"], errors="coerce")
            if pd.notna(g) and pd.notna(h) and g - h > GP_GROWTH:
                grew.append(f"{row['player_name']} {h:.0f} -> {g:.0f}")
        if jumps:
            warnings.append(
                f"{len(jumps)} player(s) moved more than {FPPG_JUMP:.0%} in "
                f"projected FPPG: {jumps[:6]}")
        if grew:
            failures.append(
                f"{len(grew)} player(s) have MORE games remaining than last "
                f"week, which cannot happen in a rest-of-season projection -- "
                f"this is the signature of a misaligned column: {grew[:6]}")

    # --- report -------------------------------------------------------------
    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")
    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    - {f}")

    if args.strict and warnings and not failures:
        print("\n  --strict: warnings treated as failures.")
        return 1
    if failures:
        print("\n  RESULT: DO NOT generate a newsletter from this file.")
        print("  Rebuild it: py scripts/fetch_playerlist.py --execute")
        print("  Or fall back to the manual procedure in WEEKLY_WORKFLOW.md "
              "Step 2.5.")
        return 1

    print("\n  RESULT: usable." + (f" {len(warnings)} warning(s)." if warnings else ""))

    if args.snapshot:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        target = SNAPSHOTS / f"PLAYERLIST_{date.today().isoformat()}.xlsx"
        shutil.copy2(PLAYERLIST, target)
        print(f"  Saved baseline: {target.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
