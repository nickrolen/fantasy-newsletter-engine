#!/usr/bin/env python3
"""
monday_poll.py -- is there a Yahoo transaction the league state has not logged?
(step 3b, Monday-window polling; claude/HANDOFF_STEP3B_TAG_FRESHNESS_2026-11-10.md s.1)

    python3 engine/scripts/monday_poll.py --base-path engine --state-dir state --oauth oauth2.json

Run by the workflow's GUARD job, on a firing scripts/run_guard.py marked
poll=true (a :00 or :30 firing while Monday's window is open, outside the
pre-tip window). That job bills a minute whatever it does, so a poll that finds
nothing costs nothing extra: no run job starts, nothing is written, committed
or published. When Yahoo has a transaction whose key is not in the state's
data/transaction_log.jsonl, it writes go=true (and new=N) to $GITHUB_OUTPUT,
and the run job runs `nightly.py --poll`: the sync logs the transactions and a
refresh prices them, with its cause built from them.

ONE CHEAP READ: Yahoo's latest POLL_COUNT transactions (a poll needs to know
only whether anything is new; the run job's sync reads the full page). The
comparison is by Yahoo's transaction key, the log's own identity
(modules/transaction_log).

STANDARD LIBRARY plus the two Yahoo client packages, pinned in run.yml's poll
step (yahoo-oauth, yahoo-fantasy-api): the guard job installs nothing else, so
this file must not import the engine's modules (they need pandas). Tests:
tests/test_tag_freshness.py.

RAISE, NEVER GUESS: a missing log, a malformed log line, a Yahoo error or a
Yahoo record with no key exits 1 and the workflow's guard-failed job opens the
failure issue. A missing log is not "nothing logged".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

POLL_COUNT = 25
LOG_REL = "data/transaction_log.jsonl"


class PollError(RuntimeError):
    pass


def logged_keys(state_dir) -> set:
    """Every transaction key in the state's transaction log."""
    p = Path(state_dir) / LOG_REL
    if not p.is_file():
        raise PollError(f"{LOG_REL} is missing under {state_dir}: the poll compares against it")
    keys = set()
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            raise PollError(f"{LOG_REL} line {i} is not JSON ({e})") from None
        if row.get("row") == "transaction":
            if not row.get("key"):
                raise PollError(f"{LOG_REL} line {i}: a transaction row with no key")
            keys.add(row["key"])
    return keys


def new_transactions(raw: list, keys: set) -> list:
    """Yahoo's records whose key is not logged, as Yahoo returned them."""
    out = []
    for r in raw or []:
        k = r.get("transaction_key") if isinstance(r, dict) else None
        if not k:
            raise PollError(f"a Yahoo transaction with no key: {r!r:.200}")
        if k not in keys:
            out.append(r)
    return out


def league_key(base) -> str:
    p = Path(base) / "config" / "league_config.json"
    if not p.is_file():
        raise PollError(f"config/league_config.json is missing under {base}")
    k = (json.loads(p.read_text(encoding="utf-8")).get("yahoo") or {}).get("current_league_key")
    if not k:
        raise PollError("config/league_config.json does not specify yahoo.current_league_key")
    return str(k)


def fetch(oauth_file: str, key: str) -> list:      # pragma: no cover -- a live Yahoo call
    from yahoo_oauth import OAuth2
    import yahoo_fantasy_api as yfa
    oauth = OAuth2(None, None, from_file=oauth_file)
    if not oauth.token_is_valid():
        oauth.refresh_access_token()
    try:
        return list(yfa.League(oauth, key).transactions(tran_types="add,drop,trade",
                                                       count=POLL_COUNT) or [])
    except Exception as e:                          # noqa: BLE001 -- named and refused
        raise PollError(f"Yahoo's transactions could not be read ({type(e).__name__}: {e})") from None


def poll(base, state_dir, oauth_file: str, fetcher=None) -> dict:
    """{"new": n, "keys": [...]}: compare Yahoo's latest with the log."""
    keys = logged_keys(state_dir)
    raw = (fetcher or fetch)(oauth_file, league_key(base))
    new = new_transactions(raw, keys)
    return {"new": len(new), "keys": [r["transaction_key"] for r in new]}


def main(argv=None, fetcher=None) -> int:
    ap = argparse.ArgumentParser(description="Monday poll: is a Yahoo transaction not yet logged?")
    ap.add_argument("--base-path", required=True, help="the engine checkout (config/league_config.json)")
    ap.add_argument("--state-dir", required=True, help="the private repo checkout (the transaction log)")
    ap.add_argument("--oauth", required=True, help="oauth2.json, written from the secret")
    a = ap.parse_args(argv)
    try:
        out = poll(a.base_path, a.state_dir, a.oauth, fetcher)
    except PollError as e:
        print(f"POLL REFUSED: {e}")
        return 1
    go = out["new"] > 0
    print(f"poll: {out['new']} new transaction(s)" + (f" ({', '.join(out['keys'])})" if go else
                                                      ": nothing to refresh"))
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"go={'true' if go else 'false'}\nnew={out['new']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
