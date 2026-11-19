"""
hub_v2/publish.py -- the new hub in publish mode: the same page, encrypted
inside the EXISTING decrypt shell (hub_page.shell_html), built only to a
scratch folder until the switch-over, to measure what a phone downloads.

    build(base, payload, passphrase, salt=..., out_dir=...) -> report
        out_dir/index.html   the shell with the encrypted bundle
                             {"page": the v2 page, "issues": {file: key}}
        Every file written is scanned (hub_publish.scan_dir) for every manager,
        team and player name and every lore marker; a hit raises PlaintextLeak.

REFUSES to write into output/hub_publish/ (the live hub's directory) or any
league-state path: nothing new is published before the switch-over (step 5).

THE SHELL'S TWO CHANGES, made here on hub_page.shell_html's string (each
RAISES unless its anchor is found exactly once; hub_page.py is untouched):
  1. its Content-Security-Policy gains "font-src data:", without which the
     embedded fonts are blocked (default-src 'none'); the current page sets
     no font, so its shell never needed it;
  2. (gz=True, the default) the bundle is gzipped before encryption, as the
     design README's budget assumes ("the page and its data are gzipped, then
     encrypted"), and marked "z": "gzip"; the shell gunzips it after
     decrypting (DecompressionStream, which the player cards already need).
     Without it the page is ~470 KB as served, over the 300 KB budget, the
     fonts alone ~133 KB of it. gz=False builds the shell as it is today,
     for the comparison.

THE NEW CARD'S FILES (4c1; cards=, hub_cards.build's result for the payload):
    cards/<sha16>.enc   one per player: his new card, rendered at build time
                        (card.view -> page_players.card_html), gzipped JSON
                        {"html"}; encrypted by its content
    photos/<sha16>.enc  one per headshot: hub_cards' own rule (the same bytes
                        and the same subkey give the same file as the current
                        hub's)
    cards/<sha16>.enc   the index: {"v": 2, "cards": {key: {"card", "photo"}}},
                        whose file and key ride in the page bundle ("cards"),
                        fetched on the first tap (HUB.cards())
A card tap fetches the index once, then that player's card file and headshot.
The current hub's card files (hub_cards.publish_files) are not touched.

LEAGUE'S HISTORY (4c4): each History chip's HTML (page_league.chip_html),
rendered at build time, gzipped JSON {"html"}, encrypted by its content as
parts/<sha16>.enc. Each chip's file and key ride inside the ENCRYPTED page
(data-part on its pane); HUB.part opens a chip's file on its first tap. A
payload without the History (no side file) builds the page with the chips'
panes empty, saying why: never a plaintext copy.

An ARCHETYPE PREVIEW (build_hub.py --v2 --archetype-preview) is never built in
publish mode: build() refuses a payload that carries one.
"""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime
from pathlib import Path

CSP_FROM = "img-src data: blob:\">"
CSP_TO = "img-src data: blob:; font-src data:\">"


class V2PublishError(RuntimeError):
    pass


OPEN_FROM = ".then(function(pt){return JSON.parse(new TextDecoder().decode(pt));});"
OPEN_TO = (".then(function(pt){if(B.z!=='gzip'){return JSON.parse(new TextDecoder().decode(pt));}"
           "if(typeof DecompressionStream==='undefined'){throw new Error('old browser');}"
           "return new Response(new Blob([pt]).stream().pipeThrough(new DecompressionStream('gzip')))"
           ".text().then(JSON.parse);});")


def shell(bundle_json: str, gz: bool = True) -> str:
    from .. import hub_page
    s = hub_page.shell_html(bundle_json)
    if s.count(CSP_FROM) != 1:
        raise V2PublishError("the decrypt shell's Content-Security-Policy changed: cannot add font-src data:")
    s = s.replace(CSP_FROM, CSP_TO)
    if gz:
        if s.count(OPEN_FROM) != 1:
            raise V2PublishError("the decrypt shell's openWith changed: cannot add the gunzip step")
        s = s.replace(OPEN_FROM, OPEN_TO)
    return s


def seal(passphrase: str, inner: bytes, gz: bool, **kw) -> dict:
    """The page bundle: hub_crypto.make_bundle on the (gzipped) inner JSON."""
    from .. import hub_crypto
    if gz:
        b = hub_crypto.make_bundle(passphrase, gzip.compress(inner, 9, mtime=0), **kw)
        b["z"] = "gzip"
        return b
    return hub_crypto.make_bundle(passphrase, inner, **kw)


