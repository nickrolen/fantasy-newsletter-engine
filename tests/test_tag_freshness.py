"""Step 3b, tag freshness (claude/HANDOFF_STEP3B_TAG_FRESHNESS_2026-11-10.md).

  1. Monday-window polling (scripts/run_guard.monday_decision, scripts/monday_poll.py,
     nightly --poll)
  2. the afternoon tag check (run_guard.afternoon_plan / admits_afternoon, nightly --afternoon)
  3. the O-past-3-games nudge (modules/o_nudge, scripts/flag_issues.py)
  4. the NBA's official injury report (modules/nba_injury_report; Tags.nba_outs through
     the simulator; the flag)
  5. the grid's tag display (hub_state.Availability.grid_status, build_grid_tab, hub_page)
  6. causes; the Actions minutes (scripts/actions_minutes.py)
Nothing here reads league state or the network: synthetic worlds, tmp_path, the
engine's own schedule and config, and one stored real report (tests/fixtures).
"""
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import actions_minutes as am                      # noqa: E402
import flag_issues as fi                          # noqa: E402
import monday_poll as mp                          # noqa: E402
import run_guard as rg                            # noqa: E402
from modules import absence, nightly, o_nudge, price_lock      # noqa: E402
from modules import hub_state as hs                            # noqa: E402
from modules import nba_injury_report as nr                    # noqa: E402
from modules import simulator_betting as sb                    # noqa: E402
from modules import week_state as ws                           # noqa: E402
from modules.data_loader import load_nba_schedule              # noqa: E402
from modules.fetch_injury_statuses import Tags                 # noqa: E402
from modules.projections import TeamProjections                # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
FIXTURE = ROOT / "tests" / "fixtures" / "nba_injury_report" / "Injury-Report_2026-11-10_05_00PM.pdf"


def la(d: date, hh: int, mm: int) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=LA)


def utc(t: datetime) -> datetime:
    return t.astimezone(timezone.utc)


def nba_schedule():
    rel, = [json.loads((ROOT / "config/league_config.json").read_text())["season"]["nba_schedule_file"]]
    root, path = rg.schedule_file(ROOT)
    return json.loads((root / path).read_text(encoding="utf-8"))


def tips(day: date) -> list:
    out = []
    for g in nba_schedule()["games"]:
        if str(g["date"])[:10] == day.isoformat() and g.get("tip_utc"):
            out.append(datetime.strptime(g["tip_utc"], "%Y-%m-%dT%H:%M:%SZ")
                       .replace(tzinfo=timezone.utc).astimezone(LA))
    return sorted(out)


def window_mondays():
    return [d for d in rg.window_days(ROOT) if tips(d)]


# =============================================================================
# 1. Monday-window polling
# =============================================================================

def firings(day: date):
    t = la(day, 7, 0)
    while t <= la(day, 19, 45):
        yield t
        t += timedelta(minutes=15)


def expected_kind(t: datetime):
    """The rule, written out apart from run_guard: pre-tip in [first - 45, first);
    else a poll on the :00/:30 firings while the window is open (12:01 AM to the
    last tip - 5 min); else nothing."""
    ts = tips(t.date())
    first, last = ts[0], ts[-1]
    if first - timedelta(minutes=45) <= t < first:
        return "pretip"
    if la(t.date(), 0, 1) <= t < last - timedelta(minutes=5) and t.minute in (0, 30):
        return "poll"
    return None


def test_the_poll_and_pretip_split_across_every_window_monday_of_the_season():
    mons = window_mondays()
    assert len(mons) >= 20
    for d in mons:
        kinds = [(t, rg.monday_decision(utc(t), ROOT, ROOT)[0]) for t in firings(d)]
        assert [k for _, k in kinds] == [expected_kind(t) for t, _ in kinds], d
        # at most one poll every 30 minutes, and three pre-tip firings when the
        # window opens after 07:45 (the earliest pre-tip firing is 07:00)
        polls = [t for t, k in kinds if k == "poll"]
        assert all(b - a >= timedelta(minutes=30) for a, b in zip(polls, polls[1:])), d
        assert sum(k == "pretip" for _, k in kinds) == 3, d
        assert all(t < tips(d)[-1] - timedelta(minutes=5) for t in polls), d


@pytest.mark.parametrize("holiday", [date(2027, 1, 18), date(2027, 2, 15)])
def test_the_holiday_mondays_with_a_9_am_tip(holiday):
    assert tips(holiday)[0].strftime("%H:%M") == "09:00"
    k = {t.strftime("%H:%M"): rg.monday_decision(utc(t), ROOT, ROOT)[0] for t in firings(holiday)}
    assert [k["07:00"], k["07:30"], k["08:00"]] == ["poll"] * 3
    assert [k["08:15"], k["08:30"], k["08:45"]] == ["pretip"] * 3
    assert k["09:00"] == "poll" and k["09:15"] is None


def test_no_poll_outside_the_window():
    tue = date(2026, 11, 17)
    assert all(rg.monday_decision(utc(t), ROOT, ROOT)[0] is None for t in firings(tue))
    mon = date(2026, 11, 16)
    close = tips(mon)[-1] - timedelta(minutes=5)
    after = [t for t in firings(mon) if t >= close]
    assert after and all(rg.monday_decision(utc(t), ROOT, ROOT)[0] is None for t in after)
    # a late firing still reads as its own slot, never as two
    assert rg.monday_decision(utc(la(mon, 10, 13)), ROOT, ROOT)[0] == "poll"
    assert rg.monday_decision(utc(la(mon, 10, 16)), ROOT, ROOT)[0] is None


def test_the_window_close_is_price_locks():
    assert rg.WINDOW_CLOSE_BEFORE_LAST_TIP == price_lock.WINDOW_CLOSE_BEFORE_LAST_TIP


def _log(tmp_path, keys):
    p = tmp_path / "data" / "transaction_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps({"row": "transaction", "key": k}) + "\n" for k in keys))


