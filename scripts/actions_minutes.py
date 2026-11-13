#!/usr/bin/env python3
r"""
actions_minutes.py -- the Actions minutes GitHub BILLS, recomputed: the
private state repo's workflows only (step 3b; recounted in 40b, 11-13).
Standard library only.

    python scripts/actions_minutes.py                    the month's estimate, from today
    python scripts/actions_minutes.py --from 2026-11-16 --json
    python scripts/actions_minutes.py --usage-csv _to_delete\actions\usage.csv

WHAT COUNTS (40b): the free plan's 2,000 minutes a month are charged only for
PRIVATE repos. The engine (its ci.yml, Pages) and the hub (Pages) are public,
so their minutes are free; GitHub's detailed usage report for 11-01..11-13
showed 964 gross minutes of which 801 were public. Only the state repo's
workflows (config/STATE_MANIFEST.json private_repo) count, and only they are
modelled here. The public repos come from the run workflow's ENGINE_REPO and
HUB_REPO; a repo in a usage report that is none of the three RAISES.

THE MODEL, per job, because GitHub bills each job rounded UP to a whole
minute (a guard job that exits in seconds bills one):
  - every cron-job.org firing (deploy/state-repo/cron-job-org.json, the plan
    of record) starts a guard job: GUARD_MIN, or 2 when a Monday poll
    inside it runs long (worst);
  - every admitted run is a run job: ceil((SETUP + its run's seconds) / 60).
    Its seconds by mode (RUN_SECONDS, measured from output/nightly_runs.jsonl
    11-11..11-13), plus ADVICE_SECONDS for every mode that prices (the advice
    step, since 11-12), plus the free agents' actuals pass (40b, ~1 s a
    night: a handful of calls, inside RUN_SECONDS' margin);
  - which runs are admitted comes from scripts/run_guard.py's own functions
    over the season: one nightly a night, the afternoon run the guard picks
    on non-window game days, the Monday pre-tip runs and polls; a poll that
    finds a move starts a refresh (POLL_REFRESHES_PER_MONDAY);
  - phone and desk entries (entry.yml, overrides-push.yml) are one refresh
    run each, ENTRIES_PER_WEEK.
worst = every run twice as slow, the long polls, the busy entry weeks.
--usage-csv calibrates it: the report's state-repo minutes by workflow and
UTC day beside this model's for the same days (tests/test_40b_fa_actuals.py
pins the reader and the model's pieces).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_guard as rg                                   # noqa: E402

WEEKS_PER_MONTH = 4.35
DAYS_PER_MONTH = 30.4
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FREE_MINUTES = 2000

# (typical, worst). Calibrated on the 11-01..11-13 usage report (40b): a
# nightly of 100-115 s billed 3 minutes, an afternoon run of 57-62 s 2, so the
# job's own setup (checkouts, the venv restore, the overlay, the commit and the
# hub push) is 20-58 s.
SETUP_SECONDS = (45, 90)
GUARD_MIN = (1, 1)
POLL_GUARD_MIN = (1, 2)                  # a guard job that also polled Yahoo (Monday)
RUN_SECONDS = {                          # the python run, without advice (output/nightly_runs.jsonl)
    "nightly": (95, 190),                # 11-12/13: 100-115 s with advice ~10 s
    "pretip": (45, 90),                  # 11-09: 33-52 s
    "poll": (50, 100),
    "afternoon": (50, 100),              # 11-11/12: 57-62 s with advice ~9 s
    "afternoon_unchanged": (30, 60),     # the line came back unchanged: no title odds, no hub
    "refresh": (55, 110),                # 11-11: 58-62 s
}
ADVICE_SECONDS = (11, 22)                # the advice step (11-12/13: 8.6-11 s)
PRICES = {"nightly", "pretip", "poll", "afternoon", "refresh"}
SHARE_PRICED_AFTERNOON = (0.7, 1.0)      # afternoons whose line changed (tags move most days)
POLL_REFRESHES_PER_MONDAY = (5, 8)       # 11-02: 3, 11-09: 7 distinct half-hours with moves
ENTRIES_PER_WEEK = (7, 14)               # 11-11..11-13: 3 entry / override runs in 3 days
PLAN_SINCE = date(2026, 11, 11)          # task 6f: cron-job.org's plan; before it, GitHub's own crons


def run_job_minutes(mode: str, case: int) -> int:
    """One run job, billed: ceil((setup + run [+ advice]) / 60), at least 1."""
    secs = SETUP_SECONDS[case] + RUN_SECONDS[mode][case]
    if mode in PRICES:
        secs += ADVICE_SECONDS[case]
    return max(1, math.ceil(secs / 60))


def _field(spec: str, lo: int, hi: int) -> set:
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, st = part.split("/")
            step = int(st)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = b = int(part)
        out.update(range(a, b + 1, step))
    return out


def cron_per_week(expr: str) -> int:
    """Firings of a 5-field UTC cron (minute hour * * dow) in one week."""
    m, h, dom, mon, dow = expr.split()
    if dom != "*" or mon != "*":
        raise ValueError(f"{expr!r}: only minute, hour and day-of-week fields are modelled")
    days = _field(dow.replace("7", "0"), 0, 6)
    return len(_field(m, 0, 59)) * len(_field(h, 0, 23)) * len(days)


def github_crons(base=ROOT) -> dict:
    out = {}
    for p in sorted((base / "deploy/state-repo/.github/workflows").glob("*.yml")):
        crons = re.findall(r"-\s*cron:\s*'([^']+)'", p.read_text(encoding="utf-8"))
        if crons:
            out[p.name] = sum(cron_per_week(c) for c in crons)
    return out


def cron_job_org(base=ROOT) -> dict:
    """{job name: firings per week}, from the plan."""
    plan = json.loads((base / "deploy/state-repo/cron-job-org.json").read_text(encoding="utf-8"))
    out = {}
    for j in plan["jobs"]:
        per_day = len(j["times"]) if "times" in j else (
            (datetime.strptime(j["to"], "%H:%M") - datetime.strptime(j["from"], "%H:%M")).seconds
            // 60 // int(j["every_minutes"]) + 1)
        out[j["name"]] = per_day * len(j["days"])
    return out


def job(base, name: str) -> dict:
    plan = json.loads((base / "deploy/state-repo/cron-job-org.json").read_text(encoding="utf-8"))
    return next(j for j in plan["jobs"] if j["name"] == name)


def season_counts(start: date, base=ROOT) -> dict:
    """What the guard admits on every day from `start` to the season's end."""
    tz = rg.league_zone(base)
    weeks = json.loads((base / "config/SCHEDULE.json").read_text(encoding="utf-8"))["weeks"]
    end = date.fromisoformat(str(weeks[-1]["end_date"])[:10])
    pre = job(base, "Pre-tip")
    t0, t1 = (datetime.strptime(pre[k], "%H:%M").time() for k in ("from", "to"))
    step = timedelta(minutes=int(pre["every_minutes"]))
    afternoon, skipped, polls, pretips, mondays, game_days = 0, [], 0, 0, 0, 0
    d = start
    while d <= end:
        plan = rg.afternoon_plan(base, d, tz, base)
        if plan["first_tip"] is not None:
            game_days += 1
            if plan["firing"]:
                afternoon += 1
            else:
                skipped.append(plan["why"])
        if d.weekday() == 0 and d in rg.window_days(base):
            mondays += 1
            t = datetime.combine(d, t0, tzinfo=tz)
            while t <= datetime.combine(d, t1, tzinfo=tz):
                kind, _ = rg.monday_decision(t.astimezone(timezone.utc), base, base)
                polls += kind == "poll"
                pretips += kind == "pretip"
                t += step
        d += timedelta(days=1)
    n_weeks = ((end - start).days + 1) / 7
    return {"from": start.isoformat(), "to": end.isoformat(), "weeks": round(n_weeks, 2),
            "non_window_game_days": game_days, "afternoon_runs": afternoon, "afternoon_skipped": skipped,
            "coverage": round(afternoon / game_days, 3) if game_days else None,
            "window_mondays": mondays, "polls": polls, "pretip_runs": pretips,
            "polls_per_monday": round(polls / mondays, 2) if mondays else 0.0}


