# Page map

Every screen, what's on it, and which components build it, in the order they appear. "Engine" means the value comes precomputed in the hub's data and the page only shows it.

## Home

The big things, in this order:

1. **AppHeader**: week, date, search, freshness (stale banner when stale).
2. **IssueBar**: "Latest issue · Week N: <headline>", which opens the newsletter.
3. **This week's matchups**: one **MatchupCard** per matchup, in the engine's order. Eyebrow title on `canvas`, meta "Day N of 7".
4. **Power rankings**: a Card of **RankingRow**s (title odds, 4-week sparkline, change).
5. **Teams**: a 2×2 grid of team summary cards. Each card is a **TeamMark** + name + manager + four nested values: record, title odds, adds left, injured. The whole card is a link.
6. **Trade block**: a Card listing each team's stance (Buying / Selling / Neutral as a neutral `StatusChip`), what's on the block and what they want.
7. **TabBar**.

## Matchups

- **List:** every matchup this week as **MatchupCard**s, then the **games grid** (a **HeatGrid** of games per team, **3 weeks out**).
- **Matchup page:**
  - a white top bar (back to Matchups);
  - both teams (**TeamMark** 36, name, score `display-xl`, projection);
  - the **win bar** with both percentages;
  - **SegmentedTabs**:
    - **Summary:** the engine's key facts, starts left, who's missing.
    - **Win %:** a **LineChart** of win chance through the week with event markers; tap a point for what changed.
    - **Game flow:** a **LineChart** of cumulative points by day for both teams, with projections dashed.
    - **Lines:** spread, total and moneyline as nested **KpiTile**s, with how they moved since Monday.
  - **Starts left** (**HeatGrid** by day).
  - **Who's missing** (rows with swatch, name, reason, **StatusChip**).

## Teams

- **List:** four team cards (as on Home, larger).
- **Team page:**
  - a white top bar;
  - **TeamMark** 72 (Yahoo picture or monogram), name `display-lg`, "manager · record · place · PF";
  - **SegmentedTabs**: Roster / Schedule / Moves / Keepers.
  - **Roster** tab:
    - 2×2 **KpiTile**s: title odds with sparkline, this week's win chance, points for vs the league average, adds left with reset day.
    - The **RosterTable** (Simple/Detailed, IL slots apart).
    - **Likely keepers**: ranked rows with keep-chance bars (`lh-bar-h` in the team colour).
  - **Schedule** tab: next 3 weeks of games per player (**HeatGrid**).
  - **Moves** tab: this team's moves ledger (date, add/drop, players).
  - **Keepers** tab: keep chance, rank on the team, and POT for each player.

## Players

- **Search and browse:** a search field, filter chips (position, NBA team, fantasy team, status), and a sortable table (name, OVR, POT, FPPG, team, next).
- **Player card:**
  - **PlayerHero**;
  - **SegmentedTabs**:
    - **Season:**
      - 2×2 **KpiTile**s: FPPG vs last season, games of team games, total FP with rank, last 14 days vs season. NBA numbers lead, with the league-roster figure as a secondary line where it differs.
      - **Attributes:** 8 **GradeTile**s.
      - **Fantasy points by game:** a **BarChart** with the average.
      - **Keeper outlook:** keep chance, team rank, acquired.
      - **Last 5 games:** a small table.
    - **Career:** a by-season table and the FPPG trend (**LineChart**).
    - **Keeper:** keep chance, rank on his team, POT, and the age curve.
    - **History:** who has owned him, his draft slot and trades, and his records.
- **Compare:** two players' heroes side by side (headshots 96 px), then the same rows of KPIs and grades in two columns, with the better value in each row marked in `ink-strong` weight 800 (not colour).

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
