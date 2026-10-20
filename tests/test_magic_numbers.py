"""Magic number computation -- including the co-leader case."""
from modules.data_loader import Record
from modules.simulator_title_odds import compute_magic_numbers

MGRS = ["A", "B", "C", "D"]


def test_sole_leader():
    recs = {"A": Record(12, 3), "B": Record(10, 5), "C": Record(6, 9), "D": Record(4, 11)}
    odds = {"A": 80.0, "B": 19.0, "C": 1.0, "D": 0.0}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    # lead of 2 over best rival, 6 remaining -> 6 - 2 + 1 = 5
    assert out["A"] == 5


def test_co_leaders_measure_against_each_other():
    recs = {"A": Record(10, 5), "B": Record(10, 5), "C": Record(6, 9), "D": Record(4, 11)}
    odds = {"A": 45.0, "B": 45.0, "C": 9.0, "D": 1.0}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    # Each co-leader's best rival is the OTHER co-leader (lead = 0),
    # not 3rd place: magic = 6 - 0 + 1 = 7
    assert out["A"] == 7
    assert out["B"] == 7


def test_trailing_manager_has_no_magic_number():
    recs = {"A": Record(12, 3), "B": Record(10, 5), "C": Record(6, 9), "D": Record(4, 11)}
    odds = {"A": 80.0, "B": 19.0, "C": 1.0, "D": 0.5}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    assert out["B"] is None
    assert out["C"] is None


def test_eliminated_manager_is_none_even_if_tied_for_lead():
    recs = {"A": Record(8, 7), "B": Record(8, 7), "C": Record(8, 7), "D": Record(8, 7)}
    odds = {"A": 50.0, "B": 49.9, "C": 0.05, "D": 0.05}
    out = compute_magic_numbers(recs, 6, odds, MGRS)
    assert out["C"] is None and out["D"] is None
    assert out["A"] == 7 and out["B"] == 7


def test_magic_number_capped_at_remaining_plus_one():
    recs = {"A": Record(5, 5), "B": Record(5, 5), "C": Record(5, 5), "D": Record(5, 5)}
    odds = {m: 25.0 for m in MGRS}
    out = compute_magic_numbers(recs, 3, odds, MGRS)
    for m in MGRS:
        assert out[m] is not None and 0 <= out[m] <= 4


def test_a_half_game_lead_rounds_the_magic_number_up():
    """A T makes the lead a half game: 7-2-1 (7.5) over 7-3 (7.0), 4 left.
    The rival's best is 11.0; the leader needs to be strictly above it:
    7.5 + x > 11 -> x = 4 (whole results), i.e. floor(4 - 0.5) + 1."""
    recs = {"A": Record(7, 2, 1), "B": Record(7, 3), "C": Record(3, 7), "D": Record(2, 8)}
    odds = {"A": 60.0, "B": 39.0, "C": 0.5, "D": 0.5}
    assert compute_magic_numbers(recs, 4, odds, MGRS)["A"] == 4
