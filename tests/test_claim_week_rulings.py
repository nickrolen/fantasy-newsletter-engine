"""Group-chat claims use the add budget of the week they were claimed in
(HANDOFF_CLAIM_WEEK_RULINGS 2026-10-31; LEAGUE_RULES rule 7).

Nick, 10-30: "If I add someone midweek in week 2, I am using my week 2 add
allowance, but that player won't be on my roster until Monday of week 3." So a
claim made in the chat in week N is applied in Yahoo in week N+1's Monday
window and carries week N+1's date, and every add counter used to count it in
week N+1. A `claim_week` ruling says which week it was claimed in, and ONE
function, transaction_rulings.add_budget_week, decides every add's week.

Nick's answers, 10-31:
  - Hayden's Sunday 22:35 Wagner add: void ("the Franz Wagner add never
    happened effectively");
  - of 10-26's adds, Garrett's two were made directly in Yahoo on Monday
    morning; every Hayden, Benton and Nick add was a week 1 chat claim;
  - "Any adds made before tipoff of the first NBA game of the year DO NOT
    COUNT as moves anywhere";
  - a claim is LISTED in the waivers file of its Yahoo week, marked
    "(week N claim)", and COUNTED only in week N.
"""
import ast
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import transaction_rulings as tr          # noqa: E402
from modules import league_clock as lc                 # noqa: E402
from league_state import needs_state  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
SCHEDULE = {"weeks": [{"week": 1, "start_date": "2026-10-20", "end_date": "2026-10-25"},
                      {"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01"},
                      {"week": 3, "start_date": "2026-11-02", "end_date": "2026-11-08"}]}

BOOZER = {"kind": "claim_week", "manager": "Benton", "player": "Cameron Boozer", "type": "add",
          "transaction_date": "2026-10-26", "claim_week": 1, "by": "Nick", "on": "2026-10-31",
          "reason": "Claimed in the group chat during week 1; applied in Yahoo in week 2's "
                    "Monday window (rule 7)."}
LAVINE = {"kind": "effective_date", "manager": "Hayden", "player": "Zach LaVine", "type": "add",
          "transaction_date": "2026-10-25", "effective": "2026-10-26", "by": "Nick",
          "on": "2026-10-30", "reason": "added after Sunday's games"}
GARRETT_PG = {"date": "2026-10-26", "manager": "Garrett", "type": "add", "player": "Paul George",
              "ruling": "void", "by": "Nick", "on": "2026-10-30", "reason": "Benton claimed first"}


