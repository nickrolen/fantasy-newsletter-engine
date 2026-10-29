"""A tied regular-season week is a tie (HANDOFF_TIE_RULE_2026-10-20).

Nick, 10-20: a T for both managers, nobody wins it (Yahoo). A T counts half a
win: (W + 0.5*T) / (W + L + T). A season series can end 2-2-1, and then
head-to-head cannot separate the two and total points does.
"""
import json
from fractions import Fraction
from pathlib import Path

import pytest

import modules.data_loader as dl
from modules import angles as A
from modules import season_outcomes as so
from modules import simulator_title_odds as sto
from modules import standing_threads as st
from modules.data_loader import (FantasyData, MANAGERS, Record, UnspecifiedRule,
                                 results_from, standings_order, week_outcome)

ROOT = Path(__file__).resolve().parent.parent


def _season(results):
    """results: [(week, a, b, score_a, score_b)] -> (scores_by_week, matchups_by_week)."""
    scores, pairs = {}, {}
    for w, a, b, sa, sb in results:
        scores.setdefault(w, {}).update({a: sa, b: sb})
        pairs.setdefault(w, []).append({"manager_a": a, "manager_b": b})
    return scores, pairs


# 1 -- a tied week is a T for both, a win for neither
def test_a_tied_week_is_a_t_for_both_and_a_win_for_neither():
    scores, pairs = _season([(1, "Nick", "Hayden", 1500.0, 1500.0),
                             (1, "Benton", "Garrett", 1400.0, 1300.0)])
    recs, h2h, _pts = results_from(scores, pairs, 15)
    assert recs["Nick"] == recs["Hayden"] == Record(0, 0, 1)
    assert recs["Benton"] == Record(1, 0, 0) and recs["Garrett"] == Record(0, 1, 0)
    assert h2h["Nick"]["Hayden"] == Record(0, 0, 1)
    assert str(recs["Nick"]) == "0-0-1"


def test_get_manager_record_carries_the_t():
    data = FantasyData(
        schedule={"weeks": [{"week": 1, "matchups": [{"manager_a": "Nick", "manager_b": "Hayden"},
                                                      {"manager_a": "Benton", "manager_b": "Garrett"}]}]},
        records={"weekly_scores": {"Nick": [{"week": 1, "score": 1500.0}],
                                   "Hayden": [{"week": 1, "score": 1500.0}],
                                   "Benton": [{"week": 1, "score": 1400.0}],
                                   "Garrett": [{"week": 1, "score": 1300.0}]}})
    assert data.get_manager_record("Nick") == Record(0, 0, 1)
    assert str(data.get_manager_record("Hayden")) == "0-0-1"


def test_both_scores_zero_is_an_unplayed_week_not_a_tie():
    scores, pairs = _season([(1, "Nick", "Hayden", 0.0, 0.0)])
    recs, _h, _p = results_from(scores, pairs, 15)
    assert "Nick" not in recs


def test_a_record_cannot_be_read_as_a_wins_losses_pair():
    """The shape breaks at an unported call site instead of dropping the T."""
    with pytest.raises(TypeError):
        w, l = Record(7, 7, 1)          # noqa: F841
    with pytest.raises(TypeError):
        Record(7, 7, 1)[0]


def test_a_record_string_with_a_t_parses():
    assert dl.parse_record_string("(7-7-1)") == Record(7, 7, 1)   # used to read as 0-0


# 2 -- Yahoo's winning percentage
def test_seven_seven_one_ranks_between_eight_seven_and_seven_eight():
    assert Record(7, 7, 1).win_pct == Fraction(1, 2)
    recs = {"Nick": Record(8, 7), "Hayden": Record(7, 7, 1), "Benton": Record(7, 8), "Garrett": Record(2, 13)}
    order = standings_order(recs, {}, {m: 0.0 for m in recs})
    assert order == ["Nick", "Hayden", "Benton", "Garrett"]


