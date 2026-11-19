"""
tests/test_advice_hold.py -- H54: holding a returner in IL for one week
(claude/HANDOFF_54_HOLD_IN_IL_2026-11-19.md; advice_v2.price_hold,
choose_il), beside H53's tests/test_advice_plan.py and 4c3's
tests/test_advice_activation.py.

THE THREE OPTIONS for a manager with a returner at this horizon's window,
each priced against C:
    A  activate now: the activation step and the plan's steps (H53, 4c3);
    B  keep the returners in IL at this window (no move at all, rule 3) and
       let the plan's own rule activate them -- and drop whom it drops -- at
       the next window;
    C  do nothing through the horizon (4c3's baseline).
B is the plan only when its score beats A's by more than settings.hold_bar.

A. The fixtures: B wins (a negative activation, no adds left); A wins because
   B blocks a valuable step; A wins on its own; B can win over a plan WITH a
   step (the evidence for "no special rule"); two returners held together; an
   early returner; no next window (B not offered); a known move at the window
   (B not offered).
B. Telescoping: B against C is its own pricing, and B minus A equals B priced
   directly against A's plan.
C. The margin.
D. Determinism and manager order.
E. The displays: the live card's hold sentence, the v2 hold row, the rest of
   the view byte-identical when A wins, a file from before 54, advice_show,
   the history row, the run log.
F. The real state (slow; skipped without it): A, B and C priced for every
   manager with a returner, the choice made, nothing raises.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

import advice_v2_scenarios as S
import hub_v2_market_fixture as MF
from modules import advice_live as al
from modules import advice_v2 as av
from test_advice_activation import negative_fixture
from test_advice_v2 import FAST, WEEKS6, _every_week
from test_il_returns import returner_fixture, chat_hz

ROOT = Path(__file__).resolve().parent.parent


def _inp(fx, **kw):
    """The chat move of week 1 (horizon weeks 2-3), with the matchups made
    close (balance) so a win-chance change is visible."""
    return fx.inputs(now=S.at(1, 2), close=S.close_of(1), balance=True, **kw)


def _plan(inp, m="Nick", steps=2):
    return av.plan_for(inp, m, FAST, av.RECOMMENDED, steps)


def _payload(inp, fx):
    adv = av.advise_all(inp, FAST, av.RECOMMENDED, max_steps=2)
    return al.latest_payload(run_id="r54", mode="nightly", cause=None, now=S.at(1, 2), inputs=inp, hz=chat_hz(fx),
                             meta={}, advice=adv, weighting=av.RECOMMENDED.name, settings=FAST, seconds={})


def _with(extra):
    fx = negative_fixture()
    extra(fx)
    return fx


def star(fx):
    """A free agent who plays every night: a step worth far more than the hold."""
    fx.player("Star", _every_week(0, 1, 2, 3, 4, 5, 6), 30.0, fa=True)


def twice(fx):
    """A free agent two nights a week at 11 FPPG for a 20-FPPG one-nighter:
    a step that beats standing pat by a little."""
    fx.player("Twice", _every_week(0, 3), 11.0, fa=True)


def second_returner(fx):
    """Hurt 2: in Nick's other IL slot, back at week 2's window, no game in week 2."""
    fx.player("Hurt 2", [(w, d) for w in WEEKS6 if w != 2 for d in (4, 6)], 33.0, manager="Nick", il=True,
              keep=0.04, status="O")


# =============================================================================
# A. the fixtures
# =============================================================================

@pytest.mark.slow
def test_b_wins_a_negative_activation_with_no_adds_left():
    """negative_fixture: Hurt's team has no game in week 2, so activating him
    costs Weak's week-2 starts. Held one week, nothing changes in week 2 (C's
    roster exactly) and week 3 is A's roster exactly."""
    inp = _inp(negative_fixture(), adds={"Nick": 0})
    pl = _plan(inp)
    il, a, h = pl.il, pl.activation, pl.il.hold
    assert not pl.steps and pl.total is None and h is not None
    assert a.dwp[0] < -0.02 and il.choice == "hold" and pl.held and pl.adds == []
    assert h.dwp[0] == 0.0 and h.dpts[0] == 0.0 and h.dstarts[0] == 0.0     # week 2: C's roster
    assert h.dwp[1] == a.dwp[1] and h.dpts[1] == pytest.approx(a.dpts[1], abs=1e-9)   # week 3: A's roster
    assert h.next_week == 3 and h.next_drops == ("Weak",) and h.next_day == S.day(3, 0)
    assert il.margin == pytest.approx(il.b_score - il.a_score) and il.margin > FAST.hold_bar
    adv = av.advise_all(inp, FAST, av.RECOMMENDED, max_steps=2)["Nick"]
    assert adv.top is None and adv.backup is None and adv.plan.held


