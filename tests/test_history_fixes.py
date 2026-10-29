"""Two fixes to the league history (HANDOFF_HISTORY_FIXES_2026-10-29).

1. No keeper before keeper_era_start: the draft writers raise on one, and
   2020-21 -- drafted from the full pool, the first keepers chosen after it --
   has none.
2. One NBA team per player per day, switching once per move, on the move's
   date (enrich_historical_playerlog): no flip-flopping after a trade, and no
   team game a team did not play.
"""
import json
import sys
import types
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import data_loader as dl                         # noqa: E402

pytest.importorskip("yahoo_oauth")
pytest.importorskip("yahoo_fantasy_api")
import pull_historical_data as P                              # noqa: E402
import enrich_historical_playerlog as E                       # noqa: E402


def _pick(season, n, keeper=False, name=None, rnd=None):
    return {"season": season, "pick_number": n, "round": rnd or (n - 1) // 4 + 1, "manager": "Nick",
            "player_key": str(1000 + n), "player_name": name or f"P{n}", "is_keeper": keeper}


# 1 -- keepers -------------------------------------------------------------
def test_a_keeper_before_the_keeper_era_raises_everywhere_it_could_be_written():
    assert dl.KEEPER_ERA_START == "2021-22"
    with pytest.raises(dl.KeeperBeforeEra, match="2020-21"):
        dl.check_keeper_era([_pick("2020-21", 30, keeper=True)])
    dl.check_keeper_era([_pick("2021-22", 30, keeper=True), _pick("2020-21", 30)])     # fine
    with pytest.raises(dl.KeeperBeforeEra):
        P._merge_drafts([], [_pick("2019-20", 1, keeper=True)], "2019-20")
    src = (ROOT / "scripts" / "rollup_season_to_history.py").read_text(encoding="utf-8")
    assert "check_keeper_era(new_rows)" in src                  # the season-end writer, too


def test_the_pull_flags_no_pre_era_keeper_and_carries_era_flags_or_raises():
    yahoo = [{k: v for k, v in _pick("2020-21", n).items() if k != "is_keeper"} for n in (1, 30)]
    stale = [_pick("2020-21", 1), _pick("2020-21", 30, keeper=True)]   # the old rounds-8+ rule
    out = P.flag_keepers("2020-21", yahoo, stale)
    assert [p["is_keeper"] for p in out] == [False, False]
    era_yahoo = [{**p, "season": "2022-23"} for p in yahoo]
    on_disk = [_pick("2022-23", 1), _pick("2022-23", 30, keeper=True)]
    assert [p["is_keeper"] for p in P.flag_keepers("2022-23", era_yahoo, on_disk)] == [False, True]
    with pytest.raises(ValueError, match="no keeper flags"):         # Yahoo cannot supply them
        P.flag_keepers("2022-23", era_yahoo, [])
    with pytest.raises(ValueError, match="does not match"):
        P.flag_keepers("2022-23", era_yahoo, [_pick("2022-23", 1), _pick("2022-23", 31, keeper=True)])


def test_a_re_pull_rewrites_one_season_in_place_and_is_deterministic():
    existing = [_pick(s, n, keeper=(s >= "2021-22" and n > 28)) for s in ("2019-20", "2020-21", "2021-22")
                for n in (1, 29)]
    existing[3]["is_keeper"] = True                                  # a stale 2020-21 flag
    fresh = [{k: v for k, v in _pick("2020-21", n).items() if k != "is_keeper"} for n in (29, 1)]
    a = P._merge_drafts(existing, P.flag_keepers("2020-21", fresh, existing), "2020-21")
    b = P._merge_drafts(a, P.flag_keepers("2020-21", fresh, a), "2020-21")
    assert a == b
    assert [(d["season"], d["pick_number"]) for d in a] == [(d["season"], d["pick_number"]) for d in existing]
    assert not any(d["is_keeper"] for d in a if d["season"] == "2020-21")


