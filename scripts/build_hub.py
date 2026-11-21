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

--v2 (4b): the NEW hub (modules/hub_v2), beside the current one, never
published: output/hub_v2_preview.html (plaintext, local only; with --out-dir,
DIR/hub_v2_preview.html), and the same page in publish mode inside the
decrypt shell, written ONLY to _to_delete/4b/publish/ to measure its size --
with a throwaway passphrase and salt (a measurement, not a hub anyone opens;
the league passphrase and salt are never read). The current hub's files are
not touched. Needs a payload with the new keys (payload "v2"): one built by
this engine (python scripts/build_hub_state.py, or --state from --out).
4c1: the preview embeds the NEW player card for every Players row, and the
publish-mode measurement builds the new card's encrypted files beside its
index.html. With --out-dir DIR the measurement goes to DIR/publish/.
--archetype-preview (with --v2): the ratings' archetype labels on the card
and in Compare, marked "Preview", in the PREVIEW only; the publish-mode
measurement is skipped (publish mode refuses a preview).

THE SWITCH (5a): config/league_config.json hub.version decides which hub
this publishes. "v1": the current page (modules/hub_page), exactly as before.
"v2": the new hub (modules/hub_v2) to the same output/hub_publish/ -- the
same URL, passphrase and salt -- with output/hub_v2_preview.html as its
plaintext preview; a payload whose new-hub keys or ratings failed is REFUSED
(exit 1), so nothing is published and the last good page stays up. Missing
or any other value: refused. --v2 (the scratch measurement) is unchanged by
the switch.

