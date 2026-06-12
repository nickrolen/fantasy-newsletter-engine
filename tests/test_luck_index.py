"""All-play luck index: conservation, ties, and label calibration."""
import math

from modules.data_loader import MANAGERS
from modules.luck_index import (
    compute_luck_index,
    _classify_luck,
    LUCK_NULL_SD_PER_SQRT_WEEK,
    LUCK_Z_THRESHOLD,
    VERY_LUCK_Z_THRESHOLD,
)


def _fixture(num_weeks, score_fn):
    """Build records/schedule fixtures for the configured MANAGERS."""
    m = MANAGERS
    weekly_scores = {mgr: [] for mgr in m}
    weeks = []
    for w in range(1, num_weeks + 1):
        for mgr in m:
            weekly_scores[mgr].append({"week": w, "score": score_fn(mgr, w)})
        weeks.append({
            "week": w,
            "matchups": [
                {"manager_a": m[0], "manager_b": m[1]},
                {"manager_a": m[2], "manager_b": m[3]},
            ],
        })
    return {"weekly_scores": weekly_scores}, {"weeks": weeks}


def test_expected_wins_conserve_to_half_the_games():
    # Distinct scores every week: all-play expected wins must sum to
    # (number of managers / 2) per week -- the conservation property.
    records, schedule = _fixture(6, lambda mgr, w: 1000 + 10 * MANAGERS.index(mgr) + w)
    report = compute_luck_index(records, schedule, through_week=6)
    total_expected = sum(x.expected_wins for x in report.managers.values())
    assert math.isclose(total_expected, 6 * len(MANAGERS) / 2, abs_tol=1e-9)


def test_luck_sums_to_zero():
    records, schedule = _fixture(6, lambda mgr, w: 1000 + 17 * ((MANAGERS.index(mgr) + w) % 4))
    report = compute_luck_index(records, schedule, through_week=6)
    total_luck = sum(x.luck_index for x in report.managers.values())
    assert math.isclose(total_luck, 0.0, abs_tol=1e-9)


def test_tie_splits_credit():
    # Everyone scores the same -> every matchup is a tie -> each manager
    # gets 0.5 wins per week, and luck is exactly 0 for everyone.
    records, schedule = _fixture(4, lambda mgr, w: 1000.0)
    report = compute_luck_index(records, schedule, through_week=4)
    for mgr in MANAGERS:
        assert math.isclose(report.managers[mgr].actual_wins, 2.0, abs_tol=1e-9)
        assert math.isclose(report.managers[mgr].luck_index, 0.0, abs_tol=1e-9)


def test_luck_labels_scale_with_sample_size():
    sigma20 = LUCK_NULL_SD_PER_SQRT_WEEK * math.sqrt(20)
    # Just inside the threshold at 20 games -> Fair
    assert _classify_luck(LUCK_Z_THRESHOLD * sigma20 - 0.01, 20) == "Fair"
    # Just past it -> Lucky
    assert _classify_luck(LUCK_Z_THRESHOLD * sigma20 + 0.01, 20) == "Lucky"
    # Well past the "very" line -> Very Lucky / Very Unlucky
    assert _classify_luck(VERY_LUCK_Z_THRESHOLD * sigma20 + 0.01, 20) == "Very Lucky"
    assert _classify_luck(-(VERY_LUCK_Z_THRESHOLD * sigma20 + 0.01), 20) == "Very Unlucky"


def test_early_season_noise_is_fair():
    # +0.8 wins of "luck" after 3 weeks is ~1.4 sigma of the 3-week null --
    # inside the noise band, so no luck narrative.
    assert _classify_luck(0.8, 3) == "Fair"
    # The key regression guard: at 20 games, +1.2 wins is only ~0.8 sigma
    # and must be Fair (the old fixed +/-1.0 threshold labeled it Lucky --
    # an average team drew a luck label ~50% of the time).
    assert _classify_luck(1.2, 20) == "Fair"
    # And a genuinely extreme early-season run still registers: +2.0 wins
    # in 3 weeks is ~3.5 sigma.
    assert _classify_luck(2.0, 3) == "Very Lucky"
