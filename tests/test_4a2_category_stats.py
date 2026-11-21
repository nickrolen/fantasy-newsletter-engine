"""4a2: the per-category stats in data/player_actuals.json, their nightly
backfill, and the grades and archetype built on them (modules/player_actuals,
modules/ratings; claude/HANDOFF_4A2_CATEGORY_STATS_2026-11-14.md).

1. the schema: version 1 still reads; version 2 validates; no made-up zeros;
   the points cross-check and the basketball identities raise, naming him and the day
2. the nightly's fetch keeps each day's categories; a category problem never costs the points
3. the backfill: the per-night cap, all or nothing per day, a complete day never
   refetched, the idle players' zeros cost no call, a stat correction is kept
4. the nightly records the backfill's failure loudly and goes on; only the nightly runs it
5. the category grades: per-game points, percentiles over the rostered players,
   None below the minimum and before the backfill, with reasons
6. the schedule grade's 3-week horizon
7. (the archetype moved to tests/test_4a4_archetypes.py: archetypes v2)
8. the real thing, unstubbed, on today's cache
No network: fake Yahoo sources and leagues only.
"""
import copy
import itertools
import json
import math
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from modules import keeper_history as kh
from modules import nightly
from modules import player_actuals as pa
from modules import ratings

ROOT = Path(__file__).resolve().parents[1]
LA = ZoneInfo("America/Los_Angeles")
FIRST = date(2026, 10, 20)
SEASON = "2026-27"
ORDER = ["FGM", "FGA", "FTM", "FTA", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
VALUES = [1, -0.45, 1, -0.75, 3, 0.5, 1.5, 2, 3, 3, -2]
HEADER = {"order": ORDER, "values": [float(v) for v in VALUES]}


def line(seed: int, played: bool = True) -> list:
    """Eleven counts that obey the identities (PTS = 2 FGM + 3PTM + FTM ...)."""
    if not played:
        return [0] * 11
    fgm = 3 + seed % 7
    fga = fgm + 2 + seed % 5
    ftm = seed % 4
    fta = ftm + seed % 3
    tpm = min(fgm, seed % 3)
    pts = 2 * fgm + tpm + ftm
    return [fgm, fga, ftm, fta, tpm, pts, 2 + seed % 9, 1 + seed % 6, seed % 3, seed % 2, seed % 4]


def points(c) -> float:
    return round(pa.cat_points(c, HEADER), 2)


def base(tmp_path, cap=20) -> Path:
    b = tmp_path / "base"
    for d in ("config", "data", "output"):
        (b / d).mkdir(parents=True, exist_ok=True)
    cfg = {"actuals": {"extra_players_max": 150, "category_backfill_calls_max": cap},
           "yahoo_settings": {"stat_values": dict(zip(ORDER, VALUES))}}
    (b / "config" / "league_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return b


def v1_blob(players: dict) -> dict:
    """players: {pid: (name, {iso: [points, games]})}, version 1 (before 4a2)."""
    blob = pa.empty(SEASON, FIRST)
    for pid, (n, days) in players.items():
        blob["players"][str(pid)] = {"name": n, "days": dict(days)}
        blob["roster_names"][n] = pid
    return blob


def days_for(pid: int, n_days: int, idle=()) -> dict:
    out = {}
    for i in range(n_days):
        d = (FIRST + timedelta(days=i)).isoformat()
        played = i not in idle
        c = line(pid * 7 + i, played)
        out[d] = [points(c), 1 if played else 0]
    return out


# =============================================================================
# 1. the schema
# =============================================================================

def test_version_1_still_reads_and_its_readers_do_not_care(tmp_path):
    b = base(tmp_path)
    blob = v1_blob({1: ("Zed Alpha", days_for(1, 4))})
    pa.write(b, blob, FIRST + timedelta(days=4))
    got = pa.load(b)
    assert got["version"] == 1 and "cats" not in got
    assert pa.season(got, "Zed Alpha", FIRST + timedelta(days=3))[1] == 4
    cs = pa.category_season(got, "Zed Alpha", FIRST, FIRST + timedelta(days=3))
    assert cs["status"] == "loading" and cs["totals"] is None          # never zeros


def test_version_2_validates_and_a_day_without_categories_is_absent_not_zero():
    blob = v1_blob({1: ("Zed Alpha", days_for(1, 3, idle={1}))})
    pa.ensure_cats(blob, HEADER)
    assert blob["version"] == 2 and blob["cats"] == HEADER
    rec = blob["players"]["1"]
    rec["cat_days"] = {FIRST.isoformat(): line(7), (FIRST + timedelta(days=1)).isoformat(): [0] * 11}
    pa.validate(blob)
    cs = pa.category_season(blob, "Zed Alpha", FIRST, FIRST + timedelta(days=2))
    assert cs["status"] == "loading" and cs["day"] == (FIRST + timedelta(days=2)).isoformat()
    cs = pa.category_season(blob, "Zed Alpha", FIRST, FIRST + timedelta(days=1))
    assert cs["status"] == "ok" and cs["games"] == 1 and cs["totals"]["PTS"] == line(7)[5]


def test_the_points_cross_check_raises_naming_the_player_and_the_day():
    blob = v1_blob({1: ("Zed Alpha", days_for(1, 2))})
    pa.ensure_cats(blob, HEADER)
    bad = line(7)
    bad[6] += 1                                                # one more rebound: 1.5 points more
    blob["players"]["1"]["cat_days"] = {FIRST.isoformat(): bad}
    with pytest.raises(pa.ActualsError, match=r"Zed Alpha 2026-10-20: the categories score .* the scoring changed"):
        pa.validate(blob)


@pytest.mark.parametrize("i,delta,what", [(5, 2, "PTS"), (0, 50, "FGM"), (4, 9, "3PTM")])
def test_the_basketball_identities_raise(i, delta, what):
    c = line(7)
    c[i] += delta
    with pytest.raises(pa.CategoryError, match=what):
        pa.check_cats(c, HEADER, points(c), "Zed Alpha", "2026-10-20")


def test_shape_problems_raise():
    blob = v1_blob({1: ("Zed Alpha", days_for(1, 2, idle={1}))})
    pa.ensure_cats(blob, HEADER)
    rec = blob["players"]["1"]
    for bad, msg in (([1.5] + line(7)[1:], "whole counts"), (line(7)[:10], "whole counts"),
                     ({"x": 1}, "whole counts")):
        rec["cat_days"] = {FIRST.isoformat(): bad}
        with pytest.raises(pa.ActualsError, match=msg):
            pa.validate(blob)
    rec["cat_days"] = {(FIRST + timedelta(days=1)).isoformat(): line(7)}      # a no-game day with stats
    with pytest.raises(pa.ActualsError, match="no game"):
        pa.validate(blob)
    rec["cat_days"] = {(FIRST + timedelta(days=9)).isoformat(): line(7)}      # no points that day
    with pytest.raises(pa.ActualsError, match="no points cached"):
        pa.validate(blob)
    v1 = v1_blob({1: ("Zed Alpha", days_for(1, 1))})
    v1["players"]["1"]["cat_days"] = {FIRST.isoformat(): line(7)}
    with pytest.raises(pa.ActualsError, match="no \"cats\" header"):
        pa.validate(v1)


def test_a_changed_scoring_refuses():
    blob = v1_blob({})
    pa.ensure_cats(blob, HEADER)
    other = {"order": ORDER, "values": [float(v) for v in VALUES[:-1]] + [-1.0]}
    with pytest.raises(pa.ActualsError, match="scoring changed mid-season"):
        pa.ensure_cats(blob, other)


def test_the_header_is_the_configs_stat_values_in_order():
    h = pa.scoring_header(ROOT)
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert h["order"] == list(cfg["yahoo_settings"]["stat_values"]) == ORDER
    assert h["values"] == [float(v) for v in VALUES]


def test_parse_cats_reads_a_dash_only_on_a_day_he_did_not_play():
    row = dict(zip(ORDER, ["-"] * 11))
    assert pa.parse_cats(row, HEADER, "Zed", "2026-10-20", 0) == [0] * 11
    with pytest.raises(pa.CategoryError, match="on a day he played"):
        pa.parse_cats(row, HEADER, "Zed", "2026-10-20", 1)
    with pytest.raises(pa.CategoryError, match="has no TO"):
        pa.parse_cats({k: 1.0 for k in ORDER[:-1]}, HEADER, "Zed", "2026-10-20", 1)
    assert pa.parse_cats(dict(zip(ORDER, [float(x) for x in line(3)])), HEADER, "Zed", "d", 1) == line(3)


# =============================================================================
# 2. the nightly's fetch keeps the categories
# =============================================================================

class FakeLeague:
    """yahoo_fantasy_api's League as YahooSource uses it: league-scoped rows
    with the categories and total_points, and the game-scoped stat 0.
    lines: {(pid, iso): counts}; total_shift: {(pid, iso): points added to
    Yahoo's total (a stat correction)}; broken: {(pid, iso)} rows missing TO."""

    def __init__(self, lines, total_shift=None, broken=(), fail_after=None):
        self.league_id = "466.l.99999"
        self.lines = lines
        self.total_shift = total_shift or {}
        self.broken = set(broken)
        self.fail_after = fail_after
        self.stat_calls = []
        lg = self

        class H:
            def get(self, url):
                d = url.split("date=")[1]
                keys = url.split("player_keys=")[1].split("/")[0].split(",")
                players = {"count": len(keys)}
                for i, k in enumerate(keys):
                    pid = int(k.split(".p.")[1])
                    g = 1 if any(lg.lines.get((pid, d), [0])) else 0
                    players[str(i)] = {"player": [[{"player_id": str(pid)}],
                                                  {"player_stats": {"stats": [{"stat": {"stat_id": "0", "value": str(g)}}]}}]}
                return {"fantasy_content": {"players": players}}
        self.yhandler = H()

    def player_stats(self, ids, kind, date=None):
        if self.fail_after is not None and len(self.stat_calls) >= self.fail_after:
            raise RuntimeError("Yahoo is down")
        iso = date.isoformat()
        self.stat_calls.append((iso, tuple(ids)))
        rows = []
        for pid in ids:
            c = self.lines.get((pid, iso), [0] * 11)
            played = any(c)
            r = {"player_id": pid, "name": f"P{pid}",
                 "total_points": points(c) + self.total_shift.get((pid, iso), 0.0)}
            r.update({k: (float(v) if played else "-") for k, v in zip(ORDER, c)})
            if (pid, iso) in self.broken:
                del r["TO"]
            rows.append(r)
        return rows


def test_the_nightly_fetch_keeps_each_days_categories(tmp_path):
    b = base(tmp_path)
    lines = {(p, (FIRST + timedelta(days=i)).isoformat()): line(p * 7 + i, i != 1)
             for p in (1, 2) for i in range(3)}
    src = pa.YahooSource(FakeLeague(lines))
    r = pa.update(b, source=src, ids={"Zed Alpha": 1, "Yan Beta": 2}, today=FIRST + timedelta(days=3),
                  first_day=FIRST, season=SEASON, echo=lambda *a: None)
    assert r["cat_errors"] == [] and r["calls"] == 6                  # no extra call: 2 a day, as before
    blob = pa.load(b)
    assert blob["version"] == 2 and blob["cats"] == HEADER
    for (p, iso), c in lines.items():
        assert blob["players"][str(p)]["cat_days"][iso] == c
        assert blob["players"][str(p)]["days"][iso][0] == points(c)


def test_a_category_problem_never_costs_the_points(tmp_path):
    b = base(tmp_path)
    d0 = FIRST.isoformat()
    lines = {(1, d0): line(1), (2, d0): line(2)}
    src = pa.YahooSource(FakeLeague(lines, broken={(2, d0)}))
    r = pa.update(b, source=src, ids={"Zed Alpha": 1, "Yan Beta": 2}, today=FIRST + timedelta(days=1),
                  first_day=FIRST, season=SEASON, echo=lambda *a: None)
    assert len(r["cat_errors"]) == 1 and "Yan Beta" in r["cat_errors"][0] and "has no TO" in r["cat_errors"][0]
    blob = pa.load(b)
    assert blob["players"]["1"]["days"][d0][0] == points(line(1))    # the points are written
    assert "cat_days" not in blob["players"]["1"] and "cat_days" not in blob["players"]["2"]  # all or nothing


# =============================================================================
# 3. the backfill
# =============================================================================

def backfill_world(tmp_path, n_players=30, n_days=4, cap=20, idle=lambda p, i: (p + i) % 3 == 0, **kw):
    """A version-1 cache (n_players x n_days) and the league that holds its categories."""
    b = base(tmp_path, cap=cap)
    lines, players = {}, {}
    for p in range(1, n_players + 1):
        days = {}
        for i in range(n_days):
            iso = (FIRST + timedelta(days=i)).isoformat()
            c = line(p * 7 + i, not idle(p, i))
            lines[(p, iso)] = c
            days[iso] = [points(c), 1 if any(c) else 0]
        players[p] = (f"Player {p}", days)
    pa.write(b, v1_blob(players), FIRST + timedelta(days=n_days))
    return b, lines, FakeLeague(lines, **kw)


def test_the_backfill_respects_the_cap_oldest_first_and_never_refetches(tmp_path):
    b, lines, lg = backfill_world(tmp_path, cap=3)                  # 20 of 30 play a day: 1 call a day
    today = FIRST + timedelta(days=4)
    plan = pa.backfill_categories(b, today=today, dry_run=True)
    assert plan["calls_needed"] == 4 and plan["days_missing"] == 4
    src = pa.YahooSource(lg)
    r1 = pa.backfill_categories(b, source=src, today=today)
    assert r1["calls"] == 3 and r1["days_done"] == ["2026-10-20", "2026-10-21", "2026-10-22"]
    assert r1["days_left"] == 1 and "cap" in r1["stopped"]
    blob = pa.load(b)
    assert blob["version"] == 2
    for (p, iso), c in lines.items():
        got = blob["players"][str(p)].get("cat_days", {}).get(iso)
        assert got == (c if iso <= "2026-10-22" else None)
    r2 = pa.backfill_categories(b, source=src, today=today)
    assert r2["days_done"] == ["2026-10-23"] and r2["days_left"] == 0
    asked = [d for d, _ids in lg.stat_calls]
    assert asked == sorted(asked) and len(asked) == len(set(asked)) == 4    # each day once, oldest first
    n = len(lg.stat_calls)
    r3 = pa.backfill_categories(b, source=src, today=today)
    assert r3["days_done"] == [] and r3["calls"] == 0 and len(lg.stat_calls) == n


def test_the_idle_players_get_zeros_with_no_call(tmp_path):
    b, lines, lg = backfill_world(tmp_path, n_players=3, n_days=2, idle=lambda p, i: True)
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=2))
    assert r["calls"] == 0 and lg.stat_calls == [] and len(r["days_done"]) == 2
    assert pa.load(b)["players"]["1"]["cat_days"]["2026-10-20"] == [0] * 11


