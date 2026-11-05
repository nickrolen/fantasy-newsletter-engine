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
  4b schedule      (nightly only; task 33) refetch the NBA schedule at most once a
                   league day (modules/nba_schedule.refetch, through
                   fetch_nba_schedule.fetch_trimmed, basketball-reference):
                   written to the refetched
                   copy (league state) only if it never shrinks; a failed or
                   refused fetch keeps the stored schedule and is named in the
                   detail -- it never fails the night. Then (task 46) the stand-ins
                   for games the NBA has not scheduled are counted into the run
                   record's "schedule" block; from the window day of the fantasy
                   week holding the unscheduled window (Mon 11-30) on, stand-ins
                   still there are a flag: schedule_flags=true under the workflow
                   (the schedule issue, scripts/schedule_issue.py). Stand-ins
                   still needed on or after the window's first day raise (the
                   loader's rule): that does fail the night
   5 tags          fetch_playerlist --execute --no-bbref-ages and
                   check_playerlist (the live
                   file only; no daily PLAYERLIST snapshot), then Yahoo's
                   injury tags, recorded in output/tag_records.jsonl. Tags
                   are facts: recorded before anything asks to price, so a
                   locked night still refreshes them, and the hub reads them
 5b ledger        the move ledger (step 2, modules/move_ledger): verify every
                   pending entry against tonight's transaction log and IL slots
                   (applied / missing / conflict) and flag every Yahoo move
                   outside a Monday window that matches no entry, into
                   data/move_ledger_states.jsonl; on a window day the first run
                   publishes that Monday's checklist (output/move_checklist_
                   weekN.json, IL eligibility on tonight's tags); in shadow mode,
                   the ledger's add counts beside the rulings'. Anything to look
                   at goes in the run record's "ledger" block and, under the
                   workflow, ledger_flags=true (the ledger issue). A flag never
                   stops the run: the hub still builds.
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

--scheduled (the cron fires every 30 minutes through the early morning): exit
0 and do nothing unless the guard admits the firing: the league clock is in
[00:00, 06:00) and tonight's run hasn't happened (output/nightly_last.json,
written by record_night after every nightly-mode run; a failed night is
retried once). GitHub delays and drops scheduled firings (11-05: the first
scheduled night never fired), so one late or lost firing only delays the night.
With --pretip, --scheduled admits only [first tip - 45 min, first tip) on a
window day instead. Both decisions are scripts/run_guard.py's (standard
library only; the workflow's guard job runs the same functions).

STEP 1c-ii (HANDOFF_STEP1C2):
  - a scheduled nightly run first prices the latest closed week's closing line
    when it is due (closing_line.due): a week with no pre-tip tag record is
    recorded once as "no closing line" (closing_line.record_none) and the
    night goes on; any other refusal stops the run (exit 1);
  - the engine step compares HEAD with $ENGINE_COMMIT when it is set (the
    runner sets it from the private repo's ENGINE_COMMIT; design invariant 3);
  - --ignore-clock (only with --scheduled, nightly mode): the workflow's
    force input, workflow_dispatch only. It skips the night's guard, nothing else;
  - --no-closing-line --week N --reason TEXT: Nick records by hand that week N
    has no closing line, when its refusal is permanent.
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
    "nightly": ("engine", "logs", "sync", "settings", "schedule", "tags", "ledger", "line", "title_odds",
                "actuals", "hub"),
    "pretip": ("engine", "window", "logs", "sync", "settings", "tags", "ledger", "line", "title_odds",
               "hub"),
    "closing": ("engine", "window", "sync", "closing"),
}


class StepRefused(RuntimeError):
    """A step refused; the run stops here."""


def run_guard():
    """scripts/run_guard.py, the one definition of both scheduled guards."""
    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_guard as rg
    return rg


def scheduled_guard_decision(now_utc: datetime, base_path=".") -> tuple:
    """The nightly guard (scripts/run_guard.py): (admitted, why), reading the
    night's marker from this tree (the overlaid state, in the workflow)."""
    from .league_clock import league_tz
    rg = run_guard()
    return rg.nightly_decision(now_utc, league_tz(), rg.read_marker(base_path))


def scheduled_guard_admits(now_utc: datetime, base_path=".") -> bool:
    return scheduled_guard_decision(now_utc, base_path)[0]


