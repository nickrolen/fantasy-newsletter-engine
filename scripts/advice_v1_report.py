"""
advice_v1_report.py -- the 2025-26 replay's numbers (advice v2 V1).

    python scripts\\advice_v1_replay.py report --out _to_delete\\v1

Reads out/replay/week_NN.json (scripts/advice_v1_replay.py run) and writes
out/report.json; prints the summary. Every pick is scored on what really
happened over its two weeks (modules/advice_replay.realised). Intervals are
95%, from a bootstrap that resamples whole Mondays (the four managers of one
Monday share a pool and a slate, so they are not independent).
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

REGULAR_LAST_MONDAY = 20          # its horizon (20, 21) is all regular season
GRID_LAM = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
GRID_MODES = ("wins", "wins_penalty")
GRID_W2 = (0.5, 1.0)
BARS = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08)
BOOT = 10000


def load(out: Path) -> list:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted((out / "replay").glob("week_*.json"))]


def score(f, mode, w1, w2, lam, lbar):
    """advice_v2.Weighting.score on a checkpoint's finalist."""
    if mode == "title":
        return f["dT_h"] + lam * f["dT_l"]
    t = min(0.0, f["dT_l"]) if mode == "wins_penalty" else f["dT_l"]
    later = lam * t / lbar if (lam and lbar) else 0.0
    return w1 * f["dwp"][0] + w2 * f["dwp"][1] + later


def pick(fins, mode, w1, w2, lam, lbar, bar=0.0):
    ranked = sorted(fins, key=lambda f: (-score(f, mode, w1, w2, lam, lbar), f["kind"], f["add"], f["drop"] or ""))
    if not ranked:
        return None, None
    s = score(ranked[0], mode, w1, w2, lam, lbar)
    return (ranked[0], s) if s > bar else (None, s)


def gain(x):
    """Realised two-week points: a finalist carries real_pts, a rule's result pts."""
    return 0.0 if x is None else float(sum(x.get("real_pts", x.get("pts"))))


def flips(x):
    return 0 if x is None else int(sum(x.get("real_flip", x.get("flip"))))


def boot_ci(diffs_by_monday: dict, rng) -> tuple:
    keys = sorted(diffs_by_monday)
    arrs = [np.asarray(diffs_by_monday[k], float) for k in keys]
    allv = np.concatenate(arrs)
    means = []
    for _ in range(BOOT):
        idx = rng.integers(0, len(arrs), len(arrs))
        v = np.concatenate([arrs[i] for i in idx])
        means.append(v.mean())
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(allv.mean()), float(lo), float(hi), len(allv)


def compare(rows, a, b, rng):
    by_m = defaultdict(list)
    w = t = l = 0
    for r in rows:
        d = r[a] - r[b]
        by_m[r["week"]].append(d)
        w += d > 1e-9
        l += d < -1e-9
        t += abs(d) <= 1e-9
    mean, lo, hi, n = boot_ci(by_m, rng)
    verdict = "ahead" if lo > 0 else ("behind" if hi < 0 else "can't tell")
    return {"mean": round(mean, 2), "ci": [round(lo, 2), round(hi, 2)], "n": n,
            "wins": int(w), "ties": int(t), "losses": int(l), "verdict": verdict}


