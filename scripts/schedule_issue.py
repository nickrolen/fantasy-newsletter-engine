"""
schedule_issue.py -- the NBA schedule's issue in the private repo (task 46). Standard library only.

    python3 scripts/schedule_issue.py title --runs-file output/nightly_runs.jsonl --skip N
    python3 scripts/schedule_issue.py body  --runs-file output/nightly_runs.jsonl --skip N --run-url URL

The workflow (deploy/state-repo/.github/workflows/run.yml) runs it when the
nightly run wrote schedule_flags=true: stand-ins for games the NBA has not
scheduled (modules/nba_schedule.py) are still in the schedule at the window of
the fantasy week they fall in (week 7: Monday 11-30). The NBA posts those games
after the Cup group stage (11-27); the nightly run refetches the schedule every
night, so a flag means the refetch has not picked them up yet -- the body says
how the last refetch went.

It is NOT the failure issue: the build doesn't fail (the stand-ins are counted
on estimated days), and the failure issue is closed by every good run, so it
could not carry this. Not the ledger's issue either: another subject. One open
issue at a time (label nba-schedule); later flags are comments on it. Nick
closes it once the schedule is refetched. From the window's first day (12-04),
stand-ins that are still needed make the run itself fail: the failure issue.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def flagged_rows(runs_file: str, skip: int) -> list:
    p = Path(runs_file)
    if not p.is_file():
        return []
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()[skip:] if x.strip()]
    return [r for r in rows if (r.get("schedule") or {}).get("flags")]


def title(rows: list) -> str:
    if not rows:
        return "NBA schedule: nothing flagged"
    sc = rows[-1]["schedule"]
    return (f"NBA schedule: {sc.get('standins', 0)} games still unscheduled at their week's window: "
            f"refetch")[:160]


def body(rows: list, run_url: str = "") -> str:
    out = []
    for r in rows:
        sc = r["schedule"]
        rf = sc.get("refetch") or {}
        out.append(f"**{r.get('mode')} run {r.get('run_id')}** (reading {sc.get('file')})")
        for f in sc["flags"]:
            out.append(f"- {f}")
        out.append(f"- last refetch: {rf.get('outcome')}" + (f" ({rf['why']})" if rf.get("why") else ""))
        out.append("")
    out.append("The NBA posts each team's last two regular-season games after the Cup group stage "
               "(11-27). Until they are in the schedule the engine counts them on estimated days. "
               "If the nightly refetch keeps failing, refetch on the desk: `python scripts\\state.py "
               "pull`, `python scripts\\fetch_nba_schedule.py`, `python scripts\\state.py push`. "
               "From the window's first day the run refuses while stand-ins are still needed. "
               "Close this issue once the schedule is refetched.")
    if run_url:
        out.append("")
        out.append(f"Run: {run_url}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("title", "body"))
    ap.add_argument("--runs-file", required=True)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--run-url", default="")
    a = ap.parse_args(argv)
    rows = flagged_rows(a.runs_file, a.skip)
    sys.stdout.write(title(rows) + "\n" if a.what == "title" else body(rows, a.run_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
