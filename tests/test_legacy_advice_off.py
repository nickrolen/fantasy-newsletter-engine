"""Section 10's old C2/C3 advice is off until advice v2 ships (Nick, 11-01;
claude/HANDOFF_SECTION10_OFF_AND_BUDGET_WEEK_2026-11-02.md part 1;
claude/ADVICE_V2_DESIGN.md decision 8).

season.legacy_advice is required, "off" or "on". Off: the weekly build never
calls the advice engine, and Section 10 prints exactly one line where the
advice went, "The advice returns with the new engine." Everything else in
Section 10 (Rumor Mill) is what a build with the switch "on" prints.
"""
import importlib.util
import json
from pathlib import Path

import pytest

import il_state
import modules.advice_runner as ar
import modules.data_loader as dl
import modules.report_builder as rb
from modules import advice_render as rr

ROOT = Path(__file__).parent.parent
LINE = "The advice returns with the new engine."


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def off_report():
    """build_stats_report on the project's own data with the switch "off" and
    the launch week forced to 1 (so the old rule would have run and spoken),
    every entry to the advice engine spied on."""
    mp = pytest.MonkeyPatch()
    calls = []

    def spy(name):
        def f(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} called with the advice off")
        return f
    mp.setattr(dl, "SEASON_CONFIG", dict(dl.SEASON_CONFIG, legacy_advice="off"))
    mp.setattr(dl, "ADVICE_PUBLISH_FROM_WEEK", 1)
    mp.setattr(ar, "ADVICE_PUBLISH_FROM_WEEK", 1)
    mp.setattr(ar, "build_advice", spy("build_advice"))
    mp.setattr(ar, "run_advice_safely", spy("run_advice_safely"))
    mp.setattr(rb, "_run_advice_guarded", spy("_run_advice_guarded"))
    mp.setattr(rb, "build_season_performers", lambda *a, **k: {})   # no Yahoo in tests
    data = dl.load_all_data(ROOT, current_week=1)
    data.il_slots = il_state.as_last_synced(2)
    from modules.fetch_injury_statuses import Tags as _Tags
    report = rb.build_stats_report(data, 1, run_simulations=True, injury_statuses=_Tags.none(),
                                   num_title_sims=60, num_betting_sims=100, seed=1)
    mp.undo()
    return report, calls


def test_the_advice_engine_is_never_called_with_the_switch_off(off_report):
    report, calls = off_report
    assert calls == []
    adv = report["advice"]
    assert adv["status"] == "off" and adv["ran"] is False and adv["published"] is False
    assert adv["legacy_advice"] == "off"


def _section10(report):
    fmt = _load("format_stats_report")
    return fmt.format_section_10_rumor_mill(report, fmt.build_lookup_tables(report))


def test_section_10_markdown_has_the_one_line_and_no_c2c3(off_report):
    md = _section10(off_report[0])
    assert md.count(LINE) == 1
    assert LINE + "\n" in md.splitlines(keepends=True)            # a line of its own, as given
    for gone in ("TRADE FINDER", "Waiver plans", "not in this issue", "Section 10 returns",
                 "Trade finder"):
        assert gone not in md


def test_section_10_html_has_the_one_line_and_no_c2c3(off_report):
    nhg = _load("newsletter_html_generator")
    out = nhg.generate_html("Week 1", "sub", [("Rumor Mill", "Some rumors.")],
                            stats_report=off_report[0])
    assert out.count(LINE) == 1 and "Some rumors." in out
    assert "Trade finder" not in out and 'data-viz="advice"' not in out
    assert rr.render_html(off_report[0]["advice"]) == f'<div class="adv adv-status">{LINE}</div>'


def _strip_advice(md: str, advice: dict) -> str:
    block = rr.render_markdown(advice, dl.MANAGERS)
    assert block and block in md
    return md.replace(block, "", 1)


@pytest.mark.parametrize("on_advice", [
    # "on" as it would print: the published engine block ...
    {"ran": True, "published": True, "launched": True, "week": 1, "for_week": 2,
     "bar": {}, "trades": [], "trade_counts": {}, "plans": []},
    # ... and the engine failing (the retired path's status line)
    {"ran": False, "status": "error", "published": False, "launched": True, "week": 1,
     "publish_reason": "RuntimeError: x"}])
def test_the_rest_of_section_10_is_unchanged(off_report, on_advice):
    report = off_report[0]
    on = dict(report, advice=on_advice)
    assert _strip_advice(_section10(report), report["advice"]) == \
        _strip_advice(_section10(on), on_advice)


def test_off_keeps_the_old_trade_ideas_in_the_rumor_mill(off_report):
    """Nick, 11-02 ("B is fine for Rumor Mill"): with the switch "off", C2/C3
    never launched, so the rumor mill's old heuristic trade ideas and
    free-agent targets stay, even past advice_publish_from_week (the fixture
    forces the launch week to 1). With "on", the launch rule still clears
    them from that week (test_advice_wiring)."""
    report = off_report[0]
    assert report["advice"]["launched"] is False
    assert report["rumor_mill"]["trade_ideas"] or report["rumor_mill"]["free_agent_targets"]
    for week in (2, 3, 8, 23):
        assert rb._advice_off(week)["launched"] is False


@pytest.mark.parametrize("cfg", [{}, {"legacy_advice": None}, {"legacy_advice": "OFF"},
                                 {"legacy_advice": True}, {"legacy_advice": "no"}])
def test_a_missing_or_bad_switch_raises(cfg):
    with pytest.raises(ValueError, match="legacy_advice"):
        dl.legacy_advice_on(cfg)


def test_a_bad_switch_stops_the_build_instead_of_printing_as_an_advice_failure(monkeypatch):
    """The switch is read outside _run_advice_guarded (which never raises)."""
    import inspect
    src = inspect.getsource(rb.build_stats_report)
    i, j = src.index("legacy_advice_on()"), src.index("_run_advice_guarded(")
    assert i < j
    assert "legacy_advice_on" not in inspect.getsource(rb._run_advice_guarded)
    monkeypatch.setattr(dl, "SEASON_CONFIG", {"current": "2026-27"})
    with pytest.raises(ValueError, match="legacy_advice is missing"):
        dl.legacy_advice_on()


def test_the_values_and_the_live_config():
    assert dl.legacy_advice_on({"legacy_advice": "on"}) is True
    assert dl.legacy_advice_on({"legacy_advice": "off"}) is False
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text("utf-8"))["season"]
    assert cfg["legacy_advice"] == "off"
    assert "ADVICE_V2_DESIGN.md" in cfg["_legacy_advice_comment"]


def test_the_line_has_no_number_for_the_claim_check():
    """Not "Section 10 returns...": the claim check flagged the 10."""
    import re
    assert rr.OFF_LINE == LINE and not re.search(r"\d", LINE)


def test_the_drafting_prompts_expect_no_advice():
    tpl = (ROOT / "templates" / "newsletter_template.md").read_text("utf-8")
    prm = (ROOT / "templates" / "NEWSLETTER_PROMPTS.md").read_text("utf-8")
    for t in (tpl, prm):
        assert LINE in t and "Section 10 returns" not in t.replace('never "Section 10 returns', "")


def test_the_dry_run_packet_needs_no_preview_with_the_advice_off():
    """build_dryrun_packet used to require advice_preview_weekN.html, which
    the report no longer writes with the switch off."""
    src = (ROOT / "scripts" / "build_dryrun_packet.py").read_text("utf-8")
    assert "legacy_advice_on(" in src
    assert '*([f"advice_preview_week{week}.html"] if advice_on else [])' in src
