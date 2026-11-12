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
  7b advice       advice v2 (modules/advice_live): every manager's best move --
                   the Monday move before this week's window close, the chat
                   move after it -- with its backup, on the live rosters, the
                   ledger's pending moves, the tags and the stakes; written to
                   output/advice_latest.json and output/advice_history.jsonl.
                   Every run that prices runs it (nightly, pre-tip, refresh,
                   poll, afternoon), during the lock too: advice is not a price,
                   it plans future days. Not the facts-only refresh. A failure
                   is recorded (both outputs, the run's "advice" block, ADVICE
                   FAILED in the summary) and never stops the run
   8 actuals       player_actuals.update (the pre-tip run too, before its hub
                   step: a player added in the Monday window is backfilled here,
                   or the hub refuses with ActualsStale -- 11-09's 3:15 and 3:30
                   runs did). The closing run builds no hub and reads no actuals
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

STEP 3a (HANDOFF_STEP3A s.1), the refresh run:

    python scripts\\nightly.py --refresh --cause "injury update: Zion Williamson out, back 11-21"

  The nightly run's path without the log pull (design s.5): engine, banked,
  sync, settings, tags, ledger, line and title_odds (only when prices are not
  locked), actuals, hub. No guard on the clock: it runs whenever an entry
  lands; the workflow's concurrency group queues it behind a nightly or
  pre-tip run. --cause is required: one short line naming the trigger, built by
  the caller from its own inputs; it is recorded in the run's row (every mode's
  row carries one: "nightly", "Monday pre-tip"), and a priced line's win-% row
  carries it (decision 1).
  - banked: the price lock runs "from the first tip until the next 12:01 run's
    banking" (design s.4.1). price_lock.status covers the first tip to
    midnight; between midnight and the nightly run's log pull, last night's
    games are unbanked and nothing can be priced or built for the new day. So
    a refresh that finds a finished league day missing from the logs is
    DEFERRED: outcome "deferred", exit 0, nothing priced or built -- the
    entry is already committed, and the nightly run prices it.
  - line, title_odds: during the lock (price_lock.status) nothing is priced:
    the run's outcome is "locked" and the hub's lock note counts it as a
    change waiting (hub_state.lock_note).
  - hub: a refresh (and a pre-tip run) shows last night's matchup paragraph
    byte for byte (output/night_paragraph.json, written only by the nightly
    run's hub step; decisions 2-3).
  The nightly run gains step 5c, returns (decision 13b): an injury entry whose
  return date has passed is removed when Yahoo shows him with no O/OFS tag
  (recorded in output/override_history.jsonl and in the run's "returns"
  block), and gets one issue (scripts/returns_issue.py, label return-passed)
  when he is still tagged O/OFS or his tag is unknown.

TASK 49 (HANDOFF_TRADE_BLOCK_2026-11-11), the trade block:
  - the nightly run's step 3a, trade_block, right after the sync: a listed
    player no longer on that manager's roster (traded, dropped) is taken off,
    and from the day after the trade deadline the whole block is cleared,
    once (modules/trade_block.upkeep; history rows by "nightly"; the run
    record's "trade_block" block). Nothing is re-priced.
  - the FACTS-ONLY refresh, after a trade-block entry (it changes no price):

        python scripts\\nightly.py --refresh --facts-only --cause "trade block: Garrett selling"

    the refresh's steps without line and title_odds (STEPS["refresh_facts"]),
    so no win-% point and no title-odds row; the run's row says
    "facts_only": true. Its step line_engine defers the run (exit 0, nothing
    built) when this week's line on disk was priced by another engine (just
    after set-engine): the hub refuses a line priced by another engine, and a
    facts-only run must not price one. The next run that prices rebuilds it.

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
MODES = ("nightly", "pretip", "closing", "refresh", "poll", "afternoon")
NIGHT_CAUSE = {"nightly": "nightly", "pretip": "Monday pre-tip"}
# step 3b: the runs that are a refresh (no log pull, no clock guard of their
# own here, the lock judged before pricing, last night's paragraph reused)
REFRESH_MODES = ("refresh", "poll", "afternoon")
# step 3b: the runs that READ the NBA's injury report (the runs before tip that
# price); every other pricing run reuses the latest stored read
REPORT_READERS = ("nightly", "pretip", "afternoon")
STEP_TIMEOUT_S = 900

# Advice v2 (V2 s.5): every mode that prices runs "advice", right after
# title_odds (the stakes it reads) and before actuals and the hub (which shows
# it when advice.hub is on); not refresh_facts, not closing.
STEPS = {
    "nightly": ("engine", "logs", "sync", "trade_block", "settings", "schedule", "tags", "nba_report",
                "returns", "ledger", "line", "title_odds", "advice", "actuals", "hub", "nudges"),
    # Step 3a: the nightly path without the log pull; actuals stays right
    # before the hub, as in every mode that builds one (F1)
    "refresh": ("engine", "banked", "sync", "settings", "tags", "nba_report", "ledger", "line",
                "title_odds", "advice", "actuals", "hub"),
    # task 49: a refresh after a trade-block entry, which changes no price: the
    # refresh without line and title_odds (no win-% point, no title-odds row);
    # mode "refresh" with facts_only (--refresh --facts-only)
    "refresh_facts": ("engine", "banked", "sync", "line_engine", "settings", "tags", "nba_report",
                      "ledger", "actuals", "hub"),
    "pretip": ("engine", "window", "logs", "sync", "settings", "tags", "nba_report", "ledger", "line",
               "title_odds", "advice", "actuals", "hub"),
    # Step 3b: a Monday poll that found a new Yahoo transaction (the guard job's
    # scripts/monday_poll.py): the refresh, its cause named from what the sync logged
    "poll": ("engine", "banked", "sync", "moves", "settings", "tags", "nba_report", "ledger", "line",
             "title_odds", "advice", "actuals", "hub"),
    # Step 3b: the afternoon tag check, about an hour before the day's first tip
    "afternoon": ("engine", "banked", "sync", "settings", "tags", "nba_report", "changes", "ledger",
                  "line", "title_odds", "advice", "actuals", "hub"),
    "closing": ("engine", "window", "sync", "closing"),
}


class StepRefused(RuntimeError):
    """A step refused; the run stops here."""


class NothingNew(RuntimeError):
    """A poll whose sync logged no new transaction (another run logged it
    first): nothing to refresh. Not a failure: the run stops, exit 0."""


class RunDeferred(RuntimeError):
    """A refresh before the nightly run has banked last night's games: nothing
    to price or build yet. Not a failure: the run stops, exit 0."""


def run_guard():
    """scripts/run_guard.py, the one definition of both scheduled guards."""
    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_guard as rg
    return rg


def scheduled_guard_decision(now_utc: datetime, base_path=".") -> tuple:
    """The nightly guard (scripts/run_guard.py): (admitted, why), reading the
    night's marker from this tree (the overlaid state, in the workflow), with
    the same window as the workflow's guard (run_guard.night_cutoff: to the
    day's first tip less an hour, at most noon, at least 6:00; 11-07)."""
    from .league_clock import league_tz
    rg = run_guard()
    tz = league_tz()
    cut, why = rg.night_cutoff(rg.ROOT, rg._aware(now_utc).astimezone(tz).date(), tz, base_path)
    return rg.nightly_decision(now_utc, tz, rg.read_marker(base_path), cut, why)


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
                 echo=print, cause: str = None, facts_only: bool = False):
        from .league_clock import league_now
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if facts_only and mode != "refresh":
            raise ValueError("facts_only is a refresh's switch (--refresh --facts-only)")
        self.facts_only = bool(facts_only)
        if mode == "refresh" and not str(cause or "").strip():
            raise ValueError("a refresh run needs its cause (--cause): what triggered it, in one line")
        if mode in ("poll", "afternoon") and cause is not None:
            raise ValueError(f"a {mode} run names its own cause from its inputs; none is passed in")
        # poll and afternoon: set by their moves / changes step, from their own inputs
        self.cause = (str(cause).strip() if mode == "refresh" else NIGHT_CAUSE.get(mode))
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

    # -- refresh: is last night banked?
    def step_banked(self):
        import refresh_service as rs
        from .data_loader import load_all_data
        data = load_all_data(self.base, current_week=None)
        todo = rs.missing_days(data, self.today)
        if todo:
            raise RunDeferred(f"{', '.join(d.isoformat() for d in todo)} not banked yet: the 12:01 AM "
                              "run pulls the logs and prices this change; nothing priced or built now")
        return "every finished league day is banked"

    def steps(self) -> tuple:
        """This run's steps: STEPS[mode], or the facts-only refresh's."""
        return STEPS["refresh_facts" if self.facts_only else self.mode]

    # -- 3a (nightly; task 49): the trade block's upkeep
    def step_trade_block(self):
        from . import trade_block as tb
        out = tb.upkeep(self.base, tb.rosters_now(self.base), self.today, self.now)
        self.ctx["trade_block"] = {"cleared": out["cleared"], "removed": out["removed"]}
        return tb.upkeep_text(out)

    # -- facts-only refresh (task 49): the hub builds only on a line of this engine
    def step_line_engine(self):
        from . import live_lines_page as llp
        from .hub_state import load_line
        line = load_line(self.base, self.week)
        chk = llp.engine_check(line, self.base)
        if not chk["ok"] and not self.allow_dirty:
            if chk["payload"] and not str(chk["payload"]).endswith(("-dirty", "-unknown")):
                # 11-11: the hub shows the previous clean engine's line with a
                # note (hub_state.build previous_engine_ok), so the entry still
                # reaches the hub now
                return (f"week {self.week}'s line is the previous engine's ({chk['payload']}); the hub "
                        "shows it with a note until the next run that prices")
            raise RunDeferred(f"week {self.week}'s line on disk was priced by engine {chk['payload']}, the "
                              f"engine is {chk['current']}: a facts-only refresh prices nothing, so the "
                              "hub is rebuilt (with this change) by the next run that prices")
        return f"week {self.week}'s line is engine {chk['current']}'s"

    # -- 5c (nightly): passed return dates (decision 13b)
    def step_returns(self):
        """Every injury entry whose return date has passed (before today, the
        league clock): no O/OFS tag in Yahoo now -> removed (overrides.py's
        remove, recorded in the history and in this run's "returns" block);
        still tagged O/OFS, or not in Yahoo's lists at all (his tag unknown)
        -> an issue for Nick, one per player while it is open
        (scripts/returns_issue.py dedupes by title)."""
        import overrides as ov
        from . import move_ledger as ml
        from .absence import parse_return_date
        from .data_loader import PlayerIndex, load_all_data
        tags = self.ctx["tags"]
        blob = ov._read(self.base, ov.OVERRIDES)
        data = load_all_data(self.base, current_week=None)
        rostered = PlayerIndex({n: m for m, v in data.get_current_rosters().items() for n in v})
        listed = PlayerIndex({str(n): True for n in data.playerlist["player_name"].dropna()})
        fa = getattr(tags, "free_agents", None)
        removed, issues = [], []
        for e in list(blob.get("players") or []):
            name = str(e.get("player_name"))
            rd = parse_return_date(e.get("return_date"), name)
            if rd is None or rd >= self.today:
                continue
            if rostered.canonical(name) is not None:
                hit = tags.canonical(name)
                tag = tags[hit] if hit is not None else ""
            elif listed.canonical(name) is not None and fa is not None:
                hit = fa.canonical(name)
                tag = fa[hit] if hit is not None else ""
            else:
                tag = None                                   # not in Yahoo's lists: unknown
            tag = None if tag is None else str(tag or "").upper()
            md = f"{rd.month:02d}-{rd.day:02d}"
            if tag is not None and not ml.tag_il_eligible(tag):
                ch = ov.remove_change(self.base, name, now=self.now, by="nightly (13b)")
                ov.apply(self.base, ch)
                removed.append({"player": ch["player"], "return_date": rd.isoformat(),
                                "tag": tag or "none"})
                continue
            if tag is None:
                title = f"{name}'s return date {md} has passed; his Yahoo tag is unknown"
            else:
                title = f"{name}'s return date {md} has passed; he is still tagged {tag}"
            issues.append({"player": name, "return_date": rd.isoformat(), "tag": tag, "title": title,
                           "body": f"{title}. Push the date (`Injury: {name} back MM/DD`) or remove him "
                                   f"(`Injury remove: {name}`). This issue closes by itself the night "
                                   "after it is answered."})
        self.ctx["returns"] = {"removed": removed, "issues": issues}
        bits = [f"removed {r['player']} (back {r['return_date'][5:]}, tag {r['tag']})" for r in removed]
        bits += [f"issue: {i['title']}" for i in issues]
        return "; ".join(bits) or "no passed return dates"

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
        self.ctx["tags"] = tags
        n = sum(1 for t in dict(tags).values() if str(t).upper() != "HEALTHY")
        if "nba_report" in self.steps():
            # step 3b: recorded by the nba_report step, with the report's Outs
            # (Tags.nba_outs), so the closing line reads what the pre-tip line priced
            done.append(f"{n} rostered tag(s) fetched")
            return "; ".join(done)
        row = tag_records.append(self.base, tags, run_id=self.run_id, mode=self.mode,
                                 week=self.week, now=self.now)
        done.append(f"{n} rostered tag(s) recorded at {row['taken_at']}")
        return "; ".join(done)

    # -- 5a (step 3b): the NBA's official injury report
    def step_nba_report(self):
        """Read the report (nightly, afternoon, pre-tip: REPORT_READERS) or
        reuse the latest stored read (refresh, poll); apply tonight's Outs to
        the tags (Tags.nba_outs, nba_injury_report.assess); record the tags.
        The report itself never stops the run: unavailable, unreadable or a
        failure here is named, nothing is applied, and Yahoo's tags stand. The
        tag record is written either way (tags are facts)."""
        from . import nba_injury_report as nr
        from . import tag_records
        tags = self.ctx["tags"]
        info = {"read": None, "outcome": None, "filed_at": None, "applied": {}, "flags": [],
                "loud": [], "unresolved": 0, "covered": [], "summary": None}
        try:
            row = None
            if self.mode in REPORT_READERS:
                row = nr.read_and_store(self.base, self.now, run_id=self.run_id, mode=self.mode)
                info["read"] = "read"
            else:
                info["read"] = "reused"
            lat = nr.latest(self.base)
            attempt, report = lat["attempt"], lat["report"]
            info["outcome"] = attempt.get("outcome") if attempt else "none"
            if attempt is None or attempt.get("outcome") != "ok":
                tags.nba_outs = {}
                info["summary"] = (nr.summary(attempt, {}) if attempt else
                                   "NBA report: none read yet; Yahoo's tags stand")
            else:
                assessed = self._assess_report(nr, report, tags)
                tags.nba_outs = dict(assessed["applied"])
                info.update(filed_at=report.get("filed_at"), applied=dict(assessed["applied"]),
                            flags=assessed["flags"], loud=assessed["loud"],
                            unresolved=len(assessed["unresolved"]), covered=assessed["covered"],
                            stale=assessed["stale"], summary=nr.summary(attempt, assessed))
        except Exception as e:                          # noqa: BLE001 -- never stops a run (s.4)
            tags.nba_outs = {}
            info.update(outcome="error", summary=f"NBA report unavailable ({type(e).__name__}: {e}); "
                                                 "Yahoo's tags stand")
        self.ctx["nba_report"] = info
        rec = tag_records.append(self.base, tags, run_id=self.run_id, mode=self.mode,
                                 week=self.week, now=self.now)
        return f"{info['summary']}; tags recorded at {rec['taken_at']}"

    def _assess_report(self, nr, report, tags) -> dict:
        from .data_loader import PlayerIndex, load_all_data
        from .hub_state import override_out_on
        from .week_state import week_entry, week_for_date
        data = load_all_data(self.base, current_week=None)
        rosters = {m: list(v) for m, v in data.get_current_rosters().items()}
        wk = week_for_date(data, self.today)
        wstart = date.fromisoformat(str(week_entry(data, wk)["start_date"])[:10])
        over = PlayerIndex({e["player_name"]: e for e in (data.injury_overrides or {}).get("players", [])})

        def out_today(name):
            e = over.get(name)
            return e is not None and override_out_on(e, self.today, wk, wstart)
        known = nr.known_players(self.base, rosters, data.playerlist)
        return nr.assess(report, tags, rosters, out_today, self.today, known, now=self.now)

    # -- poll (step 3b): the transactions the sync just logged name the cause
    def step_moves(self):
        from . import transaction_log as tlog
        keys = list((self.ctx.get("sync") or {}).get("log", {}).get("new_keys") or [])
        if not keys:
            raise NothingNew("the sync logged no new transaction (another run logged it first): "
                             "nothing to refresh")
        rows = {t["key"]: t for t in tlog.transactions(self.base)}
        missing = [k for k in keys if k not in rows]
        if missing:
            raise StepRefused(f"the transaction log lacks {missing}, which the sync reported appending")
        self.cause = moves_cause([rows[k] for k in keys])
        return self.cause

    # -- afternoon (step 3b): what changed since the line, from the inputs
    def step_changes(self):
        self.cause = afternoon_cause(self.base, self.week, self.ctx["tags"],
                                     (self.ctx.get("nba_report") or {}))
        return self.cause

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
        if self.mode in REFRESH_MODES:
            # the lock is judged here, before anything prices: a refresh during
            # the lock prices nothing, even when the line's inputs are unchanged
            # (title odds would otherwise re-price mid-game)
            from . import price_lock
            from .data_loader import load_all_data
            st = price_lock.status(self.now, load_all_data(self.base, current_week=None).nba_schedule)
            if st["locked"]:
                self.ctx["locked"] = True
                return (f"locked: games are on (first tip {st['first_tip']}); nothing priced -- "
                        f"{self.cause} is priced after tonight's games")
        out = rs.run(self.base, as_of=self.today, week=self.week,
                     sims=self.sims or DEFAULT_NUM_SIMULATIONS, trigger=self.mode,
                     pull_logs=False, statuses=self.ctx["tags"], now=self.now, cause=self.cause)
        self.ctx["line"] = out
        if out["exit"] != 0:
            raise StepRefused(f"refresh_service: {out.get('error')}")
        self.ctx["locked"] = out["outcome"] == "locked"
        return out["outcome"] + (f" ({out.get('why_priced')})" if out.get("why_priced") else "")

    # -- 7
    def _afternoon_unchanged(self) -> bool:
        """Step 3b: an afternoon check whose line came back unchanged (nothing
        moved since the last line) writes nothing more: no title odds, no hub."""
        return self.mode == "afternoon" and (self.ctx.get("line") or {}).get("outcome") == "unchanged"

    def step_title_odds(self):
        from . import title_odds_run as tor
        from .data_loader import SEASON_SIMS, load_all_data
        if self._afternoon_unchanged():
            self.ctx["unchanged"] = True
            return "skipped: nothing changed since the last line"
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

    # -- 7b (advice v2)
    def step_advice(self):
        """Advice for every manager (modules/advice_live.run_step): built,
        advised and written; an error is recorded there and the run goes on.
        An afternoon check that changed nothing writes nothing more."""
        from . import advice_live as al
        if self._afternoon_unchanged():
            return "skipped: nothing changed since the last line"
        out = al.run_step(self.base, self.now, run_id=self.run_id, mode=self.mode, cause=self.cause,
                          echo=self.echo)
        self.ctx["advice"] = out["block"]
        self.ctx["advice_lines"] = out["lines"]
        return out["detail"]

    # -- 8
    def step_actuals(self):
        from . import player_actuals as pa
        if self._afternoon_unchanged():
            return "skipped: nothing changed since the last line"
        r = pa.update(self.base, today=self.today)
        return (f"through {r['through']}: {len(r['days_fetched'])} day(s), {r['calls']} call(s)"
                + (f"; backfilled {', '.join(r['backfilled'])}" if r["backfilled"] else ""))

    # -- 9
    def step_hub(self):
        import build_hub
        from . import hub_matchups, hub_state
        if self._afternoon_unchanged():
            return "skipped: nothing changed since the last line (nothing published)"
        # decisions 2-3: only the nightly run builds the matchup paragraph; a
        # refresh or a pre-tip run shows last night's, byte for byte
        night_out = {}
        payload = hub_state.build(self.base, now=self.now, allow_engine_mismatch=self.allow_dirty,
                                  previous_engine_ok=self.mode in REFRESH_MODES,
                                  echo=lambda *a: None,
                                  night="build" if self.mode == "nightly" else "reuse",
                                  night_out=night_out, nba_report=self.ctx.get("nba_report"))
        hub_state.write(self.base, payload)
        if self.mode == "nightly" and night_out.get("night") is not None:
            hub_matchups.write_night(self.base, night_out["night"], run_id=self.run_id)
        enc = bool(os.environ.get("HUB_PASSPHRASE"))
        rc = build_hub.main(["--base-path", str(self.base)] + ([] if enc else ["--preview-only"]))
        if rc != 0:
            raise StepRefused(f"build_hub exited {rc}")
        return ("encrypted publish directory" if enc else "preview only (no HUB_PASSPHRASE)") \
            + (" -- ENGINE MISMATCH banner (dirty engine)" if payload["header"]["engine_mismatch"] else "")

    # -- (nightly, last; step 3b s.3): the O-past-3-games nudge
    def step_nudges(self):
        """Every player tagged O for more than live_refresh.o_nudge.more_than_games
        of his team's games with no injury entry -- rostered, and the free agents
        the stash could show -- gets one issue (scripts/nudge_issue.py, label
        o-no-entry). Listed in the run's "nudges" block; never guessed."""
        from . import o_nudge
        out = o_nudge.find(self.base, self.ctx["tags"], self.today)
        self.ctx["nudges"] = out
        bits = [i["title"] for i in out]
        return "; ".join(bits) or "no player O past the cap without an entry"

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
        for name in self.steps():
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
            except NothingNew as e:
                rows.append({"step": name, "outcome": "nothing new",
                             "seconds": round(time.perf_counter() - t0, 2), "detail": str(e)})
                self.echo(f"  [{name}] NOTHING NEW: {e}")
                outcome = "nothing new"
                break
            except RunDeferred as e:
                rows.append({"step": name, "outcome": "deferred",
                             "seconds": round(time.perf_counter() - t0, 2), "detail": str(e)})
                self.echo(f"  [{name}] DEFERRED: {e}")
                outcome = "deferred"
                break
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
        if outcome == "ok" and self.ctx.get("unchanged"):
            outcome = "unchanged"
        eng = self.ctx.get("engine") or {}
        row = {"run_id": self.run_id, "mode": self.mode, "week": self.week,
               "started_at": started.isoformat(timespec="seconds"),
               "finished_at": league_now().isoformat(timespec="seconds"),
               "seconds": round(sum(r["seconds"] for r in rows), 2),
               "engine": {"commit": eng.get("commit"), "dirty": eng.get("dirty")},
               "allow_dirty_engine": self.allow_dirty, "steps": rows, "outcome": outcome,
               "exit": 1 if outcome == "refused" else 0, "error": error}
        if self.cause is not None:
            row["cause"] = self.cause
        if self.facts_only:
            row["facts_only"] = True
        if self.ctx.get("trade_block") is not None:
            row["trade_block"] = self.ctx["trade_block"]
        if self.ctx.get("returns") is not None:
            row["returns"] = self.ctx["returns"]
        if self.ctx.get("ledger") is not None:
            row["ledger"] = self.ctx["ledger"]
        if self.ctx.get("schedule") is not None:
            row["schedule"] = self.ctx["schedule"]
        if self.ctx.get("nba_report") is not None:
            row["nba_report"] = self.ctx["nba_report"]
        if self.ctx.get("nudges") is not None:
            row["nudges"] = self.ctx["nudges"]
        if self.ctx.get("advice") is not None:
            row["advice"] = self.ctx["advice"]
        if self.mode == "nightly":
            row["afternoon"] = afternoon_plan_today(self.base, self.today)
        from .jsonl_log import append_rows
        append_rows(self.base / RUNS_FILE, [row])
        return row