def rows_for(weeks, mode, w1, w2, lam, bar=0.0):
    out = []
    for rec in weeks:
        for m, d in rec["managers"].items():
            fins = d["finalists"]
            top, s = pick(fins, mode, w1, w2, lam, d["lbar"], bar)
            drop = top["drop"] if top is not None and top["kind"] == "add_drop" else None
            if drop is None:
                drop = next((f["drop"] for f in fins if f["kind"] == "add_drop"), None)
            com = d["common"].get(drop) if drop else None
            r = {"week": rec["week"], "manager": m, "top": top, "score": s,
                 "engine": gain(top), "engine_flips": flips(top),
                 "most_games": gain(d["rules"]["most_games"]["real"]) if d["rules"]["most_games"]["move"] else 0.0,
                 "highest_projection": gain(d["rules"]["highest_projection"]["real"]) if d["rules"]["highest_projection"]["move"] else 0.0,
                 "mg_flips": flips(d["rules"]["most_games"]["real"]) if d["rules"]["most_games"]["move"] else 0,
                 "hp_flips": flips(d["rules"]["highest_projection"]["real"]) if d["rules"]["highest_projection"]["move"] else 0,
                 "mg_move": d["rules"]["most_games"]["move"], "hp_move": d["rules"]["highest_projection"]["move"],
                 "common_drop": drop}
            if com is not None:
                r["most_games_common"] = gain(com["most_games"]["real"]) if com["most_games"]["move"] else 0.0
                r["highest_projection_common"] = gain(com["highest_projection"]["real"]) if com["highest_projection"]["move"] else 0.0
            out.append(r)
    return out


def summarise(rows, rng, label):
    s = {"label": label, "n": len(rows)}
    for k in ("engine", "most_games", "highest_projection"):
        v = [r[k] for r in rows]
        s[k] = {"mean": round(float(np.mean(v)), 2), "sd": round(float(np.std(v)), 1),
                "moves": int(sum(1 for r in rows if (r["top"] if k == "engine" else r[{"most_games": "mg_move", "highest_projection": "hp_move"}[k]]) is not None))}
    s["flips"] = {"engine": sum(r["engine_flips"] for r in rows), "most_games": sum(r["mg_flips"] for r in rows),
                  "highest_projection": sum(r["hp_flips"] for r in rows)}
    s["engine_vs_most_games"] = compare(rows, "engine", "most_games", rng)
    s["engine_vs_highest_projection"] = compare(rows, "engine", "highest_projection", rng)
    com = [r for r in rows if "most_games_common" in r]
    if com:
        s["common_drop"] = {"n": len(com),
                            "engine_vs_most_games": compare(com, "engine", "most_games_common", rng),
                            "engine_vs_highest_projection": compare(com, "engine", "highest_projection_common", rng),
                            "most_games_common_mean": round(float(np.mean([r["most_games_common"] for r in com])), 2),
                            "highest_projection_common_mean": round(float(np.mean([r["highest_projection_common"] for r in com])), 2)}
    return s


def later_real(season, actuals, week: int, top) -> float:
    """Player-level, not lineup-aware: the add's real fantasy points minus the
    drop's (and the follow-up drop's) over the regular-season weeks after the
    pick's two-week horizon. The long-run lens on the title-odds term, which
    two-week scoring cannot see."""
    if top is None:
        return 0.0
    from modules import advice_replay as ar
    tot = 0.0
    for w in range(week + 2, ar.REGULAR_THROUGH + 1):
        for d in ar.season_dates(season, w):
            tot += actuals.played(top["add"], d) or 0.0
            for x in (top["drop"], top.get("followup")):
                if x:
                    tot -= actuals.played(x, d) or 0.0
    return tot


