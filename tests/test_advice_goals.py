"""Advice goals' engine (modules/advice_goals; claude/HANDOFF_ADVICE_GOALS_2026-11-24.md
Part C), on a synthetic league where each goal's right answer is known by
construction (tests/advice_goals_fixture.py). Not wired into any run yet."""

from datetime import date, timedelta

import pytest

import advice_goals_fixture as GF
from modules import advice_goals as ag, advice_v2 as av

ST = av.Settings()
RULES = ag.NoiseRules.from_config(GF.CFG)


def _goals(fx):
    return {g.key: g for g in ag.goals_for(1, fx.week_dates(), GF.CFG)}


def _run(fx, key, nick_adds=1):
    inp = GF.inputs(fx, nick_adds)
    bal = av.plan_for(inp, "Nick", ST, av.RECOMMENDED, max_steps=1)
    opp, ties = GF.opponents()
    goal = _goals(fx)[key]
    gp = ag.plan_goal(inp, "Nick", goal, ST, opp, ties, max_steps=1, balanced=bal)
    return inp, bal, gp, ag.compare(inp, "Nick", gp, bal, ST, opp, ties, RULES)


# =============================================================================
# the goals and their weeks (fast)
# =============================================================================

def _league_weeks():
    """The league calendar's shape: week 7 is 14 days (LEAGUE_RULES rule 9)."""
    out, d = {}, date(2026, 10, 20)
    for w in range(1, 24):
        n = 14 if w == 7 else 7
        out[w] = [d + timedelta(days=k) for k in range(n)]
        d += timedelta(days=n)
    return out


def test_goals_follow_the_ranges_and_week_7_says_14_days():
    from modules.hub_v2 import ranges as rg
    wk = _league_weeks()
    gs = ag.goals_for(7, wk)
    keys = [g.key for g in gs]
    assert keys[:8] == ["balanced", "next", "next2", "next3", "ros", "semis", "finals", "cup"]
    assert keys[8:] == [f"week:{k}" for k in range(8, 16)]          # first week + 1 through week 15
    by = {g.key: g for g in gs}
    assert by["next"].chip == "Wk 7" and by["next2"].chip == "Wks 7\u20138"
    assert by["next"].long_weeks == (7,) and "14 days" in by["next"].sub
    assert by["week:8"].long_weeks == ()
    rr = {r.key: r.weeks for r in rg.ranges(wk[7][0], 7, wk)}        # one definition: Market's ranges
    for k, weeks in rr.items():
        assert by[k].weeks == weeks
    assert {g.key for g in gs if g.near} == {"balanced", "next", "next2", "next3"}


def test_passed_goals_are_hidden():
    wk = _league_weeks()
    keys = [g.key for g in ag.goals_for(16, wk)]
    assert "ros" not in keys and not any(k.startswith("week:") for k in keys)
    assert "semis" in keys
    keys = [g.key for g in ag.goals_for(19, wk)]
    assert "semis" not in keys and "finals" in keys


def test_noise_rules_are_required():
    with pytest.raises(ag.GoalError, match="advice.goals is missing"):
        ag.NoiseRules.from_config({"advice": {}})
    bad = {"advice": {"goals": dict(GF.CFG["advice"]["goals"], noise_z=-1)}}
    with pytest.raises(ag.GoalError, match="noise_z"):
        ag.NoiseRules.from_config(bad)


def test_the_config_has_nicks_numbers_and_far_goals_start_hidden():
    from modules.data_loader import _LEAGUE_CONFIG as cfg
    r = ag.NoiseRules.from_config(cfg)
    assert (r.z, r.floor, r.per_week, r.title_floor) == (2.0, 0.01, 0.01, 0.005)   # Nick, 11-25
    assert ag.far_public(cfg) is False
    wk = _league_weeks()
    shown = {g.key for g in ag.goals_for(7, wk) if ag.public(g, cfg)}
    assert shown == {"balanced", "next", "next2", "next3"}
    with pytest.raises(ag.GoalError, match="far_public"):
        ag.far_public({"advice": {"goals": {}}})
    with pytest.raises(ag.GoalError, match="true or false"):
        ag.far_public({"advice": {"goals": {"far_public": "no"}}})


