"""The lore usage ledger.

Nothing recorded which lore entries a week's newsletter actually used, so the
drafting chat saw all 100 approved entries as equally fresh every week and the
same characterisation of a manager could run in all 23 issues (Nick, 10-14).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from modules import lore_usage as LU  # noqa: E402


def test_a_missing_ledger_is_empty_not_an_error(tmp_path):
    assert LU.load(tmp_path)["weeks"] == {}
    assert LU.last_used(tmp_path, "2026-27") == {}
    assert LU.weeks_since(tmp_path, "2026-27", 5) == {}


def test_a_week_is_recorded_and_read_back(tmp_path):
    LU.record(tmp_path, "2026-27", 3, ["myth-a", "myth-b"])
    assert LU.used_ids(tmp_path, "2026-27", 3) == ["myth-a", "myth-b"]
    assert LU.last_used(tmp_path, "2026-27") == {"myth-a": 3, "myth-b": 3}


def test_rechecking_a_week_replaces_it_rather_than_appending(tmp_path):
    """The claim check is run more than once on the same draft. Checking a
    draft three times must not look like using an entry three times."""
    LU.record(tmp_path, "2026-27", 3, ["myth-a", "myth-a", "myth-b"])
    LU.record(tmp_path, "2026-27", 3, ["myth-a"])
    assert LU.used_ids(tmp_path, "2026-27", 3) == ["myth-a"]


def test_duplicates_within_one_issue_count_once(tmp_path):
    LU.record(tmp_path, "2026-27", 4, ["myth-a", "myth-a", "myth-a"])
    assert LU.used_ids(tmp_path, "2026-27", 4) == ["myth-a"]


def test_the_week_being_drafted_does_not_count_as_used(tmp_path):
    """The export runs before the week is written, so its own week must not
    make every entry look stale."""
    LU.record(tmp_path, "2026-27", 5, ["myth-a"])
    assert LU.last_used(tmp_path, "2026-27", before_week=5) == {}
    assert LU.last_used(tmp_path, "2026-27", before_week=6) == {"myth-a": 5}


def test_weeks_since_counts_back_from_the_current_week(tmp_path):
    LU.record(tmp_path, "2026-27", 2, ["old"])
    LU.record(tmp_path, "2026-27", 7, ["recent"])
    assert LU.weeks_since(tmp_path, "2026-27", 8) == {"old": 6, "recent": 1}


def test_the_most_recent_week_wins(tmp_path):
    LU.record(tmp_path, "2026-27", 2, ["myth-a"])
    LU.record(tmp_path, "2026-27", 9, ["myth-a"])
    assert LU.last_used(tmp_path, "2026-27")["myth-a"] == 9


def test_seasons_do_not_bleed_into_each_other(tmp_path):
    LU.record(tmp_path, "2025-26", 3, ["myth-a"])
    assert LU.last_used(tmp_path, "2026-27") == {}


def test_a_corrupt_ledger_does_not_take_the_check_down(tmp_path):
    LU.path(tmp_path).parent.mkdir(exist_ok=True)
    LU.path(tmp_path).write_text("{not json", encoding="utf-8")
    assert LU.load(tmp_path)["weeks"] == {}


def test_the_ledger_is_not_written_into_the_curated_lore_file(tmp_path):
    """LEAGUE_LORE.json is curated by hand through the sittings. A machine
    appending to it weekly would collide with Nick's own edits."""
    LU.record(tmp_path, "2026-27", 1, ["myth-a"])
    assert LU.path(tmp_path).name == "LORE_USAGE.json"
    assert not (tmp_path / "config" / "LEAGUE_LORE.json").exists()


def test_every_approved_manager_entry_carries_a_valence():
    """Balance cannot be enforced, or even measured, on unlabelled entries.
    Aliases are NBA player nicknames and carry no manager valence.

    Valence stopped being one string per entry on 10-15: an entry naming two
    managers is favourable to one and damning to the other, so it is now a
    mapping, manager -> label. The check therefore asks whether every manager
    an entry NAMES is labelled, which is the question balance depends on, and
    it lives in modules/lore_valence so there is only one tally.

    LEAGUE_LORE.json is gitignored -- the repo is public and the lore is not --
    so this checks the working copy when there is one and skips otherwise,
    rather than failing on a fresh clone.
    """
    from modules import lore_valence as LV
    path = ROOT / "config" / "LEAGUE_LORE.json"
    if not path.exists():
        pytest.skip("LEAGUE_LORE.json is not in the repo by design")
    lore = json.loads(path.read_text(encoding="utf-8"))
    approved = [e for e in lore["entries"]
                if e.get("status") == "approved" and e.get("kind") != "alias"]
    gaps = LV.missing_labels(approved)
    assert gaps == [], f"unlabelled manager slots: {gaps[:5]}"
