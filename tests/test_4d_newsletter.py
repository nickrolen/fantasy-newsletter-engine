"""4d: the newsletter slimmed to the story (claude/HANDOFF_4D_NEWSLETTER_
TEMPLATE_2026-11-25.md; NEWSLETTER_REVIEW 2026-11-25, all five decisions).

The issue is the story of the week, published Monday night; the hub carries
the live numbers. Pinned here:
  - the formatted report: the cut blocks are gone, AWARD MOVES is in;
  - AWARD MOVES (modules/awards.award_moves): a leader change is flagged, a
    quiet week prints the none line, the thresholds are required;
  - the claim check: a dollar line without its pot and window is a finding
    in any section; the Betting Lines are the report's line;
  - the page: no Money block, no Keeper Watch panel or cards, the "On the
    hub:" line is a pointer that 48a's parser does not read, the cut blocks
    refuse the build;
  - the template, the prompts and the verification checklist follow.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from modules import awards as aw                                   # noqa: E402
from modules import claim_check as cc                              # noqa: E402
from modules import newsletter_shape as shape                      # noqa: E402
from modules import prepare_prompts as pp                          # noqa: E402
from league_state import needs_state                               # noqa: E402

MANAGERS = ["Nick", "Hayden", "Benton", "Garrett"]
TEAMS = {"Nick": "Luka my Balls", "Hayden": "Big Nik Energy", "Benton": "Spayed for Cade",
         "Garrett": "Blink-183"}
RULES = {"lead_change_share": 0.5, "mvp_odds_swing_points": 10.0}
TEMPLATE = (ROOT / "templates" / "newsletter_template.md").read_text(encoding="utf-8")
PROMPTS = (ROOT / "templates" / "NEWSLETTER_PROMPTS.md").read_text(encoding="utf-8")


def _fmt():
    import format_stats_report as F
    return F


# =============================================================================
# AWARD MOVES
# =============================================================================

def _week(w, tops=None, odds=None, final=False, season="2026-27"):
    """One finished week's history lines, every award (top: [(key, m, value)])."""
    out = []
    for k in aw.KEYS:
        top = [{"rank": i, "key": key, "label": key, "m": m, "value": v}
               for i, (key, m, v) in enumerate((tops or {}).get(k, []), 1)]
        ln = {"schema": 1, "season": season, "week": w, "through": f"2026-11-{w:02d}", "award": k,
              "final": final, "replacement_level": 20.0, "top": top, "eligible": len(top),
              "excluded": 0, "error": None}
        if k == "mvp":
            if odds is None:
                ln["odds"], ln["odds_why"] = None, "no MVP odds were priced"
            else:
                ln["odds"] = {"p": [{"key": key, "label": key, "m": m, "p": p} for key, m, p in odds]}
        out.append(ln)
    return out


def _moves(lines, week, rules=RULES):
    return aw.award_moves(lines, "2026-27", week, rules)


def test_a_leader_change_is_flagged_with_before_and_after():
    lines = (_week(1, {"mvp": [("Luka Doncic", "Nick", 100.0), ("Victor Wembanyama", "Garrett", 90.0)]})
             + _week(2, {"mvp": [("Victor Wembanyama", "Garrett", 210.0), ("Luka Doncic", "Nick", 200.0)]}))
    res = _moves(lines, 2)
    assert res["state"] == "moves"
    m = [x for x in res["moves"] if x["award"] == "mvp"][0]
    assert m["kind"] == "new_leader"
    assert (m["before"]["label"], m["before"]["value"], m["before"]["week"]) == ("Luka Doncic", 100.0, 1)
    assert (m["after"]["label"], m["after"]["value"], m["after"]["week"]) == ("Victor Wembanyama", 210.0, 2)
    md = aw.render_award_moves(res, RULES)
    assert md.startswith(aw.MOVES_HEAD + "WEEK 2")
    assert "**MVP: new leader.** Victor Wembanyama (Garrett) leads at 210.00 PAR after week 2" in md
    assert aw.NO_MOVE not in md


