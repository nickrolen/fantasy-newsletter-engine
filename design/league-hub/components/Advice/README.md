# Advice

The engine's plan for each team, as the Market tab's **Advice** segment shows it. Built from the approved mockup (`mockups/Advice.html`, v5, Nick 11-18) and `claude/ADVICE_VIEW_DESIGN_2026-11-18.md`. Display only: every number and sentence is an engine string (`output/advice_latest.json`, carried into the payload by `modules/hub_v2/market.py`). Opening and closing a row is the page's only behaviour.

## Anatomy

- **The intro line** under the segments, with an InfoTip (ⓘ): "Best moves for Monday's window, in order, with how much each one changes your chance to win this week and next. ⚑: another team wants him too. Tap a move for why."
- **One card per team** (`lh-card adv`), in the page's team order.
  - **The header** (`adv-head`): TeamMark (32), the team name (a link to the team), and under it "Wk 6 vs <team> · Wk 7 vs <team>"; on the right the **"N adds left"** pill (`adv-adds`).
  - **"WIN % CHANGE"** column header (`adv-colh`) above the numbers.
- **The IL activation row** (`adv-row adv-row--il`), first when there is one:
  - shaded `status-il-tint`, with an `adv-bar` (3 px) `status-il` bar down the left edge (an inset shadow);
  - a filled ↺ circle (`adv-ilic`, `adv-dot` 22 px, `status-il`) in place of the step number;
  - the label **"ACTIVATE FROM IL · NO ADD"** (`adv-ilk`);
  - the returner in bold, then "− <drop>" with the red minus;
  - the same Wk 6 / Wk 7 win-% columns.
  - It is priced against **doing nothing**: he stays in his IL slot through the two weeks, nobody is dropped, and no other move is made (LEAGUE_RULES rule 3: legal, and it blocks every move). A negative number shows as it is, in `down`.
- **The hold variant** (H54, pending Nick's approval), in its place when advice keeps the returner in IL this week (`il_choice` "hold": holding beats activating now, his steps included, by more than `hold_bar`):
  - the same shading, bar, ↺ circle and Wk 6 / Wk 7 columns as the activation row;
  - the label **"KEEP IN IL THIS WEEK · NO MOVES"**;
  - the returner in bold, then a plain sub-line **"activate at week 7's window"** (no sign: nobody is dropped this window);
  - its numbers are **against activating now**, and the tap-open sentence says so ("Against activating him now: +0.8 lineup starts (…). At week 7's window (Mon 11-30) he comes back and the plan drops X.");
  - nothing follows it but the adds state: no THEN, no step, no plan line, no backup (a hold blocks every move). With no adds left, "No adds left. Resets Monday." as after an activation.
- **"THEN"** labels (`adv-then`) between rows.
- **A step row** (`adv-row`):
  - a numbered circle (`adv-n`, 22 px);
  - "+ Add" (green +, bold name) over "− Drop" (red −); an IL placement's second line reads "IL <name>";
  - **⚑** (`adv-flag`, `status-q` on `status-q-tint`, with its own label) beside the add when another team's plan adds him;
  - the right column stacked "Wk 6 +4.6%" over "Wk 7 +4.0%", **the same size** (`adv-wkrows`, `adv-col` 112 px wide);
  - a chevron.
- **Every row starts closed.** A tap opens (`adv-det`, `surface-subtle`):
  - the reason, one plain sentence (`adv-why`): the lineup starts it adds by week; for the activation when steps follow, "Needed before any add: while a healthy player sits in IL, you can't make moves.";
  - an IL move's follow-up, when there is one;
  - three small tiles (`adv-mini`): **Starts · Points · Title odds** (Title odds only while `advice.show_title_odds` is true: absent, not blank, when false);
  - "Also wanted by" with the other team's chip, when flagged;
  - "Cards:" — every player the row names, each opening his card (the row itself is the tap that opens it, so its names are plain text).
- **The plan line** (`adv-plan`), when there are two rows or more (the activation counts): "BOTH MOVES" / "ALL THREE", with "title odds +x%" under it (absent when title odds are off), and the totals in the same Wk 6 / Wk 7 layout. The total is the whole plan priced directly; the rows' gains add up to it.
- **The backup** (`adv-bk`): one muted line, "If LeBron James is gone: + Randle − Black ›" ("If he's gone" with a one-step plan), tappable for its numbers, reason and tiles.
- **The one-sentence states** (`adv-empty`), for a team with nothing to do: "Standing pat is best this week." / "Standing pat is best this week: no move is worth your last add." / "No adds left. Resets Monday." A team with an activation and no adds left shows the activation row, then the sentence.
- A failed advice run says "Advice could not be updated" and shows no pick; the season's end says so.

## Rules

- Tap targets: rows are at least `row-min`, the backup line `tap-min`; every row is a `<button>` with `aria-expanded` and `aria-controls`.
- Text ≥ 10 px (`type-label-size` for the labels). Tokens only, no hex or px in the CSS.
- Win-% values use `font-display` at `type-reading-size`, `up` / `down` / `ink-2` (a dash) by the engine's direction.
- Nothing is computed in the page: the labels ("Both moves", "All three"), the signs, the dashes and the directions are the engine's.

## Tokens added (4c3)

`adv-dot` 22px · `adv-col` 112px · `adv-bar` 3px (`tokens.json`, sizing).
