"""Per-entity lore valence (modules/lore_valence.py).

The bug this exists to prevent: valence was one string per entry, and two
approved entries name two managers with opposite sign --

    "Nick has been known to reach in trades, especially when dealing with
     Benton."                                     valence: "negative"

-- so a by-manager tally counted it as a negative for Benton, whom it
flatters. Measured 10-15, the scalar tally reported Benton 2 positive /
4 negative and Garrett 3/3; the true figures are Benton 3/3 and Garrett 2/4,
which moved the whole target of the lore work.
"""
import json
from pathlib import Path

import pytest

from modules import lore_valence as LV
from modules.data_loader import MANAGERS

ROOT = Path(__file__).resolve().parent.parent


def _e(eid, entities, valence):
    return {"id": eid, "entities": entities, "valence": valence}


def test_managers_in_ignores_players_and_keeps_manager_order():
    e = _e("x", ["Nikola Jokic", "Hayden"], {"Hayden": "positive"})
    assert LV.managers_in(e) == ["Hayden"]
    both = _e("y", ["Benton", "Nick"], {})
    assert LV.managers_in(both) == [m for m in MANAGERS if m in ("Nick", "Benton")]


def test_a_mapping_is_read_per_manager():
    e = _e("x", ["Nick", "Benton"], {"Nick": "negative", "Benton": "positive"})
    assert LV.valence_for(e, "Nick") == "negative"
    assert LV.valence_for(e, "Benton") == "positive"
    assert LV.valence_for(e, "Hayden") is None


def test_a_scalar_is_honoured_only_on_a_single_manager_entry():
    """Retired form. Still readable so a half-migrated file does not raise."""
    e = _e("x", ["Hayden"], "positive")
    assert LV.valence_for(e, "Hayden") == "positive"
    assert LV.valence_for(e, "Nick") is None


def test_a_scalar_on_a_two_manager_entry_is_refused():
    """THE regression guard. The scalar cannot say which manager it meant,
    so it must not be spread across both."""
    e = _e("written-nick-reaches", ["Nick", "Benton"], "negative")
    assert LV.valence_for(e, "Nick") is None
    assert LV.valence_for(e, "Benton") is None
    assert LV.balance([e])["Benton"]["negative"] == 0
    assert ("written-nick-reaches", "Benton") in LV.missing_labels(e for e in [e])


def test_an_unknown_label_is_not_a_label():
    assert LV.valence_for(_e("x", ["Nick"], {"Nick": "spicy"}), "Nick") is None
    assert LV.valence_for(_e("y", ["Nick"], "spicy"), "Nick") is None


def test_balance_counts_opposite_signs_on_one_entry():
    entries = [
        _e("a", ["Nick", "Benton"], {"Nick": "negative", "Benton": "positive"}),
        _e("b", ["Nick", "Garrett"], {"Nick": "positive", "Garrett": "negative"}),
        _e("c", ["Hayden"], {"Hayden": "neutral"}),
    ]
    bal = LV.balance(entries)
    assert bal["Nick"]["negative"] == 1 and bal["Nick"]["positive"] == 1
    assert bal["Benton"]["positive"] == 1 and bal["Benton"]["negative"] == 0
    assert bal["Garrett"]["negative"] == 1 and bal["Garrett"]["positive"] == 0
    assert bal["Hayden"]["neutral"] == 1


def test_missing_labels_distinguishes_omission_from_neutral():
    """Neutral is a judgement; missing is an omission. A tally cannot tell
    them apart unless one of them is reported."""
    labelled = _e("a", ["Nick"], {"Nick": "neutral"})
    unlabelled = _e("b", ["Nick"], {})
    assert LV.missing_labels([labelled]) == []
    assert LV.missing_labels([unlabelled]) == [("b", "Nick")]


def test_format_balance_names_a_one_sided_manager():
    entries = [_e("a", ["Hayden"], {"Hayden": "positive"}),
               _e("b", ["Hayden"], {"Hayden": "positive"}),
               _e("c", ["Nick"], {"Nick": "positive"}),
               _e("d", ["Nick"], {"Nick": "negative"})]
    text = LV.format_balance(entries)
    assert "one-sided: Hayden" in text and "Nick" in text


def test_empty_input_is_every_manager_at_zero():
    bal = LV.balance([])
    assert set(bal) == set(MANAGERS)
    assert all(sum(c.values()) == 0 for c in bal.values())


# ---------------------------------------------------------------------------
# The working copy, when there is one
# ---------------------------------------------------------------------------

def _lore():
    path = ROOT / "config" / "LEAGUE_LORE.json"
    if not path.exists():
        pytest.skip("LEAGUE_LORE.json is not in the repo by design")
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_approved_entry_labels_every_manager_it_names():
    """Replaces the scalar-shaped check in test_lore_usage. Balance cannot be
    measured on an entry that names a manager and says nothing about him."""
    approved = [e for e in _lore()["entries"]
                if e.get("status") == "approved" and e.get("kind") != "alias"]
    gaps = LV.missing_labels(approved)
    assert gaps == [], f"unlabelled manager slots: {gaps[:5]}"


def test_no_approved_entry_still_carries_a_scalar_valence():
    """The migration (scripts/migrate_lore_valence.py) is complete."""
    scalars = [e["id"] for e in _lore()["entries"]
               if e.get("status") == "approved" and e.get("kind") != "alias"
               and not isinstance(e.get("valence"), dict)]
    assert scalars == [], f"not migrated: {scalars[:5]}"
