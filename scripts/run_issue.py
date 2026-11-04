#!/usr/bin/env python3
"""
run_issue.py -- the failure issue's title and body (step 1c-ii,
HANDOFF_STEP1C2 s.4 step 10). STANDARD LIBRARY ONLY: the workflow calls it on
the runner's own python3 even when setting up Python is what failed.

    python3 scripts/run_issue.py title --outcomes "state=success,engine=failure,..."
                                       [--runs-file output/nightly_runs.jsonl --skip N]
                                       [--logs DIR]
    python3 scripts/run_issue.py body  (same arguments) --run-url URL --mode nightly

The title is "Nightly run failed: <step>: <reason>":
  - <step> is the first workflow step whose outcome is "failure", in the order
    given. When that step is the run itself ("run"), the step is the nightly
    run's own failing step, read from the run record (output/nightly_runs.jsonl,
    the rows after the first N, which the workflow counted before the run):
    e.g. "line", "closing", or "pretip/tags" for a pre-tip run.
  - <reason> is that row's error, or the last non-empty line of the failed
    workflow step's log (DIR/<step>.log, which the workflow tees), one line,
    at most 160 characters.
The workflow opens one issue with that title (label run-failed) or, when one is
open already, comments on it; the next good run closes it. Nothing here calls
GitHub.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PREFIX = "Nightly run failed"
MAX_REASON = 160


def parse_outcomes(text: str) -> list:
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"--outcomes entries are step=outcome, not {part!r}")
        k, v = part.split("=", 1)
        out.append((k.strip(), v.strip()))
    return out


def run_rows(runs_file, skip: int) -> list:
    p = Path(runs_file)
    if not p.is_file():
        return []
    rows = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in rows[int(skip):]]


def one_line(text: str) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= MAX_REASON else s[:MAX_REASON - 3] + "..."


def last_line(path: Path) -> str:
    if not path.is_file():
        return ""
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if ln.strip()]
    return lines[-1] if lines else ""


def failure(outcomes: list, rows: list, logs=None) -> tuple:
    """(step, reason) of the first failed workflow step."""
    failed = [k for k, v in outcomes if v == "failure"]
    if not failed:
        return "workflow", "a job failed before its steps ran; see the run log"
    step = failed[0]
    if step == "run":
        refused = [r for r in rows if r.get("outcome") == "refused"]
        if refused:
            r = refused[-1]
            bad = next((s for s in r.get("steps", []) if s.get("outcome") == "refused"), {})
            name = bad.get("step", "?")
            name = name if r.get("mode") == "nightly" else f"{r.get('mode')}/{name}"
            return name, one_line(r.get("error") or bad.get("detail") or "refused")
        reason = last_line(Path(logs) / "run.log") if logs else ""
        return "run", one_line(reason or "nightly.py exited non-zero without a refused run record")
    reason = last_line(Path(logs) / f"{step}.log") if logs else ""
    return step, one_line(reason or "see the run log")


def title(outcomes, rows, logs=None) -> str:
    step, reason = failure(outcomes, rows, logs)
    return f"{PREFIX}: {step}: {reason}"


def body(outcomes, rows, logs=None, run_url="", mode="") -> str:
    step, reason = failure(outcomes, rows, logs)
    lines = [f"**{mode or 'the'} run failed** at `{step}`: {reason}", "",
             f"Run: {run_url}" if run_url else "", "",
             "Workflow steps: " + ", ".join(f"{k} {v}" for k, v in outcomes), ""]
    for r in rows:
        lines.append(f"- `{r.get('mode')}` run {r.get('run_id')}: **{r.get('outcome')}** "
                     f"in {r.get('seconds')} s")
        for s in r.get("steps", []):
            lines.append(f"  - {s.get('step')}: {s.get('outcome')} ({s.get('seconds')} s)")
    lines += ["", "State was copied back and committed whatever the outcome (unless the copy "
                  "itself failed). This issue closes on the next good run."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The failure issue's title or body (stdlib only).")
    ap.add_argument("what", choices=("title", "body"))
    ap.add_argument("--outcomes", required=True)
    ap.add_argument("--runs-file", default="output/nightly_runs.jsonl")
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--logs")
    ap.add_argument("--run-url", default="")
    ap.add_argument("--mode", default="")
    a = ap.parse_args(argv)
    outcomes = parse_outcomes(a.outcomes)
    rows = run_rows(a.runs_file, a.skip)
    if a.what == "title":
        print(title(outcomes, rows, a.logs))
    else:
        sys.stdout.write(body(outcomes, rows, a.logs, a.run_url, a.mode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
