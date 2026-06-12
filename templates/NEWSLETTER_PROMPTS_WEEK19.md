# Newsletter Drafting Prompts — Week 19

Use these 3 prompts in a **separate LLM chat** (not this project chat). Upload the listed files with Part 1; they carry through to Parts 2 and 3 in the same chat.

---

## Pre-Flight Checklist ...

1. **Week 19, Mar 2–8, 2025-26**
2. **Key storylines:**
   - Nick demolishes Hayden 1776.20–1333.85 by 442.35, covering the spread — season series now Nick 6, Hayden 1
   - Garrett beats Benton 1559.25–1341.40 by 217.85, extending his new season-best win streak to 4 (Weeks 16–19) — chasing his personal all-time record of 7 (2021-22)
   - Victor Wembanyama wins POTW — 241.65 FP, 4 games, 60.41 FPPG (best game: 79.0 FP vs DET on 3/5)
   - Standings: Nick 15-4 leads by 5 games over Benton 10-9 (Garrett 9-10, Hayden 4-15)
   - Benton committed 2 blunders (James Harden 25.4 FP, Trey Murphy III 44.7 FP) — left 138.5 points on the bench total, though it wouldn't have flipped the matchup
   - Payton Pritchard posts the new season-low single game: -3.7 FP vs CHA on 3/4
3. **Fantasy trade this week?** No — the season trade log remains at 5 total trades (last trade was Week 16)
4. **Current rosters** — included in Part 3 below

---

## PART 1 — Sections 1–4

**Files to upload:**
- `stats_report_week19.md`
- `newsletter_template.md`
- `LAST_WEEK_RECAP.md`
- `RECENT_CONTENT.json`
- `INJURY_OVERRIDES.json`

**Prompt:**

```
You are a seasoned sports editor writing the weekly newsletter for the **CHS Alumni Fantasy Basketball League**, a 4-team keeper league among college friends who've played together for 8+ years. Your writing should feel like ESPN or The Athletic — sharp, witty, and deeply informed by the league's history and rivalries.

### FILES
I've attached these files. **Read `newsletter_template.md` thoroughly before writing** — it contains section-by-section instructions, formatting rules, extraction schemas, and accuracy requirements. The Companion Files table at the top of the template explains what each file does.

### THE MANAGERS
| Manager | Team Name | Star Players |
|---------|-----------|-------------|
| Nick | Luka my Balls | Luka Doncic, Anthony Edwards, Karl-Anthony Towns |
| Hayden | Big Nik Energy | Nikola Jokic, Shai Gilgeous-Alexander, Paolo Banchero |
| Benton | Smaxey | Tyrese Maxey, Cade Cunningham, Donovan Mitchell |
| Garrett | Saboner | Victor Wembanyama, Kevin Durant, Jalen Brunson |

### KEY STORYLINES (reference throughout)
1. **Nick steamrolls Hayden 1776.20–1333.85 by 442.35** — Luka Doncic (225.55 FP, 4 games), Karl-Anthony Towns (170.45), and Anthony Edwards (161.45) powered the blowout. Hayden lost 10 games to injury (Jalen Williams 3, Kevin Porter Jr. 3, VJ Edgecombe 2, Keyonte George 1, SGA 1). Season series now Nick 6, Hayden 1. All-time: Nick 37, Hayden 27. Nick has won 6 straight against Hayden.
2. **Garrett extends his season-best win streak to 4 (Weeks 16–19), beating Benton 1559.25–1341.40 by 217.85** — Victor Wembanyama (241.65 FP), Tyler Herro (171.10), and Jalen Brunson (155.85) carried Garrett. Benton lost 6 games to injury and committed 2 blunders. Season series: Benton 4, Garrett 3. All-time: Benton 31, Garrett 33. Garrett chasing his personal all-time win streak record of 7 (2021-22).
3. **Victor Wembanyama wins POTW for the 2nd time this season** — 241.65 FP, 4 games, 60.41 FPPG, best game: 79.0 FP vs DET on 3/5. (Previous Wembanyama POTW: Week 1.) POTW by manager this season: Hayden 6, Benton 5, Nick 5, Garrett 3.
4. **Nick extends his lead to 5 games** — Standings: Nick 15-4, Benton 10-9, Garrett 9-10, Hayden 4-15. Title was already clinched in Week 18, but Nick keeps padding the lead.
5. **Payton Pritchard sets the new season-low single game: -3.7 FP** vs CHA on 3/4, breaking the previous record.

### YOUR TASK — SECTIONS 1–4 ONLY

Write Sections 1–4 of the newsletter following the template's instructions for each section:
1. Matchup Summaries
2. Report Cards (ordered by letter grade descending — highest grade first — Total FP as tiebreaker)
3. Betting Lines
4. Player of the Week

Follow the extract→cite→write→clean workflow internally, but **output ONLY the final cleaned prose.** No extraction blocks, no citations, no working notes. Every number must come directly from the stats report — no rounding, no inventing.

Start with:
## **CHS Alumni Fantasy Basketball League — Week 19 Newsletter**
**Season 2025-26 | Week 19 (Mar 2 to Mar 8)**

Stop after Section 4. Present it as a downloadable file.
```

