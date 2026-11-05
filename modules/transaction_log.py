"""
transaction_log.py -- every Yahoo transaction, kept (step 1c; Nick, 11-03).

Yahoo's transaction log holds adds, drops, trades and the exact time of each.
sync_transactions used to keep only the adds, by date, in the weekly waivers
files, and throw the drops and the times away. The hub's moves feed shows
drops and exact times (Nick, 11-03), so the sync now keeps the whole log here:

    data/transaction_log.jsonl   (private league state, config/STATE_MANIFEST.json)

One JSON object per line, APPEND-ONLY (modules/jsonl_log). Two kinds of row:

  {"row": "transaction",                       one per Yahoo transaction
   "key": "478.l.16778.tr.90",                 Yahoo's transaction key: never twice
   "id": 90, "type": "add" | "drop" | "add/drop" | "trade", "status": "successful",
   "timestamp": 1793649440,                    Yahoo's Unix seconds
   "time": "2026-11-02T12:57:20-08:00",        the league clock (Pacific)
   "league_day": "2026-11-02", "fantasy_week": 3 (null: before the season / after it),
   "players": [{"name", "player_key", "action": "add" | "drop" | "trade",
                "from": {"type", "team_key", "team", "manager"},
                "to":   {"type", "team_key", "team", "manager"}}],
   "rulings": [{"kind", "player", "label", "reason", ("claim_week" | "effective")}],
   "logged_at", "logged_by"}

  {"row": "rulings", "key": ..., "rulings": [...], "logged_at", "logged_by"}
      A TRANSACTION_RULINGS ruling written after the transaction was logged
      (Nick writes the claim rulings after the moves are in Yahoo, and the
      nightly run may log the moves first). The transaction row is never
      rewritten: the latest rulings row for a key is the rulings that apply.

RULES (tests/test_transaction_log.py):
  - a key is logged once; a second sync of the same Yahoo log appends nothing;
  - a key already logged whose Yahoo record has CHANGED raises
    (TransactionChanged): the type, status, time, and each player's key,
    action and source and destination (type and team KEY) are compared. A
    team's display name and its manager are not: a rename is not a changed
    transaction;
  - an unknown transaction type, player action or status raises;
  - times are the league clock (league_clock), never the machine's.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from .jsonl_log import LogCorrupt, append_rows, read_rows

LOG_FILE = Path("data") / "transaction_log.jsonl"
TYPES = ("add", "drop", "add/drop", "trade")
ACTIONS = ("add", "drop", "trade")
STATUSES = ("successful",)


class TransactionLogError(ValueError):
    """The log, or a Yahoo record headed for it, is not what this module defines."""


class TransactionChanged(TransactionLogError):
    """Yahoo now reports a different record under a key already logged."""


def week_containing(schedule: dict, day: date):
    """The fantasy week whose dates hold `day`, or None (before or after the
    season). A transaction's LISTING week, for the log and the feed's marks;
    which budget an add uses is transaction_rulings.add_budget_week's alone."""
    for w in (schedule or {}).get("weeks", []):
        if date.fromisoformat(str(w["start_date"])[:10]) <= day <= date.fromisoformat(
                str(w["end_date"])[:10]):
            return int(w["week"])
    return None


def strip_accents(text: str) -> str:
    """The spelling sync_transactions has always used for a player's name."""
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")


# =============================================================================
# Yahoo's record -> a row
# =============================================================================

def _player_entries(raw: dict) -> list:
    out = []
    players = raw.get("players") or {}
    for k, entry in players.items():
        if k == "count":
            continue
        if not isinstance(entry, dict) or len(entry.get("player") or []) < 2:
            raise TransactionLogError(f"Yahoo transaction {raw.get('transaction_key')}: a player "
                                      f"entry is not [info, transaction_data]: {entry!r:.200}")
        info, wrap = entry["player"][0], entry["player"][1]
        name, key = None, None
        for d in info if isinstance(info, list) else []:
            if isinstance(d, dict) and "name" in d:
                name = (d["name"] or {}).get("full")
            if isinstance(d, dict) and "player_key" in d:
                key = d["player_key"]
        td = (wrap or {}).get("transaction_data")
        if isinstance(td, list):
            td = td[0] if td else None
        elif isinstance(td, dict) and "0" in td:
            td = td["0"]
        if not name or not key or not isinstance(td, dict):
            raise TransactionLogError(f"Yahoo transaction {raw.get('transaction_key')}: a player "
                                      "with no name, key or transaction_data")
        out.append((name, key, td))
    if not out:
        raise TransactionLogError(f"Yahoo transaction {raw.get('transaction_key')} names no player")
    return out


