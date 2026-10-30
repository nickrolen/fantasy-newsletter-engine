"""
transaction_rulings.py -- the commissioner's rulings on transactions.

config/TRANSACTION_RULINGS.json (tracked). Yahoo's transaction log is what
happened; a ruling is what COUNTS. On 2026-10-26 Garrett added Paul George and
dropped him the same day -- Benton had already claimed George in the group
chat, unapplied. Nick voided the add on 10-30 and set Garrett's week-2 move
count from 3 to 2. Yahoo's log still holds the add, so every sync would count
it again, and build_add_budget read 3 used, 0 left.

    {"date": "2026-10-26", "manager": "Garrett", "type": "add",
     "player": "Paul George", "ruling": "void", "by": "Nick", "on": "2026-10-30",
     "reason": "..."}

WHAT A RULING DOES. "void" on an "add": the add does not count against the
weekly budget and is not listed as an add (waivers_week{N}.txt, the add
budget, waiver ROI). It does NOT touch rosters: the ROSTERS.json sync still
applies the add and whatever followed it (here the same-day drop, so there is
no roster effect to undo). A ruling that should also change a roster has to
say so in a field this module does not know yet -- and an unknown field
RAISES rather than being ignored. So does any other type or ruling.

LOUD, NOT SILENT. A ruling must match exactly one transaction in the window
it falls in (date, manager, type, player -- the player through PlayerIndex),
or the sync raises naming it -- a typo cannot quietly do nothing. A reader of
a waivers file raises the same way unless the file records that the ruling
was applied when it was written ("# RULING applied: ..."). Every application
is printed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RULINGS_FILE = Path("config") / "TRANSACTION_RULINGS.json"
FIELDS = ("date", "manager", "type", "player", "ruling", "by", "on", "reason")
TYPES = ("add",)
RULINGS = ("void",)
APPLIED_PREFIX = "# RULING applied: "
_LINE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s+(.+)$")


class RulingError(ValueError):
    """A ruling that is malformed, or matches no transaction."""


@dataclass(frozen=True)
class Ruling:
    date: str
    manager: str
    type: str
    player: str
    ruling: str
    by: str
    on: str
    reason: str

    def label(self) -> str:
        return (f"{self.ruling} {self.date} {self.manager} {self.type} {self.player} "
                f"({self.by}, {self.on})")

    def matches(self, d, manager: str, kind: str, player: str) -> bool:
        from .data_loader import PlayerIndex
        return (str(d)[:10] == self.date and manager == self.manager and kind == self.type
                and PlayerIndex({self.player: True}).get(player) is not None)


def load_rulings(base_path) -> list[Ruling]:
    """Every ruling, validated. No file is no rulings."""
    path = Path(base_path) / RULINGS_FILE
    if not path.is_file():
        return []
    blob = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i, r in enumerate(blob.get("rulings", [])):
        where = f"{RULINGS_FILE} ruling {i + 1}"
        missing = [f for f in FIELDS if not str(r.get(f, "")).strip()]
        if missing:
            raise RulingError(f"{where}: missing {missing}")
        unknown = sorted(set(r) - set(FIELDS))
        if unknown:
            raise RulingError(f"{where}: unknown field(s) {unknown} -- a ruling only voids "
                              "counting and listing; anything more must be built, not ignored")
        if r["type"] not in TYPES or r["ruling"] not in RULINGS:
            raise RulingError(f"{where}: only {RULINGS} on {TYPES} is defined, not "
                              f"{r['ruling']!r} on {r['type']!r}")
        date.fromisoformat(r["date"])
        out.append(Ruling(**{f: str(r[f]).strip() for f in FIELDS}))
    return out


def _in(r: Ruling, since, until) -> bool:
    d = date.fromisoformat(r.date)
    return (since is None or d >= since) and (until is None or d <= until)


def apply_to_transactions(transactions: list[dict], rulings: list[Ruling], since=None,
                          until=None, echo=print) -> tuple[list[dict], list[Ruling]]:
    """(the transactions that count, the rulings applied) for a sync window
    [since, until]. Every ruling dated in the window must match exactly one
    transaction, or this RAISES. Transactions are sync_transactions' dicts."""
    kept, applied = list(transactions), []
    for r in rulings:
        if not _in(r, since, until):
            continue
        hits = [t for t in kept
                if r.matches(t["date"], t.get("manager", ""), t["type"], t["player_name"])]
        if len(hits) != 1:
            raise RulingError(f"ruling '{r.label()}' matches {len(hits)} transactions in Yahoo's "
                              f"log for {since} to {until or 'today'}, not 1 -- fix "
                              f"{RULINGS_FILE}")
        kept.remove(hits[0])
        applied.append(r)
        echo(f"  RULING applied: {r.label()} -- {r.reason}")
    return kept, applied


