"""stats_corner_viz.py

Render Stats Corner visualizations as HTML blocks for the newsletter.

Each render function takes a dict from stats_report_weekN.json and returns
an HTML string ready to inject into the Stats Corner section.

Visualizations:
  1. Positional Scoring Breakdown (donut charts, 2x2 grid)
  2. Draft Value Tracker (tabbed diverging bar cards)
  3. Waiver Wire ROI (tabbed manager panels)
  4. Keeper Watch (tier board with manager summary strip)
"""

from __future__ import annotations
import json
import math
import os
from html import escape as _html_escape
from typing import Optional

from .data_loader import (
    MANAGERS, MANAGER_TO_TEAM, MANAGER_COLORS, PRE_DATA_ERA,
    CURRENT_SEASON, PLAYOFF_START_WEEK, TOTAL_WEEKS,
)


def _html(text) -> str:
    """Escape text for safe HTML insertion, preserving Unicode characters.

    Uses html.escape() for HTML-dangerous chars (<, >, &, quotes) while
    keeping accented/Unicode characters intact (Jokic, Doncic, etc.).
    """
    return _html_escape(str(text))


#  Manager metadata (from config via data_loader)
MANAGER_TEAMS = MANAGER_TO_TEAM
POSITION_COLORS = {
    "G": "#1F4E79",
    "F": "#C9A227",
    "C": "#5B8C5A",
}
VALUE_TIERS = {
    "Steal": {"label": "Steal", "bg": "#2e7d32", "color": "#fff"},
    "Good Value": {"label": "Good Value", "bg": "#66bb6a", "color": "#fff"},
    "Fair": {"label": "Fair", "bg": "#ffa726", "color": "#333"},
    "Bust": {"label": "Bust", "bg": "#c62828", "color": "#fff"},
    "Too Early": {"label": "Too Early", "bg": "#9e9e9e", "color": "#fff"},
}
KEEPER_TIER_ORDER = ["Lock", "Strong Hold", "Stash", "Sell High", "On the Bubble", "Dynasty Stash", "Waiver Wire"]

# Playoff weeks by season - playoffs are last 2 weeks of each season
# 19-20 had NO playoffs due to COVID
# Historical playoff weeks are hardcoded per season. For a new league, update
# or remove these. The current season's entry comes from league_config.json.
PLAYOFF_WEEKS = {
    '2017-18': [22, 23],
    '2018-19': [22, 23],
    '2019-20': None,  # No playoffs - COVID
    '2020-21': [17, 18],
    '2021-22': [21, 22],
    '2022-23': [22, 23],
    '2023-24': [22, 23],
    '2024-25': [22, 23],
    CURRENT_SEASON: [PLAYOFF_START_WEEK, TOTAL_WEEKS],
}

# Manager list and historical viz colors (from config)
MANAGERS_LIST = MANAGERS
# Historical viz uses distinct high-contrast palette for readability on dense grids
# Historical viz colors: use the canonical manager colors from config.
# (Previously used a hard-coded palette that swapped Hayden/Benton colors.)
MGR_COLORS_HIST = MANAGER_COLORS


# =====================================================================
# 1. POSITIONAL SCORING BREAKDOWN (Donut Charts)
# =====================================================================

def render_positional_breakdown(data: dict) -> str:
    """Render 2x2 donut chart grid showing G/F/C split per manager."""
    if not data or "managers" not in data:
        return ""

    managers = data["managers"]
    # Sort by total FP descending
    sorted_mgrs = sorted(managers.items(), key=lambda x: -x[1].get("total_fp", 0))

    cards_html = []
    for mgr, mdata in sorted_mgrs:
        total_fp = mdata.get("total_fp", 0)
        if total_fp == 0:
            continue

        # Calculate percentages and donut arcs
        positions = []
        for pos in ("G", "F", "C"):
            pdata = mdata.get(pos, {})
            fp = pdata.get("total_fp", 0)
            gp = pdata.get("gp", 0)
            fppg = pdata.get("fppg", 0)
            pct = (fp / total_fp * 100) if total_fp > 0 else 0
            positions.append({
                "pos": pos, "fp": fp, "gp": gp, "fppg": fppg, "pct": pct,
            })

        # Build SVG donut (r=44, circumference = 2*pi*44 = 276.46)
        circumference = 2 * math.pi * 44
        offset = 0
        circles = ""
        for p in positions:
            arc_len = circumference * p["pct"] / 100
            gap_len = circumference - arc_len
            circles += (
                f'<circle cx="60" cy="60" r="44" fill="none" '
                f'stroke="{POSITION_COLORS[p["pos"]]}" stroke-width="18" '
                f'stroke-dasharray="{arc_len:.1f} {gap_len:.1f}" '
                f'stroke-dashoffset="{-offset:.1f}" />\n'
            )
            offset += arc_len

        # Build stat rows
        stat_rows = ""
        total_gp = 0
        for p in positions:
            total_gp += p["gp"]
            color = POSITION_COLORS[p["pos"]]
            stat_rows += f'''
            <div class="sc-donut-stat">
              <div class="sc-ds-left">
                <div class="sc-ds-swatch" style="background: {color};"></div>
                <div class="sc-ds-pos">{p["pos"]}</div>
              </div>
              <div class="sc-ds-right">
                <div class="sc-ds-fp">{p["fp"]:,.0f}</div>
                <div class="sc-ds-fppg">{p["fppg"]:.1f} &middot; {p["gp"]}g</div>
                <div class="sc-ds-pct" style="color: {color};">{p["pct"]:.1f}%</div>
              </div>
            </div>'''
        
        # Calculate team FPPG
        team_fppg = (total_fp / total_gp) if total_gp > 0 else 0

        team = MANAGER_TEAMS.get(mgr, "")
        cards_html.append(f'''
        <div class="sc-donut-card">
          <div class="sc-donut-left">
            <div class="sc-donut-wrapper">
              <svg viewBox="0 0 120 120">
                {circles}
              </svg>
              <div class="sc-donut-center">
                <div class="sc-center-val">{total_fp:,.0f}</div>
                <div class="sc-center-lbl">Total FP</div>
              </div>
            </div>
            <div class="sc-donut-team-total">{team_fppg:.1f} FPPG &middot; {total_gp}g</div>
          </div>
          <div class="sc-donut-right">
            <div class="sc-donut-mgr">{mgr}</div>
            <div class="sc-donut-team">{team}</div>
            <div class="sc-donut-stats">{stat_rows}
            </div>
          </div>
        </div>''')

    legend = '''
    <div class="sc-pos-legend">
      <div class="sc-leg-item"><div class="sc-leg-swatch" style="background: #1F4E79;"></div> Guards</div>
      <div class="sc-leg-item"><div class="sc-leg-swatch" style="background: #C9A227;"></div> Forwards</div>
      <div class="sc-leg-item"><div class="sc-leg-swatch" style="background: #5B8C5A;"></div> Centers</div>
    </div>'''

    return f'''
    <div class="sc-viz-block">
      <h3 class="sc-viz-title">Positional Scoring Breakdown</h3>
      <div class="sc-viz-subtitle">Season Total Fantasy Points by Position</div>
      <div class="sc-donut-grid">
        {"".join(cards_html)}
      </div>
      {legend}
    </div>'''


# =====================================================================
# 2. DRAFT VALUE TRACKER (Tabbed Diverging Bars)
# =====================================================================

def render_draft_value_tracker(data: dict) -> str:
    """Render tabbed draft value tracker with diverging bar cards per manager."""
    if not data or "drafted" not in data:
        return ""

    drafted = data["drafted"]
    if not drafted:
        return ""

    # Group by manager
    by_manager = {}
    for p in drafted:
        mgr = p["manager"]
        if mgr not in by_manager:
            by_manager[mgr] = []
        by_manager[mgr].append(p)

    # Sort managers by avg delta descending
    mgr_order = sorted(
        by_manager.keys(),
        key=lambda m: sum(p["delta"] for p in by_manager[m]) / len(by_manager[m]),
        reverse=True,
    )

    panels_html = []
    tabs_html = []
    max_abs_delta = max(abs(p["delta"]) for p in drafted) if drafted else 1

    for idx, mgr in enumerate(mgr_order):
        players = by_manager[mgr]
        # Sort within manager by delta descending
        players.sort(key=lambda x: -x["delta"])

        color = MANAGER_COLORS.get(mgr, "#333")
        team = MANAGER_TEAMS.get(mgr, "")
        active = " sc-active" if idx == 0 else ""

        # Build player cards
        cards = []
        for p in players:
            delta = p["delta"]
            value = p.get("value", "Fair")
            tier = VALUE_TIERS.get(value, VALUE_TIERS["Fair"])

            # 4-way status: rostered (original team), traded, claimed (waiver), dropped
            status = p.get("status", "rostered")
            if status == "traded":
                status_cls = "sc-traded"
                status_txt = "Traded"
            elif status == "claimed":
                status_cls = "sc-claimed"
                status_txt = "Claimed"
            elif status == "dropped":
                status_cls = "sc-dropped"
                status_txt = "Dropped"
            else:
                status_cls = "sc-rostered"
                status_txt = "Rostered"

            bar_cls = "sc-bar-faded" if status not in ("rostered",) else ""

            # OFS tag
            ofs = p.get("out_for_season", False)
            ofs_tag = '<span class="sc-ofs-tag">OFS</span>' if ofs else ""

            # Bar width as % of max, capped at 50% of container
            bar_pct = min(abs(delta) / max_abs_delta * 50, 50) if max_abs_delta > 0 else 0
            bar_side = "left: 50%;" if delta >= 0 else "right: 50%;"
            delta_cls = "sc-pos" if delta > 0 else ("sc-neg" if delta < 0 else "sc-neutral")
            delta_sign = "+" if delta > 0 else ""

            cards.append(f'''
          <div class="sc-draft-entry">
            <div class="sc-de-top">
              <div>
                <div class="sc-de-player">{p["player_name"]}</div>
                <div class="sc-de-pick">R{p["round"]} Pick {p["pick"]}</div>
              </div>
              <div class="sc-de-tags">
                <span class="sc-tier-tag" style="background:{tier["bg"]};color:{tier["color"]};">{tier["label"]}</span>
                <span class="sc-status-tag {status_cls}">{status_txt}</span>
                {ofs_tag}
              </div>
            </div>
            <div class="sc-de-bar-row">
              <div class="sc-bar-container">
                <div class="sc-center-line"></div>
                <div class="sc-bar {bar_cls}" style="width:{bar_pct:.1f}%;{bar_side}background:{color};"></div>
              </div>
              <div class="sc-delta-value {delta_cls}">{delta_sign}{delta:.1f}</div>
            </div>
            <div class="sc-de-detail">Exp {p["expected_fppg"]:.1f} &rarr; Actual {p["actual_fppg"]:.1f} FPPG &middot; {p["gp"]} GP &middot; {p["total_fp"]:,.0f} FP</div>
          </div>''')

        avg_delta = sum(p["delta"] for p in players) / len(players)
        avg_cls = "sc-pos" if avg_delta > 0 else "sc-neg"
        avg_sign = "+" if avg_delta > 0 else ""

        panels_html.append(f'''
      <div class="sc-manager-panel{active}" id="sc-dv-panel-{mgr.lower()}">
        <div class="sc-panel-header">
          <div class="sc-panel-color-bar" style="background:{color};"></div>
          <div class="sc-panel-info">
            <div class="sc-panel-name">{mgr}</div>
            <div class="sc-panel-team">{team}</div>
          </div>
        </div>
        {"".join(cards)}
        <div class="sc-chart-axis"><span>&larr; Bust</span><span>Expected</span><span>Steal &rarr;</span></div>
        <div class="sc-panel-avg">Average &Delta;: <span class="{avg_cls}">{avg_sign}{avg_delta:.1f}</span> across {len(players)} picks</div>
      </div>''')

        tabs_html.append(
            f'<div class="sc-manager-tab{active}" onclick="scShowPanel(\'dv\',\'{mgr.lower()}\')" '
            f'id="sc-dv-tab-{mgr.lower()}">{mgr}</div>'
        )

    return f'''
    <div class="sc-viz-block" data-viz="draft-value">
      <h3 class="sc-viz-title">Draft Value Tracker</h3>
      <div class="sc-viz-subtitle">Drafted Players R1&ndash;7 &middot; Actual vs Expected FPPG</div>
      {"".join(panels_html)}
      <div class="sc-manager-tabs">{"".join(tabs_html)}</div>
    </div>'''


