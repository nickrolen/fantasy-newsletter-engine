"""
phone_entries.py -- the one-line entries Nick types as GitHub issue titles on
his phone (Step 3a; claude/HANDOFF_STEP3A_PHONE_ENTRIES_2026-11-10.md s.2;
SELF_RUNNING_DESIGN s.6.2 and s.7).

THE GRAMMAR -- strict; anything else is refused with the reason and the forms:

  Injury: <player> [<notes>], back MM/DD     a new injury entry          (overrides.py add)
  Injury: <player> [<notes>], out for season a new entry, rest of season (add --season)
  Injury: <player> back MM/DD                move his return date         (set-return)
  Injury: <player> notes <text>              replace his notes            (set-notes)
  Injury remove: <player>                    remove his entry             (remove)

  <Manager> move: [+<add>] [-<drop>] [IL+<player>] [IL-<player>]
  Trade: <Manager> gets <p1>[, <p2>...]; <Manager> gets <p3>[, ...]
                                             the move ledger (move_ledger's grammar)

  Block: <Manager> untouchable <p1>[, <p2>...]   add to his untouchables    (the trade block,
  Block: <Manager> on the block <p1>[, <p2>...]  add to his block            modules/trade_block;
  Block: <Manager> remove <p1>[, <p2>...]        off either list             task 49, 11-11)
  Block: <Manager> buying | selling | neutral    set his mode
  Block: <Manager> clear                         empty both lists, mode neutral

- Keywords ("Injury", "remove", "back", "notes", "out for season") are matched
  without regard to case; the canonical spelling is the one above, and
  format_title(parse_title(t)) == t for every canonical title (tested).
- MM/DD is the next such day inside the current fantasy season: outside the
  season it refuses, and so does a day already past (resolve_day).
- A new entry's player is the LONGEST leading run of words that names exactly
  one NBA player ("Coby White knee": Coby White, notes "knee"); a run that
  could be two players refuses listing them (overrides.resolve_player).
- The edit forms name a player who has an entry (overrides.resolve_entry).
- "Block:" names one of the league's managers (any case; the canonical
  spelling is the config's), then one keyword (any case; canonical lower
  case) and, for the list forms, players separated by commas. The players
  are kept AS TYPED here; trade_block.apply resolves them on that manager's
  roster (the ledger's resolver) and refuses one on any other roster.

This module only reads the title. scripts/apply_entry.py applies it through
scripts/overrides.py and modules/move_ledger, whose checks are the gate.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

FORMS = (
    "Injury: <player> <notes>, back MM/DD",
    "Injury: <player> <notes>, out for season",
    "Injury: <player> back MM/DD",
    "Injury: <player> notes <text>",
    "Injury remove: <player>",
    "<Manager> move: +<add> -<drop> IL+<player> IL-<player>  (any of the four, at least one)",
    "Trade: <Manager> gets <player>[, ...]; <Manager> gets <player>[, ...]",
    "Block: <Manager> untouchable <player>[, ...]",
    "Block: <Manager> on the block <player>[, ...]",
    "Block: <Manager> remove <player>[, ...]",
    "Block: <Manager> buying | selling | neutral",
    "Block: <Manager> clear",
)

_MD = r"(?P<m>\d{1,2})/(?P<d>\d{1,2})"
RE_REMOVE = re.compile(r"^\s*injury\s+remove\s*:\s*(?P<name>\S.*?)\s*$", re.I)
RE_SEASON = re.compile(r"^\s*injury\s*:\s*(?P<subject>\S.*?)\s*,\s*out\s+for\s+season\s*$", re.I)
RE_ADD = re.compile(r"^\s*injury\s*:\s*(?P<subject>\S.*?)\s*,\s*back\s+" + _MD + r"\s*$", re.I)
RE_RETURN = re.compile(r"^\s*injury\s*:\s*(?P<name>[^,]*?\S)\s+back\s+" + _MD + r"\s*$", re.I)
RE_NOTES = re.compile(r"^\s*injury\s*:\s*(?P<name>[^,]*?\S)\s+notes\s+(?P<notes>\S.*?)\s*$", re.I)
RE_INJURY_ANY = re.compile(r"^\s*injury\b", re.I)
RE_BLOCK = re.compile(r"^\s*block\s*:\s*(?P<rest>\S.*?)\s*$", re.I)
RE_BLOCK_ANY = re.compile(r"^\s*block\b", re.I)
# after "Block: <Manager> ": the list forms, the modes, clear
RE_BLOCK_LIST = re.compile(r"^(?P<kw>untouchable|on\s+the\s+block|remove)(?:\s+(?P<players>\S.*))?$", re.I)
RE_BLOCK_MODE = re.compile(r"^(?P<mode>buying|selling|neutral)$", re.I)
RE_BLOCK_CLEAR = re.compile(r"^clear$", re.I)
BLOCK_KW = {"untouchable": "untouchable", "on the block": "block", "remove": "remove"}
BLOCK_TEXT = {"untouchable": "untouchable", "block": "on the block", "remove": "remove"}


class TitleRefused(ValueError):
    """The title is not an entry; the message says why and lists the forms."""


def forms_text() -> str:
    return "Accepted forms:\n" + "\n".join(f"- `{f}`" for f in FORMS)


def _refuse(why: str) -> TitleRefused:
    return TitleRefused(f"{why}\n\n{forms_text()}")


def parse_title(title: str, managers=None) -> dict:
    """The title's parsed form, names AS TYPED. {"kind": "injury", "form":
    "add" | "season" | "set-return" | "set-notes" | "remove", ...} or
    {"kind": "ledger", "text": <the title, stripped>, "parsed": move_ledger's}.
    Raises TitleRefused."""
    if not isinstance(title, str) or not title.strip():
        raise _refuse("An empty title.")
    if "\n" in title.strip():
        raise _refuse("One entry per issue, on one line.")
    t = title.strip()
    m = RE_REMOVE.match(t)
    if m:
        return {"kind": "injury", "form": "remove", "name": m["name"]}
    m = RE_SEASON.match(t)
    if m:
        return {"kind": "injury", "form": "season", "subject": m["subject"]}
    m = RE_ADD.match(t)
    if m:
        return {"kind": "injury", "form": "add", "subject": m["subject"], "md": (int(m["m"]), int(m["d"]))}
    m = RE_RETURN.match(t)
    if m:
        return {"kind": "injury", "form": "set-return", "name": m["name"],
                "md": (int(m["m"]), int(m["d"]))}
    m = RE_NOTES.match(t)
    if m:
        return {"kind": "injury", "form": "set-notes", "name": m["name"], "notes": m["notes"]}
    if RE_INJURY_ANY.match(t):
        raise _refuse(f"{t!r} starts like an injury entry but matches none of its forms.")
    if RE_BLOCK_ANY.match(t):
        if managers is None:
            from .data_loader import MANAGERS
            managers = list(MANAGERS)
        return parse_block(t, managers)
    from . import move_ledger as ml
    if ml.MOVE_RE.match(t) or ml.TRADE_RE.match(t):
        if managers is None:
            from .data_loader import MANAGERS
            managers = list(MANAGERS)
        try:
            parsed = ml.parse(t, managers)
        except ml.EntryRefused as e:
            raise _refuse(str(e)) from None
        return {"kind": "ledger", "text": t, "parsed": parsed}
    raise _refuse(f"{t!r} is not an entry.")


def parse_block(t: str, managers) -> dict:
    """A "Block:" title -> {"kind": "block", "manager": the config's spelling,
    "action": "untouchable" | "block" | "remove" | "mode" | "clear",
    "mode": buying|selling|neutral (mode only), "players": [as typed]}."""
    m = RE_BLOCK.match(t)
    if not m:
        raise _refuse(f"{t!r} starts like a trade-block entry but names no manager.")
    rest = m["rest"]
    hits = [x for x in managers if rest.casefold() == x.casefold()
            or rest.casefold().startswith(x.casefold() + " ")]
    if not hits:
        raise _refuse(f"{t!r}: a trade-block entry starts with a manager ({', '.join(managers)}).")
    mgr = max(hits, key=len)
    after = re.sub(r"\s+", " ", rest[len(mgr):].strip())
    if not after:
        raise _refuse(f"{t!r} says nothing to do for {mgr}.")
    base = {"kind": "block", "manager": mgr, "mode": None, "players": []}
    mm = RE_BLOCK_MODE.match(after)
    if mm:
        return dict(base, action="mode", mode=mm["mode"].lower())
    if RE_BLOCK_CLEAR.match(after):
        return dict(base, action="clear")
    ml_ = RE_BLOCK_LIST.match(after)
    if not ml_:
        raise _refuse(f"{t!r} matches none of the trade-block forms.")
    kw = BLOCK_KW[re.sub(r"\s+", " ", ml_["kw"].lower())]
    if not ml_["players"]:
        raise _refuse(f"{t!r} names no player.")
    players = [x.strip() for x in ml_["players"].split(",")]
    if any(not x for x in players):
        raise _refuse(f"{t!r} has an empty name between commas.")
    folded = [x.casefold() for x in players]
    if len(set(folded)) != len(folded):
        raise _refuse(f"{t!r} names a player twice.")
    return dict(base, action=kw, players=players)


def format_title(p: dict) -> str:
    """The canonical title of a parsed entry (the round trip)."""
    if p["kind"] == "block":
        if p["action"] == "mode":
            return f"Block: {p['manager']} {p['mode']}"
        if p["action"] == "clear":
            return f"Block: {p['manager']} clear"
        return f"Block: {p['manager']} {BLOCK_TEXT[p['action']]} {', '.join(p['players'])}"
    if p["kind"] == "ledger":
        q = p["parsed"]
        if q["kind"] == "trade":
            return "Trade: " + "; ".join(f"{s['manager']} gets {', '.join(s['gets'])}" for s in q["sides"])
        parts = [f"{lbl}{n}" for kind, lbl in (("add", "+"), ("drop", "-"), ("il_place", "IL+"),
                                                ("il_activate", "IL-")) for n in q[kind]]
        return f"{q['manager']} move: " + " ".join(parts)
    f = p["form"]
    if f == "remove":
        return f"Injury remove: {p['name']}"
    if f == "season":
        return f"Injury: {p['subject']}, out for season"
    if f == "add":
        return f"Injury: {p['subject']}, back {p['md'][0]:02d}/{p['md'][1]:02d}"
    if f == "set-return":
        return f"Injury: {p['name']} back {p['md'][0]:02d}/{p['md'][1]:02d}"
    if f == "set-notes":
        return f"Injury: {p['name']} notes {p['notes']}"
    raise ValueError(f"unknown form {f!r}")


def season_bounds(schedule: dict) -> tuple:
    from .injury_entries import fantasy_weeks
    w = fantasy_weeks(schedule)
    return w[0][1], w[-1][2]


def resolve_day(md: tuple, today: date, schedule: dict) -> date:
    """MM/DD -> the next such day inside the current fantasy season. Refuses a
    day that does not exist, one outside the season, and one already past."""
    first, last = season_bounds(schedule)
    m, d = md
    cands = []
    for y in sorted({first.year, last.year}):
        try:
            cands.append(date(y, m, d))
        except ValueError:
            raise _refuse(f"{m:02d}/{d:02d} is not a day.") from None
    inside = [c for c in cands if first <= c <= last]
    if not inside:
        raise _refuse(f"{m:02d}/{d:02d} is outside the season ({first:%m/%d/%Y} to {last:%m/%d/%Y}). "
                      "For a player out for the rest of it: `Injury: <player> <notes>, out for season`.")
    ahead = [c for c in inside if c >= today]
    if not ahead:
        raise _refuse(f"{m:02d}/{d:02d} ({inside[-1].isoformat()}) is in the past (today is "
                      f"{today.isoformat()}, league clock). If he is back, remove the entry: "
                      "`Injury remove: <player>`.")
    return min(ahead)


def split_subject(subject: str, resolve) -> tuple:
    """(player, notes or None) for a new entry's "<player> [<notes>]": the
    longest leading run of words that `resolve` (overrides.resolve_player)
    maps to exactly one player. A run that could be two players refuses with
    them; nothing at all refuses with the nearest names."""
    from . import injury_entries as ie
    words = subject.split()
    ambiguous, unknown = None, []
    for k in range(len(words), 0, -1):
        head = " ".join(words[:k])
        try:
            name = resolve(head)
        except ie.EntryRefused as e:
            msg = str(e)
            if "could be" in msg and ambiguous is None:
                ambiguous = msg
            else:
                unknown.append(msg)
            continue
        notes = " ".join(words[k:]) or None
        return name, notes
    if ambiguous:
        raise _refuse(ambiguous)
    hinted = [u for u in unknown if "did you mean" in u]
    raise _refuse((hinted[0] if hinted else unknown[-1] if unknown else f"{subject!r} names no player")
                  + " Write the player's name first, then the notes.")


def md_text(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def cause_of(action: str, player: str, after: Optional[dict]) -> str:
    """The refresh's --cause for an applied injury change: one short line,
    built from the change itself (never guessed)."""
    if action == "add":
        rd = (after or {}).get("return_date")
        return (f"injury update: {player} out, back {md_text(date.fromisoformat(rd))}" if rd
                else f"injury update: {player} out for the season")
    if action == "set-return":
        return f"injury update: {player} back {md_text(date.fromisoformat(after['return_date']))}"
    if action == "set-notes":
        return f"injury notes: {player}"
    if action == "remove":
        return f"injury removed: {player}"
    raise ValueError(f"unknown action {action!r}")
