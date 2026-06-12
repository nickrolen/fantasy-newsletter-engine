"""
player_card_modal.py

Generates the HTML, CSS, and JavaScript for the interactive player card modal
that appears when clicking a player chip in the Keeper Watch section.

Design: 2K MyNBA-inspired scouting cards with dark theme, mobile-first.
Integrates with the existing Stats Corner visualization system (sc- prefix namespace).

Usage (from stats_corner_viz.py or newsletter_html_generator.py):
    from modules.player_card_modal import get_player_card_css, get_player_card_js, embed_player_card_data

    # In CSS section:
    css += get_player_card_css()

    # In JS section:
    js += get_player_card_js()

    # Embed the JSON data blob (call after build_player_cards):
    html += embed_player_card_data(cards)
"""

from __future__ import annotations
import json
from html import escape as _html_escape

from .data_loader import MANAGER_COLORS

TIER_COLORS = {
    "Lock": {"bg": "#2e7d32", "color": "#fff"},
    "Strong Hold": {"bg": "#1F4E79", "color": "#fff"},
    "Stash": {"bg": "#7b1fa2", "color": "#fff"},
    "Sell High": {"bg": "#ffa726", "color": "#333"},
    "On the Bubble": {"bg": "#757575", "color": "#fff"},
    "Dynasty Stash": {"bg": "#0288d1", "color": "#fff"},
    "Drop": {"bg": "#c62828", "color": "#fff"},
}

# SYNC: labels must match the archetype classifier in player_card_builder.py
# (classify_archetype). When adding or renaming an archetype, update BOTH this
# dict AND the inline archColors object in pcRenderCard below.
ARCHETYPE_COLORS = {
    # Insufficient data
    "Uncharted Prospect": "#A5D6A7",
    "Small Sample": "#78909C",
    # Elite (gold / orange)
    "Generational Big": "#FFD700",
    "Cheat Code": "#FFD700",
    "Supernova": "#FF6B35",
    "Alpha Scorer": "#FFD700",
    # All-Star (blue / green / purple)
    "Iron Man Elite": "#4FC3F7",
    "Metronome Star": "#4FC3F7",
    "Franchise Cornerstone": "#69F0AE",
    "Young Alpha": "#69F0AE",
    "Walking Bucket": "#4FC3F7",
    "Ageless Wonder": "#CE93D8",
    "Vintage Star": "#FF6B35",
    "High Roller": "#FFB74D",
    "Aging Superstar": "#CE93D8",
    "All-Star Caliber": "#4FC3F7",
    # Starter (green / yellow / red)
    "Future Franchise": "#69F0AE",
    "Ascending Talent": "#69F0AE",
    "Steady Riser": "#81C784",
    "Breakout Candidate": "#FFB74D",
    "Building Block": "#81C784",
    "Ironman Floor Raiser": "#4FC3F7",
    "Reliable Starter": "#81C784",
    "High-Ceiling Starter": "#FFB74D",
    "Talented but Fragile": "#EF5350",
    "Father Time Defier": "#CE93D8",
    "Crafty Veteran": "#CE93D8",
    "Volatile Starter": "#FFB74D",
    "Streaky Scorer": "#FFB74D",
    "Quality Starter": "#81C784",
    # Rotation (green / gray / orange)
    "Blue-Chip Prospect": "#69F0AE",
    "Lottery Ticket": "#69F0AE",
    "Development Play": "#A5D6A7",
    "Glue Guy": "#81C784",
    "Rollercoaster": "#FF8A65",
    "Veteran Presence": "#B0BEC5",
    "Steady Contributor": "#B0BEC5",
    "Rotation Piece": "#B0BEC5",
    # Fringe / Bench (light green / gray)
    "Raw Prospect": "#A5D6A7",
    "Upside Bench Stash": "#A5D6A7",
    "Aging Vet": "#78909C",
    "Roster Filler": "#78909C",
}


def embed_player_card_data(cards: list[dict]) -> str:
    """
    Embed player card data as a JSON blob in a <script> tag.
    This goes in the HTML body so the modal JS can access it.
    """
    # Sanitize for safe HTML embedding
    json_str = json.dumps(cards, default=str, ensure_ascii=True)
    # Escape </script> sequences
    json_str = json_str.replace("</", "<\\/")
    return f'<script>var PC_DATA = {json_str};</script>'


