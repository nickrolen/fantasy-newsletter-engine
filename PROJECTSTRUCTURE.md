# Newsletter Project Structure

Quick-reference structural map for the Fantasy Basketball Newsletter engine.
For the showcase overview and setup, see `README.md`. For the weekly run sequence,
see `WEEKLY_WORKFLOW.md`. For the season rollover runbook, see `SEASON_RESET.md`.

The entire engine is driven by a single config file (`config/league_config.json`).
No league names, team names, colors, or Yahoo keys are hardcoded anywhere in the code.

## Complete Folder Structure

```
newsletter/
|
+-- config/                           # League config + per-season state
|   +-- league_config.json            # *** THE ONE FILE a new user fills in ***
|   +-- league_config.json.example    # Placeholder template for new leagues
|   +-- DRAFT_PICK_VALUES.json        # Pick-level (P1-P36) expected FPPG + Total FP
|   +-- DRAFT_PICKS_CURRENT.json      # Current season draft picks (R1-7 drafted, R8-13 keepers)
|   +-- INJURY_OVERRIDES.json         # Manual injury status overrides (includes return fields)
|   +-- LAST_WEEK_RECAP.md            # Reporter's notebook -- narrative continuity
|   +-- POTW_HISTORY.json             # Player of the Week history (multi-season, auto-updated)
|   +-- RECENT_CONTENT.json           # Tracks recently shown content for freshness
|   +-- RECORDS.json                  # League records (weekly_scores, top-10 leaderboards)
|   +-- ROSTERS.json                  # Current team rosters (editable)
|   +-- ROOKIE_SEASONS.json           # NBA debut seasons per player (built by script)
|   +-- SCHEDULE.json                 # Fantasy schedule (regular + playoff weeks, routing metadata)
|   +-- TRADES.json                   # Trade history + draft pick ownership
|   +-- .file_baselines.json          # Integrity-check size baseline (machine-specific, gitignored)
|   |
|   \-- snapshots/                    # Reproducibility snapshots (--repro flag)
|       +-- RECENT_CONTENT_pre_week{N}.json
|       \-- RECENT_CONTENT_post_week{N}.json
|
+-- data/                             # Raw data + historical archives
|   +-- LEAGUEHISTORY.xlsx            # Historical league data (includes blunder tracking)
|   +-- LINEUPS.xlsx                  # Yahoo lineup data
|   +-- PLAYERLIST.xlsx               # Player projections & info
|   +-- PLAYERLOG.xlsx                # Game-by-game player stats
|   +-- nba_schedule_{season}.json    # NBA game schedule (filename set in league_config.json)
|   +-- waivers_week{N}.txt           # Weekly waiver wire moves
|   +-- weeklycontextinput_week{N}.json  # Weekly context for LLM (trades, storylines)
|   |
|   \-- historical/                   # Multi-season archives (updated yearly)
|       +-- all_drafts.json
|       +-- all_matchups.json
|       +-- all_standings.json
|       +-- all_teams.json
|       +-- all_trades.json
|       +-- historical_summary.json
|       +-- DRAFT_PERFORMANCE.json    # Per-pick stats across all seasons
|       \-- HISTORICAL_PLAYERLOG.json # Game-level player data across 8 seasons (2017-25)
|
+-- modules/                          # Analysis engine -- imported by scripts (24 files)
|   +-- __init__.py                   # Central import hub; re-exports all submodules
|   +-- data_loader.py                # Loads all data + reads league_config.json (config hub)
|   +-- weekly_stats.py               # Weekly team and player statistics
|   +-- projections.py                # Player projections + return field handling
|   +-- schedule_strength.py          # Schedule Strength Index (NBA games per roster)
|   +-- lineup_optimizer.py           # Optimal daily lineup solver
|   +-- consistency_score.py          # Consistency/Volatility (team + player CV, IQR, boom/bust)
|   +-- luck_index.py                 # Luck Index (all-play expected wins)
|   +-- keepability_v2.py             # Keeper scoring (5 components + age multiplier)
|   +-- records_tracker.py            # Records, H2H streaks, blunders, top-10 leaderboards
|   +-- report_builder.py             # Orchestrator -- assembles the full JSON report
|   +-- player_card_builder.py        # Player card data (career history, archetypes)
|   +-- player_card_modal.py          # Interactive player card modal HTML/CSS/JS
|   +-- stats_corner_viz.py           # Stats Corner HTML visualizations + record book
|   +-- content_freshness.py          # Tracks recently used content to prevent repetition
|   +-- fun_facts_generator.py        # Auto-generates fun facts from weekly/season data
|   +-- waiver_roi.py                 # Waiver Wire ROI (season-long transaction value)
|   +-- what_if_analyzer.py           # What-if analysis + blunder detection
|   +-- season_performers.py          # Season-to-date best/worst performers (Yahoo API)
|   +-- fetch_injury_statuses.py      # Yahoo API injury status fetcher (optional)
|   +-- rumor_mill_analyzer.py        # Trade ideas, FA targets, drop candidates
|   +-- simulator_title_odds.py       # Regular season title odds (Monte Carlo)
|   +-- simulator_playoff_odds.py     # Playoff bracket championship odds (Monte Carlo)
|   \-- simulator_betting.py          # Betting lines (spread, O/U, moneyline) + O/U injury discount
|
+-- scripts/                          # Pipeline steps + utilities (22 scripts)
|   +-- generate_stats_report.py      # Main entry point -- builds stats_report_week{N}.json
|   +-- format_stats_report.py        # JSON -> newsletter-ready Markdown (deterministic)
|   +-- newsletter_html_generator.py  # Markdown draft -> styled HTML newsletter
|   +-- update_fantasy_logs.py        # Daily pull from Yahoo -> PLAYERLOG/LINEUPS
|   +-- sync_transactions.py          # Sync Yahoo transactions -> ROSTERS + waivers file
|   +-- generate_rosters.py           # Generate ROSTERS.json from LINEUPS
|   +-- update_leaguehistory.py       # Update LEAGUEHISTORY.xlsx with weekly stats
|   +-- pull_current_draft.py         # Pull current season draft from Yahoo API
|   +-- pull_historical_data.py       # Pull historical data (end-of-season)
|   +-- backfill_draft_names.py       # Backfill draft player names from Yahoo API
|   +-- backfill_trades.py            # Populate all_trades.json from Yahoo API
|   +-- backfill_waivers.py           # Regenerate waivers files from Yahoo history
|   +-- backfill_player_records.py    # Recompute all-time top-10 leaderboards
|   +-- build_draft_pick_values.py    # Build DRAFT_PICK_VALUES.json (regression model)
|   +-- build_rookie_seasons.py       # Basketball Reference scraper -> ROOKIE_SEASONS.json
|   +-- extract_draft_fppg.py         # Build DRAFT_PERFORMANCE.json
|   +-- enrich_historical_playerlog.py # Add NBA team/opponent data to historical playerlog
|   +-- fetch_nba_schedule.py         # Fetch NBA schedule from official API
|   +-- check_file_health.py          # ASCII enforcement for .py/.md files
|   +-- start_new_season.py           # Season reset: archive, reset, delete (see SEASON_RESET.md)
|   +-- verify_project_integrity.py   # Project health check (run after batch edits)
|   \-- generate_player_card_preview.py # Standalone HTML player card preview
|
+-- templates/
|   +-- newsletter_template.md        # Writing guide & reference manual (incl. Playoff Addendum)
|   +-- NEWSLETTER_PROMPTS.md         # Reusable 3-part drafting prompts (fill in weekly)
|   \-- NEWSLETTER_PROMPTS_WEEK{N}.md # Per-week filled-in prompt examples
|
+-- output/                           # Generated reports + newsletters
|   +-- stats_report_week{N}.json     # Stats report (JSON)
|   +-- stats_report_week{N}.md       # Newsletter-ready stats (Markdown)
|   +-- looking_ahead_week{N}.json    # Cached betting lines/previews (for --repro)
|   \-- WEEK{N}_NEWSLETTER.html       # Final newsletter HTML
|
+-- assets/
|   +-- helmet.png                    # Helmet icon for newsletter
|   +-- potw.png                      # Player of the Week graphic
|   +-- podium.png                    # Podium graphic for POTW section
|   \-- WEEK{N}_DRAFT.md              # Weekly newsletter drafts (LLM-authored)
|
+-- archive/                          # Archived past seasons (created by start_new_season.py)
|   \-- {season}/                     # Complete snapshot of one finished season
|
+-- oauth2.json                       # Yahoo OAuth credentials (gitignored)
+-- oauth2.json.example               # Placeholder credentials template
+-- requirements.txt                  # Python dependencies
+-- check_all.py                      # Convenience wrapper for project checks
+-- README.md                         # Showcase overview + setup
+-- WEEKLY_WORKFLOW.md                # Step-by-step weekly run sequence
+-- SEASON_RESET.md                   # Season rollover runbook
+-- PROJECTSTRUCTURE.md               # This file
\-- .gitignore
```