def test_the_regenerated_drafts_have_no_keeper_before_2021_22():
    drafts = json.loads((ROOT / "data" / "historical" / "all_drafts.json").read_text(encoding="utf-8"))
    dl.check_keeper_era(drafts)
    by = defaultdict(int)
    for d in drafts:
        by[d["season"]] += bool(d["is_keeper"])
    assert by["2020-21"] == 0 and sum(1 for d in drafts if d["season"] == "2020-21") == 52
    assert all(by[s] == 24 for s in ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26"))


# 2 -- one team per day ----------------------------------------------------
TX = ('<li><span>February 9, 2023</span>'
      '<p>In a 4-team trade, the <a data-attr-from="BRK" href="/t">Brooklyn Nets</a> traded '
      '<a href="/players/d/duranke01.html">Kevin Durant</a> and <a href="/players/w/x.html">T.J. Warren</a> '
      'to the <a data-attr-to="PHO" href="/t">Phoenix Suns</a>; the <a data-attr-from="IND" href="/t">Indiana '
      'Pacers</a> traded a 2024 2nd round draft pick (<a href="/players/k/k.html">Pick Guy</a> was later '
      'selected) to the <a data-attr-to="BRK" href="/t">Brooklyn Nets</a>; and  the <a data-attr-from="PHO" '
      'href="/t">Phoenix Suns</a> traded <a href="/players/b/b.html">Mikal Bridges</a> to the '
      '<a data-attr-to="BRK" href="/t">Brooklyn Nets</a>.</p>'
      '<p>The <a data-attr-from="LAL" href="/t">Los Angeles Lakers</a> traded <a href="/players/w/w.html">'
      'Russell Westbrook</a> to the <a data-attr-to="UTA" href="/t">Utah Jazz</a> for '
      '<a href="/players/r/r.html">Mike Conley</a>.</p></li>'
      '<li><span>February 22, 2023</span><p>The <a data-attr-to="LAC" href="/t">Los Angeles Clippers</a> '
      'signed <a href="/players/w/w.html">Russell Westbrook</a>.</p>'
      '<p>The <a data-attr-to="MIA" href="/t">Miami Heat</a> claimed <a href="/players/s/s.html">D.J. '
      'Stewart Jr.</a> on waivers from the <a data-attr-from="DAL" href="/t">Dallas Mavericks</a>.</p></li>')


def test_transactions_parse_every_arrival_and_nothing_else():
    ev = {(e["player"], e["to"], e["date"], e["kind"]) for e in E.parse_transactions(TX)}
    assert ev == {("Kevin Durant", "PHX", "2023-02-09", "trade"), ("T.J. Warren", "PHX", "2023-02-09", "trade"),
                  ("Mikal Bridges", "BKN", "2023-02-09", "trade"),           # the "; and the" clause
                  ("Russell Westbrook", "UTA", "2023-02-09", "trade"),
                  ("Mike Conley", "LAL", "2023-02-09", "trade"),            # the "for" side
                  ("Russell Westbrook", "LAC", "2023-02-22", "signed"),
                  ("D.J. Stewart Jr.", "MIA", "2023-02-22", "claimed")}     # no "Pick Guy"
    assert E.parse_transactions(TX) == E.parse_transactions(TX)


def test_a_move_is_dated_from_its_transaction_or_raises():
    moves = E.moves_by_player({"events": E.parse_transactions(TX)})
    games = {"2023-02-07": "BKN", "2023-03-01": "PHX", "2023-03-03": "PHX"}
    st = E.season_stints(games, moves["kevin durant"])
    assert st == [("", "BKN", "first game"), ("2023-02-09", "PHX", "transaction")]
    assert E.team_on(st, "2023-02-08") == "BKN" and E.team_on(st, "2023-02-09") == "PHX"
    rw = E.season_stints({"2023-02-07": "LAL", "2023-02-27": "LAC"}, moves["russell westbrook"])
    assert [t for _, t, _ in rw] == ["LAL", "UTA", "LAC"]                    # through Utah
    assert E.move_key(E.normalize_name("Jimmy Butler III")) == "jimmy butler"
    with pytest.raises(E.UnplaceableMove, match="BKN -> PHX"):
        E.season_stints(games, [])


def _durant_world():
    """Durant: BKN until the trade on 02-09, hurt, first PHX game 03-01."""
    dates = [f"2023-02-{d:02d}" for d in range(1, 29)] + [f"2023-03-{d:02d}" for d in range(1, 6)]
    bkn = {d for i, d in enumerate(dates) if i % 2 == 0}                     # BKN plays every other day
    phx = {d for i, d in enumerate(dates) if i % 2 == 1}                     # PHX the others
    played = {"2023-02-01": "BKN", "2023-02-03": "BKN", "2023-03-02": "PHX", "2023-03-04": "PHX"}
    sched = defaultdict(dict)
    for d in bkn:
        sched[d]["BKN"] = "NYK"
    for d in phx:
        sched[d]["PHX"] = "LAL"
    lookup = {"kevin durant": {d: {"team": t, "opponent": sched[d][t]} for d, t in played.items()}}
    rows = [{"season_year": "2022-2023", "season_key": "2022-23", "date": d, "player_name": "Kevin Durant",
             "fantasy_points": 40.0 if d in played else 0.0, "nba_team": "?", "nba_opponent": "?",
             "had_game": None, "is_injured": None} for d in dates]
    moves = {"2022-23": E.moves_by_player({"events": E.parse_transactions(TX)})}
    return rows, lookup, sched, moves, bkn, phx


def test_durant_switches_once_on_the_trade_date_and_misses_only_his_own_teams_games():
    rows, lookup, sched, moves, bkn, phx = _durant_world()
    out, stats = E.enrich_rows(rows, lookup, {"kevin durant": "Kevin Durant"}, sched, {"2022-23"}, moves=moves)
    E.verify_enriched(out, sched, stats["stints"], {"2022-23"})
    teams = [r["nba_team"] for r in sorted(out, key=lambda r: r["date"])]
    changes = [(out[i + 1]["date"], a, b) for i, (a, b) in enumerate(zip(teams, teams[1:])) if a != b]
    assert changes == [("2023-02-09", "BKN", "PHX")]
    for r in out:
        own = bkn if r["date"] < "2023-02-09" else phx
        assert r["had_game"] == (r["date"] in own)
        assert r["is_injured"] == (r["had_game"] and r["fantasy_points"] == 0)


def test_the_check_catches_a_flip_or_a_game_his_team_did_not_play():
    rows, lookup, sched, moves, bkn, phx = _durant_world()
    out, stats = E.enrich_rows(rows, lookup, {"kevin durant": "Kevin Durant"}, sched, {"2022-23"}, moves=moves)
    flipped = [dict(r) for r in out]
    late = next(r for r in flipped if r["date"] > "2023-02-10" and not r["had_game"])
    late["nba_team"], late["nba_opponent"], late["had_game"] = "BKN", sched[late["date"]].get("BKN", "NYK"), True
    with pytest.raises(AssertionError):
        E.verify_enriched(flipped, sched, stats["stints"], {"2022-23"})


def test_enrichment_is_deterministic():
    def once():
        rows, lookup, sched, moves, _, _ = _durant_world()
        return E.enrich_rows(rows, lookup, {"kevin durant": "Kevin Durant"}, sched, {"2022-23"},
                             moves=moves)[0]
    assert json.dumps(once(), sort_keys=True) == json.dumps(once(), sort_keys=True)


def test_a_failed_fetch_raises_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "CACHE_DIR", tmp_path)

    def down(url):
        raise OSError("connection refused")
    with pytest.raises(RuntimeError, match="NBA_2023_transactions"):
        E.fetch_transactions("2022-23", fetch=down)
    with pytest.raises(RuntimeError, match="parsed to no transactions"):
        E.fetch_transactions("2022-23", fetch=lambda url: "<html></html>")

    class Down:
        def __init__(self, **kw):
            raise ConnectionError("reset")
    fake = types.ModuleType("nba_api.stats.endpoints")
    fake.LeagueGameLog = Down
    for name in ("nba_api", "nba_api.stats"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "nba_api.stats.endpoints", fake)
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="2022-23: failed"):
        E.fetch_season_game_logs("2022-23", max_retries=2)
    assert list(tmp_path.iterdir()) == []


