"""
The Stats Corner history grids publish stored finishes, and their totals
reconcile with the rows beside them.

Through 2025-26 the standings grid re-ranked every season on wins alone;
sorted() is stable and MANAGERS_LIST starts with Nick, so ties on wins went
to him by list position. Published wrong: 2021-22 (Garrett won the
regular-season series 4-3) and 2022-23 (Benton 5-2). Its 1st column also
added two pre-data-era titles to a nine-season count, and there was no 4th.
"""

import json
import re

import pytest

from modules import stats_corner_viz as v


def _grid(render):
    """{manager: ([(place, cell text) per season], [summary ints])}, seasons."""
    html = render({})
    seasons = re.findall(r'sc-hist-th-season[^"]*">([^<]+)<', html)
    out = {}
    for row in re.findall(r'<tr class="sc-hist-row">(.*?)</tr>', html, re.S):
        mgr = re.search(r'sc-hist-td-mgr"[^>]*>([^<]+)<', row).group(1)
        cells = re.findall(r'<td class="sc-hist-td(?: sc-hist-current)?">(.*?)</td>', row)
        places = [(m.group(1) if (m := re.search(r'sc-hist-(1st|2nd|3rd|4th)"', c)) else None, c)
                  for c in cells]
        sums = [int(x) for x in re.findall(r'sc-hist-td-sum[^>]*>(\d+)<', row)]
        out[mgr] = (places, sums)
    return out, seasons, html


def test_ties_on_wins_take_the_stored_tiebreak():
    grid, seasons, _ = _grid(v._render_historical_standings_grid)
    col = {s: i for i, s in enumerate(seasons)}
    assert grid["Garrett"][0][col["21-22"]][0] == "2nd"
    assert grid["Nick"][0][col["21-22"]][0] == "3rd"
    assert grid["Benton"][0][col["22-23"]][0] == "2nd"
    assert grid["Nick"][0][col["22-23"]][0] == "3rd"


@pytest.mark.parametrize("render", [v._render_historical_standings_grid,
                                    v._render_historical_playoff_results_grid])
def test_every_finish_in_the_grid_is_the_stored_one(render):
    stored = v._load_season_standings()
    grid, seasons, _ = _grid(render)
    key = ("regular_season_rank" if render is v._render_historical_standings_grid
           else "playoff_rank")
    for i, short in enumerate(seasons):
        season = next(s for s in stored if s[2:] == short)
        for mgr, (places, _) in grid.items():
            want = v.PLACE_LABELS.get(stored[season][mgr].get(key))
            assert places[i][0] == want, (season, mgr)


def test_standings_totals_reconcile_with_the_rows_beside_them():
    grid, seasons, html = _grid(v._render_historical_standings_grid)
    n = len(seasons)
    for mgr, (places, sums) in grid.items():
        assert len(sums) == 4, f"{mgr}: 1st-4th columns"
        assert sums == [sum(p == lab for p, _ in places) for lab in ("1st", "2nd", "3rd", "4th")]
        assert sum(sums) == n, f"{mgr} finishes don't add up to the seasons shown"
    for k in range(4):
        assert sum(s[k] for _, s in grid.values()) == n
    assert f"Totals count the {n} seasons shown" in html


def test_playoff_titles_count_only_the_seasons_shown():
    grid, seasons, html = _grid(v._render_historical_playoff_results_grid)
    for mgr, (places, sums) in grid.items():
        assert sums == [sum(p == "1st" for p, _ in places)]
    played = sum(1 for i in range(len(seasons))
                 if any(places[i][0] for places, _ in grid.values()))
    assert sum(s[0] for _, s in grid.values()) == played


def test_a_broken_rank_in_the_stored_standings_raises(tmp_path, monkeypatch):
    rows = json.loads(open(v.STANDINGS_PATH, encoding="utf-8").read())
    rows[1]["regular_season_rank"] = rows[0]["regular_season_rank"]   # duplicate
    bad = tmp_path / "all_standings.json"
    bad.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(v, "STANDINGS_PATH", str(bad))
    with pytest.raises(ValueError, match="regular_season_rank"):
        v._render_historical_standings_grid({})
