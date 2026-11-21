"""4a4 Phase A, the basketball-reference fallback (modules/nba_seasons_bbref,
scripts/fetch_nba_seasons.py --bbref; Nick 11-20: Yahoo's today's game does
not know retired players, so 2014-15 to 2021-22 come from basketball-
reference's season totals).

1. the pages: one per season, polite (3.2 s apart), cached, never fetched twice
2. the rows: a traded player's total row, never the per-team rows; a missing
   column refuses; a row failing an identity is rejected by name
3. the match: accents, suffixes, the Hall-of-Fame asterisk; unmatched and
   ambiguous names listed, never stored, never guessed
4. the proof: 2022-23 against Yahoo, the kept Yahoo 2021-22; a failed proof
   writes nothing
5. one source per season, recorded; Yahoo seasons untouched; deterministic
No network: a fake basketball-reference in the page's real markup (the
cached per-game pages' attributes: data-append-csv, data-stat).
"""
import json

import pytest

from modules import nba_seasons as ns
from modules import nba_seasons_bbref as nb
from scripts import fetch_nba_seasons as cli
from test_4a4_nba_seasons import VALUES, ORDER, box

NOW = "2026-11-20T23:00:00+00:00"
BB_SEASONS = ns.seasons_between("2014-15", "2021-22")


@pytest.fixture(autouse=True)
def _small_seasons(monkeypatch):
    """The fixtures' Yahoo seasons are 20-30 players; a real one needs 300 who played."""
    assert ns.MIN_PLAYED == 300
    monkeypatch.setattr(ns, "MIN_PLAYED", 5)


def cell(stat, value, cls="right"):
    return f'<td class="{cls} " data-stat="{stat}" >{value}</td>'


def row(bid, name, team, gp, st, rank):
    t = team if team in ("2TM", "3TM", "TOT") else f'<a href="/teams/{team}/2022.html">{team}</a>'
    return ("<tr >" + f'<th scope="row" class="right " data-stat="ranker" csk="{rank}" >{rank}</th>'
            + f'<td class="left " data-append-csv="{bid}" data-stat="name_display" csk="x" >'
              f'<a href="/players/{bid[0]}/{bid}.html">{name}</a></td>'
            + cell("age", 27) + cell("team_name_abbr", t, "left") + cell("pos", "C", "center")
            + cell("games", gp) + cell("games_started", gp) + cell("mp", 30 * gp)
            + cell("fg", st["FGM"]) + cell("fga", st["FGA"]) + cell("fg_pct", ".500")
            + cell("fg3", st["3PTM"]) + cell("fg3a", st["3PTM"] * 3)
            + cell("ft", st["FTM"]) + cell("fta", st["FTA"]) + cell("orb", 1) + cell("drb", st["REB"] - 1)
            + cell("trb", st["REB"]) + cell("ast", st["AST"]) + cell("stl", st["ST"]) + cell("blk", st["BLK"])
            + cell("tov", st["TO"]) + cell("pf", 10) + cell("pts", st["PTS"]) + "</tr>")


