#!/usr/bin/env python3
"""
advice_title_check.py -- the advice engine's title-odds term against the
season pass (claude/HANDOFF_ADVICE_TITLE_TERM_2026-11-11.md s.3). Read-only.

    python scripts\\advice_title_check.py pass base   --dir _to_delete\\title_term
    python scripts\\advice_title_check.py pass 7      --dir _to_delete\\title_term
    python scripts\\advice_title_check.py estimate    --dir _to_delete\\title_term
    python scripts\\advice_title_check.py report      --dir _to_delete\\title_term

THE MOVE LIST is <dir>/moves.json, fixed before any result: each move's
manager, kind, add, drop, IL placement and follow-up drop, its split ("dev":
developed against; "held_out": reported untouched), the clock the inputs were
built at, the tag record and the stakes run.

THE FULL SIDE ("pass"): season_sim.run_season with the move applied at its
window as KNOWN moves (and, mid-week, its tags anchored where the week's live
line anchored them: title_odds_run.line_anchors, HANDOFF_CAUSAL_LEVERAGE s.3) (advice_v2.known_for -- the same encoding the engine's
title term prices), at the stakes file's seed and number of simulations
(common random numbers), on the tag record the stakes were priced on, through
the playoffs: the regular-season title and the champion do not depend on the
Cup (run_season: a stage's numbers never depend on what comes after it; the
draws are keyed by week), and the base pass proves it by reproducing the
stakes file, priced through the Cup, exactly.

A pass at 50,000 simulations runs close to the VM's 3-minute cap per command,
so it is two calls, each resumable: the first computes the week matrices
(simulator_betting.week_score_matrices, inside run_season, unchanged) and
saves them losslessly to <dir>/passes/<key>.matrices.npz; the second runs
run_season again with week_score_matrices answering from that file (it checks
the weeks, the managers and the number of simulations) and writes the
checkpoint. Nothing else in the pass changes; the base pass's exact
reproduction of the stakes file covers the split too.

A MOVE'S MATRICES REUSE THE BASE'S where they cannot differ: a manager whose
roster and IL slots in a week are the base plan's has the base's column that
week (the draws are keyed by player, date and week -- crn.py -- so an unchanged
roster gives the same numbers). Only the changed manager-weeks are simulated,
by simulate_week_matrix itself with the move's plan. --verify-reuse also
computes every column in full and refuses unless the two agree bit for bit
(run once; the result doc reports it). When the matrices come quickly, the
same call goes on to the second half. "pass base" is the pass with no move: it must reproduce
the stakes file (drop_inputs.read_stakes)'s rs_title and champion for every team, or it refuses.
Each pass is one checkpoint (<dir>/passes/<key>.json), ~50-70 s here; a
finished checkpoint is never recomputed (--force to redo).

THE ESTIMATE ("estimate"): advice_v2.price on the same inputs (advice_live.build
at the move list's clock), every move's dT_horizon + dT_later; written to
<dir>/estimates.json.

THE TABLE ("report"): per split, the correlation, the slope (estimate on
full), the sign agreement, the mean absolute error against the mean |full|,
in 18b's stake units (2 x P(regular-season title) + 1 x P(champion)).

IT NEVER WRITES A STATE FILE: every path it writes is checked against
config/STATE_MANIFEST.json and must be inside the repo, under --dir, and under
_to_delete/ (scratch); anything else refuses before a byte is written.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TARGET = {"corr": 0.85, "slope": (0.8, 1.25), "sign": 0.90}


class Refused(RuntimeError):
    """A write this script will not make, or inputs that do not match the list."""


def guard(path: Path, out_dir: Path) -> Path:
    """The only way this script writes: inside the repo, under --dir, and not
    a state path (config/STATE_MANIFEST.json)."""
    from modules import state_manifest
    p = Path(path).resolve()
    d = Path(out_dir).resolve()
    try:
        rel = p.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        raise Refused(f"{p} is outside the repo: refused")
    if d not in p.parents:
        raise Refused(f"{rel} is not under --dir {d}: refused")
    if (ROOT.resolve() / "_to_delete") not in p.parents:
        raise Refused(f"{rel} is not under _to_delete/ (scratch): refused")
    man = state_manifest.load(ROOT)
    if man.contains(rel) or man.contains(Path(out_dir).resolve().relative_to(ROOT.resolve()).as_posix() + "/x"):
        raise Refused(f"{rel} is a state path (config/STATE_MANIFEST.json): refused")
    return p


def write_json(path: Path, blob, out_dir: Path) -> None:
    p = guard(path, out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(blob, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)


def load_list(out_dir: Path) -> dict:
    f = Path(out_dir) / "moves.json"
    if not f.is_file():
        raise Refused(f"{f} is missing: the move list is fixed first")
    return json.loads(f.read_text(encoding="utf-8"))


def _tag_row(base, run_id: str) -> dict:
    from modules import tag_records
    for r in reversed(tag_records.read(base)):
        if r.get("run_id") == run_id:
            return r
    raise Refused(f"no tag record {run_id} in output/tag_records.jsonl")


def _move(x):
    from modules import advice_v2 as av
    return av.Move(x["manager"], x["kind"], x["add"], drop=x.get("drop"), to_il=x.get("to_il"))


# =============================================================================
# the full side
# =============================================================================

def _data(out_dir: Path, lst: dict):
    from modules.data_loader import load_all_data
    return load_all_data(str(ROOT), current_week=None)


def cmd_pass(a) -> int:
    from modules import advice_v2 as av, move_ledger as ml, tag_records
    from modules.data_loader import load_all_data
    from modules.season_sim import run_season
    from modules.title_odds_run import line_anchors
    import numpy as np
    t0 = time.time()
    out_dir = Path(a.dir)
    lst = load_list(out_dir)
    key = a.key
    f = out_dir / "passes" / f"{key}.json"
    if f.is_file() and not a.force:
        secs = json.loads(f.read_text(encoding="utf-8"))["seconds"]
        print(f"{key}: done ({secs} s)")
        return 0
    from modules import drop_inputs
    stakes, note = drop_inputs.read_stakes(str(ROOT))      # the stakes' one reader
    if stakes is None:
        raise Refused(f"no usable stakes: {note}")
    if stakes["run_id"] != lst["stakes_run"]:
        raise Refused(f"the stakes file is run {stakes['run_id']}, the list was fixed on "
                      f"{lst['stakes_run']}: the base pass could not reproduce it")
    data = _data(out_dir, lst)
    tags = tag_records.as_tags(_tag_row(str(ROOT), lst["tag_run"]))
    known = ml.known_moves(str(ROOT))
    base_known = av.merge_known(known)
    if key != "base":
        x = lst["moves"][int(key)]
        hz = lst["horizon"]
        known = av.merge_known(known, av.known_for(_move(x), hz[0], x.get("followup"), hz[1]))
    data.known_moves = {int(w): v for w, v in known.items()}
    through = "playoffs" if stakes["through"] == "cup" else stakes["through"]
    n, seed = int(stakes["num_simulations"]), int(stakes["seed"])
    mfile = guard(out_dir / "passes" / f"{key}.matrices.npz", out_dir)
    import modules.simulator_betting as sbm
    import modules.season_sim as ssm
    real = sbm.week_score_matrices
    t = time.time()
    if not mfile.is_file():
        class _Saved(Exception):
            pass
        base_file = out_dir / "passes" / "base.matrices.npz"
        reuse = key != "base" and base_file.is_file()

        def compute(data_, tps, weeks, statuses, seed_, n_, tag_anchor=None, plan=None, tag_chain=None):
            from modules import roster_plan as rp
            from modules.data_loader import MANAGERS
            chain_kw = {"tag_chain": tag_chain} if tag_chain is not None else {}
            if not reuse or a.verify_reuse:
                full = real(data_, tps, weeks, statuses, seed_, n_, tag_anchor=tag_anchor, plan=plan, **chain_kw)
            if reuse:
                base_m = np.load(base_file)
                bplan = rp.build(**{**plan.args, "known": base_known})
                draws = sbm.KeyedDraws(seed_, n_)
                mats, simulated = {}, 0
                for w in weeks:
                    w = int(w)
                    changed = []
                    for m in MANAGERS:
                        mv_, bv = plan.plan.get(w, {}).get(m), bplan.get(w, {}).get(m)
                        same = (mv_ is not None and bv is not None
                                and sorted(mv_["active"]) == sorted(bv["active"])
                                and sorted(mv_["il"]) == sorted(bv["il"]))
                        if not same:
                            changed.append(m)
                    mats[w] = {m: base_m[f"{w}|{m}"] for m in MANAGERS if m not in changed}
                    if changed:
                        tp, mask = rp.week_rosters(plan, tps, w)
                        res = sbm.simulate_week_matrix(data_, tp, sbm.schedule_week(data_, w), statuses, draws,
                                                       tag_anchor, managers=changed, il_mask=mask, **chain_kw)
                        for m in changed:
                            mats[w][m] = res[m]["score"]
                        simulated += len(changed)
                if a.verify_reuse:
                    bad = [(w, m) for w in full for m in full[w]
                           if not np.array_equal(np.asarray(full[w][m]), np.asarray(mats[int(w)][m]))]
                    if bad:
                        raise Refused(f"reused matrices differ from the full computation: {bad[:6]}")
                    print(f"{key}: reuse verified bit for bit on {len(full) * len(MANAGERS)} columns "
                          f"({simulated} simulated)")
                print(f"{key}: {simulated} manager-weeks simulated, the rest the base's")
            else:
                mats = full
            arrs = {f"{w}|{m}": np.asarray(v, dtype=np.float64) for w, ms in mats.items() for m, v in ms.items()}
            mfile.parent.mkdir(parents=True, exist_ok=True)
            tmp = mfile.with_name(mfile.name + ".tmp.npz")
            np.savez(tmp, **arrs)
            tmp.replace(mfile)
            raise _Saved()
        ssm.week_score_matrices = compute
        try:
            run_season(data, num_simulations=n, seed=seed, injury_statuses=tags, through=through,
                       tag_anchors=line_anchors(str(ROOT)))
        except _Saved:
            print(f"{key}: week matrices saved ({time.time() - t:.0f} s)")
        else:
            raise Refused("run_season asked for no week matrices")
        finally:
            ssm.week_score_matrices = real
        if time.time() - t0 > a.budget:
            print(f"{key}: run the same command again for the second half")
            return 0
        t = time.time()
    saved = np.load(mfile)

    def answer(data_, tps, weeks, statuses, seed_, n_, tag_anchor=None, plan=None, tag_chain=None):
        if int(n_) != n or int(seed_) != seed:
            raise Refused("the saved matrices are for another seed or number of simulations")
        out = {}
        for w in weeks:
            out[int(w)] = {}
            for m in sp_managers:
                k = f"{int(w)}|{m}"
                if k not in saved.files:
                    raise Refused(f"the saved matrices have no week {w} for {m}")
                out[int(w)][m] = saved[k]
                if len(out[int(w)][m]) != n:
                    raise Refused("a saved matrix has the wrong length")
        if len(saved.files) != len(weeks) * len(sp_managers):
            raise Refused("the saved matrices are for other weeks")
        return out
    from modules.data_loader import MANAGERS as sp_managers
    ssm.week_score_matrices = answer
    try:
        sp = run_season(data, num_simulations=n, seed=seed, injury_statuses=tags, through=through,
                        tag_anchors=line_anchors(str(ROOT)))
    finally:
        ssm.week_score_matrices = real
    secs = round(time.time() - t, 1)
    rs = {m: float((sp.reg_finish[:, 0] == j).mean()) for j, m in enumerate(sp.managers)}
    ch = {m: float((sp.playoff_finish[:, 0] == j).mean()) for j, m in enumerate(sp.managers)}
    margins = {str(w): {m: float(np.nanmean(arr[:, j])) for j, m in enumerate(sp.managers)}
               for w, arr in sp.week_margins.items()}
    if key == "base":
        bad = [m for m in sp.managers
               if abs(rs[m] - stakes["teams"][m]["rs_title"]) > 1e-12
               or abs(ch[m] - (stakes["teams"][m]["champion"] or 0.0)) > 1e-12]
        if bad:
            raise Refused(f"the base pass does not reproduce the stakes file (drop_inputs.read_stakes) for {bad}: "
                          f"{ {m: (rs[m], stakes['teams'][m]['rs_title']) for m in bad} }")
    blob = {"key": key, "rs": rs, "champ": ch, "seconds": secs, "through": through,
            "week_margin_means": margins,
            "known": {str(w): v for w, v in data.known_moves.items()},
            "at": datetime.now().isoformat(timespec="seconds")}
    write_json(f, blob, out_dir)
    print(f"{key}: {secs} s", {m: (round(rs[m], 5), round(ch[m], 5)) for m in sp.managers})
    return 0


# =============================================================================
# the estimate
# =============================================================================

def cmd_estimate(a) -> int:
    from dataclasses import replace
    from modules import advice_live as al, advice_v2 as av
    out_dir = Path(a.dir)
    lst = load_list(out_dir)
    now = datetime.fromisoformat(lst["now"])
    t = time.time()
    inp, hz, meta = al.build(str(ROOT), now)
    if list(hz.weeks) != list(lst["horizon"]):
        raise Refused(f"the horizon is {hz.weeks}, the list was fixed on {lst['horizon']}")
    if meta.get("stakes_run") != lst["stakes_run"] or meta.get("tags_run") != lst["tag_run"]:
        raise Refused("the inputs' stakes or tags are not the ones the list was fixed on")
    inp.managers = {m: replace(st, adds_left=3) for m, st in inp.managers.items()}
    t_in = time.time() - t
    S = av.Settings()
    rows = []
    t1 = time.time()
    for x in lst["moves"]:
        mo = _move(x)
        p = av.price(inp, x["manager"], [mo], S, followups={mo: x.get("followup")})[0]
        rows.append({"id": x["id"], "est": p.dT_horizon + p.dT_later, "dT_h": p.dT_horizon,
                     "dT_l": p.dT_later, "dT_rs": p.dT_rs, "dT_po": p.dT_po, "dwp": list(p.dwp),
                     "dpts": list(p.dpts), "later_by_week": [list(v) for v in p.dpts_later_by_week]})
    blob = {"engine": a.label, "seconds": {"inputs": round(t_in, 1), "pricing": round(time.time() - t1, 1)},
            "rows": rows, "at": datetime.now().isoformat(timespec="seconds")}
    write_json(out_dir / "estimates.json", blob, out_dir)
    print(f"{len(rows)} estimates, inputs {t_in:.1f} s, pricing {time.time() - t1:.1f} s")
    return 0


# =============================================================================
# the table
# =============================================================================

def table(lst: dict, est: dict, passes: dict, split: str) -> dict:
    import numpy as np
    b = passes["base"]
    rows = []
    for x in lst["moves"]:
        if split != "all" and x["split"] != split:
            continue
        p = passes.get(str(x["id"]))
        e = est.get(x["id"])
        if p is None or e is None:
            continue
        m = x["manager"]
        drs, dch = p["rs"][m] - b["rs"][m], p["champ"][m] - b["champ"][m]
        rows.append({"id": x["id"], "manager": m, "move": _move(x).describe(), "category": x["category"],
                     "est": e["est"], "full": 2 * drs + 1 * dch, "est_rs": e["dT_rs"] / 2, "full_rs": drs,
                     "est_po": e["dT_po"], "full_po": dch, "v2_est": x.get("v2_est")})
    out = {"split": split, "n": len(rows), "rows": rows}
    if len(rows) >= 3:
        est_a = np.array([r["est"] for r in rows]); full_a = np.array([r["full"] for r in rows])
        out.update(corr=float(np.corrcoef(est_a, full_a)[0, 1]),
                   slope=float(np.polyfit(full_a, est_a, 1)[0]),
                   sign=float(np.mean(np.sign(est_a) == np.sign(full_a))),
                   mae=float(np.mean(np.abs(est_a - full_a))),
                   mean_abs_full=float(np.mean(np.abs(full_a))),
                   rs_corr=float(np.corrcoef([r["est_rs"] for r in rows], [r["full_rs"] for r in rows])[0, 1]))
        v2 = [r["v2_est"] for r in rows if r["v2_est"] is not None]
        if len(v2) == len(rows):
            out["v2_corr"] = float(np.corrcoef(np.array(v2), full_a)[0, 1])
            out["v2_slope"] = float(np.polyfit(full_a, np.array(v2), 1)[0])
        out["meets"] = (out["corr"] >= TARGET["corr"] and TARGET["slope"][0] <= out["slope"] <= TARGET["slope"][1]
                        and out["sign"] >= TARGET["sign"])
    return out


def cmd_report(a) -> int:
    out_dir = Path(a.dir)
    lst = load_list(out_dir)
    ef = out_dir / "estimates.json"
    if not ef.is_file():
        raise Refused(f"{ef} is missing: run estimate first")
    est = {r["id"]: r for r in json.loads(ef.read_text(encoding="utf-8"))["rows"]}
    passes = {}
    for f in sorted((out_dir / "passes").glob("*.json")):
        passes[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    if "base" not in passes:
        raise Refused("no base pass yet")
    res = {}
    for split in (a.split,) if a.split else ("dev", "held_out", "all"):
        t = table(lst, est, passes, split)
        res[split] = t
        print(f"\n== {split}: n = {t['n']}")
        if t["n"] >= 3:
            print(f"   correlation {t['corr']:.3f} (target >= {TARGET['corr']}); slope est on full {t['slope']:.3f} "
                  f"(target {TARGET['slope'][0]}-{TARGET['slope'][1]}); sign {t['sign']:.0%} (target >= "
                  f"{TARGET['sign']:.0%}); MAE {t['mae']:.4f} vs mean |full| {t['mean_abs_full']:.4f}; "
                  f"RS-title corr {t['rs_corr']:.3f}" + (f"; V2's estimate: corr {t['v2_corr']:.3f}, slope "
                                                        f"{t['v2_slope']:.3f}" if "v2_corr" in t else "")
                  + f" -> {'MEETS' if t['meets'] else 'DOES NOT MEET'} the target")
        for r in t["rows"]:
            print(f"   {r['id']:2d} {r['manager']:8s} {r['move'][:58]:58s} est {r['est']:+.4f} full {r['full']:+.4f}"
                  f" | RS {r['est_rs']:+.4f}/{r['full_rs']:+.4f}" + (f" | V2 {r['v2_est']:+.4f}" if r['v2_est'] is not None else ""))
    if a.save:
        write_json(out_dir / "report.json", res, out_dir)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pass"); p.add_argument("key"); p.add_argument("--dir", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--verify-reuse", action="store_true")
    p.add_argument("--budget", type=float, default=70.0,
                   help="seconds after which the second half waits for the next call")
    e = sub.add_parser("estimate"); e.add_argument("--dir", required=True)
    e.add_argument("--label", default="working tree")
    r = sub.add_parser("report"); r.add_argument("--dir", required=True)
    r.add_argument("--split", choices=("dev", "held_out", "all")); r.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    try:
        return {"pass": cmd_pass, "estimate": cmd_estimate, "report": cmd_report}[a.cmd](a)
    except Refused as err:
        print(f"REFUSED: {err}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
