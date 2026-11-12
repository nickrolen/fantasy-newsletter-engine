"""
tests/test_advice_v2.py -- advice v2's engine (modules/advice_v2), V1 and V2.

A. Invariants: no file read; common random numbers (same seed and inputs, the
   same ranking); a top-4 keeper is never a suggested drop; an open IL slot is
   never a free roster spot; only O/OFS go to IL; the weightings' arithmetic;
   the last add's bar; a horizon that does not start at the tags' anchor raises.
B. Nick's scenarios 1-7 (claude/ADVICE_V2_DESIGN.md s.3a; fixtures in
   tests/advice_v2_scenarios.py) under the recommended weighting. Scenario 5
   runs three ways: Paolo in the IL slot, Jalen Johnson in it protected, and
   Jalen Johnson unprotected (the pricing alone must keep him). Scenario 3
   runs through the live chat-move path (V2 s.8).
C. V2 (claude/HANDOFF_ADVICE_V2_2026-11-11.md): scenarios 8-12 (contested,
   pending claim, budget, the switch at the window close, tags anchored for a
   horizon starting next week), the points tie-break, bracket ties.
"""

from __future__ import annotations

import inspect
from datetime import timedelta
import re

import numpy as np
import pytest

import advice_v2_scenarios as S
from modules import advice_v2 as av

FAST = av.Settings(price_sims=600, screen_sims=32, long_sims=8)


def rec(fx_or_inputs, settings=FAST, weighting=av.RECOMMENDED, manager="Nick", **kw):
    inp = fx_or_inputs.inputs(**kw) if isinstance(fx_or_inputs, S.Fixture) else fx_or_inputs
    return inp, av.recommend(inp, manager, settings, weighting)


def touches(move, name):
    return name in (move.add, move.drop, move.to_il)


# =============================================================================
# A. invariants
# =============================================================================

@pytest.mark.parametrize("mod", ["advice_v2", "advice_replay"])
def test_the_engine_modules_open_no_file(mod):
    src = inspect.getsource(__import__(f"modules.{mod}", fromlist=["x"]))
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    for pat in (r"\bopen\(", r"read_text\(", r"read_bytes\(", r"json\.load\(", r"read_excel\(",
                r"read_csv\(", r"urlopen\(", r"write_text\(", r"\.to_json\("):
        assert not re.search(pat, code), f"modules/{mod}.py calls {pat}"


def test_same_seed_and_inputs_give_the_same_ranking():
    a = av.recommend(S.scenario_1().inputs(), "Nick", FAST)
    b = av.recommend(S.scenario_1().inputs(), "Nick", FAST)
    assert [(round(s, 12), p.move) for s, p in a.ranked] == [(round(s, 12), p.move) for s, p in b.ranked]


def test_an_unchanged_roster_prices_to_exactly_zero():
    """Common random numbers: a move that changes nothing moves nothing."""
    inp = S.scenario_1().inputs()
    st = inp.managers["Nick"]
    base = [av.week_roster(inp, st, None, k, None) for k in (0, 1)]
    for k, w in enumerate(inp.horizon):
        a = av._scores(inp, "Nick", *base[k], w, FAST)[0]
        inp._sims.clear()
        b = av._scores(inp, "Nick", *base[k], w, FAST)[0]
        assert (a == b).all()


@pytest.mark.parametrize("mk", [S.scenario_1, S.scenario_2, S.scenario_4, lambda: S.scenario_5(False),
                                lambda: S.scenario_5(True), lambda: S.scenario_7(45)])
def test_a_top_four_keeper_is_never_a_suggested_drop(mk):
    inp = mk().inputs()
    prot = av.protected(inp.managers["Nick"], FAST.protected)
    assert len(prot) == 4
    moves = av.candidate_moves(inp, "Nick", FAST)
    assert moves
    for mo in moves:
        assert mo.drop not in prot
    r = av.recommend(inp, "Nick", FAST)
    for _s, p in r.ranked:
        assert p.move.drop not in prot and p.followup_drop not in prot


def test_protection_raises_without_a_keep_chance():
    inp = S.scenario_1().inputs()
    st = inp.managers["Nick"]
    keep = dict(st.keep)
    keep.pop("Julius Randle")
    bad = av.ManagerState(st.manager, st.active, st.il, st.active_capacity, st.il_capacity,
                          st.adds_left, keep, st.opponents)
    with pytest.raises(KeyError):
        av.protected(bad, 4)


def test_an_open_il_slot_is_never_a_free_roster_spot():
    """Full active roster, one IL slot open, nobody O: no add without a drop."""
    fx = S.scenario_1()
    inp = fx.inputs(il_capacity=2)
    st = inp.managers["Nick"]
    assert len(st.il) < st.il_capacity and len(st.active) == st.active_capacity
    kinds = {mo.kind for mo in av.candidate_moves(inp, "Nick", FAST)}
    assert kinds == {"add_drop"}


