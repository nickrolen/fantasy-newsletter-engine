"""The live line as a page (HANDOFF_HTML_SURFACE_2026-10-22).

A sportsbook page: the current score and the available bets. The page
DISPLAYS; the engine computes -- so every number on it is the payload's own,
and a payload from a retired engine is refused rather than rendered with its
retired caveats.
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from modules import calibration_log as cal
from modules import claim_check as cc
from modules import live_lines_page as page

ROOT = Path(__file__).parent.parent
NOW = datetime(2026, 10, 23, 9, 0, 0)


def _engine(base=ROOT) -> dict:
    live = cal.engine_version(base)
    return {"commit": live["commit"], "dirty": live["dirty"],
            "key": cal.engine_key({"engine_commit": live["commit"],
                                   "engine_dirty": live["dirty"]})}


def _line(**over):
    line = {
        "matchup": "Nick vs Benton", "manager_a": "Nick", "manager_b": "Benton",
        "team_name_a": "Luka my Balls", "team_name_b": "Kevin Quran't",
        "spread_a": -95.5, "spread_b": 95.5, "over_under": 2900,
        "win_prob_a": 70.64, "win_prob_b": 29.36,
        "moneyline_a": -240, "moneyline_b": 240,
        "banked_a": 912.4, "banked_b": 743.1,
        "remaining_mean_a": 585.8, "remaining_mean_b": 659.5,
        "projected_final_a": 1498.2, "projected_final_b": 1402.6,
        "display_a": "912 → 1498", "display_b": "743 → 1403",
        "std_dev_a": 122.07, "std_dev_b": 126.86,
    }
    line.update(over)
    return line


def _payload(**over):
    payload = {
        "week": 1, "as_of": "2026-10-23", "generated_at": "2026-10-23T06:40:11",
        "engine": _engine(), "seed": 20262027, "num_simulations": 5000,
        "state_hash": "3f91c0de2b7714aa",
        "completed_dates": ["2026-10-20", "2026-10-21", "2026-10-22"],
        "remaining_dates": ["2026-10-23", "2026-10-24", "2026-10-25"],
        "assumptions": ["ASSUMED: every live tag existed since 2026-10-20."],
        "tag_events": [
            {"player": "Kon Knueppel", "tag": "O", "event": "changed Q -> O: re-anchored",
             "anchor": "2026-10-22", "basis": "suppressed: an INJURY_OVERRIDES entry governs"},
            {"player": "Bam Adebayo", "tag": "Q", "event": "cleared", "anchor": None},
        ],
        "caveats": ["Team-level noise on the remainder is scaled by sqrt(share left)."],
        "lines": [_line()],
    }
    payload.update(over)
    return payload


def _text(html_str: str) -> str:
    """The page as text, cells separated -- what a reader sees."""
    return re.sub(r"<[^>]+>", " | ", html_str)


def _render(**over):
    return page.render(_payload(**over), base_path=ROOT, now=NOW)


# =============================================================================
# 1 -- the page displays, the engine computes
# =============================================================================

def test_every_number_is_the_payloads_own():
    line = _line()
    text = _text(_render())
    assert line["display_a"] in text and line["display_b"] in text   # as given
    for value in ("-95.5", "+95.5", "-240", "+240", "70.64", "29.36", "2900"):
        assert value in text, value
    # nothing is rounded or recomputed at render time
    assert "1498.2" not in text and "585.8" not in text    # only the decomposition shows
    assert "912 → 1498" in text


def test_the_renderer_does_no_arithmetic():
    """A grep-level guard: the module formats and escapes, it does not compute.
    The only arithmetic it may do is the week clock's percentage and the age."""
    src = (ROOT / "modules" / "live_lines_page.py").read_text(encoding="utf-8")
    body = src.split("def render(")[1]
    for forbidden in ("projected_final_a", "remaining_mean_a", "banked_a", "std_dev_a"):
        assert forbidden not in body, forbidden        # the page never re-derives the line
    assert "round(float" not in src


@pytest.mark.parametrize("field", ["week", "as_of", "lines"])
def test_a_payload_missing_a_field_raises(field):
    payload = _payload()
    del payload[field]
    with pytest.raises(page.LiveLinesPayloadError, match=field):
        page.render(payload, base_path=ROOT, now=NOW)


