# Weekly Newsletter Workflow Guide

**Last updated:** February 10, 2026

This is the complete step-by-step workflow for generating the CHS Alumni Fantasy Basketball League weekly newsletter. Run these steps every Monday after the previous week ends.

All commands assume you're in the project root directory:
```
cd <project_root>
```

> **Batch file note:** If you put any of these commands in a `.bat` file, replace `%d` with `%%d` and `%N` with `%%N` in `for` loops.

---

## Before You Start: Fill In This Week's Info

Before running anything, identify these values for the current week:

| Variable | Description | Example (Week 15) |
|----------|-------------|--------------------|
| `WEEK` | The fantasy week that just ended | `15` |
| `START_DATE` | Monday of that week (YYYY-MM-DD) | `2026-01-26` |
| `END_DATE` | Sunday of that week (YYYY-MM-DD) | `2026-02-01` |
| `NEXT_WEEK_START` | Monday of the upcoming week | `2026-02-02` |
| `NEXT_WEEK_END` | Sunday of the upcoming week | `2026-02-08` |

Look these up in `config\SCHEDULE.json` if unsure.

---

## Step 0a: Project Integrity Check (sanity check)

**Run this first, every week.** It catches silent file truncation, broken imports, config drift, and encoding corruption that any earlier Cowork/automated edit session might have introduced.

```cmd
py scripts\verify_project_integrity.py
```

**Also run it:**
- After every Cowork/automated edit session (most important — automated edits are the main way silent truncation happens)
- After running `scripts\start_new_season.py` (see `SEASON_RESET.md`)

**What it checks:**

