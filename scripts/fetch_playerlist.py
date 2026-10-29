#!/usr/bin/env python3
"""
fetch_playerlist.py -- build data/PLAYERLIST.xlsx from Yahoo.

WHAT THIS REPLACES
------------------
Step 4.75 of the weekly workflow (2.5 until 10-27): open Yahoo, sort by projected rest-of-season
fantasy points, select ~125 rows, paste the mess into an LLM, have it parse
out five fields, compute FPPG, carry ages forward, cross-check the rosters,
and write the spreadsheet. Every week. It is the only manual step left in the
workflow and the one most likely to go wrong quietly.

WHY IT CAN BE AUTOMATED AT ALL
------------------------------
Yahoo's Fantasy API does not expose projections -- stats;type=projected_season,
type=projected_week and type=projected all return HTTP 400, and an unplayed
week returns player_points 0.00. But the WEBSITE renders them, server-side, in
a URL-parameterised table:

    /nba/<league_id>/players?status=<...>&stat1=S_PSR&sort=PTS&count=<n>

    stat1=S_PSR  is the "Remaining Games (proj)" view -- the one the manual
                 step uses. GP and Fan Pts on that view are exactly the two
                 numbers the spreadsheet wants.

and that page needs no login, because the league is publicly visible. Verified
from a machine with no Yahoo cookies at all: the table renders with our team
names in the roster column and Fan Pts already scored by OUR league's
settings. The raw stat projections are Yahoo's global NBA numbers; the Fan
Pts column is those numbers run through this league's eleven categories.

    IF THE LEAGUE IS EVER MADE PRIVATE, THIS BREAKS. The symptom will be a
    table with no player rows rather than an error. The fallback is the
    manual procedure, which WEEKLY_WORKFLOW.md keeps documented for exactly
    that reason.

ROSTER COVERAGE
---------------
Two passes, not one. status=T ("All Taken Players") returns every rostered
player regardless of rank, so a season-long injury who has fallen out of the
top 150 -- the Tatum/Haliburton case the manual instructions call out by name
-- cannot be missed. status=ALL then supplies the free-agent pool for the
waiver and rumour-mill sections.

AGES
----
Not on the page, and not in the API either (player_details has no birth_year
or age field). They live in config/PLAYER_AGES.json, keyed by Yahoo's player
id rather than by name so a spelling change cannot orphan an entry. A player
with no cached age is reported, not guessed; fill them in once and they carry
forever, including across the season reset -- which the old carry-forward
from last week's spreadsheet did not.

USAGE
    py scripts/fetch_playerlist.py                 # preview, writes nothing
    py scripts/fetch_playerlist.py --execute
    py scripts/fetch_playerlist.py --execute --limit 200

EXIT CODES
    0 = wrote it (or a clean preview)
    1 = refused; the existing PLAYERLIST.xlsx was not touched
"""

import argparse
import html as html_lib
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import (  # noqa: E402
    CURRENT_SEASON, LEAGUE_KEY, MANAGER_TO_TEAM, PlayerIndex, normalize_player_name,
)
from modules import playerlist_freshness  # noqa: E402
from modules import projection_overrides  # noqa: E402

PLAYERLIST = PROJECT_ROOT / "data" / "PLAYERLIST.xlsx"
AGES = PROJECT_ROOT / "config" / "PLAYER_AGES.json"
ROSTERS = PROJECT_ROOT / "config" / "ROSTERS.json"

COLUMNS = ["player_name", "player_nba_team", "player_position(s)",
           "player_total_proj_FP", "player_proj_GP", "projectedFPPG", "age"]

BASE = "https://basketball.fantasysports.yahoo.com/nba/{league_id}/players"
STAT_VIEW = "S_PSR"      # "Remaining Games (proj)"
PAGE_SIZE = 25
REQUEST_PAUSE = 1.0      # be a polite guest on someone else's website

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class TableFormatError(RuntimeError):
    """Yahoo's players table no longer looks the way this parser expects."""


class AgeFetchError(RuntimeError):
    """A basketball-reference age page could not be fetched or parsed. Raised,
    never {}: a failed fetch must not quietly leave stale or missing ages
    (10-29, as modules/nba_reference.py does for names)."""


