"""One-week streams drop only from the bottom of the roster (Nick, 10-29).

C2's this_week plan may only drop one of the bottom season.stream_drop_pool
ACTIVE players by PROJECTED points per game (projected_fppg, never the
actual-blended effective_fppg). No keeper protection; IL occupants are not
ranked; a player with no projection is never a drop. The pool is fixed from
the roster at the start of the plan; the regular_season list is not limited
by it. STREAM_DROPS_RESULT_2026-10-29.
"""
import sys
from pathlib import Path

import pytest

from modules import advice as adv
from modules import marginal_value as mv
from modules.data_loader import UnspecifiedRule, stream_drop_pool

sys.path.insert(0, str(Path(__file__).parent))
from test_marginal_value import _world, _ctx  # noqa: E402  (shared builders)


@pytest.fixture(autouse=True)
def _season(monkeypatch):
    spans = {"regular_season": (1, 3), "playoffs": (4, 5), "cup": (6, 7)}
    monkeypatch.setattr(mv, "stage_weeks", lambda season, stage: spans.get(stage))


def _ctxs(w, season=False):
    out = {"this_week": (_ctx(w, sims=40), _ctx(w, sims=200))}
    if season:
        out["regular_season"] = (_ctx(w, window="regular_season", sims=40),
                                 _ctx(w, window="regular_season", sims=200))
    return out


def _fppg(ctx, p):
    return ctx.players[p].projected_fppg


# 1 -- never outside the pool, even when a non-pool drop scores better
def test_a_stream_never_drops_outside_the_pool_even_when_that_drop_scores_better():
    w = _world(seed=4)
    projs, rosters = w[0], w[1]
    full = _ctx(w, sims=200)
    by_fppg = sorted(rosters["Hayden"], key=lambda p: (_fppg(full, p), p))
    star = by_fppg[-1]                       # top of the roster by points per game
    projs[star].out_weeks = [2, 3]           # ...and out all week: the free drop
    ctxs = _ctxs(w)
    unlimited = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3,
                                protected_week=1, stream_pool_size=15)
    assert any(r.drop == star for r in unlimited.this_week), "without the pool he is the best drop"
    plan = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3,
                           protected_week=1, stream_pool_size=4)
    assert plan.stream_pool == by_fppg[:4] and star not in plan.stream_pool
    assert plan.this_week, "the pool still leaves moves that clear"
    assert all(r.drop in plan.stream_pool for r in plan.this_week)


# 2 -- the pool: the N lowest ACTIVE by projected fppg, ties by name;
#      a keeper may enter, IL and unprojected never do
def test_the_pool_is_the_n_lowest_active_by_projected_fppg_ties_by_name():
    import dataclasses
    w = _world(seed=4)
    projs, rosters = w[0], w[1]
    roster = rosters["Hayden"]
    full = _ctx(w, sims=200)
    by_fppg = sorted(roster, key=lambda p: (_fppg(full, p), p))
    keeper, il_man = by_fppg[0], by_fppg[1]  # the two lowest
    tie_a, tie_b = sorted(by_fppg[4:6])      # level these two; the name breaks it
    for p in (tie_a, tie_b):
        projs[p].projected_fppg = 20.0
    rosters["Hayden"] = roster + ["Deep Guy"]  # unprojected: valued 0.0, never droppable
    full = _ctx(w, sims=200, fallback_info={"Deep Guy": ("BOS", "SF")})
    assert "Deep Guy" in full.unprojected

    cands = adv.stream_candidates(full, "Hayden", {il_man})
    assert keeper in cands and il_man not in cands and "Deep Guy" not in cands
    expected = sorted(cands, key=lambda p: (_fppg(full, p), p))
    assert expected[0] == keeper
    for n in (1, 2, 3, 4, 6):
        pool = adv.stream_pool(full, cands, n)
        assert pool == expected[:n] and not {il_man, "Deep Guy"} & set(pool)
    assert adv.stream_pool(full, cands, 50) == expected       # n past the roster: all of it
    i = expected.index(tie_a)
    assert expected[i + 1] == tie_b and _fppg(full, tie_a) == _fppg(full, tie_b)
    # waiver_plan builds the same pool, and the keeper is in it
    ctxs = {"this_week": (_ctx(w, sims=40, fallback_info={"Deep Guy": ("BOS", "SF")}), full)}
    plan = adv.waiver_plan("Hayden", ctxs, w[4], protected=[keeper], adds_remaining=2,
                           protected_week=1, il={il_man}, stream_pool_size=4)
    assert plan.stream_pool == expected[:4] and keeper in plan.stream_pool
    assert all(r.drop in plan.stream_pool for r in plan.this_week)
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            adv.stream_pool(full, cands, bad)


def test_the_pool_ranks_by_the_projection_not_by_actual_play():
    """effective_fppg blends actual games in; the pool reads projected_fppg
    alone. Make the effective figure say the opposite of the projection."""
    import dataclasses
    w = _world(seed=4)
    full = _ctx(w, sims=200)
    cands = adv.stream_candidates(full, "Hayden")
    by_proj = sorted(cands, key=lambda p: (full.players[p].projected_fppg, p))
    for k, p in enumerate(by_proj):          # effective: best projection is now the worst
        full.players[p] = dataclasses.replace(full.players[p], fppg=float(k))
    assert adv.stream_pool(full, cands, 4) == by_proj[:4]
    gone = dataclasses.replace(full.players[by_proj[0]], projected_fppg=None)
    full.players[by_proj[0]] = gone
    with pytest.raises(ValueError, match="projected_fppg"):
        adv.stream_pool(full, cands, 4)


