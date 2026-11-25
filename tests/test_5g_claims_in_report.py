"""5g s.1 (claude/HANDOFF_5G_WEEKLY_BUILD_FIXES_2026-11-25.md): the weekly
report counts pending group-chat claims, as the hub does.

Week 5's report (built 11-24) showed Hayden 2 week-6 adds left and Dyson
Daniels as a top free agent and as Benton's FA target: Hayden had claimed him
in the chat on 11-23 (ledger entry 8, claim week 6). Under rules 10 and 12 the
claim used an add the moment it was posted and reserved Daniels. The report
read only Yahoo's synced waivers files. Now:
  - build_add_budget counts a live claim in its claim week through
    move_ledger.counted_adds_by_week, the hub's own count;
  - every free-agent list in the report goes through data_loader.free_agents
    with the ledger (FantasyData.ledger_view) or schedule_strength's pool with
    it: a reserved player is in none, a live chat drop's player is back in;
  - the ledger is read through its own functions (hub_view), and an unreadable
    ledger raises.
"""
import ast
import inspect
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from modules import move_ledger as ml                            # noqa: E402
from modules import data_loader as dl                            # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=LA)                    # Wednesday of week 6
SCHED = {"weeks": [{"week": 5, "start_date": "2026-11-16", "end_date": "2026-11-22"},
                   {"week": 6, "start_date": "2026-11-23", "end_date": "2026-11-29"},
                   {"week": 7, "start_date": "2026-11-30", "end_date": "2026-12-13"}]}


def monday_games(*mondays):
    """Games only on the given Mondays, the last tipping 7:00 PM Pacific: the
    window closes 6:55 PM."""
    g = []
    for m in mondays:
        nxt = m + timedelta(days=1)
        g.append({"date": m.isoformat(), "away": "AAA", "home": "BBB", "tip_utc": f"{nxt.isoformat()}T03:00:00Z"})
        g.append({"date": m.isoformat(), "away": "CCC", "home": "DDD", "tip_utc": f"{nxt.isoformat()}T00:00:00Z"})
    return {"games": g}


NBA = monday_games(date(2026, 11, 16), date(2026, 11, 23), date(2026, 11, 30))


def entry(i, text, manager, add=(), drop=(), *, claimed, window, claim_week):
    return {"row": "entry", "id": i, "text": text, "kind": "move",
            "parsed": {"manager": manager, "add": list(add), "drop": list(drop), "il_place": [],
                       "il_activate": []},
            "claimed_at": claimed, "claim_week": claim_week, "window_week": claim_week + 1,
            "window": window, "entered_at": claimed, "entered_by": "test", "checks": []}


# entry 8 as it is in the real ledger; entry 9 a Benton chat drop; entry 3 a
# week-5 claim whose window (11-23) has closed; entry 10 voided
HAYDEN = entry(8, "Hayden move: +Dyson Daniels -Day'Ron Sharpe", "Hayden", ["Dyson Daniels"], ["Day'Ron Sharpe"],
               claimed="2026-11-23T22:00:00-08:00", window="2026-11-30", claim_week=6)
BENTON_DROP = entry(9, "Benton move: -Naz Reid", "Benton", [], ["Naz Reid"],
                    claimed="2026-11-24T12:00:00-08:00", window="2026-11-30", claim_week=6)
CLOSED = entry(3, "Garrett move: +Tari Eason", "Garrett", ["Tari Eason"], [],
               claimed="2026-11-20T10:00:00-08:00", window="2026-11-23", claim_week=5)
VOIDED = entry(10, "Nick move: +Keon Ellis", "Nick", ["Keon Ellis"], [],
               claimed="2026-11-24T13:00:00-08:00", window="2026-11-30", claim_week=6)
VOID_ROW = ("void", VOIDED)              # voids VOIDED, whatever id it gets

ROSTERS = {"Nick": ["Kevin Durant", "Luka Doncic"], "Hayden": ["Austin Reaves", "Day'Ron Sharpe"],
           "Benton": ["Naz Reid", "Julius Randle"], "Garrett": ["Victor Wembanyama"]}
PLAYERLIST = ["Kevin Durant", "Luka Doncic", "Austin Reaves", "Day'Ron Sharpe", "Naz Reid", "Julius Randle",
              "Victor Wembanyama", "Dyson Daniels", "Tari Eason", "Keon Ellis", "Ayo Dosunmu"]


