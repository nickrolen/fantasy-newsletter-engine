"""H51 (11-17): the shared guard for real-state builds of the hub and the
cards (tests/league_state.skip_if_actuals_behind). On Nick's laptop at 12:05
AM Pacific on 11-17, test_player_cards failed with ActualsStale: "yesterday"
(11-16) had moved past the local cache, which is only as fresh as the last
state pull. That is the normal state between midnight and a pull: skip with
both days named. A cache that reaches yesterday and still lacks a player is a
real gap and is NOT skipped."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import league_state

LA = ZoneInfo("America/Los_Angeles")


def _world(tmp_path, last_day, roster=("A Player",), cached=("A Player",)):
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    players = {str(i): {"name": n, "days": {"2026-11-14": [10.0, 1], last_day: [12.5, 1]}}
               for i, n in enumerate(cached, start=1)}
    blob = {"version": 1, "season": "2026-27", "first_day": "2026-10-20", "players": players,
            "roster_names": {n: i for i, n in enumerate(cached, start=1)},
            "rosters_from": "config/ROSTERS.json", "updated_at": None}
    (tmp_path / "data" / "player_actuals.json").write_text(json.dumps(blob), encoding="utf-8")
    (tmp_path / "config" / "ROSTERS.json").write_text(
        json.dumps({"rosters": {"Nick": list(roster)}}), encoding="utf-8")


def test_a_cache_a_day_behind_skips_naming_both_days(tmp_path):
    _world(tmp_path, "2026-11-15")
    with pytest.raises(pytest.skip.Exception, match=r"ends 2026-11-15, before this build's yesterday "
                                                    r"\(2026-11-16"):
        league_state.skip_if_actuals_behind(datetime(2026, 11, 17, 0, 5, tzinfo=LA), root=tmp_path)


def test_a_current_cache_runs(tmp_path):
    _world(tmp_path, "2026-11-16")
    league_state.skip_if_actuals_behind(datetime(2026, 11, 17, 0, 5, tzinfo=LA), root=tmp_path)


def test_a_roster_pickup_the_cache_has_not_fetched_skips_by_name(tmp_path):
    _world(tmp_path, "2026-11-16", roster=("A Player", "New Pickup"))
    with pytest.raises(pytest.skip.Exception, match="New Pickup, not yet in data/player_actuals.json"):
        league_state.skip_if_actuals_behind(datetime(2026, 11, 17, 0, 5, tzinfo=LA), root=tmp_path)


def test_no_cache_is_no_league_state(tmp_path):
    with pytest.raises(pytest.skip.Exception, match="league state not in this checkout"):
        league_state.skip_if_actuals_behind(datetime(2026, 11, 17, 0, 5, tzinfo=LA), root=tmp_path)


@pytest.mark.slow       # reads every test file: ~3 s on the VM's shared folder
def test_every_real_hub_build_in_the_suite_is_guarded():
    """Every test or fixture that builds the real hub (hub_state.build on
    ROOT) calls the guard first, so a new one can't quietly fail on the
    calendar again."""
    import ast
    import re
    from pathlib import Path
    tests = Path(__file__).resolve().parent
    unguarded = []
    for f in sorted(tests.glob("test_*.py")):
        src = f.read_text(encoding="utf-8")
        if not re.search(r"\b(?:hs|hub_state)\.build\(ROOT\b", src):
            continue
        lines = src.splitlines()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef):
                body = "\n".join(lines[node.lineno - 1:node.end_lineno])
                if re.search(r"\b(?:hs|hub_state)\.build\(ROOT\b", body) \
                        and "skip_if_actuals_behind(" not in body:
                    unguarded.append(f"{f.name}::{node.name}")
    assert not unguarded, unguarded
