"""E1: the calibration log (HANDOFF_E1_CALIBRATION_2026-10-22).

Every published line, logged at publish time with the ENGINE that produced
it, settled from RECORDS.json when the week closes, and scored by engine
version. The -120.8 backtest baseline was measured on an engine that no
longer exists; a curve that pools lines from both sides of that measures
nothing, so mixing versions has to be asked for.
"""
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest

from modules import backtest_metrics as bm
from modules import calibration_log as cal

ROOT = Path(__file__).parent.parent
ENGINE = {"commit": "abc1234", "dirty": False}
OTHER_ENGINE = {"commit": "def5678", "dirty": False}
MANAGERS = ("Nick", "Hayden", "Benton", "Garrett")


@dataclass
class FakeLine:
    manager_a: str = "Nick"
    manager_b: str = "Benton"
    team_name_a: str = "Luka my Balls"
    team_name_b: str = "Kevin Quran't"
    spread_a: float = 22.0
    over_under: float = 2830.0
    moneyline_a: int = 110
    moneyline_b: int = -130
    win_prob_a: float = 46.3
    win_prob_b: float = 53.7
    avg_score_a: float = 1404.2
    avg_score_b: float = 1426.0
    banked_a: float = 0.0
    banked_b: float = 0.0


def _rec(base_kwargs=None, **over):
    line = FakeLine(**{k: v for k, v in over.items() if k in FakeLine.__annotations__})
    kwargs = dict(week=2, seed=7, num_simulations=500, engine=ENGINE,
                  as_of="2026-11-02T08:00:00", tags={"Kon Knueppel": "O", "X": "HEALTHY"},
                  overrides_governing={"Nick": False, "Benton": True})
    kwargs.update({k: v for k, v in over.items() if k not in FakeLine.__annotations__})
    kwargs.update(base_kwargs or {})
    # stand-in for week_state.line_cache_key: it covers the engine, the seed,
    # the simulation count and the state, so a test record's key does too
    kwargs.setdefault("line_key", "key-{commit}-{dirty}-w{w}-s{s}-n{n}-{h}".format(
        commit=kwargs["engine"].get("commit"), dirty=kwargs["engine"].get("dirty"),
        w=kwargs["week"], s=kwargs["seed"], n=kwargs["num_simulations"],
        h=kwargs.get("state_hash")))
    return cal.line_record(line, **kwargs)


def _week_scores(week, a, b, manager_a="Nick", manager_b="Benton"):
    return {"weekly_scores": {manager_a: [{"week": week, "score": a}],
                              manager_b: [{"week": week, "score": b}]}}


# =============================================================================
# 2 -- a line for every published matchup, every build, no gaps
# =============================================================================

def test_a_record_carries_the_line_its_provenance_and_its_inputs():
    r = _rec()
    assert (r["season"], r["week"], r["matchup_id"]) == (
        __import__("modules.data_loader", fromlist=["x"]).CURRENT_SEASON, 2, "Benton|Nick")
    for field in ("spread_a", "total", "moneyline_a", "moneyline_b", "win_prob_a",
                  "projected_a", "projected_b"):
        assert r[field] is not None, field
    assert (r["engine_commit"], r["engine_dirty"]) == ("abc1234", False)
    assert (r["seed"], r["num_simulations"], r["as_of"]) == (7, 500, "2026-11-02T08:00:00")
    assert r["tags"] == {"Kon Knueppel": "O"}          # HEALTHY is not an input
    assert r["overrides_governing"] == {"Benton": True, "Nick": False}
    assert (r["actual_a"], r["actual_b"], r["settled_at"]) == (None, None, None)


def test_every_published_matchup_is_logged_from_the_builder(tmp_path):
    """report_builder builds the records where the lines are produced, and the
    script writes them -- a dry run must not append to an append-only log."""
    rb = (ROOT / "modules" / "report_builder.py").read_text(encoding="utf-8")
    assert "_published_line_records(" in rb and '"published_lines": published_lines' in rb
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert "cal.append(" not in src and "cal.settle(data.records, base_path)" in src
    assert "Calibration log not touched" in src        # dry run / repro / fast
    gen = (ROOT / "scripts" / "newsletter_html_generator.py").read_text(encoding="utf-8")
    assert "cal.append(lines, root)" in gen             # Step 9 publishes (2026-10-28)
    refresh = (ROOT / "scripts" / "refresh_lines.py").read_text(encoding="utf-8")
    assert "cal.line_record(" in refresh and "source=cal.LIVE_REFRESH" in refresh


