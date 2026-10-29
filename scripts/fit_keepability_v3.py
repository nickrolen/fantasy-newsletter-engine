"""Fit keepability v3, validate it leave-one-season-out, and write its parameters.

    python scripts/fit_keepability_v3.py [--priors P1 P2 P3 P3r] [--features "age linear"]
        [--baseline output/keeper_backtest.json] [--params config/keepability_v3_params.json]
        [--fit-date YYYY-MM-DD] [--out report.md] [--no-live]

KEEPABILITY_V3_DESIGN.md; HANDOFF_KEEPABILITY_B_FIT / _B2_PRIOR_2026-10-29. Once
a season, after the keepers are chosen: refitting is a deliberate act; the
weekly build only reads the parameters file (modules/keepability_v3.predict).

1. The dataset: every decision 2021-22 .. 2026-27 at week2 / mid / end
   (modules/keeper_history), cached under data/.cache/ keyed on its inputs.
2. Coverage: how many previous seasons each candidate has in the log.
3. k0 for each prior of the level, MEASURED on scoring (k0_pairs, measure_k0:
   the rest-of-season backtest that measured 13 on 10-23). P1 keeps step B's 13.
4. Each prior compared with the features fixed (step B chose "age linear";
   SPECS keeps the alternatives it beat): held-out log-likelihood (the deciding
   number), hits out of 24 beside rules A and v2.2 (--baseline, from
   scripts/keeper_backtest.py --json), calibration.
5. The best-likelihood prior is chosen unless it loses hits to P1 on totals;
   then both are reported and the parameters file is NOT rewritten.
6. This season at week 2 on today's rosters: P1 before, the chosen prior after.
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


def rosters(snaps, decisions, point, features, lp, drop_empty=True):
    """(Rosters, [(decision, manager, candidates)]): each manager's roster at
    `point`, labelled with which of them he kept; K = the keepers present."""
    Xs, chosen, K, labels = [], [], [], []
    for d in decisions:
        snap = snaps[(d, point)]
        fill = M.fill_values(snap.candidates, lp)
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
                                 [getattr(c, a) for a in ("kept", "draft_rank", "acquired", "games", "fppg",
                                                          "prev_lines", "league_mean", "availability",
                                                          "age", "fppg_rank")]],
                                default=str).encode())
    h.update(json.dumps(features).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# the shrinkage constant for each prior, measured on scoring (step B2)
# ---------------------------------------------------------------------------

K0_CUTOFFS = (1, 3, 5, 8, 10, 15, 20, 30)
K0_MIN_REST = 10


def k0_pairs(inputs, spec, cutoffs=K0_CUTOFFS, min_rest=K0_MIN_REST) -> dict:
    """{k: [(first-k mean, rest-of-season mean, prior)]} over every player-
    season in the log with a prior under `spec`: the method that measured
    k0 = 13 (REVIEW_PROJECTION_VS_ACTUALS_RESULT_2026-10-23 section 4) --
    predict a player's rest-of-season FPPG from the prior and his first k
    games. Appearances only, bench games included; whole previous seasons
    only; the rest must hold at least min_rest games."""
    out = {k: [] for k in cutoffs}
    for season in sorted(inputs.log):
        back = kh.previous_lines(inputs, season)
        games: dict = {}
        for r in sorted(inputs.log[season], key=lambda r: r["date"]):
            if kh.appeared(r):
                games.setdefault(r["player_name"], []).append(r["fantasy_points"])
        for name, fps in games.items():
            prior, used = M.prior_from_lines(season, back(name), spec)
            if prior is None:
                continue
            for k in cutoffs:
                if len(fps) >= k + min_rest:
                    out[k].append((float(np.mean(fps[:k])), float(np.mean(fps[k:])), prior))
    return out


def measure_k0(pairs: dict, grid=None) -> dict:
    """The k0 minimising pooled squared error of w*first-k + (1-w)*prior,
    w = k/(k+k0), across every cutoff; plus each cutoff's own best weight."""
    grid = np.arange(0.5, 80.0001, 0.1) if grid is None else grid
    sse = np.zeros(len(grid))
    for k, rows in pairs.items():
        if not rows:
            continue
        a = np.array(rows)
        w = k / (k + grid)[:, None]
        sse += (((w * a[None, :, 0] + (1 - w) * a[None, :, 2]) - a[None, :, 1]) ** 2).sum(1)
    best = float(grid[int(np.argmin(sse))])
    n = sum(len(v) for v in pairs.values())
    oracle = {}
    for k, rows in pairs.items():
        a = np.array(rows)
        ws = np.linspace(0, 1, 101)
        e = [(((w * a[:, 0] + (1 - w) * a[:, 2]) - a[:, 1]) ** 2).mean() for w in ws]
        oracle[k] = float(ws[int(np.argmin(e))])
    rmse = {k: float(np.sqrt(np.mean([((k / (k + best)) * f + (1 - k / (k + best)) * p - r) ** 2
                                      for f, r, p in rows]))) for k, rows in pairs.items() if rows}
    return {"k0": round(best, 1), "n_pairs": n, "player_seasons_at_k10": len(pairs.get(10, [])),
            "oracle_weight": oracle, "rmse": rmse}


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