# =====================================================================
# 3. WAIVER WIRE ROI (Tabbed Manager Panels)
# =====================================================================

def render_waiver_roi(data: dict) -> str:
    """Render tabbed waiver ROI panels per manager."""
    if not data or "managers" not in data:
        return ""

    league_avg = data.get("league_waiver_fppg", 0)
    managers = data["managers"]

    # Sort by fppg_vs_avg descending
    mgr_order = sorted(
        managers.keys(),
        key=lambda m: managers[m].get("fppg_vs_avg", 0),
        reverse=True,
    )

    panels_html = []
    tabs_html = []

    for idx, mgr in enumerate(mgr_order):
        mdata = managers[mgr]
        color = MANAGER_COLORS.get(mgr, "#333")
        team = MANAGER_TEAMS.get(mgr, "")
        active = " sc-active" if idx == 0 else ""

        fppg = mdata.get("waiver_fppg", 0)
        vs_avg = mdata.get("fppg_vs_avg", 0)
        hit_rate = mdata.get("hit_rate", 0)
        bust_rate = mdata.get("bust_rate", 0)
        meh_rate = max(0, 100 - hit_rate - bust_rate)
        adds = mdata.get("total_adds", 0)
        share = mdata.get("waiver_share", 0)

        fppg_cls = "sc-pos" if vs_avg >= 0 else "sc-neg"
        vs_sign = "+" if vs_avg >= 0 else ""

        # Notable pickups (top 3 adds by total FP, deduplicated by player name)
        adds_list = mdata.get("adds", [])
        seen_players = set()
        unique_adds = []
        for a in sorted(adds_list, key=lambda a: -a.get("total_fp", 0)):
            if a.get("player_name") not in seen_players:
                seen_players.add(a.get("player_name"))
                unique_adds.append(a)
        top_adds = unique_adds[:3]
        pickup_rows = ""
        for a in top_adds:
            afppg = a.get("fppg", 0)
            verdict = "Hit" if afppg >= league_avg else ("Bust" if afppg < 25 else "Meh")
            v_cls = "sc-good" if verdict == "Hit" else ("sc-bad" if verdict == "Bust" else "")
            pickup_rows += f'''
            <tr>
              <td class="sc-player-name">{a.get("player_name", "")}</td>
              <td class="{v_cls}">{a.get("total_fp", 0):,.0f}</td>
              <td>{afppg:.1f}</td>
              <td>{a.get("total_games", 0)}</td>
              <td><span class="{v_cls}">{verdict}</span></td>
            </tr>'''

        # Callout cards
        best = mdata.get("best_add", {})
        regret = mdata.get("biggest_loss", {})

        best_html = ""
        if best:
            best_html = f'''
          <div class="sc-callout-card sc-best">
            <div class="sc-tcc-label">Best Pickup</div>
            <div class="sc-tcc-player">{best.get("player_name", "N/A")}</div>
            <div class="sc-tcc-detail">{best.get("total_fp", 0):,.0f} FP &middot; {best.get("fppg", 0):.1f} FPPG across {best.get("total_games", 0)} games</div>
          </div>'''

        regret_html = ""
        if regret:
            regret_html = f'''
          <div class="sc-callout-card sc-regret">
            <div class="sc-tcc-label">Biggest Regret</div>
            <div class="sc-tcc-player">{regret.get("player_name", "N/A")}</div>
            <div class="sc-tcc-detail">Dropped &rarr; {regret.get("picked_up_by", "?")} &middot; {regret.get("new_team_fp", 0):,.0f} FP, {regret.get("new_team_fppg", 0):.1f} FPPG since</div>
          </div>'''

        panels_html.append(f'''
      <div class="sc-manager-panel{active}" id="sc-wr-panel-{mgr.lower()}">
        <div class="sc-panel-header">
          <div class="sc-panel-color-bar" style="background:{color};"></div>
          <div class="sc-panel-info">
            <div class="sc-panel-name">{mgr}</div>
            <div class="sc-panel-team">{team}</div>
          </div>
        </div>
        <div class="sc-stats-row">
          <div class="sc-stat"><div class="sc-ts-val">{adds}</div><div class="sc-ts-lbl">Adds</div></div>
          <div class="sc-stat"><div class="sc-ts-val {fppg_cls}">{fppg:.1f}</div><div class="sc-ts-lbl">FPPG</div></div>
          <div class="sc-stat"><div class="sc-ts-val {fppg_cls}">{vs_sign}{vs_avg:.1f}</div><div class="sc-ts-lbl">vs Avg</div></div>
          <div class="sc-stat"><div class="sc-ts-val">{hit_rate:.0f}%</div><div class="sc-ts-lbl">Hit Rate</div></div>
          <div class="sc-stat"><div class="sc-ts-val">{share:.0f}%</div><div class="sc-ts-lbl">WVR Share</div></div>
        </div>
        <div class="sc-hitbust">
          <div class="sc-hb-bar">
            <div class="sc-hb-hit" style="width:{hit_rate:.0f}%;"></div>
            <div class="sc-hb-mid" style="width:{meh_rate:.0f}%;"></div>
            <div class="sc-hb-bust" style="width:{bust_rate:.0f}%;"></div>
          </div>
          <div class="sc-hb-labels">
            <span class="sc-hb-l-hit">{hit_rate:.0f}% Hit</span>
            <span class="sc-hb-l-mid">{meh_rate:.0f}% Meh</span>
            <span class="sc-hb-l-bust">{bust_rate:.0f}% Bust</span>
          </div>
        </div>
        <div class="sc-pickups-title">Notable Pickups</div>
        <table class="sc-pickup-table">
          <thead><tr><th>Player</th><th>Total FP</th><th>FPPG</th><th>GP</th><th>Verdict</th></tr></thead>
          <tbody>{pickup_rows}</tbody>
        </table>
        <div class="sc-callouts">{best_html}{regret_html}</div>
      </div>''')

        tabs_html.append(
            f'<div class="sc-manager-tab{active}" onclick="scShowPanel(\'wr\',\'{mgr.lower()}\')" '
            f'id="sc-wr-tab-{mgr.lower()}">{mgr}</div>'
        )

    return f'''
    <div class="sc-viz-block" data-viz="waiver-roi">
      <h3 class="sc-viz-title">Season Waiver Wire ROI</h3>
      <div class="sc-viz-subtitle">League Avg: {league_avg:.1f} FPPG</div>
      {"".join(panels_html)}
      <div class="sc-manager-tabs">{"".join(tabs_html)}</div>
    </div>'''


# =====================================================================
# 4. KEEPER WATCH (Tier Board)
# =====================================================================