def test_a_failure_writes_nothing_for_its_day_and_keeps_the_days_before(tmp_path):
    b, lines, lg = backfill_world(tmp_path, n_players=40, cap=20, fail_after=3)   # 2 calls a day
    with pytest.raises(pa.ActualsError, match="Yahoo request for 2026-10-21's categories failed"):
        pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    blob = pa.load(b)
    have = {iso for rec in blob["players"].values() for iso in rec.get("cat_days", {})}
    assert have == {"2026-10-20"}                                   # 10-21's first batch came back: not written


def test_a_missing_category_refuses_the_day(tmp_path):
    b, lines, lg = backfill_world(tmp_path, n_players=5, idle=lambda p, i: False,
                                  broken={(3, "2026-10-21")})
    with pytest.raises(pa.CategoryError, match="Player 3"):
        pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    blob = pa.load(b)
    assert {iso for rec in blob["players"].values() for iso in rec.get("cat_days", {})} == {"2026-10-20"}


def test_a_stat_correction_is_kept_beside_the_points_and_a_scoring_change_raises(tmp_path):
    b, lines, lg = backfill_world(tmp_path, n_players=4, n_days=2, idle=lambda p, i: False)
    # Yahoo's total now is 1.5 higher than cached, and so are the categories (one more rebound)
    iso = "2026-10-21"
    cached = list(lines[(2, iso)])
    c = list(cached)
    c[6] += 1
    lg.lines[(2, iso)] = c
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=2))
    blob = pa.load(b)
    rec = blob["players"]["2"]
    assert rec["days"][iso][0] == points(cached)                     # the points are never rewritten
    assert rec["cat_days"][iso] == c and rec["cat_corrections"][iso] == points(c)
    assert r["corrections"] == [f"Player 2 {iso}: {points(cached)} cached, {points(c)} now"]
    # a total that the categories do not score: the scoring changed
    b2, lines2, lg2 = backfill_world(tmp_path / "x", n_players=2, n_days=1, idle=lambda p, i: False,
                                     total_shift={(1, "2026-10-20"): 0.4})
    with pytest.raises(pa.CategoryError, match="Player 1 2026-10-20: the categories score"):
        pa.backfill_categories(b2, source=pa.YahooSource(lg2), today=FIRST + timedelta(days=1))


