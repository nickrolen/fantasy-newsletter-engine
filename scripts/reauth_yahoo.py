#!/usr/bin/env python3
"""
reauth_yahoo.py -- Force a fresh Yahoo authorization.

WHY
---
A refresh token keeps working even after the underlying grant loses a scope.
That produces a confusing symptom: yahoo_oauth reports "TOKEN IS STILL VALID"
while every API call comes back "This application is not authorized to perform
this action."

Refreshing cannot fix that. A refresh renews an existing grant; it cannot add
a permission the grant never had. The only fix is a new consent, which means
discarding the stored token and letting Yahoo issue a new one.

modules/yahoo_auth.build_oauth() deliberately never prompts -- correct for the
weekly workflow, which must not block on a browser. This script is the
explicit, manual counterpart.

BEFORE RUNNING
--------------
Check https://developer.yahoo.com/apps/ first. Open the app whose consumer key
is in oauth2.json and confirm:
  - the app still exists
  - API Permissions includes Fantasy Sports (Read, or Read/Write)
If Fantasy Sports is not granted there, re-consent will produce another token
with no fantasy scope and you will be back here.

WHAT IT DOES
------------
Backs up oauth2.json, strips only the token fields (consumer_key and
consumer_secret are preserved), then runs the interactive flow. Yahoo opens a
browser or prints a URL; you approve and paste back the verifier. On success
it verifies the new token with a real league-scoped call.

USAGE
    py scripts/reauth_yahoo.py                       # verify against config's league
    py scripts/reauth_yahoo.py --league-key 466.l.42309
    py scripts/reauth_yahoo.py --dry-run             # show the plan only

EXIT CODES
    0 = re-authorized and verified
    1 = aborted, or the new token still cannot read the league
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import LEAGUE_KEY  # noqa: E402

OAUTH_FILE = PROJECT_ROOT / "oauth2.json"

# Everything except these is a token artifact and gets cleared.
KEEP_FIELDS = {"consumer_key", "consumer_secret"}


def main():
    parser = argparse.ArgumentParser(
        description="Force a fresh Yahoo OAuth consent."
    )
    parser.add_argument("--league-key", default=None,
                        help=f"league key to verify against (default: {LEAGUE_KEY})")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would happen; change nothing")
    args = parser.parse_args()
    league_key = args.league_key or LEAGUE_KEY

    if not OAUTH_FILE.exists():
        print(f"ERROR: {OAUTH_FILE.name} not found.")
        print("       Copy oauth2.json.example and fill in consumer_key/secret.")
        return 1

    try:
        creds = json.loads(OAUTH_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: {OAUTH_FILE.name} is unreadable: {e}")
        return 1

    key = str(creds.get("consumer_key", ""))
    secret = str(creds.get("consumer_secret", ""))
    if not key or not secret:
        print(f"ERROR: {OAUTH_FILE.name} has no consumer_key/consumer_secret.")
        print("       Those come from https://developer.yahoo.com/apps/")
        return 1

    dropping = sorted(k for k in creds if k not in KEEP_FIELDS)
    print("=" * 62)
    print("  YAHOO RE-AUTHORIZATION")
    print("=" * 62)
    print(f"\n  consumer_key:  {key[:12]}...{key[-4:]}  (kept)")
    print(f"  token fields to clear: {', '.join(dropping) if dropping else '(none)'}")
    print(f"  verify against: {league_key}")

    if args.dry_run:
        print("\n  [DRY-RUN] Nothing changed. Re-run without --dry-run.")
        return 0

    print("\n  Have you confirmed at https://developer.yahoo.com/apps/ that this")
    print("  app has Fantasy Sports permission? Without it, the new token will")
    print("  be refused exactly like the old one.")
    answer = input("\n  Continue? [y/N] ").strip().lower()
    if answer != "y":
        print("  Aborted. Nothing changed.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = OAUTH_FILE.with_name(f"oauth2.backup_{stamp}.json")
    shutil.copy2(OAUTH_FILE, backup)
    print(f"\n  Backup: {backup.name}")

    OAUTH_FILE.write_text(
        json.dumps({"consumer_key": key, "consumer_secret": secret}, indent=2),
        encoding="utf-8",
    )
    print(f"  Cleared token fields from {OAUTH_FILE.name}")

    try:
        from yahoo_oauth import OAuth2
        import yahoo_fantasy_api as yfa
    except ImportError as e:
        print(f"\nERROR: missing dependency ({e}). Restore {backup.name}.")
        return 1

    print("\n  Starting the interactive flow -- approve in the browser, then")
    print("  paste the verifier code back here if prompted.\n")
    try:
        oauth = OAuth2(None, None, from_file=str(OAUTH_FILE))
    except Exception as e:
        print(f"\nAUTH FAILED: {e}")
        print(f"Restore your previous credentials with:  copy {backup.name} oauth2.json")
        return 1

    if not oauth.token_is_valid():
        print("\nAUTH FAILED: no valid token after the flow.")
        print(f"Restore with:  copy {backup.name} oauth2.json")
        return 1
    print("\n  New token obtained.")

    print(f"\n  Verifying with a real league read ({league_key})...")
    try:
        lg = yfa.League(oauth, league_key)
        teams = lg.teams()
        print(f"  SUCCESS -- read {len(teams)} teams.")
    except Exception as e:
        msg = str(e).replace("\n", " ")
        print(f"  STILL REFUSED: {msg[:150]}")
        print("\n  The new token has the same problem, which means the app itself")
        print("  lacks Fantasy Sports permission. Fix it at")
        print("  https://developer.yahoo.com/apps/ (or create a new app and put")
        print("  its key/secret in oauth2.json), then run this again.")
        return 1

    print("\n" + "=" * 62)
    print("  Yahoo access restored. Re-run scripts/check_yahoo_access.py")
    print("  to confirm every engine call works.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. If token fields were already cleared, restore the")
        print("oauth2.backup_*.json file this script created.")
        sys.exit(1)
