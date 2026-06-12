"""newsletter_html_generator.py

Generate a beautifully-styled HTML newsletter from a markdown draft.

Designed to look like a professional sports publication (The Athletic / ESPN vibes).

Usage:
  python scripts/newsletter_html_generator.py --input assets/WEEK21_DRAFT.md --output output/WEEK21_NEWSLETTER.html --helmet assets/helmet.png --potw assets/potw.png --podium assets/podium.png --stats-report output/stats_report_week21.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.stats_corner_viz import (
    render_stats_corner_visualizations,
    get_stats_corner_css,
    get_stats_corner_js,
)
from modules.player_card_modal import (
    get_player_card_css,
    get_player_card_js,
    embed_player_card_data,
)
from modules.player_card_builder import build_player_cards
from modules.data_loader import (
    MANAGER_TO_TEAM as _CFG_MANAGER_TO_TEAM,
    MANAGERS,
    BRAND_COLORS, LEAGUE_NAME, LEAGUE_NAME_SHORT,
)

# Pre-computed manager regex alternation used by several parsers below to
# match multi-word manager names ("Mary Jane", "De'Aaron") rather than \w+.
# Sort longest-first so the regex engine prefers the longer name when one is
# a prefix of another.
_MANAGER_ALT = "|".join(re.escape(m) for m in sorted(MANAGERS, key=len, reverse=True))
_MANAGER_BY_LOWER = {m.lower(): m for m in MANAGERS}


# -------------------------
# Constants
# -------------------------

HELMET_BLUE = BRAND_COLORS.get("primary", "#1F4E79")
ACCENT_GOLD = BRAND_COLORS.get("accent", "#C9A227")
LIGHT_GRAY = "#f8f9fa"
MEDIUM_GRAY = "#6c757d"
DARK_GRAY = "#343a40"

# Manager name to team name mapping (lowercase keys for matching)
MANAGER_TO_TEAM = {k.lower(): v.lower() for k, v in _CFG_MANAGER_TO_TEAM.items()}

def names_match(name1: str, name2: str) -> bool:
    """Check if two names refer to the same team (handles manager vs team name)."""
    n1 = name1.lower().strip()
    n2 = name2.lower().strip()
    
    # Direct match
    if n1 == n2 or n1 in n2 or n2 in n1:
        return True
    
    # Check if one is a manager name and the other is the team name
    if n1 in MANAGER_TO_TEAM and MANAGER_TO_TEAM[n1] == n2:
        return True
    if n2 in MANAGER_TO_TEAM and MANAGER_TO_TEAM[n2] == n1:
        return True
    if n1 in MANAGER_TO_TEAM and n2 in MANAGER_TO_TEAM[n1]:
        return True
    if n2 in MANAGER_TO_TEAM and n1 in MANAGER_TO_TEAM[n2]:
        return True
    
    # Check reverse mapping (team name to manager)
    for manager, team in MANAGER_TO_TEAM.items():
        if (n1 == manager or n1 in team or team in n1) and (n2 == manager or n2 in team or team in n2):
            return True
    
    return False


# -------------------------
# Image handling
# -------------------------

def image_to_base64(path: str) -> Optional[str]:
    """Convert an image file to base64 data URI."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("utf-8")
        ext = Path(path).suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(ext, "image/png")
        return f"data:{mime};base64,{data}"
    except Exception:
        return None


# -------------------------
# Markdown parsing
# -------------------------

def strip_markdown_formatting(text: str) -> str:
    """Remove markdown formatting but preserve structure."""
    # Remove ** bold markers
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    # Remove single * italic markers
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    return text


