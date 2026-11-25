# CHS Alumni Fantasy Basketball Newsletter -> Writing Guide & Reference Manual

This is the **reference manual** for writing the weekly CHS Alumni Fantasy Basketball Newsletter. It contains section-by-section instructions, formatting rules, extraction schemas, and accuracy requirements.

The **drafting prompt** (sent separately) provides week-specific context: storylines, matchup results, and task scope. This template and that prompt work as a pair " the prompt tells you *what happened this week*, this template tells you *how to write about it*.

---

## COMPANION FILES

These files are provided alongside the stats report during drafting. Each serves a specific purpose:

| File | Purpose |
|------|---------|
| `VOICE.md` | **Who is speaking.** Read it first; every section is in that one voice. |
| `lore_for_drafting.json` | Approved lore: the only source for history, habits and reputations the stats report can't prove (rule 21). Every entry in it is sayable; nothing else is. |
| `stats_report_weekN.md` | **Single source of truth.** Every number in the newsletter must come from this file. |
| `newsletter_template.md` | This file. Section-by-section writing guide and formatting rules. |
| `LAST_WEEK_RECAP.md` | Last week's storylines, grades, and callbacks. Use for **narrative continuity** " continue running threads, follow up on "Looking Ahead" items, avoid repeating last week's angles or phrasing. |
| `RECENT_CONTENT.json` | Headlines and section openers from recent weeks. **Do NOT reuse any of these** " find fresh angles. |
| `INJURY_OVERRIDES.json` | Source of truth for injury durations and return timelines. Use for "X has been out since..." or "expected back in ~Y weeks" claims. |
| `weeklycontextinput_weekN.json` | *(Only present if fantasy trades occurred this week.)* Trade details for Around the NBA section. |

---

## -> MANDATORY WORKFLOW: EXTRACT -> CITE -> WRITE -> CLEAN

**This workflow is NON-NEGOTIABLE. Skipping steps causes hallucinations.**

### Step 1: EXTRACT
Before writing ANY section, you MUST extract the relevant data from `stats_report_weekN.md` into a structured format.

### Step 2: CITE
When writing prose, include inline citations for EVERY stat: `[from extraction: X]`

Example:
```
Nick's magic number is 7 [from extraction: Magic Number: 7] -> any combination of Nick wins and Benton losses totaling 7 clinches.
```

### Step 3: WRITE
Write the prose with all citations visible.

### Step 4: CLEAN
Remove all `[from extraction: ...]` citations to produce the final version.

**NOTE:** The drafting prompt will specify whether to show extraction blocks or output only cleaned prose. When the prompt says "output ONLY the final cleaned prose," still follow Steps 1-3 internally " just don't include extraction blocks or citations in your output. The internal process prevents hallucinations even when the output is clean.

**WHY THIS MATTERS:** Without extraction, you WILL hallucinate stats. You'll confuse career records, invent streaks, and attribute stats to wrong players. The extraction step forces you to look at the actual data before writing.

---

## CRITICAL RULES

1. **NEVER write a stat that wasn't extracted** -> If it's not in your extraction, it doesn't exist
2. **NEVER improvise numbers** -> "Lost by around 100" is WRONG. "Lost by 97.35" is RIGHT.
3. **NEVER guess player teams or managers** -> Verify against rosters data
4. **If data is missing, say so** -> "Data not available" is better than fabrication
5. **When in doubt, leave it out** -> An accurate newsletter with fewer details beats a fabricated one
6. **NO REPETITION across sections** - If you list detailed injury breakdowns (e.g., "Deni Avdija (3), Quickley (2), Nembhard (1)...") in Matchup Summaries, do NOT repeat the same list in Report Cards. Instead, reference it generally: "the 9 games lost to injury" or "his injury-plagued week". The newsletter should flow, not repeat itself.
7. **RESPECT TIME BOUNDARIES** - The newsletter covers Week N (completed) and previews Week N+1 (upcoming). Matchup Summaries and Report Cards use PAST tense (what happened). Betting Lines and injury previews use FUTURE tense (what's coming). If web search returns news from after Week N ended, frame it as upcoming, not as already happened.
8. **GAME COUNTING DEFINITIONS** - These terms have specific meanings:
   - **Scheduled games** = LINEUPS rows with `nba_opponent` + `fantasy_points` value + slot != IL
   - **Games played** = PLAYERLOG rows where `started=TRUE` and `is_injured=FALSE`
   - **Games lost to injury** = LINEUPS rows with `nba_opponent` + `fantasy_points=0.0` + slot != IL
   - **Games left on bench** = LINEUPS rows with `fantasy_points > 0` + slot in {BN, IL+}
   - **Blunders** = Subset of games left on bench where a starter slot was available (empty or occupied by a DNP player). Represents manager negligence, not unavoidable overflow. Blunder value = the bench player's full FP (not a swap differential).
   - **The math:** Scheduled = Games Played + Games Lost to Injury + Games Left on Bench
9. **EFFICIENCY != INJURIES** - Efficiency measures how well healthy players performed vs projections (actual FP / projected FP). Injuries affect total FP by reducing games played. These are SEPARATE facts. Never say injuries "hurt" or "tanked" efficiency -- that conflates two different things.
10. **INJURY GAME COUNTING GLOSSARY (CRITICAL -- read before writing ANY injury stat):**

   These six terms have SPECIFIC, NON-OVERLAPPING definitions. Using the wrong one causes confusion:

   | Term | Definition | Source Field | Example |
   |------|-----------|-------------|---------|
   | **Games lost to injury** | Games where a starter-slot player had an opponent but scored 0.0 FP (slot != IL) | `non_il_injury_games` / `games_lost_to_injury` | "Hayden has lost 116 games to injury this season" |
   | **IL games** | Total games logged in the IL slot (both injured and healthy -- the slot itself) | `il_injury_games` | "compounded by 89 IL games, with Haliburton's 49 leading the way" |
   | **Total injury games** | Games lost to injury + IL games (the combined count across all slots) | `total_injury_games` | "Hayden has dealt with 205 total injury games this season -- 116 in starter slots and 89 in IL" |
   | **Games left on bench** | Games where a BN/IL+ slot player scored > 0 FP (healthy production wasted) | `games_left_on_bench` | "left 5 games on the bench this week" |
   | **Blunders** | Subset of bench games where a starter slot was available (empty or DNP starter). Pure manager negligence. | `blunders` / `blunder_points` | "2 blunders (54.5 FP wasted) -- Zion and Knueppel left on the bench with open slots" |
   | **Season injury burden %** | (All injuries across ALL slots / all scheduled games) x 100 -- includes both non-IL and IL | `total_injury_burden_pct` | "24.9% season injury burden" |

   **RULES FOR PROSE:**
   - When citing a raw game count alongside the burden %, default to **Games lost to injury** (the non-IL number): "Hayden's 24.9% season injury burden (116 games lost to injury)"
   - IL games are mentioned SEPARATELY as additional context: "compounded by 89 IL games with Haliburton's 49 leading the way"
   - **Total injury games** CAN be used when you want to convey the full combined picture, but MUST be called "total injury games" -- NEVER just "games lost" or "games lost to injury": "Hayden has dealt with 205 total injury games this season -- 116 in starter slots and 89 in IL"
   - NEVER label the combined number as just "games lost to injury" -- that term is reserved for the non-IL count only
   - **Games left on bench** is about roster management, NOT injuries -- it belongs in Report Cards and What If, not injury discussions
   - **Blunders** are the most egregious subset of bench games -- they belong in Report Cards (as a penalty explanation) and What If (with specific player/slot details). When a manager has blunders, always call them out by name: "left Zion on the bench with an open F slot"

11. **INJURY TIMELINES -> PROSE, NOT PARENTHESES (applies to ALL sections):** When discussing injured players and their return timelines anywhere in the newsletter, write in natural prose. NEVER use parenthetical shorthand like "(2/3 games)", "(3 weeks remaining, calf)", "(1 week remaining on his knee injury)", or "(season-long)". Instead, write something like "he's expected back this week", "still a couple weeks away", "expected back any day now from his knee injury", or "has been out all season." The parenthetical format reads like a spreadsheet -> write it like sports journalism.
12. **SPORTSBOOK LANGUAGE FOR ODDS (applies to ALL sections):** When describing upsets, underdogs, or matchup dynamics in prose, use American odds (moneyline) and/or point spreads, NOT win probability percentages. Write it like an actual sportsbook: "+140 underdog on the moneyline", "69.5-point underdog", "the -270 favorite". Win probability percentages belong ONLY in stat blocks (like the Betting Lines header), never in narrative prose.
13. **SUPERLATIVE/HISTORICAL CLAIM VERIFICATION (CRITICAL):** NEVER use phrases like "the most/least/worst/best in league history", "all-time", "ever", "first time ever", "most unlucky season ever" unless you have VERIFIED the claim against the extracted data. The historical_luck section contains ALL season records -- check them before claiming any season is "the worst" or "the most" of anything. If Hayden's luck index is -3.6, check the historical table: Benton 2020-21 was -7.6, Benton 2023-24 was -6.2, etc. A claim of "most unlucky season in history" when it's actually #6 all-time is a SERIOUS factual error. When in doubt, use relative language: "one of the unluckiest seasons" or "the worst of Hayden's career" (after verifying career data). This applies to ALL superlative claims -- streaks, scores, margins, records, etc.
14. **MAGIC NUMBER DEFINITION:** A magic number of N means the leading team needs ANY COMBINATION of N events (own wins + rival losses) to clinch. A magic number of 2 does NOT mean "one more win clinches" -- it means the leader needs a win AND a rival loss, OR two wins, OR two rival losses. NEVER write "one win clinches" unless the magic number is literally 1. Correct phrasing: "With a magic number of 2, Nick needs any combination of one win and one Benton loss to clinch" or "Nick's magic number is 2 -- a win paired with a Benton loss would clinch the title."
15. **ELIMINATION STATUS:** Check `current_standings` and records carefully. If a team is mathematically eliminated from contention, never write that they are "not quite eliminated" or "close to elimination." Conversely, if they are NOT eliminated, do not claim they are. When discussing implications of wins/losses, verify the math: "6 games back with 5 weeks to play" = mathematically eliminated.
16. **TRADE GRADE DIRECTION VERIFICATION (CRITICAL):** When grading trades in Around the NBA or Rumor Mill, you MUST re-read the trade data AFTER writing each grade to verify you haven't reversed who gained and who lost assets. Specifically: if Manager A SENT higher-value picks (e.g., 3rd + 4th rounders) and RECEIVED lower-value picks (e.g., 8th rounders), Manager A LOST draft capital -- do NOT write that they "acquired premium draft capital." This error has occurred before and is unacceptable. MANDATORY STEP: After writing trade grades, re-read the `side_a.sent_picks` and `side_b.sent_picks` fields and confirm your grade narrative matches who sent what.
17. **TABLE HEADERS -- NO ROW COUNTS:** Table headers must match the template exactly. Do NOT append row counts like "(5)", "(30)", or "(all)" to table headers. Write `**Top Performances**`, not `**Top Performances (5)**`. This applies to ALL tables in every section.
18. **NO DUPLICATE SECTION HEADERS:** When a section's required output format shows a bold header like `**What If?**` or `**Stats Corner**`, that IS the section content header -- do NOT also produce it if you're already using `### **[N]. [Section Name]**` as the section heading. Each section name should appear exactly once.
19. **HEADLINE STYLE (Around the NBA):** Same voice as everything else (VOICE.md) -- one narrator, one register. Headlines are plain and specific with the league's stake first: write "Jokic's knee, and what three weeks without him costs Hayden", NOT a news-wire headline ("Jokic Suffers Setback as Nuggets Fall") and NOT a metadata label ("Player of the Night - Kawhi Leonard - Feb. 8"). Facts from web search are reported as such, with their date.
20. **DATE RANGES:** Use the word "to" for date ranges in the title and subtitle (e.g., "Feb 2 to Feb 8"). Do NOT use em dashes, en dashes, arrows, or special characters for date ranges -- they can cause encoding issues in downstream rendering.
21. **LEAGUE LORE (`LEAGUE_LORE.json`) IS THE ONLY SOURCE FOR WHAT THE NUMBERS CAN'T SAY.** History, habits, reputations, nicknames: if it isn't in the stats report, it must be an APPROVED lore entry, and the sentence that uses it ends with that entry's tag, `<!--lore:ENTRY_ID-->` (invisible to readers; the HTML generator strips it). `scripts/check_draft.py` refuses history claims ("again", "always", "first time since") with no tag or number, and tags that don't resolve. **Placement:** a lore clause attaches to a claim the sentence makes -- a number, a result, a verdict -- and explains or complicates it. If deleting it leaves the sentence's point unchanged, it is hanging off a name: cut or move it (VOICE.md, "Where the clause goes"). Lore volume follows how many of the week's claims it bears on, never an even spread across sections.
    - **strength "fact"** (e.g. "Benton is 6-22 in February"): true, but not evidence of a pattern. Tell it as HISTORY, never as character -- "Benton is 6-22 in February matchups", not "Benton always collapses in February". The check flags character words on a fact tag.
    - **strength "tendency"**: survived a test against chance. May be told as character.
    - **strength "written"**: Nick's own words. May be told as character. Its numbers are NOT sayable -- take numbers from the stats report.
    - **kind "alias"**: an approved nickname ("Wemby") counts as the player's name.
    - Proposed, rejected or stale entries do not exist. Do not use them.
22. **OPEN WITH THE LEAD ANGLE.** The stats report's "ANGLES" block ranks this week's stories by how unusual they are times how much they moved the Cup-seeding and standings races. The newsletter's opening (the first matchup summary's first paragraph, and the subtitle if there is one) leads with the top angle; the next ones are the secondary threads. Never print the scores. If the block says angles are unavailable, choose from the storyline alerts.

