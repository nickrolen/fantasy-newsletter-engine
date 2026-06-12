# Development Changelog

This file preserves the detailed development history that was originally tracked in README.md and PROJECTSTRUCTURE.md before the project was repackaged for public release.

---

## From README.md (high-level changelog)

## Changelog

### March 2026

**March 24, 2026 - Playoff System**

Added full playoff support to the newsletter pipeline. The 21-week regular season is over; Weeks 22-23 are the playoff bracket (semifinals + finals).

- **New module: `simulator_playoff_odds.py`** -- Monte Carlo bracket simulator. Simulates Week 22 semifinals, dynamically builds Week 23 finals (semi winners play championship, losers play consolation). Outputs championship probability, semifinal win probs, finish distribution (1st-4th), most likely championship matchup.
- **`report_builder.py`** -- Automatic routing: `week >= regular_season_weeks` triggers the playoff simulator instead of regular title odds. Week 21 (final regular season week) gets the bracket preview since standings are locked.
- **`format_stats_report.py`** -- Section 7 becomes "Playoff Championship Odds" with semifinal matchup table, championship probability table, most likely finals matchup, plus existing team health/scoring trends/keeper quality data.
- **`SCHEDULE.json`** -- Added `regular_season_weeks: 21` and `playoff_start_week: 22` metadata. Total weeks updated to 23.
- **`stats_corner_viz.py`** -- Added `'2025-26': [22, 23]` to `PLAYOFF_WEEKS` for historical results grid.
- **`newsletter_template.md`** -- Added Playoff Edition Addendum: section-by-section modifications, language reminders, Week 23 special notes.
- **`NEWSLETTER_PROMPTS_WEEK22.md`** -- Complete playoff-edition 3-part prompts with bracket framing and playoff verification checklist.

### February 2026

**February 13, 2026 - Newsletter Quality Audit & Viz Enhancements**

Comprehensive audit of Week 16 newsletter output. Fixed rendering bugs, eliminated hallucination-prone patterns in the template, and added two new Record Book visualizations.

**HTML Generator Fixes (`newsletter_html_generator.py`):**
- Nav links: Replaced `<a href="#section-id">` anchor links with `javascript:void(0)` + `scrollIntoView({behavior:'smooth'})`. Fixes "Open external link" warnings in iMessage, Claude.ai artifact preview, and other sandboxed HTML viewers.
- Pagination: Fixed keyword matching for 30-row season performer tables. Trigger checked for `'Season Best'`/`'Season Worst'` but actual headers say `'Best Performers'`/`'Worst Performers'`. Added both variants. All 4 tables now paginate (10 rows/page).
- Subsection headers: Increased `**bold**` header length limit from 60 to 120 chars. Long Around the NBA headlines (e.g., trade recaps) were falling through to `<p class="stat-line">` rendering instead of `<h4>`.
- Compatibility: Parser regex updated to accept `def.`, `--`, and `-` in matchup headers; `->`, `--`, and `:` in report card grades (with optional `(previously X)` suffix).
- Stats Corner table filter: Added `SKIP_TABLES` list to suppress 6 tables now rendered as interactive visualizations. Viz injection split into `position="top"` (4 blocks above prose) and `position="bottom"` (Record Book below prose).

**Stats Corner Viz Enhancements (`stats_corner_viz.py`):**
- Record Book default tab changed from "Team" to "Manager" (less vertical space on load).
- New: Historical League Standings grid -- 4 manager rows x 9 season columns showing each season's record with color-coded rank (green 1st, blue 2nd, orange 3rd, gray 4th) + trophy/medal icons. Summary columns tally 1st/2nd/3rd place finishes per manager. Current season column highlighted.
- New: Historical Luck Index grid -- same 4x9 layout showing luck index per season, color-coded by severity (red <= -4, orange <= -2, gray neutral, blue >= +2, green >= +4). Career totals in rightmost column. Legend bar at bottom.
- Both tables injected into Record Book Manager tab, above existing "Most Total Injury Games" records.
- `render_stats_corner_visualizations()` now accepts `position` parameter for top/bottom split.
- `render_record_book()` now accepts `historical_luck` parameter for the two new grid tables.

**Newsletter Template Anti-Hallucination Rules (`newsletter_template.md`):**
- Rule 13 (NEW): Superlative/historical claim verification. Every "most", "worst", "best", "in league history" must be verified against extracted historical data before writing. Prompted by LLM claiming "-3.6 luck index is the most unlucky season ever" when data shows 5 worse seasons.
- Rule 14 (NEW): Magic number definition. Explicitly defines magic number of N = any combination of N events (wins + rival losses). Prompted by LLM writing "one win clinches" when magic number was 2.
- Rule 15 (NEW): Elimination status verification. Must verify math before claiming a team is or isn't eliminated. Prompted by LLM writing a team was "not quite eliminated" when they'd been eliminated for weeks.
- Rule 16 (NEW): Trade grade direction verification. Mandatory re-read of `side_a.sent_picks` vs `side_b.sent_picks` after writing each trade grade. Prompted by LLM reversing who gained/lost draft capital (second occurrence of this error).
- Rumor Mill KEY RULES: Added "BULLET FORMAT IS MANDATORY" enforcement with wrong vs correct examples. All Trade Ideas, Free Agent Targets, Hot Streaks, and Slump Watch items must use `- ` bullet format, never flowing paragraphs (paragraphs break card-style HTML rendering).
- Final checklist expanded: 5 new items covering superlatives, magic numbers, elimination status, trade grade direction, and Rumor Mill bullet format.

**Format Stats Report cleanup (`format_stats_report.py`):**
- Removed 6 Stats Corner table generation blocks (Positional Scoring Breakdown, Season Waiver Wire ROI, Bench Report, Record Book Snapshot, Keeper Watch, Draft Value Tracker) -- all now rendered as interactive visualizations by the HTML generator. Underlying JSON data generation unchanged.

**Modified files:** `newsletter_html_generator.py`, `stats_corner_viz.py`, `newsletter_template.md`, `format_stats_report.py`

**February 10, 2026 - Stats Corner Visualizations & Keeper Tier Refactor**

New module `stats_corner_viz.py` renders 4 interactive HTML visualization cards in the Stats Corner section of the newsletter: Positional Scoring Breakdown (donut charts), Draft Value Tracker (diverging bars with trade/drop/claimed status badges), Waiver Wire ROI (summary stats + notable adds table), and Keeper Watch (tiered chip layout). All visualizations are mobile-responsive with tabbed manager views.

Keeper tier system refactored from hard-coded FPPG/age thresholds to score-based keepability system consistent with `rumor_mill_analyzer.compute_trade_value()`: `score = blended_fppg x sqrt(availability) x age_factor`. Fixes cases like Jokic (63 FPPG, age 30) being incorrectly tier'd as "Strong Hold" instead of "Lock."

Draft value tracker enhanced with granular player status detection (rostered/traded/claimed/dropped) by cross-referencing draft picks, current rosters, and waiver files. Newsletter HTML generator updated with `--stats-report` CLI arg to auto-inject visualizations.

New files: `modules/stats_corner_viz.py`. Modified files: `report_builder.py`, `newsletter_html_generator.py`, `__init__.py`

**February 9, 2026 - Stats Corner Expansion + Draft Data Architecture**

Four new Stats Corner tables added (14 total): Bench Report (season bench production + blunders), Record Book Snapshot (season vs all-time records), Keeper Watch (top 6 per team with tier labels), and Draft Value Tracker (grades R1-7 picks as Steal/Good Value/Fair/Bust against expected FPPG).

Positional classification refactored: `classify_position_group()` moved from `weekly_stats.py` to `data_loader.py` with majority-voting logic replacing the old "biggest position wins" priority system. 11 players reclassified to more intuitive positions.

Draft data architecture overhauled: New `config/DRAFT_PICKS_CURRENT.json` holds current season draft picks. Historical `all_drafts.json` cleaned to past seasons only. Fixed `pull_historical_data.py` `extract_draft()` -- Yahoo returns `player_id` (int) not `player_key` (str), so `lg.player_details()` was silently failing for all 416 historical picks. All draft picks across 9 seasons now have player names.

New scripts: `pull_current_draft.py` (Yahoo API draft pull), `backfill_draft_names.py` (historical name resolution), `fix_positional_records.py` (one-time RECORDS fix).

Modified files: `data_loader.py`, `weekly_stats.py`, `__init__.py`, `rumor_mill_analyzer.py`, `report_builder.py`, `format_stats_report.py`, `pull_historical_data.py`, `newsletter_template.md`, `NEWSLETTER_PROMPTS.md`

**February 9, 2026 - Newsletter Drafting Prompt System**

New file `templates/NEWSLETTER_PROMPTS.md` -- reusable 3-part drafting prompts that pair with the newsletter template. Prompts carry week-specific context (storylines, dates, trades, rosters) while the template carries permanent rules (formatting, extraction workflow, injury glossary). Each week: fill in `[FILL IN]` placeholders and run 3 parts in a separate Claude chat (Sections 1-4, 5-8, 9-10).

Updated `templates/newsletter_template.md` -- added Companion Files table, reorganized final checklist into 4 categories (Structure, Accuracy, Style, Continuity), removed redundancy with prompts. Updated `WEEKLY_WORKFLOW.md` Step 7 and Step 10 to match.

**February 5, 2026 - Consistency/Volatility Score**

New module `consistency_score.py` measures scoring predictability using Coefficient of Variation on weekly FPPG. Team-level: CV, boom/bust counts, floor/ceiling, recent trend, rating labels. Player-level: per-player CV and IQR (25th-75th percentile) for all rostered players (ROSTERS.json ownership, game logs across all managers). Includes `player_lookup` dict for cross-referencing.

Integrated into Section 3 (per-matchup predictability context), Section 7 (league-wide consistency table + player highlights), and Section 8 (CV and IQR columns added to all four season performer tables).

Modified files: `consistency_score.py` (new), `report_builder.py`, `format_stats_report.py`, `PROJECTSTRUCTURE.md`, `README.md`

