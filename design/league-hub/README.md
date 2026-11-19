The League Hub is a private fantasy-basketball dashboard for four managers, and the weekly newsletter that goes with it. It should read like an excellent analyst's dashboard: light, restrained, every number trustworthy, every chart earning its place. It is not a game UI. Depth comes from the menus, as in a 2K MyLeague, never from crowding one screen.

Build every screen phone-first (390 px wide). Desktop gets a wider arrangement of the same components, not a different design.

## Principles

1. **The page displays; the engine computes.** Show the engine's numbers exactly as given. The page may scale a bar to its number. It does no other arithmetic, re-ranking or re-deriving.
2. **Colour means something.** The four team colours identify teams. `accent` means "you can tap this". Status colours mean availability. Grade colours group letter grades. Nothing is coloured for decoration.
3. **Never colour alone.** Every colour signal also has a word, a ▲/▼, a label or a position.
4. **Every number has context.** A KPI shows its change or comparison, a chart its unit, a percentage what it is the chance of.
5. **If there's a related number, a tap shows it.** Chips open teams, names open player cards, chart points show what changed, and headers sort.
6. **Simple first, Detailed on request.** Use the Simple/Detailed toggles and segmented tabs instead of long pages.
7. **No made-up values.** A missing figure shows "—" and says why.

## Content fundamentals

- **Voice in the UI:** plain and short. Use sentence case for everything except eyebrow titles and labels, which are uppercase by style, not by typing. No exclamation marks, no emoji, no jokes in the chrome. The newsletter keeps its own voice. The UI around it does not imitate it.
- **People and teams:** managers by first name ("Marcus"), teams by their league names ("Glass Cannons"), monograms as two letters ("GC"). Players are named in full the first time on a screen and by surname after that where space is short.
- **Numbers:**
  - Thousands get a comma (1,182).
  - Percentages have no space (64%).
  - Negatives use a real minus sign (−64, U+2212), not a hyphen.
  - FPPG always has one decimal (61.8). Points totals are whole numbers.
  - Records are W-L (4-1).
  - Changes say their unit once: "▲ 6 pts this week", "▼ 2.1 vs last 14 days".
- **Dates and times:** "Wed Dec 2", "4:00 PM" (Pacific, as the league plays), relative ages for freshness ("Updated 14 min ago", "19 h").
- **Terms:**
  - **"Title" means the regular-season title, weeks 1–15.** Title odds are odds of finishing first in weeks 1–15.
  - OVR, POT and FPPG are used as-is, with an `InfoTip` the first time they appear on a screen.
- **Never in the hub:** lore. Every string passes the engine's `clean`. Group-chat text never appears either.

## Colour

Use the tokens by name. The palette is one light theme.

- **Grounds:**
  - `canvas` behind everything.
  - `surface` (white) for cards, sheets, the tab bar and the player hero.
  - `surface-subtle` for tiles nested in a card and table headers.
  - `surface-sunken` for control tracks and neutral chips.
- **Text:**
  - `ink` for primary text and numbers.
  - `ink-2` for secondary text and eyebrow titles.
  - `ink-3` for labels, sub-lines and axis text.
  - `ink-body` for newsletter prose.
  - All pass AA on every light ground. `ink-3` replaces the mockups' #64748B, which failed on `canvas`.
- **Dark, for emphasis only:** `dark` is allowed in exactly three places:
  - the app header;
  - the newsletter masthead;
  - the pressed Simple/Detailed pill.

  On dark, use `ink-on-dark`, `ink-on-dark-2` and `ink-on-dark-3`, with `focus-on-dark` for the focus ring. Never put a headshot on dark.
- **Accent:** `accent` (navy) for links, "Details ›", back links and the focus ring on light grounds. `accent-pressed` when pressed. Accent is never a team colour and never a chart series.
- **Team colours, the categorical palette:** `team-blue`, `team-orange`, `team-teal` and `team-plum`, each with a `-tint` (chip fill) and an `-ink` (text on the tint).
  - Each manager gets one slot for good. The assignment lives in the engine's config, not in the page.
  - A team's colour is identical in every chart, chip, bar, line, monogram and ring.
  - The four colours hold 4.9:1 or more against white, so they work as marks and as text on `surface`.
  - The closest pair under colour-vision deficiency is blue and teal under tritanopia (ΔE about 14), which is why names or direct labels always accompany them.
  - Set a team on an element with `lh-t-blue`, `lh-t-orange`, `lh-t-teal` or `lh-t-plum`. Components then read `--team`, `--team-tint` and `--team-ink`.
