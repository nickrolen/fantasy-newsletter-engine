"""4a3: minutes stored beside the daily lines, and MIN and MIN delta on the new
hub (modules/player_actuals, modules/nightly, modules/hub_v2/players, roster,
card, page_players; claude/HANDOFF_4A3_MINUTES_2026-11-19.md).

1. Yahoo's minutes: "30", "30:12", "-", and anything else raises
2. the checks: minutes without games, games without minutes, over 70, the
   legal zero-minute cameo; each names the player and the day
3. the schema: old files still read, new days validate, and "days" and
   "cat_days" are byte-identical to the code before 4a3 for the same inputs
4. the nightly keeps each day's minutes at no extra call; a minutes problem
   never costs the points or the categories
5. the backfill: the cap, oldest first, all or nothing per day, never a
   refetch, idle players free; its failure is soft and loud, nightly only
6. the hub: MIN and MIN delta (values, reasons, the payload orders), the
   card's last-5 MIN and Season line, Compare's MIN row, the 4b/4c rules
7. the real thing, unstubbed: today's cache, every MIN cell before the
   backfill, and the live hub unchanged by minutes
No network: fake Yahoo leagues only.
"""
import json
import re
import subprocess
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import league_state                                    # noqa: F401
from modules import nightly
from modules import player_actuals as pa
from modules.hub_v2 import players as P, roster as R, card as C, page_players as PP, infotips, publish as v2pub
from test_4a2_category_stats import line, points, ORDER, VALUES, HEADER, FIRST, SEASON, v1_blob
from test_hub_v2 import synth_payload, render, visible_text, strings, tap_violations, budget_bytes, ROOT
from test_hub_v2_players import synth_cards
from test_hub_v2_teams import team_world

LA = ZoneInfo("America/Los_Angeles")
DASH = "\u2014"
MINUS = "\u2212"
PRE_4A3 = "f8b8232"               # the commit before 4a3: its player_actuals is "the code before"


