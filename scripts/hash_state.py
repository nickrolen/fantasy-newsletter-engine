#!/usr/bin/env python3
"""
hash_state.py -- a record of every state file, so a builder can prove it
changed none (the rule: builders write no file in config/STATE_MANIFEST.json).

    python scripts/hash_state.py OUT.json            write the record
    python scripts/hash_state.py --compare A.json B.json

Every file state_manifest.present() lists: SHA-256, size and mtime_ns.
Lore-bearing paths (any path with "lore" in it) are recorded by size and
mtime only and never opened (lore only through output/lore_for_drafting.json).
Run it before reading any code and again at the end; --compare names every
file added, removed or changed. Write the records to scratch (_to_delete\\<job>\\).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def record() -> dict:
    from modules import state_manifest
    m = state_manifest.load(ROOT)
    out = {}
    for rel in m.present(ROOT):
        p = ROOT / rel
        st = p.stat()
        rec = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": None}
        if "lore" not in rel.lower():
            rec["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        out[rel] = rec
    return out


def digest(rec: dict) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--compare"] and len(argv) == 3:
        a, b = (json.loads(Path(x).read_text(encoding="utf-8")) for x in argv[1:])
        added, removed = sorted(set(b) - set(a)), sorted(set(a) - set(b))
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        for k in added:
            print(f"ADDED    {k}")
        for k in removed:
            print(f"REMOVED  {k}")
        for k in changed:
            print(f"CHANGED  {k}")
        print(f"{len(a)} before, {len(b)} after; {digest(a)} / {digest(b)}; "
              f"{'IDENTICAL' if not (added or removed or changed) else 'DIFFERENT'}")
        return 0 if not (added or removed or changed) else 1
    if len(argv) != 1:
        print(__doc__)
        return 2
    rec = record()
    Path(argv[0]).write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    lore = sum(1 for v in rec.values() if v["sha256"] is None)
    print(f"{len(rec)} files ({lore} lore, size and mtime only) -> {argv[0]}; {digest(rec)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
