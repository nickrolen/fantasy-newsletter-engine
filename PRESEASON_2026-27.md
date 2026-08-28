# Preseason Runbook -- 2026-27

Getting the project from "2025-26 is over" to "Week 1 newsletter ships on time."

Companion to `SEASON_RESET.md` (what the reset script does) and
`WEEKLY_WORKFLOW.md` (the in-season loop). This file is the sequencing layer:
what order to do things in, and what has to be true before each step.

---

## Calendar Anchors

| Anchor | Date | Source |
|--------|------|--------|
| Plan written | Fri Aug 28, 2026 | -- |
| Draft | ~Fri Oct 16, 2026 | **CONFIRM** -- "7 weeks out" as of Aug 28 |
| NBA opening night | Tue Oct 20, 2026 | NBA.com schedule release |
| Fantasy Week 1 | Mon Oct 19 -- Sun Oct 25, 2026 | **CONFIRM in Yahoo.** Mirrors 2025-26, where Week 1 was Mon Oct 20 with opening night Tue Oct 21 |
| First newsletter drafted | Week of Mon Oct 26, 2026 | Week 1 workflow runs after Week 1 closes |
| NBA regular season ends | Sun Apr 11, 2027 | NBA.com |

Everything below is scheduled backward from the draft. The hard deadline is not
Week 1 -- it is **draft day**, because `pull_current_draft.py` and the keeper
analysis both need the new league configured and the historical data rebuilt
before the draft happens.

---

## Current State (as of Aug 28, 2026)

Verified against the working tree:

- [x] 2025-26 season is complete -- outputs run through Week 23 (playoffs end at Week 23 per `league_config.json`)
- [x] Phase 0 housekeeping done -- see below
- [ ] **2025-26 is NOT in the historical record.** `all_standings.json`, `all_matchups.json`, `all_drafts.json`, `all_trades.json`, and `HISTORICAL_PLAYERLOG.json` all stop at **2024-25**. *This is by design* -- the current season is deliberately kept out of the historical files and rolled in between seasons. That roll-in is Phase 1.
- [ ] Season reset has not been run -- no `archive/` folder; `output/`, `config/snapshots/`, `data/waivers_week*.txt` still hold 2025-26 artifacts
- [ ] `league_config.json` still says `season.current = "2025-26"`

Nothing here is broken. It is just a season that was never formally closed out.

---

## Phase 0 -- Clear the Decks  [DONE Aug 28, 2026]

Done before anything else, so later checks are trustworthy.

**What was done:**

- Cleared a stale `.git/index.lock` that was blocking all git writes
- Deleted build cruft: `__pycache__` (root/modules/scripts, holding stale
  `.pyc` for both Python 3.10 and 3.14), `.pytest_cache`, an empty stray
  `pytest-cache-files-*` dir, and `_backups/` (7 module copies git already has)
- Deleted `data/historical/HISTORICAL_PLAYERLOG_BACKUP.json` (25MB stale
  pre-enrichment copy; `enrich_historical_playerlog.py` regenerates it)
- **Un-ignored `data/historical/*.json` and committed it.** Nine seasons of
  records now have offsite, versioned backup instead of living on one disk
- Fixed two stale `.gitignore` comments and added pytest cache patterns
- Rebuilt the integrity baseline from a clean tree

**Result:** 74MB -> 48MB on disk. Integrity check 6/6 including golden master,
0 warnings / 0 failures. 59 tests pass. Working tree clean.

The original instructions are kept below for next season.

---

### 0.1 Refresh the integrity baseline

```cmd
py scripts\verify_project_integrity.py
```

Expect 9 `DISAPPEARED since baseline` failures, all under `_recovery/`. That
folder was deliberately removed, so the baseline is stale, not the tree.
Confirm every failure is a `_recovery/` path, then:

```cmd
py scripts\verify_project_integrity.py --baseline
py scripts\verify_project_integrity.py
```

Second run should exit 0. **Do not skip this** -- a noisy baseline means you
cannot tell real truncation from old noise during the reset, which is exactly
when truncation is most likely.

### 0.2 Commit the working tree

