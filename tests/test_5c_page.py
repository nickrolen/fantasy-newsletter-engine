"""5c, the page (claude/HANDOFF_5C_PHONE_BUGS_2026-11-20.md section 1-2):

  - "Forget this phone" asks first, in the page (no browser confirm()):
    Forget forgets, Cancel and Escape forget nothing (jsdom, published);
  - an InfoTip popover is placed by the page inside the screen, fixed (no
    scrolling table clips it), and kept there on scroll and resize;
  - a tap that reached a .v2-tap through its 44-point area, on a point where
    another tap target is drawn, goes to the drawn one;
  - the chart tooltip comes back inside the screen when an end label pushed it
    out (360 px);
  - THE SWEEP (scripts/hub_tap_sweep.py): the synthetic league, published,
    opened in headless Chrome at 390, 360 and 1280 px, every screen, segment,
    chip and lazy screen; skips where playwright or Chrome is missing (the
    builder's container has both; see the script's docstring).
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

import league_state                                    # noqa: F401
import test_hub_v2 as T2
from test_hub_switch import _shell, _v2_world, PASS, SALT, GEN
from modules.hub_v2 import page, publish as v2pub, publish_check as pc

ROOT = T2.ROOT


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    base = tmp_path_factory.mktemp("v2pub5c")
    p = _v2_world(base, keep_cards=True)
    out = base / "_to_delete" / "j" / "publish"
    v2pub.build(base, p, PASS, salt=SALT, out_dir=out, iterations=1000, terms=T2.TERMS, now=GEN, pictures=[])
    return out


def _page_html(out):
    return pc.open_page((out / "index.html").read_text(encoding="utf-8"), PASS)["page"]


# ---- Forget asks first

def test_the_forget_question_is_in_the_published_page_only(published):
    pub = _page_html(published)
    assert pub.count('id="forget-ask"') == 1 and page.FORGET_ASK in pub
    assert "Forget this phone? You'll need the passphrase again." in pub.replace("&#x27;", "'")
    assert 'id="forget-yes"' in pub and 'id="forget-no"' in pub
    assert 'id="forget-ask"' not in T2.render()                            # preview: no Forget button at all
    js = page.script()
    assert "confirm(" not in js                                            # never the browser's dialog
    # only the question's own Forget button forgets
    assert js.count("window.HUB.forget()") == 1
    assert "if(e.target.closest('#forget-yes')){askForget(false);if(window.HUB){window.HUB.forget();}return;}" in js


@pytest.mark.slow
def test_in_jsdom_forget_asks_first_and_only_forget_forgets(published):
    r = _shell(published, {"forget": True})
    assert r["mounted"] and r["errors"] == [], r
    f = r["forget"]
    assert f["stored_before"] and f["asked"] and f["calls_on_ask"] == []
    assert f["question"] == "Forget this phone? You'll need the passphrase again."
    assert f["buttons"] == ["Cancel", "Forget"] and f["focus"] == "forget-no"     # Cancel has the focus
    assert f["after_cancel"] == [False, []] and f["after_escape"] == [False, []]
    assert f["after_yes"] == [False, ["forget"]]                           # once, and no confirm()
    assert f["stored_after_stub"] and not f["stored_after_real"]           # the real one clears the key


# ---- the InfoTip popover, the tap rule, the chart tooltip (layout code: pinned; the sweep measures it)

def test_the_popover_is_placed_by_the_page_inside_the_screen():
    js = page.script()
    assert "function placePop(btn,pop)" in js and "pop.style.position='fixed'" in js
    assert "if(left<pad){left=pad;}" in js and "if(left+w>vw-pad){left=vw-pad-w;}" in js
    assert "if(!open){placePop(t,pp);}" in js                               # placed when it opens
    assert "hideTip();placePops();},true);" in js                           # and kept there on scroll
    assert ".lh-info__pop{max-width:calc(100vw - 2 * var(--space-16))}" in page.LAYOUT_CSS


def test_a_tap_reaches_what_is_drawn():
    js = page.script()
    i = js.index("function drawnTap(t,x,y)")
    assert js.index("document.addEventListener('click',function(e){\n  if(!e.detail") < js.index("function route()")
    assert "if(inBox(t,x,y)){return null;}" in js[i:i + 400]               # a tap on the target itself: as before
    assert "e.preventDefault();e.stopImmediatePropagation();" in js        # the area's own target never runs
    assert "},true);" in js[i:i + 1400]                                     # capture: before every other listener


def test_the_chart_tooltip_comes_back_inside_from_the_right():
    js = page.script()
    assert "else if(left+w>vw-pad){left=vw-pad-w;var s2=svg.getBoundingClientRect();top=s2.bottom+pad;}" in js
    i = js.index("function placeTip(el,box){")
    assert js.index("box.style.left='0px';box.style.top='0px';", i) < js.index("w=box.offsetWidth", i)


# ---- the sweep

def _chrome():
    for c in (os.environ.get("HUB_TEST_CHROME"), shutil.which("google-chrome"), shutil.which("chromium"),
              shutil.which("chrome")):
        if c:
            return c
    return None


@pytest.mark.slow
def test_the_tap_sweep_of_the_published_synthetic_league(tmp_path):
    """About 4 minutes. Every hit is what is drawn there or its own 44-point
    area; no tap forgets or reloads; Forget asks first; every popover and chart
    tooltip inside the screen; no script error; no sideways scroll."""
    pytest.importorskip("playwright")
    chrome = _chrome()
    if chrome is None:
        pytest.skip("no Chrome here (HUB_TEST_CHROME)")
    sys.path.insert(0, str(ROOT / "scripts"))
    import hub_tap_sweep as sw
    from test_hub_v2_players import synth_cards
    base = tmp_path / "base"
    base.mkdir()
    e = T2._archive(base)
    p = T2.synth_payload()
    import hub_v2_market_fixture as MF                  # Advice goals (Part D): the picker and its parts too
    MF.add_market(p, advice=MF.advice_with_goals())
    p["v2"]["issue"]["file"] = e["enc"]
    p["newsletter"]["current"]["file"] = e["enc"]
    out = tmp_path / "publish"
    v2pub.build(base, p, T2.PASS, salt=b"\x09" * 16, out_dir=out, iterations=1000, terms=T2.TERMS, now=T2.GEN,
                pictures=[], cards=synth_cards(p))
    with sw.serve(out) as url:
        rep = sw.run(url, T2.PASS, chrome=chrome)
    bad = sw.failures(rep)
    assert not bad, "\n".join(bad[:40])
    for w, W in rep["widths"].items():
        routes = {s["state"].split(" [")[0] for s in W["states"]}
        assert {"home", "matchups", "teams", "players", "market", "league", "league/history/champions",
                "league/awards"} <= routes, routes
        assert any(r.startswith("teams/") for r in routes) and any(r.startswith("players/compare/") for r in routes)
