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
or scrape. A misalignment moves MOST rows at once, in no particular
direction; a projection refresh moves a few. (It used to fail on any one
player gaining games remaining. That happens whenever an injury outlook
improves -- six players on 2026-10-13 -- and was wrong; see GP_UP_SHARE.)

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
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import (  # noqa: E402
    PlayerIndex, normalize_player_name, _without_suffix, initial_match,
)
from modules import playerlist_freshness  # noqa: E402

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
GP_CEILING = 82         # an NBA regular season; nobody has more remaining

# Share of players present in both weeks whose projected games remaining went
# UP, above which the file is treated as misaligned. Measured 2026-10-13:
#   Yahoo's real refresh 10-05 -> 10-13    6 of 168 up (3.6%), 10 down
#   stats shifted one row against names   78-82 of 175 up (45-47%)
# In season every player's games remaining falls each week, so a legitimate
# refresh is mostly DOWN; a shift is a coin flip either way. "How many rows
# changed" would not work -- in season nearly all of them change. Direction
# is the signature. The 40% FPPG jump below misses the likely shift entirely:
# fetch_playerlist sorts by total FP, so neighbouring rows have similar FPPG
# (0 of 175 rows jumped 40% in the simulated shift).
GP_UP_SHARE = 0.25
MIN_COMMON_FOR_SHARE = 20   # fewer players in common and a share means little


