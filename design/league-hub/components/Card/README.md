# Card

The white container every hub section sits in: a 1 px `line` border, `radius-14`, `space-14` padding, on `canvas`.

- **Provide:** a section title (always), optional meta on the right (a count, a date, a unit), the content, and optionally one link at the bottom right.
- Title: `lh-eyebrow` (12 px, 800, uppercase, `ink-2`). Meta: `lh-meta` (`ink-3` on white). A meta line that sits on `canvas` outside a card uses `ink-2`.
- Rows inside a card are divided by `line-soft` hairlines, not boxes.
- **No shadows** (the only shadow is the selected segment), no coloured left borders, no gradients.
- A card that holds a table uses `lh-card--flush` so the table runs edge to edge.
- Sections that are a list of cards (matchups, teams) skip the outer card: the eyebrow title sits on `canvas` above them.