def open_inner(passphrase: str, bundle: dict) -> dict:
    """What the shell does, in Python (tests): decrypt, gunzip if marked."""
    from .. import hub_crypto
    pt = hub_crypto.open_bundle(passphrase, {k: v for k, v in bundle.items() if k != "z"})
    if bundle.get("z") == "gzip":
        pt = gzip.decompress(pt)
    return json.loads(pt)


def refusal(base, out_dir) -> str:
    from ..hub_publish import scratch_refusal, PUBLISH_RELDIR
    b = Path(base).resolve()
    o = Path(out_dir).resolve()
    live = (b / PUBLISH_RELDIR).resolve()
    if o == live or live in o.parents or o in live.parents:
        return f"{out_dir} is (or holds) the live hub's {PUBLISH_RELDIR}: nothing new is published before the switch-over"
    return scratch_refusal(b, o / "index.html")


def card_html_all(payload: dict, cards_obj: dict) -> dict:
    """{key: the new card's HTML} for every Players row with a card."""
    from . import card, page_players
    return {k: page_players.card_html(v) for k, v in card.views(payload, cards_obj).items()}


def preview_cards(base, payload: dict, cards_obj: dict) -> dict:
    """The plaintext preview's new cards: {"cards": {key: {"html", "photo":
    a data URI or None}}} (embedded in DIR/hub_v2_preview.html only)."""
    from .. import headshots
    out = {}
    for k, h in card_html_all(payload, cards_obj).items():
        ph = cards_obj["photos"].get(k)
        out[k] = {"html": h, "photo": headshots.data_uri(Path(base) / ph) if ph else None}
    return {"v": 2, "cards": out}


