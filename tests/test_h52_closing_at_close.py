"""H52 (claude/HANDOFF_52_CLOSING_AT_CLOSE_2026-11-17.md; Nick, 11-17).

  A. the closing line is priced in the cloud right after Monday's window
     closes: run_guard's "closing" firings, `nightly.py --closing --scheduled`
     (the closing line, then the hub), the workflow's wiring, the season's
     firings; the 12:05 AM nightly's due() stays the fallback;
  B. the nightly goes on after a refused closing line (ClosingChanged still
     stops it), with the inputs a late close would read live pinned: the IL
     slots as at the close, output/stakes.json as at the tip, the keep
     chances' logs as of Sunday; the hub's banner; the failure issue;
  C. the NBA report's Outs for the PLAYERLIST free agents, kept in the tag
     record, so a player added after the last pre-tip record comes in with
     his Out.
Synthetic worlds and tmp_path; the season's real schedule for the firings.
No network, no league state written.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import run_guard as rg                                          # noqa: E402
import run_issue as ri                                          # noqa: E402
from modules import closing_line as cl                          # noqa: E402
from modules import nba_injury_report as nr                     # noqa: E402
from modules import nightly                                     # noqa: E402
from modules import tag_records as tr                           # noqa: E402
from modules.fetch_injury_statuses import Tags                  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
WF = ROOT / "deploy" / "state-repo" / ".github" / "workflows"


def la(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=LA)


def utc(t):
    return t.astimezone(timezone.utc)


# =============================================================================
# A synthetic guard world: week 6 opens Mon 11-23, first tip 16:00, last 19:00
# (the close 18:55)
# =============================================================================

def _tip(d: date, hh: int, mm: int = 0) -> str:
    return la(d.year, d.month, d.day, hh, mm).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


MON = date(2026, 11, 23)
CLOSE = la(2026, 11, 23, 18, 55)
FIRST = la(2026, 11, 23, 16, 0)


def guard_world(tmp_path, last=(19, 0)) -> Path:
    base = tmp_path / "engine"
    (base / "config").mkdir(parents=True)
    (base / "data").mkdir()
    (base / "config" / "league_config.json").write_text(json.dumps({
        "league_structure": {"time_zone": "America/Los_Angeles"},
        "season": {"nba_schedule_file": "data/nba_schedule_test.json"},
        "live_refresh": {"afternoon_firings": ["08:30", "11:30", "15:30"], "afternoon_lead_minutes": [30, 90],
                         "firing_tolerance_minutes": 10, "monday_poll_slots": [0, 30],
                         "afternoon_days": ["Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}}))
    (base / "config" / "SCHEDULE.json").write_text(json.dumps({"weeks": [
        {"week": 5, "start_date": "2026-11-16", "end_date": "2026-11-22"},
        {"week": 6, "start_date": "2026-11-23", "end_date": "2026-11-29"}]}))
    games = [{"date": "2026-11-23", "home": "A", "away": "B", "tip_utc": _tip(MON, 16)},
             {"date": "2026-11-23", "home": "C", "away": "D", "tip_utc": _tip(MON, *last)}]
    (base / "data" / "nba_schedule_test.json").write_text(json.dumps({"games": games}))
    return base


# =============================================================================
# A. the closing run
# =============================================================================

def test_the_first_firings_after_the_close_are_the_closing_run(tmp_path):
    base = guard_world(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    k = lambda t: rg.monday_decision(utc(t), base, state)[0]       # noqa: E731
    assert k(la(2026, 11, 23, 18, 30)) == "poll"                    # the window is open
    assert k(la(2026, 11, 23, 18, 45)) is None                      # open, not a poll slot
    assert k(la(2026, 11, 23, 19, 0)) == "closing"                  # the first firing at or after 18:55
    assert k(la(2026, 11, 23, 19, 15)) == "closing"                 # the one retry, while not on file
    assert k(la(2026, 11, 23, 19, 30)) is None                      # past the 30 minutes: 12:05 AM's job
    assert k(CLOSE) == "closing"                                    # at the close itself
    why = rg.monday_decision(utc(la(2026, 11, 23, 19, 30)), base, state)[1]
    assert "12:05 AM nightly prices week 6" in why


@pytest.mark.parametrize("kind", ["line", "none"])
def test_once_the_closing_line_or_its_none_record_is_on_file_later_firings_do_nothing(tmp_path, kind):
    base = guard_world(tmp_path)
    state = tmp_path / "state"
    (state / "output").mkdir(parents=True)
    (state / "output" / f"closing_{kind}_week6.json").write_text("{}")
    kind_, why = rg.monday_decision(utc(la(2026, 11, 23, 19, 15)), base, state)
    assert kind_ is None and "settled" in why
    # another week's file is not this week's
    other = tmp_path / "other"
    (other / "output").mkdir(parents=True)
    (other / "output" / "closing_line_week5.json").write_text("{}")
    assert rg.monday_decision(utc(la(2026, 11, 23, 19, 0)), base, other)[0] == "closing"


def test_the_close_is_derived_from_the_last_tip_every_week(tmp_path):
    base = guard_world(tmp_path, last=(16, 0))                      # one game: close 15:55, first tip 16:00
    state = tmp_path / "s"
    state.mkdir()
    assert rg.monday_decision(utc(la(2026, 11, 23, 15, 30)), base, state)[0] == "pretip"
    assert rg.monday_decision(utc(la(2026, 11, 23, 16, 0)), base, state)[0] == "closing"
    late = guard_world(tmp_path / "late", last=(19, 30))            # close 19:25
    assert rg.monday_decision(utc(la(2026, 11, 23, 19, 15)), late, state)[0] is None
    assert rg.monday_decision(utc(la(2026, 11, 23, 19, 30)), late, state)[0] == "closing"


def test_the_guard_files_are_closing_lines(tmp_path):
    assert rg.CLOSING_REL.format(week=6) == cl.closing_path(".", 6).as_posix()
    assert rg.CLOSING_NONE_REL.format(week=6) == cl.none_path(".", 6).as_posix()


def test_the_guard_cli_writes_closing_for_the_workflow(tmp_path, monkeypatch):
    base = guard_world(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    out = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert rg.main(["pretip", "--base-path", str(base), "--state-dir", str(state),
                    "--now", utc(la(2026, 11, 23, 19, 0)).isoformat()]) == 0
    assert out.read_text().splitlines() == ["go=false", "poll=false", "closing=true"]


def _plan_firings(day: date) -> list:
    plan = json.loads((ROOT / "deploy/state-repo/cron-job-org.json").read_text(encoding="utf-8"))
    j = next(x for x in plan["jobs"] if x["name"] == "Pre-tip")
    assert plan["time_zone"] == "America/Los_Angeles" and "Mon" in j["days"]
    h0, m0 = (int(x) for x in j["from"].split(":"))
    h1, m1 = (int(x) for x in j["to"].split(":"))
    t, end, out = la(day.year, day.month, day.day, h0, m0), la(day.year, day.month, day.day, h1, m1), []
    while t <= end:
        out.append(t)
        t += timedelta(minutes=int(j["every_minutes"]))
    return out


@pytest.mark.slow
def test_every_window_monday_of_the_season_gets_two_closing_firings(tmp_path):
    """The existing pre-tip job (every 15 minutes to 19:45 Pacific) carries the
    closing run: on every window Monday with games, exactly two of its firings
    are the closing run with no closing line on file. The season's latest close
    is 19:25 (19:30 and 19:45 fire)."""
    empty = tmp_path / "no_state"
    empty.mkdir()
    days = [d for d in rg.window_days(ROOT) if d.isoweekday() == 1 and rg.tip_times(ROOT, d)]
    assert len(days) >= 20
    for d in days:
        kinds = [(t, rg.monday_decision(utc(t), ROOT, empty)[0]) for t in _plan_firings(d)]
        closing = [t for t, k in kinds if k == "closing"]
        close = rg.window_open(ROOT, d)[1]
        assert len(closing) == 2 and all(close <= t < close + rg.CLOSING_ADMIT for t in closing), (d, closing)


def test_the_workflow_runs_the_closing_kind_as_the_closing_run():
    run = yaml.safe_load((WF / "run.yml").read_text(encoding="utf-8"))
    guard = run["jobs"]["guard"]
    assert "steps.guard.outputs.closing == 'true'" in guard["outputs"]["go"]
    assert "steps.guard.outputs.closing == 'true' && 'closing'" in guard["outputs"]["kind"]
    sparse = guard["steps"][0]["with"]["sparse-checkout"]
    assert "/output/closing_line_week*.json" in sparse and "/output/closing_none_week*.json" in sparse
    steps = {s.get("id"): s for s in run["jobs"]["run"]["steps"] if s.get("id")}
    assert 'elif [ "$MODE" = pretip ] && [ "$KIND" = closing ]; then\n  set -- --closing --scheduled' \
        in steps["run"]["run"]
    close = next(s for s in run["jobs"]["run"]["steps"] if s.get("name") == "Close the failure issue")
    assert "needs.guard.outputs.kind != 'closing'" in close["if"]
    assert "steps.run.outputs.closing_refused != 'true'" in close["if"]
    opened = next(s for s in run["jobs"]["run"]["steps"] if s.get("name") == "Open or comment on the failure issue")
    assert opened["if"] == "failure() || steps.run.outputs.closing_refused == 'true'"


def test_closing_scheduled_takes_no_week_and_closing_alone_needs_one():
    with pytest.raises(SystemExit):
        nightly.main(["--closing", "--scheduled", "--week", "6"])
    with pytest.raises(SystemExit):
        nightly.main(["--closing"])


def test_the_closing_run_with_the_hub_runs_the_closing_steps_then_actuals_and_the_hub():
    r = nightly.Run(".", "closing", week=6, now=la(2026, 11, 23, 19, 0), with_hub=True, echo=lambda *a: None)
    assert r.steps() == ("engine", "window", "sync", "closing", "actuals", "hub")
    assert nightly.Run(".", "closing", week=6, now=la(2026, 11, 23, 19, 0), echo=lambda *a: None).steps() \
        == ("engine", "window", "sync", "closing")
    with pytest.raises(ValueError, match="with_hub"):
        nightly.Run(".", "nightly", with_hub=True)


@pytest.mark.parametrize("outcome,code,ran", [("not due", 0, "false"), ("ok", 0, "true"),
                                              ("refused", 1, "false"), ("none recorded", 0, "false")])
def test_closing_scheduled_exits_and_publishes_by_its_outcome(monkeypatch, tmp_path, outcome, code, ran):
    out = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    seen = {}

    def fake(base, **k):
        seen.update(k)
        if outcome == "not due":
            return {"week": None, "outcome": "not due", "row": None}
        return {"week": 6, "outcome": outcome, "exception": None,
                "row": {"seconds": 40.0, "error": None if outcome == "ok" else "ClosingRefused: x"}}
    monkeypatch.setattr(nightly, "scheduled_closing", fake)
    assert nightly.main(["--closing", "--scheduled"]) == code
    assert seen["with_hub"] is True
    assert out.read_text().splitlines() == [f"ran={ran}"]


# =============================================================================
# B. the nightly goes on after a refused closing line
# =============================================================================

def _night(monkeypatch, tmp_path, result):
    monkeypatch.setattr(nightly, "scheduled_guard_decision", lambda now, base=".": (True, "test"))
    marked, runs = [], []
    monkeypatch.setattr(nightly, "record_night", lambda base, row, ok, now=None: marked.append(ok))
    monkeypatch.setattr(nightly, "scheduled_closing", lambda *a, **k: result)

    def execute(self, steps=None):
        runs.append(dict(self.ctx))
        return {"outcome": "ok", "exit": 0, "seconds": 90.0, "error": None}
    monkeypatch.setattr(nightly.Run, "execute", execute)
    out = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    code = nightly.main(["--scheduled"])
    return code, marked, runs, out.read_text().splitlines() if out.exists() else []


def test_a_refused_closing_line_is_recorded_loudly_and_the_night_goes_on(monkeypatch, tmp_path, capsys):
    code, marked, runs, gh = _night(monkeypatch, tmp_path, {
        "week": 6, "outcome": "refused", "exception": cl.ClosingRefused("no pre-tip copy"),
        "row": {"run_id": "r-closing", "seconds": 3.0, "error": "ClosingRefused: no pre-tip copy"}})
    assert code == 0 and marked == [True] and len(runs) == 1        # the night ran, and counts as good
    assert runs[0]["closing_block"] == {"week": 6, "outcome": "refused", "run_id": "r-closing",
                                        "error": "ClosingRefused: no pre-tip copy"}
    assert "closing_refused=true" in gh and "ran=true" in gh        # the failure issue opens; the hub publishes
    assert "CLOSING LINE REFUSED" in capsys.readouterr().out


def test_closing_changed_still_stops_everything(monkeypatch, tmp_path):
    code, marked, runs, gh = _night(monkeypatch, tmp_path, {
        "week": 6, "outcome": "refused", "exception": cl.ClosingChanged("different bytes"),
        "row": {"run_id": "r", "seconds": 3.0, "error": "ClosingChanged: different bytes"}})
    assert code == 1 and marked == [False] and runs == [] and "closing_refused=true" not in gh


def test_the_next_night_retries_it_first(monkeypatch, tmp_path):
    """due() keeps offering the week (test_cloud_run pins due); the night
    after a refusal starts with it, and a priced one is the night's block."""
    code, marked, runs, gh = _night(monkeypatch, tmp_path, {
        "week": 6, "outcome": "ok", "exception": None,
        "row": {"run_id": "r2", "seconds": 35.0, "error": None}})
    assert code == 0 and runs[0]["closing_block"]["outcome"] == "ok" and "closing_refused=true" not in gh


