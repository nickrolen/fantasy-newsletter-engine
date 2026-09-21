"""The regular/playoff boundary is per-season, not a constant.

The engine used one cutoff (week 21) for every season ever played. That is
wrong for three of the nine Yahoo seasons and for the 2026-27 format:

    2019-20  ended wk 19, no bracket        (COVID stoppage)
    2020-21  regular thru wk 16, bracket 17-18
    2021-22  regular thru wk 20, bracket 21-22
    2026-27  regular thru wk 15

The cause is that Yahoo stretches any week containing the All-Star break to
14 days, so a season covers the same calendar in a varying number of fantasy
weeks. Through 2025-26 the durable rule was that the bracket is the last two
weeks. From 2026-27 that rule is retired: the postseason is eight weeks --
best-of-3 series in 16-21 and the Cup in 22-23 -- and the shape comes from
league_config.postseason_format instead.
"""
import json
from pathlib import Path

import pytest

from modules.data_loader import (
    SEASON_STRUCTURE,
    is_regular_season_week,
    regular_season_weeks_for,
    season_had_bracket,
    stage_weeks,
    uses_three_stage_format,
)

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("season,expected", [
    ("2017-18", 21), ("2018-19", 21), ("2019-20", 19), ("2020-21", 16),
    ("2021-22", 20), ("2022-23", 21), ("2023-24", 21), ("2024-25", 21),
    ("2025-26", 21), ("2026-27", 15),
])
def test_regular_season_cutoff_per_season(season, expected):
    assert regular_season_weeks_for(season) == expected


def test_unknown_season_falls_back_to_the_current_value():
    from modules.data_loader import REGULAR_SEASON_WEEKS
    assert regular_season_weeks_for("1999-00") == REGULAR_SEASON_WEEKS


def test_the_short_seasons_classify_their_brackets_correctly():
    # 2020-21: bracket is 17-18
    assert is_regular_season_week("2020-21", 16)
    assert not is_regular_season_week("2020-21", 17)
    assert not is_regular_season_week("2020-21", 18)
    # 2021-22: bracket is 21-22 -- week 21 is NOT regular season here
    assert is_regular_season_week("2021-22", 20)
    assert not is_regular_season_week("2021-22", 21)
    # ...but week 21 IS regular season in a normal 23-week year
    assert is_regular_season_week("2025-26", 21)
    assert not is_regular_season_week("2025-26", 22)


def test_2019_20_had_no_bracket():
    assert season_had_bracket("2019-20") is False
    assert season_had_bracket("2020-21") is True
    assert season_had_bracket("2025-26") is True


def test_structure_matches_the_matchup_data():
    """Check the recorded cutoff against the data rather than trusting it.

    Two different rules apply, and which one holds depends on the season:

      through 2025-26  the postseason was a single-game bracket in the final
                       two weeks, so regular_through == last_week - 2 (or
                       last_week where no bracket was played at all)
      2026-27 onward   the postseason is eight weeks -- a six-week best-of-3
                       bracket then a two-week Cup -- so the cutoff comes
                       from postseason_format and last_week - 2 is wrong

    The old single rule is exactly what this guards: applied to a 23-week
    2026-27 it would put the regular season through week 21.
    """
    matchups = json.loads(
        (PROJECT_ROOT / "data" / "historical" / "all_matchups.json").read_text(encoding="utf-8"))
    last = {}
    for r in matchups:
        s = r["season"]
        last[s] = max(last.get(s, 0), int(r["week"]))
    for season, last_week in sorted(last.items()):
        if uses_three_stage_format(season):
            reg = stage_weeks(season, "regular_season")
            cup = stage_weeks(season, "cup")
            assert regular_season_weeks_for(season) == reg[1]
            assert cup and cup[1] == last_week, (
                f"{season}: last week played is {last_week} but the Cup is "
                f"recorded as ending in week {cup[1] if cup else None}")
        else:
            expected = last_week - 2 if season_had_bracket(season) else last_week
            assert regular_season_weeks_for(season) == expected, (
                f"{season}: last week {last_week}, bracket={season_had_bracket(season)}, "
                f"so regular_through should be {expected}")


def test_every_recorded_season_is_in_the_structure():
    matchups = json.loads(
        (PROJECT_ROOT / "data" / "historical" / "all_matchups.json").read_text(encoding="utf-8"))
    for season in sorted({r["season"] for r in matchups}):
        assert season in SEASON_STRUCTURE, f"{season} missing from season_structure"


def test_playoff_weeks_are_excluded_from_historical_h2h():
    """records_tracker's historical streak walk must use the per-season rule."""
    src = (PROJECT_ROOT / "modules" / "records_tracker.py").read_text(encoding="utf-8")
    assert "is_regular_season_week(season, week" in src, (
        "the historical h2h filter must call is_regular_season_week, not compare "
        "against a single max_regular_season_week")
