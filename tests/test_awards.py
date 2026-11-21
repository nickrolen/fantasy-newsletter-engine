"""
tests/test_awards.py -- 4c5: the league awards and their races
(claude/HANDOFF_4C5_AWARDS_2026-11-19.md s.7; AWARDS_DEFINITIONS_2026-11-14).

On a made-up season (tests/awards_fixture.py): made-up names and numbers.

A. PAR: every number traces to started games (bench points never count; a
   started DNP is no game); R per week is point in time.
B. Wins swung: the synthetic recompute, and a known historical week checked
   by hand (2025-26 week 12, slow: the league log).
C. A traded player's PAR splits for Trade of the Year and sums for MVP.
D. Eligibility excludes with a reason (each award); Rookie of the Year is not
   computed without this season's rookies.
E. Best pickup: free-agent adds only; two stints counted separately; the drop.
F. Most improved's 20-game minimums both ways; Bust's 10 games and its source.
G. The history file: one line per award per week, append-only, the backfill
   equals the weekly writer, the 14-day week is one line.
H. Movement, "new leader", the chart's points equal the lines, no chart text.
I. League > Awards on the hub: a lazy encrypted part; the 4b/4c rules.
J. 4c4's follow-ups: the "(wk 2)" fallback, the Cup column, Standings agree
   with Home on a Monday, POTW points from the started games.
K. Real state (slow; skipped without it): every award, the backfill into a
   temp folder, the v2 preview's Awards, publish mode within the budget.
"""
from __future__ import annotations

import copy
import gzip
import html as _html
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

import awards_fixture as F
import league_state
from modules import awards as A, keeper_history as kh, keepability_v3 as M

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def inp():
    return F.inp()


@pytest.fixture(scope="module")
def res(inp):
    return A.compute(inp, F.LAST)


def _starts(rows, cut=F.LAST):
    return [r for r in rows if r["date"] <= cut and r["started"] and kh.appeared(r)]


# =============================================================================
# A. PAR
# =============================================================================

def test_every_number_traces_to_started_games_and_bench_points_never_count(inp, res):
    R = res["R"]
    want: dict = {}
    for r in _starts(inp["rows"]):
        want[r["player_name"]] = want.get(r["player_name"], 0.0) + r["fantasy_points"] - R[r["week"]]["R"]
    got = {r["player"]: r["value"] for r in res["awards"]["mvp"]["rows"]}
    assert set(got) == set(want)
    for n in want:
        assert got[n] == pytest.approx(want[n])
    assert not any(n.endswith("Bench") for n in got)          # 72+ a game on the bench: never counted
    # raise every bench score: no bench point is credited to anyone. (R itself is OVR's R, whose
    # levels count bench games -- OVR's definition -- so R may move; PAR stays started points - R.)
    rows = copy.deepcopy(inp["rows"])
    for r in rows:
        if not r["started"]:
            r["fantasy_points"] += 500.0
    res2 = A.compute(F.inp(rows=rows), F.LAST)
    got2 = {r["player"]: r for r in res2["awards"]["mvp"]["rows"]}
    assert set(got2) == set(got)
    for n, r in got2.items():
        pts = sum(x["fantasy_points"] for x in _starts(inp["rows"]) if x["player_name"] == n)
        assert r["value"] + sum(res2["R"][x["week"]]["R"] for x in _starts(rows) if x["player_name"] == n) \
            == pytest.approx(pts)


def test_a_started_dnp_is_no_game_and_charged_nothing(res, inp):
    tw = next(r for r in res["awards"]["mvp"]["rows"] if r["player"] == "Tyler Wing")
    started = [r for r in inp["rows"] if r["player_name"] == "Tyler Wing" and r["started"] and r["had_game"]]
    dnp = [r for r in started if r["is_injured"]]
    assert dnp and tw["starts"] == len(started) - len(dnp)


def test_R_is_ovrs_lowest_level_on_the_weeks_last_day(inp, res):
    for w, x in res["R"].items():
        snap = kh.snapshot(inp["inputs"], kh.next_season(F.SEASON), "end", None, check=False, labels=False,
                           as_of=x["as_of"])
        assert x["R"] == pytest.approx(min(M.level_of(c, inp["lp"])[0] for c in snap.candidates))
        wk = next(v for v in inp["weeks"] if v["week"] == w)
        assert x["as_of"] == min(wk["end_date"], F.LAST)


def test_R_per_week_is_point_in_time_later_data_changes_no_earlier_week(res):
    later = F.log("2026-11-30")
    for r in later:
        if r["date"] > F.LAST:
            r["fantasy_points"] *= 7.0                         # wild later games
    res2 = A.compute(F.inp("2026-11-30", rows=later), "2026-11-30")
    for w in (1, 2, 3, 4):
        assert res2["R"][w] == res["R"][w]


# =============================================================================
# B. wins swung
# =============================================================================

