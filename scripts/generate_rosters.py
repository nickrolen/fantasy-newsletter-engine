#!/usr/bin/env python3
"""
generate_rosters.py

Generate config/ROSTERS.json from LINEUPS data as a starting point.
Run this before generate_stats_report.py, then manually edit ROSTERS.json
to reflect any waiver moves that happened after the last game day.

Usage:
    python scripts/generate_rosters.py
    python scripts/generate_rosters.py --week 12  # Use specific week instead of most recent
    python scripts/generate_rosters.py --from-draft   # week-1 rosters, from the draft

--from-draft exists because LINEUPS is empty between the season reset and
week 1, so there was no path to opening-day rosters: on 2026-10-12 they were
built from DRAFT_PICKS_CURRENT.json by hand. It refuses once LINEUPS has any
rows -- by then waivers and trades have moved the rosters past the draft.

AFTER THE NEXT WINDOW HAS CLOSED, IT REFUSES (5g, 11-25). --week N rebuilds
ROSTERS.json from week N's lineups. Run after week N+1's Monday window has
closed (price_lock.window_close), that drops every move made in the window
(on 11-24 it would have removed Nick's Durant-for-Daniels move). The cloud
keeps ROSTERS.json current then: the closing run syncs it right after the
close, and the nightly every night. --force rebuilds anyway, with a warning.
"""

import argparse
import sys
import json
import re
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.data_loader import (
    CURRENT_SEASON, LEAGUE_STRUCTURE, MANAGERS, load_all_data,
)
from modules.league_clock import league_now
from modules.price_lock import window_close as _window_close


class RostersAfterClose(RuntimeError):
    """--week N after week N+1's Monday window has closed (5g s.3)."""


def check_not_after_close(week: int, weeks: list, nba_schedule, *, now, window_close=_window_close):
    """Raise RostersAfterClose when `now` (the league clock) is at or past the
    close of week `week`+1's Monday window: rebuilding ROSTERS.json from week
    `week`'s lineups then drops every move made in that window. None when
    there is no week N+1 in the schedule, or it has not closed yet.
    weeks: SCHEDULE.json's week entries; nba_schedule: the tip times."""
    if now.tzinfo is None:
        raise ValueError("check_not_after_close needs the league clock (an aware time)")
    nxt = next((w for w in weeks if int(w["week"]) == int(week) + 1), None)
    if nxt is None:
        return None
    from datetime import date as _date
    monday = _date.fromisoformat(str(nxt["start_date"])[:10])
    if now.date() < monday:
        return None
    close = window_close(monday, nba_schedule)
    if now < close:
        return None
    raise RostersAfterClose(
        f"week {int(week) + 1}'s window closed {close.isoformat(timespec='minutes')} (it is "
        f"{now.isoformat(timespec='minutes')}): rebuilding config/ROSTERS.json from week {week}'s "
        f"lineups would drop every move made in that window. The cloud keeps ROSTERS.json current: "
        f"the closing run syncs it right after the close, and the nightly every night, so after a "
        f"pull it is already right (python scripts\\state.py pull). Skip Step 3. To rebuild "
        f"anyway: --force.")


def _guard_inputs(base_path: Path):
    """(SCHEDULE.json's weeks, the NBA schedule with tip times) for the guard."""
    from modules.data_loader import NBA_SCHEDULE_FILE, load_nba_schedule
    from modules.nba_schedule import schedule_path
    weeks = json.loads((base_path / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))["weeks"]
    if not NBA_SCHEDULE_FILE:
        raise RostersAfterClose("league_config season.nba_schedule_file is not set: the window's "
                                "close cannot be placed")
    return weeks, load_nba_schedule(schedule_path(base_path))


class DraftRosterError(ValueError):
    """The draft file cannot be turned into opening-day rosters."""