def test_a_poll_with_nothing_new_says_go_false(tmp_path, monkeypatch):
    _log(tmp_path, ["478.l.1.tr.1", "478.l.1.tr.2"])
    out = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    fetch = lambda oauth, key: [{"transaction_key": "478.l.1.tr.2"}, {"transaction_key": "478.l.1.tr.1"}]
    assert mp.main(["--base-path", str(ROOT), "--state-dir", str(tmp_path), "--oauth", "x"], fetch) == 0
    assert out.read_text().splitlines() == ["go=false", "new=0"]
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["gh", "transaction_log.jsonl"]


def test_a_poll_with_a_new_transaction_says_go_true(tmp_path, monkeypatch):
    _log(tmp_path, ["478.l.1.tr.1"])
    out = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    fetch = lambda oauth, key: [{"transaction_key": "478.l.1.tr.3"}, {"transaction_key": "478.l.1.tr.1"}]
    assert mp.main(["--base-path", str(ROOT), "--state-dir", str(tmp_path), "--oauth", "x"], fetch) == 0
    assert out.read_text().splitlines() == ["go=true", "new=1"]


def test_the_poll_refuses_rather_than_guess(tmp_path):
    with pytest.raises(mp.PollError, match="missing"):
        mp.logged_keys(tmp_path)
    with pytest.raises(mp.PollError, match="no key"):
        mp.new_transactions([{"type": "add"}], set())
    assert mp.main(["--base-path", str(ROOT), "--state-dir", str(tmp_path), "--oauth", "x"],
                   lambda *a: []) == 1


def test_the_poll_imports_only_the_standard_library_and_the_yahoo_clients():
    src = (ROOT / "scripts" / "monday_poll.py").read_text()
    mods = set(re.findall(r"^\s*(?:from|import)\s+([a-z_]+)", src, re.M))
    assert mods <= {"__future__", "argparse", "json", "os", "sys", "pathlib", "yahoo_oauth",
                    "yahoo_fantasy_api"}, mods
    assert "modules" not in src.split('"""', 2)[2]


TX = [
    {"row": "transaction", "key": "k1", "id": 1, "type": "add/drop", "status": "successful",
     "timestamp": 1, "time": "2026-11-16T09:00:00-08:00", "league_day": "2026-11-16", "rulings": [],
     "players": [{"name": "PJ Washington", "action": "add", "from": {"type": "freeagents"},
                  "to": {"manager": "Benton"}},
                 {"name": "Paul George", "action": "drop", "from": {"manager": "Benton"},
                  "to": {"type": "waivers"}}]},
    {"row": "transaction", "key": "k2", "id": 2, "type": "trade", "status": "successful",
     "timestamp": 2, "time": "2026-11-16T09:10:00-08:00", "league_day": "2026-11-16", "rulings": [],
     "players": [{"name": "A One", "action": "trade", "from": {"manager": "Nick"}, "to": {"manager": "Hayden"}},
                 {"name": "B Two", "action": "trade", "from": {"manager": "Hayden"}, "to": {"manager": "Nick"}}]},
]


def test_the_poll_cause_is_built_from_the_transactions():
    assert nightly.moves_cause(TX[:1]) == "Monday move: Benton added PJ Washington, dropped Paul George"
    assert nightly.moves_cause(TX) == ("Monday moves: Benton added PJ Washington, dropped Paul George; "
                                       "trade: Hayden sends B Two to Nick; Nick sends A One to Hayden")


def _poll_world(tmp_path, new_keys, calls):
    p = tmp_path / "data" / "transaction_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(t) + "\n" for t in TX))
    run = nightly.Run(tmp_path, "poll", now=la(date(2026, 11, 16), 9, 30), echo=lambda *a: None)

    def sync():
        run.ctx["sync"] = {"log": {"new_keys": list(new_keys)}}
        run.week = 5

    def spy(name):
        def f():
            calls.append((name, run.cause))
        return f
    steps = {"engine": lambda: None, "banked": lambda: None, "sync": sync}
    for n in ("settings", "tags", "nba_report", "ledger", "line", "title_odds", "actuals", "hub"):
        steps[n] = spy(n)
    return run, steps


def test_a_new_transaction_refreshes_with_its_cause(tmp_path):
    calls = []
    run, steps = _poll_world(tmp_path, ["k1"], calls)
    row = run.execute(steps)
    assert row["outcome"] == "ok" and row["mode"] == "poll"
    assert row["cause"] == "Monday move: Benton added PJ Washington, dropped Paul George"
    assert ("line", row["cause"]) in calls and ("title_odds", row["cause"]) in calls


def test_a_poll_whose_sync_found_nothing_new_prices_nothing(tmp_path):
    calls = []
    run, steps = _poll_world(tmp_path, [], calls)
    row = run.execute(steps)
    assert row["outcome"] == "nothing new" and row["exit"] == 0 and calls == []


def test_poll_and_afternoon_name_their_own_cause():
    for mode in ("poll", "afternoon"):
        with pytest.raises(ValueError, match="names its own cause"):
            nightly.Run(".", mode, cause="x", now=la(date(2026, 11, 16), 9, 0))


def test_a_locked_poll_prices_nothing_and_counts_as_a_change_waiting(tmp_path, monkeypatch):
    assert "poll" in nightly.REFRESH_MODES and "afternoon" in nightly.REFRESH_MODES
    src = Path(nightly.__file__).read_text()
    assert "if self.mode in REFRESH_MODES:\n            # the lock is judged here" in src
    assert 'r.get("mode") in ("refresh", "poll", "afternoon") and r.get("outcome") == "locked"' \
        in Path(hs.__file__).read_text()


# =============================================================================
# 2. the afternoon tag check
# =============================================================================

