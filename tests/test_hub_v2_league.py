"""
tests/test_hub_v2_league.py -- 4c4: the new hub's League tab: Standings,
History, Awards, Archive (claude/HANDOFF_4C4_LEAGUE_2026-11-19.md s.3).

On the synthetic league (tests/test_hub_v2.py, its League by the real
league.build from tests/hub_v2_league_fixture.py): made-up names and numbers,
made-up images generated here in memory.

A. The 4b/4c rules on every new piece: display-only, lore, tokens only, taps,
   aria, nothing hover-only, offline, the script inside the page's closure.
B. Standings: standings_order (a T counts half; head-to-head, then points),
   the tie said; streaks (every week; a T ends one).
C. The title-odds chart: the points are the history file's runs (and the
   published reports before it); markers carry their causes and open the
   tooltip; no text on the chart.
D. History: champions (2016-17 named, the records-only seasons, a season with
   no bracket); all-time = LEAGUEHISTORY + the live season; head to head
   symmetric; the record book = RECORDS; the draft = the draft files, OVR then
   and now from the right sources; trades = the trade files.
E. Awards (Player of the Week) and the Archive (newest first, each opening its file).
F. Publish: History in encrypted part files, never in the page; the preview's templates.
G. The default-avatar rule (made-up images).
H. draft_ovr: the two days, and the cache against a rebuild (slow; Nick's machine).
I. The live hub: League adds v2 keys only.
J. Real state (slow; skipped without the league's state): the League payload, the
   preview in every segment and chip, publish mode with the budget and the scan.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import inspect
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import league_state                                    # noqa: F401
from test_hub_v2 import (synth_payload, render, visible_text, strings, tap_violations, GEN, PASS, TERMS, _archive,
                         budget_bytes, ROOT)
import hub_v2_league_fixture as LF
from modules.hub_v2 import league as L, view, page, page_league as PL, publish as v2pub, tokens
from modules import team_pictures as tp


def _league_html(h: str) -> str:
    i = h.index('data-route="league"')
    return h[i:h.index("</main>", i)]


def _inputs():
    return LF.inputs(synth_payload())


# =============================================================================
# A. the rules
# =============================================================================

def test_segments_and_chips_in_order():
    h = _league_html(render())
    seg = re.search(r'data-seg="league".*?</div>', h, re.S).group(0)
    assert re.findall(r'data-pane="(\w+)"', seg) == ["standings", "history", "awards", "archive"]
    assert re.findall(r'data-lhchip="(\w+)"', h) == ["champions", "alltime", "h2h", "records", "draft", "trades"]
    assert view.PLACEHOLDER not in h


def test_the_league_renderer_does_no_arithmetic():
    src = "".join(inspect.getsource(f) for f in (PL._standings, PL.awards_html, PL._race, PL._aw_info,
                                                 PL._awards_pane, PL._archive, PL._champions,
                                                 PL._alltime, PL._h2h, PL._records, PL._draft, PL._trades,
                                                 PL.chip_html, PL._history, PL.league_screen, PL.templates))
    for banned in ("round", "float", "sum", "sorted", "max", "min", "int"):
        assert not re.search(rf"\b{banned}\(", src), f"the League renderer calls {banned}("
    assert ".sort(" not in PL.JS


def test_every_number_in_league_and_its_history_is_a_payload_string():
    p = synth_payload()
    h = page.render(view.build(p, mode="preview", now=GEN + timedelta(hours=2)))
    text = visible_text(_league_html(h)) + " " + visible_text(PL.templates(view.build(p, mode="preview",
                                                                                       now=GEN)["league"], page._mono))
    known = " ".join(strings(p))
    for n in re.findall(r"\d+(?:[.,]\d+)*", text):
        assert n in known, f"{n!r} in League is in no payload string"


def test_a_lore_tag_in_a_league_string_never_reaches_the_page():
    p = synth_payload()
    p["v2"]["league"]["standings"]["note"] = "A note <!-- lore:phase-x --> here."
    p["v2"]["league_history"]["champions"]["note"] = "Champs <!-- lore:phase-y -->."
    h = render(p)
    assert "lore:" not in h and "phase-x" not in h and "phase-y" not in h


def test_league_css_is_tokens_only():
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", PL.CSS)
    assert not re.search(r"\d+px", PL.CSS)
    for v in set(re.findall(r"var\(--([a-z0-9-]+)\)", PL.CSS)) - {"n"}:     # --n: the grid's column count, inline
        assert f"--{v}:" in tokens.css(""), v


def test_league_taps_aria_and_nothing_hover_only():
    h = render()
    lg = _league_html(h) + PL.templates(view.build(synth_payload(), mode="preview", now=GEN)["league"], page._mono)
    assert not tap_violations("<body>" + lg + "</body>")
    assert not re.search(r"mouseover|mouseenter|mouseleave|:hover", PL.JS + PL.CSS)
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", lg, re.S):
        attrs, inner = m.groups()
        assert "aria-label" in attrs or visible_text(inner).strip(), attrs[:80]
    assert re.search(r'<svg class="lh-chart"[^>]*aria-label="Title odds by run', lg)


def test_league_is_offline():
    lg = _league_html(render(mode="publish"))
    assert not re.search(r"(?:src|href)=\"https?:", lg) and "url(http" not in PL.CSS


def test_the_tab_scripts_run_inside_the_page_closure_before_the_first_route():
    js = page.script()
    i_route = js.rindex("route();check130();")
    assert js.index("window.lgRoute") < i_route and js.index("var MK=") < i_route
    assert js.rstrip().endswith("})();")
    # 4c3's Sort select called sortTable from outside the closure: it threw
    assert js.index("function sortTable") < js.index("sortTable(tb,t.value)")


# =============================================================================
# B. Standings
# =============================================================================

def test_the_order_is_standings_order_with_ties_as_t_and_the_tie_said():
    from modules.data_loader import results_from, standings_order
    inp = _inputs()
    lg, _h = L.build(inp)
    res = L.week_results(inp)
    pairs = {int(w["week"]): w["matchups"] for w in inp["weeks"]}
    scores = {}
    for w, rows in res.items():
        for a, b, sa, sb, _o in rows:
            scores.setdefault(w, {}).update({a: sa, b: sb})
    rec, h2h, pts = results_from(scores, pairs, 15)
    assert [r["m"] for r in lg["standings"]["rows"]] == standings_order(rec, h2h, pts, LF.MGRS)
    rows = {r["m"]: r for r in lg["standings"]["rows"]}
    assert rows["Tyler"]["record"] == "4-3-1" and rows["Jordan"]["record"] == "4-3-1"      # a T shows
    assert rows["Tyler"]["tie"] and rows["Jordan"]["tie"] and not rows["Marcus"]["tie"]
    assert lg["standings"]["ties"] == ["Tyler and Jordan are level at 4-3-1: ordered on total points "
                                       "(head-to-head could not separate them)."]
    assert "* " + lg["standings"]["ties"][0] in visible_text(_league_html(render()))


def test_a_tie_head_to_head_breaks_is_said_so():
    inp = _inputs()
    # week 8: Jordan beats Tyler again (h2h Jordan 2-0-1)... make Tyler-Jordan week 5 a Jordan win too
    inp["weekly_scores"] = copy.deepcopy(inp["weekly_scores"])
    for m, v in (("Tyler", 1290.0), ("Jordan", 1300.0)):
        next(e for e in inp["weekly_scores"][m] if e["week"] == 5)["score"] = v
    # Tyler then 3-4-1, Jordan 5-2-1: level no more; make Marcus and Jordan level instead
    LF.sync_power(inp)
    lg, _ = L.build(inp)
    st = lg["standings"]
    assert all("head-to-head" in t for t in st["ties"])
    for t in st["ties"]:
        assert t.endswith("ordered on head-to-head.") or "could not separate" in t


def test_streaks_count_every_week_and_a_t_ends_one():
    res = {1: [("A", "B", 10.0, 5.0, "a")], 2: [("A", "B", 10.0, 5.0, "a")], 3: [("A", "B", 7.0, 7.0, "tie")]}
    assert L.streaks(res, ["A", "B"]) == {"A": "T1", "B": "T1"}
    res[4] = [("A", "B", 1.0, 5.0, "b")]
    assert L.streaks(res, ["A", "B", "C"]) == {"A": "L1", "B": "W1", "C": "\u2014"}
    res[17] = [("A", "B", 1.0, 5.0, "b")]                  # a postseason week counts too
    assert L.streaks(res, ["A", "B"])["B"] == "W2"


def test_standings_rows_carry_the_power_rows_odds_and_change():
    p = synth_payload()
    power = {r["manager"]: r for r in p["power"]["rows"]}
    for r in p["v2"]["league"]["standings"]["rows"]:
        assert (r["odds"], r["delta"]) == (power[r["m"]]["odds"], power[r["m"]]["delta"])


# =============================================================================
# C. the title-odds chart
# =============================================================================

def test_the_chart_points_are_the_history_runs_and_the_reports_before_them():
    inp = _inputs()
    lg, _ = L.build(inp)
    pts = lg["chart"]["points"]
    rows = sorted(inp["history_rows"], key=lambda r: r["as_of"])
    first = datetime.fromisoformat(rows[0]["as_of"]).date()
    reports = [w for w in sorted(inp["reports"]) if LF.WEEK1 + timedelta(days=7 * w) < first]
    assert len(pts) == len(rows) + len(reports)
    hist = pts[len(reports):]
    for p, r in zip(hist, rows):
        assert p["vals"] == {m: float(v) for m, v in r["title_odds"].items()}
        assert p["texts"] == {m: f"{float(v):.1f}%" for m, v in r["title_odds"].items()}
    xs = [p["x"] for p in pts]
    assert xs == sorted(xs) and 0.0 <= xs[0] and xs[-1] <= 1.0


def test_markers_carry_their_causes_and_open_the_tooltip_with_no_text_on_the_chart():
    lg, _ = L.build(_inputs())
    ev = lg["chart"]["events"]
    bodies = " ".join(e["tip"]["b"] for e in ev)
    assert "Week 4 final:" in bodies and "closing line priced" in bodies and "Trade: Dana \u21c4 Jordan" in bodies
    for e in ev:
        assert e["dir"] in ("up", "down") and e["tip"]["h"] and e["tip"]["f"]
    h = _league_html(render())
    svg = re.search(r'<svg class="lh-chart"[^>]*data-chart="lg-odds".*?</svg>', h, re.S).group(0)
    texts = re.findall(r"<text[^>]*>([^<]*)</text>", svg)
    for e in ev:
        assert e["tip"]["b"] not in " ".join(texts)
    hits = re.findall(r'<circle class="v2-ev-hit"[^>]*data-tip-b="([^"]*)"', svg)
    assert len(hits) == len(ev) and all('aria-expanded="false"' in m.group(0)
                                        for m in re.finditer(r'<circle class="v2-ev-hit"[^>]*>', svg))
    # labels: the y axis, the week ticks and one end label per team, nothing else
    assert all(re.fullmatch(r"\d+%|W\d+|[A-Z]{2} \d+\.\d%", t) for t in texts), texts


def test_a_cause_that_moved_nothing_gets_no_marker():
    inp = _inputs()
    rows = inp["history_rows"]
    i = next(k for k, r in enumerate(rows) if r["kind"] == "closing")
    rows[i]["title_odds"] = dict(rows[i - 1]["title_odds"])
    lg, _ = L.build(inp)
    at = [p["head"] for p in lg["chart"]["points"]]
    assert not any(e["tip"]["h"] == at[e["i"]].split(" \u00b7 ")[0] and "closing" in e["tip"]["b"]
                   and e["tip"]["h"].startswith(rows[i]["as_of"][5:10].replace("-", "-")) for e in lg["chart"]["events"]
                   if False)
    moved = [e for e in lg["chart"]["events"] if "closing" in e["tip"]["b"]]
    assert len(moved) == len([r for r in rows if r["kind"] == "closing"]) - 1


def test_power_history_is_the_published_reports_newest_first_with_the_rank_change():
    lg, _ = L.build(_inputs())
    w = lg["power"]["weeks"]
    assert [x["week"] for x in w] == ["3", "2", "1"]
    tyler = {x["week"]: next(r for r in x["rows"] if r["m"] == "Tyler") for x in w}
    assert tyler["1"]["move"] == "\u2014" and tyler["2"]["move"] == "\u25bc 1" and tyler["3"]["move"] == "\u25bc 1"


def test_an_unpublished_report_raises():
    inp = _inputs()
    inp["reports"][1]["metadata"]["run_mode"] = "test"
    with pytest.raises(L.LeagueError, match="not a published report"):
        L.build(inp)


# =============================================================================
# D. History
# =============================================================================

def test_champions_per_season_with_2015_16_named_and_the_records_only_seasons():
    """Nick, 11-19: the record-only seasons are 2014-15 and 2016-17; 2015-16 was
    not played (the earlier record had them the other way round).
    Nick, 11-20: each season's CHAMPION is the regular-season winner (the
    League Champion); the bracket's winner is the Playoff Champion, a line."""
    inp = _inputs()
    _, h = L.build(inp)
    rows = {r["season"]: r for r in h["champions"]["rows"]}
    assert list(rows)[0] == "2026-27" and rows["2026-27"]["kind"] == "live"
    assert rows["2026-27"]["lines"][0]["k"] == "League champion" and "in progress" in rows["2026-27"]["lines"][0]["t"]
    r = rows["2025-26"]
    assert r["who"] == r["m"] == "Tyler" and r["lines"][0]["k"] == "Runner-up"
    assert r["lines"][1]["k"] == "Playoff champion" and r["lines"][1]["t"].startswith("Jordan") and "over Tyler" in r["lines"][1]["t"]
    assert rows["2024-25"]["who"] == "Marcus" and rows["2024-25"]["lines"][1]["t"].startswith("Marcus")
    nb = rows["2023-24"]
    rank1 = next(x["manager"] for x in inp["all_standings"] if x["season"] == "2023-24" and x["regular_season_rank"] == 1)
    assert nb["kind"] == "nobracket" and nb["who"] == rank1
    assert nb["lines"][1]["k"] == "Playoffs" and "a made-up stoppage" in nb["lines"][1]["t"]
    assert rows["2015-16"]["kind"] == "off" and rows["2015-16"]["lines"][0]["k"] == "Not played"
    assert rows["2016-17"]["kind"] == "records" and rows["2016-17"]["who"] == "Tyler"
    assert rows["2016-17"]["lines"][0]["t"] == "Marcus" and rows["2016-17"]["lines"][1]["t"] == "Jordan, over Tyler"
    assert rows["2014-15"]["kind"] == "records" and rows["2014-15"]["who"] == "Marcus"
    seasons = [r["season"] for r in h["champions"]["rows"]]
    assert seasons.index("2017-18") < seasons.index("2016-17") < seasons.index("2015-16") < seasons.index("2014-15")


