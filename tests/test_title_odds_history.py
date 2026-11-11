"""Title-odds history (step 1a; design s.1 decision 4, s.4 step 6, invariant 13).

Every title-odds run appends a row to output/title_odds_history.jsonl -- the
hub's "title odds over time" chart and the audit trail. It is history, never a
score: nothing that scores probabilities may reach it. Append-only; a
malformed file raises and is never truncated. It is league state
(config/STATE_MANIFEST.json).
"""
import ast
import json
import re
from pathlib import Path

import pytest

from modules import title_odds_history as toh
from modules import state_manifest as sm

ROOT = Path(__file__).resolve().parents[1]


def row(run_id="r1", odds=None, **kw):
    base = {"run_id": run_id, "produced_by": "test", "as_of": "2026-11-02T00:05:00-08:00",
            "engine": {"commit": "abc1234", "dirty": False}, "engine_key": "abc1234",
            "seed": 7, "num_simulations": 1000,
            "title_odds": odds or {"Nick": 36.5, "Hayden": 51.25, "Benton": 4.6, "Garrett": 7.65}}
    base.update(kw)
    return base


def test_rows_append_and_read_back_in_order(tmp_path):
    toh.append(tmp_path, row("a"))
    toh.append(tmp_path, row("b", week=2, cup_odds={"Nick": 25.0}))
    got = toh.read(tmp_path)
    assert [r["run_id"] for r in got] == ["a", "b"] and got[1]["cup_odds"] == {"Nick": 25.0}


def test_a_row_is_never_rewritten(tmp_path):
    path = tmp_path / toh.HISTORY_FILE
    toh.append(tmp_path, row("a"))
    first = path.read_bytes()
    toh.append(tmp_path, row("b"))
    assert path.read_bytes().startswith(first)          # appended, the old bytes untouched
    with pytest.raises(toh.HistoryCorrupt, match="already"):
        toh.append(tmp_path, row("a", odds={"Nick": 99.0}))
    assert [r["title_odds"].get("Nick") for r in toh.read(tmp_path)] == [36.5, 36.5]


@pytest.mark.parametrize("bad", ['{"run_id": "x"}\n', "not json\n", "\n",
                                 json.dumps(row("x")) + "\n" + json.dumps(row("y"))])
def test_a_malformed_file_raises_and_is_never_truncated(tmp_path, bad):
    path = tmp_path / toh.HISTORY_FILE
    path.parent.mkdir(parents=True)
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(toh.HistoryCorrupt):
        toh.append(tmp_path, row("z"))
    assert path.read_text(encoding="utf-8") == bad


@pytest.mark.parametrize("change", [{"title_odds": {}}, {"title_odds": {"Nick": "high"}},
                                    {"surprise": 1}])
def test_a_bad_row_is_refused(tmp_path, change):
    with pytest.raises(toh.HistoryCorrupt):
        toh.append(tmp_path, row("a", **change))
    assert not (tmp_path / toh.HISTORY_FILE).exists()


def test_a_row_carries_kind_expected_records_and_playoff_and_cup_odds(tmp_path, monkeypatch):
    """Step 1c: every run's row (title_odds_run.record, the one path) carries
    its kind and each manager's expected record, and playoff and Cup odds as
    {manager: %} when the pass computed them."""
    from modules import calibration_log as cal
    monkeypatch.setattr(cal, "engine_version", lambda base=".": {"commit": "abc1234", "dirty": False})
    r = toh.make_row(base_path=tmp_path, run_id="w2", produced_by="t", seed=5, num_simulations=100,
                     title_odds={"Nick": 40.0, "Hayden": 60.0}, week=2,
                     playoff_odds={"Nick": 45.0, "Hayden": 55.0}, cup_odds={"Nick": 30.0, "Hayden": 70.0},
                     kind="nightly", expected_record={"Nick": (7.5, 7.5, 0.0), "Hayden": (8, 7, 0)})
    toh.append(tmp_path, r)
    back = toh.read(tmp_path)[0]
    assert (back["week"], back["kind"], back["engine_key"]) == (2, "nightly", "abc1234")
    assert back["expected_record"] == {"Nick": [7.5, 7.5, 0.0], "Hayden": [8.0, 7.0, 0.0]}
    assert back["playoff_odds"] == {"Nick": 45.0, "Hayden": 55.0}
    assert back["cup_odds"] == {"Nick": 30.0, "Hayden": 70.0}


