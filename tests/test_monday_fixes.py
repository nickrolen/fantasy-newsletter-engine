"""
The first full Monday's fixes (claude/HANDOFF_MONDAY_FIXES_2026-11-09.md).

F1  the pre-tip run fetches player actuals before its hub step
F3  the POTW career count on a rerun
F4  a stats-report rerun reads freshness from the pre-week snapshot
F5  the Monday nightly records the finished week
F6  the checklist is off the hub; matchups lead
F9  the drafting and verification prompts' first line
F11 the stale-gates clock; integrity says python, never py
"""

from __future__ import annotations

import functools
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import nightly                      # noqa: E402

LA = ZoneInfo("America/Los_Angeles")


# =============================================================================
# F1. the pre-tip run fetches player actuals
# =============================================================================

def test_the_step_order_of_every_mode_is_pinned():
    assert nightly.STEPS == {
        # step 3b: the NBA report after the tags (it records them); the O-past-3
        # nudge last (it reads the night's player actuals, and opens issues only)
        "nightly": ("engine", "logs", "sync", "settings", "schedule", "tags", "nba_report", "returns",
                    "ledger", "line", "title_odds", "actuals", "hub", "nudges"),
        # step 3a: the refresh is the nightly path without the log pull
        "refresh": ("engine", "banked", "sync", "settings", "tags", "nba_report", "ledger", "line",
                    "title_odds", "actuals", "hub"),
        "pretip": ("engine", "window", "logs", "sync", "settings", "tags", "nba_report", "ledger", "line",
                   "title_odds", "actuals", "hub"),
        "closing": ("engine", "window", "sync", "closing"),
        # step 3b: a Monday poll's refresh, its cause from the synced transactions
        "poll": ("engine", "banked", "sync", "moves", "settings", "tags", "nba_report", "ledger", "line",
                 "title_odds", "actuals", "hub"),
        # step 3b: the afternoon tag check
        "afternoon": ("engine", "banked", "sync", "settings", "tags", "nba_report", "changes", "ledger",
                      "line", "title_odds", "actuals", "hub"),
    }
    # actuals sits right before the hub wherever a hub is built
    for mode, steps in nightly.STEPS.items():
        if "hub" in steps:
            assert steps[steps.index("hub") - 1] == "actuals", mode


class _FakeYahoo:
    def __init__(self):
        self.calls = 0
        self.asked = []

    def day(self, pids, d, names):
        self.calls += 2
        self.asked.append((d, tuple(pids)))
        return {p: [30.0, 1] for p in pids}


def _pretip_with_real_actuals(tmp_path, monkeypatch, steps_tuple=None):
    """A Monday pre-tip run on 11-09 where Franz Wagner was added that
    afternoon: the actuals file holds every other rostered player through
    Sunday, not him. Every step but actuals is a stub; the hub stub reads his
    season line the way hub_state does (player_actuals.season), so a missing
    player refuses with ActualsStale exactly as 11-09's 3:15 run did."""
    from modules import player_actuals as pa
    first = date(2026, 10, 20)
    monday = date(2026, 11, 9)
    real_update = pa.update
    # the nightly at 00:05 cached the old roster through Sunday
    real_update(tmp_path, source=_FakeYahoo(), ids={"Zion Williamson": 1}, today=monday,
                first_day=first, season="2026-27", echo=lambda *a: None)
    src = _FakeYahoo()
    monkeypatch.setattr(pa, "update", functools.partial(
        real_update, source=src, ids={"Zion Williamson": 1, "Franz Wagner": 2}, first_day=first,
        season="2026-27", echo=lambda *a: None))

    def hub():
        blob = pa.load(tmp_path)
        for name in ("Zion Williamson", "Franz Wagner"):
            pa.season(blob, name, monday.replace(day=8))
        return "built"

    if steps_tuple is not None:
        monkeypatch.setitem(nightly.STEPS, "pretip", steps_tuple)
    stubs = {n: (lambda n=n: n) for n in nightly.STEPS["pretip"] if n != "actuals"}
    stubs["hub"] = hub
    run = nightly.Run(tmp_path, "pretip", now=datetime(2026, 11, 9, 15, 15, tzinfo=LA),
                      echo=lambda *a: None)
    return run.execute(stubs), src


def test_a_player_added_on_the_window_day_does_not_make_the_pretip_run_refuse(tmp_path, monkeypatch):
    row, src = _pretip_with_real_actuals(tmp_path, monkeypatch)
    assert (row["outcome"], row["exit"]) == ("ok", 0), row["error"]
    steps = [s["step"] for s in row["steps"]]
    assert steps.index("actuals") == steps.index("hub") - 1
    # only the new player was fetched, from the season's first day through Sunday
    assert {pids for _d, pids in src.asked} == {(2,)}
    assert max(d for d, _p in src.asked) == date(2026, 11, 8)


