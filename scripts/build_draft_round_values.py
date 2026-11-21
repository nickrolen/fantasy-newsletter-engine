#!/usr/bin/env python3
"""
build_draft_round_values.py -- write data/historical/DRAFT_ROUND_VALUES.json:
what a live draft pick is worth, by round (modules/draft_values; H56 s.4.3,
replacing config/DRAFT_PICK_VALUES.json, Nick 11-21).

    python scripts/build_draft_round_values.py           write the file
    python scripts/build_draft_round_values.py --check   rebuild in memory and compare (exit 1 if it differs)

Reads only; writes only the one file. Run at the season reset, after the
finished season joins the league log (SEASON_RESET), so its draft counts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    from modules import draft_values as DV
    obj = DV.build(ROOT)
    text = json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
    out = ROOT / DV.FILE
    if a.check:
        same = out.is_file() and out.read_text(encoding="utf-8") == text
        print(f"{out}: {'identical' if same else 'DIFFERS from a rebuild'}")
        return 0 if same else 1
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}: drafts {obj['drafts']}, {obj['picks']} live picks.")
    for m, blob in obj["measures"].items():
        rows = " | ".join(f"R{r} {v['value']} (n {v['n']})" for r, v in blob["rounds"].items())
        print(f"  {m}: k {blob['k']}, curve {blob['curve']['a']} + {blob['curve']['b']} ln(r): {rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
