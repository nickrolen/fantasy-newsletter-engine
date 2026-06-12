#!/usr/bin/env python3
"""
generate_player_card_preview.py

Generates a standalone HTML preview of the player card modal,
populated with full historical data from HISTORICAL_PLAYERLOG.json.

Usage:
    cd <project_root>
    python scripts/generate_player_card_preview.py

    # Opens automatically in your default browser

Output:
    output/player_card_preview.html
"""

import json
import sys
import webbrowser
from pathlib import Path

# Path setup
SCRIPT_DIR = Path(__file__).resolve().parent
if SCRIPT_DIR.name == "scripts":
    PROJECT_ROOT = SCRIPT_DIR.parent
else:
    PROJECT_ROOT = SCRIPT_DIR

# Add project root to path for imports
sys.path.insert(0, str(PROJECT_ROOT))

from modules.player_card_builder import build_player_cards
from modules.player_card_modal import get_player_card_css, get_player_card_js, embed_player_card_data
from modules.data_loader import MANAGER_COLORS, LEAGUE_NAME_SHORT, SEASON_NUMBER

# Directories
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
HISTORICAL_DIR = DATA_DIR / "historical"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_FILE = OUTPUT_DIR / "player_card_preview.html"

TIER_SORT = {
    "Lock": 0, "Strong Hold": 1, "Stash": 2, "Sell High": 3,
    "On the Bubble": 4, "Dynasty Stash": 5, "Drop": 6,
}


def main():
    print("=" * 60)
    print("PLAYER CARD PREVIEW GENERATOR")
    print("=" * 60)
    print()

    # Find latest stats report
    stats_reports = sorted(OUTPUT_DIR.glob("stats_report_week*.json"), reverse=True)
    if not stats_reports:
        print("ERROR: No stats_report_weekN.json found in output/")
        sys.exit(1)

    sr_path = stats_reports[0]
    print(f"Using stats report: {sr_path.name}")

    with open(sr_path) as f:
        sr = json.load(f)

    kw_players = sr.get("keeper_watch", {}).get("players", [])
    if not kw_players:
        print("ERROR: No keeper_watch players found in stats report")
        sys.exit(1)

    print(f"Found {len(kw_players)} keeper watch players")
    print()

    # Build cards with full historical data
    cards = build_player_cards(
        keeper_watch_players=kw_players,
        data_dir=DATA_DIR,
        config_dir=CONFIG_DIR,
        historical_dir=HISTORICAL_DIR,
        season_performers=sr.get("season_performers"),
    )

    print()
    print(f"Built {len(cards)} player cards")

    # Sort cards: by tier, then by FPPG within tier
    cards.sort(key=lambda c: (
        TIER_SORT.get(c.get("keeper_tier", "Drop"), 9),
        -(c.get("current_season", {}).get("fppg", 0))
    ))

    # Build HTML
    html = build_preview_html(cards)

    # Write
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    file_size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"\nPreview saved: {OUTPUT_FILE}")
    print(f"File size: {file_size_kb:.0f} KB")
    print(f"\nOpening in browser...")
    webbrowser.open(OUTPUT_FILE.resolve().as_uri())
    print()

    # Print some stats
    from collections import Counter
    archetypes = Counter(c["archetype"] for c in cards)
    print("Archetype distribution:")
    for arch, count in archetypes.most_common():
        print(f"  {arch}: {count}")

    # Show players with most record book entries
    print()
    print("Most Record Book appearances:")
    by_records = sorted(cards, key=lambda c: -len(c.get("record_book", [])))[:10]
    for c in by_records:
        rb = c.get("record_book", [])
        firsts = sum(1 for r in rb if r["rank"] == 1)
        print(f"  {c['player_name']:25s}: {len(rb):2d} entries ({firsts} #1s)")