def league(tmp_path, items):
    """A league folder with the ledger `items` (entries numbered 1, 2, 3 ... in
    order, as the ledger requires; ("void", entry) voids that entry), no
    states, and week 6's waivers file (Hayden's Yahoo add of Austin Reaves and
    Nick's of Kevin Durant in the 11-23 window)."""
    rows, ids = [], {}
    for it in items:
        if isinstance(it, tuple):
            rows.append({"row": "void", "entry": ids[id(it[1])], "by": "Nick",
                         "on": "2026-11-24T13:05:00-08:00", "reason": "typed what was not posted"})
        else:
            ids[id(it)] = len(ids) + 1
            rows.append(dict(it, id=ids[id(it)]))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "MOVE_LEDGER.json").write_text(
        json.dumps({"schema": 1, "_comment": "test", "rows": rows}), encoding="utf-8")
    (tmp_path / "data" / "waivers_week6.txt").write_text(
        "# partial\n\n- [2026-11-23] Hayden: Austin Reaves\n- [2026-11-23] Nick: Kevin Durant\n",
        encoding="utf-8")
    return tmp_path


def view(base, now=NOW):
    return ml.hub_view(base, now, NBA)


def playerlist():
    return pd.DataFrame({"player_name": PLAYERLIST, "projectedFPPG": [30.0] * len(PLAYERLIST),
                         "player_position(s)": ["G"] * len(PLAYERLIST),
                         "player_nba_team": ["ATL"] * len(PLAYERLIST)})


@pytest.fixture
def rb_at(monkeypatch):
    from modules import report_builder as rb

    def at(base):
        monkeypatch.setattr(rb, "__file__", str(base / "modules" / "report_builder.py"))
        return rb
    return at


class D:
    schedule = SCHED


# ======================================================== the add budget

def test_a_live_claim_counts_in_its_claim_week(tmp_path, rb_at):
    base = league(tmp_path, [HAYDEN])
    out = rb_at(base).build_add_budget(D(), 5, ledger_view=view(base))
    h = out["managers"]["Hayden"]
    assert out["week"] == 6
    assert (h["used"], h["remaining"]) == (2, 1)
    assert h["players"] == ["Austin Reaves", "Dyson Daniels"]
    assert h["shown"] == ["Austin Reaves", "Dyson Daniels (chat claim, joins 11-30)"]
    assert h["claims"][0]["entry"] == 1
    assert out["ledger"] == {"mode": "on", "live_claims": 1}


def test_the_formatted_table_shows_the_claim(tmp_path, rb_at):
    sys.path.insert(0, str(ROOT / "scripts"))
    import format_stats_report as fsr
    base = league(tmp_path, [HAYDEN])
    budget = rb_at(base).build_add_budget(D(), 5, ledger_view=view(base))
    src = inspect.getsource(fsr)
    assert 'entry.get("shown", entry.get("players", []))' in src
    row = next(f"| Hayden | {e['used']} | {e['remaining']} | {'; '.join(e['shown'])} |"
               for m, e in budget["managers"].items() if m == "Hayden")
    assert row == "| Hayden | 2 | 1 | Austin Reaves; Dyson Daniels (chat claim, joins 11-30) |"


def test_a_voided_entry_and_a_closed_window_change_nothing(tmp_path, rb_at):
    base = league(tmp_path, [CLOSED, VOIDED, VOID_ROW])
    v = view(base)
    assert v["claimed"] == {} and v["pending_adds"] == {}
    out = rb_at(base).build_add_budget(D(), 5, ledger_view=v)
    assert out["managers"]["Nick"]["used"] == 1 and out["managers"]["Garrett"]["used"] == 0
    assert out["ledger"]["live_claims"] == 0
    names = list(dl.free_agents(playerlist(), ROSTERS, ledger_view=v)["player_name"])
    assert names == list(dl.free_agents(playerlist(), ROSTERS)["player_name"])


def test_the_report_counts_what_the_hub_counts(tmp_path, rb_at):
    """The hub's count is move_ledger.counted_adds (hub_state.build); the
    report's is the same function's, for the same inputs."""
    base = league(tmp_path, [HAYDEN, BENTON_DROP, CLOSED])
    v = view(base)
    out = rb_at(base).build_add_budget(D(), 5, ledger_view=v)
    hub = ml.counted_adds(base, SCHED, 6, v)
    assert {m: e["players"] for m, e in out["managers"].items() if e["players"]} == hub
    fns = {n.name: n for n in ast.walk(ast.parse((ROOT / "modules" / "hub_state.py").read_text("utf-8")))
           if isinstance(n, ast.FunctionDef)}
    src = ast.get_source_segment((ROOT / "modules" / "hub_state.py").read_text("utf-8"), fns["build"])
    assert "ml.counted_adds(base, sched, week, lv, ledger_mode=ledger_mode)" in src
    assert "pending_adds" not in src                        # no second reading of the claims


def test_shadow_mode_counts_no_pending_claim_like_the_hub(tmp_path, rb_at, monkeypatch):
    monkeypatch.setattr(ml, "mode", lambda cfg=None: "shadow")
    base = league(tmp_path, [HAYDEN])
    out = rb_at(base).build_add_budget(D(), 5, ledger_view=view(base))
    assert out["managers"]["Hayden"]["used"] == 1 and out["managers"]["Hayden"]["claims"] == []