def test_without_the_step_the_same_monday_refuses_as_on_11_09(tmp_path, monkeypatch):
    """The control: 2f5db12's pre-tip steps (no actuals) refuse at the hub."""
    old = ("engine", "window", "logs", "sync", "settings", "tags", "ledger", "line", "title_odds", "hub")
    row, _src = _pretip_with_real_actuals(tmp_path, monkeypatch, steps_tuple=old)
    assert row["outcome"] == "refused"
    assert row["steps"][-1]["step"] == "hub" and "ActualsStale" in row["error"]
    assert "Franz Wagner" in row["error"]


def test_the_actuals_step_uses_the_runs_own_clock():
    import inspect
    src = inspect.getsource(nightly.Run.step_actuals)
    assert "today=self.today" in src


# =============================================================================
# F3. the POTW career count on a rerun
# =============================================================================

def _potw_section(base, week, winner, season="2026-2027"):
    import format_stats_report as fsr
    hist, all_data = fsr.load_potw_history(week, base, season)
    career = fsr.career_stats_before_week(all_data, season, week, winner) if all_data else None
    data = {"metadata": {"season_year": season}, "player_of_week": {"winner": winner}}
    return fsr.format_section_4_potw(data, {}, hist, career)


def _winner(name, manager, fp=250.0):
    return {"player_name": name, "manager": manager, "total_fp": fp, "games": 4, "fppg": fp / 4,
            "nba_team": "SAS"}


def _write_history(base, seasons):
    (base / "config").mkdir(parents=True, exist_ok=True)
    (base / "config" / "POTW_HISTORY.json").write_text(json.dumps({"seasons": seasons}), encoding="utf-8")


def test_the_first_run_and_a_rerun_print_the_same_counts(tmp_path):
    import format_stats_report as fsr
    _write_history(tmp_path, {
        "2025-26": [{"week": w, "player": "Victor Wembanyama", "manager": "Garrett"} for w in (2, 5, 9)]
        + [{"week": 11, "player": "Nikola Jokic", "manager": "Hayden"}],
        "2026-27": [{"week": 1, "player": "Tyrese Maxey", "manager": "Benton"},
                    {"week": 2, "player": "Luka Doncic", "manager": "Nick"}]})
    win = _winner("Victor Wembanyama", "Garrett")
    first = _potw_section(tmp_path, 3, win)
    assert fsr.save_potw_winner(tmp_path, "2026-2027", win, 3) is True      # the first run saves him
    rerun = _potw_section(tmp_path, 3, win)
    assert rerun == first
    assert "4 career POTW awards (2025-26: 3, 2026-27: 1; this week included)" in first
    assert "first POTW award this season" in first
    assert "POTW by manager (season):** Benton 1, Nick 1, Garrett 1" in first
    assert "POTW by manager (career):** Garrett 4, Hayden 1, Benton 1, Nick 1" in first
    assert "+ 1 this week" not in first


def test_a_week_already_in_the_history_is_not_added_twice_and_a_changed_winner_raises():
    import format_stats_report as fsr
    all_data = {"seasons": {"2026-27": [{"week": 3, "player": "A", "manager": "Nick"},
                                        {"week": 4, "player": "A", "manager": "Nick"}]}}
    stats = fsr.career_stats_before_week(all_data, "2026-2027", 3, _winner("A", "Nick"))
    assert stats["by_player"] == {} and stats["by_manager"] == {}            # weeks 3 and 4 left out
    with pytest.raises(ValueError, match="already holds week 3"):
        fsr.career_stats_before_week(all_data, "2026-2027", 3, _winner("B", "Hayden"))


def test_the_week_3_numbers_on_the_real_history():
    path = ROOT / "config" / "POTW_HISTORY.json"
    if not path.is_file():
        pytest.skip("no league state here")
    wk3 = [e for e in json.loads(path.read_text(encoding="utf-8"))["seasons"].get("2026-27", [])
           if e["week"] == 3]
    if not wk3 or wk3[0]["player"] != "Victor Wembanyama":
        pytest.skip("week 3 is not recorded as Wembanyama here")
    text = _potw_section(ROOT, 3, _winner("Victor Wembanyama", "Garrett"))
    assert "Victor Wembanyama has 4 career POTW awards" in text
    assert "POTW by manager (career):** Hayden 9, Nick 7, Benton 6, Garrett 4" in text
    assert "first POTW award this season" in text and "2026-27: 1;" in text


