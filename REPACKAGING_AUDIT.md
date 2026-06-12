# REPACKAGING AUDIT

> **Goal:** Make this project clone-and-run for any stranger with a 4-team Yahoo Fantasy Basketball league, on Windows or Mac, by filling in one config file.
>
> **Audit date:** 2026-06-09
> **Audited by:** Claude (automated full-project scan)

---

## 1. PROJECT STRUCTURE SUMMARY

### File counts

| Type | Count |
|------|-------|
| `.py` | 46 (25 modules + 21 scripts) |
| `.json` | 53 (10 config + 8 historical + 8 output + 15 snapshots + misc) |
| `.md` | 24 (3 root + 6 asset drafts + 6 templates + 9 output reports) |
| `.txt` | 25 (23 waiver files + requirements.txt + 1 summary) |
| `.html` | 7 (6 newsletter outputs + 1 player card preview) |
| `.xlsx` | 5 (PLAYERLOG, LINEUPS, LEAGUEHISTORY, PLAYERLIST, TEAMLIST) |

### Directory tree

```
newsletter/
├── modules/                  # Core analysis engine (25 .py files)
│   ├── __init__.py
│   ├── data_loader.py
│   ├── weekly_stats.py
│   ├── projections.py
│   ├── simulator_*.py (3)
│   ├── *_score.py / *_index.py
│   └── ... (see below)
├── scripts/                  # CLI entry points and data pipelines (21 .py files)
│   ├── generate_stats_report.py
│   ├── format_stats_report.py
│   ├── newsletter_html_generator.py
│   ├── update_fantasy_logs.py
│   └── ... (see below)
├── config/                   # League/season configuration (10 JSON + snapshots/)
├── data/                     # Raw data (Excel, waivers, NBA schedule)
│   └── historical/           # Multi-season archives (8 JSON files)
├── output/                   # Generated reports and newsletters
├── assets/                   # Weekly newsletter drafts (markdown)
├── templates/                # LLM prompt templates
├── oauth2.json               # Yahoo API credentials (gitignored)
├── requirements.txt
├── README.md
├── PROJECTSTRUCTURE.md
└── WEEKLY_WORKFLOW.md
```

### Module descriptions (modules/)

| File | Purpose | Engine / League-specific |
|------|---------|--------------------------|
| `__init__.py` | Central import hub; re-exports all submodules | Engine |
| `data_loader.py` | Loads all Excel/JSON data; **defines MANAGERS, MANAGER_TO_TEAM** | **LEAGUE-SPECIFIC (primary source of truth)** |
| `weekly_stats.py` | Computes team and player statistics for a given fantasy week | Engine |
| `projections.py` | Player projections, variance modeling, availability calculations | Engine |
| `schedule_strength.py` | Schedule strength via daily lineup simulation | Engine |
| `lineup_optimizer.py` | Solves optimal daily lineups respecting position constraints | Engine |
| `consistency_score.py` | Consistency/Volatility scores using Coefficient of Variation | Engine (has season string) |
| `luck_index.py` | Pythagorean Record (Luck Index) for each manager | Engine (has season string) |
| `simulator_playoff_odds.py` | Monte Carlo simulation for playoff bracket | Engine (has season structure constants) |
| `simulator_title_odds.py` | Monte Carlo simulation for rest-of-season title odds | Engine (has hardcoded 4-team assumption) |
| `simulator_betting.py` | Monte Carlo for weekly betting lines (spread, O/U, moneyline) | Engine (has season string) |
| `keepability_v2.py` | Keeper scoring with v2.2 formula (5 components + age multiplier) | Engine (has season defaults) |
| `records_tracker.py` | Tracks season records, streaks, all-time leaderboards | Engine (has 8+ season string occurrences) |
| `report_builder.py` | Orchestrator -- assembles all stats into final JSON report | Engine (has season strings) |
| `player_card_builder.py` | Assembles player card data (career history, stats, archetypes) | Engine (has season constants) |
| `player_card_modal.py` | Generates HTML/CSS/JS for interactive player card modals | **LEAGUE-SPECIFIC (manager colors hardcoded in Python AND JS)** |
| `stats_corner_viz.py` | Renders Stats Corner HTML visualizations (donuts, charts) | **LEAGUE-SPECIFIC (duplicated manager names, colors, historical data)** |
| `content_freshness.py` | Tracks recently used content to prevent repetition | Engine |
| `fun_facts_generator.py` | Auto-generates interesting facts from weekly/season data | Engine |
| `waiver_roi.py` | Computes season-long Waiver Wire ROI | Engine |
| `what_if_analyzer.py` | "What if" scenarios -- points left on bench, optimal swaps | Engine |
| `season_performers.py` | Season-to-date best/worst performers via Yahoo API | **LEAGUE-SPECIFIC (duplicates Yahoo credentials)** |
| `fetch_injury_statuses.py` | Fetches injury statuses from Yahoo Fantasy API | **LEAGUE-SPECIFIC (Yahoo credentials + team mapping)** |
| `rumor_mill_analyzer.py` | Strategic analysis for Rumor Mill (trade ideas, FA recs) | Engine |
| `simulator_playoff_odds - Copy.py` | **DEAD FILE -- exact backup, should be deleted** | N/A |

### Script descriptions (scripts/)

