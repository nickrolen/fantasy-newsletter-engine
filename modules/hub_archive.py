"""
hub_archive.py -- the newsletter archive the hub publishes (Step 1b; design
s.3, invariant 6).

Each published issue is archived ONCE, by content hash, and never rewritten:

    output/hub_archive/                       (private state, the manifest)
      index.json                              one entry per week
      weekNN-<sha12>.html                     the issue's plaintext bytes
      weekNN-<sha12>.enc                      the same, encrypted once (iv||ct)
                                              with the entry's own random key

  - archive_issue(week) reads output/WEEK{N}_NEWSLETTER.html (the file Step 9
    writes and Nick sends). The same bytes again: a no-op. Different bytes
    for an archived week: ArchiveConflict -- a published issue is never
    replaced.
  - verify() checks every entry on every hub build: the plaintext file hashes
    to the entry's sha256, the encrypted file to its enc_sha256 and decrypts
    to the plaintext, and the published file in output/, while it exists, is
    still byte-identical to what was archived (IssueChanged otherwise).
  - The issue keys live in index.json (private state, beside the plaintext
    they protect) and are published only inside the encrypted page bundle.

Archiving is explicit (python scripts/archive_issue.py --week N): a draft on
disk is never archived by a hub build.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

ARCHIVE_RELDIR = Path("output") / "hub_archive"
INDEX = "index.json"
INDEX_VERSION = 1


class ArchiveError(RuntimeError):
    pass


class ArchiveConflict(ArchiveError):
    """An archived week offered different bytes."""


class IssueChanged(ArchiveError):
    """The published issue on disk no longer matches what was archived."""


def archive_dir(base_path=".") -> Path:
    return Path(base_path) / ARCHIVE_RELDIR


def issue_source(base_path, week: int) -> Path:
    return Path(base_path) / "output" / f"WEEK{int(week)}_NEWSLETTER.html"


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def size_text(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 100_000 else f"{max(1, round(n / 1000))} KB"


def load_index(base_path=".") -> dict:
    """The index; an empty one when the archive has never been seeded."""
    d = archive_dir(base_path)
    p = d / INDEX
    if not p.is_file():
        if d.exists() and any(d.iterdir()):
            raise ArchiveError(f"{ARCHIVE_RELDIR} has files and no {INDEX}")
        return {"version": INDEX_VERSION, "issues": []}
    idx = json.loads(p.read_text(encoding="utf-8"))
    if idx.get("version") != INDEX_VERSION or not isinstance(idx.get("issues"), list):
        raise ArchiveError(f"{ARCHIVE_RELDIR / INDEX} is not a version-{INDEX_VERSION} index")
    weeks = [int(i["week"]) for i in idx["issues"]]
    if len(weeks) != len(set(weeks)):
        raise ArchiveError(f"{ARCHIVE_RELDIR / INDEX} lists a week twice")
    return idx


def _write_index(base_path, idx: dict) -> None:
    from .data_loader import atomic_write_json
    atomic_write_json(archive_dir(base_path) / INDEX, idx, indent=1)


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ArchiveConflict(f"{path.name} exists with different bytes: never rewritten")
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def archive_issue(base_path, week: int, source: Optional[Path] = None, now: datetime = None,
                  avoid=None) -> dict:
    """Archive week N's published issue once. Returns {"week", "wrote", ...}.

    avoid: the plaintext scan's terms (hub_publish.scan_terms). The encrypted
    copy is written once and published for good, so it is re-sealed with a
    fresh key until no term turns up in its random bytes by chance; the scan
    of the publish directory then stays clean for this file forever."""
    from . import hub_crypto
    if avoid is None:
        raise ArchiveError("archive_issue needs the scan terms (hub_publish.scan_terms): an "
                           "issue's ciphertext is published for good")
    base = Path(base_path)
    src = Path(source) if source else issue_source(base, week)
    if not src.is_file():
        raise ArchiveError(f"{src} is missing: archive the issue that was published")
    data = src.read_bytes()
    digest = sha256(data)
    idx = load_index(base)
    for e in idx["issues"]:
        if int(e["week"]) == int(week):
            if e["sha256"] == digest:
                return {"week": int(week), "wrote": False, "why": "already archived, identical",
                        "entry": e}
            raise ArchiveConflict(
                f"week {week} was archived {e['archived_at']} as {e['sha256'][:12]}, and "
                f"{src.name} is now {digest[:12]}: a published issue is never rewritten. If the "
                "first one was wrong, that is Nick's call, made by hand")
    d = archive_dir(base)
    d.mkdir(parents=True, exist_ok=True)
    stem = f"week{int(week):02d}-{digest[:12]}"
    for _ in range(20):
        key = hub_crypto.new_key()
        sealed = hub_crypto.seal(key, data)
        if not any(t.encode("utf-8") in sealed for t in avoid):
            break
    else:
        raise ArchiveError(f"week {week}'s encrypted copy matched a scan term 20 times running")
    _write_once(d / f"{stem}.html", data)
    _write_once(d / f"{stem}.enc", sealed)
    if now is None:
        from .league_clock import league_now
        now = league_now()
    entry = {"week": int(week), "source": src.name, "sha256": digest, "bytes": len(data),
             "plain": f"{stem}.html", "enc": f"{stem}.enc", "enc_sha256": sha256(sealed),
             "enc_bytes": len(sealed), "enc_size_text": size_text(len(sealed)),
             "key_b64": hub_crypto.b64(key), "archived_at": now.isoformat(timespec="seconds")}
    idx["issues"] = sorted(idx["issues"] + [entry], key=lambda e: int(e["week"]))
    _write_index(base, idx)
    return {"week": int(week), "wrote": True, "why": None, "entry": entry}


def verify(base_path=".") -> dict:
    """Every entry intact; every published issue still what was archived."""
    from . import hub_crypto
    base = Path(base_path)
    idx = load_index(base)
    d = archive_dir(base)
    for e in idx["issues"]:
        plain = (d / e["plain"]).read_bytes() if (d / e["plain"]).is_file() else None
        if plain is None or sha256(plain) != e["sha256"]:
            raise ArchiveError(f"{ARCHIVE_RELDIR / e['plain']} is missing or changed")
        sealed = (d / e["enc"]).read_bytes() if (d / e["enc"]).is_file() else None
        if sealed is None or sha256(sealed) != e["enc_sha256"]:
            raise ArchiveError(f"{ARCHIVE_RELDIR / e['enc']} is missing or changed")
        if hub_crypto.open_sealed(hub_crypto.unb64(e["key_b64"]), sealed) != plain:
            raise ArchiveError(f"{e['enc']} does not decrypt to week {e['week']}'s issue")
        src = base / "output" / e["source"]
        if src.is_file() and sha256(src.read_bytes()) != e["sha256"]:
            raise IssueChanged(f"output/{e['source']} changed after week {e['week']} was archived "
                               f"({e['sha256'][:12]} -> {sha256(src.read_bytes())[:12]}): a "
                               "published issue is never rewritten")
    return idx
