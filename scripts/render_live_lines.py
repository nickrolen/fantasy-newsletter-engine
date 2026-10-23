#!/usr/bin/env python3
"""
render_live_lines.py -- turn output/live_lines_weekN.json into a page.

    py scripts/render_live_lines.py                       # this week
    py scripts/render_live_lines.py --week 3
    py scripts/render_live_lines.py --payload FILE --out FILE
    py scripts/render_live_lines.py --allow-engine-mismatch

One static, self-contained HTML file beside the payload, which opens from the
filesystem on Windows: no server, no build step. Run it after
scripts/refresh_lines.py; the page is only ever as fresh as the payload, and
it says so on its face.

It REFUSES a payload priced by an engine that is not the one on disk -- that
is the whole reason the payload records its engine (modules/live_lines_page.py
and modules/calibration_log.py). --allow-engine-mismatch renders it anyway,
with the mismatch as the loudest element on the page.

EXIT CODES
    0 = written
    1 = refused (engine mismatch, or no payload)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from modules import live_lines_page as page          # noqa: E402
from modules import week_state as ws                 # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--week", type=int, help="default: the week the payload names")
    ap.add_argument("--payload", help="default: output/live_lines_week<week>.json")
    ap.add_argument("--out", help="default: output/live_lines_week<week>.html")
    ap.add_argument("--allow-engine-mismatch", action="store_true",
                    help="render a payload from another engine anyway; the page says so")
    ap.add_argument("--base-path", default=str(PROJECT_ROOT))
    a = ap.parse_args(argv)

    base = Path(a.base_path)
    if a.payload:
        path = Path(a.payload)
    else:
        week = a.week
        if week is None:
            from modules.data_loader import load_all_data
            from datetime import date
            data = load_all_data(base, current_week=None)
            week = ws.week_for_date(data, date.today())
        path = page.payload_path(week, base)
    if not path.is_file():
        print(f"REFUSED: no payload at {path}. Run scripts/refresh_lines.py first.")
        return 1

    payload = page.load_payload(path)
    try:
        written = page.write_page(payload, a.out, base,
                                  allow_engine_mismatch=a.allow_engine_mismatch)
    except page.EngineMismatch as e:
        print(f"REFUSED: {e}")
        return 1
    except page.LiveLinesPayloadError as e:
        print(f"REFUSED: {path} is not a live-lines payload ({e})")
        return 1
    n = len(payload.get("lines") or [])
    print(f"Week {payload['week']} live lines -> {written}")
    print(f"  {n} matchup(s), as of {payload['as_of']}, "
          f"computed {payload.get('generated_at', '?')}")
    if a.allow_engine_mismatch:
        check = page.engine_check(payload, base)
        if not check["ok"]:
            print(f"  WARNING: {check['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