def test_the_bar_widens_with_weeks_ahead():
    g_near = ag.Goal("next", "Wk 7", "", (7,), ag.NEAR, "wins")
    g_far = ag.Goal("week:12", "Wk 12", "", (12,), ag.NIGHTLY, "wins")
    assert RULES.bar(g_near, 7, 0.0) == pytest.approx(0.01)
    assert RULES.bar(g_far, 7, 0.0) == pytest.approx(0.01 + 0.01 * 5)
    assert RULES.bar(g_near, 7, 0.02) == pytest.approx(0.04)          # z x SE when it is larger


def test_bracket_goals_are_not_priced_yet():
    fx = GF.fixture()
    inp = GF.inputs(fx)
    opp, ties = GF.opponents()
    for key, target in ag.BRACKET_TARGETS.items():
        goal = ag.Goal(key, key, "", (3,), ag.NIGHTLY, target)
        with pytest.raises(ag.GoalNotPriced):
            ag.price_goal(inp, "Nick", goal, ST, opp, ties)


# =============================================================================
# each goal's answer, known by construction (slow: they price)
# =============================================================================

@pytest.mark.slow
def test_week_n_wins_the_first_week_even_when_it_costs_the_next():
    # Balanced takes Both Guy (weeks 1 and 2); Week 1 takes Now Guy (more week 1, nothing in week 2)
    _inp, bal, gp, c = _run(GF.fixture(now_games=3), "next")
    assert [s.priced.move.add for s in bal.steps] == ["Both Guy"]
    assert [s.priced.move.add for s in gp.steps] == ["Now Guy"]
    assert c["vs_balanced"] == "different" and c["gain"] > c["bar"]
    wk2 = next(x for x in c["cost"]["weeks"] if x["week"] == 2)
    assert wk2["dwp"] < 0 and not wk2["in_goal"]                     # the cost: week 2


@pytest.mark.slow
def test_a_specific_week_picks_the_stash():
    _inp, bal, gp, c = _run(GF.fixture(), "week:3")
    assert [s.priced.move.add for s in bal.steps] != ["Stash Guy"]
    assert [s.priced.move.add for s in gp.steps] == ["Stash Guy"]
    assert c["vs_balanced"] == "different"
    assert c["cost"]["holds_weeks"] == 2                            # weeks 1-2 before week 3
    assert [x["week"] for x in c["cost"]["weeks"]] == [1, 2, 3]
    assert c["cost"]["title_odds"] is not None                      # never hidden


@pytest.mark.slow
def test_the_noise_bar_keeps_balanceds_move():
    # a weak stash beats Balanced on week 3, but by less than the bar
    _inp, bal, gp, c = _run(GF.fixture(stash_fppg=2.0), "week:3")
    assert [s.priced.move.add for s in gp.steps] == ["Stash Guy"]
    assert 0 < c["gain"] <= c["bar"]
    assert c["vs_balanced"] == "same" and bal.steps


@pytest.mark.slow
def test_the_cost_is_the_goal_minus_balanced():
    inp, bal, gp, c = _run(GF.fixture(), "week:3")
    opp, ties = GF.opponents()
    Pg = av._plan(inp, ag.plan_known(inp, "Nick", [s.priced for s in gp.steps]))
    Pb = av._plan(inp, ag.plan_known(inp, "Nick", [s.priced for s in bal.steps]))
    gw = ag.plan_weeks(inp, "Nick", Pg, [1, 2, 3], ST, opp, ties)
    bw = ag.plan_weeks(inp, "Nick", Pb, [1, 2, 3], ST, opp, ties)
    for x in c["cost"]["weeks"]:
        w = x["week"]
        assert x["dwp"] == pytest.approx(float((gw[w].wins - bw[w].wins).mean()))
    b0 = av._price_base(inp, "Nick", ST)
    t = (av._measure(inp, "Nick", ST, b0, Pg)["dT_rs"] - av._measure(inp, "Nick", ST, b0, Pb)["dT_rs"])
    assert c["cost"]["title_odds"] == pytest.approx(t / inp.drop_config.rs_weight)
    assert (c["cost"]["adds"], c["cost"]["adds_balanced"]) == (1, 1)