**February 5, 2026 - ASCII-Only Source Policy**

All `.py` and `.md` source files converted to pure ASCII. Unicode characters in Python string literals use `\u` escape sequences; comments/docstrings/markdown use ASCII equivalents (`->`, `--`, `!=`, `^2`). `check_file_health.py` rewritten to enforce this policy. Prevents mojibake corruption during Claude download/upload cycles. 37/37 files verified clean.

**February 5, 2026 - Schedule Strength Index**

New module `schedule_strength.py` counts NBA games per fantasy roster for upcoming week and rest-of-season. Filters by injury status for weekly view. Integrated into Section 3 (Betting Lines) via `report_builder.py` and `format_stats_report.py` -- adds league-wide schedule summary and per-matchup schedule edge context.

Data sources: `nba_schedule_2025-26.json`, `ROSTERS.json`, `PLAYERLIST.xlsx`, `SCHEDULE.json`, `INJURY_OVERRIDES.json`.

Modified files: `schedule_strength.py` (new), `report_builder.py`, `format_stats_report.py`, `PROJECTSTRUCTURE.md`, `README.md`

**February 5, 2026 - Luck Index & Waiver Wire ROI**

Two new analytics modules integrated into the newsletter pipeline:

1. **`luck_index.py`** (Section 5 - Fun Facts): Pythagorean expected record (PF^2/(PF^2+PA^2)) vs actual record. Quantifies luck by comparing actual wins to what scoring differential suggests. Includes luck ratings ("Very Lucky" to "Very Unlucky"), scoring margins, and per-game averages.

2. **`waiver_roi.py`** (Section 8 - Stats Corner): Season-long waiver wire return on investment. Tracks FP gained from pickups in starter slots vs FP lost from dropped players on their new teams. Highlights best add, biggest regret, and FP-per-add efficiency for each manager.

Modified files: `report_builder.py`, `format_stats_report.py`, `__init__.py`, `PROJECTSTRUCTURE.md`, `README.md`

**February 4, 2026 - IL+ Slot Reclassification & Injury Burden Fix**

Fixed how `build_season_injury_burden()` in `report_builder.py` and `generate_season_injury_burden_facts()` in `fun_facts_generator.py` handle IL and IL+ slots:

1. **IL+ = BN.** IL+ is now treated identically to a bench slot. Previously it was grouped with IL for the IL injury game count. Now IL+ injuries require `fantasy_points == 0.0` like any other non-IL slot.
2. **IL = always injured.** Any LINEUPS row in an IL slot with an `nba_opponent` value counts as an IL Injury Game regardless of `fantasy_points`. Previously, IL rows where a player scored (e.g., returned from injury but still in IL slot) were silently excluded. Now the slot assignment itself is the signal.

Impact on Week 15 numbers: Non-IL injury counts unchanged. Total injury burden % shifted slightly upward for Nick (17.8% -> 18.6%), Benton (24.3% -> 24.5%), Garrett (23.9% -> 24.2%). Hayden unchanged. `weekly_stats.py`, `format_stats_report.py`, and `LEAGUEHISTORY.xlsx` already had the correct logic/values and required no changes.

**Modified files:** `report_builder.py`, `fun_facts_generator.py`

**February 4, 2026 - TRADES.json, Injury Glossary, Newsletter Style Rules**

Three categories of changes: trade hallucination prevention, injury terminology standardization, and newsletter prose style rules.

**New config file: `config/TRADES.json`**

Created a structured trade history and draft pick ownership tracker to prevent the LLM from hallucinating trade details or misattributing draft pick ownership. Contains two sections:
- `trades`: Array of every trade this season with date, managers, `sends_a`/`sends_b` arrays (players and draft picks), and notes
- `draft_pick_ownership`: Maps `{round}_{originalOwner}` to current owner for every pick that has changed hands

Integrated into `format_stats_report.py` -- the formatter loads TRADES.json and injects trade history and draft pick ownership into the formatted markdown (Section 9 Around the NBA and Section 10 Rumor Mill). The LLM no longer needs to recall trade details from memory.

**Injury game counting glossary (format_stats_report.py + newsletter_template.md)**

Standardized six game-counting terms across the entire pipeline to prevent confusion between non-IL starter slot injuries, IL slot games, bench overflow, and avoidable blunders:

| Term | Definition | Source Field |
|------|-----------|-------------|
| Games lost to injury | Non-IL slot player had opponent but scored 0.0 FP (slot != IL) | `non_il_injury_games` |
| IL games | Any scheduled game in the IL slot (slot = IL + has `nba_opponent`; FP value irrelevant) | `il_injury_games` |
| Total injury games | Games lost to injury + IL games | `total_injury_games` |
| Games left on bench | BN/IL+ slot player scored > 0 FP (healthy production wasted) | `games_left_on_bench` |
| Blunders | Subset of bench games where a starter slot was available (empty or DNP starter) | `blunders` / `blunder_points` |
| Season injury burden % | Total injury games / all scheduled games | `total_injury_burden_pct` |

Changes in `format_stats_report.py`: All Season Injury Context blocks (Sections 1, 2, 7, 8) now output all three counts with explicit labels: `Total injury games: 205 | Games lost to injury (non-IL): 116 | IL games: 89`. The old ambiguous "games lost" label (which used the combined total) is eliminated.

Changes in `newsletter_template.md`: Rule 10 replaced with a 6-row glossary table. Default to "games lost to injury" (non-IL count) in prose; "total injury games" is available for the combined number but must be called by that exact name.

**Newsletter style rules (newsletter_template.md + newsletter_html_generator.py)**

Five new prose style rules added to the template and final checklist:
- **Rule 12 -- Sportsbook language for odds:** Use moneyline/spread in narrative prose ("+140 underdog," "69.5-point spread"), not win probability percentages. Win probability % belongs only in stat blocks.
- **Rule 11 -- Prose injury timelines:** Write "expected back this week" or "still a couple weeks away" -- never parenthetical shorthand like "(2/3 games)" or "(3 weeks remaining)".
- **Report card ordering:** Must be sorted by `overall_score` descending, not alphabetical or by record.
- **No player-by-player injury lists in matchup summaries:** State the count ("11 games lost to injury"), don't enumerate which players missed which games.
- **Matchup scoreboard rendering fix (newsletter_html_generator.py):** Fixed garbled UTF-8 regex in `parse_matchup_summaries()` -- the em-dash character class was double-encoded. Replaced with proper Unicode escapes `[\u2014\u2013\-]` so matchup scoreboards render as card-style headers instead of falling through to generic `<h4>` formatting.

**February 3, 2026 - Draft Pick Valuation Guide (NEW)**

Added `config/DRAFT_PICK_VALUES.json` -- maps each draft round (1-7) to expected projFPPG and role tier for objective trade grading. Built from 2024-2025 draft analysis with keeper league context. Referenced by `newsletter_template.md` Section 9 trade grading instructions and `format_stats_report.py` trade block output.

**February 3, 2026 - Newsletter Template Audit & Simulator O/U Fix**

Comprehensive section-by-section audit of `newsletter_template.md` using the Week 15 draft as a test case. Also fixed systematic O/U bias in betting simulator.

**Template changes (Sections 1-2):**
- Section 1 italic statline now shows total FP, FPPG, and games per position (e.g., "G: 509.75 (46.3/g, 11g)")
- Section 1 player mentions now require games played (e.g., "Brandon Miller (166.35 FP over 4 games)")
- Section 2 waiver statline expanded: adds count, total FP, games, FPPG, and FP per add
- Section 2 efficiency format changed from "Efficiency: 103.3%" to "+3.3% vs projection"
- Section 2 new rule: utilization rate is weekly, must be labeled when mixed with season-long stats

**Code changes (report_builder.py, format_stats_report.py):**
- `report_builder.py`: Added `waiver_games` and `waiver_fppg` to report card dict (data was computed in `weekly_stats.py` but not exported)
- `format_stats_report.py`: Updated waiver output line to include games, FPPG, and FP per add

**Simulator O/U fix (simulator_betting.py):**
- Added `OU_INJURY_DISCOUNT = 0.10` constant -- applies a 10% discount to avg scores and O/U only
- Problem: O/U was systematically too high because the simulator projected scores assuming all non-INJURY_OVERRIDE players stay healthy. In reality, ~14.6% of games are lost to random mid-week injuries (non-IL). After subtracting the ~3-4% already captured by GTD/O status checks, ~10% of injury impact was unaccounted for, making "under" a near-guaranteed bet every week.
- Fix: Avg scores and O/U are multiplied by 0.90. Spread, moneyline, and win probability are unaffected (they depend on relative strength, not absolute totals).
- The constant is tunable -- adjust up/down based on whether O/U hits start trending over or under.

**February 3, 2026 - Stats Report Formatter Audit (Sections 0-10)**

Comprehensive audit of `format_stats_report.py` raising all 11 sections from 7-8.5/10 to 9-10/10:

- **Section 0 (Matchup Recaps):** Upset detection -- loads previous week's betting predictions, flags when underdogs win
- **Section 1 (Matchup Summaries):** Moved Current Team Health block to Section 3 (more relevant for forward-looking analysis)
- **Section 2 (Report Cards):** Previous week grade comparison ("B, previously C+"), utilization rates
- **Section 3 (Betting Lines):** 2-key-player rotation with injury filtering (reads PLAYERLIST.xlsx projections), Current Team Health block added here
- **Section 4 (POTW):** Multi-season POTW history from `config/POTW_HISTORY.json` with auto-save; season leaderboard and career stats
- **Section 7 (Power Rankings):** Title odds movement from previous week ("74.9% -- 88.7%, +13.8%")
- **Section 8 (Stats Corner):** Fixed free agents table -- positions parsed correctly, added Games This Week/Next Week columns
- **Section 9 (Around the NBA):** Injury timelines from INJURY_OVERRIDES.json ("Missed 4 of ~7 weeks since week 12"); structured trade block with enriched player projections and trade grade instructions

