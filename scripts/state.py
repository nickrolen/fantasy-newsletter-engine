#!/usr/bin/env python3
"""
state.py -- move the league's state between this folder and the private repo.

THE SPLIT (claude/SELF_RUNNING_DESIGN.md s.2, P2 2026-10-31). The private repo
(config/STATE_MANIFEST.json: private_repo, nickrolen/newsletter-state) is the
single source of truth for the league's mutable state. Its clone lives at
.state/ INSIDE this folder (gitignored): the league's data never leaves the
repo folder. The engine keeps reading its files from today's paths; this
script copies exactly the manifest's paths (modules/state_manifest.py) between
the working tree and .state/, in both directions, and touches nothing else.

    python scripts/state.py status   what differs, file by file
    python scripts/state.py pull     before a manual run: private repo -> here
    python scripts/state.py push     after it: here -> private repo, commit, push
    python scripts/state.py init     once: the first push into an EMPTY clone
    python scripts/state.py set-engine         point the cloud run at this engine's HEAD
    python scripts/state.py install-workflows  copy deploy/state-repo/.github/ into the private repo

THE SYNC RECORD (.state_sync.json, gitignored, per machine) holds the private
repo's commit and every state file's SHA-256 at the last pull, push or init.
That is how the two refusals that matter work:
  - pull refuses while a state file here changed since the last sync (edits
    not yet pushed would be overwritten);
  - push refuses when the private repo moved since the last sync (someone
    else -- the nightly run -- pushed; pull first).
A manual run never silently races the nightly one (design s.2.3).

THE THREE-WAY PULL (step 1c-ii, HANDOFF_STEP1C2 s.5). Once the cloud commits
state every night, Nick can pull in the morning, change state by hand, and
find at push time that the private repo moved (the pre-tip run). pull then
compares, file by file, against the sync record: the files changed here, and
the files changed in the private repo since the last sync (git diff of the
recorded commit and the remote's). When the two sets do not overlap -- or
overlap only where both sides hold the same bytes -- pull takes the private
repo's changes and keeps the local ones, which the next push sends. A real
overlap refuses, naming the files, and changes nothing here or in .state/.

Every refusal names the file(s) and what to do, and exits 1. Standard library
plus `git` on PATH. Nothing here reads a file's contents except to hash and
copy it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import state_manifest as sm   # noqa: E402

CLONE_DIR = ".state"
SYNC_FILE = ".state_sync.json"
README = ("# newsletter-state\n\n"
          "State for the newsletter engine (nickrolen/fantasy-newsletter-engine): the league's\n"
          "logs, rosters, overrides, rulings, lore and issues. Private. The engine's\n"
          "claude/SELF_RUNNING_DESIGN.md s.2 explains the split; its config/STATE_MANIFEST.json\n"
          "lists what lives here, and its scripts/state.py moves it (pull before a run, push\n"
          "after). ENGINE_COMMIT is the engine commit this state was last run with.\n")
# No line-ending or other conversion of state files, ever: a pull and a push
# must round-trip byte for byte on any machine (Windows autocrlf included).
GITATTRIBUTES = "* -text\n"


class Refusal(RuntimeError):
    """A refusal: printed with what to do, exit 1."""


# ============================================================================ helpers

def git(*args, cwd, check=True, capture=True) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=capture, text=True)
    except FileNotFoundError:
        raise Refusal("git is not on PATH -- install Git for Windows, then rerun") from None
    if check and r.returncode != 0:
        raise Refusal(f"git {' '.join(args)} failed in {cwd}:\n{(r.stderr or r.stdout).strip()}")
    return (r.stdout or "").strip()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hashes(root: Path, man) -> dict:
    return {rel: sha(root / rel) for rel in man.present(root)}


def league_time() -> str:
    from modules.league_clock import league_now
    return league_now().strftime("%Y-%m-%d %H:%M %Z")


def load_record(root: Path):
    p = root / SYNC_FILE
    if not p.is_file():
        return None
    blob = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(blob.get("files"), dict) or not blob.get("commit"):
        raise Refusal(f"{SYNC_FILE} is malformed. Do not edit it by hand; if it is lost, "
                      "the safe way back is: push nothing, re-clone .state, and ask before "
                      "overwriting either side")
    return blob


def save_record(root: Path, commit: str, files: dict, action: str) -> None:
    blob = {"_comment": "state.py's sync record (per machine, gitignored). Do not edit.",
            "commit": commit, "action": action, "at": league_time(),
            "machine": platform.node(), "files": dict(sorted(files.items()))}
    (root / SYNC_FILE).write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")


def clone_checks(root: Path, man, want_commits: bool = True) -> Path:
    """.state/ exists and is a clone of the private repo. Returns its path."""
    clone = root / CLONE_DIR
    url = f"https://github.com/{man.private_repo}.git"
    how = f"clone it: git clone {url} {CLONE_DIR}"
    if not clone.is_dir():
        raise Refusal(f"{CLONE_DIR}\\ is missing -- {how}")
    if not (clone / ".git").exists():
        raise Refusal(f"{CLONE_DIR}\\ is not a git clone -- move it aside and {how}")
    origin = git("remote", "get-url", "origin", cwd=clone, check=False).replace("\\", "/")
    if not re.search(rf"[/:]{re.escape(man.private_repo)}(\.git)?/?$", origin):
        raise Refusal(f"{CLONE_DIR}\\ is a clone of {origin or 'nothing'}, not {man.private_repo} "
                      f"-- move it aside and {how}")
    return clone


def head(clone: Path):
    out = git("rev-parse", "--verify", "-q", "HEAD", cwd=clone, check=False)
    return out or None


def branch(clone: Path) -> str:
    return git("symbolic-ref", "--short", "HEAD", cwd=clone)


def remote_head(clone: Path):
    br = branch(clone)
    git("fetch", "-q", "origin", cwd=clone)
    out = git("rev-parse", "--verify", "-q", f"origin/{br}", cwd=clone, check=False)
    return out or None


def dirty(clone: Path) -> list:
    return [ln for ln in git("status", "--porcelain", cwd=clone).splitlines() if ln.strip()]


def copy_state(src: Path, dst: Path, man) -> tuple:
    """Make dst's state paths equal src's: copy what differs, delete state
    paths dst has and src lacks. Only manifest paths, in both trees.
    Returns (copied, deleted)."""
    s, d = hashes(src, man), hashes(dst, man)
    copied, deleted = [], []
    for rel, h in s.items():
        if d.get(rel) != h:
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, target)
            copied.append(rel)
    for rel in sorted(set(d) - set(s)):
        assert man.contains(rel), rel          # never anything outside the manifest
        (dst / rel).unlink()
        deleted.append(rel)
        parent = (dst / rel).parent
        while parent != dst and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return copied, deleted


def blob_sha(clone: Path, ref: str, rel: str):
    """SHA-256 of `rel`'s bytes at `ref` in the clone, or None if absent there.
    The private repo sets `* -text`, so the blob is the file's bytes."""
    r = subprocess.run(["git", "cat-file", "blob", f"{ref}:{rel}"], cwd=str(clone),
                       capture_output=True)
    if r.returncode != 0:
        return None
    return hashlib.sha256(r.stdout).hexdigest()