1. Python syntax of every `.py` file in `modules\` and `scripts\`
2. File-size baseline — flags any `.py` / `.json` / `.md` file that shrank by more than 20% (possible truncation) or disappeared
3. Import chain — imports every module in `modules\` to catch missing references
4. `config\league_config.json` schema (required keys, manager counts, alias coverage)
5. ASCII compliance for all `.py` files
6. Golden master check on `output\stats_report_week22.json` (only with `--compare-golden`)

**Exit code 0** means all checks passed (warnings about pre-existing ASCII chars are OK). **Exit code 1** means at least one failure — investigate before continuing the weekly workflow.

If you make a deliberate structural change (add/remove modules, intentionally rewrite a large file), refresh the baseline:

```cmd
py scripts\verify_project_integrity.py --baseline
```

---

## Step 0: Update NBA Schedule

The NBA schedule file can go stale due to postponements and rescheduling, which affects betting lines and title odds accuracy. **Run this first every week.**

```cmd
python scripts\fetch_nba_schedule.py --season 2025-26 --output data\nba_schedule_2025-26.json
```

**What this does:** Downloads the full NBA schedule from `cdn.nba.com`, trims it to ~120KB (date/home/away only), and saves it.

**If the NBA API is down:** Manually download from `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json`, then run:
```cmd
python scripts\fetch_nba_schedule.py --input raw_schedule.json --output data\nba_schedule_2025-26.json
```

---

## Step 1: Pull Yahoo Data

Pull lineup and scoring data from the Yahoo Fantasy API for each day of the week.

```cmd
:: Replace dates with the actual dates for your week (Monday through Sunday)
for %d in (YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD) do python scripts\update_fantasy_logs.py --date %d
```

**Example for Week 15:**
```cmd
for %d in (2026-01-26 2026-01-27 2026-01-28 2026-01-29 2026-01-30 2026-01-31 2026-02-01) do python scripts\update_fantasy_logs.py --date %d
```

**What each run does:**
- Connects to Yahoo Fantasy API via OAuth
- Pulls each team's roster for that date (who was on each lineup slot)
- Pulls each player's fantasy points for that date
- Appends rows to `data\LINEUPS.xlsx` and `data\PLAYERLOG.xlsx`
- Deduplicates by (season_year, date, manager, player_name)

**Verify:**
```cmd
python -c "import pandas as pd; pl=pd.read_excel('data\\PLAYERLOG.xlsx'); wk=pl[(pl['week']==WEEK) & (pl['started']==True)]; print(f'Week WEEK rows: {len(wk)}'); [print(f'  {m}: {len(wk[wk[\"manager\"]==m])} games, {wk[wk[\"manager\"]==m][\"fantasy_points\"].sum():.1f} FP') for m in ['Nick','Hayden','Benton','Garrett']]"
```
*(Replace `WEEK` with the actual week number. The `started==True` filter excludes bench/IL players whose NBA teams played but whose points don't count toward the Yahoo matchup score.)*

---

## Step 2: Update League History

Adds the week's stats to the cumulative `data\LEAGUEHISTORY.xlsx`.

```cmd
python scripts\update_leaguehistory.py --week WEEK
```

**What it computes per manager:** Total FP, scheduled games, healthy starter games, games lost to injury, games left on bench.

---

## Step 2.5: Update PLAYERLIST (with Claude)

PLAYERLIST contains ROS projections for the top ~125 fantasy players. Yahoo doesn't provide projections via API, so this step involves copying from Yahoo's website and parsing here.

### How to do it:

1. **Go to Yahoo Fantasy -> Players -> Sort by "Proj FP (ROS)"**
2. **Copy the top ~125 players** (select all, Ctrl+C -> it will include a lot of junk data)
3. **Paste the raw text into this Claude chat** and say something like: *"Here's this week's raw Yahoo projections data. Please parse it and generate an updated PLAYERLIST."*

### What Claude does:
- Parses the raw text to extract: player name, NBA team, positions, projected GP, projected total FP
- Strips accents (e.g., Don -> i -> -> Doncic)
- Calculates projectedFPPG (= total FP -> GP)
- Carries forward ages from last week's PLAYERLIST; web-searches ages for any new players
- Checks `config\ROSTERS.json` and adds any rostered players missing from the Yahoo top ~125 (e.g., Tatum, Haliburton) using last week's placeholder projections
- Outputs an updated `data\PLAYERLIST.xlsx` matching the exact column format

### Columns in PLAYERLIST.xlsx:
| Column | Type | Source |
|--------|------|--------|
| `player_name` | str | Yahoo (ASCII, no accents) |
| `player_nba_team` | str | Yahoo (e.g., "DEN", "LAL") |
| `player_position(s)` | str | Yahoo (e.g., "PG,SG") -> excludes Util/IL/IL+ |
| `player_total_proj_FP` | float | Yahoo |
| `player_proj_GP` | float | Yahoo |
| `projectedFPPG` | float | Calculated (total FP -> GP) |
| `age` | int | Carried from last week or web-searched |

### Key rules:
- **Every rostered player MUST be in the file**, even injured-for-season players like Tatum/Haliburton (they get placeholder values)
- Ages carry forward automatically; only new-to-the-list players need lookup
- File replaces `data\PLAYERLIST.xlsx` -> save the output there before proceeding

---

## Step 3: Generate Rosters File

Creates a baseline `config\ROSTERS.json` from the week's LINEUPS data.

```cmd
python scripts\generate_rosters.py --week WEEK --show-diff
```

**What it does:**
- Reads LINEUPS.xlsx, finds all unique players per manager for the given week
- Writes to `config\ROSTERS.json`
- `--show-diff` shows changes from the previous week's rosters

**Why this matters:** ROSTERS.json is the source of truth for all roster-dependent analysis (Slump Watch, Hot Streaks, Betting Lines, Title Odds, etc.).

**Note:** If a player was traded mid-week, both the pre-trade and post-trade rosters may appear, inflating player counts. Step 4 fixes this.

---

## Step 4: Sync Waiver Transactions

Updates ROSTERS.json with waiver/trade moves and creates the waivers file for the newsletter.

```cmd
:: Dry run first -> see what it finds without changing anything
python scripts\sync_transactions.py --week WEEK