def test_wins_swung_recomputes_each_finished_matchup(inp, res):
    R, tie = res["R"], 0.5
    tot: dict = {}
    for r in inp["rows"]:
        if r["started"] and r["date"] <= F.LAST:
            tot.setdefault(r["week"], {}).setdefault(r["manager"], 0.0)
            tot[r["week"]][r["manager"]] += r["fantasy_points"]

    def val(a, b):
        a, b = round(a, 2), round(b, 2)
        return 1.0 if a > b else tie if a == b else 0.0
    for row in res["awards"]["mvp"]["rows"]:
        n, swung = row["player"], 0.0
        by: dict = {}
        for r in _starts(inp["rows"]):
            if r["player_name"] == n:
                x = by.setdefault((r["week"], r["manager"]), [0.0, 0])
                x[0] += r["fantasy_points"]
                x[1] += 1
        for (w, m), (p, g) in by.items():
            if w not in res["finished"]:
                continue
            mu = next(x for x in next(v for v in inp["weeks"] if v["week"] == w)["matchups"]
                      if m in (x["manager_a"], x["manager_b"]))
            o = mu["manager_b"] if mu["manager_a"] == m else mu["manager_a"]
            swung += max(0.0, val(tot[w][m], tot[w][o]) - val(tot[w][m] - p + R[w]["R"] * g, tot[w][o]))
        assert row["swung"] == swung, n
        assert row["shown"] == f"wins swung: {A._half(swung)}"
    assert any(r["swung"] > 0 for r in res["awards"]["mvp"]["rows"])


def test_a_flip_to_a_tie_counts_half():
    inp = {"weeks": [{"week": 1, "matchups": [{"manager_a": "A", "manager_b": "B"}]}], "tie_value": 0.5}
    R = {1: {"R": 10.0}}
    # A 100 - his 30 + 2 x 10 = 90 = B's 90: a W becomes a T
    assert A.wins_swung({(1, "A"): [30.0, 2]}, {1: {"A": 100.0, "B": 90.0}}, inp, R, [1]) == (0.5, 0.0)
    # a T becomes an L: half again
    assert A.wins_swung({(1, "A"): [30.0, 2]}, {1: {"A": 90.0, "B": 90.0}}, inp, R, [1]) == (0.5, 0.0)
    # below replacement: the other direction is a cost, never a swing
    assert A.wins_swung({(1, "A"): [5.0, 2]}, {1: {"A": 85.0, "B": 90.0}}, inp, R, [1]) == (0.0, 1.0)
    # a week not finished counts nothing
    assert A.wins_swung({(1, "A"): [30.0, 2]}, {1: {"A": 100.0, "B": 90.0}}, inp, R, []) == (0.0, 0.0)


@pytest.mark.slow
@league_state.needs_state("data/historical/HISTORICAL_PLAYERLOG.json", "data/historical/all_matchups.json",
                          "config/keepability_v3_params.json", why="a known historical week, from the league log")
def test_wins_swung_recomputes_a_known_historical_week_checked_by_hand():
    """2025-26 week 12 (checked by hand in 4C5_RESULT): Nick 1,713.20 beat
    Benton 1,708.05. R that week = 27.011 (the lowest level on 2026-01-11).
    Luka Doncic started 3 games for 149.90: 1,713.20 - 149.90 + 3 x 27.011 =
    1,644.33 < 1,708.05, a W that becomes an L: 1 win swung."""
    inputs = kh.Inputs.load(ROOT)
    S, W = "2025-26", 12
    rows = inputs.log[S]
    mat = [m for m in json.loads((ROOT / "data/historical/all_matchups.json").read_text(encoding="utf-8"))
           if m["season"] == S and m["week"] == W]
    days = sorted({r["date"] for r in rows if r["week"] == W})
    inp = {"inputs": inputs, "season": S, "reg": 21, "days": sorted({r["date"] for r in rows}),
           "lp": M.level_config(M.load_params()), "quantile": 0.0, "tie_value": 0.5,
           "weeks": [{"week": W, "start_date": days[0], "end_date": days[-1],
                      "matchups": [{"manager_a": m["manager_a"], "manager_b": m["manager_b"]} for m in mat]}]}
    R = A.replacement_levels(inp, days[-1])
    assert R[W]["as_of"] == "2026-01-11" and R[W]["R"] == pytest.approx(27.011, abs=5e-4)
    tot, his = {}, {}
    for r in rows:
        if r["week"] == W and r["started"]:
            tot[r["manager"]] = tot.get(r["manager"], 0.0) + r["fantasy_points"]
            if kh.appeared(r) and r["player_name"] == "Luka Doncic":
                x = his.setdefault((W, r["manager"]), [0.0, 0])
                x[0] += r["fantasy_points"]
                x[1] += 1
    for m in mat:                                              # the log's started totals ARE the results
        assert round(tot[m["manager_a"]], 2) == m["score_a"] and round(tot[m["manager_b"]], 2) == m["score_b"]
    assert round(tot["Nick"], 2) == 1713.20 and round(tot["Benton"], 2) == 1708.05
    assert his == {(W, "Nick"): [pytest.approx(149.90), 3]}
    assert A.wins_swung(his, {W: tot}, inp, R, [W]) == (1.0, 0.0)


# =============================================================================
# C. a traded player
# =============================================================================

