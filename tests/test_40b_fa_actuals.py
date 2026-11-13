"""40b (claude/HANDOFF_40B_FA_ACTUALS_2026-11-13.md).

  s.1 the actuals fetch also covers every NON-ROSTERED player the hub names
      (player_actuals.update_extras), with the rostered players' rules: the
      previous run's names, one night's lag; ids by the engine's one rule;
      a cap that raises; its own batches after the rostered pass; the
      nightly records its failure loudly and goes on.
  s.2 the card loader says "reload" when a card, history or photo file is
      gone (HTTP 404); any other failure keeps the old message (jsdom).
  s.3 actions_minutes counts only the private state repo's workflows, with
      the per-job rounding and the advice step; --usage-csv reads GitHub's
      detailed usage report.

No live Yahoo call anywhere: the sources are fakes, and the one real run path
(the nightly's actuals step on a copy of Nick's state) parses Yahoo's two
response shapes (the ones step 1b measured; tests/test_player_actuals.py's
parser test) from a fake league.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from modules import hub_cards as hc, hub_crypto, hub_page, hub_publish, nightly  # noqa: E402
from modules import player_actuals as pa  # noqa: E402
from modules import player_card_builder as pcb  # noqa: E402
from league_state import needs_state  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
FIRST = date(2026, 10, 20)
SEASON = "2026-27"
TEST_PASS = "a test passphrase, never the real one"


class FakeSource:
    """{(pid, day): [points, games]}, else [0.0, 0]. fail_on: (pid, day)."""

    def __init__(self, lines=None, fail_on=None):
        self.lines = lines or {}
        self.fail_on = fail_on
        self.calls = 0
        self.asked = []

    def day(self, pids, d, names):
        self.asked.append((d, tuple(pids)))
        out = {}
        for i in range(0, len(pids), pa.BATCH):
            self.calls += 2
            for p in pids[i:i + pa.BATCH]:
                if self.fail_on == (p, d):
                    raise pa.ActualsError(f"Yahoo returned no {d} games-played stat for {names[p]}")
                out[p] = list(self.lines.get((p, d), [0.0, 0]))
        return out


# --- a base: the sample hub payload, PLAYERLIST ids, the cap ------------------

ROSTERED = {"Zed Alpha": 1, "Yan Beta": 2}
PL_IDS = {"Free Agent": 11, "Hurt Agent": 12, "Gone Agent": 13, "Free Guy": 14, "New Guy": 15,
          "Old Guy": 16, "A Guy": 17, "B Guy": 18}            # "Kept Drop": no id (unless the log has one)


def _payload(drop=(), add=()):
    from test_hub import sample_payload
    p = sample_payload()
    hc.annotate(p)
    p["free_agents"]["rows"] = [r for r in p["free_agents"]["rows"] if r["name"] not in drop]
    p["stash"]["rows"] = [r for r in p["stash"]["rows"] if r["name"] not in drop]
    for n in add:
        p["free_agents"]["rows"].append(dict(p["free_agents"]["rows"][0], name=n))
    for w in p["moves"]["weeks"]:
        for it in w["items"]:
            it["parts"] = [x for x in it["parts"] if not set(hc.part_names(x)) & set(drop)]
        w["items"] = [it for it in w["items"] if it["parts"]]
    return p


def _base(tmp_path, cap=20, ids=None, payload=None, log_ids=None):
    b = tmp_path / "base"
    for d in ("config", "data", "output"):
        (b / d).mkdir(parents=True, exist_ok=True)
    (b / "config" / "league_config.json").write_text(json.dumps({"actuals": {"extra_players_max": cap}}))
    ids = PL_IDS if ids is None else ids
    pd.DataFrame({"player_name": list(ids), "yahoo_id": list(ids.values())}).to_excel(
        b / "data" / "PLAYERLIST.xlsx", index=False)
    _write_payload(b, payload or _payload())
    if log_ids:
        rows = [{"row": "transaction", "key": f"k{i}", "type": "add", "status": "successful",
                 "timestamp": str(1762000000 + i), "time": "x", "league_day": "2026-11-01",
                 "players": [{"name": n, "player_key": f"466.p.{pid}"}], "rulings": []}
                for i, (n, pid) in enumerate(log_ids.items())]
        (b / "data" / "transaction_log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return b


def _write_payload(b, p):
    (b / "output" / "hub_state.json").write_text(json.dumps(p), encoding="utf-8")


def _night(b, today, rostered=ROSTERED, src=None, payload=None):
    """One actuals step: the rostered pass (HEAD's), then the extras pass."""
    if payload is not None:
        _write_payload(b, payload)
    src = src or FakeSource()
    r = pa.update(b, source=src, ids=dict(rostered), today=today, first_day=FIRST, season=SEASON,
                  echo=lambda *a: None)
    n0 = len(src.asked)
    x = pa.update_extras(b, source=src, rostered=r["ids"], today=today)
    return r, x, src.asked[:n0], src.asked[n0:]


# =============================================================================
# s.1 the free agents' NBA numbers
# =============================================================================

def test_a_listed_free_agent_is_fetched_and_his_card_shows_the_nba_numbers(tmp_path):
    b = _base(tmp_path)
    today = date(2026, 10, 24)                                   # finished: 10-20 .. 10-23
    src = FakeSource({(11, date(2026, 10, 21)): [41.5, 1], (11, date(2026, 10, 23)): [20.0, 1]})
    _r, x, _ros, ext = _night(b, today, src=src)
    assert x["players"] == 8 and x["no_id"] == ["Kept Drop"]
    assert all(11 in pids for _d, pids in ext) and len(ext) == 4
    payload = json.loads((b / "output" / "hub_state.json").read_text())
    payload["sources"]["actuals_through"] = "2026-10-23"
    extras = [{"player_name": v["name"], "manager": ""} for v in payload["cards"]["players"].values()
              if v["kind"] != "rostered"]
    nba = hc.nba_lines(b, payload, [], extras)
    assert [ln[1:] for ln in nba["lines"]["Free Agent"]] == [[0.0, 0], [41.5, 1], [0.0, 0], [20.0, 1]]
    (b / "data" / "historical").mkdir()
    cards = {c["player_name"]: c for c in pcb.build_player_cards(
        [], b / "data", b / "config", b / "data" / "historical",
        extra_players=[{"player_name": "Free Agent", "manager": ""}], nba=nba)}
    cs = cards["Free Agent"]["current_season"]
    assert (cs["gp"], cs["fppg"]) == (2, 30.8) and not cards["Free Agent"].get("season_note")


def test_a_newly_listed_player_is_backfilled_once_and_says_fetched_from_tonight(tmp_path):
    b = _base(tmp_path, ids=dict(PL_IDS, **{"Late Comer": 21}))
    _night(b, date(2026, 10, 23))                                # 10-20 .. 10-22 for the first eight
    # the hub lists him tonight; the fetch ran before the hub, so his card says so
    p = _payload(add=["Late Comer"])
    blob = pa.load(b)
    out = pa.card_lines(blob, ["Late Comer", "Free Agent"], date(2026, 10, 22), no_id=["Kept Drop"])
    assert out["lines"]["Late Comer"] is None and out["notes"]["Late Comer"] == pa.NOTE_NEVER
    assert "fetched" in pa.NOTE_NEVER and "from tonight" in pa.NOTE_NEVER
    assert out["lines"]["Free Agent"] is not None
    # the next night reads tonight's names: he is backfilled from the first day, once
    _r, x, _ros, ext = _night(b, date(2026, 10, 24), payload=p)
    assert x["backfilled"] == ["Late Comer"]
    asked_him = [d for d, pids in ext if 21 in pids]
    assert asked_him == [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 23)]
    assert [pids for d, pids in ext if d < date(2026, 10, 23)] == [(21,)] * 3       # alone for the old days
    _r, x2, _ros, ext2 = _night(b, date(2026, 10, 25), payload=p)
    assert x2["backfilled"] == [] and [d for d, _p in ext2] == [date(2026, 10, 24)]  # once


