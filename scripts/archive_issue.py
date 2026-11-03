#!/usr/bin/env python3
"""
archive_issue.py -- archive a published newsletter issue for the hub, once.

    python scripts/archive_issue.py --week N

Reads output/WEEK{N}_NEWSLETTER.html (the issue as sent) into
output/hub_archive/ (private state): its plaintext bytes, an encrypted copy
made once with its own key, and the index. The same bytes again do nothing;
different bytes for a week already archived are refused -- a published issue
is never rewritten. Run it after the issue goes out, never on a draft.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--base-path", default=".")
    a = ap.parse_args(argv)
    from modules import hub_archive, hub_publish
    try:
        r = hub_archive.archive_issue(a.base_path, a.week, avoid=hub_publish.scan_terms(a.base_path))
    except (hub_archive.ArchiveError, hub_publish.PublishError) as e:
        print(f"REFUSED: {e}")
        return 1
    e = r["entry"]
    print(f"Week {a.week}: {'archived' if r['wrote'] else r['why']} -- {e['source']} "
          f"{e['bytes']:,} bytes, sha256 {e['sha256'][:12]}; encrypted {e['enc']} {e['enc_bytes']:,} bytes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
