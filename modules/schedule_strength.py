"""
schedule_strength.py

Computes schedule strength for each fantasy manager by simulating optimal
daily lineups.  Instead of naively summing every rostered player's NBA
games (which inflates bench-heavy rosters), this module determines how
many games actually fit into starting slots on each game day.

KEY CONCEPT -- "startable games":
  On any given day a manager can start at most 10 players:
      PG(1) SG(1) G(1) SF(1) PF(1) F(1) C(2) Util(2)
  If 14 healthy players have games that day, only 10 start; the other 4
  sit on the bench no matter what.  "startable_games" counts only the
  games that make it into an optimal lineup (greedy by projected FPPG).

DESTINATION: Section 3 (Betting Lines) -- explains *usable* schedule
advantages, not just raw game counts.

DATA SOURCES:
  - nba_schedule_2025-26.json: Every NBA game with date, home, away
  - ROSTERS.json: Which players belong to which manager
  - PLAYERLIST.xlsx: player_name -> nba_team, position(s), projectedFPPG
  - SCHEDULE.json: Fantasy week date ranges
  - INJURY_OVERRIDES.json: Who is injured (for weekly view)

INTEGRATION POINTS:
  - report_builder.py: build_stats_report() calls build_schedule_strength()
  - format_stats_report.py: Section 3 uses startable_games in betting lines
"""

from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from .data_loader import FantasyData, MANAGERS


# Date parsing warnings: avoid silently dropping NBA games when schedule dates are malformed.
MAX_DATE_PARSE_WARNINGS = 5
_DATE_PARSE_WARNINGS_SHOWN = 0
_WARNED_DATE_PARSE_KEYS: set[tuple[str, str, str]] = set()


def _warn_bad_game_date(raw_date: object, home: object, away: object) -> None:
    """Print a limited number of warnings for unparseable NBA schedule dates."""
    global _DATE_PARSE_WARNINGS_SHOWN

    key = (str(raw_date), str(home), str(away))
    if key in _WARNED_DATE_PARSE_KEYS:
        return
    _WARNED_DATE_PARSE_KEYS.add(key)

    _DATE_PARSE_WARNINGS_SHOWN += 1
    if _DATE_PARSE_WARNINGS_SHOWN <= MAX_DATE_PARSE_WARNINGS:
        print(
            f"Warning: Could not parse NBA schedule date {raw_date!r} for game {away}@{home}; skipping."
        )
    elif _DATE_PARSE_WARNINGS_SHOWN == MAX_DATE_PARSE_WARNINGS + 1:
        print(
            "Warning: More unparseable NBA schedule dates encountered; further warnings suppressed."
        )


# ============================================================================
# CONSTANTS
# ============================================================================

# The 30 real NBA teams.  Anything else (All-Star, exhibition) is filtered.
NBA_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET",
    "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN",
    "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS",
    "TOR", "UTA", "WAS",
}

# Yahoo H2H fantasy basketball starting slots.
# Each tuple: (slot_name, set_of_eligible_positions, capacity)
# Ordered from MOST restrictive to LEAST restrictive -- this ordering is
# critical for the greedy lineup algorithm.
SLOT_DEFINITIONS = [
    ("PG",   {"PG"},           1),
    ("SG",   {"SG"},           1),
    ("SF",   {"SF"},           1),
    ("PF",   {"PF"},           1),
    ("C",    {"C"},            2),
    ("G",    {"PG", "SG"},     1),
    ("F",    {"SF", "PF"},     1),
    ("Util", {"PG", "SG", "SF", "PF", "C"}, 2),
]

# Max starters per day (sum of all slot capacities)
MAX_STARTERS_PER_DAY = sum(cap for _, _, cap in SLOT_DEFINITIONS)  # 10


# ============================================================================
# CORE: NBA SCHEDULE HELPERS
# ============================================================================

