"""4c7: the awards extension (claude/HANDOFF_4C7_AWARDS_EXTENSION_2026-11-22.md).

A. The rest of the season's awards for past seasons (modules/awards_past):
   Best pickup off the daily rosters (pickup vs trade arrival, preseason
   adds out), Rookie of the Year from NBA_SEASONS (ROOKIE_SEASONS checked),
   Bust's past expectation = his previous NBA season's FPPG (this season's
   unchanged), Player of the Week's seasons.
B. The trophy case (modules/trophy_case): League Championships = LEAGUEHISTORY
   titles_won = season_outcomes.league_champion; playoff titles =
   playoff_championships; the credit rules; Bust and Unluckiest apart.
C. The manager awards (modules/manager_awards): fill rate on a fixture day,
   the draft class with keepers apart, Unluckiest on a fixture week.
D. One measure per idea: the record book's retired lists and the awards'
   lists in their place.
E. The display: manager awards, Past winners, the trophy case, every column
   defined, the champion guard.
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

from modules import awards as A, awards_past as P, manager_awards as MA, trophy_case as TC, keeper_history as kh

ROOT = Path(__file__).resolve().parents[1]


def _past(reg=5, **kw):
    from test_awards_past import _past as base
    return base(reg=reg, **kw)


def _season(pi, only=P.PAST):
    return A.compute(pi, A._week(pi, pi["reg"])["end_date"], only=only)


# =============================================================================
# A. past seasons
# =============================================================================

def test_a_past_pickup_is_a_stint_off_the_rosters_never_a_trade_arrival():
    _i, pi, _ = _past()
    res = _season(pi)
    st = {(s["player"], s["m"], s["add_day"]): s for s in res["awards"]["pickup"]["stints"]}
    assert set(st) == {("Quinn Rookie", "Jordan", "2026-10-12"), ("Pat Journey", "Dana", "2026-10-12"),
                       ("Pat Journey", "Dana", "2026-11-02")}
    # one arrival and one departure that day: the drop is read off the rosters
    assert st[("Quinn Rookie", "Jordan", "2026-10-12")]["drops"] == ["Jordan Role"]
    assert st[("Pat Journey", "Dana", "2026-11-02")]["drops"] == ["Dana Bench"]
    # the Marcus <-> Tyler trade (10-19, all_trades) brings both Stars: never pickups
    assert not any(s[0].endswith("Star") for s in st)
    # PAR in his starts for the adder, from the add through the regular season
    q = st[("Quinn Rookie", "Jordan", "2026-10-12")]
    R = res["R"]
    want = sum(r["fantasy_points"] - R[int(r["week"])]["R"] for r in pi["rows"]
               if r["player_name"] == "Quinn Rookie" and r["manager"] == "Jordan" and r["started"]
               and kh.appeared(r) and int(r["week"]) <= 5)
    assert q["value"] == pytest.approx(want)
    assert res["awards"]["pickup"]["rows"][0]["label"] == "Quinn Rookie"


def test_without_its_trade_a_roster_to_roster_move_is_a_pickup_and_is_listed():
    i, pi, _ = _past()
    pi = dict(pi, inputs=kh.Inputs(log=pi["inputs"].log, picks=pi["inputs"].picks, trades=[]))
    res = _season(pi, only=("pickup",))
    got = {(s["player"], s["m"]) for s in res["awards"]["pickup"]["stints"]}
    assert ("Tyler Star", "Marcus") in got and ("Marcus Star", "Tyler") in got
    off = res["awards"]["pickup"]["off_rosters"]
    assert {(x["player"], x["from"], x["to"]) for x in off} == {("Tyler Star", "Tyler", "Marcus"),
                                                              ("Marcus Star", "Marcus", "Tyler")}


def test_an_opening_day_player_not_drafted_or_kept_is_a_preseason_add_and_out():
    _i, pi, _ = _past()
    picks = [p for p in pi["inputs"].picks["2026-27"] if p["player_name"] != "Marcus Role"]
    pi = dict(pi, inputs=kh.Inputs(log=pi["inputs"].log, picks={"2026-27": picks}, trades=pi["inputs"].trades))
    a = _season(pi, only=("pickup",))["awards"]["pickup"]
    assert [(e["who"], e["kind"]) for e in a["excluded"]] == [("Marcus Role", "preseason add")]
    assert "preseason adds are not moves" in a["excluded"][0]["reason"]      # 5e: no rule numbers in the UI
    assert not any(s["player"] == "Marcus Role" for s in a["stints"])


def test_a_missing_team_day_never_breaks_a_stint():
    """2017-18 misses whole days for one team: a stint runs over the manager's
    own logged days, so no false re-add."""
    _i, pi, _ = _past()
    rows = [r for r in pi["rows"] if not (r["manager"] == "Jordan" and r["date"] == "2026-10-20")]
    pi = dict(pi, rows=rows)
    st = _season(pi, only=("pickup",))["awards"]["pickup"]["stints"]
    assert [(s["player"], s["stint"][0]) for s in st if s["m"] == "Jordan"] == [("Quinn Rookie", "2026-10-12")]


def test_rookie_of_the_year_reads_nba_seasons_and_reports_where_rookie_seasons_disagrees():
    import awards_fixture as AF
    i, pi, _ = _past()
    assert pi["rookie_check"]["rookies"] == ["Quinn Rookie"]
    out = P.season_awards(pi)
    assert out["awards"]["roy"]["winner"]["label"] == "Quinn Rookie"
    assert out["checks"]["rookies"]["rule"].startswith("NBA_SEASONS wins")
    # ROOKIE_SEASONS says Marcus Wing is a rookie; NBA_SEASONS (2014-15) wins, and the check names him
    rk, chk = P.rookie_seasons(AF.nba_ctx({"Quinn Rookie": AF.SEASON, "Marcus Wing": AF.SEASON}), AF.SEASON,
                               pi["rows"])
    assert rk["Marcus Wing"] == "2014-15 or earlier" and chk["rookies"] == ["Quinn Rookie"]
    assert chk["disagree"] == [{"player": "Marcus Wing", "nba_seasons": "2014-15 or earlier",
                                "rookie_seasons": AF.SEASON}]


def test_a_rookie_the_file_cannot_place_is_raised_not_guessed():
    import awards_fixture as AF
    nba = AF.nba_ctx()
    nba["blob"]["players"].pop(str(AF.PID["Quinn Rookie"]))
    from modules import nba_prior
    nba["index"] = nba_prior.Index(nba["blob"], {})
    _i, pi, _ = _past()
    rk, chk = P.rookie_seasons(nba, AF.SEASON, pi["rows"])
    pi = dict(pi, rookies=rk, rookie_check=chk)
    assert "Quinn Rookie" in chk["unplaced"]
    with pytest.raises(P.AwardsPastError, match="roy"):
        P.season_awards(pi)
    nba = AF.nba_ctx()
    nba["unmatched"] = {"Quinn Rookie": {"2025-26"}}           # an earlier season could hide his first one
    with pytest.raises(P.AwardsPastError, match="not known"):
        P.rookie_season(nba, "Quinn Rookie", AF.PID["Quinn Rookie"])


def test_a_past_bust_is_measured_against_his_previous_nba_season():
    """The fixture: each Wing's 2025-26 FPPG is his level + 6 + i; his season
    line is his level over 30 games, so he is (6 + i) x 30 short."""
    import awards_fixture as AF
    _i, pi, _ = _past()
    a = _season(pi, only=("bust",))["awards"]["bust"]
    assert "2025-26 NBA FPPG" in a["source"] and "no preseason projection" in a["source"]
    got = {r["label"]: r for r in a["rows"]}
    for k, m in enumerate(AF.MGRS):
        r = got[f"{m} Wing"]
        assert r["expected"] == pytest.approx(AF.LEVEL[f"{m} Wing"] + 6 + k)
        assert r["value"] == pytest.approx((6 + k) * 30) and r["games"] == 30
    assert a["rows"][0]["label"] == "Jordan Wing"
    # drafted or kept only: Quinn Rookie (a pickup) is never judged
    assert "Quinn Rookie" not in got


def test_this_seasons_bust_is_unchanged():
    import awards_fixture as AF
    a = A.compute(AF.inp(), AF.LAST)["awards"]["bust"]
    assert a["source"].startswith("Yahoo's preseason projection")
    assert all("expected" in r["shown"] for r in a["rows"])


def test_potw_by_season_most_wins_and_best_week(tmp_path):
    from modules.data_loader import CURRENT_SEASON
    (tmp_path / "config").mkdir()
    hist = {"seasons": {"2025-26": [
        {"week": 1, "player": "Ann Star", "manager": "Dana", "total_fp": 200.0, "games": 4, "fppg": 50.0},
        {"week": 2, "player": "Bo Wing", "manager": "Tyler"},                             # filled from the log
        {"week": 3, "player": "Ann Star", "manager": "Dana", "total_fp": 210.5, "games": 3, "fppg": 70.17}],
        CURRENT_SEASON: [{"week": 1, "player": "Zed", "manager": "Dana", "total_fp": 999.0, "games": 4, "fppg": 1.0}]}}
    (tmp_path / "config" / "POTW_HISTORY.json").write_text(json.dumps(hist), encoding="utf-8")
    rows = [{"season_key": "2025-26", "week": 2, "date": f"2025-10-2{d}", "manager": "Tyler", "player_name": "Bo Wing",
             "fantasy_points": 120.0, "started": True, "had_game": True, "is_injured": False} for d in (1, 2)]
    out = P.potw(tmp_path, kh.Inputs(log={"2025-26": rows}, picks={}, trades=[]))
    assert list(out) == ["2025-26"]                                      # this season is not final
    s = out["2025-26"]
    assert s["most_wins"] == [{"player": "Ann Star", "wins": 2, "ms": ["Dana"]}]
    assert s["best_week"]["player"] == "Bo Wing" and s["best_week"]["total_fp"] == 240.0 and s["best_week"]["from_log"]


def test_the_whole_season_record_is_valid():
    import awards_fixture as AF
    _i, pi, _ = _past()
    out = P.season_awards(pi)
    assert set(out["awards"]) == set(P.PAST) and set(out["managers"]) == set(MA.KEYS)
    blob = AF.past_blob()
    P.validate(blob)
    assert set(blob["best"]) == set(P.BEST_KEYS)


# =============================================================================
# B. the trophy case
# =============================================================================

def test_the_trophy_case_credits_each_award_and_keeps_bust_and_unlucky_apart():
    import awards_fixture as AF
    blob = AF.past_blob()
    st = []
    for s, champ, pchamp in (("2024-25", "Dana", "Tyler"), ("2025-26", "Marcus", None)):
        for i, m in enumerate(AF.MGRS):
            st.append({"season": s, "manager": m, "regular_season_rank": 1 if m == champ else 2 + i,
                       "playoff_rank": (1 if m == pchamp else 2 + i) if pchamp else None,
                       "reg_wins": 10, "reg_losses": 5, "points_for": 1000.0})
    cfg = {"managers": AF.MGRS, "pre_data_era": {"seasons": {"2016-17": {
        "league_champion": "Jordan", "league_runner_up": "Dana", "playoff_champion": "Jordan",
        "playoff_runner_up": "Dana"}}}, "keeper_rules": {"cup_winners": {"2026-27": None}}}
    tc = TC.build(ROOT, past=blob, standings=st, cfg=cfg, managers=AF.MGRS)
    row = {r["m"]: r for r in tc["managers"]}
    assert row["Jordan"]["counts"]["league"] == 1 and row["Jordan"]["counts"]["playoff"] == 1    # 2016-17
    assert row["Dana"]["counts"]["league"] == 1 and row["Marcus"]["counts"]["league"] == 1
    assert row["Tyler"]["counts"]["playoff"] == 1 and sum(r["counts"]["cup"] for r in tc["managers"]) == 0
    # MVP to ms[0]; Best pickup to the adder; Trade of the Year to its winner; manager awards to the winners
    assert [x["season"] for x in row["Marcus"]["items"]["mvp"]] == ["2024-25"]
    assert [x["season"] for x in row["Tyler"]["items"]["mvp"]] == ["2025-26"]
    assert row["Jordan"]["counts"]["trade"] == 1 and row["Dana"]["counts"]["lineup"] == 2
    assert row["Jordan"]["counts"]["bust"] == 2 and "bust" in tc["apart"] and "unlucky" in tc["apart"]
    assert tc["order"][:3] == ["league", "playoff", "cup"]
    # League Championships, then playoff titles, then the config's manager order
    assert [r["m"] for r in tc["managers"]] == ["Jordan", "Marcus", "Dana", "Tyler"]


def test_the_trophy_case_raises_on_an_unknown_manager():
    import awards_fixture as AF
    with pytest.raises(TC.TrophyCaseError):
        TC.build(ROOT, past=None, standings=[{"season": "2024-25", "manager": "Nobody", "regular_season_rank": 1,
                                              "playoff_rank": 1, "reg_wins": 1, "reg_losses": 0, "points_for": 1.0}],
                 cfg={"managers": AF.MGRS}, managers=AF.MGRS)


def _needs_real():
    import league_state
    return league_state.needs_state("data/historical/all_standings.json", "data/LEAGUEHISTORY.xlsx",
                                    why="the trophy case against LEAGUEHISTORY")


@_needs_real()
def test_real_trophy_case_titles_equal_leaguehistory_and_season_outcomes():
    import pandas as pd
    from modules import season_outcomes as SO
    tc = TC.build(ROOT)
    lh = pd.read_excel(ROOT / "data" / "LEAGUEHISTORY.xlsx")
    by = {r["m"]: r for r in tc["managers"]}
    for _, r in lh.iterrows():
        assert by[r["manager_name"]]["counts"]["league"] == int(r["titles_won"])
        assert by[r["manager_name"]]["counts"]["playoff"] == int(r["playoff_championships"])
    st = json.loads((ROOT / "data/historical/all_standings.json").read_text(encoding="utf-8"))
    seasons: dict = {}
    for r in st:
        seasons.setdefault(r["season"], []).append(r)
    for s, rs in seasons.items():
        who = [m for m, r in by.items() if any(x["season"] == s for x in r["items"]["league"])]
        assert who == [SO.league_champion(rs)], s


# =============================================================================
# C. the manager awards
# =============================================================================

def test_fill_rate_on_a_fixture_day():
    """5e (4C7 decision 3): the share of ALL daily slots filled. Tue 2026-10-06:
    Tyler starts Star, Wing (hurt, but his team played: the slot is filled)
    and Role: 3 of 10. Marcus 3 of 10. Sun 2026-10-11 has no NBA game: not a
    day of the measure. More than ten starts on a day RAISES."""
    _i, pi, _ = _past()
    day = [r for r in pi["rows"] if r["date"] in ("2026-10-06", "2026-10-11")]
    res = dict(_season(pi, only=("pickup",)), cut="2026-10-11")
    f = MA.fill(dict(pi, rows=day), res)
    assert (f["Tyler"]["filled"], f["Tyler"]["slots"], f["Tyler"]["days"]) == (3, 10, 1)
    assert (f["Marcus"]["filled"], f["Marcus"]["slots"]) == (3, 10)
    bad = [dict(r, started=True) for r in day if r["manager"] == "Marcus" and r["date"] == "2026-10-06"]
    bad += [dict(bad[0], player_name=f"X{k}") for k in range(8)]             # 12 starts, 10 seats
    with pytest.raises(MA.ManagerAwardsError, match="seats hold"):
        MA.fill(dict(pi, rows=bad), res)


@pytest.mark.slow
def test_real_2025_26_fill_rates():
    """5e: 2025-26's fill rates as the league measured them (LEAGUE_RULES via
    the 4C7 decisions: Nick 73, Garrett 68, Hayden 67, Benton 66, over the
    whole season). This measure over the whole season (every NBA day of the
    log, 10-21 to 04-05, 158 days) gives Nick 72.4, Garrett 67.8, Benton 66.3,
    Hayden 66.1: within a point, Hayden and Benton a fifth of a point apart and
    in the other order (claude/5E_RESULT s.4: the old measure said 157 days;
    its "more than 10 players with a game on 37 days" is reproduced exactly).
    The award counts the regular season only (weeks 1-21 then)."""
    from modules import keeper_history as kh
    inputs = kh.Inputs.load(ROOT)
    rows = inputs.log["2025-26"]
    last = max(r["date"] for r in rows)
    f = MA.fill({"season": "2025-26", "rows": rows, "reg": 99}, {"cut": last})
    got = {m: round(100 * x["filled"] / x["slots"], 1) for m, x in f.items()}
    assert got == {"Nick": 72.4, "Garrett": 67.8, "Benton": 66.3, "Hayden": 66.1}
    assert {x["days"] for x in f.values()} == {158}
    blob = json.loads((ROOT / "data/historical/AWARDS_PAST.json").read_text(encoding="utf-8"))
    reg = {r["m"]: r["shown"] for r in blob["seasons"]["2025-26"]["managers"]["lineup"]["top"]}
    assert reg == {"Nick": "72.1%", "Garrett": "67.4%", "Benton": "66.0%", "Hayden": "64.9%"}


def test_rookie_of_the_year_needs_ten_starts():
    """5e (4C7 decision 5): a rookie one start under the minimum is listed but
    can't lead; at the minimum he is eligible (the fixture's rookie has n
    starts: minimum n+1 is "9 of 10", minimum n is "10 of 10"). The minimum is
    a config key and a missing key RAISES."""
    _i, pi, _ = _past()
    cfg = dict(pi["cfg"])

    def roy(need):
        return A.compute(dict(pi, cfg=dict(cfg, roy_min_starts=need)), pi["days"][-1], only=("roy",))["awards"]["roy"]
    a = roy(1)
    assert a["rows"], "the fixture has a rookie"
    top = a["rows"][0]
    n = top["starts"]
    a = roy(n)
    assert a["rows"][0]["key"] == top["key"]
    assert all(r["starts"] >= n for r in a["rows"]) and all(r["starts"] < n for r in a["ineligible"])
    a = roy(n + 1)
    assert top["key"] not in {r["key"] for r in a["rows"]}
    x = next(r for r in a["ineligible"] if r["key"] == top["key"])
    assert x["sub"] in (f"not yet eligible ({n} of {n + 1} starts)", f"ineligible ({n} of {n + 1} starts)")
    cfgm = {k: v for k, v in cfg.items() if k != "roy_min_starts"}
    with pytest.raises(A.AwardsInputError, match="roy_min_starts"):
        A.config({"awards": cfgm})


def test_draft_of_the_year_counts_the_draft_class_with_keepers_apart():
    _i, pi, _ = _past()
    res = _season(pi)
    dc = MA.draft_class(pi, res)
    R = res["R"]

    def par(n, m):
        return sum(r["fantasy_points"] - R[int(r["week"])]["R"] for r in pi["rows"]
                   if r["player_name"] == n and r["manager"] == m and r["started"] and kh.appeared(r)
                   and int(r["week"]) <= pi["reg"])
    j = dc["Jordan"]
    assert j["par"] == pytest.approx(par("Jordan Wing", "Jordan") + par("Jordan Role", "Jordan")
                                     + par("Jordan Bench", "Jordan"))
    assert j["keepers"] == 1 and j["keepers_par"] == pytest.approx(par("Jordan Star", "Jordan"))
    rec = MA.compute(pi, res)
    row = next(r for r in rec["awards"]["draft"]["rows"] if r["m"] == "Jordan")
    assert row["value"] == pytest.approx(j["par"]) and "keepers apart" in row["sub"]
    none = MA.compute(dict(pi, inputs=kh.Inputs(log=pi["inputs"].log, picks={}, trades=[])), res)
    assert none["awards"]["draft"]["rows"] == [] and "no draft list" in none["awards"]["draft"]["none"]


def test_unluckiest_on_a_fixture_week():
    """Week 1: A 100 v B 110, C 90 v D 50; the median 95: A beat it and lost
    (1 loss), B won, C was under it. Week 2: A 100 v B 100 (a tie, both over
    the median 55): half a loss each."""
    inp = {"season": "x", "tie_value": 0.5, "weeks": [
        {"week": 1, "matchups": [{"manager_a": "A", "manager_b": "B"}, {"manager_a": "C", "manager_b": "D"}]},
        {"week": 2, "matchups": [{"manager_a": "A", "manager_b": "B"}, {"manager_a": "C", "manager_b": "D"}]}]}
    res = {"finished": [1, 2], "totals": {1: {"A": 100.0, "B": 110.0, "C": 90.0, "D": 50.0},
                                          2: {"A": 100.0, "B": 100.0, "C": 10.0, "D": 0.0}}}
    u = MA.unlucky(inp, res)
    assert u["A"]["losses"] == 1.5 and u["B"]["losses"] == 0.5 and u["C"]["losses"] == 0
    assert u["A"]["weeks_above"] == 2 and u["C"]["weeks_above"] == 0 and u["A"]["pa"] == 210.0


def test_waiver_king_sums_every_pickup_stint():
    _i, pi, _ = _past()
    res = _season(pi)
    w = MA.waiver(res)
    stints = res["awards"]["pickup"]["stints"]
    assert w["Dana"]["n"] == 2 and w["Dana"]["par"] == pytest.approx(sum(s["value"] for s in stints if s["m"] == "Dana"))
    rec = MA.compute(pi, res)
    assert rec["awards"]["waiver"]["winners"] == ["Jordan"]
    assert [r["m"] for r in rec["awards"]["waiver"]["rows"]][-2:] == ["Marcus", "Tyler"]       # 0, by name


# =============================================================================
# D. one measure per idea
# =============================================================================

def test_the_record_book_retires_the_overlapping_lists_and_writes_the_awards_measures():
    import awards_fixture as AF
    sys.path.insert(0, str(ROOT / "scripts"))
    import backfill_player_records as B
    out = B.award_records(AF.past_blob())
    assert set(out) == {"best_pickup", "best_pickup_top10", "lopsided_trade", "lopsided_trade_top10",
                        "draft_of_year", "draft_of_year_top10"}                     # 5e
    assert out["draft_of_year"]["manager"] == "Dana" and out["draft_of_year"]["par_per_week"] == 42.86
    assert out["best_pickup"]["par"] == 420.5 and out["lopsided_trade"]["par_gap"] == 300.0
    B.check_written_leaderboards(out)
    with pytest.raises(FileNotFoundError):
        B.award_records(None)
    src = (ROOT / "scripts" / "backfill_player_records.py").read_text(encoding="utf-8")
    assert "for k in RETIRED_KEYS:" in src and '"tw_top10"' not in src
    from modules.hub_v2 import league as L
    assert not {"trade_winner", "best_waiver_pickup"} & {k for k, *_ in L.RECORD_BOOK}


def test_best_draft_class_is_retired_with_no_reader_left():
    """5e (4C7 decision 6): Draft of the year replaces best_draft_class
    everywhere; the only mentions left are the retirement itself."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import backfill_player_records as B
    assert {"best_draft_class", "best_draft_class_top10", "best_draft_class_fppg",
            "best_draft_class_fppg_top10"} <= set(B.RETIRED_KEYS)
    hits = []
    for d in ("modules", "scripts", "templates"):
        for p in (ROOT / d).rglob("*"):
            if p.suffix in (".py", ".html", ".md", ".txt", ".j2") and p.is_file():
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if "best_draft_class" in line and "5e" not in line and "RETIRED" not in line \
                            and '"best_draft_class", "best_draft_class_top10"' not in line:
                        hits.append(f"{p.relative_to(ROOT)}:{i}")
    assert not hits, hits
    from modules import player_card_builder as PCB
    assert "best_draft_class" not in PCB.RECORD_BOOK_LABELS and "draft_of_year" in PCB.RECORD_BOOK_LABELS


