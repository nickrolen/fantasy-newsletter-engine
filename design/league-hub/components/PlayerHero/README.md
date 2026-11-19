# PlayerHero

The top of every player card, always white: a big square headshot, OVR ring and POT with the weekly change, his fantasy team chip, name, bio line, status, and archetype.

- **Provide:** the headshot path from the library (`assets/headshots/<slug>.webp`, 320 px source shown at `headshot-hero` 148 px), name, positions, NBA team, age, status, the fantasy team (or none), OVR, POT, the weekly change, and the archetype label with two or three keywords. All from the engine.
- **Headshots are square on white:** `radius-0`, no frame, no border, no shadow, never on `dark` or a tint, so the photo's own white background disappears into the card. A missing photo shows his **initials in `ink-3` on the white square** (4c1; it was the neutral silhouette), never a broken image and never a team-coloured block. A photo that fails to load is removed and the initials stay.
- **OVR ring:** an 80 px ring, 7 px stroke; the arc is OVR/99 of the circle (the engine gives the dash), in the team's colour, on a `line` track. The number in `display`, 32 px. POT beside it, 30 px, with both weekly changes as `lh-delta` ("POT ▲ 1 this week", "OVR ▲ 3 this week"). **No line a week back means no change line at all**, never a zero or a dash.
- **Free agents have no OVR and no POT** (4a decision 8): the ring is replaced by FPPG with "Nth percentile of rostered players", a percentile bar, and an InfoTip saying why.
- Team chip: `lh-chip` in the team's colours, or `lh-chip--fa` "Free agent". Status: `StatusChip`; "Healthy" only here.
- Archetype: 15 px/800, keywords 12 px `ink-2`, separated by " · ". **Only the ratings' archetype, and only when `ratings.archetype.enabled` is true**; a local `--archetype-preview` build marks it with a "Preview" pill. The old card's archetype is never shown.
- A **Compare** button (`lh-btn`, 44 px tall) in the top bar opens Compare with this player on the left.
- Under the hero: `SegmentedTabs` (Season / Career / Keeper / History), then the Season tab's 2×2 `KpiTile`s, `GradeTile`s, the `BarChart` of points by game, keeper outlook, last 5 games.
- **No made-up values:** a value the engine doesn't have shows "—" with the reason in its context line. Until OVR/POT pass validation, the ring and POT are hidden, not faked.