def test_the_history_is_league_state():
    man = sm.load(ROOT)
    assert man.contains(str(toh.HISTORY_FILE).replace("\\", "/"))


REFERS = re.compile(r"title_odds_history\.jsonl|title_odds_history\s+import|import\s+title_odds_history"
                    r"|from\s+\.?\.?(modules\.)?title_odds_history|title_odds_history\s+as\b")


def test_nothing_that_scores_probabilities_reaches_the_history():
    """Invariant 13. The only code that names the history file or imports the
    module: the module itself and the weekly build that writes a row. (The
    RECORDS.json key "title_odds_history" is a different, older thing: last
    week's odds for the delta.)"""
    users = sorted(p.name for p in [*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py")]
                   if REFERS.search(p.read_text(encoding="utf-8")))
    # hub_state (step 1b) reads it for display: the hub's odds column and its
    # "title odds over time" chart, which is what decision 4 keeps the history for.
    # title_odds_run (step 1c) is the one path that writes a row, for the
    # weekly build and the nightly run alike.
    # The closing line (step 1c) writes its own row, marked kind "closing".
    # hub_charts (hub polish 3, 48d) draws the rows hub_state reads: the season's
    # title-odds line chart, display only.
    assert users == ["closing_line.py", "generate_stats_report.py", "hub_charts.py", "hub_state.py",
                     "title_odds_history.py", "title_odds_run.py"], users
    for scorer in ("calibration_log.py", "backtest_metrics.py"):
        src = (ROOT / "modules" / scorer).read_text(encoding="utf-8")
        assert "title_odds_history" not in src, scorer


SCORERS = ("calibration_log.py", "backtest_metrics.py")


def test_nothing_that_scores_reads_the_latest_file_or_the_stakes():
    """Invariant 7 of step 1c: calibration never reads the title-odds history,
    the latest file or the stakes (the 1a source pin, extended)."""
    for scorer in SCORERS:
        src = (ROOT / "modules" / scorer).read_text(encoding="utf-8")
        for name in ("title_odds_history", "title_odds_latest", "stakes.json", "title_odds_run",
                     "STAKES_FILE", "LATEST_FILE"):
            assert name not in src, (scorer, name)
    # and the only reader of the latest file is the hub (through
    # title_odds_run.load_latest); the stakes' one reader is the roster plan's
    # injured-drop inputs (task 18b: modules/drop_inputs)
    srcs = {p.name: p.read_text(encoding="utf-8")
            for p in [*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py")]}
    assert {n for n, s in srcs.items() if "load_latest(" in s} == {"hub_state.py", "title_odds_run.py"}
    # (the weekly build names it in a comment and a print, and writes it
    # through title_odds_run.record)
    assert {n for n, s in srcs.items() if "stakes.json" in s} <= {"title_odds_run.py",
                                                                  "generate_stats_report.py",
                                                                  "drop_inputs.py"}
    assert {n for n, s in srcs.items() if "STAKES_FILE" in s} <= {"title_odds_run.py",
                                                                  "generate_stats_report.py",
                                                                  "drop_inputs.py"}


def test_the_weekly_build_writes_a_row_only_on_a_run_of_record():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and "tor.record(" in (ast.get_source_segment(src, n) or "")]
    assert guards, "the history append is not guarded"
    test = ast.get_source_segment(src, guards[-1].test)
    assert "run_sims" in test and "dry_run" in test and "repro" in test