```cmd
git status
git add data\backtest\backtest_summary.json
git commit -m "Track backtest summary output"
```

### 0.3 Tag the end of the season

A tag is a free rollback point before any destructive step:

```cmd
git tag season-2025-26-final
```

### 0.4 Run the test suite

```cmd
py -m pytest tests\ -q
```

All green before you start changing season state.

---

## Phase 1 -- Roll 2025-26 Into History (Sep 7 - Sep 11)

**This is the highest-risk phase and the one with the least tooling.** Phase 2
truncates `PLAYERLOG.xlsx` and `LINEUPS.xlsx` to header rows. The archive keeps
a copy, but the permanent record has to be written by hand first.

### Ordering trap -- read this before following SEASON_RESET.md literally

`SEASON_RESET.md` says to append final standings to `all_standings.json` before
the reset, and to edit `league_config.json` after it. Those two instructions
conflict for the Yahoo-sourced files:

`scripts/pull_historical_data.py` builds `LEAGUE_KEYS` by **excluding**
`CURRENT_SEASON`. While `season.current` is still `"2025-26"`, the script cannot
see 2025-26 at all -- `--season 2025-26` will fail with
`Season 2025-26 not found in LEAGUE_KEYS`.

So split the rollup in two:

**Must happen BEFORE the reset** (depends on files the reset wipes):

1. Update `data\LEAGUEHISTORY.xlsx` with final 2025-26 records and titles
   ```cmd
   py scripts\update_leaguehistory.py --week 23
   ```
   Confirm weeks 1-23 are all applied. `update_leaguehistory.py` keeps a ledger
   at `config\.leaguehistory_applied_weeks.json` -- that file does not currently
   exist, so verify the season's weeks are actually in the workbook rather than
   trusting the ledger.

2. Append 2025-26 rows from `data\PLAYERLOG.xlsx` into
   `data\historical\HISTORICAL_PLAYERLOG.json`.
   **There is no script for this.** Every script that touches that file only
   reads it (`build_rookie_seasons.py`, `backfill_player_records.py`,
   `extract_draft_fppg.py`); `enrich_historical_playerlog.py` overwrites it.
   Match the existing schema exactly:
   `season_year, season_key, week, date, manager, fantasy_team, player_name,`
   `player_id, positions, slot, fantasy_points, started, ...`
   Back up `HISTORICAL_PLAYERLOG.json` first, then verify the row count grew by
   the number of 2025-26 rows and that `2025-26` appears in the season keys.

**Can happen AFTER the config bump** (pulled fresh from Yahoo):

3. `all_standings.json`, `all_matchups.json`, `all_drafts.json`,
   `all_trades.json` -- see Phase 3.

### Then run the reset

```cmd
py scripts\start_new_season.py                    :: dry run -- read the plan
py scripts\start_new_season.py --execute
py scripts\verify_project_integrity.py
```

### Known gaps in the reset script

`start_new_season.py` does not archive or reset these, so 2025-26 state leaks
into the new season unless you handle them by hand:

| File | Why it matters | Action |
|------|----------------|--------|
| `config\DRAFT_PICKS_CURRENT.json` | Holds all 36 of last year's picks. Its own `_comment` says it merges into `all_drafts.json` at season end | Copy to `archive\2025-26\config\`, then let `pull_current_draft.py` overwrite it after the new draft |
| `config\LAST_WEEK_RECAP.md` | Week 23 recap; feeds the Reporter's Notebook | Copy to archive, then blank it |
| `config\.leaguehistory_applied_weeks.json` | Applied-weeks ledger, if it exists by then | Delete or reset to `{}` so new-season weeks apply cleanly |

Worth patching into the script itself so next year is one command.

---

## Phase 2 -- Stand Up the New League (Sep 14 - Sep 18)

Blocked on the Yahoo league for 2026-27 actually existing. Create/renew it
first, then grab the league key.

### 2.1 `config\league_config.json`

