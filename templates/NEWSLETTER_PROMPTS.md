<!-- BY HAND ONLY -->
# Newsletter Drafting Prompts -- Reusable Template

**The normal path is the script:** `python scripts\prepare_prompts.py --week N` (after Step 6.5) fills every placeholder below from the week's stats report and the config and writes `output\prompts_weekN.md`: the files to upload, then Parts 1, 2 and 3, ready to paste. Everything between `BY HAND ONLY` and its end marker is for filling this file by hand, the fallback (WEEKLY_WORKFLOW.md Step 7); the script replaces it with its own header.

Use these 3 prompts in a **separate LLM chat** (not this project chat). Upload the listed files with Part 1; they carry through to Parts 2 and 3 in the same chat.

By hand: fill in every `[FILL IN: ...]` placeholder before sending. A block that starts with an `[IF ...]` line and ends with `[END IF]` is conditional: keep or delete its contents as the condition says, and delete the `[IF ...]` and `[END IF]` lines either way.

---

## Pre-Flight Checklist

Before opening the drafting chat, pull these from the **stats report markdown** (`output\stats_report_weekN.md`) and the config:

1. **Week number, dates, and season** -- e.g., Week 16, Feb 2-8, 2025-26. Dates from `config\SCHEDULE.json`; the season from `config\league_config.json` (`season.current`).
2. **The league line** -- the number of teams (`managers` in the config) and the league's season as an ordinal word from `season.league_season_number` (12 is "twelfth"), never `data_era_season_number`.
3. **The manager table** -- every manager and his team name from the config (`manager_to_team`); his three star players are his top three in the stats report's keeper watch by keep chance (the report's own per-team rank).
4. **Key storylines** -- the stats report's ANGLES block, verbatim and in its order: the lead, the secondary angles, the standing threads, and the "Money this week" line. If it says NO LEAD THIS WEEK, that goes in as is. What the block ranks, for reference:
   - Matchup results (upsets? streaks extended/snapped? blowouts?)
   - Title odds shifts / magic number changes (magic numbers from the week 8 report on only)
   - POTW winner and notable stat lines
   - Milestones (career wins, records, first-time achievements)
   - Running threads from `LAST_WEEK_RECAP.md` that resolved or continued

   **Storyline templates (for reference, fill with specific numbers):**
   - **Upset/decisive win:** "[Manager] [beats/upsets] [Manager] [score]-[score] [as a +X underdog / covering the X-point spread]. [Key stat or streak implication]."
   - **Streak:** "[Manager] extends [win/loss] streak to [N]. [Context: record chase, season best, etc.]"
   - **Title race:** "[Manager]'s magic number drops to [N]. Title odds: [X]%." (Week 8 report on. Before that: "Title odds: [X]%." and no magic number.)
   - **POTW:** "[Player] wins POTW -- [FP] FP, [games] games, [FPPG] FPPG. [Manager] has won [N] straight POTWs / [N] total this season."
   - **Trade:** "[Manager A]-[Manager B] trade: [key pieces]. **All-time trade history: [N] deals between them** (verify against `trade_partners` data). First-ever / Nth trade between them this season."
5. **Fantasy trades this week?** -- Check the move ledger (`python scripts\ledger.py list`), the transaction log, and whether `data\weeklycontextinput_weekN.json` exists (it carries the picks).
6. **Current rosters** -- Copy all managers' rosters from `config\ROSTERS.json` for Part 3, marking each player in an IL slot (`data\IL_SLOTS.json`) "(IL)".
7. **The trade block** -- Copy each team's mode and listed players from `config\TRADE_BLOCK.json` for Part 3's Rumor Mill, each with the day it was set.

---
<!-- END BY HAND ONLY -->

## PART 1 -- Sections 1-4

