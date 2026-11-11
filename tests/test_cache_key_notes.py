"""A notes-only override edit (and the updated_at every edit stamps) leaves the
line's cache key alone, so it neither re-prices nor adds a flat win-% point;
a return-date change still moves it (11-10, Step 3a review)."""
from modules import week_state as ws

BASE = dict(state_hash="s", tags="t", projections="p", schedule="sch", assumptions=(),
            seed=1, num_simulations=10, engine={"commit": "abc", "dirty": False}, il={})
E = {"player_name": "Coby White", "out_weeks": [4], "return_week": 5, "notes": "calf",
     "updated_at": "2026-11-10T10:00:00-08:00"}


def key(entry):
    return ws.line_cache_key(overrides=[entry], **BASE)["key"]


def test_notes_and_timestamp_do_not_move_the_key():
    assert key(E) == key({**E, "notes": "left calf strain", "updated_at": "2026-11-11T14:14:00-08:00"})


def test_a_return_change_still_moves_it():
    assert key(E) != key({**E, "return_week": 6})
