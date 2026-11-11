"""Every nightly.py mode whose steps price title odds records them under its
own kind, so every such mode must be a title_odds_run kind (11-11: the first
phone entry's refresh failed with "kind must be one of ... not 'refresh'";
Step 3a/3b's tests stubbed the title-odds step and never reached the check)."""
from modules import nightly, title_odds_run as tor


def test_every_mode_that_prices_title_odds_is_a_kind():
    missing = [m for m in nightly.MODES
               if "title_odds" in nightly.STEPS.get(m, ()) and m not in tor.KINDS]
    assert missing == []


def test_the_refresh_modes_are_kinds():
    for m in nightly.REFRESH_MODES:
        assert m in tor.KINDS, m


def test_an_unknown_kind_still_raises(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="kind must be one of"):
        tor.record(tmp_path, None, run_id="x", produced_by="t", kind="bogus", week=1)
