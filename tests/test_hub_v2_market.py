"""
tests/test_hub_v2_market.py -- 4c3: the new hub's Market tab, the advice view
(Advice.html v5) and the team pictures
(claude/HANDOFF_4C3_MARKET_ADVICE_2026-11-18.md s.1-s.3, s.6).

On the synthetic league (tests/test_hub_v2.py, with its Market by the real
market.build: tests/hub_v2_market_fixture.py), made-up names and numbers, and
made-up images generated here in memory -- never a real picture.

A. Market: the segments in order; each segment's rows come from the payload;
   the game cells' tooltips list the days their count counts; the filters'
   data; the moves newest first, by team; no "what they want" anywhere; every
   player name opens his card, every team chip its team.
B. The advice view: activation, step 1, THEN, step 2, the plan line, the
   backup; every row closed at first; the flag only on contested adds; "All
   three" / "Both moves"; both switches each way; the one-sentence states;
   every number an engine string; a negative activation as it is; a file from
   before 4c3 still renders, with no activation numbers.
C. Team pictures: fetched and cached by content; a changed picture replaces
   the old one; a failure is recorded and falls back (last good, else the
   monogram); TeamMark draws it once per team; no picture in a plaintext
   published file; the nightly step is soft.
D. The live hub's advice card: unchanged but for the activation's numbers line.
E. Real state (slow; skipped without the league's state): the hub build's
   Market in every segment, the v2 preview, publish mode with the budget and
   the plaintext scan.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import hub_v2_market_fixture as MF
from test_hub_v2 import (synth_payload, render, visible_text, strings, tap_violations, _archive, GEN, PASS,
                         TERMS, ROOT, MGRS, TEAMS, SLOTS, budget_bytes)
from modules import advice_live as al
from modules import team_pictures as tp
from modules.hub_v2 import market, view, page, publish as v2pub

MINUS = "\u2212"


def _market_html(h: str) -> str:
    i = h.index('data-route="market"')
    return h[i:h.index('data-route="league"', i)]


def _pane(h: str, key: str) -> str:
    m = _market_html(h)
    i = m.index(f'data-pane-of="{key}"')
    j = m.find('data-pane-of="', i + 20)
    return m[i:j if j > 0 else len(m)]


def _payload(**kw):
    p = synth_payload()
    if kw:
        MF.add_market(p, **kw)
    return p


# =============================================================================
# A. Market
# =============================================================================

def test_the_segments_in_the_advice_mockups_order_and_the_placeholder_is_gone():
    h = render()
    m = _market_html(h)
    segs = re.findall(r'data-seg="market".*?</div>', m, re.S)[0]
    assert re.findall(r'data-pane="(\w+)"', segs) == ["available", "stash", "advice", "block", "moves"]
    assert re.findall(r'data-pane="\w+" aria-selected="(\w+)"', segs) == ["true", "false", "false", "false", "false"]
    assert "Coming in the new hub" not in m
    lg = h[h.index('data-route="league"'):]
    assert "Coming in the new hub" in lg[:2000]                       # League keeps its placeholder (4c4)


def test_advice_hub_off_leaves_the_advice_segment_out():
    h = render(_payload(advice_on=False))
    segs = re.findall(r'data-seg="market".*?</div>', _market_html(h), re.S)[0]
    assert re.findall(r'data-pane="(\w+)"', segs) == ["available", "stash", "block", "moves"]
    assert 'data-pane-of="advice"' not in h and "adv-row" not in _market_html(h)


def test_available_rows_come_from_the_payload_and_the_cells_tooltips_match_the_counts():
    p = synth_payload()
    a = p["v2"]["market"]["available"]
    fa = p["free_agents"]["rows"][0]
    row = a["rows"][0]
    z = next(r for r in p["v2"]["players"]["rows"] if r["name"] == MF.FA_NAME)
    assert (row["name"], row["fppg"], row["l14"], row["proj"]) == (fa["name"], z["fppg"], z["l14"], fa["proj"])
    assert [c["n"] for c in row["games"]] == [fa["g1"], fa["g2"], fa["g3"]]
    for c in row["games"]:
        assert len(c["tip"]["b"].split(" \u00b7 ")) == int(c["n"])     # the days its count counts
    pane = _pane(render(p), "available")
    cells = re.findall(r'<button type="button" class="v2-mkcell"[^>]*data-tip-b="([^"]*)"[^>]*>'
                       r'<span class="v2-mkbox[^"]*">(\d+)</span>', pane)
    assert len(cells) == 3 and all(len(b.split(" &middot; " if "&middot;" in b else " \u00b7 ")) == int(n)
                                   for b, n in cells)
    assert 'data-pos="SF PF"' in pane and 'data-h="1"' in pane and "id=\"mk-fa\"" in pane
    assert json.loads(re.search(r"data-orders='([^']*)'", pane).group(1).replace("&quot;", '"')) == a["orders"]


def test_an_out_day_lowers_the_count_and_says_so_and_a_mismatch_raises():
    out = {MF.FA_NAME: {MF.WEEKS[10][1]}}
    p = synth_payload()
    p["free_agents"] = MF.free_agents()
    p["free_agents"]["rows"][0]["g2"] = "2"
    mk = market.build(p, {"fa_av": MF.FaAv(out), "col_specs": MF.col_specs(), "advice_on": False, "advice": None,
                          "show_title": True, "first_day": date(2026, 10, 20)})
    c = mk["available"]["rows"][0]["games"][1]
    assert c["n"] == "2" and c["tip"]["f"].startswith("out ")
    with pytest.raises(market.MarketError, match="games in the free-agent table"):
        market.build(p, {"fa_av": MF.FaAv(), "col_specs": MF.col_specs(), "advice_on": False, "advice": None,
                         "show_title": True, "first_day": date(2026, 10, 20)})


def test_the_orders_put_the_best_first_and_a_missing_value_last():
    assert market.order_desc([30.1, None, 41.0, 30.1], ["b", "x", "c", "a"]) == [2, 3, 0, 1]


def test_stash_and_block_come_from_the_payload_and_nothing_says_what_they_want():
    p = synth_payload()
    h = render(p)
    st = _pane(h, "stash")
    assert "Stash Guy" in st and "O \u00b7 back 01-13" in visible_text(st) and "Open IL slots now: Dana 1." in st
    bl = _pane(h, "block")
    assert "On the block:" in visible_text(bl) and "Jordan Bench" in bl and "Selling" in bl
    assert "want" not in visible_text(bl).lower()                     # 4b decision 6: no "what they want"
    assert "what they want" not in visible_text(_market_html(h)).lower()
    bad = copy.deepcopy(p)
    bad["trade_block"]["cards"][0]["lists"] = [{"label": "Wants", "key": "wants", "rows": []}]
    with pytest.raises(market.MarketError, match="4b decision 6"):
        market.block(bad["trade_block"], MGRS)


def _moves_payload():
    p = synth_payload()
    it = lambda day, date_, time_, who, kind, parts: {"day": day, "date": date_, "time": time_, "who": who,
                                                      "what": "", "note": "", "state": "Applied", "kind": kind,
                                                      "parts": parts}
    add = lambda n: {"kind": "add", "marker": "+", "text": f"added {n}", "segs": [{"t": "added "}, {"t": n}]}
    p["moves"]["weeks"] = [
        {"key": "8", "label": "Week 8", "items": [it("Fri", "11/27", "9:00 PM", "Dana", "add", [add("Old Guy")])]},
        {"key": "9", "label": "Week 9", "items": [
            it("Mon", "11/30", "6:11 AM", "Marcus", "add", [add("Free Guy")]),
            it("Tue", "12/1", "8:00 AM", "Trade:", "trade",
               [{"kind": "trade", "marker": "\u21c4", "text": "Tyler gets A", "segs": [{"t": "Tyler gets A"}]},
                {"kind": "trade", "marker": "\u21c4", "text": "Jordan gets B", "segs": [{"t": "Jordan gets B"}]}])]}]
    return MF.add_market(p)


def test_the_moves_are_newest_first_with_markers_and_their_teams_for_the_chips():
    p = _moves_payload()
    items = p["v2"]["market"]["moves"]["items"]
    assert [x["when"] for x in items] == ["Tue 12-01", "Mon 11-30", "Fri 11-27"]
    assert [x["marker"] for x in items] == ["\u21c4", "+", "+"]
    assert items[0]["ms"] == ["Tyler", "Jordan"] and items[1]["ms"] == ["Marcus"]
    mv = _pane(render(p), "moves")
    assert re.findall(r'data-mvf="(\w*)"', mv) == ["", *MGRS]
    assert re.findall(r'class="v2-mv" data-ms="([^"]*)"', mv) == ["Tyler Jordan", "Marcus", "Dana"]


def test_a_move_naming_no_manager_raises():
    p = synth_payload()
    p["moves"]["weeks"][0]["items"][0]["who"] = "Nobody"
    with pytest.raises(market.MarketError, match="names no manager"):
        market.moves(p["moves"], MGRS, date(2026, 10, 20))


def test_every_player_name_opens_his_card_and_every_team_chip_its_team():
    h = render()
    m = _market_html(h)
    assert 'href="#/players/free-guy"' in _pane(h, "available")
    assert 'href="#/players/jordan-bench"' in _pane(h, "block")
    for t in re.findall(r'<a class="lh-chip [^"]*" href="([^"]*)"', m):
        assert t.startswith("#/teams/") and t[len("#/teams/"):] in MGRS


def test_the_4b_rules_hold_on_market():
    h = render()
    assert not [b for b in tap_violations(h) if any(c.startswith(("adv", "v2-mk", "v2-mv")) for c in b[1])]
    m = _market_html(h)
    assert "http://" not in m and "https://" not in m                  # offline
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", page.pm.CSS) and not re.search(r"\d+px", page.pm.CSS)
    assert not re.search(r"onmouse|:hover", m + page.pm.CSS)          # nothing hover-only
    for b in re.findall(r'<button type="button" class="v2-mkcell"[^>]*>', m):
        assert 'aria-label="' in b and 'aria-expanded="false"' in b
    for b in re.findall(r'<button type="button" class="adv-(?:row|bk)[^>]*>', m):
        assert 'aria-controls="' in b and 'aria-expanded="false"' in b
    assert 'aria-label="Another team wants him too"' in m


# =============================================================================
# B. the advice view
# =============================================================================

def _card(h: str, m: str) -> str:
    a = _pane(h, "advice")
    i = a.index(f'data-manager="{m}"')
    j = a.find("</section>", i)
    return a[i:j]


def test_the_order_activation_step_1_then_step_2_the_plan_line_the_backup():
    c = _card(render(), "Marcus")
    then = [x.start() for x in re.finditer("adv-then", c)]
    assert len(then) == 2                                              # between the three rows
    marks = [c.index("adv-row--il"), then[0], c.index('aria-label="Step 1"'), then[1],
             c.index('aria-label="Step 2"'), c.index('class="adv-plan"'), c.index('class="adv-bk"')]
    assert marks == sorted(marks)
    assert "Activate from IL \u00b7 no add" in c and "&#8634;" in c
    assert "Win % change" in c
    v = visible_text(c)
    assert "All three" in v and "title odds +2.6%" in v


def test_every_row_starts_closed_and_opens_its_own_part():
    a = _pane(render(), "advice")
    rows = re.findall(r'<button type="button" class="adv-(?:row|bk)[^"]*" aria-expanded="(\w+)" aria-controls="(\w+)"', a)
    assert rows and all(e == "false" for e, _ in rows)
    for _e, did in rows:
        assert re.search(rf'<div class="adv-det" id="{did}" hidden>', a)


def test_the_flag_only_on_a_contested_add():
    h = render()
    mc, tc = _card(h, "Marcus"), _card(h, "Tyler")
    s1 = mc[mc.index('aria-label="Step 1"'):mc.index('aria-label="Step 2"')]
    s2 = mc[mc.index('aria-label="Step 2"'):]
    assert "adv-flag" not in s1 and "adv-flag" in s2 and "adv-flag" in tc
    assert "Also wanted by" in s2 and 'href="#/teams/Tyler"' in s2


def test_both_moves_when_an_activation_and_one_step():
    adv = MF.advice_latest()
    e = adv["managers"]["Marcus"]
    e["plan"] = e["plan"][:1]
    e["plan_total"]["v2"] = dict(e["plan_total"]["v2"], label=al.PLAN_LABELS[2], rows=2)
    c = _card(render(_payload(advice=adv)), "Marcus")
    assert "Both moves" in visible_text(c) and "All three" not in visible_text(c)
    # no plan line with one row
    tc = _card(render(), "Tyler")
    assert 'class="adv-plan"' not in tc


def test_title_odds_switch_off_leaves_no_tile_and_no_plan_title():
    h = render(_payload(advice=MF.advice_latest(show_title=False), show_title=False))
    a = _pane(h, "advice")
    assert "Title odds" not in visible_text(a) and "title odds" not in visible_text(a)
    assert visible_text(a).count("Starts") >= 3
    h2 = render()
    assert "Title odds" in visible_text(_pane(h2, "advice"))


def test_the_one_sentence_states():
    h = render()
    assert "Standing pat is best this week." in visible_text(_card(h, "Dana"))
    assert "No adds left. Resets Monday." in visible_text(_card(h, "Jordan"))
    assert "adv-row" not in _card(h, "Dana") and "adv-row" not in _card(h, "Jordan")


def test_every_number_in_the_advice_view_is_an_engine_string():
    p = synth_payload()
    pool = set(strings(p["v2"]["market"]["advice"]))
    v = visible_text(_pane(render(p), "advice"))
    for num in re.findall(r"[+\u2212-]?\d+(?:\.\d+)?%?", v):
        assert any(num in s for s in pool), num


def test_a_negative_activation_renders_as_it_is():
    p = _payload(advice=MF.advice_latest(act_dwp=(-0.011, 0.048)))
    c = _card(render(p), "Marcus")
    il = c[c.index("adv-row--il"):c.index('aria-label="Step 1"')]
    assert f'<span class="adv-v adv-v--down">{MINUS}1.1%</span>' in il
    assert '<span class="adv-v">+4.8%</span>' in il


def test_a_file_from_before_4c3_still_renders_with_no_activation_numbers():
    p = _payload(advice=MF.advice_latest(pre_4c3=True))
    c = _card(render(p), "Marcus")
    il = c[c.index("adv-row--il"):c.index('aria-label="Step 1"')]
    assert "\u2014" in visible_text(il) and "%" not in visible_text(il)
    assert "Marcus Hurt is back for week 10" in visible_text(c)          # its reason: the step's own text
    assert "+4.6%" in visible_text(c)                                   # the steps' strings, from their numbers
    # the plan line without the activation (its total is the steps') still says how many rows
    assert "Both moves" in visible_text(c)


def test_advice_failed_or_season_over_says_so_and_shows_no_pick():
    adv = MF.advice_latest()
    adv["error"] = "boom"
    a = _pane(render(_payload(advice=adv)), "advice")
    assert "Advice could not be updated" in a and "adv-row" not in a


# =============================================================================
# C. team pictures (made-up images only)
# =============================================================================

def _img(colour, size=(300, 200), fmt="PNG") -> bytes:
    PIL = pytest.importorskip("PIL.Image")
    im = PIL.new("RGB", size, colour)
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def _teams_json(urls: dict) -> dict:
    return {f"t.{i}": {"team_key": f"t.{i}", "name": f"Team {m}",
                       "team_logos": [{"team_logo": {"size": "large", "url": u}}] if u else []}
            for i, (m, u) in enumerate(urls.items())}


def _by_name(name, team_key=None):
    return name[len("Team "):]


NOW = datetime(2026, 12, 2, 0, 10, tzinfo=timezone(timedelta(hours=-8)))


def test_logo_urls_reads_yahoos_shape_by_team_key_and_prefers_https():
    tj = _teams_json({"Marcus": "http://x.example/a.png", "Tyler": None})
    tj["t.0"]["team_logos"].insert(0, {"team_logo": {"size": "small", "url": "https://x.example/s.png"}})
    assert tp.logo_urls(tj, manager_of=_by_name) == {"Marcus": "https://x.example/a.png"}

    def unknown(name, team_key=None):
        raise KeyError(f"no manager for {name}")
    with pytest.raises(KeyError):
        tp.logo_urls(tj, manager_of=unknown)


def test_fetch_stores_each_picture_downscaled_and_cached_by_content(tmp_path):
    pics = {"https://x/a.png": _img((200, 30, 30)), "https://x/b.png": _img((30, 30, 200), (90, 90), "JPEG")}
    got = []
    blk = tp.fetch(tmp_path, ["Marcus", "Tyler"], _teams_json({"Marcus": "https://x/a.png", "Tyler": "https://x/b.png"}),
                   now=NOW, get_bytes=lambda u: got.append(u) or pics[u], manager_of=_by_name)
    idx = tp.load_index(tmp_path)
    assert set(idx["teams"]) == {"Marcus", "Tyler"} and blk["failures"] == {}
    for m, v in idx["teams"].items():
        data = (tmp_path / tp.DIR / v["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == v["sha"] and v["file"].startswith(v["sha"][:16])
        assert v["mime"] == "image/jpeg"
    assert idx["teams"]["Marcus"]["px"] == tp.PX                       # 300x200 -> 144 square
    assert idx["teams"]["Tyler"]["px"] == 90                           # never enlarged
    files = sorted(p.name for p in (tmp_path / tp.DIR).iterdir())
    assert len(files) == 3                                             # two pictures and the index
    # the same pictures again: nothing changes
    blk2 = tp.fetch(tmp_path, ["Marcus", "Tyler"], _teams_json({"Marcus": "https://x/a.png", "Tyler": "https://x/b.png"}),
                    now=NOW + timedelta(days=1), get_bytes=lambda u: pics[u], manager_of=_by_name)
    assert not any(v["changed"] for v in blk2["teams"].values())
    assert sorted(p.name for p in (tmp_path / tp.DIR).iterdir()) == files


def test_a_changed_picture_replaces_the_old_one(tmp_path):
    a, b = _img((10, 200, 10)), _img((200, 200, 10))
    tj = _teams_json({"Marcus": "https://x/a.png"})
    tp.fetch(tmp_path, ["Marcus"], tj, now=NOW, get_bytes=lambda u: a, manager_of=_by_name)
    old = tp.load_index(tmp_path)["teams"]["Marcus"]
    blk = tp.fetch(tmp_path, ["Marcus"], tj, now=NOW + timedelta(days=1), get_bytes=lambda u: b, manager_of=_by_name)
    new = tp.load_index(tmp_path)["teams"]["Marcus"]
    assert blk["teams"]["Marcus"]["changed"] and new["sha"] != old["sha"]
    assert not (tmp_path / tp.DIR / old["file"]).exists() and (tmp_path / tp.DIR / new["file"]).exists()
    uris, notes = tp.data_uris(tmp_path, ["Marcus"])
    assert uris["Marcus"] == "data:image/jpeg;base64," + base64.b64encode(
        (tmp_path / tp.DIR / new["file"]).read_bytes()).decode() and notes == []


def test_a_failure_is_recorded_and_falls_back_last_good_then_monogram(tmp_path):
    tj = _teams_json({"Marcus": "https://x/a.png", "Tyler": "https://x/b.png"})

    def broken(u):
        if u.endswith("b.png"):
            raise OSError("connection reset")
        return b"<html>not an image</html>"
    blk = tp.fetch(tmp_path, ["Marcus", "Tyler"], tj, now=NOW, get_bytes=broken, manager_of=_by_name)
    assert set(blk["failures"]) == {"Marcus", "Tyler"} and "PictureError" in blk["failures"]["Marcus"]
    assert tp.data_uris(tmp_path, ["Marcus", "Tyler"]) == ({}, [])     # no picture: the monograms
    good = _img((1, 2, 3))
    tp.fetch(tmp_path, ["Marcus", "Tyler"], tj, now=NOW, get_bytes=lambda u: good, manager_of=_by_name)
    blk = tp.fetch(tmp_path, ["Marcus", "Tyler"], tj, now=NOW, get_bytes=broken, manager_of=_by_name)
    assert set(blk["failures"]) == {"Marcus", "Tyler"} and set(blk["kept"]) == {"Marcus", "Tyler"}
    assert set(tp.data_uris(tmp_path, ["Marcus", "Tyler"])[0]) == {"Marcus", "Tyler"}   # last good kept
    # Yahoo lists none now: the stored one goes, the monogram shows
    tp.fetch(tmp_path, ["Marcus", "Tyler"], _teams_json({"Marcus": None, "Tyler": "https://x/b.png"}), now=NOW,
             get_bytes=lambda u: good, manager_of=_by_name)
    assert set(tp.data_uris(tmp_path, ["Marcus", "Tyler"])[0]) == {"Tyler"}
    # a file that does not match its hash is left out, not shown broken
    v = tp.load_index(tmp_path)["teams"]["Tyler"]
    (tmp_path / tp.DIR / v["file"]).write_bytes(b"tampered")
    uris, notes = tp.data_uris(tmp_path, ["Tyler"])
    assert uris == {} and "does not match" in notes[0]


def _pics(tmp_path):
    good = {m: _img(c) for m, c in zip(MGRS, [(200, 0, 0), (0, 200, 0), (0, 0, 200), (90, 90, 90)])}
    tp.fetch(tmp_path, MGRS, _teams_json({m: f"https://x/{m}.png" for m in MGRS}), now=NOW,
             get_bytes=lambda u: good[u.rsplit("/", 1)[1][:-4]], manager_of=_by_name)
    return tp.data_uris(tmp_path, MGRS)[0]


def test_teammark_draws_each_picture_once_and_the_monogram_stays_under_it(tmp_path):
    pics = _pics(tmp_path)
    h = page.render(view.build(synth_payload(), mode="preview", now=GEN + timedelta(hours=2), pictures=pics))
    for m, uri in pics.items():
        assert h.count(uri.split(",", 1)[1]) == 1                       # once, in the pictures style
        assert f'.v2-pic-{SLOTS[m]}::after' in h
    marks = re.findall(r'<span class="lh-mono ([^"]*)"[^>]*>([^<]*)</span>', h)
    assert marks and all("v2-pic" in c and txt for c, txt in marks)    # the monogram's letters stay
    plain = page.render(view.build(synth_payload(), mode="preview", now=GEN + timedelta(hours=2)))
    assert "v2-pic-" not in plain.split("</style>", 2)[-1] and 'id="v2-pics"' not in plain


def test_no_picture_reaches_a_plaintext_published_file(tmp_path):
    pics = _pics(tmp_path)
    terms = TERMS + tp.scan_terms(tmp_path)
    assert len(terms) == len(TERMS) + 4
    e = _archive(tmp_path)
    p = synth_payload()
    p["v2"]["issue"]["file"] = e["enc"]
    out = tmp_path / "_to_delete" / "4c3" / "publish"
    rep = v2pub.build(tmp_path, p, PASS, salt=b"\x02" * 16, out_dir=out, iterations=1000, terms=terms, now=GEN)
    from modules import hub_publish
    assert hub_publish.scan_dir(out, terms)["hits"] == {}
    inner = v2pub.open_inner(PASS, json.loads(re.search(r'id="hub-bundle">(.*?)</script>',
                                                       (out / "index.html").read_text(encoding="utf-8"), re.S).group(1)))
    assert all(uri.split(",", 1)[1] in inner["page"] for uri in pics.values())   # inside: encrypted only
    assert hub_publish.hits(inner["page"].encode(), tp.scan_terms(tmp_path))     # the negative control
    assert rep["served_bytes"] <= budget_bytes()


def test_the_nightly_step_is_soft(tmp_path, monkeypatch):
    from modules import nightly
    good = _img((5, 5, 5))
    monkeypatch.setattr(tp, "http_get", lambda u, timeout=20.0: good)
    monkeypatch.setattr("modules.data_loader.manager_for_team", _by_name)
    run = SimpleNamespace(base=tmp_path, now=NOW, ctx={},
                          _yahoo_teams=lambda: _teams_json({m: f"https://x/{m}.png" for m in MGRS}))
    import modules.data_loader as dl
    monkeypatch.setattr(dl, "MANAGERS", MGRS)
    out = nightly.Run.step_team_pictures(run)
    assert out.startswith("team pictures: 4 of 4 stored") and run.ctx["team_pictures"]["error"] is None
    assert "team_pictures_lines" not in run.ctx

    def down():
        raise RuntimeError("Yahoo auth failed")
    run = SimpleNamespace(base=tmp_path, now=NOW, ctx={}, _yahoo_teams=down)
    out = nightly.Run.step_team_pictures(run)
    assert "FAILED" in out and run.ctx["team_pictures"]["error"].startswith("RuntimeError")
    assert run.ctx["team_pictures_lines"][0].startswith("TEAM PICTURES FAILED")
    assert set(tp.data_uris(tmp_path, MGRS)[0]) == set(MGRS)           # the last good pictures stand


def test_the_state_manifest_holds_the_pictures_and_git_ignores_them():
    from modules import state_manifest
    man = state_manifest.load(ROOT)
    assert man.contains("output/team_pictures/index.json") and man.contains("output/team_pictures/abc.jpg")
    assert "output/team_pictures" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


# =============================================================================
# D. the live hub's advice card: only the activation's numbers line
# =============================================================================

def test_the_live_card_gains_only_the_activation_numbers_line():
    from test_advice_live import _page, _view
    rows = [{"manager": m, "team": TEAMS[m]} for m in MGRS]
    new = MF.advice_latest()
    old = MF.advice_latest(pre_4c3=True)
    for f in (new, old):                     # the same plan line on both, so only the activation differs
        f["managers"]["Marcus"]["plan_total"]["text"] = "Plan: x"
    vn, vo = al.hub_view(new, rows), al.hub_view(old, rows)
    cn, co = vn["cards"][0], vo["cards"][0]
    assert {k for k in set(cn) | set(co) if cn.get(k) != co.get(k)} == {"step_numbers"}
    assert "step_numbers" not in co and cn["step_numbers"] == new["managers"]["Marcus"]["activation"]["texts"]["numbers"]
    a, b = _view(_page(vo)[1]), _view(_page(vn)[1])
    diff = [x for x in b.split("<div") if x not in a.split("<div")]
    assert len(diff) == 1 and diff[0].startswith(' class="ad-n">') and "+6.1%" in diff[0]
    assert b.index("Marcus Hurt is back") < b.index(diff[0]) < b.index('<div class="ad-m">')


# =============================================================================
# E. real state (slow)
# =============================================================================

def _have_state() -> bool:
    return (ROOT / "output" / "hub_state.json").is_file() and (ROOT / "output" / "advice_latest.json").is_file() \
        and (ROOT / "config" / "ROSTERS.json").is_file()


@pytest.mark.slow
@pytest.mark.skipif(not _have_state(), reason="needs the league's state (python scripts\\state.py pull)")
def test_real_market_in_every_segment_the_preview_and_publish(tmp_path):
    """Today's state, unstubbed: the hub build's Market, the v2 preview's
    every segment, and publish mode to a temp folder (a throwaway passphrase
    and a fresh salt) within the budget and clean of plaintext."""
    import os
    import league_state
    from modules import hub_state, hub_publish
    league_state.skip_if_actuals_behind()          # H51: the real build reads actuals through yesterday
    po = {}
    p = hub_state.build(ROOT, allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po)
    assert p["v2_error"] is None, p["v2_error"]
    from modules.hub_v2 import data as v2data
    v2data.attach_players(p, po)            # 4c2: the Players rows live in their own file (4a3 review fix)
    mk = p["v2"]["market"]
    assert mk["available"]["rows"] and [s[0] for s in mk["segs"]][:2] == ["available", "stash"]
    for r in mk["available"]["rows"]:
        for c in r["games"]:
            if c["tip"]:
                assert len(c["tip"]["b"].split(" \u00b7 ")) == int(c["n"]) or c["n"] == "0"
    h = page.render(view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]),
                               pictures=tp.data_uris(ROOT, p["v2"]["team_order"])[0]))
    for key, _lab in mk["segs"]:
        assert f'data-pane-of="{key}"' in h
    terms = hub_publish.scan_terms(ROOT)
    out = tmp_path / "_to_delete" / "4c3" / "publish"
    rep = v2pub.build(ROOT, p, "throwaway " + os.urandom(8).hex(), salt=os.urandom(16), out_dir=out,
                      iterations=1000, terms=terms)
    assert rep["served_bytes"] <= budget_bytes()
    assert hub_publish.scan_dir(out, terms)["hits"] == {}


def test_a_one_row_card_still_shows_its_title_odds_change():
    """Nick, 11-19: "Even though its only one move, it should still show title
    odds change". A one-row card (no plan line) gets a title line of its own,
    the engine's string; none with the switch off; a two-row card keeps it on
    its plan line only."""
    p = synth_payload()
    tyler = next(c for c in p["v2"]["market"]["advice"]["cards"] if c["m"] == "Tyler")
    assert len(tyler["rows"]) == 1 and tyler["plan"] is None
    assert tyler["title"] and tyler["title"].startswith("title odds ")
    assert tyler["title"] in strings(p["v2"]["market"]["advice"])
    tc = _card(render(p), "Tyler")
    assert 'class="adv-plan adv-title"' in tc and tyler["title"].replace("−", "&minus;") in tc \
        or tyler["title"] in visible_text(tc)
    off = render(_payload(advice=MF.advice_latest(show_title=False), show_title=False))
    assert "adv-title" not in _card(off, "Tyler") and "title odds" not in visible_text(_card(off, "Tyler"))
    marcus = next(c for c in p["v2"]["market"]["advice"]["cards"] if c["m"] == "Marcus")
    assert marcus["plan"] is not None and marcus["title"] is None
