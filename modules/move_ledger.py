"""
move_ledger.py -- group-chat moves, recorded the moment they are posted (step 2).

claude/SELF_RUNNING_DESIGN.md s.6.1-6.4 is the spec; claude/HANDOFF_STEP2_MOVE_LEDGER_
2026-11-05.md the brief; claude/LEAGUE_RULES.md rules 0-15 the rules it enforces.

Nick types one line per group-chat move, as it happens:

    python scripts\\ledger.py add "Benton move: +Bane -Alexander-Walker"
    python scripts\\ledger.py add "Nick move: +Bane IL+Edwards"
    python scripts\\ledger.py add "Trade: Benton gets Tatum; Hayden gets Barnes"

TWO FILES, both private league state (config/STATE_MANIFEST.json):

  config/MOVE_LEDGER.json          the entries. Written ONLY by scripts/ledger.py
                                   (through write_entries below); APPEND-ONLY: an
                                   entry is never edited or deleted (design s.6.3).
                                   {"schema": 1, "_comment": ..., "rows": [...]}
      {"row": "entry", "id": 1, "text": <as typed>, "kind": "move" | "trade",
       "parsed": {"manager", "add": [..], "drop": [..], "il_place": [..],
                  "il_activate": [..]}                         (a move; full names)
               | {"sides": [{"manager", "gets": [..]}, {...}]} (a trade),
       "claimed_at": <league clock, ISO>, "claim_week": N,     the budget week (rule 7)
       "window_week": N + 1, "window": "YYYY-MM-DD",           the Monday it takes effect
       "entered_at", "entered_by", "checks": [what was checked]}
      {"row": "void", "entry": id, "by", "on", "reason"}
          Nick's ruling on a MISTAKEN ENTRY (he typed what was not posted). The
          entry stays; it does nothing and counts nowhere. This is not a cancel:
          a claim cannot be cancelled (rule 12) -- undoing a real claim is
          another move ("Benton move: -Bane").

  data/move_ledger_states.jsonl    what verification found, APPEND-ONLY
                                   (modules/jsonl_log). Written only by verify(),
                                   from the nightly run's ledger step: the cloud
                                   and the desk never write the same file, so a
                                   `state.py pull` merges them.
      {"row": "state", "entry": id, "state": "applied" | "missing" | "conflict",
       "at", "by", "why", "transactions": [Yahoo keys]}
      {"row": "unmatched", "key": <Yahoo key>, "at", "by", "why"}
          a Yahoo transaction outside a Monday window matching no entry (rule 4)

  An entry's state is its latest state row, else "pending" ("void" if voided).

THE RULES IT ENFORCES (LEAGUE_RULES rules 1-15):
  - a claim reserves the player at once (10): he leaves the coming week's pool;
  - a chat drop frees the player for the coming week at once (11);
  - a claim uses the add budget of the week it is CLAIMED in (7); a Sunday
    claim is that Sunday's week (the league clock, rule 0);
  - <= weekly_add_budget (3) adds per budget week, Yahoo's 6 notwithstanding;
  - the roster after the window is legal (1-3): 15 active, 2 IL, IL only for
    a player TAGGED O or OFS in Yahoo (rule 2; task 47, Nick 11-05: Yahoo
    enforces only its own tag). One function decides it, tag_il_eligible, on
    roster_moves.il_eligible_tags (the hub's stash table reads the same). At
    the window -- the checklist, its re-check, ledger.py check -- the tag alone
    decides. At entry an IL+ for a player with no eligible tag but a live
    injury entry covering the window day is ACCEPTED WITH A WARNING ("not
    tagged O/OFS in Yahoo now: he must be by Monday's window or the move
    fails"); that warning is the only place an injury entry counts here;
  - an add that would put a team over 15 active must name its IL placement or
    a drop (15); an activation needs room the same way;
  - a claim cannot be cancelled (12); a claimed player may be dropped before
    he joins: the add, then the drop, in the same window, and the add counts;
  - a chat trade takes effect the following Monday, uses no adds (13), and is
    refused after the trade deadline (yahoo_settings.trade_deadline).

THE MODE (league_config roster_moves.ledger_mode, required): "shadow" or "on".
  shadow: the ledger records, checks, publishes the checklist and verifies;
          every add count still comes from the TRANSACTION_RULINGS claim_week
          rulings; shadow_compare() reports where the ledger would differ;
          nothing is priced from a pending move.
  on:     the ledger's claim weeks are the add counts (transaction_rulings.
          add_budget_week takes the ledger), and the roster plan treats a
          pending move as a known pickup from its window (roster_plan.build).

Raise, never guess: an unknown or ambiguous name, a missing file the check
needs, a malformed row -- each refuses with the reason.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

LEDGER_FILE = Path("config") / "MOVE_LEDGER.json"
STATES_FILE = Path("data") / "move_ledger_states.jsonl"
CHECKLIST_DIR = Path("output")
SCHEMA = 1
MODES = ("shadow", "on")
STATES = ("applied", "missing", "conflict")
WINDOW_OPENS = time(0, 1)              # rule 4: 12:01 AM (league clock)
LEDGER_COMMENT = ("The move ledger (modules/move_ledger.py): every group-chat claim, drop and "
                  "trade Nick entered with scripts/ledger.py, append-only. Never edit by hand; "
                  "a mistaken entry is voided with `python scripts\\ledger.py void N --reason ...`.")


class LedgerError(ValueError):
    """The ledger's files or inputs are not what they must be."""


class EntryRefused(LedgerError):
    """An entry is refused; the reason says why. Nothing was written."""


class NameUnknown(EntryRefused):
    pass


class NameAmbiguous(EntryRefused):
    pass


# =============================================================================
# config
# =============================================================================

def _cfg(cfg=None) -> dict:
    if cfg is None:
        from .data_loader import _LEAGUE_CONFIG
        cfg = _LEAGUE_CONFIG
    return cfg


def _roster_moves(cfg=None) -> dict:
    rm = _cfg(cfg).get("roster_moves")
    if not isinstance(rm, dict):
        raise LedgerError("league_config.json has no roster_moves block")
    return rm


def mode(cfg=None) -> str:
    """roster_moves.ledger_mode: "shadow" or "on". Missing or anything else RAISES."""
    rm = _roster_moves(cfg)
    if "ledger_mode" not in rm:
        raise LedgerError("league_config.json roster_moves.ledger_mode is missing: it must be "
                          "\"shadow\" or \"on\" (step 2 ships \"shadow\")")
    m = rm["ledger_mode"]
    if m not in MODES:
        raise LedgerError(f"roster_moves.ledger_mode is {m!r}: it must be \"shadow\" or \"on\"")
    return m


def verify_from(cfg=None) -> date:
    """roster_moves.ledger_verify_from: Yahoo transactions on or after this
    league day are checked against rule 4 (outside a window, no entry)."""
    rm = _roster_moves(cfg)
    if "ledger_verify_from" not in rm:
        raise LedgerError("league_config.json roster_moves.ledger_verify_from is missing")
    return date.fromisoformat(str(rm["ledger_verify_from"]))


def il_eligible_tags(cfg=None) -> tuple:
    rm = _roster_moves(cfg)
    if "il_eligible_tags" not in rm:
        raise LedgerError("league_config.json roster_moves.il_eligible_tags is missing")
    return tuple(str(t).upper() for t in rm["il_eligible_tags"])


def tag_il_eligible(tag, eligible_tags=None) -> bool:
    """Rule 2, the one definition (task 47): a player may go into an IL slot
    only when his Yahoo tag is one of roster_moves.il_eligible_tags (O, OFS;
    OFS's aliases count as OFS). Nothing else makes him eligible -- not an
    injury entry: Yahoo enforces only its own tag. The ledger (World) and the
    hub's stash table (hub_state.stash_rows) both call this."""
    from . import absence
    if tag is None:
        return False
    eligible = set(eligible_tags if eligible_tags is not None else il_eligible_tags())
    return absence.normalised_tag(tag) in eligible or (absence.season_out(tag) and "OFS" in eligible)


def trade_deadline(cfg=None) -> date:
    ys = _cfg(cfg).get("yahoo_settings") or {}
    if "trade_deadline" not in ys:
        raise LedgerError("league_config.json yahoo_settings.trade_deadline is missing")
    return date.fromisoformat(str(ys["trade_deadline"]))


def roster_shape(cfg=None) -> tuple:
    """(active spots, IL slots, weekly add budget) from league_structure."""
    ls = _cfg(cfg).get("league_structure") or {}
    for k in ("starters", "bench", "il_slots", "weekly_add_budget"):
        if ls.get(k) is None:
            raise LedgerError(f"league_config.json league_structure.{k} is missing")
    return int(ls["starters"]) + int(ls["bench"]), int(ls["il_slots"]), int(ls["weekly_add_budget"])


# =============================================================================
# the grammar (design s.6.2)
# =============================================================================