def test_a_day_bigger_than_the_cap_raises_rather_than_waiting_forever(tmp_path):
    b, lines, lg = backfill_world(tmp_path, n_players=60, n_days=1, cap=2, idle=lambda p, i: False)
    with pytest.raises(pa.ActualsError, match="need 3 calls .* raise the cap"):
        pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=1))


def test_the_cap_is_required(tmp_path):
    b = base(tmp_path)
    cfg = json.loads((b / "config" / "league_config.json").read_text())
    del cfg["actuals"]["category_backfill_calls_max"]
    (b / "config" / "league_config.json").write_text(json.dumps(cfg))
    with pytest.raises(pa.ActualsError, match="category_backfill_calls_max"):
        pa.backfill_cap(b)
    assert pa.backfill_cap(ROOT) >= 1


# =============================================================================
# 4. the nightly: soft and loud, the nightly run only
# =============================================================================

class _Src:
    def cats_day(self, *a, **k):
        raise AssertionError("stubbed backfill")


def _step(tmp_path, monkeypatch, mode, backfill):
    b = base(tmp_path)
    called = []
    monkeypatch.setattr(pa, "update", lambda *a, **k: {
        "through": "2026-10-22", "days_fetched": ["2026-10-22"], "calls": 2, "backfilled": [], "ids": {},
        "source": _Src(), "header": HEADER, "cat_errors": ["2026-10-22: Yahoo's line for Zed has no TO"]})
    monkeypatch.setattr(pa, "update_extras", lambda *a, **k: {
        "players": 0, "no_id": [], "days_fetched": [], "calls": 0, "backfilled": [], "cap": 150,
        "cat_errors": []})

    def bf(*a, **k):
        called.append(k)
        return backfill()
    monkeypatch.setattr(pa, "backfill_categories", bf)
    hour = 0 if mode == "nightly" else 15
    run = nightly.Run(b, mode, now=datetime(2026, 10, 23, hour, 5, tzinfo=LA), echo=lambda *a: None)
    detail = run.step_actuals()
    return run, detail, called