# 3 -- W + L + T = games played, every manager, every season
def test_w_l_t_adds_up_to_games_played_in_every_archived_season():
    rows = json.loads((ROOT / "data" / "historical" / "all_matchups.json").read_text(encoding="utf-8"))
    by = {}
    for r in rows:
        by.setdefault(r["season"], []).append(r)
    for season, rs in by.items():
        played = {}
        for r in rs:
            if dl.is_regular_season_week(season, r["week"]):
                for m in (r["manager_a"], r["manager_b"]):
                    played[m] = played.get(m, 0) + 1
        for row in so.build_standings(season, rs):
            assert row["reg_wins"] + row["reg_losses"] + row["reg_ties"] == played[row["manager"]], (season, row)


def test_w_l_t_adds_up_with_a_tie_in_the_season():
    """The invariant that failed before: a 7-7-1 manager read as 7-7 over 15."""
    rows = []
    for w in range(1, 16):
        tie = w == 8
        rows.append({"season": "2026-27", "week": w, "manager_a": "Nick", "manager_b": "Hayden",
                     "score_a": 1000.0, "score_b": 1000.0 if tie else (900.0 if w % 2 else 1100.0),
                     "winner": None if tie else ("Nick" if w % 2 else "Hayden"),
                     "loser": None if tie else ("Hayden" if w % 2 else "Nick")})
        rows.append({"season": "2026-27", "week": w, "manager_a": "Benton", "manager_b": "Garrett",
                     "score_a": 1200.0, "score_b": 800.0, "winner": "Benton", "loser": "Garrett"})
    out = {r["manager"]: r for r in so.build_standings("2026-27", rows)}
    for m in MANAGERS:
        r = out[m]
        assert r["reg_wins"] + r["reg_losses"] + r["reg_ties"] == 15, (m, r)
    assert out["Nick"]["reg_ties"] == out["Hayden"]["reg_ties"] == 1


# 4 -- a 2-2-1 series falls through to total points
def test_a_two_two_one_series_falls_through_to_total_points():
    res = [(1, "Nick", "Hayden", 10, 5), (2, "Nick", "Hayden", 10, 5),
           (3, "Nick", "Hayden", 5, 10), (4, "Nick", "Hayden", 5, 10),
           (5, "Nick", "Hayden", 7, 7)]
    scores, pairs = _season(res)
    recs, h2h, pts = results_from(scores, pairs, 15)
    assert recs["Nick"] == recs["Hayden"] == Record(2, 2, 1)
    assert h2h["Nick"]["Hayden"] == Record(2, 2, 1)
    notes = []
    pts = {"Nick": 100.0, "Hayden": 120.0}
    assert standings_order(recs, h2h, pts, ["Nick", "Hayden"], notes=notes) == ["Hayden", "Nick"]
    assert "total points" in notes[0]


def test_a_three_one_one_series_is_settled_by_head_to_head():
    h2h = {"Nick": {"Hayden": Record(3, 1, 1)}, "Hayden": {"Nick": Record(1, 3, 1)}}
    recs = {"Nick": Record(5, 5, 1), "Hayden": Record(5, 5, 1)}
    assert standings_order(recs, h2h, {"Nick": 1.0, "Hayden": 999.0}, ["Nick", "Hayden"]) == ["Nick", "Hayden"]


def test_level_on_everything_raises():
    recs = {"Nick": Record(1, 0), "Hayden": Record(1, 0)}
    with pytest.raises(UnspecifiedRule):
        standings_order(recs, {}, {"Nick": 5.0, "Hayden": 5.0}, ["Nick", "Hayden"])


