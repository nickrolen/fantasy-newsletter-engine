# Masthead

The newsletter's dark opening: the issue line, the week's headline and one-line dek, and a scrolling row of chips that jump to each of the 10 sections.

- **Provide:** issue number and date; the headline and dek written in drafting (the one new piece of writing each week, with its own rules: length, voice, no lore); the section names, in the template's fixed order.
- Headline in `display-hero` (40 px, `ink-on-dark`), two lines at most on a phone. Dek 15 px `ink-on-dark-2`, one or two lines. Kicker 11 px uppercase `ink-on-dark-3`.
- Contents chips: `dark-raised` pills, 32 px tall, scrolling sideways; each jumps to its section anchor. Chip text is the section name exactly as the template names it.
- The masthead is one of the three allowed dark areas. No photos in it.
- Under it: the "week at a glance" row (three nested `KpiTile`s from engine data: high score, closest game, how the lines did).
- Past issues keep their old look: the new masthead starts with the first issue built from the new template.
