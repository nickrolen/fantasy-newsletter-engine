"""
waiver_roi.py

Computes season-long Waiver Wire ROI for each manager.

For every waiver add, tracks:
  1. FP GAINED: What the pickup actually contributed in starter slots
  2. FP LOST: What the dropped player contributed on their new team
  3. NET ROI: FP Gained - FP Lost

Also computes per-manager:
  - Best/worst individual waiver pickups
  - FP per add (efficiency)
  - FPPG of waiver adds in starter slots
  - Biggest regret (most productive player they dropped)

DESTINATION: Section 2 (Report Cards) -- shows which managers are winning
or losing the waiver wire game over the full season, not just one week.

DATA SOURCES:
  - waivers_week{N}.txt: Who was added, when, by whom
  - LINEUPS.xlsx: Roster snapshots with slot assignments and FP
  - PLAYERLOG.xlsx: Game-by-game stats with manager attribution

INTEGRATION POINTS:
    - report_builder.py: build_stats_report() calls build_waiver_roi()
    - format_stats_report.py: format_section_2_report_cards() renders summary
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from .data_loader import FantasyData, MANAGERS, MANAGER_TO_TEAM


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class WaiverAdd:
    """A single waiver transaction."""
    week: int
    date: str               # YYYY-MM-DD
    manager: str
    player_name: str
    is_trade: bool = False   # "via trade" annotation
    
    # Post-add performance (filled in during analysis)
    starter_fp: float = 0.0         # FP scored in starter slots after add
    starter_games: int = 0          # Games started after add
    bench_fp: float = 0.0           # FP scored on bench after add
    bench_games: int = 0
    total_fp: float = 0.0           # All FP after add (starter + bench)
    total_games: int = 0
    fppg: float = 0.0               # FPPG in starter slots
    
    def to_dict(self) -> dict:
        return {
            "week": self.week,
            "date": self.date,
            "manager": self.manager,
            "player_name": self.player_name,
            "is_trade": self.is_trade,
            "starter_fp": round(self.starter_fp, 2),
            "starter_games": self.starter_games,
            "bench_fp": round(self.bench_fp, 2),
            "total_fp": round(self.total_fp, 2),
            "total_games": self.total_games,
            "fppg": round(self.fppg, 2),
        }


@dataclass
class DroppedPlayer:
    """A player who left a manager's roster (dropped or traded away)."""
    week: int                # Week the player was dropped
    manager: str             # Manager who dropped them
    player_name: str
    
    # Post-drop performance on new team(s)
    new_team_fp: float = 0.0         # FP scored for other managers after drop
    new_team_games: int = 0
    new_team_fppg: float = 0.0
    picked_up_by: str = ""           # Who picked them up (or "FA" if unclaimed)
    
    def to_dict(self) -> dict:
        return {
            "week": self.week,
            "manager": self.manager,
            "player_name": self.player_name,
            "new_team_fp": round(self.new_team_fp, 2),
            "new_team_games": self.new_team_games,
            "new_team_fppg": round(self.new_team_fppg, 2),
            "picked_up_by": self.picked_up_by or "FA",
        }