def render_keeper_watch(data: dict, player_cards: list = None) -> str:
    """Render keeper watch tier board with manager summary strip."""
    if not data or "players" not in data:
        return ""

    players = data["players"]
    if not players:
        return ""

    # Build player card lookup by name (for rank, archetype, career)
    pc_lookup = {}
    if player_cards:
        for c in player_cards:
            pc_lookup[c["player_name"]] = c

    # Get top 8 per manager
    by_manager = {}
    for p in players:
        mgr = p["manager"]
        if mgr not in by_manager:
            by_manager[mgr] = []
        by_manager[mgr].append(p)

    # Include all non-Drop players (Drop tier is the noise filter)
    top_players = [p for p in players if p.get("keeper_tier", "Drop") != "Drop"]

    # Build manager summary strip
    summary_cards = []
    for mgr in sorted(MANAGER_COLORS.keys()):
        mgr_players = [p for p in top_players if p["manager"] == mgr]
        tier_counts = {}
        for p in mgr_players:
            t = p.get("keeper_tier", "On the Bubble")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        # Avg age of top 6
        top6 = sorted(mgr_players, key=lambda x: -x["season_fppg"])[:6]
        ages = [p["age"] for p in top6 if p.get("age")]
        avg_age = sum(ages) / len(ages) if ages else 0

        color = MANAGER_COLORS.get(mgr, "#333")
        team = MANAGER_TEAMS.get(mgr, "")

        tier_pills = ""
        for tier_name, pill_color, pill_bg in [
            ("Lock", "#fff", "#2e7d32"),
            ("Strong Hold", "#fff", "#1F4E79"),
            ("Stash", "#fff", "#7b1fa2"),
            ("Sell High", "#333", "#ffa726"),
            ("On the Bubble", "#333", "#e0e0e0"),
            ("Dynasty Stash", "#fff", "#0288d1"),
            ("Waiver Wire", "#333", "#b0bec5"),
        ]:
            count = tier_counts.get(tier_name, 0)
            if count > 0:
                tier_pills += (
                    f'<span class="sc-kw-pill" style="background:{pill_bg};color:{pill_color};">'
                    f'{count} {tier_name.split()[0]}</span>'
                )

        summary_cards.append(f'''
        <div class="sc-kw-summary-card sc-kw-filter-btn" data-manager="{mgr}" style="border-top: 3px solid {color};" onclick="filterKeeperWatch('{mgr}')">
          <div class="sc-kw-mgr-name">{mgr}</div>
          <div class="sc-kw-mgr-team">{team}</div>
          <div class="sc-kw-pills">{tier_pills}</div>
          <div class="sc-kw-avg-age">Avg Age (Top 6): {avg_age:.1f}</div>
        </div>''')

    # Build tier sections
    tier_sections = []
    for tier in KEEPER_TIER_ORDER:
        tier_players = [p for p in top_players if p.get("keeper_tier") == tier]
        # Sort by keepability score descending within each tier
        tier_players.sort(key=lambda x: -x.get("keepability_score", 0))

        if not tier_players:
            continue

        chips = []
        for p in tier_players:
            color = MANAGER_COLORS.get(p["manager"], "#333")
            age_str = str(p["age"]) if p.get("age") else "?"
            ofs = p.get("out_for_season", False)
            ofs_badge = ' <span class="sc-kw-ofs">OFS</span>' if ofs else ""
            inj = p.get("injured", False) and not ofs
            inj_badge = ' <span class="sc-kw-inj">INJ</span>' if inj else ""

            # Primary stat: FPPG + proj delta
            if ofs and p.get("season_gp", 0) == 0:
                main_stat = f'{p["proj_fppg"]:.1f}'
                stat_label = "Proj FPPG"
                proj_html = ""
            else:
                main_stat = f'{p["season_fppg"]:.1f}'
                stat_label = "FPPG"
                delta = p["season_fppg"] - p["proj_fppg"] if p.get("proj_fppg") else 0
                delta_cls = "sc-pos" if delta >= 0 else "sc-neg"
                delta_sign = "+" if delta >= 0 else ""
                proj_html = (
                    f'<span class="sc-kw-stat-proj">Proj {p["proj_fppg"]:.1f}</span>'
                    f'<span class="sc-kw-stat-delta {delta_cls}">{delta_sign}{delta:.1f}</span>'
                )

            name_js = p["player_name"].replace("\\", "\\\\").replace("'", "\\x27").replace('"', '\\"')

            # Pull archetype from player cards if available
            pc = pc_lookup.get(p["player_name"])
            arch_html = ""
            if pc:
                archetype = pc.get("archetype", "")
                if archetype:
                    arch_html = f'<div class="sc-kw-chip-arch">{archetype}</div>'

            chips.append(f'''
          <div class="sc-kw-chip" data-manager="{p["manager"]}" style="border-left: 4px solid {color}; cursor:pointer;" onclick="pcOpen('{name_js}')">
            <div class="sc-kw-chip-top">
              <div class="sc-kw-chip-name">{p["player_name"]}{ofs_badge}{inj_badge}</div>
            </div>
            <div class="sc-kw-chip-meta">{p.get("pos_group", "?")} &middot; Age {age_str}</div>
            <div class="sc-kw-chip-stats">
              <span class="sc-kw-stat-main">{main_stat}</span>
              <span class="sc-kw-stat-label">{stat_label}</span>
              {proj_html}
            </div>
            {arch_html}
          </div>''')

        tier_descs = {
            "Lock": "Untouchable -- top 10-15 asset",
            "Strong Hold": "Probable keeper, possible minor concerns (availability, age)",
            "Stash": "Out for season but high projected value on return",
            "Sell High": "Producing now but aging out -- trade window open",
            "On the Bubble": "Borderline keeper / could go either way",
            "Dynasty Stash": "Young upside gamble -- smaller sample size, but the ceiling is real",
            "Waiver Wire": "Rosterable streaming piece -- not yet keeper material",
        }
        desc = tier_descs.get(tier, "")
        desc_html = f'<div class="sc-kw-tier-desc">{desc}</div>' if desc else ""

        tier_sections.append(f'''
      <div class="sc-kw-tier-section">
        <div class="sc-kw-tier-header">{tier} <span class="sc-kw-tier-count">({len(tier_players)})</span></div>
        {desc_html}
        <div class="sc-kw-tier-players">{"".join(chips)}</div>
      </div>''')

    return f'''
    <div class="sc-viz-block" data-viz="keeper-watch">
      <h3 class="sc-viz-title">Keeper Watch</h3>
      <div class="sc-viz-subtitle">Tier Assignments &amp; Projections &middot; Click a manager to filter</div>
      <div class="sc-kw-summary-grid">{"".join(summary_cards)}</div>
      <button class="sc-kw-reset-btn" onclick="resetKeeperWatch()">Show All Players</button>
      {"".join(tier_sections)}
    </div>'''


# =====================================================================
# ORCHESTRATOR
# =====================================================================

"""
render_record_book() -- ADD to stats_corner_viz.py

Add this function after render_keeper_watch() and before render_stats_corner_visualizations().
Also add the CSS block to get_stats_corner_css() and update the orchestrator.
"""


# =====================================================================
# 5. LEAGUE RECORD BOOK
# =====================================================================

def _load_matchups() -> list:
    """Load all_matchups.json from data/historical/ directory."""
    # Get project root from module location (modules/ -> project root)
    module_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(module_dir)
    
    paths_to_try = [
        # Correct path per PROJECTSTRUCTURE.md: data/historical/all_matchups.json
        os.path.join(project_root, 'data', 'historical', 'all_matchups.json'),
        # Claude Projects shows files flat, so also check root
        '/mnt/project/all_matchups.json',
    ]
    for path in paths_to_try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    return []


def _compute_regular_season_records() -> dict:
    """
    Compute regular season records (excluding playoff weeks) for each manager/season.
    
    Returns:
        dict: {season: {manager: {'wins': int, 'losses': int, 'record': str}}}
    """
    matchups = _load_matchups()
    if not matchups:
        return {}
    
    records = {}
    for season in sorted(set(m['season'] for m in matchups)):
        season_matches = [m for m in matchups if m['season'] == season]
        pweeks = PLAYOFF_WEEKS.get(season)
        
        # Filter to regular season only
        if pweeks:
            reg_matches = [m for m in season_matches if m['week'] not in pweeks]
        else:
            reg_matches = season_matches
        
        records[season] = {}
        for mgr in MANAGERS_LIST:
            wins = sum(1 for m in reg_matches if m['winner'] == mgr)
            losses = sum(1 for m in reg_matches if m['loser'] == mgr)
            records[season][mgr] = {
                'wins': wins, 
                'losses': losses, 
                'record': f"{wins}-{losses}"
            }
    
    return records


def _compute_playoff_results() -> dict:
    """
    Compute playoff results for each manager/season.
    
    Playoff format:
    - Semifinal (week 1 of playoffs): 4 teams, 2 games
    - Finals (week 2 of playoffs): Championship (semi winners), Consolation (semi losers)
    
    Returns:
        dict: {season: {manager: '1st'|'2nd'|'3rd'|'4th'|None}}
    """
    matchups = _load_matchups()
    if not matchups:
        return {}
    
    results = {}
    for season in sorted(set(m['season'] for m in matchups)):
        pweeks = PLAYOFF_WEEKS.get(season)
        if not pweeks:
            # No playoffs this season
            results[season] = {mgr: None for mgr in MANAGERS_LIST}
            continue
        
        season_matches = [m for m in matchups if m['season'] == season]
        semi_week, final_week = pweeks
        
        # Get semifinal results
        semi_matches = [m for m in season_matches if m['week'] == semi_week]
        semi_winners = [m['winner'] for m in semi_matches]
        semi_losers = [m['loser'] for m in semi_matches]
        
        # Get finals results
        final_matches = [m for m in season_matches if m['week'] == final_week]
        
        results[season] = {}
        for match in final_matches:
            winner = match['winner']
            loser = match['loser']
            
            if winner in semi_winners and loser in semi_winners:
                # Championship game
                results[season][winner] = '1st'
                results[season][loser] = '2nd'
            elif winner in semi_losers and loser in semi_losers:
                # Consolation game
                results[season][winner] = '3rd'
                results[season][loser] = '4th'
    
    return results


def _render_historical_standings_grid(historical_luck: dict) -> str:
    """
    Render Historical League Standings as a season-by-season grid.
    
    IMPORTANT: This shows REGULAR SEASON ONLY records (excluding playoffs).
    Data is computed from all_matchups.json directly.
    
    Args:
        historical_luck: dict passed in (kept for API consistency)
    
    Returns:
        HTML string for the standings grid
    """
    # Compute regular season records from matchups
    reg_records = _compute_regular_season_records()
    if not reg_records:
        return ""
    
    seasons = sorted(reg_records.keys())
    if not seasons:
        return ""
    
    # Rank managers within each season by wins
    standings = {}  # {season: {manager: {rank, record}}}
    for season in seasons:
        season_data = reg_records[season]
        ranked = sorted(
            [(mgr, data['wins'], data['record']) for mgr, data in season_data.items()],
            key=lambda x: -x[1]  # Sort by wins descending
        )
        standings[season] = {}
        for i, (mgr, wins, record) in enumerate(ranked):
            standings[season][mgr] = {"rank": i + 1, "record": record}
    
    # Shorten season labels: "2017-18" -> "17-18"
    def short_season(s):
        return s[2:]
    
    # Build header row
    header_cells = ['<th class="sc-hist-th sc-hist-th-mgr">MANAGER</th>']
    for s in seasons:
        current_class = " sc-hist-current" if s == seasons[-1] else ""
        header_cells.append(f'<th class="sc-hist-th sc-hist-th-season{current_class}">{short_season(s)}</th>')
    header_cells.append(
        '<th class="sc-hist-th sc-hist-th-summary">1st</th>'
        '<th class="sc-hist-th sc-hist-th-summary">2nd</th>'
        '<th class="sc-hist-th sc-hist-th-summary">3rd</th>'
    )
    
    # Build data rows
    rows = []
    for mgr in MANAGERS_LIST:
        color = MGR_COLORS_HIST.get(mgr, "#888")
        cells = [f'<td class="sc-hist-td sc-hist-td-mgr" style="color:{color}">{_html(mgr)}</td>']
        
        firsts = seconds = thirds = 0
        for s in seasons:
            info = standings.get(s, {}).get(mgr)
            current_class = " sc-hist-current" if s == seasons[-1] else ""
            if info:
                rank = info["rank"]
                record = info["record"]
                if rank == 1:
                    firsts += 1
                    cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-1st">{record}</span></td>')
                elif rank == 2:
                    seconds += 1
                    cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-2nd">{record}</span></td>')
                elif rank == 3:
                    thirds += 1
                    cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-3rd">{record}</span></td>')
                else:
                    cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-4th">{record}</span></td>')
            else:
                cells.append(f'<td class="sc-hist-td{current_class}">-</td>')
        
        # Summary columns (add pre-data-era finishes not in data)
        pre_era_firsts = PRE_DATA_ERA.get("first_place_finishes", {})
        firsts += pre_era_firsts.get(mgr, 0)
        
        cells.append(
            f'<td class="sc-hist-td sc-hist-td-sum sc-hist-sum-1st">{firsts}</td>'
            f'<td class="sc-hist-td sc-hist-td-sum sc-hist-sum-2nd">{seconds}</td>'
            f'<td class="sc-hist-td sc-hist-td-sum sc-hist-sum-3rd">{thirds}</td>'
        )
        rows.append(f'<tr class="sc-hist-row">{"".join(cells)}</tr>')
    
    # Note: Title no longer says "(All Seasons)" - it's implied
    return f'''
    <div class="sc-mgr-section-header">Historical League Standings</div>
    <div class="sc-hist-wrapper">
      <table class="sc-hist-table">
        <thead>
          <tr class="sc-hist-header-row">
            {"".join(header_cells)}
          </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>'''


