#!/usr/bin/env python3
"""
refresh_service.py -- B3, the live line refreshed every midnight.

    py scripts\\refresh_service.py [--trigger scheduled] [--as-of YYYY-MM-DD]
                                   [--week N] [--sims N] [--skip-log-pull]

One run a day, from Windows Task Scheduler at midnight (WEEKLY_WORKFLOW.md,
"Live line: the midnight refresh"); runnable by hand with the same arguments.
No polling, no file watches. Manual refresh is unchanged:
scripts/refresh_lines.py, exactly as before.

A run:
  1. pulls the logs (update_fantasy_logs.py) for every completed day of the
     week that LINEUPS does not yet cover -- at midnight, normally yesterday;
     on a rerun, nothing (--skip-log-pull to skip the step);
  2. gathers the line's inputs and checks them (refresh_lines.prepare: the
     week's seed, the Yahoo tags, the tag anchors, the played state) --
     raising exactly where a manual refresh raises;
  3. computes the CACHE KEY (week_state.line_cache_key): the played state
     (state_hash) AND the tags, the projections used, the governing
     INJURY_OVERRIDES entries, the schedule, the assumptions, the seed, the
     simulation count and the engine commit. state_hash alone covers none of
     the inputs after the first, so it would serve a stale line after exactly
     the changes this run exists to catch;
  4. if the key equals the one on output/live_lines_weekN.json, does
     nothing: the line is left byte-for-byte as it was. A dirty or unknown
     engine never matches (the commit does not identify the code);
  5. otherwise prices the line (refresh_lines.price): the line, the week's
     state, the calibration records and the tag log, with the run that
     produced it and the key written into the line.

FAILURE (a scheduled run has nobody to ask): any refusal -- a Yahoo fetch
that fails, an unmodelled tag, a missing log day, a log pull that fails --
is logged loudly to output/refresh_service.log and stderr, the previous line
is left in place untouched, and the run exits 1. Every run, good or bad, is
recorded in output/live_lines_weekN.runs.json, which says which run produced
the line on disk and which runs have failed since. (The line itself is not
rewritten to say so: "leave the previous output in place" and "a no-change
refresh is byte-identical" both mean the line file is only ever written by a
run that priced a new line.)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from modules.data_loader import atomic_write_json, load_all_data           # noqa: E402
from modules import simulator_betting as sb                                # noqa: E402
from modules import week_state as ws                                       # noqa: E402
import refresh_lines as rl                                                 # noqa: E402

SERVICE_LOG = Path("output") / "refresh_service.log"
PULL_TIMEOUT_S = 900


class LogPullFailed(RuntimeError):
    pass


def runs_path(base: Path, week: int) -> Path:
    return Path(base) / "output" / f"live_lines_week{week}.runs.json"


def line_path(base: Path, week: int) -> Path:
    return Path(base) / "output" / f"live_lines_week{week}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _log(base: Path, msg: str, loud: bool = False) -> None:
    path = Path(base) / SERVICE_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{_now()} {msg}\n")
    print(msg, file=sys.stderr if loud else sys.stdout)


def days_to_pull(data, week: int, as_of: date) -> list:
    """Completed days of the week (strictly before as_of) with NBA games on
    which LINEUPS lacks rows for some manager -- the days week_state would
    refuse as missing. A day already covered is not pulled again."""
    from modules.data_loader import MANAGERS
    entry = ws.week_entry(data, week)
    lu = data.lineups
    out = []
    for d in sb.get_dates_in_week(entry):
        if d >= as_of or not sb._playing_teams(data, d):
            continue
        rows = lu[lu["date"].astype(str).str[:10] == d.isoformat()] if len(lu) else lu
        have = set(rows["manager"]) if len(rows) else set()
        if any(m not in have for m in MANAGERS):
            out.append(d)
    return out


def pull_logs_subprocess(base: Path, day: date) -> None:
    """update_fantasy_logs.py for one day, run from the project folder (it
    reads oauth2.json and config/ relative to the working directory)."""
    cmd = [sys.executable, str(Path(base) / "scripts" / "update_fantasy_logs.py"),
           "--date", day.isoformat()]
    try:
        r = subprocess.run(cmd, cwd=str(base), capture_output=True, text=True,
                           timeout=PULL_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise LogPullFailed(f"update_fantasy_logs.py --date {day} ran past {PULL_TIMEOUT_S}s")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-5:]
        raise LogPullFailed(f"update_fantasy_logs.py --date {day} exited {r.returncode}: "
                            + " | ".join(tail))


def _record(base: Path, week: int, run: dict) -> dict:
    """Append `run` to the week's run record and recompute its summary from
    the line actually on disk: which run produced it, and the runs that have
    failed since it was produced."""
    path = runs_path(base, week)
    blob = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"week": week, "runs": []}
    blob["runs"].append(run)
    lp = line_path(base, week)
    line = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else None
    if line is None:
        produced_by, produced_at = None, None
    else:
        produced_by = (line.get("produced_by") or {}).get("run_id") or "refresh_lines (manual)"
        produced_at = line.get("generated_at")
    blob["line_produced_by"] = produced_by
    blob["line_generated_at"] = produced_at
    # failures since the line: after the run that produced it, by position in
    # the record; a manually refreshed line has no run, so by its timestamp
    ids = [r["run_id"] for r in blob["runs"]]
    if produced_by in ids:
        since = blob["runs"][len(ids) - 1 - ids[::-1].index(produced_by) + 1:]
    else:
        since = [r for r in blob["runs"] if produced_at is None or r["started_at"] >= produced_at]
    blob["failed_since_line"] = [r["run_id"] for r in since if r["outcome"] == "failed"]
    blob["last_run"] = run["run_id"]
    blob["last_outcome"] = run["outcome"]
    atomic_write_json(path, blob)
    return blob


def run(base_path=".", as_of: date = None, week: int = None, sims: int = sb.DEFAULT_NUM_SIMULATIONS,
        trigger: str = "manual", pull_logs: bool = True, load=None, statuses=None,
        puller=None) -> dict:
    """One service run. Returns {"outcome": "priced"|"unchanged"|"failed",
    "exit": 0|1, "run_id", "week", ...}. Never raises: a refusal is the
    "failed" outcome, logged and recorded.

    load/statuses/puller are for tests: the data loader, a tag dict in place
    of the Yahoo fetch, and the per-day log pull."""
    base = Path(base_path)
    started = datetime.now().isoformat(timespec="microseconds")
    run_id = f"{started}-{trigger}"          # microseconds: two runs in one second stay distinct
    as_of = as_of or date.today()
    load = load or (lambda: load_all_data(base, current_week=None))
    puller = puller or (lambda day: pull_logs_subprocess(base, day))
    rec = {"run_id": run_id, "trigger": trigger, "started_at": started, "as_of": as_of.isoformat(),
           "logs_pulled": [], "outcome": None}
    try:
        data = load()
        week = week or ws.week_for_date(data, as_of)
        rec["week"] = week
        if pull_logs:
            todo = days_to_pull(data, week, as_of)
            for d in todo:
                puller(d)
                rec["logs_pulled"].append(d.isoformat())
            if todo:
                data = load()
        p = rl.prepare(base, week, as_of, statuses=statuses, data=data)
        key = rl.cache_key(p, sims)
        rec["cache_key"] = key["key"]
        lp = line_path(base, week)
        on_disk = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else None
        on_disk_key = ((on_disk or {}).get("cache") or {}).get("key")
        if key["cacheable"] and on_disk_key == key["key"]:
            rec["outcome"] = "unchanged"
            msg = f"week {week} as of {as_of}: nothing changed (key {key['key']}); line left as is"
        else:
            rec["why_priced"] = ("no line on disk" if on_disk is None else
                                 key["why_not"] if not key["cacheable"] else
                                 "line on disk has no cache key (a manual refresh)" if on_disk_key is None
                                 else "inputs changed: " + ", ".join(
                                     k for k, v in key["parts"].items()
                                     if ((on_disk.get("cache") or {}).get("parts") or {}).get(k) != v))
            rl.price(p, sims, produced_by=run_id, key=key,
                     extra={"produced_by": {"run_id": run_id, "trigger": trigger,
                                            "started_at": started},
                            "cache": key})
            rec["outcome"] = "priced"
            msg = f"week {week} as of {as_of}: priced ({rec['why_priced']}); key {key['key']}"
        rec["finished_at"] = _now()
        _record(base, week, rec)
        _log(base, f"[{run_id}] OK {msg}")
        return {**rec, "exit": 0}
    except Exception as e:                                   # noqa: BLE001 -- the policy
        rec["outcome"] = "failed"
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["finished_at"] = _now()
        _log(base, f"[{run_id}] REFUSED -- {rec['error']}. The previous line is left in place; "
                   "nothing was written.\n" + traceback.format_exc(), loud=True)
        if rec.get("week") is not None:
            try:
                _record(base, rec["week"], rec)
            except Exception as e2:                          # noqa: BLE001
                _log(base, f"[{run_id}] could not record the failure: {e2}", loud=True)
        return {**rec, "exit": 1}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--trigger", default="manual", choices=("scheduled", "manual"),
                    help="who started this run; Task Scheduler passes 'scheduled'")
    ap.add_argument("--as-of", type=lambda s: date.fromisoformat(s))
    ap.add_argument("--week", type=int)
    ap.add_argument("--sims", type=int, default=sb.DEFAULT_NUM_SIMULATIONS)
    ap.add_argument("--skip-log-pull", action="store_true",
                    help="do not run update_fantasy_logs.py for uncovered days first")
    ap.add_argument("--base-path", default=".")
    a = ap.parse_args(argv)
    out = run(a.base_path, a.as_of, a.week, a.sims, a.trigger, not a.skip_log_pull)
    return out["exit"]


if __name__ == "__main__":
    sys.exit(main())
