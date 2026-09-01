# Preseason Runbook -- 2026-27

Getting the project from "2025-26 is over" to "Week 1 newsletter ships on time."

Companion to `SEASON_RESET.md` (what the reset script does) and
`WEEKLY_WORKFLOW.md` (the in-season loop). This file is the sequencing layer:
what order to do things in, and what has to be true before each step.

---

## Calendar Anchors

Confirmed with the league (Sep 1, 2026). These are dates, not estimates.

| Anchor | Date | Days out |
|--------|------|----------|
| **Keeper deadline** | **Sun Oct 4, 2026** | 33 |
| Draft | Sun Oct 11, 2026 | 40 |
| NBA opening night | Tue Oct 20, 2026 | 49 |
| **Week 1 starts** | **Tue Oct 20, 2026** | 49 |
| First newsletter drafted | week of Oct 26 | 55+ |

League: `https://basketball.fantasysports.yahoo.com/nba/16778` (league id `16778`).
Yahoo is configured as a 23-week regular season with no playoffs; all
matchups are set manually.

**The keeper deadline is the real first deadline, not the draft.** On Oct 4
the draft order is set and keepers are imported into the last six rounds.
Choosing keepers well needs `DRAFT_PICK_VALUES.json` rebuilt with 2025-26
included, which needs the historical rollup done first. So Phases 1-3 have to
finish by roughly Sep 27, not by draft day -- managers need time to decide.

Week 1 starts on a **Tuesday** (NBA opening night), so it is likely a short
week. Confirm the exact week boundaries in Yahoo before building SCHEDULE.json;
a 6-day week 1 changes expected games played and every per-game rate stat.

Everything below is scheduled backward from the draft. The hard deadline is not
Week 1 -- it is **draft day**, because `pull_current_draft.py` and the keeper
analysis both need the new league configured and the historical data rebuilt
before the draft happens.

---

## The Roster Rule Change

The league converted its two IL+ slots into two bench slots. The lineup data
pins when: through Week 15 of 2025-26 every manager carried 3 BN + 2 IL +
2 IL+, and from Week 16 (starting 2026-02-02) it was 5 BN + 2 IL with no IL+
rows at all.

Roster stayed at 17. What changed is how many spots you draft into:

| | Through 2025-26 | From 2026-27 |
|---|---|---|
| Roster | 10 starters + 3 BN + 2 IL + 2 IL+ | 10 starters + 5 BN + 2 IL |
| Non-IL spots | 13 | 15 |
| Draft | 13 rounds: 1-7 drafted, 8-13 keepers | **15 rounds: 1-9 drafted, 10-15 keepers** |
| Picks | 52 | **60** (36 drafted, 24 keepers) |

First time the league has drafted more than 7 rounds.

**`config/league_config.json` already reflects this** -- `bench: 5`,
`il_slots: 2`, `total_draft_rounds: 9`, `keepers_per_team: 6`. No edits
needed there. `historical_draft_rounds: 7` stays as-is; it describes past
seasons.

**Three places hardcoded the old boundary and are now fixed** (Aug 28, 2026):

| Where | Was | Impact if left |
|-------|-----|----------------|
| `report_builder.py` Draft Value Tracker | `if round_num >= 8: continue` | Would have dropped 8 of 36 drafted picks from the newsletter every week |
| `build_draft_pick_values.py` regression fit | `if r <= 7` | Would keep ignoring rounds 8-9 once 2026-27 has real results for them |
| `data_loader.ROSTER_SLOTS`, `lineup_optimizer` docstring | old 3 BN / 2 IL+ shape | Wrong reference description of the roster |

All three now split on the `is_keeper` flag rather than a round number, so
the next roster change does not silently break them.
`tests/test_keeper_round_agnostic.py` fails if a hardcoded round boundary
comes back, and if the roster/round arithmetic stops agreeing.

**Two things IL+ still matters for, deliberately left alone:**

- Every season through 2025-26 Week 15 has IL+ rows in its lineup data, so
  `IL_SLOTS`, `SLOT_ELIGIBILITY`, and the bench-slot filters in
  `weekly_stats.py` and `consistency_score.py` must keep handling IL+