# The two columns the spreadsheet is built from, as Yahoo labels them.
# Matched on a squashed form of the header text so "GP*" survives its
# asterisk and "Current\ue002" survives the private-use sort glyph Yahoo
# appends to whichever column is sorted.
#
# Deliberately narrow: "PTS" is a DIFFERENT column -- points scored, ten
# places to the right of Fan Pts -- and must never match here.
GP_LABELS = {"GP", "GAMES", "GAMESPLAYED", "PROJGP"}
FP_LABELS = {"FANPTS", "FANPOINTS", "FANTASYPTS", "FANTASYPOINTS", "FPTS"}


def league_id_from_key(league_key: str) -> str:
    """"478.l.16778" -> "16778"."""
    match = re.search(r"\.l\.(\d+)", str(league_key or ""))
    return match.group(1) if match else ""


def fetch_page(league_id: str, status: str, offset: int) -> str:
    url = (f"{BASE.format(league_id=league_id)}?status={status}&pos=P"
           f"&cut_type=33&stat1={STAT_VIEW}&myteam=0&sort=PTS&sdir=1"
           f"&count={offset}")
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", "replace")


def _squash(text) -> str:
    """Header text down to comparable letters: "Fan Pts" -> "FANPTS"."""
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def find_columns(doc: str):
    """{"gp": i, "fp": j} from the table's header row, or None.

    Yahoo renders a real <th> row whose cells line up index-for-index with
    each player's <td> cells -- 23 and 23, with GP at 5 and Fan Pts at 6 as
    of this writing. Letting the labels carry the positions is what makes a
    reshuffle a non-event: Yahoo can move those columns, or insert and
    remove columns to their left, and the numbers still land in the right
    fields. The alternative -- taking the first two numeric cells -- reads
    correctly today only because the two rank columns happen to sit just
    behind Fan Pts instead of just ahead of GP.
    """
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, re.S):
        heads = [_squash(html_lib.unescape(re.sub(r"<[^>]+>", "", cell)))
                 for cell in re.findall(r"<th[^>]*>(.*?)</th>", row, re.S)]
        if not heads:
            continue
        gp = next((i for i, h in enumerate(heads) if h in GP_LABELS), None)
        fp = next((i for i, h in enumerate(heads) if h in FP_LABELS), None)
        if gp is not None and fp is not None:
            return {"gp": gp, "fp": fp}
    return None


