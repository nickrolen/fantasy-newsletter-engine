"""4c1: the ratings on the hub, the Players tab, the new player card and Compare
(claude/HANDOFF_4C1_PLAYERS_2026-11-18.md s.7). Synthetic where the rule is
logic -- the made-up league of tests/test_hub_v2.py, whose Players block the
REAL engine path builds (players.build on made-up inputs) -- and one real,
unstubbed test on today's state (slow; it skips without the state)."""

import html as _html
import inspect
import copy
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import league_state                                    # noqa: E402,F401
from test_hub_v2 import (synth_payload, _synth_payload_4b, add_synth_players, render, visible_text, strings,
                         tap_violations, budget_bytes, _archive, dyn_route, ALL_CSS, GEN, PASS, TERMS, ROOT,
                         FA_NAME, FA_KEY, MGRS)

from modules.hub_v2 import (players as P, card as C, page_players as PP, page, view, publish as v2pub, tokens,
                            infotips, data as v2data)
from modules import ratings

DASH = "\u2014"


# =============================================================================
# synthetic cards: hub_cards.build's shape, for the synthetic Players rows
# =============================================================================

def synth_cards(p: dict) -> dict:
    from modules.data_loader import CURRENT_SEASON
    cards = {}
    for z in p["v2"]["players"]["rows"]:
        fppg = float(z["fppg"]) if z["fppg"] != DASH else None
        games = [{"date": (GEN.date() - timedelta(days=10 - i)).isoformat(), "fp": 30.0 + i, "injured": i == 3,
                  "season": CURRENT_SEASON} for i in range(6)]
        cards[z["key"]] = {
            "player_name": z["name"], "positions": z["pos"], "nba_team": "AAA",
            "age": None if z["age"] == DASH else int(z["age"]), "manager": z["m"],
            "keep_k5_pct": z["keep"] if z["kind"] == "rostered" else None,
            "keep_text": "70% to be kept \u2014 2nd on the roster" if z["kind"] == "rostered" else None,
            "current_season": None if fppg is None else {"fppg": fppg, "gp": int(z["gp"]), "total_fp": 404.0,
                                                         "proj_fppg": 30.0, "efficiency_pct": 100.0, "source": "nba"},
            "season_comps": {"previous_fppg": 28.5},
            "league_season": {"text": "On a league roster: 27.5 FPPG in 8 games"} if z["kind"] == "fa" else None,
            "sparkline": [{"date": "2025-01-01", "fp": 77.7, "injured": False, "season": "2024-25"}] + games,
            "last_10": [{"date": g["date"], "opponent": "@BBB", "fp": g["fp"], "injured": g["injured"]}
                        for g in reversed(games)],
            "career": {"seasons_played": 2, "career_gp": 70, "career_fp": 2100.0, "career_fppg": 30.0,
                       "season_breakdown": [{"season": "2025-26", "gp": 60, "total_fp": 1700.0, "fppg": 28.3,
                                             "managers": ["Marcus"]},
                                            {"season": CURRENT_SEASON, "gp": int(z["gp"]), "total_fp": 404.0,
                                             "fppg": fppg or 0.0, "managers": [z["m"]] if z["m"] else []}]},
            "ownership_timeline": [{"season": "2025-26", "events": [{"manager": "Marcus", "acquired_via": "draft"}]}],
            "draft_history": [{"season": "2025-26", "pick_number": 12, "round": 3, "manager": "Marcus",
                               "is_keeper": False, "expected_fppg": 25.0, "actual_fppg": 28.3, "roi": 3.3,
                               "roi_label": "Good Value"}],
            "trade_history": [], "record_book": [{"record": "Best Game", "rank": 2, "value": 77.7, "season": "2024-25",
                                                  "detail": "2024-25 | for Marcus"}],
            "archetype": "Generational Big",            # the OLD card's archetype: never shown
            "status": p["cards"]["players"][z["key"]]["status"], "card": z["key"]}
    return {"cards": cards, "photos": {}}


@pytest.fixture(scope="module")
def syn():
    p = synth_payload()
    return p, synth_cards(p)


def _rows(p):
    return p["v2"]["players"]["rows"]


def pl_name(p, riser):
    return p["v2"]["players"]["rows"][riser["i"]]["name"]


def _row(p, name):
    return next(z for z in _rows(p) if z["name"] == name)


# =============================================================================
# s.1 ratings in the payload
# =============================================================================

def test_free_agents_get_ovr_pot_and_the_grades_5b(syn):
    """5b (Nick, 11-20): a rated free agent shows OVR, POT, its change, the ring
    and the nine tiles (4a4), like a rostered player; the FPPG-percentile line is gone."""
    p, _ = syn
    fa = _row(p, FA_NAME)
    assert fa["kind"] == "fa" and fa["ovr"] == "71" and fa["pot"] == "72" and fa["ring"] is not None
    assert fa["ovr_k"] == 71 and fa["pot_k"] == 72 and len(fa["grades"]) == 9 and fa["avail"] == "90%"
    assert fa["ovr_d"]["t"] == "\u25b21" and fa["fppg"] == "31.5"
    assert "fa_pct" not in fa and "fa_note" not in p["v2"]["ratings"] and not hasattr(P, "FA_PCT_NOTE")
    for z in _rows(p):
        assert z["ovr"] != DASH and len(z["grades"]) == 9 and "fa_pct" not in z


