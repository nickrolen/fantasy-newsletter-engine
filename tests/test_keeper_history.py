"""Keepability v3, step A: the keeper-decision dataset and its backtest rules.

HANDOFF_KEEPABILITY_A_MEASURE_2026-10-29, section 5.
"""
import json
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import keeper_history as kh                      # noqa: E402
from scripts import keeper_backtest as kb                      # noqa: E402

SEASON, DECISION = "2024-25", "2025-26"     # a real season: regular_through 21 -> mid = week 11
START = date(2024, 10, 21)
DAYS = [START + timedelta(days=i) for i in range(12 * 7)]       # weeks 1..12


def _row(player, manager, i, fp, had_game=True, injured=False, team="AAA", pid=None, started=True):
    d = DAYS[i]
    return {"season_key": SEASON, "week": i // 7 + 1, "date": d.isoformat(), "manager": manager,
            "player_name": player, "player_id": pid, "nba_team": team, "nba_opponent": "BBB" if had_game else "",
            "had_game": had_game, "is_injured": injured, "fantasy_points": fp if had_game and not injured else 0.0,
            "started": started, "slot": "UTIL" if started else "BN"}


def _stint(player, manager, first, last, fp, every=2, pid=None):
    """Rostered days first..last; a game every `every` days at `fp`."""
    return [_row(player, manager, i, fp, had_game=(i % every == 0), pid=pid) for i in range(first, last + 1)]


def _world(extra=(), picks_now=None, picks_next=None, trades=()):
    end = len(DAYS) - 1
    rows = []
    for k in range(8):
        rows += _stint(f"Nick {k}", "Nick", 0, end, 20 + k)
        rows += _stint(f"Hay {k}", "Hayden", 0, end, 20 + k)
    rows += list(extra)
    log = {SEASON: sorted(rows, key=lambda r: (r["date"], r["manager"], r["player_name"]))}
    picks_now = picks_now if picks_now is not None else [
        {"season": SEASON, "manager": m, "player_name": f"{p} {k}", "round": k + 1,
         "pick_number": 2 * k + j + 1, "is_keeper": k >= 6}
        for j, (m, p) in enumerate((("Nick", "Nick"), ("Hayden", "Hay"))) for k in range(8)]
    picks_next = picks_next if picks_next is not None else [
        {"season": DECISION, "manager": m, "player_name": f"{p} {k}", "round": 10, "is_keeper": True}
        for m, p in (("Nick", "Nick"), ("Hayden", "Hay")) for k in range(2, 8)]
    return kh.Inputs(log=log, picks={SEASON: picks_now, DECISION: picks_next}, trades=list(trades))


# 1 -- every keeper on his manager's end-of-season roster; a mismatch raises
def test_all_144_keepers_are_on_their_managers_end_of_season_roster():
    inputs = kh.Inputs.load(ROOT)
    found = 0
    for d in kh.DECISIONS:
        season = kh.prev_season(d)
        rows = inputs.log[season]
        end = kh.roster_on(rows, kh.as_of_points(rows, season)["end"][1])
        keepers = kh.keepers_of(inputs, d)
        kh.check_keepers_on_rosters(keepers, end, d)            # raises on any miss
        assert all(len(v) == 6 for v in keepers.values()) and len(keepers) == 4
        found += sum(len(v) for v in keepers.values())
    assert found == 144


def test_a_keeper_resolves_by_id_or_by_accent_and_a_mismatch_raises():
    extra = _stint("Nikola Jokic", "Nick", 0, len(DAYS) - 1, 60, pid=3930)
    nxt = [{"season": DECISION, "manager": "Nick", "player_name": "Nikola Joki\u0107", "round": 10,
            "is_keeper": True},                                              # accent, no id
           {"season": DECISION, "manager": "Nick", "player_name": "N. Jokic-renamed", "round": 11,
            "player_key": "3930", "is_keeper": True}]                        # id wins over a respelling
    w = _world(extra, picks_next=nxt)
    assert kh.keepers_of(w, DECISION) == {"Nick": ["Nikola Jokic", "Nikola Jokic"]}
    bad = _world(extra, picks_next=[{"season": DECISION, "manager": "Nick", "player_name": "Nikolai Jokanovic",
                                     "round": 10, "is_keeper": True}])
    with pytest.raises(kh.KeeperNotOnRoster, match="Nikolai Jokanovic"):
        kh.snapshot(bad, DECISION, "end")


