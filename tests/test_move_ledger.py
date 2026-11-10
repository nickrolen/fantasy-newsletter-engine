"""The move ledger (step 2): claude/HANDOFF_STEP2_MOVE_LEDGER_2026-11-05.md s.3;
claude/SELF_RUNNING_DESIGN.md s.6.1-6.4 and invariants 10, 10a, 11.

Every check is on a world built in memory (move_ledger.World), except the
11-02 replay, which reads the real transaction log and skips without it.
Nothing here writes a league file: the ledger files are written in tmp_path.
"""
import ast
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import move_ledger as ml                  # noqa: E402
from modules import transaction_rulings as tr          # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
M = ["Nick", "Hayden", "Garrett", "Benton"]
WEEKS = {2: (date(2026, 10, 26), date(2026, 11, 1)), 3: (date(2026, 11, 2), date(2026, 11, 8)),
         4: (date(2026, 11, 9), date(2026, 11, 15)), 5: (date(2026, 11, 16), date(2026, 11, 22))}
FREE = ["Desmond Bane", "Anthony Black", "Leaky Black", "Kawhi Leonard", "Devin Booker", "Miles Bridges"]


def at(day, hh=12, mm=0):
    return datetime.combine(date.fromisoformat(day), time(hh, mm), tzinfo=LA)


def close(d):
    return datetime.combine(d, time(18, 55), tzinfo=LA)


def gen(m, n):
    return [f"Pat {m}{i:02d}" for i in range(1, n + 1)]


def make_world(now=None, yahoo=None, txs=(), il=None, il_week=None, tags=None, overrides=()):
    rosters = {"Nick": gen("Nick", 14) + ["Anthony Edwards", "Paolo Banchero"],
               "Hayden": gen("Hayden", 15) + ["Tyrese Haliburton", "Chet Holmgren"],
               "Garrett": gen("Garrett", 15) + ["Alex Sarr"],
               "Benton": gen("Benton", 14) + ["Nickeil Alexander-Walker"]}
    il = il if il is not None else {"Nick": ["Paolo Banchero"],
                                    "Hayden": ["Tyrese Haliburton", "Chet Holmgren"],
                                    "Garrett": ["Alex Sarr"], "Benton": []}
    t = {"Anthony Edwards": "O", "Paolo Banchero": "OFS", "Tyrese Haliburton": "O", "Chet Holmgren": "O",
         "Alex Sarr": "O", "Kawhi Leonard": "O", "Pat Hayden01": "O"}
    t.update(tags or {})
    everyone = [n for v in rosters.values() for n in v] + FREE
    yahoo = yahoo or {}
    w = ml.World(now=now or at("2026-11-05"), weeks=WEEKS, window_close=close, managers=M,
                 rosters=rosters, il=il, il_week=il_week or 3, playerlist=everyone, universe=everyone,
                 tags=t, overrides=list(overrides), yahoo_adds=lambda claims: json.loads(json.dumps(yahoo),
                 object_hook=lambda d: {int(k) if k.isdigit() else k: v for k, v in d.items()}),
                 transactions=list(txs), verify_from=date(2026, 11, 3))
    return w


def enter(w, rows, text, states=(), claimed_at=None):
    row = ml.make_entry(w, text, rows, list(states), claimed_at=claimed_at, entered_by="test")
    rows.append(row)
    return row


def refused(w, rows, text, *bits, claimed_at=None):
    with pytest.raises(ml.EntryRefused) as e:
        ml.make_entry(w, text, rows, [], claimed_at=claimed_at)
    for b in bits:
        assert b in str(e.value), str(e.value)
    return str(e.value)


# =============================================================================
# the grammar
# =============================================================================

@pytest.mark.parametrize("text,want", [
    ("Benton move: +Bane -Alexander-Walker",
     {"kind": "move", "manager": "Benton", "add": ["Bane"], "drop": ["Alexander-Walker"], "il_place": [],
      "il_activate": []}),
    ("Nick move: +Bane IL+Edwards",
     {"kind": "move", "manager": "Nick", "add": ["Bane"], "drop": [], "il_place": ["Edwards"],
      "il_activate": []}),
    ("hayden MOVE: IL-Leonard -Wagner",
     {"kind": "move", "manager": "Hayden", "add": [], "drop": ["Wagner"], "il_place": [],
      "il_activate": ["Leonard"]}),
    ("Benton move: -Bane", {"kind": "move", "manager": "Benton", "add": [], "drop": ["Bane"],
                            "il_place": [], "il_activate": []}),
    ("Nick move: +Jaren Jackson Jr. -Day'Ron Sharpe IL+Edwards IL-Banchero",
     {"kind": "move", "manager": "Nick", "add": ["Jaren Jackson Jr."], "drop": ["Day'Ron Sharpe"],
      "il_place": ["Edwards"], "il_activate": ["Banchero"]}),
    ("Trade: Benton gets Tatum; Hayden gets Barnes, Tyrese Maxey",
     {"kind": "trade", "sides": [{"manager": "Benton", "gets": ["Tatum"]},
                                 {"manager": "Hayden", "gets": ["Barnes", "Tyrese Maxey"]}]}),
])
def test_every_grammar_form_parses(text, want):
    assert ml.parse(text, M) == want


