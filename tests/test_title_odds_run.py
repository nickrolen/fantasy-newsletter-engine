"""
Step 1c: title odds every night (modules/title_odds_run.py) -- the stakes'
arithmetic, the lock, the outputs, and the pass's week results.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import title_odds_run as tor          # noqa: E402

NAN = np.nan
LA = ZoneInfo("America/Los_Angeles")


def test_leverage_arithmetic_on_known_iterations():
    """P(title | win) - P(title | loss), a T and no game in neither group."""
    won = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0.5, NAN])
    title = np.array([1, 1, 1, 0, 1, 0, 0, 0, 1, 1], bool)
    lv = tor.leverage(won, title)
    assert (lv["n_win"], lv["n_loss"], lv["n_tie"]) == (4, 4, 1)
    assert lv["p_if_win"] == 0.75 and lv["p_if_loss"] == 0.25
    assert lv["leverage"] == pytest.approx(0.5)


def test_a_week_never_lost_has_no_leverage_never_a_made_up_one():
    lv = tor.leverage(np.array([1.0, 1.0, 0.5]), np.array([True, False, True]))
    assert lv["leverage"] is None and lv["n_loss"] == 0 and "never loses" in lv["why"]


def _fake_pass():
    """Two managers, 8 iterations, one regular-season week (3) and one
    bracket week (16), hand-built so every number is known."""
    w3 = np.array([[1, 0], [1, 0], [1, 0], [0, 1], [0, 1], [0, 1], [0.5, 0.5], [1, 0]], float)
    w16 = np.array([[1, 0], [0, 1], [1, 0], [0, 1], [1, 0], [0, 1], [1, 0], [0, 1]], float)
    # regular-season title: A in iterations 0, 1, 2, 6; B otherwise
    reg_first = np.array([0, 0, 0, 1, 1, 1, 0, 1])
    # champion: A in 0, 2, 4; B otherwise
    champ = np.array([0, 1, 0, 1, 0, 1, 1, 1])
    reg_finish = np.stack([reg_first, 1 - reg_first], axis=1)
    playoff_finish = np.stack([champ, 1 - champ], axis=1)
    # margins (task 18b): A's in week 3 are 10, 20, ..., 80 (mean 45), B's the negatives;
    # week 16's are +-5 by the result
    m3 = np.arange(10.0, 90.0, 10.0)
    m16 = np.where(w16[:, 0] == 1, 5.0, -5.0)
    return SimpleNamespace(managers=["A", "B"], regular_weeks=(1, 15), through="playoffs",
                           week_results={3: w3, 16: w16}, reg_finish=reg_finish,
                           week_margins={3: np.stack([m3, -m3], axis=1),
                                         16: np.stack([m16, -m16], axis=1)},
                           playoff_finish=playoff_finish, in_progress={}, data=None)


def test_the_stakes_on_a_hand_built_pass():
    st = tor.stakes(_fake_pass())
    a3 = st["A"]["regular_season"]["3"]
    # A wins week 3 in 0,1,2,7 (title in 0,1,2: 3/4); loses in 3,4,5 (title 0/3); ties in 6
    assert (a3["n_win"], a3["n_loss"], a3["n_tie"]) == (4, 3, 1)
    assert a3["rs_leverage"] == pytest.approx(0.75 - 0.0)
    b3 = st["B"]["regular_season"]["3"]
    # B wins in 3,4,5 (title 3/3); loses in 0,1,2,7 (title in 7: 1/4)
    assert b3["rs_leverage"] == pytest.approx(1.0 - 0.25)
    a16 = st["A"]["playoffs"]["16"]
    # A wins week 16 in 0,2,4,6 (champion 0,2,4: 3/4); loses in 1,3,5,7 (0/4)
    assert a16["playoff_leverage"] == pytest.approx(0.75)
    assert st["B"]["playoffs"]["16"]["playoff_leverage"] == pytest.approx(1.0 - 0.25)
    assert "16" not in st["A"]["regular_season"] and "3" not in st["A"]["playoffs"]
    # schema 2 (task 18b): margins over the iterations with a game; title and champion odds
    assert a3["margin_mean"] == pytest.approx(45.0)
    assert a3["margin_sd"] == pytest.approx(float(np.arange(10.0, 90.0, 10.0).std()))
    assert b3["margin_mean"] == pytest.approx(-45.0)
    assert (a16["margin_mean"], a16["margin_sd"]) == (pytest.approx(0.0), pytest.approx(5.0))
    assert st["A"]["rs_title"] == 0.5 and st["A"]["champion"] == 3 / 8
    assert st["B"]["rs_title"] == 0.5 and st["B"]["champion"] == 5 / 8


def test_margins_are_recorded_beside_results_and_never_drawn(real_pass):
    """Each week's margin agrees in sign with its result, and a week with no
    game has neither (task 18b)."""
    sp = real_pass
    assert set(sp.week_margins) == set(sp.week_results)
    for w, res in sp.week_results.items():
        marg = sp.week_margins[w]
        assert np.array_equal(np.isnan(res), np.isnan(marg)), w
        ok = ~np.isnan(res)
        assert ((marg[ok] > 0) == (res[ok] == 1.0)).all() and ((marg[ok] < 0) == (res[ok] == 0.0)).all(), w


def test_price_refuses_while_locked_and_writes_nothing(tmp_path, monkeypatch):
    from modules import price_lock
    monkeypatch.setattr(price_lock, "status", lambda now=None, schedule=None: {
        "locked": True, "first_tip": "2026-11-04T16:00-08:00", "league_day": "2026-11-04",
        "now": "x"})
    called = []
    monkeypatch.setattr(tor, "run_pass", lambda *a, **k: called.append(1))
    with pytest.raises(tor.TitleOddsLocked):
        tor.price(tmp_path, SimpleNamespace(nba_schedule={}), seed=1, sims=10, statuses={},
                  run_id="r", produced_by="t", kind="nightly", week=3,
                  now=datetime(2026, 11, 4, 17, 0, tzinfo=LA))
    assert called == [] and not any(tmp_path.rglob("*"))


def test_every_output_is_league_state_and_never_scored():
    from modules import state_manifest as sm
    man = sm.load(ROOT)
    for p in (tor.LATEST_FILE, tor.STAKES_FILE):
        assert man.contains(p.as_posix()), p


@pytest.fixture(scope="module")
def real_pass():
    if not (ROOT / "config" / "RECORDS.json").exists() or not (ROOT / "data" / "IL_SLOTS.json").exists():
        pytest.skip("league state not in this checkout")
    from modules.data_loader import load_all_data
    from modules.fetch_injury_statuses import Tags
    from modules.roster_plan import ILSlotsError
    try:
        data = load_all_data(ROOT, current_week=None)
        return tor.run_pass(data, seed=20262027, sims=600, statuses=Tags.none())
    except ILSlotsError as e:
        pytest.skip(f"the real IL file is not current ({e})")


def test_the_pass_week_results_are_the_seasons_own(real_pass):
    """Recorded, never drawn: each iteration's regular-season wins equal the
    league's wins plus the weeks week_results says it won."""
    sp = real_pass
    for j, m in enumerate(sp.managers):
        won = sum((sp.week_results[w][:, j] == 1.0) for w in sp.week_results if w <= sp.regular_weeks[1])
        assert np.array_equal(won + sp.current_records[m].wins, sp.reg_wins[:, j]), m
    # every bracket week a manager plays has a result; a week he sits out has none
    for w in sp.week_results:
        if w > sp.regular_weeks[1]:
            played = ~np.isnan(sp.week_results[w])
            assert (played.sum(axis=1) == 4).all()          # two series a week, both sides


