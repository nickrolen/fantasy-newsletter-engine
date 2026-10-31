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

EXIT CODES: 0 ok; 1 check found something in 3 or 4; 2 refused / failed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules import injury_entries as ie  # noqa: E402
from modules import nba_reference as nr  # noqa: E402
from modules.data_loader import PlayerIndex, atomic_write_json  # noqa: E402
from modules.league_clock import league_today  # noqa: E402

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

def prepare_add(base: Path, name: str, out: str, back: str = None, season: bool = False,
                team: str = None, notes: str = None, return_notes: str = None,
                replace: bool = False, today: date = None, reference=None) -> tuple:
    """(new file blob, the entry, lines to show). Raises EntryRefused with what
    to do. Writes nothing."""
    today = today or league_today()
    ref = reference or nr.Reference(base)
    if ref.resolve(name) is None:
        raise ie.EntryRefused(ref.unknown_message(name))
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
        raise ie.EntryRefused(f"INJURY_OVERRIDES.json already has an entry for {hit}: pass "
                              "--replace to overwrite it")
    entry, said = ie.compute(name, team, out_d, back_d, season, schedule, games, notes,
                             return_notes)
    entry = ie.ordered(entry)
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


def cmd_add(a, base: Path, today: date = None, ask=input) -> int:
    try:
        new, entry, shown = prepare_add(base, a.name, a.out, a.back, a.season, a.team, a.notes,
                                        a.return_notes, a.replace, today)
    except (ie.EntryRefused, nr.ReferenceMissing) as e:
        print(f"REFUSED: {e}")
        return 2
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
    atomic_write_json(base / OVERRIDES, new)
    print(f"Written ({len(new['players'])} entries, last_updated {new['last_updated']}).")
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
    a = ap.parse_args(argv)
    base = Path(a.base_path)
    if a.cmd == "add":
        return cmd_add(a, base)
    if a.cmd == "check":
        return cmd_check(a, base)
    return cmd_refresh(base)


if __name__ == "__main__":
    sys.exit(main())
