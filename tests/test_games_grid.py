"""C5: the week-ahead games grid and the schedule_strength pieces under it.

The grid puts empty lineup slots in front of a manager on Monday. The
failure that matters is a hole that is not real -- a rostered player skipped
because PLAYERLIST does not carry him, or a rostered player listed as a free
agent because Yahoo respelled him -- so most of these pin exactly that.
"""
from datetime import date

import pytest

from modules import schedule_strength as ss
from modules import games_grid as gg

MON, TUE = date(2026, 10, 26), date(2026, 10, 27)


def info(team, pos, proj):
    return {"nba_team": team, "positions": set(pos.split(",")), "proj_fppg": proj}


# ---------------------------------------------------------------------------
# Slot arithmetic
# ---------------------------------------------------------------------------

def test_fill_daily_lineup_keeps_its_two_value_contract():
    started, benched = ss.fill_daily_lineup([("A", {"PG"}, 30.0)])
    assert started == ["A"] and benched == []


def test_open_slots_are_listed_per_seat_in_slot_order():
    _s, _b, remaining = ss.fill_daily_lineup_detail([("A", {"C"}, 30.0)])
    assert ss.open_slot_list(remaining) == ["PG", "SG", "SF", "PF", "C", "G", "F", "Util", "Util"]


def test_fillable_is_an_exact_matching_not_a_greedy_pass():
    """Open: one C seat, one PF seat. A plays C or PF, B only C.
    Greedy puts A at C and strands B; both seats are fillable."""
    remaining = {name: 0 for name, _e, _c in ss.SLOT_DEFINITIONS}
    remaining.update({"C": 1, "PF": 1})
    assert ss.count_fillable(remaining, [{"C", "PF"}, {"C"}]) == 2
    assert ss.count_fillable(remaining, [{"PG"}]) == 0


# ---------------------------------------------------------------------------
# Holes that are not real
# ---------------------------------------------------------------------------

def test_a_player_missing_from_playerlist_is_named_not_silently_dropped():
    pinfo = ss.PlayerIndex({"Star": info("LAL", "PG", 40.0)})
    r = ss.simulate_daily_lineups("Nick", ["Star", "Deep Streamer"], pinfo,
                                  {MON: {"LAL", "BOS"}}, {})
    assert r["unmatched_players"] == ["Deep Streamer"]


def test_lineups_fill_in_a_rostered_player_playerlist_lacks():
    import pandas as pd
    pinfo = ss.PlayerIndex({"Star": info("LAL", "PG", 40.0)})
    lineups = pd.DataFrame([
        {"player_name": "Deep Streamer", "nba_team": "MEM", "positions": "SF,PF", "date": "2026-10-20"},
        {"player_name": "Deep Streamer", "nba_team": "BOS", "positions": "SF,PF", "date": "2026-10-24"},
    ])
    filled = ss.augment_player_info_from_lineups(
        pinfo, {"Nick": ["Star", "Deep Streamer"]}, lineups)
    assert filled == ["Deep Streamer"]
    assert pinfo["Deep Streamer"]["nba_team"] == "BOS"      # most recent team
    assert pinfo["Deep Streamer"]["proj_fppg"] == 0.0       # sorts last


def test_a_respelled_rostered_player_is_not_a_free_agent():
    """Yahoo wrote 'S. Gilgeous-Alexander' on 2026-10-05; rosters kept 'Shai'."""
    pinfo = ss.PlayerIndex({
        "S. Gilgeous-Alexander": info("OKC", "PG,SG", 55.0),
        "Nikola Jokic": info("DEN", "C", 60.0),
        "Josh Hart": info("NYK", "SF", 28.0),
    })
    pool = ss.build_free_agent_pool(
        pinfo, {"Nick": ["Shai Gilgeous-Alexander"], "Hayden": ["Nikola Jokic"]})
    assert [p[0] for p in pool] == ["Josh Hart"]