# =============================================================================
# F4. a stats-report rerun reads freshness from the pre-week snapshot
# =============================================================================

def _one_run(live, pre, week, candidates):
    """What Step 6 does with the tracker: show the facts it allows, record
    them, clean up, save."""
    import generate_stats_report as gsr
    tracker, src = gsr.load_freshness(live, pre, week, echo=lambda *a: None)
    shown = []
    for key, sub, val in candidates:
        if tracker.should_show_fact(key, sub, val, week):
            tracker.record_fact(key, sub, val, week)
            shown.append(key)
    tracker.cleanup_old_entries(week, max_age_weeks=10)
    tracker.save()
    return shown, src


def _freshness_files(tmp_path):
    from modules.content_freshness import FreshnessTracker
    live = tmp_path / "config" / "RECENT_CONTENT.json"
    pre = tmp_path / "config" / "snapshots" / "RECENT_CONTENT_pre_week3.json"
    pre.parent.mkdir(parents=True)
    t = FreshnessTracker(live)
    t.record_fact("old:fact", "career_milestone", 5, 1)
    t.save()
    return live, pre


CANDIDATES = [("streak:nick", "win_streak", 2), ("milestone:hayden:100", "career_milestone", 3),
              ("old:fact", "career_milestone", 5)]


def test_two_runs_in_a_row_give_the_same_fun_facts_and_the_same_recent_content(tmp_path):
    live, pre = _freshness_files(tmp_path)
    before = live.read_bytes()
    shown1, src1 = _one_run(live, pre, 3, CANDIDATES)
    after1 = live.read_bytes()
    shown2, src2 = _one_run(live, pre, 3, CANDIDATES)
    assert shown1 == shown2 and {"streak:nick", "milestone:hayden:100"} <= set(shown1)
    assert live.read_bytes() == after1
    assert pre.read_bytes() == before                    # the snapshot is never written
    assert (src1, src2) == (live, pre)


def test_the_first_run_of_a_week_behaves_as_before(tmp_path):
    """No snapshot yet: it is made from RECENT_CONTENT.json and the run reads
    RECENT_CONTENT.json itself, and saves there."""
    from modules.content_freshness import FreshnessTracker
    live, pre = _freshness_files(tmp_path)
    before = live.read_bytes()
    shown, src = _one_run(live, pre, 3, CANDIDATES)
    assert src == live and pre.read_bytes() == before
    # the same as 2f5db12's path: load the live file, save it back
    ref = tmp_path / "ref.json"
    ref.write_bytes(before)
    t = FreshnessTracker.load(ref)
    t.set_current_week(3)
    for key, sub, val in CANDIDATES:
        if t.should_show_fact(key, sub, val, 3):
            t.record_fact(key, sub, val, 3)
    t.cleanup_old_entries(3, max_age_weeks=10)
    t.save()
    assert live.read_bytes() == ref.read_bytes()


def test_without_the_snapshot_a_rerun_would_drop_the_weeks_facts(tmp_path):
    """The control (what 11-09's reruns would have done without Nick's copy)."""
    from modules.content_freshness import FreshnessTracker
    live, pre = _freshness_files(tmp_path)
    _one_run(live, pre, 3, CANDIDATES)
    t = FreshnessTracker.load(live)
    assert not t.should_show_fact("milestone:hayden:100", "career_milestone", 3, 3)


def test_repro_still_reads_the_snapshot_and_the_cli_wires_the_helper():
    import inspect
    import generate_stats_report as gsr
    src = inspect.getsource(gsr.main)
    assert "load_freshness(" in src and "FreshnessTracker.load(" not in src


# =============================================================================
# F6. the checklist is off the hub; matchups lead.  F8. Yahoo add links
# =============================================================================

def test_no_checklist_in_the_hub_payload_or_page():
    import inspect
    from modules import hub_state, hub_page, move_ledger as ml
    assert '"checklist"' not in inspect.getsource(hub_state.build)
    page_src = inspect.getsource(hub_page.render)
    assert 'get("checklist")' not in page_src and '["checklist"]' not in page_src
    assert not hasattr(ml, "hub_checklist")


def test_this_weeks_matchups_is_always_the_first_section():
    import re
    import test_hub as th
    from modules import hub_page
    for extra in ({}, {"checklist": {"title": "Monday window", "lines": [], "stopped": []}}):
        page = hub_page.render(th.sample_payload(**extra), now=th.GEN)
        h2 = [re.sub(r"<[^>]+>", "", x) for x in re.findall(r"<h2>(.*?)</h2>", page)]
        assert h2[0] == "This week's matchups", h2
        assert page.index("<section") == page.index("<section><h2>This week's matchups</h2>")


