"""Fit keepability v3, validate it leave-one-season-out, and write its parameters.

    python scripts/fit_keepability_v3.py [--baseline output/keeper_backtest.json]
        [--params config/keepability_v3_params.json] [--fit-date YYYY-MM-DD]
        [--out report.md] [--no-live]

KEEPABILITY_V3_DESIGN.md; HANDOFF_KEEPABILITY_B_FIT_2026-10-29. Once a season,
after the keepers are chosen: refitting is a deliberate act; the weekly build
only reads the parameters file (modules/keepability_v3.predict).

1. The dataset: every decision 2021-22 .. 2026-27 at week2 / mid / end
   (modules/keeper_history), cached under data/.cache/ keyed on its inputs.
2. Specification comparison by HELD-OUT log-likelihood, leaving one season
   out: fit on five decisions, score the sixth, rotate. One specification is
   chosen for all three points (the best total).
3. The chosen specification: coefficients per point (fitted on all six) with
   standard errors; in-sample against held-out log-likelihood; hits out of 24
   (top 6 per roster, held out) beside v2.2 and rules A-C (--baseline, written
   by scripts/keeper_backtest.py --json); calibration of the held-out keep
   probabilities; 2021-22 in or out.
4. The parameters file.
5. This season at week 2: today's rosters, top 8 per team at K = 5 and K = 6.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import keeper_history as kh                  # noqa: E402
from modules import keepability_v3 as M                    # noqa: E402

BASE = ["kept", "log_draft_rank", "undrafted", "level", "availability", "age"]
SPECS = {
    "age linear":               BASE,
    "age + young":              BASE + ["young"],
    "age quadratic":            BASE + ["age_sq"],
    "age + young + trade":      BASE + ["young", "undrafted_trade"],
    "variant: + roster rank":   BASE + ["young", "fppg_rank"],
}
BINS = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0000001]
CACHE = ROOT / "data" / ".cache" / "keepability_v3_dataset.pkl"
INPUT_FILES = [kh.PLAYERLOG, kh.DRAFTS, kh.DRAFTS_CURRENT, kh.TRADES, kh.AGES_FILE,
               "modules/keeper_history.py"]


# ---------------------------------------------------------------------------
# the dataset
# ---------------------------------------------------------------------------

def _inputs_key(root=ROOT) -> str:
    h = hashlib.sha256()
    for f in INPUT_FILES:
        h.update(f.encode())
        h.update((Path(root) / f).read_bytes())
    return h.hexdigest()


def dataset(root=ROOT, use_cache: bool = True) -> dict:
    """{(decision, point): Snapshot}, cached on the bytes of every input."""
    key = _inputs_key(root)
    if use_cache and CACHE.is_file():
        blob = pickle.loads(CACHE.read_bytes())
        if blob.get("key") == key:
            return blob["snaps"]
    inputs = kh.Inputs.load(root)
    snaps = kh.build(inputs, ages=kh.load_ages(kh.age_seasons(), root))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".pkl.tmp")
    tmp.write_bytes(pickle.dumps({"key": key, "snaps": snaps}))
    tmp.replace(CACHE)
    return snaps


def rosters(snaps, decisions, point, features, drop_empty=True):
    """(Rosters, [(decision, manager, candidates)]): each manager's roster at
    `point`, labelled with which of them he kept; K = the keepers present."""
    Xs, chosen, K, labels = [], [], [], []
    for d in decisions:
        snap = snaps[(d, point)]
        fill = M.fill_values(snap.candidates)
        for m, cands in sorted(snap.by_manager().items()):
            cands = sorted(cands, key=lambda c: c.player)
            ch = np.array([c.kept_next for c in cands])
            if drop_empty and not ch.any():
                continue
            Xs.append(M.design(cands, features, fill))
            chosen.append(ch)
            K.append(int(ch.sum()))
            labels.append((d, m, cands))
    return M.Rosters(Xs, chosen, K, labels)


def missing_keepers(snaps, decisions, point) -> dict:
    """{m: share}: how many of a manager's keepers were NOT on his roster at
    `point`, across the decisions given."""
    c = Counter()
    for d in decisions:
        snap = snaps[(d, point)]
        absent = Counter(m for m, _ in snap.absent)
        for m in snap.keepers:
            c[absent.get(m, 0)] += 1
    n = sum(c.values())
    return {int(k): v / n for k, v in sorted(c.items())}


def dataset_hash(snaps, features) -> str:
    h = hashlib.sha256()
    for (d, p) in sorted(snaps):
        for c in sorted(snaps[(d, p)].candidates, key=lambda c: (c.manager, c.player)):
            h.update(json.dumps([d, p, c.manager, c.player, c.kept_next,
                                 [getattr(c, a) for a in ("kept", "draft_rank", "acquired", "level",
                                                          "availability", "age", "fppg_rank")]],
                                default=str).encode())
    h.update(json.dumps(features).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def top_k(ros, beta, k=6) -> list:
    """Per roster, the names of the k highest scores, ties by name."""
    out = []
    for r, (_d, _m, cands) in enumerate(ros.labels):
        s = ros.X[r, :len(cands)] @ beta
        order = sorted(range(len(cands)), key=lambda i: (-s[i], cands[i].player))
        out.append([cands[i].player for i in order[:k]])
    return out


def loso(snaps, features, point, decisions=kh.DECISIONS, exclude_from_fit=()):
    """Leave one season out. {held-out decision: {...}}: the fold's beta,
    held-out log-likelihood (model and uniform), hits, and keep probabilities
    for K = 6 averaged over the missing-keeper counts of the fitted seasons."""
    out = {}
    for held in decisions:
        train = [d for d in decisions if d != held and d not in exclude_from_fit]
        assert held not in train
        fit = M.fit(rosters(snaps, train, point, features))
        test = rosters(snaps, [held], point, features)
        everyone = rosters(snaps, [held], point, features, drop_empty=False)
        miss = missing_keepers(snaps, train, point)
        pi = M.mixture_inclusion(everyone, fit["beta"], 6, miss)
        cal = []
        for r, (_d, _m, cands) in enumerate(everyone.labels):
            cal += [(float(pi[r, i]), bool(c.kept_next)) for i, c in enumerate(cands)]
        tops = top_k(everyone, fit["beta"])
        hits = sum(len(set(t) & set(snaps[(held, point)].keepers.get(m, [])))
                   for t, (_d, m, _c) in zip(tops, everyone.labels))
        out[held] = {"beta": fit["beta"], "ll": float(M.loglik(test, fit["beta"]).sum()),
                     "ll_uniform": float(M.uniform_loglik(test).sum()), "n_rosters": len(test.K),
                     "hits": hits, "calibration": cal, "train": train}
    return out


def calibration_table(pairs) -> list:
    rows = []
    for lo, hi in zip(BINS, BINS[1:]):
        cell = [(p, k) for p, k in pairs if lo <= p < hi]
        if cell:
            rows.append((lo, min(hi, 1.0), len(cell), float(np.mean([p for p, _ in cell])),
                         float(np.mean([k for _, k in cell]))))
        else:
            rows.append((lo, min(hi, 1.0), 0, None, None))
    return rows


# ---------------------------------------------------------------------------
# this season, live
# ---------------------------------------------------------------------------

NAMED = {"Nick": ["Karl-Anthony Towns", "Domantas Sabonis", "Dyson Daniels", "Damian Lillard"],
         "Garrett": ["Alex Sarr", "VJ Edgecombe"],
         "Hayden": ["Joel Embiid", "Zach LaVine", "Darius Acuff Jr."]}


def live_table(params, root=ROOT) -> tuple:
    from modules.data_loader import load_all_data
    inputs = kh.Inputs.load(root)
    li, season = kh.live_inputs(root, inputs)
    data = load_all_data(root)
    ros = {m: list(v) for m, v in data.get_current_rosters().items() if v}
    snap = kh.live_snapshot(li, season, ros, kh.load_ages(kh.age_seasons(), root))
    by = snap.by_manager()
    p5 = M.predict(by, "week2", 5, params)
    p6 = M.predict(by, "week2", 6, params)
    return snap, p5, p6


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def _fmt(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", default=str(ROOT / "output" / "keeper_backtest.json"))
    ap.add_argument("--params", default=str(M.PARAMS_FILE))
    ap.add_argument("--fit-date", default=date.today().isoformat())
    ap.add_argument("--out")
    ap.add_argument("--no-live", action="store_true")
    ap.add_argument("--specs", nargs="*", help="compare only these specifications")
    a = ap.parse_args(argv)

    snaps = dataset()
    L = []
    say = L.append

    # 2. the specification comparison
    specs = {k: v for k, v in SPECS.items() if not a.specs or k in a.specs}
    held = {}
    say("## Specification comparison: held-out log-likelihood (leave one season out)\n")
    say("| specification | k | " + " | ".join(M.POINTS) + " | total | vs uniform |")
    say("|---|---|" + "---|" * (len(M.POINTS) + 2))
    for name, feats in specs.items():
        try:
            res = {p: loso(snaps, feats, p) for p in M.POINTS}
        except M.FitError as e:
            say(f"| {name} | {len(feats)} | not estimable: {e} | | | | |")
            continue
        held[name] = res
        lls = [sum(v["ll"] for v in res[p].values()) for p in M.POINTS]
        uni = sum(v["ll_uniform"] for p in M.POINTS for v in res[p].values())
        say(f"| {name} | {len(feats)} | " + " | ".join(f"{x:.1f}" for x in lls)
            + f" | **{sum(lls):.1f}** | +{sum(lls) - uni:.1f} |")
    choosable = {k: v for k, v in held.items() if not k.startswith("variant")}
    best = max(choosable, key=lambda k: sum(v["ll"] for p in M.POINTS for v in held[k][p].values()))
    feats = SPECS[best]
    say(f"\nChosen: **{best}** ({len(feats)} coefficients per point): the best held-out total "
        "among the non-variant specifications.\n")

    # 3. the chosen specification
    params = {"version": 3, "features": feats, "feature_text": {f: M.FEATURE_TEXT[f] for f in feats},
              "specification": best,
              "why": "highest summed held-out log-likelihood (leave one season out, all three points) "
                     "among: " + ", ".join(k for k in SPECS if not k.startswith("variant")),
              "fitted_on": list(kh.DECISIONS), "fit_date": a.fit_date,
              "dataset_sha256": dataset_hash(snaps, feats),
              "shrinkage": {"k0_prior_season": kh.K0_PRIOR_SEASON, "k0_league_mean": kh.K0_LEAGUE_MEAN,
                            "prior_min_games": kh.PRIOR_MIN_GAMES,
                            "source": "measured 10-23/10-28 against these priors "
                                      "(REVIEW_PROJECTION_VS_ACTUALS_RESULT_2026-10-23, "
                                      "SHRINKAGE_CURVE_RESULT_2026-10-28); reused, not refit"},
              "age_center": M.AGE_CENTER, "young_age": M.YOUNG_AGE, "rank_center": M.RANK_CENTER,
              "prior": {"sd": M.PRIOR_SCALE, "on": "each coefficient times its feature's scale "
                        "(an indicator as is, a continuous input at 2 sd); Gelman et al. 2008. "
                        "Stops quasi-separation: plain ML put 'undrafted' at week 2 at -23.7"},
              "points": {}}
    say("## Coefficients (fitted on all six decisions), standard errors in brackets\n")
    say("| feature | " + " | ".join(M.POINTS) + " |")
    say("|---|" + "---|" * len(M.POINTS))
    fits = {}
    for p in M.POINTS:
        ros = rosters(snaps, kh.DECISIONS, p, feats)
        fits[p] = M.fit(ros)
        n_all = rosters(snaps, kh.DECISIONS, p, feats)
        ll_in = fits[p]["loglik"] / len(ros.K)
        ll_out = sum(v["ll"] for v in held[best][p].values()) / sum(v["n_rosters"] for v in held[best][p].values())
        uni = float(M.uniform_loglik(ros).sum()) / len(ros.K)
        params["points"][p] = {
            "coef": {f: round(float(b), 6) for f, b in zip(feats, fits[p]["beta"])},
            "se": {f: round(float(s), 6) for f, s in zip(feats, fits[p]["se"])},
            "missing_keepers": {str(k): round(v, 6) for k, v in missing_keepers(snaps, kh.DECISIONS, p).items()},
            "n_rosters": len(ros.K), "n_players": int(ros.mask.sum()),
            "loglik_per_roster": {"in_sample": round(ll_in, 4), "held_out": round(ll_out, 4),
                                  "uniform": round(uni, 4)},
        }
    for i, f in enumerate(feats):
        say(f"| {f} | " + " | ".join(f"{fits[p]['beta'][i]:+.3f} ({fits[p]['se'][i]:.3f})" for p in M.POINTS) + " |")
    say("\nLog-likelihood per roster: in-sample / held-out / uniform\n")
    for p in M.POINTS:
        q = params["points"][p]["loglik_per_roster"]
        say(f"- {p}: {q['in_sample']:.3f} / {q['held_out']:.3f} / {q['uniform']:.3f} "
            f"(gap in-held {q['in_sample'] - q['held_out']:.3f}; held-out gain over uniform "
            f"{q['held_out'] - q['uniform']:.3f})")

    # hits
    base = json.loads(Path(a.baseline).read_text(encoding="utf-8")) if Path(a.baseline).is_file() else None
    say("\n## Hits out of 24 (held out), beside step A\n")
    cols = [(d, p) for d in kh.DECISIONS for p in M.POINTS]
    say("| method | " + " | ".join(f"{d[2:]} {p}" for d, p in cols) + " | total | w/o 2021-22 |")
    say("|---|" + "---|" * (len(cols) + 2))
    def row(name, get):
        cells = [get(d, p) for d, p in cols]
        tot = sum(cells)
        wo = sum(c for (d, _), c in zip(cols, cells) if d != "2021-22")
        say(f"| {name} | " + " | ".join(str(c) for c in cells) + f" | {tot} | {wo} |")
    row("*ceiling*", lambda d, p: snaps[(d, p)].ceiling)
    row("**v3**", lambda d, p: held[best][p][d]["hits"])
    if base:
        for m in ("v2.2", "A", "B", "C"):
            row(m, lambda d, p, m=m: base["hits"][f"{m}|{d}|{p}"])
    say("\nBy point, without 2021-22: " + "; ".join(
        f"{p} v3 {sum(held[best][p][d]['hits'] for d in kh.DECISIONS[1:])}"
        + (f", A {sum(base['hits'][f'A|{d}|{p}'] for d in kh.DECISIONS[1:])}"
           f", v2.2 {sum(base['hits'][f'v2.2|{d}|{p}'] for d in kh.DECISIONS[1:])}" if base else "")
        + f" / {sum(snaps[(d, p)].ceiling for d in kh.DECISIONS[1:])}"
        for p in M.POINTS))

    # calibration
    say("\n## Calibration (held out; K = 6 averaged over the missing-keeper counts of the fitted seasons)\n")
    say("| predicted | " + " | ".join(f"{p}: n, mean predicted, share kept" for p in M.POINTS) + " |")
    say("|---|" + "---|" * len(M.POINTS))
    tabs = {p: calibration_table([x for v in held[best][p].values() for x in v["calibration"]]) for p in M.POINTS}
    for i, (lo, hi, *_r) in enumerate(tabs[M.POINTS[0]]):
        say(f"| {lo:.0%}-{hi:.0%} | " + " | ".join(
            f"{t[i][2]}, {_fmt(t[i][3] and 100 * t[i][3], 0)}%, {_fmt(t[i][4] and 100 * t[i][4], 0)}%"
            if t[i][2] else "0" for t in (tabs[p] for p in M.POINTS)) + " |")
    for p in M.POINTS:
        allp = [x for v in held[best][p].values() for x in v["calibration"]]
        brier = float(np.mean([(q - k) ** 2 for q, k in allp]))
        say(f"- {p}: Brier {brier:.4f}; probabilities sum to {sum(q for q, _ in allp):.1f} against "
            f"{sum(k for _, k in allp)} keepers on these rosters")

    # 2021-22 in or out
    say("\n## 2021-22 in or out of the fit\n")
    say("| point | feature | with 2021-22 | without |")
    say("|---|---|---|---|")
    without = {}
    for p in M.POINTS:
        later = list(kh.DECISIONS[1:])
        f_wo = M.fit(rosters(snaps, later, p, feats))
        for i, f in enumerate(feats):
            say(f"| {p} | {f} | {fits[p]['beta'][i]:+.3f} | {f_wo['beta'][i]:+.3f} |")
        without[p] = loso(snaps, feats, p, decisions=later)
    say("\nHeld-out hits on the other five seasons, fitted with / without 2021-22: " + "; ".join(
        f"{p} {sum(held[best][p][d]['hits'] for d in kh.DECISIONS[1:])} / "
        f"{sum(without[p][d]['hits'] for d in kh.DECISIONS[1:])}" for p in M.POINTS))

    # the parameters file
    Path(a.params).write_text(json.dumps(params, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    say(f"\nWrote {a.params} (dataset sha256 {params['dataset_sha256'][:16]}...).")

    # age, in plain words
    say("\n## The age effect, in points per game\n")
    for p in M.POINTS:
        c = params["points"][p]["coef"]
        rate = c["level"]
        line = f"- {p}: a year of age is worth {c['age'] / rate:+.2f} FPPG of level"
        if "young" in c:
            line += f"; being {M.YOUNG_AGE} or under is worth {c['young'] / rate:+.2f} FPPG"
        if "age_sq" in c:
            line += f"; curvature {c['age_sq'] / rate:+.2f} FPPG per (years/sqrt10)^2"
        line += f"; being a keeper already is worth {c['kept'] / rate:+.1f} FPPG"
        say(line)

    # this season
    if not a.no_live:
        snap, p5, p6 = live_table(params)
        say(f"\n## 2026-27 at week 2: today's rosters, log through {snap.as_of}\n")
        info = {(c.manager, c.player): c for c in snap.candidates}
        for m in sorted(p5):
            say(f"**{m}**\n")
            say("| # | player | keep, K=5 | keep, K=6 | kept | draft rank | level | games | age |")
            say("|---|---|---|---|---|---|---|---|---|")
            six = dict(p6[m])
            for i, (n, q) in enumerate(p5[m][:8], 1):
                c = info[(m, n)]
                say(f"| {i} | {n} | {q:.0%} | {six[n]:.0%} | {'yes' if c.kept else ''} | "
                    f"{c.draft_rank or ''} | {c.level:.1f} | {c.games} | {c.age} |")
                if i == 5:
                    say("| | *--- the line at 5 (the 6th: 6 if he wins the Cup) ---* | | | | | | | |")
            say("")
        say("Named:")
        for m, names in NAMED.items():
            five = {n: (i, q) for i, (n, q) in enumerate(p5[m], 1)}
            six = dict(p6[m])
            for n in names:
                if n in five:
                    say(f"- {n} ({m}): #{five[n][0]} on his roster, {five[n][1]:.0%} at K=5, {six[n]:.0%} at K=6")
                else:
                    say(f"- {n} ({m}): not on today's roster")

    text = "\n".join(L) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