def test_the_nightly_row_carries_the_closing_block(tmp_path):
    r = nightly.Run(tmp_path, "nightly", now=la(2026, 11, 24, 0, 5), echo=lambda *a: None)
    r.ctx["closing_block"] = {"week": 6, "outcome": "refused", "run_id": "x", "error": "e"}
    row = r.execute(steps={n: (lambda: "ok") for n in r.steps()})
    assert row["closing"]["outcome"] == "refused"


def test_the_failure_issue_names_a_refused_closing_when_the_night_went_on():
    rows = [{"mode": "closing", "outcome": "refused", "error": "ClosingRefused: x",
             "steps": [{"step": "closing", "outcome": "refused"}]},
            {"mode": "nightly", "outcome": "ok", "steps": []}]
    assert ri.title([("run", "success")], rows) == \
        "Closing line refused (the night went on): closing/closing: ClosingRefused: x"
    assert ri.title([("run", "failure")], rows[:1]).startswith("Nightly run failed: closing/closing")


# --- the hub's banner ---------------------------------------------------------

def _banner_world(tmp_path, refused_weeks=(6,), settled=(5,)):
    weeks = [{"week": w, "start_date": (date(2026, 11, 16) + timedelta(days=7 * (w - 5))).isoformat()}
             for w in (5, 6, 7)]
    games = []
    for w in weeks:
        d = date.fromisoformat(w["start_date"])
        games += [{"date": f"{d}", "home": "A", "away": "B", "tip_utc": _tip(d, 16)},
                  {"date": f"{d}", "home": "C", "away": "D", "tip_utc": _tip(d, 19)}]
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    for w in settled:
        cl.closing_path(tmp_path, w).write_text("{}")
    rows = [{"run_id": f"c{w}", "mode": "closing", "week": w, "outcome": "refused",
             "error": f"ClosingRefused: week {w} problem"} for w in refused_weeks]
    (tmp_path / nightly.RUNS_FILE).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return SimpleNamespace(schedule={"weeks": weeks}, nba_schedule={"games": games})


