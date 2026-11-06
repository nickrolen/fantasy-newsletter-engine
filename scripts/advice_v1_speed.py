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
    from modules import advice_v2 as av, injured_drop, drop_inputs as di, tag_records, hub_state
    from modules.data_loader import (load_all_data, free_agents, PlayerIndex, CURRENT_SEASON,
                                     regular_season_weeks_for, league_rule)
    from modules.projections import load_player_projections
    from modules.roster_plan import load_il_slots
    from modules.simulator_playoff_odds import bracket_weeks
    from modules.league_clock import league_now
    from modules import week_state as ws

    data = load_all_data(base, current_week=None)
    today = league_now().date()
    week = ws.week_for_date(data, today) + 1                # next Monday's window
    horizon = (week, week + 1)
    proj_raw = load_player_projections(data)
    pidx = PlayerIndex(proj_raw)
    rosters = {m: list(v) for m, v in data.get_current_rosters().items()}
    il_state = load_il_slots(base, data)
    il = {m: list(v) for m, v in (il_state.get("slots") or {}).items()}
    tag_row = tag_records.latest(base)
    rostered = [n for v in rosters.values() for n in v]
    tags = dict(tag_records.hub_tags(tag_row, rostered))
    fa_df = free_agents(data.playerlist, rosters)
    pool = [n for n in fa_df["player_name"] if pidx.get(n) is not None]
    tags.update({n: t for n, t in hub_state.free_agent_tags(tag_row, pool).items()
                 if t not in (None, "HEALTHY")})
    proj = {}
    for n in rostered + pool:
        p = pidx.get(n)
        if p is None:
            raise KeyError(f"{n} has no projection in PLAYERLIST")
        proj[n] = p
    keep_all = di.keep_chances(data, base, week - 1)
    blob, note = di.read_stakes(base)
    stakes = {}
    if blob is not None:
        for m in rosters:
            stakes[m] = di.team_stakes(blob, m, week, last_regular=regular_season_weeks_for(CURRENT_SEASON),
                                       bracket=bracket_weeks())
    opp = {}
    for w in horizon:
        wk = next(x for x in data.schedule["weeks"] if int(x["week"]) == w)
        for mu in wk["matchups"]:
            opp.setdefault(mu["manager_a"], {})[w] = mu["manager_b"]
            opp.setdefault(mu["manager_b"], {})[w] = mu["manager_a"]
    shape = (int(league_rule("league_structure", "roster_size")) - int(league_rule("league_structure", "il_slots")),
             int(league_rule("league_structure", "il_slots")))
    states = {}
    for m, ro in rosters.items():
        on_il = tuple(n for n in ro if n in set(il.get(m, [])))
        act = tuple(n for n in ro if n not in set(on_il))
        keep = {n: float(PlayerIndex(keep_all.get(m, {})).get(n, 0.0)) for n in ro}
        states[m] = av.ManagerState(m, act, on_il, shape[0], shape[1], 3, keep, opp[m])
    world = av.World(data.nba_schedule, data.schedule["weeks"], week - 1, data.durability_prior)
    anchor = world.dates(week)[0]
    inp = av.MondayInputs(CURRENT_SEASON, horizon, world, proj, tags, states, tuple(pool), anchor,
                          stakes, injured_drop.from_rules())
    inp.check()
    return inp, {"week": week, "pool": len(pool), "stakes_note": note, "tags": len(tags)}


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
    inp3.stakes = {}
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
