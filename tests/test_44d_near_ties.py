"""44d (claude/HANDOFF_44D_NEAR_TIES_2026-11-14.md; Nick's decisions, 11-13).

s.1 A NEAR-TIE -- a long-run decision (an activation drop, its tied-set
    pick included, or a mid-week returner's activate-or-wait) whose closest
    deciding comparison sits within roster_moves.longrun_escalate_margin SEs
    of the tie band's edge -- is re-decided on those comparisons at
    roster_moves.longrun_escalated_sims (the same seed and keying), and that
    answer stands, recorded with both measurements. Advice reads the plan's.
s.2 On a keeper-watch failure, 18b HOLDS every injured player beyond the IL
    slots (no drops), the slots by value without the keeper term, loudly.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from modules import advice_v2 as av
from modules import injured_drop as idr
from modules import roster_plan as rp
from test_injured_drop import _ctx, _keep_low, _plan_stakes, _three_out
from test_roster_plan import _build, _p

ROOT = Path(__file__).parent.parent


def _table(sims, means, sd, seed):
    """{name: per-simulation draws} with exactly the stated means."""
    rng = np.random.default_rng(seed)
    out = {}
    for n, mu in means.items():
        x = sd.get(n, 0.0) * rng.standard_normal(sims)
        out[n] = x - x.mean() + float(mu)
    return out


def _sum_of(table):
    return lambda r: sum(table[n] for n in r)


def _never(*a, **k):
    raise AssertionError("a clear decision asked for the escalated measure")


PROJ = {"A": 30.0, "B": 20.0, "K": 40.0, "R": 35.0}
KW = dict(manager="Nick", week=5, il=[], back=["R"], n=1, chance=lambda x: {"K": 0.9}.get(x, 0.0),
          protected_n=1, proj=lambda x: PROJ[x], band=2.0)


# =============================================================================
# s.1 the config
# =============================================================================

def test_the_escalation_settings_are_required_config(monkeypatch):
    assert rp.escalation_rules() == {"margin": 2.0, "sims": 800}
    assert rp.escalation_rules()["sims"] == 4 * rp.longrun_rules()["sims"]
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))["roster_moves"]
    assert "44d" in cfg["_longrun_escalate_margin"] and "44d" in cfg["_longrun_escalated_sims"]
    from modules import data_loader as dl
    real = dl.league_rule
    for key, bad in (("longrun_escalate_margin", None), ("longrun_escalated_sims", None),
                     ("longrun_escalated_sims", 200), ("longrun_escalate_margin", -1)):
        monkeypatch.setattr(dl, "league_rule", lambda s, k, _k=key, _b=bad: _b if k == _k else real(s, k))
        with pytest.raises(ValueError, match=key):
            rp.escalation_rules()
    monkeypatch.setattr(dl, "league_rule", real)


# =============================================================================
# s.1 an activation drop
# =============================================================================

def test_a_near_tie_escalates_and_the_escalated_answer_wins():
    """At 200 sims A (10) and B (11) are tied (SD 30): the lower projection, B,
    would go, 1.6 SE from the band's edge. At the escalated measure (800
    sims, SD 5) B costs clearly more than A: A goes, and the row says so,
    with both measurements; its fields are the deciding measurement's."""
    t200 = _table(200, {"A": 10, "B": 11, "K": 99, "R": 50}, {"A": 30, "B": 30}, 7)
    t800 = _table(800, {"A": 10, "B": 16, "K": 99, "R": 50}, {"A": 5, "B": 5}, 8)
    d0, det0 = rp.activation_drops(active=list(t200), value=_sum_of(t200), escalate=None, escalate_margin=None, **KW)
    assert d0 == ["B"] and det0[0]["escalated"] is False and det0[0]["margin"] <= 2.0     # a near-tie at 200
    d, det = rp.activation_drops(active=list(t200), value=_sum_of(t200), escalate=_sum_of(t800),
                                 escalate_margin=2.0, **KW)
    row = det[0]
    assert d == ["A"] and row["player"] == "A" and row["escalated"] is True and row["sims"] == 800
    first, second = row["measurements"]
    assert (first["sims"], first["player"], first["tied"]) == (200, "B", ["A", "B"])
    assert first["margin"] == det0[0]["margin"]
    assert (second["sims"], second["player"], second["tied"], second["cheapest"]) == (800, "A", ["A"], "A")
    assert (row["tied"], row["cheapest"], row["margin"], row["loss"]) == \
        (second["tied"], second["cheapest"], second["margin"], second["loss"])


def test_a_clear_decision_does_not_escalate():
    """A costs 10, B 100: the decision sits far from the band's edge, so the
    escalated measure is never asked for."""
    t = _table(200, {"A": 10, "B": 100, "K": 99, "R": 50}, {"A": 1, "B": 1}, 9)
    d, det = rp.activation_drops(active=list(t), value=_sum_of(t), escalate=_never, escalate_margin=2.0, **KW)
    assert d == ["A"] and det[0]["escalated"] is False and "measurements" not in det[0]
    assert det[0]["margin"] > 2.0