def test_a_quiet_week_prints_the_none_line_never_empty():
    lines = (_week(1, {"mvp": [("A", "Nick", 100.0), ("B", "Hayden", 90.0)]})
             + _week(2, {"mvp": [("A", "Nick", 150.0), ("B", "Hayden", 138.0)]}))     # lead 10 -> 12
    res = _moves(lines, 2)
    assert res["state"] == "none" and res["moves"] == []
    md = aw.render_award_moves(res, RULES)
    assert aw.NO_MOVE == "No award race moved this week." and aw.NO_MOVE in md
    assert "Cite no MVP odds" in md                                   # the odds weren't compared


@pytest.mark.parametrize("gap2, moved", [(15.0, True), (14.9, False), (5.0, True), (5.1, False)])
def test_the_lead_threshold_is_a_share_of_last_weeks_lead(gap2, moved):
    lines = (_week(1, {"bust": [("A", "Nick", 100.0), ("B", "Hayden", 90.0)]})          # lead 10
             + _week(2, {"bust": [("A", "Nick", 120.0 + gap2), ("B", "Hayden", 120.0)]}))
    kinds = [m["kind"] for m in _moves(lines, 2)["moves"]]
    assert bool(kinds) is moved
    if moved:
        assert kinds == ["lead_grew" if gap2 > 10 else "lead_shrank"]


def test_a_first_leader_and_the_mvp_odds():
    lines = (_week(1, {"mvp": [("A", "Nick", 100.0), ("B", "Hayden", 90.0)]},
                   odds=[("A", "Nick", 0.50), ("B", "Hayden", 0.30)])
             + _week(2, {"mvp": [("A", "Nick", 150.0), ("B", "Hayden", 141.0)],
                         "roy": [("R", "Benton", 40.0)]},
                     odds=[("A", "Nick", 0.30), ("B", "Hayden", 0.55)]))
    kinds = {(m["award"], m["kind"]) for m in _moves(lines, 2)["moves"]}
    assert kinds == {("roy", "first_leader"), ("mvp", "new_favourite"), ("mvp", "odds_swing")}
    md = aw.render_award_moves(_moves(lines, 2), RULES)
    assert "**MVP odds: a 20.0-point swing.** A (Nick) went from 50.0% after week 1 to 30.0%" in md
    assert "Cite no MVP odds" not in md


def test_a_week_not_on_file_says_so_and_after_the_races_it_says_they_ended():
    lines = _week(1) + _week(2)
    res = _moves(lines, 3)
    assert res["state"] == "missing"
    assert "**Unavailable this week:**" in aw.render_award_moves(res, RULES)
    fin = _week(14) + _week(15, final=True)
    res = _moves(fin, 16)
    assert res["state"] == "final" and "week 15 (Final)" in res["why"]
    assert "**No weekly moves:**" in aw.render_award_moves(res, RULES)
    assert any("are Final" in n for n in _moves(fin, 15)["notes"])


def test_a_partial_week_raises():
    lines = _week(1) + [x for x in _week(2) if x["award"] != "bust"]
    with pytest.raises(aw.AwardsError, match="week 2"):
        _moves(lines, 2)


def test_the_thresholds_are_required():
    with pytest.raises(aw.AwardsInputError):
        aw.award_moves(_week(1) + _week(2), "2026-27", 2, {"lead_change_share": 0.5})
    from modules.data_loader import _LEAGUE_CONFIG
    good = copy.deepcopy(_LEAGUE_CONFIG)
    assert aw.moves_config(good) == {"lead_change_share": 0.5, "mvp_odds_swing_points": 10.0}
    for bad in ("drop_block", "drop_key", 0, -1, True, "0.5"):
        cfg = copy.deepcopy(good)
        nm = cfg["awards"]["newsletter_moves"]
        if bad == "drop_block":
            del cfg["awards"]["newsletter_moves"]
        elif bad == "drop_key":
            del nm["mvp_odds_swing_points"]
        else:
            nm["lead_change_share"] = bad
        with pytest.raises(aw.AwardsInputError):
            aw.moves_config(cfg)