def record_night(base_path, run_row: dict, ok: bool, now=None) -> dict:
    """After every nightly-mode run: output/nightly_last.json, the marker the
    guard reads (one run a night; a failed night retried once). A run on the
    same league day adds an attempt; ok sticks once any attempt succeeded."""
    from .data_loader import atomic_write_json
    from .league_clock import league_now
    rg = run_guard()
    now = now or league_now()
    day = now.date()
    path = Path(base_path) / rg.MARKER_REL
    prev = rg.read_marker(base_path)
    same = prev is not None and prev["league_day"] == day
    m = {"league_day": day.isoformat(),
         "attempts": (prev["attempts"] + 1) if same else 1,
         "ok": bool(ok or (same and prev["ok"])),
         "run_id": run_row.get("run_id"),
         "finished_at": run_row.get("finished_at")}
    atomic_write_json(path, m)
    return m


def pretip_guard_admits(now_utc: datetime, base_path=".") -> tuple:
    """(admitted, why): only in [first tip - 45 min, first tip) on a window day."""
    return run_guard().admits_pretip(now_utc, Path(base_path))


def engine_head(base: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(base), capture_output=True, text=True,
                       timeout=20)
    return r.stdout.strip() if r.returncode == 0 else ""


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
        self.exception = None

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
        pin = os.environ.get("ENGINE_COMMIT")
        if pin is not None:
            pin = pin.strip()
            if len(pin) != 40 or any(c not in "0123456789abcdef" for c in pin):
                raise StepRefused(f"ENGINE_COMMIT is set but is not a full commit SHA: {pin!r}")
            head = engine_head(self.base)
            if head != pin:
                raise StepRefused(f"the engine checkout is at {head or 'an unknown commit'}, not "
                                  f"ENGINE_COMMIT {pin}: a run never prices on code other than "
                                  "the pinned engine (design invariant 3)")
            self.ctx["engine_pinned"] = pin
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

    # -- 4b
    def step_schedule(self):
        from . import nba_schedule as ns
        from .data_loader import load_nba_schedule, load_schedule
        prior = schedule_attempt_today(self.base, self.today)
        if prior is not None:
            fetched = {"outcome": "skipped", "why": f"already tried today ({prior})"}
        else:
            import fetch_nba_schedule as fns
            # basketball-reference: the source the refetch's checks are built on (its
            # remarks mark the NBA Cup final); cdn.nba.com 403s everywhere (Sep 2026)
            fetched = ns.refetch(self.base, self.today, lambda: fns.fetch_trimmed(source="bbref"))
        # recorded before the load, which may raise: a retried night never refetches twice
        self.ctx["schedule"] = {"league_day": self.today.isoformat(), "refetch": fetched}
        path = ns.schedule_path(self.base)
        sched = load_nba_schedule(path, today=self.today)       # raises past the window
        block = ns.info(sched)
        flags = []
        if block:
            win = ns.window_config()
            warn = ns.warn_from(load_schedule(self.base / "config" / "SCHEDULE.json"), win)
            if warn is not None and self.today >= warn:
                flags.append(f"STANDINS {block['games']} stand-in games: {ns.note_text(block)} The "
                             f"window was {warn:%a %m-%d}: refetch the schedule (the nightly run "
                             f"refetches it; last refetch: {fetched['outcome']}"
                             + (f", {fetched['why']}" if fetched.get("why") else "") + ")")
        self.ctx["schedule"] = {
            "league_day": self.today.isoformat(),
            "file": path.relative_to(self.base).as_posix() if path.is_relative_to(self.base) else str(path),
            "refetch": fetched, "standins": block["games"] if block else 0,
            "per_team": block["per_team"] if block else {}, "flags": flags}
        bits = [f"refetch {fetched['outcome']}"
                + (f" from {fetched['source']}" if fetched.get("source") else "")
                + (f" ({fetched['games']} games, +{fetched['added']} -{fetched['removed']}, "
                   f"{len(fetched['moved'])} moved)" if fetched["outcome"] in ("updated", "unchanged") else "")
                + (f": {fetched['why']}" if fetched.get("why") else "")]
        bits += [f"moved {m}" for m in fetched.get("moved") or []]
        bits += [f"NBA Cup final left out: {c}" for c in fetched.get("cup_final") or []]
        bits.append(f"{block['games']} stand-in games ({ns.note_text(block)})" if block
                    else "no stand-ins: every team at its full schedule")
        if flags:
            bits.append(f"{len(flags)} FLAG(S): " + " | ".join(flags))
        return "; ".join(bits)

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

    # -- 5b
    def step_ledger(self):
        from . import move_ledger as ml
        from .data_loader import load_all_data
        mode = ml.mode()
        rows, states = ml.read_rows(self.base), ml.read_states(self.base)
        data = load_all_data(self.base, current_week=None)
        world = ml.World.from_base(self.base, now=self.now, data=data)
        new, rep = ml.verify(world, rows, states, run_id=self.run_id)
        ml.append_states(self.base, new)
        states = states + new
        flags = list(rep["flags"])
        bits = [f"{mode}: {len(rep['applied'])} applied, {len(rep['missing'])} missing, "
                f"{len(rep['conflict'])} conflict, {len(rep['pending'])} pending, "
                f"{len(rep['unmatched'])} outside a window"]
        wk = world.current_week()
        cl_block = None
        if self.mode == "nightly" and self.today == world.window_day(wk):
            path = ml.checklist_path(self.base, wk)
            if path.is_file():
                bits.append(f"week {wk} checklist already published")
            else:
                cl = ml.checklist(world, rows, states, wk, run_id=self.run_id)
                from .data_loader import atomic_write_json
                atomic_write_json(path, cl, indent=1)
                bits.append(f"week {wk} checklist: {len(cl['lines'])} line(s), "
                            f"{len(cl['stopped'])} team(s) stopped")
                flags += [f"CHECKLIST STOPPED {x['team']}: {x['reason']}" for x in cl["stopped"]]
                cl_block = {"week": wk, "lines": len(cl["lines"]), "stopped": cl["stopped"]}
        shadow = None
        if mode == "shadow":
            cmp_ = ml.shadow_compare(self.base, data.schedule, ml.entries(rows))
            shadow = {"differences": [d["text"] for d in cmp_["differences"]], "error": cmp_["error"]}
            if cmp_["error"]:
                flags.append(f"SHADOW the ledger's count could not be made: {cmp_['error']}")
            flags += [f"SHADOW {d}" for d in shadow["differences"]]
            bits.append(f"shadow: {len(cmp_['differences'])} difference(s) from the rulings"
                        + (" (error)" if cmp_["error"] else ""))
        self.ctx["ledger"] = {"mode": mode, "flags": flags, "applied": rep["applied"],
                              "missing": rep["missing"], "conflict": rep["conflict"],
                              "unmatched": rep["unmatched"], "pending": rep["pending"],
                              "checklist": cl_block, "shadow": shadow}
        if flags:
            bits.append(f"{len(flags)} FLAG(S): " + " | ".join(flags))
        return "; ".join(bits)

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
        from .roster_plan import take_notes
        take_notes()                                    # this run's notes only
        for name in STEPS[self.mode]:
            fn = (steps or {}).get(name) or getattr(self, f"step_{name}")
            t0 = time.perf_counter()
            try:
                detail = fn()
                # the roster plan's notes (task 18b: the stakes bootstrap) go on
                # the step that built the plan, in the run record and on screen
                from .roster_plan import take_notes
                notes = take_notes()
                if notes:
                    detail = "; ".join([str(detail or "")] + notes) if detail else "; ".join(notes)
                rows.append({"step": name, "outcome": "ok", "seconds": round(time.perf_counter() - t0, 2),
                             "detail": str(detail or "")})
                self.echo(f"  [{name}] ok ({rows[-1]['seconds']} s): {detail}")
            except Exception as e:                          # noqa: BLE001 -- the policy
                error = f"{type(e).__name__}: {e}"
                self.exception = e
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
        if self.ctx.get("ledger") is not None:
            row["ledger"] = self.ctx["ledger"]
        if self.ctx.get("schedule") is not None:
            row["schedule"] = self.ctx["schedule"]
        from .jsonl_log import append_rows
        append_rows(self.base / RUNS_FILE, [row])
        return row