def test_an_injured_free_agent_fills_nothing():
    pinfo = ss.PlayerIndex({"A": info("LAL", "PG", 40.0), "FA": info("BOS", "C", 30.0)})
    weeks = [{"week": 2, "start_date": "2026-10-26", "end_date": "2026-10-26"}]
    nba = {"games": [{"date": "2026-10-26", "home": "LAL", "away": "BOS"}]}
    overrides = {"players": [{"player_name": "FA", "out_weeks": [2]}]}
    pool = ss.build_free_agent_pool(pinfo, {"Nick": ["A"]})
    up = ss._build_for_week_with_lineups(2, weeks, nba, {"Nick": ["A"]}, pinfo,
                                         overrides, free_agents=pool)
    day = up["managers"]["Nick"]["daily_detail"][0]
    assert day["free_agents_playing"] == 0 and day["fillable"] == 0


def test_the_free_agent_pool_never_changes_startable_games():
    """The grid is additive: betting-line inputs must not move."""
    pinfo = ss.PlayerIndex({"A": info("LAL", "PG", 40.0), "B": info("BOS", "C", 30.0),
                            "FA": info("BOS", "SF", 20.0)})
    sched = {MON: {"LAL", "BOS"}, TUE: {"BOS", "MIA"}}
    plain = ss.simulate_daily_lineups("Nick", ["A", "B"], pinfo, sched, {})
    pool = ss.build_free_agent_pool(pinfo, {"Nick": ["A", "B"]})
    rich = ss.simulate_daily_lineups("Nick", ["A", "B"], pinfo, sched, {}, free_agents=pool)
    for k in ("startable_games", "bench_games", "healthy_games", "total_games"):
        assert plain[k] == rich[k]


def _open(**caps):
    rem = {name: 0 for name, _e, _c in ss.SLOT_DEFINITIONS}
    rem.update(caps)
    return rem


def test_streamers_rank_by_points_added_not_games_then_projection():
    """Two games at 20 (40 pts) loses to one game at 50 (50 pts). The old
    ranking -- most holes, ties by projection -- put the 20 first."""
    full = {name: cap for name, _e, cap in ss.SLOT_DEFINITIONS}
    days = [(MON, {"BOS", "MIA"}, dict(full)), (TUE, {"BOS"}, dict(full))]
    pool = [("Two Games", "BOS", {"C"}, 20.0), ("One Game", "MIA", {"C"}, 50.0)]
    board = ss.build_streamer_board({"Nick": days}, pool)
    assert [r["player"] for r in board] == ["One Game", "Two Games"]
    assert board[1]["managers"]["Nick"] == {
        "holes_filled": 2, "points_added": 40.0, "days": ["2026-10-26", "2026-10-27"]}


def test_board_scores_every_fa_against_every_roster():
    """A full night for one manager is a hole for another; the board shows it."""
    days_nick = [(MON, {"BOS"}, _open(Util=1)), (TUE, {"BOS"}, _open(Util=1))]
    days_hay = [(MON, {"BOS"}, _open()), (TUE, {"BOS"}, _open(Util=1))]  # Mon full
    board = ss.build_streamer_board({"Nick": days_nick, "Hayden": days_hay},
                                    [("FA", "BOS", {"SF"}, 30.0)])
    assert board[0]["managers"]["Nick"]["holes_filled"] == 2
    assert board[0]["managers"]["Hayden"]["holes_filled"] == 1


def test_positional_fit_counts_when_util_is_closed():
    days = [(MON, {"BOS"}, _open(C=1))]
    board = ss.build_streamer_board({"Nick": days}, [("G", "BOS", {"PG"}, 30.0)])
    assert board == []


def test_private_fill_state_never_reaches_the_report():
    pinfo = ss.PlayerIndex({"A": info("LAL", "PG", 40.0), "FA": info("BOS", "C", 30.0)})
    weeks = [{"week": 2, "start_date": "2026-10-26", "end_date": "2026-10-26"}]
    nba = {"games": [{"date": "2026-10-26", "home": "LAL", "away": "BOS"}]}
    pool = ss.build_free_agent_pool(pinfo, {"Nick": ["A"]})
    up = ss._build_for_week_with_lineups(2, weeks, nba, {"Nick": ["A"]}, pinfo, {},
                                         free_agents=pool)
    import json
    json.dumps(up)  # dates and sets would raise
    assert "_remaining_by_day" not in up["managers"]["Nick"]
    assert up["streamer_board"][0]["player"] == "FA"


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------