def test_the_formatter_raises_without_the_threshold(monkeypatch):
    import modules.data_loader as dl
    cfg = copy.deepcopy(dl._LEAGUE_CONFIG)
    del cfg["awards"]["newsletter_moves"]
    monkeypatch.setattr(dl, "_LEAGUE_CONFIG", cfg)
    with pytest.raises(aw.AwardsInputError):
        _fmt().build_award_moves_block(ROOT, {"metadata": {"season_year": "2026-27"}}, 5)


def test_the_moves_come_from_the_hubs_history_through_newsletter_facts():
    src = (ROOT / "modules" / "awards.py").read_text(encoding="utf-8")
    body = src[src.index("def award_moves("):src.index("def render_award_moves(")]
    assert "facts = newsletter_facts(lines, season, week)" in body
    fsr = (ROOT / "scripts" / "format_stats_report.py").read_text(encoding="utf-8")
    assert "aw.award_moves(aw.read_history(base), season, int(week), rules)" in fsr


# =============================================================================
# the formatter
# =============================================================================

def test_the_report_joins_angles_then_award_moves_and_the_prompts_read_it_back(monkeypatch):
    F = _fmt()
    for n in ("format_section_1_matchup_summaries", "format_section_2_report_cards",
              "format_section_3_betting_lines", "format_section_4_potw", "format_section_5_fun_facts",
              "format_section_6_what_if", "format_section_7_power_rankings",
              "format_section_8_stats_corner", "format_section_9_around_nba",
              "format_section_10_rumor_mill"):
        monkeypatch.setattr(F, n, lambda *a, _n=n, **k: f"## {_n}\n")
    monkeypatch.setattr(F, "compute_storyline_alerts", lambda *a, **k: [])
    monkeypatch.setattr(F, "build_lookup_tables", lambda d: {})
    block = aw.render_award_moves({"state": "none", "week": 5, "moves": [], "notes": [], "why": ""}, RULES)
    md = F.format_stats_report({"metadata": {"week": 5}}, angles_block="## -> ANGLES -> NO LEAD THIS WEEK\n\nx\n",
                               award_moves_block=block)
    assert md.index("## -> ANGLES ->") < md.index(aw.MOVES_HEAD) < md.index("## format_section_1")
    assert pp.award_moves_block(md) == block.rstrip("\n")
    with pytest.raises(pp.PromptsRefused, match="AWARD MOVES"):
        pp.award_moves_block(md.replace(aw.MOVES_HEAD, "## -> OTHER -> "))


def _kw():
    import test_keepability_wire as W
    return W._kw()


def test_stats_corner_is_the_weeks_tables_only():
    F = _fmt()
    g = {"player_name": "P", "nba_team": "T", "manager": "Nick", "fantasy_points": 10.0,
         "date": "2026-11-20", "nba_opponent": "X"}
    w = {"player_name": "Q", "nba_team": "T", "manager": "Nick", "games": 3, "total_fp": 90.0, "fppg": 30.0}
    data = {"best_worst": {"best_games": [g], "worst_games": [g], "best_waivers": [w],
                           "best_free_agents": [{"player_name": "FA", "projected_fppg": 30.0}]},
            "season_performers": {"best_total_fp": [{"player_name": "S"}]}, "keeper_watch": _kw()}
    md = F.format_section_8_stats_corner(data, {})
    heads = re.findall(r"^\*\*(.+?)(?: \(\w+\))?:\*\*$", md, re.M)
    assert tuple(heads) == shape.SECTION_TABLES[8]
    for h in shape.CUT_MD_HEADINGS:
        assert h not in md


def test_power_rankings_and_rumor_mill_drop_their_cut_blocks():
    src = (ROOT / "scripts" / "format_stats_report.py").read_text(encoding="utf-8")
    for gone in ("Projected Finish Distribution:", "format_money_facts", "format_keeper_watch_facts",
                 "**Free Agent Targets:**", "Season Best -> Total FP", "Top Available Free Agents:"):
        assert gone not in src, gone
    assert "Free agent targets: on the hub, not in the issue." in src
    assert "shape.ADVICE_POINTER" not in src and "ADVICE_POINTER as _adv_ptr" in src


@needs_state("output/stats_report_week5.json", "output/awards_history.jsonl",
             why="the week-5 report and the awards history, through the new formatter")
