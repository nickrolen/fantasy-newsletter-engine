"""MC2: the manager card (claude/HANDOFF_MC2_MANAGER_CARD_BUILD_2026-11-25.md).

A. One source of titles: League > All-time, Champions, the trophy case and the
   card agree (synthetic; real state too)
B. The franchise player: one definition, started games only (answer 7)
C. Money: the config's one reader; every season's nets sum to zero; 2026-27
   equals the engine's payouts; every line names its pot
D. The fuller synthetic league: every league season, consistent
E. The pre-Yahoo seasons on the card; rivalry runs (a T ends one)
F. The page: taps, the route, the lazy screens, the renderer computes nothing,
   tokens-only CSS, soft failure
"""
from __future__ import annotations

import inspect
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "scripts")]

import hub_v2_league_fixture as LF                                   # noqa: E402
from modules.hub_v2 import league as L, manager as MG                 # noqa: E402

DASH = "—"


def _world():
    import test_hub_v2 as T2
    p = T2.synth_payload()
    inp = LF.inputs(p)
    return p, inp, MG.build(inp, L.week_results(inp), LF.manager_extra())


# =============================================================================
# A. one source of titles
# =============================================================================

def _champions_counts(champ: dict) -> dict:
    out: dict = {}
    for r in champ["rows"]:
        if r["kind"] in ("played", "nobracket", "records"):
            out[r["who"]] = out.get(r["who"], 0) + 1
    return out


def _agree(inp: dict, cards: dict):
    from modules import trophy_case as TC
    results = L.week_results(inp)
    at = {r["m"]: r for r in L.alltime(inp, results)["rows"]}
    ch = _champions_counts(L.champions(inp))
    tc = {r["m"]: r["counts"] for r in TC.build(inp.get("base") or ".", past=inp.get("awards_past"),
                                                  standings=inp["all_standings"], cfg=L._trophy_cfg(inp),
                                                  managers=inp["managers"])["managers"]}
    for m in inp["managers"]:
        hon = {x["k"]: x["n"] for x in cards[m]["hero"]["hon"]}
        assert at[m]["titles"] == str(tc[m]["league"]) == hon["lc"] == str(ch.get(m, 0)), m
        assert at[m]["playoff_titles"] == str(tc[m]["playoff"]) == hon["po"], m
        lc = next(x for x in cards[m]["trophies"]["case"] if x["k"] == "league")
        assert lc["n"] == hon["lc"]
        assert cards[m]["hero"]["kpis"][0]["v"] == at[m]["record"] and cards[m]["hero"]["kpis"][1]["v"] == at[m]["pct"]


@pytest.mark.slow
def test_one_source_of_titles_on_the_synthetic_league():
    _p, inp, out = _world()
    _agree(inp, out["cards"])
    # the fixture's LEAGUEHISTORY agrees too (MC1 found All-time 0 against Champions 3)
    lh = {r["manager_name"]: r for r in inp["leaguehistory"]}
    for m in inp["managers"]:
        hon = {x["k"]: x["n"] for x in out["cards"][m]["hero"]["hon"]}
        assert str(lh[m]["titles_won"]) == hon["lc"] and str(lh[m]["playoff_championships"]) == hon["po"]


@pytest.mark.slow
def test_alltime_titles_are_the_trophy_cases_not_leaguehistorys():
    _p, inp, _out = _world()
    inp["leaguehistory"] = [dict(r, titles_won=99) for r in inp["leaguehistory"]]
    rows = L.alltime(inp, L.week_results(inp))["rows"]
    assert all(r["titles"] != "99" for r in rows)
    inp["all_standings"] = [dict(r, regular_season_rank=None) for r in inp["all_standings"]]   # the case fails
    rows = L.alltime(inp, L.week_results(inp))["rows"]
    assert all(r["titles"] == DASH for r in rows)                 # never a second source


@pytest.mark.slow
@pytest.mark.real
def test_one_source_of_titles_and_the_money_on_the_real_league():
    from modules.data_loader import load_all_data
    from modules import hub_state
    from modules.hub_v2 import data as v2data
    p = v2data.attach_players(hub_state.load(ROOT), hub_state.load_players(ROOT / hub_state.PAYLOAD_RELPATH))
    data = load_all_data(ROOT, current_week=None)
    inp = L.gather(ROOT, data=data, power=p["power"], managers=list(p["v2"]["team_order"]), teams=p["v2"]["teams"],
                   newsletter=p["newsletter"], now=datetime.fromisoformat(p["generated_at"]), live=None)
    out = MG.build(inp, L.week_results(inp), MG.manager_inputs(ROOT, schedule=data.schedule))
    _agree(inp, out["cards"])
    _money_sums(out)
    for m, c in out["cards"].items():
        assert "2015-16" not in json.dumps([c["overview"]["strip"]["cells"], c["career"]["rows"]])


