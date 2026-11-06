"""
tests/test_advice_v2.py -- advice v2's engine (modules/advice_v2), V1.

A. Invariants: no file read; common random numbers (same seed and inputs, the
   same ranking); a top-4 keeper is never a suggested drop; an open IL slot is
   never a free roster spot; only O/OFS go to IL; the weightings' arithmetic;
   the last add's bar; a horizon that does not start at the tags' anchor raises.
B. Nick's scenarios 1-7 (claude/ADVICE_V2_DESIGN.md s.3a; fixtures in
   tests/advice_v2_scenarios.py) under the recommended weighting. Scenario 5
   runs three ways: Paolo in the IL slot, Jalen Johnson in it protected, and
   Jalen Johnson unprotected (the pricing alone must keep him).
"""

from __future__ import annotations

import inspect
import re

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


def test_a_horizon_that_does_not_start_at_the_anchor_raises():
    inp = S.scenario_1().inputs()
    inp.anchor = inp.anchor.replace(day=inp.anchor.day + 1)
    inp._ctx.clear()
    with pytest.raises(ValueError, match="anchor"):
        av.candidate_moves(inp, "Nick", FAST)


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


def test_scenario_3_lillard_for_jerome_as_a_chat_move():
    """Valued from next Monday (horizon = weeks 2 and 3): +1 startable game."""
    _inp, r = rec(S.scenario_3(), horizon=(2, 3))
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
