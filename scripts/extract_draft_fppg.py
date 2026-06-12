#!/usr/bin/env python3
"""
extract_draft_fppg.py

Extracts season FPPG for every drafted player, cross-referencing
all_drafts.json + DRAFT_PICKS_CURRENT.json against HISTORICAL_PLAYERLOG.json
and PLAYERLOG.xlsx.

Outputs a compact JSON file (data/historical/DRAFT_PERFORMANCE.json) small
enough to upload to Claude Projects.

Usage:
    python scripts/extract_draft_fppg.py

Output: data/historical/DRAFT_PERFORMANCE.json
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# ---- Paths (adjust if your layout differs) ----
PROJECT_ROOT = Path(__file__).parent.parent
HISTORICAL_PLAYERLOG = PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
PLAYERLOG_XLSX = PROJECT_ROOT / "data" / "PLAYERLOG.xlsx"
ALL_DRAFTS = PROJECT_ROOT / "data" / "historical" / "all_drafts.json"
DRAFT_PICKS_CURRENT = PROJECT_ROOT / "config" / "DRAFT_PICKS_CURRENT.json"
OUTPUT_FILE = PROJECT_ROOT / "data" / "historical" / "DRAFT_PERFORMANCE.json"


def normalize_season(s: str) -> str:
    """Normalize '2025-2026' -> '2025-26', leave '2025-26' as-is."""
    s = str(s).strip()
    if len(s) >= 9 and s[4] == "-":
        return f"{s[:4]}-{s[-2:]}"
    return s


def load_drafts() -> list[dict]:
    """Load all draft picks (historical + current season)."""
    picks = []

    # Historical drafts
    if ALL_DRAFTS.exists():
        with open(ALL_DRAFTS, "r", encoding="utf-8") as f:
            historical = json.load(f)
        for p in historical:
            picks.append({
                "season": normalize_season(p["season"]),
                "round": int(p["round"]),
                "pick_number": int(p["pick_number"]),
                "player_name": p["player_name"],
                "manager": p["manager"],
            })
        print(f"Loaded {len(historical)} picks from all_drafts.json")
    else:
        print(f"WARNING: {ALL_DRAFTS} not found")

    # Current season draft
    if DRAFT_PICKS_CURRENT.exists():
        with open(DRAFT_PICKS_CURRENT, "r", encoding="utf-8") as f:
            current = json.load(f)
        for p in current.get("picks", []):
            picks.append({
                "season": normalize_season(p["season"]),
                "round": int(p["round"]),
                "pick_number": int(p["pick_number"]),
                "player_name": p["player_name"],
                "manager": p["manager"],
            })
        print(f"Loaded {len(current.get('picks', []))} picks from DRAFT_PICKS_CURRENT.json")
    else:
        print(f"WARNING: {DRAFT_PICKS_CURRENT} not found")

    return picks


def build_fppg_lookup_historical() -> dict:
    """
    Scan HISTORICAL_PLAYERLOG.json and compute season FPPG per (player, season).

    Only counts games where the player started (was in active lineup).
    Returns: {(player_name, season): {"gp": int, "total_fp": float, "fppg": float}}
    """
    if not HISTORICAL_PLAYERLOG.exists():
        print(f"ERROR: {HISTORICAL_PLAYERLOG} not found!")
        sys.exit(1)

    print(f"Loading HISTORICAL_PLAYERLOG.json (this may take a moment)...")
    with open(HISTORICAL_PLAYERLOG, "r", encoding="utf-8") as f:
        rows = json.load(f)
    print(f"  {len(rows):,} game rows loaded")

    # Accumulate: (player_name, season) -> {total_fp, gp}
    accum = defaultdict(lambda: {"total_fp": 0.0, "gp": 0})

    for row in rows:
        # Only count started games
        if not row.get("started", False):
            continue

        fp = row.get("fantasy_points")
        if fp is None or fp == "":
            continue
        fp = float(fp)
        if fp <= 0:
            continue  # Skip DNPs/injuries

        player = row.get("player_name", "").strip()
        season = normalize_season(row.get("season_year", ""))
        if not player or not season:
            continue

        key = (player, season)
        accum[key]["total_fp"] += fp
        accum[key]["gp"] += 1

    # Compute FPPG
    lookup = {}
    for key, stats in accum.items():
        if stats["gp"] > 0:
            lookup[key] = {
                "gp": stats["gp"],
                "total_fp": round(stats["total_fp"], 2),
                "fppg": round(stats["total_fp"] / stats["gp"], 2),
            }

    print(f"  Computed FPPG for {len(lookup):,} (player, season) combos")
    return lookup


def build_fppg_lookup_current() -> dict:
    """
    Compute season FPPG from PLAYERLOG.xlsx for the current season.
    Returns same format as historical lookup.
    """
    if not PLAYERLOG_XLSX.exists():
        print(f"WARNING: {PLAYERLOG_XLSX} not found, skipping current season")
        return {}

    try:
        import pandas as pd
    except ImportError:
        print("WARNING: pandas not installed, skipping current season PLAYERLOG.xlsx")
        return {}

    df = pd.read_excel(PLAYERLOG_XLSX)
    print(f"Loaded {len(df)} rows from PLAYERLOG.xlsx")

    # Filter to started games with positive FP
    mask = (df["started"] == True) & (df["fantasy_points"] > 0)
    started = df[mask]

    lookup = {}
    for (player, season_year), group in started.groupby(["player_name", "season_year"]):
        season = normalize_season(str(season_year))
        total_fp = group["fantasy_points"].sum()
        gp = len(group)
        lookup[(player, season)] = {
            "gp": gp,
            "total_fp": round(float(total_fp), 2),
            "fppg": round(float(total_fp / gp), 2),
        }

    print(f"  Computed FPPG for {len(lookup)} players in current season")
    return lookup


def main():
    print("=" * 60)
    print("DRAFT PICK FPPG EXTRACTOR")
    print("=" * 60)

    # 1. Load all draft picks
    picks = load_drafts()
    if not picks:
        print("ERROR: No draft picks found!")
        sys.exit(1)

    # 2. Build FPPG lookups
    fppg_historical = build_fppg_lookup_historical()
    fppg_current = build_fppg_lookup_current()

    # Merge (current overrides historical for same keys)
    fppg_all = {**fppg_historical, **fppg_current}

    # 3. Match each draft pick to their season performance
    results = []
    matched = 0
    missed = 0

    for pick in picks:
        key = (pick["player_name"], pick["season"])
        stats = fppg_all.get(key)

        entry = {
            "season": pick["season"],
            "round": pick["round"],
            "pick_number": pick["pick_number"],
            "player_name": pick["player_name"],
            "manager": pick["manager"],
        }

        if stats:
            entry["gp"] = stats["gp"]
            entry["total_fp"] = stats["total_fp"]
            entry["fppg"] = stats["fppg"]
            matched += 1
        else:
            entry["gp"] = 0
            entry["total_fp"] = 0.0
            entry["fppg"] = None
            missed += 1

        results.append(entry)

    print(f"\n{'=' * 60}")
    print(f"Matched: {matched}/{len(picks)} draft picks to season performance")
    if missed > 0:
        print(f"Missed:  {missed} picks (player not found in playerlog for that season)")
        # Show some misses for debugging
        misses = [r for r in results if r["fppg"] is None]
        for m in misses[:10]:
            print(f"  - {m['season']} R{m['round']}: {m['player_name']} ({m['manager']})")
        if len(misses) > 10:
            print(f"  ... and {len(misses) - 10} more")

    # 4. Save output
    output = {
        "_description": "Season FPPG for every draft pick across all seasons. Used to compute data-driven draft pick values.",
        "_generated_by": "scripts/extract_draft_fppg.py",
        "seasons": sorted(set(r["season"] for r in results)),
        "total_picks": len(results),
        "matched_picks": matched,
        "picks": results,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to {OUTPUT_FILE}")
    print(f"File size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")
    print("Upload this file to Claude Projects to continue.")


if __name__ == "__main__":
    main()
