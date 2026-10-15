"""
Work through lore: approve, edit, reject, skip -- or sit down with one
manager at a time.

    python scripts/review_lore.py                    # every proposed entry
    python scripts/review_lore.py --sitting Garrett  # one manager, start to end
    python scripts/review_lore.py --revisit          # look again at rejections
    python scripts/review_lore.py --add              # write an entry yourself

Saves after every decision, so quitting part-way loses nothing. Every
decision is logged on its entry; [u]ndo reverts the previous one, and
nothing is ever deleted. Editing a derived entry edits its TEMPLATE: keep
the {placeholders} and the numbers stay live.

A sitting shows the manager's career line and what the data says about him,
walks every proposal about him (newsletter mythology, data facts,
nicknames), then asks what else the four of you know. That last part is the
source: lore comes from Nick, in his own words.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import lore as L  # noqa: E402
from modules import lore_usage

KEYS = "[a]pprove  [e]dit  [r]eject  [s]kip  [u]ndo previous  [q]uit"


def _show(e: dict, i: int, n: int, out) -> None:
    ev = e.get("evidence", {})
    out(f"\n--- {i}/{n}  {e['id']}  ({e['kind']}"
        f"{', ' + e['strength'] if e.get('strength') else ''}"
        f"{', currently ' + e['status'] if e.get('status') != 'proposed' else ''})")
    out(f"    {e.get('text', '')}")
    if e.get("kind") == "derived" and e.get("template"):
        out(f"    template: {e['template']}")
    for k in ("asserted_in", "note", "p", "q", "cells_scanned",
              "uses_in_past_newsletters"):
        if k in ev:
            vals = ev[k] if isinstance(ev[k], list) else [ev[k]]
            for v in vals:
                out(f"    {k}: {v}")


def _values_of(e: dict) -> dict:
    return e.get("render_values") or {}


def review(lore: dict, save, ask=input, out=print, kind=None,
           entries=None) -> dict:
    todo = entries if entries is not None else [
        e for e in lore.get("entries", [])
        if e.get("status") == "proposed" and
        (kind is None or e.get("kind") == kind)]
    tally = {"approved": 0, "rejected": 0, "edited": 0, "skipped": 0,
             "undone": 0}
    i = 0
    last = None
    while i < len(todo):
        e = todo[i]
        _show(e, i + 1, len(todo), out)
        a = (ask(f"    {KEYS}: ") or "").strip().lower()[:1]
        if a == "q":
            return tally
        if a == "u":
            if last is not None and L.undo(todo[last]):
                tally["undone"] += 1
                save(lore)
                out(f"    undid {todo[last]['id']} -> "
                    f"{todo[last]['status']}")
                i = last
                last = None
            else:
                out("    nothing to undo")
            continue
        if a == "s":
            tally["skipped"] += 1
        elif a == "r":
            L.decide(e, "rejected")
            tally["rejected"] += 1
        elif a in ("a", "e"):
            if a == "e" and not _edit(e, ask, out):
                continue
            if a == "e":
                tally["edited"] += 1
            L.decide(e, "approved")
            tally["approved"] += 1
        else:
            continue
        save(lore)
        last = i
        i += 1
    return tally


def _edit(e: dict, ask, out) -> bool:
    field = "template" if e.get("kind") == "derived" else (
        "alias" if e.get("kind") == "alias" else "text")
    new = ask(f"    new {field}: ").strip()
    if not new:
        return False
    if field == "template":
        try:
            L.render(new, _values_of(e))
        except (KeyError, IndexError, ValueError) as err:
            out(f"    template doesn't render ({err}); keep the "
                "{placeholders}")
            return False
        e["text"] = L.render(new, _values_of(e))
    if field == "alias":
        e["text"] = f"{new} = {e['name']}"
    if field == "text" and re.search(r"\d", new):
        out("    note: numbers in written lore are not sayable -- the "
            "claim check takes numbers from the stats report only")
    e[field] = new
    return True


def add(lore: dict, save, ask=input, out=print, about: str = "",
        source: str = "Nick") -> dict:
    text = ask("    Lore, in your words (blank to finish): ").strip()
    if not text:
        return {}
    who = about or ask("    About whom (comma-separated): ").strip()
    base = re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-")
    have = {e["id"] for e in lore.get("entries", [])}
    eid, k = f"written-{base}", 2
    while eid in have:
        eid, k = f"written-{base}-{k}", k + 1
    e = {"id": eid, "kind": "written", "strength": "written",
         "status": "proposed", "text": text,
         "entities": [w.strip() for w in who.split(",") if w.strip()],
         "evidence": {"source": source}}
    L.decide(e, "approved")
    lore.setdefault("entries", []).append(e)
    save(lore)
    out(f"    added {eid}  (tag: <!--lore:{eid}-->)")
    return e


def about(e: dict, manager: str) -> bool:
    m = manager.lower()
    return any(str(x).lower() == m for x in e.get("entities", [])) or \
        str((e.get("definition") or {}).get("manager", "")).lower() == m


def dossier(lore: dict, manager: str, base: Path) -> list[str]:
    """What the data already says: career line, and every data fact about
    him -- approved or not -- so the sitting starts from something."""
    lines = [f"=== Sitting: {manager} ==="]
    try:
        import pandas as pd
        lh = pd.read_excel(base / "data" / "LEAGUEHISTORY.xlsx")
        row = lh[lh["manager_name"] == manager]
        if not row.empty:
            r = row.iloc[0]
            lines.append(
                f"  {int(r['seasons_completed'])} seasons | regular season "
                f"{r['regular_season_record']} | playoffs "
                f"{r['playoff_record']} | {int(r['titles_won'])} regular-"
                f"season titles, {int(r['playoff_championships'])} playoff "
                "championships")
    except Exception as err:  # noqa: BLE001
        lines.append(f"  (career line unavailable: {err})")
    facts = [e for e in lore.get("entries", [])
             if e.get("kind") == "derived" and about(e, manager)]
    if facts:
        lines.append("  What the data says (facts, not character):")
        lines += [f"   - {e['text']}  [{e['status']}]" for e in facts]
    return lines


def sitting(lore, manager, base, save, ask=input, out=print) -> dict:
    for line in dossier(lore, manager, base):
        out(line)
    entries = [e for e in lore.get("entries", [])
               if e.get("status") == "proposed" and about(e, manager)]
    t = review(lore, save, ask, out, entries=entries)
    out(f"\n    Anything else about {manager} the four of you know?")
    t["added"] = 0
    while add(lore, save, ask, out, about=manager):
        t["added"] += 1
    return t


def export(lore: dict, base: Path, week: int = None,
           season: str = None) -> Path:
    """Approved, non-stale entries only, stripped to what the writer needs.
    Proposals, rejections, evidence and decision logs stay out: what the
    drafting chat is shown, it treats as sayable.

    Each entry also carries how recently it was published, so the drafting
    chat can tell a line it has never used from one it ran last week. Without
    this every entry looked equally fresh in all 23 issues and the same
    characterisation of a manager could repeat all season (Nick, 10-14).
    `valence` rides along so the writer can keep praise and criticism in
    proportion rather than reaching for the same flattering or damning line.
    """
    keep = ("id", "kind", "strength", "text", "entities", "alias", "name",
            "valence")
    entries = [{k: e[k] for k in keep if k in e}
               for e in L.approved(lore)]

    note = ("Entries carry last_used_week when they have been published "
            "before. Prefer an entry that has never run, or one that ran "
            "long ago, over one from recent weeks.")
    if season:
        last = lore_usage.last_used(base, season,
                                    before_week=week if week else None)
        for e in entries:
            w = last.get(e.get("id"))
            if w is not None:
                e["last_used_week"] = w
                if week:
                    e["weeks_since_used"] = int(week) - w
    out = base / "output" / "lore_for_drafting.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"_usage_note": note, "entries": entries},
                              indent=1, ensure_ascii=True) + "\n",
                   encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--kind", choices=["derived", "written", "alias"])
    ap.add_argument("--sitting", metavar="MANAGER")
    ap.add_argument("--revisit", action="store_true")
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--export", action="store_true",
                    help="write output/lore_for_drafting.json: approved, "
                         "current entries only, for the drafting chat")
    ap.add_argument("--week", type=int,
                    help="the week being drafted; adds weeks_since_used to "
                         "the export so the writer can avoid recent lines")
    ap.add_argument("--base", default=str(ROOT))
    args = ap.parse_args(argv)
    base = Path(args.base)
    lore = L.load(base)
    save = lambda d: L.save(base, d)  # noqa: E731
    if args.add:
        while add(lore, save):
            pass
        return 0
    if args.export:
        out = export(lore, base, week=args.week,
                     season=(json.loads((base / "config" / "league_config.json")
                                        .read_text(encoding="utf-8"))
                             .get("season") or {}).get("current"))
        print(f"wrote {out} ({len(json.loads(out.read_text(encoding='utf-8'))['entries'])} "
              "approved entries)")
        return 0
    if args.sitting:
        t = sitting(lore, args.sitting, base, save)
    elif args.revisit:
        t = review(lore, save, entries=[
            e for e in lore.get("entries", [])
            if e.get("status") == "rejected"])
    else:
        t = review(lore, save, kind=args.kind)
    left = sum(1 for e in lore.get("entries", [])
               if e.get("status") == "proposed")
    print(f"\n{t}. {left} still proposed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
