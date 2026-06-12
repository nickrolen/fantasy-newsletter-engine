"""
lineup_optimizer.py

Solves optimal daily lineups respecting position eligibility constraints.
Used for betting lines simulation (high fidelity) and What-If analysis.

Roster structure:
    PG, SG, G, SF, PF, F, C, C, UTIL, UTIL (10 starters)
    BN, BN, BN (3 bench)
    IL, IL, IL+, IL+ (4 injured reserve)
"""

from dataclasses import dataclass, field
from typing import Optional
import itertools

from .data_loader import get_position_list


# =============================================================================
# SLOT DEFINITIONS
# =============================================================================

# Roster slots in order (for optimization)
STARTER_SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "UTIL", "UTIL"]
NUM_STARTERS = 10

# Position eligibility for each slot
SLOT_POSITIONS = {
    "PG": ["PG"],
    "SG": ["SG"],
    "G": ["PG", "SG"],
    "SF": ["SF"],
    "PF": ["PF"],
    "F": ["SF", "PF"],
    "C": ["C"],
    "UTIL": ["PG", "SG", "SF", "PF", "C"],
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PlayerSlot:
    """A player assigned to a specific lineup slot."""
    player_name: str
    slot: str
    projected_fp: float
    positions: list[str]


@dataclass
class OptimizedLineup:
    """Result of lineup optimization."""
    starters: list[PlayerSlot]  # Players in starting slots
    bench: list[str]  # Player names on bench
    
    total_projected_fp: float = 0.0
    num_starters: int = 0
    unfilled_slots: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        self.num_starters = len(self.starters)
        self.total_projected_fp = sum(s.projected_fp for s in self.starters)


@dataclass
class AvailablePlayer:
    """A player available for lineup construction."""
    name: str
    positions: list[str]
    projected_fp: float
    
    def can_fill_slot(self, slot: str) -> bool:
        """Check if player can fill a specific slot."""
        eligible = SLOT_POSITIONS.get(slot, [])
        return any(pos in eligible for pos in self.positions)


# =============================================================================
# LINEUP OPTIMIZATION
# =============================================================================

def optimize_lineup(
    available_players: list[AvailablePlayer],
    slots: list[str] = None,
) -> OptimizedLineup:
    """
    Find optimal lineup assignment to maximize total projected FP.
    
    Uses a greedy assignment that fills the most-constrained slots first.
    Fast enough for simulation purposes (the brute-force backtracking
    fallback was removed: production sims never relied on it).
    
    Args:
        available_players: List of available players with projections
        slots: Slots to fill (default: STARTER_SLOTS)
    
    Returns:
        OptimizedLineup with optimal slot assignments
    """
    if slots is None:
        slots = STARTER_SLOTS.copy()
    
    # Sort players by projected FP (highest first)
    sorted_players = sorted(
        available_players,
        key=lambda p: p.projected_fp,
        reverse=True
    )
    
    # Use greedy assignment
    assignments = _greedy_assign(sorted_players, slots)
    
    # Build result
    starters = []
    assigned_names = set()
    filled_indices = set()
    
    for slot_idx, slot, player in assignments:
        starters.append(PlayerSlot(
            player_name=player.name,
            slot=slot,
            projected_fp=player.projected_fp,
            positions=player.positions,
        ))
        assigned_names.add(player.name)
        filled_indices.add(slot_idx)
    
    # Remaining players go to bench
    bench = [p.name for p in sorted_players if p.name not in assigned_names]
    
    # Find unfilled slots
    unfilled = [slots[i] for i in range(len(slots)) if i not in filled_indices]
    
    lineup = OptimizedLineup(
        starters=starters,
        bench=bench,
        unfilled_slots=unfilled,
    )
    
    return lineup


def _greedy_assign(
    players: list[AvailablePlayer],
    slots: list[str],
) -> list[tuple[int, str, AvailablePlayer]]:
    """
    Greedy slot assignment - assign best available player to each slot.
    
    Returns list of (slot_index, slot_name, player) tuples.
    
    May not be optimal if a high-value player can only fill one slot
    that a lower-value player gets assigned to first.
    """
    assignments = []
    used_players = set()
    
    # Create indexed slots for processing
    indexed_slots = list(enumerate(slots))
    
    # Process slots in a strategic order:
    # 1. Most restrictive slots first (PG, SG, SF, PF, C)
    # 2. Then flexible slots (G, F)
    # 3. UTIL last
    
    def slot_priority(item):
        idx, slot = item
        if slot in ["PG", "SG", "SF", "PF", "C"]:
            return (0, idx)
        elif slot in ["G", "F"]:
            return (1, idx)
        else:  # UTIL
            return (2, idx)
    
    sorted_indexed_slots = sorted(indexed_slots, key=slot_priority)
    
    for slot_idx, slot in sorted_indexed_slots:
        best_player = None
        best_fp = float("-inf")  # -1 sentinel silently dropped legitimate negative-FP games
        
        for player in players:
            if player.name in used_players:
                continue
            if not player.can_fill_slot(slot):
                continue
            if player.projected_fp > best_fp:
                best_fp = player.projected_fp
                best_player = player
        
        if best_player:
            assignments.append((slot_idx, slot, best_player))
            used_players.add(best_player.name)
    
    return assignments


# =============================================================================
# SIMPLIFIED OPTIMIZER (for ROS title odds sim)
# =============================================================================

def select_top_n_players(
    available_players: list[AvailablePlayer],
    n: int = 10,
) -> list[AvailablePlayer]:
    """
    Simple selection: just take top N players by projection.
    
    No position constraints - used for simplified ROS simulation.
    
    Args:
        available_players: List of available players
        n: Number to select
    
    Returns:
        Top N players by projected FP
    """
    sorted_players = sorted(
        available_players,
        key=lambda p: p.projected_fp,
        reverse=True
    )
    return sorted_players[:n]


def compute_simple_daily_score(
    available_players: list[AvailablePlayer],
    max_starters: int = 10,
) -> float:
    """
    Compute daily score using simplified model.
    
    Takes top N players by projection (no position constraints).
    Used for ROS title odds simulation.
    
    Args:
        available_players: Players available to play
        max_starters: Maximum starters (default 10)
    
    Returns:
        Sum of top N projected FP
    """
    top_players = select_top_n_players(available_players, max_starters)
    return sum(p.projected_fp for p in top_players)


# =============================================================================
# WHAT-IF ANALYSIS HELPERS
# =============================================================================

def find_best_swap(
    bench_player: AvailablePlayer,
    current_lineup: OptimizedLineup,
    all_players: list[AvailablePlayer],
) -> Optional[dict]:
    """
    Find the best swap for a bench player into the starting lineup.
    
    Args:
        bench_player: The bench player to swap in
        current_lineup: Current optimized lineup
        all_players: All available players (for rebuilding)
    
    Returns:
        Dict with swap details, or None if no beneficial swap exists
    """
    if bench_player.projected_fp <= 0:
        return None
    
    best_swap = None
    best_gain = 0
    
    # Try swapping bench player into each eligible slot
    for starter in current_lineup.starters:
        if not bench_player.can_fill_slot(starter.slot):
            continue
        
        # Calculate gain from this swap
        gain = bench_player.projected_fp - starter.projected_fp
        
        if gain > best_gain:
            best_gain = gain
            best_swap = {
                "bench_player": bench_player.name,
                "bench_player_fp": bench_player.projected_fp,
                "starter_replaced": starter.player_name,
                "starter_fp": starter.projected_fp,
                "slot": starter.slot,
                "gain": gain,
            }
    
    return best_swap


def analyze_what_if_swaps(
    starters_with_fp: list[dict],  # [{"name": str, "positions": list, "fp": float}, ...]
    bench_with_fp: list[dict],
) -> list[dict]:
    """
    Analyze all potential what-if swaps for a given day.
    
    Args:
        starters_with_fp: Starters with actual FP scored
        bench_with_fp: Bench players with actual FP scored
    
    Returns:
        List of beneficial swaps (gain > 0)
    """
    # Convert to AvailablePlayer format
    starter_players = [
        AvailablePlayer(
            name=s["name"],
            positions=s.get("positions", []),
            projected_fp=s["fp"],  # Using actual FP as "projection" for what-if
        )
        for s in starters_with_fp
    ]
    
    bench_players = [
        AvailablePlayer(
            name=b["name"],
            positions=b.get("positions", []),
            projected_fp=b["fp"],
        )
        for b in bench_with_fp
    ]
    
    # Build pseudo-lineup for analysis
    # Assign starters to slots based on position
    all_players = starter_players + bench_players
    current_lineup = optimize_lineup(starter_players, STARTER_SLOTS)
    
    # Find best swap for each bench player
    swaps = []
    for bench_player in bench_players:
        if bench_player.projected_fp <= 0:
            continue
        
        swap = find_best_swap(bench_player, current_lineup, all_players)
        if swap and swap["gain"] > 0:
            swaps.append(swap)
    
    # Sort by gain (highest first)
    swaps.sort(key=lambda x: x["gain"], reverse=True)
    
    return swaps


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    # Test with sample players
    players = [
        AvailablePlayer("Luka Doncic", ["PG", "SG"], 55.0),
        AvailablePlayer("Shai Gilgeous-Alexander", ["PG", "SG"], 52.0),
        AvailablePlayer("Jayson Tatum", ["SF", "PF"], 48.0),
        AvailablePlayer("Kevin Durant", ["SF", "PF"], 45.0),
        AvailablePlayer("Anthony Davis", ["PF", "C"], 47.0),
        AvailablePlayer("Nikola Jokic", ["C"], 58.0),
        AvailablePlayer("Joel Embiid", ["C"], 54.0),
        AvailablePlayer("Trae Young", ["PG"], 42.0),
        AvailablePlayer("Donovan Mitchell", ["SG"], 40.0),
        AvailablePlayer("LeBron James", ["SF", "PF"], 43.0),
        AvailablePlayer("Kawhi Leonard", ["SF"], 38.0),
        AvailablePlayer("Draymond Green", ["PF", "C"], 25.0),
    ]
    
    print("Available players:")
    for p in players:
        print(f"  {p.name}: {p.positions} - {p.projected_fp}")
    
    print("\n" + "=" * 50)
    print("Optimized Lineup:")
    
    lineup = optimize_lineup(players)
    
    for starter in sorted(lineup.starters, key=lambda s: STARTER_SLOTS.index(s.slot) if s.slot in STARTER_SLOTS else 99):
        print(f"  {starter.slot}: {starter.player_name} ({starter.projected_fp})")
    
    print(f"\nTotal: {lineup.total_projected_fp}")
    print(f"Bench: {lineup.bench}")
    print(f"Unfilled: {lineup.unfilled_slots}")
    
    print("\n" + "=" * 50)
    print("Simple top-10 selection:")
    top10 = select_top_n_players(players, 10)
    print(f"  Players: {[p.name for p in top10]}")
    print(f"  Total: {sum(p.projected_fp for p in top10)}")
