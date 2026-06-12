#!/usr/bin/env python3
"""
start_new_season.py -- Season-reset lifecycle script.

Archives the current season's working files, resets per-season configs to
empty defaults, and removes the now-archived outputs from the working dirs.

SAFE BY DEFAULT: runs in dry-run mode unless --execute is passed.
Cross-platform: uses pathlib.Path and shutil only (no OS-specific commands).

Usage:
    py scripts/start_new_season.py              # dry-run (shows plan, changes nothing)
    py scripts/start_new_season.py --execute    # actually perform the reset
    py scripts/start_new_season.py --execute --force  # overwrite existing archive folder
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root (one level up from scripts/)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# ---------------------------------------------------------------------------
# Files the script must NEVER touch
# ---------------------------------------------------------------------------
PROTECTED_PATHS = {
    "config/league_config.json",         # manual edit only
    "data/LEAGUEHISTORY.xlsx",           # permanent historical record (archived as snapshot, never modified)
}
PROTECTED_DIRS = {
    "data/historical",                   # append-only historical archive
}

def is_protected(rel_path_str: str) -> bool:
    """Return True if a path falls under the protected list."""
    normed = rel_path_str.replace("\\", "/")
    if normed in PROTECTED_PATHS:
        return True
    for d in PROTECTED_DIRS:
        if normed.startswith(d + "/") or normed == d:
            return True
    return False

def is_nba_schedule(rel_path_str: str) -> bool:
    """Return True for NBA schedule data files (never touched by reset)."""
    normed = rel_path_str.replace("\\", "/")
    return normed.startswith("data/nba_schedule_")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load league_config.json and return the parsed dict."""
    config_path = PROJECT_ROOT / "config" / "league_config.json"
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def collect_glob(pattern: str) -> list[Path]:
    """Glob relative to PROJECT_ROOT and return sorted list of matching paths."""
    return sorted(PROJECT_ROOT.glob(pattern))


def rel(path: Path) -> str:
    """Return a clean relative path string from PROJECT_ROOT."""
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def verify_copy(src: Path, dst: Path) -> bool:
    """Verify that dst exists and has the same size as src."""
    if not dst.exists():
        return False
    return src.stat().st_size == dst.stat().st_size


def print_header(title: str) -> None:
    """Print a bold section header."""
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_file_list(label: str, paths: list[Path]) -> None:
    """Print a labeled list of files with count."""
    print(f"\n  {label} ({len(paths)} file{'s' if len(paths) != 1 else ''}):")
    for p in paths:
        print(f"    {rel(p)}")


# ---------------------------------------------------------------------------
# Phase 1: ARCHIVE
# ---------------------------------------------------------------------------

def get_archive_files() -> list[Path]:
    """Collect all files to be archived."""
    patterns = [
        "output/stats_report_week*.json",
        "output/stats_report_week*.md",
        "output/looking_ahead_week*.json",
        "output/*.html",
        "assets/WEEK*_DRAFT.md",
        "config/snapshots/*",
        "data/waivers_week*.txt",
    ]
    single_files = [
        "config/POTW_HISTORY.json",
        "config/RECENT_CONTENT.json",
        "config/ROSTERS.json",
        "config/TRADES.json",
        "config/INJURY_OVERRIDES.json",
        "config/RECORDS.json",
        "config/league_config.json",    # snapshot copy (original is never modified)
        "data/LEAGUEHISTORY.xlsx",      # snapshot copy (original is never modified)
        # Season data files -- MUST be archived before Phase 2 wipes them.
        # If these are missing from the archive and the user hasn't already rolled
        # them into data/historical/, the season's raw data is permanently lost.
        "data/PLAYERLOG.xlsx",          # daily player stat lines
        "data/LINEUPS.xlsx",            # slot-level lineup history (bench/injury metrics)
        "data/PLAYERLIST.xlsx",         # projection snapshot for the season
    ]

    files = []
    for pat in patterns:
        files.extend(collect_glob(pat))

    for sf in single_files:
        p = PROJECT_ROOT / sf
        if p.exists():
            files.append(p)

    # Deduplicate (in case glob patterns overlap) and sort
    files = sorted(set(files))
    return files


