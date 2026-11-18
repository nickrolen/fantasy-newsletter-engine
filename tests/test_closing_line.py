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
import sim_counts                                       # noqa: E402

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
    cl.capture_il_at_close(tmp_path, 3, CLOSE)       # H52: the closing run's sync keeps it
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


@pytest.mark.slow
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


@pytest.mark.slow
def test_a_naive_fetch_stamp_refuses_rather_than_guess_its_zone(tmp_path):
    data = _inputs(tmp_path, fetched=datetime(2026, 11, 2, 6, 46))
    with pytest.raises(cl.ClosingRefused, match="no time zone"):
        cl.check_inputs(tmp_path, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE)


# =============================================================================
# H51: the projections as at the first tip, from the engine's pre-tip copy
# =============================================================================

WEEK = 3


def _write_pl(path, fetched, fppg=30.0):
    from modules import playerlist_freshness
    path.parent.mkdir(parents=True, exist_ok=True)
    playerlist_freshness.write(pd.DataFrame({
        "player_name": ["A"], "player_nba_team": ["AAA"], "player_position(s)": ["PG"],
        "player_total_proj_FP": [2400.0], "player_proj_GP": [80], "projectedFPPG": [fppg]}),
        path, source="test", now=fetched)


def test_a_post_tip_live_playerlist_with_a_pre_tip_copy_prices_on_the_copy(tmp_path):
    """11-16: Step 4.75 refetched at 6:28 PM, after the 4 PM tip. The copy the
    last pre-tip run kept is what the close prices on, and the check passes."""
    data = _inputs(tmp_path, fetched=datetime(2026, 11, 2, 18, 28, tzinfo=LA))
    _write_pl(cl.pretip_playerlist_path(tmp_path, WEEK), datetime(2026, 11, 2, 15, 3, tzinfo=LA))
    got = cl.playerlist_at_tip(tmp_path, WEEK, FIRST_TIP)
    assert got["source"] == "pretip copy" and got["rel"] == "config/snapshots/pretip/PLAYERLIST_week03.xlsx"
    info = cl.check_inputs(tmp_path, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE, week=WEEK)
    assert info["playerlist"] == got["rel"] and info["playerlist_fetched"] < FIRST_TIP


def test_a_post_tip_live_playerlist_with_no_pre_tip_copy_refuses(tmp_path):
    data = _inputs(tmp_path, fetched=datetime(2026, 11, 2, 18, 28, tzinfo=LA))
    with pytest.raises(cl.ClosingRefused, match="after Monday's first tip.*no pre-tip copy"):
        cl.check_inputs(tmp_path, data, monday=MONDAY, first_tip=FIRST_TIP, close=CLOSE, week=WEEK)


def test_the_copys_stamp_is_checked(tmp_path):
    """A copy fetched after the tip, or one whose rows no longer match its
    stamp, refuses: it cannot vouch for the projections at the tip."""
    _inputs(tmp_path, fetched=datetime(2026, 11, 2, 18, 28, tzinfo=LA))
    copy = cl.pretip_playerlist_path(tmp_path, WEEK)
    _write_pl(copy, datetime(2026, 11, 2, 16, 5, tzinfo=LA))
    with pytest.raises(cl.ClosingRefused, match="a pre-tip copy must be from before the tip"):
        cl.playerlist_at_tip(tmp_path, WEEK, FIRST_TIP)
    _write_pl(copy, datetime(2026, 11, 2, 15, 3, tzinfo=LA))
    from modules.playerlist_freshness import DATA_SHEET, STAMP_SHEET
    sheets = pd.read_excel(copy, sheet_name=None)
    sheets[DATA_SHEET].loc[0, "projectedFPPG"] = 99.0          # a hand edit after the fetch
    with pd.ExcelWriter(copy, engine="openpyxl") as xw:
        for name in (DATA_SHEET, STAMP_SHEET):
            sheets[name].to_excel(xw, sheet_name=name, index=False)
    with pytest.raises(cl.ClosingRefused, match="does not describe its rows"):
        cl.playerlist_at_tip(tmp_path, WEEK, FIRST_TIP)