- **2025-26 is a split season.** Any comparison of IL games, total injury
  games, or games left on bench that spans the Week 15/16 boundary crosses
  a rule change. Worth remembering when the newsletter makes a
  season-over-season or career superlative claim about injury burden.

---

## Four Deadlines, Not One

Not everything has to be ready by Week 1. Sorting the work by when it is
actually needed makes the schedule far less alarming:

| By | What must work |
|----|----------------|
| **Oct 4** (keepers) | Rollup done; config updated; league key set; DRAFT_PICK_VALUES rebuilt; keeper analysis delivered |
| **Oct 11** (draft) | OAuth verified; SCHEDULE.json weeks 1-15; draft pull ready; DRAFT_PICKS_CURRENT plan settled |
| **Oct 20** (Week 1) | Engine runs clean on empty post-reset state; PLAYERLIST and ROSTERS built; the regular-season / stat-window config split done, since records start accruing immediately |
| **~Week 14** (playoffs approach) | `simulator_playoff_odds.py` reworked for best-of-3 series; cup odds; series tracking in the newsletter |

That last row is the biggest chunk of remaining work and it has the latest
deadline. Playoff odds are meaningless in October -- they matter around the
time the race tightens. Do not let it crowd out the October work.

---

## The 2026-27 Format Change

The league is moving off the 21-week regular season + 2-week single-elim
playoff it has used since 2017-18.

| | Through 2025-26 | From 2026-27 |
|---|---|---|
| Weeks 1-15 | regular season | **regular season** (5 meetings per opponent) |
| Weeks 16-21 | regular season | **playoffs**: semifinals wks 16-18, championship + 3rd-place wks 19-21, all best-of-3 |
| Weeks 22-23 | championship (single elim) | **cup**: 2-week single-elim mini tournament |
| Total | 23 weeks | 23 weeks |

Game 3 of a series is always played, even at 2-0. Cup seeding comes from team
total fantasy points over **weeks 1-21**, which is what stops those dead-rubber
games from being meaningless. The cup pays no money -- the winner keeps an
extra keeper the following season. 2026-27 runs 6 keepers for everyone; from
2027-28 it is 5 per team with the cup winner getting a 6th.

### What this breaks, and when

**1. One config knob is doing two jobs.** `regular_season_weeks` currently
drives both the competitive window (standings, W-L, H2H, seeding) and the
record-keeping window. Those now differ: competition ends at week 15,
record-keeping runs through week 21. Set it to 15 and the record book silently
shrinks to a 15-week window, breaking comparability with nine seasons. Set it
to 21 and playoff series results get absorbed into the regular-season W-L.
The concept has to split in two. **Needed by Week 1** -- records accrue
immediately.

**2. `manager_season_totals` already mixes windows.** Verified on the
2025-26 file: `wins`/`losses` are computed over weeks 1-21 (Nick 17-4 = 21
games) while `total_points` sums weeks 1-23 (Nick 37,562.35 = all 23). Same
object, two windows. That is a bug today, before any format change.

**3. Cup seeding cannot reuse `total_points`.** Seeding is defined as points
over weeks 1-21, but the existing field holds 1-23 -- which includes the cup
itself. Seeding a tournament on a number containing that tournament's results
is circular. It needs its own explicit 1-21 sum.

**4. The H2H tiebreaker needs bounding to week 15.** Five meetings per
opponent is odd on purpose, so a season series always has a winner. But a
semifinal adds three more meetings against the same opponent: 5 + 3 = 8, even,
drawable. The standings tiebreaker must see weeks 1-15 only. The existing
guard keys off `regular_season_weeks`, so this falls out correctly once that
becomes 15 -- but only if the record-keeping window is a separate setting.

