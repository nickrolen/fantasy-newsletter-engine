"""
Claim check (prose layer, item 5).

The real-data tests run on the 2025-26 archive: the drafts that were
published and the stats reports they were written from. Only weeks 17, 19,
20 and 21 are usable as "what the writer was given": the week 16 and 18
reports were regenerated after the newsletter went out, so most of their
numbers no longer match what the writer saw.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from modules import claim_check as cc  # noqa: E402
import check_draft  # noqa: E402

ARCHIVE = ROOT / "archive" / "2025-26"
CONFIG = json.loads((ROOT / "config" / "league_config.json")
                    .read_text(encoding="utf-8"))


def _draft(week):
    return (ARCHIVE / "assets" / f"WEEK{week}_DRAFT.md").read_text(
        encoding="utf-8")


@pytest.fixture(scope="module")
def prepared():
    out = {}
    for w in (17, 19, 20):
        out[w] = check_draft.prepare(w, [ARCHIVE / "output"], CONFIG, [],
                                     bases=[ARCHIVE], include_recap=False)
    return out


def _check(prepared, week, text):
    pool, vocab, lore, _ = prepared[week]
    return cc.check(text, pool, vocab, lore)


# ------------------------------------------------------------ real drafts

def test_clean_published_draft_stays_clean(prepared):
    """Week 17 was published, its report is the one it was written from,
    and every claim in it checks out. Zero findings is the bar."""
    assert _check(prepared, 17, _draft(17)) == []


def test_false_positive_budget_week20(prepared):
    """Week 20 has two known false positives (a sum across paragraphs; a
    nickname, "NAW", the vocabulary doesn't know). More means a
    regression."""
    found = _check(prepared, 20, _draft(20))
    assert len([f for f in found if f.kind != "approximate_number"]) <= 2
    # and one real template-rule-2 violation: "by more than 27%"
    assert [f.token for f in found if f.kind == "approximate_number"] == \
        ["27%"]


def test_catches_the_errors_that_shipped_in_week19(prepared):
    """Two arithmetic errors that went out in the published week 19
    newsletter: Garrett's guards beat Benton's by 324.00 (854.15 - 530.15),
    not 323.00; Garrett's last-3 average was 1767.0, not 1684.40."""
    found = {(f.kind, f.token) for f in _check(prepared, 19, _draft(19))}
    assert ("unsupported_number", "323.00") in found
    assert ("unsupported_number", "1684.40") in found


def test_catches_planted_slips(prepared):
    text = _draft(20)
    assert "1633.55" in text
    for good, bad in [("1633.55", "1663.55"), ("304.35", "304.53"),
                      ("76.09", "76.90")]:
        planted = text.replace(good, bad, 1)
        lines = {f.line for f in _check(prepared, 20, planted)
                 if f.kind == "unsupported_number" and f.token == bad}
        assert lines, f"planted {good}->{bad} not caught"


def test_table_row_numbers_belong_to_the_row_player(prepared):
    """A row's fantasy-team column must not license every number that
    manager owns: move one player's FPPG into another's row."""
    text = _draft(20)
    rows = [l for l in text.splitlines() if l.startswith("| ") and
            "Nickeil Alexander-Walker" in l]
    assert rows
    row = rows[0]
    planted = text.replace(row, row.replace("33.26", "35.06"), 1)
    found = [f for f in _check(prepared, 20, planted)
             if f.token == "35.06"]
    assert found


# ------------------------------------------------------------ unit level

class _V(cc.Vocabulary):
    def __init__(self):
        super().__init__(["Nick", "Hayden", "Benton", "Garrett"],
                         {"Nick": "Luka my Balls", "Garrett": "Saboner"},
                         {}, ["Luka Doncic", "Victor Wembanyama"])


def _pool(objs=(), mds=(), lore=()):
    v = _V()
    return cc.build_pool(v, [("r", o) for o in objs],
                         [("m", m) for m in mds], lore), v


def test_extract_numbers_kinds():
    ns = cc.extract_numbers(
        "Nick (15-4) beat Garrett 1,913.65 to 1440.8 on March 6 in "
        "2025-26, nearly 60 points, his 6th title since 2019; three games")
    kinds = {(n.kind, n.raw) for n in ns}
    assert ("record", "15-4") in kinds
    assert ("num", "1,913.65") in kinds
    assert ("date", "March 6") in kinds
    assert ("season", "2025-26") in kinds
    assert ("ordinal", "6th") in kinds
    assert ("year", "2019") in kinds
    assert ("num", "three") in kinds
    assert [n for n in ns if n.raw == "60"][0].approx


def test_week_labels_are_not_claims():
    assert cc.extract_numbers("Weeks 16-19 and Week 20") == []


def test_small_number_needs_an_owner():
    pool, v = _pool([{"Nick": {"games_lost": 4}, "Hayden": {"games_lost": 7}}])
    assert cc.check("### **1. X**\n\nNick lost 4 games to injury.", pool, v) == []
    found = cc.check("### **1. X**\n\nHayden lost 4 games to injury.", pool, v)
    assert [f.token for f in found] == ["4"]


def test_margin_is_derived_not_required_in_sources():
    pool, v = _pool([{"manager_a": "Nick", "manager_b": "Garrett",
                      "score_a": 1913.65, "score_b": 1440.80}])
    ok = "### **1. X**\n\nNick 1913.65, Garrett 1440.80: a 472.85-point win."
    assert cc.check(ok, pool, v) == []
    bad = ok.replace("472.85", "427.85")
    assert [f.token for f in cc.check(bad, pool, v)] == ["427.85"]


def test_verdicts_are_the_voice_rankings_need_a_source():
    pool, v = _pool([{"weekly": [{"manager": m, "fp": x} for m, x in
                                 [("Nick", 1900.0), ("Hayden", 1500.0),
                                  ("Benton", 1700.0), ("Garrett", 1600.0)]]}])
    assert cc.check("### **1. X**\n\nThe cleanest, cruelest week Nick has "
                    "had. He needs at least a split.", pool, v) == []
    assert cc.check("### **1. X**\n\nNick's 1900.0 was the league's "
                    "highest this week.", pool, v) == []
    found = cc.check("### **1. X**\n\nGarrett's 1600.0 was the league's "
                     "highest this week.", pool, v)
    assert [f.kind for f in found] == ["unsupported_superlative"]


def test_history_claim_needs_lore():
    pool, v = _pool([{"Garrett": {"wins": 9}}])
    text = "### **1. X**\n\nGarrett fades in December, as he always does."
    assert [f.kind for f in cc.check(text, pool, v)] == ["unsourced_history"]


def test_lore_is_the_bridge():
    entry = {"id": "garrett-december", "status": "approved",
             "text": "Garrett is 9-23 in December matchups since 2017-18.",
             "entities": ["Garrett"], "values": [9, 23]}
    pool, v = _pool([{"Garrett": {"wins": 9}}], lore=[entry])
    lore = {entry["id"]: entry}
    text = ("### **1. X**\n\nGarrett fades in December, as he always does: "
            "9-23 since 2017-18. <!--lore:garrett-december-->")
    assert cc.check(text, pool, v, lore) == []


@pytest.mark.parametrize("status,stale", [("proposed", False),
                                          ("rejected", False),
                                          ("approved", True)])
def test_lore_tag_must_resolve_to_approved_current_entry(status, stale):
    entry = {"id": "x", "status": status, "stale": stale,
             "text": "Garrett always fades.", "entities": ["Garrett"]}
    pool, v = _pool([], lore=[entry])
    found = cc.check("### **1. X**\n\nGarrett always fades. <!--lore:x-->",
                     pool, v, {"x": entry})
    assert "bad_lore_ref" in {f.kind for f in found}
    found = cc.check("### **1. X**\n\nGarrett always fades. <!--lore:nope-->",
                     pool, v, {})
    assert "bad_lore_ref" in {f.kind for f in found}


def test_around_the_nba_is_left_to_step_8():
    pool, v = _pool([])
    assert cc.check("### **9. Around the NBA**\n\nCurry scored 61 again.",
                    pool, v) == []


# ------------------------------------------------------------ the script

def test_script_exit_codes(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "config" / "league_config.json").write_text(
        json.dumps(CONFIG), encoding="utf-8")
    draft = tmp_path / "assets" / "WEEK3_DRAFT.md"
    draft.write_text("### **1. X**\n\nNick scored 1913.65.\n",
                     encoding="utf-8")
    assert check_draft.main(["--week", "3", "--base", str(tmp_path)]) == 2
    (tmp_path / "output" / "stats_report_week3.json").write_text(
        json.dumps({"team_stats": [{"manager": "Nick", "weekly_fp": 1913.65}]}),
        encoding="utf-8")
    assert check_draft.main(["--week", "3", "--base", str(tmp_path)]) == 0
    draft.write_text("### **1. X**\n\nNick scored 1931.65.\n",
                     encoding="utf-8")
    assert check_draft.main(["--week", "3", "--base", str(tmp_path)]) == 1
    rep = (tmp_path / "output" / "claim_check_week3.md").read_text(
        encoding="utf-8")
    assert "1931.65" in rep


def test_html_generator_strips_lore_tags_and_reports_status(tmp_path):
    import newsletter_html_generator as gen
    md = ("## **CHS Alumni Fantasy Basketball League - Week 3 Newsletter**\n\n"
          "### **1. Matchup Summaries**\n\nGarrett always fades. "
          "<!--lore:garrett-december-->\n")
    out = tmp_path / "o.html"
    gen.build_newsletter_html(md, str(out))
    html = out.read_text(encoding="utf-8")
    assert "lore:" not in html and "Garrett always fades." in html
    (tmp_path / "assets").mkdir()
    (tmp_path / "output").mkdir()
    d = tmp_path / "assets" / "WEEK3_DRAFT.md"
    d.write_text(md, encoding="utf-8")
    assert "NOT RUN" in gen.claim_check_status(str(d))


def test_approximations_break_rule_2_but_prepositions_dont():
    pool, v = _pool([{"Nick": {"margin": 58.35, "games": 4}}])
    assert [f.kind for f in cc.check(
        "### **1. X**\n\nNick won by nearly 60 points.", pool, v)] == \
        ["approximate_number"]
    assert cc.check("### **1. X**\n\nNick won by 58.35 over 4 games.",
                    pool, v) == []


def test_no_lore_reference_can_reach_published_html(tmp_path):
    """Nick, 10-08: the repo is public and the lore file is not; a tag in
    the page source gives the entry away. Malformed tags too."""
    import newsletter_html_generator as gen
    md = ("## **CHS Alumni Fantasy Basketball League - Week 3 Newsletter**\n\n"
          "### **1. Matchup Summaries**\n\nGarrett won. "
          "<!--lore:myth-garrett-title-drought--> <!-- lore : x --> "
          "<!--LORE:y-->\n")
    out = tmp_path / "o.html"
    gen.build_newsletter_html(md, str(out))
    assert "lore" not in out.read_text(encoding="utf-8").lower()


def test_archived_drafts_lose_their_lore_tags():
    import start_new_season as sns
    from pathlib import Path as P
    assert sns._is_draft(P("assets/WEEK3_DRAFT.md"))
    assert sns._strip_lore_tags("a <!--lore:x--> b") == "a  b"
