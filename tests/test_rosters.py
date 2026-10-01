"""ROSTERS.json: the file every simulator reads as ground truth.

It is assembled from a week's LINEUPS and then patched from Yahoo's
transaction log, and until now nothing checked the result. Two things got
through:

    A player who changed hands mid-week appears in both managers' lineups,
    so he lands on both rosters. sync_transactions is meant to resolve it.
    When it does not, every simulator projects his points for two teams.

    "(Empty)" is what LINEUPS records for an open roster slot -- 13 rows
    across 5 weeks last season. It arrived in ROSTERS as a player, held a
    spot, matched nothing in PLAYERLIST and projected 0.0 FPPG.
"""
import importlib.util
import json

import pytest

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location(
        "check_rosters", PROJECT_ROOT / "scripts" / "check_rosters.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(
        "generate_rosters", PROJECT_ROOT / "scripts" / "generate_rosters.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(check, rosters, argv=("c",)):
    import sys
    (check.ROSTERS.parent).mkdir(parents=True, exist_ok=True)
    check.ROSTERS.write_text(json.dumps({"rosters": rosters}), encoding="utf-8")
    old = sys.argv
    sys.argv = list(argv)
    try:
        return check.main()
    finally:
        sys.argv = old


@pytest.fixture
def sandbox(check, tmp_path, monkeypatch):
    monkeypatch.setattr(check, "ROSTERS", tmp_path / "config" / "ROSTERS.json")
    monkeypatch.setattr(check, "PLAYERLIST", tmp_path / "nope.xlsx")
    return check


def _full(size=17, prefix=""):
    return [f"{prefix}Player {i}" for i in range(size)]


# ---------------------------------------------------------------------------
# What it catches
# ---------------------------------------------------------------------------

def test_a_player_on_two_rosters_fails(sandbox, capsys):
    rosters = {m: _full(prefix=f"{m} ") for m in
               ("Nick", "Hayden", "Benton", "Garrett")}
    rosters["Nick"][0] = "Alex Sarr"
    rosters["Benton"][0] = "Alex Sarr"
    assert _run(sandbox, rosters) == 1
    out = capsys.readouterr().out
    assert "Alex Sarr is on 2 rosters" in out
    assert "project him for both teams" in out


def test_duplicate_detection_ignores_spelling(sandbox, capsys):
    """The roster files strip accents; PLAYERLIST does not. A duplicate
    must be caught whichever spelling each side happens to use."""
    rosters = {m: _full(prefix=f"{m} ") for m in
               ("Nick", "Hayden", "Benton", "Garrett")}
    rosters["Nick"][0] = "Nikola Jokic"
    rosters["Hayden"][0] = "Nikola Jokić"
    assert _run(sandbox, rosters) == 1
    assert "2 rosters" in capsys.readouterr().out


def test_an_empty_slot_placeholder_fails(sandbox, capsys):
    rosters = {m: _full(prefix=f"{m} ") for m in
               ("Nick", "Hayden", "Benton", "Garrett")}
    rosters["Hayden"][0] = "(Empty)"
    assert _run(sandbox, rosters) == 1
    assert "empty lineup slot, not a player" in capsys.readouterr().out


@pytest.mark.parametrize("token", ["(Empty)", "empty", "", "   ", "--", "N/A",
                                   "None", "TBD", "(open)"])
def test_every_placeholder_spelling_is_rejected(sandbox, token):
    rosters = {m: _full(prefix=f"{m} ") for m in
               ("Nick", "Hayden", "Benton", "Garrett")}
    rosters["Nick"][0] = token
    assert _run(sandbox, rosters) == 1


def test_a_missing_manager_fails(sandbox, capsys):
    rosters = {m: _full(prefix=f"{m} ") for m in ("Nick", "Hayden", "Benton")}
    assert _run(sandbox, rosters) == 1
    assert "no roster for: Garrett" in capsys.readouterr().out


def test_a_wildly_wrong_roster_size_fails(sandbox):
    rosters = {m: _full(prefix=f"{m} ") for m in
               ("Nick", "Hayden", "Benton", "Garrett")}
    rosters["Nick"] = _full(size=4, prefix="Nick ")
    assert _run(sandbox, rosters) == 1


def test_one_player_off_is_only_a_warning(sandbox):
    """Rosters legitimately sit a player short between a drop and an add."""
    rosters = {m: _full(prefix=f"{m} ") for m in
               ("Nick", "Hayden", "Benton", "Garrett")}
    rosters["Nick"] = _full(size=16, prefix="Nick ")
    assert _run(sandbox, rosters) == 0
    assert _run(sandbox, rosters, argv=("c", "--strict")) == 1


# ---------------------------------------------------------------------------
# What it allows
# ---------------------------------------------------------------------------

def test_a_clean_set_of_rosters_passes(sandbox):
    rosters = {m: _full(prefix=f"{m} ") for m in
               ("Nick", "Hayden", "Benton", "Garrett")}
    assert _run(sandbox, rosters) == 0


def test_an_empty_file_is_fine_before_the_draft(sandbox, capsys):
    assert _run(sandbox, {}) == 0
    assert "Before the draft this is" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The source-side filter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token", ["(Empty)", "(empty)", "EMPTY", "", "  ",
                                   "--", "N/A", "none", "TBD"])
def test_generate_rosters_drops_placeholders(gen, token):
    assert gen._is_placeholder(token), f"{token!r} should be filtered"


@pytest.mark.parametrize("name", ["Nikola Jokic", "Alex Sarr", "VJ Edgecombe",
                                  "Jimmy Butler III", "Egor Demin"])
def test_generate_rosters_keeps_real_players(gen, name):
    assert not gen._is_placeholder(name), f"{name!r} is a person"
