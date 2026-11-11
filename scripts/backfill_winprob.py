#!/usr/bin/env python3
"""
backfill_winprob.py -- back-fill one week's win-% history from the private
repo's own history (hub polish 3, task 48b). Nick runs it once, for week 4:

    python scripts\\backfill_winprob.py --week 4

The live line (output/live_lines_weekN.json) is overwritten every time it is
priced, but the private repo (.state, the clone scripts\\state.py keeps)
holds every pushed version: one per cloud run that priced it. This script
reads them READ-ONLY (git -C .state log / git show: no checkout, no write
inside .state) in commit order, skips any version whose row equals the one
before it, and writes output/live_lines_weekN.winprob.jsonl
(modules/winprob_history) in date order. It REFUSES when that file already
exists (the history is append-only; the pricer appends from then on), when
.state is not a git checkout, when no version is found, or when two
different versions carry the same run id. It writes nothing else.

Then: python scripts\\state.py push.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class BackfillError(RuntimeError):
    pass


def _git(state_dir: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(state_dir), *args], capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        raise BackfillError(f"git {' '.join(args)} failed in {state_dir}: {r.stderr.strip()}")
    return r.stdout


def versions(state_dir: Path, week: int) -> list:
    """[(commit, commit time, the line payload)] of output/live_lines_weekN.json,
    oldest first, read-only."""
    if not (Path(state_dir) / ".git").exists():
        raise BackfillError(f"{state_dir} is not a git checkout of the private repo "
                            "(python scripts\\state.py pull makes it)")
    rel = (Path("output") / f"live_lines_week{int(week)}.json").as_posix()
    log = _git(state_dir, "log", "--reverse", "--format=%H %cI", "--", rel).split("\n")
    out = []
    for ln in log:
        if not ln.strip():
            continue
        sha, when = ln.split(" ", 1)
        try:
            blob = _git(state_dir, "show", f"{sha}:{rel}")
        except BackfillError:
            continue                                   # a commit that deleted the file
        out.append((sha, when, json.loads(blob)))
    return out


def rows_for(week: int, vers: list) -> list:
    """The history rows, one per distinct priced line, in date order."""
    from modules import winprob_history as wh
    rows, prev, by_id = [], None, {}
    for sha, _when, line in vers:
        if int(line.get("week", -1)) != int(week):
            raise BackfillError(f"commit {sha[:7]}: the week-{week} line file holds week {line.get('week')}")
        row = wh.row_from_line(line)
        if prev is not None and row == prev:
            continue                                   # the same line as the version before
        prev = row
        old = by_id.get(row["run_id"])
        if old is not None:
            if old != row:
                raise BackfillError(f"run {row['run_id']} appears twice with different lines "
                                    f"(commit {sha[:7]})")
            continue
        by_id[row["run_id"]] = row
        rows.append(row)
    from datetime import datetime
    rows.sort(key=lambda r: datetime.fromisoformat(r["as_of"]))
    return rows


def backfill(base: Path, week: int, state_dir: Path, out: Path = None) -> dict:
    from modules import winprob_history as wh
    out = Path(out) if out else wh.path_for(base, week)
    if out.exists():
        raise BackfillError(f"{out} exists: the history is append-only and is never rebuilt over")
    vers = versions(state_dir, week)
    if not vers:
        raise BackfillError(f"no version of output/live_lines_week{week}.json in {state_dir}'s history")
    rows = rows_for(week, vers)
    for i, r in enumerate(rows, 1):
        wh.check_row(r, f"row {i}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8",
                   newline="\n")
    tmp.replace(out)
    return {"out": out, "versions": len(vers), "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--base-path", default=".")
    ap.add_argument("--state-dir", default=None, help="the private repo's clone (default: .state)")
    ap.add_argument("--out", default=None, help="write here instead of output/ (a scratch run)")
    a = ap.parse_args(argv)
    base = Path(a.base_path)
    try:
        r = backfill(base, a.week, Path(a.state_dir) if a.state_dir else base / ".state", a.out)
    except BackfillError as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"Week {a.week}: {len(r['rows'])} win-% point(s) from {r['versions']} pushed version(s) -> {r['out']}")
    for row in r["rows"]:
        print(f"  {row['as_of']}  {row['trigger']:8s}  completed {len(row['completed_dates'])} day(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