# 5 -- draft order is the exact reverse of the standings, ties included
def test_draft_order_is_the_reverse_of_the_one_standings_rule():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bdo", ROOT / "scripts" / "build_draft_order.py")
    bdo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bdo)
    weeks, scores = [], {m: [] for m in MANAGERS}
    plan = [("Nick", "Hayden", 10, 10), ("Benton", "Garrett", 9, 3),     # a T
            ("Nick", "Benton", 4, 8), ("Hayden", "Garrett", 7, 6),
            ("Nick", "Garrett", 7, 2), ("Hayden", "Benton", 1, 9)]
    for i in range(0, len(plan), 2):
        w = i // 2 + 1
        weeks.append({"week": w, "matchups": [{"manager_a": p[0], "manager_b": p[1]} for p in plan[i:i + 2]]})
        for a, b, sa, sb in plan[i:i + 2]:
            scores[a].append({"week": w, "score": sa}); scores[b].append({"week": w, "score": sb})
    recs, pts, h2h, _ = bdo.regular_season_results({"weekly_scores": scores},
                                                   {"regular_season_weeks": 3, "weeks": weeks})
    order, _notes = bdo.rank_managers(recs, pts, h2h)
    assert order == standings_order(recs, h2h, pts)
    assert recs["Nick"] == Record(1, 1, 1) and recs["Hayden"] == Record(1, 1, 1)
    sm = [{"season": "x", "week": w["week"], "manager_a": mu["manager_a"], "manager_b": mu["manager_b"],
           "score_a": next(s["score"] for s in scores[mu["manager_a"]] if s["week"] == w["week"]),
           "score_b": next(s["score"] for s in scores[mu["manager_b"]] if s["week"] == w["week"])}
          for w in weeks for mu in w["matchups"]]
    assert A.final_order(sm, 3) == order                               # angles agrees
    drafted = st.draft_order(sm, 3, "2026-27", 3, None)[0]
    assert ", ".join(reversed(order)) in drafted                       # and draft reverses it


def test_no_second_copy_of_the_ranking_rule():
    """The standings sort lives in data_loader.standings_order. Every surface
    that ranks the regular season calls it."""
    import inspect
    from modules import simulator_playoff_odds as spo
    srcs = {"playoff seeds": inspect.getsource(spo.rank_managers_by_standings),
            "title odds": inspect.getsource(sto.apply_tiebreakers),
            "angles": inspect.getsource(A.final_order) + inspect.getsource(A._seeds),
            "season_outcomes": inspect.getsource(so.build_standings),
            "draft order": (ROOT / "scripts" / "build_draft_order.py").read_text(encoding="utf-8")}
    for name, src in srcs.items():
        assert "standings_order(" in src, name


# 6 -- title odds: a simulated tied week is a T, deterministically
def test_a_simulated_tied_week_is_a_t_with_no_coin():
    res = {"Nick": 1500.0, "Hayden": 1500.0}
    m1 = sto.simulate_matchup(res, {"manager_a": "Nick", "manager_b": "Hayden"}, 1)
    m2 = sto.simulate_matchup(res, {"manager_a": "Nick", "manager_b": "Hayden"}, 1)
    assert m1.winner is None and m2.winner is None


def test_a_simulated_season_records_the_t():
    flat = {2: {m: 1000.0 for m in MANAGERS}}       # one simulation's week 2: all level
    weeks = [{"week": 2, "matchups": [{"manager_a": "Nick", "manager_b": "Hayden"},
                                      {"manager_a": "Benton", "manager_b": "Garrett"}]}]
    start = {"Nick": Record(1, 0), "Hayden": Record(0, 1), "Benton": Record(1, 0), "Garrett": Record(0, 1)}
    pts = {"Nick": 1300.0, "Hayden": 1100.0, "Benton": 1250.0, "Garrett": 1000.0}
    runs = [sto.simulate_full_season(start, {}, pts, weeks, flat) for _ in range(2)]
    for r in runs:
        assert r.final_records["Nick"] == Record(1, 0, 1)
        assert r.final_records["Hayden"] == Record(0, 1, 1)
        assert r.h2h_records["Nick"]["Hayden"] == Record(0, 0, 1)
    assert runs[0].finish_order == runs[1].finish_order == ["Nick", "Benton", "Hayden", "Garrett"]


def test_the_title_odds_module_has_no_coin_flip():
    import inspect
    assert "random.choice" not in inspect.getsource(sto.simulate_matchup)