def test_the_nightly_records_a_backfill_failure_loudly_and_goes_on(tmp_path, monkeypatch):
    def boom():
        raise pa.CategoryError("Zed 2026-10-20: the categories score 10.00 ...")
    run, detail, called = _step(tmp_path, monkeypatch, "nightly", boom)
    assert called and "categories' backfill FAILED" in detail
    cats = run.ctx["actuals"]["categories"]
    assert cats["error"].startswith("CategoryError") and cats["errors"] == ["2026-10-22: Yahoo's line for Zed has no TO"]
    assert all(l.startswith("CATEGORY STATS FAILED") for l in run.ctx["actuals_lines"]) and len(run.ctx["actuals_lines"]) == 2
    assert run.ctx["actuals"]["error"] is None                      # the free agents were fine


def test_a_good_nights_backfill_is_recorded(tmp_path, monkeypatch):
    ok = {"days_done": ["2026-10-20"], "days_left": 3, "calls": 4, "cap": 20, "corrections": [], "stopped": None}
    run, detail, called = _step(tmp_path, monkeypatch, "nightly", lambda: dict(ok))
    assert run.ctx["actuals"]["categories"]["backfill"] == ok and "3 day(s) left" in detail


def test_only_the_nightly_run_backfills(tmp_path, monkeypatch):
    run, detail, called = _step(tmp_path, monkeypatch, "pretip", lambda: {})
    assert called == [] and run.ctx["actuals"]["categories"]["backfill"] is None