def archive_phase(season: str, archive_dir: Path, execute: bool, force: bool) -> bool:
    """Copy files into archive/<season>/. Returns True on success."""
    files = get_archive_files()

    print_header(f"PHASE 1: ARCHIVE  ->  archive/{season}/")

    if not files:
        print("\n  No files found to archive.")
        return True

    if archive_dir.exists() and not force:
        print(f"\n  ERROR: Archive directory already exists: {rel(archive_dir)}")
        print("  Use --force to overwrite.")
        return False

    print(f"\n  Archive target: {rel(archive_dir)}")
    print_file_list("Files to archive", files)

    if not execute:
        print(f"\n  [DRY-RUN] Would archive {len(files)} files.")
        return True

    # Create archive dir
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Copy each file preserving subfolder structure
    failed = []
    for src in files:
        rel_path = src.relative_to(PROJECT_ROOT)
        dst = archive_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        if not verify_copy(src, dst):
            failed.append((src, dst))

    if failed:
        print("\n  ARCHIVE VERIFICATION FAILED for:")
        for src, dst in failed:
            print(f"    {rel(src)} -> {dst}")
        print("\n  ABORTING. No files have been reset or deleted.")
        return False

    print(f"\n  OK -- Archived {len(files)} files. All copies verified.")
    return True


# ---------------------------------------------------------------------------
# Phase 2: RESET
# ---------------------------------------------------------------------------

def reset_recent_content(execute: bool) -> None:
    """Reset RECENT_CONTENT.json to empty schema."""
    path = PROJECT_ROOT / "config" / "RECENT_CONTENT.json"
    empty = {"fun_facts": {}, "trade_ideas": {}, "free_agent_recs": {}}
    if execute:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)
        print(f"    OK  {rel(path)}")
    else:
        print(f"    {rel(path)} -> empty (3 keys, all empty dicts)")


def reset_potw_history(execute: bool) -> None:
    """Reset POTW_HISTORY.json to empty schema."""
    path = PROJECT_ROOT / "config" / "POTW_HISTORY.json"
    empty = {
        "_comment": "All-time Player of the Week history. The formatter reads this at startup and appends the current week's winner after each run. Organized by NBA season.",
        "seasons": {}
    }
    if execute:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)
        print(f"    OK  {rel(path)}")
    else:
        print(f"    {rel(path)} -> empty seasons dict")


def reset_injury_overrides(execute: bool) -> None:
    """Reset INJURY_OVERRIDES.json to empty schema."""
    path = PROJECT_ROOT / "config" / "INJURY_OVERRIDES.json"
    empty = {"players": [], "last_updated": ""}
    if execute:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)
        print(f"    OK  {rel(path)}")
    else:
        print(f"    {rel(path)} -> empty players list")


def reset_rosters(execute: bool) -> None:
    """Reset ROSTERS.json to empty schema."""
    path = PROJECT_ROOT / "config" / "ROSTERS.json"
    empty = {
        "_comment": "Current season rosters. Generated by generate_rosters.py or sync_transactions.py.",
        "_generated_from_week": None,
        "rosters": {},
        "_last_sync": None
    }
    if execute:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)
        print(f"    OK  {rel(path)}")
    else:
        print(f"    {rel(path)} -> empty rosters dict")


def reset_trades(execute: bool) -> None:
    """Reset TRADES.json to empty schema."""
    path = PROJECT_ROOT / "config" / "TRADES.json"
    empty = {
        "_description": "Trade log and draft pick ownership tracker. Updated after each trade.",
        "_usage": "Used by modules/records_tracker.py and scripts/format_stats_report.py.",
        "_rolling_window_rule": "Draft pick ownership tracks a rolling 3-year window.",
        "trades": [],
        "draft_pick_ownership": {}
    }
    if execute:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(empty, f, indent=2)
        print(f"    OK  {rel(path)}")
    else:
        print(f"    {rel(path)} -> empty trades list and draft_pick_ownership")


