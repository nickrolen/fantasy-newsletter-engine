"""Which lore entries have already been published, and in which week.

WHY
---
The drafting chat is handed every approved entry every week with no record of
what it used last time. Nothing stopped the same line about a manager running
in all 23 issues of a season -- Nick, 10-14: "I want there to be lots of
variety in the lore lines ... I don't want it getting predictable."

Fun facts already avoid this. content_freshness tracks what ran and suppressed
two of seven fun facts in the week-16 dry run for exactly this reason. Lore
had no equivalent, so a 62-entry manager pool was free to repeat from week one.

DESIGN
------
Usage is kept OUT of LEAGUE_LORE.json deliberately. That file is curated by
hand, through the sittings; a machine appending to it every week would collide
with Nick's own edits and make the diff unreadable. This is a separate ledger
keyed by entry id, written by the claim check, read by the export.

Re-running the claim check for a week REPLACES that week's record rather than
appending, so checking a draft three times does not look like using an entry
three times. Same convention as title_odds_history.

A week is only recorded when the draft actually carried the tag, so an entry
shown to the drafter and not used stays fresh.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

USAGE_PATH = ("config", "LORE_USAGE.json")

_COMMENT = (
    "Which lore entries were published, by season and week. Written by "
    "scripts/check_draft.py from the <!--lore:id--> tags in the assembled "
    "draft; read by scripts/review_lore.py --export so the drafting chat can "
    "prefer entries it has not used lately. Re-checking a week replaces that "
    "week's list. Edit by hand only to correct a mistake."
)


def path(base: Path) -> Path:
    return Path(base).joinpath(*USAGE_PATH)


def load(base: Path) -> dict:
    """The ledger, or an empty one. Never raises on a missing file."""
    p = path(base)
    if not p.exists():
        return {"_comment": _COMMENT, "weeks": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"_comment": _COMMENT, "weeks": {}}
    data.setdefault("weeks", {})
    return data


def record(base: Path, season: str, week: int, ids) -> Path:
    """Record the entries a week's draft used. Replaces that week's list."""
    data = load(base)
    season_weeks = data["weeks"].setdefault(str(season), {})
    # sorted + de-duplicated: an entry used twice in one issue is still one
    # week of usage, and a stable order keeps the diff readable.
    season_weeks[str(int(week))] = sorted(set(str(i) for i in ids))
    data["_comment"] = _COMMENT
    p = path(base)
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=True, sort_keys=False)
                 + "\n", encoding="utf-8")
    return p


def last_used(base: Path, season: str, before_week: Optional[int] = None) -> Dict[str, int]:
    """{entry id: the most recent week it ran} within `season`.

    With `before_week`, only weeks strictly earlier than it count, which is
    what the export wants: the week being drafted has not happened yet.
    """
    data = load(base)
    out: Dict[str, int] = {}
    for wk, ids in (data["weeks"].get(str(season)) or {}).items():
        try:
            w = int(wk)
        except (TypeError, ValueError):
            continue
        if before_week is not None and w >= int(before_week):
            continue
        for i in ids:
            if out.get(i, -1) < w:
                out[i] = w
    return out


def weeks_since(base: Path, season: str, current_week: int) -> Dict[str, int]:
    """{entry id: how many weeks since it last ran}. Absent = never used."""
    cw = int(current_week)
    return {i: cw - w for i, w in last_used(base, season, cw).items()}


def used_ids(base: Path, season: str, week: int) -> List[str]:
    """What a given week recorded, for tests and for inspection."""
    return list((load(base)["weeks"].get(str(season)) or {}).get(str(int(week))) or [])
