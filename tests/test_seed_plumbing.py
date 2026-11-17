"""One seed per run (HANDOFF_SEED_PLUMBING_2026-10-20).

generate_stats_report chooses the seed once, records it, and every simulator
gets it -- so a week priced in the betting lines and simulated in the bracket
comes off the same keyed draws in a real run, not just in a test that passes
the same seed by hand. The simulators no longer choose their own.
"""
import ast
import importlib.util
import inspect
from pathlib import Path

import pytest

import il_state
import sim_counts
import stakes_state
import modules.data_loader as dl
import modules.report_builder as rb
from modules import simulator_betting as sb
from modules import simulator_cup_odds as cup
from modules import simulator_playoff_odds as spo
from modules import simulator_title_odds as sto

ROOT = Path(__file__).resolve().parent.parent
# What build_stats_report calls. Since Phase 2 title odds, the bracket and the
# Cup are readouts of one season pass, so the build makes one run_season call
# where it used to make three driver calls; the drivers themselves still take
# and require the seed (test 4 below).
SIM_CALLS = ("run_season", "generate_weekly_betting_lines")


def _script():
    spec = importlib.util.spec_from_file_location(
        "generate_stats_report", ROOT / "scripts" / "generate_stats_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 1 -- a seedless run records a concrete integer
def test_a_seedless_run_gets_a_concrete_seed():
    gsr = _script()
    s1, src1 = gsr.run_seed(None)
    s2, _ = gsr.run_seed(None)
    assert isinstance(s1, int) and 0 <= s1 < 2 ** 62 and src1 == "chosen for this run"
    assert s1 != s2
    assert gsr.run_seed(7) == (7, "--seed")


def test_the_script_records_and_passes_the_seed_it_used():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    chosen = src.index("args.seed, seed_source = run_seed(args.seed)")
    for use in ("seed=args.seed,", '"seed": args.seed,'):
        assert src.index(use) > chosen, use


def test_report_metadata_carries_the_seed():
    src = inspect.getsource(rb.build_stats_report)
    assert '"seed": seed' in src


# 4 -- each simulator raises instead of choosing
@pytest.mark.parametrize("call", [
    lambda: sto.run_title_odds_simulation(None, num_simulations=1),
    lambda: spo.run_playoff_odds_simulation(None, num_simulations=1),
    lambda: cup.run_cup_odds_simulation(None, num_simulations=1),
    lambda: sb.generate_weekly_betting_lines(None, num_simulations=1),
    lambda: sb.run_matchup_simulation(None, {}, {"week": 1}, "Nick", "Benton", 1),
    lambda: rb.build_stats_report(None, 1, run_simulations=True),
])
def test_no_simulator_chooses_its_own_seed(call):
    with pytest.raises(ValueError, match="seed"):
        call()


def test_no_seed_is_drawn_from_stdlib_random_or_the_os_in_the_simulators():
    for mod in (sb, spo, cup):
        src = inspect.getsource(mod)
        assert "getrandbits" not in src and "secrets." not in src, mod.__name__


# 3 -- the run hands every simulator one seed
def test_every_simulator_call_in_build_stats_report_passes_the_runs_seed():
    tree = ast.parse(inspect.getsource(rb.build_stats_report))
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in SIM_CALLS:
            kw = {k.arg: k.value for k in node.keywords}
            assert isinstance(kw.get("seed"), ast.Name) and kw["seed"].id == "seed", node.func.id
            seen.add(node.func.id)
    assert seen == set(SIM_CALLS)


# H51 (Nick, 11-17): the same questions, asked of the cheapest entry points
# that still hand one seed to every simulator -- the line (refresh_lines:
# prepare -> compute, which the live line and the closing line price through)
# and the season pass (title_odds_run.run_pass, which title odds, the bracket
# and the Cup read). The weekly build's own wiring is pinned above by source
# (test_every_simulator_call_in_build_stats_report_passes_the_runs_seed,
# test_report_metadata_carries_the_seed): no full report build is needed.
SPIED = (("modules.simulator_betting", "simulate_week_remainder"),
         ("modules.season_sim", "run_season"))


@pytest.fixture(scope="module")
def runs():
    """Week 1 priced at seeds 3, 3 and 4 through refresh_lines and the season
    pass, on the project's own data, with every simulator spied on for the
    seed it was handed."""
    import importlib
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import refresh_lines as rl
    from datetime import date
    from modules import title_odds_run as tor
    from modules.fetch_injury_statuses import Tags
    mp = pytest.MonkeyPatch()
    try:   # undone however the run ends (task 50)
        stakes_state.state(mp, 1)      # a week-1 replay states its stakes (tests/stakes_state.py)
        sim_counts.small(mp)           # paths, not counts (tests/sim_counts.py)
        got = []
        for mod_name, fn in SPIED:
            mod = importlib.import_module(mod_name)
            real = getattr(mod, fn)

            def spy(*a, _real=real, _name=fn, **k):
                seed = k["seed"] if "seed" in k else a[4]       # simulate_week_remainder's 5th
                got.append((_name, seed))
                return _real(*a, **k)
            mp.setattr(mod, fn, spy)
        out = []
        # one load for the three runs: the roster plan is cached on it and uses
        # its own fixed seed (roster_plan.Settings.seed), never the run's
        data = dl.load_all_data(ROOT, current_week=1)
        # The IL state, stated (tests/il_state.py), and priced without tags
        # (no_tags / Tags.none): this test is about plumbing.
        data.il_slots = il_state.as_last_synced(2)
        for seed in (3, 3, 4):
            got.clear()
            p = rl.prepare(ROOT, 1, as_of=date(2026, 10, 20), seed=seed, no_tags=True,
                           dry_run=True, reseed=True, data=data)
            key = rl.cache_key(p, 200)
            res, payload = rl.compute(p, 200, extra={"generated_at": "fixed"})
            recs = rl.calibration_records(p, res, 200, key, source="weekly_build", as_of="2026-10-20")
            sp = tor.run_pass(data, seed=seed, sims=20, statuses=Tags.none())
            out.append({"payload": payload, "records": recs, "odds": tor.readouts(sp),
                        "got": list(got), "seed": seed})
    finally:
        mp.undo()
    return out


@pytest.mark.slow
def test_one_run_hands_every_simulator_the_same_seed(runs):
    for r in runs:
        assert {n for n, _s in r["got"]} == {fn for _m, fn in SPIED}, r["got"]
        assert {s for _n, s in r["got"]} == {r["seed"]}, r["got"]
        assert r["payload"]["seed"] == r["seed"]


# 2 -- same seed, same numbers; different seed, different numbers
def _numbers(r):
    return ([(ln["spread_a"], ln["win_prob_a"], ln["over_under"]) for ln in r["payload"]["lines"]],
            r["odds"]["title_odds"])


@pytest.mark.slow
def test_the_same_seed_gives_the_same_lines_and_odds(runs):
    assert _numbers(runs[0]) == _numbers(runs[1])
    assert _numbers(runs[0])[0]


@pytest.mark.slow
def test_a_different_seed_gives_different_numbers(runs):
    assert _numbers(runs[0])[0] != _numbers(runs[2])[0]
    assert _numbers(runs[0])[1] != _numbers(runs[2])[1]


@pytest.mark.slow
def test_the_build_logs_a_rerun_once_and_a_new_seed_again(runs):
    """A line's calibration records take their identity from the line key
    (calibration_log.IDENTITY): the same line twice is the same record, a
    different seed is a different one -- whatever the clock said."""
    from modules import calibration_log as cal
    keys = [{r["matchup_id"]: r["line_key"] for r in run["records"]} for run in runs]
    assert keys[0] and keys[0] == keys[1]
    assert all(keys[2][m] != k for m, k in keys[0].items())
    ids = [{cal.identity(r) for r in run["records"]} for run in runs]
    assert ids[0] == ids[1] and not (ids[0] & ids[2])