def test_an_open_active_spot_allows_a_plain_add():
    inp = S.scenario_1().inputs(active_capacity=16)
    kinds = {mo.kind for mo in av.candidate_moves(inp, "Nick", FAST)}
    assert "add_open" in kinds


def test_only_o_and_ofs_players_go_to_il():
    fx = S.scenario_7(45)
    fx.statuses["Short O"] = "Q"
    inp = fx.inputs()
    assert not [mo for mo in av.candidate_moves(inp, "Nick", FAST) if mo.to_il]
    inp = S.scenario_7(45).inputs()
    il_moves = [mo for mo in av.candidate_moves(inp, "Nick", FAST) if mo.to_il]
    assert il_moves and {mo.to_il for mo in il_moves} == {"Short O"}


def test_the_weightings():
    p = av.Priced(av.Move("Nick", "add_drop", "A", drop="B"), (0.1, 0.05), (0.5, 0.5), (10, 5), (1, 1),
                  0.02, -0.03, -40.0, 0.2)
    assert av.Weighting("w", "wins", 1, 1, 0).score(p) == pytest.approx(0.15)
    assert av.Weighting("w", "wins", 1, 1, 1).score(p) == pytest.approx(0.15 - 0.15)
    assert av.Weighting("w", "title", lam=1).score(p) == pytest.approx(-0.01)
    assert av.RECOMMENDED.score(p) == pytest.approx(0.15 - 0.5 * 0.15)
    gem = av.Priced(p.move, p.dwp, p.wp_base, p.dpts, p.dstarts, 0.02, +0.5, 400.0, 0.2)
    assert av.RECOMMENDED.score(gem) == pytest.approx(0.15)       # the penalty never pays
    with pytest.raises(ValueError):
        av.Weighting("w", "nonsense").score(p)


def test_no_adds_left_means_no_recommendation():
    inp, r = rec(S.scenario_1(), adds_left=0)
    assert r.top is None and r.ranked == ()


def test_an_anchor_after_the_horizon_starts_raises():
    """Tags cannot be dated after the games they price (V2: a later horizon
    is anchored at the fetch date; an anchor AFTER the horizon's first day
    is an error, never a re-anchoring)."""
    inp = S.scenario_1().inputs()
    inp.anchor = inp.anchor.replace(day=inp.anchor.day + 1)
    inp._ctx.clear()
    with pytest.raises(ValueError, match="anchor"):
        av.candidate_moves(inp, "Nick", FAST)
    with pytest.raises(ValueError, match="anchor"):
        inp.check()


def test_tags_more_than_a_week_before_the_horizon_raise():
    """Tags fetched in week 1 cannot price a horizon starting in week 3."""
    inp = S.scenario_3().inputs(horizon=(3, None), balance=False)
    inp.anchor = S.day(1, 2)
    with pytest.raises(ValueError, match="too old"):
        inp.check()


def test_inputs_check_raises_on_a_doubly_rostered_player():
    fx = S.scenario_1()
    fx.pool.append("Julius Randle")
    with pytest.raises(ValueError, match="roster"):
        fx.inputs(balance=False)


# =============================================================================
# B. Nick's scenarios
# =============================================================================

def test_scenario_1_coward_over_randle():
    _inp, r = rec(S.scenario_1())
    assert r.top is not None
    assert (r.top.move.add, r.top.move.drop) == ("Cedric Coward", "Julius Randle")


def test_scenario_2_the_overflow_trap():
    inp, r = rec(S.scenario_2())
    assert r.top.move.add == "FA Clean"
    score = {p.move.add: s for s, p in r.ranked if p.move.drop == "Spare"}
    assert score["FA Clean"] > score["FA Overflow"]


def test_scenario_3_lillard_for_jerome_as_a_chat_move_through_the_live_path():
    """Wednesday of week 1, after Monday's close: the live path's horizon
    (horizon_for) is the chat move, weeks 2 and 3, the tags anchored at
    Wednesday; +1 startable game next week."""
    fx = S.scenario_3()
    inp = fx.inputs(now=S.at(1, 2, 15))
    assert (inp.kind, inp.horizon, inp.anchor) == (av.CHAT, (2, 3), S.day(1, 2))
    r = av.recommend(inp, "Nick", FAST)
    assert (r.top.move.add, r.top.move.drop) == ("Damian Lillard", "Ty Jerome")
    assert r.top.dstarts[0] == pytest.approx(1.0, abs=0.05)