def test_a_dropped_player_stays_covered_while_named_and_stops_after(tmp_path):
    b = _base(tmp_path, ids=dict(PL_IDS, **{"Yan Beta": 2}))
    _night(b, date(2026, 10, 23))                                # Yan rostered: 10-20 .. 10-22
    # dropped before the next run; the previous hub (tonight's names) still shows him
    _r, x, ros, ext = _night(b, date(2026, 10, 24), rostered={"Zed Alpha": 1})
    assert all(2 not in pids for _d, pids in ros)
    assert any(2 in pids for _d, pids in ext) and "Yan Beta" not in x["backfilled"]
    blob = pa.load(b)
    assert "2026-10-23" in blob["players"]["2"]["days"]          # no gap
    assert pa.card_lines(blob, ["Yan Beta"], date(2026, 10, 23))["lines"]["Yan Beta"] is not None
    # the hub no longer names him: not fetched; his days stay
    p = _payload()
    for rb in p["rosters"].values():
        rb["players"] = [x for x in rb["players"] if x["name"] != "Yan Beta"]
    _r, x, ros, ext = _night(b, date(2026, 10, 25), rostered={"Zed Alpha": 1}, payload=p)
    assert all(2 not in pids for _d, pids in ros + ext)
    assert "Yan Beta" not in pa.load(b)["extra_names"]
    assert "2026-10-23" in pa.load(b)["players"]["2"]["days"]


