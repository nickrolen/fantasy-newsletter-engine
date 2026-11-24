"""5f item 2: a drop can be voided (Nick, 11-23: "yes drops should be able to be
voided, duh. I want the moves ledger to make sense").

A void ruling may carry "type": "drop". It is never listed where moves are
shown (Market > Moves, the cards that read it, the awards' add pairing), it
never changes rosters or logs (they follow Yahoo), and one that matches no drop
raises. Two drops of one player by one manager on one day (Nick's Daniels,
11-23, 1:19 and 1:43 AM) are told apart by "time" (HH:MM, league clock) or
"transaction_key"; without one, the ruling raises as ambiguous. The
round-trip rule (ad0df64) stays: computed on Yahoo's log as before. Synthetic
throughout: no rulings for 11-23 are written (they are state).
"""
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import hub_moves, transaction_rulings as tr  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
D = "2026-11-23"
SCHEDULE = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))


def _ts(hh, mm):
    return int(datetime(2026, 11, 23, hh, mm, tzinfo=LA).timestamp())


def tx(key, hh, mm, *parts):
    """A transaction_log row (the shape tlog.transactions returns)."""
    ps = []
    for act, mgr, name in parts:
        side = {"type": "team", "manager": mgr, "team_key": mgr, "team": mgr}
        fa = {"type": "freeagents", "manager": None, "team_key": None, "team": None}
        ps.append({"action": act, "name": name, "player_key": f"p.{abs(hash(name)) % 9999}",
                   "to": side if act == "add" else fa, "from": side if act == "drop" else fa})
    t = "add/drop" if len(parts) > 1 else parts[0][0]
    at = datetime(2026, 11, 23, hh, mm, tzinfo=LA)
    return {"row": "transaction", "key": key, "id": hh * 60 + mm, "type": t, "status": "successful",
            "timestamp": int(at.timestamp()), "time": at.isoformat(timespec="seconds"),
            "league_day": D, "fantasy_week": 6, "players": ps, "rulings": []}


def void_add(p):
    return tr.Ruling(D, "Nick", "add", p, "void", "Nick", D, "test add")


def void_drop(p, time="", key=""):
    return tr.Ruling(D, "Nick", "drop", p, "void", "Nick", D, "test drop", time, key)


# Nick's 11-23 test moves (week 6), as in test_hub_polish3: every test add
# voided; the 1:43 AM Durant-for-Daniels add/drop real.
TXS = [tx("g1", 1, 18, ("drop", "Nick", "Darius Garland")),
       tx("q1", 1, 19, ("add", "Nick", "Immanuel Quickley"), ("drop", "Nick", "Dyson Daniels")),
       tx("q2", 1, 29, ("drop", "Nick", "Immanuel Quickley")),
       tx("d1", 1, 33, ("add", "Nick", "Dyson Daniels")),
       tx("kd", 1, 43, ("add", "Nick", "Kevin Durant"), ("drop", "Nick", "Dyson Daniels"))]
ADD_VOIDS = [void_add(p) for p in ("Immanuel Quickley", "Dyson Daniels")]


# --- the ruling's shape ---------------------------------------------------------

def _load(tmp_path, *rulings):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "TRANSACTION_RULINGS.json").write_text(
        json.dumps({"rulings": list(rulings)}), encoding="utf-8")
    return tr.load_all(tmp_path, SCHEDULE)


def _rj(**over):
    r = {"date": D, "manager": "Nick", "type": "drop", "player": "Dyson Daniels",
         "ruling": "void", "by": "Nick", "on": "2026-11-24", "reason": "a test move"}
    r.update(over)
    return r


def test_a_drop_void_loads_with_its_time_or_key_and_labels_them(tmp_path):
    rs = _load(tmp_path, _rj(time="01:19"), _rj(player="Darius Garland"),
               _rj(time="01:43", transaction_key="478.l.16778.tr.99"))
    assert [r.type for r in rs] == ["drop"] * 3
    assert rs[0].label() == "void 2026-11-23 Nick drop Dyson Daniels at 01:19 (Nick, 2026-11-24)"
    assert "[478.l.16778.tr.99]" in rs[2].label()


