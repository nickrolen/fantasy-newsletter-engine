"""The two test tiers (task 50, 11-16; pytest.ini, tests/conftest.py).

The fast tier, `python -m pytest -m "not slow" -n 3 -q -p no:cacheprovider`,
is what a builder runs in one tool call; the full suite is Nick's before a
push. These pin: the marker is registered; the conftest guard fails an
unmarked test over the limit in the fast tier and never in the full suite;
and the heaviest tests on record (Nick's 11-16 timing) stay marked slow, so
the fast tier cannot quietly grow back to minutes.
"""
import ast
import configparser
from pathlib import Path

import pytest

import conftest

ROOT = Path(__file__).resolve().parents[1]

# Over 5 s on Nick's laptop on 11-16 (junit, -n 4): each must stay slow.
HEAVIEST = [
    "test_closing_line.py::test_the_second_run_is_byte_identical",
    "test_price_lock.py::test_tip_times_in_the_schedule_change_no_line_and_no_title_odds",
    "test_advice_live.py::test_a_nightly_runs_advice_step_on_the_real_state_writes_both_outputs",
    "test_midweek_title_odds.py::test_the_season_pass_prices_the_week_in_progress_as_the_live_line_does",
    "test_state_manifest.py::test_disjoint_changes_merge_on_pull_and_then_push",
    "test_il_returns.py::test_the_real_plans_activation_drops_are_the_one_rules",
    "test_44d_near_ties.py::test_escalation_is_deterministic_on_the_real_state",
    "test_title_odds_run.py::test_margins_are_recorded_beside_results_and_never_drawn",
    "test_claim_check.py::test_clean_published_draft_stays_clean",
]


def _is_slow(rel):
    fname, func = rel.split("::")
    tree = ast.parse((ROOT / "tests" / fname).read_text(encoding="utf-8"))
    marks = [ast.unparse(n.value) for n in tree.body if isinstance(n, ast.Assign)
             and any(getattr(t, "id", None) == "pytestmark" for t in n.targets)]
    if any("pytest.mark.slow" in m for m in marks):
        return True
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == func:
            return any(ast.unparse(d) == "pytest.mark.slow" for d in n.decorator_list)
    raise AssertionError(f"{rel} no longer exists: update HEAVIEST")


def test_the_slow_marker_is_registered():
    ini = configparser.ConfigParser()
    ini.read(ROOT / "pytest.ini", encoding="utf-8")
    assert any(l.strip().startswith("slow:") for l in ini["pytest"]["markers"].splitlines())


@pytest.mark.parametrize("rel", HEAVIEST)
def test_the_heaviest_tests_stay_slow(rel):
    assert _is_slow(rel), f"{rel} took over 5 s on 11-16: it belongs in the slow tier"


@pytest.mark.parametrize("markexpr,fast", [
    ("not slow", True), ("not  slow and not real_price_lock", True), ("(not slow)", True),
    ("", False), (None, False), ("slow", False), ("real_price_lock", False),
])
def test_the_guard_knows_the_fast_tier(markexpr, fast):
    assert conftest.fast_tier_run(markexpr) is fast


def test_an_unmarked_test_over_the_limit_fails_the_fast_tier_only():
    msg = conftest.tier_overrun(False, "not slow", conftest.FAST_TIER_LIMIT_S + 0.1)
    assert msg and "mark it @pytest.mark.slow" in msg
    assert conftest.tier_overrun(False, "", 120.0) is None                 # the full suite
    assert conftest.tier_overrun(True, "not slow", 120.0) is None          # marked slow
    assert conftest.tier_overrun(False, "not slow", conftest.FAST_TIER_LIMIT_S) is None


def test_the_guard_turns_an_overrun_into_a_failure(monkeypatch):
    """The hook itself, on a fake item and report: an unmarked fast-tier test
    whose setup + call is over the limit is reported failed, with the text."""
    class Opt:
        markexpr = "not slow"

    class Cfg:
        option = Opt()

    class Item:
        config = Cfg()
        _tier_setup_s = 2.0

        def get_closest_marker(self, name):
            return None

    class Rep:
        when, passed, duration, outcome, longrepr = "call", True, 1.5, "passed", None

    class Outcome:
        def get_result(self):
            return rep

    rep = Rep()
    gen = conftest.pytest_runtest_makereport.__wrapped__(Item(), None) \
        if hasattr(conftest.pytest_runtest_makereport, "__wrapped__") \
        else conftest.pytest_runtest_makereport(Item(), None)
    next(gen)
    with pytest.raises(StopIteration):
        gen.send(Outcome())
    assert rep.outcome == "failed" and "3.5 s" in rep.longrepr