def test_a_traded_players_par_sums_for_mvp_and_splits_for_the_trade(inp, res):
    R = res["R"]
    mvp = {r["player"]: r for r in res["awards"]["mvp"]["rows"]}
    ts = mvp["Tyler Star"]
    for_m = sum(r["fantasy_points"] - R[r["week"]]["R"] for r in _starts(inp["rows"])
                if r["player_name"] == "Tyler Star" and r["manager"] == "Marcus")
    for_t = sum(r["fantasy_points"] - R[r["week"]]["R"] for r in _starts(inp["rows"])
                if r["player_name"] == "Tyler Star" and r["manager"] == "Tyler")
    assert ts["value"] == pytest.approx(for_m + for_t) and ts["ms"] == ["Marcus", "Tyler"]
    assert "Marcus" in ts["sub"] and "Tyler" in ts["sub"]
    tr = res["awards"]["trade"]["rows"]
    assert len(tr) == 1
    t = tr[0]
    assert t["sides"]["Marcus"]["par"] == pytest.approx(for_m)        # only Marcus's starts after 10-19
    ms = sum(r["fantasy_points"] - R[r["week"]]["R"] for r in _starts(inp["rows"])
             if r["player_name"] == "Marcus Star" and r["manager"] == "Tyler")
    # H56 s.4.4: Tyler also got Marcus's 2027 2nd, at round 2's expected PAR (est.)
    from modules import draft_values as DV
    est = DV.value(DV.load(), "par", 2)["value"]
    tt = t["sides"]["Tyler"]
    assert tt["players_par"] == pytest.approx(ms) and tt["picks_est"] == pytest.approx(est)
    assert tt["par"] == pytest.approx(ms + est) and t["sides"]["Marcus"]["picks_est"] == 0
    tot_t = ms + est
    assert t["value"] == pytest.approx(abs(for_m - tot_t)) and t["m"] == ("Marcus" if for_m >= tot_t else "Tyler")
    assert "picks est." in t["shown"] and t["picks"] == {"Tyler": [f"Marcus's 2027 2nd (est. {A._d1(est)})"]}


def test_a_trade_after_the_regular_season_is_excluded_with_a_reason():
    late = [{"season": F.SEASON, "date": "2027-02-20", "trader_manager": "Dana", "tradee_manager": "Jordan",
             "players": [{"player_name": "Dana Wing", "to_manager": "Jordan"}]}]
    i = F.inp(extra_trades=late)
    r = A.compute(i, F.LAST)["awards"]["trade"]
    assert [e["kind"] for e in r["excluded"]] == ["after the regular season"]


# =============================================================================
# D. eligibility, never silent
# =============================================================================

def test_each_exclusion_carries_its_reason(res):
    imp = {e["who"]: e for e in res["awards"]["improved"]["excluded"]}
    assert imp["Dana Star"]["kind"] == "no prior league seasons"
    assert imp["Dana Wing"]["kind"] == "under 20 games in his prior league seasons" and "10 games" in imp["Dana Wing"]["reason"]
    assert imp["Dana Role"]["kind"] == "under 20 games this season"
    bust = {e["who"]: e for e in res["awards"]["bust"]["excluded"]}
    assert bust["Dana Role"]["kind"] == "under 10 games: out, not a bust"
    assert bust["Jordan Role"]["kind"] == "not in Yahoo's preseason projections"
    for k in A.KEYS:
        for e in res["awards"][k]["excluded"]:
            assert e["who"] and e["kind"] and e["reason"]


def test_rookie_of_the_year_is_not_computed_without_this_seasons_rookies():
    a = A.compute(F.inp(rookies={n: "2015-16" for n in F.LEVEL}), F.LAST)["awards"]["roy"]
    assert a["rows"] == [] and "lists no 2026-27 rookie" in a["error"] and "build_rookie_seasons.py --update" in a["error"]
    a = A.compute(F.inp(rookies={"Quinn Rookie": F.SEASON}), F.LAST)["awards"]["roy"]
    assert a["rows"] == [] and "are not in it" in a["error"]
    ok = A.compute(F.inp(), F.LAST)["awards"]["roy"]
    assert [r["player"] for r in ok["rows"]] == ["Quinn Rookie"] and ok["error"] is None
    assert re.fullmatch(r"\d+\.\d FPPG in \d+ games", ok["rows"][0]["shown"])


def test_a_missing_config_key_raises():
    with pytest.raises(A.AwardsInputError, match="bust_min_games"):
        A.config({"awards": {k: v for k, v in F.CFG.items() if k != "bust_min_games"}})
    with pytest.raises(A.AwardsInputError, match="no \"awards\" block"):
        A.config({})


# =============================================================================
# E. best pickup
# =============================================================================

def test_best_pickup_is_free_agent_adds_only_and_each_stint_counts(res):
    a = res["awards"]["pickup"]
    players = {r["player"] for r in a["rows"]}
    assert players == {"Quinn Rookie", "Pat Journey"}           # Marcus Role was a preseason add (rule 14)
    assert "Tyler Star" not in players and "Marcus Star" not in players        # trades
    assert not any(n.endswith(("Wing", "Bench")) for n in players)              # the draft
    pat = [s for s in a["stints"] if s["player"] == "Pat Journey"]
    assert [s["stint"] for s in pat] == [["2026-10-12", "2026-10-25"], ["2026-11-02", F.LAST]]
    assert pat[0]["drops"] == ["Dana Role"] and pat[1]["drops"] == ["Dana Bench"]   # one-to-one; same row
    best = next(r for r in a["rows"] if r["player"] == "Pat Journey")
    assert best["value"] == max(s["value"] for s in pat)
    assert next(r for r in a["rows"] if r["player"] == "Quinn Rookie")["shown"] == "dropped Jordan Role on 10-12"
    assert any(x["who"] == "Marcus Role" and x["kind"] == "preseason add" for x in a["excluded"])   # Nick, 11-19


