"""The league's state lives in the private repo (P2, HANDOFF_P2_PRIVATE_STATE
2026-10-31; claude/SELF_RUNNING_DESIGN.md s.2 and s.10, invariants 1-3).

config/STATE_MANIFEST.json lists every state path; scripts/state.py moves
exactly those between this folder and the private clone at .state/. These
tests pin:
  1. every manifest path is ignored by the public .gitignore and tracked by
     nothing -- except the deliberate public exceptions, below;
  2. every gitignored path the engine reads at run time is in the manifest
     or on its commented exclusion list (a source-level check);
  3. the manifest never names a credential, .state/ or output/dryrun/;
  4. pull and push, on throwaway git repos: round trips, refusals, nothing
     outside the manifest touched, deletions propagate, init refuses a
     non-empty clone;
  5. a nested .state repo is never staged as files;
  6. the integrity check's --no-league-state flag: CI passes it, it skips
     exactly the checks that read state and lists each, and without it a
     missing state file fails.
"""
import ast
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import state_manifest as sm      # noqa: E402

MAN = sm.load(ROOT)

# DELIBERATE PUBLIC EXCEPTIONS (Nick, 10-31). Tracked files inside a manifest
# directory or pattern that stay public on purpose: the pinned pre-season
# durability prior (the public CI's integrity check reads it), and week 1's two
# live-line pages, kept as showcases. Every LATER week's page is state.
PUBLIC_EXCEPTIONS = {
    "config/snapshots/PLAYERLIST_2026-10-13.xlsx",
    "output/live_lines_week1.html",
    "output/live_lines_week1_midweek_DEMO.html",
}

HAVE_GIT = shutil.which("git") is not None and (ROOT / ".git").exists()
needs_git = pytest.mark.skipif(not HAVE_GIT, reason="needs git and this repo's .git")


def git(*args, cwd=ROOT, check=True):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout


def samples(man=MAN):
    """One concrete path per manifest entry, plus every state file present."""
    out = set(man.files)
    for d, _ in man.dirs:
        out.add(f"{d}/sample/inner.json")
    for d, pat, _ in man.patterns:
        out.add(f"{d}/{pat.replace('*', '7').replace('?', 'x')}")
    out.update(man.present(ROOT))
    return sorted(out)


def ignored(paths):
    r = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"], cwd=str(ROOT),
                       input="\n".join(paths) + "\n", capture_output=True, text=True)
    return set(r.stdout.split())


# ================================================== 1. ignored, tracked by nothing

def test_the_manifest_loads_and_names_the_private_repo():
    assert MAN.private_repo == "nickrolen/newsletter-state"
    assert set(MAN.public_exceptions) == PUBLIC_EXCEPTIONS


@needs_git
def test_every_manifest_path_is_ignored_by_the_public_gitignore():
    paths = samples()
    missed = sorted(set(paths) - ignored(paths))
    assert not missed, f"state paths the public .gitignore would let through: {missed}"


@needs_git
def test_no_tracked_file_is_state_but_the_deliberate_public_exceptions():
    tracked = git("ls-files", "-z").split("\0")
    state = sorted(f for f in tracked if f and MAN.contains(f))
    assert not state, f"tracked in the public repo but listed as state: {state}"
    in_scope = sorted(f for f in tracked if f and f in PUBLIC_EXCEPTIONS)
    assert in_scope == sorted(PUBLIC_EXCEPTIONS), "a public exception is no longer tracked"


def test_the_public_exceptions_are_inside_a_manifest_entry_and_never_state():
    for p in PUBLIC_EXCEPTIONS:
        assert not MAN.contains(p)
        stripped = sm.parse({**MAN.raw, "public_exceptions": []})
        assert stripped.contains(p), f"{p} is not inside any manifest entry: no need to except it"


# ============================================================ 3. never a credential

@pytest.mark.parametrize("bad", ["oauth2.json", "config/my_token.json", "data/secret.txt",
                                 "certs/key.pem", ".state", ".state/x", "output/dryrun",
                                 "output/dryrun/w1", ".state_sync.json", "../x", "/etc/passwd"])