def _render_historical_playoff_results_grid(historical_luck: dict = None) -> str:
    """
    Render Historical Playoff Results as a season-by-season grid.
    
    Shows 1st/2nd/3rd/4th placement with gold/silver/bronze backgrounds.
    Handles 2019-20 having no playoffs due to COVID.
    
    Args:
        historical_luck: dict passed in (unused, kept for API consistency)
    
    Returns:
        HTML string for the playoff results grid
    """
    playoff_results = _compute_playoff_results()
    if not playoff_results:
        return ""
    
    seasons = sorted(playoff_results.keys())
    if not seasons:
        return ""
    
    def short_season(s):
        return s[2:]
    
    # Build header row
    header_cells = ['<th class="sc-hist-th sc-hist-th-mgr">MANAGER</th>']
    for s in seasons:
        current_class = " sc-hist-current" if s == seasons[-1] else ""
        header_cells.append(f'<th class="sc-hist-th sc-hist-th-season{current_class}">{short_season(s)}</th>')
    # Summary column: Championship wins (1st place finishes)
    header_cells.append(
        '<th class="sc-hist-th sc-hist-th-summary">&#127942;</th>'  # Trophy emoji for titles
    )
    
    # Build data rows
    rows = []
    for mgr in MANAGERS_LIST:
        color = MGR_COLORS_HIST.get(mgr, "#888")
        cells = [f'<td class="sc-hist-td sc-hist-td-mgr" style="color:{color}">{_html(mgr)}</td>']
        
        titles = 0
        for s in seasons:
            result = playoff_results.get(s, {}).get(mgr)
            current_class = " sc-hist-current" if s == seasons[-1] else ""
            
            if result is None:
                # No playoffs this season (COVID)
                cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-no-playoffs">--</span></td>')
            elif result == '1st':
                titles += 1
                cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-1st">1st</span></td>')
            elif result == '2nd':
                cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-2nd">2nd</span></td>')
            elif result == '3rd':
                cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-3rd">3rd</span></td>')
            elif result == '4th':
                cells.append(f'<td class="sc-hist-td{current_class}"><span class="sc-hist-place sc-hist-4th">4th</span></td>')
            else:
                cells.append(f'<td class="sc-hist-td{current_class}">-</td>')
        
        # Summary column: total titles (add pre-data-era championships)
        pre_era_titles = PRE_DATA_ERA.get("titles", {})
        titles += pre_era_titles.get(mgr, 0)
        
        cells.append(f'<td class="sc-hist-td sc-hist-td-sum sc-hist-sum-1st">{titles}</td>')
        rows.append(f'<tr class="sc-hist-row">{"".join(cells)}</tr>')
    
    return f'''
    <div class="sc-mgr-section-header">Historical Playoff Results</div>
    <div class="sc-hist-wrapper">
      <table class="sc-hist-table">
        <thead>
          <tr class="sc-hist-header-row">
            {"".join(header_cells)}
          </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>'''


def _render_luck_index_grid(historical_luck: dict) -> str:
    """Render Historical Luck Index as a season-by-season grid (manager rows x season columns)."""
    mgrs_data = historical_luck.get("managers", {})
    if not mgrs_data:
        return ""

    # Collect all seasons
    all_seasons = set()
    for mdata in mgrs_data.values():
        for s in mdata.get("seasons", []):
            all_seasons.add(s["season"])
    seasons = sorted(all_seasons)

    if not seasons:
        return ""

    # Build luck lookup: {season: {manager: luck_index}}
    luck_lookup = {}
    for name, mdata in mgrs_data.items():
        for s in mdata.get("seasons", []):
            luck_lookup.setdefault(s["season"], {})[name] = s.get("luck_index", 0)

    managers = MANAGERS_LIST
    mgr_colors = MGR_COLORS_HIST

    def luck_class(val):
        # Thresholds calibrated to the all-play expected-wins scale.
        # Season luck typically ranges ~-3 to +4; Pythagorean used ~-5 to +5.
        if val <= -2: return "sc-luck-very-bad"
        elif val <= -1: return "sc-luck-bad"
        elif val < 1: return "sc-luck-neutral"
        elif val < 2: return "sc-luck-good"
        else: return "sc-luck-very-good"

    def short_season(s):
        return s[2:]

    # Header
    header_cells = ['<th class="sc-hist-th sc-hist-th-mgr">MANAGER</th>']
    for s in seasons:
        current_class = " sc-hist-current" if s == seasons[-1] else ""
        header_cells.append(f'<th class="sc-hist-th sc-hist-th-season{current_class}">{short_season(s)}</th>')
    header_cells.append('<th class="sc-hist-th sc-hist-th-summary">CAREER</th>')

    # Build rows
    rows = []
    for mgr in managers:
        color = mgr_colors.get(mgr, "#888")
        cells = [f'<td class="sc-hist-td sc-hist-td-mgr" style="color:{color}">{_html(mgr)}</td>']

        for s in seasons:
            luck_val = luck_lookup.get(s, {}).get(mgr)
            current_class = " sc-hist-current" if s == seasons[-1] else ""
            if luck_val is not None:
                sign = "+" if luck_val > 0 else ""
                lclass = luck_class(luck_val)
                cells.append(
                    f'<td class="sc-hist-td{current_class}">'
                    f'<span class="sc-luck-val {lclass}">{sign}{luck_val:.1f}</span></td>'
                )
            else:
                cells.append(f'<td class="sc-hist-td{current_class}">-</td>')

        # Career total
        career_luck = mgrs_data.get(mgr, {}).get("career_luck", 0)
        sign = "+" if career_luck > 0 else ""
        lclass = luck_class(career_luck)
        cells.append(f'<td class="sc-hist-td sc-hist-td-career"><span class="sc-luck-val sc-luck-career {lclass}">{sign}{career_luck:.1f}</span></td>')
        rows.append(f'<tr class="sc-hist-row">{"".join(cells)}</tr>')

    # Legend
    legend = '''
    <div class="sc-luck-legend">
      <span class="sc-luck-legend-item"><span class="sc-luck-swatch sc-luck-swatch-good"></span>Lucky (won more than projected)</span>
      <span class="sc-luck-legend-item"><span class="sc-luck-swatch sc-luck-swatch-bad"></span>Unlucky (won fewer than projected)</span>
    </div>'''

    return f'''
    <div class="sc-mgr-section-header">Historical Luck Index</div>
    <div class="sc-hist-wrapper">
      <table class="sc-hist-table">
        <thead>
          <tr class="sc-hist-header-row">
            {"".join(header_cells)}
          </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    {legend}'''


def render_record_book(data: dict, historical_luck: dict = None) -> str:
    """
    Render the League Record Book with tabbed navigation.

    5 tabs: Team | Players | Rookies | Draft & Trades | Manager
    Each tab contains top-5 leaderboards. Highlights current-season entries
    with gold tint and shows NEW! badge when current season holds #1.

    Args:
        data: record_book dict from stats_report with keys:
              team_records, player_records, rookie_records,
              draft_records, manager_milestones, manager_records

    Returns:
        HTML string for the record book card.
    """
    if not data:
        return ""

    team_records = data.get("team_records", [])
    player_records = data.get("player_records", [])
    rookie_records = data.get("rookie_records", [])
    draft_records = data.get("draft_records", [])
    milestones = data.get("manager_milestones", [])
    manager_records = data.get("manager_records", [])

    if not any([team_records, player_records, milestones]):
        return ""

    # ---- Build tab definitions ----
    # Each: (slug, label, has_content)
    # Manager tab first (default active tab)
    tab_defs = [
        ("manager", "Manager", bool(milestones) or bool(manager_records)),
        ("team", "Team", bool(team_records)),
        ("players", "Players", bool(player_records)),
        ("rookies", "Rookies", bool(rookie_records)),
        ("drafttrades", "Draft & Trades", bool(draft_records)),
    ]

    # Find first tab with content for default active
    first_active = next((slug for slug, _, has in tab_defs if has), "team")

    # ---- Render tab bar ----
    tab_btns = []
    for slug, label, _has in tab_defs:
        active = " sc-active" if slug == first_active else ""
        tab_btns.append(
            f'<div class="sc-rb-tab{active}" '
            f"onclick=\"scShowPanel('rb','{slug}')\" "
            f'id="sc-rb-tab-{slug}">{label}</div>'
        )
    tab_bar = f'<div class="sc-rb-tabs">{"".join(tab_btns)}</div>'

    # ---- Render tab panels ----
    panels = []

    # TEAM panel
    team_content = _render_record_section(team_records, "team")
    active_cls = " sc-active" if first_active == "team" else ""
    panels.append(
        f'<div class="sc-manager-panel{active_cls}" id="sc-rb-panel-team">'
        f'{team_content}</div>'
    )

    # PLAYERS panel
    player_content = _render_record_section(player_records, "player")
    active_cls = " sc-active" if first_active == "players" else ""
    panels.append(
        f'<div class="sc-manager-panel{active_cls}" id="sc-rb-panel-players">'
        f'{player_content}</div>'
    )

    # ROOKIES panel
    rookie_content = _render_record_section(rookie_records, "player")
    active_cls = " sc-active" if first_active == "rookies" else ""
    panels.append(
        f'<div class="sc-manager-panel{active_cls}" id="sc-rb-panel-rookies">'
        f'{rookie_content}</div>'
    )

    # DRAFT & TRADES panel
    draft_content = _render_record_section(draft_records, "player")
    active_cls = " sc-active" if first_active == "drafttrades" else ""
    panels.append(
        f'<div class="sc-manager-panel{active_cls}" id="sc-rb-panel-drafttrades">'
        f'{draft_content}</div>'
    )

    # MANAGER panel (milestones + H2H + luck index + manager records)
    mgr_parts = []
    if milestones:
        mgr_parts.append(_render_milestones(milestones))
    h2h = data.get("head_to_head", {})
    if h2h and h2h.get("managers"):
        mgr_parts.append(_render_h2h_matrix(h2h))
    # Historical standings (regular season only) and playoff results
    if historical_luck and historical_luck.get("managers"):
        mgr_parts.append(_render_historical_standings_grid(historical_luck))
        mgr_parts.append(_render_historical_playoff_results_grid(historical_luck))
        mgr_parts.append(_render_luck_index_grid(historical_luck))
    if manager_records:
        mgr_parts.append('<div class="sc-mgr-section-header">Season Records</div>')
        mgr_parts.append('<div class="sc-mgr-section-subtitle"><em>Regular Season + Playoffs</em></div>')
        mgr_parts.append(_render_record_section(manager_records, "team"))
    mgr_content = "".join(mgr_parts) if mgr_parts else (
        '<div class="sc-rb-placeholder">Awaiting data</div>'
    )
    active_cls = " sc-active" if first_active == "manager" else ""
    panels.append(
        f'<div class="sc-manager-panel{active_cls}" id="sc-rb-panel-manager">'
        f'{mgr_content}</div>'
    )

    return f'''
    <div class="sc-viz-block sc-rb-card">
      <h3 class="sc-viz-title sc-rb-title">
        <span class="sc-rb-trophy" style="color:#FFD700;">&#127942;</span> League Record Book
      </h3>
      {tab_bar}
      {"".join(panels)}
    </div>'''


def _render_record_section(records: list, entry_type: str) -> str:
    """Render a list of record leaderboards for a tab panel."""
    if not records:
        return '<div class="sc-rb-placeholder">Awaiting historical data</div>'

    lbs = []
    for rec in records:
        lbs.append(_render_leaderboard(
            title=rec["record"],
            entries=rec.get("entries", [])[:10],
            is_new_record=rec.get("is_new_record", False),
            entry_type=entry_type,
            unit=rec.get("unit", ""),
            note=rec.get("note", ""),
        ))
    return "".join(lbs)


