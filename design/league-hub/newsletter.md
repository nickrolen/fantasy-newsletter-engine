# Newsletter reading layout

The newsletter uses the same system as the hub (colours, fonts, chart rules, components), laid out for reading. **Presentation only:** the 10 sections, their order, the voice, the drafting workflow and the writing rules stay exactly as they are.

## Order of the page

1. **Masthead** (dark):
   - a back link to the hub;
   - the kicker "The Weekly · Issue N · <date>";
   - the **headline** and **dek** (written in drafting);
   - the **contents chips** for the 10 sections.
2. **Week at a glance:** three nested **KpiTile**s from engine data (high score, closest game, how the lines did) on `surface`, under an `eyebrow`-style kicker in `ink-3`.
3. **The 10 sections:** each is a **NewsletterSection** (number + name, prose, figures, optional pull quote), separated by `line` hairlines.
4. **Footer:** a link back to the hub and to the archive.

## The page

- The ground is `surface` (white) throughout, not `canvas`: it's a page to read, not a dashboard.
- The text column is 20 px from the edges on a phone. On desktop it is `reading-max` wide and centred. Figures may run 40 px wider than the text on desktop.
- **Prose:** `reading` style (17 px, line height 1.65) in `ink-body`, with `space-16` between paragraphs. Links in `accent`.
- **Section heading:** the number in `display-sm` `ink-3`, then the name in `title`. The number is part of the anchor target.
- **Headshots** (Player of the Week, anyone featured) are square on white at `headshot-feature`, the same treatment as the player card.

## What's new, and where it comes from

| Element | Source | Rule |
|---|---|---|
| Headline + dek | Written each week in drafting | The one new piece of writing: its own length and voice rules, no lore, passes `clean` |
| Week at a glance | Engine data | No writing |
| Contents chips | Section names from the template | Exactly the template's names |
| Charts between paragraphs | Engine data | Placed at natural breaks. Captions name what's shown and the unit. The prose is unchanged |
| Pull quote (optional) | A sentence from that section's own text | Never new writing; at most one per section |

## Rules for figures in the newsletter

- Use the hub's components, not copies: **LineChart**, **BarChart**, **HeatGrid**, **KpiTile**, **RosterTable** (static, no sorting), **GradeTile** badges for report cards, and **TeamMark** swatches beside team names.
- Each figure sits in an `lh-figure` panel (`surface-subtle`) with a caption in 12 px/800 `ink-2`.
- Charts in the newsletter are static pictures of that week: no tap readouts, and the numbers they need are printed on them.
- At most one figure between any two paragraphs. A section with nothing worth charting gets none.

## Past issues

- Issues already sent keep their old look.
- The new layout starts with one clean week, built from the new template (builder job 4d).