def test_scenario_4_up_300_shifts_the_ranking_to_next_week():
    _i, close = rec(S.scenario_4())
    _i, up = rec(S.scenario_4(), banked={("Nick", 1): 300.0})
    assert close.top.move.add == "FA This Week"
    assert up.top.move.add != "FA This Week"
    assert up.top.dwp[1] > up.top.dwp[0]
    this_week = next(p for _s, p in up.ranked if p.move.add == "FA This Week")
    assert this_week.dwp[0] < 0.5 * next(p for _s, p in close.ranked if p.move.add == "FA This Week").dwp[0]


def test_scenario_5_paolo_yes():
    _inp, r = rec(S.scenario_5(jalen_in_paolos_place=False))
    assert r.top is not None and r.top.move.kind == "il_swap"
    assert (r.top.move.drop, r.top.move.to_il) == ("Paolo Banchero", "Luka Doncic")


def test_scenario_5_jalen_johnson_protected_is_never_dropped():
    inp, r = rec(S.scenario_5(jalen_in_paolos_place=True))
    assert "Jalen Johnson" in av.protected(inp.managers["Nick"], 4)
    assert all(not (p.move.drop == "Jalen Johnson") for _s, p in r.ranked)


def test_scenario_5_jalen_johnson_unprotected_the_pricing_keeps_him():
    """Only Luka protected: Jalen Johnson's value after his return must keep
    him. "Wins only" -- no title term -- would not (stated in the V1 result)."""
    settings = av.Settings(price_sims=600, screen_sims=32, long_sims=8, protected=1)
    inp, r = rec(S.scenario_5(jalen_in_paolos_place=True), settings=settings)
    assert "Jalen Johnson" not in av.protected(inp.managers["Nick"], 1)
    jj = [(s, p) for s, p in r.ranked if p.move.drop == "Jalen Johnson"]
    assert jj, "the swap that drops him must be priced"
    assert r.top is None or r.top.move.drop != "Jalen Johnson"
    assert all(s <= 0 for s, _p in jj), "dropping him must score below standing pat"
    wins_only = av.recommend(inp, "Nick", settings, next(w for w in av.WEIGHTINGS if w.name == "wins only"))
    assert any(p.move.drop == "Jalen Johnson" and s > 0 for s, p in wins_only.ranked)


def test_scenario_6_the_third_add_is_not_spent_on_a_marginal_gain():
    _i, three = rec(S.scenario_6())
    _i, one = rec(S.scenario_6(), adds_left=1)
    assert three.top is not None and three.top.move.add == "FA Marginal"
    best = three.ranked[0][0]
    assert 0 < best < FAST.last_add_bar
    assert one.top is None and one.bar == FAST.last_add_bar


@pytest.mark.parametrize("fppg,stash", [(18, False), (45, True)])
def test_scenario_7_a_short_term_o_player_is_stashed_only_for_a_pickup_worth_it(fppg, stash):
    _i, r = rec(S.scenario_7(fppg))
    stashed = r.top is not None and r.top.move.to_il == "Short O"
    assert stashed is stash
    il = next(p for _s, p in r.ranked if p.move.to_il == "Short O")
    if not stash:
        assert il.dpts[0] < 0                  # his lost games outweigh the pickup
    else:
        assert il.followup_drop is not None    # back next week: the plan's second step


# =============================================================================
# C. V2: the live horizons, the ledger's inputs, contested players, ties
# =============================================================================

NO_FILLERS = {"Benton": 0, "Garrett": 0}        # the filler teams make no move (they would want the same star)

def test_scenario_8_contested_both_see_also_wanted_by_and_each_gets_an_uncontested_backup():
    inp = S.scenario_8().inputs(opponents=S.CONTEST_OPPONENTS, balance=False, adds=NO_FILLERS)
    adv = av.advise_all(inp, FAST)
    nick, hayden = adv["Nick"], adv["Hayden"]
    assert nick.top.move.add == hayden.top.move.add == "FA Star"
    assert nick.also_wanted_by == ("Hayden",) and hayden.also_wanted_by == ("Nick",)
    tops = {a.top.move.add for a in adv.values() if a.top is not None}
    for a in (nick, hayden):
        assert a.backup is not None, a.manager
        assert a.backup.move.add not in tops                      # nobody's top: uncontested
        assert a.backup_score > 0
    # a free agent is never split: the advice names him for both, it does not allocate him
    assert not [a for a in adv.values() if a.top is not None and a.top.move.add == "FA Star"
                and a.manager not in ("Nick", "Hayden")]


def test_an_uncontested_top_has_no_also_wanted_by():
    inp = S.scenario_1().inputs(adds=dict(NO_FILLERS, Hayden=0))
    adv = av.advise_all(inp, FAST)
    assert adv["Nick"].top.move.add == "Cedric Coward" and adv["Nick"].also_wanted_by == ()
    # the fillers want him too once they may add: then he is contested
    adv = av.advise_all(S.scenario_1().inputs(), FAST)
    assert adv["Nick"].also_wanted_by == tuple(sorted(m for m, a in adv.items() if m != "Nick"
                                                      and a.top is not None and a.top.move.add == "Cedric Coward"))


