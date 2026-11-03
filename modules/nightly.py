"""
nightly.py -- everything the nightly run does, in order (step 1c-i).

    python scripts\\nightly.py                        the nightly run (12:01 AM, league clock)
    python scripts\\nightly.py --pretip               Monday's pre-tip run
    python scripts\\nightly.py --closing --week N     week N's closing line

claude/HANDOFF_STEP1C1_NIGHTLY_RUN_2026-11-03.md is the spec; SELF_RUNNING_DESIGN
s.2.4 and s.4 the design. The nightly run:

   1 engine        the engine is clean and at a known commit (a dirty one
                   refuses unless --allow-dirty-engine, for a builder's own
                   testing only: the runner never passes it)
   2 logs          update_fantasy_logs for every finished league day LINEUPS
                   lacks, across week boundaries (refresh_service.missing_days)
   3 sync          sync_transactions.nightly_sync: the transaction log, the
                   current week's partial adds file, ROSTERS.json (checked
                   against Yahoo's live rosters), IL_SLOTS.json
   4 settings      yahoo_settings.check: a drift refuses
   5 tags          fetch_playerlist --execute --no-bbref-ages and
                   check_playerlist (the live
                   file only; no daily PLAYERLIST snapshot), then Yahoo's
                   injury tags, recorded in output/tag_records.jsonl. Tags
                   are facts: recorded before anything asks to price, so a
                   locked night still refreshes them, and the hub reads them
   6 line          refresh_service.run (cache key, price lock, records),
                   with step 5's tags
   7 title_odds    title_odds_run.price at the week's seed: the history row,
                   output/title_odds_latest.json, output/stakes.json. Skipped
                   (nothing priced) when the line step found prices locked
   8 actuals       player_actuals.update
   9 hub           hub_state.build, then build_hub (encrypted when
                   HUB_PASSPHRASE is set, --preview-only otherwise).
                   Publishing is step 1c-ii
  10 the record    output/nightly_runs.jsonl: one row per run

FAILURE POLICY (refresh_service's): any step that refuses stops the run; the
outputs of the steps after it are left exactly as the last good run wrote
them; the run is recorded and exits 1. A price lock is not a failure: the run
exits 0 and prices nothing.

--scheduled (1c-ii's cron fires at 07:01 and 08:01 UTC): exit 0 and do
nothing unless the league clock is in the 00:xx hour. Exactly one of the two
firings passes on every day, across both DST changes (tests/test_nightly.py).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

RUNS_FILE = Path("output") / "nightly_runs.jsonl"
MODES = ("nightly", "pretip", "closing")
STEP_TIMEOUT_S = 900

STEPS = {
    "nightly": ("engine", "logs", "sync", "settings", "tags", "line", "title_odds", "actuals", "hub"),
    "pretip": ("engine", "window", "logs", "sync", "settings", "tags", "line", "title_odds", "hub"),
    "closing": ("engine", "window", "sync", "closing"),
}


class StepRefused(RuntimeError):
    """A step refused; the run stops here."""


def scheduled_guard_admits(now_utc: datetime) -> bool:
    """1c-ii's guard: True only when the league clock reads 00:xx."""
    from .league_clock import league_tz
    if now_utc.tzinfo is None:
        raise ValueError("the guard needs an aware time")
    return now_utc.astimezone(league_tz()).hour == 0


# =============================================================================
# the steps
# =============================================================================

def child_env() -> dict:
    """The environment every child script runs in: UTF-8 stdout and stderr.

    A child's stdout here is a pipe, not a console, and on Windows Python
    then writes in the locale's code page (cp1252), which cannot encode a
    name like "Jokic" with its accent: fetch_playerlist died printing one on
    Nick's machine on 11-03 (the builder's Linux VM is UTF-8, so it never
    showed). Forcing UTF-8 here, and decoding it as UTF-8 below, makes the
    run independent of the machine's code page."""
    import os
    return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")


