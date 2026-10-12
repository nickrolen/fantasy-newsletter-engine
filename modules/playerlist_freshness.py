"""
playerlist_freshness.py -- when was PLAYERLIST fetched, as a fact about the file.

check_playerlist used to infer freshness from content: a file identical to an
earlier snapshot "was not regenerated this week". On 2026-10-12 that failed a
file fetched that morning, because Yahoo had not moved a single projection
since 10-05. Identical content is what a stale file looks like AND what a
quiet preseason week looks like; the two cannot be told apart from the rows.

So the fetch says when it happened. fetch_playerlist writes a second sheet,
"_fetch", into the workbook: when, from where, and a hash of the projection
columns it wrote. The stamp travels with the file through copies and
snapshots, which an mtime does not (the same reasoning as A3's fetched_at in
the NBA schedule, modules/schedule_freshness.py).

A stamp only counts while it still describes the file. If the projection
columns no longer hash to what was fetched -- a hand edit, a paste from the
manual Step 2.5 procedure, a stamp sheet carried over onto other data -- the
stamp is ignored and freshness falls back to the content comparison, with a
warning saying why. A stamp that cannot vouch for the data never makes old
data look fresh.

Pure functions plus two small file helpers, so it tests without a network.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from typing import Optional

import pandas as pd

STAMP_SHEET = "_fetch"
DATA_SHEET = "Sheet1"            # what DataFrame.to_excel has always written
MAX_AGE_DAYS = 8                 # weekly cadence plus a day, as for the schedule

# The columns the engine runs on. Ages and anything else may be patched after
# a fetch without voiding the stamp; a projection may not.
HASHED = ["player_name", "player_nba_team", "player_position(s)",
          "player_total_proj_FP", "player_proj_GP", "projectedFPPG"]


def content_hash(frame: pd.DataFrame) -> str:
    """sha256 of the projection columns, stable across an xlsx round trip.

    Numbers are compared at 6 decimals and as floats, so a GP written as 72
    and read back as 72.0 hashes the same.
    """
    missing = [c for c in HASHED if c not in frame.columns]
    if missing:
        raise KeyError(f"cannot hash PLAYERLIST without {missing}")
    h = hashlib.sha256()
    for row in frame[HASHED].itertuples(index=False):
        cells = []
        for v in row:
            num = pd.to_numeric(v, errors="coerce") if not isinstance(v, str) else None
            if num is not None and pd.notna(num):
                cells.append(f"{float(num):.6f}")
            else:
                cells.append("" if (v is None or (not isinstance(v, str) and pd.isna(v))) else str(v))
        h.update(("\x1f".join(cells) + "\n").encode("utf-8"))
    return h.hexdigest()


def stamp(frame: pd.DataFrame, source: str, now: Optional[datetime] = None) -> dict:
    return {
        "fetched_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "source": source,
        "rows": int(len(frame)),
        "content_sha256": content_hash(frame),
    }


def write(frame: pd.DataFrame, path, source: str,
          now: Optional[datetime] = None) -> dict:
    """Write the data sheet and its stamp. Returns the stamp."""
    s = stamp(frame, source, now)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        frame.to_excel(xw, sheet_name=DATA_SHEET, index=False)
        pd.DataFrame(sorted(s.items()), columns=["key", "value"]).to_excel(
            xw, sheet_name=STAMP_SHEET, index=False)
    return s


def read_stamp(path) -> Optional[dict]:
    """The stamp in a workbook, or None if it has none."""
    try:
        sheet = pd.read_excel(path, sheet_name=STAMP_SHEET)
    except (ValueError, KeyError):          # no such sheet
        return None
    if not {"key", "value"} <= set(sheet.columns):
        return None
    return {str(k): v for k, v in zip(sheet["key"], sheet["value"])}


def assess(frame: pd.DataFrame, stamp_: Optional[dict],
           today: Optional[date] = None) -> dict:
    """How fresh the file is, and how we know.

    how:
      "stamp"     the stamp describes these rows; fetched_on is a fact
      "mismatch"  there is a stamp but the rows changed since; it is ignored
      "none"      no stamp (manual build, or written before stamps existed)
    """
    today = today or date.today()
    out = {"how": "none", "fetched_on": None, "age_days": None,
           "source": None, "stale": None}
    if not stamp_:
        return out
    try:
        fetched = datetime.fromisoformat(str(stamp_.get("fetched_at"))).date()
    except ValueError:
        out["how"] = "mismatch"
        return out
    if str(stamp_.get("content_sha256")) != content_hash(frame):
        out["how"] = "mismatch"
        out["fetched_on"] = fetched
        return out
    age = (today - fetched).days
    out.update(how="stamp", fetched_on=fetched, age_days=age,
               source=stamp_.get("source"), stale=age > MAX_AGE_DAYS)
    return out
