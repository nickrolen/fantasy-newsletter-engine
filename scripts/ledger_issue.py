"""
ledger_issue.py -- the move ledger's issue in the private repo (step 2). Standard library only.

    python3 scripts/ledger_issue.py title --runs-file output/nightly_runs.jsonl --skip N
    python3 scripts/ledger_issue.py body  --runs-file output/nightly_runs.jsonl --skip N --run-url URL

The workflow (deploy/state-repo/.github/workflows/run.yml) runs it when the
nightly or pre-tip run wrote ledger_flags=true: verification found an entry
MISSING (its window closed without it) or in CONFLICT (a reserved player taken
by another team, or a move applied twice), a Yahoo move outside a Monday window
that no entry matches (rule 4), a checklist team that stopped, or -- in shadow
mode -- a difference between the ledger's add counts and the rulings'.

It is NOT the failure issue: a flag never fails the run (the hub still
publishes), and a good run does not close it. One open issue at a time
(label move-ledger); later flags are comments on it. Nick closes it.
The flags come from the run record's "ledger" block (modules/nightly.py).
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
    return [r for r in rows if (r.get("ledger") or {}).get("flags")]


def title(rows: list) -> str:
    if not rows:
        return "Move ledger: nothing flagged"
    flags = rows[-1]["ledger"]["flags"]
    kinds = sorted({f.split(" ", 1)[0] for f in flags})
    return f"Move ledger: {len(flags)} flag(s) ({', '.join(k.lower() for k in kinds)})"[:160]


def body(rows: list, run_url: str = "") -> str:
    out = []
    for r in rows:
        lg = r["ledger"]
        out.append(f"**{r.get('mode')} run {r.get('run_id')}** (ledger mode: {lg.get('mode')})")
        for f in lg["flags"]:
            out.append(f"- {f}")
        if lg.get("pending"):
            out.append("")
            out.append("Still pending:")
            out += [f"- {p}" for p in lg["pending"]]
        out.append("")
    out.append("MISSING / CONFLICT: decide with the managers; a mistaken entry is voided "
               "(`python scripts\\ledger.py void N --reason ...`), a late Yahoo move is ruled in "
               "TRANSACTION_RULINGS. SHADOW: until the switch to \"on\", write the claim_week rulings "
               "after the window and the difference goes away. Close this issue when settled.")
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