def base(tmp_path, cap=20, min_cap=20) -> Path:
    b = tmp_path / "base"
    for d in ("config", "data", "output"):
        (b / d).mkdir(parents=True, exist_ok=True)
    cfg = {"actuals": {"extra_players_max": 150, "category_backfill_calls_max": cap,
                       "minutes_backfill_calls_max": min_cap},
           "yahoo_settings": {"stat_values": dict(zip(ORDER, VALUES))}}
    (b / "config" / "league_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return b


def iso(i: int) -> str:
    return (FIRST + timedelta(days=i)).isoformat()


class MinLeague:
    """yahoo_fantasy_api's League as YahooSource uses it, with minutes: the
    league-scoped rows (categories, total_points) and the game-scoped stat 0
    and stat 2. lines: {(pid, iso): counts}; mins: {(pid, iso): Yahoo's raw
    stat 2} (absent: no stat 2 in the response); gp_now: {(pid, iso): stat 0
    now}; game_fail_after: the game-scoped request fails after N calls."""

    def __init__(self, lines, mins, gp_now=None, game_fail_after=None):
        self.league_id = "466.l.99999"
        self.lines, self.mins = lines, mins
        self.gp_now = gp_now or {}
        self.game_fail_after = game_fail_after
        self.stat_calls, self.game_calls = [], []
        lg = self

        class H:
            def get(self, url):
                if lg.game_fail_after is not None and len(lg.game_calls) >= lg.game_fail_after:
                    raise RuntimeError("Yahoo is down")
                d = url.split("date=")[1]
                keys = url.split("player_keys=")[1].split("/")[0].split(",")
                lg.game_calls.append((d, tuple(int(k.split(".p.")[1]) for k in keys)))
                players = {"count": len(keys)}
                for i, k in enumerate(keys):
                    pid = int(k.split(".p.")[1])
                    g = 1 if any(lg.lines.get((pid, d), [0])) else 0
                    g = lg.gp_now.get((pid, d), g)
                    stats = [{"stat": {"stat_id": "0", "value": str(g) if g in (0, 1) else g}}]
                    if (pid, d) in lg.mins:
                        stats.append({"stat": {"stat_id": "2", "value": lg.mins[(pid, d)]}})
                    players[str(i)] = {"player": [[{"player_id": str(pid)}], {"player_stats": {"stats": stats}}]}
                return {"fantasy_content": {"players": players}}
        self.yhandler = H()

    def player_stats(self, ids, kind, date=None):
        d = date.isoformat()
        self.stat_calls.append((d, tuple(ids)))
        rows = []
        for pid in ids:
            c = self.lines.get((pid, d), [0] * 11)
            played = any(c)
            r = {"player_id": pid, "name": f"P{pid}", "total_points": points(c)}
            r.update({k: (float(v) if played else "-") for k, v in zip(ORDER, c)})
            rows.append(r)
        return rows


def world(n_players=2, n_days=3, idle=lambda p, i: i == 1, mins=None):
    """(lines, Yahoo's minutes): idle days are "-"; played days "M:SS"."""
    lines, mm = {}, {}
    for p in range(1, n_players + 1):
        for i in range(n_days):
            played = not idle(p, i)
            lines[(p, iso(i))] = line(p * 7 + i, played)
            mm[(p, iso(i))] = (f"{20 + p + i}:{(p * 13 + i * 7) % 60:02d}" if played else "-")
    if mins:
        mm.update(mins)
    return lines, mm


def want_minutes(raw: str, played: bool) -> int:
    if not played:
        return 0
    m, s = raw.split(":")
    return int(m) + (1 if int(s) >= 30 else 0)


# =============================================================================
# 1-2. Yahoo's minutes and the checks
# =============================================================================

@pytest.mark.parametrize("raw,games,want", [
    ("30", 1, 30), ("30:12", 1, 30), ("30:29", 1, 30), ("30:30", 1, 31), ("65", 1, 65), ("65:00", 1, 65),
    ("-", 0, 0), ("", 0, 0), (None, 0, 0), ("0", 0, 0), ("0:00", 0, 0), (31, 1, 31),
    ("0", 1, 0), ("0:20", 1, 0)])                         # the last two: a cameo, legal
def test_yahoos_minutes_parse(raw, games, want):
    assert pa.parse_minutes(raw, "Zed Alpha", "2026-10-21", games) == want


@pytest.mark.parametrize("raw", ["30.5", "abc", "30:61", "30:5", "-3", "3O", " ", "1:2:3", True, 30.0, [30]])
def test_anything_else_raises(raw):
    with pytest.raises(pa.MinutesError, match="Zed Alpha.*|.*Zed Alpha"):
        pa.parse_minutes(raw, "Zed Alpha", "2026-10-21", 1)


def test_the_checks_raise_naming_the_player_and_the_day():
    with pytest.raises(pa.MinutesError, match=r"2026-10-21 line for Zed Alpha: '5' minutes and no game played"):
        pa.parse_minutes("5", "Zed Alpha", "2026-10-21", 0)                 # minutes without games
    for raw in ("-", None, ""):
        with pytest.raises(pa.MinutesError, match=r"2026-10-21 line for Zed Alpha: games played 1 and no minutes"):
            pa.parse_minutes(raw, "Zed Alpha", "2026-10-21", 1)            # games without minutes
    for raw in ("71", "70:30", "99:00"):
        with pytest.raises(pa.MinutesError, match=r"2026-10-21 line for Zed Alpha: .* over 70"):
            pa.parse_minutes(raw, "Zed Alpha", "2026-10-21", 1)
    assert pa.MIN_MAX == 70 and issubclass(pa.MinutesError, pa.ActualsError)


def test_a_zero_minute_cameo_is_legal_stored_and_counted():
    blob = v1_blob({1: ("Zed Alpha", {iso(0): [points(line(1)), 1], iso(1): [12.0, 1]})})
    blob["players"]["1"]["min_days"] = {iso(0): 0, iso(1): 20}            # games 1, 0 minutes: a cameo
    pa.validate(blob)
    st = pa.minutes_games(blob, "Zed Alpha", FIRST, FIRST + timedelta(days=1))
    assert st["status"] == "ok" and st["games"] == [(iso(0), 0), (iso(1), 20)]
    c = P.minutes_cells(blob, "Zed Alpha", FIRST, FIRST + timedelta(days=1), FIRST, [iso(0), iso(1)])
    assert c["min"] == "10.0" and c["min_k"] == 100                        # the cameo is one of his 2 games


# =============================================================================
# 3. the schema
# =============================================================================

def test_old_files_still_read_and_no_reader_of_the_points_sees_the_minutes():
    days = {iso(i): [points(line(i + 3)), 1] for i in range(5)}
    days[iso(2)] = [0.0, 0]
    v1 = v1_blob({1: ("Zed Alpha", days)})
    pa.validate(v1)                                                         # version 1
    v2 = json.loads(json.dumps(v1))
    pa.ensure_cats(v2, HEADER)
    pa.validate(v2)                                                         # version 2, no minutes
    assert v2["version"] == 2 and pa.VERSION == 2 and pa.READS == (1, 2)
    m = json.loads(json.dumps(v2))
    m["players"]["1"]["min_days"] = {d: (0 if v[1] == 0 else 33) for d, v in days.items()}
    pa.validate(m)
    last = FIRST + timedelta(days=4)
    for blob in (v1, v2):
        assert pa.season(blob, "Zed Alpha", last) == pa.season(m, "Zed Alpha", last)
        assert pa.last14(blob, "Zed Alpha", last) == pa.last14(m, "Zed Alpha", last)
        assert pa.card_lines(blob, ["Zed Alpha"], last) == pa.card_lines(m, ["Zed Alpha"], last)
        assert pa.minutes_games(blob, "Zed Alpha", FIRST, last)["status"] == "loading"
    assert pa.category_season(v2, "Zed Alpha", FIRST, last) == pa.category_season(m, "Zed Alpha", FIRST, last)
    assert pa.minutes_games(m, "Zed Alpha", FIRST, last) == {"status": "ok", "day": None,
                                                              "games": [(iso(i), 33) for i in (0, 1, 3, 4)]}


def test_new_days_validate_and_bad_ones_raise_naming_him():
    blob = v1_blob({1: ("Zed Alpha", {iso(0): [10.0, 1], iso(1): [0.0, 0]})})
    blob["players"]["1"]["min_days"] = {iso(0): 30, iso(1): 0}
    pa.validate(blob)
    for bad, why in (({iso(0): 71}, "not whole minutes from 0 to 70"), ({iso(0): 30.5}, "not whole minutes"),
                     ({iso(0): True}, "not whole minutes"), ({iso(0): -1}, "not whole minutes"),
                     ({iso(1): 4}, "has 4 minutes and no game"), ({iso(5): 30}, "a day with no points cached")):
        b = json.loads(json.dumps(blob))
        b["players"]["1"]["min_days"] = bad
        if bad.get(iso(0)) is True:
            b["players"]["1"]["min_days"] = {iso(0): True}
        with pytest.raises(pa.ActualsError, match=f"Zed Alpha.*{why}"):
            pa.validate(b)
    b = json.loads(json.dumps(blob))
    b["players"]["1"]["min_days"] = [30]
    with pytest.raises(pa.ActualsError, match="Zed Alpha's min_days is malformed"):
        pa.validate(b)


def _pre_4a3_module():
    """modules/player_actuals.py as of PRE_4A3, executed from git (no file is
    written): "the code before" for the byte-identical test."""
    try:
        r = subprocess.run(["git", "show", f"{PRE_4A3}:modules/player_actuals.py"], cwd=ROOT,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("git is not available")
    if r.returncode != 0:
        pytest.skip(f"no git history for {PRE_4A3}")
    mod = types.ModuleType("modules._player_actuals_pre_4a3")
    mod.__package__ = "modules"
    mod.__file__ = str(ROOT / "modules" / "_player_actuals_pre_4a3.py")
    exec(compile(r.stdout, mod.__file__, "exec"), mod.__dict__)
    assert not hasattr(mod, "parse_minutes")
    return mod


def test_days_and_cat_days_are_byte_identical_to_the_code_before_4a3(tmp_path):
    old = _pre_4a3_module()
    lines, mins = world(n_players=30, n_days=3, idle=lambda p, i: (p + i) % 4 == 0)
    mins[(3, iso(2))] = "-"                                 # one day's minutes fail: points and categories stay
    ids = {f"Player {p}": p for p in range(1, 31)}
    out = {}
    for name, mod in (("new", pa), ("old", old)):
        b = base(tmp_path / name)
        r = mod.update(b, source=mod.YahooSource(MinLeague(lines, mins)), ids=ids, today=FIRST + timedelta(days=3),
                       first_day=FIRST, season=SEASON, echo=lambda *a: None)
        blob = json.loads((b / "data" / "player_actuals.json").read_text(encoding="utf-8"))
        out[name] = (r, blob)
    (rn, new), (ro, old_blob) = out["new"], out["old"]
    assert rn["calls"] == ro["calls"] == 2 * 2 * 3                          # 2 batches, 2 requests, 3 days
    for k in ("days", "cat_days"):
        a = json.dumps({p: rec.get(k) for p, rec in sorted(new["players"].items())}, sort_keys=True)
        b = json.dumps({p: rec.get(k) for p, rec in sorted(old_blob["players"].items())}, sort_keys=True)
        assert a == b, k
    assert all("min_days" not in rec for rec in old_blob["players"].values())
    assert len(rn["min_errors"]) == 1 and "Player 3" in rn["min_errors"][0]
    have = {d for rec in new["players"].values() for d in rec.get("min_days", {})}
    # day 2's minutes failed for Player 3: no one's minutes that day (all or nothing, both batches)
    assert have == {iso(0), iso(1)}


# =============================================================================
# 4. the nightly's fetch
# =============================================================================

def test_the_nightly_fetch_keeps_each_days_minutes_at_no_extra_call(tmp_path):
    b = base(tmp_path)
    lines, mins = world()
    lg = MinLeague(lines, mins)
    r = pa.update(b, source=pa.YahooSource(lg), ids={"Zed Alpha": 1, "Yan Beta": 2}, today=FIRST + timedelta(days=3),
                  first_day=FIRST, season=SEASON, echo=lambda *a: None)
    assert r["min_errors"] == [] and r["cat_errors"] == [] and r["calls"] == 6       # 2 a day, as before
    assert len(lg.game_calls) == 3
    blob = pa.load(b)
    for (p, d), raw in mins.items():
        played = blob["players"][str(p)]["days"][d][1] == 1
        assert blob["players"][str(p)]["min_days"][d] == want_minutes(raw, played)
    assert blob["players"]["1"]["min_days"][iso(1)] == 0                              # a day he did not play


@pytest.mark.parametrize("bad,why", [("-", "games played 1 and no minutes"), ("71", "over 70"),
                                     ("x", "not \"30\""), (None, "games played 1 and no minutes")])
def test_a_minutes_problem_never_costs_the_points_or_the_categories(tmp_path, bad, why):
    b = base(tmp_path)
    lines, mins = world(idle=lambda p, i: False)
    if bad is None:
        del mins[(2, iso(1))]                               # no stat 2 at all
    else:
        mins[(2, iso(1))] = bad
    r = pa.update(b, source=pa.YahooSource(MinLeague(lines, mins)), ids={"Zed Alpha": 1, "Yan Beta": 2},
                  today=FIRST + timedelta(days=3), first_day=FIRST, season=SEASON, echo=lambda *a: None)
    assert len(r["min_errors"]) == 1 and r["min_errors"][0].startswith("2026-10-21: ")
    assert "Yan Beta" in r["min_errors"][0] and why in r["min_errors"][0]
    blob = pa.load(b)
    for p in (1, 2):
        rec = blob["players"][str(p)]
        assert rec["days"][iso(1)][0] == points(line(p * 7 + 1)) and rec["cat_days"][iso(1)] == line(p * 7 + 1)
        assert iso(1) not in rec["min_days"] and iso(0) in rec["min_days"]            # all or nothing, per day


def test_the_extras_pass_keeps_minutes_too(tmp_path):
    b = base(tmp_path)
    lines, mins = world(n_players=3)
    src = pa.YahooSource(MinLeague(lines, mins))
    r = pa.update(b, source=src, ids={"Zed Alpha": 1}, today=FIRST + timedelta(days=3), first_day=FIRST,
                  season=SEASON, echo=lambda *a: None)
    x = pa.update_extras(b, source=src, rostered=r["ids"], today=FIRST + timedelta(days=3),
                         extras={"ids": {"Free Guy": 3}, "no_id": [], "from": "x", "cap": 150}, header=r["header"])
    assert x["min_errors"] == []
    assert pa.load(b)["players"]["3"]["min_days"] == {d: want_minutes(mins[(3, d)], any(lines[(3, d)]))
                                                      for d in (iso(0), iso(1), iso(2))}


# =============================================================================
# 5. the backfill
# =============================================================================

def backfill_world(tmp_path, n_players=30, n_days=4, min_cap=20, idle=lambda p, i: (p + i) % 3 == 0, **kw):
    """A version-2 cache with categories and no minutes (n_players x n_days),
    and the league that holds its minutes."""
    b = base(tmp_path, min_cap=min_cap)
    lines, mins = world(n_players, n_days, idle)
    players = {p: (f"Player {p}", {iso(i): [points(lines[(p, iso(i))]), 1 if any(lines[(p, iso(i))]) else 0]
                                   for i in range(n_days)}) for p in range(1, n_players + 1)}
    blob = v1_blob(players)
    pa.ensure_cats(blob, HEADER)
    for p in players:
        blob["players"][str(p)]["cat_days"] = {iso(i): lines[(p, iso(i))] for i in range(n_days)}
    pa.write(b, blob, FIRST + timedelta(days=n_days))
    return b, lines, mins, MinLeague(lines, mins, **kw)


def _days_with_minutes(b):
    return {d for rec in pa.load(b)["players"].values() for d in rec.get("min_days", {})}


def test_the_backfill_respects_the_cap_oldest_first_and_never_refetches(tmp_path):
    b, lines, mins, lg = backfill_world(tmp_path, min_cap=3)        # 20 of 30 play a day: 1 call a day
    today = FIRST + timedelta(days=4)
    before = pa.load(b)
    plan = pa.backfill_minutes(b, today=today, dry_run=True)
    assert plan["calls_needed"] == 4 and plan["days_missing"] == 4 and plan["cap"] == 3
    src = pa.YahooSource(lg)
    r1 = pa.backfill_minutes(b, source=src, today=today)
    assert r1["calls"] == 3 and r1["days_done"] == [iso(0), iso(1), iso(2)]
    assert r1["days_left"] == 1 and "cap" in r1["stopped"]
    assert lg.stat_calls == []                                       # the game-scoped request only
    blob = pa.load(b)
    for (p, d), raw in mins.items():
        played = blob["players"][str(p)]["days"][d][1] == 1
        got = blob["players"][str(p)].get("min_days", {}).get(d)
        assert got == (want_minutes(raw, played) if d <= iso(2) else None)
    for pid, rec in blob["players"].items():                          # the points and categories untouched
        assert rec["days"] == before["players"][pid]["days"] and rec["cat_days"] == before["players"][pid]["cat_days"]
    r2 = pa.backfill_minutes(b, source=src, today=today)
    assert r2["days_done"] == [iso(3)] and r2["days_left"] == 0
    asked = [d for d, _ids in lg.game_calls]
    assert asked == sorted(asked) and len(asked) == len(set(asked)) == 4     # each day once, oldest first
    n = len(lg.game_calls)
    r3 = pa.backfill_minutes(b, source=src, today=today)
    assert r3["days_done"] == [] and r3["calls"] == 0 and len(lg.game_calls) == n


def test_the_idle_players_get_zero_with_no_call(tmp_path):
    b, lines, mins, lg = backfill_world(tmp_path, n_players=3, n_days=2, idle=lambda p, i: True)
    r = pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=2))
    assert r["calls"] == 0 and lg.game_calls == [] and len(r["days_done"]) == 2
    assert pa.load(b)["players"]["1"]["min_days"] == {iso(0): 0, iso(1): 0}


