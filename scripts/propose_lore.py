"""
Propose league-lore entries from the data, and refresh the ones already
there. Nick approves, edits or rejects each (scripts/review_lore.py).

    python scripts/propose_lore.py            # scan, propose, refresh
    python scripts/propose_lore.py --refresh  # recompute existing only

Never changes an entry's status, never rewrites a written entry, and never
re-proposes anything already in the file. Rejected entries stay in the file
with their decision log; review_lore.py --revisit brings them back.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import lore as L  # noqa: E402
from modules.data_loader import (  # noqa: E402
    CURRENT_SEASON, MANAGERS, regular_season_weeks_for)


def _json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def current_draft(base: Path, have: set) -> list:
    """This season's picks, once its draft has happened and if all_drafts
    does not already hold them."""
    blob = _json(base / "config" / "DRAFT_PICKS_CURRENT.json", {})
    picks = [p for p in blob.get("picks", []) if p.get("player_name")]
    if not picks or blob.get("season") != CURRENT_SEASON or CURRENT_SEASON in have:
        return []
    return picks


def build_cells(base: Path, perms: int = L.PERMUTATIONS):
    hist = base / "data" / "historical"
    matchups = _json(hist / "all_matchups.json", [])
    playerlog = _json(hist / "HISTORICAL_PLAYERLOG.json", [])
    drafts = _json(hist / "all_drafts.json", [])
    # all_drafts.json holds COMPLETED seasons only (the pull_current_draft
    # trap); the season in progress has its draft in DRAFT_PICKS_CURRENT.json.
    # Without it every loyalty fact was a draft behind from draft day to the
    # season's end: on 2026-10-13 the approved lines read "of 9 drafts ...
    # to 2025-26" two days after the tenth.
    drafts = drafts + current_draft(base, {d.get("season") for d in drafts})
    schedule = _json(base / "config" / "SCHEDULE.json", {})
    records = _json(base / "config" / "RECORDS.json", {})
    have = {m["season"] for m in matchups}
    if CURRENT_SEASON not in have:
        matchups = matchups + L.current_season_matchups(
            schedule, records.get("weekly_scores", {}), CURRENT_SEASON)
    games = L.games_from_matchups(matchups)
    months = L.week_months(playerlog, schedule, CURRENT_SEASON)
    positions = L.positions_from_playerlog(playerlog)
    return L.scan(games, months, regular_season_weeks_for, drafts,
                  positions, perms=perms), len(games)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--base", default=str(ROOT))
    args = ap.parse_args(argv)
    base = Path(args.base)
    lore = L.load(base)
    cells, n_games = build_cells(base)
    changed = L.refresh(lore, cells)
    new = []
    if not args.refresh:
        L.benjamini_hochberg(cells)
        new += L.propose(lore, cells)
        drafts = [(Path(f).name, Path(f).read_text(encoding="utf-8"))
                  for f in sorted(glob.glob(str(base / "archive" / "*" /
                                                "assets" / "WEEK*_DRAFT.md")))
                  + sorted(glob.glob(str(base / "assets" /
                                         "WEEK*_DRAFT.md")))]
        players = set()
        for f in glob.glob(str(base / "archive" / "*" / "output" /
                               "stats_report_week*.json")):
            from modules.claim_check import players_in
            players |= players_in(_json(Path(f), {}))
        cfg = _json(base / "config" / "league_config.json", {})
        new += L.propose_aliases(
            lore, [t for _, t in drafts], players,
            reserved=set(cfg.get("manager_to_team", {}).values()) |
            set(MANAGERS))
        # Newsletter mythology is read, not regex-mined: the six 2025-26
        # newsletters are data-dense, and a keyword pass found three lines
        # (two of them the same claim). The curated myth-* entries came from
        # reading them; new newsletters go through the same reading.
    path = L.save(base, lore)
    tested = [c for c in cells if c.tested]
    import numpy as np
    k05 = int(np.sum(np.array([c.p for c in tested]) <= L.FACT_P))
    print(f"lore: scanned {len(tested)} tested cells over {n_games // 2} "
          f"matchups; {k05} at p <= {L.FACT_P} (chance alone gives about "
          f"{round(L.FACT_P * len(tested))}); "
          f"{sum(1 for c in tested if c.q <= L.FDR_Q)} survive FDR {L.FDR_Q}.")
    by = {}
    for e in new:
        by[e.get("strength", e["kind"])] = by.get(
            e.get("strength", e["kind"]), 0) + 1
    print(f"lore: {len(new)} new proposal(s) {by}; {len(changed)} entr"
          f"{'y' if len(changed) == 1 else 'ies'} changed state -> {path}")
    for i in changed:
        print(f"  state changed: {i}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