# =============================================================================
# B. the franchise player
# =============================================================================

def test_the_franchise_player_counts_his_started_games_only():
    import pandas as pd
    import backfill_player_records as B

    def row(p, m, s, d, fp, started):
        return {"player_name": p, "manager": m, "season_year": s, "week": 1, "date": d, "fantasy_points": fp,
                "started": started, "slot": "UTIL" if started else "BN"}
    hist = [row("Starter", "Marcus", "2024-2025", f"2024-11-{d:02d}", 40.0, True) for d in range(1, 11)]
    # a bench player who scored more, all on the bench: never a game for him
    hist += [row("Bencher", "Marcus", "2024-2025", f"2024-11-{d:02d}", 90.0, False) for d in range(1, 11)]
    hist += [row("Bencher", "Marcus", "2025-2026", "2025-11-01", 50.0, True)]
    games = B.build_combined_playerlog(hist, pd.DataFrame())
    fb = B.franchise_badges_from(games)
    assert fb["Marcus"] == {"player": "Starter", "total_fp": 400.0, "gp": 10, "seasons": 1, "first": "2024-25",
                            "last": "2024-25"}
    # the record book's leaderboards use the one definition
    src = inspect.getsource(B.compute_expanded_leaderboards)
    assert "franchise_badges = franchise_badges_from(games)" in src


# =============================================================================
# C. money
# =============================================================================

def test_money_reads_one_table_per_season_and_raises_outside_it():
    from modules import money as MO
    assert MO.table("2016-17")["regular_season"] == {"1": 150, "2": -50, "3": -50, "4": -50}
    assert MO.table("2025-26")["playoffs"] == {"champion": 75, "runner_up": -25, "semifinal_loser": -25}
    assert MO.table("2026-27")["regular_season"] == {"1": 180, "2": 0, "3": -90, "4": -90}
    assert MO.table("2030-31")["playoffs"] == {"champion": 90, "runner_up": 0, "semifinal_loser": -45}
    with pytest.raises(MO.MoneyError, match="no range for 2013-14"):
        MO.table("2013-14")
    MO.check_engine_payouts("2026-27")                     # equals config payouts (the engine's own)
    from modules.data_loader import _LEAGUE_CONFIG
    bad = json.loads(json.dumps(_LEAGUE_CONFIG))
    bad["payouts"]["league_champion"]["total"] = 200
    with pytest.raises(MO.MoneyError, match="disagrees with payouts.league_champion"):
        MO.check_engine_payouts("2026-27", bad)
    bad = json.loads(json.dumps(_LEAGUE_CONFIG))
    bad["payouts_by_season"]["ranges"][0]["regular_season"]["2"] = -40
    with pytest.raises(MO.MoneyError, match="sum to"):
        MO.table("2020-21", bad)


def _money_sums(out: dict):
    seasons = {r["s"] for c in out["cards"].values() for r in c["trophies"]["money"]["rows"]}
    assert seasons
    for s in seasons:
        tot = 0
        for c in out["cards"].values():
            r = next(x for x in c["trophies"]["money"]["rows"] if x["s"] == s)
            tot += int(r["net"].replace("−", "-").replace("$", "").replace("+", "").replace(",", ""))
        assert tot == 0, s
    for c in out["cards"].values():
        for r in c["trophies"]["money"]["rows"]:
            assert r["reg"].startswith("Regular season: ") and r["po"].startswith("Playoffs: ")    # the Language rule
            assert not re.search(r"\b(safe|certain)\b", r["reg"] + r["po"], re.I)


@pytest.mark.slow
def test_money_nets_sum_to_zero_and_name_their_pot():
    _p, inp, out = _world()
    _money_sums(out)
    rows = {r["s"]: r for r in out["cards"]["Marcus"]["trophies"]["money"]["rows"]}
    assert "2026-27" not in rows                            # this season: nothing until a pot is decided
    assert rows["2023-24"]["po"].startswith("Playoffs: no playoff pot (a made-up stoppage)")
    assert rows["2014-15"]["reg"] == "Regular season: +$150 (1st)"          # the League Champion
    assert rows["2014-15"]["po"] == "Playoffs: −$25 (runner-up)"       # paid like anyone else before 2026-27


# =============================================================================
# D. the fuller synthetic league
# =============================================================================