# 2 -- nothing after the as-of day enters a feature
def test_no_feature_reads_past_its_as_of_day():
    """Late (after week 2) the bench guy turns into a star, gets traded to
    Hayden, and a newcomer is picked up: none of it may move a week-2 feature."""
    end = len(DAYS) - 1
    late = (_stint("Late Star", "Nick", 0, 30, 10)              # weak through week 2 ...
            + _stint("Late Star", "Nick", 31, 60, 80)            # ... a monster after
            + _stint("Late Star", "Hayden", 61, end, 80)         # ... and traded
            + _stint("Newcomer", "Hayden", 40, end, 70))
    trades = [{"season": SEASON, "date": DAYS[61].isoformat(), "players": [
        {"player_name": "Late Star", "from_manager": "Nick", "to_manager": "Hayden"}]}]
    full = _world(late, trades=trades)
    w2_day = kh.as_of_points(full.log[SEASON], SEASON)["week2"][1]
    cut = kh.Inputs(log={SEASON: [r for r in full.log[SEASON] if r["date"] <= w2_day]},
                    picks=full.picks, trades=[])
    a = kh.snapshot(full, DECISION, "week2", check=False)
    b = kh.snapshot(cut, DECISION, "week2", check=False)
    assert [asdict(c) for c in a.candidates] == [asdict(c) for c in b.candidates]
    star = next(c for c in a.candidates if c.player == "Late Star")
    assert star.fppg == 10 and star.manager == "Nick" and star.fppg_rank == 9
    assert "Newcomer" not in {c.player for c in a.candidates}
    # ...and at season's end the same player reads the whole season
    e = next(c for c in kh.snapshot(full, DECISION, "end", check=False).candidates if c.player == "Late Star")
    assert e.manager == "Hayden" and e.fppg > 50 and e.acquired == "trade"


def test_the_point_in_time_holds_on_the_real_log_too():
    inputs = kh.Inputs.load(ROOT)
    season = kh.prev_season("2026-27")
    day = kh.as_of_points(inputs.log[season], season)["mid"][1]
    cut = kh.Inputs(log={**inputs.log, season: [r for r in inputs.log[season] if r["date"] <= day]},
                    picks=inputs.picks, trades=inputs.trades)
    a = kh.snapshot(inputs, "2026-27", "mid", check=False)
    b = kh.snapshot(cut, "2026-27", "mid", check=False)
    assert [asdict(c) for c in a.candidates] == [asdict(c) for c in b.candidates]


def test_the_as_of_points_are_week_2_mid_and_the_last_day():
    w = _world()
    pts = kh.as_of_points(w.log[SEASON], SEASON)
    assert pts["week2"] == (2, DAYS[13].isoformat())
    assert pts["mid"] == (11, DAYS[11 * 7 - 1].isoformat())          # ceil(21 / 2)
    assert pts["end"] == (12, DAYS[-1].isoformat())
    with pytest.raises(KeyError, match="regular_through"):
        kh.as_of_points(w.log[SEASON], "1999-00")


# 3 -- a traded keeper carries "kept" and his round to the new team
def test_a_traded_keeper_carries_kept_and_round_to_his_new_team():
    end = len(DAYS) - 1
    extra = (_stint("Old Keeper", "Hayden", 0, 40, 40) + _stint("Old Keeper", "Nick", 41, end, 40)
             + _stint("Second Rounder", "Hayden", 0, 40, 35) + _stint("Second Rounder", "Nick", 41, end, 35)
             + _stint("Waiver Guy", "Nick", 20, end, 30))
    picks = [{"season": SEASON, "manager": "Hayden", "player_name": "Old Keeper", "round": 12,
              "pick_number": 47, "is_keeper": True},
             {"season": SEASON, "manager": "Hayden", "player_name": "Second Rounder", "round": 2,
              "pick_number": 6, "is_keeper": False},
             {"season": SEASON, "manager": "Nick", "player_name": "Nick 0", "round": 1, "pick_number": 1,
              "is_keeper": False}]
    trades = [{"season": SEASON, "date": DAYS[41].isoformat(), "players": [
        {"player_name": n, "from_manager": "Hayden", "to_manager": "Nick"}
        for n in ("Old Keeper", "Second Rounder")]}]
    snap = kh.snapshot(_world(extra, picks_now=picks, trades=trades), DECISION, "end", check=False)
    c = {x.player: x for x in snap.candidates}
    assert c["Old Keeper"].manager == "Nick" and c["Old Keeper"].kept and c["Old Keeper"].acquired == "trade"
    assert c["Old Keeper"].draft_round is None and not c["Old Keeper"].undrafted
    assert c["Second Rounder"].draft_round == 2 and not c["Second Rounder"].kept
    assert c["Second Rounder"].acquired == "trade"
    assert c["Waiver Guy"].undrafted and c["Waiver Guy"].acquired == "pickup"
    assert c["Nick 0"].acquired == "draft" and c["Nick 0"].draft_round == 1


