"""
rumor_mill_analyzer.py

Data-driven strategic analysis for the Rumor Mill section.
Generates trade ideas, free agent recommendations, and drop candidates.

KEEPER LEAGUE TRADE LOGIC (v4):
- Top 6 players per team = "keepers" (hard to acquire, need competitive packages)
- Players 7+ = "trade block" (expendable, likely gone next year)
- Core keepers (1-3) require overpay; fringe keepers (4-6) available for right price

MANAGER SITUATION TAGS:
- Contender: High title odds (>15%), wants proven production NOW
- Fringe: Medium title odds (5-15%), could go either way
- Rebuilder: Low title odds (<5%), wants youth, upside, draft picks

TRADE VALUE CALCULATION (v6 - Keepability V2 integration):
When keeper_watch data is provided, trade values use the keepability V2
score (0-100 scale) which factors in:
  - Weighted 3-year FPPG (50%)
  - Peak FPPG career ceiling (20%)
  - 3-year availability (15%)
  - Consistency / low volatility (15%)
  - Age curve multiplier (0.95-1.05)
  - Positional scarcity multiplier (1.00-1.03)

Falls back to legacy compute_trade_value() (single-season blend) if
keeper_watch data is not available.

AGE-BASED DYNASTY VALUE:
- Young ( -> 23): Premium dynasty asset, teams hesitant to trade
- Prime (24-29): Peak production years, high value
- Veteran (30-32): Still productive but declining runway
- Aging (33+): Sell candidate, especially for rebuilders

TRADE TYPES GENERATED:
1. Trade block swaps - 1-for-1 between non-keepers addressing positional needs
2. 2-for-1 consolidation - Package depth for star (contender move)
3. 2-for-1 expansion - Trade aging star for young pieces (rebuilder move)
4. Keeper + pick deals - Sweeten with draft capital for slight upgrades
5. Buy-low opportunities - Target underperforming players at discount
"""

from dataclasses import dataclass, field
from typing import Optional
import math

import pandas as pd

from .data_loader import FantasyData, MANAGERS, MANAGER_TO_TEAM, get_position_list
from .projections import (
    load_all_team_projections,
    get_underperformers,
    get_overperformers,
    compute_underperformance_index,
)
from .data_loader import classify_position_group


# =============================================================================
# CONSTANTS
# =============================================================================

# Age thresholds for dynasty value
AGE_YOUNG = 23 # -> 23 = young asset
AGE_PRIME_END = 29  # 24-29 = prime
AGE_VETERAN_END = 32  # 30-32 = veteran
# 33+ = aging

# Title odds thresholds for team situation
CONTENDER_THRESHOLD = 15.0  # >15% = contender
REBUILDER_THRESHOLD = 5.0   # <5% = rebuilder


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PositionNeed:
    """A manager's need at a position group."""
    manager: str
    position: str  # "G", "F", or "C"
    need_score: float  # Higher = more need
    current_strength: float  # Total projected FPPG at position
    reason: str


@dataclass
class TradeIdea:
    """A potential trade concept."""
    manager_a: str
    manager_b: str
    gives_a: list[str]  # Players A would give
    receives_a: list[str]  # Players A would receive
    rationale: str
    fit_score: float
    trade_type: str = "swap"  # "swap", "upgrade", "depth"


@dataclass
class FreeAgentTarget:
    """A free agent recommendation."""
    player_name: str
    positions: list[str]
    projected_fppg: float
    target_manager: str
    fit_score: float
    reason: str


@dataclass
class DropCandidate:
    """A player who should be considered for dropping."""
    player_name: str
    manager: str
    projected_fppg: float
    underperformance_index: float
    underperformance_index_last_14_days: Optional[float]
    reason: str
    better_fa_available: Optional[str] = None


@dataclass
class HotStreakCandidate:
    """A player on a hot streak who has trade value."""
    player_name: str
    manager: str
    projected_fppg: float
    overperformance_index: float
    overperformance_index_last_14_days: Optional[float]
    reason: str
    trade_value_note: Optional[str] = None


@dataclass
class RumorMillAnalysis:
    """Complete Rumor Mill analysis."""
    position_needs: dict[str, list[PositionNeed]]  # manager -> list of needs
    trade_ideas: list[TradeIdea]
    free_agent_targets: list[FreeAgentTarget]
    hot_streak_candidates: list[HotStreakCandidate]
    drop_candidates: list[DropCandidate]


# =============================================================================
# HELPER FUNCTIONS - AGE & TEAM SITUATION
# =============================================================================

def get_age_category(age: int) -> str:
    """Categorize player age for dynasty value assessment."""
    if age <= AGE_YOUNG:
        return "young"
    elif age <= AGE_PRIME_END:
        return "prime"
    elif age <= AGE_VETERAN_END:
        return "veteran"
    else:
        return "aging"


def get_age_description(age: int) -> str:
    """Get a descriptive string for player age."""
    category = get_age_category(age)
    if category == "young":
        return f"young ({age})"
    elif category == "prime":
        return f"prime-age ({age})"
    elif category == "veteran":
        return f"veteran ({age})"
    else:
        return f"aging ({age})"


def get_team_situation(title_odds: float) -> str:
    """
    Categorize team as contender, fringe, or rebuilder based on title odds.
    
    Returns: 'contender', 'fringe', or 'rebuilder'
    """
    if title_odds >= CONTENDER_THRESHOLD:
        return "contender"
    elif title_odds >= REBUILDER_THRESHOLD:
        return "fringe"
    else:
        return "rebuilder"


def get_situation_description(situation: str, manager: str) -> str:
    """Get a descriptive phrase for the manager's situation."""
    if situation == "contender":
        return f"{manager}, in the title hunt,"
    elif situation == "fringe":
        return f"{manager}, on the playoff bubble,"
    else:
        return f"{manager}, looking ahead to next season,"


def compute_dynasty_value(projected_fppg: float, age: int) -> float:
    """
    Compute a dynasty-adjusted value for a player.
    Young players get a premium, aging players get a discount.
    
    NOTE: This is the LEGACY function using only projections.
    For trade comparisons, use compute_trade_value() which factors in
    actual performance and availability.
    """
    base_value = projected_fppg
    category = get_age_category(age)
    
    if category == "young":
        # Young players get 15% premium for upside
        return base_value * 1.15
    elif category == "prime":
        # Prime players valued at face value
        return base_value
    elif category == "veteran":
        # Veterans get slight discount (5%)
        return base_value * 0.95
    else:
        # Aging players get 15% discount
        return base_value * 0.85


def get_expected_games_for_week(week: int) -> int:
    """
    Calculate expected games played through a given week.
    Assumes ~3.3 games per week average over 21-week season (~70 total games).
    """
    return int(week * 3.3)


