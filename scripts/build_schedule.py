#!/usr/bin/env python3
"""
build_schedule.py -- write config/SCHEDULE.json for the current season from
Yahoo.

WHY THIS EXISTS
---------------
SCHEDULE.json was built by hand every year, and the season reset does not
clear it, so for the whole preseason the live file was the PREVIOUS season's
-- right shape, wrong year. Six modules used to read week counts out of it
and silently applied last season's boundary; they now read league_config, but
the matchups and dates still come from here and still have to be this
season's.

WHAT IT WRITES
--------------
Every week's pairings and date range, straight from Yahoo's scoreboard, which
carries week_start and week_end on each matchup. That matters: Yahoo's
week_date_range() refuses to look more than one week ahead, but the scoreboard
payload does not, so the whole season can be built in the preseason.

The week COUNTS come from league_config, not from Yahoo. Yahoo is told a
different story about this league on purpose -- see the warnings below.

WHAT IT WILL TELL YOU ABOUT
---------------------------
Yahoo does not know about the league's real format. It is configured with a
21-week regular season and its own 2-week playoff, so:

  * weeks 16-21 come back as ordinary round-robin pairings. Under the real
    format those are the best-of-3 bracket, and the pairings depend on the
    final standings, so they cannot be known until week 15 is over. They are
    written as-is and flagged.
  * weeks 22-23 come back EMPTY, because Yahoo is holding them for a playoff
    bracket it will seed itself, by record. The Cup is seeded by POINTS. Turn
    Yahoo's playoffs off to be able to set those pairings.

USAGE
    py scripts/build_schedule.py               # preview
    py scripts/build_schedule.py --execute
    py scripts/build_schedule.py --execute --league-key 478.l.16778

EXIT CODES
    0 = written (or a clean preview)
    1 = refused; nothing was written
"""

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules.data_loader import (  # noqa: E402
    CURRENT_SEASON, CURRENT_SEASON_LONG, MANAGERS, MANAGER_TO_TEAM,
    PLAYOFF_START_WEEK, REGULAR_SEASON_WEEKS, TOTAL_WEEKS,
    phase_for_week, resolve_league_key,
)

SCHEDULE = PROJECT_ROOT / "config" / "SCHEDULE.json"


def manager_for(team_name, fallback_map):
    """Map a Yahoo team name to a manager, via config then a live lookup."""
    if team_name in fallback_map:
        return fallback_map[team_name]
    lowered = {k.lower(): v for k, v in fallback_map.items()}
    return lowered.get(str(team_name).lower())


def fetch_weeks(league, first, last, name_to_manager):
    """[{week, start_date, end_date, days, matchups}] from Yahoo's scoreboard."""
    weeks, problems = [], []
    for wk in range(first, last + 1):
        try:
            raw = league.matchups(wk)
            board = raw["fantasy_content"]["league"][1]["scoreboard"]["0"]["matchups"]
        except Exception as e:
            problems.append(f"week {wk}: could not read the scoreboard ({e})")
            continue

        count = int(board.get("count", 0))
        entry = {"week": wk, "start_date": None, "end_date": None,
                 "days": None, "matchups": []}
        for i in range(count):
            matchup = board[str(i)]["matchup"]
            entry["start_date"] = entry["start_date"] or matchup.get("week_start")
            entry["end_date"] = entry["end_date"] or matchup.get("week_end")
            teams = matchup["0"]["teams"]
            names = []
            for j in range(int(teams["count"])):
                block = teams[str(j)]["team"][0]
                name = next((d["name"] for d in block
                             if isinstance(d, dict) and "name" in d), None)
                names.append(name)
            managers = [manager_for(n, name_to_manager) for n in names]
            if len(managers) != 2 or not all(managers):
                problems.append(
                    f"week {wk}: could not map {names} to managers -- check "
                    "manager_to_team in league_config.json")
                continue
            entry["matchups"].append({"manager_a": managers[0],
                                      "manager_b": managers[1]})

        if entry["start_date"] and entry["end_date"]:
            a = datetime.strptime(entry["start_date"], "%Y-%m-%d").date()
            b = datetime.strptime(entry["end_date"], "%Y-%m-%d").date()
            entry["days"] = (b - a).days + 1
        if not entry["matchups"]:
            problems.append(
                f"week {wk}: Yahoo returned NO matchups. It is holding this "
                "week for its own playoff bracket -- turn playoffs off in the "
                "league settings to be able to set the pairings.")
        weeks.append(entry)
    return weeks, problems