def test_the_favourite_is_the_side_with_the_negative_spread():
    html_str = _render()
    rows = re.findall(r'<tr class="(fav|)"><td class="team">([^<]+)', html_str)
    assert rows[0] == ("fav", "Luka my Balls")          # -95.5
    flipped = _render(lines=[_line(spread_a=95.5, spread_b=-95.5)])
    rows = re.findall(r'<tr class="(fav|)"><td class="team">([^<]+)', flipped)
    assert rows[0][0] == "" and rows[1][0] == "fav"


# =============================================================================
# 2 -- the voice rule, through the one implementation
# =============================================================================

def test_banked_and_expected_remaining_never_appear_as_labels():
    assert cc.score_label_findings(_text(_render())) == []
    # the rule exists where it is written down
    voice = (ROOT / "templates" / "VOICE.md").read_text(encoding="utf-8")
    assert "never appear as labels" in voice and "912 -> 1498" in voice
    # and the newsletter is held to it by the same function
    draft_check = (ROOT / "scripts" / "check_draft.py").read_text(encoding="utf-8")
    assert "cc.score_label_findings(draft_text, vocab)" in draft_check
    # the check bites
    assert [f.token for f in cc.score_label_findings("Banked: 912 | Remaining: 586")] == ["Banked"]
    assert cc.score_label_findings("912 -> 1498") == []


def test_a_payload_string_that_names_the_machinery_is_caught_not_hidden():
    """The page does not launder a bad string: if an upstream assumption ever
    reads as a label, the check sees it on the page."""
    bad = _render(assumptions=["Banked: 912 for Nick"])
    assert [f.token for f in cc.score_label_findings(_text(bad))] == ["Banked"]


# =============================================================================
# 3 -- no lore tag reaches a rendered page (VOICE.md rule 21)
# =============================================================================

def test_no_lore_tag_reaches_the_page():
    html_str = _render()
    assert "<!--lore:" not in html_str and "lore:" not in html_str
    # even when the payload carries one, in any field the page shows
    seeded = _render(
        assumptions=["a tag from nowhere <!--lore:myth-garrett-title-drought-->"],
        caveats=["<!-- lore:loyalty-nick-joelembiid --> another"],
        tag_events=[{"player": "X <!--lore:x-->", "tag": "O", "event": "cleared",
                     "anchor": None}])
    assert "lore:" not in seeded and "<!--" not in seeded
    assert "a tag from nowhere" in _text(seeded)        # the sentence survives


# =============================================================================
# 4 -- a payload from another engine
# =============================================================================

def test_a_payload_from_another_engine_is_refused():
    with pytest.raises(page.EngineMismatch, match="no longer exists"):
        page.render(_payload(engine={"commit": "0000000", "dirty": False}),
                    base_path=ROOT, now=NOW)


def test_a_payload_that_does_not_say_its_engine_is_refused():
    payload = _payload()
    del payload["engine"]
    with pytest.raises(page.EngineMismatch, match="does not say which engine"):
        page.render(payload, base_path=ROOT, now=NOW)
    # which is exactly the week-1 file written before the engine was recorded
    on_disk = ROOT / "output" / "live_lines_week1.json"
    if on_disk.is_file():
        old = page.load_payload(on_disk)
        if "engine" not in old:
            with pytest.raises(page.EngineMismatch):
                page.render(old, base_path=ROOT, now=NOW)


def test_the_override_renders_it_with_the_mismatch_as_the_loudest_element():
    html_str = page.render(_payload(engine={"commit": "0000000", "dirty": False}),
                           base_path=ROOT, now=NOW, allow_engine_mismatch=True)
    assert "Do not price anything off this page" in html_str
    assert html_str.index("mismatch") < html_str.index("<section")   # before the lines
    assert "0000000" in html_str


