"""
yahoo_auth.py

Centralized, fail-fast Yahoo OAuth2 client construction.

WHY THIS EXISTS:
    The raw pattern used throughout the pipeline --

        oauth = OAuth2(None, None, from_file="oauth2.json")
        if not oauth.token_is_valid():
            oauth.refresh_access_token()

    -- hangs forever on placeholder or never-authorized credentials, because
    yahoo_oauth's refresh_access_token() drops into an INTERACTIVE browser +
    "Enter verifier:" stdin prompt when there is no usable refresh token. That
    is fine at a keyboard but fatal for any scheduled / automated / first-run
    use, and it gives adopters a confusing silent hang instead of an error.

    build_oauth() detects that situation up front and raises YahooAuthError
    with an actionable message INSTEAD of prompting. Callers that need live
    Yahoo data can let it propagate (fail fast); optional callers (e.g. injury
    fetch) can catch it and degrade to cached data.

DESTINATION: every live Yahoo API entry point (season_performers,
fetch_injury_statuses, and the backfill scripts).
"""

import json
from pathlib import Path


class YahooAuthError(RuntimeError):
    """Raised when Yahoo OAuth credentials cannot authenticate non-interactively."""


# Substrings that indicate an unfilled credentials file (see oauth2.json.example).
_PLACEHOLDER_MARKERS = ("YOUR_YAHOO", "YOUR_CONSUMER", "REPLACE", "XXXX")


def build_oauth(oauth_file, *, OAuth2):
    """Return a ready-to-use OAuth2 client, or raise YahooAuthError.

    Never triggers the interactive authorization prompt: if the token is
    invalid and cannot be refreshed without user interaction, it raises.

    Args:
        oauth_file: Path to the oauth2.json credentials file.
        OAuth2: The yahoo_oauth.OAuth2 class (passed in so this module has no
            hard dependency on yahoo_oauth being importable for tests).
    """
    path = Path(oauth_file)
    if not path.is_file():
        raise YahooAuthError(
            f"Yahoo OAuth file not found: {path}. Copy oauth2.json.example to "
            f"oauth2.json and fill in your credentials, or run with "
            f"--fast / --no-fetch-injuries / --repro to skip live Yahoo calls."
        )

    try:
        creds = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise YahooAuthError(f"Yahoo OAuth file {path} is unreadable: {e}")

    consumer_key = str(creds.get("consumer_key", ""))
    consumer_secret = str(creds.get("consumer_secret", ""))
    blob = (consumer_key + consumer_secret).upper()
    if not consumer_key or not consumer_secret or any(m in blob for m in _PLACEHOLDER_MARKERS):
        raise YahooAuthError(
            f"Yahoo OAuth file {path} still contains placeholder/empty "
            f"credentials. Fill in your consumer_key/consumer_secret, or run "
            f"with --fast / --no-fetch-injuries / --repro to skip live Yahoo calls."
        )

    oauth = OAuth2(None, None, from_file=str(path))
    if oauth.token_is_valid():
        return oauth

    # Token invalid. A non-interactive refresh is only possible if a stored
    # refresh_token exists; otherwise refresh_access_token() would prompt.
    if not creds.get("refresh_token"):
        raise YahooAuthError(
            f"Yahoo token in {path} is expired/absent and has no stored "
            f"refresh_token, so it cannot be refreshed without an interactive "
            f"login. Complete a manual OAuth flow once, or run with "
            f"--fast / --no-fetch-injuries / --repro to skip live Yahoo calls."
        )

    oauth.refresh_access_token()
    return oauth
