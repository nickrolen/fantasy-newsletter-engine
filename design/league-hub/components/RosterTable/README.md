# RosterTable

The team's roster as a sortable table, 2K-roster-viewer style: OVR with its weekly change beside POT, FPPG and next week's games; Detailed swaps in letter grades; IL slots sit apart at the bottom.

- **Provide:** rows from the engine (name, positions, NBA team, status tag, OVR and its change, POT, FPPG, next-week games, grades), the team's IL rows, and the default sort (OVR, descending).
- **Numbers right-aligned, tabular, consistent decimals** (FPPG to one decimal everywhere). Text left-aligned. Header labels in `label` style; the sorted header is `ink-strong` with ▾/▴ and `aria-sort`.
- Tap any header to sort; tap again to reverse. Names sort A→Z first, numbers best first (high→low, except Bust %, Missed, Age, Keep rank, Back and Acquired, which run low→high), a missing value last. **The order is the engine's** (an integer order per column); the page parses nothing. Sorting never moves IL rows out of their group. Every header button is at least 44 px wide.
- **Simple / Detailed** (`lh-toggle`). Same rows either way.
  - **Simple (team page):** FPPG, GP, Proj, Next.
  - **Detailed (4c2)** adds a chip row: **Value · Form · Schedule · Health · Keeper · Profile · All**. Each chip shows its group's columns beside the pinned name; **All** shows every column and the table scrolls sideways with the name column sticky. The chip (and Simple/Detailed) is remembered for the session, in memory only.
    - **Value:** OVR (with ▲/▼ this week), POT, Team value, Title Δ, Start %.
    - **Form:** FPPG, L14, vs Proj, Trend (a sparkline of his last 10 games, one scale per team), Floor, Ceil, Boom %, Bust % (MIN and MIN Δ join here once minutes are stored, job 4a3).
    - **Schedule:** Next, Next starts, GL, B2B.
    - **Health:** GP, Avail %, Missed, Back.
    - **Keeper:** Keep %, Keep rank ("#3 of 5"), Age, Acquired ("Kept '26", "R2 '26", "FA 11-09", "Trade 10-30"), Since acq.
    - **Profile:** Archetype (only when the ratings' archetype is switched on), Share, Best, Worst ("79 vs DEN").
  - Under the table, the chosen group's note: what each column means and why a "—" is a dash.
- OVR change: ▲ (`up`) / ▼ (`down`) / nothing. IL rows are `row-inactive` with `ink-3` numbers and no change marker.
- Rows are 48 px minimum; the player name links to his card. Status tags (Q, Out, IL · back date) follow the meta line in their status colour and in words.
- The footnote explains any abbreviation the table uses.
- On phone, at most 5 columns. Wider tables (League history, Players search) scroll horizontally with the name column sticky.