@dataclass
class ManagerWaiverROI:
    """Season-long waiver ROI for a single manager."""
    manager: str
    
    # Aggregate metrics
    total_adds: int = 0
    total_trades: int = 0            # Subset of adds that were trades
    total_drops_tracked: int = 0
    
    # FP accounting
    fp_gained: float = 0.0           # Total starter FP from waiver adds
    fp_lost: float = 0.0             # Total FP dropped players scored elsewhere
    net_roi: float = 0.0             # fp_gained - fp_lost
    fp_per_add: float = 0.0          # Average starter FP per add
    
    # Efficiency metrics
    total_starter_games: int = 0     # Games started by waiver adds
    waiver_fppg: float = 0.0         # FPPG of waiver adds in starter slots
    fppg_vs_avg: float = 0.0         # FPPG compared to league waiver average
    net_value_vs_avg: float = 0.0    # Total FP gained/lost vs league average
    hit_rate: float = 0.0            # % of adds performing above league waiver avg
    bust_rate: float = 0.0           # % of adds below 25 FPPG
    waiver_share: float = 0.0        # % of total starter FP from waiver adds
    
    # Notable transactions
    best_add: Optional[WaiverAdd] = None
    worst_add: Optional[WaiverAdd] = None
    biggest_loss: Optional[DroppedPlayer] = None  # Most productive dropped player
    
    # Detail lists
    adds: list[WaiverAdd] = field(default_factory=list)
    drops: list[DroppedPlayer] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "manager": self.manager,
            "total_adds": self.total_adds,
            "total_trades": self.total_trades,
            "total_drops_tracked": self.total_drops_tracked,
            "fp_gained": round(self.fp_gained, 2),
            "fp_lost": round(self.fp_lost, 2),
            "net_roi": round(self.net_roi, 2),
            "fp_per_add": round(self.fp_per_add, 2),
            "total_starter_games": self.total_starter_games,
            "waiver_fppg": round(self.waiver_fppg, 2),
            "fppg_vs_avg": round(self.fppg_vs_avg, 2),
            "net_value_vs_avg": round(self.net_value_vs_avg, 2),
            "hit_rate": round(self.hit_rate, 1),
            "bust_rate": round(self.bust_rate, 1),
            "waiver_share": round(self.waiver_share, 1),
            "best_add": self.best_add.to_dict() if self.best_add else None,
            "worst_add": self.worst_add.to_dict() if self.worst_add else None,
            "biggest_loss": self.biggest_loss.to_dict() if self.biggest_loss else None,
            "adds": [a.to_dict() for a in self.adds],
            "drops": [d.to_dict() for d in self.drops],
        }


@dataclass
class WaiverROIReport:
    """Complete Waiver Wire ROI report for the league."""
    managers: dict[str, ManagerWaiverROI] = field(default_factory=dict)
    weeks_analyzed: int = 0
    league_waiver_fppg: float = 0.0  # League-wide waiver add FPPG (baseline)
    best_waiver_manager: str = ""
    worst_waiver_manager: str = ""
    
    def to_dict(self) -> dict:
        return {
            "weeks_analyzed": self.weeks_analyzed,
            "league_waiver_fppg": round(self.league_waiver_fppg, 2),
            "best_waiver_manager": self.best_waiver_manager,
            "worst_waiver_manager": self.worst_waiver_manager,
            "managers": {
                m: roi.to_dict() for m, roi in self.managers.items()
            },
        }


# =============================================================================
# WAIVER FILE PARSING
# =============================================================================

def parse_waiver_file(filepath: Path) -> list[WaiverAdd]:
    """
    Parse a waivers_week{N}.txt file into WaiverAdd objects.
    
    Expected format:
        - [2026-01-26] Nick: Santi Aldama
        - [2026-01-27] Benton: Michael Porter Jr. (via trade)
    """
    adds = []
    
    if not filepath.exists():
        return adds
    
    # Extract week number from filename
    match = re.search(r"week(\d+)", filepath.name)
    week = int(match.group(1)) if match else 0
    
    # FIXED: Match manager by MANAGERS lookup (longest-first) so multi-word
    # names like "Mary Jane" are not truncated to "Mary" by \w+.
    sorted_managers = sorted(MANAGERS, key=len, reverse=True)
    date_prefix_re = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})\]\s+(.+)$")

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse: - [YYYY-MM-DD] Manager: Player Name (optional annotation)
            prefix_match = date_prefix_re.match(line)
            if not prefix_match:
                continue

            date_str = prefix_match.group(1)
            rest = prefix_match.group(2)

            manager = None
            player_raw = None
            for mgr in sorted_managers:
                token = f"{mgr}: "
                if rest.startswith(token):
                    manager = mgr
                    player_raw = rest[len(token):].strip()
                    break

            if manager is None:
                continue
            
            # Check for "(via trade)" annotation
            is_trade = "(via trade)" in player_raw.lower()
            player_name = re.sub(
                r"\s*\(via trade\)\s*", "", player_raw, flags=re.IGNORECASE
            ).strip()
            
            adds.append(WaiverAdd(
                week=week,
                date=date_str,
                manager=manager,
                player_name=player_name,
                is_trade=is_trade,
            ))
    
    return adds