def test_no_ledger_view_raises(tmp_path, rb_at):
    base = league(tmp_path, [])
    with pytest.raises(ValueError, match="move ledger"):
        rb_at(base).build_add_budget(D(), 5, ledger_view=None)


def test_an_unreadable_ledger_raises(tmp_path):
    base = league(tmp_path, [])
    (base / "config" / "MOVE_LEDGER.json").write_text('{"schema": 99, "rows": []}', encoding="utf-8")
    with pytest.raises(ml.LedgerError):
        view(base)


def test_the_report_reads_the_ledger_before_anything_and_never_catches():
    from modules import report_builder as rb
    src = inspect.getsource(rb.build_stats_report)
    i = src.index("data.ledger_view = _ml.hub_view(data.base_path, now, data.nba_schedule)")
    assert i < src.index("compute_weekly_report(") < src.index("generate_rumor_mill_analysis(")
    assert "build_add_budget(data, week, ledger_view=data.ledger_view)" in src
    assert src[:i].count("try:") == 0                        # the read is not inside a try


# ======================================================== the free-agent pool

def test_a_reserved_player_is_no_free_agent_and_a_chat_drop_is(tmp_path):
    base = league(tmp_path, [HAYDEN, BENTON_DROP])
    v = view(base)
    names = list(dl.free_agents(playerlist(), ROSTERS, ledger_view=v)["player_name"])
    assert "Dyson Daniels" not in names                         # rule 10
    assert "Naz Reid" in names                                  # rule 11: free for the coming week
    assert "Day'Ron Sharpe" in names                            # Hayden's drop in the same entry
    assert "Tari Eason" in names and "Kevin Durant" not in names
    # Yahoo's rosters are unchanged: Reid still counts for Benton this week
    assert "Naz Reid" in ROSTERS["Benton"]


def test_get_free_agents_applies_the_reports_ledger(tmp_path, monkeypatch):
    base = league(tmp_path, [HAYDEN])
    data = dl.FantasyData(playerlist=playerlist())
    monkeypatch.setattr(dl.FantasyData, "get_current_rosters", lambda self: ROSTERS)
    assert "Dyson Daniels" in list(data.get_free_agents()["player_name"])     # no ledger: Yahoo only
    data.ledger_view = view(base)
    assert "Dyson Daniels" not in list(data.get_free_agents()["player_name"])
    # rosters passed in (C1, the retro-sim) are taken as given
    assert "Dyson Daniels" in list(data.get_free_agents(ROSTERS)["player_name"])


def test_a_freed_player_missing_from_playerlist_raises(tmp_path):
    ghost = entry(11, "Benton move: -Nobody Here", "Benton", [], ["Nobody Here"],
                  claimed="2026-11-24T12:00:00-08:00", window="2026-11-30", claim_week=6)
    base = league(tmp_path, [ghost])
    with pytest.raises(ValueError, match="Nobody Here \\(ledger entry 1\\)"):
        dl.free_agents(playerlist(), ROSTERS, ledger_view=view(base))


def test_schedule_strengths_pool_follows_the_ledger(tmp_path):
    from modules import schedule_strength as ss
    base = league(tmp_path, [HAYDEN, BENTON_DROP])
    info = {n: {"nba_team": "ATL", "positions": ["G"], "proj_fppg": 30.0} for n in PLAYERLIST}
    pool = [p[0] for p in ss.build_free_agent_pool(info, ROSTERS, view(base))]
    assert "Dyson Daniels" not in pool and "Naz Reid" in pool
    assert "Dyson Daniels" in [p[0] for p in ss.build_free_agent_pool(info, ROSTERS)]
    assert 'build_free_agent_pool(player_info, rosters, getattr(data, "ledger_view", None))' in \
        inspect.getsource(ss.build_schedule_strength)


def test_every_free_agent_list_in_the_report_goes_through_the_ledger_aware_pool():
    """best_worst's top free agents, the rumor mill's FA targets and its drop
    candidates' replacements read data.get_free_agents() (ledger-aware when
    the report set data.ledger_view); no report module builds its own pool."""
    from modules import report_builder as rb, rumor_mill_analyzer as rm
    assert "data.get_free_agents()" in inspect.getsource(rb.build_best_worst)
    assert "data.get_free_agents()" in inspect.getsource(rm.analyze_free_agents)
    assert "data.get_free_agents()" in inspect.getsource(rm.identify_drop_candidates)
    for mod in ("report_builder", "rumor_mill_analyzer", "waiver_roi", "season_performers",
                "standing_threads", "what_if_analyzer", "fun_facts_generator"):
        src = (ROOT / "modules" / f"{mod}.py").read_text(encoding="utf-8")
        assert "free_agents(data.playerlist" not in src and "free_agents(pl," not in src, mod
