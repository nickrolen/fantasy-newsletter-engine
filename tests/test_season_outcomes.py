"""Three titles a season, and they are not interchangeable.

scripts/rollover_leaguehistory.py used to work the champion out by hand:
"the winner of the final week, among whoever won the week before". That is
right for a two-week single-game bracket. From 2026-27 the final two weeks
are the CUP, so it would have written the Cup winner into
LEAGUEHISTORY.xlsx as Playoff Champion -- permanently, in the file that is
the source of truth for titles -- and credited the real weeks 19-21 series
winner with nothing.

Meanwhile scripts/rollup_season_to_history.py had the right computation.
Two scripts, two answers, one of them wrong. They now share
modules/season_outcomes.
"""
import json
from pathlib import Path

import pytest

import modules.data_loader as dl
from modules.season_outcomes import (
    build_matchups, build_standings, cup_champion, league_champion,
    playoff_champion, season_outcomes,
)

PROJECT_ROOT = Path(__file__).parent.parent
MGRS = ["Nick", "Hayden", "Benton", "Garrett"]


def _season(week_winners, weeks=23):
    """Build (records, schedule) where `week_winners` maps week -> winner pairs.

    Each entry is [(winner, loser), (winner, loser)] for that week's two
    matchups. Scores are synthesised so the winner wins.
    """
    records = {"weekly_scores": {m: [] for m in MGRS}}
    schedule = {"weeks": []}
    for wk in range(1, weeks + 1):
        pairs = week_winners.get(wk) or [("Nick", "Hayden"), ("Benton", "Garrett")]
        schedule["weeks"].append({
            "week": wk,
            "matchups": [{"manager_a": w, "manager_b": l} for w, l in pairs],
        })
        for w, l in pairs:
            records["weekly_scores"][w].append({"week": wk, "score": 100.0})
            records["weekly_scores"][l].append({"week": wk, "score": 50.0})
    return records, schedule


# ---------------------------------------------------------------------------
# The 2026-27 shape
# ---------------------------------------------------------------------------

# The real rotation: three pairings, repeated five times over fifteen weeks,
# so every manager plays every other exactly five times.
ROTATION = [
    [("Nick", "Hayden"), ("Benton", "Garrett")],
    [("Nick", "Benton"), ("Hayden", "Garrett")],
    [("Nick", "Garrett"), ("Hayden", "Benton")],
]


@pytest.fixture
def new_format_season():
    """Nick wins the regular season. Hayden wins the bracket. Benton wins the Cup."""
    wins = {}
    # weeks 1-15: Nick beats everyone (15-0), Hayden beats everyone but Nick (10-5)
    for wk in range(1, 16):
        wins[wk] = list(ROTATION[(wk - 1) % 3])
    # weeks 16-18 semifinals: Hayden over Nick, Garrett over Benton
    for wk in range(16, 19):
        wins[wk] = [("Hayden", "Nick"), ("Garrett", "Benton")]
    # weeks 19-21 final: Hayden over Garrett. Third place: Nick over Benton.
    for wk in range(19, 22):
        wins[wk] = [("Hayden", "Garrett"), ("Nick", "Benton")]
    # week 22 cup semis, week 23 cup final: Benton wins it
    wins[22] = [("Benton", "Nick"), ("Garrett", "Hayden")]
    wins[23] = [("Benton", "Garrett"), ("Hayden", "Nick")]
    return _season(wins)


def test_the_three_titles_go_to_three_different_managers(new_format_season):
    records, schedule = new_format_season
    league, playoff, cup, _ = season_outcomes("2026-27", records, schedule)
    assert league == "Nick", "best record over weeks 1-15"
    assert playoff == "Hayden", "won the weeks 19-21 final"
    assert cup == "Benton", "won the weeks 22-23 Cup"


def test_the_old_rule_would_have_named_the_cup_winner(new_format_season):
    """The bug, stated as the thing it would have produced.

    "Winner of the last week among the previous week's winners" picks out of
    weeks 22-23 -- the Cup -- and returns Benton where the Playoff Champion
    is Hayden.
    """
    records, schedule = new_format_season
    rows = build_matchups("2026-27", records, schedule)
    last = max(r["week"] for r in rows)
    prev_winners = {r["winner"] for r in rows if r["week"] == last - 1}
    old_answer = next(
        r["winner"] for r in rows
        if r["week"] == last
        and {r["manager_a"], r["manager_b"]} <= prev_winners)

    assert old_answer == "Benton"
    assert playoff_champion(build_standings("2026-27", rows)) == "Hayden"
    assert old_answer != playoff_champion(build_standings("2026-27", rows))