# =============================================================================
# 5-6. the category grades and the schedule horizon
# =============================================================================

@pytest.fixture(scope="module")
def history():
    return kh.Inputs.load(ROOT)


def _rate_with(history, actuals, weeks=None):
    season = "2024-25"
    snap = kh.snapshot(history, kh.next_season(season), "mid", ages=None, check=False, labels=False)
    sched = {}
    for r in history.log[season]:
        if r["had_game"] and r["nba_team"]:
            sched.setdefault(r["nba_team"], set()).add(r["date"])
    sched = {t: sorted(v) for t, v in sched.items()}
    return snap, ratings.rate(snap, history, sched, history.log[season][-1]["date"],
                              actuals=actuals, weeks=weeks), sched


def _actuals_for(snap, n_days=10, games_of=lambda i: 10, skip=(), loading=()):
    """A version-2 cache for the snapshot's players over the n_days ending at
    its as_of: player i plays games_of(i) of them."""
    as_of = date.fromisoformat(snap.as_of)
    first = as_of - timedelta(days=n_days - 1)
    blob = {"version": 2, "season": "x", "first_day": first.isoformat(), "cats": HEADER, "players": {},
            "roster_names": {}, "rosters_from": None, "updated_at": None}
    names = sorted(c.player for c in snap.candidates)
    for i, n in enumerate(names):
        if n in skip:
            continue
        rec = {"name": n, "days": {}, "cat_days": {}}
        for k in range(n_days):
            iso = (first + timedelta(days=k)).isoformat()
            c = line(i * 3 + k, k < games_of(i))
            rec["days"][iso] = [points(c), 1 if any(c) else 0]
            if n not in loading:
                rec["cat_days"][iso] = c
        blob["players"][str(1000 + i)] = rec
        blob["roster_names"][n] = 1000 + i
    pa.validate(blob, "test")
    return blob, names


