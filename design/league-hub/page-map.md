# Page map

Every screen, what's on it, and which components build it, in the order they appear. "Engine" means the value comes precomputed in the hub's data and the page only shows it.

## Home

The big things, in this order:

1. **AppHeader**: week, date, search, freshness (stale banner when stale), and the line's engine string: "Line priced Wed Nov 18, 3:30 PM Pacific", or, between the closing run and the next pricing, "Closing line priced Mon Nov 23, 6:55 PM Pacific" (4c2). 5a: and the NBA injury report's line ("NBA injury report filed Thu 3:15 PM Pacific."), as the current header shows it; its flags show as notes under the header with the engine and H52 closing-line notes. **The current hub's links** (`#v-main`, `#v-roster-<manager>`, `#v-chart`, `#v-block`, `#v-advice`, `#v-last`, `#v-mu<week>-<n>-<sum|win|flow>`) land on Home, the team, League › Standings, Market (Block or Advice), Matchups, and the matchup page with that segment.
2. **IssueBar**: "Latest issue · Week N: <headline>", which opens the newsletter.
3. **This week's matchups**: one **MatchupCard** per matchup, in the engine's order. Eyebrow title on `canvas`, meta "Day N of 7".
4. **Power rankings**: a Card of **RankingRow**s (title odds, 4-week sparkline, change).
5. **Teams**: a 2×2 grid of team summary cards. Each card is a **TeamMark** + name + manager + four nested values: record, title odds, adds left, injured. The whole card is a link.
6. **Trade block**: a Card listing each team's stance (Buying / Selling / Neutral as a neutral `StatusChip`), then "On the block" and "Untouchable", or "Nothing listed." ("What they want" is dropped: the block does not record it; 4b decision 6.)
7. **TabBar**.

## Matchups

- **List:** every matchup this week as **MatchupCard**s, then the **games grid** (a **HeatGrid** of starts per team, **3 weeks out**, shaded by rank within each week; tap a cell for its starts by day), then **Last week** (4c2; 4b decision 11): each of last week's matchups with its final scores, the result, and how Monday's closing line did ("Nick −72 · 61% at the close", then "Nick covered: won by 140", "won by 50, short of the spread", "Push" or "Upset: Benton won by 236"; "No closing line that week" when there was none). A tap opens that matchup as it stood at the end.
- **Last week's matchup page** (`#/matchups/w4-0`): the final scores (the winner bold), the win bar at 100/0, **SegmentedTabs** Summary (the closing line and its verdict, the Final paragraph, Monday's preview) / Win % (with the final point) / Game flow (every day banked).
- **Matchup page:**
  - a white top bar (back to Matchups);
  - both teams (**TeamMark** 36, name, score `display-xl`, projection);
  - the **win bar** with both percentages;
  - **SegmentedTabs**:
    - **Summary:** the engine's key facts, starts left, who's missing.
    - **Win %:** a **LineChart** of win chance through the week. Events are small hollow up/down markers with no text on the chart; tap one for the **Tooltip** ("Fri 3:15 PM · Dejounte Murray D→O · LM −4.2%"); tap any other point for the readout line.
    - **Game flow:** a **LineChart** of cumulative points by day for both teams, with projections dashed.
    - **Lines:** spread, total and moneyline as nested **KpiTile**s, with how they moved since Monday.
  - **Starts left** (**HeatGrid** by day): tap a team's day for the **Tooltip**: who starts that day, a Q who fits if he plays, and who is out tonight.
  - **Who's missing** (rows with swatch, name, reason, **StatusChip**).

## Teams

