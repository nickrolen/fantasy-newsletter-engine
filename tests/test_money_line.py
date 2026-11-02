"""The money line must not contradict the Money and Exposure rule
(claude/HANDOFF_SECTION10_OFF_AND_BUDGET_WEEK_2026-11-02.md part 4).

In a week where no money was decided, angles.money_line used to tell the
drafter "Quote no dollar figures anywhere in the newsletter", while the claim
check exempts Section 7's Money and Exposure block (claim_check.MONEY_BLOCK)
and the template puts dollar figures there every week. The week 2 drafter
caught it. The line now names the exemption from claim_check's own constants.
"""
from modules import angles as A
from modules import claim_check as cc
from modules import standing_threads as ST

MGRS = ["Nick", "Hayden", "Benton", "Garrett"]


def test_the_line_names_the_exemption_the_check_uses():
    line = A.money_line({"money_events": []})
    where = f"Section {cc.MONEY_BLOCK_SECTION}'s {cc.MONEY_BLOCK_NAME} block"
    assert f"Quote no dollar figures outside {where}; a pot can be named without its amount." in line
    assert "anywhere" not in line
    assert f"(Checked: a dollar figure outside {where} this week is a claim-check finding.)" in line
    # one definition: the block the check exempts is the one the line names,
    # and the one the page's section is headed with
    assert cc.MONEY_BLOCK == cc.MONEY_BLOCK_NAME.lower()
    assert ST.MONEY_HEADER == cc.MONEY_BLOCK_NAME


def test_the_check_does_what_the_line_says():
    vocab = cc.Vocabulary(MGRS)
    inside = ("## **7. Power Rankings**\n\n**" + cc.MONEY_BLOCK_NAME + "**\n\n"
              "Garrett and Hayden would each pay $150 if the season ended today.\n")
    outside = "## **1. Matchup Summaries**\n\nHayden is on the hook for $150 right now.\n"
    assert cc.money_findings(inside, vocab, []) == []
    assert [f.token for f in cc.money_findings(outside, vocab, [])] == ["$150"]


def test_a_week_that_decided_money_is_unchanged():
    line = A.money_line({"money_events": [("clinched_title", "Nick")]})
    assert line.startswith("**Money this week:** Nick clinched the regular-season title.")
