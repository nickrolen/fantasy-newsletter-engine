import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

# Add project root to path for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.data_loader import CURRENT_SEASON_LONG

PLAYERLOG_XLSX_PATH = "data/PLAYERLOG.xlsx"
LINEUPS_XLSX_PATH = "data/LINEUPS.xlsx"
LEAGUEHISTORY_XLSX_PATH = "data/LEAGUEHISTORY.xlsx"
APPLIED_WEEKS_LEDGER_PATH = "config/.leaguehistory_applied_weeks.json"


def _load_applied_weeks_ledger(base_path: Path, season: str) -> dict:
    """Load the applied-weeks ledger. Returns dict keyed by season."""
    ledger_path = base_path / APPLIED_WEEKS_LEDGER_PATH
    if not ledger_path.exists():
        return {}
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_applied_weeks_ledger(base_path: Path, ledger: dict) -> None:
    """Save the applied-weeks ledger atomically."""
    ledger_path = base_path / APPLIED_WEEKS_LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)


def _is_week_already_applied(ledger: dict, season: str, week: int) -> bool:
    """Check whether (season, week) has already been accumulated."""
    season_entry = ledger.get(season) or {}
    applied = season_entry.get("applied_weeks", [])
    return week in applied


def _record_week_applied(ledger: dict, season: str, week: int) -> dict:
    """Record (season, week) in the ledger and return the updated ledger."""
    season_entry = ledger.setdefault(season, {"applied_weeks": [], "last_applied": None})
    if week not in season_entry["applied_weeks"]:
        season_entry["applied_weeks"].append(week)
        season_entry["applied_weeks"].sort()
    season_entry["last_applied"] = datetime.now().isoformat()
    return ledger

def _parse_positions(pos_str) -> list[str]:
    """Parse comma-separated position string into a list."""
    if not pos_str or pd.isna(pos_str):
        return []
    return [p.strip() for p in str(pos_str).split(",")]


def normalize_manager(s):
    return str(s).strip()


def compute_weekly_from_playerlog(plog: pd.DataFrame, season: str, week: int):
    """Return per-manager weekly points and healthy starter games."""
    plog = plog.copy()
    plog.columns = [c.strip() for c in plog.columns]

    # Filter to this season + week
    plog = plog[(plog["season_year"] == season) & (plog["week"] == week)].copy()

    if plog.empty:
        return {}, {}

    plog["manager"] = plog["manager"].map(normalize_manager)

    # Ensure boolean
    plog["is_injured"] = plog["is_injured"].fillna(False).astype(bool)
    plog["started"] = plog["started"].fillna(False).astype(bool)

    healthy_starters = plog[(plog["started"]) & (~plog["is_injured"])].copy()
    if healthy_starters.empty:
        return {}, {}

    weekly_points = (
        healthy_starters.groupby("manager")["fantasy_points"].sum().to_dict()
    )
    healthy_games = healthy_starters.groupby("manager").size().to_dict()

    return weekly_points, healthy_games


def compute_weekly_scheduled_from_lineups(lineups: pd.DataFrame, season: str, week: int):
    """Return per-manager weekly scheduled games.

    Definition of scheduled game:
    - Row is in this season & week
    - slot is NOT IL (IL+ is included)
    - nba_opponent is non-blank (non-null, non-empty)
    - fantasy_points has a value (not NaN)
    """
    lineups = lineups.copy()
    lineups.columns = [c.strip() for c in lineups.columns]

    # Filter to this season + week ONLY
    lineups = lineups[
        (lineups["season_year"] == season) &
        (lineups["week"] == week)
    ].copy()
    if lineups.empty:
        return {}

    lineups["manager"] = lineups["manager"].map(normalize_manager)
    lineups["slot"] = lineups["slot"].astype(str).str.upper()
    
    # Ensure fantasy_points is numeric
    lineups["fantasy_points"] = pd.to_numeric(
        lineups["fantasy_points"], errors="coerce"
    )

    # Non-IL only (IL+ is included in scheduled)
    mask_non_il = ~lineups["slot"].isin(["IL"])

    # nba_opponent must be non-null and non-empty
    mask_has_opp = lineups["nba_opponent"].notna() & (
        lineups["nba_opponent"].astype(str).str.strip() != ""
    )
    
    # fantasy_points must have a value (not NaN)
    mask_has_fp = lineups["fantasy_points"].notna()

    scheduled_df = lineups[mask_non_il & mask_has_opp & mask_has_fp]
    if scheduled_df.empty:
        return {}

    scheduled = scheduled_df.groupby("manager").size().to_dict()
    return scheduled