def test_the_firings_are_the_cron_job_org_jobs_times():
    cfg = json.loads((ROOT / "config/league_config.json").read_text())["live_refresh"]
    job = am.job(ROOT, "Afternoon tags")
    assert job["times"] == cfg["afternoon_firings"] and len(job["times"]) <= 3
    assert job["days"] == cfg["afternoon_days"] and "Mon" not in job["days"] and len(job["days"]) == 6
    assert job["workflow"] == "afternoon.yml"


def game_days():
    sched = json.loads((ROOT / "config/SCHEDULE.json").read_text())["weeks"]
    a, b = date.fromisoformat(sched[0]["start_date"][:10]), date.fromisoformat(sched[-1]["end_date"][:10])
    d = a
    while d <= b:
        if tips(d):
            yield d
        d += timedelta(days=1)


def test_guard_admission_across_the_seasons_real_tip_times():
    cfg = rg.live_cfg(ROOT)
    windows = set(rg.window_days(ROOT))
    covered = skipped = 0
    for d in game_days():
        first = tips(d)[0]
        admitted = [t for t in cfg["firings"]
                    if rg.admits_afternoon(utc(datetime.combine(d, t, tzinfo=LA)), ROOT, ROOT)[0]]
        fits = [t for t in cfg["firings"]
                if first - timedelta(minutes=90) <= datetime.combine(d, t, tzinfo=LA) <= first - timedelta(minutes=30)]
        if d in windows:
            assert admitted == [], d                       # Monday: the pre-tip runs instead
            continue
        assert admitted == fits[-1:], d                    # the latest that fits, else none
        plan = rg.afternoon_plan(ROOT, d, LA, ROOT)
        if admitted:
            covered += 1
            assert plan["firing"] == admitted[0].strftime("%H:%M")
        else:
            skipped += 1
            assert plan["firing"] is None and "SKIPPED" in plan["why"] and first.strftime("%H:%M") in plan["why"]
    assert covered / (covered + skipped) >= 0.85


def test_a_firing_that_lands_late_still_counts_and_a_stray_one_does_not():
    d = date(2026, 11, 17)                                 # first tip 16:30: the 15:30 firing
    assert rg.admits_afternoon(utc(la(d, 15, 31)), ROOT, ROOT)[0]
    assert not rg.admits_afternoon(utc(la(d, 15, 50)), ROOT, ROOT)[0]
    assert not rg.admits_afternoon(utc(la(d, 11, 30)), ROOT, ROOT)[0]


def test_the_skipped_day_is_named_in_that_nights_summary():
    d = next(x for x in game_days() if x not in set(rg.window_days(ROOT))
             and rg.afternoon_plan(ROOT, x, LA, ROOT)["firing"] is None)
    note = nightly.afternoon_plan_today(ROOT, d)
    assert note["firing"] is None and "SKIPPED" in note["why"]
    assert "row[\"afternoon\"] = afternoon_plan_today(self.base, self.today)" in Path(nightly.__file__).read_text()


def test_a_monday_that_is_not_a_window_day_is_skipped_not_claimed(monkeypatch):
    """Mon 12-07 sits inside week 7's 14 days: no pre-tip runs, and cron-job.org's
    afternoon job does not fire on Mondays. The night's summary must say SKIPPED."""
    d = date(2026, 12, 7)
    assert d not in rg.window_days(ROOT)
    monkeypatch.setattr(rg, "first_tip", lambda base, day, tz=None, state_dir=None:
                        datetime.combine(day, datetime.min.time(), tzinfo=LA).replace(hour=16))
    plan = rg.afternoon_plan(ROOT, d, LA, ROOT)
    assert plan["firing"] is None and "does not fire on Mondays" in plan["why"]
    assert not rg.admits_afternoon(utc(la(d, 15, 30)), ROOT, ROOT)[0]


def test_monday_is_excluded_and_the_guard_cli_admits_afternoon(tmp_path, monkeypatch):
    mon = window_mondays()[3]
    for t in rg.live_cfg(ROOT)["firings"]:
        assert not rg.admits_afternoon(utc(datetime.combine(mon, t, tzinfo=LA)), ROOT, ROOT)[0]
    out = tmp_path / "gh"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert rg.main(["afternoon", "--now", utc(la(date(2026, 11, 17), 15, 30)).isoformat()]) == 0
    assert out.read_text().splitlines() == ["go=true", "poll=false"]


def _line_files(tmp_path, week, tags, outs=None):
    o = tmp_path / "output"
    o.mkdir(parents=True, exist_ok=True)
    (o / f"live_lines_week{week}.state.json").write_text(json.dumps(
        {"week": week, "seed": 1, "as_of": "2026-11-17", "tags": {n: {"tag": t, "anchor": "2026-11-16"}
                                                                  for n, t in tags.items()}}))
    line = {"week": week, "lines": []}
    if outs:
        line["nba_outs"] = outs
    (o / f"live_lines_week{week}.json").write_text(json.dumps(line))


def test_the_afternoon_cause_names_each_change_from_its_inputs(tmp_path):
    _line_files(tmp_path, 5, {"Jalen Johnson": "Q", "Kel'el Ware": "D"})
    c = nightly.afternoon_cause(tmp_path, 5, {"Jalen Johnson": "O", "Coby White": "Q"},
                                {"applied": {"Zion Williamson": "2026-11-17"}})
    assert c == ("tag update: Coby White healthy→Q, Jalen Johnson Q→O, Kel'el Ware D→healthy; "
                 "NBA report: Zion Williamson out tonight")
    # the state file keeps chain tags only: OFS and healthy rostered players are no change
    _line_files(tmp_path, 5, {"A": "Q"})
    assert nightly.afternoon_cause(tmp_path, 5, {"A": "Q", "B": "OFS", "C": "HEALTHY", "E": "P"},
                                   {"applied": {}}) == "afternoon check: no change"
    _line_files(tmp_path, 5, {"A": "Q"}, {"Z": "2026-11-17"})
    assert nightly.afternoon_cause(tmp_path, 5, {"A": "Q"}, {"applied": {}}) == "NBA report: Z no longer out"
    assert nightly.afternoon_cause(tmp_path, 5, {"A": "Q"}, {"applied": {"Z": "2026-11-17"}}) == \
        "afternoon check: no change"


