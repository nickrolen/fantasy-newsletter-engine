"""
override_history.py -- every change to config/INJURY_OVERRIDES.json, before
and after, append-only (task 26; Step 3a, HANDOFF_STEP3A s.2.1).

    output/override_history.jsonl        (league state, the manifest)

One row per change, written by scripts/overrides.py in the same call that
writes the file (add, set-return, set-notes, remove -- from the desk, from a
phone entry through scripts/apply_entry.py, or the nightly run's passed-return
removal, decision 13b):

    {"schema": 1, "at": <league clock, with offset>, "action": "add" |
     "set-return" | "set-notes" | "remove", "player": <the entry's name>,
     "before": <the entry, or null for an add>, "after": <the entry, or null
     for a remove>, ("replace": the desk's add --replace, before and after), "last_updated_before", "last_updated_after", "by": who
     ("overrides.py (desk)", "issue #12", "nightly (13b)"), "issue": N or null}

APPEND-ONLY (modules/jsonl_log): a row is never rewritten.

THE CLOSING LINE READS IT (design s.4.1, "no information from after the
close"): as_of() rebuilds the overrides as they stood at a moment -- Monday's
first tip -- by undoing, newest first, every change made after it. It RAISES
when the file and the history disagree (an entry that is not what the history
says the last change left: a hand edit after a recorded change), and
closing_line raises when an entry that governs the week carries an updated_at
after the tip with no record to undo. Entries written before the history began
have no updated_at: they are "before the history began", never given a time.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

SCHEMA = 1
HISTORY_FILE = Path("output") / "override_history.jsonl"
ACTIONS = ("add", "replace", "set-return", "set-notes", "remove")
ROW_KEYS = ("schema", "at", "action", "player", "before", "after", "last_updated_before",
            "last_updated_after", "by", "issue")


class OverrideHistoryError(RuntimeError):
    """The history is malformed, or the file and the history disagree."""


def path_for(base_path) -> Path:
    return Path(base_path) / HISTORY_FILE


def _aware(text, where: str) -> datetime:
    try:
        t = datetime.fromisoformat(str(text))
    except ValueError:
        raise OverrideHistoryError(f"{where}: {text!r} is not an ISO time") from None
    if t.tzinfo is None:
        raise OverrideHistoryError(f"{where}: {text!r} carries no offset (the league clock has one)")
    return t


def check_row(row: dict, where: str) -> None:
    miss = [k for k in ROW_KEYS if k not in row]
    if miss or row.get("schema") != SCHEMA:
        raise OverrideHistoryError(f"{where}: not a schema-{SCHEMA} override-history row (missing {miss})")
    if row["action"] not in ACTIONS:
        raise OverrideHistoryError(f"{where}: unknown action {row['action']!r}")
    _aware(row["at"], where)
    if row["action"] == "add" and (row["before"] is not None or row["after"] is None):
        raise OverrideHistoryError(f"{where}: an add has no before and an after")
    if row["action"] == "remove" and (row["before"] is None or row["after"] is not None):
        raise OverrideHistoryError(f"{where}: a remove has a before and no after")
    if row["action"] in ("replace", "set-return", "set-notes") and (row["before"] is None
                                                                    or row["after"] is None):
        raise OverrideHistoryError(f"{where}: an edit has a before and an after")


def read(base_path) -> list:
    """Every row, in order; [] when there is no file yet. A malformed row RAISES."""
    from . import jsonl_log
    p = path_for(base_path)
    try:
        rows = jsonl_log.read_rows(p, label=p.name)
    except jsonl_log.LogCorrupt as e:
        raise OverrideHistoryError(str(e)) from None
    for i, r in enumerate(rows, 1):
        check_row(r, f"{p.name} row {i}")
    return rows


def make_row(*, at: datetime, action: str, player: str, before, after, last_updated_before,
             last_updated_after, by: str, issue=None) -> dict:
    if at.tzinfo is None:
        raise OverrideHistoryError("an override-history time must be on the league clock (aware)")
    row = {"schema": SCHEMA, "at": at.isoformat(timespec="seconds"), "action": action,
           "player": str(player), "before": copy.deepcopy(before), "after": copy.deepcopy(after),
           "last_updated_before": last_updated_before, "last_updated_after": last_updated_after,
           "by": str(by), "issue": int(issue) if issue is not None else None}
    check_row(row, "the new row")
    return row


def append(base_path, row: dict) -> None:
    from . import jsonl_log
    check_row(row, "the new row")
    jsonl_log.append_rows(path_for(base_path), [row])


def applied_issue(base_path, issue: int):
    """The history row that applied phone issue #issue, or None."""
    for r in read(base_path):
        if r.get("issue") is not None and int(r["issue"]) == int(issue):
            return r
    return None


def _same(a, b) -> bool:
    return json.loads(json.dumps(a, sort_keys=True)) == json.loads(json.dumps(b, sort_keys=True))


def as_of(blob: dict, rows: list, moment: datetime) -> tuple:
    """(the overrides blob as it stood at `moment`, [the rows undone]).

    Undoes, newest first, every row whose time is after `moment`: the entry
    for its player must be exactly the row's `after` (absent for a remove),
    and becomes its `before` (absent for an add). A mismatch RAISES -- the
    file changed after that row with no record. last_updated goes back to the
    earliest undone row's last_updated_before. Never edits `blob`."""
    from .data_loader import PlayerIndex
    if moment.tzinfo is None:
        raise OverrideHistoryError("as_of needs an aware moment (the league clock)")
    out = copy.deepcopy(blob or {})
    players = list(out.get("players") or [])
    later = [r for r in rows if _aware(r["at"], "override history") > moment]
    for r in reversed(later):
        idx = PlayerIndex({str(e.get("player_name")): i for i, e in enumerate(players)})
        hit = idx.canonical(r["player"])
        cur = players[dict.__getitem__(idx, hit)] if hit is not None else None
        if r["after"] is None:
            if cur is not None:
                raise OverrideHistoryError(
                    f"{r['player']} was removed at {r['at']} ({r['by']}), but the file has an entry for "
                    "him: it changed after that with no history record")
        elif cur is None or not _same(cur, r["after"]):
            raise OverrideHistoryError(
                f"{r['player']}'s entry is not what the {r['action']} at {r['at']} ({r['by']}) left: "
                "the file changed after that with no history record")
        if r["before"] is None:
            players.pop(dict.__getitem__(idx, hit))
        elif cur is None:
            players.append(copy.deepcopy(r["before"]))
        else:
            players[dict.__getitem__(idx, hit)] = copy.deepcopy(r["before"])
    out["players"] = players
    if later:
        out["last_updated"] = later[0]["last_updated_before"]
    return out, later


def changed_after(entries, moment: datetime) -> list:
    """The entries whose updated_at is after `moment` (an entry with no
    updated_at was written before the history began: never after)."""
    out = []
    for e in entries or []:
        u = e.get("updated_at")
        if u and _aware(u, f"{e.get('player_name')}'s updated_at") > moment:
            out.append(e)
    return out
