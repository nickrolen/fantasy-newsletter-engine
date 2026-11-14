# RosterTable

The team's roster as a sortable table, 2K-roster-viewer style: OVR with its weekly change beside POT, FPPG and next week's games; Detailed swaps in letter grades; IL slots sit apart at the bottom.

- **Provide:** rows from the engine (name, positions, NBA team, status tag, OVR and its change, POT, FPPG, next-week games, grades), the team's IL rows, and the default sort (OVR, descending).
- **Numbers right-aligned, tabular, consistent decimals** (FPPG to one decimal everywhere). Text left-aligned. Header labels in `label` style; the sorted header is `ink-strong` with ▾/▴ and `aria-sort`.
- Tap any header to sort; tap again to reverse. Names sort A→Z first, numbers high→low first. Sorting never moves IL rows out of their group.
- **Simple / Detailed** (`lh-toggle`): Simple = OVR, POT, FPPG, Next. Detailed = OVR plus grades (2–4 that fit) and FPPG; on desktop Detailed shows all grades. Same rows either way.
- OVR change: ▲ (`up`) / ▼ (`down`) / nothing. IL rows are `row-inactive` with `ink-3` numbers and no change marker.
- Rows are 48 px minimum; the player name links to his card. Status tags (Q, Out, IL · back date) follow the meta line in their status colour and in words.
- The footnote explains any abbreviation the table uses.
- On phone, at most 5 columns. Wider tables (League history, Players search) scroll horizontally with the name column sticky.