def test_the_hub_banner_names_a_refused_closing_line(tmp_path):
    w = _banner_world(tmp_path)
    assert cl.refusal_note(tmp_path, la(2026, 11, 23, 18, 0), w) == ""          # before the close
    note = cl.refusal_note(tmp_path, la(2026, 11, 24, 0, 30), w)
    assert note.startswith("Week 6's closing line refused: ClosingRefused: week 6 problem.")
    cl.closing_path(tmp_path, 6).write_text("{}")
    assert cl.refusal_note(tmp_path, la(2026, 11, 24, 0, 30), w) == ""          # priced: gone


def test_a_week_left_unsettled_when_the_next_window_closes_is_named(tmp_path):
    """due() only offers the latest closed week: once week 7 closes, week 6 is
    never retried. The banner says so instead of dropping it silently."""
    w = _banner_world(tmp_path, refused_weeks=(6,))
    note = cl.refusal_note(tmp_path, la(2026, 11, 30, 19, 30), w)
    assert "Week 6's closing line was never priced" in note and "--no-closing-line --week 6" in note
    assert cl.closed_unsettled(tmp_path, la(2026, 11, 30, 19, 30), w) == [6, 7]


def test_the_hub_page_shows_the_banner():
    from modules import hub_page
    import inspect
    src = inspect.getsource(hub_page)
    assert 'h.get("closing_note")' in src
    from modules import hub_state
    assert '"closing_note": closing_note' in inspect.getsource(hub_state.build)