**New data sources loaded by formatter:** Previous week's JSON (betting predictions, grades, title odds), `data/PLAYERLIST.xlsx` (projections), `config/POTW_HISTORY.json` (auto-saved each run), `config/INJURY_OVERRIDES.json` (injury timelines), `data/weeklycontextinput_weekN.json` (structured trades)

**New config file:** `config/POTW_HISTORY.json` -- tracks all POTW winners by season with auto-save

**Weekly context input format change:** Added structured `trades` array to `weeklycontextinput_weekN.json` for trade coverage (draft picks must go here since sync_transactions can't detect them)

**February 12, 2026 - Record Book Overhaul (47 Tables, 5 Categories)**

Major expansion from ~30 tables to 50 tables across 5 categories (was 4), plus complete rework of the draft pick valuation system to pick-level granularity.

Key changes: player/rookie records consolidated by (player, season) instead of (player, manager, season); added "Best FPPG in Single Week" tables; changed 45+ FP threshold to 40+ FP; added season-length 40+ FP and sub-20 FP tables; all draft records filtered to keeper-era only (2021-22+); DRAFT_PICK_VALUES.json rebuilt with 36 pick-level entries using 70/30 raw/regression blend; added Total FP versions of steal/bust tables; replaced IL Game-Days with Total Injury Games using LINEUPS.xlsx slot data; added trade acquisition FPPG table (25 GP min) and waiver pickup Total FP table.

New script: `build_draft_pick_values.py` -- builds pick-level expected values from DRAFT_PERFORMANCE.json.

**Modified files:** `build_draft_pick_values.py`, `backfill_player_records.py`, `report_builder.py`, `stats_corner_viz.py`
**Updated config:** `DRAFT_PICK_VALUES.json`, `RECORDS.json`

**February 10, 2026 - Record Book Expansion (Top-10 Leaderboards)**

Expanded the Record Book from an 8-row season-vs-all-time snapshot table into a full 4-category visualization with top-10 leaderboards, powered by historical game-level data across 8 seasons.

**Record Book Categories:**
1. **Team Records** (6 leaderboards): Highest/Lowest Weekly Score, Biggest Blowout, Closest Game, Longest Win/Loss Streak
2. **Player Records** (4 leaderboards): Highest/Lowest Single Game, Best Season FPPG (min 30 GP), Most FP in Single Week
3. **Rookie Records** (3 leaderboards): Best Rookie Single Game, Best Rookie Season FPPG (min 30 GP), Best Rookie Fantasy Week
4. **Manager Milestones**: Career wins, losses, win%, career points, titles -- ranked list

All FPPG records enforce a blanket 30 GP minimum to filter out small-sample flukes. Current-season entries get gold highlights in the viz, and a NEW! badge appears when the current season holds the #1 spot.

**Data pipeline:**
- `backfill_player_records.py` (one-time) computes all-time top-10s from `all_matchups.json` + `HISTORICAL_PLAYERLOG.json`
- `build_rookie_seasons.py` scrapes Basketball Reference for NBA debut seasons -> `ROOKIE_SEASONS.json`
- `records_tracker.py` maintains leaderboards weekly via 6 new functions (`update_top10_list`, `check_alltime_single_game_top10`, `update_season_player_records`, `update_alltime_weekly_top10s`, `update_alltime_season_fppg_top10`, `_normalize_season`)
- `report_builder.py` outputs expanded 4-category schema (replaces old `{"records": [...]}` format)
- `stats_corner_viz.py` renders trophy-case HTML card with top-5 leaderboards per record
- `format_stats_report.py` outputs full top-10 markdown tables for LLM newsletter drafting

**New files:** `scripts/backfill_player_records.py`, `scripts/build_rookie_seasons.py`, `config/ROOKIE_SEASONS.json`
**New data dependency:** `data/historical/HISTORICAL_PLAYERLOG.json` (game-level data, 2017-25)
**Modified files:** `records_tracker.py`, `report_builder.py`, `stats_corner_viz.py`, `format_stats_report.py`

**February 2, 2026 - Stats Report Formatter (NEW)**

Added `scripts/format_stats_report.py` -- converts JSON stats report to newsletter-ready Markdown.

**Problem solved:** Previously, Claude had to extract and cross-reference data from 15+ JSON sections before writing. This was error-prone (missing fields, hallucinated numbers) and consumed output tokens.

**Solution:** Python assembles all data by newsletter section:
- Section 1: Matchup Summaries (combines matchup_summaries, team_stats, injury_burden, scoring_trends)
- Section 2: Report Cards (combines report_cards, injury_burden)
- Section 3: Betting Lines (from looking_ahead, scoring_trends, team_health, PLAYERLIST projections)
- Section 4: Player of the Week (from player_of_week)
- Section 5: Fun Facts (from fun_facts, current_streaks, record_updates, all_time_records)
- Section 6: What If (from what_if)
- Section 7: Power Rankings (from power_rankings, injury_burden, team_health, scoring_trends)
- Section 8: Stats Corner (from best_worst, season_performers, waiver_roi)
- Section 9: Around the NBA (from rosters, team_health -- web search deferred)
- Section 10: Rumor Mill (from rumor_mill, injury_burden, all_time_records)

**Workflow change:**
```
BEFORE (2 LLM passes):
  JSON -> Claude extracts -> Claude writes

AFTER (1 LLM pass):
  JSON -> Python formats -> Markdown -> Claude writes
```

**New files:**
- `scripts/format_stats_report.py` -- The formatter script
- `output/stats_report_week{N}.md` -- Markdown output

**Usage:**
```bash
python scripts/format_stats_report.py --week 15
```

### February 2026

**February 16, 2026 - Newsletter Enhancements & Verification System**

**Stats Corner Navigation & UI Improvements:**
- Added "Record Book" shortcut to main navigation bar
- Added Stats Corner sub-navigation with links to: Positional Breakdown, Draft Value, Waiver ROI, Keeper Watch, Record Book, Season Leaders
- Added team FPPG and total games under each donut chart in Positional Scoring Breakdown
- Added Keeper Watch manager filter - click any manager card to filter players, click again to reset

**Draft Pick Values Smoothing (Change 5):**
- Changed blend ratio from 70/30 to 50/50 (raw mean / regression)
- Added Â±1.5 FPPG deviation cap from regression line
- Result: Pick 17 vs Pick 20 gap reduced from 6.2 to 3.8 FPPG
- Updated `build_draft_pick_values.py` with new `MAX_DEVIATION_FROM_REGRESSION` constant

**Newsletter Verification Checklist (NEW):**
Added post-draft verification step to `NEWSLETTER_PROMPTS.md` and `NEWSLETTER_PROMPTS_WEEK16.md` with specific error patterns to check:
1. Head-to-head record interpretation (e.g., "dominated 25-39" when trailing)
2. Win streak records - personal vs league disambiguation
3. Trade grade direction verification
4. Superlative claims without data verification
5. Efficiency rating claims (untrackable)

**Trade Grade Formatting Fix:**
- Updated `newsletter_template.md` with explicit formatting rule: trade grades must be inline with analysis paragraph, not on separate line
- Format: `**Grade: X | Y** -- Analysis continues...`

**Encoding Fixes:**
- Fixed corrupted trophy emoji in Record Book title (stats_corner_viz.py line 904)
- Fixed corrupted Â± symbol in build_draft_pick_values.py
- Fixed em-dash normalization in newsletter_html_generator.py (was causing Report Cards to not render)
- All three files now pass ASCII-only validation

**Dark Mode Helmet Fix:**
- Created `helmet_transparent.png` with transparent background (original was JPEG with white background)
- Helmets now blend seamlessly into dark mode header

**February 13, 2026 - Repro Mode for Iterative Newsletter Development**

Added `--repro` flag to `generate_stats_report.py` for reproducible re-runs of the same week without polluting continuity state:

**New flag: `--repro`**
- Uses pre-week `RECENT_CONTENT` snapshot instead of live file (prevents freshness contamination)
- Freezes entire `looking_ahead` section from prior published report (betting lines stay consistent)
- Skips Yahoo injury fetch (uses cached data)
- Does not save freshness updates (leaves `RECENT_CONTENT.json` unchanged)

**New directory: `config/snapshots/`**
- `RECENT_CONTENT_pre_week{N}.json` - Freshness state before week N processing
- `RECENT_CONTENT_post_week{N}.json` - Freshness state after week N processing
- Auto-created on first normal run, used during `--repro` runs

**New cache file: `output/looking_ahead_week{N}.json`**
- Stores betting lines, previews, and next-week context
- Created during normal runs, loaded during `--repro` runs
- Ensures betting simulations don't change when iterating on newsletter content

**Usage example:**
```bash
# First run: generates report, saves snapshots
python generate_stats_report.py --week 16

# Re-run: uses snapshots, freezes betting lines
python generate_stats_report.py --week 16 --repro
```

**Impact:** Enables multiple newsletter drafts for the same week without changing betting lines or contaminating freshness tracking. Critical for iterative content refinement.

### January 2026

**January 27, 2026 - Newsletter Template v2 & HTML Generator Fix**

Added 8 underutilized stats report fields to template:
- `scoring_trends` for momentum narratives
- `positional_matchups` for betting analysis
- `implications` for stakes framing
- `expected_record` for projections
- `trade_partners` for historical context

Fixed HTML generator Unicode issues in `parse_report_cards()`.

**January 26, 2026 - ROSTERS.json as Source of Truth & Rumor Mill Enhancements**

**ROSTERS.json as Single Source of Truth:**
All roster-dependent sections now use `config/ROSTERS.json` instead of LINEUPS for current roster state.

**Hot Streaks Feature (NEW):**
Added "Hot Streaks" subsection to Rumor Mill (mirrors Slump Watch for overperformers).

**Slump Watch Improvements:**
- `better_fa_available` now only suggests FAs with projection > player's projection
- `better_fa_available` now filters out players in `INJURY_OVERRIDES.json`

**January 24, 2026 - Game Counting Definitions & Season Totals**

Formalized definitions for all game metrics:
- Scheduled games: Rows with `nba_opponent` + `fantasy_points` value + slot != IL
- Games played: Rows where `started=TRUE` and `is_injured=FALSE`
- Games lost to injury: Rows with `nba_opponent` + `fantasy_points=0.0` + slot != IL
- Games left on bench: Rows with `fantasy_points > 0` + slot in {BN, IL+}
- Blunders: Subset of bench games where a starter slot was available (empty or DNP). See February 9, 2026 changelog.
- IL+ is treated as a bench slot everywhere (identical to BN); only IL is excluded

**January 2026 (Earlier) - Injury Metrics & Partial Returns**

Added two-metric injury system:
- `season_injury_burden`: Historical injury impact
- `current_team_health`: Real-time roster health with partial return support

### January 2025

**HTML Newsletter Generator (NEW):**
- Replaced PDF generation with modern HTML output
- Professional styling with Inter + Playfair Display fonts
- Self-contained single-file output with embedded base64 images
- Responsive design works on mobile, tablet, and desktop

**Stats Report Enhancements:**
- Added `season_performers` section with 4 tables
- Fixed trajectory arrows Unicode encoding issues
- Added `nba_team` column to free agents table

## Configuration Files

All configuration files are stored in `config/`:

### `SCHEDULE.json`
Defines the fantasy schedule with matchups. Contains `total_weeks` (23), `regular_season_weeks` (21), and `playoff_start_week` (22) metadata fields. Weeks 1-21 are regular season; Weeks 22-23 are playoffs (semifinals and finals). The `regular_season_weeks` field controls simulator routing in `report_builder.py` — weeks before it use regular title odds, weeks at or after it use playoff championship odds. Week 23 matchups should be updated manually after semifinal results are in (winners play championship, losers play consolation).

### `DRAFT_PICK_VALUES.json`
Pick-level expected values for all 36 draft positions (P1-P36) with both FPPG and Total FP. Built by `build_draft_pick_values.py` from keeper-era data only (2021-22 onward, 5 seasons). P1-P28 use a 50/50 blend of raw historical mean and regression-fitted value, capped at Â±1.5 FPPG deviation from regression to smooth small-sample variance. P29-P36 (expansion R8-R9) use cliff decay from R7 average. Used by the Draft Value Tracker, draft steal/bust record tables, and LLM trade grading.

### `DRAFT_PICKS_CURRENT.json`
Current season's 52 draft picks with player names, managers, rounds, and pick numbers. Rounds 1-7 are actual draft selections; rounds 8-13 are keeper slots. Created via `pull_current_draft.py` at season start, lives in config during the season. At season end, `pull_historical_data.py` merges this data into `data/historical/all_drafts.json`. Read by `report_builder.py` for the Draft Value Tracker table.

### `INJURY_OVERRIDES.json`
Manual injury tracking for players with optional partial return support.

### `ROSTERS.json`
Current roster state for each manager, updated weekly.

### `POTW_HISTORY.json`
Multi-season Player of the Week award history. Auto-updated by `format_stats_report.py` each week. Organized by NBA season with player name, manager, total FP, games, and FPPG. Used for narrative context ("Luka's 2nd POTW this season") and season leaderboards.

### `RECORDS.json`
Tracks league records, milestones, weekly scores, blunder counts (`cumulative_blunders`, `single_week_blunders_high`), and all-time top-10 leaderboards (`*_top10` keys) across 5 categories: Team Records (16 tables), Player Records (16 tables), Rookie Records (5 tables), Draft & Trades (10 tables), and Manager Records (7 tables). Top-10s are recomputed weekly by `backfill_player_records.py` (Step 5.75 in the workflow) and supplemented at runtime by `report_builder.py`'s patching functions.

### `ROOKIE_SEASONS.json`
Maps player names to their NBA debut season (e.g., `"Cooper Flagg": "2025-26"`). Built by `build_rookie_seasons.py` via Basketball Reference lookups. Used by `records_tracker.py` and `report_builder.py` to identify rookie-eligible performances for the Record Book's Rookie Records category. Run `--update` annually each October for new rookies.

### `TRADES.json`
Structured trade history and draft pick ownership tracker. Contains a `trades` array documenting every trade this season (date, managers, `sends_a`/`sends_b` with players and draft picks) and a `draft_pick_ownership` map tracking every pick that has changed hands (e.g., `"1_Garrett": "Hayden"` means Hayden owns Garrett's 1st rounder). Loaded by `format_stats_report.py` and injected into Sections 9 and 10 so the LLM never has to infer trade details from memory. Updated manually after each trade.

### `LAST_WEEK_RECAP.md`
Reporter's notebook that carries narrative continuity between newsletter drafting sessions.

## Newsletter Template & Drafting Prompts

The newsletter drafting system uses two files in `templates/` that work as a pair:

### `newsletter_template.md` (Reference Manual)
The permanent writing guide that contains:
- Voice and tone guidance (ESPN/The Athletic style)
- Exact format templates for each of the 10 sections
- Data source mappings with specific field paths
- Extraction workflow (Extract -> Cite -> Write -> Clean)
- Injury game counting glossary (Rule 10) with 6 distinct terms and prose usage rules (includes blunders)
- Prose injury timeline rule (Rule 11) -- no parenthetical shorthand like "(2/3 games)"
- Sportsbook language rule (Rule 12) -- moneyline/spread in narrative prose, not win probability %
- Superlative verification rule (Rule 13) -- all "most/worst/best in history" claims must be verified against data
- Magic number definition (Rule 14) -- prevents "one win clinches" when magic number > 1
- Elimination status verification (Rule 15) -- verify math before any elimination claims
- Trade grade direction verification (Rule 16) -- mandatory re-read of sent_picks after writing trade grades
- Trade grading rules referencing `DRAFT_PICK_VALUES.json`
- Companion Files table explaining all uploaded files
- Final checklist organized by Structure, Accuracy, Style, and Continuity
- **Playoff Edition Addendum** (Weeks 22-23): Section-by-section modifications for playoff newsletters. Section 7 becomes "Playoff Championship Odds" with bracket tables. Rumor Mill reframed as offseason moves. Language reminders (no standings races, no magic numbers). Week 23 special notes for finals coverage.

### `NEWSLETTER_PROMPTS.md` (Weekly Prompts)
Reusable 3-part prompts with `[FILL IN]` placeholders that change each week:
- **Part 1** (Sections 1-4): Includes manager table, key storylines, and task scope
- **Part 2** (Sections 5-8): Specifies table counts (2 for Power Rankings, 14 for Stats Corner)
- **Part 3** (Sections 9-10): Includes trade block (if applicable), rosters for web search, and closing

The prompts carry week-specific context (storylines, dates, trade details) while deferring all formatting and accuracy rules to the template. This keeps the prompts lean and eliminates redundancy.

## Contributing

This is a personal project for a private fantasy league, but the architecture could be adapted for other leagues. Key areas for customization:

1. Update `MANAGERS` and `MANAGER_TO_TEAM` in `modules/data_loader.py`
2. Modify `config/SCHEDULE.json` for your league structure
3. Adjust simulation parameters in `modules/simulator_title_odds.py`
4. Customize `templates/newsletter_template.md` for your league's voice

## License

MIT License - Feel free to adapt for your own fantasy league!

## Acknowledgments

- Yahoo Fantasy API for data access
- NBA API for schedule and player data
- Claude (Anthropic) for newsletter drafting assistance
- Google Fonts (Inter, Playfair Display) for typography

---

## From PROJECTSTRUCTURE.md (detailed technical changes)

## Recent Changes

### March 24, 2026 - Playoff System (Bracket Simulator, Section 7 Overhaul, Template Addendum)

Added full playoff support to the newsletter pipeline. The regular season ended at Week 21; Weeks 22-23 are the playoff bracket (semifinals + finals).

**New module: `modules/simulator_playoff_odds.py`**
- Monte Carlo simulator (default 10,000 iterations) for the 2-week playoff bracket
- Simulates Week 22 semifinals using SCHEDULE.json matchups, then dynamically builds Week 23 finals (semi winners play championship, semi losers play consolation)
- Reuses `simulate_week_historical()` from `simulator_title_odds.py` for consistent score projections
- Outputs `PlayoffOddsResult` dataclass: championship probability per team, semifinal win probabilities, finish distribution (1st-4th), most likely championship matchup, expected scores
- Interface-compatible with `TitleOddsResult` so `build_power_rankings()` consumes it without changes

**Report routing (`report_builder.py`):**
- New `use_playoff_odds` flag: `True` when `week >= regular_season_weeks` (i.e., Week 21+)
- Week 21 (final regular season week) uses the playoff simulator instead of regular title odds, since standings are locked and the bracket preview is the interesting forward-looking data
- Weeks 22-23 (actual playoff weeks) also use the playoff simulator
- Weeks 1-20 are completely unaffected
- Report dict gets `is_playoff_week` flag and `playoff_odds` block when playoff sim is used

**Section 7 overhaul (`format_stats_report.py`):**
- When `is_playoff_week=True`, Section 7 becomes "PLAYOFF CHAMPIONSHIP ODDS" instead of "POWER RANKINGS"
- Renders: semifinal matchup table with win probabilities, championship probability table (Champ%/Runner-Up%/3rd%/4th%), most likely championship matchup, keeper quality scores, season injury burden, current team health, and scoring trends
- Regular section 7 is completely unchanged for weeks 1-20

**Config changes:**
- `SCHEDULE.json`: Added `regular_season_weeks: 21` and `playoff_start_week: 22` metadata fields; `total_weeks` updated to 23; Weeks 22-23 added with playoff matchups
- `stats_corner_viz.py`: Added `'2025-26': [22, 23]` to `PLAYOFF_WEEKS` dict for historical playoff results grid

**Template & prompts:**
- `newsletter_template.md`: Added "Playoff Edition Addendum" section at the bottom covering section-by-section modifications for Weeks 22-23 (Section 7 becomes Championship Odds, Rumor Mill reframed as offseason moves, language reminders, Week 23 special notes)
- `NEWSLETTER_PROMPTS_WEEK22.md`: Complete playoff-edition 3-part prompts with bracket context, semifinal preview framing, and playoff-specific verification checklist

**Other new files:**
- `data/waivers_week22.txt` (empty placeholder for pipeline compatibility)
- `config/weeklycontextinput_week22.json` (playoff context template)
- `modules/__init__.py` updated with `simulator_playoff_odds` imports

**Modified files:** `report_builder.py`, `format_stats_report.py`, `generate_stats_report.py`, `stats_corner_viz.py`, `__init__.py`, `SCHEDULE.json`, `newsletter_template.md`
**New files:** `simulator_playoff_odds.py`, `NEWSLETTER_PROMPTS_WEEK22.md`, `waivers_week22.txt`, `weeklycontextinput_week22.json`

### February 12, 2026 - Record Book Overhaul (10 Changes, 3 Batches)

Major expansion of the Record Book from ~30 tables to 50 tables across 5 categories, plus a complete rework of the draft pick valuation system to use pick-level granularity.

**Batch A -- Record Table Changes (Changes 1-4, 7):**
- **Change 1:** Player/rookie records consolidated by (player, season) instead of (player, manager, season). If a player was traded mid-season, all managers are listed.
- **Change 2:** Added "Best FPPG in Single Week" tables to Players and Rookies pages (3 game minimum).
- **Change 3:** Changed "Most Games 45+ FP (Week)" to "Most Games 40+ FP (Week)" on Teams page.
- **Change 4:** Added "Most Games Over 40 FP (Season)" table to Players page.
- **Change 7:** Fixed duplicate season year in Best Draft Class italic text.

**Batch B -- Draft System Rework (Changes 5-6):**
- **Change 5:** All draft records now use keeper-era only (2021-22 onward, 5 seasons). Pre-keeper drafts excluded from DRAFT_PICK_VALUES and all Draft & Trades tables. Asterisks note this on affected tables.
- **Change 6:** DRAFT_PICK_VALUES.json completely reworked:
  - Now 36 pick-level entries (P1-P36) instead of 7 round-level entries
  - P1-P28: 70% raw historical mean + 30% regression-fitted value (preserves pick personality while smoothing outliers)
  - P29-P36 (expansion R8-R9): Cliff decay from R7 average (0.5 FPPG/pick, 40 TFP/pick)
  - Both FPPG and Total FP expected values per pick
  - Configurable knobs: RAW_WEIGHT, REG_WEIGHT, EXPANSION_FPPG_DECAY_PER_PICK, EXPANSION_TFP_DECAY_PER_PICK
  - Added Total FP versions of Biggest Draft Steal and Biggest Draft Bust tables (4 steal/bust tables total)

**Batch C -- Manager/Trade/Waiver Additions (Changes 8-10):**
- **Change 8:** Replaced "Most IL Game-Days" with "Most Total Injury Games (Season)" on Managers page. Uses LINEUPS.xlsx directly for slot + nba_opponent data. Shows breakdown (non-IL injuries + IL games + burden %). 2025-26 onward only (requires LINEUPS slot data).
- **Change 9:** Added "Best Trade Acquisition (FPPG)" table (25 GP minimum) alongside existing Total FP version.
- **Change 10:** Added "Best Waiver Pickup (Total FP)" table alongside existing FPPG version. 2025-26 onward.

**Record Book final table count (50 tables):**
1. Team Records (16): Highest/Lowest Weekly Score, Highest/Lowest Team FPPG, Biggest Blowout, Closest Game, Win/Loss Streak, Best/Worst Daily Team FPPG, Highest Daily Team Score, Best Duo (Day/Week/Season), Most 40+ FP Games (Week), Most Sub-20 FP Games (Week)
2. Player Records (16): Highest/Lowest Single Game, Best Season FPPG/FP, Most FP in Single Week, Best FPPG Single Week, Biggest Outperformance, Most Consistent, Most Games Over 40 FP (Season), Most Games Under 20 FP (Season), Mr. Monday Night, Mr. 4th Quarter, Best Career FP/FPPG/By Manager, Longest Tenure
3. Rookie Records (5): Best Single Game, Best Season FPPG/FP, Most FP in Single Week, Best FPPG Single Week
4. Draft & Trades (10): Best Draft Class FP/FPPG, Draft Steal/Bust FPPG/TFP, Trade Acquisition FP/FPPG, Waiver Pickup FPPG/FP
5. Manager Records (3): Best/Worst Manager Season (FP/week), Most Total Injury Games (Season)

**Manager Page redesign (stats_corner_viz.py):**
- Franchise Player badge with seasons/GP/FPPG detail
- H2H records grid (each manager's record vs every other)
- Tabbed manager detail cards with career stats

**Data pipeline for draft values:**
```
extract_draft_fppg.py -> DRAFT_PERFORMANCE.json (raw data)
    v
build_draft_pick_values.py -> DRAFT_PICK_VALUES.json (P1-P36 expected values)
    v
backfill_player_records.py -> RECORDS.json (steal/bust tables use pick-level lookup)
    v
report_builder.py -> record_book dict (display layer)
    v
stats_corner_viz.py -> HTML (5 tabbed pages)
```

**Modified files:** `build_draft_pick_values.py`, `backfill_player_records.py`, `report_builder.py`, `stats_corner_viz.py`
**Updated config:** `DRAFT_PICK_VALUES.json` (36 pick-level entries), `RECORDS.json` (new top-10 keys)

**Files safe to delete after this update:**
- `backfill_historical_playerlog.py` (root) -- one-time script, already run
- `scripts/fix_2324_draft_order.py` -- one-time fix, already applied
- `scripts/newsletterpdfgenerator.py` -- legacy PDF generator, replaced by HTML

### February 13, 2026 - Newsletter Quality Audit & Viz Enhancements

Comprehensive audit of Week 16 newsletter identified rendering bugs and hallucination-prone patterns. All fixes target upstream files (template, generator, viz) to prevent recurrence.

**HTML Generator (`newsletter_html_generator.py`):**
- Nav links use `scrollIntoView()` JS instead of `<a href="#id">` anchors (fixes iMessage/sandboxed viewer warnings)
- Pagination keyword matching fixed for season performer tables (was `'Season Best'`, now also matches `'Best Performers'`)
- Subsection header length limit raised from 60 to 120 chars (fixes long trade headlines rendering as stat-lines)
- Parser regex: accepts `def.`/`--`/`-` in matchup headers; `->`, `--`, `:` in report card grades
- Stats Corner: 6 tables filtered from prose (now viz-only), viz injection split into top/bottom positions

**Stats Corner Viz (`stats_corner_viz.py`):**
- Record Book default tab: Manager (was Team)
- New: Historical League Standings grid (4 rows x 9 season columns, rank-colored records, trophy icons, finish tallies)
- New: Historical Luck Index grid (4 rows x 9 columns, color-coded luck values, career totals, legend)
- Both grids in Record Book Manager tab above existing manager records
- `render_stats_corner_visualizations()` accepts `position` param; `render_record_book()` accepts `historical_luck`

**Newsletter Template (`newsletter_template.md`):**
- Rule 13: Superlative/historical claim verification (must check extracted data)
- Rule 14: Magic number definition (N = combination of wins + rival losses)
- Rule 15: Elimination status verification (verify math before claims)
- Rule 16: Trade grade direction verification (re-read sent_picks after writing)
- Rumor Mill: Mandatory bullet format for all subsections
- Final checklist: 5 new verification items

**Format Stats Report (`format_stats_report.py`):**
- Removed 6 Stats Corner table generation blocks (now interactive viz only)

**Modified files:** `newsletter_html_generator.py`, `stats_corner_viz.py`, `newsletter_template.md`, `format_stats_report.py`

### February 10, 2026 - Record Book Expansion (Top-10 Leaderboards)

Expanded the Record Book from an 8-row season-vs-all-time snapshot table into a full 4-category visualization with top-10 leaderboards, powered by historical game-level data across 8 seasons.

**Record Book Categories:**
1. **Team Records** (6 leaderboards): Highest/Lowest Weekly Score, Biggest Blowout, Closest Game, Longest Win/Loss Streak
2. **Player Records** (4 leaderboards): Highest/Lowest Single Game, Best Season FPPG (min 30 GP), Most FP in Single Week
3. **Rookie Records** (3 leaderboards): Best Rookie Single Game, Best Rookie Season FPPG (min 30 GP), Best Rookie Fantasy Week
4. **Manager Milestones**: Career wins, losses, win%, career points, titles -- ranked list

All FPPG records enforce a blanket 30 GP minimum. Current-season entries get gold highlights; NEW! badge when current season holds #1.

**Data pipeline:**
- `backfill_player_records.py` computes all-time top-10s from `all_matchups.json` + `HISTORICAL_PLAYERLOG.json`
- `build_rookie_seasons.py` scrapes Basketball Reference for debut seasons -> `ROOKIE_SEASONS.json`
- `records_tracker.py` maintains leaderboards weekly (6 new functions)
- `report_builder.py` outputs 4-category schema with ranked entries
- `stats_corner_viz.py` renders trophy-case HTML card (5th viz card)
- `format_stats_report.py` outputs full top-10 markdown tables for LLM

**New files:** `scripts/backfill_player_records.py`, `scripts/build_rookie_seasons.py`, `config/ROOKIE_SEASONS.json`
**New data dependency:** `data/historical/HISTORICAL_PLAYERLOG.json`
**Modified files:** `records_tracker.py`, `report_builder.py`, `stats_corner_viz.py`, `format_stats_report.py`

### February 10, 2026 - Stats Corner Visualizations & Keeper Tier Refactor

**New module: `modules/stats_corner_viz.py`**

Interactive HTML visualizations for Section 8 (Stats Corner), rendered directly in the newsletter. Four visualization cards with tabbed manager views:

1. **Positional Scoring Breakdown** -- Donut charts showing G/F/C split per manager with GP, Total FP, and FPPG stats. Horizontal card layout on mobile, 2x2 grid on desktop.
2. **Draft Value Tracker** -- Diverging bar chart of actual vs expected FPPG for R1-7 picks. Color-coded labels (Steal/Good Value/Fair/Bust/Too Early). Player status badges: Rostered (green), Traded (blue), Claimed (purple), Dropped (red). Faded bars for non-rostered players. OFS badge for out-for-season players.
3. **Waiver Wire ROI** -- Summary stats (FPPG, hit rate, bust rate, total adds, waiver share) + 3 notable pickups table (deduplicated) + best add and biggest regret callouts per manager.
4. **Keeper Watch** -- Tiered chip layout with 6 tiers: Lock (green), Strong Hold (blue), Sell High (amber), On the Bubble (gray), Drop (red), Stash (purple). Chips show name, age, position, FPPG, and GP stats. OFS players show projected FPPG instead of season stats.

All visualizations are mobile-responsive with single-column layouts at <600px.

**Keeper tier refactor (`report_builder.py`)**

Replaced hard-coded FPPG + age threshold table with score-based keepability system consistent with `rumor_mill_analyzer.compute_trade_value()`:

```
keepability_score = blended_fppg x availability_factor x age_factor
```

- **Blended FPPG**: 70% actual + 30% projected (>=10 GP), weighted blend (5-9 GP), or 100% projected (<5 GP)
- **Availability**: sqrt(games_played / expected_games) -- softened penalty
- **Age factor**: <=23 = 1.15x (young), 24-29 = 1.0x (prime), 30-32 = 0.95x (veteran), 33+ = 0.85x (aging)

Tier thresholds: Lock >= 40, Strong Hold >= 30, On the Bubble >= 24. Sell High for aging players (33+ with score >= 28, or 30+ with score 20-30). Stash for OFS players with proj FPPG >= 35.

Key re-tierings vs old system: Jokic (Strong Hold -> Lock, 63 FPPG overwhelms age-30 haircut), Sengun (Strong Hold -> Lock, youth premium at 23), Edwards (Lock -> Strong Hold, availability penalty).

**Draft value tracker enhancements (`report_builder.py`)**

Added granular player status detection by cross-referencing DRAFT_PICKS_CURRENT.json (who drafted), ROSTERS.json (current roster), and waivers_weekN.txt files (waiver adds):
- **Rostered**: Still on drafting team
- **Traded**: Changed teams, no waiver record (actual trade)
- **Claimed**: Changed teams via waiver pickup (drop-and-claim)
- **Dropped**: Currently a free agent

Added `out_for_season` flag from INJURY_OVERRIDES.json.

**Newsletter HTML generator integration (`newsletter_html_generator.py`)**

- New `--stats-report` CLI arg accepts path to `stats_report_weekN.json`
- Stats Corner visualizations auto-injected into Section 8 when data is present
- CSS and JS from `stats_corner_viz.py` embedded in HTML output
- Graceful degradation: sections with no data are silently skipped

**Modified files:** `report_builder.py`, `newsletter_html_generator.py`, `__init__.py`
**New files:** `modules/stats_corner_viz.py`

### February 9, 2026 - Stats Corner Expansion + Draft Data Architecture

**Four new Stats Corner tables** (10 -> 14 total):

1. **Bench Report** -- Season-long bench production (GP, FP, FP/Wk) and blunder count from RECORDS.json
2. **Record Book Snapshot** -- Side-by-side season vs all-time records (8 categories)
3. **Keeper Watch** -- Top 6 players per team with tier labels (Lock/Strong Hold/On the Bubble/Sell High/Drop) based on FPPG + age
4. **Draft Value Tracker** -- Grades R1-7 picks against expected FPPG from DRAFT_PICK_VALUES.json. Labels: Steal (+4), Good Value (+1), Fair (-3), Bust (<-3), Too Early (<10 GP). Keepers (R8-13) excluded -- covered by Keeper Watch.

**Positional classification refactor:**
- Moved `classify_position_group()` from `weekly_stats.py` to `data_loader.py` as canonical source
- Changed from "C > F > G priority" to majority-voting logic (count PG/SG vs SF/PF vs C, ties go bigger)
- 11 players reclassified (e.g., Amen Thompson F->G, Scottie Barnes C->F)
- One-time fix script: `fix_positional_records.py` recomputes RECORDS.json positional stats

**Draft data architecture:**
- New: `config/DRAFT_PICKS_CURRENT.json` -- current season's 52 draft picks (R1-7 drafted, R8-13 keepers)
- `data/historical/all_drafts.json` -- now contains only historical seasons (2017-2025). Current season removed.
- Fixed `pull_historical_data.py` `extract_draft()` -- was looking for `player_key` (always empty); now uses `int(player_id)` which is what Yahoo actually returns. All 416 historical draft picks now have player names.
- Fixed 2023-24 draft order -- keepers were in rounds 1-6 (inverted); moved to rounds 8-13 to match all other years.

**New scripts:**
- `pull_current_draft.py` -- Pulls current season draft from Yahoo API using int player_ids
- `backfill_draft_names.py` -- Backfills player names across all historical seasons in all_drafts.json
- `fix_positional_records.py` -- One-time RECORDS.json positional stats recompute
- `fix_2324_draft_order.py` -- One-time fix for 2023-24 keeper round ordering

**End-of-season workflow:** Add `"2025-26": "466.l.42309"` to LEAGUE_KEYS in `pull_historical_data.py`, run it, and current season draft merges into all_drafts.json alongside all other historical data.

**Modified files:** `data_loader.py`, `weekly_stats.py`, `__init__.py`, `rumor_mill_analyzer.py`, `report_builder.py`, `format_stats_report.py`, `newsletter_template.md`, `NEWSLETTER_PROMPTS.md`, `pull_historical_data.py`

### February 9, 2026 - Blunder Detection & Tracking

**New feature: Blunders** -- a subset of "games left on bench" where a starter slot was available (empty or occupied by a DNP player). Distinguishes avoidable manager negligence from unavoidable bench overflow.

**Detection logic (what_if_analyzer.py):**
- Per day, identifies starter slots where the assigned player didn't play (DNP)
- Checks if any bench player who scored could have filled that slot (position-eligible)
- Greedy matching: highest-FP bench players assigned first to prevent double-counting
- Tracks: count, FP wasted (bench player's full FP, not swap differential), player/slot details

**Grading impact (report_builder.py):**
- Management score penalty: -5 per blunder (stacks with -2 bench penalty = -7 total per blunder vs -2 for overflow)
- New output fields: `blunders`, `blunder_points`, `blunder_details[]` in both report cards and what_if sections

**Display (format_stats_report.py):**
- Report cards: "Blunders: X (Y FP wasted)" in stat line (omitted when 0)
- What If: "BLUNDER: [player] ([FP]) left on bench -> [slot] slot ([DNP starter] didn't play) on [date]"

**Records (records_tracker.py + RECORDS.json):**
- `cumulative_blunders`: season totals per manager
- `single_week_blunders_high`: worst single-week count per manager (all four peaked in Week 4)

**Data storage (LEAGUEHISTORY.xlsx + update_leaguehistory.py):**
- New column P: `total_blunders_current_season` (backfilled through Week 16)
- Standalone blunder detection function in update_leaguehistory.py (replicates core logic since script runs outside package)

**Template & prompt updates:**
- `newsletter_template.md`: Blunders added to game counting glossary, report card extraction spec, and What If section format
- `NEWSLETTER_PROMPTS.md`: Part 2 What If instructions updated to lead with blunders
- `VERIFICATION_TEMPLATE.md`: Blunder-specific hallucination patterns added

**Season totals (Weeks 1-16):** Hayden 14, Nick 10, Garrett 10, Benton 7. Week 4 was the outlier (31 league-wide blunders -- early-season lineup neglect).

**Modified files:** `what_if_analyzer.py`, `report_builder.py`, `format_stats_report.py`, `records_tracker.py`, `update_leaguehistory.py`, `LEAGUEHISTORY.xlsx`, `RECORDS.json`, `newsletter_template.md`, `NEWSLETTER_PROMPTS.md`, `VERIFICATION_TEMPLATE.md`, `PROJECTSTRUCTURE.md`, `README.md`

### February 9, 2026 - Newsletter Drafting Prompt System & Template Update

**New file: `templates/NEWSLETTER_PROMPTS.md`**
Reusable 3-part drafting prompts that work in tandem with the newsletter template. Each week, fill in `[FILL IN]` placeholders (week number, dates, key storylines, rosters) and run the 3 parts in a separate Claude chat:
- Part 1: Sections 1-4 (Matchup Summaries, Report Cards, POTW, Betting Lines)
- Part 2: Sections 5-8 (Fun Facts, Power Rankings, Stats Corner, What If)
- Part 3: Sections 9-10 (Around the NBA with web search, Rumor Mill)

**Updated: `templates/newsletter_template.md`**
- Added Companion Files table at top explaining all 6 uploaded files
- Updated workflow section to support "clean output only" mode (extract internally, output clean prose)
- Reorganized final checklist into 4 categories: Structure, Accuracy, Style, Continuity
- Added continuity checks for LAST_WEEK_RECAP.md and RECENT_CONTENT.json
- Removed redundancy with prompts -- template is now the permanent "reference manual" while prompts carry week-specific context

**Division of labor:**
- **Prompts** = what to write about (changes weekly: storylines, trades, rosters, dates)
- **Template** = how to write it (permanent: formatting rules, extraction schemas, injury glossary, trade grading)
- Rules that Claude commonly violates are reinforced in both (report card ordering, table counts, draft pick checks)

**Updated: `WEEKLY_WORKFLOW.md`** -- Step 7 rewritten to reference 3-part prompt system; Step 10 expanded to include RECENT_CONTENT.json update

### February 5, 2026 - Consistency/Volatility Score

**New module: `modules/consistency_score.py`**

Measures scoring predictability using Coefficient of Variation (CV) on weekly FPPG. Lower CV = more consistent.

**Team-level metrics (per manager):**
- Weekly FPPG series (total FP / games started per week -- normalizes across weeks)
- CV, mean, std dev on the FPPG series
- Floor/ceiling weeks (best and worst FPPG)
- Boom/bust counts (weeks > 1 SD above/below mean)
- Recent trend (last 5 weeks CV vs full season -- "Getting steadier", "Getting wilder", "Stable")
- Rating label: "Rock Solid" (<8%), "Steady" (8-14%), "Variable" (14-20%), "Boom-or-Bust" (>20%)

**Player-level metrics (per roster via ROSTERS.json):**
- Per-player game-by-game CV (min 10 started games)
- IQR (25th-75th percentile) for scoring range
- Most consistent and most volatile starter per team
- Full player_lookup dict for cross-referencing in other sections

**Data flow:**
- `LINEUPS.xlsx` + `ROSTERS.json` + `SCHEDULE.json` -> `consistency_score.py` -> `stats_report["consistency_scores"]`
- Player ownership uses ROSTERS.json (current roster truth), game logs pulled across all managers (handles mid-season trades)

**Integration points:**
- Section 3 (Betting Lines): Per-matchup consistency comparison with predictability note
- Section 7 (Power Rankings): League-wide consistency table + player highlights
- Section 8 (Best/Worst): CV and IQR (25-75) columns added to all four season performer tables

**Modified files:** `consistency_score.py` (new), `report_builder.py` (import + dict key), `format_stats_report.py` (Section 3 matchup context, Section 7 table, Section 8 enriched columns)

### February 5, 2026 - ASCII-Only Source Policy

**All .py and .md files must be pure ASCII (every character ord <= 127).**

Root cause: downloading files from Claude and uploading to Claude Projects corrupts UTF-8 characters (arrows, em dashes, accented chars) into mojibake. Each download/upload cycle adds another encoding layer.

**Solution:**
- Python string literals use `\u` escape sequences for runtime Unicode (e.g., `"\u2192"` renders as -> at runtime but source bytes are pure ASCII)
- Comments, docstrings, and markdown use ASCII equivalents (`->`, `--`, `!=`, `^2`, etc.)
- `check_file_health.py` rewritten to flag ANY non-ASCII character (not just severe corruption)

**Workflow:** Run `python scripts/check_file_health.py` after downloading files from Claude, before importing to project. All 37 files verified clean.

### February 5, 2026 - Schedule Strength Index

**New module: `modules/schedule_strength.py`**

Counts NBA games per fantasy roster for the upcoming week and rest-of-season. Factors in injury status (INJURY_OVERRIDES.json) for weekly view. Integrated into Section 3 (Betting Lines) of the newsletter.

**What it computes:**
- Per-manager: total games, healthy games, injured games, per-player breakdown
- Weekly view: filters out injured players for realistic game counts
- ROS view: all rostered players regardless of injury status

**Data flow:**
- `nba_schedule_2025-26.json` + `ROSTERS.json` + `PLAYERLIST.xlsx` + `SCHEDULE.json` + `INJURY_OVERRIDES.json` -> `schedule_strength.py` -> `stats_report["schedule_strength"]`
- `format_stats_report.py` displays: league-wide summary at top of Section 3 + per-matchup schedule edge

**Modified files:** `report_builder.py` (import + dict key), `format_stats_report.py` (Section 3 schedule context blocks)

### February 5, 2026 - Luck Index & Waiver Wire ROI Integration

**Two new analytics modules integrated into the newsletter pipeline:**

- **`modules/luck_index.py`**: Pythagorean expected record (PF^2/(PF^2+PA^2)) compared to actual record. Quantifies how much each manager has over/underperformed based on scoring differential. Feeds Section 5 (Fun Facts) as a table with actual vs expected record, luck rating, and scoring margins.

- **`modules/waiver_roi.py`**: Season-long waiver wire return on investment. Tracks FP gained from waiver adds in starter slots vs FP lost from dropped players on their new teams. Identifies best add, biggest regret, and FP per add efficiency. Feeds Section 8 (Stats Corner) as a league-wide summary table.

**Modified files:** `report_builder.py` (2 imports + 2 dict keys), `format_stats_report.py` (Section 8 waiver ROI table + Section 5 luck index table), `__init__.py` (exports), `PROJECTSTRUCTURE.md`, `README.md`

**Data flow:**
- `RECORDS.json` + `SCHEDULE.json` -> `luck_index.py` -> `stats_report["luck_index"]` -> Section 5 table
- `waivers_week{N}.txt` + `LINEUPS.xlsx` + `PLAYERLOG.xlsx` -> `waiver_roi.py` -> `stats_report["waiver_roi"]` -> Section 8 table

### February 4, 2026 - IL+ Slot Reclassification & Injury Burden Fix

**IL+ now treated identically to BN.** Previously, `build_season_injury_burden()` in `report_builder.py` and `generate_season_injury_burden_facts()` in `fun_facts_generator.py` grouped IL+ with IL for the IL injury count. IL+ is now treated as a regular bench slot -- injuries in IL+ require `fantasy_points == 0.0` just like any starter or BN slot.

**IL slot = always injured.** Any LINEUPS row in an IL slot with an `nba_opponent` value now counts as an IL Injury Game regardless of `fantasy_points`. Previously, IL rows where a player scored points (e.g., player returned but manager hadn't moved them out of IL yet) were not counted as injury games. Now the slot assignment itself is the signal.

**Updated game counting definitions:**
- **Games lost to injury (non-IL):** `nba_opponent` present + `fantasy_points == 0.0` + slot != IL (unchanged)
- **IL Injury Games:** ANY row with `nba_opponent` present + slot = IL (changed -- no longer requires `fp == 0.0`)
- **Total injury games:** Games lost to injury + IL Injury Games
- **Games left on bench:** `fantasy_points > 0` + slot in {BN, IL+} (unchanged -- IL+ was already here)
- **Blunders:** Subset of bench games where a starter slot was available (empty or DNP starter). Detected via greedy position-eligible matching. See February 9, 2026 changelog.
- **Scheduled games:** `nba_opponent` present + slot != IL (unchanged -- IL was already excluded)

**Impact on numbers (Week 15):** Non-IL injury counts unchanged for all managers. Total injury burden % shifted slightly upward for Nick (17.8% -> 18.6%), Benton (24.3% -> 24.5%), and Garrett (23.9% -> 24.2%). Hayden unchanged (no IL-slotted players scored points). IL game counts increased by 7 (Nick), 1 (Benton), and 2 (Garrett).

**No changes needed to:** `weekly_stats.py` (already correct), `format_stats_report.py` (labels already accurate), `LEAGUEHISTORY.xlsx` (values already aligned with non-IL definitions)

**Modified files:** `report_builder.py`, `fun_facts_generator.py`

### February 19, 2026 - Manager Season Record Tables (Total FP & FP/game)

**New Record Book tables in Manager tab:** Added 4 new manager season leaderboards providing three lenses on seasonal performance:

1. **Best/Worst Manager Season (Total FP)** - Raw total fantasy points scored in a season
2. **Best/Worst Manager Season (FP/game)** - Average fantasy points per game started (total FP / games played)

The existing FP/week tables remain, now using explicit `_fpweek_top10` keys.

**New RECORDS.json keys:**
- `best_manager_season_top10` - Top 10 by total FP (was previously used for FP/week display)
- `worst_manager_season_top10` - Bottom 10 by total FP
- `best_manager_season_fpweek_top10` - Top 10 by FP/week
- `worst_manager_season_fpweek_top10` - Bottom 10 by FP/week
- `best_manager_season_fppg_top10` - Top 10 by FP/game (NEW)
- `worst_manager_season_fppg_top10` - Bottom 10 by FP/game (NEW)

**FP/game calculation:** Requires game-level data from `HISTORICAL_PLAYERLOG.json`. Current season data pulled from `RECORDS.json["weekly_scores"]` and `RECORDS.json["manager_season_totals"]` for wins/losses.

**Data note:** FP/game leaderboards only include seasons with game-level data in HISTORICAL_PLAYERLOG. Historical seasons without game data will not appear in FP/game tables but will appear in Total FP and FP/week tables.

**Modified files:** `backfill_player_records.py`, `report_builder.py`

### February 16, 2026 - Newsletter Enhancements & Verification System

**Stats Corner Navigation & UI Improvements:**
- Added "Record Book" shortcut to main navigation bar (`newsletter_html_generator.py`)
- Added Stats Corner sub-navigation with links to: Positional Breakdown, Draft Value, Waiver ROI, Keeper Watch, Record Book, Season Leaders
- Added team FPPG and total games under each donut chart in Positional Scoring Breakdown (`stats_corner_viz.py`)
- Added Keeper Watch manager filter - click any manager card to filter players, click again to reset (`stats_corner_viz.py`)

**Draft Pick Values Smoothing:**
- Changed blend ratio from 70/30 to 50/50 (raw mean / regression) in `build_draft_pick_values.py`
- Added Â±1.5 FPPG deviation cap from regression line (`MAX_DEVIATION_FROM_REGRESSION` constant)
- Result: Pick 17 vs Pick 20 gap reduced from 6.2 to 3.8 FPPG
- Updated `DRAFT_PICK_VALUES.json` with new methodology

**Newsletter Verification Checklist (NEW):**
Added post-draft verification step to `NEWSLETTER_PROMPTS.md` and `NEWSLETTER_PROMPTS_WEEK16.md`:
1. Head-to-head record interpretation (e.g., "dominated 25-39" when trailing)
2. Win streak records - personal vs league disambiguation
3. Trade grade direction verification
4. Superlative claims without data verification
5. Efficiency rating claims (untrackable)

**Trade Grade Formatting Fix:**
- Updated `newsletter_template.md` with explicit formatting rule: trade grades must be inline with analysis paragraph
- Format: `**Grade: X | Y** -- Analysis continues...` (not on separate line)

**Encoding Fixes:**
- Fixed corrupted trophy emoji in Record Book title (`stats_corner_viz.py`)
- Fixed corrupted Â± symbol in `build_draft_pick_values.py`
- Fixed em-dash normalization in `newsletter_html_generator.py` (was causing Report Cards to not render)
- All files now pass ASCII-only validation via `check_file_health.py`

**Dark Mode Helmet Fix:**
- Created `helmet_transparent.png` with transparent background
- Original `helmet.png` was JPEG with white background that showed as rectangle in dark mode

**Modified files:** `newsletter_html_generator.py`, `stats_corner_viz.py`, `build_draft_pick_values.py`, `newsletter_template.md`, `NEWSLETTER_PROMPTS.md`, `NEWSLETTER_PROMPTS_WEEK16.md`, `DRAFT_PICK_VALUES.json`
**New assets:** `assets/helmet_transparent.png`

### February 13, 2026 - Repro Mode for Iterative Newsletter Development

Added `--repro` flag to `generate_stats_report.py` for reproducible re-runs of the same week without polluting continuity state.

**New flag: `--repro`**
- Uses pre-week `RECENT_CONTENT` snapshot instead of live file (prevents freshness contamination)
- Freezes entire `looking_ahead` section from prior published report (betting lines stay consistent)
- Skips Yahoo injury fetch (uses cached data)
- Does not save freshness updates (leaves `RECENT_CONTENT.json` unchanged)

**New directory: `config/snapshots/`**
- `RECENT_CONTENT_pre_week{N}.json` - Freshness state before week N processing
- `RECENT_CONTENT_post_week{N}.json` - Freshness state after week N processing
- Auto-created on first normal run, used during `--repro` runs

**New cache file: `output/looking_ahead_week{N}.json`**
- Stores betting lines, previews, and next-week context
- Created during normal runs, loaded during `--repro` runs
- Ensures betting simulations don't change when iterating on newsletter content

**Workflow:**
```bash
# First run: generates report, saves snapshots
python scripts\generate_stats_report.py --week 16

# Re-run: uses snapshots, freezes betting lines
python scripts\generate_stats_report.py --week 16 --repro
```

**Impact:** Enables multiple newsletter drafts for the same week without changing betting lines or contaminating freshness tracking. Critical for iterative content refinement.

**Modified files:** `generate_stats_report.py`
**New directory:** `config/snapshots/`
**New cache files:** `output/looking_ahead_week{N}.json`

### February 4, 2026 - TRADES.json, Injury Glossary, Newsletter Style Rules

**New config file: `config/TRADES.json`**
- Structured trade history (`trades` array with `sends_a`/`sends_b`) and draft pick ownership map (`draft_pick_ownership`)
- Loaded by `format_stats_report.py` and injected into Sections 9 (Around the NBA) and 10 (Rumor Mill)
- Prevents LLM from hallucinating trade details or misattributing draft picks

**Injury game counting glossary (format_stats_report.py + newsletter_template.md):**
- All Season Injury Context blocks now output three distinct counts with explicit labels: `Total injury games: 205 | Games lost to injury (non-IL): 116 | IL games: 89`
- Template Rule 10 replaced with 5-row glossary defining: games lost to injury, IL games, total injury games, games left on bench, season injury burden %
- Default to "games lost to injury" (non-IL count) in prose; "total injury games" for combined picture but must use that exact label

**Newsletter style rules (newsletter_template.md):**
- Rule 11: Prose injury timelines -- no parenthetical shorthand like "(2/3 games)" or "(3 weeks remaining)"
- Rule 12: Sportsbook language -- use moneyline/spread in narrative prose, not win probability percentages
- Report cards must be sorted by `overall_score` descending
- No player-by-player injury lists in matchup summaries -- just state the count
- Final checklist expanded with 4 new items

**HTML generator fix (newsletter_html_generator.py):**
- Fixed garbled UTF-8 regex in `parse_matchup_summaries()` for em-dash detection
- Replaced double-encoded character class with proper Unicode escapes `[\u2014\u2013\-]`
- Matchup scoreboards now render as card-style headers (same styling as Betting Lines)

**Modified files:** `format_stats_report.py`, `newsletter_template.md`, `newsletter_html_generator.py`
**New files:** `config/TRADES.json`

### February 3, 2026 - Newsletter Template Audit & Simulator O/U Fix

**Template audit (newsletter_template.md):**
- Section 1: Expanded positional statline to show total FP, FPPG, and games per position; player mentions require game counts
- Section 2: Waiver statline now includes games, FPPG, and FP per add; efficiency displayed as "+X% vs projection"; utilization rate clarified as weekly stat

**Code changes:**
- `report_builder.py`: Added `waiver_games` and `waiver_fppg` to report card output dict
- `format_stats_report.py`: Updated waiver output line to include games, FPPG, and FP per add

**Simulator O/U fix (simulator_betting.py):**
- Added `OU_INJURY_DISCOUNT = 0.10` -- applies 10% discount to avg scores and O/U to account for random mid-week injuries not captured by INJURY_OVERRIDES or GTD/O statuses
- Spread, moneyline, and win probability are unaffected

### February 3, 2026 - Draft Pick Valuation Guide

Added `config/DRAFT_PICK_VALUES.json` -- a reference file mapping each draft round (1-7) to expected player value (projFPPG) and role tier. Used by the LLM when grading trades in Section 9 (Around the NBA) of the newsletter.

**Methodology:** Built from analysis of 2024 and 2025 draft results combined with qualitative assessment of keeper league dynamics. In a 4-team keeper league with 6 keepers per team, the top ~24 players are off the board before the draft begins, compressing the talent pool.

**Pick value tiers:**
- Round 1 (~41 FPPG): Elite draft asset, likely keeper candidate
- Round 2 (~39 FPPG): Strong draft asset, possible keeper
- Rounds 3-4 (~34-36 FPPG): Solid contributors, unlikely to become keepers
- Round 5 (~33.5 FPPG): Fringe contributor, may or may not stick on roster
- Rounds 6-7 (~28-30.5 FPPG): Roster churn, likely dropped by midseason

**Integration points:**
- `format_stats_report.py` Section 9 trade grading instructions reference this file
- `newsletter_template.md` Section 9 trade grading rules reference this file
- Key principle: A single high-round pick with keeper upside > multiple low-round picks

### February 3, 2026 - Stats Report Formatter Audit (Sections 0-10)

Comprehensive audit of `format_stats_report.py` raising all 11 sections from 7-8.5/10 to 9-10/10:

- **Section 0 (Matchup Recaps):** Upset detection -- loads previous week's betting predictions, flags when underdogs win
- **Section 1 (Matchup Summaries):** Moved Current Team Health block to Section 3 (more relevant for forward-looking preview)
- **Section 2 (Report Cards):** Previous week grade comparison ("B, previously C+"), utilization rates
- **Section 3 (Betting Lines):** 2-key-player rotation with injury filtering (reads PLAYERLIST.xlsx projections), Current Team Health block added
- **Section 4 (POTW):** Multi-season POTW history from `config/POTW_HISTORY.json` with auto-save; season leaderboard and career stats
- **Section 7 (Power Rankings):** Title odds movement from previous week ("74.9% -> 88.7%, +13.8%")
- **Section 8 (Stats Corner):** Fixed free agents table -- positions parsed correctly, added Games This Week/Next Week columns
- **Section 9 (Around the NBA):** Injury timelines from INJURY_OVERRIDES.json; structured trade block with enriched player projections and trade grade instructions

**New data sources loaded by formatter:** Previous week's JSON, `data/PLAYERLIST.xlsx`, `config/POTW_HISTORY.json` (auto-saved each run), `config/INJURY_OVERRIDES.json`, `data/weeklycontextinput_weekN.json` (structured trades)

**New config file:** `config/POTW_HISTORY.json` -- tracks all POTW winners by season with auto-save

**Weekly context input format change:** Added structured `trades` array to `weeklycontextinput_weekN.json` for trade coverage (draft picks must go here since sync_transactions can't detect them)

### February 2, 2026 - Stats Report Formatter

#### New Script: format_stats_report.py
Converts JSON stats report to newsletter-ready markdown, eliminating the LLM extraction step.

**Problem solved:** Previously, Claude had to extract and cross-reference data from 15+ JSON sections before writing. This was error-prone (missing fields, hallucinated numbers) and consumed output tokens.

**Solution:** Python assembles all data by newsletter section:
- Section 0: Matchup Recaps (from matchup_summaries, previous week betting predictions)
- Section 1: Matchup Summaries (combines matchup_summaries, team_stats, injury_burden, scoring_trends)
- Section 2: Report Cards (combines report_cards, injury_burden, previous week grades)
- Section 3: Betting Lines (from looking_ahead, scoring_trends, team_health, PLAYERLIST projections)
- Section 4: Player of the Week (from player_of_week, POTW_HISTORY.json)
- Section 5: Fun Facts (from fun_facts, current_streaks, record_updates, all_time_records)
- Section 6: What If (from what_if)
- Section 7: Power Rankings (from power_rankings, injury_burden, team_health, scoring_trends, previous title odds)
- Section 8: Stats Corner (from best_worst, season_performers, waiver_roi)
- Section 9: Around the NBA (from rosters, team_health, INJURY_OVERRIDES, weekly context trades -- web search deferred)
- Section 10: Rumor Mill (from rumor_mill, injury_burden, all_time_records)

**Workflow change:**
```
BEFORE (2 LLM passes):
  JSON -> Claude extracts -> Claude writes

AFTER (1 LLM pass):
  JSON -> Python formats -> Markdown -> Claude writes
```

**New files:**
- `scripts/format_stats_report.py` -- The formatter script
- `output/stats_report_week{N}.md` -- Markdown output

**Usage:**
```cmd
python scripts\format_stats_report.py --week 15
```