def test_the_latest_fetch_before_the_tip_wins(tmp_path):
    """Both before the tip: a manual fetch at 3:50 PM after the last pre-tip
    run (3:45) is the projections at the tip, so the live file is read."""
    _inputs(tmp_path, fetched=datetime(2026, 11, 2, 15, 50, tzinfo=LA))
    _write_pl(cl.pretip_playerlist_path(tmp_path, WEEK), datetime(2026, 11, 2, 15, 3, tzinfo=LA))
    assert cl.playerlist_at_tip(tmp_path, WEEK, FIRST_TIP)["source"] == "live"


def _capture_world(tmp_path, monkeypatch):
    from modules import data_loader, price_lock
    monkeypatch.setattr(data_loader, "load_schedule", lambda p: {"weeks": [
        {"week": WEEK, "start_date": MONDAY.isoformat(), "end_date": "2026-11-08"}]})
    monkeypatch.setattr(data_loader, "load_nba_schedule", lambda p, today=None: {"games": []})
    monkeypatch.setattr(price_lock, "first_tip", lambda day, sched=None: FIRST_TIP if day == MONDAY else None)


def test_the_pre_tip_runs_keep_the_copy_and_nothing_after_the_tip_touches_it(tmp_path, monkeypatch):
    _capture_world(tmp_path, monkeypatch)
    live = tmp_path / "data" / "PLAYERLIST.xlsx"
    copy = cl.pretip_playerlist_path(tmp_path, WEEK)
    _write_pl(live, datetime(2026, 11, 2, 0, 7, tzinfo=LA))
    # Sunday: not a window day
    assert "not a window day" in cl.capture_pretip_playerlist(tmp_path, datetime(2026, 11, 1, 23, 0, tzinfo=LA))
    assert not copy.exists()
    # the 12:05 AM nightly, then the 3:03 PM fetch and the 3:30 pre-tip run
    assert "-> config/snapshots/pretip/PLAYERLIST_week03.xlsx" in cl.capture_pretip_playerlist(
        tmp_path, datetime(2026, 11, 2, 0, 8, tzinfo=LA))
    _write_pl(live, datetime(2026, 11, 2, 15, 3, tzinfo=LA), fppg=31.0)
    cl.capture_pretip_playerlist(tmp_path, datetime(2026, 11, 2, 15, 30, tzinfo=LA))
    kept = copy.read_bytes()
    assert copy.read_bytes() == live.read_bytes()
    # a restored older file before the tip never moves the copy backwards
    _write_pl(live, datetime(2026, 11, 2, 0, 7, tzinfo=LA))
    assert "already holds" in cl.capture_pretip_playerlist(tmp_path, datetime(2026, 11, 2, 15, 45, tzinfo=LA))
    assert copy.read_bytes() == kept
    # Step 4.75 at 6:28 PM, and any run after the tip: the copy stands
    _write_pl(live, datetime(2026, 11, 2, 18, 28, tzinfo=LA), fppg=40.0)
    assert "after the first tip" in cl.capture_pretip_playerlist(tmp_path, datetime(2026, 11, 2, 18, 30, tzinfo=LA))
    assert copy.read_bytes() == kept
    got = cl.playerlist_at_tip(tmp_path, WEEK, FIRST_TIP)
    assert got["source"] == "pretip copy" and got["fetched_at"] == datetime(2026, 11, 2, 15, 3, tzinfo=LA)


def test_a_live_file_fetched_after_the_tip_is_never_copied(tmp_path, monkeypatch):
    """A run before the tip that finds a post-tip stamp (a clock or a restore
    gone wrong) copies nothing rather than vouch for it."""
    _capture_world(tmp_path, monkeypatch)
    _write_pl(tmp_path / "data" / "PLAYERLIST.xlsx", datetime(2026, 11, 2, 16, 30, tzinfo=LA))
    assert "not copied" in cl.capture_pretip_playerlist(tmp_path, datetime(2026, 11, 2, 15, 30, tzinfo=LA))
    assert not cl.pretip_playerlist_path(tmp_path, WEEK).exists()