def compute_trade_value(
    player,  # PlayerProjection
    age: int,
    current_week: int = 13,
    min_games_for_actual: int = 10,
) -> float:
    """
    Compute realistic trade value using actual performance + availability + age.
    
    This is the PRIMARY valuation function for trade fairness comparisons.
    It accounts for:
    - Actual FPPG vs projected (weighted blend if enough games)
    - Games played / availability (players who don't play aren't as valuable)
    - Age-based dynasty adjustment
    
    Args:
        player: PlayerProjection with actual_fppg, actual_games, projected_fppg
        age: Player's age
        current_week: Current fantasy week (for expected games calculation)
        min_games_for_actual: Minimum games to trust actual stats
    
    Returns:
        Trade value (higher = more valuable)
    """
    # Get projected and actual stats
    projected = player.projected_fppg or 0
    actual = getattr(player, 'actual_fppg', None)
    games = getattr(player, 'actual_games', 0) or 0
    
    # Calculate base FPPG using weighted blend
    if actual is not None and games >= min_games_for_actual:
        # Weight actual performance heavily if we have enough data
        # 70% actual, 30% projected
        base_fppg = 0.7 * actual + 0.3 * projected
    elif actual is not None and games >= 5:
        # Some data - blend more evenly
        weight = games / min_games_for_actual
        base_fppg = weight * actual + (1 - weight) * projected
    else:
        # Not enough actual data - use projection
        base_fppg = projected
    
    # Availability factor - players who don't play aren't as valuable
    expected_games = get_expected_games_for_week(current_week)
    if expected_games > 0 and games > 0:
        availability = min(1.0, games / expected_games)
        # Apply availability penalty (sqrt to soften the impact)
        # A player with 50% availability gets ~71% of value, not 50%
        availability_factor = math.sqrt(availability)
    else:
        availability_factor = 1.0
    
    # Age adjustment
    category = get_age_category(age)
    if category == "young":
        age_factor = 1.15
    elif category == "prime":
        age_factor = 1.0
    elif category == "veteran":
        age_factor = 0.95
    else:  # aging
        age_factor = 0.85
    
    return base_fppg * availability_factor * age_factor


def load_player_ages(data: FantasyData) -> dict[str, int]:
    """Load player ages from PLAYERLIST."""
    ages = {}
    if hasattr(data, 'playerlist') and 'age' in data.playerlist.columns:
        for _, row in data.playerlist.iterrows():
            ages[row['player_name']] = int(row['age']) if pd.notna(row['age']) else 26  # Default to 26
    return ages


# =============================================================================
# POSITION NEED ANALYSIS
# =============================================================================

def compute_position_needs(data: FantasyData) -> dict[str, list[PositionNeed]]:
    """
    Compute positional need scores for each manager.
    
    Need score based on:
    - Total projected FPPG at position vs league average
    - Depth at position
    - Position slots available
    """
    team_projections = load_all_team_projections(data)
    
    # Compute league averages by position
    position_totals = {"G": [], "F": [], "C": []}
    
    for manager in MANAGERS:
        team = team_projections[manager]
        pos_fp = {"G": 0.0, "F": 0.0, "C": 0.0}
        
        for player in team.players.values():
            pos_group = classify_position_group(player.positions)
            pos_fp[pos_group] += player.projected_fppg
        
        for pos in ["G", "F", "C"]:
            position_totals[pos].append((manager, pos_fp[pos]))
    
    # Calculate league averages
    league_avg = {
        pos: sum(x[1] for x in totals) / len(totals)
        for pos, totals in position_totals.items()
    }
    
    # Compute need scores
    needs = {m: [] for m in MANAGERS}
    
    for manager in MANAGERS:
        team = team_projections[manager]
        
        for pos in ["G", "F", "C"]:
            manager_total = next(
                x[1] for x in position_totals[pos] if x[0] == manager
            )
            
            # Need score = how far below average (higher = more need).
            # Guard against a zero league average: in the final week there are
            # no upcoming games to project, so every team's positional
            # projection can be 0, which would divide-by-zero here. If the
            # league average is 0, there is no meaningful need to flag.
            diff = league_avg[pos] - manager_total
            if league_avg[pos] > 0:
                need_score = max(0, diff / league_avg[pos] * 100)
            else:
                need_score = 0
            
            if need_score > 5:  # FIXED: Lower threshold to capture more needs
                pos_name = {"G": "Guards", "F": "Forwards", "C": "Centers"}[pos]
                needs[manager].append(PositionNeed(
                    manager=manager,
                    position=pos,
                    need_score=need_score,
                    current_strength=manager_total,
                    reason=f"{manager}'s {pos_name} rank below league average by {diff:.1f} FPPG",
                ))
        
        # Sort by need score
        needs[manager].sort(key=lambda x: x.need_score, reverse=True)
    
    return needs


# =============================================================================
# TRADE IDEAS - WITH SITUATIONAL AWARENESS
# =============================================================================