def loso(snaps, features, point, lp, decisions=kh.DECISIONS, exclude_from_fit=()):
    """Leave one season out. {held-out decision: {...}}: the fold's beta,
    held-out log-likelihood (model and uniform), hits, and keep probabilities
    for K = 6 averaged over the missing-keeper counts of the fitted seasons."""
    out = {}
    for held in decisions:
        train = [d for d in decisions if d != held and d not in exclude_from_fit]
        assert held not in train
        fit = M.fit(rosters(snaps, train, point, features, lp))
        test = rosters(snaps, [held], point, features, lp)
        everyone = rosters(snaps, [held], point, features, lp, drop_empty=False)
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


def live_snapshot(root=ROOT):
    from modules.data_loader import load_all_data
    inputs = kh.Inputs.load(root)
    li, season = kh.live_inputs(root, inputs)
    data = load_all_data(root)
    ros = {m: list(v) for m, v in data.get_current_rosters().items() if v}
    return kh.live_snapshot(li, season, ros, kh.load_ages(kh.age_seasons(), root))


# ---------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------

def _fmt(x, nd=1):
    return "-" if x is None else f"{x:.{nd}f}"


P1_K0 = {"k0": 13.0, "source": "measured 10-23 against a one-season prior "
         "(REVIEW_PROJECTION_VS_ACTUALS_RESULT_2026-10-23; 401 player-seasons); step B's constant"}
K0_LEAGUE_MEAN = {"k0": 4.7, "source": "measured 10-23 against the league mean "
                  "(variance components, 589 player-seasons)"}


def level_prior(spec: str, k0: dict) -> dict:
    return {"spec": spec, "text": M.PRIOR_SPECS[spec]["text"], "k0_prior": k0["k0"],
            "k0_prior_source": k0["source"], "k0_league_mean": K0_LEAGUE_MEAN["k0"],
            "k0_league_mean_source": K0_LEAGUE_MEAN["source"]}


def evaluate(snaps, feats, lp) -> dict:
    """Leave-one-season-out at every point, and the fit on all six."""
    held = {p: loso(snaps, feats, p, lp) for p in M.POINTS}
    full = {p: M.fit(rosters(snaps, kh.DECISIONS, p, feats, lp)) for p in M.POINTS}
    return {"held": held, "full": full, "lp": lp,
            "ll": {p: sum(v["ll"] for v in held[p].values()) for p in M.POINTS},
            "hits": {p: {d: held[p][d]["hits"] for d in kh.DECISIONS} for p in M.POINTS}}