@pytest.mark.parametrize("bad, msg", [
    (_rj(type="add", time="01:19"), "defined on a voided drop only"),
    (_rj(time="1:19 AM"), "is not HH:MM"),
    (_rj(time="25:00"), "is not HH:MM"),
    (_rj(type="trade"), "an 'add' or a 'drop'"),
    (_rj(transaction_key=" "), "is empty"),
    (_rj(minute="01:19"), "unknown field"),
])
def test_a_malformed_drop_ruling_raises(tmp_path, bad, msg):
    with pytest.raises(tr.RulingError, match=msg):
        _load(tmp_path, bad)


def test_two_rulings_on_the_same_drop_raise_but_two_named_drops_do_not(tmp_path):
    with pytest.raises(tr.RulingError, match="two rulings on one"):
        _load(tmp_path, _rj(time="01:19"), _rj(time="01:19"))
    with pytest.raises(tr.RulingError, match="two rulings on one"):
        _load(tmp_path / "b", _rj(), _rj())
    assert len(_load(tmp_path / "c", _rj(time="01:19"), _rj(time="01:43"))) == 2
    # a voided add and a voided drop of the same player that day are two moves
    assert len(_load(tmp_path / "d", _rj(time="01:19"), _rj(type="add"))) == 2


# --- matching ---------------------------------------------------------------------

def test_the_voided_drop_is_found_by_its_time_and_the_real_one_stays():
    assert tr.voided_drops(TXS, [void_drop("Dyson Daniels", time="01:19")]) == {"q1": ["Dyson Daniels"]}
    assert tr.voided_drops(TXS, [void_drop("Dyson Daniels", key="kd")]) == {"kd": ["Dyson Daniels"]}
    left = tr.without_voided_drops(TXS, [void_drop("Dyson Daniels", time="01:19"),
                                         void_drop("Darius Garland")])
    by = {t["key"]: t for t in left}
    assert "g1" not in by                                         # nothing else in that move: gone
    assert [p["action"] for p in by["q1"]["players"]] == ["add"]   # the add stays
    assert [p["name"] for p in by["kd"]["players"]] == ["Kevin Durant", "Dyson Daniels"]  # the real drop
    assert len(TXS[1]["players"]) == 2                            # the log itself is untouched


def test_an_ambiguous_drop_ruling_raises():
    with pytest.raises(tr.RulingError, match=r"ambiguous: 2 drops .* \"time\" .* \"transaction_key\""):
        tr.voided_drops(TXS, [void_drop("Dyson Daniels")])


def test_a_drop_ruling_matching_nothing_raises():
    for r in (void_drop("Dyson Daniels", time="02:00"), void_drop("Kevin Durant"),
              void_drop("Dyson Daniels", key="nope"),
              tr.Ruling("2026-11-22", "Nick", "drop", "Dyson Daniels", "void", "Nick", D, "x", "01:19")):
        with pytest.raises(tr.RulingError, match="matches no drop"):
            tr.voided_drops(TXS, [r])


# --- Market > Moves -----------------------------------------------------------

def _feed(rulings):
    return hub_moves.by_week(TXS, rulings, SCHEDULE, None, {6: {"Nick": ["Kevin Durant"]}}, week=6,
                             managers=["Nick", "Hayden", "Garrett", "Benton"], budget=3, mode="shadow")


def _whats(feed):
    tab = next(t for t in feed["weeks"] if t["key"] == "6")
    return sorted(x["what"] for x in tab["items"])


def test_a_voided_drop_disappears_from_moves_and_the_real_drop_of_the_same_player_stays():
    before = _whats(_feed(ADD_VOIDS))
    assert "dropped Darius Garland" in before
    after = _whats(_feed(ADD_VOIDS + [void_drop("Darius Garland")]))
    assert "dropped Darius Garland" not in after
    assert "added Kevin Durant, dropped Dyson Daniels" in after
    assert [u["text"] for u in next(t for t in _feed(ADD_VOIDS + [void_drop("Darius Garland")])["weeks"]
                                    if t["key"] == "6")["used"]][0] == "Nick 1 of 3"   # counts unchanged


