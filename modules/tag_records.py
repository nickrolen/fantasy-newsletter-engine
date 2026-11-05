"""
tag_records.py -- every Yahoo injury-tag fetch, kept (step 1c).

    output/tag_records.jsonl   (private league state; APPEND-ONLY, modules/jsonl_log)

One row per fetch: {"run_id", "mode", "taken_at" (the league clock),
"league_day", "week", "tags": Tags.to_json()} -- rostered players and the
PLAYERLIST free agents, exactly as fetch_injury_statuses returned them.

Two readers, and why the record exists apart from the line:
  - THE HUB'S STATUSES (HANDOFF_STEP1C1 s.6, "tags as facts"): the hub reads
    the latest record, not the live line's state file. A night the line is
    locked writes no line (refresh_service prices nothing), but the nightly
    run fetches and records tags before it asks to price, so the hub's tags
    and statuses update whether or not anything is priced.
  - THE CLOSING LINE (s.5): the tags as at Monday's first tip are the latest
    record taken ON the Monday BEFORE its first tip -- the pre-tip run's,
    else the 12:01 AM nightly run's. No such record refuses (NoPretipTags).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .jsonl_log import append_rows, read_rows

RECORD_FILE = Path("output") / "tag_records.jsonl"
FIELDS = ("run_id", "mode", "taken_at", "league_day", "week", "tags")


class TagRecordError(ValueError):
    pass


class NoPretipTags(TagRecordError):
    """No tag record was taken on the Monday before its first tip."""


def read(base_path=".") -> list:
    rows = read_rows(Path(base_path) / RECORD_FILE, RECORD_FILE.as_posix())
    seen = set()
    for i, r in enumerate(rows, start=1):
        missing = [f for f in FIELDS if f not in r]
        if missing:
            raise TagRecordError(f"{RECORD_FILE} line {i}: missing {missing}")
        if r["run_id"] in seen:
            raise TagRecordError(f"{RECORD_FILE} line {i}: run {r['run_id']} recorded twice")
        seen.add(r["run_id"])
        if not isinstance(r["tags"], dict) or "rostered" not in r["tags"]:
            raise TagRecordError(f"{RECORD_FILE} line {i}: tags are not Tags.to_json()")
    return rows


def append(base_path, tags, *, run_id: str, mode: str, week: int, now: datetime) -> dict:
    """Record one fetch. The free agents must have been fetched (the roster
    plan and the closing line need them): a record without them raises."""
    if now.tzinfo is None:
        raise ValueError("a tag record's time must be the league clock (aware)")
    blob = tags.to_json()
    if blob.get("free_agents") is None and not blob.get("free_agents_assumed_healthy"):
        raise TagRecordError("a tag record must carry the free agents' tags (fetch_injury_statuses "
                             "returns them); a rostered-only dict is not a record")
    rows = read(base_path)
    if any(r["run_id"] == run_id for r in rows):
        raise TagRecordError(f"run {run_id} already has a tag record")
    row = {"run_id": run_id, "mode": mode, "taken_at": now.isoformat(timespec="seconds"),
           "league_day": now.date().isoformat(), "week": int(week), "tags": blob}
    append_rows(Path(base_path) / RECORD_FILE, [row])
    return row


def as_tags(row: dict):
    from .fetch_injury_statuses import Tags
    return Tags.from_json(row["tags"])


def latest(base_path=".") -> dict:
    rows = read(base_path)
    if not rows:
        raise TagRecordError(f"{RECORD_FILE.as_posix()} has no records: run python scripts\\nightly.py")
    return max(rows, key=lambda r: datetime.fromisoformat(r["taken_at"]))


def for_close(base_path, monday: date, first_tip: datetime) -> dict:
    """The latest record taken on `monday` (league day) before `first_tip`."""
    rows = [r for r in read(base_path) if r["league_day"] == monday.isoformat()
            and datetime.fromisoformat(r["taken_at"]) < first_tip]
    if not rows:
        raise NoPretipTags(f"no tag record was taken on {monday} before its first tip "
                           f"({first_tip.isoformat(timespec='minutes')}): the closing line's tags "
                           "are the Monday pre-tip run's (else the 12:01 AM run's), and neither "
                           f"exists in {RECORD_FILE.as_posix()}. Nothing is priced.")
    return max(rows, key=lambda r: datetime.fromisoformat(r["taken_at"]))


def hub_tags(row: dict, rostered) -> dict:
    """{rostered player (the roster's spelling): tag} for the hub's statuses:
    the record's rostered tags resolved to the roster (absence.resolve_tags,
    which raises on a tag that lands on nobody), keeping the tags the line
    models (absence.chain_tag) -- the same set the line's state file kept."""
    from . import absence
    resolved, _unmatched, _missing = absence.resolve_tags(row["tags"]["rostered"] or {}, rostered)
    # OFS is kept too: it is no chain tag (the line prices it as a season-long
    # out), but the hub's statuses and grid must see it (reviewing session,
    # 11-04: a rostered OFS player showed as healthy and counted in the grid)
    return {n: str(t) for n, t in dict(resolved).items() if kept_for_hub(t)}


def kept_for_hub(tag) -> bool:
    """A tag the hub's statuses and grid read: one the line chains, or OFS
    (hub_tags; the next-week grid's joining players, hub_state)."""
    from . import absence
    return absence.chain_tag(tag) is not None or bool(absence.season_out(tag))
