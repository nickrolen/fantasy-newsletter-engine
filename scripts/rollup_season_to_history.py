#!/usr/bin/env python3
"""
rollup_season_to_history.py -- Append a finished season's per-game player log
to the permanent historical record.

WHY THIS EXISTS
---------------
The project deliberately keeps the current season OUT of data/historical/.
Working files (PLAYERLOG.xlsx, LINEUPS.xlsx) accumulate all season; between
seasons the finished season is rolled into history and the working files are
reset.

Most of that roll-in is automated: pull_historical_data.py re-fetches
standings, matchups, drafts and trades from Yahoo. But HISTORICAL_PLAYERLOG
.json -- 76k rows of per-game, per-slot player detail built up daily by
update_fantasy_logs.py -- cannot be re-fetched. Yahoo does not serve
day-by-day historical rosters for a closed league. Every script that touches
that file only READS it.

So this was the one step with no tooling, and it is also the only
irreversible one: start_new_season.py Phase 2 truncates PLAYERLOG.xlsx to a
header row. Miss this step and the season's per-game detail survives only as
an archived spreadsheet.

WHAT IT DOES
------------
PLAYERLOG.xlsx does not have the historical schema. Four fields have to be
supplied, and this script derives all four rather than asking a human to:

  season_key   "2025-2026" -> "2025-26"
  slot         joined from LINEUPS.xlsx on (date, manager, player_name)
  had_game     True when nba_opponent is set
               (verified: 0 disagreements across all 76,098 historical rows)
  player_id    looked up by name from existing history
               (verified: no player has ever had two ids)

Three xlsx-only columns (source, notes, opponent_manager) are dropped -- they
are weekly-workflow bookkeeping and are not part of the historical schema.

It also canonicalizes player names against the existing record. A single row
spelled "Lebron James" instead of "LeBron James" would append as a separate
player: career totals split in two, records understated, and nothing would
ever flag it. Names that match an existing player after normalization
(case, accents, punctuation) are rewritten to the historical spelling and
reported. Ambiguous matches are left alone and reported instead.

SAFETY
------
Dry-run by default, same as start_new_season.py. Refuses to append a season
that is already present. Backs up before writing, then re-reads and verifies
the result. Run this BEFORE start_new_season.py.

USAGE
    py scripts/rollup_season_to_history.py                # preview (default)
    py scripts/rollup_season_to_history.py --execute      # do it
    py scripts/rollup_season_to_history.py --execute --force   # replace a
                                                          # season already in
                                                          # the record
    py scripts/rollup_season_to_history.py --season 2025-26    # override

EXIT CODES
    0 = success (or a clean dry run)
    1 = refused or failed; nothing was written
"""

import argparse
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import CURRENT_SEASON, CURRENT_SEASON_LONG  # noqa: E402

PLAYERLOG_XLSX = PROJECT_ROOT / "data" / "PLAYERLOG.xlsx"
LINEUPS_XLSX = PROJECT_ROOT / "data" / "LINEUPS.xlsx"
HISTORY_JSON = PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"

# The historical schema, in order. Rows are written with exactly these keys.
HISTORY_FIELDS = [
    "season_year", "season_key", "week", "date", "manager", "fantasy_team",
    "player_name", "player_id", "positions", "slot", "fantasy_points",
    "started", "nba_team", "nba_opponent", "had_game", "is_injured",
]

