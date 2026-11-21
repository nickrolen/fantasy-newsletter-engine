"""4a4 s.2.5: the NBA drafts (modules/nba_drafts.py, scripts/fetch_nba_seasons.py --drafts).
No network: a made-up draft page in basketball-reference's shape, a fake fetch.

1. the page: picks, rounds (from round rows, or by pick number), a forfeited pick, gaps
2. a page the parser cannot read RAISES; nothing is written
3. the match: by the engine's matcher; unmatched and ambiguous listed, never stored as a match
4. the file: deterministic, atomic; one id in two drafts decided by his first season; load() names a missing file and the fix
5. the fetch: cached pages cost nothing; the pace between fetches; the script's exit codes
"""
import json
from pathlib import Path

import pytest

from modules import nba_drafts as nd
from modules import nba_seasons as ns
from modules import nba_seasons_bbref as nb

ROOT = Path(__file__).resolve().parents[1]


def _row(pick, name, bid, team="SAS"):
    if name is None:
        return (f'<tr><th data-stat="ranker">{pick}</th><td data-stat="pick_overall">{pick}</td>'
                f'<td data-stat="team_id">{team}</td><td data-stat="player"></td></tr>')
    return (f'<tr><th data-stat="ranker">{pick}</th><td data-stat="pick_overall"><a href="/draft/x">{pick}</a></td>'
            f'<td data-stat="team_id"><a href="/teams/{team}/draft.html">{team}</a></td>'
            f'<td class="left" data-append-csv="{bid}" data-stat="player" csk="x"><a href="/players/x/{bid}.html">'
            f'{name}</a></td><td data-stat="college_name">U</td></tr>')