---

## PART 2 — Sections 5–8

**Files:** Same chat, no new files needed.

**Prompt:**

```
Continue the Week 19 Newsletter. Write **Sections 5–8** following the template's instructions for each section:

5. **Fun Facts** — Weave the fun_facts data into engaging prose bullets.

6. **What If** — Use what_if_analysis data. Key findings this week:
   - Benton left 138.5 points on the bench and committed **2 blunders** totaling 70.1 FP wasted (James Harden 25.4 FP left on bench with open G slot on 3/3; Trey Murphy III 44.7 FP left on bench with open SF slot on 3/8). Even with an optimal lineup, Benton would NOT have flipped the matchup vs Garrett.
   - Garrett left 46.5 points on the bench (0 blunders) — would NOT have flipped.
   - Nick (0 blunders) and Hayden (0 blunders) had clean lineup management.

7. **Power Rankings** — TWO tables required:
   - Narrative note: the title was clinched in Week 18 — Nick at 100.0% title odds. The race for 2nd is live: Benton 93.64% for 2nd, Garrett 93.64% for 3rd. Hayden locked into 4th at 100.0%.
   - Table 1: Projected Finish Distribution (Team | 1st | 2nd | 3rd | 4th)
   - Table 2: Power Rankings (Rank | Team | Record | Title Odds | Trend)
   - Then 3–4 paragraphs of narrative.

8. **Stats Corner** — EIGHT tables required, in this order:
   1. Top Performances
   2. Worst Performances
   3. Best Performers — Total FP, This Season
   4. Best Performers — FPPG, This Season
   5. Worst Performers — Total FP, This Season
   6. Worst Performers — FPPG, This Season
   7. Waiver Pickups
   8. Top Available Free Agents
   - Additional tables (Positional Breakdown, Waiver ROI, Bench Report, Record Book, Keeper Watch, Draft Value Tracker) are rendered as interactive visualizations by the HTML generator, do NOT include them in the draft.
   - Then 3 or 4 sentences of commentary.

Same rules as Part 1: cleaned prose only, every number from the stats report. Present sections 5–8 as a downloadable file.
```

---

## PART 3 — Sections 9–10

**Files:** Same chat, no new files needed.

**Prompt:**

