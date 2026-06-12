#!/usr/bin/env python3
"""
backfill_player_records.py

One-time script to compute all-time player records and team leaderboards,
then merge them into config/RECORDS.json.

Computes:
  - Team record top-10 leaderboards from all_matchups.json
  - Player record top-10s from HISTORICAL_PLAYERLOG + current PLAYERLOG
  - Rookie record top-10s (if ROOKIE_SEASONS.json exists)
  - Expanded record top-10s (duos, collective, consistency, etc.)
  - Draft, trade, & manager leaderboards
  - Season-level player records from current PLAYERLOG

Usage:
    python scripts/backfill_player_records.py

CHANGELOG (v2 - Feb 2026):
  - Added date normalization to prevent duplicate GP from format mismatches
  - Added GP sanity caps: max 4/week per player, max 82/season per player
  - Fixed "games" field in weekly records (was counting inflated rows)
  - Draft steal/bust now uses is_keeper flag + DRAFT_PICK_VALUES.json deltas
  - Best waiver pickup now works across all seasons (not just current)
  - Added new records: team FPPG week, daily team score, duo day/season,
    sub-20 FP week
  - Renamed keys for clarity (collective_team_game -> daily_team_fppg, etc.)
  - Added 5-starter qualifier note to daily team FPPG records
  - Keeper slots (is_keeper=True) excluded from all draft analysis
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.data_loader import (
    CURRENT_SEASON, CURRENT_SEASON_LONG, KEEPER_ERA_START,
)

PROJECT_ROOT = Path(__file__).parent.parent
RECORDS_FILE = PROJECT_ROOT / "config" / "RECORDS.json"
ALL_MATCHUPS_FILE = PROJECT_ROOT / "data" / "historical" / "all_matchups.json"
HISTORICAL_PLAYERLOG_FILE = PROJECT_ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json"
PLAYERLOG_FILE = PROJECT_ROOT / "data" / "PLAYERLOG.xlsx"
LINEUPS_FILE = PROJECT_ROOT / "data" / "LINEUPS.xlsx"
ROOKIE_SEASONS_FILE = PROJECT_ROOT / "config" / "ROOKIE_SEASONS.json"
ALL_DRAFTS_FILE = PROJECT_ROOT / "data" / "historical" / "all_drafts.json"
DRAFT_PICKS_CURRENT_FILE = PROJECT_ROOT / "config" / "DRAFT_PICKS_CURRENT.json"
ALL_TRADES_FILE = PROJECT_ROOT / "data" / "historical" / "all_trades.json"
DRAFT_PICK_VALUES_FILE = PROJECT_ROOT / "config" / "DRAFT_PICK_VALUES.json"
WAIVERS_DIR = PROJECT_ROOT / "data"

MIN_GP_FPPG = 30
MAX_GAMES_PER_WEEK = 7  # generous cap for 14-day weeks (NBA Cup, All-Star break)
MAX_GAMES_PER_SEASON = 82


def normalize_season(season_str: str) -> str:
    s = str(season_str).strip()
    if len(s) >= 9 and s[4] == "-":
        return f"{s[:4]}-{s[-2:]}"
    return s


def normalize_date(date_str: str) -> str:
    s = str(date_str).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%m-%d-%Y"):
        try:
            dt = datetime.strptime(s[:10], fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    if " " in s:
        s = s.split(" ")[0]
    parts = s.split("-")
    if len(parts) == 3:
        try:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            pass
    return s


def compute_last_updated_week(matchups: list, games: list, current_df: pd.DataFrame, current_season: str = CURRENT_SEASON) -> int:
    """
    Compute the most recent fantasy week for bookkeeping in RECORDS.json.

    Priority:
      1) Max week in current PLAYERLOG rows whose date <= today (current season only).
      2) Max week in the combined game list (current season only).
      3) Max week in all_matchups.json (current season only).

    Returns 0 if no usable week is found.
    """
    weeks: list[int] = []
    today = datetime.now().date()

    # 1) Current PLAYERLOG (date-aware, if possible)
    if current_df is not None and not current_df.empty and "week" in current_df.columns:
        df = current_df
        if "season_year" in df.columns:
            try:
                df = df[df["season_year"].apply(normalize_season) == current_season]
            except Exception:
                pass
        if "date" in df.columns:
            def _safe_date(x):
                s = normalize_date(x)
                try:
                    return datetime.strptime(s, "%Y-%m-%d").date()
                except Exception:
                    return None
            try:
                d = df["date"].apply(_safe_date)
                df = df[d.notna() & (d <= today)]
            except Exception:
                pass
        try:
            wk = pd.to_numeric(df["week"], errors="coerce").dropna()
            wk = wk[wk > 0]
            if not wk.empty:
                weeks.append(int(wk.max()))
        except Exception:
            pass

    # 2) Combined games list
    if games:
        try:
            w = [int(g.get("week", 0)) for g in games if g.get("season") == current_season and int(g.get("week", 0)) > 0]
            if w:
                weeks.append(max(w))
        except Exception:
            pass

    # 3) Matchups list
    if matchups:
        try:
            w = [int(m.get("week", 0)) for m in matchups if m.get("season") == current_season and int(m.get("week", 0)) > 0]
            if w:
                weeks.append(max(w))
        except Exception:
            pass

    return max(weeks) if weeks else 0


def load_records() -> dict:
    if RECORDS_FILE.exists():
        with open(RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"all_time": {}, "season_records": {}}


def save_records(records: dict) -> None:
    with open(RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=True)
    print(f"Saved RECORDS.json ({RECORDS_FILE})")


def load_all_matchups() -> list:
    if not ALL_MATCHUPS_FILE.exists():
        print(f"WARNING: {ALL_MATCHUPS_FILE} not found")
        return []
    with open(ALL_MATCHUPS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_historical_playerlog() -> list:
    if not HISTORICAL_PLAYERLOG_FILE.exists():
        print(f"WARNING: {HISTORICAL_PLAYERLOG_FILE} not found -- skipping player records")
        return []
    with open(HISTORICAL_PLAYERLOG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"Loaded {len(data)} rows from HISTORICAL_PLAYERLOG.json")
    return data


def load_current_playerlog() -> pd.DataFrame:
    if not PLAYERLOG_FILE.exists():
        print(f"WARNING: {PLAYERLOG_FILE} not found")
        return pd.DataFrame()
    df = pd.read_excel(PLAYERLOG_FILE)
    print(f"Loaded {len(df)} rows from PLAYERLOG.xlsx")
    return df


def load_rookie_seasons() -> dict | None:
    if ROOKIE_SEASONS_FILE.exists():
        with open(ROOKIE_SEASONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"Loaded {len(data)} entries from ROOKIE_SEASONS.json")
        return data
    print("ROOKIE_SEASONS.json not found -- skipping rookie records")
    return None


def load_all_drafts() -> list:
    drafts = []
    if ALL_DRAFTS_FILE.exists():
        with open(ALL_DRAFTS_FILE, "r", encoding="utf-8") as f:
            drafts = json.load(f)
    if DRAFT_PICKS_CURRENT_FILE.exists():
        with open(DRAFT_PICKS_CURRENT_FILE, "r", encoding="utf-8") as f:
            current = json.load(f)
        current_picks = current.get("picks", current if isinstance(current, list) else [])
        drafts.extend(current_picks)
    keepers = sum(1 for d in drafts if d.get("is_keeper", False))
    print(f"Loaded {len(drafts)} picks ({len(drafts) - keepers} draft, {keepers} keepers)")
    return drafts


def load_draft_pick_values() -> dict:
    if not DRAFT_PICK_VALUES_FILE.exists():
        print(f"WARNING: {DRAFT_PICK_VALUES_FILE} not found -- using defaults")
        return {}
    with open(DRAFT_PICK_VALUES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pick_values", {})


def load_all_trades() -> list:
    if not ALL_TRADES_FILE.exists():
        print(f"WARNING: {ALL_TRADES_FILE} not found")
        return []
    with open(ALL_TRADES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    with_players = sum(1 for t in data if any(p.get("player_name") for p in t.get("players", [])))
    print(f"Loaded {len(data)} trades ({with_players} with player data)")
    return data


def load_waivers() -> list:
    waivers = []
    malformed_lines = 0
    waiver_files = sorted(WAIVERS_DIR.glob("waivers_week*.txt"))
    # Expected line format (one per add):
    #   - [YYYY-MM-DD] Manager Name: Player Name (optional "(via trade)")
    line_re = re.compile(r"^- \[(?P<date>[^\]]+)\]\s*(?P<mgr>[^:]+):\s*(?P<player>.+)$")

    for wf in waiver_files:
        wk_match = re.search(r"waivers_week(\d+)\.txt", wf.name)
        week_num = int(wk_match.group(1)) if wk_match else 0
        with open(wf, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line.startswith("- ["):
                    continue

                m = line_re.match(line)
                if not m:
                    malformed_lines += 1
                    continue

                date = m.group("date").strip()
                mgr = m.group("mgr").strip()
                player_raw = m.group("player").strip()

                is_trade = "(via trade)" in player_raw
                player_name = re.sub(r"\s*\(via trade\)\s*$", "", player_raw).strip()

                # If any critical field is missing, skip the line safely.
                if not date or not mgr or not player_name:
                    malformed_lines += 1
                    continue

                waivers.append({
                    "date": date,
                    "manager": mgr,
                    "player_name": player_name,
                    "week": week_num,
                    "is_trade": is_trade,
                })

    if malformed_lines:
        print(f"  WARNING: Skipped {malformed_lines} malformed waiver line(s)")
    print(f"Loaded {len(waivers)} waiver adds from {len(waiver_files)} files")
    return waivers

def build_combined_playerlog(historical: list, current_df: pd.DataFrame) -> list:
    """
    Combine historical + current playerlog into deduplicated started-game list.
    GP = one game row with nonzero FP where started=True.
    Deduplicates by (player_name, date, manager, season) with normalized dates.
    """
    combined = []

    for row in historical:
        if not row.get("started", False):
            continue
        fp = row.get("fantasy_points")
        if fp is None:
            continue
        fp = float(fp)
        if fp == 0.0:
            continue
        combined.append({
            "player_name": row.get("player_name", ""),
            "manager": row.get("manager", ""),
            "fantasy_points": fp,
            "season": normalize_season(row.get("season_year", "")),
            "week": int(row.get("week", 0)),
            "date": normalize_date(row.get("date", "")),
            "slot": row.get("slot", ""),
        })

    if not current_df.empty:
        if "started" in current_df.columns:
            mask = (
                (current_df["started"] == True)
                & (current_df["fantasy_points"].notna())
                & (current_df["fantasy_points"] != 0)
            )
            if "nba_opponent" in current_df.columns:
                mask = mask & (current_df["nba_opponent"].notna())
        else:
            mask = (
                (current_df["fantasy_points"].notna())
                & (current_df["fantasy_points"] != 0)
            )

        for _, row in current_df[mask].iterrows():
            combined.append({
                "player_name": str(row.get("player_name", "")),
                "manager": str(row.get("manager", "")),
                "fantasy_points": float(row["fantasy_points"]),
                "season": normalize_season(str(row.get("season_year", CURRENT_SEASON_LONG))),
                "week": int(row.get("week", 0)),
                "date": normalize_date(str(row.get("date", ""))),
            })

    pre_dedup = len(combined)

    seen = {}
    for game in combined:
        key = (game["player_name"], game["date"], game["manager"], game["season"])
        if key in seen:
            if game["fantasy_points"] > seen[key]["fantasy_points"]:
                seen[key] = game
        else:
            seen[key] = game

    deduped = list(seen.values())
    post_dedup = len(deduped)
    removed = pre_dedup - post_dedup
    if removed:
        print(f"  Deduplicated: {pre_dedup} -> {post_dedup} games ({removed} duplicates removed)")
    else:
        print(f"  Combined playerlog: {post_dedup} games (no duplicates)")

    # Sanity checks
    season_gp = defaultdict(int)
    for g in deduped:
        season_gp[(g["player_name"], g["manager"], g["season"])] += 1
    flagged = {k: v for k, v in season_gp.items() if v > MAX_GAMES_PER_SEASON}
    if flagged:
        print(f"  WARNING: {len(flagged)} player-seasons exceed {MAX_GAMES_PER_SEASON} GP:")
        for (player, mgr, season), gp in sorted(flagged.items(), key=lambda x: -x[1])[:10]:
            print(f"    {player} ({mgr}, {season}): {gp} GP")

    return deduped


def build_all_records_with_slots(historical: list) -> list:
    records = []
    for row in historical:
        fp = row.get("fantasy_points")
        if fp is None:
            continue
        records.append({
            "player_name": row.get("player_name", ""),
            "manager": row.get("manager", ""),
            "fantasy_points": float(fp),
            "season": normalize_season(row.get("season_year", "")),
            "week": int(row.get("week", 0)),
            "date": normalize_date(row.get("date", "")),
            "slot": row.get("slot", ""),
        })
    return records


def compute_team_leaderboards(matchups: list, games: list = None, 
                               current_season_scores: dict = None,
                               current_season_totals: dict = None,
                               current_season: str = CURRENT_SEASON) -> dict:
    print("\n--- Computing Team Record Leaderboards ---")
    all_scores = []
    for m in matchups:
        season, week = m.get("season", ""), m.get("week", 0)
        all_scores.append({"score": m["score_a"], "manager": m["manager_a"], "season": season, "week": week})
        all_scores.append({"score": m["score_b"], "manager": m["manager_b"], "season": season, "week": week})

    # Enrich weekly scores with games/fppg from player data if available
    if games:
        week_games = defaultdict(int)
        for g in games:
            if g["fantasy_points"] != 0:
                week_games[(g["manager"], g["season"], g["week"])] += 1
        for s in all_scores:
            gc = week_games.get((s["manager"], s["season"], s["week"]), 0)
            s["games"] = gc
            s["fppg"] = round(s["score"] / gc, 1) if gc > 0 else 0

    highest_top10 = sorted(all_scores, key=lambda x: x["score"], reverse=True)[:10]
    lowest_top10 = sorted([s for s in all_scores if s["score"] > 0], key=lambda x: x["score"])[:10]
    print(f"  Highest Weekly Team Score: {highest_top10[0]['score']} by {highest_top10[0]['manager']}")
    print(f"  Lowest Weekly Team Score: {lowest_top10[0]['score']} by {lowest_top10[0]['manager']}")

    matchups_with_margin = [
        {"margin": round(m["margin"], 2), "winner": m["winner"], "loser": m["loser"],
         "season": m.get("season", ""), "week": m.get("week", 0)}
        for m in matchups if m.get("winner")
    ]
    biggest_blowout_top10 = sorted(matchups_with_margin, key=lambda x: x["margin"], reverse=True)[:10]
    closest_game_top10 = sorted(matchups_with_margin, key=lambda x: x["margin"])[:10]

    win_streak_top10, loss_streak_top10 = _compute_streaks(matchups)

    # HEAD-TO-HEAD RECORDS
    # NOTE: This computes historical H2H only from all_matchups.json.
    # Current season H2H is added by report_builder.py's _inject_current_season_into_all_time()
    h2h = {}
    managers = sorted(set(m.get("manager_a", "") for m in matchups) | set(m.get("manager_b", "") for m in matchups))
    for a in managers:
        for b in managers:
            if a == b:
                continue
            wins = sum(1 for m in matchups if m.get("winner") == a and m.get("loser") == b)
            h2h[f"{a}_vs_{b}"] = wins
    
    h2h["managers"] = managers
    print(f"  Head-to-head: {len(managers)} managers, {len(h2h)-1} matchup pairs")

    # BEST/WORST MANAGER SEASONS
    ms = defaultdict(lambda: {"wins": 0, "losses": 0, "total_fp": 0.0, "weeks": 0})
    for m in matchups:
        season = m.get("season", "")
        for side, score_key in [("manager_a", "score_a"), ("manager_b", "score_b")]:
            mgr = m[side]
            ms[(mgr, season)]["total_fp"] += m[score_key]
            ms[(mgr, season)]["weeks"] += 1
        w = m.get("winner")
        lo = m.get("loser")
        if w and lo:
            ms[(w, season)]["wins"] += 1
            ms[(lo, season)]["losses"] += 1
    
    # For current season: calculate total_fp and weeks directly from PLAYERLOG (games list)
    # This ensures we always use fresh data, since backfill runs BEFORE generate_stats_report
    # which would otherwise leave RECORDS.json["weekly_scores"] one week behind.
    if games:
        current_season_fp = defaultdict(float)
        current_season_weeks = defaultdict(set)
        for g in games:
            if g.get("season") == current_season and g["fantasy_points"] != 0:
                current_season_fp[g["manager"]] += g["fantasy_points"]
                current_season_weeks[g["manager"]].add(g["week"])
        
        for mgr in current_season_fp:
            ms[(mgr, current_season)]["total_fp"] = round(current_season_fp[mgr], 1)
            ms[(mgr, current_season)]["weeks"] = len(current_season_weeks[mgr])
        print(f"  Current season ({current_season}) totals from PLAYERLOG: {dict(current_season_fp)}")
    elif current_season_scores:
        # Fallback: use RECORDS.json weekly_scores if no games list (shouldn't happen)
        for mgr, scores in current_season_scores.items():
            if isinstance(scores, list):
                for entry in scores:
                    week = entry.get("week", 0)
                    score = entry.get("score", 0)
                    if score > 0:
                        ms[(mgr, current_season)]["total_fp"] += score
                        ms[(mgr, current_season)]["weeks"] += 1
        print(f"  Added current season ({current_season}) weekly scores (fallback from RECORDS.json)")
    
    # Add current season wins/losses from manager_season_totals
    if current_season_totals:
        for mgr, totals in current_season_totals.items():
            if (mgr, current_season) in ms:
                ms[(mgr, current_season)]["wins"] = totals.get("wins", 0)
                ms[(mgr, current_season)]["losses"] = totals.get("losses", 0)
        print(f"  Added current season ({current_season}) wins/losses")
    
    ms_list = [
        {"manager": mgr, "season": season, "wins": d["wins"], "losses": d["losses"],
         "total_fp": round(d["total_fp"], 1), "weeks": d["weeks"],
         "fppg_per_week": round(d["total_fp"] / d["weeks"], 1) if d["weeks"] > 0 else 0}
        for (mgr, season), d in ms.items()
    ]
    
    # For "Worst" leaderboards, require minimum 18 weeks to exclude incomplete seasons
    MIN_WEEKS_FOR_WORST = 18
    ms_list_complete = [x for x in ms_list if x["weeks"] >= MIN_WEEKS_FOR_WORST]
    
    # Total FP leaderboards (sorted by total_fp)
    best_manager_season_top10 = sorted(ms_list, key=lambda x: x["total_fp"], reverse=True)[:10]
    worst_manager_season_top10 = sorted(ms_list_complete, key=lambda x: x["total_fp"])[:10]
    # FP/week leaderboards (sorted by fppg_per_week)
    best_manager_season_fpweek_top10 = sorted(ms_list, key=lambda x: x["fppg_per_week"], reverse=True)[:10]
    worst_manager_season_fpweek_top10 = sorted(ms_list_complete, key=lambda x: x["fppg_per_week"])[:10]

    # BEST/WORST MANAGER SEASONS BY FP/GAME
    # Requires game-level data to compute total games started per manager-season
    best_manager_season_fppg_top10 = []
    worst_manager_season_fppg_top10 = []
    if games:
        # Count total games per manager per season (only non-zero FP games = actual starts)
        season_games = defaultdict(int)
        for g in games:
            if g["fantasy_points"] != 0:
                season_games[(g["manager"], g["season"])] += 1
        
        # Build list with FP/game for seasons that have game data
        ms_fppg_list = []
        for (mgr, season), d in ms.items():
            total_games = season_games.get((mgr, season), 0)
            if total_games > 0:
                fppg = round(d["total_fp"] / total_games, 1)
                ms_fppg_list.append({
                    "manager": mgr,
                    "season": season,
                    "wins": d["wins"],
                    "losses": d["losses"],
                    "total_fp": round(d["total_fp"], 1),
                    "weeks": d["weeks"],
                    "games": total_games,
                    "fppg": fppg,
                })
        
        if ms_fppg_list:
            best_manager_season_fppg_top10 = sorted(
                ms_fppg_list, key=lambda x: x["fppg"], reverse=True
            )[:10]
            # Filter for complete seasons (min 18 weeks) for worst leaderboard
            ms_fppg_complete = [x for x in ms_fppg_list if x["weeks"] >= MIN_WEEKS_FOR_WORST]
            worst_manager_season_fppg_top10 = sorted(
                ms_fppg_complete, key=lambda x: x["fppg"]
            )[:10]
            print(f"  Best Manager Season (FP/game): {best_manager_season_fppg_top10[0]['fppg']} by {best_manager_season_fppg_top10[0]['manager']} ({best_manager_season_fppg_top10[0]['season']})")
            print(f"  Worst Manager Season (FP/game): {worst_manager_season_fppg_top10[0]['fppg']} by {worst_manager_season_fppg_top10[0]['manager']} ({worst_manager_season_fppg_top10[0]['season']})")
        else:
            print("  FP/game records: No game-level data available")
    else:
        print("  FP/game records: Skipped (no game-level data provided)")

    result = {
        "highest_weekly_score_top10": highest_top10,
        "lowest_weekly_score_top10": lowest_top10,
        "biggest_blowout_top10": biggest_blowout_top10,
        "closest_game_top10": closest_game_top10,
        "longest_win_streak_top10": win_streak_top10,
        "longest_loss_streak_top10": loss_streak_top10,
        "head_to_head": h2h,
        "head_to_head_historical": h2h.copy(),  # Preserved baseline for report_builder.py
        "best_manager_season_top10": best_manager_season_top10,
        "worst_manager_season_top10": worst_manager_season_top10,
        "best_manager_season_fpweek_top10": best_manager_season_fpweek_top10,
        "worst_manager_season_fpweek_top10": worst_manager_season_fpweek_top10,
    }
    
    # Only add FP/game leaderboards if we have data
    if best_manager_season_fppg_top10:
        result["best_manager_season_fppg_top10"] = best_manager_season_fppg_top10
    if worst_manager_season_fppg_top10:
        result["worst_manager_season_fppg_top10"] = worst_manager_season_fppg_top10
    
    return result


def _compute_streaks(matchups: list) -> tuple:
    by_season = defaultdict(list)
    for m in matchups:
        by_season[m.get("season", "")].append(m)

    all_win, all_loss = [], []
    for season, sm in sorted(by_season.items()):
        sm.sort(key=lambda x: x.get("week", 0))
        cw, cl = defaultdict(int), defaultdict(int)
        for m in sm:
            w, lo = m.get("winner"), m.get("loser")
            if not w or not lo:
                continue
            cw[w] += 1
            if cl[w] > 0:
                all_loss.append({"length": cl[w], "manager": w, "season": season})
            cl[w] = 0
            cl[lo] += 1
            if cw[lo] > 0:
                all_win.append({"length": cw[lo], "manager": lo, "season": season})
            cw[lo] = 0
        for mgr, length in cw.items():
            if length > 0:
                all_win.append({"length": length, "manager": mgr, "season": season})
        for mgr, length in cl.items():
            if length > 0:
                all_loss.append({"length": length, "manager": mgr, "season": season})

    return (
        sorted(all_win, key=lambda x: x["length"], reverse=True)[:10],
        sorted(all_loss, key=lambda x: x["length"], reverse=True)[:10],
    )


def compute_player_leaderboards(games: list) -> dict:
    print("\n--- Computing Player Record Leaderboards ---")
    if not games:
        return {}

    # Single game records
    by_fp_desc = sorted(games, key=lambda x: x["fantasy_points"], reverse=True)
    highest_top10 = [
        {"player_name": g["player_name"], "manager": g["manager"],
         "fantasy_points": round(g["fantasy_points"], 2),
         "date": g["date"], "season": g["season"], "week": g["week"]}
        for g in by_fp_desc[:10]
    ]
    by_fp_asc = sorted(games, key=lambda x: x["fantasy_points"])
    lowest_top10 = [
        {"player_name": g["player_name"], "manager": g["manager"],
         "fantasy_points": round(g["fantasy_points"], 2),
         "date": g["date"], "season": g["season"], "week": g["week"]}
        for g in by_fp_asc[:10]
    ]

    # Season stats -- consolidated by (player, season), not (player, manager, season)
    season_stats = defaultdict(lambda: {"fp": 0.0, "gp": 0, "managers": set()})
    for g in games:
        key = (g["season"], g["player_name"])
        season_stats[key]["fp"] += g["fantasy_points"]
        season_stats[key]["gp"] += 1
        season_stats[key]["managers"].add(g["manager"])

    for (season, player), stats in season_stats.items():
        if stats["gp"] > MAX_GAMES_PER_SEASON:
            original_gp = stats["gp"]
            mgrs = ", ".join(sorted(stats.get("managers", [])))
            print(
                f"WARNING: GP cap triggered: {player} ({season}) has {original_gp} GP "
                f"(managers: {mgrs}). Likely duplicate game rows. Capping to {MAX_GAMES_PER_SEASON}."
            )
            stats["gp"] = MAX_GAMES_PER_SEASON

    # Season FPPG (min 30 GP)
    fppg_entries = []
    for (season, player), stats in season_stats.items():
        if stats["gp"] >= MIN_GP_FPPG:
            fppg_entries.append({
                "player_name": player, "manager": ", ".join(sorted(stats["managers"])),
                "fppg": round(stats["fp"] / stats["gp"], 2),
                "gp": stats["gp"], "total_fp": round(stats["fp"], 1),
                "season": season,
            })
    fppg_entries.sort(key=lambda x: x["fppg"], reverse=True)

    # Season Total FP
    totalfp_entries = [
        {"player_name": player, "manager": ", ".join(sorted(stats["managers"])),
         "total_fp": round(stats["fp"], 1), "gp": stats["gp"],
         "fppg": round(stats["fp"] / stats["gp"], 2) if stats["gp"] > 0 else 0,
         "season": season}
        for (season, player), stats in season_stats.items()
    ]
    totalfp_entries.sort(key=lambda x: x["total_fp"], reverse=True)

    # Most FP Single Week -- consolidated by (player, week, season)
    weekly_totals = defaultdict(lambda: {"fps": [], "managers": set()})
    for g in games:
        key = (g["season"], g["week"], g["player_name"])
        weekly_totals[key]["fps"].append(g["fantasy_points"])
        weekly_totals[key]["managers"].add(g["manager"])

    weekly_entries = []
    weekly_fppg_entries = []
    for (season, week, player), data in weekly_totals.items():
        fps = data["fps"]
        capped = sorted(fps, reverse=True)[:MAX_GAMES_PER_WEEK]
        mgr_str = ", ".join(sorted(data["managers"]))
        weekly_entries.append({
            "player_name": player, "manager": mgr_str,
            "weekly_fp": round(sum(capped), 2), "games": len(capped),
            "season": season, "week": week,
        })
        # Best FPPG in Single Week (min 3 games)
        if len(capped) >= 3:
            weekly_fppg_entries.append({
                "player_name": player, "manager": mgr_str,
                "weekly_fppg": round(sum(capped) / len(capped), 2), "games": len(capped),
                "weekly_fp": round(sum(capped), 2),
                "season": season, "week": week,
            })
    weekly_entries.sort(key=lambda x: x["weekly_fp"], reverse=True)
    weekly_fppg_entries.sort(key=lambda x: x["weekly_fppg"], reverse=True)

    for label, lst in [("Best Season FPPG", fppg_entries), ("Best Season Total FP", totalfp_entries), ("Most FP Single Week", weekly_entries)]:
        if lst:
            e = lst[0]
            val = e.get("fppg", e.get("total_fp", e.get("weekly_fp", "?")))
            print(f"  {label}: {val} by {e['player_name']} ({e['season']})")

    # Change 4: Most Games Over 40 FP (player, season) -- consolidated by (player, season)
    player_over40 = defaultdict(lambda: {"count": 0, "gp": 0, "managers": set()})
    for g in games:
        key = (g["season"], g["player_name"])
        player_over40[key]["gp"] += 1
        player_over40[key]["managers"].add(g["manager"])
        if g["fantasy_points"] >= 40:
            player_over40[key]["count"] += 1
    over40_entries = [
        {"player_name": player, "manager": ", ".join(sorted(data["managers"])),
         "count": data["count"], "gp": data["gp"],
         "season": season}
        for (season, player), data in player_over40.items()
        if data["count"] >= 1
    ]
    over40_entries.sort(key=lambda x: x["count"], reverse=True)

    return {
        "highest_single_game": highest_top10[0] if highest_top10 else {},
        "highest_single_game_top10": highest_top10,
        "lowest_single_game": lowest_top10[0] if lowest_top10 else {},
        "lowest_single_game_top10": lowest_top10,
        "best_season_fppg": fppg_entries[0] if fppg_entries else {},
        "best_season_fppg_top10": fppg_entries[:10],
        "best_season_total_fp": totalfp_entries[0] if totalfp_entries else {},
        "best_season_total_fp_top10": totalfp_entries[:10],
        "most_fp_single_week": weekly_entries[0] if weekly_entries else {},
        "most_fp_single_week_top10": weekly_entries[:10],
        "best_fppg_single_week": weekly_fppg_entries[0] if weekly_fppg_entries else {},
        "best_fppg_single_week_top10": weekly_fppg_entries[:10],
        "most_games_over_40": over40_entries[0] if over40_entries else {},
        "most_games_over_40_top10": over40_entries[:10],
    }


def compute_rookie_leaderboards(games: list, rookie_seasons: dict) -> dict:
    print("\n--- Computing Rookie Record Leaderboards ---")
    rookie_games = [
        g for g in games
        if g["player_name"] in rookie_seasons
        and g["season"] == normalize_season(rookie_seasons[g["player_name"]])
    ]
    print(f"  Found {len(rookie_games)} rookie games across {len(set(g['player_name'] for g in rookie_games))} players")
    if not rookie_games:
        return {}

    # Single game
    by_fp = sorted(rookie_games, key=lambda x: x["fantasy_points"], reverse=True)
    sg_top10 = [
        {"player_name": g["player_name"], "manager": g["manager"],
         "fantasy_points": round(g["fantasy_points"], 2),
         "date": g["date"], "season": g["season"], "week": g["week"]}
        for g in by_fp[:10]
    ]

    # Season stats -- consolidated by (player, season) not (player, manager, season)
    season_stats = defaultdict(lambda: {"fp": 0.0, "gp": 0, "managers": set()})
    for g in rookie_games:
        key = (g["season"], g["player_name"])
        season_stats[key]["fp"] += g["fantasy_points"]
        season_stats[key]["gp"] += 1
        season_stats[key]["managers"].add(g["manager"])
    for (season, player), stats in season_stats.items():
        if stats["gp"] > MAX_GAMES_PER_SEASON:
            original_gp = stats["gp"]
            mgrs = ", ".join(sorted(stats.get("managers", [])))
            print(
                f"WARNING: ROOKIE GP cap triggered: {player} ({season}) has {original_gp} GP "
                f"(managers: {mgrs}). Likely duplicate game rows. Capping to {MAX_GAMES_PER_SEASON}."
            )
            stats["gp"] = MAX_GAMES_PER_SEASON

    fppg_entries, totalfp_entries = [], []
    for (season, player), stats in season_stats.items():
        gp, total_fp = stats["gp"], round(stats["fp"], 1)
        mgr_str = ", ".join(sorted(stats["managers"]))
        fppg_val = round(stats["fp"] / gp, 2) if gp > 0 else 0
        totalfp_entries.append({"player_name": player, "manager": mgr_str, "total_fp": total_fp, "gp": gp, "fppg": fppg_val, "season": season})
        if gp >= MIN_GP_FPPG:
            fppg_entries.append({"player_name": player, "manager": mgr_str, "fppg": fppg_val, "gp": gp, "total_fp": total_fp, "season": season})
    fppg_entries.sort(key=lambda x: x["fppg"], reverse=True)
    totalfp_entries.sort(key=lambda x: x["total_fp"], reverse=True)

    # Weekly -- consolidated by (player, week, season)
    weekly_totals = defaultdict(lambda: {"fps": [], "managers": set()})
    for g in rookie_games:
        key = (g["season"], g["week"], g["player_name"])
        weekly_totals[key]["fps"].append(g["fantasy_points"])
        weekly_totals[key]["managers"].add(g["manager"])
    weekly_entries = []
    weekly_fppg_entries = []
    for (season, week, player), data in weekly_totals.items():
        fps = data["fps"]
        capped = sorted(fps, reverse=True)[:MAX_GAMES_PER_WEEK]
        mgr_str = ", ".join(sorted(data["managers"]))
        weekly_entries.append({"player_name": player, "manager": mgr_str, "weekly_fp": round(sum(capped), 2), "games": len(capped), "season": season, "week": week})
        if len(capped) >= 3:
            weekly_fppg_entries.append({"player_name": player, "manager": mgr_str,
                "weekly_fppg": round(sum(capped) / len(capped), 2), "games": len(capped),
                "weekly_fp": round(sum(capped), 2), "season": season, "week": week})
    weekly_entries.sort(key=lambda x: x["weekly_fp"], reverse=True)
    weekly_fppg_entries.sort(key=lambda x: x["weekly_fppg"], reverse=True)

    return {
        "best_rookie_single_game": sg_top10[0] if sg_top10 else {},
        "best_rookie_single_game_top10": sg_top10,
        "best_rookie_season_fppg": fppg_entries[0] if fppg_entries else {},
        "best_rookie_season_fppg_top10": fppg_entries[:10],
        "best_rookie_season_total_fp": totalfp_entries[0] if totalfp_entries else {},
        "best_rookie_season_total_fp_top10": totalfp_entries[:10],
        "best_rookie_fantasy_week": weekly_entries[0] if weekly_entries else {},
        "best_rookie_fantasy_week_top10": weekly_entries[:10],
        "best_rookie_fppg_week": weekly_fppg_entries[0] if weekly_fppg_entries else {},
        "best_rookie_fppg_week_top10": weekly_fppg_entries[:10],
    }


def compute_expanded_leaderboards(games: list) -> dict:
    import statistics as stats_mod
    print("\n--- Computing Expanded Record Leaderboards ---")
    if not games:
        return {}

    games_by_season = defaultdict(list)
    for g in games:
        games_by_season[g["season"]].append(g)

    # ---- DAILY TEAM FPPG (best/worst, 5-starter min) + DAILY TEAM SCORE ----
    best_dtf, worst_dtf, daily_score = [], [], []
    for season, sg in games_by_season.items():
        day_teams = defaultdict(list)
        for g in sg:
            if g["fantasy_points"] != 0:
                day_teams[(g["date"], g["manager"])].append(g)

        for (date, mgr), gs in day_teams.items():
            fps = [g["fantasy_points"] for g in gs]
            total, n = sum(fps), len(fps)
            wk = gs[0]["week"]
            daily_score.append({"manager": mgr, "total_fp": round(total, 1), "starters": n, "date": date, "week": wk, "season": season})
            if n >= 5:
                avg = total / n if n > 0 else 0
                entry = {"manager": mgr, "avg_fp": round(avg, 1), "total_fp": round(total, 1), "starters": n, "date": date, "week": wk, "season": season}
                best_dtf.append(entry)
                worst_dtf.append(dict(entry))

    best_dtf.sort(key=lambda x: x["avg_fp"], reverse=True)
    worst_dtf.sort(key=lambda x: x["avg_fp"])
    daily_score.sort(key=lambda x: x["total_fp"], reverse=True)

    # ---- TEAM FPPG (WEEK) ----
    twf = []
    for season, sg in games_by_season.items():
        team_weeks = defaultdict(list)
        for g in sg:
            if g["fantasy_points"] != 0:
                team_weeks[(g["manager"], g["week"])].append(g["fantasy_points"])
        for (mgr, wk), fps in team_weeks.items():
            if len(fps) >= 5:
                twf.append({"manager": mgr, "avg_fppg": round(sum(fps) / len(fps), 2), "total_fp": round(sum(fps), 1), "games": len(fps), "week": wk, "season": season})
    twf_high = sorted(twf, key=lambda x: x["avg_fppg"], reverse=True)[:10]
    twf_low = sorted(twf, key=lambda x: x["avg_fppg"])[:10]

    # ---- DUOS: Day, Week, Season ----
    duo_day, duo_week, duo_season = [], [], []
    for season, sg in games_by_season.items():
        played = [g for g in sg if g["fantasy_points"] > 0]

        # Day
        ddt = defaultdict(list)
        for g in played:
            ddt[(g["manager"], g["date"])].append((g["player_name"], g["fantasy_points"]))
        for (mgr, date), players in ddt.items():
            if len(players) >= 2:
                players.sort(key=lambda x: x[1], reverse=True)
                p1, fp1 = players[0]; p2, fp2 = players[1]
                wk = next((g["week"] for g in played if g["date"] == date and g["manager"] == mgr), 0)
                duo_day.append({"manager": mgr, "combined_fp": round(fp1 + fp2, 1), "player1": p1, "player1_fp": round(fp1, 1), "player2": p2, "player2_fp": round(fp2, 1), "date": date, "week": wk, "season": season})

        # Week
        pw = defaultdict(float)
        for g in played:
            pw[(g["manager"], g["week"], g["player_name"])] += g["fantasy_points"]
        tw = defaultdict(list)
        for (mgr, wk, player), fp in pw.items():
            tw[(mgr, wk)].append((player, fp))
        for (mgr, wk), players in tw.items():
            if len(players) >= 2:
                players.sort(key=lambda x: x[1], reverse=True)
                p1, fp1 = players[0]; p2, fp2 = players[1]
                duo_week.append({"manager": mgr, "combined_fp": round(fp1 + fp2, 1), "player1": p1, "player1_fp": round(fp1, 1), "player2": p2, "player2_fp": round(fp2, 1), "week": wk, "season": season})

        # Season
        ps = defaultdict(float)
        for g in played:
            ps[(g["manager"], g["player_name"])] += g["fantasy_points"]
        ts = defaultdict(list)
        for (mgr, player), fp in ps.items():
            ts[mgr].append((player, fp))
        for mgr, players in ts.items():
            if len(players) >= 2:
                players.sort(key=lambda x: x[1], reverse=True)
                p1, fp1 = players[0]; p2, fp2 = players[1]
                duo_season.append({"manager": mgr, "combined_fp": round(fp1 + fp2, 1), "player1": p1, "player1_fp": round(fp1, 1), "player2": p2, "player2_fp": round(fp2, 1), "season": season})

    duo_day.sort(key=lambda x: x["combined_fp"], reverse=True)
    duo_week.sort(key=lambda x: x["combined_fp"], reverse=True)
    duo_season.sort(key=lambda x: x["combined_fp"], reverse=True)

    # ---- 40+ and <20 GAMES (WEEK) -- game-level counting ----
    hot, cold = [], []
    for season, sg in games_by_season.items():
        glw = defaultdict(lambda: {"over_40": 0, "under_20": 0, "total": 0})
        for g in sg:
            if g["fantasy_points"] != 0:
                key = (g["manager"], g["week"])
                glw[key]["total"] += 1
                if g["fantasy_points"] >= 40:
                    glw[key]["over_40"] += 1
                if 0 < g["fantasy_points"] < 20:
                    glw[key]["under_20"] += 1
        for (mgr, wk), c in glw.items():
            if c["over_40"] >= 3:
                hot.append({"manager": mgr, "count": c["over_40"], "total_games": c["total"], "week": wk, "season": season})
            if c["under_20"] >= 3:
                cold.append({"manager": mgr, "count": c["under_20"], "total_games": c["total"], "week": wk, "season": season})
    hot.sort(key=lambda x: x["count"], reverse=True)
    cold.sort(key=lambda x: x["count"], reverse=True)

    # ---- OUTPERFORMANCE, CONSISTENCY, MOST GAMES UNDER 20, MONDAY, SUNDAY ----
    outperf, consist, garbage, monday, sunday = [], [], [], [], []
    for season, sg in games_by_season.items():
        played = [g for g in sg if g["fantasy_points"] > 0]
        pstats = defaultdict(lambda: {"fps": [], "dates": [], "mgr": ""})
        for g in played:
            pstats[(g["player_name"], g["manager"])]["fps"].append(g["fantasy_points"])
            pstats[(g["player_name"], g["manager"])]["dates"].append(g.get("date", ""))
            pstats[(g["player_name"], g["manager"])]["mgr"] = g["manager"]

        for (player, mgr), stats in pstats.items():
            fps = stats["fps"]
            dates = stats["dates"]
            gp = min(len(fps), MAX_GAMES_PER_SEASON)
            avg = sum(fps) / len(fps) if len(fps) > 0 else 0
            if len(fps) >= 10:
                for fp, dt in zip(fps, dates):
                    delta = fp - avg
                    if delta > 15:
                        outperf.append({"player_name": player, "manager": mgr, "game_fp": round(fp, 2), "season_avg": round(avg, 2), "delta": round(delta, 1), "season": season, "date": dt})
            if gp >= MIN_GP_FPPG:
                consist.append({"player_name": player, "manager": mgr, "std_dev": round(stats_mod.stdev(fps), 2), "avg_fp": round(avg, 1), "gp": gp, "season": season})
            if gp >= 20:
                u20 = sum(1 for fp in fps if fp < 20)
                if u20 > 0:
                    garbage.append({"player_name": player, "manager": mgr, "under_20_count": u20, "total_starts": gp, "pct": round(u20 / gp * 100, 1), "season": season})

        mon_stats = defaultdict(list)
        sun_stats = defaultdict(list)
        for g in played:
            try:
                dow = datetime.strptime(g["date"], "%Y-%m-%d").weekday()
                if dow == 0:  # Monday
                    mon_stats[(g["player_name"], g["manager"])].append(g["fantasy_points"])
                elif dow == 6:  # Sunday
                    sun_stats[(g["player_name"], g["manager"])].append(g["fantasy_points"])
            except (ValueError, KeyError):
                pass
        for (player, mgr), mfps in mon_stats.items():
            if len(mfps) >= 5:
                monday.append({"player_name": player, "manager": mgr, "avg_fp": round(sum(mfps) / len(mfps), 1), "monday_games": len(mfps), "season": season})
        for (player, mgr), sfps in sun_stats.items():
            if len(sfps) >= 5:
                sunday.append({"player_name": player, "manager": mgr, "avg_fp": round(sum(sfps) / len(sfps), 1), "sunday_games": len(sfps), "season": season})

    outperf.sort(key=lambda x: x["delta"], reverse=True)
    consist.sort(key=lambda x: x["std_dev"])
    garbage.sort(key=lambda x: x["under_20_count"], reverse=True)
    monday.sort(key=lambda x: x["avg_fp"], reverse=True)
    sunday.sort(key=lambda x: x["avg_fp"], reverse=True)

    # ---- CAREER RECORDS (all-time) ----
    # Store historical_fp (all seasons except current) so the weekly pipeline
    # can recompute total = historical_fp + live current-season FP
    current_season = max(g["season"] for g in games) if games else CURRENT_SEASON

    # Career Total FP By Manager (old "franchise_player" - tracks player+manager combos)
    fran = defaultdict(lambda: {"fp": 0.0, "gp": 0, "hist_fp": 0.0, "hist_gp": 0, "seasons": set()})
    for g in games:
        if g["fantasy_points"] > 0:
            key = (g["player_name"], g["manager"])
            fran[key]["fp"] += g["fantasy_points"]
            fran[key]["gp"] += 1
            fran[key]["seasons"].add(g["season"])
            if g["season"] != current_season:
                fran[key]["hist_fp"] += g["fantasy_points"]
                fran[key]["hist_gp"] += 1
    career_by_mgr = sorted([
        {"player_name": p, "manager": m, "total_fp": round(s["fp"], 1), "gp": s["gp"],
         "historical_fp": round(s["hist_fp"], 1), "historical_gp": s["hist_gp"],
         "seasons": len(s["seasons"]), "fppg": round(s["fp"] / s["gp"], 2) if s["gp"] > 0 else 0,
         "season": "all-time"}
        for (p, m), s in fran.items()
    ], key=lambda x: x["total_fp"], reverse=True)

    # Extract franchise player badge per manager (best player by total FP for each)
    franchise_badges = {}
    for entry in career_by_mgr:
        mgr = entry["manager"]
        if mgr not in franchise_badges:
            franchise_badges[mgr] = {"player": entry["player_name"], "total_fp": entry["total_fp"]}

    # Career Total FP (pure player, aggregated across all managers)
    career_pure = defaultdict(lambda: {"fp": 0.0, "gp": 0, "hist_fp": 0.0, "hist_gp": 0, "seasons": set(), "managers": set()})
    for g in games:
        if g["fantasy_points"] > 0:
            career_pure[g["player_name"]]["fp"] += g["fantasy_points"]
            career_pure[g["player_name"]]["gp"] += 1
            career_pure[g["player_name"]]["seasons"].add(g["season"])
            career_pure[g["player_name"]]["managers"].add(g["manager"])
            if g["season"] != current_season:
                career_pure[g["player_name"]]["hist_fp"] += g["fantasy_points"]
                career_pure[g["player_name"]]["hist_gp"] += 1
    career_total_fp = sorted([
        {"player_name": p, "manager": ", ".join(sorted(s["managers"])), "total_fp": round(s["fp"], 1), "gp": s["gp"],
         "historical_fp": round(s["hist_fp"], 1), "historical_gp": s["hist_gp"],
         "seasons": len(s["seasons"]), "fppg": round(s["fp"] / s["gp"], 2) if s["gp"] > 0 else 0,
         "season": "all-time"}
        for p, s in career_pure.items()
    ], key=lambda x: x["total_fp"], reverse=True)

    # Career FPPG (min 150 GP, pure player)
    MIN_GP_CAREER = 150
    career_fppg = sorted([
        e for e in career_total_fp if e["gp"] >= MIN_GP_CAREER
    ], key=lambda x: x["fppg"], reverse=True)

    # ---- LONGEST PLAYER TENURE (consecutive seasons with same manager) ----
    all_seasons = sorted(set(g["season"] for g in games))
    pms = defaultdict(set)
    for g in games:
        if g["fantasy_points"] > 0:
            pms[(g["player_name"], g["manager"])].add(g["season"])

    tenure_all = []
    for (player, mgr), seasons_set in pms.items():
        sorted_s = sorted(seasons_set)
        if len(sorted_s) < 2:
            continue
        # Find longest run of consecutive seasons
        best_run, current_run = 1, 1
        best_start, best_end = sorted_s[0], sorted_s[0]
        run_start = sorted_s[0]
        for i in range(1, len(sorted_s)):
            prev_idx = all_seasons.index(sorted_s[i - 1]) if sorted_s[i - 1] in all_seasons else -1
            curr_idx = all_seasons.index(sorted_s[i]) if sorted_s[i] in all_seasons else -1
            if curr_idx == prev_idx + 1:
                current_run += 1
                if current_run > best_run:
                    best_run = current_run
                    best_start = run_start
                    best_end = sorted_s[i]
            else:
                current_run = 1
                run_start = sorted_s[i]
        if best_run >= 2:
            tenure_all.append({
                "player_name": player, "manager": mgr,
                "consecutive_seasons": best_run,
                "start_season": best_start, "end_season": best_end,
                "active": best_end == current_season,
                "season": "all-time",
            })
    tenure_all.sort(key=lambda x: x["consecutive_seasons"], reverse=True)

    def _t(lst):
        return (lst[0] if lst else {}, lst[:10])

    result = {}
    for name, data in [
        ("best_daily_team_fppg", best_dtf), ("worst_daily_team_fppg", worst_dtf),
        ("highest_daily_team_score", daily_score),
        ("team_fppg_week_high", twf_high), ("team_fppg_week_low", twf_low),
        ("best_duo_day", duo_day), ("best_duo_week", duo_week), ("best_duo_season", duo_season),
        ("most_40plus_games_week", hot), ("most_sub20_games_week", cold),
        ("biggest_outperformance", outperf), ("most_consistent_player", consist),
        ("most_games_under_20", garbage), ("mr_monday_night", monday),
        ("mr_4th_quarter", sunday),
        ("career_total_fp_by_manager", career_by_mgr),
        ("career_total_fp", career_total_fp),
        ("career_fppg", career_fppg),
        ("longest_player_tenure", tenure_all),
    ]:
        single, top10 = _t(data)
        result[name] = single
        result[f"{name}_top10"] = top10

    # Legacy aliases for backward compatibility
    result["best_collective_team_game"] = result["best_daily_team_fppg"]
    result["best_collective_team_game_top10"] = result["best_daily_team_fppg_top10"]
    result["worst_collective_team_game"] = result["worst_daily_team_fppg"]
    result["worst_collective_team_game_top10"] = result["worst_daily_team_fppg_top10"]
    result["best_duo_output"] = result["best_duo_week"]
    result["best_duo_output_top10"] = result["best_duo_week_top10"]
    result["most_40plus_fp_week"] = result["most_40plus_games_week"]
    result["most_40plus_fp_week_top10"] = result["most_40plus_games_week_top10"]
    # Legacy alias for garbage_time_king (now most_games_under_20)
    result["garbage_time_king"] = result["most_games_under_20"]
    result["garbage_time_king_top10"] = result["most_games_under_20_top10"]
    # Legacy alias for franchise_player (now career_total_fp_by_manager)
    result["franchise_player"] = result["career_total_fp_by_manager"]
    result["franchise_player_top10"] = result["career_total_fp_by_manager_top10"]
    # Franchise badges (one per manager for milestone cards)
    result["franchise_badges"] = franchise_badges

    for name in ["best_daily_team_fppg", "highest_daily_team_score", "best_duo_week", "most_40plus_games_week", "career_total_fp_by_manager", "career_total_fp", "longest_player_tenure"]:
        e = result.get(name, {})
        if e:
            val = e.get("avg_fp", e.get("total_fp", e.get("combined_fp", e.get("count", "?"))))
            holder = e.get("player_name", e.get("manager", "?"))
            print(f"  {name}: {val} by {holder} ({e.get('season', '?')})")

    return result


def compute_draft_manager_leaderboards(games, drafts, trades=None, waivers=None, all_records=None) -> dict:
    print("\n--- Computing Draft, Trade & Manager Leaderboards ---")
    if not games or not drafts:
        return {}

    pss = defaultdict(lambda: {"total_fp": 0.0, "gp": 0, "fps": []})
    for g in games:
        if g["fantasy_points"] > 0:
            key = (g["player_name"], g["manager"], g["season"])
            pss[key]["total_fp"] += g["fantasy_points"]
            pss[key]["gp"] += 1
            pss[key]["fps"].append(g["fantasy_points"])

    pick_values = load_draft_pick_values()

    # Keeper-era filter (from config/league_config.json)

    # BEST DRAFT CLASS (real draft picks only, top 7 per team, keeper era only)
    dbc = defaultdict(list)
    for pick in drafts:
        if not pick.get("is_keeper", False) and pick["season"] >= KEEPER_ERA_START:
            dbc[(pick["manager"], pick["season"])].append(pick)
    dc_all = []
    for (mgr, season), picks in dbc.items():
        # Sort by round (earliest picks first) and take top 7
        picks_sorted = sorted(picks, key=lambda p: p.get("round", 99))[:7]
        fp, gp, cnt = 0.0, 0, 0
        for p in picks_sorted:
            s = pss.get((p["player_name"], mgr, season))
            if s and s["gp"] > 0:
                fp += s["total_fp"]; gp += s["gp"]; cnt += 1
        if cnt >= 3:
            dc_all.append({"manager": mgr, "total_fp": round(fp, 1), "total_gp": gp, "player_count": cnt, "draft_year": season, "season": season})
    dc_all.sort(key=lambda x: x["total_fp"], reverse=True)

    # BEST DRAFT CLASS BY FPPG (top 7 picks, min 20 GP per player, keeper era only)
    dc_fppg = []
    for (mgr, season), picks in dbc.items():
        picks_sorted = sorted(picks, key=lambda p: p.get("round", 99))[:7]
        qualifying = []
        for p in picks_sorted:
            s = pss.get((p["player_name"], mgr, season))
            if s and s["gp"] >= 20:
                qualifying.append({"fppg": s["total_fp"] / s["gp"], "gp": s["gp"]})
        if len(qualifying) >= 3:
            avg_fppg = sum(q["fppg"] for q in qualifying) / len(qualifying)
            total_gp = sum(q["gp"] for q in qualifying)
            dc_fppg.append({"manager": mgr, "avg_fppg": round(avg_fppg, 2), "total_gp": total_gp,
                            "player_count": len(qualifying), "draft_year": season, "season": season})
    dc_fppg.sort(key=lambda x: x["avg_fppg"], reverse=True)

    # DRAFT STEAL & BUST BY FPPG (real picks, delta vs expected FPPG, keeper era only)
    steal_fppg, bust_fppg = [], []
    # DRAFT STEAL & BUST BY TOTAL FP (real picks, delta vs expected Total FP, keeper era only)
    steal_totalfp, bust_totalfp = [], []

    for pick in drafts:
        if pick.get("is_keeper", False):
            continue
        if pick["season"] < KEEPER_ERA_START:
            continue
        s = pss.get((pick["player_name"], pick["manager"], pick["season"]))
        if not s or s["gp"] < 20:
            continue

        # Look up expected values by individual pick number (not round)
        pick_str = str(pick["pick_number"])
        pv = pick_values.get(pick_str, {})

        # FPPG steal/bust
        actual_fppg = s["total_fp"] / s["gp"]
        expected_fppg = pv.get("expected_projFPPG", {}).get("mid", 35.0)
        delta_fppg = actual_fppg - expected_fppg
        fppg_entry = {
            "player_name": pick["player_name"], "manager": pick["manager"],
            "round": pick["round"], "pick_number": pick["pick_number"],
            "fppg": round(actual_fppg, 2), "expected_fppg": expected_fppg,
            "delta": round(delta_fppg, 2),
            "total_fp": round(s["total_fp"], 1), "gp": s["gp"],
            "season": pick["season"],
        }
        if delta_fppg > 0:
            steal_fppg.append(fppg_entry)
        if delta_fppg < 0:
            bust_fppg.append(dict(fppg_entry))

        # Total FP steal/bust
        actual_totalfp = s["total_fp"]
        expected_totalfp = pv.get("expected_total_fp", {}).get("mid", 1500.0)
        delta_totalfp = actual_totalfp - expected_totalfp
        totalfp_entry = {
            "player_name": pick["player_name"], "manager": pick["manager"],
            "round": pick["round"], "pick_number": pick["pick_number"],
            "total_fp": round(actual_totalfp, 1), "expected_total_fp": expected_totalfp,
            "delta": round(delta_totalfp, 1),
            "fppg": round(actual_fppg, 2), "gp": s["gp"],
            "season": pick["season"],
        }
        if delta_totalfp > 0:
            steal_totalfp.append(totalfp_entry)
        if delta_totalfp < 0:
            bust_totalfp.append(dict(totalfp_entry))

    steal_fppg.sort(key=lambda x: x["delta"], reverse=True)
    bust_fppg.sort(key=lambda x: x["delta"])
    steal_totalfp.sort(key=lambda x: x["delta"], reverse=True)
    bust_totalfp.sort(key=lambda x: x["delta"])

    # TRADE WINNER
    tw_top10 = []
    if trades:
        tr = []
        for trade in trades:
            for p in trade.get("players", []):
                pname, to_m, from_m = p.get("player_name", ""), p.get("to_manager", ""), p.get("from_manager", "")
                if not pname or not to_m:
                    continue
                s = pss.get((pname, to_m, trade["season"]))
                if s and s["gp"] >= 5:
                    tr.append({"player_name": pname, "manager": to_m, "from_manager": from_m, "post_trade_fp": round(s["total_fp"], 1), "gp": s["gp"], "fppg": round(s["total_fp"] / s["gp"], 2), "season": trade["season"]})
        tr.sort(key=lambda x: x["post_trade_fp"], reverse=True)
        tw_top10 = tr[:10]

    # BEST TRADE ACQUISITION BY FPPG (25 GP minimum)
    tw_fppg_top10 = []
    if trades:
        tr_fppg = []
        for trade in trades:
            for p in trade.get("players", []):
                pname, to_m, from_m = p.get("player_name", ""), p.get("to_manager", ""), p.get("from_manager", "")
                if not pname or not to_m:
                    continue
                s = pss.get((pname, to_m, trade["season"]))
                if s and s["gp"] >= 25:
                    tr_fppg.append({"player_name": pname, "manager": to_m, "from_manager": from_m, "fppg": round(s["total_fp"] / s["gp"], 2), "post_trade_fp": round(s["total_fp"], 1), "gp": s["gp"], "season": trade["season"]})
        tr_fppg.sort(key=lambda x: x["fppg"], reverse=True)
        tw_fppg_top10 = tr_fppg[:10]

    # BEST WAIVER PICKUP (all seasons)
    wp_top10 = []
    if waivers:
        wr = []
        for w in waivers:
            if w.get("is_trade", False):
                continue
            post = [g["fantasy_points"] for g in games if g["player_name"] == w["player_name"] and g["manager"] == w["manager"] and g["date"] >= w["date"] and g["fantasy_points"] > 0]
            if len(post) >= 10:
                total = sum(post)
                ws = next((g["season"] for g in games if g["player_name"] == w["player_name"] and g["manager"] == w["manager"] and g["date"] >= w["date"]), "unknown")
                wr.append({"player_name": w["player_name"], "manager": w["manager"], "fppg": round(total / len(post), 2), "total_fp": round(total, 1), "gp": len(post), "add_date": w["date"], "season": ws})
        seen = {}
        for r in wr:
            key = (r["player_name"], r["manager"], r["season"])
            if key not in seen or r["fppg"] > seen[key]["fppg"]:
                seen[key] = r
        wp_top10 = sorted(seen.values(), key=lambda x: x["fppg"], reverse=True)[:10]

    # BEST WAIVER PICKUP BY TOTAL FP (all seasons, 10 GP min)
    wp_totalfp_top10 = []
    if waivers:
        wr_tfp = []
        for w in waivers:
            if w.get("is_trade", False):
                continue
            post = [g["fantasy_points"] for g in games if g["player_name"] == w["player_name"] and g["manager"] == w["manager"] and g["date"] >= w["date"] and g["fantasy_points"] > 0]
            if len(post) >= 10:
                total = sum(post)
                ws = next((g["season"] for g in games if g["player_name"] == w["player_name"] and g["manager"] == w["manager"] and g["date"] >= w["date"]), "unknown")
                wr_tfp.append({"player_name": w["player_name"], "manager": w["manager"], "total_fp": round(total, 1), "fppg": round(total / len(post), 2), "gp": len(post), "add_date": w["date"], "season": ws})
        seen_tfp = {}
        for r in wr_tfp:
            key = (r["player_name"], r["manager"], r["season"])
            if key not in seen_tfp or r["total_fp"] > seen_tfp[key]["total_fp"]:
                seen_tfp[key] = r
        wp_totalfp_top10 = sorted(seen_tfp.values(), key=lambda x: x["total_fp"], reverse=True)[:10]

    # MOST CURSED ROSTER (renamed from most_cursed to most_il_gamedays)
    il_src = all_records if all_records else games
    il_c = defaultdict(int)
    for g in il_src:
        if g.get("slot", "") in ("IL", "IL+"):
            il_c[(g["manager"], g["season"])] += 1
    cursed = sorted([{"manager": m, "il_games": c, "season": s} for (m, s), c in il_c.items()], key=lambda x: x["il_games"], reverse=True)

    def _t(lst):
        return (lst[0] if lst else {}, lst[:10])

    result = {}
    for name, data in [
        ("best_draft_class", dc_all), ("best_draft_class_fppg", dc_fppg),
        ("biggest_draft_steal", steal_fppg), ("biggest_draft_bust", bust_fppg),
        ("biggest_draft_steal_totalfp", steal_totalfp), ("biggest_draft_bust_totalfp", bust_totalfp),
        ("trade_winner", tw_top10), ("trade_winner_fppg", tw_fppg_top10),
        ("best_waiver_pickup", wp_top10), ("best_waiver_pickup_totalfp", wp_totalfp_top10),
        ("most_cursed_roster", cursed),
    ]:
        single, top10 = _t(data)
        result[name] = single
        result[f"{name}_top10"] = top10

    for name in ["best_draft_class", "biggest_draft_steal", "biggest_draft_bust", "biggest_draft_steal_totalfp", "biggest_draft_bust_totalfp"]:
        e = result.get(name, {})
        if e:
            print(f"  {name}: {e.get('player_name', e.get('manager', '?'))} ({e.get('season', '?')})")

    return result


def compute_current_season_player_records(current_df, rookie_seasons=None) -> dict:
    print("\n--- Computing Current Season Player Records ---")
    if current_df.empty:
        return {}
    mask = (current_df["started"] == True) & (current_df["fantasy_points"].notna()) & (current_df["fantasy_points"] != 0)
    if "nba_opponent" in current_df.columns:
        mask = mask & (current_df["nba_opponent"].notna())
    started = current_df[mask].copy()
    if started.empty:
        return {}

    ps = started.groupby("player_name").agg(gp=("fantasy_points", "size"), total_fp=("fantasy_points", "sum")).reset_index()
    ps["fppg"] = round(ps["total_fp"] / ps["gp"], 2)
    bg = started.loc[started["fantasy_points"].idxmax()]
    recs = {"highest_single_game": {"player_name": str(bg["player_name"]), "manager": str(bg["manager"]), "fantasy_points": round(float(bg["fantasy_points"]), 2), "date": str(bg["date"])}}
    q = ps[ps["gp"] >= MIN_GP_FPPG]
    if not q.empty:
        bf = q.loc[q["fppg"].idxmax()]
        recs["best_season_fppg"] = {"player_name": str(bf["player_name"]), "fppg": round(float(bf["fppg"]), 2), "gp": int(bf["gp"])}
    bt = ps.loc[ps["total_fp"].idxmax()]
    recs["best_season_total_fp"] = {"player_name": str(bt["player_name"]), "total_fp": round(float(bt["total_fp"]), 1), "gp": int(bt["gp"])}
    if rookie_seasons:
        rk = started[started["player_name"].apply(
            lambda name: normalize_season(str(rookie_seasons.get(name, ""))) == CURRENT_SEASON
        )]
        if not rk.empty:
            brg = rk.loc[rk["fantasy_points"].idxmax()]
            recs["best_rookie_single_game"] = {"player_name": str(brg["player_name"]), "manager": str(brg["manager"]), "fantasy_points": round(float(brg["fantasy_points"]), 2)}
    print(f"  Computed {len(recs)} season record keys")
    return recs


def compute_total_injury_games() -> dict:
    """
    Compute Most Total Injury Games (Season) from LINEUPS data.

    Total injury games = games lost to injury (non-IL slot, 0.0 FP, has opponent)
                       + IL games (IL slot with opponent, any FP value)

    This metric requires slot + nba_opponent data which is only in LINEUPS.xlsx
    (not PLAYERLOG.xlsx). Historical seasons will be added as they are archived.

    Returns dict with most_total_injury_games and most_total_injury_games_top10.
    """
    print("\n--- Computing Total Injury Games ---")
    if not LINEUPS_FILE.exists():
        print(f"  WARNING: {LINEUPS_FILE} not found, skipping")
        return {}

    df = pd.read_excel(LINEUPS_FILE)
    if df.empty or "slot" not in df.columns:
        print("  WARNING: LINEUPS.xlsx missing or has no 'slot' column, skipping")
        return {}

    # Derive has_game
    df["has_game"] = (
        df["nba_opponent"].notna()
        & (df["nba_opponent"].astype(str).str.strip() != "")
    )

    results = []
    current_season = CURRENT_SEASON

    for manager in df["manager"].dropna().unique():
        mgr_df = df[(df["manager"] == manager) & (df["has_game"] == True)]

        # IL slot: ANY scheduled game = injury game
        il_games = len(mgr_df[mgr_df["slot"] == "IL"])

        # Non-IL slots: injury = has_game AND fantasy_points == 0.0
        non_il_games = mgr_df[mgr_df["slot"] != "IL"]
        non_il_injuries = len(non_il_games[non_il_games["fantasy_points"] == 0.0])

        total_injury = non_il_injuries + il_games
        total_scheduled = len(mgr_df)
        burden_pct = round(total_injury / total_scheduled * 100, 1) if total_scheduled > 0 else 0.0

        results.append({
            "manager": manager,
            "total_injury_games": total_injury,
            "non_il_injuries": non_il_injuries,
            "il_games": il_games,
            "total_scheduled": total_scheduled,
            "burden_pct": burden_pct,
            "season": current_season,
        })

    results.sort(key=lambda x: x["total_injury_games"], reverse=True)
    for r in results[:4]:
        print(f"  {r['manager']}: {r['total_injury_games']} total ({r['non_il_injuries']} non-IL + {r['il_games']} IL) = {r['burden_pct']}%")

    return {
        "most_total_injury_games": results[0] if results else {},
        "most_total_injury_games_top10": results[:10],
    }


def main():
    print("=" * 60)
    print("BACKFILL PLAYER RECORDS (v2)")
    print("=" * 60)

    records = load_records()
    all_time = records.setdefault("all_time", {})
    season_recs = records.setdefault("season_records", {})

    matchups = load_all_matchups()
    historical = load_historical_playerlog()
    current_df = load_current_playerlog()
    rookie_seasons = load_rookie_seasons()

    # Build combined player data first (needed for team leaderboard enrichment)
    combined = []
    if historical or not current_df.empty:
        combined = build_combined_playerlog(historical, current_df)

    if matchups:
        # Load current season data from RECORDS.json for FP/game calculation
        current_season_scores = records.get("weekly_scores", {})
        current_season_totals = records.get("manager_season_totals", {})
        for k, v in compute_team_leaderboards(
            matchups, combined or None, 
            current_season_scores=current_season_scores,
            current_season_totals=current_season_totals,
            current_season=CURRENT_SEASON
        ).items():
            all_time[k] = v

    if combined:
        for k, v in compute_player_leaderboards(combined).items():
            if v:
                all_time[k] = v

        if rookie_seasons:
            for k, v in compute_rookie_leaderboards(combined, rookie_seasons).items():
                if v:
                    all_time[k] = v

        for k, v in compute_expanded_leaderboards(combined).items():
            if v:
                all_time[k] = v

        drafts = load_all_drafts()
        trades = load_all_trades()
        waivers = load_waivers()
        all_recs = build_all_records_with_slots(historical)
        if drafts:
            for k, v in compute_draft_manager_leaderboards(combined, drafts, trades, waivers, all_recs).items():
                if v:
                    all_time[k] = v

    for k, v in compute_current_season_player_records(current_df, rookie_seasons).items():
        season_recs[k] = v

    # Total Injury Games (current season only, requires LINEUPS.xlsx slot data)
    for k, v in compute_total_injury_games().items():
        if v:
            all_time[k] = v

    # Assign franchise player badges from expanded leaderboards
    careers = all_time.setdefault("manager_careers", {})
    badges = all_time.get("franchise_badges", {})
    for mgr, badge in badges.items():
        if mgr in careers:
            careers[mgr]["franchise_player"] = badge.get("player", "")
            careers[mgr]["franchise_player_fp"] = badge.get("total_fp", 0)

    # Store titles from LEAGUEHISTORY.xlsx into manager_careers
    lh_file = PROJECT_ROOT / "data" / "LEAGUEHISTORY.xlsx"
    if lh_file.exists():
        try:
            lh = pd.read_excel(lh_file)
            careers = all_time.setdefault("manager_careers", {})
            for _, row in lh.iterrows():
                mgr = row.get("manager_name", "")
                if mgr and mgr in careers:
                    careers[mgr]["titles"] = int(row.get("titles_won", 0))
            print(f"\n  Stored titles from LEAGUEHISTORY.xlsx")
        except Exception as e:
            print(f"\n  Warning: Could not read LEAGUEHISTORY.xlsx for titles: {e}")

    # NOTE: Do NOT overwrite last_updated_week here.
    # That field is owned by records_tracker.py (called during generate_stats_report.py).
    # If we set it here based on PLAYERLOG data, records_tracker will see the week
    # as already processed and skip all current-season record updates (streaks,
    # weekly scores, H2H, blunders, etc.). Preserve whatever value is already there.
    existing_last_updated = records.get("last_updated_week", 0)
    records["last_updated_week"] = existing_last_updated
    save_records(records)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    top10_keys = sorted(k for k in all_time if k.endswith("_top10"))
    print(f"  {len(top10_keys)} top-10 leaderboards")
    for k in top10_keys:
        entries = all_time[k]
        print(f"    {k}: {len(entries) if isinstance(entries, list) else 0}")
    print("\nDone!")


if __name__ == "__main__":
    main()