def get_player_card_js() -> str:
    """Return JavaScript for the player card modal."""
    _mgr_colors_js = json.dumps(MANAGER_COLORS)
    return (
        '\nvar pcManagerColors = ' + _mgr_colors_js + ';\n'
        + '''
/* ================================================================
   PLAYER CARD MODAL
   ================================================================ */

var pcModal = null;
var pcData = {};

function pcInit() {
  if (typeof PC_DATA === 'undefined') return;
  // Index cards by player name for fast lookup
  PC_DATA.forEach(function(card) {
    pcData[card.player_name] = card;
  });
  
  // Create modal element
  var m = document.createElement('div');
  m.id = 'pc-modal';
  m.className = 'pc-modal';
  m.innerHTML = '<div class="pc-backdrop" onclick="pcClose()"></div><div class="pc-sheet" id="pc-sheet"></div>';
  document.body.appendChild(m);
  pcModal = m;
}

function pcOpen(playerName) {
  var card = pcData[playerName];
  if (!card || !pcModal) return;
  
  pcCurrentCard = card;
  pcCurrentFilter = null;
  
  var sheet = document.getElementById('pc-sheet');
  sheet.innerHTML = pcRenderCard(card);
  sheet.scrollTop = 0;
  pcModal.classList.add('pc-open');
  document.body.style.overflow = 'hidden';
  
  // Bind season trend click handlers via event delegation
  var trendCols = sheet.querySelectorAll('.pc-trend-clickable');
  trendCols.forEach(function(col) {
    col.addEventListener('click', function() {
      var season = this.getAttribute('data-season');
      if (season) pcFilterSeason(this, season);
    });
  });
}

function pcClose() {
  if (!pcModal) return;
  pcModal.classList.remove('pc-open');
  document.body.style.overflow = '';
}

// Close on Escape key
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') pcClose();
});

function pcRenderCard(c) {
  var mgrColor = pcManagerColors[c.manager] || "#666";
  var tierColors = {"Lock":["#2e7d32","#fff"],"Strong Hold":["#1F4E79","#fff"],"Stash":["#7b1fa2","#fff"],"Sell High":["#ffa726","#333"],"On the Bubble":["#757575","#fff"],"Dynasty Stash":["#0288d1","#fff"],"Drop":["#c62828","#fff"]};
  var tc = tierColors[c.keeper_tier] || ["#666","#fff"];
  
  // SYNC: labels must match player_card_builder.py classify_archetype()
  var archColors = {"Uncharted Prospect":"#A5D6A7","Small Sample":"#78909C","Generational Big":"#FFD700","Cheat Code":"#FFD700","Supernova":"#FF6B35","Alpha Scorer":"#FFD700","Iron Man Elite":"#4FC3F7","Metronome Star":"#4FC3F7","Franchise Cornerstone":"#69F0AE","Young Alpha":"#69F0AE","Walking Bucket":"#4FC3F7","Ageless Wonder":"#CE93D8","Vintage Star":"#FF6B35","High Roller":"#FFB74D","Aging Superstar":"#CE93D8","All-Star Caliber":"#4FC3F7","Future Franchise":"#69F0AE","Ascending Talent":"#69F0AE","Steady Riser":"#81C784","Breakout Candidate":"#FFB74D","Building Block":"#81C784","Ironman Floor Raiser":"#4FC3F7","Reliable Starter":"#81C784","High-Ceiling Starter":"#FFB74D","Talented but Fragile":"#EF5350","Father Time Defier":"#CE93D8","Crafty Veteran":"#CE93D8","Volatile Starter":"#FFB74D","Streaky Scorer":"#FFB74D","Quality Starter":"#81C784","Blue-Chip Prospect":"#69F0AE","Lottery Ticket":"#69F0AE","Development Play":"#A5D6A7","Glue Guy":"#81C784","Rollercoaster":"#FF8A65","Veteran Presence":"#B0BEC5","Steady Contributor":"#B0BEC5","Rotation Piece":"#B0BEC5","Raw Prospect":"#A5D6A7","Upside Bench Stash":"#A5D6A7","Aging Vet":"#78909C","Roster Filler":"#78909C"};
  var archColor = archColors[c.archetype] || "#B0BEC5";
  
  var html = '';
  
  // === CLOSE BUTTON ===
  html += '<button class="pc-close" onclick="pcClose()">&times;</button>';
  
  // === HEADER ===
  html += '<div class="pc-header" style="border-bottom: 3px solid ' + mgrColor + ';">';
  html += '<div class="pc-header-top">';
  html += '<div class="pc-name-row"><div class="pc-name">' + esc(c.player_name) + '</div>';
  if (c.overall_rank) {
    html += '<div class="pc-rank">Avg. Rank: #' + c.overall_rank + '</div>';
  }
  html += '</div>';
  html += '<div class="pc-meta">' + esc(c.nba_team) + ' &middot; ' + esc(c.positions) + ' &middot; Age ' + c.age + '</div>';
  html += '</div>';
  html += '<div class="pc-badges">';
  html += '<span class="pc-arch-badge" style="background:' + archColor + ';color:#1a1a1a;">' + esc(c.archetype) + '</span>';
  html += '<span class="pc-tier-badge" style="background:' + tc[0] + ';color:' + tc[1] + ';">' + esc(c.keeper_tier) + '</span>';
  html += '</div>';
  html += '</div>';
  
  // === STAT BAR ===
  var cs = c.current_season || {};
  var career = c.career || {};
  html += '<div class="pc-stat-bar">';
  html += '<div class="pc-stat-cell" id="pc-hdr-fppg"><div class="pc-stat-val">' + (cs.fppg || 0).toFixed(1) + '</div>' + (c.composite_rank_fppg ? '<div class="pc-stat-rank">#' + c.composite_rank_fppg + '</div>' : '') + '<div class="pc-stat-lbl">FPPG</div></div>';
  html += '<div class="pc-stat-cell" id="pc-hdr-totalfp"><div class="pc-stat-val">' + Math.round(cs.total_fp || 0).toLocaleString() + '</div>' + (c.composite_rank_total ? '<div class="pc-stat-rank">#' + c.composite_rank_total + '</div>' : '') + '<div class="pc-stat-lbl">Tot FP</div></div>';
  html += '<div class="pc-stat-cell" id="pc-hdr-gp"><div class="pc-stat-val">' + (cs.gp || 0) + '</div><div class="pc-stat-lbl">GP</div></div>';
  html += pcStatCell('Career', (career.career_fppg || 0).toFixed(1));
  html += '</div>';
  
  // === KEEPABILITY BREAKDOWN ===
  html += pcRenderKeepability(c);
  
  // === SCORING SPARKLINE ===
  html += pcRenderSparkline(c);
  
  // === BOOM / BUST ===
  html += pcRenderBoomBust(c);
  
  // === SEASON COMPS ===
  html += pcRenderSeasonComps(c);
  
  // === OWNERSHIP TIMELINE ===
  html += pcRenderTimeline(c);
  
  // === TRADE HISTORY ===
  html += pcRenderTradeHistory(c);
  
  // === DRAFT ROI ===
  html += pcRenderDraftROI(c);
  
  // === INJURY PROFILE ===
  html += pcRenderInjury(c);
  
  // === RECORD BOOK ===
  html += pcRenderRecords(c);
  
  // === MILESTONES ===
  html += pcRenderMilestones(c);
  
  // === LAST 10 GAMES ===
  html += pcRenderLast10(c);
  
  return html;
}

function esc(s) { 
  var d = document.createElement('div'); 
  d.textContent = s == null ? '' : String(s); 
  return d.innerHTML; 
}

function pcStatCell(label, value, rank) {
  var html = '<div class="pc-stat-cell"><div class="pc-stat-val">' + value + '</div>';
  if (rank) {
    html += '<div class="pc-stat-rank">' + rank + '</div>';
  }
  html += '<div class="pc-stat-lbl">' + label + '</div></div>';
  return html;
}

/* --- KEEPABILITY BREAKDOWN (V2) --- */
function pcRenderKeepability(c) {
  var score = c.keepability_score;
  if (!score) return '';
  
  var comp = c.keepability_components || {};
  
  // Check if we have v2 components (presence of weighted_fppg_raw indicates v2)
  var isV2 = comp.weighted_fppg_raw !== undefined;
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Keepability Score' + (isV2 ? ' (v2)' : '') + '</div>';
  
  // Main score bar
  var scorePct = isV2 ? Math.min(100, score) : Math.min(100, (score / 60) * 100);
  var scoreColor = (isV2 ? score >= 70 : score >= 40) ? '#4FC3F7' : 
                   ((isV2 ? score >= 60 : score >= 30) ? '#81C784' : 
                   ((isV2 ? score >= 40 : score >= 20) ? '#FFB74D' : '#EF5350'));
  html += '<div class="pc-keep-score-row">';
  html += '<div class="pc-keep-score-val" style="color:' + scoreColor + '">' + score.toFixed(1) + '</div>';
  html += '<div class="pc-keep-score-bar-wrap"><div class="pc-keep-score-bar" style="width:' + scorePct + '%;background:' + scoreColor + '"></div></div>';
  html += '</div>';
  
  // Component breakdown
  html += '<div class="pc-keep-breakdown">';
  
  if (isV2) {
    // V2.2: 5 components + age multiplier
    
    // 1. Weighted 3-Yr FPPG (40%)
    html += '<div class="pc-keep-factor">';
    html += '<span class="pc-keep-factor-label">3-Yr FPPG</span>';
    html += '<span class="pc-keep-factor-val">' + (comp.weighted_fppg_raw || 0).toFixed(1) + '</span>';
    html += '<span class="pc-keep-factor-detail">(40% wt, norm: ' + (comp.weighted_fppg_normalized || 0).toFixed(0) + ')</span>';
    html += '</div>';
    
    // 2. Projected FPPG (20%)
    html += '<div class="pc-keep-factor">';
    html += '<span class="pc-keep-factor-label">Proj FPPG</span>';
    html += '<span class="pc-keep-factor-val">' + (comp.proj_fppg_raw || 0).toFixed(1) + '</span>';
    html += '<span class="pc-keep-factor-detail">(20% wt, norm: ' + (comp.proj_fppg_normalized || 0).toFixed(0) + ')</span>';
    html += '</div>';
    
    // 3. 3-Yr Availability (20%)
    html += '<div class="pc-keep-factor">';
    html += '<span class="pc-keep-factor-label">Availability</span>';
    html += '<span class="pc-keep-factor-val">' + (comp.availability_3yr_pct || 0).toFixed(0) + '%</span>';
    html += '<span class="pc-keep-factor-detail">(20% wt, 3-yr wtd avg, norm: ' + (comp.availability_normalized || 0).toFixed(0) + ')</span>';
    html += '</div>';
    
    // 4. Peak FPPG (10%)
    html += '<div class="pc-keep-factor">';
    html += '<span class="pc-keep-factor-label">Peak FPPG</span>';
    html += '<span class="pc-keep-factor-val">' + (comp.peak_fppg_raw || 0).toFixed(1) + '</span>';
    html += '<span class="pc-keep-factor-detail">(10% wt, career high, norm: ' + (comp.peak_fppg_normalized || 0).toFixed(0) + ')</span>';
    html += '</div>';
    
    // 5. Consistency (10%)
    html += '<div class="pc-keep-factor">';
    html += '<span class="pc-keep-factor-label">Consistency</span>';
    html += '<span class="pc-keep-factor-val">' + (comp.consistency_cv || 15).toFixed(1) + '% CV</span>';
    html += '<span class="pc-keep-factor-detail">(10% wt, lower=better, norm: ' + (comp.consistency_normalized || 0).toFixed(0) + ')</span>';
    html += '</div>';
    
    // Age multiplier (shown as info, not a weighted component)
    var age = comp.age || c.age || 27;
    var ageLabel = age <= 23 ? '+15% youth' : (age <= 29 ? 'prime' : (age <= 33 ? '-5% vet' : '-15% aging'));
    var ageColor = age <= 23 ? '#69F0AE' : (age <= 29 ? '#e0e0e0' : '#FFB74D');
    html += '<div class="pc-keep-factor" style="border-top:1px solid rgba(255,255,255,0.1);padding-top:4px;margin-top:4px">';
    html += '<span class="pc-keep-factor-label">Age Multiplier</span>';
    html += '<span class="pc-keep-factor-val" style="color:' + ageColor + '">x' + (comp.age_factor || 1.0).toFixed(2) + '</span>';
    html += '<span class="pc-keep-factor-detail">(' + ageLabel + ', age ' + age + ')</span>';
    html += '</div>';
    
  } else {
    // V1: 3 components (fallback for old data)
    var cs = c.current_season || {};
    var fppg = cs.fppg || 0;
    var proj = cs.proj_fppg || 0;
    var gp = cs.gp || 0;
    var age = c.age || 27;
    
    var blended;
    if (gp >= 10) {
      blended = 0.7 * fppg + 0.3 * proj;
    } else if (gp >= 5) {
      var w = gp / 10.0;
      blended = w * fppg + (1 - w) * proj;
    } else {
      blended = proj;
    }
    
    var expectedGP = Math.round(18 * 3.3);
    var availPct = Math.min(1.0, gp / expectedGP);
    var availFactor = Math.sqrt(availPct);
    
    var ageFactor;
    if (age <= 23) ageFactor = 1.15;
    else if (age <= 29) ageFactor = 1.00;
    else if (age <= 32) ageFactor = 0.95;
    else ageFactor = 0.85;
    
    html += '<div class="pc-keep-factor"><span class="pc-keep-factor-label">Blended FPPG</span><span class="pc-keep-factor-val">' + blended.toFixed(1) + '</span><span class="pc-keep-factor-detail">(' + (gp >= 10 ? '70/30' : (gp >= 5 ? Math.round(gp*10) + '/' + Math.round(100-gp*10) : 'proj only')) + ' actual/proj)</span></div>';
    html += '<div class="pc-keep-factor"><span class="pc-keep-factor-label">Availability</span><span class="pc-keep-factor-val">' + (availFactor * 100).toFixed(0) + '%</span><span class="pc-keep-factor-detail">(' + gp + '/' + expectedGP + ' GP)</span></div>';
    
    var ageLabel = age <= 23 ? '+15% youth' : (age <= 29 ? 'prime' : (age <= 32 ? '-5% vet' : '-15% aging'));
    var ageColor = age <= 23 ? '#69F0AE' : (age <= 29 ? '#e0e0e0' : '#FFB74D');
    html += '<div class="pc-keep-factor"><span class="pc-keep-factor-label">Age Factor</span><span class="pc-keep-factor-val" style="color:' + ageColor + '">x' + ageFactor.toFixed(2) + '</span><span class="pc-keep-factor-detail">(' + ageLabel + ')</span></div>';
  }
  
  html += '</div>'; // Close breakdown
  html += '</div>'; // Close section
  return html;
}

/* --- TRADE HISTORY --- */
function pcRenderTradeHistory(c) {
  var trades = c.trade_history || [];
  if (trades.length === 0) return '';
  
  var mgrColors = pcManagerColors;
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Trade History (' + trades.length + ')</div>';
  
  trades.forEach(function(t) {
    var fromColor = mgrColors[t.from_manager] || '#666';
    var toColor = mgrColors[t.to_manager] || '#666';
    
    html += '<div class="pc-trade-entry">';
    
    // Header: season + direction + date
    html += '<div class="pc-trade-header">';
    html += '<span class="pc-trade-season">' + esc(t.season) + '</span>';
    html += '<span class="pc-trade-flow">';
    html += '<span style="color:' + fromColor + '">' + esc(t.from_manager) + '</span>';
    html += ' &#8594; ';
    html += '<span style="color:' + toColor + '">' + esc(t.to_manager) + '</span>';
    html += '</span>';
    html += '<span class="pc-trade-date">' + esc(t.date) + '</span>';
    html += '</div>';
    
    // Trade details: what was sent with this player, what came back
    var hasSent = (t.also_sent && t.also_sent.length > 0);
    var hasReceived = (t.received_back && t.received_back.length > 0);
    var hasPicks = (t.picks && t.picks.length > 0);
    
    if (hasSent || hasReceived || hasPicks) {
      html += '<div class="pc-trade-details">';
      
      // Sent side (this player + others going same direction)
      var sentItems = [esc(c.player_name)];
      if (hasSent) {
        t.also_sent.forEach(function(p) { sentItems.push(esc(p)); });
      }
      // Add picks sent by from_manager
      if (hasPicks) {
        t.picks.forEach(function(pk) {
          if (pk.from_manager === t.from_manager) {
            sentItems.push(esc(pk.pick));
          }
        });
      }
      
      // Received side
      var recvItems = [];
      if (hasReceived) {
        t.received_back.forEach(function(p) { recvItems.push(esc(p)); });
      }
      // Add picks sent by to_manager (received by from_manager)
      if (hasPicks) {
        t.picks.forEach(function(pk) {
          if (pk.from_manager === t.to_manager) {
            recvItems.push(esc(pk.pick));
          }
        });
      }
      
      if (recvItems.length > 0) {
        html += '<div class="pc-trade-side"><span class="pc-trade-dir" style="color:' + toColor + '">&#8594; ' + esc(t.to_manager) + ' got:</span> ' + sentItems.join(', ') + '</div>';
        html += '<div class="pc-trade-side"><span class="pc-trade-dir" style="color:' + fromColor + '">&#8594; ' + esc(t.from_manager) + ' got:</span> ' + recvItems.join(', ') + '</div>';
      }
      
      html += '</div>';
    }
    
    html += '</div>';
  });
  
  html += '</div>';
  return html;
}

/* --- SPARKLINE --- */
function pcRenderSparkline(c) {
  var data = c.sparkline || [];
  if (data.length === 0) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Season Scoring</div>';
  html += '<div id="pc-filter-label" class="pc-filter-label" style="display:none"></div>';
  html += '<div id="pc-sparkline-area">';
  html += pcRenderSparklineInner(c, null);
  html += '</div></div>';
  return html;
}

function pcRenderSparklineInner(c, filterSeason) {
  var data = c.sparkline || [];
  
  // Filter to selected season, or default to current (last) season
  var filtered;
  if (filterSeason) {
    filtered = data.filter(function(g) { return g.season === filterSeason; });
  } else {
    // Default: show current season only (last season in data)
    var seasons = [];
    data.forEach(function(g) { if (seasons.indexOf(g.season) === -1) seasons.push(g.season); });
    var currentSeason = seasons.length > 0 ? seasons[seasons.length - 1] : null;
    filtered = currentSeason ? data.filter(function(g) { return g.season === currentSeason; }) : data;
  }
  
  if (filtered.length === 0) return '<div class="pc-no-data">No game data for this season</div>';
  
  var maxFp = 0;
  filtered.forEach(function(g) { if (g.fp > maxFp) maxFp = g.fp; });
  if (maxFp === 0) maxFp = 60;
  
  var barW = Math.max(2, Math.floor(100 / filtered.length * 0.85));
  
  var html = '<div class="pc-spark-container">';
  // Reference lines
  html += '<div class="pc-spark-ref" style="bottom:' + (40/maxFp*100) + '%"><span>40</span></div>';
  html += '<div class="pc-spark-ref" style="bottom:' + (20/maxFp*100) + '%"><span>20</span></div>';
  
  html += '<div class="pc-spark-bars">';
  filtered.forEach(function(g) {
    var pct = Math.max(1, g.fp / maxFp * 100);
    var color = g.injured ? '#EF5350' : (g.fp >= 40 ? '#4FC3F7' : (g.fp < 20 ? '#FF8A65' : '#78909C'));
    html += '<div class="pc-spark-bar" style="height:' + pct + '%;background:' + color + ';width:' + barW + '%" title="' + g.date + ': ' + g.fp + ' FP"></div>';
  });
  html += '</div></div>';
  
  // Legend
  html += '<div class="pc-spark-legend">';
  html += '<span><i style="background:#4FC3F7"></i>40+</span>';
  html += '<span><i style="background:#78909C"></i>20-40</span>';
  html += '<span><i style="background:#FF8A65"></i>&lt;20</span>';
  html += '<span><i style="background:#EF5350"></i>INJ</span>';
  html += '</div>';
  
  return html;
}

/* --- BOOM / BUST --- */
function pcRenderBoomBust(c) {
  var bb = c.boom_bust || {};
  if (!bb.total_games) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Boom / Bust Profile</div>';
  html += '<div id="pc-boombust-area">';
  html += pcRenderBoomBustInner(c, null);
  html += '</div></div>';
  return html;
}

function pcRenderBoomBustInner(c, filterSeason) {
  var html = '';
  var boomRate, bustRate, bestGame, worstGame, consistency, totalGames;
  
  if (filterSeason) {
    // Compute boom/bust from filtered sparkline data
    var filtered = (c.sparkline || []).filter(function(g) {
      return g.season === filterSeason && !g.injured;
    });
    var fps = filtered.map(function(g) { return g.fp; }).filter(function(fp) { return fp > 0; });
    totalGames = fps.length;
    
    if (totalGames === 0) return '<div class="pc-no-data">No game data for this season</div>';
    
    var boomCount = fps.filter(function(fp) { return fp >= 40; }).length;
    var bustCount = fps.filter(function(fp) { return fp < 20; }).length;
    boomRate = (100 * boomCount / totalGames).toFixed(1);
    bustRate = (100 * bustCount / totalGames).toFixed(1);
    bestGame = Math.max.apply(null, fps).toFixed(1);
    worstGame = Math.min.apply(null, fps).toFixed(1);
    
    // Std dev
    var mean = fps.reduce(function(a,b) { return a+b; }, 0) / fps.length;
    var variance = fps.reduce(function(a,b) { return a + (b-mean)*(b-mean); }, 0) / fps.length;
    consistency = Math.sqrt(variance).toFixed(1);
  } else {
    var bbd = c.boom_bust || {};
    boomRate = bbd.boom_rate;
    bustRate = bbd.bust_rate;
    bestGame = bbd.best_game;
    worstGame = bbd.worst_game;
    consistency = bbd.consistency_std;
    totalGames = bbd.total_games;
  }
  
  html += '<div class="pc-bb-grid">';
  
  html += '<div class="pc-bb-row">';
  html += '<div class="pc-bb-label">Boom (40+)</div>';
  html += '<div class="pc-bb-bar-wrap"><div class="pc-bb-bar pc-bb-boom" style="width:' + boomRate + '%"></div></div>';
  html += '<div class="pc-bb-pct">' + boomRate + '%</div>';
  html += '</div>';
  
  html += '<div class="pc-bb-row">';
  html += '<div class="pc-bb-label">Bust (&lt;20)</div>';
  html += '<div class="pc-bb-bar-wrap"><div class="pc-bb-bar pc-bb-bust" style="width:' + Math.max(bustRate, 2) + '%"></div></div>';
  html += '<div class="pc-bb-pct">' + bustRate + '%</div>';
  html += '</div>';
  
  html += '</div>';
  
  html += '<div class="pc-bb-footer">';
  html += '<span>Best: ' + bestGame + '</span>';
  html += '<span>Worst: ' + worstGame + '</span>';
  html += '<span>&sigma;: ' + consistency + '</span>';
  html += '</div>';
  
  return html;
}

/* --- SEASON COMPS --- */
function pcRenderSeasonComps(c) {
  var sc = c.season_comps || {};
  var career = c.career || {};
  var bd = career.season_breakdown || [];
  if (bd.length < 2) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Season Trend <span class="pc-tap-hint">(tap a season to filter)</span></div>';
  
  // Find max FPPG for scaling, with a floor so bars aren't always 100%
  var maxFppg = 0;
  bd.forEach(function(s) { if (s.fppg > maxFppg) maxFppg = s.fppg; });
  maxFppg = Math.max(maxFppg * 1.1, 30); // 10% headroom, min 30
  
  html += '<div class="pc-trend-chart">';
  bd.forEach(function(s) {
    var pct = Math.max(4, (s.fppg / maxFppg * 100)).toFixed(0);
    var isCurrent = (s.season === bd[bd.length-1].season);
    var barCls = isCurrent ? 'pc-trend-bar pc-trend-current' : 'pc-trend-bar';
    // Season label: "21-22" format
    var parts = s.season.split('-');
    var yrLabel = parts[0].slice(2) + '-' + (parts[1].length === 2 ? parts[1] : parts[1].slice(2));
    
    html += '<div class="pc-trend-col pc-trend-clickable" data-season="' + s.season + '">';
    html += '<div class="pc-trend-val">' + s.fppg.toFixed(1) + '</div>';
    html += '<div class="pc-trend-gp">' + s.gp + ' GP</div>';
    html += '<div class="pc-trend-bar-area"><div class="' + barCls + '" style="height:' + pct + '%;"></div></div>';
    html += '<div class="pc-trend-yr">' + yrLabel + '</div>';
    html += '</div>';
  });
  html += '</div>';
  
  // Trend description
  if (sc.description) {
    var trendIcon = sc.trend === 'improving' ? '&#9650;' : (sc.trend === 'declining' ? '&#9660;' : '&#9670;');
    var trendColor = sc.trend === 'improving' ? '#4FC3F7' : (sc.trend === 'declining' ? '#EF5350' : '#78909C');
    html += '<div class="pc-trend-desc" style="color:' + trendColor + '">' + trendIcon + ' ' + esc(sc.description) + '</div>';
  }
  
  html += '</div>';
  return html;
}

/* --- OWNERSHIP TIMELINE --- */
function pcRenderTimeline(c) {
  var tl = c.ownership_timeline || [];
  if (tl.length === 0) return '';
  
  var mgrColors = pcManagerColors;
  
  function acqPhrase(via, mgr) {
    if (via === 'draft') return 'Drafted by ' + mgr;
    if (via === 'keeper') return 'Kept by ' + mgr;
    if (via === 'trade') return 'Traded to ' + mgr;
    if (via === 'waiver') return 'Picked up by ' + mgr;
    return mgr;
  }
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Ownership History</div>';
  html += '<div class="pc-tl-scroll">';
  
  tl.forEach(function(season, sIdx) {
    var events = season.events || [];
    var yrParts = season.season.split("-");
    var yrLabel = yrParts[0].slice(2) + '-' + (yrParts[1].length === 2 ? yrParts[1] : yrParts[1].slice(2));
    
    if (sIdx > 0) html += '<div class="pc-tl-divider"></div>';
    
    html += '<div class="pc-tl-season">';
    html += '<div class="pc-tl-season-yr">' + yrLabel + '</div>';
    html += '<div class="pc-tl-events">';
    
    events.forEach(function(e, eIdx) {
      var color = mgrColors[e.manager] || "#666";
      var phrase = acqPhrase(e.acquired_via, esc(e.manager));
      
      if (eIdx > 0) html += '<div class="pc-tl-arrow">&#8594;</div>';
      
      html += '<div class="pc-tl-card" style="border-left: 3px solid ' + color + ';">';
      html += '<div class="pc-tl-card-phrase">' + phrase + '</div>';
      html += '</div>';
    });
    
    html += '</div>';
    html += '</div>';
  });
  
  html += '</div>';
  html += '</div>';
  return html;
}

/* --- DRAFT ROI --- */
function pcRenderDraftROI(c) {
  var dh = c.draft_history || [];
  if (dh.length === 0) return '';
  
  // Only show non-keeper drafts (first draft + any re-drafts)
  var notable = dh.filter(function(d) { return !d.is_keeper && d.actual_fppg; });
  if (notable.length === 0) {
    // Show the original draft at least
    notable = dh.filter(function(d) { return !d.is_keeper; });
  }
  if (notable.length === 0) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Draft ROI</div>';
  
  notable.forEach(function(d) {
    var roiColors = {"Steal":"#4FC3F7","Good Value":"#81C784","Fair":"#FFB74D","Bust":"#EF5350","Disaster":"#B71C1C"};
    var roiColor = roiColors[d.roi_label] || "#78909C";
    
    html += '<div class="pc-draft-entry">';
    html += '<div class="pc-draft-top">';
    html += '<span class="pc-draft-pick">Rd ' + d.round + ', Pick ' + d.pick_number + '</span>';
    html += '<span class="pc-draft-season">' + d.season + ' by ' + esc(d.manager) + '</span>';
    html += '</div>';
    
    if (d.actual_fppg && d.expected_fppg) {
      html += '<div class="pc-draft-roi">';
      html += '<span>Expected: ' + d.expected_fppg.toFixed(1) + '</span>';
      html += '<span>Actual: ' + d.actual_fppg.toFixed(1) + '</span>';
      html += '<span class="pc-draft-roi-badge" style="background:' + roiColor + '">' + (d.roi > 0 ? '+' : '') + d.roi.toFixed(1) + ' ' + d.roi_label + '</span>';
      html += '</div>';
    }
    
    html += '</div>';
  });
  
  html += '</div>';
  return html;
}

/* --- INJURY PROFILE --- */
function pcRenderInjury(c) {
  var ip = c.injury_profile || {};
  var rates = ip.season_rates || [];
  if (rates.length === 0) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Injury Profile</div>';
  
  html += '<div class="pc-inj-summary">';
  html += '<div class="pc-stat-cell"><div class="pc-stat-val">' + ip.career_injury_rate + '%</div><div class="pc-stat-lbl">Career Miss Rate</div></div>';
  html += '<div class="pc-stat-cell"><div class="pc-stat-val">' + ip.career_games_missed + '</div><div class="pc-stat-lbl">Games Missed</div></div>';
  html += '<div class="pc-stat-cell"><div class="pc-stat-val">' + ip.career_games_scheduled + '</div><div class="pc-stat-lbl">Scheduled</div></div>';
  html += '</div>';
  
  // Mini bar chart of injury rates by season
  html += '<div class="pc-inj-chart">';
  rates.forEach(function(r) {
    var barH = Math.max(2, r.injury_rate);
    var color = r.injury_rate > 20 ? '#EF5350' : (r.injury_rate > 10 ? '#FFB74D' : '#81C784');
    html += '<div class="pc-inj-col">';
    html += '<div class="pc-inj-rate">' + r.injury_rate + '%</div>';
    html += '<div class="pc-inj-bar" style="height:' + barH + 'px;background:' + color + ';"></div>';
    html += '<div class="pc-inj-yr">' + r.season.split("-")[0].slice(2) + '-' + r.season.split("-")[1] + '</div>';
    html += '</div>';
  });
  html += '</div>';
  
  if (ip.current_injury_streak > 0) {
    html += '<div class="pc-inj-streak">Currently on a ' + ip.current_injury_streak + '-game injury streak</div>';
  }
  
  html += '</div>';
  return html;
}

/* --- RECORD BOOK --- */
function pcRenderRecords(c) {
  var rb = c.record_book || [];
  if (rb.length === 0) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Record Book (' + rb.length + ' entries)</div>';
  
  // Show top 8 entries
  var show = rb.slice(0, 8);
  show.forEach(function(r) {
    var medal = r.rank === 1 ? '&#127942;' : (r.rank <= 3 ? '&#129351;' : '');
    html += '<div class="pc-rb-entry">';
    html += '<span class="pc-rb-rank">#' + r.rank + ' ' + medal + '</span>';
    html += '<span class="pc-rb-name">' + esc(r.record) + '</span>';
    if (r.value != null) {
      html += '<span class="pc-rb-val">' + (typeof r.value === "number" ? r.value.toFixed(1) : r.value) + '</span>';
    }
    html += '</div>';
  });
  
  if (rb.length > 8) {
    html += '<div class="pc-rb-more">+ ' + (rb.length - 8) + ' more records</div>';
  }
  
  html += '</div>';
  return html;
}

/* --- MILESTONES --- */
function pcRenderMilestones(c) {
  var ms = c.milestones || [];
  if (ms.length === 0) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Milestones</div>';
  
  ms.forEach(function(m) {
    var pct = (m.current / m.target * 100).toFixed(0);
    html += '<div class="pc-ms-entry">';
    html += '<div class="pc-ms-label">' + esc(m.label) + '</div>';
    html += '<div class="pc-ms-bar-wrap"><div class="pc-ms-bar" style="width:' + pct + '%"></div></div>';
    if (m.games_needed) {
      html += '<div class="pc-ms-eta">~' + m.games_needed + ' games at current pace</div>';
    }
    html += '</div>';
  });
  
  html += '</div>';
  return html;
}

/* --- LAST 10 GAMES --- */
function pcRenderLast10(c) {
  var games = c.last_10 || [];
  if (games.length === 0) return '';
  
  var html = '<div class="pc-section">';
  html += '<div class="pc-section-title">Last 10 Games</div>';
  html += '<div class="pc-l10-grid">';
  
  games.forEach(function(g) {
    var fpCls = g.injured ? 'pc-l10-inj' : (g.fp >= 40 ? 'pc-l10-boom' : (g.fp < 20 ? 'pc-l10-bust' : ''));
    html += '<div class="pc-l10-row">';
    html += '<span class="pc-l10-date">' + g.date.slice(5) + '</span>';
    html += '<span class="pc-l10-opp">' + esc(g.opponent) + '</span>';
    html += '<span class="pc-l10-fp ' + fpCls + '">' + (g.injured ? 'INJ' : g.fp.toFixed(1)) + '</span>';
    html += '</div>';
  });
  
  html += '</div></div>';
  return html;
}

// --- Season filter state ---
var pcCurrentFilter = null; // null = show all (current season), or a season key like "2022-23"
var pcCurrentCard = null;   // reference to current card data for re-rendering

function pcFilterSeason(el, season) {
  if (!pcCurrentCard) return;
  
  // Toggle: tap same season again to reset
  if (pcCurrentFilter === season) {
    pcCurrentFilter = null;
  } else {
    pcCurrentFilter = season;
  }
  
  // Update trend bar highlight
  var cols = document.querySelectorAll('.pc-trend-clickable');
  cols.forEach(function(col) {
    col.classList.remove('pc-trend-selected');
    if (pcCurrentFilter && col.getAttribute('data-season') === pcCurrentFilter) {
      col.classList.add('pc-trend-selected');
    }
  });
  
  // Re-render sparkline with filtered data
  var sparkEl = document.getElementById('pc-sparkline-area');
  if (sparkEl) {
    sparkEl.innerHTML = pcRenderSparklineInner(pcCurrentCard, pcCurrentFilter);
  }
  
  // Re-render boom/bust with filtered data
  var bbEl = document.getElementById('pc-boombust-area');
  if (bbEl) {
    bbEl.innerHTML = pcRenderBoomBustInner(pcCurrentCard, pcCurrentFilter);
  }
  
  // Update filter label
  var labelEl = document.getElementById('pc-filter-label');
  if (labelEl) {
    if (pcCurrentFilter) {
      labelEl.innerHTML = 'Showing: ' + pcCurrentFilter + ' <span class="pc-filter-clear" id="pc-filter-clear-btn">&times; clear</span>';
      labelEl.style.display = 'block';
      // Attach click handler for clear button
      var clearBtn = document.getElementById('pc-filter-clear-btn');
      if (clearBtn) {
        clearBtn.onclick = function() { pcFilterSeason(null, pcCurrentFilter); };
      }
    } else {
      labelEl.style.display = 'none';
    }
  }
  
  // Update header stats (FPPG, Tot FP, GP) to match selected season
  var hdrFppg = document.getElementById('pc-hdr-fppg');
  var hdrTfp = document.getElementById('pc-hdr-totalfp');
  var hdrGp = document.getElementById('pc-hdr-gp');
  if (hdrFppg && hdrTfp && hdrGp) {
    var cs = pcCurrentCard.current_season || {};
    var career = pcCurrentCard.career || {};
    var bd = career.season_breakdown || [];
    
    if (pcCurrentFilter) {
      // Find the selected season in breakdown
      var match = null;
      bd.forEach(function(s) { if (s.season === pcCurrentFilter) match = s; });
      if (match) {
        hdrFppg.querySelector('.pc-stat-val').textContent = match.fppg.toFixed(1);
        hdrTfp.querySelector('.pc-stat-val').textContent = Math.round(match.total_fp).toLocaleString();
        hdrGp.querySelector('.pc-stat-val').textContent = match.gp;
        // Hide rank badges for historical seasons (ranks are current-season only)
        var ranks = [hdrFppg.querySelector('.pc-stat-rank'), hdrTfp.querySelector('.pc-stat-rank')];
        ranks.forEach(function(r) { if (r) r.style.display = 'none'; });
      }
    } else {
      // Reset to current season (default)
      hdrFppg.querySelector('.pc-stat-val').textContent = (cs.fppg || 0).toFixed(1);
      hdrTfp.querySelector('.pc-stat-val').textContent = Math.round(cs.total_fp || 0).toLocaleString();
      hdrGp.querySelector('.pc-stat-val').textContent = (cs.gp || 0);
      // Restore current-season rank badges
      var ranks = [hdrFppg.querySelector('.pc-stat-rank'), hdrTfp.querySelector('.pc-stat-rank')];
      ranks.forEach(function(r) { if (r) r.style.display = ''; });
    }
  }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', pcInit);
} else {
  pcInit();
}
'''
    )


