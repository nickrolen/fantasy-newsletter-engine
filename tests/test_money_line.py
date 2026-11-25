"""The money line must not contradict the claim check's money rule
(claude/HANDOFF_SECTION10_OFF_AND_BUDGET_WEEK_2026-11-02.md part 4).

In a week where no money was decided, angles.money_line used to tell the
drafter "Quote no dollar figures anywhere in the newsletter", while the claim
check exempts Section 7's Money and Exposure block (claim_check.MONEY_BLOCK)
and the template puts dollar figures there every week. The week 2 drafter
caught it, and the line named the exemption. 4d moved the block to the hub:
no exemption, and the line says "anywhere" again.
"""
from modules import angles as A
from modules import claim_check as cc
from modules import standing_threads as ST

MGRS = ["Nick", "Hayden", "Benton", "Garrett"]


def test_the_line_says_anywhere_now_there_is_no_block():
    """4d (NEWSLETTER_REVIEW 11-25): Money and Exposure moved to the hub, so
    the 11-02 exemption went with it and "anywhere" is true again."""
    line = A.money_line({"money_events": []})
    assert "Quote no dollar figures anywhere in the issue; a pot can be named without its amount." in line
    assert "(Checked: a dollar figure this week is a claim-check finding.)" in line
    assert "outside" not in line and not hasattr(cc, "MONEY_BLOCK")


def test_the_check_does_what_the_line_says():
    vocab = cc.Vocabulary(MGRS)
    inside = ("## **7. Power Rankings**\n\n**Money and Exposure**\n\n"
              "Garrett and Hayden would each pay $150 if the season ended today.\n")
    outside = "## **1. Matchup Summaries**\n\nHayden is on the hook for $150 right now.\n"
    assert [f.token for f in cc.money_findings(inside, vocab, [])] == ["$150"]     # 4d: no exemption
    assert [f.token for f in cc.money_findings(outside, vocab, [])] == ["$150"]


def test_a_week_that_decided_money_is_unchanged():
    line = A.money_line({"money_events": [("clinched_title", "Nick")]})
    assert line.startswith("**Money this week:** Nick clinched the regular-season title.")