# =============================================================================
# E. the display
# =============================================================================

def _hub():
    from test_hub_v2 import synth_payload
    return synth_payload()


def test_awards_show_the_manager_awards_with_past_winners_and_potw_seasons():
    from datetime import datetime
    from modules.hub_v2 import view, page, page_league as PL, publish_check as PC
    p = _hub()
    vm = view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]))
    h = PL.awards_html(vm["league"]["awards"], page._mono, page._chart, page.INFO)
    keys = re.findall(r'data-mgr-award="(\w+)"', h)
    assert keys == list(MA.KEYS)
    for k in MA.KEYS:
        sec = re.search(rf'data-mgr-award="{k}".*?</section>', h, re.S).group(0)
        assert "Past winners" in sec
    assert "Most wins" in h and "Best week" in h
    assert not PC.champion_audit({"awards": h})


def test_the_trophy_case_renders_under_all_time_with_every_column_defined():
    from modules.hub_v2 import view, page_league as PL, infotips, publish_check as PC
    from test_hub_v2 import tap_violations
    p = _hub()
    for k in ("team",) + TC.ORDER:
        infotips.column("trophy", k)                                   # raises without a definition
    from datetime import datetime
    from modules.hub_v2 import page
    vm = view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]))
    h = PL.chip_html(vm["league"]["history"], "alltime", page._mono)
    sec = re.search(r'data-section="trophy".*?</section>', h, re.S).group(0)
    assert sec.count('data-colh="trophy|') == len(TC.ORDER) + 1
    assert sec.count("<tr>") == 5 and "data-tip-h=" in sec
    assert not tap_violations("<body>" + sec + "</body>")
    assert not PC.champion_audit({"alltime": h})


