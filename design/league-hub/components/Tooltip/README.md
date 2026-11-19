# Tooltip

The one small dark box a tap opens beside a mark: what a games-grid cell counts, what moved a chart. One component, used everywhere a mark has more to say than its number (4c2; Nick's preview notes s.1 and s.3).

- **Provide:** three engine strings, set on the element that opens it as `data-tip-h`, `data-tip-b` and `data-tip-f`:
  - **head** (`h`), the time or the week: "Fri 3:15 PM", "Wk 5", "Wk 4 rest", "Thu 11-19 · Luka my Balls";
  - **body** (`b`), the event or the days: "Dejounte Murray D→O", "Mon · Wed · Fri · Sun", or who starts that day;
  - **foot** (`f`, optional), the figure or the marks: "LM −4.2%", "Fri–Sat B2B · out Mon", "8 starts".
  The page computes none of them; it prints them as given.
- **Look:** `lh-tip` in `bundle.css`: `dark` with `ink-on-dark` (the foot in `ink-on-dark-2`), `radius-12`, `space-8`/`space-12` padding, 12 px text, at most `tip-max` (240 px) wide. The head is bold. No arrow, no shadow.
- **Opening and closing:**
  - a tap opens it; a second tap on the same mark, or a tap anywhere else, closes it;
  - keyboard focus on the mark opens it; Escape closes it;
  - a scroll, a resize, a sort or a change of screen closes it;
  - one at a time: opening one closes the other.
- **Placing:** fixed to the screen, above its mark and centred on it; below it when there is no room above; always inside the screen (8 px from each edge). **On a chart it never covers the end labels**: when it would, it moves left of them, and when there is no room left of them, below the chart.
- **The marks that open it are taps:** 44 px. A games-grid cell is a button 44 px tall (`v2-cell`); a chart marker gets an invisible 44 px circle (`v2-ev-hit`, r 22) on top of the chart's point strips. Each carries an `aria-label` with the same strings and `aria-expanded`.
- **Never hover.** Nothing opens on a pointer passing over.
- **Rules for the strings:**
  - the days a player plays are exactly the days his count counts: a cell of 3 lists 3 days; days his team plays that he is out (a tag, an injury entry, the NBA report) are marked "out Mon", not listed;
  - a back-to-back is marked "Fri–Sat B2B";
  - a week longer than seven days shows dates ("Mon 12-21");
  - "Wk N rest" lists only the days left;
  - a "—" cell says why ("IL slot · back 01-25").
- **Not for explanations of a concept:** that is the InfoTip (ⓘ), written once per concept. The Tooltip is about one mark's own data.