| File | Purpose | Engine / League-specific |
|------|---------|--------------------------|
| `generate_stats_report.py` | **Main entry point** -- orchestrates weekly stats report | Engine |
| `format_stats_report.py` | Converts stats JSON into newsletter-ready markdown | **LEAGUE-SPECIFIC (manager names in ~8 loops)** |
| `newsletter_html_generator.py` | Converts markdown draft to styled HTML newsletter | **LEAGUE-SPECIFIC (league name, brand colors, team names)** |
| `update_fantasy_logs.py` | **Daily pipeline** -- pulls Yahoo stats into Excel files | **LEAGUE-SPECIFIC** |
| `sync_transactions.py` | Syncs Yahoo transactions to ROSTERS.json + waivers file | **LEAGUE-SPECIFIC** |
| `generate_rosters.py` | Generates ROSTERS.json from LINEUPS data | Engine |
| `update_leaguehistory.py` | Computes weekly stats and updates LEAGUEHISTORY.xlsx | Engine (has season default) |
| `pull_current_draft.py` | Pulls draft results for current season from Yahoo API | **LEAGUE-SPECIFIC** |
| `pull_historical_data.py` | Pulls historical data from Yahoo API (all past seasons) | **LEAGUE-SPECIFIC (all historical league keys)** |
| `backfill_draft_names.py` | Backfills player names in all_drafts.json via Yahoo API | **LEAGUE-SPECIFIC (all 9 historical league keys)** |
| `backfill_trades.py` | Re-fetches trade details for all_trades.json | **LEAGUE-SPECIFIC** |
| `backfill_waivers.py` | Regenerates waivers files from Yahoo transaction history | **LEAGUE-SPECIFIC** |
| `backfill_player_records.py` | Computes all-time player/team records for RECORDS.json | Engine (has season constants) |
| `debug_backfill_player_records.py` | Debug copy with extra logging -- **has stale hardcoded week** | **Should be deleted** |
| `build_draft_pick_values.py` | Generates draft pick valuation model via regression | **LEAGUE-SPECIFIC (4 teams, draft rounds, roster size)** |
| `build_rookie_seasons.py` | Scrapes Basketball Reference for rookie year data | Engine |
| `fetch_nba_schedule.py` | Fetches NBA schedule from official API | Engine |
| `extract_draft_fppg.py` | Extracts season FPPG for every drafted player | Engine |
| `enrich_historical_playerlog.py` | Enriches historical playerlog with NBA team/opponent data | Engine |
| `check_file_health.py` | Detects encoding corruption in project files | Engine |
| `generate_player_card_preview.py` | Generates standalone HTML player card preview | **LEAGUE-SPECIFIC (manager colors, league branding)** |

---

## 2. HARDCODED VALUES INVENTORY

### 2A. League Identity

#### Manager Names: `"Nick"`, `"Hayden"`, `"Benton"`, `"Garrett"`

| File | Line(s) | Context | Destination |
|------|---------|---------|-------------|
| `modules/data_loader.py` | 37 | `MANAGERS = ["Nick", "Hayden", "Benton", "Garrett"]` | league_config.json |
| `modules/data_loader.py` | 300-308 | `normalize_manager_name()` hardcoded name map | league_config.json |
| `modules/stats_corner_viz.py` | 78 | `MANAGERS_LIST = ["Nick", "Hayden", "Benton", "Garrett"]` | league_config.json (DUPLICATE) |
| `modules/stats_corner_viz.py` | 813 | `pre_2017_firsts = {"Nick": 1, "Hayden": 1}` | league_config.json |
| `modules/stats_corner_viz.py` | 900 | `pre_2017_titles = {"Nick": 1, "Benton": 1}` | league_config.json |
| `modules/stats_corner_viz.py` | 943 | `managers = ["Nick", "Hayden", "Benton", "Garrett"]` | league_config.json (DUPLICATE) |
| `modules/player_card_modal.py` | 28-33 | `MANAGER_COLORS` dict keys | league_config.json |
| `modules/player_card_modal.py` | ~171, ~380, ~636 | Manager names in embedded JavaScript (3 separate JS dicts) | league_config.json (inject from Python) |
| `scripts/format_stats_report.py` | 934 | `managers = ["Nick", "Hayden", "Benton", "Garrett"]` | league_config.json |
| `scripts/format_stats_report.py` | 1094 | `managers = ["Nick", "Hayden", "Benton", "Garrett"]` | league_config.json |
| `scripts/format_stats_report.py` | 2209-2211 | `nick_pr = ...` / `"Nick's magic number"` / `"Nick wins + Benton losses"` | league_config.json (logic hardcoded to specific managers) |
| `scripts/format_stats_report.py` | 2281, 2320, 2522, 2595, 2733, 2753 | `for mgr in ["Nick", "Hayden", "Benton", "Garrett"]:` (6 loops) | league_config.json |
| `scripts/newsletter_html_generator.py` | 49-54 | `MANAGER_TO_TEAM` dict (lowercase keys) | league_config.json |
| `scripts/generate_player_card_preview.py` | 43-48 | `MANAGER_COLORS` dict | league_config.json (DUPLICATE) |
| `scripts/generate_player_card_preview.py` | 196, 372 | `"CHS Fantasy Basketball"` / `"CHS Fantasy Player Cards"` | league_config.json |
| `scripts/pull_current_draft.py` | 37-40 | `MANAGER_ALIASES` dict | league_config.json |
| `scripts/backfill_draft_names.py` | 47-51 | `MANAGER_ALIASES` dict | league_config.json |
| `scripts/pull_historical_data.py` | 39-43 | `MANAGER_ALIASES` dict | league_config.json |

#### Team Names: `"Luka my Balls"`, `"Big Nik Energy"`, `"Smaxey"`, `"Saboner"`

| File | Line(s) | Context | Destination |
|------|---------|---------|-------------|
| `modules/data_loader.py` | 40-45 | `MANAGER_TO_TEAM` dict | league_config.json |
| `modules/stats_corner_viz.py` | 43-48 | `MANAGER_TEAMS` dict | league_config.json (DUPLICATE) |
| `modules/fetch_injury_statuses.py` | 29-34 | `FANTASY_TEAM_TO_MANAGER` dict | league_config.json (DUPLICATE) |
| `scripts/update_fantasy_logs.py` | 18-21 | `FANTASY_TEAM_TO_MANAGER` dict | league_config.json (DUPLICATE) |
| `scripts/sync_transactions.py` | 33-36 | `FANTASY_TEAM_TO_MANAGER` dict | league_config.json (DUPLICATE) |
| `scripts/backfill_waivers.py` | 45-48 | `FANTASY_TEAM_TO_MANAGER` dict | league_config.json (DUPLICATE) |
| `scripts/newsletter_html_generator.py` | 49-54 | `MANAGER_TO_TEAM` dict (lowercase) | league_config.json (DUPLICATE) |