def test_a_trade_dated_as_a_week_range_is_placed_and_anything_else_raises():
    assert kh.trade_dates("2026-01-27", "2025-26") == ("2026-01-27", "2026-01-27")
    assert kh.trade_dates("Feb 2 - Feb 8", "2025-26") == ("2026-02-02", "2026-02-08")
    assert kh.trade_dates("Dec 29 - Jan 4", "2025-26") == ("2025-12-29", "2026-01-04")
    for bad in ("", "sometime in February", "Feb 2", "2026-13-01"):
        with pytest.raises(ValueError):
            kh.trade_dates(bad, "2025-26")


# 4 -- appearances: not an injured row, not a no-game day; bench games count
def test_appearances_exclude_injured_rows_and_no_game_days():
    rows = [_row("P", "Nick", 0, 40.0),                                   # played
            _row("P", "Nick", 1, 0.0, had_game=False),                    # off day
            _row("P", "Nick", 2, 0.0, injured=True),                      # had a game, sat
            _row("P", "Nick", 3, 30.0, started=False),                    # played from the bench
            _row("P", "Nick", 4, -2.0)]                                   # a real, bad game
    assert [kh.appeared(r) for r in rows] == [True, False, False, True, True]
    assert kh._season_line(rows) == (3, pytest.approx(68.0 / 3))
    with pytest.raises(ValueError, match="is_injured"):
        kh.appeared({k: v for k, v in rows[0].items() if k != "is_injured"})
    snap = kh.snapshot(_world(_stint("P2", "Nick", 0, 13, 50, every=2)), DECISION, "week2", check=False)
    p2 = next(c for c in snap.candidates if c.player == "P2")
    assert p2.games == 7 and p2.team_games == 7 and p2.availability == 1.0


# 5 -- every rule ranks deterministically, ties by name
def _cand(player, fppg=None, kept=False, rnd=None):
    return kh.Candidate(decision=DECISION, season=SEASON, point="end", as_of="x", manager="Nick",
                        player=player, kept_next=False, kept=kept, draft_round=rnd,
                        undrafted=not kept and rnd is None, acquired="draft", stint_start="x",
                        games=0 if fppg is None else 10, fppg=fppg, fppg_rank=0, team_games=10,
                        availability=None, days_rostered=1, first_day="x", prev_games=None,
                        prev_fppg=None, age=None)


def test_each_rule_ranks_deterministically_ties_by_name():
    cands = [_cand("Zed", 40.0, kept=True), _cand("Abe", 40.0, kept=True), _cand("Moe", 50.0, rnd=1),
             _cand("Bo", 30.0, rnd=1), _cand("Al", 30.0, rnd=3), _cand("Cy", None), _cand("Ax", None)]
    names = lambda xs: [c.player for c in xs]
    assert names(kb.rule_a(cands)) == ["Abe", "Zed", "Moe", "Al", "Bo", "Ax", "Cy"]
    assert names(kb.rule_b(cands)) == ["Abe", "Zed", "Bo", "Moe", "Al", "Ax", "Cy"]
    assert names(kb.rule_c(cands)) == ["Moe", "Abe", "Zed", "Al", "Bo", "Ax", "Cy"]
    for rule in (kb.rule_a, kb.rule_b, kb.rule_c):
        assert names(rule(list(reversed(cands)))) == names(rule(cands))


def test_hits_count_each_managers_top_k_against_his_keepers():
    snap = kh.Snapshot(DECISION, "end", 12, "x", {}, {"Nick": ["A", "B"], "Hayden": ["C", "D"]}, 4, [])
    assert kb.hits(snap, {"Nick": ["A", "X", "B"], "Hayden": ["D", "C", "E"]}) == 3