def test_an_exact_tie_cannot_move_and_does_not_escalate():
    """Players who never start cost exactly nothing: no spread, margin None,
    nothing more simulations could change."""
    t = {"A": np.zeros(200), "B": np.zeros(200), "K": np.full(200, 99.0), "R": np.full(200, 50.0)}
    d, det = rp.activation_drops(active=list(t), value=_sum_of(t), escalate=_never, escalate_margin=2.0, **KW)
    assert d == ["B"] and det[0]["margin"] is None and det[0]["escalated"] is False


def test_a_near_tie_with_no_escalated_measure_raises():
    t200 = _table(200, {"A": 10, "B": 11, "K": 99, "R": 50}, {"A": 30, "B": 30}, 7)
    with pytest.raises(rp.ActivationError, match="near-tie"):
        rp.activation_drops(active=list(t200), value=_sum_of(t200), escalate=None, escalate_margin=2.0, **KW)


# =============================================================================
# s.1 a mid-week returner
# =============================================================================

def _midweek_world(r200, r800):
    """Nick's 14 active and R in IL, back mid-week 5: A (activate now) minus B
    (wait) is R's week-5 draws exactly (every other week and player cancels),
    r200 at the base measure and r800 at the escalated one."""
    active = [f"N{j}" for j in range(14)]

    def valuer(rdraws):
        sims = len(rdraws)

        def v(roster, weeks, resolve):
            return rdraws.copy() if ("R" in roster and 5 in weeks) else np.zeros(sims)
        return v
    drops = rp.DropContext(config=idr.from_rules(), note=lambda: None, stakes=None, keep=None, games=None,
                           availability=None, longrun=valuer(r200), longrun_last=6,
                           longrun_escalated=None if r800 is None else valuer(r800),
                           little_left=lambda m, w: None)
    s = {"active": active, "il": ["R"], "standins": set(), "joined": set()}
    day_of = {5: date(2026, 11, 16), 6: date(2026, 11, 23)}
    return s, drops, day_of


def _draw(sims, mean, sd, seed):
    x = sd * np.random.default_rng(seed).standard_normal(sims)
    return x - x.mean() + mean


def test_a_near_midweek_call_escalates_and_the_escalated_answer_wins():
    """+1 pt (SE ~2.1) at 200 keeps him in IL inside the band; +10 (SE ~0.2)
    at 800 activates him: he is activated, recorded with both."""
    s, drops, day_of = _midweek_world(_draw(200, 1.0, 30.0, 1), _draw(800, 10.0, 5.0, 2))
    go, why, _d, _det, stats = rp._midweek("Nick", 5, s, "R", lambda n: None, drops, ["Nick"], day_of,
                                           {"active_spots": 15})
    assert go is True and stats["escalated"] is True
    first, second = stats["measurements"]
    assert (first["sims"], first["activate"]) == (200, False) and first["margin"] <= 2.0
    assert (second["sims"], second["activate"]) == (800, True)
    assert (stats["gain"], stats["se"], stats["margin"]) == (second["gain"], second["se"], second["margin"])
    assert "near-tie at 200 sims" in why and "activated now" in why


def test_a_clear_midweek_call_does_not_escalate_and_a_near_one_without_the_measure_raises():
    s, drops, day_of = _midweek_world(_draw(200, 40.0, 5.0, 3), None)
    go, _why, _d, _det, stats = rp._midweek("Nick", 5, s, "R", lambda n: None, drops, ["Nick"], day_of,
                                            {"active_spots": 15})
    assert go is True and stats["escalated"] is False and "measurements" not in stats
    s, drops, day_of = _midweek_world(_draw(200, 1.0, 30.0, 1), None)
    with pytest.raises(rp.ActivationError, match="near-tie"):
        rp._midweek("Nick", 5, s, "R", lambda n: None, drops, ["Nick"], day_of, {"active_spots": 15})


# =============================================================================
# s.1 on a real long-run measure: deterministic, and advice reads it
# =============================================================================

def _decisions(plan):
    """Every long-run decision a plan records: (week, manager) -> activation
    rows, drops and mid-week rows."""
    return {(w, m): (v.get("activation_detail"), v.get("activation_drops"), v.get("midweek"), v.get("activated"))
            for w, wk in plan.items() for m, v in wk.items()}