def test_the_weekly_change_needs_a_line_at_least_7_days_back():
    lines = [{"as_of": "2026-11-12", "ovr": {"A": 82}, "pot": {"A": 86}},
             {"as_of": "2026-11-14", "ovr": {"A": 84}, "pot": {"A": 87}}]
    assert ratings.previous_from_history(lines, "2026-11-18") is None                 # 6 and 4 days back only
    assert ratings.previous_from_history(lines, "2026-11-19") is None                 # 4a4: 4a's OVR (no versions)
    assert ratings.previous_from_history(lines, "2026-11-19", key="pot") is None      # 4a4: an old POT (version 1)
    v = [dict(l, versions=dict(ratings.HISTORY_VERSIONS)) for l in lines]
    assert ratings.previous_from_history(v, "2026-11-18") is None                     # 6 and 4 days back only
    assert ratings.previous_from_history(v, "2026-11-19") == {"A": 82}                # exactly 7
    assert ratings.previous_from_history(v, "2026-11-19", key="pot") == {"A": 86}
    assert ratings.line_from_history(lines, "2026-11-22")["as_of"] == "2026-11-14"   # the latest a week back
    # no line a week back: no marker on anyone, never a zero, and no Risers section
    import hub_v2_market_fixture as MF
    import hub_v2_league_fixture as LF
    p = LF.add_league(MF.add_market(add_synth_players(_synth_payload_4b(), previous=False)))  # 4c3/4c4: Market, League
    assert all(z["ovr_d"] is None and z["pot_d"] is None for z in _rows(p))
    assert p["v2"]["players"]["risers"] is None
    h = render(p)
    assert 'data-section="risers"' not in h and "Risers this week" not in h
    assert "No weekly change yet" in visible_text(h)


def test_the_change_markers_with_a_week_old_line(syn):
    p, _ = syn
    up = [z for z in _rows(p) if (z["ovr_d"] or {}).get("dir") == "up"]
    assert up and all(z["ovr_d"]["t"].startswith("\u25b2") for z in up)
    flat = [z for z in _rows(p) if (z["ovr_d"] or {}).get("dir") == "flat"]
    assert flat and all(z["ovr_d"]["t"] == "\u2013" for z in flat)
    assert all((z["pot_d"] or {}).get("t") == "\u25b21" for z in _rows(p) if z["kind"] == "rostered")


def test_the_history_line_carries_ovr_pot_and_the_terms_and_appends(tmp_path):
    res = {"as_of": "2026-11-17", "season": "2026-27", "players": {
        "A": {"ovr": 90, "pot": 91, "components": {"level": 40.123456, "availability": 0.91234, "games_remaining": 60}},
        "B": {"ovr": None, "pot": 70, "components": {"level": 20.0, "availability": None, "games_remaining": None}}}}
    line = ratings.history_line(res)
    assert line == {"as_of": "2026-11-17", "season": "2026-27", "ovr": {"A": 90}, "pot": {"A": 91, "B": 70},
                    "terms": {"A": [40.123, 0.9123, 60]}, "versions": ratings.HISTORY_VERSIONS}
    assert ratings.read_history(tmp_path) == []                                       # not there yet
    assert ratings.append_history(tmp_path, line) is not None
    assert ratings.append_history(tmp_path, dict(line, ovr={"A": 89})) is None      # same as_of: skipped
    assert ratings.append_history(tmp_path, dict(line, as_of="2026-11-18")) is not None
    got = ratings.read_history(tmp_path)
    assert [l["as_of"] for l in got] == ["2026-11-17", "2026-11-18"]
    assert got[0]["ovr"] == {"A": 90}                                                # the first of the day stays
    (tmp_path / ratings.HISTORY_RELPATH).write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ratings.RatingsInputError, match="line 1"):
        ratings.read_history(tmp_path)


def test_the_ratings_fail_softly_and_say_so(monkeypatch):
    from modules import hub_state
    said = []

    def boom(*a, **k):
        raise ratings.RatingsInputError("a test failure")
    monkeypatch.setattr(ratings, "for_today", boom)

    class L:                       # a stand-in live log (Inputs, season)
        log = {"2026-27": [{"date": "2026-11-17"}]}
    rt = hub_state.ratings_step(ROOT, (L(), "2026-27"), {}, echo=said.append)
    assert rt["result"] is None and rt["line"] is None and "a test failure" in rt["error"]
    assert said and said[0].startswith("RATINGS FAILED")
    rt2 = hub_state.ratings_step(ROOT, None, {}, echo=lambda *a: None)
    assert rt2["result"] is None and "live log" in rt2["error"]