```
Finish the Week 19 Newsletter. Write **Sections 9–10** and the closing line, following the template's instructions for each section.

### Section 9: Around the NBA

**No fantasy trades this week.** Skip the trade analysis headline.

**Search the web** for 3–5 real NBA headlines from **Mar 2 – Mar 8, 2026** that connect to rostered players. Good search topics:
— Injury updates for currently injured rostered players
— Standout performances by rostered players during that week
— Breaking news on rostered players

**Reminder:** When discussing returning players in prose, use natural language ("expected back Wednesday," "could return for 3 of 5 games"), NOT parenthetical shorthand like "(2/5 games)".

**Suggested searches (starting points):**
— "Anthony Davis hand injury update March 2026"
— "Stephen Curry knee injury update March 2026"
— "Domantas Sabonis out for season update March 2026"
— "Nikola Vucevic out for season update March 2026"
— "Jalen Williams hamstring return March 2026"
— "Tyrese Maxey finger injury return March 2026"
— "Lauri Markkanen illness update March 2026"
— "Luka Doncic Lakers March 6 79.8 FP"
— "Victor Wembanyama 79 FP Spurs Pistons March 5 2026"

**Current rosters for reference:**
- **Nick (17):** Amen Thompson, Anthony Davis, Anthony Edwards, Brandon Ingram, Brandon Miller, Chet Holmgren, Darius Garland, Deni Avdija, Jalen Duren, Jalen Johnson, Jalen Suggs, Karl-Anthony Towns, Luka Doncic, Myles Turner, OG Anunoby, Payton Pritchard, Ryan Rollins
- **Hayden (17):** De'Aaron Fox, Devin Booker, Jalen Williams, Kevin Porter Jr., Keyonte George, Kon Knueppel, LaMelo Ball, Lauri Markkanen, Mikal Bridges, Nikola Jokic, Onyeka Okongwu, Paolo Banchero, Pascal Siakam, Scottie Barnes, Shai Gilgeous-Alexander, Tyrese Haliburton, VJ Edgecombe
- **Benton (17):** Bam Adebayo, Cade Cunningham, Derrick White, Desmond Bane, Donovan Mitchell, Evan Mobley, James Harden, Jarrett Allen, Jaylen Brown, Jayson Tatum, Josh Giddey, Julius Randle, LeBron James, Michael Porter Jr., Trae Young, Trey Murphy III, Tyrese Maxey
- **Garrett (17):** Alperen Sengun, Austin Reaves, Cooper Flagg, Domantas Sabonis, Donovan Clingan, Giannis Antetokounmpo, Isaiah Collier, Jalen Brunson, Jamal Murray, Josh Hart, Kawhi Leonard, Kevin Durant, Nikola Vucevic, Stephen Curry, Stephon Castle, Tyler Herro, Victor Wembanyama


### Section 10: Rumor Mill
Use the rumor_mill data from the stats report. Cover trade ideas, free agent targets, hot streaks, and slump watch per the template's instructions.

**CRITICAL for Section 10:**
— Check DRAFT PICK OWNERSHIP in the stats report before writing any trade involving picks
— Check the SEASON TRADE LOG — don't invent trade history
— Use trade_value_note language from the stats report for hot streaks
— There have been 5 trades this season (Weeks 7, 8, 14, 15, 16) — no trade this week

### Close the newsletter with:

---
**End of Week 19 Newsletter**

Same rules as Parts 1–2: cleaned prose only, every number from the stats report. Present sections 9–10 as a downloadable file.
```

---

## After Drafting -- Back in Project Chat

Once all 3 parts are generated:

1. **Combine** the three downloaded files into one full newsletter
1.5. **Scan the seams** — check that the transition between Part 1→Part 2 and Part 2→Part 3 doesn't have duplicate section headers, missing `---` separators, or formatting shifts.
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
- League record: 9 games (Benton 2017-18, Hayden 2022-23)
- Nick's personal record: 8 games (2020-21)
- Garrett's personal record: 7 games (2021-22)
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
- Check all Stats Corner table headers — they should NOT include row counts like "(5)" or "(30)"
- Check for duplicate section name headers (e.g., `**What If?**` appearing both as a section heading and as a standalone bold line inside the section)
- Check the title/subtitle date range uses "to" (not garbled characters, em dashes, or arrows)

### 7. AROUND THE NBA HEADLINES
- Every headline should read like a real sports news headline (ESPN-style), not a metadata label
- Flag any headline that looks like "Player of the [X] - [Name] - [Date]" format
- Headlines should be active and narrative: "Kawhi Drops 41 as Clippers Rout Wolves" not "Player of the Night - Kawhi Leonard - Feb. 8"

### 8. SEASON-LOW SINGLE GAME CLAIM
- Verify the -3.7 FP single game record: the stats report lists Payton Pritchard at -3.7 FP vs CHA on 3/4 as the new season-low single game. Confirm this is referenced accurately and not confused with other low performances.

### 9. GARRETT WIN STREAK
- Garrett's current win streak is 4 (Weeks 16–19), which is the new season-best. His personal all-time record is 7 (2021-22). The league record is 9.
- Flag any confusion between season-best, personal all-time, and league all-time streak records.

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
| Garbled date range | "Mar 2 → Mar 8" or "Mar 2 — Mar 8" | "Mar 2 to Mar 8" |
| Metadata headline | "Player of the Night - Wemby - Mar. 5" | "Wembanyama Erupts for 79.0 FP as Spurs Dismantle Pistons" |
| Wrong trade history count | "1 all-time deal" (actually 3) | Verify against `trade_partners` data |
| Win streak confusion | "all-time record of 4" (it's season-best, not all-time) | "new season-best win streak of 4, chasing his personal all-time record of 7" |
