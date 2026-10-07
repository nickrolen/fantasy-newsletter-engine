"""
Replay the angle selector over a whole past season, week by week, with the
recency tiebreak carried forward as it would have been live.

    python scripts/angles_report.py --season 2025-26

Weeks with an archived stats report also get its storylines (records,
upsets, milestones); earlier weeks use the results alone. History is prior
seasons only. Writes output/angles_<season>.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import angles as A  # noqa: E402
from modules.data_loader import MANAGERS, regular_season_weeks_for  # noqa: E402
from modules.storylines import compute_storylines  # noqa: E402


def replay(base: Path, season: str):
    allm = json.loads((base / "data" / "historical" / "all_matchups.json")
                      .read_text(encoding="utf-8"))
    sm = [m for m in allm if m["season"] == season]
    hist = A.History.build([m for m in allm if m["season"] < season],
                           regular_season_weeks_for)
    cup_last, reg_last = A.season_windows(season)
    od = base / "archive" / season / "output"
    import format_stats_report as fmt
    last, rows, prev_lead = {}, [], None
    for w in sorted({m["week"] for m in sm}):
        stories = None
        f = od / f"stats_report_week{w}.json"
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            stories = compute_storylines(
                d, fmt.load_last_week_betting_predictions(w, od), season,
                list(MANAGERS))
        sel = A.run_week([m for m in sm if m["week"] <= w], w, hist,
                         cup_last, reg_last, stories, last, season,
                         prev_lead)
        A.update_last_used(last, sel, w)
        prev_lead = None if sel["dead"] else sel["lead"]
        rows.append((w, bool(stories), sel))
    return rows, hist, cup_last, reg_last


def render(season, rows, hist, cup_last, reg_last) -> str:
    def cell(a):
        p = a["parts"]
        why = " + ".join(f"{k} {p[k]:.2f}" for k in ("cup", "standings",
                                                     "bracket") if p[k])
        return (f"{a['text']} -- **{a['score']:.2f}** = u {a['unusualness']:.2f}"
                f" x c {max(a['consequence'], A.CONSEQUENCE_FLOOR):.2f}"
                f"{' (' + why + ')' if why else ''}")
    out = [f"# Angle selector replay -- {season}", "",
           f"History: prior seasons only ({len(hist.margins)} games). Weekly "
           f"score spread {hist.sigma:.0f}. Cup window weeks 1-{cup_last} "
           f"(counterfactual: {season} had no Cup); regular season 1-"
           f"{reg_last}. `*` = archived stats report available (adds its "
           "storylines).", ""]
    fam = Counter(sel["lead"]["family"] for _, _, sel in rows
                  if not sel["dead"])
    out.append("Lead families: " + ", ".join(f"{k} {v}" for k, v in
                                             fam.most_common()))
    out.append(f"No-lead weeks: {[w for w, _, s in rows if s['dead']]}. "
               f"Repeats of last week's lead re-scored as conditional: "
               f"{sum(s['repeats_discounted'] for *_, s in rows)}.")
    out.append(f"Weeks where the recency tiebreak changed the order: "
               f"{sum(1 for *_, s in rows if s['recency_reordered'])} of "
               f"{len(rows)}.")
    out.append("")
    for w, st, sel in rows:
        if sel["dead"]:
            out.append(f"**Week {w}{'*' if st else ''}** -- NO LEAD "
                       f"({sel['dead']}). Best of it: {cell(sel['lead'])}")
        else:
            out.append(f"**Week {w}{'*' if st else ''}** -- lead: "
                       f"{cell(sel['lead'])}")
        for a in sel["secondary"][:2]:
            out.append(f"  - {cell(a)}")
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--season", required=True)
    ap.add_argument("--base", default=str(ROOT))
    args = ap.parse_args(argv)
    base = Path(args.base)
    rows, hist, cl, rl = replay(base, args.season)
    text = render(args.season, rows, hist, cl, rl)
    out = base / "output" / f"angles_{args.season}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
