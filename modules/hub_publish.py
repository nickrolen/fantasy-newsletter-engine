"""
hub_publish.py -- the hub's publish directory and the plaintext scan
(Step 1b; design s.3, invariant 4).

    output/hub_publish/                 (ignored; excluded from the manifest:
      index.html                         regenerable)
      issues/weekNN-<sha12>.enc         copied byte for byte from the archive

index.html is the decrypt shell (hub_page.shell_html) carrying the page
bundle: {"page": the rendered hub, "issues": {file: its key}}, encrypted with
the passphrase's key (hub_crypto). Nothing else may be in the directory.

THE SCAN (scan_dir): every file in the directory, as bytes, for every manager
name, team name, rostered player name (config/ROSTERS.json) and PLAYERLIST
name, each also HTML-escaped, the lore marker "<!-- lore:" and every lore id
in output/lore_for_drafting.json. Exact, case-sensitive substrings. Any hit
fails the build.

Ciphertext is random, and a short name ("Nick") can turn up in random bytes
by chance (about once in a hundred builds for the base64 page bundle). That
is not a leak, but the scan cannot tell, so the bundle is re-encrypted with a
fresh salt and IV until it is clean, before anything is written, and
archive_issue does the same for an issue at archive time. The scan itself is
never relaxed.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Iterable, List, Set

PUBLISH_RELDIR = Path("output") / "hub_publish"
LORE_MARKER = "<!-- lore:"
MAX_RESEAL = 20


class PlaintextLeak(RuntimeError):
    pass


class PublishError(RuntimeError):
    pass


def publish_dir(base_path=".") -> Path:
    return Path(base_path) / PUBLISH_RELDIR


def scan_terms(base_path=".", data=None) -> List[str]:
    """Every string that must never appear in a published file."""
    base = Path(base_path)
    from .data_loader import MANAGERS, MANAGER_TO_TEAM
    terms: Set[str] = set(MANAGERS) | set(MANAGER_TO_TEAM.values())
    rp = base / "config" / "ROSTERS.json"
    if not rp.is_file():
        raise PublishError("config/ROSTERS.json is missing: the plaintext scan needs every rostered name")
    for names in (json.loads(rp.read_text(encoding="utf-8")).get("rosters") or {}).values():
        terms.update(names)
    import pandas as pd
    pl = base / "data" / "PLAYERLIST.xlsx"
    if not pl.is_file():
        raise PublishError("data/PLAYERLIST.xlsx is missing: the plaintext scan reads its names")
    terms.update(str(n) for n in pd.read_excel(pl)["player_name"].dropna())
    terms.add(LORE_MARKER)
    lp = base / "output" / "lore_for_drafting.json"
    if not lp.is_file():
        raise PublishError("output/lore_for_drafting.json is missing: the scan checks every lore id")
    for e in json.loads(lp.read_text(encoding="utf-8")).get("entries", []):
        if e.get("id"):
            terms.add(str(e["id"]))
    out = set()
    for t in terms:
        t = str(t).strip()
        if len(t) >= 3:
            out.add(t)
            out.add(html.escape(t))
    return sorted(out)


def hits(data: bytes, terms: Iterable[str]) -> List[str]:
    return [t for t in terms if t.encode("utf-8") in data]


def scan_dir(path: Path, terms: Iterable[str]) -> dict:
    """{relative file: [terms found]} for every file under `path`."""
    terms = list(terms)
    found = {}
    files = sorted(p for p in Path(path).rglob("*") if p.is_file())
    for f in files:
        h = hits(f.read_bytes(), terms)
        if h:
            found[str(f.relative_to(path)).replace("\\", "/")] = h
    return {"files": [str(f.relative_to(path)).replace("\\", "/") for f in files], "hits": found}


def _write_if_changed(path: Path, data: bytes) -> None:
    if path.is_file() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def build(base_path, payload: dict, passphrase: str, *, terms: List[str] = None,
          iterations: int = None, now=None) -> dict:
    """Write the publish directory and scan it. Returns a report; raises
    PlaintextLeak on any hit, PublishError on a stray file."""
    from . import hub_archive, hub_page, hub_crypto
    base = Path(base_path)
    idx = hub_archive.verify(base)
    by_file = {e["enc"]: e for e in idx["issues"]}
    nl = payload["newsletter"]
    for i in ([nl["current"]] if nl["current"] else []) + list(nl["archive"]):
        if i["file"] not in by_file:
            raise PublishError(f"the payload lists issue {i['file']}, which the archive does not hold: "
                               "rebuild the payload (python scripts/build_hub_state.py)")
    terms = terms if terms is not None else scan_terms(base)
    page = hub_page.render(payload, now=now, mode="publish")
    inner = json.dumps({"page": page, "issues": {f: e["key_b64"] for f, e in by_file.items()}},
                       separators=(",", ":")).encode("utf-8")
    kw = {} if iterations is None else {"iterations": iterations}
    for attempt in range(1, MAX_RESEAL + 1):
        bundle = hub_crypto.make_bundle(passphrase, inner, **kw)
        shell = hub_page.shell_html(hub_crypto.bundle_json(bundle)).encode("utf-8")
        if not hits(shell, terms):
            break
    else:
        raise PlaintextLeak(f"the decrypt shell still matched a scan term after {MAX_RESEAL} fresh "
                            "encryptions: that is not chance; the shell itself carries plaintext")
    out = publish_dir(base)
    expected = {"index.html"} | {f"issues/{f}" for f in by_file}
    if out.exists():
        stray = sorted(str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*")
                       if p.is_file() and str(p.relative_to(out)).replace("\\", "/") not in expected)
        if stray:
            raise PublishError(f"{PUBLISH_RELDIR} holds files the build does not write: {stray}. "
                               "Nothing but the shell and the encrypted issues may be published")
    _write_if_changed(out / "index.html", shell)
    for f, e in by_file.items():
        _write_if_changed(out / "issues" / f, (hub_archive.archive_dir(base) / f).read_bytes())
    scan = scan_dir(out, terms)
    if scan["hits"]:
        raise PlaintextLeak(f"plaintext in {PUBLISH_RELDIR}: {scan['hits']}")
    sizes = {f: (out / f).stat().st_size for f in scan["files"]}
    return {"dir": str(PUBLISH_RELDIR), "files": scan["files"], "sizes": sizes,
            "reseals": attempt - 1, "terms": len(terms), "bundle_salt": bundle["salt"],
            "iterations": bundle["iter"]}