- **List:** four team cards (as on Home, larger).
- **Team page:**
  - a white top bar;
  - **TeamMark** 72 (Yahoo picture or monogram), name `display-lg`, "manager · record · Power #2 · PF" (the power ranking, labelled so it is not read as the standings place; 4b decision 5);
  - **SegmentedTabs**: Roster / Schedule / Moves / Keepers.
  - **Roster** tab:
    - 2×2 **KpiTile**s: title odds with sparkline, this week's win chance, points for vs the league average, adds left with reset day.
    - The **RosterTable** (IL slots apart): Simple = FPPG, GP, Proj, Next; Detailed = the chip row Value · Form · Schedule · Health · Keeper · Profile · All (RosterTable README, 4c2). Every value is the engine's string; Team value is the points he adds to this team's best daily lineups over advice's two weeks against the best free agent in his place, and Title Δ is Team value at the causal price of a point, in title-odds points (it always has Team value's sign).
    - **Likely keepers**: ranked rows with keep-chance bars (`lh-bar-h` in the team colour).
  - **Schedule** tab: next 3 weeks of games per player (**HeatGrid**); tap a cell for the days he plays ("Wk 5 · Mon · Wed · Fri · Sun", back-to-backs and "out" days marked; "IL slot · back 01-25" on a dash).
  - **Moves** tab: this team's moves ledger (date, add/drop, players).
  - **Keepers** tab: keep chance, rank on the team, and POT for each player.

## Players

Built in 4c1 (mockups `mockups/Players.html`, `mockups/Players-Compare.html`).

- **AppHeader** carries a search button (`lh-iconbtn`) that opens Players with the search field focused.
- **Search and browse** (`#/players`):
  - a search field over every player the hub has a card for (the rostered players and the free agents it names). The engine gives each player a folded search key ("jokic" finds "Jokić"); the page folds what is typed the same way and only matches strings;
  - **SegmentedTabs**-style **All / Rostered / Free agents**;
  - filter chips: **Position**, **Team** (NBA), **Age** (24 and under, 25–29, 30 and over), each a native picker inside a pill, and a **Healthy only** toggle. The engine assigns every player's values;
  - a sortable table: player (name, team chip in the manager's colour or "FA", positions · NBA team, status chips), **OVR** with its weekly change, **POT**, **FPPG**, **Next** (next week's games he will play). Sorting uses the engine's orders (best first, then reversed); a missing value sorts last both ways. A free agent's OVR and POT cells are "—", explained by the OVR column's InfoTip;
  - **Risers this week**: the biggest OVR gains against the ratings at least 7 days old, each with the engine's one-line reason (which of OVR's terms moved most). The section is absent, not empty, until such a line exists.
