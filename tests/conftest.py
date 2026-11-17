"""Pytest configuration: make the project root importable."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# The price lock (modules/price_lock, step 1a). Re-pricing is refused from a
# league day's first tip until the day ends, judged on the wall clock -- so a
# test that re-prices would pass at 10 AM and fail at 8 PM, and every test
# whose fixture schedule has no tip times would refuse. Every test therefore
# sees prices UNLOCKED, unless it is marked real_price_lock: those (all in
# tests/test_price_lock.py) run the real lock, including the check that every
# re-price path consults it. Production code has no such switch.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_price_lock: run against the real price lock, not the test default "
                   "(prices unlocked)")


@pytest.fixture(autouse=True)
def _prices_unlocked_unless_marked(request, monkeypatch):
    if request.node.get_closest_marker("real_price_lock"):
        return
    from modules import price_lock

    def unlocked(now=None, schedule=None):
        return {"locked": False, "league_day": None, "now": None, "first_tip": None,
                "_test_default": True}
    monkeypatch.setattr(price_lock, "status", unlocked)


# ---------------------------------------------------------------------------
# Two tiers (task 50, 11-16; pytest.ini). A builder runs the fast tier,
#     python -m pytest -m "not slow" -n 3 -q -p no:cacheprovider
# and it has to stay fast: tests drift. In a run that deselects "slow", any
# test NOT marked slow whose setup + call takes over FAST_TIER_LIMIT_S fails
# with the time and what to do. The full suite (no -m) is never failed for
# time. tests/test_tiers.py tests this guard.
# ---------------------------------------------------------------------------
# 8 s, not 3 (11-17): under -n 3 on the VM's 2 cores a 0.1 s test took 5.2 s and a
# first git status 4-7 s. The guard is for a test that really belongs in the slow tier
# (those take 10 s and up), not for contention noise.
FAST_TIER_LIMIT_S = 8.0


def fast_tier_run(markexpr):
    """True when the run's -m expression deselects the slow tier."""
    return bool(markexpr) and "not slow" in " ".join(str(markexpr).split())


def tier_overrun(is_slow, markexpr, seconds, limit=FAST_TIER_LIMIT_S):
    """The failure text for a fast-tier test over the limit, else None."""
    if is_slow or not fast_tier_run(markexpr) or seconds <= limit:
        return None
    return (f"this test is not marked slow but took {seconds:.1f} s (setup + call) in the fast "
            f"tier (limit {limit:.0f} s). Make it faster, or mark it @pytest.mark.slow "
            f"(pytest.ini, tests/conftest.py).")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "setup":
        item._tier_setup_s = rep.duration if rep.passed else None
        return
    if rep.when != "call" or not rep.passed or getattr(item, "_tier_setup_s", None) is None:
        return
    msg = tier_overrun(item.get_closest_marker("slow") is not None,
                       item.config.option.markexpr, item._tier_setup_s + rep.duration)
    if msg:
        rep.outcome = "failed"
        rep.longrepr = msg