# =============================================================================
# 3 and 4 -- append-only, and idempotent
# =============================================================================

def test_the_same_build_twice_appends_once(tmp_path):
    records = [_rec(), _rec(manager_a="Hayden", manager_b="Garrett")]
    assert cal.append(records, tmp_path)["added"] == 2
    again = cal.append(records, tmp_path)
    assert (again["added"], again["skipped"]) == (0, 2)
    assert len(cal.load_log(tmp_path)["lines"]) == 2


def test_a_reissued_line_is_a_new_entry_and_the_first_is_unchanged(tmp_path):
    first = _rec()
    cal.append([first], tmp_path)
    reissue = _rec(as_of="2026-11-04T19:30:00", state_hash="s2",
                   source=cal.LIVE_REFRESH, spread_a=8.0)
    assert cal.append([reissue], tmp_path)["added"] == 1
    lines = cal.load_log(tmp_path)["lines"]
    assert len(lines) == 2
    assert lines[0]["spread_a"] == first["spread_a"] and lines[0]["as_of"] == first["as_of"]
    assert lines[0]["source"] == cal.WEEKLY_BUILD and lines[1]["source"] == cal.LIVE_REFRESH
    assert lines[1]["state_hash"] == "s2"


def test_settlement_is_idempotent_and_never_overwrites(tmp_path):
    cal.append([_rec()], tmp_path)
    records = _week_scores(2, 1500.0, 1450.0)
    first = cal.settle(records, tmp_path, today=date(2026, 11, 9))
    assert (first["settled"], first["unsettled"]) == (1, 0)
    again = cal.settle(records, tmp_path, today=date(2026, 11, 16))
    assert again["settled"] == 0
    line = cal.load_log(tmp_path)["lines"][0]
    assert (line["actual_a"], line["actual_b"]) == (1500.0, 1450.0)
    assert line["settled_at"] == "2026-11-09"           # the first settlement's date
    assert line["actual_source"] == "RECORDS.json weekly_scores"


def test_an_unclosed_week_is_left_alone(tmp_path):
    cal.append([_rec()], tmp_path)
    half = {"weekly_scores": {"Nick": [{"week": 2, "score": 1500.0}]}}   # no opponent yet
    assert cal.settle(half, tmp_path)["settled"] == 0
    assert cal.load_log(tmp_path)["lines"][0]["settled_at"] is None


# =============================================================================
# 1 -- the reality check: actuals reconcile with RECORDS.json
# =============================================================================

def test_settled_actuals_reconcile_with_records_exactly(tmp_path):
    cal.append([_rec()], tmp_path)
    cal.settle(_week_scores(2, 1511.25, 1402.75), tmp_path)
    line = cal.load_log(tmp_path)["lines"][0]
    scores = cal.weekly_scores(_week_scores(2, 1511.25, 1402.75))[2]
    assert line["actual_a"] == scores[line["manager_a"]]
    assert line["actual_b"] == scores[line["manager_b"]]


def test_a_settled_line_that_disagrees_with_records_is_a_loud_failure(tmp_path):
    cal.append([_rec()], tmp_path)
    cal.settle(_week_scores(2, 1500.0, 1450.0), tmp_path)
    with pytest.raises(cal.CalibrationConflict, match="disagree with RECORDS"):
        cal.settle(_week_scores(2, 1500.0, 1399.0), tmp_path)
    # and the log is not quietly corrected
    assert cal.load_log(tmp_path)["lines"][0]["actual_b"] == 1450.0


def test_a_corrupt_log_raises_rather_than_starting_a_new_one(tmp_path):
    path = cal.log_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(cal.CalibrationConflict, match="append-only"):
        cal.load_log(tmp_path)


# =============================================================================
# 5 -- aggregation refuses to mix engine versions unless asked
# =============================================================================