def _checklist_fixture():
    rows = [{"row": "entry", "id": 7, "text": "Nick move: +Ty Jerome -Kyle Filipowski"},
            {"row": "entry", "id": 8, "text": "Benton move: +Jabari Smith Jr. -Davion Mitchell"},
            {"row": "entry", "id": 9, "text": "Nick move: +Nobody Known"}]
    cl = {"week": 4, "window": "2026-11-09", "closes": "2026-11-09T18:55-08:00",
          "order": "IL placements, then drops, trades, adds; every drop before every add.",
          "lines": [{"n": 1, "phase": "drop", "team": "Nick", "player": "Kyle Filipowski", "other": None,
                     "entry": 7, "text": "Nick: drop Kyle Filipowski"},
                    {"n": 2, "phase": "add", "team": "Nick", "player": "Ty Jerome", "other": None,
                     "entry": 7, "text": "Nick: add Ty Jerome"},
                    {"n": 3, "phase": "add", "team": "Nick", "player": "Nobody Known", "other": None,
                     "entry": 9, "text": "Nick: add Nobody Known"}],
          "stopped": [{"team": "Benton", "entries": [8],
                       "reason": "Anthony Davis sits in an IL slot and is not O or OFS on Mon 11-09: "
                                 "Yahoo allows Benton no moves until he leaves it (rule 3)"}]}
    return cl, rows


def test_ledger_checklist_prints_per_team_with_blocked_reasons_and_add_links():
    from modules import move_ledger as ml
    from modules.data_loader import PlayerIndex
    cl, rows = _checklist_fixture()
    states = [{"row": "state", "entry": 7, "state": "pending"}]
    out = ml.checklist_for_nick(cl, rows, states, ids=PlayerIndex({"Ty Jerome": 6212}),
                                league_key="478.l.16778", managers=["Nick", "Hayden", "Benton", "Garrett"])
    text = "\n".join(out)
    assert out[0] == "Week 4 window: Mon 11-09, closes 6:55 PM Pacific."
    assert text.index("\nNick\n") < text.index("\nBenton\n")              # the checklist's order
    assert "   1. Nick: drop Kyle Filipowski  [pending; entry 7]" in text
    assert "https://basketball.fantasysports.yahoo.com/nba/16778/addplayer?apid=6212" in text
    assert "no Yahoo add link: Nobody Known has no Yahoo id on file" in text
    assert "  BLOCKED: Anthony Davis sits in an IL slot and is not O or OFS" in text
    assert "      entry 8: Benton move: +Jabari Smith Jr. -Davion Mitchell" in text
    assert out[-1] == "Hayden, Garrett: nothing to do."
    # the drop has no link; only adds do
    drop_i = out.index("   1. Nick: drop Kyle Filipowski  [pending; entry 7]")
    assert "addplayer" not in out[drop_i + 1]


def test_yahoo_ids_come_from_playerlist_then_the_transaction_log(tmp_path):
    import pandas as pd
    from modules import move_ledger as ml
    (tmp_path / "data").mkdir()
    pd.DataFrame({"player_name": ["Nikola Jokić"], "yahoo_id": [5352]}).to_excel(
        tmp_path / "data" / "PLAYERLIST.xlsx", index=False)
    tx = [{"players": [{"name": "Ty Jerome", "player_key": "478.p.6212"}]}]
    ids = ml.yahoo_ids(tmp_path, tx)
    assert ids.get("Nikola Jokic") == 5352 and ids.get("Ty Jerome") == 6212
    assert ml.yahoo_add_url("478.l.16778", 6212).endswith("/nba/16778/addplayer?apid=6212")
    with pytest.raises(ValueError):
        ml.yahoo_add_url("", 1)


def test_the_playerlist_fetch_keeps_the_yahoo_id_outside_the_stamp_hash():
    import fetch_playerlist as fp
    from modules import playerlist_freshness as pf
    assert fp.COLUMNS[-1] == "yahoo_id" and "yahoo_id" not in pf.HASHED


# =============================================================================
# F9. chats use only the files they're given
# =============================================================================

def test_the_filled_prompts_open_with_the_uploaded_files_only_line(tmp_path):
    import test_prepare_prompts as tpp
    from modules import prepare_prompts as pp
    out = tpp.build(tpp.league(tmp_path))
    for n in ("1", "2", "3"):
        block = pp.prompt_blocks(tpp.part(out, n))[0]
        assert block.startswith(pp.ONLY_UPLOADED + "\n"), n
    assert pp.ONLY_UPLOADED == ("Use only the files uploaded to this chat. Do not open any other file "
                                "in my folder, and never `config/LEAGUE_LORE.json`.")


