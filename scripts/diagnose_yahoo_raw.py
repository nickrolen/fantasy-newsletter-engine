#!/usr/bin/env python3
"""
diagnose_yahoo_raw.py -- Talk to Yahoo directly, below yahoo_fantasy_api.

WHY
---
yahoo_fantasy_api raises RuntimeError(response.content) and throws the HTTP
status code away. That code is the whole diagnosis:

    401  the access token is rejected      -> a credentials/grant problem
    403  the token is fine, the app is not -> an app-permission problem
    999  Yahoo rate limiting / bot block   -> wait and retry
    200  it works

"This application is not authorized to perform this action" is the body Yahoo
returns for several different causes, so the body alone cannot distinguish
them. The status can.

It also asks Yahoo which account actually consented. The browser flow uses
whatever Yahoo session is signed in, so it is entirely possible to authorize
with the wrong account and get a perfectly valid token that has no business
reading your league.

Nothing is written. Tokens are never printed.

USAGE
    py scripts/diagnose_yahoo_raw.py
    py scripts/diagnose_yahoo_raw.py --league-key 466.l.42309
"""

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import LEAGUE_KEY  # noqa: E402

OAUTH_FILE = PROJECT_ROOT / "oauth2.json"
FANTASY = "https://fantasysports.yahooapis.com/fantasy/v2"
USERINFO = "https://api.login.yahoo.com/openid/v1/userinfo"

MEANING = {
    200: "OK",
    401: "token rejected -- credentials/grant problem",
    403: "token accepted, action forbidden -- APP PERMISSION problem",
    404: "not found -- wrong key, or no access to this resource",
    999: "Yahoo rate limit / bot block -- wait, then retry",
}


def get(session, url, token):
    try:
        r = session.get(url, headers={"Authorization": f"Bearer {token}"},
                        timeout=30)
    except Exception as e:
        return None, f"request failed: {e}"
    body = (r.text or "").replace("\n", " ").strip()
    if len(body) > 160:
        body = body[:160] + "..."
    return r.status_code, body


def main():
    parser = argparse.ArgumentParser(description="Raw Yahoo API diagnosis.")
    parser.add_argument("--league-key", default=None)
    args = parser.parse_args()
    league_key = args.league_key or LEAGUE_KEY

    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. pip install -r requirements.txt")
        return 1

    if not OAUTH_FILE.exists():
        print(f"ERROR: {OAUTH_FILE.name} not found.")
        return 1
    creds = json.loads(OAUTH_FILE.read_text(encoding="utf-8"))
    token = creds.get("access_token")
    if not token:
        print(f"ERROR: no access_token in {OAUTH_FILE.name}. Run reauth_yahoo.py.")
        return 1

    print("=" * 68)
    print("  RAW YAHOO DIAGNOSIS")
    print("=" * 68)
    print(f"\n  access_token present ({len(token)} chars, not shown)")
    print(f"  consumer_key: {str(creds.get('consumer_key',''))[:12]}...")

    session = requests.Session()

    # 1. Who consented? The browser flow uses whatever session was signed in.
    print("\n  [1] Which Yahoo account does this token belong to?")
    code, body = get(session, USERINFO, token)
    if code == 200:
        try:
            info = json.loads(body if body.endswith("}") else body.rstrip("."))
            who = info.get("email") or info.get("nickname") or info.get("sub")
            print(f"      {code}  consented as: {who}")
            print("      ^ this MUST be the Yahoo account that is in the league.")
        except Exception:
            print(f"      {code}  (could not parse) {body[:100]}")
    else:
        print(f"      {code}  {MEANING.get(code, '')}")
        print(f"      {body[:120]}")
        print("      (a failure here is not fatal -- openid scope may not be granted)")

    # 2. Fantasy endpoints, narrowest requirement first.
    checks = [
        ("users;use_login=1/games",
         f"{FANTASY}/users;use_login=1/games?format=json",
         "needs ONLY a fantasy-scoped token; no league membership"),
        ("game/nba",
         f"{FANTASY}/game/nba?format=json",
         "public-ish game metadata"),
        (f"league/{league_key}/settings",
         f"{FANTASY}/league/{league_key}/settings?format=json",
         "needs fantasy scope AND membership in this league"),
    ]

    print("\n  [2] Fantasy endpoints")
    results = {}
    for label, url, note in checks:
        code, body = get(session, url, token)
        results[label] = code
        meaning = MEANING.get(code, "")
        print(f"\n      {label}")
        print(f"        {note}")
        print(f"        HTTP {code}  {meaning}")
        if code != 200:
            print(f"        {body[:150]}")

    # 3. Verdict
    print("\n" + "=" * 68)
    codes = set(results.values())
    if codes == {200}:
        print("  Everything works. Re-run scripts/check_yahoo_access.py.")
        print("=" * 68)
        return 0

    if 999 in codes:
        print("  VERDICT: Yahoo is rate limiting or bot-blocking this client.")
        print("  Wait 15-60 minutes and re-run. Nothing is wrong with the app.")
    elif 403 in codes:
        print("  VERDICT: 403 -- the token is accepted, the APP is not permitted.")
        print()
        print("  The token is valid and a fresh grant already failed, so this is")
        print("  the app itself. Yahoo has been restricting Fantasy API access;")
        print("  an app can show 'Fantasy Sports - Read' in the console and")
        print("  still be refused at the API.")
        print()
        print("  Next: create a BRAND NEW app at https://developer.yahoo.com/apps/")
        print("    - Application Type: Installed Application")
        print("    - API Permissions: Fantasy Sports -> Read")
        print("  Put its Client ID / Secret into oauth2.json as consumer_key /")
        print("  consumer_secret, then:  py scripts/reauth_yahoo.py")
        print("  Re-run this script to confirm before doing anything else.")
    elif 401 in codes:
        print("  VERDICT: 401 -- the access token itself is being rejected.")
        print("  Re-run py scripts/reauth_yahoo.py and complete the browser flow")
        print("  again, making sure you approve while signed in as the Yahoo")
        print("  account that is a member of the league.")
    else:
        print(f"  VERDICT: unexpected status codes {sorted(c for c in codes if c)}.")
        print("  Send this output on; the bodies above carry the detail.")

    if results.get("users;use_login=1/games") != 200:
        print()
        print("  Note: users;use_login=1/games needs no league membership at all.")
        print("  It failing means the problem is the token's fantasy access,")
        print("  not anything about league " + league_key + ".")
    print("=" * 68)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUNEXPECTED ERROR in the diagnostic: {e}")
        sys.exit(1)
