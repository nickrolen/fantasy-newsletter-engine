"""
Every table in a published newsletter reconciles with itself and with the
stored records (modules/published_tables.py).

Run against the six shipped 2025-26 newsletters, the checker finds what was
actually wrong in print -- the history-grid errors found by hand on 10-13,
and three more nobody had noticed:

  - both history grids marked the last column "current" (24-25) in a 25-26
    newsletter;
  - Manager Profiles printed an eleven-season title count on a card whose
    record counts the data era;
  - WEEK18's Worst Performers (FPPG) printed Pascal Siakam's FPPG as 1859.0,
    his total, from a draft row shifted by one cell;
  - Season Waiver Wire ROI printed starts-only FPPG beside all-games Total
    FP and GP, so FPPG != Total / GP on most rows.

The current renderers produce none of them (the last test).
"""

import json
import re
from pathlib import Path

import pytest

from modules import published_tables as pt

ROOT = Path(__file__).parent.parent
ARCHIVE = ROOT / "archive" / "2025-26" / "output"


def _check(path):
    doc = path.read_text(encoding="utf-8")
    return pt.check_document(doc, pt.load_context(ROOT, pt.season_of(path, doc)))


def _kinds(findings):
    return {(f.table, f.check) for f in findings}


@pytest.fixture(scope="module")
def week21():
    path = ARCHIVE / "WEEK21_NEWSLETTER.html"
    if not path.is_file():
        pytest.skip("archive not present")
    return _check(path)


def test_the_shipped_standings_errors_are_found(week21):
    findings, _ = week21
    stored = [f.detail for f in findings if f.check == "stored finish"]
    assert sorted(stored) == sorted([
        "21-22 Nick: shown 2, stored regular_season_rank 3",
        "21-22 Garrett: shown 3, stored regular_season_rank 2",
        "22-23 Nick: shown 2, stored regular_season_rank 3",
        "22-23 Benton: shown 3, stored regular_season_rank 2"])


def test_the_shipped_scope_mixing_is_found(week21):
    kinds = _kinds(week21[0])
    assert ("Historical League Standings", "1st column") in kinds
    assert ("Historical Playoff Results", "\U0001F3C6 column") in kinds
    assert ("Manager Profiles", "titles scope") in kinds
    assert ("Season Waiver Wire ROI", "FPPG = Total/GP") in kinds
    assert ("Historical League Standings", "current column") in kinds


def test_the_shifted_draft_row_in_week18_is_found():
    path = ARCHIVE / "WEEK18_NEWSLETTER.html"
    if not path.is_file():
        pytest.skip("archive not present")
    findings, _ = _check(path)
    assert any(f.check == "FPPG range" and "Pascal Siakam" in f.detail for f in findings)


def test_every_table_in_a_shipped_newsletter_has_a_check(week21):
    _, unchecked = week21
    assert unchecked == [], f"tables with no relations defined: {unchecked}"


# ---------------------------------------------------------------------------
# Each relation fires on a minimal page (so a clean result is not vacuous)
# ---------------------------------------------------------------------------

def _page(body):
    return f"<html><body>{body}</body></html>"


def _table(title, header, rows, cls=""):
    th = "".join(f"<th>{h}</th>" for h in header)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<div class="section-header">{title}</div>'
            f'<table class="{cls}"><tr>{th}</tr>{trs}</table>')


@pytest.mark.parametrize("rows,bad", [
    ([["A", "40%", "30%", "20%", "10%"], ["B", "10%", "20%", "30%", "40%"],
      ["C", "25%", "25%", "25%", "25%"], ["D", "25%", "25%", "25%", "25%"]], False),
    ([["A", "40%", "30%", "20%", "20%"], ["B", "10%", "20%", "30%", "40%"],
      ["C", "25%", "25%", "25%", "25%"], ["D", "25%", "25%", "25%", "25%"]], True),
])
def test_probability_rows_and_columns_sum_to_100(rows, bad):
    doc = _page(_table("Playoff Championship Probability",
                       ["Team", "Champ %", "Runner-Up %", "3rd %", "4th %"], rows))
    findings, _ = pt.check_document(doc, {"season": None, "standings": {}})
    assert bool(findings) == bad


def test_a_total_in_an_fppg_column_and_a_bad_division_are_found():
    doc = _page(_table("Waiver Pickups", ["Player", "GP", "Total FP", "FPPG"],
                       [["Ok", "4", "120.00", "30.00"],
                        ["Shifted", "4", "30.00", "120.00"],
                        ["Wrong", "4", "120.00", "33.00"]]))
    findings, _ = pt.check_document(doc, {"season": None, "standings": {}})
    assert {f.check for f in findings} == {"FPPG range", "FPPG = Total/GP"}
    assert not any("Ok" in f.detail for f in findings)


def test_h2h_must_be_antisymmetric():
    doc = _page(_table("Head-to-Head Records", ["", "A", "B"],
                       [["A", "-", "5-3"], ["B", "4-5", "-"]]))
    findings, _ = pt.check_document(doc, {"season": None, "standings": {}})
    assert [f.check for f in findings] == ["antisymmetry", "antisymmetry"]


def test_a_summary_column_that_does_not_count_its_row_is_found():
    cells = ('<td class="sc-hist-td"><span class="sc-hist-place sc-hist-1st">10-5</span></td>'
             '<td class="sc-hist-td"><span class="sc-hist-place sc-hist-2nd">9-6</span></td>')
    html = ('<div class="sc-mgr-section-header">Historical League Standings</div>'
            '<table class="sc-hist-table"><tr><th>MANAGER</th><th>20-21</th><th>21-22</th>'
            '<th>1st</th><th>2nd</th></tr>'
            f'<tr class="sc-hist-row"><td class="sc-hist-td sc-hist-td-mgr">A</td>{cells}'
            '<td class="sc-hist-td sc-hist-td-sum">2</td><td class="sc-hist-td sc-hist-td-sum">1</td></tr>'
            '</table>')
    findings, _ = pt.check_document(_page(html), {"season": None, "standings": {}})
    assert [f.check for f in findings] == ["1st column"]


def test_games_grid_cells_must_add_up():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_gg_fixture", Path(__file__).parent / "test_games_grid.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    from modules import games_grid as gg
    html = gg.render_html(fixture._report())
    clean, _ = pt.check_document(_page(html), {"season": None, "standings": {}})
    assert clean == []
    broken = re.sub(r'<span class="gg-n">(\d+)</span>', '<span class="gg-n">99</span>', html, count=1)
    findings, _ = pt.check_document(_page(broken), {"season": None, "standings": {}})
    assert any(f.check == "starters" for f in findings)


# ---------------------------------------------------------------------------
# The current renderers
# ---------------------------------------------------------------------------

def test_the_current_stats_corner_reconciles():
    """Stats Corner rendered today from the archived week-21 report: the
    history grids, profiles, leaderboards and H2H matrix all reconcile."""
    from modules.stats_corner_viz import render_stats_corner_visualizations
    rep_path = ARCHIVE / "stats_report_week21.json"
    if not rep_path.is_file():
        pytest.skip("archive not present")
    report = json.loads(rep_path.read_text(encoding="utf-8"))
    html = render_stats_corner_visualizations(report)
    root = pt.parse(html)
    assert len(root.find_all(cls="sc-hist-table")) == 3      # not vacuous
    assert len(root.find_all(cls="sc-mgr-card")) == 4
    findings, unchecked = pt.check_document(_page(html), pt.load_context(ROOT, "2026-27"))
    assert findings == [], [str(f) for f in findings]
