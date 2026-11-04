"""
fit_injured_drop.py -- refit M, F and K for the injured-drop rule (task 18b).

    python scripts\\fit_injured_drop.py

Plays Nick's scenarios (tests/injured_drop_scenarios.py) on every seed in
SEEDS, prints each seed's feasible region of (M, K, F), the region common
to all of them and its deepest point, then every scenario's outcome at the
values in config/league_config.json injured_drop. Writes nothing: a refit
is applied by editing the config (and the EXTENT in tests/test_injured_drop.py)
by hand, with the reviewing session. About a minute.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import injured_drop_scenarios as sc          # noqa: E402
from modules import injured_drop as idr      # noqa: E402


def main() -> int:
    cfg = idr.from_rules()
    res = sc.fit(cfg)
    for sd, r in res["per_seed"].items():
        print(f"seed {sd}: " + ("NO FEASIBLE POINT" if r is None else
                                f"M {r['M'][0]:.2f}-{r['M'][1]:.2f}  K {r['K'][0]:.3f}-{r['K'][1]:.3f}  "
                                f"F {r['F'][0]:.3f}-{r['F'][1]:.3f}"))
    c = res["common"]
    if c is None:
        print("common to every seed: NONE -- no setting fits (see INJURED_DROP_RESULT_2 s.1.5)")
        return 1
    print(f"common to every seed: M {c['M'][0]:.2f}-{c['M'][1]:.2f}  K {c['K'][0]:.3f}-{c['K'][1]:.3f}  "
          f"F {c['F'][0]:.3f}-{c['F'][1]:.3f}")
    M, K, F, depth = res["centre"]
    print(f"deepest point: M {M:.2f}  K {K:.3f}  F {F:.3f}  (a box of {depth:.0%} of each extent fits)")
    print(f"\nconfigured: M {cfg.margin}  K {cfg.keeper_weight}  F {cfg.floor}")
    for sd in sc.SEEDS:
        nums = sc.numbers(cfg, sd)
        line = []
        for n in nums:
            g = sc.gives(n, cfg.margin, cfg.floor, cfg.keeper_weight)
            ok = "" if n.answer in (None, g) else " (WRONG)"
            line.append(f"{n.sid} {g}{ok}")
        print(f"  seed {sd}: " + ", ".join(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
