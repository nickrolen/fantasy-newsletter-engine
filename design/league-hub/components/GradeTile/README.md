# GradeTile

A letter grade (A+ to D) for one attribute, with its percentile as a thin bar and a number: the player card's attribute grid, and the badge on the newsletter's report cards.

- **Provide:** attribute name, letter, percentile (0–100), and the comparison group ("vs rostered players", stated once in the section header with an `InfoTip`). The engine computes grades; the page only shows them.
- Letter in `display-md`, coloured by band: `grade-a` (A range), `grade-b`, `grade-c`, `grade-d`. The letter carries the meaning; colour only groups the bands.
- Percentile bar: 4 px, `track` behind, the band colour in front, width = percentile. The printed "84th pct" sits under it, so the bar is `aria-hidden`.
- Grid: 4 across on phone (8 tiles), 8 across on desktop. Fixed order everywhere: the league's scoring categories, then Durability, Consistency, Schedule.
- **Badge** (`lh-grade-badge`): a 52 px tinted square for a team's weekly report-card grade in the newsletter; `grade-*-tint` behind `grade-*` text.
- In tables, grades are just the coloured letter (`lh-grade-cell`).