#### Yahoo League Key: `"466.l.42309"`

| File | Line(s) | Context | Destination |
|------|---------|---------|-------------|
| `modules/fetch_injury_statuses.py` | 26 | `LEAGUE_KEY = "466.l.42309"` | league_config.json |
| `modules/season_performers.py` | 49 | `LEAGUE_KEY = "466.l.42309"` | league_config.json (DUPLICATE) |
| `scripts/update_fantasy_logs.py` | 13 | `LEAGUE_KEY = "466.l.42309"` | league_config.json (DUPLICATE) |
| `scripts/sync_transactions.py` | 30 | `LEAGUE_KEY = "466.l.42309"` | league_config.json (DUPLICATE) |
| `scripts/backfill_waivers.py` | 43 | `LEAGUE_KEY = "466.l.42309"` | league_config.json (DUPLICATE) |
| `scripts/pull_current_draft.py` | 34 | `LEAGUE_KEY = "466.l.42309"` | league_config.json (DUPLICATE) |

#### Historical League Keys (all 9 seasons)

| File | Line(s) | Context | Destination |
|------|---------|---------|-------------|
| `scripts/backfill_draft_names.py` | 36-45 | `LEAGUE_KEYS` dict: `"2017-18": "380.l.23647"` through `"2025-26": "466.l.42309"` | league_config.json |
| `scripts/backfill_trades.py` | 41-49 | `LEAGUE_KEYS` dict (8 seasons, missing 2025-26) | league_config.json (DUPLICATE) |
| `scripts/pull_historical_data.py` | 27-36 | `LEAGUE_KEYS` dict (8 seasons) | league_config.json (DUPLICATE) |

#### Manager Colors

| File | Line(s) | Context | Destination |
|------|---------|---------|-------------|
| `modules/player_card_modal.py` | 28-33 | `MANAGER_COLORS = {"Nick": "#1F4E79", "Hayden": "#C9A227", "Benton": "#5B8C5A", "Garrett": "#B85C38"}` | league_config.json |
| `modules/player_card_modal.py` | ~171 | Same colors in embedded JS `pcRenderCard()` | league_config.json (inject from Python) |
| `modules/player_card_modal.py` | ~380 | Same colors in embedded JS `pcRenderTradeHistory()` | league_config.json (inject from Python) |
| `modules/player_card_modal.py` | ~636 | Same colors in embedded JS `pcRenderTimeline()` | league_config.json (inject from Python) |
| `modules/stats_corner_viz.py` | 37-42 | `MANAGER_COLORS` dict (same hex values) | league_config.json (DUPLICATE) |
| `modules/stats_corner_viz.py` | 79 | `MGR_COLORS_HIST` -- **DIFFERENT color assignments** (potential bug or intentional variant) | league_config.json |
| `modules/stats_corner_viz.py` | 944 | Another `mgr_colors` dict | league_config.json (DUPLICATE) |
| `scripts/generate_player_card_preview.py` | 43-48 | `MANAGER_COLORS` dict | league_config.json (DUPLICATE) |
| `scripts/newsletter_html_generator.py` | 42-43 | `HELMET_BLUE = "#1F4E79"`, `ACCENT_GOLD = "#C9A227"` | league_config.json |

> **BUG FLAG:** `stats_corner_viz.py` line 79 defines `MGR_COLORS_HIST` with **different color assignments** than the standard `MANAGER_COLORS` at line 37. Verify whether this is intentional (different visualization context) or a copy-paste bug.

#### League Name / Branding

| File | Line(s) | Context | Destination |
|------|---------|---------|-------------|
| `scripts/newsletter_html_generator.py` | 920 | `title = "CHS Alumni Weekly Newsletter"` | league_config.json |
| `scripts/newsletter_html_generator.py` | 1994 | `"CHS Alumni Fantasy Basketball League"` in footer | league_config.json |
| `scripts/generate_player_card_preview.py` | 196 | `"Player Cards - CHS Fantasy Basketball"` in HTML title | league_config.json |
| `scripts/generate_player_card_preview.py` | 372 | `"CHS Fantasy Player Cards"` in heading | league_config.json |
| `scripts/generate_player_card_preview.py` | 374 | `"Season 8"` in subheading | season_config |

#### League Structure Constants

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `scripts/build_draft_pick_values.py` | 78 | `TEAMS = 4` | league_config.json |
| `scripts/build_draft_pick_values.py` | 81 | `HISTORICAL_DRAFT_ROUNDS = 7` | league_config.json |
| `scripts/build_draft_pick_values.py` | 85 | `TOTAL_DRAFT_ROUNDS = 9` | league_config.json |
| `scripts/build_draft_pick_values.py` | 478-479 | `keepers_per_team=6`, `total_keepers=24` | league_config.json |
| `scripts/build_draft_pick_values.py` | 486 | `roster_size=17` (`"10 starters + 5 BN + 2 IL"`) | league_config.json |
| `scripts/build_draft_pick_values.py` | 65 | `KEEPER_ERA_START = "2021-22"` | league_config.json |
| `scripts/backfill_player_records.py` | 1148 | `KEEPER_ERA_START = "2021-22"` | league_config.json (DUPLICATE) |
| `scripts/debug_backfill_player_records.py` | 1052 | `KEEPER_ERA_START = "2021-22"` | league_config.json (DUPLICATE) |
| `modules/simulator_title_odds.py` | 817 | `range(4)` -- hardcoded 4 teams in finish distribution | league_config.json (NUM_TEAMS) |
| `modules/simulator_title_odds.py` | 834 | `{1: 0, 2: 0, 3: 0, 4: 0}` -- hardcoded 4 finish positions | league_config.json (NUM_TEAMS) |

