"""Nothing may assume keepers start at a fixed draft round.

The league converted two IL+ slots to bench slots effective Week 16 of
2025-26 (2026-02-02). That grew the draft from 13 rounds to 15: drafted
rounds went 1-7 -> 1-9, keeper rounds went 8-13 -> 10-15.

Two places hardcoded the old boundary and would have failed silently:
  - report_builder's Draft Value Tracker skipped `round_num >= 8`, which in
    2026-27 drops 8 of 36 drafted picks out of the newsletter every week
  - build_draft_pick_values fit its regression on `r <= 7`, which would keep
    ignoring rounds 8-9 once 2026-27 has real results for them

Both now split on the is_keeper flag. These tests pin that.
"""
import ast
import re
from pathlib import Path

from modules.data_loader import LEAGUE_STRUCTURE, ROSTER_SLOTS
from modules.report_builder import _pick_is_keeper

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# The keeper test itself
# ---------------------------------------------------------------------------

def test_is_keeper_flag_wins_over_round_number():
    """A round-9 drafted pick is NOT a keeper, even though it used to be."""
    assert _pick_is_keeper({"round": 9, "is_keeper": False}, 9) is False
    assert _pick_is_keeper({"round": 12, "is_keeper": True}, 12) is True


def test_round_8_and_9_are_drafted_picks_now():
    """The 2026-27 expansion rounds must survive into the value tracker."""
    for rnd in (8, 9):
        assert _pick_is_keeper({"round": rnd, "is_keeper": False}, rnd) is False, (
            f"round {rnd} is a DRAFTED round from 2026-27 onward; treating it "
            "as a keeper silently drops it from the Draft Value Tracker"
        )


def test_fallback_uses_config_not_a_magic_number():
    """With no flag, fall back to config's drafted-round count."""
    drafted = LEAGUE_STRUCTURE["total_draft_rounds"]
    assert _pick_is_keeper({"round": drafted}, drafted) is False
    assert _pick_is_keeper({"round": drafted + 1}, drafted + 1) is True


# ---------------------------------------------------------------------------
# No new hardcoded round boundaries
# ---------------------------------------------------------------------------

KEEPER_BOUNDARY_PATTERN = re.compile(
    r"round\w*\s*(>=\s*8|<=\s*7|>\s*7|<\s*8)\b"
)


def test_no_hardcoded_keeper_round_boundary_in_engine():
    """Guard against the pattern coming back somewhere new."""
    offenders = []
    for d in ("modules", "scripts"):
        for f in sorted((PROJECT_ROOT / d).glob("*.py")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if KEEPER_BOUNDARY_PATTERN.search(line):
                    offenders.append(f"{d}/{f.name}:{i}: {line.strip()}")
    assert offenders == [], (
        "hardcoded keeper-round boundary found -- split on is_keeper instead, "
        "because the boundary moves when the roster changes:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Roster shape and round math agree with each other
# ---------------------------------------------------------------------------

def test_roster_slots_match_league_config():
    counts = {s: ROSTER_SLOTS.count(s) for s in set(ROSTER_SLOTS)}
    bench = counts.get("BN", 0)
    il = counts.get("IL", 0) + counts.get("IL+", 0)
    starters = len(ROSTER_SLOTS) - bench - il

    assert starters == LEAGUE_STRUCTURE["starters"]
    assert bench == LEAGUE_STRUCTURE["bench"]
    assert il == LEAGUE_STRUCTURE["il_slots"]
    assert len(ROSTER_SLOTS) == LEAGUE_STRUCTURE["roster_size"]


def test_draft_rounds_equal_the_non_il_roster_spots():
    """You draft into every roster spot that is not an IL slot.

    15 rounds = 9 drafted + 6 keepers = 17 roster spots - 2 IL.
    This is the relationship that changed, so it is worth pinning: if the
    roster changes again, this fails until the round counts are updated too.
    """
    s = LEAGUE_STRUCTURE
    total_rounds = s["total_draft_rounds"] + s["keepers_per_team"]
    assert total_rounds == s["roster_size"] - s["il_slots"], (
        f"{s['total_draft_rounds']} drafted + {s['keepers_per_team']} keepers "
        f"= {total_rounds} rounds, but the roster has "
        f"{s['roster_size'] - s['il_slots']} non-IL spots"
    )


# ---------------------------------------------------------------------------
# is_keeper survives the pipeline into DRAFT_PERFORMANCE.json
# ---------------------------------------------------------------------------

def test_extract_draft_fppg_carries_is_keeper():
    """build_draft_pick_values can only use the flag if extract emits it."""
    src = (PROJECT_ROOT / "scripts" / "extract_draft_fppg.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    emits = any(
        isinstance(n, ast.Constant) and n.value == "is_keeper"
        for n in ast.walk(tree)
    )
    assert emits, (
        "extract_draft_fppg.py must carry is_keeper into DRAFT_PERFORMANCE.json; "
        "without it build_draft_pick_values falls back to a round threshold"
    )


def test_historical_drafts_all_carry_is_keeper():
    """The flag the engine now depends on is actually present in the data."""
    import json
    drafts = json.loads(
        (PROJECT_ROOT / "data" / "historical" / "all_drafts.json").read_text(
            encoding="utf-8"
        )
    )
    missing = [d for d in drafts if "is_keeper" not in d]
    assert missing == [], f"{len(missing)} historical picks lack is_keeper"