def test_an_unchanged_afternoon_writes_no_title_odds_and_no_hub(tmp_path):
    run = nightly.Run(tmp_path, "afternoon", now=la(date(2026, 11, 17), 15, 30), echo=lambda *a: None)
    calls = []
    steps = {n: (lambda n=n: calls.append(n)) for n in nightly.STEPS["afternoon"]
             if n not in ("line", "title_odds", "actuals", "hub", "changes")}
    steps["changes"] = lambda: setattr(run, "cause", "afternoon check: no change")
    steps["line"] = lambda: run.ctx.__setitem__("line", {"outcome": "unchanged"})
    row = run.execute(steps)
    assert row["outcome"] == "unchanged" and row["exit"] == 0
    assert [s["detail"] for s in row["steps"] if s["step"] in ("title_odds", "actuals", "hub")] == \
        ["skipped: nothing changed since the last line"] * 2 + \
        ["skipped: nothing changed since the last line (nothing published)"]


# =============================================================================
# 3. the O-past-3-games nudge
# =============================================================================

class _Data:
    """The few attributes o_nudge.find reads."""

    def __init__(self, rosters, overrides, playerlist, team_dates):
        self._r, self.injury_overrides, self.playerlist = rosters, {"players": overrides}, playerlist
        self._td = team_dates

    def get_current_rosters(self):
        return self._r


def _nudge(monkeypatch, tags, fa, actuals, records, overrides=(), today=date(2026, 11, 20)):
    import pandas as pd
    games = [date(2026, 11, d) for d in (10, 12, 14, 15, 17, 19, 21)]
    pl = pd.DataFrame([{"player_name": n, "player_nba_team": "NOP", "player_position(s)": "PF",
                        "projectedFPPG": f} for n, f in (("Zion Williamson", 40.0), ("Fa Good", 30.0),
                                                         ("Fa Low", 20.0), ("Healthy Guy", 30.0))])
    data = _Data({"Nick": ["Zion Williamson", "Healthy Guy"]}, list(overrides), pl, {"NOP": games})
    monkeypatch.setattr("modules.simulator_betting.team_season_dates", lambda d: {"NOP": games})
    return o_nudge.find(".", Tags(tags, fa), today, data=data, records=records, actuals=actuals,
                        cfg={"live_refresh": {"o_nudge": {"more_than_games": 3,
                                                          "free_agent_min_projected_fppg": 26.0}}})


def _actuals(last_played: str, through="2026-11-19"):
    days = {}
    d = date(2026, 11, 9)
    while d <= date.fromisoformat(through):
        days[d.isoformat()] = [10.0, 1 if d.isoformat() == last_played else 0]
        d += timedelta(days=1)
    return {"roster_names": {"Zion Williamson": 7}, "players": {"7": {"name": "Zion Williamson", "days": days}}}


def test_the_count_is_his_teams_games_since_his_last_game(monkeypatch):
    # his team's games after 11-10 through yesterday (11-19): 12, 14, 15, 17, 19
    out = _nudge(monkeypatch, {"Zion Williamson": "O"}, {}, _actuals("2026-11-10"), [])
    assert [x["title"] for x in out] == ["Zion Williamson has been O for 5 games with no injury entry"]
    assert "`Injury: Zion Williamson <notes>, back MM/DD`" in out[0]["body"]
    # three games (15, 17, 19) is not past the cap; four (14 too) is
    assert _nudge(monkeypatch, {"Zion Williamson": "O"}, {}, _actuals("2026-11-14"), []) == []
    assert _nudge(monkeypatch, {"Zion Williamson": "O"}, {}, _actuals("2026-11-12"), [])[0]["count"] == 4


def test_an_entry_or_another_tag_means_no_nudge(monkeypatch):
    entry = [{"player_name": "Zion Williamson", "out_weeks": [5]}]
    assert _nudge(monkeypatch, {"Zion Williamson": "O"}, {}, _actuals("2026-11-10"), [], entry) == []
    assert _nudge(monkeypatch, {"Zion Williamson": "Q"}, {}, _actuals("2026-11-10"), []) == []


def test_the_cant_count_path_says_so_and_never_guesses(monkeypatch):
    out = _nudge(monkeypatch, {"Zion Williamson": "O"}, {}, _actuals("2026-11-10", through="2026-11-15"), [])
    assert out[0]["count"] is None
    assert out[0]["title"] == "Zion Williamson is tagged O with no injury entry: can't count his games"
    assert "can't count his games: data/player_actuals.json reaches 2026-11-15" in out[0]["body"]


def _rec(day, fa):
    return {"run_id": day, "taken_at": f"{day}T00:05:00-08:00", "league_day": day,
            "tags": {"rostered": {}, "free_agents": fa}}


def test_a_free_agents_count_is_a_lower_bound_from_the_tag_records(monkeypatch):
    recs = [_rec("2026-11-11", {"Fa Good": "Q"})] + [_rec(f"2026-11-{d}", {"Fa Good": "O"}) for d in (12, 13, 20)]
    out = _nudge(monkeypatch, {}, {"Fa Good": "O", "Fa Low": "O"}, None, recs)
    assert [x["title"] for x in out] == ["Fa Good has been O for at least 4 games with no injury entry"]
    assert out[0]["scope"] == "free agent" and "lower bound" in out[0]["body"]
    # O since only 11-17: two games -- proves nothing, opens nothing
    late = [_rec("2026-11-16", {"Fa Good": "Q"}), _rec("2026-11-17", {"Fa Good": "O"})]
    assert _nudge(monkeypatch, {}, {"Fa Good": "O"}, None, late) == []