def _history():
    return json.loads((ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").read_text(encoding="utf-8"))


def test_the_history_has_one_team_per_day_switching_only_on_a_move():
    """On the regenerated file: no player-season's team changes more than its
    distinct teams allow (a flip back and forth fails), Durant 2022-23
    switches once, on 2023-02-09."""
    seq = defaultdict(list)
    for r in _history():
        if r["nba_team"]:
            seq[(r["season_key"], r["player_name"])].append((r["date"], r["nba_team"]))
    bad = []
    for k, v in seq.items():
        teams = [t for _, t in sorted(v)]
        changes = sum(1 for a, b in zip(teams, teams[1:]) if a != b)
        if changes > 2 * (len(set(teams)) - 1):          # A->B, or A->B->A on a return
            bad.append((k, changes))
    assert not bad, bad[:10]
    durant = sorted(seq[("2022-23", "Kevin Durant")])
    assert [(durant[i + 1][0], a[1], b[1]) for i, (a, b) in enumerate(zip(durant, durant[1:])) if a[1] != b[1]] \
        == [("2023-02-09", "BKN", "PHX")]


def test_no_team_games_count_exceeds_a_real_schedule():
    """Every had_game row agrees with every other row about who its team
    played that day, and no player-season has more team games than any team
    played that season -- plus TRADE_SLACK for a player who changed teams."""
    rows = _history()
    opp, games, teams = {}, defaultdict(int), defaultdict(set)
    for r in rows:
        if r["nba_team"]:
            teams[(r["season_key"], r["player_name"])].add(r["nba_team"])
        if r["had_game"]:
            key = (r["date"], r["nba_team"])
            assert opp.setdefault(key, r["nba_opponent"]) == r["nba_opponent"], key
            games[(r["season_key"], r["player_name"])] += 1
    over = [(k, g) for k, g in games.items()
            if g > 82 + (E.TRADE_SLACK if len(teams[k]) > 1 else 0)]
    assert not over, sorted(over, key=lambda kv: -kv[1])[:8]


# 2b -- the basketball-reference source (the default; stats.nba.com resets) --
def test_waivers_and_extensions_parse_and_same_day_order_is_the_pages():
    page = ('<li><span>February 6, 2025</span>'
            '<p>The <a data-attr-to="MIA" href="/t">Miami Heat</a> signed <a href="/players/b/b.html">'
            'Jimmy Butler</a> to a contract extension.</p>'
            '<p>The <a data-attr-from="MIA" href="/t">Miami Heat</a> traded <a href="/players/b/b.html">'
            'Jimmy Butler</a> to the <a data-attr-to="GSW" href="/t">Golden State Warriors</a>.</p>'
            '<p>The <a data-attr-from="UTA" href="/t">Utah Jazz</a> waived <a href="/players/w/w.html">'
            'Russell Westbrook</a>.</p></li>')
    ev = E.parse_transactions(page)
    assert [(e["player"], e["to"], e["from"], e["kind"]) for e in ev] == [
        ("Jimmy Butler", "GSW", "MIA", "trade"),                 # the extension moved no one
        ("Russell Westbrook", "", "UTA", "waived")]


def test_the_cup_final_is_found_alone_and_anything_else_raises():
    g = [("2023-12-07", "MIL", "IND", "In-Season Tournament"), ("2023-12-07", "NOP", "LAL", "In-Season Tournament"),
         ("2023-12-09", "IND", "LAL", "In-Season Tournament"), ("2023-12-09", "BOS", "NYK", "")]
    assert E.cup_final(g) == ("2023-12-09", "IND", "LAL")
    assert E.cup_final([("2018-12-09", "BOS", "NYK", "")]) is None
    with pytest.raises(ValueError, match="not alone"):
        E.cup_final(g[:2])


def test_bbref_stints_follow_moves_waivers_and_a_trade_before_he_played():
    moves = [("2023-02-09", "UTA", "LAL"), ("2023-02-20", "", "UTA"), ("2023-02-22", "LAC", ""),
             ("2022-07-01", "LAL", "")]                                       # offseason: ignored
    st = E.bbref_stints(["LAL", "LAC"], moves, "2022-10-18")
    assert [(d, t) for d, t, _ in st] == [("", "LAL"), ("2023-02-09", "UTA"), ("2023-02-20", ""),
                                          ("2023-02-22", "LAC")]
    # traded on 12-01 before ever playing for his old team: he began on the old one
    st = E.bbref_stints(["DAL"], [("2022-12-01", "DAL", "WAS")], "2022-10-18")
    assert [(d, t) for d, t, _ in st] == [("", "WAS"), ("2022-12-01", "DAL")]
    with pytest.raises(E.UnplaceableMove):
        E.bbref_stints(["BKN", "PHX"], [], "2022-10-18")
    assert E.bbref_stints([], moves, "2022-10-18") == []


def test_per_game_teams_come_in_order_without_the_combined_rows():
    row = lambda n, t: (f'<tr><td data-stat="name_display"><a href="x">{n}</a></td>'
                        f'<td data-stat="team_name_abbr"><a href="x">{t}</a></td></tr>')
    page = ('<table id="per_game_stats">' + row("Kevin Durant", "2TM") + row("Kevin Durant", "BRK")
            + row("Kevin Durant", "PHO") + row("Nikola Joki&#263;", "DEN") + "</table>")
    assert E.parse_per_game_teams(page) == {"Kevin Durant": ["BKN", "PHX"], "Nikola Jokić": ["DEN"]}


def _bbref_world(fp_on_trade_day=0.0):
    sched = {"2022-23": {"2023-02-08": {"BKN": "NYK", "NYK": "BKN"}, "2023-02-10": {"PHX": "LAL", "LAL": "PHX"},
                         "2023-02-11": {"BKN": "MIA", "MIA": "BKN"}}}
    teams = {"2022-23": {"Kevin Durant": ["BKN", "PHX"]}}
    moves = {"2022-23": {"kevin durant": [("2023-02-09", "PHX", "BKN")]}}
    rows = [{"season_year": "2022-2023", "date": d, "player_name": "Kevin Durant", "fantasy_points": fp,
             "nba_team": "?", "nba_opponent": "?", "had_game": None, "is_injured": None}
            for d, fp in (("2023-02-08", 50.0), ("2023-02-10", 0.0), ("2023-02-11", fp_on_trade_day))]
    return rows, sched, teams, moves


def test_bbref_enrichment_switches_on_the_trade_and_checks_every_scoring_day():
    rows, sched, teams, moves = _bbref_world()
    out, stats = E.enrich_rows_bbref(rows, {"2022-23"}, sched, teams, moves)
    assert [(r["nba_team"], r["nba_opponent"], r["had_game"], r["is_injured"]) for r in out] == [
        ("BKN", "NYK", True, False), ("PHX", "LAL", True, True), ("PHX", "", False, False)]
    rows, sched, teams, moves = _bbref_world(fp_on_trade_day=30.0)   # scored on a day PHX did not play
    with pytest.raises(E.UnplaceableMove, match="PHX did not play"):
        E.enrich_rows_bbref(rows, {"2022-23"}, sched, teams, moves)


def test_a_failed_bbref_page_raises_and_writes_nothing(tmp_path, monkeypatch):
    import urllib.error
    monkeypatch.setattr(E, "CACHE_DIR", tmp_path)

    def down(url):
        raise OSError("reset")
    with pytest.raises(RuntimeError, match="per_game"):
        E.bbref_teams("2022-23", fetch=down)

    def missing(url):
        raise urllib.error.HTTPError(url, 404, "nf", None, None)
    assert E.bbref_get("https://x/july", "july.html", fetch=missing, allow_404=True) is None
    with pytest.raises(RuntimeError, match="HTTP 404"):
        E.bbref_get("https://x/per_game", "pg.html", fetch=missing)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["july.html"]       # the 404 marker only