def estimate(start: date, base=ROOT) -> dict:
    """The state repo's billed minutes in a month, (typical, worst), by
    workflow, from the plan of record and the guard's admissions over the
    rest of the season."""
    sc = season_counts(start, base)
    cjo = cron_job_org(base)
    month = lambda per_week: per_week * WEEKS_PER_MONTH            # noqa: E731
    aft_runs = month(sc["afternoon_runs"] / sc["weeks"])
    mondays = month(sc["window_mondays"] / sc["weeks"])
    polls = sc["polls_per_monday"] * mondays
    pretips = month(sc["pretip_runs"] / sc["weeks"])
    rows = []
    for i, case in enumerate(("typical", "worst")):
        share = SHARE_PRICED_AFTERNOON[i]
        other_pretip_firings = month(cjo["Pre-tip"]) - polls
        r = {
            "nightly.yml": month(cjo["Nightly"]) * GUARD_MIN[i] + DAYS_PER_MONTH * run_job_minutes("nightly", i),
            "pretip.yml": (other_pretip_firings * GUARD_MIN[i] + polls * POLL_GUARD_MIN[i]
                           + pretips * run_job_minutes("pretip", i)
                           + mondays * POLL_REFRESHES_PER_MONDAY[i] * run_job_minutes("poll", i)),
            "afternoon.yml": (month(cjo["Afternoon tags"]) * GUARD_MIN[i]
                              + aft_runs * (share * run_job_minutes("afternoon", i)
                                            + (1 - share) * run_job_minutes("afternoon_unchanged", i))),
            "entry.yml + overrides-push.yml": month(ENTRIES_PER_WEEK[i]) * run_job_minutes("refresh", i),
        }
        total = sum(r.values())
        rows.append({"case": case, "by_workflow": {k: round(v) for k, v in r.items()}, "total": round(total),
                     "share_of_free": round(total / FREE_MINUTES, 3)})
    return {"counts": sc, "github_crons_per_week": github_crons(base), "cron_job_org_per_week": cjo,
            "run_job_minutes": {m: [run_job_minutes(m, 0), run_job_minutes(m, 1)] for m in RUN_SECONDS},
            "estimates": rows}