def _settled_pair(tmp_path, engine, week, scores=(1600.0, 1500.0, 1400.0, 1300.0)):
    """Both of a week's matchups, logged and settled. The four scores are
    distinct, so neither matchup is a tie."""
    cal.append([_rec(engine=engine, week=week),
                _rec(engine=engine, week=week, manager_a="Hayden", manager_b="Garrett")], tmp_path)
    cal.settle({"weekly_scores": {m: [{"week": week, "score": scores[i]}]
                                  for i, m in enumerate(MANAGERS)}}, tmp_path)


def test_the_curve_groups_by_engine_and_pools_only_when_asked(tmp_path):
    _settled_pair(tmp_path, ENGINE, 2)
    _settled_pair(tmp_path, OTHER_ENGINE, 3)
    result = cal.curve(tmp_path)
    assert set(result["groups"]) == {"abc1234 / weekly_build", "def5678 / weekly_build"}
    assert all(g["n_lines"] == 2 for g in result["groups"].values())
    mixed = cal.curve(tmp_path, mix_versions=True)
    assert list(mixed["groups"]) == ["mixed (2 engines) / weekly_build"]
    assert mixed["groups"]["mixed (2 engines) / weekly_build"]["n_lines"] == 4
    one = cal.curve(tmp_path, engine="abc1234")
    assert list(one["groups"]) == ["abc1234 / weekly_build"]
    assert one["groups"]["abc1234 / weekly_build"]["n_lines"] == 2


def test_a_dirty_tree_is_its_own_engine_and_so_is_an_unknown_one():
    """On a dirty tree the commit does not identify the simulator, so the
    lines are not pooled with the clean commit's -- and if git cannot say,
    that is a THIRD label, not a quiet "clean". Rounding an unknown answer
    down to the safe-looking one is the mistake this field exists to stop."""
    assert cal.engine_key(_rec(engine={"commit": "abc1234", "dirty": True})) == "abc1234-dirty"
    assert cal.engine_key(_rec(engine=ENGINE)) == "abc1234"
    assert cal.engine_key({"engine_commit": "abc1234", "engine_dirty": None}) == "abc1234-unknown"
    assert cal.engine_key({"engine_commit": None}) == "unknown-unknown"
    live = cal.engine_version(ROOT)
    assert live["commit"], "git could not name the commit"
    assert live["dirty"] in (True, False), "git could not say whether the tree is dirty"


# =============================================================================
# 7 -- an unsettled line never counts
# =============================================================================

def test_an_unsettled_line_is_never_in_the_curve(tmp_path):
    _settled_pair(tmp_path, ENGINE, 2)
    cal.append([_rec(week=4, as_of="2026-11-20T08:00:00")], tmp_path)   # not played yet
    result = cal.curve(tmp_path)
    assert (result["settled"], result["unsettled"]) == (2, 1)
    assert result["groups"]["abc1234 / weekly_build"]["n_lines"] == 2
    assert result["groups"]["abc1234 / weekly_build"]["weeks"] == [2]
    assert cal.settled(cal.load_log(tmp_path)["lines"]) == [
        r for r in cal.load_log(tmp_path)["lines"] if r["week"] == 2]


def test_the_curve_reports_an_empty_log_plainly(tmp_path):
    out = "\n".join(cal.format_curve(cal.curve(tmp_path)))
    assert "empty" in out and "no line has been published yet" in out
    cal.append([_rec()], tmp_path)
    out = "\n".join(cal.format_curve(cal.curve(tmp_path)))
    assert "1 record(s), 0 settled, 1 awaiting a result" in out
    assert "no settled line yet" in out


# =============================================================================
# 6 -- every metric comes from backtest_metrics, with no second copy
# =============================================================================