def test_the_nudge_issue_is_one_per_player_retitled_and_closed():
    items = [{"player": "Zion Williamson", "title": o_nudge.title("Zion Williamson", 5), "body": "b"},
             {"player": "Fa Good", "title": o_nudge.title("Fa Good", 6, True), "body": "b"}]
    open_ = [(11, o_nudge.title("Zion Williamson", 4)), (12, o_nudge.title("Gone Player", 7)),
             (13, o_nudge.title("Zion Williamson", None))]
    acts = fi.plan_nudges(items, open_)
    assert ("edit", 11, items[0]["title"], None) in acts
    assert ("close", 13, None, "Duplicate of #11.") in acts
    assert ("create", None, items[1]["title"], "b") in acts
    assert any(a[0] == "close" and a[1] == 12 for a in acts)
    assert not any(a[0] == "create" and "Zion" in a[2] for a in acts)
    # the script's matching is o_nudge's titles, both shapes
    for n in (5, None):
        assert fi.nudge_matches(o_nudge.title("Zion Williamson", n), "Zion Williamson")
        assert o_nudge.title_matches(o_nudge.title("Zion Williamson", n), "Zion Williamson")
    assert not fi.nudge_matches(o_nudge.title("Zion Williamson Jr", 5), "Zion Williamson")


def test_the_nudge_runs_in_the_nightly_only():
    assert [m for m, s in nightly.STEPS.items() if "nudges" in s] == ["nightly"]


# =============================================================================
# 4. the NBA report
# =============================================================================

def test_the_parser_reads_a_stored_real_report():
    p = nr.parse(FIXTURE.read_bytes())
    assert p["heading"] == "11/10/26 05:00 PM"
    st = {}
    for e in p["entries"]:
        st[e["status"]] = st.get(e["status"], 0) + 1
    assert st == {"Questionable": 12, "Doubtful": 3, "Out": 61, "Available": 4, "Probable": 2}
    assert {e["game_date"] for e in p["entries"]} == {"2026-11-10", "2026-11-11"}
    assert {e["team"] for e in p["entries"]} <= set(nr.TEAMS)
    first = p["entries"][0]
    assert (first["matchup"], first["team"], first["player"], first["status"]) == \
        ("MIL@NYK", "Milwaukee Bucks", "Tyler Herro", "Questionable")
    assert any(e["player"] == "Ernest Udeh Jr." for e in p["entries"])
    assert len(p["not_submitted"]) == 13
    assert nr.filed_at(FIXTURE.name, ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M") == "2026-11-10 17:00"


def test_first_last_names():
    assert nr.first_last("Jackson Jr., Jaren") == "Jaren Jackson Jr."
    assert nr.first_last("Udeh, Jr., Ernest") == "Ernest Udeh Jr."
    with pytest.raises(nr.ReportUnreadable):
        nr.first_last("A, B, C")


def test_a_changed_format_is_unreadable_not_guessed():
    hdr = [(23, 480, "Game"), (53, 480, "Date"), (119, 480, "Game"), (149, 480, "Time"), (200, 480, "Matchup"),
           (264, 480, "Team"), (425, 480, "Player"), (456, 480, "Name"), (585, 480, "Current"),
           (624, 480, "Status"), (666, 480, "Reason")]
    row = [(24, 459, "11/10/2026"), (120, 459, "07:30"), (201, 459, "MIL@NYK"), (265, 459, "Milwaukee"),
           (312, 459, "Bucks"), (426, 459, "Herro,"), (454, 459, "Tyler")]
    with pytest.raises(nr.ReportUnreadable, match="Banished"):
        nr.parse_fragments([hdr + row + [(586, 459, "Banished")]])
    with pytest.raises(nr.ReportUnreadable, match="no table header"):
        nr.parse_fragments([row])
    ok = nr.parse_fragments([hdr + row + [(586, 459, "Out")]])
    assert ok["entries"][0]["player"] == "Tyler Herro"


CFG = {"index_url": "https://index", "time_zone": "America/New_York", "cadence_minutes": 15,
       "probe_steps": 4, "timeout_seconds": 1, "stale_hours": 30,
       "pdf_url": "https://ak/Injury-Report_{date}_{hh}_{mm}{ampm}.pdf", "tz": ZoneInfo("America/New_York")}


def test_the_latest_report_from_the_index_else_by_probing():
    import urllib.error
    now = datetime(2026, 11, 10, 22, 7, tzinfo=timezone.utc)          # 17:07 ET
    page = b'<a href="/referee/injury/Injury-Report_2026-11-10_04_45PM.pdf"></a>' \
           b'<a href="/referee/injury/Injury-Report_2026-11-10_05_00PM.pdf"></a>'
    url, at, how = nr.latest_url(now, CFG, lambda u, t: page)
    assert how == "index" and url.endswith("Injury-Report_2026-11-10_05_00PM.pdf")
    tried = []

    def get(u, t):
        tried.append(u)
        if u == "https://index":
            raise urllib.error.URLError("refused")
        if u.endswith("04_45PM.pdf"):
            return b"%PDF"
        raise urllib.error.HTTPError(u, 403, "no", {}, None)
    url, at, how = nr.latest_url(now, CFG, get)
    assert how == "probe" and url.endswith("04_45PM.pdf") and tried[1].endswith("05_00PM.pdf")
    with pytest.raises(nr.ReportUnavailable, match="index page: network"):
        nr.latest_url(now, CFG, lambda u, t: (_ for _ in ()).throw(urllib.error.URLError("down")))


def test_an_unavailable_report_is_a_row_never_a_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "fetch", lambda *a, **k: (_ for _ in ()).throw(nr.ReportUnavailable("HTTP 403")))
    row = nr.read_and_store(tmp_path, la(date(2026, 11, 17), 15, 30), run_id="r1", mode="afternoon", cfg=CFG)
    assert row["outcome"] == "unavailable" and row["reason"] == "HTTP 403"
    assert nr.read_rows(tmp_path)[-1]["run_id"] == "r1"
    assert "NBA report unavailable (HTTP 403); Yahoo's tags stand" == nr.summary(row, {})


