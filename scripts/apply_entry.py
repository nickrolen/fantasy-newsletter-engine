#!/usr/bin/env python3
"""
apply_entry.py -- apply Nick's phone entries (GitHub issue titles) to the
league state, and write the comments the workflow posts (Step 3a;
claude/HANDOFF_STEP3A_PHONE_ENTRIES_2026-11-10.md s.2).

    python scripts/apply_entry.py apply --event $GITHUB_EVENT_PATH --open-issues open.json --out-dir DIR
    python scripts/apply_entry.py effect --out-dir DIR --runs-file output/nightly_runs.jsonl --skip N
    python scripts/apply_entry.py check "Injury: Tatum knee, back 12/09"      (desk: parse only)

The grammar is modules/phone_entries.py. The checks are the desk's, called,
never copied: injury entries through scripts/overrides.py (add / set-return /
set-notes / remove), moves and trades through modules/move_ledger.add (the
path `ledger.py add` takes: budget, roster legality, the reserved-player
rules, the trade deadline).

apply  reads the event (the issue that fired the workflow, its author, the
       sender, opened or edited) and the list of Nick's open issues, and
       applies, in issue order: the event's issue, then every other open
       issue of Nick's that has never been answered (no entry-refused label).
       That second part is the CATCH-UP: GitHub keeps at most one run waiting
       in a concurrency group and cancels the older one, so an entry whose
       run was cancelled is applied by the next entry's run.
       Per issue:
         - not Nick's (author or sender): "Only Nick's entries are applied", nothing else;
         - already applied (its number is in the override history or on a
           ledger entry): an edit gets "already applied as ...; open a new
           issue to change it", nothing else;
         - refused: the reason and the forms; state untouched; left open,
           labelled entry-refused (an edit re-parses it);
         - applied: the entry before and after (equal to the file's diff),
           the cause; closed.
       Writes DIR/actions.json, one DIR/<n>.md per comment, DIR/before.json
       (this week's win % and the title odds before anything was applied, for
       the effect), and under the workflow applied=true|false and cause=...
       to $GITHUB_OUTPUT. A refusal exits 0: it is not a failed run.
effect after the refresh: DIR/effect.md -- each matchup's win % this week and
       the title odds, before and after; "priced after tonight's games" when
       the refresh found prices locked; the failure when it failed.

NICK (the one login whose entries apply, invariant 12) is this file's
constant; the workflow's job conditions use the same login (a test pins it).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

NICK = "nickrolen"
REFUSED_LABEL = "entry-refused"
UNAUTHORIZED = "Only Nick's entries are applied."
BOT_LABELS = ("run-failed", "move-ledger", "nba-schedule", "return-passed")


def authorized(author: str, sender: str) -> bool:
    """Invariant 12: only Nick's own issue, opened or edited by Nick."""
    return str(author or "").lower() == NICK and str(sender or "").lower() == NICK


# =============================================================================
# what was applied already
# =============================================================================

def applied_as(base: Path, issue: int):
    """A short description of how issue #issue was applied, or None."""
    from modules import move_ledger as ml, override_history as oh
    r = oh.applied_issue(base, issue)
    if r is not None:
        return f"{r['action']} {r['player']} ({r['at'][:16].replace('T', ' ')} Pacific)"
    for e in ml.entries(ml.read_rows(base)):
        if e.get("issue") == int(issue):
            return f"ledger entry {e['id']}: {e['text']}"
    return None


# =============================================================================
# one entry
# =============================================================================

def _league_time(text: str) -> datetime:
    from modules.league_clock import league_tz
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"{text!r} carries no time zone")
    return t.astimezone(league_tz())


def _json_block(obj) -> str:
    if obj is None:
        return "(no entry)"
    return "```json\n" + json.dumps(obj, indent=1, ensure_ascii=False) + "\n```"