def test_a_failure_writes_nothing_for_its_day_and_keeps_the_days_before(tmp_path):
    b, lines, mins, lg = backfill_world(tmp_path, n_players=40, idle=lambda p, i: False, game_fail_after=3)
    with pytest.raises(pa.ActualsError, match="Yahoo request for 2026-10-21's minutes failed"):
        pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    assert _days_with_minutes(b) == {iso(0)}                          # 10-21's first batch came back: not written


@pytest.mark.parametrize("kw,match", [
    ({"mins": {(3, "2026-10-21"): "-"}}, "Player 3: games played 1 and no minutes"),
    ({"mins": {(3, "2026-10-21"): "80"}}, "Player 3: '80' minutes, over 70"),
    ({"gp_now": {(3, "2026-10-21"): 0}}, "Player 3 now says games played '0', but the cache has him playing"),
])
def test_a_bad_or_changed_line_refuses_its_day_naming_him(tmp_path, kw, match):
    mins_over = kw.pop("mins", None)
    b, lines, mins, lg = backfill_world(tmp_path, n_players=5, idle=lambda p, i: False, **kw)
    if mins_over:
        lg.mins.update(mins_over)
    with pytest.raises(pa.MinutesError, match=f"2026-10-21 line for {match}".replace("(", r"\(")):
        pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    assert _days_with_minutes(b) == {iso(0)}