MOVE_RE = re.compile(r"^\s*(?P<mgr>[A-Za-z][A-Za-z .'-]*?)\s+move\s*:\s*(?P<rest>.*)$", re.IGNORECASE)
TRADE_RE = re.compile(r"^\s*trade\s*:\s*(?P<rest>.*)$", re.IGNORECASE)
SIDE_RE = re.compile(r"^\s*(?P<mgr>[A-Za-z][A-Za-z .'-]*?)\s+gets\s+(?P<players>.+?)\s*$", re.IGNORECASE)
# a part starts at the beginning or after whitespace: IL+ / IL- / + / -, then the name
PART_RE = re.compile(r"(?:(?<=\s)|^)(IL\+|IL-|\+|-)(?=\S)", re.IGNORECASE)
PART_KIND = {"+": "add", "-": "drop", "IL+": "il_place", "IL-": "il_activate"}
PART_LABEL = {"add": "+", "drop": "-", "il_place": "IL+", "il_activate": "IL-"}
GRAMMAR = ('"<Manager> move: [+<add>] [-<drop>] [IL+<player>] [IL-<player>]" (at least one part, '
           'each at most once) or "Trade: <Manager> gets <p1>[, <p2>...]; <Manager> gets <p3>[, ...]"')


def _manager(typed: str, managers) -> str:
    by = {m.lower(): m for m in managers}
    m = by.get(typed.strip().lower())
    if m is None:
        raise EntryRefused(f"{typed.strip()!r} is not a manager ({', '.join(managers)})")
    return m


def parse(text: str, managers) -> dict:
    """The entry's parsed form, names AS TYPED (resolve() makes them full
    names). Anything that does not parse refuses with the reason."""
    if not isinstance(text, str) or not text.strip():
        raise EntryRefused(f"an empty entry: write {GRAMMAR}")
    if "\n" in text.strip():
        raise EntryRefused("one entry per line")
    t = TRADE_RE.match(text)
    if t:
        sides_txt = t.group("rest").split(";")
        if len(sides_txt) != 2:
            raise EntryRefused(f"a trade has exactly two sides separated by ';' ({len(sides_txt)} "
                               f"found): {GRAMMAR}")
        sides = []
        for s in sides_txt:
            m = SIDE_RE.match(s)
            if not m:
                raise EntryRefused(f"{s.strip()!r} is not '<Manager> gets <player>[, ...]'")
            names = [p.strip() for p in m.group("players").split(",")]
            if any(not p for p in names):
                raise EntryRefused(f"an empty player name in {s.strip()!r}")
            sides.append({"manager": _manager(m.group("mgr"), managers), "gets": names})
        if sides[0]["manager"] == sides[1]["manager"]:
            raise EntryRefused(f"a trade needs two different managers, not {sides[0]['manager']} twice")
        allp = [p for s in sides for p in s["gets"]]
        if any(_same(a, b) for i, a in enumerate(allp) for b in allp[i + 1:]):
            raise EntryRefused("the same player is named twice in the trade")
        return {"kind": "trade", "sides": sides}
    m = MOVE_RE.match(text)
    if not m:
        raise EntryRefused(f"not an entry: write {GRAMMAR}")
    manager = _manager(m.group("mgr"), managers)
    rest = m.group("rest")
    pieces = PART_RE.split(rest)
    if pieces[0].strip():
        raise EntryRefused(f"{pieces[0].strip()!r} before the first part: every part starts with "
                           "+, -, IL+ or IL-")
    out = {"kind": "move", "manager": manager, "add": [], "drop": [], "il_place": [], "il_activate": []}
    seen = []
    for i in range(1, len(pieces), 2):
        kind = PART_KIND[pieces[i].upper()]
        name = pieces[i + 1].strip()
        if not name:
            raise EntryRefused(f"a {PART_LABEL[kind]} with no player")
        if out[kind]:
            raise EntryRefused(f"two {PART_LABEL[kind]} parts in one entry: one of each per entry; "
                               "enter a second move for the other")
        if any(_same(name, x) for x in seen):
            raise EntryRefused(f"{name} is named twice in one entry")
        seen.append(name)
        out[kind].append(name)
    if not seen:
        raise EntryRefused(f"a move with no parts: write {GRAMMAR}")
    return out


# =============================================================================
# names (design s.6.2: PlayerIndex and NBA_PLAYER_REFERENCE; ambiguous or
# unknown refuses with the candidates)
# =============================================================================

def _same(a: str, b: str) -> bool:
    """One player? Through PlayerIndex (accents, suffixes, initials), the
    project's one name matcher (tests/test_name_resolution.py)."""
    from .data_loader import PlayerIndex
    return PlayerIndex({a: True}).get(b) is not None


def _in(name: str, names) -> Optional[str]:
    """The entry of `names` that is `name`, through PlayerIndex, or None."""
    from .data_loader import PlayerIndex
    return PlayerIndex({n: n for n in names}).canonical(name)


def _fold(name: str) -> str:
    """Letters and digits, lower case: for the last-name search and the typo
    hint only (resolve_name), never to join two files' names."""
    return "".join(_words(name))


def _words(name: str) -> list:
    from .data_loader import _GENERATIONAL_SUFFIX
    text = unicodedata.normalize("NFKD", _GENERATIONAL_SUFFIX.sub("", str(name or "").strip()))
    text = text.encode("ascii", "ignore").decode().lower()
    return [re.sub(r"[^a-z0-9]", "", w) for w in text.split() if re.sub(r"[^a-z0-9]", "", w)]


def _surname_hit(q: str, name: str) -> bool:
    w = _words(name)
    if len(w) < 2:
        return False
    return q in {w[-1], "".join(w[1:])}


def resolve_name(typed: str, names, where: str) -> str:
    """The one player `typed` names among `names`: a full name (accents,
    suffixes and initials as PlayerIndex matches them), else a unique last
    name. Two or more matches refuse with the candidates; none refuses with
    the nearest names. Never guesses."""
    from .data_loader import PlayerIndex
    names = list(dict.fromkeys(names))
    idx = PlayerIndex({n: n for n in names})
    hit = idx.canonical(typed)
    if hit is not None:
        return hit
    q = _fold(typed)
    cands = sorted({n for n in names if _surname_hit(q, n)})
    if len(cands) == 1:
        return cands[0]
    if len(cands) > 1:
        raise NameAmbiguous(f"{typed!r} {where} could be {', '.join(cands)}: write the full name")
    by_norm = {}
    for n in names:
        by_norm.setdefault(_fold(n), n)
        w = _words(n)
        if len(w) > 1:
            by_norm.setdefault(w[-1], n)                  # a misspelt last name, too
    near = list(dict.fromkeys(by_norm[k] for k in difflib.get_close_matches(q, list(by_norm), n=6,
                                                                            cutoff=0.7)))[:4]
    raise NameUnknown(f"{typed!r} {where} matches no player"
                      + (f"; nearest: {', '.join(near)}" if near else ""))


# =============================================================================
# the files
# =============================================================================

def _validate_entry_rows(rows: list, where: str) -> None:
    ids = []
    for i, r in enumerate(rows, start=1):
        if not isinstance(r, dict):
            raise LedgerError(f"{where} row {i}: not an object")
        kind = r.get("row")
        if kind == "entry":
            need = ("id", "text", "kind", "parsed", "claimed_at", "claim_week", "window_week", "window",
                    "entered_at", "entered_by", "checks")
            miss = [k for k in need if k not in r]
            if miss:
                raise LedgerError(f"{where} row {i}: entry missing {miss}")
            if r["id"] != len(ids) + 1:
                raise LedgerError(f"{where} row {i}: entry id {r['id']}, expected {len(ids) + 1} "
                                  "(ids run 1, 2, 3 ... with no gaps)")
            if r["kind"] not in ("move", "trade"):
                raise LedgerError(f"{where} row {i}: kind {r['kind']!r}")
            ids.append(r["id"])
        elif kind == "void":
            for k in ("entry", "by", "on", "reason"):
                if k not in r:
                    raise LedgerError(f"{where} row {i}: void missing {k!r}")
            if r["entry"] not in ids:
                raise LedgerError(f"{where} row {i}: void of entry {r['entry']}, not above it")
            if sum(1 for x in rows[:i - 1] if x.get("row") == "void" and x["entry"] == r["entry"]):
                raise LedgerError(f"{where} row {i}: entry {r['entry']} is voided twice")
        else:
            raise LedgerError(f"{where} row {i}: unknown row kind {kind!r}")


def read_rows(base_path=".") -> list:
    """Every row of config/MOVE_LEDGER.json, validated. No file is no rows."""
    p = Path(base_path) / LEDGER_FILE
    if not p.is_file():
        return []
    blob = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(blob, dict) or blob.get("schema") != SCHEMA or not isinstance(blob.get("rows"), list):
        raise LedgerError(f"{LEDGER_FILE.as_posix()} is not a schema-{SCHEMA} ledger")
    _validate_entry_rows(blob["rows"], LEDGER_FILE.as_posix())
    return blob["rows"]


def write_entries(base_path, old_rows: list, new_rows: list) -> Path:
    """Append rows to config/MOVE_LEDGER.json. THE ONLY WRITER of the file
    (scripts/ledger.py calls it; tests/test_move_ledger.py pins that). The
    file on disk must still hold exactly `old_rows` (nobody wrote between the
    read and this write); the result is old + new, validated, written
    atomically. Nothing already there is ever changed."""
    from .data_loader import atomic_write_json
    base = Path(base_path)
    now_rows = read_rows(base)
    if now_rows != old_rows:
        raise LedgerError(f"{LEDGER_FILE.as_posix()} changed since it was read: nothing written")
    rows = list(old_rows) + list(new_rows)
    _validate_entry_rows(rows, LEDGER_FILE.as_posix())
    p = base / LEDGER_FILE
    atomic_write_json(p, {"schema": SCHEMA, "_comment": LEDGER_COMMENT, "rows": rows}, indent=1)
    return p


