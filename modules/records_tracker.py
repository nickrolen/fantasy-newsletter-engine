"""
records_tracker.py

Tracks and updates season records for Fun Facts generation.
Manages RECORDS.json with current season records, streaks, and title odds history.

FIXES APPLIED (v2):
- Fixed streak tracking logic: only update longest when current EXCEEDS previous
- Added week field to SingleGameRecord
- Cleaner initialization of streak structures
- Fixed lowest_single_game comparison logic
- Separated current_streak (active) from longest_streak (season record)
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from .data_loader import FantasyData, MANAGERS, CURRENT_SEASON, REGULAR_SEASON_WEEKS, save_records
from .weekly_stats import WeeklyReport, MatchupStats


def _load_rookie_seasons_if_available(base_path) -> dict:
    """Load ROOKIE_SEASONS.json if it exists. Returns empty dict otherwise."""
    path = Path(base_path) / "config" / "ROOKIE_SEASONS.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SingleGameRecord:
    """Record for a single game performance."""
    player_name: str
    manager: str
    date: str
    week: int  # FIXED: Added week field
    fantasy_points: float
    nba_opponent: str = ""
    
    def to_dict(self) -> dict:
        return {
            "player_name": self.player_name,
            "manager": self.manager,
            "date": self.date,
            "week": self.week,
            "fantasy_points": self.fantasy_points,
            "nba_opponent": self.nba_opponent,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "SingleGameRecord":
        return cls(
            player_name=d.get("player_name", ""),
            manager=d.get("manager", ""),
            date=d.get("date", ""),
            week=d.get("week", 0),
            fantasy_points=d.get("fantasy_points", 0.0),
            nba_opponent=d.get("nba_opponent", ""),
        )


@dataclass
class WeeklyTeamRecord:
    """Record for weekly team performance."""
    manager: str
    week: int
    score: float
    
    def to_dict(self) -> dict:
        return {
            "manager": self.manager,
            "week": self.week,
            "score": self.score,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "WeeklyTeamRecord":
        return cls(
            manager=d.get("manager", ""),
            week=d.get("week", 0),
            score=d.get("score", 0.0),
        )


@dataclass
class StreakRecord:
    """
    Record for a win/loss streak.
    
    SCHEMA (FIXED):
    - length: Number of consecutive wins/losses
    - start_week: Week the streak started
    - end_week: Week the streak ended (or current week if active)
    - active: True if this streak is ongoing
    """
    length: int
    start_week: int
    end_week: int
    active: bool
    
    def to_dict(self) -> dict:
        return {
            "length": self.length,
            "start_week": self.start_week,
            "end_week": self.end_week,
            "active": self.active,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "StreakRecord":
        # Handle legacy format with "streak" and "weeks" keys
        if "streak" in d:
            length = d.get("streak", 0)
            weeks_str = d.get("weeks", "")
            if weeks_str and "-" in str(weeks_str):
                parts = str(weeks_str).split("-")
                start_week = int(parts[0]) if parts[0] else 0
                end_week = int(parts[1]) if len(parts) > 1 and parts[1] else start_week
            else:
                start_week = 0
                end_week = 0
            return cls(
                length=length,
                start_week=start_week,
                end_week=end_week,
                active=d.get("active", False),
            )
        
        return cls(
            length=d.get("length", 0),
            start_week=d.get("start_week", 0),
            end_week=d.get("end_week", 0),
            active=d.get("active", False),
        )


@dataclass
class RecordUpdate:
    """Describes an update to a record (for Fun Facts)."""
    record_type: str  # e.g., "highest_single_game", "longest_win_streak"
    is_new_record: bool
    current_value: float
    previous_value: Optional[float]
    description: str
    details: dict = field(default_factory=dict)


# =============================================================================
# RECORD TRACKING
# =============================================================================

def check_single_game_record(
    records: dict,
    key: str,
    candidate: SingleGameRecord,
    compare_higher: bool = True,
) -> Optional[RecordUpdate]:
    """
    Check if a candidate beats the current single-game record.
    
    Args:
        records: Current records dict
        key: Record key (e.g., "highest_single_game")
        candidate: Candidate record
        compare_higher: True if higher is better
    
    Returns:
        RecordUpdate if record was broken, None otherwise
    """
    current = records.get("season_records", {}).get(key)
    
    if current is None:
        # First record of this type - initialize
        records.setdefault("season_records", {})[key] = candidate.to_dict()
        return None
    
    current_fp = current.get("fantasy_points", 0)
    
    # For lowest_single_game, negative scores are valid (bad games happen!)
    # Only skip if it's exactly 0 or NaN (likely DNP)
    if not compare_higher and (candidate.fantasy_points == 0 or candidate.fantasy_points != candidate.fantasy_points):
        return None  # Don't count DNP games as "lowest"
    
    is_new_record = (
        (compare_higher and candidate.fantasy_points > current_fp) or
        (not compare_higher and candidate.fantasy_points < current_fp)
    )
    
    if is_new_record:
        records["season_records"][key] = candidate.to_dict()
        return RecordUpdate(
            record_type=key,
            is_new_record=True,
            current_value=candidate.fantasy_points,
            previous_value=current_fp,
            description=f"New {key.replace('_', ' ')}",
            details=candidate.to_dict(),
        )
    
    return None


def check_weekly_team_record(
    records: dict,
    key: str,
    candidate: WeeklyTeamRecord,
    compare_higher: bool = True,
) -> Optional[RecordUpdate]:
    """Check if a candidate beats the current weekly team record."""
    current = records.get("season_records", {}).get(key)
    
    if current is None:
        records.setdefault("season_records", {})[key] = candidate.to_dict()
        return RecordUpdate(
            record_type=key,
            is_new_record=True,
            current_value=candidate.score,
            previous_value=None,
            description=f"First {key.replace('_', ' ')} set",
            details=candidate.to_dict(),
        )
    
    current_score = current.get("score", 0)
    
    is_new_record = (
        (compare_higher and candidate.score > current_score) or
        (not compare_higher and candidate.score < current_score)
    )
    
    if is_new_record:
        records["season_records"][key] = candidate.to_dict()
        return RecordUpdate(
            record_type=key,
            is_new_record=True,
            current_value=candidate.score,
            previous_value=current_score,
            description=f"New {key.replace('_', ' ')}",
            details=candidate.to_dict(),
        )
    
    return None


def _initialize_streak_tracking(records: dict) -> None:
    """
    Initialize streak tracking structures if they don't exist.
    
    MIGRATION: Converts old format to new format if needed.
    
    Old format:
      - current_win_streak: {manager: int}
      - current_loss_streak: {manager: int}
      - longest_win_streak: {manager: {length, week_ended}}
      - longest_loss_streak: {manager: {length, week_ended}}
    
    New format:
      - current_streaks: {manager: {win: int, loss: int}}
      - season_longest_win_streak: {manager: {length, start_week, end_week, active}}
      - season_longest_loss_streak: {manager: {length, start_week, end_week, active}}
    """
    sr = records.setdefault("season_records", {})
    
    # Migrate old format to new format if needed
    if "current_win_streak" in sr and "current_streaks" not in sr:
        # Old format exists, migrate it
        old_win = sr.get("current_win_streak", {})
        old_loss = sr.get("current_loss_streak", {})
        
        sr["current_streaks"] = {}
        for m in MANAGERS:
            sr["current_streaks"][m] = {
                "win": old_win.get(m, 0),
                "loss": old_loss.get(m, 0),
            }
        
        # Clean up old keys
        sr.pop("current_win_streak", None)
        sr.pop("current_loss_streak", None)
    
    # Migrate longest win streak
    if "longest_win_streak" in sr and "season_longest_win_streak" not in sr:
        old_longest = sr.get("longest_win_streak", {})
        sr["season_longest_win_streak"] = {}
        
        for m in MANAGERS:
            old = old_longest.get(m, {})
            if isinstance(old, dict):
                length = old.get("length", old.get("streak", 0))
                # Try to infer start_week from week_ended and length
                end_week = old.get("week_ended", old.get("end_week"))
                start_week = old.get("start_week")
                if end_week and length and not start_week:
                    start_week = end_week - length + 1
                
                sr["season_longest_win_streak"][m] = {
                    "length": length,
                    "start_week": start_week,
                    "end_week": end_week,
                    "active": old.get("active", False),
                }
            else:
                sr["season_longest_win_streak"][m] = {
                    "length": 0, "start_week": None, "end_week": None, "active": False
                }
        
        sr.pop("longest_win_streak", None)
    
    # Migrate longest loss streak
    if "longest_loss_streak" in sr and "season_longest_loss_streak" not in sr:
        old_longest = sr.get("longest_loss_streak", {})
        sr["season_longest_loss_streak"] = {}
        
        for m in MANAGERS:
            old = old_longest.get(m, {})
            if isinstance(old, dict):
                length = old.get("length", old.get("streak", 0))
                end_week = old.get("week_ended", old.get("end_week"))
                start_week = old.get("start_week")
                if end_week and length and not start_week:
                    start_week = end_week - length + 1
                
                sr["season_longest_loss_streak"][m] = {
                    "length": length,
                    "start_week": start_week,
                    "end_week": end_week,
                    "active": old.get("active", False),
                }
            else:
                sr["season_longest_loss_streak"][m] = {
                    "length": 0, "start_week": None, "end_week": None, "active": False
                }
        
        sr.pop("longest_loss_streak", None)
    
    # Initialize new structures if they still don't exist
    if "current_streaks" not in sr:
        sr["current_streaks"] = {
            m: {"win": 0, "loss": 0} for m in MANAGERS
        }
    
    if "season_longest_win_streak" not in sr:
        sr["season_longest_win_streak"] = {
            m: {"length": 0, "start_week": None, "end_week": None, "active": False}
            for m in MANAGERS
        }
    
    if "season_longest_loss_streak" not in sr:
        sr["season_longest_loss_streak"] = {
            m: {"length": 0, "start_week": None, "end_week": None, "active": False}
            for m in MANAGERS
        }


def update_streaks(
    records: dict,
    week: int,
    matchup_results: list[MatchupStats],
) -> list[RecordUpdate]:
    """
    Update win/loss streaks based on weekly results.
    
    FIXED LOGIC:
    1. Update current_streaks based on this week's results
    2. Compare current streak to season_longest_streak
    3. Only update season_longest if current EXCEEDS it (not equals)
    4. Track start/end weeks properly
    
    Returns list of RecordUpdates for any streak records broken.
    """
    updates = []
    
    # Initialize tracking structures
    _initialize_streak_tracking(records)
    
    sr = records["season_records"]
    current_streaks = sr["current_streaks"]
    longest_win = sr["season_longest_win_streak"]
    longest_loss = sr["season_longest_loss_streak"]
    
    # Process each matchup
    for matchup in matchup_results:
        winner = matchup.winner
        if winner is None:
            continue  # Tie - no streak changes
        
        loser = matchup.manager_a if winner == matchup.manager_b else matchup.manager_b
        
        # --- WINNER PROCESSING ---
        # Extend win streak, reset loss streak
        prev_win_streak = current_streaks[winner]["win"]
        current_streaks[winner]["win"] = prev_win_streak + 1
        current_streaks[winner]["loss"] = 0
        
        new_win_streak = current_streaks[winner]["win"]
        
        # Check if this is a new season record
        prev_longest = longest_win[winner].get("length", 0)
        
        # FIXED: Only update if current EXCEEDS previous (strictly greater)
        if new_win_streak > prev_longest:
            start_week = week - new_win_streak + 1
            longest_win[winner] = {
                "length": new_win_streak,
                "start_week": start_week,
                "end_week": week,
                "active": True,
            }
            updates.append(RecordUpdate(
                record_type="longest_win_streak",
                is_new_record=True,
                current_value=new_win_streak,
                previous_value=prev_longest if prev_longest > 0 else None,
                description=f"{winner} sets new season win streak record at {new_win_streak}",
                details={"manager": winner, "weeks": f"{start_week}-{week}"},
            ))
        elif new_win_streak == prev_longest and longest_win[winner].get("active"):
            # Tying their own active record - just update end_week
            longest_win[winner]["end_week"] = week
        
        # --- LOSER PROCESSING ---
        # Extend loss streak, reset win streak
        prev_loss_streak = current_streaks[loser]["loss"]
        current_streaks[loser]["loss"] = prev_loss_streak + 1
        current_streaks[loser]["win"] = 0
        
        new_loss_streak = current_streaks[loser]["loss"]
        
        # Mark any active win streak as no longer active
        if longest_win[loser].get("active"):
            longest_win[loser]["active"] = False
        
        # Check if this is a new season loss streak record
        prev_longest_loss = longest_loss[loser].get("length", 0)
        
        if new_loss_streak > prev_longest_loss:
            start_week = week - new_loss_streak + 1
            longest_loss[loser] = {
                "length": new_loss_streak,
                "start_week": start_week,
                "end_week": week,
                "active": True,
            }
            updates.append(RecordUpdate(
                record_type="longest_loss_streak",
                is_new_record=True,
                current_value=new_loss_streak,
                previous_value=prev_longest_loss if prev_longest_loss > 0 else None,
                description=f"{loser} extends loss streak to {new_loss_streak}",
                details={"manager": loser, "weeks": f"{start_week}-{week}"},
            ))
        elif new_loss_streak == prev_longest_loss and longest_loss[loser].get("active"):
            longest_loss[loser]["end_week"] = week
        
        # Mark any active loss streak for winner as no longer active
        if longest_loss[winner].get("active"):
            longest_loss[winner]["active"] = False
    
    return updates


def update_h2h_records(
    records: dict,
    matchup_results: list[MatchupStats],
    week: int = None,
) -> None:
    """Update head-to-head season records.

    DESIGN CHOICE (consistent with get_manager_record() and career W-L):
    Playoff weeks (week > REGULAR_SEASON_WEEKS) are NOT counted toward the
    H2H season series. Previously, playoff matchups inflated the season
    series (e.g., "Nick leads Hayden 6-2") while the report card showed
    regular-season-only records. This made the same report self-inconsistent.

    If `week` is None, the guard is skipped (back-compat for callers that
    haven't yet been updated, e.g. historical backfills).
    """
    if week is not None and week > REGULAR_SEASON_WEEKS:
        # Playoff week: skip H2H accumulation entirely.
        return

    h2h = records.setdefault("h2h_season", {})

    for matchup in matchup_results:
        winner = matchup.winner
        if winner is None:
            continue

        loser = matchup.manager_a if winner == matchup.manager_b else matchup.manager_b

        # Create canonical key (alphabetically sorted)
        managers_sorted = sorted([matchup.manager_a, matchup.manager_b])
        key = f"{managers_sorted[0]}_vs_{managers_sorted[1]}"

        if key not in h2h:
            h2h[key] = {managers_sorted[0].lower(): 0, managers_sorted[1].lower(): 0}

        h2h[key][winner.lower()] = h2h[key].get(winner.lower(), 0) + 1


def update_all_time_records(
    records: dict,
    matchup_results: list[MatchupStats],
    manager_scores: dict[str, float],
    week: int,
    season: str = None,
) -> None:
    """
    Update all-time historical records based on this week's results.

    Updates:
    - all_time.h2h: Head-to-head records between managers (REGULAR SEASON ONLY)
    - all_time.manager_careers: Total wins/losses (REGULAR SEASON ONLY),
      total points scored (ALL weeks, including playoffs), win %
    - all_time.highest_weekly_score / lowest_weekly_score (ALL weeks)
    - all_time.biggest_blowout / closest_game (ALL weeks)

    DESIGN CHOICE: Career W-L and H2H exclude playoff weeks so the same
    report is internally consistent with get_manager_record() (which is
    regular-season only). Total points scored, weekly highs/lows, and
    blowout/closest records still include playoff games -- those are
    "best ever performance" records that should reflect all games played.
    """
    if season is None:
        season = CURRENT_SEASON
    all_time = records.setdefault("all_time", {})

    is_regular_season = week <= REGULAR_SEASON_WEEKS

    # Update all-time H2H -- regular season only (matches season H2H and
    # get_manager_record()).
    if is_regular_season:
        h2h = all_time.setdefault("h2h", {})
        for matchup in matchup_results:
            winner = matchup.winner
            if winner is None:
                continue

            loser = matchup.manager_a if winner == matchup.manager_b else matchup.manager_b
            managers_sorted = sorted([matchup.manager_a, matchup.manager_b])
            key = f"{managers_sorted[0]}_vs_{managers_sorted[1]}"

            if key not in h2h:
                h2h[key] = {managers_sorted[0].lower(): 0, managers_sorted[1].lower(): 0}

            h2h[key][winner.lower()] = h2h[key].get(winner.lower(), 0) + 1

    # Update manager careers W-L -- regular season only.
    careers = all_time.setdefault("manager_careers", {})
    if is_regular_season:
        for matchup in matchup_results:
            winner = matchup.winner
            if winner is None:
                continue

            loser = matchup.manager_a if winner == matchup.manager_b else matchup.manager_b

            # Update winner
            if winner not in careers:
                careers[winner] = {"total_wins": 0, "total_losses": 0, "total_points_scored": 0, "win_pct": 0}
            careers[winner]["total_wins"] = careers[winner].get("total_wins", 0) + 1

            # Update loser
            if loser not in careers:
                careers[loser] = {"total_wins": 0, "total_losses": 0, "total_points_scored": 0, "win_pct": 0}
            careers[loser]["total_losses"] = careers[loser].get("total_losses", 0) + 1

    # Update total points (ALL weeks -- playoff points are still real points)
    # and recompute win % from career W-L totals.
    for manager, score in manager_scores.items():
        if manager not in careers:
            careers[manager] = {"total_wins": 0, "total_losses": 0, "total_points_scored": 0, "win_pct": 0}
        careers[manager]["total_points_scored"] = careers[manager].get("total_points_scored", 0) + score

        # Recalc win % (denominator is regular-season-only W+L)
        total_games = careers[manager]["total_wins"] + careers[manager]["total_losses"]
        if total_games > 0:
            careers[manager]["win_pct"] = round(
                (careers[manager]["total_wins"] / total_games) * 100, 1
            )
    
    # Update highest/lowest weekly scores
    for matchup in matchup_results:
        scores = [
            (matchup.manager_a, matchup.score_a),
            (matchup.manager_b, matchup.score_b),
        ]
        
        for manager, score in scores:
            # Highest weekly
            current_high = all_time.get("highest_weekly_score", {})
            if not current_high or score > current_high.get("score", 0):
                all_time["highest_weekly_score"] = {
                    "manager": manager,
                    "score": score,
                    "week": week,
                    "season": season,
                }
            
            # Lowest weekly (must have actual score > 0)
            if score > 0:
                current_low = all_time.get("lowest_weekly_score", {})
                if not current_low or score < current_low.get("score", float("inf")):
                    all_time["lowest_weekly_score"] = {
                        "manager": manager,
                        "score": score,
                        "week": week,
                        "season": season,
                    }
    
    # Update biggest blowout / closest game
    for matchup in matchup_results:
        if matchup.winner is None:
            continue
        
        margin = matchup.margin
        
        # Biggest blowout
        current_blowout = all_time.get("biggest_blowout", {})
        if not current_blowout or margin > current_blowout.get("margin", 0):
            all_time["biggest_blowout"] = {
                "winner": matchup.winner,
                "loser": matchup.manager_a if matchup.winner == matchup.manager_b else matchup.manager_b,
                "margin": margin,
                "week": week,
                "season": season,
            }
        
        # Closest game
        current_closest = all_time.get("closest_game", {})
        if not current_closest or margin < current_closest.get("margin", float("inf")):
            all_time["closest_game"] = {
                "winner": matchup.winner,
                "loser": matchup.manager_a if matchup.winner == matchup.manager_b else matchup.manager_b,
                "margin": margin,
                "week": week,
                "season": season,
            }


def update_weekly_scores(
    records: dict,
    week: int,
    manager_scores: dict[str, float],
) -> None:
    """
    Store weekly scores for historical tracking.
    
    Handles two formats:
    - Old format: {manager: [{week, score}, ...]} (per-manager lists)
    - New format: [{week, scores: {manager: score}}] (per-week list)
    
    We'll use the old format if it exists, otherwise new format.
    """
    weekly_scores = records.get("weekly_scores", {})
    
    # Check if it's the old format (dict with manager keys)
    if isinstance(weekly_scores, dict) and any(m in weekly_scores for m in MANAGERS):
        # Old format - update each manager's list
        for manager, score in manager_scores.items():
            if manager not in weekly_scores:
                weekly_scores[manager] = []
            
            # Remove existing entry for this week
            weekly_scores[manager] = [
                w for w in weekly_scores[manager] 
                if w.get("week") != week
            ]
            
            weekly_scores[manager].append({
                "week": week,
                "score": score,
            })
            
            # Sort by week
            weekly_scores[manager].sort(key=lambda x: x.get("week", 0))
    else:
        # New format - list of {week, scores}
        if not isinstance(weekly_scores, list):
            weekly_scores = []
        
        # Remove existing entry for this week
        weekly_scores = [w for w in weekly_scores if w.get("week") != week]
        
        weekly_scores.append({
            "week": week,
            "scores": manager_scores.copy(),
        })
        
        weekly_scores = sorted(weekly_scores, key=lambda x: x.get("week", 0))
    
    records["weekly_scores"] = weekly_scores


def update_title_odds_history(
    records: dict,
    week: int,
    title_odds: dict[str, float],
) -> None:
    """Store title odds for trend tracking.

    Handles the case where an older RECORDS.json has the key present with
    value ``None`` -- ``setdefault`` would return ``None`` and the assignment
    below would crash. Coerce to a dict explicitly.
    """
    history = records.get("title_odds_history")
    if not isinstance(history, dict):
        history = {}
        records["title_odds_history"] = history
    history[f"week_{week}"] = title_odds.copy()


def update_cumulative_bench_points(
    records: dict,
    bench_points: dict[str, float],
) -> None:
    """Update cumulative bench points left on table."""
    cumulative = records.setdefault("cumulative_bench_points", {m: 0.0 for m in MANAGERS})
    for manager, points in bench_points.items():
        cumulative[manager] = cumulative.get(manager, 0.0) + points


def update_cumulative_blunders(
    records: dict,
    blunders: dict[str, int],
    week: int,
) -> None:
    """Update cumulative blunder counts and single-week high.
    
    Blunders are bench games where a starter slot was available (empty or DNP).
    Tracks both season totals and worst single-week blunder counts per manager.
    """
    # Season totals
    cumulative = records.setdefault("cumulative_blunders", {m: 0 for m in MANAGERS})
    for manager, count in blunders.items():
        cumulative[manager] = cumulative.get(manager, 0) + count
    
    # Single-week high per manager
    weekly_high = records.setdefault("single_week_blunders_high", {
        m: {"count": 0, "week": 0} for m in MANAGERS
    })
    for manager, count in blunders.items():
        current = weekly_high.get(manager, {"count": 0, "week": 0})
        if count > current["count"]:
            weekly_high[manager] = {"count": count, "week": week}


def update_season_fppg_stats(
    records: dict,
    week: int,
    report: "WeeklyReport",
    data: "FantasyData" = None,
) -> None:
    """
    Update season-long FPPG stats (team and positional).
    """
    season_stats = records.setdefault("season_fppg_stats", {})
    
    for manager, ms in report.manager_stats.items():
        mgr_stats = season_stats.setdefault(manager, {
            "total_fp": 0.0,
            "total_games": 0,
            "fppg": 0.0,
            "last_updated_week": 0,
        })
        
        # Add this week's stats
        mgr_stats["total_fp"] += ms.total_fp
        mgr_stats["total_games"] += ms.total_healthy_starter_games
        
        if mgr_stats["total_games"] > 0:
            mgr_stats["fppg"] = round(mgr_stats["total_fp"] / mgr_stats["total_games"], 2)
        
        # Update positional stats
        pos_stats = mgr_stats.setdefault("positional", {
            "guard": {"total_fp": 0.0, "games": 0, "fppg": 0.0},
            "forward": {"total_fp": 0.0, "games": 0, "fppg": 0.0},
            "center": {"total_fp": 0.0, "games": 0, "fppg": 0.0},
        })
        
        # Guard
        pos_stats["guard"]["total_fp"] += ms.guard_stats.total_fp
        pos_stats["guard"]["games"] += ms.guard_stats.games
        if pos_stats["guard"]["games"] > 0:
            pos_stats["guard"]["fppg"] = round(pos_stats["guard"]["total_fp"] / pos_stats["guard"]["games"], 2)
        
        # Forward
        pos_stats["forward"]["total_fp"] += ms.forward_stats.total_fp
        pos_stats["forward"]["games"] += ms.forward_stats.games
        if pos_stats["forward"]["games"] > 0:
            pos_stats["forward"]["fppg"] = round(pos_stats["forward"]["total_fp"] / pos_stats["forward"]["games"], 2)
        
        # Center
        pos_stats["center"]["total_fp"] += ms.center_stats.total_fp
        pos_stats["center"]["games"] += ms.center_stats.games
        if pos_stats["center"]["games"] > 0:
            pos_stats["center"]["fppg"] = round(pos_stats["center"]["total_fp"] / pos_stats["center"]["games"], 2)
        
        mgr_stats["last_updated_week"] = week


# =============================================================================
# TOP-10 LEADERBOARD UTILITIES
# =============================================================================


def update_top10_list(
    top10_list: list,
    new_entry: dict,
    key_field: str,
    reverse: bool = True,
) -> bool:
    """
    Insert an entry into a top-10 leaderboard list if it qualifies.

    Deduplicates before inserting: if an existing entry matches the same
    identity (same combination of player/manager/date/season/week fields),
    it is removed first so the record appears only once.

    Args:
        top10_list: Existing sorted list (up to 10 entries). Modified in place.
        new_entry: New entry dict to potentially insert.
        key_field: Field name to sort by (e.g., 'fantasy_points', 'score').
        reverse: True for highest-first records, False for lowest-first.

    Returns:
        True if the entry was inserted (qualified for top 10), False otherwise.
    """
    new_val = new_entry.get(key_field, 0)

    # Build identity tuple from all common fields (covers both player-game
    # and team-matchup record types). Fields absent from an entry become None,
    # so two entries only collide when every present field matches.
    _DEDUP_FIELDS = (
        "player_name", "date", "season", "week",
        "manager", "manager_a", "manager_b",
        # winner/loser identify team-matchup entries (blowout/closest game);
        # without them, two different matchups in the same (season, week)
        # collided and evicted each other from the top-10.
        "winner", "loser",
    )
    new_identity = tuple(new_entry.get(f) for f in _DEDUP_FIELDS)

    # Remove any existing entry with the same identity
    top10_list[:] = [
        e for e in top10_list
        if tuple(e.get(f) for f in _DEDUP_FIELDS) != new_identity
    ]

    # Check if it qualifies (re-check after possible removal shrank list)
    if len(top10_list) >= 10:
        worst = top10_list[-1].get(key_field, 0)
        if reverse and new_val <= worst:
            return False
        if not reverse and new_val >= worst:
            return False

    top10_list.append(new_entry)
    top10_list.sort(key=lambda x: x.get(key_field, 0), reverse=reverse)
    while len(top10_list) > 10:
        top10_list.pop()

    return True


def _normalize_season(s: str) -> str:
    """Normalize season string to YYYY-YY."""
    s = str(s).strip()
    if len(s) >= 9 and s[4] == "-":
        return f"{s[:4]}-{s[-2:]}"
    return s


def check_alltime_single_game_top10(
    records: dict,
    player_name: str,
    manager: str,
    fantasy_points: float,
    date_str: str,
    season: str,
    week: int,
    rookie_seasons: dict = None,
) -> list:
    """
    Check if a single-game performance qualifies for any all-time top-10 lists.

    Checks highest_single_game_top10, lowest_single_game_top10,
    and best_rookie_single_game_top10 (if player is a rookie this season).
    Also updates the single-record keys if a new #1 is set.

    Returns:
        List of description strings for any records broken.
    """
    all_time = records.setdefault("all_time", {})
    updates = []

    entry = {
        "player_name": player_name,
        "manager": manager,
        "fantasy_points": round(fantasy_points, 2),
        "date": date_str,
        "season": season,
        "week": week,
    }

    # Highest single game top-10
    high_top10 = all_time.setdefault("highest_single_game_top10", [])
    if update_top10_list(high_top10, dict(entry), "fantasy_points", reverse=True):
        if high_top10 and high_top10[0].get("fantasy_points") == round(fantasy_points, 2):
            all_time["highest_single_game"] = dict(entry)
            updates.append(
                f"New all-time highest single game: {fantasy_points:.2f} by {player_name} ({manager})"
            )

    # Lowest single game top-10 (include negatives, skip exact 0 / DNPs)
    if fantasy_points != 0:
        low_top10 = all_time.setdefault("lowest_single_game_top10", [])
        if update_top10_list(low_top10, dict(entry), "fantasy_points", reverse=False):
            if low_top10 and low_top10[0].get("fantasy_points") == round(fantasy_points, 2):
                all_time["lowest_single_game"] = dict(entry)
                updates.append(
                    f"New all-time lowest single game: {fantasy_points:.2f} by {player_name} ({manager})"
                )

    # Rookie single game top-10
    if rookie_seasons and player_name in rookie_seasons:
        debut = rookie_seasons[player_name]
        if _normalize_season(season) == _normalize_season(debut):
            rookie_top10 = all_time.setdefault("best_rookie_single_game_top10", [])
            if update_top10_list(rookie_top10, dict(entry), "fantasy_points", reverse=True):
                if rookie_top10 and rookie_top10[0].get("fantasy_points") == round(fantasy_points, 2):
                    all_time["best_rookie_single_game"] = dict(entry)
                    updates.append(
                        f"New all-time best rookie single game: {fantasy_points:.2f} by {player_name}"
                    )

    return updates


def update_season_player_records(
    records: dict,
    playerlog_df,  # pd.DataFrame
    week: int,
    rookie_seasons: dict = None,
) -> list:
    """
    Recompute all season-level player records from current playerlog data.

    Called each week to keep season records current. Computes:
      - best_season_fppg (min 30 GP), best_season_total_fp
      - most_fp_single_week
      - best_rookie_single_game, best_rookie_season_fppg, best_rookie_season_total_fp, best_rookie_fantasy_week

    Returns:
        List of description strings for any notable updates.
    """
    import pandas as pd

    season_recs = records.setdefault("season_records", {})
    updates = []

    if playerlog_df is None or playerlog_df.empty:
        return updates

    # Filter to started games with valid FP (exclude 0 FP injury DNPs)
    df = playerlog_df.copy()
    mask = df["fantasy_points"].notna() & (df["fantasy_points"] > 0)
    if "started" in df.columns:
        mask = mask & (df["started"] == True)
    if "nba_opponent" in df.columns:
        mask = mask & df["nba_opponent"].notna()
    df = df[mask]

    if df.empty:
        return updates

    MIN_GP = 30

    # --- Best Season FPPG ---
    player_stats = df.groupby(["player_name", "manager"]).agg(
        total_fp=("fantasy_points", "sum"),
        gp=("fantasy_points", "count"),
    ).reset_index()
    player_stats["fppg"] = (player_stats["total_fp"] / player_stats["gp"]).round(2)

    qualified = player_stats[player_stats["gp"] >= MIN_GP]
    if not qualified.empty:
        best = qualified.loc[qualified["fppg"].idxmax()]
        season_recs["best_season_fppg"] = {
            "player_name": str(best["player_name"]),
            "manager": str(best["manager"]),
            "fppg": float(best["fppg"]),
            "gp": int(best["gp"]),
            "total_fp": round(float(best["total_fp"]), 1),
        }

    # --- Best Season Total FP ---
    if not player_stats.empty:
        best_total = player_stats.loc[player_stats["total_fp"].idxmax()]
        season_recs["best_season_total_fp"] = {
            "player_name": str(best_total["player_name"]),
            "manager": str(best_total["manager"]),
            "total_fp": round(float(best_total["total_fp"]), 1),
            "gp": int(best_total["gp"]),
            "fppg": round(float(best_total["total_fp"]) / int(best_total["gp"]), 2) if int(best_total["gp"]) > 0 else 0,
        }

    # --- Most FP in Single Week ---
    weekly = df.groupby(["player_name", "manager", "week"]).agg(
        weekly_fp=("fantasy_points", "sum"),
        games=("fantasy_points", "count"),
    ).reset_index()

    if not weekly.empty:
        best_week = weekly.loc[weekly["weekly_fp"].idxmax()]
        season_recs["most_fp_single_week"] = {
            "player_name": str(best_week["player_name"]),
            "manager": str(best_week["manager"]),
            "weekly_fp": round(float(best_week["weekly_fp"]), 2),
            "games": int(best_week["games"]),
            "week": int(best_week["week"]),
        }

    # --- Best / Worst Collective Team Game (single day) ---
    # Starters who actually played (FP > 0) on a given date
    if "date" in df.columns:
        played = df[df["fantasy_points"] > 0]
        day_team = played.groupby(["manager", "date"]).agg(
            total_fp=("fantasy_points", "sum"),
            starters=("fantasy_points", "count"),
            avg_fp=("fantasy_points", "mean"),
        ).reset_index()
        day_team = day_team[day_team["starters"] >= 5]  # min 5 starters

        if not day_team.empty:
            # Best
            best_day = day_team.loc[day_team["avg_fp"].idxmax()]
            # Find the week for this date
            date_week = df.loc[df["date"] == best_day["date"], "week"]
            wk = int(date_week.iloc[0]) if not date_week.empty else 0
            season_recs["best_collective_team_game"] = {
                "manager": str(best_day["manager"]),
                "avg_fp": round(float(best_day["avg_fp"]), 1),
                "total_fp": round(float(best_day["total_fp"]), 1),
                "starters": int(best_day["starters"]),
                "date": str(best_day["date"]),
                "week": wk,
            }
            # Worst
            worst_day = day_team.loc[day_team["avg_fp"].idxmin()]
            date_week = df.loc[df["date"] == worst_day["date"], "week"]
            wk = int(date_week.iloc[0]) if not date_week.empty else 0
            season_recs["worst_collective_team_game"] = {
                "manager": str(worst_day["manager"]),
                "avg_fp": round(float(worst_day["avg_fp"]), 1),
                "total_fp": round(float(worst_day["total_fp"]), 1),
                "starters": int(worst_day["starters"]),
                "date": str(worst_day["date"]),
                "week": wk,
            }

    # --- Best Combined Duo Output (single week) ---
    # Top 2 players per manager per week
    player_weekly = df.groupby(["manager", "week", "player_name"]).agg(
        weekly_fp=("fantasy_points", "sum"),
    ).reset_index()

    duo_records = []
    for (mgr, wk), grp in player_weekly.groupby(["manager", "week"]):
        if len(grp) < 2:
            continue
        top2 = grp.nlargest(2, "weekly_fp")
        rows = top2.values.tolist()  # each: [manager, week, player_name, weekly_fp]
        p1_name, p1_fp = str(top2.iloc[0]["player_name"]), float(top2.iloc[0]["weekly_fp"])
        p2_name, p2_fp = str(top2.iloc[1]["player_name"]), float(top2.iloc[1]["weekly_fp"])
        duo_records.append({
            "manager": str(mgr),
            "week": int(wk),
            "combined_fp": round(p1_fp + p2_fp, 1),
            "player1": p1_name, "player1_fp": round(p1_fp, 1),
            "player2": p2_name, "player2_fp": round(p2_fp, 1),
        })

    if duo_records:
        best_duo = max(duo_records, key=lambda x: x["combined_fp"])
        season_recs["best_duo_output"] = best_duo

    # --- Most Players with 45+ FP in a Single Week ---
    hot_counts = []
    for (mgr, wk), grp in player_weekly.groupby(["manager", "week"]):
        over_45 = grp[grp["weekly_fp"] >= 45]
        if len(over_45) >= 3:
            hot_counts.append({
                "manager": str(mgr),
                "week": int(wk),
                "count": int(len(over_45)),
            })

    if hot_counts:
        best_hot = max(hot_counts, key=lambda x: x["count"])
        season_recs["most_45plus_fp_week"] = best_hot

    # --- Biggest Single-Game Outperformance vs Season Avg ---
    # Need per-player season avg, then compare each game
    if not player_stats.empty:
        avg_lookup = player_stats.set_index(["player_name", "manager"])["fppg"].to_dict()
        min_gp_for_avg = 10  # need enough games for meaningful average
        qual_players = player_stats[player_stats["gp"] >= min_gp_for_avg]
        qual_set = set(zip(qual_players["player_name"], qual_players["manager"]))

        outperformances = []
        for _, row in df.iterrows():
            key = (row["player_name"], row["manager"])
            if key not in qual_set:
                continue
            avg = avg_lookup.get(key, 0)
            if avg <= 0:
                continue
            delta = float(row["fantasy_points"]) - avg
            if delta > 0:
                outperformances.append({
                    "player_name": str(row["player_name"]),
                    "manager": str(row["manager"]),
                    "game_fp": round(float(row["fantasy_points"]), 2),
                    "season_avg": round(avg, 2),
                    "delta": round(delta, 1),
                    "date": str(row.get("date", "")),
                    "week": int(row.get("week", 0)),
                })

        if outperformances:
            best_op = max(outperformances, key=lambda x: x["delta"])
            season_recs["biggest_outperformance"] = best_op

    # --- Most Consistent Player (lowest std dev, min 30 GP) ---
    if not qualified.empty:
        import statistics as _stats
        consistency_records = []
        for _, row in qualified.iterrows():
            pname, mgr = str(row["player_name"]), str(row["manager"])
            mask_p = (df["player_name"] == pname) & (df["manager"] == mgr)
            fps = df.loc[mask_p, "fantasy_points"].tolist()
            if len(fps) >= MIN_GP:
                std = round(_stats.stdev(fps), 2)
                avg = round(sum(fps) / len(fps), 1)
                consistency_records.append({
                    "player_name": pname,
                    "manager": mgr,
                    "std_dev": std,
                    "avg_fp": avg,
                    "gp": len(fps),
                })

        if consistency_records:
            best_con = min(consistency_records, key=lambda x: x["std_dev"])
            season_recs["most_consistent_player"] = best_con

    # --- Garbage Time King (most starts under 15 FP, min 20 starts) ---
    starters_with_fp = df[df["fantasy_points"] > 0]
    if not starters_with_fp.empty:
        garbage_stats = starters_with_fp.groupby(["player_name", "manager"]).apply(
            lambda g: pd.Series({
                "under_15_count": int((g["fantasy_points"] < 15).sum()),
                "total_starts": int(len(g)),
            })
        ).reset_index()
        garbage_qual = garbage_stats[garbage_stats["total_starts"] >= 20]

        if not garbage_qual.empty:
            garbage_qual = garbage_qual.copy()
            garbage_qual["pct"] = (
                garbage_qual["under_15_count"] / garbage_qual["total_starts"] * 100
            ).round(1)
            best_garbage = garbage_qual.loc[garbage_qual["under_15_count"].idxmax()]
            season_recs["garbage_time_king"] = {
                "player_name": str(best_garbage["player_name"]),
                "manager": str(best_garbage["manager"]),
                "under_15_count": int(best_garbage["under_15_count"]),
                "total_starts": int(best_garbage["total_starts"]),
                "pct": float(best_garbage["pct"]),
            }

    # --- Mr. Monday Night (highest avg FP on Mondays, min 5 games) ---
    if "date" in df.columns:
        played = df[df["fantasy_points"] > 0].copy()
        played["day_of_week"] = pd.to_datetime(played["date"]).dt.dayofweek
        mondays = played[played["day_of_week"] == 0]

        if not mondays.empty:
            mon_stats = mondays.groupby(["player_name", "manager"]).agg(
                avg_fp=("fantasy_points", "mean"),
                monday_games=("fantasy_points", "count"),
            ).reset_index()
            mon_qual = mon_stats[mon_stats["monday_games"] >= 5]

            if not mon_qual.empty:
                best_mon = mon_qual.loc[mon_qual["avg_fp"].idxmax()]
                season_recs["mr_monday_night"] = {
                    "player_name": str(best_mon["player_name"]),
                    "manager": str(best_mon["manager"]),
                    "avg_fp": round(float(best_mon["avg_fp"]), 1),
                    "monday_games": int(best_mon["monday_games"]),
                }

    # --- Rookie Records ---
    current_season = CURRENT_SEASON
    if rookie_seasons:
        rookie_mask = df["player_name"].apply(
            lambda name: _normalize_season(
                rookie_seasons.get(str(name), "")
            ) == current_season
        )
        rookie_df = df[rookie_mask]

        if not rookie_df.empty:
            # Best rookie single game
            best_rsg = rookie_df.loc[rookie_df["fantasy_points"].idxmax()]
            season_recs["best_rookie_single_game"] = {
                "player_name": str(best_rsg["player_name"]),
                "manager": str(best_rsg["manager"]),
                "fantasy_points": round(float(best_rsg["fantasy_points"]), 2),
                "date": str(best_rsg.get("date", "")),
                "week": int(best_rsg.get("week", 0)),
            }

            # Best rookie season FPPG
            r_stats = rookie_df.groupby(["player_name", "manager"]).agg(
                total_fp=("fantasy_points", "sum"),
                gp=("fantasy_points", "count"),
            ).reset_index()
            r_stats["fppg"] = (r_stats["total_fp"] / r_stats["gp"]).round(2)
            r_qual = r_stats[r_stats["gp"] >= MIN_GP]
            if not r_qual.empty:
                best_rf = r_qual.loc[r_qual["fppg"].idxmax()]
                season_recs["best_rookie_season_fppg"] = {
                    "player_name": str(best_rf["player_name"]),
                    "manager": str(best_rf["manager"]),
                    "fppg": float(best_rf["fppg"]),
                    "gp": int(best_rf["gp"]),
                    "total_fp": round(float(best_rf["total_fp"]), 1),
                }

            # Best rookie season total FP
            if not r_stats.empty:
                best_rt = r_stats.loc[r_stats["total_fp"].idxmax()]
                season_recs["best_rookie_season_total_fp"] = {
                    "player_name": str(best_rt["player_name"]),
                    "manager": str(best_rt["manager"]),
                    "total_fp": round(float(best_rt["total_fp"]), 1),
                    "gp": int(best_rt["gp"]),
                    "fppg": round(float(best_rt["total_fp"]) / int(best_rt["gp"]), 2) if int(best_rt["gp"]) > 0 else 0,
                }

            # Best rookie fantasy week
            r_weekly = rookie_df.groupby(["player_name", "manager", "week"]).agg(
                weekly_fp=("fantasy_points", "sum"),
                games=("fantasy_points", "count"),
            ).reset_index()
            if not r_weekly.empty:
                best_rw = r_weekly.loc[r_weekly["weekly_fp"].idxmax()]
                season_recs["best_rookie_fantasy_week"] = {
                    "player_name": str(best_rw["player_name"]),
                    "manager": str(best_rw["manager"]),
                    "weekly_fp": round(float(best_rw["weekly_fp"]), 2),
                    "games": int(best_rw["games"]),
                    "week": int(best_rw["week"]),
                }

    return updates


def update_alltime_weekly_top10s(
    records: dict,
    matchup_results,  # list[MatchupStats]
    manager_scores: dict,
    week: int,
    season: str = None,
) -> None:
    """
    Update all-time team record top-10 leaderboards for this week's results.

    Updates highest/lowest weekly score, biggest blowout, closest game top-10s.
    """
    if season is None:
        season = CURRENT_SEASON
    all_time = records.setdefault("all_time", {})

    for matchup in matchup_results:
        scores = [
            (matchup.manager_a, matchup.score_a),
            (matchup.manager_b, matchup.score_b),
        ]

        for manager, score in scores:
            entry = {
                "score": round(score, 2),
                "manager": manager,
                "season": season,
                "week": week,
            }

            # Highest
            high_top10 = all_time.setdefault("highest_weekly_score_top10", [])
            update_top10_list(high_top10, dict(entry), "score", reverse=True)

            # Lowest (must have score > 0)
            if score > 0:
                low_top10 = all_time.setdefault("lowest_weekly_score_top10", [])
                update_top10_list(low_top10, dict(entry), "score", reverse=False)

        # Blowout / closest
        if matchup.winner:
            loser = (matchup.manager_a
                     if matchup.winner == matchup.manager_b
                     else matchup.manager_b)
            margin_entry = {
                "margin": round(matchup.margin, 2),
                "winner": matchup.winner,
                "loser": loser,
                "season": season,
                "week": week,
            }

            blowout_top10 = all_time.setdefault("biggest_blowout_top10", [])
            update_top10_list(blowout_top10, dict(margin_entry), "margin", reverse=True)

            closest_top10 = all_time.setdefault("closest_game_top10", [])
            update_top10_list(closest_top10, dict(margin_entry), "margin", reverse=False)


def update_alltime_season_fppg_top10(
    records: dict,
    playerlog_df,  # pd.DataFrame
    season: str = None,
    rookie_seasons: dict = None,
) -> None:
    """
    Update all-time season FPPG and weekly FP top-10s with current season data.

    Recomputes the current season's best entries and checks them against
    the all-time leaderboards. Called once per week.
    """
    if season is None:
        season = CURRENT_SEASON
    import pandas as pd

    all_time = records.setdefault("all_time", {})

    if playerlog_df is None or playerlog_df.empty:
        return

    df = playerlog_df.copy()
    mask = df["fantasy_points"].notna() & (df["fantasy_points"] > 0)
    if "started" in df.columns:
        mask = mask & (df["started"] == True)
    if "nba_opponent" in df.columns:
        mask = mask & df["nba_opponent"].notna()
    df = df[mask]

    if df.empty:
        return

    MIN_GP = 30

    # Best Season FPPG
    player_stats = df.groupby(["player_name", "manager"]).agg(
        total_fp=("fantasy_points", "sum"),
        gp=("fantasy_points", "count"),
    ).reset_index()
    player_stats["fppg"] = (player_stats["total_fp"] / player_stats["gp"]).round(2)

    qualified = player_stats[player_stats["gp"] >= MIN_GP]
    fppg_top10 = all_time.setdefault("best_season_fppg_top10", [])

    # Remove existing entries from current season before re-inserting
    fppg_top10[:] = [e for e in fppg_top10 if e.get("season") != season]

    for _, row in qualified.iterrows():
        entry = {
            "player_name": str(row["player_name"]),
            "manager": str(row["manager"]),
            "fppg": float(row["fppg"]),
            "gp": int(row["gp"]),
            "total_fp": round(float(row["total_fp"]), 1),
            "season": season,
        }
        update_top10_list(fppg_top10, entry, "fppg", reverse=True)

    if fppg_top10:
        all_time["best_season_fppg"] = dict(fppg_top10[0])

    # Best Season Total FP
    totalfp_top10 = all_time.setdefault("best_season_total_fp_top10", [])
    totalfp_top10[:] = [e for e in totalfp_top10 if e.get("season") != season]

    for _, row in player_stats.nlargest(20, "total_fp").iterrows():
        entry = {
            "player_name": str(row["player_name"]),
            "manager": str(row["manager"]),
            "total_fp": round(float(row["total_fp"]), 1),
            "gp": int(row["gp"]),
            "fppg": float(row["fppg"]),
            "season": season,
        }
        update_top10_list(totalfp_top10, entry, "total_fp", reverse=True)

    if totalfp_top10:
        all_time["best_season_total_fp"] = dict(totalfp_top10[0])

    # Most FP Single Week
    weekly = df.groupby(["player_name", "manager", "week"]).agg(
        weekly_fp=("fantasy_points", "sum"),
        games=("fantasy_points", "count"),
    ).reset_index()

    week_top10 = all_time.setdefault("most_fp_single_week_top10", [])
    week_top10[:] = [e for e in week_top10 if e.get("season") != season]

    for _, row in weekly.nlargest(20, "weekly_fp").iterrows():
        entry = {
            "player_name": str(row["player_name"]),
            "manager": str(row["manager"]),
            "weekly_fp": round(float(row["weekly_fp"]), 2),
            "games": int(row["games"]),
            "season": season,
            "week": int(row["week"]),
        }
        update_top10_list(week_top10, entry, "weekly_fp", reverse=True)

    if week_top10:
        all_time["most_fp_single_week"] = dict(week_top10[0])

    # Best / Worst Collective Team Game (single day)
    if "date" in df.columns:
        played = df[df["fantasy_points"] > 0]
        day_team = played.groupby(["manager", "date"]).agg(
            total_fp=("fantasy_points", "sum"),
            starters=("fantasy_points", "count"),
            avg_fp=("fantasy_points", "mean"),
        ).reset_index()
        day_team = day_team[day_team["starters"] >= 5]

        if not day_team.empty:
            # Best collective game
            best_cg_top10 = all_time.setdefault("best_collective_team_game_top10", [])
            best_cg_top10[:] = [e for e in best_cg_top10 if e.get("season") != season]
            for _, row in day_team.nlargest(20, "avg_fp").iterrows():
                date_wk = df.loc[df["date"] == row["date"], "week"]
                wk = int(date_wk.iloc[0]) if not date_wk.empty else 0
                entry = {
                    "manager": str(row["manager"]),
                    "avg_fp": round(float(row["avg_fp"]), 1),
                    "total_fp": round(float(row["total_fp"]), 1),
                    "starters": int(row["starters"]),
                    "date": str(row["date"]),
                    "week": wk,
                    "season": season,
                }
                update_top10_list(best_cg_top10, entry, "avg_fp", reverse=True)
            if best_cg_top10:
                all_time["best_collective_team_game"] = dict(best_cg_top10[0])

            # Worst collective game
            worst_cg_top10 = all_time.setdefault("worst_collective_team_game_top10", [])
            worst_cg_top10[:] = [e for e in worst_cg_top10 if e.get("season") != season]
            for _, row in day_team.nsmallest(20, "avg_fp").iterrows():
                date_wk = df.loc[df["date"] == row["date"], "week"]
                wk = int(date_wk.iloc[0]) if not date_wk.empty else 0
                entry = {
                    "manager": str(row["manager"]),
                    "avg_fp": round(float(row["avg_fp"]), 1),
                    "total_fp": round(float(row["total_fp"]), 1),
                    "starters": int(row["starters"]),
                    "date": str(row["date"]),
                    "week": wk,
                    "season": season,
                }
                update_top10_list(worst_cg_top10, entry, "avg_fp", reverse=False)
            if worst_cg_top10:
                all_time["worst_collective_team_game"] = dict(worst_cg_top10[0])

    # Best Combined Duo Output (single week)
    player_weekly = weekly  # already computed: player_name, manager, week, weekly_fp
    duo_top10 = all_time.setdefault("best_duo_output_top10", [])
    duo_top10[:] = [e for e in duo_top10 if e.get("season") != season]

    duo_entries = []
    for (mgr, wk), grp in player_weekly.groupby(["manager", "week"]):
        if len(grp) < 2:
            continue
        top2 = grp.nlargest(2, "weekly_fp")
        p1_name, p1_fp = str(top2.iloc[0]["player_name"]), float(top2.iloc[0]["weekly_fp"])
        p2_name, p2_fp = str(top2.iloc[1]["player_name"]), float(top2.iloc[1]["weekly_fp"])
        duo_entries.append({
            "manager": str(mgr),
            "combined_fp": round(p1_fp + p2_fp, 1),
            "player1": p1_name, "player1_fp": round(p1_fp, 1),
            "player2": p2_name, "player2_fp": round(p2_fp, 1),
            "week": int(wk),
            "season": season,
        })

    duo_entries.sort(key=lambda x: x["combined_fp"], reverse=True)
    for entry in duo_entries[:20]:
        update_top10_list(duo_top10, entry, "combined_fp", reverse=True)
    if duo_top10:
        all_time["best_duo_output"] = dict(duo_top10[0])

    # Most Players with 45+ FP in a Single Week
    hot_top10 = all_time.setdefault("most_45plus_fp_week_top10", [])
    hot_top10[:] = [e for e in hot_top10 if e.get("season") != season]

    hot_entries = []
    for (mgr, wk), grp in player_weekly.groupby(["manager", "week"]):
        over_45 = grp[grp["weekly_fp"] >= 45]
        if len(over_45) >= 3:
            hot_entries.append({
                "manager": str(mgr),
                "count": int(len(over_45)),
                "week": int(wk),
                "season": season,
            })

    hot_entries.sort(key=lambda x: x["count"], reverse=True)
    for entry in hot_entries[:20]:
        update_top10_list(hot_top10, entry, "count", reverse=True)
    if hot_top10:
        all_time["most_45plus_fp_week"] = dict(hot_top10[0])

    # Biggest Single-Game Outperformance vs Season Avg
    outperf_top10 = all_time.setdefault("biggest_outperformance_top10", [])
    outperf_top10[:] = [e for e in outperf_top10 if e.get("season") != season]

    if not player_stats.empty:
        avg_lookup = player_stats.set_index(["player_name", "manager"])["fppg"].to_dict()
        qual_set = set(
            zip(player_stats[player_stats["gp"] >= 10]["player_name"],
                player_stats[player_stats["gp"] >= 10]["manager"])
        )
        op_entries = []
        for _, row in df.iterrows():
            key = (row["player_name"], row["manager"])
            if key not in qual_set:
                continue
            avg = avg_lookup.get(key, 0)
            if avg <= 0:
                continue
            delta = float(row["fantasy_points"]) - avg
            if delta > 15:  # Only consider significant outperformances
                op_entries.append({
                    "player_name": str(row["player_name"]),
                    "manager": str(row["manager"]),
                    "game_fp": round(float(row["fantasy_points"]), 2),
                    "season_avg": round(avg, 2),
                    "delta": round(delta, 1),
                    "date": str(row.get("date", "")),
                    "week": int(row.get("week", 0)),
                    "season": season,
                })

        op_entries.sort(key=lambda x: x["delta"], reverse=True)
        for entry in op_entries[:20]:
            update_top10_list(outperf_top10, entry, "delta", reverse=True)

    if outperf_top10:
        all_time["biggest_outperformance"] = dict(outperf_top10[0])

    # Most Consistent Player (lowest std dev, min 30 GP)
    consist_top10 = all_time.setdefault("most_consistent_player_top10", [])
    consist_top10[:] = [e for e in consist_top10 if e.get("season") != season]

    if not qualified.empty:
        import statistics as _stats
        for _, row in qualified.iterrows():
            pname, mgr = str(row["player_name"]), str(row["manager"])
            mask_p = (df["player_name"] == pname) & (df["manager"] == mgr)
            fps = df.loc[mask_p, "fantasy_points"].tolist()
            if len(fps) >= MIN_GP:
                std = round(_stats.stdev(fps), 2)
                avg = round(sum(fps) / len(fps), 1)
                entry = {
                    "player_name": pname,
                    "manager": mgr,
                    "std_dev": std,
                    "avg_fp": avg,
                    "gp": len(fps),
                    "season": season,
                }
                update_top10_list(consist_top10, entry, "std_dev", reverse=False)

    if consist_top10:
        all_time["most_consistent_player"] = dict(consist_top10[0])

    # Garbage Time King (most starts under 15 FP, min 20 starts)
    garbage_top10 = all_time.setdefault("garbage_time_king_top10", [])
    garbage_top10[:] = [e for e in garbage_top10 if e.get("season") != season]

    starters_with_fp = df[df["fantasy_points"] > 0]
    if not starters_with_fp.empty:
        import pandas as pd
        garbage_stats = starters_with_fp.groupby(["player_name", "manager"]).apply(
            lambda g: pd.Series({
                "under_15_count": int((g["fantasy_points"] < 15).sum()),
                "total_starts": int(len(g)),
            })
        ).reset_index()
        garbage_qual = garbage_stats[garbage_stats["total_starts"] >= 20]

        if not garbage_qual.empty:
            garbage_qual = garbage_qual.copy()
            garbage_qual["pct"] = (
                garbage_qual["under_15_count"] / garbage_qual["total_starts"] * 100
            ).round(1)
            for _, row in garbage_qual.nlargest(20, "under_15_count").iterrows():
                entry = {
                    "player_name": str(row["player_name"]),
                    "manager": str(row["manager"]),
                    "under_15_count": int(row["under_15_count"]),
                    "total_starts": int(row["total_starts"]),
                    "pct": float(row["pct"]),
                    "season": season,
                }
                update_top10_list(garbage_top10, entry, "under_15_count", reverse=True)

    if garbage_top10:
        all_time["garbage_time_king"] = dict(garbage_top10[0])

    # Mr. Monday Night (highest avg FP on Mondays, min 5 games)
    monday_top10 = all_time.setdefault("mr_monday_night_top10", [])
    monday_top10[:] = [e for e in monday_top10 if e.get("season") != season]

    if "date" in df.columns:
        played = df[df["fantasy_points"] > 0].copy()
        played["day_of_week"] = pd.to_datetime(played["date"]).dt.dayofweek
        mondays = played[played["day_of_week"] == 0]

        if not mondays.empty:
            mon_stats = mondays.groupby(["player_name", "manager"]).agg(
                avg_fp=("fantasy_points", "mean"),
                monday_games=("fantasy_points", "count"),
            ).reset_index()
            mon_qual = mon_stats[mon_stats["monday_games"] >= 5]

            for _, row in mon_qual.nlargest(20, "avg_fp").iterrows():
                entry = {
                    "player_name": str(row["player_name"]),
                    "manager": str(row["manager"]),
                    "avg_fp": round(float(row["avg_fp"]), 1),
                    "monday_games": int(row["monday_games"]),
                    "season": season,
                }
                update_top10_list(monday_top10, entry, "avg_fp", reverse=True)

    if monday_top10:
        all_time["mr_monday_night"] = dict(monday_top10[0])

    # Rookie records
    if rookie_seasons:
        rookie_mask = df["player_name"].apply(
            lambda name: _normalize_season(
                rookie_seasons.get(str(name), "")
            ) == season
        )
        rookie_df = df[rookie_mask]

        if not rookie_df.empty:
            # Rookie season FPPG
            r_stats = rookie_df.groupby(["player_name", "manager"]).agg(
                total_fp=("fantasy_points", "sum"),
                gp=("fantasy_points", "count"),
            ).reset_index()
            r_stats["fppg"] = (r_stats["total_fp"] / r_stats["gp"]).round(2)
            r_qual = r_stats[r_stats["gp"] >= MIN_GP]

            rfppg_top10 = all_time.setdefault("best_rookie_season_fppg_top10", [])
            rfppg_top10[:] = [e for e in rfppg_top10 if e.get("season") != season]

            for _, row in r_qual.iterrows():
                entry = {
                    "player_name": str(row["player_name"]),
                    "manager": str(row["manager"]),
                    "fppg": float(row["fppg"]),
                    "gp": int(row["gp"]),
                    "total_fp": round(float(row["total_fp"]), 1),
                    "season": season,
                }
                update_top10_list(rfppg_top10, entry, "fppg", reverse=True)

            if rfppg_top10:
                all_time["best_rookie_season_fppg"] = dict(rfppg_top10[0])

            # Rookie season total FP
            rtotalfp_top10 = all_time.setdefault("best_rookie_season_total_fp_top10", [])
            rtotalfp_top10[:] = [e for e in rtotalfp_top10 if e.get("season") != season]

            for _, row in r_stats.nlargest(20, "total_fp").iterrows():
                entry = {
                    "player_name": str(row["player_name"]),
                    "manager": str(row["manager"]),
                    "total_fp": round(float(row["total_fp"]), 1),
                    "gp": int(row["gp"]),
                    "fppg": float(row["fppg"]),
                    "season": season,
                }
                update_top10_list(rtotalfp_top10, entry, "total_fp", reverse=True)

            if rtotalfp_top10:
                all_time["best_rookie_season_total_fp"] = dict(rtotalfp_top10[0])

            # Rookie weekly FP
            r_weekly = rookie_df.groupby(["player_name", "manager", "week"]).agg(
                weekly_fp=("fantasy_points", "sum"),
                games=("fantasy_points", "count"),
            ).reset_index()

            rweek_top10 = all_time.setdefault("best_rookie_fantasy_week_top10", [])
            rweek_top10[:] = [e for e in rweek_top10 if e.get("season") != season]

            for _, row in r_weekly.nlargest(20, "weekly_fp").iterrows():
                entry = {
                    "player_name": str(row["player_name"]),
                    "manager": str(row["manager"]),
                    "weekly_fp": round(float(row["weekly_fp"]), 2),
                    "games": int(row["games"]),
                    "season": season,
                    "week": int(row["week"]),
                }
                update_top10_list(rweek_top10, entry, "weekly_fp", reverse=True)

            if rweek_top10:
                all_time["best_rookie_fantasy_week"] = dict(rweek_top10[0])


# =============================================================================
# MAIN UPDATE FUNCTION
# =============================================================================

def update_records_from_weekly_report(
    data: FantasyData,
    report: WeeklyReport,
    title_odds: dict[str, float] = None,
    bench_points: dict[str, float] = None,
    blunders: dict[str, int] = None,
) -> list[RecordUpdate]:
    """
    Update all records based on a weekly report.
    
    Args:
        data: FantasyData container (records dict will be updated in place)
        report: WeeklyReport with this week's stats
        title_odds: Title odds to store (optional)
        bench_points: Bench points left on table per manager (optional)
        blunders: Blunder counts per manager (optional)
    
    Returns:
        List of RecordUpdates describing any records broken
    """
    records = data.records
    week = report.week
    updates = []

    # title_odds_history is keyed by week, so re-writing the same week is a safe
    # overwrite (not a cumulative add). Update it BEFORE the already-processed
    # guard so re-running a week still refreshes the odds-history entry that
    # the power-rankings trend depends on. Without this, regenerating a report
    # for a previously-processed week leaves title_odds_history stale (or
    # empty, in the bug case where the records call ran before the simulation)
    # and every manager's trend arrow gets frozen at "flat".
    if title_odds:
        update_title_odds_history(records, week, title_odds)

    # Check if this week was already processed to prevent double-counting
    last_week = records.get("last_updated_week", 0)
    if last_week >= week:
        print(f"  Note: Week {week} already processed (last_updated_week={last_week}), skipping record updates")
        return updates

    # Update last_updated_week
    records["last_updated_week"] = week
    
    # Check single-game records
    if report.best_single_game:
        bg = report.best_single_game
        update = check_single_game_record(
            records,
            "highest_single_game",
            SingleGameRecord(
                player_name=bg["player_name"],
                manager=bg["manager"],
                date=bg["date"],
                week=week,
                fantasy_points=bg["fantasy_points"],
                nba_opponent=bg.get("nba_opponent", ""),
            ),
            compare_higher=True,
        )
        if update:
            updates.append(update)
    
    if report.worst_single_game:
        wg = report.worst_single_game
        # Track lowest single game - negative scores ARE valid (bad games happen)
        # Only skip if fantasy_points is exactly 0 (likely DNP)
        if wg["fantasy_points"] != 0:
            update = check_single_game_record(
                records,
                "lowest_single_game",
                SingleGameRecord(
                    player_name=wg["player_name"],
                    manager=wg["manager"],
                    date=wg["date"],
                    week=week,
                    fantasy_points=wg["fantasy_points"],
                    nba_opponent=wg.get("nba_opponent", ""),
                ),
                compare_higher=False,
            )
            if update:
                updates.append(update)
    
    # Check weekly team records
    manager_scores = {}
    for manager, stats in report.manager_stats.items():
        manager_scores[manager] = stats.total_fp
        
        # Highest weekly team score
        update = check_weekly_team_record(
            records,
            "highest_weekly_team_score",
            WeeklyTeamRecord(manager=manager, week=week, score=stats.total_fp),
            compare_higher=True,
        )
        if update:
            updates.append(update)
        
        # Lowest weekly team score
        update = check_weekly_team_record(
            records,
            "lowest_weekly_team_score",
            WeeklyTeamRecord(manager=manager, week=week, score=stats.total_fp),
            compare_higher=False,
        )
        if update:
            updates.append(update)
    
    # Update streaks
    streak_updates = update_streaks(records, week, report.matchups)
    updates.extend(streak_updates)
    
    # Update H2H records (season) -- regular season only; playoff weeks
    # are intentionally skipped to stay consistent with get_manager_record().
    update_h2h_records(records, report.matchups, week=week)
    
    # Update all-time records (career stats, H2H, high/low scores, blowouts)
    update_all_time_records(records, report.matchups, manager_scores, week)
    
    # Update weekly scores history
    update_weekly_scores(records, week, manager_scores)
    
    # Update season FPPG stats (team and positional)
    update_season_fppg_stats(records, week, report, data)
    
    # Title odds history already updated above the already-processed guard
    # (it's an idempotent overwrite keyed by week, so safe to write before the
    # guard and skip the redundant call here).

    # Update cumulative bench points
    if bench_points:
        update_cumulative_bench_points(records, bench_points)
    
    # Update cumulative blunders
    if blunders:
        update_cumulative_blunders(records, blunders, week)
    
    # Update all-time team record top-10 leaderboards
    update_alltime_weekly_top10s(records, report.matchups, manager_scores, week)

    # Update season-level player records (FPPG, weekly FP, rookie records)
    rookie_seasons = _load_rookie_seasons_if_available(data.base_path)
    update_season_player_records(records, data.playerlog, week, rookie_seasons)

    # Update all-time player FPPG/weekly top-10s
    update_alltime_season_fppg_top10(
        records, data.playerlog, CURRENT_SEASON, rookie_seasons
    )

    # Check individual game records against all-time top-10s
    if report.best_single_game:
        bg = report.best_single_game
        check_alltime_single_game_top10(
            records, bg["player_name"], bg["manager"],
            bg["fantasy_points"], bg.get("date", ""), CURRENT_SEASON, week,
            rookie_seasons=rookie_seasons,
        )

    if report.worst_single_game:
        wg = report.worst_single_game
        if wg["fantasy_points"] != 0:
            check_alltime_single_game_top10(
                records, wg["player_name"], wg["manager"],
                wg["fantasy_points"], wg.get("date", ""), CURRENT_SEASON, week,
                rookie_seasons=rookie_seasons,
            )

    return updates


# =============================================================================
# QUERY FUNCTIONS
# =============================================================================

def get_current_streaks(records: dict) -> dict[str, dict]:
    """Get current win/loss streaks for all managers."""
    sr = records.get("season_records", {})
    current = sr.get("current_streaks", {})
    
    return {
        manager: {
            "win_streak": current.get(manager, {}).get("win", 0),
            "loss_streak": current.get(manager, {}).get("loss", 0),
        }
        for manager in MANAGERS
    }


def get_season_series(records: dict, manager_a: str, manager_b: str) -> tuple[int, int]:
    """Get season series record between two managers."""
    h2h = records.get("h2h_season", {})
    
    managers_sorted = sorted([manager_a, manager_b])
    key = f"{managers_sorted[0]}_vs_{managers_sorted[1]}"
    
    if key not in h2h:
        return (0, 0)
    
    wins_a = h2h[key].get(manager_a.lower(), 0)
    wins_b = h2h[key].get(manager_b.lower(), 0)
    
    return (wins_a, wins_b)


def get_current_season_h2h_matchups(manager_a: str, manager_b: str,
                                     weekly_scores: dict, schedule: dict,
                                     current_season: str = None) -> list:
    """
    Reconstruct current season H2H matchup results in chronological order
    using weekly_scores and schedule data.
    
    Args:
        manager_a: First manager name
        manager_b: Second manager name  
        weekly_scores: Dict from RECORDS.json with {manager: [{week, score}, ...]}
        schedule: Dict from SCHEDULE.json with weeks and matchups
        current_season: Current season string
    
    Returns:
        List of matchup dicts sorted by week (most recent first), each with:
            - season, week, winner
    """
    if current_season is None:
        current_season = CURRENT_SEASON
    # Build a lookup for weekly scores: {manager: {week: score}}
    scores_lookup = {}
    for manager, scores in weekly_scores.items():
        scores_lookup[manager] = {s['week']: s['score'] for s in scores}
    
    # Find all weeks where manager_a plays manager_b from schedule
    h2h_matchups = []
    for week_data in schedule.get('weeks', []):
        week_num = week_data.get('week')
        for matchup in week_data.get('matchups', []):
            m_a = matchup.get('manager_a')
            m_b = matchup.get('manager_b')
            
            # Check if this is a matchup between our two managers
            if set([m_a, m_b]) == set([manager_a, manager_b]):
                # Get scores for this week
                score_a = scores_lookup.get(manager_a, {}).get(week_num)
                score_b = scores_lookup.get(manager_b, {}).get(week_num)
                
                # Only include if both scores exist (game has been played)
                if score_a is not None and score_b is not None:
                    # Tie convention for completed games: award to
                    # manager_a (deterministic, consistent with the
                    # project-wide rule documented in data_loader.py).
                    # Real ties are essentially impossible with fractional
                    # scoring; this branch exists for explicitness.
                    winner = manager_a if score_a >= score_b else manager_b
                    h2h_matchups.append({
                        'season': current_season,
                        'week': week_num,
                        'winner': winner,
                    })
    
    # Sort by week descending (most recent first)
    h2h_matchups.sort(key=lambda x: x['week'], reverse=True)
    return h2h_matchups


def get_h2h_streak(all_matchups: list, manager_a: str, manager_b: str,
                   current_season: str = None, max_regular_season_week: int = None,
                   current_season_h2h: dict = None,
                   weekly_scores: dict = None, schedule: dict = None) -> dict:
    """
    Calculate the active head-to-head winning streak between two managers.
    
    Only counts regular season games (weeks 1-21 by default, excludes playoffs).
    Combines historical data from all_matchups with current season data.
    
    Args:
        all_matchups: List of historical matchup dicts
        manager_a: First manager name
        manager_b: Second manager name
        current_season: Current season string (e.g., "2025-26")
        max_regular_season_week: Max week for regular season (default 21)
        current_season_h2h: Dict from records["h2h_season"] with current season results
            (used as fallback if weekly_scores/schedule not provided)
        weekly_scores: Dict from RECORDS.json["weekly_scores"] - preferred method
        schedule: Dict from SCHEDULE.json - preferred method
    
    Returns:
        dict with keys:
            - streak_holder: manager who has the active streak
            - streak_length: number of consecutive wins
            - last_loss_season: when the streak holder last lost to opponent
            - last_loss_week: week number of last loss
    """
    if current_season is None:
        current_season = CURRENT_SEASON
    if max_regular_season_week is None:
        max_regular_season_week = REGULAR_SEASON_WEEKS
    # Collect all regular season H2H matchups from historical data
    h2h_matchups = []
    
    for m in all_matchups:
        managers = [m.get('manager_a'), m.get('manager_b')]
        week = m.get('week', 0)
        season = m.get('season', '')
        
        # Skip playoff weeks
        if week > max_regular_season_week:
            continue
        
        # Skip current season from historical (we handle current season separately)
        if season == current_season:
            continue
        
        if manager_a in managers and manager_b in managers:
            h2h_matchups.append({
                'season': season,
                'week': week,
                'winner': m.get('winner'),
            })
    
    # Sort historical by season desc, then week desc (most recent first)
    def sort_key(m):
        season = m['season']
        try:
            year = int(season.split('-')[0])
        except (ValueError, IndexError):
            year = 0
        return (year, m['week'])
    
    h2h_matchups.sort(key=sort_key, reverse=True)
    
    # Get current season matchups - prefer weekly_scores + schedule method
    current_season_matchups = []
    
    # Check if weekly_scores is a valid dict with manager data (not an empty list from legacy default)
    weekly_scores_valid = (
        isinstance(weekly_scores, dict) and 
        weekly_scores and 
        any(manager in weekly_scores for manager in [manager_a, manager_b])
    )
    
    if weekly_scores_valid and schedule:
        # PREFERRED: Use actual week-by-week scores to determine winners in order
        current_season_matchups = get_current_season_h2h_matchups(
            manager_a, manager_b, weekly_scores, schedule, current_season
        )
    elif current_season_h2h:
        # FALLBACK: Use h2h_season totals (can't determine order, less accurate)
        # This is the old behavior - only use if we don't have weekly data
        key1 = f"{manager_a}_vs_{manager_b}"
        key2 = f"{manager_b}_vs_{manager_a}"
        h2h_record = current_season_h2h.get(key1) or current_season_h2h.get(key2) or {}
        current_season_wins_a = h2h_record.get(manager_a.lower(), 0)
        current_season_wins_b = h2h_record.get(manager_b.lower(), 0)
        
        # Without week-by-week data, we can only make assumptions
        # If one manager swept, we know they have the streak
        # If both have wins, assume most recent games favor the one with more wins
        # (This is imperfect but maintains backward compatibility)
        if current_season_wins_a > 0 and current_season_wins_b == 0:
            for i in range(current_season_wins_a):
                current_season_matchups.append({
                    'season': current_season, 'week': 99-i, 'winner': manager_a
                })
        elif current_season_wins_b > 0 and current_season_wins_a == 0:
            for i in range(current_season_wins_b):
                current_season_matchups.append({
                    'season': current_season, 'week': 99-i, 'winner': manager_b
                })
        elif current_season_wins_a > 0 and current_season_wins_b > 0:
            # Both have wins - we don't know the order without week-by-week data
            # Since we can't determine the actual sequence, we should NOT add
            # any placeholder matchups that would artificially extend a streak.
            # The streak will be calculated from historical data only, which
            # is technically the "last known streak" before this season started.
            # This is conservative but accurate - better than guessing wrong.
            pass
    
    # Insert current season matchups at the front (they're already sorted desc)
    h2h_matchups = current_season_matchups + h2h_matchups
    
    if not h2h_matchups:
        return {
            'streak_holder': None,
            'streak_length': 0,
            'last_loss_season': None,
            'last_loss_week': None,
        }
    
    # Calculate active streak
    streak_holder = h2h_matchups[0]['winner']
    streak_length = 0
    last_loss_season = None
    last_loss_week = None
    
    for m in h2h_matchups:
        if m['winner'] == streak_holder:
            streak_length += 1
        else:
            last_loss_season = m['season']
            # Don't report placeholder weeks (50+)
            last_loss_week = m['week'] if m['week'] < 50 else None
            break
    
    return {
        'streak_holder': streak_holder,
        'streak_length': streak_length,
        'last_loss_season': last_loss_season,
        'last_loss_week': last_loss_week,
    }




# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    from .weekly_stats import compute_weekly_report, load_waiver_adds
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 11
    
    print(f"Loading data from: {base.absolute()}")
    print(f"Processing week {week}")
    print("-" * 50)
    
    data = load_all_data(base)
    
    # Load waivers
    waiver_file = base / f"data/waivers_week{week}.txt"
    waivers = load_waiver_adds(str(waiver_file))
    
    # Compute report
    report = compute_weekly_report(data, week, waivers)
    
    # Update records
    updates = update_records_from_weekly_report(data, report)
    
    print(f"\nRecord Updates ({len(updates)} total):")
    for update in updates:
        print(f"  {update.record_type}: {update.description}")
        if update.previous_value is not None:
            print(f"    Previous: {update.previous_value}, New: {update.current_value}")
    
    print("\nCurrent Streaks:")
    streaks = get_current_streaks(data.records)
    for manager, s in streaks.items():
        print(f"  {manager}: W{s['win_streak']} / L{s['loss_streak']}")
    
    print("\nSeason-Best Streaks:")
    
    print("\nH2H Records:")
    for key, record in data.records.get("h2h_season", {}).items():
        print(f"  {key}: {record}")