:: Apply if everything looks right
python scripts\sync_transactions.py --week WEEK --apply
```

**What it does (two parts):**
1. **Waivers file:** Finds all Yahoo transactions during the week, writes adds to `data\waivers_weekN.txt`
2. **ROSTERS.json:** Applies ALL transactions since the week's start (including post-week moves like Monday morning pickups)

**After running, verify ROSTERS.json:**
- Each manager should have ~17 players
- No phantom players from mid-week trades
- Dropped players are gone, picked-up players are present

**Known edge case (fixed Feb 2026):** Same-day add-then-drop was processed in reverse order. The fix sorts transactions by Unix timestamp instead of date. If you see this bug, make sure you're using the updated `sync_transactions.py`.

---

## Step 5: Update INJURY_OVERRIDES.json (MANUAL)

Open `config\INJURY_OVERRIDES.json` and update based on current injury news.

### What to check:

1. **Players whose `out_weeks` end this week** -> Are they returning next week or still out?
   - If returning fully: remove the player from the file entirely
   - If returning partially: add return fields (see below)
   - If still out: extend `out_weeks`

2. **New injuries** -> Any players hurt during the week? Add new entries.

3. **Return fields** -> For confirmed partial returns next week:
```json
{
  "player_name": "Devin Booker",
  "out_weeks": [14, 15],
  "notes": "Ankle injury - out ~2 weeks starting week 14",
  "return_week": 16,
  "return_games": 1,
  "total_week_games": 3,
  "return_notes": "Possibly returning from ankle injury on 2/7"
}
```

### Optional: Create weeklycontextinput_weekN.json

If there are trades or notable storylines the stats report won't capture, create `data\weeklycontextinput_weekN.json`:

```json
{
  "week": 15,
  "trades": [
    {
      "manager_a": "Hayden",
      "sends_a": ["Michael Porter Jr.", "2027 2nd round pick"],
      "manager_b": "Benton",
      "sends_b": ["Lauri Markkanen", "2026 5th round pick", "2027 5th round pick"]
    }
  ],
  "notes": "Hayden stuck at 99 career wins for 3rd straight week"
}
```

**Why trades go here:** `sync_transactions.py` can detect player-for-player swaps but cannot detect draft pick compensation. Putting trades in this structured format ensures the formatter can enrich each traded player with projections from PLAYERLIST.xlsx and generate trade grade instructions for the LLM.

**Notes:** Can be a string or array of strings. For non-trade storylines only -> trade details belong in the `trades` array.

### Update TRADES.json (if trades occurred)

When a trade happens, also update `config\TRADES.json` with two changes:

1. **Add the trade to the `trades` array** -- includes week, date, both sides' players and picks
2. **Update `draft_pick_ownership`** -- move any traded picks to their new owner

This file is loaded by `format_stats_report.py` and automatically injected into the stats report markdown as **SEASON TRADE LOG** and **DRAFT PICK OWNERSHIP** blocks. These prevent the LLM from:
- Inventing trade history ("the first trade since the early-season blockbusters" when there was one last week)
- Suggesting managers trade picks they no longer own
- Claiming managers are "competing for the #1 pick" when one manager owns both 1st rounders

**Only non-default ownership is tracked** -- if a pick hasn't been traded, it's assumed to belong to its original manager. The file uses `{round}_{originalOwner}` keys (e.g., `"1_Garrett": "Hayden"` means Hayden now owns Garrett's 1st rounder).

---

## Step 5.75: Refresh All-Time Records (Record Book)

Recomputes all-time top-10 leaderboards for the Record Book from historical + current-season data.

```cmd
python scripts\backfill_player_records.py
```

**What it does:**
- Combines `data\historical\HISTORICAL_PLAYERLOG.json` with the current `data\PLAYERLOG.xlsx` into one unified game list
- Combines `data\historical\all_matchups.json` with current-season matchup results from `config\RECORDS.json`
- Recomputes ALL top-10 leaderboards across 5 categories (~50 tables): Team Records, Player Records, Rookie Records, Draft & Trades, Manager Records
- Updates career totals, franchise player badges, head-to-head records, manager milestones
- Writes results to `config\RECORDS.json["all_time"]`

**Why it's in the weekly workflow:** While `generate_stats_report.py` does runtime patching for ~12 matchup-derived tables (weekly scores, blowouts, streaks, manager seasons by Total FP and FP/week), the remaining ~35 tables (player single-game records, duo records, daily team records, outperformance, consistency, rookie records, draft/trade records, manager season FP/game, injury games, etc.) only update when this script runs. Running it weekly ensures the entire Record Book is accurate.

**Runtime:** A few seconds. Safe to re-run — deduplication and sanity caps prevent data corruption.

---

## Step 6: Generate the Stats Report

The main analysis engine -> runs all modules and produces the JSON that feeds the newsletter.

```cmd
python scripts\generate_stats_report.py --week WEEK
```

**For faster generation (skips Monte Carlo sims -> NOT recommended for final newsletter):**
```cmd
python scripts\generate_stats_report.py --week WEEK --fast
```

**For maximum accuracy:**
```cmd
python scripts\generate_stats_report.py --week WEEK --title-sims 10000 --betting-sims 5000
```

**What it does:**
1. Loads all data (PLAYERLOG, LINEUPS, PLAYERLIST, ROSTERS, SCHEDULE, RECORDS, INJURY_OVERRIDES, NBA schedule)
2. Loads `data\waivers_weekN.txt` for waiver context
3. Fetches live injury statuses from Yahoo API (auto-enabled if `oauth2.json` exists)
4. Builds complete stats report: matchup summaries, report cards, standings, streaks, scoring trends, title odds (Monte Carlo), betting lines, Player of the Week, What-If analysis, power rankings, rumor mill, fun facts, season performers
5. Saves to `output\stats_report_weekN.json`
6. Updates `config\RECORDS.json` with new standings, streaks, and records

**Runtime:** ~30-60 seconds with sims, ~5-10 seconds with `--fast`

**Useful flags:**
| Flag | What it does |
|------|-------------|
| `--fast` | Skip all Monte Carlo simulations |
| `--fetch-injuries` | Force Yahoo injury fetch (auto-enabled if oauth exists) |
| `--no-fetch-injuries` | Skip Yahoo injury fetch |
| `--title-sims N` | Set number of title odds simulations (default: 10000) |
| `--betting-sims N` | Set number of betting line simulations (default: 5000) |
| `--dry-run` | Don't save any files |
| `--no-save-records` | Don't update RECORDS.json |
| `--no-freshness` | Disable content repetition tracking |

---

## Step 6.5: Format Stats Report for Newsletter

Converts the JSON stats report into newsletter-ready markdown, eliminating the need for Claude to do data extraction.

```cmd
python scripts\format_stats_report.py --week WEEK
```

**What it does:**
- Reads `output\stats_report_weekN.json` (primary data source)
- Loads 5 additional data sources for enrichment:
  - Previous week's JSON -> upset detection (betting predictions), report card grade deltas, title odds movement
  - `data\PLAYERLIST.xlsx` -> player projections for key matchup selection and trade enrichment
  - `config\POTW_HISTORY.json` -> multi-season POTW award history (auto-saved each run)
  - `config\INJURY_OVERRIDES.json` -> injury timelines (weeks missed, first week out)
  - `data\weeklycontextinput_weekN.json` -> structured trade details (optional)
- Cross-references all data and outputs `output\stats_report_weekN.md` with all data pre-assembled by newsletter section

**Why this matters:** Previously, Claude had to extract and cross-reference data from 15+ JSON sections before writing. This step does that mechanically, so Claude can focus purely on writing engaging prose.

**Output:** ~650 lines of organized data, ready for drafting.

**Key section features:**
- Section 0: Upset flags when betting underdogs win
- Sections 2/7: Previous week comparisons (grades, title odds deltas)
- Section 3: 2-key-player rotation with injury filtering + Current Team Health
- Section 4: POTW career history and season leaderboard
- Section 9: Injury timelines + structured trade blocks with grade instructions

---

## Step 7: Draft the Newsletter (with Claude)

The newsletter is drafted in a **separate Claude chat** using a 3-part prompt system. The prompts live in `templates\NEWSLETTER_PROMPTS.md` -- open that file and follow its instructions.

### Pre-Flight (before opening the drafting chat)

Open `output\stats_report_weekN.md` and `config\LAST_WEEK_RECAP.md` to pull:
1. Week number, dates, and season
2. 3-5 key storylines (matchup results, upsets, streaks, title odds, POTW, milestones)
3. Whether fantasy trades happened (does `data\weeklycontextinput_weekN.json` exist?)
4. Current rosters from `config\ROSTERS.json` (needed for Part 3)

Fill in the `[FILL IN]` placeholders in the prompts.

### Upload these files with Part 1:
1. `output\stats_report_weekN.md` (single source of truth for all numbers)
2. `templates\newsletter_template.md` (structure, formatting, extraction schemas)
3. `config\LAST_WEEK_RECAP.md` (narrative continuity)
4. `config\RECENT_CONTENT.json` (avoid repeated headlines/phrases)
5. `config\INJURY_OVERRIDES.json` (injury timelines)
6. `data\weeklycontextinput_weekN.json` (only if fantasy trades happened)

### The 3 Parts:
| Part | Sections | Notes |
|------|----------|-------|
| Part 1 | 1-4 (Matchup Summaries, Report Cards, POTW, Betting Lines) | Includes storylines and manager table |
| Part 2 | 5-8 (Fun Facts, Power Rankings, Stats Corner, What If) | Specifies table counts (2 for PR, 9 for SC) |
| Part 3 | 9-10 (Around the NBA, Rumor Mill) + closing | Includes trade block (if applicable), rosters, web search |

### How it works:
- The **prompts** provide week-specific context (storylines, trade details, rosters)
- The **template** provides permanent rules (formatting, extraction workflow, injury glossary, trade grading)
- The prompts say "Read `newsletter_template.md` thoroughly" and defer all rule details to it
- Parts 2 and 3 run in the same chat -- no need to re-upload files

**Output:** Save each part's downloaded file, then combine into `assets\WEEK{N}_DRAFT.md`
---

## Step 8: Verify the Draft (Recommended)

Run this in a **fresh chat** -- not the drafting chat. A chat that just argued
itself into a claim is the worst possible auditor of it.

Upload `assets\WEEK{N}_DRAFT.md`, `output\stats_report_week{N}.md`, and
`templates\VERIFICATION_TEMPLATE.md`, then paste the prompt from that file.
It sorts findings into P0 (factual errors), P1 (template rule violations) and
P2 (format), and ends with a publish/fix verdict.

**What verification catches:**
- Wrong superlatives ("highest score of the season" when it wasn't)
- Misattributed stats (giving one player another's numbers)
- Incorrect injury timelines
- Wrong record references
- Fabricated details not present in the stats report

---

## Step 9: Generate HTML Newsletter

```cmd
python scripts\newsletter_html_generator.py --input assets\WEEKN_DRAFT.md --output output\WEEKN_NEWSLETTER.html --helmet assets\helmet.png --potw assets\potw.png --podium assets\podium.png --stats-report output\stats_report_weekN.json
```

**What's new:** The `--stats-report` flag loads the JSON stats report and injects interactive Stats Corner visualizations (Positional Breakdown, Draft Value Tracker, Waiver ROI, Keeper Watch) into Section 8. If omitted, the newsletter renders normally without visualizations.

**Output:** A single self-contained HTML file with embedded images, visualizations, professional styling, and responsive design. Ready to distribute!

---

## Step 10: Update the Reporter's Notebook

After the newsletter is finalized and distributed, update two files so the next week's drafting session has narrative continuity and freshness:

### 10a: Update LAST_WEEK_RECAP.md

**What to include:**

1. **Week N Results** -> Final scores, margins, updated standings
2. **Key Storylines Covered** -> The 3-5 major narrative beats from this week's newsletter
3. **Running Threads to Continue** -> Ongoing storylines that should carry forward (streaks, milestone chases, injury watches, trade fallout)
4. **Callbacks Planted** -> Things you said in the "Looking Ahead" or "Betting Lines" section that should be followed up on next week (predictions, projected returns, etc.)
5. **Report Card Grades** -> This week's grades for easy reference
6. **Tone & Recurring Bits** -> Any running jokes, nicknames, recurring framing devices, and the POTW history

**How to do it:** The easiest approach is to ask Claude at the end of the drafting session: *"Now update LAST_WEEK_RECAP.md based on the newsletter we just finalized."* Claude will generate the updated file from the draft content.

**Key rule:** Only the most recent week's recap is kept. The file replaces itself each week -> it's a rolling notebook, not an archive.

### 10b: Update RECENT_CONTENT.json

Ask Claude: *"Now update RECENT_CONTENT.json -- append this week's headlines and section openers."*

This prevents future newsletters from reusing the same phrasing or angles. The prompts template instructs the drafting Claude to check this file before writing.

---

## Quick Reference: Complete Command Sequence

```cmd
cd <project_root>