def read_states(base_path=".") -> list:
    from .jsonl_log import read_rows as jr
    rows = jr(Path(base_path) / STATES_FILE, STATES_FILE.as_posix())
    for i, r in enumerate(rows, start=1):
        if r.get("row") == "state":
            if r.get("state") not in STATES or not isinstance(r.get("entry"), int):
                raise LedgerError(f"{STATES_FILE.as_posix()} line {i}: bad state row")
        elif r.get("row") == "unmatched":
            if not r.get("key"):
                raise LedgerError(f"{STATES_FILE.as_posix()} line {i}: unmatched row with no key")
        else:
            raise LedgerError(f"{STATES_FILE.as_posix()} line {i}: unknown row kind {r.get('row')!r}")
    return rows


def append_states(base_path, rows: list) -> int:
    """Append verification rows (data/move_ledger_states.jsonl). Only verify()'s
    caller (the nightly run's ledger step) writes them."""
    from .jsonl_log import append_rows
    return append_rows(Path(base_path) / STATES_FILE, rows)


def entries(rows: list) -> list:
    """The entry rows, each with "voided" (the void row or None)."""
    voids = {r["entry"]: r for r in rows if r["row"] == "void"}
    out = []
    for r in rows:
        if r["row"] == "entry":
            e = dict(r)
            e["voided"] = voids.get(r["id"])
            out.append(e)
    return out


def state_of(entry: dict, states: list) -> str:
    if entry.get("voided"):
        return "void"
    st = [r for r in states if r.get("row") == "state" and r["entry"] == entry["id"]]
    return st[-1]["state"] if st else "pending"


def state_row(entry: dict, states: list) -> Optional[dict]:
    st = [r for r in states if r.get("row") == "state" and r["entry"] == entry["id"]]
    return st[-1] if st else None


# =============================================================================
# the world an entry is checked against
# =============================================================================

@dataclass
class World:
    """Everything the checks read, as of `now` (the league clock). from_base()
    reads it from a league folder; tests build one in memory."""
    now: datetime
    weeks: Dict[int, tuple]                   # {week: (first day, last day)}
    window_close: Callable[[date], datetime]
    managers: List[str]
    rosters: Dict[str, List[str]]             # Yahoo's, now (ROSTERS.json)
    il: Dict[str, List[str]]                  # Yahoo's IL slots, now
    il_week: int
    playerlist: List[str]                     # every Yahoo player (PLAYERLIST)
    universe: List[str]                       # PLAYERLIST + NBA reference + rostered
    tags: Dict[str, str]                      # the latest Yahoo tags (rostered + free agents)
    overrides: List[dict]                     # INJURY_OVERRIDES players
    yahoo_adds: Callable[[object], dict]      # ledger_claims -> {budget week: {manager: [players]}}
    transactions: List[dict]                  # the transaction log
    active_spots: int = 15
    il_slots: int = 2
    budget: int = 3
    deadline: date = date(2027, 3, 4)
    eligible_tags: tuple = ("O", "OFS")
    verify_from: date = None
    _tag_idx: object = field(default=None, repr=False)

    # -- the calendar
    def week_of(self, d: date) -> Optional[int]:
        for w, (a, b) in self.weeks.items():
            if a <= d <= b:
                return w
        return None

    def window_day(self, week: int) -> date:
        if week not in self.weeks:
            raise EntryRefused(f"fantasy week {week} is not in the schedule: there is no window for it")
        return self.weeks[week][0]

    def window_open(self, week: int) -> datetime:
        from .league_clock import league_tz
        return datetime.combine(self.window_day(week), WINDOW_OPENS, tzinfo=league_tz())

    def current_week(self) -> int:
        w = self.week_of(self.now.date())
        if w is None:
            raise LedgerError(f"{self.now.date()} is in no fantasy week")
        return w

    # -- tags and IL eligibility (rule 2)
    def tag(self, name: str) -> Optional[str]:
        from .data_loader import PlayerIndex
        if self._tag_idx is None:
            self._tag_idx = PlayerIndex(dict(self.tags or {}))
        return self._tag_idx.get(name)

    def il_eligible(self, name: str, day: date) -> tuple:
        """(eligible, why) at the window (`day`): his Yahoo tag alone
        (tag_il_eligible, rule 2). An injury entry does not count."""
        from . import absence
        tag = self.tag(name)
        if tag_il_eligible(tag, self.eligible_tags):
            return True, f"tagged {absence.normalised_tag(tag)}"
        return False, (f"{name} is tagged {absence.normalised_tag(tag) if tag else 'healthy'} in Yahoo: "
                       f"only {' or '.join(self.eligible_tags)} may go into an IL slot ({day:%a %m-%d}; "
                       "rule 2: Yahoo enforces its own tag)")

    def il_entry_check(self, name: str, day: date) -> tuple:
        """(accepted, why, warning) when an entry is MADE, for the window on
        `day`: an eligible tag -> accepted; no eligible tag but a live injury
        entry keeping him out on `day` -> accepted with the warning (he must be
        tagged by then); neither -> refused. The only place an injury entry is
        read for IL eligibility (task 47)."""
        ok, why = self.il_eligible(name, day)
        if ok:
            return True, why, None
        from .data_loader import PlayerIndex
        from .hub_state import override_out_on
        e = PlayerIndex({o["player_name"]: o for o in self.overrides or []}).get(name)
        w = self.week_of(day)
        if e is not None and w is not None and override_out_on(e, day, w, self.weeks[w][0]):
            return True, f"out under an injury entry on {day:%a %m-%d}", (
                f"IL+{name}: not tagged {'/'.join(self.eligible_tags)} in Yahoo now: he must be by "
                f"Monday's window ({day:%a %m-%d}) or the move fails")
        return False, why[:-1] + f"; no injury entry covers {day:%a %m-%d} either)", None

    @classmethod
    def from_base(cls, base_path=".", now: datetime = None, data=None) -> "World":
        """The world from a league folder: ROSTERS.json and IL_SLOTS.json (which
        must be this week's: pull or sync first), PLAYERLIST, the NBA reference,
        the latest tag record, INJURY_OVERRIDES, the transaction log, the
        synced adds. Every one is required."""
        from .league_clock import league_now
        from .data_loader import load_all_data, MANAGERS
        from . import price_lock, tag_records, transaction_log as tlog, transaction_rulings as tr
        from .nba_reference import Reference
        from .roster_plan import load_il_slots, check_against_rosters
        base = Path(base_path)
        now = now or league_now()
        if now.tzinfo is None:
            raise LedgerError("the ledger's clock must be the league clock (aware)")
        data = data or load_all_data(base, current_week=None)
        weeks = {int(w["week"]): (date.fromisoformat(str(w["start_date"])[:10]),
                                  date.fromisoformat(str(w["end_date"])[:10]))
                 for w in data.schedule.get("weeks", [])}
        rosters = {m: list(v) for m, v in data.get_current_rosters().items()}
        il_state = load_il_slots(base, data, now.date())
        check_against_rosters(il_state, rosters)
        tag_row = tag_records.latest(base)
        tags = dict((tag_row.get("tags") or {}).get("rostered") or {})
        fa_tags = (tag_row.get("tags") or {}).get("free_agents")
        if fa_tags is None:
            raise LedgerError(f"the latest tag record ({tag_row.get('run_id')}) has no free-agent "
                              "tags: run the nightly (or python scripts\\state.py pull)")
        tags.update(fa_tags)
        pl_names = [str(n) for n in data.playerlist["player_name"]]
        ref = Reference(base)
        universe = list(dict.keys(ref.index)) + pl_names
        if not (base / tlog.LOG_FILE).is_file():
            raise LedgerError(f"{tlog.LOG_FILE.as_posix()} is missing: python scripts\\state.py pull")
        txs = tlog.transactions(base)
        active, il_n, budget = roster_shape()
        sched = data.schedule

        def yahoo_adds(claims, base=base, sched=sched):
            return tr.adds_by_budget_week(base, sched, ledger=claims)

        nba = data.nba_schedule
        return cls(now=now, weeks=weeks, window_close=lambda d, nba=nba: price_lock.window_close(d, nba),
                   managers=list(MANAGERS), rosters=rosters,
                   il={m: list(v) for m, v in (il_state.get("slots") or {}).items()},
                   il_week=int(il_state["fantasy_week"]), playerlist=pl_names, universe=universe,
                   tags=tags, overrides=list((data.injury_overrides or {}).get("players", [])),
                   yahoo_adds=yahoo_adds, transactions=txs, active_spots=active, il_slots=il_n,
                   budget=budget, deadline=trade_deadline(), eligible_tags=il_eligible_tags(),
                   verify_from=verify_from())


# =============================================================================
# the window: an entry's effect, in the checklist's order
# =============================================================================

