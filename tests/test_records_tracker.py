"""Top-10 leaderboard mechanics and weekly-score idempotency."""
from modules.data_loader import MANAGERS
from modules.records_tracker import update_top10_list, update_weekly_scores


def test_insert_sorts_highest_first():
    lst = [{"player_name": "A", "season": "s", "week": 1, "fantasy_points": 50.0}]
    update_top10_list(lst, {"player_name": "B", "season": "s", "week": 2,
                            "fantasy_points": 70.0}, "fantasy_points")
    assert [e["player_name"] for e in lst] == ["B", "A"]


def test_lowest_first_direction():
    lst = [{"player_name": "A", "season": "s", "week": 1, "fantasy_points": 50.0}]
    update_top10_list(lst, {"player_name": "B", "season": "s", "week": 2,
                            "fantasy_points": 30.0}, "fantasy_points", reverse=False)
    assert [e["player_name"] for e in lst] == ["B", "A"]


def test_trims_to_ten():
    lst = []
    for i in range(12):
        update_top10_list(lst, {"player_name": f"P{i}", "season": "s", "week": i,
                                "fantasy_points": float(100 - i)}, "fantasy_points")
    assert len(lst) == 10
    assert lst[0]["fantasy_points"] == 100.0


def test_same_identity_replaces_not_duplicates():
    lst = []
    entry = {"player_name": "A", "season": "s", "week": 3, "fantasy_points": 55.0}
    update_top10_list(lst, dict(entry), "fantasy_points")
    update_top10_list(lst, dict(entry, fantasy_points=60.0), "fantasy_points")
    assert len(lst) == 1
    assert lst[0]["fantasy_points"] == 60.0


def test_two_matchups_same_week_both_survive():
    # Regression: blowout/closest entries are identified by winner/loser;
    # before the fix, two matchups in the same (season, week) collided and
    # evicted each other.
    lst = []
    update_top10_list(lst, {"season": "s", "week": 5, "winner": "A", "loser": "B",
                            "margin": 120.0}, "margin")
    update_top10_list(lst, {"season": "s", "week": 5, "winner": "C", "loser": "D",
                            "margin": 80.0}, "margin")
    assert len(lst) == 2


def test_weekly_scores_idempotent_rerun():
    records = {"weekly_scores": {m: [] for m in MANAGERS}}
    scores = {m: 1000.0 + i for i, m in enumerate(MANAGERS)}
    update_weekly_scores(records, 7, scores)
    update_weekly_scores(records, 7, scores)  # re-run must not duplicate
    for m in MANAGERS:
        entries = [e for e in records["weekly_scores"][m] if e["week"] == 7]
        assert len(entries) == 1