@pytest.mark.parametrize("text,why", [
    ("", "an empty entry"),
    ("Bob move: +Bane", "'Bob' is not a manager"),
    ("Nick move:", "a move with no parts"),
    ("Nick move: Bane", "before the first part"),
    ("Nick move: +Bane +Black", "two + parts in one entry"),
    ("Nick move: +Bane -Bane", "named twice"),
    ("Nick move: + -Jerome", "before the first part"),
    ("Nick adds Bane", "not an entry"),
    ("Trade: Nick gets Tatum", "exactly two sides"),
    ("Trade: Nick gets Tatum; Nick gets Bane", "two different managers"),
    ("Trade: Nick takes Tatum; Benton gets Bane", "is not '<Manager> gets"),
    ("Trade: Nick gets Tatum,; Benton gets Bane", "an empty player name"),
    ("Nick move: +Bane\nNick move: +Black", "one entry per line"),
])
def test_each_malformed_form_refuses_with_its_reason(text, why):
    with pytest.raises(ml.EntryRefused) as e:
        ml.parse(text, M)
    assert why in str(e.value)


def test_unknown_and_ambiguous_names_refuse_with_candidates():
    w = make_world()
    refused(w, [], "Nick move: +Black IL+Edwards", "could be Anthony Black, Leaky Black",
            "write the full name")
    refused(w, [], "Nick move: +Bnae IL+Edwards", "matches no player", "nearest: Desmond Bane")
    refused(w, [], "Nick move: +Zzyzx IL+Edwards", "matches no player")
    # a full name, accents and case aside, resolves
    row = enter(w, [], "Nick move: +anthony black IL+Edwards")
    assert row["parsed"]["add"] == ["Anthony Black"] and row["parsed"]["il_place"] == ["Anthony Edwards"]


def test_a_drop_resolves_on_his_roster_and_says_whose_he_is_otherwise():
    w = make_world()
    refused(w, [], "Benton move: -Edwards", "Anthony Edwards is not on Benton's roster")


# =============================================================================
# the pool: a claim reserves (rule 10), a chat drop frees (rule 11)
# =============================================================================

def test_a_claim_of_a_reserved_player_refuses():
    w, rows = make_world(), []
    enter(w, rows, "Nick move: +Bane IL+Edwards")
    refused(w, rows, "Benton move: +Bane -Alexander-Walker", "Desmond Bane is reserved",
            "Nick claimed him (entry 1", "rule 10")


def test_a_chat_dropped_player_is_claimable_at_once():
    w, rows = make_world(), []
    enter(w, rows, "Benton move: -Alexander-Walker")
    row = enter(w, rows, "Nick move: +Alexander-Walker IL+Edwards")
    assert row["parsed"]["add"] == ["Nickeil Alexander-Walker"]
    assert any("dropped in the chat, entry 1" in c for c in row["checks"])
    pool = ml.pool(w, ml.entries(rows))
    assert "Nickeil Alexander-Walker" not in pool and "Desmond Bane" in pool


def test_a_rostered_player_is_not_a_free_agent():
    w = make_world()
    refused(w, [], "Benton move: +Edwards -Alexander-Walker", "Anthony Edwards is on Nick's roster")


# =============================================================================
# the add budget (rule 7, design s.6.1a)
# =============================================================================

def test_a_team_at_3_adds_in_a_claim_week_is_refused_a_4th_yahoos_6_notwithstanding():
    w, rows = make_world(yahoo={3: {"Benton": ["Davion Mitchell", "Some One"]}}), []
    enter(w, rows, "Benton move: +Bane -Alexander-Walker")                 # his 3rd in week 3
    why = refused(w, rows, "Benton move: +Leaky Black -Pat Benton01", "has used 3 of 3 adds in week 3",
                  "Yahoo's 6 notwithstanding")
    assert "Desmond Bane" in why
    # the same claim posted in week 4 (Monday 00:30, the league clock) uses week 4's budget
    w4 = make_world(now=at("2026-11-09", 0, 30), yahoo={3: {"Benton": ["Davion Mitchell", "Some One"]}})
    row = enter(w4, list(rows), "Benton move: +Leaky Black -Pat Benton01")
    assert row["claim_week"] == 4 and row["window"] == "2026-11-16"


def test_a_sunday_2330_claim_counts_in_that_sundays_week():
    w = make_world(now=at("2026-11-09", 0, 40))
    row = enter(w, [], "Nick move: +Bane IL+Edwards", claimed_at=at("2026-11-08", 23, 30))
    assert row["claim_week"] == 3 and row["window"] == "2026-11-09" and row["window_week"] == 4


def test_a_claim_whose_window_has_closed_refuses():
    w = make_world(now=at("2026-11-09", 20, 0))
    refused(w, [], "Nick move: +Bane IL+Edwards", "has closed", claimed_at=at("2026-11-08", 23, 0))


def test_a_claim_time_in_the_future_or_pre_season_refuses():
    w = make_world()
    refused(w, [], "Nick move: +Bane IL+Edwards", "in the future", claimed_at=at("2026-11-06"))
    refused(w, [], "Nick move: +Bane IL+Edwards", "pre-season", claimed_at=at("2026-10-12"))


def test_a_pending_claim_counts_once_and_its_yahoo_add_does_not_double_it():
    w, rows = make_world(), []
    enter(w, rows, "Nick move: +Bane IL+Edwards")
    assert ml.adds_used(w, ml.entries(rows), [], 3) == {"Nick": ["Desmond Bane"]}
    tx = txn(1, "2026-11-09T08:00:00-08:00", [("add", "Desmond Bane", None, "Nick")])
    claims = ml.budget_claims(ml.entries(rows))
    w2 = make_world(txs=[tx], yahoo={3: {"Nick": ["Desmond Bane"]}})       # the sync counted it, by the ledger
    assert ml.adds_used(w2, ml.entries(rows), [], 3) == {"Nick": ["Desmond Bane"]}
    assert claims == [{"manager": "Nick", "player": "Desmond Bane", "window": "2026-11-09", "claim_week": 3,
                       "entry": 1}]