def test_a_ratings_error_leaves_ovr_out_with_its_reason():
    p = _synth_payload_4b()
    import test_hub_v2 as T
    orig = P.build

    def with_error(base, payload, ctx):
        ctx = dict(ctx, ratings={"result": None, "error": "RatingsInputError: boom", "previous_line": None})
        return orig(base, payload, ctx)
    P.build = with_error
    try:
        import hub_v2_market_fixture as MF
        import hub_v2_league_fixture as LF
        p = LF.add_league(MF.add_market(T.add_synth_players(p)))                 # 4c3/4c4: Market, League
    finally:
        P.build = orig
    assert all(z["ovr"] == DASH and z["pot"] == DASH and z["grades"] is None for z in _rows(p))
    assert {z["ovr_note"] for z in _rows(p) if z["kind"] == "rostered"} == {"ratings failed on this run"}
    assert p["v2"]["ratings"]["error"] == "RatingsInputError: boom"
    t = visible_text(render(p))
    assert "The ratings failed on this run" in t and "boom" in t


def test_the_nightly_writes_one_history_line_per_published_run_and_day_only(tmp_path):
    from modules import nightly
    run = nightly.Run.__new__(nightly.Run)
    run.base, run.ctx = tmp_path, {}
    line = {"as_of": "2026-11-17", "season": "2026-27", "ovr": {"A": 90}, "pot": {"A": 91}, "terms": {}}
    ok = {"result": {"as_of": "2026-11-17", "players": {"A": {}}}, "error": None, "seconds": 1.0,
          "previous_line": None, "line": line}
    rec = run._ratings_record(ok, published=False)                       # a preview build
    assert rec["history"].startswith("not written") and not (tmp_path / ratings.HISTORY_RELPATH).exists()
    rec = run._ratings_record(ok, published=True)
    assert rec["history"].startswith("appended") and len(ratings.read_history(tmp_path)) == 1
    rec = run._ratings_record(ok, published=True)                        # a later run, the same as_of
    assert rec["history"].startswith("skipped") and len(ratings.read_history(tmp_path)) == 1
    nxt = dict(ok, line=dict(line, as_of="2026-11-18"))
    run._ratings_record(nxt, published=True)
    assert len(ratings.read_history(tmp_path)) == 2
    bad = dict(ok, result=None, line=None, error="RatingsInputError: x")
    rec = run._ratings_record(bad, published=True)
    assert rec["error"] and rec["history"] == "not written: the ratings failed"
    assert run.ctx["ratings_lines"][0].startswith("RATINGS FAILED")
    assert len(ratings.read_history(tmp_path)) == 2
    src = inspect.getsource(nightly.Run.step_hub)
    assert "self._ratings_record(ratings_out, published=enc)" in src


def test_the_new_state_file_is_in_the_manifest_and_ignored():
    m = json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    assert "output/ratings_history.jsonl" in {e["path"] for e in m["files"]}
    assert "output/ratings_history.jsonl" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    from modules import state_manifest
    man = state_manifest.load(ROOT)
    assert man.contains("output/ratings_history.jsonl")


