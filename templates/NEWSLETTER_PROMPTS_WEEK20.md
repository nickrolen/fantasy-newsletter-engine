# Newsletter Drafting Prompts — Week 20

Use these 3 prompts in a **separate LLM chat** (not this project chat). Upload the listed files with Part 1; they carry through to Parts 2 and 3 in the same chat.

---

## Pre-Flight Checklist ✓

1. **Week 20, Mar 9–15, 2025-26**
2. **Key storylines:**
   - **Hayden stuns Benton 1633.55–1560.55 as a massive +975 underdog (9% win prob)** — Benton was a -975 moneyline favorite with 90.70% win probability. Nikola Jokic (304.35 FP, 4 games, 76.09 FPPG) carried Hayden almost single-handedly. Benton's losing streak extends to 3 (Weeks 18–20). Season series: Hayden 3, Benton 4. All-time: Hayden 40, Benton 26.
   - **Nick beats Garrett 1910.20–1778.90 by 131.30** — Luka Doncic (234.55 FP, 3 games, 78.18 FPPG) with a monster 99.8 FP game vs CHI on 3/12. Jalen Johnson (161.90 FP) and Ryan Rollins (159.00 FP) contributed. Season series: Nick 6, Garrett 1. All-time: Nick 46, Garrett 20. Garrett's win streak snapped at 4.
   - **Nikola Jokic wins POTW for the 6th time this season** — 304.35 FP, 4 games, 76.09 FPPG, best game: 88.6 FP vs @SAS on 3/12. Previous Jokic POTWs: Weeks 3, 5, 10, 16, 17. POTW by manager this season: Hayden 7, Benton 5, Nick 5, Garrett 3.
   - **Standings locked: Nick 16-4, Benton 10-10, Garrett 9-11, Hayden 5-15** — All four finishing positions are now 100.0% locked. Nick's title (clinched Week 18) is secure. Benton has clinched 2nd place.
   - **Benton clinching 2nd means both the 1st AND 2nd overall picks in the 2026 draft belong to Hayden** — Hayden owns their own 1st-round pick (#1 overall, from finishing 4th) AND Garrett's 1st-round pick (#2 overall, from Garrett finishing 3rd — acquired in the Week 14 Curry/Edgecombe trade). This is a massive offseason haul for a team that endured the league's unluckiest season.
   - **Week 21 is the final regular season week — playoff seeding is locked** — The 21-week regular season ends next week. Playoff matchups are set: #1 Nick vs #4 Hayden, #2 Benton vs #3 Garrett. This newsletter should preview the playoff picture.
   - **Luka Doncic drops 99.8 FP vs CHI on 3/12** — The highest single-game score of Week 20, nearly cracking triple digits.
   - **All four managers had perfect lineup management** — Zero blunders, zero bench points left on the table across the board.
3. **Fantasy trade this week?** No — the season trade log remains at 5 total trades (last trade was Week 16)
4. **Current rosters** — included in Part 3 below

---

## PART 1 — Sections 1–4

**Files to upload:**
- `stats_report_week20.md`
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
| Nick | Luka my Balls | Luka Doncic, Anthony Edwards, Jalen Johnson |
| Hayden | Big Nik Energy | Nikola Jokic, Shai Gilgeous-Alexander, Paolo Banchero |
| Benton | Smaxey | Cade Cunningham, Donovan Mitchell, James Harden |
| Garrett | Saboner | Victor Wembanyama, Kawhi Leonard, Jalen Brunson |

### KEY STORYLINES (reference throughout)
1. **Hayden upsets Benton 1633.55–1560.55 as a +975 underdog** — Benton was a -975 moneyline favorite with 90.70% win probability. Nikola Jokic went nuclear: 304.35 FP, 4 games, 76.09 FPPG, with an 88.6 FP game vs @SAS on 3/12. Benton's losing streak extends to 3 (Weeks 18–20). Season series: Hayden 3, Benton 4. All-time: Hayden 40, Benton 26. Hayden leads the all-time series.
2. **Nick beats Garrett 1910.20–1778.90 by 131.30, snapping Garrett's 4-game win streak** — Luka Doncic (234.55 FP, 3 games, 78.18 FPPG) dropped a 99.8 FP game vs CHI on 3/12. Jalen Johnson (161.90 FP), Ryan Rollins (159.00 FP) contributed. Season series: Nick 6, Garrett 1. All-time: Nick 46, Garrett 20 (Nick has now won 46 of 66 all-time meetings, 70%). Garrett had the higher team FPPG (38.67 vs 38.20) but Nick had 4 more games played (50 vs 46). Garrett lost 8 games to injury.
3. **Nikola Jokic wins POTW for the 6th time this season (league-leading)** — 304.35 FP, 4 games, 76.09 FPPG. Best game: 88.6 FP vs @SAS on 3/12. Previous Jokic POTWs: Weeks 3, 5, 10, 16, 17. Hayden now has 7 POTWs this season (league-leading). POTW by manager: Hayden 7, Benton 5, Nick 5, Garrett 3.
4. **All four finishing positions are 100% locked** — Standings: Nick 16-4, Benton 10-10, Garrett 9-11, Hayden 5-15. Nick's 6-game lead over Benton is insurmountable. Title was clinched in Week 18. Benton has clinched 2nd place.
5. **Benton clinching 2nd means Hayden now owns both the 1st AND 2nd overall picks in the 2026 draft** — Hayden owns their own 1st-round pick (4th place = #1 overall) AND Garrett's 1st-round pick (3rd place = #2 overall, acquired in the Week 14 Curry/Edgecombe trade). Despite the league's unluckiest season (-4.3 luck index, worst of Hayden's career), the draft capital haul sets up a potentially league-altering offseason.
6. **Week 21 is the final regular season week — playoff seeding is now locked** — Matchups: #1 Nick vs #4 Hayden, #2 Benton vs #3 Garrett. The regular season finale next week doubles as a playoff preview.

### YOUR TASK — SECTIONS 1–4 ONLY

Write Sections 1–4 of the newsletter following the template's instructions for each section:
1. Matchup Summaries
2. Report Cards (ordered by letter grade descending — highest grade first — Total FP as tiebreaker)
3. Betting Lines
4. Player of the Week

Follow the extract→cite→write→clean workflow internally, but **output ONLY the final cleaned prose.** No extraction blocks, no citations, no working notes. Every number must come directly from the stats report — no rounding, no inventing.

Start with:
## **CHS Alumni Fantasy Basketball League — Week 20 Newsletter**
**Season 2025-26 | Week 20 (Mar 9 to Mar 15)**

Stop after Section 4. Present it as a downloadable file.
```

---

## PART 2 — Sections 5–8

**Files:** Same chat, no new files needed.

**Prompt:**

```
Continue the Week 20 Newsletter. Write **Sections 5–8** following the template's instructions for each section:

5. **Fun Facts** — Weave the fun_facts data into engaging prose bullets.

6. **What If** — Use what_if_analysis data. Key finding this week:
   - **All four managers had perfect lineup management.** Zero blunders, zero bench points across the board. Note clean lineup management for all managers.

7. **Power Rankings** — TWO tables required:
   - Narrative note: All four finishing positions are now 100.0% locked. Nick at 100.0% for 1st, Benton at 100.0% for 2nd, Garrett at 100.0% for 3rd, Hayden at 100.0% for 4th. The regular season race is over — the only drama left is playoff seeding (which is also locked: #1 Nick vs #4 Hayden, #2 Benton vs #3 Garrett).
   - **IMPORTANT: Mention that Benton clinching 2nd means Hayden now owns both the 1st AND 2nd overall picks in the 2026 draft** (Hayden's own pick from finishing 4th = #1 overall, plus Garrett's pick from finishing 3rd = #2 overall, acquired in the Week 14 Curry/Edgecombe trade). This is a major offseason storyline.
   - **IMPORTANT: Mention that Week 21 is the final regular season week and playoff seeding is locked.** Preview the playoff matchups: #1 Nick vs #4 Hayden, #2 Benton vs #3 Garrett.
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
Finish the Week 20 Newsletter. Write **Sections 9–10** and the closing line, following the template's instructions for each section.

### Section 9: Around the NBA

**No fantasy trades this week.** Skip the trade analysis headline.

**Search the web** for 3–5 real NBA headlines from **Mar 9 – Mar 15, 2026** that connect to rostered players. Good search topics:
— Injury updates for currently injured rostered players
— Standout performances by rostered players during that week
— Breaking news on rostered players

**Reminder:** When discussing returning players in prose, use natural language ("expected back Wednesday," "could return for 3 of 5 games"), NOT parenthetical shorthand like "(2/5 games)".

**Suggested searches (starting points):**
— "Anthony Davis hand injury update March 2026"
— "Stephen Curry knee injury update March 2026"
— "Domantas Sabonis out for season update March 2026"
— "Tyrese Maxey finger injury return March 2026"
— "Jarrett Allen knee injury return March 2026"
— "Lauri Markkanen hip injury update March 2026"
— "Nikola Jokic 88.6 FP Spurs March 12 2026"
— "Luka Doncic 99.8 FP Lakers Bulls March 12 2026"
— "Kawhi Leonard Clippers March 2026"
— "Pascal Siakam ankle return March 2026"

**Current rosters for reference:**
- **Nick (16):** Amen Thompson, Anthony Davis, Anthony Edwards, Brandon Ingram, Brandon Miller, Chet Holmgren, Dejounte Murray, Deni Avdija, Jalen Duren, Jalen Johnson, Jalen Suggs, Karl-Anthony Towns, Luka Doncic, Miles Bridges, Nickeil Alexander-Walker, Ryan Rollins
- **Hayden (17):** De'Aaron Fox, Devin Booker, Kevin Porter Jr., Kon Knueppel, LaMelo Ball, Lauri Markkanen, Matas Buzelis, Mikal Bridges, Nikola Jokic, Onyeka Okongwu, Paolo Banchero, Pascal Siakam, RJ Barrett, Scottie Barnes, Shai Gilgeous-Alexander, Stephon Castle, Tyrese Haliburton
- **Benton (17):** Bam Adebayo, Cade Cunningham, Derrick White, Desmond Bane, Donovan Mitchell, Evan Mobley, James Harden, Jarrett Allen, Jaylen Brown, Jayson Tatum, Josh Giddey, Julius Randle, LeBron James, Michael Porter Jr., Trae Young, Trey Murphy III, Tyrese Maxey
- **Garrett (17):** Alperen Sengun, Austin Reaves, Cooper Flagg, Domantas Sabonis, Donovan Clingan, Giannis Antetokounmpo, Immanuel Quickley, Jalen Brunson, Jamal Murray, Josh Hart, Kawhi Leonard, Kevin Durant, Kyle Filipowski, Rudy Gobert, Stephen Curry, Tyler Herro, Victor Wembanyama


### Section 10: Rumor Mill
Use the rumor_mill data from the stats report. Cover trade ideas, free agent targets, hot streaks, and slump watch per the template's instructions.

**CRITICAL for Section 10:**
— Check DRAFT PICK OWNERSHIP in the stats report before writing any trade involving picks
— Check the SEASON TRADE LOG — don't invent trade history
— Use trade_value_note language from the stats report for hot streaks
— There have been 5 trades this season (Weeks 7, 8, 14, 15, 16) — no trade this week
— **Reminder: Hayden now owns both the 1st and 2nd overall picks in the 2026 draft.** Factor this into any trade analysis or offseason positioning discussion.
— **Reminder: Week 21 is the final regular season week — playoff matchups are locked (#1 Nick vs #4 Hayden, #2 Benton vs #3 Garrett).** Trade ideas and roster moves should be framed in the context of playoff preparation.

### Close the newsletter with:

---
**End of Week 20 Newsletter**

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
- Garrett's current win streak was snapped at 4 this week — it was the season-best, NOT an all-time record
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

### 8. DRAFT PICK OWNERSHIP ACCURACY
- Verify that any mention of Hayden owning both the 1st and 2nd overall picks is accurate:
  - Hayden owns their own 1st-round pick (finishing 4th = #1 overall)
  - Hayden owns Garrett's 1st-round pick (finishing 3rd = #2 overall, acquired in the Week 14 Curry/Edgecombe trade)
- Verify that NO trade ideas suggest a manager trading a pick they no longer own

### 9. PLAYOFF SEEDING ACCURACY
- Verify playoff matchups are stated correctly: #1 Nick vs #4 Hayden, #2 Benton vs #3 Garrett
- Verify all finishing positions are described as 100.0% locked
- Flag any language suggesting the standings race is still live

### 10. GARRETT WIN STREAK
- Garrett's win streak was SNAPPED at 4 this week (Weeks 16–19). Nick beat Garrett in Week 20.
- Garrett's season-best win streak is 4 (Weeks 16–19). His personal all-time record is 7 (2021-22). The league record is 9.
- Flag any claim that Garrett's win streak is still active or that it reached 5+.

### 11. BENTON LOSING STREAK
- Benton has now lost 3 straight (Weeks 18–20). This is a new season-worst losing streak for Benton (tied with his season-best win streak of 3 from Weeks 3–5).
- Benton's all-time worst losing streak is 18 (2020-21).
- Flag any confusion about the streak length or any claims this is an all-time record.

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
| Garbled date range | "Mar 9 → Mar 15" or "Mar 9 — Mar 15" | "Mar 9 to Mar 15" |
| Metadata headline | "Player of the Night - Jokic - Mar. 12" | "Jokic Erupts for 88.6 FP as Nuggets Topple Spurs" |
| Wrong trade history count | "1 all-time deal" (actually 3) | Verify against `trade_partners` data |
| Garrett streak still active | "Garrett extends win streak to 5" | "Garrett's 4-game win streak was snapped by Nick" |
| Draft pick error | "Garrett owns his 1st-round pick" | "Garrett traded his 2026 1st to Hayden in Week 14" |
| Standings still live | "Benton fighting for 2nd" | "Benton has clinched 2nd at 100.0%" |