def test_an_unpairable_drop_is_said_not_guessed(inp):
    i = copy.deepcopy(inp)
    i["transactions"].append({"key": "x", "league_day": "2026-10-12", "timestamp": 99, "status": "successful",
                              "type": "drop", "players": [F._p("drop", "Dana Bench", "Dana")], "rulings": []})
    r = A.compute(i, F.LAST)["awards"]["pickup"]
    pat = [s for s in r["stints"] if s["player"] == "Pat Journey"][0]
    assert pat["drops"] == [] and "drop not paired in Yahoo's log" in pat["shown"]


# =============================================================================
# F. most improved and bust
# =============================================================================

def test_most_improved_needs_20_games_both_ways(inp):
    base = A.compute(inp, F.LAST)["awards"]["improved"]
    ms = next(r for r in base["rows"] if r["player"] == "Marcus Star")
    assert ms["games"] >= 20 and ms["shown"] == f"{A._d1(ms['fppg'])} vs {A._d1(ms['usual'])} usual"
    assert ms["usual"] == pytest.approx((25 * 38.0 + 30 * 40.0) / 55)          # P3: games-weighted
    i = copy.deepcopy(inp)
    i["cfg"]["most_improved_min_games"] = ms["games"] + 1
    e = {x["who"]: x for x in A.compute(i, F.LAST)["awards"]["improved"]["excluded"]}
    assert e["Marcus Star"]["kind"] == f"under {ms['games'] + 1} games this season"
    i = copy.deepcopy(inp)
    i["cfg"]["most_improved_min_prior_games"] = 56
    e = {x["who"]: x for x in A.compute(i, F.LAST)["awards"]["improved"]["excluded"]}
    assert e["Marcus Star"]["reason"] == "55 games in his prior league seasons (56 needed)"
    # declined (Tyler Star): eligible, not improved, never in the race
    assert "Tyler Star" not in {r["player"] for r in base["rows"]}


def test_bust_needs_10_games_names_its_source_and_is_the_shortfall_in_points(res):
    a = res["awards"]["bust"]
    assert a["source"] == ("Yahoo's preseason projection (config/snapshots/PLAYERLIST_made_up.xlsx, "
                           "fetched 2026-10-01)")
    for r in a["rows"]:
        assert r["games"] >= 10 and r["value"] == pytest.approx((r["expected"] - r["fppg"]) * r["games"]) and r["value"] > 0
    assert a["rows"][0]["player"].endswith("Wing")


@pytest.mark.skipif(not (ROOT / "config/snapshots/PLAYERLIST_2026-10-13.xlsx").is_file(),
                    reason="the pinned preseason snapshot is a public exception file")
def test_the_bust_expectation_is_the_pinned_preseason_snapshot():
    cfg = json.loads((ROOT / "config/league_config.json").read_text(encoding="utf-8"))
    assert cfg["durability_prior"]["snapshot"] == "config/snapshots/PLAYERLIST_2026-10-13.xlsx"
    pre = A._preseason(ROOT / cfg["durability_prior"]["snapshot"])
    assert pre["fetched"] == "2026-10-13" and len(pre["by_name"]) > 100


# =============================================================================
# G. the history file
# =============================================================================

def test_one_line_per_award_per_finished_week_and_the_14_day_week_is_one(inp):
    lines = A.pending(inp, [])
    assert [(l["week"], l["award"]) for l in lines] == [(w, k) for w in (1, 2, 3, 4) for k in A.KEYS]
    wk3 = [l for l in lines if l["week"] == 3]
    assert len(wk3) == 6 and {l["through"] for l in wk3} == {"2026-11-01"}       # 14 days, one line each
    for l in lines:
        assert len(l["top"]) <= F.CFG["history_top_n"] and [e["rank"] for e in l["top"]] == list(range(1, len(l["top"]) + 1))
        assert set(l) >= {"season", "week", "through", "award", "final", "replacement_level", "top", "error"}
    # no line for the week in progress
    with pytest.raises(A.AwardsError, match="not finished"):
        A.history_lines(A.compute(inp, F.LAST), F.CFG)


def test_the_backfill_equals_what_the_weekly_run_would_have_written(inp):
    back = A.pending(inp, [])
    for w in (1, 2, 3, 4):
        end = next(v for v in inp["weeks"] if v["week"] == w)["end_date"]
        night = F.inp(end)                     # the nightly after the week's last day: the log stops there
        assert A.lines_for_week(night, w) == [l for l in back if l["week"] == w], w


