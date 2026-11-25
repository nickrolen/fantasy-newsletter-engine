"""newsletter_shape.py -- the newsletter's 4d shape, in one place
(claude/HANDOFF_4D_NEWSLETTER_TEMPLATE_2026-11-25.md; NEWSLETTER_REVIEW
2026-11-25). The issue is the story of the week, published Monday night;
the hub carries the live numbers.

Read by scripts/format_stats_report.py (what the drafter is handed),
scripts/newsletter_html_generator.py (how the pointer lines render) and the
tests that pin templates/newsletter_template.md and the prompts to this
shape. One definition, so the template, the report and the page cannot
drift.
"""

from __future__ import annotations

# The line that closes each Betting Lines matchup (decision 5: the shortened
# Betting Lines are the issue's whole look-ahead; starts, light days and
# injuries live on the hub's Next week page). The HTML generator renders a
# line starting with HUB_POINTER_LEAD as <div class="hub-pointer">, not a <p>,
# so 48a's archive parser (modules/hub_matchups.py), which reads a matchup's
# <p>s as Monday's paragraph, never shows it on the hub itself.
HUB_POINTER_LEAD = "**On the hub:**"
NEXT_WEEK_POINTER = (f"{HUB_POINTER_LEAD} starts, light days and injuries for this matchup "
                     "are on the Next week page.")
# Rumor Mill's optional last line, where free agent targets used to be.
ADVICE_POINTER = f"{HUB_POINTER_LEAD} free-agent targets for every team are on the Advice page."

# Betting Lines: two or three sentences on what decides each matchup.
BETTING_SENTENCES = (2, 3)

# What left the issue: the formatted .md's headings. The JSON report still
# computes all of it (the hub reads it; Step 9 still writes the keepability
# snapshot). A test keeps every one out of the .md.
CUT_MD_HEADINGS = (
    "**Projected Finish Distribution:**",          # s.7 -> the hub's Money view
    "**MONEY AND EXPOSURE -- FACTS**",             # s.7 -> the hub's Money view
    "**Season Best -> Total FP:**",                # s.8 -> the hub's Players
    "**Season Best -> FPPG:**",
    "**Season Worst -> Total FP:**",
    "**Season Worst -> FPPG:**",
    "**Top Available Free Agents:**",              # s.8 -> the hub's Market
    "**KEEPER WATCH -- SUMMARY FACTS**",           # s.8, cut (Nick, 11-25)
    "**Free Agent Targets:**",                     # s.10 -> the hub's Advice
)

# The drafted issue's tables, per section, as the template requires them.
SECTION_TABLES = {
    7: ("Power Rankings",),
    8: ("Top Performances", "Worst Performances", "Waiver Pickups"),
}

# The drafted issue's bold headings that left with 4d. The HTML generator's
# main() refuses a draft carrying one (check_cut_blocks), as it refuses a
# draft missing a section: a cut block would otherwise render as a normal
# heading and paragraphs (a weekly dollar block, a keeper paragraph).
CUT_DRAFT_HEADINGS = (
    "Projected Finish Distribution",
    "Money and Exposure",
    "Best Performers",
    "Worst Performers",
    "Season Best",
    "Season Worst",
    "Top Available Free Agents",
    "Keeper Watch",
    "Free Agent Targets",
)

# The Keeper Watch panel left the issue (Nick, 11-25). The newsletter's player
# cards opened only from that panel, so with it off they are not built either
# (nothing on the page could open one). Kept as a switch, not deleted: the
# panel, its cards and their tests still exist for the day it comes back.
KEEPER_WATCH_IN_ISSUE = False