def compute_weekly_games_lost_from_lineups(lineups: pd.DataFrame, season: str, week: int):
    """Return per-manager weekly games lost to injury.

    Definition of game lost to injury:
    - Row is in this season & week
    - slot is NOT IL (IL+ is included)
    - nba_opponent is non-blank (non-null, non-empty)
    - fantasy_points = 0.0
    """
    lineups = lineups.copy()
    lineups.columns = [c.strip() for c in lineups.columns]

    lineups = lineups[
        (lineups["season_year"] == season) &
        (lineups["week"] == week)
    ].copy()
    if lineups.empty:
        return {}

    lineups["manager"] = lineups["manager"].map(normalize_manager)
    lineups["slot"] = lineups["slot"].astype(str).str.upper()
    lineups["fantasy_points"] = pd.to_numeric(
        lineups["fantasy_points"], errors="coerce"
    )

    mask = (
        ~lineups["slot"].isin(["IL"]) &
        lineups["nba_opponent"].notna() &
        (lineups["nba_opponent"].astype(str).str.strip() != "") &
        (lineups["fantasy_points"] == 0.0)
    )

    lost_df = lineups[mask]
    if lost_df.empty:
        return {}

    return lost_df.groupby("manager").size().to_dict()


def compute_weekly_bench_games_from_lineups(lineups: pd.DataFrame, season: str, week: int):
    """Return per-manager weekly games left on bench.

    Definition of game left on bench:
    - Row is in this season & week
    - slot is BN or IL+
    - fantasy_points > 0
    """
    lineups = lineups.copy()
    lineups.columns = [c.strip() for c in lineups.columns]

    lineups = lineups[
        (lineups["season_year"] == season) &
        (lineups["week"] == week)
    ].copy()
    if lineups.empty:
        return {}

    lineups["manager"] = lineups["manager"].map(normalize_manager)
    lineups["slot"] = lineups["slot"].astype(str).str.upper()
    lineups["fantasy_points"] = pd.to_numeric(
        lineups["fantasy_points"], errors="coerce"
    )

    mask = (
        lineups["slot"].isin(["BN", "IL+"]) &
        (lineups["fantasy_points"] > 0)
    )

    bench_df = lineups[mask]
    if bench_df.empty:
        return {}

    return bench_df.groupby("manager").size().to_dict()


def compute_weekly_blunders_from_lineups(lineups: pd.DataFrame, playerlog: pd.DataFrame, season: str, week: int):
    """Return per-manager weekly blunder count (managers with any).

    One definition, modules/blunders (F2, 11-09): on each day, the most
    starters achievable from the players who played (the exact fill, so a
    blunder that needs a reshuffle counts) minus the starters who played.
    """
    from modules import blunders as bl
    lineups = lineups.copy()
    lineups.columns = [c.strip() for c in lineups.columns]
    playerlog = playerlog.copy()
    playerlog.columns = [c.strip() for c in playerlog.columns]
    lineups = lineups[(lineups["season_year"] == season) & (lineups["week"] == week)]
    playerlog = playerlog[(playerlog["season_year"] == season) & (playerlog["week"] == week)]
    return bl.counts(bl.week_from_frames(lineups, playerlog))


# =============================================================================
# H51 (FIXES item 2): the two current-season columns this script never wrote.
# record_current_season and total_moves_current_season are SET from their
# sources on every run (never added), so a re-run cannot double count. The
# April rollover (rollover_leaguehistory.py) adds the moves into
# total_moves_made_to_date and refuses when the record does not reconcile with
# RECORDS.json's regular season; both read the same functions as here.
# =============================================================================

