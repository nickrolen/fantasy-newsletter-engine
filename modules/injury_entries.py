"""
injury_entries.py -- an INJURY_OVERRIDES entry, computed and checked.

One place that turns "out from D1, back on D2" into the file's schema, and one
place that checks an entry's shape against the schedules. scripts/overrides.py
(add) writes with the first; scripts/verify_project_integrity.py checks with
the second. Neither touches the network.

Fantasy weeks come from config/SCHEDULE.json, NEVER the calendar: week 7 is 14
days (LEAGUE_RULES.md rule 9). NBA games come from the season's NBA schedule
file (data/nba_schedule_2026-27.json), each game on its date's first ten
characters -- the reading simulator_betting.team_season_dates uses.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .absence import parse_return_date

# The keys an entry carries, in the order Nick's hand-written entries use;
# nba_team (new 10-28) follows the name.
ENTRY_ORDER = ("player_name", "nba_team", "out_weeks", "notes", "return_week", "return_games",
               "total_week_games", "return_notes", "return_date")


class EntryRefused(ValueError):
    """The entry cannot be written as asked; the message says what to do."""


# -----------------------------------------------------------------------------
# the schedules
# -----------------------------------------------------------------------------

def fantasy_weeks(schedule: dict) -> list:
    """[(week, first day, last day)] from SCHEDULE.json, in order."""
    out = []
    for w in schedule.get("weeks", []):
        out.append((int(w["week"]), date.fromisoformat(str(w["start_date"])[:10]),
                    date.fromisoformat(str(w["end_date"])[:10])))
    if not out:
        raise EntryRefused("SCHEDULE.json has no weeks")
    return sorted(out)


def week_of(schedule: dict, d: date) -> Optional[int]:
    for week, start, end in fantasy_weeks(schedule):
        if start <= d <= end:
            return week
    return None


def week_bounds(schedule: dict, week: int) -> tuple:
    for w, start, end in fantasy_weeks(schedule):
        if w == int(week):
            return start, end
    raise EntryRefused(f"week {week} is not in SCHEDULE.json")


def team_games(nba_schedule: dict) -> dict:
    """{team: sorted game dates} from the NBA schedule file."""
    out = {}
    for g in (nba_schedule or {}).get("games", []):
        d = str(g.get("date", ""))[:10]
        if not d:
            continue
        for side in ("home", "away"):
            t = str(g.get(side) or "").upper()
            if t:
                out.setdefault(t, set()).add(date.fromisoformat(d))
    return {t: sorted(ds) for t, ds in out.items()}


def games_in(games: list, start: date, end: date, from_day: date = None) -> int:
    lo = max(start, from_day) if from_day else start
    return sum(1 for d in games if lo <= d <= end)


# -----------------------------------------------------------------------------
# computing an entry
# -----------------------------------------------------------------------------

def _did_you_mean(d: date, schedule: dict) -> str:
    """The same month and day inside the fantasy season, if there is one."""
    weeks = fantasy_weeks(schedule)
    first, last = weeks[0][1], weeks[-1][2]
    for year in (first.year, last.year):
        try:
            cand = d.replace(year=year)
        except ValueError:
            continue
        if first <= cand <= last and cand != d:
            return f" Did you mean {cand.isoformat()}?"
    return ""


def check_dates(out: date, back: Optional[date], schedule: dict, today: date) -> None:
    """Raise EntryRefused on a --back in the past, outside the fantasy season
    or not after --out, and on a --out after the season."""
    weeks = fantasy_weeks(schedule)
    first, last = weeks[0][1], weeks[-1][2]
    if out > last:
        raise EntryRefused(f"--out {out} is after the 2026-27 fantasy season "
                           f"({first} to {last}).{_did_you_mean(out, schedule)}")
    if back is None:
        return
    if not (first <= back <= last):
        raise EntryRefused(f"--back {back} is outside the 2026-27 fantasy season ({first} to "
                           f"{last}).{_did_you_mean(back, schedule)} For a player out for the "
                           "rest of it, use --season instead of --back.")
    if back < today:
        raise EntryRefused(f"--back {back} is in the past (today is {today}).{_did_you_mean(back, schedule)}"
                           " An override whose return has passed changes nothing; if he is "
                           "back, there is nothing to add.")
    if back <= out:
        raise EntryRefused(f"--back {back} is not after --out {out}.")


def compute(name: str, team: str, out: date, back: Optional[date], season: bool,
            schedule: dict, games_by_team: dict, notes: str = None,
            return_notes: str = None) -> tuple:
    """(entry, [notes about how it was computed]) -- pure, no refusals of
    dates (check_dates does those).

    out_weeks:        every fantasy week from the one containing `out` through
                      the week before the return week -- contiguous by
                      construction. An `out` before week 1 starts at week 1.
    return_week:      the fantasy week containing `back`.
    return_games /
    total_week_games: his team's games in the return week on or after `back`,
                      and in all of it.
    season (no back): out for the rest of the season -- out through the LAST
                      fantasy week (23), with no return_week, return_date or
                      game counts (Nick, 10-28). With no stated return, a
                      rostered OFS tag raises no SeasonOutConflict. (Jalen
                      Williams and Cason Wallace are NOT this: they are
                      expected back for the Cup, an ordinary --back
                      2027-03-29.)
    """
    said = []
    team = str(team).upper()
    if team not in games_by_team:
        raise EntryRefused(f"team {team!r} has no games in the NBA schedule; "
                           f"teams: {', '.join(sorted(games_by_team))}")
    weeks = fantasy_weeks(schedule)
    first_week = week_of(schedule, out)
    if first_week is None:
        if out < weeks[0][1]:
            first_week = weeks[0][0]
            said.append(f"--out {out} is before week 1: out from week 1")
        else:
            raise EntryRefused(f"--out {out} falls in no fantasy week")
    if season:
        if back is not None:
            raise EntryRefused("give --back or --season, not both")
        last = weeks[-1][0]
        entry = {"player_name": name, "nba_team": team,
                 "out_weeks": list(range(first_week, last + 1))}
        if notes:
            entry["notes"] = notes
        if return_notes:
            entry["return_notes"] = return_notes
        said.append(f"--season: out through week {last}, the last fantasy week; no return")
        return entry, said
    else:
        if back is None:
            raise EntryRefused("give --back DATE or --season")
        return_week = week_of(schedule, back)
        if return_week is None:
            raise EntryRefused(f"--back {back} falls in no fantasy week")
    start, end = week_bounds(schedule, return_week)
    games = games_by_team[team]
    entry = {"player_name": name, "nba_team": team,
             "out_weeks": list(range(first_week, return_week))}
    if notes:
        entry["notes"] = notes
    entry["return_week"] = return_week
    entry["return_games"] = games_in(games, start, end, back)
    entry["total_week_games"] = games_in(games, start, end)
    if return_notes:
        entry["return_notes"] = return_notes
    entry["return_date"] = back.isoformat()
    return entry, said


# -----------------------------------------------------------------------------
# checking an entry's shape (integrity)
# -----------------------------------------------------------------------------

def shape_problems(entry: dict, schedule: dict, games_by_team: dict, today: date) -> tuple:
    """(failures, warnings) for one entry. Failures: out_weeks not
    contiguous; return_week not one after the last out week; return_date
    malformed or outside return_week; with nba_team, return_games or
    total_week_games not what the NBA schedule says. Warnings: no nba_team
    (the schedule fields are unverified); a return that has passed."""
    name = str(entry.get("player_name", "?"))
    fail, warn = [], []
    weeks = [int(w) for w in entry.get("out_weeks") or []]
    if weeks and weeks != list(range(min(weeks), max(weeks) + 1)):
        fail.append(f"{name}: out_weeks {weeks} is not contiguous")
    rw = entry.get("return_week")
    if rw is not None and weeks and int(rw) != max(weeks) + 1:
        fail.append(f"{name}: return_week {rw} is not one after the last out week ({max(weeks)})")
    rd = None
    try:
        rd = parse_return_date(entry.get("return_date"), name)
    except ValueError as e:
        fail.append(str(e))
    if rd is not None and rw is not None:
        try:
            start, end = week_bounds(schedule, int(rw))
        except EntryRefused as e:
            fail.append(f"{name}: {e}")
            start = end = None
        if start is not None and not (start <= rd <= end):
            fail.append(f"{name}: return_date {rd} is not inside return_week {rw} "
                        f"({start} to {end})")
        elif start is not None:
            team = entry.get("nba_team")
            if not team:
                warn.append(f"{name}: no nba_team, so return_games and total_week_games are "
                            "UNVERIFIED against the NBA schedule")
            elif str(team).upper() not in games_by_team:
                fail.append(f"{name}: nba_team {team!r} has no games in the NBA schedule")
            else:
                games = games_by_team[str(team).upper()]
                want_total, want_back = games_in(games, start, end), games_in(games, start, end, rd)
                if entry.get("total_week_games") != want_total:
                    fail.append(f"{name}: total_week_games {entry.get('total_week_games')} but "
                                f"{team} plays {want_total} in week {rw}")
                if entry.get("return_games") != want_back:
                    fail.append(f"{name}: return_games {entry.get('return_games')} but {team} "
                                f"plays {want_back} in week {rw} on or after {rd}")
    if rd is not None and rd < today:
        warn.append(f"{name}: return_date {rd} has passed -- a candidate to remove "
                    "(py scripts/overrides.py check)")
    return fail, warn


def ordered(entry: dict) -> dict:
    """The entry with its keys in ENTRY_ORDER, any others after, in place."""
    out = {k: entry[k] for k in ENTRY_ORDER if k in entry}
    out.update({k: v for k, v in entry.items() if k not in out})
    return out