def test_a_template_without_the_line_refuses(tmp_path):
    import test_prepare_prompts as tpp
    from modules import prepare_prompts as pp
    b = tpp.league(tmp_path)
    t = b / pp.TEMPLATE
    t.write_text(t.read_text(encoding="utf-8").replace(pp.ONLY_UPLOADED + "\n\nContinue", "Continue", 1),
                 encoding="utf-8")
    with pytest.raises(pp.PromptsRefused, match="uploaded-files-only"):
        tpp.build(b)


def test_the_verification_prompt_opens_with_the_line_and_never_lists_the_lore_file():
    from modules import prepare_prompts as pp
    text = (ROOT / "templates" / "VERIFICATION_TEMPLATE.md").read_text(encoding="utf-8")
    prompt = text.split("## The Prompt", 1)[1].split("```", 2)[1].lstrip("\n")
    assert prompt.startswith(pp.ONLY_UPLOADED + "\n")
    assert "LEAGUE_LORE.json" not in prompt.replace(pp.ONLY_UPLOADED, "")
    assert "lore_for_drafting.json" in prompt
    np_ = (ROOT / pp.TEMPLATE).read_text(encoding="utf-8")
    ver = np_.split("### Prompt for Verification:", 1)[1].split("```", 2)[1].lstrip("\n")
    assert ver.startswith(pp.ONLY_UPLOADED + "\n")


# =============================================================================
# F11. lore phase-benton-late; integrity says python
# =============================================================================

def _lore_base(tmp_path, text):
    """A throwaway tree with its own lore file (never the real one)."""
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "league_config.json").write_text(json.dumps({"season": {"current": "2026-27"}}))
    entry = {"id": "phase-benton-late", "kind": "derived", "status": "approved", "strength": "fact",
             "template": "{manager} is {w}-{l} in {phase} ({pct}% wins), against {ow}-{ol} ({opct}%) "
                         "the rest of the time, {span}.",
             "text": text, "entities": ["Benton"]}
    (tmp_path / "config" / "LEAGUE_LORE.json").write_text(json.dumps({"entries": [entry]}))
    return tmp_path


def test_the_lore_export_recomputes_derived_entries_first(tmp_path, monkeypatch):
    """11-09: the export handed the writer 67-70 (stored before Benton's week-3
    win); the lore code on the day's data gives 68-70."""
    import propose_lore
    import review_lore
    from modules import lore as L
    base = _lore_base(tmp_path, "Benton is 20-42 in the last third of the regular season (32% wins), "
                                "against 67-70 (49%) the rest of the time, 2017-18 to 2026-27.")
    vals = dict(manager="Benton", phase=L.PHASE_LABEL["late"], w=20, l=42, ow=68, ol=70, pct=32, opct=49,
                span="2017-18 to 2026-27")
    cell = L.Cell("phase-benton-late", "phase", "Benton", {"family": "phase"}, "", vals, 0.01, 62, "low")
    monkeypatch.setattr(propose_lore, "build_cells", lambda b, *a, **k: ([cell], 400))
    assert review_lore.main(["--export", "--base", str(base)]) == 0
    got = json.loads((base / "output" / "lore_for_drafting.json").read_text())["entries"]
    assert got[0]["text"].startswith("Benton is 20-42") and "against 68-70 (49%)" in got[0]["text"]


def test_the_lore_export_refuses_when_it_cannot_recompute(tmp_path, monkeypatch, capsys):
    import propose_lore
    import review_lore
    base = _lore_base(tmp_path, "stale text")

    def boom(*a, **k):
        raise FileNotFoundError("data/historical/all_matchups.json")

    monkeypatch.setattr(propose_lore, "build_cells", boom)
    assert review_lore.main(["--export", "--base", str(base)]) == 1
    assert "REFUSED" in capsys.readouterr().out
    assert not (base / "output" / "lore_for_drafting.json").exists()


def test_the_phase_split_counts_every_game_once():
    """The cell's two records are the manager's whole career: inside + rest."""
    from modules import lore as L
    games = [L.Game("2026-27", w, "Benton", "X", 10.0 + (w % 3), 11.0) for w in range(1, 16)]
    labels = [L._phase(g, lambda s: 15) for g in games]
    w, l, ow, ol = L._split_record(games, [x == "late" for x in labels])
    assert w + l + ow + ol == len(games) and (w + ow) == sum(g.won for g in games)


def test_integrity_messages_say_python_never_py():
    import re
    text = (ROOT / "scripts" / "verify_project_integrity.py").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])py scripts[/\\]", text)