SET_COLUMNS = ("record_current_season", "total_moves_current_season")


def current_season_values(base: Path, through_week: int) -> dict:
    """{manager: {"record_current_season": "(W-L)", "total_moves_current_season": n}}
    over weeks 1..through_week:
      - the record: every week played (regular season and post-season), from
        RECORDS.json's weekly scores and SCHEDULE.json through
        season_outcomes.build_matchups / build_standings -- the functions the
        rollover reconciles against (its "wins"/"losses"; the rollover takes
        reg_wins/reg_losses from the same rows);
      - the moves: the season's adds as the add budget counts them
        (transaction_rulings.adds_by_budget_week: rulings applied, voids
        excluded, trades excluded), budget weeks 1..through_week.
    Raises on a tie (the column and the rollover read W-L only)."""
    from modules.data_loader import CURRENT_SEASON
    from modules.season_outcomes import build_matchups, build_standings
    from modules import transaction_rulings as tr
    records = json.loads((base / "config" / "RECORDS.json").read_text(encoding="utf-8"))
    schedule = json.loads((base / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    rows = [r for r in build_matchups(CURRENT_SEASON, records, schedule) if r["week"] <= int(through_week)]
    standings = {row["manager"]: row for row in build_standings(CURRENT_SEASON, rows)} if rows else {}
    counts = tr.adds_by_budget_week(base, schedule)
    out = {}
    from modules.data_loader import MANAGERS
    for m in MANAGERS:
        st = standings.get(m, {"wins": 0, "losses": 0, "ties": 0})
        if st.get("ties"):
            raise ValueError(f"{m} has {st['ties']} tied week(s) this season: record_current_season "
                             "and the rollover read W-L only. Ask Nick how a tie is recorded.")
        moves = sum(len(by.get(m, [])) for wk, by in counts.items() if int(wk) <= int(through_week))
        out[m] = {"record_current_season": f"({int(st['wins'])}-{int(st['losses'])})",
                  "total_moves_current_season": int(moves)}
    return out


def set_current_season(ws, col_idx: dict, values: dict) -> list:
    """SET the two columns on every manager row. Returns [(manager, column,
    old, new)]. Raises when a column or a manager is missing."""
    missing = [c for c in SET_COLUMNS if c not in col_idx]
    if missing:
        raise ValueError(f"LEAGUEHISTORY.xlsx is missing required column(s): {missing}")
    seen, changes = set(), []
    for r in range(2, ws.max_row + 1):
        name = ws.cell(row=r, column=col_idx["manager_name"]).value
        if not name:
            continue
        m = normalize_manager(name)
        if m not in values:
            raise ValueError(f"LEAGUEHISTORY.xlsx row {r}: {name!r} is not a manager this season")
        seen.add(m)
        for c in SET_COLUMNS:
            cell = ws.cell(row=r, column=col_idx[c])
            changes.append((m, c, cell.value, values[m][c]))
            cell.value = values[m][c]
    if seen != set(values):
        raise ValueError(f"LEAGUEHISTORY.xlsx has no row for {sorted(set(values) - seen)}")
    return changes


def weeks_played(base: Path) -> int:
    """The last week with a result for every matchup in RECORDS.json."""
    from modules.data_loader import CURRENT_SEASON
    from modules.season_outcomes import build_matchups
    records = json.loads((base / "config" / "RECORDS.json").read_text(encoding="utf-8"))
    schedule = json.loads((base / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    rows = build_matchups(CURRENT_SEASON, records, schedule)
    done = 0
    for wk in sorted(schedule.get("weeks", []), key=lambda w: int(w["week"])):
        n = sum(1 for r in rows if r["week"] == int(wk["week"]))
        if n and n == len(wk.get("matchups", [])):
            done = int(wk["week"])
        else:
            break
    return done


def fill_current_season(base: Path, dry_run: bool, echo=print) -> dict:
    """--fill-current-season: set the two columns for the weeks already played,
    touching nothing else (no other column, no applied-weeks ledger)."""
    through = weeks_played(base)
    values = current_season_values(base, through)
    path = base / LEAGUEHISTORY_XLSX_PATH
    wb = load_workbook(path, data_only=False)
    ws = wb.active
    col_idx = {name: i + 1 for i, name in enumerate(cell.value for cell in ws[1])}
    changes = set_current_season(ws, col_idx, values)
    echo(f"current-season columns through week {through} (the weeks played):")
    for m, c, old, new in changes:
        echo(f"  {m:8} {c:28} {old!s:>8} -> {new}")
    if dry_run:
        echo("[DRY-RUN] nothing written.")
    else:
        wb.save(path)
        echo(f"{LEAGUEHISTORY_XLSX_PATH} updated (those two columns only).")
    return {"through": through, "values": values, "changes": changes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--season",
        default=CURRENT_SEASON_LONG,
        help="Season label as stored in season_year column (default: 2025-2026).",
    )
    parser.add_argument(
        "--week",
        type=int,
        help="Fantasy week number to add into LEAGUEHISTORY.",
    )
    parser.add_argument(
        "--fill-current-season", action="store_true",
        help="Set record_current_season and total_moves_current_season for the weeks "
             "already played, touching nothing else (H51; once, by hand).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="With --fill-current-season: print what it would write, write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-apply a week even if the ledger says it has already been applied. "
             "Use only after a correction (otherwise this causes double-counting).",
    )
    args = parser.parse_args()

    base = Path(".")
    if args.fill_current_season:
        if args.week is not None:
            parser.error("--fill-current-season sets the weeks played; it takes no --week")
        fill_current_season(base, args.dry_run)
        return
    if args.week is None:
        parser.error("--week N is required (or --fill-current-season)")
    if args.dry_run:
        parser.error("--dry-run goes with --fill-current-season")

    # --- Applied-weeks ledger guard (prevents double-counting on re-run) ---
    ledger = _load_applied_weeks_ledger(base, args.season)
    if _is_week_already_applied(ledger, args.season, args.week) and not args.force:
        print(
            f"WARNING: Week {args.week} has already been applied to "
            f"LEAGUEHISTORY.xlsx for season {args.season}. Skipping to prevent "
            f"double-counting."
        )
        print(
            "To force re-application (e.g., after a correction), use --force."
        )
        # H51: the two SET columns are idempotent: refresh them anyway
        wb = load_workbook(base / LEAGUEHISTORY_XLSX_PATH, data_only=False)
        ws = wb.active
        col_idx = {name: i + 1 for i, name in enumerate(cell.value for cell in ws[1])}
        set_current_season(ws, col_idx, current_season_values(base, args.week))
        wb.save(base / LEAGUEHISTORY_XLSX_PATH)
        print("record_current_season and total_moves_current_season set (idempotent).")
        return
    if _is_week_already_applied(ledger, args.season, args.week) and args.force:
        print(
            f"--force: Week {args.week} previously applied; re-accumulating "
            f"per user override."
        )

    # Load source data
    from modules.transaction_rulings import apply_effective_dates
    plog = apply_effective_dates(pd.read_excel(base / PLAYERLOG_XLSX_PATH), base, "playerlog")
    lineups = apply_effective_dates(pd.read_excel(base / LINEUPS_XLSX_PATH), base, "lineups")

    weekly_points, healthy_games = compute_weekly_from_playerlog(
        plog, args.season, args.week
    )
    scheduled_games = compute_weekly_scheduled_from_lineups(
        lineups, args.season, args.week
    )
    games_lost = compute_weekly_games_lost_from_lineups(
        lineups, args.season, args.week
    )
    bench_games = compute_weekly_bench_games_from_lineups(
        lineups, args.season, args.week
    )
    blunders = compute_weekly_blunders_from_lineups(
        lineups, plog, args.season, args.week
    )

    print(f"Week {args.week} summary (season {args.season}):")
    managers = sorted(
        set(list(weekly_points.keys()) + list(healthy_games.keys()) + list(scheduled_games.keys()))
    )
    for m in managers:
        print(
            f"  {m}: "
            f"{weekly_points.get(m, 0):.1f} FP, "
            f"{scheduled_games.get(m, 0)} scheduled, "
            f"{healthy_games.get(m, 0)} healthy, "
            f"{games_lost.get(m, 0)} lost, "
            f"{bench_games.get(m, 0)} bench, "
            f"{blunders.get(m, 0)} blunders"
        )

    # Load LEAGUEHISTORY with openpyxl to preserve formulas
    wb = load_workbook(base / LEAGUEHISTORY_XLSX_PATH, data_only=False)
    ws = wb.active  # assume first sheet

    # Header / column indices
    header = [cell.value for cell in ws[1]]
    col_idx = {name: i + 1 for i, name in enumerate(header)}

    required_cols = [
        "manager_name",
        "total_points_scored_to_date",
        "total_points_current_season",
        "total_scheduled_games_current_season",
        "total_healthy_starter_games_current_season",
        "total_games_lost_current_season",
        "total_games_left_on_bench_current_season",
        "total_blunders_current_season",
    ]
    for col in required_cols:
        if col not in col_idx:
            raise ValueError(f"LEAGUEHISTORY.xlsx is missing required column: {col}")

    def get_number(row, col_name):
        c = col_idx[col_name]
        val = ws.cell(row=row, column=c).value
        if val is None or val == "":
            return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    # Update each manager row
    for r in range(2, ws.max_row + 1):
        name_cell = ws.cell(row=r, column=col_idx["manager_name"])
        if not name_cell.value:
            continue
        manager = normalize_manager(name_cell.value)

        add_fp = weekly_points.get(manager, 0.0)
        add_sched = scheduled_games.get(manager, 0)
        add_healthy = healthy_games.get(manager, 0)
        add_lost = games_lost.get(manager, 0)
        add_bench = bench_games.get(manager, 0)
        add_blunders = blunders.get(manager, 0)

        if add_fp == 0 and add_sched == 0 and add_healthy == 0:
            continue

        cur_total_pts = get_number(r, "total_points_scored_to_date")
        ws.cell(row=r, column=col_idx["total_points_scored_to_date"], value=cur_total_pts + add_fp)

        cur_season_pts = get_number(r, "total_points_current_season")
        ws.cell(row=r, column=col_idx["total_points_current_season"], value=cur_season_pts + add_fp)

        cur_sched = get_number(r, "total_scheduled_games_current_season")
        ws.cell(row=r, column=col_idx["total_scheduled_games_current_season"], value=cur_sched + add_sched)

        cur_healthy = get_number(r, "total_healthy_starter_games_current_season")
        ws.cell(row=r, column=col_idx["total_healthy_starter_games_current_season"], value=cur_healthy + add_healthy)

        cur_lost = get_number(r, "total_games_lost_current_season")
        ws.cell(row=r, column=col_idx["total_games_lost_current_season"], value=cur_lost + add_lost)

        cur_bench = get_number(r, "total_games_left_on_bench_current_season")
        ws.cell(row=r, column=col_idx["total_games_left_on_bench_current_season"], value=cur_bench + add_bench)

        cur_blunders = get_number(r, "total_blunders_current_season")
        ws.cell(row=r, column=col_idx["total_blunders_current_season"], value=cur_blunders + add_blunders)

    # H51: SET, never added (a re-run cannot double count)
    for m, c, old, new in set_current_season(ws, col_idx, current_season_values(base, args.week)):
        print(f"  {m}: {c} {old} -> {new}")
    wb.save(base / LEAGUEHISTORY_XLSX_PATH)
    print("LEAGUEHISTORY.xlsx updated.")

    ledger = _record_week_applied(ledger, args.season, args.week)
    _save_applied_weeks_ledger(base, ledger)
    print(f"Recorded week {args.week} ({args.season}) in {APPLIED_WEEKS_LEDGER_PATH}.")


if __name__ == "__main__":
    main()