def test_every_seasons_headline_is_the_league_champion_never_the_bracket():
    """The error 4c4 shipped (Nick, 11-20): the bracket's winner headlined each
    season and the real champion sat on a "Regular season" sub-line."""
    from modules.season_outcomes import league_champion
    inp = _inputs()
    _, h = L.build(inp)
    by = {}
    for x in inp["all_standings"]:
        by.setdefault(x["season"], []).append(x)
    rows = {r["season"]: r for r in h["champions"]["rows"]}
    for s, rs in by.items():
        assert rows[s]["m"] == rows[s]["who"] == league_champion(rs), s
        assert not any(x["k"] == "Regular season" for x in rows[s]["lines"]), s
    for s, v in inp["pre_data_era"]["seasons"].items():
        assert rows[s]["who"] == v["league_champion"], s
    note = h["champions"]["note"]
    assert note.startswith("The champion is the League Champion: first in the regular season")
    assert "bracket's winner" not in note


def test_pre_data_era_seasons_must_agree_with_the_totals():
    inp = _inputs()
    inp["pre_data_era"]["seasons"]["2016-17"]["playoff_champion"] = "Marcus"
    with pytest.raises(L.LeagueError, match="disagree"):
        L.build(inp)


def test_pre_data_era_old_key_names_raise():
    """"champion" meant the bracket's winner in the config; renamed 11-20."""
    inp = _inputs()
    v = inp["pre_data_era"]["seasons"]["2016-17"]
    v["champion"] = v.pop("playoff_champion")
    with pytest.raises(L.LeagueError, match="old key"):
        L.build(inp)