def moves_cause(rows: list) -> str:
    """A poll's cause, from the transactions themselves (transaction_log rows):
    "Monday move: Benton added PJ Washington, dropped Paul George";
    several: "Monday moves: ...; ..."."""
    bits = []
    for t in rows:
        if t["type"] == "trade":
            sides = {}
            for p in t["players"]:
                fm, to = (p.get("from") or {}).get("manager"), (p.get("to") or {}).get("manager")
                sides.setdefault((fm, to), []).append(p["name"])
            bits.append("trade: " + "; ".join(f"{fm} sends {', '.join(v)} to {to}"
                                               for (fm, to), v in sorted(sides.items(), key=str)))
            continue
        by = {}
        for p in t["players"]:
            if p["action"] == "add":
                m = (p.get("to") or {}).get("manager")
                by.setdefault(m, []).append(f"added {p['name']}")
            elif p["action"] == "drop":
                m = (p.get("from") or {}).get("manager")
                by.setdefault(m, []).append(f"dropped {p['name']}")
        for m, acts in by.items():
            if not m:
                raise StepRefused(f"transaction {t['key']} names no manager for {acts}")
            bits.append(f"{m} {', '.join(acts)}")
    if not bits:
        raise StepRefused("the new transactions name no player: no cause can be built")
    return ("Monday move: " if len(bits) == 1 else "Monday moves: ") + "; ".join(bits)


