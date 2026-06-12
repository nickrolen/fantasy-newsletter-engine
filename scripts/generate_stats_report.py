#!/usr/bin/env python3
"""
generate_stats_report.py

Main entry point for weekly newsletter stats report generation.

Usage:
    python generate_stats_report.py --week 11
    python generate_stats_report.py --week 11 --fast  # Skip simulations
    python generate_stats_report.py --week 11 --title-sims 10000 --betting-sims 5000
"""

# Suppress pandas FutureWarnings and other noisy warnings
import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='Could not infer format')

import argparse
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.data_loader import load_all_data, save_records
from modules.weekly_stats import load_waiver_adds
from modules.report_builder import build_stats_report, save_stats_report


def main():
    parser = argparse.ArgumentParser(
        description="Generate weekly stats report for fantasy basketball newsletter"
    )
    parser.add_argument(
        "--week",
        type=int,
        required=True,
        help="Fantasy week number to generate report for",
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default=".",
        help="Base path to project directory (default: current directory)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip Monte Carlo simulations for faster generation",
    )
    parser.add_argument(
        "--title-sims",
        type=int,
        default=10000,
        help="Number of title odds simulations (default: 10000)",
    )
    parser.add_argument(
        "--betting-sims",
        type=int,
        default=5000,
        help="Number of betting line simulations (default: 5000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: output/stats_report_weekN.json)",
    )
    parser.add_argument(
        "--no-save-records",
        action="store_true",
        help="Skip saving updated RECORDS.json (records are saved by default)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test run - don't save any files (stats report or RECORDS.json)",
    )
    parser.add_argument(
        "--regenerate-rosters",
        action="store_true",
        help="Regenerate config/ROSTERS.json from LINEUPS before running (overwrites any manual edits)",
    )
    parser.add_argument(
        "--ignore-rosters-config",
        action="store_true",
        help="Ignore config/ROSTERS.json and use LINEUPS directly for roster data",
    )
    parser.add_argument(
        "--fetch-injuries",
        action="store_true",
        help="Fetch current injury statuses from Yahoo API for more accurate betting lines",
    )
    parser.add_argument(
        "--no-fetch-injuries",
        action="store_true",
        help="Skip fetching injury statuses even if oauth2.json exists",
    )
    parser.add_argument(
        "--no-freshness",
        action="store_true",
        help="Disable freshness tracking (allow repetitive content)",
    )
    parser.add_argument(
        "--repro",
        action="store_true",
        help="Repro run for the given week: use pre-week RECENT_CONTENT snapshot, do not save freshness, "
             "skip Yahoo injury fetch, and freeze looking_ahead from the existing stats report",
    )
    
    args = parser.parse_args()
    
    # --dry-run implies --no-save-records
    if args.dry_run:
        args.no_save_records = True
    
    base_path = Path(args.base_path)
    week = args.week

    # Repro/snapshot paths
    snapshots_dir = base_path / "config" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    freshness_live_file = base_path / "config" / "RECENT_CONTENT.json"
    freshness_pre_file = snapshots_dir / f"RECENT_CONTENT_pre_week{week}.json"
    freshness_post_file = snapshots_dir / f"RECENT_CONTENT_post_week{week}.json"

    # Cache for freezing betting lines / previews (Option A: freeze entire looking_ahead block)
    looking_ahead_cache_file = base_path / "output" / f"looking_ahead_week{week}.json"

    # Prior published report path (used during repro to freeze looking_ahead)
    prior_report_path = base_path / f"output/stats_report_week{week}.json"

    
    print("=" * 60)
    print(f"Fantasy Basketball Newsletter - Stats Report Generator")
    print(f"Week {week}")
    if args.dry_run:
        print("*** DRY RUN - No files will be saved ***")
    print("=" * 60)
    print()
    
    # Load data
    print(f"Loading data from: {base_path.absolute()}")
    start_time = datetime.now()
    
    try:
        # Pass the target week explicitly so the report is built "as of" the
        # requested week. Without this, current_week auto-detects the latest
        # week present in the data -- which silently breaks regenerating an
        # earlier week once later weeks are loaded (e.g. a Week 22 report would
        # read as post_finals because Week 23 data exists). week is None-safe:
        # load_all_data falls back to auto-detect when current_week is None.
        data = load_all_data(base_path, current_week=week)
    except Exception as e:
        print(f"ERROR loading data: {e}")
        sys.exit(1)
    
    print(f"  PLAYERLOG: {len(data.playerlog)} rows")
    print(f"  LINEUPS: {len(data.lineups)} rows")
    print(f"  PLAYERLIST: {len(data.playerlist)} players")
    print(f"  Current week in data: {data.current_week}")
    print()
    
    # Handle roster config
    from modules.projections import ROSTERS_FILE, generate_rosters_file, load_rosters_from_config
    
    if args.regenerate_rosters:
        print("Regenerating config/ROSTERS.json from LINEUPS...")
        generate_rosters_file(data)
        print()
    
    if args.ignore_rosters_config:
        print("Ignoring config/ROSTERS.json - using LINEUPS for rosters")
        # Temporarily rename the file if it exists.
        # Self-healing: if a stale .bak survives from a previous crashed run,
        # restore it FIRST -- otherwise the rename below would fail on Windows
        # (target exists) and the live roster file could be lost permanently.
        import os
        _bak = str(ROSTERS_FILE) + ".bak"
        if Path(_bak).exists():
            os.replace(_bak, ROSTERS_FILE)
            print(f"  (Recovered stale {_bak} from a previous interrupted run)")
        if ROSTERS_FILE.exists():
            os.rename(ROSTERS_FILE, _bak)
            print(f"  (Temporarily moved {ROSTERS_FILE} to {ROSTERS_FILE}.bak)")
    else:
        # Check if ROSTERS.json exists and report
        config_rosters = load_rosters_from_config()
        if config_rosters:
            print(f"Using rosters from: {ROSTERS_FILE}")
            print("  (Edit this file to reflect waiver moves before running)")
            for mgr, players in config_rosters.items():
                print(f"    {mgr}: {len(players)} players")
        else:
            print("No config/ROSTERS.json found - using LINEUPS for rosters")
            print("  (Run with --regenerate-rosters to create editable roster file)")
    print()
    
    # Load waivers
    waiver_file = base_path / f"data/waivers_week{week}.txt"
    if waiver_file.exists():
        waivers = load_waiver_adds(str(waiver_file))
        print(f"Loaded waivers from: {waiver_file}")
        for manager, players in waivers.items():
            if players:
                print(f"  {manager}: {', '.join(players)}")
    else:
        print(f"No waiver file found at: {waiver_file}")
        waivers = {}
    print()
    
    # Fetch injury statuses from Yahoo API
    injury_statuses = {}
    oauth_file = base_path / "oauth2.json"
    
    # Determine if we should fetch injuries
    # Default: fetch if oauth file exists and not in fast mode, unless --no-fetch-injuries
    should_fetch = (
        (not args.repro) and (
            args.fetch_injuries or
            (oauth_file.exists() and not args.fast and not args.no_fetch_injuries)
        )
    )

    if args.repro:
        print("Repro mode: skipping injury status fetch and freezing looking_ahead")
        print()

    
    if should_fetch:
        print("Fetching current injury statuses from Yahoo API...")
        try:
            from modules.fetch_injury_statuses import fetch_injury_statuses_safe
            injury_statuses = fetch_injury_statuses_safe(
                oauth_file=str(oauth_file),
                verbose=True
            )
            if injury_statuses:
                non_healthy = {k: v for k, v in injury_statuses.items() if v != "HEALTHY"}
                print(f"  Loaded {len(injury_statuses)} player statuses ({len(non_healthy)} non-healthy)")
            else:
                print("  No injury statuses fetched (API unavailable or failed)")
        except ImportError:
            print("  Warning: fetch_injury_statuses module not found")
        except Exception as e:
            print(f"  Warning: Failed to fetch injury statuses: {e}")
        print()
    elif args.no_fetch_injuries:
        print("Skipping injury status fetch (--no-fetch-injuries)")
        print()
    elif not oauth_file.exists():
        print("Skipping injury status fetch (no oauth2.json found)")
        print("  (Run with --fetch-injuries after setting up Yahoo OAuth to enable)")
        print()
    
    # Load freshness tracker for content deduplication
    freshness_tracker = None
    if not args.no_freshness:
        print("Loading content freshness tracker...")
        try:
            from modules.content_freshness import FreshnessTracker

            # Ensure we have a pre-week snapshot saved (only create it if missing)
            if not freshness_pre_file.exists():
                if freshness_live_file.exists():
                    shutil.copy2(freshness_live_file, freshness_pre_file)
                    print(f"  Saved pre-week freshness snapshot: {freshness_pre_file}")
                else:
                    print(f"  Warning: live freshness file not found at {freshness_live_file}")
                    print("  Starting fresh (no RECENT_CONTENT.json found)")

            # Choose freshness input: repro uses the pre-week snapshot if available
            if args.repro and freshness_pre_file.exists():
                freshness_in = freshness_pre_file
                print(f"  Repro mode: using freshness snapshot: {freshness_in}")
            else:
                freshness_in = freshness_live_file
                print(f"  Using freshness file: {freshness_in}")

            freshness_tracker = FreshnessTracker.load(freshness_in)
            freshness_tracker.set_current_week(week)

            if freshness_tracker.fun_facts:
                print(f"  Loaded {len(freshness_tracker.fun_facts)} tracked facts from previous weeks")
            else:
                print("  Starting fresh (no previous content tracked)")

        except ImportError:
            print("  Warning: content_freshness module not found, skipping freshness tracking")
        except Exception as e:
            print(f"  Warning: Failed to load freshness tracker: {e}")
        print()
    else:
        print("Freshness tracking disabled (--no-freshness)")
        print()

    
    # Build report
    print("Building stats report...")
    if args.fast:
        print("  (Fast mode - skipping simulations)")
        run_sims = False
    else:
        print(f"  Title odds simulations: {args.title_sims}")
        print(f"  Betting line simulations: {args.betting_sims}")
        run_sims = True
    
    try:
        report = build_stats_report(
            data,
            week,
            waivers,
            run_simulations=run_sims,
            num_title_sims=args.title_sims,
            num_betting_sims=args.betting_sims,
            seed=args.seed,
            injury_statuses=injury_statuses,
            freshness_tracker=freshness_tracker,
        )
    except Exception as e:
        print(f"ERROR building report: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    # -------------------------------------------------------------------------
    # Step 6: Repro mode -> freeze entire looking_ahead block (Option A)
    # -------------------------------------------------------------------------
    if args.repro:
        frozen_looking_ahead = None

        # Prefer freezing from the prior published stats report for the same week
        if prior_report_path.exists():
            try:
                with open(prior_report_path, "r", encoding="utf-8") as f:
                    prior_report = json.load(f)
                frozen_looking_ahead = prior_report.get("looking_ahead")
                print(f"Repro mode: froze looking_ahead from {prior_report_path}")
            except Exception as e:
                print(f"Warning: could not load prior report for looking_ahead freeze: {e}")

        # Fallback: freeze from a cached looking_ahead file if present
        if frozen_looking_ahead is None and looking_ahead_cache_file.exists():
            try:
                with open(looking_ahead_cache_file, "r", encoding="utf-8") as f:
                    frozen_looking_ahead = json.load(f)
                print(f"Repro mode: froze looking_ahead from {looking_ahead_cache_file}")
            except Exception as e:
                print(f"Warning: could not load looking_ahead cache: {e}")

        if frozen_looking_ahead is not None:
            report["looking_ahead"] = frozen_looking_ahead
        else:
            print("Warning: Repro mode requested, but no freeze source found for looking_ahead")
        print()

    # -------------------------------------------------------------------------
    # Step 7: Save freshness tracker (normal runs only; repro should not mutate continuity state)
    # -------------------------------------------------------------------------
    if freshness_tracker is not None and not args.dry_run and (not args.repro):
        try:
            freshness_tracker.cleanup_old_entries(week, max_age_weeks=10)
            freshness_tracker.save()
            print(f"Saved freshness tracker to: {freshness_tracker.filepath}")

            # Also snapshot post-week freshness state for auditing / future repro runs
            try:
                shutil.copy2(freshness_tracker.filepath, freshness_post_file)
                print(f"Saved post-week freshness snapshot: {freshness_post_file}")
            except Exception as e:
                print(f"Warning: Failed to write post-week freshness snapshot: {e}")

        except Exception as e:
            print(f"Warning: Failed to save freshness tracker: {e}")
    elif args.repro and freshness_tracker is not None and not args.dry_run:
        print("Repro mode: not saving freshness tracker (RECENT_CONTENT stays unchanged)")
    
    # Save report
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = base_path / f"output/stats_report_week{week}.json"
    
    if args.dry_run:
        print(f"\n[DRY RUN] Would save stats report to: {output_path}")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_stats_report(report, output_path)
        if not args.repro:
            try:
                looking_ahead_cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(looking_ahead_cache_file, "w", encoding="utf-8") as f:
                    json.dump(report.get("looking_ahead", {}), f, indent=2)
                print(f"Saved looking_ahead cache to: {looking_ahead_cache_file}")
            except Exception as e:
                print(f"Warning: Failed to save looking_ahead cache: {e}")
                
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print()
    print("=" * 60)
    print(f"Report generated successfully!")
    if not args.dry_run:
        print(f"  Output: {output_path}")
    else:
        print(f"  Output: [DRY RUN - not saved]")
    print(f"  Time: {elapsed:.1f} seconds")
    print("=" * 60)
    print()
    
    # Print summary
    print("REPORT SUMMARY")
    print("-" * 40)
    
    # Matchup results
    print("\nMatchup Results:")
    for matchup in report["matchup_summaries"]:
        winner = matchup["winner"]
        loser = matchup["manager_a"] if winner == matchup["manager_b"] else matchup["manager_b"]
        print(f"  {winner} def. {loser}: {matchup['score_a']:.1f} - {matchup['score_b']:.1f}")
    
    # Power rankings / Playoff odds
    if report.get("is_playoff_week") and report.get("playoff_odds"):
        po = report["playoff_odds"]
        print(f"\nPLAYOFF MODE ({po['playoff_round']})")
        print("\nSemifinal Matchups:")
        for semi in po.get("semi_matchups", []):
            print(f"  #{semi['seed_a']} {semi['manager_a']} ({semi['win_prob_a']:.1f}%) vs "
                  f"#{semi['seed_b']} {semi['manager_b']} ({semi['win_prob_b']:.1f}%)")
        print("\nChampionship Odds:")
        if report.get("power_rankings"):
            for pr in report["power_rankings"]:
                print(f"  {pr['rank']}. {pr['manager']} ({pr['record']}) - {pr['title_odds']:.1f}% championship")
    elif report.get("power_rankings"):
        print("\nPower Rankings:")
        for pr in report["power_rankings"]:
            print(f"  {pr['rank']}. {pr['manager']} ({pr['record']}) - {pr['title_odds']:.1f}% title odds")
    
    # Player of the week
    pow_data = report.get("player_of_week")
    if pow_data and pow_data.get("winner"):
        winner = pow_data["winner"]
        print(f"\nPlayer of the Week: {winner['player_name']} ({winner['manager']})")
        print(f"  {winner['total_fp']:.1f} FP on {winner['games']} games ({winner['fppg']:.1f} FPPG)")
    
    # Fun facts
    print("\nFun Facts:")
    for fact in report.get("fun_facts", [])[:5]:
        print(f"  * {fact['text']}")
    
    # Save records (default behavior; skipped by --no-save-records, --dry-run,
    # or --repro). Repro mode must be a pure read-only operation so re-running
    # an older week never alters RECORDS.json (standings, career stats, etc.).
    if args.repro:
        print("\n[repro mode] Skipping RECORDS.json save (repro is read-only)")
    elif not args.no_save_records:
        records_path = base_path / "config/RECORDS.json"
        
        # Update manager_season_totals from the report
        if "manager_season_totals" not in data.records:
            data.records["manager_season_totals"] = {}
        
        # Set wins/losses from current standings (which are already updated)
        for standing in report.get("current_standings", []):
            manager = standing["manager"]
            # Records are "W-L" (ties are not counted as wins or losses per the
            # project-wide tie convention in data_loader.py, but a "W-L-T" string
            # from any source must not crash the parser).
            record_parts = standing["record"].strip("()").split("-")
            wins = int(record_parts[0])
            losses = int(record_parts[1])
            # record_parts[2] (ties), if present, is intentionally ignored
            
            if manager not in data.records["manager_season_totals"]:
                data.records["manager_season_totals"][manager] = {"wins": 0, "losses": 0, "total_points": 0.0}
            
            data.records["manager_season_totals"][manager]["wins"] = wins
            data.records["manager_season_totals"][manager]["losses"] = losses
        
        # Update total_points from season_fppg_stats (which has accurate totals)
        season_stats = report.get("season_fppg_stats", {})
        for manager, stats in season_stats.items():
            if manager not in data.records["manager_season_totals"]:
                data.records["manager_season_totals"][manager] = {"wins": 0, "losses": 0, "total_points": 0.0}
            data.records["manager_season_totals"][manager]["total_points"] = stats.get("total_fp", 0.0)
        
        save_records(data.records, records_path)
        print(f"\nUpdated RECORDS.json saved to: {records_path}")
    elif args.dry_run:
        print(f"\n[DRY RUN] Would update RECORDS.json")
    
    # Restore rosters file if we moved it
    if args.ignore_rosters_config:
        backup_path = str(ROSTERS_FILE) + ".bak"
        if Path(backup_path).exists():
            import os
            os.replace(backup_path, ROSTERS_FILE)
            print(f"Restored {ROSTERS_FILE}")

    print()
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