def test_a_day_bigger_than_the_cap_raises_and_the_cap_is_required(tmp_path):
    b, lines, mins, lg = backfill_world(tmp_path, n_players=60, n_days=1, min_cap=2, idle=lambda p, i: False)
    with pytest.raises(pa.ActualsError, match="minutes need 3 calls .*minutes_backfill_calls_max .*raise the cap"):
        pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=1))
    cfg = json.loads((b / "config" / "league_config.json").read_text())
    del cfg["actuals"]["minutes_backfill_calls_max"]
    (b / "config" / "league_config.json").write_text(json.dumps(cfg))
    with pytest.raises(pa.ActualsError, match="minutes_backfill_calls_max"):
        pa.minutes_cap(b)
    assert pa.minutes_cap(ROOT) >= 4                                   # at least today's busiest day


# ---- the nightly: soft and loud, the nightly run only

class _Src:
    def cats_day(self, *a, **k):
        raise AssertionError("stubbed")

    def minutes_day(self, *a, **k):
        raise AssertionError("stubbed")


def _step(tmp_path, monkeypatch, mode, backfill, min_errors=(), extras_min_errors=()):
    b = base(tmp_path)
    called = []
    monkeypatch.setattr(pa, "update", lambda *a, **k: {
        "through": "2026-10-22", "days_fetched": ["2026-10-22"], "calls": 2, "backfilled": [], "ids": {},
        "source": _Src(), "header": HEADER, "cat_errors": [], "min_errors": list(min_errors)})
    monkeypatch.setattr(pa, "update_extras", lambda *a, **k: {
        "players": 0, "no_id": [], "days_fetched": [], "calls": 0, "backfilled": [], "cap": 150,
        "cat_errors": [], "min_errors": list(extras_min_errors)})
    monkeypatch.setattr(pa, "backfill_categories", lambda *a, **k: {
        "days_done": [], "days_left": 0, "calls": 0, "cap": 20, "corrections": [], "stopped": None})

    def bf(*a, **k):
        called.append(k)
        return backfill()
    monkeypatch.setattr(pa, "backfill_minutes", bf)
    hour = 0 if mode == "nightly" else 15
    run = nightly.Run(b, mode, now=datetime(2026, 10, 23, hour, 5, tzinfo=LA), echo=lambda *a: None)
    detail = run.step_actuals()
    return run, detail, called


