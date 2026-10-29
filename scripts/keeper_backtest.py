"""Backtest keepability against every keeper decision (keepability v3, step A).

    py scripts/keeper_backtest.py [--no-v22] [--out FILE.md]

For each decision (2021-22 .. 2026-27) and each as-of point (week2, mid,
end; modules/keeper_history), each method ranks each manager's roster on that
day; his top K (his real keeper count, 6 in every decision so far) is scored
against who he actually kept. Hits out of 24, beside the CEILING -- the keepers
who were on their manager's roster at that point at all.

Methods (ties by name, always):
  v2.2      modules/keepability_v2.compute_keepability_v2 itself, fed the
            season-so-far as it stood. Yahoo's projected FPPG (20% of the
            score) has no history, so it is SUBSTITUTED -- see v22_inputs();
            the 2026-27 decision at season's end also runs with the archived
            2025-26 PLAYERLIST (v2.2 archived), the most faithful case.
  v2.2 noproj the same with the projection's 20% removed and the other four
            weights rescaled to sum to 1 -- how much the substitute matters.
  A         reputation, then season: this season's keepers first (by FPPG so
            far), then the rest by FPPG so far.
  B         reputation only: this season's keepers first (by name), then draft
            round, earliest first; undrafted last. No season data.
  C         season only: FPPG so far.
A player with no appearances yet ranks below every player with one.

Read-only on the playerlog, drafts, trades, PLAYER_AGES-equivalent bbref cache
and archive/2025-26. Fits nothing; changes no consumer.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import keeper_history as kh                    # noqa: E402
from modules import keepability_v2 as v2                    # noqa: E402
from modules.data_loader import PlayerIndex                 # noqa: E402

METHODS = ("v2.2", "v2.2 noproj", "A", "B", "C")
ARCHIVE_PLAYERLIST = "archive/2025-26/data/PLAYERLIST.xlsx"
V2_DEFAULT_AGE = 27            # what v2.2 itself falls back to (build_keepability_report)
V2_NEUTRAL_CV = 33.0           # likewise, under 10 started games


# ---------------------------------------------------------------------------
# the three rules
# ---------------------------------------------------------------------------

def _fppg_key(c):
    return (c.fppg is None, -(c.fppg or 0.0), c.player)


def rule_a(cands):
    return sorted(cands, key=lambda c: (not c.kept,) + _fppg_key(c))


def rule_b(cands):
    def key(c):
        if c.kept:
            return (0, 0, c.player)
        if c.draft_round is not None:
            return (1, c.draft_round, c.player)
        return (2, 0, c.player)
    return sorted(cands, key=key)


def rule_c(cands):
    return sorted(cands, key=_fppg_key)


# ---------------------------------------------------------------------------
# v2.2, reproduced at a past moment
# ---------------------------------------------------------------------------

class V22History:
    """Per-player season lines the way keepability_v2.extract_player_season_stats
    builds them: a game is fp != 0 and not is_injured (any slot), expected
    games = weeks rostered x 3.3, availability capped at 1. Every season before
    the decision season is whole; the decision season is cut at as-of."""

    def __init__(self, inputs: kh.Inputs):
        self.inputs = inputs
        self.whole: dict = {}             # season -> {player: SeasonStats}
        for s, rows in inputs.log.items():
            self.whole[s] = self._lines(rows, s)

    @staticmethod
    def _lines(rows, season) -> dict:
        fps, weeks = {}, {}
        for r in rows:
            weeks.setdefault(r["player_name"], set()).add(r["week"])
            if r["fantasy_points"] != 0 and not r["is_injured"]:
                fps.setdefault(r["player_name"], []).append(r["fantasy_points"])
        out = {}
        for n, wk in weeks.items():
            f = fps.get(n, [])
            exp = len(wk) * 3.3
            out[n] = v2.SeasonStats(season=season, games_played=len(f), total_fp=sum(f),
                                    fppg=sum(f) / len(f) if f else 0.0, expected_games=int(exp),
                                    availability_pct=min(1.0, len(f) / exp if exp else 0.0))
        return out

    def seasons_for(self, player, season, cut: dict) -> list:
        """Newest first. Earlier seasons only where he had a game (v2.2's
        historical rule); the current season whenever he is rostered."""
        out = [cut[player]] if player in cut else []
        for s in sorted(self.whole):
            if s < season and player in self.whole[s] and self.whole[s][player].games_played:
                out.append(self.whole[s][player])
        return sorted(out, key=lambda x: x.season, reverse=True)


def consistency_cv(rows_cut, player) -> float:
    fps = [r["fantasy_points"] for r in rows_cut
           if r["player_name"] == player and r["started"] and r["fantasy_points"] != 0]
    if len(fps) < 10 or statistics.mean(fps) == 0:
        return V2_NEUTRAL_CV
    return statistics.pstdev(fps) / statistics.mean(fps) * 100


def v22_inputs(c, season_line, prev_line, archive=None) -> tuple:
    """(proj_fppg, age, how) for one candidate.

    Substitute (no Yahoo history): the season so far, v2.2's own game rule,
    if he has 10+ games; else last season's FPPG if 10+ games; else 0.0 --
    which is exactly what v2.2 feeds a player PLAYERLIST does not match.
    Age: basketball-reference for that season; missing -> 27, v2.2's default.
    archive: the 2025-26 end-of-season PLAYERLIST -- projectedFPPG and age
    straight from it, v2.2's defaults when he is not in it."""
    if archive is not None:
        row = archive.get(c.player)
        if row is None:
            return 0.0, V2_DEFAULT_AGE, "not in archived PLAYERLIST: proj 0, age 27"
        return float(row["proj"] or 0.0), int(row["age"] or V2_DEFAULT_AGE), "archived PLAYERLIST"
    age = c.age if c.age is not None else V2_DEFAULT_AGE
    if season_line is not None and season_line.games_played >= v2.MIN_GAMES_FOR_SEASON:
        return season_line.fppg, age, "season so far"
    if prev_line is not None and prev_line.games_played >= v2.MIN_GAMES_FOR_SEASON:
        return prev_line.fppg, age, "last season"
    return 0.0, age, "none: 0.0"