def get_player_card_css() -> str:
    """Return CSS for the player card modal."""
    return '''
/* ================================================================
   PLAYER CARD MODAL
   ================================================================ */

/* --- Modal Overlay --- */
.pc-modal {
  display: none;
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  z-index: 10000;
}
.pc-modal.pc-open {
  display: flex;
  align-items: flex-end;
  justify-content: center;
}

.pc-backdrop {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.7);
  -webkit-backdrop-filter: blur(4px);
  backdrop-filter: blur(4px);
}

/* --- Sheet (bottom-sheet on mobile, centered card on desktop) --- */
.pc-sheet {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 480px;
  max-height: 88vh;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  background: #1a1a2e;
  border-radius: 16px 16px 0 0;
  padding: 20px 16px 32px;
  color: #e0e0e0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  animation: pcSlideUp 0.25s ease-out;
}

@keyframes pcSlideUp {
  from { transform: translateY(100%); opacity: 0; }
  to   { transform: translateY(0); opacity: 1; }
}

@media (min-width: 600px) {
  .pc-sheet {
    border-radius: 16px;
    margin-bottom: 20px;
    max-height: 85vh;
    animation: pcFadeIn 0.2s ease-out;
  }
  .pc-modal.pc-open {
    align-items: center;
  }
}

@keyframes pcFadeIn {
  from { transform: scale(0.95); opacity: 0; }
  to   { transform: scale(1); opacity: 1; }
}

/* --- Close Button --- */
.pc-close {
  position: sticky;
  top: 0;
  float: right;
  background: rgba(255,255,255,0.1);
  border: none;
  color: #a0a0a0;
  font-size: 1.5rem;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
  transition: background 0.15s;
}
.pc-close:hover {
  background: rgba(255,255,255,0.2);
  color: #fff;
}

/* --- Header --- */
.pc-header {
  padding-bottom: 12px;
  margin-bottom: 14px;
}
.pc-header-top {
  margin-bottom: 8px;
}
.pc-name-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.pc-name {
  font-size: 1.4rem;
  font-weight: 800;
  color: #fff;
  letter-spacing: -0.3px;
  line-height: 1.2;
}
.pc-rank {
  font-size: 0.85rem;
  font-weight: 700;
  color: #808080;
  flex-shrink: 0;
}
.pc-meta {
  font-size: 0.78rem;
  color: #a0a0a0;
  margin-top: 2px;
}
.pc-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.pc-arch-badge, .pc-tier-badge {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 3px 8px;
  border-radius: 4px;
  text-transform: uppercase;
}

/* --- Stat Bar --- */
.pc-stat-bar {
  display: flex;
  justify-content: space-between;
  background: rgba(255,255,255,0.05);
  border-radius: 8px;
  padding: 10px 8px;
  margin-bottom: 16px;
}
.pc-stat-cell {
  text-align: center;
  flex: 1;
}
.pc-stat-val {
  font-size: 1.1rem;
  font-weight: 800;
  color: #fff;
  line-height: 1.2;
}
.pc-stat-rank {
  font-size: 0.55rem;
  font-weight: 600;
  color: #4FC3F7;
  line-height: 1;
}
.pc-stat-lbl {
  font-size: 0.55rem;
  color: #808080;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* --- Keepability Breakdown --- */
.pc-keep-score-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.pc-keep-score-val {
  font-size: 1.2rem;
  font-weight: 800;
  width: 48px;
  flex-shrink: 0;
}
.pc-keep-score-bar-wrap {
  flex: 1;
  height: 8px;
  background: rgba(255,255,255,0.08);
  border-radius: 4px;
  overflow: hidden;
}
.pc-keep-score-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}
.pc-keep-breakdown {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.pc-keep-section-label {
  font-size: 0.58rem;
  font-weight: 700;
  color: #4FC3F7;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 6px;
  margin-bottom: 2px;
  padding-left: 6px;
}
.pc-keep-factor {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.62rem;
  padding: 3px 6px;
  background: rgba(255,255,255,0.03);
  border-radius: 3px;
}
.pc-keep-factor.pc-keep-subtotal {
  background: rgba(79, 195, 247, 0.1);
  border-left: 2px solid #4FC3F7;
  font-weight: 600;
}
.pc-keep-factor-label {
  color: #a0a0a0;
  width: 90px;
  flex-shrink: 0;
}
.pc-keep-factor-val {
  color: #e0e0e0;
  font-weight: 700;
  width: 40px;
  flex-shrink: 0;
}
.pc-keep-factor-detail {
  color: #606060;
  font-size: 0.55rem;
}

/* --- Trade History --- */
.pc-trade-entry {
  background: rgba(255,255,255,0.03);
  border-radius: 4px;
  margin-bottom: 6px;
  padding: 6px 8px;
}
.pc-trade-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.65rem;
  margin-bottom: 2px;
}
.pc-trade-season {
  color: #808080;
  width: 42px;
  flex-shrink: 0;
  font-weight: 600;
}
.pc-trade-flow {
  flex: 1;
  font-weight: 600;
}
.pc-trade-date {
  color: #606060;
  font-size: 0.55rem;
  flex-shrink: 0;
}
.pc-trade-details {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid rgba(255,255,255,0.06);
}
.pc-trade-side {
  font-size: 0.58rem;
  color: #a0a0a0;
  padding: 1px 0;
}
.pc-trade-dir {
  font-weight: 600;
  font-size: 0.55rem;
}

/* --- Sections --- */
.pc-section {
  margin-bottom: 18px;
}
.pc-section-title {
  font-size: 0.72rem;
  font-weight: 700;
  color: #808080;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}

/* --- Sparkline --- */
.pc-spark-container {
  position: relative;
  height: 80px;
  background: rgba(255,255,255,0.03);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 6px;
}
.pc-spark-bars {
  display: flex;
  align-items: flex-end;
  height: 100%;
  gap: 1px;
  padding: 4px 2px;
}
.pc-spark-bar {
  border-radius: 1px 1px 0 0;
  min-width: 2px;
  transition: opacity 0.15s;
}
.pc-spark-bar:hover {
  opacity: 0.7;
}
.pc-spark-ref {
  position: absolute;
  left: 0; right: 0;
  border-top: 1px dashed rgba(255,255,255,0.1);
  pointer-events: none;
}
.pc-spark-ref span {
  font-size: 0.5rem;
  color: rgba(255,255,255,0.2);
  position: absolute;
  right: 4px;
  top: -8px;
}
.pc-spark-legend {
  display: flex;
  justify-content: center;
  gap: 12px;
  font-size: 0.55rem;
  color: #808080;
}
.pc-spark-legend i {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  vertical-align: middle;
  margin-right: 3px;
}

/* --- Boom / Bust --- */
.pc-bb-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pc-bb-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pc-bb-label {
  font-size: 0.68rem;
  color: #a0a0a0;
  width: 70px;
  flex-shrink: 0;
}
.pc-bb-bar-wrap {
  flex: 1;
  height: 14px;
  background: rgba(255,255,255,0.05);
  border-radius: 7px;
  overflow: hidden;
}
.pc-bb-bar {
  height: 100%;
  border-radius: 7px;
  transition: width 0.3s;
}
.pc-bb-boom { background: linear-gradient(90deg, #4FC3F7, #29B6F6); }
.pc-bb-bust { background: linear-gradient(90deg, #FF8A65, #EF5350); }
.pc-bb-pct {
  font-size: 0.72rem;
  font-weight: 700;
  color: #e0e0e0;
  width: 40px;
  text-align: right;
}
.pc-bb-footer {
  display: flex;
  justify-content: space-between;
  font-size: 0.6rem;
  color: #808080;
  margin-top: 4px;
  padding-top: 4px;
}

/* --- Season Trend --- */
.pc-trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  padding: 0 4px;
  margin-bottom: 6px;
}
.pc-trend-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}
.pc-trend-clickable {
  cursor: pointer;
  border-radius: 4px;
  padding: 2px 0;
  transition: background 0.15s;
}
.pc-trend-clickable:hover {
  background: rgba(255,255,255,0.06);
}
.pc-trend-clickable.pc-trend-selected {
  background: rgba(79,195,247,0.15);
  box-shadow: 0 0 0 1px rgba(79,195,247,0.3);
}
.pc-trend-val {
  font-size: 0.6rem;
  font-weight: 700;
  color: #e0e0e0;
  white-space: nowrap;
}
.pc-trend-gp {
  font-size: 0.45rem;
  color: #808080;
  white-space: nowrap;
  margin-bottom: 1px;
}
.pc-trend-bar-area {
  width: 100%;
  height: 50px;
  display: flex;
  align-items: flex-end;
}
.pc-trend-bar {
  width: 100%;
  background: #3a5a7a;
  border-radius: 2px 2px 0 0;
  min-height: 2px;
}
.pc-trend-current {
  background: #4FC3F7 !important;
}
.pc-trend-selected .pc-trend-bar {
  background: #4FC3F7 !important;
}
.pc-trend-yr {
  font-size: 0.48rem;
  color: #808080;
  margin-top: 2px;
  white-space: nowrap;
}
.pc-trend-desc {
  font-size: 0.68rem;
  font-weight: 600;
  text-align: center;
  padding: 4px;
}
.pc-tap-hint {
  font-weight: 400;
  font-size: 0.55rem;
  color: #606060;
  font-style: italic;
  text-transform: none;
  letter-spacing: 0;
}

/* --- Filter label --- */
.pc-filter-label {
  font-size: 0.62rem;
  color: #4FC3F7;
  text-align: center;
  padding: 4px 8px;
  margin-bottom: 6px;
  background: rgba(79,195,247,0.08);
  border-radius: 4px;
}
.pc-filter-clear {
  cursor: pointer;
  color: #a0a0a0;
  margin-left: 6px;
  font-size: 0.72rem;
}
.pc-filter-clear:hover {
  color: #fff;
}

/* --- No data placeholder --- */
.pc-no-data {
  font-size: 0.65rem;
  color: #606060;
  text-align: center;
  padding: 16px 8px;
  font-style: italic;
}

/* --- Ownership Timeline --- */
.pc-tl-scroll {
  display: flex;
  overflow-x: auto;
  gap: 0;
  padding-bottom: 6px;
  -webkit-overflow-scrolling: touch;
}
.pc-tl-scroll::-webkit-scrollbar {
  height: 3px;
}
.pc-tl-scroll::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.15);
  border-radius: 2px;
}
.pc-tl-season {
  flex-shrink: 0;
  text-align: center;
}
.pc-tl-season-yr {
  font-size: 0.55rem;
  font-weight: 700;
  color: #a0a0a0;
  margin-bottom: 4px;
}
.pc-tl-events {
  display: flex;
  align-items: center;
  gap: 2px;
}
.pc-tl-card {
  background: rgba(255,255,255,0.05);
  border-radius: 4px;
  padding: 4px 8px;
}
.pc-tl-card-phrase {
  font-size: 0.58rem;
  color: #c0c0c0;
  white-space: nowrap;
}
.pc-tl-arrow {
  font-size: 0.55rem;
  color: #606060;
  padding: 0 1px;
  flex-shrink: 0;
}
.pc-tl-divider {
  width: 1px;
  align-self: stretch;
  background: rgba(255,255,255,0.08);
  margin: 0 6px;
  flex-shrink: 0;
}

/* --- Draft ROI --- */
.pc-draft-entry {
  background: rgba(255,255,255,0.04);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
}
.pc-draft-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.pc-draft-pick {
  font-size: 0.75rem;
  font-weight: 700;
  color: #e0e0e0;
}
.pc-draft-season {
  font-size: 0.62rem;
  color: #808080;
}
.pc-draft-roi {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 0.62rem;
  color: #a0a0a0;
}
.pc-draft-roi-badge {
  font-size: 0.58rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  color: #1a1a1a;
}

/* --- Injury Profile --- */
.pc-inj-summary {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}
.pc-inj-chart {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  margin-bottom: 4px;
}
.pc-inj-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.pc-inj-rate {
  font-size: 0.48rem;
  color: #a0a0a0;
}
.pc-inj-bar {
  width: 100%;
  max-width: 20px;
  border-radius: 2px 2px 0 0;
  min-height: 2px;
}
.pc-inj-yr {
  font-size: 0.5rem;
  color: #808080;
}
.pc-inj-streak {
  font-size: 0.65rem;
  color: #EF5350;
  text-align: center;
  margin-top: 4px;
  font-weight: 600;
}

/* --- Record Book --- */
.pc-rb-entry {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  font-size: 0.68rem;
}
.pc-rb-rank {
  font-weight: 700;
  color: #C9A227;
  width: 36px;
  flex-shrink: 0;
}
.pc-rb-name {
  flex: 1;
  color: #e0e0e0;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pc-rb-val {
  font-weight: 700;
  color: #4FC3F7;
  flex-shrink: 0;
}
.pc-rb-more {
  font-size: 0.6rem;
  color: #808080;
  text-align: center;
  padding-top: 4px;
  font-style: italic;
}

/* --- Milestones --- */
.pc-ms-entry {
  margin-bottom: 8px;
}
.pc-ms-label {
  font-size: 0.68rem;
  color: #e0e0e0;
  margin-bottom: 4px;
}
.pc-ms-bar-wrap {
  height: 6px;
  background: rgba(255,255,255,0.08);
  border-radius: 3px;
  overflow: hidden;
}
.pc-ms-bar {
  height: 100%;
  background: linear-gradient(90deg, #C9A227, #FFD700);
  border-radius: 3px;
}
.pc-ms-eta {
  font-size: 0.55rem;
  color: #808080;
  margin-top: 2px;
}

/* --- Last 10 Games --- */
.pc-l10-grid {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.pc-l10-row {
  display: flex;
  align-items: center;
  padding: 4px 6px;
  background: rgba(255,255,255,0.03);
  border-radius: 3px;
}
.pc-l10-date {
  font-size: 0.62rem;
  color: #808080;
  width: 42px;
  flex-shrink: 0;
}
.pc-l10-opp {
  flex: 1;
  font-size: 0.68rem;
  color: #a0a0a0;
}
.pc-l10-fp {
  font-size: 0.75rem;
  font-weight: 700;
  color: #e0e0e0;
  width: 40px;
  text-align: right;
}
.pc-l10-boom { color: #4FC3F7; }
.pc-l10-bust { color: #FF8A65; }
.pc-l10-inj { color: #EF5350; font-size: 0.62rem; }

/* --- Scrollbar styling --- */
.pc-sheet::-webkit-scrollbar {
  width: 4px;
}
.pc-sheet::-webkit-scrollbar-track {
  background: transparent;
}
.pc-sheet::-webkit-scrollbar-thumb {
  background: rgba(255,255,255,0.15);
  border-radius: 2px;
}

/* --- Light mode override (for non-dark-mode users) --- */
@media (prefers-color-scheme: light) {
  .pc-sheet {
    background: #1a1a2e;
    color: #e0e0e0;
  }
}
'''