def _tag_word(tag) -> str:
    """The chain tag (Q, D, O) or "healthy": the line's state file keeps chain
    tags only, so only they are compared (an OFS, SUSP or NA change still moves
    the line's cache key, and its win-% point says "also moved: tags")."""
    from . import absence
    t = absence.chain_tag(tag) if tag is not None else None
    return t or "healthy"


def afternoon_cause(base, week: int, tags, report: dict) -> str:
    """The afternoon check's cause from its own inputs: each rostered tag that
    differs from the tags the current line priced (its state file), and each
    NBA-report Out it applies that the line did not (its "nba_outs"), and back.
    "tag update: Jalen Johnson Q->O; NBA report: Zion Williamson out tonight".
    Nothing changed: "afternoon check: no change" (the line's cache then
    says unchanged, and nothing is written)."""
    from .data_loader import PlayerIndex
    base = Path(base)
    sp = base / "output" / f"live_lines_week{week}.state.json"
    lp = base / "output" / f"live_lines_week{week}.json"
    if not sp.is_file() or not lp.is_file():
        return f"afternoon check: no week {week} line yet"
    priced = PlayerIndex({n: (v or {}).get("tag") for n, v in
                          (json.loads(sp.read_text(encoding="utf-8")).get("tags") or {}).items()})
    now = PlayerIndex({n: t for n, t in dict(tags).items()})
    changed = []
    for n in sorted(set(dict.keys(now)) | set(dict.keys(priced))):
        a, b = _tag_word(priced.get(n)), _tag_word(now.get(n))
        if a != b:
            changed.append(f"{n} {a}\u2192{b}")
    line_outs = json.loads(lp.read_text(encoding="utf-8")).get("nba_outs") or {}
    applied = (report or {}).get("applied") or {}
    bits = []
    if changed:
        bits.append("tag update: " + ", ".join(changed))
    new = sorted(set(applied) - set(line_outs))
    gone = sorted(set(line_outs) - set(applied))
    if new:
        bits.append("NBA report: " + ", ".join(f"{n} out tonight" for n in new))
    if gone:
        bits.append("NBA report: " + ", ".join(f"{n} no longer out" for n in gone))
    return "; ".join(bits) or "afternoon check: no change"