def load_all_waivers(base_path: Path, through_week: int) -> list[WaiverAdd]:
    """
    Load all waiver adds from waivers_week1.txt through waivers_week{through_week}.txt.
    
    Looks in both data/ subdirectory and root directory (for flexibility).
    """
    all_adds = []
    
    for week in range(1, through_week + 1):
        # Check data/ first, then root
        for subdir in ["data", "."]:
            filepath = base_path / subdir / f"waivers_week{week}.txt"
            if filepath.exists():
                adds = parse_waiver_file(filepath)
                all_adds.extend(adds)
                break
    
    return all_adds


# =============================================================================
# ROSTER CHANGE DETECTION (for identifying drops)
# =============================================================================

def detect_drops(
    lineups: pd.DataFrame,
    waiver_adds: list[WaiverAdd],
    through_week: int,
    traded_away: set[tuple[str, str]] | None = None,
) -> list[DroppedPlayer]:
    """
    Detect dropped players by comparing rosters week-to-week.
    
    A "drop" is when a player appears on a manager's roster in week N
    but not in week N+1, AND that manager made at least one waiver add
    in week N+1 (implying the drop was to make room).
    
    This heuristic isn't perfect -- a player might disappear because they
    were traded (not dropped) or because the season ended. But it catches
    the vast majority of real drops in a keeper league.
    
    Args:
        lineups: LINEUPS.xlsx DataFrame
        waiver_adds: List of all waiver adds (including trades, for detection)
        through_week: Analyze through this week
    
    Returns:
        List of DroppedPlayer objects
    """
    drops = []
    
    # Build per-week roster sets: {manager: {week: set(player_names)}}
    roster_by_week = {}
    for manager in MANAGERS:
        roster_by_week[manager] = {}
        mgr_lineups = lineups[lineups["manager"] == manager]
        
        for week in range(1, through_week + 1):
            week_players = mgr_lineups[
                mgr_lineups["week"] == week
            ]["player_name"].unique().tolist()
            roster_by_week[manager][week] = set(week_players)
    
    # Build lookup: {(manager, week): [add_player_names]}
    adds_by_mgr_week = {}
    for add in waiver_adds:
        key = (add.manager, add.week)
        if key not in adds_by_mgr_week:
            adds_by_mgr_week[key] = []
        adds_by_mgr_week[key].append(add.player_name)
    
    # For each manager and each week they made adds, find who disappeared
    for manager in MANAGERS:
        for week in range(2, through_week + 1):
            add_key = (manager, week)
            if add_key not in adds_by_mgr_week:
                continue
            
            prev_roster = roster_by_week[manager].get(week - 1, set())
            curr_roster = roster_by_week[manager].get(week, set())
            
            if not prev_roster or not curr_roster:
                continue
            
            # Players who were on the roster last week but not this week
            disappeared = prev_roster - curr_roster
            
            # Exclude players who were added this same week (edge case safety)
            added_this_week = set(adds_by_mgr_week[add_key])
            disappeared -= added_this_week
            
            # Exclude players who left via trade (not a waiver drop)
            if traded_away:
                disappeared = {
                    p for p in disappeared
                    if (manager, p) not in traded_away
                }
            
            for player_name in disappeared:
                drops.append(DroppedPlayer(
                    week=week,
                    manager=manager,
                    player_name=player_name,
                ))
    
    return drops


# =============================================================================
# POST-TRANSACTION PERFORMANCE TRACKING
# =============================================================================

# Starter slot names (case-insensitive matching)
_STARTER_SLOTS = {"PG", "SG", "G", "SF", "PF", "F", "C", "UTIL"}