# =============================================================================
# the roster after the window (rules 1-3, 15)
# =============================================================================

def test_an_add_over_15_active_with_no_il_placement_refuses():
    w = make_world()
    refused(w, [], "Nick move: +Bane", "Nick's roster is full",
            "add a drop (-Player) or an IL placement (IL+Player)")


def test_il_plus_of_a_non_o_player_refuses():
    w = make_world()
    refused(w, [], "Nick move: +Bane IL+Pat Nick01", "tagged healthy", "only O or OFS", "rule 2")
    w = make_world(tags={"Pat Nick02": "Q"})
    refused(w, [], "Nick move: +Bane IL+Pat Nick02", "tagged Q", "only O or OFS")


def test_il_plus_with_a_live_injury_entry_is_accepted_with_a_warning():
    # task 47: at entry only, and with a warning; the window reads the tag alone
    # (tests/test_il_tag_rule.py has the rest)
    entry = {"player_name": "Pat Nick02", "out_weeks": [4, 5], "return_week": 6}
    w = make_world(overrides=[entry])
    row = enter(w, [], "Nick move: +Bane IL+Pat Nick02")
    assert any("injury entry" in c for c in row["checks"])
    assert row["warnings"] and "must be by Monday's window" in row["warnings"][0]


def test_il_plus_of_a_player_already_in_il_refuses_naming_the_slot():
    w = make_world()
    refused(w, [], "Nick move: IL+Banchero", "already in an IL slot (Nick's IL: Paolo Banchero)")


def test_a_full_il_refuses_a_placement_unless_it_is_a_swap():
    w = make_world()
    refused(w, [], "Hayden move: IL+Pat Hayden01 -Pat Hayden02", "IL slots are full")
    rows = []
    enter(w, rows, "Hayden move: IL+Pat Hayden01 IL-Haliburton")
    cl = ml.checklist(w, rows, [], 4)
    assert [x["phase"] for x in cl["lines"]] == ["il_swap"]
    assert "swap Pat Hayden01 into the IL slot, Tyrese Haliburton out" in cl["lines"][0]["text"]


def test_an_activation_needs_room():
    w = make_world()
    refused(w, [], "Garrett move: IL-Sarr", "Garrett's active roster is full", "needs a drop")
    enter(w, [], "Garrett move: IL-Sarr -Pat Garrett01")


def test_a_valid_entry_records_its_checks_and_weeks():
    w = make_world()
    row = enter(w, [], "Nick move: +Bane IL+Edwards")
    assert row["id"] == 1 and row["claim_week"] == 3 and row["window_week"] == 4 \
        and row["window"] == "2026-11-09"
    assert "Nick after the 11-09 window: 15 active, 2 IL" in row["checks"]
    assert "week 3 adds: 0 used before, 1 of 3 with this one" in row["checks"]


# =============================================================================
# rule 12: a claimed player dropped before he joins
# =============================================================================

def test_rule_12_claim_then_drop_is_add_then_drop_in_the_same_window_and_the_add_counts():
    w, rows = make_world(), []
    enter(w, rows, "Nick move: +Bane IL+Edwards")
    row = enter(w, rows, "Nick move: -Bane")
    assert row["window"] == "2026-11-09" and row["parsed"]["drop"] == ["Desmond Bane"]
    cl = ml.checklist(w, rows, [], 4)
    texts = [x["text"] for x in cl["lines"]]
    assert texts == ["Nick: move Anthony Edwards into an IL slot", "Nick: add Desmond Bane",
                     "Nick: drop Desmond Bane (just added; rule 12)"]
    assert ml.adds_used(w, ml.entries(rows), [], 3) == {"Nick": ["Desmond Bane"]}
    # and he is free for the coming week again (rule 11)
    assert "Desmond Bane" in ml.pool(w, ml.entries(rows))


def test_a_claim_cannot_be_cancelled_only_voided_as_nicks_mistake(tmp_path):
    (tmp_path / "config").mkdir()
    w = make_world()
    ml.add(tmp_path, "Nick move: +Bane IL+Edwards", world=w)
    before = ml.read_rows(tmp_path)[0]
    with pytest.raises(ml.EntryRefused, match="needs a reason"):
        ml.void(tmp_path, 1, "")
    ml.void(tmp_path, 1, "typed the wrong manager", now=at("2026-11-05", 13))
    rows = ml.read_rows(tmp_path)
    assert rows[0] == before                                          # the entry is untouched
    assert ml.state_of(ml.entries(rows)[0], []) == "void"
    assert ml.budget_claims(ml.entries(rows)) == []
    with pytest.raises(ml.EntryRefused, match="already voided"):
        ml.void(tmp_path, 1, "again")


# =============================================================================
# the checklist (design s.6.4)
# =============================================================================

def test_checklist_order_il_then_drops_then_adds_then_activations_and_every_drop_before_every_add():
    w, rows = make_world(), []
    enter(w, rows, "Benton move: -Alexander-Walker")
    enter(w, rows, "Nick move: +Alexander-Walker IL+Edwards")
    enter(w, rows, "Garrett move: IL-Sarr -Pat Garrett01")
    enter(w, rows, "Benton move: +Bane")
    cl = ml.checklist(w, rows, [], 4)
    phases = [x["phase"] for x in cl["lines"]]
    assert phases == ["il_place", "drop", "drop", "add", "add", "il_activate"]
    last_drop = max(i for i, p in enumerate(phases) if p == "drop")
    first_add = min(i for i, p in enumerate(phases) if p == "add")
    assert last_drop < first_add
    for team in M:
        mine = [x["phase"] for x in cl["lines"] if x["team"] == team]
        order = ["il_place", "drop", "add", "il_activate"]
        assert mine == sorted(mine, key=order.index)
    assert [x["n"] for x in cl["lines"]] == list(range(1, 7))
    assert cl["stopped"] == []