# 7 -- no raise on a legal outcome, and the rule comes from the config
def test_nothing_raises_on_a_tied_regular_season_week():
    sm = [{"season": "2026-27", "week": w, "manager_a": a, "manager_b": b, "score_a": sa, "score_b": sb}
          for w, a, b, sa, sb in [(1, "Nick", "Hayden", 1500.0, 1500.0), (1, "Benton", "Garrett", 1400.0, 1300.0),
                                  (2, "Nick", "Benton", 1200.0, 1100.0), (2, "Hayden", "Garrett", 1300.0, 1000.0)]]
    assert not hasattr(A, "check_no_ties")
    # the rest of the regular season's pairings: the exact clinch check reads them
    rest = [{"week": w, "manager_a": a, "manager_b": b} for w in range(3, 16)
            for a, b in ((("Nick", "Garrett"), ("Hayden", "Benton")) if w % 2 else
                         (("Nick", "Hayden"), ("Benton", "Garrett")))]
    A.decided_status(sm, 2, 15, pairings=rest)
    # Nick and Hayden both 1-0-1, series 0-0-1: total points (Hayden 2800) decide
    assert A.final_order(sm, 2)[:2] == ["Hayden", "Nick"]
    lines = st.regular_season(sm, 2, 15, st.rules_from_config(), pairings=rest)
    assert "Nick 1-0-1" in lines[0] and "Hayden 1-0-1" in lines[0]


def test_the_rule_is_read_from_the_config(monkeypatch):
    rules = dict(dl._LEAGUE_CONFIG["tiebreaker_rules"])
    monkeypatch.setitem(dl._LEAGUE_CONFIG, "tiebreaker_rules", {**rules, "tie_win_value": 0.25})
    assert Record(0, 0, 4).standing == 1
    no_rule = {k: v for k, v in rules.items() if k != "regular_season_week"}
    monkeypatch.setitem(dl._LEAGUE_CONFIG, "tiebreaker_rules", no_rule)
    with pytest.raises(UnspecifiedRule):
        week_outcome(10.0, 10.0)
    assert week_outcome(11.0, 10.0) == "a"                             # no tie, no rule needed


# the angles: a half game is a half game
def test_clinch_and_magic_number_handle_a_half_game():
    """Two managers, 3 weeks, Nick 1-0-1 (1.5) vs Hayden 0-1-1 (0.5), 1 left:
    Hayden's best is 1.5 = Nick's current -> not clinched yet (a tie is
    undecided); Nick needs 1 more result."""
    sm = [{"season": "x", "week": 1, "manager_a": "Nick", "manager_b": "Hayden", "score_a": 9.0, "score_b": 9.0},
          {"season": "x", "week": 2, "manager_a": "Nick", "manager_b": "Hayden", "score_a": 9.0, "score_b": 8.0},
          {"season": "x", "week": 3, "manager_a": "Nick", "manager_b": "Hayden", "score_a": 1.0, "score_b": 2.0}]
    assert ("clinched_title", "Nick") not in A.decided_status(sm, 2, 3)
    assert A.magic_number(sm, 2, 3) == ("Nick", 1)


def test_the_standings_consequence_term_reads_a_half_game_gap():
    """Not rounded: a half-game gap is between level and a full game."""
    full, half, level = (A._p_ahead(g, 1.0) for g in (1.0, 0.5, 0.0))
    assert level < half < full


# the persisted record: careers and series keep the T
def test_careers_and_series_keep_the_t():
    from modules import records_tracker as rt
    from modules.weekly_stats import MatchupStats
    m = MatchupStats(week=1, manager_a="Nick", manager_b="Hayden", score_a=10.0, score_b=10.0,
                     winner=None, margin=0.0, stats_a=None, stats_b=None)
    records = {}
    rt.update_h2h_records(records, [m], week=1, season="2026-27")
    rt.update_all_time_records(records, [m], {"Nick": 10.0, "Hayden": 10.0}, week=1, season="2026-27")
    assert records["h2h_season_ties"] == {"Hayden_vs_Nick": 1}
    assert records["all_time"]["h2h_ties"] == {"Hayden_vs_Nick": 1}
    car = records["all_time"]["manager_careers"]["Nick"]
    assert car["total_ties"] == 1 and car["games_played"] == 1 and car["win_pct"] == 50.0