def test_the_run_goes_on_when_the_report_step_fails(tmp_path, monkeypatch):
    run = nightly.Run(tmp_path, "afternoon", now=la(date(2026, 11, 17), 15, 30), echo=lambda *a: None)
    run.week = 5
    run.ctx["tags"] = Tags({"Zion Williamson": "Q"}, {"Fa": "O"}, nba_outs={"X": "2026-11-17"})
    monkeypatch.setattr(nr, "read_and_store", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    detail = run.step_nba_report()
    assert "NBA report unavailable (OSError: disk); Yahoo's tags stand" in detail
    assert run.ctx["tags"].nba_outs == {}
    from modules import tag_records
    assert tag_records.read(tmp_path)[-1]["tags"].get("nba_outs") is None      # recorded, nothing applied


def test_a_same_report_is_stored_once(tmp_path, monkeypatch):
    body = FIXTURE.read_bytes()
    monkeypatch.setattr(nr, "fetch", lambda *a, **k: ("https://ak/" + FIXTURE.name,
                                                      datetime(2026, 11, 10, 17, tzinfo=CFG["tz"]), body, "index"))
    a = nr.read_and_store(tmp_path, la(date(2026, 11, 10), 15, 0), run_id="a", mode="afternoon", cfg=CFG)
    b = nr.read_and_store(tmp_path, la(date(2026, 11, 10), 15, 30), run_id="b", mode="afternoon", cfg=CFG)
    assert "entries" in a and "entries" not in b and b["same_as"] == "a"
    assert len(nr.latest(tmp_path)["report"]["entries"]) == len(a["entries"])


def _entry(player, status="Out", day="2026-11-17", team="New Orleans Pelicans"):
    last, first = player.split(" ", 1)[1], player.split(" ", 1)[0]
    return {"game_date": day, "game_time": "08:00 (ET)", "matchup": "NOP@MIA", "team": team,
            "name": f"{last}, {first}", "player": player, "status": status, "reason": ""}


def _assess(entries, tags, out_today=lambda n: False, known=None, filed="2026-11-17T13:00-05:00",
            now=la(date(2026, 11, 17), 15, 30)):
    known = known or {"Zion Williamson": "NOP", "Coby White": "CHA", "Jalen Johnson": "ATL",
                      "Fa Guy": "MIA", "Dillon Mitchell": "BOS", "Davion Mitchell": "MIA"}
    rosters = {"Nick": ["Zion Williamson", "Coby White", "Jalen Johnson", "Davion Mitchell"]}
    return nr.assess({"filed_at": filed, "entries": entries}, tags, rosters, out_today,
                     date(2026, 11, 17), known, now=now, cfg=CFG)


def test_out_tonight_is_applied_and_flagged_where_yahoo_has_no_o():
    a = _assess([_entry("Zion Williamson"), _entry("Coby White"), _entry("Jalen Johnson"),
                 _entry("Fa Guy"), _entry("Zion Williamson", day="2026-11-18")],
                {"Zion Williamson": "Q", "Jalen Johnson": "O"})
    assert a["applied"] == {"Zion Williamson": "2026-11-17", "Coby White": "2026-11-17"}
    assert [f["text"] for f in a["flags"]] == ["NBA report: Zion Williamson out tonight (Yahoo: Q)",
                                               "NBA report: Coby White out tonight (Yahoo: no tag)"]
    assert a["flags"][0]["title"] == "NBA report: Zion Williamson out Tue 11-17 (Yahoo: Q)"
    assert a["covered"] == ["Jalen Johnson (Yahoo O)"]


def test_an_injury_entry_covers_it_but_the_flag_stands():
    a = _assess([_entry("Zion Williamson")], {"Zion Williamson": "Q"}, out_today=lambda n: True)
    assert a["applied"] == {} and a["covered"] == ["Zion Williamson (injury entry)"]
    assert len(a["flags"]) == 1


def test_a_stale_report_is_not_applied():
    a = _assess([_entry("Zion Williamson")], {}, filed="2026-11-15T13:00-05:00")
    assert a["applied"] == {} and "not applied" in a["stale"]


def test_unresolved_names_are_listed_and_a_rostered_lookalike_is_loud():
    a = _assess([_entry("Zion Willamson"), _entry("Dillon Mitchell", team="Boston Celtics"),
                 _entry("Nobody Known", team="Utah Jazz")], {})
    # Dillon Mitchell is a known player (not rostered): resolved, not loud
    assert [x["name"] for x in a["unresolved"]] == ["Zion Willamson", "Nobody Known"]
    assert [(x["name"], x["maybe"]) for x in a["loud"]] == [("Zion Willamson", "Zion Williamson")]
    assert "FLAG unresolved NBA report name Zion Willamson" in nr.summary({"outcome": "ok",
                                                                          "filed_at": "2026-11-17T13:00-05:00"}, a)


def test_the_nba_flag_issue_is_one_per_player_per_game_and_closes_after_the_game():
    a = _assess([_entry("Zion Williamson")], {"Zion Williamson": "Q"})
    block = {"flags": a["flags"], "loud": []}
    t = a["flags"][0]["title"]
    assert fi.plan_nba(block, [], date(2026, 11, 17))[0][:3] == ("create", None, t)
    assert fi.plan_nba(block, [(5, t)], date(2026, 11, 17)) == []
    assert fi.plan_nba({}, [(5, t)], date(2026, 11, 18)) == [("close", 5, None, "The game is over.")]


# --- through the simulator: Out on one game, the chain, no double charge ----------

def _world(tag, outs, as_of=None):
    from test_absence import MWF, MON, _betting_data, _proj
    data = _betting_data({"BOS": MWF})
    teams = {"Nick": TeamProjections("Nick", {"A": _proj("A", "BOS")})}
    statuses = {"A": tag} if tag else {}
    blocks = sb.tag_blocks(data, teams, statuses, sb.KeyedDraws(7, 20000), MON, nba_outs=outs)
    return blocks.get("A"), MWF


def _misses(block, games):
    return np.stack([~sb.entry_available(len(block.k), (None,) * 4 + (None, None, None, True), d, None,
                                         block, None) for d in games], axis=1)


def test_a_q_tagged_player_out_tonight_misses_it_then_follows_the_q_chain():
    from test_absence import MWF
    blk, games = _world("Q", {"A": MWF[0].isoformat()})
    assert blk.start == 1 and blk.forced == frozenset({MWF[0]}) and "NBA report" in blk.basis
    m = _misses(blk, games)
    assert m[:, 0].all()                                   # tonight: certain
    expect = 1 + absence.expected_missed("Q", (False,))    # then the chain from its second game
    assert m.sum(axis=1).mean() == pytest.approx(expect, abs=0.02)
    # never double-charged: the chain is conditioned on tonight, not drawn again over it
    assert m.sum(axis=1).max() <= absence.MAX_TAG_GAMES
    assert absence.expected_missed("Q", (False,)) < absence.expected_missed("Q")  + 1


def test_a_player_with_no_tag_misses_that_game_only():
    from test_absence import MWF
    blk, games = _world(None, {"A": MWF[1].isoformat()})
    m = _misses(blk, games)
    assert (m.sum(axis=1) == 1).all() and m[:, 1].all()


def test_an_o_tag_already_covers_it():
    from test_absence import MWF
    with_out, _ = _world("O", {"A": MWF[0].isoformat()})
    plain, _ = _world("O", None)
    assert with_out.forced == frozenset() and (with_out.k == plain.k).all() and with_out.start == plain.start
    ofs, _ = _world("OFS", {"A": MWF[0].isoformat()})
    assert ofs is None


def test_an_out_that_is_not_the_chains_next_game_is_that_game_only():
    from test_absence import MWF
    blk, games = _world("D", {"A": MWF[1].isoformat()})
    plain, _ = _world("D", None)
    assert blk.start == 0 and (blk.k == plain.k).all() and blk.forced == frozenset({MWF[1]})
    assert _misses(blk, games)[:, 1].all()


def test_the_outs_ride_on_the_tags_and_the_tag_record():
    t = Tags({"A": "Q"}, {"B": "O"}, nba_outs={"A": "2026-11-17"})
    assert Tags.from_json(t.to_json()).nba_outs == {"A": "2026-11-17"}
    assert "nba_outs" not in Tags({"A": "Q"}, {}).to_json()           # older records read the same
    with pytest.raises(ValueError):
        Tags({}, {}, nba_outs={"A": "11/17"})


def test_the_outs_are_part_of_the_lines_cache_key_only_when_there_are_any():
    kw = dict(state_hash="s", tags="t", projections="p", overrides=[], schedule="x", assumptions=[],
              seed=1, num_simulations=10, engine={"commit": "c", "dirty": False}, il={})
    plain = ws.line_cache_key(**kw)
    assert ws.line_cache_key(**kw, nba_outs={}) == plain                # every older key unchanged
    out = ws.line_cache_key(**kw, nba_outs={"A": "2026-11-17"})
    assert out["key"] != plain["key"] and "nba_outs" in out["parts"]
    import refresh_lines as rl
    import types
    tmp = Path(__file__).parent
    p = types.SimpleNamespace(out_dir=tmp, week=99999)
    assert rl.waiting_changes(p, out) == ["no line on disk"]


def test_the_line_and_the_season_pass_read_the_outs():
    rl_src = (ROOT / "scripts" / "refresh_lines.py").read_text()
    assert "nba_outs = dict(live.nba_outs)" in rl_src and "nba_outs=nba_outs)" in rl_src
    assert "nba_outs=getattr(p, \"nba_outs\", None) or {})" in rl_src
    ss = (ROOT / "modules" / "season_sim.py").read_text()
    assert 'outs = getattr(injury_statuses, "nba_outs", None) or {}' in ss
    # passed to the remainder only when there are any (the chain's anchors ride beside them, s.3 of
    # HANDOFF_CAUSAL_LEVERAGE_2026-11-12: modules/season_sim.run_season's `extra`)
    assert 'extra = {"nba_outs": outs} if outs else {}' in ss
    assert "injury_statuses, il_mask=mask_w, **extra)" in ss


def test_the_report_is_read_by_the_runs_before_tip_and_reused_by_the_rest():
    assert nightly.REPORT_READERS == ("nightly", "pretip", "afternoon")
    for mode, steps in nightly.STEPS.items():
        if "line" in steps:
            assert "nba_report" in steps and steps.index("tags") < steps.index("nba_report") < steps.index("line"), mode


def test_the_report_file_is_state_and_ignored():
    m = json.loads((ROOT / "config/STATE_MANIFEST.json").read_text())
    assert "output/nba_injury_reports.jsonl" in [f["path"] for f in m["files"]]
    assert "output/nba_injury_reports.jsonl" in (ROOT / ".gitignore").read_text().splitlines()


def test_pypdf_is_pinned():
    assert "pypdf==6.21.2" in (ROOT / "requirements.txt").read_text().splitlines()


# =============================================================================
# 5. the grid's tag display
# =============================================================================

MON, TUE, WED = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)
WEEKS = {5: (MON, date(2026, 11, 22))}


