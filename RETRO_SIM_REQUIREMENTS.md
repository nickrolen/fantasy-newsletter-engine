# Retro-simulation: requirements and known limits

Written 2026-10-06, before any harness code exists, so that the constraints
are read before the harness is designed rather than found in it. Plan item 6
(the harness) and item 7 (A2, the absence model) both inherit everything here.

---

## 1. What a historical week can and cannot be rebuilt from

Checked against the data on disk, 2026-10-06.

| Input the simulator needs | Rebuildable? | From |
|---|---|---|
| Rosters at week start | **Yes** | `HISTORICAL_PLAYERLOG.json` -- every roster slot every day, bench and IL included, 12-17 rows per manager-day for 2017-18 through 2024-25. 2025-26 only after the §3.1 log repair (until then 1-17 rows per manager-day). |
| Fantasy matchups and week dates | **Yes** | `all_matchups.json` + the log's `week` field |
| NBA schedule | **Yes, for rostered teams** | the log's `had_game` / `nba_team` / `nba_opponent`. Games *as played*, so postponements leak (mostly 2019-20 and 2020-21). Small and accepted. |
| Injury state at week start | **Proxy only** | see R1 -- `is_injured` is an outcome, not a status |
| `projectedFPPG`, `player_proj_GP` | **No** | Yahoo's projections were never saved for any past week. The one archived 2025-26 PLAYERLIST is a single late-season snapshot. |
| Free-agent pool with projections | **No** | so C2/C3 cannot be validated retroactively at all |

The harness therefore substitutes its **own point-in-time projection**:
trailing FPPG and trailing miss rate from games strictly before the week,
blended with the previous season early on.

From 2026-27 on, Step 6 freezes the real inputs every week
(`config/snapshots/point_in_time/report_weekNN/`, see `modules/point_in_time.py`).
That is the forward record that closes the gap; the retro-sim does not.

---

## 2. Hard requirements -- assertions, not comments

A comment saying "don't read the future" will not survive six weeks. Each of
these is enforced in code and pinned by a test that **plants a poisoned value
and proves the harness never sees it**.

**R1 -- `is_injured` is never read on or after day 1 of the simulated week.**
`enrich_historical_playerlog.py` sets `is_injured = had_game and FP == 0`. It
is an outcome dressed as a status: on day 1 of week W it says the player
*missed* day 1 of week W. The harness reads the log only through one accessor
that is bounded by a cutoff date and **raises** on any row dated on or after
it. The same applies to `fantasy_points`; actuals for scoring come through a
separate object the projection code has no handle on.
Test: a row dated on the cutoff with `is_injured=True` either raises or
leaves every projection byte-identical to the run without it.

**R2 -- no input is read from a fixed path.** The engine reads rosters from
hard-coded locations: `simulator_betting.py` (~line 254, `config/ROSTERS.json`),
`data_loader.py` (~lines 391 and 418), and `projections.ROSTERS_FILE`. A
retro-sim through the normal entry points would silently simulate a 2019
week with today's rosters. The harness passes rosters, projections, schedule
and injury state in explicitly.
Test: point every one of those paths at a poisoned file (or make it raise)
and assert the harness output is unchanged. Re-run that test when any new
module reads a config file.

**R3 -- score against log-derived actuals.** Log-derived weekly started-FP
disagrees with `all_matchups` scores by 1-5 points (once by 155) for
2017-18 through 2024-25, plausibly Yahoo stat corrections. The simulator is
built on the log, so it is scored against the log. Report the disagreement,
do not average it away.

**R4 -- 2025-26 is excluded until the §3.1 repair lands**, and the harness
asserts a minimum rows-per-manager-day before admitting a season.

---

## 3. Known limitation of A2 -- state this in the A2 writeup

**A2 is calibrated against a projection distribution that is never published.**

The harness substitutes its trailing-FPPG projection for Yahoo's. Absence
*shape* -- block vs. scattered vs. iron-man, weekly games-played variance,
zero-game weeks -- is mostly separable from projection *level*, so the shape
calibration should transfer.

What does **not** transfer is the interaction between projection error and
absence variance. Live, the engine is wrong about a player's level (Yahoo's
error) *and* about his availability at the same time, and the two compound.
The retro-sim has a different projection error with a different distribution,
so the joint error it measures is not the joint error of the published lines.

That interaction is exactly where close-matchup win probabilities live: when
two teams project within ~50 points, the outcome is decided by the tails, and
the tails are where level error and absence variance stack. So:

- Retro-sim results for A2 are evidence about **absence shape**, not about the
  accuracy of published win probabilities.
- They cannot attribute the measured -120.8 level bias (weeks 17-22, n=12)
  between Yahoo's projections and the model -- the harness never sees Yahoo's
  projections. Sign: error = actual - projected, so -120.8 means the lines
  run too HIGH (backtest_metrics.ERROR_CONVENTION). Known model-side
  candidate: the simulators start an unconstrained top 10 with no position
  limits, which overstates points (A4).
- The check that does measure it: re-price 2026-27's weeks from the frozen
  `report_weekNN` inputs with and without A2, and score both against what
  happened. That needs a season of captures; it is not available before
  roughly midseason.

Any A2 writeup that reports win-probability or Brier improvement from the
retro-sim must quote this section.