#### Pre-History Data (before data collection began)

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `modules/stats_corner_viz.py` | 813 | `pre_2017_firsts = {"Nick": 1, "Hayden": 1}` | league_config.json |
| `modules/stats_corner_viz.py` | 900 | `pre_2017_titles = {"Nick": 1, "Benton": 1}` | league_config.json |

---

### 2B. Season Parameters

#### Season Strings: `"2025-26"` / `"2025-2026"`

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `modules/data_loader.py` | 31 | `"data/nba_schedule_2025-26.json"` (filename) | season_config |
| `modules/data_loader.py` | 99 | `season_year: str = "2025-2026"` default | season_config |
| `modules/data_loader.py` | 446-453 | Default records with `"season_year": "2025-2026"` | season_config |
| `modules/data_loader.py` | 511 | `season_year: str = "2025-2026"` default | season_config |
| `modules/season_performers.py` | 50 | `NBA_SEASON = "2025-26"` | season_config |
| `modules/season_performers.py` | 98 | `'data/nba_schedule_2025-26.json'` | season_config |
| `modules/consistency_score.py` | 393 | `lineups["season_year"] == "2025-2026"` | season_config |
| `modules/consistency_score.py` | 458 | `lineups["season_year"] == "2025-2026"` | season_config |
| `modules/luck_index.py` | 603 | `current_season: str = "2025-26"` default | season_config |
| `modules/keepability_v2.py` | 682 | `current_season: str = "2025-26"` default | season_config |
| `modules/keepability_v2.py` | 735-744 | `season_lengths` dict (8 historical seasons) | season_config |
| `modules/keepability_v2.py` | 747 | `season_lengths[current_season] = 21` | season_config |
| `modules/simulator_betting.py` | 790 | `"2025-26"` default for current_season | season_config |
| `modules/records_tracker.py` | 498, 1171, 1243, 1297, 1834, 1842, 1851, 1930, 1982, 2124 | `"2025-26"` (10 occurrences across functions) | season_config |
| `modules/report_builder.py` | 1545 | `cs = "2025-26"` | season_config |
| `modules/report_builder.py` | 1752 | `current_season = "2025-26"` | season_config |
| `modules/report_builder.py` | 2713 | `current_season="2025-26"` in call | season_config |
| `modules/report_builder.py` | 3285 | `current_season="2025-26"` in call | season_config |
| `modules/player_card_builder.py` | 48-49 | `CURRENT_SEASON_KEY = "2025-26"`, `CURRENT_SEASON_YEAR = "2025-2026"` | season_config |
| `scripts/update_fantasy_logs.py` | 14-15 | `NBA_SEASON = "2025-26"`, `SEASON_YEAR_LABEL = "2025-2026"` | season_config |
| `scripts/update_fantasy_logs.py` | 262 | `"nba_schedule_2025-26.json"` filename | season_config |
| `scripts/update_leaguehistory.py` | 284 | `default="2025-2026"` for --season arg | season_config |
| `scripts/pull_current_draft.py` | 35 | `SEASON = "2025-26"` | season_config |
| `scripts/backfill_player_records.py` | 57-58 | `CURRENT_SEASON = "2025-26"`, `CURRENT_SEASON_LONG = "2025-2026"` | season_config |
| `scripts/debug_backfill_player_records.py` | 57-58 | Same as above | season_config |
| `scripts/format_stats_report.py` | 1915, 1918 | `"2025-26"` season string | season_config |
| `scripts/enrich_historical_playerlog.py` | 52-61 | `ALL_SEASONS` list (8 seasons) | season_config |

**Total:** ~35 occurrences of season strings across ~18 files.

#### Season Structure Constants

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `modules/simulator_playoff_odds.py` | 37-39 | `REGULAR_SEASON_WEEKS = 21`, `SEMIFINAL_WEEK = 22`, `FINALS_WEEK = 23` | season_config |
| `modules/records_tracker.py` | 1982 | `max_regular_season_week: int = 21` | season_config |
| `modules/keepability_v2.py` | 747 | `season_lengths[current_season] = 21` | season_config |
| `modules/stats_corner_viz.py` | 65-75 | `PLAYOFF_WEEKS` dict (per-season playoff week mapping) | season_config |
| `modules/player_card_builder.py` | 905-916 | `SEASON_START_DATES` dict (10 NBA season start dates) | season_config / historical |

#### Hardcoded Week Numbers

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `scripts/debug_backfill_player_records.py` | 1428 | `records["last_updated_week"] = 16` | **remove/fix (stale debug value)** |
| `scripts/backfill_waivers.py` | 316 | `default=14` for --end week arg | remove/fix (stale default) |

---

### 2C. Paths & Portability

