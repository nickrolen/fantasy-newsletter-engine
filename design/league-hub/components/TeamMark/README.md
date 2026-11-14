# TeamMark

How a fantasy team is shown anywhere: its Yahoo picture or a monogram in the manager's colour, a 10 px swatch beside its name, or a tinted chip that opens the team.

- **Provide:** the team's colour slot (`lh-t-blue` / `-orange` / `-teal` / `-plum`, set once per team in config), its two-letter monogram, its name, and the cached picture if there is one.
- **Picture first, monogram as the fallback:** put the picture `<img>` inside `lh-mono`; if it is missing or fails to load, the monogram letters show on the team colour. Never a broken image. Sizes: 72 (team page), 36 (matchup header), 32 (matchup row), 28 (rankings). Corners are 25% of the size.
- **Swatch** (`lh-swatch`) beside a team name in lists and charts' direct labels. The name is always there too: colour never identifies a team alone.
- **Chip** (`lh-chip`): team tint with the team's `-ink` text; every chip is a link to that team. Players with no team get the neutral "Free agent" chip.
- The four colours are the categorical palette for the whole hub: a team's colour is identical in every chart, chip, bar and line. Don't use them for anything that isn't a team.
- Team colour as text (a win %, a team name) is allowed on `surface` (4.9:1+), not on `canvas` below 14 px.
