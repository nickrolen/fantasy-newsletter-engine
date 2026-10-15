"""Typed storylines render exactly the alert strings they replaced."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import format_stats_report as fmt  # noqa: E402
from modules.storylines import FAMILY, compute_storylines  # noqa: E402

OUT = ROOT / "archive" / "2025-26" / "output"
GOLDEN = json.loads((ROOT / "tests" / "fixtures" /
                     "storyline_alerts_2025-26.json").read_text())


@pytest.mark.parametrize("week", range(16, 24))
def test_alert_strings_unchanged(week):
    d = json.loads((OUT / f"stats_report_week{week}.json").read_text())
    lk = fmt.build_lookup_tables(d)
    pred = fmt.load_last_week_betting_predictions(week, OUT)
    assert fmt.compute_storyline_alerts(d, lk, pred) == \
        GOLDEN[str(week)]["with_predictions"]
    assert fmt.compute_storyline_alerts(d, lk, None) == \
        GOLDEN[str(week)]["without"]


def test_every_storyline_is_typed():
    for week in range(16, 24):
        d = json.loads((OUT / f"stats_report_week{week}.json").read_text())
        pred = fmt.load_last_week_betting_predictions(week, OUT)
        for s in compute_storylines(d, pred, "2025-26",
                                    ["Nick", "Hayden", "Benton", "Garrett"]):
            assert s.kind in FAMILY and s.managers and s.magnitude


# ---------------------------------------------------------------------------
# A record claim needs a record on file
# ---------------------------------------------------------------------------

def test_no_record_on_file_makes_no_record_claim():
    """The week-16 report published "Nick's 7-game win streak is a new
    personal best (previous: 0 in )".

    at_win defaulted length to 0 and season to "", which made cur > at true
    for any streak of 3 or more and printed the empty parenthetical. The
    blowout claims in the same function already require a stored record
    before asserting one; the streak claims now do too.
    """
    from modules.storylines import compute_storylines
    data = {
        "metadata": {"week": 16},
        "current_streaks": {"Nick": {"win_streak": 7, "loss_streak": 0}},
        "all_time_records": {},          # nothing on file
    }
    out = compute_storylines(data, None, "2026-27", ["Nick"])
    text = " ".join(s.text for s in out)
    assert "personal best" not in text
    assert "ALL-TIME RECORD" not in text
    assert "previous: 0" not in text and "in )" not in text
    assert "record of 0" not in text


def test_a_real_record_is_still_claimed():
    """The guard must not silence a genuine all-time streak."""
    from modules.storylines import compute_storylines
    data = {
        "metadata": {"week": 16},
        "current_streaks": {"Nick": {"win_streak": 7, "loss_streak": 0}},
        "all_time_records": {
            "longest_win_streaks": {"Nick": {"length": 5, "season": "2021-22"}}},
    }
    out = compute_storylines(data, None, "2026-27", ["Nick"])
    text = " ".join(s.text for s in out)
    assert "personal best" in text and "2021-22" in text and "previous: 5" in text
