"""44a: IL returns and injury entries -- one rule for the plan and advice
(claude/HANDOFF_44A_IL_RETURNS_2026-11-13.md s.2-s.3).

THE ONE ACTIVATION RULE (roster_plan.activation_drops): when IL returns take a
team over its 15 active spots, the plan drops the player whose loss costs the
least LONG-RUN VALUE (roster_plan.LongRun: expected startable points,
marginal_value, from the window through the stakes' last week -- advice's IL
follow-up measure since V2), never a protected player (top 4 by keep chance)
and never a returner. Advice reads the plan: its activation step (s.3) and its
IL follow-up drop are the plan's own, so the two cannot disagree.

THE STEP (advice_v2.activation_step): at a chat move's window the plan's
activation is shown before the pick, and the pick is priced on the roster after
it. A Monday move's window is the plan's locked start week (case 10, raised):
no step there.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import advice_v2_scenarios as S
from modules import advice_live as al
from modules import advice_v2 as av
from modules import injured_drop as idr
from modules import roster_plan as rp
from modules.data_loader import MANAGERS
from test_advice_v2 import FAST, WEEKS6, _every_week, chat_inputs
from test_roster_plan import _build, _league, _p, activation_ctx

ROOT = Path(__file__).parent.parent


# =============================================================================
# fixtures
# =============================================================================

def returner_fixture(*, weak=True, weak_keep=0.0, nick_active=14, hurt=True, hurt_out=(),
                     hurt_return=None, il_candidate=False, hurt_days=(5, 6), hurt_tag="O"):
    """test_advice_v2.plan_fixture's world (Wednesday of week 1, after the
    close: a chat move into weeks 2-3, later weeks 4-6): Nick has
    `nick_active` fillers (Tue/Thu, 20 FPPG, keep 0.9 down by 0.01), Weak
    (Tue, 5 FPPG, keep `weak_keep`) and, in an IL slot, Hurt (tagged
    `hurt_tag`, O by default; an injury entry only if hurt_out is given;
    hurt_return: a midweek return date). With 14 fillers and Weak, Hurt's
    return makes 16 active.
    il_candidate: Achy, an active player O-tagged now and out (entry) for
    week 2 only -- a legal chat IL placement who returns at week 3."""
    fx = S.Fixture(weeks=WEEKS6)
    for i in range(nick_active):
        fx.player(f"Filler {i}", _every_week(1, 3), 20.0, manager="Nick", keep=0.9 - 0.01 * i)
    if weak:
        fx.player("Weak", _every_week(1), 5.0, manager="Nick", keep=weak_keep)
    if il_candidate:
        fx.player("Achy", _every_week(0, 2, 4), 30.0, manager="Nick", keep=0.02, status="O", out_weeks=[2])
    if hurt:
        fx.player("Hurt", _every_week(*hurt_days), 35.0, manager="Nick", il=True, keep=0.05, status=hurt_tag,
                  out_weeks=list(hurt_out))
        if hurt_return is not None:
            p = fx.proj["Hurt"]
            p.return_date = hurt_return.isoformat()
            p.return_week = next(w for w in WEEKS6 if S.day(w, 0) <= hurt_return <= S.day(w, 6))
    S.opponents_flat(fx, {"Hayden": 18.0, "Benton": 18.0, "Garrett": 18.0})
    for i in range(6):
        fx.player(f"Wire {i}", _every_week(0), 15.0 - i, fa=True)
    fx.player("Add", _every_week(0, 2, 4), 25.0, fa=True)
    return fx


def chat_hz(fx):
    return fx.horizon(S.at(1, 2), S.close_of(1))


def payload(fx, inp):
    adv = av.advise_all(inp, FAST, av.RECOMMENDED)
    return al.latest_payload(run_id="r1", mode="nightly", cause=None, now=S.at(1, 2), inputs=inp,
                             hz=chat_hz(fx) if inp.kind == av.CHAT else
                             av.Horizon(av.MONDAY, tuple(inp.horizon), inp.horizon[0], S.day(inp.horizon[0], 0),
                                        S.close_of(inp.horizon[0])),
                             meta={}, advice=adv, weighting=av.RECOMMENDED.name, settings=FAST, seconds={})


def _chance(keep):
    return lambda x: keep.get(x)


# =============================================================================
# A. the one rule
# =============================================================================

def test_a_protected_low_projection_keeper_is_never_the_activation_drop_in_the_plan():
    """Nick_14 is the lowest projected (26) and the cheapest long-run -- and
    his team's most likely keeper (a young keeper with a low projection, the
    brief's example). The old rule dropped him; the one rule drops Nick_13."""
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-16")      # back at week 5's window
    base = rp.DropContext(config=idr.from_rules(), note=lambda: "no stakes (test)", stakes=None,
                          keep=lambda m: {"Nick_14": 0.99} if m == "Nick" else {}, games=None,
                          availability=None)
    plan = _build(players, rosters, drops=base)
    v = plan[5]["Nick"]
    assert v["activated"] == ["Nick_0"]
    assert v["activation_drops"] == ["Nick_13"] and "Nick_14" in v["active"]
    old = _build(players, rosters)                    # keep all 0: Nick_14 unprotected
    assert old[5]["Nick"]["activation_drops"] == ["Nick_14"]