def reset_records(execute: bool) -> None:
    """Reset RECORDS.json: preserve all_time + team_name_history, reset current-season sections."""
    path = PROJECT_ROOT / "config" / "RECORDS.json"
    if not path.exists():
        print(f"    SKIP {rel(path)} -- file not found")
        return

    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)

    # Keys we KNOW are all-time / historical -- PRESERVE these
    all_time_keys = {"all_time", "team_name_history"}

    # Keys we KNOW are current-season -- RESET these
    current_season_keys = {
        "season_records",       # current season records
        "h2h_season",           # current season head-to-head
        "manager_season_totals",# current season totals
        "weekly_scores",        # current season weekly scores
        "season_fppg_stats",    # current season FPPG
        "cumulative_blunders",  # current season blunders
        "single_week_blunders_high",  # current season blunder highs
        "last_updated_week",    # reset to 0
    }

    # Any key not in either set -> preserve + warn
    unknown_keys = set(records.keys()) - all_time_keys - current_season_keys

    if execute:
        new_records = {}
        for k in records:
            if k in all_time_keys:
                new_records[k] = records[k]
            elif k == "last_updated_week":
                new_records[k] = 0
            elif k in current_season_keys:
                new_records[k] = {}
            else:
                # Unknown key -- preserve it for safety
                new_records[k] = records[k]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(new_records, f, indent=2)
        print(f"    OK  {rel(path)} (preserved all_time + team_name_history, reset {len(current_season_keys)} season sections)")
    else:
        print(f"    {rel(path)}:")
        print(f"      PRESERVE: {', '.join(sorted(all_time_keys))}")
        print(f"      RESET:    {', '.join(sorted(current_season_keys))}")

    if unknown_keys:
        print(f"    WARNING -- Unknown keys preserved for manual review: {', '.join(sorted(unknown_keys))}")


def reset_excel(filename: str, headers: list[str], execute: bool) -> None:
    """Clear data rows from an Excel file, keeping only the header row."""
    path = PROJECT_ROOT / "data" / filename
    if not path.exists():
        print(f"    SKIP data/{filename} -- file not found")
        return

    if execute:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        wb.save(path)
        wb.close()
        print(f"    OK  data/{filename} (header only, 0 data rows)")
    else:
        print(f"    data/{filename} -> header row preserved, all data rows cleared")


def reset_phase(execute: bool) -> None:
    """Reset per-season config files to empty defaults."""
    print_header("PHASE 2: RESET per-season files to empty defaults")

    if not execute:
        print("\n  [DRY-RUN] The following files would be reset:\n")
    else:
        print()

    reset_recent_content(execute)
    reset_potw_history(execute)
    reset_injury_overrides(execute)
    reset_rosters(execute)
    reset_trades(execute)
    reset_records(execute)

    playerlog_headers = [
        "season_year", "week", "date", "manager", "fantasy_team",
        "player_name", "nba_team", "positions", "nba_opponent",
        "fantasy_points", "opponent_manager", "source", "notes",
        "is_injured", "started"
    ]
    reset_excel("PLAYERLOG.xlsx", playerlog_headers, execute)

    lineups_headers = [
        "season_year", "week", "date", "manager", "fantasy_team",
        "player_name", "nba_team", "positions", "slot", "nba_opponent",
        "fantasy_points", "source", "notes", "opponent_manager"
    ]
    reset_excel("LINEUPS.xlsx", lineups_headers, execute)


# ---------------------------------------------------------------------------
# Phase 3: DELETE archived output files from working dirs
# ---------------------------------------------------------------------------

def get_delete_files() -> list[Path]:
    """Collect per-season output files to delete (now safely in archive)."""
    patterns = [
        "output/stats_report_week*.json",
        "output/stats_report_week*.md",
        "output/looking_ahead_week*.json",
        "output/*.html",
        "assets/WEEK*_DRAFT.md",
        "config/snapshots/*",
        "data/waivers_week*.txt",
    ]
    files = []
    for pat in patterns:
        files.extend(collect_glob(pat))
    return sorted(set(files))


