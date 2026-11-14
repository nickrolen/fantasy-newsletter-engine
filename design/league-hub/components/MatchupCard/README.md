# MatchupCard

One head-to-head this week, as it sits at the top of Home: both teams, points banked and projected, win chance, the lines, and the one thing that matters most right now.

- **Provide (all from the engine):** each team's mark, name, manager and record; banked and projected points; win chance; spread, total and moneyline; a one-line note (the engine's biggest swing factor: games left, a key absence).
- The favourite's win % is in its team colour; the underdog's in `ink`. Win % is `display-md`; points banked `display-sm` 18 px/600; projection in `lh-sub`.
- The **win bar** splits at the favourite's win chance, each side in its team's colour, with a 2 px white gap. It's decorative next to the printed percentages, so it carries an `aria-label` and nothing else depends on it.
- Lines sit in three nested tiles (`lh-kpi--nested`).
- The whole card is one link to the matchup page (`Details ›` is a visual cue, not a second target).
- Order on Home: the engine's matchup order, never re-sorted by the page.
