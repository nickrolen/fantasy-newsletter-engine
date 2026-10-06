# Project Map

---

## 1. The shape of the thing

Python assembles data. A human-run LLM chat writes prose. A Python script
renders the result to HTML.

**No LLM is called anywhere in this repository.** Nothing imports an API
client, nothing holds a model key. Step 7 of the weekly workflow is a person
uploading files into a chat window and pasting the answer back. Any sentence
in the newsletter was written in that chat, following
`templates/newsletter_template.md`.

That boundary matters: everything upstream of Step 7 is deterministic and
testable, and everything at Step 7 is not.

---

## 2. The weekly chain

In `WEEKLY_WORKFLOW.md` order. Each step's real inputs and outputs:

| Step | Script | Reads | Writes |
|---|---|---|---|
| 0a | `verify_project_integrity.py` | everything | nothing |
| 0 | `fetch_nba_schedule.py` | basketball-reference (cdn.nba.com 403s) | the file `league_config.season.nba_schedule_file` names |
| 1 | `update_fantasy_logs.py --date D` | Yahoo API, once per day | appends `LINEUPS.xlsx`, `PLAYERLOG.xlsx` |
| 2 | `update_leaguehistory.py --week N` | the two logs | `LEAGUEHISTORY.xlsx` |
| 2.5 | `fetch_playerlist.py --execute` | Yahoo **website** HTML | `PLAYERLIST.xlsx`, `PLAYER_AGES.json` |
| 2.5 | `check_playerlist.py --snapshot` | the above | a snapshot; **gate, do not skip** |
| 3 | `generate_rosters.py --week N` | `LINEUPS.xlsx` | `ROSTERS.json` |
| 4 | `sync_transactions.py --week N --apply` | Yahoo transactions | `waivers_weekN.txt`, patches `ROSTERS.json` |
| 5 | by hand | - | `INJURY_OVERRIDES.json`, optional `weeklycontextinput_weekN.json` |
| 5.75 | `backfill_player_records.py` | historical JSON, logs | `RECORDS.json["all_time"]` |
| 6 | `generate_stats_report.py --week N` | nearly everything | `stats_report_weekN.json`, `RECORDS.json`, `RECENT_CONTENT.json`, `snapshots/point_in_time/report_weekNN/` |
| 6.5 | `format_stats_report.py --week N` | the JSON + 5 more sources | `stats_report_weekN.md` (~650 lines) |
| 7 | **a human in an LLM chat** | the .md + template + recaps | `assets/WEEKN_DRAFT.md` |
| 8 | optional LLM verification | `VERIFICATION_TEMPLATE.md` | - |
| 9 | `newsletter_html_generator.py` | the draft + the JSON | `output/WEEKN_NEWSLETTER.html` |
| 10 | by hand | - | rewrites `LAST_WEEK_RECAP.md` |

Two useful flags on Step 6: `--fast` skips the Monte Carlo simulators **and**
the live injury fetch, which empties `power_rankings` and `looking_ahead` and
makes every manager look like a title contender to the Rumor Mill. `--repro`
re-runs a week without mutating the freshness tracker.

---

## 3. The ten sections: who writes what

Every section's **numbers** are computed in Python. Every section's **prose**
is written by the LLM at Step 7. The split per section:

| # | Section | Computed | Written |
|---|---|---|---|
| 1 | Matchup Summaries | scores, series, H2H, positional FP, best/worst | 3-4 paragraphs |
| 2 | Report Cards | **the grade itself**, by fixed formula | 6-8 sentences of justification |
| 3 | Betting Lines | lines, odds, win probs, key players | 4-6 sentence preview |
| 4 | Player of the Week | **the winner**, by tiered rules | 5-7 sentences |
| 5 | Fun Facts | **candidates, scoring and selection** | rewrite in voice, numbers exact |
| 6 | What If | bench swaps, blunders, notable swaps | bullets + summary |
| 7 | Power Rankings | ranks, odds, trend (80% odds / 20% keeper quality) | 3-4 paragraphs |
| 8 | Stats Corner | 8 required tables | 3-4 sentences |
| 9 | Around the NBA | league context only | headlines, news, **trade grades** |
| 10 | Rumor Mill | **trades, FA targets, streaks, drops** | rewrite each bullet |

