#!/usr/bin/env python3
"""
advice_show.py -- the latest advice, on Nick's desk (advice v2, V2 s.5).

    python scripts\\state.py pull
    python scripts\\advice_show.py              the latest run's advice, every manager
    python scripts\\advice_show.py --runs 5     also the last 5 runs' top moves, one line each

Reads output/advice_latest.json and output/advice_history.jsonl (written by
every run that prices: modules/advice_live). Writes nothing. For the shadow
week (from Monday 11-16's window) while the hub's advice view is off
(league_config advice.hub). A failed advice step is printed as FAILED, with
its error: no pick is shown for that run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def show(latest: dict, out=print) -> None:
    out(f"Advice from run {latest['run_id']} ({latest['mode']}), as of {latest['as_of']}")
    out(latest["updated_text"])
    if latest.get("error"):
        out(f"FAILED: {latest['error']}")
        for line in latest.get("traceback") or []:
            out(f"    {line}")
        return
    if latest.get("season_over"):
        out(latest["season_over"])
        return
    hz = latest["horizon"]
    ins = latest.get("inputs") or {}
    out(f"{hz['label']}: weeks {', '.join(str(w) for w in hz['weeks'] if w is not None)}; adds count in "
        f"week {hz['budget_week']}'s budget; window closes {hz['closes']}")
    out(f"Tags fetched {ins.get('tags_taken_at')} (anchored {ins.get('anchor')}); stakes as of "
        f"{ins.get('stakes_as_of')}; {ins.get('pool')} free agents; claimed in the chat: "
        f"{', '.join(ins.get('reserved') or []) or 'none'}")
    secs = latest.get("seconds") or {}
    out(f"Timing: inputs {secs.get('inputs')} s, engine {secs.get('engine')} s, total {secs.get('total')} s"
        + ("  [published: Monday 12:01]" if latest.get("published") else ""))
    for m, e in latest["managers"].items():
        out("")
        out(f"{m} -- {e['adds_left']} add(s) left; opponents "
            + ", ".join(f"week {w}: {o or 'not set'}" for w, o in e["opponents"].items()))
        if e["move"] is None:
            out(f"  {e.get('empty') or 'No move beats standing pat'}")
            continue
        for label, key in (("Move", "move"), ("Backup", "backup")):
            mv = e[key]
            if mv is None:
                if key == "backup":
                    out("  Backup: none (no other qualifying move whose add is nobody else's top)")
                continue
            t = mv["text"]
            out(f"  {label}: {t['move']}")
            if t["followup"]:
                out(f"    {t['followup']}")
            out(f"    {t['numbers']}")
            if latest.get("show_title_odds") is False:
                out(f"    title odds: hidden (advice.show_title_odds is false; the estimate "
                    f"{mv['title_odds'] if mv['title_odds'] is None else format(100 * mv['title_odds'], '+.1f') + '%'} "
                    "is kept in the file)")
            elif "show_title_odds" not in latest:
                out("    title odds: as written before advice.show_title_odds existed")
            out(f"    {t['reason']}")
            out(f"    engine: score {mv['score']:+.4f}; dwp {mv['dwp']}; dpts {mv['dpts']}; "
                f"title term later {mv['dT_later']:+.4f} (stake units){'; ranked on points' if mv['flat'] else ''}")
        if e["also_wanted_by"]:
            out(f"  Also wanted by {', '.join(e['also_wanted_by'])}")


def show_runs(rows: list, n: int, out=print) -> None:
    out("")
    out(f"The last {min(n, len(rows))} runs:")
    for r in rows[-n:]:
        if r.get("error"):
            out(f"  {r['as_of']} {r['mode']}: FAILED ({r['error']})")
            continue
        bits = []
        for m, e in (r.get("managers") or {}).items():
            t = e.get("top")
            bits.append(f"{m} " + (f"+{t['add']}" + (f" -{t['drop']}" if t.get("drop") else "")
                                   + (f" IL+{t['to_il']}" if t.get("to_il") else "") if t else "pat"))
        pub = " [published]" if r.get("published") else ""
        out(f"  {r['as_of']} {r['mode']}{pub}: " + "; ".join(bits))


def main(argv=None) -> int:
    from modules import advice_live as al
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=0, help="also the last N runs' top moves")
    ap.add_argument("--base-path", default=str(ROOT))
    a = ap.parse_args(argv)
    try:
        latest = al.read_latest(a.base_path)
    except al.AdviceInputError as e:
        print(f"REFUSED: {e}")
        return 1
    show(latest)
    if a.runs:
        show_runs(al.read_history(a.base_path), a.runs)
    return 1 if latest.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
