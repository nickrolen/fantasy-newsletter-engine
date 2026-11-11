#!/usr/bin/env python3
"""
actions_minutes.py -- the private repo's Actions minutes, recomputed (step 3b).
Standard library only.

    python scripts/actions_minutes.py                   the table, from today to the season's end
    python scripts/actions_minutes.py --from 2026-11-11 --json

The handoff's hard constraint: the free plan is 2,000 minutes a month, and a
3b worst case past ~1,700 stops the build. EVERY FIRING BILLS AT LEAST ONE
MINUTE, a refused one included. This script counts the firings themselves --
it never takes a count from a doc:
  - GitHub's own crons, from the workflow files (deploy/state-repo/.github/
    workflows/*.yml), evaluated minute by minute over a week (task 6f removes
    them);
  - cron-job.org's jobs, from deploy/state-repo/cron-job-org.json (the plan of
    record; tests pin its afternoon times to config live_refresh);
  - what the guard admits, from scripts/run_guard.py's own functions over every
    remaining day of the season: the afternoon runs (afternoon_plan) and the
    Monday polls and pre-tip runs (monday_decision at each pre-tip firing).
Minutes per run are the COST MODEL below (typical, worst), from the measured
work (3a's result s.10, 1c-ii's s.11); worst = a runner twice as slow.
BASELINE is today's total before 3b as 3a's result states it (it is not
recomputed here: it includes the nightly and entry runs this script does not
model). tests/test_tag_freshness.py runs this and pins the counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_guard as rg                                   # noqa: E402

WEEKS_PER_MONTH = 4.35
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# (typical, worst) billed minutes. A run job's setup: checkouts ~10 s, Python
# and the venv restore ~15 s (step 3b caches it; the install was 40-60 s),
# overlay and commit ~10 s, hub checkout, scan and push ~15 s.
COST = {
    "firing": (1, 1),             # the guard job: seconds, billed a minute
    "poll_no_change": (0, 1),     # inside the guard job; worst: the pinned install pushes it to 2
    "afternoon_priced": (4, 6),   # tags ~5 s, report ~10 s, line ~5 s, title odds ~80 s, hub ~13 s
    "afternoon_unchanged": (2, 3),
    "poll_refresh": (4, 6),       # sync, the refresh with title odds, hub
    "report_read": (0.2, 1),      # +~10 s on each nightly and pre-tip run
    "nudge_nightly": (0, 1),      # +~1 s, and the issue step's gh calls on a night with nudges
    "nba_issue_step": (0.1, 1),   # gh calls on a run with flags
    "venv_saving": (-0.5, -1),    # per run job, every mode (the 40-60 s install becomes a restore)
}
SHARE_PRICED_AFTERNOON = (0.7, 1.0)      # afternoons whose line changed (tags move most days)
POLL_REFRESHES_PER_MONDAY = (5, 8)       # 11-02: 3, 11-09: 7 distinct half-hours with moves (+ overnight)
BASELINE = {"typical": 760, "worst": 1355, "note": "3a's result s.10: today's nightly + Monday + entries"}
GITHUB_CRONS_6F = 300                    # the handoff's figure for task 6f
RUN_JOBS_PER_MONTH_TODAY = 99            # nightly 30 + pre-tip 13 + entries ~56 (3a's 13 a week)


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
    sc = season_counts(start, base)
    cjo = cron_job_org(base)
    month = lambda per_week: per_week * WEEKS_PER_MONTH            # noqa: E731
    aft_runs = month(sc["afternoon_runs"] / sc["weeks"])
    mondays = month(sc["window_mondays"] / sc["weeks"])
    polls = sc["polls_per_monday"] * mondays
    rows = []
    for i, k in enumerate(("typical", "worst")):
        share = SHARE_PRICED_AFTERNOON[i]
        r = {
            "afternoon firings (guard, 1 min each)": month(cjo["Afternoon tags"]) * COST["firing"][i],
            "afternoon runs": aft_runs * (share * COST["afternoon_priced"][i]
                                          + (1 - share) * COST["afternoon_unchanged"][i]),
            "Monday polls with nothing new (in the guard job)": polls * COST["poll_no_change"][i],
            "Monday poll refreshes": mondays * POLL_REFRESHES_PER_MONDAY[i] * COST["poll_refresh"][i],
            "NBA report read (nightly, pre-tip)": (30.4 + month(sc["pretip_runs"] / sc["weeks"]))
                                                  * COST["report_read"][i],
            "O-past-3 nudge (nightly)": 30.4 * COST["nudge_nightly"][i],
            "NBA-report issue step": (aft_runs + 30.4) * COST["nba_issue_step"][i],
            "venv cache (every run job)": (RUN_JOBS_PER_MONTH_TODAY + aft_runs
                                           + mondays * POLL_REFRESHES_PER_MONDAY[i]) * COST["venv_saving"][i],
        }
        add = sum(r.values())
        rows.append({"case": k, "pieces": {kk: round(v) for kk, v in r.items()}, "added_by_3b": round(add),
                     "baseline": BASELINE[k], "total": round(BASELINE[k] + add),
                     "total_after_6f": round(BASELINE[k] + add - GITHUB_CRONS_6F)})
    return {"counts": sc, "github_crons_per_week": github_crons(base), "cron_job_org_per_week": cjo,
            "estimates": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Actions minutes a month, recomputed from the plan")
    ap.add_argument("--from", dest="start", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    start = date.fromisoformat(a.start) if a.start else datetime.now(ZoneInfo("America/Los_Angeles")).date()
    e = estimate(start)
    if a.json:
        print(json.dumps(e, indent=1))
        return 0
    c = e["counts"]
    print(f"season {c['from']} to {c['to']} ({c['weeks']} weeks)")
    print(f"GitHub's own crons, firings a week: {e['github_crons_per_week']}  (task 6f removes them)")
    print(f"cron-job.org, firings a week: {e['cron_job_org_per_week']}")
    print(f"afternoon: {c['afternoon_runs']} of {c['non_window_game_days']} non-window game days run "
          f"({c['coverage']:.1%}); {len(c['afternoon_skipped'])} skipped")
    print(f"Mondays: {c['window_mondays']}, {c['polls']} polls ({c['polls_per_monday']} a Monday), "
          f"{c['pretip_runs']} pre-tip runs")
    for r in e["estimates"]:
        print(f"\n{r['case']}:")
        for k, v in r["pieces"].items():
            print(f"  {k:52s} {v:6d}")
        print(f"  {'added by 3b':52s} {r['added_by_3b']:6d}")
        print(f"  {'baseline (3a)':52s} {r['baseline']:6d}")
        print(f"  {'TOTAL':52s} {r['total']:6d}   after 6f: {r['total_after_6f']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
