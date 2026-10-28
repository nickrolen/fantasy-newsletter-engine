"""The IL state a real-data plumbing test states for itself.

The weekly suite runs at Step 0b, before the roster sync refreshes
data/IL_SLOTS.json, so these tests cannot demand this week's file. They take
the slots the last sync wrote -- the same sync that wrote ROSTERS.json, so the
two agree -- and state the week themselves. A missing file still raises: the
real rosters carry IL players, and an empty IL would put 16 men in 15 spots.
"""
import json
from pathlib import Path

from modules import roster_plan

ROOT = Path(__file__).parent.parent


def as_last_synced(fantasy_week: int) -> dict:
    path = ROOT / roster_plan.IL_FILE
    if not path.exists():
        raise roster_plan.ILSlotsError(f"{path} is missing: run "
                                       f"`python scripts/sync_transactions.py --il-only` once")
    slots = json.loads(path.read_text(encoding="utf-8"))["slots"]
    return {"fantasy_week": int(fantasy_week), "slots": slots, "fetched_at": None}
