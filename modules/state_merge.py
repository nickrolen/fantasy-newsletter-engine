"""
state_merge.py -- `state.py pull` merges what can be merged (5g s.5, 11-25).

THE CASE (week 5, 11-24). The 3:30 PM afternoon run and Nick's Step 6 (3:43 PM)
both wrote four state files, and `pull` refused. The reviewer merged by hand:
both sides' appends in the title-odds history and the calibration log, and
the cloud's version of the latest title odds and the stakes (the manifest
names the files). That is option (a) of
STEP1C2_RESULT_2026-11-03.md s.15, built here as per-file rules named in
config/STATE_MANIFEST.json (a file entry's "merge"):

  append_jsonl     both sides only APPENDED lines to the common base: the
                   result is the base, then every new line of both sides in
                   as_of order (a line both added, byte for byte, once). An
                   edited or removed line, or a new line with no as_of with an
                   offset, refuses.
  calibration_log  the calibration log (published_lines): the base's records
                   may have gained settle fields on either side (actual_a,
                   actual_b, actual_source, settled_at, and nothing else), and
                   both sides may append. The settle fields merge (two
                   different settled values refuse), then theirs' new records
                   are appended, then ours' (a record both appended, equal in
                   every field, once). Anything else refuses.
  cloud_wins       a derived "latest" file the next cloud run rewrites anyway:
                   the private repo's version is taken.

A file with no rule refuses as before (scripts/state.py). Each function here
takes the three versions as bytes (base: the last sync's commit, or None when
the file is new on both sides; theirs: the private repo's; ours: this folder's)
and returns (bytes, a one-line summary), or raises MergeRefused naming why.
Standard library only, like state.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

RULES = ("append_jsonl", "calibration_log", "cloud_wins")
SETTLE_FIELDS = ("actual_a", "actual_b", "actual_source", "settled_at")


class MergeRefused(RuntimeError):
    """The two sides cannot be merged by the file's rule."""


def _lines(raw: bytes) -> list:
    return [ln for ln in (raw or b"").split(b"\n") if ln.strip()] if raw is not None else []


def _as_of(line: bytes, rel: str) -> datetime:
    try:
        row = json.loads(line.decode("utf-8"))
        when = datetime.fromisoformat(str(row["as_of"]))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise MergeRefused(f"{rel}: a new line has no readable as_of, so the two sides' lines cannot "
                           f"be put in order: {line[:120]!r}") from None
    if when.tzinfo is None:
        raise MergeRefused(f"{rel}: a new line's as_of {row['as_of']!r} has no offset, so the two "
                           "sides' lines cannot be put in order")
    return when.astimezone(timezone.utc)


def append_jsonl(base, theirs: bytes, ours: bytes, rel: str = "") -> tuple:
    b, t, o = _lines(base), _lines(theirs), _lines(ours)
    for side, lines in (("the private repo", t), ("this folder", o)):
        if lines[:len(b)] != b:
            raise MergeRefused(f"{rel}: {side} edited or removed a line of the last sync's version "
                               "(only appends merge)")
    t_new, o_new = t[len(b):], o[len(b):]
    new = list(t_new) + [ln for ln in o_new if ln not in t_new]
    keyed = sorted(((_as_of(ln, rel), i, ln) for i, ln in enumerate(new)), key=lambda x: (x[0], x[1]))
    merged = b + [ln for _w, _i, ln in keyed]
    out = b"\n".join(merged) + (b"\n" if merged else b"")
    return out, (f"appended both sides: {len(b)} line(s) in common, {len(t_new)} from the private "
                 f"repo, {len(o_new)} from here ({len(merged)} in all, new lines in as_of order)")


def _blob(raw, rel: str, side: str) -> dict:
    try:
        blob = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise MergeRefused(f"{rel}: {side}'s version is not JSON") from None
    if not isinstance(blob, dict) or not isinstance(blob.get("lines"), list):
        raise MergeRefused(f"{rel}: {side}'s version has no \"lines\" list")
    return blob


def calibration_log(base, theirs: bytes, ours: bytes, rel: str = "") -> tuple:
    t, o = _blob(theirs, rel, "the private repo"), _blob(ours, rel, "this folder")
    b = _blob(base, rel, "the last sync") if base is not None else None
    head_keys = sorted((set(t) | set(o) | set(b or {})) - {"lines"})
    for k in head_keys:
        want = (b or t).get(k)
        if t.get(k) != want or o.get(k) != want:
            raise MergeRefused(f"{rel}: the two sides disagree on {k!r} (only settling and appending "
                               "merge)")
    bl = b["lines"] if b is not None else []
    tl, ol = t["lines"], o["lines"]
    for side, lines in (("the private repo", tl), ("this folder", ol)):
        if len(lines) < len(bl):
            raise MergeRefused(f"{rel}: {side} has fewer records than the last sync ({len(lines)} < "
                               f"{len(bl)}): a record was removed")
    merged, settled = [], 0
    for i, br in enumerate(bl):
        tr, orr = tl[i], ol[i]
        keys = set(br) | set(tr) | set(orr)
        row = {}
        for k in list(br) + [k for k in tr if k not in br] + [k for k in orr if k not in br and k not in tr]:
            bv, tv, ov = br.get(k), tr.get(k), orr.get(k)
            if k in SETTLE_FIELDS:
                if tv == ov:
                    row[k] = tv
                elif tv == bv:
                    row[k] = ov
                elif ov == bv:
                    row[k] = tv
                else:
                    raise MergeRefused(f"{rel}: record {i + 1} (week {br.get('week')} "
                                       f"{br.get('matchup_id')}, {br.get('source')}) was settled "
                                       f"differently on the two sides: {k} {tv!r} vs {ov!r}")
            else:
                if not (k in br and k in tr and k in orr) or not (bv == tv == ov):
                    raise MergeRefused(f"{rel}: record {i + 1} (week {br.get('week')} "
                                       f"{br.get('matchup_id')}) changed {k!r} on one side (only the "
                                       f"settle fields {', '.join(SETTLE_FIELDS)} may change)")
                row[k] = bv
        assert set(row) == keys
        if row != br:
            settled += 1
        merged.append(row)
    t_new, o_new = tl[len(bl):], ol[len(bl):]
    merged += t_new + [r for r in o_new if r not in t_new]
    out_blob = {k: (merged if k == "lines" else v) for k, v in t.items()}
    out = json.dumps(out_blob, indent=2).encode("utf-8")
    return out, (f"{len(bl)} record(s) in common ({settled} settled on one side), {len(t_new)} appended "
                 f"in the private repo, {len(o_new)} here ({len(merged)} in all)")


def cloud_wins(base, theirs: bytes, ours: bytes, rel: str = "") -> tuple:
    if theirs is None:
        raise MergeRefused(f"{rel}: the private repo deleted it; nothing to take")
    return theirs, "took the private repo's version (a derived file: the next cloud run rewrites it)"


def merge(rule: str, base, theirs, ours, rel: str = "") -> tuple:
    """(merged bytes, summary) by `rule`, or MergeRefused."""
    if rule not in RULES:
        raise MergeRefused(f"{rel}: unknown merge rule {rule!r}")
    if rule != "cloud_wins" and (theirs is None or ours is None):
        raise MergeRefused(f"{rel}: deleted on one side (only appends merge)")
    return {"append_jsonl": append_jsonl, "calibration_log": calibration_log,
            "cloud_wins": cloud_wins}[rule](base, theirs, ours, rel)