def scheduled_closing(base_path=".", *, now: datetime = None, allow_dirty_engine: bool = False,
                      sims: int = None, title_sims: int = None, echo=print, data=None,
                      steps: dict = None) -> dict:
    """The scheduled nightly run's first job (HANDOFF_STEP1C2 s.3): price the
    latest closed week's closing line when it is due.

    Returns {"week": N or None, "outcome": "not due" | "ok" | "none recorded"
    | "refused", "row": the closing run's row or None}. "refused" stops the
    nightly run; "none recorded" (no pre-tip tag record: tag_records.NoPretipTags)
    writes output/closing_none_weekN.json once and lets the night go on."""
    from . import closing_line
    from .league_clock import league_now
    from .tag_records import NoPretipTags
    now = now or league_now()
    week = closing_line.due(base_path, now, data=data)
    if week is None:
        return {"week": None, "outcome": "not due", "row": None}
    echo(f"closing line due: week {week}")
    crun = Run(base_path, "closing", week=week, now=now, allow_dirty_engine=allow_dirty_engine,
               sims=sims, title_sims=title_sims, echo=echo)
    row = crun.execute(steps)
    if row["outcome"] != "refused":
        return {"week": week, "outcome": "ok", "row": row}
    if isinstance(crun.exception, NoPretipTags):
        p = closing_line.record_none(base_path, week, reason=str(crun.exception),
                                     run_id=crun.run_id, now=now)
        echo(f"week {week}: no closing line this week (no pre-tip tag record); recorded once "
             f"in {Path(p).relative_to(Path(base_path)).as_posix()}, never retried")
        return {"week": week, "outcome": "none recorded", "row": row}
    return {"week": week, "outcome": "refused", "row": row}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The nightly run, Monday's pre-tip run, or a week's "
                                             "closing line (steps 1c-i, 1c-ii).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--pretip", action="store_true", help="Monday's pre-tip run (before the first tip)")
    g.add_argument("--closing", action="store_true", help="the closing line for --week N")
    g.add_argument("--no-closing-line", action="store_true",
                   help="record that --week N has no closing line (with --reason), once")
    ap.add_argument("--week", type=int)
    ap.add_argument("--reason", help="with --no-closing-line: why (recorded)")
    ap.add_argument("--scheduled", action="store_true",
                    help="the cloud's cron: exit 0 doing nothing unless the guard admits this "
                         "moment (scripts/run_guard.py); a nightly run then prices a due "
                         "closing line first")
    ap.add_argument("--ignore-clock", action="store_true",
                    help="with --scheduled (nightly only): skip the night's guard -- the "
                         "workflow's force input, workflow_dispatch only")
    ap.add_argument("--allow-dirty-engine", action="store_true",
                    help="builder testing only: run on uncommitted code. The runner never passes it")
    ap.add_argument("--sims", type=int, help="line simulations (default: the line's default)")
    ap.add_argument("--title-sims", type=int, help="title-odds simulations (default: season_sims)")
    ap.add_argument("--base-path", default=".")
    a = ap.parse_args(argv)
    if a.week is not None and not (a.closing or a.no_closing_line):
        ap.error("--week goes with --closing or --no-closing-line")
    if a.ignore_clock and not a.scheduled:
        ap.error("--ignore-clock goes with --scheduled")
    if a.scheduled and (a.closing or a.no_closing_line):
        ap.error("--scheduled is for the nightly and pre-tip runs")
    if a.ignore_clock and a.pretip:
        ap.error("--ignore-clock is for the nightly run only: the pre-tip run has its window")
    from datetime import timezone
    if a.no_closing_line:
        return _no_closing_line(a)
    if a.scheduled:
        now_utc = datetime.now(timezone.utc)
        if a.pretip:
            ok, why = pretip_guard_admits(now_utc, a.base_path)
            if not ok:
                print(f"--pretip --scheduled: {why}; nothing to do.")
                return _ran(False)
        elif a.ignore_clock:
            print("--scheduled --ignore-clock: the night's guard is skipped (forced run).")
        else:
            ok, why = scheduled_guard_decision(now_utc, a.base_path)
            if not ok:
                print(f"--scheduled: {why}; nothing to do.")
                return _ran(False)
    mode = "pretip" if a.pretip else "closing" if a.closing else "nightly"
    if a.scheduled and mode == "nightly":
        c = scheduled_closing(a.base_path, allow_dirty_engine=a.allow_dirty_engine, sims=a.sims,
                              title_sims=a.title_sims)
        if c["outcome"] == "refused":
            row = c["row"]
            print(f"closing run for week {c['week']} REFUSED in {row['seconds']} s: {row['error']} "
                  f"(recorded in {RUNS_FILE.as_posix()}); the nightly run does not start")
            record_night(a.base_path, row, ok=False)
            return _ran(True, 1)
        if c["outcome"] != "not due":
            print(f"closing line, week {c['week']}: {c['outcome']}")
    run = Run(a.base_path, mode, week=a.week, allow_dirty_engine=a.allow_dirty_engine,
              sims=a.sims, title_sims=a.title_sims)
    print(f"{mode} run {run.run_id}")
    row = run.execute()
    if mode == "nightly":
        record_night(a.base_path, row, ok=row["exit"] == 0)
    print(f"{mode} run {row['outcome'].upper()} in {row['seconds']} s"
          + (f": {row['error']}" if row["error"] else "")
          + f" (recorded in {RUNS_FILE.as_posix()})")
    flags = (row.get("ledger") or {}).get("flags") or []
    if flags:
        print(f"MOVE LEDGER: {len(flags)} flag(s) to look at:")
        for f_ in flags:
            print(f"  {f_}")
        _ledger_flags(True)
    sflags = (row.get("schedule") or {}).get("flags") or []
    if sflags:
        print(f"NBA SCHEDULE: {len(sflags)} flag(s):")
        for f_ in sflags:
            print(f"  {f_}")
        _schedule_flags(True)
    return _ran(True, row["exit"]) if a.scheduled else row["exit"]


