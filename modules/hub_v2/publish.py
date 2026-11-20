"""
hub_v2/publish.py -- the new hub in publish mode: the page, gzipped, then
encrypted, inside the new hub's decrypt shell (hub_page.shell_html(...,
"v2")), and every lazy part encrypted by its content.

    build(base, payload, passphrase, salt=..., out_dir=..., live=False) -> report
        out_dir/index.html      the shell with the encrypted bundle
                                {"page": the v2 page, "issues": {file: key},
                                 "cards": the card index's {file, key}}
        out_dir/issues/*.enc    the newsletter archive's files, byte for byte
        out_dir/cards/*.enc     the new cards and their index (below)
        out_dir/photos/*.enc    the headshots (the same files as the current hub's)
        out_dir/parts/*.enc     League's History chips and Awards (below)
        Every file written is scanned (hub_publish.scan_dir) for every manager,
        team and player name, every team picture and every lore marker; a hit
        raises PlaintextLeak. A file in out_dir the build does not write is a
        stray: PublishError (clear_superseded removes an earlier build's
        content-named files first).

LIVE OR SCRATCH (5a). live=False (the default) is a scratch build: it REFUSES
output/hub_publish/ and any league-state path, as before the switch-over.
live=True is the real publisher, called only by scripts/build_hub.run when
config hub.version is "v2": it writes the live hub's directory, with the
league passphrase and the hub's own salt (hub_publish.hub_salt), which that
caller reads; nothing here reads either.

THE SHELL (4b decision 1, built properly in 5a): hub_page.shell_html(bundle,
"v2") -- the current shell's form, stored key and loader, plus "font-src
data:" in its Content-Security-Policy and SHELL_JS_V2, which gunzips a bundle
marked "z": "gzip" and tells a browser without DecompressionStream "This
browser is too old to open the hub. Update iOS or Chrome." instead of "Wrong
passphrase". gz=False (a size comparison only, never written) seals the page
uncompressed in the current hub's shell.

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

class V2PublishError(RuntimeError):
    pass


def shell(bundle_json: str, gz: bool = True) -> str:
    """The new hub's index.html (gz=True), or, for the size comparison only,
    the page sealed plain in the current shell (gz=False; never written)."""
    from .. import hub_page
    return hub_page.shell_html(bundle_json, "v2" if gz else "v1")


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
    League's History chips (4c4) and its Awards segment (4c5), from the view model."""
    import hashlib
    from .. import hub_crypto, hub_cards
    from . import page as _page, page_league
    lg = vm.get("league") or {}
    h = lg.get("history")
    htmls = {}
    if lg.get("awards") is not None:                 # 4c5: the Awards segment, one more part
        htmls["awards"] = page_league.awards_html(lg["awards"], _page._mono, _page._chart, _page.INFO)
    for chip, _lab in (h["chips"] if h else []):
        htmls[chip] = page_league.chip_html(h, chip, _page._mono)
    if not htmls:
        return {}, {}, None
    K = hub_crypto.subkey(root_key, hub_crypto.CARDS_INFO)
    files, refs, sizes = {}, {}, {}
    for key, html in htmls.items():
        k, blob = hub_crypto.seal_by_content(K, hub_cards._gz({"html": html}), terms)
        rel = f"{PART_DIR}/{hashlib.sha256(blob).hexdigest()[:16]}.enc"
        files[rel] = blob
        refs[key] = {"file": rel, "key": hub_crypto.b64(k)}
        sizes[key] = len(blob)
    return files, refs, {"parts": len(files), "bytes": sizes, "largest": max(sizes.values()) if sizes else 0}


CONTENT_DIRS = ("cards", "photos", PART_DIR)
LAZY_CAP_BYTES = 60_000                         # design/league-hub/README.md: each lazy file as served


def budget_bytes(base=None) -> int:
    """hub.first_load_budget_kb (1 KB = 1,000 bytes), the engine's config."""
    from ..data_loader import _LEAGUE_CONFIG
    return int(_LEAGUE_CONFIG["hub"]["first_load_budget_kb"]) * 1000


