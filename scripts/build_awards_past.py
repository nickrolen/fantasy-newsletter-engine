#!/usr/bin/env python3
"""
build_awards_past.py -- past seasons' awards for the record book (4c6 part B).

    python scripts\\build_awards_past.py            write data\\historical\\AWARDS_PAST.json
    python scripts\\build_awards_past.py --check    build and validate, write nothing
    python scripts\\build_awards_past.py --out data\\historical\\AWARDS_PAST.json

MVP with wins swung, Trade of the Year and Most improved for every season
2017-18 to 2025-26, through each season's own regular season, by
modules/awards_past (modules/awards' definitions). Public history like
DRAFT_OVR.json: built here, on Nick's machine, where the league log lives;
committed; the runner never rebuilds it. --out must be inside
data\\historical\\ (anything else REFUSES before a byte is written). About
25 s.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=None, help="the file to write (inside data/historical/)")
    ap.add_argument("--check", action="store_true", help="build and validate only")
    ap.add_argument("--base-path", default=str(ROOT))
    a = ap.parse_args(argv)
    from modules import awards_past as P
    base = Path(a.base_path)
    out = Path(a.out) if a.out else base / P.FILE
    if not a.check:
        try:                                      # refuse before the 25-second build
            p = (out if out.is_absolute() else base / out).resolve()
            if (base / "data" / "historical").resolve() not in p.parents:
                raise P.AwardsPastError(f"refused: {p} is not inside {(base / 'data' / 'historical').resolve()}")
        except P.AwardsPastError as e:
            print(f"REFUSED: {e}")
            return 1
    t0 = time.time()
    blob = P.build(base)
    for s, v in blob["seasons"].items():
        bits = []
        for k in P.PAST:
            w = v["awards"][k]["winner"]
            bits.append(f"{k} {w['label']} {w['value']:,.1f}" if w else f"{k} none")
        print(f"{s}: " + "; ".join(bits))
    if a.check:
        print(f"OK: {len(blob['seasons'])} seasons built and valid in {time.time() - t0:.1f} s (nothing written).")
        return 0
    try:
        p = P.write(blob, out, base)
    except P.AwardsPastError as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"Wrote {p} ({len(blob['seasons'])} seasons) in {time.time() - t0:.1f} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