def test_the_metrics_are_backtest_metrics_and_not_reimplemented(tmp_path):
    src = (ROOT / "modules" / "calibration_log.py").read_text(encoding="utf-8")
    # no second implementation, by name
    for name in ("score_error_stats", "margin_error_stats", "dispersion_ratio",
                 "standardized_residuals", "implied_sigma", "brier_score",
                 "log_loss", "brier_skill_score", "hit_rate"):
        assert f"def {name}" not in src, f"{name} is reimplemented in calibration_log"
        assert f"bm.{name}" in src or name in ("implied_sigma",), name
    # and no hand-rolled statistics either
    assert "import statistics" not in src and "from statistics" not in src
    assert "math.sqrt" not in src

    _settled_pair(tmp_path, ENGINE, 2)
    rows = cal.settled(cal.load_log(tmp_path)["lines"])
    group = cal.curve(tmp_path)["groups"]["abc1234 / weekly_build"]
    projected = [r["projected_a"] for r in rows] + [r["projected_b"] for r in rows]
    actual = [r["actual_a"] for r in rows] + [r["actual_b"] for r in rows]
    def _same(x, y):          # nan == nan, for a t-stat with no spread
        import math
        return {k: ("nan" if isinstance(v, float) and math.isnan(v) else v)
                for k, v in x.items()} == {
                k: ("nan" if isinstance(v, float) and math.isnan(v) else v)
                for k, v in y.items()}
    assert _same(group["level"], bm.score_error_stats(projected, actual))
    assert _same(group["margin"], bm.margin_error_stats(
        [r["projected_a"] - r["projected_b"] for r in rows],
        [r["actual_a"] - r["actual_b"] for r in rows]))
    probs = [r["win_prob_a"] / 100.0 for r in rows]
    outcomes = [1 if r["actual_a"] > r["actual_b"] else 0 for r in rows]
    assert group["probability"]["brier"] == bm.brier_score(probs, outcomes)
    assert group["probability"]["log_loss"] == bm.log_loss(probs, outcomes)


def test_a_tied_week_is_dropped_from_the_probability_scores_and_counted(tmp_path):
    """A regular-season tie is neither a win nor a loss (tiebreaker_rules),
    and the probability scores take 0/1 outcomes."""
    cal.append([_rec(week=2), _rec(week=2, manager_a="Hayden", manager_b="Garrett")], tmp_path)
    cal.settle({"weekly_scores": {"Nick": [{"week": 2, "score": 1500.0}],
                                  "Benton": [{"week": 2, "score": 1500.0}],
                                  "Hayden": [{"week": 2, "score": 1600.0}],
                                  "Garrett": [{"week": 2, "score": 1400.0}]}}, tmp_path)
    prob = cal.curve(tmp_path)["groups"]["abc1234 / weekly_build"]["probability"]
    assert prob["n"] == 1 and prob["ties_dropped"] == 1


# =============================================================================
# where the file lives, and what came before it
# =============================================================================

def test_the_log_lives_under_data_not_config():
    assert cal.LOG_RELPATH.parts[0] == "data"
    assert "calibration" in cal.LOG_RELPATH.parts
    src = (ROOT / "modules" / "calibration_log.py").read_text(encoding="utf-8")
    assert "WORK_BREAKDOWN.md says config/PUBLISHED_LINES.json" in src   # the override, stated
    assert not (ROOT / "config" / "PUBLISHED_LINES.json").exists()


def test_backtest_extract_says_it_is_historical_only():
    doc = (ROOT / "scripts" / "backtest_extract.py").read_text(encoding="utf-8")
    assert "HISTORICAL ONLY" in doc and "calibration_log" in doc
    assert "Do not extend it to new seasons." in doc


def test_nothing_was_backfilled_from_the_b2_test_artifact(tmp_path):
    """No newsletter has gone out this season: the log starts empty, and the
    10-20 live_lines file is a test artifact from a retired engine."""
    real = cal.log_path(ROOT)
    if real.is_file():
        for line in cal.load_log(ROOT)["lines"]:
            assert line["as_of"] >= "2026-10-26", line["as_of"]


def test_the_build_updates_records_before_it_settles():
    """Week N's build records week N's scores (records_tracker mutates
    data.records in place, in the STATE phase) and publishes week N+1's
    lines. Settlement runs after that, so the lines published LAST week
    settle on THIS build -- which is only true while this order holds."""
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    build_at = src.index("report = build_stats_report(")
    settle_at = src.index("cal.settle(data.records, base_path)")
    assert build_at < settle_at
    # the lines are appended at Step 9, after this build and its settlement
    assert "cal.append(" not in src
    rb = (ROOT / "modules" / "report_builder.py").read_text(encoding="utf-8")
    state_phase = rb.index("phase=RECORDS_PHASE_STATE")
    lines_built = rb.index("published_lines = _published_line_records(")
    assert state_phase < lines_built