def _side(td: dict, which: str, manager_of) -> dict:
    kind = td.get(f"{which}_type")
    if not kind:
        raise TransactionLogError(f"transaction data with no {which}_type: {td!r:.200}")
    team_key = td.get(f"{which}_team_key")
    team = td.get(f"{which}_team_name")
    side = {"type": kind, "team_key": team_key, "team": team, "manager": None}
    if kind == "team":
        if not team_key and not team:
            raise TransactionLogError(f"a {which} team with neither key nor name: {td!r:.200}")
        side["manager"] = manager_of(team, team_key)
    return side


def row_from_yahoo(raw: dict, *, manager_of, week_of, rulings=(), logged_at: str = None,
                   logged_by: str = None) -> dict:
    """The log row for one of Yahoo's records (lg.transactions(...) items).

    manager_of(team_name, team_key) -> manager (data_loader.manager_for_team,
    which raises on an unknown team); week_of(league_day) -> fantasy week or
    None. Raises on anything this module does not define."""
    from .league_clock import league_tz
    key = raw.get("transaction_key")
    if not key:
        raise TransactionLogError(f"a Yahoo transaction with no key: {raw!r:.200}")
    kind = str(raw.get("type", ""))
    if kind not in TYPES:
        raise TransactionLogError(f"Yahoo transaction {key}: unknown type {kind!r}; defined: {TYPES}")
    status = str(raw.get("status", ""))
    if status not in STATUSES:
        raise TransactionLogError(f"Yahoo transaction {key}: status {status!r} -- only "
                                  f"{STATUSES} are logged; anything else is not a move yet")
    try:
        ts = int(raw.get("timestamp"))
    except (TypeError, ValueError):
        raise TransactionLogError(f"Yahoo transaction {key} has no usable timestamp "
                                  f"({raw.get('timestamp')!r}); refusing to guess its time") from None
    at = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(league_tz())
    players = []
    for name, pkey, td in _player_entries(raw):
        action = str(td.get("type", ""))
        if action not in ACTIONS:
            raise TransactionLogError(f"Yahoo transaction {key}: unknown player action {action!r}")
        players.append({"name": strip_accents(name), "player_key": pkey, "action": action,
                        "from": _side(td, "source", manager_of),
                        "to": _side(td, "destination", manager_of)})
    day = at.date()
    row = {"row": "transaction", "key": key, "id": int(raw.get("transaction_id") or 0),
           "type": kind, "status": status, "timestamp": ts,
           "time": at.isoformat(timespec="seconds"), "league_day": day.isoformat(),
           "fantasy_week": week_of(day), "players": players,
           "rulings": rulings_for(players, day, rulings),
           "logged_at": logged_at, "logged_by": logged_by}
    return row


def identity(row: dict) -> dict:
    """What a Yahoo record IS, for the changed-record check: everything but
    display names, managers and the rulings."""
    return {"type": row["type"], "status": row["status"], "timestamp": int(row["timestamp"]),
            "players": [{"player_key": p["player_key"], "action": p["action"],
                         "from": (p["from"]["type"], p["from"].get("team_key")),
                         "to": (p["to"]["type"], p["to"].get("team_key"))}
                        for p in row["players"]]}


# =============================================================================
# rulings
# =============================================================================