PHASES = ("il_place", "drop", "trade", "add", "drop_after_join", "il_activate")
PHASE_TEXT = {"il_place": "IL placements", "drop": "drops", "trade": "trades", "add": "adds",
              "drop_after_join": "drops of players who join in this window (rule 12)",
              "il_activate": "IL activations"}


def is_open(world: World, entry: dict) -> bool:
    """Its window has not closed yet (it can still be applied)."""
    return world.now < world.window_close(date.fromisoformat(entry["window"]))


def live(world: World, ents: list, states: list) -> list:
    """Pending, unvoided entries whose window is still open, in entry order."""
    return [e for e in ents if state_of(e, states) == "pending" and is_open(world, e)]


def _parts(e: dict) -> list:
    """[(phase, manager, player, other manager)] for one entry (phase "drop"
    is decided later between drop / drop_after_join)."""
    p = e["parsed"]
    if e["kind"] == "trade":
        a, b = p["sides"]
        return ([("trade", a["manager"], n, b["manager"]) for n in a["gets"]]
                + [("trade", b["manager"], n, a["manager"]) for n in b["gets"]])
    m = p["manager"]
    return ([("il_place", m, n, None) for n in p["il_place"]] + [("drop", m, n, None) for n in p["drop"]]
            + [("add", m, n, None) for n in p["add"]] + [("il_activate", m, n, None) for n in p["il_activate"]])


class _Team:
    def __init__(self, active, il):
        self.active = list(active)
        self.il = list(il)

    def has(self, n):
        return n in self.active or n in self.il


def _start(world: World) -> dict:
    out = {}
    for m in world.managers:
        il = list(world.il.get(m, []))
        out[m] = _Team([n for n in world.rosters.get(m, []) if n not in il], il)
    return out


def simulate(world: World, ents: list, upto_week: int, *, strict: set, check_day=None,
             at_entry: bool = False) -> dict:
    """Apply `ents` (live entries, in entry order) window by window up to
    `upto_week`, each window in the checklist's order: IL placements, drops,
    trades, adds, drops of players joining in that window (rule 12), IL
    activations. Parts of entries in `strict` get every check (IL eligibility
    on the window day, room, presence); a part of any other entry that is
    already reflected in Yahoo's roster (applied before the sync caught up) is
    skipped, and one that can no longer apply is noted, never raised.

    at_entry: an entry being made (make_entry): IL eligibility by
    World.il_entry_check (an injury entry is accepted with a warning);
    otherwise by the tag alone, World.il_eligible (task 47).

    Returns {"teams": {m: _Team}, "lines": {week: [line]}, "problems":
    [(entry id, manager, reason)], "notes": [...], "warnings": [(entry id,
    manager, warning)]}."""
    teams = _start(world)
    lines, problems, notes, warnings = {}, [], [], []
    windows = sorted({int(e["window_week"]) for e in ents if int(e["window_week"]) <= upto_week})
    for w in windows:
        day = world.window_day(w)
        wk = [e for e in ents if int(e["window_week"]) == w]
        parts = []
        for e in wk:
            for ph, m, n, other in _parts(e):
                parts.append({"phase": ph, "manager": m, "player": n, "other": other, "entry": e["id"],
                              "strict": e["id"] in strict})
        claimed_here = [(x["manager"], x["player"]) for x in parts if x["phase"] == "add"]
        for x in parts:
            if x["phase"] == "drop" and not teams[x["manager"]].has(x["player"]) \
                    and any(m_ == x["manager"] and _same(n_, x["player"]) for m_, n_ in claimed_here):
                x["phase"] = "drop_after_join"
        # an IL swap: placement and activation for one team with no open slot
        out_lines = []
        stopped = {}

        def problem(x, why):
            problems.append((x["entry"], x["manager"], why))
            stopped.setdefault(x["manager"], why)

        swaps = {}
        for m in world.managers:
            pl = [x for x in parts if x["manager"] == m and x["phase"] == "il_place"]
            ac = [x for x in parts if x["manager"] == m and x["phase"] == "il_activate"]
            free = world.il_slots - len(teams[m].il)
            for p_, a_ in zip(pl[max(0, free):], ac):
                swaps[id(p_)] = a_
                a_["swapped"] = True
        for ph in PHASES:
            for x in [x for x in parts if x["phase"] == ph]:
                m, n = x["manager"], x["player"]
                t = teams[m]
                if x.get("swapped"):
                    continue                                  # done with its placement
                if m in stopped and x["strict"]:
                    continue
                label = {"entry": x["entry"], "team": m, "player": n, "phase": ph}
                if ph == "il_place":
                    if n in t.il:
                        if x["strict"]:
                            problem(x, f"{n} is already in an IL slot ({m}'s IL: {', '.join(t.il)})")
                        continue
                    if n not in t.active:
                        if x["strict"]:
                            problem(x, f"{n} is not on {m}'s roster as of the {day:%m-%d} window")
                        else:
                            notes.append(f"entry {x['entry']}: IL+{n} skipped, not on {m}'s roster")
                        continue
                    if x["strict"]:
                        if at_entry:
                            ok, why, warn = world.il_entry_check(n, check_day or day)
                            if ok and warn:
                                warnings.append((x["entry"], m, warn))
                        else:
                            ok, why = world.il_eligible(n, check_day or day)
                        if not ok:
                            problem(x, why)
                            continue
                    sw = swaps.get(id(x))
                    if sw is None and len(t.il) >= world.il_slots:
                        if x["strict"]:
                            problem(x, f"{m}'s IL slots are full ({', '.join(t.il)}): IL+{n} needs an "
                                       "open slot, or an activation in the same window (a swap)")
                        continue
                    if sw is not None:
                        if sw["player"] not in t.il:
                            if x["strict"]:
                                problem(x, f"{sw['player']} is not in {m}'s IL slot ({', '.join(t.il)})")
                            continue
                        t.il.remove(sw["player"])
                        t.active.append(sw["player"])
                        label.update(phase="il_swap", player=n, other=sw["player"])
                    t.active.remove(n)
                    t.il.append(n)
                elif ph in ("drop", "drop_after_join"):
                    if not t.has(n):
                        if x["strict"]:
                            problem(x, f"{n} is not on {m}'s roster as of the {day:%m-%d} window")
                        else:
                            notes.append(f"entry {x['entry']}: -{n} skipped, not on {m}'s roster")
                        continue
                    (t.il if n in t.il else t.active).remove(n)
                elif ph == "trade":
                    giver = teams[x["other"]]
                    if t.has(n) and not giver.has(n):
                        notes.append(f"entry {x['entry']}: {n} is already {m}'s")
                        continue
                    if n in giver.il:
                        problem(x, f"{n} is in {x['other']}'s IL slot: trading an IL player is not "
                                   "modelled -- ask before entering it")
                        continue
                    if n not in giver.active:
                        problem(x, f"{n} is not on {x['other']}'s roster as of the {day:%m-%d} window")
                        continue
                    giver.active.remove(n)
                    t.active.append(n)
                    label["other"] = x["other"]
                elif ph == "add":
                    if t.has(n):
                        if x["strict"]:
                            problem(x, f"{n} is already on {m}'s roster")
                        continue
                    t.active.append(n)
                    if len(t.active) > world.active_spots and x["strict"]:
                        t.active.remove(n)
                        problem(x, f"{m}'s roster is full ({world.active_spots} active at the "
                                   f"{day:%m-%d} window); add a drop (-Player) or an IL placement "
                                   "(IL+Player)")
                        continue
                elif ph == "il_activate":
                    if n not in t.il:
                        if x["strict"]:
                            problem(x, f"{n} is not in {m}'s IL slot ({', '.join(t.il) or 'empty'})")
                        continue
                    t.il.remove(n)
                    t.active.append(n)
                    if len(t.active) > world.active_spots and x["strict"]:
                        t.active.remove(n)
                        t.il.append(n)
                        problem(x, f"{m}'s active roster is full at the {day:%m-%d} window: IL-{n} "
                                   "needs a drop (-Player)")
                        continue
                out_lines.append(label)
        for m, t in teams.items():
            if len(t.active) > world.active_spots:
                notes.append(f"{m} has {len(t.active)} active after the {day:%m-%d} window")
        lines[w] = {"lines": out_lines, "stopped": stopped}
    return {"teams": teams, "lines": lines, "problems": problems, "notes": notes, "warnings": warnings}


# =============================================================================
# the coming week's free-agent pool (rules 10-11) and the add budget (rule 7)
# =============================================================================

def pool(world: World, ents: list) -> dict:
    """{free agent: None, or the entry id that dropped him}. Yahoo's free
    agents now (PLAYERLIST minus every roster) minus every live claim, plus
    every live chat drop, in entry order."""
    from .data_loader import roster_index
    rostered = roster_index(world.rosters)
    out = {n: None for n in world.playerlist if n not in rostered}
    for e in ents:
        for ph, m, n, _ in _parts(e):
            if ph == "add":
                out.pop(_in(n, out) or n, None)
            elif ph == "drop":
                out.pop(_in(n, out) or n, None)
                out[n] = e["id"]
    return out


