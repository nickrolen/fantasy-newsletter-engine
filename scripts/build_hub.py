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
The preview embeds them in plaintext, headshots included. They fail softly
(run()): a card failure builds the hub with plain names and no card files and
prints PLAYER CARDS FAILED; a plaintext hit in any file still refuses.

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
    from modules import hub_state, hub_archive, hub_crypto, hub_publish
    try:
        res = run(a.base_path, preview_only=a.preview_only, state=a.state, out_dir=a.out_dir)
    except (hub_state.HubInputError, hub_archive.ArchiveError, hub_crypto.PassphraseError,
            hub_publish.PublishError, hub_publish.PlaintextLeak) as e:
        print(f"REFUSED: {e}")
        return 1
    return res["rc"]


def run(base_path=".", *, preview_only: bool = False, state=None, out_dir=None, echo=print) -> dict:
    """Render, encrypt and write; main()'s work, for the nightly run's hub
    step too. Returns {"rc", "cards": how many published (None: none),
    "cards_error": None or {"stage", "error"}, "payload": the payload
    published (plain names after a card failure), "report": the publish
    report}.

    THE CARDS FAIL SOFTLY (Nick, 11-12, like advice): building them, their
    preview bundle or their publish files failing never stops the hub. The
    hub is then built as it is without cards -- every name plain text
    (hub_cards.strip), no card or photo file -- and the failure comes back in
    "cards_error" for the run to record loudly. Never partial cards, never an
    earlier build's card files (clear_superseded runs first). What still
    stops it, as before: the page, the encryption, the archive, a stray file
    and the plaintext scan -- a card file that leaks plaintext is a
    PlaintextLeak like any other file."""
    from modules import hub_state, hub_page, hub_archive, hub_crypto, hub_publish, hub_cards
    base = Path(base_path)
    if out_dir is not None:
        refusal = hub_publish.scratch_refusal(base, Path(out_dir) / "hub_preview.html")
        if refusal:
            echo(f"REFUSED: {refusal}")
            return {"rc": 1, "cards": None, "cards_error": None, "payload": None, "report": None}
    if state is not None:
        import json
        payload = json.loads(Path(state).read_text(encoding="utf-8"))
        if payload.get("schema") != hub_state.SCHEMA:
            raise hub_state.HubInputError(f"{state} is schema {payload.get('schema')}, "
                                          f"not {hub_state.SCHEMA}")
    else:
        payload = hub_state.load(base)
    hub_archive.verify(base)
    out_dir = Path(out_dir) if out_dir is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    preview = base / "output" / "hub_preview.html"
    if out_dir is not None:                 # a scratch build: beside, never inside, its hub_publish/
        preview = out_dir / "hub_preview.html"
    cards, err = None, None

    def fail(stage, e):
        nonlocal cards, err
        err = hub_cards.failure(stage, e)
        cards = None
        hub_cards.strip(payload)
        echo(f"PLAYER CARDS FAILED ({stage}; the hub goes on with plain names): {err['error']}")

    if (payload.get("cards") or {}).get("players"):
        try:
            cards = None if state is not None else hub_cards.load_for(base, payload)
            if cards is None:
                cards = hub_cards.build(base, payload)
                echo(f"Built {len(cards['cards'])} player card(s) from this folder's data "
                     f"({cards['seconds']} s); {len(cards['photos'])} with a headshot.")
            hub_cards.check_against(payload, cards)
        except Exception as e:                       # noqa: BLE001 -- the cards fail softly
            fail("build", e)
    preview_cards = None
    if cards is not None:
        try:
            preview_cards = hub_cards.preview_bundle(base, cards)
        except Exception as e:                       # noqa: BLE001 -- the cards fail softly
            fail("preview", e)
    preview.write_text(hub_page.render(payload, mode="preview", cards=preview_cards), encoding="utf-8")
    echo(f"Wrote {preview} (plaintext; local only).")
    if preview_only:
        return {"rc": 0, "cards": None if cards is None else len(cards["cards"]), "cards_error": err,
                "payload": payload, "report": None}
    passphrase = hub_crypto.passphrase_from_env()
    pub = hub_publish.publish_dir(base) if out_dir is None else out_dir / "hub_publish"
    gone = hub_publish.clear_superseded(pub)
    if gone:
        echo(f"Removed {len(gone)} card/headshot file(s) an earlier build wrote.")
    target = None if out_dir is None else out_dir / "hub_publish"
    try:
        r = hub_publish.build(base, payload, passphrase, cards=cards, out_dir=target)
    except hub_publish.CardFilesError as e:
        # nothing was written yet: the card files fail before any file is
        fail("publish", e)
        preview.write_text(hub_page.render(payload, mode="preview"), encoding="utf-8")
        r = hub_publish.build(base, payload, passphrase, cards=None, out_dir=target)
    echo(f"Wrote {r['dir']}: {len(r['files'])} file(s), PBKDF2-SHA256 x {r['iterations']:,}.")
    for f in r["files"]:
        echo(f"  {f}  {r['sizes'][f]:,} bytes")
    echo(f"Plaintext scan: {r['terms']} terms, no hits"
         + (f" (bundle re-encrypted {r['reseals']} time(s) after a chance match)" if r["reseals"] else "")
         + ".")
    return {"rc": 0, "cards": None if cards is None else len(cards["cards"]), "cards_error": err,
            "payload": payload, "report": r}


if __name__ == "__main__":
    sys.exit(main())