def test_scenario_9_a_claimed_player_is_never_suggested_to_anyone():
    """Engine side: a reserved player in the pool raises, and the pool the
    live path passes leaves him out (the ledger side: test_advice_live)."""
    fx = S.scenario_8()
    inp = fx.inputs(opponents=S.CONTEST_OPPONENTS, balance=False, reserved=("FA Star",))
    adv = av.advise_all(inp, FAST)
    for a in adv.values():
        for _s, p in a.rec.ranked:
            assert p.move.add != "FA Star"
    bad = fx.inputs(opponents=S.CONTEST_OPPONENTS, balance=False)
    bad.reserved = frozenset({"FA Star"})
    with pytest.raises(ValueError, match="claimed"):
        bad.check()


def test_scenario_10_the_budget_binds_chat_moves():
    """A chat claim counts against this week's budget (rule 7): at 3 adds used
    no chat move; with 1 left only a move above the last add's bar."""
    now = S.at(1, 2, 15)
    _i, none_left = rec(S.scenario_3(), now=now, adds={"Nick": 0})
    assert none_left.top is None and none_left.note == "no adds left"
    _i, big = rec(S.scenario_3(), now=now, adds={"Nick": 1})
    assert big.top is not None and big.ranked[0][0] > FAST.last_add_bar
    _i, small = rec(_marginal_chat(), now=now, adds={"Nick": 1})
    _i, small3 = rec(_marginal_chat(), now=now, adds={"Nick": 3})
    assert small3.top is not None and small3.top.move.add == "FA Marginal"
    assert small3.ranked[0][0] < FAST.last_add_bar                    # a marginal gain ...
    assert small.top is None and small.bar == FAST.last_add_bar        # ... does not spend the last add


def _marginal_chat():
    """Scenario 6 one week later: the marginal free agent's two games and the
    spare's one are in week 2, the chat move's first week."""
    fx = S.Fixture()
    S.nick_core(fx, crowded=((2, 1), (3, 3)))
    for i in range(4):
        fx.player(f"Bench {i}", [(2, 0), (2, 2), (2, 5), (3, 0), (3, 2), (3, 5)], 33.0, manager="Nick", keep=0.3)
    S.opponents_flat(fx, {"Hayden": 18.0, "Benton": 18.0, "Garrett": 18.0})
    fx.player("Spare", [(2, 6)], 20.0, manager="Nick", keep=0.0)
    fx.player("FA Marginal", [(2, 4), (2, 6)], 11.0, fa=True)
    return fx


def test_scenario_11_the_switch_at_the_window_close():
    """The same inputs: a Monday move (this week and next) a minute before the
    close, a chat move (next week and the week after) a minute after."""
    fx = S.scenario_4()
    close = S.close_of(1)
    before = fx.inputs(now=close - timedelta(minutes=1))
    after = S.scenario_4().inputs(now=close + timedelta(minutes=1))
    assert (before.kind, before.horizon) == (av.MONDAY, (1, 2))
    assert (after.kind, after.horizon) == (av.CHAT, (2, 3))
    assert before.anchor == after.anchor == S.day(1, 0)
    rb = av.recommend(before, "Nick", FAST)
    ra = av.recommend(after, "Nick", FAST)
    assert rb.top.move.add == "FA This Week"
    assert ra.top.move.add == "FA Next Week"          # FA This Week has no game after this week
    assert all(p.move.add != "FA This Week" or s <= 0 for s, p in ra.ranked)


def test_horizon_for_is_the_clock_not_the_weekday():
    wd = S.scenario_1().week_dates()
    close = S.close_of(1)
    assert av.horizon_for(close - timedelta(seconds=1), 1, wd, close).kind == av.MONDAY
    h = av.horizon_for(close, 1, wd, close)
    assert (h.kind, h.weeks, h.budget_week, h.effective) == (av.CHAT, (2, 3), 1, S.day(2, 0))
    assert h.label() == "Chat move (effective Mon 11-09)"
    assert av.horizon_for(S.at(3, 2), 3, wd, S.close_of(3)) is None          # no week 4: none left
    last = av.horizon_for(S.at(2, 2), 2, wd, S.close_of(2))
    assert last.weeks == (3, None)                                          # past the season: absent
    with pytest.raises(ValueError):
        av.horizon_for(S.at(1, 2).replace(tzinfo=None), 1, wd, close)


