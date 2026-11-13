"""
advice_v1_speed.py -- advice v2's speed on the CURRENT season (V1, decision 7).

    python scripts\\advice_v1_speed.py --out _to_delete\\v1

Builds next Monday's advice_v2.MondayInputs from the live files, READ-ONLY
(load_all_data, load_player_projections with INJURY_OVERRIDES, ROSTERS.json,
IL_SLOTS.json, the latest tag record, the stakes the nightly wrote, the live
keeper watch), and times:
    the inputs;
    a full Monday run, all four managers (screen, finalists, price, rank);
    one manager's re-run (fresh caches: what an incremental re-run redoes);
    the finalists' title-odds step (the later-weeks pricing) on its own.
Writes only out/speed.json. Publishes nothing; touches no state file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def live_inputs(base: Path, settings):
    """The live inputs, as every run builds them (modules/advice_live.build:
    the ledger, the season pass's roster plan, the stakes). V1 built its own
    here; since V2 the live path is the one way, and since the title-term job
    the engine needs the roster plan it carries."""
    from modules import advice_live as al
    from modules.league_clock import league_now
    inp, hz, meta = al.build(base, league_now())
    if inp is None:
        raise RuntimeError(f"no window is left this season: {meta}")
    return inp, {"week": hz.weeks[0], "horizon": list(hz.weeks), "kind": hz.kind,
                 "pool": len(inp.pool), "tags": len(inp.statuses)}


def main(argv=None):
    from modules import advice_v2 as av
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    base = ROOT
    st = av.Settings()
    out = {"settings": st.__dict__}
    t0 = time.time()
    inp, meta = live_inputs(base, st)
    out["inputs_s"] = round(time.time() - t0, 2)
    out.update(meta)
    t1 = time.time()
    tops, per = {}, {}
    for m in sorted(inp.managers):
        tm = time.time()
        r = av.recommend(inp, m, st)
        per[m] = round(time.time() - tm, 2)
        tops[m] = None if r.top is None else r.top.move.kind
    out["full_run_s"] = round(time.time() - t1, 2)
    out["per_manager_s"] = per
    out["top_kinds"] = tops
    # a re-run: one manager, every cache dropped (the incremental path redoes his plan only)
    inp2, _ = live_inputs(base, st)
    m0 = sorted(inp2.managers)[0]
    t2 = time.time()
    av.recommend(inp2, m0, st)
    out["rerun_one_manager_s"] = round(time.time() - t2, 2)
    # the finalists' title-odds step on its own: price with the stakes, then without
    inp3, _ = live_inputs(base, st)
    fin = av.finalists(av.candidate_moves(inp3, m0, st), st)
    t3 = time.time()
    av.price(inp3, m0, fin, st)
    with_title = time.time() - t3
    saved = inp3.stakes
    inp3.stakes = {m: None for m in saved}          # stated: no stakes (44c: a missing one raises)
    inp3._sims.clear()
    t4 = time.time()
    av.price(inp3, m0, fin, st)
    without = time.time() - t4
    inp3.stakes = saved
    out["title_step_s"] = round(with_title - without, 2)
    out["price_without_title_s"] = round(without, 2)
    out["finalists"] = len(fin)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "speed.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
