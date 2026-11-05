#!/usr/bin/env python3
"""
fetch_nba_schedule.py

Fetch the NBA schedule for a given season and save a trimmed version
containing only the data needed for fantasy projections.

Usage:
    python scripts/fetch_nba_schedule.py --season 2025-26
    python scripts/fetch_nba_schedule.py --season 2025-26 --output data/nba_schedule.json

The script fetches from the NBA's official schedule API and trims the response
from ~7MB to ~120KB by keeping only:
- Game date
- Home team abbreviation  
- Away team abbreviation

SOURCES
    nba    cdn.nba.com's scheduleLeagueV2.json. The original source, and the
           one to prefer when it works.
    bbref  basketball-reference.com month pages. Added Sep 2026 because
           cdn.nba.com began returning HTTP 403 (an Akamai block) to
           everything we could point at it -- the cloud container, the local
           VM, and an ordinary browser on a home connection. bbref answers
           normally from all three.
    auto   try nba, fall back to bbref. The default.

TIP TIMES (step 1a, 2026-10-31; claude/SELF_RUNNING_DESIGN.md s.4.1)
    Every game keeps its tip as a UTC instant, "tip_utc": "2026-11-03T00:30:00Z".
    bbref's "Start (ET)" ("7:30p") is converted through the zone database
    (America/New_York), never a fixed offset; nba's gameDateTimeUTC is used as
    is. A game with no time yet (TBD, postponed, an unset Cup knockout game)
    is stored with "tip_utc": null -- never guessed. Every tip must fall, on
    the league's clock (modules/league_clock), on the game's listed date, or
    the fetch raises naming the game. Only modules/price_lock.py reads tip_utc:
    nothing that prices a line or a season does (tests/test_price_lock.py).

    --tips-only adds the tips to the existing file and changes nothing else:
    the refetched games must match it exactly (date, home, away), or the file
    is left alone and the differences are printed (exit 2).

For manual download:
    The NBA schedule can be downloaded from:
    https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json
    
    Then run with --input to trim an existing file:
    python scripts/fetch_nba_schedule.py --input raw_schedule.json --output data/nba_schedule.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import (  # noqa: E402
    CURRENT_SEASON, NBA_SCHEDULE_FILE,
)
from modules.schedule_freshness import (  # noqa: E402
    changes_within, diff_schedules, shrink_problem, stamp,
)

# Where the schedule goes is a config question, not a thing to retype.
# It used to be three different answers: this script defaulted to
# data/nba_schedule.json, WEEKLY_WORKFLOW told you to write
# data/nba_schedule_2025-26.json, and league_config read
# data/nba_schedule_2026-27.json. Only the third was ever loaded, so
# following the documented command refreshed a file nothing reads and
# left the live one frozen -- silently, since both files exist.
DEFAULT_OUTPUT = Path(NBA_SCHEDULE_FILE or "data/nba_schedule.json")
# Task 33 (11-05): with no --output, the fetch goes through modules/
# nba_schedule.refetch -- the nightly run's own path -- and writes the
# REFETCHED COPY (data/nba_schedule_<season>.refetched.json, league state:
# push it with python scripts\state.py push). The engine's file above is the
# committed seed, read only while no copy exists; writing it while a copy
# exists refuses (the copy would hide it).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


NBA_SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"

BBREF_URL = "https://www.basketball-reference.com/leagues/NBA_{year}_games-{month}.html"
BBREF_MONTHS = ["october", "november", "december", "january", "february",
                "march", "april", "may", "june"]

# basketball-reference uses its own abbreviations for three franchises.
# Everything else already matches the NBA's tricodes, which are what
# PLAYERLOG and the projections key off.
BBREF_TO_NBA = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX"}

BBREF_ZONE = "America/New_York"   # bbref's "Start (ET)"


class TipCheckFailed(ValueError):
    """A tip time that does not fit its game: unparseable, or not on the
    game's listed date on the league's clock."""


def bbref_tip_utc(day, text):
    """bbref's Start (ET) text ("7:30p", "10:00p", "12:00p") on `day` as a UTC
    instant "YYYY-MM-DDTHH:MM:SSZ", through the zone database. Empty or TBD
    -> None (no time yet). Anything else raises: a format change must not
    turn into a quietly wrong time."""
    import re as _re
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    raw = _re.sub(r"<[^>]+>", "", str(text or "")).strip()
    if raw == "" or raw.upper() in ("TBD", "TBA", "PPD", "POSTPONED"):
        return None
    m = _re.fullmatch(r"(\d{1,2}):(\d{2})\s*([ap])m?", raw, _re.I)
    if not m:
        raise TipCheckFailed(f"{day}: unrecognised Start (ET) {raw!r}")
    hour, minute, ap = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if not (1 <= hour <= 12 and 0 <= minute < 60):
        raise TipCheckFailed(f"{day}: unrecognised Start (ET) {raw!r}")
    hour = (hour % 12) + (12 if ap == "p" else 0)
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(BBREF_ZONE))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tip_league_date(tip_utc):
    """The league day (modules/league_clock) a tip instant falls on."""
    from datetime import datetime, timezone
    from modules.league_clock import league_date_of_timestamp
    t = datetime.strptime(tip_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return league_date_of_timestamp(t.timestamp())


def check_tips(games) -> None:
    """Every game's tip, on the league's clock, falls on its listed date.
    Raises naming each game that does not."""
    bad = []
    for g in games:
        tip = g.get("tip_utc")
        if tip is None:
            continue
        on = tip_league_date(tip)
        if on.isoformat() != str(g["date"])[:10]:
            bad.append(f"{g['away']} @ {g['home']} listed {str(g['date'])[:10]}, tip {tip} "
                       f"is {on} on the league's clock")
    if bad:
        raise TipCheckFailed("tip times that do not fall on their game's date:\n  "
                             + "\n  ".join(bad))


def add_tips_only(old: dict, new: dict):
    """(old's file with each game's tip_utc taken from `new`, problems).
    `problems` lists every game that is not in both files with the same date,
    home and away -- if there is any, nothing may be written."""
    key = lambda g: (str(g.get("date"))[:10], g.get("home"), g.get("away"))
    new_tips = {}
    for g in new.get("games", []):
        new_tips[key(g)] = g.get("tip_utc")
    old_keys = [key(g) for g in old.get("games", [])]
    problems = []
    if len(set(old_keys)) != len(old_keys):
        problems.append("the existing file lists a game twice")
    for k in old_keys:
        if k not in new_tips:
            problems.append(f"in the file, not in the refetch: {k[0]} {k[2]} @ {k[1]}")
    for k in sorted(set(new_tips) - set(old_keys)):
        problems.append(f"in the refetch, not in the file: {k[0]} {k[2]} @ {k[1]}")
    merged = dict(old)
    merged["games"] = [{**g, "tip_utc": new_tips.get(key(g))} for g in old.get("games", [])]
    return merged, problems


BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_nba_schedule() -> dict:
    """Fetch the full NBA schedule from the official API."""
    if not HAS_REQUESTS:
        raise RuntimeError("the 'requests' library is required for the nba source")
    
    print(f"Fetching schedule from {NBA_SCHEDULE_URL}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    
    response = requests.get(NBA_SCHEDULE_URL, headers=headers, timeout=30)
    response.raise_for_status()
    
    return response.json()


def _season_end_year(season: str) -> int:
    """"2026-27" -> 2027. basketball-reference files a season under its end year."""
    import re as _re
    match = _re.fullmatch(r"(\d{4})-(\d{2})", str(season or "").strip())
    if not match:
        raise SystemExit(
            f"--season must look like 2026-27 to use the bbref source, got {season!r}")
    return int(match.group(1)) + 1


def _parse_bbref_month(html: str, year: int) -> list:
    """[{date, home, away}] from one basketball-reference month page.

    Team codes come out of the /teams/XXX/ links rather than the visible
    names, so a franchise rename or relocation does not silently drop games.
    """
    import re as _re
    from datetime import datetime

    table = _re.search(r'<table[^>]+id="schedule".*?</table>', html, _re.S)
    if not table:
        return []

    def cell(row, stat):
        found = _re.search(r'data-stat="%s"[^>]*>(.*?)</t[hd]>' % stat, row, _re.S)
        return found.group(1) if found else None

    def tricode(cell_html):
        found = _re.search(r"/teams/([A-Z]{3})/", cell_html or "")
        if not found:
            return None
        return BBREF_TO_NBA.get(found.group(1), found.group(1))

    games = []
    if 'data-stat="game_start_time"' not in table.group(0):
        raise TipCheckFailed("a basketball-reference month page has no Start (ET) column "
                             "(data-stat=game_start_time): the markup changed")
    for row in _re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(0), _re.S):
        raw_date = cell(row, "date_game")
        away = tricode(cell(row, "visitor_team_name"))
        home = tricode(cell(row, "home_team_name"))
        if not raw_date or not away or not home:
            continue
        text = _re.sub(r"<[^>]+>", "", raw_date).strip()
        try:
            parsed = datetime.strptime(text, "%a, %b %d, %Y")
        except ValueError:
            continue
        games.append({
            "date": parsed.strftime("%Y-%m-%dT00:00:00Z"),
            "home": home,
            "away": away,
            "tip_utc": bbref_tip_utc(parsed.date(), cell(row, "game_start_time")),
            # "NBA Cup" marks every Cup game, the final included: kept only until
            # nba_schedule.exclude_cup_final drops the final (task 33), never written
            "remarks": _re.sub(r"<[^>]+>", "", cell(row, "game_remarks") or "").strip(),
        })
    return games


def fetch_from_bbref(season: str) -> dict:
    """Build the trimmed schedule from basketball-reference month pages.

    Returns the already-trimmed shape, so trim_schedule() passes it through.
    """
    import time
    import urllib.error
    import urllib.request

    year = _season_end_year(season)
    print(f"Fetching {season} schedule from basketball-reference "
          f"(NBA_{year}_games-*)...")

    games = []
    for i, month in enumerate(BBREF_MONTHS):
        url = BBREF_URL.format(year=year, month=month)
        request = urllib.request.Request(url, headers=BROWSER_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                html = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Not every season has a May/June page at fetch time.
                continue
            print(f"  {month}: HTTP {e.code}")
            continue
        except Exception as e:
            print(f"  {month}: {e}")
            continue

        found = _parse_bbref_month(html, year)
        print(f"  {month}: {len(found)} games")
        games.extend(found)
        if i < len(BBREF_MONTHS) - 1:
            # basketball-reference rate-limits aggressively.
            time.sleep(3)

    if not games:
        print("\nNo games parsed. basketball-reference may have changed its "
              "table markup, or the season is not published yet.")
        sys.exit(1)

    # Same game can appear twice if a month page overlaps; keep it unique.
    seen = set()
    unique = []
    for g in sorted(games, key=lambda g: (g["date"], g["away"], g["home"])):
        key = (g["date"], g["away"], g["home"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(g)
    return {"games": unique}


def load_schedule_from_file(path: Path) -> dict:
    """Load schedule from a local JSON file."""
    print(f"Loading schedule from {path}...")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def trim_schedule(full_schedule: dict) -> dict:
    """
    Trim the full NBA schedule to only essential fields.
    
    Input format (NBA API):
        {
            "leagueSchedule": {
                "gameDates": [
                    {
                        "gameDate": "...",
                        "games": [
                            {
                                "gameDateEst": "2025-10-22T00:00:00Z",
                                "homeTeam": {"teamTricode": "BOS", ...},
                                "awayTeam": {"teamTricode": "NYK", ...},
                                ... (30+ other fields)
                            }
                        ]
                    }
                ]
            }
        }
    
    Output format (trimmed):
        {
            "games": [
                {"date": "2025-10-22T00:00:00Z", "home": "BOS", "away": "NYK"},
                ...
            ]
        }
    """
    games = []
    
    # Handle full NBA API format
    if "leagueSchedule" in full_schedule:
        for game_date_obj in full_schedule["leagueSchedule"].get("gameDates", []):
            for game in game_date_obj.get("games", []):
                # Skip preseason games
                if game.get("gameLabel", "").lower() == "preseason":
                    continue
                if game.get("gameSubtype", "").lower() == "preseason":
                    continue
                    
                tip = game.get("gameDateTimeUTC") or None
                if tip and str(game.get("gameStatusText", "")).strip().upper().startswith("TBD"):
                    tip = None          # a placeholder time, not a tip
                if tip:
                    tip = str(tip)[:19].replace(" ", "T") + "Z"
                games.append({
                    "date": game.get("gameDateEst", ""),
                    "home": game.get("homeTeam", {}).get("teamTricode", ""),
                    "away": game.get("awayTeam", {}).get("teamTricode", ""),
                    "tip_utc": tip,
                })
    
    # Handle already-trimmed format (just validate/pass through)
    elif "games" in full_schedule:
        for game in full_schedule["games"]:
            g = {
                "date": game.get("date", ""),
                "home": game.get("home", game.get("home_team", "")),
                "away": game.get("away", game.get("away_team", "")),
            }
            if "tip_utc" in game:
                g["tip_utc"] = game["tip_utc"]
            if game.get("remarks"):
                g["remarks"] = game["remarks"]
            games.append(g)
    
    else:
        print("Warning: Unrecognized schedule format")
        return full_schedule
    
    return {"games": games}


def _report_team_counts(trimmed: dict) -> None:
    """Warn when a team does not have a full 82-game slate.

    A schedule published before the NBA Cup group stage finishes carries only
    80 games per team: the last two depend on how the Cup shakes out and are
    announced in December. That is normal and not an error -- but the file
    has to be refetched then, or the projections lose two games per team for
    the back half of the season.
    """
    from collections import Counter
    counts = Counter()
    for g in trimmed.get("games", []):
        counts[g["home"]] += 1
        counts[g["away"]] += 1
    if not counts:
        return

    off = sorted((team, n) for team, n in counts.items() if n != 82)
    print(f"\n  {len(counts)} teams", end="")
    if not off:
        print(", all with 82 games.")
        return

    sizes = sorted({n for _, n in off})
    print(f"; {len(off)} not at 82 games (have: {sizes}).")
    if sizes == [80] and len(off) == len(counts):
        print("  This is expected for a schedule published before the NBA Cup")
        print("  knockout round is set -- every team's last two games are TBD.")
        print("  REFETCH THIS FILE in mid-December once those are announced.")
    else:
        for team, n in off[:10]:
            print(f"    {team}: {n}")


def _report_and_log_diff(diff: dict, trimmed: dict, output: Path) -> None:
    """Print what the refresh changed and append it to the season's log.

    The log is the record of how the schedule moved under the engine --
    which postponements arrived when -- next to the file it describes.
    """
    from datetime import date
    n_add, n_rem, n_mov = len(diff["added"]), len(diff["removed"]), len(diff["moved"])
    print(f"\n  Changes since the last fetch: {n_add} added, {n_rem} removed, "
          f"{n_mov} moved ({diff['old_games']} -> {diff['new_games']} games).")
    near = changes_within(diff, date.today(), days=14)
    if near:
        print(f"  {len(near)} of them fall in the next 14 days -- these move this "
              "week's and next week's numbers:")
        for line in near[:20]:
            print(f"    {line}")
        if len(near) > 20:
            print(f"    ... and {len(near) - 20} more")
    if n_add or n_rem or n_mov:
        log = output.with_name(output.stem + ".changes.jsonl")
        entry = {"fetched_at": trimmed["fetched_at"], "source": trimmed["source"],
                 **diff}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"  Logged to {log}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch and trim NBA schedule for fantasy basketball projections."
    )
    parser.add_argument(
        "--season",
        default=CURRENT_SEASON,
        help=f"Season to fetch (default: {CURRENT_SEASON}, from league_config). "
             f"Honoured by the bbref source; the nba source always returns "
             f"the current season.",
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        help="Input file path (skip fetching, trim existing file)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output file path (default: the refetched copy, "
             "data/nba_schedule_<season>.refetched.json -- league state, read instead of "
             f"{DEFAULT_OUTPUT} whenever it exists; push it with state.py push)",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "nba", "bbref"],
        default="auto",
        help="where to fetch from (default: auto -- cdn.nba.com, then bbref)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="write even if the new schedule has fewer games than the one it "
             "replaces, in all or for any team (normally refused: a partial fetch, "
             "or a postponement with no new date yet -- Nick's call)",
    )
    parser.add_argument(
        "--tips-only",
        action="store_true",
        help="add each game's tip time to the existing file and change nothing else; "
             "refuses (exit 2, file untouched) if any game differs",
    )
    parser.add_argument(
        "--keep-full",
        action="store_true",
        help="Also save the full (untrimmed) schedule",
    )
    
    args = parser.parse_args()
    
    if args.output is None and not args.tips_only and not args.keep_full:
        return _refetch_copy(args)
    if args.output is None:
        from modules.nba_schedule import schedule_path
        args.output = schedule_path(PROJECT_ROOT)
    _refuse_hidden_engine_write(args.output)

    # Get the schedule
    if args.input:
        full_schedule = load_schedule_from_file(args.input)
        source = f"file:{args.input.name}"
    elif args.source == "bbref":
        full_schedule = fetch_from_bbref(args.season)
        source = "bbref"
    elif args.source == "nba":
        full_schedule = fetch_nba_schedule()
        source = "nba"
    else:
        try:
            full_schedule = fetch_nba_schedule()
            source = "nba"
        except Exception as e:
            print(f"cdn.nba.com failed ({e}); falling back to basketball-reference.")
            full_schedule = fetch_from_bbref(args.season)
            source = "bbref"
    
    # Optionally save full version
    if args.keep_full:
        full_path = args.output.parent / f"{args.output.stem}_full.json"
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(full_schedule, f)
        full_size = full_path.stat().st_size
        print(f"Saved full schedule: {full_path} ({full_size:,} bytes)")
    
    # Trim, compare with what it replaces, then save
    trimmed = trim_schedule(full_schedule)

    old = None
    if args.output.is_file():
        try:
            with open(args.output, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, json.JSONDecodeError):
            old = None
    check_tips(trimmed.get("games", []))
    if args.tips_only:
        if not old:
            print(f"\nREFUSED: --tips-only needs the existing {args.output} to add tips to.")
            sys.exit(2)
        merged, problems = add_tips_only(old, trimmed)
        if problems:
            print(f"\nSTOPPED: the refetch does not match {args.output} game for game, so "
                  f"nothing was written. {len(problems)} difference(s):")
            for line in problems:
                print(f"  {line}")
            print("A moved, added or removed game is Nick's call (STATUS task 33).")
            sys.exit(2)
        check_tips(merged["games"])
        merged["tips_fetched_at"] = stamp({}, source)["fetched_at"]
        merged["tips_source"] = source
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        n = len(merged["games"])
        timed = sum(1 for g in merged["games"] if g.get("tip_utc"))
        print(f"\nAdded tip times to {args.output}: {timed} of {n} games timed, "
              f"{n - timed} with no time yet (tip_utc null). Nothing else changed.")
        return

    from modules.nba_schedule import exclude_cup_final, never_shrinks, window_config
    games, final = exclude_cup_final(trimmed.get("games", []), window_config()["cup_final"])
    trimmed = {"games": games}
    for g in final:
        print(f"  The NBA Cup final ({g['away']} @ {g['home']} {g['date'][:10]}) is not a "
              "regular-season game: left out.")
    diff = diff_schedules(old, trimmed) if old else None
    if diff:
        problem = shrink_problem(diff) or "; ".join(never_shrinks(old, trimmed)) or None
        if problem and not args.force:
            print(f"\nREFUSED: {problem}")
            print(f"  {args.output} was left as it was. Re-run, or pass --force "
                  "if the drop is real.")
            sys.exit(1)

    trimmed = stamp(trimmed, source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2)

    if diff:
        _report_and_log_diff(diff, trimmed, args.output)
    
    trimmed_size = args.output.stat().st_size
    game_count = len(trimmed.get("games", []))

    _report_team_counts(trimmed)
    
    print(f"Saved trimmed schedule: {args.output}")
    print(f"  {game_count} games, {trimmed_size:,} bytes ({trimmed_size/1024:.1f} KB)")
    
    # Show sample
    if game_count > 0:
        print(f"\nSample games:")
        for g in trimmed["games"][:3]:
            print(f"  {g['date'][:10]}: {g['away']} @ {g['home']}")


def fetch_trimmed(season: str = None, source: str = "auto"):
    """(trimmed schedule, source) for modules/nba_schedule.refetch: the nightly
    run's fetch and this script's default. Tips are checked. Raises on any
    failure (never sys.exit): the caller keeps the stored schedule."""
    season = season or CURRENT_SEASON
    try:
        if source == "bbref":
            full, src = fetch_from_bbref(season), "bbref"
        else:
            try:
                full, src = fetch_nba_schedule(), "nba"
            except Exception as e:                      # noqa: BLE001 -- cdn.nba.com 403s (Sep 2026)
                if source == "nba":
                    raise
                print(f"cdn.nba.com failed ({e}); falling back to basketball-reference.")
                full, src = fetch_from_bbref(season), "bbref"
    except SystemExit as e:
        raise RuntimeError(f"the schedule fetch stopped (exit {e.code}): no games parsed") from None
    trimmed = trim_schedule(full)
    if not trimmed.get("games"):
        raise RuntimeError(f"the {src} fetch returned no games")
    check_tips(trimmed["games"])
    return trimmed, src


def _refuse_hidden_engine_write(output: Path) -> None:
    """Writing the engine's file while a refetched copy exists would change a
    file nothing reads."""
    from modules.nba_schedule import engine_path, refetched_path
    eng, copy = engine_path(PROJECT_ROOT).resolve(), refetched_path(PROJECT_ROOT)
    if Path(output).resolve() == eng and copy.is_file():
        print(f"REFUSED: {copy.relative_to(PROJECT_ROOT).as_posix()} exists and is what the engine "
              f"reads; writing {output} would change nothing. Drop --output to refetch the copy.")
        sys.exit(2)


def _refetch_copy(args) -> int:
    """The default: modules/nba_schedule.refetch, the nightly run's own path:
    the NBA Cup final left out, never shrinking (unless --force), the
    stand-ins checked, then the refetched copy written (league state)."""
    from modules.league_clock import league_today
    from modules.nba_schedule import refetch
    if args.input:
        src_name = f"file:{args.input.name}"
        fetch = lambda: (trim_schedule(load_schedule_from_file(args.input)), src_name)  # noqa: E731
    else:
        fetch = lambda: fetch_trimmed(args.season, args.source)                     # noqa: E731
    out = refetch(PROJECT_ROOT, league_today(), fetch, force=args.force)
    print(f"\n{out['outcome'].upper()}: compared with {out['from']}"
          + (f" -- {out['why']}" if out.get("why") else ""))
    if out["outcome"] in ("failed", "refused"):
        print("  Nothing was written; the stored schedule stays."
              + (" Pass --force if a drop is real (a postponement with no new date)."
                 if out["outcome"] == "refused" else ""))
        return 1
    print(f"  Wrote {out['to']}: {out['games']} games from {out['source']} "
          f"(+{out['added']} -{out['removed']}, {len(out['moved'])} moved).")
    for line in out["moved"][:20]:
        print(f"    moved {line}")
    for line in out["cup_final"]:
        print(f"  The NBA Cup final ({line}) is not a regular-season game: left out.")
    print("  League state: push it with python scripts\\state.py push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