@pytest.mark.slow
def test_rest_of_season_is_the_league_championship_alone():
    fx = GF.fixture()
    inp = GF.inputs(fx)
    opp, ties = GF.opponents()
    gps = ag.price_goal(inp, "Nick", _goals(fx)["ros"], ST, opp, ties)
    assert gps
    for g in gps:
        assert g.target == pytest.approx(g.priced.dT_rs / inp.drop_config.rs_weight)


@pytest.mark.slow
def test_a_goal_with_no_matchup_is_hidden():
    fx = GF.fixture()
    inp = GF.inputs(fx)
    _o, ties = GF.opponents()
    opp = {1: "Hayden", 2: "Benton", 3: None}
    gp = ag.plan_goal(inp, "Nick", _goals(fx)["week:3"], ST, opp, ties, max_steps=1)
    assert gp.stop == "hidden" and not gp.steps


@pytest.mark.slow
def test_no_adds_left_is_its_own_state_not_noise():
    """11-25, Nick's real data: the two teams with no adds left showed "noise"
    (gain 0) on every goal. No adds is its own state, after a hold and before
    hidden / noise / same / different."""
    fx = GF.fixture()
    inp = GF.inputs(fx, nick_adds=0)
    opp, ties = GF.opponents()
    bal = av.plan_for(inp, "Nick", ST, av.RECOMMENDED, max_steps=1)
    for key in ("next", "week:3", "ros"):
        gp = ag.plan_goal(inp, "Nick", _goals(fx)[key], ST, opp, ties, max_steps=1, balanced=bal)
        c = ag.compare(inp, "Nick", gp, bal, ST, opp, ties, RULES)
        assert gp.stop == "no_adds" and c["vs_balanced"] == "no_adds" and "gain" not in c

    class Held:
        held = True
        steps = ()
    gp = ag.plan_goal(inp, "Nick", _goals(fx)["next"], ST, opp, ties, balanced=Held())
    assert gp.stop == "hold"                                     # a hold first, even with no adds
    no_match = {1: "Hayden", 2: "Benton", 3: None}
    gp = ag.plan_goal(inp, "Nick", _goals(fx)["week:3"], ST, no_match, ties, balanced=bal)
    assert gp.stop == "no_adds"                                  # no adds before hidden


@pytest.mark.slow
def test_a_hold_blocks_every_goal():
    class Held:
        held = True
        steps = ()
    fx = GF.fixture()
    inp = GF.inputs(fx)
    opp, ties = GF.opponents()
    gp = ag.plan_goal(inp, "Nick", _goals(fx)["week:3"], ST, opp, ties, balanced=Held())
    assert gp.stop == "hold" and not gp.steps


@pytest.mark.slow
def test_a_goals_later_steps_are_built_after_the_activation():
    """Nick's 11-25 run failed in a goal's step 2 ("the plan activates ... after
    the earlier steps"). With an IL returner the plan activates at the advised
    window, every goal's plan takes two steps, and step 2 is priced on the
    roster after step 1 and the activation (advice_v2.apply_step, as plan_for)."""
    fx = GF.fixture(returner=True)
    inp = GF.returner_inputs(fx)
    step = av.activation_step(inp, "Nick")
    assert step is not None and step["back"] == ["Hurt Guy"]
    opp, ties = GF.opponents()
    bal = av.plan_for(inp, "Nick", ST, av.RECOMMENDED, max_steps=2)
    two = 0
    for goal in ag.goals_for(inp.horizon[0], fx.week_dates(), GF.CFG):
        if goal.target not in ("wins", "rs_title"):
            continue
        gp = ag.plan_goal(inp, "Nick", goal, ST, opp, ties, max_steps=2, balanced=bal)
        if gp.steps:
            cur = av.apply_step(inp, "Nick", gp.steps[0].priced, first=True)
            assert av.activation_step(cur, "Nick") is None          # step 1 carried it
            known = cur.prior["Nick"][int(inp.horizon[0])]["Nick"]
            assert "Hurt Guy" in known["il_activate"] and "Spare" in known["drop"]
        two += len(gp.steps) == 2 or (len(gp.steps) == 1 and gp.stop == "pat")
        ag.compare(inp, "Nick", gp, bal, ST, opp, ties, RULES)
    assert two >= 1                                     # a second step was priced (taken or not)