def test_the_week5_report_through_the_new_formatter():
    """The published week-5 report through the 4d formatter, in memory (no
    angles file, no POTW or trade syncs: those are main()'s)."""
    F = _fmt()
    data = json.loads((ROOT / "output" / "stats_report_week5.json").read_text(encoding="utf-8"))
    md = F.format_stats_report(data, award_moves_block=F.build_award_moves_block(ROOT, data, 5))
    for h in shape.CUT_MD_HEADINGS:
        assert h not in md, h
    assert "## -> AWARD MOVES -> WEEK 5" in md and pp.award_moves_block(md)
    assert shape.NEXT_WEEK_POINTER in md and shape.ADVICE_POINTER in md
    s7 = md[md.index("## SECTION 7"):md.index("## SECTION 8")]
    assert "$" not in s7
    # the JSON keeps computing all of it
    assert data["money_section"] and data["keeper_watch"]["players"]
    assert data["rumor_mill"]["free_agent_targets"] and data["best_worst"]["best_free_agents"]


# =============================================================================
# the claim check
# =============================================================================

def _vocab():
    return cc.Vocabulary(MANAGERS, TEAMS, {}, [])


@pytest.mark.parametrize("section", [1, 3, 5, 7, 8, 10])
def test_a_dollar_line_without_its_pot_is_a_finding_in_any_section(section):
    draft = f"### **{section}. Anything**\n\nHayden is now on the hook for $45.\n"
    f = cc.money_line_findings(draft, _vocab())
    assert [(x.kind, x.section, x.token) for x in f] == [("money_unqualified", section, "$45")]


def test_a_dollar_line_with_its_pot_and_window_passes_and_safe_needs_both():
    ok = ("### **7. Power Rankings**\n\nBenton can't finish 3rd or 4th in the regular season (weeks 1-15), "
          "so he won't pay into its $180 pot. The $90 playoff pot is still open until the semifinals.\n")
    assert cc.money_line_findings(ok, _vocab()) == []
    bad = "### **7. Power Rankings**\n\nBenton is safe from paying.\n"
    assert [x.token for x in cc.money_line_findings(bad, _vocab())] == ["safe"]
    fine = "### **1. Matchup Summaries**\n\nNick's lead was safe by Thursday.\n"      # no money
    assert cc.money_line_findings(fine, _vocab()) == []
    nba = "### **9. Around the NBA**\n\nThe Lakers paid $45 million.\n"               # exempt
    assert cc.money_line_findings(nba, _vocab()) == []


def test_the_old_money_block_is_no_longer_exempt():
    draft = "### **7. Power Rankings**\n\n**Money and Exposure**\n\nGarrett's likeliest result is +$270.\n"
    assert [x.kind for x in cc.money_findings(draft, _vocab(), [])] == ["money_without_event"]


def test_a_week_label_with_a_hyphen_is_structure():
    assert cc.extract_numbers("These week-6 lines are Monday's closing line.") == []
    assert [n.value for n in cc.extract_numbers("all three week-6 adds, 48 startable games")] == [3.0, 48.0]


BL = {"spread_a": -28.5, "spread_b": 28.5, "over_under": 3050, "win_prob_a": 55.36, "win_prob_b": 44.64,
      "moneyline_a": -125, "moneyline_b": 125, "avg_score_a": 1537.93, "avg_score_b": 1509.24}
REPORT = {"looking_ahead": {"matchup_previews": [
    {"manager_a": "Nick", "manager_b": "Garrett", "team_name_a": "Luka my Balls", "team_name_b": "Blink-183",
     "betting_line": BL}]}}
S3 = ("### **3. Betting Lines**\n\n**Luka my Balls vs Blink-183**\n\n"
      "*Line: Luka my Balls -28.5 (Blink-183 +28.5) | O/U: 3050*\n"
      "*Win Prob: Luka my Balls 55.36% | Blink-183 44.64%*\n"
      "*Moneyline: Luka my Balls -125 | Blink-183 +125*\n"
      "*Avg Score: Luka my Balls 1537.93 | Blink-183 1509.24*\n\n"
      "Nick is the -125 favorite. The winner takes the tiebreaker.\n\n"
      f"{shape.NEXT_WEEK_POINTER}\n\n### **4. Player of the Week**\n\nx\n")