## Files Removed During Repackaging

These dead/backup files were deleted to clean up the repo. Do not recreate them:

- `modules/simulator_playoff_odds - Copy.py` -- exact backup of the playoff simulator
- `scripts/debug_backfill_player_records.py` -- debug copy with a stale hardcoded week
- `config/RECORDS - Copy.json` -- backup copy of RECORDS.json

## Configuration Model

`config/league_config.json` is the single source of truth for all league-specific
values: managers, team names, manager/brand colors, Yahoo league keys (current +
historical), league structure (teams, roster size, keepers, draft rounds), tiebreaker
rules, pre-data-era history, and the current season block. `modules/data_loader.py`
loads it at import time and exposes the values every other module and script consumes.
A new league only needs to copy `league_config.json.example` to `league_config.json`
and fill it in -- there is no need to edit any `.py` file.

## Path Conventions in Code

```python
from pathlib import Path

# Get project root (from a module in modules/)
PROJECT_ROOT = Path(__file__).parent.parent

# Config files
CONFIG_DIR = PROJECT_ROOT / "config"
LEAGUE_CONFIG_FILE = CONFIG_DIR / "league_config.json"
ROSTERS_FILE = CONFIG_DIR / "ROSTERS.json"
RECORDS_FILE = CONFIG_DIR / "RECORDS.json"
SCHEDULE_FILE = CONFIG_DIR / "SCHEDULE.json"

# Data files
DATA_DIR = PROJECT_ROOT / "data"
HISTORICAL_DIR = DATA_DIR / "historical"

# Output / assets / templates
OUTPUT_DIR = PROJECT_ROOT / "output"
ASSETS_DIR = PROJECT_ROOT / "assets"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
```

