#!/usr/bin/env python3
"""
check_yahoo_settings.py -- refuse when a Yahoo league setting the engine
models has changed (modules/yahoo_settings.py; design s.4, invariant 9).

    python scripts/check_yahoo_settings.py                 one read-only Yahoo call
    python scripts/check_yahoo_settings.py --from-file F   a saved response instead

Exit 0: every modelled setting matches config/league_config.json (printed).
Exit 1: a difference ("Yahoo setting X changed from A to B; update config or
revert in Yahoo.") or a modelled setting missing on either side. Nothing is
ever written to config.

--save-scrubbed F writes the response with only the compared fields (no
league name, key, password, links or chat ids): how
tests/fixtures/yahoo_settings_2026-10-31.json was made.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import yahoo_settings as ys   # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-file", type=Path, help="a saved league/<key>/settings response")
    ap.add_argument("--save-scrubbed", type=Path, help="write the scrubbed response here")
    a = ap.parse_args(argv)
    raw = (json.loads(a.from_file.read_text(encoding="utf-8")) if a.from_file
           else ys.fetch_raw())
    if a.save_scrubbed:
        a.save_scrubbed.write_text(json.dumps(ys.scrub(raw), indent=1) + "\n", encoding="utf-8")
        print(f"scrubbed response saved to {a.save_scrubbed}")
    try:
        got = ys.check(raw)
    except (ys.SettingsDrift, ys.SettingMissing) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    print("Yahoo league settings match config/league_config.json:")
    for k, v in got.items():
        print(f"  {k}: {json.dumps(v, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