def test_the_new_renderers_do_no_arithmetic():
    import inspect
    from modules.hub_v2 import page_league as PL
    src = "".join(inspect.getsource(f) for f in (PL._mgr_award, PL._potw_past, PL._trophy))
    for banned in ("round", "float", "sum", "sorted", "max", "min", "int", "len"):
        assert not re.search(rf"\b{banned}\(", src), f"the League renderer calls {banned}("


def test_a_rookie_under_the_minimum_is_listed_marked_and_never_leads_on_the_hub():
    """5e: the race lists him after the eligible rows, unranked, marked, and he
    is never the leader or on the race chart; with no eligible rookie the card
    says so."""
    _i, pi, _ = _past()
    cfg = dict(pi["cfg"])
    first = A.compute(dict(pi, cfg=dict(cfg, roy_min_starts=1)), pi["days"][-1], only=("roy",))["awards"]["roy"]
    n = first["rows"][0]["starts"]
    res = A.compute(dict(pi, cfg=dict(cfg, roy_min_starts=n + 1)), pi["days"][-1], only=("roy",))
    out = {a["key"]: a for a in A.races(res, [], dict(cfg, roy_min_starts=n + 1))["awards"]}
    roy = out["roy"]
    marked = [r for r in roy["rows"] if r.get("ineligible")]
    assert marked and all(r["rank"] == "–" for r in marked)
    assert marked[0]["sub"].endswith(f"({n} of {n + 1} starts)")
    assert not [r for r in roy["rows"] if not r.get("ineligible")]
    assert roy["empty"] == f"No rookie has {n + 1} starts yet." and roy["leader"] == ""
