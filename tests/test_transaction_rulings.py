"""The commissioner's rulings on transactions (HANDOFF_WEEK2_GRID_AND_RULINGS
2026-10-30, s.2).

On 10-26 Garrett added Paul George and dropped him the same day; Benton had
already claimed George in the group chat. Nick voided the add on 10-30 and set
Garrett's week-2 move count from 3 to 2. Yahoo's log still holds the add, so
the partial waivers file -- and every later sync -- counted it: 3 used, 0 left.
"""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import transaction_rulings as tr          # noqa: E402
from modules.weekly_stats import load_waiver_adds      # noqa: E402

SCHEDULE = {"weeks": [{"week": 1, "start_date": "2026-10-20", "end_date": "2026-10-25"},
                      {"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01"}]}

# data/waivers_week2.txt as sync_transactions wrote it on 10-26 23:04
FILE_10_26 = """# Waiver Adds for Week 2
# Generated: 2026-10-26 23:04 (PARTIAL -- week still in progress)

# Adds made so far in a week that has not finished. The
# newsletter reads this to report each team's remaining
# adds. It is overwritten by the full file when this
# week is itself synced.

- [2026-10-26] Hayden: Franz Wagner
- [2026-10-26] Hayden: Zach LaVine
- [2026-10-26] Garrett: Paul George
- [2026-10-26] Garrett: Aaron Wiggins
- [2026-10-26] Garrett: Toumani Camara
- [2026-10-26] Hayden: Darius Acuff Jr.
- [2026-10-26] Benton: Nickeil Alexander-Walker
- [2026-10-26] Benton: Paul George
- [2026-10-26] Benton: Cameron Boozer
- [2026-10-26] Nick: Damian Lillard
- [2026-10-26] Nick: Dyson Daniels
- [2026-10-26] Nick: Ty Jerome
"""

GARRETT = {"date": "2026-10-26", "manager": "Garrett", "type": "add", "player": "Paul George",
           "ruling": "void", "by": "Nick", "on": "2026-10-30", "reason": "claimed by Benton first"}


def world(tmp_path, rulings=None, real=False):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    if real:
        shutil.copy(ROOT / tr.RULINGS_FILE, tmp_path / tr.RULINGS_FILE)
    else:
        (tmp_path / tr.RULINGS_FILE).write_text(json.dumps({"rulings": rulings or []}))
    f = tmp_path / "data" / "waivers_week2.txt"
    f.write_text(FILE_10_26, encoding="utf-8")
    return f


def txn(kind, manager, player, d="2026-10-26"):
    return {"type": kind, "manager": manager, "player_name": player,
            "date": date.fromisoformat(d), "details": {}}


# ------------------------------------------------------------- the rulings

def test_the_real_file_holds_garretts_ruling_and_loads():
    rulings = tr.load_rulings(ROOT)
    assert [(r.date, r.manager, r.type, r.player, r.ruling) for r in rulings] == [
        ("2026-10-26", "Garrett", "add", "Paul George", "void")]


def test_a_ruling_the_code_does_not_know_raises(tmp_path):
    for bad in ({**GARRETT, "type": "drop"}, {**GARRETT, "ruling": "reverse"},
                {**GARRETT, "roster_effect": "undo"}, {k: v for k, v in GARRETT.items()
                                                       if k != "reason"}):
        world(tmp_path, [bad])
        with pytest.raises(tr.RulingError):
            tr.load_rulings(tmp_path)


# ------------------------------------------------------------------ the sync

def test_a_voided_add_is_not_counted_or_listed_but_the_drop_still_is(tmp_path):
    world(tmp_path, [GARRETT])
    said = []
    log = [txn("add", "Garrett", "Paul George"), txn("drop", "Garrett", "Paul George"),
           txn("add", "Benton", "Paul George"), txn("add", "Garrett", "Aaron Wiggins")]
    kept, applied = tr.apply_to_transactions(log, tr.load_rulings(tmp_path),
                                             since=date(2026, 10, 26), echo=said.append)
    assert [(t["type"], t["manager"], t["player_name"]) for t in kept] == [
        ("drop", "Garrett", "Paul George"), ("add", "Benton", "Paul George"),
        ("add", "Garrett", "Aaron Wiggins")]
    assert len(applied) == 1 and "RULING applied: void 2026-10-26 Garrett add Paul George" in said[0]


def test_a_ruling_matching_nothing_raises_with_its_date_and_names(tmp_path):
    world(tmp_path, [{**GARRETT, "player": "Paul Georges"}])
    with pytest.raises(tr.RulingError, match="2026-10-26 Garrett add Paul Georges"):
        tr.apply_to_transactions([txn("add", "Garrett", "Paul George")],
                                 tr.load_rulings(tmp_path), since=date(2026, 10, 26))


