# HeatGrid

A small table of counts shaded by size: starts left by day on the matchup page, games per team per week in the 3-week games grid.

- **Provide:** row labels (teams, with their swatch), column labels (days or weeks), the counts, and the bucket edges (from the engine or the section's definition).
- **Neutral sequential scale** `seq-1` → `seq-4` (slate), never a team colour, so no team "owns" the grid. Text on `seq-1`/`seq-2` is `ink-strong`; on `seq-3`/`seq-4` it's white.
- **The number is printed in every cell.** Shade helps you scan; the number is the data.
- Four buckets at most, explained in one line under the grid.
- Row totals on the right in `display-sm`.
- Cells 32 px tall, `radius-6`, 4 px gaps. Up to 7 columns on phone; more scrolls with the label column sticky.