The LLM does not choose the Report Card grade, the POTW winner, which fun
facts appear, or which trades are proposed. It chooses words.

`format_stats_report.compute_storyline_alerts` also precomputes narrative
flags -- UPSET, RECORD WATCH, BLOWOUT, STREAK SNAPPED, CLINCH WATCH -- into a
"READ FIRST" block. That is the closest thing to automated story selection
that exists today.

---

## 4. Modules that make judgments

These are the ones that decide something, as opposed to totalling something.

- **`luck_index.py`** -- `actual_wins` vs all-play `expected_wins`; a rating
  from Very Lucky to Very Unlucky. This is the only module that separates
  misfortune from misjudgement.
- **`consistency_score.py`** -- CV of weekly FPPG, rated Rock Solid to
  Boom-or-Bust. **Needs 4 weeks**; before that every manager reads 0.0 and
  sorts as most consistent.
- **`schedule_strength.py`** -- `startable_games` via a greedy daily lineup
  simulation, which is the real "schedule edge" number. Also, per day: the
  open slots left, how many a healthy free agent with a game could fill
  (exact matching), and a streamer board: top free agents by projected points
  added, scored against every roster.
- **`lineup_fill.py`** -- the one exact daily lineup fill (matroid greedy:
  most starters, then most projected points). schedule_strength and What-If
  use it. The betting and title-odds sims still start an unconstrained top
  10 -- that is A4. Unconstrained lineups score MORE, and the published
  -120.8 level bias means lines run too HIGH (backtest_metrics:
  error = actual - projected), so the position bug is a plausible part of
  that bias and fixing it should move it toward zero (C1_DESIGN, project).
- **`marginal_value.py`** -- C1. `marginal_value(ctx, manager, adds, drops)`:
  expected points a roster change adds over a named window
  (this_week / regular_season / cup_seeding), keyed common random numbers,
  reads no files. Every advice surface (C2-C4, C6) is a caller.
  `scripts/validate_marginal_value.py` re-checks the roster-relative premise
  on real rosters; exit 2 below half the original measurement.
- **`games_grid.py`** -- C5. Lays that out as a manager x day grid led by
  Starts and Fillable, rows sorted by Starts, day cells muted. Rendered into Section 3 of the HTML straight
  from the JSON; the drafting chat sees it but must not retype it.
- **`records_tracker.py`** -- detects new records; owns `current_streaks`,
  H2H season series, `title_odds_history`.
- **`simulator_title_odds.py`** / **`simulator_playoff_odds.py`** /
  **`simulator_cup_odds.py`** -- 10,000-run Monte Carlo; title odds, finish
  distribution, magic numbers, series probabilities, Cup seeding.
- **`simulator_betting.py`** -- spreads, totals, moneylines, win probabilities.
- **`what_if_analyzer.py`** -- bench points left behind, blunders, whether a
  better lineup would have flipped the result.
- **`keepability_v2.py`** -- keeper scores and tiers. Feeds both the power
  rankings blend and Rumor Mill trade valuation.
- **`fun_facts_generator.py`** (1,197 lines) -- 20 candidate generators across
  historical / season / weekly buckets, each with a hardcoded `interestingness`
  constant, filtered for freshness, then top 3 + 2 + 3.
- **`rumor_mill_analyzer.py`** (1,541 lines) -- position needs, team situation,
  trade ideas with fit scores, free-agent targets, hot streaks, drop
  candidates. All computed; only the rationale sentences are written.

---

## 5. Data files and their scopes

**This is the section to read before trusting any number.** The files
deliberately disagree with each other.

The league has played 12 seasons. The first two predate the current rules and
are **deliberately excluded** from the data. So:

| File | Covers | Notes |
|---|---|---|
| `data/LEAGUEHISTORY.xlsx` | **11 completed seasons** | The honour roll. The ONLY file counting the two pre-rules seasons. |
| `data/historical/all_standings.json` | 9 seasons, 2017-18 on | 36 rows, 4 per season |
| `data/historical/all_matchups.json` | 9 seasons | 394 matchups |
| `config/RECORDS.json` | 9 seasons + current | `manager_careers` is regular season only |
| `config/league_config.json` `pre_data_era` | the 2 missing seasons | added to derived totals to reconcile |