def test_the_nightly_records_a_minutes_failure_loudly_and_goes_on(tmp_path, monkeypatch):
    def boom():
        raise pa.MinutesError("Yahoo's 2026-10-20 line for Zed: '80' minutes, over 70: misread")
    run, detail, called = _step(tmp_path, monkeypatch, "nightly", boom,
                                min_errors=["2026-10-22: Yahoo's 2026-10-22 line for Zed: games played 1 and no minutes"],
                                extras_min_errors=["2026-10-22: Yahoo's 2026-10-22 line for Free Guy: 'x' ..."])
    assert called and "minutes' backfill FAILED" in detail and "2 day(s) of minutes FAILED" in detail
    mins = run.ctx["actuals"]["minutes"]
    assert mins["error"].startswith("MinutesError") and len(mins["errors"]) == 2 and mins["backfill"] is None
    lines = run.ctx["actuals_lines"]
    assert len(lines) == 3 and all(x.startswith("MINUTES FAILED") for x in lines)
    assert "points and categories are written" in lines[0] and lines[-1].endswith("MIN and MIN delta wait")
    assert all(x.isascii() for x in lines)                              # printed on a Windows console too
    assert run.ctx["actuals"]["error"] is None and run.ctx["actuals"]["categories"]["error"] is None


def test_a_good_nights_minutes_backfill_is_recorded(tmp_path, monkeypatch):
    ok = {"days_done": [iso(0)], "days_left": 3, "calls": 4, "cap": 20, "corrections": [], "stopped": None}
    run, detail, called = _step(tmp_path, monkeypatch, "nightly", lambda: dict(ok, seconds=0.1, days_missing=4))
    assert run.ctx["actuals"]["minutes"]["backfill"] == ok
    assert "minutes backfilled 1 day(s), 4 call(s), 3 day(s) left" in detail and run.ctx["actuals_lines"] == []


def test_only_the_nightly_run_backfills_minutes(tmp_path, monkeypatch):
    run, detail, called = _step(tmp_path, monkeypatch, "pretip", lambda: {})
    assert called == [] and run.ctx["actuals"]["minutes"]["backfill"] is None


def test_the_desk_script_lists_a_minutes_failure_and_exits_1(tmp_path, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("fetch_player_actuals_4a3", ROOT / "scripts" / "fetch_player_actuals.py")
    fpa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fpa)
    monkeypatch.setattr(pa, "update", lambda *a, **k: {
        "through": "2026-10-22", "days_fetched": [], "calls": 0, "seconds": 0.0, "backfilled": [], "players": 1,
        "ids": {}, "source": None, "header": None, "cat_errors": [], "min_errors": ["2026-10-22: Zed: no minutes"]})
    monkeypatch.setattr(pa, "update_extras", lambda *a, **k: {
        "players": 0, "no_id": [], "from": "x", "cap": 150, "backfilled": [], "missing_days": {}, "days_fetched": [],
        "calls": 0, "seconds": 0.0, "cat_errors": [], "min_errors": []})
    assert fpa.main(["--base-path", str(tmp_path)]) == 1
    assert "MINUTES FAILED: 2026-10-22: Zed: no minutes" in capsys.readouterr().out


# =============================================================================
# 6. the hub
# =============================================================================

def _cache(spec: dict, through: date) -> dict:
    """spec: {name: [(day index, minutes or None (no minutes stored) or "dnp")]}."""
    players = {}
    for k, (n, games) in enumerate(spec.items(), 1):
        days, md = {}, {}
        for i in range((through - FIRST).days + 1):
            days[iso(i)] = [0.0, 0]
            md[iso(i)] = 0
        for i, m in games:
            days[iso(i)] = [20.0, 1]
            if m is None:
                del md[iso(i)]
            else:
                md[iso(i)] = m
        players[k] = (n, days)
        players[k] = (n, days)
        players[k] = (n, days)
    blob = v1_blob(players)
    for k, (n, games) in enumerate(spec.items(), 1):
        md = {d: 0 for d in blob["players"][str(k)]["days"]}
        for i, m in games:
            if m is None:
                md.pop(iso(i))
            else:
                md[iso(i)] = m
        blob["players"][str(k)]["min_days"] = md
    pa.validate(blob)
    return blob


THROUGH = FIRST + timedelta(days=29)                       # 30 days; the last 14 start at day 16
L14 = THROUGH - timedelta(days=13)


def _cells(blob, name):
    played = [d for d, v in sorted(pa.find_record(blob, name)["days"].items()) if v[1] == 1]
    return P.minutes_cells(blob, name, FIRST, THROUGH, L14, played)


