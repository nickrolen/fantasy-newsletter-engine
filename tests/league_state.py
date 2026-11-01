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