def track_add_performance(
    add: WaiverAdd,
    lineups: pd.DataFrame,
    through_week: int,
    end_week: int = None,
) -> WaiverAdd:
    """
    Track a waiver add's performance AFTER being added.
    
    Uses LINEUPS data (not PLAYERLOG) because LINEUPS has slot assignments,
    which lets us distinguish starter FP from bench FP.

    end_week bounds the stint at the player's NEXT drop by this manager
    (inclusive of the drop week itself, since pre-drop days that week are
    legitimate). Without it, an add -> drop -> re-add sequence counted the
    second stint's production under BOTH WaiverAdd records.
    """
    upper = through_week if end_week is None else min(through_week, end_week)
    # Filter to this player, this manager, weeks within this stint
    player_rows = lineups[
        (lineups["player_name"] == add.player_name) &
        (lineups["manager"] == add.manager) &
        (lineups["week"] >= add.week) &
        (lineups["week"] <= upper)
    ]
    
    if player_rows.empty:
        return add
    
    # Only count rows where the player had a game (nba_opponent present)
    # AND actually played. Exact 0.0 = injury/DNP per the project convention;
    # negative scores are legitimate played games and are included.
    game_rows = player_rows[
        player_rows["nba_opponent"].notna() &
        (player_rows["nba_opponent"].astype(str).str.strip() != "") &
        (player_rows["fantasy_points"].notna()) &
        (player_rows["fantasy_points"] != 0)
    ]
    
    for _, row in game_rows.iterrows():
        fp = row.get("fantasy_points", 0)
        
        slot = str(row.get("slot", "")).strip().upper()
        
        if slot in _STARTER_SLOTS:
            add.starter_fp += fp
            add.starter_games += 1
        else:
            add.bench_fp += fp
            add.bench_games += 1
    
    add.total_fp = add.starter_fp + add.bench_fp
    add.total_games = add.starter_games + add.bench_games
    add.fppg = (add.starter_fp / add.starter_games) if add.starter_games > 0 else 0.0
    
    return add


def track_drop_performance(
    drop: DroppedPlayer,
    lineups: pd.DataFrame,
    through_week: int,
) -> DroppedPlayer:
    """
    Track a dropped player's performance AFTER being dropped.

    Uses LINEUPS (starter slots only) so the "FP lost" side of Net ROI is
    measured the same way as the "FP gained" side -- starter-slot production.
    Previously this used PLAYERLOG (all slots, no horizon symmetry), which
    counted bench production the new owner never started and made Net ROI
    structurally biased negative.
    """
    # Find this player's rows on OTHER managers' teams after the drop
    post_drop_games = lineups[
        (lineups["player_name"] == drop.player_name) &
        (lineups["week"] >= drop.week) &
        (lineups["week"] <= through_week) &
        (lineups["manager"] != drop.manager)
    ]
    
    if post_drop_games.empty:
        drop.picked_up_by = "FA"
        return drop
    
    # Starter-slot games only, played (0.0 = injury/DNP; negatives count)
    scored_games = post_drop_games[
        post_drop_games["slot"].astype(str).str.upper().isin(_STARTER_SLOTS) &
        post_drop_games["fantasy_points"].notna() &
        (post_drop_games["fantasy_points"] != 0)
    ]
    
    drop.new_team_fp = scored_games["fantasy_points"].sum()
    drop.new_team_games = len(scored_games)
    drop.new_team_fppg = (
        drop.new_team_fp / drop.new_team_games
        if drop.new_team_games > 0 else 0.0
    )
    
    # Who picked them up? Most common manager in post-drop data
    if not post_drop_games.empty:
        new_manager = post_drop_games["manager"].mode()
        drop.picked_up_by = new_manager.iloc[0] if not new_manager.empty else "FA"
    
    return drop


# =============================================================================
# MAIN COMPUTATION
# =============================================================================