@pytest.mark.slow
def test_a_wins_because_b_blocks_a_valuable_step():
    """The same negative activation, but Star is on the wire and Nick has
    adds: B beats the activation ALONE, yet A (the activation and the step)
    beats B, because B blocks the step this window."""
    inp = _inp(_with(star))
    pl = _plan(inp)
    il = pl.il
    assert [s.priced.move.add for s in pl.steps] == ["Star"]
    assert il.choice == "activate" and il.hold is not None
    assert av.option_key(av.RECOMMENDED, il.hold)[0] > av.option_key(av.RECOMMENDED, pl.activation)[0]
    assert il.a_score == av.option_key(av.RECOMMENDED, pl.total)[0] > il.b_score
    assert pl.adds == ["Star"]


@pytest.mark.slow
def test_a_wins_on_its_own():
    """returner_fixture: Hurt plays in week 2; activating him now is better
    in week 2 and the same in week 3."""
    pl = _plan(_inp(returner_fixture(), adds={"Nick": 0}))
    il = pl.il
    assert pl.activation.dwp[0] > 0 and il.choice == "activate" and il.margin < 0
    assert il.hold.dwp[0] == 0.0


@pytest.mark.slow
def test_b_can_win_over_a_plan_with_a_step():
    """The handoff asked whether B ever wins when the plan has steps. It can:
    a step that beats standing pat by less than the activation's week-2 cost.
    No special rule: the comparison is A's WHOLE plan against B."""
    fx = _with(twice)
    inp = _inp(fx)
    pl = _plan(inp)
    assert [s.priced.move.add for s in pl.steps] == ["Twice"] and pl.steps[0].score > 0
    assert pl.il.choice == "hold" and pl.held and pl.adds == []
    assert pl.il.a_score == av.option_key(av.RECOMMENDED, pl.total)[0]
    e = _payload(inp, fx)["managers"]["Nick"]
    assert e["il_choice"]["choice"] == "hold" and e["il_choice"]["against"] == "plan_total"
    assert e["move"] is None and e["plan"] == [] and e["plan_total"] is None and e["backup"] is None
    assert [d["add"] for d in e["activate_plan"]] == ["Twice"] and e["activate_total"]["includes_activation"]
    assert e["plan_stop"]["code"] == "hold" and e["empty"] == "Keeping him in IL blocks every move this window"
    assert e["v2_empty"] == ""