# =============================================================================
# 2026-10-28 -- identity is the line key, not a wall-clock timestamp
# =============================================================================

def test_the_same_line_twice_appends_once_even_minutes_apart(tmp_path):
    """The 10-23 duplicates: same line, logged 00:36:52 and 00:38:59."""
    first = _rec(as_of="2026-10-23T00:36:52")
    assert cal.append([first], tmp_path)["added"] == 1
    assert cal.append([first], tmp_path)["added"] == 0
    later = _rec(as_of="2026-10-23T00:38:59")
    assert cal.append([later], tmp_path)["added"] == 0
    next_day = _rec(as_of="2026-10-24T09:00:00")
    assert cal.append([next_day], tmp_path)["added"] == 0      # nothing it was priced from moved
    assert len(cal.load_log(tmp_path)["lines"]) == 1


def test_a_record_without_a_line_key_is_refused():
    with pytest.raises(ValueError, match="line_key"):
        _rec(line_key=None)


def test_a_dirty_engine_keeps_lines_apart_only_when_the_numbers_differ(tmp_path):
    dirty = {"commit": "abc1234", "dirty": True}
    assert cal.append([_rec(engine=dirty)], tmp_path)["added"] == 1
    assert cal.append([_rec(engine=dirty, as_of="2026-11-02T09:00:00")], tmp_path)["added"] == 0
    assert cal.append([_rec(engine=dirty, spread_a=19.5)], tmp_path)["added"] == 1


def test_a_legacy_record_keeps_its_old_identity():
    r = _rec()
    r.pop("line_key")
    assert cal.identity(r)[0] == "legacy" and "2026-11-02T08:00:00" in cal.identity(r)


# Through the real writer: refresh_lines on the synthetic week of test_live_lines
@pytest.fixture
def live(monkeypatch, tmp_path):
    import importlib
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "tests"))
    rl = importlib.import_module("refresh_lines")
    from test_live_lines import _data, _teams
    monkeypatch.setattr(rl, "load_all_team_projections", lambda data: _teams())
    monkeypatch.setattr(cal, "engine_version", lambda base=".": dict(ENGINE))

    def run(as_of, statuses=None, overrides=None, **kw):
        data, _ = _data(through=as_of)
        if overrides is not None:
            data.injury_overrides = {"players": overrides}
        return rl.refresh(tmp_path, week=2, as_of=as_of, sims=300, data=data,
                          statuses=statuses or {"Nikola Jokić": "O"}, **kw)
    run.n = lambda: len(cal.load_log(tmp_path)["lines"])
    return run


def test_a_rerun_after_a_pause_appends_nothing_and_a_moved_input_appends(live):
    import time
    from test_live_lines import D, MON
    live(MON, seed=5)
    assert live.n() == 2                                   # two matchups
    time.sleep(1.2)                                        # a later wall-clock second
    out = live(MON)
    assert out["calibration_logged"] == 0 and live.n() == 2
    live(MON, statuses={"Nikola Jokić": "O", "B1": "O"})   # a tag, same day, same state
    assert live.n() == 4
    live(D[2], statuses={"Nikola Jokić": "O", "B1": "O"})  # the state moved: a real re-issue
    assert live.n() == 6
    live(D[2], seed=6, reseed=True, statuses={"Nikola Jokić": "O", "B1": "O"})
    assert live.n() == 8                                   # a new seed


def test_an_input_that_cannot_move_the_line_appends_nothing_and_one_that_can_does(live):
    from test_live_lines import MON
    live(MON, seed=5)
    live(MON, overrides=[{"player_name": "N2", "out_weeks": [9]}])        # governs week 9 only
    live(MON, overrides=[{"player_name": "Not Rostered", "out_weeks": [2]}])
    assert live.n() == 2
    live(MON, overrides=[{"player_name": "N2", "out_weeks": [2]}])        # governs this week
    assert live.n() == 4