#### Absolute Paths

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `modules/player_card_builder.py` | 24 | `cd C:/Users/1429524/Desktop/newsletter` (in comment) | remove/fix |
| `scripts/enrich_historical_playerlog.py` | 18 | `cd C:/Users/1429524/Desktop/newsletter` (in docstring) | remove/fix |
| `scripts/generate_player_card_preview.py` | 9 | `cd C:/Users/1429524/Desktop/newsletter` (in docstring) | remove/fix |
| `scripts/backfill_waivers.py` | 26 | `C:/Users/you/Desktop/newsletter` (in docstring, already generic) | OK |
| `PROJECTSTRUCTURE.md` | 8 | `C:\Users\1429524\Desktop\newsletter\` | remove/fix |
| `WEEKLY_WORKFLOW.md` | 9, 422 | `cd C:\Users\1429524\Desktop\newsletter` | remove/fix |

#### Hardcoded Backslashes in Strings

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `scripts/update_fantasy_logs.py` | 267-268 | `"Run: python scripts\\fetch_nba_schedule.py --season 2025-26 --output data\\nba_schedule_2025-26.json"` | remove/fix (use forward slashes) |
| `scripts/generate_player_card_preview.py` | 112 | `start output\\player_card_preview.html` (Windows-only `start` command) | remove/fix |
| `scripts/newsletter_html_generator.py` | 8 | Backslash paths throughout usage docstring | remove/fix |

---

### 2D. Other Constants

#### Simulation Parameters

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `modules/simulator_title_odds.py` | 34 | `DEFAULT_NUM_SIMULATIONS = 10000` | engine constant (already CLI-overridable) |
| `modules/simulator_playoff_odds.py` | 36 | `DEFAULT_NUM_SIMULATIONS = 10000` | engine constant |
| `modules/simulator_betting.py` | 37 | `DEFAULT_NUM_SIMULATIONS = 5000` | engine constant |
| `modules/lineup_optimizer.py` | 204 | `max_iterations: int = 10000` | engine constant |

#### External URLs / API Endpoints

| File | Line(s) | Value | Destination |
|------|---------|-------|-------------|
| `scripts/fetch_nba_schedule.py` | 38 | `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json` | engine constant |
| `scripts/build_rookie_seasons.py` | 106 | `https://www.basketball-reference.com/search/search.fcgi` | engine constant |
| `scripts/enrich_historical_playerlog.py` | 132-146 | NBA API headers for `stats.nba.com` | engine constant |

#### Hardcoded Filenames

All scripts use relative paths like `"data/PLAYERLOG.xlsx"`, `"config/ROSTERS.json"`, etc. These are project-convention paths and should remain as-is (engine constants), not user-configurable.

---

## 3. CROSS-PLATFORM ISSUES

### Windows-Specific Path References

| Issue | File | Line(s) | Severity |
|-------|------|---------|----------|
| Absolute path `C:/Users/1429524/...` in comment | `modules/player_card_builder.py` | 24 | Low (comment only) |
| Absolute path `C:/Users/1429524/...` in docstring | `scripts/enrich_historical_playerlog.py` | 18 | Low (docstring only) |
| Absolute path `C:/Users/1429524/...` in docstring | `scripts/generate_player_card_preview.py` | 9 | Low (docstring only) |
| Absolute path `C:\Users\1429524\...` | `PROJECTSTRUCTURE.md` | 8 | Medium (user-facing docs) |
| Absolute path `C:\Users\1429524\...` (2 occurrences) | `WEEKLY_WORKFLOW.md` | 9, 422 | Medium (user-facing docs) |

### Windows-Specific Commands

| Issue | File | Line(s) | Severity |
|-------|------|---------|----------|
| `start output\\player_card_preview.html` (Windows `start` command) | `scripts/generate_player_card_preview.py` | 112 | Medium (would fail on Mac; use `webbrowser.open()`) |
| Backslash paths in error message | `scripts/update_fantasy_logs.py` | 267-268 | Low (display only) |
| Backslash paths in usage docstring | `scripts/newsletter_html_generator.py` | 8 | Low (display only) |

### What's NOT an issue

- **Path handling in runtime code:** The project overwhelmingly uses `pathlib.Path` and `os.path.join`, which are cross-platform safe. Only one instance of `os.path.join` (in `backfill_trades.py` line 58) which is also safe.
- **No `os.system()` calls** found in any .py file.
- **File encoding:** All I/O consistently uses `encoding="utf-8"`. The project even includes `check_file_health.py` to detect encoding corruption.
- **No Windows-specific imports** (no `winreg`, `msvcrt`, etc.).
- **User-Agent strings** contain `"Windows NT 10.0"` but this is a scraping header, not a platform dependency. Works fine from Mac.

---

## 4. DEPENDENCY AUDIT

### requirements.txt Contents

| Package | Version Spec | Actually Imported? | Notes |
|---------|-------------|-------------------|-------|
| `pandas` | `>=2.0.0` | Yes (14 files) | Core data library |
| `numpy` | `>=1.24.0` | Yes (2 files: `projections.py`, `weekly_stats.py`) | Used for variance/stats |
| `openpyxl` | `>=3.1.0` | Yes (2 files: `update_leaguehistory.py`, `format_stats_report.py`) | Excel engine for pandas |
| `yahoo-oauth` | `>=2.0` | Yes (8 files) | Yahoo API auth |
| `yahoo-fantasy-api` | `>=2.0` | Yes (8 files) | Yahoo Fantasy wrapper |
| `nba_api` | `>=1.2.0` | Yes (2 files: `season_performers.py`, `enrich_historical_playerlog.py`) | NBA stats API |
| `reportlab` | `>=4.0.0` | **NO -- never imported** | Legacy PDF generator, dead dependency |
| `requests` | `>=2.28.0` | Yes (2 files: `fetch_nba_schedule.py`, `build_rookie_seasons.py`) | HTTP requests (optional fallback in fetch_nba_schedule) |
| `python-dateutil` | `>=2.8.0` | **NO -- never explicitly imported** | May be a transitive dependency of pandas |

### Missing from requirements.txt

| Package | Used In | Notes |
|---------|---------|-------|
| `beautifulsoup4` | `scripts/build_rookie_seasons.py` (as `from bs4 import BeautifulSoup`) | **MISSING -- will crash on fresh install** |

### Version Pinning

All dependencies use **minimum version floors only** (e.g., `>=2.0.0`), not exact pins. Commented-out exact pins exist at the bottom of the file (e.g., `pandas==2.1.4`, `numpy==1.26.3`) but are inactive.

**Recommendation:** Use exact pins for reproducibility. The commented pins are a good starting point.

### Python Version