# =============================================================================
# a day at a time (the calibration against GitHub's usage report)
# =============================================================================

def firings_on(base, d: date, tz: ZoneInfo) -> list:
    """[(job name, aware LA datetime)] for every cron-job.org firing on LA day d."""
    plan = json.loads((base / "deploy/state-repo/cron-job-org.json").read_text(encoding="utf-8"))
    out = []
    for j in plan["jobs"]:
        if DAYS[d.weekday()] not in j["days"]:
            continue
        if "times" in j:
            ts = [datetime.strptime(t, "%H:%M").time() for t in j["times"]]
        else:
            t = datetime.combine(d, datetime.strptime(j["from"], "%H:%M").time())
            t1 = datetime.combine(d, datetime.strptime(j["to"], "%H:%M").time())
            ts = []
            while t <= t1:
                ts.append(t.time())
                t += timedelta(minutes=int(j["every_minutes"]))
        out += [(j["name"], datetime.combine(d, t, tzinfo=tz)) for t in ts]
    return out


WORKFLOW = {"Nightly": "nightly.yml", "Pre-tip": "pretip.yml", "Afternoon tags": "afternoon.yml"}


def day_model(utc_day: date, base=ROOT, case: int = 0) -> dict:
    """{workflow: billed minutes} the plan predicts for one UTC day (the
    usage report's day), entries excluded (they follow Nick's entries, not a
    clock). Expected values: a priced share of afternoons, a Monday's poll
    refreshes spread over its polls."""
    tz = rg.league_zone(base)
    out = {}
    for d in (utc_day - timedelta(days=1), utc_day, utc_day + timedelta(days=1)):
        fs = firings_on(base, d, tz)
        aft = rg.afternoon_plan(base, d, tz, base) if any(n == "Afternoon tags" for n, _t in fs) else None
        firsts = {}
        mon = [t for n, t in fs if n == "Pre-tip"]
        kinds = {t: rg.monday_decision(t.astimezone(timezone.utc), base, base)[0] for t in mon} \
            if mon and d in rg.window_days(base) else {}
        n_polls = sum(1 for k in kinds.values() if k == "poll")
        for name, t in fs:
            if t.astimezone(timezone.utc).date() != utc_day:
                continue
            wf = WORKFLOW[name]
            m = 0.0
            if name == "Nightly":
                m += GUARD_MIN[case]
                if name not in firsts:                       # the guard admits the night's first firing
                    firsts[name] = t
                    m += run_job_minutes("nightly", case)
            elif name == "Afternoon tags":
                m += GUARD_MIN[case]
                if aft is not None and aft["firing"] == t.strftime("%H:%M"):
                    sh = SHARE_PRICED_AFTERNOON[case]
                    m += sh * run_job_minutes("afternoon", case) + (1 - sh) * run_job_minutes(
                        "afternoon_unchanged", case)
            else:
                kind = kinds.get(t)
                if kind == "poll":
                    m += POLL_GUARD_MIN[case] + (POLL_REFRESHES_PER_MONDAY[case] / n_polls) * run_job_minutes(
                        "poll", case)
                else:
                    m += GUARD_MIN[case]
                    if kind == "pretip":
                        m += run_job_minutes("pretip", case)
            out[wf] = out.get(wf, 0.0) + m
    return out