@pytest.mark.slow
def test_two_returners_are_held_together_and_both_come_back_at_the_next_window():
    """Rule 3: holding either blocks every move, so B holds them all (one
    plan, not each subset)."""
    inp = _inp(_with(second_returner), adds={"Nick": 0})
    step = av.activation_step(inp, "Nick")
    assert sorted(step["back"]) == ["Hurt", "Hurt 2"] and len(step["drops"]) == 2
    pl = _plan(inp)
    h = pl.il.hold
    assert sorted(h.step["back"]) == ["Hurt", "Hurt 2"] and len(h.next_drops) == 2
    P = av._plan(inp, av.hold_one_known(inp, "Nick", step))
    assert sorted(P[2]["Nick"]["held"]) == ["Hurt", "Hurt 2"] and sorted(P[3]["Nick"]["activated"]) == ["Hurt", "Hurt 2"]
    assert pl.il.choice == "hold"
    assert al.hold_text({"back": ["Hurt", "Hurt 2"], "week": 2, "next_week": 3, "next_day": S.day(3, 0).isoformat()}) \
        == f"Keep Hurt and Hurt 2 in IL for week 2 and activate them at week 3's window ({S.day(3, 0):%a %m-%d}). " \
           "It blocks your moves this window."


@pytest.mark.slow
def test_an_early_returner_held_this_window_is_activated_at_the_next():
    """44c s.2.1: back on week 2's Wednesday, activated early at its window
    by A. Held, he comes back at week 3's window, as any returner."""
    inp = _inp(returner_fixture(hurt_out=[1], hurt_return=S.day(2, 2)), adds={"Nick": 0})
    step = av.activation_step(inp, "Nick")
    assert step["returns"] == {"Hurt": S.day(2, 2).isoformat()}
    h = _plan(inp).il.hold
    assert h is not None and h.next_week == 3 and h.dwp[0] == 0.0
    P = av._plan(inp, av.hold_one_known(inp, "Nick", step))
    assert P[2]["Nick"]["held"] == ["Hurt"] and "Hurt" in P[3]["Nick"]["activated"]


@pytest.mark.slow
def test_no_next_window_in_the_horizon_means_no_b():
    """A chat move in week 5 of a six-week season: the horizon is (6, None)."""
    rot = {"Nick": "Hayden", "Hayden": "Nick", "Benton": "Garrett", "Garrett": "Benton"}
    inp = negative_fixture().inputs(now=S.at(5, 2), close=S.close_of(5), balance=False, adds={"Nick": 0},
                                    opponents={m: {w: rot[m] for w in WEEKS6} for m in rot})
    assert tuple(inp.horizon) == (6, None) and av.activation_step(inp, "Nick") is not None
    il = _plan(inp).il
    assert il.hold is None and il.choice == "activate" and il.why_not == "no next window in the horizon"


@pytest.mark.slow
def test_a_known_move_of_his_at_the_window_means_no_b():
    """A pending claim of his at this window: a held healthy player would
    block it (rule 3), so B is not offered (never priced with the claim)."""
    inp = _inp(negative_fixture(), adds={"Nick": 0})
    step = av.activation_step(inp, "Nick")
    known = {2: {"Nick": {"il_place": [], "drop": ["Filler 13"], "add": ["Wire 0"], "il_activate": []}}}
    other = replace(inp, plan=av.PlanSpec({**inp.plan.args, "known": known}))
    assert "known move of his" in av.hold_offer(other, "Nick", step)
    assert av.hold_offer(inp, "Nick", step) == ""
    hayden = {2: {"Hayden": {"il_place": [], "drop": [], "add": [], "il_activate": []}}}
    assert av.hold_offer(replace(inp, plan=av.PlanSpec({**inp.plan.args, "known": hayden})), "Nick", step) == ""
    assert av.hold_offer(inp, "Nick", None) == "no returner at this window"


# =============================================================================
# B. telescoping
# =============================================================================