| Key | New value |
|-----|-----------|
| `season.current` | `"2026-27"` |
| `season.current_long` | `"2026-2027"` |
| `season.season_number` | `10` |
| `season.nba_schedule_file` | `"data/nba_schedule_2026-27.json"` |
| `season.regular_season_weeks` / `playoff_start_week` / `total_weeks` | Re-derive from the Yahoo schedule -- 2025-26 was 21 / 22 / 23 |
| `yahoo.current_league_key` | New 2026-27 key |
| `yahoo.historical_league_keys` | Add `"2026-27": "<new key>"` (2025-26 is already listed) |
| `manager_to_team` | Update any renamed teams |
| `manager_colors` | Only if the roster of managers changes |

Then: `py scripts\verify_project_integrity.py` -- check 4 validates this schema.

### 2.2 Re-auth Yahoo

`oauth2.json` was last touched in June. Tokens go stale over an offseason.
Re-run any Yahoo script early enough to hit the browser consent flow calmly --
**not** on draft night.

### 2.3 Fetch the NBA schedule

```cmd
py scripts\fetch_nba_schedule.py --season 2026-27 --output data\nba_schedule_2026-27.json
```

The 2026-27 schedule is already published, so this should work now. Fallback if
`cdn.nba.com` is down is documented in `WEEKLY_WORKFLOW.md` Step 0.

### 2.4 Build `config\SCHEDULE.json`

Same shape as the 2025-26 file: `season_year`, `total_weeks`,
`regular_season_weeks`, `playoff_start_week`, `managers`, then a `weeks` array
of `{week, start_date, end_date, days, matchups}`. Week 1 is expected to be
**Mon 2026-10-19 - Sun 2026-10-25** -- confirm against Yahoo before committing,
since every weekly run reads its dates from here.

---

## Phase 3 -- Rebuild Derived Data (Sep 21 - Sep 25)

Now that `season.current` is `2026-27`, 2025-26 is visible to the historical
puller.

```cmd
py scripts\pull_historical_data.py --season 2025-26
py scripts\backfill_draft_names.py --season 2025-26
```

Verify 2025-26 now appears in the season keys of `all_standings.json`,
`all_matchups.json`, `all_drafts.json`, and `all_trades.json`.

Then rebuild everything downstream of a new season of history:

```cmd
py scripts\build_rookie_seasons.py --update      :: adds the 2026-27 rookie class
py scripts\extract_draft_fppg.py                 :: refresh draft-value inputs
py scripts\build_draft_pick_values.py            :: re-fit with 2025-26 included
py scripts\backfill_player_records.py            :: refresh all-time record book
```

`DRAFT_PICK_VALUES.json` currently says it was built from "131 qualifying data
points across 5 keeper-era seasons" -- adding 2025-26 makes it 6, which is the
single biggest accuracy improvement available before the draft.

---

## Phase 4 -- Draft Prep (Sep 28 - Oct 15)

### 4.1 Keeper analysis

Six keepers per team, keepers occupy rounds 8-13. `modules/keepability_v2.py`
plus refreshed `DRAFT_PICK_VALUES.json` is the tooling. Deliver keeper
recommendations to the league **before whatever the keeper deadline is** --
that date is not recorded anywhere in the repo. Find it and write it here.

### 4.2 Restore the missing verification template

`WEEKLY_WORKFLOW.md` Step 8 says to verify the draft with
`VERIFICATION_TEMPLATE.md`. **That file does not exist anywhere in the repo.**
`templates\NEWSLETTER_PROMPTS.md` is present and fine; the verification
template is simply gone. Either rebuild it or cut Step 8 from the workflow --
discovering this in Week 1 is worse than discovering it now.

