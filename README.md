# Fantasy Basketball Newsletter Engine

[![CI](https://github.com/nickrolen/fantasy-newsletter-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/nickrolen/fantasy-newsletter-engine/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

*A data pipeline that turns a season of Yahoo Fantasy Basketball into a polished, sportsbook-style weekly newsletter.*

This project pulls a fantasy league's raw data from the Yahoo Fantasy API, runs it through a 20+ module statistics engine and tens of thousands of Monte Carlo simulations, and emits a single HTML newsletter every week (one file with CSS/JS/data inline; Google Fonts are loaded from the web with system-sans/serif fallbacks). The interesting part is the architecture: a deterministic Python formatter does all the number-crunching and cross-referencing before any prose is written, so the language model that drafts the copy never has to invent a statistic. Nearly the entire engine is driven by **one config file** -- point it at your own league and the bulk of the work happens automatically.

It was built and tested for a real four-team keeper league (the CHS Alumni league, running since 2017), which serves as the reference implementation throughout. The regular-season analytics scale to N teams; the playoff bracket and a few visualizations currently assume a four-team structure.

### Sample output

**[View a live newsletter ->](https://nickrolen.github.io/fantasy-newsletter-engine/)** (rendered via GitHub Pages -- no download needed)

A finished newsletter for Week 21 lives at [`output/WEEK21_NEWSLETTER.html`](output/WEEK21_NEWSLETTER.html) -- view it live at the link above, or open the file in a browser to see the end product (matchup recaps, power rankings, betting lines, interactive Stats Corner visualizations, and a 50-table record book). Fresh output is generated weekly during the season; the `output/` folder keeps the most recent weeks on hand.

> Note: GitHub renders the `.html` file as source. The live link above serves the rendered page.

---

## What It Does

The pipeline moves data through six stages, each handing a cleaner artifact to the next:

**Yahoo Fantasy API -> stats engine -> Monte Carlo simulations -> deterministic formatter -> LLM drafting -> HTML newsletter.**

Daily and weekly pulls bring in box scores, lineups, transactions, and standings. The stats engine computes everything from weekly team totals to season-long advanced metrics. Monte Carlo simulators project title odds, playoff brackets, and betting lines over thousands of iterations. A deterministic formatter then assembles ~650 lines of organized, pre-cited Markdown -- one source of truth for every number. A language model drafts the prose section by section against that Markdown (the only manual step), and a standalone HTML generator renders the final, mobile-responsive newsletter with embedded graphics and interactive charts.

Headline features:

- **15+ newsletter sections** -- matchup recaps, manager report cards, power rankings, Player of the Week, fun facts, "What If" optimal-lineup analysis, around-the-league notes, and a strategy-focused rumor mill.
- **Playoff bracket simulation** -- a Monte Carlo bracket simulator that projects semifinal and championship probabilities and the most likely finals matchup.
- **Sportsbook-style betting lines** -- spreads, over/unders, and moneylines for every upcoming matchup, generated from simulated score distributions.
- **50-table record book** -- five categories (team, player, rookie, draft & trades, manager) of all-time top-10 leaderboards, rendered as an interactive trophy case spanning every season on record.
- **Keeper scoring** -- a score-based keepability model that tiers each roster's top players from "Lock" to "Drop."
- Plus a luck index, consistency/volatility scoring, a draft value tracker, waiver-wire ROI, and schedule-strength analysis.

---

## Model Validation

The newsletter publishes betting lines every week, so the obvious question is
whether they are any good. This section reports the answer, including the parts
that are unflattering.

**Method.** Lines are read back out of the published newsletter HTML rather than
the stored JSON. `output/looking_ahead_week*.json` is regenerated whenever a past
week is re-run, and a re-run uses today's rosters and injuries -- three of the
2025-26 files no longer match what was actually published (week 21 now reads
+419.5 / 6.6% where the newsletter printed +118.5 / 34.62%). The HTML is the
immutable record, and the only copy committed here, so
[`scripts/backtest_extract.py`](scripts/backtest_extract.py) reproduces the
dataset from a fresh clone. Lines for week N come from week N-1's newsletter, so
every prediction is scored against a result that had not happened yet.

**Sample: 12 lines across weeks 17-22, and the 24 team-score projections behind
them.** That is small. The two matchups in a given week share a scoring
environment, so the effective sample is smaller still. Every interval below is
wide, and the significance test on the team-score bias treats team-weeks as
independent when they are not -- read its direction, not its p-value.

![Betting-line backtest: projected vs actual](assets/backtest_calibration.png)

| Question | Answer |
|---|---|
| Are the team-score projections right on average? | **No.** Mean error -120.8 FP (-7.3%); 18 of 24 landed below projection. |
| Is the projected margin right on average? | Close enough. Mean error -77.8 FP, t = -1.1, not significant. |
| Is the stated uncertainty honest? | As far as this sample can tell, yes. rms(z) = 0.99, 95% CI [0.71, 1.63]. |
| Do the win probabilities carry information? | **Not detectably.** Brier 0.2485 against 0.2500 for a coin flip; the favourite went 6-6. |

**Reading it.** The simulator is better at ranking teams than at scoring them.
Both sides of a matchup get over-projected by a similar amount, so the error
largely cancels in the spread and accumulates in the total: totals ran 242 FP
high and only 2 of 12 went OVER. The most likely cause is that projections
assume rostered players play, while real weeks lose games to injury, rest and
late scratches.

The moneyline line in that table is the one that matters most and the one this
sample can say least about. At n=12 a Brier score of 0.2485 is indistinguishable
from no skill and equally indistinguishable from useful skill. The honest
statement is that these win probabilities have not been shown to beat a coin
flip. It is also worth knowing that the published lines were generated with
between 200 and 5,000 simulations depending on the week, so some of them carry
several points of Monte Carlo noise on their own.

**What it changes.** A level correction is the obvious first fix, and the
backtest predicts what it should do: scale the projections down and the totals
should move while the spreads stay put. Re-running this report after any change
to the simulator is one command:

```bash
python scripts/backtest_extract.py          # rebuild the dataset
python scripts/backtest_report.py --plot    # score it and redraw the figure
```

The scoring rules themselves live in
[`modules/backtest_metrics.py`](modules/backtest_metrics.py) and are unit-tested
in [`tests/test_backtest_metrics.py`](tests/test_backtest_metrics.py).

---

## Quick Start

You'll need Python 3.10+ and a Yahoo Fantasy league.

**1. Clone the repo and install dependencies.**

```bash
git clone https://github.com/nickrolen/fantasy-newsletter-engine.git
cd fantasy-newsletter-engine
pip install -r requirements.txt
```

**2. Set up your Yahoo API credentials.** Create an app in the [Yahoo Developer portal](https://developer.yahoo.com/), then copy the example credentials file and fill in your keys:

```bash
cp oauth2.json.example oauth2.json
# edit oauth2.json -> add your consumer_key and consumer_secret
```

`oauth2.json` is gitignored and never committed. The first API call opens a browser to complete OAuth.

**3. Configure your league.** This is the one file you actually edit. Copy the example and fill in your league's details:

```bash
cp config/league_config.json.example config/league_config.json
```

Set your managers, team names, Yahoo league key, brand/manager colors, league structure (teams, roster size, keepers), and the current season block. Nearly every downstream module reads from here. A small handful of visualization constants and narrative strings may still need a one-time edit for a new league.

**4. Fetch your NBA schedule** for the season you're covering:

```bash
python scripts/fetch_nba_schedule.py --season <your-season> --output data/nba_schedule_<your-season>.json
```

(e.g. `--season 2025-26 --output data/nba_schedule_2025-26.json`)

**5. Create your season schedule.** Populate `config/SCHEDULE.json` with your league's weekly matchups and date ranges, including the `regular_season_weeks`, `playoff_start_week`, and `total_weeks` metadata that drives playoff routing.

**6. Run the weekly workflow.** With config in place, each week follows a repeatable sequence -- pull data, generate the stats report, format it, draft, and render. The full step-by-step is in [`WEEKLY_WORKFLOW.md`](WEEKLY_WORKFLOW.md).

---

## Architecture

```
                          league_config.json
                                  |
                                  v
   Yahoo Fantasy API  -->  data_loader.py  -->  Stats Engine (20+ modules)
                                                        |
                  +-----------------------------+-------+-----------------------+
                  |                             |                               |
            Monte Carlo                  Advanced Metrics                  Record Book
            Simulators            (luck, consistency, draft value,    (50 leaderboards
       (title / playoff /          waiver ROI, keeper, what-if)        across 5 groups)
        betting odds)                       |                               |
                  +-----------------------------+-------+-----------------------+
                                                  |
                                                  v
                                          report_builder.py
                                       (assembles one JSON report)
                                                  |
                                                  v
                                       format_stats_report.py
                                  (deterministic Markdown, pre-cited)
                                                  |
                                                  v
                                         LLM Drafting (manual)
                                                  |
                                                  v
                                    newsletter_html_generator.py
                                                  |
                                                  v
                                       Final HTML Newsletter
```

The key design decision is the split between the deterministic formatter and the language model. By the time the LLM sees anything, every statistic, record claim, and injury timeline has already been computed and cross-referenced by Python. The model's job is voice, not arithmetic.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ |
| Data processing | pandas, NumPy, openpyxl |
| Fantasy data | Yahoo Fantasy API (`yahoo-fantasy-api`, `yahoo-oauth`) |
| NBA data | NBA API (`nba_api`), Basketball Reference (BeautifulSoup) |
| Modeling | Monte Carlo simulation (title odds, playoff brackets, betting lines) |
| Output | Self-contained HTML (no framework), embedded base64 images, Google Fonts |

---

## Project Structure

```
newsletter/
+-- config/        # League config + per-season state
|   \-- league_config.json   # <-- THE ONE FILE a new user fills in
+-- modules/       # Analysis engine (24 files)
+-- scripts/       # Pipeline steps + utilities (22 scripts)
+-- data/          # Game data + historical archives
+-- templates/     # Newsletter writing prompts & reference manual
+-- output/        # Generated reports + newsletters
+-- assets/        # Newsletter drafts + image assets
\-- archive/       # Archived past seasons (created at season reset)
```

For a file-by-file map of the engine, see [`PROJECTSTRUCTURE.md`](PROJECTSTRUCTURE.md).

---

## Features in Depth

<details>
<summary><strong>Statistical &amp; analytical features</strong></summary>

- **Monte Carlo simulators** -- Three engines run thousands of iterations each. `simulator_title_odds.py` projects regular-season finish distributions and magic numbers; `simulator_playoff_odds.py` simulates the two-week playoff bracket (semifinals into a dynamically built finals); `simulator_betting.py` produces spreads, over/unders, and moneylines with an injury discount applied to scoring totals.
- **Luck Index** -- All-play expected wins (each week, the fraction of the league you outscored) compared against actual wins, isolating schedule luck from skill. Labels are z-scored against the metric's null distribution so early-season noise doesn't earn a luck narrative.
- **Consistency / volatility scoring** -- Coefficient of variation and interquartile range at both the team and player level, with boom/bust counts and recent-trend detection.
- **Draft value tracker** -- Grades every drafted pick against a pick-level expected-value model (P1-P36), labeling each Steal, Fair, or Bust, with player-status detection (rostered/traded/claimed/dropped).
- **Waiver-wire ROI** -- Season-long return on every pickup: fantasy points gained in starter slots versus points lost on dropped players, with best-add and biggest-regret callouts.
- **Keeper scoring** -- A blended-FPPG-times-availability-times-age model that tiers each roster's top six from Lock to Drop, consistent with the trade-value engine.
- **What-If analysis** -- Optimal-lineup reconstruction that surfaces points left on the bench and flags avoidable "blunders" (a scoring bench player who could have filled an empty or DNP starter slot).
- **Schedule strength** -- NBA games per roster for the upcoming week and rest-of-season, filtered by injury status.

</details>

<details>
<summary><strong>Engineering &amp; reliability features</strong></summary>

- **Deterministic formatter** -- `format_stats_report.py` cross-references 15+ JSON sections plus six additional data sources and emits ~650 lines of pre-organized, pre-cited Markdown. The LLM never extracts numbers itself, which eliminates an entire class of hallucinated statistics.
- **Anti-hallucination template** -- The newsletter template encodes explicit verification rules (superlative claims, magic numbers, elimination math, trade-grade direction) plus a per-section final checklist, hardening the manual drafting step against common model errors.
- **Content freshness** -- `content_freshness.py` tracks recently used headlines and openers so week-to-week newsletters don't repeat themselves.
- **Reproducibility mode** -- A `--repro` flag re-runs any week against pre-week snapshots and frozen betting lines, so you can iterate on newsletter copy without contaminating continuity state or changing the odds. (Boundary note: repro freezes betting lines and freshness state, but season-cumulative stats are recomputed from the current game logs -- regenerating an old week after later weeks were logged will reflect the newer cumulative totals.)
- **Integrity checker** -- `verify_project_integrity.py` catches silent file truncation, syntax breakage, broken imports, config drift, and encoding corruption after any batch of edits, with an optional golden-master comparison.
- **ASCII-only source policy** -- `check_file_health.py` enforces pure-ASCII `.py` and `.md` files (Unicode via escape sequences), preventing mojibake when files pass through download/upload cycles.
- **Single source of configuration** -- One `league_config.json` feeds the bulk of the engine: manager and team names, league keys, and most colors flow from this file.

</details>

---

## Season Lifecycle

The project supports clean transitions between seasons. At the end of a year, [`scripts/start_new_season.py`](scripts/start_new_season.py) archives that season's outputs, resets the per-season working files to empty defaults, and clears the generated artifacts -- always as a dry run first, then with `--execute`. Every archived season lands in `archive/<season>/` as a complete snapshot (reports, newsletters, drafts, snapshots, and config), while the permanent historical record and league identity stay untouched.

The full runbook -- what's archived, what's reset, and the manual steps for rolling a finished season into history -- is in [`SEASON_RESET.md`](SEASON_RESET.md). Run the integrity checker afterward to confirm nothing was left in a broken state.

---

## The League

This engine was built for the **CHS Alumni Fantasy Basketball League**, a four-team keeper league running since 2017. It's the reference implementation -- the values you'd replace in `league_config.json` for your own league:

| Manager | Team Name |
|---------|-----------|
| Nick | Luka my Balls |
| Hayden | Big Nik Energy |
| Benton | Smaxey |
| Garrett | Saboner |

---

## License

MIT License -- free to adapt for your own fantasy league.

## Acknowledgments

- **Yahoo Fantasy API** -- league, roster, and transaction data
- **NBA API** -- schedule and player data
- **Basketball Reference** -- rookie-season lookups
- **Google Fonts** (Inter, Playfair Display) -- newsletter typography