def test_alltime_is_leaguehistory_plus_the_live_season():
    inp = _inputs()
    _, h = L.build(inp)
    res = L.week_results(inp)
    for r in h["alltime"]["rows"]:
        lh = next(x for x in inp["leaguehistory"] if x["manager_name"] == r["m"])
        w, l, t = L._wl(lh["regular_season_record"])
        lw = sum(1 for rows in res.values() for a, b, _sa, _sb, o in rows if (a == r["m"] and o == "a") or (b == r["m"] and o == "b"))
        ll = sum(1 for rows in res.values() for a, b, _sa, _sb, o in rows if (a == r["m"] and o == "b") or (b == r["m"] and o == "a"))
        lt = sum(1 for rows in res.values() for a, b, _sa, _sb, o in rows if r["m"] in (a, b) and o == "tie")
        assert r["record"] == L._rec(w + lw, l + ll, t + lt)
        done = float(lh["total_points_scored_to_date"]) - float(lh["total_points_current_season"])
        live = sum(e["score"] for e in inp["weekly_scores"][r["m"]])
        assert r["pf"] == f"{done + live:,.0f}"
        assert r["titles"] == str(lh["titles_won"]) and r["playoff_titles"] == str(lh["playoff_championships"])
    assert "every season with records" in h["alltime"]["note"] and "2015-16 was not played" in h["alltime"]["note"]
    assert "Titles = League Championships" in h["alltime"]["note"]