def world(tmp_path, rulings, files=None):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / tr.RULINGS_FILE).write_text(json.dumps({"rulings": rulings}))
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHEDULE))
    for wk, lines in (files or {}).items():
        (tmp_path / "data" / f"waivers_week{wk}.txt").write_text(
            f"# Waiver Adds for Week {wk}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def add(d, manager, player, **kw):
    return {"date": d, "manager": manager, "player": player, **kw}


def txn(kind, manager, player, d):
    return {"type": kind, "manager": manager, "player_name": player,
            "date": date.fromisoformat(d), "details": {}}


# =========================================================== 1. which week

def test_a_claim_counts_in_its_claim_week_not_its_yahoo_week(tmp_path):
    rulings = tr.load_all(world(tmp_path, [BOOZER]))
    assert tr.add_budget_week(add("2026-10-26", "Benton", "Cameron Boozer"), rulings, SCHEDULE) == 1


def test_a_direct_monday_window_add_counts_in_its_own_week(tmp_path):
    rulings = tr.load_all(world(tmp_path, [BOOZER]))
    assert tr.add_budget_week(add("2026-10-26", "Garrett", "Aaron Wiggins"), rulings, SCHEDULE) == 2


def test_a_voided_add_counts_nowhere(tmp_path):
    rulings = tr.load_all(world(tmp_path, [GARRETT_PG]))
    assert tr.add_budget_week(add("2026-10-26", "Garrett", "Paul George"), rulings, SCHEDULE) is None
    # Benton's add of the same player on the same day is his own, and counts
    assert tr.add_budget_week(add("2026-10-26", "Benton", "Paul George"), rulings, SCHEDULE) == 2


def test_an_effective_date_add_counts_in_the_week_it_was_made(tmp_path):
    """Nick, 11-01: "Lavine should have counted against his week 1 budget,
    not his week 2 budget." Made Sun 10-25 (week 1), effective Mon 10-26: the
    budget week is the Yahoo date's; the effective date governs only the logs."""
    rulings = tr.load_all(world(tmp_path, [LAVINE]))
    # by its Yahoo date, and by the date a waivers file carries once re-dated
    for d in ("2026-10-25", "2026-10-26"):
        assert tr.add_budget_week(add(d, "Hayden", "Zach LaVine"), rulings, SCHEDULE) == 1


def test_an_effective_date_add_made_and_effective_in_one_week_counts_there(tmp_path):
    rule = {**LAVINE, "transaction_date": "2026-10-27", "effective": "2026-10-28"}
    rulings = tr.load_all(world(tmp_path, [rule]))
    for d in ("2026-10-27", "2026-10-28"):
        assert tr.add_budget_week(add(d, "Hayden", "Zach LaVine"), rulings, SCHEDULE) == 2


def test_an_effective_date_add_made_pre_season_counts_nowhere(tmp_path):
    """Its Yahoo date decides, so a pre-season add effective in week 1 is
    still pre-season (Nick, 10-31)."""
    rule = {**LAVINE, "transaction_date": "2026-10-19", "effective": "2026-10-21"}
    rulings = tr.load_all(world(tmp_path, [rule]))
    assert tr.add_budget_week(add("2026-10-21", "Hayden", "Zach LaVine"), rulings, SCHEDULE) is None


def test_an_effective_date_add_made_on_opening_day_is_not_guessed(tmp_path):
    rule = {**LAVINE, "transaction_date": "2026-10-20", "effective": "2026-10-21"}
    rulings = tr.load_all(world(tmp_path, [rule]))
    with pytest.raises(tr.RulingError, match="first day"):
        tr.add_budget_week(add("2026-10-21", "Hayden", "Zach LaVine"), rulings, SCHEDULE)


def test_an_effective_date_add_is_listed_in_its_effective_week_marked(tmp_path):
    """Listed where the player joined (week 2), marked "(week 1 add)": the
    week it was made in and whose budget it uses. A line written before the
    mark existed gets it at read time; a rewrite keeps it, once."""
    base = world(tmp_path, [LAVINE], {1: [], 2: ["- [2026-10-26] Hayden: Zach LaVine"]})
    (base / "data" / "waivers_week1.txt").write_text(
        "# Waiver Adds for Week 1\n# RULING applied: " + tr.load_all(base)[0].label()
        + "\n\nNo waiver adds this week.\n", encoding="utf-8")
    path = base / "data" / "waivers_week2.txt"
    lines, applied = tr.waiver_lines(path, base, 2, SCHEDULE)
    assert "- [2026-10-26] Hayden: Zach LaVine (week 1 add)" in lines and len(applied) == 1
    assert tr.parse_add_line("- [2026-10-26] Hayden: Zach LaVine (week 1 add)")["player"] == "Zach LaVine"
    assert tr.adds_by_budget_week(base, SCHEDULE) == {1: {"Hayden": ["Zach LaVine"]}}
    assert len(tr.rewrite_waivers_file(path, base, 2, SCHEDULE, echo=lambda *_: None)) == 1
    text = path.read_text("utf-8")
    assert "Zach LaVine (week 1 add)" in text and text.count("# RULING applied") == 1
    assert tr.rewrite_waivers_file(path, base, 2, SCHEDULE, echo=lambda *_: None) == []
    assert path.read_text("utf-8") == text


def test_a_wrong_or_unbacked_add_mark_raises(tmp_path):
    base = world(tmp_path, [LAVINE], {2: ["- [2026-10-26] Hayden: Zach LaVine (week 2 add)"]})
    with pytest.raises(tr.RulingError, match="made in week 1"):
        tr.waiver_lines(base / "data" / "waivers_week2.txt", base, 2, SCHEDULE)
    base = world(tmp_path, [], {2: ["- [2026-10-26] Garrett: Aaron Wiggins (week 1 add)"]})
    with pytest.raises(tr.RulingError, match="no effective_date ruling"):
        tr.waiver_lines(base / "data" / "waivers_week2.txt", base, 2, SCHEDULE)


def test_pre_season_adds_count_nowhere():
    """Nick, 10-31: adds before the season's first tip count in no week."""
    for d in ("2026-10-11", "2026-10-19"):
        assert tr.add_budget_week(add(d, "Nick", "Julius Randle"), [], SCHEDULE) is None


def test_an_opening_day_add_is_not_guessed_either_way():
    """Before the first tip it counts nowhere, after it in week 1, and tip
    times are not stored (design s.4.1): it raises."""
    with pytest.raises(tr.RulingError, match="first day"):
        tr.add_budget_week(add("2026-10-20", "Nick", "Julius Randle"), [], SCHEDULE)


def test_a_trade_uses_no_add():
    assert tr.add_budget_week(add("2026-10-27", "Nick", "X", via="trade"), [], SCHEDULE) is None
    assert tr.add_budget_week({"date": date(2026, 10, 27), "manager": "Nick", "player_name": "X",
                               "details": {"via": "trade"}}, [], SCHEDULE) is None


def test_an_add_after_the_schedule_cannot_be_placed():
    with pytest.raises(tr.RulingError, match="no fantasy week"):
        tr.add_budget_week(add("2027-06-01", "Nick", "X"), [], SCHEDULE)


# ============================================================ 2. refusals

def test_a_claim_week_ruling_matching_no_transaction_raises(tmp_path):
    rulings = tr.load_all(world(tmp_path, [BOOZER]))
    with pytest.raises(tr.RulingError, match="claim_week 1 2026-10-26 Benton add Cameron Boozer"):
        tr.apply_to_transactions([txn("add", "Benton", "Paul George", "2026-10-26")], rulings,
                                 since=date(2026, 10, 26), echo=lambda *_: None)


def test_a_claim_week_ruling_matching_no_waivers_line_raises(tmp_path):
    base = world(tmp_path, [BOOZER], {2: ["- [2026-10-26] Benton: Paul George"]})
    with pytest.raises(tr.RulingError, match="matches 0 adds"):
        tr.waiver_lines(base / "data" / "waivers_week2.txt", base, 2, SCHEDULE)


@pytest.mark.parametrize("cw", [2, 3])
def test_a_claim_week_not_earlier_than_its_yahoo_week_raises(tmp_path, cw):
    with pytest.raises(tr.RulingError, match="not earlier than week 2"):
        tr.load_all(world(tmp_path, [{**BOOZER, "claim_week": cw}]))


@pytest.mark.parametrize("cw", [0, "1", 1.0, True, None])
def test_a_claim_week_that_is_not_a_week_number_raises(tmp_path, cw):
    with pytest.raises(tr.RulingError):
        tr.load_all(world(tmp_path, [{**BOOZER, "claim_week": cw}]))


def test_a_claim_week_with_no_schedule_to_check_against_raises(tmp_path):
    base = world(tmp_path, [BOOZER])
    (base / "config" / "SCHEDULE.json").unlink()
    with pytest.raises(tr.RulingError, match="cannot be checked"):
        tr.load_all(base)


@pytest.mark.parametrize("field", ["by", "claim_week", "transaction_date"])
def test_a_claim_week_with_a_missing_field_raises(tmp_path, field):
    with pytest.raises(tr.RulingError, match="missing"):
        tr.load_all(world(tmp_path, [{k: v for k, v in BOOZER.items() if k != field}]))


def test_a_claim_week_with_an_unknown_field_raises(tmp_path):
    with pytest.raises(tr.RulingError, match="unknown field"):
        tr.load_all(world(tmp_path, [{**BOOZER, "effective": "2026-10-26"}]))


@pytest.mark.parametrize("other", [
    {"kind": "effective_date", "manager": "Benton", "player": "Cameron Boozer", "type": "add",
     "transaction_date": "2026-10-26", "effective": "2026-11-02", "by": "Nick", "on": "2026-10-31",
     "reason": "x"},
    {"date": "2026-10-26", "manager": "Benton", "type": "add", "player": "Cameron Boozer",
     "ruling": "void", "by": "Nick", "on": "2026-10-31", "reason": "x"},
    BOOZER,
])
def test_two_rulings_on_one_add_raise(tmp_path, other):
    with pytest.raises(tr.RulingError, match="two rulings on one add"):
        tr.load_all(world(tmp_path, [BOOZER, other]))


def test_add_budget_week_itself_refuses_two_rulings_on_one_add(tmp_path):
    """load_all refuses such a file; rulings handed in some other way are
    refused again where the week is decided."""
    a = tr.load_all(world(tmp_path, [BOOZER]))
    b = tr.load_all(world(tmp_path, [{**GARRETT_PG, "manager": "Benton",
                                      "player": "Cameron Boozer"}]))
    with pytest.raises(tr.RulingError, match="one add has one week"):
        tr.add_budget_week(add("2026-10-26", "Benton", "Cameron Boozer"), a + b, SCHEDULE)


def test_a_mark_with_no_ruling_behind_it_raises(tmp_path):
    base = world(tmp_path, [], {2: ["- [2026-10-26] Nick: Ty Jerome (week 1 claim)"]})
    with pytest.raises(tr.RulingError, match="no claim_week ruling"):
        tr.waiver_lines(base / "data" / "waivers_week2.txt", base, 2, SCHEDULE)


def test_a_mark_that_disagrees_with_its_ruling_raises(tmp_path):
    base = world(tmp_path, [{**BOOZER, "transaction_date": "2026-11-02", "claim_week": 2}],
                 {3: ["- [2026-11-02] Benton: Cameron Boozer (week 1 claim)"]})
    with pytest.raises(tr.RulingError, match="marked week 1"):
        tr.waiver_lines(base / "data" / "waivers_week3.txt", base, 3, SCHEDULE)


# ======================================== 3. LaVine on the league's clock

@pytest.fixture(params=["UTC", "America/Phoenix"])
def machine_clock(request):
    """Run as if the machine's own clock were this zone (test_league_clock)."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX-only; the zone-independence check runs in CI")
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


def test_lavines_ruling_matches_his_sunday_2240_pacific_add_on_any_machine(machine_clock, tmp_path):
    """Yahoo stamped LaVine's add Sun 10-25 22:40 Pacific (10-26 05:40 UTC).
    The ruling (as published in 2157743), corrected to transaction_date 2026-10-25, matches it on
    a UTC and a Phoenix machine, and the add counts in week 2."""
    ts = int(datetime(2026, 10, 25, 22, 40, tzinfo=LA).timestamp())
    day = lc.league_date_of_timestamp(ts)
    assert day == date(2026, 10, 25)
    rulings = tr.load_all(frozen_world(tmp_path))
    t = {"type": "add", "manager": "Hayden", "player_name": "Zach LaVine", "date": day,
         "timestamp": ts, "details": {}}
    # his voided Wagner add five minutes earlier is in the same window
    ts_w = int(datetime(2026, 10, 25, 22, 35, tzinfo=LA).timestamp())
    wagner = {"type": "add", "manager": "Hayden", "player_name": "Franz Wagner",
              "date": lc.league_date_of_timestamp(ts_w), "timestamp": ts_w, "details": {}}
    # and the rest of the window, which week 2's other rulings must match
    rest = [txn("add", m, p, d) for d, m, p in WINDOW["txns"] if d == "2026-10-26"]
    window = [wagner, t] + rest
    wk1, ap1 = tr.apply_to_transactions(window, rulings, since=date(2026, 10, 20),
                                        until=date(2026, 10, 25), echo=lambda *_: None)
    wk2, ap2 = tr.apply_to_transactions(window, rulings, since=date(2026, 10, 26),
                                        until=date(2026, 11, 1), echo=lambda *_: None)
    assert wk1 == []
    assert [(x["date"], x["player_name"]) for x in wk2 if x["manager"] == "Hayden"
            and x["player_name"] == "Zach LaVine"] == [(date(2026, 10, 26), "Zach LaVine")]
    lavine = [r for r in rulings if r.kind == "effective_date" and r.player == "Zach LaVine"]
    assert lavine and lavine[0] in ap1 and lavine[0] in ap2      # recorded in both weeks' files
    # made Sunday 10-25 Pacific: week 1's budget (Nick, 11-01)
    assert tr.add_budget_week(t, rulings, SCHEDULE) == 1


@needs_state("config/TRANSACTION_RULINGS.json", why="checks the real rulings file")
def test_the_real_rulings_load_with_the_real_schedule():
    labels = [r.label() for r in tr.load_all(ROOT)]
    assert "effective 2026-10-26 2026-10-25 Hayden add Zach LaVine (Nick, 2026-10-30)" in labels
    assert "void 2026-10-25 Hayden add Franz Wagner (Nick, 2026-10-31)" in labels
    claims = sorted((r.manager, r.player, r.transaction_date, r.claim_week)
                    for r in tr.claim_weeks(tr.load_all(ROOT)))
    assert claims == sorted([
        ("Hayden", "Darius Acuff Jr.", "2026-10-26", 1),
        ("Benton", "Nickeil Alexander-Walker", "2026-10-26", 1),
        ("Benton", "Paul George", "2026-10-26", 1),
        ("Benton", "Cameron Boozer", "2026-10-26", 1),
        ("Nick", "Damian Lillard", "2026-10-26", 1),
        ("Nick", "Dyson Daniels", "2026-10-26", 1),
        ("Nick", "Ty Jerome", "2026-10-26", 1),
        # the week-2 chat claims, applied in Yahoo on 11-02 (reviewing session)
        ("Hayden", "Yaxel Lendeborg", "2026-11-02", 2),
        ("Hayden", "Brandin Podziemski", "2026-11-02", 2),
        ("Hayden", "Anthony Black", "2026-11-02", 2),
        ("Benton", "Devin Booker", "2026-11-02", 2),
        ("Benton", "Caleb Wilson", "2026-11-02", 2),
        ("Nick", "Desmond Bane", "2026-11-02", 2),
        ("Nick", "Miles Bridges", "2026-11-02", 2)])


# ========================================== listing vs counting (s.3c)

WINDOW = {"txns": [
    ("2026-10-25", "Hayden", "Franz Wagner"), ("2026-10-25", "Hayden", "Zach LaVine"),
    ("2026-10-26", "Garrett", "Paul George"), ("2026-10-26", "Garrett", "Aaron Wiggins"),
    ("2026-10-26", "Garrett", "Toumani Camara"), ("2026-10-26", "Hayden", "Darius Acuff Jr."),
    ("2026-10-26", "Benton", "Nickeil Alexander-Walker"), ("2026-10-26", "Benton", "Paul George"),
    ("2026-10-26", "Benton", "Cameron Boozer"), ("2026-10-26", "Nick", "Damian Lillard"),
    ("2026-10-26", "Nick", "Dyson Daniels"), ("2026-10-26", "Nick", "Ty Jerome")]}


# The rulings as published in 2157743 (frozen): the live file is league state
# now (P2, 10-31). The listing/counting logic is checked on this copy in every
# checkout; test_the_real_10_26_window_counts checks the live files.
FROZEN_RULINGS = ROOT / "tests" / "fixtures" / "transaction_rulings_2026-10-31.json"


def frozen_world(tmp_path):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "SCHEDULE.json").write_text(
        (ROOT / "config" / "SCHEDULE.json").read_text("utf-8"), encoding="utf-8")
    (tmp_path / tr.RULINGS_FILE).write_text(FROZEN_RULINGS.read_text("utf-8"), encoding="utf-8")
    return tmp_path


def _sync_files(tmp_path, rulings_src=None):
    """Weeks 1 and 2 as `sync_transactions --week 1 --apply` writes them,
    from the 10-25/10-26 window, through the sync's own writer."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("st", ROOT / "scripts" / "sync_transactions.py")
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHEDULE))
    src = FROZEN_RULINGS if rulings_src is None else rulings_src / tr.RULINGS_FILE
    (tmp_path / tr.RULINGS_FILE).write_text(src.read_text("utf-8"))
    rulings = tr.load_all(tmp_path)
    txns = [txn("add", m, p, d) for d, m, p in WINDOW["txns"]]
    w1, a1 = tr.apply_to_transactions(txns, rulings, since=date(2026, 10, 20),
                                      until=date(2026, 10, 25), echo=lambda *_: None)
    st.write_waivers_file(w1, 1, tmp_path, applied=a1)
    w2, a2 = tr.apply_to_transactions(txns, rulings, since=date(2026, 10, 26),
                                      echo=lambda *_: None)
    st.write_waivers_file(w2, 2, tmp_path, partial=True, applied=a2)
    return tmp_path