def build(base, payload: dict, passphrase: str, *, salt: bytes, out_dir=None, iterations: int = None,
          terms=None, now: datetime = None, gz: bool = True, cards: dict = None, live: bool = False,
          pictures=None, strict_issues: bool = None) -> dict:
    """Write the new hub's publish directory and scan it (module doc).
    out_dir: required for a scratch build; live=True writes
    output/hub_publish/ (out_dir None) or out_dir. pictures: the team
    pictures' data URIs (team_pictures.data_uris), read here when None.
    strict_issues (default: live): every issue the payload lists must be in
    the archive, as the current hub's build requires; a scratch measurement
    of a made-up payload may list issues no archive holds."""
    from .. import hub_archive, hub_crypto, hub_publish
    from . import view, page
    base = Path(base)
    if out_dir is None:
        if not live:
            raise V2PublishError("a scratch build needs out_dir (live=False)")
        out_dir = hub_publish.publish_dir(base)
    why = hub_publish.scratch_refusal(base, Path(out_dir) / "index.html") if live else refusal(base, out_dir)
    if why:
        raise V2PublishError(why)
    if ((payload.get("v2") or {}).get("ratings") or {}).get("preview"):
        raise V2PublishError("this payload carries an archetype preview (--archetype-preview): a preview is "
                             "never built in publish mode")
    out = Path(out_dir)
    gen = datetime.fromisoformat(payload["generated_at"])
    if pictures is None:
        from .. import team_pictures
        pictures, _notes = team_pictures.data_uris(base, list((payload.get("v2") or {}).get("team_order") or []))
    vm = view.build(payload, mode="publish", now=now or datetime.now(gen.tzinfo), pictures=pictures)
    idx = hub_archive.verify(base)
    by_file = {e["enc"]: e for e in idx["issues"]}
    nl = payload["newsletter"]
    for i in ([nl["current"]] if nl["current"] else []) + list(nl["archive"]):
        if i["file"] not in by_file and (live if strict_issues is None else strict_issues):
            raise V2PublishError(f"the payload lists issue {i['file']}, which the archive does not hold: "
                                 "rebuild the payload (python scripts/build_hub_state.py)")
    terms = terms if terms is not None else hub_publish.scan_terms(base)
    kw = {"salt": salt} if iterations is None else {"salt": salt, "iterations": iterations}
    inner_obj = {"page": None, "issues": {f: e["key_b64"] for f, e in by_file.items()}}
    cfiles, crep = {}, None
    root = hub_crypto.derive_key(passphrase, salt, kw.get("iterations", hub_crypto.ITERATIONS))
    try:
        lfiles, lrefs, lrep = league_files(vm, root, terms)
    except hub_crypto.SealExhausted as e:
        raise hub_publish.PlaintextLeak(str(e)) from None
    vm["league"]["parts"] = lrefs
    vm["league"]["history"] = None                # never in the page itself: only its encrypted files
    vm["league"]["awards_html"] = None            # 4c5: nor the Awards segment
    html = page.render(vm)
    inner_obj["page"] = html
    cfiles.update(lfiles)
    if cards is not None:
        try:
            files2, cref, crep = card_files(base, payload, cards, root, terms)
        except hub_crypto.SealExhausted as e:
            raise hub_publish.PlaintextLeak(str(e)) from None
        except Exception as e:                       # noqa: BLE001 -- the cards fail softly; nothing written yet
            raise hub_publish.CardFilesError(f"{type(e).__name__}: {e}") from None
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
    issue_files = {f"issues/{f}": (hub_archive.archive_dir(base) / f).read_bytes() for f in by_file}
    expected = {"index.html"} | set(issue_files) | set(cfiles)
    if out.exists():
        stray = sorted(str(q.relative_to(out)).replace("\\", "/") for q in out.rglob("*")
                       if q.is_file() and str(q.relative_to(out)).replace("\\", "/") not in expected)
        if stray:
            raise hub_publish.PublishError(f"{out} holds files the build does not write: {stray}. Nothing but "
                                           "the shell, the encrypted issues and the encrypted parts may be "
                                           "published")
    out.mkdir(parents=True, exist_ok=True)
    hub_publish._write_if_changed(out / "index.html", sh)
    for f, b in list(issue_files.items()) + list(cfiles.items()):
        hub_publish._write_if_changed(out / f, b)
    scan = hub_publish.scan_dir(out, terms)
    if scan["hits"]:
        raise hub_publish.PlaintextLeak(f"plaintext in {out}: {scan['hits']}")
    sizes = {f: (out / f).stat().st_size for f in scan["files"]}
    # the other variant's size, for the comparison (never written)
    other = len(shell(hub_crypto.bundle_json(seal(passphrase, inner, not gz, **kw)), not gz).encode("utf-8"))
    budget = budget_bytes(base)
    lazy = {f: n for f, n in sizes.items() if f != "index.html"}
    over_cap = sorted(f for f, n in lazy.items() if n > LAZY_CAP_BYTES and not f.startswith("issues/"))
    return {"dir": str(out), "files": scan["files"], "sizes": sizes, "terms": len(terms), "reseals": attempt - 1,
            "gzip": gz, "live": live, "card_files": crep, "league_parts": lrep,
            "iterations": bundle["iter"], "bundle_salt": bundle["salt"],
            "budget_bytes": budget, "over_budget": len(sh) > budget, "lazy_cap_bytes": LAZY_CAP_BYTES,
            "over_cap": over_cap,
            **measure(html, len(sh), other if gz else len(sh), inner)}


def clear_superseded(out) -> list:
    """hub_publish.clear_superseded for the new hub's content folders too
    (cards, photos, parts): an earlier build's files, each named by its own
    bytes' hash, removed before a build into a directory that persists."""
    from .. import hub_publish
    return hub_publish.clear_superseded(out, dirs=CONTENT_DIRS)


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