- **Status:**
  - `status-out` on `status-out-tint` (Out).
  - `status-q` on `status-q-tint` (Q).
  - `status-il` on `status-il-tint` (IL, neutral by design).
  - `up` and `down` for changes, always with ▲/▼ or a sign.
  - Amber and red are reserved for status and for C/D grades.
- **Grades:** `grade-a` to `grade-d`, plus tints for the newsletter badges.
- **Sequential:** `seq-1` to `seq-4` (slate) for heat grids, so no team owns them.
- **Chart neutrals:**
  - `axis` for baselines.
  - `line-soft` for gridlines.
  - `axis-strong` for reference lines that carry meaning (the 50% line) and de-emphasised marks.
  - `track` behind percentile and progress bars.
- **No gradients, no shadows** (except `shadow-seg` on a selected segment), no tinted cards, no coloured left borders on cards.

## Type

- **Manrope** (`--font-sans`) for all text and UI.
- **Archivo Narrow** (`--font-display`) only for names, headlines and big numbers.
- Both are SIL OFL and bundled in `fonts/`: latin files listed in tokens, plus latin-ext files for names like Jokić and Dončić, declared by unicode-range in `bundle.css`.
- The hub embeds these files. It makes no font requests.
- All numbers use tabular figures (`lh-num`; `lh-dsp` includes them), so columns line up.
- **Scale:**
  - Display styles:
    - `display-hero` 40: the newsletter headline.
    - `display-xl` 34: the player name and matchup scores.
    - `display-lg` 30: KPI values and team names.
    - `display-md` 26: win % and grade letters.
    - `display-row` 19: OVR in tables.
    - `display-sm` 18: ranks, small values and section numbers.
  - Text styles:
    - `title` 22: newsletter section heads.
    - `reading` 17/1.65: newsletter prose.
    - `heading` 15/800.
    - `row` 14/700: names in lists.
    - `body` 13.
    - `meta` 12.
    - `eyebrow` 12/800 uppercase.
    - `small` 11.
    - `label` 10/800 uppercase.
    - `tab` 10.
- **Rules:**
  - Nothing smaller than 10 px. 10 px is only for labels and tab names, never sentences.
  - Weights in use are 400, 600, 700 and 800 for Manrope, and 600 and 700 for Archivo Narrow.
  - Line length for prose is at most `reading-max`.
- The page must survive the phone's text size turned up: use rem-safe layouts, let rows grow, and never fix a height on text.

## Layout and spacing

- **Phone:**
  - 16 px side padding (`space-16`).
  - Cards `radius-14` with `space-14` padding and `space-14` between them.
  - `space-20` between Home sections.
  - The bottom tab bar is `tabbar-height`.
- **Spacing steps:** 2, 4, 6, 8, 10, 12, 14, 16, 20, 24 and 32 px (`space-*`). Don't use other values.
- **Radii:**
  - 0 for headshots, always.
  - 3 for swatches.
  - 6 for heat cells.
  - 9 for segments.
  - 12 for tiles and buttons.
  - 14 for cards.
  - Pill for chips.
  - Monograms use 25% of their size.
- **Breakpoints:**
  - Below 600 px: one column.
  - 600–899 px: one column, wider cards, 4 KPI tiles across.
  - 900 px and up: two columns up to `page-max`, and the tab bar becomes a top bar with the same six items.
- **Tap targets:** at least `tap-min` (44 px); rows at least `row-min` (48 px).

## Data visualization rules

These are not optional.

- **Tables:**
  - Numbers right-aligned with consistent decimals; text left-aligned.
  - Any column sorts.
  - At most 5 columns on a phone. Wider tables scroll with the name column sticky.
- **Direct labels, not legends:** label a line at its end with the team's abbreviation and value, in the team colour.
- **Small multiples over big lone charts:** prefer a sparkline per row on one shared scale.
- **KPI tiles always have context:** a change or a comparison, never a bare number.
- **Honest axes:**
  - Bars start at zero.
  - Probabilities run 0–100% with a 50% reference line.
  - Cumulative points start at 0.
