#!/usr/bin/env python3
"""
state_overlay.py -- lay the private repo's state over an engine checkout, and
copy it back (step 1c-ii; claude/SELF_RUNNING_DESIGN.md s.2.1).

    python scripts/state_overlay.py in  --state-dir ../state    before the run
    python scripts/state_overlay.py out --state-dir ../state    after it, good or refused

The runner checks out the engine (public) at ENGINE_COMMIT and the private
repo beside it. `in` makes every state path of the engine tree equal the
private checkout's; `out` makes the private checkout's equal the engine
tree's. Run from the engine checkout (or --engine-dir).

ONLY MANIFEST PATHS, BOTH WAYS. Which paths are state is config/STATE_MANIFEST.json
(modules/state_manifest.py), read from the ENGINE tree. The copying is
scripts/state.py's copy_state, the same code `state.py pull` and `push` use:
it copies what differs, deletes state paths the other side lacks, and asserts
it never touches a path outside the manifest. So oauth2.json, written on the
runner from its secret, is never copied back: it is not, and can never be, a
manifest path (the manifest refuses credential names; tests pin both).

REFUSALS (exit 1, nothing copied):
  - the engine tree has no config/STATE_MANIFEST.json, or it is malformed;
  - --state-dir is not a private-repo checkout (no ENGINE_COMMIT in it). The
    private repo holds no manifest of its own: the engine's is the one list;
  - any path about to be copied, either way, names a credential;
  - `out` without a completed `in` into this tree, from the same state
    checkout (.state_overlay.json, written by `in`; gitignored, never state).
    A failed or skipped `in` must never be copied back: the engine tree's
    missing state would delete the private repo's.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import state as st                          # noqa: E402  (copy_state, hashes: one copier)
from modules import state_manifest as sm    # noqa: E402

MARKER = ".state_overlay.json"


class OverlayRefused(RuntimeError):
    pass


def _credential(rel: str) -> bool:
    name = rel.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return any(f in name for f in sm.FORBIDDEN)


def _checks(engine: Path, state: Path):
    try:
        man = sm.load(engine)
    except sm.ManifestError as e:
        raise OverlayRefused(f"the engine tree's manifest: {e}") from None
    if not state.is_dir():
        raise OverlayRefused(f"--state-dir {state} does not exist")
    if not (state / "ENGINE_COMMIT").is_file():
        raise OverlayRefused(f"--state-dir {state} is not a checkout of the private repo "
                             f"({man.private_repo}): it has no ENGINE_COMMIT")
    if engine.resolve() == state.resolve():
        raise OverlayRefused("--state-dir is the engine tree itself")
    for root in (engine, state):
        bad = [p for p in man.present(root) if _credential(p)]
        if bad:
            raise OverlayRefused(f"credential path(s) among the state paths in {root}: {bad}. "
                                 "Credentials are never state")
    return man


def overlay_in(engine, state, out=print) -> dict:
    engine, state = Path(engine), Path(state)
    man = _checks(engine, state)
    copied, deleted = st.copy_state(state, engine, man)
    files = st.hashes(engine, man)
    if files != st.hashes(state, man):
        raise OverlayRefused("after the copy the engine tree's state differs from the private "
                             "checkout's: stop")
    (engine / MARKER).write_text(json.dumps(
        {"_comment": "state_overlay.py: overlay in completed into this tree. Never state.",
         "state_dir": str(state.resolve()), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "files": len(files)}, indent=2) + "\n", encoding="utf-8")
    out(f"overlay in: {len(files)} state file(s) from {state} ({len(copied)} copied, "
        f"{len(deleted)} removed)")
    return {"files": len(files), "copied": copied, "deleted": deleted}


def overlay_out(engine, state, out=print) -> dict:
    engine, state = Path(engine), Path(state)
    man = _checks(engine, state)
    mk = engine / MARKER
    if not mk.is_file():
        raise OverlayRefused(f"no completed overlay in ({MARKER} is missing in {engine}): copying "
                             "back an engine tree that never received the state would delete it "
                             "from the private repo")
    blob = json.loads(mk.read_text(encoding="utf-8"))
    if Path(blob.get("state_dir", "")) != state.resolve():
        raise OverlayRefused(f"overlay in came from {blob.get('state_dir')}, not {state.resolve()}")
    copied, deleted = st.copy_state(engine, state, man)
    if st.hashes(engine, man) != st.hashes(state, man):
        raise OverlayRefused("after the copy back the private checkout's state differs from the "
                             "engine tree's: stop")
    out(f"overlay out: {len(copied)} state file(s) changed, {len(deleted)} removed")
    for p in copied:
        out(f"  changed  {p}")
    for p in deleted:
        out(f"  removed  {p}")
    return {"copied": copied, "deleted": deleted}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Overlay the private repo's state on an engine "
                                             "checkout (in), or copy it back (out).")
    ap.add_argument("direction", choices=("in", "out"))
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--engine-dir", default=str(ROOT))
    a = ap.parse_args(argv)
    try:
        (overlay_in if a.direction == "in" else overlay_out)(a.engine_dir, a.state_dir)
    except OverlayRefused as e:
        print(f"REFUSED (overlay {a.direction}): {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