While you are in `templates\`: `NEWSLETTER_PROMPTS_WEEK18-21.md` are
2025-26 one-offs the reset script does not touch. Archive them or delete them.

### 4.3 Preseason newsletter (optional but the obvious win)

Everything needed already exists: nine seasons of history, a refreshed record
book, keeper values, draft pick values. A preview issue is the same pipeline
with no weekly stats. Decide now whether you want one, because it needs to be
drafted before draft day to be worth anything.

### 4.4 Dry-run the engine

Before draft day, confirm the pipeline survives empty per-season files.
Expect graceful gaps where 2026-27 data does not exist yet; what you are
hunting for is *crashes* on empty `ROSTERS.json`, empty `RECENT_CONTENT.json`,
and a header-only `PLAYERLOG.xlsx`.

```cmd
py check_all.py                                        :: syntax sweep only
py scripts\generate_stats_report.py --week 1 --fast --dry-run
```

`check_all.py` just AST-parses every `.py` file -- it proves nothing about
runtime behavior. The `generate_stats_report.py` dry run is the real test.
Fix anything that hard-fails on empty state now, not in the 24 hours after the
draft.

---

## Phase 5 -- Draft Week (Oct 16 - Oct 18)

Immediately after the draft completes:

```cmd
py scripts\pull_current_draft.py --dry-run
py scripts\pull_current_draft.py
py scripts\generate_rosters.py
```

Then:

- Verify `config\DRAFT_PICKS_CURRENT.json` has all picks with real player names
  and correct `is_keeper` flags for rounds 8-13
- Verify `config\ROSTERS.json` has 4 teams x 17 players
- Update `data\PLAYERLIST.xlsx` for the new season (`WEEKLY_WORKFLOW.md` Step 2.5)
- Reset `config\TRADES.json` `draft_pick_ownership` for 2027-28 picks if your
  league trades future picks

---

## Phase 6 -- Week 1 (Oct 19 - Oct 25, live)

Week 1 runs Mon Oct 19 through Sun Oct 25. The newsletter is produced the
following week, from `WEEKLY_WORKFLOW.md` as normal:

```cmd
py scripts\verify_project_integrity.py
py scripts\fetch_nba_schedule.py --season 2026-27 --output data\nba_schedule_2026-27.json
for %d in (2026-10-19 2026-10-20 2026-10-21 2026-10-22 2026-10-23 2026-10-24 2026-10-25) do py scripts\update_fantasy_logs.py --date %d
py scripts\update_leaguehistory.py --week 1
py scripts\generate_rosters.py
py scripts\sync_transactions.py --week 1 --apply
py scripts\generate_stats_report.py --week 1
py scripts\format_stats_report.py --week 1
py scripts\newsletter_html_generator.py --input assets\WEEK1_DRAFT.md --output output\WEEK1_NEWSLETTER.html --helmet assets\helmet.png --potw assets\potw.png --podium assets\podium.png --stats-report output\stats_report_week1.json
```

(Steps 5, 5.5, 7 and 8 of `WEEKLY_WORKFLOW.md` -- injury overrides, weekly
context, the Claude drafting session, and verification -- sit between
`format_stats_report.py` and the HTML generator, same as any other week.)

Week 1 caveats the engine will hit:

- **No prior-week comparisons.** Anything keyed off last week's report is empty
- **Projections have no current-season sample** -- they lean entirely on
  historical and preseason inputs
- **Records/streaks start cold** after the RECORDS.json current-season reset
- **Betting-line backtest** restarts its published-lines dataset
- `config\LAST_WEEK_RECAP.md` will be blank -- expected

Watch these in the Week 1 draft rather than assuming a bug.

---

## Critical Path

Everything else can slip. These cannot:

1. **LEAGUEHISTORY + HISTORICAL_PLAYERLOG rollup before the reset** -- the only
   genuinely irreversible step in the whole sequence. (As of Phase 0 the
   historical files are committed to git, so a bad rollup is now recoverable
   with `git checkout` -- commit before and after the append.)
2. **Yahoo league created + league key in config** -- blocks all of Phase 3
3. **Yahoo OAuth working** -- blocks the draft pull on draft night
4. **`SCHEDULE.json` for 2026-27** -- blocks every weekly run
5. **Draft pull within a day of the draft** -- Yahoo draft results are easiest
   to pull clean before roster churn starts

---

## Open Questions

- [ ] Exact draft date and time
- [ ] Keeper declaration deadline
- [ ] Is the 2026-27 Yahoo league created yet? What is its league key?
- [ ] Any manager or team-name changes for 2026-27?
- [ ] Confirm Yahoo Week 1 dates (assumed Mon Oct 19 - Sun Oct 25)
- [ ] Is the league still 4 teams / 21 regular-season weeks / 23 total?
- [ ] Do you want a preseason preview issue?
