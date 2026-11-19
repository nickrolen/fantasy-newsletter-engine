# Page map

Every screen, what's on it, and which components build it, in the order they appear. "Engine" means the value comes precomputed in the hub's data and the page only shows it.

## Home

The big things, in this order:

1. **AppHeader**: week, date, search, freshness (stale banner when stale), and the line's engine string: "Line priced Wed Nov 18, 3:30 PM Pacific", or, between the closing run and the next pricing, "Closing line priced Mon Nov 23, 6:55 PM Pacific" (4c2).
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
      - **Last 5 games:** a small table.
    - **Career:** the FPPG trend (**LineChart**) and the by-season table with the career line.
    - **Keeper:** keep chance beside POT (4a decision 2), rank on his team, and this league's age curve (**LineChart**, his age marked).
    - **History:** ownership by season, draft slots, trades, record-book entries.
- **Compare** (`#/players/compare/<a>` picks the second player with the same search; then `#/players/compare/<a>/<b>`): two square headshots (`headshot-compare`, 96 px), names, team chips and OVR rings (`ring-compare`, 56 px); then rows of POT, FPPG, L14, Avail %, games in the next 3 weeks, Keep %, Age and the five category grades. The better value in each row is `ink-strong` weight 800 (not colour), decided only by the engine's integer order keys; Age has no winner, and a missing value ("—", e.g. a free agent's OVR or Keep %) wins nothing.

## Market

- **Free agents:** a sortable table with 3-week games (Simple/Detailed).
- **The stash:** players worth holding, with return dates.
- **Trade block:** in full, by team.
- **Advice:** the engine's picks, once advice goes on; whether it gets its own tab is still open.
- **Moves ledger:** every add, drop and trade, newest first, with filter chips by team.

## League

- **Standings:** a table, and title odds over the season (**LineChart**, four teams, direct labels).
- **Power rankings history:** **RankingRow**s by week.
- **History:**
  - all-time standings;
  - head-to-head records (a 4×4 table);
  - the record book;
  - champions;
  - trade history;
  - **draft history**: each pick, who made it, and how he has rated since (OVR at the time vs now).
- **Awards:** a running MVP race and best pickup (**RankingRow**s with players), most improved, and Player of the Week history. Definitions are still to be decided.
- **Newsletter archive:** every issue, newest first. Past issues open in their original look.

## Every screen

- Freshness is shown.
- Every team mark or chip opens the team.
- Every player name opens his card.
- Every non-obvious number has an **InfoTip** the first time it appears.