@pytest.mark.slow
def test_category_grades_are_per_game_points_as_percentiles_over_the_rostered(history):
    snap, _r, _s = _rate_with(history, None)
    blob, names = _actuals_for(snap, games_of=lambda i: 3 if i % 5 == 0 else 8,
                               loading={snap.candidates[1].player})
    _snap, res, _s = _rate_with(history, blob)
    P = res["players"]
    first, through = date.fromisoformat(blob["first_day"]), date.fromisoformat(snap.as_of)
    vals = {}
    for i, n in enumerate(names):
        cs = pa.category_season(blob, n, first, through)
        g = P[n]["grades"]["scoring"]
        if n == snap.candidates[1].player:
            assert g["letter"] is None and g["reason"] == "stats still loading"
        elif i % 5 == 0:
            assert g["letter"] is None and g["reason"] == "3 games: shows after 5"
        else:
            want = cs["totals"]["PTS"] * 0.5 / cs["games"]           # 4a4: scoring is PTS alone
            assert g["value"] == pytest.approx(want)
            assert P[n]["grades"]["shooting"]["value"] == pytest.approx(cs["totals"]["3PTM"] * 3 / cs["games"])
            vals[n] = want
            # the seven grades add up to his FPPG
            total = sum(P[n]["grades"][a]["value"] for a in ratings.CATEGORY_GRADES)
            pts = sum(v[0] for v in blob["players"][str(1000 + i)]["days"].values())
            assert total == pytest.approx(pts / cs["games"])
    assert {n: P[n]["grades"]["scoring"]["percentile"] for n in vals} == pytest.approx(ratings.percentiles(vals))


@pytest.mark.slow
def test_no_actuals_and_a_cache_gap_give_reasons(history):
    snap, res, _s = _rate_with(history, None)
    assert all(p["grades"]["steals"]["reason"] == "no per-category stats for this day" for p in res["players"].values())
    gone = snap.candidates[0].player
    blob, _ = _actuals_for(snap, skip={gone})
    _snap, res, _s = _rate_with(history, blob)
    assert res["players"][gone]["grades"]["rebounding"]["reason"] == "no daily lines cached for him"
    blob, _ = _actuals_for(snap)
    rec = next(r for r in blob["players"].values() if r["name"] == gone)
    last = max(rec["days"])
    del rec["days"][last]
    rec["cat_days"].pop(last, None)
    _snap, res, _s = _rate_with(history, blob)
    assert res["players"][gone]["grades"]["playmaking"]["reason"] == f"his daily lines are not fetched for {last}"