def _ledger_flags(on: bool) -> None:
    """Under the workflow: ledger_flags=true, for the step that opens (or
    comments on) the ledger issue (scripts/ledger_issue.py). A flag is not a
    failure: the run stays green and the hub publishes."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out and on:
        with open(out, "a", encoding="utf-8") as f:
            f.write("ledger_flags=true\n")


def _schedule_flags(on: bool) -> None:
    """Under the workflow: schedule_flags=true, for the step that opens (or
    comments on) the schedule issue (scripts/schedule_issue.py): stand-ins
    still there at the window of the week they fall in. Not a failure."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out and on:
        with open(out, "a", encoding="utf-8") as f:
            f.write("schedule_flags=true\n")


def schedule_attempt_today(base_path, today: date):
    """The run id of tonight's earlier nightly run that already tried the
    refetch (the run record), or None: the refetch runs at most once a league
    day, a retried night included."""
    from .jsonl_log import read_rows
    p = Path(base_path) / RUNS_FILE
    if not p.is_file():
        return None
    for r in reversed(read_rows(p)):
        sc = r.get("schedule") or {}
        if r.get("mode") != "nightly" or sc.get("league_day") != today.isoformat():
            continue
        out = (sc.get("refetch") or {}).get("outcome")
        if out not in (None, "skipped"):
            return r.get("run_id")
    return None