def test_an_unorderable_team_stops_with_its_reason_and_the_others_go_on():
    w, rows = make_world(), []
    enter(w, rows, "Nick move: +Bane IL+Edwards")
    enter(w, rows, "Benton move: +Leaky Black -Pat Benton01")
    # Monday: Edwards is healthy again, so he cannot go into the IL slot (rule 2)
    w2 = make_world(now=at("2026-11-09", 0, 2), tags={"Anthony Edwards": "HEALTHY"})
    cl = ml.checklist(w2, rows, [], 4)
    assert [s["team"] for s in cl["stopped"]] == ["Nick"]
    assert "only O or OFS" in cl["stopped"][0]["reason"] and cl["stopped"][0]["entries"] == [1]
    assert [x["team"] for x in cl["lines"]] == ["Benton", "Benton"]
    assert "STOPPED Nick" in "\n".join(ml.format_checklist(cl))


def test_a_healthy_player_in_an_il_slot_stops_his_teams_lines_rule_3():
    w, rows = make_world(), []
    enter(w, rows, "Garrett move: IL-Sarr -Pat Garrett01")
    enter(w, rows, "Benton move: +Bane -Pat Benton01")
    w2 = make_world(now=at("2026-11-09", 0, 2), tags={"Alex Sarr": "HEALTHY"})
    cl = ml.checklist(w2, rows, [], 4)
    assert [s["team"] for s in cl["stopped"]] == ["Garrett"] and "rule 3" in cl["stopped"][0]["reason"]
    assert [x["team"] for x in cl["lines"]] == ["Benton", "Benton"]


def test_ledger_py_check_finds_what_changed_since_entry():
    w, rows = make_world(), []
    enter(w, rows, "Nick move: +Bane IL+Edwards")
    assert ml.recheck(w, rows, []) == [(1, "ok")]
    w2 = make_world(tags={"Anthony Edwards": "Q"})
    (eid, why), = ml.recheck(w2, rows, [])
    assert eid == 1 and "tagged Q" in why


def test_trades():
    w, rows = make_world(), []
    refused(w, rows, "Trade: Benton gets Banchero; Nick gets Alexander-Walker", "in Nick's IL slot")
    row = enter(w, rows, "Trade: Benton gets Pat Nick01; Nick gets Alexander-Walker")
    assert row["kind"] == "trade" and row["claim_week"] == 3
    assert ml.budget_claims(ml.entries(rows)) == []                       # trades use no adds (rule 6)
    cl = ml.checklist(w, rows, [], 4)
    assert {x["text"] for x in cl["lines"]} == {"Benton gets Pat Nick01 from Nick (trade)",
                                                "Nick gets Nickeil Alexander-Walker from Benton (trade)"}
    w2 = make_world(now=at("2027-03-05"))
    w2.weeks = {**WEEKS, 19: (date(2027, 3, 1), date(2027, 3, 7)), 20: (date(2027, 3, 8), date(2027, 3, 14))}
    refused(w2, [], "Trade: Benton gets Pat Nick01; Nick gets Alexander-Walker", "trade deadline was 2027-03-04")


# =============================================================================
# verification (design s.6.4, invariant 11)
# =============================================================================

def txn(i, when, players, key=None):
    """players: [(action, name, from manager, to manager)]."""
    t = datetime.fromisoformat(when)
    return {"row": "transaction", "key": key or f"t.{i}", "id": i,
            "type": "add/drop" if len(players) > 1 else players[0][0], "status": "successful",
            "timestamp": int(t.timestamp()), "time": when, "league_day": t.date().isoformat(),
            "players": [{"name": n, "action": a,
                         "from": {"type": "team" if f else "freeagents", "manager": f},
                         "to": {"type": "team" if to else "freeagents", "manager": to}}
                        for a, n, f, to in players], "rulings": []}


def _entered(*texts):
    w, rows = make_world(), []
    for t in texts:
        enter(w, rows, t)
    return rows


AFTER = at("2026-11-10", 0, 5)
IL_AFTER = {"Nick": ["Paolo Banchero", "Anthony Edwards"], "Hayden": ["Tyrese Haliburton", "Chet Holmgren"],
            "Garrett": ["Alex Sarr"], "Benton": []}


def test_verification_applied():
    rows = _entered("Nick move: +Bane IL+Edwards")
    w = make_world(now=AFTER, txs=[txn(1, "2026-11-09T08:00:00-08:00", [("add", "Desmond Bane", None, "Nick")])],
                   il=IL_AFTER, il_week=4)
    new, rep = ml.verify(w, rows, [], run_id="r1")
    assert [(r["entry"], r["state"], r["transactions"]) for r in new] == [(1, "applied", ["t.1"])]
    assert rep["flags"] == []


def test_verification_waits_for_the_close_for_il_and_never_marks_missing_early():
    rows = _entered("Nick move: +Bane IL+Edwards")
    w = make_world(now=at("2026-11-09", 9), txs=[txn(1, "2026-11-09T08:00:00-08:00",
                                                      [("add", "Desmond Bane", None, "Nick")])])
    new, rep = ml.verify(w, rows, [], run_id="r1")
    assert new == [] and len(rep["pending"]) == 1


