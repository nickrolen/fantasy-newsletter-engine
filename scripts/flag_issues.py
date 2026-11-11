#!/usr/bin/env python3
"""
flag_issues.py -- step 3b's issues, planned. Standard library only; nothing
here calls GitHub (the workflow carries the plan out with gh).

    python3 scripts/flag_issues.py plan --kind nudge|nba --runs-file output/nightly_runs.jsonl \\
        --skip N --open open.tsv --out-dir DIR

open.tsv: the open issues with the kind's label, "<number>\\t<title>" per line.
Writes DIR/plan.tsv, one action per line, and the body files it names:
    create\\t-\\t<title>\\t<body file>
    edit\\t<number>\\t<new title>\\t-
    close\\t<number>\\t-\\t<comment file>

nudge (label o-no-entry; modules/o_nudge, the nightly run's "nudges" block):
  ONE ISSUE PER PLAYER. An open issue is his whatever count its title shows
  ("<Name> has been O for ..." or "<Name> is tagged O with no injury entry:
  can't count his games"): the count grows nightly, and matching whole titles
  would open a new issue every night. A changed count edits the title; an open
  one the night no longer lists (he has an entry, or is no longer O) is closed.
  The block is only on nightly rows; no block, no plan.
nba (label nba-report; modules/nba_injury_report, the run's "nba_report" block):
  ONE ISSUE PER PLAYER PER GAME: deduped by the whole title, which carries the
  game's day ("NBA report: Zion Williamson out Tue 11-10 (Yahoo: Q)"). An open
  one whose day is before the run's league day is closed (the game is over).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

NUDGE_LABEL, NBA_LABEL = "o-no-entry", "nba-report"
DAY_RE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d\d)-(\d\d)\b")


def last_row(runs_file: str, skip: int, key: str):
    p = Path(runs_file)
    if not p.is_file():
        return None
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()[skip:] if x.strip()]
    rows = [r for r in rows if r.get(key) is not None]
    return rows[-1] if rows else None


def read_open(path: str) -> list:
    out = []
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                n, _, t = line.partition("\t")
                out.append((int(n), t))
    return out


def nudge_matches(issue_title: str, player: str) -> bool:
    """modules/o_nudge.title's two shapes, for this player, any count."""
    t = str(issue_title)
    return (t.startswith(f"{player} has been O for ")
            or t == f"{player} is tagged O with no injury entry: can't count his games")


def plan_nudges(items: list, open_: list) -> list:
    acts, kept = [], set()
    for it in items:
        mine = [(n, t) for n, t in open_ if nudge_matches(t, it["player"])]
        if not mine:
            acts.append(("create", None, it["title"], it["body"]))
            continue
        n, t = mine[0]
        kept.update(x for x, _ in mine)
        if t != it["title"]:
            acts.append(("edit", n, it["title"], None))
        for n2, _ in mine[1:]:                            # a duplicate: never two for one player
            acts.append(("close", n2, None, f"Duplicate of #{n}."))
    for n, t in open_:
        if n not in kept:
            acts.append(("close", n, None, "Answered: he has an injury entry or is no longer tagged O."))
    return acts


def nba_titles(block: dict) -> list:
    out = [{"title": f["title"], "body": (f"{f['text']}. The NBA's injury report has him Out for "
                                          f"this game, and it counts as a certain miss for it now. "
                                          f"Yahoo shows {f['yahoo']}. If the report is right, nothing "
                                          "to do; an injury entry (`Injury: <name> <notes>, back MM/DD`) "
                                          "is for a longer absence.")}
           for f in block.get("flags") or []]
    for x in block.get("loud") or []:
        d = date.fromisoformat(x["game_date"])
        out.append({"title": f"NBA report name {x['name']} ({x['team']}) not matched; is it "
                             f"{x['maybe']}? ({d:%a %m-%d})",
                    "body": (f"The NBA's injury report lists {x['name']} ({x['team']}) as "
                             f"{x['status']} for {d:%a %m-%d}, and the name matches no player the "
                             f"engine knows. It looks like rostered {x['maybe']}: if it is him, his "
                             "report status is not applied. Check him, and his name's spelling "
                             "(data/NBA_PLAYER_REFERENCE.json).")})
    return out


def title_day(title: str, league_day: date):
    """The game day a title names ("... Tue 11-10 ..."), in the year that puts
    it nearest the league day (a December game read in January), or None."""
    m = DAY_RE.search(str(title))
    if not m:
        return None
    mo, dy = int(m.group(1)), int(m.group(2))
    cands = []
    for y in (league_day.year - 1, league_day.year, league_day.year + 1):
        try:
            cands.append(date(y, mo, dy))
        except ValueError:
            pass
    return min(cands, key=lambda d: abs((d - league_day).days)) if cands else None


def plan_nba(block: dict, open_: list, league_day: date) -> list:
    acts, want = [], nba_titles(block or {})
    have = {t for _, t in open_}
    for it in want:
        if it["title"] not in have:
            acts.append(("create", None, it["title"], it["body"]))
    for n, t in open_:
        d = title_day(t, league_day)
        if d is not None and d < league_day:
            acts.append(("close", n, None, "The game is over."))
    return acts


def write_plan(acts: list, out_dir: str) -> Path:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, (kind, n, title, text) in enumerate(acts):
        f = "-"
        if text is not None:
            f = f"flag_{i}.md"
            (d / f).write_text(text + "\n", encoding="utf-8")
        for v in (title or "",):
            if "\t" in v or "\n" in v:
                raise SystemExit(f"a title with a tab or newline: {v!r}")
        lines.append("\t".join([kind, str(n) if n is not None else "-", title or "-", f]))
    p = d / "plan.tsv"
    p.write_text("".join(x + "\n" for x in lines), encoding="utf-8")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=("plan",))
    ap.add_argument("--kind", required=True, choices=("nudge", "nba"))
    ap.add_argument("--runs-file", required=True)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--open", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    open_ = read_open(a.open)
    if a.kind == "nudge":
        row = last_row(a.runs_file, a.skip, "nudges")
        acts = [] if row is None else plan_nudges(row["nudges"], open_)
    else:
        row = last_row(a.runs_file, a.skip, "nba_report")
        acts = [] if row is None else plan_nba(row["nba_report"], open_,
                                               date.fromisoformat(str(row["started_at"])[:10]))
    p = write_plan(acts, a.out_dir)
    for kind, n, title, _ in acts:
        print(f"{kind} {n or ''} {title or ''}".strip())
    print(f"{len(acts)} action(s) -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
