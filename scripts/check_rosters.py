#!/usr/bin/env python3
"""
check_rosters.py -- the gate on ROSTERS.json.

ROSTERS.json is built by generate_rosters.py from the week's LINEUPS, then
patched by sync_transactions.py from Yahoo's transaction log. Both steps can
leave it wrong, and nothing checked the result:

    A mid-week trade or waiver claim puts a player in BOTH managers'
    lineups for that week, so generate_rosters lists him on both rosters.
    sync_transactions is supposed to resolve it. If it does not -- a missed
    transaction, a stale token, a name it could not parse -- the player
    stays on two rosters and every simulator projects his points for two
    teams at once.

    "(Empty)" is a real value in LINEUPS when a manager leaves a roster
    slot open. It is not a player. It reached ROSTERS as one, took up a
    roster spot, matched nothing in PLAYERLIST and projected 0.0 FPPG --
    thirteen times across five weeks last season, unfiltered anywhere.

Neither failure raises anything. Both quietly change the numbers.

USAGE
    py scripts/check_rosters.py
    py scripts/check_rosters.py --strict      # warnings become failures

EXIT CODES
    0 = usable
    1 = do not generate a newsletter from this
"""

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import (  # noqa: E402
    LEAGUE_STRUCTURE, MANAGERS, normalize_player_name,
)

ROSTERS = PROJECT_ROOT / "config" / "ROSTERS.json"
PLAYERLIST = PROJECT_ROOT / "data" / "PLAYERLIST.xlsx"

# Anything matching these is a slot state, not a person.
PLACEHOLDER = re.compile(
    r"^\s*$|^\(?\s*empty\s*\)?$|^--+$|^n/?a$|^none$|^tbd$|^\(?\s*open\s*\)?$",
    re.IGNORECASE,
)


def expected_roster_size() -> int:
    """Every roster spot including IL -- that is what a lineup week shows."""
    return int(LEAGUE_STRUCTURE.get("roster_size", 17))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate ROSTERS.json.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat warnings as failures.")
    args = ap.parse_args()

    print("=" * 66)
    print("  CHECK ROSTERS")
    print("=" * 66)
    print()

    failures, warnings = [], []

    if not ROSTERS.is_file():
        print("  config/ROSTERS.json does not exist.")
        print("  Run: py scripts/generate_rosters.py --week N")
        return 1

    try:
        payload = json.loads(ROSTERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  config/ROSTERS.json is unreadable: {type(e).__name__}: {e}")
        return 1

    rosters = payload.get("rosters", {})
    if not rosters:
        print("  ROSTERS.json has no rosters. Before the draft this is")
        print("  expected; during the season it is not.")
        return 0

    size = expected_roster_size()
    print(f"  {len(rosters)} rosters, expecting {size} players each")
    print()

    # --- every player belongs to exactly one manager ---------------------
    owners = {}
    for manager, players in rosters.items():
        for player in players:
            owners.setdefault(normalize_player_name(player), []).append(
                (manager, player))
    for _, holders in sorted(owners.items()):
        if len(holders) > 1:
            who = ", ".join(f"{m} ({p})" for m, p in holders)
            failures.append(
                f"{holders[0][1]} is on {len(holders)} rosters: {who}. A "
                f"mid-week move that sync_transactions did not resolve; every "
                f"simulator will project him for both teams.")

    # --- placeholders are not players ------------------------------------
    for manager, players in sorted(rosters.items()):
        for player in players:
            if PLACEHOLDER.match(str(player)):
                failures.append(
                    f"{manager} has {player!r} as a roster entry. That is an "
                    f"empty lineup slot, not a player; it occupies a spot and "
                    f"projects 0.0 FPPG.")

    # --- roster sizes ------------------------------------------------------
    for manager, players in sorted(rosters.items()):
        if len(players) != size:
            (failures if abs(len(players) - size) > 2 else warnings).append(
                f"{manager} has {len(players)} players, expected {size}.")

    # --- every manager accounted for ---------------------------------------
    missing = [m for m in MANAGERS if m not in rosters]
    if missing:
        failures.append(f"no roster for: {', '.join(missing)}")
    unknown = [m for m in rosters if m not in MANAGERS]
    if unknown:
        failures.append(f"roster for unknown manager(s): {', '.join(unknown)}")

    # --- projections exist for rostered players ----------------------------
    if PLAYERLIST.is_file():
        try:
            import pandas as pd
            frame = pd.read_excel(PLAYERLIST)
            known = {normalize_player_name(n) for n in frame["player_name"]}
            unmatched = []
            for manager, players in sorted(rosters.items()):
                for player in players:
                    if PLACEHOLDER.match(str(player)):
                        continue
                    if normalize_player_name(player) not in known:
                        unmatched.append(f"{player} ({manager})")
            if unmatched:
                warnings.append(
                    f"{len(unmatched)} rostered player(s) are not in "
                    f"PLAYERLIST, so they project 0.0 FPPG: "
                    f"{unmatched[:6]}{' ...' if len(unmatched) > 6 else ''}")
        except Exception as e:
            warnings.append(f"could not cross-check PLAYERLIST: "
                            f"{type(e).__name__}: {e}")

    for manager, players in sorted(rosters.items()):
        print(f"    {manager:<9} {len(players)} players")
    print()

    if args.strict:
        failures, warnings = failures + warnings, []

    if warnings:
        print(f"  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")
        print()
    if failures:
        print(f"  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    - {f}")
        print()
        print("  RESULT: DO NOT generate a newsletter from this file.")
        print("  Re-run: py scripts/sync_transactions.py --week N --apply")
        print("  Or edit config/ROSTERS.json by hand.")
        return 1

    print(f"  RESULT: usable."
          f"{f' {len(warnings)} warning(s).' if warnings else ''}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