def test_more_names_than_the_cap_raise_naming_the_count(tmp_path):
    b = _base(tmp_path, cap=7)
    src = FakeSource()
    r = pa.update(b, source=src, ids=dict(ROSTERED), today=date(2026, 10, 23), first_day=FIRST,
                  season=SEASON, echo=lambda *a: None)
    before = (b / pa.CACHE_RELPATH).read_bytes()
    n = len(src.asked)
    with pytest.raises(pa.ActualsError, match=r"names 8 non-rostered players.*\(7\)"):
        pa.update_extras(b, source=src, rostered=r["ids"], today=date(2026, 10, 23))
    assert len(src.asked) == n and (b / pa.CACHE_RELPATH).read_bytes() == before   # nothing asked, nothing written


def test_the_cap_is_required(tmp_path):
    b = _base(tmp_path)
    (b / "config" / "league_config.json").write_text(json.dumps({"actuals": {}}))
    with pytest.raises(pa.ActualsError, match="extra_players_max"):
        pa.extras_cap(b)
    real = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert pa.extras_cap(ROOT) == real["actuals"]["extra_players_max"] >= 1


def test_no_yahoo_id_gives_the_note_with_the_reason_and_the_log_is_the_second_source(tmp_path):
    b = _base(tmp_path)
    _r, x, _ros, ext = _night(b, date(2026, 10, 22))
    assert x["no_id"] == ["Kept Drop"] and all(99 not in p for _d, p in ext)
    payload = json.loads((b / "output" / "hub_state.json").read_text())
    payload["sources"]["actuals_through"] = "2026-10-21"
    nba = hc.nba_lines(b, payload, [], [{"player_name": "Kept Drop", "manager": ""},
                                        {"player_name": "Free Agent", "manager": ""}])
    assert nba["lines"]["Kept Drop"] is None and nba["notes"]["Kept Drop"] == pa.NOTE_NO_ID
    assert "not in Yahoo's player list" in pa.NOTE_NO_ID
    # move_ledger.yahoo_ids' second source: the transaction log's player key (Yahoo's own)
    b2 = _base(tmp_path / "two", log_ids={"Kept Drop": 99})
    _r, x2, _ros, ext2 = _night(b2, date(2026, 10, 22))
    assert x2["no_id"] == [] and any(99 in p for _d, p in ext2)


def test_a_partial_day_is_not_written(tmp_path):
    b = _base(tmp_path)
    src = FakeSource(fail_on=(13, date(2026, 10, 22)))
    r = pa.update(b, source=src, ids=dict(ROSTERED), today=date(2026, 10, 24), first_day=FIRST,
                  season=SEASON, echo=lambda *a: None)
    with pytest.raises(pa.ActualsError, match=r"2026-10-22.*Gone Agent"):
        pa.update_extras(b, source=src, rostered=r["ids"], today=date(2026, 10, 24))
    blob = pa.load(b)
    for pid in PL_IDS.values():
        assert sorted(blob["players"][str(pid)]["days"]) == ["2026-10-20", "2026-10-21"]
    for pid in ROSTERED.values():                                # the rostered pass's days all stand
        assert sorted(blob["players"][str(pid)]["days"]) == ["2026-10-20", "2026-10-21", "2026-10-22",
                                                             "2026-10-23"]


