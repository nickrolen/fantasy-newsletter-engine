"""E1 logs a line when it PUBLISHES -- Step 9, the page -- not when Step 6
builds it (HANDOFF_LOG_AT_PUBLISH_2026-10-28).

Step 7 runs the report more than once. When an input moves between runs each
run is a genuinely different line with its own line_key, and none of them was
seen by anybody until the page is built. A superseded draft was often
superseded because its number looked wrong, so logging drafts biases the
record E1 keeps.
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from modules import calibration_log as cal

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_calibration_log import _rec  # noqa: E402


def _gen():
    spec = importlib.util.spec_from_file_location(
        "newsletter_html_generator", ROOT / "scripts" / "newsletter_html_generator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(tmp_path, key, publishable=True, run_mode="publish", name="stats_report_week2.json"):
    """A Step 6 report as it reaches Step 9: two matchups, built with line_key `key`."""
    lines = [_rec(line_key=f"{key}-a"),
             _rec(manager_a="Hayden", manager_b="Garrett", line_key=f"{key}-b")]
    meta = {"published_lines": lines, "run_mode": run_mode}
    if publishable is not None:
        meta["publishable"] = publishable
    path = tmp_path / "output" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metadata": meta}), encoding="utf-8")
    return path


def _logged(tmp_path):
    if not cal.log_path(tmp_path).is_file():
        return []
    return cal.load_log(tmp_path)["lines"]


# 1 -- Step 6 produces, Step 9 publishes
def test_step_6_never_appends_and_only_the_built_page_is_logged(tmp_path):
    tree = ast.parse((ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "append"
                   and getattr(getattr(n.func, "value", None), "id", None) == "cal"
                   for n in ast.walk(tree)), "Step 6 appends to the calibration log"
    # two Step 6 runs, an input moved in between: two different lines, nothing logged
    _report(tmp_path, "draft-1")
    second = _report(tmp_path, "draft-2")
    assert _logged(tmp_path) == []
    out = _gen().log_published_lines(str(second), sendable=True)
    assert out["logged"] == 2
    keys = sorted(r["line_key"] for r in _logged(tmp_path))
    assert keys == ["draft-2-a", "draft-2-b"]
    assert all(r["source"] == cal.WEEKLY_BUILD and r["published_at"] for r in _logged(tmp_path))


# 2 -- the page twice logs once
def test_building_the_page_twice_from_one_report_logs_once(tmp_path):
    gen = _gen()
    path = _report(tmp_path, "final")
    assert gen.log_published_lines(str(path), sendable=True)["logged"] == 2
    again = gen.log_published_lines(str(path), sendable=True)
    assert (again["logged"], again["skipped"]) == (0, 2)
    assert len(_logged(tmp_path)) == 2


# 3 -- a failed write logs nothing
def test_a_failed_html_write_logs_nothing(tmp_path, monkeypatch):
    gen = _gen()
    path = _report(tmp_path, "final")
    draft = tmp_path / "WEEK2_DRAFT.md"
    draft.write_text("# draft", encoding="utf-8")
    monkeypatch.setattr(gen, "check_sections_complete", lambda text: None)

    def fail(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(gen, "build_newsletter_html", fail)
    monkeypatch.setattr(sys, "argv", ["x", "--input", str(draft), "--output",
                                      str(tmp_path / "output" / "WEEK2.html"),
                                      "--stats-report", str(path)])
    with pytest.raises(OSError):
        gen.main()
    assert _logged(tmp_path) == []


def test_main_logs_after_a_clean_build_and_not_after_a_failed_table_check(tmp_path, monkeypatch):
    gen = _gen()
    path = _report(tmp_path, "final")
    draft = tmp_path / "WEEK2_DRAFT.md"
    draft.write_text("# draft", encoding="utf-8")
    page = tmp_path / "output" / "WEEK2.html"

    def build(md, out, *a, **k):
        Path(out).write_text("<html></html>", encoding="utf-8")
        return out
    monkeypatch.setattr(gen, "check_sections_complete", lambda text: None)
    monkeypatch.setattr(gen, "build_newsletter_html", build)
    argv = ["x", "--input", str(draft), "--output", str(page), "--stats-report", str(path)]
    monkeypatch.setattr(gen, "table_check", lambda p: 1)          # "do not send this page"
    monkeypatch.setattr(sys, "argv", argv)
    assert gen.main() == 1 and _logged(tmp_path) == []
    monkeypatch.setattr(sys, "argv", argv + ["--no-log"])
    monkeypatch.setattr(gen, "table_check", lambda p: 0)
    assert gen.main() == 0 and _logged(tmp_path) == []           # a preview build
    monkeypatch.setattr(sys, "argv", argv)
    assert gen.main() == 0 and len(_logged(tmp_path)) == 2


# 4 -- the repro / --fast / --dry-run guard travels with the report
@pytest.mark.parametrize("mode", ["repro", "fast", "dry-run"])
def test_a_report_step_6_did_not_mark_publishable_is_refused(tmp_path, mode):
    path = _report(tmp_path, "x", publishable=False, run_mode=mode)
    out = _gen().log_published_lines(str(path), sendable=True)
    assert out["logged"] == 0 and mode in out["why_not"]
    assert _logged(tmp_path) == []


def test_an_unmarked_report_is_refused_rather_than_assumed_publishable(tmp_path):
    path = _report(tmp_path, "x", publishable=None, run_mode=None)
    out = _gen().log_published_lines(str(path), sendable=True)
    assert out["logged"] == 0 and "not publishable" in out["why_not"]


def test_step_6_marks_each_run_mode():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert '''run_mode = ("dry-run" if args.dry_run else "repro" if args.repro
                else "fast" if args.fast else "publish")''' in src
    assert 'report["metadata"]["publishable"] = run_mode == "publish"' in src
    # stamped before the report is saved, or Step 9 would read an unmarked file
    assert src.index('report["metadata"]["publishable"]') < src.index("save_stats_report(report, output_path)")


# 5 -- the live line still logs at refresh time: it goes straight onto the page
def test_refresh_lines_still_logs_at_refresh_time():
    src = (ROOT / "scripts" / "refresh_lines.py").read_text(encoding="utf-8")
    assert "cal.append([" in src and "source=cal.LIVE_REFRESH" in src
    # and behaviourally: test_calibration_log.test_a_rerun_after_a_pause_appends_nothing_and_a_moved_input_appends