def test_verification_missing():
    rows = _entered("Nick move: +Bane IL+Edwards")
    w = make_world(now=AFTER, il=IL_AFTER, il_week=4)
    new, rep = ml.verify(w, rows, [], run_id="r1")
    assert [(r["entry"], r["state"]) for r in new] == [(1, "missing")]
    assert "+Desmond Bane" in new[0]["why"] and rep["flags"][0].startswith("MISSING")
    # an IL part Yahoo does not show is missing too
    w = make_world(now=AFTER, txs=[txn(1, "2026-11-09T08:00:00-08:00", [("add", "Desmond Bane", None, "Nick")])],
                   il_week=4)
    new, _ = ml.verify(w, rows, [], run_id="r1")
    assert new[0]["state"] == "missing" and "IL+Anthony Edwards" in new[0]["why"]


def test_verification_conflict_reserved_player_taken_and_applied_twice():
    rows = _entered("Nick move: +Bane IL+Edwards")
    w = make_world(now=at("2026-11-07"), txs=[txn(1, "2026-11-06T09:00:00-08:00",
                                                   [("add", "Desmond Bane", None, "Hayden")])])
    new, rep = ml.verify(w, rows, [], run_id="r1")
    assert new[0]["state"] == "conflict" and "reserved by Nick" in new[0]["why"]
    assert any(f.startswith("CONFLICT") for f in rep["flags"])
    w = make_world(now=AFTER, il=IL_AFTER, il_week=4, txs=[
        txn(1, "2026-11-09T08:00:00-08:00", [("add", "Desmond Bane", None, "Nick")]),
        txn(2, "2026-11-09T08:05:00-08:00", [("add", "Desmond Bane", None, "Nick")])])
    new, _ = ml.verify(w, rows, [], run_id="r1")
    assert new[0]["state"] == "conflict" and "applied 2 times" in new[0]["why"]


def test_a_move_outside_a_window_matching_no_entry_is_flagged_once():
    tx_out = txn(1, "2026-11-06T09:00:00-08:00", [("add", "Kawhi Leonard", None, "Garrett")])
    tx_in = txn(2, "2026-11-09T09:00:00-08:00", [("add", "Miles Bridges", None, "Benton")])
    tx_late = txn(3, "2026-11-09T19:30:00-08:00", [("drop", "Pat Benton01", "Benton", None)])
    tx_old = txn(4, "2026-10-25T22:40:00-07:00", [("add", "Zach LaVine", None, "Hayden")])
    w = make_world(now=AFTER, txs=[tx_out, tx_in, tx_late, tx_old], il=IL_AFTER, il_week=4)
    new, rep = ml.verify(w, [], [], run_id="r1")
    assert sorted(r["key"] for r in new) == ["t.1", "t.3"]          # in-window direct adds are fine
    assert all(r["row"] == "unmatched" for r in new) and len(rep["unmatched"]) == 2
    again, rep2 = ml.verify(w, [], new, run_id="r2")
    assert again == [] and rep2["flags"] == []


def test_a_settled_entry_is_never_verified_again():
    rows = _entered("Nick move: +Bane IL+Edwards")
    states = [{"row": "state", "entry": 1, "state": "missing", "at": "x", "by": "r0", "why": "w",
               "transactions": []}]
    w = make_world(now=AFTER, txs=[txn(1, "2026-11-09T08:00:00-08:00", [("add", "Desmond Bane", None, "Nick")])],
                   il=IL_AFTER, il_week=4)
    assert ml.verify(w, rows, states, run_id="r1")[0] == []


# =============================================================================
# the 11-02 window, replayed from the real transaction log
# =============================================================================

REPLAY = [  # the week-2 group-chat claims, applied in Yahoo in week 3's window (LEAGUE_RULES rule 7)
    ("Hayden move: +Yaxel Lendeborg", "2026-10-26 22:00"),
    ("Benton move: +Devin Booker -Nickeil Alexander-Walker", "2026-10-30 08:00"),
    ("Nick move: +Desmond Bane IL+Anthony Edwards", "2026-10-30 08:15"),
    # claim times not on record: any time in week 2 gives the same week
    ("Hayden move: +Anthony Black", "2026-10-31 12:00"),
    ("Hayden move: +Brandin Podziemski", "2026-10-31 12:01"),
    ("Benton move: +Caleb Wilson", "2026-10-31 12:02"),
    ("Nick move: +Miles Bridges -Ty Jerome", "2026-10-31 12:03"),
]
IL_WEEK3 = {"Benton": ["Jayson Tatum"], "Garrett": ["Alex Sarr", "Kon Knueppel"],
            "Hayden": ["Chet Holmgren", "Tyrese Haliburton"], "Nick": ["Anthony Edwards", "Paolo Banchero"]}


def _replay_rows():
    rows = []
    for i, (text, when) in enumerate(REPLAY, start=1):
        p = ml.parse(text, M)
        rows.append({"row": "entry", "id": i, "text": text, "kind": "move", "parsed":
                     {k: v for k, v in p.items() if k != "kind"},
                     "claimed_at": ml._parse_at(when).isoformat(), "claim_week": 2, "window_week": 3,
                     "window": "2026-11-02", "entered_at": "2026-11-05T09:00:00-08:00",
                     "entered_by": "test replay", "checks": []})
    return rows


@pytest.fixture(scope="module")
def real_log():
    from modules import transaction_log as tlog
    if not (ROOT / tlog.LOG_FILE).is_file():
        pytest.skip("league state not in this checkout (the transaction log)")
    sched = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    return tlog.transactions(ROOT), sched


