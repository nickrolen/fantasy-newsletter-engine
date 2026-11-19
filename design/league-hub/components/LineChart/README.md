# LineChart

A line over time in a team's colour, labelled directly at its end, with the moments that moved it marked and tappable: win chance through the week, the game flow, title odds over the season.

- **Provide:** the series (one per team, at most 4 lines; usually 1 or 2), the x labels, each point's "what changed" text from the engine (run name and the change it knows about), and any event markers.
- **Direct labels, not legends:** each line ends with its team's abbreviation and final value in the team colour. A legend only if labels would collide, and then as swatch + name.
- **Axes where honesty requires:** probability charts run 0–100% with a dashed `axis-strong` 50% reference line; cumulative points start at 0. Three y labels at most, `ink-3` 10 px. `axis` baseline, `line-soft` gridlines.
- **Projections are dashed** (`lh-c-proj`) and say so in the meta ("dashed = projected").
- **Say why it moved:** an event the engine knows (an injury tag, a move) gets a small hollow marker, r 4 (about the end dot's size), stroked `down` or `up` by the way the line moved. **No event text sits on the chart** (4c2, Nick: "I don't like the red text at all").
- **Tap a marker** to open the **Tooltip** (components/Tooltip): the time, the event and the swing, e.g. "Fri 3:15 PM · Dejounte Murray D→O · LM −4.2%". Each marker has an invisible 44 px tap circle (r 22) on top of the point strips, keyboard-focusable (focus opens it, Escape closes it). The Tooltip never covers the end labels.
- **Tap any other point** for its value, time and reason in the readout line under the chart (a hit strip per point, full plot height, keyboard-reachable). Never hover-only.
- Every chart has an `aria-label` sentence that states the takeaway.
- Lines are 2.5 px; the current point gets a filled dot and its value.