def changed_between(clone: Path, man, old: str, new: str) -> list:
    """State paths that differ between two commits of the private repo."""
    if old == new:
        return []
    out = git("diff", "--name-only", "--no-renames", old, new, cwd=clone)
    return sorted(p for p in out.splitlines() if p.strip() and man.contains(p))


def diff(a: dict, b: dict) -> list:
    """Paths whose hash differs between two {path: hash} maps (either side missing too)."""
    return sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))


def _list(paths, limit=40) -> str:
    shown = "\n".join(f"    {p}" for p in paths[:limit])
    more = f"\n    ... and {len(paths) - limit} more" if len(paths) > limit else ""
    return shown + more


# ============================================================================ commands

def cmd_status(root: Path, man, out=print) -> int:
    clone = clone_checks(root, man)
    rec = load_record(root)
    local, private = hashes(root, man), hashes(clone, man)
    base = (rec or {}).get("files", {})
    rows = []
    for p in sorted(set(local) | set(private) | set(base)):
        l, r, b = local.get(p), private.get(p), base.get(p)
        if l == r and l is not None:
            what = "in sync"
        elif l is None and r is None:
            what = "deleted on both sides since the last sync"
        elif l is None:
            what = "missing here" + (" (deleted here)" if b is not None and r == b else "")
        elif r is None:
            what = "missing in the private repo" + (" (new here)" if b is None else "")
        elif r == b:
            what = "changed here"
        elif l == b:
            what = "changed in the private repo"
        else:
            what = "changed on BOTH sides"
        rows.append((what, p))
    for what, p in rows:
        if what != "in sync":
            out(f"  {what:44} {p}")
    n_sync = sum(1 for w, _ in rows if w == "in sync")
    out(f"{n_sync} of {len(rows)} state file(s) in sync"
        + ("" if rec else f"; no sync record yet ({SYNC_FILE}) -- run init or pull"))
    try:
        rh = remote_head(clone)
        if rh and rh != head(clone):
            out(f"the private repo has commits {CLONE_DIR}\\ does not: pull to take them")
    except Refusal as e:
        out(f"(could not fetch the private repo: {e})")
    return 0