def test_the_bracket_is_read_as_series_not_single_games(new_format_season):
    """Weeks 16-18 are one best-of-3, not three separate rounds."""
    records, schedule = new_format_season
    st = {r["manager"]: r for r in build_standings("2026-27", *[
        build_matchups("2026-27", records, schedule)][:1])}
    assert st["Hayden"]["playoff_rank"] == 1
    assert st["Garrett"]["playoff_rank"] == 2
    assert st["Nick"]["playoff_rank"] == 3, "won the third-place series"
    assert st["Benton"]["playoff_rank"] == 4


def test_the_league_champion_is_the_regular_season_not_the_bracket(
        new_format_season):
    """Nick goes 15-0, loses the semifinal, and is still the League Champion.

    The title, the draft order and the payouts all come from weeks 1-15. The
    bracket decides a different, secondary trophy.
    """
    records, schedule = new_format_season
    rows = build_matchups("2026-27", records, schedule)
    standings = build_standings("2026-27", rows)
    st = {r["manager"]: r for r in standings}
    assert (st["Nick"]["reg_wins"], st["Nick"]["reg_losses"]) == (15, 0)
    assert (st["Hayden"]["reg_wins"], st["Hayden"]["reg_losses"]) == (10, 5)
    assert league_champion(standings) == "Nick"
    assert st["Nick"]["regular_season_rank"] == 1
    assert st["Nick"]["playoff_rank"] != 1, "he lost the bracket"
    assert playoff_champion(standings) == "Hayden"


def test_a_recorded_cup_winner_wins_over_the_derivation(new_format_season, monkeypatch):
    """The Cup decides next season's keepers, so the config value is the
    record of it; deriving is only the fallback."""
    records, schedule = new_format_season
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2026-27", "Garrett")
    rows = build_matchups("2026-27", records, schedule)
    assert cup_champion("2026-27", rows) == "Garrett"


# ---------------------------------------------------------------------------
# Old seasons must still come out right
# ---------------------------------------------------------------------------

def test_the_archived_2025_26_season_reproduces_what_was_published():
    arc = PROJECT_ROOT / "archive" / "2025-26" / "config"
    if not (arc / "RECORDS.json").is_file():
        pytest.skip("no 2025-26 archive on this machine")
    records = json.loads((arc / "RECORDS.json").read_text(encoding="utf-8"))
    schedule = json.loads((arc / "SCHEDULE.json").read_text(encoding="utf-8"))
    league, playoff, cup, st = season_outcomes("2025-26", records, schedule)
    assert league == "Nick", "the Week 21 newsletter had Nick 17-4 as #1 seed"
    assert playoff == "Garrett"
    assert cup is None, "there was no Cup before 2026-27"
    by = {r["manager"]: r for r in st}
    assert (by["Nick"]["reg_wins"], by["Nick"]["reg_losses"]) == (17, 4)


def test_a_season_with_no_bracket_has_no_playoff_champion():
    """2019-20 stopped at week 19 with nothing after it."""
    matchups = json.loads((PROJECT_ROOT / "data" / "historical" /
                           "all_matchups.json").read_text(encoding="utf-8"))
    rows = [r for r in matchups if r["season"] == "2019-20"]
    st = build_standings("2019-20", rows)
    assert playoff_champion(st) is None
    assert league_champion(st) == "Hayden"


# ---------------------------------------------------------------------------
# One definition, not two
# ---------------------------------------------------------------------------

def test_both_scripts_use_the_shared_definition():
    for name in ("rollup_season_to_history.py", "rollover_leaguehistory.py"):
        src = (PROJECT_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "from modules.season_outcomes import" in src, (
            f"{name} must not define its own idea of who won what")


def test_rollover_no_longer_guesses_from_the_last_two_weeks():
    src = (PROJECT_ROOT / "scripts" / "rollover_leaguehistory.py").read_text(
        encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "prev = last - 1" not in code, (
        "the two-week-bracket assumption is back")
