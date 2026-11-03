#!/usr/bin/env python3
"""
fetch_player_actuals.py -- cache every rostered player's daily fantasy points
and games played from Yahoo, one finished league day at a time.

    python scripts/fetch_player_actuals.py

Writes data/player_actuals.json (private state; modules/player_actuals.py
says what is in it and why). A finished league day (before today, Pacific)
is fetched once and never again; a player new to a roster is backfilled from
the season's first day. Read-only against Yahoo.

Refuses (exit 1) on any failed or malformed Yahoo line, naming the date and
the player; the days that completed before it stay written, a partial day is
never written. build_hub_state reads the file and refuses if it does not
cover yesterday for every rostered player.

Step 1c's nightly run calls this before build_hub_state.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import player_actuals as pa          # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=".")
    a = ap.parse_args(argv)
    try:
        r = pa.update(a.base_path)
    except pa.ActualsError as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"Player actuals through {r['through']}: {r['players']} rostered players; "
          f"{len(r['days_fetched'])} day(s) fetched, {r['calls']} Yahoo call(s), {r['seconds']} s.")
    if r["backfilled"]:
        print(f"  backfilled from the season's first day: {', '.join(r['backfilled'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
