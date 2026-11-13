"""
tests/test_advice_title_check.py -- the title term's check against the season
pass (scripts/advice_title_check.py, HANDOFF_ADVICE_TITLE_TERM s.3) and the
pieces the term added around it.

  - the check script never writes a state file (config/STATE_MANIFEST.json),
    nor outside its --dir, nor outside the repo;
  - its table's arithmetic (correlation, slope estimate-on-full, sign, MAE,
    the target) on a synthetic list;
  - marginal_value.add_players: a stand-in made after the context counts in
    roster_totals; a different player under the same name raises;
  - the live path prices with the season pass's projections (the roster
    plan's player index, actuals blended), never load_player_projections.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
import scripts.advice_title_check as tc            # noqa: E402


def test_the_check_refuses_to_write_a_state_file():
    scratch = ROOT / "_to_delete" / "title_term_test"
    assert tc.guard(scratch / "x.json", scratch) == (scratch / "x.json").resolve()
    for state in ("output/stakes.json", "output/advice_latest.json", "config/ROSTERS.json"):
        with pytest.raises(tc.Refused):
            tc.guard(ROOT / state, ROOT / Path(state).parent)
    with pytest.raises(tc.Refused, match="not under --dir"):
        tc.guard(ROOT / "_to_delete" / "elsewhere.json", scratch)
    with pytest.raises(tc.Refused, match="outside the repo"):
        tc.guard(Path("/tmp/x.json"), Path("/tmp"))
    with pytest.raises(tc.Refused, match="scratch"):
        tc.guard(ROOT / "output" / "x.json", ROOT / "output")


def test_every_write_goes_through_the_guard():
    src = inspect.getsource(tc)
    body = src.split("def guard(", 1)[1]
    writes = [l for l in body.splitlines() if "write_text(" in l or "write_bytes(" in l or "np.savez(" in l]
    assert writes and all(("tmp" in l) for l in writes), writes
    assert src.count("guard(") >= 3


def _synthetic(slope, noise, n=12, seed=1):
    rng = np.random.default_rng(seed)
    full = rng.normal(0, 0.1, n)
    est = slope * full + rng.normal(0, noise, n)
    moves = [{"id": i, "manager": "Nick", "kind": "add_drop", "add": f"A{i}", "drop": f"D{i}",
              "to_il": None, "category": "x", "split": "dev" if i % 2 else "held_out",
              "v2_est": float(est[i] * 2)} for i in range(n)]
    base = {"rs": {"Nick": 0.3}, "champ": {"Nick": 0.4}}
    passes = {"base": base}
    for i in range(n):
        passes[str(i)] = {"rs": {"Nick": 0.3 + full[i] / 2}, "champ": {"Nick": 0.4}}
    est_rows = {i: {"est": float(est[i]), "dT_rs": float(est[i]), "dT_po": 0.0} for i in range(n)}
    return {"moves": moves}, est_rows, passes, full, est


def test_the_table_arithmetic():
    lst, est, passes, full, e = _synthetic(1.0, 0.0)
    t = tc.table(lst, est, passes, "all")
    assert t["n"] == 12
    assert t["corr"] == pytest.approx(1.0) and t["slope"] == pytest.approx(1.0)
    assert t["sign"] == 1.0 and t["mae"] == pytest.approx(0.0, abs=1e-12) and t["meets"]
    assert t["mean_abs_full"] == pytest.approx(float(np.mean(np.abs(full))))
    assert t["v2_slope"] == pytest.approx(2.0)
    lst, est, passes, full, e = _synthetic(1.4, 0.0)
    t = tc.table(lst, est, passes, "all")
    assert t["slope"] == pytest.approx(1.4) and t["corr"] == pytest.approx(1.0) and not t["meets"]
    held = tc.table(lst, est, passes, "held_out")
    assert held["n"] == 6 and all(r["id"] % 2 == 0 for r in held["rows"])


def test_the_report_refuses_without_the_list(tmp_path):
    assert tc.main(["report", "--dir", str(tmp_path)]) == 2


def test_add_players_counts_a_late_stand_in_and_refuses_a_different_namesake():
    from datetime import date
    from modules import marginal_value as mv
    from modules.projections import PlayerProjection
    games = {"games": [{"date": "2026-11-0%dT00:00:00Z" % d, "home": "AAA", "away": "ZZZ"} for d in (2, 4, 6)]}
    weeks = [{"week": 1, "start_date": "2026-11-02", "end_date": "2026-11-08"}]
    a = PlayerProjection("A", "AAA", ["PG"], 20.0, projected_gp=82.0)
    ctx = mv.build_context({"A": a}, {"Nick": ["A"]}, games, weeks, "this_week", 0, sims=4, seed=1,
                           season="2026-27")
    s = PlayerProjection("Replacement for open spot 1, Nick (30.0)", "AAA", ["SG"], 30.0, projected_gp=82.0,
                         standin=True)
    before = float(mv.roster_totals(ctx, ["A", s.player_name])[0].mean())
    assert before == pytest.approx(60.0)              # the stand-in is not in the context: skipped
    assert mv.add_players(ctx, {s.player_name: s}) == [s.player_name]
    assert float(mv.roster_totals(ctx, ["A", s.player_name])[0].mean()) == pytest.approx(150.0)
    assert mv.add_players(ctx, {s.player_name: s}) == []
    other = PlayerProjection(s.player_name, "BBB", ["SG"], 30.0, projected_gp=82.0, standin=True)
    with pytest.raises(ValueError, match="different player"):
        mv.add_players(ctx, {s.player_name: other})


def test_the_live_path_prices_with_the_season_pass_projections():
    from modules import advice_live
    src = inspect.getsource(advice_live.build)
    assert 'pidx = run.args["players"]' in src
    assert "load_player_projections(" not in src
    assert "roster_plan.for_run(data, tps, tags, today=today, now=now)" in src     # 44b: the run's clock
    assert "plan=av.PlanSpec(dict(run.args))" in src