@pytest.mark.slow
def test_b_against_c_is_its_own_pricing_and_b_minus_a_is_b_against_a():
    inp = _inp(_with(star))
    pl = _plan(inp)
    a, t, h = pl.activation, pl.total, pl.il.hold
    step = a.step
    # A's activation + steps = A's total against C (4c3/H53, here with B beside it)
    rows = [a] + [s.priced for s in pl.steps]
    for k in (0, 1):
        assert sum(r.dwp[k] for r in rows) == pytest.approx(t.dwp[k], abs=1e-9)
    # B against C, by hand: B's plan, C's base
    C = av._hold_plan(inp, "Nick", step)
    B = av._plan(inp, av.hold_one_known(inp, "Nick", step))
    bc = av._price_base(inp, "Nick", FAST, base_plan=C)
    r = av._measure(inp, "Nick", FAST, bc, B)
    assert r["dwp"] == h.dwp and r["dpts"] == h.dpts and r["dstarts"] == h.dstarts
    assert h.wp_base == a.wp_base == t.wp_base
    # B against A's plan, priced directly = B's numbers minus A's
    known = av.merge_known(*[av.known_for(s.priced.move, 2, s.priced.followup_drop, 3,
                                          step=step if k == 0 else None) for k, s in enumerate(pl.steps)])
    ba = av._price_base(inp, "Nick", FAST, base_plan=av._plan(inp, known))
    d = av._measure(inp, "Nick", FAST, ba, B)
    for k in (0, 1):
        assert d["dwp"][k] == pytest.approx(h.dwp[k] - t.dwp[k], abs=1e-12)
        assert d["dpts"][k] == pytest.approx(h.dpts[k] - t.dpts[k], abs=1e-9)
    fx = _with(star)
    e = _payload(_inp(fx), fx)["managers"]["Nick"]
    vs = e["hold"]["vs_activate"]
    assert vs["dwp"] == [round(x - y, 6) for x, y in zip(h.dwp, t.dwp)]
    assert e["hold"]["chosen"] is False and e["il_choice"]["choice"] == "activate"


# =============================================================================
# C. the margin
# =============================================================================

def _act(dwp, dpts=(1.0, 1.0)):
    return av.ActivationPriced({"week": 2, "back": ["Hurt"], "drops": ["Weak"]}, tuple(dwp), (0.5, 0.5), tuple(dpts),
                               (0.0, 0.0), 0.0, 0.0, 0.0, 1.0)


def _hold(dwp, dpts=(1.0, 1.0)):
    from datetime import date
    return av.HoldPriced({"week": 2, "back": ["Hurt"], "drops": ["Weak"]}, 3, date(2026, 11, 30), ("Weak",),
                         tuple(dwp), (0.5, 0.5), tuple(dpts), (0.0, 0.0), 0.0, 0.0, 0.0, 1.0)


def test_b_below_the_margin_is_not_recommended():
    s = av.Settings()
    assert s.hold_bar == 0.01
    # today's Benton, in shape: B beats A by 0.004 -> A stays
    c = av.choose_il(_act((-0.004, 0.048)), _hold((0.0, 0.048)), "", s, av.RECOMMENDED)
    assert c.choice == "activate" and c.margin == pytest.approx(0.004)
    assert av.choose_il(_act((-0.02, 0.048)), _hold((0.0, 0.048)), "", s, av.RECOMMENDED).choice == "hold"
    # just under the bar: A (activation is the default action); just over: B
    under = av.choose_il(_act((-0.0099, 0.05)), _hold((0.0, 0.05)), "", s, av.RECOMMENDED)
    assert under.margin == pytest.approx(0.0099) and under.choice == "activate"
    assert av.choose_il(_act((-0.0101, 0.05)), _hold((0.0, 0.05)), "", s, av.RECOMMENDED).choice == "hold"
    # a flat horizon (the matchups decided) cannot tell them apart on win chance: A, whatever the points
    flat = av.choose_il(_act((0.0, 0.0), (-30.0, 0.0)), _hold((0.0, 0.0), (0.0, 0.0)), "", s, av.RECOMMENDED)
    assert flat.choice == "activate" and flat.margin == 0.0
    # with a zero bar the same Benton-shaped case holds him
    assert av.choose_il(_act((-0.004, 0.048)), _hold((0.0, 0.048)), "", replace(s, hold_bar=0.0),
                        av.RECOMMENDED).choice == "hold"
    none = av.choose_il(_act((-0.5, 0.0)), None, "no next window in the horizon", s, av.RECOMMENDED)
    assert none.choice == "activate" and none.margin is None and none.b_score is None