def rulings_for(players: list, day: date, rulings) -> list:
    """The TRANSACTION_RULINGS rulings that name an add in this transaction
    (transaction_rulings' own match: Yahoo date, manager, type, player)."""
    out = []
    for p in players:
        if p["action"] != "add" or p["to"]["type"] != "team":
            continue
        for r in rulings:
            if r.matches(day, p["to"]["manager"], "add", p["name"]):
                one = {"kind": r.kind, "player": p["name"], "label": r.label(), "reason": r.reason}
                if r.kind == "claim_week":
                    one["claim_week"] = int(r.claim_week)
                if r.kind == "effective_date":
                    one["effective"] = r.effective
                out.append(one)
    return sorted(out, key=lambda x: (x["player"], x["kind"]))


# =============================================================================
# the file
# =============================================================================

def read(base_path=".") -> list:
    """Every row, validated: a transaction key logged twice, a rulings row for
    a key never logged, or a row of an unknown kind raises."""
    rows = read_rows(Path(base_path) / LOG_FILE, LOG_FILE.as_posix())
    seen = set()
    for i, r in enumerate(rows, start=1):
        kind = r.get("row")
        if kind == "transaction":
            for f in ("key", "type", "status", "timestamp", "time", "league_day", "players",
                      "rulings"):
                if f not in r:
                    raise LogCorrupt(f"{LOG_FILE} line {i}: missing {f!r}")
            if r["key"] in seen:
                raise LogCorrupt(f"{LOG_FILE} line {i}: transaction {r['key']} is logged twice")
            seen.add(r["key"])
        elif kind == "rulings":
            if r.get("key") not in seen:
                raise LogCorrupt(f"{LOG_FILE} line {i}: rulings for {r.get('key')}, which is not "
                                 "logged above it")
        else:
            raise LogCorrupt(f"{LOG_FILE} line {i}: unknown row kind {kind!r}")
    return rows


def transactions(base_path=".", rows: list = None) -> list:
    """The logged transactions, oldest first, each with the rulings that apply
    now (the latest rulings row for its key, else its own)."""
    rows = read(base_path) if rows is None else rows
    latest = {}
    for r in rows:
        if r["row"] == "rulings":
            latest[r["key"]] = r["rulings"]
    out = []
    for r in rows:
        if r["row"] == "transaction":
            t = dict(r)
            if r["key"] in latest:
                t["rulings"] = latest[r["key"]]
            out.append(t)
    return sorted(out, key=lambda t: (int(t["timestamp"]), t.get("id", 0)))


def sync(base_path, raw_transactions: list, *, manager_of, week_of, rulings=(),
         run_id: str = None, now: datetime = None, page_full: bool = False) -> dict:
    """Append every Yahoo transaction not yet logged, and a rulings row for a
    logged one whose applicable rulings changed. Raises TransactionChanged
    (writing nothing) if Yahoo's record for a logged key changed.

    page_full: Yahoo returned as many rows as one call asks for, so older
    ones may be cut off. That is fine while the fetch overlaps the log (the
    newest page reaches back to something already kept); without an overlap
    there may be a gap, and it RAISES rather than log around it.
    {"appended": n, "rulings_rows": m, "total": logged transactions}."""
    from .league_clock import league_now
    stamp = (now or league_now()).isoformat(timespec="seconds")
    rows = read(base_path)
    have = {t["key"]: t for t in transactions(base_path, rows)}
    if page_full and not ({r.get("transaction_key") for r in raw_transactions} & set(have)):
        raise TransactionLogError(
            f"Yahoo returned a full page ({len(raw_transactions)} transactions) and none of them is "
            "already logged: older transactions may have been cut off, and the log would have a "
            "gap. Page the Yahoo fetch before logging. Nothing was written.")
    new, amend, seen = [], [], set()
    for raw in raw_transactions:
        row = row_from_yahoo(raw, manager_of=manager_of, week_of=week_of, rulings=rulings,
                             logged_at=stamp, logged_by=run_id)
        if row["key"] in seen:
            raise TransactionLogError(f"Yahoo returned transaction {row['key']} twice in one fetch")
        seen.add(row["key"])
        old = have.get(row["key"])
        if old is None:
            new.append(row)
            continue
        if identity(old) != identity(row):
            raise TransactionChanged(
                f"Yahoo's record for transaction {row['key']} changed since it was logged "
                f"({old['time']}): logged {identity(old)}, now {identity(row)}. The log is never "
                "rewritten; nothing was written. Ask Nick.")
        if old["rulings"] != row["rulings"]:
            amend.append({"row": "rulings", "key": row["key"], "rulings": row["rulings"],
                          "logged_at": stamp, "logged_by": run_id})
    new.sort(key=lambda r: (r["timestamp"], r["id"]))
    append_rows(Path(base_path) / LOG_FILE, new + amend)
    return {"appended": len(new), "rulings_rows": len(amend), "total": len(have) + len(new)}


