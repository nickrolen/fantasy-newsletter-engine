"""Money and Exposure: the ledger as a section (HANDOFF_MONEY_SECTION_2026-10-29
s.1-s.5; Nick, 10-29 -- ship with today's numbers; the three prose rules; lead
with the +$135 case). Plus the step C follow-ups of 10-30: a conflicting
keepability snapshot stops the page build; the rumor mill's tiers are cut by
keep rank.
"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import claim_check as cc                       # noqa: E402
from modules import standing_threads as T                   # noqa: E402
from modules.data_loader import MANAGERS, MANAGER_TO_TEAM   # noqa: E402

RULES = {"league_champion": {"total": 180, "per_payer": 90},
         "playoff_champion": {"total": 90, "per_payer": 45},
         "payer_places": [3, 4], "semis_end": 18, "cup_first_played": "2026-27"}

# today's ledger (MONEY_SECTION_S0_RECHECK_2026-10-29, 20k)
LEDGER = {
    "Hayden": (0.4844, 73.99, 0.1786, 0.298, 0.5319, 0.2275, 0.4717,
               {-135.0: .1173, -90.0: .0214, -45.0: .1871, 0.0: .09845, 90.0: .0914,
                135.0: .2275, 180.0: .09015, 270.0: .1667}),
    "Nick": (0.3891, 60.49, 0.2938, 0.3619, 0.3488, 0.1095, 0.2704,
             {-135.0: .12755, -90.0: .07305, -45.0: .1117, 0.0: .1891, 90.0: .10945,
              135.0: .1095, 180.0: .1203, 270.0: .15935}),
    "Garrett": (0.0825, -58.16, 0.7202, 0.1862, 0.5546, 0.032, 0.1791,
                {-135.0: .4264, -90.0: .17115, -45.0: .0962, 0.0: .181, 90.0: .0427,
                 135.0: .032, 180.0: .0297, 270.0: .02085}),
    "Benton": (0.044, -76.33, 0.8074, 0.1538, 0.5647, 0.0187, 0.0788,
               {-135.0: .4726, -90.0: .21835, -45.0: .0734, 0.0: .16415, 90.0: .02755,
                135.0: .01875, 180.0: .0154, 270.0: .0098}),
}
STANDINS = {"Hayden": [{"week": 3, "name": "Replacement for Tyrese Haliburton (34.8)",
                        "covers": "Tyrese Haliburton", "level": 34.8},
                       {"week": 3, "name": "Replacement for open spot 1, Hayden (34.8)",
                        "covers": None, "level": 34.8}],
            "Nick": [{"week": 3, "name": "Replacement for Anthony Edwards (34.8)",
                      "covers": "Anthony Edwards", "level": 34.8}],
            "Benton": [], "Garrett": []}
POINTS = {"Hayden": 24724, "Nick": 24534, "Garrett": 23540, "Benton": 23313}


def _sp(ledger=LEDGER, exact=None, standins=STANDINS, week=1):
    mans = list(MANAGERS)
    L = {m: {"dollars": {"expected": v[1], "min": -135.0, "max": 270.0, "distribution": v[7],
                         "p_league_champion": v[0], "p_pays_league_pot": v[2],
                         "p_playoff_champion": v[3], "p_pays_playoff_pot": v[4],
                         "p_win_regular_season_lose_semifinal": v[5]},
             "keeper": {"p_sixth_keeper_next_season": v[6]}} for m, v in ledger.items()}
    ex = exact or {m: {"title": "alive", "league_pot": "alive", "playoff_champion": "alive",
                       "playoff_pot": "alive", "cup_champion": "alive"} for m in mans}
    pts = np.array([[POINTS[m] for m in mans]] * 3, dtype=float)
    return SimpleNamespace(through="cup", managers=mans, current_week=week, num_simulations=20000,
                           seed=20262027, reg_points=pts, standins=standins,
                           ledger=lambda: L, exact=lambda: ex)


def _ms(**kw):
    return T.money_section(_sp(**kw), {"Hayden": 30.2, "Nick": 31.59}, rules=RULES, early=True)


# ---------------------------------------------------------------------------
# the section's sentences: Nick's three rules, the lead, the language rule
# ---------------------------------------------------------------------------

def test_the_section_leads_with_haydens_plus_135_case():
    ms = _ms()
    lead = ms["lines"][1]
    assert lead.startswith("Hayden's single most likely outcome is +$135 (22.8%)")
    assert "Nick 11.0%, Garrett 3.2%, Benton 1.9%" in lead
    assert ms["lines"][0].startswith("Nothing is settled: every manager can still finish "
                                     "anywhere from -$135 to +$270")


def test_title_odds_are_rounded_and_the_confidence_note_is_said_once():
    ms = _ms()
    text = " ".join(ms["lines"])
    assert "Hayden about 48%, Nick about 39%, Garrett about 8%, Benton about 4%" in text
    assert "48.4" not in text
    assert text.count("runs a little confident") == 1
    late = T.money_section(_sp(), {"Hayden": 30.2, "Nick": 31.59}, rules=RULES, early=False)
    assert "runs a little confident" not in " ".join(late["lines"])


def test_the_odds_say_what_they_assume_and_the_figure_without_it():
    lines = _ms()["lines"]
    hay = next(x for x in lines if x.startswith("Hayden's odds assume"))
    assert "Tyrese Haliburton's IL stint and an open roster spot" in hay
    assert "replacement-level free agents (34.8 FPPG) from week 3" in hay
    assert "without those pickups he is at about 30%" in hay and "better real pickup raises it" in hay
    nick = next(x for x in lines if x.startswith("Nick's odds assume"))
    assert "a replacement-level free agent" in nick and "that pickup" in nick and "about 32%" in nick
    assert not any(x.startswith(("Garrett's odds", "Benton's odds")) for x in lines)


def test_a_manager_with_stand_ins_needs_his_without_figure():
    with pytest.raises(ValueError, match="Nick"):
        T.money_section(_sp(), {"Hayden": 30.2}, rules=RULES)


def test_a_season_total_says_what_it_is_conditional_on():
    line = next(x for x in _ms()["lines"] if "regular-season points" in x)
    assert "Hayden 24,724" in line
    assert "apart from the moves the league's rules force" in line and "run low by design" in line


def test_every_line_that_talks_about_paying_names_its_pot():
    ex = {m: {"title": "alive", "league_pot": "alive", "playoff_champion": "alive",
              "playoff_pot": "alive", "cup_champion": "alive"} for m in MANAGERS}
    ex["Benton"].update(league_pot="will_pay", title="eliminated")
    ex["Hayden"].update(playoff_pot="will_pay")
    for ms in (_ms(), _ms(exact=ex)):
        page_cols = [c for _cap, cols in T.MONEY_PAGE_TABLES for c in cols]
        for x in ms["lines"] + list(T.MONEY_COLUMNS) + page_cols:
            low = x.lower()
            assert "safe" not in low, x
            if "pay" in low or "owe" in low or "into" in low:
                assert "pot" in low, x


# ---------------------------------------------------------------------------
# two currencies, never summed; clinches from the arithmetic
# ---------------------------------------------------------------------------

def test_dollars_do_not_move_with_the_cup():
    a = _ms()
    other = {m: v[:6] + ((1.0 if m == "Benton" else 0.0),) + v[7:] for m, v in LEDGER.items()}
    b = T.money_section(_sp(ledger=other), {"Hayden": 30.2, "Nick": 31.59}, rules=RULES, early=True)
    keys = ("expected_dollars", "min_dollars", "max_dollars", "most_likely_dollars",
            "p_into_league_pot", "p_into_playoff_pot", "p_win_rs_lose_semi")
    for m in MANAGERS:
        assert {k: a["managers"][m][k] for k in keys} == {k: b["managers"][m][k] for k in keys}
        assert a["managers"][m]["p_sixth_keeper"] != b["managers"][m]["p_sixth_keeper"] or m == "Benton"
    import inspect
    from modules import season_sim
    assert "cup" not in " ".join(inspect.signature(season_sim.dollars_for).parameters)


def test_a_clinch_comes_from_races_exact_never_from_a_sampled_one():
    sure = {m: v for m, v in LEDGER.items()}
    sure["Hayden"] = (1.0,) + LEDGER["Hayden"][1:]
    assert _ms(ledger=sure)["lines"][0].startswith("Nothing is settled")
    ex = {m: {"title": "alive", "league_pot": "alive", "playoff_champion": "alive",
              "playoff_pot": "alive", "cup_champion": "alive"} for m in MANAGERS}
    ex["Hayden"]["title"] = "clinched"
    assert _ms(exact=ex)["lines"][0] == ("Settled so far: Hayden has clinched the "
                                         "regular-season title and its pot.")


# ---------------------------------------------------------------------------
# the claim check: figures in the block every week, nowhere else; "about N%"
# ---------------------------------------------------------------------------

def _pool(ms):
    import format_stats_report as F
    vocab = cc.Vocabulary(MANAGERS, MANAGER_TO_TEAM, {}, [])
    facts = "\n".join(F.format_money_facts(ms))
    return vocab, cc.build_pool(vocab, [("report", {"money_section": ms})], [("facts", facts)])


BLOCK = ("### **7. Power Rankings**\n\n**Money and Exposure**\n\n"
         "Hayden's single most likely outcome is +$135, at 22.8%: he wins the regular-season pot "
         "and loses his semifinal. He is about 48% to win the regular season, but that rests on "
         "replacement-level pickups; without them he is at about 30%. Expected net dollars: "
         "Hayden +$74, Benton -$76.\n")


def test_a_draft_with_the_section_passes_the_claim_check():
    ms = _ms()
    vocab, pool = _pool(ms)
    assert cc.check(BLOCK, pool, vocab) == []
    assert cc.money_findings(BLOCK, vocab, []) == []          # no money event, and still fine


def test_dollar_figures_outside_the_block_are_still_findings():
    ms = _ms()
    vocab, pool = _pool(ms)
    draft = BLOCK + "\n### **5. Fun Facts**\n\nHayden could collect +$135 this year.\n"
    found = cc.money_findings(draft, vocab, [])
    assert [f.section for f in found] == [5] and found[0].kind == "money_without_event"


def test_about_n_percent_must_be_exact_and_only_in_the_block():
    ms = _ms()
    vocab, pool = _pool(ms)
    wrong = BLOCK.replace("about 48%", "about 50%")
    assert any(f.kind == "unsupported_number" and f.token.startswith("50")
               for f in cc.check(wrong, pool, vocab))
    outside = "### **7. Power Rankings**\n\nHayden is about 48% to win the regular season.\n"
    assert any(f.kind == "approximate_number" for f in cc.check(outside, pool, vocab))


# ---------------------------------------------------------------------------
# the page: the block is lifted into the rendered section; its table checks
# ---------------------------------------------------------------------------

def test_the_page_lifts_the_paragraphs_and_renders_the_table():
    import newsletter_html_generator as g
    from modules import published_tables as pt
    ms = _ms()
    rest, summ = g.lift_block(BLOCK.split("\n", 1)[1], g.MONEY_HEADER)
    assert "+$135" not in rest and summ.count("<p>") == 1
    html = T.render_money_html(ms, summ)
    # two tables (Nick, 10-30): a header and four managers each
    assert html.count("<tr>") == 2 * (1 + 4) and "Cup 6th keeper %" in html
    page = f"<html><body><h2>Power Rankings</h2>{html}</body></html>"
    findings, unchecked = pt.check_document(page, {"season": None, "standings": {}})
    assert findings == [] and unchecked == []
    broken = page.replace(">+$74<", ">+$84<")
    findings, _ = pt.check_document(broken, {"season": None, "standings": {}})
    assert any(f.check == "zero-sum" for f in findings)


def test_the_keeper_watch_table_is_checked_too():
    from modules import published_tables as pt
    from modules.stats_corner_viz import render_keeper_watch
    import test_keepability_wire as W
    html = "<html><body>" + render_keeper_watch(W._kw()) + "</body></html>"
    findings, unchecked = pt.check_document(html, {"season": None, "standings": {}})
    assert findings == [] and unchecked == []
    broken = re.sub(r'(<td class="sc-kw3-p6">)\d+%', r"\g<1>0%", html, count=1)
    findings, _ = pt.check_document(broken, {"season": None, "standings": {}})
    assert any(f.check == "5 vs 6 keepers" for f in findings)


def test_the_drafter_is_told_the_rules():
    import format_stats_report as F
    facts = "\n".join(F.format_money_facts(_ms()))
    assert "lead with the named outcome above (Hayden's +$135 finish)" in facts
    assert "\"about N%\"" in facts and "run low by design" in facts and "a little confident" in facts
    tmpl = (ROOT / "templates" / "newsletter_template.md").read_text(encoding="utf-8")
    assert "**Money and Exposure**" in tmpl and "Dollar figures belong in this block only" in tmpl


# ---------------------------------------------------------------------------
# the counterfactual: no stand-ins for one manager, nobody else moves
# ---------------------------------------------------------------------------

def test_no_standins_leaves_that_managers_spots_open_and_nobody_else_moves():
    import test_roster_plan as R
    from modules import roster_plan as rp
    from modules.data_loader import PlayerIndex
    players, rosters = R._league()
    rosters["Nick"] = rosters["Nick"][:13]
    base = R._build(players, rosters)
    tags = {n: "HEALTHY" for n in players}
    off = rp.build(start_week=2, il_slots={}, rosters=rosters, windows=R.WINDOWS,
                   players=PlayerIndex(players), statuses=tags, rules=R.RULES,
                   standin_gp=R.GP, order=list(MANAGERS), no_standins=frozenset({"Nick"}))
    assert base[3]["Nick"]["added"] and not off[3]["Nick"]["added"]
    assert len(off[3]["Nick"]["active"]) == 13
    for m in MANAGERS:
        if m != "Nick":
            assert base[3][m] == off[3][m]


# ---------------------------------------------------------------------------
# step C follow-ups (Nick, 10-30)
# ---------------------------------------------------------------------------

def test_a_conflicting_snapshot_stops_the_page_build(tmp_path, monkeypatch):
    import newsletter_html_generator as g
    calls = []
    monkeypatch.setattr(g, "check_sections_complete", lambda md: None)
    monkeypatch.setattr(g, "build_newsletter_html", lambda *a, **k: str(tmp_path / "x.html"))
    (tmp_path / "x.html").write_text("x")
    monkeypatch.setattr(g, "claim_check_status", lambda p: "ok")
    monkeypatch.setattr(g, "table_check", lambda p: 0)
    monkeypatch.setattr(g, "log_published_lines", lambda *a, **k: calls.append("logged"))
    monkeypatch.setattr(g, "publish_keepability_snapshot",
                        lambda *a, **k: {"wrote": False, "conflict": True, "path": "p", "why_not": "x"})
    draft = tmp_path / "d.md"
    draft.write_text("# x\n")
    monkeypatch.setattr(sys, "argv", ["g", "--input", str(draft), "--output", str(tmp_path / "x.html"),
                                      "--stats-report", str(tmp_path / "sr.json")])
    assert g.main() == 1 and calls == []
    monkeypatch.setattr(g, "publish_keepability_snapshot",
                        lambda *a, **k: {"wrote": True, "conflict": False, "path": "p", "why_not": None})
    assert g.main() == 0 and calls == ["logged"]


def test_the_rumor_mill_cuts_its_tiers_by_keep_rank():
    from modules.rumor_mill_analyzer import keep_tiers
    P = lambda n, v, r: SimpleNamespace(player_name=n, trade_value=v, keep_rank=r)  # noqa: E731
    # by production: A B C D E F G H; by keep rank: H G A B C D E F
    ps = [P("A", 50, 3), P("B", 48, 4), P("C", 46, 5), P("D", 44, 6), P("E", 42, 7),
          P("F", 40, 8), P("G", 38, 2), P("H", 30, 1)]
    t = keep_tiers(ps, 6, True, "Nick")
    assert [p.player_name for p in t["core"]] == ["H", "G", "A"]
    assert [p.player_name for p in t["fringe"]] == ["B", "C", "D"]
    assert [p.player_name for p in t["block"]] == ["E", "F"]
    assert [p.player_name for p in t["all_sorted"]] == list("ABCDEFGH")   # values stay by production
    with pytest.raises(KeyError, match="Z"):
        keep_tiers(ps + [P("Z", 20, None)], 6, True, "Nick")