def generate_trade_ideas(
    data: FantasyData,
    position_needs: dict[str, list[PositionNeed]],
    title_odds: dict[str, float] = None,
    max_ideas: int = 4,
    week: int = None,
    keeper_watch: dict = None,
) -> list[TradeIdea]:
    """
    Generate realistic trade ideas based on keeper league dynamics,
    team situations (contender vs rebuilder), and player ages.
    
    KEEPER LEAGUE LOGIC:
    - Each team keeps 6 players per year
    - Top 6 players by value = "keepers" (hard to acquire)
    - Players 7+ = "trade block" (expendable, likely gone next year anyway)
    - To get a keeper, you need a competitive package (keeper + pick, or 2-for-1)
    
    SITUATIONAL AWARENESS:
    - Contenders want proven production NOW
    - Rebuilders want youth, upside, and draft picks
    - Young players have dynasty premium
    - Aging stars are sell candidates for rebuilders
    
    VALUATION:
    - Uses keepability V2 scores (multi-year, 0-100 scale) when available.
      These factor in 3-year FPPG, peak FPPG, availability, consistency,
      age curve, and positional scarcity.
    - Falls back to compute_trade_value() (single-season) if keeper_watch
      not provided.
    """
    team_projections = load_all_team_projections(data)
    player_ages = load_player_ages(data)
    ideas = []
    
    # Get current week for trade value calculations
    current_week = week or getattr(data, 'current_week', 13) or 13
    
    # Default title odds if not provided
    if title_odds is None:
        title_odds = {m: 25.0 for m in MANAGERS}  # Assume equal odds
    
    # Build keepability lookup from V2 keeper_watch data (if available)
    # Maps player_name -> {"score": float, "tier": str}
    keepability_lookup = {}
    if keeper_watch:
        for p in keeper_watch.get("players", []):
            keepability_lookup[p["player_name"]] = {
                "score": p.get("keepability_score", 0),
                "tier": p.get("keeper_tier", ""),
            }
    
    # Categorize each manager's situation
    team_situations = {m: get_team_situation(title_odds.get(m, 25.0)) for m in MANAGERS}
    
    # Categorize each team's players into tiers
    # Use TRADE VALUE (keepability V2 if available, else legacy) for sorting
    team_tiers = {}
    for manager in MANAGERS:
        team = team_projections[manager]
        
        # Add age, trade_value, and keeper_tier to each player
        for p in team.players.values():
            p.age = player_ages.get(p.player_name, 26)
            
            # Use V2 keepability score if available, else fall back to legacy
            kd = keepability_lookup.get(p.player_name)
            if kd and kd["score"] > 0:
                p.trade_value = kd["score"]
                p.keeper_tier = kd["tier"]
            else:
                p.trade_value = compute_trade_value(p, p.age, current_week)
                p.keeper_tier = ""
        
        # Sort by trade value (accounts for actual performance + availability + age)
        sorted_players = sorted(
            team.players.values(),
            key=lambda p: p.trade_value,
            reverse=True
        )
        
        # Top 3 = core keepers (very hard to pry loose)
        # 4-6 = fringe keepers (available for right price)  
        # 7+ = trade block (expendable)
        team_tiers[manager] = {
            "core": sorted_players[:3] if len(sorted_players) >= 3 else sorted_players,
            "fringe": sorted_players[3:6] if len(sorted_players) >= 6 else sorted_players[3:],
            "block": sorted_players[6:] if len(sorted_players) > 6 else [],
            "all_sorted": sorted_players,
        }
    
    # Get standings for draft pick value (worse teams have better picks).
    # Use the H2H-aware ranker so that ties in record resolve via the league
    # tiebreaker_rules (head-to-head regular-season series, then total points),
    # consistent with the rest of the standings UI.
    from .simulator_playoff_odds import rank_managers_by_standings
    ranked = rank_managers_by_standings(data)  # best record first
    # Draft pick value: worst record gets pick #1, best record gets pick #N.
    pick_value = {mgr: (len(ranked) - idx) for idx, mgr in enumerate(ranked)}
    
    # Helper to describe pick value
    def get_pick_description(manager: str) -> str:
        pv = pick_value[manager]
        if pv == 1:
            return "a lottery pick"
        elif pv == 2:
            return "a high pick"
        elif pv == 3:
            return "a mid-round pick"
        else:
            return "a late pick"
    
    # =========================================================================
    # STRATEGY 1: Trade Block Swaps (most common, most realistic)
    # 1-for-1 deals between expendable players addressing positional needs
    # =========================================================================
    for manager_a in MANAGERS:
        block_a = team_tiers[manager_a]["block"]
        needs_a = position_needs.get(manager_a, [])
        situation_a = team_situations[manager_a]
        
        if not block_a:
            continue
            
        for manager_b in MANAGERS:
            if manager_b == manager_a:
                continue
                
            block_b = team_tiers[manager_b]["block"]
            needs_b = position_needs.get(manager_b, [])
            situation_b = team_situations[manager_b]
            
            if not block_b:
                continue
            
            # Find complementary swaps
            for player_a in block_a:
                pos_a = classify_position_group(player_a.positions)
                age_a = getattr(player_a, 'age', 26)
                
                for player_b in block_b:
                    pos_b = classify_position_group(player_b.positions)
                    age_b = getattr(player_b, 'age', 26)
                    
                    # Skip same position (no point)
                    if pos_a == pos_b:
                        continue
                    
                    # Check if this addresses needs
                    a_needs_pos_b = any(n.position == pos_b for n in needs_a)
                    b_needs_pos_a = any(n.position == pos_a for n in needs_b)
                    
                    if not (a_needs_pos_b or b_needs_pos_a):
                        continue
                    
                    # Value should be reasonably close
                    # trade_value is keepability V2 score (0-100) when available,
                    # or legacy blended FPPG (~20-60) as fallback.
                    # Use adaptive threshold: V2 scores are on wider scale.
                    val_a = getattr(player_a, 'trade_value', player_a.projected_fppg)
                    val_b = getattr(player_b, 'trade_value', player_b.projected_fppg)
                    value_diff = abs(val_a - val_b)
                    
                    # Max gap for fair swap (scaled to whichever valuation system is active)
                    max_gap = 20 if keepability_lookup else 12
                    if value_diff > max_gap:
                        continue
                    
                    pos_name_a = {"G": "guard", "F": "forward", "C": "center"}[pos_a]
                    pos_name_b = {"G": "guard", "F": "forward", "C": "center"}[pos_b]
                    
                    # Build rationale with age context
                    age_note = ""
                    if age_a <= AGE_YOUNG and age_b > AGE_PRIME_END:
                        age_note = f" ({player_a.player_name} has youth upside)"
                    elif age_b <= AGE_YOUNG and age_a > AGE_PRIME_END:
                        age_note = f" ({player_b.player_name} has youth upside)"
                    
                    if a_needs_pos_b and b_needs_pos_a:
                        rationale = f"Win-win: {manager_a} gets {pos_name_b} help, {manager_b} gets {pos_name_a} depth{age_note}"
                    elif a_needs_pos_b:
                        rationale = f"{manager_a} addresses {pos_name_b} need with expendable piece{age_note}"
                    else:
                        rationale = f"{manager_b} addresses {pos_name_a} need with expendable piece{age_note}"
                    
                    ideas.append(TradeIdea(
                        manager_a=manager_a,
                        manager_b=manager_b,
                        gives_a=[player_a.player_name],
                        receives_a=[player_b.player_name],
                        rationale=rationale,
                        fit_score=70 + (12 - value_diff) + (5 if a_needs_pos_b and b_needs_pos_a else 0),
                        trade_type="swap",
                    ))
    
    # =========================================================================
    # STRATEGY 2A: 2-for-1 Consolidation (CONTENDER move)
    # Contender packages depth for a star - win-now mode
    # =========================================================================
    for manager_a in MANAGERS:
        situation_a = team_situations[manager_a]
        
        # Only contenders/fringe teams want to consolidate
        if situation_a == "rebuilder":
            continue
        
        fringe_a = team_tiers[manager_a]["fringe"]
        block_a = team_tiers[manager_a]["block"]
        offer_pool = fringe_a + block_a[:3]
        
        if len(offer_pool) < 2:
            continue
        
        for manager_b in MANAGERS:
            if manager_b == manager_a:
                continue
            
            # Target B's core or top fringe players
            core_b = team_tiers[manager_b]["core"]
            top_fringe_b = team_tiers[manager_b]["fringe"][:2] if team_tiers[manager_b]["fringe"] else []
            targets_b = core_b + top_fringe_b
            
            if not targets_b:
                continue
            
            for i, player1 in enumerate(offer_pool):
                for player2 in offer_pool[i+1:]:
                    # Use trade_value for comparison (accounts for actual perf + availability)
                    val1 = getattr(player1, 'trade_value', player1.projected_fppg)
                    val2 = getattr(player2, 'trade_value', player2.projected_fppg)
                    combined_value = val1 + val2
                    
                    for target in targets_b:
                        target_val = getattr(target, 'trade_value', target.projected_fppg)
                        ratio = combined_value / target_val if target_val > 0 else 0
                        
                        if ratio < 1.3 or ratio > 1.9:
                            continue
                        
                        # Minimum value threshold (scaled to valuation system)
                        min_val = 35 if keepability_lookup else 20
                        if val1 < min_val or val2 < min_val:
                            continue
                        
                        target_pos = classify_position_group(target.positions)
                        target_age = getattr(target, 'age', 26)
                        needs_a = position_needs.get(manager_a, [])
                        fills_need = any(n.position == target_pos for n in needs_a)
                        
                        pos_name = {"G": "guard", "F": "forward", "C": "center"}[target_pos]
                        situation_desc = "in title contention" if situation_a == "contender" else "pushing for playoffs"
                        
                        # Add age context
                        age_context = ""
                        if target_age <= AGE_YOUNG:
                            age_context = f" (and {target.player_name}'s {get_age_description(target_age)} upside)"
                        
                        ideas.append(TradeIdea(
                            manager_a=manager_a,
                            manager_b=manager_b,
                            gives_a=[player1.player_name, player2.player_name],
                            receives_a=[target.player_name],
                            rationale=f"{manager_a}, {situation_desc}, consolidates for star {pos_name}{age_context}; {manager_b} gains flexibility",
                            fit_score=90 + (10 if fills_need else 0) + (target_val / 10),
                            trade_type="2-for-1",
                        ))
    
    # =========================================================================
    # STRATEGY 2B: 2-for-1 Expansion (REBUILDER move)  
    # Rebuilder trades aging star for young pieces + roster flexibility
    # =========================================================================
    for manager_a in MANAGERS:
        situation_a = team_situations[manager_a]
        
        # Only rebuilders want to expand/sell
        if situation_a != "rebuilder":
            continue
        
        # Look for aging stars to sell (use trade_value threshold, not projected)
        # V2 keepability: >=50 is Strong Hold territory; V1: >=30 was solid
        all_players_a = team_tiers[manager_a]["all_sorted"]
        min_star_val = 45 if keepability_lookup else 30
        aging_stars = [p for p in all_players_a[:6] 
                       if getattr(p, 'age', 26) >= 30 
                       and getattr(p, 'trade_value', p.projected_fppg) >= min_star_val]
        
        if not aging_stars:
            continue
        
        for aging_star in aging_stars:
            star_age = getattr(aging_star, 'age', 26)
            star_value = getattr(aging_star, 'trade_value', aging_star.projected_fppg)
            
            for manager_b in MANAGERS:
                if manager_b == manager_a:
                    continue
                
                situation_b = team_situations[manager_b]
                
                # Contenders are best trade partners for aging stars
                if situation_b == "rebuilder":
                    continue
                
                # B offers two younger players
                all_players_b = team_tiers[manager_b]["all_sorted"]
                young_pieces = [p for p in all_players_b[3:10] if getattr(p, 'age', 26) <= AGE_PRIME_END]
                
                if len(young_pieces) < 2:
                    continue
                
                # Pick two pieces that roughly match value
                for i, piece1 in enumerate(young_pieces):
                    for piece2 in young_pieces[i+1:]:
                        val1 = getattr(piece1, 'trade_value', piece1.projected_fppg)
                        val2 = getattr(piece2, 'trade_value', piece2.projected_fppg)
                        combined = val1 + val2
                        ratio = combined / star_value if star_value > 0 else 0
                        
                        if ratio < 1.2 or ratio > 1.8:
                            continue
                        
                        age1 = getattr(piece1, 'age', 26)
                        age2 = getattr(piece2, 'age', 26)
                        avg_age = (age1 + age2) / 2
                        
                        # Prefer if return is significantly younger
                        if avg_age >= star_age - 3:
                            continue
                        
                        star_pos = classify_position_group(aging_star.positions)
                        pos_name = {"G": "guard", "F": "forward", "C": "center"}[star_pos]
                        
                        ideas.append(TradeIdea(
                            manager_a=manager_a,
                            manager_b=manager_b,
                            gives_a=[aging_star.player_name],
                            receives_a=[piece1.player_name, piece2.player_name],
                            rationale=f"{manager_a}, looking to next season, moves {get_age_description(star_age)} {aging_star.player_name} for younger assets; {manager_b} gets win-now {pos_name}",
                            fit_score=88 + (star_age - 30) * 2 + (30 - avg_age),
                            trade_type="sell-high",
                        ))
    
    # =========================================================================
    # STRATEGY 3: Keeper + Pick Deals
    # Fringe keeper + draft pick for slight upgrade
    # =========================================================================
    for manager_a in MANAGERS:
        fringe_a = team_tiers[manager_a]["fringe"]
        situation_a = team_situations[manager_a]
        
        if not fringe_a:
            continue
        
        pick_desc_a = get_pick_description(manager_a)
        
        for manager_b in MANAGERS:
            if manager_b == manager_a:
                continue
            
            fringe_b = team_tiers[manager_b]["fringe"]
            situation_b = team_situations[manager_b]
            
            if not fringe_b:
                continue
            
            for player_a in fringe_a:
                age_a = getattr(player_a, 'age', 26)
                val_a = getattr(player_a, 'trade_value', player_a.projected_fppg)
                
                for player_b in fringe_b:
                    age_b = getattr(player_b, 'age', 26)
                    val_b = getattr(player_b, 'trade_value', player_b.projected_fppg)
                    upgrade = val_b - val_a
                    
                    if upgrade < 1 or upgrade > 15:
                        continue
                    
                    pos_a = classify_position_group(player_a.positions)
                    pos_b = classify_position_group(player_b.positions)
                    
                    needs_a = position_needs.get(manager_a, [])
                    a_needs_pos_b = any(n.position == pos_b for n in needs_a)
                    
                    # Adjust rationale based on team situations
                    if situation_b == "rebuilder":
                        rationale = f"{manager_a} upgrades{' at ' + {'G': 'guard', 'F': 'forward', 'C': 'center'}[pos_b] if a_needs_pos_b else ''} with draft capital; {manager_b} stockpiles picks for rebuild"
                    else:
                        rationale = f"{manager_a} upgrades{' at ' + {'G': 'guard', 'F': 'forward', 'C': 'center'}[pos_b] if a_needs_pos_b else ''} with draft capital; {manager_b} builds for future"
                    
                    ideas.append(TradeIdea(
                        manager_a=manager_a,
                        manager_b=manager_b,
                        gives_a=[player_a.player_name, f"+ {pick_desc_a}"],
                        receives_a=[player_b.player_name],
                        rationale=rationale,
                        fit_score=75 + upgrade + (pick_value[manager_a] * 2) + (5 if a_needs_pos_b else 0),
                        trade_type="player + pick",
                    ))
    
    # =========================================================================
    # STRATEGY 4: Buy-Low on Underperformers
    # Target players performing below projections
    # =========================================================================
    underperformers = get_underperformers(data, threshold=0.7)
    
    for up in underperformers[:5]:
        owner = up["manager"]
        player_name = up["player_name"]
        situation_owner = team_situations[owner]
        
        owner_tiers = team_tiers[owner]
        player_tier = None
        player_obj = None
        
        for p in owner_tiers["all_sorted"]:
            if p.player_name == player_name:
                player_obj = p
                idx = owner_tiers["all_sorted"].index(p)
                if idx < 3:
                    player_tier = "core"
                elif idx < 6:
                    player_tier = "fringe"
                else:
                    player_tier = "block"
                break
        
        if not player_obj or player_tier == "core":
            continue
        
        player_age = getattr(player_obj, 'age', 26)
        
        for buyer in MANAGERS:
            if buyer == owner:
                continue
            
            situation_buyer = team_situations[buyer]
            buyer_block = team_tiers[buyer]["block"]
            
            if not buyer_block:
                continue
            
            best_offer = max(buyer_block, key=lambda p: getattr(p, 'trade_value', p.projected_fppg))
            best_offer_val = getattr(best_offer, 'trade_value', best_offer.projected_fppg)
            player_val = getattr(player_obj, 'trade_value', player_obj.projected_fppg)
            
            if best_offer_val < player_val * 0.6:
                continue
            
            pos = classify_position_group(player_obj.positions)
            pos_name = {"G": "guard", "F": "forward", "C": "center"}[pos]
            
            # Add context based on situations
            if situation_owner == "rebuilder" and player_age >= 30:
                context = f"; {owner} may be ready to move on"
            elif player_age <= AGE_YOUNG:
                context = f" ({get_age_description(player_age)} with upside)"
            else:
                context = ""
            
            ideas.append(TradeIdea(
                manager_a=buyer,
                manager_b=owner,
                gives_a=[best_offer.player_name],
                receives_a=[player_name],
                rationale=f"Buy-low opportunity: {player_name} is underperforming but has {pos_name} upside{context}",
                fit_score=80 + (player_val - best_offer_val) / 3,
                trade_type="buy-low",
            ))
    
    # =========================================================================
    # FINAL SELECTION: Ensure variety in trade types and no duplicate players
    # =========================================================================
    
    # Group ideas by trade type
    ideas_by_type = {}
    for idea in ideas:
        if idea.trade_type not in ideas_by_type:
            ideas_by_type[idea.trade_type] = []
        ideas_by_type[idea.trade_type].append(idea)
    
    # Sort each group by fit score
    for trade_type in ideas_by_type:
        ideas_by_type[trade_type].sort(key=lambda x: x.fit_score, reverse=True)
    
    final_ideas = []
    used_players = set()
    
    # First pass: try to get one of each trade type
    trade_type_priority = ["swap", "2-for-1", "sell-high", "player + pick", "buy-low"]
    
    for trade_type in trade_type_priority:
        if trade_type not in ideas_by_type:
            continue
        
        for idea in ideas_by_type[trade_type]:
            players_in_trade = set()
            for p in idea.gives_a + idea.receives_a:
                if not p.startswith("+"):
                    players_in_trade.add(p)
            
            if players_in_trade & used_players:
                continue
            
            final_ideas.append(idea)
            used_players.update(players_in_trade)
            break
        
        if len(final_ideas) >= max_ideas:
            break
    
    # Second pass: fill remaining slots with best available
    if len(final_ideas) < max_ideas:
        all_remaining = []
        for ideas_list in ideas_by_type.values():
            all_remaining.extend(ideas_list)
        all_remaining.sort(key=lambda x: x.fit_score, reverse=True)
        
        for idea in all_remaining:
            if idea in final_ideas:
                continue
            
            players_in_trade = set()
            for p in idea.gives_a + idea.receives_a:
                if not p.startswith("+"):
                    players_in_trade.add(p)
            
            if players_in_trade & used_players:
                continue
            
            final_ideas.append(idea)
            used_players.update(players_in_trade)
            
            if len(final_ideas) >= max_ideas:
                break
    
    return final_ideas