def test_the_history_is_append_only(tmp_path, inp):
    lines = A.pending(inp, [])
    assert A.read_history(tmp_path) == []
    A.append_history(tmp_path, lines[:12])
    raw = (tmp_path / A.HISTORY_RELPATH).read_text(encoding="utf-8")
    with pytest.raises(A.AwardsError, match="append-only"):
        A.append_history(tmp_path, lines[:6])
    assert (tmp_path / A.HISTORY_RELPATH).read_text(encoding="utf-8") == raw
    A.append_history(tmp_path, A.pending(inp, A.read_history(tmp_path)))       # only weeks 3-4 are new
    got = A.read_history(tmp_path)
    assert got == lines and (tmp_path / A.HISTORY_RELPATH).read_text(encoding="utf-8").startswith(raw)
    assert A.pending(inp, got) == []
    (tmp_path / A.HISTORY_RELPATH).write_text(raw + raw.splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(A.AwardsError, match="repeats"):
        A.read_history(tmp_path)


def test_a_half_written_week_raises(inp):
    lines = A.pending(inp, [])
    with pytest.raises(A.AwardsError, match="week 2 for"):
        A.pending(inp, [l for l in lines if not (l["week"] == 2 and l["award"] == "bust")])


def test_the_manifest_and_gitignore_carry_the_history_file():
    man = json.loads((ROOT / "config/STATE_MANIFEST.json").read_text(encoding="utf-8"))
    assert A.HISTORY_RELPATH.as_posix() in {f["path"] for f in man["files"]}
    assert A.HISTORY_RELPATH.as_posix() in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_the_nightly_appends_pending_lines_only_when_published(tmp_path, inp):
    from modules import nightly
    lines = A.pending(inp, [])

    class Run:
        base = tmp_path
        ctx: dict = {}
    rec = nightly.Run._awards_record(Run(), {"pending": lines, "error": None, "week": 5}, published=False)
    assert rec["history"].startswith("not written: a preview build") and not (tmp_path / A.HISTORY_RELPATH).exists()
    rec = nightly.Run._awards_record(Run(), {"pending": lines, "error": None, "week": 5}, published=True)
    assert rec["history"].startswith("appended weeks [1, 2, 3, 4]") and A.read_history(tmp_path) == lines
    rec = nightly.Run._awards_record(Run(), {"pending": [], "error": None}, published=True)
    assert rec["history"].startswith("nothing to append")
    rec = nightly.Run._awards_record(Run(), {"pending": [], "error": "X: y"}, published=True)
    assert rec["history"] == "not written: the awards failed" and Run.ctx["awards_lines"][0].startswith("AWARDS FAILED")


# =============================================================================
# H. movement, new leader, the chart
# =============================================================================

def test_moves_compare_with_the_week_before_and_a_new_leader_is_said(inp, res):
    lines = A.pending(inp, [])
    prev = copy.deepcopy([l for l in lines if l["week"] == 4])
    mvp4 = next(l for l in prev if l["award"] == "mvp")
    now = [r["key"] for r in res["awards"]["mvp"]["rows"]]
    # last week: the order of today's 2nd, 1st, 5th ... and one of today's top 5 outside it
    order = [now[1], now[0], now[4], now[2]]
    mvp4["top"] = [dict(e, key=k, label=k, rank=i) for i, (e, k) in enumerate(zip(mvp4["top"], order), 1)]
    other = [l for l in lines if l["week"] != 4]
    r = next(a for a in A.races(res, other + prev, F.CFG)["awards"] if a["key"] == "mvp")
    assert [x["move"] for x in r["rows"]] == ["\u25b2 1", "\u25bc 1", "\u25b2 1", "new", "\u25bc 2"]
    assert r["leader"] == f"New leader: {now[0]} (was {now[1]})."
    same = next(a for a in A.races(res, lines, F.CFG)["awards"] if a["key"] == "trade")
    assert same["leader"] == ""


def test_the_chart_points_are_the_lines_and_under_two_weeks_is_the_list_only(inp, res):
    lines = A.pending(inp, [])
    rc = {a["key"]: a for a in A.races(res, lines, F.CFG)["awards"]}
    c = rc["mvp"]["chart"]
    assert c["weeks"] == ["1", "2", "3", "4"]
    for s in c["series"]:
        for w, v in zip(c["weeks"], s["vals"]):
            line = next(l for l in lines if l["week"] == int(w) and l["award"] == "mvp")
            hit = next((e for e in line["top"] if e["key"] == s["key"]), None)
            assert v == (None if hit is None else hit["value"])
    assert [s["key"] for s in c["series"]] == [r["key"] for r in rc["mvp"]["rows"]]
    assert [s["end"] for s in c["series"]] == ["Jordan", "Dana", "Tyler", "Marcus", "Rookie"]   # four "Star"s
    assert c["points"][0]["body"].startswith("Jordan ")
    one = A.races(res, [l for l in lines if l["week"] == 1], F.CFG)["awards"]
    assert all(a["chart"] is None for a in one)


def test_newsletter_facts_name_the_leader_the_gap_and_a_new_leader(inp):
    lines = A.pending(inp, [])
    f = A.newsletter_facts(lines, F.SEASON, 4)
    m = f["mvp"]
    top = next(l for l in lines if l["week"] == 4 and l["award"] == "mvp")["top"]
    assert m["leader"] == top[0]["label"] and m["gap"] == round(top[0]["value"] - top[1]["value"], 2)
    assert set(f) == set(A.KEYS) and all(len(x["moves"]) <= 5 for x in f.values())


# =============================================================================
# I. League > Awards on the hub
# =============================================================================

def _hub():
    from test_hub_v2 import synth_payload
    return synth_payload()


def test_awards_render_every_award_with_its_rows_moves_chart_and_infotip():
    from test_hub_v2 import render
    from modules.hub_v2 import view, page, page_league as PL
    from datetime import datetime
    p = _hub()
    vm = view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]))
    h = PL.awards_html(vm["league"]["awards"], page._mono, page._chart, page.INFO)
    assert re.findall(r'data-award="(\w+)"', h) == list(A.KEYS)
    for k in A.KEYS:
        assert f'aria-controls="awtip-{k}"' in h
    assert re.search(r'<svg class="lh-chart"[^>]*aria-label="MVP race', h)
    assert h.count('data-section="potw"') == 1
    full = render(p)
    assert '<template id="v2-lg-awards">' in full and 'data-lhpart-of="awards"' in full