def params_for(snaps, feats, ev, spec_name, fit_date) -> dict:
    out = {"version": 3, "features": feats, "feature_text": {f: M.FEATURE_TEXT[f] for f in feats},
           "specification": spec_name, "level_prior": ev["lp"],
           "why": "features: step B's comparison (age linear). Level prior: highest summed held-out "
                  "log-likelihood among P1, P2, P3, P3r without losing hits to P1 (step B2)",
           "fitted_on": list(kh.DECISIONS), "fit_date": fit_date,
           "dataset_sha256": dataset_hash(snaps, feats + [ev["lp"]["spec"]]),
           "age_center": M.AGE_CENTER, "young_age": M.YOUNG_AGE, "rank_center": M.RANK_CENTER,
           "prior": {"sd": M.PRIOR_SCALE, "on": "each coefficient times its feature's scale "
                     "(an indicator as is, a continuous input at 2 sd); Gelman et al. 2008. "
                     "Stops quasi-separation: plain ML put 'undrafted' at week 2 at -23.7"},
           "points": {}}
    for p in M.POINTS:
        ros = rosters(snaps, kh.DECISIONS, p, feats, ev["lp"])
        f = ev["full"][p]
        hp = ev["held"][p]
        out["points"][p] = {
            "coef": {k: round(float(b), 6) for k, b in zip(feats, f["beta"])},
            "se": {k: round(float(x), 6) for k, x in zip(feats, f["se"])},
            "missing_keepers": {str(k): round(v, 6) for k, v in missing_keepers(snaps, kh.DECISIONS, p).items()},
            "n_rosters": len(ros.K), "n_players": int(ros.mask.sum()),
            "loglik_per_roster": {
                "in_sample": round(f["loglik"] / len(ros.K), 4),
                "held_out": round(sum(v["ll"] for v in hp.values()) / sum(v["n_rosters"] for v in hp.values()), 4),
                "uniform": round(float(M.uniform_loglik(ros).sum()) / len(ros.K), 4)},
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", default=str(ROOT / "output" / "keeper_backtest.json"))
    ap.add_argument("--params", default=str(M.PARAMS_FILE))
    ap.add_argument("--fit-date", default=date.today().isoformat())
    ap.add_argument("--out")
    ap.add_argument("--no-live", action="store_true")
    ap.add_argument("--features", default="age linear", choices=sorted(SPECS))
    ap.add_argument("--priors", nargs="*", default=list(M.PRIOR_SPECS))
    a = ap.parse_args(argv)

    snaps = dataset()
    inputs = kh.Inputs.load()
    feats = SPECS[a.features]
    L = []
    say = L.append

    # coverage: previous seasons in the log, per decision (season's end candidates)
    say("## Previous seasons available in the log (candidates at season's end)\n")
    say("| decision | 0 | 1 | 2 | 3 |")
    say("|---|---|---|---|---|")
    for d in kh.DECISIONS:
        c = Counter(len(x.prev_lines) for x in snaps[(d, "end")].candidates)
        say(f"| {d} | " + " | ".join(str(c.get(i, 0)) for i in range(4)) + " |")

    # k0 for each prior, measured on scoring
    say("\n## k0 for each prior (rest-of-season backtest, cutoffs " + ", ".join(map(str, K0_CUTOFFS)) + ")\n")
    say("| prior | k0 | player-seasons at k=10 | (k, n) pairs | weight at k=10 (oracle) |")
    say("|---|---|---|---|---|")
    k0s = {}
    for spec in a.priors:
        r = measure_k0(k0_pairs(inputs, spec))
        k0s[spec] = {"k0": r["k0"], "n_k10": r["player_seasons_at_k10"],
                     "source": f"measured {a.fit_date} on this run's playerlog, the method of "
                               f"REVIEW_PROJECTION_VS_ACTUALS_RESULT_2026-10-23 s4: {r['player_seasons_at_k10']} "
                               f"player-seasons at k=10, {r['n_pairs']} (k, player-season) pairs"}
        say(f"| {spec} | {r['k0']} | {r['player_seasons_at_k10']} | {r['n_pairs']} | {r['oracle_weight'][10]:.2f} |")
    if "P1" in k0s:
        say(f"\nP1 replicated here at {k0s['P1']['k0']}; P1 is run with step B's 13 so it stays the baseline.")
        k0s["P1"] = {"k0": P1_K0["k0"], "source": P1_K0["source"]}

    # the comparison
    base = json.loads(Path(a.baseline).read_text(encoding="utf-8")) if Path(a.baseline).is_file() else None
    evs = {spec: evaluate(snaps, feats, level_prior(spec, k0s[spec])) for spec in a.priors}
    say("\n## The priors compared (features: " + a.features + ")\n")
    say("| prior | k0 | held-out LL week2 | mid | end | total | hits total | w/o 2021-22 | week2 / mid / end w/o 2021-22 |")
    say("|---|---|---|---|---|---|---|---|---|")
    for spec, ev in evs.items():
        tot = sum(sum(ev["hits"][p].values()) for p in M.POINTS)
        wo = {p: sum(ev["hits"][p][d] for d in kh.DECISIONS[1:]) for p in M.POINTS}
        say(f"| {spec} | {k0s[spec]['k0']} | " + " | ".join(f"{ev['ll'][p]:.1f}" for p in M.POINTS)
            + f" | **{sum(ev['ll'].values()):.1f}** | {tot} | {sum(wo.values())} | "
            + " / ".join(str(wo[p]) for p in M.POINTS) + " |")
    if base:
        for m in ("A", "v2.2"):
            tot = sum(base["hits"][f"{m}|{d}|{p}"] for d in kh.DECISIONS for p in M.POINTS)
            wo = {p: sum(base["hits"][f"{m}|{d}|{p}"] for d in kh.DECISIONS[1:]) for p in M.POINTS}
            say(f"| rule {m} | | | | | | {tot} | {sum(wo.values())} | " + " / ".join(str(wo[p]) for p in M.POINTS) + " |")

    say("\n### Hits per season and point\n")
    cols = [(d, p) for d in kh.DECISIONS for p in M.POINTS]
    say("| method | " + " | ".join(f"{d[2:]} {p}" for d, p in cols) + " | total |")
    say("|---|" + "---|" * (len(cols) + 1))
    say("| *ceiling* | " + " | ".join(str(snaps[c].ceiling) for c in cols) + f" | {sum(snaps[c].ceiling for c in cols)} |")
    for spec, ev in evs.items():
        cells = [ev["hits"][p][d] for d, p in cols]
        say(f"| {spec} | " + " | ".join(map(str, cells)) + f" | {sum(cells)} |")
    if base:
        for m in ("A", "v2.2"):
            cells = [base["hits"][f"{m}|{d}|{p}"] for d, p in cols]
            say(f"| {m} | " + " | ".join(map(str, cells)) + f" | {sum(cells)} |")

    say("\n### Calibration (held out)\n")
    for spec, ev in evs.items():
        tabs = {p: calibration_table([x for v in ev["held"][p].values() for x in v["calibration"]]) for p in M.POINTS}
        briers = {p: float(np.mean([(q - k) ** 2 for v in ev["held"][p].values() for q, k in v["calibration"]]))
                  for p in M.POINTS}
        say(f"**{spec}** (Brier " + " / ".join(f"{briers[p]:.4f}" for p in M.POINTS) + ")\n")
        say("| predicted | " + " | ".join(f"{p}: n, predicted, kept" for p in M.POINTS) + " |")
        say("|---|" + "---|" * len(M.POINTS))
        for i, (lo, hi, *_r) in enumerate(tabs[M.POINTS[0]]):
            say(f"| {lo:.0%}-{hi:.0%} | " + " | ".join(
                f"{t[i][2]}, {100 * t[i][3]:.0f}%, {100 * t[i][4]:.0f}%" if t[i][2] else "0"
                for t in (tabs[p] for p in M.POINTS)) + " |")
        say("")

    # choose
    best = max(evs, key=lambda k: sum(evs[k]["ll"].values()))
    hits = {k: sum(sum(ev["hits"][p].values()) for p in M.POINTS) for k, ev in evs.items()}
    say(f"Best held-out likelihood: **{best}**.")
    write = True
    if "P1" in evs and hits[best] < hits["P1"]:
        say(f"**{best} loses hits to P1 on totals ({hits[best]} against {hits['P1']}): both reported, "
            "parameters NOT rewritten -- Nick decides.**")
        write = False
    ev = evs[best]
    params = params_for(snaps, feats, ev, a.features, a.fit_date)

    say(f"\n## {best}: coefficients (all six decisions), standard errors in brackets\n")
    say("| feature | " + " | ".join(M.POINTS) + " |")
    say("|---|" + "---|" * len(M.POINTS))
    for i, f in enumerate(feats):
        say(f"| {f} | " + " | ".join(f"{ev['full'][p]['beta'][i]:+.3f} ({ev['full'][p]['se'][i]:.3f})"
                                     for p in M.POINTS) + " |")
    say("\nLog-likelihood per roster, in-sample / held-out / uniform: " + "; ".join(
        f"{p} {params['points'][p]['loglik_per_roster']['in_sample']:.3f} / "
        f"{params['points'][p]['loglik_per_roster']['held_out']:.3f} / "
        f"{params['points'][p]['loglik_per_roster']['uniform']:.3f}" for p in M.POINTS))
    for p in M.POINTS:
        c = params["points"][p]["coef"]
        say(f"- {p}: a year of age is worth {c['age'] / c['level']:+.2f} FPPG of level; "
            f"being a keeper already {c['kept'] / c['level']:+.1f} FPPG")

    if write:
        Path(a.params).write_text(json.dumps(params, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        say(f"\nWrote {a.params}: prior {best}, k0 {ev['lp']['k0_prior']} "
            f"(dataset sha256 {params['dataset_sha256'][:16]}...).")

    # this season, before (P1) and after
    if not a.no_live:
        snap = live_snapshot()
        by = snap.by_manager()
        p1 = params_for(snaps, feats, evs["P1"], a.features, a.fit_date) if "P1" in evs else params
        res = {}
        for tag, pr in (("P1", p1), (best, params)):
            res[tag] = (M.predict(by, "week2", 5, pr), M.predict(by, "week2", 6, pr))
        info = {(c.manager, c.player): c for c in snap.candidates}
        say(f"\n## 2026-27 at week 2, today's rosters (log through {snap.as_of}): P1 before, {best} after\n")
        for m in sorted(by):
            say(f"**{m}** -- keep chance at K=5 / K=6\n")
            say(f"| # | P1 | {best} |")
            say("|---|---|---|")
            b5, b6 = res["P1"]
            a5, a6 = res[best]
            bb6, aa6 = dict(b6[m]), dict(a6[m])
            for i in range(8):
                nb, qb = b5[m][i]
                na, qa = a5[m][i]
                say(f"| {i + 1} | {nb} {qb:.0%} / {bb6[nb]:.0%} | {na} {qa:.0%} / {aa6[na]:.0%} |")
                if i == 4:
                    say("| | *the line at 5* | *(the 6th: 6 if he wins the Cup)* |")
            say("")
        say("Named, with the prior behind each (" + best + "):\n")
        named = {"Garrett": ["Giannis Antetokounmpo", "Alex Sarr", "VJ Edgecombe"],
                 "Nick": ["Domantas Sabonis", "Karl-Anthony Towns", "Evan Mobley", "Dyson Daniels", "Damian Lillard"],
                 "Hayden": ["Joel Embiid", "Zach LaVine", "Darius Acuff Jr."]}
        for m, names in named.items():
            for n in names:
                c = info.get((m, n))
                if c is None:
                    say(f"- {n} ({m}): not on today's roster")
                    continue
                lb = level_of_str(c, p1["level_prior"])
                la = level_of_str(c, params["level_prior"])
                rb = [x for x, _ in res["P1"][0][m]].index(n) + 1
                ra = [x for x, _ in res[best][0][m]].index(n) + 1
                say(f"- **{n}** ({m}): #{rb} -> #{ra}; K=5 {dict(res['P1'][0][m])[n]:.0%} -> "
                    f"{dict(res[best][0][m])[n]:.0%}, K=6 {dict(res['P1'][1][m])[n]:.0%} -> "
                    f"{dict(res[best][1][m])[n]:.0%}. Level {lb} -> {la}")

    text = "\n".join(L) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


def level_of_str(c, lp) -> str:
    lvl, prior, k0, kind, used = M.level_of(c, lp)
    seasons = ", ".join(f"{s} {g}g {f:.1f}" for s, g, f in used) or "none"
    return f"{lvl:.1f} (prior {prior:.1f}, {kind}, k0 {k0:g}, {c.games} games this season; seasons: {seasons})"


if __name__ == "__main__":
    sys.exit(main())