# 6 -- a missing age is reported, never guessed; a failed fetch raises
def test_a_missing_age_takes_the_neighbouring_season_and_says_so():
    """Nick, 10-29: the following season's age - 1, else the preceding + 1;
    the source is recorded; neither raises (HANDOFF_HISTORY_FIXES 3)."""
    nxt, prv = kh.next_season(SEASON), kh.prev_season(SEASON)
    ages = {SEASON: kh.PlayerIndex({"Nick 0": 25}),
            nxt: kh.PlayerIndex({"Nick 1": 30, "Nick 2": 40}),
            prv: kh.PlayerIndex({"Nick 2": 50, "Nick 3": 22})}
    assert kh.age_for(ages, SEASON, "Nick 0") == (25, f"bbref {SEASON}")
    assert kh.age_for(ages, SEASON, "Nick 1") == (29, f"bbref {nxt} - 1")
    assert kh.age_for(ages, SEASON, "Nick 2") == (39, f"bbref {nxt} - 1")      # following first
    assert kh.age_for(ages, SEASON, "Nick 3") == (23, f"bbref {prv} + 1")
    with pytest.raises(kh.AgeNotFound, match="Nick 4"):
        kh.age_for(ages, SEASON, "Nick 4")
    w = _world()
    with pytest.raises(kh.AgeNotFound):                    # nobody's age is guessed
        kh.build(w, decisions=(DECISION,), points=("end",), ages=ages)
    full = {s: kh.PlayerIndex({**{f"Nick {k}": 20 + k for k in range(8)},
                               **{f"Hay {k}": 30 + k for k in range(8)}})
            for s in (nxt,)}
    snap = kh.build(w, decisions=(DECISION,), points=("end",), ages={**ages, **full})[(DECISION, "end")]
    c = {x.player: x for x in snap.candidates}
    assert (c["Nick 0"].age, c["Nick 0"].age_source) == (25, f"bbref {SEASON}")
    assert (c["Hay 3"].age, c["Hay 3"].age_source) == (32, f"bbref {nxt} - 1")
    s = kh.summary(w, kh.build(w, decisions=(DECISION,), points=kh.POINTS, ages={**ages, **full}))[0]
    assert "Hay 3 (bbref 2025-26 - 1)" in s["age_from_neighbour"] and s["missing_age"] == []


def test_the_three_real_missing_ages_come_from_the_following_season():
    ages = kh.load_ages(kh.age_seasons(), ROOT)
    assert kh.age_for(ages, "2021-22", "Kawhi Leonard") == (30, "bbref 2022-23 - 1")
    assert kh.age_for(ages, "2021-22", "Zion Williamson") == (21, "bbref 2022-23 - 1")
    assert kh.age_for(ages, "2025-26", "Tyrese Haliburton")[1].startswith("bbref 2026-27")


def test_a_failed_basketball_reference_fetch_raises_and_writes_nothing(tmp_path):
    from scripts.fetch_playerlist import AgeFetchError

    def down(url):
        raise OSError("connection refused")
    with pytest.raises(AgeFetchError, match="NBA_2025"):
        kh.load_ages([SEASON], root=tmp_path, fetch=down)
    assert not (tmp_path / kh.AGES_FILE).exists()
    page = '<tr><td data-stat="name_display"><a href="x">Nikola Joki\u0107</a></td><td data-stat="age">29</td></tr>'
    ages = kh.load_ages([SEASON], root=tmp_path, fetch=lambda url: page, today="2026-10-29")
    assert ages[SEASON]["Nikola Jokic"] == 29
    cached = json.loads((tmp_path / kh.AGES_FILE).read_text(encoding="utf-8"))
    assert cached["seasons"][SEASON]["fetched"] == "2026-10-29"
    assert cached["seasons"][SEASON]["url"].endswith("NBA_2025_per_game.html")
    assert kh.load_ages([SEASON], root=tmp_path, fetch=down)[SEASON]["Nikola Jokic"] == 29   # cached: no fetch


# the v2.2 reproduction reads past seasons exactly as keepability_v2 does
def test_v22_history_matches_keepability_v2s_own_extraction():
    import pandas as pd
    from modules import keepability_v2 as v2
    w = _world(_stint("Hist", "Nick", 0, 60, 33, every=3))
    hist = kb.V22History(w)
    log = [r for rows in w.log.values() for r in rows]
    empty = pd.DataFrame(columns=["player_name", "week", "fantasy_points", "nba_opponent"])
    theirs = v2.extract_player_season_stats("Hist", log, empty, "2099-00", {}, 1)
    assert [asdict(s) for s in theirs] == [asdict(hist.whole[SEASON]["Hist"])]