def test_every_run_that_records_tags_keeps_the_copy():
    """The capture sits beside both tag-record writers in the nightly, so a
    nightly, pre-tip, poll, refresh or afternoon run on the Monday keeps it."""
    import inspect
    from modules import nightly
    for step in ("step_tags", "step_nba_report"):
        src = inspect.getsource(getattr(nightly.Run, step))
        assert src.count("tag_records.append(") == src.count("_capture_pretip_playerlist()") == 1, step


# =============================================================================
# the real league, week 3 (state-dependent)
# =============================================================================

def _real_or_skip():
    need = [ROOT / "config" / "RECORDS.json", ROOT / "data" / "IL_SLOTS.json",
            ROOT / "output" / "live_lines_week3.state.json", ROOT / "output" / tr.RECORD_FILE.name]
    if not all(p.exists() for p in need):
        pytest.skip("league state (and a tag record) not in this checkout")


def real_pins(mp):
    """H52: the IL slots as at the close and the stakes as at the tip, stated:
    the live files stand in for the copies the closing run and the pre-tip
    runs keep (those are tests/test_h52_closing_at_close.py's business)."""
    il_blob = json.loads((ROOT / "data" / "IL_SLOTS.json").read_text(encoding="utf-8"))
    st = ROOT / "output" / "stakes.json"
    st_at = datetime.fromisoformat(json.loads(st.read_text(encoding="utf-8"))["as_of"])
    mp.setattr(cl, "il_at_close", lambda base, week, close: {
        "blob": il_blob, "rel": "data/IL_SLOTS.json",
        "fetched_at": datetime.fromisoformat(il_blob["fetched_at"])})
    mp.setattr(cl, "stakes_at_tip", lambda base, week, first: {
        "path": st, "rel": "output/stakes.json", "as_of": st_at, "source": "live"})


