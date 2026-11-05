#!/usr/bin/env python3
"""
build_hub.py -- render the hub from output/hub_state.json, encrypt it, and
write the publish directory.

    python scripts/build_hub.py              (needs HUB_PASSPHRASE in the environment)
    python scripts/build_hub.py --preview-only
    python scripts/build_hub.py --state PAYLOAD --out-dir DIR [--preview-only]

Writes:
  output/hub_preview.html   the plaintext page, for review on this machine
                            only (ignored; never published)
  output/hub_publish/       index.html (the decrypt shell with the encrypted
                            page) and issues/*.enc (copied from the archive)

The passphrase is read from HUB_PASSPHRASE and nowhere else; it is never
printed or written. Missing or shorter than 20 characters: refused. After
writing, every file in output/hub_publish/ is scanned for every manager,
team and player name and every lore marker; any hit fails (exit 1).

--state and --out-dir (a scratch build): read the payload from PAYLOAD
(scripts/build_hub_state.py --out) and write DIR/hub_preview.html and
DIR/hub_publish/ instead; DIR may not be league state.

Preview the published hub on this machine (fetching the issues needs a
server, not a file:// page):
    python -m http.server 8000 --directory output/hub_publish
    then open http://localhost:8000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=".")
    ap.add_argument("--preview-only", action="store_true",
                    help="write output/hub_preview.html and nothing else (no passphrase needed)")
    ap.add_argument("--state", default=None, help="read the payload from this file (a scratch build)")
    ap.add_argument("--out-dir", default=None,
                    help="write the preview and the publish directory under this folder (a scratch build)")
    a = ap.parse_args(argv)
    from modules import hub_state, hub_page, hub_archive, hub_crypto, hub_publish
    base = Path(a.base_path)
    if a.out_dir is not None:
        from modules.hub_publish import scratch_refusal
        refusal = scratch_refusal(base, Path(a.out_dir) / "hub_preview.html")
        if refusal:
            print(f"REFUSED: {refusal}")
            return 1
    try:
        if a.state is not None:
            import json
            payload = json.loads(Path(a.state).read_text(encoding="utf-8"))
            if payload.get("schema") != hub_state.SCHEMA:
                raise hub_state.HubInputError(f"{a.state} is schema {payload.get('schema')}, "
                                              f"not {hub_state.SCHEMA}")
        else:
            payload = hub_state.load(base)
        hub_archive.verify(base)
        out_dir = Path(a.out_dir) if a.out_dir is not None else None
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
        preview = base / "output" / "hub_preview.html"
        if out_dir is not None:                 # a scratch build: beside, never inside, its hub_publish/
            preview = out_dir / "hub_preview.html"
        preview.write_text(hub_page.render(payload, mode="preview"), encoding="utf-8")
        print(f"Wrote {preview} (plaintext; local only).")
        if a.preview_only:
            return 0
        passphrase = hub_crypto.passphrase_from_env()
        r = hub_publish.build(base, payload, passphrase,
                              out_dir=None if out_dir is None else out_dir / "hub_publish")
    except (hub_state.HubInputError, hub_archive.ArchiveError, hub_crypto.PassphraseError,
            hub_publish.PublishError, hub_publish.PlaintextLeak) as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"Wrote {r['dir']}: {len(r['files'])} file(s), PBKDF2-SHA256 x {r['iterations']:,}.")
    for f in r["files"]:
        print(f"  {f}  {r['sizes'][f]:,} bytes")
    print(f"Plaintext scan: {r['terms']} terms, no hits"
          + (f" (bundle re-encrypted {r['reseals']} time(s) after a chance match)" if r["reseals"] else "")
          + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