**5. The record book keeps a two-tier policy** (verified in the code, not
assumed): standings-shaped records -- W-L, season series, all-time H2H,
streaks -- are regular-season-only. Performance-shaped records -- highest
weekly score, biggest blowout, closest game -- deliberately include playoff
weeks, per an explicit comment in `records_tracker`. Agreed policy going
forward: counting and rate stats move to weeks 1-21 in both eras; peak records
keep all 23 weeks, because excluding 22-23 retroactively would delete nine
seasons of championship performances from the all-time book, and a maximum
over 21 weeks versus 23 is barely biased anyway.

**6. `simulator_playoff_odds.py` models the wrong tournament.** Its docstring
says "the 2-week playoff bracket (semifinals + finals)" with single-week
rounds and a consolation game. It needs best-of-3 series over three weeks per
round, plus a separate cup simulation seeded by total points. ~700 lines, the
largest remaining piece of work -- but not needed until the playoff race
matters, around week 14. `simulator_title_odds.py` models the regular-season
race only, so it just needs the 15-week window. `simulator_betting.py` should
be unaffected: a series game is still a weekly matchup.

**7. Four outcomes per season now**, where there used to be two: regular-season
winner (wks 1-15), champion (19-21), 3rd-place series winner, cup winner
(22-23). `league_config.json` already separates `first_place_finishes` from
`titles` in `pre_data_era`, so there is precedent -- but decide how all four
are recorded before the season, not in March.

**8. All-time H2H will accrue slower.** 15 games per season against 21
historically. Not wrong, but the milestone numbers the fun-facts generator
leans on ("Nick leads Hayden 46-20") will grow at a different pace.

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

