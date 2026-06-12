"""
keepability_v2.py

Keepability scoring (current formula: v2.2). The previous hybrid "raw FPPG +
multiplier" approach has been RETIRED. All five components are now normalized
to 0-100, weighted-summed into a core_score, then scaled by an age multiplier.

CORE SCORE (0-100), weighted sum of normalized components:
  - Weighted 3-Year FPPG: 40%  (production track record)
  - Projected FPPG:       20%  (forward-looking value from PLAYERLIST)
  - 3-Year Availability:  20%  (durability)
  - Peak FPPG:            10%  (career ceiling)
  - Consistency:          10%  (low volatility bonus)

AGE MULTIPLIER (applied to core_score to produce final_score):
  - ≤23:    1.15  (dynasty premium)
  - 24-29:  1.00  (prime)
  - 30-33:  0.95  (late prime)
  - 34+:    0.85  (aging)

LOW-DATA FALLBACK: If no valid prior seasons (all <10 GP), proj_fppg is used
as the floor for the weighted_fppg and peak_fppg components so recently
acquired players are not zeroed out.

Tier assignment is FIXED-SLOT (see assign_keeper_tiers): top-9 Lock, next 12
Strong Hold, next 12 On the Bubble, with OFS / age / score overrides.

Usage:
    from modules.keepability_v2 import compute_keepability_v2, build_keepability_report

    # Single player score
    score, components = compute_keepability_v2(
        player_name="Luka Doncic",
        seasons=season_stats_list,
        age=26,
        positions="PG,SG",
        consistency_cv=0.35,
        ceilings={},          # signature compat only; FIXED_CEILINGS is used
        proj_fppg=48.0,
    )

    # Full report for all rostered players
    report = build_keepability_report(
        data=FantasyData(...),
        historical_playerlog=hist_data,
        week=18
    )
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import pandas as pd

from .data_loader import CURRENT_SEASON, REGULAR_SEASON_WEEKS


# =============================================================================
# CONFIGURATION
# =============================================================================

# Season weights for 3-year FPPG calculation
SEASON_WEIGHTS = {
    "current": 0.50,      # This year (most recent)
    "last_year": 0.30,    # Year -1
    "two_years": 0.20,    # Year -2
}

# Age factor multipliers (applied as final multiplier after core score)
# See _get_age_factor() for the actual implementation.
# ≤23: 1.15 (dynasty premium) | 24-29: 1.00 (prime)
# 30-33: 0.95 (late prime) | 34+: 0.85 (aging)

# Position scarcity multipliers -- REMOVED in v2.2
# Positional value is adequately captured by FPPG (centers produce more FP).
# POSITION_SCARCITY is no longer used in the formula.

# Component weights in final score (v2.2 formula)
# Age applied as final multiplier AFTER core score calculation
COMPONENT_WEIGHTS = {
    "weighted_fppg": 0.40,      # 3-year weighted production (dominant factor)
    "proj_fppg": 0.20,          # Current projected FPPG (forward-looking)
    "availability": 0.20,       # 3-year weighted availability
    "peak_fppg": 0.10,          # Career ceiling
    "consistency": 0.10,        # Low volatility bonus
}

# Minimum games required for meaningful season stats
MIN_GAMES_FOR_SEASON = 10

# Fixed theoretical ceilings for normalization
FIXED_CEILINGS = {
    "weighted_fppg": 65.0,   # Elite sustained production
    "proj_fppg": 60.0,       # Elite projection (Jokic-tier)
    "peak_fppg": 70.0,       # Generational peak season
    "availability": 0.95,    # 95% games played (ironman)
}

# Consistency CV normalization range
CONSISTENCY_CV_BEST = 24.0   # ~P10: very consistent (maps to 100)
CONSISTENCY_CV_WORST = 42.0  # ~P90: very volatile (maps to 0)

# Projected FPPG floor for players with insufficient historical data
LOW_DATA_PROJ_FLOOR = True

# Fixed tier slot counts (v2.2)
TIER_LOCK_COUNT = 12
TIER_STRONG_HOLD_COUNT = 12
TIER_ON_THE_BUBBLE_COUNT = 12
KEEPER_WATCH_PLAYER_CAP = 48

# Score override: players above this threshold are ALWAYS Lock,
# regardless of age or other contextual overrides.
LOCK_SCORE_OVERRIDE = 80.0


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SeasonStats:
    """Player stats for a single season."""
    season: str
    games_played: int
    total_fp: float
    fppg: float
    expected_games: int  # Based on league schedule that season
    availability_pct: float  # games_played / expected_games


@dataclass
class KeeperComponents:
    """Individual components of keepability score (v2.2 formula)."""
    weighted_fppg_raw: float
    weighted_fppg_normalized: float
    proj_fppg_raw: float
    proj_fppg_normalized: float
    peak_fppg_raw: float
    peak_fppg_normalized: float
    availability_3yr_pct: float
    availability_normalized: float
    consistency_cv: float
    consistency_normalized: float
    age: int
    age_factor: float
    
    # Core score (before age multiplier)
    core_score: float
    
    # Final score (after age multiplier)
    final_score: float
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "weighted_fppg_raw": round(self.weighted_fppg_raw, 2),
            "weighted_fppg_normalized": round(self.weighted_fppg_normalized, 2),
            "proj_fppg_raw": round(self.proj_fppg_raw, 2),
            "proj_fppg_normalized": round(self.proj_fppg_normalized, 2),
            "peak_fppg_raw": round(self.peak_fppg_raw, 2),
            "peak_fppg_normalized": round(self.peak_fppg_normalized, 2),
            "availability_3yr_pct": round(self.availability_3yr_pct * 100, 1),
            "availability_normalized": round(self.availability_normalized, 2),
            "consistency_cv": round(self.consistency_cv, 2),
            "consistency_normalized": round(self.consistency_normalized, 2),
            "age": self.age,
            "age_factor": round(self.age_factor, 2),
            "core_score": round(self.core_score, 1),
            "final_score": round(self.final_score, 1),
        }


# =============================================================================
# SEASON LENGTH LOOKUP
# =============================================================================

def get_season_lengths(all_matchups: List[dict]) -> Dict[str, int]:
    """
    Extract the number of weeks in each historical season.
    
    Returns:
        Dict mapping season -> max week number
        e.g., {"2019-20": 19, "2020-21": 18, "2021-22": 22, ...}
    """
    seasons = {}
    for matchup in all_matchups:
        season = matchup["season"]
        week = matchup["week"]
        if season not in seasons:
            seasons[season] = 0
        seasons[season] = max(seasons[season], week)
    return seasons


# =============================================================================
# POSITION GROUP CLASSIFICATION
# =============================================================================

def classify_position_group(positions: str) -> str:
    """
    Classify player into G/F/C based on position string.
    
    Priority: C > F > G (most scarce -> least scarce)
    
    Examples:
        "C" -> "C"
        "PF,C" -> "C"
        "SG,SF" -> "F"
        "PG" -> "G"
    """
    if not positions:
        return "G"  # Default to most common
    
    pos_upper = positions.upper()
    
    # Check for Center first (most scarce)
    if "C" in pos_upper and "PF" not in pos_upper and "SF" not in pos_upper:
        return "C"
    
    # Check for Forward
    if any(p in pos_upper for p in ["PF", "SF", "F"]):
        return "F"
    
    # Default to Guard
    return "G"


# =============================================================================
# MULTI-YEAR PLAYER STATS EXTRACTION
# =============================================================================

def extract_player_season_stats(
    player_name: str,
    historical_playerlog: List[dict],
    current_season_playerlog: pd.DataFrame,
    current_season: str,
    season_lengths: Dict[str, int],
    current_week: int,
) -> List[SeasonStats]:
    """
    Extract season-by-season stats for a player from historical + current data.
    
    Args:
        player_name: Player's name
        historical_playerlog: List of game dicts from HISTORICAL_PLAYERLOG.json
        current_season_playerlog: DataFrame from PLAYERLOG.xlsx (current season only)
        current_season: Current season string (e.g., "2025-26")
        season_lengths: Dict mapping season -> number of weeks
        current_week: Current week number
    
    Returns:
        List of SeasonStats, one per season where player appeared (sorted newest first)
    """
    season_stats = []
    
    # --- Process historical seasons ---
    # HISTORICAL_PLAYERLOG structure: list of game dicts with keys:
    # season, week, player_name, manager, started, fantasy_points, nba_opponent
    
    historical_by_season = defaultdict(list)
    historical_weeks_rostered = defaultdict(set)  # Track weeks player was on ANY roster
    for game in historical_playerlog:
        if game.get("player_name") == player_name:
            season_key = game.get("season_key", "")
            if season_key:
                # Track ALL weeks this player appears on a roster (any slot)
                week_num = game.get("week")
                if week_num is not None:
                    historical_weeks_rostered[season_key].add(week_num)
                
                # Count any game where the player actually played (FP > 0),
                # regardless of whether they were in a starter or bench slot.
                # Player-level stats should reflect player performance, not
                # their manager's lineup decisions.
                fp = game.get("fantasy_points", 0.0)
                had_game = game.get("had_game", False)
                is_injured = game.get("is_injured", False)
                if fp != 0 and not is_injured:
                    historical_by_season[season_key].append(fp)
    
    for season, fp_list in historical_by_season.items():
        games_played = len(fp_list)
        total_fp = sum(fp_list)
        fppg = total_fp / games_played if games_played > 0 else 0.0
        
        # Expected games based on weeks the player was ACTUALLY ROSTERED,
        # not the full season length. This prevents mid-season pickups and
        # rookies called up late from being penalized for "missing" games
        # before they were on anyone's team.
        weeks_on_roster = len(historical_weeks_rostered.get(season, set()))
        if weeks_on_roster > 0:
            expected_games = weeks_on_roster * 3.3
        else:
            # Fallback to full season if we can't determine weeks rostered
            expected_games = season_lengths.get(season, 23) * 3.3
        
        availability_pct = games_played / expected_games if expected_games > 0 else 0.0
        
        season_stats.append(SeasonStats(
            season=season,
            games_played=games_played,
            total_fp=total_fp,
            fppg=fppg,
            expected_games=int(expected_games),
            availability_pct=min(1.0, availability_pct),  # Cap at 100%
        ))
    
    # --- Process current season ---
    # Current season data comes from PLAYERLOG.xlsx
    # First, find ALL rows for this player (any slot) to determine weeks rostered
    all_player_rows = current_season_playerlog[
        (current_season_playerlog["player_name"] == player_name)
        & (current_season_playerlog["week"] <= current_week)
    ]
    current_weeks_rostered = all_player_rows["week"].nunique() if not all_player_rows.empty else 0
    
    # Filter to games where player actually played (FP != 0, real game).
    # Includes BOTH starter and bench slots -- player-level stats should
    # reflect player performance, not their manager's lineup decisions.
    current_games = current_season_playerlog[
        (current_season_playerlog["player_name"] == player_name)
        & (current_season_playerlog["week"] <= current_week)
        & (current_season_playerlog["fantasy_points"].notna())
        & (current_season_playerlog["fantasy_points"] != 0)
        & (current_season_playerlog["nba_opponent"].notna())
    ]
    
    # ALWAYS create a SeasonStats for the current season if the player is
    # rostered, even with 0 GP. This ensures players who missed the entire
    # season (e.g., Tatum on IL all year) get a 0% availability penalty
    # instead of being invisible and scored on historical data only.
    if current_weeks_rostered > 0:
        games_played = len(current_games) if not current_games.empty else 0
        total_fp = current_games["fantasy_points"].sum() if not current_games.empty else 0.0
        fppg = total_fp / games_played if games_played > 0 else 0.0
        
        expected_games = int(current_weeks_rostered * 3.3)
        availability_pct = games_played / expected_games if expected_games > 0 else 0.0
        
        season_stats.append(SeasonStats(
            season=current_season,
            games_played=games_played,
            total_fp=total_fp,
            fppg=fppg,
            expected_games=expected_games,
            availability_pct=min(1.0, availability_pct),
        ))
    
    # Sort by season (newest first)
    season_stats.sort(key=lambda x: x.season, reverse=True)
    
    return season_stats


# =============================================================================
# COMPONENT CALCULATIONS
# =============================================================================

def _calculate_weighted_fppg(seasons: List[SeasonStats]) -> float:
    """
    Calculate weighted 3-year FPPG (50% this year, 30% last year, 20% two years ago).
    
    Handles cases where player has <3 seasons gracefully:
      - 1 season: 100% weight on that season
      - 2 seasons: 62.5% recent, 37.5% older (renormalized weights)
      - 3+ seasons: Standard 50/30/20 split
    
    Only includes seasons with MIN_GAMES_FOR_SEASON or more.
    """
    # Filter to seasons with meaningful sample size
    valid_seasons = [s for s in seasons if s.games_played >= MIN_GAMES_FOR_SEASON]
    
    if not valid_seasons:
        return 0.0
    
    if len(valid_seasons) == 1:
        return valid_seasons[0].fppg
    
    if len(valid_seasons) == 2:
        # Renormalize: 50% / (50% + 30%) = 62.5%, 30% / 80% = 37.5%
        return (0.625 * valid_seasons[0].fppg) + (0.375 * valid_seasons[1].fppg)
    
    # 3+ seasons: standard weights
    weighted = (
        SEASON_WEIGHTS["current"] * valid_seasons[0].fppg +
        SEASON_WEIGHTS["last_year"] * valid_seasons[1].fppg +
        SEASON_WEIGHTS["two_years"] * valid_seasons[2].fppg
    )
    return weighted


def _calculate_3yr_availability(seasons: List[SeasonStats]) -> float:
    """
    Calculate recency-weighted availability % over last 3 seasons.
    
    Uses the same weighting scheme as _calculate_weighted_fppg:
      - 1 season:  100% weight
      - 2 seasons: 62.5% recent + 37.5% older
      - 3+ seasons: 50% current + 30% last year + 20% two years ago
    
    This ensures a player's current-season health matters more than
    an injury-plagued season 2 years ago.
    """
    if not seasons:
        return 0.0
    
    recent_3 = seasons[:3]  # Already sorted newest first
    
    if len(recent_3) == 1:
        return recent_3[0].availability_pct
    
    if len(recent_3) == 2:
        return (0.625 * recent_3[0].availability_pct) + (0.375 * recent_3[1].availability_pct)
    
    # 3+ seasons: standard 50/30/20 weights
    return (
        SEASON_WEIGHTS["current"] * recent_3[0].availability_pct +
        SEASON_WEIGHTS["last_year"] * recent_3[1].availability_pct +
        SEASON_WEIGHTS["two_years"] * recent_3[2].availability_pct
    )


def _get_age_factor(age: int) -> float:
    """Get age multiplier (applied after core score).
    
    Brackets (v2.2):
        ≤23:  1.15 (dynasty premium)
        24-29: 1.00 (prime)
        30-33: 0.95 (late prime / veteran)
        34+:   0.85 (aging)
    """
    if not age:
        age = 27  # Default to prime
    
    if age <= 23:
        return 1.15
    elif age <= 29:
        return 1.00
    elif age <= 33:
        return 0.95
    else:
        return 0.85




# =============================================================================
# NORMALIZATION TO 0-100 SCALE
# =============================================================================

def normalize_to_100(
    raw_value: float,
    ceiling: float,
    floor: float = 0.0,
) -> float:
    """
    Normalize a raw value to 0-100 scale based on ceiling and floor.
    
    Args:
        raw_value: The actual value to normalize
        ceiling: The theoretical maximum (maps to 100)
        floor: The theoretical minimum (maps to 0)
    
    Returns:
        Normalized value between 0-100
    """
    if ceiling == floor:
        return 100.0 if raw_value >= ceiling else 0.0
    
    normalized = ((raw_value - floor) / (ceiling - floor)) * 100
    return max(0.0, min(100.0, normalized))  # Clamp to [0, 100]


# =============================================================================
# MAIN KEEPABILITY SCORE CALCULATION
# =============================================================================

def compute_keepability_v2(
    player_name: str,
    seasons: List[SeasonStats],
    age: int,
    positions: str,
    consistency_cv: float,
    ceilings: Dict[str, float],  # Unused, kept for signature compatibility
    proj_fppg: float = 0.0,
) -> Tuple[float, KeeperComponents]:
    """
    Compute keepability score (v2.2 formula).
    
    CORE SCORE (0-100) from 5 normalized components:
      - 3-Year Weighted FPPG: 40% (production track record)
      - Projected FPPG: 20% (forward-looking value from PLAYERLIST)
      - 3-Year Weighted Availability: 20% (durability)
      - Peak FPPG: 10% (career ceiling)
      - Consistency: 10% (low volatility bonus)
    
    Then apply age multiplier:
      ≤23: 1.15x | 24-29: 1.00x | 30-33: 0.95x | 34+: 0.85x
    
    LOW-DATA FALLBACK: When a player has no valid seasons (all < 10 GP),
    weighted_fppg and peak_fppg would be 0.0. Use proj_fppg as floor
    for those components so recently acquired players aren't zeroed out.
    """
    # --- Component 1: Weighted 3-Year FPPG (40%) ---
    weighted_fppg_raw = _calculate_weighted_fppg(seasons)
    
    # --- Component 2: Peak FPPG (10%) ---
    valid_seasons = [s for s in seasons if s.games_played >= MIN_GAMES_FOR_SEASON]
    peak_fppg_raw = max((s.fppg for s in valid_seasons), default=0.0)
    
    # --- LOW-DATA PROJECTION FLOOR ---
    if LOW_DATA_PROJ_FLOOR and weighted_fppg_raw == 0.0 and proj_fppg > 0:
        weighted_fppg_raw = proj_fppg
        peak_fppg_raw = proj_fppg
    
    weighted_fppg_normalized = normalize_to_100(
        weighted_fppg_raw, ceiling=FIXED_CEILINGS["weighted_fppg"],
    )
    
    # --- Component 3: Projected FPPG (20%) ---
    proj_fppg_normalized = normalize_to_100(
        proj_fppg, ceiling=FIXED_CEILINGS["proj_fppg"],
    )
    
    peak_fppg_normalized = normalize_to_100(
        peak_fppg_raw, ceiling=FIXED_CEILINGS["peak_fppg"],
    )
    
    # --- Component 4: 3-Year Availability (20%) ---
    availability_3yr_pct = _calculate_3yr_availability(seasons)
    availability_normalized = normalize_to_100(
        availability_3yr_pct, ceiling=FIXED_CEILINGS["availability"],
    )
    
    # --- Component 5: Consistency (10%) ---
    cv_range = CONSISTENCY_CV_WORST - CONSISTENCY_CV_BEST
    if cv_range > 0:
        consistency_normalized = normalize_to_100(
            CONSISTENCY_CV_WORST - consistency_cv,
            ceiling=cv_range, floor=0.0,
        )
    else:
        consistency_normalized = 50.0
    
    # --- CORE SCORE ---
    core_score = (
        COMPONENT_WEIGHTS["weighted_fppg"] * weighted_fppg_normalized +
        COMPONENT_WEIGHTS["proj_fppg"] * proj_fppg_normalized +
        COMPONENT_WEIGHTS["availability"] * availability_normalized +
        COMPONENT_WEIGHTS["peak_fppg"] * peak_fppg_normalized +
        COMPONENT_WEIGHTS["consistency"] * consistency_normalized
    )
    
    # --- AGE MULTIPLIER (applied last) ---
    age_factor = _get_age_factor(age)
    final_score = core_score * age_factor
    
    # Build components object
    position_group = classify_position_group(positions)
    components = KeeperComponents(
        weighted_fppg_raw=weighted_fppg_raw,
        weighted_fppg_normalized=weighted_fppg_normalized,
        proj_fppg_raw=proj_fppg,
        proj_fppg_normalized=proj_fppg_normalized,
        peak_fppg_raw=peak_fppg_raw,
        peak_fppg_normalized=peak_fppg_normalized,
        availability_3yr_pct=availability_3yr_pct,
        availability_normalized=availability_normalized,
        consistency_cv=consistency_cv,
        consistency_normalized=consistency_normalized,
        age=age,
        age_factor=age_factor,
        core_score=core_score,
        final_score=final_score,
    )
    
    return final_score, components


# =============================================================================
# KEEPER TIER ASSIGNMENT
# =============================================================================

def assign_keeper_tiers(players: List[dict]) -> List[dict]:
    """
    Assign keeper tiers using FIXED SLOT COUNTS (v2.2).
    
    Players sorted by keepability score descending. Contextual overrides
    are checked first (these don't consume fixed-tier slots):
    
    OVERRIDES:
      - OFS (out for season) → always "Stash"
      - Age ≤ 23 → always "Dynasty Stash"
      - Age ≥ 33 AND within top-33 range → "Sell High"
    
    FIXED SLOTS (non-overridden players fill in order):
      - First 9  → Lock
      - Next 12  → Strong Hold
      - Next 12  → On the Bubble
    
    REMAINING (after 33 fixed slots filled):
      - Age ≥ 33 → "Sell High"
      - Otherwise → "Waiver Wire"
    
    Section capped at KEEPER_WATCH_PLAYER_CAP (45) players total.
    """
    # Cap to top 45
    players = players[:KEEPER_WATCH_PLAYER_CAP]
    
    lock_remaining = TIER_LOCK_COUNT
    strong_remaining = TIER_STRONG_HOLD_COUNT
    bubble_remaining = TIER_ON_THE_BUBBLE_COUNT
    
    for p in players:
        age = p.get("age") or 27
        is_ofs = p.get("out_for_season", False)
        score = p.get("keepability_score", 0)
        
        # --- SCORE OVERRIDE: Elite players are ALWAYS Lock ---
        # A player scoring 80+ is undeniably elite regardless of age.
        # Prevents young superstars or aging legends from being pulled
        # out of Lock by contextual overrides.
        if score >= LOCK_SCORE_OVERRIDE and not is_ofs:
            p["keeper_tier"] = "Lock"
            if lock_remaining > 0:
                lock_remaining -= 1
            continue
        
        if is_ofs:
            p["keeper_tier"] = "Stash"
            continue
        if age <= 23:
            p["keeper_tier"] = "Dynasty Stash"
            continue
        if age >= 33 and (lock_remaining > 0 or strong_remaining > 0 or bubble_remaining > 0):
            p["keeper_tier"] = "Sell High"
            continue
        
        if lock_remaining > 0:
            p["keeper_tier"] = "Lock"
            lock_remaining -= 1
        elif strong_remaining > 0:
            p["keeper_tier"] = "Strong Hold"
            strong_remaining -= 1
        elif bubble_remaining > 0:
            p["keeper_tier"] = "On the Bubble"
            bubble_remaining -= 1
        else:
            p["keeper_tier"] = "Sell High" if age >= 33 else "Waiver Wire"
    
    return players


# Legacy single-player function kept for backward compatibility
def assign_keeper_tier(score, age, core_score, is_injured=False, is_out_for_season=False):
    """Legacy per-player tier. Use assign_keeper_tiers() for batch."""
    if is_out_for_season: return "Stash"
    if age and age <= 23: return "Dynasty Stash"
    if age and age >= 33: return "Sell High"
    if score >= 68: return "Lock"
    if score >= 58: return "Strong Hold"
    if score >= 50: return "On the Bubble"
    return "Waiver Wire"


# =============================================================================
# FULL REPORT BUILDER
# =============================================================================

def build_keepability_report(
    data,  # FantasyData object
    historical_playerlog: List[dict],
    week: int,
    current_season: str = None,
) -> dict:
    """
    Build complete keepability report for all rostered players.
    
    Args:
        data: FantasyData object with current season data
        historical_playerlog: List of game dicts from HISTORICAL_PLAYERLOG.json
        week: Current week number
        current_season: Current season string
    
    Returns:
        Dict with structure:
        {
            "players": [
                {
                    "player_name": str,
                    "manager": str,
                    "keeper_tier": str,
                    "keepability_score": float,
                    "components": {...},  # Breakdown of score
                    "age": int,
                    "pos_group": str,
                    "season_gp": int,
                    "season_fppg": float,
                    ...
                },
                ...
            ],
            "league_ceilings": {...},  # Theoretical ceilings used
        }
    """
    if current_season is None:
        current_season = CURRENT_SEASON
    # Load supporting data
    rosters = data.get_current_rosters()
    playerlist = data.playerlist
    playerlog = data.playerlog
    
    # Load season lengths from all_matchups.json
    from pathlib import Path
    import json
    
    # Determine project root based on data object location
    # Assuming data object has methods that can help us find the root
    # For now, use relative path from module location
    module_dir = Path(__file__).resolve().parent
    project_root = module_dir.parent if module_dir.name == "modules" else module_dir
    
    all_matchups_path = project_root / "all_matchups.json"
    if all_matchups_path.exists():
        with open(all_matchups_path, 'r') as f:
            all_matchups = json.load(f)
        season_lengths = get_season_lengths(all_matchups)
    else:
        # Fallback to hardcoded values
        season_lengths = {
            "2017-18": 23,
            "2018-19": 23,
            "2019-20": 19,
            "2020-21": 18,
            "2021-22": 22,
            "2022-23": 23,
            "2023-24": 23,
            "2024-25": 23,
        }
    
    # Add current season
    season_lengths[current_season] = REGULAR_SEASON_WEEKS
    
    # Build player info lookup from PLAYERLIST
    player_info = {}
    for _, row in playerlist.iterrows():
        pname = row["player_name"]
        player_info[pname] = {
            "age": int(row["age"]) if pd.notna(row.get("age")) else 27,
            "positions": row.get("player_position(s)", ""),
            "proj_fppg": round(float(row["projectedFPPG"]), 2) if pd.notna(row.get("projectedFPPG")) else 0.0,
        }
    
    # Extract multi-year stats for all players
    all_player_stats = {}
    for mgr, roster in rosters.items():
        for pname in roster:
            seasons = extract_player_season_stats(
                player_name=pname,
                historical_playerlog=historical_playerlog,
                current_season_playerlog=playerlog,
                current_season=current_season,
                season_lengths=season_lengths,
                current_week=week,
            )
            all_player_stats[pname] = seasons
    
    # No longer need dynamic ceilings - using FIXED_CEILINGS constant
    ceilings = {}  # Empty dict for signature compatibility
    
    # Get consistency scores from existing system
    from .consistency_score import get_player_consistency_cv
    consistency_scores = get_player_consistency_cv(data, week)
    
    # Load injury overrides
    ofs_players = set()
    injured_players = set()
    for inj in data.injury_overrides.get("players", []):
        if inj.get("notes", "").lower().startswith("out for season"):
            ofs_players.add(inj["player_name"])
        out_weeks = inj.get("out_weeks", [])
        if week in out_weeks or (out_weeks and max(out_weeks) >= week):
            injured_players.add(inj["player_name"])
    
    # Compute keepability for all players
    players = []
    for mgr, roster in rosters.items():
        for pname in roster:
            info = player_info.get(pname, {})
            age = info.get("age", 27)
            positions = info.get("positions", "")
            
            seasons = all_player_stats.get(pname, [])
            
            # Get consistency CV
            # Players with <10 GP get a default from get_player_consistency_cv().
            # That default (15%) is below our CV_BEST (24%), which would give them
            # a PERFECT consistency score for having too few games to measure.
            # Instead, give low-GP players a NEUTRAL consistency score (league median CV).
            raw_cv = consistency_scores.get(pname)
            if raw_cv is not None:
                consistency_cv = raw_cv  # Real data from 10+ games
            else:
                consistency_cv = 33.0  # League median CV -- neutral "we don't know"
            
            # Compute score
            score, components = compute_keepability_v2(
                player_name=pname,
                seasons=seasons,
                age=age,
                positions=positions,
                consistency_cv=consistency_cv,
                ceilings=ceilings,
                proj_fppg=info.get("proj_fppg", 0.0),
            )
            
            # Track OFS/injured status
            is_ofs = pname in ofs_players
            is_injured = pname in injured_players
            
            # Get current season stats for display
            current_season_data = next((s for s in seasons if s.season == current_season), None)
            season_gp = current_season_data.games_played if current_season_data else 0
            season_fppg = current_season_data.fppg if current_season_data else 0.0
            season_total_fp = current_season_data.total_fp if current_season_data else 0.0
            proj_fppg_val = info.get("proj_fppg", 0.0)
            
            players.append({
                "player_name": pname,
                "manager": mgr,
                "keeper_tier": "",  # Assigned below by batch function
                "keepability_score": round(score, 1),
                "components": components.to_dict(),
                "age": age,
                "pos_group": classify_position_group(positions),
                "season_gp": season_gp,
                "season_fppg": round(season_fppg, 2),
                "season_total_fp": round(season_total_fp, 1),
                "proj_fppg": proj_fppg_val,
                "out_for_season": is_ofs,
                "injured": is_injured,
            })
    
    # Sort by keepability score descending
    players.sort(key=lambda x: -x["keepability_score"])
    
    # Assign tiers using fixed-count system (top 45 players only)
    players = assign_keeper_tiers(players)
    
    return {
        "players": players,
    }


# =============================================================================
# STANDALONE TESTING
# =============================================================================

if __name__ == "__main__":
    print("keepability_v2.py - Enhanced Keepability Scoring System")
    print("=" * 70)
    print("\nThis module must be imported and called with proper data sources.")
    print("See docstring for usage examples.")