def build_preview_html(cards: list[dict]) -> str:
    """Build the full standalone preview HTML."""

    # Group cards by tier for the chip grid
    tiers = {}
    for c in cards:
        tier = c.get("keeper_tier", "Drop")
        if tier not in tiers:
            tiers[tier] = []
        tiers[tier].append(c)

    tier_order = ["Lock", "Strong Hold", "Stash", "Sell High", "On the Bubble", "Dynasty Stash"]
    tier_colors = {
        "Lock": "#2e7d32", "Strong Hold": "#1F4E79", "Stash": "#7b1fa2",
        "Sell High": "#ffa726", "On the Bubble": "#757575", "Dynasty Stash": "#0288d1",
    }

    # Rankings are already computed by build_player_cards

    # Build chip grid HTML
    chips_html = ""
    for tier in tier_order:
        tier_cards = tiers.get(tier, [])
        if not tier_cards:
            continue
        tier_color = tier_colors.get(tier, "#666")
        chips_html += f'<div class="prev-tier-header" style="border-left: 4px solid {tier_color};">{tier} ({len(tier_cards)})</div>\n'
        chips_html += '<div class="preview-grid">\n'
        for c in tier_cards:
            color = MANAGER_COLORS.get(c["manager"], "#666")
            fppg = c.get("current_season", {}).get("fppg", 0)
            gp = c.get("current_season", {}).get("gp", 0)
            career = c.get("career", {})
            career_szns = career.get("seasons_played", 0)
            career_fppg = career.get("career_fppg", 0)
            name_js = c["player_name"].replace("\\", "\\\\").replace("'", "\\x27").replace('"', '\\"')
            rank = c.get("overall_rank", "?")
            rank_badge = f'<span class="chip-rank">Avg. Rank: #{rank}</span>'

            chips_html += f"""<div class="preview-chip" style="border-left-color:{color}" onclick="pcOpen('{name_js}')">
  <div class="chip-row1"><span class="chip-name">{c['player_name']}</span>{rank_badge}</div>
  <div class="chip-sub">{c['nba_team']} &middot; {c['pos_group']} &middot; {c['age']}y &middot; {c['manager']}</div>
  <div class="chip-stats">
    <span class="chip-fppg">{fppg:.1f} FPPG</span>
    <span class="chip-gp">{gp} GP</span>
    <span class="chip-career">{career_szns}yr / {career_fppg:.1f}</span>
  </div>
  <div class="chip-arch">{c['archetype']}</div>
</div>
"""
        chips_html += "</div>\n"

    # Manager filter buttons
    filter_html = '<div class="prev-filters">\n'
    filter_html += '<button class="prev-filter-btn prev-filter-active" onclick="prevFilter(\'all\')">All</button>\n'
    for mgr, color in MANAGER_COLORS.items():
        filter_html += f'<button class="prev-filter-btn" data-mgr="{mgr}" style="border-bottom: 3px solid {color};" onclick="prevFilter(\'{mgr}\')">{mgr}</button>\n'
    filter_html += '</div>\n'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Player Cards - {LEAGUE_NAME_SHORT}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #121220; color: #e0e0e0;
  padding: 16px 12px;
  -webkit-font-smoothing: antialiased;
}}

/* --- Page Header --- */
.prev-header {{
  text-align: center;
  padding: 16px 0 12px;
  margin-bottom: 12px;
  border-bottom: 2px solid #C9A227;
}}
.prev-title {{
  font-size: 1.3rem;
  font-weight: 800;
  color: #5b9bd5;
  letter-spacing: -0.5px;
}}
.prev-subtitle {{
  font-size: 0.7rem;
  color: #808080;
  font-style: italic;
  margin-top: 2px;
}}
.prev-count {{
  font-size: 0.62rem;
  color: #606060;
  margin-top: 6px;
}}

/* --- Manager Filters --- */
.prev-filters {{
  display: flex;
  justify-content: center;
  gap: 4px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}}
.prev-filter-btn {{
  background: rgba(255,255,255,0.06);
  border: none;
  border-bottom: 3px solid transparent;
  color: #a0a0a0;
  padding: 6px 12px;
  border-radius: 6px 6px 0 0;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}}