# --- the pinned inputs ----------------------------------------------------------

def _il(base, fetched, week=6, slots=None):
    p = base / "data" / "IL_SLOTS.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"fantasy_week": week, "slots": slots or {"Nick": ["A"]},
                             "fetched_at": fetched.isoformat(timespec="seconds")}))


def test_the_il_slots_are_kept_as_at_the_close_and_a_tuesday_change_does_not_leak(tmp_path):
    _il(tmp_path, la(2026, 11, 23, 18, 0))                                       # before the close
    assert "not kept" in cl.capture_il_at_close(tmp_path, 6, CLOSE)
    with pytest.raises(cl.ClosingRefused, match="IL_SLOTS_week06.json is missing"):
        cl.il_at_close(tmp_path, 6, CLOSE)
    _il(tmp_path, la(2026, 11, 23, 19, 1), slots={"Nick": ["A"]})                # the closing run's sync
    assert "-> config/snapshots/close/IL_SLOTS_week06.json" in cl.capture_il_at_close(tmp_path, 6, CLOSE)
    _il(tmp_path, la(2026, 11, 25, 0, 5), slots={"Nick": ["B"]})                 # Tuesday's IL move, synced
    assert "already kept" in cl.capture_il_at_close(tmp_path, 6, CLOSE)         # never overwritten
    got = cl.il_at_close(tmp_path, 6, CLOSE)
    assert got["blob"]["slots"] == {"Nick": ["A"]} and got["fetched_at"] == la(2026, 11, 23, 19, 1)
    _il(tmp_path / "w7", la(2026, 11, 30, 19, 1), week=7)
    assert "not 6" in cl.capture_il_at_close(tmp_path / "w7", 6, CLOSE)


