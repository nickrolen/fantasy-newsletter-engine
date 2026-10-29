"""C2/C3 wiring: the engine may fail; the newsletter may not.

Nick, 10-06: "Make the engine raise and assert the newsletter still
generates. A test, not an intention." Step 6 is the pipeline the week-1 bar
("newsletter goes out, numbers are right, nothing new") exists to protect.
"""
import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

import il_state
from modules import advice_runner as ar
from modules import advice_render as rr

ROOT = Path(__file__).parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The real pipeline, with the engine raising
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def failed_report():
    """build_stats_report on the project's own data, C2/C3 forced to raise,
    launch week forced to 1 so the failure must be SAID, not hidden."""
    import modules.data_loader as dl
    import modules.report_builder as rb
    mp = pytest.MonkeyPatch()

    def boom(*a, **k):
        raise RuntimeError("engine exploded on purpose")
    mp.setattr(ar, "build_advice", boom)
    mp.setattr(ar, "ADVICE_PUBLISH_FROM_WEEK", 1)
    mp.setattr(dl, "ADVICE_PUBLISH_FROM_WEEK", 1)
    mp.setattr(rb, "build_season_performers", lambda *a, **k: {})   # no Yahoo in tests
    data = dl.load_all_data(ROOT, current_week=1)
    # The IL state, stated (tests/il_state.py): the weekly suite (Step 0b)
    # runs before the roster sync refreshes data/IL_SLOTS.json.
    data.il_slots = il_state.as_last_synced(2)
    # Priced without tags, stated (Tags.none): the roster plan's stand-in
    # pool needs free agents' tags or this statement, never a silent default.
    from modules.fetch_injury_statuses import Tags as _Tags
    report = rb.build_stats_report(data, 1, run_simulations=True, injury_statuses=_Tags.none(),
                                   num_title_sims=100, num_betting_sims=100, seed=1)
    mp.undo()
    return report


def test_the_report_is_built_when_the_engine_raises(failed_report):
    adv = failed_report["advice"]
    assert adv["ran"] is False and adv["published"] is False
    assert "engine exploded on purpose" in adv["publish_reason"]
    # the rest of the report is intact
    for key in ("matchup_summaries", "rumor_mill", "schedule_strength", "add_budget"):
        assert key in failed_report


def test_section_10_says_it_did_not_run_and_does_not_fall_back(failed_report):
    fmt = _load("format_stats_report")
    md = fmt.format_section_10_rumor_mill(failed_report, fmt.build_lookup_tables(failed_report))
    assert "not in this issue" in md and "engine exploded on purpose" in md
    assert failed_report["rumor_mill"]["trade_ideas"] == []
    assert failed_report["rumor_mill"]["free_agent_targets"] == []


def test_the_newsletter_html_generates_and_carries_the_status(failed_report):
    nhg = _load("newsletter_html_generator")
    sections = [("Matchup Summaries", "A recap."), ("Rumor Mill", "Some rumors.")]
    out = nhg.generate_html("Week 1", "sub", sections, stats_report=failed_report)
    assert "<html" in out and "Some rumors." in out
    assert "engine exploded on purpose" in out


def test_even_a_broken_advice_import_cannot_break_the_report(monkeypatch):
    import modules.report_builder as rb
    monkeypatch.setitem(sys.modules, "modules.advice_runner", None)   # import -> ImportError
    out = rb._run_advice_guarded(None, 5, True, None, None, None, None)
    assert out["ran"] is False and out["status"] == "error"


def test_fast_runs_are_reported_as_skipped_not_silent():
    import modules.report_builder as rb
    out = rb._run_advice_guarded(None, 5, False, None, None, None, None)
    assert out["status"] == "skipped" and "--fast" in out["publish_reason"]


# ---------------------------------------------------------------------------
# The gate -- MARGINAL means talk, not ship
# ---------------------------------------------------------------------------

S = "2026-27"


@pytest.mark.parametrize("gate,week,frm,publish,why", [
    ({"season": S, "band": "CLEAR"}, 3, 3, True, "published"),
    ({"season": S, "band": "CLEAR"}, 2, 3, False, "preview"),
    ({"season": S, "band": "MARGINAL"}, 5, 3, False, "talk, not ship"),
    ({"season": S, "band": "FAIL"}, 5, 3, False, "FAIL"),
    (None, 5, 3, False, "has not been run"),
    ({"season": "2025-26", "band": "CLEAR"}, 5, 3, False, "2025-26"),
    ({"season": S, "band": "CLEAR"}, 5, None, False, "advice_publish_from_week"),
])
def test_publish_only_on_clear_this_season_from_launch(gate, week, frm, publish, why):
    ok, reason = ar.publish_decision(gate, S, week, frm)
    assert ok is publish and why in reason


def test_there_is_no_override_for_a_marginal_premise():
    """Nick, before seeing the number: hold me to that."""
    for fn in (ar.publish_decision, ar.run_advice_safely, ar.build_advice):
        params = set(inspect.signature(fn).parameters)
        assert not params & {"force", "override", "allow_marginal", "ignore_gate"}
    flags = (ROOT / "scripts" / "generate_stats_report.py").read_text().lower()
    for f in ("--allow-marginal", "--force-advice", "--publish-advice", "--ignore-gate"):
        assert f not in flags