# =============================================================================
# D. determinism and manager order
# =============================================================================

@pytest.mark.slow
def test_the_choice_is_the_same_in_any_manager_order_and_on_fresh_inputs():
    fx = _with(twice)
    a = av.advise_all(_inp(fx), FAST, av.RECOMMENDED, max_steps=2)
    inp = _inp(_with(twice))
    rev = {m: av.plan_for(inp, m, FAST, av.RECOMMENDED, 2) for m in sorted(inp.managers, reverse=True)}
    assert rev["Nick"].il == a["Nick"].plan.il
    assert av.advise_all(_inp(_with(twice)), FAST, av.RECOMMENDED, max_steps=2)["Nick"].plan.il == a["Nick"].plan.il
    # the contest reads the chosen plan: a hold adds nobody this window
    assert a["Nick"].plan.adds == [] and "Nick" not in av.also_wanted(a, "Hayden", "Twice")


# =============================================================================
# E. the displays
# =============================================================================

@pytest.mark.slow
def test_the_live_card_the_summary_advice_show_and_history_when_b_wins():
    from scripts import advice_show
    fx = negative_fixture()
    inp = _inp(fx, adds={"Nick": 0})
    pl = _payload(inp, fx)
    e = pl["managers"]["Nick"]
    h = e["hold"]
    nxt = S.day(3, 0)
    assert h["text"] == (f"Keep Hurt in IL for week 2 and activate him at week 3's window ({nxt:%a %m-%d}). "
                         "It blocks your moves this window.")
    assert ", against activating now" in h["texts"]["numbers"] and h["texts"]["numbers"].startswith("+")
    assert h["texts"]["numbers"] == al.hold_numbers_text(h["vs_activate"], pl["horizon"], e["opponents"],
                                                         show_title=pl["show_title_odds"])
    assert e["activation"]["step"] == 0 and e["activation"]["dwp"][0] < 0       # A's step kept as it is
    card = al.hub_view(pl, [{"manager": "Nick", "team": "Team Nick"}])["cards"][0]
    assert card["step"] == h["text"] and card["step_numbers"] == h["texts"]["numbers"]
    assert card["players"]["step"] == ["Hurt"] and card["move"] == "" and card["backup"] == ""
    assert card["empty"] == "No adds left this week (week 1's budget)"
    line = next(x for x in al.summary_lines(pl) if x.startswith("ADVICE Nick"))
    assert f"Step: {h['text']} ({h['texts']['numbers']}) Then: No adds left" in line
    hist = al.history_row(pl, published=False)["managers"]["Nick"]
    assert hist["il_choice"]["choice"] == "hold" and hist["hold"]["dwp"] == h["dwp"]
    assert "texts" not in hist["hold"] and "text" not in hist["hold"]
    assert hist["hold"]["vs_activate"] == h["vs_activate"] and hist["activate_plan"] == []
    out = []
    pl.update(published=False)
    advice_show.show(pl, out=out.append)
    txt = "\n".join(out)
    assert f"  Step: {h['text']}" in out
    for want in ("    A. Activate now: ", "    B. Keep in IL for week 2, activate at week 3's window",
                 "    C. Keep in IL through the horizon, no move: win chance ", "    Chosen: B, keep him in IL",
                 "    B against A: "):
        assert want in txt, want


