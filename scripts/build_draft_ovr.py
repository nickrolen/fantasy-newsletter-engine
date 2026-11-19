#!/usr/bin/env python3
"""
build_draft_ovr.py -- write data/historical/DRAFT_OVR.json: every past
season's draft picks with their OVR on that season's opening day ("then") and
at its trade-deadline point ("later"), for the hub's League > History > Draft
(modules/draft_ovr.py says why those two days).

    python scripts/build_draft_ovr.py              write the file
    python scripts/build_draft_ovr.py --check      rebuild in memory and compare (exit 1 if it differs)
    python scripts/build_draft_ovr.py --out PATH   write elsewhere (a scratch check)

Run it on a machine with basketball-reference's month pages cached in
data/.cache/ (Nick's): past seasons' schedules come from there, and it never
fetches (a missing page raises). Past seasons never change, so this runs once,
and again at the season reset when the finished season joins the log
(19c's checklist). Reads only; writes only the one file. Seconds.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=".")
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    from modules import draft_ovr
    base = Path(a.base_path)
    t0 = time.time()
    try:
        obj = draft_ovr.build_cache(base)
    except Exception as e:                            # noqa: BLE001 -- printed, exit 1
        print(f"REFUSED: {type(e).__name__}: {e}")
        return 1
    text = json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
    out = Path(a.out) if a.out else base / draft_ovr.CACHE_RELPATH
    if a.check:
        same = out.is_file() and out.read_text(encoding="utf-8") == text
        print(f"{out}: {'identical' if same else 'DIFFERS from a rebuild'} ({time.time() - t0:.1f} s)")
        return 0 if same else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    n = sum(len(s["picks"]) for s in obj["seasons"].values())
    print(f"Wrote {out}: {len(obj['seasons'])} seasons, {n} picks, in {time.time() - t0:.1f} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