def load_archive(root=ROOT) -> PlayerIndex:
    import pandas as pd
    df = pd.read_excel(Path(root) / ARCHIVE_PLAYERLIST)
    return PlayerIndex({r["player_name"]: {"proj": r.get("projectedFPPG"), "age": r.get("age")}
                        for _, r in df.iterrows()})


def v22_rank(snap, hist: V22History, archive=None) -> tuple:
    """({manager: ranked names} for v2.2, the same for noproj, substitution counts)."""
    season = kh.prev_season(snap.decision)
    rows_cut = [r for r in hist.inputs.log[season] if r["date"] <= snap.as_of]
    cut = V22History._lines(rows_cut, season)
    prev = hist.whole.get(kh.prev_season(season), {})
    ranked, ranked_np, how = {}, {}, {}
    for m, cands in snap.by_manager().items():
        scored = []
        for c in cands:
            proj, age, why = v22_inputs(c, cut.get(c.player), prev.get(c.player), archive)
            how[why] = how.get(why, 0) + 1
            if c.age is None and archive is None:
                how["age missing: 27"] = how.get("age missing: 27", 0) + 1
            score, comp = v2.compute_keepability_v2(
                c.player, hist.seasons_for(c.player, season, cut), age, "",
                consistency_cv(rows_cut, c.player), {}, proj_fppg=proj)
            noproj = (comp.core_score - v2.COMPONENT_WEIGHTS["proj_fppg"] * comp.proj_fppg_normalized) \
                / (1 - v2.COMPONENT_WEIGHTS["proj_fppg"]) * comp.age_factor
            scored.append((c.player, score, noproj))
        ranked[m] = [p for p, s, _ in sorted(scored, key=lambda x: (-x[1], x[0]))]
        ranked_np[m] = [p for p, _, s in sorted(scored, key=lambda x: (-x[2], x[0]))]
    return ranked, ranked_np, how


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def hits(snap, ranked: dict) -> int:
    return sum(len(set(ranked.get(m, [])[:len(ks)]) & set(ks)) for m, ks in snap.keepers.items())


def picks(snap, ranked: dict) -> dict:
    return {m: ranked.get(m, [])[:len(ks)] for m, ks in snap.keepers.items()}


def rank_all(snap, hist=None, archive=None) -> tuple:
    bym = snap.by_manager()
    out = {"A": {m: [c.player for c in rule_a(v)] for m, v in bym.items()},
           "B": {m: [c.player for c in rule_b(v)] for m, v in bym.items()},
           "C": {m: [c.player for c in rule_c(v)] for m, v in bym.items()}}
    how = {}
    if hist is not None:
        out["v2.2"], out["v2.2 noproj"], how = v22_rank(snap, hist)
        if archive is not None:
            out["v2.2 archived"], _, how_a = v22_rank(snap, hist, archive)
            how = {**how, **{"archived: " + k: v for k, v in how_a.items()}}
    return out, how


def run(root=ROOT, with_v22=True):
    inputs = kh.Inputs.load(root)
    ages = kh.load_ages(kh.age_seasons(), root)
    snaps = kh.build(inputs, ages=ages)
    hist = V22History(inputs) if with_v22 else None
    archive = load_archive(root) if with_v22 else None
    table, subs, chosen = {}, {}, {}
    for (d, p), snap in snaps.items():
        arch = archive if (d == "2026-27" and p == "end") else None
        ranked, how = rank_all(snap, hist, arch)
        for meth, r in ranked.items():
            table[(meth, d, p)] = hits(snap, r)
            chosen[(meth, d, p)] = picks(snap, r)
        subs[(d, p)] = how
    return inputs, snaps, table, subs, chosen


