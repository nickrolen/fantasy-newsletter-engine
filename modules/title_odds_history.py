"""
title_odds_history.py -- every title-odds run, kept as history.

Nick, 10-30 (claude/SELF_RUNNING_DESIGN.md s.1 decision 4, s.4 step 6,
invariant 13): keep every title-odds run -- the Monday build's and, from step
1c, every nightly one -- for a "title odds over time" chart on the hub and as
an audit trail. Calibration scores only the Monday publications: nightly runs
are correlated guesses about one outcome per season and would swamp the
scored record. So this file is HISTORY, never a score:
  - nothing that scores probabilities reads it (modules/calibration_log and
    every reader of the curve; a source test pins it);
  - it is league state, kept in the private repo (config/STATE_MANIFEST.json).

output/title_odds_history.jsonl, one JSON object per line, APPEND-ONLY:
    run_id, produced_by, as_of (the league clock, when the run priced),
    week, engine {commit, dirty}, engine_key, seed, num_simulations,
    title_odds {manager: %}, and playoff_odds / cup_odds when the run
    computed them.
A row is never rewritten. A malformed existing file RAISES (naming the line);
it is never truncated or repaired here.
"""

from __future__ import annotations

import json
from pathlib import Path

HISTORY_FILE = Path("output") / "title_odds_history.jsonl"
REQUIRED = ("run_id", "produced_by", "as_of", "engine", "engine_key", "seed",
            "num_simulations", "title_odds")
OPTIONAL = ("week", "playoff_odds", "cup_odds")


class HistoryCorrupt(ValueError):
    """The history file holds a line that is not a valid row."""


def _check(row: dict, where: str) -> None:
    if not isinstance(row, dict):
        raise HistoryCorrupt(f"{where}: not a JSON object")
    missing = [k for k in REQUIRED if k not in row]
    if missing:
        raise HistoryCorrupt(f"{where}: missing {missing}")
    unknown = sorted(set(row) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        raise HistoryCorrupt(f"{where}: unknown field(s) {unknown}")
    odds = row["title_odds"]
    if not isinstance(odds, dict) or not odds or not all(
            isinstance(v, (int, float)) for v in odds.values()):
        raise HistoryCorrupt(f"{where}: title_odds must be {{manager: number}}")


def read(base_path=".") -> list:
    """Every row, in order. No file is no rows. Raises HistoryCorrupt on any
    malformed line, and on a file whose last line is unterminated (a write
    that was cut off): the file is evidence, never silently skipped."""
    path = Path(base_path) / HISTORY_FILE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        raise HistoryCorrupt(f"{HISTORY_FILE}: the last line is unterminated (a cut-off write); "
                             "fix the file by hand -- it is never truncated here")
    rows = []
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise HistoryCorrupt(f"{HISTORY_FILE} line {i}: blank line")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise HistoryCorrupt(f"{HISTORY_FILE} line {i}: not JSON ({e})") from None
        _check(row, f"{HISTORY_FILE} line {i}")
        rows.append(row)
    return rows


def append(base_path, row: dict) -> dict:
    """Append one row. Reads (and so validates) the whole file first; the
    file is only ever opened for appending."""
    _check(row, "the new row")
    existing = read(base_path)
    if any(r["run_id"] == row["run_id"] for r in existing):
        raise HistoryCorrupt(f"run {row['run_id']} is already in {HISTORY_FILE}: a row is "
                             "never rewritten or repeated")
    path = Path(base_path) / HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def make_row(*, base_path, run_id: str, produced_by: str, seed: int, num_simulations: int,
             title_odds: dict, week=None, playoff_odds=None, cup_odds=None, as_of=None) -> dict:
    """A row for one run, stamped with the engine (calibration_log's one
    definition) and the league clock."""
    from .calibration_log import engine_key, engine_version
    from .league_clock import league_now
    eng = engine_version(base_path)
    row = {
        "run_id": str(run_id), "produced_by": str(produced_by),
        "as_of": (as_of or league_now()).isoformat(timespec="seconds"),
        "engine": {"commit": eng["commit"], "dirty": eng["dirty"]},
        "engine_key": engine_key({"engine_commit": eng["commit"], "engine_dirty": eng["dirty"]}),
        "seed": int(seed), "num_simulations": int(num_simulations),
        "title_odds": {str(m): float(v) for m, v in title_odds.items()},
    }
    if week is not None:
        row["week"] = int(week)
    if playoff_odds:
        row["playoff_odds"] = playoff_odds
    if cup_odds:
        row["cup_odds"] = {str(m): float(v) for m, v in cup_odds.items()}
    return row


def row_from_report(report: dict, *, base_path, run_id: str, produced_by: str, seed: int,
                    num_simulations: int) -> dict:
    """The row for a weekly build's stats report: its power rankings' title
    odds (or championship odds in playoff weeks) and its Cup odds."""
    pr = report.get("power_rankings") or []
    odds = {r["manager"]: r["title_odds"] for r in pr if r.get("title_odds") is not None}
    if not odds:
        raise ValueError("this report has no title odds (a --fast run?): nothing to record")
    playoff = report.get("playoff_odds")
    return make_row(base_path=base_path, run_id=run_id, produced_by=produced_by, seed=seed,
                    num_simulations=num_simulations, title_odds=odds,
                    week=(report.get("metadata") or {}).get("week") or report.get("week"),
                    playoff_odds=({"playoff_round": playoff.get("playoff_round"),
                                   "finish_distribution": playoff.get("finish_distribution")}
                                  if playoff else None),
                    cup_odds=(report.get("cup_odds") or {}).get("cup_odds"))