def load_rosters() -> dict:
    if not ROSTERS.is_file():
        return {}
    try:
        blob = json.loads(ROSTERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rosters = blob.get("rosters", blob)
    return {m: p for m, p in rosters.items() if isinstance(p, list)}


def _snapshot_is_from_today(path) -> bool:
    """Snapshots are named PLAYERLIST_<YYYY-MM-DD>.xlsx."""
    found = re.search(r"(\d{4}-\d{2}-\d{2})", getattr(path, "name", ""))
    return bool(found) and found.group(1) == date.today().isoformat()


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
    ap.add_argument("--file", default=None,
                    help="check this workbook instead of data/PLAYERLIST.xlsx "
                         "(e.g. one written by fetch_playerlist.py --out)")
    args = ap.parse_args()
    path = Path(args.file) if args.file else PLAYERLIST
    if args.file and args.snapshot:
        print("  --snapshot saves the LIVE file as next week's baseline; it "
              "cannot be combined with --file.")
        return 1

    failures, warnings = [], []

    print("=" * 66)
    print("  CHECK PLAYERLIST")
    print("=" * 66)

    if not path.is_file():
        print(f"\n  FAIL: {path} does not exist.")
        return 1
    try:
        frame = pd.read_excel(path)
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
    gp_all = pd.to_numeric(frame["player_proj_GP"], errors="coerce")
    gp_bad = frame[(gp_all < 0) | (gp_all > GP_CEILING)]["player_name"].tolist()
    if gp_bad:
        failures.append(f"{len(gp_bad)} player(s) with projected GP outside "
                        f"0-{GP_CEILING}: {gp_bad[:5]}")
    if low:
        failures.append(f"{len(low)} player(s) below {FPPG_FLOOR} FPPG: {low[:5]}")
    if high:
        failures.append(f"{len(high)} player(s) above {FPPG_CEILING} FPPG: {high[:5]}")
    print(f"  FPPG range: {fppg.min():.1f} - {fppg.max():.1f}")

    # --- roster coverage ----------------------------------------------------
    # Through PlayerIndex, the resolver the simulators use, so this check and
    # the engine agree on who is present. Yahoo's roster and pool endpoints
    # spell some players differently in the same fetch ("Shai Gilgeous-
    # Alexander" / "S. Gilgeous-Alexander"); plain normalising called that a
    # missing player while the engine -- on 10-12 -- also missed him, through
    # a second, shorter copy of the ladder. Both now resolve the same way.
    rosters = load_rosters()
    if rosters:
        have = PlayerIndex({n: n for n in frame["player_name"]})
        absent, respelled = [], []
        for manager, players in rosters.items():
            for p in players:
                hit = have.get(p)
                if hit is None:
                    absent.append(f"{p} ({manager})")
                elif normalize_player_name(hit) != normalize_player_name(p):
                    respelled.append(f"{p} -> {hit}")
        if respelled:
            print(f"  resolved by respelling ({len(respelled)}): "
                  f"{', '.join(respelled[:6])}")
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

    # --- when it was fetched -------------------------------------------------
    # A fact written by fetch_playerlist, not an inference from whether the
    # numbers moved (modules/playerlist_freshness.py).
    fresh = playerlist_freshness.assess(
        frame.drop(columns=["_key"]), playerlist_freshness.read_stamp(path))
    if fresh["how"] == "stamp":
        print(f"  fetched {fresh['fetched_on']} ({fresh['age_days']} day(s) ago) "
              f"from {fresh['source']}")
        if fresh["stale"]:
            failures.append(
                f"fetched {fresh['age_days']} days ago ({fresh['fetched_on']}), "
                f"more than {playerlist_freshness.MAX_AGE_DAYS} -- this week's "
                f"projections were not pulled")
    elif fresh["how"] == "mismatch":
        warnings.append(
            "the fetch stamp no longer matches the projections in this file "
            "(edited after fetching?), so it was ignored and freshness is "
            "judged by comparing against the last snapshot")
    else:
        warnings.append(
            "no fetch stamp (built by hand, or before stamps existed), so "
            "freshness is judged by comparing against the last snapshot. "
            "fetch_playerlist.py --execute writes one.")

    # --- against last week --------------------------------------------------
    prev, prev_path = previous_snapshot()
    if prev is None:
        warnings.append("no previous snapshot to compare against. Run with "
                        "--snapshot to start the baseline.")
    else:
        prev = prev.copy()
        prev["_key"] = prev["player_name"].apply(normalize_player_name)
        joined = frame.merge(prev, on="_key", suffixes=("", "_prev"))

        # Yahoo renames players. On 2026-10-05 "Shai Gilgeous-Alexander"
        # became "S. Gilgeous-Alexander" and "Bobby Portis" became "Bobby
        # Portis Jr." -- not one projection changed, only the spelling --
        # while every other file in the project kept the old form. A rename
        # looks exactly like one player leaving the pool and another
        # arriving, so nothing flagged it, and a keeper silently lost his
        # projection. Anything that leaves and comes back under a name
        # reducing to the same person is reported.
        entered = set(frame["player_name"]) - set(prev["player_name"])
        departed = set(prev["player_name"]) - set(frame["player_name"])
        renames = []
        for gone in sorted(departed):
            for arrived in sorted(entered):
                same = (_without_suffix(gone) == _without_suffix(arrived)
                        or initial_match(gone, arrived))
                if same:
                    renames.append((gone, arrived))
        for gone, arrived in renames:
            warnings.append(
                f"Yahoo renamed {gone!r} to {arrived!r}. Projections still "
                f"resolve, but every other file in the project uses the old "
                f"spelling -- check anything that stores this name.")

        print(f"  compared against {prev_path.name} "
              f"({len(joined)} players in both)")

        if len(joined) == len(frame) == len(prev):
            same = frame[REQUIRED].equals(prev[REQUIRED]) if list(prev.columns) else False
            # Identical to a snapshot taken on an EARLIER day means the file
            # was not rebuilt. Identical to one taken today just means this
            # ran twice today, which is what happens after a re-run, and
            # Yahoo's numbers do not move between two runs an hour apart.
            if same and fresh["how"] == "stamp":
                # The stamp already settled freshness; identical numbers just
                # mean Yahoo has not moved a projection since the snapshot.
                print(f"  (projections unchanged since {prev_path.name}; the "
                      f"file itself was fetched {fresh['fetched_on']})")
            elif same and _snapshot_is_from_today(prev_path):
                print("  (identical to today's snapshot -- a same-day re-run, "
                      "not a stale file)")
            elif same:
                failures.append(
                    "identical to the previous snapshot -- this file was not "
                    "regenerated this week")

        jumps, grew, compared = [], [], 0
        for _, row in joined.iterrows():
            a = pd.to_numeric(row["projectedFPPG"], errors="coerce")
            b = pd.to_numeric(row["projectedFPPG_prev"], errors="coerce")
            if pd.notna(a) and pd.notna(b) and b > 0:
                if abs(a - b) / b > FPPG_JUMP:
                    jumps.append(f"{row['player_name']} {b:.1f} -> {a:.1f}")
            g = pd.to_numeric(row["player_proj_GP"], errors="coerce")
            h = pd.to_numeric(row["player_proj_GP_prev"], errors="coerce")
            if pd.notna(g) and pd.notna(h):
                compared += 1
                if g > h:
                    grew.append(f"{row['player_name']} {h:.0f} -> {g:.0f}")
        if jumps:
            warnings.append(
                f"{len(jumps)} player(s) moved more than {FPPG_JUMP:.0%} in "
                f"projected FPPG: {jumps[:6]}")
        share = len(grew) / compared if compared else 0.0
        if compared >= MIN_COMMON_FOR_SHARE and share > GP_UP_SHARE:
            failures.append(
                f"{len(grew)} of {compared} players ({share:.0%}) have more games "
                f"remaining than last week. A refresh moves a few players up as "
                f"injury outlooks improve; this many, in both directions, is the "
                f"signature of stats shifted against names: {grew[:6]}")
        elif grew:
            print(f"  games remaining up for {len(grew)} of {compared} "
                  f"({share:.0%}; outlooks improving -- not a problem): "
                  f"{', '.join(grew[:6])}")

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