@pytest.mark.slow
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
    # H51: the live file stands in for the projections at the tip (the input
    # checks, the pre-tip copy included, are the unit tests' business above)
    live = {"path": ROOT / "data" / "PLAYERLIST.xlsx", "rel": "data/PLAYERLIST.xlsx",
            "fetched_at": datetime(2026, 11, 2, 6, 46, tzinfo=LA), "source": "live"}
    mp.setattr(cl, "playerlist_at_tip", lambda *a, **k: dict(live))
    real_pins(mp)
    sim_counts.small(mp)     # the roster plan's long-run sims: paths, not counts (tests/sim_counts.py)
    out = tmp_path_factory.mktemp("closing")
    try:
        # H52: the cloud's closing run (Monday 7 PM, after week 3's 18:55 close) and
        # the 12:05 AM nightly's retry price the same bytes: the plan's clock is the
        # close, never the run's (a day apart, they used to anchor a day apart)
        now = datetime(2026, 11, 2, 19, 0, tzinfo=LA)
        first = cl.price(ROOT, 3, now=now, sims=400, title_sims=400, out_base=out)
        body1 = cl.closing_path(out, 3).read_bytes()
        files1 = {p.name: p.read_bytes() for p in out.rglob("*") if p.is_file()}
        second = cl.price(ROOT, 3, now=datetime(2026, 11, 3, 0, 5, tzinfo=LA), sims=400,
                          title_sims=400, out_base=out)
        files2 = {p.name: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    except ILSlotsError as e:
        pytest.skip(f"the real IL file is not current ({e})")
    finally:
        mp.undo()
    return {"first": first, "second": second, "body": body1, "files1": files1, "files2": files2,
            "out": out, "tags": tr.as_tags(real_row)}


@pytest.mark.slow
def test_the_second_run_is_byte_identical(priced_twice):
    assert priced_twice["first"]["outcome"] == "priced"
    assert priced_twice["second"]["outcome"] == "unchanged"
    assert priced_twice["files1"] == priced_twice["files2"]


@pytest.mark.slow
def test_no_monday_result_is_banked_and_it_is_priced_as_at_the_close(priced_twice):
    line = priced_twice["first"]["line"]
    assert line["completed_dates"] == [] and line["as_of"] == "2026-11-02"
    assert line["generated_at"] == line["closing"]["window_close"]
    assert line["kind"] == "closing"
    assert all(ln["banked_a"] == 0 and ln["banked_b"] == 0 for ln in line["lines"])
    seed = json.loads((ROOT / "output" / "live_lines_week3.state.json").read_text(encoding="utf-8"))["seed"]
    assert line["seed"] == seed                      # the week's seed


@pytest.mark.slow
def test_its_records_are_closing_records_at_the_close(priced_twice):
    from modules import calibration_log as cal
    recs = cal.load_log(priced_twice["out"])["lines"]
    assert len(recs) == 2 and {r["source"] for r in recs} == {cal.CLOSING}
    assert {r["as_of"] for r in recs} == {priced_twice["first"]["line"]["closing"]["window_close"]}


@pytest.mark.slow
def test_title_odds_at_the_close_use_the_same_inputs(priced_twice, monkeypatch):
    sim_counts.small(monkeypatch)                  # as the fixture priced it
    from modules import title_odds_run as tor
    from modules.data_loader import load_all_data
    row = priced_twice["first"]["row"]
    assert (row["kind"], row["run_id"], row["as_of"]) == \
        ("closing", "closing-week3", priced_twice["first"]["line"]["closing"]["window_close"])
    data = cl.pre_close_data(ROOT, MONDAY, load_all_data(ROOT, current_week=None))
    # pre_close_data cuts the logs, not RECORDS: in production the close is
    # priced on Tuesday of its own week, before the weekly build records it.
    # Once the real RECORDS hold week 3 (the 11-09 weekly build), re-pricing
    # week 3's close from disk can't be "as at the close" any more (11-10).
    if int((data.records or {}).get("last_updated_week") or 0) >= 3:
        pytest.skip("the real RECORDS already hold week 3's result: its close can't be re-priced from disk")
    sp = tor.run_pass(data, seed=priced_twice["first"]["line"]["seed"], sims=400,
                      statuses=priced_twice["tags"])
    assert 3 not in sp.in_progress and 3 in sp.simulated_weeks        # nothing of Monday banked
    assert tor.readouts(sp)["title_odds"] == row["title_odds"]


def test_tags_follow_the_rosters_as_at_the_close():
    """11-17: week 5's close refused (UnresolvedTagName) because Murray and Mobley, both O in
    the pre-tip record, were dropped between the pre-tip run and the close. A player who left
    a roster takes his tag to the free agents; one who joined takes his from them; the tags
    themselves stay as at the tip."""
    tags = Tags({"Stays": "Q", "Dropped Star": "O", "Dropped Bench": "HEALTHY"},
                {"Added Guy": "D", "Still Free": "O"}, nba_outs={"Dropped Star": "2026-11-16",
                                                                  "Stays": "2026-11-16"})
    out, left, joined = cl.align_to_close(tags, ["Stays", "Added Guy", "Other"])
    assert dict(out) == {"Stays": "Q", "Added Guy": "D"}
    assert dict(out.free_agents) == {"Still Free": "O", "Dropped Star": "O", "Dropped Bench": "HEALTHY"}
    assert left == ["Dropped Bench", "Dropped Star"] and joined == ["Added Guy"]
    assert dict(out.nba_outs) == {"Stays": "2026-11-16"}
    # nothing moved: the same tags back
    same, l2, j2 = cl.align_to_close(Tags({"A": "O"}, {"B": "Q"}), ["A"])
    assert dict(same) == {"A": "O"} and dict(same.free_agents) == {"B": "Q"} and l2 == j2 == []