@pytest.mark.slow
def test_a_move_never_flips_the_midweek_decision():
    """11-25, Nick's real data: the plan as it stands keeps a mid-week returner
    in IL (44b s.4, activate false); a move (+ Fresh - Streak X) made the plan
    re-decide it as "activate now" and drop P2 -- a drop no step priced or
    showed -- and the next plan step raised. The decision is made once, on the
    base roster, and every move's plan holds it (advice_v2._hold_midweek,
    roster_plan's il_keep), Balanced's and every goal's alike."""
    fx = GF.flip_fixture()
    inp = GF.flip_inputs(fx)
    w1 = int(inp.horizon[0])
    base = av._plan(inp)[w1]["Nick"]
    assert base["activated"] == [] and [(e["player"], e["activate"]) for e in base["midweek"]] == [("Late", False)]
    assert av.midweek_kept(inp, "Nick") == ["Late"] and av.activation_step(inp, "Nick") is None
    mv = av.Move("Nick", "add_drop", "Fresh", drop="Streak X")
    p = av.price(inp, "Nick", [mv], ST)[0]
    after = av._plan(inp, av.known_for(mv, w1, None, w1 + 1))[w1]["Nick"]
    assert after["activated"] == [] and after["activation_drops"] == []          # not flipped
    assert "Late" in after["il"] and "P2" in after["active"]
    cur = av.apply_step(inp, "Nick", p, first=True)
    assert av.activation_step(cur, "Nick") is None                              # step 2 builds
    av.candidate_moves(cur, "Nick", ST)
    bal = av.plan_for(inp, "Nick", ST, av.RECOMMENDED, max_steps=2)             # Balanced, two steps' worth
    opp, ties = GF.opponents()
    opp = {**opp, 4: GF.FLIP_OPP["Nick"][4]}
    goal = {g.key: g for g in ag.goals_for(w1, fx.week_dates(), GF.CFG)}["next"]
    gp = ag.plan_goal(inp, "Nick", goal, ST, opp, {**ties, 4: 0.5}, max_steps=2, balanced=bal)
    for s_ in list(bal.steps) + [x.priced for x in gp.steps]:
        pr = s_.priced if hasattr(s_, "priced") else s_
        P = av._plan(inp, av.known_for(pr.move, w1, pr.followup_drop, w1 + 1))
        assert "Late" in P[w1]["Nick"]["il"] or pr.move.drop == "Late"