**Files to upload:**
- `stats_report_week[FILL IN: N].md`
- `VOICE.md` *(who is speaking -- read it first)*
- `newsletter_template.md`
- `LAST_WEEK_RECAP.md`
- `RECENT_CONTENT.json`
- `INJURY_OVERRIDES.json`
- `lore_for_drafting.json` *(approved lore only -- the only source for history and reputations the stats report can't prove; template rule 21)*
[IF data\weeklycontextinput_weekN.json EXISTS, KEEP THIS LINE; OTHERWISE DELETE IT:]
- `weeklycontextinput_week[FILL IN: N].json` *(the week's context: trade details, picks included)*
[END IF]

**Prompt:**

```
Use only the files uploaded to this chat. Do not open any other file in my folder, and never `config/LEAGUE_LORE.json`.

You are writing the weekly newsletter for the **CHS Alumni Fantasy Basketball League**, a [FILL IN: number of teams]-team keeper league among CHS alumni, now in its [FILL IN: league season ordinal, e.g. twelfth] season. **Read `VOICE.md` first, then `newsletter_template.md`.** VOICE.md defines who is speaking; everything you write, in every section, is in that one voice.

### FILES
I've attached these files. **Read `newsletter_template.md` thoroughly before writing** -- it contains section-by-section instructions, formatting rules, extraction schemas, and accuracy requirements. The Companion Files table at the top of the template explains what each file does.

### THE MANAGERS
| Manager | Team Name | Star Players |
|---------|-----------|-------------|
[FILL IN: one row per manager: | Manager | Team Name | three star players |]

### KEY STORYLINES (reference throughout)
[FILL IN: the stats report's ANGLES block, verbatim]

**Money (template rule 23):** the block above ends with its "Money this week" line. If it says nothing was decided, the newsletter quotes no dollar figures except where that line allows. If it names what was decided, dollar figures belong to those lines only.

### YOUR TASK -- SECTIONS 1-4 ONLY
Write Sections 1-4 of the newsletter following the template's instructions for each section:
1. Matchup Summaries
2. Report Cards (ordered by `overall_score` descending, ties by `weekly_fp` -- the order `report_cards` arrives in; NOT by letter grade. Template, Section 2)
3. Betting Lines
4. Player of the Week

Follow the extract -> cite -> write -> clean workflow internally, but **output ONLY the final cleaned prose.** No extraction blocks, no citations, no working notes. Every number must come directly from the stats report -- no rounding, no inventing.

Start with:
## **CHS Alumni Fantasy Basketball League — Week [FILL IN: N] Newsletter**
**Season [FILL IN: YYYY-YY] | Week [FILL IN: N] ([FILL IN: Start Date] to [FILL IN: End Date])**

Stop after Section 4. Present it as a downloadable file.
```

---

## PART 2 -- Sections 5-8

**Files:** Same chat, no new files needed.

**Prompt:**

```
Use only the files uploaded to this chat. Do not open any other file in my folder, and never `config/LEAGUE_LORE.json`.

Continue the Week [FILL IN: N] Newsletter. Write **Sections 5-8** following the template's instructions for each section:

5. **Fun Facts** -- Weave the fun_facts data into engaging prose bullets.

6. **What If** -- Use what_if_analysis data. If no costly decisions >= 25 points, note clean lineup management.

7. **Power Rankings** -- TWO tables required:
   - Table 1: Projected Finish Distribution (Team | 1st | 2nd | 3rd | 4th)
   - Table 2: Power Rankings (Rank | Team | Record | Title Odds | Trend)
   - Then 3-4 paragraphs of narrative.

8. **Stats Corner** -- EIGHT tables required, in this order:
   1. Top Performances
   2. Worst Performances
   3. Best Performers -- Total FP, This Season
   4. Best Performers -- FPPG, This Season
   5. Worst Performers -- Total FP, This Season
   6. Worst Performers -- FPPG, This Season
   7. Waiver Pickups
   8. Top Available Free Agents
   - Additional tables (Positional Breakdown, Waiver ROI, Bench Report, Record Book, Keeper Watch, Draft Value Tracker) are rendered as interactive visualizations by the HTML generator, do NOT include them in the draft.
   - Then 3 or 4 sentences of commentary.

Same rules as Part 1: cleaned prose only, every number from the stats report. Present sections 5-8 as a downloadable file.
```

---

## PART 3 -- Sections 9-10

**Files:** Same chat, no new files needed.

**Prompt:**

```
Use only the files uploaded to this chat. Do not open any other file in my folder, and never `config/LEAGUE_LORE.json`.

Finish the Week [FILL IN: N] Newsletter. Write **Sections 9-10** and the closing line, following the template's instructions for each section.

### Section 9: Around the NBA

[IF FANTASY TRADES HAPPENED IN WEEK N, KEEP THIS BLOCK; OTHERWISE DELETE IT:]
**FIRST headline MUST cover the Week [FILL IN: N] trade:**
- [FILL IN: Manager A] sends: [FILL IN: players/picks sent]
- [FILL IN: Manager B] sends: [FILL IN: players/picks sent]
- Include a letter grade (A-F) for EACH manager analyzing fairness.
[END IF]

**Then search the web** for 3-5 real NBA headlines from **[FILL IN: Week N start date] to [FILL IN: Week N end date]** that connect to rostered players. Good search topics:
- Injury updates for currently injured rostered players
- NBA trade deadline rumors (if near the deadline)
- Standout performances by rostered players during that week
- Breaking news on rostered players

**Current rosters for reference** (players in an IL slot are marked "(IL)"):
[FILL IN: every manager's roster from config/ROSTERS.json, all players listed, IL-slot players marked (IL) from data/IL_SLOTS.json]

### Section 10: Rumor Mill
**The trade block** (what each manager told Nick and the hub shows: his mode, his untouchables and the players he has on the block, each with the day it was set):
[FILL IN: the trade block from config/TRADE_BLOCK.json, one line per team with its mode and listed players and the day each was set]

The Rumor Mill may cite the trade block as what that manager has said, with its date. It is the managers' own word, not a rumor and not advice.

Use the rumor_mill data from the stats report. Cover trade ideas, free agent targets, hot streaks, and slump watch per the template's instructions. Cover only what the stats report has: an empty list gets no subsection.

**The advice is off** until the new engine ships: the stats report's Section 10 says only "The advice returns with the new engine." The page prints that line itself; don't retype it and write no advice (trade finder, waiver plans) of your own. If you mention the advice, use that sentence word for word.

**CRITICAL for Section 10:**
- Check DRAFT PICK OWNERSHIP in the stats report before writing any trade involving picks
- Check the SEASON TRADE LOG -- don't invent trade history
- Use trade_value_note language from the stats report for hot streaks

### Close the newsletter with:

---
**End of Week [FILL IN: N] Newsletter**

Same rules as Parts 1-2: cleaned prose only, every number from the stats report. Present sections 9-10 as a downloadable file.
```

---

## After Drafting -- Back in Project Chat

Once all 3 parts are generated:

1. **Combine** the three downloaded files into one full newsletter
1.5. **Scan the seams** -- check that the transition between Part 1 -> Part 2 and Part 2 -> Part 3 doesn't have duplicate section headers, missing `---` separators, or formatting shifts.
2. **Run verification** -- see checklist below
3. **Generate HTML** -- run `newsletter_html_generator.py`
4. **Update LAST_WEEK_RECAP.md** -- ask LLM to generate it from the finalized draft
5. **Update RECENT_CONTENT.json** -- ask LLM to append this week's headlines/openers

---

## VERIFICATION CHECKLIST (Run After Combining Draft)

Upload the combined draft and ask LLM to check for these specific error patterns that have occurred in the past:

### Prompt for Verification:
```
Use only the files uploaded to this chat. Do not open any other file in my folder, and never `config/LEAGUE_LORE.json`.

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
- Every headline is in the newsletter's own voice (VOICE.md): plain and specific, the league's stake first -- not a news-wire or ESPN-style headline, and not a metadata label
- Flag any headline that looks like "Player of the [X] - [Name] - [Date]" format, or that switches register from the rest of the newsletter

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
| Garbled date range | "Feb 2 – Feb 8" or "Feb 2 -- Feb 8" | "Feb 2 to Feb 8" |
| Metadata headline | "Player of the Night - Kawhi - Feb. 8" | "Kawhi Drops 41 as Clippers Rout Wolves" |
| Wrong trade history count | "1 all-time deal" (actually 3) | Verify against `trade_partners` data |