--v2 --publish-check (5a): the full published new hub, built with a
THROWAWAY passphrase and a fresh salt into a scratch folder
(_to_delete/publish_check/, or --out-dir DIR), then opened as the browser
would: the shell's bundle decrypted and gunzipped, every route the page
links resolved to its screen, every lazy part (cards, headshots, History,
Awards, the issues) decrypted with the key the page or the card index gives
it, every file reached by a key, the plaintext scan, and the sizes against
the budget. Exit 0 only when every check passes. Run it on the real data
before flipping hub.version to "v2". It never reads the league passphrase
or the hub's salt, and never writes output/hub_publish/.

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
    ap.add_argument("--v2", action="store_true",
                    help="build the NEW hub's preview and its publish-mode size measurement (4b); publishes nothing")
    ap.add_argument("--archetype-preview", action="store_true",
                    help="with --v2: show the archetype labels in the preview, marked; never in publish mode (4c1)")
    ap.add_argument("--publish-check", action="store_true",
                    help="with --v2: build the full published new hub with a throwaway key into a scratch folder, "
                         "open every route and part as the browser would, scan it and size it (5a)")
    a = ap.parse_args(argv)
    from modules import hub_state, hub_archive, hub_crypto, hub_publish, hub_version
    from modules.hub_v2 import data as v2data
    if a.publish_check and not a.v2:
        print("REFUSED: --publish-check goes with --v2")
        return 1
    if a.v2:
        from modules.hub_v2 import view, publish as v2pub, tokens
        try:
            if a.publish_check:
                return publish_check(a.base_path, state=a.state, out_dir=a.out_dir)["rc"]
            return run_v2(a.base_path, state=a.state, out_dir=a.out_dir,
                          archetype_preview=a.archetype_preview)["rc"]
        except (hub_state.HubInputError, hub_archive.ArchiveError, view.ViewError, v2pub.V2PublishError,
                tokens.TokenError, hub_publish.PublishError, hub_publish.PlaintextLeak, v2data.V2Error,
                hub_version.V2HubFailed) as e:
            print(f"REFUSED: {e}")
            return 1
    if a.archetype_preview:
        print("REFUSED: --archetype-preview goes with --v2 (the new hub's preview only)")
        return 1
    try:
        res = run(a.base_path, preview_only=a.preview_only, state=a.state, out_dir=a.out_dir)
    except (hub_state.HubInputError, hub_archive.ArchiveError, hub_crypto.PassphraseError,
            hub_publish.PublishError, hub_publish.PlaintextLeak, hub_version.HubVersionError,
            hub_version.V2HubFailed, v2data.V2Error) as e:
        print(f"REFUSED: {e}")
        return 1
    except Exception as e:                           # noqa: BLE001 -- the new hub's renderer, named
        from modules.hub_v2 import view, publish as v2pub, tokens
        if isinstance(e, (view.ViewError, v2pub.V2PublishError, tokens.TokenError)):
            print(f"REFUSED: {e}")
            return 1
        raise
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
    PlaintextLeak like any other file.

    5a: config hub.version "v2" hands the whole build to run_v2_publish (the
    new hub, same directory, same return shape); "v1" goes on below,
    unchanged; anything else raises HubVersionError."""
    from modules import hub_version
    if hub_version.version(base_path) == "v2":
        return run_v2_publish(base_path, preview_only=preview_only, state=state, out_dir=out_dir, echo=echo)
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
    if payload.get("v2_store"):                   # 5b: stored under v2, without the current page's keys
        raise hub_state.HubInputError("this payload was stored under hub.version v2, without the current "
                                      "page's own keys: rebuild it (python scripts/build_hub_state.py)")
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


V2_PUBLISH_SCRATCH = Path("_to_delete") / "4b" / "publish"
V2_PREVIEW = Path("output") / "hub_v2_preview.html"
V2_MEASURE_PASSPHRASE = "a throwaway passphrase for measuring the size only"


def run_v2(base_path=".", *, state=None, out_dir=None, echo=print, archetype_preview: bool = False) -> dict:
    """The new hub (4b, 4c1): its preview, with the new player cards embedded,
    and its publish-mode page and card files built to a scratch folder with a
    throwaway key, to measure what a phone downloads. Returns {"rc",
    "preview", "report"}. The cards fail softly, as in run().
    archetype_preview (4c1): the archetype labels in the preview only,
    marked; no publish-mode measurement (publish mode refuses it)."""
    import json
    from modules import hub_state, hub_archive, hub_cards, hub_crypto
    from modules.hub_v2 import view, page, publish as v2pub, players as v2players
    from datetime import datetime
    base = Path(base_path)
    if state is not None:
        payload = json.loads(Path(state).read_text(encoding="utf-8"))
        if payload.get("schema") != hub_state.SCHEMA:
            raise hub_state.HubInputError(f"{state} is schema {payload.get('schema')}, not {hub_state.SCHEMA}")
    else:
        payload = hub_state.load(base)
    hub_archive.verify(base)
    preview = base / V2_PREVIEW if out_dir is None else Path(out_dir) / V2_PREVIEW.name
    if out_dir is not None:
        from modules import hub_publish
        refusal = hub_publish.scratch_refusal(base, preview)
        if refusal:
            echo(f"REFUSED: {refusal}")
            return {"rc": 1, "preview": None, "report": None}
    if payload.get("v2") is not None and "players" not in payload["v2"]:
        # 4c2: the Players rows live in their own file beside the payload
        from modules.hub_v2 import data as v2data
        sp = Path(state) if state is not None else base / hub_state.PAYLOAD_RELPATH
        v2data.attach_players(payload, hub_state.load_players(sp))
    if (payload.get("v2") or {}).get("players") is None:
        raise view.ViewError("the payload's new-hub keys predate 4c1 (no Players tab): rebuild it with this "
                             "engine (python scripts/build_hub_state.py)")
    if archetype_preview:
        n = v2players.archetype_preview(payload)
        echo(f"Archetype PREVIEW: {n} rostered player(s) labelled (the rest: a rookie under 5 games, or no ratings); "
             "the preview is marked, and publish mode is not measured.")
        for kind in ("rostered", "fa"):
            echo(f" {kind}:")
            for label, who in v2players.archetype_table(payload, kind):
                echo(f"  {label} ({len(who)}): " + "; ".join(f"{n_} ({m_}; {st_}; {tg_})" for n_, m_, st_, tg_ in who))
    cards, preview_cards = None, None
    if (payload.get("cards") or {}).get("players"):
        try:
            cards = hub_cards.load_for(base, payload) if state is None else None
            if cards is None:
                cards = hub_cards.build(base, payload, echo=lambda *a, **k: None)
            hub_cards.check_against(payload, cards)
            preview_cards = v2pub.preview_cards(base, payload, cards)
        except Exception as e:                       # noqa: BLE001 -- the cards fail softly
            cards, preview_cards = None, None
            hub_cards.strip(payload)
            echo(f"PLAYER CARDS FAILED (the preview goes on with plain names): {type(e).__name__}: {e}")
    gen = datetime.fromisoformat(payload["generated_at"])
    now = datetime.now(gen.tzinfo)
    from modules import team_pictures                # 4c3: each team's picture, when stored
    pics, pic_notes = team_pictures.data_uris(base, list((payload.get("v2") or {}).get("team_order") or []))
    for n in pic_notes:
        echo(f"Team picture left out (the monogram shows): {n}")
    html = page.render(view.build(payload, mode="preview", now=now, pictures=pics), cards=preview_cards)
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_text(html, encoding="utf-8")
    echo(f"Wrote {preview} (plaintext; local only; {len(html.encode('utf-8')):,} bytes"
         + (f", {len(preview_cards['cards'])} new player cards embedded" if preview_cards else "") + ").")
    if archetype_preview:
        return {"rc": 0, "preview": str(preview), "report": None}
    pub = base / V2_PUBLISH_SCRATCH if out_dir is None else Path(out_dir) / "publish"
    rep = v2pub.build(base, payload, V2_MEASURE_PASSPHRASE, salt=hub_crypto.new_salt(), out_dir=pub, now=now,
                      cards=cards)
    echo(f"Wrote {rep['dir']}/index.html in publish mode (a throwaway key: a size measurement, never published).")
    echo(f"  index.html as served: {rep['served_bytes']:,} bytes ({rep['served_bytes'] / 1000:.1f} KB, the bundle "
         f"gzipped before encryption); the fonts' share {rep['fonts_served_bytes']:,} bytes")
    echo(f"  with the shell as it is today (no gzip): {rep['served_plain_bytes']:,} bytes; "
         f"the page itself {rep['page_bytes']:,} bytes")
    if rep.get("card_files"):
        c = rep["card_files"]
        echo(f"  new cards: {c['cards']} card files (median {c['card_bytes_median']:,} bytes, largest "
             f"{c['card_bytes_max']:,}), index {c['index_bytes']:,} bytes, {c['photos']} headshots (median "
             f"{c['photo_bytes_median']:,} bytes)")
    if rep.get("league_parts"):
        lp = rep["league_parts"]
        echo(f"  League history: {lp['parts']} encrypted chip files ("
             + ", ".join(f"{k} {v:,}" for k, v in lp["bytes"].items()) + " bytes), loaded on tap")
    echo(f"Plaintext scan: {rep['terms']} terms, no hits.")
    return {"rc": 0, "preview": str(preview), "report": rep}



def _load_payload(base: Path, state):
    import json
    from modules import hub_state
    if state is not None:
        payload = json.loads(Path(state).read_text(encoding="utf-8"))
        if payload.get("schema") != hub_state.SCHEMA:
            raise hub_state.HubInputError(f"{state} is schema {payload.get('schema')}, not {hub_state.SCHEMA}")
        return payload, Path(state)
    return hub_state.load(base), base / hub_state.PAYLOAD_RELPATH


def _v2_cards(base: Path, payload: dict, pub_payload: dict, state, echo, fail):
    """(cards, preview cards) for the new hub, softly: fail(stage, e) on any
    error, as run() does."""
    from modules import hub_cards
    from modules.hub_v2 import publish as v2pub
    cards, pv = None, None
    if (payload.get("cards") or {}).get("players"):
        try:
            cards = hub_cards.load_for(base, payload) if state is None else None
            if cards is None:
                cards = hub_cards.build(base, payload, echo=lambda *a, **k: None)
                echo(f"Built {len(cards['cards'])} player card(s) from this folder's data "
                     f"({cards['seconds']} s); {len(cards['photos'])} with a headshot.")
            hub_cards.check_against(payload, cards)
            pv = v2pub.preview_cards(base, pub_payload, cards)
        except Exception as e:                       # noqa: BLE001 -- the cards fail softly
            fail("build", e)
            cards, pv = None, None
    return cards, pv


def run_v2_publish(base_path=".", *, preview_only: bool = False, state=None, out_dir=None, echo=print) -> dict:
    """hub.version "v2" (5a): the NEW hub is the hub. run()'s work and return
    shape ({"rc", "cards", "cards_error", "payload", "report"}, plus
    "version": "v2"), for the nightly's step 9 and a desk build:
      - REFUSES (hub_version.V2HubFailed) a payload whose new-hub keys or
        ratings failed: under v2 they are hard, like every hub failure;
      - puts the side file back (output/hub_players.json: the Players rows,
        League's History and the keys 5a moved out of the payload); missing or
        stale refuses (hub_v2.data.V2Error);
      - writes output/hub_v2_preview.html (plaintext, local only), or
        DIR/hub_v2_preview.html with out_dir;
      - unless preview_only: the passphrase from HUB_PASSPHRASE, the hub's own
        salt (hub_publish.hub_salt), and the new hub's publish directory --
        output/hub_publish/, or DIR/hub_publish/ -- every file scanned.
    The player cards fail softly, as in run(): plain names, no card files,
    "cards_error" set. The payload returned is the one to keep as state
    (side-file keys not put back; card keys stripped after a card failure)."""
    import copy
    from datetime import datetime
    from modules import hub_state, hub_archive, hub_cards, hub_crypto, hub_publish, hub_version, team_pictures
    from modules.hub_v2 import view, page, publish as v2pub, data as v2data
    base = Path(base_path)
    out_dir = Path(out_dir) if out_dir is not None else None
    if out_dir is not None:
        refusal = hub_publish.scratch_refusal(base, out_dir / V2_PREVIEW.name)
        if refusal:
            echo(f"REFUSED: {refusal}")
            return {"rc": 1, "cards": None, "cards_error": None, "payload": None, "report": None, "version": "v2"}
    payload, spath = _load_payload(base, state)
    hub_version.check_v2_whole(payload)
    hub_archive.verify(base)
    pub_payload = v2data.attach_players(copy.deepcopy(payload), hub_state.load_players(spath))
    err = None

    def fail(stage, e):
        nonlocal err
        err = hub_cards.failure(stage, e)
        hub_cards.strip(payload)
        hub_cards.strip(pub_payload)
        echo(f"PLAYER CARDS FAILED ({stage}; the hub goes on with plain names): {err['error']}")

    cards, preview_cards = _v2_cards(base, payload, pub_payload, state, echo, fail)
    gen = datetime.fromisoformat(payload["generated_at"])
    now = datetime.now(gen.tzinfo)
    pics, notes = team_pictures.data_uris(base, list(pub_payload["v2"].get("team_order") or []))
    for n in notes:
        echo(f"Team picture left out (the monogram shows): {n}")
    preview = (out_dir / V2_PREVIEW.name) if out_dir is not None else base / V2_PREVIEW
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    html = page.render(view.build(copy.deepcopy(pub_payload), mode="preview", now=now, pictures=pics),
                       cards=preview_cards)
    preview.write_text(html, encoding="utf-8")
    echo(f"Wrote {preview} (the new hub, plaintext; local only).")
    if preview_only:
        return {"rc": 0, "cards": None if cards is None else len(cards["cards"]), "cards_error": err,
                "payload": payload, "report": None, "version": "v2"}
    passphrase = hub_crypto.passphrase_from_env()
    pub = hub_publish.publish_dir(base) if out_dir is None else out_dir / "hub_publish"
    gone = v2pub.clear_superseded(pub)
    if gone:
        echo(f"Removed {len(gone)} content-named file(s) an earlier build wrote.")
    salt = hub_publish.hub_salt(base)
    try:
        r = v2pub.build(base, pub_payload, passphrase, salt=salt, out_dir=pub, cards=cards, live=True,
                        pictures=pics, now=now)
    except hub_publish.CardFilesError as e:          # nothing was written yet
        fail("publish", e)
        r = v2pub.build(base, pub_payload, passphrase, salt=salt, out_dir=pub, cards=None, live=True,
                        pictures=pics, now=now)
    echo(f"Wrote {r['dir']} (the new hub, hub.version v2): {len(r['files'])} file(s), "
         f"PBKDF2-SHA256 x {r['iterations']:,}.")
    echo(f"  index.html as served: {r['served_bytes']:,} bytes of the {r['budget_bytes']:,} budget"
         + (" -- OVER BUDGET" if r["over_budget"] else ""))
    if r["over_cap"]:
        echo(f"  lazy files over {r['lazy_cap_bytes']:,} bytes: {r['over_cap']}")
    echo(f"Plaintext scan: {r['terms']} terms, no hits"
         + (f" (bundle re-encrypted {r['reseals']} time(s) after a chance match)" if r["reseals"] else "") + ".")
    return {"rc": 0, "cards": None if cards is None else len(cards["cards"]), "cards_error": err,
            "payload": payload, "report": r, "version": "v2"}


PUBLISH_CHECK_DIR = Path("_to_delete") / "publish_check"


def publish_check(base_path=".", *, state=None, out_dir=None, echo=print) -> dict:
    """--v2 --publish-check (5a): the full published new hub with a
    THROWAWAY passphrase and a fresh salt, into out_dir/publish/ (default
    _to_delete/publish_check/), opened as the browser would
    (modules/hub_v2/publish_check). The league passphrase and the hub's salt
    are never read; output/hub_publish/ is never written. {"rc", "report"}."""
    import copy
    from datetime import datetime
    from modules import hub_state, hub_archive, hub_crypto, hub_publish, hub_version, team_pictures
    from modules.hub_v2 import publish as v2pub, data as v2data, publish_check as pc
    base = Path(base_path)
    od = Path(out_dir) if out_dir is not None else base / PUBLISH_CHECK_DIR
    refusal = hub_publish.scratch_refusal(base, od / "publish" / "index.html")
    if refusal:
        echo(f"REFUSED: {refusal}")
        return {"rc": 1, "report": None}
    payload, spath = _load_payload(base, state)
    fails = hub_version.v2_failures(payload)
    if fails:
        echo("FAIL: under hub.version \"v2\" this payload would be refused: " + "; ".join(fails))
        return {"rc": 1, "report": {"v2_failures": fails}}
    hub_archive.verify(base)
    pub_payload = v2data.attach_players(copy.deepcopy(payload), hub_state.load_players(spath))
    errs = []
    cards, _pv = _v2_cards(base, payload, pub_payload, state, echo,
                           lambda stage, e: errs.append(f"{stage}: {type(e).__name__}: {e}"))
    if errs:
        echo(f"FAIL: the player cards failed ({errs[0]}); the hub would publish with plain names")
    gen = datetime.fromisoformat(payload["generated_at"])
    now = datetime.now(gen.tzinfo)
    pics, notes = team_pictures.data_uris(base, list(pub_payload["v2"].get("team_order") or []))
    pub = od / "publish"
    if pub.exists():
        v2pub.clear_superseded(pub)
        for f in ("index.html",):
            if (pub / f).is_file():
                (pub / f).unlink()
        for q in sorted((pub / "issues").glob("*.enc")) if (pub / "issues").is_dir() else []:
            q.unlink()
    rep = pc.check(base, pub_payload, cards, pub, now=now, pictures=pics, echo=echo,
                   picture_notes=notes, card_errors=errs)
    for line in pc.summary(rep):
        echo(line)
    return {"rc": 0 if rep["ok"] else 1, "report": rep}


if __name__ == "__main__":
    sys.exit(main())