def test_the_comparison_uses_calibration_logs_engine_key():
    """One definition, two consumers -- not a second comparison."""
    src = (ROOT / "modules" / "live_lines_page.py").read_text(encoding="utf-8")
    assert "cal.engine_key(" in src and "cal.engine_version(" in src
    assert "-dirty" not in src.split("CSS =")[0] + src.split('"""')[-1]
    payload = _payload(engine={"commit": "abc1234", "dirty": True})
    assert page.payload_engine_key(payload) == cal.engine_key(
        {"engine_commit": "abc1234", "engine_dirty": True}) == "abc1234-dirty"
    assert page.current_engine_key(ROOT) == cal.engine_key(
        {"engine_commit": cal.engine_version(ROOT)["commit"],
         "engine_dirty": cal.engine_version(ROOT)["dirty"]})


def test_refresh_lines_writes_the_same_engine_field_e1_logs():
    src = (ROOT / "scripts" / "refresh_lines.py").read_text(encoding="utf-8")
    assert "_cal.engine_version(base)" in src and "_cal.engine_key(" in src
    assert '"engine": {"commit"' in src


# =============================================================================
# 5 -- freshness, unmissably
# =============================================================================

def test_as_of_and_generated_at_appear():
    text = _text(_render())
    assert "as of 2026-10-23" in text and "2026-10-23T06:40:11" in text


def test_the_age_is_in_words_and_an_old_page_says_so():
    assert "2 h old" in _text(_render())               # 06:40 against NOW 09:00
    old = page.render(_payload(generated_at="2026-10-20T06:40:11"), base_path=ROOT, now=NOW)
    assert "3 days old" in _text(old) and 'class="age stale"' in old
    fresh = page.render(_payload(generated_at="2026-10-23T08:50:00"), base_path=ROOT, now=NOW)
    assert "10 min old" in _text(fresh) and 'class="age stale"' not in fresh


def test_the_week_clock_shows_how_much_is_played():
    assert "3 of 6 game days played" in _text(_render())
    none_yet = _render(completed_dates=[], remaining_dates=["2026-10-20"] * 6)
    assert "0 of 6 game days played" in _text(none_yet)


# =============================================================================
# 6 -- tag events, including the cleared case
# =============================================================================

def test_tag_events_render_including_cleared():
    html_str = _render()
    text = _text(html_str)
    assert "Kon Knueppel" in text and "changed Q -&gt; O: re-anchored" in text
    assert "anchored 2026-10-22" in text
    assert "an INJURY_OVERRIDES entry governs" in text
    assert "Bam Adebayo" in text and "cleared" in text
    assert 'class="ev cleared"' in html_str            # marked, not listed flat
    assert "Injury tags this week" in text


def test_assumptions_and_caveats_render_as_the_payload_states_them():
    text = _text(_render())
    assert "ASSUMED: every live tag existed since 2026-10-20." in text
    assert "Team-level noise on the remainder" in text
    bare = _render(assumptions=[], caveats=[], tag_events=[])
    assert "Injury tags this week" not in _text(bare)   # no empty headings


# =============================================================================
# one static file, no server, no build step
# =============================================================================

def test_the_page_is_self_contained():
    html_str = _render()
    assert "<script" not in html_str                   # no JavaScript at all
    for remote in ("http://", "https://", "//fonts.", "src=", "<link"):
        assert remote not in html_str, remote
    assert html_str.startswith("<!DOCTYPE html>") and html_str.rstrip().endswith("</html>")
    assert "<style>" in html_str                       # inline, so it opens from disk


def test_the_script_writes_one_file_and_refuses_a_retired_payload(tmp_path):
    payload = _payload()
    src = tmp_path / "p.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    out = tmp_path / "page.html"
    r = subprocess.run([sys.executable, "scripts/render_live_lines.py",
                        "--payload", str(src), "--out", str(out),
                        "--base-path", str(ROOT)],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert out.is_file() and list(tmp_path.glob("*.html")) == [out]
    assert "1 matchup(s)" in r.stdout

    retired = tmp_path / "old.json"
    retired.write_text(json.dumps(_payload(engine={"commit": "0000000", "dirty": False})),
                       encoding="utf-8")
    r = subprocess.run([sys.executable, "scripts/render_live_lines.py",
                        "--payload", str(retired), "--out", str(tmp_path / "x.html"),
                        "--base-path", str(ROOT)],
                       cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "REFUSED" in r.stdout
    assert not (tmp_path / "x.html").exists()