def test_a_ruling_outside_the_sync_window_is_not_asked_to_match(tmp_path):
    world(tmp_path, [GARRETT])
    kept, applied = tr.apply_to_transactions([], tr.load_rulings(tmp_path),
                                             since=date(2026, 10, 20), until=date(2026, 10, 25))
    assert kept == [] and applied == []


def test_the_synced_file_records_the_ruling_and_reads_clean(tmp_path):
    import sync_transactions as st
    world(tmp_path, [GARRETT])
    log = [txn("add", "Garrett", "Paul George"), txn("add", "Garrett", "Aaron Wiggins"),
           txn("add", "Garrett", "Toumani Camara")]
    kept, applied = tr.apply_to_transactions(log, tr.load_rulings(tmp_path),
                                             since=date(2026, 10, 26), echo=lambda *_: None)
    st.write_waivers_file(kept, 2, tmp_path, partial=True, applied=applied)
    path = tmp_path / "data" / "waivers_week2.txt"
    text = path.read_text(encoding="utf-8")
    assert "# RULING applied: void 2026-10-26 Garrett add Paul George (Nick, 2026-10-30)" in text
    assert "- [2026-10-26] Garrett: Paul George" not in text
    lines, again = tr.waiver_lines(path, tmp_path, 2, SCHEDULE)
    assert again == []                                 # already applied when written
    assert load_waiver_adds(str(path), lines=lines)["Garrett"] == ["Aaron Wiggins", "Toumani Camara"]


# --------------------------------------------------------- reading the file

def test_garretts_week_2_on_the_10_26_file_is_2_used_1_left(tmp_path, monkeypatch):
    world(tmp_path, real=True)
    from modules import report_builder as rb
    monkeypatch.setattr(rb, "__file__", str(tmp_path / "modules" / "report_builder.py"))

    class D:
        schedule = SCHEDULE
    out = rb.build_add_budget(D(), 1)
    assert out["managers"]["Garrett"] == {"used": 2, "remaining": 1,
                                          "players": ["Aaron Wiggins", "Toumani Camara"],
                                          "over_budget": False}
    assert out["managers"]["Benton"]["players"] == [
        "Nickeil Alexander-Walker", "Paul George", "Cameron Boozer"]   # Benton's claim stands
    assert out["rulings_applied"] == ["void 2026-10-26 Garrett add Paul George (Nick, 2026-10-30)"]


def test_a_file_ruling_that_matches_no_line_raises(tmp_path):
    path = world(tmp_path, [{**GARRETT, "manager": "Hayden"}])
    with pytest.raises(tr.RulingError, match="2026-10-26 Hayden add Paul George"):
        tr.waiver_lines(path, tmp_path, 2, SCHEDULE)


def test_the_rewrite_removes_the_line_records_it_and_is_idempotent(tmp_path):
    path = world(tmp_path, [GARRETT])
    applied = tr.rewrite_waivers_file(path, tmp_path, 2, SCHEDULE, echo=lambda *_: None)
    assert len(applied) == 1
    text = path.read_text(encoding="utf-8")
    assert "- [2026-10-26] Garrett: Paul George" not in text
    assert "- [2026-10-26] Benton: Paul George" in text
    assert "# RULING applied: void 2026-10-26 Garrett add Paul George (Nick, 2026-10-30)" in text
    assert tr.rewrite_waivers_file(path, tmp_path, 2, SCHEDULE, echo=lambda *_: None) == []
    assert path.read_text(encoding="utf-8") == text
    assert load_waiver_adds(str(path))["Garrett"] == ["Aaron Wiggins", "Toumani Camara"]


def test_waiver_roi_does_not_list_a_voided_add(tmp_path):
    from modules.waiver_roi import load_all_waivers
    world(tmp_path, [GARRETT])
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHEDULE))
    got = [(a.manager, a.player_name) for a in load_all_waivers(tmp_path, 2)]
    assert ("Garrett", "Paul George") not in got and ("Benton", "Paul George") in got


def test_a_ruling_dated_outside_every_week_cannot_be_placed(tmp_path):
    path = world(tmp_path, [{**GARRETT, "date": "2027-06-01"}])
    with pytest.raises(tr.RulingError, match="no fantasy week"):
        tr.waiver_lines(path, tmp_path, 2, SCHEDULE)


def test_a_new_season_starts_with_no_rulings(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sns", ROOT / "scripts" / "start_new_season.py")
    sns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sns)
    monkeypatch.setattr(sns, "PROJECT_ROOT", tmp_path)
    world(tmp_path, real=True)
    sns.reset_transaction_rulings(execute=True)
    assert tr.load_rulings(tmp_path) == []
    assert "commissioner" in json.loads((tmp_path / tr.RULINGS_FILE).read_text())["_comment"]
