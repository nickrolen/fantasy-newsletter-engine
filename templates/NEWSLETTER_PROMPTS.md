# Newsletter Drafting Prompts " Reusable Template

Use these 3 prompts in a **separate LLM chat** (not this project chat). Upload the listed files with Part 1; they carry through to Parts 2 and 3 in the same chat.

Fill in all `[FILL IN]` placeholders before sending. Lines starting with `[IF ... ]` are conditional " include or delete the block based on the condition.

---

## Pre-Flight Checklist

Before opening the drafting chat, pull these from the **stats report markdown**:

1. **Week number, dates, and season** " e.g., Week 16, Feb 2"8, 2025-26
2. **Key storylines (3"5 bullets)** " The big narratives. Check:
   - Matchup results (upsets? streaks extended/snapped? blowouts?)
   - Title odds shifts / magic number changes
   - POTW winner and notable stat lines
   - Milestones (career wins, records, first-time achievements)
   - Running threads from `LAST_WEEK_RECAP.md` that resolved or continued
   
   **Storyline templates (pick 3-5, fill with specific numbers):**
   - **Upset/decisive win:** "[Manager] [beats/upsets] [Manager] [score]-[score] [as a +X underdog / covering the X-point spread]. [Key stat or streak implication]."
   - **Streak:** "[Manager] extends [win/loss] streak to [N]. [Context: record chase, season best, etc.]"
   - **Title race:** "[Manager]'s magic number drops to [N]. Title odds: [X]%."
   - **POTW:** "[Player] wins POTW -- [FP] FP, [games] games, [FPPG] FPPG. [Manager] has won [N] straight POTWs / [N] total this season."
   - **Trade:** "[Manager A]-[Manager B] trade: [key pieces]. **All-time trade history: [N] deals between them** (verify against `trade_partners` data). First-ever / Nth trade between them this season."
3. **Fantasy trades this week?** " Check if `weeklycontextinput_weekN.json` exists
4. **Current rosters** " Copy all 4 managers' rosters from ROSTERS.json for Part 3

---

## PART 1 " Sections 1"4

**Files to upload:**
- `stats_report_weekN.md`
- `newsletter_template.md`
- `LAST_WEEK_RECAP.md`
- `RECENT_CONTENT.json`
- `INJURY_OVERRIDES.json`
- `weeklycontextinput_weekN.json` *(only if fantasy trades happened this week)*

**Prompt:**

```
You are a seasoned sports editor writing the weekly newsletter for the **CHS Alumni Fantasy Basketball League**, a 4-team keeper league among college friends who've played together for 8+ years. Your writing should feel like ESPN or The Athletic " sharp, witty, and deeply informed by the league's history and rivalries.

### FILES
I've attached these files. **Read `newsletter_template.md` thoroughly before writing** " it contains section-by-section instructions, formatting rules, extraction schemas, and accuracy requirements. The Companion Files table at the top of the template explains what each file does.

### THE MANAGERS
| Manager | Team Name | Star Players |
|---------|-----------|-------------|
| Nick | Luka my Balls | Luka Doncic, Anthony Edwards, Karl-Anthony Towns |
| Hayden | Big Nik Energy | Nikola Jokic, Shai Gilgeous-Alexander, Paolo Banchero |
| Benton | Smaxey | Tyrese Maxey, Cade Cunningham, Donovan Mitchell |
| Garrett | Saboner | Victor Wembanyama, Kevin Durant, Jalen Brunson |

### KEY STORYLINES (reference throughout)
[FILL IN: 3"5 numbered storylines with specific numbers from the stats report. Examples:]
[1. **Nick upsets Benton 2037.45"1807.05 as a +140 underdog** " Win streak now 6. Luka went nuclear: 261.70 FP.]
[2. **Hayden FINALLY reaches 100 career wins** " Stuck at 99 since Week 9. Give this the big payoff it deserves.]
[3. **Nick's magic number drops to 4** " Title odds: Nick 89.1%, Benton 10.9%.]
[4. **Luka Doncic wins POTW** " 261.70 FP, 4 games, 65.42 FPPG. Nick has won 3 straight POTWs.]

### YOUR TASK " SECTIONS 1"4 ONLY
Write Sections 1"4 of the newsletter following the template's instructions for each section:
1. Matchup Summaries
2. Report Cards (ordered by letter grade descending -- highest grade first -- Total FP as tiebreaker)
3. Betting Lines
4. Player of the Week

Follow the extract'cite'write'clean workflow internally, but **output ONLY the final cleaned prose.** No extraction blocks, no citations, no working notes. Every number must come directly from the stats report " no rounding, no inventing.

Start with:
## **CHS Alumni Fantasy Basketball League ' Week [FILL IN: N] Newsletter**
**Season [FILL IN: YYYY-YY] | Week [FILL IN: N] ([FILL IN: Start Date] to [FILL IN: End Date])**

Stop after Section 4. Present it as a downloadable file.
```

---

## PART 2 " Sections 5"8

**Files:** Same chat, no new files needed.

**Prompt:**

```
Continue the Week [FILL IN: N] Newsletter. Write **Sections 5"8** following the template's instructions for each section:

5. **Fun Facts** " Weave the fun_facts data into engaging prose bullets.

6. **What If** " Use what_if_analysis data. If no costly decisions >= 25 points, note clean lineup management.

7. **Power Rankings** " TWO tables required:
   - Table 1: Projected Finish Distribution (Team | 1st | 2nd | 3rd | 4th)
   - Table 2: Power Rankings (Rank | Team | Record | Title Odds | Trend)
   - Then 3"4 paragraphs of narrative.

8. **Stats Corner**  EIGHT tables required, in this order:
   1. Top Performances
   2. Worst Performances
   3. Best Performers  Total FP, This Season
   4. Best Performers  FPPG, This Season
   5. Worst Performers  Total FP, This Season
   6. Worst Performers  FPPG, This Season
   7. Waiver Pickups
   8. Top Available Free Agents
   - Additional tables (Positional Breakdown, Waiver ROI, Bench Report, Record Book, Keeper Watch, Draft Value Tracker) are rendered as interactive visualizations by the HTML generator, do NOT include them in the draft.
   - Then 3 or 4 sentences of commentary.

Same rules as Part 1: cleaned prose only, every number from the stats report. Present sections 5"8 as a downloadable file.
```

---

## PART 3 " Sections 9"10

**Files:** Same chat, no new files needed.

**Prompt:**

```
Finish the Week [FILL IN: N] Newsletter. Write **Sections 9"10** and the closing line, following the template's instructions for each section.

### Section 9: Around the NBA

[IF FANTASY TRADES HAPPENED THIS WEEK, INCLUDE THIS BLOCK:]
**FIRST headline MUST cover the Week [N] trade:**
' [FILL IN: Manager A] sends: [FILL IN: players/picks sent]
' [FILL IN: Manager B] sends: [FILL IN: players/picks sent]
' Include a letter grade (A"F) for EACH manager analyzing fairness.
[IF NO FANTASY TRADES THIS WEEK, DELETE THE BLOCK ABOVE.]

**Then search the web** for 3"5 real NBA headlines from **[FILL IN: Week N start date] " [FILL IN: Week N end date]** that connect to rostered players. Good search topics:
' Injury updates for currently injured rostered players
' NBA trade deadline rumors (if near the deadline)
' Standout performances by rostered players during that week
' Breaking news on rostered players

**Current rosters for reference:**
[FILL IN: Copy full rosters from ROSTERS.json " all 4 managers with all players listed]

### Section 10: Rumor Mill
Use the rumor_mill data from the stats report. Cover trade ideas, free agent targets, hot streaks, and slump watch per the template's instructions.

**CRITICAL for Section 10:**
' Check DRAFT PICK OWNERSHIP in the stats report before writing any trade involving picks
' Check the SEASON TRADE LOG " don't invent trade history
' Use trade_value_note language from the stats report for hot streaks

### Close the newsletter with:

---
**End of Week [FILL IN: N] Newsletter**

Same rules as Parts 1"2: cleaned prose only, every number from the stats report. Present sections 9"10 as a downloadable file.
```

---

## After Drafting -- Back in Project Chat

Once all 3 parts are generated:

1. **Combine** the three downloaded files into one full newsletter
1.5. **Scan the seams** -- check that the transition between Part 1->Part 2 and Part 2->Part 3 doesn't have duplicate section headers, missing `---` separators, or formatting shifts.
2. **Run verification** -- see checklist below
3. **Generate HTML** -- run `newsletter_html_generator.py`
4. **Update LAST_WEEK_RECAP.md** -- ask LLM to generate it from the finalized draft
5. **Update RECENT_CONTENT.json** -- ask LLM to append this week's headlines/openers

---

## VERIFICATION CHECKLIST (Run After Combining Draft)

Upload the combined draft and ask LLM to check for these specific error patterns that have occurred in the past:

### Prompt for Verification:
```
Review this newsletter draft for the following specific error patterns. For each category, quote any problematic sentences and provide the correction:

### 1. HEAD-TO-HEAD RECORD INTERPRETATION
Find every sentence with a head-to-head record (e.g., "25-39", "36-27"). 
- In "Manager A leads Manager B 36-27", the FIRST number (36) is A's wins, SECOND (27) is B's wins
- Flag any sentence where the language (dominated, leads, trails) doesn't match who actually has more wins
- Example error: "Benton has dominated Hayden 25-39" -- this says Benton has 25 wins, Hayden has 39, so Hayden has dominated Benton

### 2. WIN STREAK RECORDS -- PERSONAL VS LEAGUE
Find every mention of "all-time record" for win streaks.
- [verify league record and per-manager personal records from `all_time_records.longest_win_streaks` in the stats report -- do NOT hardcode]
- Flag any ambiguous "all-time record" that doesn't specify personal vs league

### 3. TRADE GRADE DIRECTION
For any trade graded in the newsletter:
- Identify who SENT higher-value picks and who RECEIVED them
- Flag if the grade narrative says someone "gained draft capital" when they actually sent the better picks

### 4. SUPERLATIVE CLAIMS WITHOUT VERIFICATION
Flag any "best/worst/most/least in league history" or "first time ever" claims.
- Can this be verified from the stats report data?
- If not verifiable, suggest changing to "one of the best/worst" or "among the most"

### 5. EFFICIENCY RATING CLAIMS
Flag any "best/worst efficiency of the season" claims -- we don't track weekly efficiency history, so these can't be verified.

### 6. FORMATTING CONSISTENCY
- Check all Stats Corner table headers -- they should NOT include row counts like "(5)" or "(30)"
- Check for duplicate section name headers (e.g., `**What If?**` appearing both as a section heading and as a standalone bold line inside the section)
- Check the title/subtitle date range uses "to" (not garbled characters, em dashes, or arrows)

### 7. AROUND THE NBA HEADLINES
- Every headline should read like a real sports news headline (ESPN-style), not a metadata label
- Flag any headline that looks like "Player of the [X] - [Name] - [Date]" format
- Headlines should be active and narrative: "Kawhi Drops 41 as Clippers Rout Wolves" not "Player of the Night - Kawhi Leonard - Feb. 8"

List all issues found with quoted text and corrections.
```

### Common Fixes Reference:
| Error Pattern | Example | Fix |
|--------------|---------|-----|
| Record backwards | "dominated Hayden 25-39" | "trails Hayden 25-39" |
| Ambiguous record | "all-time record of 8" | "personal all-time record of 8" |
| Trade direction | "acquired premium picks" (but sent 3rd, got 8th) | "traded down in draft capital" |
| Unverifiable superlative | "worst efficiency of the season" | "a rare underperformance" |
| Row counts in headers | "Top Performances (5)" | "Top Performances" |
| Duplicate section header | `**What If?**` inside `### **8. What If**` | Remove the standalone bold line |
| Garbled date range | "Feb 2 " Feb 8" or "Feb 2 -- Feb 8" | "Feb 2 to Feb 8" |
| Metadata headline | "Player of the Night - Kawhi - Feb. 8" | "Kawhi Drops 41 as Clippers Rout Wolves" |
| Wrong trade history count | "1 all-time deal" (actually 3) | 