def test_min_and_min_delta_values_and_reasons():
    blob = _cache({
        "Steady": [(i, 24) for i in range(0, 12)] + [(i, 30) for i in range(16, 20)],   # 12 earlier, 4 in the 14
        "Few": [(i, 30) for i in range(0, 10)] + [(16, 10), (18, 12), (20, 14)],            # 3 in the 14
        "One": [(i, 30) for i in range(0, 10)] + [(25, 9)],
        "New": [(i, 28) for i in range(17, 23)],                                            # all in the 14
        "Down": [(i, 36) for i in range(0, 6)] + [(i, 20) for i in range(20, 26)],
        "Loading": [(0, None), (1, 30)] + [(i, 31) for i in range(20, 25)],                 # day 0 lacks minutes
        "Idle": []}, THROUGH)
    s = _cells(blob, "Steady")
    assert (s["min"], s["min_k"], s["mind"], s["mind_k"]) == ("25.5", 255, "+4.5", 45)       # (12*24+4*30)/16
    f = _cells(blob, "Few")
    assert f["min"] == "25.8" and (f["mind"], f["mind_k"]) == ("3 of 4 games", None)
    assert _cells(blob, "One")["mind"] == "1 of 4 games"
    n = _cells(blob, "New")
    assert n["min"] == "28.0" and (n["mind"], n["mind_k"]) == ("no earlier games", None)       # never a made-up 0
    d = _cells(blob, "Down")
    assert (d["min"], d["mind"], d["mind_k"]) == ("28.0", f"{MINUS}8.0", -80)
    ld = _cells(blob, "Loading")
    assert (ld["min"], ld["min_k"], ld["mind"], ld["mind_k"]) == ("loading", None, "loading", None)
    assert ld["min_g"] == {iso(i): "31" for i in range(20, 25)} | {iso(1): "30"}             # the last 10 that have them
    i = _cells(blob, "Idle")
    assert (i["min"], i["min_k"], i["mind"], i["mind_k"]) == (DASH, None, DASH, None)
    assert P.minutes_cells(blob, "Nobody", FIRST, THROUGH, L14, [])["min"] == DASH          # never cached
    assert P.MIN_DELTA_GAMES == 4 and P.MIN_LAST == 10
    for c in (s, f, n, d, ld, i):
        assert "0" != c["min"] and not c["min"].startswith("0.0") and c["mind"] not in ("0", "0.0", "+0.0")


@pytest.fixture(scope="module")
def synm():
    """The synthetic league (tests/test_hub_v2.py) with minutes in its cache:
    24 a game before the last 14 days, 30 in them, 0 on a day off."""
    with pytest.MonkeyPatch.context() as mp:
        orig = pa.find_record

        def fr(blob, name):
            rec = orig(blob, name)
            if rec is not None and "min_days" not in rec:
                last = max(rec["days"])
                l14 = (date.fromisoformat(last) - timedelta(days=13)).isoformat()
                rec["min_days"] = {d: (0 if v[1] == 0 else (30 if d >= l14 else 24)) for d, v in rec["days"].items()}
            return rec
        mp.setattr(pa, "find_record", fr)
        p = synth_payload()
    return p, synth_cards(p)


def test_the_roster_prints_the_players_rows_minutes_and_follows_their_orders(synm):
    p, _ = synm
    rows = {z["name"]: z for z in p["v2"]["players"]["rows"]}
    keys = p["v2"]["roster_cols"]["keys"]
    form = next(g for g in p["v2"]["roster_cols"]["groups"] if g["key"] == "form")["cols"]
    assert form[-2:] == ["min", "mind"]
    seen = set()
    for m, t in p["v2"]["teams"].items():
        det = t["roster"]["detail"]
        names = [x["name"] for x in p["rosters"][m]["players"]]
        for k, kk in (("min", "min_k"), ("mind", "mind_k")):
            col = keys.index(k)
            for i, n in enumerate(names):
                assert det["rows"][i][col] == rows[n][k]                      # one string everywhere
                seen.add(rows[n][k])
            have = [i for i in det["orders"][k] if rows[names[i]][kk] is not None]
            miss = [i for i in det["orders"][k] if rows[names[i]][kk] is None]
            assert det["orders"][k] == have + miss                           # a missing value last
            ks = [rows[names[i]][kk] for i in have]
            assert ks == sorted(ks, reverse=True)                            # more minutes first
    assert any(re.fullmatch(r"\d+\.\d", s) for s in seen) and any(s.startswith("+") for s in seen)


def test_the_roster_cells_say_why_and_sort_by_the_payload(tmp_path):
    payload, ctx = team_world(tmp_path)
    vals = {"P One": ("26.4", 264, "+3.6", 36), "P Two": ("loading", None, "loading", None),
            "P Three": ("31.0", 310, "3 of 4 games", None), "P Four": ("20.0", 200, "no earlier games", None)}
    for z in ctx["players_block"]["rows"]:
        z["min"], z["min_k"], z["mind"], z["mind_k"] = vals[z["name"]]
    shared, out = R.build(tmp_path, payload, ctx)
    d = out["M"]
    k1, k2 = shared["keys"].index("min"), shared["keys"].index("mind")
    assert [r[k1] for r in d["rows"]] == ["26.4", "loading", "31.0", "20.0"]
    assert [r[k2] for r in d["rows"]] == ["+3.6", "loading", "3 of 4 games", "no earlier games"]
    assert d["orders"]["min"] == [2, 0, 3, 1] and d["orders"]["mind"] == [0, 1, 2, 3]
    assert shared["cols"]["min"]["label"] == "MIN" and shared["cols"]["mind"]["label"] == "MIN \u0394"
    assert "loading" in shared["why"]["min"] and "loading" in shared["why"]["mind"]
    del ctx["players_block"]["rows"][0]["mind_k"]
    with pytest.raises(R.RosterError, match="P One .*no minutes .*rebuild it"):
        R.build(tmp_path, payload, ctx)


def test_before_the_backfill_every_min_cell_says_loading():
    p = synth_payload()                                       # its cache has no minutes
    for z in p["v2"]["players"]["rows"]:
        if z["fppg"] != DASH:
            assert (z["min"], z["min_k"], z["mind"], z["mind_k"]) == ("loading", None, "loading", None)
    keys = p["v2"]["roster_cols"]["keys"]
    for t in p["v2"]["teams"].values():
        for r in t["roster"]["detail"]["rows"]:
            assert r[keys.index("min")] == "loading" and r[keys.index("mind")] == "loading"