def page(year, n=58, round_rows=True, forfeit=(), names=None):
    names = names or {}
    rows = []
    for p in range(1, n + 1):
        if round_rows and p == 31:
            rows.append('<tr class="thead"><th colspan="10">Round 2</th></tr>')
        if p in forfeit:
            continue
        nm = names.get(p, f"Player {year} {p}")
        rows.append(_row(p, nm, f"id{year}{p:02d}"))
    if round_rows:
        rows.insert(0, '<tr class="thead"><th colspan="10">Round 1</th></tr>')
    return (f"<html><body><h1>{year} NBA Draft</h1><table id=\"stats\" class=\"stats_table\"><thead><tr>"
            '<th data-stat="pick_overall">Pk</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></body></html>")


# ---- 1. the page

def test_picks_and_rounds_from_the_round_rows():
    d = nd.parse_draft(page(2023), 2023)
    assert len(d["picks"]) == 58 and d["round_from"] == "the page's round rows"
    assert d["picks"][0] == {"pick": 1, "round": 1, "name": "Player 2023 1", "bbref_id": "id202301", "team": "SAS"}
    assert {x["round"] for x in d["picks"] if x["pick"] <= 30} == {1}
    assert {x["round"] for x in d["picks"] if x["pick"] > 30} == {2}


def test_rounds_by_pick_number_without_round_rows_and_a_forfeited_pick():
    html = page(2022, n=58, round_rows=False).replace(_row(45, "Player 2022 45", "id202245"),
                                                      _row(45, None, None))
    d = nd.parse_draft(html, 2022)
    assert d["round_from"].startswith("pick number") and d["forfeited"] == 1 and d["gaps"] == [45]
    assert [x["round"] for x in d["picks"]][29:31] == [1, 2]


def test_commented_out_tables_are_read():
    d = nd.parse_draft(page(2019).replace('<table id="stats"', '<!--<table id="stats"').replace("</table>", "</table>-->"), 2019)
    assert len(d["picks"]) == 58


# ---- 2. what raises

@pytest.mark.parametrize("bad,match", [
    ("<html>nothing</html>", "no draft table"),
    (page(2020, n=40), "only 40 picks"),
    (page(2020, forfeit=(7,)), "first round"),
])
def test_an_unreadable_page_raises(bad, match):
    with pytest.raises(nd.DraftsError, match=match):
        nd.parse_draft(bad, 2020)


# ---- 3-4. the match and the file

@pytest.fixture
def world(tmp_path, monkeypatch):
    names = {"100": ["Victor Wembanyama"], "200": ["Jalen Williams"], "201": ["Jalen Williams"],
             "300": ["Nikola Jokic"]}
    monkeypatch.setattr(ns, "load", lambda base, **k: {"players": {}, "provenance": {}})
    monkeypatch.setattr(nb, "yahoo_names", lambda base, blobs: names)
    return tmp_path


def test_the_match_and_the_file(world):
    pages = {2022: page(2022, names={12: "Jalen Williams"}), 2023: page(2023, names={1: "Victor Wembanyama"})}
    blob = nd.build(world, pages, now="2026-11-20T00:00:00+00:00")
    assert blob["players"] == {"100": {"year": 2023, "pick": 1, "round": 1, "name": "Victor Wembanyama"}}
    p22 = blob["provenance"]["2022"]
    assert p22["matched"] == 0 and [a["name"] for a in p22["ambiguous"]] == ["Jalen Williams"]
    assert len(p22["unmatched"]) == 57 and {"name": "Player 2022 1", "pick": 1} in p22["unmatched"]
    assert blob["drafts"]["2023"][0]["yahoo_id"] == "100" and blob["drafts"]["2022"][11]["yahoo_id"] is None
    text = nd.dumps(blob)
    assert text == nd.dumps(json.loads(text)) and text.isascii()
    nd.write(world, blob)
    assert nd.load(world)["players"] == blob["players"]
    assert not list((world / "data" / "historical").glob("*.tmp"))
    lines = nd.summary_lines(blob)
    assert lines[0].startswith("NBA_DRAFTS: 2 drafts (2022-2023), 116 picks, 1 matched")
    assert any("ambiguous: Jalen Williams" in ln for ln in lines)


def _seasons(first):
    return {"players": {} if first is None else {"300": {"name": "Nikola Jokic", "seasons": {
        first: {"gp": 0 if first == "zero" else 70, "stats": {}}}}}, "provenance": {}}


@pytest.mark.parametrize("first,kept", [
    ("2022-23", 2022),        # the 2022 pick's rookie season: 2022 keeps the id, 2023 is unmatched
    ("2021-22", None),        # before both drafts: neither fits
    ("2024-25", None),        # a later debut fits both: never guessed
    (None, None),             # no season in the file: cannot tell them apart
])
def test_one_id_in_two_drafts_is_decided_by_his_first_season(world, monkeypatch, first, kept):
    """Nick, 11-20: Justin Jackson 2017 #15 and 2018 #43 share a name and a Yahoo id."""
    monkeypatch.setattr(ns, "load", lambda base, **k: _seasons(first))
    pages = {2022: page(2022, names={3: "Nikola Jokic"}), 2023: page(2023, names={9: "Nikola Jokic"})}
    blob = nd.build(world, pages)
    got = {y: [x["yahoo_id"] for x in blob["drafts"][y] if x["name"] == "Nikola Jokic"][0] for y in ("2022", "2023")}
    if kept is None:
        assert got == {"2022": None, "2023": None} and "300" not in blob["players"]
    else:
        assert got == {"2022": "300", "2023": None}
        assert blob["players"]["300"] == {"year": 2022, "pick": 3, "round": 1, "name": "Nikola Jokic"}
    for y, pk in (("2022", 3), ("2023", 9)):
        if got[y] is None:
            u = next(u for u in blob["provenance"][y]["unmatched"] if u["pick"] == pk)
            assert u["name"] == "Nikola Jokic" and "Yahoo id 300" in u["why"]
    assert any("shared id:" in ln for ln in nd.summary_lines(blob))


def test_first_season_start():
    assert nd.first_season_start(_seasons("2019-20"), "300") == 2019
    assert nd.first_season_start(_seasons(None), "300") is None


def test_load_names_the_file_and_the_fix(tmp_path):
    with pytest.raises(nd.DraftsError, match="NBA_DRAFTS.json is missing: run python scripts/fetch_nba_seasons.py --drafts"):
        nd.load(tmp_path)
    (tmp_path / "data" / "historical").mkdir(parents=True)
    nd.path(tmp_path).write_text("{", encoding="utf-8")
    with pytest.raises(nd.DraftsError, match="unreadable"):
        nd.load(tmp_path)


# ---- 5. the fetch

def test_cached_pages_cost_nothing_and_the_pace_holds(world):
    calls, waits = [], []

    def fetch(url):
        calls.append(url)
        return page(int(url.split("_")[-1].split(".")[0]))
    r = nd.run(world, first=2021, last=2023, fetch=fetch, sleeper=waits.append, log=lambda *a: None, now="x")
    assert r["fetched"] == 3 and len(calls) == 3 and waits == [nb.PACE, nb.PACE]
    assert calls[0] == "https://www.basketball-reference.com/draft/NBA_2021.html"
    r = nd.run(world, first=2021, last=2023, fetch=fetch, sleeper=waits.append, log=lambda *a: None, now="x")
    assert r["fetched"] == 0 and len(calls) == 3


def test_a_failed_fetch_writes_nothing(world):
    def fetch(url):
        if "2022" in url:
            raise OSError("boom")
        return page(2021)
    with pytest.raises(nd.DraftsError, match="NBA_2022.html"):
        nd.run(world, first=2021, last=2023, fetch=fetch, sleeper=lambda s: None, log=lambda *a: None)
    assert not nd.path(world).exists() and nd.cache_path(world, 2021).is_file()


def test_the_scripts_drafts_option(world):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import fetch_nba_seasons as F
    out = []
    rc = F.main(["--base-path", str(world), "--drafts", "--draft-last", "2014"], log=out.append,
                sleeper=lambda s: None, bbref_fetch=lambda url: page(2014))
    assert rc == 0 and any(x.startswith("NBA_DRAFTS: 1 drafts (2014-2014)") for x in out)
    rc = F.main(["--base-path", str(world), "--drafts", "--draft-last", "2015"], log=out.append,
                sleeper=lambda s: None, bbref_fetch=lambda url: "<html></html>")
    assert rc == 1 and any(x.startswith("REFUSED: 2015: no draft table") for x in out)