def test_the_sync_lists_claims_in_their_yahoo_week_marked(tmp_path, capsys):
    base = _sync_files(tmp_path)
    w1 = (base / "data" / "waivers_week1.txt").read_text("utf-8")
    w2 = (base / "data" / "waivers_week2.txt").read_text("utf-8")
    assert "No waiver adds this week." in w1 and "Wagner" not in w1.split("\n\n", 1)[1]
    adds2 = [ln for ln in w2.splitlines() if ln.startswith("- [")]
    assert adds2 == [
        "- [2026-10-26] Hayden: Zach LaVine (week 1 add)",
        "- [2026-10-26] Garrett: Aaron Wiggins",
        "- [2026-10-26] Garrett: Toumani Camara",
        "- [2026-10-26] Hayden: Darius Acuff Jr. (week 1 claim)",
        "- [2026-10-26] Benton: Nickeil Alexander-Walker (week 1 claim)",
        "- [2026-10-26] Benton: Paul George (week 1 claim)",
        "- [2026-10-26] Benton: Cameron Boozer (week 1 claim)",
        "- [2026-10-26] Nick: Damian Lillard (week 1 claim)",
        "- [2026-10-26] Nick: Dyson Daniels (week 1 claim)",
        "- [2026-10-26] Nick: Ty Jerome (week 1 claim)"]
    # both files read back clean: every ruling is recorded where it applies
    for wk in (1, 2):
        tr.waiver_lines(base / "data" / f"waivers_week{wk}.txt", base, wk, SCHEDULE)