def apply_one(base: Path, title: str, issue: int, created_at: datetime, now: datetime) -> dict:
    """{"verdict": "applied" | "refused", "comment": text, "cause": str or None}.
    Writes state only when applied."""
    import overrides as ov
    from modules import injury_entries as ie, move_ledger as ml, phone_entries as pe
    from modules.data_loader import MANAGERS
    by = f"issue #{issue}"
    try:
        p = pe.parse_title(title, list(MANAGERS))
        if p["kind"] == "ledger":
            row = ml.add(base, p["text"], now=now, claimed_at=min(created_at, now),
                         entered_by=f"Nick (issue #{issue})", issue=issue)
            return {"verdict": "applied", "cause": p["text"], "comment": ledger_comment(base, row, now)}
        sched = json.loads((base / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
        f = p["form"]
        if f in ("add", "season"):
            ref = __import__("modules.nba_reference", fromlist=["Reference"]).Reference(base)
            name, notes = pe.split_subject(p["subject"], lambda n: ov.resolve_player(n, ref))
            back = pe.resolve_day(p["md"], now.date(), sched) if f == "add" else None
            ch = ov.add_change(base, name, back=back, season=(f == "season"), notes=notes, now=now,
                               out_day=created_at.date(), by=by, issue=issue, reference=ref)
        elif f == "set-return":
            back = pe.resolve_day(p["md"], now.date(), sched)
            ch = ov.set_return_change(base, p["name"], back, now=now, by=by, issue=issue)
        elif f == "set-notes":
            ch = ov.set_notes_change(base, p["name"], p["notes"], now=now, by=by, issue=issue)
        else:
            ch = ov.remove_change(base, p["name"], now=now, by=by, issue=issue)
        ov.apply(base, ch)
    except (pe.TitleRefused, ie.EntryRefused, ml.EntryRefused) as e:
        text = str(e)
        if "Accepted forms:" not in text:
            text += "\n\n" + pe.forms_text()
        return {"verdict": "refused", "cause": None,
                "comment": f"**Refused** (nothing was changed): {text}\n\nEdit the title to fix it, "
                           "or close this issue."}
    cause = pe.cause_of(ch["action"], ch["player"], ch["after"])
    comment = (f"**Applied:** {ch['action']} {ch['player']} (`config/INJURY_OVERRIDES.json`).\n\n"
               f"Before:\n{_json_block(ch['before'])}\n\nAfter:\n{_json_block(ch['after'])}\n\n"
               + "".join(f"- {s}\n" for s in ch["shown"])
               + f"\nThe hub refreshes now ({cause}); its effect follows in a second comment.")
    return {"verdict": "applied", "cause": cause, "comment": comment}


def ledger_comment(base: Path, row: dict, now: datetime) -> str:
    from modules import move_ledger as ml
    claimed = datetime.fromisoformat(row["claimed_at"])
    lines = [f"**Applied:** ledger entry {row['id']}: `{row['text']}`.", ""]
    if row["kind"] == "move":
        q = row["parsed"]
        parts = ([f"+{n}" for n in q["add"]] + [f"-{n}" for n in q["drop"]]
                 + [f"IL+{n}" for n in q["il_place"]] + [f"IL-{n}" for n in q["il_activate"]])
        lines.append(f"{q['manager']}: {' '.join(parts)}.")
    else:
        lines.append("; ".join(f"{s['manager']} gets {', '.join(s['gets'])}" for s in row["parsed"]["sides"]) + ".")
    lines.append(f"Claimed {claimed:%a %m-%d %I:%M %p} Pacific: it counts in week {row['claim_week']}'s "
                 f"budget and takes effect in the Mon {date.fromisoformat(row['window']):%m-%d} window "
                 f"(week {row['window_week']}).")
    if row["kind"] == "move" and row["parsed"]["add"]:
        world = ml.World.from_base(base, now=now)
        rows, states = ml.read_rows(base), ml.read_states(base)
        used = ml.adds_used(world, ml.entries(rows), states, row["claim_week"])
        m = row["parsed"]["manager"]
        lines.append(f"{m}: {len(used.get(m, []))} of {world.budget} used in week {row['claim_week']}.")
    lines += ["", "Checks: " + "; ".join(row["checks"]), "",
              "This week's line does not change (a claim takes effect next Monday); title odds and "
              "the hub refresh now. The effect follows in a second comment."]
    return "\n".join(lines)


# =============================================================================
# the effect (after the refresh)
# =============================================================================

def snapshot(base: Path, now: datetime) -> dict:
    """This week's win % per matchup and the title odds, as on disk now."""
    from modules.data_loader import load_all_data
    from modules.week_state import week_for_date
    data = load_all_data(base, current_week=None)
    week = week_for_date(data, now.date())
    out = {"week": week, "lines": None, "title_odds": None}
    lp = base / "output" / f"live_lines_week{week}.json"
    if lp.is_file():
        line = json.loads(lp.read_text(encoding="utf-8"))
        out["lines"] = {f"{ln['manager_a']}|{ln['manager_b']}": [ln["win_prob_a"], ln["win_prob_b"]]
                        for ln in line["lines"]}
        out["line_generated_at"] = line.get("generated_at")
    tp = base / "output" / "title_odds_latest.json"
    if tp.is_file():
        t = json.loads(tp.read_text(encoding="utf-8"))
        out["title_odds"] = (t.get("row") or t).get("title_odds")
    return out


def effect_text(before: dict, after: dict, run_row) -> str:
    if run_row is None:
        return "The refresh did not run; the 12:01 AM run prices the change."
    outcome = run_row.get("outcome")
    if outcome == "refused":
        return (f"The refresh failed ({run_row.get('error')}). The entry stands; the failure issue "
                "has the details, and the 12:01 AM run prices it.")
    if outcome == "deferred":
        return ("Priced by the 12:01 AM run: last night's games are not banked yet, and the nightly "
                "run banks them first.")
    if outcome == "locked":
        return "Priced after tonight's games (lines and title odds are locked while games are on)."
    lines = [f"**Effect** (week {after['week']}):"]
    for k, (a0, b0) in (before.get("lines") or {}).items():
        a, b = k.split("|")
        a1, b1 = (after.get("lines") or {}).get(k, [None, None])
        if a1 is None:
            continue
        lines.append(f"- {a} vs {b}: {a} {a0:.1f}% \u2192 {a1:.1f}%"
                     + ("" if abs(a1 - a0) >= 0.05 else " (unchanged)"))
    t0, t1 = before.get("title_odds") or {}, after.get("title_odds") or {}
    for m in sorted(t1, key=lambda m: -t1[m]):
        if m in t0:
            lines.append(f"- {m} title odds {t0[m]:.1f}% \u2192 {t1[m]:.1f}%")
    return "\n".join(lines)


# =============================================================================
# the CLI
# =============================================================================

def _gh_output(**kv) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        for k, v in kv.items():
            f.write(f"{k}={str(v).replace(chr(10), ' ')}\n")


def queue(event: dict, open_issues: list) -> list:
    """[(issue dict, is_event)] in issue order: the event's issue, then every
    other open issue of Nick's never answered (no entry-refused label, no bot
    label)."""
    ev = event["issue"]
    items = {int(ev["number"]): ({"number": int(ev["number"]), "title": ev["title"],
                                  "author": (ev.get("user") or {}).get("login"),
                                  "created_at": ev["created_at"],
                                  "labels": [x["name"] for x in ev.get("labels") or []],
                                  "state": ev.get("state")}, True)}
    for i in open_issues or []:
        n = int(i["number"])
        labels = [x["name"] for x in i.get("labels") or []]
        author = (i.get("author") or {}).get("login")
        if n in items or str(author).lower() != NICK or REFUSED_LABEL in labels \
                or any(b in labels for b in BOT_LABELS):
            continue
        items[n] = ({"number": n, "title": i["title"], "author": author, "created_at": i["createdAt"],
                     "labels": labels, "state": "open"}, False)
    return [items[n] for n in sorted(items)]


def cmd_apply(a) -> int:
    from modules.league_clock import league_now
    base = Path(a.base_path)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = _league_time(a.now) if a.now else league_now()
    event = json.loads(Path(a.event).read_text(encoding="utf-8"))
    open_issues = json.loads(Path(a.open_issues).read_text(encoding="utf-8")) if a.open_issues else []
    sender = (event.get("sender") or {}).get("login")
    action = event.get("action")
    (out / "before.json").write_text(json.dumps(snapshot(base, now), indent=1), encoding="utf-8")
    actions, causes = [], []
    for item, is_event in queue(event, open_issues):
        n = item["number"]
        act = {"issue": n, "verdict": None, "comment": None, "close": False, "label": None,
               "unlabel": False}
        if not authorized(item["author"], sender if is_event else item["author"]):
            act.update(verdict="unauthorized", comment=UNAUTHORIZED)
        elif (done := applied_as(base, n)) is not None:
            act.update(verdict="already", close=item.get("state") == "open",
                       comment=(f"Already applied as {done}; open a new issue to change it."
                                if is_event and action == "edited" else None))
        else:
            res = apply_one(base, item["title"], n, _league_time(item["created_at"]), now)
            act["verdict"] = res["verdict"]
            act["comment"] = res["comment"]
            if res["verdict"] == "applied":
                act["close"] = True
                act["unlabel"] = REFUSED_LABEL in item["labels"]
                causes.append(res["cause"])
            else:
                act["label"] = REFUSED_LABEL
        if act["comment"]:
            (out / f"{n}.md").write_text(act["comment"] + "\n", encoding="utf-8")
            act["comment_file"] = f"{n}.md"
        actions.append(act)
        print(f"issue #{n}: {act['verdict']}")
    (out / "actions.json").write_text(json.dumps(actions, indent=1), encoding="utf-8")
    cause = causes[0] if len(causes) == 1 else (f"{len(causes)} entries: " + "; ".join(causes)
                                                 if causes else "")
    (out / "cause.txt").write_text(cause + "\n", encoding="utf-8")
    _gh_output(applied="true" if causes else "false", cause=cause)
    return 0


def cmd_effect(a) -> int:
    from modules.league_clock import league_now
    base = Path(a.base_path)
    out = Path(a.out_dir)
    before = json.loads((out / "before.json").read_text(encoding="utf-8"))
    rows = []
    p = Path(a.runs_file)
    if p.is_file():
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()[a.skip:] if x.strip()]
    runs = [r for r in rows if r.get("mode") == "refresh"]
    after = snapshot(base, league_now())
    text = effect_text(before, after, runs[-1] if runs else None)
    (out / "effect.md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def cmd_check(a) -> int:
    from modules import phone_entries as pe
    try:
        p = pe.parse_title(a.title)
    except pe.TitleRefused as e:
        print(f"REFUSED: {e}")
        return 2
    print(json.dumps(p, indent=1))
    print(f"canonical: {pe.format_title(p)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-path", default=str(ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--event", required=True, help="the workflow's event payload ($GITHUB_EVENT_PATH)")
    p.add_argument("--open-issues", help="gh issue list --json number,title,createdAt,author,labels")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--now", help="ISO time (tests)")
    p = sub.add_parser("effect")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--runs-file", default="output/nightly_runs.jsonl")
    p.add_argument("--skip", type=int, default=0)
    p = sub.add_parser("check")
    p.add_argument("title")
    a = ap.parse_args(argv)
    return {"apply": cmd_apply, "effect": cmd_effect, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