def compute_waiver_roi(
    data: FantasyData,
    through_week: int,
    include_trades: bool = False,
) -> WaiverROIReport:
    """
    Compute season-long Waiver Wire ROI for all managers.
    
    Args:
        data: FantasyData container
        through_week: Analyze through this week (inclusive)
        include_trades: If True, include "via trade" adds in ROI calc.
                       Default False since trades are a different strategic decision.
    
    Returns:
        WaiverROIReport with per-manager ROI data
    """
    base_path = data.base_path
    
    # Load all waiver adds
    all_adds = load_all_waivers(base_path, through_week)
    
    # Optionally filter out trades for the ROI calculation
    if not include_trades:
        waiver_adds = [a for a in all_adds if not a.is_trade]
    else:
        waiver_adds = all_adds
    
    # Build set of traded-away players: {(manager, player_name)}
    # Uses "(via trade)" annotations in waiver files as the source of truth.
    # For each trade arrival, trace back to find which manager lost the player.
    traded_away = set()

    # Build per-week rosters from LINEUPS for trade detection
    _roster_by_week = {}
    for mgr in MANAGERS:
        _roster_by_week[mgr] = {}
        mgr_rows = data.lineups[data.lineups["manager"] == mgr]
        for wk in range(1, through_week + 1):
            wk_players = mgr_rows[mgr_rows["week"] == wk]["player_name"].unique()
            _roster_by_week[mgr][wk] = set(wk_players)

    # For each "via trade" add, find which manager lost the player that week
    trade_adds = [a for a in all_adds if a.is_trade]
    for add in trade_adds:
        for mgr in MANAGERS:
            if mgr == add.manager:
                continue
            prev = _roster_by_week[mgr].get(add.week - 1, set())
            curr = _roster_by_week[mgr].get(add.week, set())
            if add.player_name in prev and add.player_name not in curr:
                traded_away.add((mgr, add.player_name))
                break

    # Detect drops (use all_adds including trades for roster change detection)
    drops = detect_drops(data.lineups, all_adds, through_week, traded_away)
    
    # Track performance for each add
    for add in waiver_adds:
        # Bound each add's window at the player's next drop by the same
        # manager (prevents double-counting re-added players' second stints)
        later_drops = [
            d.week for d in drops
            if d.manager == add.manager
            and d.player_name == add.player_name
            and d.week >= add.week
        ]
        stint_end = min(later_drops) if later_drops else None
        track_add_performance(add, data.lineups, through_week, end_week=stint_end)
    
    # Track performance for each drop
    for drop in drops:
        track_drop_performance(drop, data.lineups, through_week)
    
    # Build per-manager summaries
    report = WaiverROIReport(weeks_analyzed=through_week)
    
    for manager in MANAGERS:
        mgr_adds = [a for a in waiver_adds if a.manager == manager]
        mgr_trades = [a for a in all_adds if a.manager == manager and a.is_trade]
        mgr_drops = [d for d in drops if d.manager == manager]
        
        roi = ManagerWaiverROI(manager=manager)
        roi.total_adds = len(mgr_adds)
        roi.total_trades = len(mgr_trades)
        roi.total_drops_tracked = len(mgr_drops)
        roi.adds = mgr_adds
        roi.drops = mgr_drops
        
        # Aggregate FP gained from adds (starter slots only)
        roi.fp_gained = sum(a.starter_fp for a in mgr_adds)
        roi.total_starter_games = sum(a.starter_games for a in mgr_adds)
        roi.waiver_fppg = (
            roi.fp_gained / roi.total_starter_games
            if roi.total_starter_games > 0 else 0.0
        )
        roi.fp_per_add = (
            roi.fp_gained / roi.total_adds
            if roi.total_adds > 0 else 0.0
        )
        
        # Aggregate FP lost from drops (what dropped players scored elsewhere)
        roi.fp_lost = sum(d.new_team_fp for d in mgr_drops)
        
        # Net ROI
        roi.net_roi = roi.fp_gained - roi.fp_lost
        
        # Best/worst adds (by starter FP contributed)
        if mgr_adds:
            roi.best_add = max(mgr_adds, key=lambda a: a.starter_fp)
            # Only flag worst if they had a chance to contribute (was started)
            started_adds = [a for a in mgr_adds if a.starter_games > 0]
            if started_adds:
                roi.worst_add = min(started_adds, key=lambda a: a.fppg)
            elif mgr_adds:
                roi.worst_add = min(mgr_adds, key=lambda a: a.starter_fp)
        
        # Biggest loss (dropped player who produced the most elsewhere)
        if mgr_drops:
            productive_drops = [d for d in mgr_drops if d.new_team_fp > 0]
            if productive_drops:
                roi.biggest_loss = max(
                    productive_drops, key=lambda d: d.new_team_fp
                )
        
        report.managers[manager] = roi
    
    # Calculate league-wide waiver average FPPG
    total_league_fp = sum(r.fp_gained for r in report.managers.values())
    total_league_games = sum(r.total_starter_games for r in report.managers.values())
    if total_league_games > 0:
        report.league_waiver_fppg = total_league_fp / total_league_games
    
    # Calculate per-manager vs-average metrics and hit/bust rates
    for roi in report.managers.values():
        roi.fppg_vs_avg = roi.waiver_fppg - report.league_waiver_fppg
        roi.net_value_vs_avg = roi.total_starter_games * roi.fppg_vs_avg
        
        # Hit rate: % of adds (min 3 starts) above league waiver avg
        started_adds = [a for a in roi.adds if a.starter_games >= 3]
        if started_adds:
            hits = [a for a in started_adds if a.fppg >= report.league_waiver_fppg]
            roi.hit_rate = len(hits) / len(started_adds) * 100
            
            # Bust rate: % of adds below 25 FPPG
            busts = [a for a in started_adds if a.fppg < 25]
            roi.bust_rate = len(busts) / len(started_adds) * 100
    
    # Calculate waiver share (% of starter FP from waiver adds)
    starter_slots = {"PG", "SG", "G", "SF", "PF", "F", "C", "UTIL"}
    starter_games = data.lineups[
        data.lineups["nba_opponent"].notna() &
        (data.lineups["nba_opponent"].astype(str).str.strip() != "") &
        (data.lineups["slot"].str.upper().isin(starter_slots))
    ]
    for roi in report.managers.values():
        mgr_starters = starter_games[starter_games["manager"] == roi.manager]
        total_starter_fp = mgr_starters["fantasy_points"].sum()
        if total_starter_fp > 0:
            roi.waiver_share = roi.fp_gained / total_starter_fp * 100
    
    # Identify best/worst waiver managers by FPPG vs average (not raw net ROI)
    if report.managers:
        sorted_by_efficiency = sorted(
            report.managers.values(),
            key=lambda x: x.fppg_vs_avg,
            reverse=True,
        )
        report.best_waiver_manager = sorted_by_efficiency[0].manager
        report.worst_waiver_manager = sorted_by_efficiency[-1].manager
    
    return report