def test_the_rostered_players_get_exactly_heads_calls(tmp_path):
    """The rostered pass is update() unchanged: the same asks as with no
    extras at all; the extras come after, in batches of their own."""
    many = {f"Rostered {i}": 100 + i for i in range(30)}         # two rostered batches
    a = _base(tmp_path / "a")
    src_a = FakeSource()
    pa.update(a, source=src_a, ids=dict(many), today=date(2026, 10, 23), first_day=FIRST, season=SEASON,
              echo=lambda *x: None)
    b = _base(tmp_path / "b")
    _r, _x, ros, ext = _night(b, date(2026, 10, 23), rostered=many)
    assert ros == src_a.asked
    assert ext and all(not set(p) & set(many.values()) for _d, p in ext)
    assert pa.load(b)["roster_names"] == pa.load(a)["roster_names"]


def test_extra_names_are_recorded_and_validated(tmp_path):
    b = _base(tmp_path)
    _night(b, date(2026, 10, 22))
    blob = pa.load(b)
    assert blob["extra_names"] == {n: pid for n, pid in sorted(PL_IDS.items())}
    blob["extra_names"]["Ghost"] = 777
    with pytest.raises(pa.ActualsError, match="Ghost"):
        pa.validate(blob)
    # a quiet run leaves the file byte-identical
    before = (b / pa.CACHE_RELPATH).read_bytes()
    src = FakeSource()
    _night(b, date(2026, 10, 22), src=src)
    assert src.calls == 0 and (b / pa.CACHE_RELPATH).read_bytes() == before


def test_the_nightly_records_an_extras_failure_loudly_and_goes_on(tmp_path, monkeypatch, capsys):
    import functools
    b = _base(tmp_path, cap=3)                                  # 8 names > 3
    real = pa.update
    monkeypatch.setattr(pa, "update", functools.partial(
        real, source=FakeSource(), ids=dict(ROSTERED), first_day=FIRST, season=SEASON, echo=lambda *a: None))
    stubs = {n: (lambda n=n: n) for n in nightly.STEPS["nightly"] if n != "actuals"}
    run = nightly.Run(b, "nightly", now=datetime(2026, 10, 23, 0, 5, tzinfo=LA), echo=lambda *a: None)
    row = run.execute(stubs)
    assert (row["outcome"], row["exit"]) == ("ok", 0)
    step = next(s for s in row["steps"] if s["step"] == "actuals")
    assert "free agents FAILED" in step["detail"] and "names 8" in step["detail"]
    assert row["actuals"]["error"].startswith("ActualsError") and row["actuals"]["extras"] is None
    assert run.ctx["actuals_lines"][0].startswith("FREE-AGENT ACTUALS FAILED")
    assert "2026-10-22" in pa.load(b)["players"]["1"]["days"]  # the rostered days are written
    src = (ROOT / "modules" / "nightly.py").read_text(encoding="utf-8")
    assert 'for line in run.ctx.get("actuals_lines") or []' in src


def test_a_good_night_records_its_free_agents(tmp_path, monkeypatch):
    import functools
    b = _base(tmp_path)
    monkeypatch.setattr(pa, "update", functools.partial(
        pa.update, source=FakeSource(), ids=dict(ROSTERED), first_day=FIRST, season=SEASON,
        echo=lambda *a: None))
    stubs = {n: (lambda n=n: n) for n in nightly.STEPS["nightly"] if n != "actuals"}
    row = nightly.Run(b, "nightly", now=datetime(2026, 10, 23, 0, 5, tzinfo=LA), echo=lambda *a: None).execute(stubs)
    assert row["actuals"]["extras"] == 8 and row["actuals"]["no_id"] == ["Kept Drop"] and row["actuals"]["error"] is None
    step = next(s for s in row["steps"] if s["step"] == "actuals")
    assert "free agents 8 (cap 20)" in step["detail"] and "no Yahoo id: Kept Drop" in step["detail"]


