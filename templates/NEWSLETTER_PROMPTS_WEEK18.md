# Newsletter Drafting Prompts — Week 18

Use these 3 prompts in a **separate LLM chat** (not this project chat). Upload the listed files with Part 1; they carry through to Parts 2 and 3 in the same chat.

---

## Pre-Flight Checklist ...

1. **Week 18, Feb 23–Mar 1, 2025-26**
2. **Key storylines:**
   - Nick survives Benton 1562.75–1547.70 despite being favored by 151.0 — a 15.05-point squeaker
   - Garrett crushes Hayden 1505.45–1165.25 by 340.20, covering the -308.0 spread by +32.20 — new season-best 3-game win streak
   - Luka Doncic wins POTW — 236.40 FP, 4 games, 59.10 FPPG (best game: 71.0 FP vs @PHX on 2/26)
   - **TITLE CLINCHED:** Nick wins the league title in Week 18 — title odds move 95.2% → 100.0% (Benton 4.8% → 0.0%)
   - **TITLE-SWINGING SUNDAY:** Benton’s lineup mistakes left enough points on the bench that an optimal Sunday would have flipped the matchup — and kept the title race alive
   - Standings: Nick 14-4 leads by 4 games over Benton 10-8 (Garrett 8-10, Hayden 4-14)
3. **Fantasy trade this week?** No — the season trade log remains at 5 total trades (last trade was Week 16)
4. **Current rosters** — included in Part 3 below

---

## PART 1 — Sections 1–4

**Files to upload:**
- `stats_report_week18.md`
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
1. **Nick wins the league title in Week 18 — and it comes down to 15.05 points** — Nick entered as a massive favorite (-151.0) but nearly got ambushed, surviving Benton 1562.75–1547.70. Luka Doncic (236.40 FP, 4 games) put the trophy on ice, while Benton countered with Derrick White (202.60 FP) and Cade Cunningham (195.90 FP). Season series now Nick 4, Benton 2. All-time: Nick 36, Benton 28.
2. **TITLE-SWINGING SUNDAY: Benton *had* the points to steal the week** — per the What If analysis, Benton’s optimal lineup would have flipped the matchup vs Nick (needed 15.0 points). If Benton sets Sunday correctly, Nick’s clinch gets pushed back and the title race stays alive.
3. **Garrett steamrolls Hayden 1505.45–1165.25, covering the -308.0 spread by +32.20** — Kevin Durant (186.95 FP), Victor Wembanyama (178.95), and Alperen Sengun (161.70) powered a 340.20-point blowout. Garrett extends his new season-best win streak to 3 (Weeks 16–18), chasing his personal all-time record of 7 (2021-22).
4. **The model locks in behind the clinch** — Nick sits 14-4 with a 4-game lead over Benton (10-8), and the simulation now has Nick at **100.0%** title odds (up from 95.2%).
5. **Luka Doncic wins POTW for the 3rd time this season** — 236.40 FP, 4 games, 59.10 FPPG, best game: 71.0 FP vs @PHX on 2/26. (Previous Doncic POTWs: Week 6, Week 15.)

### YOUR TASK — SECTIONS 1–4 ONLY


Write Sections 1–4 of the newsletter following the template's instructions for each section:
1. Matchup Summaries
2. Report Cards (ordered by letter grade descending — highest grade first — Total FP as tiebreaker)
3. Betting Lines
4. Player of the Week

Follow the extract→cite→write→clean workflow internally, but **output ONLY the final cleaned prose.** No extraction blocks, no citations, no working notes. Every number must come directly from the stats report — no rounding, no inventing.

Start with:
## **CHS Alumni Fantasy Basketball League — Week 18 Newsletter**
**Season 2025-26 | Week 18 (Feb 23 to Mar 1)**

Stop after Section 4. Present it as a downloadable file.
```

---

## PART 2 — Sections 5–8

**Files:** Same chat, no new files needed.

**Prompt:**

```
Continue the Week 18 Newsletter. Write **Sections 5–8** following the template's instructions for each section:

5. **Fun Facts** — Weave the fun_facts data into engaging prose bullets.

6. **What If** — Use what_if_analysis data. Key findings this week:
   - Benton left 49.4 points on the bench, and an optimal lineup would have flipped the matchup vs Nick (needed 15.0 points) — which would have **kept the title race alive**. Two blunders totaled 103.9 FP wasted (Bam Adebayo 36.0; Josh Giddey 68.0).
   - Hayden committed **4 blunders** totaling 174.8 FP wasted (Kevin Porter Jr., VJ Edgecombe, Scottie Barnes, Zion Williamson). Potential gain from optimal lineup: 26.6 points.
   - Garrett and Nick had clean lineup management (0 blunders).