def audit(weeks):
    """Say how what Yahoo returned compares to the format we actually play."""
    from collections import Counter
    notes = []

    regular = [w for w in weeks if phase_for_week(CURRENT_SEASON, w["week"]) == "regular_season"]
    pairs = Counter()
    for w in regular:
        for m in w["matchups"]:
            pairs[tuple(sorted((m["manager_a"], m["manager_b"])))] += 1
    if pairs:
        counts = sorted(set(pairs.values()))
        expected = REGULAR_SEASON_WEEKS // (len(MANAGERS) - 1)
        ok = counts == [expected]
        notes.append(
            f"  regular season (wks 1-{REGULAR_SEASON_WEEKS}): "
            f"{'OK -- ' if ok else 'MISMATCH -- '}"
            f"{counts} meetings per opponent, expected {expected}")
        if not ok:
            for p, n in sorted(pairs.items()):
                notes.append(f"      {p[0]} vs {p[1]}: {n}")

    for stage, label in (("playoffs", "bracket"), ("cup", "Cup")):
        wks = [w for w in weeks
               if phase_for_week(CURRENT_SEASON, w["week"]) == stage]
        if not wks:
            continue
        empty = [w["week"] for w in wks if not w["matchups"]]
        notes.append(
            f"  {label} (wks {wks[0]['week']}-{wks[-1]['week']}): "
            + (f"{len(empty)} week(s) with no matchups: {empty}" if empty
               else "pairings present, but they are Yahoo's round robin -- "
                    "they depend on seeding and must be set once week "
                    f"{REGULAR_SEASON_WEEKS} is final"))
    return notes


def main():
    ap = argparse.ArgumentParser(
        description="Write config/SCHEDULE.json for the current season from Yahoo.")
    ap.add_argument("--execute", action="store_true",
                    help="write the file (default: preview)")
    ap.add_argument("--league-key", default=None,
                    help="override the league key")
    args = ap.parse_args()

    league_key, key_source = resolve_league_key(args.league_key)
    if not league_key:
        print(f"\n  ERROR: {key_source}")
        return 1

    print("=" * 66)
    print(f"  BUILD SCHEDULE -- {CURRENT_SEASON}")
    print("=" * 66)
    print(f"\n  league key: {league_key}  ({key_source})")

    try:
        from yahoo_oauth import OAuth2
        import yahoo_fantasy_api as yfa
    except ImportError as e:
        print(f"\n  ERROR: {e}")
        return 1

    oauth = OAuth2(None, None, from_file=str(PROJECT_ROOT / "oauth2.json"))
    league = yfa.League(oauth, league_key)

    settings = league.settings()
    yahoo_season = str(settings.get("season", ""))
    expected_season = CURRENT_SEASON.split("-")[0]
    if yahoo_season and yahoo_season != expected_season:
        print(f"\n  REFUSED: Yahoo says this league is season {yahoo_season}, "
              f"but league_config says {CURRENT_SEASON}.")
        return 1

    name_to_manager = {v: k for k, v in MANAGER_TO_TEAM.items()}
    live = {v.get("name"): None for v in league.teams().values()}
    unknown = [n for n in live if manager_for(n, name_to_manager) is None]
    if unknown:
        print(f"\n  REFUSED: Yahoo team name(s) {unknown} are not in "
              "manager_to_team. Update league_config.json first -- guessing "
              "here would silently attribute a whole season to the wrong "
              "manager.")
        return 1

    weeks, problems = fetch_weeks(league, 1, TOTAL_WEEKS, name_to_manager)
    if len(weeks) != TOTAL_WEEKS:
        print(f"\n  REFUSED: read {len(weeks)} weeks, league_config says "
              f"{TOTAL_WEEKS}.")
        return 1

    print(f"\n  Read {TOTAL_WEEKS} weeks: "
          f"{weeks[0]['start_date']} to {weeks[-1]['end_date']}")
    long_weeks = [(w["week"], w["days"]) for w in weeks if (w["days"] or 7) > 7]
    if long_weeks:
        print(f"  Stretched weeks (All-Star break): {long_weeks}")

    print("\n  How Yahoo's schedule compares to the format we play:")
    for line in audit(weeks):
        print(line)

    if problems:
        print(f"\n  {len(problems)} issue(s):")
        for p in problems:
            print(f"    - {p}")

    payload = {
        "season_year": CURRENT_SEASON_LONG,
        "total_weeks": TOTAL_WEEKS,
        "regular_season_weeks": REGULAR_SEASON_WEEKS,
        "playoff_start_week": PLAYOFF_START_WEEK,
        "_source": (f"built from Yahoo league {league_key} on "
                    f"{date.today().isoformat()}. Week COUNTS come from "
                    "league_config, not Yahoo -- Yahoo is configured with a "
                    "21-week regular season and its own 2-week playoff, which "
                    "is not the format this league plays."),
        "managers": list(MANAGERS),
        "weeks": weeks,
    }

    if not args.execute:
        print("\n  [DRY-RUN] Nothing written. Re-run with --execute.")
        return 0

    if SCHEDULE.is_file():
        shutil.copy2(SCHEDULE, SCHEDULE.with_suffix(".json.bak"))
    SCHEDULE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\n  Wrote {SCHEDULE.name}")
    print("  Run: py scripts/verify_project_integrity.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
