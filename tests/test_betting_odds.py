"""Fair-odds conversion sanity."""
from modules.simulator_betting import probability_to_american_odds


def test_even_money_is_minus_100():
    assert probability_to_american_odds(0.5) == -100


def test_favorites_negative_underdogs_positive():
    assert probability_to_american_odds(0.75) < -100
    assert probability_to_american_odds(0.25) > 100


def test_extremes_are_capped():
    assert probability_to_american_odds(0.0) == 10000
    assert probability_to_american_odds(1.0) == -10000