def test_the_closing_run_keeps_the_il_after_its_sync(tmp_path, monkeypatch):
    import sync_transactions as st
    monkeypatch.setattr(st, "nightly_sync", lambda base, **k: {"week": 6, "log": {"appended": 0, "total": 1},
                                                              "counts": []})
    r = nightly.Run(tmp_path, "closing", week=6, now=la(2026, 11, 23, 19, 1), echo=lambda *a: None)
    r.ctx["window_close"] = CLOSE
    _il(tmp_path, la(2026, 11, 23, 19, 1))
    assert "IL slots at week 6's close" in r.step_sync()
    assert cl.il_close_path(tmp_path, 6).is_file() and "il_at_close" in r.ctx


def _stakes(path, as_of, week=6):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 3, "week": week, "as_of": as_of.isoformat(timespec="seconds"),
                                "teams": {}}))


def test_the_stakes_are_read_as_at_the_tip(tmp_path, monkeypatch):
    live = tmp_path / "output" / "stakes.json"
    _stakes(live, la(2026, 11, 23, 15, 30))                                     # the pre-tip run's
    got = cl.stakes_at_tip(tmp_path, 6, FIRST)
    assert got["source"] == "live" and got["as_of"] == la(2026, 11, 23, 15, 30)
    cl_copy = cl.pretip_stakes_path(tmp_path, 6)
    _stakes(cl_copy, la(2026, 11, 23, 15, 30))
    _stakes(live, la(2026, 11, 23, 18, 36))                                     # Step 6's weekly build
    got = cl.stakes_at_tip(tmp_path, 6, FIRST)
    assert got["source"] == "pretip copy" and got["rel"] == "config/snapshots/pretip/stakes_week06.json"
    cl_copy.unlink()
    with pytest.raises(cl.ClosingRefused, match="no stakes file as at Monday's first tip"):
        cl.stakes_at_tip(tmp_path, 6, FIRST)


