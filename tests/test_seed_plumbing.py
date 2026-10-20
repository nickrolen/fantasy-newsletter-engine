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

import modules.advice_runner as ar
import modules.data_loader as dl
import modules.report_builder as rb
from modules import simulator_betting as sb
from modules import simulator_cup_odds as cup
from modules import simulator_playoff_odds as spo
from modules import simulator_title_odds as sto

ROOT = Path(__file__).resolve().parent.parent
SIM_CALLS = ("run_title_odds_simulation", "run_playoff_odds_simulation",
             "run_cup_odds_simulation", "generate_weekly_betting_lines", "generate_fun_facts")


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


@pytest.fixture(scope="module")
def runs():
    """build_stats_report on the project's own data at seeds 3, 3 and 4,
    with every simulator spied on for the seed it was handed."""
    mp = pytest.MonkeyPatch()
    mp.setattr(rb, "build_season_performers", lambda *a, **k: {})   # no Yahoo in tests
    mp.setattr(ar, "build_advice", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")))
    got = []
    for name in SIM_CALLS:
        real = getattr(rb, name)

        def spy(*a, _real=real, _name=name, **k):
            got.append((_name, k.get("seed")))
            return _real(*a, **k)
        mp.setattr(rb, name, spy)
    out = []
    for seed in (3, 3, 4):
        got.clear()
        data = dl.load_all_data(ROOT, current_week=1)
        rep = rb.build_stats_report(data, 1, run_simulations=True,
                                    num_title_sims=60, num_betting_sims=200, seed=seed)
        out.append((rep, list(got)))
    mp.undo()
    return out


def test_one_run_hands_every_simulator_the_same_seed(runs):
    for (rep, got), seed in zip(runs, (3, 3, 4)):
        assert got, "no simulator ran"
        assert {s for _n, s in got} == {seed}, got
        assert rep["metadata"]["seed"] == seed


# 2 -- same seed, same numbers; different seed, different numbers
def _numbers(rep):
    return rep.get("looking_ahead"), rep.get("title_odds")


def test_the_same_seed_gives_the_same_lines_and_odds(runs):
    assert _numbers(runs[0][0]) == _numbers(runs[1][0])
    assert _numbers(runs[0][0])[0] is not None


def test_a_different_seed_gives_different_numbers(runs):
    assert _numbers(runs[0][0]) != _numbers(runs[2][0])
