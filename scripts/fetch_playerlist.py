#!/usr/bin/env python3
"""
fetch_playerlist.py -- build data/PLAYERLIST.xlsx from Yahoo.

WHAT THIS REPLACES
------------------
Step 2.5 of the weekly workflow: open Yahoo, sort by projected rest-of-season
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
    CURRENT_SEASON, LEAGUE_KEY, MANAGER_TO_TEAM, normalize_player_name,
)

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


def parse_rows(doc: str, team_names: set) -> list:
    """[{yahoo_id, player_name, nba_team, positions, proj_gp, total_fp, owner}]

    The table is server-rendered HTML, so this reads the markup. Team codes
    and the player id come from structural attributes (the /nba/players/<id>/
    link) rather than from column position, which is the part most likely to
    be reshuffled by a cosmetic change.
    """
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
        numeric = [c for c in cells if re.fullmatch(r"-|[\d,]+\.?\d*", c or "")]
        owner = next((c for c in cells if c in team_names), None)
        out.append({
            "yahoo_id": yahoo_id,
            "player_name": name,
            "nba_team": team_pos.group(1) if team_pos else "",
            "positions": team_pos.group(2) if team_pos else "",
            "proj_gp": numeric[0] if numeric else "",
            "total_fp": numeric[1] if len(numeric) > 1 else "",
            "owner": owner,
        })
    return out


def to_number(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def collect(league_id: str, status: str, limit: int, label: str) -> dict:
    """{yahoo_id: row} for one status filter, paging until it runs dry."""
    found, offset = {}, 0
    while offset < limit:
        try:
            page = parse_rows(fetch_page(league_id, status, offset),
                              set(MANAGER_TO_TEAM.values()))
        except urllib.error.HTTPError as e:
            print(f"    {label}: HTTP {e.code} at offset {offset}")
            break
        except Exception as e:
            print(f"    {label}: {type(e).__name__} at offset {offset}: {e}")
            break
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
    """{normalised name: age} from a PLAYERLIST workbook, or {}."""
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
            out[normalize_player_name(row.get("player_name"))] = int(age)
    return out


def ages_from_basketball_reference(season_end_year: int) -> dict:
    """{normalised name: age} for a COMPLETED season, from basketball-reference.

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
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            doc = response.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    basketball-reference: {type(e).__name__}: {e}")
        return {}

    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", doc, re.S):
        name = re.search(r'data-stat="(?:name_display|player)"[^>]*>(?:<a[^>]*>)?([^<]+)', row)
        age = re.search(r'data-stat="age"[^>]*>(\d+)<', row)
        if name and age:
            out[normalize_player_name(html_lib.unescape(name.group(1)))] = int(age.group(1)) + 1
    print(f"    basketball-reference {season_end_year}: {len(out)} ages "
          "(+1 year for the current season)")
    return out


def seed_ages(rows: list, cached: dict, use_bbref: bool,
              trust_live: bool = True) -> dict:
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
                      reverse=True)
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
    if trust_live:
        by_name.update(_ages_from_spreadsheet(PLAYERLIST))
    if by_name:
        print(f"    spreadsheets on disk: {len(by_name)} ages")

    if use_bbref:
        # The most recent COMPLETED season: this season's pages have no ages
        # until games are played. Walk back two more seasons as well -- a
        # player who missed a whole year to injury (Lillard, Irving and
        # VanVleet all missed 2025-26) has no row in the latest one.
        year = date.today().year if date.today().month >= 7 else date.today().year - 1
        for back, candidate in enumerate((year, year - 1, year - 2)):
            found = ages_from_basketball_reference(candidate)
            for key, age in found.items():
                by_name.setdefault(key, age + back)   # one more year per season back

    # Yahoo abbreviates long names ("N. Alexander-Walker"); basketball-reference
    # spells them out. Index by last name plus first initial so those still join.
    def short_key(name):
        parts = [p for p in re.split(r"\s+", str(name).strip()) if p]
        if len(parts) < 2:
            return None
        return normalize_player_name(parts[0][0] + parts[-1])

    seeded, unmatched = {}, []
    for row in rows:
        if row["yahoo_id"] in cached:
            continue
        name = row["player_name"]
        age = by_name.get(normalize_player_name(name))
        if age is None:
            sk = short_key(name)
            if sk:
                # match against every known name reduced the same way
                for known, known_age in by_name.items():
                    if known.endswith(sk[1:]) and known.startswith(sk[0]):
                        age = known_age
                        break
        if age is None:
            unmatched.append(name)
        else:
            seeded[row["yahoo_id"]] = age
    return seeded


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
    args = ap.parse_args()

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
              "the manual procedure in WEEKLY_WORKFLOW.md Step 2.5.")
        return 1

    merged = dict(pool)
    merged.update(taken)          # a rostered row wins: it carries the owner
    rows = list(merged.values())

    cached = {} if args.refresh_ages else load_ages()
    if args.refresh_ages:
        print("\n  Ages (--refresh-ages: cache ignored, rebuilding from source):")
    else:
        print("\n  Ages:")
    seeded = seed_ages(rows, cached, use_bbref=not args.no_bbref_ages,
                       trust_live=not args.refresh_ages)
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

    missing = [n for n in rostered_names()
               if normalize_player_name(n) not in
               {normalize_player_name(r["player_name"]) for r in records}]
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

    if PLAYERLIST.is_file():
        shutil.copy2(PLAYERLIST, PLAYERLIST.with_suffix(".xlsx.bak"))
    frame[COLUMNS].to_excel(PLAYERLIST, index=False)
    print(f"\n  Wrote {PLAYERLIST.name} ({len(frame)} rows)")

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
