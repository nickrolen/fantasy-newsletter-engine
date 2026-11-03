"""
Step 1c: the closing line (modules/closing_line.py) -- the official line
(Nick, 11-03). HANDOFF_STEP1C1 s.5's tests and invariant 8:
  - it uses a 4:30 PM roster change (a transaction before the close) and
    refuses a transaction after the close;
  - it ignores a tag change at 6 PM (after the first tip): its tags are the
    latest record taken on Monday before the first tip;
  - it refuses before the close, and with no pre-tip tag record;
  - title odds at the close use the same inputs;
  - a second run is byte-identical; its calibration records are source
    "closing" (scored; tests/test_calibration_log.py pins the scoring).
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import closing_line as cl, tag_records as tr          # noqa: E402
from modules.fetch_injury_statuses import Tags                     # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
MONDAY = date(2026, 11, 2)
FIRST_TIP = datetime(2026, 11, 2, 16, 0, tzinfo=LA)
CLOSE = datetime(2026, 11, 2, 19, 25, tzinfo=LA)


def _tags(rostered):
    return Tags(rostered, {"Free Agent": "HEALTHY"})


def test_the_tags_are_mondays_before_the_first_tip_and_a_6pm_change_is_ignored(tmp_path):
    tr.append(tmp_path, _tags({"Star": "HEALTHY"}), run_id="sun", mode="nightly", week=2,
              now=datetime(2026, 11, 1, 0, 1, tzinfo=LA))
    tr.append(tmp_path, _tags({"Star": "Q"}), run_id="mon-0001", mode="nightly", week=3,
              now=datetime(2026, 11, 2, 0, 1, tzinfo=LA))
    tr.append(tmp_path, _tags({"Star": "O"}), run_id="mon-pretip", mode="pretip", week=3,
              now=datetime(2026, 11, 2, 15, 30, tzinfo=LA))
    tr.append(tmp_path, _tags({"Star": "HEALTHY"}), run_id="mon-6pm", mode="pretip", week=3,
              now=datetime(2026, 11, 2, 18, 0, tzinfo=LA))
    row = tr.for_close(tmp_path, MONDAY, FIRST_TIP)
    assert row["run_id"] == "mon-pretip" and dict(tr.as_tags(row)) == {"Star": "O"}
    # with no pre-tip run, the 12:01 AM run's record
    other = tmp_path / "b"
    tr.append(other, _tags({"Star": "Q"}), run_id="mon-0001", mode="nightly", week=3,
              now=datetime(2026, 11, 2, 0, 1, tzinfo=LA))
    assert tr.for_close(other, MONDAY, FIRST_TIP)["run_id"] == "mon-0001"


def test_no_pre_tip_record_refuses(tmp_path):
    tr.append(tmp_path, _tags({"Star": "O"}), run_id="tue", mode="nightly", week=3,
              now=datetime(2026, 11, 3, 0, 1, tzinfo=LA))
    with pytest.raises(tr.NoPretipTags, match="no tag record was taken on 2026-11-02"):
        tr.for_close(tmp_path, MONDAY, FIRST_TIP)


def test_a_tag_record_must_carry_the_free_agents(tmp_path):
    with pytest.raises(tr.TagRecordError, match="free agents"):
        tr.append(tmp_path, Tags({"Star": "O"}, None), run_id="x", mode="nightly", week=3,
                  now=datetime(2026, 11, 2, 0, 1, tzinfo=LA))


# =============================================================================
# the inputs, against the close
# =============================================================================

def _inputs(tmp_path, *, synced=datetime(2026, 11, 3, 0, 1, tzinfo=LA),
            fetched=datetime(2026, 11, 2, 6, 46, tzinfo=LA), txn_times=()):
    from modules import playerlist_freshness, transaction_log as tlog
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "config" / "ROSTERS.json").write_text(
        json.dumps({"rosters": {}, "_last_sync": synced.isoformat(timespec="seconds")}), encoding="utf-8")
    (tmp_path / "data" / "IL_SLOTS.json").write_text(
        json.dumps({"fantasy_week": 3, "slots": {}, "fetched_at": synced.isoformat(timespec="seconds")}),
        encoding="utf-8")
    playerlist_freshness.write(pd.DataFrame({
        "player_name": ["A"], "player_nba_team": ["AAA"], "player_position(s)": ["PG"],
        "player_total_proj_FP": [2400.0], "player_proj_GP": [80], "projectedFPPG": [30.0]}),
                               tmp_path / "data" / "PLAYERLIST.xlsx", source="test", now=fetched)
    raws = []
    for i, t in enumerate(txn_times):
        raws.append({"transaction_key": f"k.{i}", "transaction_id": str(i), "type": "add",
                     "status": "successful", "timestamp": str(int(t.timestamp())),
                     "players": {"count": 1, "0": {"player": [
                         [{"player_key": f"p.{i}"}, {"name": {"full": f"Pickup {i}"}}],
                         {"transaction_data": [{"type": "add", "source_type": "freeagents",
                                                "destination_type": "team",
                                                "destination_team_name": "Blink-183"}]}]}}})
    tlog.sync(tmp_path, raws, manager_of=lambda n, k: "Garrett", week_of=lambda d: 3, run_id="t",
              now=synced)
    from types import SimpleNamespace
    return SimpleNamespace(injury_overrides={"last_updated": "2026-11-02", "players": []})


def test_a_430pm_roster_change_is_used_and_a_move_after_the_close_refuses(tmp_path):
    data = _inputs(tmp_path, txn_times=[datetime(2026, 11, 2, 16, 30, tzinfo=LA)])
    info = cl.check_inputs(tmp_path, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE)
    assert info["rosters_synced"] >= CLOSE          # rosters as at the close, the 4:30 PM move in them
    late = tmp_path / "late"
    late.mkdir()
    data = _inputs(late, txn_times=[datetime(2026, 11, 2, 16, 30, tzinfo=LA),
                                    datetime(2026, 11, 2, 20, 0, tzinfo=LA)])
    with pytest.raises(cl.ClosingRefused, match="after the window closed.*Pickup 1.*rule 4"):
        cl.check_inputs(late, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE)


def test_rosters_synced_before_the_close_refuse(tmp_path):
    data = _inputs(tmp_path, synced=datetime(2026, 11, 2, 12, 0, tzinfo=LA))
    with pytest.raises(cl.ClosingRefused, match="before the close"):
        cl.check_inputs(tmp_path, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE)


def test_projections_fetched_after_the_first_tip_refuse(tmp_path):
    data = _inputs(tmp_path, fetched=datetime(2026, 11, 2, 17, 0, tzinfo=LA))
    with pytest.raises(cl.ClosingRefused, match="after Monday's first tip"):
        cl.check_inputs(tmp_path, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE)


def test_a_naive_fetch_stamp_refuses_rather_than_guess_its_zone(tmp_path):
    data = _inputs(tmp_path, fetched=datetime(2026, 11, 2, 6, 46))
    with pytest.raises(cl.ClosingRefused, match="no time zone"):
        cl.check_inputs(tmp_path, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE)


# =============================================================================
# the real league, week 3 (state-dependent)
# =============================================================================

def _real_or_skip():
    need = [ROOT / "config" / "RECORDS.json", ROOT / "data" / "IL_SLOTS.json",
            ROOT / "output" / "live_lines_week3.state.json", ROOT / "output" / tr.RECORD_FILE.name]
    if not all(p.exists() for p in need):
        pytest.skip("league state (and a tag record) not in this checkout")


def test_it_refuses_before_the_close():
    _real_or_skip()
    with pytest.raises(cl.ClosingRefused, match="closes"):
        cl.price(ROOT, 3, now=datetime(2026, 11, 2, 12, 0, tzinfo=LA), write=False)


@pytest.fixture(scope="module")
def priced_twice(tmp_path_factory):
    """Week 3's closing line priced into a scratch folder, twice. The tags are
    the latest real record, standing in for Monday's pre-tip record (none was
    taken on 11-02: the record began with step 1c); the input checks are the
    unit tests' business above."""
    _real_or_skip()
    from modules.data_loader import load_all_data
    from modules.roster_plan import ILSlotsError
    real_row = tr.latest(ROOT)
    mp = pytest.MonkeyPatch()
    mp.setattr(tr, "for_close", lambda base, monday, first: dict(real_row, league_day="2026-11-02"))
    mp.setattr(cl, "check_inputs", lambda *a, **k: {"overrides_last_updated": "x"})
    out = tmp_path_factory.mktemp("closing")
    try:
        now = datetime(2026, 11, 3, 9, 0, tzinfo=LA)
        first = cl.price(ROOT, 3, now=now, sims=400, title_sims=400, out_base=out)
        body1 = cl.closing_path(out, 3).read_bytes()
        files1 = {p.name: p.read_bytes() for p in out.rglob("*") if p.is_file()}
        second = cl.price(ROOT, 3, now=datetime(2026, 11, 3, 23, 0, tzinfo=LA), sims=400,
                          title_sims=400, out_base=out)
        files2 = {p.name: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    except ILSlotsError as e:
        pytest.skip(f"the real IL file is not current ({e})")
    finally:
        mp.undo()
    return {"first": first, "second": second, "body": body1, "files1": files1, "files2": files2,
            "out": out, "tags": tr.as_tags(real_row)}


def test_the_second_run_is_byte_identical(priced_twice):
    assert priced_twice["first"]["outcome"] == "priced"
    assert priced_twice["second"]["outcome"] == "unchanged"
    assert priced_twice["files1"] == priced_twice["files2"]


def test_no_monday_result_is_banked_and_it_is_priced_as_at_the_close(priced_twice):
    line = priced_twice["first"]["line"]
    assert line["completed_dates"] == [] and line["as_of"] == "2026-11-02"
    assert line["generated_at"] == line["closing"]["window_close"]
    assert line["kind"] == "closing"
    assert all(ln["banked_a"] == 0 and ln["banked_b"] == 0 for ln in line["lines"])
    seed = json.loads((ROOT / "output" / "live_lines_week3.state.json").read_text(encoding="utf-8"))["seed"]
    assert line["seed"] == seed                      # the week's seed


def test_its_records_are_closing_records_at_the_close(priced_twice):
    from modules import calibration_log as cal
    recs = cal.load_log(priced_twice["out"])["lines"]
    assert len(recs) == 2 and {r["source"] for r in recs} == {cal.CLOSING}
    assert {r["as_of"] for r in recs} == {priced_twice["first"]["line"]["closing"]["window_close"]}


def test_title_odds_at_the_close_use_the_same_inputs(priced_twice):
    from modules import title_odds_run as tor
    from modules.data_loader import load_all_data
    row = priced_twice["first"]["row"]
    assert (row["kind"], row["run_id"], row["as_of"]) == \
        ("closing", "closing-week3", priced_twice["first"]["line"]["closing"]["window_close"])
    data = cl.pre_close_data(ROOT, MONDAY, load_all_data(ROOT, current_week=None))
    sp = tor.run_pass(data, seed=priced_twice["first"]["line"]["seed"], sims=400,
                      statuses=priced_twice["tags"])
    assert 3 not in sp.in_progress and 3 in sp.simulated_weeks        # nothing of Monday banked
    assert tor.readouts(sp)["title_odds"] == row["title_odds"]
