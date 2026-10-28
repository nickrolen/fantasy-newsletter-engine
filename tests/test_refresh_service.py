"""B3: the live line refreshed every midnight (HANDOFF_B3_REFRESH_2026-10-22).

The cache key is the one piece of real engineering here: state_hash is a
fingerprint of the week's PLAYED state and nothing else, so a cache keyed on
it would serve a stale line after a tag change, a PLAYERLIST refresh, an
overrides edit, a new seed or an engine change -- the changes a refresh
exists to catch.
"""
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from modules import calibration_log as cal
from modules import week_state as ws
from modules.projections import PlayerProjection, TeamProjections
from test_live_lines import D, MON, _data, _teams

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
rl = importlib.import_module("refresh_lines")
rs = importlib.import_module("refresh_service")

CLEAN = {"commit": "abc1234", "dirty": False}
TAGS = {"Nikola Jokić": "O"}


@pytest.fixture
def svc(monkeypatch, tmp_path):
    """run(as_of, statuses=..., **kw) on the synthetic week 2 of test_live_lines,
    in a scratch project folder; a clean engine unless the test says not."""
    box = {"teams": _teams(), "engine": dict(CLEAN), "pulled": [], "data": {}}
    monkeypatch.setattr(rl, "load_all_team_projections", lambda data: box["teams"])
    monkeypatch.setattr(cal, "engine_version", lambda base=".": dict(box["engine"]))

    def run(as_of, statuses=TAGS, through=None, **kw):
        def load():
            data, _ = _data(through=box["data"].get("through", through or as_of))
            for k, v in box["data"].items():
                if k != "through":
                    setattr(data, k, v)
            return data
        kw.setdefault("puller", lambda d: box["pulled"].append(d))
        return rs.run(tmp_path, as_of=as_of, week=2, sims=300, trigger="scheduled",
                      load=load, statuses=statuses, **kw)
    run.box, run.tmp = box, tmp_path
    run.line = lambda: (tmp_path / "output" / "live_lines_week2.json").read_bytes()
    run.state = lambda: (tmp_path / "output" / "live_lines_week2.state.json").read_bytes()
    run.runs = lambda: json.loads((tmp_path / "output" / "live_lines_week2.runs.json").read_text(encoding="utf-8"))
    return run


# 1 -- no change: byte-identical; a tag change: a different line
def test_no_change_is_byte_identical_and_a_tag_change_is_not(svc):
    svc(MON)                                         # the week's tag record starts Monday
    first = svc(D[2])
    assert first["outcome"] == "priced" and first["exit"] == 0
    before = svc.line()
    again = svc(D[2])
    assert again["outcome"] == "unchanged"
    assert svc.line() == before, "a no-change refresh rewrote the line"
    moved = svc(D[2], statuses={**TAGS, "B1": "O"})
    assert moved["outcome"] == "priced" and "tags" in moved["why_priced"]
    after = json.loads(svc.line())
    assert after["lines"] != json.loads(before)["lines"]
    assert after["produced_by"]["run_id"] == moved["run_id"]


# 2 -- the key covers what state_hash does not
def _prepared(tmp_path, statuses=TAGS, teams=None, overrides=None, seed=5):
    data, _ = _data(through=D[2])
    if overrides is not None:
        data.injury_overrides = {"players": overrides}
    return rl.prepare(tmp_path, 2, D[2], seed=seed, statuses=statuses, data=data,
                      assume_tags_since_week_start=True)


def test_the_cache_key_moves_with_every_input_state_hash_misses(monkeypatch, tmp_path):
    box = {"teams": _teams(), "engine": dict(CLEAN)}
    monkeypatch.setattr(rl, "load_all_team_projections", lambda data: box["teams"])
    monkeypatch.setattr(cal, "engine_version", lambda base=".": dict(box["engine"]))
    base = _prepared(tmp_path)
    k0 = rl.cache_key(base, 300)

    def differs(p, label):
        k = rl.cache_key(p, 300)
        assert p.state.state_hash == base.state.state_hash, f"{label}: state_hash moved -- not a test"
        assert k["key"] != k0["key"], f"{label}: the key did not move"

    differs(_prepared(tmp_path, statuses={**TAGS, "B1": "Q"}), "tags")
    stronger = _teams()
    n2 = stronger["Nick"].players["N2"]
    stronger["Nick"].players["N2"] = replace(n2, projected_fppg=n2.projected_fppg + 5)
    box["teams"] = stronger
    differs(_prepared(tmp_path), "projections")
    box["teams"] = _teams()
    differs(_prepared(tmp_path, overrides=[{"player_name": "N2", "out_weeks": [2]}]), "overrides")
    differs(_prepared(tmp_path, seed=6), "seed")
    box["engine"] = {"commit": "def5678", "dirty": False}
    differs(_prepared(tmp_path), "engine commit")
    box["engine"] = dict(CLEAN)
    assert rl.cache_key(base, 301)["key"] != k0["key"], "simulation count"
    assert rl.cache_key(_prepared(tmp_path), 300)["key"] == k0["key"], "the key is not stable"


def test_an_override_that_does_not_govern_this_week_does_not_move_the_key(monkeypatch, tmp_path):
    monkeypatch.setattr(rl, "load_all_team_projections", lambda data: _teams())
    monkeypatch.setattr(cal, "engine_version", lambda base=".": dict(CLEAN))
    k0 = rl.cache_key(_prepared(tmp_path), 300)["key"]
    k1 = rl.cache_key(_prepared(tmp_path, overrides=[{"player_name": "N2", "out_weeks": [9]},
                                                     {"player_name": "Somebody Else", "out_weeks": [2]}]),
                      300)["key"]
    assert k0 == k1


