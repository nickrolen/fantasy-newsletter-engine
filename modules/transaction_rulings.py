"""
transaction_rulings.py -- the commissioner's rulings on transactions.

config/TRANSACTION_RULINGS.json (tracked). Yahoo's transaction log and the
logs pulled from Yahoo (LINEUPS.xlsx, PLAYERLOG.xlsx) are what Yahoo recorded;
a ruling is what COUNTS. Two kinds:

VOID (no "kind", or "kind": "void") -- on 2026-10-26 Garrett added Paul George
and dropped him the same day; Benton had already claimed George in the group
chat, unapplied. Nick voided the add on 10-30.

    {"date": "2026-10-26", "manager": "Garrett", "type": "add",
     "player": "Paul George", "ruling": "void", "by": "Nick", "on": "2026-10-30",
     "reason": "..."}

  The add does not count against the weekly budget and is not listed as an
  add (waivers_week{N}.txt, the add budget, waiver ROI). It does NOT touch
  rosters: the ROSTERS.json sync still applies the add and whatever followed
  it (here the same-day drop, so there is no roster effect to undo).

EFFECTIVE DATE ("kind": "effective_date") -- Hayden added Zach LaVine late on
Sunday 10-25, after every game that day had finished; the league counts it as
a week 2 move. Yahoo's roster for 10-25 nonetheless lists LaVine on Hayden's
bench, so the log pulled on 10-26 has a 10-25 bench row (44.25 FP) and every
reader blamed Hayden for a 44.2-point blunder he could not have avoided.

    {"kind": "effective_date", "manager": "Hayden", "player": "Zach LaVine",
     "type": "add", "transaction_date": "2026-10-26", "effective": "2026-10-26",
     "by": "Nick", "on": "2026-10-30", "reason": "..."}

  The player is not on that manager's roster for any day before `effective`:
  every reader of LINEUPS/PLAYERLOG drops that player-manager's rows dated
  before it (apply_effective_dates) -- at load time, never by rewriting the
  logs, so the next log pull cannot bring the row back. And the add counts in
  the fantasy week containing `effective`, whatever date the sync stamped.

Anything else -- another kind, type or ruling, a missing or unknown field --
RAISES rather than being ignored: a ruling only does what is written here.

LOUD, NOT SILENT. A ruling must match exactly one transaction in the window it
falls in (date, manager, type, player -- the player through PlayerIndex), or
the sync raises naming it, so a typo cannot quietly do nothing. A reader of a
waivers file raises the same way unless the file records that the ruling was
applied when it was written ("# RULING applied: ..."). An effective date that
would drop a STARTED row raises: points that counted on Yahoo's scoreboard
mean the ruling is wrong. Every application is printed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

RULINGS_FILE = Path("config") / "TRANSACTION_RULINGS.json"
APPLIED_PREFIX = "# RULING applied: "
_LINE = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s+(.+)$")
BENCH_SLOTS = {"BN", "IL", "IL+"}


class RulingError(ValueError):
    """A ruling that is malformed, or matches no transaction."""


def _same_player(a: str, b: str) -> bool:
    from .data_loader import PlayerIndex
    return PlayerIndex({a: True}).get(b) is not None


@dataclass(frozen=True)
class Ruling:
    """A void."""
    date: str
    manager: str
    type: str
    player: str
    ruling: str
    by: str
    on: str
    reason: str
    kind = "void"
    FIELDS = ("date", "manager", "type", "player", "ruling", "by", "on", "reason")

    def label(self) -> str:
        return (f"{self.ruling} {self.date} {self.manager} {self.type} {self.player} "
                f"({self.by}, {self.on})")

    def matches(self, d, manager: str, kind: str, player: str) -> bool:
        return (str(d)[:10] == self.date and manager == self.manager and kind == self.type
                and _same_player(self.player, player))


@dataclass(frozen=True)
class EffectiveDate:
    """An add that takes effect on `effective`, not on the day Yahoo shows."""
    manager: str
    player: str
    type: str
    transaction_date: str
    effective: str
    by: str
    on: str
    reason: str
    kind = "effective_date"
    FIELDS = ("manager", "player", "type", "transaction_date", "effective", "by", "on", "reason")

    def label(self) -> str:
        return (f"effective {self.effective} {self.transaction_date} {self.manager} {self.type} "
                f"{self.player} ({self.by}, {self.on})")

    def matches(self, d, manager: str, kind: str, player: str) -> bool:
        return (str(d)[:10] == self.transaction_date and manager == self.manager
                and kind == self.type and _same_player(self.player, player))


KINDS = {"void": Ruling, "effective_date": EffectiveDate}


def load_all(base_path) -> list:
    """Every ruling of every kind, validated. No file is no rulings."""
    path = Path(base_path) / RULINGS_FILE
    if not path.is_file():
        return []
    blob = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i, r in enumerate(blob.get("rulings", [])):
        where = f"{RULINGS_FILE} ruling {i + 1}"
        kind = r.get("kind", "void")
        cls = KINDS.get(kind)
        if cls is None:
            raise RulingError(f"{where}: unknown kind {kind!r}; defined: {sorted(KINDS)}")
        body = {k: v for k, v in r.items() if k != "kind"}
        missing = [f for f in cls.FIELDS if not str(body.get(f, "")).strip()]
        if missing:
            raise RulingError(f"{where}: missing {missing}")
        unknown = sorted(set(body) - set(cls.FIELDS))
        if unknown:
            raise RulingError(f"{where}: unknown field(s) {unknown} -- a ruling only does what "
                              "transaction_rulings defines; anything more must be built, not ignored")
        if body["type"] != "add":
            raise RulingError(f"{where}: only rulings on an 'add' are defined, not {body['type']!r}")
        if cls is Ruling and body["ruling"] != "void":
            raise RulingError(f"{where}: only 'void' is defined, not {body['ruling']!r}")
        for f in ("date", "transaction_date", "effective"):
            if f in body:
                date.fromisoformat(str(body[f]))
        out.append(cls(**{f: str(body[f]).strip() for f in cls.FIELDS}))
    return out


def load_rulings(base_path) -> list:
    """Every ruling (both kinds). Kept under its first name for its callers."""
    return load_all(base_path)


def voids(rulings) -> list:
    return [r for r in rulings if r.kind == "void"]


def effective_dates(rulings) -> list:
    return [r for r in rulings if r.kind == "effective_date"]


def _in(day: str, since, until) -> bool:
    d = date.fromisoformat(str(day)[:10])
    return (since is None or d >= since) and (until is None or d <= until)


# =============================================================================
# the sync: Yahoo's transaction log
# =============================================================================

def apply_to_transactions(transactions: list[dict], rulings: list, since=None, until=None,
                          echo=print) -> tuple[list[dict], list]:
    """(the transactions that count in [since, until], the rulings applied).

    Effective dates first: an add named by one is re-dated to `effective`
    (so it lands in the week the league counts it in); every effective-date
    ruling whose transaction_date is in the window must match exactly one add.
    Then the window is applied to the (re-dated) dates. Then voids: every void
    dated in the window must match exactly one transaction. A ruling that
    matches the wrong number RAISES. Transactions are sync_transactions'
    dicts; the list given may reach past the window (a day of slack, so an
    add stamped the day before its effective date is still seen)."""
    work = [dict(t) for t in transactions]
    applied = []
    for r in effective_dates(rulings):
        hits = [t for t in work if r.matches(t["date"], t.get("manager", ""), t["type"],
                                             t["player_name"])]
        if _in(r.transaction_date, since, until) and len(hits) != 1:
            raise RulingError(f"ruling '{r.label()}' matches {len(hits)} transactions in Yahoo's "
                              f"log for {since} to {until or 'today'}, not 1 -- fix {RULINGS_FILE}")
        for t in hits[:1]:
            t["date"] = date.fromisoformat(r.effective)
            if _in(r.effective, since, until):
                applied.append(r)
                echo(f"  RULING applied: {r.label()} -- {r.reason}")
    work = [t for t in work if _in(t["date"], since, until)]
    for r in voids(rulings):
        if not _in(r.date, since, until):
            continue
        hits = [t for t in work
                if r.matches(t["date"], t.get("manager", ""), t["type"], t["player_name"])]
        if len(hits) != 1:
            raise RulingError(f"ruling '{r.label()}' matches {len(hits)} transactions in Yahoo's "
                              f"log for {since} to {until or 'today'}, not 1 -- fix "
                              f"{RULINGS_FILE}")
        work.remove(hits[0])
        applied.append(r)
        echo(f"  RULING applied: {r.label()} -- {r.reason}")
    return work, applied


def applied_lines(applied: list) -> list[str]:
    """The record a waivers file keeps of the rulings applied when it was written."""
    return [f"{APPLIED_PREFIX}{r.label()}" for r in applied]


def week_of(day: str, schedule: dict):
    d = date.fromisoformat(str(day)[:10])
    for w in (schedule or {}).get("weeks", []):
        if date.fromisoformat(str(w["start_date"])[:10]) <= d <= date.fromisoformat(
                str(w["end_date"])[:10]):
            return int(w["week"])
    return None


def _placed(r, schedule, *days) -> list:
    weeks = [week_of(d, schedule) for d in days]
    if any(w is None for w in weeks):
        raise RulingError(f"ruling '{r.label()}' is dated in no fantasy week of the "
                          "schedule given -- it cannot be placed")
    return weeks


def _parse_line(ln: str):
    from .data_loader import MANAGERS
    m = _LINE.match(ln.strip())
    if not m:
        return None
    for mgr in sorted(MANAGERS, key=len, reverse=True):
        if m.group(2).startswith(f"{mgr}: "):
            player = re.sub(r"\s*\(via [^)]*\)\s*$", "", m.group(2)[len(mgr) + 2:]).strip()
            return m.group(1), mgr, player
    return None


# =============================================================================
# readers of waivers_week{N}.txt
# =============================================================================

def waiver_lines(path, base_path, week: int, schedule: dict) -> tuple[list[str], list]:
    """(the file's lines with the rulings applied, the rulings this read
    applied).

    Void: a void for `week` must match exactly one add line here or be
    recorded in the file as already applied; the line is removed.
    Effective date: an add stamped in this week (transaction_date) must be
    here (or recorded); it is removed when `effective` is in another week.
    An add whose `effective` is in this week but was stamped in another is
    added here, as "- [effective] Manager: Player". Otherwise this RAISES."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    recorded = {ln[len(APPLIED_PREFIX):].strip() for ln in lines if ln.startswith(APPLIED_PREFIX)}
    rulings = load_all(base_path)
    keep, applied = list(lines), []

    def hits_for(r, day):
        return [i for i, ln in enumerate(keep)
                if (p := _parse_line(ln)) and p[0] == day and p[1] == r.manager
                and _same_player(r.player, p[2])]

    for r in effective_dates(rulings):
        stamped, counts = _placed(r, schedule, r.transaction_date, r.effective)
        if stamped == int(week):
            hits = hits_for(r, r.transaction_date)
            if len(hits) > 1 or (not hits and r.label() not in recorded):
                raise RulingError(f"ruling '{r.label()}' matches {len(hits)} adds in {path} and "
                                  f"the file does not record it as applied -- fix {RULINGS_FILE} "
                                  "or the file")
            if hits and counts != int(week):
                del keep[hits[0]]
                applied.append(r)
        elif counts == int(week) and r.label() not in recorded \
                and not hits_for(r, r.effective):
            keep.append(f"- [{r.effective}] {r.manager}: {r.player}")
            applied.append(r)

    for r in voids(rulings):
        if _placed(r, schedule, r.date)[0] != int(week):
            continue
        hits = [i for i, ln in enumerate(keep)
                if (p := _parse_line(ln)) and r.matches(p[0], p[1], "add", p[2])]
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