## Phase 1 -- Roll 2025-26 Into History (target: Sep 7)

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
   `data\historical\HISTORICAL_PLAYERLOG.json`:

   ```cmd
   py scripts\rollup_season_to_history.py             :: preview
   py scripts\rollup_season_to_history.py --execute
   ```

   Dry-run by default. It derives the four fields PLAYERLOG.xlsx does not
   carry (`season_key`, `slot` from LINEUPS, `had_game`, `player_id`), drops
   the three workflow-only columns, backs up before writing, and re-reads the
   file afterward to verify row count and schema. It refuses to append a
   season already in the record, so a double-run cannot duplicate rows.

   **Read its report before passing `--execute`.** On the 2025-26 data it
   flags one row with no LINEUPS match (De'Aaron Fox, 2025-11-05), 23 players
   new to the record, and one name correction -- `Lebron James` -> `LeBron
   James`, a single misspelled row that would otherwise have appended as a
   separate player and split LeBron's career totals across two names.

**Can happen AFTER the config bump** (pulled fresh from Yahoo):

3. `all_standings.json`, `all_matchups.json`, `all_drafts.json`,
   `all_trades.json` -- see Phase 3.

### Then run the reset

```cmd
py scripts\start_new_season.py                    :: dry run -- read the plan
py scripts\start_new_season.py --execute
py scripts\verify_project_integrity.py
```

### Gaps in the reset script  [FIXED Aug 28, 2026]

`start_new_season.py` used to leave three per-season files untouched, so
2025-26 state would have leaked into the new season. All three are now
archived in Phase 1 and reset in Phase 2:

| File | Why it mattered |
|------|-----------------|
| `config\DRAFT_PICKS_CURRENT.json` | All 52 of last season's picks and keeper flags, read by `report_builder` and `player_card_builder` all season |
| `config\LAST_WEEK_RECAP.md` | Final-week recap fed to the drafting chat as narrative context -- would have seeded Week 1 with dead storylines |
| `config\.leaguehistory_applied_weeks.json` | Applied-weeks ledger; stale entries can make `update_leaguehistory.py` skip weeks |

`tests/test_start_new_season.py` guards this now: one test fails if a
per-season `config/` file is missing from the archive list, another fails if
any file in `config/` is unclassified -- so the next file added mid-season
forces a decision instead of being silently forgotten.

**One thing the script cannot fix:** nothing writes
`config\DRAFT_PICKS_CURRENT.json`. `pull_current_draft.py` patches
`all_drafts.json` only. After the draft, rebuild it by hand with the
`is_keeper` flags -- the reset's manual checklist now says so explicitly, and
Phase 5 below covers it.

---

## Phase 2 -- Stand Up the New League (target: Sep 14)

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
| `league_structure` | **No change needed** -- already correct for the 15-round draft (see The Roster Rule Change above) |
| `yahoo.current_league_key` | New 2026-27 key |
| `yahoo.historical_league_keys` | Add `"2026-27": "<new key>"` (2025-26 is already listed) |
| `manager_to_team` | Update any renamed teams |
| `manager_colors` | Only if the roster of managers changes |

Then: `py scripts\verify_project_integrity.py` -- check 4 validates this schema.

### 2.2 Get the league key, and prove OAuth still works

```cmd
py scripts\get_league_key.py --league-id 16778 --season 2026
```

One call. It authenticates, prints the NBA `game_id` for the season, lists
your leagues, and hands back the exact `<game_id>.l.16778` string to paste
into `league_config.json`. The `game_id` is not guessable -- it has run 380,
390, 402, 411, 418, 428, 438, 451, 466 across nine seasons, in jumps of 7 to
15.

It is also the cheapest possible live Yahoo call, so it doubles as the OAuth
health check. `oauth2.json` was last touched in June; tokens go stale over an
offseason. Run this now, at a browser, rather than discovering the problem on
draft night with 60 picks waiting.

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

## Phase 3 -- Rebuild Derived Data (target: Sep 20)

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

Caveat worth carrying into draft night: **rounds 8 and 9 have never existed.**
Their pick values are cliff-decay extrapolations from the round-7 average, not
observed results, because no keeper-era season drafted past round 7. Treat the
grades on picks 29-36 as modeled rather than measured until 2026-27 is in the
books. (Once it is, the regression will pick them up automatically -- that is
what the `is_keeper` fix bought.)

---

## Phase 4 -- Keeper + Draft Prep (Sep 21 - Oct 10)

### 4.1 Keeper analysis

Six keepers per team, keepers occupy rounds 8-13. `modules/keepability_v2.py`
plus refreshed `DRAFT_PICK_VALUES.json` is the tooling. Deliver keeper
recommendations to the league **before whatever the keeper deadline is** --
that date is not recorded anywhere in the repo. Find it and write it here.

### 4.2 Verification template  [DONE Aug 28, 2026]

`templates\VERIFICATION_TEMPLATE.md` was referenced by `WEEKLY_WORKFLOW.md`
Step 8 and by its File Reference table, but did not exist. Rebuilt as a
three-tier audit (P0 factual errors, P1 template-rule violations, P2 format)
keyed to the CRITICAL RULES in `newsletter_template.md`, with a
section-by-section sweep. Run it in a fresh chat -- the drafting chat cannot
audit itself.

Still open: `templates\NEWSLETTER_PROMPTS_WEEK18-21.md` are 2025-26 one-offs
the reset script does not touch. Archive or delete them when convenient.

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

## Phase 5 -- Draft Day (Oct 11) and the week after

Immediately after the draft completes:

```cmd
py scripts\pull_current_draft.py --dry-run
py scripts\pull_current_draft.py
py scripts\generate_rosters.py
```

Then:

- Verify `config\DRAFT_PICKS_CURRENT.json` has **60 picks** (15 rounds x 4
  teams) with real player names, and `is_keeper` set true for rounds 10-15.
  The engine now trusts that flag rather than inferring from the round number,
  so getting it right matters more than it used to.
- Verify `config\ROSTERS.json` has 4 teams x 17 players
- Update `data\PLAYERLIST.xlsx` for the new season (`WEEKLY_WORKFLOW.md` Step 2.5)
- Reset `config\TRADES.json` `draft_pick_ownership` for 2027-28 picks if your
  league trades future picks

---

## Phase 6 -- Week 1 (starts Tue Oct 20)

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
   genuinely irreversible step in the whole sequence. Now scripted
   (`rollup_season_to_history.py`) with a dry run, a backup and a post-write
   verify; the LEAGUEHISTORY.xlsx update is still manual. The historical files
   are committed to git as of Phase 0, so a bad rollup is recoverable with
   `git checkout` -- commit before and after the append.
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