def test_the_dry_run_prints_the_plan_and_touches_nothing(tmp_path, monkeypatch, capsys):
    import fetch_player_actuals as fpa
    b = _base(tmp_path)
    (b / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": {"M": ["Zed Alpha", "Yan Beta", "Rookie New"]}}))
    _night(b, date(2026, 10, 22))
    before = (b / pa.CACHE_RELPATH).read_bytes()
    from modules import season_performers as sp

    def no_yahoo(*a, **k):
        raise AssertionError("the dry run must not reach Yahoo")
    monkeypatch.setattr(sp, "get_yahoo_league", no_yahoo)
    monkeypatch.setattr("modules.league_clock.league_today", lambda: date(2026, 10, 24))
    assert fpa.main(["--base-path", str(b), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Rookie New" in out and "no Yahoo id" in out and "Kept Drop" in out
    # rostered: 2 known x 2 days (1 batch -> 2 calls a day) + the new pickup's 4 days alone
    assert "Rostered players: 3" in out and "2 day(s) to fetch, 12 call(s)" in out
    assert re.search(r"PLANNED: \d+ Yahoo call", out)
    assert (b / pa.CACHE_RELPATH).read_bytes() == before


def test_calls_for_is_two_per_batch_per_day():
    assert pa.calls_for({date(2026, 1, 1): list(range(25)), date(2026, 1, 2): list(range(26))}) == 2 + 4


# --- the real run path: the nightly's actuals step on a copy of Nick's state ---

class _Handler:
    def __init__(self, lg):
        self.lg = lg

    def get(self, url):
        """The game-scoped players/stats response (Yahoo's shape, as step 1b
        measured it): stat 0 = games played."""
        m = re.match(r"players;player_keys=(.+)/stats;type=date;date=(\d{4}-\d\d-\d\d)$", url)
        assert m, url
        d = date.fromisoformat(m.group(2))
        pids = [int(k.split(".p.")[1]) for k in m.group(1).split(",")]
        self.lg.game_calls.append((d, tuple(pids)))
        players = {"count": len(pids)}
        for i, pid in enumerate(pids):
            g = self.lg.line(pid, d)[1]
            players[str(i)] = {"player": [[{"player_key": f"466.p.{pid}"}, {"player_id": str(pid)},
                                           {"name": {"full": f"P{pid}"}}],
                                          {"player_stats": {"coverage_type": "date", "date": d.isoformat(),
                                                            "stats": [{"stat": {"stat_id": "0", "value": str(g)}},
                                                                      {"stat": {"stat_id": "2", "value": "30"}}]}}]}
        return {"fantasy_content": {"players": players}}


class FakeLeague:
    """yahoo_fantasy_api's League, as YahooSource and roster_player_ids use it:
    league_id, teams(), to_team().roster(), player_stats(ids, 'date', date=)
    (the league-scoped rows: player_id, name, total_points) and yhandler.get."""

    def __init__(self, roster):
        self.league_id = "466.l.99999"
        self.roster = roster
        self.yhandler = _Handler(self)
        self.stat_calls, self.game_calls = [], []

    @staticmethod
    def line(pid, d):
        g = 1 if (pid + d.toordinal()) % 4 else 0
        return [round((pid % 37) + d.day + 0.25, 2) if g else 0.0, g]

    def teams(self):
        return {"466.l.99999.t.1": {}}

    def to_team(self, key):
        rows = [{"name": n, "player_id": pid} for n, pid in self.roster.items()]
        return type("T", (), {"roster": lambda s: rows})()

    def player_stats(self, ids, kind, date=None):
        assert kind == "date" and len(ids) <= 25
        self.stat_calls.append((date, tuple(ids)))
        return [{"player_id": pid, "name": f"P{pid}", "position_type": "P",
                 "total_points": self.line(pid, date)[0]} for pid in ids]


@needs_state("data/player_actuals.json", "output/hub_state.json", "config/ROSTERS.json",
             "data/PLAYERLIST.xlsx", "data/transaction_log.jsonl",
             why="the nightly's actuals step on a copy of Nick's state: the free agents his hub names")
def test_the_real_actuals_step_covers_every_carded_free_agent(tmp_path, monkeypatch):
    base = tmp_path / "base"
    rels = ["data/player_actuals.json", "output/hub_state.json", "config/ROSTERS.json", "config/league_config.json",
            "data/PLAYERLIST.xlsx", "data/transaction_log.jsonl", "config/SCHEDULE.json"]
    rels += [p.relative_to(ROOT).as_posix() for p in (ROOT / "data").glob("nba_schedule_*.json")]
    for r in rels:
        (base / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / r, base / r)
    blob0 = pa.load(base)
    payload = json.loads((base / "output" / "hub_state.json").read_text(encoding="utf-8"))
    through = date.fromisoformat(payload["sources"]["actuals_through"])
    today = through + timedelta(days=1)
    roster = {n: int(p) for n, p in blob0["roster_names"].items()}
    lg = FakeLeague(roster)
    from modules import season_performers as sp
    monkeypatch.setattr(sp, "get_yahoo_league", lambda b: lg)
    # every rostered name must be on the fake league's roster: the real ROSTERS.json
    rosters = sp.load_rosters(base)
    if any(pa.find_days(blob0, n) is None for ns in rosters.values() for n in ns):
        pytest.skip("ROSTERS.json has a pickup the cache has not fetched yet: run the real fetch first")
    run = nightly.Run(base, "nightly", now=datetime.combine(today, datetime.min.time()).replace(
        hour=0, minute=5, tzinfo=LA), echo=lambda *a: None)
    detail = run.step_actuals()
    assert run.ctx["actuals"]["error"] is None, detail
    blob = pa.load(base)
    reg = payload["cards"]["players"]
    extras = [{"player_name": v["name"], "manager": ""} for v in reg.values() if v["kind"] != "rostered"]
    nba = hc.nba_lines(base, payload, [], extras)
    covered = [x["player_name"] for x in extras if nba["lines"][x["player_name"]] is not None]
    assert run.ctx["actuals"]["extras"] == len(covered)
    assert set(covered) | set(run.ctx["actuals"]["no_id"]) == {x["player_name"] for x in extras}
    for x in extras:
        n = x["player_name"]
        if nba["lines"][n] is None:
            assert nba["notes"][n] == pa.NOTE_NO_ID
    # the rostered players' cached days are exactly what they were: nothing re-asked for them
    rost_ids = set(roster.values())
    assert not any(set(ids) & rost_ids for _d, ids in lg.stat_calls)
    for pid in rost_ids:
        assert blob["players"][str(pid)]["days"] == blob0["players"][str(pid)]["days"]
    # Yahoo's two requests per batch, at most 25 players each; a name NEW to the cache is asked
    # from the season's first day. 44c: picked from the state -- before 40b's backfill every
    # carded free agent was new; after it (Nick, 11-13) none is, and nothing is asked at all
    assert len(lg.stat_calls) == len(lg.game_calls) and all(len(i) <= 25 for _d, i in lg.stat_calls)
    first = date.fromisoformat(blob["first_day"])
    known = {int(v) for v in (blob0.get("extra_names") or {}).values()} | set(roster.values())
    new = {int(v) for v in (blob.get("extra_names") or {}).values()} - known
    for pid in new:
        assert min(d for d, ids in lg.stat_calls if pid in {int(i) for i in ids}) == first, pid
    if not lg.stat_calls:
        print(f"\n  nothing to fetch on this state: every carded name is cached through {through}")
    assert run.ctx["actuals"]["calls"] == 2 * len(lg.stat_calls)


# =============================================================================
# s.2 the card loader: "reload" when the hub has moved on
# =============================================================================

def test_a_404_is_gone_and_gone_says_reload_in_the_page_and_the_shell():
    shell, page = hub_page.SHELL_JS, hub_page.PAGE_JS
    assert "if(r.status===404){throw new Error('gone');}" in shell
    assert "reload:function(){" in shell and "sessionStorage.setItem(RELOAD" in shell
    assert "if(err&&err.message==='gone'){movedBox();return;}" in page
    assert "The hub has been updated: reload the page to open player cards." in page
    assert "'That player card could not be opened.'" in page                 # every other failure
    # the photo goes through the same check (the modal drops a failed photo quietly)
    assert "window.HUB.photo(ref).catch(function(err){if(err&&err.message==='gone'){movedBox();}" in page


def _jsdom_env():
    node = shutil.which("node")
    if node is None:
        return None, None
    env = dict(os.environ)
    if os.environ.get("HUB_TEST_JSDOM"):
        env["NODE_PATH"] = os.environ["HUB_TEST_JSDOM"]
    ok = subprocess.run([node, "-e", "require.resolve('jsdom')"], env=env, capture_output=True).returncode == 0
    return (node, env) if ok else (None, None)


NODE, NODE_ENV = _jsdom_env()
needs_jsdom = pytest.mark.skipif(NODE is None, reason="node and jsdom are not installed here (NODE_PATH or "
                                                      "HUB_TEST_JSDOM): the published page is run in jsdom")


from test_player_cards import _cards_for, _payload_no_issue, pubbase  # noqa: E402,F401


@pytest.fixture
def published(pubbase):
    p = _payload_no_issue()
    cards = _cards_for(p, pubbase)
    out = pubbase / "pub"
    hub_publish.build(pubbase, p, TEST_PASS, cards=cards, iterations=1000, out_dir=out)
    bundle = json.loads(re.search(r'id="hub-bundle">(.*?)</script>', (out / "index.html").read_text()).group(1))
    inner = json.loads(hub_crypto.open_bundle(TEST_PASS, bundle))
    import gzip
    live = json.loads(gzip.decompress(hub_crypto.open_sealed(hub_crypto.unb64(inner["cards"]["key"]),
                                                             (out / inner["cards"]["file"]).read_bytes())))
    z = live["cards"]["zed-alpha"]
    return {"dir": out, "bundle": inner["cards"]["file"], "code": live["code"]["file"],
            "hist": z["hist"]["file"], "photo": z["photo"]["file"]}


def _page(pub, **scenario):
    r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "hub_loader.js"), str(pub["dir"]), TEST_PASS,
                        json.dumps(scenario)], env=NODE_ENV, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out.get("errors") == [], out
    return out


MOVED = "The hub has been updated: reload the page to open player cards. Reload"


@needs_jsdom
def test_jsdom_a_good_tap_opens_the_card(published):
    out = _page(published, tap="zed-alpha")
    assert out["mounted"] and out["prompted"] and out["modal"] and out["moved"] is None and out["alerts"] == []
    assert published["hist"] in out["asked"]


@needs_jsdom
@pytest.mark.parametrize("which", ["bundle", "code", "hist", "photo"])
def test_jsdom_a_gone_file_says_reload(published, which):
    out = _page(published, tap="zed-alpha", gone=[published[which]])
    assert out["moved"] == MOVED and out["moved_button"], out
    assert out["alerts"] == []                                             # not the old message


@needs_jsdom
def test_jsdom_a_decrypt_failure_keeps_the_old_message(published):
    out = _page(published, tap="zed-alpha", corrupt=[published["bundle"]])
    assert out["moved"] is None and out["alerts"] == ["That player card could not be opened."]


@needs_jsdom
def test_jsdom_reload_keeps_the_key_for_one_load_with_no_passphrase(published):
    out = _page(published, tap="zed-alpha", gone=[published["bundle"]], reload=True)
    held = json.loads(out["session_after_reload"])
    assert set(held) == {"salt", "key"}
    again = _page(published, session=out["session_after_reload"], tap="zed-alpha")
    assert again["prompted"] is False and again["mounted"] and again["modal"]
    # a key for another salt (a new passphrase) is not used: the form asks
    other = _page(published, session=json.dumps({"salt": "AAAA", "key": held["key"]}))
    assert other["prompted"] is True and other["mounted"]


# =============================================================================
# s.3 actions_minutes: only what GitHub bills
# =============================================================================

import actions_minutes as am  # noqa: E402

CSV_HEAD = ('"date","product","sku","quantity","unit_type","applied_cost_per_quantity","gross_amount",'
            '"discount_amount","net_amount","username","organization","repository","workflow_path",'
            '"cost_center_name"\n')


def _csv(tmp_path, rows):
    p = tmp_path / "usage.csv"
    p.write_text("﻿" + CSV_HEAD + "".join(
        f'"{d}","{prod}","actions_linux","{q}","{unit}","0.006","0","0","0","nickrolen","","{repo}","{wf}",""\n'
        for d, prod, q, unit, repo, wf in rows), encoding="utf-8")
    return p


def test_the_usage_report_counts_only_the_private_state_repo(tmp_path):
    p = _csv(tmp_path, [
        ("2026-11-12", "actions", 7, "minutes", "newsletter-state", ".github/workflows/nightly.yml"),
        ("2026-11-12", "actions", 5, "minutes", "newsletter-state", ".github/workflows/afternoon.yml"),
        ("2026-11-12", "actions", 42, "minutes", "fantasy-newsletter-engine", ".github/workflows/ci.yml"),
        ("2026-11-12", "actions", 9, "minutes", "newsletter-hub", "dynamic/pages/pages-build-deployment"),
        ("2026-11-12", "actions", 3, "GigabyteHours", "newsletter-state", ""),
    ])
    u = am.read_usage(p, ROOT)
    assert u["repos"] == {"counted": "newsletter-state", "free": ["fantasy-newsletter-engine", "newsletter-hub"]}
    sm = am.usage_summary(u)
    assert (sm["counted"], sm["free"]) == (12, 51) and u["other_rows"] == 1
    # the calibration: the plan's day beside the report's (the 11-12 plan: 4 nightly guards + a
    # 3-minute run; 3 afternoon guards + a 2-minute run)
    cal = {c["workflow"]: c for c in am.calibrate(u, ROOT)}
    assert (cal["nightly.yml"]["actual"], cal["nightly.yml"]["model"]) == (7, 7.0)
    assert (cal["afternoon.yml"]["actual"], cal["afternoon.yml"]["model"]) == (5, 5.0)
    bad = _csv(tmp_path, [("2026-11-12", "actions", 1, "minutes", "someone-elses-repo", "x.yml")])
    with pytest.raises(ValueError, match="someone-elses-repo"):
        am.read_usage(bad, ROOT)


def test_each_job_is_billed_rounded_up_and_the_advice_step_counts():
    assert am.run_job_minutes("nightly", 0) == math.ceil((am.SETUP_SECONDS[0] + am.RUN_SECONDS["nightly"][0]
                                                          + am.ADVICE_SECONDS[0]) / 60) == 3
    assert am.run_job_minutes("afternoon_unchanged", 0) == math.ceil(
        (am.SETUP_SECONDS[0] + am.RUN_SECONDS["afternoon_unchanged"][0]) / 60)      # prices nothing: no advice
    assert am.GUARD_MIN == (1, 1)


def test_the_estimate_is_the_state_repos_workflows_and_fits_the_free_minutes():
    e = am.estimate(date(2026, 11, 16), ROOT)
    for r in e["estimates"]:
        assert set(r["by_workflow"]) == {"nightly.yml", "pretip.yml", "afternoon.yml",
                                         "entry.yml + overrides-push.yml"}
        assert abs(r["total"] - sum(r["by_workflow"].values())) <= 2           # rounding only
    typ = e["estimates"][0]
    assert 500 <= typ["total"] <= 900 and e["estimates"][1]["total"] < am.FREE_MINUTES


def test_the_usage_csv_command_prints_counted_and_free(tmp_path, capsys):
    p = _csv(tmp_path, [("2026-11-12", "actions", 7, "minutes", "newsletter-state", ".github/workflows/nightly.yml"),
                        ("2026-11-12", "actions", 42, "minutes", "fantasy-newsletter-engine", ".github/workflows/ci.yml")])
    assert am.main(["--usage-csv", str(p)]) == 0
    out = capsys.readouterr().out
    assert "COUNTED 7" in out and "free 42" in out and "actual    7  model    7.0" in out