def test_award_numbers_are_payload_strings_and_lore_never_reaches_the_page():
    from test_hub_v2 import strings, visible_text
    from modules.hub_v2 import view, page, page_league as PL
    from datetime import datetime
    p = _hub()
    aw = p["v2"]["league"]["awards"]
    aw["races"][0]["rows"][0]["shown"] = "wins swung: 1 <!-- lore:phase-x -->"
    vm = view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]))
    h = PL.awards_html(vm["league"]["awards"], page._mono, page._chart, page.INFO)
    assert "lore:" not in h and "phase-x" not in h
    text = visible_text(re.sub(r"<svg.*?</svg>", " ", h, flags=re.S))
    known = " ".join(strings(p))
    for n in re.findall(r"\d+(?:[.,]\d+)*", text):
        assert n in known, n


def test_the_race_chart_has_no_text_but_its_axes_and_end_labels():
    from modules.hub_v2 import view, page, page_league as PL
    from datetime import datetime
    p = _hub()
    vm = view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]))
    h = PL.awards_html(vm["league"]["awards"], page._mono, page._chart, page.INFO)
    for svg in re.findall(r'<svg class="lh-chart".*?</svg>', h, re.S):
        for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg):
            # 4c6: the MVP odds chart's axis reads 0%..100%
            assert re.fullmatch(r"\u2212?[\d,]+(?:\.\d)?|W\d+|[A-Za-z' .\u21c4-]+|\d\d-\d\d|\d+%", t), t
        assert "<rect class=\"lh-c-hit\"" in svg and "legend" not in svg.lower()


def test_awards_taps_aria_tokens_offline_and_nothing_hover_only():
    from test_hub_v2 import tap_violations, visible_text
    from modules.hub_v2 import view, page, page_league as PL, tokens
    from datetime import datetime
    p = _hub()
    vm = view.build(p, mode="publish", now=datetime.fromisoformat(p["generated_at"]))
    h = PL.awards_html(vm["league"]["awards"], page._mono, page._chart, page.INFO)
    assert not tap_violations("<body>" + h + "</body>")
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", h, re.S):
        assert "aria-label" in m.group(1) or visible_text(m.group(2)).strip()
    assert not re.search(r"(?:src|href)=\"https?:", h)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\d+px", PL.CSS)
    for v in set(re.findall(r"var\(--([a-z0-9-]+)\)", PL.CSS)) - {"n"}:
        assert f"--{v}:" in tokens.css(""), v
    assert not re.search(r"mouseover|mouseenter|:hover", PL.JS + PL.CSS)
    for a in re.findall(r'href="(#/players/[^"]+)"', h):
        assert a.startswith("#/players/")


def test_awards_are_published_as_an_encrypted_part_never_in_the_page(tmp_path):
    from test_hub_v2 import _archive, PASS, TERMS, GEN, budget_bytes
    from modules.hub_v2 import publish as v2pub
    from modules import hub_crypto, hub_publish
    e = _archive(tmp_path)
    p = _hub()
    p["v2"]["issue"]["file"] = e["enc"]
    out = tmp_path / "_to_delete" / "4c5" / "publish"
    rep = v2pub.build(tmp_path, p, PASS, salt=b"\x05" * 16, out_dir=out, iterations=1000, terms=TERMS, now=GEN)
    assert "awards" in rep["league_parts"]["bytes"] and rep["served_bytes"] <= budget_bytes()
    assert hub_publish.scan_dir(out, TERMS)["hits"] == {}
    inner = v2pub.open_inner(PASS, json.loads(re.search(r'id="hub-bundle">(.*?)</script>',
                                                        (out / "index.html").read_text(encoding="utf-8"), re.S).group(1)))
    pg = inner["page"]
    assert 'data-award="mvp"' not in pg and 'id="v2-lg-awards"' not in pg and "Wins swung" not in pg
    ref = json.loads(_html.unescape(re.search(r'data-lhpart-of="awards" data-part=\'([^\']+)\'', pg).group(1)))
    blob = (out / ref["file"]).read_bytes()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    part = json.loads(gzip.decompress(AESGCM(hub_crypto.unb64(ref["key"])).decrypt(blob[:12], blob[12:], None)))
    assert 'data-award="mvp"' in part["html"] and "Player of the Week" in part["html"]


