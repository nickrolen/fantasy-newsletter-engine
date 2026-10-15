"""An unmeasured consistency profile must not read as a measured one.

Before MIN_WEEKS_FOR_CV weeks, compute_manager_consistency returned a profile
whose numeric fields were untouched zero defaults, and three separate
renderers printed them as statistics: "0.0%" volatility, a "0.00" mean, and a
floor of "0.00 (Wk 0)". That is the project's named signature -- a silent
default making missing data look real -- and it would have been visible in
newsletter 1, where every manager has one week on record.
"""
import collections
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _fmt():
    spec = importlib.util.spec_from_file_location(
        "fsr", ROOT / "scripts" / "format_stats_report.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _mgr(name, insufficient, weeks, cv=0.0, mean=0.0):
    return {"manager": name, "insufficient_data": insufficient,
            "weeks_available": weeks, "cv": cv, "mean_fppg": mean,
            "rating": "" if insufficient else "Steady",
            "floor_fppg": 0.0 if insufficient else 20.0, "floor_week": 0,
            "ceiling_fppg": 0.0 if insufficient else 40.0, "ceiling_week": 0,
            "boom_weeks": 0, "bust_weeks": 0, "recent_trend": "Stable"}


# --- the data layer says so ------------------------------------------------

def test_a_short_series_is_marked_not_zeroed():
    from modules.consistency_score import ManagerConsistency
    mc = ManagerConsistency(manager="Nick")
    assert mc.insufficient_data is False and mc.weeks_available == 0
    mc.weeks_available, mc.insufficient_data = 1, True
    d = mc.to_dict()
    assert d["insufficient_data"] is True and d["weeks_available"] == 1
    # The zeros are still there; the point is that they are now labelled.
    assert d["mean_fppg"] == 0.0


def test_min_weeks_threshold_is_the_gate():
    from modules.consistency_score import MIN_WEEKS_FOR_CV
    assert MIN_WEEKS_FOR_CV == 4


# --- section 7: the volatility table ---------------------------------------

def test_section_7_omits_the_table_when_nobody_has_a_series():
    data = collections.defaultdict(dict, {"consistency_scores": {"managers": {
        m: _mgr(m, True, 1) for m in ("Nick", "Hayden", "Benton", "Garrett")}}})
    out = _fmt().format_section_7_power_rankings(data, collections.defaultdict(dict), None)
    assert "not enough weeks yet (1 on record)" in out
    assert "do NOT write about consistency" in out
    assert "0.0%" not in out and "(Wk 0)" not in out
    assert "Weekly FPPG Volatility" not in out


def test_section_7_keeps_measured_managers_and_names_the_rest():
    data = collections.defaultdict(dict, {"consistency_scores": {"managers": {
        "Nick": _mgr("Nick", False, 6, cv=12.5, mean=33.4),
        "Hayden": _mgr("Hayden", True, 1)}}})
    out = _fmt().format_section_7_power_rankings(data, collections.defaultdict(dict), None)
    assert "Weekly FPPG Volatility" in out
    assert "Nick" in out and "12.5" in out
    assert "No series yet for Hayden" in out
    # Hayden must not appear as a row of zeros.
    assert "| Hayden | 0.0%" not in out


# --- section 3: the per-matchup lines --------------------------------------

def test_section_3_drops_the_matchup_lines_when_either_side_is_thin():
    """Both sides have to be measurable. One thin manager used to print a
    flat-scorer line for both."""
    fmt = _fmt()
    thin = collections.defaultdict(dict, {"consistency_scores": {"managers": {
        "Nick": _mgr("Nick", True, 1), "Hayden": _mgr("Hayden", True, 1)}}})
    out = fmt.format_section_3_betting_lines(thin, collections.defaultdict(dict))
    assert "CV 0.0%" not in out and "avg 0.0 FPPG" not in out
    assert "floor 0.0 / ceiling 0.0" not in out