7. **Power Rankings** — TWO tables required:
   - Narrative note: this is the **title-clinch week** — make it unmistakable that Nick has won the title (100.0% title odds; 100% 1st-place finish distribution).
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
Finish the Week 18 Newsletter. Write **Sections 9–10** and the closing line, following the template's instructions for each section.

### Section 9: Around the NBA

**No fantasy trades this week.** Skip the trade analysis headline.

**Search the web** for 3–5 real NBA headlines from **Feb 23 – Mar 1, 2026** that connect to rostered players. Good search topics:
— Injury updates for currently injured rostered players
— Standout performances by rostered players during that week
— Breaking news on rostered players

**Reminder:** When discussing returning players in prose, use natural language ("expected back Wednesday," "could return for 3 of 5 games"), NOT parenthetical shorthand like "(2/5 games)".

**Suggested searches (starting points):**
— "Anthony Davis hand injury update late February 2026"
— "Stephen Curry knee injury update February 2026"
— "Domantas Sabonis out for season update February 2026"
— "Trae Young quad injury update February 2026"
— "Donovan Mitchell groin injury update February 2026"
— "Devin Booker hip injury update February 2026"
— "Franz Wagner injury update February 2026"
— "Jalen Williams hamstring injury update February 2026"
— "Luka Doncic Lakers Suns February 26 2026"

**Current rosters for reference:**
- **Nick (17):** Amen Thompson, Anthony Davis, Anthony Edwards, Brandon Ingram, Brandon Miller, Chet Holmgren, Darius Garland, Deni Avdija, Jalen Duren, Jalen Johnson, Jalen Suggs, Karl-Anthony Towns, Luka Doncic, Myles Turner, OG Anunoby, Payton Pritchard, Ryan Rollins
- **Hayden (17):** De'Aaron Fox, Devin Booker, Franz Wagner, Jalen Williams, Kevin Porter Jr., Keyonte George, Kon Knueppel, LaMelo Ball, Lauri Markkanen, Mikal Bridges, Nikola Jokic, Paolo Banchero, Pascal Siakam, Scottie Barnes, Shai Gilgeous-Alexander, Tyrese Haliburton, VJ Edgecombe
- **Benton (17):** Bam Adebayo, Cade Cunningham, Derrick White, Desmond Bane, Donovan Mitchell, Evan Mobley, James Harden, Jarrett Allen, Jaylen Brown, Jayson Tatum, Josh Giddey, Julius Randle, LeBron James, Michael Porter Jr., Trae Young, Trey Murphy III, Tyrese Maxey
- **Garrett (17):** Alperen Sengun, Austin Reaves, Cooper Flagg, Domantas Sabonis, Donovan Clingan, Giannis Antetokounmpo, Jalen Brunson, Jamal Murray, Josh Hart, Jrue Holiday, Kawhi Leonard, Kevin Durant, Nikola Vucevic, Stephen Curry, Stephon Castle, Tyler Herro, Victor Wembanyama


### Section 10: Rumor Mill
Use the rumor_mill data from the stats report. Cover trade ideas, free agent targets, hot streaks, and slump watch per the template's instructions.

**CRITICAL for Section 10:**
— Check DRAFT PICK OWNERSHIP in the stats report before writing any trade involving picks
— Check the SEASON TRADE LOG — don't invent trade history
— Use trade_value_note language from the stats report for hot streaks
— There have been 5 trades this season (Weeks 7, 8, 14, 15, 16) — no trade this week

### Close the newsletter with:

---
**End of Week 18 Newsletter**

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

### 8. LOSING STREAK CLAIM
- Verify the "14-game losing streak to Nick" claim: the stats report says Garrett's H2H streak against Nick was 1 win (just broke the streak). The commissioner note says "Garrett breaks 14 game losing streak to Nick." Confirm this is referenced accurately and not confused with a general losing streak.

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
| Garbled date range | "Feb 9 → Feb 22" or "Feb 9 — Feb 22" | "Feb 9 to Feb 22" |
| Metadata headline | "Player of the Night - Jokic - Feb. 22" | "Jokic Erupts for 88.8 FP as Nuggets Torch Warriors" |
| Wrong trade history count | "1 all-time deal" (actually 3) | Verify against `trade_partners` data |
| H2H streak confusion | "14-game win streak" (it's a losing streak TO Nick that was broken) | "snapped a 14-game skid against Nick" |
