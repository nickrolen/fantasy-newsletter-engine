"""5d2 s.0: one source for every range-dependent number (modules/hub_v2/
ranges.py). On a made-up league (tests/hub_5d2_world.py) through the real
Availability: the seven ranges, week 7's 14 days, IL players never startable,
a passed range hidden, and the grid, the starters and the roster's Next
starts reading the same day fill."""

import copy
from datetime import date, timedelta

import pytest

import hub_5d2_world as W
from modules.hub_v2 import ranges as R
from modules import hub_state


@pytest.fixture(scope="module")
def w():
    return W.world()


def test_the_seven_ranges_after_mondays_close(w):
    wk = w["wk_dates"]
    # Tue 11-24, week 6, after the close: a pickup joins week 7 (rule 7)
    rs = R.ranges(wk[7][0], 7, wk)
    assert [r.key for r in rs] == list(R.RANGE_KEYS)
    by = {r.key: r for r in rs}
    assert by["next"].weeks == (7,) and len(by["next"].days) == 14 and "14 days" in by["next"].sub
    assert by["next2"].weeks == (7, 8) and by["next3"].weeks == (7, 8, 9)
    assert by["ros"].weeks == tuple(range(7, 16))                  # rest of season ends at week 15
    assert by["semis"].weeks == (16, 17, 18) and "17 is 14 days" in by["semis"].sub
    assert by["finals"].weeks == (19, 20, 21) and by["cup"].weeks == (22, 23)
    assert not any(r.partial for r in rs)
    assert [r.label for r in rs] == ["Next week", "Next 2 weeks", "Next 3 weeks", "Rest of season",
                                     "Semifinals", "Finals", "Cup"]


def test_before_the_close_the_week_under_way_counts_its_remaining_days(w):
    wk = w["wk_dates"]
    today = wk[6][0]                                                # Monday, window open
    rs = {r.key: r for r in R.ranges(today, 6, wk)}
    assert rs["next"].days[0] == today and rs["next"].partial is False
    tue = wk[6][1]
    rs = {r.key: r for r in R.ranges(tue, 6, wk)}
    assert rs["next"].days == tuple(wk[6][1:]) and rs["next"].partial and "(rest)" in rs["next"].sub


def test_a_range_that_has_passed_is_hidden(w):
    wk = w["wk_dates"]
    keys = [r.key for r in R.ranges(wk[17][0], 17, wk)]
    assert "ros" not in keys and keys[:3] == ["next", "next2", "next3"] and "semis" in keys
    semis = next(r for r in R.ranges(wk[17][0], 17, wk) if r.key == "semis")
    assert semis.weeks == (17, 18)                                   # under way: what's left of it
    keys = [r.key for r in R.ranges(wk[19][0], 19, wk)]
    assert "semis" not in keys and "finals" in keys and "cup" in keys
    keys = [r.key for r in R.ranges(wk[23][0], 23, wk)]
    assert keys == ["next", "next2", "next3", "cup"]                  # the last week: no week 24
    assert all(r.weeks == (23,) for r in R.ranges(wk[23][0], 23, wk))


def test_the_stage_weeks_are_config_and_required():
    from modules.data_loader import _LEAGUE_CONFIG
    cfg = copy.deepcopy(_LEAGUE_CONFIG)
    assert R.stage_weeks_cfg(cfg) == {"ros": (1, 15), "semis": (16, 18), "finals": (19, 21), "cup": (22, 23)}
    cfg["postseason_format"]["stages"]["playoffs"]["rounds"] = [
        r for r in cfg["postseason_format"]["stages"]["playoffs"]["rounds"] if r["name"] != "Final"]
    with pytest.raises(R.RangeError, match="Final"):
        R.stage_weeks_cfg(cfg)
    cfg = copy.deepcopy(_LEAGUE_CONFIG)
    del cfg["postseason_format"]["stages"]["cup"]["weeks"]
    with pytest.raises(R.RangeError, match="cup"):
        R.stage_weeks_cfg(cfg)


def test_the_day_never_counts_an_il_player_and_its_numbers_add_up(w):
    src = w["src"]
    seen_il = 0
    for m in w["managers"]:
        for d in w["wk_dates"][6][1:] + w["wk_dates"][7]:
            x = src.day(m, d)
            av = src.av_on(d)
            il = set(av.il.get(m) or {})
            assert not (set(x.sure) | set(x.maybe) | set(x.started)) & il
            seen_il += sum(1 for n in il if av.has_game(n, d))
            assert x.starts[0] <= x.starts[1] <= R.SEATS
            assert x.count[0] - x.starts[0] >= 0 and x.count[1] - x.starts[1] >= 0
            assert x.empty == ((R.SEATS - x.starts[1], R.SEATS - x.starts[0]) if x.nba else (0, 0))
            assert x.pts[0] <= x.pts[1] + 1e-9
            assert x.light == (bool(x.nba) and x.count[1] <= 4) and x.over == (x.count[1] > R.SEATS)
    assert seen_il > 0                                               # the IL players had games to leave out


