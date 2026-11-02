"""No magic number before the week 8 report (Nick, 11-02:
"we probably should have just no mention at all of 'magic numbers' until
like, at least week 8 or something? Theyre pretty pointless to report on
before that point.").

presentation.magic_number_from_week (required) decides what is SHOWN: the
storyline alerts and the ANGLES ranking (CLINCH WATCH), the standing
threads, Section 7's facts, and the claim check's finding. The value is
still computed and kept in the report JSON; clinch logic is unchanged.
(claude/HANDOFF_SECTION10_OFF_AND_BUDGET_WEEK_2026-11-02.md part 3)
"""
import importlib.util
import json
from pathlib import Path

import pytest

import modules.data_loader as dl
from modules import angles as A
from modules import claim_check as cc
from modules import standing_threads as ST
from modules.storylines import compute_storylines
from league_state import needs_state

ROOT = Path(__file__).parent.parent
MGRS = ["Nick", "Hayden", "Benton", "Garrett"]
PAIRS = [[("Nick", "Hayden"), ("Benton", "Garrett")],
         [("Nick", "Benton"), ("Hayden", "Garrett")],
         [("Nick", "Garrett"), ("Hayden", "Benton")]]


def _fmt():
    spec = importlib.util.spec_from_file_location("fsr", ROOT / "scripts" / "format_stats_report.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------ the threshold

def test_the_live_threshold_is_8_with_nicks_quote():
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text("utf-8"))["presentation"]
    assert cfg["magic_number_from_week"] == 8
    assert "pointless to report on" in cfg["_magic_number_comment"]
    assert dl.magic_number_from_week() == 8
    assert not dl.shows_magic_number(7) and dl.shows_magic_number(8)


@pytest.mark.parametrize("cfg", [{}, {"magic_number_from_week": None},
                                 {"magic_number_from_week": "8"}, {"magic_number_from_week": 0},
                                 {"magic_number_from_week": 8.0},
                                 {"magic_number_from_week": True}])
def test_a_missing_or_bad_threshold_raises(cfg):
    with pytest.raises(ValueError, match="magic_number_from_week"):
        dl.shows_magic_number(8, cfg)


@pytest.mark.parametrize("week", [None, "8", 8.0, True])
def test_an_unknown_report_week_raises_rather_than_default(week):
    with pytest.raises(ValueError, match="report week"):
        dl.shows_magic_number(week)


# ------------------------------------- storyline alerts and the ANGLES block

def _report(week, magic=13):
    return {"metadata": {"week": week},
            "power_rankings": [{"manager": "Nick", "rank": 1, "magic_number": magic,
                                "record": "2-0", "title_odds": 58.5},
                               {"manager": "Hayden", "rank": 2, "magic_number": None,
                                "record": "1-1", "title_odds": 16.5}]}


def test_no_clinch_watch_before_week_8_and_the_value_is_kept():
    data = _report(2)
    kinds = [s.kind for s in compute_storylines(data, None, "2026-27", MGRS)]
    assert "clinch_watch" not in kinds
    assert data["power_rankings"][0]["magic_number"] == 13       # still in the JSON


def test_clinch_watch_from_week_8_as_today():
    stories = compute_storylines(_report(8, 4), None, "2026-27", MGRS)
    cw = [s for s in stories if s.kind == "clinch_watch"]
    assert [s.text for s in cw] == [" -> CLINCH WATCH: Nick's magic number is 4"]


def test_a_magic_number_with_no_report_week_raises():
    with pytest.raises(ValueError, match="report week"):
        compute_storylines({"power_rankings": _report(2)["power_rankings"]}, None, "2026-27", MGRS)


def test_no_clinch_watch_angle_in_the_week_2_ranking():
    """The ANGLES ranking takes its CLINCH WATCH angle from the storyline
    (storyline_angles): before week 8 there is none to rank; from week 8 the
    angle is there as today."""
    hist = A.History.build([], lambda s: 15)
    for week, want in ((2, False), (8, True)):
        stories = compute_storylines(_report(week), None, "2026-27", MGRS)
        texts = [a.text for a in A.storyline_angles(stories, hist, week, 4 * week)]
        assert any("CLINCH WATCH" in t for t in texts) is want, (week, texts)


# ---------------------------------------------------------- standing threads

def _season(weeks):
    sm = []
    for w in range(1, weeks + 1):
        for (a, b) in PAIRS[w % 3]:
            # Nick wins every week; the rest by a fixed order, with distinct
            # point totals so no tiebreak is ever needed
            rank = {"Nick": 4, "Hayden": 3, "Benton": 2, "Garrett": 1}
            sm.append({"season": "x", "week": w, "manager_a": a, "manager_b": b,
                       "score_a": 100 * rank[a] + w, "score_b": 100 * rank[b] + w})
    return sm


def _rules():
    return {"league_champion": {"total": 300, "per_payer": 150},
            "playoff_champion": {"total": 300, "per_payer": 150},
            "payer_places": [3, 4], "semis_end": 0, "cup_first_played": None}


@pytest.mark.parametrize("week, shown", [(2, False), (7, False), (8, True), (9, True)])
def test_the_standing_thread_names_the_magic_number_only_from_week_8(week, shown):
    sm = _season(week)
    pairings = [{"week": w, "manager_a": a, "manager_b": b}
                for w in range(1, 16) for a, b in PAIRS[w % 3]]
    assert A.magic_number(sm, week, 15)[1] > 0                  # computed either way
    out = ST.regular_season(sm, week, 15, _rules(), pairings=pairings)
    assert any("magic number" in ln for ln in out) is shown


# ---------------------------------------------------------- Section 7 facts

def _section7(report):
    f = _fmt()
    return f.format_section_7_power_rankings(report, f.build_lookup_tables(report))


@needs_state("output/stats_report_week2.json", why="the week 2 report as published (11-02)")
def test_week_2_section_7_and_the_whole_report_have_no_magic_number():
    rep = json.loads((ROOT / "output" / "stats_report_week2.json").read_text("utf-8"))
    nick = next(p for p in rep["power_rankings"] if p["manager"] == "Nick")
    assert nick["magic_number"] == 13                              # the JSON keeps it
    assert "magic" not in _section7(rep).lower()
    stories = compute_storylines(rep, None, "2026-27", MGRS)
    assert not [s for s in stories if "magic" in s.text.lower()]
    rep8 = dict(rep, metadata=dict(rep["metadata"], week=8))
    assert "**Magic Number:** Nick's magic number is 13" in _section7(rep8)


# ------------------------------------------------------------ claim check

def test_the_claim_check_flags_a_magic_number_before_week_8():
    vocab = cc.Vocabulary(MGRS)
    draft = "## **7. Power Rankings**\n\nNick's magic number is 13 already.\n"
    f2 = cc.magic_number_findings(draft, vocab, 2)
    assert [(x.kind, x.token.lower()) for x in f2] == [("magic_number_early", "magic number")]
    assert cc.magic_number_findings(draft, vocab, 8) == []