def rewrite_waivers_file(path, base_path, week: int, schedule: dict, echo=print) -> list:
    """Rewrite an existing waivers file with the rulings applied: voided lines
    removed, effective-date adds moved to their week, and a "# RULING
    applied:" record added under the header. Touches nothing else -- not
    ROSTERS.json, not Yahoo. Idempotent."""
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


# =============================================================================
# readers of LINEUPS.xlsx / PLAYERLOG.xlsx
# =============================================================================

def _schedule(base_path) -> dict:
    p = Path(base_path) / "config" / "SCHEDULE.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _add_on_file(r: EffectiveDate, base_path, schedule) -> bool:
    """The add an effective-date ruling names, in the synced waivers files:
    stamped on transaction_date in its week's file, or already moved to
    `effective` in that week's file, or recorded there as applied."""
    for day in (r.transaction_date, r.effective):
        wk = week_of(day, schedule)
        f = Path(base_path) / "data" / f"waivers_week{wk}.txt"
        if wk is None or not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        if any(ln.startswith(APPLIED_PREFIX) and ln[len(APPLIED_PREFIX):].strip() == r.label()
               for ln in lines):
            return True
        for ln in lines:
            p = _parse_line(ln)
            if p and p[0] == day and p[1] == r.manager and _same_player(r.player, p[2]):
                return True
    return False