@pytest.mark.slow
def test_advice_show_and_history_when_a_wins_keep_b_off_the_hub():
    from scripts import advice_show
    fx = _with(star)
    inp = _inp(fx)
    pl = _payload(inp, fx)
    e = pl["managers"]["Nick"]
    assert e["il_choice"]["choice"] == "activate" and e["hold"]["chosen"] is False
    assert e["move"]["add"] == "Star" and "activate_plan" not in e
    card = al.hub_view(pl, [{"manager": "Nick", "team": "Team Nick"}])["cards"][0]
    assert card["step"] == e["activation"]["text"]                               # A, as today
    assert "against activating now" not in json.dumps(card)
    hist = al.history_row(pl, published=False)["managers"]["Nick"]
    assert hist["hold"]["dwp"] == e["hold"]["dwp"] and hist["il_choice"]["choice"] == "activate"
    assert "activate_plan" not in hist
    out = []
    pl.update(published=False)
    advice_show.show(pl, out=out.append)
    txt = "\n".join(out)
    assert "    A. Activate now + 1 step(s): " in txt and "    Chosen: A, activate now -- B trails A by " in txt


def _hold_file(chosen: bool, *, show_title: bool = True) -> dict:
    """The market fixture's file, Marcus given option B's numbers (vs C) and
    the choice; the texts by advice_live's own function."""
    adv = MF.advice_latest(show_title=show_title)
    e = adv["managers"]["Marcus"]
    a = e["plan_total"]
    d = {"offered": True, "kind": "hold", "baseline": "hold", "week": 10, "back": ["Marcus Hurt"], "next_week": 11,
         "next_day": "2026-12-14", "next_drops": ["Marcus Bench"], "next_standins": [], "dwp": [0.0, 0.053],
         "wp_base": [0.44, 0.47], "dpts": [0.0, 30.5], "dstarts": [0.0, 0.9], "dT_horizon": 0.002, "dT_later": 0.0,
         "dT_rs": 0.002, "dT_po": 0.0, "dpts_later": 0.0, "flat": False, "title_odds": 0.004,
         "title_label": "title odds", "score": 0.053, "chosen": chosen}
    vs = {k: [round(x - y, 6) for x, y in zip(d[k], a[k])] for k in ("dwp", "dpts", "dstarts")}
    vs.update({k: round(d[k] - a[k], 6) for k in ("dT_horizon", "dT_later", "dT_rs", "dT_po", "dpts_later")},
              flat=False, title_odds=round(d["title_odds"] - a["title_odds"], 6), title_label="title odds")
    d["vs_activate"] = vs
    al.with_hold_texts(d, adv["horizon"], e["opponents"], show_title=show_title)
    e["hold"] = d
    e["il_choice"] = {"choice": "hold" if chosen else "activate", "offered": True, "why_not": "",
                      "against": "plan_total", "activate_score": 0.26, "hold_score": 0.053,
                      "margin": 0.053 - 0.26, "bar": 0.01}
    if chosen:
        e["activate_plan"], e["activate_total"] = e["plan"], e["plan_total"]
        e.update(plan=[], move=None, plan_total=None, backup=None, plan_stop={"code": "hold", "text": "x"},
                 empty="Keeping him in IL blocks every move this window", v2_empty="")
    return adv


def _render(adv):
    from test_hub_v2 import render
    from test_hub_v2_market import _payload as mp
    return render(mp(advice=adv))


def test_the_v2_hold_row_label_no_minus_and_numbers_against_activating_now():
    from test_hub_v2_market import _card
    from test_hub_v2 import visible_text
    adv = _hold_file(True)
    c = _card(_render(adv), "Marcus")
    h = adv["managers"]["Marcus"]["hold"]
    assert c.count("adv-row--il") == 1 and "Keep in IL this week \u00b7 no moves" in c and "&#8634;" in c
    assert "Activate from IL" not in c
    row = c[c.index("adv-row--il"):c.index("</button>", c.index("adv-row--il"))]
    assert "<b>Marcus Hurt</b>" in row and "adv-down" not in row and "Marcus Bench" not in row
    assert "activate at week 11\u2019s window" in visible_text(row)
    for w in h["texts"]["v2"]["weeks"]:
        assert f'>{w["value"]}</span>' in row
    assert h["texts"]["v2"]["weeks"][0]["value"].startswith("\u2212")       # vs activating now, not vs C
    det = c[c.index('class="adv-det"'):]
    assert "Against activating him now:" in visible_text(det) and "Marcus Bench" in visible_text(det)
    assert 'aria-label="Step 1"' not in c and 'class="adv-plan"' not in c and 'class="adv-bk"' not in c
    assert "adv-then" not in c and "adv-empty" not in c          # 2 adds left: the hold row alone
    adv0 = _hold_file(True)
    adv0["managers"]["Marcus"]["adds_left"] = 0
    c0 = _card(_render(adv0), "Marcus")
    assert "No adds left. Resets Monday." in visible_text(c0)


