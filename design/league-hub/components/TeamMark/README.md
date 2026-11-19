# TeamMark

How a fantasy team is shown anywhere: its Yahoo picture or a monogram in the manager's colour, a 10 px swatch beside its name, or a tinted chip that opens the team.

- **Provide:** the team's colour slot (`lh-t-blue` / `-orange` / `-teal` / `-plum`, set once per team in config), its two-letter monogram, its name, and the cached picture if there is one.
- **Picture first, monogram as the fallback:** the monogram letters are always in `lh-mono`; a team with a picture also gets `v2-pic v2-pic-<slot>`, and the picture is drawn over the letters (an `::after` layer, `background-size: cover`). If it is missing or fails to decode, the monogram letters show on the team colour. Never a broken image. Sizes: 72 (team page), 36 (matchup header), 32 (matchup row, the Advice card), 28 (rankings). Corners are 25% of the size.
- **The picture (4c3):** the team's current Yahoo picture, fetched nightly and cached by content (`output/team_pictures/`, league state), centre-cropped square and downscaled to 144 px (TeamMark 72 at 2×). It rides in the encrypted page **once per team** as a data URI in one small style block (`.v2-pic-<slot>::after`), however many marks show it, so it costs its bytes once against the first-load budget. Never in a plaintext published file (the plaintext scan covers it), never in a test (tests make their images). A changed picture shows from the next day's build.
- **Swatch** (`lh-swatch`) beside a team name in lists and charts' direct labels. The name is always there too: colour never identifies a team alone.
- **Chip** (`lh-chip`): team tint with the team's `-ink` text; every chip is a link to that team. Players with no team get the neutral "Free agent" chip.
- The four colours are the categorical palette for the whole hub: a team's colour is identical in every chart, chip, bar and line. Don't use them for anything that isn't a team.
- Team colour as text (a win %, a team name) is allowed on `surface` (4.9:1+), not on `canvas` below 14 px.