def apply_effective_dates(df, base_path, source: str, schedule: dict = None, echo=print):
    """`df` (LINEUPS or PLAYERLOG rows, source "lineups" / "playerlog") without
    the rows an effective-date ruling takes off a roster: that player with that
    manager, dated before `effective`. The file is never rewritten.

    RAISES when a ruling names no add in the synced waivers files, or when a
    row it would drop was STARTED (a lineup slot, or PLAYERLOG started=True):
    points that counted on Yahoo's scoreboard mean the ruling is wrong."""
    rulings = effective_dates(load_all(base_path))
    if not rulings or df is None or len(df) == 0:
        return df
    if schedule is None:
        schedule = _schedule(base_path)
    import pandas as pd
    days = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    drop = pd.Series(False, index=df.index)
    for r in rulings:
        if not _add_on_file(r, base_path, schedule):
            raise RulingError(f"ruling '{r.label()}' matches no add in the synced waivers files "
                              f"(data/waivers_week*.txt) -- fix {RULINGS_FILE}")
        from .data_loader import PlayerIndex
        one = PlayerIndex({r.player: True})
        cand = ((df["manager"].astype(str) == r.manager) & (days < r.effective)).tolist()
        mine = pd.Series([bool(c) and one.get(n) is not None
                          for n, c in zip(df["player_name"].astype(str), cand)],
                         index=df.index, dtype=bool)
        if not mine.any():
            continue
        rows = df[mine]
        if source == "lineups":
            started = ~rows["slot"].astype(str).str.upper().isin(BENCH_SLOTS)
        elif source == "playerlog":
            started = rows["started"].fillna(False).astype(bool)
        else:
            raise ValueError(f"source must be 'lineups' or 'playerlog', not {source!r}")
        if started.any():
            bad = ", ".join(sorted(days[rows[started].index].unique()))
            raise RulingError(f"ruling '{r.label()}' would drop {r.player}'s STARTED {source} "
                              f"row(s) for {r.manager} on {bad}: points that counted on Yahoo's "
                              "scoreboard -- the ruling is wrong")
        drop |= mine
        echo(f"  RULING applied ({source}): {r.label()} -- dropped {int(mine.sum())} row(s) "
             f"before {r.effective}")
    return df[~drop].copy() if drop.any() else df