def test_the_pretip_runs_keep_the_stakes(tmp_path, monkeypatch):
    from modules import price_lock
    monkeypatch.setattr(price_lock, "first_tip", lambda day, sched: FIRST if day == MON else None)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps({"weeks": [
        {"week": 6, "start_date": "2026-11-23", "end_date": "2026-11-29"}]}))
    import modules.closing_line as m
    monkeypatch.setattr("modules.data_loader.load_nba_schedule", lambda *a, **k: {"games": []})
    monkeypatch.setattr("modules.data_loader.load_schedule", lambda p: json.loads(Path(p).read_text()))
    live = tmp_path / "output" / "stakes.json"
    _stakes(live, la(2026, 11, 23, 0, 5))
    assert "-> config/snapshots/pretip/stakes_week06.json" in m.capture_pretip_stakes(tmp_path, la(2026, 11, 23, 0, 5))
    _stakes(live, la(2026, 11, 23, 15, 30))
    m.capture_pretip_stakes(tmp_path, la(2026, 11, 23, 15, 30))
    assert json.loads(cl.pretip_stakes_path(tmp_path, 6).read_text())["as_of"].startswith("2026-11-23T15:30")
    _stakes(live, la(2026, 11, 23, 18, 36))
    assert "after the first tip" in m.capture_pretip_stakes(tmp_path, la(2026, 11, 23, 18, 36))
    assert json.loads(cl.pretip_stakes_path(tmp_path, 6).read_text())["as_of"].startswith("2026-11-23T15:30")
    assert "not a window day" in m.capture_pretip_stakes(tmp_path, la(2026, 11, 24, 0, 5))


def test_the_plan_reads_the_stakes_file_the_closing_line_names(tmp_path, monkeypatch):
    from modules import drop_inputs as di
    seen = []
    monkeypatch.setattr(di, "read_stakes", lambda base, season=None, path=None: seen.append(path) or (None, "n"))
    data = SimpleNamespace(stakes_file=tmp_path / "copy.json")
    ctx = di.context(data, tmp_path, keep_week=5)
    assert ctx.note() == "n" and seen == [tmp_path / "copy.json"]
    seen.clear()
    di.context(SimpleNamespace(), tmp_path, keep_week=5).note()
    assert seen == [None]                                                      # every other run: the live file


def test_the_keep_chances_read_the_logs_as_of_sunday(monkeypatch):
    import rollup_season_to_history as R
    from modules import keeper_history as kh
    rows = [{"date": d, "manager": "Nick", "player_name": "A"} for d in
            ("2026-11-21", "2026-11-22", "2026-11-23", "2026-11-24")]
    monkeypatch.setattr(R, "build_rows", lambda season, flat, *a, **k: ([dict(r) for r in rows], {}))
    hist = kh.Inputs(log={}, picks={}, trades=[])
    li, season = kh.live_inputs(ROOT, hist, before=date(2026, 11, 23))
    assert [r["date"] for r in li.log[season]] == ["2026-11-21", "2026-11-22"]
    li, season = kh.live_inputs(ROOT, hist)
    assert len(li.log[season]) == 4                                            # every other reader: uncut