def test_record_writes_the_row_the_latest_file_and_the_stakes(tmp_path, real_pass, monkeypatch):
    from modules import calibration_log as cal, title_odds_history as toh
    monkeypatch.setattr(cal, "engine_version", lambda base=".": {"commit": "abc1234", "dirty": False})
    out = tor.record(tmp_path, real_pass, run_id="r1", produced_by="test", kind="nightly", week=3,
                     as_of=datetime(2026, 11, 4, 0, 1, tzinfo=LA))
    row = toh.read(tmp_path)[0]
    latest = tor.load_latest(tmp_path)
    stakes = json.loads((tmp_path / tor.STAKES_FILE).read_text(encoding="utf-8"))
    assert row["title_odds"] == latest["title_odds"] and row["kind"] == "nightly"
    assert row["expected_record"] == latest["expected_record"]
    assert latest["playoff_odds"] and latest["cup_odds"]
    assert (latest["seed"], latest["num_simulations"], latest["as_of"]) == \
        (20262027, 600, "2026-11-04T00:01:00-08:00")
    assert stakes["run_id"] == latest["run_id"] == "r1"
    assert stakes["schema"] == tor.STAKES_SCHEMA == 2 and stakes["season"] == "2026-27"
    assert set(stakes["teams"]) == set(latest["title_odds"])
    with pytest.raises(toh.HistoryCorrupt):          # a repeated run id: nothing more written
        tor.record(tmp_path, real_pass, run_id="r1", produced_by="test", kind="nightly", week=3)


