# RankingRow

A ranked team row with a small multiple: rank, team mark and name, record and points for, a sparkline of the trend, the headline number and its change.

- **Provide:** rank, team, record, points for, the series for the sparkline (4–8 points, oldest first), the current value and its change.
- Sparklines in a list share **one y-scale** (here 0–50%), so rows compare honestly. Each has an `aria-label` that lists its values.
- The change uses `lh-delta` with ▲/▼ and the unit implied by the column ("pts" spelled out once in the section meta).
- Each row is a link to the team (48 px tall minimum).
- The engine decides the order; the page never re-ranks.
- Used for power rankings on Home and for the title-odds history in League. The same row shape works for an awards race (MVP, best pickup) with a player instead of a team.