def test_the_betting_lines_trace_to_the_report_line():
    assert cc.betting_lines_findings(S3, REPORT, TEAMS) == []
    swapped = S3.replace("Luka my Balls 55.36% | Blink-183 44.64%", "Blink-183 44.64% | Luka my Balls 55.36%")
    assert cc.betting_lines_findings(swapped, REPORT, TEAMS) == []
    wrong = S3.replace("O/U: 3050", "O/U: 3040").replace("Blink-183 +125*", "Blink-183 +130*")
    toks = [f.token for f in cc.betting_lines_findings(wrong, REPORT, TEAMS)]
    assert toks == ["O/U 3040 (report 3050)", "Moneyline Blink-183 +130 (report +125)"]
    no_avg = S3.replace("*Avg Score: Luka my Balls 1537.93 | Blink-183 1509.24*\n", "")
    assert [f.token for f in cc.betting_lines_findings(no_avg, REPORT, TEAMS)] == ["Avg Score"]
    two = {"looking_ahead": {"matchup_previews": REPORT["looking_ahead"]["matchup_previews"] + [
        {"manager_a": "Hayden", "manager_b": "Benton", "team_name_a": "Big Nik Energy",
         "team_name_b": "Spayed for Cade", "betting_line": BL}]}}
    f = cc.betting_lines_findings(S3, two, TEAMS)
    assert len(f) == 1 and "no block" in f[0].sentence


def test_check_draft_runs_the_new_rules_and_lists_their_kinds():
    import check_draft as cd
    src = (ROOT / "scripts" / "check_draft.py").read_text(encoding="utf-8")
    assert "cc.money_line_findings(draft_text, vocab)" in src
    assert "cc.betting_lines_findings(draft_text, meta.get(\"current_report\") or {}" in src
    for k in ("money_unqualified", "betting_line_mismatch"):
        assert k in cd.KIND_ORDER and k in cd.KIND_LABEL


# =============================================================================
# the page
# =============================================================================

def _gen():
    import newsletter_html_generator as g
    return g


def test_the_hub_line_is_a_pointer_and_48as_parser_skips_it():
    from modules import hub_matchups as hm
    g = _gen()
    body = S3.split("\n\n", 1)[1].split("### **4.")[0]
    html = g.parse_section(body, "Betting Lines")
    assert html.count('<div class="hub-pointer">') == 1 and "<p>On the hub" not in html
    page = f'<section id="betting-lines"><h2>Betting Lines</h2>{html}</section>'
    out = hm.newsletter_blocks(page, [{"manager_a": "Nick", "manager_b": "Garrett"}], TEAMS, 5)
    blk = out[("Nick", "Garrett")]
    assert blk["paragraphs"] == ["Nick is the -125 favorite. The winner takes the tiebreaker."]
    assert blk["line"] == "Luka my Balls -28.5 / -125, O/U 3050"


def test_the_section_ids_are_unchanged_betting_lines_kept():
    g = _gen()
    names = [n for _, n in g.required_sections()]
    assert names == ["Matchup Summaries", "Report Cards", "Betting Lines", "Player of the Week", "Fun Facts",
                     "What If?", "Power Rankings", "Stats Corner", "Around the NBA", "Rumor Mill"]
    assert names[2].lower().replace(" ", "-") == "betting-lines"


@pytest.mark.parametrize("head", list(shape.CUT_DRAFT_HEADINGS) + ["Best Performers (Total FP, This Season)"])
def test_a_draft_with_a_cut_block_refuses(head):
    with pytest.raises(SystemExit, match="no longer has"):
        _gen().check_cut_blocks(f"### **7. Power Rankings**\n\n**{head}**\n\ntext\n")


def test_a_4d_draft_passes_the_cut_block_gate():
    g = _gen()
    g.check_cut_blocks(S3 + "\n**Power Rankings**\n\n**Top Performances**\n\n**Waiver Pickups**\n\n"
                       "**Trade Ideas**\n\n**Hot Streaks**\n\n" + shape.ADVICE_POINTER + "\n")
    src = (ROOT / "scripts" / "newsletter_html_generator.py").read_text(encoding="utf-8")
    main = src[src.index("def main():"):]
    assert main.index("check_sections_complete(markdown_text)") < main.index("check_cut_blocks(markdown_text)") \
        < main.index("out = build_newsletter_html(")


