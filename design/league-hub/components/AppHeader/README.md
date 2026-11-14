# AppHeader

The dark strip at the top of every hub screen: the hub's name, the week and day, search, and how fresh the data is.

- **Provide:** the week label, the date, the freshness text (minutes since the last successful run, and what's live), and whether the data is stale.
- **Freshness is never hidden.** Fresh: the `live` dot plus "Updated N min ago". Stale (the engine's own stale rule): drop the dot and show the stale banner directly under the header, in `status-q` on `status-q-tint`, with the age in words. The banner is a sentence, not a colour.
- The header is one of the three places `dark` is allowed (with the newsletter masthead and the active Simple/Detailed pill). Nothing else goes dark.
- Search is the only control in the header: a 44 px `lh-iconbtn`.
- Detail pages (team, player, matchup) replace the header with a white top bar and a `lh-back` link, and keep the freshness line in their own meta.
