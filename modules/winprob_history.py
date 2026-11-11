"""
winprob_history.py -- each week's win % over the week, one row per PRICED
live-lines run (hub polish 3, task 48b; Nick, 11-10: "once a night", "one
model throughout").

    output/live_lines_weekN.winprob.jsonl      (league state, the manifest)

The live line (output/live_lines_weekN.json) is overwritten every time it is
priced, so the pricer (scripts/refresh_lines._write: the nightly, the Monday
pre-tip runs, a forced or manual run) appends one row here each time it
writes a line. An "unchanged" or "locked" run writes no line, so no row.
Every row is the live-lines pricer's own win_prob_a / win_prob_b with the
week's seed: one model.

Row:
    {"schema": 1, "week", "run_id", "trigger", "as_of" (the run's clock, the
     line's generated_at), "league_day" (the day priced as of),
     "completed_dates", "matchups": [{"manager_a", "manager_b",
     "win_prob_a", "win_prob_b", "banked_a", "banked_b",
     "projected_final_a", "projected_final_b"}]}

Step 3a (decision 1, Nick 11-10: "as granular as possible"): a row may
also carry "cause" -- what triggered the run, named by the caller from its
own inputs ("nightly", "Monday pre-tip", "injury update: Zion Williamson
out, back 11-21") -- and "changed", the line's cache-key parts that moved
since the line before it (["overrides", "tags"]). The Win % view's tap text
shows the cause. Rows written before this have neither and show their
trigger as before; nothing is back-filled.

APPEND-ONLY (modules/jsonl_log), like the title-odds history: a row
is never rewritten, a run id is written once. The HUB DRAWS FROM IT AND
NOTHING SCORES IT: calibration is the closing line and the weekly build
(modules/calibration_log), and a source test pins that no scorer names this
file (tests/test_hub_polish3.py, as invariant 13 is pinned).
"""

from __future__ import annotations

from pathlib import Path

SCHEMA = 1
MATCHUP_KEYS = ("manager_a", "manager_b", "win_prob_a", "win_prob_b", "banked_a", "banked_b",
                "projected_final_a", "projected_final_b")
ROW_KEYS = ("schema", "week", "run_id", "trigger", "as_of", "league_day", "completed_dates",
            "matchups")


class WinProbHistoryError(RuntimeError):
    pass


def path_for(base_path, week: int) -> Path:
    return Path(base_path) / "output" / f"live_lines_week{int(week)}.winprob.jsonl"


def row_from_line(line: dict) -> dict:
    """The history row of a priced line payload (refresh_lines.compute's).
    RAISES on a payload without the fields a row needs."""
    pb = line.get("produced_by") or {}
    run_id = pb.get("run_id") or f"manual-{line['generated_at']}"
    trigger = pb.get("trigger") or "manual"
    try:
        row = {"schema": SCHEMA, "week": int(line["week"]), "run_id": str(run_id),
               "trigger": str(trigger), "as_of": str(line["generated_at"]),
               "league_day": str(line["as_of"])[:10],
               "completed_dates": list(line["completed_dates"]),
               "matchups": [{k: ln[k] for k in MATCHUP_KEYS} for ln in line["lines"]]}
    except KeyError as e:
        raise WinProbHistoryError(f"a week-{line.get('week')} line lacks {e}: no win-% row") from None
    if pb.get("cause"):
        row["cause"] = str(pb["cause"])
        row["changed"] = [str(x) for x in pb.get("changed") or []]
    return row


def label(row: dict) -> str:
    """The tap text's label for a row: its cause (Step 3a), with any line
    input that moved besides the one the cause names; a row from before the
    causes began shows its trigger, as it always did."""
    cause = row.get("cause")
    if not cause:
        return f"{row['trigger']} run"
    own = {"overrides"} if str(cause).startswith(("injury", "injuries")) else set()
    if str(cause) in ("nightly", "Monday pre-tip"):
        return cause
    extra = [c for c in row.get("changed") or [] if c not in own]
    return cause + (f"; also moved: {', '.join(extra)}" if extra else "")


def check_row(row: dict, where: str) -> None:
    missing = [k for k in ROW_KEYS if k not in row]
    if missing or row.get("schema") != SCHEMA:
        raise WinProbHistoryError(f"{where}: not a schema-{SCHEMA} win-% row (missing {missing})")
    for m in row["matchups"]:
        miss = [k for k in MATCHUP_KEYS if k not in m]
        if miss:
            raise WinProbHistoryError(f"{where}: a matchup lacks {miss}")


def read(base_path, week: int) -> list:
    """Every row of week N's history, in order; [] when the file does not exist
    (a week before the history began). A malformed row RAISES."""
    from . import jsonl_log
    p = path_for(base_path, week)
    try:
        rows = jsonl_log.read_rows(p, label=p.name)
    except jsonl_log.LogCorrupt as e:
        raise WinProbHistoryError(str(e)) from None
    for i, r in enumerate(rows, 1):
        check_row(r, f"{p.name} row {i}")
        if int(r["week"]) != int(week):
            raise WinProbHistoryError(f"{p.name} row {i} is for week {r['week']}")
    return rows


def append(base_path, row: dict) -> bool:
    """Append one row; a run id already in the file writes nothing (False)."""
    from . import jsonl_log
    check_row(row, "the new row")
    have = read(base_path, row["week"])
    if any(r["run_id"] == row["run_id"] for r in have):
        return False
    p = path_for(base_path, row["week"])
    p.parent.mkdir(parents=True, exist_ok=True)
    jsonl_log.append_rows(p, [row])
    return True
