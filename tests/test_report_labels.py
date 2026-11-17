"""H51 D (FIXES items 1 and 4): the report card's "New players" line and the
Career Luck table's scope.

Item 1: the card's "Waiver adds: 6 adds" counted every player who JOINED that
week -- the previous week's rule-7 claims applied in this window included --
and the week-4 drafting chat turned Nick's into "made six adds, the most in
the league" (he made 3). The line now says players joined, split by where
each counts, with the ADD BUDGET table's own counting
(transaction_rulings.add_budget_week via joined_by_budget_week)."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from modules import report_builder as rb                     # noqa: E402
from modules import transaction_rulings as tr                 # noqa: E402


def _fmt():
    spec = importlib.util.spec_from_file_location("format_stats_report",
                                                  ROOT / "scripts" / "format_stats_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_label_splits_this_weeks_adds_from_last_weeks_claims():
    fmt = _fmt()
    rc = {"joined_week_adds": 3, "joined_claims": 3, "joined_claim_weeks": {"3": 3}, "joined_no_budget": 0}
    assert fmt.joined_label(rc, 6, 4) == "6 joined (3 week-4 adds, 3 week-3 claims)"
    rc = {"joined_week_adds": 1, "joined_claims": 0, "joined_claim_weeks": {}, "joined_no_budget": 0}
    assert fmt.joined_label(rc, 1, 4) == "1 joined (1 week-4 add)"
    assert fmt.joined_label({}, 6, 4) == "6 joined"           # a card from before the split


@pytest.mark.skipif(not (ROOT / "output" / "stats_report_week4.json").is_file(),
                    reason="league state not in this checkout (output/stats_report_week4.json)")
def test_the_card_line_never_says_adds():
    """Week 4's real report, formatted: a report from before the split says
    only how many joined; with the split it says which were this week's adds."""
    import json
    fmt = _fmt()
    rep = json.loads((ROOT / "output" / "stats_report_week4.json").read_text(encoding="utf-8"))
    md = fmt.format_section_2_report_cards(rep, fmt.build_lookup_tables(rep))
    assert "Waiver adds" not in md and "- New players: 6 joined, 468.75 total FP over 13 games" in md
    nick = next(rc for rc in rep["report_cards"] if rc["manager"] == "Nick")
    nick.update(joined_week_adds=3, joined_claims=3, joined_claim_weeks={"3": 3}, joined_no_budget=0)
    md = fmt.format_section_2_report_cards(rep, fmt.build_lookup_tables(rep))
    assert ("- New players: 6 joined (3 week-4 adds, 3 week-3 claims), 468.75 total FP over 13 games "
            "(36.06 fppg, 78.1 FP per player)") in md


def test_a_split_that_does_not_cover_the_cards_players_raises():
    with pytest.raises(ValueError, match="would not add up"):
        rb._joined_split({4: ["A"]}, 4, "Nick", ["A", "B"])
    got = rb._joined_split({4: ["A"], 3: ["B", "C"], None: ["D"]}, 4, "Nick", ["A", "B", "C", "D"])
    assert got == {"week_adds": 1, "claims": 2, "claim_weeks": {"3": 2}, "no_budget": 1}


@pytest.mark.skipif(not (ROOT / "data" / "waivers_week4.txt").is_file()
                    or not (ROOT / "config" / "TRANSACTION_RULINGS.json").is_file(),
                    reason="league state not in this checkout (data/waivers_week4.txt and the rulings)")
def test_week_4s_real_numbers():
    """Week 4 on the real file and rulings (checked by hand against
    data/waivers_week4.txt and its claim_week rulings, 11-17): Nick 3 adds +
    3 week-3 claims, Hayden 0 + 2, Benton 2 + 1, Garrett 1 + 0."""
    sched = tr._schedule(ROOT)
    got = tr.joined_by_budget_week(ROOT, 4, sched)
    split = {m: (len(b.get(4, [])), len(b.get(3, []))) for m, b in got.items()}
    assert split == {"Nick": (3, 3), "Hayden": (0, 2), "Benton": (2, 1), "Garrett": (1, 0)}, got
    assert all(set(b) <= {3, 4} for b in got.values()), got
    # the same counting as the ADD BUDGET table: every week-4 add listed here is
    # in its week-4 budget (which also holds week-4 claims applied in week 5's window)
    budget = tr.adds_by_budget_week(ROOT, sched)
    for m, b in got.items():
        assert set(b.get(4, [])) <= set(budget.get(4, {}).get(m, [])), m
        assert set(b.get(3, [])) <= set(budget.get(3, {}).get(m, [])), m


def test_the_career_luck_table_names_its_scope():
    src = (ROOT / "scripts" / "format_stats_report.py").read_text(encoding="utf-8")
    assert '"_Career Luck (all-time, every week incl. playoffs):_"' in src
