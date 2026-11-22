"""
tests/test_h56_trade_picks.py -- H56 Part 2, the pull (s.4.1): Yahoo's trade
transactions parsed with their draft picks, matched to all_trades.json, the
players unchanged; the 2023-24 screenshot check; which draft a pick belongs
to; keeper-round picks. No network: the fixtures below are built in the
shape Yahoo documents for a league's transactions collection (a transaction
is [meta, {"players": ...}], picks in the meta's "picks"). The fetch saves
Yahoo's raw JSON; the parse step prints the shape Yahoo really used, and these
fixtures are replaced by recorded ones once Nick has run it.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import trade_picks as TP                       # noqa: E402

L = "428.l.83508"
MG = {f"{L}.t.1": "Nick", f"{L}.t.2": "Garrett", f"{L}.t.3": "Hayden", f"{L}.t.4": "Benton"}


def _player(name, key, src, dst):
    return {"player": [[{"player_key": key}, {"player_id": key.split(".")[-1]}, {"name": {"full": name}}],
                       {"transaction_data": [{"type": "trade", "source_type": "team", "source_team_key": src,
                                              "destination_type": "team", "destination_team_key": dst}]}]}


def _pick(rnd, src, dst, orig=None):
    p = {"source_team_key": src, "source_team_name": "x", "destination_team_key": dst,
         "destination_team_name": "y", "round": str(rnd)}
    if orig:
        p["original_team_key"] = orig
    return {"pick": p}


def _trade(tid, ts, trader, tradee, players, picks=None):
    meta = {"transaction_key": f"{L}.tr.{tid}", "transaction_id": str(tid), "type": "trade", "status": "successful",
            "timestamp": str(ts), "trader_team_key": trader, "trader_team_name": "a",
            "tradee_team_key": tradee, "tradee_team_name": "b"}
    if picks is not None:
        meta["picks"] = picks
    parts = [meta]
    if players:
        parts.append({"players": {**{str(i): p for i, p in enumerate(players)}, "count": len(players)}})
    return {"transaction": parts}


N, B = f"{L}.t.1", f"{L}.t.4"
G = f"{L}.t.2"
JAN15 = 1705334400 + 3600 * 20        # 2024-01-15 20:00 UTC = noon Pacific
RAW = {"fantasy_content": {"league": [{"league_key": L}, {"transactions": {
    "0": _trade(30, JAN15, N, B, [_player("Stephen Curry", "428.p.4612", N, B),
                                  _player("CJ McCollum", "428.p.4720", B, N),
                                  _player("Kawhi Leonard", "428.p.4896", B, N)],
                [_pick(1, N, B, N), _pick(3, B, N, B)]),
    "1": _trade(12, 1700000000, N, G, [_player("A Guy", "428.p.1", N, G), _player("B Guy", "428.p.2", G, N)]),
    "2": {"transaction": [{"transaction_key": f"{L}.tr.5", "type": "add", "status": "successful",
                           "timestamp": "1699000000"}]},
    "count": 3}}]}}

ROWS = [{"season": "2023-24", "timestamp": str(JAN15), "date": "2024-01-15", "trader_team": "a", "tradee_team": "b",
         "trader_manager": "Nick", "tradee_manager": "Benton",
         "players": [{"player_name": "Stephen Curry", "from_team": "a", "to_team": "b", "from_manager": "Nick",
                      "to_manager": "Benton"},
                     {"player_name": "CJ McCollum", "from_team": "b", "to_team": "a", "from_manager": "Benton",
                      "to_manager": "Nick"},
                     {"player_name": "Kawhi Leonard", "from_team": "b", "to_team": "a", "from_manager": "Benton",
                      "to_manager": "Nick"}]},
        {"season": "2023-24", "timestamp": None, "date": "2023-11-14", "trader_team": "a", "tradee_team": "c",
         "trader_manager": "Nick", "tradee_manager": "Garrett",
         "players": [{"player_name": "A Guy", "from_team": "a", "to_team": "c", "from_manager": "Nick",
                      "to_manager": "Garrett"},
                     {"player_name": "B Guy", "from_team": "c", "to_team": "a", "from_manager": "Garrett",
                      "to_manager": "Nick"}]},
        {"season": "2017-18", "timestamp": "1", "date": "2018-01-01", "players": []}]


def test_the_parser_reads_players_and_picks_and_skips_other_transactions():
    ts = TP.parse(RAW)
    assert [t["transaction_key"] for t in ts] == [f"{L}.tr.12", f"{L}.tr.30"]      # oldest first, trades only
    jan = ts[1]
    assert [p["name"] for p in jan["players"]] == ["Stephen Curry", "CJ McCollum", "Kawhi Leonard"]
    assert [(p["round"], p["source_team_key"], p["destination_team_key"], p["original_team_key"]) for p in jan["picks"]] \
        == [(1, N, B, N), (3, B, N, B)]
    assert ts[0]["picks"] == []
    assert "picks" in jan["parts"][0]


def test_a_pick_without_a_round_or_teams_raises_never_guessed():
    bad = copy.deepcopy(RAW)
    del bad["fantasy_content"]["league"][1]["transactions"]["0"]["transaction"][0]["picks"][0]["pick"]["round"]
    with pytest.raises(TP.TradeShapeError):
        TP.parse(bad)


def test_rows_match_by_timestamp_or_by_players_and_only_the_new_field_is_added():
    before = copy.deepcopy(ROWS)
    got, rep = TP.match(ROWS, {"2023-24": TP.parse(RAW)}, {"2023-24": MG})
    assert sorted(got) == [0, 1] and rep["unmatched_rows"] == [] and rep["yahoo_only"] == []
    after = TP.add_picks(ROWS, got, {"2023-24": MG}, {"2023-24": "2023-10-24"})
    assert ROWS == before and TP.players_unchanged(ROWS, after)
    assert after[1]["draft_picks"] == [] and "draft_picks" not in after[2]
    assert [(p["round"], p["draft"], p["original_manager"], p["from_manager"], p["to_manager"])
            for p in after[0]["draft_picks"]] == [(1, "2024-25", "Nick", "Nick", "Benton"),
                                                  (3, "2024-25", "Benton", "Benton", "Nick")]
    broken = copy.deepcopy(after)
    broken[0]["players"][0]["player_name"] = "Steph Curry"
    assert not TP.players_unchanged(ROWS, broken)


def test_a_yahoo_trade_missing_from_the_file_is_reported():
    got, rep = TP.match(ROWS[:1], {"2023-24": TP.parse(RAW)}, {"2023-24": MG})
    assert rep["yahoo_only"] == [("2023-24", f"{L}.tr.12", 2, 0)]


def test_the_screenshot_check():
    got, _ = TP.match(ROWS, {"2023-24": TP.parse(RAW)}, {"2023-24": MG})
    after = TP.add_picks(ROWS, got, {"2023-24": MG}, {"2023-24": "2023-10-24"})
    assert TP.screenshot_check(after)["jan15"] is True
    wrong = copy.deepcopy(after)
    wrong[0]["draft_picks"][1]["round"] = 4
    assert TP.screenshot_check(wrong)["jan15"] is False


def test_which_draft_a_pick_belongs_to():
    p = {"round": 1}
    assert TP.draft_of(p, "2023-24", "2024-01-15", "2023-10-24")[0] == "2024-25"
    assert TP.draft_of(p, "2023-24", "2023-09-30", "2023-10-24")[0] == "2023-24"
    assert TP.draft_of({"round": 2, "draft_field": ("season", "2027")}, "2025-26", "2026-01-27", "2025-10-21") \
        == ("2027-28", "yahoo season")
    with pytest.raises(TP.TradeShapeError):
        TP.draft_of(p, "2023-24", "2024-01-15", None)


def test_listed_valued_and_keeper_round_picks_follow_the_draft_eras():
    from modules import draft_history as DH
    assert not DH.keeper_era("2020-21")                      # a snake-draft pick: listed, never valued
    assert DH.keeper_era("2021-22") and DH.live_rounds("2021-22") == 7
    assert 8 > DH.live_rounds("2024-25")                     # round 8 of 2024-25 is a keeper slot
    assert DH.live_rounds("2026-27") == 9 and DH.live_rounds("2027-28") == 10


def test_the_25_26_labels_parse():
    sys.path.insert(0, str(ROOT / "scripts"))
    import pull_trade_picks as P
    assert P._label("2026 2nd (Nick)") == ("2026-27", 2, "Nick")
    assert P._label("2027 8th (Garrett)") == ("2027-28", 8, "Garrett")
    with pytest.raises(ValueError):
        P._label("Round 2")


def test_the_pull_writes_only_all_trades_and_never_state():
    src = (ROOT / "scripts" / "pull_trade_picks.py").read_text(encoding="utf-8")
    assert src.count(".write_text(") == 2                        # the raw files, and all_trades.json
    assert "TRADES.json\").write" not in src and "STATE" not in src.replace("STATE_MANIFEST", "")
    assert "data/historical/all_trades.json" not in json.dumps(
        json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8")))


# =============================================================================
# Nick's rulings, 11-21 (LEAGUE_RULES "Traded draft picks")
# =============================================================================

def test_only_completed_trades_count_and_a_vetoed_one_is_named_for_removal():
    raw = copy.deepcopy(RAW)
    t = raw["fantasy_content"]["league"][1]["transactions"]
    t["3"] = _trade(31, JAN15 - 1500, N, f"{L}.t.3", [_player("Andre Drummond", "428.p.9", N, f"{L}.t.3")],
                    [_pick(2, N, f"{L}.t.3", N)])
    t["3"]["transaction"][0]["status"] = "vetoed"
    assert f"{L}.tr.31" not in [x["transaction_key"] for x in TP.parse(raw)]
    assert TP.not_completed(raw) == [(f"{L}.tr.31", str(JAN15 - 1500), "vetoed")]
    src = (ROOT / "scripts" / "pull_trade_picks.py").read_text(encoding="utf-8")
    assert "TP.not_completed(raw)" in src and "removed" in src


def test_a_keeper_round_pick_raises_unless_ruled_and_is_never_a_category():
    tr = {"transaction_key": "x.tr.1", "timestamp": str(1769500000), "picks": [
        {"round": 15, "source_team_key": "k3", "destination_team_key": "k4", "original_team_key": "k3"}]}
    mg = {"k3": "Hayden", "k4": "Benton"}
    with pytest.raises(TP.KeeperRoundPick):
        TP.picks_for_file(tr, "2025-26", mg, "2025-10-21")
    tr2 = dict(tr, transaction_key="466.l.42309.tr.203",
               picks=[dict(tr["picks"][0], original_team_key="466.l.42309.t.3", source_team_key="466.l.42309.t.3",
                           destination_team_key="466.l.42309.t.4")])
    out = TP.picks_for_file(tr2, "2025-26", {"466.l.42309.t.3": "Hayden", "466.l.42309.t.4": "Benton"}, "2025-10-21")
    assert out[0]["round"] == 9 and "Hayden's 9th" in out[0]["corrected"]
    for f in ("modules/trade_picks.py", "scripts/pull_trade_picks.py"):
        assert "KEEPER-ROUND pick" not in (ROOT / f).read_text(encoding="utf-8")


def test_picks_beyond_the_next_draft_come_from_the_chat_labels():
    row = {"date": "2026-01-27", "trader_manager": "Hayden", "tradee_manager": "Benton",
           "picks": {"Hayden": ["2026 9th (Hayden)", "2027 2nd (Hayden)"], "Benton": ["2026 5th (Benton)", "2027 5th (Benton)"]}}
    got = TP.chat_picks(row, "2025-26")
    assert sorted((p["draft"], p["round"], p["from_manager"], p["to_manager"], p["source"]) for p in got) == \
        [("2027-28", 2, "Hayden", "Benton", "chat"), ("2027-28", 5, "Benton", "Hayden", "chat")]


def test_the_written_file_has_no_vetoed_trade_and_matches_the_25_26_labels():
    rows = json.loads((ROOT / "data" / "historical" / "all_trades.json").read_text(encoding="utf-8"))
    assert not any(r.get("timestamp") == "1547595949" for r in rows)              # Drummond for Kawhi, vetoed
    assert all("draft_picks" in r for r in rows)
    sys.path.insert(0, str(ROOT / "scripts"))
    import pull_trade_picks as P
    assert P._labels_agree(rows) == [True] * 5
    from modules import draft_history as DH
    for r in rows:
        for p in r["draft_picks"]:
            if DH.keeper_era(p["draft"]):
                assert p["round"] <= DH.live_rounds(p["draft"]), (r["date"], p)
    # 62 in Yahoo + 4 in the chat = 66; the Feb 26, 2024 swap (2 picks) was reversed outside Yahoo (Nick, 11-21)
    assert sum(len(r["draft_picks"]) for r in rows) == 64
    assert sum(len(r.get("draft_picks_reversed", [])) for r in rows) == 2
    sc = TP.screenshot_check(rows)
    assert sc["jan15"] and sc["later_have_picks"] == {"2024-02-26": True, "2024-03-07": True}


def _feb26():
    return {"transaction_key": f"{L}.tr.220", "timestamp": "1708967779", "picks": [
        {"round": 4, "source_team_key": B, "destination_team_key": N, "original_team_key": B},
        {"round": 3, "source_team_key": N, "destination_team_key": B, "original_team_key": N}]}


def test_the_feb26_2024_swap_is_reversed_by_a_ruling_tied_to_its_transaction():
    """5d1 (Nick, 11-21; H56 Part 2 decision 2): both picks leave the trade, with the reason."""
    out = TP.picks_for_file(_feb26(), "2023-24", MG, "2023-10-24")
    stand, gone = TP.split_reversed(out)
    assert stand == [] and len(gone) == 2
    assert {(p["original_manager"], p["draft"], p["round"]) for p in gone} == {("Benton", "2024-25", 4), ("Nick", "2024-25", 3)}
    assert all("outside Yahoo (Nick, 11-21)" in p["reversed"] and "2024-25 draft" in p["reversed"] for p in gone)
    # the same picks in another transaction are untouched: the ruling is tied to tr.220
    other = dict(_feb26(), transaction_key=f"{L}.tr.221")
    assert all("reversed" not in p for p in TP.picks_for_file(other, "2023-24", MG, "2023-10-24"))


def test_add_picks_moves_reversed_picks_out_and_a_stale_ruling_raises():
    row = {"season": "2023-24", "date": "2024-02-26", "players": []}
    out = TP.add_picks([row], {0: _feb26()}, {"2023-24": MG}, {"2023-24": "2023-10-24"})
    assert out[0]["draft_picks"] == [] and len(out[0]["draft_picks_reversed"]) == 2
    assert TP.players_unchanged([row], out)
    no_picks = dict(_feb26(), picks=[])                        # the ruled picks are gone from Yahoo's record
    with pytest.raises(TP.StaleRuling):
        TP.add_picks([row], {0: no_picks}, {"2023-24": MG}, {"2023-24": "2023-10-24"})


def test_the_written_file_and_the_awards_drop_the_reversed_picks():
    rows = json.loads((ROOT / "data" / "historical" / "all_trades.json").read_text(encoding="utf-8"))
    f = [r for r in rows if r["date"] == "2024-02-26"]
    assert len(f) == 1 and f[0]["draft_picks"] == [] and len(f[0]["draft_picks_reversed"]) == 2
    assert not any(p.get("reversed") for r in rows for p in r["draft_picks"])
    past = json.loads((ROOT / "data" / "historical" / "AWARDS_PAST.json").read_text(encoding="utf-8"))
    t = past["seasons"]["2023-24"]["awards"]["trade"]
    assert t["winner"]["date"] == "2024-01-15" and t["winner"]["m"] == "Benton"      # the winner doesn't change
    feb = [x for x in t["top"] if x["date"] == "2024-02-26"][0]
    assert all(sd["picks"] == [] and sd["picks_est"] == 0 for sd in feb["sides"].values())


# =============================================================================
# s.4.2 showing picks, s.4.4 valuing them
# =============================================================================

def _p(orig, draft, rnd, frm, to):
    return {"original_manager": orig, "draft": draft, "round": rnd, "from_manager": frm, "to_manager": to}


def test_a_picks_label_says_whose_which_draft_which_round():
    assert TP.pick_label(_p("Benton", "2024-25", 3, "Benton", "Nick")) == "Benton's 2024 3rd"
    assert [TP.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st"]


def _draft(season, order, rounds=2):
    rows, n = [], 0
    for rd in range(1, rounds + 1):
        for m in order:
            n += 1
            rows.append({"season": season, "pick_number": n, "round": rd, "manager": m,
                         "player_name": f"{m} R{rd}", "is_keeper": False})
    return rows


def test_what_a_pick_became_shows_only_from_trusted_drafts_and_only_when_it_adds_up():
    d24 = _draft("2024-25", ["Benton", "Garrett", "Hayden", "Nick"])
    d24[5]["manager"] = "Nick"                                            # Garrett's 2nd made by Nick
    B = TP.Became({"2024-25": d24, "2023-24": _draft("2023-24", ["Nick", "Benton", "Garrett", "Hayden"])})
    assert TP.show(_p("Garrett", "2024-25", 2, "Garrett", "Nick"), B) == "Garrett's 2024 2nd → Garrett R2, 2.02"
    assert TP.show(_p("Garrett", "2024-25", 1, "Garrett", "Hayden"), B) == "Garrett's 2024 1st"   # Hayden didn't make it
    assert TP.show(_p("Nick", "2023-24", 1, "Nick", "Benton"), B) == "Nick's 2023 1st"            # punted order
    assert TP.show(_p("Nick", "2027-28", 1, "Nick", "Benton"), B) == "Nick's 2027 1st"            # not drafted yet


def test_trade_of_the_year_counts_picks_at_their_rounds_value_and_says_so():
    from modules import awards as A
    assert "A draft pick counts as the average value of players taken in that round" in A.INFO["trade"]
    import inspect
    src = inspect.getsource(A._trades)
    assert 'DV.value(table, "par"' in src and "(not valued)" in src and "DH.keeper_era" in src
    past = json.loads((ROOT / "data" / "historical" / "AWARDS_PAST.json").read_text(encoding="utf-8"))
    w = past["seasons"]["2023-24"]["awards"]["trade"]["winner"]
    assert w["sides"]["Benton"]["picks"] == ["Nick's 2024 1st (est. 650.6)"]
    assert w["sides"]["Benton"]["par"] == pytest.approx(w["sides"]["Benton"]["players_par"] + w["sides"]["Benton"]["picks_est"], abs=0.02)
    s18 = past["seasons"]["2018-19"]["awards"]["trade"]["winner"]
    assert all(x.endswith("(not valued)") for sd in s18["sides"].values() for x in sd["picks"])   # snake-era picks
    assert "not valued" in past["notes"]["trades"] and "est." in past["notes"]["trades"]
