"""Ages: joined through PlayerIndex, sourced, and a failed fetch raises
(HANDOFF_C2C3_GATE_2026-10-29 s.4).

Darius Acuff Jr. (Yahoo id 10582), a 2026 rookie, carried 29 from 09-25 to
10-29: the old fallback join reduced "Darius Acuff Jr." to its first initial
and LAST token ("d" + "jr") and took the first known name that fit --
Derrick Jones Jr. Darryn Peterson (27) and Mikel Brown Jr. (29) were wrong the
same way.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _fp():
    spec = importlib.util.spec_from_file_location("fetch_playerlist_t",
                                                  ROOT / "scripts" / "fetch_playerlist.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _page(rows):
    tr = ('<tr><td data-stat="name_display"><a href="x">{n}</a></td>'
          '<td data-stat="age">{a}</td></tr>')
    return "<table>" + "".join(tr.format(n=n, a=a) for n, a in rows) + "</table>"


@pytest.fixture
def fp(tmp_path, monkeypatch):
    mod = _fp()
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)          # no archived spreadsheets
    monkeypatch.setattr(mod, "PLAYERLIST", tmp_path / "none.xlsx")
    return mod


def _with_pages(fp, monkeypatch, pages):
    """pages: {season end year: [(name, age)]}; any other year is an empty page."""
    real = fp.ages_from_basketball_reference
    monkeypatch.setattr(fp, "ages_from_basketball_reference",
                        lambda year, add=1: real(year, add, fetch=lambda url: _page(pages.get(year, [("Filler Guy", 30)]))))


ROWS = [{"yahoo_id": "10582", "player_name": "Darius Acuff Jr."},
        {"yahoo_id": "1", "player_name": "N. Alexander-Walker"}]


def test_a_rookie_gets_this_seasons_age_and_never_a_namesakes(fp, monkeypatch):
    from datetime import date
    year = date.today().year if date.today().month >= 7 else date.today().year - 1
    _with_pages(fp, monkeypatch, {
        year + 1: [("Darius Acuff Jr.", 20)],                     # this season: he has played
        year: [("Derrick Jones Jr.", 28), ("Nickeil Alexander-Walker", 27)]})
    got = fp.seed_ages(ROWS, {}, use_bbref=True, trust_live=False)
    assert got["10582"] == 20                                    # a rookie's age, from a source
    assert got["1"] == 28                                        # Yahoo's initial still joins (+1)


def test_no_source_is_no_age_not_the_nearest_jr(fp, monkeypatch):
    from datetime import date
    year = date.today().year if date.today().month >= 7 else date.today().year - 1
    _with_pages(fp, monkeypatch, {year: [("Derrick Jones Jr.", 28)]})
    got = fp.seed_ages(ROWS[:1], {}, use_bbref=True, trust_live=False)
    assert "10582" not in got                                    # unaged, reported -- not 29


def test_the_committed_cache_ages_the_rookies_as_rookies():
    ages = json.loads((ROOT / "config" / "PLAYER_AGES.json").read_text(encoding="utf-8"))["ages"]
    for pid in ("10582", "10588", "10590"):                      # Acuff, Brown Jr., Peterson
        assert 18 <= ages[pid] <= 22, (pid, ages[pid])


def test_a_failed_or_empty_age_page_raises(fp):
    def boom(url):
        raise OSError("no network")
    with pytest.raises(fp.AgeFetchError, match="Ages were not changed"):
        fp.ages_from_basketball_reference(2026, fetch=boom)
    with pytest.raises(fp.AgeFetchError, match="no ages"):
        fp.ages_from_basketball_reference(2026, fetch=lambda url: "<html></html>")
    assert fp.ages_from_basketball_reference(2027, add=0, fetch=lambda url: _page(
        [("A B", 20)])) == {"A B": 20}


def test_seed_ages_propagates_the_failure(fp, monkeypatch):
    def fail(year, add=1):
        raise fp.AgeFetchError("down")
    monkeypatch.setattr(fp, "ages_from_basketball_reference", fail)
    with pytest.raises(fp.AgeFetchError):
        fp.seed_ages(ROWS, {}, use_bbref=True)


def test_recheck_replaces_only_ages_more_than_a_year_off(fp, capsys):
    rows = [{"yahoo_id": "10582", "player_name": "Darius Acuff Jr.", "owner": "Hayden"},
            {"yahoo_id": "7", "player_name": "Kon Knueppel", "owner": "Garrett"},
            {"yahoo_id": "8", "player_name": "AJ Dybantsa", "owner": None}]
    written = {}
    code = fp.recheck_ages(rows, execute=True, cached={"10582": 29, "7": 22, "8": 19},
                           derive=lambda: {"10582": 20, "7": 21}, write=written.update)
    out = capsys.readouterr().out
    assert code == 0 and written == {"10582": 20, "7": 22, "8": 19}
    assert "cached 29, source 20" in out and "Kon Knueppel: cached 22, source 21" in out
    assert "no source to check against: AJ Dybantsa" in out
    assert fp.recheck_ages(rows, execute=False, cached={"10582": 29},
                           derive=lambda: {"10582": 20}) == 1     # dry run: not fixed
