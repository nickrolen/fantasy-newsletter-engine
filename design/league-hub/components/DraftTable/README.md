# DraftTable

League > History > Draft (4c4): each season's draft, every pick with how the player rated then and later, after 2K's draft summary (brief §2). Display only: every value and reason is an engine string (`modules/hub_v2/league.py` `draft`, `modules/draft_ovr.py`).

## Anatomy

- **A season select** (`v2-fchip` with a `select`, `data-lhdraft`), this season first; one card per season, the chosen one shown.
- **The card header:** "2026-27 draft" and the meta "opening day 10-20 · now today" (a past season: "· deadline at the trade-deadline point").
- **The table** (`lh-table`): **Pick** ("1.01" = round 1, its first pick; a keeper adds **K**), **Player** (name, his card where he has one; the team chip under), **Then**, and **Now** (this season) or **Deadline** (a past season), with the change beside it (▲4 `up`, ▼2 `down`, – `ink-3`).
- **A dash says why:** a missing OVR is "—" as a 44 px button (`v2-lg-why`, dotted underline) that opens the Tooltip with the player and the reason: no earlier season of his in the league log (his opening-day level would be the league average), not on a roster that day, not on a roster today (free agents have no OVR), or the cache missing.
- **The foot:** each manager's drafted (non-keeper) picks ("Benton 9 · Garrett 9 · Hayden 9 · Nick 9").

## What the numbers are

- **Then:** OVR on the season's opening day, `ratings.rate` on that day's snapshot (4a's call).
- **Deadline:** OVR at the trade-deadline point (the same place in the season as this season's deadline; 4a's "deadline" cell). Not the season's end: OVR is rest-of-season value, and no games remain on the last day.
- **Now:** today's OVR.
- Past seasons come from `data/historical/DRAFT_OVR.json` (`scripts/build_draft_ovr.py`, once a season, where basketball-reference's pages are cached).