def misses(snaps, chosen, methods, point="end") -> tuple:
    """(keepers every method missed, non-keepers every method kept) at `point`."""
    missed, wrong = [], []
    for (d, p), snap in sorted(snaps.items()):
        if p != point:
            continue
        for m, ks in snap.keepers.items():
            picked = [set(chosen[(meth, d, p)][m]) for meth in methods if (meth, d, p) in chosen]
            for k in ks:
                if all(k not in s for s in picked):
                    missed.append((d, m, k))
            for n in set.intersection(*picked) - set(ks):
                wrong.append((d, m, n))
    return missed, wrong


def report(inputs, snaps, table, subs, chosen) -> str:
    L = []
    L.append("## Dataset\n")
    L.append("| decision | from | as-of (week2 / mid / end) | candidates (B/G/H/N) | keepers found | "
             "partial season | joined after day 1 | not rostered the season before | acquired (draft/trade/pickup) "
             "| NBA-team rows flip | ages from a neighbouring season |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in kh.summary(inputs, snaps):
        c = s["candidates"]
        a = s["acquired"]
        wk = s["weeks"]
        days = " / ".join(snaps[(s["decision"], p)].as_of for p in kh.POINTS)
        L.append(f"| {s['decision']} | {s['from_season']} | wk {wk['week2']}, {wk['mid']}, {wk['end']}: {days} | "
                 f"{c.get('Benton')}/{c.get('Garrett')}/{c.get('Hayden')}/{c.get('Nick')} | "
                 f"{s['keepers_found']}/{s['keepers']} | {s['partial_season']} | {s['joined_after_day_1']} | "
                 f"{s['prev_season_not_rostered']} | {a['draft']}/{a['trade']}/{a['pickup']} | "
                 f"{len(s['team_label_flipping'])} | {', '.join(s['age_from_neighbour']) or '-'} |")
    L.append("\n## Backtest: hits / 24\n")
    cols = [(d, p) for d in kh.DECISIONS for p in kh.POINTS]
    L.append("| method | " + " | ".join(f"{d[2:]} {p}" for d, p in cols) + " | total |")
    L.append("|---|" + "---|" * (len(cols) + 1))
    L.append("| *ceiling* | " + " | ".join(str(snaps[c].ceiling) for c in cols)
             + f" | {sum(snaps[c].ceiling for c in cols)} |")
    for meth in METHODS + ("v2.2 archived",):
        cells = [table.get((meth,) + c) for c in cols]
        if all(x is None for x in cells):
            continue
        tot = sum(x for x in cells if x is not None)
        L.append(f"| {meth} | " + " | ".join("" if x is None else str(x) for x in cells)
                 + f" | {tot if meth != 'v2.2 archived' else ''} |")
    L.append("\nTotals by point:\n")
    for meth in METHODS:
        if (meth, kh.DECISIONS[0], "end") not in table:
            continue
        L.append(f"- {meth}: " + ", ".join(
            f"{p} {sum(table[(meth, d, p)] for d in kh.DECISIONS)}/{sum(snaps[(d, p)].ceiling for d in kh.DECISIONS)}"
            for p in kh.POINTS))
    L.append("\nWithout 2021-22 (the outlier decision):\n")
    later = kh.DECISIONS[1:]
    for meth in METHODS:
        if (meth, later[0], "end") not in table:
            continue
        L.append(f"- {meth}: " + ", ".join(
            f"{p} {sum(table[(meth, d, p)] for d in later)}/{sum(snaps[(d, p)].ceiling for d in later)}"
            for p in kh.POINTS) + f"; all {sum(table[(meth, d, p)] for d in later for p in kh.POINTS)}")
    if any(subs.values()):
        L.append("\n## v2.2 inputs substituted (candidates per decision x point)\n")
        for (d, p), how in sorted(subs.items()):
            L.append(f"- {d} {p}: " + "; ".join(f"{k} {v}" for k, v in sorted(how.items())))
    meths = [m for m in ("v2.2", "A", "B", "C") if (m, kh.DECISIONS[0], "end") in table]
    missed, wrong = misses(snaps, chosen, meths)
    L.append(f"\n## At season's end: keepers every method ({', '.join(meths)}) missed\n")
    L.extend(f"- {d} {m}: {k}" for d, m, k in missed)
    L.append("\n## At season's end: non-keepers every method kept\n")
    L.extend(f"- {d} {m}: {k}" for d, m, k in wrong)
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-v22", action="store_true", help="skip the v2.2 reproduction")
    ap.add_argument("--out", help="also write the report to this .md file")
    ap.add_argument("--json", help="also write the hits table to this .json file "
                    "(read by scripts/fit_keepability_v3.py --baseline)")
    a = ap.parse_args(argv)
    res = run(with_v22=not a.no_v22)
    text = report(*res)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    if a.json:
        _inputs, snaps, table, _subs, _chosen = res
        Path(a.json).write_text(json.dumps({
            "hits": {f"{m}|{d}|{p}": h for (m, d, p), h in sorted(table.items())},
            "ceiling": {f"{d}|{p}": s.ceiling for (d, p), s in sorted(snaps.items())},
        }, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
