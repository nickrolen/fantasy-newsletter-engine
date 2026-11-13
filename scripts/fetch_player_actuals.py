#!/usr/bin/env python3
"""
fetch_player_actuals.py -- cache every rostered player's daily fantasy points
and games played from Yahoo, one finished league day at a time; then (40b)
every non-rostered player the hub names, for the player cards.

    python scripts/fetch_player_actuals.py --dry-run     the plan and its calls; no Yahoo, nothing written
    python scripts/fetch_player_actuals.py

Writes data/player_actuals.json (private state; modules/player_actuals.py
says what is in it and why). A finished league day (before today, Pacific)
is fetched once and never again; a player new to a roster, or new to the
hub's lists, is backfilled from the season's first day. Read-only against
Yahoo.

The non-rostered players are every name output/hub_state.json shows (the free
agents, the stash, the trade block, the moves feed, advice), less the rostered
ones, with a Yahoo id by the engine's one rule (PLAYERLIST, then the
transaction log); at most config actuals.extra_players_max of them.

Refuses (exit 1) on any failed or malformed Yahoo line, naming the date and
the player; the days that completed before it stay written, a partial day is
never written. The rostered pass runs first and is written before the other
players are asked for. build_hub_state reads the file and refuses if it does
not cover yesterday for every rostered player.

The nightly run (modules/nightly, step 8) calls the same two passes before
the hub; then python scripts/state.py push after a desk run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import player_actuals as pa          # noqa: E402

SECONDS_PER_CALL = 0.23           # measured in step 1b (STEP1B_RESULT s.2)


def _extras_lines(x: dict) -> list:
    out = [f"Other players the hub names ({pa.HUB_STATE_RELPATH.as_posix()}, built {x['from']}): "
           f"{x['players']} with a Yahoo id (cap {x['cap']}), {len(x['no_id'])} without"]
    if x["backfilled"]:
        out.append(f"  new to the cache, backfilled from the season's first day: {', '.join(x['backfilled'])}")
    catch = sorted((n, k) for n, k in x["missing_days"].items() if n not in set(x["backfilled"]))
    if catch:
        out.append("  catching up: " + ", ".join(f"{n} ({k} day{'s' if k != 1 else ''})" for n, k in catch))
    if x["no_id"]:
        out.append(f"  no Yahoo id (the card keeps its note, never guessed): {', '.join(x['no_id'])}")
    return out


def dry_run(base: str) -> int:
    r = pa.rostered_dry_plan(base)
    rostered = dict(r["ids"], **{n: -1 for n in r["new"]})
    x = pa.update_extras(base, source=None, rostered=rostered, dry_run=True)
    print("DRY RUN: no Yahoo call made, nothing written.")
    print(f"Finished league days through {r['through']}.")
    print(f"Rostered players: {r['players']} (config/ROSTERS.json, matched to the cache's ids): "
          f"{r['planned_days']} day(s) to fetch, {r['planned_calls']} call(s)")
    if r["new"]:
        print(f"  new pickups (the real run reads their ids from Yahoo's rosters and backfills them): "
              f"{', '.join(r['new'])}")
    for line in _extras_lines(x):
        print(line)
    print(f"  {x['planned_days']} day(s) to fetch, {x['planned_calls']} call(s)")
    total = r["planned_calls"] + x["planned_calls"]
    print(f"PLANNED: {total} Yahoo call(s), about {round(total * SECONDS_PER_CALL)} s, plus the login. "
          "Then run it without --dry-run, then python scripts\\state.py push.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=".")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and its Yahoo calls; no Yahoo call, nothing written")
    a = ap.parse_args(argv)
    try:
        if a.dry_run:
            return dry_run(a.base_path)
        r = pa.update(a.base_path)
    except pa.ActualsError as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"Player actuals through {r['through']}: {r['players']} rostered players; "
          f"{len(r['days_fetched'])} day(s) fetched, {r['calls']} Yahoo call(s), {r['seconds']} s.")
    if r["backfilled"]:
        print(f"  backfilled from the season's first day: {', '.join(r['backfilled'])}")
    try:
        x = pa.update_extras(a.base_path, source=r["source"], rostered=r["ids"])
    except pa.ActualsError as e:
        print(f"REFUSED (the other players the hub names; the rostered days above are written): {e}")
        return 1
    for line in _extras_lines(x):
        print(line)
    print(f"  {len(x['days_fetched'])} day(s) fetched, {x['calls']} Yahoo call(s), {x['seconds']} s.")
    print("Then: python scripts\\state.py push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