def test_the_11_02_window_replayed_gives_applied_for_all_seven(real_log):
    from modules import price_lock
    txs, sched = real_log
    weeks = {int(w["week"]): (date.fromisoformat(w["start_date"][:10]), date.fromisoformat(w["end_date"][:10]))
             for w in sched["weeks"]}
    w = ml.World(now=at("2026-11-03", 0, 5), weeks=weeks, window_close=price_lock.window_close, managers=M,
                 rosters={}, il=IL_WEEK3, il_week=3, playerlist=[], universe=[], tags={}, overrides=[],
                 yahoo_adds=lambda c: {}, transactions=[t for t in txs if t["league_day"] <= "2026-11-02"],
                 verify_from=date(2026, 10, 27))
    rows = _replay_rows()
    new, rep = ml.verify(w, rows, [], run_id="replay")
    assert [(r["entry"], r["state"]) for r in new] == [(i, "applied") for i in range(1, 8)], rep
    assert rep["flags"] == [] and rep["unmatched"] == []
    # every claim's Yahoo add is matched: Bane and Bridges are Nick's, Booker Benton's, ...
    keys = {r["entry"]: r["transactions"] for r in new}
    assert all(keys.values())


def test_the_11_02_replay_counts_match_the_claim_week_rulings(real_log):
    """The shadow comparison's first real test: the seven claims counted by the
    ledger alone (their claim_week rulings set aside) land where the rulings
    put them -- week 2 -- and every other add where it was."""
    txs, sched = real_log
    rulings = tr.load_all(ROOT, sched)
    without = [r for r in rulings if not (r.kind == "claim_week" and int(r.claim_week) == 2)]
    claims = ml.budget_claims(ml.entries(_replay_rows()))
    by_rulings, by_ledger = {}, {}
    for t in txs:
        if t["league_day"] != "2026-11-02":
            continue
        for p in t["players"]:
            if p["action"] != "add":
                continue
            a = {"date": t["league_day"], "manager": p["to"]["manager"], "player": p["name"]}
            for out, rs, led in ((by_rulings, rulings, None), (by_ledger, without, claims)):
                wk = tr.add_budget_week(a, rs, sched, led)
                out.setdefault(wk, {}).setdefault(a["manager"], []).append(a["player"])
    assert by_ledger == by_rulings
    assert sum(len(v) for v in by_ledger[2].values()) == 7


# =============================================================================
# add_budget_week takes the ledger (invariant 10a; "on" mode)
# =============================================================================

SCHED = {"weeks": [{"week": w, "start_date": a.isoformat(), "end_date": b.isoformat()}
                   for w, (a, b) in sorted(WEEKS.items())]}