def test_the_manifest_refuses_a_forbidden_path(bad):
    with pytest.raises(sm.ManifestError):
        sm.parse({**MAN.raw, "files": [{"path": bad, "what": "x"}]})
    with pytest.raises(sm.ManifestError):
        sm.parse({**MAN.raw, "dirs": [{"path": bad, "what": "x"}]})


def test_the_real_manifest_names_no_credential_clone_or_dryrun():
    for e in MAN.entries():
        low = e.lower()
        assert "oauth" not in low and "token" not in low and "secret" not in low
        assert not low.endswith(".pem") and not low.startswith(".state")
        assert not low.startswith("output/dryrun")


@pytest.mark.parametrize("name", ["*", "../x*", "sub/x*.json", "**/x", ".*"])
def test_a_pattern_cannot_reach_outside_its_directory(name):
    with pytest.raises(sm.ManifestError):
        sm.parse({**MAN.raw, "patterns": [{"dir": "data", "name": name, "what": "x"}]})


def test_patterns_match_only_in_their_own_directory():
    assert MAN.contains("data/waivers_week3.txt")
    assert not MAN.contains("data/sub/waivers_week3.txt")
    assert not MAN.contains("data/waivers_weekN_txt.example")
    assert MAN.contains("output/live_lines_week2.html")
    assert not MAN.contains("output/live_lines_week1.html")


# ================================================ 2. every ignored path read is listed

ROOT_DIRS = ("config/", "data/", "output/", "assets/", "archive/")
DIR_NAMES = {"CONFIG_DIR": "config", "DATA_DIR": "data", "OUTPUT_DIR": "output",
             "ASSETS_DIR": "assets", "WAIVERS_DIR": "data"}


