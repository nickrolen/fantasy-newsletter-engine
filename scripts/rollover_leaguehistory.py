#!/usr/bin/env python3
"""
rollover_leaguehistory.py -- Fold a finished season into LEAGUEHISTORY.xlsx.

WHY
---
LEAGUEHISTORY.xlsx is a four-row cumulative summary, one row per manager. It
has two kinds of column:

    *_to_date / regular_season_record / playoff_record / seasons_completed
        the permanent all-time record
    *_current_season / record_current_season
        this season only, accumulated weekly by update_leaguehistory.py

update_leaguehistory.py only ever ADDS to the current-season columns. Nothing
folds them into the to-date totals at season end -- there is no rollover mode,
and start_new_season.py deliberately never touches this file.

So without this step, week 1 of the new season starts adding on top of last
season's numbers, and the all-time record silently stops advancing. Unlike the
player-log rollup, nothing downstream errors -- the totals just quietly go
wrong and stay wrong.

DANGER -- READ THIS
-------------------
Populated current-season columns do NOT prove the to-date columns are missing
this season. The sheet is maintained by hand, and a season can be accumulated
into the to-date totals while the current-season columns are simply left
filled in. That is exactly what happened in 2025-26: running this script
blind double-counted every to-date field.

There is no way to detect that from the sheet alone. So the operator must
confirm it. If the to-date totals already include the finished season, the
only thing left to do is clear the current-season columns:

    py scripts/rollover_leaguehistory.py --zero-only --execute

WHAT IT DOES
------------
For each manager:
    regular_season_record       += regular-season W-L (weeks 1..N)
    playoff_record              += post-season W-L (the remainder)
    total_points_scored_to_date += total_points_current_season
    total_moves_made_to_date    += total_moves_current_season
    seasons_completed           += 1
    titles_won                  += 1 for the regular-season winner
    playoff_championships       += 1 for the playoff champion
    every *_current_season column -> 0

The regular/post split comes from RECORDS.json, which tracks W-L over weeks
1..regular_season_weeks only. Post-season W-L is record_current_season minus
that, so the two always reconcile to the 23 games actually played.

Champion and regular-season winner are derived and printed for review; both
can be overridden, which is what you will want when the playoff format
changes.

USAGE
    py scripts/rollover_leaguehistory.py                    # preview
    py scripts/rollover_leaguehistory.py --execute
    py scripts/rollover_leaguehistory.py --champion Garrett --execute

EXIT CODES
    0 = success (or a clean dry run)
    1 = refused or failed; nothing was written
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import openpyxl

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import CURRENT_SEASON, MANAGERS  # noqa: E402
from modules.season_outcomes import (  # noqa: E402
    build_matchups, build_standings, cup_champion, league_champion,
    playoff_champion,
)

LEAGUEHISTORY = PROJECT_ROOT / "data" / "LEAGUEHISTORY.xlsx"
RECORDS = PROJECT_ROOT / "config" / "RECORDS.json"
SCHEDULE = PROJECT_ROOT / "config" / "SCHEDULE.json"

CURRENT_SUFFIX = "_current_season"
RECORD_RE = re.compile(r"\(?\s*(\d+)\s*-\s*(\d+)\s*\)?")


def rel(p):
    try:
        return str(Path(p).relative_to(PROJECT_ROOT))
    except ValueError:
        return str(p)


def fail(msg):
    print(f"\nREFUSED: {msg}\nNothing was written.")
    return 1


def parse_record(value):
    """'(140-83)' -> (140, 83)."""
    m = RECORD_RE.search(str(value or ""))
    if not m:
        raise ValueError(f"cannot parse a W-L record from {value!r}")
    return int(m.group(1)), int(m.group(2))


def fmt_record(w, l):
    return f"({w}-{l})"


def num(v):
    return 0 if v is None or v == "" else float(v)


def derive_outcomes(records, schedule):
    """Return (league_champion, playoff_champion, standings).

    This used to work the old format out by hand: "the champion is the winner
    of the final week, among whoever won the week before". That is right for a
    two-week single-game bracket and wrong from 2026-27, where the final two
    weeks are the CUP -- so it would have credited the Cup winner with a
    playoff championship in LEAGUEHISTORY.xlsx, permanently, and the real
    weeks 19-21 series winner with nothing.

    It also picked the regular-season winner out of manager_season_totals,
    whose W-L spans every week played rather than the regular season.

    Both now come from modules/season_outcomes, which reads the week
    boundaries out of league_config and is the same code the history rollup
    uses. One definition of who won what.
    """
    rows = build_matchups(CURRENT_SEASON, records, schedule)
    if not rows:
        return None, None, []
    standings = build_standings(CURRENT_SEASON, rows)
    return league_champion(standings), playoff_champion(standings), standings


def derive_cup_champion(records, schedule):
    """The Cup winner, or None for a season that had no Cup."""
    rows = build_matchups(CURRENT_SEASON, records, schedule)
    return cup_champion(CURRENT_SEASON, rows) if rows else None


def main():
    parser = argparse.ArgumentParser(
        description="Fold a finished season into LEAGUEHISTORY.xlsx."
    )
    parser.add_argument("--execute", action="store_true",
                        help="write (default is a dry run)")
    parser.add_argument("--zero-only", action="store_true",
                        help="ONLY clear the current-season columns. Use when "
                             "the to-date totals already include this season "
                             "(e.g. it was accumulated by hand).")
    parser.add_argument("--champion", default=None,
                        help="override the derived playoff champion")
    parser.add_argument("--regular-season-winner", default=None,
                        help="override the derived regular-season winner")
    parser.add_argument("--season", default=None,
                        help=f"season label for reporting (default {CURRENT_SEASON})")
    args = parser.parse_args()
    season = args.season or CURRENT_SEASON

    for p in (LEAGUEHISTORY, RECORDS, SCHEDULE):
        if not p.exists():
            return fail(f"required file not found: {rel(p)}")

    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    schedule = json.loads(SCHEDULE.read_text(encoding="utf-8"))

    wb = openpyxl.load_workbook(LEAGUEHISTORY)
    ws = wb.active
    headers = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(headers) if h}

    required = ["manager_name", "seasons_completed", "regular_season_record",
                "playoff_record", "titles_won", "playoff_championships",
                "total_points_scored_to_date", "total_points_current_season",
                "total_moves_made_to_date", "total_moves_current_season",
                "record_current_season"]
    missing = [c for c in required if c not in col]
    if missing:
        return fail(f"LEAGUEHISTORY.xlsx is missing columns: {missing}")

    current_cols = [h for h in headers if h and h.endswith(CURRENT_SUFFIX)]

    # Already rolled over? Every current-season column being empty is the tell.
    live = False
    for r in range(2, ws.max_row + 1):
        if ws.cell(row=r, column=col["manager_name"]).value is None:
            continue
        for h in current_cols:
            v = ws.cell(row=r, column=col[h]).value
            if h == "record_current_season":
                try:
                    if parse_record(v) != (0, 0):
                        live = True
                except ValueError:
                    pass
            elif num(v) != 0:
                live = True
    if not live:
        return fail("all *_current_season columns are already zero -- this "
                    "season looks rolled over. Nothing to do.")

    if args.zero_only:
        print("=" * 66)
        print(f"  LEAGUEHISTORY -- CLEAR CURRENT-SEASON COLUMNS ONLY ({season})")
        print("=" * 66)
        print("\n  To-date totals will NOT be touched.")
        print(f"  Clearing: {', '.join(current_cols)}\n")
        for r in range(2, ws.max_row + 1):
            name = ws.cell(row=r, column=col["manager_name"]).value
            if not name:
                continue
            vals = {h: ws.cell(row=r, column=col[h]).value for h in current_cols}
            print(f"    {str(name).strip():9} {vals}")
        if not args.execute:
            print("\n  [DRY-RUN] Nothing written.")
            return 0
        backup = LEAGUEHISTORY.with_suffix(".xlsx.bak")
        shutil.copy2(LEAGUEHISTORY, backup)
        print(f"\n  Backup: {rel(backup)}")
        for r in range(2, ws.max_row + 1):
            if not ws.cell(row=r, column=col["manager_name"]).value:
                continue
            for h in current_cols:
                ws.cell(row=r, column=col[h],
                        value="(0-0)" if h == "record_current_season" else 0)
        wb.save(LEAGUEHISTORY)
        print("  Cleared. To-date totals unchanged.")
        return 0

    reg_winner, champion, standings = derive_outcomes(records, schedule)
    cup = derive_cup_champion(records, schedule)
    reg_by_manager = {row["manager"]: (row["reg_wins"], row["reg_losses"])
                      for row in standings}
    if args.regular_season_winner:
        reg_winner = args.regular_season_winner
    if args.champion:
        champion = args.champion

    totals = records.get("manager_season_totals", {})

    print("=" * 66)
    print(f"  LEAGUEHISTORY ROLLOVER -- {season}")
    print("=" * 66)
    print(f"\n  Regular-season winner : {reg_winner}"
          f"{'  (overridden)' if args.regular_season_winner else '  (derived)'}"
          f"   -> titles_won +1")
    print(f"  Playoff champion      : {champion}"
          f"{'  (overridden)' if args.champion else '  (derived)'}"
          f"   -> playoff_championships +1")
    if cup:
        print(f"  Cup champion          : {cup}   -> no column for this yet")
        print("      LEAGUEHISTORY.xlsx has titles_won and "
              "playoff_championships but no cup_championships. Add the column "
              "and this will fill it; until then record the Cup winner in "
              "league_config keeper_rules.cup_winners, which is what next "
              "season's keeper counts read.")
    if not champion:
        return fail("could not determine the champion; pass --champion")

    print(f"\n  Clearing {len(current_cols)} current-season column(s): "
          f"{', '.join(current_cols)}")
    print("\n  Per manager:\n")

    plan = []
    for r in range(2, ws.max_row + 1):
        name = ws.cell(row=r, column=col["manager_name"]).value
        if not name:
            continue
        name = str(name).strip()

        cur_w, cur_l = parse_record(ws.cell(row=r, column=col["record_current_season"]).value)
        # The regular-season split comes from the standings, which bound it to
        # that season's own regular season. It used to come from
        # manager_season_totals, whose W-L spans every week played -- fine
        # while the postseason was two games, wrong now it is eight.
        if name in reg_by_manager:
            reg_w, reg_l = reg_by_manager[name]
            # RECORDS.json keeps its own copy in manager_season_totals. If the
            # two disagree, one of them is wrong and writing either into the
            # permanent history is a coin flip.
            t = totals.get(name)
            if t and (int(t.get("wins", 0)), int(t.get("losses", 0))) != (reg_w, reg_l):
                return fail(
                    f"{name}: manager_season_totals says "
                    f"{t.get('wins')}-{t.get('losses')} for the regular season "
                    f"but the week-by-week results say {reg_w}-{reg_l}. "
                    "These must reconcile before this is written to "
                    "LEAGUEHISTORY.xlsx.")
        else:
            t = totals.get(name, {})
            reg_w, reg_l = int(t.get("wins", 0)), int(t.get("losses", 0))
        # NOTE: from 2026-27 this remainder is the six-week bracket AND the
        # two-week Cup, eight games, all landing in playoff_record. The
        # arithmetic reconciles; the label is broad until there is a
        # cup_record column.
        po_w, po_l = cur_w - reg_w, cur_l - reg_l
        if po_w < 0 or po_l < 0:
            return fail(
                f"{name}: regular-season record ({reg_w}-{reg_l}) from RECORDS.json "
                f"exceeds record_current_season ({cur_w}-{cur_l}). These must reconcile."
            )

        old_reg = parse_record(ws.cell(row=r, column=col["regular_season_record"]).value)
        old_po = parse_record(ws.cell(row=r, column=col["playoff_record"]).value)
        old_pts = num(ws.cell(row=r, column=col["total_points_scored_to_date"]).value)
        cur_pts = num(ws.cell(row=r, column=col["total_points_current_season"]).value)
        old_mv = num(ws.cell(row=r, column=col["total_moves_made_to_date"]).value)
        cur_mv = num(ws.cell(row=r, column=col["total_moves_current_season"]).value)
        old_sc = int(num(ws.cell(row=r, column=col["seasons_completed"]).value))
        old_tw = int(num(ws.cell(row=r, column=col["titles_won"]).value))
        old_pc = int(num(ws.cell(row=r, column=col["playoff_championships"]).value))

        new = {
            "regular_season_record": fmt_record(old_reg[0] + reg_w, old_reg[1] + reg_l),
            "playoff_record": fmt_record(old_po[0] + po_w, old_po[1] + po_l),
            "total_points_scored_to_date": round(old_pts + cur_pts, 2),
            "total_moves_made_to_date": int(old_mv + cur_mv),
            "seasons_completed": old_sc + 1,
            "titles_won": old_tw + (1 if name == reg_winner else 0),
            "playoff_championships": old_pc + (1 if name == champion else 0),
        }
        plan.append((r, name, new))

        print(f"    {name}")
        print(f"      season split: regular {reg_w}-{reg_l}, playoff {po_w}-{po_l} "
              f"(from record_current_season {cur_w}-{cur_l})")
        print(f"      regular_season_record  {fmt_record(*old_reg)} -> {new['regular_season_record']}")
        print(f"      playoff_record         {fmt_record(*old_po)} -> {new['playoff_record']}")
        print(f"      points_to_date         {old_pts:,.2f} -> {new['total_points_scored_to_date']:,.2f}")
        print(f"      moves_to_date          {int(old_mv)} -> {new['total_moves_made_to_date']}")
        print(f"      seasons_completed      {old_sc} -> {new['seasons_completed']}")
        if new["titles_won"] != old_tw:
            print(f"      titles_won             {old_tw} -> {new['titles_won']}  (regular-season winner)")
        if new["playoff_championships"] != old_pc:
            print(f"      playoff_championships  {old_pc} -> {new['playoff_championships']}  (champion)")
        print()

    print("  " + "!" * 62)
    print("  THIS ADDS to the to-date columns. Confirm they do NOT already")
    print("  include this season. Populated current-season columns are NOT")
    print("  evidence of that -- the sheet is maintained by hand, and a season")
    print("  can be accumulated while those columns are left filled in.")
    print("  If the to-date totals already include it, you want --zero-only.")
    print("  " + "!" * 62)

    if not args.execute:
        print("\n  [DRY-RUN] Nothing written.")
        print("  Check the split, the two winners, and the warning above.")
        return 0

    backup = LEAGUEHISTORY.with_suffix(".xlsx.bak")
    shutil.copy2(LEAGUEHISTORY, backup)
    print(f"  Backup: {rel(backup)}")

    for r, _name, new in plan:
        for k, v in new.items():
            ws.cell(row=r, column=col[k], value=v)
        for h in current_cols:
            ws.cell(row=r, column=col[h],
                    value="(0-0)" if h == "record_current_season" else 0)
    wb.save(LEAGUEHISTORY)

    # Verify from disk.
    wb2 = openpyxl.load_workbook(LEAGUEHISTORY)
    ws2 = wb2.active
    problems = []
    for r, name, new in plan:
        for k, expected in new.items():
            got = ws2.cell(row=r, column=col[k]).value
            if isinstance(expected, float):
                if abs(num(got) - expected) > 0.01:
                    problems.append(f"{name}.{k}: {got} != {expected}")
            elif str(got) != str(expected):
                problems.append(f"{name}.{k}: {got!r} != {expected!r}")
        for h in current_cols:
            got = ws2.cell(row=r, column=col[h]).value
            want = "(0-0)" if h == "record_current_season" else 0
            if str(got) != str(want):
                problems.append(f"{name}.{h} not cleared: {got!r}")
    if problems:
        print("\n  VERIFICATION FAILED:")
        for p in problems[:10]:
            print(f"    - {p}")
        print(f"\n  Restore from {backup.name}.")
        return 1

    print(f"  Wrote and verified {len(plan)} manager rows.")
    print("\n  Next: py scripts/start_new_season.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
