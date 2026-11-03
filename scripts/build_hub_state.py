#!/usr/bin/env python3
"""
build_hub_state.py -- write output/hub_state.json, the hub's one payload.

    python scripts/build_hub_state.py [--allow-engine-mismatch]

Reads only what is on disk (modules/hub_state.py lists every source): this
week's live line, the latest title-odds run (output/title_odds_latest.json)
and the history, the rosters, IL slots, the latest tag record
(output/tag_records.jsonl), data/player_actuals.json, PLAYERLIST, the
transaction log, the newsletter archive. The nightly run (python
scripts\\nightly.py) writes every one of them and then builds the hub; run
this by hand only after it.

Refuses (exit 1) on any missing or inconsistent input, naming the file.
--allow-engine-mismatch builds from a live line priced by another engine (an
uncommitted tree, say); the hub then says so above everything else, as the
line page does.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=".")
    ap.add_argument("--allow-engine-mismatch", action="store_true")
    a = ap.parse_args(argv)
    from modules import hub_state, player_actuals, hub_archive, live_lines_page
    t0 = time.time()
    try:
        payload = hub_state.build(a.base_path, allow_engine_mismatch=a.allow_engine_mismatch)
    except (hub_state.HubInputError, player_actuals.ActualsError, hub_archive.ArchiveError,
            live_lines_page.EngineMismatch) as e:
        print(f"REFUSED: {e}")
        return 1
    p = hub_state.write(a.base_path, payload)
    print(f"Wrote {p} for week {payload['week']} ({payload['league_day']}) in {time.time() - t0:.1f} s.")
    if payload["header"]["engine_mismatch"]:
        print(f"  ENGINE MISMATCH (allowed): {payload['header']['engine_mismatch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
