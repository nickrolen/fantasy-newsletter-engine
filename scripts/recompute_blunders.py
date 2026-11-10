"""
recompute_blunders.py -- recompute this season's stored blunder counts with
the one definition (modules/blunders; F2, 11-09).

    python scripts\\recompute_blunders.py            report only: writes nothing
    python scripts\\recompute_blunders.py --apply    set the stored counts

The stored counts are league state, written week by week by the old greedy,
which missed every blunder that needs a reshuffle:
  - LEAGUEHISTORY.xlsx total_blunders_current_season: the weeks in
    config/.leaguehistory_applied_weeks.json (Step 2's ledger);
  - RECORDS.json cumulative_blunders and single_week_blunders_high: weeks 1
    through RECORDS' last_history_week (the stats report's history phase).

--apply SETS each to the sum (and the single-week high) of the recomputed
weeks; it never adds, so running it twice changes nothing the second time.
It touches those three values only. Run it between `python scripts\\state.py
pull` and `push`, never during a cloud run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LEAGUEHISTORY = Path("data") / "LEAGUEHISTORY.xlsx"
LEDGER = Path("config") / ".leaguehistory_applied_weeks.json"
RECORDS = Path("config") / "RECORDS.json"
COLUMN = "total_blunders_current_season"


def weekly(base: Path, season: str, weeks) -> dict:
    """{week: {manager: Day list}} for the season's weeks, on the files
    update_leaguehistory and the stats report read (effective dates applied)."""
    import pandas as pd
    from modules import blunders as bl
    from modules.transaction_rulings import apply_effective_dates
    plog = apply_effective_dates(pd.read_excel(base / "data" / "PLAYERLOG.xlsx"), base, "playerlog")
    lu = apply_effective_dates(pd.read_excel(base / "data" / "LINEUPS.xlsx"), base, "lineups")
    out = {}
    for w in weeks:
        out[w] = bl.week_from_frames(lu[(lu["season_year"] == season) & (lu["week"] == w)],
                                     plog[(plog["season_year"] == season) & (plog["week"] == w)])
    return out


def plan(base: Path) -> dict:
    """What the stored values are and what they become. Reads only."""
    from openpyxl import load_workbook
    from modules.data_loader import CURRENT_SEASON_LONG, MANAGERS
    from modules.records_tracker import HISTORY_WATERMARK_KEY
    season = CURRENT_SEASON_LONG
    ledger = json.loads((base / LEDGER).read_text(encoding="utf-8")) if (base / LEDGER).is_file() else {}
    lh_weeks = sorted((ledger.get(season) or {}).get("applied_weeks") or [])
    records = json.loads((base / RECORDS).read_text(encoding="utf-8"))
    rec_last = int(records.get(HISTORY_WATERMARK_KEY) or 0)
    rec_weeks = list(range(1, rec_last + 1))
    per_week = weekly(base, season, sorted(set(lh_weeks) | set(rec_weeks)))

    def count(w, m):
        return sum(d.count for d in per_week[w].get(m, []))

    def points(w, m):
        return round(sum(d.points for d in per_week[w].get(m, [])), 2)

    wb = load_workbook(base / LEAGUEHISTORY, data_only=False)
    ws = wb.active
    header = [c.value for c in ws[1]]
    if COLUMN not in header or "manager_name" not in header:
        raise SystemExit(f"{LEAGUEHISTORY} lacks {COLUMN} or manager_name")
    ci, mi = header.index(COLUMN) + 1, header.index("manager_name") + 1
    lh_old = {str(ws.cell(row=r, column=mi).value).strip(): ws.cell(row=r, column=ci).value
              for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=mi).value}
    lh_new = {m: sum(count(w, m) for w in lh_weeks) for m in MANAGERS}

    rec_old_cum = dict(records.get("cumulative_blunders") or {})
    rec_old_high = dict(records.get("single_week_blunders_high") or {})
    rec_new_cum = {m: sum(count(w, m) for w in rec_weeks) for m in MANAGERS}
    rec_new_high = {}
    for m in MANAGERS:
        best = {"count": 0, "week": 0}
        for w in rec_weeks:                              # the first week reaching the high, as before
            if count(w, m) > best["count"]:
                best = {"count": count(w, m), "week": w}
        rec_new_high[m] = best
    stale = sorted({(d.date, m, n) for w in per_week for m, days in per_week[w].items()
                    for d in days for n in d.stale_positions})
    return {"season": season, "lh_weeks": lh_weeks, "rec_weeks": rec_weeks,
            "per_week": {w: {m: {"count": count(w, m), "points": points(w, m),
                                 "players": [f"{b.date} {b.bench_player} {b.bench_player_fp:.2f}"
                                             + (f" (reshuffle: {b.reshuffle_text()})" if b.moves else "")
                                             for d in per_week[w].get(m, []) for b in d.blunders]}
                             for m in MANAGERS} for w in per_week},
            "leaguehistory": {"old": lh_old, "new": lh_new},
            "records": {"cumulative_old": rec_old_cum, "cumulative_new": rec_new_cum,
                        "high_old": rec_old_high, "high_new": rec_new_high},
            "stale_positions": stale}


def apply(base: Path, p: dict) -> list:
    """Set the three stored values. Returns what changed."""
    from openpyxl import load_workbook
    from modules.data_loader import save_records
    changed = []
    wb = load_workbook(base / LEAGUEHISTORY, data_only=False)
    ws = wb.active
    header = [c.value for c in ws[1]]
    ci, mi = header.index(COLUMN) + 1, header.index("manager_name") + 1
    dirty = False
    for r in range(2, ws.max_row + 1):
        m = ws.cell(row=r, column=mi).value
        if not m:
            continue
        m = str(m).strip()
        if m not in p["leaguehistory"]["new"]:
            raise SystemExit(f"{LEAGUEHISTORY} row {r}: unknown manager {m!r}")
        new = p["leaguehistory"]["new"][m]
        old = ws.cell(row=r, column=ci).value
        if old is None or float(old) != float(new):
            ws.cell(row=r, column=ci, value=new)
            changed.append(f"LEAGUEHISTORY {m}: {old} -> {new}")
            dirty = True
    if dirty:
        wb.save(base / LEAGUEHISTORY)
    records = json.loads((base / RECORDS).read_text(encoding="utf-8"))
    rc = p["records"]
    if (records.get("cumulative_blunders") != rc["cumulative_new"]
            or records.get("single_week_blunders_high") != rc["high_new"]):
        changed.append(f"RECORDS cumulative_blunders: {records.get('cumulative_blunders')} -> "
                       f"{rc['cumulative_new']}")
        changed.append(f"RECORDS single_week_blunders_high: {records.get('single_week_blunders_high')} "
                       f"-> {rc['high_new']}")
        records["cumulative_blunders"] = rc["cumulative_new"]
        records["single_week_blunders_high"] = rc["high_new"]
        save_records(records, base / RECORDS)
    return changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="set the stored counts (default: report only)")
    ap.add_argument("--base-path", default=".")
    ap.add_argument("--json", help="also write the report as JSON to this path")
    a = ap.parse_args(argv)
    base = Path(a.base_path)
    p = plan(base)
    print(f"Blunders, {p['season']} (modules/blunders: the exact fill)")
    for w, ms in sorted(p["per_week"].items()):
        for m, v in ms.items():
            if v["count"]:
                print(f"  week {w} {m}: {v['count']} ({v['points']:.2f} FP) -- " + "; ".join(v["players"]))
    print(f"LEAGUEHISTORY {COLUMN} (weeks {p['lh_weeks']}):")
    for m, new in p["leaguehistory"]["new"].items():
        print(f"  {m}: stored {p['leaguehistory']['old'].get(m)} -> {new}")
    print(f"RECORDS (weeks {p['rec_weeks']}):")
    for m, new in p["records"]["cumulative_new"].items():
        print(f"  {m}: cumulative stored {p['records']['cumulative_old'].get(m)} -> {new}; "
              f"single-week high stored {p['records']['high_old'].get(m)} -> {p['records']['high_new'][m]}")
    if p["stale_positions"]:
        print("Starters seated outside their listed positions (taken as eligible): "
              + "; ".join(" ".join(x) for x in p["stale_positions"]))
    if a.json:
        Path(a.json).write_text(json.dumps(p, indent=1, default=str), encoding="utf-8")
    if not a.apply:
        print("Report only: nothing written. --apply sets these values.")
        return 0
    changed = apply(base, p)
    print("\n".join(changed) if changed else "Nothing to change: the stored counts already match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