def test_counted_in_the_claim_week_even_though_listed_in_the_next(tmp_path):
    counts = tr.adds_by_budget_week(_sync_files(tmp_path), SCHEDULE)
    assert {w: {m: len(v) for m, v in by.items()} for w, by in counts.items()} == {
        1: {"Hayden": 2, "Benton": 3, "Nick": 3},
        2: {"Garrett": 2}}
    assert tr.over_budget(counts, 3) == []


def test_week_2_adds_left_before_and_after_the_rulings(tmp_path, monkeypatch):
    """Before: the 10-26 file counted every claim in week 2 (Hayden, Benton
    and Nick 0 left). After: 3, 1, 3, 3 (LaVine is a week 1 add: Nick, 11-01)."""
    from modules import report_builder as rb
    base = _sync_files(tmp_path)
    monkeypatch.setattr(rb, "__file__", str(base / "modules" / "report_builder.py"))

    class D:
        schedule = SCHEDULE
    out = rb.build_add_budget(D(), 1)
    assert {m: (v["used"], v["remaining"]) for m, v in out["managers"].items()} == {
        "Hayden": (0, 3), "Garrett": (2, 1), "Benton": (0, 3), "Nick": (0, 3)}
    assert out["over_budget_weeks"] == []


def test_a_file_written_before_the_ruling_gets_the_mark_at_read_time(tmp_path):
    base = world(tmp_path, [BOOZER], {2: ["- [2026-10-26] Benton: Cameron Boozer"]})
    lines, applied = tr.waiver_lines(base / "data" / "waivers_week2.txt", base, 2, SCHEDULE)
    assert "- [2026-10-26] Benton: Cameron Boozer (week 1 claim)" in lines and len(applied) == 1
    assert tr.adds_by_budget_week(base, SCHEDULE) == {1: {"Benton": ["Cameron Boozer"]}}


