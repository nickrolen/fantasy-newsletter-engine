"""The weekly RECORDS write is two phases, and the first must precede the sims.

One call used to do two unrelated jobs, after the simulations:

  - advance current state (W-L, H2H, career totals), which the simulations and
    the report cards need BEFORE they run;
  - persist what the week's analysis concluded (bench points, blunders), which
    cannot exist UNTIL after the what-if.

Bundled and placed last, every published report simulated from records one
week stale, so the report disagreed with itself: cards read 0-0 under
standings reading 1-0, expected records came out a game short of the season,
and week 16 showed a 12-point title-odds error on a published number. Not a
week-1 artifact -- the pipeline runs once a week, so the stale run is the one
that publishes, every week.

The suite had 916 tests guarding local invariants and nothing guarding this
transition, which is why it survived a season. These are that guard.
"""
from types import SimpleNamespace

import pytest

from modules import records_tracker as rt
from modules.data_loader import MANAGERS, regular_season_weeks_for


def _records(state_week, history_week=None):
    """A RECORDS skeleton. history_week=None means a pre-split file."""
    r = {rt.STATE_WATERMARK_KEY: state_week}
    if history_week is not None:
        r[rt.HISTORY_WATERMARK_KEY] = history_week
    return r


# ---------------------------------------------------------------------------
# 1. The watermarks, and the trap the split creates
# ---------------------------------------------------------------------------

def test_a_pre_split_file_inherits_the_state_watermark_once():
    """Before the split one watermark was an accurate position for both."""
    r = _records(7)
    rt.seed_history_watermark(r)
    assert r[rt.HISTORY_WATERMARK_KEY] == 7
    # Idempotent: a second seed must not clobber an advanced history mark.
    r[rt.HISTORY_WATERMARK_KEY] = 9
    rt.seed_history_watermark(r)
    assert r[rt.HISTORY_WATERMARK_KEY] == 9


def test_seeding_after_the_state_phase_would_swallow_the_history_phase():
    """THE trap. If the history watermark is seeded from a state watermark the
    state phase has already advanced, the history phase sees its own week as
    done and skips -- trading a stale-input bug for a lost-history bug."""
    poisoned = _records(state_week=8, history_week=8)   # seeded too late
    rt._persist_derived_history(poisoned, 8, {"Nick": 50.0}, {"Nick": 1})
    assert "cumulative_bench_points" not in poisoned     # silently skipped

    correct = _records(state_week=8, history_week=7)     # seeded before
    rt._persist_derived_history(correct, 8, {"Nick": 50.0}, {"Nick": 1})
    assert correct["cumulative_bench_points"]["Nick"] == 50.0
    assert correct[rt.HISTORY_WATERMARK_KEY] == 8


def test_the_real_sequence_lets_both_phases_land():
    """State then history, from a pre-split file, through the public entry
    point. Seeding happens on the first call, before the state phase advances
    anything, which is the only ordering that works."""
    r = _records(state_week=0)                 # pre-split, nothing processed
    import pandas as pd
    data = SimpleNamespace(records=r, base_path=".",
                           playerlog=pd.DataFrame())
    # The state phase reads these four off the report; empty is enough here,
    # since what is under test is the watermark sequence, not the records.
    report = SimpleNamespace(week=1, best_single_game=None,
                             worst_single_game=None, manager_stats={},
                             matchups=[])

    rt.update_records_from_weekly_report(
        data, report, phase=rt.RECORDS_PHASE_STATE, title_odds=None)
    assert r[rt.HISTORY_WATERMARK_KEY] == 0    # seeded from state's OLD value

    rt.update_records_from_weekly_report(
        data, report, phase=rt.RECORDS_PHASE_HISTORY,
        bench_points={"Nick": 42.0}, blunders={"Nick": 2})
    assert r["cumulative_bench_points"]["Nick"] == 42.0
    assert r[rt.HISTORY_WATERMARK_KEY] == 1


def test_the_history_phase_does_not_double_add():
    """Bench points and blunders are cumulative adds, so the guard has to
    survive the split -- that is what it was there for."""
    r = _records(state_week=3, history_week=2)
    rt._persist_derived_history(r, 3, {"Nick": 10.0}, {"Nick": 1})
    rt._persist_derived_history(r, 3, {"Nick": 10.0}, {"Nick": 1})
    assert r["cumulative_bench_points"]["Nick"] == 10.0


def test_an_unknown_phase_raises_rather_than_silently_doing_nothing():
    data = SimpleNamespace(records=_records(1))
    with pytest.raises(ValueError):
        rt.update_records_from_weekly_report(
            data, SimpleNamespace(week=1), phase="both-ish")