The project requires **Python 3.10+** (per requirements.txt header comment). The README mentions Python 3.14 which should be corrected to 3.10+. No syntax features beyond 3.10 are used (`from __future__ import annotations` handles type hint compatibility).

### Summary

- **1 missing dependency:** `beautifulsoup4` (imported but not in requirements.txt)
- **2 unused dependencies:** `reportlab` (never imported), `python-dateutil` (never explicitly imported)
- **0 exact version pins** (all floor-only)

---

## 5. CONFIGURATION TOUCHPOINTS

For each file containing hardcoded league-specific values, here's how values are currently sourced and the recommended refactor path.

### `modules/data_loader.py` -- THE CENTRAL CONFIG HUB

**Current:** Module-level constants (`MANAGERS`, `MANAGER_TO_TEAM`, `TEAM_TO_MANAGER`) defined at the top of the file. Season string defaults in function signatures.

**Refactor:** This should be the ONLY file that reads `league_config.json`. All other modules already import from here. Steps:
1. Create `config/league_config.json` with `managers`, `manager_to_team`, `yahoo_league_key`, `league_name`, `manager_colors`, `league_keys_historical`, `league_structure` (num_teams, draft_rounds, roster_size, keepers_per_team, keeper_era_start)
2. Create a `season_config` section (or separate file) with `current_season`, `current_season_long`, `regular_season_weeks`, `playoff_start_week`, `total_weeks`, `nba_schedule_file`
3. Have `data_loader.py` load these at import time and expose the same constants it does today
4. No other file needs to change its imports -- they already get `MANAGERS` etc. from `data_loader`

### `modules/fetch_injury_statuses.py` & `modules/season_performers.py`

**Current:** Each defines its own `LEAGUE_KEY`, `YAHOO_GAME_CODE`, and `FANTASY_TEAM_TO_MANAGER` as module-level constants.

**Refactor:** Import from `data_loader` (which would read from config). Both files already have `from .data_loader import ...` patterns; just add the Yahoo constants to `data_loader`'s exports.

### `modules/player_card_modal.py`

**Current:** `MANAGER_COLORS` defined as Python dict, then the SAME colors are hardcoded AGAIN in 3 separate JavaScript string literals inside the module's HTML generation functions.

**Refactor:** Import `MANAGER_COLORS` from `data_loader`, then inject them into JS via `json.dumps()` template substitution. This is the single hardest refactor because the JS strings are deeply embedded in multi-line f-strings.

### `modules/stats_corner_viz.py`

**Current:** Defines its own `MANAGER_COLORS`, `MANAGER_TEAMS`, `MANAGERS_LIST`, `MGR_COLORS_HIST`, and `PLAYOFF_WEEKS` as module-level constants. Also has hardcoded `pre_2017_firsts` and `pre_2017_titles` in function bodies.

**Refactor:** Import `MANAGERS`, `MANAGER_TO_TEAM`, `MANAGER_COLORS` from `data_loader`. Move `pre_2017_firsts/titles` to `league_config.json` as `pre_data_era_firsts` and `pre_data_era_titles`. Move `PLAYOFF_WEEKS` to season config.

### `modules/simulator_title_odds.py`

**Current:** `range(4)` and `{1: 0, 2: 0, 3: 0, 4: 0}` hardcoded in finish distribution logic.

**Refactor:** Import `NUM_TEAMS` from `data_loader` (derived from `len(MANAGERS)`). Replace `range(4)` with `range(NUM_TEAMS)` and build the finish dict dynamically.

### `modules/simulator_playoff_odds.py`

**Current:** `REGULAR_SEASON_WEEKS`, `SEMIFINAL_WEEK`, `FINALS_WEEK` as module-level constants.

**Refactor:** Import from `data_loader` (which reads from season config).

### `modules/records_tracker.py`

**Current:** `"2025-26"` appears as default parameter values in 10+ function signatures.

**Refactor:** Import `CURRENT_SEASON` from `data_loader`. Use as default value in function signatures. Since Python evaluates defaults at definition time and `data_loader` is loaded at import time, this works cleanly.

### `modules/consistency_score.py`

**Current:** `"2025-2026"` hardcoded in 2 DataFrame filter expressions.

**Refactor:** Import `CURRENT_SEASON_LONG` from `data_loader`.

### `modules/report_builder.py`

**Current:** `"2025-26"` appears in 4 places as inline string literals.

**Refactor:** Import `CURRENT_SEASON` from `data_loader`.

### `modules/keepability_v2.py`

**Current:** Season string as default parameter; `season_lengths` dict with 8 historical seasons hardcoded in function body.

**Refactor:** Import `CURRENT_SEASON` from `data_loader`. Move `season_lengths` to season config or compute from historical data.

### `scripts/update_fantasy_logs.py`, `sync_transactions.py`, `backfill_waivers.py`

**Current:** Each defines its own `LEAGUE_KEY` and `FANTASY_TEAM_TO_MANAGER` as module-level constants.

