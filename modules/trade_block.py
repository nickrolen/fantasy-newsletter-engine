"""
trade_block.py -- the trade block (task 49, the simple form;
claude/HANDOFF_TRADE_BLOCK_2026-11-11.md s.1).

For each team: the players marked UNTOUCHABLE, the players ON THE BLOCK, and
the team's MODE (buying, selling or neutral), each with the day it was set.
The managers text Nick and Nick enters it from his phone as an issue
(modules/phone_entries' "Block:" forms, applied by scripts/apply_entry.py,
with the same author check, catch-up and comments as every phone entry).
There is no self-service form and no write path on the hub (shelved 11-11).

    config/TRADE_BLOCK.json             league state (config/STATE_MANIFEST.json)
    output/trade_block_history.jsonl    league state, append-only

THE FILE
    {"schema": 1, "season": "2026-27",
     "teams": {"Garrett": {"mode": "selling", "mode_set": "2026-11-11",
                           "untouchable": [{"player": "Victor Wembanyama", "set": "2026-11-11"}],
                           "block": [{"player": "Kyrie Irving", "set": "2026-11-11"}]}, ...}}
  - every manager of the config is a key, and only they;
  - mode is buying, selling or neutral; mode_set is the day it was set (the
    issue's day on the league clock), or null for a neutral never set;
  - a player is on at most one of a team's lists, once; "set" is the day he
    was put there.
  NO FILE means nothing has been entered this season (the empty block), but
  only while the history is empty too: a history with rows and no file
  RAISES (the file was lost, which is not the same as empty). A season other
  than the config's RAISES (the season reset has not reset it).

ONE WRITER: write_change() writes the file, then appends its history row. No
other code writes either file (tests/test_trade_block.py pins it).

THE HISTORY ROW
    {"schema": 1, "at": <league clock, with offset>, "action": "untouchable" |
     "block" | "remove" | "mode" | "clear" | "roster" | "deadline",
     "before": {manager: his team as it was}, "after": {manager: as it is},
     (the teams that changed, and only they), "moved": [player moved from one
     list to the other], "by": "issue #12" | "nightly", "issue": N or null}
  The file after the change is the file before it with each "after" team in
  place (tested).

THE RULES OF AN ENTRY (apply)
  - after the trade deadline (yahoo_settings.trade_deadline, the date the
    move ledger refuses chat trades after: move_ledger.trade_deadline) every
    entry is refused: "the trade deadline has passed";
  - untouchable / on the block: each player resolved with the ledger's
    resolver (move_ledger.resolve_name: a full name, else a unique last name;
    ambiguous lists the candidates) among THAT manager's roster
    (config/ROSTERS.json as synced). A player on another roster, or on none,
    refuses;
  - a player already on the other list is MOVED (the comment says so); one
    already on the same list refuses (nothing would change);
  - remove: each player must be on one of the team's lists;
  - a mode he already has, or a clear of a team with nothing set, refuses;
  - all or nothing: one refused player refuses the whole entry, and nothing
    is written.

UPKEEP (the nightly run, nightly.step_trade_block; neither re-prices anything)
  - a listed player no longer on that manager's roster (traded, dropped:
    config/ROSTERS.json as the night's sync left it) is taken off: one row,
    action "roster", by "nightly". A trade between two teams cleans both;
  - from the day after the trade deadline, the whole file is cleared (every
    list empty, every mode neutral with no date): one row, action
    "deadline", once (a cleared file has nothing to clear).

WHO READS IT
  current(base, rosters) is the one read for the hub (hub_state), the
  drafting prompts (prepare_prompts) and, later, advice V3: the block as
  stored, less any listed player no longer on that manager's roster (the
  12:01 AM run takes him off the file; until then he is not shown).

THE SEASON RESET (task 19c, not built here): the reset should write the new
season's empty file through write_change (action "clear" for every team,
by "season reset"), or move both files aside and start empty; until it does,
load() refuses the old season's file.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path

SCHEMA = 1
PATH = Path("config") / "TRADE_BLOCK.json"
HISTORY = Path("output") / "trade_block_history.jsonl"
MODES = ("buying", "selling", "neutral")
LISTS = ("untouchable", "block")
LIST_LABEL = {"untouchable": "Untouchable", "block": "On the block"}
MODE_LABEL = {"buying": "Buying", "selling": "Selling", "neutral": "Neutral"}
ACTIONS = ("untouchable", "block", "remove", "mode", "clear", "roster", "deadline")
ROW_KEYS = ("schema", "at", "action", "before", "after", "moved", "by", "issue")


class TradeBlockError(RuntimeError):
    """The file or its history is malformed, or they disagree."""


class BlockRefused(ValueError):
    """A trade-block entry that cannot be applied; nothing was written."""


# =============================================================================
# the file
# =============================================================================

def path_for(base) -> Path:
    return Path(base) / PATH


def history_path(base) -> Path:
    return Path(base) / HISTORY


def _config():
    from .data_loader import MANAGERS, CURRENT_SEASON
    if not CURRENT_SEASON:
        raise TradeBlockError("league_config.json season.current is missing")
    return list(MANAGERS), CURRENT_SEASON


def empty_team() -> dict:
    return {"mode": "neutral", "mode_set": None, "untouchable": [], "block": []}


def empty(managers=None, season: str = None) -> dict:
    cm, cs = _config()
    return {"schema": SCHEMA, "season": season or cs,
            "teams": {m: empty_team() for m in (managers or cm)}}


def _day(text, where: str) -> str:
    try:
        return date.fromisoformat(str(text)).isoformat()
    except ValueError:
        raise TradeBlockError(f"{where}: {text!r} is not a date (YYYY-MM-DD)") from None


def validate(blob: dict, managers=None, season: str = None, where: str = "config/TRADE_BLOCK.json") -> None:
    cm, cs = _config()
    managers, season = list(managers or cm), season or cs
    if not isinstance(blob, dict) or blob.get("schema") != SCHEMA:
        raise TradeBlockError(f"{where} is not a schema-{SCHEMA} trade block")
    if blob.get("season") != season:
        raise TradeBlockError(f"{where} is season {blob.get('season')!r}, the config's is {season!r}: "
                              "the season reset has not reset it")
    teams = blob.get("teams")
    if not isinstance(teams, dict) or set(teams) != set(managers):
        raise TradeBlockError(f"{where} names teams {sorted(teams or {})}; the managers are "
                              f"{sorted(managers)}")
    for m, t in teams.items():
        w = f"{where} {m}"
        if not isinstance(t, dict) or set(t) != {"mode", "mode_set", *LISTS}:
            raise TradeBlockError(f"{w}: keys {sorted(t or {})}, expected mode, mode_set, "
                                  f"{', '.join(LISTS)}")
        if t["mode"] not in MODES:
            raise TradeBlockError(f"{w}: mode {t['mode']!r} is not one of {MODES}")
        if t["mode_set"] is None:
            if t["mode"] != "neutral":
                raise TradeBlockError(f"{w}: mode {t['mode']} has no date it was set")
        else:
            _day(t["mode_set"], f"{w} mode_set")
        seen = set()
        for lst in LISTS:
            if not isinstance(t[lst], list):
                raise TradeBlockError(f"{w} {lst}: not a list")
            for e in t[lst]:
                if not isinstance(e, dict) or set(e) != {"player", "set"} or not str(e["player"]).strip():
                    raise TradeBlockError(f"{w} {lst}: {e!r} is not {{player, set}}")
                _day(e["set"], f"{w} {lst} {e['player']}")
                k = str(e["player"]).casefold()
                if k in seen:
                    raise TradeBlockError(f"{w}: {e['player']} is listed twice (a player is on one "
                                          "list, once)")
                seen.add(k)


def load(base, managers=None, season: str = None) -> dict:
    """The validated file. No file and no history: the empty block (nothing
    entered this season). No file but a history: RAISES."""
    p = path_for(base)
    if not p.is_file():
        rows = read_history(base)
        if rows:
            raise TradeBlockError(f"{PATH.as_posix()} is missing but {HISTORY.as_posix()} has "
                                  f"{len(rows)} row(s): the file was lost, not emptied. Restore it "
                                  "(python scripts\\state.py pull)")
        return empty(managers, season)
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TradeBlockError(f"{PATH.as_posix()} is not valid JSON: {e}") from None
    validate(blob, managers, season)
    return blob


def is_empty(blob: dict) -> bool:
    return all(t == empty_team() for t in blob["teams"].values())


# =============================================================================
# the history
# =============================================================================

def check_row(row: dict, where: str) -> None:
    miss = [k for k in ROW_KEYS if k not in row]
    if miss or row.get("schema") != SCHEMA:
        raise TradeBlockError(f"{where}: not a schema-{SCHEMA} trade-block history row (missing {miss})")
    if row["action"] not in ACTIONS:
        raise TradeBlockError(f"{where}: unknown action {row['action']!r}")
    try:
        at = datetime.fromisoformat(str(row["at"]))
    except ValueError:
        raise TradeBlockError(f"{where}: {row['at']!r} is not an ISO time") from None
    if at.tzinfo is None:
        raise TradeBlockError(f"{where}: {row['at']!r} carries no offset (the league clock has one)")
    if not isinstance(row["before"], dict) or not isinstance(row["after"], dict) or \
            set(row["before"]) != set(row["after"]) or not row["after"]:
        raise TradeBlockError(f"{where}: before and after must name the same changed teams")


def read_history(base) -> list:
    from . import jsonl_log
    p = history_path(base)
    try:
        rows = jsonl_log.read_rows(p, label=p.name)
    except jsonl_log.LogCorrupt as e:
        raise TradeBlockError(str(e)) from None
    for i, r in enumerate(rows, 1):
        check_row(r, f"{p.name} row {i}")
    return rows


def applied_issue(base, issue: int):
    """The history row that applied phone issue #issue, or None."""
    for r in read_history(base):
        if r.get("issue") is not None and int(r["issue"]) == int(issue):
            return r
    return None


