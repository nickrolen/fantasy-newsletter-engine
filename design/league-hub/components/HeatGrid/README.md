# HeatGrid

A small table of counts shaded by size: starts left by day on the matchup page, games per team per week in the 3-week games grid.

- **Provide:** row labels (teams, with their swatch), column labels (days or weeks), the counts, and the bucket edges (from the engine or the section's definition).
- **Neutral sequential scale** `seq-1` → `seq-4` (slate), never a team colour, so no team "owns" the grid. Text on `seq-1`/`seq-2` is `ink-strong`; on `seq-3`/`seq-4` it's white.
- **The number is printed in every cell.** Shade helps you scan; the number is the data.
- Four buckets at most, explained in one line under the grid.
- Row totals on the right in `display-sm`.
- Cells `radius-6`, 4 px gaps. Up to 7 columns on phone; more scrolls with the label column sticky.
- **Every cell is a tap (4c2):** a button 44 px tall (`v2-cell`; was 32 px) that opens the **Tooltip** with the engine's day list:
  - a player's week (the team's Schedule grid): "Wk 5 · Mon · Wed · Fri · Sun", with "Fri–Sat B2B" and "out Mon" marked, so the days and the count agree; "Wk 4 rest" lists only the days left; a week longer than seven days shows dates; a "—" cell says why ("IL slot · back 01-25");
  - a team's week (the Matchups 3-week grid): its starts by day, "Mon 8 · Tue 4 · …";
  - a team's day (a matchup's Starts left): who starts that day, a Q who fits if he plays, and anyone out tonight.
- **The Matchups 3-week grid shades by rank within each week** (4b decision 8): darker = more starts than the other teams that week, so a short week compares fairly. Its note says so.