def test_a_t_ends_a_streak():
    sm = [{"season": "x", "week": w, "manager_a": "Nick", "manager_b": "Hayden",
           "score_a": sa, "score_b": sb} for w, sa, sb in [(1, 9, 1), (2, 9, 1), (3, 5, 5)]]
    # each toy season's regular season is the weeks it has: History judges
    # what was decided over the games actually left (decided_status)
    hist = A.History.build(sm + [{"season": "y", "week": 1, "manager_a": "Nick", "manager_b": "Hayden",
                                  "score_a": 3.0, "score_b": 4.0}], lambda s: 3 if s == "x" else 1)
    angles = A.matchup_angles(sm, 3, hist, 15)
    assert not any(a.family == "streak" for a in angles)
    assert any("tied at 5.00" in a.text for a in angles)


# ---------------------------------------------------------------------------
# The standings storyline reads standing value, not field [0] of the record
# string (found in review of the tie-rule commit, fbc55ac)
# ---------------------------------------------------------------------------

def _standings_storyline(lead_record, second_record):
    from modules.storylines import compute_storylines
    data = {"metadata": {"week": 10},
            "current_standings": [{"manager": "Nick", "record": lead_record},
                                  {"manager": "Hayden", "record": second_record}]}
    out = [s for s in compute_storylines(data, None, "2026-27", list(MANAGERS))
           if s.kind == "standings_lead"]
    return out[0] if out else None


def test_a_half_game_lead_is_counted_and_printed_as_a_half():
    """8-6-1 over 7-8 is 1.5 games, not 1. Reading wins alone said 1."""
    s = _standings_storyline("8-6-1", "7-8")
    assert s is None or s.magnitude["games_back"] == 1.5     # below the threshold
    s = _standings_storyline("12-2-1", "7-8")
    assert s is not None and s.magnitude["games_back"] == 5.5
    assert "leads by 5.5 games" in s.text


def test_a_tie_can_be_the_whole_lead():
    """7-7-1 over 7-8 is half a game ahead; wins alone said level."""
    from modules.storylines import compute_storylines
    data = {"metadata": {"week": 10},
            "current_standings": [{"manager": "Nick", "record": "7-7-1"},
                                  {"manager": "Hayden", "record": "7-8"}]}
    lead = (dl.parse_record_string("7-7-1").standing
            - dl.parse_record_string("7-8").standing)
    assert lead == Fraction(1, 2)
    assert not [s for s in compute_storylines(data, None, "2026-27", list(MANAGERS))
                if s.kind == "standings_lead"]          # half a game is not a lead


def test_a_tie_free_lead_still_prints_a_whole_number():
    """The archived strings are pinned byte-for-byte; nothing changes without a T."""
    s = _standings_storyline("12-2", "8-6")
    assert s is not None and "leads by 4 games" in s.text
    assert s.magnitude["games_back"] == 4


def test_the_games_formatter_is_shared_with_the_betting_preview():
    """Two games-back computations drifted once; they render through one formatter."""
    from modules import simulator_betting as sb
    for x in (0, 1, 4, Fraction(3, 2), Fraction(11, 2), 2.0):
        assert sb._games(x) == dl.format_games_count(x)
    assert dl.format_games_count(4) == "4"
    assert dl.format_games_count(Fraction(3, 2)) == "1.5"


def test_the_dryrun_rewind_refuses_a_record_with_a_tie():
    """It used to take the first two fields and drop the T silently."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_bdp", ROOT / "scripts" / "build_dryrun_packet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._wl("(8-3)") == (8, 3)
    with pytest.raises(ValueError, match="carries a tie"):
        mod._wl("(7-7-1)")
