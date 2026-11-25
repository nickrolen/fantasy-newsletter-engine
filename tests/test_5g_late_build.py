"""5g s.2 (claude/HANDOFF_5G_WEEKLY_BUILD_FIXES_2026-11-25.md): a weekly build
made after its week has started.

  (a) the title-odds chart: a weekly_build history row never displaces another
      kind's row on the same league day; it fills a day only when no other run
      wrote one (hub_charts.title_points). The history file is unchanged.
  (b) the calibration log: a weekly-build record published after its week's
      first tip carries published_after_first_tip; the curve leaves such
      records out (and the pre-5g ones by the same rule, by as_of) and says how
      many. The weekly build's stamps carry the league clock's offset; readers
      accept the old naive (Phoenix) form too.
"""
import inspect
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import calibration_log as cal                       # noqa: E402
from modules import hub_charts as hc                             # noqa: E402

PT = ZoneInfo("America/Los_Angeles")
SCHED = {"weeks": [{"week": 5, "start_date": "2026-11-16", "end_date": "2026-11-22"},
                   {"week": 6, "start_date": "2026-11-23", "end_date": "2026-11-29"}]}


def row(as_of, kind, garrett):
    return {"as_of": as_of, "kind": kind, "title_odds": {"Garrett": garrett, "Nick": 100 - garrett}}


# ============================================================ (a) the chart

def test_a_later_weekly_build_row_does_not_take_the_afternoon_point():
    """11-24 exactly: nightly 56.9 at 7:29 AM, afternoon 57.4 at 3:30 PM, the
    week-5 build's 61.4 at 3:43 PM. The day shows the afternoon run's."""
    rows = [row("2026-11-24T07:29:27-08:00", "nightly", 56.858),
            row("2026-11-24T15:30:39-08:00", "afternoon", 57.42),
            row("2026-11-24T15:43:27-08:00", "weekly_build", 61.438)]
    pts = hc.title_points(rows, [], SCHED)
    assert pts[date(2026, 11, 24)]["values"]["Garrett"] == 57.42
    assert pts[date(2026, 11, 24)]["source"] == "afternoon run"


def test_a_day_with_only_a_weekly_build_row_shows_it():
    rows = [row("2026-11-23T18:55:00-08:00", "closing", 60.494),
            row("2026-11-24T15:43:27-08:00", "weekly_build", 61.438)]
    pts = hc.title_points(rows, [], SCHED)
    assert pts[date(2026, 11, 24)]["values"]["Garrett"] == 61.438
    assert pts[date(2026, 11, 24)]["source"] == "weekly_build run"
    assert pts[date(2026, 11, 23)]["values"]["Garrett"] == 60.494


def test_another_kinds_later_row_still_replaces_a_weekly_build():
    rows = [row("2026-11-24T10:00:00-08:00", "weekly_build", 61.438),
            row("2026-11-24T15:30:39-08:00", "afternoon", 57.42)]
    assert hc.title_points(rows, [], SCHED)[date(2026, 11, 24)]["values"]["Garrett"] == 57.42


def test_the_history_rows_are_not_touched():
    rows = [row("2026-11-24T15:30:39-08:00", "afternoon", 57.42),
            row("2026-11-24T15:43:27-08:00", "weekly_build", 61.438)]
    before = json.dumps(rows, sort_keys=True)
    hc.title_points(rows, [], SCHED)
    assert json.dumps(rows, sort_keys=True) == before


# ============================================================ (b) calibration

TIP6 = datetime(2026, 11, 23, 16, 0, tzinfo=PT)
TIP5 = datetime(2026, 11, 16, 16, 0, tzinfo=PT)


def tip(season, week):
    return {5: TIP5, 6: TIP6}[int(week)]