def delete_phase(execute: bool) -> None:
    """Remove archived per-season output files from working directories."""
    files = get_delete_files()

    print_header("PHASE 3: DELETE archived output files from working dirs")

    if not files:
        print("\n  No output files to delete.")
        return

    print_file_list("Files to delete", files)

    if not execute:
        print(f"\n  [DRY-RUN] Would delete {len(files)} files.")
        return

    for f in files:
        f.unlink()
    print(f"\n  OK -- Deleted {len(files)} files.")


# ---------------------------------------------------------------------------
# Manual checklist
# ---------------------------------------------------------------------------

def print_manual_checklist(season: str) -> None:
    """Print the manual steps the script deliberately does not automate."""
    print_header("MANUAL STEPS TO COMPLETE THE NEW SEASON SETUP")
    print(f"""
  !!! READ FIRST -- DATA LOSS WARNING !!!

  BEFORE running with --execute, complete these steps. Phase 2 truncates
  PLAYERLOG.xlsx and LINEUPS.xlsx to header-only; the archive copies them, but
  the *permanent* historical record lives elsewhere and must be updated by hand:

    1. Append PLAYERLOG data to data/historical/HISTORICAL_PLAYERLOG.json
    2. Append final standings to data/historical/all_standings.json
    3. Update data/LEAGUEHISTORY.xlsx with final records/titles

  AFTER the reset (the script has archived season {season} and reset working files):

    4. Edit config/league_config.json:
       - season.current          -> new season (e.g. "2026-27")
       - season.current_long     -> new long form (e.g. "2026-2027")
       - season.season_number    -> increment by 1
       - yahoo.current_league_key -> new Yahoo league ID for the new season
       - yahoo.historical_league_keys -> add "{season}" with its league key
       - season.nba_schedule_file -> new filename (e.g. "data/nba_schedule_2026-27.json")
       - manager_to_team         -> update if any team names changed

    5. Fetch the new NBA schedule:
       py scripts/fetch_nba_schedule.py --season <new> --output data/nba_schedule_<new>.json

    6. Create config/SCHEDULE.json for the new season (matchups + dates)

    7. Run the draft pull once the draft happens:
       py scripts/pull_current_draft.py
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive the current season and prepare the project for a new one.",
        epilog="DEFAULT: dry-run mode. Pass --execute to actually perform the reset."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the archive/reset/delete (default: dry-run only)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting an existing archive/<season>/ folder"
    )
    args = parser.parse_args()

    execute = args.execute
    force = args.force

    # Load config
    config = load_config()
    season = config["season"]["current"]

    archive_dir = PROJECT_ROOT / "archive" / season

    # Banner
    mode = "EXECUTE MODE" if execute else "DRY-RUN MODE (no changes will be made)"
    print()
    print("*" * 60)
    print(f"  SEASON RESET -- {mode}")
    print(f"  Archiving season: {season}")
    print(f"  Archive target:   archive/{season}/")
    print("*" * 60)

    if not execute:
        print("\n  This is a preview. Pass --execute to perform the reset.")

    # Phase 1: Archive
    ok = archive_phase(season, archive_dir, execute, force)
    if not ok:
        print("\n  ABORTED -- archive phase failed. No files were modified.")
        sys.exit(1)

    # Phase 2: Reset
    reset_phase(execute)

    # Phase 3: Delete
    delete_phase(execute)

    # Manual checklist (always printed)
    print_manual_checklist(season)

    # Summary
    if execute:
        print("=" * 60)
        print("  SEASON RESET COMPLETE")
        print(f"  Archived season {season} -> archive/{season}/")
        print("  Per-season files reset to empty defaults.")
        print("  Follow the manual checklist above to finish setup.")
        print("=" * 60)
    else:
        print("=" * 60)
        print("  DRY-RUN COMPLETE -- no files were modified.")
        print("  Review the plan above, then run with --execute to proceed.")
        print("=" * 60)
    print()


if __name__ == "__main__":
    main()
