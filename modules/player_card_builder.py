"""
player_card_builder.py

Assembles comprehensive player card data for the Keeper Watch interactive modal.
Each player card contains career history, current season stats, record book
appearances, draft ROI, ownership timeline, and more.

Data sources:
  - HISTORICAL_PLAYERLOG.json (career game logs, 8 seasons)
  - PLAYERLOG.xlsx (current season game logs)
  - PLAYERLIST.xlsx (projections, age, positions, NBA team)
  - ROSTERS.json (current ownership)
  - RECORDS.json (all-time top-10 leaderboards)
  - all_drafts.json (draft history)
  - all_trades.json + TRADES.json (trade history)
  - DRAFT_PICK_VALUES.json (expected pick value for draft ROI)
  - keeper_watch data from stats report (tier, keepability score)

Output:
  A list of player card dicts, one per keeper watch player, ready to be
  embedded as JSON in the newsletter HTML for the modal UI.

Usage (standalone test):
    cd <project_root>
    python modules/player_card_builder.py

Usage (from report_builder.py):
    from modules.player_card_builder import build_player_cards
    cards = build_player_cards(stats_report, data_dir, config_dir, historical_dir)
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd

from .data_loader import CURRENT_SEASON, CURRENT_SEASON_LONG


# =============================================================================
# CONFIGURATION
# =============================================================================

# Archetype thresholds
ARCHETYPE_RULES = {
    # (label, condition_fn) -- evaluated in order, first match wins
    # condition_fn receives a dict with: pos_group, career_fppg, season_fppg,
    # boom_rate, bust_rate, consistency_std, age, injury_rate, seasons_in_league
}

# Record book labels (human-readable names for top-10 keys)
RECORD_BOOK_LABELS = {
    "highest_single_game": "Highest Single Game FP",
    "best_season_fppg": "Best Season FPPG",
    "best_season_total_fp": "Best Season Total FP",
    "most_fp_single_week": "Most FP in a Single Week",
    "best_fppg_single_week": "Best FPPG in a Single Week",
    "most_games_over_40": "Most 40+ FP Games (Season)",
    "most_games_under_20": "Most Sub-20 FP Games (Season)",
    "most_consistent_player": "Most Consistent Player",
    "mr_monday_night": "Mr. Monday Night",
    "mr_4th_quarter": "Mr. 4th Quarter (Sundays)",
    "career_fppg": "Career FPPG",
    "career_total_fp": "Career Total FP",
    "career_total_fp_by_manager": "Career FP (By Manager)",
    "longest_player_tenure": "Longest Player Tenure",
    "franchise_player": "Franchise Player Value",
    "best_keeper_value": "Best Keeper Value",
    "biggest_outperformance": "Biggest Single-Game Outperformance",
    "best_rookie_single_game": "Best Rookie Single Game",
    "best_rookie_season_fppg": "Best Rookie Season FPPG",
    "best_rookie_season_total_fp": "Best Rookie Season Total FP",
    "best_rookie_fantasy_week": "Best Rookie Fantasy Week",
    "best_duo_season": "Best Duo (Season)",
    "best_duo_week": "Best Duo (Week)",
    "best_duo_day": "Best Duo (Day)",
    "garbage_time_king": "Garbage Time King",
    "best_draft_class": "Best Draft Class",
    "biggest_draft_steal": "Biggest Draft Steal (FPPG)",
    "biggest_draft_steal_totalfp": "Biggest Draft Steal (Total FP)",
    "biggest_draft_bust": "Biggest Draft Bust (FPPG)",
    "biggest_draft_bust_totalfp": "Biggest Draft Bust (Total FP)",
    "best_waiver_pickup": "Best Waiver Pickup (FPPG)",
    "best_waiver_pickup_totalfp": "Best Waiver Pickup (Total FP)",
}

# Milestone thresholds to check against
CAREER_FP_MILESTONES = [1000, 2500, 5000, 7500, 10000, 15000, 20000, 25000, 30000]
CAREER_GP_MILESTONES = [50, 100, 150, 200, 250, 300, 400, 500]


# =============================================================================
# ARCHETYPE ENGINE
# =============================================================================

# SYNC: archetype labels emitted here must match the JS color map
# (ARCHETYPE_COLORS and the inline archColors object) in player_card_modal.py.
# When adding, removing, or renaming a label below, update BOTH sites or the
# affected players will render with the fallback gray color.
def classify_archetype(stats: dict) -> str:
    """
    Classify a player into a 2K-inspired archetype based on their statistical
    profile. Archetypes describe a player's STYLE and ROLE, not their flaws.

    Design philosophy:
    - Names should feel like 2K player builds: aspirational, descriptive, fair
    - Injury rate and volatility are MODIFIERS, not primary labels
    - Every archetype should be something a manager wouldn't mind seeing
    - Young players get future-oriented labels; vets get respect-oriented labels

    Production tiers:
      Elite (50+ FPPG) -> Superstar labels
      All-Star (42+)   -> Star-caliber labels
      Starter (36+)    -> Solid contributor labels
      Rotation (30+)   -> Role player labels
      Bench (<30)      -> Development/depth labels

    Input stats dict keys:
      pos_group, season_fppg, career_fppg, boom_rate, bust_rate,
      consistency_std, age, injury_rate, seasons_in_league, gp_this_season,
      best_game, worst_game

    Returns a string archetype label.
    """
    pos = stats.get("pos_group", "G")
    fppg = stats.get("season_fppg", 0)
    career = stats.get("career_fppg", 0)
    boom = stats.get("boom_rate", 0)
    bust = stats.get("bust_rate", 0)
    std = stats.get("consistency_std", 15)
    age = stats.get("age", 25)
    injury = stats.get("injury_rate", 0)
    seasons = stats.get("seasons_in_league", 1)
    gp = stats.get("gp_this_season", 0)
    best = stats.get("best_game", 0)
    worst = stats.get("worst_game", 0)

    # --- Insufficient data ---
    if gp < 8:
        if age <= 22:
            return "Uncharted Prospect"
        return "Small Sample"

    # =================================================================
    # TIER 1: ELITE (FPPG >= 50) — Superstars
    # =================================================================
    if fppg >= 50:
        if std <= 14 and bust <= 3:
            if pos == "C":
                return "Generational Big"
            return "Cheat Code"
        if boom >= 75:
            return "Supernova"
        return "Alpha Scorer"

    # =================================================================
    # TIER 2: ALL-STAR (FPPG >= 42) — Star caliber
    # =================================================================
    if fppg >= 42:
        # Iron Man: consistent + high GP
        if std <= 13 and bust <= 4:
            if gp >= 50:
                return "Iron Man Elite"
            return "Metronome Star"

        # Young franchise piece
        if age <= 24:
            if std <= 14:
                return "Franchise Cornerstone"
            return "Young Alpha"

        # High-volume scorer with boom upside
        if boom >= 55 and bust <= 5:
            if age >= 33:
                return "Ageless Wonder"
            return "Walking Bucket"

        # Boom-bust star (high variance both ways)
        if boom >= 50 and bust >= 6:
            if age >= 33:
                return "Vintage Star"
            return "High Roller"

        # Default all-star
        if age >= 33:
            return "Aging Superstar"
        return "All-Star Caliber"

    # =================================================================
    # TIER 3: STARTER-LEVEL (FPPG >= 36) — Solid starters
    # =================================================================
    if fppg >= 36:
        # Young + productive = dynasty gold
        if age <= 23:
            if fppg >= 39:
                return "Future Franchise"
            return "Ascending Talent"

        if age <= 25:
            if std <= 12:
                return "Steady Riser"
            if boom >= 40:
                return "Breakout Candidate"
            return "Building Block"

        # Floor raisers: low std, moderate scoring
        if std <= 11:
            if gp >= 50:
                return "Ironman Floor Raiser"
            return "Reliable Starter"

        # High-upside but availability concerns
        if injury >= 20:
            if fppg >= 39:
                return "High-Ceiling Starter"
            return "Talented but Fragile"

        # Aging but productive
        if age >= 33:
            if gp >= 50:
                return "Father Time Defier"
            return "Crafty Veteran"

        # Volatile mid-tier
        if bust >= 10 and boom >= 30:
            return "Volatile Starter"

        if boom >= 40:
            return "Streaky Scorer"

        return "Quality Starter"

    # =================================================================
    # TIER 4: ROTATION PLAYER (FPPG >= 30) — Role players
    # =================================================================
    if fppg >= 30:
        if age <= 22:
            if fppg >= 33:
                return "Blue-Chip Prospect"
            return "Lottery Ticket"

        if age <= 24:
            return "Development Play"

        # Floor raiser role player
        if std <= 10:
            return "Glue Guy"

        if bust >= 15:
            return "Rollercoaster"

        if age >= 33:
            return "Veteran Presence"

        if gp >= 50:
            return "Steady Contributor"

        return "Rotation Piece"

    # =================================================================
    # TIER 5: FRINGE / BENCH (FPPG < 30)
    # =================================================================
    if age <= 22:
        return "Raw Prospect"
    if age <= 24:
        return "Upside Bench Stash"
    if age >= 33:
        return "Aging Vet"
    return "Roster Filler"


# =============================================================================
# DATA LOADING HELPERS
# =============================================================================

def _load_json(path: Path) -> dict | list:
    """Load a JSON file, returning empty dict/list on failure."""
    if not path.exists():
        print(f"  WARNING: {path} not found")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_historical_playerlog(hist_dir: Path) -> list[dict]:
    """Load HISTORICAL_PLAYERLOG.json."""
    path = hist_dir / "HISTORICAL_PLAYERLOG.json"
    data = _load_json(path)
    if isinstance(data, list):
        return data
    return []


def _load_current_playerlog(data_dir: Path) -> pd.DataFrame:
    """Load PLAYERLOG.xlsx for current season."""
    path = data_dir / "PLAYERLOG.xlsx"
    if not path.exists():
        print(f"  WARNING: {path} not found")
        return pd.DataFrame()
    return pd.read_excel(path)


def _to_season_key(season_year: str) -> str:
    """Convert '2017-2018' -> '2017-18'."""
    if "-" in season_year and len(season_year) == 7:
        return season_year
    if "-" in season_year and len(season_year) >= 9:
        parts = season_year.split("-")
        return f"{parts[0]}-{parts[1][2:]}"
    return season_year


# =============================================================================
# CORE BUILDER
# =============================================================================

def build_player_cards(
    keeper_watch_players: list[dict],
    data_dir: Path,
    config_dir: Path,
    historical_dir: Path,
    current_season_key: str = CURRENT_SEASON,
    season_performers: dict | None = None,
) -> list[dict]:
    """
    Build comprehensive player card data for each keeper watch player.

    Args:
        keeper_watch_players: List of player dicts from stats_report["keeper_watch"]["players"].
            Each must have: player_name, manager, age, pos_group, season_gp, season_fppg,
            season_total_fp, proj_fppg, keeper_tier, keepability_score, out_for_season, injured.
        data_dir: Path to the data/ directory.
        config_dir: Path to the config/ directory.
        historical_dir: Path to data/historical/ directory.
        current_season_key: e.g., "2025-26".
        season_performers: Optional dict from stats_report["season_performers"].
            If provided, uses NBA-level stats (all games) instead of fantasy-lineup-only stats.

    Returns:
        List of player card dicts ready for JSON serialization.
    """
    print("Building player cards...")

    # --- Load all data sources ---
    print("  Loading data sources...")
    hist_log = _load_historical_playerlog(historical_dir)
    current_log = _load_current_playerlog(data_dir)
    playerlist = _load_playerlist(data_dir)
    rosters = _load_json(config_dir / "ROSTERS.json")
    records = _load_json(config_dir / "RECORDS.json")
    all_drafts = _load_json(historical_dir / "all_drafts.json")
    all_trades = _load_json(historical_dir / "all_trades.json")
    current_trades = _load_json(config_dir / "TRADES.json")
    draft_pick_values = _load_json(config_dir / "DRAFT_PICK_VALUES.json")

    if not isinstance(all_drafts, list):
        all_drafts = []
    if not isinstance(all_trades, list):
        all_trades = []

    # Merge current-season draft picks into all_drafts
    current_draft = _load_json(config_dir / "DRAFT_PICKS_CURRENT.json")
    if isinstance(current_draft, dict):
        current_picks = current_draft.get("picks", [])
    elif isinstance(current_draft, list):
        current_picks = current_draft
    else:
        current_picks = []
    # Only add picks not already in all_drafts for the current season
    existing_current = {d["player_name"] for d in all_drafts if d.get("season") == current_season_key}
    for pick in current_picks:
        if isinstance(pick, dict) and pick.get("player_name") and pick["player_name"] not in existing_current:
            all_drafts.append({
                "season": pick.get("season", current_season_key),
                "player_name": pick["player_name"],
                "manager": pick.get("manager", ""),
                "pick_number": pick.get("pick_number", 0),
                "round": pick.get("round", 0),
                "is_keeper": pick.get("is_keeper", False),
            })

    # Merge current-season trades into all_trades
    if isinstance(current_trades, dict):
        for t in current_trades.get("trades", []):
            # Collect pick info for display
            picks_info = []
            side_a = t.get("side_a", {})
            side_b = t.get("side_b", {})
            for pick_str in side_a.get("sent_picks", []):
                picks_info.append({"pick": pick_str, "from_manager": side_a["manager"], "to_manager": side_b["manager"]})
            for pick_str in side_b.get("sent_picks", []):
                picks_info.append({"pick": pick_str, "from_manager": side_b["manager"], "to_manager": side_a["manager"]})

            all_trades.append({
                "season": current_season_key,
                "date": t.get("date", ""),
                "players": _flatten_trade_players(t),
                "picks": picks_info,
            })

    all_time = records.get("all_time", {})
    pick_values = draft_pick_values.get("pick_values", {})

    # --- Pre-index historical data ---
    print("  Indexing historical game logs...")
    hist_by_player = _index_historical_by_player(hist_log)

    print("  Indexing current season game logs...")
    current_by_player = _index_current_by_player(current_log)

    print("  Indexing drafts and trades...")
    drafts_by_player = _index_drafts_by_player(all_drafts)
    trades_by_player = _index_trades_by_player(all_trades)

    # --- Build season_performers lookup (all-games stats, not lineup-only) ---
    sp_lookup = {}
    if season_performers:
        for key in ["best_fppg", "best_total_fp", "worst_fppg", "worst_total_fp"]:
            for p in season_performers.get(key, []):
                pname = p.get("player_name", "")
                if pname and pname not in sp_lookup:
                    sp_lookup[pname] = p

    # --- Build each card ---
    cards = []
    for kw_player in keeper_watch_players:
        name = kw_player["player_name"]
        card = _build_single_card(
            name=name,
            kw_data=kw_player,
            hist_games=hist_by_player.get(name, []),
            current_games=current_by_player.get(name, []),
            playerlist=playerlist,
            all_time=all_time,
            drafts=drafts_by_player.get(name, []),
            trades=trades_by_player.get(name, []),
            pick_values=pick_values,
            current_season_key=current_season_key,
            sp_data=sp_lookup.get(name),
        )
        cards.append(card)

    # --- Compute composite rankings (avg of FPPG rank + Total FP rank) ---
    rankable = [c for c in cards if c.get("current_season", {}).get("gp", 0) > 0]
    by_fppg = sorted(rankable, key=lambda c: -c["current_season"]["fppg"])
    by_total = sorted(rankable, key=lambda c: -c["current_season"]["total_fp"])

    fppg_ranks = {c["player_name"]: i + 1 for i, c in enumerate(by_fppg)}
    total_ranks = {c["player_name"]: i + 1 for i, c in enumerate(by_total)}

    for c in cards:
        name = c["player_name"]
        fr = fppg_ranks.get(name, len(rankable))
        tr = total_ranks.get(name, len(rankable))
        c["composite_rank_fppg"] = fr
        c["composite_rank_total"] = tr
        c["composite_rank"] = (fr + tr) / 2.0

    by_composite = sorted(cards, key=lambda c: c.get("composite_rank", 999))
    for i, c in enumerate(by_composite):
        c["overall_rank"] = i + 1

    print(f"  Built {len(cards)} player cards")
    return cards


def _load_playerlist(data_dir: Path) -> dict:
    """Load PLAYERLIST.xlsx and return a {player_name: row_dict} lookup."""
    path = data_dir / "PLAYERLIST.xlsx"
    if not path.exists():
        return {}
    df = pd.read_excel(path)
    result = {}
    for _, row in df.iterrows():
        name = str(row.get("player_name", ""))
        if name:
            result[name] = row.to_dict()
    return result


def _flatten_trade_players(trade: dict) -> list[dict]:
    """Convert TRADES.json format to all_trades.json format for merging."""
    players = []
    side_a = trade.get("side_a", {})
    side_b = trade.get("side_b", {})
    for p in side_a.get("sent_players", []):
        players.append({
            "player_name": p,
            "from_manager": side_a["manager"],
            "to_manager": side_b["manager"],
        })
    for p in side_b.get("sent_players", []):
        players.append({
            "player_name": p,
            "from_manager": side_b["manager"],
            "to_manager": side_a["manager"],
        })
    return players


# =============================================================================
# INDEXING HELPERS
# =============================================================================

def _index_historical_by_player(hist_log: list[dict]) -> dict[str, list[dict]]:
    """Group historical game log rows by player_name."""
    by_player = defaultdict(list)
    for row in hist_log:
        by_player[row.get("player_name", "")].append(row)
    return dict(by_player)


def _index_current_by_player(current_log: pd.DataFrame) -> dict[str, list[dict]]:
    """Group current season PLAYERLOG rows by player_name."""
    if current_log.empty:
        return {}
    by_player = defaultdict(list)
    for _, row in current_log.iterrows():
        d = row.to_dict()
        # Normalize NaN -> None for JSON safety
        for k, v in d.items():
            if isinstance(v, float) and math.isnan(v):
                d[k] = None
        by_player[str(d.get("player_name", ""))].append(d)
    return dict(by_player)


def _index_drafts_by_player(all_drafts: list[dict]) -> dict[str, list[dict]]:
    """Group draft entries by player_name."""
    by_player = defaultdict(list)
    for d in all_drafts:
        by_player[d.get("player_name", "")].append(d)
    return dict(by_player)


def _index_trades_by_player(all_trades: list[dict]) -> dict[str, list[dict]]:
    """Group trade entries by player_name, including full trade context."""
    by_player = defaultdict(list)
    for t in all_trades:
        season = t.get("season", "")
        date = t.get("date", "")
        all_players = t.get("players", [])
        # Also capture draft picks if present (from TRADES.json format)
        picks_info = t.get("picks", [])

        for p in all_players:
            # Build list of other players in same trade, grouped by direction
            other_sent = []  # Others going same direction as this player
            other_received = []  # Others coming the opposite direction
            for op in all_players:
                if op.get("player_name") == p.get("player_name"):
                    continue
                if op.get("from_manager") == p.get("from_manager"):
                    other_sent.append(op.get("player_name", ""))
                else:
                    other_received.append(op.get("player_name", ""))

            entry = {
                "season": season,
                "date": date,
                "player_name": p.get("player_name", ""),
                "from_manager": p.get("from_manager", ""),
                "to_manager": p.get("to_manager", ""),
                "also_sent": other_sent,
                "received_back": other_received,
                "picks": picks_info,
            }
            by_player[entry["player_name"]].append(entry)
    return dict(by_player)


# =============================================================================
# SINGLE CARD BUILDER
# =============================================================================

def _build_single_card(
    name: str,
    kw_data: dict,
    hist_games: list[dict],
    current_games: list[dict],
    playerlist: dict,
    all_time: dict,
    drafts: list[dict],
    trades: list[dict],
    pick_values: dict,
    current_season_key: str,
    sp_data: dict | None = None,
) -> dict:
    """Build a complete player card for one player."""

    plist = playerlist.get(name, {})

    # =========================================================================
    # 1. HEADER / BASIC INFO
    # =========================================================================
    card = {
        "player_name": name,
        "nba_team": plist.get("player_nba_team", kw_data.get("nba_team", "")),
        "positions": plist.get("player_position(s)", kw_data.get("pos_group", "")),
        "pos_group": kw_data.get("pos_group", ""),
        "age": kw_data.get("age", plist.get("age")),
        "manager": kw_data.get("manager", ""),
        "keeper_tier": kw_data.get("keeper_tier", ""),
        "keepability_score": round(kw_data.get("keepability_score", 0), 1),
        "keepability_components": kw_data.get("components", {}),  # V2 component breakdown
        "out_for_season": kw_data.get("out_for_season", False),
        "injured": kw_data.get("injured", False),
    }

    # =========================================================================
    # 2. CURRENT SEASON STATS
    # Use keeper_watch data (PLAYERLOG-based, includes bench games) as the
    # single source of truth for player-level season stats.
    # season_performers (Yahoo API) is ONLY for the Stats Corner tables.
    # =========================================================================
    # Player-level FP list: all games where the player actually played
    # (not injured, had fantasy points). Includes bench/IL+ slot games.
    current_played = [g for g in current_games if not g.get("is_injured") and float(g.get("fantasy_points", 0) or 0) != 0]
    current_fps = [float(g["fantasy_points"]) for g in current_played if g.get("fantasy_points")]

    # Always use keeper_watch / PLAYERLOG data for season stats
    season_fppg = kw_data.get("season_fppg", 0)
    season_gp = kw_data.get("season_gp", len(current_fps))
    season_total_fp = kw_data.get("season_total_fp", sum(current_fps))

    proj_fppg = kw_data.get("proj_fppg", plist.get("projectedFPPG", 0))

    efficiency_pct = round(100 * season_fppg / proj_fppg, 1) if proj_fppg > 0 else None

    card["current_season"] = {
        "fppg": round(season_fppg, 1),
        "gp": season_gp,
        "total_fp": round(season_total_fp, 1),
        "proj_fppg": round(proj_fppg, 1) if proj_fppg else None,
        "efficiency_pct": efficiency_pct,
    }

    # =========================================================================
    # 3. LAST 10 GAMES (Scoring Sparkline data)
    # =========================================================================
    all_current_sorted = sorted(current_games, key=lambda g: str(g.get("date", "")), reverse=True)
    # Include started games AND injured games (IL rows have started=False but is_injured=True)
    # Skip bench rows (started=False, is_injured=False)
    relevant_sorted = [g for g in all_current_sorted if g.get("started") or g.get("is_injured")]
    last_10 = []
    for g in relevant_sorted[:10]:
        last_10.append({
            "date": str(g.get("date", ""))[:10],
            "opponent": g.get("nba_opponent", ""),
            "fp": round(float(g.get("fantasy_points", 0)), 1),
            "injured": bool(g.get("is_injured", False)),
        })

    card["last_10"] = last_10

    # Full season sparkline (all started + injured games, chronological)
    # Includes BOTH historical and current season data for season-click filtering
    sparkline = []

    # Historical seasons
    for g in sorted(hist_games, key=lambda x: str(x.get("date", ""))):
        started = g.get("started", False)
        injured = g.get("is_injured", False)
        if not started and not injured:
            continue  # bench row
        if not g.get("had_game", False) and not injured:
            continue  # Skip off-days (no sparkline bar for days with no game)
        sparkline.append({
            "date": str(g.get("date", ""))[:10],
            "fp": round(float(g.get("fantasy_points", 0)), 1),
            "injured": bool(injured),
            "season": _to_season_key(g.get("season_year", "")),
        })

    # Current season
    for g in sorted(current_games, key=lambda x: str(x.get("date", ""))):
        started = g.get("started", False)
        injured = g.get("is_injured", False)
        if not started and not injured:
            continue  # bench row
        sparkline.append({
            "date": str(g.get("date", ""))[:10],
            "fp": round(float(g.get("fantasy_points", 0)), 1),
            "injured": bool(injured),
            "season": current_season_key,
        })

    card["sparkline"] = sparkline

    # =========================================================================
    # 4. BOOM / BUST RATES
    # =========================================================================
    if current_fps:
        boom_count = sum(1 for fp in current_fps if fp >= 40)
        bust_count = sum(1 for fp in current_fps if fp < 20)
        boom_rate = round(100 * boom_count / len(current_fps), 1)
        bust_rate = round(100 * bust_count / len(current_fps), 1)
        try:
            consistency_std = round(statistics.stdev(current_fps), 1) if len(current_fps) > 1 else 0
        except Exception:
            consistency_std = 0
    else:
        boom_rate = 0
        bust_rate = 0
        consistency_std = 0

    card["boom_bust"] = {
        "boom_rate": boom_rate,
        "bust_rate": bust_rate,
        "boom_count": boom_count if current_fps else 0,
        "bust_count": bust_count if current_fps else 0,
        "total_games": len(current_fps),
        "consistency_std": consistency_std,
        "best_game": round(max(current_fps), 1) if current_fps else 0,
        "worst_game": round(min(current_fps), 1) if current_fps else 0,
    }

    # =========================================================================
    # 5. CAREER IN CHS LEAGUE (from historical + current)
    # =========================================================================
    career = _compute_career_stats(name, hist_games, current_games, current_season_key)
    card["career"] = career

    # =========================================================================
    # 6. OWNERSHIP TIMELINE
    # =========================================================================
    card["ownership_timeline"] = _build_ownership_timeline(
        name, hist_games, current_games, drafts, trades, current_season_key
    )

    # =========================================================================
    # 7. DRAFT ROI
    # =========================================================================
    card["draft_history"] = _build_draft_history(name, drafts, career, pick_values)

    # =========================================================================
    # 8. TRADE HISTORY
    # =========================================================================
    card["trade_history"] = [
        {
            "season": t["season"],
            "date": t.get("date", ""),
            "from_manager": t["from_manager"],
            "to_manager": t["to_manager"],
            "also_sent": t.get("also_sent", []),
            "received_back": t.get("received_back", []),
            "picks": t.get("picks", []),
        }
        for t in trades
    ]

    # =========================================================================
    # 9. RECORD BOOK APPEARANCES
    # =========================================================================
    card["record_book"] = _find_record_book_appearances(name, all_time)

    # =========================================================================
    # 10. INJURY PROFILE
    # =========================================================================
    card["injury_profile"] = _compute_injury_profile(
        name, hist_games, current_games, current_season_key
    )

    # =========================================================================
    # 11. PLAYER COMPS (season-over-season trends)
    # =========================================================================
    card["season_comps"] = _build_season_comps(career)

    # =========================================================================
    # 12. MILESTONE TRACKER
    # =========================================================================
    card["milestones"] = _compute_milestones(career, card["current_season"])

    # =========================================================================
    # 13. ARCHETYPE
    # =========================================================================
    card["archetype"] = classify_archetype({
        "pos_group": card["pos_group"],
        "season_fppg": season_fppg,
        "career_fppg": career.get("career_fppg", 0),
        "boom_rate": boom_rate,
        "bust_rate": bust_rate,
        "consistency_std": consistency_std,
        "age": card["age"] or 25,
        "injury_rate": card["injury_profile"].get("career_injury_rate", 0),
        "seasons_in_league": career.get("seasons_played", 1),
        "gp_this_season": season_gp,
        "best_game": card["boom_bust"].get("best_game", 0),
        "worst_game": card["boom_bust"].get("worst_game", 0),
    })

    return card


# =============================================================================
# CAREER STATS
# =============================================================================

def _compute_career_stats(
    name: str,
    hist_games: list[dict],
    current_games: list[dict],
    current_season_key: str,
) -> dict:
    """Compute career-level stats across all seasons."""
    # Combine historical + current into season buckets
    season_stats = defaultdict(lambda: {
        "gp": 0, "total_fp": 0.0, "managers": set(), "games_scheduled": 0,
        "games_missed": 0, "game_fps": [],
    })

    # Historical seasons
    for g in hist_games:
        sk = _to_season_key(g.get("season_year", ""))
        injured = g.get("is_injured", False)
        fp = float(g.get("fantasy_points", 0))
        has_game = g.get("had_game", False)

        # Count any game-day event: player played (fp > 0) or was injured.
        # Include bench games where the player actually scored -- player-level
        # stats should reflect player performance, not lineup decisions.
        if has_game or injured:
            season_stats[sk]["games_scheduled"] += 1
            if injured:
                season_stats[sk]["games_missed"] += 1
            elif fp != 0:
                season_stats[sk]["gp"] += 1
                season_stats[sk]["total_fp"] += fp
                season_stats[sk]["game_fps"].append(fp)
            else:
                season_stats[sk]["games_missed"] += 1

        mgr = g.get("manager", "")
        if mgr:
            season_stats[sk]["managers"].add(mgr)

    # Current season
    for g in current_games:
        sk = current_season_key
        is_injured = g.get("is_injured", False)
        fp = float(g.get("fantasy_points", 0) or 0)

        # Count any game-day event: player played (fp > 0) or was injured.
        # Include bench games -- player-level stats reflect player performance.
        if not is_injured and fp != 0:
            season_stats[sk]["gp"] += 1
            season_stats[sk]["total_fp"] += fp
            season_stats[sk]["game_fps"].append(fp)
            season_stats[sk]["games_scheduled"] += 1
        elif is_injured:
            season_stats[sk]["games_scheduled"] += 1
            season_stats[sk]["games_missed"] += 1

        mgr = g.get("manager", "")
        if mgr:
            season_stats[sk]["managers"].add(mgr)

    # Aggregate career totals
    career_gp = 0
    career_fp = 0.0
    all_fps = []
    seasons_played = 0
    season_breakdown = []

    for sk in sorted(season_stats.keys()):
        s = season_stats[sk]
        if s["gp"] == 0 and s["games_scheduled"] == 0:
            continue
        seasons_played += 1
        career_gp += s["gp"]
        career_fp += s["total_fp"]
        all_fps.extend(s["game_fps"])

        fppg = round(s["total_fp"] / s["gp"], 1) if s["gp"] > 0 else 0
        season_breakdown.append({
            "season": sk,
            "gp": s["gp"],
            "total_fp": round(s["total_fp"], 1),
            "fppg": fppg,
            "managers": sorted(s["managers"]),
            "games_scheduled": s["games_scheduled"],
            "games_missed": s["games_missed"],
        })

    career_fppg = round(career_fp / career_gp, 1) if career_gp > 0 else 0

    return {
        "seasons_played": seasons_played,
        "career_gp": career_gp,
        "career_fp": round(career_fp, 1),
        "career_fppg": career_fppg,
        "season_breakdown": season_breakdown,
    }


# =============================================================================
# OWNERSHIP TIMELINE
# =============================================================================

# Season start dates for detecting mid-season waiver pickups
# Format: "YYYY-26" -> "YYYY-10-DD" (approximate NBA season start)
SEASON_START_DATES = {
    "2017-18": "2017-10-17",
    "2018-19": "2018-10-16",
    "2019-20": "2019-10-22",
    "2020-21": "2020-12-22",  # COVID delayed start
    "2021-22": "2021-10-19",
    "2022-23": "2022-10-18",
    "2023-24": "2023-10-24",
    "2024-25": "2024-10-22",
    "2025-26": "2025-10-21",
    "2026-27": "2026-10-20",
}

# Threshold: if first game is more than this many days after season start,
# it's likely a mid-season waiver pickup, not a keeper
MID_SEASON_PICKUP_THRESHOLD_DAYS = 30


def _is_mid_season_pickup(first_game_date: str, season_key: str) -> bool:
    """
    Determine if a player's first game of the season indicates a mid-season
    waiver pickup rather than a keeper or early-season roster spot.
    
    Returns True if the first game is significantly after the season start,
    suggesting the player was picked up mid-season on waivers.
    """
    from datetime import datetime
    
    season_start = SEASON_START_DATES.get(season_key)
    if not season_start or not first_game_date:
        return False
    
    try:
        start_dt = datetime.strptime(season_start, "%Y-%m-%d")
        first_dt = datetime.strptime(first_game_date[:10], "%Y-%m-%d")
        days_after_start = (first_dt - start_dt).days
        return days_after_start > MID_SEASON_PICKUP_THRESHOLD_DAYS
    except (ValueError, TypeError):
        return False


def _build_ownership_timeline(
    name: str,
    hist_games: list[dict],
    current_games: list[dict],
    drafts: list[dict],
    trades: list[dict],
    current_season_key: str,
) -> list[dict]:
    """
    Build a season-by-season ownership timeline showing ALL ownership events.

    Returns a list of dicts per season:
        {
            "season": "2025-26",
            "events": [
                {"manager": "Garrett", "acquired_via": "draft"},
                {"manager": "Nick", "acquired_via": "trade"},
            ]
        }

    acquired_via options: "draft", "trade", "keeper", "waiver"
    """
    # --- Step 1: Determine ordered manager stints per season from game logs ---
    # Each stint is (season, manager, first_date, last_date)
    season_stints = defaultdict(list)  # season -> [(manager, first_date, last_date)]

    # Historical
    for g in hist_games:
        sk = _to_season_key(g.get("season_year", ""))
        mgr = g.get("manager", "")
        date_str = str(g.get("date", ""))[:10]
        if mgr and sk:
            stints = season_stints[sk]
            if stints and stints[-1][0] == mgr:
                stints[-1] = (mgr, stints[-1][1], date_str)  # extend last stint
            else:
                stints.append((mgr, date_str, date_str))

    # Current (already sorted by date in PLAYERLOG)
    for g in sorted(current_games, key=lambda x: str(x.get("date", ""))):
        mgr = g.get("manager", "")
        date_str = str(g.get("date", ""))[:10]
        if mgr:
            stints = season_stints[current_season_key]
            if stints and stints[-1][0] == mgr:
                stints[-1] = (mgr, stints[-1][1], date_str)
            else:
                stints.append((mgr, date_str, date_str))

    # --- Step 2: Build lookup tables ---
    draft_lookup = {}
    for d in drafts:
        dk = d.get("season", "")
        draft_lookup[dk] = {
            "manager": d.get("manager", ""),
            "pick": d.get("pick_number", 0),
            "round": d.get("round", 0),
            "is_keeper": d.get("is_keeper", False),
        }

    trade_lookup = defaultdict(list)
    for t in trades:
        trade_lookup[t.get("season", "")].append(t)

    # --- Step 3: Assemble timeline with all events ---
    timeline = []
    prev_season_last_manager = None

    for sk in sorted(season_stints.keys()):
        stints = season_stints[sk]
        if not stints:
            continue

        events = []
        draft_info = draft_lookup.get(sk)
        season_trades = trade_lookup.get(sk, [])

        for stint_idx, (mgr, first_date, last_date) in enumerate(stints):
            acquired_via = None

            if stint_idx == 0:
                # First manager of the season — how did they get the player?
                if draft_info and draft_info["manager"] == mgr:
                    # Draft record exists for this manager this season
                    if draft_info["is_keeper"]:
                        # Marked as keeper — but validate they actually owned player last season
                        if prev_season_last_manager == mgr:
                            acquired_via = "keeper"
                        elif prev_season_last_manager is None:
                            # First season in CHS league, can't be a true "keeper"
                            # They must have drafted this player
                            acquired_via = "draft"
                        else:
                            # Data inconsistency: is_keeper=True but different manager last season
                            # This likely means offseason waiver/trade not tracked, or bad data
                            # Show as "draft" since they appear in draft with this player
                            acquired_via = "draft"
                    else:
                        acquired_via = "draft"
                elif prev_season_last_manager and prev_season_last_manager == mgr:
                    # Same manager as end of last season — could be:
                    # 1. Keeper (if draft_info shows is_keeper=True)
                    # 2. Re-drafted (if draft_info shows is_keeper=False)
                    # 3. Mid-season waiver re-pickup (if no draft_info AND first game is late)
                    # 4. True keeper via implicit carryover (if no draft_info AND first game is early)
                    if draft_info and draft_info["manager"] == mgr:
                        # Explicit draft/keeper record exists
                        acquired_via = "keeper" if draft_info["is_keeper"] else "draft"
                    else:
                        # No draft record for this season — was player dropped then re-picked?
                        # Check if first game is well after season start (mid-season pickup)
                        if _is_mid_season_pickup(first_date, sk):
                            acquired_via = "waiver"
                        else:
                            acquired_via = "keeper"
                else:
                    # New manager, not drafted by them — check trades or waiver
                    traded_in = False
                    for t in season_trades:
                        if t.get("to_manager") == mgr:
                            traded_in = True
                            break
                    acquired_via = "trade" if traded_in else "waiver"
            else:
                # Mid-season manager change — was there a trade?
                traded_in = False
                for t in season_trades:
                    if t.get("to_manager") == mgr:
                        traded_in = True
                        break
                if traded_in:
                    acquired_via = "trade"
                else:
                    # Manager changed without a trade = dropped then picked up on waivers
                    acquired_via = "waiver"

            events.append({
                "manager": mgr,
                "acquired_via": acquired_via or "waiver",
            })

        timeline.append({
            "season": sk,
            "events": events,
        })

        prev_season_last_manager = stints[-1][0]

    return timeline


# =============================================================================
# DRAFT ROI
# =============================================================================

def _build_draft_history(
    name: str,
    drafts: list[dict],
    career: dict,
    pick_values: dict,
) -> list[dict]:
    """Build draft history with ROI calculation for each draft entry."""
    result = []
    season_lookup = {s["season"]: s for s in career.get("season_breakdown", [])}

    for d in sorted(drafts, key=lambda x: x.get("season", "")):
        pick = d.get("pick_number", 0)
        season = d.get("season", "")
        is_keeper = d.get("is_keeper", False)

        # Get expected value for this pick
        expected_fppg = None
        if pick and str(pick) in pick_values:
            expected_fppg = pick_values[str(pick)].get("expected_projFPPG", {}).get("mid")

        # Get actual production that season
        actual_fppg = None
        season_data = season_lookup.get(season)
        if season_data and season_data["gp"] > 0:
            actual_fppg = season_data["fppg"]

        # Compute ROI
        roi = None
        roi_label = None
        if expected_fppg and actual_fppg:
            roi = round(actual_fppg - expected_fppg, 1)
            if roi >= 10:
                roi_label = "Steal"
            elif roi >= 3:
                roi_label = "Good Value"
            elif roi >= -3:
                roi_label = "Fair"
            elif roi >= -8:
                roi_label = "Bust"
            else:
                roi_label = "Disaster"

        result.append({
            "season": season,
            "pick_number": pick,
            "round": d.get("round", 0),
            "manager": d.get("manager", ""),
            "is_keeper": is_keeper,
            "expected_fppg": round(expected_fppg, 1) if expected_fppg else None,
            "actual_fppg": actual_fppg,
            "roi": roi,
            "roi_label": roi_label,
        })

    return result


# =============================================================================
# RECORD BOOK APPEARANCES
# =============================================================================

def _find_record_book_appearances(name: str, all_time: dict) -> list[dict]:
    """Find all top-10 leaderboard appearances for a player."""
    appearances = []
    top10_keys = [k for k in all_time if k.endswith("_top10")]

    for key in sorted(top10_keys):
        entries = all_time[key]
        for i, entry in enumerate(entries):
            entry_name = entry.get("player_name", "")
            if entry_name == name:
                label_key = key.replace("_top10", "")
                label = RECORD_BOOK_LABELS.get(label_key, label_key.replace("_", " ").title())

                # Extract the primary value
                value = None
                for vf in ["fantasy_points", "fppg", "total_fp", "count",
                           "consecutive_seasons", "avg_fp", "std_dev",
                           "delta", "under_20_count"]:
                    if vf in entry:
                        value = entry[vf]
                        break

                appearances.append({
                    "record": label,
                    "rank": i + 1,
                    "value": value,
                    "season": entry.get("season", ""),
                    "detail": _format_record_detail(entry),
                })

    # Sort by rank (best first)
    appearances.sort(key=lambda x: x["rank"])
    return appearances


def _format_record_detail(entry: dict) -> str:
    """Create a human-readable detail string for a record book entry."""
    parts = []
    if "season" in entry and entry["season"] != "all-time":
        parts.append(entry["season"])
    if "manager" in entry:
        parts.append(f"for {entry['manager']}")
    if "gp" in entry:
        parts.append(f"{entry['gp']} GP")
    return " | ".join(parts) if parts else ""


# =============================================================================
# INJURY PROFILE
# =============================================================================

def _compute_injury_profile(
    name: str,
    hist_games: list[dict],
    current_games: list[dict],
    current_season_key: str,
) -> dict:
    """Compute injury profile across all seasons.
    
    A game is "scheduled" if:
      - The player started (started=True), OR
      - The player was marked injured (is_injured=True, even if started=False,
        because IL slot games still represent missed NBA games).
    A game is "missed" if is_injured=True.
    Bench rows (started=False, is_injured=False) are skipped — they're just
    off-days where the manager benched a healthy player.
    """
    season_injury = defaultdict(lambda: {"scheduled": 0, "missed": 0})

    # Historical
    for g in hist_games:
        started = g.get("started", False)
        injured = g.get("is_injured", False)
        had_game = g.get("had_game", False)
        if not started and not injured:
            continue  # bench row
        sk = _to_season_key(g.get("season_year", ""))
        if had_game or injured:
            season_injury[sk]["scheduled"] += 1
            if injured:
                season_injury[sk]["missed"] += 1

    # Current
    for g in current_games:
        started = g.get("started", False)
        injured = g.get("is_injured", False)
        fp = float(g.get("fantasy_points", 0) or 0)
        if not started and not injured:
            continue  # bench row
        sk = current_season_key
        if injured or fp != 0:
            season_injury[sk]["scheduled"] += 1
            if injured:
                season_injury[sk]["missed"] += 1

    # Aggregate
    total_scheduled = sum(s["scheduled"] for s in season_injury.values())
    total_missed = sum(s["missed"] for s in season_injury.values())
    career_rate = round(100 * total_missed / total_scheduled, 1) if total_scheduled > 0 else 0

    # Per-season rates
    season_rates = []
    for sk in sorted(season_injury.keys()):
        s = season_injury[sk]
        rate = round(100 * s["missed"] / s["scheduled"], 1) if s["scheduled"] > 0 else 0
        season_rates.append({
            "season": sk,
            "games_scheduled": s["scheduled"],
            "games_missed": s["missed"],
            "injury_rate": rate,
        })

    # Current injury streak
    # Walk backwards through ALL game-day rows. A player is "out" if
    # is_injured=True (regardless of started flag or lineup position).
    # The streak breaks when we find a row where the player actually played
    # (started=True, is_injured=False, fp > 0).
    current_streak = 0
    if current_games:
        for g in sorted(current_games, key=lambda x: str(x.get("date", "")), reverse=True):
            is_injured = g.get("is_injured", False)
            started = g.get("started", False)
            fp = float(g.get("fantasy_points", 0) or 0)

            if is_injured:
                current_streak += 1
            elif not is_injured and fp != 0:
                # Played a game -- streak broken
                break
            # Skip bench rows where player isn't injured and didn't play

    return {
        "career_games_scheduled": total_scheduled,
        "career_games_missed": total_missed,
        "career_injury_rate": career_rate,
        "season_rates": season_rates,
        "current_injury_streak": current_streak,
    }


# =============================================================================
# PLAYER COMPS (season-over-season trends)
# =============================================================================

def _build_season_comps(career: dict) -> dict:
    """Analyze season-over-season trends."""
    breakdown = career.get("season_breakdown", [])
    if len(breakdown) < 2:
        return {"trend": "new", "description": "First or second season in league"}

    # FPPG trend
    fppgs = [(s["season"], s["fppg"]) for s in breakdown if s["gp"] >= 10]
    if len(fppgs) < 2:
        return {"trend": "limited_data", "description": "Not enough qualifying seasons"}

    current = fppgs[-1]
    previous = fppgs[-2]
    best = max(fppgs, key=lambda x: x[1])
    worst = min(fppgs, key=lambda x: x[1])

    delta = round(current[1] - previous[1], 1)

    # Consecutive decline check
    consecutive_decline = 0
    for i in range(len(fppgs) - 1, 0, -1):
        if fppgs[i][1] < fppgs[i - 1][1]:
            consecutive_decline += 1
        else:
            break

    # Consecutive improvement check
    consecutive_improve = 0
    for i in range(len(fppgs) - 1, 0, -1):
        if fppgs[i][1] > fppgs[i - 1][1]:
            consecutive_improve += 1
        else:
            break

    if delta > 3:
        trend = "improving"
    elif delta < -3:
        trend = "declining"
    else:
        trend = "stable"

    description = f"{delta:+.1f} FPPG vs last season ({previous[0]})"
    if current[1] >= best[1]:
        description += f" | Best CHS season ever"
    elif consecutive_decline >= 2:
        description += f" | {consecutive_decline} consecutive seasons of decline"
    elif consecutive_improve >= 2:
        description += f" | {consecutive_improve} consecutive seasons of improvement"

    return {
        "trend": trend,
        "delta_vs_last": delta,
        "current_fppg": current[1],
        "previous_fppg": previous[1],
        "best_season": {"season": best[0], "fppg": best[1]},
        "worst_season": {"season": worst[0], "fppg": worst[1]},
        "consecutive_decline": consecutive_decline,
        "consecutive_improve": consecutive_improve,
        "description": description,
    }


# =============================================================================
# MILESTONE TRACKER
# =============================================================================

def _compute_milestones(career: dict, current_season: dict) -> list[dict]:
    """Find upcoming milestones the player is approaching."""
    milestones = []
    career_fp = career.get("career_fp", 0)
    career_gp = career.get("career_gp", 0)
    fppg = current_season.get("fppg", 0)

    # Career FP milestones
    for ms in CAREER_FP_MILESTONES:
        if career_fp < ms:
            remaining = round(ms - career_fp, 1)
            # Estimate games to reach
            games_needed = math.ceil(remaining / fppg) if fppg > 0 else None
            milestones.append({
                "type": "career_fp",
                "target": ms,
                "current": career_fp,
                "remaining": remaining,
                "games_needed": games_needed,
                "label": f"{remaining:.0f} FP away from {ms:,} career fantasy points",
            })
            break  # Only show next milestone

    # Career GP milestones
    for ms in CAREER_GP_MILESTONES:
        if career_gp < ms:
            remaining = ms - career_gp
            milestones.append({
                "type": "career_gp",
                "target": ms,
                "current": career_gp,
                "remaining": remaining,
                "label": f"{remaining} games away from {ms} career starts",
            })
            break

    return milestones


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    """Quick test: build cards from existing stats report and print one."""
    import sys

    PROJECT_ROOT = Path(__file__).resolve().parent
    if PROJECT_ROOT.name == "modules":
        PROJECT_ROOT = PROJECT_ROOT.parent

    config_dir = PROJECT_ROOT / "config"
    data_dir = PROJECT_ROOT / "data"
    historical_dir = data_dir / "historical"

    # Load latest stats report for keeper_watch data
    stats_reports = sorted(PROJECT_ROOT.glob("output/stats_report_week*.json"), reverse=True)
    if not stats_reports:
        # Try flat structure (Claude Projects)
        stats_reports = sorted(PROJECT_ROOT.glob("stats_report_week*.json"), reverse=True)

    if not stats_reports:
        print("ERROR: No stats_report_weekN.json found!")
        sys.exit(1)

    sr_path = stats_reports[0]
    print(f"Using stats report: {sr_path}")
    with open(sr_path) as f:
        stats_report = json.load(f)

    kw_players = stats_report.get("keeper_watch", {}).get("players", [])
    if not kw_players:
        print("ERROR: No keeper_watch players in stats report!")
        sys.exit(1)

    print(f"Found {len(kw_players)} keeper watch players")
    print()

    cards = build_player_cards(kw_players, data_dir, config_dir, historical_dir)

    # Print a sample card
    if cards:
        # Find Luka
        sample = next((c for c in cards if "Doncic" in c["player_name"]), cards[0])
        print()
        print("=" * 70)
        print(f"SAMPLE CARD: {sample['player_name']}")
        print("=" * 70)
        print(json.dumps(sample, indent=2, default=str))

        # Summary stats
        print()
        print(f"Total cards built: {len(cards)}")
        archetypes = defaultdict(int)
        for c in cards:
            archetypes[c["archetype"]] += 1
        print("Archetype distribution:")
        for arch, count in sorted(archetypes.items(), key=lambda x: -x[1]):
            print(f"  {arch}: {count}")