23. **MONEY ONLY WHEN IT MOVED.** The ANGLES block ends with a "Money this week" line, computed from what was decided this week. If it says nothing was decided, the newsletter contains **no dollar figures** -- name a pot without its amount if you need it. `scripts/check_draft.py` flags every dollar figure in such a week (finding `money_without_event`). If something was decided, state a liability only for the managers it changed or where it separates one manager from the rest; a liability true of everyone last week and this week is not news (VOICE.md, "Money only when it moved"). Rule 23 decides *whether* to mention money; the pot-and-window rule decides *how*. Both apply.
    - **Pot and window, in every section** (LEAGUE_RULES "Language rule"). A sentence with a dollar figure names its pot (the regular-season pot or the playoff pot) and its window (weeks 1-15, the regular season, the semifinals); never "safe" or "certain" about paying without both. There is no Money and Exposure block any more (it moved to the hub, 4d), so no section is exempt: `check_draft.py` flags a dollar line without its pot and window (finding `money_unqualified`), in any section.

24. **AWARD RACES ONLY WHEN THEY MOVED.** There is no awards block in the newsletter; the hub's Awards page carries the races. The stats report's **AWARD MOVES** block, right after the ANGLES, lists the races that moved this week (a new leader, a big change in the leader's lead, a big swing in the MVP odds) with the before and after. Mention a race only for a move listed there, once, where it fits: Power Rankings, Fun Facts, or the matchup it happened in. Every award number comes from that block (the claim check traces it). When the block says "No award race moved this week.", or that it is unavailable, the issue mentions no award race. Cite no MVP odds the block says were not compared.

---

## THE FOUR MANAGERS

| Manager | Team Name | Notes |
|---------|-----------|-------|
| Nick | Luka my Balls | Named after Luka Doncic, most career wins |
| Hayden | Big Nik Energy | Named after Nikola Jokic, second most career wins |
| Benton | Smaxey | Named after Tyrese Maxey, third most career wins |
| Garrett | Saboner | Named after Domantas Sabonis, least career wins |

---

## OUTPUT FORMAT

```
## **CHS Alumni Fantasy Basketball League -> Week [X] Newsletter**

**Season [YYYY-YY] | Week [X] ([Start Date] to [End Date])**

---

### **1. Matchup Summaries**
[content]

### **2. Report Cards**
[content]

...continue through all 10 sections...

---

**End of Week [X] Newsletter**
```

**Formatting:**
- Use `- ` (standard markdown bullet) for bullets
- Use `**text**` for bold, `*text*` for italics
- Separate sections with `---`
- Tables: `| Col1 | Col2 |` with `|---|---|` separator

---

# THE 10 SECTIONS

---

## **1. Matchup Summaries**

### DATA EXTRACTION (do this first)
```
For each matchup in matchup_summaries[]:
- Winner: [matchup_summaries[i].winner]
- Score: [matchup_summaries[i].score_a] - [matchup_summaries[i].score_b]
- Margin: [matchup_summaries[i].margin]
- Team A: [manager_a], [record], [stats_a.games_played] games, [team_fppg] fppg
  - Positional: G: [g_fppg] | F: [f_fppg] | C: [c_fppg]
  - Top performers: [stats_a.best_performers[0].name] ([stats_a.best_performers[0].fp] FP, [games] games)
  - Worst performer: [stats_a.worst_performer.name] ([stats_a.worst_performer.fppg] FPPG)
  - Games lost to injury: [stats_a.games_lost_to_injury]
  - Injury breakdown: [stats_a.injury_breakdown[].player] ([stats_a.injury_breakdown[].games] games)
- Team B: [same structure with stats_b]
- Season series: [season_series]
- All-time: [all_time_series]

CHAMPIONSHIPS (from power_rankings[].championships):
- [verify counts from RECORDS.json / power_rankings -- do NOT hardcode]

SEASON INJURY CONTEXT (from season_injury_burden, for both managers in matchup):
- [Manager]: [total_injury_burden_pct]% season injury burden ([non_il_injury_games] games lost to injury)
  - IL usage: [il_injury_games] games (top: [il_players[0].player] - [il_players[0].games] games)
  - NOTE: Use total burden % but non-IL game count for prose. Call it "games lost to injury" (not just "games lost").

CURRENT TEAM HEALTH (from current_team_health, for both managers in matchup):
- [Manager]: [health_pct]% healthy ([injured_fppg] proj FPPG out)
  - Injured: [injured_players[].player] ([proj_fppg] FPPG, [remaining_weeks] weeks, status: [status]) or "None"
  - If status="returning": player available [return_games]/[total_week_games] games

RETURNING PLAYERS (from current_team_health.returning_players[]):
- [player] ([manager]): returning [return_games]/[total_week_games] games -> [return_notes]

SCORING TRENDS (from scoring_trends, for both managers in matchup):
- [Manager]: 
  - Last 3 avg: [last_3_avg] | Season avg: [season_avg]
  - Trend: [trend] ([trend_description])
  - Trajectory: [trajectory] (last 3 weeks direction)
```

### REQUIRED OUTPUT FORMAT
```
**[Winner Team] [Winner Score] def. [Loser Team] [Loser Score]**

*[Team A] ([Record]): [games] games, [fppg] fppg (G: [g_fppg] | F: [f_fppg] | C: [c_fppg])*
*[Team B] ([Record]): [games] games, [fppg] fppg (G: [g_fppg] | F: [f_fppg] | C: [c_fppg])*
*Season series: [X-X] | All-time: [Leader] leads [W-L]*

[3-4 paragraphs of flowing narrative that weaves together the story of the matchup. Don't write in rigid blocks -> let the narrative breathe and connect naturally. Include stakes, key performers with EXACT FP totals, positional battles, and closing implications. Write like a sportswriter, not a data reporter.]
```

### KEY RULES
- **SCOREBOARD FORMAT IS EXACT -- DO NOT DEVIATE:** The matchup header MUST be formatted as: `**[Winner Team] [Winner Score] def. [Loser Team] [Loser Score]**`. The winning team always comes first, followed by their score, then "def.", then the losing team and their score. No arrows, no dashes, no "vs" -- always `def.` Examples:
  - CORRECT: `**Luka my Balls 1455.95 def. Big Nik Energy 1270.75**`
  - CORRECT: `**Saboner 1581.35 def. Smaxey 1389.50**`
  - WRONG: `**Luka my Balls 1455.95 -> Big Nik Energy 1270.75**`
  - WRONG: `**Luka my Balls (1455.95) vs Big Nik Energy (1270.75)**`
  - WRONG: `**Luka my Balls 1455.95 - Big Nik Energy 1270.75**`
  - This format is critical for HTML rendering -- any variation breaks the scoreboard display.
- Headers use TEAM NAMES ("Luka my Balls 1713.2"), not manager names
- Every player mention needs their FP total AND games played from the extraction (e.g., "Brandon Miller (166.35 FP over 4 games)")
- Reference positional breakdowns in narrative
- **UPSET LANGUAGE -- USE SPORTSBOOK ODDS:** When describing an upset win, use the spread and/or moneyline from the previous week's betting lines (in the Week N-1 stats report under `looking_ahead`), NOT win probability percentages. Write it like an actual sportsbook:
  - CORRECT: "Coming in as a +140 underdog on the moneyline and getting 69.5 points on the spread, Luka my Balls flipped the script"
  - CORRECT: "Hayden entered at +115 on the moneyline, a 28.5-point underdog"
  - WRONG: "Coming in as a 41% underdog against Benton's 59% win probability"
  - WRONG: "Hayden entered as a 46% underdog"
  - Win probability percentages belong in the Betting Lines stat block, not in narrative prose about upsets.
- **INJURY GAMES -- COUNTS ONLY, NO PLAYER LISTS:** When mentioning games lost to injury, state the COUNT only. Do NOT list which specific players missed which specific games. Keep it concise:
  - CORRECT: "Nick lost 9 games to injury, but a 103.3% efficiency rating meant the players who did suit up more than compensated"
  - CORRECT: "a week where 10 games were lost to injury"
  - WRONG: "Santi Aldama missed 3, Deni Avdija missed 2, and Anthony Edwards, Devin Booker, Jalen Johnson, and Joel Embiid each missed 1 apiece"
  - WRONG: "Franz Wagner (4), Jalen Williams (2), Keyonte George (2), Lauri Markkanen (1), and Onyeka Okongwu (1)"
  - These player-by-player breakdowns add bulk without adding interest. The count tells the story.
- **INJURY BREAKDOWN (internal use only):** Use the `injury_breakdown` field to identify WHICH players caused those losses internally for accuracy, but do NOT reproduce the list in prose. Do NOT assume the major injured player (e.g., one in INJURY_OVERRIDES or an IL slot) was responsible -> they may be in an IL slot and not counting against starter games. The `injury_breakdown` shows short-term injuries to players who were in starting slots.
- **SEASON INJURY CONTEXT:** When injuries significantly impacted a matchup, weave in season-long non-IL injury burden for context. Example: "This was yet another injury-plagued week for Hayden, who has now lost 116 games to injury this season -> 51 more than any other manager." This adds depth without making every matchup about injuries.
- **HISTORICAL CLAIM VERIFICATION:** Before writing ANY "most/worst/best in league history" or "in X years of the league" claim, you MUST check the extracted historical data. For luck index claims, check `historical_luck.managers` for all seasons. Hayden's -3.6 luck index is NOT "the most unlucky season in league history" -- it's #6 all-time (Benton's 2020-21 at -7.6 is the actual worst). Use "one of the unluckiest" or "the worst of Hayden's career" (after verifying) instead. See Critical Rule #13.
- **CURRENT TEAM HEALTH:** Use `current_team_health` to show the health state GOING INTO the matchup. This is crucial for forward-looking context:
  - **What it counts (11-02):** every player in an IL slot for the coming week (out all week), every override covering the week, and every Q/D/O tag with no override (the games the injury model expects him to miss). Each player's `why` says which: "IL slot", "override, back MM-DD", or "O tag, expected to miss ~N of M games". Say why in those words; never call a tagged player out for the week.
  - "Hayden enters Week 14 at 83.8% health with Jokic (59.2 FPPG) still sidelined, while Benton is nearly full strength at 93.8%"
  - "For the first time since Week 10, Nick is playing without a major injury -> AD's return bumps him to 100% health"
  - Combine with non-IL burden for the full picture: "Hayden's 83.8% current health is actually an improvement -> he's dealt with a league-high 24.9% season burden"
- **RETURNING PLAYERS:** If `returning_players[]` contains entries, highlight mid-week returns:
  - "Kawhi's Thursday return (2/4 games expected) gives Garrett a late-week boost that could swing this matchup"
  - Players with partial availability are neither fully "out" nor fully "healthy" -> they're wildcards worth mentioning
- **CHAMPIONSHIPS (optional):** When relevant, weave in championship context to add historical stakes:
  - "Nick moved one step closer to a sixth title -> more than anyone else in league history"
  - "Garrett's loss keeps him winless in the title hunt after eight seasons"
  - Use sparingly -> not every matchup needs championship context
- **SCORING TRENDS:** Use `scoring_trends` to add momentum context to matchup narratives:
  - "Nick came in running hot -> 9% above his season average over the last 3 weeks -> and delivered again with 1521.75 FP"
  - "Hayden's slide continues: this was his fifth straight week below season average"
  - "The trajectory told the story: Nick's rising form vs Hayden's decline pointed to a mismatch"
  - Especially useful when explaining upsets or confirming expected outcomes
- **WRITE NATURALLY** -> avoid formulaic paragraph structures like "Paragraph 1: stakes. Paragraph 2: performers. Paragraph 3: implications." Instead, weave these elements together organically like real sports journalism. Let one thought flow into the next.

---

## **2. Report Cards**

### DATA EXTRACTION (do this first)
```
SEASON WAIVER WIRE ROI: See Section 8 (Stats Corner) for the league-wide table.
Individual waiver stats for each manager are still in the italic stat line below.

For each manager in report_cards[]:
- Manager: [manager]
- Team: [team_name]
- Grade: [letter_grade]
- Record: [record]
- Weekly FP: [weekly_fp]
- Efficiency: [efficiency_pct]%
- Games lost to injury: [games_lost_to_injury] (count only - player names already in Matchup Summaries)
- Games left on bench: [games_left_on_bench]
- Blunders: [blunders] ([blunder_points] FP wasted) -- if 0, show as "Blunders: 0" (no FP wasted parenthetical)
- New players: [waiver_adds_count] joined ([joined_week_adds] week-N adds, [joined_claims] week-(N-1) claims), [waiver_fp_total] total FP over [waiver_games] games ([waiver_fppg] fppg, [fp_per_add] FP per player). These are the players who JOINED the roster this week: last week's rule-7 claims applied in this window are among them. The adds a manager MADE this week are only [joined_week_adds] (the ADD BUDGET table counts the same way). Never write "made N adds" from [waiver_adds_count].

SEASON INJURY CONTEXT (from season_injury_burden for this manager):
- Season injury burden: [total_injury_burden_pct]% ([non_il_injury_games] games lost to injury)
- IL usage: [il_injury_games] games (top IL player: [il_players[0].player] - [il_players[0].games] games)
- NOTE: Use total burden % but non-IL game count for prose. "Games lost to injury" = non-IL only.

SEASON TOTALS (from LEAGUEHISTORY - use for context/rankings):
- [Manager]: [total_scheduled_games_current_season] scheduled, [total_healthy_starter_games_current_season] played, [total_games_lost_current_season] lost, [total_games_left_on_bench_current_season] bench
- Utilization rate: played / scheduled * 100 (e.g., Nick: 552/661 = 83.5%)
- Use for context: "Nick's league-best 83.5% utilization rate" or "Hayden's 116 games lost to injury -> most in the league"
```

### REQUIRED OUTPUT FORMAT (sorted by overall_score, DESCENDING -- highest score first)
**CRITICAL: Report cards MUST be ordered by `overall_score` from the stats report, highest to lowest. This is NOT alphabetical, NOT by record, and NOT by letter grade alone (since letter grades can be subjective). Check `report_cards[].overall_score` and sort strictly descending. Example: if scores are Nick 87.9, Benton 76.7, Garrett 72.1, Hayden 69.4, the order is Nick -> Benton -> Garrett -> Hayden.**

**Ties: equal `overall_score` is broken by `weekly_fp` (the week's points), higher first.** `report_cards` already arrives in this order; keep it. `check_draft.py` flags any other order (finding `report_card_order`). Two cards equal on both are a tie no rule covers: the report still builds, and `check_draft.py` flags it for Nick. Example, week 16 of 2025-26: Garrett 85.2 (B), Hayden 67.6 (C-), Nick 67.2 (C-), Benton 64.2 (D+) -> Garrett, Hayden, Nick, Benton. Hayden is ahead of Nick on score; the matching letter grade is irrelevant.
```
**[Manager] ([Team]) -- [Grade]**

*Record: [W-L] | [Won/Lost] [to/vs] [Opponent] by [margin] | [FP] FP | [+/-X]% vs projection | Injuries: [X] | Bench: [X] | Blunders: [X] ([FP] FP wasted) | New players: [count] joined ([FP] FP over [games] games, [fppg] fppg, [FP per player] FP per player)*

NOTE: Blunders always appear in the stat line. If blunders = 0, show "Blunders: 0" (no FP wasted parenthetical). If blunders > 0, show "Blunders: X (Y FP wasted)". Only call out blunders by name in the prose paragraph when blunders > 0.

[6-8 sentence assessment -> justify grade with specific figures from extraction. When injuries impacted the week:
- Reference the COUNT only (e.g., "lost 9 games to injury"), NOT the player names (those were already listed in Matchup Summaries)
- Connect to **season_injury_burden** (non-IL) for pattern context (e.g., "continuing a season where he's lost 116 games to injury -> the league's highest burden")
- Reference **utilization rate** when relevant (e.g., "Nick's 83.5% utilization rate leads the league")
Example: "The 9 games lost to injury limited his output, but his 83.5% season utilization rate remains the league's best."]
```

### GRADING CRITERIA
- A+/A/A-: exceeded projections + good decisions
- B+/B/B-: exceeded projections, minor issues
- C+/C/C-: Met expectations, nothing special
- D+/D/D-: underperformed + questionable decisions
- F: Disaster week

### KEY RULES
- **EFFICIENCY FORMAT**: In the italic statline, express efficiency as a delta from projection (e.g., "+3.3% vs projection" not "Efficiency: 103.3%"). In prose, either format is fine, but the delta is preferred for readability.
- **UTILIZATION RATE TIME SCOPE**: Utilization rate (games played / scheduled) is a WEEKLY stat. When mixing it with season-long stats like injury burden in the same sentence, clarify the scope so the reader isn't confused. Example: "Nick's Week 15 utilization of 85.0% (51 of 60 games) was strong, and his league-low 17.8% season injury burden tells the story of a manager who has navigated every obstacle this year."
- **EFFICIENCY** = actual FP / projected FP for healthy starters. It measures performance vs expectations, NOT availability. A 91% efficiency means healthy players scored 91% of projections. Injuries affect total FP (fewer games), NOT efficiency. These are separate facts -> never say injuries "hurt efficiency."
- **INJURY REFERENCES - NO PLAYER NAMES**: When mentioning games lost to injury in Report Cards, use only the count, NEVER list player names. Matchup Summaries already detailed who was injured.
  - -> CORRECT: "The 9 games lost to injury limited his output"
  - -> CORRECT: "his injury-depleted roster" or "the injuries detailed above"
  - -> WRONG: "The 9 games lost to injury -> Deni Avdija (3), Quickley (2), Nembhard (1)..."
  - -> WRONG: "Injuries tanked his efficiency" (efficiency measures performance, not availability)
  - Player names ARE fine in other contexts (top performers, waiver adds, underperformers, etc.)

---

## **3. Betting Lines**

The issue's whole look-ahead (4d; NEWSLETTER_REVIEW 2026-11-25, decisions 2 and 5): each matchup's line, then two or three sentences on what decides it, then one line pointing to the hub's Next week page, which carries starts, light days and injuries in full. No position-by-position paragraph.

### DATA EXTRACTION (do this first)
```
WHERE THE LINES COME FROM (the italic note at the top of Section 3 of the stats report):
- [Monday's closing line, or this report's own line -- as the note says]

THE LINE, for each matchup in looking_ahead.matchup_previews[] (copy exactly as printed):
- Teams: [team_name_a] vs [team_name_b]
- Spread: [manager_a] [spread_a] ([manager_b] [spread_b])
- O/U: [over_under]
- Win prob: [win_prob_a]% vs [win_prob_b]%
- Moneyline: [moneyline_a] / [moneyline_b]
- Avg score (the projected final): [avg_score_a] / [avg_score_b]

WHAT COULD DECIDE IT (read them all, then pick the one or two that matter most):
- Key matchup: [the "Key matchup" line: two players per team, projected FPPG]
- Health: [current_team_health health_pct] and the notable injuries / returning players
- Schedule: the Schedule Context line (startable games, the edge)
- Stakes: [implications]
- Series: season series, all-time, H2H streak (only if 3 or more)
- Form: the Scoring Trends lines
```

### REQUIRED OUTPUT FORMAT
```
[One sentence on where the lines come from, only when the drafting prompt's Part 1 asks for it.]

**[Team A] vs [Team B]**

*Line: [Favorite] -[spread] ([Underdog] +[spread]) | O/U: [total]*
*Win Prob: [Team A] [X]% | [Team B] [X]%*
*Moneyline: [Team A] [odds] | [Team B] [odds]*
*Avg Score: [Team A] [score] | [Team B] [score]*

[2-3 sentences: what decides this matchup.]

**On the hub:** starts, light days and injuries for this matchup are on the Next week page.
```

### KEY RULES
- **TWO OR THREE SENTENCES per matchup, no more.** Say what decides it: the one or two facts from WHAT COULD DECIDE IT that the line rests on (a star's health, a schedule edge, what a loss would cost). Never walk through the positions, every injury or the full schedule: the hub's Next week page has them.
- **THE LINE BLOCK:** copy its numbers exactly as the stats report prints them, with TEAM NAMES. They are the closing line on a Monday-night build; `check_draft.py` compares each matchup's four lines with the report's previews (finding `betting_line_mismatch`).
- **THE HUB LINE:** end every matchup with this line, exactly: `**On the hub:** starts, light days and injuries for this matchup are on the Next week page.` The page renders it as a pointer under the matchup, and the hub's archive does not read it as the preview.
- **SPORTSBOOK LANGUAGE:** in the sentences, use spreads and moneylines, never win probability percentages ("Nick is a -270 favorite", not "Nick's 72.94% win probability"). The percentages are in the line block only.
- **GAMES GRID -- DO NOT REPRODUCE:** the week's games grid is rendered into the HTML from the stats report. You MAY cite a manager's Starts or Idle from the "Games Grid" block. Do NOT name players to add (that is gated advice), and do not claim how many starts an add could recover.
- **INJURY TIMELINES -- PROSE, NOT PARENTHESES:** "Anthony Davis is still a few weeks away", never "(3 weeks remaining)" or "(2/3 games)".
- **INJURY TIMELINES:** when injury notes say "out ~X weeks starting week Y", the REMAINING weeks are `X - (current_week + 1 - Y)`. Report remaining time, not the total.
- **H2H streaks:** only when `h2h_streak_length` >= 3.
- **ELIMINATION CHECK:** before writing "not quite eliminated" or similar on top of the implications, do the math: if games_back > remaining_weeks, the team IS eliminated.

---

## **4. Player of the Week**

### DATA EXTRACTION (do this first)
```
Winner:
- Player: [player_of_week.winner.player_name]
- Manager: [player_of_week.winner.manager]
- Team: [player_of_week.winner.team]
- Total FP: [player_of_week.winner.total_fp]
- Games: [player_of_week.winner.games]
- FPPG: [player_of_week.winner.fppg]
- vs Projection: [player_of_week.winner.vs_projection_pct]%
- Team contribution: [player_of_week.winner.team_contribution_pct]%

Honorable mentions:
- [honorable_mentions[0].player_name] ([manager]): [total_fp] FP, [games] games, [fppg] FPPG
- [honorable_mentions[1].player_name] ([manager]): [total_fp] FP, [games] games, [fppg] FPPG
```

### REQUIRED OUTPUT FORMAT
```
**[Player Name]**

*[Total FP] FP over [games] games ([FPPG] FPPG) | [+/-X]% vs projection | [X]% of team output*

[5-7 sentences -> signature moments, consistency, context in season performance. ALL stats must come from extraction.]

**Honorable Mentions:** [Player Name] posted [FP] FP across [games] games ([FPPG] FPPG) -> [one sentence]. [Second player name] delivered [FP] FP across [games] games ([FPPG] FPPG) -> [one sentence].
```

---

## **5. Fun Facts**

### DATA EXTRACTION (do this first)
```
From fun_facts[]:
1. [fun_facts[0].text] (category: [category])
2. [fun_facts[1].text]
3. [fun_facts[2].text]
4. [fun_facts[3].text]
5. [fun_facts[4].text]
6. [fun_facts[5].text]
7. [fun_facts[6].text]

SEASON-LONGEST STREAKS (from current_streaks):
| Manager | Current Win | Current Loss | Season-Best Win | Season-Best Loss |
| Nick    | [win_streak] | [loss_streak] | [season_longest_win_streak] (weeks [season_longest_win_weeks]) | [season_longest_loss_streak] |
| Hayden  | ... | ... | ... | ... |
| Benton  | ... | ... | ... | ... |
| Garrett | ... | ... | ... | ... |

LUCK INDEX - CURRENT SEASON (from luck_index):
| Manager | Actual | Expected | Luck | Rating |
| [manager] | [actual_record] | [expected_record] | [luck_index] | [luck_rating] |
Luckiest: [luckiest] | Unluckiest: [unluckiest]

LUCK INDEX - HISTORICAL CONTEXT (from historical_luck):
Career totals (all-time, every week incl. playoffs -- not the Power Rankings' regular-season Career Record):
| Manager | Record | Win% | Career Luck |
| [manager] | [actual_record] | [win_pct]% | [career_luck] |
All-time luckiest: [all_time_luckiest] | All-time unluckiest: [all_time_unluckiest]

Per-manager career context (use for narrative):
- [manager]'s current [luck_index] ranks #[rank] of [num_seasons] career seasons
- Luckiest season ever: [luckiest_season.season] ([luckiest_season.luck_index])
- Unluckiest season ever: [unluckiest_season.season] ([unluckiest_season.luck_index])

League records:
- Luckiest single season ever: [luckiest_single_season.manager] [luckiest_single_season.season] ([luck_index])
- Unluckiest single season ever: [unluckiest_single_season.manager] [unluckiest_single_season.season] ([luck_index])
```

### REQUIRED OUTPUT FORMAT
```
**Fun Facts**

- [Fact 1 -- rewrite in your voice, keep all numbers exact]

- [Fact 2 -- rewrite in your voice, keep all numbers exact]

- [Fact 3 -- rewrite in your voice, keep all numbers exact]

- [Fact 4 -- rewrite in your voice, keep all numbers exact]

- [Fact 5 -- rewrite in your voice, keep all numbers exact]

- [Fact 6 -- rewrite in your voice, keep all numbers exact]

- [Fact 7 -- rewrite in your voice, keep all numbers exact]
```

### KEY RULES
- Use ` -> ` bullet character
- Each fact is one sentence with specific numbers
- You may lightly rephrase for flow, but NEVER change the numbers
- Select 5 most interesting/varied facts if more than 5 available
- **STREAK VERIFICATION:** When writing about streaks, ALWAYS check `season_longest_win_streak` and `season_longest_loss_streak` to verify superlatives:
  - -> WRONG: "Nick's 4-game win streak is his longest of the season" (if season_longest_win_streak = 5)
  - -> CORRECT: "Nick's 4-game win streak is his second-longest of the season, behind a 5-game run in Weeks 4-8"
  - -> CORRECT: "Nick has won 4 straight" (no superlative claim)
- **SEASON TOTALS:** You MAY add 1-2 fun facts derived from LEAGUEHISTORY season totals if interesting:
  - "Hayden has lost 99 games to injury this season -> 16 more than any other manager"
  - "Nick's 83.5% utilization rate is 3.6 percentage points better than second place"
  - Only add these if they're genuinely interesting, not to pad the section

---

## **6. What If?**

### DATA EXTRACTION (do this first)
```
From what_if.costly_decisions[] (only swaps >= 25 point swing):
- [manager]: Benched [benched_player] ([benched_fp] FP) over [started_player] ([started_fp] FP) -> [net_swing] swing

From what_if.matchup_changers[]:
- Would any optimal lineups have flipped outcomes? [yes/no, details]

From what_if.manager_analysis[].blunder_details[] (blunders -- bench games with open starter slots):
- [manager]: [bench_player] ([bench_player_fp] FP) left on bench -> [available_slot] slot ([dnp_starter] didn't play) on [date]
- Total blunders: [blunders] | Total FP wasted: [blunder_points]
```

### REQUIRED OUTPUT FORMAT
```
[If any blunders exist, lead with them -- they're the biggest story:]
- [Manager] committed [X] blunder(s): [Player] ([X] FP) sat on the bench while [DNP starter]'s [slot] slot was wide open. [One sentence on impact -- "That's [X] free points left on the table."]

[Then swaps >= 25 points:]
- [Manager]: [Benched Player] ([X] FP on bench) over [Started Player] ([X] FP started) -> [net swing] point swing. [One sentence on impact.]

- [Next swap if applicable]

[2-3 sentence summary -> who got lucky, who got burned, would any swaps have changed matchup outcomes? If blunders existed, close with the accountability angle: "Setting your lineup isn't optional."]
```

### KEY RULES
- **Blunders always lead the section** -- they're worse than swaps because they were entirely avoidable (open slots existed)
- Only include swaps with >= 25 point swing
- Use ` -> ` bullet character
- End with whether optimal lineups would have changed outcomes
- If NO costly decisions >= 25 points AND no blunders, say "No major lineup regrets this week" and note that all managers set strong lineups

---

## **7. Power Rankings**

### DATA EXTRACTION (do this first)
```
From power_rankings[]:
| Rank | Manager | Team | Record | Title Odds | Trend | Expected Record | Career Record | Career Win % | Championships |
[extract all 4 teams]
Note: "career_record" format is WINS-LOSSES (e.g., "113-74" means 113 wins, 74 losses)
Note: "championships" = number of titles won (read live values from power_rankings[].championships -- do NOT hardcode)
Note: "expected_record" = projected final record based on simulations (e.g., "14.4-6.6")

From title_odds:
- Magic number (if applicable; week 8 report on only): [title_odds.magic_number]

SEASON INJURY BURDEN (from season_injury_burden, all managers):
| Manager | Season Burden | Games Lost to Injury | IL Games | Top IL Player |
| [Manager] | [total_injury_burden_pct]% | [non_il_injury_games] | [il_injury_games] | [il_players[0].player] ([il_players[0].games]) |
[4 rows, sorted by total_injury_burden_pct descending]

CURRENT TEAM HEALTH (from current_team_health):
| Manager | Health % | Injured FPPG | Key Injured Players |
| [Manager] | [health_pct]% | [injured_fppg] | [injured_players summary] |
[4 rows, sorted by health_pct descending]
Rankings: [rankings] (healthiest to most injured)

SCORING TRENDS (from scoring_trends, all managers):
| Manager | Last 3 Avg | Season Avg | Trend | Trend Description |
| [Manager] | [last_3_avg] | [season_avg] | [trend] | [trend_description] |
[4 rows - use to identify hot/cold teams]

RETURNING PLAYERS (from current_team_health.returning_players[]):
- [player] ([manager]): [return_games]/[total_week_games] games -> [return_notes]
[Note any confirmed returns that could shift power rankings outlook]

```

### REQUIRED OUTPUT FORMAT
```
**Power Rankings**

| Rank | Team | Record | Title Odds | Trend |
|------|------|--------|------------|-------|
| 1 | [Team] | [W-L] | [X]% | [ -> / -> / -> ] |
[4 rows]

[3-4 paragraphs -> title race narrative, each team's outlook, magic numbers (week 8 report on only), draft pick positioning implications (check the SEASON TRADE LOG and DRAFT PICK OWNERSHIP blocks in the stats report to see who actually owns whose picks -> do NOT assume last place = #1 overall pick, as picks may have been traded). An award race that moved (rule 24) may go here. EVERY stat must be from extraction.]
```

### KEY RULES
- **ONE table: Power Rankings.** The projected finish distribution and Money and Exposure moved to the hub (4d); the stats report no longer prints them. Do not reproduce them or write a money paragraph.
- **DOLLAR FIGURES:** only in a week that decided money (rule 23, the ANGLES block's "Money this week" line), each naming its pot and window. Otherwise name a pot without its amount.
- **INJURY CONTEXT FOR OUTLIERS:** Use BOTH season burden AND current health to explain mismatched records:
  - **Season burden** tells the historical story: "Hayden has lost 116 games to injury (24.9% season burden) -> 51 more than anyone else"
  - **Current health** tells the forward-looking story: "But Hayden enters Week 14 at 83.8% health -> Jokic is his only major absence now"
  - Combine them: "Hayden's brutal 3-10 reflects a league-high 24.9% season burden, but at 83.8% current health, he finally has a chance to climb back"
  - "Nick's 17.8% season burden AND 92.7% current health make him the league's healthiest team -> past AND present"
- **UTILIZATION RATES:** Reference season totals from LEAGUEHISTORY to explain rankings:
  - "Nick's league-best 83.5% utilization rate explains his dominance"
  - "Hayden's 116 games lost to injury -> most in the league -> tells the story of this 3-10 season"
- **CHAMPIONSHIPS:** Use championship counts for historical context:
  - "Nick is chasing his sixth title -> no one else has more than three"
  - "Garrett, still searching for his first championship, sits in last place"
  - "A title would tie Hayden with Nick for most all-time" (hypothetical example)
- **EXPECTED RECORD:** Use `expected_record` to project where each team is headed:
  - "Nick projects to finish 14-7 based on remaining schedule strength"
  - "Hayden's expected 6-15 finish would be his worst season since 2018-19"
  - Compare expected vs actual: "Benton is outperforming projections -> his 7-5 is ahead of the expected 6.2-6.8 pace"
- **SCORING TRENDS:** Use momentum to add texture to the rankings narrative:
  - "Nick's hot streak (9% above season average) explains his surge up the rankings"
  - "Hayden has been cold for weeks -> his last 3 average of 1,450 is 8% below his season norm"
  - Trends can signal whether a team's record reflects their true strength or luck
- Trend arrows: ^ (improved), v (declined), ??" (unchanged)
- **NO MAGIC NUMBER BEFORE THE WEEK 8 REPORT** (Nick, 11-02). The stats report prints none before then; don't write one, or mention magic numbers at all. The claim check flags it.
- **MAGIC NUMBER:** If present (week 8 report on), the magic number applies to the 1st place team clinching over the **2nd place team specifically**. For example, "Nick's magic number is 7" means any combination of Nick wins + **Benton** losses (the 2nd place team) totaling 7 clinches. Do NOT say "non-Nick losses" -> only losses by the 2nd place challenger count. **CRITICAL: A magic number of 2 does NOT mean "one win clinches." It means TWO events are needed (e.g., a Nick win AND a Benton loss). NEVER write "a win clinches" unless the magic number is literally 1.**
- **ELIMINATION CHECK:** Before writing about any team's playoff/title hopes, verify: games_back vs weeks_remaining. If games_back > weeks_remaining, the team is mathematically eliminated. Do NOT write "not quite eliminated" for a team that IS eliminated. Hayden at 4-12 with 5 weeks left and 9 games back = eliminated.
- **DRAFT PICK OWNERSHIP DEFAULTS:** In the DRAFT PICK OWNERSHIP table, only NON-DEFAULT ownership is listed. If a pick is NOT listed, the original team STILL OWNS IT. Example: Benton owns Nick's 2026 1st (listed as "1_Nick": "Benton"), but Benton also still owns HIS OWN 2026 1st (not listed because it's default). Do NOT write "Benton's 1st round pick is actually Nick's" -- Benton has BOTH his own 1st AND Nick's 1st.
- **DO NOT list career win rates explicitly** -> career stats can inform your tone (e.g., "defying his historical struggles" or "continuing his usual dominance") but should not be dumped as a list like "Nick leads at 60.4%, followed by..."
- **Career record format:** "99-88" means 99 WINS and 88 LOSSES -> do not misread this as a head-to-head record

---

## **8. Stats Corner**

The week's tables only (4d): the top 5 and worst 5 performances, and the week's waiver pickups. The season tables are on the hub's Players page and the free agents on its Market page; Keeper Watch is cut.

### DATA EXTRACTION (do this first)
```
TOP PERFORMANCES (best_worst.best_games[], top 5):
| Rank | Player | NBA Team | Manager | FP | Date | Opponent |
[5 rows]

WORST PERFORMANCES (best_worst.worst_games[], top 5):
| Rank | Player | NBA Team | Manager | FP | Date | Opponent |
[5 rows]

WAIVER PICKUPS (best_worst.best_waivers[], ALL):
| Player | NBA Team | Manager | GP | Total FP | FPPG |
[all rows]
```

### REQUIRED OUTPUT FORMAT
```
**Stats Corner**

**Top Performances**

| Rank | Player | NBA Team | Manager | FP | Date | Opponent |
|------|--------|----------|---------|----|------|----------|
[5 rows from extraction]

**Worst Performances**

| Rank | Player | NBA Team | Manager | FP | Date | Opponent |
|------|--------|----------|---------|----|------|----------|
[5 rows from extraction]

**Waiver Pickups**

| Player | NBA Team | Manager | GP | Total FP | FPPG |
|--------|----------|---------|----|----------|------|
[all rows from extraction]

[3-4 sentence commentary on notable performances]
```

### KEY RULES
- **3 TABLES REQUIRED** -- Top Performances, Worst Performances, Waiver Pickups, in that order.
- **CUT IN 4D -- none of these in the draft, as a table or as prose:** the four season tables (Best and Worst Performers, by Total FP and by FPPG), Top Available Free Agents, and Keeper Watch.
- **RENDERED, NOT DRAFTED:** Positional Scoring Breakdown, Season Waiver Wire ROI, Bench Report, Record Book Snapshot and Draft Value Tracker are rendered by the HTML generator from the stats report. Do not put them in the draft.
- **ALL COLUMNS REQUIRED** -- match the table headers exactly as shown; do not drop columns (especially NBA Team)
- Copy data exactly from extraction -- no rounding, no approximating

---

## **9. Around the NBA**

This section covers **real NBA news from Week N (the covered week)** and connects it to fantasy implications. It is NOT a preview section.

### -> CRITICAL: WEEK N NEWS ONLY
- Around the NBA covers news that happened **DURING Week N** (the week being recapped)
- **DO NOT** include news from Week N+1 (that belongs in Betting Lines)
- If web search returns news from after Week N ended, **skip it** or save it for Betting Lines

Example - if covering Week 13 and it's now Week 14:
- -> WRONG: "Kawhi Leonard returned Thursday, scoring 24 points..." (Week 14 event)
- -> CORRECT: Focus on what happened during Week 13 (LeBron's 5-game stretch, Jokic injury updates from that week, etc.)

### STEP 1: EXTRACT LEAGUE CONTEXT (do this first)
```
ROSTERED PLAYERS BY MANAGER (from rosters):
- Nick: [list all players]
- Hayden: [list all players]
- Benton: [list all players]
- Garrett: [list all players]

CURRENT INJURIES (from looking_ahead.matchup_previews[].notable_injuries_a/b):
- [Manager]: [Player] ([injury type])
[list all]

INJURY OVERRIDES - DURATION DATA (from injury_overrides.players[]):
- [player_name]: out_weeks = [out_weeks array] -> [count] weeks out so far
  - Notes: [notes]
  - Remaining: ~[remaining weeks based on notes] weeks
[list all injured players - this is the SOURCE OF TRUTH for "how long has X been out"]

SEASON INJURY BURDEN (from season_injury_burden):
- [Manager]: 
  - Season Burden: [total_injury_burden_pct]% ([non_il_injury_games] games lost to injury)
  - IL Usage: [il_injury_games] games (tracked separately, not included in prose game count)
  - IL Usage: [il_injury_games] games - [il_players[0].player] ([games]), [il_players[1].player] ([games])
  - Top non-IL injuries: [top_non_il_injured[0].player] ([games]), [top_non_il_injured[1].player] ([games])
[list all managers, sorted by total_injury_burden_pct descending]

CURRENT TEAM HEALTH (from current_team_health):
- [Manager]: [health_pct]% healthy
  - Injured: [injured_players[].player] ([proj_fppg] FPPG, ~[remaining_weeks] weeks)
  - Healthy FPPG: [healthy_fppg] / Total: [total_fppg]
[list all managers, rankings: healthiest to most injured]

TOP PERFORMERS THIS WEEK (from player_of_week + best_worst.best_games[]):
- [player] ([manager]): [total_fp] FP, [fppg] FPPG
[list top 3-5]

CURRENT STREAKS (from current_streaks):
- [manager]: [X] game [win/loss] streak

STRUGGLING PLAYERS (from rumor_mill.drop_candidates[]):
- [player] ([manager]): [underperformance_index]% below projection
```

### STEP 2: WEB SEARCH FOR NBA NEWS
Search for recent NBA news about rostered players. Run 3-5 searches targeting:

1. **Injury updates**: "[injured player name] injury update" for each injured player
2. **Hot players**: "[top performer name] recent performance" 
3. **General NBA news**: "NBA news this week" or "NBA headlines [current date]"
4. **Trade rumors** (if near deadline): "NBA trade rumors [player name]"

** -> TIME AWARENESS - CRITICAL**: Around the NBA covers news from **Week N (the covered week) ONLY**.
- If web search returns news about events that happened AFTER Week N ended, **DO NOT include them**
- Player returns, game results, and performances from Week N+1 belong in **Betting Lines**, not here
- Example: If covering Week 13 and Kawhi returned in Week 14, do NOT write "Kawhi returned Thursday" - that's Week 14 news

**PRIORITY ORDER for storylines (Week N events only):**
1. Injury updates that occurred DURING Week N (new injuries, setbacks, surgery news)
2. Breakout performances from Week N with real-world context (new role, scheme change)
3. Trade rumors involving rostered players
4. Rotation changes affecting rostered players
5. Milestone watch (approaching career marks, records)

### STEP 3: CONNECT NEWS TO FANTASY
For each storyline, you MUST:
1. **Lead with the real NBA news** (what happened, context from web search)
2. **Name the fantasy manager affected**
3. **Quantify the fantasy impact** (FP totals, positional need, win/loss implications)
4. **Frame forward implications** (if he returns, if the trade happens, etc.)

### REQUIRED OUTPUT FORMAT
```
**Around the NBA**

- **[Story 1 Headline -> in voice (rule 19): plain, specific, the league's stake first]**

[3-4 sentence paragraph: Real NBA context from web search, fantasy manager named, stats from extraction, forward-looking implications]

- **[Story 2 Headline]**

[3-4 sentence paragraph]

- **[Story 3 Headline]**

[3-4 sentence paragraph]

- **[Story 4 Headline]**

[3-4 sentence paragraph]

[Optional 5th story if compelling]
```

### EXAMPLE (with citations during drafting)
```
- **Jokic Recovery Hits Snag**

Nikola Jokic remains sidelined with the knee injury that's kept him out since Week 11 [from extraction: injury_overrides shows Jokic out_weeks includes 11, 12, 13]. Hayden has now played three weeks without his cornerstone player [from extraction: len(out_weeks) = 3], going 1-2 during that stretch [from extraction: cross-reference Hayden's weekly results with Jokic out_weeks]. The Nuggets play 4 games next week [from web search: Denver schedule], and with Jokic's status listed as "~2 more weeks" [from extraction: remaining_weeks], the earliest return would be Week 15. At 3-10 [from extraction: Hayden record], time is running out.
```

### KEY RULES
- **4-5 stories with bullet points** -> each story gets a ` -> ` bullet and **bold headline**
- **Every story names a fantasy manager**
- **Mix of web search context + extraction stats**
- **DO NOT fabricate injury timelines** -> if web search doesn't give a return date, say "no timetable"
- **INJURY DURATION FROM DATA ONLY:** "Weeks without player X" MUST come from `injury_overrides.out_weeks[]` array (count the weeks listed). Do NOT infer injury duration from loss streaks -> a 5-game loss streak does NOT mean 5 weeks without a player.
- **INJURY TIMELINES FROM DATA:** When injury notes say "out ~X weeks starting week Y", calculate REMAINING weeks as: `X - (current_week - Y)`. Report remaining time (e.g., "~2 more weeks"), not total duration.
- **DO NOT invent quotes** -> only use quotes if found in web search
- **Prioritize stories with biggest fantasy impact**
- **Frame forward** -> what does this mean for next week, rest of season?
- **USE BOTH INJURY METRICS FOR CONTEXT:** Combine season burden (historical) with current health (right now) for the full picture:
  - **Season burden** for historical context: "Hayden has lost 176 games to injury this season -> the highest burden at 24.8%"
  - **Current health** for the present state: "But Hayden enters Week 14 at 83.8% health -> only Jokic (59.2 FPPG) remains out"
  - **Combined example**: "Jokic's return would be huge for Hayden, who despite a league-high 24.8% season burden, is finally approaching full strength at 83.8% current health"
  - **Contrast when relevant**: "Nick has been the healthiest all season (17.6% burden) AND enters Week 14 at 92.7% -> only AD is out"
  This transforms generic injury news into fantasy-relevant storylines with both historical context and current state.


### SEASON TRADE LOG & DRAFT PICK OWNERSHIP (from TRADES.json)
The stats report now includes a **SEASON TRADE LOG** and **DRAFT PICK OWNERSHIP** block (loaded from `config/TRADES.json`). These are critical guardrails:
- **DO NOT** invent trade history beyond what's in the SEASON TRADE LOG. If a trade isn't listed there, it didn't happen.
- **DO NOT** claim a trade is "the first since..." without checking the log -- there may have been a trade just last week.
- **DO NOT** suggest a manager trades a pick they no longer own. Check the DRAFT PICK OWNERSHIP table first.
- **DO NOT** claim two managers are "competing for the #1 pick" without verifying who actually owns whose picks.
- When referencing trade frequency (e.g., "the league's most active trading stretch"), count from the SEASON TRADE LOG.
- When trade ideas involve draft picks, name the **specific pick and current owner** (e.g., "Garrett's 2026 2nd rounder, originally Nick's, acquired in the Week 7 KAT deal").

### TRADE GRADING RULES (when stats report includes TRADES THIS WEEK)
When the stats report contains a "TRADES THIS WEEK" block, the FIRST headline(s) in Around the NBA MUST cover each trade. Every trade headline paragraph MUST include a letter grade (A-F) for EACH manager involved.

**TRADE GRADE FORMATTING (CRITICAL):** The trade grade must be INLINE with the analysis paragraph, NOT on its own line. The grade line should flow directly into the analysis text in a single paragraph.
- WRONG FORMAT (creates broken rendering):
  ```
  **Grade: Hayden C+ | Garrett A-**
  
  Hayden's rationale makes sense...
  ```
- CORRECT FORMAT (grade flows into analysis):
  ```
  **Grade: Hayden C+ | Garrett A-** -- Hayden's rationale makes sense...
  ```
The double-dash after the grade connects it to the analysis as one continuous paragraph. NEVER put the grade on its own line followed by a blank line.

**Reference `config/DRAFT_PICK_VALUES.json` for draft pick valuations.** Key tiers:
- Round 1: Elite draft asset, likely keeper candidate
- Round 2: Strong draft asset, possible keeper
- Rounds 3-4: Solid contributor, unlikely to become a keeper
- Round 5: Fringe contributor, may get dropped by midseason
- Rounds 6-7: Roster churn, dart throws that usually get dropped early

**How to grade trades:**
1. **Compare player values** using projFPPG from the stats report
2. **Value draft picks** using `config/DRAFT_PICK_VALUES.json` for expected projFPPG by round (do not reference the exact FPPG numbers in the newsletter prose -> use qualitative tier descriptions instead)
3. **Quality over quantity:** A single high-round pick (Rd 1-2) with keeper upside is worth MORE than multiple low-round picks (Rd 5-7). Two 5th-round picks will likely both be dropped by midseason, while a 2nd-round pick could become a keeper for years.
4. **Factor in team context:** A rebuilding team (eliminated from playoffs) getting future assets grades differently than a contender going all-in. Consider: team record, championship odds, roster holes filled, injury situations, and keeper implications.
5. **Name the specific picks** in the analysis (e.g., "the 2027 2nd rounder is the most valuable non-player asset in this deal -> a strong draft asset with genuine keeper upside")
6. **MANDATORY POST-GRADE VERIFICATION:** After writing EACH trade grade, STOP and re-read the trade data. Ask: "Who SENT the higher-value picks? Did I say that manager GAINED or LOST capital?" If the answer doesn't match, rewrite. Example check:
   - Trade data: `side_a (Hayden) sent_picks: ["2026 4th", "2027 3rd"]` / `side_b (Garrett) sent_picks: ["2026 8th", "2027 8th"]`
   - Hayden SENT 4th + 3rd, RECEIVED 8th + 8th -> Hayden LOST draft capital
   - Writing "Hayden acquires premium draft capital" would be BACKWARDS and WRONG
   - Correct: "Hayden traded down in draft capital (4th + 3rd for 8th + 8th) but gained durability in Barnes"

### WHAT TO SEARCH (be specific)
Good searches:
- "Nikola Jokic injury update January 2026"
- "LaMelo Ball recent games"
- "Anthony Davis hand injury status"
- "NBA trade deadline rumors 2026"

Bad searches (too vague):
- "NBA news"
- "basketball updates"
- "fantasy basketball"

---

## **10. Rumor Mill**

### DATA EXTRACTION (do this first)
```
TRADE IDEAS (from rumor_mill.trade_ideas[]):
1. [manager_a] sends [gives_a] <-> [manager_b] sends [receives_a]
   Type: [trade_type]
   Rationale: [rationale]
[repeat for all trades]

HOT STREAKS (from rumor_mill.hot_streak_candidates[]):
- [player_name] ([manager])
  Reason: [reason]
  Overperformance: [overperformance_index]% (last 4 weeks), [overperformance_index_last_14_days]% (last 14 days)
  Trade Value: [trade_value_note]
[list all]

SLUMP WATCH (from rumor_mill.drop_candidates[]):
- [player_name] ([manager])
  Reason: [reason]
  Underperformance: [underperformance_index]% (last 4 weeks), [underperformance_index_last_14_days]% (last 14 days)
  Better FA: [better_fa_available]
[list all]

SEASON INJURY BURDEN (from season_injury_burden, for trade context):
| Manager | Total Burden | IL Games | Top IL Player |
| [Manager] | [total_injury_burden_pct]% | [il_injury_games] | [il_players[0].player] ([games]) |
[4 rows - use to identify desperate/comfortable trade positions]

TRADE HISTORY (from all_time_records.trade_partners):
| Trade Partners | All-Time Deals |
| Nick & Benton | [Benton_and_Nick] |
| Nick & Hayden | [Hayden_and_Nick] |
| Nick & Garrett | [Garrett_and_Nick] |
| Hayden & Benton | [Benton_and_Hayden] |
| Hayden & Garrett | [Garrett_and_Hayden] |
| Benton & Garrett | [Benton_and_Garrett] |
[Use to add context: "Nick and Benton have been the league's most active trade partners (12 deals all-time)"]
```

### REQUIRED OUTPUT FORMAT
```
**Rumor Mill**

**Trade Ideas**

- **[Manager A] sends [Player(s)] -> [Manager B] sends [Player(s)]**

[2-3 sentence rationale from extraction, framed by trade type]

- **[Next trade]**

[rationale]

[4 trade ideas total]

**Hot Streaks**

- **[Player]** ([Manager]): [reason - includes timeframe like "X% above projection over the last 4 weeks on [team]" or "since joining [team]", plus last 14 days trend]. [If trade_value_note exists: include "Sell high candidate" or "Elevated trade value" note.]
- [repeat for all candidates]

**Slump Watch**

- **[Player]** ([Manager]): [Underperformance %] below projection -> [reason]. [If better_fa_available exists: "**Replacement:** [better_fa_available] ([proj FPPG] FPPG)." If showing improvement in last 14 days: "Trending up -> hold for now." If neither: "No clear replacement available."] -> [reason]. [If better_fa_available: "Consider [player] as replacement." If showing improvement in last 14 days, note "Hold for now."]
- [repeat for all candidates]

[Optional last line, exactly:] **On the hub:** free-agent targets for every team are on the Advice page.
```

### KEY RULES
- **NO FREE AGENT TARGETS (4d).** They moved to the hub's Advice page; the stats report no longer prints them. Write none. Rumor Mill may end with the line above, exactly as shown, and nothing else about free agents (Slump Watch's "Better FA" replacement stays: it is part of Slump Watch as is).
- **THE ADVICE IS OFF until the new engine ships (Nick, 11-01).** While `season.legacy_advice` is "off", Section 10 of the stats report has no trade finder or waiver plans, only the line "The advice returns with the new engine." The page prints that line itself at the top of Rumor Mill: do not retype it, and write no advice, trade finder or waiver plans of your own. If you mention the advice anywhere, use that sentence word for word (never "Section 10 returns...": the claim check reads the 10 as an unsourced number). Hot Streaks, Slump Watch and the rest of Rumor Mill are unchanged.
- **TRADE FINDER AND WAIVER PLANS (when the stats report has the block):** the tables are rendered into the HTML automatically -- never retype them. Write around them.
  - **Never call a trade fair, and never say both sides "win".** Gains are measured against NOT trading. Every trade has a differential: say who moves ahead of whom ("Nick gains 200, Hayden 150 -- Nick moves 50 ahead, and both pull away from Benton and Garrett"). In a four-team league a trade is a two-on-two move.
  - The trade order is the smaller side's gain: how likely the reluctant side is to say yes. Do not describe it as a ranking of fairness or quality.
  - When the commissioner is a party, say so plainly.
  - A trade or add "on the table since week N" has gone unclaimed: that is a story (the model may be wrong, or there is a human reason). Use it; do not invent the reason.
  - A free agent recommended to more than one manager is a race -- the add window opens 12:01 Monday. Name everyone it was recommended to.
  - If the block says it did not run or is paused, say that in one plain sentence. Do not substitute trade ideas of your own.
- **BULLET FORMAT IS MANDATORY** -- Every item in Trade Ideas, Hot Streaks, and Slump Watch MUST be a bullet point (`- `) with a bold header. NEVER write these sections as flowing paragraphs. Each trade idea, each free agent, each hot/cold player gets its OWN bullet. This is critical for HTML rendering -- paragraphs break the card-style layout.
- **WRONG FORMAT (paragraphs):** "The analytics engine flagged four deals this week. The most intriguing has Nick sending Edwards to Benton for Maxey. Two other deals to watch: Hayden could swap Bridges for Giannis..."
- **CORRECT FORMAT (bullets):** Each trade on its own `- **bold header**` line with a paragraph underneath, each free agent on its own bullet, each hot/cold player on its own bullet. Follow the REQUIRED OUTPUT FORMAT exactly.
- **Trade Ideas get 2-3 sentence rationales** as a continuation paragraph below each bullet header
- **Hot Streaks, Slump Watch** are single-bullet items (header + detail in same bullet)

### TRADE TYPE FRAMING
- `swap` -> "A straightforward swap..."
- `2-for-1` -> "A consolidation play..."
- `sell-high` -> "Selling high on..."
- `buy-low` -> "A buy-low gamble..."
- `player + pick` -> "Adding draft capital..."


### INJURY BURDEN TRADE CONTEXT
Use `season_injury_burden` to add depth to trade rationales:
- **IL-heavy managers** (high il_injury_games) may be desperate for healthy depth: "Benton, with 79 IL games this season (Tatum alone at 41), might be willing to move a healthy contributor for long-term upside."
- **Healthiest managers** (low total_injury_burden_pct) can afford to buy low on injured stars: "Nick's league-low 17.6% injury burden gives him the roster flexibility to stash an injured player and wait for the playoffs."
- **High non-IL burden** managers keep getting hit by unexpected injuries: "Hayden's 15.7% non-IL injury burden suggests his roster is fragile -> consolidating into fewer, more reliable players could help."
- Frame trades around injury context when relevant, but don't force it if the trade rationale is already clear.

### DRAFT PICK OWNERSHIP CHECK (CRITICAL)
Before writing any trade idea that involves draft picks:
1. Check the **DRAFT PICK CONTEXT** block at the top of Section 10 in the stats report
2. Verify the manager actually owns the pick being offered (e.g., Garrett cannot offer his 2026 1st if he already traded it to Hayden)
3. If a trade idea from `rumor_mill.trade_ideas[]` says "a high pick" or "a lottery pick," look up what the manager's HIGHEST AVAILABLE pick actually is and name it specifically
4. Reference the pick's provenance when relevant: "Garrett's 2026 2nd rounder (originally Nick's, acquired in the Week 7 KAT deal)"

### TRADE HISTORY CONTEXT
Use `all_time_records.trade_partners` to add historical context to trade proposals:
- **Frequent partners:** "Nick and Benton have completed 12 trades all-time -> the league's most active partnership -> so this deal fits their history of finding mutually beneficial swaps."
- **Rare partners:** "Garrett and Hayden have only traded once in league history, making any deal between them noteworthy."
- **Context for specific trades:** "This would be the third Nick-Hayden trade this season, following the Jokic blockbuster and the depth swap in Week 4."
- Use trade history to make proposals feel more grounded and realistic.


### HOT STREAKS GUIDANCE
Use `trade_value_note` to provide actionable recommendations:
- **Sell high candidates** (25%+ above projection): Include the trade_value_note verbatim: "Sell high candidate - actual [X] FPPG unlikely to sustain."
- **Elevated trade value** (15-25% above): Include the trade_value_note: "Elevated trade value - producing [X] FPPG vs [Y] projected."
- **When trending up:** If `overperformance_index_last_14_days` is higher than `overperformance_index`, the reason will say "trending up" - note: "May have more room to run."
- **When cooling off:** If `overperformance_index_last_14_days` is lower than `overperformance_index`, the reason will say "cooling off" - note: "Sell window may be closing."
- Hot streaks are opportunities for contenders to sell high and rebuilders to cash in on unexpected value.
- The `reason` field already contains the timeframe ("over the last 4 weeks on [team]" or "since joining [team]") - use it directly.

### SLUMP WATCH GUIDANCE
Use `better_fa_available` to provide actionable recommendations:
- **When a replacement exists:** "Consider [better_fa_available] as a replacement -> projects for [X] FPPG vs [player]'s [Y] FPPG."
- **When no replacement exists:** "No clear upgrade available on waivers -> hold for now despite the struggles."
- **When showing improvement:** If `underperformance_index_last_14_days` is significantly better than `underperformance_index`, note: "Showing signs of life (only -8.2% last 14 days vs -22.9% last 4 weeks) -> hold and monitor."
- Always include the specific replacement player name when available; this is the most actionable part of the analysis.
- **CRITICAL: Use the `reason` field directly** - it already contains the correct timeframe ("over the last 4 weeks on [team]" or "since joining [team]"). NEVER say "season" or "season-long" - the underperformance is a 4-week rolling window, NOT full season performance.

---

## FINAL CHECKLIST

Before submitting, verify:

**Structure & Formatting:**
- [ ] ALL 10 sections present with `### **[N]. [Section Name]**` headers
- [ ] Every section began with DATA EXTRACTION before prose (even if output is clean-only)
- [ ] Every stat in prose came from extraction (no improvised numbers)
- [ ] Matchup headers use exact format: `**[Winner] [Score] def. [Loser] [Score]**` with TEAM NAMES, not manager names
- [ ] All bullet points use `- ` (standard markdown dash)
- [ ] Power Rankings has ONE table (no projected finish distribution, no Money and Exposure: they are on the hub)
- [ ] Stats Corner has THREE tables: Top Performances, Worst Performances, Waiver Pickups (no season tables, no free agents, no Keeper Watch)
- [ ] Title is `## **CHS Alumni Fantasy Basketball League -> Week [X] Newsletter**`
- [ ] Ends with `**End of Week [X] Newsletter**`

**Accuracy:**
- [ ] Trade references match SEASON TRADE LOG (no invented trade history)
- [ ] Draft pick mentions match DRAFT PICK OWNERSHIP (no suggesting picks that were traded away)
- [ ] Around the NBA headlines only cover events from the covered week (not prior weeks)
- [ ] Report cards ordered by `overall_score` descending (highest first), ties by `weekly_fp`; NOT alphabetical, by record or by letter grade
- [ ] No dollar figures unless the ANGLES block's "Money this week" line names something decided this week (rule 23), and each one names its pot and window, in any section; every lore clause attaches to a claim, not a name (rule 21)
- [ ] An award race appears only for a move the AWARD MOVES block lists, with its numbers (rule 24)
- [ ] ALL superlative claims ("most", "worst", "best", "first ever", "in league history") verified against historical data -- especially luck index, streaks, scores
- [ ] Magic number usage is correct: magic number of N means N total events (wins + rival losses), NOT "N wins"
- [ ] Elimination status is correct: check if teams are mathematically eliminated before writing "not quite eliminated" or similar
- [ ] Trade grade direction is correct: re-read side_a.sent_picks vs side_b.sent_picks after writing each trade analysis to confirm who gained/lost capital
- [ ] Benton still holds his own 1st round pick in addition to any acquired picks -- don't imply otherwise

**Format (commonly broken):**
- [ ] Rumor Mill uses BULLET FORMAT for ALL subsections (Trade Ideas, Hot Streaks, Slump Watch) -- never paragraphs; no Free Agent Targets
- [ ] No parenthetical injury shorthand anywhere -- "(2/3 games)", "(3 weeks remaining)", "(season-long)" etc. are all written in prose instead
- [ ] Betting Lines: each matchup is the line block, then 2-3 sentences on what decides it, then the "On the hub:" line exactly as the template gives it
- [ ] Upset/underdog language uses moneyline and/or spread, NOT win probability percentages
- [ ] No player-by-player injury breakdowns in matchup summaries -- just the total count (e.g., "11 games lost to injury")
- [ ] Stats Corner table headers do NOT include row counts like "(5)", "(30)", or "(all)"
- [ ] No duplicate section name headers (e.g., `**What If?**` appearing both as a section heading AND as a standalone bold line inside the section)
- [ ] Title/subtitle date range uses "to" (not dashes, arrows, or garbled characters)
- [ ] Around the NBA headlines are in the newsletter's voice (rule 19, VOICE.md), not news-wire style and not metadata labels
- [ ] Trade history numbers (e.g., "3 all-time deals") match the `trade_partners` data in the stats report

**Continuity (check LAST_WEEK_RECAP.md and RECENT_CONTENT.json):**
- [ ] Running threads from last week are continued or resolved (not dropped)
- [ ] "Looking Ahead" callbacks from last week are followed up on where relevant
- [ ] No headlines or section openers reused from RECENT_CONTENT.json
- [ ] No phrasing closely echoing last week's newsletter

---

## EXAMPLE: COMPLETE SECTION WITH EXTRACTION WORKFLOW

Here's how Section 5 (Fun Facts) should be produced:

### STEP 1: EXTRACT
```
From fun_facts[]:
1. "Hayden is 1 win away from 100 career victories" (category: milestone, managers: Hayden)
2. "Nick has won 13 consecutive head-to-head matchups against Garrett" (category: streak, managers: Nick, Garrett)
3. "Benton and Garrett are tied 31-31 all-time" (category: historical, managers: Benton, Garrett)
4. "LaMelo Ball's 73.25 FP game was the week's highest" (category: weekly, managers: Hayden)
5. "Garrett has won 4 straight against Hayden this season" (category: streak, managers: Garrett, Hayden)
```

### STEP 2: WRITE WITH CITATIONS
```
**Fun Facts**

- Hayden sits just 1 win away from 100 career victories [from extraction: fact 1] -> but he'll need to snap a 5-game losing streak [from extraction: current_streaks] to get there.

- Nick has won 13 consecutive head-to-head matchups against Garrett [from extraction: fact 2], a streak that dates back multiple seasons.

- Benton and Garrett are deadlocked at 31-31 all-time [from extraction: fact 3] -> the league's only perfectly even rivalry.

- LaMelo Ball's 73.25 FP explosion against the Lakers [from extraction: fact 4] was the week's single-best performance.

- Garrett has swept Hayden this season, winning all 4 matchups [from extraction: fact 5] -> their most lopsided season series ever.
```

### STEP 3: CLEAN (remove citations)
```
**Fun Facts**

- Hayden sits just 1 win away from 100 career victories -> but he'll need to snap a 5-game losing streak to get there.

- Nick has won 13 consecutive head-to-head matchups against Garrett, a streak that dates back multiple seasons.

- Benton and Garrett are deadlocked at 31-31 all-time -> the league's only perfectly even rivalry.

- LaMelo Ball's 73.25 FP explosion against the Lakers was the week's single-best performance.

- Garrett has swept Hayden this season, winning all 4 matchups -> their most lopsided season series ever.
```

---

**End of Template**

---

# POSTSEASON EDITION ADDENDUM (Weeks 16-23)

This section applies **only** from Week 16 onward. From 2026-27 the postseason
is EIGHT weeks and there are THREE separate champions, so "the playoffs" is no
longer one thing. Everything below replaces the old two-week addendum.

If a section is not mentioned here, it runs identically to the regular season.

---

## THE THREE CHAMPIONS -- GET THIS RIGHT

This is the single most important thing in this addendum. Confusing these is
the mistake a reader will notice immediately.

| Title | Decided by | When | Prize |
|-------|-----------|------|-------|
| **League Champion** | Best record over Weeks 1-15 | Already decided by Week 16 | $180 ($90 each from 3rd and 4th) |
| **Playoff Champion** | Best-of-3 bracket, Weeks 16-21 | Week 21 | $90 ($45 each from 3rd and 4th) |
| **Cup Champion** | Single elimination, Weeks 22-23 | Week 23 | An extra (6th) keeper next season |

The **League Champion is the real champion** of this league. The regular season
decides the money, the draft order, and the banner. The bracket winner is the
**Playoff Champion** -- a separate, secondary title. Never call the bracket
winner "the league champion" and never imply the regular season was a
qualifier for the bracket.

---

## POSTSEASON CALENDAR

- **Weeks 1-15:** Regular season. 5 meetings against each of the 3 opponents.
  Odd on purpose -- no season series can end drawn.
- **Weeks 16-18: Semifinals, best-of-3.** #1 seed vs #4, #2 vs #3. Seeds come
  from the FINAL regular-season standings and never move.
- **Weeks 19-21: Final and Third Place, best-of-3.** Semifinal winners play for
  the Playoff Championship; semifinal losers play for 3rd.
- **Weeks 22-23: The Cup.** Single elimination, seeded by TOTAL POINTS across
  Weeks 1-21. Week 22 is #1 vs #4 and #2 vs #3; Week 23 is the Cup Final.

**Every week of a series is played even after the series is decided.** A 2-0
lead still plays its third week. Those points are not meaningless -- they feed
the Cup seeding, which is points-based. Say so; it is a real strategic wrinkle.

**Cup seeding is points, not record.** A manager knocked out in the semifinals
can be the #1 Cup seed. This is the most counter-intuitive thing about the new
format and worth explaining every time it comes up.

---

## WHICH NEWSLETTER COVERS WHAT

**Newsletter N covers Week N** -- the week just finished -- and previews Week
N+1. The number is the week COVERED, never the week the newsletter goes out
in: WEEK17_NEWSLETTER.html reports "Week 17", and the injury-timeline rule
above reads current_week as N in a Week N newsletter.

This list used to be numbered by publication week, one ahead of the files.
Both numbering schemes were internally consistent, which is why it survived:
"the Week 16 newsletter" named two different newsletters depending on
whether you were reading the template or the output directory. It put the
League Champion one newsletter late and named the wrong bracket stage in
every postseason week.

- **Week 15 newsletter:** the REGULAR SEASON FINALE and the crowning of the
  League Champion. This is the biggest newsletter of the year. Previews the
  semifinal series.
- **Weeks 16-17:** mid-series. Report the series score ("Nick leads 2-0"), not
  just the week result.
- **Week 18 newsletter:** covers the semifinal results. Who advanced, who fell.
- **Weeks 19-20:** the Final and Third Place series in progress.
- **Week 21 newsletter:** covers the end of the bracket and crowns the Playoff
  Champion. Introduces the Cup, its points-based seeding, and what is at stake.
- **Week 22 newsletter:** covers the Cup semifinals; previews the Cup Final.
- **Week 23 newsletter:** crowns the Cup Champion and states plainly that they
  keep a sixth player next season while everyone else keeps five.

---

## SECTION-BY-SECTION MODIFICATIONS

### 1. Matchup Summaries
- Report the SERIES state, not only the week: "Hayden takes Game 2, leads the
  series 2-0 with one to play."
- A dead rubber (a third week of a 2-0 series) still gets written up. Frame it
  as it is: pride, points for Cup seeding, and momentum.
- All stat extraction and formatting rules are identical to regular season.

### 2. Report Cards
- Same grading system, same format.
- Add postseason readiness context: who is peaking, who is limping, who is
  healthy.

### 3. Betting Lines (Looking Ahead)
- Preview the coming week of whichever series is live.
- In a series, note the series price as well as the week price where the data
  supports it -- being down 0-2 changes what a weekly favorite means.
- During the Cup, these are single elimination games. Say so.

### 4. Player of the Week
- No changes.

### 5. Fun Facts
- No changes.

### 6. What If
- No changes.

### 7. Power Rankings -> **Playoff Championship Odds**

The section header becomes **"Playoff Championship Odds"**. Extract from the
`playoff_odds` block, not the regular `power_rankings` block.

Money and Exposure is on the hub, not in this section (4d). A dollar figure
appears only in a week that decided money (rule 23), naming its pot and window.

#### DATA EXTRACTION (do this first)
```
From playoff_odds:
  playoff_round: [pre_playoffs | semifinals | final | complete]
  round_weeks:   {"Semifinals": [16, 18], "Final": [19, 21], "Third Place": [19, 21]}
  sweep_probability: {"Semifinals": X.X, "Final": X.X}   # chance a series ends 3-0

  For each series in semi_matchups[]:
  - manager_a: [name], seed: [#], win_prob_a: [X.X%]   # SERIES win probability
  - manager_b: [name], seed: [#], win_prob_b: [X.X%]
  - weeks: [16, 18], format: "best-of-3"

  For each manager in finish_distribution:
  - [manager]: 1st [X.X%], 2nd [X.X%], 3rd [X.X%], 4th [X.X%]

  championship_matchup_probs:
  - [ManagerA vs ManagerB]: [X.X%]
```

**`win_prob_a` is the chance of winning the SERIES, not a single week.** Do not
describe it as a weekly win probability.

Use `round_weeks` for every week number you print. Do not write "Week 22"
because a previous newsletter did -- the bracket moved.

#### REQUIRED OUTPUT FORMAT

**Table 1: Semifinal Series (Weeks 16-18, best-of-3)**
```
| Series | Higher Seed | Series Win Prob | vs | Lower Seed | Series Win Prob |
|--------|-------------|-----------------|-----|------------|-----------------|
```

**Table 2: Playoff Championship Probability**
```
| Seed | Manager | Record | Playoff Champ % | Runner-Up % | 3rd % | 4th % |
|------|---------|--------|-----------------|-------------|-------|-------|
```

**Table 3: Most Likely Final**
```
- [Team A] vs [Team B]: [X.X%]
```

Then **3-4 paragraphs of narrative**, covering:
- Why the favorite is favored, and how much a best-of-3 protects them compared
  to the old one-week bracket (a single bad week no longer ends a season)
- The underdog's path: they need two good weeks out of three, not one
- How the other series shapes up
- Keeper quality and draft capital as the consolation narrative

**DO NOT include:**
- Magic numbers (not applicable)
- Expected regular season records (the regular season is over)
- Standings race language
- Any suggestion that this decides the league title -- it does not

### 7B. The Cup (Weeks 22-23 only)

When the stats report has a `cup_odds` block, add a section after Section 7.

```
From cup_odds:
  cup_round:      [pre_cup | semifinals | final | complete]
  seeds:          {manager: 1-4}          # by POINTS, not record
  seeding_points: {manager: total}        # weeks 1-21
  seeding_weeks:  [1, 21]
  cup_odds:       {manager: X.X%}
  round_weeks:    {"Cup Semifinals": [22, 22], "Cup Final": [23, 23]}
  keeper_stakes:  {season_affected, base_keepers, winner_keepers, recorded_winner}
```

Lead with the seeding table and say what it is seeded on. A manager who lost
in the semifinals but scored the most points over 21 weeks is the #1 Cup seed,
and that deserves a sentence.

Always close the Cup section with the stakes: the winner keeps
`winner_keepers` players in `season_affected` and drafts rounds 1-9; everyone
else keeps `base_keepers` and drafts rounds 1-10. One round of that draft has
three picks in it instead of four.

### 8. Stats Corner
- No changes.

### 9. Around the NBA
- No changes to format.

### 10. Rumor Mill
- Reframe all trade ideas as OFFSEASON moves. Rosters are locked.
- "Buy low" and "sell high" are about keeper value heading into the draft.
- From Week 22 onward, keeper talk has to account for the Cup: the winner keeps
  six and the other three keep five, so the same player is worth more to
  whoever is still alive in the Cup.

---

## LANGUAGE REMINDERS FOR POSTSEASON WEEKS

| Instead of... | Write... |
|--------------|----------|
| "League champion" (for the bracket winner) | "Playoff Champion" |
| "The playoffs decide the title" | "The regular season decided the title; the bracket decides the Playoff Championship" |
| "Title odds" | "Playoff championship odds" |
| "Power Rankings" (as section name) | "Playoff Championship Odds" |
| "Clinch", "magic number" | Not applicable -- the regular season is over |
| "Standings race" | "Bracket" or "series" |
| "Wins the week, wins the series" | "Leads the series 2-1" |
| "Meaningless game" (a dead rubber) | "Still counts -- Cup seeding is points-based" |
| "Waiver pickup this week" | "Offseason target" (rosters locked) |

---

## SPECIAL NOTES

**Week 15 newsletter (regular season finale).** The League Champion is
crowned here, along with the $180 payout and the draft order. This is the
headline of the year -- do not bury it under a bracket preview. The money
rule (rule 23) expects the $180 in THIS newsletter: week 15 is where the
race is decided, so week 16 carries no money event and a dollar figure
there is flagged.

**Week 21 newsletter (Playoff Champion crowned, Cup introduced).** Two stories:
the bracket result, and the Cup nobody has played before. Explain the
points-based seeding from scratch; it will be unfamiliar.

**Week 23 newsletter (Cup Champion crowned).** State the keeper consequence
explicitly. Then tease the offseason: keeper decisions, the draft order from
the regular-season standings, and next season's outlook.

**A reminder for whoever maintains this:** none of the week numbers above are
hardcoded in the engine. They come from `postseason_format` in
`config/league_config.json`. If the format changes again, change it there,
run `py scripts/verify_project_integrity.py`, and then update this addendum.

---

**End of Postseason Addendum**
