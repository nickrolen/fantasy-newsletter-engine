#!/usr/bin/env python3
"""
returns_issue.py -- the passed-return issues (decision 13b, Step 3a). Standard library only.

    python3 scripts/returns_issue.py titles --runs-file output/nightly_runs.jsonl --skip N
    python3 scripts/returns_issue.py body   --runs-file output/nightly_runs.jsonl --skip N --title T --run-url URL

The nightly run's returns step (modules/nightly.step_returns) checks every
injury entry whose return date has passed. With no O/OFS tag in Yahoo the
entry is removed (and listed in the run's summary); still tagged O/OFS, or
with no tag known, it asks Nick, here: one issue per player while it is open
(label return-passed). The workflow creates a title only when no open issue
has it (dedupe by title), and closes an open one whose title tonight's run no
longer lists (Nick answered it with an entry). Nothing here calls GitHub.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def returns_block(runs_file: str, skip: int):
    """The last run row (after the first `skip`) that carries a returns block."""
    p = Path(runs_file)
    if not p.is_file():
        return None
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()[skip:] if x.strip()]
    blocks = [r["returns"] for r in rows if r.get("returns") is not None]
    return blocks[-1] if blocks else None


def titles(block) -> list:
    return [i["title"] for i in (block or {}).get("issues") or []]


def body(block, title: str, run_url: str = "") -> str:
    hit = next((i for i in (block or {}).get("issues") or [] if i["title"] == title), None)
    if hit is None:
        raise SystemExit(f"no passed-return issue titled {title!r} in the run")
    out = [hit["body"], ""]
    removed = (block or {}).get("removed") or []
    if removed:
        out.append("Removed tonight (no O/OFS tag in Yahoo): "
                   + ", ".join(f"{r['player']} (back {r['return_date'][5:]})" for r in removed) + ".")
        out.append("")
    if run_url:
        out.append(f"Run: {run_url}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("titles", "body"))
    ap.add_argument("--runs-file", required=True)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--title")
    ap.add_argument("--run-url", default="")
    a = ap.parse_args(argv)
    block = returns_block(a.runs_file, a.skip)
    if a.what == "titles":
        sys.stdout.write("".join(t + "\n" for t in titles(block)))
    else:
        sys.stdout.write(body(block, a.title or "", a.run_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