def rosters_from_draft(blob: dict, season: str, managers, rounds: int) -> dict:
    """{manager: sorted player names} from DRAFT_PICKS_CURRENT.json.

    Every check raises; none of them defaults. A short draft, a stale file
    from last season or a manager with the wrong pick count would otherwise
    become a plausible-looking roster.
    """
    if str(blob.get("season")) != str(season):
        raise DraftRosterError(
            f"DRAFT_PICKS_CURRENT.json is for {blob.get('season')!r}, the "
            f"current season is {season!r}. Rebuild it after this season's draft.")
    picks = blob.get("picks") or []
    rosters = {m: [] for m in managers}
    for pick in picks:
        manager, name = pick.get("manager"), str(pick.get("player_name") or "").strip()
        if manager not in rosters:
            raise DraftRosterError(f"pick {pick.get('pick_number')} is for "
                                   f"unknown manager {manager!r}")
        if not name or _is_placeholder(name):
            raise DraftRosterError(f"pick {pick.get('pick_number')} has no player")
        rosters[manager].append(name)
    short = {m: len(p) for m, p in rosters.items() if len(p) != rounds}
    if short:
        raise DraftRosterError(
            f"every manager drafts {rounds} (keepers included); got {short}")
    seen = {}
    for m, players in rosters.items():
        for name in players:
            if name in seen:
                raise DraftRosterError(f"{name} was picked by both {seen[name]} and {m}")
            seen[name] = m
    return {m: sorted(p) for m, p in rosters.items()}


PLACEHOLDER_SLOT = re.compile(
    r"^\s*$|^\(?\s*empty\s*\)?$|^--+$|^n/?a$|^none$|^tbd$|^\(?\s*open\s*\)?$",
    re.IGNORECASE,
)


def _is_placeholder(name) -> bool:
    """True for a lineup token that records an empty slot, not a player."""
    return bool(PLACEHOLDER_SLOT.match(str(name)))


def write_rosters(base_path: Path, new_rosters: dict, show_diff: bool,
                  header: dict) -> Path:
    """Show the diff against the existing file if asked, then write."""
    rosters_file = base_path / "config" / "ROSTERS.json"
    if show_diff and rosters_file.exists():
        old_rosters = json.loads(
            rosters_file.read_text(encoding="utf-8")).get("rosters", {})
        print("\n=== CHANGES FROM EXISTING ROSTERS.json ===")
        has_changes = False
        for manager in MANAGERS:
            old_set = set(old_rosters.get(manager, []))
            new_set = set(new_rosters.get(manager, []))
            added, removed = new_set - old_set, old_set - new_set
            if added or removed:
                has_changes = True
                print(f"\n{manager}:")
                for player in sorted(added):
                    print(f"  + {player}")
                for player in sorted(removed):
                    print(f"  - {player}")
        if not has_changes:
            print("  No changes detected")
        print()
    output = dict(header)
    output["rosters"] = new_rosters
    rosters_file.parent.mkdir(parents=True, exist_ok=True)
    rosters_file.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Generated: {rosters_file}")
    print()
    for manager, players in new_rosters.items():
        print(f"  {manager}: {len(players)} players")
    print()
    return rosters_file