def _subprocess(base: Path, args: list, what: str) -> str:
    cmd = [sys.executable, *args]
    try:
        r = subprocess.run(cmd, cwd=str(base), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=child_env(), timeout=STEP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise StepRefused(f"{what} ran past {STEP_TIMEOUT_S}s")
    if r.returncode != 0:
        tail = (r.stdout + "\n" + r.stderr).strip().splitlines()[-6:]
        raise StepRefused(f"{what} exited {r.returncode}: " + " | ".join(tail))
    return r.stdout


class Run:
    """One run. Each step is a method; ctx carries what later steps need."""

    def __init__(self, base_path=".", mode: str = "nightly", *, week: int = None, now: datetime = None,
                 allow_dirty_engine: bool = False, sims: int = None, title_sims: int = None,
                 echo=print):
        from .league_clock import league_now
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.base = Path(base_path)
        self.mode = mode
        self.now = now or league_now()
        self.today = self.now.date()
        self.week = week
        self.allow_dirty = allow_dirty_engine
        self.sims = sims
        self.title_sims = title_sims
        self.echo = echo
        self.run_id = f"{self.now.isoformat(timespec='microseconds')}-{mode}"
        self.ctx = {}

    # -- 1
    def step_engine(self):
        from .calibration_log import engine_version
        eng = engine_version(self.base)
        self.ctx["engine"] = eng
        if not eng.get("commit"):
            raise StepRefused("the engine's commit is unknown (not a git checkout?)")
        if eng.get("dirty") is None:
            raise StepRefused("whether the engine is dirty is unknown (git status failed)")
        if eng["dirty"] and not self.allow_dirty:
            raise StepRefused(f"the engine at {eng['commit']} is dirty (uncommitted changes under "
                              "modules/, scripts/ or league_config.json): a line priced now names "
                              "no code. Commit first.")
        return f"{eng['commit']}{' (dirty, --allow-dirty-engine)' if eng['dirty'] else ''}"

    # -- the window (pretip, closing)
    def step_window(self):
        from . import price_lock
        from .data_loader import load_all_data
        from .week_state import week_entry, week_for_date
        data = load_all_data(self.base, current_week=None)
        if self.mode == "pretip":
            week = week_for_date(data, self.today)
            monday = date.fromisoformat(str(week_entry(data, week)["start_date"])[:10])
            if self.today != monday:
                raise StepRefused(f"--pretip runs on the week's window day ({monday}), not {self.today}")
            first = price_lock.first_tip(monday, data.nba_schedule)
            if first is None or self.now >= first:
                raise StepRefused(f"--pretip runs before Monday's first tip "
                                  f"({first.isoformat(timespec='minutes') if first else 'no games'})")
            self.week = week
            return f"week {week}, before the first tip {first.isoformat(timespec='minutes')}"
        if self.week is None:
            raise StepRefused("--closing needs --week N")
        monday = date.fromisoformat(str(week_entry(data, self.week)["start_date"])[:10])
        close = price_lock.window_close(monday, data.nba_schedule)
        if self.now < close:
            raise StepRefused(f"week {self.week}'s window closes {close.isoformat(timespec='minutes')}; "
                              "the closing line is priced after the close")
        return f"week {self.week}'s window closed {close.isoformat(timespec='minutes')}"

    # -- 2
    def step_logs(self):
        import refresh_service as rs
        from .data_loader import load_all_data
        data = load_all_data(self.base, current_week=None)
        todo = rs.missing_days(data, self.today)
        for d in todo:
            rs.pull_logs_subprocess(self.base, d)
        if todo:
            left = rs.missing_days(load_all_data(self.base, current_week=None), self.today)
            if left:
                raise StepRefused(f"after the pull, LINEUPS still lacks {[d.isoformat() for d in left]}")
        self.ctx["logs_pulled"] = [d.isoformat() for d in todo]
        return ", ".join(d.isoformat() for d in todo) or "nothing to pull"

    # -- 3
    def step_sync(self):
        import sync_transactions as st
        out = st.nightly_sync(self.base, run_id=self.run_id, now=self.now,
                              echo=lambda *a: None)
        self.ctx["sync"] = out
        if self.week is None:
            self.week = out["week"]
        log = out["log"]
        return (f"week {out['week']}: {log['appended']} new transaction(s), {log['total']} logged; "
                + "; ".join(out["counts"]))

    # -- 4
    def step_settings(self):
        from . import yahoo_settings as ys
        got = ys.check(ys.fetch_raw())
        return f"{len(got)} modelled settings match"

    # -- 5
    def step_tags(self):
        from . import tag_records
        from .fetch_injury_statuses import fetch_injury_statuses
        done = []
        if self.mode == "nightly":
            # --no-bbref-ages: the nightly run reads Yahoo only; a missing
            # age is reported, never guessed, and Monday's workflow fetch
            # (Step 4.75) seeds it from basketball-reference as before
            _subprocess(self.base, ["scripts/fetch_playerlist.py", "--execute", "--no-bbref-ages"],
                        "fetch_playerlist --execute --no-bbref-ages")
            _subprocess(self.base, ["scripts/check_playerlist.py"], "check_playerlist")
            done.append("PLAYERLIST fetched and checked")
        tags = fetch_injury_statuses(oauth_file=str(self.base / "oauth2.json"), verbose=False)
        row = tag_records.append(self.base, tags, run_id=self.run_id, mode=self.mode,
                                 week=self.week, now=self.now)
        self.ctx["tags"] = tags
        n = sum(1 for t in dict(tags).values() if str(t).upper() != "HEALTHY")
        done.append(f"{n} rostered tag(s) recorded at {row['taken_at']}")
        return "; ".join(done)

    # -- 6
    def step_line(self):
        import refresh_service as rs
        from .simulator_betting import DEFAULT_NUM_SIMULATIONS
        out = rs.run(self.base, as_of=self.today, week=self.week,
                     sims=self.sims or DEFAULT_NUM_SIMULATIONS, trigger=self.mode,
                     pull_logs=False, statuses=self.ctx["tags"], now=self.now)
        self.ctx["line"] = out
        if out["exit"] != 0:
            raise StepRefused(f"refresh_service: {out.get('error')}")
        self.ctx["locked"] = out["outcome"] == "locked"
        return out["outcome"] + (f" ({out.get('why_priced')})" if out.get("why_priced") else "")

    # -- 7
    def step_title_odds(self):
        from . import title_odds_run as tor
        from .data_loader import SEASON_SIMS, load_all_data
        if self.ctx.get("locked"):
            self.ctx["title_odds_outcome"] = "locked"
            return "locked: nothing priced"
        sp_ = self.base / "output" / f"live_lines_week{self.week}.state.json"
        if not sp_.is_file():
            raise StepRefused(f"{sp_.relative_to(self.base).as_posix()} is missing: title odds are "
                              "priced at the week's seed")
        seed = int(json.loads(sp_.read_text(encoding="utf-8"))["seed"])
        sims = self.title_sims or SEASON_SIMS
        data = load_all_data(self.base, current_week=None)
        out = tor.price(self.base, data, seed=seed, sims=sims, statuses=self.ctx["tags"],
                        run_id=self.run_id, produced_by=f"nightly.py ({self.mode})", kind=self.mode,
                        week=self.week, now=self.now)
        odds = out["row"]["title_odds"]
        return (f"seed {seed}, {sims:,} sims: "
                + ", ".join(f"{m} {v:.1f}" for m, v in sorted(odds.items(), key=lambda kv: -kv[1])))

    # -- 8
    def step_actuals(self):
        from . import player_actuals as pa
        r = pa.update(self.base)
        return (f"through {r['through']}: {len(r['days_fetched'])} day(s), {r['calls']} call(s)"
                + (f"; backfilled {', '.join(r['backfilled'])}" if r["backfilled"] else ""))

    # -- 9
    def step_hub(self):
        import build_hub
        from . import hub_state
        payload = hub_state.build(self.base, now=self.now, allow_engine_mismatch=self.allow_dirty,
                                  echo=lambda *a: None)
        hub_state.write(self.base, payload)
        enc = bool(os.environ.get("HUB_PASSPHRASE"))
        rc = build_hub.main(["--base-path", str(self.base)] + ([] if enc else ["--preview-only"]))
        if rc != 0:
            raise StepRefused(f"build_hub exited {rc}")
        return ("encrypted publish directory" if enc else "preview only (no HUB_PASSPHRASE)") \
            + (" -- ENGINE MISMATCH banner (dirty engine)" if payload["header"]["engine_mismatch"] else "")

    # -- closing
    def step_closing(self):
        from . import closing_line
        out = closing_line.price(self.base, self.week, now=self.now, sims=self.sims,
                                 title_sims=self.title_sims)
        self.ctx["closing"] = out
        lines = "; ".join(f"{ln['matchup']} {ln['manager_a']} {ln['spread_a']:+.1f} "
                          f"({ln['win_prob_a']:.1f}%)" for ln in out["line"]["lines"])
        return f"{out['outcome']}: {lines}; calibration records added {out['calibration_added']}"

    # =========================================================================
    def execute(self, steps: dict = None) -> dict:
        """Run the mode's steps in order. steps: {name: callable} overrides
        (tests). Returns the run record's row (also appended to the file)."""
        from .league_clock import league_now
        started = league_now()
        rows, error, outcome = [], None, "ok"
        for name in STEPS[self.mode]:
            fn = (steps or {}).get(name) or getattr(self, f"step_{name}")
            t0 = time.perf_counter()
            try:
                detail = fn()
                rows.append({"step": name, "outcome": "ok", "seconds": round(time.perf_counter() - t0, 2),
                             "detail": str(detail or "")})
                self.echo(f"  [{name}] ok ({rows[-1]['seconds']} s): {detail}")
            except Exception as e:                          # noqa: BLE001 -- the policy
                error = f"{type(e).__name__}: {e}"
                rows.append({"step": name, "outcome": "refused",
                             "seconds": round(time.perf_counter() - t0, 2), "detail": error})
                self.echo(f"  [{name}] REFUSED ({rows[-1]['seconds']} s): {error}")
                self.echo(traceback.format_exc())
                outcome = "refused"
                break
        if outcome == "ok" and self.ctx.get("locked"):
            outcome = "locked"
        eng = self.ctx.get("engine") or {}
        row = {"run_id": self.run_id, "mode": self.mode, "week": self.week,
               "started_at": started.isoformat(timespec="seconds"),
               "finished_at": league_now().isoformat(timespec="seconds"),
               "seconds": round(sum(r["seconds"] for r in rows), 2),
               "engine": {"commit": eng.get("commit"), "dirty": eng.get("dirty")},
               "allow_dirty_engine": self.allow_dirty, "steps": rows, "outcome": outcome,
               "exit": 1 if outcome == "refused" else 0, "error": error}
        from .jsonl_log import append_rows
        append_rows(self.base / RUNS_FILE, [row])
        return row


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The nightly run, Monday's pre-tip run, or a week's "
                                             "closing line (step 1c-i).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--pretip", action="store_true", help="Monday's pre-tip run (before the first tip)")
    g.add_argument("--closing", action="store_true", help="the closing line for --week N")
    ap.add_argument("--week", type=int)
    ap.add_argument("--scheduled", action="store_true",
                    help="exit 0 doing nothing unless the league clock reads 00:xx (1c-ii's cron)")
    ap.add_argument("--allow-dirty-engine", action="store_true",
                    help="builder testing only: run on uncommitted code. The runner never passes it")
    ap.add_argument("--sims", type=int, help="line simulations (default: the line's default)")
    ap.add_argument("--title-sims", type=int, help="title-odds simulations (default: season_sims)")
    ap.add_argument("--base-path", default=".")
    a = ap.parse_args(argv)
    if a.scheduled:
        from datetime import timezone
        if not scheduled_guard_admits(datetime.now(timezone.utc)):
            print("--scheduled: the league clock is not in the 00:xx hour; nothing to do.")
            return 0
    if a.week is not None and not a.closing:
        ap.error("--week goes with --closing")
    mode = "pretip" if a.pretip else "closing" if a.closing else "nightly"
    run = Run(a.base_path, mode, week=a.week, allow_dirty_engine=a.allow_dirty_engine,
              sims=a.sims, title_sims=a.title_sims)
    print(f"{mode} run {run.run_id}")
    row = run.execute()
    print(f"{mode} run {row['outcome'].upper()} in {row['seconds']} s"
          + (f": {row['error']}" if row["error"] else "")
          + f" (recorded in {RUNS_FILE.as_posix()})")
    return row["exit"]
