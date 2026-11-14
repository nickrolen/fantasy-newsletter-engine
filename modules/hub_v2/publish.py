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

The card and headshot files are not built here (they are the current
build's, unchanged by 4b); the measurement is index.html, the first load.
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


def build(base, payload: dict, passphrase: str, *, salt: bytes, out_dir, iterations: int = None,
          terms=None, now: datetime = None, gz: bool = True) -> dict:
    from .. import hub_archive, hub_crypto, hub_publish
    from . import view, page
    why = refusal(base, out_dir)
    if why:
        raise V2PublishError(why)
    base = Path(base)
    out = Path(out_dir)
    gen = datetime.fromisoformat(payload["generated_at"])
    html = page.render(view.build(payload, mode="publish", now=now or datetime.now(gen.tzinfo)))
    idx = hub_archive.verify(base)
    by_file = {e["enc"]: e for e in idx["issues"]}
    inner = json.dumps({"page": html, "issues": {f: e["key_b64"] for f, e in by_file.items()}},
                       separators=(",", ":")).encode("utf-8")
    terms = terms if terms is not None else hub_publish.scan_terms(base)
    kw = {"salt": salt} if iterations is None else {"salt": salt, "iterations": iterations}
    for attempt in range(1, hub_publish.MAX_RESEAL + 1):
        bundle = seal(passphrase, inner, gz, **kw)
        sh = shell(hub_crypto.bundle_json(bundle), gz).encode("utf-8")
        if not hub_publish.hits(sh, terms):
            break
    else:
        raise hub_publish.PlaintextLeak("the v2 shell matched a scan term after every re-encryption")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_bytes(sh)
    scan = hub_publish.scan_dir(out, terms)
    if scan["hits"]:
        raise hub_publish.PlaintextLeak(f"plaintext in {out}: {scan['hits']}")
    # the other variant's size, for the comparison (never written)
    other = len(shell(hub_crypto.bundle_json(seal(passphrase, inner, not gz, **kw)), not gz).encode("utf-8"))
    return {"dir": str(out), "files": scan["files"], "terms": len(terms), "reseals": attempt - 1, "gzip": gz,
            **measure(html, len(sh), other if gz else len(sh), inner)}


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