# =============================================================================
# HANDOFF_CURVE_GROUPING (Nick 10-28): one outcome, one observation -- the
# curve scores the latest published line per matchup-week and source
# =============================================================================

PAIRS = (("Nick", "Benton"), ("Hayden", "Garrett"))
SCORES = {2: (1600.0, 1500.0, 1400.0, 1300.0), 3: (1350.0, 1550.0, 1610.0, 1420.0),
          4: (1480.0, 1390.0, 1300.0, 1525.0)}


def _refreshes(week, n, engine=ENGINE, source=cal.WEEKLY_BUILD, drift=0.0, start=0):
    """n records per matchup of `week`, a day apart, as the midnight refresh
    logs them: a new line key each time, the projection drifting by `drift`."""
    out = []
    for i in range(start, start + n):
        for a, b in PAIRS:
            out.append(_rec(engine=engine, week=week, manager_a=a, manager_b=b, source=source,
                            as_of=(date(2026, 10, 26) + timedelta(days=7 * (week - 2) + i)
                                   ).isoformat() + "T00:05:00",
                            line_key=f"{engine['commit']}-{source}-w{week}-{a}-{i}",
                            avg_score_a=1404.2 + drift * i, spread_a=22.0 - drift * i))
    return out


def _settle_weeks(tmp_path, weeks):
    cal.settle({"weekly_scores": {m: [{"week": w, "score": SCORES[w][i]} for w in weeks]
                                  for i, m in enumerate(MANAGERS)}}, tmp_path)


def test_seven_records_per_matchup_score_as_one_line_and_the_se_is_one_records(tmp_path):
    dup, single = tmp_path / "dup", tmp_path / "single"
    for w in (2, 3, 4):
        cal.append(_refreshes(w, 7), dup)
        cal.append(_refreshes(w, 1, start=6), single)          # just the latest
    _settle_weeks(dup, (2, 3, 4))
    _settle_weeks(single, (2, 3, 4))
    d = cal.curve(dup)["groups"]["abc1234 / weekly_build"]
    s = cal.curve(single)["groups"]["abc1234 / weekly_build"]
    assert (d["n_records"], d["n_lines"]) == (42, 6)
    assert (s["n_records"], s["n_lines"]) == (6, 6)
    for k in ("level", "margin", "probability", "dispersion"):
        assert d[k] == s[k], k
    assert all(c["of"] == 7 for c in d["collapsed"])


def test_the_latest_as_of_is_scored_and_a_tie_goes_to_the_later_appended(tmp_path):
    early = _rec(as_of="2026-10-27T00:05:00", line_key="k1", avg_score_a=1300.0)
    late = _rec(as_of="2026-10-30T00:05:00", line_key="k2", avg_score_a=1350.0)
    earlier_appended_last = _rec(as_of="2026-10-28T00:05:00", line_key="k3", avg_score_a=1999.0)
    kept, info = cal.latest_per_matchup_week([early, late, earlier_appended_last])
    assert kept == [late] and info["collapsed"][0]["of"] == 3 and info["ties"] == []
    # a tie: the later-appended wins, and different numbers are said
    t1 = _rec(as_of="2026-10-30", line_key="t1", avg_score_a=1350.0)
    t2 = _rec(as_of="2026-10-30", line_key="t2", avg_score_a=1360.0)
    kept, info = cal.latest_per_matchup_week([t1, t2])
    assert kept == [t2] and "different published numbers" in info["ties"][0]
    same = _rec(as_of="2026-10-30", line_key="t3", avg_score_a=1360.0)
    kept, info = cal.latest_per_matchup_week([t2, same])
    assert kept == [same] and info["ties"] == []          # identical numbers: nothing to say
    # a bare date is that day's midnight: an 08:00 record on it is later
    kept, _ = cal.latest_per_matchup_week([_rec(as_of="2026-10-30T08:00:00", line_key="x"),
                                           _rec(as_of="2026-10-30", line_key="y")])
    assert kept[0]["line_key"] == "x"