def test_title_odds_history_is_written_even_when_both_guards_skip():
    """It is an overwrite keyed by week, not a cumulative add, and the
    power-rankings trend arrows depend on it. It lives outside both guards so
    a re-run refreshes it instead of freezing every trend at "flat"."""
    r = _records(state_week=5, history_week=5)      # both guards will skip
    data = SimpleNamespace(records=r)
    rt.update_records_from_weekly_report(
        data, SimpleNamespace(week=5), phase=rt.RECORDS_PHASE_HISTORY,
        title_odds={"Nick": 61.2}, bench_points={"Nick": 1.0})
    hist = r.get("title_odds_history") or {}
    assert hist, "title_odds_history was not written"
    assert "cumulative_bench_points" not in r        # guard still held


# ---------------------------------------------------------------------------
# 2. Expected records span the whole season
# ---------------------------------------------------------------------------

def test_recorded_weeks_plus_remaining_weeks_equal_the_season():
    """The arithmetic the bug broke. With records one week stale the two sides
    sum to one short of the season, which is how a 15-week race was projected
    as 14 games. The length comes from league_config -- never hardcoded, since
    season layouts vary by year."""
    from modules.simulator_title_odds import get_remaining_weeks
    from modules.data_loader import CURRENT_SEASON

    season_len = regular_season_weeks_for(CURRENT_SEASON)
    schedule = {"weeks": [{"week": w, "start_date": "2026-10-20",
                           "end_date": "2026-10-25"} for w in range(1, 24)]}
    data = SimpleNamespace(schedule=schedule)

    week = 1
    remaining = len(get_remaining_weeks(data, week))
    assert week + remaining == season_len, (
        f"records through week {week} plus {remaining} remaining "
        f"should be {season_len}")
    # One week stale is one game short -- the defect, stated as arithmetic.
    assert (week - 1) + remaining == season_len - 1


def test_remaining_weeks_stop_at_the_regular_season_boundary():
    """Playoff and Cup weeks must not inflate the race to a 23-game scale."""
    from modules.simulator_title_odds import get_remaining_weeks
    from modules.data_loader import CURRENT_SEASON
    schedule = {"weeks": [{"week": w, "start_date": "2026-10-20",
                           "end_date": "2026-10-25"} for w in range(1, 24)]}
    data = SimpleNamespace(schedule=schedule)
    weeks = [w["week"] for w in get_remaining_weeks(data, 0)]
    assert weeks and max(weeks) == regular_season_weeks_for(CURRENT_SEASON)


# ---------------------------------------------------------------------------
# 3. The report has to agree with itself
# ---------------------------------------------------------------------------

def test_manager_week_stats_carries_no_record_snapshot():
    """These stats are computed as part of PRODUCING week N's result, so any
    record read there is necessarily the week before. Deleting the fields is
    what stops the stale snapshot coming back."""
    from modules.weekly_stats import ManagerWeekStats
    fields = set(getattr(ManagerWeekStats, "__dataclass_fields__", {}))
    assert not ({"wins", "losses", "record_str"} & fields), (
        "a record snapshot is back on ManagerWeekStats")


def test_build_report_cards_requires_data_so_it_can_read_the_live_record():
    """The cards and current_standings must read one source, once per render:
    data.get_manager_record(). An optional `data` would let a caller fall back
    to a snapshot."""
    import inspect
    from modules.report_builder import build_report_cards
    p = inspect.signature(build_report_cards).parameters
    assert "data" in p, "build_report_cards no longer takes data"
    assert p["data"].default is inspect.Parameter.empty, (
        "data is optional again; the cards can go back to a stale snapshot")


# ---------------------------------------------------------------------------
# 4. The two phases stay on opposite sides of the simulations
# ---------------------------------------------------------------------------

def test_state_precedes_the_simulations_and_history_follows_the_what_if():
    """The cheap guard against the two calls being collapsed back into one.
    Source order is the invariant: no unit test can see it, and a single call
    anywhere is the original bug."""
    import inspect
    from modules import report_builder
    src = inspect.getsource(report_builder.build_stats_report)

    state = src.index("RECORDS_PHASE_STATE")
    history = src.index("RECORDS_PHASE_HISTORY")
    first_sim = src.index("run_season(")      # the one season pass (Phase 2)
    what_if = src.index("analyze_weekly_what_if")

    assert state < first_sim, "the state write moved after the simulations"
    assert what_if < history, "the history write moved before the what-if"
    assert state < history