def reserved_by(ents: list, name: str) -> Optional[dict]:
    hit = None
    for e in ents:
        for ph, m, n, _ in _parts(e):
            if ph == "add" and _same(n, name):
                hit = e
            elif ph == "drop" and _same(n, name):
                hit = None
    return hit


def budget_claims(ents: list) -> list:
    """Every unvoided claim, for transaction_rulings.add_budget_week's
    `ledger` argument: [{"manager", "player", "window", "claim_week", "entry"}].
    A claim is matched to the Yahoo add that applies it by manager, player and
    the Yahoo date = its window day."""
    out = []
    for e in ents:
        if e.get("voided") or e["kind"] != "move":
            continue
        for n in e["parsed"]["add"]:
            out.append({"manager": e["parsed"]["manager"], "player": n, "window": e["window"],
                        "claim_week": int(e["claim_week"]), "entry": e["id"]})
    return out


def _yahoo_added(world: World, claim: dict) -> bool:
    """The Yahoo add applying `claim` is in the log (on its window day, to its team)."""
    return claim_in_log(world.transactions, claim)


def claim_in_log(transactions, claim: dict) -> bool:
    """The Yahoo add applying `claim` ({"manager", "player", "window"}) is in
    `transactions` (the transaction log): made on its window day, to its team.
    A claim applied in Monday's window is pending until the night's
    verification, so a counter that adds pending claims to Yahoo's must skip
    these (adds_used here; the hub's moves by budget week)."""
    for t in transactions:
        if t["league_day"] != claim["window"]:
            continue
        for p in t["players"]:
            if p["action"] == "add" and (p["to"] or {}).get("manager") == claim["manager"] \
                    and _same(p["name"], claim["player"]):
                return True
    return False


def adds_used(world: World, ents: list, states: list, week: int) -> dict:
    """{manager: [players]} counted against budget week `week` by the ledger's
    rule: Yahoo's adds (claims matched to their claim week) plus every claim of
    that week not yet in Yahoo (pending; a claim is used once posted, rule 12)."""
    claims = budget_claims(ents)
    counted = world.yahoo_adds(claims).get(week, {})
    out = {m: list(v) for m, v in counted.items()}
    for c in claims:
        e = next(x for x in ents if x["id"] == c["entry"])
        if c["claim_week"] != week or state_of(e, states) != "pending" or _yahoo_added(world, c):
            continue
        out.setdefault(c["manager"], []).append(c["player"])
    return out


# =============================================================================
# an entry
# =============================================================================

def _parse_at(text: str) -> datetime:
    from .league_clock import league_tz
    try:
        dt = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise EntryRefused(f"--at {text!r}: write 'YYYY-MM-DD HH:MM' (Pacific, the league clock)") from None
    return dt.replace(tzinfo=league_tz())


def resolve(world: World, parsed: dict, coming: dict) -> dict:
    """The parsed entry with full names. Adds resolve among every NBA player;
    drops and IL parts among the manager's roster as of the coming window
    (then, failing that, among every player, to say whose he is); a trade's
    players among the other side's roster."""
    def on_roster(typed, m, what):
        t = coming[m]
        try:
            return resolve_name(typed, t.active + t.il, f"({what}, {m}'s roster)")
        except NameUnknown:
            who = resolve_name(typed, world.universe, f"({what})")
            raise EntryRefused(f"{who} is not on {m}'s roster as of the coming window") from None

    if parsed["kind"] == "trade":
        a, b = parsed["sides"]
        return {"kind": "trade", "sides": [
            {"manager": a["manager"], "gets": [on_roster(n, b["manager"], f"{a['manager']} gets")
                                               for n in a["gets"]]},
            {"manager": b["manager"], "gets": [on_roster(n, a["manager"], f"{b['manager']} gets")
                                               for n in b["gets"]]}]}
    m = parsed["manager"]
    out = {"kind": "move", "manager": m,
           "add": [resolve_name(n, world.universe, "(+add)") for n in parsed["add"]],
           "drop": [], "il_place": [], "il_activate": []}
    for kind in ("drop", "il_place", "il_activate"):
        for n in parsed[kind]:
            # rule 12: a claimed player may be dropped before he joins
            pend = [c for c in coming.get("_claims", {}).get(m, [])]
            try:
                out[kind].append(on_roster(n, m, PART_LABEL[kind]))
            except EntryRefused:
                if kind == "drop" and pend:
                    out[kind].append(resolve_name(n, pend, f"(-drop, {m}'s pending claims)"))
                else:
                    raise
    names = [x for k in ("add", "drop", "il_place", "il_activate") for x in out[k]]
    if any(_same(a, b) for i, a in enumerate(names) for b in names[i + 1:]):
        raise EntryRefused("the same player is named twice in one entry")
    return out


def make_entry(world: World, text: str, rows: list, states: list, *, claimed_at: datetime = None,
               entered_by: str = "Nick", issue: int = None) -> dict:
    """The entry row for `text`, every check passed, or EntryRefused. Writes
    nothing (add() writes). issue: the phone entry's issue number (Step 3a,
    design s.6.3), recorded on the row as "issue"."""
    from .data_loader import roster_index
    parsed = parse(text, world.managers)
    ents = entries(rows)
    lv = live(world, ents, states)
    now = world.now
    at = claimed_at or now
    if at.tzinfo is None:
        raise EntryRefused("the claim time must be on the league clock")
    if at > now:
        raise EntryRefused(f"the claim time {at:%Y-%m-%d %H:%M} is in the future")
    cw = world.week_of(at.date())
    if cw is None:
        first = min(a for a, _ in world.weeks.values())
        if at.date() < first:
            raise EntryRefused("a pre-season move is made in Yahoo and counts nowhere (rule 14): "
                               "nothing to enter")
        raise EntryRefused(f"{at.date()} is after the last fantasy week: no window is left")
    ww = cw + 1
    if ww not in world.weeks:
        raise EntryRefused(f"a claim in week {cw} would take effect in week {ww}, which is not in "
                           "the schedule")
    wday = world.window_day(ww)
    close = world.window_close(wday)
    if now >= close:
        raise EntryRefused(f"its window ({wday:%a %m-%d}) has closed: enter only moves still to be "
                           "applied")
    if parsed["kind"] == "trade" and at.date() > world.deadline:
        raise EntryRefused(f"the trade deadline was {world.deadline:%Y-%m-%d} (rule 13): a trade "
                           f"agreed {at.date():%Y-%m-%d} is refused")
    # the coming roster before this entry: every live entry for windows <= ww
    before = simulate(world, lv, ww, strict=set())
    coming = dict(before["teams"])
    claims = {}
    for e in lv:
        if e["kind"] == "move" and int(e["window_week"]) == ww:
            claims.setdefault(e["parsed"]["manager"], []).extend(e["parsed"]["add"])
    coming["_claims"] = claims
    full = resolve(world, parsed, coming)
    new = {"row": "entry", "id": len(ents) + 1, "text": text.strip(), "kind": parsed["kind"],
           "parsed": ({k: v for k, v in full.items() if k != "kind"}),
           "claimed_at": at.isoformat(timespec="seconds"), "claim_week": cw, "window_week": ww,
           "window": wday.isoformat(), "entered_at": now.isoformat(timespec="seconds"),
           "entered_by": entered_by, "checks": []}
    if issue is not None:
        if any(e.get("issue") == int(issue) for e in ents):
            raise EntryRefused(f"issue #{issue} is already ledger entry "
                               f"{next(e['id'] for e in ents if e.get('issue') == int(issue))}")
        new["issue"] = int(issue)
    checks = []
    # adds: in the coming week's pool (rules 10-11), and the claim week's budget (rule 7)
    if full["kind"] == "move" and full["add"]:
        fa = pool(world, lv)
        rostered = roster_index(world.rosters)
        for n in full["add"]:
            hit = _in(n, fa)
            if hit is not None:
                dropped_by = fa[hit]
                checks.append(f"{n} is in the coming week's pool"
                              + (f" (dropped in the chat, entry {dropped_by})" if dropped_by else ""))
                continue
            r = reserved_by(lv, n)
            if r is not None:
                raise EntryRefused(f"{n} is reserved: {r['parsed']['manager']} claimed him "
                                   f"(entry {r['id']}, {r['claimed_at'][:16].replace('T', ' ')}; rule 10)")
            owner = rostered.get(n)
            if owner is not None:
                raise EntryRefused(f"{n} is on {owner}'s roster")
            if _in(n, world.playerlist) is None:
                raise EntryRefused(f"{n} is not in data/PLAYERLIST.xlsx (Yahoo's player list): the "
                                   "engine cannot place or price him; refetch PLAYERLIST or ask")
            raise EntryRefused(f"{n} is not a free agent for the coming week")
        used = adds_used(world, ents, states, cw).get(full["manager"], [])
        if len(used) + len(full["add"]) > world.budget:
            raise EntryRefused(f"{full['manager']} has used {len(used)} of {world.budget} adds in week "
                               f"{cw} ({', '.join(used)}): a claim posted now counts in week {cw} "
                               f"(rule 7), and the league's limit is {world.budget} (Yahoo's 6 "
                               "notwithstanding)")
        checks.append(f"week {cw} adds: {len(used)} used before, {len(used) + len(full['add'])} of "
                      f"{world.budget} with this one")
    # the roster after the window: rules 1-3, 15
    after = simulate(world, lv + [new], ww, strict={new["id"]}, at_entry=True)
    mine = [p for p in after["problems"] if p[0] == new["id"]]
    if mine:
        raise EntryRefused(mine[0][2])
    for m, t in after["teams"].items():
        if len(t.active) > world.active_spots or len(t.il) > world.il_slots:
            touched = m in ([full["manager"]] if full["kind"] == "move"
                            else [s["manager"] for s in full["sides"]])
            if touched:
                raise EntryRefused(f"{m} would have {len(t.active)} active and {len(t.il)} IL after "
                                   f"the {wday:%m-%d} window ({world.active_spots} and "
                                   f"{world.il_slots} allowed): enter the drop first")
    for m in ([full["manager"]] if full["kind"] == "move" else [s["manager"] for s in full["sides"]]):
        t = after["teams"][m]
        checks.append(f"{m} after the {wday:%m-%d} window: {len(t.active)} active, {len(t.il)} IL")
    warns = [w_ for eid, _m, w_ in after["warnings"] if eid == new["id"]]
    if full["kind"] == "move" and full["il_place"]:
        for n in full["il_place"]:
            checks.append(f"IL+{n}: {world.il_entry_check(n, wday)[1]} now; only his Yahoo tag counts "
                          "at the window")
    new["checks"] = checks + [f"WARNING: {w_}" for w_ in warns]
    if warns:
        new["warnings"] = warns
    return new