def write_change(base, before: dict, after: dict, *, action: str, by: str, now: datetime,
                 issue=None, moved=None) -> dict:
    """THE ONE WRITER: config/TRADE_BLOCK.json, then its history row. `before`
    is the file as loaded, `after` the whole new file. Returns the row."""
    from . import jsonl_log
    from .data_loader import atomic_write_json
    if now.tzinfo is None:
        raise TradeBlockError("a trade-block change is timed on the league clock (aware)")
    validate(after)
    if before.get("season") != after.get("season"):
        raise TradeBlockError("a change never moves the file to another season")
    changed = sorted(m for m in after["teams"] if after["teams"][m] != before["teams"].get(m))
    if not changed:
        raise TradeBlockError("a trade-block change that changes nothing is not written")
    row = {"schema": SCHEMA, "at": now.isoformat(timespec="seconds"), "action": action,
           "before": {m: copy.deepcopy(before["teams"][m]) for m in changed},
           "after": {m: copy.deepcopy(after["teams"][m]) for m in changed},
           "moved": list(moved or []), "by": str(by), "issue": int(issue) if issue is not None else None}
    check_row(row, "the new row")
    atomic_write_json(path_for(base), after, indent=1)
    jsonl_log.append_rows(history_path(base), [row])
    return row


# =============================================================================
# rosters, names
# =============================================================================