def test_the_closing_lines_data_carries_sunday_and_the_keep_chances_pass_it(monkeypatch):
    import pandas as pd
    from modules import drop_inputs as di, keepability_v3 as kv3
    data = SimpleNamespace(lineups=pd.DataFrame({"date": ["2026-11-22", "2026-11-23"]}),
                           playerlog=pd.DataFrame({"date": ["2026-11-22", "2026-11-23"], "week": [5, 6]}))
    out = cl.pre_close_data(".", MON, data)
    assert out.logs_before == MON and list(out.playerlog["date"]) == ["2026-11-22"]
    got = []
    monkeypatch.setattr(kv3, "keeper_watch", lambda d, w, root=None, logs_before=None: got.append(logs_before)
                        or {"players": []})
    di.keep_chances(out, ".", 6)
    assert got == [MON]


def test_the_closing_line_prices_on_the_pins_and_the_close_as_its_clock():
    import inspect
    src = inspect.getsource(cl.price)
    for want in ("il = il_at_close(base, week, close)", "stakes = stakes_at_tip(base, week, first)",
                 "data.plan_now = close", "pass_data.plan_now = close", "data.il_slots =",
                 "pass_data.il_slots =", "data.stakes_file = stakes[\"path\"]",
                 "pass_data.stakes_file = stakes[\"path\"]", '"il_slots": {"file": il["rel"]',
                 '"stakes": {"file": stakes["rel"]'):
        assert want in src, want
    assert "plan_now = now" not in src


# =============================================================================
# C. the NBA report's Outs for the free agents
# =============================================================================

def _entry(player, status="Out", day="2026-11-23"):
    last, first = player.split(" ", 1)[1], player.split(" ", 1)[0]
    return {"game_date": day, "game_time": "07:00 (ET)", "matchup": "PHX@BOS", "team": "Phoenix Suns",
            "name": f"{last}, {first}", "player": player, "status": status, "reason": ""}


CFG = {"stale_hours": 30}


def _assess(entries, tags, out_today=lambda n: False):
    known = {"Devin Booker": "PHX", "Fa Tagged": "PHX", "Rostered Guy": "PHX", "Fa Entry": "PHX"}
    return nr.assess({"filed_at": "2026-11-23T13:00-05:00", "entries": entries}, tags,
                     {"Nick": ["Rostered Guy"]}, out_today, MON, known, now=la(2026, 11, 23, 15, 30), cfg=CFG)


def test_a_free_agents_out_is_recorded_beside_his_tag():
    tags = Tags({"Rostered Guy": "Q"}, {"Devin Booker": "HEALTHY", "Fa Tagged": "O", "Fa Entry": "Q"})
    a = _assess([_entry("Devin Booker"), _entry("Fa Tagged"), _entry("Rostered Guy"), _entry("Fa Entry")],
                tags, out_today=lambda n: n == "Fa Entry")
    assert a["fa_applied"] == {"Devin Booker": "2026-11-23"}          # O already, or an entry: covered
    assert a["applied"] == {"Rostered Guy": "2026-11-23"}             # the rostered rule, unchanged
    assert [f["player"] for f in a["flags"]] == ["Rostered Guy"]      # no flag, no issue for a free agent
    assert "fa_applied" in _assess([], Tags({}, {}))


def test_the_record_keeps_the_free_agents_outs_and_an_older_record_reads_none(tmp_path):
    t = Tags({"A": "Q"}, {"Devin Booker": "HEALTHY"}, nba_outs={"A": "2026-11-23"},
             free_agent_nba_outs={"Devin Booker": "2026-11-23"})
    back = Tags.from_json(t.to_json())
    assert back.free_agent_nba_outs == {"Devin Booker": "2026-11-23"} and back.nba_outs == {"A": "2026-11-23"}
    old = {"rostered": {"A": "Q"}, "free_agents": {"Devin Booker": "HEALTHY"}, "free_agents_assumed_healthy": False}
    assert Tags.from_json(old).free_agent_nba_outs == {}
    assert "free_agent_nba_outs" not in Tags({"A": "Q"}, {}).to_json()