def test_every_candidate_protected_raises():
    """15 active and 4 protected cannot leave no candidate; a roster that
    does is not one the rule can answer, so it raises."""
    keep = {"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.6}
    with pytest.raises(rp.ActivationError, match="neither protected"):
        rp.activation_drops(manager="Nick", week=5, active=["A", "B", "C", "D", "R"], il=[], back=["R"],
                            n=1, chance=_chance(keep), protected_n=4, value=lambda r: len(r), proj=lambda x: 1.0, band=2.0)


def test_a_returner_is_never_dropped_and_a_stand_in_is_valued_at_his_level():
    """The returner is worth least here and still stays (he is why the team
    activates); a stand-in has no keep chance, so he is never protected, and
    is valued at his level like anyone else: the cheapest goes."""
    pts = {"R": 1.0, "Stand-in (30.0)": 30.0, "X": 31.0, "K": 2.0}
    keep = {"X": 0.1, "K": 0.9, "R": 0.0}            # the stand-in: None
    drops, detail = rp.activation_drops(
        manager="Nick", week=5, active=list(pts), il=[], back=["R"], n=1, chance=_chance(keep),
        protected_n=1, value=lambda r: sum(pts[n] for n in r), proj=lambda x: pts[x], band=2.0)
    assert drops == ["Stand-in (30.0)"] and detail[0]["loss"] == 30.0
    assert detail[0]["next"] == [(31.0, "X")]          # K is protected (top 1), R a returner


def test_ties_go_to_the_lower_projection_then_the_name():
    """Players who never start cost exactly nothing long-run: the measure
    cannot tell them apart, so the lower projection goes, then the name."""
    proj = {"Zed": 5.0, "Abe": 20.0, "Bob": 20.0, "R": 30.0}
    drops, _ = rp.activation_drops(manager="Nick", week=5, active=list(proj), il=[], back=["R"], n=2,
                                   chance=lambda x: 0.0, protected_n=0, value=lambda r: 0.0,
                                   proj=lambda x: proj[x], band=2.0)
    assert drops == ["Zed", "Abe"]


def test_an_activation_over_15_without_the_rules_inputs_raises():
    players, rosters = _league()
    players["Nick_0"] = _p("Nick_0", 40.0, out=[3, 4], ret="2026-11-16")
    with pytest.raises(rp.ActivationError, match="needs a DropContext"):
        _build(players, rosters, drops=None)
    from modules.data_loader import PlayerIndex
    from test_roster_plan import GP, RULES, WINDOWS
    for gone in ("longrun", "config"):
        ctx = replace(activation_ctx(players), **{gone: None})
        with pytest.raises(rp.ActivationError, match="needs a DropContext"):
            rp.build(start_week=2, il_slots={}, rosters=rosters, windows=WINDOWS,
                     players=PlayerIndex(players), statuses={n: "HEALTHY" for n in players},
                     rules=RULES, standin_gp=GP, drops=ctx)


def test_the_protected_count_is_advices():
    """The plan protects injured_drop.protected_keepers, advice Settings.protected: one number."""
    assert av.Settings().protected == idr.from_rules().protected_keepers == 4


# =============================================================================
# B. the plan and advice: one answer
# =============================================================================

def test_the_plan_and_advice_choose_the_same_player_on_the_same_roster():
    """On the chat fixture the plan activates Hurt at week 2 and drops one
    player. (1) Advice's step IS the plan's activation. (2) The measure is
    advice's own: activation_drops valued with advice's V2 follow-up
    valuation (marginal_value on the advice inputs' own context, _week_points
    over the window through the stakes' last week) picks the same player, and
    LongRun's numbers equal it for every candidate."""
    fx = returner_fixture()
    inp = chat_inputs(fx)
    P0 = av._plan(inp)
    step = av.activation_step(inp, "Nick")
    v = P0[2]["Nick"]
    assert step["back"] == v["activated"] == ["Hurt"] and step["drops"] == v["activation_drops"]
    weeks = rp.longrun_weeks(2, inp.stakes["Nick"])
    assert weeks == [2, 3, 4, 5, 6]
    import numpy as np
    from modules import marginal_value as mv
    ctx = av._later_ctx(inp, weeks, av.Settings().long_sims, av.Settings().seed, [P0])

    def advice_value(r):                        # advice's own valuation, per simulation (44b s.1)
        assert all(ctx.players.canonical(n) is not None for n in r)
        bw = mv.roster_totals(ctx, list(r))[2]
        return sum(np.asarray(bw[w], dtype=float) for w in weeks)
    active = P0[1]["Nick"]["active"] + ["Hurt"]
    keep = dict(inp.managers["Nick"].keep)
    picked, detail = rp.activation_drops(manager="Nick", week=2, active=active, il=[], back=["Hurt"], n=1,
                                         chance=_chance(keep), protected_n=4, value=advice_value,
                                         proj=lambda x: inp.projection(x).effective_fppg,
                                         band=rp.longrun_rules()["band"])
    assert picked == step["drops"]
    lr = inp.plan.args["drops"].longrun
    assert av.Settings().long_sims == rp.longrun_rules()["sims"] == 200
    for x in [n for n in active if n != "Hurt"]:
        r = [n for n in active if n != x]
        assert np.allclose(lr(r, weeks, inp.projection), advice_value(r), atol=1e-9), x


def test_a_protected_low_projection_keeper_is_never_the_activation_drop_in_advice():
    """Weak (5 FPPG, worth nothing long-run) is Nick's most likely keeper:
    the step drops someone else, and no move, backup or follow-up names him."""
    fx = returner_fixture(weak_keep=0.99, il_candidate=True, nick_active=13)
    inp = chat_inputs(fx)
    step = av.activation_step(inp, "Nick")
    assert step["back"] == ["Hurt"] and "Weak" not in step["drops"]
    prot = av.protected(inp.managers["Nick"], 4)
    assert "Weak" in prot and not set(step["drops"]) & prot
    rec = av.recommend(inp, "Nick", FAST)
    for _s, p in rec.ranked:
        assert p.move.drop not in prot and p.followup_drop not in prot


def test_order_independence_across_managers_still_holds():
    """The plan's activation values each team's own roster (keyed draws), so
    the order the managers are handed in cannot move it."""
    fx = returner_fixture()
    inp = chat_inputs(fx)
    a = av._plan(inp)
    args = dict(inp.plan.args)
    args["rosters"] = dict(reversed(list(args["rosters"].items())))
    args["order"] = list(reversed(MANAGERS))
    b = rp.build(**args)
    assert a == b


def test_the_il_follow_up_is_the_plans_activation_drop():
    """A chat IL placement of Achy (O now, out for week 2 by his entry) with
    the add: the plan brings him back at week 3 and the one rule drops a
    player there. Advice's follow-up is that player -- read off the plan."""
    fx = returner_fixture(il_candidate=True, nick_active=13)
    inp = chat_inputs(fx)
    assert "Achy" in inp.il_eligible
    step = av.activation_step(inp, "Nick")
    mo = av.Move("Nick", "il_add", "Add", to_il="Achy")
    fu = av.followup_drop(inp, "Nick", mo, FAST)
    P = av._plan(inp, av.known_for(mo, 2, step=step))
    assert "Achy" in P[2]["Nick"]["il"] and P[3]["Nick"]["activated"] == ["Achy"]
    assert fu == P[3]["Nick"]["activation_drops"][0]
    p = av.price(inp, "Nick", [mo], FAST)[0]
    assert p.followup_drop == fu and not p.followup_standin


# =============================================================================
# C. advice shows the return (s.3)
# =============================================================================

def test_a_return_at_the_chat_moves_window_is_shown_before_the_pick_everywhere():
    """advice_latest.json's "activation", the history row, the summary line,
    advice_show.py and the hub card: "Hurt is back for week 2: activate him
    and drop X. It costs no add." -- before the move."""
    from scripts import advice_show
    fx = returner_fixture()
    inp = chat_inputs(fx)
    step = av.activation_step(inp, "Nick")
    pl = payload(fx, inp)
    act = pl["managers"]["Nick"]["activation"]
    want = f"Hurt is back for week 2: activate him and drop {step['drops'][0]}. It costs no add."
    assert act == {"week": 2, "back": ["Hurt"], "drops": step["drops"], "returns": {}, "text": want}
    assert all(pl["managers"][m]["activation"] is None for m in MANAGERS if m != "Nick")
    assert al.history_row(pl, published=False)["managers"]["Nick"]["activation"] == act
    line = next(l for l in al.summary_lines(pl) if l.startswith("ADVICE Nick"))
    assert f"Step: {want} Then: " in line
    out = []
    pl.update(published=False)
    advice_show.show(pl, out=out.append)
    i = out.index(f"  Step: {want}")
    assert out[i - 1].startswith("Nick -- ")
    view = al.hub_view(pl, [{"manager": "Nick", "team": "Team Nick"}])
    card = view["cards"][0]
    assert card["step"] == want and card["players"]["step"] == ["Hurt"] + step["drops"]
    from test_advice_live import _page, _view
    _p_, page = _page(view)
    v = _view(page)
    assert "Hurt is back for week 2" in v
    if card["move"]:
        assert v.index("Hurt is back for week 2") < v.index('<div class="ad-m">')


def test_the_pick_is_priced_after_the_step_and_cannot_conflict_with_it():
    """The pick is a move from the roster after the step: it never drops the
    player just activated (nor puts him in IL), never drops the step's drop
    again, never adds him; the step is encoded with the move, so the move's
    plan carries exactly the step at the window. An explicit pick that
    contradicts the step cannot be recommended."""
    fx = returner_fixture(il_candidate=True, nick_active=13)
    inp = chat_inputs(fx)
    step = av.activation_step(inp, "Nick")
    moves = av.candidate_moves(inp, "Nick", FAST)
    assert moves
    for mo in moves:
        assert mo.drop not in step["back"] + step["drops"] and mo.to_il not in step["back"]
        assert mo.add not in step["drops"]
    mo = next(m for m in moves if m.kind == "add_drop")
    P = av._plan(inp, av.known_for(mo, 2, step=step))
    v = P[2]["Nick"]
    assert "Hurt" in v["active"] and not set(step["drops"]) & set(v["active"])
    assert mo.add in v["active"] and mo.drop not in v["active"]
    assert not v.get("activated") and not v.get("activation_drops"), "the step was applied as known moves"
    with pytest.raises(ValueError, match="not in an IL slot"):        # the plan refuses it
        av.price(inp, "Nick", [av.Move("Nick", "add_drop", "Add", drop="Hurt")], FAST)
    good = av.price(inp, "Nick", [mo], FAST)[0]
    for bad in (av.Move("Nick", "add_drop", mo.add, drop="Hurt"),
                av.Move("Nick", "add_drop", step["drops"][0], drop=mo.drop)):
        with pytest.raises(AssertionError, match="conflicts with the activation step"):
            av.recommend(inp, "Nick", FAST, priced=[replace(good, move=bad)])


def test_no_return_changes_nothing_in_the_output():
    fx = returner_fixture(hurt=False)
    inp = chat_inputs(fx)
    assert all(av.activation_step(inp, m) is None for m in MANAGERS)
    pl = payload(fx, inp)
    assert all(e["activation"] is None for e in pl["managers"].values())
    assert not any("Step:" in l for l in al.summary_lines(pl))
    from scripts import advice_show
    out = []
    pl.update(published=False)
    advice_show.show(pl, out=out.append)
    assert not any("Step:" in l for l in out)
    assert all(c["step"] == "" for c in al.hub_view(pl, [{"manager": m, "team": m} for m in MANAGERS])["cards"])


def test_a_monday_move_before_the_close_shows_the_step():
    """Case 10 (44b s.2): a Monday move is before the window's close, when the
    plan's start week is an OPEN window: the plan activates Hurt there (with
    the one rule's drop), so the Monday move shows the step, and the pick is
    priced after it. (44a showed none: the start week was locked.) Hurt is
    tagged Q today, as Benton's Reaves is: 44c holds an O/OFS-tagged
    occupant with no entry in IL at the open window (tests/test_44c_il_fixes)."""
    fx = returner_fixture(hurt_tag="Q")
    inp = fx.inputs(horizon=(2, 3), balance=False)
    assert inp.kind == av.MONDAY and inp.plan.args["start_week"] == 2
    assert inp.plan.args["open_day"] == S.day(2, 0)
    step = av.activation_step(inp, "Nick")
    assert step["week"] == 2 and step["back"] == ["Hurt"] and step["drops"] == ["Weak"]
    P0 = av._plan(inp)
    assert "Hurt" in P0[2]["Nick"]["active"] and not P0[2]["Nick"]["il"]
    for mo in av.candidate_moves(inp, "Nick", FAST):
        assert mo.drop not in ("Hurt", "Weak") and mo.to_il != "Hurt"


def test_an_il_occupant_with_no_entry_is_back_at_the_next_window():
    """Case 3: the plan's own availability rule -- no injury entry, so he is
    available from the next window (an O tag is at most 3 games): the step is
    shown for him. (The brief presumed nothing would show; raised.)"""
    fx = returner_fixture()
    inp = chat_inputs(fx)
    assert inp.status("Hurt") == "O" and not fx.proj["Hurt"].out_weeks
    assert av.activation_step(inp, "Nick")["back"] == ["Hurt"]


def test_an_entry_return_before_the_window_is_shown_and_a_midweek_one_waits():
    """Case 1: an entry out for week 1 only: back for week 2's window, shown.
    Case 2 (44b s.4): an entry returning on week 2's Wednesday. His games are
    Saturday and Sunday, so activating him at week 2's window loses him
    nothing and costs nothing (Weak's long-run value is 0): the plan activates
    him early, and advice shows it as the step. With Monday and Tuesday games
    he would miss all of week 2: activating early gains exactly nothing, a
    tie, which keeps him in IL until week 3."""
    fx = returner_fixture(hurt_out=[1])
    assert av.activation_step(chat_inputs(fx), "Nick")["back"] == ["Hurt"]
    fx = returner_fixture(hurt_out=[1], hurt_return=S.day(2, 2))
    inp = chat_inputs(fx)
    step = av.activation_step(inp, "Nick")
    assert step["back"] == ["Hurt"] and step["drops"] == ["Weak"]
    assert av._plan(inp)[2]["Nick"]["midweek"][0]["activate"] is True
    fx = returner_fixture(hurt_out=[1], hurt_return=S.day(2, 2), hurt_days=(0, 1))
    inp = chat_inputs(fx)
    assert av.activation_step(inp, "Nick") is None
    P0 = av._plan(inp)
    assert P0[2]["Nick"]["midweek"][0]["activate"] is False
    assert "Hurt" in P0[2]["Nick"]["il"] and P0[3]["Nick"]["activated"] == ["Hurt"]


# =============================================================================
# D. the real plan, unstubbed (the changed run path)
# =============================================================================

def test_the_real_plans_activation_drops_are_the_one_rules():
    """roster_plan.for_run on the real state, nothing stubbed: the keeper
    watch, the stakes file and the run's LongRun. Every activation drop is
    neither protected (top 4 by the keeper watch) nor a returner, recomputing
    the one rule with the run's own inputs gives the same players, and the
    plan is the same whatever order the managers come in. Skips without this
    week's IL file."""
    from modules import data_loader as dl, tag_records
    from modules.projections import load_all_team_projections
    data = dl.load_all_data(ROOT)
    try:
        rp.load_il_slots(ROOT, data)
    except rp.ILSlotsError as e:
        pytest.skip(f"needs this week's IL file: {e}")
    tags = tag_records.as_tags(tag_records.latest(ROOT))
    teams = load_all_team_projections(data)
    run = rp.for_run(data, teams, tags)
    drops = run.args["drops"]
    seen = 0
    for w in sorted(run.plan):
        for m, v in run.plan[w].items():
            if not v.get("activation_drops"):
                continue
            seen += 1
            keep = dict(drops.keep(m))
            prot = rp.protected_players([n for n in keep], lambda x: keep.get(x), 4)
            assert not set(v["activation_drops"]) & set(prot), (w, m)
            assert not set(v["activation_drops"]) & set(v["activated"]), (w, m)
    # (11-12's state has six: Benton, Hayden twice, Nick twice, Garrett; a later state may have none)
    data.__dict__.pop("_roster_plans", None)
    rev = rp.for_run(data, dict(reversed(list(teams.items()))), tags)
    assert {w: {m: (v["active"], v["il"], v.get("activation_drops")) for m, v in wk.items()}
            for w, wk in rev.plan.items()} == \
        {w: {m: (v["active"], v["il"], v.get("activation_drops")) for m, v in wk.items()}
         for w, wk in run.plan.items()}