JOIN_KEY = ["date", "manager", "player_name"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def header(title):
    print()
    print("=" * 62)
    print(f"  {title}")
    print("=" * 62)


def rel(path):
    """Display path relative to the project when possible, absolute otherwise.

    Purely cosmetic -- but it runs between the backup and the write, so it
    must never raise.
    """
    try:
        return str(Path(path).relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def fail(msg):
    print(f"\nREFUSED: {msg}")
    print("Nothing was written.")
    return 1


def season_key_from_long(season_long):
    """'2025-2026' -> '2025-26'."""
    s = str(season_long).strip()
    if "-" not in s:
        return s
    start, end = s.split("-", 1)
    return f"{start}-{end[-2:]}"


def normalize_name(name):
    """Collapse case, accents and punctuation so spelling variants collide."""
    n = unicodedata.normalize("NFKD", str(name))
    n = n.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", n.lower())


def clean_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def to_date_str(v):
    ts = pd.to_datetime(v, errors="coerce")
    return "" if pd.isna(ts) else ts.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def load_slot_lookup():
    """Map (date, manager, player_name) -> roster slot, from LINEUPS.xlsx."""
    lineups = pd.read_excel(LINEUPS_XLSX)
    missing = [c for c in JOIN_KEY + ["slot"] if c not in lineups.columns]
    if missing:
        raise ValueError(f"LINEUPS.xlsx is missing columns: {missing}")
    lineups = lineups[JOIN_KEY + ["slot"]].copy()
    lineups["date"] = lineups["date"].map(to_date_str)
    lineups["manager"] = lineups["manager"].map(clean_str)
    lineups["player_name"] = lineups["player_name"].map(clean_str)
    lineups = lineups.dropna(subset=["slot"]).drop_duplicates(subset=JOIN_KEY)
    return {
        (r.date, r.manager, r.player_name): clean_str(r.slot)
        for r in lineups.itertuples(index=False)
    }


def load_player_ids(history):
    """Map player_name -> player_id using ids already in the record."""
    ids = {}
    for row in history:
        name = row.get("player_name")
        pid = row.get("player_id")
        if name and pid is not None and name not in ids:
            ids[name] = pid
    return ids


def load_canonical_names(history):
    """Map normalized name -> set of spellings used in the record."""
    by_norm = {}
    for row in history:
        name = row.get("player_name")
        if name:
            by_norm.setdefault(normalize_name(name), set()).add(name)
    return by_norm


def build_rows(season_key, history):
    """Transform PLAYERLOG.xlsx into historical-schema rows. Returns (rows, report)."""
    log = pd.read_excel(PLAYERLOG_XLSX)
    if log.empty:
        raise ValueError(
            "PLAYERLOG.xlsx has no data rows. If start_new_season.py has "
            "already run, recover the season's log from archive/<season>/data/."
        )

    slots = load_slot_lookup()
    known_ids = load_player_ids(history)
    canonical = load_canonical_names(history)

    rows = []
    report = {
        "no_slot_match": [],
        "new_players": set(),
        "is_injured_disagreements": [],
        "renamed": {},
        "ambiguous_names": {},
        "weeks": Counter(),
    }

    for r in log.to_dict("records"):
        date = to_date_str(r.get("date"))
        manager = clean_str(r.get("manager"))
        name = clean_str(r.get("player_name"))

        # Canonicalize against the record before anything keys off the name.
        if name and name not in canonical.get(normalize_name(name), set()):
            variants = canonical.get(normalize_name(name), set())
            if len(variants) == 1:
                official = next(iter(variants))
                report["renamed"].setdefault(name, official)
                name = official
            elif len(variants) > 1:
                report["ambiguous_names"][name] = sorted(variants)

        opponent = clean_str(r.get("nba_opponent"))

        try:
            fp = float(r.get("fantasy_points") or 0.0)
        except (TypeError, ValueError):
            fp = 0.0

        had_game = bool(opponent)
        derived_injured = had_game and fp == 0.0

        # PLAYERLOG carries its own is_injured; cross-check rather than trust.
        if "is_injured" in r and not pd.isna(r.get("is_injured")):
            if bool(r["is_injured"]) != derived_injured:
                report["is_injured_disagreements"].append(
                    f"{date} {manager} {name}: file={bool(r['is_injured'])} derived={derived_injured}"
                )

        slot = slots.get((date, manager, name))
        if slot is None:
            slot = ""
            report["no_slot_match"].append(f"{date} {manager} {name}")

        pid = known_ids.get(name)
        if pid is None:
            report["new_players"].add(name)

        try:
            week = int(r.get("week"))
        except (TypeError, ValueError):
            week = 0
        report["weeks"][week] += 1

        rows.append({
            "season_year": clean_str(r.get("season_year")) or CURRENT_SEASON_LONG,
            "season_key": season_key,
            "week": week,
            "date": date,
            "manager": manager,
            "fantasy_team": clean_str(r.get("fantasy_team")),
            "player_name": name,
            "player_id": pid,
            "positions": clean_str(r.get("positions")),
            "slot": slot,
            "fantasy_points": fp,
            "started": bool(r.get("started")),
            "nba_team": clean_str(r.get("nba_team")),
            "nba_opponent": opponent,
            "had_game": had_game,
            "is_injured": derived_injured,
        })

    return rows, report


def print_report(season_key, rows, report, history_len):
    header(f"ROLLUP PREVIEW -- {season_key}")
    weeks = sorted(w for w in report["weeks"] if w)
    print(f"\n  Rows to append:     {len(rows):,}")
    print(f"  Weeks covered:      {min(weeks)}-{max(weeks)} ({len(weeks)} weeks)")
    print(f"  Distinct players:   {len({r['player_name'] for r in rows})}")
    print(f"  Managers:           {', '.join(sorted({r['manager'] for r in rows}))}")
    print(f"\n  History before:     {history_len:,} rows")
    print(f"  History after:      {history_len + len(rows):,} rows")

    slot_counts = Counter(r["slot"] or "(none)" for r in rows)
    print(f"\n  Slots: {dict(slot_counts.most_common(8))}")
    print(f"  Games lost to injury (had_game + 0.0 FP): "
          f"{sum(1 for r in rows if r['is_injured']):,}")

    if report["no_slot_match"]:
        print(f"\n  WARNING: {len(report['no_slot_match'])} row(s) had no LINEUPS "
              f"match; slot left empty:")
        for line in report["no_slot_match"][:5]:
            print(f"    {line}")
        if len(report["no_slot_match"]) > 5:
            print(f"    ... and {len(report['no_slot_match']) - 5} more")

    if report["renamed"]:
        print(f"\n  CORRECTED {len(report['renamed'])} player name(s) to the "
              f"spelling already in the record:")
        for wrong, right in sorted(report["renamed"].items()):
            n = sum(1 for r in rows if r["player_name"] == right)
            print(f"    '{wrong}' -> '{right}'  ({n} row(s) now under '{right}')")
        print("    Left uncorrected, each variant would have become a separate")
        print("    player, silently splitting career totals.")

    if report["ambiguous_names"]:
        print(f"\n  WARNING: {len(report['ambiguous_names'])} name(s) matched more "
              f"than one existing spelling and were NOT changed:")
        for wrong, opts in sorted(report["ambiguous_names"].items()):
            print(f"    '{wrong}' -> {opts}")

    if report["new_players"]:
        print(f"\n  NOTE: {len(report['new_players'])} player(s) new to the record; "
              f"player_id left null:")
        for n in sorted(report["new_players"])[:8]:
            print(f"    {n}")
        if len(report["new_players"]) > 8:
            print(f"    ... and {len(report['new_players']) - 8} more")
        print("    (player_id is archival -- no engine module reads it from history)")

    if report["is_injured_disagreements"]:
        print(f"\n  WARNING: is_injured in PLAYERLOG.xlsx disagreed with the "
              f"derived value on {len(report['is_injured_disagreements'])} row(s).")
        print("    The derived value was used. Investigate if this count is large:")
        for line in report["is_injured_disagreements"][:5]:
            print(f"    {line}")


def verify_written(season_key, expected_total, expected_new):
    """Re-read the file from disk and confirm what landed."""
    with open(HISTORY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    problems = []
    if len(data) != expected_total:
        problems.append(f"row count is {len(data):,}, expected {expected_total:,}")

    season_rows = [r for r in data if r.get("season_key") == season_key]
    if len(season_rows) != expected_new:
        problems.append(
            f"{season_key} has {len(season_rows):,} rows, expected {expected_new:,}"
        )

    bad_schema = [r for r in season_rows if set(r.keys()) != set(HISTORY_FIELDS)]
    if bad_schema:
        problems.append(f"{len(bad_schema)} appended row(s) have the wrong field set")

    return problems


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Append a finished season's player log to HISTORICAL_PLAYERLOG.json"
    )
    parser.add_argument("--execute", action="store_true",
                        help="actually write (default is a dry run)")
    parser.add_argument("--force", action="store_true",
                        help="replace the season if it is already in the record")
    parser.add_argument("--season", default=None,
                        help=f"season key to roll up (default: {CURRENT_SEASON})")
    args = parser.parse_args()

    season_key = args.season or CURRENT_SEASON

    for path in (PLAYERLOG_XLSX, LINEUPS_XLSX, HISTORY_JSON):
        if not path.exists():
            return fail(f"required file not found: {rel(path)}")

    with open(HISTORY_JSON, "r", encoding="utf-8") as f:
        history = json.load(f)

    existing = sum(1 for r in history if r.get("season_key") == season_key)
    if existing and not args.force:
        return fail(
            f"{season_key} is already in HISTORICAL_PLAYERLOG.json "
            f"({existing:,} rows).\n         Use --force to replace those rows."
        )

    try:
        rows, report = build_rows(season_key, history)
    except (ValueError, KeyError) as e:
        return fail(str(e))

    if not rows:
        return fail("no rows built from PLAYERLOG.xlsx")

    base = [r for r in history if r.get("season_key") != season_key] if args.force else history
    print_report(season_key, rows, report, len(base))

    if not args.execute:
        print("\n  [DRY-RUN] Nothing written. Re-run with --execute to append.")
        print("  Run this BEFORE scripts/start_new_season.py -- Phase 2 truncates")
        print("  PLAYERLOG.xlsx to a header row.")
        return 0

    header("WRITING")
    backup = HISTORY_JSON.with_suffix(".json.bak")
    shutil.copy2(HISTORY_JSON, backup)
    print(f"\n  Backup:  {rel(backup)}")

    if args.force and existing:
        print(f"  Removed  {existing:,} existing {season_key} rows (--force)")

    merged = base + rows
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    print(f"  Wrote    {len(merged):,} rows to {rel(HISTORY_JSON)}")

    problems = verify_written(season_key, len(merged), len(rows))
    if problems:
        print("\n  VERIFICATION FAILED:")
        for p in problems:
            print(f"    - {p}")
        print(f"\n  The previous file is intact at {backup.name}. Restore it, "
              f"then investigate.")
        return 1

    print(f"  Verified {len(rows):,} {season_key} rows on disk, schema matches")
    print("\n  Next: update data/LEAGUEHISTORY.xlsx, then run")
    print("        py scripts/start_new_season.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