@pytest.mark.slow
def test_a_far_stash_with_no_keep_chance_is_a_joining_pickup():
    """11-25, Nick's real data (Holmgren at weeks 12 and 15): a free agent with
    no keep chance, the best stash for a far week, added while out -- three
    injured for two IL slots, so the plan's injured-drop decision (18b) ran on
    him and asked for his keep chance (KeyError). A known pickup joining has
    none yet: no keeper term, never protected (injured_drop.costs' joining),
    as advice_v2.protected and the activation rule already treat him."""
    from modules import injured_drop as idr
    fx = GF.injured_stash_fixture()
    inp = GF.injured_stash_inputs(fx)
    mv = av.Move("Nick", "add_drop", "Hurt Star", drop="Spare")
    P = av._plan(inp, av.known_for(mv, 2, None, 3))                       # raised KeyError before
    dec = {d["player"]: d for d in P[2]["Nick"]["decisions"]}
    assert "Hurt Star" not in dec or dec["Hurt Star"]["keep_rank"] is None
    assert "Hurt Star" in P[2]["Nick"]["active"] + P[2]["Nick"]["il"]
    opp = {w: GF.STASH_OPP["Nick"][w] for w in (1, 2, 3, 4)}
    goal = {g.key: g for g in ag.goals_for(2, fx.week_dates(), GF.CFG4)}["week:4"]
    bal = av.plan_for(inp, "Nick", ST, av.RECOMMENDED, max_steps=2)
    gp = ag.plan_goal(inp, "Nick", goal, ST, opp, {w: 0.5 for w in opp}, max_steps=2, balanced=bal)
    assert [s_.priced.move.add for s_ in gp.steps][:1] == ["Hurt Star"]
    ag.compare(inp, "Nick", gp, bal, ST, opp, {w: 0.5 for w in opp}, RULES)
    # only a joining pickup is exempt: anyone else with no keep chance still raises
    c = idr.Candidate("Nobody", 4, {w: (40.0 if w == 4 else 0.0) for w in range(1, 30)}, {w: 10.0 for w in range(1, 30)})
    st_ = inp.stakes["Nick"]
    with pytest.raises(KeyError, match="no keep chance"):
        idr.costs(c, st_, {"Someone": 0.5}, inp.drop_config)
    assert idr.costs(c, st_, {"Someone": 0.5}, inp.drop_config, joining=True)["keep_rank"] is None
    with pytest.raises(ValueError, match="joining but has a keep chance"):
        idr.costs(c, st_, {"Nobody": 0.5}, inp.drop_config, joining=True)


def test_merge_known_carries_il_keep_once():
    a = {2: {"Nick": {"il_place": [], "drop": [], "add": ["A"], "il_activate": [], "il_keep": ["Late"]}}}
    b = {2: {"Nick": {"il_place": [], "drop": [], "add": [], "il_activate": [], "il_keep": ["Late"]}}}
    assert av.merge_known(a, b)[2]["Nick"]["il_keep"] == ["Late"]


@pytest.mark.slow
def test_the_screen_on_the_horizon_is_todays():
    # advice_v2.candidate_moves with screen_weeks = the horizon screens exactly as without
    fx = GF.fixture()
    inp = GF.inputs(fx)
    a = av.candidate_moves(inp, "Nick", ST)
    b = av.candidate_moves(inp, "Nick", ST, screen_weeks=inp.weeks())
    assert [(m.kind, m.add, m.drop, m.to_il) for m in a] == [(m.kind, m.add, m.drop, m.to_il) for m in b]
    assert [round(m.screen_points, 6) for m in a] == [round(m.screen_points, 6) for m in b]


def test_the_goals_module_opens_no_file():
    import inspect
    import re
    src = inspect.getsource(ag)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    for pat in (r"\bopen\(", r"read_text\(", r"read_bytes\(", r"json\.load\(", r"read_excel\(",
                r"read_csv\(", r"urlopen\(", r"write_text\(", r"\.to_json\("):
        assert not re.search(pat, code), f"modules/advice_goals.py calls {pat}"


# =============================================================================
# the run's goals pass (advice_live; Part C.1, C.2, C.7)
# =============================================================================

def _fake_data():
    from types import SimpleNamespace
    weeks = []
    for w in (1, 2, 3):
        pairs = {tuple(sorted((a, b))) for a, v in GF.OPP.items() for ww, b in v.items() if ww == w}
        weeks.append({"week": w, "matchups": [{"manager_a": a, "manager_b": b} for a, b in sorted(pairs)]})
    return SimpleNamespace(schedule={"weeks": weeks})


class _Patch:
    """A tiny monkeypatch that also runs without pytest's fixture."""
    def __init__(self):
        self.undo = []

    def setattr(self, obj, name, value):
        self.undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def close(self):
        for obj, name, old in reversed(self.undo):
            setattr(obj, name, old)


