"""
prepare_prompts.py -- the three drafting prompts, filled (task 10a).

    python scripts\\prepare_prompts.py --week N

Run it after Step 6.5 (format_stats_report), between `python scripts\\state.py
pull` and `push` like any manual run. It writes output\\prompts_weekN.md: the
files to upload with Part 1, by path, then Parts 1, 2 and 3, ready to paste
into a new drafting chat (WEEKLY_WORKFLOW.md Step 7). The file holds names:
it is league state (config/STATE_MANIFEST.json), never committed.

    --out PATH     write somewhere else (a check run; the default is
                   output\\prompts_weekN.md)

modules/prepare_prompts.py does the work and says where each part comes
from. Anything missing or disagreeing refuses with the reason (exit 1);
nothing is guessed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fill the three drafting prompts for week N.")
    ap.add_argument("--week", type=int, required=True, help="the week being reported")
    ap.add_argument("--out", type=Path, default=None, help="output path (default output/prompts_weekN.md)")
    ap.add_argument("--base-path", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        # a refusal can name a player with an accent; a Windows console must not crash on it
        sys.stdout.reconfigure(errors="replace")
    from modules import prepare_prompts as pp
    try:
        p = pp.write(args.base_path, args.week, out=args.out)
    except pp.PromptsRefused as e:
        print(f"REFUSED: {e}")
        return 1
    try:
        shown = p.resolve().relative_to(Path(args.base_path).resolve())
    except ValueError:
        shown = p
    print(f"Wrote {shown}. Open it and follow it top to bottom: upload the listed files with "
          "Part 1, then paste Parts 1, 2 and 3 in order.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