def rosters_now(base, managers=None) -> dict:
    """{manager: [players]} from config/ROSTERS.json (Yahoo's rosters as the
    last sync left them). Every manager and only they, or it RAISES."""
    cm, _ = _config()
    managers = list(managers or cm)
    p = Path(base) / "config" / "ROSTERS.json"
    if not p.is_file():
        raise TradeBlockError("config/ROSTERS.json is missing: no roster to check a player against")
    blob = json.loads(p.read_text(encoding="utf-8"))
    r = blob.get("rosters") if isinstance(blob, dict) else None
    if not isinstance(r, dict) or set(r) != set(managers):
        raise TradeBlockError(f"config/ROSTERS.json has rosters for {sorted(r or {})}; the managers "
                              f"are {sorted(managers)}")
    return {m: list(v) for m, v in r.items()}


def _resolve_rostered(typed: str, manager: str, rosters: dict) -> str:
    """The player `typed` names on `manager`'s roster (the ledger's resolver).
    A player on another roster refuses, saying whose; on none, the nearest."""
    from . import move_ledger as ml
    try:
        return ml.resolve_name(typed, rosters[manager], f"on {manager}'s roster")
    except ml.NameAmbiguous as e:
        raise BlockRefused(str(e)) from None
    except ml.NameUnknown as e:
        own = str(e)
    others = {n: m for m, v in rosters.items() if m != manager for n in v}
    try:
        hit = ml.resolve_name(typed, list(others), "on another roster")
    except ml.EntryRefused:
        raise BlockRefused(own) from None
    raise BlockRefused(f"{hit} is on {others[hit]}'s roster, not {manager}'s: a player goes only on "
                       "his own manager's block")


