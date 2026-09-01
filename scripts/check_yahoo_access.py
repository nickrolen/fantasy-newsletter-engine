#!/usr/bin/env python3
"""
check_yahoo_access.py -- Find out exactly which Yahoo API calls this account
is allowed to make.

WHY
---
"This application is not authorized to perform this action" can mean anything
from "your whole integration is dead" to "that one discovery endpoint needs a
scope you never granted". The difference matters enormously in September, so
this tests each call the engine actually depends on and reports which ones
work.

The engine only ever uses LEAGUE-SCOPED calls -- yfa.League(oauth, key) and
its methods. It never calls Game.game_id() or Game.league_ids(); those are
discovery endpoints used only by get_league_key.py. So the two can fail
independently, and league-scoped access failing is the serious one.

USAGE
    py scripts/check_yahoo_access.py                     # uses config's key
    py scripts/check_yahoo_access.py --league-key 466.l.42309

EXIT CODES
    0 = every call the engine needs works
    1 = at least one engine-critical call failed
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import LEAGUE_KEY  # noqa: E402
from modules.yahoo_auth import YahooAuthError, build_oauth  # noqa: E402

OAUTH_FILE = PROJECT_ROOT / "oauth2.json"


def short_error(e):
    s = str(e).replace("\n", " ")
    if "not authorized" in s:
        return "NOT AUTHORIZED (scope/permission)"
    if len(s) > 90:
        s = s[:90] + "..."
    return s or e.__class__.__name__


def probe(label, fn, critical=True):
    """Run one API call and report. Returns True on success."""
    try:
        result = fn()
    except Exception as e:
        tag = "FAIL" if critical else "fail"
        print(f"  [{tag}] {label:34} {short_error(e)}")
        return False
    detail = ""
    if isinstance(result, (list, dict)):
        detail = f"{len(result)} item(s)"
    elif result is not None:
        detail = str(result)[:40]
    print(f"  [ OK ] {label:34} {detail}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Check which Yahoo Fantasy API calls this account can make."
    )
    parser.add_argument("--league-key", default=None,
                        help=f"league key to test against (default: {LEAGUE_KEY})")
    args = parser.parse_args()
    league_key = args.league_key or LEAGUE_KEY

    try:
        from yahoo_oauth import OAuth2
        import yahoo_fantasy_api as yfa
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}). pip install -r requirements.txt")
        return 1

    print("=" * 64)
    print("  YAHOO API ACCESS CHECK")
    print("=" * 64)

    try:
        oauth = build_oauth(OAUTH_FILE, OAuth2=OAuth2)
    except YahooAuthError as e:
        print(f"\nAUTH FAILED: {e}")
        return 1
    print("\n  Token authenticates and refreshes OK.")

    # ---- League-scoped: everything the engine depends on -----------------
    print(f"\n  LEAGUE-SCOPED CALLS  (league {league_key})")
    print("  These are what the engine actually uses. All must work.\n")

    lg = yfa.League(oauth, league_key)
    critical = {
        "settings()": lambda: lg.settings(),
        "teams()": lambda: lg.teams(),
        "standings()": lambda: lg.standings(),
        "current_week()": lambda: lg.current_week(),
        "end_week()": lambda: lg.end_week(),
        "draft_results()": lambda: lg.draft_results(),
        "transactions('add,drop', 5)": lambda: lg.transactions("add,drop", 5),
    }
    results = {name: probe(name, fn) for name, fn in critical.items()}

    # matchups() and player_details() need a week / player id, so derive them
    try:
        wk = lg.current_week()
        results["matchups(week)"] = probe("matchups(week)", lambda: lg.matchups(wk))
    except Exception:
        print("  [SKIP] matchups(week)                    (no current_week)")

    try:
        first_team = list(lg.teams().keys())[0]
        roster = lg.to_team(first_team).roster()
        pid = roster[0]["player_id"]
        results["player_details(id)"] = probe(
            "player_details(id)", lambda: lg.player_details([int(pid)])
        )
    except Exception as e:
        print(f"  [SKIP] player_details(id)                ({short_error(e)})")

    # ---- Discovery: NOT used by the engine -------------------------------
    print("\n  DISCOVERY CALLS  (used only by get_league_key.py)")
    print("  These need broader scopes and can fail harmlessly.\n")

    game = yfa.Game(oauth, "nba")
    disc_id = probe("Game.game_id()", lambda: game.game_id(), critical=False)
    disc_ids = probe("Game.league_ids()", lambda: game.league_ids(), critical=False)

    # ---- Verdict ---------------------------------------------------------
    print("\n" + "=" * 64)
    failed = [k for k, v in results.items() if not v]
    if not failed:
        print("  VERDICT: the engine's Yahoo access is fully working.")
        if not (disc_id and disc_ids):
            print()
            print("  Only the discovery endpoints are blocked. The engine never")
            print("  calls those, so nothing in the weekly workflow is affected.")
            print("  To find the new season's league key, run:")
            print("      py scripts/get_league_key.py --league-id 16778 --probe")
            print("  which finds the game_id by trying league-scoped reads instead.")
        print("=" * 64)
        return 0

    print(f"  VERDICT: {len(failed)} engine-critical call(s) FAILED:")
    for f in failed:
        print(f"    - {f}")
    print()
    print("  This is the serious case -- the weekly workflow depends on these.")
    print("  Check the app's permissions at https://developer.yahoo.com/apps/")
    print("  and confirm it has Fantasy Sports READ access. If the app was")
    print("  re-created or its permissions changed, oauth2.json must be")
    print("  regenerated from the new consumer key/secret.")
    print("=" * 64)
    return 1


if __name__ == "__main__":
    sys.exit(main())
