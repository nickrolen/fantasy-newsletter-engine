# HeadToHead

League > History > Head to head (4c4): every manager's all-time record against every other, as a 4×4 grid. Display only: every record is an engine string (`modules/hub_v2/league.py` `h2h`).

## Anatomy

- **Phase chips** (`v2-fchip`, `aria-pressed`): **Regular season · Postseason**, Regular season first. Postseason = every week after the regular season (the bracket, the third-place series, and from 2026-27 the Cup), split by each season's `regular_through`.
- **The grid** (`v2-lg-h2h`, `role="table"`): a first column of row TeamMarks (28, each a link to the team, the manager in its label), a header of column TeamMarks, and a cell per pair: the **row's** record against the **column**, W-L or W-L-T. The diagonal is "—".
- **Each cell is a 44 px button** (`v2-lg-cell`, `surface-subtle`, `radius-6`); its label reads "Marcus against Tyler, Regular season: 4-13. Tap for each season." A tap opens the pair's seasons under the grid and outlines the cell (`aria-expanded`); a second tap closes it.
- **The pair's seasons** (`v2-lg-pair`): "Marcus vs Tyler", both totals ("Regular season 4-13 · postseason 0-2"), then one line per season, newest first ("2025-26  6-1 · postseason 0-1").

## Rules

- **Symmetric:** A's row against B mirrors B's against A (tested).
- **Scope:** 2017-18 on (Yahoo's matchups) and this season live; the note says so. The two records-only seasons have no games.
- Tokens only; nothing hover-only; the grid fits 360 px (TeamMarks, not names, head the rows and columns).
