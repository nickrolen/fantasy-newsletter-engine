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


def test_fillable_lets_existing_starters_move():
    """2025-26 week 20, Hayden's Saturday, in miniature: the only open seat
    is F, a forward sits in Util, and the free agent is a point guard. Slide
    the forward to F and the guard takes Util -- one fillable hole. The old
    check ("does he fit a seat left open?") said zero."""
    roster = {"PG1": "PG", "SG1": "SG", "G1": "PG", "SF1": "SF", "PF1": "PF",
              "C1": "C", "C2": "C", "U1": "SF", "U2": "SG"}
    pinfo = ss.PlayerIndex({n: info("BOS", p, 30.0) for n, p in roster.items()})
    pinfo["FA Guard"] = info("BOS", "PG", 25.0)
    pool = ss.build_free_agent_pool(pinfo, {"Nick": list(roster)})
    r = ss.simulate_daily_lineups("Nick", list(roster), pinfo, {MON: {"BOS", "LAL"}}, {},
                                  free_agents=pool)
    day = r["daily_detail"][0]
    assert day["started"] == 9
    assert day["fillable"] == 1


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


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------

def _report():
    return {"schedule_strength": {"upcoming_week": {
        "week": 2, "start_date": "2026-10-26", "end_date": "2026-10-28",
        "nba_games_by_day": {"2026-10-26": 5, "2026-10-28": 11},
        "free_agent_pool_size": 60,
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
    assert "board" not in g


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
    assert "streamer" not in md.lower()


def test_html_highlights_fillable_holes_and_escapes_names():
    out = gg.render_html(_report())
    head = out.split("<tbody>")[0]
    assert head.index(">Starts<") < head.index(">Fillable<") < head.index("Mon 10/26")
    assert '<td class="gg-key gg-top">20</td>' in out     # league-best Starts
    assert "gg-fill" not in out                            # no per-day shading
    assert "streamer" not in out.lower()                   # board cut for week 1
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


# ---------------------------------------------------------------------------
# Grid invariants, over random rosters and schedules
# ---------------------------------------------------------------------------

POSITIONS = ["PG", "SG", "SF", "PF", "C", "PG,SG", "SG,SF", "SF,PF", "PF,C", "PG,SG,SF"]
TEAMS = sorted(ss.NBA_TEAMS)


def _random_report(rng):
    """A full pipeline run -- simulation, FA pool, grid -- on random inputs."""
    names = [f"P{i}" for i in range(80)]
    pinfo = ss.PlayerIndex({
        n: info(rng.choice(TEAMS), rng.choice(POSITIONS), round(rng.uniform(5, 55), 1))
        for n in names})
    rosters = {m: names[i * 15:(i + 1) * 15] for i, m in enumerate(["A", "B", "C", "D"])}
    start = date(2026, 11, 2)
    games, days = [], 7
    for k in range(days):
        playing = rng.sample(TEAMS, 2 * rng.randint(0, 12))
        d = date.fromordinal(start.toordinal() + k).isoformat()
        games += [{"date": d, "home": playing[j], "away": playing[j + 1]}
                  for j in range(0, len(playing), 2)]
    weeks = [{"week": 3, "start_date": start.isoformat(),
              "end_date": date.fromordinal(start.toordinal() + days - 1).isoformat()}]
    out = {"players": [{"player_name": n, "out_weeks": [3]}
                       for n in rng.sample(names, 6)]}
    pool = ss.build_free_agent_pool(pinfo, rosters)
    import unittest.mock as um
    with um.patch.object(ss, "MANAGERS", list(rosters)):
        up = ss._build_for_week_with_lineups(3, weeks, {"games": games}, rosters,
                                             pinfo, out, free_agents=pool)
    return {"schedule_strength": {"upcoming_week": up}}


@pytest.mark.parametrize("seed", range(40))
def test_row_totals_are_the_sum_of_their_days(seed):
    import random
    g = gg.build_grid(_random_report(random.Random(seed)))
    for r in g["rows"]:
        days = [c for c in r["cells"] if not c["off"]]
        assert r["startable"] == sum(c["started"] for c in days)
        assert r["fillable"] == sum(c["fillable"] for c in days)
        assert r["holes"] == sum(c["holes"] for c in days)
        assert r["overflow"] == sum(c["overflow"] for c in days)


@pytest.mark.parametrize("seed", range(40))
def test_every_cell_accounts_for_all_ten_seats(seed):
    import random
    g = gg.build_grid(_random_report(random.Random(seed)))
    for r in g["rows"]:
        for c in r["cells"]:
            if c["off"]:
                continue
            assert c["started"] + c["holes"] == gg.STARTING_SLOTS
            assert 0 <= c["fillable"] <= c["holes"]
            assert len(c["open_slots"]) == c["holes"]


def test_starts_plus_fillable_is_not_always_ten():
    """Why the stronger claim is not tested as an invariant.

    Nine starters, the only open seat is C, and the one free agent playing
    tonight is a guard. Starts 9 + fillable 0 = 9. In a deep four-team pool
    this is rare -- it held for every cell of 2025-26 week 20 -- but it is a
    property of the data, not of the grid.
    """
    roster = {"PG": "PG", "SG": "SG", "G": "PG", "SF": "SF", "PF": "PF",
              "F": "SF", "C": "C", "U1": "PG", "U2": "SG"}
    pinfo = ss.PlayerIndex({n: info("BOS", p, 30.0) for n, p in roster.items()})
    pinfo["FA Guard"] = info("BOS", "PG", 25.0)
    pool = ss.build_free_agent_pool(pinfo, {"Nick": list(roster)})
    r = ss.simulate_daily_lineups("Nick", list(roster), pinfo, {MON: {"BOS", "LAL"}}, {},
                                  free_agents=pool)
    day = r["daily_detail"][0]
    assert day["started"] == 9 and day["open_slots"] == ["C"]
    assert day["fillable"] == 0


def test_the_fill_starts_as_many_players_as_can_possibly_start():
    """Nine players, nine seats they can fill -- the old greedy started eight.

    The SF/SG player went to SG (tried before SF), and the PG/SG player
    found PG, SG, G and both Util taken: SF empty, a man benched. Was an
    xfail pinning the bug until the exact fill landed.
    """
    av = [("p0", {"PG"}, 50), ("p1", {"PG"}, 49), ("p2", {"PG"}, 48),
          ("p3", {"PF"}, 47), ("p4", {"PG"}, 46), ("p5", {"C", "PF"}, 45),
          ("p6", {"SF", "SG"}, 44), ("p7", {"C", "PF"}, 43), ("p8", {"PG", "SG"}, 42)]
    started, benched = ss.fill_daily_lineup(av)
    assert len(started) == 9 and benched == []


def _brute_best(players):
    """Max (starters, projected points) by trying every subset, small rosters."""
    import itertools
    from modules.lineup_fill import SEATS
    def seatable(sub):
        def go(i, used):
            if i == len(sub):
                return True
            return any(si not in used and (sub[i][1] & el) and go(i + 1, used | {si})
                       for si, (_n, el) in enumerate(SEATS))
        return go(0, frozenset())
    best = (0, 0.0)
    for k in range(min(len(players), 10), -1, -1):
        for sub in itertools.combinations(players, k):
            if seatable(sub):
                best = max(best, (k, round(sum(p[2] for p in sub), 6)))
        if best[0] == k:
            break
    return best


@pytest.mark.parametrize("seed", range(60))
def test_exact_fill_matches_brute_force(seed):
    """Most starters, then most projected points -- checked by exhaustion."""
    import random
    from modules.lineup_fill import exact_fill
    rng = random.Random(seed)
    players = [(f"p{i}", frozenset(rng.choice(POSITIONS).split(",")),
                round(rng.uniform(5, 55), 1)) for i in range(rng.randint(6, 12))]
    started, benched, assignment = exact_fill(players)
    proj = {p[0]: p[2] for p in players}
    assert (len(started), round(sum(proj[n] for n in started), 6)) == _brute_best(players)
    assert sorted(started) == sorted(assignment.values())
    assert set(started) | set(benched) == {p[0] for p in players}


def test_what_if_optimizer_is_exact_too():
    """lineup_optimizer.optimize_lineup was a slot-first greedy."""
    from modules.lineup_optimizer import AvailablePlayer, optimize_lineup
    av = [AvailablePlayer("p0", ["PG"], 50), AvailablePlayer("p1", ["PG"], 49),
          AvailablePlayer("p2", ["PG"], 48), AvailablePlayer("p3", ["PF"], 47),
          AvailablePlayer("p4", ["PG"], 46), AvailablePlayer("p5", ["C", "PF"], 45),
          AvailablePlayer("p6", ["SF", "SG"], 44), AvailablePlayer("p7", ["C", "PF"], 43),
          AvailablePlayer("p8", ["PG", "SG"], 42)]
    lineup = optimize_lineup(av)
    assert len(lineup.starters) == 9 and lineup.bench == []
    assert len(lineup.unfilled_slots) == 1