def test_a_weekly_build_line_and_a_live_refresh_line_are_separate_curves(tmp_path):
    """Nick 10-28: a group is engine x source. Two products' lines on one
    matchup-week share one outcome, so they are never pooled -- the weekly
    build's curve is the newsletter's line, the live refresh's the live page's."""
    cal.append(_refreshes(2, 1) + _refreshes(2, 5, source=cal.LIVE_REFRESH, start=1), tmp_path)
    _settle_weeks(tmp_path, (2,))
    groups = cal.curve(tmp_path)["groups"]
    assert set(groups) == {"abc1234 / weekly_build", "abc1234 / live_refresh"}
    wk, live = groups["abc1234 / weekly_build"], groups["abc1234 / live_refresh"]
    assert (wk["n_records"], wk["n_lines"]) == (2, 2)
    assert (live["n_records"], live["n_lines"]) == (10, 2)
    assert sorted(c["of"] for c in live["collapsed"]) == [5, 5]


def test_one_record_from_each_source_lands_in_two_groups_of_one_line(tmp_path):
    cal.append([_rec(as_of="2026-10-26T08:00:00", line_key="build"),
                _rec(as_of="2026-10-29T00:05:00", line_key="live", source=cal.LIVE_REFRESH)],
               tmp_path)
    cal.settle(_week_scores(2, 1500.0, 1450.0), tmp_path)
    for mode in ({}, {"mix_versions": True}, {"engine": "abc1234"}):
        groups = cal.curve(tmp_path, **mode)["groups"]
        assert len(groups) == 2, mode
        assert sorted(g["n_lines"] for g in groups.values()) == [1, 1], mode
        assert {k.rpartition(" / ")[2] for k in groups} == {cal.WEEKLY_BUILD, cal.LIVE_REFRESH}


def test_two_engines_on_one_week_stay_apart_each_deduplicated(tmp_path):
    cal.append(_refreshes(2, 3) + _refreshes(2, 4, engine=OTHER_ENGINE), tmp_path)
    _settle_weeks(tmp_path, (2,))
    groups = cal.curve(tmp_path)["groups"]
    a, b = groups["abc1234 / weekly_build"], groups["def5678 / weekly_build"]
    assert (a["n_records"], a["n_lines"]) == (6, 2)
    assert (b["n_records"], b["n_lines"]) == (8, 2)
    mixed = cal.curve(tmp_path, mix_versions=True)["groups"]["mixed (2 engines) / weekly_build"]
    assert (mixed["n_records"], mixed["n_lines"]) == (14, 4)   # not across engines


def test_the_summary_names_the_count_it_collapsed_from(tmp_path):
    cal.append(_refreshes(2, 7), tmp_path)
    _settle_weeks(tmp_path, (2,))
    out = "\n".join(cal.format_curve(cal.curve(tmp_path)))
    assert "14 record(s), 14 settled" in out
    assert ("engine abc1234, weekly_build (the newsletter's line): 2 line(s) from 14 settled "
            "record(s)") in out
    assert "week 2 (weekly_build): Benton|Nick latest of 7, Garrett|Hayden latest of 7" in out


def test_settle_over_a_duplicated_log_is_idempotent_and_still_catches_a_real_conflict(tmp_path):
    cal.append(_refreshes(2, 7), tmp_path)
    _settle_weeks(tmp_path, (2,))
    before = cal.log_path(tmp_path).read_bytes()
    again = cal.settle({"weekly_scores": {m: [{"week": 2, "score": SCORES[2][i]}]
                                          for i, m in enumerate(MANAGERS)}}, tmp_path)
    assert again["settled"] == 0 and cal.log_path(tmp_path).read_bytes() == before
    wrong = {"weekly_scores": {m: [{"week": 2, "score": SCORES[2][i] + (5 if m == "Nick" else 0)}]
                               for i, m in enumerate(MANAGERS)}}
    with pytest.raises(cal.CalibrationConflict, match=r"Nick v Benton.*\(7 records\)") as e:
        cal.settle(wrong, tmp_path)
    assert "Hayden" not in str(e.value)
    assert cal.log_path(tmp_path).read_bytes() == before
