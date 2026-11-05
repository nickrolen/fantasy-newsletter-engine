"""
Task 47 (Nick's spec for 42; LEAGUE_RULES rule 2): IL eligibility is the Yahoo
tag. At the window -- the checklist, its rule-3 re-check, ledger.py check --
only a tag in roster_moves.il_eligible_tags (O, OFS) makes a player
IL-eligible. At entry, an IL+ for a player with no eligible tag but a live
injury entry covering the window day is accepted WITH A WARNING; with neither
it is refused. One function decides (move_ledger.tag_il_eligible); the hub's
stash table reads the same function and the same config key.
"""
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from modules import move_ledger as ml, hub_state as hs          # noqa: E402
from test_move_ledger import make_world, enter, refused, at      # noqa: E402

ENTRY = {"player_name": "Pat Nick02", "out_weeks": [4, 5], "return_week": 6}   # out on Mon 11-09
WARN = "not tagged O/OFS in Yahoo now: he must be by Monday's window (Mon 11-09) or the move fails"


def test_tagged_o_is_eligible_at_entry_and_at_the_window():
    w, rows = make_world(tags={"Pat Nick02": "O"}), []
    row = enter(w, rows, "Nick move: +Bane IL+Pat Nick02")
    assert "warnings" not in row and not any(c.startswith("WARNING") for c in row["checks"])
    assert any("IL+Pat Nick02: tagged O" in c for c in row["checks"])
    monday = make_world(now=at("2026-11-09", 0, 2), tags={"Pat Nick02": "O"})
    cl = ml.checklist(monday, rows, [], 4)
    assert cl["stopped"] == []
    assert [x["text"] for x in cl["lines"]] == ["Nick: move Pat Nick02 into an IL slot", "Nick: add Desmond Bane"]
    assert ml.recheck(monday, rows, []) == [(1, "ok")]


def test_an_injury_entry_alone_is_accepted_with_the_warning_and_not_eligible_at_the_window():
    w, rows = make_world(overrides=[ENTRY]), []            # Pat Nick02 untagged (healthy)
    row = enter(w, rows, "Nick move: +Bane IL+Pat Nick02")
    assert row["warnings"] == [f"IL+Pat Nick02: {WARN}"]
    assert f"WARNING: IL+Pat Nick02: {WARN}" in row["checks"]
    # Monday: still untagged in Yahoo -> the checklist marks Nick's line not eligible, as any other
    monday = make_world(now=at("2026-11-09", 0, 2), overrides=[ENTRY])
    cl = ml.checklist(monday, rows, [], 4)
    assert [s["team"] for s in cl["stopped"]] == ["Nick"]
    assert "only O or OFS may go into an IL slot" in cl["stopped"][0]["reason"]
    assert "injury entry" not in cl["stopped"][0]["reason"]
    # ledger.py check (recheck) reads the tag alone too
    (eid, why), = ml.recheck(monday, rows, [])
    assert eid == 1 and "only O or OFS" in why
    # tagged O by Monday -> the line goes through
    ok = make_world(now=at("2026-11-09", 0, 2), overrides=[ENTRY], tags={"Pat Nick02": "O"})
    assert ml.checklist(ok, rows, [], 4)["stopped"] == []


def test_neither_tag_nor_entry_is_refused():
    msg = refused(make_world(), [], "Nick move: +Bane IL+Pat Nick02", "tagged healthy", "only O or OFS",
                  "rule 2", "no injury entry covers Mon 11-09 either")
    assert "WARNING" not in msg


def test_a_q_player_with_an_entry_is_the_same_as_entry_only():
    w, rows = make_world(tags={"Pat Nick02": "Q"}, overrides=[ENTRY]), []
    row = enter(w, rows, "Nick move: +Bane IL+Pat Nick02")
    assert row["warnings"] == [f"IL+Pat Nick02: {WARN}"]
    monday = make_world(now=at("2026-11-09", 0, 2), tags={"Pat Nick02": "Q"}, overrides=[ENTRY])
    cl = ml.checklist(monday, rows, [], 4)
    assert [s["team"] for s in cl["stopped"]] == ["Nick"] and "tagged Q" in cl["stopped"][0]["reason"]
    # and a Q player with no entry is refused at entry
    refused(make_world(tags={"Pat Nick02": "Q"}), [], "Nick move: +Bane IL+Pat Nick02", "tagged Q")


def test_an_entry_that_does_not_cover_the_window_day_is_refused():
    gone = {"player_name": "Pat Nick02", "out_weeks": [3], "return_week": 4}     # back by Mon 11-09
    refused(make_world(overrides=[gone]), [], "Nick move: +Bane IL+Pat Nick02", "only O or OFS")


def test_a_healthy_il_occupant_with_an_entry_stops_his_team_at_the_window_rule_3():
    # the checklist's own re-check (rule 3) is the tag alone too
    w, rows = make_world(), []
    enter(w, rows, "Garrett move: +Bane -Pat Garrett01")
    monday = make_world(now=at("2026-11-09", 0, 2), tags={"Alex Sarr": "HEALTHY"},
                        overrides=[{"player_name": "Alex Sarr", "out_weeks": [4], "return_week": 5}])
    cl = ml.checklist(monday, rows, [], 4)
    assert [s["team"] for s in cl["stopped"]] == ["Garrett"] and "rule 3" in cl["stopped"][0]["reason"]


def test_one_function_decides_and_only_the_entry_check_reads_an_injury_entry():
    assert ml.tag_il_eligible("O", ("O", "OFS")) and ml.tag_il_eligible("OFS", ("O", "OFS"))
    assert not ml.tag_il_eligible("Q", ("O", "OFS")) and not ml.tag_il_eligible(None, ("O", "OFS"))
    assert not ml.tag_il_eligible("HEALTHY", ("O", "OFS"))
    assert "tag_il_eligible" in inspect.getsource(ml.World.il_eligible)
    assert "override" not in inspect.getsource(ml.World.il_eligible)
    src = inspect.getsource(ml)
    # an injury entry is read for IL eligibility in exactly one place: il_entry_check
    assert src.count("override_out_on") == 2                     # its import and its call
    assert "override_out_on" in inspect.getsource(ml.World.il_entry_check)
    # the window paths never call the entry check
    for fn in (ml.checklist, ml.recheck, ml.rosters_after):
        assert "il_entry_check" not in inspect.getsource(fn) and "at_entry" not in inspect.getsource(fn)
    assert "at_entry=True" in inspect.getsource(ml.make_entry)


def test_the_stash_table_and_the_ledger_read_the_same_function_and_key(monkeypatch):
    assert "tag_il_eligible" in inspect.getsource(hs.stash_rows)
    assert "il_eligible_tags" in inspect.getsource(hs.stash_rows)
    assert "eligible_tags=il_eligible_tags()" in inspect.getsource(ml.World.from_base)
    # the config key moves both: with only "O" eligible, OFS is out of both
    monkeypatch.setattr(ml, "il_eligible_tags", lambda cfg=None: ("O",))
    assert ml.tag_il_eligible("O") and not ml.tag_il_eligible("OFS")
    w = make_world()
    w.eligible_tags = ml.il_eligible_tags()
    assert w.il_eligible("Paolo Banchero", w.window_day(4))[0] is False      # OFS
    assert w.il_eligible("Anthony Edwards", w.window_day(4))[0] is True      # O


def test_the_config_key_is_required():
    with pytest.raises(ml.LedgerError, match="il_eligible_tags is missing"):
        ml.il_eligible_tags({"roster_moves": {"ledger_mode": "shadow"}})
