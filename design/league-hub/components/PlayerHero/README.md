# PlayerHero

The top of every player card, always white: a big square headshot, OVR ring and POT with the weekly change, his fantasy team chip, name, bio line, status, and archetype.

- **Provide:** the headshot path from the library (`assets/headshots/<slug>.webp`, 320 px source shown at `headshot-hero` 148 px), name, positions, NBA team, age, status, the fantasy team (or none), OVR, POT, the weekly change, and the archetype label with two or three keywords. All from the engine.
- **Headshots are square on white:** `radius-0`, no frame, no border, no shadow, never on `dark` or a tint, so the photo's own white background disappears into the card. A missing photo shows the neutral silhouette in `axis`, never a broken image and never a team-coloured block.
- **OVR ring:** an 80 px ring, 7 px stroke; the arc is OVR/99 of the circle, in the team's colour (`ink-strong` for a free agent), on a `line` track. The number in `display`, 32 px. POT beside it, 30 px, with the weekly change as `lh-delta` ("▲ 1 this week"; "—" before the first week).
- Team chip: `lh-chip` in the team's colours, or `lh-chip--fa` "Free agent". Status: `StatusChip`; "Healthy" only here.
- Archetype: 15 px/800, keywords 12 px `ink-2`, separated by " · ".
- Under the hero: `SegmentedTabs` (Season / Career / Keeper / History), then the Season tab's 2×2 `KpiTile`s, `GradeTile`s, the `BarChart` of points by game, keeper outlook, last 5 games.
- **No made-up values:** a value the engine doesn't have shows "—" with the reason in its context line. Until OVR/POT pass validation, the ring and POT are hidden, not faked.
