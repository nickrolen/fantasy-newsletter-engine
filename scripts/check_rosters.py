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
    IL_SLOTS, LEAGUE_STRUCTURE, MANAGERS, PlayerIndex,
)

ROSTERS = PROJECT_ROOT / "config" / "ROSTERS.json"
PLAYERLIST = PROJECT_ROOT / "data" / "PLAYERLIST.xlsx"
LINEUPS = PROJECT_ROOT / "data" / "LINEUPS.xlsx"

# Anything matching these is a slot state, not a person.
PLACEHOLDER = re.compile(
    r"^\s*$|^\(?\s*empty\s*\)?$|^--+$|^n/?a$|^none$|^tbd$|^\(?\s*open\s*\)?$",
    re.IGNORECASE,
)


def active_spots() -> int:
    """Starters plus bench: the spots every roster fills. Read, never defaulted."""
    return int(LEAGUE_STRUCTURE["starters"]) + int(LEAGUE_STRUCTURE["bench"])


def expected_roster_size(on_il: int = 0) -> int:
    """15 active spots, plus each player actually sitting in an IL slot.

    This used to return roster_size, 17, "including IL". That is right for a
    lineup week and wrong for a roster: an IL slot only takes an IL-tagged
    player, and an empty one is not a roster spot anybody holds. So it
    warned on all four teams every preseason (15 players, "expected 17"),
    and a warning that is always there is one nobody reads.
    """
    il_slots = int(LEAGUE_STRUCTURE["il_slots"])
    if on_il < 0:
        raise ValueError(on_il)
    return active_spots() + min(on_il, il_slots)


def live_il_names(oauth_file=None) -> dict:
    """{manager: [players in an IL slot right now]}, from Yahoo's live rosters
    (lg.to_team(key).roster(), the selected_position update_fantasy_logs
    reads). Managers resolved by team KEY, which survives a rename. Raises
    when the league cannot be reached; the caller falls back and says so."""
    from modules.fetch_injury_statuses import OAuth2, YAHOO_API_AVAILABLE, get_league, strip_accents
    from modules.data_loader import manager_for_team
    from modules.yahoo_auth import build_oauth
    if not YAHOO_API_AVAILABLE:
        raise RuntimeError("yahoo_oauth / yahoo_fantasy_api are not installed")
    oauth_file = Path(oauth_file or PROJECT_ROOT / "oauth2.json")
    if not oauth_file.is_file():
        raise RuntimeError(f"no {oauth_file.name}")
    lg = get_league(build_oauth(str(oauth_file), OAuth2=OAuth2))
    out = {}
    for key, team in lg.teams().items():
        manager = manager_for_team(team["name"], key, base_path=PROJECT_ROOT)
        out[manager] = [strip_accents(p["name"]) for p in lg.to_team(key).roster()
                        if str(p.get("selected_position", "")).upper() in IL_SLOTS]
    return out


def players_on_il(rosters: dict, lineups=None, live=None) -> tuple:
    """({manager: rostered players in an IL slot}, where that came from).

    live: {manager: [names in an IL slot now]} (live_il_names) -- TODAY's IL,
    and the source whenever the league is reachable. Without it, the latest
    day in LINEUPS, which only exists for weeks already played: an IL move
    made today is invisible to it. On 10-26 that warned Garrett and Nick had
    16 players "with 0 in an IL slot" when Flagg, Knueppel and Banchero had
    all gone to IL that morning (HANDOFF_STALE_GATES sec.3). So the source is
    always named, and the fallback says what it cannot see.

    ROSTERS.json is names only. A player who has since left the roster does
    not count, whichever source.
    """
    out = {m: 0 for m in rosters}
    if live is not None:
        for manager, players in rosters.items():
            on_roster = PlayerIndex({p: 1 for p in players})
            out[manager] = sum(1 for n in live.get(manager, []) if n in on_roster)
        return out, "the live Yahoo roster"
    if lineups is None:
        if not LINEUPS.is_file():
            return out, "nothing (no live roster and no LINEUPS.xlsx): nobody counted on IL"
        import pandas as pd
        lineups = pd.read_excel(LINEUPS)
        from modules.transaction_rulings import apply_effective_dates
        lineups = apply_effective_dates(lineups, LINEUPS.parent.parent, "lineups")
    if lineups is None or len(lineups) == 0:
        return out, "nothing (no live roster and LINEUPS is empty): nobody counted on IL"
    latest_day = str(lineups["date"].astype(str).max())[:10]
    for manager, players in rosters.items():
        rows = lineups[lineups["manager"] == manager]
        if rows.empty:
            continue
        latest = rows[rows["date"].astype(str) == rows["date"].astype(str).max()]
        il_names = latest[latest["slot"].astype(str).str.upper().isin(IL_SLOTS)]
        on_roster = PlayerIndex({p: 1 for p in players})
        out[manager] = sum(1 for n in il_names["player_name"] if n in on_roster)
    return out, (f"the latest lineup in LINEUPS.xlsx ({latest_day}) -- IL moves made "
                 "after it are not seen")


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

    try:
        live, live_problem = live_il_names(), None
    except Exception as e:
        live, live_problem = None, f"{type(e).__name__}: {e}"
    on_il, il_source = players_on_il(rosters, live=live)
    print(f"  {len(rosters)} rosters, expecting {active_spots()} active players "
          f"each, plus any in an IL slot")
    print(f"  IL membership from {il_source}")
    if live_problem:
        print(f"    (the live roster was not reachable: {live_problem})")
    print()

    # --- every player belongs to exactly one manager ---------------------
    owners, seen = {}, PlayerIndex()
    for manager, players in rosters.items():
        for player in players:
            canonical = seen.get(player)
            if canonical is None:
                seen[player] = canonical = player
            owners.setdefault(canonical, []).append((manager, player))
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
        size = expected_roster_size(on_il.get(manager, 0))
        if len(players) != size:
            why = (f"{active_spots()} active + {on_il.get(manager, 0)} in an IL "
                   f"slot, per {il_source}")
            (failures if abs(len(players) - size) > 2 else warnings).append(
                f"{manager} has {len(players)} players, expected {size} ({why}).")

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
            # The simulators' resolver, so this agrees with the engine about
            # who has a projection (see check_playerlist).
            known = PlayerIndex({n: n for n in frame["player_name"]})
            unmatched = []
            for manager, players in sorted(rosters.items()):
                for player in players:
                    if PLACEHOLDER.match(str(player)):
                        continue
                    if player not in known:
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