def _report():
    return {"schedule_strength": {"upcoming_week": {
        "week": 2, "start_date": "2026-10-26", "end_date": "2026-10-28",
        "nba_games_by_day": {"2026-10-26": 5, "2026-10-28": 11},
        "free_agent_pool_size": 60,
        "streamer_board": [{"player": "Josh Hart", "nba_team": "NYK",
                            "positions": "SF", "proj_fppg": 28.8,
                            "best_points_added": 57.6, "managers": {
                                "Nick": {"holes_filled": 2, "points_added": 57.6,
                                         "days": ["2026-10-26", "2026-10-28"]},
                                "Hayden": {"holes_filled": 0, "points_added": 0.0,
                                           "days": []}}}],
        "managers": {
            "Hayden": {"startable_games": 20, "unmatched_players": [],
                       "daily_detail": [
                           {"date": "2026-10-26", "started": 10, "benched": 0,
                            "open_slots": [], "fillable": 0, "benched_players": [],
                            "injured_with_game": 0}]},
            "Nick": {"startable_games": 17, "unmatched_players": ["Deep <Guy>"],
                     "daily_detail": [
                         {"date": "2026-10-26", "started": 7, "benched": 0,
                          "open_slots": ["C", "Util", "Util"], "fillable": 3,
                          "benched_players": [], "injured_with_game": 1},
                         {"date": "2026-10-28", "started": 10, "benched": 2,
                          "open_slots": [], "fillable": 0,
                          "benched_players": ["X", "Y"], "injured_with_game": 0}]},
        }}}}


def test_grid_marks_game_free_days_and_totals_holes():
    g = gg.build_grid(_report())
    assert [d["label"] for d in g["days"]] == ["Mon 10/26", "Tue 10/27", "Wed 10/28"]
    assert [r["manager"] for r in g["rows"]] == ["Hayden", "Nick"]   # by Starts
    row = g["rows"][1]
    assert row["cells"][1]["off"] is True
    assert row["holes"] == 3 and row["fillable"] == 3 and row["overflow"] == 2
    hart = g["board"][0]
    assert [c["manager"] for c in hart["cells"]] == ["Hayden", "Nick"]
    assert hart["cells"][1]["day_labels"] == ["Mon", "Wed"]


def test_no_data_renders_nothing():
    for rep in ({}, {"schedule_strength": None},
                {"schedule_strength": {"upcoming_week": {"week": 24, "error": "x"}}}):
        assert gg.build_grid(rep) is None
        assert gg.render_html(rep) == "" and gg.render_markdown(rep) == ""


def test_markdown_tells_the_drafting_chat_not_to_retype_it():
    md = gg.render_markdown(_report())
    assert "do NOT reproduce" in md
    assert "7 (3 fillable: C,Util,Util)" in md
    assert "10 +2 bench" in md
    assert "| Manager | Starts | Fillable holes | Mon 10/26" in md
    assert "| Josh Hart (NYK, SF, 28.8 proj) | 0 / 0.0 | 2 / 57.6 |" in md


def test_html_highlights_fillable_holes_and_escapes_names():
    out = gg.render_html(_report())
    head = out.split("<tbody>")[0]
    assert head.index(">Starts<") < head.index(">Fillable<") < head.index("Mon 10/26")
    assert '<td class="gg-key gg-top">20</td>' in out     # league-best Starts
    assert "gg-fill" not in out                            # no per-day shading
    assert "Deep &lt;Guy&gt;" in out and "Deep <Guy>" not in out
    assert "Benched with a game: X, Y" in out


def test_newsletter_puts_the_grid_in_betting_lines():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location(
        "nhg", root / "scripts" / "newsletter_html_generator.py")
    nhg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nhg)
    sections = [("Betting Lines", "**Nick vs Hayden**\n\nA preview.")]
    with_grid = nhg.generate_html("t", "s", sections, stats_report=_report())
    without = nhg.generate_html("t", "s", sections, stats_report={"x": 1})
    assert "Week 2 Games Grid" in with_grid
    assert "Games Grid" not in without.split("<body")[1]