Career honours are quoted at **11 seasons**; career W-L and points at **9**.
That asymmetry is intentional and the league knows about it. "All-time" in the
newsletter means "since 2017-18" for everything except titles.

`verify_project_integrity` now enforces the reconciliation: nine derived
seasons plus two honoured must equal LEAGUEHISTORY, per manager, for both
honours.

Current standing: titles Nick 6, Hayden 3, Benton 2, Garrett 0 (= 11).
Playoff championships Nick 3, Hayden 2, Benton 3, Garrett 2 (= 10; 2019-20 was
never awarded, the COVID season).

---

## 6. Traps

Things that look like bugs and are not, and things that look fine and are not.

**Accented names.** `PLAYERLIST.xlsx` keeps Yahoo's spelling. `LINEUPS`,
`PLAYERLOG` and `ROSTERS` strip diacritics on the way in. Any dict joining
across that boundary with raw string keys silently misses, and the miss looks
like a real zero. Use `data_loader.PlayerIndex`, never a plain dict, for any
name-keyed lookup that crosses the boundary. This was fixed halfway once --
three call sites of eight -- and the halfway state scored Jokic at 0.0
projected FPPG for weeks.

**`pre_data_era` key names.** `titles_won` is the regular season,
`playoff_championships` is the bracket, matching LEAGUEHISTORY's columns. They
used to be named `first_place_finishes` and `titles`, where `titles` meant
playoff championships -- the opposite of what `titles_won` means one file over.

**Silent defaults.** `.get(x, 0)` is fine where zero is the right answer for
absent data. It is a bug where zero is a plausible real value a reader would
believe: titles, records, projections, ages, streaks. Prefer None and let the
renderer say "unavailable".

**`RECENT_CONTENT.json`** holds exactly three keys: `fun_facts`,
`trade_ideas`, `free_agent_recs`. `content_freshness.save()` rewrites only
those, so anything else written into it -- headlines, section openers -- is
silently dropped on the next run.

**`--fast`** is not free. It skips the simulators, so sections 3 and 7 come out
empty and Rumor Mill reads every manager as a contender on a 25% default.

**Season performers** calls the Yahoo API at report time. If Yahoo is
unreachable, every player gets 0 games played, three of the four leaderboards
come back empty, and the run still prints "Report generated successfully".

**`(Empty)`** is a real value in `LINEUPS` when a manager leaves a roster slot
open. It reaches `ROSTERS.json` as though it were a player.

**Mid-week transactions** put a player on two rosters until
`sync_transactions` resolves it. `check_rosters.py` now verifies that it did.

---

## 7. The gates

Three things are allowed to stop a week. Respect them.

- `check_playerlist.py` -- every simulator runs on `projectedFPPG`. Its
  sharpest rule is that projected games remaining may not go **up**, which is
  the signature of a shifted column.
- `verify_project_integrity.py` -- syntax, file sizes (a >20% shrink is a
  FAILURE), imports, config, ASCII, and the golden master with
  `--compare-golden`.
- `check_rosters.py` -- no duplicate ownership, no placeholders, plausible
  sizes.

Step 6 itself refuses to run in season on an NBA schedule fetched more than
8 days ago (`modules/schedule_freshness.py`; `--allow-stale-schedule`
overrides and is recorded). `fetch_nba_schedule` refuses a refresh that
loses more than 10% of games and logs every change set.

`verify_project_integrity` also guards the point-in-time record: a latest
report with no capture under `config/snapshots/point_in_time/` FAILS, an
unreviewed `INJURY_OVERRIDES.json` FAILS from Week 1, and a PLAYERLIST snapshot
older than 8 days warns. Every one of those is a week of record that cannot be
rebuilt later -- the reason no pre-2026-27 published line can be backtested.

---

**Retro-simulation** has its own constraints, written before any of it was
built: `RETRO_SIM_REQUIREMENTS.md`. Read it before touching the harness or A2.

## 8. If you are picking this up again

Run `python scripts/verify_project_integrity.py --compare-golden`, then
`python -m pytest tests/ -q`. If both are clean the engine is sound and
anything odd is data.

The recurring failure in this project is not broken code. It is a value
derived once and never advanced, quietly disagreeing with its source. Stale
baselines, week counts read from the wrong file, a description contradicting
the config beneath it, a copy of a count that was never refreshed. When adding
anything, ask what advances it and what happens if nothing does.