:: Step 0: Fresh NBA schedule
python scripts\fetch_nba_schedule.py --season 2025-26 --output data\nba_schedule_2025-26.json

:: Step 1: Pull Yahoo data (replace dates for your week)
for %d in (YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD YYYY-MM-DD) do python scripts\update_fantasy_logs.py --date %d

:: Step 2: Update league history
python scripts\update_leaguehistory.py --week N

:: Step 2.5: Update PLAYERLIST (paste raw Yahoo data into Claude chat)

:: Step 3: Generate rosters
python scripts\generate_rosters.py --week N --show-diff

:: Step 4: Sync transactions
python scripts\sync_transactions.py --week N --apply

:: Step 5: Manually update config\INJURY_OVERRIDES.json
:: Step 5.5: Optionally create data\weeklycontextinput_weekN.json

:: Step 5.75: Refresh all-time records (Record Book)
python scripts\backfill_player_records.py

:: Step 6: Generate stats report (JSON)
python scripts\generate_stats_report.py --week N

:: Step 6.5: Format stats report (JSON -> Markdown)
python scripts\format_stats_report.py --week N

:: Step 7: Draft newsletter with Claude (open NEWSLETTER_PROMPTS.md, fill in placeholders, run 3 parts in new chat)
:: Step 8: Verify draft with VERIFICATION_TEMPLATE.md