def test_head_to_head_is_symmetric_and_splits_the_postseason():
    _, h = L.build(_inputs())
    hh = h["h2h"]
    ms = hh["order"]
    for ph in ("reg", "post"):
        g = {r["m"]: r["cells"] for r in hh["grid"][ph]}
        for i, a in enumerate(ms):
            assert g[a][i] is None
            for j, b in enumerate(ms):
                if a == b:
                    continue
                wa = [int(x) for x in g[a][j]["t"].split("-")]
                wb = [int(x) for x in g[b][i]["t"].split("-")]
                assert wa[0] == wb[1] and wa[1] == wb[0] and (wa[2:] == wb[2:])
    assert set(hh["pairs"]) == {f"{a}|{b}" for a in ms for b in ms if a != b}
    pr = hh["pairs"]["Marcus|Tyler"]
    assert pr["lines"][0]["season"] == "2026-27" and any("postseason" in x["t"] for x in pr["lines"])


def test_the_record_book_equals_records_json():
    inp = _inputs()
    _, h = L.build(inp)
    at = inp["records_alltime"]
    shown = {lst["key"]: lst for g in h["records"]["groups"] for lst in g["lists"]}
    assert list(shown) == [k for k, *_ in L.RECORD_BOOK]
    for key, _label, _g, val, who in L.RECORD_BOOK:
        top = at[f"{key}_top10"]
        assert [r["value"] for r in shown[key]["rows"]] == [val(e) for e in top]
        assert [r["who"] for r in shown[key]["rows"]] == [who(e) for e in top]
    assert [t["key"] for t in h["records"]["tiles"]] == L.TILES
    tip = shown["highest_weekly_score"]["rows"][0]["tip"]
    assert tip["h"] == "2024-25 \u00b7 Week 1 \u00b7 2024-10-20" and "won by" in tip["f"]
    with pytest.raises(L.LeagueError, match="closest_game_top10"):
        bad = _inputs()
        del bad["records_alltime"]["closest_game_top10"]
        L.build(bad)