def add(base_path, text: str, *, now: datetime = None, claimed_at: datetime = None,
        entered_by: str = "Nick", world: World = None, issue: int = None) -> dict:
    """Check `text` and append it to config/MOVE_LEDGER.json. Returns the row.
    The desk (scripts/ledger.py) and Nick's phone (scripts/apply_entry.py,
    with the issue number) both come through here: the same checks."""
    from .league_clock import league_now
    base = Path(base_path)
    rows = read_rows(base)
    states = read_states(base)
    world = world or World.from_base(base, now=now or league_now())
    row = make_entry(world, text, rows, states, claimed_at=claimed_at, entered_by=entered_by,
                     issue=issue)
    write_entries(base, rows, [row])
    return row


def void(base_path, entry_id: int, reason: str, *, by: str = "Nick", now: datetime = None) -> dict:
    """Nick's ruling on an entry he typed by mistake: it stays in the ledger and
    does nothing. Not a cancel (rule 12): a real claim stands."""
    from .league_clock import league_now
    base = Path(base_path)
    rows = read_rows(base)
    if not str(reason or "").strip():
        raise EntryRefused("a void needs a reason")
    ent = [e for e in entries(rows) if e["id"] == int(entry_id)]
    if not ent:
        raise EntryRefused(f"there is no entry {entry_id}")
    if ent[0]["voided"]:
        raise EntryRefused(f"entry {entry_id} is already voided")
    st = state_of(ent[0], read_states(base))
    if st != "pending":
        raise EntryRefused(f"entry {entry_id} is {st}: only a pending entry can be voided; a "
                           "verified one is settled (ask the reviewing session for a ruling)")
    row = {"row": "void", "entry": int(entry_id), "by": by,
           "on": (now or league_now()).isoformat(timespec="seconds"), "reason": reason.strip()}
    write_entries(base, rows, [row])
    return row


def recheck(world: World, rows: list, states: list) -> list:
    """[(entry id, "ok" | reason)] for every live entry, checked again now
    (IL eligibility with today's tags, presence, room): `ledger.py check`."""
    ents = entries(rows)
    lv = live(world, ents, states)
    out = []
    for e in lv:
        sim = simulate(world, lv, int(e["window_week"]), strict={e["id"]}, check_day=world.now.date())
        mine = [p for p in sim["problems"] if p[0] == e["id"]]
        out.append((e["id"], mine[0][2] if mine else "ok"))
    return out


# =============================================================================
# the Monday checklist (design s.6.4)
# =============================================================================

def _line_text(x: dict) -> str:
    m, n = x["team"], x["player"]
    return {"il_place": f"{m}: move {n} into an IL slot",
            "il_swap": f"{m}: swap {n} into the IL slot, {x.get('other')} out of it",
            "drop": f"{m}: drop {n}",
            "trade": f"{m} gets {n} from {x.get('other')} (trade)",
            "add": f"{m}: add {n}",
            "drop_after_join": f"{m}: drop {n} (just added; rule 12)",
            "il_activate": f"{m}: activate {n} from the IL slot"}[x["phase"]]


line_text = _line_text          # one checklist line in words (the hub's grid note uses it too)


def rosters_after(world: World, rows: list, states: list, upto_week: int) -> dict:
    """The rosters as they will stand once every live entry (pending, unvoided,
    its window still open) up to window `upto_week` is applied, window by
    window in the checklist's order (simulate, every entry non-strict: a part
    already in Yahoo's roster is skipped, one that can no longer apply is
    noted). Facts, in both ledger modes: the hub's next-week grid (task 43a).
    {"rosters": {m: [names]}, "il": {m: [names]}, "lines": [checklist line
    texts, in order], "notes": [parts that could not apply], "entries": [ids]}."""
    ents = [e for e in live(world, entries(rows), states) if int(e["window_week"]) <= int(upto_week)]
    sim = simulate(world, ents, int(upto_week), strict=set())
    lines = [line_text(x) for w in sorted(sim["lines"]) for x in sim["lines"][w]["lines"]]
    return {"rosters": {m: list(t.active) + list(t.il) for m, t in sim["teams"].items()},
            "il": {m: list(t.il) for m, t in sim["teams"].items()},
            "lines": lines, "notes": list(sim["notes"]), "entries": [e["id"] for e in ents]}


def checklist(world: World, rows: list, states: list, week: int, *, run_id: str = None) -> dict:
    """The window's checklist for fantasy week `week` (its Monday): every live
    entry for it, IL eligibility checked again on the window day. Per team:
    IL placements, drops, adds, IL activations; across teams every drop before
    every add (one global order by phase). A team whose lines cannot be
    ordered stops with the reason; Nick decides, the engine never substitutes."""
    ents = entries(rows)
    lv = live(world, ents, states)
    mine = [e for e in lv if int(e["window_week"]) == int(week)]
    sim = simulate(world, lv, int(week), strict={e["id"] for e in mine},
                   check_day=world.window_day(week))
    block = sim["lines"].get(int(week), {"lines": [], "stopped": {}})
    stopped = {}
    for eid, m, why in sim["problems"]:
        if any(e["id"] == eid for e in mine):
            stopped.setdefault(m, {"team": m, "reason": why, "entries": []})
            if eid not in stopped[m]["entries"]:
                stopped[m]["entries"].append(eid)
    # rule 3: a healthy player sitting in an IL slot blocks every move of his
    # team in Yahoo. The checklist puts activations last, so a team in that
    # state stops whether or not its lines activate him: Nick orders it.
    wday_ = world.window_day(week)
    for m in sorted({x["team"] for x in block["lines"]} - set(stopped)):
        for n in world.il.get(m, []):
            ok, why = world.il_eligible(n, wday_)
            if not ok:
                ids = sorted({x["entry"] for x in block["lines"] if x["team"] == m})
                stopped[m] = {"team": m, "entries": ids,
                              "reason": f"{n} sits in an IL slot and is not O or OFS on "
                                        f"{wday_:%a %m-%d}: Yahoo allows {m} no moves until he leaves it "
                                        "(rule 3); the checklist puts activations last, so Nick "
                                        "orders this team"}
                break
    order = {ph: i for i, ph in enumerate(("il_place", "il_swap", "drop", "trade", "add",
                                           "drop_after_join", "il_activate"))}
    lines = [x for x in block["lines"] if x["team"] not in stopped]
    lines.sort(key=lambda x: (order[x["phase"]], world.managers.index(x["team"])
                              if x["team"] in world.managers else 99, x["entry"]))
    wday = world.window_day(week)
    return {"schema": 1, "week": int(week), "window": wday.isoformat(),
            "closes": world.window_close(wday).isoformat(timespec="minutes"),
            "built_at": world.now.isoformat(timespec="seconds"), "run_id": run_id,
            "lines": [{"n": i + 1, "phase": x["phase"], "team": x["team"], "player": x["player"],
                       "other": x.get("other"), "entry": x["entry"], "text": _line_text(x)}
                      for i, x in enumerate(lines)],
            "stopped": sorted(stopped.values(), key=lambda s: s["team"]),
            "order": ("IL placements, then drops, trades, adds, then drops of players who join in "
                      "this window (rule 12), then IL activations; every drop before every add."),
            "notes": sim["notes"]}


def checklist_path(base_path, week: int) -> Path:
    return Path(base_path) / CHECKLIST_DIR / f"move_checklist_week{int(week)}.json"


def format_checklist(cl: dict, states_by_entry: dict = None) -> list:
    out = [f"Week {cl['week']} window, {cl['window']} (closes {cl['closes'][11:16]} Pacific):"]
    if not cl["lines"] and not cl["stopped"]:
        out.append("  no chat moves to apply in this window")
    for x in cl["lines"]:
        st = (states_by_entry or {}).get(x["entry"], "pending")
        out.append(f"  {x['n']:2d}. [{st}] {x['text']}  (entry {x['entry']})")
    for s in cl["stopped"]:
        out.append(f"  STOPPED {s['team']} (entries {', '.join(map(str, s['entries']))}): {s['reason']}")
    return out