def cmd_pull(root: Path, man, out=print) -> int:
    clone = clone_checks(root, man)
    if head(clone) is None:
        raise Refusal(f"the private repo is empty -- run `python scripts/state.py init` first")
    if dirty(clone):
        raise Refusal(f"{CLONE_DIR}\\ has uncommitted changes of its own:\n"
                      + _list(dirty(clone)) + "\nnothing here makes those; ask before discarding")
    rec = load_record(root)
    local = hashes(root, man)
    if rec is None:
        if local:
            raise Refusal(f"there is no sync record ({SYNC_FILE}) but {len(local)} state file(s) "
                          "are here; a pull would overwrite them unseen. If the private repo is "
                          "new, run `python scripts/state.py init`; otherwise ask before going on")
        changed = []
    else:
        if head(clone) != rec["commit"]:
            raise Refusal(f"{CLONE_DIR}\\ is at {str(head(clone))[:12]}, but the last sync was "
                          f"{rec['commit'][:12]}: a command that never finished, or a commit made "
                          "by hand. Look at `git -C .state log` and ask before going on")
        changed = diff(local, rec["files"])
    if not changed:
        git("pull", "-q", "--ff-only", cwd=clone)
        copied, deleted = copy_state(clone, root, man)
        save_record(root, head(clone), hashes(root, man), "pull")
        out(f"pulled {head(clone)[:12]}: {len(copied)} file(s) updated, {len(deleted)} removed")
        for p in copied:
            out(f"  updated  {p}")
        for p in deleted:
            out(f"  removed  {p}")
        return 0
    # Local changes not yet pushed: the three-way check, file by file.
    remote = remote_head(clone)
    if remote is None:
        raise Refusal("the private repo has no branch to pull")
    theirs = changed_between(clone, man, rec["commit"], remote)
    both = sorted(set(changed) & set(theirs))
    clash = [p for p in both if local.get(p) != blob_sha(clone, remote, p)]
    if clash:
        raise Refusal("the same state file(s) changed here AND in the private repo since the last "
                      "sync:\n" + _list(clash)
                      + "\nnothing was changed, here or in .state\\. Ask before going on: one "
                        "side's version of each has to be chosen by hand")
    git("pull", "-q", "--ff-only", cwd=clone)
    if head(clone) != remote:
        raise Refusal(f"{CLONE_DIR}\\ did not fast-forward to {remote[:12]}: ask before going on")
    took, removed = [], []
    for rel in theirs:
        assert man.contains(rel), rel          # never anything outside the manifest
        if rel in both:
            continue                           # the same bytes on both sides already
        src, dst = clone / rel, root / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            took.append(rel)
        elif dst.is_file():
            dst.unlink()
            removed.append(rel)
    save_record(root, head(clone), hashes(clone, man), "pull (kept local changes)")
    kept = sorted(set(changed) - set(both))
    out(f"pulled {head(clone)[:12]}: {len(took)} file(s) updated, {len(removed)} removed from the "
        f"private repo; {len(kept)} local change(s) kept, not yet pushed -- push them next")
    for p in took:
        out(f"  updated  {p}")
    for p in removed:
        out(f"  removed  {p}")
    for p in kept:
        out(f"  kept     {p}  (changed here)")
    return 0