.prev-filter-btn:hover {{
  background: rgba(255,255,255,0.1);
  color: #fff;
}}
.prev-filter-btn.prev-filter-active {{
  background: rgba(255,255,255,0.12);
  color: #fff;
  border-bottom-color: #5b9bd5;
}}

/* --- Tier Headers --- */
.prev-tier-header {{
  font-size: 0.72rem;
  font-weight: 700;
  color: #a0a0a0;
  text-transform: uppercase;
  letter-spacing: 1px;
  padding: 8px 10px;
  margin: 16px 0 8px;
  background: rgba(255,255,255,0.03);
  border-radius: 4px;
}}

/* --- Chip Grid --- */
.preview-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  max-width: 520px;
  margin: 0 auto;
}}
@media (max-width: 500px) {{
  .preview-grid {{ grid-template-columns: 1fr; max-width: 100%; }}
}}

.preview-chip {{
  background: #1e1e30;
  border-radius: 8px;
  padding: 10px 10px 8px;
  cursor: pointer;
  transition: transform 0.12s, box-shadow 0.12s;
  border-left: 4px solid #666;
}}
.preview-chip:hover {{
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(0,0,0,0.5);
}}
.preview-chip:active {{
  transform: translateY(0);
  box-shadow: none;
}}
.chip-row1 {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
}}
.chip-name {{
  font-weight: 700;
  font-size: 0.78rem;
  color: #fff;
  min-width: 0;
}}
.chip-rank {{
  font-size: 0.52rem;
  font-weight: 700;
  background: rgba(255,255,255,0.1);
  color: #a0a0a0;
  padding: 1px 5px;
  border-radius: 4px;
  flex-shrink: 0;
  white-space: nowrap;
}}
@media (max-width: 500px) {{
  .chip-name {{ font-size: 0.85rem; }}
  .chip-sub {{ font-size: 0.65rem; }}
  .chip-stats {{ font-size: 0.68rem; }}
  .chip-arch {{ font-size: 0.58rem; }}
  .chip-rank {{ font-size: 0.58rem; }}
}}
.chip-sub {{
  font-size: 0.58rem;
  color: #808080;
  margin: 2px 0;
}}
.chip-stats {{
  display: flex;
  gap: 6px;
  align-items: baseline;
  font-size: 0.62rem;
  margin-top: 3px;
}}
.chip-fppg {{
  font-weight: 700;
  color: #4FC3F7;
}}
.chip-gp {{
  color: #a0a0a0;
}}
.chip-career {{
  color: #808080;
  font-size: 0.55rem;
}}
.chip-arch {{
  font-size: 0.52rem;
  color: #606060;
  font-style: italic;
  margin-top: 2px;
}}

/* Player card chip hidden by filter */
.preview-chip.prev-hidden {{
  display: none;
}}

{get_player_card_css()}
</style>
</head>
<body>

<div class="prev-header">
  <div class="prev-title">{LEAGUE_NAME_SHORT} Player Cards</div>
  <div class="prev-subtitle">Tap any player to open their scouting card</div>
  <div class="prev-count">{len(cards)} players &middot; Season {SEASON_NUMBER}</div>
</div>

{filter_html}

{chips_html}

{embed_player_card_data(cards)}

<script>
{get_player_card_js()}

/* --- Manager filter --- */
function prevFilter(mgr) {{
  var chips = document.querySelectorAll('.preview-chip');
  var btns = document.querySelectorAll('.prev-filter-btn');

  btns.forEach(function(b) {{ b.classList.remove('prev-filter-active'); }});
  event.target.classList.add('prev-filter-active');

  chips.forEach(function(chip) {{
    if (mgr === 'all') {{
      chip.classList.remove('prev-hidden');
    }} else {{
      var sub = chip.querySelector('.chip-sub');
      if (sub && sub.textContent.indexOf(mgr) !== -1) {{
        chip.classList.remove('prev-hidden');
      }} else {{
        chip.classList.add('prev-hidden');
      }}
    }}
  }});
}}
</script>

</body>
</html>"""

    return html


if __name__ == "__main__":
    main()