# =============================================================================
# verification (design s.6.4)
# =============================================================================

def _tx_time(t: dict) -> datetime:
    return datetime.fromisoformat(t["time"])


def in_window(world: World, t: dict) -> Optional[int]:
    """The fantasy week whose Monday window `t` was made in, or None."""
    d = date.fromisoformat(t["league_day"])
    w = world.week_of(d)
    if w is None or world.weeks[w][0] != d:
        return None
    if world.window_open(w) <= _tx_time(t) < world.window_close(d):
        return w
    return None


def _player_hits(txs, action, manager, name, side):
    hits = []
    for t in txs:
        for p in t["players"]:
            if p["action"] == action and (p[side] or {}).get("manager") == manager \
                    and _same(p["name"], name):
                hits.append(t)
    return hits


def verify(world: World, rows: list, states: list, *, run_id: str) -> tuple:
    """Check every pending entry against Yahoo's transaction log and live IL
    slots. Returns (new state rows, report). An entry becomes
      applied   every add, drop and trade part matched by a transaction in its
                window (right team, player, day) and, once the window has
                closed, its IL parts shown by Yahoo's IL slots;
      missing   the window closed without one of them;
      conflict  a player it reserved was taken by another team, or a part
                was applied twice.
    Plus every Yahoo transaction since ledger_verify_from outside a Monday
    window that no entry matches (rule 4), once each. The ledger never edits
    Yahoo or the logs."""
    ents = entries(rows)
    stamp = world.now.isoformat(timespec="seconds")
    new, report = [], {"applied": [], "missing": [], "conflict": [], "pending": [], "unmatched": [],
                       "flags": []}
    for e in ents:
        if state_of(e, states) != "pending":
            continue
        wday = date.fromisoformat(e["window"])
        ww = int(e["window_week"])
        close = world.window_close(wday)
        opened = world.window_open(ww)
        win = [t for t in world.transactions if opened <= _tx_time(t) < close]
        keys, unmatched, conflicts = [], [], []
        for ph, m, n, other in _parts(e):
            if ph in ("add", "drop", "trade"):
                action = "trade" if ph == "trade" else ph
                side = "from" if ph == "drop" else "to"
                hits = _player_hits(win, action, m, n, side)
                if len(hits) > 1 and ph != "drop":
                    conflicts.append(f"{m} {PART_LABEL.get(ph, 'gets ')}{n} was applied "
                                     f"{len(hits)} times ({', '.join(t['key'] for t in hits)})")
                if hits:
                    keys += [t["key"] for t in hits]
                else:
                    unmatched.append(f"{PART_LABEL.get(ph, m + ' gets ')}{n}")
            if ph in ("add", "trade"):
                claimed = datetime.fromisoformat(e["claimed_at"])
                for t in world.transactions:
                    if _tx_time(t) <= claimed:
                        continue
                    for p in t["players"]:
                        to = (p["to"] or {}).get("manager")
                        if p["action"] in ("add", "trade") and to and to != m \
                                and _same(p["name"], n):
                            conflicts.append(f"{n}, reserved by {m} (entry {e['id']}), was added by "
                                             f"{to} at {t['time'][:16].replace('T', ' ')} ({t['key']})")
        il_bad = []
        il_parts = [(ph, n) for ph, m, n, _ in _parts(e) if ph in ("il_place", "il_activate")]
        if il_parts and world.now >= close:
            if world.il_week != ww:
                il_bad.append(f"IL parts not checked: Yahoo's IL file is week {world.il_week}, "
                              f"not week {ww}")
            else:
                m = e["parsed"]["manager"]
                il_now = list(world.il.get(m, []))
                for ph, n in il_parts:
                    if ph == "il_place" and _in(n, il_now) is None:
                        unmatched.append(f"IL+{n} (not in {m}'s IL slot after the window)")
                    if ph == "il_activate" and _in(n, il_now) is not None:
                        unmatched.append(f"IL-{n} (still in {m}'s IL slot after the window)")
        label = f"entry {e['id']} ({e['text']})"
        if conflicts:
            row = {"row": "state", "entry": e["id"], "state": "conflict", "at": stamp, "by": run_id,
                   "why": "; ".join(conflicts), "transactions": sorted(set(keys))}
            new.append(row)
            report["conflict"].append(f"{label}: {row['why']}")
        elif il_bad:
            report["pending"].append(f"{label}: {il_bad[0]}")
            report["flags"].append(f"{label}: {il_bad[0]}")
        elif not unmatched and (world.now >= close or not il_parts):
            row = {"row": "state", "entry": e["id"], "state": "applied", "at": stamp, "by": run_id,
                   "why": "matched in Yahoo", "transactions": sorted(set(keys))}
            new.append(row)
            report["applied"].append(label)
        elif world.now >= close:
            row = {"row": "state", "entry": e["id"], "state": "missing", "at": stamp, "by": run_id,
                   "why": f"the {wday:%m-%d} window closed {close:%H:%M} without "
                          + ", ".join(unmatched), "transactions": sorted(set(keys))}
            new.append(row)
            report["missing"].append(f"{label}: {row['why']}")
        else:
            report["pending"].append(f"{label}: waiting for {', '.join(unmatched) or 'the window to close'}")
    # rule 4: transactions outside a Monday window that match no entry
    seen = {r["key"] for r in states if r.get("row") == "unmatched"}
    first = world.verify_from
    if first is None:
        raise LedgerError("the world has no verify_from (roster_moves.ledger_verify_from)")
    season_first = min(a for a, _ in world.weeks.values())
    for t in world.transactions:
        d = date.fromisoformat(t["league_day"])
        if d < first or d < season_first or t["key"] in seen:
            continue
        if in_window(world, t) is not None:
            continue
        who = sorted({(p["to"] or {}).get("manager") or (p["from"] or {}).get("manager") or "?"
                      for p in t["players"]})
        what = ", ".join(f"{p['action']} {p['name']}" for p in t["players"])
        why = (f"{t['time'][:16].replace('T', ' ')} {'/'.join(who)}: {what} -- outside a Monday "
               "window, and no ledger entry matches it (rule 4)")
        new.append({"row": "unmatched", "key": t["key"], "at": stamp, "by": run_id, "why": why})
        report["unmatched"].append(why)
    report["flags"] += ([f"MISSING {x}" for x in report["missing"]]
                        + [f"CONFLICT {x}" for x in report["conflict"]]
                        + [f"UNMATCHED {x}" for x in report["unmatched"]])
    return new, report


# =============================================================================
# shadow mode: the ledger's counts beside the rulings'
# =============================================================================

def shadow_compare(base_path, schedule: dict, ents: list) -> dict:
    """{"differences": [...], "error": str|None}: every (budget week, manager)
    whose add count differs between the TRANSACTION_RULINGS count (what the
    engine prints, in shadow mode) and the ledger's (claims matched to their
    claim week). A ruling that contradicts a ledger claim is reported, not
    raised: shadow mode reports disagreements."""
    from . import transaction_rulings as tr
    base = Path(base_path)
    claims = budget_claims(ents)
    a = tr.adds_by_budget_week(base, schedule, ledger=None)
    try:
        b = tr.adds_by_budget_week(base, schedule, ledger=claims)
    except tr.RulingError as e:
        return {"differences": [], "error": str(e), "rulings": a, "ledger": None}
    diffs = []
    for w in sorted(set(a) | set(b)):
        for m in sorted(set(a.get(w, {})) | set(b.get(w, {}))):
            x, y = sorted(a.get(w, {}).get(m, [])), sorted(b.get(w, {}).get(m, []))
            if x != y:
                diffs.append({"week": w, "manager": m, "rulings": x, "ledger": y,
                              "text": f"week {w} {m}: rulings count {len(x)} ({', '.join(x) or '-'}), "
                                      f"the ledger {len(y)} ({', '.join(y) or '-'})"})
    return {"differences": diffs, "error": None, "rulings": a, "ledger": b}


# =============================================================================
# on mode: pending moves for the roster plan (design s.6.3)
# =============================================================================

def known_moves(base_path=".", now: datetime = None) -> dict:
    """{window week: {manager: {"il_place", "drop", "add", "il_activate"}}}
    from every pending, unvoided entry whose window is still open: the roster
    plan's KNOWN pickups (roster_plan.build(known=...)). Read only in "on"
    mode (roster_plan.for_run asks mode() first). A trade is a drop for the
    giver and an add for the getter."""
    from .league_clock import league_now
    from . import price_lock
    now = now or league_now()
    rows = read_rows(base_path)
    states = read_states(base_path)
    out = {}
    for e in entries(rows):
        if state_of(e, states) != "pending":
            continue
        if now >= price_lock.window_close(date.fromisoformat(e["window"])):
            continue
        w = out.setdefault(int(e["window_week"]), {})
        for ph, m, n, other in _parts(e):
            if ph == "trade":
                w.setdefault(other, {"il_place": [], "drop": [], "add": [], "il_activate": []})["drop"].append(n)
                ph = "add"
            w.setdefault(m, {"il_place": [], "drop": [], "add": [], "il_activate": []})[ph].append(n)
    return out