# =============================================================================
# FREE AGENT TARGETS
# =============================================================================

def analyze_free_agents(
    data: FantasyData,
    position_needs: dict[str, list[PositionNeed]],
    week: int = None,
    max_targets: int = 5,
) -> list[FreeAgentTarget]:
    """Identify best free agent targets with specific manager recommendations.
    
    Factors in:
    - Positional need for each manager
    - Injury situations (managers with injured players need more help)
    - Schedule advantage (games in next 2 weeks)
    - Player quality (projected FPPG)
    
    Note: Players listed in INJURY_OVERRIDES are excluded from recommendations.
    """
    free_agents = data.get_free_agents()
    
    if free_agents.empty:
        return []
    
    # Build set of injured player names from INJURY_OVERRIDES
    injured_players = set()
    for player in data.injury_overrides.get("players", []):
        player_name = player.get("player_name", "")
        out_weeks = player.get("out_weeks", [])
        # Exclude if player has ANY weeks they're out for
        if player_name and out_weeks:
            injured_players.add(player_name)
    
    # Filter out injured players from free agents
    if injured_players:
        free_agents = free_agents[~free_agents["player_name"].isin(injured_players)]
    
    if free_agents.empty:
        return []
    
    # Build a quick lookup of position need scores per manager
    need_scores = {manager: {"G": 0, "F": 0, "C": 0} for manager in MANAGERS}
    for manager in MANAGERS:
        for need in position_needs[manager]:
            need_scores[manager][need.position] = need.need_score
    
    # Get injury info - managers with injured stars need more help
    injury_boost = {manager: {"G": 0, "F": 0, "C": 0} for manager in MANAGERS}
    for player in data.injury_overrides.get("players", []):
        player_name = player.get("player_name", "")
        out_weeks = player.get("out_weeks", [])
        
        if len(out_weeks) >= 2:
            for _, row in data.lineups.iterrows():
                if row["player_name"] == player_name:
                    manager = row["manager"]
                    positions = get_position_list(row.get("positions", ""))
                    pos_group = classify_position_group(positions)
                    injury_boost[manager][pos_group] += 15
                    break
    
    # Calculate games per team for next 2 weeks
    games_next_2_weeks = {}
    if week is not None:
        from datetime import datetime, timedelta
        
        next_2_weeks_dates = []
        for w in data.schedule.get("weeks", []):
            if w["week"] in [week + 1, week + 2]:
                start = datetime.strptime(w["start_date"], "%Y-%m-%d").date()
                end = datetime.strptime(w["end_date"], "%Y-%m-%d").date()
                current = start
                while current <= end:
                    next_2_weeks_dates.append(current)
                    current += timedelta(days=1)
        
        for d in next_2_weeks_dates:
            games = data.get_nba_games_for_date(d)
            for game in games:
                home = game.get("home_team", "")
                away = game.get("away_team", "")
                if home:
                    games_next_2_weeks[home] = games_next_2_weeks.get(home, 0) + 1
                if away:
                    games_next_2_weeks[away] = games_next_2_weeks.get(away, 0) + 1
    
    targets = []
    
    # Consider ALL free agents with proj FPPG >= 20 (wider pool than just top 15)
    viable_fas = free_agents[free_agents["projectedFPPG"] >= 20].copy()
    
    for _, fa_row in viable_fas.iterrows():
        player_name = fa_row["player_name"]
        proj_fppg = float(fa_row.get("projectedFPPG", 0))
        positions_str = fa_row.get("player_position(s)", "")
        positions = get_position_list(positions_str)
        pos_group = classify_position_group(positions)
        nba_team = fa_row.get("player_nba_team", "")
        
        # Get games in next 2 weeks for this player's team
        games_upcoming = games_next_2_weeks.get(nba_team, 0)
        
        # Calculate fit score for each manager and create a target for EACH manager
        # This allows the variety filter to pick the best combination later
        for manager in MANAGERS:
            base_need = need_scores[manager].get(pos_group, 0)
            injury_need = injury_boost[manager].get(pos_group, 0)
            total_need = base_need + injury_need
            
            # FIT SCORE FORMULA:
            # - Base: projected FPPG (quality floor)
            # - Schedule bonus: +3 points per game above 6 games (avg is ~7 games/2 weeks)
            # - Need multiplier: boosts score based on positional need
            
            schedule_bonus = max(0, (games_upcoming - 6)) * 3
            base_score = proj_fppg + schedule_bonus
            need_multiplier = 1 + (total_need / 30)
            fit_score = base_score * need_multiplier
            
            has_injury_need = injury_need > 0
            
            # Build reason string - include schedule info when relevant
            games_str = f", {games_upcoming} games next 2 weeks" if games_upcoming >= 8 else ""
            
            if has_injury_need:
                reason = f"Addresses {manager}'s injury-depleted {pos_group} corps ({proj_fppg:.1f} FPPG{games_str})"
            elif total_need > 10:
                reason = f"Fills {manager}'s {pos_group} weakness ({proj_fppg:.1f} FPPG{games_str})"
            elif games_upcoming >= 8:
                reason = f"Schedule advantage for {manager} ({proj_fppg:.1f} FPPG{games_str})"
            else:
                reason = f"Best fit for {manager} at {pos_group} ({proj_fppg:.1f} FPPG)"
            
            targets.append(FreeAgentTarget(
                player_name=player_name,
                positions=positions,
                projected_fppg=proj_fppg,
                target_manager=manager,
                fit_score=fit_score,
                reason=reason,
            ))
    
    # Sort by fit score
    targets.sort(key=lambda x: x.fit_score, reverse=True)
    
    # Return top targets with variety rules:
    # - Max 2 recommendations per manager
    # - No duplicate manager+position combinations
    selected = []
    players_covered = set()
    manager_count = {m: 0 for m in MANAGERS}
    manager_position_used = set()
    
    for target in targets:
        if len(selected) >= max_targets:
            break
        
        if target.player_name in players_covered:
            continue
        
        if manager_count[target.target_manager] >= 2:
            continue
        
        pos_group = classify_position_group(target.positions)
        manager_pos_key = (target.target_manager, pos_group)
        
        if manager_pos_key in manager_position_used:
            continue
        
        selected.append(target)
        players_covered.add(target.player_name)
        manager_count[target.target_manager] += 1
        manager_position_used.add(manager_pos_key)
    
    return selected