def test_a_drop_hidden_by_a_round_trip_and_also_voided_is_fine_and_the_round_trip_is_unchanged():
    """The 1:19 Daniels drop is a round trip (the voided 1:33 re-add undid it).
    Voiding it as well hides it once; the voided re-add still does not reach
    the real 1:43 drop, which a removal BEFORE the round trip would have done."""
    plain = _whats(_feed(ADD_VOIDS))
    both = _whats(_feed(ADD_VOIDS + [void_drop("Dyson Daniels", time="01:19")]))
    assert plain == both
    assert "added Kevin Durant, dropped Dyson Daniels" in both
    assert hub_moves.round_trip_drops(TXS, ADD_VOIDS + [void_drop("Dyson Daniels", time="01:19")]) \
        == hub_moves.round_trip_drops(TXS, ADD_VOIDS)


def test_moves_raise_on_a_drop_ruling_that_matches_nothing():
    with pytest.raises(tr.RulingError, match="matches no drop"):
        _feed(ADD_VOIDS + [void_drop("Nobody")])


# --- the sync: rosters follow Yahoo; the waivers files list adds only --------------

def _sync_mod():
    spec = importlib.util.spec_from_file_location("sync_5f", ROOT / "scripts" / "sync_transactions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sync_txs():
    from datetime import date
    d = date(2026, 11, 23)

    def t(kind, name, hh, mm, key):
        return {"type": kind, "player_name": name, "manager": "Nick", "fantasy_team": "Nick's",
                "date": d, "timestamp": _ts(hh, mm), "transaction_key": key, "details": {}}
    return [t("drop", "Dyson Daniels", 1, 19, "k119"), t("add", "Dyson Daniels", 1, 33, "k133"),
            t("add", "Kevin Durant", 1, 43, "k143"), t("drop", "Dyson Daniels", 1, 43, "k143")]


def test_the_sync_takes_the_voided_drop_out_of_its_list_and_rosters_are_unchanged():
    from datetime import date
    sync = _sync_mod()
    txs = _sync_txs()
    counted, applied = tr.apply_to_transactions(
        txs, [void_drop("Dyson Daniels", time="01:19")], since=date(2026, 11, 23),
        until=date(2026, 11, 29), echo=lambda *_: None)
    assert [(t["type"], t["timestamp"]) for t in counted if t["type"] == "drop"] == [("drop", _ts(1, 43))]
    assert applied[0].type == "drop"
    # by key, too; and ambiguous / unmatched raise here as in the hub
    counted, _ = tr.apply_to_transactions(txs, [void_drop("Dyson Daniels", key="k143")],
                                          since=date(2026, 11, 23), until=None, echo=lambda *_: None)
    assert [t["timestamp"] for t in counted if t["type"] == "drop"] == [_ts(1, 19)]
    with pytest.raises(tr.RulingError, match="ambiguous"):
        tr.apply_to_transactions(txs, [void_drop("Dyson Daniels")], since=date(2026, 11, 23), until=None)
    with pytest.raises(tr.RulingError, match="matches no drop"):
        tr.apply_to_transactions(txs, [void_drop("Dyson Daniels", time="03:00")],
                                 since=date(2026, 11, 23), until=None)
    # rosters: the sync applies Yahoo's whole list, never the ruled one
    ros = {"rosters": {"Nick": ["Dyson Daniels", "Someone"]}}
    with_r, _ = sync.apply_transactions(json.loads(json.dumps(ros)), txs)
    assert sorted(with_r["rosters"]["Nick"]) == ["Kevin Durant", "Someone"]


def test_the_sync_dicts_carry_yahoos_transaction_key():
    src = (ROOT / "scripts" / "sync_transactions.py").read_text(encoding="utf-8")
    assert src.count('"transaction_key": txn.get("transaction_key"),') == 4


def test_a_waivers_file_is_read_as_before_with_a_drop_void_on_file(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "TRANSACTION_RULINGS.json").write_text(
        json.dumps({"rulings": [_rj(time="01:19")]}), encoding="utf-8")
    f = tmp_path / "waivers_week6.txt"
    f.write_text("# Waiver Adds for Week 6\n\n- [2026-11-23] Nick: Kevin Durant\n", encoding="utf-8")
    lines, applied = tr.waiver_lines(f, tmp_path, 6, SCHEDULE)
    assert "- [2026-11-23] Nick: Kevin Durant" in lines and applied == []
    assert tr.add_budget_week({"date": D, "manager": "Nick", "player": "Kevin Durant"},
                              tr.load_all(tmp_path, SCHEDULE), SCHEDULE) == 6
