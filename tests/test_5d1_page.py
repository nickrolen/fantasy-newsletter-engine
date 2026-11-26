"""5d1, the page (claude/HANDOFF_5D1_PHONE_FIXES_2026-11-21.md):

  s.4  title odds open League > Standings' title-odds chart with that team's
       line highlighted (the route carries ?hl=); the team name still opens
       the team page;
  s.5  every table header opens its column's definition (infotips.COLUMNS),
       with Sort inside where the table sorts; a header with no entry FAILS;
  s.6  Home's issue bar links to League > Archive ("All issues");
  s.7  charts: every labelled series is drawn and every drawn series is
       labelled; a one-point series is a dot; two players of one fantasy team
       are told apart; the race charts' axis is named;
  s.8  the season picker on the lists that grow each season, past seasons
       as their own parts, the season in the route;
  s.9  the wording guard: a planted "Champion: <the bracket's winner>" makes
       the publish check refuse.
jsdom runs where node and jsdom are installed (slow).
"""
import copy
import json
import re

import pytest

import league_state                                    # noqa: F401
import test_hub_v2 as T2
from test_hub_switch import _shell, _v2_world, PASS, SALT, GEN
from modules.hub_v2 import infotips, page, page_league as PL, publish as v2pub, publish_check as pc, view

ROOT = T2.ROOT