def rec(week, a, b, source, as_of, *, settled=True, mark=None, pa=1300.0, pb=1250.0, engine="abc1234"):
    r = {"season": "2026-27", "week": week, "manager_a": a, "manager_b": b,
         "matchup_id": "|".join(sorted((a, b))), "spread_a": -20.5, "total": 2600.0,
         "moneyline_a": -130, "moneyline_b": 130, "win_prob_a": 56.0, "win_prob_b": 44.0,
         "projected_a": pa, "projected_b": pb, "banked_a": 0.0, "banked_b": 0.0,
         "engine_commit": engine, "engine_dirty": False, "seed": 1, "num_simulations": 10,
         "state_hash": None, "line_key": f"k{week}{a}{source}{as_of}", "as_of": as_of, "source": source,
         "tags": {}, "overrides_governing": {},
         "actual_a": 1310.0 if settled else None, "actual_b": 1200.0 if settled else None,
         "actual_source": "RECORDS.json" if settled else None,
         "settled_at": "2026-11-30" if settled else None}
    if mark is not None:
        r[cal.AFTER_FIRST_TIP] = mark
    return r


def week5_issue():
    """The week-5 issue's two records as they sit in the log: naive Phoenix,
    Tuesday 11-24 16:42 (15:42 Pacific), after week 6's first tip; unsettled."""
    return [rec(6, "Nick", "Garrett", "weekly_build", "2026-11-24T16:42:36", settled=False),
            rec(6, "Hayden", "Benton", "weekly_build", "2026-11-24T16:42:36", settled=False)]


def test_the_week_5_issues_records_are_recognised_without_a_mark():
    for r in week5_issue():
        assert cal.AFTER_FIRST_TIP not in r
        assert cal.is_after_first_tip(r, tip) is True


def test_the_curve_leaves_out_late_weekly_builds_and_says_how_many():
    lines = [
        # week 5: two pre-week weekly builds (Monday 7:55 AM Phoenix) and two late ones
        rec(5, "Nick", "Hayden", "weekly_build", "2026-11-16T07:55:45"),
        rec(5, "Benton", "Garrett", "weekly_build", "2026-11-16T07:55:45"),
        rec(5, "Nick", "Hayden", "weekly_build", "2026-11-16T19:36:22", engine="late111"),
        rec(5, "Benton", "Garrett", "weekly_build", "2026-11-16T19:36:22", engine="late111"),
        # marked ones (from 5g on): one true, one false
        rec(5, "Nick", "Hayden", "weekly_build", "2026-11-16T18:00:00-08:00", mark=True, engine="mk"),
        rec(5, "Benton", "Garrett", "weekly_build", "2026-11-16T09:00:00-08:00", mark=False, engine="mk"),
        # the closing line and a live refresh are never left out by this rule
        rec(5, "Nick", "Hayden", "closing", "2026-11-16T17:55:00-08:00"),
        rec(5, "Benton", "Garrett", "closing", "2026-11-16T17:55:00-08:00"),
        rec(5, "Nick", "Hayden", "live_refresh", "2026-11-18T00:05:00-08:00"),
    ] + week5_issue()
    out = cal.curve(lines=lines, first_tip=tip)
    late = out["after_first_tip"]
    assert late["left_out"] == 5               # 2 late (by as_of), 1 marked, the week-5 issue's 2
    assert late["settled_left_out"] == 3
    assert late["weeks"] == [5, 6] and late["marked"] == 1
    assert "late111 / weekly_build" not in out["groups"]
    assert out["groups"]["abc1234 / weekly_build"]["n_lines"] == 2
    assert out["groups"]["mk / weekly_build"]["n_lines"] == 1
    assert out["groups"]["abc1234 / closing"]["n_lines"] == 2
    assert out["records"] == len(lines)
    text = "\n".join(cal.format_curve(out))
    assert "left out: 5 weekly-build record(s) published after their week's first tip" in text


def test_the_rule_reads_naive_as_phoenix_and_aware_as_written():
    # 16:30 Phoenix is 15:30 Pacific: before the 16:00 PT tip
    assert cal.is_after_first_tip(rec(6, "A", "B", "weekly_build", "2026-11-23T16:30:00"), tip) is False
    # 17:00 Phoenix is 16:00 Pacific: at the tip, so after
    assert cal.is_after_first_tip(rec(6, "A", "B", "weekly_build", "2026-11-23T17:00:00"), tip) is True
    assert cal.is_after_first_tip(rec(6, "A", "B", "weekly_build", "2026-11-23T15:59:59-08:00"), tip) is False
    assert cal.is_after_first_tip(rec(6, "A", "B", "weekly_build", "2026-11-23T16:00:00-08:00"), tip) is True
    with pytest.raises(cal.CalibrationConflict):
        cal.is_after_first_tip(rec(6, "A", "B", "weekly_build", "2026-11-23"), tip)