def parse_rows(doc: str, team_names: set, columns=None) -> list:
    """[{yahoo_id, player_name, nba_team, positions, proj_gp, total_fp, owner}]

    The table is server-rendered HTML, so this reads the markup. Player id
    and name come from the /nba/players/<id>/ link, team and positions from
    the "DEN - C" text pattern, and the owner from matching a known team
    name -- all structural or content-based, none of them sensitive to
    column order.

    GP and Fan Pts are the two values that live in bare cells, so they are
    located by their header labels via find_columns().

    columns=None means "find the header in doc, and if there is none, fall
    back to the first two numeric cells". That fallback is for parsing a
    bare <tr> fragment in a test. The pipeline never relies on it: collect()
    demands a header and refuses without one, because on a real page a
    missing header means the table changed shape, and guessing at that point
    is how a wrong spreadsheet gets written quietly.
    """
    if columns is None:
        columns = find_columns(doc)
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, re.S):
        link = re.search(r"/nba/players/(\d+)[/\"][^>]*>([^<]+)</a>", row)
        if not link:
            continue
        yahoo_id, name = link.group(1), html_lib.unescape(link.group(2)).strip()
        flat = re.sub(r"<[^>]+>", " ", row)
        team_pos = re.search(r"\b([A-Z]{2,3})\s*-\s*([A-Z,]+)", flat)
        cells = [html_lib.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if columns:
            proj_gp = _cell(cells, columns["gp"])
            total_fp = _cell(cells, columns["fp"])
        else:
            numeric = [c for c in cells if re.fullmatch(r"-|[\d,]+\.?\d*", c or "")]
            proj_gp = numeric[0] if numeric else ""
            total_fp = numeric[1] if len(numeric) > 1 else ""
        owner = next((c for c in cells if c in team_names), None)
        out.append({
            "yahoo_id": yahoo_id,
            "player_name": name,
            "nba_team": team_pos.group(1) if team_pos else "",
            "positions": team_pos.group(2) if team_pos else "",
            "proj_gp": proj_gp,
            "total_fp": total_fp,
            "owner": owner,
        })
    return out


def _cell(cells: list, index: int) -> str:
    """cells[index], or "" when the row is shorter than the header."""
    return cells[index] if 0 <= index < len(cells) else ""


def to_number(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def collect(league_id: str, status: str, limit: int, label: str) -> dict:
    """{yahoo_id: row} for one status filter, paging until it runs dry."""
    found, offset, columns = {}, 0, None
    while offset < limit:
        try:
            doc = fetch_page(league_id, status, offset)
        except urllib.error.HTTPError as e:
            print(f"    {label}: HTTP {e.code} at offset {offset}")
            break
        except Exception as e:
            print(f"    {label}: {type(e).__name__} at offset {offset}: {e}")
            break
        if columns is None:
            # Located once per run and reused for every page. Absent means
            # the table is not the table this script was written against,
            # and the only safe move is to stop: a wrong PLAYERLIST is worse
            # than no PLAYERLIST, because the simulators will run on it.
            columns = find_columns(doc)
            if columns is None:
                raise TableFormatError(
                    "Yahoo's players table has no recognisable 'GP' and "
                    "'Fan Pts' columns, so its numbers cannot be trusted. "
                    "PLAYERLIST was NOT modified.\n"
                    "  Use the manual procedure in WEEKLY_WORKFLOW.md for "
                    "this week, then update GP_LABELS / FP_LABELS or "
                    "find_columns() in scripts/fetch_playerlist.py.")
            print(f"    columns: GP at {columns['gp']}, "
                  f"Fan Pts at {columns['fp']}")
        page = parse_rows(doc, set(MANAGER_TO_TEAM.values()), columns)
        fresh = [r for r in page if r["yahoo_id"] not in found]
        for r in fresh:
            found[r["yahoo_id"]] = r
        if not page:
            break
        offset += PAGE_SIZE
        if not fresh:
            break
        time.sleep(REQUEST_PAUSE)
    print(f"    {label}: {len(found)} players")
    return found


def load_ages() -> dict:
    if not AGES.is_file():
        return {}
    try:
        return json.loads(AGES.read_text(encoding="utf-8")).get("ages", {})
    except (OSError, json.JSONDecodeError):
        return {}


def _ages_from_spreadsheet(path: Path) -> dict:
    """{player name: age} from a PLAYERLIST workbook, or {}. Names as written;
    seed_ages joins through PlayerIndex."""
    if not path.is_file():
        return {}
    try:
        frame = pd.read_excel(path)
    except Exception:
        return {}
    if "age" not in frame.columns or frame.empty:
        return {}
    out = {}
    for _, row in frame.iterrows():
        age = row.get("age")
        if pd.notna(age):
            out[str(row.get("player_name"))] = int(age)
    return out


def ages_from_basketball_reference(season_end_year: int, add: int = 1, fetch=None) -> dict:
    """{player name: age + add} from basketball-reference's per-game page.

    add=1 for a COMPLETED season (its ages are a year old); add=0 for THIS
    season's page, which carries an age for everyone who has played --
    rookies included (a completed season's page cannot age a rookie).
    RAISES AgeFetchError on a failed request or a page with no ages: it used
    to print and return {}, which left ages stale or missing without a word.

    Yahoo does not publish ages on the projections page and the Fantasy API
    has no birth_year field, so they have to come from somewhere. The current
    season's b-ref pages carry no ages until games are played, but the last
    completed season's do -- roughly a thousand players. Add a year and you
    have this season's age for everyone except genuine rookies.

    A note on conventions: b-ref reports age on February 1 of the season,
    while the hand-maintained spreadsheets used age at the start of it, so
    the two sources can disagree by a year for anyone with a birthday in
    between. The spreadsheet wins where both exist, for continuity.
    Keepability buckets ages; it does not need a birthday.
    """
    url = (f"https://www.basketball-reference.com/leagues/"
           f"NBA_{season_end_year}_per_game.html")
    try:
        if fetch is not None:
            doc = fetch(url)
        else:
            request = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(request, timeout=45) as response:
                doc = response.read().decode("utf-8", "replace")
    except Exception as e:
        raise AgeFetchError(f"{url}: {type(e).__name__}: {e}. Ages were not changed; "
                            "re-run, or pass --no-bbref-ages to skip the lookup knowingly.") from e

    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, re.S):
        name = re.search(r'data-stat="(?:name_display|player)"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
        age = re.search(r'data-stat="age"[^>]*>(\d+)<', row)
        if name and age:
            # a traded player has a combined row and one per team: first wins
            out.setdefault(html_lib.unescape(name.group(1)).strip(), int(age.group(1)) + add)
    if not out:
        raise AgeFetchError(f"{url} parsed to no ages: the page changed. Ages were not changed.")
    print(f"    basketball-reference {season_end_year}: {len(out)} ages"
          + (f" (+{add} year for the current season)" if add else " (this season)"))
    return out


def seed_ages(rows: list, cached: dict, use_bbref: bool,
              trust_live: bool = True, use_spreadsheets: bool = True) -> dict:
    """Fill ages for players the id-keyed cache does not know yet.

    In order of preference: the spreadsheet on disk, then the most recent
    archived one (so the season reset does not lose them), then
    basketball-reference. Joined by normalised name -- once -- after which
    the Yahoo id carries the value.
    """
    # An archived spreadsheet holds ages for ITS season, so they have to be
    # aged forward. Taking them at face value put Jokic at 30 and Doncic at 26
    # in 2026-27 -- last season's numbers, everyone a year young, which feeds
    # straight into keepability's age curve.
    def season_start(text):
        found = re.search(r"(\d{4})-\d{2}", str(text))
        return int(found.group(1)) if found else None

    current_start = season_start(CURRENT_SEASON) or date.today().year

    by_name = {}
    archives = sorted((PROJECT_ROOT / "archive").glob("*/data/PLAYERLIST.xlsx"),
                      reverse=True) if use_spreadsheets else []
    for source in archives:
        start = season_start(source.parent.parent.name)
        if start is None:
            continue
        elapsed = max(0, current_start - start)
        for key, age in _ages_from_spreadsheet(source).items():
            by_name.setdefault(key, age + elapsed)
    # The live file is this season's already, so it needs no adjustment and
    # overrides anything derived -- EXCEPT during a refresh, when it is this
    # script's own previous output and may be exactly what we are rebuilding.
    if trust_live and use_spreadsheets:
        by_name.update(_ages_from_spreadsheet(PLAYERLIST))
    if by_name:
        print(f"    spreadsheets on disk: {len(by_name)} ages")

    if use_bbref:
        # THIS season's page first: it carries an age for everyone who has
        # played, rookies included, and needs no adjustment. Then the most
        # recent COMPLETED season, and two more back -- a player who missed a
        # whole year to injury (Lillard, Irving and VanVleet all missed
        # 2025-26) has no row in the latest one.
        year = date.today().year if date.today().month >= 7 else date.today().year - 1
        for key, age in ages_from_basketball_reference(year + 1, add=0).items():
            by_name.setdefault(key, age)
        for back, candidate in enumerate((year, year - 1, year - 2)):
            found = ages_from_basketball_reference(candidate)
            for key, age in found.items():
                by_name.setdefault(key, age + back)   # one more year per season back

    # One join, through data_loader.PlayerIndex: accents, suffixes and Yahoo's
    # initials ("N. Alexander-Walker"), and an ambiguous match is NO match.
    # The hand-rolled fallback this replaced reduced a name to its first
    # initial plus its LAST token -- "Darius Acuff Jr." became "d" + "jr" --
    # and took the first known name that fit: Derrick Jones Jr., 29. The 2026
    # rookie carried that age from 2026-09-25 to 10-29.
    index = PlayerIndex(by_name)
    seeded, unmatched = {}, []
    for row in rows:
        if row["yahoo_id"] in cached:
            continue
        name = row["player_name"]
        age = index.get(name)
        if age is None:
            unmatched.append(name)
        else:
            seeded[row["yahoo_id"]] = int(age)
    return seeded


def recheck_ages(rows: list, execute: bool = False, cached: dict = None,
                 derive=None, write=None, players: list = None) -> int:
    """Compare every cached age with what its sources say now. Exit 0 when
    nothing is more than a year off (or it was fixed with --execute), 1 when
    something is and was not fixed.

    players: NAMED players only, derived from basketball-reference alone (no
    spreadsheets -- the source being corrected), and replaced on ANY
    difference: naming him is the decision the one-year rule leaves to a
    person. A named player who matches no fetched row, or has no source,
    refuses."""
    cached = dict(load_ages() if cached is None else cached)
    if players:
        index = PlayerIndex({r["player_name"]: r for r in rows})
        picked = []
        for name in players:
            row = index.get(name)
            if row is None:
                print(f"\n  REFUSED: {name!r} matches no player in this fetch.")
                return 1
            picked.append(row)
        rows = picked
        print(f"\n  Re-deriving {', '.join(r['player_name'] for r in rows)} from "
              "basketball-reference only (not the spreadsheets, the live file or the cache):")
        derive = derive or (lambda: seed_ages(rows, {}, use_bbref=True, trust_live=False,
                                               use_spreadsheets=False))
    else:
        print("\n  Re-deriving ages from source (archived spreadsheets, basketball-reference;"
              " not the live file, not the cache):")
        derive = derive or (lambda: seed_ages(rows, {}, use_bbref=True, trust_live=False))
    try:
        fresh = derive()
    except AgeFetchError as e:
        print(f"\n  REFUSED: {e}")
        return 1
    names = {r["yahoo_id"]: (r["player_name"], bool(r.get("owner"))) for r in rows}
    off, near, nosrc = [], [], []
    for pid, (name, rostered) in sorted(names.items(), key=lambda kv: kv[1]):
        if pid not in cached and not players:
            continue
        if pid not in fresh:
            nosrc.append(name)
            continue
        d = int(cached.get(pid, fresh[pid])) - int(fresh[pid]) if pid in cached else None
        if players:
            if d != 0:
                off.append((pid, name, rostered, cached.get(pid), fresh[pid]))
            continue
        if abs(d) > 1:
            off.append((pid, name, rostered, cached[pid], fresh[pid]))
        elif d and rostered:
            near.append((name, cached[pid], fresh[pid]))
    print(f"\n  {len(off)} cached age(s) " + ("that differ from their source:" if players
          else "more than a year from their source:"))
    for pid, name, rostered, was, now in off:
        print(f"    {name} (id {pid}{', rostered' if rostered else ''}): cached {was}, source {now}")
    if near:
        print(f"\n  {len(near)} rostered age(s) one year from their source (left alone -- "
              "the two age conventions can differ by one):")
        for name, was, now in near:
            print(f"    {name}: cached {was}, source {now}")
    if nosrc:
        print(f"\n  {len(nosrc)} cached age(s) with no source to check against: "
              + ", ".join(nosrc[:10]) + (" ..." if len(nosrc) > 10 else ""))
        if players:
            print("  REFUSED: a named player needs a source.")
            return 1
    if not off:
        return 0
    if not execute:
        print("\n  [DRY-RUN] Re-run with --recheck-ages --execute to replace them.")
        return 1
    for pid, _name, _r, _was, now in off:
        cached[pid] = int(now)
    (write or _write_ages)(cached)
    print(f"\n  Replaced {len(off)} age(s) in {AGES.name}. PLAYERLIST carries them from the "
          "next fetch (Step 4.75).")
    return 0


def _write_ages(cached: dict) -> None:
    blob = json.loads(AGES.read_text(encoding="utf-8")) if AGES.is_file() else {}
    blob["ages"] = dict(sorted(cached.items(), key=lambda kv: int(kv[0])))
    blob["_updated"] = date.today().isoformat()
    AGES.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")


def rostered_names() -> set:
    if not ROSTERS.is_file():
        return set()
    try:
        blob = json.loads(ROSTERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    rosters = blob.get("rosters", blob)
    names = set()
    for players in rosters.values():
        if isinstance(players, list):
            names.update(players)
    return names


def main():
    ap = argparse.ArgumentParser(
        description="Build data/PLAYERLIST.xlsx from Yahoo's public player list.")
    ap.add_argument("--execute", action="store_true",
                    help="write the file (default: preview)")
    ap.add_argument("--limit", type=int, default=175,
                    help="how deep to page the available-player pool (default 175)")
    ap.add_argument("--league-key", default=None, help="override the league key")
    ap.add_argument("--refresh-ages", action="store_true",
                    help="rebuild every age from source instead of trusting "
                         "the cache. Use at the start of a season -- cached "
                         "ages are a year stale by then.")
    ap.add_argument("--no-bbref-ages", action="store_true",
                    help="do not consult basketball-reference for missing ages")
    ap.add_argument("--recheck-ages", action="store_true",
                    help="re-derive every cached age from its sources (the archived "
                         "spreadsheets and basketball-reference -- never the live file or "
                         "the cache itself) and report each that differs. With --execute, "
                         "replace the ones more than a year off in config/PLAYER_AGES.json "
                         "ONLY; PLAYERLIST is not written. A one-year difference is left "
                         "alone: the spreadsheets' age-at-season-start and "
                         "basketball-reference's age-on-February-1 can differ by one.")
    ap.add_argument("--player", action="append", default=None, metavar="NAME",
                    help="with --recheck-ages: re-derive only this player (repeatable), from "
                         "basketball-reference alone -- this season's page, else the last "
                         "season he played plus the years since -- skipping the spreadsheets, "
                         "and replace his cached age on ANY difference. For a spreadsheet age "
                         "that is one year wrong (Kon Knueppel, 10-29).")
    ap.add_argument("--out", default=None,
                    help="write the workbook here instead of data/PLAYERLIST.xlsx "
                         "(no .bak, and the age cache is left alone). For "
                         "checking a fetch without replacing the live file.")
    args = ap.parse_args()
    target = Path(args.out) if args.out else PLAYERLIST

    league_id = league_id_from_key(args.league_key or LEAGUE_KEY)
    if not league_id:
        print("\n  REFUSED: no league id. yahoo.current_league_key is empty and "
              "no --league-key was given.")
        return 1

    print("=" * 66)
    print(f"  FETCH PLAYERLIST -- Yahoo league {league_id}")
    print("=" * 66)
    print(f"\n  stat view: {STAT_VIEW} (Remaining Games, projected)")

    taken = collect(league_id, "T", 200, "rostered (status=T)")
    pool = collect(league_id, "ALL", args.limit, "pool (status=ALL)")
    if not taken and not pool:
        print("\n  REFUSED: no player rows parsed at all. Either the league was "
              "made private, or Yahoo changed the players table. Fall back to "
              "the manual procedure in WEEKLY_WORKFLOW.md Step 4.75.")
        return 1

    # Every rostered row must name a team config knows. A miss means a manager
    # renamed his team in Yahoo (Benton, "Smaxey" -> "Kevin Quran't", found
    # 10-12) and every ingest script that maps team -> manager will refuse.
    orphans = sorted({r["player_name"] for r in taken.values() if not r["owner"]})
    if orphans:
        print(f"\n  WARNING: {len(orphans)} rostered player(s) on a team name "
              f"that config manager_to_team does not know: {orphans[:5]}"
              f"{' ...' if len(orphans) > 5 else ''}\n  Update manager_to_team "
              f"in config/league_config.json before syncing lineups.")

    merged = dict(pool)
    merged.update(taken)          # a rostered row wins: it carries the owner
    rows = list(merged.values())

    if args.player and not args.recheck_ages:
        print("\n  REFUSED: --player goes with --recheck-ages.")
        return 1
    if args.recheck_ages:
        return recheck_ages(rows, execute=args.execute, players=args.player)

    cached = {} if args.refresh_ages else load_ages()
    if args.refresh_ages:
        print("\n  Ages (--refresh-ages: cache ignored, rebuilding from source):")
    else:
        print("\n  Ages:")
    try:
        seeded = seed_ages(rows, cached, use_bbref=not args.no_bbref_ages,
                           trust_live=not args.refresh_ages)
    except AgeFetchError as e:
        print(f"\n  REFUSED: {e}\n  PLAYERLIST and {AGES.name} were NOT modified.")
        return 1
    if seeded:
        print(f"    seeded {len(seeded)} new age(s)")
        cached.update(seeded)

    records, bad, ageless = [], [], []
    for r in rows:
        gp, fp = to_number(r["proj_gp"]), to_number(r["total_fp"])
        if gp is None or fp is None:
            bad.append(r["player_name"])
            continue
        # Derived here, never parsed. The manual step had an LLM doing this
        # division, which is an error class with no upside.
        fppg = round(fp / gp, 2) if gp else 0.0
        age = cached.get(r["yahoo_id"])
        if age is None:
            ageless.append(r["player_name"])
        records.append({
            "player_name": r["player_name"],
            "player_nba_team": r["nba_team"],
            "player_position(s)": r["positions"],
            "player_total_proj_FP": fp,
            "player_proj_GP": gp,
            "projectedFPPG": fppg,
            "age": age,
            "_yahoo_id": r["yahoo_id"],
            "_owner": r["owner"],
        })

    # Patches on rows Yahoo has wrong upstream (config/PROJECTION_OVERRIDES.json).
    # Applied here, after parsing and before anything is written, so a
    # refetch cannot silently undo them; what Yahoo actually said goes into
    # the stamp, so the file still records the upstream row.
    entries = projection_overrides.load(PROJECT_ROOT / "config" / "PROJECTION_OVERRIDES.json")
    applied, unapplied = projection_overrides.apply(records, entries)
    if entries:
        print(f"\n  Projection overrides ({len(applied)} applied, {len(unapplied)} not):")
        for a in applied:
            y, n = a["yahoo"], a["now"]
            flag = "" if a["replaces_matches"] else "   <-- Yahoo's row has CHANGED since this was written"
            print(f"    {a['player_name']}: Yahoo {y['player_proj_GP']:g} GP / {y['projectedFPPG']:.2f} FPPG"
                  f" -> {n['player_proj_GP']:g} GP / {n['projectedFPPG']:.2f} FPPG"
                  f" (review by {a['review_by']}){flag}")
        for u in unapplied:
            print(f"    NOT APPLIED -- {u['player_name']}: {u['why']}")

    records.sort(key=lambda r: -r["player_total_proj_FP"])
    frame = pd.DataFrame(records)

    print(f"\n  {len(records)} players "
          f"({sum(1 for r in records if r['_owner'])} rostered, "
          f"{sum(1 for r in records if not r['_owner'])} available)")
    if not frame.empty:
        print(f"  FPPG range: {frame['projectedFPPG'].min():.1f} - "
              f"{frame['projectedFPPG'].max():.1f}")
        top = frame.iloc[0]
        print(f"  top: {top['player_name']} -- {top['player_proj_GP']:.0f} GP, "
              f"{top['player_total_proj_FP']:,.2f} FP, "
              f"{top['projectedFPPG']:.2f} FPPG")

    if bad:
        print(f"\n  {len(bad)} row(s) with unreadable GP/FP, dropped: {bad[:5]}")

    # The same resolver the simulators use. Yahoo's roster endpoint and its
    # pool endpoint spell some players differently in the same fetch ("Shai
    # Gilgeous-Alexander" / "S. Gilgeous-Alexander"); plain normalising calls
    # that a missing player.
    fetched = PlayerIndex({r["player_name"]: 1 for r in records})
    missing = [n for n in rostered_names() if n not in fetched]
    if missing:
        print(f"\n  ROSTERED BUT MISSING ({len(missing)}): {missing}")
        print("  These would get a 0.0 FPPG projection in every simulation.")

    if ageless:
        print(f"\n  {len(ageless)} player(s) with no cached age:")
        for n in ageless[:12]:
            print(f"    - {n}")
        if len(ageless) > 12:
            print(f"    ... and {len(ageless) - 12} more")
        print(f"  Add them to {AGES.name} (keyed by Yahoo player id); the file "
              "shows the ids. Missing ages default to 27 in keepability.")

    if not args.execute:
        print("\n  [DRY-RUN] Nothing written. Re-run with --execute.")
        return 0

    if target == PLAYERLIST and PLAYERLIST.is_file():
        shutil.copy2(PLAYERLIST, PLAYERLIST.with_suffix(".xlsx.bak"))
    # The stamp (a "_fetch" sheet) is what tells check_playerlist this file was
    # fetched, and when, instead of inferring it from whether the numbers moved.
    st = playerlist_freshness.write(
        frame[COLUMNS], target, source=f"yahoo:{league_id}",
        extra={projection_overrides.STAMP_KEY:
               projection_overrides.stamp_value(applied, unapplied)})
    print(f"\n  Wrote {target} ({len(frame)} rows), fetched_at {st['fetched_at']}")
    if target != PLAYERLIST:
        print(f"\n  --out: data/PLAYERLIST.xlsx and {AGES.name} were not touched.")
        print(f"  Check it: py scripts/check_playerlist.py --file {target}")
        return 0

    payload = {
        "_comment": ("Player ages, keyed by Yahoo NBA player id. Ages are not "
                     "on the projections page and not in the Fantasy API, so "
                     "they are cached here. Keyed by id rather than name so a "
                     "spelling change cannot orphan an entry. Survives the "
                     "season reset."),
        "_updated": date.today().isoformat(),
        "ages": dict(sorted(cached.items(), key=lambda kv: int(kv[0]))),
        "_needs_age": {r["_yahoo_id"]: r["player_name"]
                       for r in records if r["age"] is None},
    }
    AGES.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"  Wrote {AGES.name} ({len(cached)} cached, "
          f"{len(payload['_needs_age'])} needing a lookup)")
    print("\n  Next: py scripts/check_playerlist.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
