# SegmentedTabs

Switches between views of one thing instead of one long page: the player card's Season / Career / Keeper / History, a matchup's Summary / Win % / Game flow / Lines, and the Simple / Detailed toggle on tables.

- **Provide:** 2–4 labels (one word each where possible) and the selected one.
- **Segmented tabs** (`lh-seg`): equal-width segments on a `surface-sunken` track (`line` when the control sits on `canvas`). The selected segment is white with `shadow-seg` and `ink-strong` text; the others are `ink-2`. Segments are `tap-min` (44 px) tall inside a 4 px track. Use `role="tablist"` / `role="tab"` / `aria-selected`.
- **Simple / Detailed toggle** (`lh-toggle`): a pill pair at the right of a table's title row. The pressed option is `dark` (one of the allowed dark spots). Detailed adds columns (grades, ranges); it never changes the rows.
- Remember the last choice per view for the session.
- More than 4 options means it isn't a segmented control: use a list or a filter row.
