"""recoverable_under_budget -- the games grid's "Recoverable" column.

It replaced "Fillable", which was max_starters(roster + EVERY free agent
playing tonight) - started: the ceiling with unlimited adds. With a ~175-deep
wire that ceiling is always just the day's empty seats, so across 84 measured
cells fillable equalled holes every time and each manager's total equalled
10 * days_with_games - starts exactly -- Starts restated, and it implied 22
recoverable starts in a week the league caps at 3 adds.

The rule being modelled (Nick, 10-15): 3 adds a matchup week, no rollover. An
add made in the pre-matchup window, before the first tip, starts that night;
one made after the first tip is held until the next matchup and cannot help
the week it was made in. So an add is modelled as active for the whole
previewed week, scoring on every day its NBA team plays.
"""
from modules.lineup_fill import SEATS, max_starters
from modules.schedule_strength import recoverable_under_budget as R

# day_pools entries are (roster position sets, starters, teams playing)
ONE_EMPTY_DAY = [([], 0, {"LAL"})]
THREE_EMPTY_DAYS = [([], 0, {"LAL"}), ([], 0, {"LAL"}), ([], 0, {"LAL"})]
FA = ("A", "LAL", {"PG"}, 1.0)


def test_no_add_rule_is_unknown_not_zero():
    """Before 2026-27 the budget did not exist. None keeps the column blank;
    0 would claim there is nothing to gain, which is a different statement."""
    assert R(ONE_EMPTY_DAY, [FA], None) == (None, [])


def test_no_free_agent_pool_is_unknown():
    assert R(ONE_EMPTY_DAY, None, 3) == (None, [])
    assert R(ONE_EMPTY_DAY, [], 3) == (None, [])


def test_one_add_fills_one_seat():
    assert R(ONE_EMPTY_DAY, [FA], 1) == (1, ["A"])


def test_one_add_scores_every_day_his_team_plays():
    """The point of a week-level number: an add is not a one-night rental.
    A per-day 'fillable' cannot express this."""
    gained, picks = R(THREE_EMPTY_DAYS, [FA], 1)
    assert (gained, picks) == (3, ["A"])


def test_an_add_whose_team_is_idle_gains_nothing():
    assert R(ONE_EMPTY_DAY, [("A", "BOS", {"PG"}, 1.0)], 3) == (0, [])


def test_positions_gate_the_fill():
    """A player eligible for no seat cannot be started, however deep the wire."""
    assert R(ONE_EMPTY_DAY, [("A", "LAL", {"XX"}, 1.0)], 3) == (0, [])


def test_it_stops_when_no_further_add_helps():
    """Budget 3, one useful free agent: it must not pad the pick list."""
    gained, picks = R(ONE_EMPTY_DAY, [FA], 3)
    assert gained == 1 and picks == ["A"]


def test_it_spends_the_whole_budget_when_every_add_pays():
    pool = [("A", "LAL", {"PG"}, 1.0), ("B", "LAL", {"PG"}, 1.0),
            ("C", "LAL", {"PG"}, 1.0)]
    gained, picks = R(ONE_EMPTY_DAY, pool, 3)
    assert gained == 3 and sorted(picks) == ["A", "B", "C"]


def test_it_never_exceeds_the_budget():
    pool = [(n, "LAL", {"PG"}, 1.0) for n in "ABCDEFGH"]
    gained, picks = R(ONE_EMPTY_DAY, pool, 3)
    assert len(picks) <= 3 and gained <= 3


def test_a_full_lineup_has_nothing_to_recover():
    full = [frozenset(p) for _n, p in SEATS]
    started = max_starters(full)
    assert started == len(SEATS)
    assert R([(full, started, {"LAL"})], [FA], 3) == (0, [])


def test_it_never_exceeds_the_weeks_open_seats():
    """The invariant published_tables asserts on the rendered grid: you
    cannot buy back a start there is no seat for."""
    pool = [(n, "LAL", {"PG"}, 1.0) for n in "ABCDEFGH"]
    for pools in (ONE_EMPTY_DAY, THREE_EMPTY_DAYS):
        holes = sum(len(SEATS) - started for _sets, started, _t in pools)
        gained, _ = R(pools, pool, 3)
        assert 0 <= gained <= holes


# ---------------------------------------------------------------------------
# _resolve_budgets -- one source for the number
# ---------------------------------------------------------------------------

from modules.schedule_strength import _resolve_budgets

MGRS = ["Nick", "Hayden"]


def test_a_flat_int_applies_to_everyone():
    assert _resolve_budgets(3, MGRS) == (3, {"Nick": 3, "Hayden": 3}, None)


def test_none_falls_back_to_the_league_rule():
    from modules.data_loader import add_budget_for
    league, per, synced = _resolve_budgets(None, MGRS)
    assert league == add_budget_for()
    assert per == {m: add_budget_for() for m in MGRS} and synced is None


def test_build_add_budget_block_spends_remaining_not_the_rule():
    """The bug this fixes: quoting 3 at a manager who has already used two
    of his three adds in the previewed week's pre-tip window."""
    block = {
        "budget": 3,
        "source_exists": True,
        "managers": {"Nick": {"remaining": 1}, "Hayden": {"remaining": 3}},
    }
    league, per, synced = _resolve_budgets(block, MGRS)
    assert league == 3
    assert per == {"Nick": 1, "Hayden": 3}
    assert synced is True


def test_a_manager_missing_from_the_block_gets_the_league_rule():
    block = {"budget": 3, "source_exists": False,
             "managers": {"Nick": {"remaining": 0}}}
    league, per, synced = _resolve_budgets(block, MGRS)
    assert per == {"Nick": 0, "Hayden": 3} and synced is False


def test_spending_fewer_adds_recovers_fewer_starts():
    """End to end on the greedy: the budget is the lever."""
    pool = [(n, "LAL", {"PG"}, 1.0) for n in "ABCDEFGH"]
    assert R(ONE_EMPTY_DAY, pool, 3)[0] == 3
    assert R(ONE_EMPTY_DAY, pool, 1)[0] == 1


def test_spent_out_recovers_zero_not_unknown():
    """A manager who used all three adds can recover nothing, and 0 says so.
    "?" would read as "we do not know", which is a different claim."""
    pool = [(n, "LAL", {"PG"}, 1.0) for n in "ABCDEFGH"]
    assert R(ONE_EMPTY_DAY, pool, 0) == (0, [])