def _resolve_listed(typed: str, manager: str, team: dict) -> str:
    from . import move_ledger as ml
    listed = [e["player"] for lst in LISTS for e in team[lst]]
    if not listed:
        raise BlockRefused(f"{manager} has no player on either list: nothing to remove")
    try:
        return ml.resolve_name(typed, listed, f"on {manager}'s lists")
    except ml.EntryRefused as e:
        raise BlockRefused(str(e)) from None


def _where(team: dict, player: str):
    for lst in LISTS:
        for e in team[lst]:
            if e["player"] == player:
                return lst, e
    return None, None


def md(day: str) -> str:
    d = date.fromisoformat(str(day))
    return f"{d.month:02d}-{d.day:02d}"


# =============================================================================
# an entry
# =============================================================================

def apply(base, parsed: dict, *, issue, created_at: datetime, now: datetime, by: str = None) -> dict:
    """Apply a parsed "Block:" entry (phone_entries.parse_title, kind "block").
    Returns {"manager", "action", "players" (resolved), "before" (his team),
    "after", "moved", "notes", "cause", "row"}. Refusals raise BlockRefused
    and write nothing."""
    from . import move_ledger as ml
    deadline = ml.trade_deadline()
    if now.date() > deadline:
        raise BlockRefused(f"the trade deadline has passed ({deadline.isoformat()}): the trade block "
                           "is closed until next season")
    if created_at.tzinfo is None or now.tzinfo is None:
        raise TradeBlockError("the entry's times must be on the league clock (aware)")
    m, action = parsed["manager"], parsed["action"]
    blob = load(base)
    if m not in blob["teams"]:
        raise BlockRefused(f"{m!r} is not a manager")
    new = copy.deepcopy(blob)
    team = new["teams"][m]
    day = created_at.date().isoformat()
    names, moved, notes = [], [], []
    if action in LISTS:
        rosters = rosters_now(base)
        for typed in parsed["players"]:
            n = _resolve_rostered(typed, m, rosters)
            if n in names:
                raise BlockRefused(f"{n} is named twice")
            names.append(n)
        other = "block" if action == "untouchable" else "untouchable"
        for n in names:
            cur, e = _where(team, n)
            if cur == action:
                raise BlockRefused(f"{n} is already {LIST_LABEL[action].lower()} for {m} (since "
                                   f"{md(e['set'])}): nothing to change")
            if cur == other:
                team[other] = [x for x in team[other] if x["player"] != n]
                moved.append(n)
                notes.append(f"{n} moved from {LIST_LABEL[other]} to {LIST_LABEL[action]}.")
            team[action].append({"player": n, "set": day})
    elif action == "remove":
        for typed in parsed["players"]:
            n = _resolve_listed(typed, m, blob["teams"][m])
            if n in names:
                raise BlockRefused(f"{n} is named twice")
            names.append(n)
        for n in names:
            cur, _ = _where(team, n)
            team[cur] = [x for x in team[cur] if x["player"] != n]
            notes.append(f"{n} taken off {LIST_LABEL[cur]}.")
    elif action == "mode":
        mode = parsed["mode"]
        if team["mode"] == mode:
            since = f" (since {md(team['mode_set'])})" if team["mode_set"] else ""
            raise BlockRefused(f"{m} is already {mode}{since}: nothing to change")
        team["mode"], team["mode_set"] = mode, day
    elif action == "clear":
        if not team["untouchable"] and not team["block"] and team["mode"] == "neutral":
            raise BlockRefused(f"{m} has nothing listed and is neutral: nothing to clear")
        new["teams"][m] = {"mode": "neutral", "mode_set": day, "untouchable": [], "block": []}
    else:
        raise TradeBlockError(f"unknown trade-block action {action!r}")
    row = write_change(base, blob, new, action=action, by=by or f"issue #{issue}", now=now,
                       issue=issue, moved=moved)
    return {"manager": m, "action": action, "players": names, "mode": parsed.get("mode"),
            "before": blob["teams"][m], "after": new["teams"][m], "moved": moved, "notes": notes,
            "cause": cause_of(m, action, names, parsed.get("mode")), "row": row}