def afternoon_plan_today(base, today: date) -> dict:
    """The nightly run's note on today's afternoon check (run_guard.afternoon_plan):
    the firing that runs, or SKIPPED and why. Never stops the night."""
    rg = run_guard()
    try:
        from .league_clock import league_tz
        return rg.afternoon_plan(rg.ROOT, today, league_tz(), base)
    except Exception as e:                              # noqa: BLE001 -- a note, not a gate
        return {"day": today.isoformat(), "firing": None, "why": f"unknown ({type(e).__name__}: {e})"}


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
    g.add_argument("--refresh", action="store_true",
                   help="Step 3a: the nightly path without the log pull, after an entry (needs --cause)")
    g.add_argument("--poll", action="store_true",
                   help="Step 3b: a Monday poll found a new Yahoo transaction: sync, then refresh "
                        "with the transactions as the cause")
    g.add_argument("--afternoon", action="store_true",
                   help="Step 3b: the afternoon tag check (tags, the NBA report, a refresh)")
    ap.add_argument("--cause", help="with --refresh: what triggered it, one short line")
    ap.add_argument("--facts-only", action="store_true",
                    help="with --refresh (task 49): rebuild the hub's facts and price nothing "
                         "(a trade-block entry)")
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
    if a.refresh and not str(a.cause or "").strip():
        ap.error("--refresh needs --cause: what triggered it, in one short line")
    if a.cause is not None and not a.refresh:
        ap.error("--cause goes with --refresh")
    if a.facts_only and not a.refresh:
        ap.error("--facts-only goes with --refresh")
    if a.refresh and a.scheduled:
        ap.error("--refresh has no clock guard: it runs whenever an entry lands")
    if (a.poll or a.afternoon) and a.scheduled:
        ap.error("--poll and --afternoon are admitted by the workflow's guard job, not here")
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
    mode = ("pretip" if a.pretip else "closing" if a.closing else "refresh" if a.refresh
            else "poll" if a.poll else "afternoon" if a.afternoon else "nightly")
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
              sims=a.sims, title_sims=a.title_sims, cause=a.cause, facts_only=a.facts_only)
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
    tb_ = row.get("trade_block") or {}
    if tb_.get("cleared"):
        print("TRADE BLOCK: the trade deadline has passed; every team's block cleared")
    for r in tb_.get("removed") or []:
        print(f"TRADE BLOCK: {r['player']} taken off {r['manager']}'s list (no longer on his roster)")
    if row.get("returns") is not None:
        ret = row["returns"]
        for r in ret["removed"]:
            print(f"RETURN PASSED: removed {r['player']} (back {r['return_date']}, tag {r['tag']})")
        for i in ret["issues"]:
            print(f"RETURN PASSED: {i['title']}")
        _gh_flag("returns")
    rep_ = row.get("nba_report") or {}
    if rep_.get("summary"):
        print(rep_["summary"])
    if rep_.get("flags") or rep_.get("loud"):
        _gh_flag("nba_flags")
    for n_ in row.get("nudges") or []:
        print(f"NUDGE: {n_['title']}")
    if row.get("nudges") is not None:
        _gh_flag("nudges")
    if row.get("afternoon") is not None:
        print(f"AFTERNOON CHECK TODAY: {row['afternoon']['why']}")
    for line in run.ctx.get("advice_lines") or []:                # advice v2: one line per manager
        print(line)
    if mode in REFRESH_MODES:
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"ran={'false' if row['outcome'] in ('deferred', 'nothing new', 'unchanged') else 'true'}\n")
        return row["exit"]
    sflags = (row.get("schedule") or {}).get("flags") or []
    if sflags:
        print(f"NBA SCHEDULE: {len(sflags)} flag(s):")
        for f_ in sflags:
            print(f"  {f_}")
        _schedule_flags(True)
    return _ran(True, row["exit"]) if a.scheduled else row["exit"]


def _gh_flag(name: str) -> None:
    """Under the workflow: <name>=true for a later step."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"{name}=true\n")


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