# 3 -- a player added earlier in the plan never enters the pool
def test_an_added_player_never_enters_the_pool():
    w = _world(seed=4)
    ctxs = _ctxs(w)
    roster = list(w[1]["Hayden"])
    plan3 = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3,
                            protected_week=1, stream_pool_size=4)
    adds = {r.add for r in plan3.this_week}
    assert set(plan3.stream_pool) <= set(roster) and not adds & set(plan3.stream_pool)
    assert all(r.drop not in adds for r in plan3.this_week)
    # a pool of one: once he is dropped the pool is empty, so the plan stops
    # -- the player just added does not take his place, however cheap
    plan1 = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3,
                            protected_week=1, stream_pool_size=1)
    assert len(plan1.this_week) <= 1
    assert all(r.drop == plan1.stream_pool[0] for r in plan1.this_week)
    assert len(plan3.this_week) > 1, "with a wider pool the same world makes more moves"


# 4 -- the season list is unchanged
def test_the_season_list_does_not_read_the_pool():
    w = _world(seed=4)
    ctxs = _ctxs(w, season=True)
    a = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3,
                        protected_week=1, stream_pool_size=1)
    b = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=3,
                        protected_week=1, stream_pool_size=15)
    assert a.regular_season and [adv.asdict(r) for r in a.regular_season] == \
        [adv.asdict(r) for r in b.regular_season]
    assert any(r.drop not in a.stream_pool for r in a.regular_season), \
        "season drops reach past the stream pool"


# 6 -- the config: required, an integer >= 1
def test_the_pool_size_is_required_config():
    assert stream_drop_pool() == 4                       # Nick, 10-29
    assert stream_drop_pool({"stream_drop_pool": 2}) == 2
    with pytest.raises(UnspecifiedRule):
        stream_drop_pool({})
    for bad in (0, -3, 2.5, "4", None, True):
        with pytest.raises(ValueError):
            stream_drop_pool({"stream_drop_pool": bad})


def test_waiver_plan_reads_the_config_when_not_told(monkeypatch):
    import modules.advice as advice_mod
    w = _world(seed=4)
    ctxs = _ctxs(w)
    plan = adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=1, protected_week=1)
    assert len(plan.stream_pool) == stream_drop_pool()
    monkeypatch.setattr(advice_mod, "stream_drop_pool",
                        lambda: stream_drop_pool({}))     # the key removed
    with pytest.raises(UnspecifiedRule):
        adv.waiver_plan("Hayden", ctxs, w[4], protected=[], adds_remaining=1, protected_week=1)


def test_the_footer_states_the_pool_from_config(monkeypatch):
    import modules.advice_render as r
    advice = {"published": True, "week": 1, "for_week": 2, "plans": [], "trades": [],
              "bar": {"per_week": 10}}
    html = r.render_html(advice)
    assert "one-week streams only drop from the bottom 4 of a roster by projected points per game, keepers included" in html
    assert "Season drops never touch next season's keepers" in html      # the keeper rule is the season list's alone
    monkeypatch.setattr(r, "stream_drop_pool", lambda: 6)
    html = r.render_html(advice)
    assert "bottom 6 of a roster" in html


# 5 -- on today's data (10-29, report week 1): the pools, and Lillard and
#      Embiid are not stream drops
TODAY = {"Nick": ["Dyson Daniels", "Julius Randle", "Ty Jerome", "Jaylen Brown"],
         "Hayden": ["Zach LaVine", "Darius Acuff Jr.", "Stephon Castle", "Amen Thompson"],
         "Benton": ["Paul George", "Cameron Boozer", "Nickeil Alexander-Walker", "Pascal Siakam"],
         "Garrett": ["Aaron Wiggins", "Toumani Camara", "VJ Edgecombe", "Alex Sarr"]}


def test_on_the_10_29_data_the_pools_hold_and_lillard_and_embiid_are_safe():
    root = Path(__file__).resolve().parents[1]
    from modules import advice_runner as ar
    from modules.data_loader import load_all_data
    from modules.projections import load_player_projections, populate_actual_stats
    from modules.report_builder import build_keeper_watch
    data = load_all_data(root)
    if data.current_week != 1:
        pytest.skip("pinned to the 10-29 data (report week 1); the rosters have moved on")
    rosters = {m: list(v) for m, v in data.get_current_rosters().items() if v}
    il = ar.il_occupants(data, rosters)
    projs = load_player_projections(data)
    populate_actual_stats(projs, data)
    fas = ar.free_agents(data.playerlist, rosters)["player_name"].tolist()
    kw = build_keeper_watch(data, 1)
    kw["week"] = 1
    prot, _ = adv.protected_keepers(kw, 1, rosters, ar.protected_keeper_counts(rosters))

    def ctx(n):
        return mv.build_context(projs, rosters, data.nba_schedule, data.schedule.get("weeks", []),
                                "this_week", 1, extra_players=fas,
                                fallback_info=ar._fallback_info(getattr(data, "lineups", None)),
                                sims=n, durability_prior=getattr(data, "durability_prior", None))
    ctxs = {"this_week": (ctx(20), ctx(60))}
    full = ctxs["this_week"][1]
    for m, pool in TODAY.items():
        assert adv.stream_pool(full, adv.stream_candidates(full, m, il.get(m)), 4) == pool, m
    for m, star in (("Nick", "Damian Lillard"), ("Hayden", "Joel Embiid")):
        assert star in rosters[m]
        plan = adv.waiver_plan(m, ctxs, fas, prot[m], 3, 1, il=il.get(m))
        assert plan.stream_pool == TODAY[m] and star not in plan.stream_pool
        assert all(r.drop in plan.stream_pool for r in plan.this_week)
        assert all(r.drop != star for r in plan.this_week)