def _ran(ran: bool, code: int = 0) -> int:
    """Under the workflow ($GITHUB_OUTPUT set): ran=true|false for its later
    steps -- a scheduled run the guard declined built no hub, so nothing is
    published and no failure issue is closed. Returns `code`."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"ran={'true' if ran else 'false'}\n")
    return code


def _no_closing_line(a) -> int:
    """--no-closing-line --week N --reason TEXT (Nick, by hand)."""
    from . import closing_line, price_lock
    from .data_loader import load_all_data
    from .league_clock import league_now
    from .week_state import week_entry
    if a.week is None or not (a.reason or "").strip():
        print("REFUSED: --no-closing-line needs --week N and --reason")
        return 1
    now = league_now()
    try:
        data = load_all_data(a.base_path, current_week=None)
        monday = date.fromisoformat(str(week_entry(data, a.week)["start_date"])[:10])
        close = price_lock.window_close(monday, data.nba_schedule)
        if now < close:
            print(f"REFUSED: week {a.week}'s window closes {close.isoformat(timespec='minutes')}; "
                  "nothing to record before it")
            return 1
        p = closing_line.record_none(a.base_path, a.week, reason=a.reason,
                                     run_id=f"{now.isoformat(timespec='seconds')}-no-closing-line",
                                     now=now, by="nightly.py --no-closing-line (by hand)")
    except (closing_line.ClosingRefused, KeyError) as e:
        print(f"REFUSED: {e}")
        return 1
    print(f"recorded: week {a.week} has no closing line ({p})")
    return 0
