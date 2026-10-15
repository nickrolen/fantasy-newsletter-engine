"""One-time: valence from a single string to manager -> label.

Why, and the two entries that forced it: see modules/lore_valence.py.

Single-manager entries convert mechanically -- the same label, now keyed by
the manager it was always about. Nothing is reinterpreted.

The two multi-manager entries cannot convert mechanically, because the
scalar never said which manager it referred to. Their second manager is
listed in NEEDS_NICK below with the value this script writes and the reason.
Those are sign inversions of sentences Nick already approved, not new
characterisations, but they are still interpretations of his lore and he
should confirm or flip them.

Idempotent: an entry already carrying a dict is left alone. Dry run unless
--apply. The lore file is gitignored (the repo is public, the lore is not),
so this script is the only committed record of the change.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.lore_valence import LABELS, managers_in  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LORE = ROOT / "config" / "LEAGUE_LORE.json"

# entry id -> {manager: label}, for entries naming more than one manager.
# Each is the inverse of the approved scalar for the manager the sentence
# is NOT about.
NEEDS_NICK = {
    "written-nick-has-been-known-to-reach-in-trades-e": {
        "Nick": "negative",     # the approved scalar; the sentence is about Nick
        "Benton": "positive",   # INFERRED: he gets the better of Nick in trades
    },
    "written-nick-has-gotten-the-better-of-garrett-in": {
        "Nick": "positive",     # the approved scalar
        "Garrett": "negative",  # INFERRED: he comes off worse in those dealings
    },
}


def migrate(entries: list[dict]) -> tuple[list[str], list[str], list[str]]:
    converted, explicit, skipped = [], [], []
    for e in entries:
        eid = e.get("id", "<no id>")
        v = e.get("valence")
        if isinstance(v, dict):
            skipped.append(f"{eid}: already a mapping")
            continue
        if eid in NEEDS_NICK:
            e["valence"] = dict(NEEDS_NICK[eid])
            explicit.append(f"{eid}: {e['valence']}")
            continue
        if v not in LABELS:
            # Rejected and alias entries carry no valence, by design.
            skipped.append(f"{eid}: no scalar valence ({v!r})")
            continue
        named = managers_in(e)
        if len(named) != 1:
            skipped.append(f"{eid}: scalar {v!r} but names {named} "
                           "-- add it to NEEDS_NICK")
            continue
        e["valence"] = {named[0]: v}
        converted.append(f"{eid}: {{{named[0]!r}: {v!r}}}")
    return converted, explicit, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write the file; otherwise report and change nothing")
    ap.add_argument("--path", default=str(LORE))
    args = ap.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"not found: {path}")
        return 1
    lore = json.loads(path.read_text(encoding="utf-8"))
    converted, explicit, skipped = migrate(lore["entries"])

    print(f"converted mechanically: {len(converted)}")
    for line in converted:
        print(f"  {line}")
    print(f"\nneeds Nick's confirmation: {len(explicit)}")
    for line in explicit:
        print(f"  {line}")
    print(f"\nleft alone: {len(skipped)}")
    for line in skipped:
        if "no scalar valence" not in line:
            print(f"  {line}")

    if not args.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply.")
        return 0
    path.write_text(json.dumps(lore, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"\nwritten: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