def applied_lines(applied: list[Ruling]) -> list[str]:
    """The record a waivers file keeps of the rulings applied when it was written."""
    return [f"{APPLIED_PREFIX}{r.label()}" for r in applied]


def week_of(day: str, schedule: dict):
    d = date.fromisoformat(day)
    for w in (schedule or {}).get("weeks", []):
        if date.fromisoformat(str(w["start_date"])[:10]) <= d <= date.fromisoformat(
                str(w["end_date"])[:10]):
            return int(w["week"])
    return None


def waiver_lines(path, base_path, week: int, schedule: dict) -> tuple[list[str], list[Ruling]]:
    """(the file's lines with voided adds removed, the rulings this read
    applied). A ruling for `week` must either match exactly one add line here
    or be recorded in the file as already applied; otherwise this RAISES."""
    from .data_loader import MANAGERS
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    rulings = []
    for r in load_rulings(base_path):
        wk = week_of(r.date, schedule)
        if wk is None:
            raise RulingError(f"ruling '{r.label()}' is dated in no fantasy week of the "
                              "schedule given -- it cannot be placed")
        if wk == int(week):
            rulings.append(r)
    recorded = {ln[len(APPLIED_PREFIX):].strip() for ln in lines if ln.startswith(APPLIED_PREFIX)}
    managers = sorted(MANAGERS, key=len, reverse=True)

    def parsed(ln):
        m = _LINE.match(ln.strip())
        if not m:
            return None
        for mgr in managers:
            if m.group(2).startswith(f"{mgr}: "):
                player = re.sub(r"\s*\(via [^)]*\)\s*$", "", m.group(2)[len(mgr) + 2:]).strip()
                return m.group(1), mgr, player
        return None

    keep, applied = list(lines), []
    for r in rulings:
        hits = [i for i, ln in enumerate(keep)
                if (p := parsed(ln)) and r.matches(p[0], p[1], "add", p[2])]
        if len(hits) == 1:
            del keep[hits[0]]
            applied.append(r)
        elif not hits and r.label() in recorded:
            continue
        else:
            raise RulingError(f"ruling '{r.label()}' matches {len(hits)} adds in {path} and the "
                              "file does not record it as applied -- fix "
                              f"{RULINGS_FILE} or the file")
    return keep, applied


def rewrite_waivers_file(path, base_path, week: int, schedule: dict, echo=print) -> list[Ruling]:
    """Rewrite an existing waivers file with the rulings applied: the voided
    lines removed and a "# RULING applied:" record added under the header.
    Touches nothing else -- not ROSTERS.json, not Yahoo. Idempotent."""
    keep, applied = waiver_lines(path, base_path, week, schedule)
    if not applied:
        echo(f"  {path}: no ruling to apply")
        return []
    head = 0
    while head < len(keep) and keep[head].startswith("#"):
        head += 1
    keep[head:head] = applied_lines(applied)
    Path(path).write_text("\n".join(keep) + "\n", encoding="utf-8")
    for r in applied:
        echo(f"  RULING applied to {path}: {r.label()} -- {r.reason}")
    return applied
