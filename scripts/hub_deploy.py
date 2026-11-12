#!/usr/bin/env python3
"""
hub_deploy.py -- stage the hub for publishing: mirror output/hub_publish/ into
a checkout of the public hub repo (nickrolen/newsletter-hub), then scan
exactly what will be pushed (step 1c-ii, HANDOFF_STEP1C2 s.4 step 9).

    python scripts/hub_deploy.py --target ../hub

After it, the target's files are exactly:
    index.html           the decrypt shell (the page, encrypted)
    issues/*.enc         the encrypted issues
    cards/*.enc          the player cards (task 40): the card bundle and each
                         player's earlier seasons, encrypted
    photos/*.enc         the headshots, encrypted
    .nojekyll            GitHub Pages: serve the files as they are
and nothing else (the repo's first README included: it is removed). .git is
never touched or scanned.

THE SCAN AGAIN, ON WHAT IS PUSHED. build_hub scanned output/hub_publish/ when it
wrote it; this scans the target tree, file by file, with the same terms
(hub_publish.scan_terms: every manager, team, rostered and PLAYERLIST name,
HTML-escaped too, the lore marker and every lore id) through
hub_publish.scan_dir. Any hit refuses (exit 1) and the workflow pushes
nothing. The workflow commits and pushes only after this exits 0.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NOJEKYLL = ".nojekyll"


class DeployRefused(RuntimeError):
    pass


def _files(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and p.relative_to(root).parts[0] != ".git")


def stage(base, target, terms=None, out=print) -> dict:
    from modules import hub_publish as hp
    base, target = Path(base), Path(target)
    src = hp.publish_dir(base)
    if not (src / "index.html").is_file():
        raise DeployRefused(f"{hp.PUBLISH_RELDIR.as_posix()}/index.html is missing: the run built "
                            "no encrypted hub (is HUB_PASSPHRASE set?). Nothing to publish")
    if not (target / ".git").exists():
        raise DeployRefused(f"--target {target} is not a git checkout of the hub repo")
    want = _files(src)
    bad = [f for f in want if f != "index.html"
           and not (f.split("/")[0] in ("issues", "cards", "photos") and f.count("/") == 1
                    and f.endswith(".enc"))]
    if bad:
        raise DeployRefused(f"{hp.PUBLISH_RELDIR.as_posix()} holds files the hub never publishes: {bad}")
    terms = terms if terms is not None else hp.scan_terms(base)
    pre = hp.scan_dir(src, terms)
    if pre["hits"]:
        raise hp.PlaintextLeak(f"plaintext in {hp.PUBLISH_RELDIR.as_posix()}: {pre['hits']}")
    expected = set(want) | {NOJEKYLL}
    removed = []
    for f in _files(target):
        if f not in expected:
            (target / f).unlink()
            removed.append(f)
    changed = []
    for f in want:
        data = (src / f).read_bytes()
        t = target / f
        if not t.is_file() or t.read_bytes() != data:
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(data)
            changed.append(f)
    if not (target / NOJEKYLL).is_file() or (target / NOJEKYLL).read_bytes() != b"":
        (target / NOJEKYLL).write_bytes(b"")
        changed.append(NOJEKYLL)
    for d in sorted((p for p in target.rglob("*") if p.is_dir() and ".git" not in p.relative_to(target).parts),
                    key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()
    got = _files(target)
    if set(got) != expected:
        raise DeployRefused(f"the staged tree is not exactly the publish set: {sorted(set(got) ^ expected)}")
    scan = hp.scan_dir(target, terms, skip=(".git",))
    if scan["hits"]:
        raise hp.PlaintextLeak(f"plaintext in what would be pushed: {scan['hits']}")
    if sorted(scan["files"]) != got:
        raise DeployRefused("the scan did not cover every file to be pushed")
    out(f"staged {len(got)} file(s) in {target}: {len(changed)} changed, {len(removed)} removed; "
        f"plaintext scan of exactly these files: {len(terms)} terms, no hits")
    return {"files": got, "changed": changed, "removed": removed, "terms": len(terms)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mirror the hub's publish directory into the hub "
                                             "repo checkout and scan what will be pushed.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--base-path", default=".")
    a = ap.parse_args(argv)
    from modules import hub_publish as hp
    try:
        stage(a.base_path, a.target)
    except (DeployRefused, hp.PlaintextLeak, hp.PublishError) as e:
        print(f"REFUSED (hub deploy): {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