def test_scenario_12_tags_are_anchored_at_their_fetch_date_for_a_horizon_starting_next_week():
    """Tuesday of week 1, after the close: horizon weeks 2-3, anchor Tuesday.
    No raise; the O chain spends Wed and Fri of week 1 and at most Monday of
    week 2 -- in marginal_value and in the week engine alike, on the same
    draws -- and his Wed and Fri of week 2 are never charged."""
    from modules import marginal_value as mv, simulator_betting as sb
    from modules.projections import TeamProjections
    fx = S.scenario_12()
    inp = fx.inputs(now=S.at(1, 1, 15), balance=False)
    assert (inp.kind, inp.horizon, inp.anchor) == (av.CHAT, (2, 3), S.day(1, 1))
    want = [S.day(1, 2), S.day(1, 4), S.day(2, 0)]
    ctx = av._mv_ctx(inp, inp.weeks(), 64, 7)
    p = ctx.player("Tagged O")
    chain = mv.tag_missed(ctx, p)
    assert sorted(chain) == want
    tp = {"Nick": TeamProjections("Nick", {"Tagged O": inp.projections["Tagged O"]})}
    blocks = sb.tag_blocks(inp.world, tp, inp.statuses, sb.KeyedDraws(7, 64), tag_anchor=inp.anchor)
    assert blocks["Tagged O"].games == want
    assert (chain[S.day(2, 0)] == blocks["Tagged O"].missed(S.day(2, 0))).all()
    assert chain[S.day(2, 0)].any() and not chain[S.day(2, 0)].all()   # some draws miss Monday
    for d in (S.day(2, 2), S.day(2, 4)):
        assert mv._draws(ctx, p, d, 2).all()
    # mis-anchored at next Monday, the same tag would charge Mon, Wed and Fri of week 2
    wrong = mv.build_context({"Tagged O": inp.projections["Tagged O"]}, {"Nick": ["Tagged O"]},
                             inp.world.nba_schedule, inp.world.schedule["weeks"], "this_week", 1,
                             injury_statuses=inp.statuses, sims=64, seed=7)
    assert sorted(mv.tag_missed(wrong, wrong.player("Tagged O"))) == [S.day(2, 0), S.day(2, 2), S.day(2, 4)]
    r = av.recommend(inp, "Nick", FAST)                  # the whole path prices without a raise
    assert r.ranked


def test_a_chat_move_puts_in_il_only_a_player_still_out_next_monday():
    """Rule 2 at next Monday's window: an O tag alone (back within 3 games) is
    not IL-eligible for a chat move; OFS or an injury entry covering the
    window day is. A Monday move takes the tag now."""
    names = ["A", "B", "C", "D"]
    tags = {"A": "O", "B": "OFS", "C": "O", "D": "Q"}
    assert av.chat_il_eligible(names, tags, {"C"}) == {"B", "C"}
    assert av.monday_il_eligible(names, tags) == {"A", "B", "C"}
    fx = S.scenario_7(45)                 # Short O: tagged O, no injury entry
    inp = fx.inputs(now=S.at(1, 2, 15), balance=False)
    assert "Short O" not in inp.il_eligible
    assert not [mo for mo in av.candidate_moves(inp, "Nick", FAST) if mo.to_il]
    inp.il_eligible = None
    with pytest.raises(ValueError, match="chat"):
        inp.il_ok("Short O")


def test_same_inputs_same_advice():
    a = av.advise_all(S.scenario_8().inputs(opponents=S.CONTEST_OPPONENTS, balance=False), FAST)
    b = av.advise_all(S.scenario_8().inputs(opponents=S.CONTEST_OPPONENTS, balance=False), FAST)
    for m in a:
        assert [(round(s, 12), p.move) for s, p in a[m].rec.ranked] == \
               [(round(s, 12), p.move) for s, p in b[m].rec.ranked]
        assert (a[m].top and a[m].top.move) == (b[m].top and b[m].top.move)
        assert (a[m].backup and a[m].backup.move) == (b[m].backup and b[m].backup.move)
        assert a[m].also_wanted_by == b[m].also_wanted_by


@pytest.mark.parametrize("mk,kw", [(S.scenario_3, {"now": S.at(1, 2, 15)}),
                                   (lambda: S.scenario_5(False), {"now": S.at(1, 2, 15)}),
                                   (S.scenario_8, {"opponents": S.CONTEST_OPPONENTS, "balance": False})])
def test_a_top_four_keeper_is_never_a_suggested_drop_or_backup_drop(mk, kw):
    inp = mk().inputs(**kw)
    adv = av.advise_all(inp, FAST)
    for m, a in adv.items():
        prot = av.protected(inp.managers[m], FAST.protected)
        for p in [a.top, a.backup] + [p for _s, p in a.rec.ranked]:
            if p is not None:
                assert p.move.drop not in prot and p.followup_drop not in prot


