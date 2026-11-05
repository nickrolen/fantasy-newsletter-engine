"""
Step 1c: the transaction log (modules/transaction_log.py), the nightly sync
(sync_transactions.nightly_sync) and the hub's moves feed.

Invariants (HANDOFF_STEP1C1 s.7):
  4. the transaction log never duplicates or rewrites a row;
  5. the nightly sync never rewrites a finished week's adds file.
Plus: a drop and a trade land with Pacific times, and a Sunday 23:30 Pacific
transaction lands on Sunday whatever the machine's clock.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import transaction_log as tlog            # noqa: E402
from modules.jsonl_log import LogCorrupt               # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
TEAMS = {"Luka my Balls": "Nick", "Big Nik Energy": "Hayden", "Spayed for Cade": "Benton",
         "Blink-183": "Garrett"}
SCHEDULE = {"weeks": [
    {"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01", "matchups": []},
    {"week": 3, "start_date": "2026-11-02", "end_date": "2026-11-08", "matchups": []},
    {"week": 4, "start_date": "2026-11-09", "end_date": "2026-11-15", "matchups": []}]}


def _week_of(d):
    from modules.transaction_rulings import week_of
    return week_of(d.isoformat(), SCHEDULE)


def _manager_of(name, key):
    return TEAMS[name]


def _ts(y, mo, d, h, mi) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=LA).timestamp())


def _player(name, pid, action, src=None, dst=None):
    td = {"type": action}
    if src:
        td.update(source_type="team", source_team_name=src, source_team_key=f"k.{src}")
    else:
        td.update(source_type="freeagents")
    if dst:
        td.update(destination_type="team", destination_team_name=dst, destination_team_key=f"k.{dst}")
    else:
        td.update(destination_type="freeagents")
    return {"player": [[{"player_key": f"p.{pid}"}, {"player_id": str(pid)},
                        {"name": {"full": name}}], {"transaction_data": [td]}]}


def raw(tid, ts, kind, *players):
    blob = {"transaction_key": f"478.l.1.tr.{tid}", "transaction_id": str(tid), "type": kind,
            "status": "successful", "timestamp": str(ts), "players": {"count": len(players)}}
    for i, p in enumerate(players):
        blob["players"][str(i)] = p
    return blob


ADD = raw(1, _ts(2026, 11, 2, 11, 18), "add", _player("Davion Mitchell", 1, "add", dst="Spayed for Cade"))
ADD_DROP = raw(2, _ts(2026, 11, 2, 6, 12), "add/drop",
               _player("Miles Bridges", 2, "add", dst="Luka my Balls"),
               _player("Ty Jerome", 3, "drop", src="Luka my Balls"))
DROP = raw(3, _ts(2026, 11, 3, 9, 5), "drop", _player("Kawhi Leonard", 4, "drop", src="Big Nik Energy"))
TRADE = raw(4, _ts(2026, 11, 4, 20, 45), "trade",
            _player("Jayson Tatum", 5, "trade", src="Spayed for Cade", dst="Big Nik Energy"),
            _player("Scottie Barnes", 6, "trade", src="Big Nik Energy", dst="Spayed for Cade"))
SUNDAY_LATE = raw(5, _ts(2026, 11, 8, 23, 30), "add", _player("Late Guy", 7, "add", dst="Blink-183"))


def _sync(base, txns, rulings=()):
    return tlog.sync(base, txns, manager_of=_manager_of, week_of=_week_of, rulings=rulings,
                     run_id="test", now=datetime(2026, 11, 9, 0, 1, tzinfo=LA))


def test_no_duplicate_rows_across_two_runs(tmp_path):
    first = _sync(tmp_path, [ADD, ADD_DROP, DROP])
    assert (first["appended"], first["total"]) == (3, 3)
    before = (tmp_path / tlog.LOG_FILE).read_bytes()
    again = _sync(tmp_path, [DROP, ADD_DROP, ADD])          # Yahoo's newest-first order
    assert (again["appended"], again["rulings_rows"]) == (0, 0)
    assert (tmp_path / tlog.LOG_FILE).read_bytes() == before
    more = _sync(tmp_path, [TRADE, DROP, ADD_DROP, ADD])
    assert more["appended"] == 1
    keys = [r["key"] for r in tlog.read(tmp_path)]
    assert len(keys) == len(set(keys)) == 4
    assert (tmp_path / tlog.LOG_FILE).read_bytes().startswith(before)      # appended, never rewritten


def test_a_changed_yahoo_record_raises_and_writes_nothing(tmp_path):
    _sync(tmp_path, [ADD, DROP])
    before = (tmp_path / tlog.LOG_FILE).read_bytes()
    changed = json.loads(json.dumps(DROP))
    changed["timestamp"] = str(int(changed["timestamp"]) + 60)
    with pytest.raises(tlog.TransactionChanged, match="changed since it was logged"):
        _sync(tmp_path, [ADD, changed, TRADE])
    assert (tmp_path / tlog.LOG_FILE).read_bytes() == before                # not even the trade


def test_a_team_rename_is_not_a_changed_record(tmp_path):
    _sync(tmp_path, [ADD])
    renamed = json.loads(json.dumps(ADD))
    td = renamed["players"]["0"]["player"][1]["transaction_data"][0]
    td["destination_team_name"] = "Blink-183"           # a new display name, the same team key
    out = tlog.sync(tmp_path, [renamed], manager_of=lambda n, k: "Benton", week_of=_week_of,
                    run_id="t2", now=datetime(2026, 11, 9, tzinfo=LA))
    assert out["appended"] == 0


def test_a_drop_and_a_trade_are_logged_with_pacific_times(tmp_path):
    _sync(tmp_path, [ADD_DROP, DROP, TRADE])
    rows = {r["type"]: r for r in tlog.transactions(tmp_path)}
    d = rows["drop"]
    assert (d["time"], d["league_day"], d["fantasy_week"]) == ("2026-11-03T09:05:00-08:00", "2026-11-03", 3)
    assert d["players"] == [{"name": "Kawhi Leonard", "player_key": "p.4", "action": "drop",
                             "from": {"type": "team", "team_key": "k.Big Nik Energy",
                                      "team": "Big Nik Energy", "manager": "Hayden"},
                             "to": {"type": "freeagents", "team_key": None, "team": None,
                                    "manager": None}}]
    t = rows["trade"]
    assert t["time"] == "2026-11-04T20:45:00-08:00"
    assert sorted((p["name"], p["from"]["manager"], p["to"]["manager"]) for p in t["players"]) == \
        [("Jayson Tatum", "Benton", "Hayden"), ("Scottie Barnes", "Hayden", "Benton")]
    ad = rows["add/drop"]
    assert [p["action"] for p in ad["players"]] == ["add", "drop"]


@pytest.fixture(params=["UTC", "America/Phoenix"])
def machine_clock(request):
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX-only")
    old = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield request.param
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_a_sunday_2330_pacific_transaction_lands_on_sunday(tmp_path, machine_clock):
    _sync(tmp_path, [SUNDAY_LATE])
    r = tlog.read(tmp_path)[0]
    assert (r["league_day"], r["fantasy_week"], r["time"]) == ("2026-11-08", 3, "2026-11-08T23:30:00-08:00")


def test_unknown_type_action_or_status_raises(tmp_path):
    for bad in (dict(ADD, type="commish"), dict(ADD, status="pending"), dict(ADD, timestamp=None)):
        with pytest.raises(tlog.TransactionLogError):
            _sync(tmp_path, [bad])
    assert not (tmp_path / tlog.LOG_FILE).exists()


def test_a_ruling_written_after_the_move_is_appended_not_rewritten(tmp_path):
    from modules.transaction_rulings import ClaimWeek
    _sync(tmp_path, [ADD_DROP])
    before = (tmp_path / tlog.LOG_FILE).read_bytes()
    ruling = ClaimWeek(manager="Nick", player="Miles Bridges", type="add", transaction_date="2026-11-02",
                       claim_week=2, by="Nick", on="2026-11-02", reason="a week-2 chat claim")
    out = _sync(tmp_path, [ADD_DROP], rulings=[ruling])
    assert (out["appended"], out["rulings_rows"]) == (0, 1)
    assert (tmp_path / tlog.LOG_FILE).read_bytes().startswith(before)
    t = tlog.transactions(tmp_path)[0]
    assert t["rulings"] == [{"kind": "claim_week", "player": "Miles Bridges", "claim_week": 2,
                             "label": ruling.label(), "reason": "a week-2 chat claim"}]
    assert _sync(tmp_path, [ADD_DROP], rulings=[ruling])["rulings_rows"] == 0   # no repeat
    item = tlog.feed_item(t, SCHEDULE)
    assert (item["who"], item["what"], item["note"], item["time"]) == \
        ("Nick", "added Miles Bridges, dropped Ty Jerome", "week 2 claim", "6:12 AM")


def test_a_malformed_or_duplicated_file_raises(tmp_path):
    _sync(tmp_path, [ADD])
    p = tmp_path / tlog.LOG_FILE
    line = p.read_text(encoding="utf-8")
    p.write_text(line + line, encoding="utf-8")
    with pytest.raises(LogCorrupt, match="logged twice"):
        tlog.read(tmp_path)
    p.write_text(line.rstrip("\n"), encoding="utf-8")
    with pytest.raises(LogCorrupt, match="unterminated"):
        tlog.read(tmp_path)


def test_the_feed_shows_drops_and_trades_with_times(tmp_path):
    _sync(tmp_path, [DROP, TRADE])
    items = [tlog.feed_item(t, SCHEDULE) for t in tlog.transactions(tmp_path)]
    assert items[0]["what"] == "dropped Kawhi Leonard" and items[0]["time"] == "9:05 AM"
    assert items[1]["who"] == "Trade:" and items[1]["time"] == "8:45 PM"
    assert "Hayden gets Jayson Tatum" in items[1]["what"]


def test_the_hub_moves_read_the_log_newest_first_in_each_week(tmp_path):
    """The hub's moves (task 43: by budget week, modules/hub_moves) read this
    log, newest first within a week; no log raises."""
    from modules import hub_moves
    _sync(tmp_path, [ADD, ADD_DROP, DROP, TRADE])
    feed = hub_moves.by_week(tlog.transactions(tmp_path), [], SCHEDULE, None,
                             {3: {"Benton": ["Davion Mitchell"], "Nick": ["Miles Bridges"]}}, week=3,
                             managers=["Nick", "Hayden", "Garrett", "Benton"], budget=3, mode="shadow")
    wk3 = next(t for t in feed["weeks"] if t["key"] == "3")
    assert [x["time"] for x in wk3["items"]] == ["8:45 PM", "9:05 AM", "11:18 AM", "6:12 AM"]
    assert "dates only" not in feed["note"] and "adds only" not in feed["note"]
    with pytest.raises(hub_moves.MovesError, match="transaction_log"):
        hub_moves.build(tmp_path / "nowhere", SCHEDULE, 3, managers=["Nick"], budget=3)


# =============================================================================
# the nightly sync
# =============================================================================

def _world(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHEDULE), encoding="utf-8")
    rosters = {"rosters": {"Nick": ["Miles Bridges"], "Hayden": ["Kawhi Leonard"],
                           "Benton": ["Davion Mitchell"], "Garrett": ["A Guard"]}}
    (tmp_path / "config" / "ROSTERS.json").write_text(json.dumps(rosters), encoding="utf-8")
    finished = "# Waiver Adds for Week 2\n# Generated: 2026-11-02 08:00 PST\n\n- [2026-10-28] Nick: Old Pick\n"
    (tmp_path / "data" / "waivers_week2.txt").write_text(finished, encoding="utf-8")
    return finished


LIVE = {"Nick": {"players": ["Miles Bridges"], "il": []},
        "Hayden": {"players": [], "il": []},
        "Benton": {"players": ["Davion Mitchell"], "il": []},
        "Garrett": {"players": ["A Guard"], "il": ["A Guard"]}}


def test_the_nightly_sync_never_rewrites_a_finished_weeks_adds_file(tmp_path, monkeypatch):
    import sync_transactions as st
    monkeypatch.setattr(st, "manager_for_team", lambda n, k=None: TEAMS[n])
    finished = _world(tmp_path)
    before = (tmp_path / "data" / "waivers_week2.txt").read_bytes()
    out = st.nightly_sync(tmp_path, raw=[ADD, ADD_DROP, DROP], live=LIVE,
                          now=datetime(2026, 11, 4, 0, 1, tzinfo=LA), echo=lambda *a: None)
    assert out["week"] == 3
    assert (tmp_path / "data" / "waivers_week2.txt").read_bytes() == before == finished.encode()
    week3 = (tmp_path / "data" / "waivers_week3.txt").read_text(encoding="utf-8")
    assert "PARTIAL" in week3 and "Benton: Davion Mitchell" in week3 and "Nick: Miles Bridges" in week3
    il = json.loads((tmp_path / "data" / "IL_SLOTS.json").read_text(encoding="utf-8"))
    assert (il["fantasy_week"], il["slots"]["Garrett"]) == (3, ["A Guard"])
    assert out["counts"] == ["Nick: 1 active, 0 IL", "Hayden: 0 active, 0 IL",
                             "Benton: 1 active, 0 IL", "Garrett: 0 active, 1 IL"]
    assert len(tlog.read(tmp_path)) == 3


def test_the_nightly_sync_refuses_a_roster_yahoo_does_not_have(tmp_path, monkeypatch):
    import sync_transactions as st
    monkeypatch.setattr(st, "manager_for_team", lambda n, k=None: TEAMS[n])
    _world(tmp_path)
    live = json.loads(json.dumps(LIVE))
    live["Nick"]["players"].append("Someone Else")
    ros_before = (tmp_path / "config" / "ROSTERS.json").read_bytes()
    with pytest.raises(st.RosterMismatch, match="Yahoo also has \\['Someone Else'\\]"):
        st.nightly_sync(tmp_path, raw=[ADD, ADD_DROP, DROP], live=live,
                        now=datetime(2026, 11, 4, 0, 1, tzinfo=LA), echo=lambda *a: None)
    assert (tmp_path / "config" / "ROSTERS.json").read_bytes() == ros_before
    assert not (tmp_path / "data" / "waivers_week3.txt").exists()
    assert not (tmp_path / "data" / "IL_SLOTS.json").exists()


def test_roster_counts_print_active_and_il_apart():
    import sync_transactions as st
    assert st.roster_count_lines({"Benton": [f"p{i}" for i in range(16)]}, {"Benton": ["p3"]}) == \
        ["Benton: 15 active, 1 IL"]
    with pytest.raises(ValueError, match="not on his roster"):
        st.roster_count_lines({"Benton": ["a"]}, {"Benton": ["b"]})


def test_the_transaction_log_is_league_state():
    from modules import state_manifest as sm
    assert sm.load(ROOT).contains(tlog.LOG_FILE.as_posix())


def test_a_full_page_that_does_not_reach_the_log_raises_a_possible_gap(tmp_path):
    _sync(tmp_path, [ADD])
    with pytest.raises(tlog.TransactionLogError, match="gap"):
        tlog.sync(tmp_path, [DROP, TRADE], manager_of=_manager_of, week_of=_week_of,
                  run_id="t", now=datetime(2026, 11, 9, tzinfo=LA), page_full=True)
    assert len(tlog.read(tmp_path)) == 1
    # a full page that overlaps what is logged is fine
    out = tlog.sync(tmp_path, [DROP, TRADE, ADD], manager_of=_manager_of, week_of=_week_of,
                    run_id="t", now=datetime(2026, 11, 9, tzinfo=LA), page_full=True)
    assert out["appended"] == 2
