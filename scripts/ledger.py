"""
ledger.py -- the move ledger from Nick's desktop (step 2; phone entries are step 3).

    python scripts\\ledger.py add "Benton move: +Bane -Alexander-Walker"
    python scripts\\ledger.py add "Nick move: +Bane IL+Edwards" --at "2026-11-06 22:15"
    python scripts\\ledger.py add "Trade: Benton gets Tatum; Hayden gets Barnes"
    python scripts\\ledger.py add "..." --dry-run      check only; writes nothing
    python scripts\\ledger.py list                      pending and recent entries, with states
    python scripts\\ledger.py check                     every pending entry, checked again now
    python scripts\\ledger.py checklist [--week N]      the coming Monday's checklist (console)
    python scripts\\ledger.py void N --reason "..."     an entry Nick typed by mistake does nothing

Run it between `python scripts\\state.py pull` and `python scripts\\state.py push`,
like any manual run: the ledger is league state, and the checks read this
week's rosters, IL slots and tags as the cloud last synced them.

--at: when the claim was POSTED in the chat (Pacific, the league clock), if
it was entered later. It decides the claim's budget week (rule 7: a Sunday
claim counts for that Sunday's week). Default: now.

modules/move_ledger.py holds the rules; this file only reads arguments and
prints. It is the only program that writes config/MOVE_LEDGER.json.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _world(base, now=None):
    from modules import move_ledger as ml
    return ml.World.from_base(base, now=now)


def cmd_add(a) -> int:
    from modules import move_ledger as ml
    base = Path(a.base_path)
    ml.mode()                                       # a missing or unknown mode refuses first
    at = ml._parse_at(a.at) if a.at else None
    world = _world(base)
    rows, states = ml.read_rows(base), ml.read_states(base)
    row = ml.make_entry(world, a.entry, rows, states, claimed_at=at, entered_by="Nick (ledger.py)")
    print(f"entry {row['id']}: {row['text']}")
    print(f"  claimed {row['claimed_at'][:16].replace('T', ' ')} Pacific: week {row['claim_week']}'s "
          f"budget; applied in the {row['window']} window (week {row['window_week']})")
    for c in row["checks"]:
        print(f"  {c}" if c.startswith("WARNING: ") else f"  ok: {c}")
    if a.dry_run:
        print("--dry-run: nothing written")
        return 0
    ml.write_entries(base, rows, [row])
    print(f"written to {ml.LEDGER_FILE.as_posix()}. Push it: python scripts\\state.py push")
    return 0


def cmd_list(a) -> int:
    from modules import move_ledger as ml
    from modules.league_clock import league_now
    base = Path(a.base_path)
    rows, states = ml.read_rows(base), ml.read_states(base)
    today = league_now().date()
    shown = 0
    for e in ml.entries(rows):
        st = ml.state_of(e, states)
        recent = date.fromisoformat(e["window"]) >= today - timedelta(days=a.days)
        if st != "pending" and not recent:
            continue
        sr = ml.state_row(e, states)
        print(f"{e['id']:3d} [{st}] {e['text']}  -- claimed {e['claimed_at'][:16].replace('T', ' ')} "
              f"(week {e['claim_week']}), window {e['window']}"
              + (f"; {sr['why']}" if sr and st != "applied" else "")
              + (f"; VOIDED: {e['voided']['reason']}" if e["voided"] else ""))
        shown += 1
    if not shown:
        print(f"no pending entries and none with a window in the last {a.days} days")
    print(f"mode: {ml.mode()}")
    return 0


def cmd_check(a) -> int:
    from modules import move_ledger as ml
    base = Path(a.base_path)
    world = _world(base)
    rows, states = ml.read_rows(base), ml.read_states(base)
    res = ml.recheck(world, rows, states)
    if not res:
        print("no pending entries")
    bad = 0
    by_id = {e["id"]: e for e in ml.entries(rows)}
    for eid, why in res:
        print(f"{eid:3d} {'ok' if why == 'ok' else 'PROBLEM'}: {by_id[eid]['text']}"
              + ("" if why == "ok" else f"\n      {why}"))
        bad += why != "ok"
    return 1 if bad else 0


def cmd_checklist(a) -> int:
    from modules import move_ledger as ml
    base = Path(a.base_path)
    world = _world(base)
    rows, states = ml.read_rows(base), ml.read_states(base)
    week = a.week or (world.current_week() + (0 if world.now.date() == world.window_day(
        world.current_week()) else 1))
    cl = ml.checklist(world, rows, states, week)
    sts = {e["id"]: ml.state_of(e, states) for e in ml.entries(rows)}
    print("\n".join(ml.format_checklist(cl, sts)))
    return 1 if cl["stopped"] else 0


def cmd_void(a) -> int:
    from modules import move_ledger as ml
    row = ml.void(Path(a.base_path), a.entry_id, a.reason)
    print(f"entry {row['entry']} voided ({row['reason']}). Push it: python scripts\\state.py push")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("entry")
    p.add_argument("--at", help="when it was posted, 'YYYY-MM-DD HH:MM' Pacific (default: now)")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("list")
    p.add_argument("--days", type=int, default=14)
    sub.add_parser("check")
    p = sub.add_parser("checklist")
    p.add_argument("--week", type=int)
    p = sub.add_parser("void")
    p.add_argument("entry_id", type=int)
    p.add_argument("--reason", required=True)
    a = ap.parse_args(argv)
    from modules import move_ledger as ml
    try:
        return {"add": cmd_add, "list": cmd_list, "check": cmd_check, "checklist": cmd_checklist,
                "void": cmd_void}[a.cmd](a)
    except ml.EntryRefused as e:
        print(f"REFUSED: {e}")
        print("Nothing was written.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
