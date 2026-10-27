"""The engine key means "did the simulator change" (HANDOFF_ENGINE_KEY_SCOPE_2026-10-23).

engine_version called ANY difference in the tree dirty. A refresh writes its
own outputs -- output/live_lines_weekN*.json and the calibration log -- so on
2026-10-23 refresh_lines priced a payload as f33ca19, render_live_lines read
f33ca19-dirty, and the page refused the payload it had just been handed. It
fired on the first refresh after a commit and then went quiet once the tree
was dirty anyway. The same mistake one level up: the weekly workflow writes
into config/ every week, so "config/ is the engine" would have marked every
line of every week dirty.
"""
import json
import subprocess
from pathlib import Path

import pytest

from modules import calibration_log as cal
from modules import live_lines_page as page
from modules.data_loader import atomic_write_json

ROOT = Path(__file__).parent.parent
PRIOR = "config/snapshots/PLAYERLIST_2026-10-13.xlsx"


def _git(base, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=base, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    """A committed tree laid out like the project's."""
    files = {
        "modules/simulator.py": "X = 1\n",
        "scripts/refresh.py": "print('refresh')\n",
        "config/league_config.json": json.dumps({"durability_prior": {"snapshot": PRIOR}}),
        PRIOR: "frozen pre-season GP",
        "config/INJURY_OVERRIDES.json": '{"players": []}',
        "config/PLAYER_AGES.json": "{}",
        "config/RECENT_CONTENT.json": "{}",
        "config/LAST_WEEK_RECAP.md": "recap\n",
        "config/POTW_HISTORY.json": "{}",
        "data/PLAYERLOG.csv": "a,b\n",
        "output/.keep": "",
        "tests/test_x.py": "",
    }
    for rel, text in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    cal._ENGINE_VERSION.clear()
    yield tmp_path
    cal._ENGINE_VERSION.clear()


def _fresh(base) -> dict:
    """engine_version as a NEW process sees it (the cache is per process)."""
    cal._ENGINE_VERSION.clear()
    return cal.engine_version(base)


def _tree_dirty(base) -> bool:
    return bool(_git(base, "status", "--porcelain").strip())


def _refresh_writes(base, week=2):
    """Exactly where a refresh writes: its payload, its state file, the log."""
    atomic_write_json(base / "output" / f"live_lines_week{week}.json", {"week": week})
    atomic_write_json(base / "output" / f"live_lines_week{week}.state.json", {"seed": 1})
    atomic_write_json(cal.log_path(base), {"lines": [{"week": week}]})


# 1 -- output/ and data/ are not the engine
def test_writing_output_or_data_does_not_change_the_engine_key(repo):
    clean = _fresh(repo)
    assert clean["dirty"] is False
    _refresh_writes(repo)
    (repo / "data" / "PLAYERLOG.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert _tree_dirty(repo), "precondition: the tree is dirty, which is what used to trip"
    assert _fresh(repo) == clean


# 1b -- nor is what the weekly workflow writes into config/ (corrects the brief)
def test_the_weekly_workflows_config_writes_do_not_change_it(repo):
    clean = _fresh(repo)
    for rel in ("config/INJURY_OVERRIDES.json", "config/PLAYER_AGES.json",
                "config/RECENT_CONTENT.json", "config/LAST_WEEK_RECAP.md",
                "config/POTW_HISTORY.json"):
        (repo / rel).write_text("edited this week\n", encoding="utf-8")
    (repo / "config" / ".leaguehistory_applied_weeks.json").write_text("[1]", encoding="utf-8")
    (repo / "config" / "snapshots" / "PLAYERLIST_2026-11-02.xlsx").write_text("weekly", encoding="utf-8")
    assert _tree_dirty(repo)
    assert _fresh(repo) == clean


# 2 -- the simulator's code and parameters are
@pytest.mark.parametrize("rel,text", [
    ("modules/simulator.py", "X = 2\n"),
    ("modules/new_engine_part.py", "Y = 1\n"),          # untracked code counts
    ("scripts/refresh.py", "print('changed')\n"),
    ("config/league_config.json", json.dumps({"durability_prior": {"snapshot": PRIOR}, "x": 1})),
    (PRIOR, "overwritten in place"),                       # the frozen prior is an engine input
])
def test_touching_the_engine_makes_it_dirty(repo, rel, text):
    commit = _fresh(repo)["commit"]
    (repo / rel).write_text(text, encoding="utf-8")
    after = _fresh(repo)
    assert after == {"commit": commit, "dirty": True}
    assert cal.engine_key({"engine_commit": after["commit"],
                           "engine_dirty": after["dirty"]}) == f"{commit}-dirty"


def test_tests_are_not_the_engine(repo):
    clean = _fresh(repo)
    (repo / "tests" / "test_x.py").write_text("def test(): pass\n", encoding="utf-8")
    assert _fresh(repo) == clean


# 3 -- a refresh followed immediately by a render does not trip the guard
def _payload(engine):
    return {"engine": {"commit": engine["commit"], "dirty": engine["dirty"],
                       "key": cal.engine_key({"engine_commit": engine["commit"],
                                              "engine_dirty": engine["dirty"]})}}


def test_a_refresh_then_a_render_does_not_trip_the_guard(repo):
    priced = _payload(_fresh(repo))        # the refresh process
    _refresh_writes(repo)                  # ... and what it leaves behind
    cal._ENGINE_VERSION.clear()            # the render is a new process
    check = page.engine_check(priced, base_path=repo)
    assert check["ok"], check
    assert check["payload"] == check["current"] == priced["engine"]["key"]


def test_the_guard_still_trips_when_the_engine_changed_in_between(repo):
    priced = _payload(_fresh(repo))
    _refresh_writes(repo)
    (repo / "modules" / "simulator.py").write_text("X = 3\n", encoding="utf-8")
    cal._ENGINE_VERSION.clear()
    check = page.engine_check(priced, base_path=repo)
    assert not check["ok"] and check["current"].endswith("-dirty")


def test_the_engine_scope_excludes_everything_a_refresh_writes():
    """Structural, on the real project: adding data/ or output/ to the
    engine's scope would bring the self-dirtying key straight back."""
    scope = cal.engine_paths(ROOT)
    assert "config/league_config.json" in scope
    assert "modules" in scope and "scripts" in scope
    for written in (cal.log_path(ROOT), ROOT / "output" / "live_lines_week2.json",
                    ROOT / "output" / "live_lines_week2.state.json"):
        rel = written.resolve().relative_to(ROOT.resolve()).as_posix()
        assert not any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in scope), rel
    # and the durability prior it names is the one config actually uses
    conf = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert conf["durability_prior"]["snapshot"] in scope
