"""
jsonl_log.py -- append-only JSON-lines files, read strictly (step 1c).

The nightly run keeps several append-only records (the transaction log, the
tag records, the run record). They share one rule, the title-odds history's
(modules/title_odds_history.py): a file is evidence, so a malformed one RAISES
naming the line and is never truncated or repaired here, and a row is only
ever appended.
"""

from __future__ import annotations

import json
from pathlib import Path


class LogCorrupt(ValueError):
    """A JSON-lines file holds a line that is not a valid row."""


def read_rows(path, label: str = None) -> list:
    """Every row, in order. No file is no rows. Raises LogCorrupt on a line
    that is not a JSON object, a blank line, or an unterminated last line (a
    write that was cut off)."""
    path = Path(path)
    label = label or path.as_posix()
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        raise LogCorrupt(f"{label}: the last line is unterminated (a cut-off write); fix the file "
                         "by hand -- it is never truncated here")
    rows = []
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise LogCorrupt(f"{label} line {i}: blank line")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise LogCorrupt(f"{label} line {i}: not JSON ({e})") from None
        if not isinstance(row, dict):
            raise LogCorrupt(f"{label} line {i}: not a JSON object")
        rows.append(row)
    return rows


def append_rows(path, rows: list) -> int:
    """Append rows, one JSON object per line, sorted keys. The file is only
    ever opened for appending. Returns how many were written."""
    if not rows:
        return 0
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    return len(rows)
