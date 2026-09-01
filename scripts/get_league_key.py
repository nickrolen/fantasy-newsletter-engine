#!/usr/bin/env python3
"""
get_league_key.py -- Find the Yahoo league key for a season, and prove the
OAuth token still works.

WHY
---
league_config.json needs `yahoo.current_league_key` in the form
    <game_id>.l.<league_id>
e.g. "466.l.42309" for 2025-26.

The league id is the number in your league URL. The game_id is Yahoo's
internal id for that season's NBA game, and it is NOT guessable -- across
2017-18 to 2025-26 it went 380, 390, 402, 411, 418, 428, 438, 451, 466:
gaps of 7 to 15. It has to be looked up.

This script also doubles as the Yahoo OAuth health check. It is the cheapest
possible live call, so run it well before draft night: if the token has gone
stale over the offseason you want to find out now, at a browser, not while
36 draft picks are waiting to be pulled.

USAGE
    py scripts/get_league_key.py --league-id 16778
    py scripts/get_league_key.py --league-id 16778 --season 2026
    py scripts/get_league_key.py                      # just list my leagues

Read-only: it never writes league_config.json. It prints the value to set.
Editing config is a deliberate step in the season reset (SEASON_RESET.md).

EXIT CODES
    0 = found a key (or listed leagues successfully)
    1 = auth failed, or the requested league was not found
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.yahoo_auth import YahooAuthError, build_oauth  # noqa: E402

OAUTH_FILE = PROJECT_ROOT / "oauth2.json"


def parse_league_id(raw):
    """Accept a bare id or a full league URL."""
    s = str(raw).strip().rstrip("/")
    if "/" in s:
        s = s.split("/")[-1]
    if not s.isdigit():
        raise ValueError(
            f"could not read a numeric league id from {raw!r}. Pass the number "
            f"at the end of your league URL, e.g. 16778."
        )
    return s


def main():
    parser = argparse.ArgumentParser(
        description="Look up the Yahoo league key for a season."
    )
    parser.add_argument(
        "--league-id",
        help="league id, or the full league URL "
             "(https://basketball.fantasysports.yahoo.com/nba/16778)",
    )
    parser.add_argument(
        "--season", type=int, default=None,
        help="starting year of the season (2026 for 2026-27). "
             "Default: whatever Yahoo currently considers the active game.",
    )
    args = parser.parse_args()

    try:
        from yahoo_oauth import OAuth2
        import yahoo_fantasy_api as yfa
    except ImportError as e:
        print(f"ERROR: missing dependency ({e}).")
        print("       pip install -r requirements.txt")
        return 1

    print("Authenticating against Yahoo...")
    try:
        oauth = build_oauth(OAUTH_FILE, OAuth2=OAuth2)
    except YahooAuthError as e:
        print(f"\nOAUTH FAILED: {e}")
        print("\nThis is the check you wanted to fail now rather than on draft")
        print("night. Refresh oauth2.json and re-run.")
        return 1
    print("  OAuth OK -- token is valid.\n")

    game = yfa.Game(oauth, "nba")

    try:
        game_id = game.game_id()
        print(f"  NBA game_id (current): {game_id}")
    except Exception as e:
        print(f"  WARNING: could not read game_id ({e})")
        game_id = None

    try:
        league_keys = game.league_ids(year=args.season) if args.season \
            else game.league_ids()
    except Exception as e:
        print(f"\nERROR: could not list leagues ({e})")
        return 1

    if not league_keys:
        print("\nNo leagues found for that season.")
        print("If the new league exists but is not showing, confirm it has been")
        print("created/renewed and that this Yahoo account is a member.")
        return 1

    print(f"\n  Leagues on this account"
          f"{f' for {args.season}-{str(args.season + 1)[-2:]}' if args.season else ''}:")
    for k in league_keys:
        print(f"    {k}")

    if not args.league_id:
        print("\nPass --league-id to pick one out and get the config line.")
        return 0

    try:
        wanted = parse_league_id(args.league_id)
    except ValueError as e:
        print(f"\nERROR: {e}")
        return 1

    matches = [k for k in league_keys if k.endswith(f".l.{wanted}")]
    if not matches:
        print(f"\nERROR: no league ending in .l.{wanted} on this account.")
        print("       Check the id, the season, and that the league exists yet.")
        return 1

    key = matches[0]
    season_label = f"{args.season}-{str(args.season + 1)[-2:]}" if args.season else "<season>"
    print(f"\n{'=' * 58}")
    print(f"  LEAGUE KEY: {key}")
    print(f"{'=' * 58}")
    print("\nSet in config/league_config.json (AFTER the season reset runs):")
    print(f'    "yahoo": {{')
    print(f'        "current_league_key": "{key}",')
    print(f'        "historical_league_keys": {{')
    print(f'            ...,')
    print(f'            "{season_label}": "{key}"')
    print(f'        }}')
    print(f'    }}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
