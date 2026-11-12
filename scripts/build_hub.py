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
                            page), issues/*.enc (copied from the archive), and
                            the player cards: cards/*.enc and photos/*.enc
                            (task 40; modules/hub_cards)

THE CARDS: output/hub_cards.json when the nightly run built it for this
payload (same generated_at and engine); otherwise built here from this
folder's data (a desk build, a scratch build), which takes a few seconds more.
The preview embeds them in plaintext, headshots included.

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
    from modules import hub_state, hub_page, hub_archive, hub_crypto, hub_publish, hub_cards
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
        cards = None
        if (payload.get("cards") or {}).get("players"):
            cards = None if a.state is not None else hub_cards.load_for(base, payload)
            if cards is None:
                cards = hub_cards.build(base, payload)
                print(f"Built {len(cards['cards'])} player card(s) from this folder's data "
                      f"({cards['seconds']} s); {len(cards['photos'])} with a headshot.")
            hub_cards.check_against(payload, cards)
        preview.write_text(hub_page.render(payload, mode="preview",
                                           cards=None if cards is None else hub_cards.preview_bundle(base, cards)),
                           encoding="utf-8")
        print(f"Wrote {preview} (plaintext; local only).")
        if a.preview_only:
            return 0
        passphrase = hub_crypto.passphrase_from_env()
        pub = hub_publish.publish_dir(base) if out_dir is None else out_dir / "hub_publish"
        gone = hub_publish.clear_superseded(pub)
        if gone:
            print(f"Removed {len(gone)} card/headshot file(s) an earlier build wrote.")
        r = hub_publish.build(base, payload, passphrase, cards=cards,
                              out_dir=None if out_dir is None else out_dir / "hub_publish")
    except (hub_state.HubInputError, hub_archive.ArchiveError, hub_crypto.PassphraseError,
            hub_publish.PublishError, hub_publish.PlaintextLeak, hub_cards.CardsError) as e:
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
