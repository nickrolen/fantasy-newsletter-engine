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