def _commit_and_push(clone: Path, changed: list, action: str) -> str:
    git("add", "-A", cwd=clone)
    lines = "\n".join(f"- {p}" for p in changed[:200])
    more = f"\n- ... and {len(changed) - 200} more" if len(changed) > 200 else ""
    msg = (f"{action}: {len(changed)} state file(s) from {platform.node()} at {league_time()}\n\n"
           f"{lines}{more}\n")
    git("commit", "-q", "-m", msg, cwd=clone)
    git("push", "-q", "-u", "origin", branch(clone), cwd=clone)
    return head(clone)


def cmd_push(root: Path, man, out=print) -> int:
    clone = clone_checks(root, man)
    rec = load_record(root)
    if rec is None:
        raise Refusal(f"there is no sync record ({SYNC_FILE}): run `python scripts/state.py "
                      "init` for a new private repo, or `pull` first")
    if dirty(clone):
        raise Refusal(f"{CLONE_DIR}\\ has uncommitted changes of its own:\n" + _list(dirty(clone))
                      + "\nnothing here makes those; ask before discarding")
    here = head(clone)
    if here != rec["commit"]:
        raise Refusal(f"{CLONE_DIR}\\ is at {str(here)[:12]}, but the last sync was "
                      f"{rec['commit'][:12]}: a push that never finished, or a commit made by "
                      "hand. Look at `git -C .state log` and ask before going on")
    remote = remote_head(clone)
    if remote != rec["commit"]:
        raise Refusal(f"the private repo moved since the last sync ({rec['commit'][:12]} -> "
                      f"{str(remote)[:12]}): pull first (`python scripts/state.py pull`)")
    local, private = hashes(root, man), hashes(clone, man)
    changed = diff(local, private)
    if not changed:
        out("nothing changed: the private repo already has this state")
        return 0
    copy_state(root, clone, man)
    commit = _commit_and_push(clone, changed, "push")
    save_record(root, commit, hashes(root, man), "push")
    out(f"pushed {commit[:12]}: {len(changed)} file(s)")
    for p in changed:
        out(f"  {p}")
    return 0


