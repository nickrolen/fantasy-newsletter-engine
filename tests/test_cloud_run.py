"""
Step 1c-ii: the nightly run in GitHub Actions, and the hub published
(claude/HANDOFF_STEP1C2_CLOUD_RUN_2026-11-03.md s.7).

  1. the workflow files (deploy/state-repo/.github/workflows): both crons; the
     Monday cron covers 12:00-19:30 Pacific under PST and PDT, and every window
     day's pre-tip window of the season; one concurrency group; TZ; no
     forbidden flag; secrets only referenced, never echoed; force only from
     workflow_dispatch;
  2. the guards (scripts/run_guard.py): one firing a day for the nightly run
     (shared with nightly.py); pre-tip only in [first tip - 45 min, first tip)
     on window days, both DST regimes; standard library only;
  3. the closing line when due (closing_line.due, nightly.scheduled_closing);
  4. scripts/state_overlay.py;
  6. nightly.py's engine step and ENGINE_COMMIT;
  7. the publish step's scan (scripts/hub_deploy.py);
  plus the failure issue's title (scripts/run_issue.py).
(5, state.py, is in tests/test_state_manifest.py beside P2's pull/push tests.)
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_guard as rg                               # noqa: E402
from modules import nightly                           # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
WF = ROOT / "deploy" / "state-repo" / ".github" / "workflows"
WORKFLOWS = {p.name: p.read_text(encoding="utf-8") for p in sorted(WF.glob("*.yml"))}
FORBIDDEN_FLAGS = ("--allow-dirty-engine", "--allow-engine-mismatch", "--no-league-state")


# =============================================================================
# 1. the workflow files
# =============================================================================

def test_the_three_workflow_files_exist():
    assert sorted(WORKFLOWS) == ["nightly.yml", "pretip.yml", "run.yml"]


def crons(text: str) -> list:
    return re.findall(r"^\s*-\s*cron:\s*'([^']+)'\s*$", text, flags=re.M)


def _field(spec: str, lo: int, hi: int) -> set:
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-"))
        else:
            a = b = int(part)
        out.update(range(a, b + 1, step))
    return out


def fires(expr: str, t: datetime) -> bool:
    """A 5-field cron (no names; dom and month '*') against a UTC minute."""
    m, h, dom, mon, dow = expr.split()
    assert dom == "*" and mon == "*", expr
    return (t.minute in _field(m, 0, 59) and t.hour in _field(h, 0, 23)
            and (t.isoweekday() % 7) in _field(dow, 0, 6))


def firings(exprs, start_utc: datetime, end_utc: datetime) -> list:
    out, t = [], start_utc
    while t < end_utc:
        if any(fires(e, t) for e in exprs):
            out.append(t)
        t += timedelta(minutes=1)
    return out


def test_the_nightly_cron_and_the_pretip_crons():
    assert crons(WORKFLOWS["nightly.yml"]) == ["1,31 7-11 * * *"]   # 11-05: late/dropped firings
    assert crons(WORKFLOWS["pretip.yml"]) == ["*/15 15-23 * * 1", "*/15 0-3 * * 2"]
    assert crons(WORKFLOWS["run.yml"]) == []          # never scheduled on its own


@pytest.mark.parametrize("monday", [date(2026, 11, 9), date(2027, 3, 22)])   # PST, PDT
def test_the_monday_cron_covers_12_00_to_19_30_pacific_under_pst_and_pdt(monday):
    exprs = crons(WORKFLOWS["pretip.yml"])
    start = datetime.combine(monday, datetime.min.time(), LA).replace(hour=12)
    end = start.replace(hour=19, minute=30)
    t = start
    while t <= end:
        assert any(fires(e, t.astimezone(timezone.utc)) for e in exprs), t
        t += timedelta(minutes=15)


def test_every_window_day_of_the_season_gets_three_pretip_firings_inside_its_window():
    exprs = crons(WORKFLOWS["pretip.yml"])
    days = rg.window_days(ROOT)
    # Opening day (2026-10-20, a Tuesday) was before the cloud run; every other
    # window day is a Monday. Next season's schedule re-runs this check.
    assert [d for d in days if d.isoweekday() != 1] == [date(2026, 10, 20)]
    for d in days[1:]:
        tip = rg.first_tip(ROOT, d)
        assert tip is not None, d
        got = firings(exprs, (tip - rg.PRETIP_LEAD).astimezone(timezone.utc), tip.astimezone(timezone.utc))
        admitted = [f for f in got if rg.admits_pretip(f, ROOT)[0]]
        assert len(got) >= 3 and admitted == got, (d, tip, got)


def test_one_concurrency_group_never_cancelled():
    found = [(n, m) for n, t in WORKFLOWS.items() for m in re.finditer(r"concurrency:", t)]
    assert len(found) == 1 and found[0][0] == "run.yml", found
    run = WORKFLOWS["run.yml"]
    block = run[run.index("concurrency:"):][:120]
    assert "group: newsletter-state" in block and "cancel-in-progress: false" in block
    import yaml
    jobs = yaml.safe_load(run)["jobs"]
    assert jobs["run"]["concurrency"] == {"group": "newsletter-state", "cancel-in-progress": False}
    assert "concurrency" not in jobs["guard"]           # an idle firing never queues


def test_tz_is_the_league_clock_for_every_step():
    import yaml
    from modules.league_clock import league_tz
    run = yaml.safe_load(WORKFLOWS["run.yml"])
    assert run["env"]["TZ"] == "America/Los_Angeles" == league_tz().key
    for name in ("nightly.yml", "pretip.yml"):       # callers have no steps of their own
        jobs = yaml.safe_load(WORKFLOWS[name])["jobs"]
        assert all(set(j) <= {"uses", "with", "secrets"} for j in jobs.values()), name


def test_no_forbidden_flag_in_any_workflow():
    for name, text in WORKFLOWS.items():
        for flag in FORBIDDEN_FLAGS:
            assert flag not in text, (name, flag)


def test_secrets_are_only_referenced_never_echoed():
    for name, text in WORKFLOWS.items():
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            assert not re.search(r"\b(echo|printf|cat)\b[^\n]*\$\{\{\s*secrets\.", s), (name, i, s)
            assert not re.search(r"\bcat\b[^|]*oauth2", s), (name, i, s)
            assert "set -x" not in s, (name, i, s)
            assert not re.search(r"(echo|printf)[^|>]*\$(YAHOO_OAUTH_JSON|HUB_PASSPHRASE|HUB_DEPLOY_TOKEN)", s) \
                or "printf '%s' \"$YAHOO_OAUTH_JSON\" > oauth2.json" in s, (name, i, s)
            if "${{ secrets." in s:
                # only as an env value or the checkout's token, never inline in a command
                assert re.match(r"^[A-Z_]+:\s*\$\{\{\s*secrets\.[A-Z_]+\s*\}\}$", s) \
                    or re.match(r"^token:\s*\$\{\{\s*secrets\.HUB_DEPLOY_TOKEN\s*\}\}$", s), (name, i, s)
    run = WORKFLOWS["run.yml"]
    assert "umask 077" in run and "printf '%s' \"$YAHOO_OAUTH_JSON\" > oauth2.json" in run


def test_force_exists_only_under_workflow_dispatch():
    import yaml
    nightly_wf = yaml.safe_load(WORKFLOWS["nightly.yml"])
    on = nightly_wf[True]                                      # YAML 1.1 reads "on" as True
    assert set(on["workflow_dispatch"]["inputs"]) == {"force"}
    assert "inputs" not in (on.get("schedule") or [{}])[0]
    assert nightly_wf["jobs"]["nightly"]["with"]["force"] == \
        "${{ github.event_name == 'workflow_dispatch' && inputs.force == true }}"
    assert "force" not in WORKFLOWS["pretip.yml"]
    run = yaml.safe_load(WORKFLOWS["run.yml"])
    assert run["env"]["FORCE"] == "${{ github.event_name == 'workflow_dispatch' && inputs.force == true }}"
    # every other mention of force in run.yml reads $FORCE (that env), and
    # --ignore-clock is passed only in its branch
    text = WORKFLOWS["run.yml"]
    for i, line in enumerate(text.splitlines(), 1):
        if "inputs.force" in line and not line.strip().startswith("#"):
            assert line.strip().startswith("FORCE:"), (i, line)
    assert text.count("--ignore-clock") == 1
    branch = text[text.index('elif [ "$MODE" = nightly ] && [ "$FORCE" = true ]; then'):]
    assert branch.splitlines()[1].strip() == "set -- --scheduled --ignore-clock"


def test_the_run_job_runs_only_what_the_guard_admits_and_copies_back_always():
    import yaml
    jobs = yaml.safe_load(WORKFLOWS["run.yml"])["jobs"]
    assert jobs["run"]["needs"] == "guard" and jobs["run"]["if"] == "needs.guard.outputs.go == 'true'"
    steps = {s.get("id"): s for s in jobs["run"]["steps"] if s.get("id")}
    assert steps["overlay-out"]["if"] == "always() && steps.overlay-in.outcome == 'success'"
    assert steps["commit-state"]["if"] == "always() && steps.overlay-out.outcome == 'success'"
    order = [s.get("id") for s in jobs["run"]["steps"]]
    assert order.index("run") < order.index("overlay-out") < order.index("commit-state") \
        < order.index("publish-scan") < order.index("publish")
    assert "--state-dir ../state" in steps["overlay-in"]["run"]
    assert "hub_deploy.py --target ../hub" in steps["publish-scan"]["run"]
    assert "ENGINE_COMMIT: ${{ steps.pin.outputs.commit }}" in WORKFLOWS["run.yml"]
    # the guard job installs nothing: the runner's own python3 and four files
    g = jobs["guard"]["steps"]
    assert not any("setup-python" in str(s.get("uses", "")) or "pip" in str(s.get("run", "")) for s in g)
    assert "python3 engine/scripts/run_guard.py" in str(g)


# =============================================================================
# 2. the guards
# =============================================================================

def test_the_nightly_guard_is_one_definition_shared_with_nightly_py(tmp_path):
    from modules.league_clock import league_tz
    assert rg.league_zone(ROOT).key == league_tz().key
    day = date(2026, 10, 1)
    while day <= date(2027, 4, 30):
        for h in (7, 8, 11):
            f = datetime(day.year, day.month, day.day, h, 1, tzinfo=timezone.utc)
            assert nightly.scheduled_guard_admits(f, tmp_path) == rg.admits_nightly(f, LA, None)
        day += timedelta(days=1)
    src = (ROOT / "modules" / "nightly.py").read_text(encoding="utf-8")
    assert ".hour == 0" not in src            # the decision lives in run_guard only


def test_the_guard_tips_equal_price_locks_on_every_window_day():
    from modules import price_lock
    from modules.data_loader import load_nba_schedule, NBA_SCHEDULE_FILE
    sched = load_nba_schedule(ROOT / NBA_SCHEDULE_FILE)
    for d in rg.window_days(ROOT):
        assert rg.first_tip(ROOT, d) == price_lock.first_tip(d, sched), d


def _admitted_minutes(day: date) -> list:
    start = datetime.combine(day, datetime.min.time(), LA)
    out, t = [], start
    while t.date() == day:
        if rg.admits_pretip(t.astimezone(timezone.utc), ROOT)[0]:
            out.append(t)
        t += timedelta(minutes=1)
    return out


@pytest.mark.parametrize("day,tip", [
    (date(2026, 11, 9), (16, 0, "PST")),       # week 4, standard time
    (date(2026, 11, 30), (16, 0, "PST")),      # week 7's window (the 14-day week)
    (date(2026, 10, 26), (16, 0, "PDT")),      # week 2, daylight time
    (date(2027, 3, 15), (16, 0, "PDT")),       # week 20, daylight time again
    (date(2027, 1, 18), (9, 0, "PST")),        # MLK Day: a morning first tip
])
def test_pretip_admits_only_the_45_minutes_before_the_first_tip(day, tip):
    got = _admitted_minutes(day)
    first = datetime.combine(day, datetime.min.time(), LA).replace(hour=tip[0], minute=tip[1])
    assert first.tzname() == tip[2]
    assert got[0] == first - timedelta(minutes=45) and got[-1] == first - timedelta(minutes=1)
    assert len(got) == 45


@pytest.mark.parametrize("day", [date(2026, 12, 7), date(2026, 11, 10), date(2026, 11, 8)])
def test_pretip_admits_nothing_off_a_window_day(day):
    # 12-07 is a Monday inside week 7, the 14-day week: not a window day
    assert _admitted_minutes(day) == []


def _guard_base(tmp_path, games, weeks=None, cfg=None):
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "config" / "league_config.json").write_text(json.dumps(cfg if cfg is not None else {
        "league_structure": {"time_zone": "America/Los_Angeles"},
        "season": {"nba_schedule_file": "data/nba.json"}}), encoding="utf-8")
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(
        {"weeks": weeks or [{"week": 4, "start_date": "2026-11-09", "end_date": "2026-11-15"}]}),
        encoding="utf-8")
    (tmp_path / "data" / "nba.json").write_text(json.dumps({"games": games}), encoding="utf-8")
    return tmp_path


def test_a_window_day_with_a_game_missing_its_tip_refuses(tmp_path):
    base = _guard_base(tmp_path, [{"date": "2026-11-09T00:00:00Z", "home": "A", "away": "B",
                                   "tip_utc": "2026-11-10T00:00:00Z"},
                                  {"date": "2026-11-09T00:00:00Z", "home": "C", "away": "D",
                                   "tip_utc": None}])
    with pytest.raises(rg.GuardError, match="no tip time for D @ C"):
        rg.admits_pretip(datetime(2026, 11, 9, 23, 30, tzinfo=timezone.utc), base)
    # a day that is not a window day never reads a tip
    assert rg.admits_pretip(datetime(2026, 11, 10, 23, 30, tzinfo=timezone.utc), base)[0] is False


def test_the_guard_refuses_a_missing_key_rather_than_guess(tmp_path):
    base = _guard_base(tmp_path, [], cfg={"season": {"nba_schedule_file": "data/nba.json"}})
    with pytest.raises(rg.GuardError, match="time_zone"):
        rg.decide("nightly", datetime(2026, 11, 9, 8, 1, tzinfo=timezone.utc), base)


def test_the_guard_cli_writes_go_for_the_workflow(tmp_path, monkeypatch):
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert rg.main(["pretip", "--now", "2026-11-09T23:30:00Z"]) == 0
    assert rg.main(["pretip", "--now", "2026-11-10T00:00:00Z"]) == 0
    assert rg.main(["nightly", "--now", "2026-11-09T08:01:00Z", "--state-dir", str(tmp_path)]) == 0
    assert out.read_text().splitlines() == ["go=true", "go=false", "go=true"]


GUARD_BLOCKER = r'''
import importlib.machinery, sys
# Refuse every module installed outside the standard library (site- or
# dist-packages), tzdata excepted (zoneinfo's database where the OS has none).
class Block:
    def find_spec(self, name, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        origin = (spec.origin or "") if spec else ""
        if ("site-packages" in origin or "dist-packages" in origin) and name.split(".")[0] != "tzdata":
            raise ImportError("not standard library: " + name + " (" + origin + ")")
        return None
sys.meta_path.insert(0, Block())
sys.path.insert(0, sys.argv[1])
sys.argv = ["run_guard.py"] + sys.argv[2:]
import run_guard
for m in ("pandas", "numpy", "modules"):
    assert m not in sys.modules, m
sys.exit(run_guard.main())
'''


@pytest.mark.parametrize("args", [["pretip", "--now", "2026-11-09T23:30:00Z"],
                                  ["nightly", "--now", "2026-11-09T08:01:00Z"],
                                  ["pretip", "--now", "2026-11-10T12:00:00Z"]])
def test_the_guard_imports_nothing_outside_the_standard_library(args, tmp_path):
    # --state-dir: an empty folder, so the real output/nightly_last.json (which
    # moves every night) can't make a clock pinned to 11-09 read as the past (11-10)
    r = subprocess.run([sys.executable, "-c", GUARD_BLOCKER, str(ROOT / "scripts"), *args,
                        "--base-path", str(ROOT), "--state-dir", str(tmp_path)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("GO" in r.stdout) == (args[0] == "nightly" or args[2].startswith("2026-11-09T23"))


def test_the_guard_source_names_only_standard_library_modules():
    tree = ast.parse((ROOT / "scripts" / "run_guard.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            names.add(node.module.split(".")[0])
    assert names <= set(sys.stdlib_module_names), names - set(sys.stdlib_module_names)


def test_scheduled_pretip_uses_the_pretip_guard_not_the_midnight_one(monkeypatch, capsys):
    """1c-i's --scheduled applied the 00:xx guard to --pretip too, which would
    have skipped every Monday afternoon firing."""
    seen = {}
    monkeypatch.setattr(nightly, "pretip_guard_admits",
                        lambda now, base=".": seen.setdefault("pretip", (False, "outside")))
    monkeypatch.setattr(nightly, "scheduled_guard_decision",
                        lambda now, base=".": seen.setdefault("nightly", (True, "test")))
    assert nightly.main(["--pretip", "--scheduled"]) == 0
    assert "pretip" in seen and "nightly" not in seen


@pytest.mark.parametrize("argv", [["--ignore-clock"], ["--pretip", "--scheduled", "--ignore-clock"],
                                  ["--closing", "--week", "3", "--scheduled"]])
def test_ignore_clock_only_with_scheduled_nightly(argv):
    with pytest.raises(SystemExit):
        nightly.main(argv)


# =============================================================================
# 3. the closing line when due
# =============================================================================

def _tip(d: date, hh: int, mm: int = 0) -> str:
    t = datetime.combine(d, datetime.min.time(), LA).replace(hour=hh, minute=mm)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _world():
    weeks = [{"week": 3, "start_date": "2026-11-02", "end_date": "2026-11-08"},
             {"week": 4, "start_date": "2026-11-09", "end_date": "2026-11-15"}]
    games = []
    for d in (date(2026, 11, 2), date(2026, 11, 9)):
        games += [{"date": f"{d}T00:00:00Z", "home": "A", "away": "B", "tip_utc": _tip(d, 16)},
                  {"date": f"{d}T00:00:00Z", "home": "C", "away": "D", "tip_utc": _tip(d, 19)}]
    return SimpleNamespace(schedule={"weeks": weeks}, nba_schedule={"games": games})


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=LA)


def test_due_after_the_close_not_before(tmp_path):
    from modules import closing_line as cl
    w = _world()
    assert cl.due(tmp_path, at(2026, 11, 9, 18, 54), data=w) == 3       # week 4 closes 18:55
    assert cl.due(tmp_path, at(2026, 11, 9, 18, 55), data=w) == 4
    assert cl.due(tmp_path, at(2026, 11, 10, 0, 1), data=w) == 4        # Tuesday's 12:01 run
    assert cl.due(tmp_path, at(2026, 11, 2, 12, 0), data=w) is None     # before the first close


def test_a_missed_night_is_caught_up_and_a_week_is_never_due_twice(tmp_path):
    from modules import closing_line as cl
    w = _world()
    assert cl.due(tmp_path, at(2026, 11, 12, 0, 1), data=w) == 4        # Tuesday missed: Thursday
    cl.closing_path(tmp_path, 4).parent.mkdir(parents=True, exist_ok=True)
    cl.closing_path(tmp_path, 4).write_text("{}", encoding="utf-8")
    assert cl.due(tmp_path, at(2026, 11, 12, 0, 1), data=w) is None
    assert cl.due(tmp_path, at(2026, 11, 15, 0, 1), data=w) is None
    # week 3's missing line is never revisited: only the latest closed week counts
    assert not cl.closing_path(tmp_path, 3).exists()


def _closing_steps(raise_):
    def closing():
        raise raise_
    return {"engine": lambda: "e", "window": lambda: "w", "sync": lambda: "s", "closing": closing}


def test_no_pretip_record_is_recorded_once_and_never_retried(tmp_path):
    from modules import closing_line as cl
    from modules.tag_records import NoPretipTags
    w = _world()
    now = at(2026, 11, 10, 0, 1)
    out = nightly.scheduled_closing(tmp_path, now=now, data=w, echo=lambda *a: None,
                                    steps=_closing_steps(NoPretipTags("no tag record on 2026-11-09")))
    assert out["week"] == 4 and out["outcome"] == "none recorded"
    rec = json.loads(cl.none_path(tmp_path, 4).read_text(encoding="utf-8"))
    assert rec["outcome"] == "no closing line this week" and "no tag record" in rec["reason"]
    assert not cl.closing_path(tmp_path, 4).exists()
    again = nightly.scheduled_closing(tmp_path, now=at(2026, 11, 11, 0, 1), data=w, echo=lambda *a: None,
                                      steps=_closing_steps(AssertionError("must not run")))
    assert again == {"week": None, "outcome": "not due", "row": None}
    with pytest.raises(cl.ClosingRefused, match="already has"):
        cl.record_none(tmp_path, 4, reason="x", run_id="r", now=now)


def test_any_other_refusal_stops_the_run_and_is_retried_the_next_night(tmp_path):
    from modules import closing_line as cl
    w = _world()
    out = nightly.scheduled_closing(tmp_path, now=at(2026, 11, 10, 0, 1), data=w, echo=lambda *a: None,
                                    steps=_closing_steps(cl.ClosingRefused("transaction after the close")))
    assert out["outcome"] == "refused" and out["row"]["exit"] == 1
    assert not cl.none_path(tmp_path, 4).exists()
    assert cl.due(tmp_path, at(2026, 11, 11, 0, 1), data=w) == 4


def test_the_scheduled_nightly_run_stops_when_the_closing_line_refuses(monkeypatch):
    monkeypatch.setattr(nightly, "scheduled_guard_decision", lambda now, base=".": (True, "test"))
    marked = []
    monkeypatch.setattr(nightly, "record_night", lambda base, row, ok, now=None: marked.append(ok))
    monkeypatch.setattr(nightly, "scheduled_closing", lambda *a, **k: {
        "week": 4, "outcome": "refused", "row": {"seconds": 1.0, "error": "ClosingRefused: x"}})
    started = []
    monkeypatch.setattr(nightly.Run, "execute", lambda self, steps=None: started.append(1))
    assert nightly.main(["--scheduled"]) == 1 and started == []
    assert marked == [False]                  # the night counts as one failed attempt


def test_the_none_record_is_league_state_and_ignored():
    from modules import state_manifest as sm
    rel = "output/closing_none_week4.json"
    assert sm.load(ROOT).contains(rel)
    r = subprocess.run(["git", "check-ignore", "--no-index", rel, ".state_overlay.json"], cwd=str(ROOT),
                       capture_output=True, text=True)
    assert r.stdout.split() == [rel, ".state_overlay.json"]
    assert not sm.load(ROOT).contains(".state_overlay.json")


# =============================================================================
# 6. the engine step and ENGINE_COMMIT (design invariant 3)
# =============================================================================

def test_the_engine_step_refuses_head_other_than_engine_commit(monkeypatch):
    from modules import calibration_log as cal
    monkeypatch.setattr(cal, "engine_version", lambda base=".": {"commit": "abc1234", "dirty": False})
    monkeypatch.setattr(nightly, "engine_head", lambda base: "a" * 40)
    run = lambda: nightly.Run(".", "nightly", echo=lambda *a: None).step_engine()   # noqa: E731
    monkeypatch.delenv("ENGINE_COMMIT", raising=False)
    assert run() == "abc1234"                                   # unset: clean + known, as 1c-i
    monkeypatch.setenv("ENGINE_COMMIT", "b" * 40)
    with pytest.raises(nightly.StepRefused, match="not ENGINE_COMMIT"):
        run()
    monkeypatch.setenv("ENGINE_COMMIT", "a" * 40)
    assert run() == "abc1234"
    monkeypatch.setenv("ENGINE_COMMIT", "abc1234")
    with pytest.raises(nightly.StepRefused, match="full commit SHA"):
        run()
    # --allow-dirty-engine does not lift the pin
    monkeypatch.setenv("ENGINE_COMMIT", "b" * 40)
    with pytest.raises(nightly.StepRefused, match="not ENGINE_COMMIT"):
        nightly.Run(".", "nightly", allow_dirty_engine=True, echo=lambda *a: None).step_engine()


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the engine's git checkout")
def test_engine_head_is_the_full_sha_of_this_checkout():
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True)
    assert nightly.engine_head(ROOT) == r.stdout.strip() and len(r.stdout.strip()) == 40


# =============================================================================
# 4. state_overlay.py
# =============================================================================

import state_overlay as so                              # noqa: E402
from modules import state_manifest as sm               # noqa: E402

STATE = {
    "config/ROSTERS.json": b'{"rosters": {}}\r\n',
    "data/LINEUPS.xlsx": b"\x00\x01binary\xff",
    "data/lore_backups/2026-10-01.json": b"{}\n",
    "output/closing_none_week3.json": b"{}\n",
}
PRIVATE_ONLY = {"ENGINE_COMMIT": b"a" * 40 + b"\n", "README.md": b"# state\n",
                ".github/workflows/nightly.yml": b"name: Nightly\n", "notes.txt": b"not state\n"}


def _put(root: Path, files: dict):
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def _trees(tmp_path):
    eng, st_ = tmp_path / "engine", tmp_path / "state"
    (eng / "config").mkdir(parents=True)
    shutil.copy(ROOT / sm.MANIFEST_FILE, eng / sm.MANIFEST_FILE)
    _put(eng, {"modules/x.py": b"code\n", "oauth2.json": b'{"secret": "never copied"}'})
    _put(st_, {**STATE, **PRIVATE_ONLY})
    return eng, st_


def _all(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_overlay_in_copies_only_manifest_paths(tmp_path):
    eng, st_ = _trees(tmp_path)
    so.overlay_in(eng, st_, out=lambda *a: None)
    got = _all(eng)
    for rel, data in STATE.items():
        assert got[rel] == data
    for rel in PRIVATE_ONLY:
        assert rel not in got, rel
    assert got["modules/x.py"] == b"code\n"


def test_overlay_round_trip_is_byte_identical_and_never_copies_credentials_back(tmp_path):
    eng, st_ = _trees(tmp_path)
    before = _all(st_)
    so.overlay_in(eng, st_, out=lambda *a: None)
    so.overlay_out(eng, st_, out=lambda *a: None)
    assert _all(st_) == before                                  # nothing changed: identical
    _put(eng, {"data/LINEUPS.xlsx": b"new rows", "output/closing_line_week4.json": b"{}"})
    (eng / "data" / "lore_backups" / "2026-10-01.json").unlink()
    r = so.overlay_out(eng, st_, out=lambda *a: None)
    assert sorted(r["copied"]) == ["data/LINEUPS.xlsx", "output/closing_line_week4.json"]
    assert r["deleted"] == ["data/lore_backups/2026-10-01.json"]
    after = _all(st_)
    assert "oauth2.json" not in after and not any("oauth" in k for k in after)
    for rel in PRIVATE_ONLY:
        assert after[rel] == PRIVATE_ONLY[rel], rel             # never touched


def test_overlay_out_refuses_without_a_completed_in(tmp_path):
    eng, st_ = _trees(tmp_path)
    before = _all(st_)
    with pytest.raises(so.OverlayRefused, match="no completed overlay in"):
        so.overlay_out(eng, st_, out=lambda *a: None)
    assert _all(st_) == before


def test_overlay_refuses_a_credential_inside_a_manifest_directory(tmp_path):
    eng, st_ = _trees(tmp_path)
    _put(st_, {"data/lore_backups/oauth2.json": b"{}"})
    assert sm.load(eng).contains("data/lore_backups/oauth2.json")   # a dir entry would carry it
    with pytest.raises(so.OverlayRefused, match="credential"):
        so.overlay_in(eng, st_, out=lambda *a: None)
    assert not (eng / "data" / "lore_backups" / "oauth2.json").exists()


def test_overlay_refuses_a_missing_manifest_or_a_non_state_checkout(tmp_path):
    eng, st_ = _trees(tmp_path)
    (st_ / "ENGINE_COMMIT").unlink()
    with pytest.raises(so.OverlayRefused, match="ENGINE_COMMIT"):
        so.overlay_in(eng, st_, out=lambda *a: None)
    (st_ / "ENGINE_COMMIT").write_text("a" * 40)
    (eng / sm.MANIFEST_FILE).unlink()
    with pytest.raises(so.OverlayRefused, match="manifest"):
        so.overlay_in(eng, st_, out=lambda *a: None)


def test_the_overlay_reuses_state_pys_copier():
    src = (ROOT / "scripts" / "state_overlay.py").read_text(encoding="utf-8")
    assert "st.copy_state(" in src and "shutil" not in src


def test_oauth_is_never_a_manifest_path():
    man = sm.load(ROOT)
    for p in ("oauth2.json", "oauth2.backup_20260901_151034.json"):
        assert not man.contains(p)
    with pytest.raises(sm.ManifestError):
        sm.parse({**man.raw, "files": [*man.raw["files"], {"path": "oauth2.json", "what": "x"}]})


# =============================================================================
# 7. the publish step's scan (scripts/hub_deploy.py)
# =============================================================================

import hub_deploy as hd                                 # noqa: E402

TERMS = ["Nick", "Hayden", "Nikola Jokic", "<!-- lore:"]


def _hub(tmp_path, index=b"<html>ciphertext only</html>"):
    base, target = tmp_path / "base", tmp_path / "hub"
    _put(base, {"output/hub_publish/index.html": index,
                "output/hub_publish/issues/week01-abc.enc": b"\x00\x93enc"})
    _put(target, {"README.md": b"# newsletter-hub\n", ".git/description": b"Nick's repo\n"})
    return base, target


def test_deploy_mirrors_exactly_the_publish_set(tmp_path):
    base, target = _hub(tmp_path)
    r = hd.stage(base, target, terms=TERMS, out=lambda *a: None)
    assert r["files"] == [".nojekyll", "index.html", "issues/week01-abc.enc"]
    assert r["removed"] == ["README.md"]
    assert (target / ".git" / "description").read_bytes() == b"Nick's repo\n"   # .git untouched, unscanned
    again = hd.stage(base, target, terms=TERMS, out=lambda *a: None)
    assert again["changed"] == [] and again["removed"] == []


@pytest.mark.parametrize("where", ["output/hub_publish/index.html",
                                   "output/hub_publish/issues/week01-abc.enc"])
def test_deploy_refuses_a_planted_plaintext_file(tmp_path, where):
    from modules.hub_publish import PlaintextLeak
    base, target = _hub(tmp_path)
    _put(base, {where: b"<td>Nikola Jokic</td>"})
    with pytest.raises(PlaintextLeak):
        hd.stage(base, target, terms=TERMS, out=lambda *a: None)


def test_deploy_scans_what_is_pushed_not_only_the_source(tmp_path, monkeypatch):
    """If the copy into the target ever carried plaintext the source scan did
    not see, the scan of the target catches it."""
    from modules import hub_publish as hp
    from modules.hub_publish import PlaintextLeak
    base, target = _hub(tmp_path)
    real = hp.scan_dir
    calls = []

    def spy(path, terms, skip=()):
        calls.append(Path(path))
        if Path(path) == target:
            (target / "index.html").write_bytes(b"Hayden")       # tampered after the copy
        return real(path, terms, skip=skip)
    monkeypatch.setattr(hp, "scan_dir", spy)
    with pytest.raises(PlaintextLeak, match="what would be pushed"):
        hd.stage(base, target, terms=TERMS, out=lambda *a: None)
    assert calls[-1] == target


def test_deploy_refuses_without_an_encrypted_hub_or_with_a_stray_file(tmp_path):
    base, target = _hub(tmp_path)
    _put(base, {"output/hub_publish/hub_preview.html": b"x"})
    with pytest.raises(hd.DeployRefused, match="never publishes"):
        hd.stage(base, target, terms=TERMS, out=lambda *a: None)
    (base / "output" / "hub_publish" / "index.html").unlink()
    with pytest.raises(hd.DeployRefused, match="HUB_PASSPHRASE"):
        hd.stage(base, target, terms=TERMS, out=lambda *a: None)


# =============================================================================
# the failure issue (scripts/run_issue.py)
# =============================================================================

import run_issue as ri                                  # noqa: E402


def test_the_issue_title_names_the_failed_step_and_reason(tmp_path):
    runs = tmp_path / "runs.jsonl"
    old = {"mode": "nightly", "outcome": "refused", "error": "old", "steps": [{"step": "x", "outcome": "refused"}]}
    rows = [old,
            {"mode": "closing", "outcome": "refused", "error": "NoPretipTags: none",
             "steps": [{"step": "closing", "outcome": "refused"}]},
            {"mode": "nightly", "outcome": "refused", "error": "StepRefused: refresh_service: TipTimeMissing",
             "steps": [{"step": "engine", "outcome": "ok"}, {"step": "line", "outcome": "refused"}]}]
    runs.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    oc = ri.parse_outcomes("state=success,overlay-in=success,run=failure,overlay-out=success")
    got = ri.title(oc, ri.run_rows(runs, 1))
    assert got == "Nightly run failed: line: StepRefused: refresh_service: TipTimeMissing"
    pre = [{"mode": "pretip", "outcome": "refused", "error": "E", "steps": [{"step": "tags", "outcome": "refused"}]}]
    assert ri.title(oc, pre) == "Nightly run failed: pretip/tags: E"
    (tmp_path / "overlay-in.log").write_text("x\nREFUSED (overlay in): no ENGINE_COMMIT\n\n")
    oc2 = ri.parse_outcomes("state=success,overlay-in=failure,run=skipped")
    assert ri.title(oc2, [], tmp_path) == "Nightly run failed: overlay-in: REFUSED (overlay in): no ENGINE_COMMIT"
    long = [{"mode": "nightly", "outcome": "refused", "error": "y" * 500, "steps": [{"step": "hub", "outcome": "refused"}]}]
    assert len(ri.title(oc, long)) <= len("Nightly run failed: hub: ") + ri.MAX_REASON


def test_run_issue_is_standard_library_only():
    tree = ast.parse((ROOT / "scripts" / "run_issue.py").read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert names <= set(sys.stdlib_module_names)
