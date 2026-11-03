#!/usr/bin/env python3
"""
nightly.py -- the nightly run, Monday's pre-tip run, and the closing line
(step 1c-i). The logic is modules/nightly.py; its docstring lists the steps.

    python scripts\\nightly.py                        the nightly run
    python scripts\\nightly.py --pretip               Monday, before the first tip
    python scripts\\nightly.py --closing --week N     after Monday's window closes
    python scripts\\nightly.py --scheduled            1c-ii's cron: does nothing unless
                                                     the league clock reads 00:xx

Exit 0: the run finished (a price lock included: a lock is not a failure).
Exit 1: a step refused; it is named, the run stopped there, the outputs after
it are as the last good run left them, and the run is recorded in
output/nightly_runs.jsonl.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.nightly import main   # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