def test_no_keeper_watch_panel_and_no_cards_in_the_issue():
    from modules.stats_corner_viz import render_stats_corner_visualizations as viz
    assert shape.KEEPER_WATCH_IN_ISSUE is False
    assert "sc-kw3" in viz({"keeper_watch": _kw()})                         # the panel still exists
    assert viz({"keeper_watch": _kw()}, include_keeper_watch=False) == ""
    src = (ROOT / "scripts" / "newsletter_html_generator.py").read_text(encoding="utf-8")
    assert "include_keeper_watch=_shape.KEEPER_WATCH_IN_ISSUE" in src
    assert "if kw_players and _shape.KEEPER_WATCH_IN_ISSUE and data_dir" in src
    assert "render_money_html" not in src and ">Keeper Watch</a>" not in src


# =============================================================================
# the template, the prompts, the verification checklist
# =============================================================================

def _block(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_the_template_has_the_new_shapes():
    assert shape.NEXT_WEEK_POINTER in TEMPLATE and shape.ADVICE_POINTER in TEMPLATE
    assert "24. **AWARD RACES ONLY WHEN THEY MOVED.**" in TEMPLATE and "AWARD MOVES" in TEMPLATE
    assert "**Pot and window, in every section**" in TEMPLATE
    s3 = _block(TEMPLATE, "## **3. Betting Lines**", "## **4. Player of the Week**")
    assert "2-3 sentences: what decides this matchup." in s3 and "POSITIONAL MATCHUPS" not in s3
    for n, want in ((7, shape.SECTION_TABLES[7]), (8, shape.SECTION_TABLES[8])):
        sec = _block(TEMPLATE, f"## **{n}. ", f"## **{n + 1}. ")
        out = _block(sec, "### REQUIRED OUTPUT FORMAT", "### KEY RULES")
        heads = [h for h in re.findall(r"^\*\*([^*]+)\*\*$", out, re.M) if h != "Stats Corner"]
        assert tuple(heads) == want, (n, heads)
    for h in shape.CUT_DRAFT_HEADINGS:
        assert not re.search(r"^\*\*" + re.escape(h) + r"[^*]*\*\*$", TEMPLATE, re.M), h
    for gone in ("EIGHT tables", "TWO tables required", "FREE AGENT TARGETS (from",
                 "MONEY AND EXPOSURE -- FACTS", "KEEPER WATCH -- SUMMARY FACTS"):
        assert gone not in TEMPLATE, gone


def test_the_prompts_parts_follow_the_template():
    g = _gen()
    names = [n.rstrip("?") for _, n in g.required_sections()]
    blocks = pp.prompt_blocks(PROMPTS)
    p1 = re.findall(r"^(\d+)\. (?:\*\*)?([A-Z][A-Za-z ]+?)(?:\*\*)?(?: --|\s*\(|$)", blocks[0], re.M)
    p2 = re.findall(r"^(\d+)\. \*\*([^*]+)\*\*", blocks[1], re.M)
    p3 = re.findall(r"^### Section (\d+): (.+)$", blocks[2], re.M)
    got = [(int(a), b.strip().rstrip("?")) for a, b in p1 + p2 + p3]
    assert got == list(enumerate(names, 1)), got
    assert "ONE table: Power Rankings" in blocks[1] and "THREE tables, in this order" in blocks[1]
    assert pp.PH_AWARDS in blocks[0] and pp.PH_LINES in blocks[0]                # 5g's line stays
    assert "free agent targets, hot streaks" not in blocks[2] and "**No free agent targets:**" in blocks[2]


def test_the_verification_checklist_follows():
    v = (ROOT / "templates" / "VERIFICATION_TEMPLATE.md").read_text(encoding="utf-8")
    assert "### Money lines (Rule 23" in v and "### Award races (Rule 24)" in v
    assert "THREE tables (Top Performances, Worst Performances, Waiver Pickups)" in v
    assert "ONE table (Power Rankings)" in v
