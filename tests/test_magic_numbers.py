"""Magic number computation -- including the co-leader case."""
from modules.simulator_title_odds import compute_magic_numbers

MGRS = ["A", "B", "C", "D"]


def test_sole_leader():
    recs = {"A": (12, 3), "B": (10, 5), "C": (6, 9), "D": (4, 11)}
    odds = {"A": 80.0, "B": 19.0, "C": 1.0, "D": 0.0}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    # lead of 2 over best rival, 6 remaining -> 6 - 2 + 1 = 5
    assert out["A"] == 5


def test_co_leaders_measure_against_each_other():
    recs = {"A": (10, 5), "B": (10, 5), "C": (6, 9), "D": (4, 11)}
    odds = {"A": 45.0, "B": 45.0, "C": 9.0, "D": 1.0}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    # Each co-leader's best rival is the OTHER co-leader (lead = 0),
    # not 3rd place: magic = 6 - 0 + 1 = 7
    assert out["A"] == 7
    assert out["B"] == 7


def test_trailing_manager_has_no_magic_number():
    recs = {"A": (12, 3), "B": (10, 5), "C": (6, 9), "D": (4, 11)}
    odds = {"A": 80.0, "B": 19.0, "C": 1.0, "D": 0.5}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    assert out["B"] is None
    assert out["C"] is None


def test_eliminated_manager_is_none_even_if_tied_for_lead():
    recs = {"A": (8, 7), "B": (8, 7), "C": (8, 7), "D": (8, 7)}
    odds = {"A": 50.0, "B": 49.9, "C": 0.05, "D": 0.05}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    assert out["C"] is None and out["D"] is None
    assert out["A"] == 7 and out["B"] == 7


def test_magic_number_capped_at_remaining_plus_one():
    recs = {"A": (5, 5), "B": (5, 5), "C": (5, 5), "D": (5, 5)}
    odds = {m: 25.0 for m in MGRS}
    out = compute_magic_numbers(recs, 3, odds, MGRS)
    for m in MGRS:
        assert out[m] is not None and 0 <= out[m] <= 4