def test_the_rewrite_marks_claims_once_and_is_idempotent(tmp_path):
    base = world(tmp_path, [BOOZER], {2: ["- [2026-10-26] Benton: Cameron Boozer"]})
    path = base / "data" / "waivers_week2.txt"
    assert len(tr.rewrite_waivers_file(path, base, 2, SCHEDULE, echo=lambda *_: None)) == 1
    text = path.read_text("utf-8")
    assert "Cameron Boozer (week 1 claim)" in text and text.count("# RULING applied") == 1
    assert tr.rewrite_waivers_file(path, base, 2, SCHEDULE, echo=lambda *_: None) == []
    assert path.read_text("utf-8") == text


def test_no_parser_keeps_the_mark_in_a_player_name(tmp_path):
    from modules.weekly_stats import load_waiver_adds
    from modules.waiver_roi import parse_waiver_file
    line = "- [2026-10-26] Benton: Cameron Boozer (week 1 claim)"
    f = tmp_path / "waivers_week2.txt"
    f.write_text(line + "\n- [2026-10-27] Nick: X (via trade) \n"
                 "- [2026-10-26] Hayden: Zach LaVine (week 1 add)\n", encoding="utf-8")
    assert load_waiver_adds(str(f))["Benton"] == ["Cameron Boozer"]
    assert load_waiver_adds(str(f))["Hayden"] == ["Zach LaVine"]
    assert [a.player_name for a in parse_waiver_file(f)][-1] == "Zach LaVine"
    assert tr._parse_line("- [2026-10-26] Hayden: Zach LaVine (week 1 add)") == (
        "2026-10-26", "Hayden", "Zach LaVine")
    assert [a.player_name for a in parse_waiver_file(f)][0] == "Cameron Boozer"
    assert tr._parse_line(line) == ("2026-10-26", "Benton", "Cameron Boozer")
    p = tr.parse_add_line(line)
    assert (p["player"], p["via"], p["marked_claim_week"]) == ("Cameron Boozer", "", 1)


