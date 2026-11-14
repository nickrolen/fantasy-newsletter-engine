# BarChart

Columns from a zero baseline with the average drawn across them: fantasy points game by game on the player card, points by week on a team.

- **Provide:** the values in order, the label for each bar (date and opponent), the average (from the engine), and the endpoints to print under the axis.
- **Bars start at zero, always.** One colour: the player's team colour (`ink-2` for a free agent). No highlighting by threshold colours: the average line does that job.
- Average: a 1.5 px dashed `ink-strong` line with its value printed at the right ("avg 61.8").
- Under the axis: first date, the best game, last date. No y-axis labels; the average label and the readout carry the numbers.
- **Tap a bar** for the game, the value and its difference from the average; the selected bar turns `ink-strong`. Each bar is a button with an `aria-label`.
- 4 px gaps; bars stretch to fill. Above ~40 bars, switch to a line.