**Refactor:** All three should read from `league_config.json` directly (scripts can't import from `modules/` without path manipulation). Create a shared `config_loader` utility or have each script load the JSON file.

### `scripts/format_stats_report.py`

**Current:** `["Nick", "Hayden", "Benton", "Garrett"]` appears in ~8 inline list literals. The magic number logic (lines 2209-2211) is hardcoded to "Nick" and "Benton" specifically.

**Refactor:** Load managers list from config at the top of the script. The magic number logic needs a more structural refactor -- it assumes specific manager rivalries.

### `scripts/newsletter_html_generator.py`

**Current:** `MANAGER_TO_TEAM` dict, brand colors (`HELMET_BLUE`, `ACCENT_GOLD`), and league name all as module-level constants.

**Refactor:** Read from `league_config.json`. Brand colors should be in the config too.

### `scripts/build_draft_pick_values.py`

**Current:** `TEAMS = 4`, `HISTORICAL_DRAFT_ROUNDS = 7`, `TOTAL_DRAFT_ROUNDS = 9`, `keepers_per_team=6`, `roster_size=17` as module-level constants and function parameters.

**Refactor:** Read from `league_config.json` `league_structure` section.

### `scripts/backfill_draft_names.py`, `backfill_trades.py`, `pull_historical_data.py`

**Current:** Each defines its own `LEAGUE_KEYS` dict and `MANAGER_ALIASES` dict.

**Refactor:** Read from `league_config.json` `league_keys_historical` and `manager_aliases` sections.

### `scripts/pull_current_draft.py`

**Current:** `LEAGUE_KEY`, `SEASON`, `MANAGER_ALIASES` as module-level constants.

**Refactor:** Read from `league_config.json`.

---

## 6. SEASON LIFECYCLE

### Permanent (engine code, never changes between seasons)

| Category | Files |
|----------|-------|
| **Core engine modules** | `weekly_stats.py`, `projections.py`, `schedule_strength.py`, `lineup_optimizer.py`, `fun_facts_generator.py`, `waiver_roi.py`, `what_if_analyzer.py`, `rumor_mill_analyzer.py`, `content_freshness.py` |
| **Simulator engines** | `simulator_playoff_odds.py`, `simulator_title_odds.py`, `simulator_betting.py` (after extracting season constants) |
| **Scoring engines** | `consistency_score.py`, `luck_index.py`, `keepability_v2.py` (after extracting season strings) |
| **Orchestrators** | `report_builder.py`, `__init__.py` (after extracting season strings) |
| **Visualization** | `player_card_modal.py`, `stats_corner_viz.py`, `player_card_builder.py` (after extracting league data) |
| **Data loader** | `data_loader.py` (after refactor to read from config) |
| **Records engine** | `records_tracker.py` (after extracting season strings) |
| **Utility scripts** | `check_file_health.py`, `fetch_nba_schedule.py`, `build_rookie_seasons.py`, `extract_draft_fppg.py`, `enrich_historical_playerlog.py` |
| **Report scripts** | `generate_stats_report.py`, `format_stats_report.py` (after extracting manager lists) |
| **HTML generator** | `newsletter_html_generator.py` (after extracting branding) |
| **Templates** | `templates/newsletter_template.md` (needs manager table made generic) |
| **Docs** | `README.md` (after updating), `.gitignore` |

### League Identity (set once, rarely changes)

| Item | Location | Notes |
|------|----------|-------|
| Manager names | To be in `league_config.json` | Currently scattered across ~15 files |
| Team names (Yahoo) | To be in `league_config.json` | Currently scattered across ~7 files |
| Yahoo league key (current) | To be in `league_config.json` | Currently in 6 files |
| Yahoo league keys (historical) | To be in `league_config.json` | Needed only for backfill scripts |
| Manager aliases | To be in `league_config.json` | Yahoo API returns lowercase; map to proper case |
| Manager colors | To be in `league_config.json` | Currently in 4 files + 3 JS embeds |
| Brand colors | To be in `league_config.json` | `HELMET_BLUE`, `ACCENT_GOLD` |
| League name | To be in `league_config.json` | `"CHS Alumni"` / `"CHS Fantasy Basketball"` |
| Num teams | To be in `league_config.json` | Hardcoded `4` |
| Draft rounds, roster size, keepers | To be in `league_config.json` | League structure |
| Keeper era start | To be in `league_config.json` | `"2021-22"` |
| Pre-data-era history | To be in `league_config.json` | `pre_2017_firsts`, `pre_2017_titles` |
| `config/DRAFT_PICK_VALUES.json` | Config file | Regenerated occasionally, not per-season |
| `config/ROOKIE_SEASONS.json` | Config file | Grows over time, not season-bound |
| `oauth2.json` | Root (gitignored) | Must provide `oauth2.json.example` |

### Per-Season Inputs (reset each year)

| Item | Location | How Created |
|------|----------|-------------|
| `config/SCHEDULE.json` | Config file | Manually created or generated from Yahoo (contains matchups, dates, managers) |
| `config/ROSTERS.json` | Config file | Generated by `generate_rosters.py` or `sync_transactions.py` |
| `config/DRAFT_PICKS_CURRENT.json` | Config file | Generated by `pull_current_draft.py` |
| `config/INJURY_OVERRIDES.json` | Config file | Manually maintained weekly |
| `config/TRADES.json` | Config file | Manually updated after each trade |
| `data/nba_schedule_2025-26.json` | Data file | Generated by `fetch_nba_schedule.py` |
| `data/PLAYERLOG.xlsx` | Data file | Updated daily by `update_fantasy_logs.py` |
| `data/LINEUPS.xlsx` | Data file | Updated daily by `update_fantasy_logs.py` |
| `data/LEAGUEHISTORY.xlsx` | Data file | Updated weekly by `update_leaguehistory.py` |
| `data/waivers_week*.txt` | Data files (23) | Generated weekly by `sync_transactions.py` |
| Season string constants | Scattered across ~18 files | Must be updated in config at season start |

### Per-Season Outputs (generated weekly, disposable)

| Item | Location | Generated By |
|------|----------|-------------|
| `output/stats_report_week*.json` | Output | `generate_stats_report.py` |
| `output/stats_report_week*.md` | Output | `format_stats_report.py` |
| `output/looking_ahead_week*.json` | Output | `generate_stats_report.py` |
| `output/WEEK*_NEWSLETTER.html` | Output | `newsletter_html_generator.py` |
| `assets/WEEK*_DRAFT.md` | Assets | LLM-authored newsletter drafts |
| `config/RECENT_CONTENT.json` | Config | Accumulated by `content_freshness.py` |
| `config/POTW_HISTORY.json` | Config | Updated by `format_stats_report.py` |
| `config/snapshots/RECENT_CONTENT_*.json` | Snapshots | Pre/post-week backups |
| `config/RECORDS.json` (current-season portion) | Config | Updated by `backfill_player_records.py` |

### Historical (append-only, rolls forward)

| Item | Location | Notes |
|------|----------|-------|
| `data/historical/all_drafts.json` | Historical data | All draft picks, all seasons |
| `data/historical/all_matchups.json` | Historical data | All matchup results, all seasons |
| `data/historical/all_standings.json` | Historical data | Final standings, all seasons |
| `data/historical/all_teams.json` | Historical data | Team rosters by season |
| `data/historical/all_trades.json` | Historical data | All trades, all seasons |
| `data/historical/historical_summary.json` | Historical data | Aggregated historical stats |
| `data/historical/HISTORICAL_PLAYERLOG.json` | Historical data | Player game logs, all prior seasons |
| `data/historical/DRAFT_PERFORMANCE.json` | Historical data | Draft pick outcomes |
| `config/RECORDS.json` (all-time portion) | Config | All-time records, top-10 leaderboards |
| `templates/NEWSLETTER_PROMPTS.md` | Template | Contains manager/team table (needs updating per-league) |

---

## APPENDIX A: Proposed `league_config.json` Schema

```json
{
    "league_name": "CHS Alumni Fantasy Basketball League",
    "league_name_short": "CHS Alumni",
    "brand_colors": {
        "primary": "#1F4E79",
        "accent": "#C9A227"
    },
    "managers": ["Nick", "Hayden", "Benton", "Garrett"],
    "manager_to_team": {
        "Nick": "Luka my Balls",
        "Hayden": "Big Nik Energy",
        "Benton": "Smaxey",
        "Garrett": "Saboner"
    },
    "manager_aliases": {
        "nick": "Nick",
        "hayden": "Hayden",
        "benton": "Benton",
        "garrett": "Garrett"
    },
    "manager_colors": {
        "Nick": "#1F4E79",
        "Hayden": "#C9A227",
        "Benton": "#5B8C5A",
        "Garrett": "#B85C38"
    },
    "yahoo": {
        "game_code": "nba",
        "current_league_key": "466.l.42309",
        "historical_league_keys": {
            "2017-18": "380.l.23647",
            "2018-19": "390.l.19887",
            "2019-20": "402.l.24547",
            "2020-21": "411.l.45773",
            "2021-22": "418.l.129050",
            "2022-23": "428.l.10093",
            "2023-24": "438.l.31099",
            "2024-25": "451.l.13907",
            "2025-26": "466.l.42309"
        }
    },
    "league_structure": {
        "num_teams": 4,
        "roster_size": 17,
        "starters": 10,
        "bench": 5,
        "il_slots": 2,
        "keepers_per_team": 6,
        "historical_draft_rounds": 7,
        "total_draft_rounds": 9,
        "keeper_era_start": "2021-22"
    },
    "tiebreaker_rules": {
        "standings": "h2h_regular_season",
        "fallback": "total_points"
    },
    "pre_data_era": {
        "first_place_finishes": {"Nick": 1, "Hayden": 1},
        "titles": {"Nick": 1, "Benton": 1}
    },
    "season": {
        "current": "2025-26",
        "current_long": "2025-2026",
        "season_number": 9,
        "regular_season_weeks": 21,
        "playoff_start_week": 22,
        "total_weeks": 23,
        "nba_schedule_file": "data/nba_schedule_2025-26.json"
    }
}
```

## APPENDIX B: Duplication Heat Map

Number of files where each value is independently defined (not imported):

| Value | Files | Risk |
|-------|-------|------|
| `MANAGERS` list | 4 | High -- drift risk |
| `MANAGER_TO_TEAM` dict | 7 | High -- 7 independent copies |
| `LEAGUE_KEY` | 6 | High -- easy to miss one during key rotation |
| `MANAGER_COLORS` | 4 Python + 3 JS embeds = 7 | **Critical** -- includes color mismatch bug |
| `"2025-26"` season string | 18 | **Critical** -- 35+ occurrences, guaranteed misses during season rollover |
| `MANAGER_ALIASES` | 3 | Medium |
| `KEEPER_ERA_START` | 3 | Low -- changes rarely |

## APPENDIX C: Files to Delete

| File | Reason |
|------|--------|
| `modules/simulator_playoff_odds - Copy.py` | Dead backup, identical to primary |
| `scripts/debug_backfill_player_records.py` | Debug copy with stale hardcoded `last_updated_week = 16`; main version is fixed |
| `config/RECORDS - Copy.json` | Backup copy of RECORDS.json |

## APPENDIX D: Refactor Priority Order

1. **Create `config/league_config.json`** with the schema above -- this is the single config file a new user fills in.
2. **Refactor `modules/data_loader.py`** to load from `league_config.json` instead of defining constants inline. All downstream modules already import from here, so this one change propagates to ~15 files.
3. **Refactor scripts** (`update_fantasy_logs.py`, `sync_transactions.py`, `backfill_waivers.py`, `pull_current_draft.py`, etc.) to load from `league_config.json` directly (they can't import from modules without path setup).
4. **Fix `player_card_modal.py`** JS injection -- replace hardcoded JS color dicts with `json.dumps()` template substitution from the Python-side config.
5. **Fix `stats_corner_viz.py`** duplication -- remove all local constant definitions, import everything from `data_loader`.
6. **Fix `format_stats_report.py`** -- replace 8+ inline manager list literals with a config-loaded list. Restructure the magic number logic to work with any manager pairing.
7. **Create `oauth2.json.example`** with placeholder structure.
8. **Delete dead files** (Appendix C).
9. **Fix cross-platform issues** (Section 3) -- replace Windows paths in docs and error messages.
10. **Fix `requirements.txt`** -- add `beautifulsoup4`, remove `reportlab` and `python-dateutil`, add exact version pins.