def grid_world(tags, nba_outs=None, n=6):
    names = [f"P{i}" for i in range(n)]
    pos = ["PG", "SG", "SF", "PF", "C", "PG"]
    info = {nm: {"nba_team": f"T{i}", "positions": {pos[i % 6]}, "proj_fppg": 40.0 - i}
            for i, nm in enumerate(names)}
    team_dates = {f"T{i}": {MON, TUE, WED} for i in range(n)}
    return hs.Availability({"M": names}, {"M": []}, tags, {"players": []}, 5, info, team_dates, WEEKS, MON,
                           nba_outs), names


def test_d_is_out_for_his_next_game_only_and_o_is_unchanged():
    av, _ = grid_world({"P1": "D", "P2": "O"})
    assert [av.grid_status("P1", d) for d in (MON, TUE, WED)] == ["out", "plays", "plays"]
    assert [av.grid_status("P2", d) for d in (MON, TUE, WED)] == ["out", "out", "out"]
    # task 49 (Nick, 11-11): D is out for his next game everywhere the hub counts
    # games, not on the grid only; his later games count
    assert not av.plays("P1", MON) and av.plays("P1", TUE) and av.plays("P1", WED)


def test_q_is_a_range_on_his_next_game():
    av, _ = grid_world({"P1": "Q"})
    tab = hs.build_grid_tab(av, ["M"], [MON, TUE], 4, {MON: 6, TUE: 6})
    c0, c1 = tab["rows"][0]["cells"]
    assert (c0["n"], c0["rng"], c0["starts"]) == ("5–6", "1", "5–6")
    assert (c1["n"], c1["rng"]) == ("6", "")
    assert tab["rows"][0]["starts"] == "11–12" and tab["has_range"] == "1"