# =============================================================================
# the hub reads the latest run, and refuses one that no longer fits the standings
# =============================================================================

def _latest_world(tmp_path, records, after_banked):
    from modules import title_odds_history as toh
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    blob = {"schema": 1, "run_id": "r2", "kind": "nightly", "produced_by": "t",
            "as_of": "2026-11-09T00:01:00-08:00", "week": 4, "pass_current_week": 3, "seed": 1,
            "num_simulations": 10, "through": "cup",
            "records": records, "records_after_banked": after_banked, "in_progress": {},
            "title_odds": {"A": 70.0, "B": 30.0}, "expected_record": {"A": [9, 6, 0], "B": [6, 9, 0]},
            "finish_distribution": {"A": {"1": 70.0, "2": 30.0}, "B": {"1": 30.0, "2": 70.0}},
            "magic_numbers": {}, "playoff_odds": None, "playoff_finish_distribution": None,
            "cup_odds": None}
    (tmp_path / tor.LATEST_FILE).write_text(json.dumps(blob), encoding="utf-8")
    for rid, odds in (("r1", {"A": 60.0, "B": 40.0}), ("r2", {"A": 70.0, "B": 30.0})):
        toh.append(tmp_path, {"run_id": rid, "produced_by": "t", "as_of": "2026-11-08T00:01:00-08:00",
                              "engine": {"commit": "c", "dirty": False}, "engine_key": "c", "seed": 1,
                              "num_simulations": 10, "title_odds": odds})


def test_the_hub_reads_the_latest_run_and_its_change_since_the_row_before(tmp_path):
    from modules import hub_state as hs
    from modules.data_loader import Record
    _latest_world(tmp_path, {"A": "2-0", "B": "0-2"}, {"A": "3-0", "B": "0-3"})
    data = SimpleNamespace(get_manager_record=lambda m: {"A": Record(2, 0), "B": Record(0, 2)}[m])
    tor_, latest, prev = hs.title_odds_inputs(tmp_path, data, ["A", "B"])
    assert tor_.title_odds == {"A": 70.0, "B": 30.0} and tor_.expected_record["A"] == (9.0, 6.0, 0.0)
    assert prev["run_id"] == "r1"
    # a Monday 12:01 AM run, before the weekly build records the week it banked: accepted
    data = SimpleNamespace(get_manager_record=lambda m: {"A": Record(3, 0), "B": Record(0, 3)}[m])
    hs.title_odds_inputs(tmp_path, data, ["A", "B"])
    # records the run never saw: refused
    data = SimpleNamespace(get_manager_record=lambda m: {"A": Record(2, 1), "B": Record(1, 2)}[m])
    with pytest.raises(hs.HubInputError, match="records moved"):
        hs.title_odds_inputs(tmp_path, data, ["A", "B"])


def test_the_hub_prints_the_runs_banked_records_f5(tmp_path):
    """F5 (11-10): the hub's W-L is the latest run's records_after_banked, so a
    Monday 12:01 AM run shows the finished week before RECORDS has it."""
    import inspect
    from modules import hub_state as hs
    latest = {"run_id": "r2", "records": {"A": "2-0", "B": "0-2"},
              "records_after_banked": {"A": "3-0", "B": "0-3"}}
    assert hs.shown_record(latest, "A") == "3-0" and hs.shown_record(latest, "B") == "0-3"
    with pytest.raises(hs.HubInputError, match="records_after_banked"):
        hs.shown_record({"run_id": "r9", "records_after_banked": {}}, "A")
    assert '"record": shown_record(latest, m)' in inspect.getsource(hs.build_power)