def report(out: Path):
    weeks = load(out)
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from advice_v1_replay import load_season
    from modules import advice_replay as ar
    season = load_season(out)
    actuals = ar.Actuals(season.games)
    rng = np.random.default_rng(20261105)
    reg = [w for w in weeks if w["week"] <= REGULAR_LAST_MONDAY]
    po = [w for w in weeks if w["week"] > REGULAR_LAST_MONDAY]
    res = {"mondays": [w["week"] for w in weeks], "regular": {}, "playoffs": {}}
    named = {"wins + 0.5 title penalty": ("wins_penalty", 1, 1, 0.5),
             "wins + 1 title penalty": ("wins_penalty", 1, 1, 1.0),
             "wins only": ("wins", 1, 1, 0.0), "wins + 0.5 title": ("wins", 1, 1, 0.5),
             "wins + 1 title": ("wins", 1, 1, 1.0), "wins + 2 title": ("wins", 1, 1, 2.0),
             "this week only": ("wins", 1, 0, 0.0), "title odds only": ("title", 0, 0, 1.0)}
    for name, (mode, w1, w2, lam) in named.items():
        res["regular"][name] = summarise(rows_for(reg, mode, w1, w2, lam), rng, name)
        if po:
            res["playoffs"][name] = summarise(rows_for(po, mode, w1, w2, lam), rng, name)
    # the calibration grid (regular season)
    grid = []
    for mode in GRID_MODES:
      for w2 in GRID_W2:
        for lam in GRID_LAM:
            rows = rows_for(reg, mode, 1, w2, lam)
            grid.append({"mode": mode, "w2": w2, "lam": lam,
                         "later_real_mean": round(float(np.mean([later_real(season, actuals, r["week"], r["top"]) for r in rows])), 1), "engine_mean": round(float(np.mean([r["engine"] for r in rows])), 2),
                         "minus_most_games": compare(rows, "engine", "most_games", rng)["mean"],
                         "flips": sum(r["engine_flips"] for r in rows),
                         "moves": sum(1 for r in rows if r["top"] is not None)})
    res["grid"] = grid
    res["playoffs_note"] = ("2 Mondays x 4 managers: a bootstrap over 2 clusters is degenerate; "
                            "read the playoff numbers as anecdotes, not intervals")
    # the long-run lens and predicted-vs-realised, per weighting (regular season)
    lens = {}
    for name, (mode, w1, w2, lam) in named.items():
        rows = rows_for(reg, mode, w1, w2, lam)
        tops = [(r["week"], r["top"]) for r in rows]
        pred = [sum(t["dpts"]) for _w, t in tops if t is not None]
        real = [sum(t["real_pts"]) for _w, t in tops if t is not None]
        lens[name] = {"later_real_mean": round(float(np.mean([later_real(season, actuals, w, t) for w, t in tops])), 1),
                      "later_pred_mean": round(float(np.mean([t["dpl"] if t else 0.0 for _w, t in tops])), 1),
                      "pred_two_week_mean": round(float(np.mean(pred)), 1) if pred else None,
                      "real_two_week_mean": round(float(np.mean(real)), 1) if real else None}
    mg_later = []
    for rec in reg:
        for m, d in rec["managers"].items():
            mo = d["rules"]["most_games"]["move"]
            mg_later.append(later_real(season, actuals, rec["week"], mo and {"add": mo["add"], "drop": mo["drop"]}))
    lens["most_games"] = {"later_real_mean": round(float(np.mean(mg_later)), 1)}
    hp_later = []
    for rec in reg:
        for m, d in rec["managers"].items():
            mo = d["rules"]["highest_projection"]["move"]
            hp_later.append(later_real(season, actuals, rec["week"], mo and {"add": mo["add"], "drop": mo["drop"]}))
    lens["highest_projection"] = {"later_real_mean": round(float(np.mean(hp_later)), 1)}
    res["long_run"] = lens
    # the last add's bar: with one add left, which picks are withheld and what they really gained
    base_rows = rows_for(reg, "wins_penalty", 1, 1, 0.5)      # the recommended weighting
    bars = []
    for b in BARS:
        withheld = [r for r in base_rows if r["top"] is not None and r["score"] <= b]
        bars.append({"bar": b, "withheld": len(withheld),
                     "withheld_mean_gain": round(float(np.mean([r["engine"] for r in withheld])), 2) if withheld else None,
                     "kept_mean_gain": round(float(np.mean([r["engine"] for r in base_rows if r["top"] is not None and r["score"] > b])), 2)})
    res["last_add"] = bars
    # insurance: how often a manager's roster gains a newly-O player before the next Monday
    by_week = {w["week"]: w for w in weeks}
    newly, n = 0, 0
    for wk, rec in by_week.items():
        nxt = by_week.get(wk + 1)
        if not nxt:
            continue
        for m, d in rec["managers"].items():
            n += 1
            now = set(d["o_on_roster"])
            later = set(nxt["managers"][m]["o_on_roster"])
            newly += bool(later - now)
    scores = [r["score"] for r in base_rows if r["top"] is not None]
    res["insurance"] = {"p_newly_out_by_next_monday": round(newly / n, 3) if n else None,
                        "median_top_score": round(float(np.median(scores)), 4) if scores else None}
    # personalisation (recommended weighting chosen below; reported for "wins + 0.5 title")
    pers = []
    for rec in reg:
        tops = []
        for m, d in rec["managers"].items():
            t, s = pick(d["finalists"], "wins_penalty", 1, 1, 0.5, d["lbar"])
            tops.append((m, t["add"] if t else None, (t["dwp"][0] + t["dwp"][1]) if t else 0.0))
        adds = [a for _m, a, _g in tops if a]
        pers.append({"week": rec["week"], "distinct_adds": len(set(adds)), "with_pick": len(adds),
                     "gain_spread": round(max(g for *_x, g in tops) - min(g for *_x, g in tops), 4)})
    res["personalisation"] = {"by_monday": pers,
                              "mean_distinct_adds": round(float(np.mean([p["distinct_adds"] for p in pers])), 2),
                              "mondays_all_same": sum(1 for p in pers if p["with_pick"] > 1 and p["distinct_adds"] == 1),
                              "mean_gain_spread": round(float(np.mean([p["gain_spread"] for p in pers])), 4)}
    # the title-odds estimate against full season runs
    lin, full = [], []
    for rec in weeks:
        for m, d in rec["managers"].items():
            for c in d["title_check"]:
                lin.append(c["linear"]); full.append(c["full"])
    lin, full = np.array(lin), np.array(full)
    res["title_check"] = {"n": int(len(lin)), "corr": round(float(np.corrcoef(lin, full)[0, 1]), 3) if len(lin) > 2 else None,
                          "mean_abs_err": round(float(np.mean(np.abs(lin - full))), 4),
                          "mean_abs_full": round(float(np.mean(np.abs(full))), 4),
                          "sign_agree": round(float(np.mean(np.sign(lin) == np.sign(full))), 3),
                          "slope_full_on_linear": round(float(np.polyfit(lin, full, 1)[0]), 3) if len(lin) > 2 else None}
    # move kinds and the gap to most games, by kind
    kinds = defaultdict(list)
    for r in base_rows:
        k = r["top"]["kind"] if r["top"] else "none"
        kinds[k].append(r["engine"] - r["most_games"])
    res["gap_by_kind"] = {k: {"n": len(v), "mean": round(float(np.mean(v)), 2)} for k, v in kinds.items()}
    res["gap_by_monday"] = {}
    for r in base_rows:
        res["gap_by_monday"].setdefault(r["week"], []).append(round(r["engine"] - r["most_games"], 1))
    (out / "report.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    for k, v in res["regular"].items():
        e, a, b, c = v["engine"], v["engine_vs_most_games"], v["engine_vs_highest_projection"], v.get("common_drop", {})
        print(f"{k:18s} eng {e['mean']:6.1f} ({e['moves']}) | MG {v['most_games']['mean']:5.1f} HP {v['highest_projection']['mean']:5.1f}"
              f" | E-MG {a['mean']:6.1f} {a['ci']} {a['wins']}-{a['ties']}-{a['losses']} {a['verdict']}"
              f" | E-HP {b['mean']:6.1f} {b['ci']} {b['verdict']}"
              f" | common E-MG {c['engine_vs_most_games']['mean']:6.1f} {c['engine_vs_most_games']['ci']} {c['engine_vs_most_games']['verdict']}"
              f" E-HP {c['engine_vs_highest_projection']['mean']:6.1f} {c['engine_vs_highest_projection']['ci']} {c['engine_vs_highest_projection']['verdict']}"
              f" | flips {v['flips']}")
    for k in ("grid", "long_run", "last_add", "insurance", "title_check", "gap_by_kind"):
        print(k, json.dumps(res[k]))
    print("personalisation", {k: v for k, v in res["personalisation"].items() if k != "by_monday"})
    print("playoffs", json.dumps({k: {"engine": v["engine"], "mg": v["most_games"], "vsmg": v["engine_vs_most_games"]} for k, v in res["playoffs"].items()}))
    return res