def build_from_draft(base_path: Path, show_diff: bool) -> int:
    lineups = base_path / "data" / "LINEUPS.xlsx"
    if lineups.exists():
        import pandas as pd
        rows = len(pd.read_excel(lineups))
        if rows:
            print(f"REFUSED: LINEUPS has {rows} rows, so the season has started "
                  f"and rosters have moved past the draft. Use --week N.")
            return 1
    draft = base_path / "config" / "DRAFT_PICKS_CURRENT.json"
    blob = json.loads(draft.read_text(encoding="utf-8"))
    rounds = int(LEAGUE_STRUCTURE["total_rounds"])
    try:
        rosters = rosters_from_draft(blob, CURRENT_SEASON, MANAGERS, rounds)
    except DraftRosterError as e:
        print(f"REFUSED: {e}")
        return 1
    write_rosters(base_path, rosters, show_diff, {
        "_comment": (f"Opening-day rosters for {CURRENT_SEASON}, built from "
                     f"DRAFT_PICKS_CURRENT.json by generate_rosters.py "
                     f"--from-draft (LINEUPS is empty before week 1)."),
        "_generated_from_week": None,
        "_generated_from": "draft",
    })
    print("Next: python scripts/check_rosters.py")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate config/ROSTERS.json from LINEUPS data"
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default=".",
        help="Base path to project directory (default: current directory)",
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Use lineups from specific week (default: most recent week)",
    )
    parser.add_argument(
        "--from-draft",
        action="store_true",
        help="Build opening-day rosters from config/DRAFT_PICKS_CURRENT.json "
             "(only while LINEUPS is still empty)",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Show differences from existing ROSTERS.json (if it exists)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even after week N+1's Monday window has closed (drops every move "
             "made in that window; the cloud keeps ROSTERS.json current, 5g)",
    )

    args = parser.parse_args(argv)
    base_path = Path(args.base_path)

    if args.from_draft:
        return build_from_draft(base_path, args.show_diff)

    data = None
    if args.week:
        target_week = args.week
    else:
        print("Loading LINEUPS data...")
        data = load_all_data(base_path)
        if data.lineups.empty:
            print("ERROR: LINEUPS is empty, so there is no week to build from.")
            print("  Before week 1: python scripts/generate_rosters.py --from-draft")
            return 1
        target_week = int(data.lineups['week'].max())

    # 5g s.3: never after week N+1's window has closed, unless --force
    weeks, nba = _guard_inputs(base_path)
    try:
        check_not_after_close(target_week, weeks, nba, now=league_now(), window_close=_window_close)
    except RostersAfterClose as e:
        if not args.force:
            print(f"REFUSED: {e}")
            return 1
        print(f"WARNING (--force): {e}")
        print("  Rebuilding anyway: re-enter the window's moves (or pull) before Step 6.")
    return generate_rosters(base_path, target_week, args.show_diff, data=data)


def generate_rosters(base_path: Path, target_week: int, show_diff: bool, data=None) -> int:
    """Rebuild config/ROSTERS.json from week `target_week`'s lineups."""
    if data is None:
        print("Loading LINEUPS data...")
        data = load_all_data(base_path)
    print(f"Using lineups from week {target_week}")
    
    # Filter to target week
    week_lineups = data.lineups[data.lineups['week'] == target_week]
    
    if week_lineups.empty:
        print(f"ERROR: No lineups found for week {target_week}")
        return 1
    
    # Build rosters
    #
    # "(Empty)" is what LINEUPS records when a manager leaves a roster slot
    # open -- 13 rows across 5 weeks last season. It is a slot state, not a
    # person, and it used to come straight through into ROSTERS.json, where
    # it took a roster spot, matched nothing in PLAYERLIST and projected
    # 0.0 FPPG. Nothing downstream filtered it.
    new_rosters = {}
    dropped = []
    for manager in MANAGERS:
        players = week_lineups[
            week_lineups['manager'] == manager
        ]['player_name'].unique().tolist()
        real = [p for p in players if not _is_placeholder(p)]
        dropped += [(manager, p) for p in players if _is_placeholder(p)]
        new_rosters[manager] = sorted(real)

    if dropped:
        print(f"\n  Ignored {len(dropped)} empty lineup slot(s):")
        for manager, token in dropped:
            print(f"    {manager}: {token!r}")
    
    write_rosters(base_path, new_rosters, show_diff, {
        "_comment": f"Edit this file to reflect current rosters before running simulations. Auto-generated from LINEUPS week {target_week}",
        "_generated_from_week": target_week,
    })

    print("Next steps:")
    print("  1. Edit config/ROSTERS.json to add any waiver pickups")
    print("  2. Edit config/ROSTERS.json to remove any dropped players")
    print("  3. Run: python scripts/generate_stats_report.py --week <N>")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
