"""The weekly add budget: 3 adds per team, new for 2026-27.

The newsletter is written on the Monday morning after a week closes, which
is inside the NEXT week's free-add window and before any game has tipped. So
the live question is how many adds each team has left in the week that just
opened -- not the one that just ended.

Two things had to be true before this could be counted:

    sync_transactions fetched the post-week transactions and printed them to
    the console, then discarded them. They are the only record of the new
    week at newsletter time.

    sync_transactions records both sides of a TRADE as an add, marked
    "(via trade)". load_waiver_adds returned those as players literally
    named "Karl-Anthony Towns (via trade)" -- a string matching nothing in
    PLAYERLIST or PLAYERLOG, so waiver ROI scored every traded player at
    nothing and the add counts included trades.

And the budget is new. Counting 2025-26 against it reports violations of a
rule nobody was playing under.
"""
import pytest

from pathlib import Path

from modules.data_loader import add_budget_for, WEEKLY_ADD_BUDGET
from modules.weekly_stats import load_waiver_adds, _split_acquisition_source

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# The rule did not always exist
# ---------------------------------------------------------------------------

def test_the_budget_applies_from_2026_27():
    assert add_budget_for("2026-27") == 3
    assert add_budget_for("2027-28") == 3


@pytest.mark.parametrize("season", ["2017-18", "2021-22", "2024-25", "2025-26"])
def test_earlier_seasons_had_no_budget(season):
    """None, not 0, and not 3. There was no rule to be over or under."""
    assert add_budget_for(season) is None


def test_the_budget_is_three():
    assert WEEKLY_ADD_BUDGET == 3


# ---------------------------------------------------------------------------
# Trades are not adds
# ---------------------------------------------------------------------------

def test_the_via_marker_is_split_off():
    assert _split_acquisition_source("Karl-Anthony Towns (via trade)") == \
        ("Karl-Anthony Towns", "trade")
    assert _split_acquisition_source("Jalen Duren") == ("Jalen Duren", "")


def test_traded_players_are_not_waiver_adds(tmp_path):
    path = tmp_path / "waivers_week8.txt"
    path.write_text(
        "# Waiver Adds for Week 8\n\n"
        "- [2025-12-08] Nick: Andrew Nembhard\n"
        "- [2025-12-08] Nick: Karl-Anthony Towns (via trade)\n"
        "- [2025-12-08] Garrett: Austin Reaves (via trade)\n"
        "- [2025-12-08] Garrett: Naz Reid\n", encoding="utf-8")
    adds = load_waiver_adds(str(path))
    assert adds["Nick"] == ["Andrew Nembhard"]
    assert adds["Garrett"] == ["Naz Reid"]


def test_no_player_name_carries_the_marker(tmp_path):
    """The name has to join against PLAYERLIST, and "X (via trade)" never will."""
    path = tmp_path / "w.txt"
    path.write_text("- [2025-12-08] Nick: Ja Morant (via waiver)\n", encoding="utf-8")
    adds = load_waiver_adds(str(path))
    assert adds["Nick"] == ["Ja Morant"]


def test_the_real_archived_file_parses_clean():
    archived = PROJECT_ROOT / "archive" / "2025-26" / "data" / "waivers_week8.txt"
    if not archived.is_file():
        pytest.skip("archive not present")
    for players in load_waiver_adds(str(archived)).values():
        for name in players:
            assert "(via" not in name, f"marker survived into {name!r}"


# ---------------------------------------------------------------------------
# The count itself
# ---------------------------------------------------------------------------

@pytest.fixture
def builder(monkeypatch, tmp_path):
    from modules import report_builder as rb
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rb, "__file__", str(tmp_path / "modules" / "report_builder.py"))
    return rb, tmp_path


def _write(tmp_path, week, lines):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / f"waivers_week{week}.txt").write_text(
        "# partial\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def test_it_counts_the_week_that_just_opened(builder):
    rb, tmp_path = builder
    _write(tmp_path, 2, [
        "- [2026-10-26] Garrett: Jalen Duren",
        "- [2026-10-26] Garrett: Tari Eason",
        "- [2026-10-26] Garrett: Kevin Porter Jr.",
        "- [2026-10-26] Nick: Ryan Rollins",
        "- [2026-10-26] Hayden: Naz Reid (via trade)",
    ])

    class D:
        pass
    out = rb.build_add_budget(D(), 1)
    assert out["week"] == 2, "the budget is for the week that opened, not the one that closed"
    assert out["budget"] == 3
    assert out["managers"]["Garrett"] == {
        "used": 3, "remaining": 0,
        "players": ["Jalen Duren", "Tari Eason", "Kevin Porter Jr."],
        "over_budget": False}
    assert out["managers"]["Nick"]["remaining"] == 2
    assert out["managers"]["Hayden"]["used"] == 0, "a trade must not cost an add"
    assert out["managers"]["Benton"]["remaining"] == 3


def test_a_missing_file_shows_full_budgets_and_says_so(builder):
    rb, tmp_path = builder

    class D:
        pass
    out = rb.build_add_budget(D(), 1)
    assert out["source_exists"] is False
    assert all(m["remaining"] == 3 for m in out["managers"].values())
    assert "No add data synced yet" in out["_note"]


def test_no_budget_block_before_the_rule_existed(monkeypatch):
    from modules import report_builder as rb
    monkeypatch.setattr(rb, "add_budget_for", lambda *a, **k: None)

    class D:
        pass
    assert rb.build_add_budget(D(), 1) is None