def test_validator_records_the_band_where_step_6_reads_it(tmp_path):
    v = _load("validate_marginal_value")
    stats = {"rank_spread": 10, "gap_points": 300.0, "mutual_gain_swaps": 50,
             "swaps_examined": 1683, "free_agents": 100}
    gate = v.write_gate(stats, S, 0, {"Nick": ["a", "b"]}, path=tmp_path / "g.json")
    assert gate["band"] == "MARGINAL" and gate["bands"]["rank_spread"] == "MARGINAL"
    (tmp_path / "config" / "snapshots").mkdir(parents=True)
    (tmp_path / "g.json").replace(tmp_path / ar.GATE_RELPATH)
    read = ar.read_gate(tmp_path)
    assert read["band"] == "MARGINAL" and read["season"] == S
    assert ar.publish_decision(read, S, 5, 3)[0] is False


# ---------------------------------------------------------------------------
# Rendering rules
# ---------------------------------------------------------------------------

def _published():
    return {"ran": True, "published": True, "launched": True, "week": 5, "for_week": 6,
            "bar": {"per_week": 10.0, "se_mult": 2.0, "this_week_floor": 10.0, "season_floor": 100.0},
            "trade_counts": {"not_shown": 3},
            "trades": [{"manager_a": "Nick", "manager_b": "Hayden", "a_sends": ["X"], "b_sends": ["Y"],
                        "a_drops": None, "b_drops": None, "gain_a": 200.0, "se_a": 3.0,
                        "gain_b": 150.0, "se_b": 3.0, "differential": 50.0, "acceptability": 150.0,
                        "cup": None, "keepability_delta_a": -2.0, "keepability_delta_b": 2.0,
                        "keeper_flags": [], "involves_commissioner": True, "first_shown_week": 3}],
            "plans": [{"manager": "Benton", "adds_remaining": 3, "note": "",
                       "this_week": [{"step": 1, "add": "Garland", "drop": "Z", "points": 40.0,
                                      "se": 1.0, "starts": 2.0, "per_week": 40.0,
                                      "contested_with": ["Nick", "Hayden"],
                                      "runner_up": {"add": "Duren", "points": 35.0},
                                      "first_shown_week": 5}],
                       "regular_season": []}]}


def test_a_published_trade_shows_both_gains_and_who_moves_ahead():
    md = rr.render_markdown(_published(), ["Nick", "Hayden", "Benton", "Garrett"])
    assert "Nick +200" in md and "Hayden +150" in md
    assert "Nick moves 50 ahead of Hayden" in md
    assert "other two managers are unchanged" in md
    assert "commissioner is a party" in md
    assert "On the table since week 3" in md
    assert "3 more trades cleared the bar" in md
    low = md.lower()
    for claim in ("fair trade", "both win", "win-win", "everybody wins", "is fair"):
        assert claim not in low, claim


def test_a_contested_add_names_the_others_and_the_fallback():
    out = rr.render_html(_published())
    assert "Also recommended to Nick and Hayden" in out
    assert "if he&#39;s gone: Duren" in out


def test_pre_launch_section_10_is_untouched():
    pre = dict(_published(), published=False, launched=False, publish_reason="preview")
    assert rr.render_markdown(pre, []) == "" and rr.render_html(pre) == ""
    assert "PREVIEW" in rr.render_preview_page(pre)


# HANDOFF_C2C3_GATE (10-29): the first committed gate will be a SAMPLED run.
# Its file carries sampling fields and per-sample intervals; Step 6 must read
# the band from it exactly as from an unsampled one.
@pytest.mark.parametrize("estimates,bands,publish,why", [
    ((40, 45), ("CLEAR", "CLEAR"), True, "published"),
    ((30, 33), ("MARGINAL", "MARGINAL"), False, "talk, not ship"),
    ((12, 15), ("FAIL", "FAIL"), False, "FAIL"),
    ((40, 27), ("CLEAR", "MARGINAL"), False, "UNSTABLE"),
])
def test_step_6_reads_a_sampled_gate_file_from_disk(tmp_path, estimates, bands, publish, why):
    v = _load("validate_marginal_value")
    stats = {"rank_spread": 17, "gap_points": 300.0, "swaps_examined": 1350,
             "free_agents": 115, "mutual_gain_swaps": round(sum(estimates) / 2),
             "samples": [{"examined": 300, "mutual": round(e * 300 / 1350), "estimate": e,
                          "interval_95": [max(0, e - 20), e + 20], "band": b}
                         for e, b in zip(estimates, bands)]}
    (tmp_path / "config" / "snapshots").mkdir(parents=True)
    gate = v.write_gate(stats, S, 2, {"Nick": ["a"]}, path=tmp_path / ar.GATE_RELPATH, sims=3000)
    assert gate["sampling"]["stable"] is (len(set(bands)) == 1)
    read = ar.read_gate(tmp_path)
    assert read == gate                                   # the file round-trips whole
    ok, reason = ar.publish_decision(read, S, 3, 3)
    assert ok is publish and why in reason, reason