def test_the_awards_route_loads_the_part_and_scrolls_to_an_award():
    from modules.hub_v2 import page_league as PL
    assert "data-lhpart-of" in PL.JS and "data-award=" in PL.JS
    assert "lgPart(ap)" in PL.JS


def test_an_awards_failure_is_said_on_the_page():
    import hub_v2_league_fixture as LF
    from modules.hub_v2 import league as L
    i = LF.inputs(_hub())
    i["awards_rec"] = {"error": "AwardsInputError: no log", "races": None}
    aw = L.build(i)[0]["awards"]
    assert aw["races"] == [] and aw["races_error"] == "The awards could not be computed: AwardsInputError: no log"


def test_the_live_hub_never_reads_the_awards():
    import inspect
    from modules import hub_page
    src = inspect.getsource(hub_page)
    assert "awards" not in src and "hub_v2" not in src


# =============================================================================
# J. 4c4's follow-ups
# =============================================================================

def test_then_falls_back_to_the_week_2_point_labelled():
    from modules import draft_ovr as D
    assert D.then_with_fallback((None, D.THEN_NO_PRIOR), (77, None)) == ((77, None), "week2")
    assert D.then_with_fallback((None, D.THEN_NO_PRIOR), (None, "not on a roster that day"))[0][1].startswith(
        D.THEN_NO_PRIOR + "; none at week 2 either")
    assert D.then_with_fallback((81, None), (77, None)) == ((81, None), "open")
    assert D.then_with_fallback((None, D.NOT_ROSTERED), (77, None)) == ((None, D.NOT_ROSTERED), "open")
    import hub_v2_league_fixture as LF
    from modules.hub_v2 import league as L
    i = LF.inputs(_hub())
    i["draft_ovr"] = copy.deepcopy(i["draft_ovr"])
    i["draft_ovr"]["seasons"]["2025-26"]["picks"][1].update(then=70, then_reason=None, then_point="week2")
    rows = next(s for s in L.build(i)[1]["draft"]["seasons"] if s["season"] == "2025-26")["rows"]
    assert rows[1]["then"] == "70 (wk 2)"
    i["live_then"]["players"]["Marcus Big"] = (64, None, "week2")
    cur = next(s for s in L.build(i)[1]["draft"]["seasons"] if s["season"] == "2026-27")["rows"]
    assert next(r for r in cur if r["player"] == "Marcus Big")["then"] == "64 (wk 2)"


@pytest.mark.skipif(not (ROOT / "data/historical/DRAFT_OVR.json").is_file(), reason="the cache is public history")
def test_the_draft_cache_carries_the_week_2_fallback():
    from modules import draft_ovr as D
    c = D.load(ROOT)
    assert c["schema"] == D.SCHEMA == 4                          # 4a4: the skill OVR; H56: no punted order
    picks = [p for s in c["seasons"].values() for p in s["picks"]]
    assert all(p["then_point"] in ("open", "week2") for p in picks)
    assert all(p["then"] is not None for p in picks if p["then_point"] == "week2")
    assert not any(p["then_reason"] == D.THEN_NO_PRIOR for p in picks)        # each is filled or says week 2 too
    assert all(s["week2"] for s in c["seasons"].values())


def test_the_cup_is_its_own_head_to_head_phase():
    import hub_v2_league_fixture as LF
    from modules.hub_v2 import league as L
    i = LF.inputs(_hub())
    i["weekly_scores"] = copy.deepcopy(i["weekly_scores"])
    i["weeks"] = copy.deepcopy(i["weeks"]) + [{"week": 22, "start_date": "2027-03-29", "end_date": "2027-04-04",
                                                "matchups": [{"manager_a": "Marcus", "manager_b": "Tyler"}]}]
    for m, v in (("Marcus", 1700.0), ("Tyler", 1600.0)):
        i["weekly_scores"][m].append({"week": 22, "score": v})
    h = L.h2h(i, L.week_results(i))
    assert [k for k, _l in h["phases"]] == ["reg", "post", "cup"]
    row = next(r for r in h["grid"]["cup"] if r["m"] == "Marcus")
    cell = row["cells"][i["managers"].index("Tyler")]
    assert cell["t"] == "1-0"
    before = L.h2h(LF.inputs(_hub()), L.week_results(LF.inputs(_hub())))
    for ph in ("reg", "post"):                         # the Cup week went into neither
        assert h["grid"][ph] == before["grid"][ph]
    assert "Cup 1-0" in h["pairs"]["Marcus|Tyler"]["total"] and "Cup 0-0" in before["pairs"]["Marcus|Tyler"]["total"]


