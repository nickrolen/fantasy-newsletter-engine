#!/usr/bin/env python3
"""
overrides.py -- write and check config/INJURY_OVERRIDES.json.

THE POLICY (STATUS_2026-10-28, "Overrides policy"): the overrides file
describes INJURIES, not rosters. Every player with a timeline longer than the
three games a Yahoo tag models goes in, rostered or not. An entry for a
player on no roster is inert until he reappears -- which is the point.

    py scripts/overrides.py add "Tyrese Haliburton" --out 2026-10-27 --back 2026-11-17 --notes "hamstring"
    py scripts/overrides.py add "Jalen Williams" --out 2026-10-20 --season --notes "knee"
    py scripts/overrides.py check
    py scripts/overrides.py refresh-reference

add      computes out_weeks, return_week, return_date, return_games and
         total_week_games from his NBA team's schedule and the FANTASY weeks
         (config/SCHEDULE.json; week 7 is 14 days), prints the entry, asks
         y/n (--yes skips), and writes atomically: every other entry and key
         untouched, nba_team stored, last_updated set to today. Refuses a
         name that matches no NBA player, a --back in the past / outside the
         season / not after --out, a team it cannot determine (then --team),
         and an existing entry for him (then --replace).
         --season: out for the rest of the season -- out through the last
         fantasy week, with no return_week or return_date (Nick, 10-28). No
         stated return, so a rostered OFS tag raises no SeasonOutConflict.
         (Jalen Williams and Cason Wallace are expected back for the Cup:
         ordinary returns, --back 2027-03-29.)
check    READ-ONLY. Lists, for a person to judge: (1) players tagged O or OFS
         with no override, rostered first, by projected FPPG; (2) players in
         an IL slot with no override; (3) entries whose return has passed;
         (4) entries whose name matches no NBA player. Exit 1 when 3 or 4 is
         non-empty, 0 otherwise. Lists 1 and 2 are REVIEW lists: a short O is
         what the tag chain is for, and a healthy or short-term player in an
         IL slot is normal (Nick, 10-28) -- a check that failed every
         ordinary week would be ignored.
refresh-reference
         fetches the NBA player-name reference (modules/nba_reference.py).
         add, check and integrity read it and never touch the network.

STEP 3a (HANDOFF_STEP3A s.2.1) -- the edit forms, also behind Nick's phone
entries (scripts/apply_entry.py calls these same functions, never a copy):

    python scripts/overrides.py set-return "Coby White" --back 2026-11-05
    python scripts/overrides.py set-notes "Paolo Banchero" --notes "ankle"
    python scripts/overrides.py remove "Coby White"

set-return  changes ONLY the return date and what is derived from it:
            out_weeks (from the same first out week: the out date is
            untouched), return_week, return_games, total_week_games, and the
            date inside return_notes. Notes, nba_team and every other key are
            untouched. The same date checks as add.
set-notes   changes only notes.
remove      deletes the entry; a name with no entry refuses.

NAMES: a full name as PlayerIndex matches it (accents, suffixes, initials),
else a UNIQUE last name ("Tatum"); two or more refuse listing the candidates,
none refuses with the nearest names (modules/move_ledger.resolve_name, the
ledger's resolver). add resolves among every NBA player (the reference) and
stores the resolved full name; the edit forms resolve among the file's
entries. An add for a player who already has an entry refuses, pointing to the
edit forms.

TIMESTAMPS (task 26): every entry written by add, set-return or set-notes gets
updated_at (the league clock, with its offset); last_updated moves with every
change; every change appends its before and after to output/override_history.jsonl
(modules/override_history), which the closing line reads. Entries written
before this have no updated_at, and none is invented for them.

EXIT CODES: 0 ok; 1 check found something in 3 or 4; 2 refused / failed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules import injury_entries as ie  # noqa: E402
from modules import nba_reference as nr  # noqa: E402
from modules import override_history as oh  # noqa: E402
from modules.data_loader import PlayerIndex, atomic_write_json  # noqa: E402
from modules.league_clock import league_now, league_today  # noqa: E402

OVERRIDES = Path("config") / "INJURY_OVERRIDES.json"
SCHEDULE = Path("config") / "SCHEDULE.json"
NBA_SCHEDULE = Path("data") / "nba_schedule_2026-27.json"


def _read(base: Path, rel: Path) -> dict:
    path = base / rel
    if not path.is_file():
        raise ie.EntryRefused(f"{path} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def _day(text: str, flag: str) -> date:
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise ie.EntryRefused(f"{flag} {text!r} is not YYYY-MM-DD") from None


# =============================================================================
# add
# =============================================================================

def _names_by_person(ref) -> list:
    """Every name the reference knows, one spelling per person (a roster's,
    else PLAYERLIST's, else basketball-reference's): so "Jokic" is one player,
    not two spellings of him, when a last name is looked up."""
    from modules.move_ledger import _fold
    seen, out = set(), []
    for src in (ref.rostered, list(ref.playerlist), list(ref.this_season), list(ref.last_season)):
        for n in src:
            k = _fold(n)
            if k and k not in seen:
                seen.add(k)
                out.append(str(n))
    return out


def resolve_player(name: str, reference) -> str:
    """The NBA player `name` means: a full name through the reference
    (PlayerIndex: accents, suffixes, initials), else a unique last name.
    Ambiguous refuses listing the candidates; unknown refuses with the nearest
    names (move_ledger.resolve_name, the ledger's resolver)."""
    from modules import move_ledger as ml
    hit = reference.resolve(name)
    if hit is not None:
        return _names_by_person_pick(reference, hit)
    try:
        return ml.resolve_name(name, _names_by_person(reference), "(an NBA player)")
    except ml.NameAmbiguous as e:
        raise ie.EntryRefused(str(e)) from None
    except ml.NameUnknown:
        raise ie.EntryRefused(reference.unknown_message(name)) from None


def _names_by_person_pick(reference, hit: str) -> str:
    """The spelling resolve_player stores for a full-name hit: the roster's,
    else the reference's own."""
    for n in reference.rostered:
        if PlayerIndex({hit: True}).get(n) is not None:
            return str(n)
    return str(hit)


def resolve_entry(blob: dict, name: str) -> tuple:
    """(index in players, the entry's own name) for the entry `name` means,
    among the file's entries: a full name, else a unique last name. No entry
    refuses; ambiguous refuses listing the entries."""
    from modules import move_ledger as ml
    players = list(blob.get("players") or [])
    names = [str(e.get("player_name")) for e in players]
    try:
        hit = ml.resolve_name(name, names, "(among the injury entries)")
    except ml.NameAmbiguous as e:
        raise ie.EntryRefused(str(e)) from None
    except ml.NameUnknown:
        raise ie.EntryRefused(f"{name!r} has no injury entry (entries: "
                              f"{', '.join(sorted(names)) or 'none'})") from None
    return names.index(hit), hit


def _stamp(entry: dict, now: datetime) -> dict:
    out = dict(entry)
    out["updated_at"] = now.isoformat(timespec="seconds")
    return out


def prepare_add(base: Path, name: str, out: str, back: str = None, season: bool = False,
                team: str = None, notes: str = None, return_notes: str = None,
                replace: bool = False, today: date = None, reference=None,
                now: datetime = None) -> tuple:
    """(new file blob, the entry, lines to show). Raises EntryRefused with what
    to do. Writes nothing. The entry carries updated_at (now, the league clock)."""
    now = now or league_now()
    today = today or now.date()
    ref = reference or nr.Reference(base)
    name = resolve_player(name, ref)
    schedule = _read(base, SCHEDULE)
    games = ie.team_games(_read(base, NBA_SCHEDULE))
    out_d = _day(out, "--out")
    back_d = _day(back, "--back") if back else None
    if season and back_d is not None:
        raise ie.EntryRefused("give --back or --season, not both")
    if not season and back_d is None:
        raise ie.EntryRefused("give --back DATE, or --season for the rest of the season")
    ie.check_dates(out_d, back_d, schedule, today)

    found, source = ref.team_for(name)
    shown = []
    if team:
        team = team.upper()
        if team not in games:
            raise ie.EntryRefused(f"--team {team!r} is not a team in the NBA schedule "
                                  f"({', '.join(sorted(games))})")
        if found and found != team:
            shown.append(f"NOTE: --team {team}, but {source} says {found}")
        source = "--team"
    elif found:
        team = found
    else:
        raise ie.EntryRefused(f"cannot determine {name}'s NBA team from PLAYERLIST, ROSTERS.json "
                              "or the reference: pass --team (a code from the NBA schedule)")

    blob = _read(base, OVERRIDES)
    players = list(blob.get("players") or [])
    names = PlayerIndex({str(e.get("player_name")): i for i, e in enumerate(players)})
    hit = names.canonical(name)
    if hit is not None and not replace:
        raise ie.EntryRefused(
            f"{hit} already has an injury entry: change it with "
            f"'Injury: {hit} back MM/DD' or 'Injury: {hit} notes <text>' (overrides.py set-return / "
            f"set-notes), or remove it first ('Injury remove: {hit}'); on the desk, --replace "
            "overwrites it")
    entry, said = ie.compute(name, team, out_d, back_d, season, schedule, games, notes,
                             return_notes)
    entry = _stamp(ie.ordered(entry), now)
    if hit is not None:
        players[dict.__getitem__(names, hit)] = entry
    else:
        players.append(entry)
    new = dict(blob)
    new["players"] = players
    new["last_updated"] = today.isoformat()
    shown += [f"team: {team} ({source})"] + said
    if hit is not None:
        shown.append(f"REPLACES the entry for {hit}")
    return new, entry, shown


# =============================================================================
# a change: the file and its history row, written together (task 26)
# =============================================================================

def change_row(blob: dict, new: dict, action: str, player: str, before, after, *, now: datetime,
               by: str, issue=None) -> dict:
    return oh.make_row(at=now, action=action, player=player, before=before, after=after,
                       last_updated_before=blob.get("last_updated"),
                       last_updated_after=new.get("last_updated"), by=by, issue=issue)


def write_change(base: Path, new: dict, row: dict) -> None:
    """Write the file, then append its history row. The ONLY writer of
    config/INJURY_OVERRIDES.json (tests/test_phone_entries.py pins it)."""
    atomic_write_json(base / OVERRIDES, new)
    oh.append(base, row)


def add_change(base: Path, name: str, *, back: date = None, season: bool = False, notes: str = None,
               now: datetime = None, out_day: date = None, by: str, issue=None,
               reference=None) -> dict:
    """A new entry, out from the day it is made (decision 13a, the league
    clock: out_day, default today). Returns {"action", "player", "before",
    "after", "new", "row", "shown"}; writes nothing (apply() writes)."""
    now = now or league_now()
    blob = _read(base, OVERRIDES)
    new, entry, shown = prepare_add(base, name, (out_day or now.date()).isoformat(),
                                    back.isoformat() if back else None, season, None, notes, None,
                                    False, now.date(), reference, now)
    row = change_row(blob, new, "add", entry["player_name"], None, entry, now=now, by=by, issue=issue)
    return {"action": "add", "player": entry["player_name"], "before": None, "after": entry,
            "new": new, "row": row, "shown": shown}


def _return_notes(text, old: date, new: date):
    """return_notes with the old return date moved to the new one, in the
    same style (MM/DD, M/D, YYYY-MM-DD or MM-DD). Text naming no date is kept
    as it is: it says nothing the new date contradicts."""
    if not text or old is None:
        return text
    styles = (lambda d: d.isoformat(), lambda d: f"{d.month:02d}/{d.day:02d}",
              lambda d: f"{d.month}/{d.day}", lambda d: f"{d.month:02d}-{d.day:02d}")
    import re
    for st in styles:
        pat = r"(?<![0-9/-])" + re.escape(st(old)) + r"(?![0-9/])"
        if re.search(pat, text):
            return re.sub(pat, st(new), text)
    return text


def set_return_change(base: Path, name: str, back: date, *, now: datetime = None, by: str,
                      issue=None, reference=None) -> dict:
    """Only the return date and its derived fields change (set-return)."""
    from modules.absence import parse_return_date
    now = now or league_now()
    today = now.date()
    blob = _read(base, OVERRIDES)
    i, hit = resolve_entry(blob, name)
    old = dict(blob["players"][i])
    schedule = _read(base, SCHEDULE)
    games = ie.team_games(_read(base, NBA_SCHEDULE))
    weeks = [int(w) for w in old.get("out_weeks") or []]
    first = min(weeks) if weeks else old.get("return_week")
    if first is None:
        raise ie.EntryRefused(f"{hit}'s entry has neither out_weeks nor a return_week: its out date "
                              "cannot be kept. Remove it and add it again")
    out_d, _ = ie.week_bounds(schedule, int(first))
    ie.check_dates(out_d, back, schedule, today)
    team = old.get("nba_team")
    if not team:
        ref = reference or nr.Reference(base)
        team, _src = ref.team_for(hit)
        if not team:
            raise ie.EntryRefused(f"{hit}'s entry has no nba_team and the reference has none: "
                                  "edit it on the desk (overrides.py add --replace --team)")
    fresh, said = ie.compute(hit, team, out_d, back, False, schedule, games)
    new_entry = dict(old)
    for k in ("out_weeks", "return_week", "return_games", "total_week_games", "return_date"):
        new_entry[k] = fresh[k]
    if "return_notes" in old:
        new_entry["return_notes"] = _return_notes(old.get("return_notes"),
                                                  parse_return_date(old.get("return_date"), hit), back)
    new_entry = _stamp(ie.ordered(new_entry), now)
    players = list(blob["players"])
    players[i] = new_entry
    new = dict(blob, players=players, last_updated=today.isoformat())
    row = change_row(blob, new, "set-return", hit, old, new_entry, now=now, by=by, issue=issue)
    return {"action": "set-return", "player": hit, "before": old, "after": new_entry, "new": new,
            "row": row, "shown": said}


def set_notes_change(base: Path, name: str, notes: str, *, now: datetime = None, by: str,
                     issue=None) -> dict:
    """Only notes change (set-notes)."""
    now = now or league_now()
    if not str(notes or "").strip():
        raise ie.EntryRefused("set-notes needs the notes text")
    blob = _read(base, OVERRIDES)
    i, hit = resolve_entry(blob, name)
    old = dict(blob["players"][i])
    new_entry = _stamp(ie.ordered(dict(old, notes=str(notes).strip())), now)
    players = list(blob["players"])
    players[i] = new_entry
    new = dict(blob, players=players, last_updated=now.date().isoformat())
    row = change_row(blob, new, "set-notes", hit, old, new_entry, now=now, by=by, issue=issue)
    return {"action": "set-notes", "player": hit, "before": old, "after": new_entry, "new": new,
            "row": row, "shown": []}


def remove_change(base: Path, name: str, *, now: datetime = None, by: str, issue=None) -> dict:
    """The entry goes (remove). A name with no entry refuses."""
    now = now or league_now()
    blob = _read(base, OVERRIDES)
    i, hit = resolve_entry(blob, name)
    old = dict(blob["players"][i])
    players = [e for j, e in enumerate(blob["players"]) if j != i]
    new = dict(blob, players=players, last_updated=now.date().isoformat())
    row = change_row(blob, new, "remove", hit, old, None, now=now, by=by, issue=issue)
    return {"action": "remove", "player": hit, "before": old, "after": None, "new": new, "row": row,
            "shown": []}


def apply(base: Path, change: dict) -> dict:
    """Write a prepared change (the file, then its history row)."""
    write_change(base, change["new"], change["row"])
    return change


def cmd_add(a, base: Path, today: date = None, ask=input, now: datetime = None) -> int:
    now = now or league_now()
    try:
        before_blob = _read(base, OVERRIDES)
        new, entry, shown = prepare_add(base, a.name, a.out, a.back, a.season, a.team, a.notes,
                                        a.return_notes, a.replace, today, now=now)
    except (ie.EntryRefused, nr.ReferenceMissing) as e:
        print(f"REFUSED: {e}")
        return 2
    prior = next((e for e in before_blob.get("players") or []
                  if PlayerIndex({str(e.get("player_name")): True}).get(entry["player_name"]) is not None),
                 None)
    row = change_row(before_blob, new, "add" if prior is None else "replace", entry["player_name"],
                     prior, entry, now=now, by="overrides.py (desk)")
    print("The entry to write to config/INJURY_OVERRIDES.json:\n")
    print(json.dumps(entry, indent=2))
    for line in shown:
        print(f"  {line}")
    if not a.yes:
        try:
            answer = ask("\nWrite it? [y/N] ")
        except EOFError:
            answer = ""
        if str(answer).strip().lower() not in ("y", "yes"):
            print("Not written.")
            return 2
    write_change(base, new, row)
    print(f"Written ({len(new['players'])} entries, last_updated {new['last_updated']}); "
          f"history: {oh.HISTORY_FILE.as_posix()}.")
    return 0


def cmd_edit(a, base: Path, ask=input, now: datetime = None) -> int:
    """set-return / set-notes / remove from the desk."""
    now = now or league_now()
    try:
        if a.cmd == "set-return":
            ch = set_return_change(base, a.name, _day(a.back, "--back"), now=now, by="overrides.py (desk)")
        elif a.cmd == "set-notes":
            ch = set_notes_change(base, a.name, a.notes, now=now, by="overrides.py (desk)")
        else:
            ch = remove_change(base, a.name, now=now, by="overrides.py (desk)")
    except (ie.EntryRefused, nr.ReferenceMissing) as e:
        print(f"REFUSED: {e}")
        return 2
    print(f"{ch['action']} {ch['player']}\n\nbefore:\n{json.dumps(ch['before'], indent=2)}\n\n"
          f"after:\n{json.dumps(ch['after'], indent=2)}")
    for line in ch["shown"]:
        print(f"  {line}")
    if not a.yes:
        try:
            answer = ask("\nWrite it? [y/N] ")
        except EOFError:
            answer = ""
        if str(answer).strip().lower() not in ("y", "yes"):
            print("Not written.")
            return 2
    apply(base, ch)
    print(f"Written ({len(ch['new']['players'])} entries); history: {oh.HISTORY_FILE.as_posix()}.")
    return 0


# =============================================================================
# check
# =============================================================================

def _projected(base: Path) -> dict:
    path = base / "data" / "PLAYERLIST.xlsx"
    if not path.is_file():
        return {}
    import pandas as pd
    frame = pd.read_excel(path)
    return PlayerIndex({str(r["player_name"]): float(r["projectedFPPG"] or 0)
                        for _, r in frame.iterrows()})


def check_lists(base: Path, tags, today: date = None, reference=None) -> dict:
    """{"tagged": [...], "il": [...], "passed": [...], "unknown": [...], "notes": [...]}.
    Reads; never writes."""
    today = today or league_today()
    ref = reference or nr.Reference(base)
    blob = _read(base, OVERRIDES)
    entries = list(blob.get("players") or [])
    covered = PlayerIndex({str(e.get("player_name")): e for e in entries})
    fppg = _projected(base)
    out = {"tagged": [], "il": [], "passed": [], "unknown": [], "notes": []}

    # 1. tagged O / OFS, no override -- rostered first, each by projected FPPG
    for population, src in (("rostered", dict(tags or {})),
                            ("free agent", dict(getattr(tags, "free_agents", None) or {}))):
        rows = [(n, str(t).upper()) for n, t in src.items()
                if str(t).upper() in ("O", "OFS") and covered.canonical(n) is None]
        rows.sort(key=lambda r: (-(fppg.get(r[0]) or 0.0), r[0]))
        out["tagged"] += [f"{n} ({t}, {population}, {fppg.get(n) or 0.0:.1f} FPPG)" for n, t in rows]
    if getattr(tags, "free_agents", None) is None:
        out["notes"].append("free agents' tags were not supplied: list 1 covers rostered players only")

    # 2. in an IL slot, no override
    il_path = base / "data" / "IL_SLOTS.json"
    if not il_path.is_file():
        out["il"].append(f"{il_path} is missing: cannot see who is in an IL slot "
                         "(py scripts/sync_transactions.py --il-only)")
    else:
        il = json.loads(il_path.read_text(encoding="utf-8"))
        for manager, names in sorted((il.get("slots") or {}).items()):
            for n in names:
                if covered.canonical(n) is None:
                    out["il"].append(f"{n} ({manager}'s IL slot, fantasy week {il.get('fantasy_week')})")

    # 3. returns that have passed; 4. names that are nobody
    from modules.absence import parse_return_date
    for e in entries:
        name = str(e.get("player_name"))
        try:
            rd = parse_return_date(e.get("return_date"), name)
        except ValueError as err:
            out["passed"].append(f"{name}: {err}")
            rd = None
        if rd is not None and rd < today:
            out["passed"].append(f"{name} (return_date {rd})")
        if ref.resolve(name) is None:
            out["unknown"].append(ref.unknown_message(name))
    return out


TITLES = (("tagged", "1. Tagged O or OFS with no override (review; a short O is normal)"),
          ("il", "2. In an IL slot with no override (review; a short stay is normal)"),
          ("passed", "3. Return date passed -- candidates to remove"),
          ("unknown", "4. Names that match no NBA player"))


def render_check(lists: dict) -> tuple:
    lines = []
    for key, title in TITLES:
        lines.append(f"{title}: {len(lists[key]) or 'none'}")
        lines += [f"    {x}" for x in lists[key]]
    lines += [f"  note: {n}" for n in lists["notes"]]
    code = 1 if any(lists[k] for k in ("passed", "unknown")) else 0
    return lines, code


def _tags(base: Path, statuses_file: str = None):
    fis = importlib.import_module("modules.fetch_injury_statuses")
    if statuses_file:
        return fis.Tags.from_json(json.loads(Path(statuses_file).read_text(encoding="utf-8")))
    return fis.fetch_injury_statuses(oauth_file=str(base / "oauth2.json"), verbose=False)


def cmd_check(a, base: Path, today: date = None) -> int:
    try:
        lists = check_lists(base, _tags(base, a.statuses), today)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return 2
    lines, code = render_check(lists)
    print("\n".join(lines))
    return code


def cmd_refresh(base: Path) -> int:
    try:
        blob = nr.refresh(base)
    except nr.ReferenceFetchError as e:
        print(f"FAILED: {e}")
        return 2
    counts = ", ".join(f"{k} {len(v['players'])}" for k, v in blob["seasons"].items())
    print(f"Wrote {nr.CACHE} ({counts}; fetched {blob['fetched_at']}).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-path", default=str(PROJECT_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="add (or --replace) one entry")
    add.add_argument("name")
    add.add_argument("--out", required=True, help="first day out, YYYY-MM-DD")
    add.add_argument("--back", help="expected return day, YYYY-MM-DD")
    add.add_argument("--season", action="store_true", help="out for the rest of the season")
    add.add_argument("--notes")
    add.add_argument("--return-notes")
    add.add_argument("--team", help="NBA team code, when it cannot be determined")
    add.add_argument("--replace", action="store_true")
    add.add_argument("--yes", action="store_true", help="write without asking")
    chk = sub.add_parser("check", help="read-only review lists")
    chk.add_argument("--statuses", help="a tags file (fetch_injury_statuses --output) "
                                        "instead of fetching Yahoo")
    sub.add_parser("refresh-reference", help="fetch the NBA player-name reference")
    sr = sub.add_parser("set-return", help="move one entry's return date (only it and its derived fields)")
    sr.add_argument("name")
    sr.add_argument("--back", required=True, help="the new return day, YYYY-MM-DD")
    sr.add_argument("--yes", action="store_true")
    sn = sub.add_parser("set-notes", help="change one entry's notes")
    sn.add_argument("name")
    sn.add_argument("--notes", required=True)
    sn.add_argument("--yes", action="store_true")
    rm = sub.add_parser("remove", help="remove one entry")
    rm.add_argument("name")
    rm.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    base = Path(a.base_path)
    if a.cmd == "add":
        return cmd_add(a, base)
    if a.cmd in ("set-return", "set-notes", "remove"):
        return cmd_edit(a, base)
    if a.cmd == "check":
        return cmd_check(a, base)
    return cmd_refresh(base)


if __name__ == "__main__":
    sys.exit(main())
