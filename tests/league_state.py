"""Skips for tests that exist to check the league's REAL state (P2, 10-31).

The league's state lives in the private repo nickrolen/newsletter-state
(config/STATE_MANIFEST.json); the public CI has none of it. A test whose
point is the real data -- the real rulings, the real trade log, the real
PLAYERLIST snapshots, the issues that actually shipped in 2025-26 -- is
skipped where that data is absent, and ONLY such a test: a test that merely
needs a file of the right shape uses a fixture instead. Every use names the
files and says why. On Nick's machine, with the state pulled, they all run.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def needs_state(*rels, why):
    missing = [r for r in rels if not (ROOT / r).exists()]
    return pytest.mark.skipif(
        bool(missing),
        reason=f"league state not in this checkout ({', '.join(missing)}): {why}")


def actuals_last_day(root=ROOT):
    """The last league day data/player_actuals.json holds for any rostered
    player (None: no cache, or nothing cached yet)."""
    import json
    path = Path(root) / "data" / "player_actuals.json"
    if not path.is_file():
        return None
    from datetime import date
    blob = json.loads(path.read_text(encoding="utf-8"))
    ids = {str(i) for i in (blob.get("roster_names") or {}).values()}
    days = [max(r["days"]) for pid, r in (blob.get("players") or {}).items()
            if pid in ids and r.get("days")]
    return date.fromisoformat(max(days)) if days else None


def skip_if_actuals_behind(now=None, root=ROOT):
    """H51 (11-17): a real-state build of the hub or the cards reads every
    rostered player's actuals through the build's "yesterday" (league clock).
    Between midnight Pacific and the next `state.py pull`, the local cache
    ends the day before that: the normal state, not a failure. Skip then,
    naming both days; never fake the date. A cache that does reach yesterday
    and still lacks a player is a real gap, and the test runs (and fails)."""
    from datetime import timedelta
    from modules.league_clock import league_now
    now = now or league_now()
    yesterday = now.date() - timedelta(days=1)
    last = actuals_last_day(root)
    if last is None:
        pytest.skip("league state not in this checkout (data/player_actuals.json): the real "
                    "build reads every rostered player's actuals")
    if last < yesterday:
        pytest.skip(f"data/player_actuals.json ends {last}, before this build's yesterday "
                    f"({yesterday}, league clock): the local cache is a day behind until the "
                    "next `python scripts/state.py pull` (the nightly fetches it after midnight "
                    "Pacific). Pull state and re-run.")
    # the other normal gap: a roster synced here (Monday's Step 4) before the
    # next cloud run fetches the new player's actuals
    import json
    from modules import player_actuals as pa
    blob = pa.load(root)
    rosters = json.loads((Path(root) / "config" / "ROSTERS.json").read_text(encoding="utf-8"))
    new = sorted(n for v in (rosters.get("rosters") or {}).values() for n in v
                 if pa.find_days(blob, n) is None)
    if new:
        pytest.skip(f"config/ROSTERS.json has {', '.join(new)}, not yet in data/player_actuals.json "
                    "(a roster synced here before the next cloud run fetched them). Pull state "
                    "after the next run and re-run.")