# =============================================================================
# GitHub's detailed usage report
# =============================================================================

def repos(base=ROOT) -> dict:
    """{"counted": the private state repo, "free": the public repos} -- names
    without the owner, as the usage report writes them."""
    man = json.loads((base / "config/STATE_MANIFEST.json").read_text(encoding="utf-8"))
    run = (base / "deploy/state-repo/.github/workflows/run.yml").read_text(encoding="utf-8")
    pub = re.findall(r"^\s*(?:ENGINE_REPO|HUB_REPO):\s*(\S+)\s*$", run, flags=re.M)
    if len(pub) != 2:
        raise ValueError("run.yml must name ENGINE_REPO and HUB_REPO (the public repos)")
    return {"counted": man["private_repo"].split("/")[-1], "free": sorted(r.split("/")[-1] for r in pub)}


def read_usage(path, base=ROOT) -> dict:
    """GitHub's detailed usage report (CSV): Actions minutes by repo, workflow
    and day, each row marked counted (the private state repo) or free (a
    public repo). A repo that is neither RAISES; rows that are not Actions
    minutes (storage) are counted aside."""
    rp = repos(base)
    rows, other = [], 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("product") != "actions" or r.get("unit_type") != "minutes":
                other += 1
                continue
            repo = r["repository"]
            if repo == rp["counted"]:
                counted = True
            elif repo in rp["free"]:
                counted = False
            else:
                raise ValueError(f"{path}: repository {repo!r} is neither the state repo ({rp['counted']}) nor "
                                 f"a public one ({', '.join(rp['free'])}): add it before counting")
            rows.append({"date": date.fromisoformat(r["date"]), "repo": repo,
                         "workflow": r["workflow_path"].split("/")[-1], "minutes": float(r["quantity"]),
                         "counted": counted})
    if not rows:
        raise ValueError(f"{path}: no Actions minutes rows")
    return {"rows": rows, "other_rows": other, "repos": rp}


def usage_summary(u: dict) -> dict:
    by = {}
    for r in u["rows"]:
        k = (r["repo"], r["workflow"], r["counted"])
        by[k] = by.get(k, 0.0) + r["minutes"]
    days = sorted({r["date"] for r in u["rows"]})
    return {"from": days[0].isoformat(), "to": days[-1].isoformat(),
            "by_workflow": [{"repo": k[0], "workflow": k[1], "counted": k[2], "minutes": round(v)}
                            for k, v in sorted(by.items(), key=lambda kv: (not kv[0][2], -kv[1]))],
            "counted": round(sum(r["minutes"] for r in u["rows"] if r["counted"])),
            "free": round(sum(r["minutes"] for r in u["rows"] if not r["counted"]))}