def _tr_world(tmp_path, rulings=(), files=None):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / tr.RULINGS_FILE).write_text(json.dumps({"rulings": list(rulings)}))
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHED))
    for wk, lines in (files or {}).items():
        (tmp_path / "data" / f"waivers_week{wk}.txt").write_text(
            f"# Waiver Adds for Week {wk}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


CLAIM = [{"manager": "Nick", "player": "Desmond Bane", "window": "2026-11-09", "claim_week": 3, "entry": 1}]
ADD = {"date": "2026-11-09", "manager": "Nick", "player": "Desmond Bane"}


def test_add_budget_week_puts_a_ledger_claim_in_its_claim_week(tmp_path):
    rulings = tr.load_all(_tr_world(tmp_path), SCHED)
    assert tr.add_budget_week(ADD, rulings, SCHED) == 4                    # the rulings alone
    assert tr.add_budget_week(ADD, rulings, SCHED, CLAIM) == 3              # the ledger
    other = {"date": "2026-11-09", "manager": "Benton", "player": "Davion Mitchell"}
    assert tr.add_budget_week(other, rulings, SCHED, CLAIM) == 4            # a direct window add


def test_a_ruling_that_disagrees_with_a_ledger_claim_raises(tmp_path):
    cw = {"kind": "claim_week", "manager": "Nick", "player": "Desmond Bane", "type": "add",
          "transaction_date": "2026-11-09", "claim_week": 2, "by": "Nick", "on": "2026-11-09", "reason": "r"}
    rulings = tr.load_all(_tr_world(tmp_path, [cw]), SCHED)
    with pytest.raises(tr.RulingError, match="disagree"):
        tr.add_budget_week(ADD, rulings, SCHED, CLAIM)
    agree = dict(cw, claim_week=3)
    rulings = tr.load_all(_tr_world(tmp_path, [agree]), SCHED)
    assert tr.add_budget_week(ADD, rulings, SCHED, CLAIM) == 3              # shadow mode writes both
    with pytest.raises(tr.RulingError, match="one add has one week"):
        tr.add_budget_week(ADD, rulings, SCHED, CLAIM + [dict(CLAIM[0], entry=2)])


def test_shadow_mode_counts_ignore_the_ledger_and_the_comparison_reports_it(tmp_path, monkeypatch):
    base = _tr_world(tmp_path, files={4: ["- [2026-11-09] Nick: Desmond Bane"]})
    monkeypatch.setattr(ml, "mode", lambda cfg=None: "shadow")
    rows = []
    rows.append({"row": "entry", "id": 1, "text": "Nick move: +Bane IL+Edwards", "kind": "move",
                 "parsed": {"manager": "Nick", "add": ["Desmond Bane"], "drop": [], "il_place": ["Anthony Edwards"],
                            "il_activate": []}, "claimed_at": "2026-11-05T12:00:00-08:00", "claim_week": 3,
                 "window_week": 4, "window": "2026-11-09", "entered_at": "x", "entered_by": "t", "checks": []})
    ml.write_entries(base, [], rows)
    assert tr.adds_by_budget_week(base, SCHED) == {4: {"Nick": ["Desmond Bane"]}}      # the rulings
    monkeypatch.setattr(ml, "mode", lambda cfg=None: "on")
    assert tr.adds_by_budget_week(base, SCHED) == {3: {"Nick": ["Desmond Bane"]}}      # the ledger
    cmp_ = ml.shadow_compare(base, SCHED, ml.entries(ml.read_rows(base)))
    assert [d["text"] for d in cmp_["differences"]] == [
        "week 3 Nick: rulings count 0 (-), the ledger 1 (Desmond Bane)",
        "week 4 Nick: rulings count 1 (Desmond Bane), the ledger 0 (-)"]


# =============================================================================
# the mode, the files
# =============================================================================

def test_ledger_mode_is_required_and_ships_on():
    # Nick switched it on 2026-11-10, after the clean 11-09 window (shadow before).
    with pytest.raises(ml.LedgerError, match="ledger_mode is missing"):
        ml.mode({"roster_moves": {}})
    with pytest.raises(ml.LedgerError, match="must be"):
        ml.mode({"roster_moves": {"ledger_mode": "off"}})
    with pytest.raises(ml.LedgerError):
        ml.mode({})
    assert ml.mode() == "on"
    assert ml.mode({"roster_moves": {"ledger_mode": "on"}}) == "on"
    assert ml.verify_from() == date(2026, 11, 3)


def test_entries_are_append_only(tmp_path):
    (tmp_path / "config").mkdir()
    w = make_world()
    r1 = ml.add(tmp_path, "Nick move: +Bane IL+Edwards", world=w)
    raw = (tmp_path / ml.LEDGER_FILE).read_text()
    with pytest.raises(ml.LedgerError, match="changed since it was read"):
        ml.write_entries(tmp_path, [], [r1])
    with pytest.raises(ml.LedgerError, match="changed since it was read"):
        ml.write_entries(tmp_path, [dict(r1, text="edited")], [])
    assert (tmp_path / ml.LEDGER_FILE).read_text() == raw
    r2 = ml.add(tmp_path, "Benton move: -Alexander-Walker", world=w)
    rows = ml.read_rows(tmp_path)
    assert rows[0] == r1 and rows[1] == r2 and r2["id"] == 2
    blob = json.loads(raw)
    blob["rows"][0]["id"] = 5
    (tmp_path / ml.LEDGER_FILE).write_text(json.dumps(blob))
    with pytest.raises(ml.LedgerError, match="expected 1"):
        ml.read_rows(tmp_path)


def test_a_malformed_states_file_raises(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / ml.STATES_FILE).write_text('{"row": "state", "entry": 1, "state": "maybe"}\n')
    with pytest.raises(ml.LedgerError):
        ml.read_states(tmp_path)


def _calls(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    f = n.func
                    nm = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    if nm == name:
                        out.append(f"{path.name}:{fn.name}")
    return out


def test_only_ledger_py_writes_the_ledger_and_only_the_nightly_writes_its_states():
    files = sorted((ROOT / "modules").glob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
    writers = sorted({c for p in files for c in _calls(p, "write_entries")})
    assert writers == ["ledger.py:cmd_add", "move_ledger.py:add", "move_ledger.py:void"]
    adders = sorted({c for p in files for c in _calls(p, "add") if p.name == "ledger.py"})
    voiders = sorted({c for p in files for c in _calls(p, "void")})
    assert voiders == ["ledger.py:cmd_void"]
    # move_ledger.add / void are called by nothing else in the engine
    assert sorted({c for p in files if p.name != "ledger.py" for c in _calls(p, "void")}) == []
    states = sorted({c for p in files for c in _calls(p, "append_states")})
    assert states == ["nightly.py:step_ledger"]
    # nothing but move_ledger.py names the ledger's files for writing
    for p in files:
        if p.name in ("move_ledger.py",):
            continue
        src = p.read_text(encoding="utf-8")
        assert "LEDGER_FILE" not in src.replace("ml.LEDGER_FILE.as_posix()", ""), p.name
        assert "STATES_FILE" not in src, p.name


def test_the_ledger_files_are_league_state_and_ignored():
    import subprocess
    from modules import state_manifest
    man = state_manifest.load(ROOT)
    for rel in ("config/MOVE_LEDGER.json", "data/move_ledger_states.jsonl", "output/move_checklist_week4.json"):
        assert man.contains(rel), rel
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
        assert r.returncode == 0, f"{rel} is not ignored"


# =============================================================================
# the hub (design s.3, s.6.3)
# =============================================================================

def test_the_hub_view_reserves_frees_and_feeds(tmp_path):
    from modules import price_lock
    (tmp_path / "config").mkdir()
    w = make_world()
    ml.add(tmp_path, "Benton move: -Alexander-Walker", world=w)
    ml.add(tmp_path, "Nick move: +Bane IL+Edwards", world=w)
    sched = {"games": [{"date": "2026-11-09", "home": "A", "away": "B", "tip_utc": "2026-11-10T03:00:00Z"}]}
    v = ml.hub_view(tmp_path, at("2026-11-05", 13), sched)
    assert set(v["claimed"]) == {"Desmond Bane"} and set(v["dropped"]) == {"Nickeil Alexander-Walker"}
    assert v["joins"]["Nick"][0]["text"] == "+ Desmond Bane joins Mon 11-09 (claimed Thu 11-05)"
    assert v["chips"]["Benton"]["Nickeil Alexander-Walker"] == [{"text": "leaves Mon 11-09", "kind": "out"}]
    assert v["chips"]["Nick"]["Anthony Edwards"] == [{"text": "IL from Mon 11-09", "kind": "il"}]
    assert v["pending_adds"] == {3: {"Nick": ["Desmond Bane"]}}
    assert [(x["who"], x["state"], x["what"]) for x in v["feed"]] == [
        ("Benton", "Pending", "dropped Nickeil Alexander-Walker"),
        ("Nick", "Pending", "claimed Desmond Bane, Anthony Edwards to IL")]
    # after the window closes nothing is live; the feed keeps the recent ones
    v = ml.hub_view(tmp_path, at("2026-11-10", 0, 5), sched)
    assert v["claimed"] == {} and v["joins"] == {} and len(v["feed"]) == 2


def test_the_hub_page_shows_pending_joins_and_no_checklist():
    """F6 (11-09): the Monday checklist is Nick's alone (ledger.py checklist),
    never on the hub; a payload carrying one still renders none of it."""
    import test_hub as th
    from modules import hub_page
    text = th.visible_text(hub_page.render(th.sample_payload(), now=th.GEN))
    assert "+ Joe Claimed joins Mon 11-09 (claimed Thu 11-05)" in text
    cl = {"week": "4", "title": "Monday window \u00b7 week 4", "closes": "Closes 6:55 PM Pacific",
          "lines": [{"n": "1", "text": "Nick: move Anthony Edwards into an IL slot", "state": "Pending"}],
          "stopped": [], "empty": "none", "note": "IL placements first."}
    page = hub_page.render(th.sample_payload(checklist=cl), now=th.GEN)
    assert "Monday window" not in th.visible_text(page) and "move Anthony Edwards" not in page


def test_the_ledger_issue_is_built_from_the_run_records_flags(tmp_path):
    import ledger_issue as li
    runs = tmp_path / "runs.jsonl"
    rows = [{"run_id": "a", "mode": "nightly", "steps": []},
            {"run_id": "b", "mode": "nightly", "ledger": {"mode": "shadow", "pending": [],
             "flags": ["MISSING entry 1 (Nick move: +Bane): the 11-09 window closed", "SHADOW week 3 ..."]}}]
    runs.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rs = li.flagged_rows(str(runs), 1)
    assert li.title(rs) == "Move ledger: 2 flag(s) (missing, shadow)"
    assert "MISSING entry 1" in li.body(rs, "http://run") and "Run: http://run" in li.body(rs, "http://run")
    assert li.flagged_rows(str(runs), 2) == []


def test_the_workflow_opens_the_ledger_issue_without_failing_the_run():
    wf = (ROOT / "deploy" / "state-repo" / ".github" / "workflows" / "run.yml").read_text(encoding="utf-8")
    i = wf.index("name: Open or comment on the ledger issue")
    block = wf[i:wf.index("- name:", i + 10)]
    assert "if: always() && steps.run.outputs.ledger_flags == 'true'" in block
    assert "--label move-ledger" in block and "run-failed" not in block


# =============================================================================
# "on" mode: a pending move is a known pickup for the roster plan (s.6.3)
# =============================================================================

def test_on_mode_moves_the_next_weeks_roster_by_the_pickup_and_shadow_never_reads_the_ledger(monkeypatch):
    import test_roster_plan as trp
    from modules import roster_plan as rp
    players, rosters = trp._league()
    base = trp._build(players, rosters)
    known = {3: {"Nick": {"il_place": [], "drop": ["Nick_14"], "add": ["FA_0"], "il_activate": []}}}
    tags = {n: "HEALTHY" for n in players}
    with_ = rp.build(start_week=2, il_slots={}, rosters=rosters, windows=trp.WINDOWS,
                     players=trp.PlayerIndex(players), statuses=tags, rules=trp.RULES, standin_gp=trp.GP,
                     order=list(trp.MANAGERS), known=known)
    assert "FA_0" in with_[3]["Nick"]["active"] and "Nick_14" not in with_[3]["Nick"]["active"]
    assert with_[3]["Nick"]["known"] == ["-Nick_14", "+FA_0"]
    assert with_[2] == base[2]                                           # this week untouched
    proj = lambda plan, w: sum(players[n].projected_fppg for n in plan[w]["Nick"]["active"])
    assert proj(with_, 3) - proj(base, 3) == pytest.approx(30.0 - 26.0)  # the pickup, every week after
    assert proj(with_, 5) - proj(base, 5) == pytest.approx(4.0)
    for m in rosters:
        if m != "Nick":
            assert with_[3][m] == base[3][m]
    # rule 12 in the plan: joins and leaves in one window
    k12 = {3: {"Nick": {"il_place": [], "drop": ["FA_0"], "add": ["FA_0"], "il_activate": []}}}
    p12 = rp.build(start_week=2, il_slots={}, rosters=rosters, windows=trp.WINDOWS,
                   players=trp.PlayerIndex(players), statuses=tags, rules=trp.RULES, standin_gp=trp.GP,
                   order=list(trp.MANAGERS), known=k12)
    assert "FA_0" not in p12[3]["Nick"]["active"]
    # for_run: shadow never reads the ledger; on reads it (and the plan's cache key carries it)
    from types import SimpleNamespace

    class Stop(Exception):
        pass

    def stop(*a, **k):
        raise Stop()
    monkeypatch.setattr(rp, "load_il_slots", stop)
    calls = []
    monkeypatch.setattr(ml, "known_moves", lambda *a, **k: calls.append(1) or {})
    for mode_, want in (("shadow", []), ("on", [1])):
        calls.clear()
        monkeypatch.setattr(ml, "mode", lambda cfg=None, m=mode_: m)
        with pytest.raises(Stop):
            rp.for_run(SimpleNamespace(il_slots=None, base_path="."), {}, None)
        assert calls == want, mode_