def count_nba_team_games(
    nba_schedule: dict,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """
    Count how many games each NBA team plays in a date range (inclusive).

    Filters out All-Star / exhibition games (non-NBA team codes),
    games with None for home or away, and games outside the date range.

    Returns:
        Dict mapping NBA team abbreviation -> game count.
    """
    team_games: dict[str, int] = {team: 0 for team in NBA_TEAMS}

    for game in nba_schedule.get("games", []):
        home = game.get("home")
        away = game.get("away")
        if home is None or away is None:
            continue
        if home not in NBA_TEAMS or away not in NBA_TEAMS:
            continue

        raw_date = game.get("date", "")
        try:
            game_date = datetime.fromisoformat(
                raw_date.replace("Z", "+00:00")
            ).date()
        except (ValueError, AttributeError):
            _warn_bad_game_date(raw_date, home, away)
            continue

        if start_date <= game_date <= end_date:
            team_games[home] += 1
            team_games[away] += 1

    return team_games


def get_daily_nba_schedule(
    nba_schedule: dict,
    start_date: date,
    end_date: date,
) -> dict[date, set[str]]:
    """
    Build a day-by-day lookup of which NBA teams are playing.

    Returns:
        Dict mapping each date -> set of NBA team abbreviations with a
        game that day.
        Example: {date(2026,2,2): {"LAL","BOS","DEN",...}, ...}
    """
    daily: dict[date, set[str]] = {}

    for game in nba_schedule.get("games", []):
        home = game.get("home")
        away = game.get("away")
        if home is None or away is None:
            continue
        if home not in NBA_TEAMS or away not in NBA_TEAMS:
            continue

        raw_date = game.get("date", "")
        try:
            game_date = datetime.fromisoformat(
                raw_date.replace("Z", "+00:00")
            ).date()
        except (ValueError, AttributeError):
            _warn_bad_game_date(raw_date, home, away)
            continue

        if start_date <= game_date <= end_date:
            if game_date not in daily:
                daily[game_date] = set()
            daily[game_date].add(home)
            daily[game_date].add(away)

    return daily


# ============================================================================
# CORE: PLAYER INFO
# ============================================================================

def build_player_team_map(playerlist: pd.DataFrame) -> dict[str, str]:
    """
    Build a mapping from player name to their NBA team abbreviation.

    Kept for backward compatibility -- callers that only need the team
    can still use this lighter-weight lookup.
    """
    mapping = {}
    for _, row in playerlist.iterrows():
        name = row.get("player_name")
        team = row.get("player_nba_team")
        if pd.notna(name) and pd.notna(team):
            mapping[str(name)] = str(team)
    return mapping


def build_player_info_map(
    playerlist: pd.DataFrame,
) -> dict[str, dict]:
    """
    Build a rich player-info lookup from PLAYERLIST.

    Returns:
        Dict mapping player_name -> {
            "nba_team": str,
            "positions": set[str],   (e.g. {"PG","SG"})
            "proj_fppg": float,
        }
    """
    info: dict[str, dict] = {}

    for _, row in playerlist.iterrows():
        name = row.get("player_name")
        team = row.get("player_nba_team")
        if pd.isna(name) or pd.isna(team):
            continue

        name = str(name)
        team = str(team)

        # Parse positions: "PG,SG" -> {"PG", "SG"}
        raw_pos = row.get("player_position(s)", "")
        if pd.isna(raw_pos) or not raw_pos:
            positions = set()
        else:
            positions = {p.strip() for p in str(raw_pos).split(",")}

        proj = row.get("projectedFPPG", 0.0)
        if pd.isna(proj):
            proj = 0.0

        info[name] = {
            "nba_team": team,
            "positions": positions,
            "proj_fppg": float(proj),
        }

    return info


# ============================================================================
# CORE: DAILY LINEUP SIMULATION
# ============================================================================

def fill_daily_lineup(
    available_players: list[tuple[str, set[str], float]],
) -> tuple[list[str], list[str]]:
    """
    Greedily fill starting slots for one game day.

    Players are tried in descending projected-FPPG order.  For each
    player we attempt to place them in the most restrictive eligible
    slot first (PG/SG/SF/PF/C before G/F before Util).  This heuristic
    maximises total projected points and mirrors real manager behaviour.

    Args:
        available_players: List of (player_name, positions_set, proj_fppg),
            already sorted by proj_fppg descending.

    Returns:
        (started, benched) -- two lists of player names.
    """
    # Track remaining capacity per slot
    remaining = {name: cap for name, _, cap in SLOT_DEFINITIONS}

    started: list[str] = []
    benched: list[str] = []

    for player_name, positions, _proj in available_players:
        placed = False
        for slot_name, eligible_pos, _ in SLOT_DEFINITIONS:
            if remaining[slot_name] <= 0:
                continue
            # Player is eligible if ANY of their positions match the slot
            if positions & eligible_pos:
                remaining[slot_name] -= 1
                started.append(player_name)
                placed = True
                break
        if not placed:
            benched.append(player_name)

    return started, benched


def simulate_daily_lineups(
    manager: str,
    roster: list[str],
    player_info: dict[str, dict],
    daily_schedule: dict[date, set[str]],
    out_players: dict[str, Optional[date]],
) -> dict:
    """
    Simulate optimal lineups for every game day in the period.

    For each day:
      1. Find healthy rostered players whose NBA team plays that day.
      2. Sort by projected FPPG descending.
      3. Greedily fill the 10 starting slots.
      4. Track who starts and who rides the bench.

    Handles partial returns: a player in out_players whose value is a
    date (not None) is unavailable BEFORE that date and available on or
    after it.  A value of None means out for the entire period.

    Args:
        manager: Manager name (for labelling only).
        roster: List of player names on this manager's roster.
        player_info: Full player-info map from build_player_info_map().
        daily_schedule: From get_daily_nba_schedule() -- {date: set(teams)}.
        out_players: Dict mapping player name -> return date.
                     None value = out the entire period.
                     date value = unavailable before that date, available
                     on or after it.

    Returns:
        Dict with:
          - startable_games: int (games that made it into starting lineups)
          - bench_games: int (healthy games that did NOT fit into lineups)
          - healthy_games: int (startable + bench -- all non-injured games)
          - total_games: int (including injured players' games)
          - daily_detail: list of per-day dicts (day, available, started,
                          benched counts)
          - player_breakdown: list of per-player dicts
    """
    # Per-player accumulators
    player_total = {p: 0 for p in roster}
    player_healthy = {p: 0 for p in roster}
    player_started = {p: 0 for p in roster}
    player_benched = {p: 0 for p in roster}

    daily_detail: list[dict] = []

    for game_day in sorted(daily_schedule.keys()):
        teams_playing = daily_schedule[game_day]

        # Who on this roster has a game today?
        available: list[tuple[str, set[str], float]] = []
        injured_with_game = 0

        for player_name in roster:
            pi = player_info.get(player_name)
            if pi is None:
                continue
            if pi["nba_team"] not in teams_playing:
                continue

            # This player's team plays today
            player_total[player_name] += 1

            # Check injury / partial-return status
            if player_name in out_players:
                return_date = out_players[player_name]
                if return_date is None or game_day < return_date:
                    # Still out (no return date, or before return date)
                    injured_with_game += 1
                    continue
                # On or after return date -- player is available

            player_healthy[player_name] += 1
            available.append((
                player_name,
                pi["positions"],
                pi["proj_fppg"],
            ))

        # Sort by projection descending
        available.sort(key=lambda x: -x[2])

        # Fill lineup
        started, benched_list = fill_daily_lineup(available)

        for p in started:
            player_started[p] += 1
        for p in benched_list:
            player_benched[p] += 1

        daily_detail.append({
            "date": game_day.isoformat(),
            "available_healthy": len(available),
            "started": len(started),
            "benched": len(benched_list),
            "injured_with_game": injured_with_game,
        })

    # Totals
    total_games = sum(player_total.values())
    healthy_games = sum(player_healthy.values())
    startable_games = sum(player_started.values())
    bench_games = sum(player_benched.values())

    # Player breakdown (sorted by started games desc, then projection)
    player_breakdown = []
    for p in roster:
        pi = player_info.get(p, {})
        # Determine injury status string
        if p in out_players:
            ret = out_players[p]
            if ret is None:
                inj_status = "out"
            else:
                inj_status = f"returns {ret.isoformat()}"
        else:
            inj_status = "healthy"
        player_breakdown.append({
            "player": p,
            "nba_team": pi.get("nba_team", "???"),
            "positions": ",".join(sorted(pi.get("positions", set()))),
            "proj_fppg": pi.get("proj_fppg", 0.0),
            "total_games": player_total.get(p, 0),
            "healthy_games": player_healthy.get(p, 0),
            "started_games": player_started.get(p, 0),
            "benched_games": player_benched.get(p, 0),
            "is_injured": p in out_players,
            "injury_status": inj_status,
        })
    player_breakdown.sort(
        key=lambda x: (-x["started_games"], -x["proj_fppg"])
    )

    return {
        "total_games": total_games,
        "healthy_games": healthy_games,
        "startable_games": startable_games,
        "bench_games": bench_games,
        "player_breakdown": player_breakdown,
        "daily_detail": daily_detail,
    }


# ============================================================================
# LEGACY-COMPATIBLE WRAPPER
# ============================================================================

def count_manager_games(
    manager: str,
    rosters: dict[str, list[str]],
    player_team_map: dict[str, str],
    nba_team_games: dict[str, int],
    injury_overrides: Optional[dict] = None,
    week: Optional[int] = None,
) -> dict:
    """
    Legacy API -- counts total and healthy games without lineup simulation.

    Still used by _build_for_week_range (ROS) where daily simulation is
    too expensive and injuries change anyway.  Returns the same shape as
    before so existing callers don't break.
    """
    players = rosters.get(manager, [])
    player_breakdown = []
    total_games = 0
    healthy_games = 0

    out_players = set()
    if injury_overrides and week is not None:
        for player_entry in injury_overrides.get("players", []):
            if week in player_entry.get("out_weeks", []):
                out_players.add(player_entry["player_name"])

    for player_name in players:
        nba_team = player_team_map.get(player_name)
        if nba_team is None:
            player_breakdown.append({
                "player": player_name,
                "nba_team": "???",
                "games": 0,
                "is_injured": player_name in out_players,
            })
            continue

        games = nba_team_games.get(nba_team, 0)
        is_injured = player_name in out_players

        player_breakdown.append({
            "player": player_name,
            "nba_team": nba_team,
            "games": games,
            "is_injured": is_injured,
        })

        total_games += games
        if not is_injured:
            healthy_games += games

    player_breakdown.sort(key=lambda x: -x["games"])

    return {
        "total_games": total_games,
        "healthy_games": healthy_games,
        "player_breakdown": player_breakdown,
    }


# ============================================================================
# RANKING HELPER
# ============================================================================

def add_rankings(
    manager_data: dict[str, dict],
    key: str,
    rank_key: str,
) -> None:
    """
    Add a ranking field to each manager's data dict, ranked by a given key.
    Rank 1 = most games (best schedule strength).  Mutates in place.
    """
    sorted_managers = sorted(
        manager_data.keys(),
        key=lambda m: -manager_data[m].get(key, 0),
    )
    for rank, manager in enumerate(sorted_managers, start=1):
        manager_data[manager][rank_key] = rank


# ============================================================================
# MAIN BUILDER (called by report_builder.py)
# ============================================================================

def build_schedule_strength(
    data: FantasyData,
    week: int,
) -> dict:
    """
    Build the complete schedule strength analysis for the upcoming week
    and the rest of the season.

    For the upcoming week: uses daily lineup simulation to compute
    "startable_games" (games that fit into optimal starting lineups).
    This is the number that matters for matchup context.

    For rest-of-season: uses simple game counts (no lineup sim) because
    injuries change week to week and the per-day simulation would be
    misleadingly precise over 6+ weeks.

    Args:
        data: FantasyData container
        week: The CURRENT week number (just completed).  Schedule
              strength is computed for week+1 (upcoming) and for
              weeks week+1 through total_weeks (rest of season).

    Returns:
        Dict with structure:
        {
            "upcoming_week": {
                "week": 16,
                "start_date": "...", "end_date": "...",
                "managers": {
                    "Nick": {
                        "total_games": 59,
                        "healthy_games": 56,
                        "startable_games": 42,
                        "bench_games": 14,
                        "daily_detail": [...],
                        "player_breakdown": [...],
                        "startable_rank": 1,
                        ...
                    }, ...
                }
            },
            "rest_of_season": { ... },
            "nba_team_games_this_week": { ... },
        }
    """
    rosters = data.get_current_rosters()
    player_info = build_player_info_map(data.playerlist)
    player_team_map = build_player_team_map(data.playerlist)
    schedule_weeks = data.schedule.get("weeks", [])
    total_weeks = data.schedule.get("total_weeks", 21)

    upcoming_week_num = week + 1

    # --- Upcoming week (with daily lineup simulation) ---
    upcoming_result = _build_for_week_with_lineups(
        upcoming_week_num,
        schedule_weeks,
        data.nba_schedule,
        rosters,
        player_info,
        data.injury_overrides,
    )

    # --- Rest of season (simple counts, no lineup sim) ---
    ros_result = _build_for_week_range(
        start_week=upcoming_week_num,
        end_week=total_weeks,
        schedule_weeks=schedule_weeks,
        nba_schedule=data.nba_schedule,
        rosters=rosters,
        player_team_map=player_team_map,
        injury_overrides=data.injury_overrides,
    )

    return {
        "upcoming_week": upcoming_result,
        "rest_of_season": ros_result,
        "nba_team_games_this_week": upcoming_result.get(
            "nba_team_games", {}
        ),
    }


# ============================================================================
# INTERNAL HELPERS
# ============================================================================

def _get_week_dates(
    week_num: int,
    schedule_weeks: list[dict],
) -> Optional[tuple[date, date]]:
    """Look up start/end dates for a fantasy week number."""
    for w in schedule_weeks:
        if w["week"] == week_num:
            start = datetime.strptime(w["start_date"], "%Y-%m-%d").date()
            end = datetime.strptime(w["end_date"], "%Y-%m-%d").date()
            return (start, end)
    return None


def _build_for_week_with_lineups(
    week_num: int,
    schedule_weeks: list[dict],
    nba_schedule: dict,
    rosters: dict[str, list[str]],
    player_info: dict[str, dict],
    injury_overrides: dict,
) -> dict:
    """
    Build schedule strength for a single fantasy week using daily
    lineup simulation.

    This is the new, lineup-aware version that replaces the naive
    _build_for_week for the upcoming week.
    """
    dates = _get_week_dates(week_num, schedule_weeks)
    if dates is None:
        return {
            "week": week_num,
            "error": f"Week {week_num} not found in schedule",
        }

    start_date, end_date = dates

    # Get daily schedule (which teams play each day)
    daily_schedule = get_daily_nba_schedule(
        nba_schedule, start_date, end_date,
    )

    # Also get aggregate team game counts (for the summary dict)
    nba_team_games = count_nba_team_games(
        nba_schedule, start_date, end_date,
    )

    # Build injured-player dict for this week.
    # Keys are player names; values are return dates (or None if out
    # for the entire week).  Players with return_week == this week
    # and a return_date are partially available.
    out_players: dict[str, Optional[date]] = {}
    if injury_overrides:
        for entry in injury_overrides.get("players", []):
            player_name = entry.get("player_name", "")

            # Hard out for this week
            if week_num in entry.get("out_weeks", []):
                out_players[player_name] = None
                continue

            # Partial return: player was out in previous weeks and
            # return_week == this week.  They are unavailable before
            # return_date and available on or after it.
            ret_week = entry.get("return_week")
            if ret_week == week_num:
                raw_ret_date = entry.get("return_date")
                if raw_ret_date:
                    try:
                        ret_date = datetime.strptime(
                            raw_ret_date, "%Y-%m-%d"
                        ).date()
                        out_players[player_name] = ret_date
                    except ValueError:
                        pass  # Bad date format -- treat as fully available

    # Simulate each manager's lineups
    managers_data: dict[str, dict] = {}
    for manager in MANAGERS:
        roster = rosters.get(manager, [])
        result = simulate_daily_lineups(
            manager=manager,
            roster=roster,
            player_info=player_info,
            daily_schedule=daily_schedule,
            out_players=out_players,
        )
        managers_data[manager] = result

    # Add rankings
    add_rankings(managers_data, "startable_games", "startable_rank")
    add_rankings(managers_data, "healthy_games", "healthy_rank")
    add_rankings(managers_data, "total_games", "total_rank")

    return {
        "week": week_num,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "managers": managers_data,
        "nba_team_games": nba_team_games,
    }


def _build_for_week_range(
    start_week: int,
    end_week: int,
    schedule_weeks: list[dict],
    nba_schedule: dict,
    rosters: dict[str, list[str]],
    player_team_map: dict[str, str],
    injury_overrides: dict,
) -> dict:
    """
    Build schedule strength across multiple fantasy weeks (rest of season).

    Uses the simpler count_manager_games (no daily lineup sim) because
    over multiple weeks injuries change and daily precision is misleading.
    """
    start_dates = _get_week_dates(start_week, schedule_weeks)
    end_dates = _get_week_dates(end_week, schedule_weeks)

    if start_dates is None or end_dates is None:
        return {
            "error": f"Could not find weeks {start_week}-{end_week}"
        }

    overall_start = start_dates[0]
    overall_end = end_dates[1]
    weeks_remaining = end_week - start_week + 1

    nba_team_games = count_nba_team_games(
        nba_schedule, overall_start, overall_end,
    )

    # No injury filtering for ROS -- injuries change weekly
    managers_data = {}
    for manager in MANAGERS:
        managers_data[manager] = count_manager_games(
            manager, rosters, player_team_map, nba_team_games,
            injury_overrides=None,
            week=None,
        )

    add_rankings(managers_data, "total_games", "total_rank")

    # Strip player_breakdown from ROS to keep JSON size reasonable
    for manager in managers_data:
        del managers_data[manager]["player_breakdown"]

    return {
        "weeks_remaining": weeks_remaining,
        "start_date": overall_start.isoformat(),
        "end_date": overall_end.isoformat(),
        "managers": managers_data,
    }