def test_a_day_with_no_nba_games_has_no_empty_slots(w):
    src = w["src"]
    xmas_eve = date(2026, 12, 24)
    for m in w["managers"]:
        x = src.day(m, xmas_eve)
        assert x.nba == 0 and x.count == (0, 0) and x.empty == (0, 0) and x.kind == "off" and not x.light


def test_week_7_is_fourteen_days_and_one_week(w):
    src = w["src"]
    t = src.team("Marcus", w["wk_dates"][7])
    assert t.days == 14
    assert t.starts[1] <= 14 * R.SEATS
    assert t.empty[0] == sum(src.day("Marcus", d).empty[0] for d in w["wk_dates"][7])


def test_the_range_sums_its_days_scenario_by_scenario(w):
    src = w["src"]
    days = w["wk_dates"][6][1:] + w["wk_dates"][7]
    for m in w["managers"]:
        t = src.team(m, days)
        xs = [src.day(m, d) for d in days]
        assert t.games == (sum(x.count[0] for x in xs), sum(x.count[1] for x in xs))
        assert t.starts == (sum(x.starts[0] for x in xs), sum(x.starts[1] for x in xs))
        lo, hi = sum(x.idle_s[0] for x in xs), sum(x.idle_s[1] for x in xs)
        assert t.idle == (min(lo, hi), max(lo, hi))
        assert t.games[0] - t.starts[0] in t.idle and t.games[1] - t.starts[1] in t.idle
        assert t.light_days == sum(x.light for x in xs) and t.over_days == sum(x.over for x in xs)


def test_a_q_makes_a_range_and_the_low_end_leaves_him_out(w):
    src = w["src"]
    q = [n for n, t in w["tags"].items() if t == "Q"][0]
    m = next(m for m, r in w["rosters"].items() if q in r)
    d = w["av"].next_game(q)
    x = src.day(m, d)
    assert q in x.maybe and q not in x.sure and x.count[1] == x.count[0] + 1


def test_this_weeks_days_use_this_weeks_rosters_and_later_days_next_weeks(w):
    src = w["src"]
    back = w["rosters"]["Dana"][-1]                                   # activated at next week's window
    d6 = [d for d in w["wk_dates"][6][1:] if w["av"].has_game(back, d)]
    d7 = [d for d in w["wk_dates"][7] if w["av"].plays(back, d)]
    assert d6 and d7
    assert all(back not in src.day("Dana", d).sure for d in d6)
    assert any(back in src.day("Dana", d).sure + src.day("Dana", d).maybe for d in d7)


def test_the_grid_and_the_starters_read_the_same_day_fill(w):
    """One source: hub_state.build_grid_tab and data.starters_on are the day fill."""
    from modules.hub_v2 import data as v2data
    src, av = w["src"], w["av"]
    days = w["wk_dates"][6][1:]
    games_on = {d: src.nba(d) for d in days}
    tab = hub_state.build_grid_tab(av, w["managers"], days, 4, games_on, {})
    for row in tab["rows"]:
        m = row["manager"]
        t = src.team(m, days)
        assert row["starts"] == R.rng(*t.starts) and row["idle"] == R.rng(*t.idle)
        for d, c in zip(days, row["cells"]):
            x = src.day(m, d)
            assert c["starts"] == R.rng(*x.starts) and c["n"] == R.rng(*x.count) and c["kind"] == x.kind
            st, maybe, nba = v2data.starters_on(av, m, d)
            assert st == list(x.sure_started) and maybe == [p for p in x.started if p not in st]
            assert nba == list(x.nba_out)


def test_next_starts_are_the_day_fills_starters(w):
    src = w["src"]
    days = w["wk_dates"][7]
    for m in w["managers"]:
        ns = src.player_starts(m, days)
        assert sum(ns.values()) == src.team(m, days).starts[1]


def test_a_free_agents_games_on_empty_slot_days(w):
    """Nick, 11-21: games on days the team has an empty slot, not starts."""
    src, fa_av = w["src"], w["fa_av"]
    days = w["wk_dates"][7]
    for m in w["managers"]:
        empty = src.empty_days(m, days)
        assert empty and all(src.day(m, d).empty[0] > 0 for d in empty)
        for n in w["fa"][:8]:
            g = src.games_on_empty(m, n, fa_av, days)
            assert g == sum(1 for d in empty if fa_av.plays(n, d)) <= src.player_games(n, days, fa_av)