def test_the_page_shows_min_and_min_delta_in_form(synm):
    p, _ = synm
    h = render(p)
    for k in ("min", "mind"):
        assert re.search(rf'<th class="v2-dc v2-g-form v2-g-all" data-k="d_{k}"><button type="button" class="v2-tap" '
                         rf'data-sort="d_{k}" data-colh="roster\|{k}"', h)          # 5d1 s.5: + its definition
    assert "<b>MIN</b>: Minutes per game in his NBA games this season." in h
    assert "<b>MIN \u0394</b>: His minutes per game over the last 14 days minus his season" in h


def test_compares_min_row_more_is_better(synm):
    p, _ = synm
    pl = p["v2"]["players"]
    labels = [r["label"] for r in pl["cmp_rows"]]
    i = labels.index("MIN")
    assert labels[i - 1] == "L14"
    for z in pl["rows"]:
        c = z["cmp"][i]
        assert c == {"t": z["min"], "k": z["min_k"]}
        if c["k"] is not None:
            assert c["k"] == int(round(float(c["t"]) * 10))           # the key follows what is printed
    ks = [z["cmp"][i]["k"] for z in pl["rows"] if z["cmp"][i]["k"] is not None]
    assert len(set(ks)) > 1                                          # someone wins


def test_the_cards_last_5_min_and_season_line(synm):
    p, cards = synm
    views = C.views(p, cards)
    rows = {z["key"]: z for z in p["v2"]["players"]["rows"]}
    n_lines = 0
    for k, v in views.items():
        z = rows[k]
        for g, src in zip(v["season"]["last"], cards["cards"][k]["last_10"][:C.LAST_N]):
            want = DASH if src["injured"] else z["min_g"].get(src["date"], "loading")
            assert g["min"] == want
        if z["min_k"] is not None:
            assert v["season"]["minutes"] == f"MIN {z['min']} a game this season \u00b7 MIN \u0394 {z['mind']}"
            n_lines += 1
    assert n_lines > 0
    h = v2pub.card_html_all(p, cards)
    for k, one in h.items():
        assert 'data-colh="last5|fp"' in one and 'data-colh="last5|min"' in one     # 5d1 s.5: headers with definitions
        if rows[k]["min_k"] is not None:
            assert 'aria-label="What MIN means">' in one
            line_ = views[k]["season"]["minutes"]
            assert line_ in one or line_.replace("\u00b7", "&middot;") in one


def test_the_card_line_says_loading_before_the_backfill_and_nothing_with_no_games():
    row = {"min": "loading", "min_k": None, "mind": "loading", "mind_k": None, "min_g": {"2026-11-01": "30"}}
    card = {"last_10": [{"date": "2026-11-01", "fp": 30.0, "injured": False, "opponent": ""},
                        {"date": "2026-10-30", "fp": 0.0, "injured": True, "opponent": ""},
                        {"date": "2026-10-29", "fp": 20.0, "injured": False, "opponent": ""}]}
    v = _view(card, row)
    assert [g["min"] for g in v["season"]["last"]] == ["30", DASH, "loading"]
    assert v["season"]["minutes"] == "MIN loading \u00b7 MIN \u0394 loading"
    v = _view({"last_10": []}, dict(row, min=DASH, mind=DASH, min_g={}))
    assert v["season"]["minutes"] == ""


def _view(card: dict, mins: dict) -> dict:
    """card.view on a minimal free-agent card with the given minutes."""
    c = dict({"player_name": "Zed Alpha", "current_season": {"fppg": 20.0, "gp": 3, "total_fp": 60.0}, "age": 25,
              "positions": "PG", "nba_team": "AAA", "status": []}, **card)
    row = dict({"name": "Zed Alpha", "kind": "fa", "fppg": "20.0", "gp": "3", "age": "25", "pos": "PG", "ini": "ZA",
                "chip": {"text": "FA", "slot": "", "team": "Free agent"}, "m": "", "chips": [], "healthy": True,
                "ovr": DASH, "ovr_d": None, "ring": None, "pot": DASH, "pot_d": None, "fa_pct": "", "fa_pct_w": "",
                "ovr_note": "free agent", "team_gp": "4", "total_rank": "", "l14": "20.0", "grades": None,
                "keep_rank": "", "key": "zed-alpha"}, **mins)
    from modules.ratings import config as rcfg
    return C.view(c, row, {"season": "2026-27", "curve": rcfg()["pot"]["age_curve"], "team_size": {}})


def test_the_new_pieces_obey_the_4b_4c_rules(synm):
    p, cards = synm
    for k, h in v2pub.card_html_all(p, cards).items():
        doc = f"<body>{h}</body>"
        assert not tap_violations(doc), (k, tap_violations(doc)[:3])          # the new i is a tap
        assert "http://" not in h and "https://" not in h                     # offline
        assert not re.search(r"#[0-9A-Fa-f]{6}\b", h) and "px" not in re.sub(r"<svg.*?</svg>", "", h, flags=re.S)
    import inspect
    body = inspect.getsource(PP.card_html)
    for frag in ('clean(g["min"])', 'clean(s["minutes"])', '_info(ids, "min")'):
        assert frag in body
    seg = body[body.index('s.get("minutes")') - 200:body.index('("min", "MIN")') + 200]
    for banned in ("round(", "float(", "sum(", "sorted(", "max(", "min(", "int("):
        assert banned not in seg, banned                                     # display only
    # every number on a card is an engine string (the minutes included)
    for k, h in v2pub.card_html_all(p, cards).items():
        known = " ".join(strings(p)) + " " + " ".join(strings(C.views(p, cards)[k])) + " " + \
            " ".join(" ".join(v) for v in infotips.TIPS.values())
        for n in re.findall(r"\d+(?:[.,]\d+)*", visible_text(h)):
            assert n in known, (k, n)
        break