def _parts(node):
    """A path expression as a string with '*' for anything computed, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.replace("\\", "/")
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "*" for v in node.values)
    if isinstance(node, ast.Name) and node.id in DIR_NAMES:
        return DIR_NAMES[node.id]
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Path" and node.args:
        return _parts(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _parts(node.left), _parts(node.right)
        if right is None:
            return None
        return right if left is None else f"{left.rstrip('/')}/{right.lstrip('/')}"
    return None


def engine_paths():
    """Every repo path the scripts and modules name, '*' where computed."""
    found = set()
    files = [*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py"), ROOT / "check_all.py"]
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            s = _parts(node)
            if s and s.startswith(ROOT_DIRS) and " " not in s and len(s) < 120:
                found.add(re.sub(r"\*+", "*", s))
    return sorted(found)


def _excluded(path):
    for e in MAN.excluded:
        e = e.rstrip("/")
        if path == e or path.startswith(e + "/") or fnmatch.fnmatchcase(path, e) \
                or fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], e):
            return True
    return False


@needs_git
def test_every_gitignored_path_the_engine_names_is_state_or_excluded():
    paths = engine_paths()
    assert len(paths) > 50, "the path scan found almost nothing -- it is broken"
    sample = {p: p.replace("*", "7") for p in paths}
    ign = ignored(list(sample.values()))
    assert len(ign) > 30, "the scan found almost no ignored paths -- it is broken"
    offenders = [p for p, s in sample.items()
                 if s in ign and not MAN.contains(s) and not _excluded(s)
                 and not MAN.contains(s.rstrip("/") + "/x")]   # a manifest directory itself
    assert not offenders, ("gitignored paths the engine reads or writes that are neither "
                           f"state (config/STATE_MANIFEST.json) nor excluded: {offenders}")


# Paths the scan finds that git neither tracks nor ignores, on purpose. Each
# is a name fragment the code builds a pattern from, a generic glob used to
# scan a folder, or a public default -- never a file the engine writes as
# league state. Anything else that is neither tracked nor ignored would be
# committed to the public repo by a stray `git add -A` (step 1a, 10-31: the
# first version of this guard checked ignored paths only and let a new state
# file under output/ through).
NEITHER_ON_PURPOSE = {
    "data/nba_schedule_": "a name prefix (data/nba_schedule_<season>.json is tracked, public)",
    "data/waivers_week": "a name prefix of the waivers pattern (state)",
    "output/stats_report_week": "a name prefix of the stats-report pattern (state)",
    "output/*": "a generic glob: code that scans output/",
    "output/*.html": "a generic glob: code that scans output/ for pages",
    "data/nba_schedule.json": "the schedule's fallback default name; the configured "
                              "data/nba_schedule_2026-27.json is tracked and public",
    "data/calibration": "the directory; its one file, published_lines.json, is state",
}


@needs_git
def test_no_path_the_engine_names_would_be_committed_by_accident():
    """Every path the engine names is tracked (public on purpose), ignored
    (state or excluded, checked above), or listed in NEITHER_ON_PURPOSE."""
    paths = engine_paths()
    sample = {p: p.replace("*", "7") for p in paths}
    ign = ignored(list(sample.values()))
    tracked = set(git("ls-files", "-z").split("\0"))
    stray = []
    for p, s in sample.items():
        if s in ign or p in NEITHER_ON_PURPOSE:
            continue
        if s in tracked or any(f.startswith(s.rstrip("/") + "/") for f in tracked):
            continue
        stray.append(p)
    assert not stray, ("paths the engine reads or writes that git neither tracks nor "
                       f"ignores -- a `git add -A` would publish them: {sorted(stray)}. "
                       "League state goes in config/STATE_MANIFEST.json and .gitignore")


# ============================================================ 4. pull and push

STATE = Path(ROOT / "scripts" / "state.py")


def _env():
    env = dict(os.environ)
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


def run_state(root, cmd):
    r = subprocess.run([sys.executable, str(STATE), cmd, "--root", str(root)],
                       capture_output=True, text=True, env=_env())
    return r.returncode, r.stdout + r.stderr


def sh(*args, cwd):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stderr
    return r.stdout


def machine(tmp_path, name, remote):
    """A fake engine folder: its own git repo (for ENGINE_COMMIT), the real
    manifest, and a clone of the private remote at .state."""
    root = tmp_path / name
    (root / "config").mkdir(parents=True)
    shutil.copy(ROOT / sm.MANIFEST_FILE, root / sm.MANIFEST_FILE)
    sh("init", "-q", cwd=root)
    sh("add", "config/STATE_MANIFEST.json", cwd=root)
    sh("commit", "-q", "-m", "engine", cwd=root)
    sh("clone", "-q", str(remote), ".state", cwd=root)
    return root


def write(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


SEED = {
    "config/ROSTERS.json": '{"rosters": {}}\r\n',          # CRLF must survive
    "data/LINEUPS.xlsx": b"\x00\x01binary\xff",
    "data/waivers_week2.txt": "- [2026-10-26] A: B\n",
    "data/lore_backups/2026-10-01.json": "{}\n",
    "data/lore_backups/2026-10-02.json": "{}\n",
    "config/snapshots/PLAYERLIST_2026-10-26.xlsx": b"snap",
}
OUTSIDE = {   # never state: must never move, in either direction
    "config/league_config.json": "{}\n",
    "notes.txt": "mine\n",
    "output/dryrun/w1/packet.json": "{}\n",
    "data/waivers_weekN_txt.example": "example\n",
    "config/snapshots/PLAYERLIST_2026-10-13.xlsx": b"pinned prior",   # public exception
}


@pytest.fixture
def two(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("needs git")
    remote = tmp_path / "remotes" / "nickrolen" / "newsletter-state.git"
    remote.mkdir(parents=True)
    sh("init", "-q", "--bare", str(remote), cwd=tmp_path)
    a = machine(tmp_path, "desk", remote)
    for rel, data in {**SEED, **OUTSIDE}.items():
        write(a, rel, data)
    rc, out = run_state(a, "init")
    assert rc == 0, out
    b = machine(tmp_path, "runner", remote)
    write(b, "notes.txt", "runner's own\n")
    return a, b


def tree(root, rels):
    return {r: (root / r).read_bytes() if (root / r).is_file() else None for r in rels}


def test_pull_then_push_round_trips_byte_identical(two):
    a, b = two
    rc, out = run_state(b, "pull")
    assert rc == 0, out
    for rel, data in SEED.items():
        want = data if isinstance(data, bytes) else data.encode("utf-8")
        assert (b / rel).read_bytes() == want, rel
    write(b, "config/ROSTERS.json", '{"rosters": {"Nick": []}}\r\n')
    rc, out = run_state(b, "push")
    assert rc == 0, out
    rc, out = run_state(a, "pull")
    assert rc == 0, out
    assert (a / "config/ROSTERS.json").read_bytes() == b'{"rosters": {"Nick": []}}\r\n'
    assert tree(a, SEED) == tree(b, SEED)
    assert (b / ".state" / "ENGINE_COMMIT").read_text().strip() == \
        sh("rev-parse", "HEAD", cwd=a).strip()


def test_nothing_changed_is_said_and_does_nothing(two):
    a, _ = two
    before = sh("rev-parse", "HEAD", cwd=a / ".state")
    rc, out = run_state(a, "push")
    assert rc == 0 and "nothing changed" in out
    assert sh("rev-parse", "HEAD", cwd=a / ".state") == before


def test_pull_refuses_local_edits_not_yet_pushed(two):
    """P2's guarantee, unchanged: local edits are never overwritten. Since
    1c-ii (HANDOFF_STEP1C2 s.5) pull refuses only when the SAME file changed
    on both sides; disjoint changes merge (the tests after s.4 below). This
    test was P2's with the runner editing a different file (LINEUPS); it now
    edits the same file, which is the case that must still refuse."""
    a, b = two
    run_state(b, "pull")
    write(b, "data/waivers_week2.txt", "- [2026-10-26] A: B, runner\n")
    run_state(b, "push")
    write(a, "data/waivers_week2.txt", "- [2026-10-26] A: C\n")
    rc, out = run_state(a, "pull")
    assert rc == 1 and "data/waivers_week2.txt" in out and "changed here AND in the private repo" in out
    assert (a / "data/waivers_week2.txt").read_text() == "- [2026-10-26] A: C\n"   # untouched


def test_push_refuses_when_the_private_repo_moved(two):
    a, b = two
    run_state(b, "pull")
    write(b, "data/LINEUPS.xlsx", b"runner's rows")
    assert run_state(b, "push")[0] == 0
    write(a, "config/ROSTERS.json", "{}\n")
    rc, out = run_state(a, "push")
    assert rc == 1 and "pull first" in out


def test_nothing_outside_the_manifest_moves_in_either_direction(two):
    a, b = two
    write(b / ".state", "stray_in_private_repo.txt", "x\n")      # not state
    sh("add", "-A", cwd=b / ".state")
    sh("commit", "-q", "-m", "stray", cwd=b / ".state")
    sh("push", "-q", cwd=b / ".state")
    rc, out = run_state(a, "pull")
    assert rc == 0, out
    assert not (a / "stray_in_private_repo.txt").exists()
    for rel, data in OUTSIDE.items():
        want = data if isinstance(data, bytes) else data.encode("utf-8")
        assert (a / rel).read_bytes() == want, rel
        assert not (a / ".state" / rel).exists(), f"{rel} reached the private repo"
    rc, out = run_state(b, "pull")
    assert rc == 0, out
    assert (b / "notes.txt").read_text() == "runner's own\n"
    assert not (b / "config/snapshots/PLAYERLIST_2026-10-13.xlsx").exists()
    assert not (b / "stray_in_private_repo.txt").exists()


def test_deletions_inside_a_manifest_directory_propagate(two):
    a, b = two
    run_state(b, "pull")
    (b / "data/lore_backups/2026-10-01.json").unlink()
    (b / "config/snapshots/PLAYERLIST_2026-10-26.xlsx").unlink()
    rc, out = run_state(b, "push")
    assert rc == 0, out
    rc, out = run_state(a, "pull")
    assert rc == 0 and "removed  data/lore_backups/2026-10-01.json" in out
    assert not (a / "data/lore_backups/2026-10-01.json").exists()
    assert (a / "data/lore_backups/2026-10-02.json").exists()
    assert not (a / "config/snapshots/PLAYERLIST_2026-10-26.xlsx").exists()
    assert (a / "config/snapshots/PLAYERLIST_2026-10-13.xlsx").read_bytes() == b"pinned prior"


def test_init_refuses_a_non_empty_clone(two, tmp_path):
    a, _ = two
    rec = a / ".state_sync.json"
    rec.unlink()
    rc, out = run_state(a, "init")
    assert rc == 1 and "not an empty clone" in out


def test_pull_refuses_without_a_clone_and_names_the_command(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("needs git")
    root = tmp_path / "bare_folder"
    (root / "config").mkdir(parents=True)
    shutil.copy(ROOT / sm.MANIFEST_FILE, root / sm.MANIFEST_FILE)
    rc, out = run_state(root, "pull")
    assert rc == 1
    assert "git clone https://github.com/nickrolen/newsletter-state.git .state" in out


def test_pull_refuses_a_clone_of_another_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("needs git")
    other = tmp_path / "remotes" / "someone" / "other.git"
    other.mkdir(parents=True)
    sh("init", "-q", "--bare", str(other), cwd=tmp_path)
    root = machine(tmp_path, "desk", other)
    rc, out = run_state(root, "pull")
    assert rc == 1 and "not nickrolen/newsletter-state" in out


def test_status_names_what_differs(two):
    a, b = two
    run_state(b, "pull")
    write(b, "data/LINEUPS.xlsx", b"runner")
    run_state(b, "push")
    write(a, "config/ROSTERS.json", "{}\n")
    sh("pull", "-q", cwd=a / ".state")       # as a fetch-and-look would show it
    rc, out = run_state(a, "status")
    assert rc == 0
    assert re.search(r"changed here\s+config/ROSTERS.json", out)
    assert re.search(r"changed in the private repo\s+data/LINEUPS.xlsx", out)


# ================================ 4b. 1c-ii: the three-way pull, set-engine, workflows
#
# HANDOFF_STEP1C2 s.5: Nick pulls Monday morning and builds; the cloud's
# pre-tip run commits mid-afternoon; Nick's push then refuses ("the private
# repo moved") and, before 1c-ii, pull refused too ("state changed here"): a
# deadlock. pull now merges when the two sides changed different files.

def _record(root):
    return json.loads((root / ".state_sync.json").read_text(encoding="utf-8"))


def test_disjoint_changes_merge_on_pull_and_then_push(two):
    a, b = two                                   # a: Nick's desktop; b: the cloud run
    assert run_state(b, "pull")[0] == 0
    write(b, "data/LINEUPS.xlsx", b"the pre-tip run's rows")
    (b / "data/lore_backups/2026-10-01.json").unlink()
    assert run_state(b, "push")[0] == 0
    write(a, "config/ROSTERS.json", '{"rosters": {"Nick": ["x"]}}\r\n')   # Nick's newsletter build
    write(a, "data/waivers_week3.txt", "new here\n")
    rc, out = run_state(a, "push")
    assert rc == 1 and "pull first" in out
    rc, out = run_state(a, "pull")
    assert rc == 0, out
    assert "kept     config/ROSTERS.json" in out and "updated  data/LINEUPS.xlsx" in out
    assert (a / "data/LINEUPS.xlsx").read_bytes() == b"the pre-tip run's rows"
    assert not (a / "data/lore_backups/2026-10-01.json").exists()
    assert (a / "config/ROSTERS.json").read_bytes() == b'{"rosters": {"Nick": ["x"]}}\r\n'
    assert (a / "data/waivers_week3.txt").read_text() == "new here\n"
    rc, out = run_state(a, "push")
    assert rc == 0 and "config/ROSTERS.json" in out and "data/waivers_week3.txt" in out, out
    assert "data/LINEUPS.xlsx" not in out                     # already the private repo's
    # and the other way: the runner pulls Nick's changes
    write(b, "output/nightly_runs.jsonl", "{}\n")            # the runner's own, not pushed
    rc, out = run_state(b, "pull")
    assert rc == 0, out
    assert (b / "config/ROSTERS.json").read_bytes() == b'{"rosters": {"Nick": ["x"]}}\r\n'
    assert (b / "output/nightly_runs.jsonl").read_text() == "{}\n"
    assert run_state(b, "push")[0] == 0
    rc, out = run_state(a, "pull")
    assert rc == 0 and (a / "output/nightly_runs.jsonl").read_text() == "{}\n"
    assert tree(a, [*SEED, "data/waivers_week3.txt", "output/nightly_runs.jsonl"]) == \
        tree(b, [*SEED, "data/waivers_week3.txt", "output/nightly_runs.jsonl"])


def test_an_overlap_refuses_and_changes_nothing(two):
    a, b = two
    run_state(b, "pull")
    write(b, "config/ROSTERS.json", "runner\n")
    write(b, "data/LINEUPS.xlsx", b"runner rows")
    run_state(b, "push")
    write(a, "config/ROSTERS.json", "desk\n")
    write(a, "data/waivers_week2.txt", "desk only\n")
    before = {"files": tree(a, [*SEED, *OUTSIDE]), "head": sh("rev-parse", "HEAD", cwd=a / ".state"),
              "record": _record(a)}
    rc, out = run_state(a, "pull")
    assert rc == 1 and "config/ROSTERS.json" in out and "data/waivers_week2.txt" not in out.split("nothing")[0]
    assert "data/LINEUPS.xlsx" not in out                      # only the real overlap is named
    assert tree(a, [*SEED, *OUTSIDE]) == before["files"]
    assert sh("rev-parse", "HEAD", cwd=a / ".state") == before["head"]
    assert _record(a) == before["record"]


def test_the_same_bytes_on_both_sides_is_not_an_overlap(two):
    a, b = two
    run_state(b, "pull")
    write(b, "config/ROSTERS.json", "same\n")
    run_state(b, "push")
    write(a, "config/ROSTERS.json", "same\n")
    rc, out = run_state(a, "pull")
    assert rc == 0, out
    assert run_state(a, "push")[1].strip().startswith("nothing changed")


def test_pull_with_local_changes_and_nothing_new_keeps_them(two):
    a, _ = two
    write(a, "config/ROSTERS.json", "desk\n")
    rc, out = run_state(a, "pull")
    assert rc == 0 and "1 local change(s) kept" in out
    assert (a / "config/ROSTERS.json").read_text() == "desk\n"
    assert run_state(a, "push")[0] == 0


def _engine_remote(tmp_path, root):
    """Give a fake engine folder an origin with a main branch."""
    remote = tmp_path / "remotes" / "engine.git"
    if not remote.exists():
        remote.mkdir(parents=True)
        sh("init", "-q", "--bare", str(remote), cwd=tmp_path)
    sh("branch", "-M", "main", cwd=root)
    sh("remote", "add", "origin", str(remote), cwd=root)
    sh("push", "-q", "origin", "main", cwd=root)


def test_set_engine_refuses_a_dirty_or_unpushed_engine_then_pins_it(two, tmp_path):
    a, b = two
    _engine_remote(tmp_path, a)
    write(a, "modules/x.py", "v1\n")
    sh("add", "modules/x.py", cwd=a)
    sh("commit", "-q", "-m", "code", cwd=a)                    # committed, not pushed
    rc, out = run_state(a, "set-engine")
    assert rc == 1 and "not on origin/main" in out
    sh("push", "-q", "origin", "main", cwd=a)
    write(a, "modules/x.py", "v2 uncommitted\n")
    rc, out = run_state(a, "set-engine")
    assert rc == 1 and "uncommitted" in out and "modules/x.py" in out
    sh("checkout", "-q", "--", "modules/x.py", cwd=a)
    head = sh("rev-parse", "HEAD", cwd=a).strip()
    rc, out = run_state(a, "set-engine")
    assert rc == 0, out
    assert (a / ".state" / "ENGINE_COMMIT").read_text().strip() == head
    assert _record(a)["commit"] == sh("rev-parse", "HEAD", cwd=a / ".state").strip()
    assert run_state(a, "set-engine")[1].strip().endswith("nothing changed")
    write(a, "config/ROSTERS.json", "after\n")
    assert run_state(a, "push")[0] == 0                         # the record moved along
    assert run_state(b, "pull")[0] == 0
    assert (b / ".state" / "ENGINE_COMMIT").read_text().strip() == head


def test_install_workflows_keeps_the_next_push_working(two):
    a, b = two
    src = a / "deploy" / "state-repo" / ".github" / "workflows"
    src.mkdir(parents=True)
    for f in (ROOT / "deploy" / "state-repo" / ".github" / "workflows").glob("*.yml"):
        shutil.copy(f, src / f.name)
    write(a / ".state", "stray.txt", "x\n")
    rc, out = run_state(a, "install-workflows")
    assert rc == 1 and "uncommitted changes" in out
    (a / ".state" / "stray.txt").unlink()
    rc, out = run_state(a, "install-workflows")
    assert rc == 0, out
    for f in src.iterdir():
        assert (a / ".state" / ".github" / "workflows" / f.name).read_bytes() == f.read_bytes()
    assert run_state(a, "install-workflows")[1].strip().endswith("nothing changed")
    write(a, "config/ROSTERS.json", "after\n")
    rc, out = run_state(a, "push")
    assert rc == 0, out
    assert run_state(b, "pull")[0] == 0
    assert (b / ".state" / ".github" / "workflows" / "run.yml").is_file()
    assert not (b / ".github").exists()                        # never copied out as state


# ======================================================= 5. .state is never staged

@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_nested_state_repo_is_never_staged_as_files(tmp_path):
    repo = tmp_path / "engine"
    repo.mkdir()
    sh("init", "-q", cwd=repo)
    shutil.copy(ROOT / ".gitignore", repo / ".gitignore")
    st = repo / ".state"
    (st / "config").mkdir(parents=True)
    sh("init", "-q", cwd=st)
    (st / "config" / "LEAGUE_LORE.json").write_text("{}")
    sh("add", "-A", cwd=st)
    sh("commit", "-q", "-m", "state", cwd=st)
    (repo / ".state_sync.json").write_text("{}")
    sh("add", "-A", cwd=repo)
    staged = sh("diff", "--cached", "--name-only", cwd=repo).split()
    assert not [p for p in staged if p.startswith(".state")], staged
    # and even without the ignore line, a nested repo is a gitlink, never its files
    (repo / ".gitignore").write_text("")
    sh("add", "-A", cwd=repo)
    listed = sh("ls-files", "-s", cwd=repo).splitlines()
    assert not any("LEAGUE_LORE" in ln for ln in listed), listed
    assert any(ln.startswith("160000") and ln.endswith(".state") for ln in listed), listed


# ============================================= 6. the integrity check without state

def _integrity():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vpi", ROOT / "scripts" / "verify_project_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ci_passes_the_flag():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "verify_project_integrity.py --no-league-state" in ci


def test_the_flag_skips_exactly_the_state_checks_and_lists_each():
    vpi = _integrity()
    res = vpi.check_config_integrity(no_league_state=True)
    info = res.get("info", [])
    assert len(info) == len(vpi.STATE_CHECKS)
    for name in vpi.STATE_CHECKS:
        assert any(name in ln and "skipped (--no-league-state)" in ln for ln in info), name
    assert f"{len(vpi.STATE_CHECKS)} league-state check(s) skipped" in res["status"]


def test_without_the_flag_a_missing_state_file_fails(tmp_path, monkeypatch):
    vpi = _integrity()
    monkeypatch.setattr(vpi, "PROJECT_ROOT", tmp_path)
    ran, skipped = [], []

    def _check_potw_attribution(warnings):
        ran.append(1)
        return []
    gate = vpi._state_gate(False, skipped)
    out = gate(_check_potw_attribution, [])
    assert ran == [] and len(out) == 1
    assert "config/POTW_HISTORY.json" in out[0] and "state.py pull" in out[0]
    gate = vpi._state_gate(True, skipped)
    assert gate(_check_potw_attribution, []) == [] and ran == [] and len(skipped) == 1


def test_every_state_check_is_registered_and_reads_only_manifest_paths():
    """A check that names a manifest path must be in STATE_CHECKS (or CI would
    fail on it, or skip it silently), and every path STATE_CHECKS names is
    state."""
    vpi = _integrity()
    src = (ROOT / "scripts" / "verify_project_integrity.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    readers = set()
    for fn in tree.body:
        if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("_check_")):
            continue
        for node in ast.walk(fn):
            s = _parts(node)
            if not s:
                continue
            for cand in (s, f"config/{s}", f"data/{s}"):
                c = cand.replace("*", "7")
                if MAN.contains(c) or any(c == d or c.startswith(d + "/") for d, _ in MAN.dirs):
                    readers.add(fn.name)
    assert readers <= set(vpi.STATE_CHECKS), sorted(readers - set(vpi.STATE_CHECKS))
    for name, paths in vpi.STATE_CHECKS.items():
        for p in paths:
            assert MAN.contains(p) or MAN.contains(p + "/x") or \
                any(p == d for d, _ in MAN.dirs), f"{name}: {p} is not state"