def test_latest_per_matchup_week_orders_both_forms_on_one_clock():
    """A naive Phoenix 16:30 (15:30 PT) is EARLIER than an aware 15:45 PT."""
    a = rec(6, "Nick", "Garrett", "weekly_build", "2026-11-23T16:30:00", pa=1.0)
    b = rec(6, "Nick", "Garrett", "weekly_build", "2026-11-23T15:45:00-08:00", pa=2.0)
    kept, _ = cal.latest_per_matchup_week([b, a])
    assert kept[0]["projected_a"] == 2.0


def test_another_seasons_unmarked_weekly_build_raises_in_the_default_resolver():
    resolve = cal.tip_resolver(ROOT)
    with pytest.raises(cal.CalibrationConflict, match="tip times are on file"):
        resolve("2025-26", 3)


def test_the_real_week_6_first_tip_is_the_stored_one():
    """The default resolver reads SCHEDULE.json and the NBA schedule's tips."""
    from modules import price_lock
    assert cal.tip_resolver(ROOT)("2026-27", 6) == price_lock.first_tip(date(2026, 11, 23))


def test_line_record_stamps_the_league_clock_with_its_offset(monkeypatch):
    from modules import league_clock
    monkeypatch.setattr(league_clock, "league_now", lambda: datetime(2026, 11, 30, 21, 5, 7, tzinfo=PT))

    class L:
        manager_a, manager_b, spread_a, over_under = "Nick", "Garrett", -1.5, 3000
        moneyline_a, moneyline_b, win_prob_a, win_prob_b = -105, 105, 51.0, 49.0
        avg_score_a = avg_score_b = 1500.0
    r = cal.line_record(L(), week=7, seed=1, num_simulations=1, engine={"commit": "x", "dirty": False},
                        line_key="k")
    assert r["as_of"] == "2026-11-30T21:05:07-08:00"


def test_the_weekly_builds_records_carry_the_mark_and_an_aware_stamp():
    from modules import report_builder as rb
    src = inspect.getsource(rb._published_line_records)
    assert "league_now()" in src and "datetime.now()" not in src
    assert "cal.AFTER_FIRST_TIP" in src and "cal.week_first_tip(" in src


def _report(tmp_path, lines):
    p = tmp_path / "output" / "stats_report_week5.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"metadata": {"publishable": True, "run_mode": "publish",
                                          "published_lines": lines}}), encoding="utf-8")
    return p


def test_step_9_stamps_published_at_on_the_league_clock_and_marks_a_late_publish(tmp_path, monkeypatch):
    import newsletter_html_generator as nhg
    from modules import league_clock
    monkeypatch.setattr(league_clock, "league_now", lambda: datetime(2026, 11, 23, 16, 30, tzinfo=PT))
    monkeypatch.setattr(cal, "tip_resolver", lambda root: tip)
    early = rec(6, "Nick", "Garrett", "weekly_build", "2026-11-23T09:00:00-08:00", settled=False, mark=False)
    early["line_key"] = "early"
    p = _report(tmp_path, [early])
    out = nhg.log_published_lines(p, sendable=True)
    assert out["logged"] == 1
    logged = cal.load_log(tmp_path)["lines"][0]
    assert logged["published_at"] == "2026-11-23T16:30:00-08:00"
    assert logged[cal.AFTER_FIRST_TIP] is True      # priced before the tip, published after it


def test_step_9_leaves_a_pre_tip_publish_unmarked(tmp_path, monkeypatch):
    import newsletter_html_generator as nhg
    from modules import league_clock
    monkeypatch.setattr(league_clock, "league_now", lambda: datetime(2026, 11, 23, 10, 0, tzinfo=PT))
    monkeypatch.setattr(cal, "tip_resolver", lambda root: tip)
    r = rec(6, "Nick", "Garrett", "weekly_build", "2026-11-23T09:00:00-08:00", settled=False, mark=False)
    nhg.log_published_lines(_report(tmp_path, [r]), sendable=True)
    assert cal.load_log(tmp_path)["lines"][0][cal.AFTER_FIRST_TIP] is False