def test_the_rest_of_the_view_is_byte_identical_when_a_wins_and_a_pre_54_file_renders():
    from test_hub_v2_market import _pane
    old = _pane(_render(MF.advice_latest()), "advice")
    assert _pane(_render(_hold_file(False)), "advice") == old     # B's numbers are in the file, not the view
    assert "against activating now" not in old.lower() and "Keep in IL" not in old


def test_the_live_card_changes_only_where_b_wins():
    from test_advice_live import _page, _view
    rows = [{"manager": m, "team": t} for m, t in (("Marcus", "Team M"), ("Tyler", "Team T"),
                                                    ("Dana", "Team D"), ("Jordan", "Team J"))]
    base = MF.advice_latest()
    assert al.hub_view(_hold_file(False), rows) == al.hub_view(base, rows)
    assert _view(_page(al.hub_view(_hold_file(False), rows))[1]) == _view(_page(al.hub_view(base, rows))[1])
    held = al.hub_view(_hold_file(True), rows)
    cm = held["cards"][0]
    h = _hold_file(True)["managers"]["Marcus"]["hold"]
    assert cm["step"] == h["text"] and cm["step_numbers"] == h["texts"]["numbers"] and cm["move"] == ""
    assert cm["empty"] == "Keeping him in IL blocks every move this window"
    assert held["cards"][1:] == al.hub_view(base, rows)["cards"][1:]
    v = _view(_page(held)[1])
    assert "Keep Marcus Hurt in IL for week 10" in v and "against activating now" in v


def test_a_file_from_before_54_prints_and_logs_as_before():
    from scripts import advice_show
    blob = MF.advice_latest()
    assert "il_choice" not in blob["managers"]["Marcus"]
    out = []
    advice_show.show(dict(blob, published=False), out=out.append)
    assert not any("IL options" in x for x in out)
    hist = al.history_row(blob, published=False)["managers"]["Marcus"]
    assert "il_choice" not in hist and "hold" not in hist


def test_the_run_log_records_the_holds_seconds(monkeypatch, tmp_path):
    import types
    hz = av.Horizon(av.CHAT, (2, 3), 1, S.day(2, 0), S.close_of(1))

    def fake_build(base, now, data=None):
        return types.SimpleNamespace(), hz, {"week_first_day": S.day(1, 0).isoformat()}

    def fake_advise(inp, settings, weighting, max_steps=None, timings=None):
        timings["Nick"] = {"steps": [2.5], "total": 0.1, "activation": 1.2, "hold": 0.4}
        return {}

    def fake_latest(**kw):
        return {"schema": al.SCHEMA, "run_id": "r", "mode": "nightly", "cause": None, "cause_text": "c",
                "as_of": "a", "league_day": "d", "horizon": {"label": "Chat move", "weeks": [2, 3]},
                "managers": {}, "error": None, "updated_text": "u", "inputs": {}}
    monkeypatch.setattr(al, "build", fake_build)
    monkeypatch.setattr(av, "advise_all", fake_advise)
    monkeypatch.setattr(al, "latest_payload", fake_latest)
    monkeypatch.setattr(al, "write", lambda *a, **k: None)
    monkeypatch.setattr(al, "plan_steps_max", lambda cfg=None: 2)
    out = al.run_step(tmp_path, S.at(1, 2), run_id="r", mode="nightly", cause=None)
    assert out["block"]["seconds"]["hold"] == {"Nick": 0.4}
    assert "Nick act 1.2+hold 0.4+2.5" in out["detail"]


