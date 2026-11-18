"""The stakes a real-data replay test states for itself (task 50, 11-16).

Several plumbing tests replay report week 1 on the project's own data. Their
roster plan reaches an 18b decision (Hayden's injured outnumber his IL slots)
at a window from week 2 on, and prices it from output/stakes.json -- which
Step 6 rewrites every Monday for the report week, so on 11-16 it held rows
from week 5 on and the week-2..4 windows raised StakesError ("no
regular_season row for Hayden, week 4"). A live run plans from the current
week, where the file covers every window: this is a replay-only gap, not an
engine path. These tests are about wiring, seeds and the IL mask, not stakes,
so they state the stakes they replay with: the real file, as of the replayed
week, each race's earliest real row standing in for the weeks before it. A
missing file or another season stays the engine's bootstrap (None, note).
"""
import copy

from modules import drop_inputs


def as_of_week(blob: dict, week: int) -> dict:
    out = copy.deepcopy(blob)
    out["week"] = int(week)
    out["_stated_by_test"] = f"tests/stakes_state.py: the real stakes, stated as of week {week}"
    for team in out["teams"].values():
        rows = team.get("regular_season") or {}
        if not rows:
            continue
        first = min(int(w) for w in rows)
        for w in range(int(week), first):
            rows[str(w)] = copy.deepcopy(rows[str(first)])
    return out


def state(mp, week: int):
    """Make drop_inputs.read_stakes hand the plan the real stakes as of `week`
    (mp: a pytest MonkeyPatch the fixture undoes)."""
    real = drop_inputs.read_stakes

    def read(base_path, season=None, path=None):
        blob, note = real(base_path, season, path=path)
        return (as_of_week(blob, week), note) if blob is not None else (blob, note)
    mp.setattr(drop_inputs, "read_stakes", read)