def test_the_draft_equals_the_draft_files_with_ovr_from_the_right_days():
    inp = _inputs()
    _, h = L.build(inp)
    by = {s["season"]: s for s in h["draft"]["seasons"]}
    assert list(by) == ["2026-27", "2025-26"]
    cur = by["2026-27"]
    assert [r["player"] for r in cur["rows"]] == [p["player_name"] for p in inp["draft_current"]["picks"]]
    assert "Jordan 3" in cur["drafted"] and "Marcus 2" in cur["drafted"]        # the one manager with an extra pick
    assert cur["later_label"] == "Now" and by["2025-26"]["later_label"] == "Deadline"
    g = next(r for r in cur["rows"] if r["player"] == "Marcus Guard")
    assert (g["then"], g["later"], g["chg"]) == ("84", "88", "\u25b24")            # live opening day, today's OVR
    big = next(r for r in cur["rows"] if r["player"] == "Marcus Big")
    assert big["keeper"] and big["then"] == "\u2014" and "league average" in big["then_why"]
    fg = next(r for r in cur["rows"] if r["player"] == "Free Guy")
    assert fg["later"] == "\u2014" and "on no roster and not on the Players tab" in fg["later_why"]
    past = {r["player"]: r for r in by["2025-26"]["rows"]}
    assert (past["Marcus Guard"]["then"], past["Marcus Guard"]["later"]) == ("74", "81")
    assert past["Dana Guard"]["later"] == "\u2014" and past["Dana Guard"]["later_why"] == "not on a roster that day"
    assert [r["pick"] for r in by["2025-26"]["rows"]] == ["1.01", "1.02", "1.03", "1.04"]