@pytest.mark.slow
def test_a_category_in_no_grade_or_two_raises(history):
    snap, _r, _s = _rate_with(history, None)
    blob, _ = _actuals_for(snap)
    blob["cats"] = {"order": ORDER + ["DD"], "values": HEADER["values"] + [5.0]}
    with pytest.raises(ratings.RatingsInputError, match="exactly one grade"):
        _rate_with(history, blob)
    cfg = copy.deepcopy(ratings.config())
    cfg["grades"]["categories"]["steals"] = ["ST", "TO"]
    with pytest.raises(ratings.RatingsInputError, match="TO is in both"):
        ratings.config(cfg)


def test_the_real_config_partitions_the_leagues_categories():
    cats = ratings.config()["grades"]["categories"]
    used = [c for g in ratings.CATEGORY_GRADES for c in cats[g]]
    assert sorted(used) == sorted(pa.scoring_header(ROOT)["order"])


WEEKS = [{"week": 1, "start_date": "2026-10-20", "end_date": "2026-10-25"},
         {"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01"},
         {"week": 3, "start_date": "2026-11-02", "end_date": "2026-11-08"},
         {"week": 4, "start_date": "2026-11-09", "end_date": "2026-11-22"},     # a 14-day week
         {"week": 5, "start_date": "2026-11-23", "end_date": "2026-11-29"}]


@pytest.mark.parametrize("as_of,want", [
    ("2026-10-19", ("2026-10-20", "2026-11-08")),     # before the season: weeks 1-3
    ("2026-10-24", ("2026-10-25", "2026-11-08")),     # the rest of week 1, weeks 2 and 3
    ("2026-10-25", ("2026-10-26", "2026-11-22")),     # the next day opens week 2: weeks 2-4
    ("2026-11-20", ("2026-11-21", "2026-11-29")),     # past the last week's horizon: clipped
    ("2026-11-29", None),                             # nothing remains
])
def test_the_schedule_horizon_is_the_games_grids(as_of, want):
    assert ratings.schedule_horizon(as_of, WEEKS, 3) == want


@pytest.mark.slow
def test_the_schedule_grade_counts_the_horizons_games(history):
    snap, _r, sched = _rate_with(history, None)
    as_of = date.fromisoformat(snap.as_of)
    weeks = [{"start_date": (as_of + timedelta(days=1 + 7 * k)).isoformat(),
              "end_date": (as_of + timedelta(days=7 + 7 * k)).isoformat()} for k in range(6)]
    _snap, res, _s = _rate_with(history, None, weeks=weeks)
    lo, hi = res["schedule_horizon"]
    assert (lo, hi) == ((as_of + timedelta(days=1)).isoformat(), (as_of + timedelta(days=21)).isoformat())
    for p in res["players"].values():
        g = p["grades"]["schedule"]
        if p["nba_team"]:
            assert g["value"] == sum(1 for d in sched[p["nba_team"]] if lo <= d <= hi) and g["letter"]
        else:
            assert g["letter"] is None and g["reason"]


# =============================================================================
# 8. the real thing, unstubbed
# =============================================================================

REAL = [ROOT / "config" / "ROSTERS.json", ROOT / "data" / "LINEUPS.xlsx", ROOT / "data" / "player_actuals.json"]
KNOWN = ("stats still loading", "no daily lines cached for him", "his daily lines are not fetched for ",
         " games: shows after ")


@pytest.mark.slow
@pytest.mark.skipif(not all(p.is_file() for p in REAL), reason="needs the league's real state")
def test_todays_cache_rates_without_raising(history):
    """On the cache as it is (version 1 on 11-14: every category grade is
    "stats still loading"); once the nightly has written categories, every
    category grade is a letter or one of the known reasons."""
    blob = pa.load(ROOT)
    res = ratings.for_today(ROOT, history=history)
    for p in res["players"].values():
        for a in ratings.CATEGORY_GRADES:
            g = p["grades"][a]
            if blob["version"] == 1:
                assert g["letter"] is None and g["reason"] == "stats still loading", (p["player"], g)
            else:
                assert g["letter"] is not None or any(k in g["reason"] for k in KNOWN), (p["player"], g)
        assert p["archetype_enabled"] is True                  # 4a4: computed; enabled since dafe97e (Nick, 11-20)
        s = p["grades"]["schedule"]
        assert (s["letter"] is not None and isinstance(s["value"], int)) or s["reason"]
    assert res["schedule_horizon"] is not None