# =============================================================================
# the hub (design s.3, s.6.3): facts update as soon as an entry lands
# =============================================================================

def _mon(d: date) -> str:
    return f"{d:%a} {d:%m-%d}"


FEED_STATE = {"pending": "Pending", "applied": "Applied", "missing": "Missing", "conflict": "Conflict",
              "void": "Voided"}


def hub_view(base_path, now: datetime, nba_schedule, *, feed_days: int = 7) -> dict:
    """What the hub shows from the ledger, as of `now`:
      claimed   {player: {"manager", "window", "entry"}}   live claims: off the free agents
      dropped   {player: {"manager", "window", "entry"}}   live chat drops: on them,
                                                           "available from Mon MM-DD"
      joins     {manager: [{"player", "window", "entry", "text"}]}
      chips     {manager: {player: [chip]}}               "leaves Mon MM-DD", "IL from ...",
                                                           "active from ..."
      pending_adds {claim week: {manager: [player]}}      live claims not yet in Yahoo
      live_claims  [{"manager", "player", "window", "claim_week", "entry"}]
                                                           the same claims, one row each
                                                           (the moves by budget week)
      feed      [moves-feed items], the entries claimed in the last `feed_days`
                days or still pending, with their states
    Live = pending, unvoided, its window not yet closed."""
    from . import price_lock
    base = Path(base_path)
    rows, states = read_rows(base), read_states(base)
    ents = entries(rows)
    out = {"claimed": {}, "dropped": {}, "joins": {}, "chips": {}, "pending_adds": {}, "live_claims": [],
           "feed": []}
    since = now.date() - timedelta(days=feed_days - 1)
    for e in ents:
        st = state_of(e, states)
        wday = date.fromisoformat(e["window"])
        open_ = now < price_lock.window_close(wday, nba_schedule)
        live_ = st == "pending" and open_
        claimed = datetime.fromisoformat(e["claimed_at"])
        if live_:
            for ph, m, n, other in _parts(e):
                info = {"manager": m, "window": e["window"], "entry": e["id"]}
                chips = out["chips"].setdefault(m, {})
                if ph == "add":
                    out["dropped"].pop(n, None)
                    out["claimed"][n] = info
                    out["joins"].setdefault(m, []).append(
                        {"player": n, "window": e["window"], "entry": e["id"],
                         "text": f"+ {n} joins {_mon(wday)} (claimed {_mon(claimed.date())})"})
                    out["pending_adds"].setdefault(int(e["claim_week"]), {}).setdefault(m, []).append(n)
                    out["live_claims"].append({"manager": m, "player": n, "window": e["window"],
                                               "claim_week": int(e["claim_week"]), "entry": e["id"]})
                elif ph == "drop":
                    out["claimed"].pop(n, None)
                    out["dropped"][n] = info
                    chips.setdefault(n, []).append({"text": f"leaves {_mon(wday)}", "kind": "out"})
                elif ph == "il_place":
                    chips.setdefault(n, []).append({"text": f"IL from {_mon(wday)}", "kind": "il"})
                elif ph == "il_activate":
                    chips.setdefault(n, []).append({"text": f"active from {_mon(wday)}", "kind": "new"})
                elif ph == "trade":
                    out["chips"].setdefault(other, {}).setdefault(n, []).append(
                        {"text": f"traded to {m} {_mon(wday)}", "kind": "out"})
                    out["joins"].setdefault(m, []).append(
                        {"player": n, "window": e["window"], "entry": e["id"],
                         "text": f"\u21c4 {n} joins {_mon(wday)} (trade with {other})"})
        if st == "pending" or claimed.date() >= since:
            out["feed"].append(feed_item(e, st, claimed, wday))
    return out


def feed_item(e: dict, st: str, claimed: datetime, wday: date) -> dict:
    """One ledger entry as the hub's moves feed shows it, beside Yahoo's
    transactions (transaction_log.feed_item's shape)."""
    from .transaction_log import PART_MARKER
    p = e["parsed"]
    if e["kind"] == "trade":
        parts = [{"kind": "trade", "marker": PART_MARKER["trade"],
                  "text": f"{s['manager']} gets {', '.join(s['gets'])}"} for s in p["sides"]]
        who = "Trade:"
        note = f"agreed in the group chat; takes effect {_mon(wday)}"
    else:
        parts = ([{"kind": "add", "marker": PART_MARKER["add"], "text": f"claimed {n}"} for n in p["add"]]
                 + [{"kind": "drop", "marker": PART_MARKER["drop"], "text": f"dropped {n}"} for n in p["drop"]]
                 + [{"kind": "il", "marker": "IL", "text": f"{n} to IL"} for n in p["il_place"]]
                 + [{"kind": "il", "marker": "IL", "text": f"{n} off IL"} for n in p["il_activate"]])
        who = p["manager"]
        note = (f"group chat; week {e['claim_week']} budget; applied {_mon(wday)}" if p["add"]
                else f"group chat; applied {_mon(wday)}")
    if e.get("voided"):
        note += f"; voided: {e['voided']['reason']}"
    return {"_ts": int(claimed.timestamp()), "day": claimed.strftime("%a"),
            "date": f"{claimed.month}/{claimed.day}", "time": claimed.strftime("%I:%M %p").lstrip("0"),
            "who": who, "what": ", ".join(x["text"] for x in parts), "parts": parts, "note": note,
            "state": FEED_STATE[st], "kind": "ledger"}


YAHOO_ADD_URL = "https://basketball.fantasysports.yahoo.com/nba/{league}/addplayer?apid={pid}"


def yahoo_add_url(league_key: str, yahoo_id) -> str:
    """Yahoo's add page for a player (Nick tested it 11-08: league 16778, Ty
    Jerome 6212). The id is the number after "p." in a player key."""
    m = re.search(r"\.l\.(\d+)", str(league_key or ""))
    if not m:
        raise ValueError(f"no league id in league key {league_key!r}")
    return YAHOO_ADD_URL.format(league=m.group(1), pid=int(yahoo_id))


def yahoo_ids(base_path, transactions: list = None):
    """PlayerIndex {player name: Yahoo id} from PLAYERLIST's yahoo_id column
    (written by every fetch since F8), then the transaction log's player
    keys. A name in neither has no link; nothing is guessed."""
    import pandas as pd
    from .data_loader import PlayerIndex
    out = {}
    pl = Path(base_path) / "data" / "PLAYERLIST.xlsx"
    if pl.is_file():
        frame = pd.read_excel(pl)
        if "yahoo_id" in frame.columns:
            for n, y in zip(frame["player_name"], frame["yahoo_id"]):
                if pd.notna(y):
                    out[str(n)] = int(y)
    for t in transactions or []:
        for pp in t.get("players", []):
            mm = re.search(r"\.p\.(\d+)$", str(pp.get("player_key") or ""))
            if mm:
                out.setdefault(str(pp["name"]), int(mm.group(1)))
    return PlayerIndex(out)


def checklist_for_nick(cl: dict, rows: list, states: list, *, ids=None,
                       league_key: str = None, managers: list = None) -> list:
    """The checklist as Nick reads it (F6, 11-09: off the hub, his alone):
    per team, teams in the order their first step comes, each step keeping its
    number in the one order across teams; a stopped team with the reason and
    the entries it holds; each add with its Yahoo add link when the player's
    id is known (F8). Lines of text."""
    sts = {e["id"]: state_of(e, states) for e in entries(rows)}
    by_id = {e["id"]: e for e in entries(rows)}
    close = datetime.fromisoformat(cl["closes"])
    wday = date.fromisoformat(cl["window"])
    out = [f"Week {cl['week']} window: {wday:%a %m-%d}, closes "
           f"{close.strftime('%I:%M %p').lstrip('0')} Pacific.",
           f"Do the numbered steps in this order, across teams: {cl['order']}", ""]
    teams = []
    for x in list(cl["lines"]) + list(cl["stopped"]):
        if x["team"] not in teams:
            teams.append(x["team"])
    for t in teams:
        out.append(t)
        for x in [x for x in cl["lines"] if x["team"] == t]:
            out.append(f"  {x['n']:2d}. {x['text']}  [{sts.get(x['entry'], 'pending')}; entry {x['entry']}]")
            if x["phase"] == "add":
                pid = ids.get(x["player"]) if ids is not None else None
                out.append("      " + (yahoo_add_url(league_key, pid) if pid is not None and league_key
                                       else f"no Yahoo add link: {x['player']} has no Yahoo id on file"))
        for s_ in [s_ for s_ in cl["stopped"] if s_["team"] == t]:
            out.append(f"  BLOCKED: {s_['reason']}")
            for eid in s_["entries"]:
                e = by_id.get(eid)
                out.append(f"      entry {eid}: {e['text'] if e else '?'}")
    idle = [m for m in (managers or []) if m not in teams]
    if idle:
        out.append(f"{', '.join(idle)}: nothing to do.")
    if not cl["lines"] and not cl["stopped"]:
        out.append("No group-chat moves to apply in this window.")
    return out