@pytest.mark.slow
def test_the_synthetic_league_plays_every_season_consistently():
    from modules.data_loader import standings_order, Record
    _p, inp, _out = _world()
    seasons = sorted({r["season"] for r in inp["all_standings"]})
    assert seasons == LF.YAHOO and set(inp["pre_data_era"]["seasons"]) == {"2014-15", "2016-17"}
    assert seasons[0] == "2017-18" and seasons[-1] == "2025-26"
    # the standings are the games' (the one ranking rule), the brackets the games' too
    assert LF.world_standings(inp["all_matchups"]) == inp["all_standings"]
    # the careers: the pre-Yahoo seasons plus the Yahoo seasons (League's own check)
    L.check_pre_era_careers(L.pre_era_seasons(inp["pre_data_era"]), inp["leaguehistory"], inp["all_standings"],
                            inp["managers"])
    # Champions has a row for every season with results, newest first, no 2015-16
    rows = [r["season"] for r in L.champions(inp)["rows"]]
    assert rows == ["2026-27"] + LF.YAHOO[::-1] + ["2016-17", "2014-15"]


# =============================================================================
# E. the pre-Yahoo seasons; rivalries
# =============================================================================

@pytest.mark.slow
def test_the_pre_yahoo_seasons_on_the_card():
    _p, inp, out = _world()
    c = out["cards"]["Marcus"]
    cells = {x["s"]: x for x in c["overview"]["strip"]["cells"]}
    assert cells["2014-15"]["kind"] == "pre" and cells["2014-15"]["place"] == "1"
    assert cells["2016-17"]["kind"] == "pre" and cells["2016-17"]["place"] == "2"
    assert "2015-16" not in cells and "2015-16 was not played" in c["overview"]["strip"]["note"]
    assert "Standings and brackets only." in cells["2014-15"]["tip"]
    rows = {r["s"]: r for r in c["career"]["rows"]}
    assert rows["2014-15"]["wl"] == "14-7" and rows["2014-15"]["ppw"] == DASH and rows["2014-15"]["pre"]
    assert rows["2014-15"]["fin"] == "1st ★" and rows["2014-15"]["po"] == "Final"
    assert "Old Cannons" in rows["2014-15"]["team"]
    hatched = [b for b in c["career"]["ppw"]["bars"] if b["cls"] == "mc-hatch"]
    assert len(hatched) == 2                                 # no points bar: hatched, "standings only"
    names = [n["t"] for n in c["hero"]["names"]]
    assert names[-1] == "Old Cannons · 2014-15" and names[0].startswith("Glass Cannons")
    # the postseason counts the pre-Yahoo brackets, marked; the regular season starts in 2017-18
    post = {r["o"]: r for r in c["rivals"]["phases"][1]["rows"]}
    assert post["Dana"]["pre"] and "2014-15 and 2016-17 brackets" in c["rivals"]["phases"][1]["intro"]
    assert "starts in 2017-18" in c["rivals"]["phases"][0]["intro"]


def test_a_rivalry_run_crosses_seasons_and_a_t_ends_it():
    g = [{"season": "2020-21", "week": w, "a": "A", "b": "B", "sa": s, "sb": 100.0, "pre": False, "label": "", "k": 0}
         for w, s in ((20, 120.0), (21, 130.0))]
    g += [{"season": "2021-22", "week": 1, "a": "B", "b": "A", "sa": 90.0, "sb": 95.0, "pre": False, "label": "", "k": 0},
          {"season": "2021-22", "week": 2, "a": "A", "b": "B", "sa": 100.0, "sb": 100.0, "pre": False, "label": "", "k": 0},
          {"season": "2021-22", "week": 3, "a": "A", "b": "B", "sa": 101.0, "sb": 100.0, "pre": False, "label": "", "k": 0}]
    r = MG.runs(g, "A", "B")
    assert r["A"][0] == 3 and r["A"][1]["season"] == "2020-21" and r["A"][2]["season"] == "2021-22"
    assert r["B"][0] == 0


# =============================================================================
# F. the page
# =============================================================================

def _render():
    import test_hub_v2 as T2
    from modules.hub_v2 import view, page
    p = T2.synth_payload()
    return p, page.render(view.build(p, mode="preview", now=T2.GEN))