# =============================================================================
# DROP CANDIDATES
# =============================================================================

def compute_last_14_days_underperformance(
    data: FantasyData,
    player_name: str,
    manager: str,
) -> Optional[float]:
    """
    Compute underperformance index for last 14 calendar days.
    
    Index = (actual FPPG - projected FPPG) / projected FPPG * 100
    
    Returns:
        Underperformance index (percentage), or None if not enough data
    """
    from datetime import datetime, timedelta
    
    # Get the most recent game date in the data
    most_recent_date = pd.to_datetime(data.playerlog["date"]).max()
    cutoff_date = most_recent_date - timedelta(days=14)
    
    # Get player's games in last 14 days
    mask = (
        (data.playerlog["player_name"] == player_name) &
        (data.playerlog["manager"] == manager) &
        (pd.to_datetime(data.playerlog["date"]) > cutoff_date) &
        (data.playerlog["started"] == True) &
        (data.playerlog["is_injured"] == False)
    )
    
    games = data.playerlog[mask]
    
    if len(games) < 2:
        return None
    
    actual_fppg = games["fantasy_points"].mean()
    projected_fppg = data.get_player_projection(player_name)
    
    if projected_fppg is None or projected_fppg <= 0:
        return None
    
    return ((actual_fppg - projected_fppg) / projected_fppg) * 100