def test_standings_count_a_banked_week_as_home_does_on_a_monday():
    import hub_v2_league_fixture as LF
    from modules.hub_v2 import league as L
    pf_before = {r["m"]: r["pf"] for r in L.build(LF.inputs(_hub()))[0]["standings"]["rows"]}
    i = LF.inputs(_hub())
    # Monday 12:01 AM: week 9 banked whole from the logs; the weekly build has not recorded it
    banked = {9: {"Marcus": 1500.0, "Dana": 1400.0, "Tyler": 1300.0, "Jordan": 1350.0}}
    sc = copy.deepcopy(i["weekly_scores"])
    for m, v in banked[9].items():
        sc[m].append({"week": 9, "score": v})
    home = LF.sync_power(dict(copy.deepcopy(i), weekly_scores=sc))["power"]      # records_after_banked
    i["banked"], i["power"] = banked, home
    st = L.build(i)[0]["standings"]
    assert {r["m"]: r["record"] for r in st["rows"]} == {r["manager"]: r["record"] for r in home["rows"]}
    assert {r["m"]: r["pf"] for r in st["rows"]} == pf_before                    # PF: recorded weeks, as Home's
    assert "Week 9 is counted from the logs" in st["note"]
    i["power"] = LF.inputs(_hub())["power"]            # Home a week behind: they must never disagree
    with pytest.raises(L.LeagueError, match="Standings and Home disagree"):
        L.build(i)
    # once the weekly build records week 9, the banked copy is ignored: no double count
    i2 = LF.inputs(_hub())
    i2["weekly_scores"], i2["banked"], i2["power"] = sc, banked, home
    assert {r["m"]: r["record"] for r in L.build(i2)[0]["standings"]["rows"]} == \
        {r["manager"]: r["record"] for r in home["rows"]}


def test_banked_results_use_the_runs_own_rule():
    from modules import title_odds_run as tor
    weeks = [{"week": 5, "end_date": "2026-11-22"}, {"week": 6, "end_date": "2026-11-29"}]
    latest = {"in_progress": {"5": {"as_of": "2026-11-23", "banked": {"A": 1.0}},
                              "6": {"as_of": "2026-11-28", "banked": {"A": 2.0}}}}
    assert tor.banked_results(latest, weeks) == {5: {"A": 1.0}}


@pytest.mark.slow
@league_state.needs_state("data/historical/HISTORICAL_PLAYERLOG.json", "config/POTW_HISTORY.json",
                          why="Player of the Week's recorded points against the league log")
def test_potw_points_from_the_log_equal_every_recorded_week():
    """The backfill's measure (his started games that week) reproduces every
    week whose points were recorded (2025-26 weeks 14-23)."""
    from modules.hub_v2 import league as L
    inputs = kh.Inputs.load(ROOT)
    potw = json.loads((ROOT / "config/POTW_HISTORY.json").read_text(encoding="utf-8"))["seasons"]
    rec = {s: [e for e in es if e.get("total_fp") is not None] for s, es in potw.items()}
    blank = {s: [{k: v for k, v in e.items() if k not in ("total_fp", "games", "fppg")} for e in es]
             for s, es in rec.items()}
    got = L.potw_from_log(blank, inputs.log)
    n = 0
    for s, es in rec.items():
        for e in es:
            if (s, int(e["week"])) in got:
                g = got[(s, int(e["week"]))]
                assert (g["total_fp"], g["games"]) == (round(e["total_fp"], 2), e["games"]), (s, e["week"])
                n += 1
    assert n >= 10
    fill = L.potw_from_log(potw, inputs.log)
    assert all(("2025-26", w) in fill for w in range(1, 14))


# =============================================================================
# K. real state
# =============================================================================

@pytest.mark.slow
def test_real_awards_backfill_preview_and_publish(tmp_path):
    """Today's state, unstubbed: every award computed; the backfill run into a
    temp folder (never the repo's state file); the v2 preview's Awards; publish
    mode to a temp folder (a throwaway passphrase, a fresh salt) within the
    budget, the scan clean."""
    import os
    from datetime import datetime
    league_state.skip_if_actuals_behind()
    from modules import hub_state, hub_publish, team_pictures as tp
    from modules.hub_v2 import data as v2data, view, page, publish as v2pub
    from test_hub_v2 import budget_bytes
    live = kh.live_inputs(ROOT, kh.Inputs.load(ROOT))
    inp = A.gather(ROOT, live=live)
    res = A.compute(inp, inp["days"][-1])
    for k in A.KEYS:
        a = res["awards"][k]
        assert a["rows"] or a["error"] or a["excluded"] or k == "trade", k
    pend = A.pending(inp, A.read_history(ROOT))
    A.append_history(tmp_path, A.pending(inp, []))
    assert len(A.read_history(tmp_path)) == 6 * len(A.finished_weeks(inp))
    assert not (ROOT / A.HISTORY_RELPATH).exists() or pend == []
    po, ao = {}, {}
    p = hub_state.build(ROOT, allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po, awards_out=ao)
    assert p["v2_error"] is None and ao["error"] is None, (p["v2_error"], ao["error"])
    v2data.attach_players(p, po)
    assert [a["key"] for a in p["v2"]["league"]["awards"]["races"]] == list(A.KEYS)
    h = page.render(view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]),
                               pictures=tp.data_uris(ROOT, p["v2"]["team_order"])[0]))
    assert '<template id="v2-lg-awards">' in h and 'data-award="mvp"' in h
    terms = hub_publish.scan_terms(ROOT)
    out = tmp_path / "_to_delete" / "4c5" / "publish"
    rep = v2pub.build(ROOT, p, "throwaway " + os.urandom(8).hex(), salt=os.urandom(16), out_dir=out,
                      iterations=1000, terms=terms)
    assert rep["served_bytes"] <= budget_bytes() and rep["league_parts"]["largest"] <= 60_000
    assert "awards" in rep["league_parts"]["bytes"]
    assert hub_publish.scan_dir(out, terms)["hits"] == {}