- **Player card** (`#/players/<key>`), opened by every player name in the hub:
  - **PlayerHero**: a white top bar with Back and **Compare**; square headshot (initials in `ink-3` when there is no photo); OVR ring and POT with their weekly changes (a free agent: FPPG and its percentile among the rostered players instead, with an InfoTip); team chip or "Free agent"; name; positions · NBA team · age; status chips ("Healthy" when none); the archetype only when enabled (or marked "Preview" in a local preview);
  - **SegmentedTabs**:
    - **Season:**
      - 2×2 **KpiTile**s: FPPG vs last season, games of team games, total FP with its rank among the rostered players, last 14 days vs season. NBA numbers lead, with the league-roster figure as one secondary line where it differs.
      - **Attributes:** 8 **GradeTile**s (the five categories, durability, consistency, schedule with its 3-week game count); tap a tile for what it measures. Free agents get a line instead: the grades rank the rostered players.
      - **Fantasy points by game:** a **BarChart** with his average; tap a bar for the game.
      - **Keeper outlook:** keep chance and rank on his team.
      - **Last 5 games:** a small table: Day, Opp, FP, **MIN** (4a3: a game's minutes as soon as its day has them, "loading" before, — on an injured day).
      - Under the KpiTiles, one context line with an InfoTip (4a3): "MIN 31.4 a game this season · MIN Δ +2.3" (MIN Δ's reason when it has no value; "MIN loading · MIN Δ loading" before the backfill; no line with no games). The 2×2 tiles stay.
    - **Career:** the FPPG trend (**LineChart**) and the by-season table with the career line.
    - **Keeper:** keep chance beside POT (4a decision 2), rank on his team, and this league's age curve (**LineChart**, his age marked).
    - **History:** ownership by season, draft slots, trades, record-book entries.
- **Compare** (`#/players/compare/<a>` picks the second player with the same search; then `#/players/compare/<a>/<b>`): two square headshots (`headshot-compare`, 96 px), names, team chips and OVR rings (`ring-compare`, 56 px); then rows of POT, FPPG, L14, MIN (4a3; more is better), Avail %, games in the next 3 weeks, Keep %, Age and the five category grades. The better value in each row is `ink-strong` weight 800 (not colour), decided only by the engine's integer order keys; Age has no winner, and a missing value ("—", e.g. a free agent's OVR or Keep %) wins nothing.

## Market

SegmentedTabs, in this order (4c3, the Advice mockup's): **Available · Stash · Advice · Block · Moves**. Advice is there only while `advice.hub` is on.

- **Available:** filter chips (Healthy; Position; Sort: L14, FPPG, projected points), then the free-agent table: Player (name, positions · NBA team, status chips), FPPG, L14 (sortable headers) and the **3-week game cells**. Each cell is a 44 px tap that opens the Tooltip with the days it counts (the engine's day list; "out" days in its foot). The rows are the ones the current page lists (the best by projected points over the three weeks, plus every player dropped in the chat), so every name has a card.
- **Stash:** players worth holding (OFS, or O with an injury entry), with their return dates as status chips, the open IL slots, and the rule note.
- **Advice:** the **Advice** component (one card per team, in the page's team order). See `components/Advice/README.md`.
- **Block (TradeBlock):** the trade block in full, one row per team: the team chip, its stance (Buying / Selling / Neutral, with "since MM-DD"), then **On the block** and **Untouchable**, each player with positions · NBA team · since. No "what they want" anywhere (4b decision 6). The foot: how to change it, and the deadline.
- **Moves:** every add, drop, claim and trade of the season, newest first, with team filter chips (All teams + one per team). Each move: its marker (**+** add, **−** drop, **⇄** trade, **IL** a chat IL step), the team chip(s), each part with its own marker, and the day and time. Yahoo logs no IL slot changes, so IL steps show only while a chat entry is pending.
- Every player name opens his card; every team chip opens the team.

## League

SegmentedTabs, in this order (4c4): **Standings · History · Awards · Archive**. Routes: `#/league/<segment>`, `#/league/history/<chip>`, `#/league/history/h2h/<a>/<b>` (a cell open), `#/league/history/draft/<season>`. The tab remembers its segment for the session.

- **Standings:**
  - **The regular-season table** (weeks 1–15), in `data_loader.standings_order` (winning percentage, a T counting half; then head-to-head; then points): rank, TeamMark (24) and the manager's first name (the team's name in the label: the table must fit 360 px), W-L (a T shows: 4-3-1), PF, Strk (W3, L2, T1: every week counts, a T ends one), and the title odds with their change since the run before stacked under them. A tie the rules broke marks both ranks with `*` and the note says how ("… level at 4-3-1: ordered on head-to-head"). The record counts a finished week exactly as Home does (the latest title-odds run's banked weeks, `title_odds_run.banked_results`: the two never disagree, and a disagreement raises); PF counts the weeks the weekly build has recorded, as Home's does, and the note says when a banked week is in the record and not yet in PF.
  - **Title odds over the season:** a **LineChart** of the four teams' regular-season title odds, **one point per run** (the history file; before it began, each published weekly report), 0–100% with gridlines at 25/50/75, week ticks, direct end labels. **Event markers** (the Tooltip): a week's results (the first run after the week ended: "Week 4 final: SF beat LM, BL beat BN", the two biggest swings in the foot), a closing line, a trade. A cause that moved no line by 0.05 points gets no marker. Tap any point for its run in the readout.
  - **Power rankings by week:** **RankingRow**s for each week's published power rankings (the weekly report), newest first: rank, TeamMark, team, record, title odds, and the change in rank (▲ 1 / ▼ 1 / –; — in week 1).
- **History:** filter chips **Champions · All-time · Head to head · Records · Draft · Trades**. Each chip is its own encrypted file, loaded on its first tap (`HUB.part`); the plaintext preview carries them as templates.
  - **Champions:** newest first. This season (in progress; the Cup's first edition, weeks 22–23), then each season with its champion (TeamMark, that season's team name, the manager), runner-up and regular-season winner; a season with no bracket says so (2019-20); **2016-17: Not played**; **2014-15 and 2015-16** in one row, records only: their champions and regular-season winners, the season each came in not recorded.
  - **All-time standings:** every season with records (2014-15 and 2015-16 from LEAGUEHISTORY, 2017-18 on, and this season live), the scope named in the note: rank, TeamMark and manager with his playoff record under, W-L-T with win % under, PF, Champ (playoff titles), 1st (regular-season titles).
  - **Head to head:** the **HeadToHead** grid (component), with chips **Regular season · Postseason · Cup**. Tap a cell for the pair's seasons.
  - **Records:** four **KpiTile**s (highest week, biggest blowout, closest game, best player game), then the record book's lists by group (team weeks, team seasons, player games, weeks, seasons, careers, duos, moves), each a disclosure with its leader on the summary line and its top ten inside. A record with a game opens the Tooltip with that week's final. Then **Awards (4c6)**: three KpiTiles, one per past award, its all-time best season by the award's own measure (Best MVP season, Most lopsided trade, Most improved season), with the season and its regular-season length; a tap opens the Tooltip (the shown-with figure, the trade's sides, the length).
  - **Draft:** the **DraftTable** (component), a season select (this season first).
  - **Trades:** every trade, newest first: the date and season, both team chips (⇄), and what each side got: players (cards where they have one) and draft picks named by their original owner.
- **Awards** (4c5; the whole segment is one lazy part, opened on its first show; `#/league/awards[/<award>]` scrolls to an award): one card per award, in this order: **MVP · Best pickup · Most improved · Rookie of the Year · Trade of the Year · Bust of the Year**. Each card: the award's name, a **StatusChip** (Live, or Final after week 15), "through week N" and its **InfoTip** (the one-line definition); "New leader: X (was Y)." when the top spot changed since last week; the **top five RankingRows** with a player instead of a team: rank, the player (his card), the team chip (the team), the shown-with figure ("wins swung: 3", "44.0 vs 36.2 usual", "dropped X on 11-09", "expected 42.2, 30.6 in 14 games"), a second line (starts; a traded player's PAR by team), and at the right the value, its unit (PAR, FPPG, PAR gap, pts short) and the move against last week (▲ 2 / ▼ 1 / – / new; nothing in week 1). A trade row is the two teams with what each got (cards) and its PAR. Then the **race chart** (LineChart): today's top five's measure at each finished week, a line per player in his team's colour (a gap where he was outside that week's stored top 10), direct end labels (last names; first names when two last names match), no legend; tap or scrub a week for every value in the readout. Under two weeks of lines: the list only. **MVP's odds (4c6):** each MVP row also carries "61% to win" ("under 1% to win", "over 99% to win" at the ends) beside the shown-with figure; under the rows a line "Odds to win" with the odds' day ("as of Wed 11-18") and its own **InfoTip** ("The chance he finishes the regular season with the most PAR, from the same simulation as the title odds."), "Also in the running:" anyone outside the five at 1% or more, "Everyone else: <1% combined.", and the odds' history note (it starts with the first week priced at its end: no backfill). No odds once the award is Final. Once two weeks have odds, a **FilterChips** pair over the chart (**PAR · Odds**, aria-pressed) swaps the race chart for the **odds chart** (the same LineChart, 0–100%, the contenders' odds at each week's end). Without odds (none priced yet, or the file unreadable) the line says why. Then **Past winners (4c6)** for MVP, Most improved and Trade of the Year: a disclosure ("2025-26 back to 2017-18"), one row per past season, newest first: the season, the winner (his card) or the trade, the manager's team chip and that season's team name when it differs, the shown-with figure, the value and unit; a season without one says why ("no regular-season trade"). It comes from the History side file (static public history, `data/historical/AWARDS_PAST.json`), not the payload. Under it, the exclusions summed with their reasons ("Not eligible: 93 under 20 games this season.") and, for Bust, the expectation's source. An award that cannot be computed says why (Rookie of the Year until `config/ROOKIE_SEASONS.json` has the season's rookies). After the six: **Player of the Week** by season, newest first: week, the player (his card), the team chip, points with games and FPPG; a week whose points were not recorded takes them from the league log (his started games that week), marked "from the league log".
- **Archive:** every issue, newest first: the week number, its dates, the headline once issues have one (4d), the size; a tap opens it in its original look (IssueBar's rule: `HUB.openIssue` when published, the plaintext file in the preview).

## Every screen

- Freshness is shown.
- Every team mark or chip opens the team.
- Every player name opens his card.
- Every non-obvious number has an **InfoTip** the first time it appears.
