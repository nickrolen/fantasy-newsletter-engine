#!/usr/bin/env python3
"""
backfill_waivers.py

Regenerate waivers_week{N}.txt files for weeks 1-14 (or any range) by pulling
all season transactions from the Yahoo Fantasy API.

This is a one-time recovery script. It does the same thing sync_transactions.py
does for a single week, but loops over a range of weeks in one shot.

The output files match the format that waiver_roi.py expects:
    - [YYYY-MM-DD] Manager: Player Name
    - [YYYY-MM-DD] Manager: Player Name (via trade)

Usage:
    # Dry run -- shows what would be written but doesn't create files
    python scripts/backfill_waivers.py

    # Actually write the files
    python scripts/backfill_waivers.py --apply

    # Custom range (e.g. just weeks 5-10)
    python scripts/backfill_waivers.py --start 5 --end 10 --apply

    # Different project root
    python scripts/backfill_waivers.py --base-path C:/Users/you/Desktop/newsletter --apply
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import unicodedata
from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import LEAGUE_KEY, TEAM_TO_MANAGER, YAHOO_GAME_CODE


# ============================================================================
# CONFIGURATION  (loaded from config/league_config.json via data_loader)
# ============================================================================

FANTASY_TEAM_TO_MANAGER = TEAM_TO_MANAGER

SCHEDULE_JSON_PATH = "config/SCHEDULE.json"
WAIVERS_DIR = "data"                      # where waiver files live
WAIVERS_FILENAME = "waivers_week{week}.txt"


# ============================================================================
# HELPERS  (copied from sync_transactions.py for standalone operation)
# ============================================================================

def strip_accents(text: str) -> str:
    """Return ASCII-only version of a name (e.g. Nikola Jokic -> Nikola Jokic)."""
    if not isinstance(text, str):
        return text
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def load_schedule(base_path: Path) -> dict:
    """Load SCHEDULE.json."""
    path = base_path / SCHEDULE_JSON_PATH
    if not path.exists():
        raise FileNotFoundError(f"SCHEDULE.json not found at {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_week_date_range(schedule: dict, week: int) -> tuple[dt.date, dt.date]:
    """Get (start_date, end_date) for a specific fantasy week."""
    for w in schedule.get("weeks", []):
        if w["week"] == week:
            start = dt.datetime.strptime(w["start_date"], "%Y-%m-%d").date()
            end = dt.datetime.strptime(w["end_date"], "%Y-%m-%d").date()
            return start, end
    raise ValueError(f"Week {week} not found in SCHEDULE.json")


# ============================================================================
# YAHOO API
# ============================================================================

def fetch_all_season_transactions(lg: yfa.League) -> list[dict]:
    """
    Pull every add/drop/trade transaction Yahoo has for the league this season.

    Returns a flat list of dicts, each representing ONE player movement:
        {
            "type": "add" | "drop",
            "player_name": str,
            "manager": str,          # e.g. "Nick"
            "date": datetime.date,
            "via": str,              # "trade", "waivers", "free_agents", "" etc.
        }

    Trades appear as paired add+drop entries; the "via" field distinguishes them
    from normal waiver claims.
    """
    # Ask Yahoo for a large batch -- 250 covers a full NBA season easily.
    # The API returns newest-first.
    raw = lg.transactions(tran_types="add,drop,trade", count=250)
    if not raw:
        return []

    print(f"  Yahoo returned {len(raw)} raw transaction bundles")

    # Show the date window we got back
    first_ts = raw[0].get("timestamp")
    last_ts = raw[-1].get("timestamp")
    if first_ts:
        print(f"  Newest: {dt.datetime.fromtimestamp(int(first_ts)).date()}")
    if last_ts:
        print(f"  Oldest: {dt.datetime.fromtimestamp(int(last_ts)).date()}")

    results = []

    for txn in raw:
        # Get the timestamp for the whole transaction bundle
        ts = txn.get("timestamp")
        txn_date = (
            dt.datetime.fromtimestamp(int(ts)).date() if ts else dt.date.today()
        )

        # Each transaction bundle can contain multiple players
        # Structure: players = {"0": {player: [[info...], {txn_data}]}, "count": N}
        players_dict = txn.get("players", {})

        for key, player_entry in players_dict.items():
            if key == "count" or not isinstance(player_entry, dict):
                continue

            player_data = player_entry.get("player", [])
            if not player_data or len(player_data) < 2:
                continue

            # First element: list of info dicts (contains name)
            info_list = player_data[0] if isinstance(player_data[0], list) else []
            # Second element: dict with transaction_data
            txn_data_wrapper = player_data[1] if len(player_data) > 1 else {}

            # --- Extract player name ---
            player_name = "Unknown"
            for info_dict in info_list:
                if isinstance(info_dict, dict) and "name" in info_dict:
                    name_data = info_dict["name"]
                    if isinstance(name_data, dict):
                        player_name = strip_accents(name_data.get("full", "Unknown"))
                    break

            # --- Extract transaction_data ---
            txn_data_raw = txn_data_wrapper.get("transaction_data", [])
            if isinstance(txn_data_raw, list) and txn_data_raw:
                txn_data = txn_data_raw[0]
            elif isinstance(txn_data_raw, dict):
                txn_data = txn_data_raw.get("0", txn_data_raw)
            else:
                txn_data = {}

            action_type = txn_data.get("type", "").lower()
            via = txn_data.get("via", "")

            # Determine which manager is involved
            if action_type == "add":
                team_name = txn_data.get("destination_team_name", "")
            elif action_type == "drop":
                team_name = txn_data.get("source_team_name", "")
            else:
                team_name = ""

            manager = FANTASY_TEAM_TO_MANAGER.get(team_name, "")

            if action_type in ("add", "drop") and manager:
                results.append({
                    "type": action_type,
                    "player_name": player_name,
                    "manager": manager,
                    "date": txn_date,
                    "via": via,  # "trade", "waivers", "free_agents", etc.
                })
            elif action_type == "trade":
                # Trades: Yahoo gives each player action_type="trade" with both
                # a destination_team (who receives) and source_team (who sends).
                # We create a synthetic "add" for the receiving manager, tagged
                # "via trade" -- same logic as sync_transactions.py lines 217-240.
                dest_team = txn_data.get("destination_team_name", "")
                dest_mgr = FANTASY_TEAM_TO_MANAGER.get(dest_team, "")
                if dest_mgr:
                    results.append({
                        "type": "add",
                        "player_name": player_name,
                        "manager": dest_mgr,
                        "date": txn_date,
                        "via": "trade",
                    })

    return results


# ============================================================================
# GROUPING + FILE WRITING
# ============================================================================

def group_by_week(
    transactions: list[dict],
    schedule: dict,
    start_week: int,
    end_week: int,
) -> dict[int, list[dict]]:
    """
    Bucket transactions into fantasy weeks based on their date.

    Returns {week_number: [transaction, ...]} for weeks in [start_week, end_week].
    Only includes ADD transactions (drops are not written to waiver files).
    """
    # Build a lookup: list of (week, start_date, end_date) tuples
    week_ranges = []
    for w in schedule.get("weeks", []):
        wk = w["week"]
        if start_week <= wk <= end_week:
            s = dt.datetime.strptime(w["start_date"], "%Y-%m-%d").date()
            e = dt.datetime.strptime(w["end_date"], "%Y-%m-%d").date()
            week_ranges.append((wk, s, e))

    # Pre-populate every week so we write "no adds" files for quiet weeks
    grouped: dict[int, list[dict]] = {wk: [] for wk, _, _ in week_ranges}

    adds_only = [t for t in transactions if t["type"] == "add"]

    for txn in adds_only:
        txn_date = txn["date"]
        for wk, s, e in week_ranges:
            if s <= txn_date <= e:
                grouped[wk].append(txn)
                break
        # Transactions outside the requested range are silently skipped

    return grouped


def write_waivers_file(
    adds: list[dict],
    week: int,
    output_dir: Path,
    dry_run: bool = True,
) -> str:
    """
    Write (or preview) a single waivers_week{N}.txt file.

    Returns the file content as a string regardless of dry_run setting.
    """
    # Sort by date, then manager name for deterministic output
    adds_sorted = sorted(adds, key=lambda t: (t["date"], t["manager"], t["player_name"]))

    lines = []
    lines.append(f"# Waiver Adds for Week {week}")
    lines.append(f"# Generated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} (backfill)")
    lines.append("")

    if adds_sorted:
        for t in adds_sorted:
            via_str = " (via trade)" if t.get("via") == "trade" else ""
            lines.append(
                f"- [{t['date']}] {t['manager']}: {t['player_name']}{via_str}"
            )
        lines.append("")
    else:
        lines.append("No waiver adds this week.")
        lines.append("")

    content = "\n".join(lines)

    if not dry_run:
        filepath = output_dir / WAIVERS_FILENAME.format(week=week)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    return content


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Backfill waivers_week{N}.txt files from Yahoo transaction history"
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default=".",
        help="Project root directory (default: current directory)",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="First week to backfill (default: 1)",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=None,  # default: process all weeks through latest in schedule
        help="Last week to backfill (default: all weeks in schedule)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write files (default: dry run / preview only)",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Overwrite waiver files that already exist (default: skip them)",
    )

    args = parser.parse_args()
    base = Path(args.base_path)
    output_dir = base / WAIVERS_DIR

    # ------------------------------------------------------------------
    # 1. Load schedule for week date ranges
    # ------------------------------------------------------------------
    print(f"Loading schedule from {base / SCHEDULE_JSON_PATH}")
    schedule = load_schedule(base)

    # Default --end to total weeks in schedule
    if args.end is None:
        args.end = schedule.get("total_weeks", len(schedule.get("weeks", [])))

    # Show the date window we'll cover
    first_start, _ = get_week_date_range(schedule, args.start)
    _, last_end = get_week_date_range(schedule, args.end)
    print(f"Backfill range: Week {args.start} ({first_start}) through Week {args.end} ({last_end})")
    print()

    # ------------------------------------------------------------------
    # 2. Connect to Yahoo and pull ALL transactions
    # ------------------------------------------------------------------
    print("Connecting to Yahoo Fantasy API...")
    oauth = OAuth2(None, None, from_file="oauth2.json")
    if not oauth.token_is_valid():
        oauth.refresh_access_token()

    lg = yfa.League(oauth, LEAGUE_KEY)
    print("Fetching all season transactions...")
    all_txns = fetch_all_season_transactions(lg)
    print(f"Total player movements parsed: {len(all_txns)}")
    print()

    # ------------------------------------------------------------------
    # 3. Group into weeks and write files
    # ------------------------------------------------------------------
    grouped = group_by_week(all_txns, schedule, args.start, args.end)

    total_adds = 0
    files_written = 0
    files_skipped = 0

    for week in sorted(grouped.keys()):
        adds = grouped[week]
        filepath = output_dir / WAIVERS_FILENAME.format(week=week)

        # Check if file already exists
        if filepath.exists() and not args.include_existing:
            print(f"  Week {week:>2}: {filepath.name} already exists -- skipping (use --include-existing to overwrite)")
            files_skipped += 1
            continue

        content = write_waivers_file(adds, week, output_dir, dry_run=not args.apply)
        count = len(adds)
        total_adds += count

        status = "WROTE" if args.apply else "PREVIEW"
        print(f"  Week {week:>2}: {count:>3} add(s)  [{status}] {filepath.name}")

        # In preview mode, show the transactions
        if not args.apply and count > 0:
            for line in content.splitlines():
                if line.startswith("- "):
                    print(f"           {line}")

        files_written += 1

    # ------------------------------------------------------------------
    # 4. Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 55)
    print(f"  Weeks processed:  {files_written}")
    print(f"  Weeks skipped:    {files_skipped}")
    print(f"  Total adds found: {total_adds}")
    if not args.apply:
        print()
        print("  This was a DRY RUN. No files were written.")
        print("  Run again with --apply to create the files.")
    else:
        print()
        print(f"  Files written to: {output_dir}")
    print("=" * 55)

    return 0


if __name__ == "__main__":
    exit(main())