def after(base_path, moment: datetime, rows: list = None) -> list:
    """Logged transactions strictly after `moment` (an aware datetime)."""
    if moment.tzinfo is None:
        raise ValueError("after() needs an aware datetime")
    cut = int(moment.timestamp())
    return [t for t in transactions(base_path, rows) if int(t["timestamp"]) > cut]


# =============================================================================
# the hub's moves feed
# =============================================================================

# The moves feed's marker for each kind of part (task 39): never colour alone.
PART_MARKER = {"add": "+", "drop": "\u2212", "trade": "\u21c4"}


def _part(kind: str, text: str) -> dict:
    return {"kind": kind, "marker": PART_MARKER[kind], "text": text}


def feed_item(t: dict, schedule: dict) -> dict:
    """One transaction as the hub's moves feed shows it: who, what, the time
    (Pacific), and the "(week N claim)" / "(week N add)" marks the waivers
    files carry, from the rulings that apply. `parts` is the same as `what`,
    one line per add, drop or trade side, each with its kind and its marker
    (+ / minus / the two-way arrow), adds first: the page colours each by
    kind (task 39). `what` stays the parts' texts joined."""
    at = datetime.fromisoformat(t["time"])
    by_player = {r["player"]: r for r in t.get("rulings") or []}
    parts, notes, who = [], [], []
    if t["type"] == "trade":
        got = {}
        for p in t["players"]:
            got.setdefault(p["to"]["manager"] or p["to"]["type"], []).append(p["name"])
        tparts = [_part("trade", f"{m} gets {', '.join(v)}") for m, v in got.items()]
        what = "; ".join(x["text"] for x in tparts)
        return {"_ts": int(t["timestamp"]), "day": at.strftime("%a"), "date": f"{at.month}/{at.day}",
                "time": at.strftime("%I:%M %p").lstrip("0"), "who": "Trade:", "what": what,
                "parts": tparts, "note": "", "state": "Applied", "kind": "trade"}
    for p in sorted(t["players"], key=lambda p: (p["action"] != "add", p["name"])):
        if p["action"] == "add":
            parts.append(_part("add", f"added {p['name']}"))
            who.append(p["to"]["manager"])
            r = by_player.get(p["name"])
            if r and r["kind"] == "claim_week":
                notes.append(f"week {r['claim_week']} claim")
            elif r and r["kind"] == "effective_date":
                made = week_containing(schedule, date.fromisoformat(t["league_day"]))
                listed = week_containing(schedule, date.fromisoformat(r["effective"]))
                if made is not None and listed is not None and made != listed:
                    notes.append(f"week {made} add")
            elif r and r["kind"] == "void":
                notes.append("voided: counts nowhere")
        else:
            parts.append(_part("drop", f"dropped {p['name']}"))
            who.append(p["from"]["manager"])
    managers = sorted({w for w in who if w})
    if len(managers) != 1:
        raise TransactionLogError(f"transaction {t['key']} ({t['type']}) is not one manager's "
                                  f"move: {managers}")
    kind = "add" if t["type"] == "add" else "drop" if t["type"] == "drop" else "add-drop"
    return {"_ts": int(t["timestamp"]), "day": at.strftime("%a"), "date": f"{at.month}/{at.day}",
            "time": at.strftime("%I:%M %p").lstrip("0"), "who": managers[0],
            "what": ", ".join(x["text"] for x in parts), "parts": parts, "note": "; ".join(notes),
            "state": "Applied", "kind": kind}