# =============================================================================
# CONVENIENCE FUNCTION (for use in report_builder.py)
# =============================================================================

def build_waiver_roi(data: FantasyData, week: int) -> dict:
    """
    Build Waiver Wire ROI section for the stats report.
    
    Convenience wrapper that returns a JSON-serializable dict.
    
    Args:
        data: FantasyData container
        week: Current week number
    
    Returns:
        Dict ready for inclusion in the stats report JSON
    """
    report = compute_waiver_roi(data, through_week=week)
    return report.to_dict()


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    import json
    
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    from modules.data_loader import load_all_data
    
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    week = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    print("Loading data...")
    data = load_all_data(base)
    
    if week is None:
        week = data.current_week
    
    print(f"Computing Waiver Wire ROI through Week {week}")
    print("=" * 60)
    
    result = build_waiver_roi(data, week)
    
    print(f"\nBest waiver manager: {result['best_waiver_manager']}")
    print(f"Worst waiver manager: {result['worst_waiver_manager']}")
    print()
    
    header = f"{'Manager':<10} {'Adds':>5} {'FP Gained':>10} {'FP Lost':>9} {'Net ROI':>9} {'FP/Add':>8} {'FPPG':>6}"
    print(header)
    print("-" * len(header))
    
    for manager in MANAGERS:
        m = result["managers"].get(manager, {})
        if not m:
            continue
        print(
            f"{m['manager']:<10} "
            f"{m['total_adds']:>5} "
            f"{m['fp_gained']:>10.1f} "
            f"{m['fp_lost']:>9.1f} "
            f"{m['net_roi']:>9.1f} "
            f"{m['fp_per_add']:>8.1f} "
            f"{m['fppg']:>6.1f}"
        )