WAIVER_LINE_PARSERS = {"split_claim_mark", "_parse_line", "parse_add_line", "load_waiver_adds",
                       "parse_waiver_file", "load_all_waivers", "waiver_lines",
                       "adds_by_budget_week"}
# write or copy the files whole; they never read a line's player name
WAIVER_FILE_MOVERS = {"backfill_waivers.py", "build_dryrun_packet.py", "start_new_season.py",
                      "sync_transactions.py"}


def test_every_reader_of_a_waivers_file_goes_through_a_parser_that_strips_the_mark():
    offenders = []
    for path in sorted([*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py")]):
        if path.name in WAIVER_FILE_MOVERS or path.name == "transaction_rulings.py":
            continue
        src = path.read_text(encoding="utf-8")
        if "waivers_week" in src and not any(n in src for n in WAIVER_LINE_PARSERS):
            offenders.append(path.name)
    assert not offenders, offenders


# ========================================== 4. one function decides the week

BUDGET_NAMES = {"add_budget_for", "WEEKLY_ADD_BUDGET", "weekly_add_budget"}
FILE_READERS = {"load_waiver_adds", "parse_waiver_file", "load_all_waivers", "waiver_lines"}
DECIDERS = {"add_budget_week", "adds_by_budget_week"}


def _names(fn) -> set:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.update(re.findall(r"[A-Za-z_]+", node.value))
    return out


def _calls(fn) -> set:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", None))
    return out


def _functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_no_module_counts_adds_by_week_but_through_add_budget_week():
    """A function that holds an add budget AND reads the synced adds is an add
    counter, and must get each add's week from add_budget_week (directly or
    through adds_by_budget_week). Inside transaction_rulings, the week of a
    date is taken only where a ruling is placed or validated, and in
    add_budget_week itself."""
    offenders, counters = [], []
    for path in sorted([*(ROOT / "modules").glob("*.py"), *(ROOT / "scripts").glob("*.py")]):
        if path.name == "transaction_rulings.py":
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(r"from\s+\.?\.?(modules\.)?transaction_rulings\s+import[^\n]*\b(week_of|_placed|_first_day)\b", src):
            offenders.append(f"{path.name} imports transaction_rulings' week arithmetic")
        for fn in _functions(path):
            names, calls = _names(fn), _calls(fn)
            reads = bool(calls & FILE_READERS) or "waivers_week" in names
            if names & BUDGET_NAMES and reads:
                counters.append(f"{path.name}:{fn.name}")
                if not calls & DECIDERS:
                    offenders.append(f"{path.name}:{fn.name}")
            if calls & {"adds_by_budget_week"}:
                counters.append(f"{path.name}:{fn.name}")
    assert not offenders, offenders
    assert set(counters) == {"report_builder.py:build_add_budget", "advice_runner.py:build_advice"}

    tr_path = ROOT / "modules" / "transaction_rulings.py"
    week_callers = {fn.name for fn in _functions(tr_path) if "week_of" in _calls(fn)}
    # made_in_mark: the "(week N add)" listing mark, not a budget
    assert week_callers == {"load_all", "_placed", "add_budget_week", "_add_on_file",
                            "made_in_mark"}
    by_name = {fn.name: fn for fn in _functions(tr_path)}
    assert "add_budget_week" in _calls(by_name["adds_by_budget_week"])


# ===================================================== 5. the real 10-26 data

def _real_counts():
    """{week: {manager: [players]}} from the real data/waivers_week1-2.txt,
    through the same functions every counter uses."""
    schedule = json.loads((ROOT / "config" / "SCHEDULE.json").read_text("utf-8"))
    rulings = tr.load_all(ROOT, schedule)
    out = {}
    for wk in (1, 2):
        lines, _ = tr.waiver_lines(ROOT / "data" / f"waivers_week{wk}.txt", ROOT, wk, schedule)
        for ln in lines:
            p = tr.parse_add_line(ln)
            if p and (bw := tr.add_budget_week(p, rulings, schedule)) is not None:
                out.setdefault(bw, {}).setdefault(p["manager"], []).append(p["player"])
    return out


@pytest.mark.skipif(not all((ROOT / "data" / f"waivers_week{w}.txt").is_file() for w in (1, 2)),
                    reason="the synced waivers files are not here (CI)")
def test_the_real_10_26_window_counts():
    try:
        got = _real_counts()
    except tr.RulingError as e:
        pytest.fail("data/waivers_week1.txt and week 2's were written before the league clock and "
                    "these rulings; regenerate them with `python scripts/sync_transactions.py "
                    f"--week 1 --apply` (claude/CLAIM_WEEK_RULINGS_RESULT_2026-10-31.md): {e}")
    # weeks 1-2's files only: the 10-25/10-26 window. LaVine is a week 1 add
    # (made Sun 10-25; Nick, 11-01); the week-2 chat claims are in week 3's file.
    assert got == {
        1: {"Hayden": ["Zach LaVine", "Darius Acuff Jr."],
            "Benton": ["Nickeil Alexander-Walker", "Paul George", "Cameron Boozer"],
            "Nick": ["Damian Lillard", "Dyson Daniels", "Ty Jerome"]},
        2: {"Garrett": ["Aaron Wiggins", "Toumani Camara"]}}


@needs_state("data/waivers_week1.txt", "data/waivers_week2.txt", "data/waivers_week3.txt",
             "config/TRANSACTION_RULINGS.json", "config/SCHEDULE.json",
             why="the season's real add table (HANDOFF_SECTION10_OFF_AND_BUDGET_WEEK, 11-02)")
def test_the_real_add_table_weeks_1_to_3():
    """The brief's table, through adds_by_budget_week (every counter's
    source). Wagner (Hayden, void 10-25) and Garrett's Paul George (void
    10-26) are not adds; pre-season adds count nowhere; nobody is over."""
    schedule = json.loads((ROOT / "config" / "SCHEDULE.json").read_text("utf-8"))
    counts = tr.adds_by_budget_week(ROOT, schedule)
    got = {w: {m: sorted(v) for m, v in by.items()} for w, by in counts.items()}
    assert got == {
        1: {"Nick": ["Damian Lillard", "Dyson Daniels", "Ty Jerome"],
            "Hayden": ["Darius Acuff Jr.", "Zach LaVine"],
            "Benton": ["Cameron Boozer", "Nickeil Alexander-Walker", "Paul George"]},
        2: {"Nick": ["Desmond Bane", "Miles Bridges"],
            "Hayden": ["Anthony Black", "Brandin Podziemski", "Yaxel Lendeborg"],
            "Benton": ["Caleb Wilson", "Devin Booker"],
            "Garrett": ["Aaron Wiggins", "Toumani Camara"]}}
    assert 3 not in got                                     # week 3 so far: nobody
    assert "Franz Wagner" not in str(got)
    assert "Paul George" not in got[1].get("Garrett", []) + got[2]["Garrett"]
    assert tr.over_budget(counts, 3) == []


def test_the_syncs_next_week_file_holds_only_next_weeks_transactions():
    """Found 11-02: `--week 1` run once week 3 had opened put week 3's adds
    (the 11-02 week-2 claims) into week 2's partial file, where every reader
    raised. The partial file's window ends with week N+1."""
    src = (ROOT / "scripts" / "sync_transactions.py").read_text("utf-8")
    call = re.search(r"post_counted, post_applied = apply_to_transactions\((.*?)\)\n", src, re.S)
    assert call and "until=next_end" in call.group(1), "the week N+1 file's window must be capped"
    assert "get_week_date_range(schedule, args.week + 1)[1]" in src
