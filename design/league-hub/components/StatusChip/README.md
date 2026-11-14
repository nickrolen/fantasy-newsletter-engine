# StatusChip

A player's availability in one or two words: Out, Q, IL (with a return date when known), or Healthy.

- **Provide:** the status from the engine's tag pass (never re-derived in the page) and, for IL and Out, the return date if the engine has one ("back Dec 1").
- Out: `status-out` on `status-out-tint`. Q: `status-q` on `status-q-tint`. IL: neutral (`status-il` on `status-il-tint`), because IL is a roster state, not an alarm. Healthy: `up` text, no fill, only on the player card.
- The word is the signal; the colour only helps scanning. Never a dot or icon alone.
- A missing return date is left out, never guessed.
- These colours are reserved: amber and red mean status (or C/D grades), nothing else.