def test_a_joining_player_has_no_keep_chance_and_is_not_protected_others_raise():
    inp = S.scenario_1().inputs()
    st = inp.managers["Nick"]
    keep = dict(st.keep)
    keep.pop("Julius Randle")
    joined = av.ManagerState(st.manager, st.active, st.il, st.active_capacity, st.il_capacity, st.adds_left,
                             keep, st.opponents, joining=frozenset({"Julius Randle"}))
    assert "Julius Randle" not in av.protected(joined, 4)
    bare = av.ManagerState(st.manager, st.active, st.il, st.active_capacity, st.il_capacity, st.adds_left,
                           keep, st.opponents)
    with pytest.raises(KeyError):
        av.protected(bare, 4)


def test_the_second_week_roster_carries_the_ledgers_pending_moves():
    """ManagerState.later: next week's roster (a claim joining, a chat drop
    leaving) is priced in horizon week 2 only."""
    inp = S.scenario_1().inputs()
    st = inp.managers["Nick"]
    act2 = tuple(n for n in st.active if n != "Bench 0")
    inp.managers["Nick"] = av.ManagerState(st.manager, st.active, st.il, st.active_capacity, st.il_capacity,
                                           st.adds_left, st.keep, st.opponents, later=(act2, st.il))
    mo = av.Move("Nick", "add_drop", "Cedric Coward", drop="Julius Randle")
    p1, _ = av.week_roster(inp, inp.managers["Nick"], mo, 0, None)
    p2, _ = av.week_roster(inp, inp.managers["Nick"], mo, 1, None)
    assert "Bench 0" in p1 and "Bench 0" not in p2
    assert "Cedric Coward" in p1 and "Cedric Coward" in p2 and "Julius Randle" not in p2


# --- the points tie-break (V2 s.6.2) and bracket ties ---------------------------------

def _p(dwp, dpts, dT_later=0.0, lbar=0.2):
    return av.Priced(av.Move("Nick", "add_drop", "A", drop="B"), tuple(dwp), (0.9, 0.9), tuple(dpts), (0, 0),
                     0.0, dT_later, 0.0, lbar)


def test_the_points_tie_break_ranks_flat_moves_by_expected_startable_points():
    w = av.RECOMMENDED
    flat_hi, flat_lo = _p((0.001, 0.002), (40, 10)), _p((0.003, 0.0), (5, 5))
    assert flat_hi.flat() and flat_lo.flat()
    assert av.rank_key(w, flat_hi) > av.rank_key(w, flat_lo)
    assert av.qualifies(av.rank_key(w, flat_hi), 0.0)                 # beats standing pat on points
    assert not av.qualifies(av.rank_key(w, _p((0.001, 0.0), (-5, 0))), 0.0)
    assert not av.qualifies(av.rank_key(w, flat_hi), 0.01)            # never clears the last add's bar
    real = _p((0.004, 0.003), (1, 1))                                  # 0.7%: not flat
    assert not real.flat() and av.rank_key(w, real) > av.rank_key(w, flat_hi)
    vetoed = _p((0.001, 0.0), (80, 0), dT_later=-0.05)                 # the veto still applies
    assert av.rank_key(w, vetoed)[0] < 0 and not av.qualifies(av.rank_key(w, vetoed), 0.0)


def test_a_decided_horizon_is_ranked_on_points_end_to_end():
    """Up 3000 in both weeks: every win-chance change is flat; the engine still
    names the move with the most startable points rather than noise."""
    fx = S.scenario_4()
    inp = fx.inputs(banked={("Nick", 1): 3000.0, ("Nick", 2): 3000.0})
    r = av.recommend(inp, "Nick", FAST)
    assert all(p.flat() for _s, p in r.ranked)
    pts = [p.dpts[0] + p.dpts[1] for _s, p in r.ranked]
    assert pts == sorted(pts, reverse=True)
    assert r.top is not None and r.top.dpts[0] + r.top.dpts[1] == max(pts)


def test_a_tied_week_counts_by_the_competitions_rule():
    a, b = np.array([1.0, 2.0, 3.0, 3.0]), np.array([1.0, 1.0, 4.0, 3.0])
    assert av._win(a, b) == pytest.approx(0.25 + 0.5 * 0.5)            # regular season: a T is half
    assert av._win(a, b, 1.0) == pytest.approx(0.75)                   # bracket: the higher seed takes it
    assert av._win(a, b, 0.0) == pytest.approx(0.25)


def test_a_week_with_no_matchup_has_no_win_chance_term():
    inp = S.scenario_1().inputs()
    st = inp.managers["Nick"]
    inp.managers["Nick"] = av.ManagerState(st.manager, st.active, st.il, st.active_capacity, st.il_capacity,
                                           st.adds_left, st.keep, {1: st.opponents[1], 2: None})
    r = av.recommend(inp, "Nick", FAST)
    for _s, p in r.ranked:
        assert p.dwp[1] == 0.0 and p.wp_base[1] is None
    assert r.top.move.add == "Cedric Coward"