# =============================================================================
# F. the real state (slow; skipped without it)
# =============================================================================

REAL = [ROOT / "output" / "tag_records.jsonl", ROOT / "output" / "stakes.json", ROOT / "config" / "ROSTERS.json",
        ROOT / "data" / "PLAYERLIST.xlsx", ROOT / "data" / "IL_SLOTS.json"]


@pytest.mark.slow
@pytest.mark.skipif(not all(p.is_file() for p in REAL), reason="needs the league's real state")
def test_the_real_state_prices_a_b_and_c_for_every_returner():
    """Read in place (nothing written), at the latest tag fetch's clock:
    every manager with a returner at the window gets A, B (or the reason it
    is not offered) and C; B's numbers minus A's are its vs-activate numbers;
    the choice follows the bar; nothing raises. Prints the day's case."""
    import contextlib
    import io
    from datetime import datetime, timedelta
    from modules import tag_records
    now = datetime.fromisoformat(tag_records.latest(ROOT)["taken_at"]) + timedelta(minutes=1)
    with contextlib.redirect_stdout(io.StringIO()):
        inp, hz, _meta = al.build(ROOT, now)
    if inp is None:
        pytest.skip("no window left this season")
    settings = av.Settings()
    who = [m for m in sorted(inp.managers) if av.activation_step(inp, m) is not None]
    if not who:
        pytest.skip("nobody has a returner at this window today")
    for m in who:
        pl = av.plan_for(inp, m, settings, av.RECOMMENDED, al.plan_steps_max())
        il, a = pl.il, pl.total if pl.steps else pl.activation
        assert il is not None and pl.activation is not None, m
        assert il.a_score == av.option_key(av.RECOMMENDED, a)[0]
        if il.hold is None:
            assert il.why_not and il.choice == "activate"
            print(f"{m}: B not offered ({il.why_not})")
            continue
        h = il.hold
        assert h.wp_base == pl.activation.wp_base                             # one C for both
        assert h.dwp[0] == 0.0                                                 # week 1: C's roster
        assert il.choice == ("hold" if il.margin > settings.hold_bar else "activate")
        print(f"{m}: A {[round(x, 4) for x in a.dwp]} B {[round(x, 4) for x in h.dwp]} -> {il.choice} "
              f"(margin {il.margin:+.4f})")


@pytest.mark.slow
def test_a_monday_move_holds_him_at_the_open_window_and_activates_him_next_monday():
    """The Monday move (before the close): the horizon's first window is
    today's, still open (44b s.2). Hurt is tagged Q (44c: an O-tagged
    occupant with no entry stays in IL at the open window anyway), so the
    plan activates him today; B keeps him there today and brings him back at
    next Monday's window. It reads the same as on a chat move."""
    fx = negative_fixture()
    fx.statuses["Hurt"] = "Q"
    inp = fx.inputs(horizon=(2, 3), balance=True, adds={"Nick": 0})
    assert inp.kind == av.MONDAY and inp.plan.args.get("open_day") == S.day(2, 0)
    step = av.activation_step(inp, "Nick")
    assert step is not None and step["back"] == ["Hurt"]
    pl = _plan(inp)
    h = pl.il.hold
    assert h is not None and h.dwp[0] == 0.0 and h.next_week == 3
    P = av._plan(inp, av.hold_one_known(inp, "Nick", step))
    assert P[2]["Nick"]["held"] == ["Hurt"] and P[3]["Nick"]["activated"] == ["Hurt"]
    assert pl.il.choice == ("hold" if pl.il.margin > FAST.hold_bar else "activate")