def card_files(base, payload: dict, cards_obj: dict, root_key: bytes, terms=()) -> tuple:
    """({relative path: bytes}, the index's {"file", "key"}, a size report)."""
    import hashlib
    from .. import hub_crypto, hub_cards
    K = hub_crypto.subkey(root_key, hub_crypto.CARDS_INFO)
    files = {}

    def put(dirname: str, plaintext: bytes) -> dict:
        k, blob = hub_crypto.seal_by_content(K, plaintext, terms)
        rel = f"{dirname}/{hashlib.sha256(blob).hexdigest()[:16]}.enc"
        files[rel] = blob
        return {"file": rel, "key": hub_crypto.b64(k)}

    idx, card_sizes, photo_sizes = {}, [], []
    for k, h in sorted(card_html_all(payload, cards_obj).items()):
        ref = put(hub_cards.CARD_DIR, hub_cards._gz({"html": h}))
        card_sizes.append(len(files[ref["file"]]))
        ph = cards_obj["photos"].get(k)
        pref = None
        if ph:
            pref = put(hub_cards.PHOTO_DIR, (Path(base) / ph).read_bytes())
            photo_sizes.append(len(files[pref["file"]]))
        idx[k] = {"card": ref, "photo": pref}
    ref = put(hub_cards.CARD_DIR, hub_cards._gz({"v": 2, "cards": idx}))
    srt = sorted(card_sizes)
    rep = {"cards": len(idx), "index_bytes": len(files[ref["file"]]),
           "card_bytes_median": srt[len(srt) // 2] if srt else 0, "card_bytes_max": srt[-1] if srt else 0,
           "photo_bytes_median": sorted(photo_sizes)[len(photo_sizes) // 2] if photo_sizes else 0,
           "photos": len(photo_sizes), "files": len(files)}
    return files, ref, rep


PART_DIR = "parts"


def league_files(vm: dict, root_key: bytes, terms=()) -> tuple:
    """({relative path: bytes}, {chip: {"file", "key"}}, a size report) for
    League's History chips (4c4), from the view model's history."""
    import hashlib
    from .. import hub_crypto, hub_cards
    from . import page as _page, page_league
    h = (vm.get("league") or {}).get("history")
    if not h:
        return {}, {}, None
    K = hub_crypto.subkey(root_key, hub_crypto.CARDS_INFO)
    files, refs, sizes = {}, {}, {}
    for chip, _lab in h["chips"]:
        html = page_league.chip_html(h, chip, _page._mono)
        k, blob = hub_crypto.seal_by_content(K, hub_cards._gz({"html": html}), terms)
        rel = f"{PART_DIR}/{hashlib.sha256(blob).hexdigest()[:16]}.enc"
        files[rel] = blob
        refs[chip] = {"file": rel, "key": hub_crypto.b64(k)}
        sizes[chip] = len(blob)
    return files, refs, {"parts": len(files), "bytes": sizes, "largest": max(sizes.values()) if sizes else 0}


def build(base, payload: dict, passphrase: str, *, salt: bytes, out_dir, iterations: int = None,
          terms=None, now: datetime = None, gz: bool = True, cards: dict = None) -> dict:
    from .. import hub_archive, hub_crypto, hub_publish
    from . import view, page
    why = refusal(base, out_dir)
    if why:
        raise V2PublishError(why)
    if ((payload.get("v2") or {}).get("ratings") or {}).get("preview"):
        raise V2PublishError("this payload carries an archetype preview (--archetype-preview): a preview is "
                             "never built in publish mode")
    base = Path(base)
    out = Path(out_dir)
    gen = datetime.fromisoformat(payload["generated_at"])
    from .. import team_pictures
    pics, _notes = team_pictures.data_uris(base, list((payload.get("v2") or {}).get("team_order") or []))
    vm = view.build(payload, mode="publish", now=now or datetime.now(gen.tzinfo), pictures=pics)
    idx = hub_archive.verify(base)
    by_file = {e["enc"]: e for e in idx["issues"]}
    terms = terms if terms is not None else hub_publish.scan_terms(base)
    kw = {"salt": salt} if iterations is None else {"salt": salt, "iterations": iterations}
    inner_obj = {"page": None, "issues": {f: e["key_b64"] for f, e in by_file.items()}}
    cfiles, crep, lrep = {}, None, None
    root = hub_crypto.derive_key(passphrase, salt, kw.get("iterations", hub_crypto.ITERATIONS))
    lfiles, lrefs, lrep = league_files(vm, root, terms)
    vm["league"]["parts"] = lrefs
    vm["league"]["history"] = None                # never in the page itself: only its encrypted files
    html = page.render(vm)
    inner_obj["page"] = html
    cfiles.update(lfiles)
    if cards is not None:
        files2, cref, crep = card_files(base, payload, cards, root, terms)
        cfiles.update(files2)
        inner_obj["cards"] = cref
    inner = json.dumps(inner_obj, separators=(",", ":")).encode("utf-8")
    for attempt in range(1, hub_publish.MAX_RESEAL + 1):
        bundle = seal(passphrase, inner, gz, **kw)
        sh = shell(hub_crypto.bundle_json(bundle), gz).encode("utf-8")
        if not hub_publish.hits(sh, terms):
            break
    else:
        raise hub_publish.PlaintextLeak("the v2 shell matched a scan term after every re-encryption")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_bytes(sh)
    for f, b in cfiles.items():
        (out / f).parent.mkdir(parents=True, exist_ok=True)
        (out / f).write_bytes(b)
    scan = hub_publish.scan_dir(out, terms)
    if scan["hits"]:
        raise hub_publish.PlaintextLeak(f"plaintext in {out}: {scan['hits']}")
    # the other variant's size, for the comparison (never written)
    other = len(shell(hub_crypto.bundle_json(seal(passphrase, inner, not gz, **kw)), not gz).encode("utf-8"))
    return {"dir": str(out), "files": scan["files"], "terms": len(terms), "reseals": attempt - 1, "gzip": gz,
            "card_files": crep, "league_parts": lrep, **measure(html, len(sh), other if gz else len(sh), inner)}


def measure(html: str, served: int, served_plain: int, inner: bytes) -> dict:
    """The size report: index.html as served (gzipped bundle, and as the shell
    is today), the page, and the fonts' share: their bytes in the gzipped
    bundle as served (base64 data barely compresses), and in the plain one."""
    fonts = re.findall(r"data:font/woff2;base64,[A-Za-z0-9+/=]+", html)
    flen = sum(len(m) for m in fonts)
    without = inner
    for m in fonts:
        without = without.replace(m.encode("ascii"), b"")
    gz_with = len(gzip.compress(inner, 9, mtime=0))
    gz_without = len(gzip.compress(without, 9, mtime=0))
    return {"served_bytes": served, "served_plain_bytes": served_plain,
            "page_bytes": len(html.encode("utf-8")), "inner_bytes": len(inner),
            "fonts_in_page_bytes": flen, "fonts_served_plain_bytes": flen * 4 // 3,
            "fonts_served_bytes": (gz_with - gz_without) * 4 // 3}