- **Banned:**
  - 3D;
  - gradients that encode data;
  - pie charts with more than three parts;
  - dual y-axes;
  - decoration a number could replace.
- **Show uncertainty where it matters:** win chances as percentages with the bar, ranges in Detailed views, and projections dashed and labelled.
- **Say why it moved:** where the engine knows the cause (an injury tag, a move), mark it on the chart with a small hollow marker; its words open in the **Tooltip** on a tap, never as text on the chart (4c2).
- **One message per chart:** its `aria-label` states it as a sentence, and the section meta names the unit.
- **Sizes:**
  - Line charts are 356 px wide on a phone with 2.5 px lines.
  - Sparklines are 64×24.
  - Bars have 4 px gaps.
  - Axis text is 10 px `ink-3`, with three y labels at most.

## Interactivity

- **Entities:** every team chip and mark opens the team, every player name opens his card, and every matchup card opens the matchup.
- **Charts:** tap or scrub a point for its value, time and reason in a readout line under the chart. A tap on an event marker opens the **Tooltip** (components/Tooltip).
- **Grids:** tap any games-grid cell for the **Tooltip**: the days he plays, or a team's starts by day, or who starts that day (4c2).
- **Tables:** sort by any column, and filter by position, team and status where a list is long (Players, Market).
- **Views:** Simple/Detailed toggles and segmented tabs. Remember the choice for the session.
- **Compare:** two players side by side, from the player card's Compare button.
- **Explainers:** an `InfoTip` (ⓘ) beside every new or non-obvious number, with one or two plain lines written once per concept.
- **Nothing is hover-only.**
- **Focus:** a visible 2 px `accent` outline, offset 2 px (`focus-on-dark` on dark).
- **Motion:** none beyond the browser's default scroll.

## Imagery

- **Player headshots:** square, on white, `radius-0`, with no frame, border or shadow.
  - Source: the headshot library (`assets/headshots/<slug>.webp`, 320 px).
  - Shown at `headshot-hero` (148) on the card, `headshot-feature` (132) in the newsletter, and 56 in lists.
  - Shown at `headshot-compare` (96) on Compare (4c1).
  - Missing: his initials in `ink-3` on the white square (4c1; was the neutral silhouette), never a broken image.
  - Never on `dark`, a tint or a team colour.
- **Team pictures:** fetched nightly from Yahoo and cached by content. They are shown inside `lh-mono` at 72/36/32/28 px, with the monogram on the team colour as the fallback.
- No stock photos, illustrations or mascots.

## Iconography

- Inline SVG line icons on a 24 px grid: 2 px stroke, round caps and joins, `currentColor`, drawn at 16–22 px.
- The set in use:
  - the six tab icons (paths in `TabBar`);
  - search;
  - back chevron and forward chevron;
  - ⓘ (circle with a stem);
  - the newsletter page icon;
  - the warning circle for the stale banner.
- Add new icons in the same style. No icon font, no emoji.
- Glyphs ▲ ▼ ▾ ▴ · › are text, set in the surrounding font.

## Constraints that shape the design

- **One encrypted static page** on GitHub Pages:
  - offline once unlocked;
  - no external requests (fonts and icons are embedded);
  - heavy parts (player cards, photos, history, past issues) are encrypted files loaded on tap.
- **First-load budget** (targets; the shell builder confirms them on a real build):
  - **The published `index.html` is at most 300 KB as served.** The page and its data are gzipped, then encrypted and base64-encoded inside the decrypt shell. Today's data gzips to about 23 KB. The four font files are about 100 KB of that 300 once encoded.
  - Each lazy file is at most 60 KB as served.
  - Each headshot is about 15–25 KB.
  - Nothing above the fold waits on a lazy file.
- **Freshness is visible on every screen:** in the header on Home and the tab roots, and in the meta line on detail pages.
- **Switch-over happens in one go:** the current hub runs until the new one is complete and reviewed.

## Using this system

- `components/bundle.css` is the hub's base stylesheet. Port it as-is: every value in it is a `var(--token)` from `tokens.css`.
- Components are plain HTML plus `lh-` classes. Each component's README says what data it needs.
- The previews are the reference markup. They use made-up data only: Glass Cannons, Pick & Roll Call, Zone Defense and Fast Break Bros are placeholder teams.