@pytest.mark.slow
@pytest.mark.real
def test_escalation_is_deterministic_on_the_real_state():
    """Today's real plan, rebuilt from fresh contexts (the base LongRun and the
    escalated one, the same seed): every decision and record identical,
    escalated ones included, with both measurements. Printed: today's
    escalations. Advice reads this plan (parity by construction)."""
    from test_il_followup import _real
    data, tps, tags = _real()
    run = rp.for_run(data, tps, tags)
    d = run.args["drops"]
    lr, esc = d.longrun.__self__, d.longrun_escalated.__self__
    assert (esc.seed, esc.sims, esc.first_week, esc.last_week) == \
        (lr.seed, rp.escalation_rules()["sims"], lr.first_week, lr.last_week)

    def fresh(x):
        return rp.LongRun(nba_schedule=x.nba_schedule, schedule_weeks=x.schedule_weeks,
                          durability_prior=x.durability_prior, season=x.season, statuses=dict(x.statuses),
                          anchor=x.anchor, first_week=x.first_week, last_week=x.last_week, sims=x.sims, seed=x.seed)
    again = rp.build(**{**run.args, "drops": replace(d, longrun=fresh(lr).draws,
                                                     longrun_escalated=fresh(esc).draws)})
    assert _decisions(again) == _decisions(run.plan)
    rows = [(w, m, r) for (w, m), (det, _d, mid, _a) in _decisions(run.plan).items()
            for r in (det or []) + (mid or []) if r.get("escalated")]
    print(f"\n  {len(rows)} escalated decision(s) in today's plan:")
    for w, m, r in rows:
        assert [x["sims"] for x in r["measurements"]] == [rp.longrun_rules()["sims"], rp.escalation_rules()["sims"]]
        print(f"    week {w} {m}: {r.get('player', '')} {r['measurements']}")


def test_the_plan_gives_its_run_one_escalated_measure_at_the_same_seed():
    """roster_plan.for_run attaches the escalated LongRun beside the base one:
    the same seed and span, escalated sims (source: one context per run)."""
    import inspect
    src = inspect.getsource(rp.for_run)
    assert "longrun_escalated=esc.draws" in src and "seed=lr.seed" in src
    assert 'escalation_rules()["sims"]' in src


# =============================================================================
# s.2 a keeper-watch failure: hold every injured player beyond the slots
# =============================================================================

def _broken_keep(m):
    raise rp.KeeperWatchFailed("AgeNotFound: no age for Somebody")


def _four_out():
    """Nick: four players out weeks 3-6 for two IL slots (18b decides)."""
    players, rosters = _three_out()
    players["Nick_3"] = _p("Nick_3", 37.0, out=[3, 4, 5, 6], ret="2026-11-30")
    return players, rosters


def test_a_broken_keeper_watch_holds_every_excess_injured_player(monkeypatch):
    players, rosters = _four_out()
    keep = _keep_low(rosters["Nick"])
    rp.take_notes()
    plan = _build(players, rosters, drops=replace(_ctx(_plan_stakes(), keep), keep=_broken_keep))
    v = plan[3]["Nick"]
    out = {f"Nick_{j}" for j in range(4)}
    assert len(v["il"]) == 2 and set(v["il"]) <= out                     # 2 placed
    held = out - set(v["il"])
    assert len(held) == 2 and held <= set(v["active"])                    # 2 held: active, scoring nothing
    assert v["dropped"] == [] and not any(n.startswith("Replacement for dropped") for n in v["added"])
    assert sorted(d["player"] for d in v["decisions"]) == sorted(held)
    for d in v["decisions"]:
        assert (d["action"], d["carried_out"]) == (idr.HOLD, True)
        assert d["rule"] == "fallback: AgeNotFound: no age for Somebody"
        assert "keeper watch failed" in d["reason"] and d["cost_drop"] is None
    # the slots by value without the keeper term (44c), ties by the longer absence
    assert all(d["player"] not in v["il"] for d in v["decisions"])
    for w in range(4, 7):                                                  # nobody is dropped later either
        assert not plan[w]["Nick"]["dropped"]
    notes = rp.take_notes()
    assert notes == [rp.FALLBACK_NOTE.format(err="AgeNotFound: no age for Somebody")]
    assert "HELD every injured player beyond the IL slots" in notes[0]
    assert "lowest-projection rule" in notes[0]                            # one line for both fallbacks


def test_the_slots_go_by_value_without_the_keeper_term_on_a_failure():
    players, rosters = _four_out()
    plan = _build(players, rosters, drops=replace(_ctx(_plan_stakes(), _keep_low(rosters["Nick"])),
                                                  keep=_broken_keep))
    rp.take_notes()
    # every one of the four is out to the same day: the value orders them (their projections)
    assert plan[3]["Nick"]["il"] == ["Nick_0", "Nick_1"]


def test_a_working_keeper_watch_decides_as_18b_does():
    players, rosters = _four_out()
    keep = _keep_low(rosters["Nick"])
    rp.take_notes()
    plan = _build(players, rosters, drops=_ctx(_plan_stakes(), keep))
    v = plan[3]["Nick"]
    assert rp.take_notes() == []
    assert v["decisions"] and all("rule" not in d for d in v["decisions"])
    assert all(d["cost_drop"] is not None and d["keep_rank"] is not None for d in v["decisions"])
    assert any(d["action"] == idr.DROP for d in v["decisions"])          # 18b drops here, as fitted