def identify_drop_candidates(
    data: FantasyData,
    threshold: float = -15.0,
    max_candidates: int = 6,
    weeks_lookback: int = 4,
) -> list[DropCandidate]:
    """Identify players who should be considered for dropping."""
    underperformers = get_underperformers(data, threshold=threshold, weeks_lookback=weeks_lookback)
    free_agents = data.get_free_agents()
    
    candidates = []
    
    for up in underperformers:
        player_name = up["player_name"]
        manager = up["manager"]
        index = up["underperformance_index"]
        proj_fppg = up["projected_fppg"] or 0
        
        # Determine how long player has been on this manager's roster CONTINUOUSLY
        # Use LINEUPS (not PLAYERLOG) because LINEUPS shows full roster every day,
        # while PLAYERLOG only has rows for players who had games
        player_lineups = data.lineups[
            (data.lineups["player_name"] == player_name) &
            (data.lineups["manager"] == manager)
        ]
        
        current_week = data.current_week
        
        if not player_lineups.empty:
            # Get unique weeks they were on the roster, sorted descending
            weeks_on_team = sorted(player_lineups["week"].unique(), reverse=True)
            
            # Walk backwards from current week to find when the current stint started
            # A "gap" means they were dropped and re-added
            stint_start_week = current_week
            for i, week in enumerate(weeks_on_team):
                if i == 0:
                    stint_start_week = week
                else:
                    # Check if there's a gap (more than 1 week between appearances)
                    prev_week = weeks_on_team[i - 1]
                    if prev_week - week > 1:
                        # Found a gap - current stint started at prev_week
                        break
                    stint_start_week = week
            
            weeks_on_roster = current_week - stint_start_week + 1
        else:
            weeks_on_roster = weeks_lookback  # Assume full tenure if no data
        
        # Check if there's a better FA available at same position
        player_positions = []
        roster = data.lineups[
            (data.lineups["player_name"] == player_name) &
            (data.lineups["manager"] == manager)
        ]
        if not roster.empty:
            player_positions = get_position_list(roster.iloc[0].get("positions", ""))
        
        pos_group = classify_position_group(player_positions)
        
        # Get list of injured players to exclude from FA recommendations
        injured_players = {
            p["player_name"] for p in data.injury_overrides.get("players", [])
        }
        
        # Find better FA - only suggest if FA projection beats player's PROJECTION
        # (not their actual production). We don't want to suggest dropping a star
        # player for a lesser player just because the star is slumping.
        better_fa = None
        if not free_agents.empty:
            for _, fa_row in free_agents.iterrows():
                fa_name = fa_row["player_name"]
                
                # Skip injured players
                if fa_name in injured_players:
                    continue
                
                fa_positions = get_position_list(fa_row.get("player_position(s)", ""))
                fa_pos_group = classify_position_group(fa_positions)
                
                if fa_pos_group == pos_group:
                    fa_fppg = float(fa_row.get("projectedFPPG", 0))
                    # FA is "better" only if their projection beats player's projection
                    if fa_fppg > proj_fppg:
                        better_fa = fa_name
                        break
        
        # Calculate last 14 days underperformance
        last_14_index = compute_last_14_days_underperformance(data, player_name, manager)
        
        # Get team name for reason string
        team_name = MANAGER_TO_TEAM.get(manager, manager)
        
        # Determine timeframe phrasing based on tenure
        # If player has been on roster less than the lookback period, say "since joining"
        # Otherwise, say "over the last X weeks"
        if weeks_on_roster < weeks_lookback:
            timeframe = f"since joining {team_name}"
        else:
            timeframe = f"over the last {weeks_lookback} weeks on {team_name}"
        
        # Build reason string with trend context
        if last_14_index is not None:
            # Check if values are essentially the same (within 0.5%)
            if abs(last_14_index - index) < 0.5:
                # Same values - don't repeat the number
                reason = f"{abs(index):.1f}% below projection {timeframe} - consistently underperforming"
            elif last_14_index < index - 5:
                # Getting worse (last 14 days worse than tenure)
                reason = f"{abs(index):.1f}% below projection {timeframe}, {abs(last_14_index):.1f}% last 14 days - trending down"
            elif last_14_index > index + 5:
                # Improving (last 14 days better than tenure)
                reason = f"{abs(index):.1f}% below projection {timeframe}, {abs(last_14_index):.1f}% last 14 days - showing improvement"
            else:
                # Consistently bad (within 5% but not identical)
                reason = f"{abs(index):.1f}% below projection {timeframe}, {abs(last_14_index):.1f}% last 14 days - consistently underperforming"
        else:
            reason = f"{abs(index):.1f}% below projection {timeframe}, no recent games"
        
        candidates.append(DropCandidate(
            player_name=player_name,
            manager=manager,
            projected_fppg=proj_fppg,
            underperformance_index=index,
            underperformance_index_last_14_days=last_14_index,
            reason=reason,
            better_fa_available=better_fa,
        ))
    
    return candidates[:max_candidates]