def cmd_init(root: Path, man, out=print) -> int:
    clone = clone_checks(root, man)
    others = sorted(p.name for p in clone.iterdir() if p.name != ".git")
    if head(clone) is not None or others:
        raise Refusal(f"{CLONE_DIR}\\ is not an empty clone ("
                      + (f"commit {head(clone)[:12]}" if head(clone) else f"holds {others}")
                      + "): init only seeds a new, empty private repo. Use pull/push")
    if (root / SYNC_FILE).exists():
        raise Refusal(f"{SYNC_FILE} already exists: this folder has synced before. Ask before "
                      "seeding a new private repo from it")
    local = hashes(root, man)
    if not local:
        raise Refusal("there is no state here to seed the private repo with")
    copy_state(root, clone, man)
    (clone / "ENGINE_COMMIT").write_text(git("rev-parse", "HEAD", cwd=root) + "\n",
                                         encoding="utf-8")
    (clone / "README.md").write_text(README, encoding="utf-8")
    (clone / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")
    commit = _commit_and_push(clone, sorted(local), "init")
    save_record(root, commit, hashes(root, man), "init")
    out(f"seeded the private repo at {commit[:12]} with {len(local)} state file(s); "
        f"ENGINE_COMMIT {git('rev-parse', 'HEAD', cwd=root)[:12]}")
    return 0


ENGINE_BRANCH = "main"
WORKFLOWS_SRC = Path("deploy") / "state-repo" / ".github"


def _synced_clone(root: Path, man):
    """The checks every command that commits to the private repo shares with
    push: a record, a clean clone at the recorded commit, a remote that has
    not moved."""
    clone = clone_checks(root, man)
    rec = load_record(root)
    if rec is None:
        raise Refusal(f"there is no sync record ({SYNC_FILE}): pull first")
    if dirty(clone):
        raise Refusal(f"{CLONE_DIR}\\ has uncommitted changes of its own:\n" + _list(dirty(clone))
                      + "\nnothing here makes those; ask before discarding")
    if head(clone) != rec["commit"]:
        raise Refusal(f"{CLONE_DIR}\\ is at {str(head(clone))[:12]}, but the last sync was "
                      f"{rec['commit'][:12]}: look at `git -C .state log` and ask before going on")
    remote = remote_head(clone)
    if remote != rec["commit"]:
        raise Refusal(f"the private repo moved since the last sync ({rec['commit'][:12]} -> "
                      f"{str(remote)[:12]}): pull first (`python scripts/state.py pull`)")
    return clone, rec


def _commit_only(clone: Path, msg: str) -> str:
    git("add", "-A", cwd=clone)
    git("commit", "-q", "-m", msg, cwd=clone)
    git("push", "-q", "-u", "origin", branch(clone), cwd=clone)
    return head(clone)


def cmd_set_engine(root: Path, man, out=print) -> int:
    """Write this engine's HEAD into the private repo's ENGINE_COMMIT, commit,
    push. The cloud run checks the engine out at that commit and refuses any
    other (design invariant 3)."""
    tracked = [ln for ln in git("status", "--porcelain", "--untracked-files=no", cwd=root).splitlines()
               if ln.strip()]
    if tracked:
        raise Refusal("the engine has uncommitted changes:\n" + _list(tracked)
                      + "\ncommit (and push) them first: the cloud runs only committed code")
    git("fetch", "-q", "origin", ENGINE_BRANCH, cwd=root)
    eng = git("rev-parse", "HEAD", cwd=root)
    on = subprocess.run(["git", "merge-base", "--is-ancestor", eng, f"origin/{ENGINE_BRANCH}"],
                        cwd=str(root), capture_output=True)
    if on.returncode != 0:
        raise Refusal(f"the engine's HEAD {eng[:12]} is not on origin/{ENGINE_BRANCH}: push it "
                      "first (the cloud can only check out a pushed commit)")
    clone, rec = _synced_clone(root, man)
    pin = clone / "ENGINE_COMMIT"
    old = pin.read_text(encoding="utf-8").strip() if pin.is_file() else ""
    if old == eng:
        out(f"ENGINE_COMMIT is already {eng[:12]}: nothing changed")
        return 0
    pin.write_text(eng + "\n", encoding="utf-8")
    commit = _commit_only(clone, f"set-engine: ENGINE_COMMIT {old[:12] or '(none)'} -> {eng[:12]}\n\n"
                                 f"from {platform.node()} at {league_time()}\n")
    save_record(root, commit, rec["files"], "set-engine")
    out(f"ENGINE_COMMIT {old[:12] or '(none)'} -> {eng[:12]}; pushed {commit[:12]}")
    return 0


def _tree(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p for p in d.rglob("*") if p.is_file()} if d.is_dir() else {}


def cmd_install_workflows(root: Path, man, out=print) -> int:
    """Make the private repo's .github/ exactly deploy/state-repo/.github/,
    commit, push, and move the sync record along so the next push works."""
    src = root / WORKFLOWS_SRC
    if not (src / "workflows").is_dir():
        raise Refusal(f"{WORKFLOWS_SRC.as_posix()}/workflows is missing in the engine")
    clone, rec = _synced_clone(root, man)
    dst = clone / ".github"
    have, want = _tree(dst), _tree(src)
    changed = []
    for rel, p in want.items():
        if rel not in have or have[rel].read_bytes() != p.read_bytes():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dst / rel)
            changed.append(rel)
    for rel in sorted(set(have) - set(want)):
        (dst / rel).unlink()
        changed.append(rel)
    if not changed:
        out("the private repo's workflows already match: nothing changed")
        return 0
    commit = _commit_only(clone, f"install-workflows: {len(changed)} file(s) from the engine at "
                                 f"{git('rev-parse', '--short', 'HEAD', cwd=root)}\n\n"
                                 + "\n".join(f"- .github/{p}" for p in changed) + "\n")
    save_record(root, commit, rec["files"], "install-workflows")
    out(f"installed {len(changed)} workflow file(s); pushed {commit[:12]}")
    for p in changed:
        out(f"  .github/{p}")
    return 0


COMMANDS = {"status": cmd_status, "pull": cmd_pull, "push": cmd_push, "init": cmd_init,
            "set-engine": cmd_set_engine, "install-workflows": cmd_install_workflows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)  # tests only
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        man = sm.load(root)
        return COMMANDS[args.command](root, man)
    except (Refusal, sm.ManifestError) as e:
        print(f"REFUSED ({args.command}): {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