def _render_milestones(milestones: list) -> str:
    """Render Manager Profile Cards -- mobile-first stacking layout."""
    cards = []
    rank_labels = ["1st", "2nd", "3rd", "4th"]

    for i, m in enumerate(milestones[:4]):
        rank = rank_labels[i] if i < len(rank_labels) else f"{i+1}th"
        wins = m.get("career_wins", 0)
        losses = m.get("career_losses", 0)
        pct = m.get("win_pct", 0)
        pts = m.get("career_points", 0)
        titles = m.get("titles", 0)
        title_str = f"{titles} title{'s' if titles != 1 else ''}" if titles else "0 titles"

        # Franchise player detail
        fp_name = m.get("franchise_player", "")
        fp_fp = m.get("franchise_player_fp", 0)
        fp_gp = m.get("franchise_gp", 0)
        fp_seasons = m.get("franchise_seasons", 0)
        fp_fppg = m.get("franchise_fppg", 0)

        franchise_html = ""
        if fp_name and fp_fp:
            detail_parts = []
            if fp_gp:
                detail_parts.append(f"{fp_gp} GP")
            if fp_seasons:
                detail_parts.append(f"{fp_seasons} seasons")
            if fp_fppg:
                detail_parts.append(f"{fp_fppg} FPPG")
            detail_str = " * ".join(detail_parts)
            franchise_html = f'''
              <div class="sc-mgr-franchise">
                <div class="sc-mgr-franchise-label">Franchise Player</div>
                <div class="sc-mgr-franchise-name">{_html(fp_name)}</div>
                <div class="sc-mgr-franchise-stat">{fp_fp:,.1f} FP</div>
                <div class="sc-mgr-franchise-detail">{_html(detail_str)}</div>
              </div>'''

        is_leader = i == 0
        card_cls = "sc-mgr-card sc-mgr-leader" if is_leader else "sc-mgr-card"

        cards.append(f'''
          <div class="{card_cls}">
            <div class="sc-mgr-header">
              <span class="sc-mgr-name">{_html(m["manager"])}</span>
              <span class="sc-mgr-rank-badge">{rank}</span>
            </div>
            <div class="sc-mgr-stats">
              <div class="sc-mgr-stat-item">
                <span class="sc-mgr-stat-val">{wins}-{losses}</span>
                <span class="sc-mgr-stat-label">Record</span>
              </div>
              <div class="sc-mgr-stat-item">
                <span class="sc-mgr-stat-val">{pct:.1f}%</span>
                <span class="sc-mgr-stat-label">Win %</span>
              </div>
              <div class="sc-mgr-stat-item">
                <span class="sc-mgr-stat-val">{_format_career_points(pts)}</span>
                <span class="sc-mgr-stat-label">Career FP</span>
              </div>
              <div class="sc-mgr-stat-item">
                <span class="sc-mgr-stat-val">{title_str}</span>
                <span class="sc-mgr-stat-label">&nbsp;</span>
              </div>
            </div>
            {franchise_html}
          </div>''')

    return f'''
      <div class="sc-mgr-section-header">Manager Profiles</div>
      <div class="sc-mgr-grid">
        {"".join(cards)}
      </div>'''


def _render_h2h_matrix(h2h: dict) -> str:
    """Render a 4x4 head-to-head record matrix."""
    managers = h2h.get("managers", [])
    if not managers:
        return ""

    # Build header row
    header_cells = '<th class="sc-h2h-corner"></th>'
    for m in managers:
        header_cells += f'<th class="sc-h2h-header">{_html(m)}</th>'

    # Build data rows
    rows = []
    for a in managers:
        cells = f'<td class="sc-h2h-row-label">{_html(a)}</td>'
        for b in managers:
            if a == b:
                cells += '<td class="sc-h2h-cell sc-h2h-self">&mdash;</td>'
            else:
                wins = h2h.get(f"{a}_vs_{b}", 0)
                losses = h2h.get(f"{b}_vs_{a}", 0)
                # Highlight winning record green, losing red
                if wins > losses:
                    cls = "sc-h2h-cell sc-h2h-win"
                elif wins < losses:
                    cls = "sc-h2h-cell sc-h2h-loss"
                else:
                    cls = "sc-h2h-cell sc-h2h-tie"
                cells += f'<td class="{cls}">{wins}-{losses}</td>'
        rows.append(f'<tr>{cells}</tr>')

    return f'''
      <div class="sc-mgr-section-header">Head-to-Head Records</div>
      <table class="sc-h2h-table">
        <tr>{header_cells}</tr>
        {"".join(rows)}
      </table>'''


def _render_leaderboard(
    title: str,
    entries: list,
    is_new_record: bool = False,
    entry_type: str = "team",
    unit: str = "",
    note: str = "",
) -> str:
    """
    Render a single top-5 leaderboard block.

    Args:
        title: Record name (e.g., "Highest Weekly Team Score")
        entries: List of entry dicts (up to 5)
        is_new_record: Show gold NEW! badge
        entry_type: "team" or "player" (affects how holder is displayed)
        unit: Unit label shown after title (e.g., "FP", "FPPG", "sigma (std dev)")
        note: Qualifier/context note shown below title (e.g., "Min 30 GP...")
    """
    # html.escape is available via _html_escape at module level
    new_badge = '<span class="sc-rb-new-badge">NEW!</span>' if is_new_record else ""
    unit_badge = f' <span class="sc-rb-unit">({_html(unit)})</span>' if unit else ""
    note_html = f'<div class="sc-rb-note">{_html(note)}</div>' if note else ""
    safe_title = _html(title)

    if not entries:
        return f'''
        <div class="sc-rb-leaderboard">
          <div class="sc-rb-lb-title">{safe_title}{unit_badge} {new_badge}</div>
          {note_html}
          <div class="sc-rb-placeholder">Awaiting historical data</div>
        </div>'''

    rows = []
    for e in entries:
        rank = e.get("rank", 0)
        value = e.get("value", 0)
        season = e.get("season", "")
        detail = e.get("detail", "")
        is_current = e.get("is_current_season", False)
        row_cls = " sc-rb-current" if is_current else ""

        # Format value
        if isinstance(value, float):
            # Show 1 decimal for margins, 2 for FPPG, 1 for scores
            if value == int(value) and value > 100:
                val_str = f"{value:,.1f}"
            elif abs(value) < 10:
                val_str = f"{value:.2f}"
            else:
                val_str = f"{value:,.1f}"
        else:
            val_str = str(value)

        # Format holder
        if entry_type == "player":
            player = e.get("player", "")
            manager = e.get("manager", "")
            if player and manager and player != manager:
                holder_str = f"{player}, {manager}"
            else:
                holder_str = player or manager
            # Fallback: if built as team record, use "holder" field
            if not holder_str:
                holder_str = e.get("holder", "")
        else:
            holder_str = e.get("holder", "")

        # Season + detail
        context_parts = []
        if season:
            context_parts.append(season)
        if detail:
            context_parts.append(detail)
        context_str = ", ".join(context_parts)

        rows.append(f'''
          <div class="sc-rb-entry{row_cls}">
            <span class="sc-rb-rank">{rank}.</span>
            <span class="sc-rb-value">{val_str}</span>
            <span class="sc-rb-holder">{_html(holder_str)}</span>
            <span class="sc-rb-context">({_html(context_str)})</span>
          </div>''')

    return f'''
        <div class="sc-rb-leaderboard">
          <div class="sc-rb-lb-title">{safe_title}{unit_badge} {new_badge}</div>
          {note_html}
          {"".join(rows)}
        </div>'''


def _format_career_points(pts: float) -> str:
    """Format career points as '302K' style."""
    if pts >= 1000:
        return f"{pts / 1000:,.0f}K"
    return f"{pts:,.0f}"


def render_stats_corner_visualizations(stats_report: dict, position: str = "all", player_cards: list = None) -> str:
    """Render Stats Corner visualizations from a stats report dict.

    Args:
        stats_report: The full stats report dictionary.
        position: Which visualizations to render:
            "top"    -- Positional, Draft Value, Waiver ROI, Keeper Watch
            "bottom" -- Record Book only
            "all"    -- Everything (legacy default)
        player_cards: Optional list of player card dicts (from player_card_builder).
            If provided, keeper watch chips include rank, archetype, career stats.
    """
    top_blocks = []
    bottom_blocks = []

    # 1. Positional Breakdown
    pb = stats_report.get("positional_breakdown")
    if pb:
        top_blocks.append(render_positional_breakdown(pb))

    # 2. Draft Value Tracker
    dv = stats_report.get("draft_value_tracker")
    if dv:
        top_blocks.append(render_draft_value_tracker(dv))

    # 3. Waiver Wire ROI
    wr = stats_report.get("waiver_roi")
    if wr:
        top_blocks.append(render_waiver_roi(wr))

    # 4. Keeper Watch
    kw = stats_report.get("keeper_watch")
    if kw:
        top_blocks.append(render_keeper_watch(kw, player_cards=player_cards))

    # 5. Record Book (bottom)
    rb = stats_report.get("record_book")
    if rb:
        hist_luck = stats_report.get("historical_luck", {})
        bottom_blocks.append(render_record_book(rb, historical_luck=hist_luck))

    # Select which blocks to return
    if position == "top":
        blocks = top_blocks
    elif position == "bottom":
        blocks = bottom_blocks
    else:
        blocks = top_blocks + bottom_blocks

    if not blocks:
        return ""

    return f'''
    <div class="sc-visualizations">
      {"".join(blocks)}
    </div>'''


# =====================================================================
# TAB JS (shared script for all tabbed visualizations)
# =====================================================================

def get_stats_corner_js() -> str:
    """Return the shared JavaScript for tabbed panels."""
    return '''
<script>
function scShowPanel(viz, manager) {
  document.querySelectorAll('#sc-' + viz + '-panel-' + manager)
  // Generic approach: find all panels and tabs for this viz
  var panels = document.querySelectorAll('[id^="sc-' + viz + '-panel-"]');
  var tabs = document.querySelectorAll('[id^="sc-' + viz + '-tab-"]');
  panels.forEach(function(p) { p.classList.remove('sc-active'); });
  tabs.forEach(function(t) { t.classList.remove('sc-active'); });
  var panel = document.getElementById('sc-' + viz + '-panel-' + manager);
  var tab = document.getElementById('sc-' + viz + '-tab-' + manager);
  if (panel) panel.classList.add('sc-active');
  if (tab) tab.classList.add('sc-active');
}

// Keeper Watch manager filter
var kwActiveManager = null;

function filterKeeperWatch(manager) {
  var cards = document.querySelectorAll('.sc-kw-filter-btn');
  var chips = document.querySelectorAll('.sc-kw-chip');
  var resetBtn = document.querySelector('.sc-kw-reset-btn');
  
  // If clicking the same manager, reset
  if (kwActiveManager === manager) {
    resetKeeperWatch();
    return;
  }
  
  kwActiveManager = manager;
  
  // Update summary cards
  cards.forEach(function(card) {
    card.classList.remove('sc-kw-active', 'sc-kw-dimmed');
    if (card.dataset.manager === manager) {
      card.classList.add('sc-kw-active');
    } else {
      card.classList.add('sc-kw-dimmed');
    }
  });
  
  // Filter player chips - show only selected manager
  chips.forEach(function(chip) {
    chip.classList.remove('sc-kw-hidden', 'sc-kw-dimmed');
    if (chip.dataset.manager !== manager) {
      chip.classList.add('sc-kw-hidden');
    }
  });
  
  // Show reset button
  if (resetBtn) resetBtn.classList.add('sc-kw-visible');
}

function resetKeeperWatch() {
  kwActiveManager = null;
  
  var cards = document.querySelectorAll('.sc-kw-filter-btn');
  var chips = document.querySelectorAll('.sc-kw-chip');
  var resetBtn = document.querySelector('.sc-kw-reset-btn');
  
  cards.forEach(function(card) {
    card.classList.remove('sc-kw-active', 'sc-kw-dimmed');
  });
  
  chips.forEach(function(chip) {
    chip.classList.remove('sc-kw-hidden', 'sc-kw-dimmed');
  });
  
  if (resetBtn) resetBtn.classList.remove('sc-kw-visible');
}
</script>'''