def parse_markdown_table(lines: List[str]) -> str:
    """Convert markdown table lines to HTML table."""
    if len(lines) < 2:
        return ""
    
    def split_row(row: str) -> List[str]:
        cells = [c.strip() for c in row.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        return cells
    
    header_cells = split_row(lines[0])
    # Skip separator line (lines[1])
    data_rows = [split_row(line) for line in lines[2:] if line.strip()]
    
    html = '<div class="table-wrapper"><table>\n<thead>\n<tr>\n'
    for cell in header_cells:
        html += f'<th>{strip_markdown_formatting(cell)}</th>\n'
    html += '</tr>\n</thead>\n<tbody>\n'
    
    for row in data_rows:
        html += '<tr>\n'
        for cell in row:
            cell_html = strip_markdown_formatting(cell)
            # Color trend arrows only in trajectory cells (strings of ^, v, -> only)
            stripped = cell_html.strip()
            if stripped and all(c in '^v->- ' for c in stripped):
                cell_html = cell_html.replace('^', '<span class="arrow-up">^</span>')
                cell_html = cell_html.replace('->', '<span class="arrow-flat">-></span>')
                cell_html = cell_html.replace('v', '<span class="arrow-down">v</span>')
            html += f'<td>{cell_html}</td>\n'
        html += '</tr>\n'
    
    html += '</tbody>\n</table></div>'
    return html


# Global counter for unique paginated table IDs
_paginated_table_counter = 0


def parse_paginated_table(lines: List[str], page_size: int = 10) -> str:
    """Convert markdown table lines to an HTML table with pagination.
    
    Shows `page_size` rows at a time with clickable page buttons.
    Used for large Season Best/Worst performer tables.
    """
    global _paginated_table_counter
    _paginated_table_counter += 1
    table_id = f"paginated-table-{_paginated_table_counter}"
    
    if len(lines) < 2:
        return ""
    
    def split_row(row: str) -> List[str]:
        cells = [c.strip() for c in row.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        return cells
    
    header_cells = split_row(lines[0])
    # Skip separator line (lines[1])
    data_rows = [split_row(line) for line in lines[2:] if line.strip()]
    
    total_rows = len(data_rows)
    total_pages = (total_rows + page_size - 1) // page_size  # ceiling division
    
    # If only 1 page, render normally
    if total_pages <= 1:
        return parse_markdown_table(lines)
    
    # Build table with data-page attributes on rows
    html = f'<div class="table-wrapper"><div class="paginated-table-container" id="{table_id}">\n'
    html += '<table>\n<thead>\n<tr>\n'
    for cell in header_cells:
        html += f'<th>{strip_markdown_formatting(cell)}</th>\n'
    html += '</tr>\n</thead>\n<tbody>\n'
    
    for idx, row in enumerate(data_rows):
        page_num = idx // page_size + 1
        display = '' if page_num == 1 else ' style="display:none;"'
        html += f'<tr data-page="{page_num}"{display}>\n'
        for cell in row:
            cell_html = strip_markdown_formatting(cell)
            html += f'<td>{cell_html}</td>\n'
        html += '</tr>\n'
    
    html += '</tbody>\n</table>\n'
    
    # Add pagination buttons
    html += '<div class="pagination-controls">\n'
    for p in range(1, total_pages + 1):
        active_class = ' active' if p == 1 else ''
        html += f'<button class="page-btn{active_class}" onclick="paginateTable(\'{table_id}\', {p})">{p}</button>\n'
    html += '</div>\n'
    html += '</div></div>'
    
    return html


def is_table_separator(line: str) -> bool:
    """Check if line is a markdown table separator."""
    return bool(re.match(r'^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$', line))


def parse_betting_line(line: str) -> Optional[tuple]:
    """Parse a betting stat line and return (label, value) tuple."""
    clean = line.strip().strip('*')
    
    if clean.startswith('Line:'):
        return ('Line', clean.replace('Line:', '').strip())
    elif clean.startswith('Win Prob:'):
        return ('Win Prob', clean.replace('Win Prob:', '').strip())
    elif clean.startswith('Moneyline:'):
        return ('Moneyline', clean.replace('Moneyline:', '').strip())
    elif clean.startswith('Avg Score:'):
        return ('Avg Score', clean.replace('Avg Score:', '').strip())
    return None


def parse_all_betting_lines(lines_list: List[tuple]) -> dict:
    """Parse all betting line tuples into a structured dict."""
    data = {}
    
    for label, value in lines_list:
        if label == 'Line':
            # Parse: "Saboner -167.5 (Luka my Balls +167.5) | O/U: 3890"
            ou_match = re.search(r'\|\s*O/U:\s*([\d.]+)', value)
            if ou_match:
                data['over_under'] = ou_match.group(1)
            
            # Parse spreads: "Team1 -X (Team2 +Y)"
            spread_match = re.match(r'(.+?)\s*([+-][\d.]+)\s*\((.+?)\s*([+-][\d.]+)\)', value.split('|')[0])
            if spread_match:
                t1, s1, t2, s2 = spread_match.groups()
                data['team1_spread'] = (t1.strip(), s1)
                data['team2_spread'] = (t2.strip(), s2)
                
        elif label == 'Win Prob':
            # Parse: "Luka my Balls 27.9% | Saboner 72.1%"
            parts = value.split('|')
            if len(parts) == 2:
                match1 = re.search(r'([\d.]+%)', parts[0])
                match2 = re.search(r'([\d.]+%)', parts[1])
                if match1:
                    data['win_prob_1'] = match1.group(1)
                if match2:
                    data['win_prob_2'] = match2.group(1)
                # Also capture team names for ordering
                name1 = re.sub(r'[\d.]+%', '', parts[0]).strip()
                name2 = re.sub(r'[\d.]+%', '', parts[1]).strip()
                data['prob_team1'] = name1
                data['prob_team2'] = name2
                    
        elif label == 'Moneyline':
            # Parse: "Luka my Balls +260 | Saboner -260"
            parts = value.split('|')
            if len(parts) == 2:
                match1 = re.search(r'([+-][\d]+)', parts[0])
                match2 = re.search(r'([+-][\d]+)', parts[1])
                if match1:
                    data['ml_1'] = match1.group(1)
                if match2:
                    data['ml_2'] = match2.group(1)
                name1 = re.sub(r'[+-][\d]+', '', parts[0]).strip()
                name2 = re.sub(r'[+-][\d]+', '', parts[1]).strip()
                data['ml_team1'] = name1
                data['ml_team2'] = name2
                    
        elif label == 'Avg Score':
            # Parse: "Luka my Balls 1860.9 | Saboner 2028.5"
            parts = value.split('|')
            if len(parts) == 2:
                match1 = re.search(r'([\d.]+)', parts[0])
                match2 = re.search(r'([\d.]+)', parts[1])
                if match1:
                    data['avg_1'] = match1.group(1)
                if match2:
                    data['avg_2'] = match2.group(1)
                name1 = re.sub(r'[\d.]+', '', parts[0]).strip()
                name2 = re.sub(r'[\d.]+', '', parts[1]).strip()
                data['avg_team1'] = name1
                data['avg_team2'] = name2
    
    return data


def build_betting_table_from_data(betting_data: dict, team_a: str, team_b: str) -> str:
    """Build the final betting table with properly aligned data."""
    
    # Figure out which team is which based on the parsed data
    # Use spread data as primary reference
    spread_a = ''
    spread_b = ''
    if 'team1_spread' in betting_data:
        t1, s1 = betting_data['team1_spread']
        t2, s2 = betting_data['team2_spread']
        if names_match(t1, team_a):
            spread_a, spread_b = s1, s2
        else:
            spread_a, spread_b = s2, s1
    
    # Get win probs aligned to teams
    win_prob_a = ''
    win_prob_b = ''
    if 'prob_team1' in betting_data:
        t1 = betting_data.get('prob_team1', '')
        if names_match(t1, team_a):
            win_prob_a = betting_data.get('win_prob_1', '')
            win_prob_b = betting_data.get('win_prob_2', '')
        else:
            win_prob_a = betting_data.get('win_prob_2', '')
            win_prob_b = betting_data.get('win_prob_1', '')
    
    # Get moneylines aligned to teams
    ml_a = ''
    ml_b = ''
    if 'ml_team1' in betting_data:
        t1 = betting_data.get('ml_team1', '')
        if names_match(t1, team_a):
            ml_a = betting_data.get('ml_1', '')
            ml_b = betting_data.get('ml_2', '')
        else:
            ml_a = betting_data.get('ml_2', '')
            ml_b = betting_data.get('ml_1', '')
    
    # Get avg scores aligned to teams
    avg_a = ''
    avg_b = ''
    if 'avg_team1' in betting_data:
        t1 = betting_data.get('avg_team1', '')
        if names_match(t1, team_a):
            avg_a = betting_data.get('avg_1', '')
            avg_b = betting_data.get('avg_2', '')
        else:
            avg_a = betting_data.get('avg_2', '')
            avg_b = betting_data.get('avg_1', '')
    
    over_under = betting_data.get('over_under', '')
    over_val = f"o{over_under}" if over_under else ''
    under_val = f"u{over_under}" if over_under else ''
    
    html = f'''<div class="table-wrapper"><table class="betting-lines-table">
<thead>
<tr>
<th>Team</th>
<th>Spread</th>
<th>Total</th>
<th>Moneyline</th>
<th>Win Prob</th>
<th>Avg Score</th>
</tr>
</thead>
<tbody>
<tr>
<td class="team-name">{team_a}</td>
<td>{spread_a}</td>
<td>{over_val}</td>
<td>{ml_a}</td>
<td>{win_prob_a}</td>
<td>{avg_a}</td>
</tr>
<tr>
<td class="team-name">{team_b}</td>
<td>{spread_b}</td>
<td>{under_val}</td>
<td>{ml_b}</td>
<td>{win_prob_b}</td>
<td>{avg_b}</td>
</tr>
</tbody>
</table></div>'''
    return html


def parse_section(text: str, section_name: str) -> str:
    """Parse a section's content into HTML."""
    lines = text.strip().split('\n')
    
    # Filter out horizontal rules and end-of-newsletter markers
    lines = [l for l in lines if not (
        l.strip().startswith('---') or 
        'End of Week' in l or
        'End of Newsletter' in l
    )]
    
    # Tables to skip in Stats Corner (covered by interactive visualizations)
    SKIP_TABLES = [
        'Positional Scoring Breakdown',
        'Season Waiver Wire ROI',
        'Bench Report',
        'Record Book Snapshot',
        'Keeper Watch',
        'Draft Value Tracker',
    ]
    is_stats_corner = 'stats corner' in section_name.lower()
    
    html_parts = []
    i = 0
    n = len(lines)
    last_subsection_header = ""  # Track the most recent **header** for paginated table detection
    skip_current_block = False   # When True, skip tables/bullets under a filtered header
    
    while i < n:
        line = lines[i].strip()
        
        # Skip empty lines
        if not line:
            i += 1
            continue
        
        # --- Stats Corner table filtering ---
        # Detect subsection headers (bold text) and check against skip list
        if line.startswith('**') and ('**' in line[2:]):
            header_text = line.strip('*').strip().split('(')[0].strip()
            if is_stats_corner and any(skip in header_text or skip in line for skip in SKIP_TABLES):
                skip_current_block = True
                i += 1
                continue
            else:
                skip_current_block = False
        
        # While skipping, drop tables, bullets, and continuation lines
        if skip_current_block:
            i += 1
            continue
        
        # Check for table (header line followed by separator)
        if i + 1 < n and '|' in line and is_table_separator(lines[i + 1]):
            # Collect table lines
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < n and lines[i].strip() and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1
            
            # Use paginated table for Season Best/Worst performer tables (30 rows, paginate 10 at a time)
            if any(kw in last_subsection_header for kw in ['Best Performers', 'Worst Performers', 'Season Best', 'Season Worst']):
                html_parts.append(parse_paginated_table(table_lines, page_size=10))
            else:
                html_parts.append(parse_markdown_table(table_lines))
            continue
        
        # Check for bullet points
        if line.startswith('-> ') or line.startswith('- '):
            bullet_items = []
            while i < n and (lines[i].strip().startswith('-> ') or lines[i].strip().startswith('- ')):
                raw = lines[i].strip()
                if raw.startswith('-> '):
                    item_text = raw[3:]   # Remove '-> '
                else:
                    item_text = raw[2:]   # Remove '- '
                i += 1
                
                # Collect continuation lines (lines that follow a bullet but aren't bullets themselves)
                # These are typically indented or are description paragraphs
                continuation_lines = []
                while i < n:
                    next_line = lines[i].strip()
                    
                    # Skip empty lines but peek ahead to see if continuation follows
                    if not next_line:
                        # Look ahead to see what comes after empty line(s)
                        peek = i + 1
                        while peek < n and not lines[peek].strip():
                            peek += 1
                        
                        # If next non-empty line is a bullet or section header, stop here
                        if peek >= n:
                            break
                        peek_line = lines[peek].strip()
                        if peek_line.startswith('-> ') or peek_line.startswith('- '):
                            break
                        if peek_line.startswith('**') and peek_line.endswith('**') and len(peek_line) < 120:
                            break
                        
                        # Otherwise, skip the empty line and continue collecting
                        i += 1
                        continue
                    
                    if next_line.startswith('-> ') or next_line.startswith('- '):
                        break
                    if next_line.startswith('**') and next_line.endswith('**') and len(next_line) < 120:
                        # This is likely a subsection header, stop here
                        break
                    # This is a continuation line
                    continuation_lines.append(next_line.replace('**', ''))
                    i += 1
                
                # Combine bullet header with continuation
                if continuation_lines:
                    full_text = f'{item_text}<br><span class="bullet-detail">{" ".join(continuation_lines)}</span>'
                else:
                    full_text = item_text
                
                # Convert markdown bold/italic to HTML tags (don't strip them)
                full_text_clean = strip_markdown_formatting(full_text)
                
                # If no <strong> tags were produced by markdown conversion,
                # try auto-bolding trade headers or player name headers
                if '<strong>' not in full_text_clean:
                    if ' -> ' in full_text_clean or ' sends ' in full_text_clean:
                        # Bold everything before the <br> tag
                        full_text_clean = re.sub(
                            r'^([^<]+)(<br>)',
                            r'<strong>\1</strong>\2',
                            full_text_clean
                        )
                    else:
                        # Bold player names with team in parentheses at start of bullet
                        # Pattern: "Player Name (Team)" at beginning of line
                        full_text_clean = re.sub(
                            r'^([A-Z][a-zA-Z\'\'\-\.]+(?:\s+[A-Z][a-zA-Z\'\'\-\.]+)*\s*\([^)]+\))',
                            r'<strong>\1</strong>',
                            full_text_clean
                        )
                
                bullet_items.append(f'<li>{full_text_clean}</li>')
                
                # Skip any trailing empty lines before next bullet
                while i < n and not lines[i].strip():
                    i += 1
            
            html_parts.append('<ul>\n' + '\n'.join(bullet_items) + '\n</ul>')
            continue
        
        # Check for Player of the Week header - simplify to just player name
        if 'Player of the Week:' in line or 'Player of the Week:' in line.replace('**', ''):
            clean_line = line.replace('**', '').strip()
            # Extract just the player name (before the parenthetical team name)
            match = re.search(r'Player of the Week:\s*([^(]+)', clean_line)
            if match:
                player_name = match.group(1).strip()
                html_parts.append(f'<h3 class="potw-name">{player_name}</h3>')
                i += 1
                continue
        
        # Check for matchup headers FIRST (contain score pattern like "Team1 1234.5 - Team2 1234.5")
        # This must come before subsection header check since matchups also use **bold**
        clean_check = line.replace('**', '').strip()
        if len(clean_check) < 80 and re.match(r'^[A-Za-z][A-Za-z\s]+\d+\.?\d*\s*(?:-{1,2}|def\.)\s*[A-Za-z][A-Za-z\s]+\d+\.?\d*$', clean_check):
            html_parts.append(f'<div class="matchup-header">{clean_check}</div>')
            i += 1
            continue
        
        # Check for betting matchup header (Team vs Team) - must come before subsection header check
        if ' vs ' in line.lower() and len(line) < 60:
            clean_line = line.replace('**', '').strip()
            html_parts.append(f'<div class="matchup-header">{clean_line}</div>')
            i += 1
            
            # Extract team names from header
            vs_match = re.match(r'^(.+?)\s+vs\s+(.+)$', clean_line, re.IGNORECASE)
            team_a = vs_match.group(1).strip() if vs_match else ''
            team_b = vs_match.group(2).strip() if vs_match else ''
            
            # Look ahead for betting stat lines to convert to table
            betting_lines = []
            while i < n:
                next_line = lines[i].strip()
                if not next_line:
                    i += 1
                    continue
                # Check if it's a betting stat line (strip * markers first)
                clean_next = next_line.strip('*')
                parsed_bet = parse_betting_line(clean_next)
                if parsed_bet:
                    betting_lines.append(parsed_bet)
                    i += 1
                    continue
                # Not a betting line, break out
                break
            
            # If we found betting lines, build a table
            if betting_lines and team_a and team_b:
                betting_data = parse_all_betting_lines(betting_lines)
                html_parts.append(build_betting_table_from_data(betting_data, team_a, team_b))
            else:
                # Fall back to rendering as regular stat lines
                for label, value in betting_lines:
                    html_parts.append(f'<p class="stat-line">{label}: {value}</p>')
            
            continue
        
        # Check for subsection headers (bold lines that are short, like "Trade Ideas")
        # This comes AFTER matchup and betting header checks
        if line.startswith('**') and line.endswith('**') and len(line) < 120:
            title = line.strip('*')
            last_subsection_header = title  # Track for paginated table detection
            html_parts.append(f'<h4>{strip_markdown_formatting(title)}</h4>')
            i += 1
            continue
        
        # Check for stat lines (italicized, contain stats) - fallback for unmatched
        if line.startswith('*') and line.endswith('*') and '|' not in line:
            stat_text = line.strip('*')
            html_parts.append(f'<p class="stat-line">{stat_text}</p>')
            i += 1
            continue
        
        # Check for betting/preview stat lines
        if any(line.startswith(prefix) for prefix in ['Line:', 'Win Prob:', 'Moneyline:', 'Avg Score:', 'O/U:']):
            html_parts.append(f'<p class="stat-line">{strip_markdown_formatting(line)}</p>')
            i += 1
            continue
        
        # Regular paragraph - collect consecutive non-empty lines
        para_lines = [line]
        i += 1
        while i < n and lines[i].strip() and not lines[i].strip().startswith(('-> ', '- ', '|', '**')):
            next_line = lines[i].strip()
            # Stop if next line looks like a new element
            if next_line.startswith('*') and next_line.endswith('*'):
                break
            if any(next_line.startswith(p) for p in ['Line:', 'Win Prob:', 'Moneyline:', 'Avg Score:', 'O/U:']):
                break
            if re.match(r'^.+\d+\.?\d*\s*(?:-{1,2}|def\.)\s*.+\d+\.?\d*$', next_line.replace('**', '')):
                break
            if ' vs ' in next_line.lower() and len(next_line) < 60:
                break
            para_lines.append(next_line)
            i += 1
        
        para_text = ' '.join(para_lines)
        html_parts.append(f'<p>{strip_markdown_formatting(para_text)}</p>')
    
    return '\n'.join(html_parts)


def parse_report_cards(text: str) -> str:
    """Parse the Report Cards section specially to handle grades correctly."""
    html_parts = []
    
    # Filter out horizontal rules and end-of-newsletter markers
    text = '\n'.join([l for l in text.split('\n') if not (
        l.strip().startswith('---') or 
        'End of Week' in l or
        'End of Newsletter' in l
    )])
    
    # Note: Unicode dash normalization (em-dash, en-dash) is handled globally
    # in build_newsletter_html() before this function is called
    
    # Split by the grade pattern to find each report card
    # Pattern: Manager Name (Team Name): Grade or Manager Name (Team Name) -- Grade
    # Supports double-hyphen (--), single hyphen (-), arrow (->), and colon (:)
    # FIXED: Use MANAGERS alternation instead of [A-Z][a-z]+, which only
    # matched single-word names (broke "Mary Jane" etc.).
    blocks = re.split(
        rf'\n(?=\*?\*?(?:{_MANAGER_ALT})\s*\([^)]+\)\s*(?:-{{1,2}}|->|:)\s*[A-F][+-]?)',
        text.strip(),
    )
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        
        # Try to extract the header line with grade
        lines = block.split('\n')
        first_line = lines[0].replace('**', '').strip()
        # Also strip single * italic markers (e.g., "*(previously C-)*" -> "(previously C-)")
        first_line = re.sub(r'\*([^*]+)\*', r'\1', first_line)
        
        # Match pattern like "Benton (Smaxey): A-" or "Nick (Luka my Balls) -- C-"
        # Supports double-hyphen (--), single hyphen (-), arrow (->), and colon (:)
        grade_match = re.match(r'^(.+?)\s*(?:-{1,2}|->|:)\s*([A-F][+-]?)(?:\s*\(previously [A-F][+-]?\))?\s*$', first_line)
        
        if grade_match:
            name = grade_match.group(1).strip()
            grade = grade_match.group(2).strip()
            grade_letter = grade[0].lower()
            
            html_parts.append(f'''<div class="report-card">
    <div class="report-card-header">
        <span class="manager-name">{name}</span>
        <span class="grade grade-{grade_letter}">{grade}</span>
    </div>''')
            
            # Process remaining lines
            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue
                
                # Stat line (starts with * or contains Record:)
                if (line.startswith('*') and line.endswith('*')) or line.startswith('Record:') or line.startswith('*Record:'):
                    stat_text = line.strip('*').strip()
                    html_parts.append(f'    <p class="stat-line">{stat_text}</p>')
                else:
                    # Narrative paragraph
                    clean_line = line.replace('**', '')
                    html_parts.append(f'    <p>{strip_markdown_formatting(clean_line)}</p>')
            
            html_parts.append('</div>')
        else:
            # Fallback - treat as regular content
            html_parts.append(f'<p>{strip_markdown_formatting(block.replace("**", ""))}</p>')
    
    return '\n'.join(html_parts)


def parse_looking_ahead(text: str) -> str:
    """Parse the Looking Ahead section with betting tables."""
    html_parts = []
    
    # Filter out horizontal rules and end-of-newsletter markers
    text = '\n'.join([l for l in text.split('\n') if not (
        l.strip().startswith('---') or 
        'End of Week' in l or
        'End of Newsletter' in l
    )])
    
    # Split by matchup headers (Team vs Team)
    matchup_pattern = re.compile(r'\n(?=\*?\*?[A-Za-z].*?\s+vs\s+.*?\*?\*?\s*\n)', re.IGNORECASE)
    matchups = matchup_pattern.split('\n' + text.strip())
    
    for matchup in matchups:
        matchup = matchup.strip()
        if not matchup:
            continue
        
        lines = matchup.split('\n')
        
        # First line should be the matchup header
        header_line = lines[0].replace('**', '').strip()
        
        if ' vs ' not in header_line.lower():
            # Not a matchup block, skip or treat as regular content
            continue
        
        html_parts.append('<div class="matchup-preview">')
        html_parts.append('<div class="betting-box">')
        html_parts.append(f'<div class="matchup-title">{header_line}</div>')
        
        # Collect betting lines and narrative
        betting_lines = []
        narrative_lines = []
        
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            
            # Remove italics markers
            clean_line = line.strip('*').strip()
            
            # Check if it's a betting stat line
            if ':' in clean_line and any(clean_line.startswith(prefix) for prefix in 
                ['Line:', 'Win Prob:', 'Moneyline:', 'Avg Score:', 'O/U:']):
                betting_lines.append(clean_line)
            elif any(keyword in clean_line for keyword in ['Line:', 'Win Prob:', 'Moneyline:', 'Avg Score:', 'O/U:']):
                betting_lines.append(clean_line)
            else:
                narrative_lines.append(clean_line)
        
        # Create betting table
        if betting_lines:
            html_parts.append('<table class="betting-table">')
            html_parts.append('<tbody>')
            for bet_line in betting_lines:
                if ':' in bet_line:
                    parts = bet_line.split(':', 1)
                    label = parts[0].strip()
                    value = parts[1].strip() if len(parts) > 1 else ''
                    html_parts.append(f'<tr><td class="betting-label">{label}</td><td class="betting-value">{value}</td></tr>')
            html_parts.append('</tbody>')
            html_parts.append('</table>')
        
        html_parts.append('</div>')  # Close betting-box
        
        # Add narrative
        if narrative_lines:
            narrative_text = ' '.join(narrative_lines)
            html_parts.append(f'<div class="preview-narrative"><p>{strip_markdown_formatting(narrative_text)}</p></div>')
        
        html_parts.append('</div>')  # Close matchup-preview
    
    return '\n'.join(html_parts)


def parse_newsletter(text: str) -> Tuple[str, str, List[Tuple[str, str]]]:
    """Parse the newsletter markdown into title, subtitle, and sections."""
    lines = text.strip().split('\n')
    
    # Extract title and subtitle
    title = f"{LEAGUE_NAME_SHORT} Weekly Newsletter"
    subtitle = ""
    
    for line in lines[1:10]:
        stripped = line.strip()
        if stripped and not stripped.startswith(('#', '---')):
            # Look for season/week line
            if 'Season' in stripped or 'Week' in stripped:
                subtitle = stripped.replace('**', '').strip()
                break
    
    # Find sections
    section_pattern = re.compile(r'^#{1,3}\s*\*?\*?(\d+\.\s+[^*\n]+)\*?\*?\s*$', re.MULTILINE)
    matches = list(section_pattern.finditer(text))
    
    sections = []
    for i, match in enumerate(matches):
        heading = re.sub(r'^\d+\.\s*', '', match.group(1)).strip().replace('**', '')
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        
        # Remove duplicate section name if it appears at the start
        content_lines = content.split('\n', 1)
        if content_lines:
            first_line_clean = content_lines[0].replace('**', '').strip()
            if first_line_clean.lower() == heading.lower():
                content = content_lines[1].strip() if len(content_lines) > 1 else ""
        
        sections.append((heading, content))
    
    return title, subtitle, sections


# -------------------------
# HTML generation
# -------------------------

def generate_html(
    title: str,
    subtitle: str,
    sections: List[Tuple[str, str]],
    helmet_base64: Optional[str] = None,
    potw_base64: Optional[str] = None,
    podium_base64: Optional[str] = None,
    stats_report: Optional[dict] = None,
    data_dir: Optional[Path] = None,
    config_dir: Optional[Path] = None,
    historical_dir: Optional[Path] = None,
) -> str:
    """Generate the complete HTML document."""
    
    # Build player card data if stats_report is available
    _player_card_embed = ""
    _player_cards = None
    if stats_report:
        kw_players = stats_report.get("keeper_watch", {}).get("players", [])
        if kw_players and data_dir and config_dir and historical_dir:
            try:
                _player_cards = build_player_cards(
                    keeper_watch_players=kw_players,
                    data_dir=data_dir,
                    config_dir=config_dir,
                    historical_dir=historical_dir,
                    season_performers=stats_report.get("season_performers"),
                )
                _player_card_embed = embed_player_card_data(_player_cards)
            except Exception as e:
                print(f"  WARNING: Player card build failed: {e}")
                _player_card_embed = ""
                _player_cards = None
    
    # Build sections HTML
    sections_html = []
    for heading, content in sections:
        section_id = heading.lower().replace(' ', '-').replace('&', 'and')
        
        # Special handling for different section types
        if 'player of the week' in heading.lower():
            content_html = parse_section(content, heading)
            potw_img = f'<img src="{potw_base64}" alt="Player of the Week" class="potw-img">' if potw_base64 else ''
            podium_img = f'<img src="{podium_base64}" alt="" class="podium-img">' if podium_base64 else ''
            
            section_html = f'''
        <section id="{section_id}" class="potw-section">
            <h2>{heading}</h2>
            <div class="potw-container">
                <div class="potw-image-stack">
                    {potw_img}
                    {podium_img}
                </div>
                <div class="potw-content">{content_html}</div>
            </div>
        </section>'''
        
        elif 'report card' in heading.lower():
            content_html = parse_report_cards(content)
            section_html = f'''
        <section id="{section_id}">
            <h2>{heading}</h2>
            {content_html}
        </section>'''
        
        elif 'looking ahead' in heading.lower():
            content_html = parse_looking_ahead(content)
            section_html = f'''
        <section id="{section_id}">
            <h2>{heading}</h2>
            {content_html}
        </section>'''
        
        elif 'stats corner' in heading.lower():
            content_html = parse_section(content, heading)
            # Inject Stats Corner visualizations from stats_report data
            viz_top_html = ""
            viz_bottom_html = ""
            if stats_report:
                viz_top_html = render_stats_corner_visualizations(stats_report, position="top", player_cards=_player_cards) or ""
                viz_bottom_html = render_stats_corner_visualizations(stats_report, position="bottom") or ""
            
            # Add sub-navigation for Stats Corner sections
            sc_subnav = '''
            <div class="sc-subnav">
                <a href="javascript:void(0)" onclick="document.querySelector('.sc-donut-grid')?.parentElement?.scrollIntoView({behavior:'smooth'})">Positional</a>
                <a href="javascript:void(0)" onclick="document.querySelector('[data-viz=\\'draft-value\\']')?.scrollIntoView({behavior:'smooth'})">Draft Value</a>
                <a href="javascript:void(0)" onclick="document.querySelector('[data-viz=\\'waiver-roi\\']')?.scrollIntoView({behavior:'smooth'})">Waiver ROI</a>
                <a href="javascript:void(0)" onclick="document.querySelector('[data-viz=\\'keeper-watch\\']')?.scrollIntoView({behavior:'smooth'})">Keeper Watch</a>
                <a href="javascript:void(0)" onclick="document.querySelector('.sc-rb-card')?.scrollIntoView({behavior:'smooth'})">Record Book</a>
                <a href="javascript:void(0)" onclick="document.querySelector('.sc-tables-section')?.scrollIntoView({behavior:'smooth'})">Season Leaders</a>
            </div>'''
            
            # Wrap tables in a section for the shortcut
            content_html = f'<div class="sc-tables-section">{content_html}</div>'
            
            section_html = f'''
        <section id="{section_id}">
            <h2>{heading}</h2>
            {sc_subnav}
            {viz_top_html}
            {content_html}
            {viz_bottom_html}
        </section>'''
        
        else:
            content_html = parse_section(content, heading)
            section_html = f'''
        <section id="{section_id}">
            <h2>{heading}</h2>
            {content_html}
        </section>'''
        
        sections_html.append(section_html)
    
    # Helmet image for header
    helmet_img = f'<img src="{helmet_base64}" alt="Logo" class="helmet">' if helmet_base64 else ''
    helmet_img_right = f'<img src="{helmet_base64}" alt="Logo" class="helmet helmet-right">' if helmet_base64 else ''

    # Precompute nav links (avoids backslash-in-f-string-expression syntax error on Python 3.10/3.11)
    _nav_link_parts = []
    for _h, _ in sections:
        _h_id = _h.lower().replace(" ", "-").replace("&", "and")
        _nav_link_parts.append(
            '<a href="javascript:void(0)" onclick="document.getElementById('
            + "'" + _h_id + "'"
            + ').scrollIntoView({behavior:' + "'smooth'" + '})">'
            + _h + '</a>'
        )
    nav_links_html = ' '.join(_nav_link_parts)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Playfair+Display:wght@700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary-blue: {HELMET_BLUE};
            --accent-gold: {ACCENT_GOLD};
            --light-gray: {LIGHT_GRAY};
            --medium-gray: {MEDIUM_GRAY};
            --dark-gray: {DARK_GRAY};
            --text-primary: #1a1a1a;
            --text-secondary: #4a4a4a;
            --border-color: #e0e0e0;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 16px;
            line-height: 1.7;
            color: var(--text-primary);
            background: #fff;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            text-align: center;
        }}
        
        /* Header */
        header {{
            text-align: center;
            padding: 40px 20px;
            border-bottom: 3px solid var(--primary-blue);
            margin-bottom: 40px;
            position: relative;
        }}
        
        .header-content {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 30px;
        }}
        
        .helmet {{
            width: 70px;
            height: 70px;
            object-fit: contain;
        }}
        
        .helmet-right {{
            transform: scaleX(-1);
        }}
        
        .header-text {{
            text-align: center;
        }}
        
        header h1 {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--primary-blue);
            letter-spacing: -0.5px;
            margin-bottom: 8px;
        }}
        
        header .subtitle {{
            font-size: 1.1rem;
            color: var(--medium-gray);
            font-weight: 500;
        }}
        
        /* Navigation */
        nav {{
            background: var(--light-gray);
            padding: 15px 20px;
            margin-bottom: 40px;
            border-radius: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            justify-content: center;
        }}
        
        nav a {{
            color: var(--primary-blue);
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 500;
            padding: 6px 12px;
            border-radius: 4px;
            transition: background 0.2s;
        }}
        
        nav a:hover {{
            background: rgba(31, 78, 121, 0.1);
        }}
        
        /* Stats Corner Sub-Navigation */
        .sc-subnav {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            justify-content: center;
            padding: 12px 16px;
            margin-bottom: 24px;
            background: var(--light-gray);
            border-radius: 6px;
            border: 1px solid var(--border-color);
        }}
        
        .sc-subnav a {{
            color: var(--primary-blue);
            text-decoration: none;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 5px 10px;
            border-radius: 4px;
            transition: background 0.2s, color 0.2s;
            white-space: nowrap;
        }}
        
        .sc-subnav a:hover {{
            background: var(--primary-blue);
            color: #fff;
        }}
        
        /* Sections */
        section {{
            margin-bottom: 50px;
            padding-bottom: 30px;
            border-bottom: 1px solid var(--border-color);
            text-align: center;
        }}
        
        section:last-child {{
            border-bottom: none;
        }}
        
        h2 {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 1.75rem;
            color: var(--primary-blue);
            margin-bottom: 25px;
            padding-bottom: 10px;
            border-bottom: 2px solid var(--accent-gold);
            display: block;
            text-align: center;
        }}
        
        h3 {{
            font-size: 1.2rem;
            color: var(--dark-gray);
            margin: 25px 0 15px 0;
            font-weight: 600;
            text-align: center;
        }}
        
        h4 {{
            font-size: 1.1rem;
            color: var(--primary-blue);
            margin: 30px 0 15px 0;
            font-weight: 600;
            text-align: center;
        }}
        
        p {{
            margin-bottom: 16px;
            color: var(--text-secondary);
            text-align: center;
        }}
        
        /* Matchup headers */
        .matchup-header {{
            font-size: 1.4rem;
            font-weight: 800;
            color: var(--text-primary);
            margin: 35px 0 15px 0;
            padding: 20px 24px;
            background: var(--light-gray);
            border-left: 5px solid var(--primary-blue);
            border-radius: 0 8px 8px 0;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }}
        
        /* Stat lines */
        .stat-line {{
            font-size: 0.9rem;
            color: var(--medium-gray);
            font-style: italic;
            margin-bottom: 8px;
            padding: 8px 16px;
            border-left: none;
            text-align: center;
        }}
        
        /* Report Cards */
        .report-card {{
            background: var(--light-gray);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        
        .report-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        
        .manager-name {{
            font-weight: 700;
            font-size: 1.15rem;
            color: var(--text-primary);
        }}
        
        .grade {{
            font-size: 1.5rem;
            font-weight: 700;
            padding: 6px 18px;
            border-radius: 6px;
            color: white;
        }}
        
        .grade-a {{ background: #22c55e; }}
        .grade-b {{ background: #84cc16; }}
        .grade-c {{ background: #eab308; }}
        .grade-d {{ background: #f97316; }}
        .grade-f {{ background: #ef4444; }}
        
        .report-card .stat-line {{
            background: white;
            padding: 10px 16px;
            border-radius: 4px;
            border-left: 3px solid var(--primary-blue);
            margin-bottom: 12px;
        }}
        
        .report-card p:not(.stat-line) {{
            margin-bottom: 0;
        }}
        
        /* Looking Ahead - Matchup Previews */
        .matchup-preview {{
            margin-bottom: 30px;
            padding-bottom: 30px;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .matchup-preview:last-child {{
            border-bottom: none;
            margin-bottom: 0;
            padding-bottom: 0;
        }}
        
        .betting-box {{
            background: var(--light-gray);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }}
        
        .matchup-title {{
            font-weight: 700;
            font-size: 1.1rem;
            color: var(--primary-blue);
            margin-bottom: 12px;
            text-align: center;
        }}
        
        .betting-table {{
            width: 100%;
            font-size: 0.85rem;
            box-shadow: none;
            margin: 0;
        }}
        
        .betting-table tbody tr {{
            background: white;
        }}
        
        .betting-table tbody tr:nth-child(even) {{
            background: #f0f4f8;
        }}
        
        .betting-table td {{
            padding: 8px 10px;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .betting-table .betting-label {{
            font-weight: 600;
            color: var(--text-primary);
            text-align: left;
            width: 45%;
        }}
        
        .betting-table .betting-value {{
            color: var(--text-secondary);
            text-align: right;
        }}
        
        /* Matchup Stats Table */
        .matchup-stats-table {{
            width: 100%;
            max-width: 700px;
            margin: 15px auto;
            border-collapse: collapse;
            font-size: 0.9rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .matchup-stats-table th {{
            background: var(--primary-blue);
            color: white;
            padding: 12px 15px;
            font-weight: 600;
            text-align: center;
        }}
        
        .matchup-stats-table td {{
            padding: 10px 15px;
            text-align: center;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .matchup-stats-table tbody tr:nth-child(even) {{
            background: var(--light-gray);
        }}
        
        .matchup-stats-table .team-name {{
            font-weight: 600;
            color: var(--text-primary);
        }}
        
        .matchup-stats-table .series-row {{
            background: #e8f0f7 !important;
            font-style: italic;
        }}
        
        /* Betting Lines Table - DraftKings Style */
        .betting-lines-table {{
            width: auto;
            max-width: 95%;
            margin-left: auto;
            margin-right: auto;
            margin-top: 15px;
            margin-bottom: 15px;
            border-collapse: collapse;
            font-size: 0.9rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .betting-lines-table th {{
            background: var(--primary-blue);
            color: white;
            padding: 12px 10px;
            font-weight: 600;
            text-align: center;
            font-size: 0.8rem;
            text-transform: uppercase;
        }}
        
        .betting-lines-table td {{
            padding: 12px 10px;
            border-bottom: 1px solid var(--border-color);
            text-align: center;
        }}
        
        .betting-lines-table tbody tr:nth-child(odd) {{
            background: var(--light-gray);
        }}
        
        .betting-lines-table .team-name {{
            font-weight: 600;
            color: var(--text-primary);
            text-align: left;
        }}
        
        .betting-lines-table .ou-cell {{
            background: #e8f0f7;
            font-weight: 600;
            vertical-align: middle;
        }}
        
        .preview-narrative {{
            display: flex;
            align-items: center;
        }}
        
        .preview-narrative p {{
            margin: 0;
            font-size: 0.95rem;
            line-height: 1.7;
        }}
        
        /* Player of the Week */
        .potw-container {{
            display: flex;
            gap: 30px;
            align-items: center;
        }}
        
        .potw-image-stack {{
            display: flex;
            flex-direction: column;
            align-items: center;
            flex-shrink: 0;
            width: 160px;
        }}
        
        .potw-img {{
            width: 150px;
            height: 150px;
            object-fit: cover;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        
        .podium-img {{
            width: 120px;
            margin-top: 5px;
        }}
        
        .potw-content {{
            flex: 1;
        }}
        
        .potw-name {{
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 1.5rem;
            color: var(--primary-blue);
            margin: 0 0 5px 0;
            font-weight: 700;
        }}
        
        /* Tables */
        /* Table wrapper for centering */
        .table-wrapper {{
            display: flex;
            justify-content: center;
            width: 100%;
            overflow-x: auto;
        }}
        
        table {{
            width: auto;
            max-width: 95%;
            border-collapse: collapse;
            margin-left: auto;
            margin-right: auto;
            margin-top: 20px;
            margin-bottom: 20px;
            font-size: 0.9rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border-radius: 8px;
            overflow: hidden;
        }}
        
        thead {{
            background: var(--primary-blue);
            color: white;
        }}
        
        th {{
            padding: 14px 12px;
            text-align: center;
            font-weight: 600;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        td {{
            padding: 12px;
            text-align: center;
            border-bottom: 1px solid var(--border-color);
        }}
        
        tbody tr:nth-child(even) {{
            background: var(--light-gray);
        }}
        
        tbody tr:hover {{
            background: rgba(31, 78, 121, 0.05);
        }}
        
        /* Paginated table controls */
        .paginated-table-container {{
            width: 100%;
        }}
        
        .pagination-controls {{
            display: flex;
            justify-content: center;
            gap: 8px;
            margin-top: 10px;
            margin-bottom: 10px;
        }}
        
        .page-btn {{
            background: var(--light-gray);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 6px 14px;
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        
        .page-btn:hover {{
            background: rgba(31, 78, 121, 0.1);
            border-color: var(--primary-blue);
            color: var(--primary-blue);
        }}
        
        .page-btn.active {{
            background: var(--primary-blue);
            color: white;
            border-color: var(--primary-blue);
        }}
        
        /* Trend arrows */
        .arrow-up {{
            color: #22c55e;
            font-weight: 700;
        }}
        
        .arrow-down {{
            color: #ef4444;
            font-weight: 700;
        }}
        
        .arrow-flat {{
            color: #6b7280;
            font-weight: 700;
        }}
        
        /* Bullet lists */
        ul {{
            margin: 20px 0;
            padding-left: 0;
            list-style: none;
            text-align: center;
        }}
        
        li {{
            position: relative;
            padding: 12px 16px;
            margin-bottom: 8px;
            background: var(--light-gray);
            border-radius: 6px;
            color: var(--text-secondary);
            text-align: center;
        }}
        
        li::before {{
            content: none;
        }}
        
        .bullet-detail {{
            display: block;
            margin-top: 8px;
            font-size: 0.9rem;
            color: var(--text-secondary);
            line-height: 1.6;
        }}
        
        /* Footer */
        footer {{
            text-align: center;
            padding: 30px;
            color: var(--medium-gray);
            font-size: 0.9rem;
            border-top: 1px solid var(--border-color);
            margin-top: 40px;
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            body {{
                padding: 15px;
            }}
            
            header h1 {{
                font-size: 1.8rem;
            }}
            
            .helmet {{
                width: 50px;
                height: 50px;
            }}
            
            .header-content {{
                gap: 15px;
            }}
            
            .potw-container {{
                flex-direction: column;
            }}
            
            .potw-image-stack {{
                width: 100%;
                margin-bottom: 20px;
            }}
            
            .matchup-preview {{
                grid-template-columns: 1fr;
            }}
            
            nav {{
                gap: 5px;
            }}
            
            nav a {{
                font-size: 0.75rem;
                padding: 5px 8px;
            }}
            
            table {{
                font-size: 0.75rem;
            }}
            
            th, td {{
                padding: 8px 6px;
            }}
        }}
        
        /* Print styles */
        @media print {{
            body {{
                max-width: 100%;
                padding: 0;
            }}
            
            nav {{
                display: none;
            }}
            
            section {{
                page-break-inside: avoid;
            }}
            
            .matchup-header {{
                page-break-after: avoid;
            }}
            
            h2, h3, h4 {{
                page-break-after: avoid;
            }}
            
            table {{
                page-break-inside: avoid;
            }}
        }}
        
        /* ============================================
           DARK MODE SUPPORT
           Automatically applies when user's system
           or app is in dark mode
           ============================================ */
        @media (prefers-color-scheme: dark) {{
            :root {{
                --primary-blue: #5b9bd5;
                --accent-gold: #e6b93d;
                --light-gray: #2d2d2d;
                --medium-gray: #a0a0a0;
                --dark-gray: #e0e0e0;
                --text-primary: #f0f0f0;
                --text-secondary: #c0c0c0;
                --border-color: #404040;
                --card-bg: #252525;
                --body-bg: #1a1a1a;
            }}
            
            body {{
                background: var(--body-bg);
                color: var(--text-primary);
            }}
            
            /* Header */
            header {{
                border-bottom-color: var(--primary-blue);
            }}
            
            header h1 {{
                color: var(--primary-blue);
            }}
            
            /* Helmet images - make white background transparent in dark mode */
            .helmet {{
                background: var(--body-bg);
                border-radius: 6px;
                padding: 4px;
            }}
            
            /* Navigation */
            nav {{
                background: var(--light-gray);
            }}
            
            nav a {{
                color: var(--primary-blue);
            }}
            
            nav a:hover {{
                background: rgba(91, 155, 213, 0.2);
            }}
            
            /* Section headers */
            h2 {{
                color: var(--primary-blue);
                border-bottom-color: var(--accent-gold);
            }}
            
            h3 {{
                color: var(--dark-gray);
            }}
            
            h4 {{
                color: var(--primary-blue);
            }}
            
            /* Matchup headers */
            .matchup-header {{
                background: var(--card-bg);
                color: var(--text-primary);
                border-left-color: var(--primary-blue);
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            }}
            
            /* Stat lines */
            .stat-line {{
                background: var(--light-gray);
                color: var(--text-secondary);
            }}
            
            /* Betting tables */
            .betting-table {{
                background: var(--card-bg);
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            }}
            
            .betting-table th {{
                background: var(--light-gray);
                color: var(--text-primary);
            }}
            
            .betting-table td {{
                color: var(--text-primary);
                border-bottom-color: var(--border-color);
            }}
            
            /* Report cards */
            .report-card {{
                background: var(--card-bg);
                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            }}
            
            .report-card-header {{
                border-bottom-color: var(--border-color);
            }}
            
            .manager-name {{
                color: var(--text-primary);
            }}
            
            .report-card p {{
                color: var(--text-secondary);
            }}
            
            .report-card .stat-line {{
                background: var(--light-gray);
            }}
            
            /* POTW section */
            .potw-section {{
                background: var(--card-bg);
            }}
            
            .potw-name {{
                color: var(--accent-gold);
            }}
            
            .potw-stats {{
                background: var(--light-gray);
                color: var(--text-secondary);
            }}
            
            /* Tables */
            table {{
                background: var(--card-bg);
            }}
            
            th {{
                background: var(--light-gray);
                color: var(--text-primary);
            }}
            
            td {{
                color: var(--text-primary);
                border-bottom-color: var(--border-color);
            }}
            
            tr:hover {{
                background: rgba(91, 155, 213, 0.1);
            }}
            
            /* Bullet lists */
            ul {{
                background: var(--card-bg);
            }}
            
            li {{
                color: var(--text-secondary);
                border-bottom-color: var(--border-color);
            }}
            
            /* Links */
            a {{
                color: var(--primary-blue);
            }}
            
            /* Subsection headers */
            .subsection-header {{
                color: var(--primary-blue);
                border-bottom-color: var(--accent-gold);
            }}
            
            /* Paginated tables */
            .table-pagination {{
                background: var(--light-gray);
            }}
            
            .table-pagination button {{
                background: var(--card-bg);
                color: var(--text-primary);
                border-color: var(--border-color);
            }}
            
            .table-pagination button:hover {{
                background: var(--primary-blue);
                color: #fff;
            }}
            
            .table-pagination button.active {{
                background: var(--primary-blue);
                color: #fff;
            }}
            
            /* Tabs */
            .tab-bar {{
                background: var(--light-gray);
            }}
            
            .tab-btn {{
                color: var(--text-secondary);
            }}
            
            .tab-btn.active {{
                color: var(--primary-blue);
                border-bottom-color: var(--primary-blue);
            }}
            
            /* Section borders */
            section {{
                border-bottom-color: var(--border-color);
            }}
        }}
        
        {get_stats_corner_css() if stats_report else ""}
        {get_player_card_css() if stats_report else ""}
    </style>
</head>
<body>
    <header>
        <div class="header-content">
            {helmet_img}
            <div class="header-text">
                <h1>{title}</h1>
                <div class="subtitle">{subtitle}</div>
            </div>
            {helmet_img_right}
        </div>
    </header>
    
    <nav>
        {nav_links_html}
        <a href="javascript:void(0)" onclick="document.querySelector('.sc-rb-card')?.scrollIntoView({{behavior:'smooth'}})">Record Book</a>
    </nav>
    
    <main>
        {''.join(sections_html)}
    </main>
    
    <footer>
        <strong>End of Newsletter</strong><br>
        {LEAGUE_NAME}
    </footer>
    
    <script>
    function paginateTable(tableId, page) {{
        var container = document.getElementById(tableId);
        if (!container) return;
        
        // Show/hide rows
        var rows = container.querySelectorAll('tbody tr[data-page]');
        rows.forEach(function(row) {{
            row.style.display = row.getAttribute('data-page') == page ? '' : 'none';
        }});
        
        // Update active button
        var buttons = container.querySelectorAll('.page-btn');
        buttons.forEach(function(btn, idx) {{
            btn.classList.toggle('active', idx + 1 === page);
        }});
    }}
    </script>
    {get_stats_corner_js() if stats_report else ""}
    {_player_card_embed if stats_report else ""}
    {"<script>" + get_player_card_js() + "</script>" if stats_report else ""}
</body>
</html>'''
    
    return html


# -------------------------
# Main
# -------------------------

def build_newsletter_html(
    markdown_text: str,
    output_path: str,
    helmet_path: Optional[str] = None,
    potw_path: Optional[str] = None,
    podium_path: Optional[str] = None,
    stats_report_path: Optional[str] = None,
) -> str:
    """Build the HTML newsletter from markdown."""
    global _paginated_table_counter
    _paginated_table_counter = 0  # Reset for each newsletter build
    
    # Normalize all Unicode dash variants to standard ASCII for consistent parsing
    # Normalize all Unicode dash variants to standard ASCII for consistent parsing
    markdown_text = markdown_text.replace('\u2014', '--')  # em-dash to --
    markdown_text = markdown_text.replace('\u2013', '--')  # en-dash to --
    
    title, subtitle, sections = parse_newsletter(markdown_text)
    
    
    helmet_base64 = image_to_base64(helmet_path)
    potw_base64 = image_to_base64(potw_path)
    podium_base64 = image_to_base64(podium_path)
    
    # Load stats report for Stats Corner visualizations
    stats_report = None
    if stats_report_path and os.path.exists(stats_report_path):
        with open(stats_report_path, 'r', encoding='utf-8') as f:
            stats_report = json.load(f)
    
    # Determine data directories for player card builder
    # Stats report lives in output/ which is a child of the project root.
    # Resolve to absolute path first so relative paths work from any CWD.
    # Project structure (from PROJECTSTRUCTURE.md):
    #   project_root/
    #     config/     <- ROSTERS.json, RECORDS.json, TRADES.json, etc.
    #     data/       <- PLAYERLOG.xlsx, PLAYERLIST.xlsx
    #     data/historical/ <- HISTORICAL_PLAYERLOG.json, all_drafts.json, etc.
    #     output/     <- stats_report_weekN.json (this is where sr_path lives)
    sr_path = Path(stats_report_path).resolve() if stats_report_path else None
    
    if sr_path:
        sr_dir = sr_path.parent  # output/
        # The project root is the parent of output/
        project_root = sr_dir.parent
        
        data_dir = project_root / "data"
        config_dir = project_root / "config"
        historical_dir = project_root / "data" / "historical"
        
        # Validate that the expected directories exist
        if not data_dir.exists():
            print(f"  WARNING: Expected data dir not found: {data_dir}")
            print(f"  Player cards may have incomplete data.")
        if not config_dir.exists():
            print(f"  WARNING: Expected config dir not found: {config_dir}")
    else:
        data_dir = None
        config_dir = None
        historical_dir = None
    
    html = generate_html(
        title, subtitle, sections,
        helmet_base64, potw_base64, podium_base64,
        stats_report,
        data_dir=data_dir,
        config_dir=config_dir,
        historical_dir=historical_dir,
    )
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_path


def main():
    ap = argparse.ArgumentParser(description="Generate an HTML newsletter from a markdown draft.")
    ap.add_argument("--input", required=True, help="Path to the markdown draft.")
    ap.add_argument("--output", required=True, help="Output HTML path.")
    ap.add_argument("--helmet", default=None, help="Optional helmet/logo image.")
    ap.add_argument("--potw", default=None, help="Optional Player of the Week image.")
    ap.add_argument("--podium", default=None, help="Optional podium image for POTW section.")
    ap.add_argument("--stats-report", default=None, help="Path to stats_report_weekN.json for Stats Corner visualizations.")
    
    args = ap.parse_args()
    
    with open(args.input, "r", encoding="utf-8") as f:
        markdown_text = f.read()
    
    out = build_newsletter_html(
        markdown_text, args.output, args.helmet, args.potw, args.podium,
        stats_report_path=getattr(args, 'stats_report', None),
    )
    print(f"Built HTML newsletter: {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