def test_lore_never_reaches_the_minutes(synm):
    p, cards = synm
    p = json.loads(json.dumps(p))
    z = next(z for z in p["v2"]["players"]["rows"] if z["min_k"] is not None)
    z["min"] = "30.0 <!-- lore:phase-m -->"
    z["min_g"] = {d: "30 <!-- lore:phase-g -->" for d in z["min_g"]}
    h = "".join(v2pub.card_html_all(p, cards).values())
    assert "lore:" not in h and "phase-m" not in h and "phase-g" not in h


def test_the_info_words():
    assert infotips.TIPS["min"] == ("MIN", "Minutes per game in his NBA games this season. MIN \u0394: his minutes "
                                    "per game over the last 14 days against his season, a sign of a bigger or "
                                    "smaller role. It shows from 4 games in the last 14 days.")
    assert all(x.isascii() for x in (Path(PP.__file__).read_text(encoding="utf-8"),
                                     Path(infotips.__file__).read_text(encoding="utf-8")))


# =============================================================================
# 7. the real thing, unstubbed
# =============================================================================

REAL = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "hub_state.json", ROOT / "config" / "ROSTERS.json"]


@pytest.mark.slow
@pytest.mark.skipif(not all(x.is_file() for x in REAL), reason="needs the league's state (python scripts\\state.py pull)")
def test_real_todays_cache_reads_and_its_backfill_plans():
    blob = pa.load(ROOT)                                       # validates every day, the minutes included
    tracked = pa.tracked_ids(blob)
    plan = pa.backfill_minutes(ROOT, dry_run=True)
    missing = sum(1 for p in tracked for d in blob["players"][str(p)]["days"]
                  if d not in (blob["players"][str(p)].get("min_days") or {}))
    assert (plan["days_missing"] > 0) == (missing > 0)
    days = pa.backfill_plan(blob, date.fromisoformat(max(d for r in blob["players"].values() for d in r["days"])),
                            key="min_days")
    assert all(-(-len(w["played"]) // pa.BATCH) <= plan["cap"] for w in days.values())   # no day stalls


@pytest.fixture(scope="module")
def real_builds():
    """Today's hub payload twice at one clock: the cache as it is, and the
    same cache with made-up minutes on every day (in memory only)."""
    from modules import hub_state as hs
    from modules.league_clock import league_now
    if not all(x.is_file() for x in REAL):
        pytest.skip("needs the league's state (python scripts\\state.py pull)")
    league_state.skip_if_actuals_behind()
    now = league_now()
    po0, po1 = {}, {}
    p0 = hs.build(ROOT, now=now, allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po0)
    with pytest.MonkeyPatch.context() as mp:
        orig = pa.load

        def load(*a, **k):
            blob = orig(*a, **k)
            for rec in blob["players"].values():
                rec["min_days"] = {d: (0 if v[1] == 0 else 20 + int(v[0]) % 17) for d, v in rec["days"].items()}
            return blob
        mp.setattr(pa, "load", load)
        p1 = hs.build(ROOT, now=now, allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po1)
    return now, p0, p1, po0, po1


@pytest.mark.slow
@pytest.mark.real
def test_real_every_min_cell_before_the_backfill_and_nothing_raises(real_builds):
    _now, p0, _p1, po0, _po1 = real_builds
    assert p0["v2_error"] is None, p0["v2_error"]
    from modules.hub_v2 import data as v2data
    p0 = v2data.attach_players(json.loads(json.dumps(p0)), po0)     # 5b: the Detailed columns ride in the side file
    blob = pa.load(ROOT)
    none_yet = not any(rec.get("min_days") for rec in blob["players"].values())
    keys = p0["v2"]["roster_cols"]["keys"]
    reason = re.compile(r"loading|\d+\.\d|[+\u2212]\d+\.\d|0\.0|\d+ of 4 games|no earlier games|" + DASH)
    n = 0
    for t in p0["v2"]["teams"].values():
        for r in t["roster"]["detail"]["rows"]:
            a, b = r[keys.index("min")], r[keys.index("mind")]
            n += 1
            if none_yet:
                assert (a, b) == ("loading", "loading")
            else:
                assert reason.fullmatch(a) and reason.fullmatch(b), (a, b)
    assert n >= 60


@pytest.mark.slow
@pytest.mark.real
def test_real_the_live_hub_is_unchanged_by_the_minutes(real_builds, tmp_path):
    import os
    from modules import hub_page, hub_publish
    now, p0, p1, po0, po1 = real_builds
    assert p1["v2_error"] is None, p1["v2_error"]
    for k in set(p0) | set(p1):
        if k not in ("v2",):
            assert p0.get(k) == p1.get(k), k                   # every key of the current hub
    assert hub_page.render(p0, now=now) == hub_page.render(p1, now=now)
    keys = p1["v2"]["roster_cols"]["keys"]
    from modules.hub_v2 import data as v2data
    det = po1["moved"][v2data.DETAIL_KEY]                            # 5b: the Detailed columns ride in the side file
    cells = [r[keys.index("min")] for t in det.values() for r in t["rows"]]
    assert sum(1 for c in cells if re.fullmatch(r"\d+\.\d", c)) >= 50        # the new hub does show them
    assert po0["players"]["rows"] != po1["players"]["rows"]                  # its Players rows too
    from modules.hub_v2 import data as v2data
    p1 = v2data.attach_players(json.loads(json.dumps(p1)), po1)
    # publish mode with the minutes: the budget and the plaintext scan
    terms = hub_publish.scan_terms(ROOT)
    out = tmp_path / "_to_delete" / "4a3" / "publish"
    rep = v2pub.build(ROOT, p1, "throwaway " + os.urandom(8).hex(), salt=os.urandom(16), out_dir=out,
                      iterations=1000, terms=terms)
    assert rep["served_bytes"] <= budget_bytes()
    assert hub_publish.scan_dir(out, terms)["hits"] == {}
