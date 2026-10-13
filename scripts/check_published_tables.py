#!/usr/bin/env python3
"""
check_published_tables.py -- reconcile every table in a built newsletter.

A relation that does not hold is a wrong number in print: a summary column
that does not count the cells beside it, a finish that disagrees with the
stored standings, FPPG that is not Total / GP, a probability row that does
not sum to 100%, a cell shifted under the wrong header. See
modules/published_tables.py for each table's relations.

USAGE
    py scripts/check_published_tables.py output/WEEK3_NEWSLETTER.html
    py scripts/check_published_tables.py archive/2025-26/output/WEEK*.html

EXIT CODES
    0 = every checked table reconciles
    1 = findings: do not send this page
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules import published_tables as pt  # noqa: E402
from modules.data_loader import CURRENT_SEASON  # noqa: E402


def check_file(path: Path) -> list:
    doc = path.read_text(encoding="utf-8")
    season = pt.season_of(path, doc) or CURRENT_SEASON
    findings, unchecked = pt.check_document(doc, pt.load_context(PROJECT_ROOT, season))
    print(f"\n  {path}  ({season})")
    if unchecked:
        print(f"    UNCHECKED tables (no relations defined): {sorted(set(unchecked))}")
    for f in findings:
        print(f"    - {f}")
    print(f"    {len(findings)} finding(s)")
    return findings


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 1
    total = sum(len(check_file(Path(a))) for a in argv)
    if total:
        print(f"\n  RESULT: {total} finding(s). Do not send until they are fixed.")
        return 1
    print("\n  RESULT: every checked table reconciles.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