# =====================================================================
# CSS (all prefixed with sc- to avoid conflicts)
# =====================================================================

def get_stats_corner_css() -> str:
    """Return CSS for all Stats Corner visualizations."""
    return '''
/* ================================================================
   STATS CORNER VISUALIZATIONS
   ================================================================ */

.sc-visualizations {
  margin-top: 40px;
  padding-top: 30px;
  border-top: 2px solid #e0e0e0;
}

.sc-viz-block {
  margin-bottom: 40px;
}

.sc-viz-title {
  font-family: 'Playfair Display', Georgia, serif;
  font-size: 1.3rem;
  color: #1F4E79;
  text-align: center;
  margin-bottom: 4px;
  padding-bottom: 8px;
  border-bottom: 2px solid #C9A227;
}

.sc-viz-subtitle {
  font-family: 'Source Serif 4', serif;
  font-size: 0.85rem;
  color: #6c757d;
  text-align: center;
  margin-bottom: 18px;
  font-style: italic;
}

/*  Shared tab components  */
.sc-manager-panel { display: none; }
.sc-manager-panel.sc-active { display: block; }

.sc-panel-header {
  display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
}
.sc-panel-color-bar { width: 5px; height: 32px; border-radius: 3px; }
.sc-panel-info .sc-panel-name { font-size: 1rem; font-weight: 700; color: #58647a; }
.sc-panel-info .sc-panel-team { font-size: 0.78rem; color: #6c757d; }

.sc-manager-tabs {
  display: flex; justify-content: center; gap: 0;
  margin-top: 16px; border-top: 2px solid #e0e0e0;
}
.sc-manager-tab {
  flex: 1; text-align: center;
  padding: 10px 8px; font-size: 0.82rem; font-weight: 600; color: #6c757d;
  cursor: pointer; border-top: 3px solid transparent; margin-top: -2px;
  transition: all 0.2s ease; user-select: none;
}
.sc-manager-tab:hover { color: #58647a; background: #f8f9fa; }
.sc-manager-tab.sc-active { color: #58647a; border-top-color: #1F4E79; }

/*  Shared utility classes  */
.sc-pos { color: #2e7d32; }
.sc-neg { color: #c62828; }
.sc-neutral { color: #ffa726; }
.sc-good { color: #2e7d32; font-weight: 600; }
.sc-bad { color: #c62828; font-weight: 600; }

/*  1. POSITIONAL DONUT CHARTS  */
.sc-donut-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.sc-donut-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 12px;
  background: #f8f9fa;
  border-radius: 8px;
}

.sc-donut-left { flex-shrink: 0; }
.sc-donut-right { flex: 1; min-width: 0; }

.sc-donut-mgr { font-size: 0.9rem; font-weight: 700; color: #58647a; margin-bottom: 1px; }
.sc-donut-team { font-size: 0.68rem; color: #6c757d; margin-bottom: 8px; }

.sc-donut-wrapper {
  position: relative; width: 110px; height: 110px;
}
.sc-donut-wrapper svg { transform: rotate(-90deg); width: 100%; height: 100%; }

.sc-donut-center {
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%, -50%); text-align: center;
}
.sc-center-val { font-size: 1.05rem; font-weight: 800; color: #58647a; line-height: 1; }
.sc-center-lbl { font-size: 0.55rem; color: #6c757d; text-transform: uppercase; letter-spacing: 0.5px; }

.sc-donut-team-total {
  font-size: 0.68rem;
  color: #6c757d;
  text-align: center;
  margin-top: 6px;
  font-weight: 500;
}

.sc-donut-stats { display: flex; flex-direction: column; gap: 3px; }

.sc-donut-stat {
  display: flex; align-items: center; justify-content: space-between;
  padding: 3px 6px; background: #fff; border-radius: 4px;
}
.sc-ds-left { display: flex; align-items: center; gap: 5px; }
.sc-ds-swatch { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.sc-ds-pos { font-size: 0.6rem; font-weight: 700; color: #58647a; }
.sc-ds-right { display: flex; align-items: center; gap: 6px; }
.sc-ds-fp { font-size: 0.68rem; font-weight: 700; color: #58647a; }
.sc-ds-fppg { font-size: 0.58rem; color: #6c757d; }
.sc-ds-pct { font-size: 0.6rem; font-weight: 700; }

.sc-pos-legend { display: flex; justify-content: center; gap: 16px; margin-top: 14px; }
.sc-leg-item { display: flex; align-items: center; gap: 5px; font-size: 0.72rem; color: #4a4a5a; }
.sc-leg-swatch { width: 12px; height: 12px; border-radius: 3px; }

/*  2. DRAFT VALUE TRACKER  */
.sc-draft-entry {
  background: #f8f9fa; border-radius: 6px; padding: 10px; margin-bottom: 8px;
}
.sc-de-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px; }
.sc-de-player { font-size: 0.82rem; font-weight: 700; color: #58647a; line-height: 1.2; }
.sc-de-pick { font-size: 0.65rem; color: #6c757d; }
.sc-de-tags { display: flex; gap: 4px; align-items: center; flex-shrink: 0; }

.sc-tier-tag {
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.5px;
  text-transform: uppercase; padding: 2px 6px; border-radius: 2px;
}
.sc-status-tag {
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.5px;
  text-transform: uppercase; padding: 2px 6px; border-radius: 2px;
}
.sc-rostered { background: #e8f5e9; color: #2e7d32; }
.sc-traded { background: #e3f2fd; color: #1565c0; }
.sc-claimed { background: #f3e5f5; color: #7b1fa2; }
.sc-dropped { background: #fbe9e7; color: #c62828; }
.sc-ofs-tag {
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.5px;
  text-transform: uppercase; padding: 2px 6px; border-radius: 2px;
  background: #4a4a5a; color: #fff;
}

.sc-de-bar-row { display: flex; align-items: center; gap: 8px; }
.sc-bar-container {
  flex: 1; position: relative; height: 22px; background: #e9ecef; border-radius: 3px;
}
.sc-center-line {
  position: absolute; left: 50%; top: -1px; bottom: -1px;
  width: 2px; background: #343a40; z-index: 2;
}
.sc-bar {
  position: absolute; top: 2px; height: 18px; border-radius: 2px;
}
.sc-bar-faded { opacity: 0.4; }

.sc-delta-value {
  font-size: 0.82rem; font-weight: 800; white-space: nowrap; min-width: 42px; text-align: right;
}
.sc-de-detail { font-size: 0.62rem; color: #6c757d; margin-top: 4px; }

.sc-chart-axis {
  display: flex; justify-content: space-between;
  font-size: 0.65rem; color: #6c757d;
  border-top: 1px solid #e0e0e0; padding-top: 4px; margin-top: 6px;
}
.sc-panel-avg {
  text-align: center; margin-top: 12px; font-size: 0.82rem; color: #6c757d;
}

/*  3. WAIVER WIRE ROI  */
.sc-stats-row {
  display: flex; flex-wrap: wrap; justify-content: center; gap: 6px;
  background: #f8f9fa; border-radius: 8px; padding: 12px 8px; margin-bottom: 14px;
}
.sc-stat { text-align: center; min-width: 55px; flex: 1; }
.sc-ts-val { font-size: 1.2rem; font-weight: 800; color: #58647a; line-height: 1; }
.sc-ts-lbl {
  font-size: 0.58rem; color: #6c757d; text-transform: uppercase;
  letter-spacing: 0.5px; margin-top: 2px;
}

.sc-hitbust { margin-bottom: 14px; }
.sc-hb-bar { height: 12px; border-radius: 6px; display: flex; overflow: hidden; margin-bottom: 4px; }
.sc-hb-hit { background: #2e7d32; }
.sc-hb-mid { background: #e0e0e0; }
.sc-hb-bust { background: #c62828; }
.sc-hb-labels { display: flex; justify-content: space-between; font-size: 0.68rem; }
.sc-hb-l-hit { color: #2e7d32; font-weight: 600; }
.sc-hb-l-mid { color: #6c757d; }
.sc-hb-l-bust { color: #c62828; font-weight: 600; }

.sc-pickups-title {
  font-size: 0.75rem; font-weight: 700; color: #58647a;
  text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px;
}
.sc-pickup-table {
  width: 100%; border-collapse: collapse; margin-bottom: 14px; font-size: 0.75rem;
}
.sc-pickup-table th {
  text-align: left; font-size: 0.6rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.5px;
  color: #6c757d; padding: 5px 6px; border-bottom: 2px solid #e0e0e0;
}
.sc-pickup-table td {
  padding: 6px; border-bottom: 1px solid #e0e0e0; color: #4a4a5a;
}
.sc-pickup-table tr:last-child td { border-bottom: none; }
.sc-player-name { font-weight: 600; color: #58647a; }

.sc-callouts { display: flex; flex-direction: column; gap: 8px; }
.sc-callout-card { padding: 10px 12px; border-radius: 6px; }
.sc-callout-card.sc-best { background: #e8f5e9; border-left: 4px solid #2e7d32; }
.sc-callout-card.sc-regret { background: #fbe9e7; border-left: 4px solid #c62828; }
.sc-tcc-label {
  font-size: 0.58rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.5px; margin-bottom: 3px;
}
.sc-callout-card.sc-best .sc-tcc-label { color: #2e7d32; }
.sc-callout-card.sc-regret .sc-tcc-label { color: #c62828; }
.sc-tcc-player { font-size: 0.88rem; font-weight: 700; color: #58647a; margin-bottom: 1px; }
.sc-tcc-detail { font-size: 0.7rem; color: #4a4a5a; line-height: 1.3; }

/*  4. KEEPER WATCH  */
.sc-kw-summary-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 8px; margin-bottom: 20px;
}

.sc-kw-summary-card {
  background: #f8f9fa; border-radius: 6px; padding: 10px;
  text-align: center;
}

/* Clickable filter button styles */
.sc-kw-filter-btn {
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s, opacity 0.15s;
}
.sc-kw-filter-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
.sc-kw-filter-btn.sc-kw-active {
  box-shadow: 0 0 0 3px rgba(31, 78, 121, 0.4);
  transform: translateY(-1px);
}
.sc-kw-filter-btn.sc-kw-dimmed {
  opacity: 0.5;
}

/* Player chip filter states */
.sc-kw-chip.sc-kw-hidden {
  display: none;
}
.sc-kw-chip.sc-kw-dimmed {
  opacity: 0.3;
}

/* Reset button */
.sc-kw-reset-btn {
  display: none;
  margin: 0 auto 16px;
  padding: 6px 16px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #1F4E79;
  background: #e8f0fe;
  border: 1px solid #1F4E79;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s;
}
.sc-kw-reset-btn:hover {
  background: #d0e2fc;
}
.sc-kw-reset-btn.sc-kw-visible {
  display: block;
}

.sc-kw-mgr-name { font-size: 0.88rem; font-weight: 700; color: #58647a; }
.sc-kw-mgr-team { font-size: 0.62rem; color: #6c757d; margin-bottom: 6px; }

.sc-kw-pills { display: flex; flex-wrap: wrap; justify-content: center; gap: 3px; margin-bottom: 4px; }
.sc-kw-pill {
  font-size: 0.52rem; font-weight: 700; letter-spacing: 0.3px;
  padding: 2px 6px; border-radius: 3px; text-transform: uppercase;
}
.sc-kw-avg-age { font-size: 0.6rem; color: #6c757d; }

.sc-kw-tier-section { margin-bottom: 16px; }
.sc-kw-tier-header {
  font-size: 0.85rem; font-weight: 700; color: #58647a;
  text-transform: uppercase; letter-spacing: 0.5px;
  margin-bottom: 8px; padding-bottom: 4px;
  border-bottom: 1px solid #e0e0e0;
}
.sc-kw-tier-count { font-weight: 400; color: #6c757d; font-size: 0.75rem; }
.sc-kw-tier-desc {
  font-size: 0.75rem; color: #6c757d; font-style: italic;
  margin: -4px 0 8px 0;
}

.sc-kw-tier-players {
  display: flex; flex-direction: column; gap: 6px;
}
.sc-kw-chip {
  background: #fff; border-radius: 6px; padding: 8px 10px;
  border: 1px solid #e0e0e0;
}
.sc-kw-chip-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px; gap: 6px; }
.sc-kw-chip-name { font-size: 0.82rem; font-weight: 700; color: #58647a; min-width: 0; }
.sc-kw-ofs {
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.5px;
  padding: 1px 5px; border-radius: 2px; vertical-align: middle;
  background: #4a4a5a; color: #fff; margin-left: 4px;
}
.sc-kw-inj {
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.5px;
  padding: 1px 5px; border-radius: 2px; vertical-align: middle;
  background: #e65100; color: #fff; margin-left: 4px;
}
.sc-kw-chip-meta { font-size: 0.62rem; color: #6c757d; margin-bottom: 3px; }

.sc-kw-chip-stats { display: flex; gap: 6px; align-items: baseline; margin-bottom: 2px; }
.sc-kw-stat-main { font-size: 0.88rem; font-weight: 700; color: #58647a; }
.sc-kw-stat-label { font-size: 0.58rem; color: #8a9ab5; align-self: center; }
.sc-kw-stat-proj { font-size: 0.58rem; color: #6c757d; margin-left: auto; }
.sc-kw-stat-delta { font-size: 0.62rem; font-weight: 700; }
.sc-pos { color: #2e7d32; }
.sc-neg { color: #c62828; }

.sc-kw-chip-arch { font-size: 0.55rem; color: #8a9ab5; font-style: italic; }

/*  Responsive  */

/* -- 5. RECORD BOOK -- */
.sc-rb-card {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 20px 16px;
  background: #fafafa;
}

.sc-rb-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.sc-rb-trophy {
  font-size: 1.2rem;
}

.sc-rb-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 16px;
  border-bottom: 2px solid #e0e0e0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.sc-rb-tab {
  flex: 1;
  text-align: center;
  padding: 8px 6px;
  font-size: 0.72rem;
  font-weight: 600;
  color: #6c757d;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  white-space: nowrap;
  transition: color 0.15s, border-color 0.15s;
  user-select: none;
}

.sc-rb-tab:hover {
  color: #1F4E79;
}

.sc-rb-tab.sc-active {
  color: #1F4E79;
  border-bottom-color: #C9A227;
  font-weight: 700;
}

.sc-rb-leaderboard {
  margin-bottom: 14px;
  padding: 8px 10px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #eee;
  text-align: left;
}

.sc-rb-lb-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #58647a;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.sc-rb-new-badge {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 1px 6px;
  border-radius: 3px;
  background: #C9A227;
  color: #fff;
  text-transform: uppercase;
}

.sc-rb-unit {
  font-size: 0.72rem;
  font-weight: 500;
  color: #6c757d;
}

.sc-rb-note {
  font-size: 0.68rem;
  color: #9e9e9e;
  font-style: italic;
  margin: -3px 0 4px 0;
  line-height: 1.3;
}

.sc-rb-entry {
  display: flex;
  align-items: baseline;
  gap: 4px;
  padding: 2px 4px;
  font-size: 0.78rem;
  line-height: 1.5;
  border-radius: 3px;
  overflow: hidden;
}

.sc-rb-entry.sc-rb-current {
  background: rgba(201, 162, 39, 0.08);
}

.sc-rb-rank {
  font-weight: 700;
  color: #6c757d;
  min-width: 20px;
  text-align: right;
  flex-shrink: 0;
}

.sc-rb-value {
  font-weight: 700;
  color: #58647a;
  min-width: 55px;
  flex-shrink: 0;
}

.sc-rb-holder {
  color: #58647a;
  font-weight: 500;
  flex-shrink: 0;
}

.sc-rb-context {
  color: #6c757d;
  font-size: 0.72rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.sc-rb-placeholder {
  font-size: 0.78rem;
  color: #9e9e9e;
  font-style: italic;
  padding: 4px;
}

/* Manager Profile Cards */
.sc-mgr-section-header {
  font-size: 0.82rem;
  font-weight: 700;
  color: #58647a;
  margin: 0 0 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.sc-mgr-section-subtitle {
  font-size: 0.75rem;
  color: #8a8a8a;
  margin: -4px 0 10px;
}
.sc-mgr-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-bottom: 14px;
}
.sc-mgr-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e8e4d8;
  padding: 12px 14px;
}
.sc-mgr-leader {
  border-color: #C9A227;
  box-shadow: 0 0 0 1px #C9A227;
}
.sc-mgr-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.sc-mgr-name {
  font-size: 1.05rem;
  font-weight: 700;
  color: #58647a;
}
.sc-mgr-rank-badge {
  font-size: 0.68rem;
  font-weight: 700;
  color: #C9A227;
  background: rgba(201, 162, 39, 0.1);
  padding: 2px 8px;
  border-radius: 10px;
}
.sc-mgr-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
  margin-bottom: 10px;
}
.sc-mgr-stat-item {
  text-align: center;
}
.sc-mgr-stat-val {
  display: block;
  font-size: 0.88rem;
  font-weight: 700;
  color: #58647a;
}
.sc-mgr-stat-label {
  display: block;
  font-size: 0.62rem;
  color: #8a8a9a;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.sc-mgr-franchise {
  background: rgba(201, 162, 39, 0.06);
  border-top: 1px solid #e8e4d8;
  padding: 8px 0 0;
  margin-top: 2px;
}
.sc-mgr-franchise-label {
  font-size: 0.62rem;
  font-weight: 700;
  color: #C9A227;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}
.sc-mgr-franchise-name {
  font-size: 0.88rem;
  font-weight: 700;
  color: #58647a;
}
.sc-mgr-franchise-stat {
  font-size: 0.78rem;
  font-weight: 600;
  color: #4a4a5a;
}
.sc-mgr-franchise-detail {
  font-size: 0.7rem;
  color: #8a8a9a;
}

/* H2H Matrix */
.sc-h2h-table {
  width: 100%;
  border-collapse: collapse;
  margin: 6px 0 12px;
  font-size: 0.78rem;
}
.sc-h2h-corner {
  width: 60px;
}
.sc-h2h-header {
  text-align: center;
  font-weight: 600;
  color: #58647a;
  padding: 6px 4px;
  font-size: 0.75rem;
  border-bottom: 2px solid #C9A227;
}
.sc-h2h-row-label {
  font-weight: 600;
  color: #58647a;
  padding: 6px 8px;
  text-align: left;
  border-right: 2px solid #C9A227;
}
.sc-h2h-cell {
  text-align: center;
  padding: 6px 4px;
  font-weight: 500;
  border: 1px solid #e8e4d8;
}
.sc-h2h-self {
  background: #f5f3ee;
  color: #999;
}
.sc-h2h-win {
  background: #e8f5e9;
  color: #2e7d32;
}
.sc-h2h-loss {
  background: #fce4ec;
  color: #c62828;
}
.sc-h2h-tie {
  background: #fff8e1;
  color: #f57f17;
}

/* === HISTORICAL STANDINGS & LUCK TABLES === */
.sc-hist-wrapper {
  overflow-x: auto;
  margin-bottom: 16px;
}

.sc-hist-table {
  width: 100%;
  border-collapse: collapse;
  font-family: Inter, sans-serif;
}

.sc-hist-header-row {
  border-bottom: 2px solid #e5e7eb;
  background: #f8f9fa;
}

.sc-hist-th {
  padding: 6px 4px;
  font-size: 0.7rem;
  text-transform: uppercase;
  color: #6b7280;
}

.sc-hist-th-mgr {
  text-align: left;
  min-width: 70px;
}

.sc-hist-th-season {
  text-align: center;
  min-width: 55px;
}

.sc-hist-th-summary {
  text-align: center;
  min-width: 40px;
}

.sc-hist-th.sc-hist-current,
.sc-hist-td.sc-hist-current {
  background: #e8f0fe;
}

.sc-hist-td {
  padding: 5px 4px;
  font-size: 0.75rem;
  text-align: center;
}

.sc-hist-td-mgr {
  font-size: 0.8rem;
  font-weight: 700;
  text-align: left;
}

.sc-hist-td-sum {
  font-size: 0.8rem;
  font-weight: 700;
}

.sc-hist-td-career {
  font-size: 0.85rem;
}

/* Place finish badges (gold/silver/bronze backgrounds) */
.sc-hist-place {
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

.sc-hist-1st {
  background: linear-gradient(135deg, #FFD700, #FFC107);
  color: #000;
}

.sc-hist-2nd {
  background: linear-gradient(135deg, #C0C0C0, #A8A8A8);
  color: #000;
}

.sc-hist-3rd {
  background: linear-gradient(135deg, #CD7F32, #B87333);
  color: #fff;
}

.sc-hist-4th {
  color: #9ca3af;
}

/* No playoffs indicator (COVID year) */
.sc-hist-no-playoffs {
  color: #6b7280;
  font-style: italic;
}

/* Summary column colors */
.sc-hist-sum-1st { color: #16a34a; }
.sc-hist-sum-2nd { color: #2563eb; }
.sc-hist-sum-3rd { color: #ea580c; }

/* Luck values */
.sc-luck-val {
  font-weight: 600;
}

.sc-luck-career {
  font-weight: 700;
}

.sc-luck-very-good { color: #16a34a; }
.sc-luck-good { color: #2563eb; }
.sc-luck-neutral { color: #6b7280; }
.sc-luck-bad { color: #ea580c; }
.sc-luck-very-bad { color: #dc2626; }

/* Luck legend */
.sc-luck-legend {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 8px;
  font-size: 0.7rem;
  color: #6b7280;
}

.sc-luck-legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.sc-luck-swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
}

.sc-luck-swatch-good { background: #16a34a; }
.sc-luck-swatch-bad { background: #dc2626; }

@media (max-width: 599px) {
  .sc-rb-entry {
    flex-wrap: wrap;
  }
  .sc-rb-context {
    width: 100%;
    padding-left: 24px;
    white-space: normal;
    overflow: visible;
    text-overflow: unset;
  }
  .sc-rb-tab {
    font-size: 0.65rem;
    padding: 7px 4px;
  }
  .sc-h2h-table {
    font-size: 0.68rem;
  }
  .sc-h2h-header, .sc-h2h-cell {
    padding: 4px 2px;
  }
}

@media (min-width: 600px) {
  .sc-donut-grid { grid-template-columns: 1fr 1fr; gap: 20px; }
  .sc-donut-card { padding: 16px 14px; }
  .sc-donut-wrapper { width: 130px; height: 130px; }
  .sc-center-val { font-size: 1.2rem; }
  .sc-manager-tab { flex: none; padding: 10px 24px; }
  .sc-callouts { flex-direction: row; }
  .sc-callout-card { flex: 1; }
  .sc-kw-summary-grid { grid-template-columns: 1fr 1fr 1fr 1fr; }
  .sc-kw-tier-players { flex-direction: row; flex-wrap: wrap; }
  .sc-kw-chip { width: calc(50% - 3px); }
  .sc-mgr-grid { grid-template-columns: 1fr 1fr; }
}

/* ============================================
   STATS CORNER - DARK MODE SUPPORT
   Comprehensive overrides for all text colors
   ============================================ */
@media (prefers-color-scheme: dark) {
  /* === BORDERS & BACKGROUNDS === */
  .sc-visualizations {
    border-top-color: #404040;
  }
  
  .sc-viz-title {
    color: #5b9bd5;
    border-bottom-color: #e6b93d;
  }
  
  .sc-viz-subtitle {
    color: #a0a0a0;
  }
  
  /* === MANAGER TABS === */
  .sc-manager-tabs {
    border-top-color: #404040;
  }
  
  .sc-manager-tab {
    color: #a0a0a0;
  }
  
  .sc-manager-tab:hover {
    color: #f0f0f0;
    background: #2d2d2d;
  }
  
  .sc-manager-tab.sc-active {
    color: #f0f0f0;
    border-top-color: #5b9bd5;
  }
  
  /* === PANEL INFO === */
  .sc-panel-info .sc-panel-name {
    color: #f0f0f0;
  }
  
  .sc-panel-info .sc-panel-team {
    color: #a0a0a0;
  }
  
  /* === DONUT CHARTS (Positional Breakdown) === */
  .sc-donut-card {
    background: #252525;
  }
  
  .sc-donut-mgr {
    color: #f0f0f0;
  }
  
  .sc-donut-team {
    color: #a0a0a0;
  }
  
  .sc-center-val {
    color: #f0f0f0;
  }
  
  .sc-center-lbl {
    color: #a0a0a0;
  }
  
  .sc-donut-team-total {
    color: #a0a0a0;
  }
  
  .sc-donut-stat {
    background: #2d2d2d;
  }
  
  .sc-ds-pos {
    color: #e0e0e0;
  }
  
  .sc-ds-fp {
    color: #f0f0f0;
  }
  
  .sc-ds-fppg {
    color: #a0a0a0;
  }
  
  .sc-leg-item {
    color: #c0c0c0;
  }
  
  /* === DRAFT VALUE TRACKER === */
  .sc-draft-entry {
    background: #252525;
  }
  
  .sc-de-player {
    color: #f0f0f0;
  }
  
  .sc-de-pick {
    color: #a0a0a0;
  }
  
  .sc-bar-container {
    background: #3a3a3a;
  }
  
  .sc-center-line {
    background: #808080;
  }
  
  .sc-de-detail {
    color: #a0a0a0;
  }
  
  .sc-chart-axis {
    color: #a0a0a0;
    border-top-color: #404040;
  }
  
  .sc-panel-avg {
    color: #a0a0a0;
  }
  
  /* === WAIVER WIRE ROI === */
  .sc-stats-row {
    background: #252525;
  }
  
  .sc-ts-val {
    color: #f0f0f0;
  }
  
  .sc-ts-lbl {
    color: #a0a0a0;
  }
  
  .sc-hb-mid {
    background: #404040;
  }
  
  .sc-hb-l-mid {
    color: #a0a0a0;
  }
  
  .sc-pickups-title {
    color: #f0f0f0;
  }
  
  .sc-pickup-table th {
    color: #a0a0a0;
    border-bottom-color: #404040;
  }
  
  .sc-pickup-table td {
    color: #c0c0c0;
    border-bottom-color: #404040;
  }
  
  .sc-player-name {
    color: #f0f0f0;
  }
  
  /* === CALLOUT CARDS === */
  .sc-callout-card.sc-best {
    background: #1a2e1a;
    border-left-color: #4caf50;
  }
  
  .sc-callout-card.sc-regret {
    background: #2e1a1a;
    border-left-color: #ef5350;
  }
  
  .sc-tcc-player {
    color: #f0f0f0;
  }
  
  .sc-tcc-detail {
    color: #c0c0c0;
  }
  
  /* === KEEPER WATCH === */
  .sc-kw-summary-card {
    background: #252525;
  }
  
  .sc-kw-filter-btn:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  }
  
  .sc-kw-filter-btn.sc-kw-active {
    box-shadow: 0 0 0 3px rgba(91, 155, 213, 0.5);
  }
  
  .sc-kw-reset-btn {
    background: #2d2d2d;
    color: #5b9bd5;
    border-color: #5b9bd5;
  }
  
  .sc-kw-reset-btn:hover {
    background: #3d3d3d;
  }
  
  .sc-kw-mgr-name {
    color: #f0f0f0;
  }
  
  .sc-kw-mgr-team {
    color: #a0a0a0;
  }
  
  .sc-kw-avg-age {
    color: #a0a0a0;
  }
  
  .sc-kw-tier-header {
    color: #f0f0f0;
    border-bottom-color: #404040;
  }
  
  .sc-kw-tier-count {
    color: #a0a0a0;
  }
  
  .sc-kw-tier-desc {
    color: #a0a0a0;
  }
  
  .sc-kw-chip {
    background: #2d2d2d;
    border-color: #404040;
  }
  
  .sc-kw-chip-name {
    color: #f0f0f0;
  }
  
  .sc-kw-chip-meta {
    color: #a0a0a0;
  }
  
  .sc-kw-stat-main {
    color: #f0f0f0;
  }
  
  .sc-kw-stat-sub {
    color: #a0a0a0;
  }
  
  .sc-kw-chip-detail {
    color: #a0a0a0;
  }
  
  .sc-kw-rank {
    background: rgba(255,255,255,0.1);
    color: #a0a0a0;
  }
  
  .sc-kw-career {
    color: #8a9ab5;
  }
  
  .sc-kw-chip-arch {
    color: #707a8a;
  }
  
  /* === RECORD BOOK === */
  .sc-rb-card {
    background: #252525;
    border-color: #404040;
  }
  
  .sc-rb-title {
    color: #5b9bd5;
  }
  
  .sc-rb-tabs {
    border-bottom-color: #404040;
  }
  
  .sc-rb-tab {
    color: #a0a0a0;
  }
  
  .sc-rb-tab:hover {
    color: #f0f0f0;
    background: #2d2d2d;
  }
  
  .sc-rb-tab.sc-active {
    color: #5b9bd5;
    border-bottom-color: #e6b93d;
  }
  
  .sc-rb-leaderboard {
    background: #2d2d2d;
    border-color: #404040;
  }
  
  .sc-rb-lb-title {
    color: #f0f0f0;
  }
  
  .sc-rb-unit {
    color: #a0a0a0;
  }
  
  .sc-rb-note {
    color: #808080;
  }
  
  .sc-rb-entry.sc-rb-current {
    background: rgba(230, 185, 61, 0.15);
  }
  
  .sc-rb-rank {
    color: #a0a0a0;
  }
  
  .sc-rb-value {
    color: #f0f0f0;
  }
  
  .sc-rb-holder {
    color: #e0e0e0;
  }
  
  .sc-rb-context {
    color: #a0a0a0;
  }
  
  .sc-rb-placeholder {
    color: #808080;
    background: #2d2d2d;
  }
  
  /* === MANAGER PROFILE CARDS === */
  .sc-mgr-section-header {
    color: #f0f0f0;
  }
  
  .sc-mgr-section-subtitle {
    color: #a0a0a0;
  }
  
  .sc-mgr-card {
    background: #2d2d2d;
    border-color: #404040;
  }
  
  .sc-mgr-leader {
    border-color: #e6b93d;
    box-shadow: 0 0 0 1px #e6b93d;
  }
  
  .sc-mgr-name {
    color: #f0f0f0;
  }
  
  .sc-mgr-rank-badge {
    color: #e6b93d;
    background: rgba(230, 185, 61, 0.15);
  }
  
  .sc-mgr-stat-val {
    color: #f0f0f0;
  }
  
  .sc-mgr-stat-label {
    color: #a0a0a0;
  }
  
  .sc-mgr-franchise {
    background: rgba(230, 185, 61, 0.08);
    border-top-color: #404040;
  }
  
  .sc-mgr-franchise-name {
    color: #f0f0f0;
  }
  
  .sc-mgr-franchise-stat {
    color: #c0c0c0;
  }
  
  .sc-mgr-franchise-detail {
    color: #a0a0a0;
  }
  
  /* === H2H MATRIX === */
  .sc-h2h-header {
    color: #f0f0f0;
    border-bottom-color: #e6b93d;
  }
  
  .sc-h2h-row-label {
    color: #f0f0f0;
    border-right-color: #e6b93d;
  }
  
  .sc-h2h-cell {
    border-color: #404040;
  }
  
  .sc-h2h-self {
    background: #2a2a2a;
    color: #666;
  }
  
  .sc-h2h-win {
    background: #1a3d1a;
    color: #4caf50;
  }
  
  .sc-h2h-loss {
    background: #3d1a1a;
    color: #ef5350;
  }
  
  .sc-h2h-tie {
    background: #3d3d1a;
    color: #ffca28;
  }
  
  /* === HISTORICAL STANDINGS & LUCK TABLES === */
  .sc-hist-header-row {
    background: #2d2d2d;
    border-bottom-color: #404040;
  }
  
  .sc-hist-th {
    color: #a0a0a0;
  }
  
  .sc-hist-th.sc-hist-current,
  .sc-hist-td.sc-hist-current {
    background: rgba(91, 155, 213, 0.15);
  }
  
  .sc-hist-td {
    color: #c0c0c0;
  }
  
  .sc-hist-td-mgr {
    /* Manager colors are intentionally kept as-is (brand colors) */
  }
  
  .sc-hist-4th {
    color: #6b7280;
  }
  
  /* Luck legend dark mode */
  .sc-luck-legend {
    color: #a0a0a0;
  }
  
  /* Keep luck value colors the same - they work well on dark */
}
'''
