# KpiTile

One headline number with its label and a context line: the 2×2 grids on the team page and the player card.

- **Provide:** label (≤ 2 words), value (already formatted by the engine), and a **context line, always**: the change since last week, the rank, or the comparison it should be read against. A bare number is not allowed.
- Value in `display-lg` (`lh-kpi__value`), tabular figures. Label in `label` style, `ink-3`.
- Change lines use `lh-delta--up` / `--down` with ▲/▼ and the unit ("▲ 6 pts this week"). Neutral context uses `lh-kpi__ctx` (`ink-2`).
- A tile about one team may colour the **value** in the team's colour (`lh-team-text`) and carry a team-coloured sparkline (last 4–8 points, end dot, `aria-label` listing the values).
- Nested tiles inside a card (the lines tiles on a matchup, the at-a-glance tiles in the newsletter) use `lh-kpi--nested`: `surface-subtle`, no border, value 17 px.
- Grids: 2 columns on phone, 4 on desktop. Never more than 4 tiles in a group.
- A missing value shows "—" and the context line says why ("No games yet").
