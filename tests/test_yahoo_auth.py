"""
Regression tests for the fail-fast Yahoo OAuth guard (modules/yahoo_auth.py).

Encodes the bug fixed on 2026-06: placeholder / never-authorized credentials
used to drop into an interactive "Enter verifier:" prompt and hang forever.
build_oauth() must instead raise YahooAuthError WITHOUT ever calling
refresh_access_token() (which is what triggers the prompt).
"""

import json

import pytest

from modules.yahoo_auth import build_oauth, YahooAuthError


class _FakeOAuth:
    """Stand-in for yahoo_oauth.OAuth2 that explodes if a refresh is attempted."""

    last_token_valid = True

    def __init__(self, *args, **kwargs):
        pass

    def token_is_valid(self):
        return _FakeOAuth.last_token_valid

    def refresh_access_token(self):  # pragma: no cover - must never run in these tests
        raise AssertionError("refresh_access_token() would prompt interactively")


def test_missing_file_raises(tmp_path):
    with pytest.raises(YahooAuthError):
        build_oauth(tmp_path / "nope.json", OAuth2=_FakeOAuth)


def test_placeholder_credentials_raise(tmp_path):
    f = tmp_path / "oauth2.json"
    f.write_text(json.dumps({
        "consumer_key": "YOUR_YAHOO_CONSUMER_KEY",
        "consumer_secret": "YOUR_YAHOO_CONSUMER_SECRET",
    }))
    with pytest.raises(YahooAuthError):
        build_oauth(f, OAuth2=_FakeOAuth)


def test_invalid_token_without_refresh_token_raises(tmp_path):
    f = tmp_path / "oauth2.json"
    f.write_text(json.dumps({
        "consumer_key": "real_key_abc123",
        "consumer_secret": "real_secret_xyz789",
    }))
    _FakeOAuth.last_token_valid = False
    try:
        with pytest.raises(YahooAuthError):
            build_oauth(f, OAuth2=_FakeOAuth)
    finally:
        _FakeOAuth.last_token_valid = True


def test_valid_token_returns_client(tmp_path):
    f = tmp_path / "oauth2.json"
    f.write_text(json.dumps({
        "consumer_key": "real_key_abc123",
        "consumer_secret": "real_secret_xyz789",
    }))
    _FakeOAuth.last_token_valid = True
    client = build_oauth(f, OAuth2=_FakeOAuth)
    assert isinstance(client, _FakeOAuth)
