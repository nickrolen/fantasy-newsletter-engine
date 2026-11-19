#!/usr/bin/env python3
"""
advice_show.py -- the latest advice, on Nick's desk (advice v2, V2 s.5).

    python scripts\\state.py pull
    python scripts\\advice_show.py              the latest run's advice, every manager
    python scripts\\advice_show.py --runs 5     also the last 5 runs' plans, one line each

H53: each manager's advice is a plan (up to his adds left, each move priced
after the one before it): numbered steps, each with its own gain, then the
plan's total, then the backup (for step 1). A file from before 53 has no
plan: its one move is shown as before.

H54: a manager with a returner gets the three IL options, each against
doing nothing (C): A activate now (the activation and the plan's steps), B
keep him in IL this window and activate at the next, C the baseline -- then
which won, by how much, and B against A. When B wins, A's steps are printed
as the plan B beat. A file from before 54 prints as before.

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
        if e.get("activation"):
            a = e["activation"]
            if (e.get("il_choice") or {}).get("choice") == "hold":     # H54: the plan keeps him in IL
                out(f"  Step: {e['hold']['text']}")
                out(f"    {e['hold']['texts']['numbers']}")
            else:
                out(f"  Step: {a['text']}")
            if a.get("texts") and (e.get("il_choice") or {}).get("choice") != "hold":            # 4c3: priced against doing nothing (held in IL, no move)
                out(f"    {a['texts']['numbers']}")
                out(f"    {a['texts']['reason']}")
                out(f"    engine: step 0 against holding {', '.join(a['back'])} in IL with no move; "
                    f"dwp {a['dwp']}; dpts {a['dpts']}; title term later {a['dT_later']:+.4f} (stake units)"
                    + ("  [NEGATIVE: holding him through the horizon beats activating him now]"
                       if sum(a["dwp"]) < 0 or (abs(sum(a["dwp"])) < 1e-12 and sum(a["dpts"]) < 0) else ""))
        if e.get("il_choice"):
            il_lines(latest, e, out)
        if e["move"] is None:
            out(f"  {e.get('empty') or 'No move beats standing pat'}")
            if e.get("activate_plan"):            # H54: the plan the hold beat
                out("  Option A's steps (not advised: the hold blocks them):")
                for mv in e["activate_plan"]:
                    _move_lines(latest, mv, f"A step {mv.get('step', 1)}", out)
                if e.get("activate_total"):
                    out(f"  A's {e['activate_total']['text']}")
            continue
        plan = e.get("plan") or [e["move"]]       # before H53: the one move
        n = len(plan)
        for mv in plan:
            label = "Move" if n == 1 else f"Step {mv.get('step', 1)}"
            _move_lines(latest, mv, label, out)
            also = mv.get("also_wanted_by", e["also_wanted_by"] if mv is e["move"] else [])
            if also:
                out(f"    Also wanted by {', '.join(also)}")
        if n > 1 or (n == 1 and (e.get("plan_total") or {}).get("includes_activation")):
            t = e["plan_total"]
            out(f"  {t['text']}")
            act = e.get("activation") if (t.get("includes_activation") and e.get("activation")) else None
            rows = ([act] if act else []) + list(plan)
            out(f"    engine: the plan priced as one, dwp {t['dwp']}; dpts {t['dpts']}; starts {t['dstarts']}; "
                f"{'activation + steps' if act else 'steps'} summed dwp "
                f"{[round(sum(d['dwp'][k] for d in rows), 6) for k in (0, 1)]}")
        if e.get("plan_stop"):
            out(f"  Plan {e['plan_stop']['text']} ({e['adds_left']} add(s) left)")
        if e["backup"] is None:
            out("  Backup: none (no other qualifying first move whose add is in nobody's plan)"
                if e.get("plan") else "  Backup: none (no other qualifying move whose add is nobody else's top)")
        else:
            _move_lines(latest, e["backup"], "Backup (instead of step 1)" if n > 1 else "Backup", out)


def _pp(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def il_lines(latest: dict, e: dict, out) -> None:
    """H54: the three IL options, their numbers (each against C), the choice."""
    from modules import advice_live as al
    hz = latest["horizon"]
    show = latest.get("show_title_odds") is not False
    opps = e["opponents"]
    a, h, c = e["activation"], e.get("hold") or {}, e["il_choice"]
    held = c["choice"] == "hold"
    tot = e.get("activate_total") if held else e.get("plan_total")
    a_opt = tot if c["against"] == "plan_total" else a
    nsteps = len(e.get("activate_plan") if held else e.get("plan") or [])
    who = ", ".join(a["back"])
    out(f"  IL options at week {a['week']}'s window ({who}), each against C (doing nothing):")
    out(f"    A. Activate now{' + ' + str(nsteps) + ' step(s)' if nsteps else ''}: "
        f"{al.numbers_text(a_opt, hz, opps, show_title=show)}; score {c['activate_score']:+.4f}")
    if not c["offered"]:
        out(f"    B. Keep in IL one week: not offered ({c['why_not']})")
    else:
        drops = (f", dropping {', '.join(h['next_drops'])} then" if h["next_drops"]
                 else ", with room then")
        out(f"    B. Keep in IL for week {h['week']}, activate at week {h['next_week']}'s window "
            f"({al._md(al.date.fromisoformat(h['next_day']))}{drops}): {h['texts']['own_numbers']}; "
            f"score {c['hold_score']:+.4f}")
    wb = a.get("wp_base") or [None, None]
    out(f"    C. Keep in IL through the horizon, no move: win chance {_pp(wb[0])}, {_pp(wb[1])} (score 0)")
    if c["offered"]:
        m = c["margin"]
        if held:
            out(f"    Chosen: B, keep him in IL -- B beats A by {m:+.4f} (the bar is {c['bar']:+.4f})")
        else:
            out(f"    Chosen: A, activate now -- B {'trails A by ' + format(-m, '.4f') if m <= 0 else 'beats A by only ' + format(m, '+.4f')}"
                f" (B needs more than {c['bar']:+.4f} over A)")
        out(f"    B against A: {h['texts']['numbers']}")
        out(f"      {h['texts']['reason']}")
    else:
        out("    Chosen: A, activate now (B not offered)")


def _move_lines(latest: dict, mv: dict, label: str, out) -> None:
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


def show_runs(rows: list, n: int, out=print) -> None:
    out("")
    out(f"The last {min(n, len(rows))} runs:")
    for r in rows[-n:]:
        if r.get("error"):
            out(f"  {r['as_of']} {r['mode']}: FAILED ({r['error']})")
            continue
        bits = []
        for m, e in (r.get("managers") or {}).items():
            plan = e.get("plan") or ([e["top"]] if e.get("top") else [])    # before H53: the top move
            if not plan:
                bits.append(f"{m}: pat")
                continue
            bits.append(f"{m}: " + " ".join(f"{k}) {_short(t)}" for k, t in enumerate(plan, 1)))
        pub = " [published]" if r.get("published") else ""
        out(f"  {r['as_of']} {r['mode']}{pub}: " + "; ".join(bits))


def _short(t: dict) -> str:
    """'+LeBron James -Anthony Black' (IL+ for an IL placement)."""
    return (f"+{t['add']}" + (f" -{t['drop']}" if t.get("drop") else "")
            + (f" IL+{t['to_il']}" if t.get("to_il") else ""))


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
