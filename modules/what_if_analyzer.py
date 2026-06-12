"""
what_if_analyzer.py

Analyzes "what if" scenarios - points left on bench, optimal swaps.
Used for the WHAT IF section of the newsletter.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from .data_loader import FantasyData, MANAGERS, get_position_list
from .lineup_optimizer import (
    AvailablePlayer,
    optimize_lineup,
    STARTER_SLOTS,
    SLOT_POSITIONS,
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class BenchSwap:
    """A potential swap from bench to starter."""
    date: str
    bench_player: str
    bench_player_fp: float
    starter_replaced: str
    starter_fp: float
    slot: str
    gain: float
    
    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "bench_player": self.bench_player,
            "bench_player_fp": self.bench_player_fp,
            "starter_replaced": self.starter_replaced,
            "starter_fp": self.starter_fp,
            "slot": self.slot,
            "gain": self.gain,
        }


@dataclass
class Blunder:
    """A bench game left on bench when an open starter slot existed.
    
    A blunder is distinct from a swap: swaps involve two players who both played,
    while blunders involve a bench player who played when a starter slot was
    available (either empty or occupied by a DNP player). Blunders represent
    pure manager negligence -- points left on the table for free.
    """
    date: str
    bench_player: str
    bench_player_fp: float
    available_slot: str
    dnp_starter: str  # Player in the slot who didn't play (or "EMPTY" if no one)
    
    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "bench_player": self.bench_player,
            "bench_player_fp": self.bench_player_fp,
            "available_slot": self.available_slot,
            "dnp_starter": self.dnp_starter,
        }


@dataclass
class DailyWhatIf:
    """What-if analysis for a single day."""
    date: str
    manager: str
    
    # Actual lineup
    starters_fp: float
    bench_fp: float
    
    # Best swap
    best_swap: Optional[BenchSwap]
    
    # Could this have changed anything?
    potential_gain: float
    
    # Blunders: bench games where an open starter slot existed
    blunders: list[Blunder] = field(default_factory=list)


@dataclass
class ManagerWhatIf:
    """What-if analysis for a manager for one week."""
    manager: str
    week: int
    
    # Total points left on bench
    total_bench_points: float
    
    # Total gain possible from optimal swaps
    total_potential_gain: float
    
    # All beneficial swaps
    swaps: list[BenchSwap]
    
    # Blunders: bench games where a starter slot was available
    blunders: list[Blunder] = field(default_factory=list)
    total_blunders: int = 0
    total_blunder_points: float = 0.0
    
    # Daily breakdowns
    daily_analysis: list[DailyWhatIf] = field(default_factory=list)
    
    # Would it have changed the matchup?
    would_flip_matchup: bool = False
    matchup_swing: float = 0.0  # Points needed to flip


@dataclass 
class WeeklyWhatIf:
    """What-if analysis for all managers for one week."""
    week: int
    manager_analysis: dict[str, ManagerWhatIf]
    
    # Notable swaps (significant gains or matchup flips)
    notable_swaps: list[dict]


# =============================================================================
# POSITION HELPERS
# =============================================================================

def can_player_fill_slot(positions: list[str], slot: str) -> bool:
    """Check if a player can fill a given slot based on position eligibility."""
    eligible = SLOT_POSITIONS.get(slot, [])
    return any(pos in eligible for pos in positions)


# =============================================================================
# ANALYSIS FUNCTIONS
# =============================================================================

def analyze_daily_what_if(
    lineups_day: pd.DataFrame,
    playerlog_day: pd.DataFrame,
) -> DailyWhatIf:
    """
    Analyze what-if for a single day.
    
    Args:
        lineups_day: LINEUPS rows for this manager/day
        playerlog_day: PLAYERLOG rows for this manager/day (players who played)
    """
    if lineups_day.empty:
        return None
    
    manager = lineups_day.iloc[0]["manager"]
    date_str = str(lineups_day.iloc[0]["date"])
    
    # Build player FP lookup from playerlog
    fp_lookup = {}
    for _, row in playerlog_day.iterrows():
        player = row["player_name"]
        fp = float(row.get("fantasy_points", 0))
        if not row.get("is_injured", False):
            fp_lookup[player] = fp
    
    # Identify starters, bench, AND DNP starters from lineups
    starters = []
    bench = []
    dnp_starters = []  # Starter slots occupied by players who didn't play
    
    for _, row in lineups_day.iterrows():
        player = row["player_name"]
        slot = str(row["slot"]).upper()
        positions = get_position_list(row.get("positions", ""))
        
        # Skip IL slots
        if slot in ["IL", "IL+"]:
            continue
        
        # Get FP if player had a game
        fp = fp_lookup.get(player)
        
        player_info = {
            "name": player,
            "slot": slot,
            "positions": positions,
            "fp": fp,  # None if didn't play
        }
        
        if slot in ["BN"]:
            if fp is not None:
                bench.append(player_info)
        else:
            if fp is not None:
                starters.append(player_info)
            else:
                # Player is in a starter slot but didn't play -> available slot
                dnp_starters.append(player_info)
    
    # Calculate totals
    starters_fp = sum(p["fp"] for p in starters)
    bench_fp = sum(p["fp"] for p in bench)
    
    # Find best swap (existing logic -- both players played)
    best_swap = None
    best_gain = 0
    
    for bench_player in bench:
        # Find worst starter this bench player could replace
        for starter in starters:
            if not can_player_fill_slot(bench_player["positions"], starter["slot"]):
                continue
            
            gain = bench_player["fp"] - starter["fp"]
            if gain > best_gain:
                best_gain = gain
                best_swap = BenchSwap(
                    date=date_str,
                    bench_player=bench_player["name"],
                    bench_player_fp=bench_player["fp"],
                    starter_replaced=starter["name"],
                    starter_fp=starter["fp"],
                    slot=starter["slot"],
                    gain=gain,
                )
    
    # --- BLUNDER DETECTION ---
    # A blunder is a bench player who played but could have filled a starter
    # slot occupied by a DNP player. These are free points left on the table
    # due to the manager not setting their lineup.
    #
    # Greedy assignment: sort bench players by FP descending (biggest blunders
    # first), assign each to an available DNP slot if position-eligible, then
    # mark that slot as consumed so we don't double-count.
    
    blunders = []
    available_slots = list(dnp_starters)  # Copy so we can remove as assigned
    
    for bench_player in sorted(bench, key=lambda p: p["fp"], reverse=True):
        for i, dnp in enumerate(available_slots):
            if can_player_fill_slot(bench_player["positions"], dnp["slot"]):
                blunders.append(Blunder(
                    date=date_str,
                    bench_player=bench_player["name"],
                    bench_player_fp=bench_player["fp"],
                    available_slot=dnp["slot"],
                    dnp_starter=dnp["name"],
                ))
                available_slots.pop(i)  # Consume this slot
                break
    
    return DailyWhatIf(
        date=date_str,
        manager=manager,
        starters_fp=starters_fp,
        bench_fp=bench_fp,
        best_swap=best_swap,
        potential_gain=best_gain,
        blunders=blunders,
    )


def analyze_manager_what_if(
    data: FantasyData,
    manager: str,
    week: int,
    opponent_score: float = None,
    actual_score: float = None,
) -> ManagerWhatIf:
    """
    Analyze what-if scenarios for a manager for one week.
    
    Args:
        data: FantasyData container
        manager: Manager name
        week: Week number
        opponent_score: Opponent's actual score (for matchup flip analysis)
        actual_score: Manager's actual score
    """
    # Filter data to this manager and week
    lineups = data.lineups[
        (data.lineups["manager"] == manager) &
        (data.lineups["week"] == week)
    ]
    
    playerlog = data.playerlog[
        (data.playerlog["manager"] == manager) &
        (data.playerlog["week"] == week)
    ]
    
    # Get unique dates
    dates = sorted(lineups["date"].unique())
    
    daily_analyses = []
    all_swaps = []
    all_blunders = []
    total_bench_points = 0.0
    total_potential_gain = 0.0
    
    for day in dates:
        lineups_day = lineups[lineups["date"] == day]
        playerlog_day = playerlog[playerlog["date"] == day]
        
        daily = analyze_daily_what_if(lineups_day, playerlog_day)
        
        if daily:
            daily_analyses.append(daily)
            total_bench_points += daily.bench_fp
            total_potential_gain += daily.potential_gain
            
            if daily.best_swap and daily.best_swap.gain > 0:
                all_swaps.append(daily.best_swap)
            
            all_blunders.extend(daily.blunders)
    
    # Calculate blunder totals
    total_blunders = len(all_blunders)
    total_blunder_points = sum(b.bench_player_fp for b in all_blunders)
    
    # Blunders are pure gain (filling empty slots, no displacement), so add
    # them to total_potential_gain which previously only counted swaps.
    total_potential_gain += total_blunder_points
    
    # Check if optimal swaps would flip matchup
    would_flip = False
    matchup_swing = 0.0
    
    if opponent_score is not None and actual_score is not None:
        lost_by = opponent_score - actual_score
        if lost_by > 0:
            # Manager lost - could they have won?
            matchup_swing = lost_by
            would_flip = total_potential_gain >= lost_by
    
    return ManagerWhatIf(
        manager=manager,
        week=week,
        total_bench_points=total_bench_points,
        total_potential_gain=total_potential_gain,
        swaps=all_swaps,
        blunders=all_blunders,
        total_blunders=total_blunders,
        total_blunder_points=total_blunder_points,
        daily_analysis=daily_analyses,
        would_flip_matchup=would_flip,
        matchup_swing=matchup_swing,
    )


def analyze_weekly_what_if(
    data: FantasyData,
    week: int,
    matchup_results: dict[str, dict] = None,
) -> WeeklyWhatIf:
    """
    Analyze what-if for all managers for one week.
    
    Args:
        data: FantasyData container
        week: Week number
        matchup_results: Dict mapping manager -> {"score": float, "opponent_score": float}
    """
    matchup_results = matchup_results or {}
    
    manager_analysis = {}
    notable_swaps = []
    
    for manager in MANAGERS:
        result = matchup_results.get(manager, {})
        
        analysis = analyze_manager_what_if(
            data,
            manager,
            week,
            opponent_score=result.get("opponent_score"),
            actual_score=result.get("score"),
        )
        
        manager_analysis[manager] = analysis
        
        # Check for notable swaps
        if analysis.total_potential_gain >= 25:
            notable_swaps.append({
                "type": "significant_gain",
                "manager": manager,
                "gain": analysis.total_potential_gain,
                "description": f"{manager} left {analysis.total_potential_gain:.1f} points on the bench",
            })
        
        if analysis.would_flip_matchup:
            notable_swaps.append({
                "type": "matchup_flip",
                "manager": manager,
                "swing": analysis.matchup_swing,
                "description": f"Optimal lineup would have flipped {manager}'s matchup (needed {analysis.matchup_swing:.1f})",
            })
        
        # Check for blunders
        if analysis.total_blunders > 0:
            blunder_names = [b.bench_player for b in analysis.blunders]
            notable_swaps.append({
                "type": "blunder",
                "manager": manager,
                "blunders": analysis.total_blunders,
                "blunder_points": analysis.total_blunder_points,
                "players": blunder_names,
                "description": (
                    f"{manager} committed {analysis.total_blunders} blunder(s): "
                    f"left {', '.join(blunder_names)} on the bench with open starter slots available "
                    f"({analysis.total_blunder_points:.1f} FP wasted)"
                ),
            })
    
    # Sort notable swaps by impact
    notable_swaps.sort(key=lambda x: x.get("gain", 0) + x.get("swing", 0) * 2, reverse=True)
    
    return WeeklyWhatIf(
        week=week,
        manager_analysis=manager_analysis,
        notable_swaps=notable_swaps,
    )


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

def format_what_if_section(what_if: WeeklyWhatIf, include_all: bool = False) -> str:
    """
    Format what-if analysis for newsletter.
    
    Args:
        what_if: WeeklyWhatIf analysis
        include_all: If True, include all managers. If False, only notable ones.
    """
    lines = []
    
    # Summary line for each manager's bench points
    bench_summary = []
    for manager in MANAGERS:
        analysis = what_if.manager_analysis[manager]
        bench_summary.append(f"{manager}: {analysis.total_bench_points:.1f}")
    lines.append("Bench Points: " + " | ".join(bench_summary))
    lines.append("")
    
    # Blunder summary
    blunder_summary = []
    for manager in MANAGERS:
        analysis = what_if.manager_analysis[manager]
        if analysis.total_blunders > 0:
            blunder_summary.append(
                f"{manager}: {analysis.total_blunders} blunder(s), "
                f"{analysis.total_blunder_points:.1f} FP wasted"
            )
    if blunder_summary:
        lines.append("Blunders: " + " | ".join(blunder_summary))
    else:
        lines.append("Blunders: None -- all bench games were unavoidable overflow.")
    lines.append("")
    
    # Notable scenarios
    if what_if.notable_swaps:
        for notable in what_if.notable_swaps:
            if notable["type"] == "matchup_flip":
                lines.append(f"[SWAP] {notable['description']}")
            elif notable["type"] == "significant_gain":
                lines.append(f"[STATS] {notable['description']}")
            elif notable["type"] == "blunder":
                lines.append(f"[!] {notable['description']}")
    else:
        lines.append("No lineup changes would have swung more than 25 points or flipped a matchup.")
    
    lines.append("")
    
    # Detail best swaps per manager (if include_all)
    if include_all:
        for manager in MANAGERS:
            analysis = what_if.manager_analysis[manager]
            if analysis.swaps:
                best = max(analysis.swaps, key=lambda s: s.gain)
                lines.append(
                    f"{manager}'s best swap: {best.bench_player} ({best.bench_player_fp:.1f}) "
                    f"for {best.starter_replaced} ({best.starter_fp:.1f}) = +{best.gain:.1f}"
                )
            if analysis.blunders:
                for b in analysis.blunders:
                    lines.append(
                        f"  BLUNDER: {b.bench_player} ({b.bench_player_fp:.1f} FP) "
                        f"left on bench -- {b.dnp_starter} ({b.available_slot}) didn't play"
                    )
    
    return "\n".join(lines)


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .data_loader import load_all_data
    from .weekly_stats import compute_weekly_report
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    week = int(sys.argv[2]) if len(sys.argv) > 2 else 11
    
    print(f"Loading data from: {base.absolute()}")
    print(f"Analyzing week {week}")
    print("-" * 50)
    
    data = load_all_data(base)
    
    # Get actual matchup results
    report = compute_weekly_report(data, week)
    
    matchup_results = {}
    for matchup in report.matchups:
        matchup_results[matchup.manager_a] = {
            "score": matchup.score_a,
            "opponent_score": matchup.score_b,
        }
        matchup_results[matchup.manager_b] = {
            "score": matchup.score_b,
            "opponent_score": matchup.score_a,
        }
    
    # Run analysis
    what_if = analyze_weekly_what_if(data, week, matchup_results)
    
    print("\nWhat-If Analysis:")
    print(format_what_if_section(what_if, include_all=True))
    
    print("\n" + "=" * 50)
    print("Detailed Swaps:")
    for manager in MANAGERS:
        analysis = what_if.manager_analysis[manager]
        print(f"\n{manager}:")
        print(f"  Bench points: {analysis.total_bench_points:.1f}")
        print(f"  Potential gain: {analysis.total_potential_gain:.1f}")
        print(f"  Blunders: {analysis.total_blunders} ({analysis.total_blunder_points:.1f} FP wasted)")
        print(f"  Would flip: {analysis.would_flip_matchup}")
        if analysis.swaps:
            print(f"  Top swaps:")
            for swap in sorted(analysis.swaps, key=lambda s: s.gain, reverse=True)[:3]:
                print(f"    {swap.bench_player} ({swap.bench_player_fp:.1f}) for {swap.starter_replaced} ({swap.starter_fp:.1f}) = +{swap.gain:.1f}")
        if analysis.blunders:
            print(f"  Blunder details:")
            for b in analysis.blunders:
                print(f"    {b.bench_player} ({b.bench_player_fp:.1f} FP) -> {b.available_slot} slot ({b.dnp_starter} didn't play)")
