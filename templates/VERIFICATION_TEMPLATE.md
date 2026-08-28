# Newsletter Verification Template

Step 8 of `WEEKLY_WORKFLOW.md`. Run this after the draft is assembled into
`assets\WEEK{N}_DRAFT.md` and before `newsletter_html_generator.py`.

The drafting chat wrote the newsletter. This is a **fresh chat** that has never
seen the draft being written -- that separation is the point. A chat that just
argued itself into a claim is the worst possible auditor of it.

---

## How to Run

1. Open a new chat (not the drafting chat, not the project chat)
2. Upload:
   - `assets\WEEK{N}_DRAFT.md` -- the draft to audit
   - `output\stats_report_week{N}.md` -- the single source of truth
   - `output\stats_report_week{N-1}.md` -- *(only for claims about last week)*
   - `templates\VERIFICATION_TEMPLATE.md` -- this file
3. Paste the prompt below, filling in `[FILL IN]`
4. Fix every P0 and P1 finding, then re-run if the fixes were substantial

**Ground rule:** the stats report is the only source of truth. If a number in
the draft is not in the stats report, it is wrong -- even if it sounds right,
and even if it is true. Unverifiable is a finding.

---

## The Prompt

```
You are fact-checking a fantasy basketball newsletter before publication. You
did not write it and you have no stake in it. Your job is to find errors.

FILES
- WEEK[FILL IN]_DRAFT.md -- the newsletter draft under audit
- stats_report_week[FILL IN].md -- the ONLY source of truth for every number

METHOD (do not skip)
1. Read the stats report FIRST, completely, before reading the draft.
2. Read the draft one section at a time.
3. For EVERY numeric claim, superlative, and causal statement in the draft,
   locate the supporting line in the stats report and quote it.
4. If you cannot find support, that is a finding. Do not reason your way to
   it being probably fine. "Probably fine" is how errors ship.

Work through the checklist below in order. Report using the output format at
the end. Do not rewrite the newsletter -- report findings only.
```

---

## P0 -- Factual Errors (must fix before publishing)

These are the five failure modes Step 8 exists to catch.

### 1. Wrong superlatives

Every "most", "least", "best", "worst", "first", "ever", "all-time", "record",
"career-high", "season-high".

- [ ] Each superlative is checked against the historical table that covers it
      (`historical_luck` for luck claims, career/all-time tables for record
      claims, season tables for season claims)
- [ ] A claim that something is "the worst ever" is not actually 6th all-time
- [ ] Scope words match the data checked -- "worst of Hayden's career" needs
      career data, not season data
- [ ] Ties are not written as sole ownership

### 2. Misattributed stats

- [ ] Every player's FP, game count, and FPPG match the stats report row for
      **that player**, not a neighboring row
- [ ] Every player is attributed to the manager who actually rostered them
- [ ] NBA teams named for players are correct
- [ ] Manager totals match the report; margins equal the difference of the two
      scores as written

### 3. Incorrect injury timelines

- [ ] Return timelines match `INJURY_OVERRIDES.json`, not invention
- [ ] Weeks-remaining counts are consistent with the current week number
- [ ] A player described as back was not still listed out, and vice versa

### 4. Wrong record references

- [ ] Season records (W-L) match `current_standings`
- [ ] Head-to-head season series and all-time series match the report
- [ ] Streak lengths match, and direction (won/lost) is correct
- [ ] Standings positions are consistent with the records quoted

### 5. Fabricated details

- [ ] No score, date, quote, or event appears that is absent from the stats
      report (or, for Around the NBA only, from a cited web source)
- [ ] No invented narrative causation ("he was pressing after last week")
- [ ] Around the NBA items are real, from Week N, and correctly dated

---

## P1 -- Rule Violations (template rules with known past failures)

Keyed to CRITICAL RULES in `newsletter_template.md`.

### Injury glossary (Rules 8, 10) -- the most common error

The six terms are NOT interchangeable. Check every injury number:

- [ ] "Games lost to injury" is used only for the non-IL count
      (`non_il_injury_games`), never for the combined figure
- [ ] "IL games" (`il_injury_games`) is cited separately, as context
- [ ] A combined figure is labeled "total injury games"
      (`total_injury_games`) -- never "games lost"
