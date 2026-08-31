# Season Reset Runbook

How to close out a completed season and prepare the project for the next one.

---

## File Categories

Every file in the project falls into one of five lifecycle categories:

1. **Engine code** — Python modules and scripts. Never changes between seasons.
2. **League identity** — `config/league_config.json`. Set once when the league is created; only the season block and Yahoo keys change year-to-year.
3. **Per-season inputs** — `ROSTERS.json`, `TRADES.json`, `SCHEDULE.json`, `INJURY_OVERRIDES.json`, `PLAYERLOG.xlsx`, `LINEUPS.xlsx`, waiver files. Built up during the season, reset at the end.
4. **Per-season outputs** — Stats reports, newsletter HTML, newsletter drafts, snapshots, `RECENT_CONTENT.json`, `POTW_HISTORY.json`, `RECORDS.json` (current-season portion). Generated weekly, disposable once archived.
5. **Historical** — `data/historical/` (all_drafts, all_matchups, all_standings, etc.) and `LEAGUEHISTORY.xlsx`. Append-only, never reset.

---

## When to Run

Run the season reset **after**:

- The season is fully complete (all playoff weeks finished)
- You have rolled the season's data into the permanent historical record (`data/historical/`)
- You have updated `LEAGUEHISTORY.xlsx` with final standings and titles

Do **not** run it mid-season or before historical rollup is done — the archive is your safety net, not a substitute for proper historical record-keeping.

## Integrity Check (run after reset)

After the season reset script finishes, always run the project integrity checker to confirm nothing was corrupted, truncated, or left in a broken state:

```
py scripts/verify_project_integrity.py
```

If anything has changed structurally (modules were intentionally added/removed, files intentionally rewritten), refresh the size baseline once you've manually verified the new state is correct:

```
py scripts/verify_project_integrity.py --baseline
```

See `WEEKLY_WORKFLOW.md` for full details on what this script checks.

---

## How to Run

### Step 1: Dry-run (preview the plan)

```
py scripts/start_new_season.py
```

This prints exactly what would be archived, reset, and deleted — without touching any files. Review the output carefully.

### Step 2: Execute

```
py scripts/start_new_season.py --execute
```

If the archive folder `archive/<season>/` already exists (e.g. from a previous run), the script will refuse to proceed. Use `--force` to overwrite:

```
py scripts/start_new_season.py --execute --force
```

---

## What the Script Does

### Phase 1: Archive

Copies the following into `archive/<season>/`, preserving subfolder structure:

- `output/stats_report_week*.json` and `.md`
- `output/looking_ahead_week*.json`
- `output/*.html` (newsletter HTML)
- `assets/WEEK*_DRAFT.md`
- `config/snapshots/*`
- `data/waivers_week*.txt`
- `config/POTW_HISTORY.json`, `RECENT_CONTENT.json`, `ROSTERS.json`, `TRADES.json`, `INJURY_OVERRIDES.json`, `RECORDS.json`
- `config/DRAFT_PICKS_CURRENT.json`, `LAST_WEEK_RECAP.md`, `.leaguehistory_applied_weeks.json`
- `config/league_config.json` (snapshot — original is not modified)
- `data/LEAGUEHISTORY.xlsx` (snapshot — original is not modified)
- `data/PLAYERLOG.xlsx`, `data/LINEUPS.xlsx`, `data/PLAYERLIST.xlsx` (full season data — archived before Phase 2 wipes them)

After copying, every file is verified (existence + matching size). If any copy fails, the script aborts before making any changes.

### Phase 2: Reset

Resets per-season working files to empty defaults matching their existing schema:

- `config/RECENT_CONTENT.json` → empty `{fun_facts: {}, trade_ideas: {}, free_agent_recs: {}}`
- `config/POTW_HISTORY.json` → empty `{seasons: {}}`
- `config/INJURY_OVERRIDES.json` → empty `{players: [], last_updated: ""}`
- `config/ROSTERS.json` → empty `{rosters: {}}`
- `config/TRADES.json` → empty `{trades: [], draft_pick_ownership: {}}`
- `config/RECORDS.json` → preserves `all_time` and `team_name_history`, resets all current-season sections to empty. Unknown keys are preserved with a warning.
- `config/DRAFT_PICKS_CURRENT.json` → empty `{season: "", league_key: "", picks: []}`
- `config/LAST_WEEK_RECAP.md` → empty placeholder (no stale storylines)
- `config/.leaguehistory_applied_weeks.json` → empty `{}` (skipped if absent)
- `data/PLAYERLOG.xlsx` → header row only (0 data rows)
- `data/LINEUPS.xlsx` → header row only (0 data rows)

### Phase 3: Delete

Removes the now-archived output files from working directories:

- `output/stats_report_week*`, `output/looking_ahead_week*`, `output/*.html`
- `assets/WEEK*_DRAFT.md`
- `config/snapshots/*`
- `data/waivers_week*.txt`

---

## What the Script Does NOT Do

The following require manual action. The script prints this checklist at the end of every run.

### BEFORE running with `--execute` (data-loss prevention)

Phase 2 truncates `PLAYERLOG.xlsx` and `LINEUPS.xlsx` to header-only. The archive copies them, but the *permanent* historical record lives elsewhere and must be updated by hand first:

1. **Roll into permanent history:**
   - Append PLAYERLOG data to `data/historical/HISTORICAL_PLAYERLOG.json`:
     ```
     py scripts/rollup_season_to_history.py             # preview
     py scripts/rollup_season_to_history.py --execute
     ```
     Dry-run by default; backs up, verifies, and refuses to append a season
     that is already present.
   - Append final standings to `data/historical/all_standings.json`
   - Update `data/LEAGUEHISTORY.xlsx` with final records/titles

### AFTER the reset

2. **Edit `config/league_config.json`:**
   - `season.current`, `season.current_long`, `season.season_number`
   - `yahoo.current_league_key` (new Yahoo league ID)
   - `yahoo.historical_league_keys` (add the archived season)
   - `season.nba_schedule_file` (new filename)
   - `manager_to_team` (if any team names changed)

3. **Fetch the new NBA schedule:**
   ```
   py scripts/fetch_nba_schedule.py --season <new> --output data/nba_schedule_<new>.json
   ```

4. **Create `config/SCHEDULE.json`** for the new season (matchups and dates)

5. **Run the draft pull** once the draft happens:
   ```
   py scripts/pull_current_draft.py
   ```

6. **Rebuild `config/DRAFT_PICKS_CURRENT.json` by hand.** Nothing writes this
   file — `pull_current_draft.py` patches `data/historical/all_drafts.json`
   only. Phase 2 emptied it, so recreate it from the Yahoo draft results,
   including the `is_keeper` flag (2025-26: rounds 1-7 drafted, 8-13 keepers).
   `report_builder.py` and `player_card_builder.py` read it all season; an
   empty file degrades gracefully but silently loses the Draft Value Tracker.

---

## Where to Find Archived Seasons

All archived seasons live in `archive/<season>/`, e.g.:

```
archive/
  2025-26/
    config/
      POTW_HISTORY.json
      RECENT_CONTENT.json
      RECORDS.json
      ROSTERS.json
      TRADES.json
      INJURY_OVERRIDES.json
      league_config.json
      snapshots/
        ...
    output/
      stats_report_week16.json
      ...
    assets/
      WEEK16_DRAFT.md
      ...
    data/
      waivers_week1.txt
      ...
      LEAGUEHISTORY.xlsx
```

The archive is a complete snapshot of everything the season produced. The original `config/league_config.json` and `data/LEAGUEHISTORY.xlsx` are never modified by the script — only snapshot copies are placed in the archive.