def test_a_missing_cache_or_failed_ratings_says_why():
    inp = _inputs()
    inp["draft_ovr"], inp["now_ovr"], inp["ratings_error"] = None, None, "RatingsInputError: boom"
    _, h = L.build(inp)
    by = {s["season"]: s for s in h["draft"]["seasons"]}
    assert "build_draft_ovr.py" in by["2025-26"]["rows"][0]["then_why"]
    assert "boom" in by["2026-27"]["rows"][0]["later_why"]


def test_trades_equal_the_trade_files_with_picks_to_the_receiver():
    inp = _inputs()
    _, h = L.build(inp)
    items = h["trades"]["items"]
    assert len(items) == len(inp["all_trades"]) + len(inp["trades_now"])
    assert items[0]["season"] == "2026-27"                                   # newest first
    old = items[1]
    gets = {s["m"]: [g["t"] for g in s["gets"]] for s in old["sides"]}
    assert gets["Marcus"] == ["Tyler Wing", "2026 8th (Tyler)"] and gets["Tyler"] == ["Marcus Wing", "2026 4th (Marcus)"]
    bad = copy.deepcopy(inp)
    bad["all_trades"][0]["players"][0]["to_manager"] = "Nobody"
    with pytest.raises(L.LeagueError, match="outside its two managers"):
        L.build(bad)


# =============================================================================
# E. Awards and the Archive
# =============================================================================

def test_awards_show_the_races_and_player_of_the_week_with_its_backfilled_points():
    lg, _ = L.build(_inputs())
    aw = lg["awards"]
    assert [s["season"] for s in aw["potw"]] == ["2026-27", "2025-26"]
    assert aw["potw"][0]["rows"][0]["week"] == "Wk 8"
    # 4c5 (4c4 decision 14): week 1's points from the league log, his started games only (61.5 + 48.0)
    wk2, wk1 = aw["potw"][1]["rows"]
    assert wk1["pts"] == "109.5" and wk1["sub"].startswith("2 games") and "from the league log" in wk1["sub"]
    assert wk2["pts"] == "\u2014" and "not recorded" in wk2["sub"]          # not in the log: never guessed
    assert set(aw) == {"potw", "potw_note", "races", "races_error", "par_note", "races_note"}
    assert [a["key"] for a in aw["races"]] == ["mvp", "pickup", "improved", "roy", "trade", "bust"]
    assert aw["races_error"] == ""


def test_the_archive_lists_every_issue_newest_first_each_opening_its_file():
    p = synth_payload()
    p["newsletter"]["archive"] = [{"week": "7", "label": "Week 7", "file": "week07-bbbbbbbbbbbb.enc", "size": "2.3 MB"}]
    LF.add_league(p)
    pv, pb = _league_html(render(p)), _league_html(render(p, mode="publish"))
    assert re.findall(r'data-href="hub_archive/(week\d\d)', pv) == ["week08", "week07"]
    assert re.findall(r'data-issue="(week\d\d)', pb) == ["week08", "week07"]
    assert "A made-up headline" in pv


# =============================================================================
# F. publish: History as encrypted parts
# =============================================================================

def test_history_is_published_as_encrypted_parts_and_never_in_the_page(tmp_path):
    from modules import hub_crypto, hub_publish
    e = _archive(tmp_path)
    p = synth_payload()
    p["v2"]["issue"]["file"] = e["enc"]
    out = tmp_path / "_to_delete" / "4c4" / "publish"
    rep = v2pub.build(tmp_path, p, PASS, salt=b"\x02" * 16, out_dir=out, iterations=1000, terms=TERMS, now=GEN)
    assert rep["league_parts"]["parts"] == 8 and rep["served_bytes"] <= budget_bytes()       # 4c5: + Awards; 5b: + the odds chart
    assert hub_publish.scan_dir(out, TERMS)["hits"] == {}
    inner = v2pub.open_inner(PASS, json.loads(re.search(r'id="hub-bundle">(.*?)</script>',
                                                        (out / "index.html").read_text(encoding="utf-8"), re.S).group(1)))
    pg = inner["page"]
    assert 'id="v2-lg-' not in pg and "Champions:" not in pg                 # no History in the page itself
    refs = dict(re.findall(r'data-lhchip-of="(\w+)" data-part=\'([^\']+)\'', pg))
    assert set(refs) == {"champions", "alltime", "h2h", "records", "draft", "trades"}
    import html as _html
    ref = json.loads(_html.unescape(refs["h2h"]))
    blob = (out / ref["file"]).read_bytes()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pt = AESGCM(hub_crypto.unb64(ref["key"])).decrypt(blob[:12], blob[12:], None)
    part = json.loads(gzip.decompress(pt))
    assert "data-lhpair=" in part["html"] and "Head to head" in part["html"]


