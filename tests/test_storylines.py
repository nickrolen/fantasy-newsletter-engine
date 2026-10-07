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