@pytest.fixture(scope="module")
def html():
    return T2.render()


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    base = tmp_path_factory.mktemp("v2pub5d1")
    p = _v2_world(base, keep_cards=True)
    out = base / "_to_delete" / "j" / "publish"
    rep = v2pub.build(base, p, PASS, salt=SALT, out_dir=out, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    return out, p, rep


def _shown(out):
    """{where: html} of every published piece the check opens (the page, screens, parts)."""
    pg = pc.open_page((out / "index.html").read_text(encoding="utf-8"), PASS)["page"]
    shown = {"page": pg}
    todo = re.findall(r"data-(?:screen-)?part='([^']*)'", pg)
    seen = set()
    import html as _h
    while todo:
        ref = json.loads(_h.unescape(todo.pop()))
        if ref["file"] in seen:
            continue
        seen.add(ref["file"])
        h = str(pc.open_part(out, ref).get("html") or "")
        shown[ref["file"]] = h
        todo += re.findall(r"data-(?:screen-)?part='([^']*)'", h)
    return shown


# =============================================================================
# s.4 title odds -> the chart, highlighted
# =============================================================================

def test_every_title_odds_place_links_to_the_chart_with_the_team_highlighted(html):
    for m in T2.MGRS:
        href = f'href="#/league/standings?hl={m}"'
        # Home's power rankings, the Teams grid's tile, the team page's KPI, Standings and its weekly rows
        assert html.count(href) >= 5, (m, html.count(href))
        assert f'class="v2-rank-team" href="#/teams/{m}"' in html                  # the team still opens his page
        assert f'class="v2-tc-link" href="#/teams/{m}"' in html
    assert view.odds_href("Dana") == "#/league/standings?hl=Dana"
    # the chart's series and end labels carry their manager, for the highlight
    # (MC2: each manager card draws the four lines too, so every chart carries each manager once)
    series = re.findall(r'<g class="lh-t-[a-z]+" data-m="([^"]+)"><polyline', html)
    assert series and len(series) % len(T2.MGRS) == 0 and sorted(set(series)) == sorted(T2.MGRS)
    js = page.script()
    assert "window.routeQ=q" in js and "window.lgHl(" in js and "history.replaceState(null,'','#/league/standings')" in js


def test_the_odds_links_are_tap_targets_and_never_nested_in_another_link(html):
    assert {"v2-oddslink", "v2-rank-team", "v2-tc-link"} <= set(page.TAP_CLASSES)
    for a in re.finditer(r"<a\b[^>]*>(.*?)</a>", html, re.S):
        assert "<a " not in a.group(1), a.group(0)[:200]


# =============================================================================
# s.5 column definitions
# =============================================================================

def _ths(h):
    return [m.group(0) for m in re.finditer(r"<th\b[^>]*>.*?</th>", h, re.S)]


def test_every_table_header_has_a_definition(published):
    out, _p, _rep = published
    shown = _shown(out)
    shown["preview"] = T2.render()
    n = 0
    for where, h in shown.items():
        for th in _ths(h):
            if 'scope="colgroup"' in th:                 # the draft's team rows, not a column
                continue
            m = re.search(r'data-colh="([a-z0-9_]+)\|([a-z0-9_]+)"', th)
            assert m, (where, th[:160])
            assert infotips.column(m.group(1), m.group(2))
            n += 1
    assert n > 40
    # the games grid's headers and Compare's rows too (Compare is drawn by the script)
    assert 'data-colh="grid|week"' in shown["preview"]
    assert "lb.setAttribute('data-colh','compare|'+D.keys[i])" in page.script()


def test_a_header_with_no_definition_fails_and_the_words_live_in_one_place():
    from modules.hub_v2.text import colh, colh_btn
    with pytest.raises(KeyError, match="infotips.COLUMNS"):
        colh("roster", "no_such_column")
    with pytest.raises(KeyError):
        colh_btn("nope", "x", "X")
    from modules.hub_v2 import roster
    for k, (_lab, _num, tip) in roster.COLS.items():
        assert tip == infotips.column("roster", k)[1]              # the roster's notes read the same words
    flat = infotips.columns_flat()
    assert all(len(v) == 2 and v[0] and v[1].endswith((".", ")")) for v in flat.values())
    assert len(flat) == sum(len(c) for c in infotips.COLUMNS.values())


def test_the_definitions_ride_once_in_the_page_and_sort_moves_into_the_popover(html):
    blob = re.search(r'<script type="application/json" id="v2-coldefs">(.*?)</script>', html, re.S)
    assert blob and json.loads(blob.group(1)) == infotips.columns_flat()
    assert html.count('id="v2-coldefs"') == 1
    js = page.script()
    assert "e.stopImmediatePropagation();var same=(colFor===b)" in js            # a header tap opens, never sorts
    assert "colPass=true;try{btn.click();}" in js                               # Sort is inside the popover
    assert "placePop(btn,box)" in js                                            # 5c's placement rule


# =============================================================================
# s.6 All issues
# =============================================================================

def test_the_issue_bar_links_to_the_archive(html):
    assert '<a class="lh-link v2-allissues" href="#/league/archive">All issues &rsaquo;</a>' in html


# =============================================================================
# s.7 charts
# =============================================================================

TEAMS = {m: {"slot": s, "mono": m[:2].upper(), "team": f"{m}'s"} for m, s in
         (("Nick", "blue"), ("Garrett", "orange"), ("Benton", "purple"), ("Hayden", "green"))}


def _race(series):
    weeks = [1, 2, 3, 4]
    return {"weeks": weeks, "ticks": [{"x": i / 3, "t": f"W{w}"} for i, w in enumerate(weeks)],
            "yticks": [{"v": 0, "t": "0"}, {"v": 400, "t": "400"}], "ymin": 0, "ymax": 400,
            "series": series, "aria": "race",
            "points": [{"head": f"Week {w}", "body": "x"} for w in weeks]}


def _marks(geom):
    """{(cls, style): drawn?} and {(cls, style): labelled?} from a chart's geometry."""
    drawn = {}
    for ln in geom["lines"]:
        pts = ln["points"].split()
        drawn[(ln["cls"], ln.get("style", ""))] = drawn.get((ln["cls"], ln.get("style", "")), False) or \
            len(pts) > 1 or bool(ln.get("dot"))
    labelled = {(e["cls"], e.get("style", "")) for e in geom["ends"]}
    return drawn, labelled


def test_every_labelled_series_is_drawn_and_every_drawn_series_labelled():
    # Nick's two screenshots: MVP (Towns one week; Doncic and Towns both Nick's) and Best pickup
    # (Wagner and Coward picked up W4: one point each, both Nick's)
    c = _race([{"m": "Garrett", "end": "Wemby 467", "vals": [100, 200, 300, 467]},
               {"m": "Nick", "end": "Doncic 448", "vals": [120, 220, 330, 448]},
               {"m": "Nick", "end": "Towns 256", "vals": [None, None, None, 256]},
               {"m": "Nick", "end": "Wagner 93", "vals": [None, None, None, 93]},
               {"m": "Garrett", "end": "Sengun 265", "vals": [None, None, 200, 265]}])
    g = view.race_chart(c, TEAMS, "PAR so far")
    drawn, labelled = _marks(g)
    assert labelled == set(drawn) and all(drawn.values())
    assert not any(len(ln["points"].split()) == 1 and not ln.get("dot") for ln in g["lines"])   # never an empty polyline
    styles = [e["style"] for e in g["ends"]]
    assert styles == ["", "", "dash", "dot", "dash"]              # Nick's 2nd dashed, 3rd dotted; Garrett's 2nd dashed
    assert g["ytitle"] == "PAR so far" and "PAR so far" in g["readout0"]["head"]
    h = page._chart(g, "t")
    assert h.count('class="v2-c-pt') == 2 and "v2-c-dash" in h and "v2-c-lab-dash" in h and "PAR so far" in h
    # a label the spacing moved has a leader line back to its line's end
    assert all(("lead" in e) == (abs(float(e["y"]) - 4 - _end_y(g, e)) > view.LEAD_MIN) for e in g["ends"])


def _end_y(g, e):
    for ln in g["lines"]:
        if ln["cls"] == e["cls"] and ln.get("style", "") == e.get("style", ""):
            last = ln["points"].split()[-1]
    return float(last.split(",")[1])


def test_the_win_chart_draws_the_line_its_second_label_names():
    pts = [{"x": i / 4, "a": 40.0 + i, "b": 60.0 - i, "ta": f"{40 + i}%", "tb": f"{60 - i}%", "event": "", "when": "x",
            "cause": ""}
           for i in range(5)]
    win = {"points": pts, "yticks": [{"v": 0, "t": "0%"}], "ticks": [], "aria": "w", "empty": ""}
    g = view.win_chart(win, "Nick", "Garrett", TEAMS)
    drawn, labelled = _marks(g)
    assert {c for c, _s in drawn} == {c for c, _s in labelled} == {"lh-t-blue", "lh-t-orange"}


def test_the_real_awards_charts_label_only_what_they_draw():
    from modules import hub_state
    p = hub_state.players_path_for(ROOT / hub_state.PAYLOAD_RELPATH)
    if not p.exists():
        pytest.skip(f"no {p.name}")
    aw = (json.loads(p.read_text(encoding="utf-8")).get("moved") or {}).get("league.awards")
    if not aw:
        pytest.skip("the Players file has no awards")
    teams = {m: {"slot": s, "mono": m[:2], "team": m} for m, s in
             zip(sorted({sr["m"] for r in aw["races"] for sr in (r.get("chart") or {}).get("series") or []}),
                 ("blue", "orange", "purple", "green", "red", "teal"))}
    for r in aw["races"]:
        if r.get("chart"):
            g = view.race_chart(r["chart"], teams, f"{r['unit']} so far")
            drawn, labelled = _marks(g)
            assert labelled == set(drawn) and all(drawn.values()), r["key"]


# =============================================================================
# s.8 the season picker
# =============================================================================

def test_the_season_picker_defaults_to_the_current_season_or_says_why_not():
    assert PL.spick_default(["2026-27", "2025-26"], "2026-27", "trade") == ("2026-27", "")
    d, note = PL.spick_default(["2025-26", "2024-25"], "2026-27", "trade")
    assert d == "2025-26" and note == "No trade in 2026-27 yet: showing 2025-26."
    assert PL.spick_default([], "2026-27", "trade") == ("", "")


def test_past_seasons_are_their_own_parts_opened_from_inside_the_list(published):
    out, p, rep = published
    seasons = [k for k in rep["league_parts"]["bytes"] if ":" in k]
    assert {k.split(":")[0] for k in seasons} <= {"draft", "trades", "potw"} and seasons
    shown = _shown(out)
    pg = shown["page"]
    assert "<select data-spick=" not in pg and "<div data-spick-of=" not in pg   # in their parts, not the first load
    for which in ("draft", "trades"):
        part = [h for h in shown.values() if f'data-spick="{which}"' in h]
        assert len(part) == 1, which
        panes = re.findall(rf'data-spick-of="{which}\|([0-9-]+)"( data-part=)?', part[0])
        assert sum(1 for _s, ref in panes if not ref) == 1           # the default season inline, the rest parts
        assert len(panes) == 1 + sum(1 for k in seasons if k.startswith(which + ":"))


def test_the_season_is_in_the_route():
    js = page.script()
    assert "location.hash=to+encodeURIComponent(t.value)" in js
    assert "if(c==='trades'){spick('trades',q.s||'');}" in js and "spick('potw'" in js


# =============================================================================
# s.9 the wording guard
# =============================================================================

def test_a_planted_champion_who_is_the_brackets_winner_refuses_the_publish(tmp_path):
    hits = pc.champion_audit({"x": "<p>Champion: Garrett (Saboner)</p>"})
    assert len(hits) == 1 and "Champion: Garrett" in hits[0][1]
    ok = ("<p>League Champion: Nick. Playoff champion: Garrett, over Hayden. The Cup champion. Title odds 31%. "
          "Title \u0394 +2. the playoff title. the regular-season title. Titles = League Championships</p>")
    assert pc.champion_audit({"x": ok}) == []
    for bad in ("the title went to Garrett", "Garrett won the championship", "two titles", "Champions: Garrett"):
        assert pc.champion_audit({"x": f"<p>{bad}</p>"}), bad
    # the whole check on the synthetic league refuses a planted line
    p = _v2_world(tmp_path)
    p2 = json.loads(json.dumps(p).replace('"Through week', '"Champion: Garrett. Through week', 1))
    assert p2 != p
    rep = pc.check(tmp_path, p2, None, tmp_path / "_to_delete" / "g" / "publish", now=GEN, pictures=[],
                   terms=T2.TERMS)
    assert not rep["ok"] and any("a champion or title the rules don't name" in x for x in rep["problems"])
    clean_rep = pc.check(tmp_path, p, None, tmp_path / "_to_delete" / "h" / "publish", now=GEN, pictures=[],
                         terms=T2.TERMS)
    assert clean_rep["ok"], clean_rep["problems"]


def test_the_column_definitions_pass_the_guard():
    blob = json.dumps(infotips.columns_flat())
    assert pc.champion_audit({"x": f'<script type="application/json" id="d">{blob}</script>'}) == []


# =============================================================================
# jsdom (slow)
# =============================================================================

@pytest.mark.slow
def test_in_jsdom_the_highlight_the_popover_and_the_season_picker_work(published):
    out, p, _rep = published
    r = _shell(out, {"d5": "Dana"})
    assert r["mounted"] and r["errors"] == [], r
    d = r["d5"]
    assert d["hl_on"] and set(d["hl_lines"]) == {"Dana"} and len(d["hl_lines"]) >= 2   # his line, its label, his markers
    assert not d["hl_after_tap"] and d["hash_after_tap"] == "#/league/standings"
    assert d["pop_wl"].startswith("W-L") and d["pop_wl_sort"] == 0 and d["pop_closed"]
    assert not d["players_sorted_by_tap"] and d["pop_fp_sort"] and d["players_sorted_from_pop"]
    assert d["pop_fp_state"].startswith("Sorted") and d["pop_escape_closed"]
    assert d["default_season"] == d["seasons"][0]
    if len(d["seasons"]) > 1:
        assert d["hash_after_pick"].startswith("#/league/history/trades?s=") and d["past_loaded"]
        assert d["other_panes_hidden"] and "Loading" not in d["past_text"]
    assert d["all_issues"] == "#/league/archive"