- [ ] "Games left on bench" (`games_left_on_bench`) appears in roster-
      management discussion, not injury discussion
- [ ] "Blunders" are only the subset with an available starter slot, and are
      named with the specific player and slot
- [ ] The identity holds: scheduled = played + lost to injury + left on bench

### Efficiency vs injuries (Rule 9)

- [ ] Injuries are never described as hurting, tanking, or dragging down
      efficiency -- these are separate facts

### Magic number (Rule 14)

- [ ] A magic number of N is described as ANY COMBINATION of N events
- [ ] "One win clinches" appears only if the magic number is literally 1

### Elimination status (Rule 15)

- [ ] Teams described as eliminated are mathematically eliminated
- [ ] Teams described as alive actually are -- check games back vs weeks left

### Trade grade direction (Rule 16)

For each graded trade, re-read `side_a.sent_picks` and `side_b.sent_picks`
AFTER reading the grade narrative:

- [ ] The manager described as acquiring capital actually received more than
      they sent
- [ ] Pick rounds in the prose match the pick rounds in the data

### Time boundaries and tense (Rule 7)

- [ ] Week N results are past tense; Week N+1 previews are future tense
- [ ] News from after Week N ended is framed as upcoming, not as happened

### Odds language (Rule 12)

- [ ] Prose uses American odds and point spreads
- [ ] Win-probability percentages appear only in stat blocks, never in prose

### Repetition (Rule 6)

- [ ] Detailed injury breakdowns appear once, not repeated across sections
- [ ] Storylines are not retold nearly verbatim in a later section

---

## P2 -- Format and Style

- [ ] Table headers match the template exactly, with no row counts appended
      like "(5)" or "(all)" (Rule 17)
- [ ] No section name appears twice as a header (Rule 18)
- [ ] Date ranges use the word "to", not dashes or arrows (Rule 20)
- [ ] Around the NBA headlines read like sports headlines, not database
      labels (Rule 19)
- [ ] Injury timelines are prose, not parentheticals like "(2 weeks, calf)"
      (Rule 11)
- [ ] No leftover `[from extraction: ...]` citations (Step 4: CLEAN)
- [ ] No `[FILL IN]` or template placeholders left in the text
- [ ] All ten sections are present and in order
- [ ] Manager and team names are spelled as in `league_config.json`

---

## Section Sweep

A final pass, one section at a time. Each has a characteristic failure:

| # | Section | Watch for |
|---|---------|-----------|
| 1 | Matchup Summaries | Score/margin arithmetic; injury glossary misuse |
| 2 | Report Cards | Grades inconsistent with the numbers cited; blunder attribution |
| 3 | Betting Lines | Spread direction and cover math; probability language in prose |
| 4 | Player of the Week | FP/games/FPPG all from the same player row; POTW count history |
| 5 | Fun Facts | Superlatives -- highest concentration of unverified claims |
| 6 | What If? | Counterfactual uses real bench numbers, not invented lineups |
| 7 | Power Rankings | Movement claims match last week's actual positions |
| 8 | Stats Corner | Table count matches the template; figures match the report |
| 9 | Around the NBA | Real, correctly dated Week N news; trade grade direction |
| 10 | Rumor Mill | Speculation is clearly framed as speculation, not fact |

---

## Output Format

Report findings only. Do not rewrite the newsletter.

```
## P0 -- Factual Errors
1. [Section N] CLAIM: "<quote from draft>"
   REPORT SAYS: "<quote from stats report, or NOT FOUND>"
   FIX: <the corrected sentence>

## P1 -- Rule Violations
(same format, naming the rule number)

## P2 -- Format and Style
(one line each)

## Unverifiable
Claims with no supporting line in the stats report. These are not
necessarily wrong -- they are unsupported, which is its own problem.

## Verdict
READY TO PUBLISH  /  FIX P0 AND RE-CHECK
Counts: P0 <n>, P1 <n>, P2 <n>, Unverifiable <n>
```

If there are zero findings, say so plainly -- do not manufacture nitpicks to
look thorough. A clean draft is a real outcome.