def test_title_odds_are_the_phases_top_prize():
    from modules import injured_drop
    c = injured_drop.Config(2.0, 1.0, 0.05, 0.05, 4, 6, 0.25, 0.04, 0.075)
    p = av.Priced(av.Move("Nick", "add_drop", "A"), (0.1, 0.1), (0.5, 0.5), (1, 1), (0, 0), 0.03, 0.02, 0, 0.2,
                  dT_rs=0.04, dT_po=0.01)
    assert p.title_odds(c, True) == pytest.approx(0.02)        # P(regular-season title): stake units / 2
    assert p.title_odds(c, False) == pytest.approx(0.01)       # P(champion): stake units / 1


# =============================================================================
# D. The title term measures what the season pass measures
#    (claude/HANDOFF_ADVICE_TITLE_TERM_2026-11-11.md s.2 and Tests)
# =============================================================================

WEEKS6 = (1, 2, 3, 4, 5, 6)


def _every_week(*weekdays):
    return [(w, d) for w in WEEKS6 for d in weekdays]


def plan_fixture(nick_active=13, weak=False, worse=False):
    """A chat move (Wednesday of week 1, after the close: horizon weeks 2-3,
    later weeks 4-6). Nick: `nick_active` fillers (Tue/Thu every week, 20
    FPPG, ten start) and, in an IL slot, Hurt -- O-tagged, no injury entry, so
    the season pass's plan activates him at week 2's window. With 13 fillers
    he comes back to 14 active and the plan fills the open spot with a
    stand-in; with 14 fillers plus Weak (5 FPPG) he makes 16 and the plan drops
    its lowest-projected player. Add: a 25-FPPG free agent on open days."""
    fx = S.Fixture(weeks=WEEKS6)
    for i in range(nick_active):
        fx.player(f"Filler {i}", _every_week(1, 3), 20.0, manager="Nick", keep=0.9 - 0.01 * i)
    if weak:
        fx.player("Weak", _every_week(1), 5.0, manager="Nick", keep=0.0)
    fx.player("Hurt", _every_week(5, 6), 35.0, manager="Nick", il=True, keep=0.05, status="O")
    S.opponents_flat(fx, {"Hayden": 18.0, "Benton": 18.0, "Garrett": 18.0})
    for i in range(6):
        fx.player(f"Wire {i}", _every_week(0), 15.0 - i, fa=True)
    fx.player("Add", _every_week(0, 2, 4), 25.0, fa=True)
    if worse:
        fx.player("Worse", _every_week(0), 1.0, fa=True)
    return fx


def chat_inputs(fx):
    return fx.inputs(now=S.at(1, 2), close=S.close_of(1), balance=False)


def test_a_move_that_changes_nothing_has_a_term_of_exactly_zero():
    """Hurt returns at week 2 and the plan must cut one player: Weak (5) in
    the base. "Add Worse (1), drop Weak" leaves the plan cutting Worse instead:
    the season pass sees the same rosters every week, so every term is 0."""
    fx = plan_fixture(nick_active=14, weak=True, worse=True)
    inp = chat_inputs(fx)
    assert inp.kind == av.CHAT and inp.horizon == (2, 3)
    p = av.price(inp, "Nick", [av.Move("Nick", "add_drop", "Worse", drop="Weak")], FAST)[0]
    P0 = av._plan(inp)
    assert "Weak" in P0[2]["Nick"]["dropped"], "the fixture: the base plan cuts Weak at week 2"
    assert p.dwp == (0.0, 0.0) and p.dpts == (0.0, 0.0) and p.dstarts == (0.0, 0.0)
    assert p.dT_horizon == 0.0 and p.dT_later == 0.0 and p.dpts_later == 0.0
    assert p.dT_rs == 0.0 and p.dT_po == 0.0
    assert all(d == 0.0 for _w, d in p.dpts_later_by_week) and len(p.dpts_later_by_week) == 3