def test_the_preview_carries_every_chip_as_a_template():
    h = render()
    for k in ("champions", "alltime", "h2h", "records", "draft", "trades"):
        assert f'<template id="v2-lg-{k}">' in h
    assert "<template" not in render(mode="publish")


def test_without_the_side_file_history_says_so():
    p = synth_payload()
    del p["v2"]["league_history"]
    h = _league_html(render(p))
    assert "The history is not in this build" in h


def test_the_side_file_carries_history_and_a_stale_one_refuses():
    from modules.hub_v2 import data as v2data
    p = synth_payload()
    p["v2"]["players"] = {"rows": []}
    obj = v2data.players_file(p)
    assert "league_history" in obj and "league_history" not in p["v2"] and p["v2"]["players_file"]["league_history"]
    v2data.attach_players(p, obj)
    assert p["v2"]["league_history"] == obj["league_history"]
    q = synth_payload()
    q["v2"]["players"] = {"rows": []}
    o2 = v2data.players_file(q)
    del o2["league_history"]
    with pytest.raises(v2data.V2Error, match="lacks League's History"):
        v2data.attach_players(q, o2)


# =============================================================================
# G. the default avatar
# =============================================================================

def _png(color, size=(64, 64)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_yahoos_default_avatar_shows_the_monogram(tmp_path):
    mine, generic = _png((10, 120, 200)), _png((128, 128, 128))
    urls = {"Marcus": "https://img.example/custom/marcus.png", "Tyler": "https://img.example/default/generic_3.png",
            "Dana": "https://img.example/x/dana.png"}
    get = {urls["Marcus"]: mine, urls["Tyler"]: generic, urls["Dana"]: generic}.__getitem__
    rules = {"sha256": {hashlib.sha256(generic).hexdigest()}, "url_contains": ["/default/"]}
    now = datetime(2026, 12, 2, 0, 5, tzinfo=timezone(timedelta(hours=-8)))
    blk = tp.store(tmp_path, ["Marcus", "Tyler", "Dana"], urls, get, now, rules=rules)
    assert blk["teams"]["Tyler"]["default"] == "url" and blk["teams"]["Dana"]["default"] == "sha256"
    assert blk["teams"]["Marcus"]["sha"] and blk["teams"]["Marcus"]["raw_sha256"] == hashlib.sha256(mine).hexdigest()
    uris, _ = tp.data_uris(tmp_path, ["Marcus", "Tyler", "Dana"])
    assert set(uris) == {"Marcus"}                          # the other two show their monograms
    # a stored custom picture replaced by the default goes back to the monogram
    get2 = {urls["Marcus"]: generic}.__getitem__
    tp.store(tmp_path, ["Marcus"], {"Marcus": urls["Marcus"]}, get2, now, rules=rules)
    assert tp.data_uris(tmp_path, ["Marcus"])[0] == {}
    # empty rules match nothing
    assert tp.is_default(urls["Tyler"], generic, {"sha256": set(), "url_contains": []}) is None


def test_the_default_rules_are_required_in_config():
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    r = tp.default_rules(cfg)
    assert r == {"sha256": set(), "url_contains": []}         # empty until the first nightly shows the default
    del cfg["hub"]["default_avatars"]
    with pytest.raises(tp.PictureError, match="default_avatars"):
        tp.default_rules(cfg)


# =============================================================================
# H. draft_ovr
# =============================================================================

def test_the_deadline_point_is_4as():
    from modules import draft_ovr
    f = draft_ovr.deadline_fraction(ROOT)
    assert abs(f - (date(2027, 3, 4) - date(2026, 10, 20)).days / (date(2027, 4, 11) - date(2026, 10, 20)).days) < 1e-9
    rows = [{"date": d} for d in ("2020-10-01", "2020-10-02", "2020-10-05", "2020-10-09", "2020-10-11")]
    assert draft_ovr.points_of(rows, 0.5) == ("2020-10-01", "2020-10-05")


@pytest.mark.slow
def test_the_cache_is_ratings_rate_on_the_right_days():
    """data/historical/DRAFT_OVR.json equals a rebuild (ratings.rate on each
    season's opening day and deadline point, 4a's schedule): Nick's machine
    only (basketball-reference's pages in data/.cache)."""
    from modules import draft_ovr
    if not (ROOT / "data" / ".cache").is_dir():
        pytest.skip("no data/.cache: the past schedules live on Nick's machine only")
    cache = draft_ovr.load(ROOT)
    assert cache is not None
    fresh = draft_ovr.build_cache(ROOT)
    assert fresh == cache
    s = cache["seasons"]["2017-18"]
    assert all(p["then"] is None and p["then_reason"] == draft_ovr.THEN_NO_PRIOR or p["then_reason"] != draft_ovr.THEN_NO_PRIOR
               for p in s["picks"])
    # 4a4: the skill OVR rates from NBA history (and the draft slot), so even the log's first
    # season has an opening-day OVR for every pick; the week-2 stand-in (4c5) is no longer needed
    assert all(p["then"] is not None and p["then_point"] == "open" for p in s["picks"])
    assert sum(p["then"] is None for s2 in cache["seasons"].values() for p in s2["picks"]) <= 10


# =============================================================================
# I. the live hub
# =============================================================================

def test_league_soft_adds_v2_keys_only_and_fails_softly():
    from modules.hub_v2 import data as v2data
    p = synth_payload()
    before = {k: copy.deepcopy(v) for k, v in p.items() if k != "v2"}
    v2 = p["v2"]
    v2.pop("league"), v2.pop("league_history")
    out, err = v2data.league_soft(ROOT, p, {"data": None, "now": GEN}, echo=lambda *a: None)
    assert out is None and err["stage"] == "league"
    assert {k: v for k, v in p.items() if k not in ("v2",)} == before
    assert "league" not in v2 and "league_history" not in v2
    from modules import hub_page
    src = inspect.getsource(hub_page)
    assert "league_history" not in src and "hub_v2" not in src


# =============================================================================
# J. real state
# =============================================================================

@pytest.mark.slow
def test_real_league_in_every_segment_and_chip_the_preview_and_publish(tmp_path):
    """Today's state, unstubbed: the hub build's League, the v2 preview's every
    segment and chip, and publish mode to a temp folder (a throwaway passphrase
    and a fresh salt) within the budget and clean of plaintext."""
    import os
    from modules import hub_state, hub_publish
    league_state.skip_if_actuals_behind()          # H51: the real build reads actuals through yesterday
    po = {}
    p = hub_state.build(ROOT, allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po)
    assert p["v2_error"] is None, p["v2_error"]
    from modules.hub_v2 import data as v2data
    v2data.attach_players(p, po)
    lg, hist = p["v2"]["league"], p["v2"]["league_history"]
    assert [r["rank"] for r in lg["standings"]["rows"]] == ["1", "2", "3", "4"]
    assert lg["chart"]["points"] and lg["archive"]["issues"]
    assert {s["season"] for s in hist["draft"]["seasons"]} >= {"2026-27", "2017-18"}
    cur = next(s for s in hist["draft"]["seasons"] if s["season"] == "2026-27")
    counts = dict(x.split(" ") for x in cur["drafted"].split(" \u00b7 "))
    assert counts["Hayden"] == "9"                           # the draft results are right (handoff)
    seasons = [r["season"] for r in hist["champions"]["rows"]]
    assert "2016-17" in seasons and seasons[0] == "2026-27"
    h = page.render(view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]),
                               pictures=tp.data_uris(ROOT, p["v2"]["team_order"])[0]))
    for key in ("standings", "history", "awards", "archive"):
        assert f'data-pane-of="{key}"' in h
    for k in ("champions", "alltime", "h2h", "records", "draft", "trades"):
        assert f'<template id="v2-lg-{k}">' in h
    terms = hub_publish.scan_terms(ROOT)
    out = tmp_path / "_to_delete" / "4c4" / "publish"
    rep = v2pub.build(ROOT, p, "throwaway " + os.urandom(8).hex(), salt=os.urandom(16), out_dir=out,
                      iterations=1000, terms=terms)
    assert rep["served_bytes"] <= budget_bytes()
    assert rep["league_parts"]["parts"] == 8 and rep["league_parts"]["largest"] <= 60_000          # 5b: + the odds chart
    assert hub_publish.scan_dir(out, terms)["hits"] == {}
