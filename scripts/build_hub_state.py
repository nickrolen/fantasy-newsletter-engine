#!/usr/bin/env python3
"""
build_hub_state.py -- write output/hub_state.json, the hub's one payload.

    python scripts/build_hub_state.py [--allow-engine-mismatch] [--out PATH]

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
--out PATH writes the payload there instead of output/hub_state.json (a
scratch build that leaves the league state alone; refused if PATH is a state
path in config/STATE_MANIFEST.json).
--mvp-odds FILE (4c6, with --out only): the MVP odds from FILE (an
mvp_odds blob a scratch run wrote) instead of output/mvp_odds.json.

4c2: the new hub's Players rows are written beside the payload, not in it:
output/hub_players.json (regenerable, not state), or <stem>_players.json
beside --out PATH.
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
    ap.add_argument("--out", default=None,
                    help="write the payload here instead of output/hub_state.json (never a state path)")
    ap.add_argument("--mvp-odds", default=None,
                    help="with --out only: read the MVP odds from this file (a scratch preview)")
    a = ap.parse_args(argv)
    odds = None
    if a.mvp_odds is not None:
        if a.out is None:
            print("REFUSED: --mvp-odds is for a scratch build (--out) only")
            return 1
        import json
        odds = json.loads(Path(a.mvp_odds).read_text(encoding="utf-8"))
    from modules import hub_state, player_actuals, hub_archive, live_lines_page
    t0 = time.time()
    if a.out is not None:
        from modules.hub_publish import scratch_refusal
        refusal = scratch_refusal(a.base_path, a.out)
        if refusal:
            print(f"REFUSED: {refusal}")
            return 1
    try:
        players = {}
        payload = hub_state.build(a.base_path, allow_engine_mismatch=a.allow_engine_mismatch, players_out=players,
                                  **({"mvp_odds_blob": odds} if odds is not None else {}))
    except (hub_state.HubInputError, player_actuals.ActualsError, hub_archive.ArchiveError,
            live_lines_page.EngineMismatch) as e:
        print(f"REFUSED: {e}")
        return 1
    from modules import hub_version
    if hub_version.version(a.base_path) == "v2":   # 5b: stored as the nightly stores it under v2
        from modules.hub_v2 import data as v2data
        v2data.store_v2(payload)
    if a.out is None:
        p = hub_state.write(a.base_path, payload)
        if players:                    # 4c2: the Players rows, beside it (output/hub_players.json)
            hub_state.write_players(a.base_path, players)
    else:
        from modules.data_loader import atomic_write_json
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(p, payload, indent=1)
        if players:                    # 4c2: the Players file beside it (hub_state.players_path_for)
            atomic_write_json(hub_state.players_path_for(p), players, indent=None)
    print(f"Wrote {p} for week {payload['week']} ({payload['league_day']}) in {time.time() - t0:.1f} s.")
    if payload["header"]["engine_mismatch"]:
        print(f"  ENGINE MISMATCH (allowed): {payload['header']['engine_mismatch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
