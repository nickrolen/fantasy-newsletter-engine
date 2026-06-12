#!/usr/bin/env python3
"""
generate_rosters.py

Generate config/ROSTERS.json from LINEUPS data as a starting point.
Run this before generate_stats_report.py, then manually edit ROSTERS.json
to reflect any waiver moves that happened after the last game day.

Usage:
    python scripts/generate_rosters.py
    python scripts/generate_rosters.py --week 12  # Use specific week instead of most recent
"""

import argparse
import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.data_loader import load_all_data, MANAGERS


def main():
    parser = argparse.ArgumentParser(
        description="Generate config/ROSTERS.json from LINEUPS data"
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default=".",
        help="Base path to project directory (default: current directory)",
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Use lineups from specific week (default: most recent week)",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Show differences from existing ROSTERS.json (if it exists)",
    )
    
    args = parser.parse_args()
    base_path = Path(args.base_path)
    
    # Load data
    print("Loading LINEUPS data...")
    data = load_all_data(base_path)
    
    # Determine which week to use
    if args.week:
        target_week = args.week
    else:
        target_week = int(data.lineups['week'].max())
    
    print(f"Using lineups from week {target_week}")
    
    # Filter to target week
    week_lineups = data.lineups[data.lineups['week'] == target_week]
    
    if week_lineups.empty:
        print(f"ERROR: No lineups found for week {target_week}")
        sys.exit(1)
    
    # Build rosters
    new_rosters = {}
    for manager in MANAGERS:
        players = week_lineups[
            week_lineups['manager'] == manager
        ]['player_name'].unique().tolist()
        new_rosters[manager] = sorted(players)
    
    # Check for existing file and show diff if requested
    rosters_file = base_path / "config" / "ROSTERS.json"
    
    if args.show_diff and rosters_file.exists():
        with open(rosters_file) as f:
            old_data = json.load(f)
        old_rosters = old_data.get("rosters", {})
        
        print("\n=== CHANGES FROM EXISTING ROSTERS.json ===")
        has_changes = False
        
        for manager in MANAGERS:
            old_set = set(old_rosters.get(manager, []))
            new_set = set(new_rosters[manager])
            
            added = new_set - old_set
            removed = old_set - new_set
            
            if added or removed:
                has_changes = True
                print(f"\n{manager}:")
                for player in sorted(added):
                    print(f"  + {player}")
                for player in sorted(removed):
                    print(f"  - {player}")
        
        if not has_changes:
            print("  No changes detected")
        print()
    
    # Build output
    output = {
        "_comment": f"Edit this file to reflect current rosters before running simulations. Auto-generated from LINEUPS week {target_week}",
        "_generated_from_week": target_week,
        "rosters": new_rosters
    }
    
    # Save
    rosters_file.parent.mkdir(parents=True, exist_ok=True)
    with open(rosters_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Generated: {rosters_file}")
    print()
    for manager, players in new_rosters.items():
        print(f"  {manager}: {len(players)} players")
    
    print()
    print("Next steps:")
    print("  1. Edit config/ROSTERS.json to add any waiver pickups")
    print("  2. Edit config/ROSTERS.json to remove any dropped players")
    print("  3. Run: python scripts/generate_stats_report.py --week <N>")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
