#!/usr/bin/env python3
"""
headshots.py -- add player photos to the league's headshot library
(assets/headshots/, private state; task 40a). Nick supplies every photo:
nothing in the engine fetches one from the web.

    python scripts\\headshots.py add <file> "<Player Name>" [--replace]
    python scripts\\headshots.py add-folder <folder> [--replace]
    python scripts\\headshots.py missing

add          crops the photo to a centred square, resizes it to 320 x 320 and
             saves it as WebP under the player's slug (assets\\headshots\\
             victor-wembanyama.webp). The name must be a player the engine
             knows; an unknown or ambiguous name is refused with the near
             matches. An existing photo is kept unless --replace.
add-folder   the same for every image in a folder, each named after its player
             ("Victor Wembanyama.png", "victor-wembanyama.jpg"): one line per
             file -- added, already there, unknown name, ambiguous, not an image.
missing      who has no photo: rostered players by team, then the free agents
             the hub lists.

Adding needs Pillow (python -m pip install pillow); nothing else here does.
This script never pushes: after adding, run  python scripts\\state.py push
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _kb(n: int) -> str:
    return f"{n / 1000:.0f} KB"


def main(argv=None, out=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("add")
    a1.add_argument("file")
    a1.add_argument("name")
    a1.add_argument("--replace", action="store_true")
    a2 = sub.add_parser("add-folder")
    a2.add_argument("folder")
    a2.add_argument("--replace", action="store_true")
    sub.add_parser("missing")
    a = ap.parse_args(argv)
    from modules import headshots as hs
    base = Path(a.base_path)
    try:
        if a.cmd == "add":
            r = hs.add(base, a.file, a.name, replace=a.replace)
            rel = Path(r["path"]).resolve().relative_to(base.resolve()).as_posix()
            if r["status"] == "already there":
                out(f"ALREADY THERE: {r['player']} has a photo ({rel}). Nothing changed; "
                    "use --replace to replace it.")
                return 0
            out(f"{r['status'].upper()}: {r['player']} -> {rel} ({_kb(r['bytes'])})"
                + (f"; removed {r['removed'].name}" if r["removed"] else ""))
            out(hs.PUSH_HINT)
            return 0
        if a.cmd == "add-folder":
            rows = hs.add_folder(base, a.folder, replace=a.replace)
            if not rows:
                out(f"{a.folder}: no files")
                return 0
            for r in rows:
                what = r["status"].upper()
                if r["status"] in ("added", "replaced"):
                    out(f"  {what:13} {r['file']} -> {r['player']} ({_kb(r['bytes'])})"
                        + (f"; {r['detail']}" if r["detail"] else ""))
                elif r["status"] == "already there":
                    out(f"  {what:13} {r['file']} -> {r['player']} (kept; --replace to replace)")
                else:
                    out(f"  {what:13} {r['file']}: {r['detail']}")
            counts = {}
            for r in rows:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            out(", ".join(f"{v} {k}" for k, v in counts.items()))
            if counts.get("added") or counts.get("replaced"):
                out(hs.PUSH_HINT)
            bad = sum(v for k, v in counts.items() if k not in ("added", "replaced", "already there"))
            return 1 if bad else 0
        m = hs.missing(base)
        out(f"Headshots: {m['rostered_with']} of {m['rostered']} rostered players have one; "
            f"{len(m['free_agents']) - len(m['free_agents_missing'])} of {len(m['free_agents'])} "
            f"free agents the hub lists; {m['library']} in the library.")
        out("Rostered, missing:")
        for t in m["teams"]:
            out(f"  {t['team']} ({t['manager']}), {len(t['missing'])} of {t['of']}: "
                + (", ".join(t["missing"]) if t["missing"] else "none"))
        out("Free agents the hub lists, missing: "
            + (", ".join(m["free_agents_missing"]) if m["free_agents_missing"] else "none"))
        return 0
    except hs.HeadshotError as e:
        out(f"REFUSED: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
