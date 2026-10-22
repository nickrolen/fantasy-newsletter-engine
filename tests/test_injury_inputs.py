"""Injury statuses for a build (Nick, 10-21).

A failed or empty Yahoo fetch used to become injury_statuses = {} -- every
line and odds figure priced as though nobody in the league were hurt, with
one console line as the only trace. Now: "fetched, nobody tagged" and "the
fetch failed" cannot look alike; a simulating run refuses without tags unless
--allow-no-injury-statuses; the outcome is recorded in the report metadata
and the point-in-time capture either way; and a tag whose name matches no
rostered player raises instead of disappearing.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from modules import absence
import importlib
fis = importlib.import_module("modules.fetch_injury_statuses")   # the package re-exports a function by this name
from modules.fetch_injury_statuses import (InjuryFetchError, InjuryStatusesUnavailable,
                                           injury_input)

ROOT = Path(__file__).parent.parent
ROSTER = ["Shai Gilgeous-Alexander", "Nikola Jokić", "Bobby Portis", "Kon Knueppel"]


def _failing():
    raise InjuryFetchError("Yahoo auth failed: token revoked")


@pytest.mark.parametrize("fetch,why", [(_failing, "fetch failed"), (lambda: {}, "returned nothing"),
                                       (None, "not fetched")])
def test_a_needed_run_refuses_without_tags(fetch, why):
    with pytest.raises(InjuryStatusesUnavailable, match="--allow-no-injury-statuses"):
        injury_input(fetch, ROSTER, needed=True, not_fetched_reason="--no-fetch-injuries")


@pytest.mark.parametrize("fetch,why", [(_failing, "fetch failed"), (lambda: {}, "returned nothing"),
                                       (None, "not fetched")])
def test_the_override_runs_and_records_it(fetch, why):
    inj = injury_input(fetch, ROSTER, needed=True, allow_missing=True)
    assert inj.statuses == {} and not inj.available and inj.override
    rec = inj.record()
    assert rec["available"] is False and rec["override"] is True and why in rec["problem"]


def test_a_run_that_prices_nothing_needs_no_tags():
    inj = injury_input(None, ROSTER, needed=False, not_fetched_reason="--fast")
    assert not inj.available and not inj.override and "--fast" in inj.problem


def test_fetched_with_nobody_tagged_is_legitimate():
    inj = injury_input(lambda: {n: "HEALTHY" for n in ROSTER}, ROSTER, needed=True)
    assert inj.available and not inj.override and inj.problem is None
    assert inj.record()["non_healthy"] == [] and inj.record()["count"] == 4


def test_tags_resolve_to_the_roster_spelling():
    """Yahoo's 10-05 respellings and stripped accents land on the roster's name."""
    raw = {"S. Gilgeous-Alexander": "O", "Nikola Jokic": "Q", "Bobby Portis Jr.": "HEALTHY",
           "Kon Knueppel": "HEALTHY"}
    inj = injury_input(lambda: raw, ROSTER, needed=True)
    assert dict(inj.statuses) == {"Shai Gilgeous-Alexander": "O", "Nikola Jokić": "Q",
                                  "Bobby Portis": "HEALTHY", "Kon Knueppel": "HEALTHY"}
    assert inj.rostered_without_status == [] and inj.unmatched_healthy == []


def test_an_unresolvable_tag_raises_rather_than_dropping():
    with pytest.raises(absence.UnresolvedTagName, match="Somebody Else"):
        injury_input(lambda: {"Somebody Else": "O", "Kon Knueppel": "HEALTHY"}, ROSTER, needed=True)


def test_an_unresolvable_healthy_name_is_recorded_not_fatal():
    inj = injury_input(lambda: {"Somebody Else": "HEALTHY", "Kon Knueppel": "Q"}, ROSTER, needed=True)
    assert inj.unmatched_healthy == ["Somebody Else"]
    assert set(inj.rostered_without_status) == set(ROSTER) - {"Kon Knueppel"}


def test_two_spellings_with_different_tags_raise():
    with pytest.raises(absence.UnresolvedTagName, match="two Yahoo names"):
        absence.resolve_tags({"Shai Gilgeous-Alexander": "HEALTHY", "S. Gilgeous-Alexander": "O"}, ROSTER)


def test_fetch_failure_paths_raise_never_return_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(fis, "YAHOO_API_AVAILABLE", False)
    with pytest.raises(InjuryFetchError, match="not installed"):
        fis.fetch_injury_statuses(oauth_file=str(tmp_path / "oauth2.json"))
    monkeypatch.setattr(fis, "YAHOO_API_AVAILABLE", True)
    with pytest.raises(InjuryFetchError, match="OAuth file not found"):
        fis.fetch_injury_statuses(oauth_file=str(tmp_path / "missing.json"))
    assert not hasattr(fis, "fetch_injury_statuses_safe")


def test_the_build_records_the_outcome_in_metadata_and_capture():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert "--allow-no-injury-statuses" in src
    assert 'report.setdefault("metadata", {})["injury_statuses"] = injury.record()' in src
    assert '"injury_statuses_override": injury.problem if injury.override else None' in src
    assert "fetch_injury_statuses_safe" not in src
    for f in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        assert "fetch_injury_statuses_safe" not in f.read_text(encoding="utf-8"), f


def test_the_build_refuses_end_to_end_without_tags():
    """A real simulating run with no fetch exits 1 before building anything."""
    r = subprocess.run([sys.executable, "scripts/generate_stats_report.py", "--week", "1",
                        "--no-fetch-injuries", "--dry-run", "--no-freshness"],
                       cwd=ROOT, capture_output=True, text=True, timeout=170)
    assert r.returncode == 1, r.stdout[-2000:]
    assert "REFUSED: no injury statuses: not fetched (--no-fetch-injuries)" in r.stdout
    assert "Building stats report" not in r.stdout