def cause_of(manager: str, action: str, players, mode: str = None) -> str:
    """The refresh's --cause, from the entry itself: "trade block: Garrett selling"."""
    who = ", ".join(players or [])
    if action == "mode":
        return f"trade block: {manager} {mode}"
    if action == "untouchable":
        return f"trade block: {manager} untouchable {who}"
    if action == "block":
        return f"trade block: {manager} on the block {who}"
    if action == "remove":
        return f"trade block: {manager} removed {who}"
    if action == "clear":
        return f"trade block: {manager} cleared"
    raise ValueError(f"unknown action {action!r}")


# =============================================================================
# the nightly upkeep
# =============================================================================

def upkeep(base, rosters: dict, today: date, now: datetime) -> dict:
    """The nightly run's pass: {"cleared": bool, "removed": [{"manager",
    "player", "list"}], "row": the history row or None}. See the module
    docstring. No file and nothing to do: nothing is written (no file is
    created)."""
    from . import move_ledger as ml
    from .data_loader import PlayerIndex
    deadline = ml.trade_deadline()
    blob = load(base)
    if today > deadline:
        if is_empty(blob):
            return {"cleared": False, "removed": [], "row": None, "deadline": deadline.isoformat()}
        new = copy.deepcopy(blob)
        new["teams"] = {m: empty_team() for m in blob["teams"]}
        row = write_change(base, blob, new, action="deadline", by="nightly", now=now)
        return {"cleared": True, "removed": [], "row": row, "deadline": deadline.isoformat()}
    if set(rosters) != set(blob["teams"]):
        raise TradeBlockError(f"the rosters name {sorted(rosters)}; the trade block's teams are "
                              f"{sorted(blob['teams'])}")
    new = copy.deepcopy(blob)
    removed = []
    for m, team in new["teams"].items():
        idx = PlayerIndex({n: n for n in rosters[m]})
        for lst in LISTS:
            keep = []
            for e in team[lst]:
                if idx.canonical(e["player"]) is None:
                    removed.append({"manager": m, "player": e["player"], "list": lst})
                else:
                    keep.append(e)
            team[lst] = keep
    if not removed:
        return {"cleared": False, "removed": [], "row": None, "deadline": deadline.isoformat()}
    row = write_change(base, blob, new, action="roster", by="nightly", now=now)
    return {"cleared": False, "removed": removed, "row": row, "deadline": deadline.isoformat()}


def upkeep_text(out: dict) -> str:
    if out["cleared"]:
        return f"the trade deadline ({out['deadline']}) has passed: every team's block cleared"
    if out["removed"]:
        word = {"untouchable": "untouchables", "block": "block"}
        return "; ".join(f"{r['player']} taken off {r['manager']}'s {word[r['list']]} "
                         "(no longer on his roster)" for r in out["removed"])
    return "nothing to change"


# =============================================================================
# the one read: hub, prompts, advice V3
# =============================================================================

def current(base, rosters: dict, managers=None, season: str = None) -> dict:
    """The trade block as the hub, the drafting prompts and advice V3 read it:
    {"season", "teams": {manager: {"mode", "mode_set", "untouchable": [{player,
    set}], "block": [...]}}}, as stored, less any listed player no longer on
    that manager's roster in `rosters` (the 12:01 AM run takes him off)."""
    from .data_loader import PlayerIndex
    blob = load(base, managers, season)
    out = {"season": blob["season"], "teams": {}}
    for m, t in blob["teams"].items():
        if m not in rosters:
            raise TradeBlockError(f"no roster for {m}")
        idx = PlayerIndex({n: n for n in rosters[m]})
        tt = {"mode": t["mode"], "mode_set": t["mode_set"]}
        for lst in LISTS:
            tt[lst] = [dict(e, player=idx.canonical(e["player"])) for e in t[lst]
                       if idx.canonical(e["player"]) is not None]
        out["teams"][m] = tt
    return out


def prompt_lines(block: dict, managers, team_names: dict) -> list:
    """Part 3's trade-block lines for the drafting chat, one per team, in the
    config's order, every item with the day it was set."""
    lines = []
    for m in managers:
        t = block["teams"][m]
        mode = t["mode"] + (f" since {md(t['mode_set'])}" if t["mode_set"] else "")
        bits = []
        for lst in LISTS:
            if t[lst]:
                bits.append(f"{LIST_LABEL[lst]}: " + ", ".join(f"{e['player']} (since {md(e['set'])})"
                                                                 for e in t[lst]))
        lines.append(f"- **{m}** ({team_names[m]}): {mode}; "
                     + ("; ".join(bits) if bits else "nothing listed") + ".")
    return lines