def test_an_nba_report_out_is_out_and_marked():
    av, _ = grid_world({}, {"P3": MON.isoformat()})
    assert av.grid_status("P3", MON) == "nba" and av.grid_status("P3", TUE) == "plays"
    tab = hs.build_grid_tab(av, ["M"], [MON], 4, {MON: 6})
    c = tab["rows"][0]["cells"][0]
    assert (c["n"], c["nba"], c["nba_names"], tab["has_nba"]) == ("5", "1", "P3", "1")
    nxt = av.with_rosters({"M": ["P3"]}, {"M": []}, {})
    assert nxt.grid_status("P3", MON) == "nba"


def test_the_page_prints_the_ranges_and_marks_as_payload_strings():
    from test_hub import sample_payload
    from modules import hub_page
    p = sample_payload()
    t = p["grid"]["tabs"][0]
    t["rows"][0]["cells"][0].update(n="7–9", rng="1", nba="1", nba_names="Zion Williamson")
    t["rows"][0].update(starts="17–19", idle="2–3", rng="1")
    t.update(has_range="1", has_nba="1")
    p["grid"]["legend"].update(range="3–4: a Q's next game", nba="† out on the NBA report")
    p["header"]["nba"] = {"text": "NBA injury report filed Tue 2:00 PM Pacific.",
                          "flags": ["NBA report: Zion Williamson out tonight (Yahoo: Q)"]}
    html = hub_page.render(p)
    for s in ("7–9", "17–19", "2–3", "&dagger;", "NBA report: Zion Williamson out",
              "NBA injury report filed Tue 2:00 PM Pacific.", "3–4: a Q&#x27;s next game"):
        assert s in html or s.replace("'", "&#x27;") in html, s


def test_the_grid_still_fits_a_360px_phone():
    from modules import hub_page
    css = hub_page.CSS
    rule = css[css.index(".g-h,.g-r{"):]
    gap = int(re.search(r"gap:(\d+)px", rule).group(1))
    pad = int(re.search(r"padding:\d+px (\d+)px", rule).group(1))
    src = (ROOT / "modules" / "hub_page.py").read_text()
    fixed = [int(x) for x in re.findall(r"(\d+)px", re.search(r"grid-template-columns:52px[^']+", src).group(0))]
    assert fixed == [52, 40, 32]
    per_day = (360 - 2 * 16 - 2 * pad - gap * 9 - sum(fixed)) / 7
    # "10–12" at the range cell's 11px: about 4 x 6.2 px
    assert per_day >= 22, per_day
    assert ".c.rng{font-size:11px" in css and ".k.rng{font-size:12px" in css


def test_the_nba_note_is_payload_strings(tmp_path):
    n = hs.nba_note(tmp_path, {"outcome": "ok", "filed_at": "2026-11-17T17:00-05:00",
                               "flags": [{"text": "NBA report: Z out tonight (Yahoo: Q)"}],
                               "loud": [{"name": "Zion Willamson", "team": "New Orleans Pelicans",
                                         "maybe": "Zion Williamson"}]})
    assert n == {"text": "NBA injury report filed Tue 2:00 PM Pacific.",
                 "flags": ["NBA report: Z out tonight (Yahoo: Q)",
                           "NBA report lists Zion Willamson (New Orleans Pelicans), not matched: is it Zion Williamson?"]}
    u = hs.nba_note(tmp_path, {"outcome": "unavailable",
                               "summary": "NBA report unavailable (HTTP 403); Yahoo's tags stand"})
    assert u["text"] == "NBA report unavailable (HTTP 403); Yahoo's tags stand"
    assert hs.nba_note(tmp_path, None) == {"text": "", "flags": []}


# =============================================================================
# 6. the minutes
# =============================================================================

def test_the_firing_counts_are_recomputed_from_the_files():
    assert am.github_crons(ROOT) == {}            # task 6f (11-11): GitHub's own crons are gone
    assert am.cron_job_org(ROOT) == {"Nightly": 28, "Pre-tip": 52, "Afternoon tags": 18}
    assert am.cron_per_week("*/15 15-23 * * 1") == 36 and am.cron_per_week("*/15 0-3 * * 2") == 16


def test_the_worst_case_stays_under_the_cap_once_github_crons_go():
    e = am.estimate(date(2026, 11, 16), ROOT)
    worst = next(r for r in e["estimates"] if r["case"] == "worst")
    assert worst["total_after_6f"] <= 1700, worst
    c = e["counts"]
    assert c["pretip_runs"] == 3 * c["window_mondays"]
    assert 20 <= c["polls_per_monday"] <= 26