def test_the_nightly_report_step_records_the_free_agents_outs(tmp_path, monkeypatch):
    run = nightly.Run(tmp_path, "pretip", now=la(2026, 11, 23, 15, 30), echo=lambda *a: None)
    run.week = 6
    run.ctx["tags"] = Tags({"Rostered Guy": "HEALTHY"}, {"Devin Booker": "HEALTHY"})
    monkeypatch.setattr(nr, "read_and_store", lambda *a, **k: None)
    monkeypatch.setattr(nr, "latest", lambda base: {"attempt": {"outcome": "ok", "filed_at": "x"},
                                                   "report": {"filed_at": "2026-11-23T13:00-05:00"}})
    monkeypatch.setattr(nightly.Run, "_assess_report", lambda self, nr_, rep, tags: {
        "applied": {}, "fa_applied": {"Devin Booker": "2026-11-23"}, "flags": [], "loud": [], "unresolved": [],
        "covered": [], "stale": None})
    monkeypatch.setattr(nr, "summary", lambda *a: "NBA report")
    monkeypatch.setattr(nightly.Run, "_capture_pretip_playerlist", lambda self: "copy")
    run.step_nba_report()
    rec = tr.read(tmp_path)[-1]["tags"]
    assert rec["free_agent_nba_outs"] == {"Devin Booker": "2026-11-23"} and "nba_outs" not in rec


def test_a_430pm_add_who_was_out_on_the_report_is_out_monday_in_the_closing_line():
    """H51 s.1.2: Booker added 3:45-4:30 PM, after the last pre-tip record, Out on
    the NBA's report with no O from Yahoo. His Out comes in with his tag."""
    rec = Tags({"Mobley": "O"}, {"Devin Booker": "HEALTHY"}, free_agent_nba_outs={"Devin Booker": "2026-11-23"})
    out, left, joined = cl.align_to_close(Tags.from_json(rec.to_json()), ["Devin Booker", "Other"])
    assert joined == ["Devin Booker"] and dict(out)["Devin Booker"] == "HEALTHY"
    assert out.nba_outs == {"Devin Booker": "2026-11-23"}               # out Monday: what the line reads
    # and the dropped player's own Out goes with him to the free agents
    rec2 = Tags({"Gone": "Q"}, {}, nba_outs={"Gone": "2026-11-23"})
    out2, _l, _j = cl.align_to_close(rec2, ["Other"])
    assert out2.nba_outs == {} and out2.free_agent_nba_outs == {"Gone": "2026-11-23"}


def test_an_older_record_brings_no_out_in():
    rec = {"rostered": {"Mobley": "O"}, "free_agents": {"Devin Booker": "HEALTHY"},
           "free_agents_assumed_healthy": False}
    out, _left, joined = cl.align_to_close(Tags.from_json(rec), ["Devin Booker"])
    assert joined == ["Devin Booker"] and out.nba_outs == {}


def test_an_added_players_out_is_a_certain_miss_of_mondays_game():
    """Through the simulator: the closing line's tags after align_to_close."""
    import numpy as np
    from modules import simulator_betting as sb
    from modules.projections import TeamProjections
    from test_absence import MWF, MON as TMON, _betting_data, _proj
    rec = Tags({}, {"A": "HEALTHY"}, free_agent_nba_outs={"A": MWF[0].isoformat()})
    tags, _l, _j = cl.align_to_close(rec, ["A"])
    data = _betting_data({"BOS": MWF})
    teams = {"Nick": TeamProjections("Nick", {"A": _proj("A", "BOS")})}
    blk = sb.tag_blocks(data, teams, dict(tags), sb.KeyedDraws(7, 2000), TMON, nba_outs=tags.nba_outs)["A"]
    assert blk.forced == frozenset({MWF[0]})
    miss = ~sb.entry_available(len(blk.k), (None,) * 4 + (None, None, None, True), MWF[0], None, blk, None)
    assert np.asarray(miss).all()