:: Step 9: Generate HTML
python scripts\newsletter_html_generator.py --input assets\WEEKN_DRAFT.md --output output\WEEKN_NEWSLETTER.html --helmet assets\helmet.png --potw assets\potw.png --podium assets\podium.png --stats-report output\stats_report_weekN.json

:: Step 10: Update config\LAST_WEEK_RECAP.md and config\RECENT_CONTENT.json
```

---

## Troubleshooting

**Yahoo OAuth expired:**
Scripts auto-refresh tokens, but if it fails, delete `oauth2.json` and re-authenticate.

**"No lineups found for week N":**
Step 1 hasn't been run yet, or the dates pulled don't match the week in `config\SCHEDULE.json`.

**Stale betting lines / wrong game counts:**
NBA schedule file is outdated. Re-run Step 0.

**Missing players in stats report:**
Check `config\ROSTERS.json` -> make sure Step 4 ran with `--apply` and all waiver moves are reflected.

**"KeyError: 'weekly_scores'" in records:**
`config\RECORDS.json` needs weekly_scores populated. Make sure Step 6 ran and saved to RECORDS.json (don't use `--no-save-records`).

**Player showing on wrong roster after mid-week trade:**
Step 3 unions all players across the week, so a traded player appears on both rosters. Step 4 fixes this by applying the trade transaction.

**Same-day add/drop processed in wrong order:**
Make sure you're using the updated `sync_transactions.py` (Feb 2, 2026 fix) that sorts by Unix timestamp instead of date.

---

## File Reference

| File | Location | Purpose |
|------|----------|---------|
| PLAYERLOG.xlsx | `data\` | Daily fantasy points per player (from Yahoo) |
| LINEUPS.xlsx | `data\` | Daily lineup slots per manager (from Yahoo) |
| LEAGUEHISTORY.xlsx | `data\` | Cumulative weekly totals |
| PLAYERLIST.xlsx | `data\` | ROS projections for top ~125 players |
| nba_schedule_2025-26.json | `data\` | NBA game schedule (from nba.com) |
| waivers_weekN.txt | `data\` | Waiver adds during week N |
| weeklycontextinput_weekN.json | `data\` | Optional storyline context |
| ROSTERS.json | `config\` | Current rosters (source of truth) |
| SCHEDULE.json | `config\` | 21-week fantasy matchup schedule |
| INJURY_OVERRIDES.json | `config\` | Manual multi-week injury tracking |
| RECORDS.json | `config\` | All-time records, standings, streaks |
| RECENT_CONTENT.json | `config\` | Freshness tracker (prevents repeat content) |
| POTW_HISTORY.json | `config\` | Player of the Week history (multi-season, auto-updated by formatter) |
| LAST_WEEK_RECAP.md | `config\` | Reporter's notebook (narrative continuity between newsletters) |
| stats_report_weekN.json | `output\` | Complete analysis (JSON) |
| stats_report_weekN.md | `output\` | Newsletter-ready data (Markdown) |
| WEEKN_NEWSLETTER.html | `output\` | Final HTML newsletter |
| WEEKN_DRAFT.md | `assets\` | Newsletter markdown draft |
| helmet.png | `assets\` | Newsletter header image |
| potw.png | `assets\` | Player of the Week image |
| podium.png | `assets\` | Podium/standings image |
| newsletter_template.md | `templates\` | Newsletter content structure & formatting rules |
| NEWSLETTER_PROMPTS.md | `templates\` | Reusable 3-part drafting prompts (fill in weekly) |
| VERIFICATION_TEMPLATE.md | `templates\` | Draft fact-checking template |