def test_the_later_weeks_are_the_roster_plans_with_without_difference():
    """Base plan: Hurt back at week 2, a stand-in in the open spot. With the
    move (Add into the open spot): Hurt back, Add, no stand-in. Each later
    week's dpts is marginal_value on the plan's week-w active roster with the
    move minus without, computed here independently of price()."""
    from modules import marginal_value as mv
    fx = plan_fixture(nick_active=13)
    inp = chat_inputs(fx)
    mo = av.Move("Nick", "add_open", "Add")
    p = av.price(inp, "Nick", [mo], FAST)[0]
    P0 = av._plan(inp)
    P1 = av._plan(inp, av.known_for(mo, 2))
    assert "Hurt" in P0[2]["Nick"]["active"] and not P0[2]["Nick"]["il"], "the plan returns Hurt"
    stand = [n for n in P0[2]["Nick"]["added"] if n.startswith("Replacement for open spot")]
    assert stand, "the plan fills the open spot with a stand-in"
    assert "Add" in P1[4]["Nick"]["active"] and not P1[2]["Nick"]["added"]
    ctx = av._mv_ctx(inp, [4, 5, 6], FAST.long_sims, FAST.seed)
    mv.add_players(ctx, {**av.PlanSpec.standins(P0), **av.PlanSpec.standins(P1)})
    by = dict(p.dpts_later_by_week)
    assert sorted(by) == [4, 5, 6]
    for w in (4, 5, 6):
        with_ = float(np.mean(mv.roster_totals(ctx, P1[w]["Nick"]["active"])[2][w]))
        without = float(np.mean(mv.roster_totals(ctx, P0[w]["Nick"]["active"])[2][w]))
        assert by[w] == pytest.approx(round(with_ - without, 3), abs=1e-9)
    assert p.dpts_later == pytest.approx(sum(by.values()), abs=1e-2)
    assert p.dT_later == pytest.approx(sum(
        av.injured_drop.point_value(inp.stakes["Nick"].weeks[w], inp.drop_config) * by[w] for w in by), rel=1e-3)


def test_no_replacement_cap_remains():
    """C2's above-replacement cap is gone (the pass does not stream): no
    replacement-level free agent in the engine, and a pickup far below
    replacement for a good player costs his whole static difference."""
    src = inspect.getsource(av)
    assert not re.search(r"def replacement\(|replacement_rank|\bAr\b|ar_w", src)
    assert "replacement_rank" not in av.Settings.__dataclass_fields__
    fx = plan_fixture(nick_active=10, weak=True, worse=True)      # ten fillers: all start
    inp = chat_inputs(fx)
    # cut a 20-FPPG starter for a 1-FPPG pickup: every later week loses most of his points
    p = av.price(inp, "Nick", [av.Move("Nick", "add_drop", "Worse", drop="Filler 0")], FAST)[0]
    by = dict(p.dpts_later_by_week)
    # above replacement (the wire's best is 15) the loss would be capped near (20 - 15) x 2 a
    # week; the static roster charges his two starts, less Weak's (5) taking one seat
    assert all(by[w] < -20.0 for w in (4, 5, 6)), by
    assert p.dT_later < 0


def test_the_horizon_baseline_returns_an_il_player_when_the_plan_does():
    """V2 kept IL fixed through both horizon weeks; the season pass's plan
    activates Hurt (O tag, no injury entry) at week 2's window. The engine's
    "no move" baseline for week 2 is the plan's: Hurt plays."""
    fx = plan_fixture(nick_active=13)
    inp = chat_inputs(fx)
    st = inp.managers["Nick"]
    players, il = av.plan_roster(av._plan(inp), "Nick", 2)
    assert "Hurt" in players and "Hurt" not in il
    assert "Hurt" in av.week_roster(inp, st, None, 0, None)[1], "V2's convention kept him in IL"
    with_him = av._scores(inp, "Nick", players, il, 2, FAST)[0].mean()
    masked = av._scores(inp, "Nick", players, il | {"Hurt"}, 2, FAST)[0].mean()
    assert with_him > masked + 50                      # two games at 35
    mo = av.Move("Nick", "add_open", "Add")
    p = av.price(inp, "Nick", [mo], FAST)[0]
    P1 = av._plan(inp, av.known_for(mo, 2))
    sc = av._scores(inp, "Nick", *av.plan_roster(P1, "Nick", 2), 2, FAST)[0]
    base = av._scores(inp, "Nick", players, il, 2, FAST)[0]
    assert p.dpts[0] == pytest.approx(float(np.mean(sc - base)))


def test_the_plan_is_required():
    fx = plan_fixture(nick_active=13)
    inp = chat_inputs(fx)
    from dataclasses import replace
    with pytest.raises(ValueError, match="no roster plan"):
        replace(inp, plan=None).check()


def test_known_for_is_the_one_encoding():
    mo = av.Move("Nick", "il_swap", "Add", drop="X", to_il="Y")
    k = av.known_for(mo, 5, "Z", 6)
    assert k == {5: {"Nick": {"il_place": ["Y"], "drop": ["X"], "add": ["Add"], "il_activate": []}},
                 6: {"Nick": {"il_place": [], "drop": ["Z"], "add": [], "il_activate": []}}}
    with pytest.raises(ValueError):
        av.known_for(mo, 5, "Z")
    assert av.merge_known({5: {"Nick": {"add": ["A"]}}}, k)[5]["Nick"]["add"] == ["A", "Add"]
    # the check against season_sim encodes moves only through known_for
    src = (S.ROOT if hasattr(S, "ROOT") else __import__("pathlib").Path(__file__).resolve().parent.parent
           ).joinpath("scripts", "advice_title_check.py").read_text(encoding="utf-8")
    assert "av.known_for(" in src and '"il_place"' not in src
