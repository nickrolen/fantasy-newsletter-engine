"""
state_manifest.py -- which files are the league's state.

THE SPLIT (claude/SELF_RUNNING_DESIGN.md s.2, P2 2026-10-31). The public repo
nickrolen/fantasy-newsletter-engine holds the engine: code, tests, docs,
static history. The private repo nickrolen/newsletter-state holds the league's
mutable state: logs, rosters, overrides, rulings, the lore, the issues. The
engine keeps reading its files from today's paths; scripts/state.py moves them
between the working tree and the private clone (.state/ in the repo folder).

config/STATE_MANIFEST.json is the one list of what is state, and this module
the one reader of it. Every manifest path is ignored by the public .gitignore
and tracked by nothing (tests/test_state_manifest.py), so state cannot be
published from the public repo by a stray `git add`.

ENTRY KINDS
    files      exact paths.
    dirs       a directory and everything below it, minus "except" (paths
               relative to that directory, exact, no wildcards).
    patterns   file names matched with fnmatch in ONE directory, not below
               it, minus "except" (exact names). A pattern may not contain a
               "/", so it cannot reach outside the directory it names.

    excluded           paths the engine touches that are deliberately NOT
                       state (credentials, caches, the dry-run packets), each
                       with its reason. Never copied.
    public_exceptions  tracked files inside a manifest dir or pattern that
                       stay public on purpose (Nick, 10-31). Never copied.

Anything malformed, any absolute path or "..", and any path that names a
credential, .state/ or output/dryrun/ RAISES: the manifest is checked, never
trusted.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MANIFEST_FILE = Path("config") / "STATE_MANIFEST.json"
VERSION = 1

# Names the manifest may never hold, in any entry (tests pin the same list).
FORBIDDEN = ("oauth", "token", "secret", ".pem", "private.json", "credential")
FORBIDDEN_PREFIXES = (".state", ".state_sync.json", ".git", "output/dryrun")
# Files that exist only in the private repo; no manifest path may be one.
PRIVATE_REPO_ONLY = ("ENGINE_COMMIT", "README.md", ".gitattributes")


class ManifestError(ValueError):
    """The manifest is malformed or names something it may never name."""


def _clean(p: str, where: str) -> str:
    s = str(p).replace("\\", "/").strip().rstrip("/")
    pp = PurePosixPath(s)
    if not s or pp.is_absolute() or ".." in pp.parts or s.startswith("./"):
        raise ManifestError(f"{where}: {p!r} must be a plain relative path inside the repo")
    low = s.lower()
    if any(f in low for f in FORBIDDEN):
        raise ManifestError(f"{where}: {p!r} names a credential -- credentials are never state")
    if any(low == x or low.startswith(x + "/") for x in FORBIDDEN_PREFIXES):
        raise ManifestError(f"{where}: {p!r} is the private clone, the sync record, git, or "
                            "output/dryrun -- never state")
    if s in PRIVATE_REPO_ONLY:
        raise ManifestError(f"{where}: {p!r} is a private-repo-only file")
    return s


@dataclass(frozen=True)
class Manifest:
    files: tuple
    dirs: tuple          # ((dir, frozenset(except)), ...)
    patterns: tuple      # ((dir, pattern, frozenset(except)), ...)
    excluded: tuple
    public_exceptions: tuple
    private_repo: str
    raw: dict = field(compare=False, repr=False, default_factory=dict)

    # ---------------------------------------------------------------- matching
    def contains(self, rel: str) -> bool:
        """Is `rel` (repo-relative, any slashes) a state path?"""
        r = str(rel).replace("\\", "/").strip("/")
        if r in self.public_exceptions:
            return False
        if r in self.files:
            return True
        for d, exc in self.dirs:
            if r.startswith(d + "/"):
                return r[len(d) + 1:] not in exc
        parent, _, name = r.rpartition("/")
        for d, pat, exc in self.patterns:
            if parent == d and fnmatch.fnmatchcase(name, pat) and name not in exc:
                return True
        return False

    def present(self, root) -> list:
        """Every state path that exists under `root`, sorted, repo-relative
        with forward slashes. Walks only the manifest's own files, dirs and
        pattern directories (not below them), never anything else."""
        root = Path(root)
        out = set()
        for f in self.files:
            if (root / f).is_file():
                out.add(f)
        for d, _ in self.dirs:
            base = root / d
            if base.is_dir():
                for p in base.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(root).as_posix()
                        if self.contains(rel):
                            out.add(rel)
        for d, _, _ in self.patterns:
            base = root / d
            if base.is_dir():
                for p in base.iterdir():
                    if p.is_file():
                        rel = p.relative_to(root).as_posix()
                        if self.contains(rel):
                            out.add(rel)
        return sorted(out)

    def entries(self) -> list:
        """Every entry as a repo-relative string, for .gitignore checks:
        files, dirs (with a trailing "/"), and dir/pattern."""
        return ([*self.files] + [d + "/" for d, _ in self.dirs]
                + [f"{d}/{p}" for d, p, _ in self.patterns])


def load(root=None) -> Manifest:
    """config/STATE_MANIFEST.json under `root` (default: this repo), validated."""
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    path = root / MANIFEST_FILE
    if not path.is_file():
        raise ManifestError(f"{MANIFEST_FILE} is missing under {root}")
    blob = json.loads(path.read_text(encoding="utf-8"))
    return parse(blob)


def parse(blob: dict) -> Manifest:
    if blob.get("version") != VERSION:
        raise ManifestError(f"{MANIFEST_FILE}: version must be {VERSION}, not {blob.get('version')!r}")
    known = {"version", "_comment", "private_repo", "files", "dirs", "patterns", "excluded",
             "public_exceptions"}
    unknown = sorted(set(blob) - known)
    if unknown:
        raise ManifestError(f"{MANIFEST_FILE}: unknown key(s) {unknown}")
    repo = str(blob.get("private_repo", "")).strip()
    if not repo or repo.count("/") != 1:
        raise ManifestError(f"{MANIFEST_FILE}: private_repo must be 'owner/name'")

    def need_what(e, where):
        if not isinstance(e, dict) or not str(e.get("what", "")).strip():
            raise ManifestError(f"{where}: every entry needs a 'what' saying what it is")

    files = []
    for i, e in enumerate(blob.get("files", [])):
        where = f"{MANIFEST_FILE} files[{i}]"
        need_what(e, where)
        if set(e) - {"path", "what"}:
            raise ManifestError(f"{where}: unknown field(s) {sorted(set(e) - {'path', 'what'})}")
        files.append(_clean(e["path"], where))
    dirs = []
    for i, e in enumerate(blob.get("dirs", [])):
        where = f"{MANIFEST_FILE} dirs[{i}]"
        need_what(e, where)
        if set(e) - {"path", "what", "except"}:
            raise ManifestError(f"{where}: unknown field(s)")
        exc = []
        for x in e.get("except", []):
            if any(c in str(x) for c in "*?["):
                raise ManifestError(f"{where}: except entries are exact names, not {x!r}")
            exc.append(_clean(x, where))
        dirs.append((_clean(e["path"], where), frozenset(exc)))
    patterns = []
    for i, e in enumerate(blob.get("patterns", [])):
        where = f"{MANIFEST_FILE} patterns[{i}]"
        need_what(e, where)
        if set(e) - {"dir", "name", "what", "except"}:
            raise ManifestError(f"{where}: unknown field(s)")
        name = str(e.get("name", ""))
        if not name or "/" in name or "\\" in name or "**" in name or name in ("*", ".*"):
            raise ManifestError(f"{where}: name {name!r} must be a file-name pattern inside its "
                                "directory, no '/', no '**', not a bare '*'")
        _clean(f"{e['dir']}/{name.replace('*', 'x').replace('?', 'x')}", where)
        exc = []
        for x in e.get("except", []):
            if "/" in str(x) or any(c in str(x) for c in "*?["):
                raise ManifestError(f"{where}: except entries are exact file names, not {x!r}")
            exc.append(str(x))
        patterns.append((_clean(e["dir"], where), name, frozenset(exc)))
    excluded = []
    for i, e in enumerate(blob.get("excluded", [])):
        where = f"{MANIFEST_FILE} excluded[{i}]"
        if not isinstance(e, dict) or not str(e.get("why", "")).strip() or not e.get("path"):
            raise ManifestError(f"{where}: every exclusion needs a path and a 'why'")
        excluded.append(str(e["path"]).replace("\\", "/"))
    public = []
    for i, e in enumerate(blob.get("public_exceptions", [])):
        where = f"{MANIFEST_FILE} public_exceptions[{i}]"
        if not isinstance(e, dict) or not str(e.get("why", "")).strip() or not e.get("path"):
            raise ManifestError(f"{where}: every public exception needs a path and a 'why'")
        public.append(_clean(e["path"], where))
    for p in files:
        if any(p.startswith(d + "/") for d, _ in dirs):
            raise ManifestError(f"{MANIFEST_FILE}: {p} is listed as a file and also lies "
                                "inside a listed dir -- list it once")
    return Manifest(tuple(files), tuple(dirs), tuple(patterns), tuple(excluded),
                    tuple(public), repo, raw=blob)