def test_a_dirty_or_unknown_engine_never_serves_a_cached_line(svc):
    svc.box["engine"] = {"commit": "abc1234", "dirty": True}
    svc(MON)
    svc(D[2])
    out = svc(D[2])
    assert out["outcome"] == "priced" and "dirty" in out["why_priced"]
    svc.box["engine"] = {"commit": "abc1234", "dirty": None}
    assert svc(D[2])["outcome"] == "priced"


def test_a_manual_refresh_in_between_is_never_mistaken_for_the_cached_line(svc):
    svc(MON)
    svc(D[2])
    data, _ = _data(through=D[2])
    rl.refresh(svc.tmp, week=2, as_of=D[2], sims=300, data=data, statuses=TAGS)
    out = svc(D[2])
    assert out["outcome"] == "priced" and "manual" in out["why_priced"]


# 3 -- a cleared tag survives in the log
def test_a_cleared_tag_is_recoverable_from_the_log(svc):
    svc(MON, statuses={**TAGS, "B1": "Q"})
    svc(D[2], statuses=TAGS)
    assert "B1" not in json.loads(svc.state())["tags"], "the state file should drop it"
    assert all(e["player"] != "B1" for e in json.loads(svc.line())["tag_events"]
               if e["event"] != "cleared")
    log = ws.read_tag_log(svc.tmp / "output", 2)
    b1 = [e for e in log if e["player"] == "B1"]
    assert [e["event"] for e in b1] == ["baseline", "cleared"]
    assert b1[0]["tag"] == "Q" and b1[0]["anchor"] == MON.isoformat()
    assert b1[1]["as_of"] == D[2].isoformat() and b1[1]["produced_by"].endswith("scheduled")


def test_a_manual_refresh_appends_to_the_same_log(svc):
    data, _ = _data(through=MON)
    rl.refresh(svc.tmp, week=2, as_of=MON, sims=300, data=data, statuses=TAGS)
    log = ws.read_tag_log(svc.tmp / "output", 2)
    assert [e["produced_by"] for e in log] == ["refresh_lines (manual)"]


# 4 -- a failed scheduled run leaves the line and exits non-zero
def test_a_failed_yahoo_fetch_leaves_the_previous_line_and_exits_1(svc, monkeypatch):
    svc(MON)
    good = svc(D[2])
    line, state = svc.line(), svc.state()

    def boom(base):
        raise RuntimeError("Yahoo injury fetch failed (HTTP 503); pass --statuses FILE or --no-tags")
    monkeypatch.setattr(rl, "_fetch_statuses", boom)
    bad = svc(D[3], statuses=None)
    assert bad["exit"] == 1 and bad["outcome"] == "failed" and "Yahoo" in bad["error"]
    assert svc.line() == line and svc.state() == state
    runs = svc.runs()
    assert runs["line_produced_by"] == good["run_id"]
    assert runs["failed_since_line"] == [bad["run_id"]]
    assert "REFUSED" in (svc.tmp / "output" / "refresh_service.log").read_text(encoding="utf-8")
    ok = svc(D[3])
    assert ok["outcome"] == "priced" and svc.runs()["failed_since_line"] == []


def test_the_entry_point_exits_non_zero_on_a_failed_run(monkeypatch):
    monkeypatch.setattr(rs, "run", lambda *a, **k: {"exit": 1})
    assert rs.main(["--trigger", "scheduled"]) == 1
    monkeypatch.setattr(rs, "run", lambda *a, **k: {"exit": 0})
    assert rs.main([]) == 0


def test_a_failed_log_pull_is_a_failed_run(svc):
    svc(MON)
    line = svc.line()

    def puller(d):
        raise rs.LogPullFailed(f"update_fantasy_logs.py --date {d} exited 1: token expired")
    svc.box["data"]["through"] = MON                 # logs stop at Monday: Mon, Tue uncovered
    out = svc(D[2], puller=puller)
    assert out["exit"] == 1 and "LogPullFailed" in out["error"] and svc.line() == line


def test_the_run_pulls_exactly_the_uncovered_days_then_reloads(svc):
    svc.box["data"]["through"] = MON                 # nothing logged yet

    def puller(d):
        svc.box["pulled"].append(d)
        svc.box["data"]["through"] = max(svc.box["data"]["through"], d + (D[1] - D[0]))
    out = svc(D[3], puller=puller, statuses=TAGS)
    assert svc.box["pulled"] == [D[0], D[1], D[2]]
    assert out["outcome"] == "failed" and "TagHistoryMissing" in out["error"]   # no Monday record: B2 refuses
    svc.box["pulled"].clear()
    assert rs.days_to_pull(_data(through=D[3])[0], 2, D[3]) == []


# 5 -- B2's guarantees survive the service
def test_one_seed_per_week_and_unchanged_tags_keep_their_anchor(svc):
    a = svc(MON)
    seed = json.loads(svc.line())["seed"]
    svc(D[3])
    assert json.loads(svc.line())["seed"] == seed
    assert json.loads(svc.state())["tags"]["Nikola Jokić"]["anchor"] == MON.isoformat()
    assert a["outcome"] == "priced"


def test_a_missing_log_day_still_refuses(svc):
    svc(MON)
    svc.box["data"]["through"] = D[1]               # Tuesday never logged
    out = svc(D[3], pull_logs=False)
    assert out["exit"] == 1 and "MissingLogDay" in out["error"]


def test_state_hash_still_means_the_played_state_only(tmp_path, monkeypatch):
    """B3 does not widen it: the tags are not in it."""
    monkeypatch.setattr(rl, "load_all_team_projections", lambda data: _teams())
    a = _prepared(tmp_path, statuses=TAGS).state.state_hash
    b = _prepared(tmp_path, statuses={"B1": "Q"}).state.state_hash
    assert a == b