def page(players):
    """players: [(bid, name, gp, stats, teams)]; a traded player gets his
    2TM total row first, then one row per team (halves that do not add up,
    so a per-team row read by mistake shows)."""
    out = ['<table class="stats_table" id="totals_stats"><thead><tr>'
           '<th data-stat="ranker">Rk</th><th data-stat="name_display">Player</th></tr></thead><tbody>']
    for i, (bid, name, gp, st, teams) in enumerate(players, 1):
        if len(teams) > 1:
            out.append(row(bid, name, f"{len(teams)}TM", gp, st, i))
            for t in teams:
                out.append(row(bid, name, t, gp // 2, box(i, gp // 2), i))
        else:
            out.append(row(bid, name, teams[0], gp, st, i))
    out.append('<tr class="league_average_table"><td data-stat="name_display">League Average</td></tr>')
    return "\n".join(out) + "</tbody></table>"


def roster(year, n=30):
    """[(bid, name, yahoo id, gp, stats, teams)] for one season."""
    out = []
    for i in range(n):
        yid = 1000 + i * 3
        gp = 50 + (i * 7 + year) % 30
        out.append((f"pl{i:03d}aa01", f"Player {yid}", yid, gp, box(yid + year, gp),
                    ["BOS", "LAL"] if i % 9 == 4 else ["OKC"]))
    return out


class FakeBBRef:
    def __init__(self, truth, fail=None):
        self.truth = truth        # {season: roster}
        self.fail = set(fail or ())
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        year = int(url.split("NBA_")[1][:4]) - 1
        season = ns.season_label(year)
        if season in self.fail:
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return page([(b, n, g, s, t) for b, n, _, g, s, t in self.truth[season]])


def world(tmp_path, *, truth=None, yahoo22=None, yahoo21=True):
    base = tmp_path / "repo"
    (base / "config").mkdir(parents=True)
    cfg = {"yahoo": {"current_league_key": "478.l.16778",
                     "historical_league_keys": {"2017-18": "375.l.132631", "2021-22": "410.l.22742",
                                                "2022-23": "418.l.78463"}},
           "yahoo_settings": {"stat_values": VALUES}}
    (base / "config" / "league_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    truth = truth or {s: roster(ns.season_year(s)) for s in BB_SEASONS + ["2022-23"]}
    blob = ns.empty(ORDER)
    for s in BB_SEASONS:
        blob["provenance"][s] = dict(ns.fresh("999"), status="unavailable", reason="no stats")
    blob["provenance"]["2022-23"] = dict(ns.fresh("418"), status="complete", method=ns.SEASON_METHOD, pool=30)
    for b, n, yid, gp, st, t in (yahoo22 if yahoo22 is not None else truth["2022-23"]):
        blob["players"].setdefault(str(yid), {"name": n, "seasons": {}})["seasons"]["2022-23"] = {"gp": gp, "stats": st}
    if yahoo21:
        p = blob["provenance"]["2021-22"] = dict(ns.fresh("410"), status="complete", method=ns.TODAY_METHOD,
                                                 pool=30)
        kept = truth["2021-22"][:20]
        for b, n, yid, gp, st, t in kept:
            blob["players"].setdefault(str(yid), {"name": n, "seasons": {}})["seasons"]["2021-22"] = \
                {"gp": gp, "stats": st}
        p["unserved"] = [{"player_id": str(yid), "name": n, "why": "refused"} for b, n, yid, *_ in truth["2021-22"][20:]]
    (base / "data" / "historical").mkdir(parents=True)
    ns.write(base, blob)
    return base, truth


def run(base, fake, *args):
    out, sleeps = [], []
    rc = cli.main(["--base-path", str(base), "--bbref", "--last", "2022-23", *args], log=out.append,
                  now=lambda: NOW, sleeper=sleeps.append, bbref_fetch=fake)
    return rc, out, sleeps


def blob_of(base):
    return json.loads(ns.path(base).read_text(encoding="utf-8"))


# 1, 5 ------------------------------------------------------------------------

def test_the_old_seasons_come_from_bbref_with_the_source_recorded(tmp_path):
    base, truth = world(tmp_path)
    before22 = {pid: r["seasons"]["2022-23"] for pid, r in blob_of(base)["players"].items() if "2022-23" in r["seasons"]}
    fake = FakeBBRef(truth)
    rc, out, sleeps = run(base, fake)
    assert rc == 0, out
    assert len(fake.urls) == 9 and fake.urls[0] == "https://www.basketball-reference.com/leagues/NBA_2015_totals.html"
    assert sleeps == [nb.PACE] * 8, "3.2 s between pages, none before the first"
    blob = blob_of(base)
    for s in BB_SEASONS:
        p = blob["provenance"][s]
        assert p["source"] == "basketball-reference" and p["status"] == "complete"
        assert p["url"] == nb.page_url(s) and p["method"] == nb.METHOD
        assert p["matched"] == 30 and p["unmatched"] == [] and p["ambiguous"] == [] and p["rejected"] == []
        for b, n, yid, gp, st, t in truth[s]:
            assert blob["players"][str(yid)]["seasons"][s] == {"gp": gp, "stats": st}, (s, n)
    assert blob["provenance"]["2022-23"]["source"] == "yahoo"
    assert {pid: r["seasons"]["2022-23"] for pid, r in blob["players"].items() if "2022-23" in r["seasons"]} == before22
    assert any(line.startswith("PROOF 2022-23 vs Yahoo 2022-23: 30 matched players compared; 30 identical")
               for line in out)
    assert any(line.startswith("PROOF 2021-22 vs the Yahoo 2021-22 players kept: 20 matched players compared; "
                               "20 identical") for line in out)
    assert any("from basketball-reference (https://www.basketball-reference.com/leagues/NBA_2015_totals.html): "
               "30 matched" in line for line in out)


def test_a_traded_player_is_his_total_row(tmp_path):
    base, truth = world(tmp_path)
    run(base, FakeBBRef(truth))
    b, n, yid, gp, st, teams = truth["2019-20"][4]
    assert teams == ["BOS", "LAL"]
    assert blob_of(base)["players"][str(yid)]["seasons"]["2019-20"] == {"gp": gp, "stats": st}


def test_pages_are_cached_and_a_rerun_fetches_nothing_and_writes_the_same(tmp_path):
    base, truth = world(tmp_path)
    run(base, FakeBBRef(truth))
    first = ns.path(base).read_text()
    assert sorted(f.name for f in (base / "data" / ".cache").iterdir()) == \
        sorted(f"bbref_totals_{s}.html" for s in BB_SEASONS + ["2022-23"])
    fake2 = FakeBBRef(truth)
    rc, out, sleeps = run(base, fake2)
    assert rc == 0 and fake2.urls == [] and sleeps == []
    assert ns.path(base).read_text() == first
    assert any("PROOF 2021-22 vs the Yahoo 2021-22 players kept: 20 matched" in line for line in out), \
        "the second run still proves 2021-22 from the copy saved before the first replaced it"


def test_a_failed_page_writes_nothing_and_the_rerun_fetches_only_what_is_missing(tmp_path):
    base, truth = world(tmp_path)
    before = ns.path(base).read_text()
    rc, out, _ = run(base, FakeBBRef(truth, fail={"2017-18"}))
    assert rc == 1
    assert any("REFUSED: https://www.basketball-reference.com/leagues/NBA_2018_totals.html: RuntimeError: "
               "HTTP Error 429" in line for line in out)
    assert ns.path(base).read_text() == before
    fake = FakeBBRef(truth)
    rc, out, _ = run(base, fake)
    assert rc == 0
    assert fake.urls == [nb.page_url(s) for s in ("2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23")]


# 2 ---------------------------------------------------------------------------

def test_a_missing_column_refuses_naming_it(tmp_path):
    base, truth = world(tmp_path)
    before = ns.path(base).read_text()

    def no_tov(url):
        return FakeBBRef(truth)(url).replace('data-stat="tov"', 'data-stat="turnovers"')
    rc, out, _ = run(base, no_tov)
    assert rc == 1
    assert any("has no column ['tov']; its unfamiliar columns: ['turnovers']" in line for line in out)
    assert ns.path(base).read_text() == before


def test_a_row_failing_an_identity_is_rejected_by_name(tmp_path):
    base, truth = world(tmp_path)
    b, n, yid, gp, st, t = truth["2016-17"][2]
    truth["2016-17"][2] = (b, n, yid, gp, dict(st, PTS=st["PTS"] + 2), t)
    rc, out, _ = run(base, FakeBBRef(truth))
    assert rc == 0
    p = blob_of(base)["provenance"]["2016-17"]
    assert [r["name"] for r in p["rejected"]] == [n] and p["rejected"][0]["why"].startswith("PTS")
    assert "2016-17" not in blob_of(base)["players"].get(str(yid), {}).get("seasons", {})


# 3 ---------------------------------------------------------------------------

def test_spellings_match_and_the_unknown_and_ambiguous_are_listed_not_stored(tmp_path):
    base, truth = world(tmp_path)
    blob = blob_of(base)
    blob["players"]["7001"] = {"name": "Nikola Jokić", "seasons": {"2022-23": {"gp": 69, "stats": box(1, 69)}}}
    blob["players"]["7002"] = {"name": "Marcus Morris", "seasons": {"2022-23": {"gp": 65, "stats": box(2, 65)}}}
    blob["players"]["7003"] = {"name": "Mike Scott", "seasons": {"2022-23": {"gp": 1, "stats": box(3, 1)}}}
    blob["players"]["7004"] = {"name": "Mike Scott", "seasons": {"2022-23": {"gp": 2, "stats": box(4, 2)}}}
    ns.write(base, blob)
    s = "2018-19"
    truth[s] = truth[s] + [("jokicni01", "Nikola Jokic", 7001, 80, box(5, 80), ["DEN"]),
                           ("morrima03", "Marcus Morris Sr.", 7002, 75, box(6, 75), ["BOS"]),
                           ("scottmi01", "Mike Scott", None, 79, box(7, 79), ["PHI"]),
                           ("nowitdi01", "Dirk Nowitzki*", None, 77, box(8, 77), ["DAL"])]
    rc, out, _ = run(base, FakeBBRef(truth))
    assert rc == 0, out
    b = blob_of(base)
    p = b["provenance"][s]
    assert b["players"]["7001"]["seasons"][s]["gp"] == 80 and b["players"]["7001"]["name"] == "Nikola Jokić"
    assert b["players"]["7002"]["seasons"][s]["gp"] == 75
    assert p["unmatched"] == [{"name": "Dirk Nowitzki", "bbref_id": "nowitdi01", "gp": 77}], "asterisk stripped"
    assert p["ambiguous"] == [{"name": "Mike Scott", "bbref_id": "scottmi01", "yahoo_ids": ["7003", "7004"],
                               "why": "'Mike Scott' is 2 Yahoo players"}]
    assert s not in b["players"]["7003"]["seasons"] and s not in b["players"]["7004"]["seasons"]
    assert any("ambiguous: Mike Scott (scottmi01) -> Yahoo ['7003', '7004']" in line for line in out)
    assert any("unmatched (most games first): Dirk Nowitzki 77g" in line for line in out)


def test_two_bbref_rows_on_one_yahoo_id_are_both_ambiguous():
    from modules.data_loader import PlayerIndex
    idx = PlayerIndex({"Gary Payton": frozenset({"10"})})
    rows = [{"bbref_id": "paytoga02", "name": "Gary Payton II", "gp": 40},
            {"bbref_id": "paytoga01", "name": "Gary Payton", "gp": 3}]
    matched, un, amb = nb.match(rows, idx)
    assert matched == {} and un == []
    assert sorted(a["bbref_id"] for a in amb) == ["paytoga01", "paytoga02"]
    assert all("2 basketball-reference players resolve to Yahoo id 10" in a["why"] for a in amb)


# 4 ---------------------------------------------------------------------------

def test_a_failed_proof_writes_nothing_and_names_the_differences(tmp_path):
    base, truth = world(tmp_path)
    yahoo22 = [(b, n, y, gp, dict(st, AST=st["AST"] + 1), t) for b, n, y, gp, st, t in truth["2022-23"]]
    base2, _ = world(tmp_path / "x", truth=truth, yahoo22=yahoo22)
    before = ns.path(base2).read_text()
    rc, out, _ = run(base2, FakeBBRef(truth))
    assert rc == 1
    assert any("REFUSED: the proof failed (2022-23 vs Yahoo 2022-23" in line for line in out)
    assert ns.path(base2).read_text() == before
    rep = json.loads((base2 / "_to_delete" / "4a4" / "bbref_report.json").read_text())
    d = rep["proofs"]["2022-23 vs Yahoo 2022-23"]["diffs"]
    assert len(d) == 30 and d[0]["diffs"][0][0] == "AST"


def test_one_difference_in_thirty_passes_and_is_printed(tmp_path):
    base0, truth = world(tmp_path / "t")
    yahoo22 = list(truth["2022-23"])
    b, n, y, gp, st, t = yahoo22[5]
    yahoo22[5] = (b, n, y, gp - 1, st, t)
    base, _ = world(tmp_path / "x", truth=truth, yahoo22=yahoo22)
    rc, out, _ = run(base, FakeBBRef(truth))
    assert rc == 0
    assert any(f"differs: {n} ({y}): GP bbref {gp} vs Yahoo {gp - 1}" == line.strip() for line in out)
    assert any("29 identical in games and all eleven stats (96.7%); 1 differ" in line for line in out)


# 5 ---------------------------------------------------------------------------

def test_the_floor_never_audits_a_bbref_season(tmp_path, monkeypatch):
    base, truth = world(tmp_path)
    run(base, FakeBBRef(truth))
    monkeypatch.setattr(ns, "MIN_PLAYED", 300)
    blob = ns.read(base, stats=ORDER)
    assert all(blob["provenance"][s]["status"] == "complete" for s in BB_SEASONS), \
        "30 players a season is far under 300, and basketball-reference's seasons are never audited"
    assert blob["provenance"]["2022-23"]["status"] == "unavailable", "a Yahoo season still is"
    assert ns.load(base, seasons=BB_SEASONS)["provenance"]["2014-15"]["source"] == "basketball-reference"
    assert ns.path(base).read_text() == ns.dumps(json.loads(ns.path(base).read_text())), "reading wrote nothing"


def test_the_league_log_check_names_a_bbref_miss(tmp_path):
    base, truth = world(tmp_path)
    log = [{"season_key": "2019-20", "player_id": 1003, "player_name": "Player 1003", "had_game": True},
           {"season_key": "2019-20", "player_id": 4242, "player_name": "Nobody Matched", "had_game": True}]
    (base / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").write_text(json.dumps(log))
    rc, out, _ = run(base, FakeBBRef(truth))
    assert any("missing: Nobody Matched (4242) 2019-20 -- no basketball-reference row matched him" in line
               for line in out)