All runtime code uses `pathlib.Path` with relative project paths; there are no
absolute or machine-specific paths anywhere in the codebase.

## File Naming Conventions

- Weekly files use a `week{N}` or `WEEK{N}` suffix (e.g. `stats_report_week12.json`, `WEEK12_DRAFT.md`)
- Excel files: UPPERCASE with `.xlsx`
- JSON configs: UPPERCASE for hand-editable, lowercase for generated
- Python files: lowercase_with_underscores.py
- Source files (`.py`, `.md`) are pure ASCII (enforced by `check_file_health.py`)

## Manager / Team Mapping (reference implementation)

The CHS Alumni league is the reference implementation. These values live in
`config/league_config.json` and are what a new user replaces for their own league.

| Manager | Fantasy Team Name |
|---------|-------------------|
| Nick    | Luka my Balls     |
| Hayden  | Big Nik Energy    |
| Benton  | Smaxey            |
| Garrett | Saboner           |

## Pipeline Flow

```
                        league_config.json
                               |
Yahoo Fantasy API --> update_fantasy_logs.py --> PLAYERLOG.xlsx, LINEUPS.xlsx
                  --> sync_transactions.py    --> ROSTERS.json, waivers_week{N}.txt
NBA API           --> fetch_nba_schedule.py   --> nba_schedule_{season}.json
Manual input      --> INJURY_OVERRIDES.json, weeklycontextinput, LAST_WEEK_RECAP.md
                               |
                               v
            generate_stats_report.py
                               |
              +----------------+----------------+
              |                                 |
   week < regular_season_weeks      week >= regular_season_weeks
   -> simulator_title_odds.py       -> simulator_playoff_odds.py
              |                                 |
              +----------------+----------------+
                               v
            output/stats_report_week{N}.json
                               v
            format_stats_report.py
                               v
            output/stats_report_week{N}.md  (~650 lines, pre-cited)
                               v
            LLM drafting (manual) -> assets/WEEK{N}_DRAFT.md
                               v
            newsletter_html_generator.py
                               v
            output/WEEK{N}_NEWSLETTER.html
```

## Weekly Workflow (summary)

1. `update_fantasy_logs.py` -- pull Yahoo data into PLAYERLOG/LINEUPS
2. `update_leaguehistory.py` -- add weekly stats to cumulative totals
3. `generate_rosters.py` -- create ROSTERS.json baseline
4. `sync_transactions.py` -- apply waiver moves, write waivers file
5. Update `INJURY_OVERRIDES.json` -- injury status and mid-week returns
6. `generate_stats_report.py --week N` -- build the JSON report
7. `format_stats_report.py --week N` -- build the Markdown report
8. LLM drafts the newsletter from the Markdown -> `assets/WEEK{N}_DRAFT.md`
9. (Recommended) verify draft accuracy against the report
10. `newsletter_html_generator.py` -- render the final HTML
11. Update `LAST_WEEK_RECAP.md` and `RECENT_CONTENT.json` for continuity

See `WEEKLY_WORKFLOW.md` for the full commands.

## Season Lifecycle (summary)

At season end, `scripts/start_new_season.py` archives the season into
`archive/{season}/`, resets per-season working files to empty defaults, and deletes
generated artifacts -- dry run first, then `--execute`. Engine code, league identity
(`league_config.json`), and the permanent historical record are never touched. Run
`scripts/verify_project_integrity.py` afterward to confirm a clean state. The full
runbook is in `SEASON_RESET.md`.
