# NewsletterSection

One of the newsletter's 10 sections in the reading layout: a numbered heading, the drafted prose in a comfortable column, engine charts placed at natural breaks between paragraphs, and an optional pull quote.

- **Provide:** the section number and name (fixed by the template), the drafted paragraphs **unchanged**, any engine charts or tables for the section with where they go (after paragraph N), and an optional pull quote.
- **Presentation only:** the 10 sections, their order, the voice and the writing rules don't change. Layout never edits or trims the prose.
- Prose: `reading` style (17 px / 1.65, `ink-body`), max `reading-max` wide, centred on desktop. Paragraph gap `space-16`.
- Heading: the number in `display-sm` `ink-3`, the name in `title` (22 px / 800).
- **Figures** (`lh-figure`): `surface-subtle` panel, a caption that names what's shown and the unit, and a chart built from the same components as the hub (`LineChart`, `BarChart`, `HeatGrid`, `KpiTile`, `RosterTable`, `GradeTile`). Same colours, same rules.
- **Pull quote** (`lh-pull`): a sentence lifted word for word from that section's own text, never new writing. At most one per section; skip it when nothing stands out. 19 px / 700, 3 px `ink-strong` rule.
- Player of the Week uses the square headshot at `headshot-feature` (132 px) on white, like the player card.
- Sections are separated by a `line` hairline. Each section has an anchor for the contents chips.