def test_a_manifest_path_that_does_not_exist_yet_is_handled(tmp_path):
    """The first cloud run creates the file: until then present() skips it, so
    hash_state, state.py pull/push and state_overlay see nothing to copy."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import state as st
    from modules import state_manifest
    man = state_manifest.load(ROOT)
    (tmp_path / "a" / "output").mkdir(parents=True)
    (tmp_path / "b" / "output").mkdir(parents=True)
    assert "output/ratings_history.jsonl" not in man.present(tmp_path / "a")
    (tmp_path / "a" / "output" / "ratings_history.jsonl").write_text('{"as_of":"x","ovr":{}}\n', encoding="utf-8")
    copied, deleted = st.copy_state(tmp_path / "a", tmp_path / "b", man)
    assert copied == ["output/ratings_history.jsonl"] and deleted == []
    assert (tmp_path / "b" / "output" / "ratings_history.jsonl").is_file()


def test_hub_state_shares_the_live_log_and_adds_no_top_level_key():
    src = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    assert "kw = kv3.keeper_watch(data, report_week, root=base, live=live)" in src
    assert "rt = ratings_step(base, live, actuals, echo=echo)" in src
    assert 'payload["v2"], payload["v2_error"] = v2data.players_soft(' in src
    assert 'payload["ratings' not in src


# =============================================================================
# s.2 the Players tab
# =============================================================================

def test_who_and_how_many(syn):
    p, _ = syn
    pl = p["v2"]["players"]
    assert len(pl["rows"]) == len(p["cards"]["players"]) == 21
    assert pl["count"] == "21 players" and "20 rostered and 1 free agents" in pl["who"]


def test_search_keys_are_folded():
    assert P.fold("Nikola Joki\u0107") == "nikola jokic"
    assert P.fold("Luka Don\u010di\u0107") == "luka doncic"
    assert P.fold("Alperen \u015eeng\u00fcn") == "alperen sengun"
    assert P.fold("Kristaps Porzi\u0146\u0123is") == "kristaps porzingis"
    assert P.fold("\u00d8 \u0141 \u00df") == "o l ss"
    # the page folds what is typed with the same map
    js = page.PAGE_JS
    m = re.search(r"var FOLD=\{(.*?)\};", js).group(1)
    pairs = dict(re.findall(r"'\\u([0-9a-f]{4})':'(\w+)'", m))
    assert {chr(int(k, 16)): v for k, v in pairs.items()} == P.FOLD
    assert "normalize('NFKD')" in js and r"[\u0300-\u036f]" in js


def test_every_row_carries_its_search_key_and_filter_values_from_the_payload(syn):
    p, _ = syn
    h = render(p)
    pl = p["v2"]["players"]
    for i, z in enumerate(pl["rows"]):
        tbl = h[h.index('id="pl-table"'):]
        tr = re.search(rf'<tr data-i="{i}" ([^>]*)>', tbl).group(1)
        a = {k: _html.unescape(v) for k, v in re.findall(r'data-(\w+)="([^"]*)"', tr)}
        assert a == {"q": z["q"], "k": z["f"]["k"], "pos": " ".join(z["f"]["pos"]), "nba": z["f"]["nba"],
                     "age": z["f"]["age"], "h": z["f"]["h"]}
    for key in ("pos", "nba", "age"):
        sel = re.search(rf'<select data-filter="{key}"[^>]*>(.*?)</select>', h, re.S).group(1)
        got = re.findall(r'<option value="([^"]*)">', sel)[1:]
        want = [x if isinstance(x, str) else x["key"] for x in pl["filters"][key]]
        assert got == want


def test_the_orders_put_missing_values_last_both_ways(monkeypatch):
    # 5b: free agents are rated; one without a rating (none here) sorts last both ways
    import test_hub_v2 as T
    real = T.synth_ratings
    monkeypatch.setattr(T, "synth_ratings", lambda r, prev: dict(real(r, prev), free_agents={}))
    p = T.synth_payload()
    assert _row(p, FA_NAME)["ovr"] == DASH and _row(p, FA_NAME)["ovr_note"] == "not rated"
    pl = p["v2"]["players"]
    rows = pl["rows"]
    fa = next(i for i, z in enumerate(rows) if z["kind"] == "fa")
    for col in ("ovr", "pot"):
        assert pl["orders"][col]["d"][-1] == fa and pl["orders"][col]["a"][-1] == fa
        ks = [rows[i][col + "_k"] for i in pl["orders"][col]["d"][:-1]]
        assert ks == sorted(ks, reverse=True)
    assert [rows[i]["name"] for i in pl["orders"]["name"]["d"]] == sorted(z["name"] for z in rows)


def test_the_table_and_the_risers(syn):
    p, _ = syn
    h = render(p)
    sec = re.search(r'data-route="players"(.*?)</section></div></section>', h, re.S).group(1)
    assert re.findall(r'data-psort="(\w+)"', sec) == ["name", "ovr", "pot", "dur", "fppg", "next"]   # 4a4: DUR
    assert 'id="pl-search"' in sec and 'data-filter="k"' in sec and 'data-filter="h"' in sec
    risers = p["v2"]["players"]["risers"]
    assert risers and [r["d"] for r in risers] == ["\u25b23", "\u25b22", "\u25b21"]     # 5b: + the free agent
    assert risers[2]["reason"].startswith("FA \u00b7 ") and pl_name(p, risers[2]) == FA_NAME
    for r in risers:
        assert r["reason"] in visible_text(sec)
    # a free agent's OVR/POT cells say the dash, and the OVR column carries the InfoTip
    assert _html.escape(infotips.tip("ovr")[1]) in sec


def test_the_risers_reason_names_the_term_that_moved_most():
    then = {"A": [40.0, 0.80, 60], "B": [41.0, 0.90, 60], "C": [42.0, 0.85, 60]}
    now = {"A": [43.0, 0.80, 57], "B": [41.0, 0.90, 57], "C": [42.0, 0.85, 57]}
    assert P.riser_reason("A", now, then) == "scoring level 40.0 \u2192 43.0"
    now2 = {"A": [40.0, 0.95, 57], "B": [41.0, 0.90, 57], "C": [42.0, 0.85, 57]}
    assert P.riser_reason("A", now2, then) == "playing more: 80% \u2192 95% of games"
    now3 = {"A": [40.0, 0.80, 59], "B": [41.0, 0.90, 56], "C": [42.0, 0.85, 56]}
    assert P.riser_reason("A", now3, then) == "more games left than most: 59"
    assert P.riser_reason("A", {k: list(v) for k, v in then.items()}, then).startswith("held steady")
    with pytest.raises(P.PlayersError):
        P.riser_reason("Z", now, then)


def test_the_header_has_a_search_button_that_opens_players(syn):
    h = render(syn[0])
    hdr = re.search(r'<header class="lh-header.*?</header>', h, re.S).group(0)
    assert 'data-go="search"' in hdr and 'aria-label="Search players"' in hdr
    assert "focusSearch=true" in page.PAGE_JS and "location.hash='#/players'" in page.PAGE_JS


def test_routes_players_a_card_and_compare_deep_link(syn):
    h = render(syn[0])
    routes = set(re.findall(r'data-route="([^"]+)"', h))
    assert {"players", "player", "compare-pick", "compare"} <= routes
    for href in ("players", "players/marcus-guard", "players/compare/marcus-guard",
                 "players/compare/marcus-guard/free-guy"):
        assert dyn_route(href) in routes
    assert 'href="#/players/marcus-guard"' in h
    js = page.PAGE_JS
    for frag in ("if(dyn==='player'){showCard(parts[1]);}", "showPick(parts[2])", "showCompare(parts[2],parts[3])",
                 "window.addEventListener('hashchange',function(){depth++;route();});",
                 "if(depth>0){history.back();}else{location.hash=t.getAttribute('data-back');}"):
        assert frag in js


# =============================================================================
# s.3 the new player card
# =============================================================================

def test_the_card_is_the_one_builders_data_plus_the_ratings(syn):
    p, cards = syn
    views = C.views(p, cards)
    assert set(views) == set(cards["cards"])
    for k, v in views.items():
        c = cards["cards"][k]
        z = next(r for r in _rows(p) if r["key"] == k)
        assert v["season"]["kpis"][0]["value"] == f"{c['current_season']['fppg']:.1f}" == z["fppg"]
        assert v["season"]["kpis"][1]["value"] == str(c["current_season"]["gp"])
        assert v["hero"]["ovr"] == z["ovr"] and v["hero"]["pot"] == z["pot"]
        assert v["season"]["grades"] == P.tiles(z["grades"])
        if z["kind"] == "rostered":
            assert [t["name"] for t in v["season"]["grades"]] == p["v2"]["players"]["grade_labels"]
        assert v["career"]["rows"][0]["fppg"] == "28.3"
    # a card that disagrees with the Players row raises (one FPPG everywhere)
    bad = json.loads(json.dumps(cards))
    k = sorted(bad["cards"])[0]
    bad["cards"][k]["current_season"]["fppg"] += 1.0
    with pytest.raises(C.CardError, match="one FPPG everywhere"):
        C.views(p, bad)


def test_the_old_archetype_never_appears(syn):
    p, cards = syn
    for k, h in v2pub.card_html_all(p, cards).items():
        assert "Generational Big" not in h          # 4a4: the old 4a2 label is gone (the new one may show)
    assert "Generational Big" not in render(p)


def test_a_missing_headshot_renders_initials(syn):
    p, cards = syn
    pc = v2pub.preview_cards(ROOT, p, cards)
    assert all(c["photo"] is None for c in pc["cards"].values())
    h = pc["cards"]["marcus-guard"]["html"]
    assert '<span class="v2-ini" aria-hidden="true">MG</span>' in h and "<img" not in h
    assert "img.addEventListener('error',function(){img.remove();})" in page.PAGE_JS
    assert P.initials("Jaren Jackson Jr.") == "JJ" and P.initials("Nene") == "N"


def test_every_number_on_a_card_is_a_card_or_payload_string(syn):
    p, cards = syn
    views = C.views(p, cards)
    known = " ".join(strings(p)) + " " + " ".join(" ".join(v) for v in infotips.TIPS.values())
    for k, h in v2pub.card_html_all(p, cards).items():
        kk = known + " " + " ".join(strings(views[k]))
        for n in re.findall(r"\d+(?:[.,]\d+)*", visible_text(h)):
            assert n in kk, f"{n!r} on {k}'s card is in no engine string"


def test_the_card_obeys_the_page_rules(syn):
    p, cards = syn
    for k, h in v2pub.card_html_all(p, cards).items():
        doc = f"<body>{h}</body>"
        assert not tap_violations(doc), (k, tap_violations(doc)[:3])
        assert "http://" not in h and "https://" not in h and not re.search(r'\bsrc="(?!data:)', h)
        for a in re.findall(r'<svg class="lh-chart[^>]*>', h):
            assert re.search(r'aria-label="[^"]{10,}"', a), a
        assert re.search(r'class="lh-bars v2-bars[^"]*" role="group" aria-label="[^"]{10,}"', h)
        assert not re.search(r"#[0-9A-Fa-f]{6}\b", h)
        for tab in ("season", "career", "keeper", "history"):
            assert f'data-pane-of="{tab}"' in h


def test_the_free_agent_card_shows_his_ovr_ring_and_grades_5b(syn):
    p, cards = syn
    h = v2pub.card_html_all(p, cards)[FA_KEY]
    t = visible_text(h)
    assert "No OVR or POT for free agents." not in t and "percentile of rostered players" not in t
    assert "lh-ring" in h and 'aria-label="Overall rating 71 of 99"' in h and "lh-grades" in h
    assert "Free agents have no keep chance." in t
    assert "On a league roster: 27.5 FPPG in 8 games" in t                     # the secondary line


def test_lore_never_reaches_the_players_tab_or_a_card(syn):
    p, cards = syn
    p = json.loads(json.dumps(p))
    cards = json.loads(json.dumps(cards))
    z = _rows(p)[0]
    z["meta"] = "PG <!-- lore:phase-x --> AAA"
    cards["cards"][z["key"]]["keep_text"] = "kept <!-- lore:phase-y -->"
    cards["cards"][z["key"]]["record_book"][0]["detail"] = "x <!-- lore:phase-z -->"
    h = render(p) + "".join(v2pub.card_html_all(p, cards).values())
    assert "lore:" not in h and "phase-x" not in h and "phase-y" not in h and "phase-z" not in h


def test_the_renderer_does_no_arithmetic_on_the_new_screens():
    src = "".join(inspect.getsource(f) for f in (PP.players_screen, PP.card_screen, PP.compare_screens,
                                                 PP.card_html, PP._kpi, PP._grade, PP._line, PP._rows, PP._chip,
                                                 PP._delta, PP._name, PP._status, PP._info))
    for banned in ("round", "float", "sum", "sorted", "max", "min", "int"):
        assert not re.search(rf"\b{banned}\(", src), f"the renderer calls {banned}("
    js = page.PAGE_JS
    block = js[js.index("// player cards (4c1)"):js.index("function alertBox(")]
    for banned in (".sort(", "Math.", "parseFloat", "parseInt", "Number(", "toFixed"):
        assert banned not in block, banned


def test_the_infotips_are_written_once_and_the_ovr_and_efficiency_words_are_the_decisions():
    assert infotips.tip("ovr")[1] == ("How good he is per game when he plays: his fantasy production judged on his "
                                      "whole NBA record (rostered or not), this season, and his age, on a fixed 40-99 "
                                      "scale that means the same every year. It isn't about games left or how often "
                                      "he plays: that's DUR.")   # 4a4 s.2: the skill OVR
    assert infotips.tip("prov")[1] == "Small sample: this rating will settle as he plays more."   # Nick, 11-20
    assert "fa_pct" not in infotips.TIPS                                       # 5b: the free agents' tile is gone
    assert infotips.tip("grade_efficiency")[0] == "Efficiency"                  # 4a4 s.4
    for k in ("pot", "fppg", "grades", "age_curve", "archetype", "grade_scoring", "grade_shooting",
              "grade_playmaking", "grade_rebounding", "grade_steals", "grade_blocks", "grade_efficiency",
              "grade_consistency", "grade_schedule"):
        assert infotips.tip(k)[1]


# =============================================================================
# s.4 Compare
# =============================================================================

def test_compare_keys_are_integers_age_has_none_and_a_free_agent_has_no_keep(syn):
    p, _ = syn
    pl = p["v2"]["players"]
    labels = [r["label"] for r in pl["cmp_rows"]]
    assert labels == ["POT", "DUR", "FPPG", "L14", "MIN", "Avail %", "Games, next 3 wks", "Keep %", "Age", "Scoring",
                      "Shooting", "Playmaking", "Rebounding", "Steals", "Blocks", "Efficiency", "Consistency",
                      "Schedule"]                                             # 4a4 s.4: the tiles
    age = labels.index("Age")
    for z in pl["rows"]:
        assert len(z["cmp"]) == len(labels)
        assert z["cmp"][age]["k"] is None
        for c in z["cmp"]:
            assert c["k"] is None or type(c["k"]) is int
            if c["k"] is None:
                continue
    fa = _row(p, FA_NAME)                    # 5b: rated, so he competes on POT, Avail % and the grades
    assert fa["cmp"][labels.index("Keep %")] == {"t": DASH, "k": None}
    assert fa["cmp"][labels.index("POT")] == {"t": "72", "k": 72}
    assert fa["cmp"][labels.index("Avail %")] == {"t": "90%", "k": 90}
    assert fa["cmp"][labels.index("Scoring")]["t"] == "B" and fa["cmp"][labels.index("Shooting")]["k"] is None


def test_compare_keys_follow_what_is_printed(syn):
    p, _ = syn
    rows = _rows(p)
    i = [r["label"] for r in p["v2"]["players"]["cmp_rows"]].index("FPPG")
    pairs = [(float(z["cmp"][i]["t"]), z["cmp"][i]["k"]) for z in rows if z["cmp"][i]["k"] is not None]
    for (a, ka) in pairs:
        for (b, kb) in pairs:
            assert (a > b) == (ka > kb) and (a == b) == (ka == kb)
    g = [r["label"] for r in p["v2"]["players"]["cmp_rows"]].index("Scoring")
    bands = [b[1] for b in ratings.config()["grade_bands"]]
    order = {lab: k for k, lab in enumerate(reversed(bands))}
    for z in rows:
        c = z["cmp"][g]
        if c["k"] is not None:
            assert c["k"] == order[c["t"]]


def test_compare_bolds_only_by_the_order_keys():
    js = page.PAGE_JS
    blk = js[js.index("function showCompare("):js.index("function showPick(")]
    assert "var xw=(x.k!==null&&y.k!==null&&x.k>y.k),yw=(x.k!==null&&y.k!==null&&y.k>x.k);" in blk
    # nothing else decides: no text is compared or parsed
    assert ".t>" not in blk and ".t<" not in blk and "parse" not in blk
    assert "v2-cmp-v'+(xw?' v2-win':'')" in blk
    css = tokens.css(ALL_CSS)
    assert ".v2-cmp-v.v2-win{font-weight:800;color:var(--ink-strong)}" in css


def test_compare_data_is_the_payloads(syn):
    p, _ = syn
    h = render(p)
    d = json.loads(re.search(r'<script type="application/json" id="v2-cmp">(.*?)</script>', h, re.S).group(1))
    assert d["labels"] == [r["label"] for r in p["v2"]["players"]["cmp_rows"]]
    for z in _rows(p):
        assert d["rows"][z["key"]]["cmp"] == z["cmp"] and d["rows"][z["key"]]["ovr"] == z["ovr"]


# =============================================================================
# s.5 the archetype
# =============================================================================

def test_the_archetype_shows_now_it_is_enabled(syn):
    p, cards = syn
    assert ratings.config()["archetype"]["enabled"] is True          # Nick, 11-20: turn them on
    assert any(z.get("arch") for z in _rows(p)) and not any(z.get("arch_off") for z in _rows(p))
    assert any("lh-hero__arch" in h for h in v2pub.card_html_all(p, cards).values())


def test_the_archetype_is_absent_when_switched_off(monkeypatch):
    real = ratings.config

    def off(*a, **k):
        c = copy.deepcopy(real(*a, **k))
        c["archetype"]["enabled"] = False
        return c
    monkeypatch.setattr(ratings, "config", off)
    p = synth_payload()
    cards = synth_cards(p)
    assert not any(z.get("arch") for z in _rows(p))
    assert any(z.get("arch_off") for z in _rows(p))                           # computed, never printed
    assert not any("lh-hero__arch" in h or "v2-arch" in h for h in v2pub.card_html_all(p, cards).values())
    assert 'class="v2-arch-k"' not in render(p)


def test_the_archetype_preview_is_marked_and_refused_in_publish_mode(tmp_path, syn):
    p, cards = syn
    p = json.loads(json.dumps(p))
    n = P.archetype_preview(p)
    labelled = [z for z in _rows(p) if z.get("arch")]
    assert n == sum(1 for z in labelled if z["kind"] == "rostered") > 0
    assert all(z["arch"]["preview"] for z in labelled)
    table = P.archetype_table(p)
    assert sum(len(w) for lab, w in table if lab != "(no label)") == n
    assert sum(len(w) for _lab, w in table) == sum(1 for z in _rows(p) if z["kind"] == "rostered")
    assert all(len(row) == 4 for _lab, w in table for row in w)              # name, manager, standouts, tags
    assert not any(z.get("arch_off") for z in _rows(p))                       # moved to "arch", marked
    h = v2pub.card_html_all(p, cards)[labelled[0]["key"]]
    assert '<span class="v2-preview">Preview</span>' in h and labelled[0]["arch"]["label"] in h
    assert "Archetype preview" in visible_text(render(p))
    e = _archive(tmp_path)
    p["v2"]["issue"]["file"] = e["enc"]
    with pytest.raises(v2pub.V2PublishError, match="archetype preview"):
        v2pub.build(tmp_path, p, PASS, salt=b"\x01" * 16, out_dir=tmp_path / "pub", iterations=1000, terms=TERMS,
                    now=GEN)
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_hub
    assert build_hub.main(["--archetype-preview"]) == 1                  # only with --v2


# =============================================================================
# publish mode: the new card's files, the budget, the scan
# =============================================================================

def test_publish_mode_builds_the_new_card_files_encrypted_and_within_budget(tmp_path, syn):
    p, cards = syn
    e = _archive(tmp_path)
    p = json.loads(json.dumps(p))
    p["v2"]["issue"]["file"] = e["enc"]
    out = tmp_path / "_to_delete" / "4c1" / "publish"
    rep = v2pub.build(tmp_path, p, PASS, salt=b"\x01" * 16, out_dir=out, iterations=1000, terms=TERMS, now=GEN,
                      cards=cards)
    assert rep["served_bytes"] <= budget_bytes()
    c = rep["card_files"]
    assert c["cards"] == len(cards["cards"]) and c["photos"] == 0
    from modules import hub_publish, hub_crypto, hub_cards
    assert hub_publish.scan_dir(out, TERMS)["hits"] == {}
    sh = (out / "index.html").read_text(encoding="utf-8")
    inner = v2pub.open_inner(PASS, json.loads(re.search(r'id="hub-bundle">(.*?)</script>', sh, re.S).group(1)))
    # the index, then one card: what a tap fetches, opened as the shell would
    import gzip
    root = hub_crypto.derive_key(PASS, b"\x01" * 16, 1000)

    def part(ref):
        blob = (out / ref["file"]).read_bytes()
        return json.loads(gzip.decompress(hub_crypto.open_sealed(hub_crypto.unb64(ref["key"]), blob)))
    idx = part(inner["cards"])
    assert idx["v"] == 2 and set(idx["cards"]) == set(cards["cards"])
    one = part(idx["cards"]["marcus-guard"]["card"])
    assert "Marcus Guard" in one["html"] and "lh-hero" in one["html"]
    assert (out / idx["cards"]["marcus-guard"]["card"]["file"]).stat().st_size <= 60_000      # a lazy file's cap


# =============================================================================
# the one real, unstubbed test: today's state, end to end
# =============================================================================

@pytest.fixture(scope="module")
def real():
    from modules import hub_state as hs, player_actuals, hub_cards
    from modules.league_clock import league_now
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_history.jsonl",
              ROOT / "output" / "tag_records.jsonl", ROOT / "config" / "ROSTERS.json", ROOT / "data" / "LINEUPS.xlsx"]
    if not all(x.exists() for x in needed):
        pytest.skip("no league state on this machine")
    league_state.skip_if_actuals_behind()
    rt, po = {}, {}
    try:
        p = hs.build(ROOT, now=league_now(), allow_engine_mismatch=True, echo=lambda *a, **k: None, ratings_out=rt,
                     players_out=po)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        pytest.skip(f"the hub's real inputs are not current today ({e})")
    v2data.attach_players(p, po)            # 4c2: the Players rows live in their own file
    cards = hub_cards.build(ROOT, p, echo=lambda *a, **k: None)
    return p, rt, cards


@pytest.mark.slow
def test_real_ratings_players_cards_compare_and_publish(real, tmp_path):
    from modules import hub_publish
    p, rt, cards = real
    assert p.get("v2_error") is None, p.get("v2_error")
    assert rt["error"] is None, rt["error"]
    # the payload's OVR/POT equal ratings.for_today on the same inputs (unshared: built from scratch)
    prev = rt["previous_line"]
    fresh = ratings.for_today(ROOT, previous=None if prev is None else dict(prev["ovr"]))
    pl = p["v2"]["players"]
    for z in pl["rows"]:
        if z["kind"] == "rostered":
            r = fresh["players"][z["name"]]
            assert z["ovr"] == (DASH if r["ovr"] is None else str(r["ovr"])), z["name"]
            assert z["pot"] == (DASH if r["pot"] is None else str(r["pot"])), z["name"]
        else:                                # 5b: the free agents are rated (hub_state.ratings_fa_step)
            r = rt["result"]["free_agents"][z["name"]]
            assert z["ovr"] == (DASH if r["ovr"] is None else str(r["ovr"])), z["name"]
            assert z["pot"] == (DASH if r["pot"] is None else str(r["pot"])), z["name"]
    assert len(pl["rows"]) == len(p["cards"]["players"])
    # the preview: Players, three cards (a star, a rookie, a free agent) and a Compare
    now = datetime.fromisoformat(p["generated_at"]) + timedelta(minutes=5)
    h = page.render(view.build(p, mode="preview", now=now), cards=v2pub.preview_cards(ROOT, p, cards))
    assert not tap_violations(h) and "http://" not in h and "lore:" not in h
    known = " ".join(strings(p)) + " " + " ".join(" ".join(v) for v in infotips.TIPS.values())
    text = visible_text(h.split('<script type="application/json" id="v2-cards">')[0])
    from modules.hub_page import age_words, STALE_HOURS
    static = {str(STALE_HOURS), "10", "130"} | set(re.findall(r"\d+", age_words(datetime.fromisoformat(
        p["generated_at"]), now)[0]))
    for n in re.findall(r"\d+(?:[.,]\d+)*", text):
        assert n in known or n in static, f"{n!r} on the page is in no payload string"
    rows = pl["rows"]
    star = rows[pl["orders"]["ovr"]["d"][0]]
    rookies = [z for z in rows if z["kind"] == "rostered" and len(cards["cards"][z["key"]]["career"].get(
        "season_breakdown") or []) <= 1]
    fa = next(z for z in rows if z["kind"] == "fa" and z["ovr"] != DASH)
    views = C.views(p, cards)
    for z in [star, fa] + rookies[:1]:
        v = views[z["key"]]
        ch = PP.card_html(v)
        assert not tap_violations(f"<body>{ch}</body>") and "http" not in ch
        kk = known + " " + " ".join(strings(v))
        for n in re.findall(r"\d+(?:[.,]\d+)*", visible_text(ch)):
            assert n in kk, (z["name"], n)
    assert views[fa["key"]]["hero"]["ring"] is not None                 # 5b: rated, so his ring shows
    d = json.loads(re.search(r'<script type="application/json" id="v2-cmp">(.*?)</script>', h, re.S).group(1))
    assert star["key"] in d["rows"] and fa["key"] in d["rows"]
    # publish mode to a temp folder: the budget and the plaintext scan (a throwaway key)
    rep = v2pub.build(ROOT, p, PASS, salt=b"\x02" * 16, out_dir=tmp_path / "pub", iterations=1000, now=now,
                      cards=cards)
    assert rep["served_bytes"] <= budget_bytes(), rep
    assert rep["card_files"]["card_bytes_max"] <= 60_000
    assert hub_publish.scan_dir(tmp_path / "pub", hub_publish.scan_terms(ROOT))["hits"] == {}


@pytest.mark.slow
def test_real_shared_live_log_changes_no_keep_chance():
    from modules import keepability_v3 as kv3, keeper_history as kh
    from modules.data_loader import load_all_data
    if not (ROOT / "data" / "LINEUPS.xlsx").exists():
        pytest.skip("no league state on this machine")
    data = load_all_data(ROOT, current_week=None)
    from modules import week_state as ws
    from modules.league_clock import league_now
    wk = ws.week_for_date(data, league_now().date()) - 1
    a = kv3.keeper_watch(data, wk, root=ROOT)
    live = kh.live_inputs(ROOT, kh.Inputs.load(ROOT))
    b = kv3.keeper_watch(data, wk, root=ROOT, live=live)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    with pytest.raises(kv3.KeepabilityInputError):
        kv3.keeper_watch(data, wk, root=ROOT, live=live, logs_before=date(2026, 11, 1))
