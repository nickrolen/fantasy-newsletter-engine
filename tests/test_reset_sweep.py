"""The season reset: catching files that were archived but never cleared.

A per-season file that survives the reset is worse than one that goes
missing. Missing fails loudly on the first run; surviving looks populated
and valid, and the newsletter quietly reports last season's numbers.

This check existed and passed clean while all six of 2025-26's newsletters
sat in output/, byte-identical to their archived copies. It walked a hand-
written list of files, and output/ was not on it -- so the one signature it
exists to detect went unexamined for 7.5 MB. These tests cover the sweep
that replaced the blind spot, and the exception that keeps it quiet.
"""
import importlib.util

import pytest

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location(
        "verify_project_integrity",
        PROJECT_ROOT / "scripts" / "verify_project_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tree(tmp_path, verify, monkeypatch):
    """An empty project with one archived season, rooted in tmp_path."""
    (tmp_path / "archive" / "2025-26").mkdir(parents=True)
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _place(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def _both(root, rel, content, season="2025-26"):
    """The same bytes live and archived -- the shape of a survived file."""
    _place(root, rel, content)
    _place(root, f"archive/{season}/{rel}", content)


def test_a_leftover_newsletter_in_output_is_caught(tree, verify):
    """The exact miss: output/ was never on the list."""
    _both(tree, "output/WEEK21_NEWSLETTER.html", "<html>last season</html>")
    failures = verify._check_no_file_survived_the_reset([])
    assert len(failures) == 1
    assert "output/WEEK21_NEWSLETTER.html" in failures[0]
    assert "2025-26" in failures[0]


def test_all_six_that_slipped_through_are_caught(tree, verify):
    for week in range(16, 22):
        _both(tree, f"output/WEEK{week}_NEWSLETTER.html", f"<html>week {week}</html>")
    failures = verify._check_no_file_survived_the_reset([])
    assert len(failures) == 6


def test_a_nested_file_in_a_swept_directory_is_found(tree, verify):
    """rglob, not iterdir -- a leftover one level down still counts."""
    _both(tree, "config/snapshots/PLAYERLIST_2026-03-25.xlsx", b"\x50\x4b\x03\x04old")
    failures = verify._check_no_file_survived_the_reset([])
    assert len(failures) == 1
    assert "config/snapshots/PLAYERLIST_2026-03-25.xlsx" in failures[0]


def test_the_named_file_list_still_works(tree, verify):
    """PER_SEASON_FILES was the original mechanism and is not replaced."""
    _both(tree, "data/PLAYERLIST.xlsx", b"\x50\x4b\x03\x04last season")
    failures = verify._check_no_file_survived_the_reset([])
    assert len(failures) == 1
    assert "data/PLAYERLIST.xlsx" in failures[0]


def test_a_regenerated_file_is_not_flagged(tree, verify):
    """Same path, different bytes: this season's file. The whole point."""
    _place(tree, "output/WEEK01_NEWSLETTER.html", "<html>this season</html>")
    _place(tree, "archive/2025-26/output/WEEK01_NEWSLETTER.html",
           "<html>last season</html>")
    _place(tree, "data/PLAYERLIST.xlsx", b"fresh")
    _place(tree, "archive/2025-26/data/PLAYERLIST.xlsx", b"stale")
    assert verify._check_no_file_survived_the_reset([]) == []


def test_reused_assets_are_not_swept(tree, verify):
    """helmet.png is SUPPOSED to be identical every season.

    Sweeping assets/ would fail the run on files that are correct, which is
    how a check gets switched off.
    """
    _both(tree, "assets/helmet.png", b"\x89PNG helmet")
    _both(tree, "assets/podium.png", b"\x89PNG podium")
    assert verify._check_no_file_survived_the_reset([]) == []
    assert "assets" not in verify.PER_SEASON_DIRS


def test_an_empty_live_tree_passes(tree, verify):
    _place(tree, "archive/2025-26/output/WEEK21_NEWSLETTER.html", "<html>x</html>")
    assert verify._check_no_file_survived_the_reset([]) == []


def test_no_archive_at_all_is_not_an_error(tmp_path, verify, monkeypatch):
    monkeypatch.setattr(verify, "PROJECT_ROOT", tmp_path)
    _place(tmp_path, "output/WEEK21_NEWSLETTER.html", "<html>x</html>")
    assert verify._check_no_file_survived_the_reset([]) == []


def test_a_file_is_reported_once_not_once_per_season(tree, verify):
    """Two archived seasons holding the same bytes is still one problem."""
    (tree / "archive" / "2024-25").mkdir(parents=True, exist_ok=True)
    _both(tree, "output/WEEK21_NEWSLETTER.html", "<html>same</html>")
    _place(tree, "archive/2024-25/output/WEEK21_NEWSLETTER.html", "<html>same</html>")
    failures = verify._check_no_file_survived_the_reset([])
    assert len(failures) == 1


def test_a_swept_file_already_named_is_not_reported_twice(tree, verify):
    """PLAYERLIST.xlsx is named; if a swept dir ever also covered it, the
    seen-set keeps it to one failure rather than two identical ones."""
    _both(tree, "data/PLAYERLIST.xlsx", b"dupe")
    monkeypatch_dirs = list(verify.PER_SEASON_DIRS) + ["data"]
    original = verify.PER_SEASON_DIRS
    verify.PER_SEASON_DIRS = monkeypatch_dirs
    try:
        failures = verify._check_no_file_survived_the_reset([])
    finally:
        verify.PER_SEASON_DIRS = original
    assert len([f for f in failures if "PLAYERLIST" in f]) == 1