@pytest.mark.slow
def test_the_card_route_taps_and_names():
    from modules.hub_v2 import page
    import test_hub_v2 as T2
    _p, h = _render()
    for m in LF.MGRS:
        assert f'data-route="manager/{m}"' in h
    assert not T2.tap_violations(h)
    # the route: #/manager/<name> and #/manager/<name>/<tab>
    assert "if(parts[0]==='manager'&&parts[1]){want='manager/'+decodeURIComponent(parts[1]);" \
           "seen['mgr']=parts[2]||'overview';}" in page.script()
    # Standings: the mark opens the team, the name opens the card
    st = h[h.index('data-section="standings"'):h.index('data-section="title-odds"')]
    for m in LF.MGRS:
        assert f'<a class="v2-tap" href="#/teams/{m}"' in st and f'<a class="v2-mn v2-tap" href="#/manager/{m}">{m}</a>' in st
    # the Matchups cards stay one link to the matchup
    home = h[h.index('data-route="home"'):h.index('data-route="matchups"')]
    for card in re.findall(r'<a class="lh-card[^"]*"[^>]*>.*?</a>', home, re.S):
        assert "v2-mn" not in card
    # the team page's header name opens the card; the card's hero has Team page
    assert re.search(r'data-route="teams/Marcus".*?<span class="lh-meta"><a class="v2-mn v2-tap" href="#/manager/Marcus">'
                     r'Marcus</a> &middot;', h, re.S)
    assert 'href="#/teams/Marcus">Team page &rsaquo;</a>' in h
    # Back: history, or League > History > All-time from a link
    assert 'data-back="#/league/history/alltime"' in h


@pytest.mark.slow
def test_the_cards_are_lazy_screens_and_their_links_resolve(tmp_path):
    import test_hub_v2 as T2
    from test_hub_v2_players import synth_cards
    from modules.hub_v2 import publish as v2pub, publish_check as pc
    base = tmp_path / "base"
    base.mkdir()
    e = T2._archive(base)
    p = T2.synth_payload()
    p["v2"]["issue"]["file"] = e["enc"]
    p["newsletter"]["current"]["file"] = e["enc"]
    out = tmp_path / "_to_delete" / "pub"
    rep = v2pub.build(base, p, T2.PASS, salt=b"\x09" * 16, out_dir=out, iterations=1000, terms=T2.TERMS, now=T2.GEN,
                      pictures=[], cards=synth_cards(p))
    parts = {k: v for k, v in rep["screen_parts"].items() if k.startswith("manager/")}
    assert sorted(parts) == [f"manager/{m}" for m in sorted(LF.MGRS)]
    assert all(n <= v2pub.LAZY_CAP_BYTES for n in parts.values())
    assert rep["served_bytes"] <= v2pub.budget_bytes()
    page = pc.open_page((out / "index.html").read_text(encoding="utf-8"), T2.PASS)["page"]
    assert "mc-hero" not in page                              # only the top bar is in the first load
    assert pc.routes(page + '<a href="#/manager/Marcus/rivals">')["unresolved"] == []


def test_the_renderer_computes_nothing_and_its_css_is_tokens_only():
    from modules.hub_v2 import page_manager as PM, tokens
    src = inspect.getsource(PM)
    assert not re.search(r"\b(round|float|sum|sorted|max|min|int|len)\(", src)
    for css in (PM.CSS, PM.MGR_LINK_CSS):
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)
        assert not re.search(r"\d+px", css)
    tokens.fill(PM.CSS)                                      # every {{token}} is known


@pytest.mark.slow
def test_the_card_fails_softly_and_names_itself():
    from modules.hub_v2 import data as v2data
    _p, inp, _out = _world()
    bad = dict(inp, all_standings=[dict(r, playoff_rank=9) for r in inp["all_standings"]])
    r = MG.build_soft(bad, extra=LF.manager_extra())
    assert r["cards"] == {} and "ManagerError" in r["error"]
    p = {"v2": {"league": {"managers": r}}}
    assert any(x.startswith("Manager cards couldn't update: ManagerError") for x in v2data.soft_notes(p))
    # no cards: names stay plain
    import test_hub_v2 as T2
    from modules.hub_v2 import view, page
    q = T2.synth_payload()
    q["v2"]["league"]["managers"] = r
    h = page.render(view.build(q, mode="preview", now=T2.GEN))
    assert "v2-mn" not in h.split("<script")[0].split("</style>")[-1] and 'data-route="manager/' not in h


@pytest.mark.slow
def test_the_cards_strings_pass_the_champion_and_rule_audits():
    from modules.hub_v2 import publish_check as PC
    _p, h = _render()
    pieces = {"page": h}
    assert PC.champion_audit(pieces) == [] and PC.rule_audit(pieces) == []
    txt = PC.visible_text(h[h.index('data-route="manager/Marcus"'):h.index('data-route="manager/Tyler"')])
    assert not PC.OBJECT_TEXT.search(txt) and not PC.EMPTY_TEXT.search(txt)