def identify_hot_streak_candidates(
    data: FantasyData,
    threshold: float = 15.0,
    max_candidates: int = 6,
    weeks_lookback: int = 4,
) -> list[HotStreakCandidate]:
    """Identify players on hot streaks who have elevated trade value."""
    overperformers = get_overperformers(data, threshold=threshold, weeks_lookback=weeks_lookback)
    
    candidates = []
    
    for op in overperformers:
        player_name = op["player_name"]
        manager = op["manager"]
        index = op["overperformance_index"]
        proj_fppg = op["projected_fppg"] or 0
        
        # Determine how long player has been on this manager's roster CONTINUOUSLY
        # Use LINEUPS (not PLAYERLOG) because LINEUPS shows full roster every day
        player_lineups = data.lineups[
            (data.lineups["player_name"] == player_name) &
            (data.lineups["manager"] == manager)
        ]
        
        current_week = data.current_week
        
        if not player_lineups.empty:
            # Get unique weeks they were on the roster, sorted descending
            weeks_on_team = sorted(player_lineups["week"].unique(), reverse=True)
            
            # Walk backwards from current week to find when the current stint started
            stint_start_week = current_week
            for i, week in enumerate(weeks_on_team):
                if i == 0:
                    stint_start_week = week
                else:
                    prev_week = weeks_on_team[i - 1]
                    if prev_week - week > 1:
                        break
                    stint_start_week = week
            
            weeks_on_roster = current_week - stint_start_week + 1
        else:
            weeks_on_roster = weeks_lookback
        
        # Calculate last 14 days overperformance (reuse the underperformance function - it works for both)
        last_14_index = compute_last_14_days_underperformance(data, player_name, manager)
        
        # Get team name for reason string
        team_name = MANAGER_TO_TEAM.get(manager, manager)
        
        # Determine timeframe phrasing based on tenure
        if weeks_on_roster < weeks_lookback:
            timeframe = f"since joining {team_name}"
        else:
            timeframe = f"over the last {weeks_lookback} weeks on {team_name}"
        
        # Build reason string with trend context
        if last_14_index is not None:
            if abs(last_14_index - index) < 0.5:
                reason = f"{index:.1f}% above projection {timeframe} - consistently overperforming"
            elif last_14_index > index + 5:
                # Getting even hotter (last 14 days better than 4-week average)
                reason = f"{index:.1f}% above projection {timeframe}, {last_14_index:.1f}% last 14 days - trending up"
            elif last_14_index < index - 5:
                # Cooling off (last 14 days worse than 4-week average)
                reason = f"{index:.1f}% above projection {timeframe}, {last_14_index:.1f}% last 14 days - cooling off"
            else:
                reason = f"{index:.1f}% above projection {timeframe}, {last_14_index:.1f}% last 14 days - consistently overperforming"
        else:
            reason = f"{index:.1f}% above projection {timeframe}, no recent games"
        
        # Generate trade value note based on performance and situation
        # Calculate actual FPPG: actual = projected * (1 + index/100)
        actual_fppg = proj_fppg * (1 + index / 100) if proj_fppg > 0 else 0
        
        if index >= 25:
            trade_value_note = f"Sell high candidate - actual {actual_fppg:.1f} FPPG unlikely to sustain"
        elif index >= 15:
            trade_value_note = f"Elevated trade value - producing {actual_fppg:.1f} FPPG vs {proj_fppg:.1f} projected"
        else:
            trade_value_note = None
        
        candidates.append(HotStreakCandidate(
            player_name=player_name,
            manager=manager,
            projected_fppg=proj_fppg,
            overperformance_index=index,
            overperformance_index_last_14_days=last_14_index,
            reason=reason,
            trade_value_note=trade_value_note,
        ))
    
    return candidates[:max_candidates]


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def generate_rumor_mill_analysis(
    data: FantasyData,
    title_odds: dict[str, float] = None,
    week: int = None,
    freshness_tracker: "FreshnessTracker" = None,
    keeper_watch: dict = None,
) -> RumorMillAnalysis:
    """
    Generate complete Rumor Mill analysis.
    
    Args:
        data: Fantasy data object
        title_odds: Dict of manager -> title probability (0-100)
        week: Current week number (for schedule-based FA analysis)
        freshness_tracker: Optional tracker to filter stale/repetitive content
        keeper_watch: Optional keeper_watch dict from build_keeper_watch()
            with V2 keepability scores. If provided, trade ideas use V2
            scores instead of the legacy compute_trade_value() formula.
    """
    # Compute position needs
    position_needs = compute_position_needs(data)
    
    # Generate larger candidate pools to allow for freshness filtering
    # We generate more than we need, filter, then trim to final counts
    trade_ideas = generate_trade_ideas(
        data, position_needs, title_odds=title_odds, max_ideas=10,
        week=week, keeper_watch=keeper_watch,
    )
    free_agent_targets = analyze_free_agents(data, position_needs, week=week, max_targets=12)
    hot_streak_candidates = identify_hot_streak_candidates(data)
    drop_candidates = identify_drop_candidates(data)
    
    # Target counts for final output
    TARGET_TRADES = 4
    TARGET_FA = 5
    TARGET_HOT_STREAKS = 6
    TARGET_DROPS = 6
    
    # Apply freshness filtering if tracker provided
    if freshness_tracker is not None and week is not None:
        from .content_freshness import (
            filter_fresh_trades, record_shown_trades,
            filter_fresh_fa_targets, record_shown_fa_targets,
            filter_fresh_drop_candidates, record_shown_drop_candidates,
        )
        
        # Filter stale content, with fallback to least-stale if needed to meet quota
        trade_ideas = filter_fresh_trades(trade_ideas, freshness_tracker, week, min_count=TARGET_TRADES)
        free_agent_targets = filter_fresh_fa_targets(free_agent_targets, freshness_tracker, week, min_count=TARGET_FA)
        drop_candidates = filter_fresh_drop_candidates(drop_candidates, freshness_tracker, week, min_count=TARGET_DROPS)
        
        # Trim to final counts
        trade_ideas = trade_ideas[:TARGET_TRADES]
        free_agent_targets = free_agent_targets[:TARGET_FA]
        hot_streak_candidates = hot_streak_candidates[:TARGET_HOT_STREAKS]
        drop_candidates = drop_candidates[:TARGET_DROPS]
        
        # Record what we're showing
        record_shown_trades(trade_ideas, freshness_tracker, week)
        record_shown_fa_targets(free_agent_targets, freshness_tracker, week)
        record_shown_drop_candidates(drop_candidates, freshness_tracker, week)
    else:
        # No tracker - just trim to target counts
        trade_ideas = trade_ideas[:TARGET_TRADES]
        free_agent_targets = free_agent_targets[:TARGET_FA]
        hot_streak_candidates = hot_streak_candidates[:TARGET_HOT_STREAKS]
        drop_candidates = drop_candidates[:TARGET_DROPS]
    
    return RumorMillAnalysis(
        position_needs=position_needs,
        trade_ideas=trade_ideas,
        free_agent_targets=free_agent_targets,
        hot_streak_candidates=hot_streak_candidates,
        drop_candidates=drop_candidates,
    )


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_rumor_mill(analysis: RumorMillAnalysis) -> str:
    """Format Rumor Mill for newsletter output."""
    lines = []
    
    # Trade Ideas
    if analysis.trade_ideas:
        lines.append("TRADE IDEAS")
        for idea in analysis.trade_ideas:
            lines.append(f" -> {idea.manager_a} -> {idea.manager_b}: {idea.gives_a[0]} for {idea.receives_a[0]}")
            lines.append(f"    Rationale: {idea.rationale}")
        lines.append("")
    
    # Free Agent Targets
    if analysis.free_agent_targets:
        lines.append("FREE AGENT TARGETS")
        for target in analysis.free_agent_targets:
            lines.append(f" -> {target.player_name} ({target.projected_fppg:.1f} FPPG) -> {target.target_manager}")
            lines.append(f"    {target.reason}")
        lines.append("")
    
    # Drop Candidates
    if analysis.drop_candidates:
        lines.append("DROP CANDIDATES")
        for drop in analysis.drop_candidates:
            fa_note = f" (Consider: {drop.better_fa_available})" if drop.better_fa_available else ""
            lines.append(f" -> {drop.player_name} ({drop.manager}): {drop.reason}{fa_note}")
        lines.append("")
    
    return "\n".join(lines)


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    
    print(f"Loading data from: {base.absolute()}")
    print("-" * 50)
    
    data = load_all_data(base)
    
    analysis = generate_rumor_mill_analysis(data)
    
    print("\nRumor Mill Analysis:")
    print(format_rumor_mill(analysis))
    
    print("\n" + "=" * 50)
    print("Position Needs Detail:")
    for manager in MANAGERS:
        needs = analysis.position_needs[manager]
        if needs:
            print(f"  {manager}:")
            for need in needs:
                print(f"    {need.position}: {need.need_score:.1f} need score ({need.current_strength:.1f} FPPG)")