def calibrate(u: dict, base=ROOT) -> list:
    """The state repo's minutes by UTC day and workflow, beside day_model's
    for the same day (typical). Days before PLAN_SINCE ran on another plan."""
    act = {}
    for r in u["rows"]:
        if r["counted"]:
            act.setdefault(r["date"], {})
            act[r["date"]][r["workflow"]] = act[r["date"]].get(r["workflow"], 0.0) + r["minutes"]
    out = []
    for d in sorted(act):
        model = day_model(d, base)
        for wf in sorted(set(act[d]) | set(model)):
            out.append({"date": d.isoformat(), "workflow": wf, "actual": round(act[d].get(wf, 0.0)),
                        "model": None if wf not in WORKFLOW.values() else round(model.get(wf, 0.0), 1),
                        "plan_in_force": d >= PLAN_SINCE})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Actions minutes a month: the private state repo's, recomputed")
    ap.add_argument("--from", dest="start", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--usage-csv", help="GitHub's detailed usage report (CSV): minutes by repo and "
                                        "workflow, counted vs free, and the calibration by day")
    a = ap.parse_args(argv)
    if a.usage_csv:
        u = read_usage(a.usage_csv)
        sm = usage_summary(u)
        cal = calibrate(u)
        if a.json:
            print(json.dumps({"summary": sm, "calibration": cal}, indent=1))
            return 0
        print(f"usage report {sm['from']} to {sm['to']}: {sm['counted'] + sm['free']} minutes; "
              f"COUNTED {sm['counted']} (the private {u['repos']['counted']}), free {sm['free']} "
              f"(public: {', '.join(u['repos']['free'])})")
        for r in sm["by_workflow"]:
            print(f"  {'counted' if r['counted'] else 'free   '}  {r['repo']:28s} {r['workflow']:28s} {r['minutes']:6d}")
        if u["other_rows"]:
            print(f"  ({u['other_rows']} non-minute rows, e.g. storage, not counted here)")
        print("\nthe state repo by UTC day, the report beside the model (typical; entries are not modelled by day):")
        for c in cal:
            m = "-" if c["model"] is None else f"{c['model']:.1f}"
            print(f"  {c['date']}  {c['workflow']:22s} actual {c['actual']:4d}  model {m:>6s}"
                  + ("" if c["plan_in_force"] else "   (before 11-11: GitHub's own crons, another plan)"))
        return 0
    start = date.fromisoformat(a.start) if a.start else datetime.now(ZoneInfo("America/Los_Angeles")).date()
    e = estimate(start)
    if a.json:
        print(json.dumps(e, indent=1))
        return 0
    c = e["counts"]
    print(f"season {c['from']} to {c['to']} ({c['weeks']} weeks); counted: the private state repo only "
          "(public repos are free)")
    print(f"GitHub's own crons, firings a week: {e['github_crons_per_week']}")
    print(f"cron-job.org, firings a week: {e['cron_job_org_per_week']}")
    print(f"afternoon: {c['afternoon_runs']} of {c['non_window_game_days']} non-window game days run "
          f"({c['coverage']:.1%}); Mondays: {c['window_mondays']}, {c['polls']} polls, {c['pretip_runs']} pre-tip runs")
    print("run job, billed minutes (typical, worst): "
          + ", ".join(f"{m} {v[0]}/{v[1]}" for m, v in e["run_job_minutes"].items()))
    for r in e["estimates"]:
        print(f"\n{r['case']}, a month:")
        for k, v in r["by_workflow"].items():
            print(f"  {k:34s} {v:6d}")
        print(f"  {'TOTAL':34s} {r['total']:6d}   ({r['share_of_free']:.0%} of the free {FREE_MINUTES})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