def _run_step(tmp, mode="nightly", goals_raise=False, goals_on=True):
    from modules import advice_live as al
    fx = GF.fixture()
    inp = GF.inputs(fx, nick_adds=1)
    now = GF.S.at(1, 0, 0, 5)
    hz = av.Horizon(av.MONDAY, (1, 2), 1, GF.S.day(1, 0), GF.S.close_of(1))
    mp = _Patch()
    try:
        mp.setattr(al, "build", lambda *a, **k: (inp, hz, {"week_first_day": GF.S.day(1, 0).isoformat()}))
        mp.setattr(al, "goals_on", lambda cfg=None: goals_on)
        mp.setattr(al, "plan_steps_max", lambda cfg=None: 1)
        g0 = ag.goals_for
        mp.setattr(ag, "goals_for", lambda first, wk, cfg=None, join_day=None: g0(first, wk, GF.CFG))
        if goals_raise:
            def boom(*a, **k):
                raise RuntimeError("goals boom")
            mp.setattr(al, "goals_payload", boom)
        out = al.run_step(tmp, now, run_id="r", mode=mode, cause=None, data=_fake_data())
        return out, al.read_latest(tmp)
    finally:
        mp.close()


@pytest.mark.slow
def test_the_goals_pass_writes_goals_and_leaves_balanced_unchanged():
    import tempfile
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        out_on, on = _run_step(a)
        out_off, off = _run_step(b, goals_on=False)
    g = on.pop("goals")
    assert "goals" not in off
    for x in (on, off):
        for k in ("seconds", "as_of", "updated_text"):
            x.pop(k, None)
    assert on == off                                         # Balanced's top level: unchanged
    keys = [x["key"] for x in g["goals"]]
    assert keys[0] == "balanced" and "next" in keys and "week:3" in keys
    assert not any(k in keys for k in ("semis", "finals", "cup"))        # not priced yet: absent
    assert {x["key"]: x["public"] for x in g["goals"]}["week:3"] is False   # far_public false
    nick = g["managers"]["Nick"]
    assert nick["week:3"]["vs_balanced"] in ("different", "same", "noise") and nick["week:3"]["as_of"]
    assert g["managers"]["Hayden"]["next"]["vs_balanced"] == "no_adds"
    assert g["managers"]["Hayden"]["next"]["texts"]["line"] == "No adds left. Resets Monday."
    assert out_on["block"]["goals"]["error"] is None and not any("GOALS FAILED" in x for x in out_on["lines"])


@pytest.mark.slow
def test_a_failed_goals_pass_is_soft():
    import tempfile
    with tempfile.TemporaryDirectory() as a:
        out, latest = _run_step(a, goals_raise=True)
    assert latest["error"] is None and latest["managers"]["Nick"]["move"] is not None   # Balanced published
    assert latest["goals"]["error"] == "RuntimeError: goals boom"
    assert out["block"]["goals"]["error"] == "RuntimeError: goals boom"
    assert "ADVICE GOALS FAILED: RuntimeError: goals boom" in out["lines"]


@pytest.mark.slow
def test_far_goals_are_priced_nightly_and_carried_forward_otherwise():
    import tempfile
    with tempfile.TemporaryDirectory() as a:
        _o, night = _run_step(a, mode="nightly")
        _o2, poll = _run_step(a, mode="poll")
    n, p = night["goals"]["managers"]["Nick"], poll["goals"]["managers"]["Nick"]
    assert p["week:3"] == n["week:3"]                         # far: the nightly's, as of 12:01
    assert p["next"]["as_of"] != n["next"]["as_of"] or p["next"]["refresh"] == "move"   # near: re-priced
    assert poll["goals"]["carried"] is True
    with tempfile.TemporaryDirectory() as b:
        _o3, first_poll = _run_step(b, mode="poll")           # no nightly yet: pending
    assert first_poll["goals"]["managers"]["Nick"]["week:3"]["pending"]
