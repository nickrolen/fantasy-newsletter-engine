"""5d1 s.2 and s.2b: late-filled stat lines and held lines in
data/player_actuals.json (modules/player_actuals; claude/HANDOFF_5D1_PHONE_FIXES_2026-11-21.md).

s.2 (Nick, 11-20: Zion Williamson 2026-11-14): a day cached as 0 points in 1
game whose categories now score a non-zero total is an incomplete line, not a
stat correction: rewritten with Yahoo's total and recorded. The nightly
re-checks the last few days (config actuals.recheck_days) for one.
  - an incomplete line is filled and recorded (backfill, re-check, and the
    old rule's correction settled with no call);
  - a phantom is still corrected (5c);
  - a real stat correction still isn't rewritten;
  - a day that is already complete is never touched (never even asked for).
s.2b (Nickeil Alexander-Walker 2026-11-20): one player's line that doesn't add
up holds back only him.
  - an inconsistent player in a batch: the others are written, he's held back;
  - a held day that becomes consistent is written (his points too, as a late fill);
  - one that never does stops being asked for, recorded once;
  - the backfill never stalls on one player.
No network: fake Yahoo leagues only.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from modules import nightly
from modules import player_actuals as pa

ROOT = Path(__file__).resolve().parents[1]
FIRST = date(2026, 10, 20)
SEASON = "2026-27"
ORDER = ["FGM", "FGA", "FTM", "FTA", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
VALUES = [1, -0.45, 1, -0.75, 3, 0.5, 1.5, 2, 3, 3, -2]
HEADER = {"order": ORDER, "values": [float(v) for v in VALUES]}


def line(seed: int) -> list:
    fgm = 3 + seed % 7
    fga = fgm + 2 + seed % 5
    ftm = seed % 4
    fta = ftm + seed % 3
    tpm = min(fgm, seed % 3)
    return [fgm, fga, ftm, fta, tpm, 2 * fgm + tpm + ftm, 2 + seed % 9, 1 + seed % 6, seed % 3, seed % 2, seed % 4]


def points(c) -> float:
    return round(pa.cat_points(c, HEADER), 2)


def bad(c) -> list:
    """Yahoo's NAW shape: PTS that isn't 2 FGM + 3PTM + FTM."""
    c = list(c)
    c[5] += 2
    return c


def base(tmp_path, recheck=3) -> Path:
    b = tmp_path / "base"
    for d in ("config", "data", "output"):
        (b / d).mkdir(parents=True, exist_ok=True)
    cfg = {"actuals": {"extra_players_max": 150, "category_backfill_calls_max": 20, "recheck_days": recheck},
           "yahoo_settings": {"stat_values": dict(zip(ORDER, VALUES))}}
    (b / "config" / "league_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return b


class League:
    """yahoo_fantasy_api's League as YahooSource uses it. now: {(pid, iso):
    (counts, games, minutes)} is what Yahoo says NOW; total: {(pid, iso):
    Yahoo's total} when it isn't the counts' points (a line that doesn't add up)."""

    def __init__(self, now, total=None):
        self.league_id = "466.l.99999"
        self.now = now
        self.total = total or {}
        self.asked = []
        lg = self

        class H:
            def get(self, url):
                d = url.split("date=")[1]
                keys = url.split("player_keys=")[1].split("/")[0].split(",")
                players = {"count": len(keys)}
                for i, k in enumerate(keys):
                    pid = int(k.split(".p.")[1])
                    c, g, m = lg.now.get((pid, d), ([0] * 11, 0, 0))
                    players[str(i)] = {"player": [[{"player_id": str(pid)}], {"player_stats": {"stats": [
                        {"stat": {"stat_id": "0", "value": str(g)}},
                        {"stat": {"stat_id": "2", "value": str(m) if g else "-"}}]}}]}
                return {"fantasy_content": {"players": players}}
        self.yhandler = H()

    def player_stats(self, ids, kind, date=None):
        iso = date.isoformat()
        self.asked.append((iso, tuple(ids)))
        rows = []
        for pid in ids:
            c, g, _m = self.now.get((pid, iso), ([0] * 11, 0, 0))
            played = any(c) or g
            r = {"player_id": pid, "name": f"P{pid}", "total_points": self.total.get((pid, iso), points(c))}
            r.update({k: (float(v) if played else "-") for k, v in zip(ORDER, c)})
            rows.append(r)
        return rows


def cache(b, players: dict, today: date, extra=None) -> None:
    """players: {pid: (name, {iso: [points, games]}, {iso: cats} or None, {iso: minutes} or None)}."""
    blob = pa.empty(SEASON, FIRST, HEADER)
    for pid, (n, days, cd, md) in players.items():
        rec = {"name": n, "days": dict(days)}
        if cd is not None:
            rec["cat_days"] = dict(cd)
        if md is not None:
            rec["min_days"] = dict(md)
        rec.update((extra or {}).get(pid, {}))
        blob["players"][str(pid)] = rec
        blob["roster_names"][n] = pid
    pa.write(b, blob, today)


D = [(FIRST + timedelta(days=i)).isoformat() for i in range(10)]


# =============================================================================
# s.2: late-filled lines
# =============================================================================

def test_an_incomplete_line_is_filled_and_recorded_by_the_backfill(tmp_path):
    b = base(tmp_path)
    full = line(4)
    cache(b, {1: ("Zion", {D[0]: [0.0, 1]}, None, {D[0]: 30}),
              2: ("Other", {D[0]: [points(line(5)), 1]}, None, {D[0]: 30})}, FIRST + timedelta(days=1))
    lg = League({(1, D[0]): (full, 1, 30), (2, D[0]): (line(5), 1, 30)})
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=1))
    rec = pa.load(b)["players"]["1"]
    assert rec["days"][D[0]] == [points(full), 1] and rec["cat_days"][D[0]] == full
    assert "cat_corrections" not in rec and rec["late_filled"][D[0]] == {"was": 0.0, "now": points(full)}
    assert r["late_filled"] == [f"Zion {D[0]}: 0.0 cached, {points(full)} now (Yahoo's line filled in late)"]
    assert r["corrections"] == []


def test_the_old_rules_correction_is_settled_with_no_call(tmp_path):
    """Zion's 11-14 as it is cached today: 0.0 in 1 game, categories cached, Yahoo's total kept as a correction."""
    b = base(tmp_path)
    full = line(4)
    cache(b, {1: ("Zion", {D[0]: [0.0, 1]}, {D[0]: full}, {D[0]: 30})}, FIRST + timedelta(days=9),
          extra={1: {"cat_corrections": {D[0]: points(full)}}})
    pa.validate(pa.load(b))                                      # the cache as it is today is valid
    lg = League({})
    r = pa.recheck_recent(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=9))
    rec = pa.load(b)["players"]["1"]
    assert lg.asked == [] and r["calls"] == 0
    assert rec["days"][D[0]] == [points(full), 1] and "cat_corrections" not in rec
    assert r["settled"] == [f"Zion {D[0]}: 0.0 cached, {points(full)} now (Yahoo's line filled in late)"]
    assert pa.season(pa.load(b), "Zion", FIRST) == (points(full), 1)


def test_the_recheck_fills_a_recent_incomplete_line_with_its_minutes(tmp_path):
    b = base(tmp_path)
    full = line(6)
    today = FIRST + timedelta(days=3)
    cache(b, {1: ("Zion", {D[2]: [0.0, 1]}, {D[2]: [0] * 11}, {D[2]: 0})}, today)
    r = pa.recheck_recent(b, source=pa.YahooSource(League({(1, D[2]): (full, 1, 31)})), today=today)
    rec = pa.load(b)["players"]["1"]
    assert rec["days"][D[2]] == [points(full), 1] and rec["cat_days"][D[2]] == full and rec["min_days"][D[2]] == 31
    assert len(r["late_filled"]) == 1 and r["asked"] == 1 and r["calls"] == 2


def test_a_phantom_is_still_corrected_by_the_recheck(tmp_path):
    b = base(tmp_path)
    today = FIRST + timedelta(days=3)
    cache(b, {1: ("Mitchell", {D[2]: [0.0, 1]}, {D[2]: [0] * 11}, {D[2]: 0})}, today)
    r = pa.recheck_recent(b, source=pa.YahooSource(League({})), today=today)     # Yahoo now: 0 games
    rec = pa.load(b)["players"]["1"]
    assert rec["days"][D[2]] == [0.0, 0] and r["phantoms"] and r["late_filled"] == []


def test_a_real_stat_correction_still_isnt_rewritten(tmp_path):
    b = base(tmp_path)
    cached = line(4)
    now = list(cached)
    now[6] += 1                                                  # one more rebound since the night
    cache(b, {1: ("Tatum", {D[0]: [points(cached), 1]}, None, None),
              2: ("Other", {D[0]: [points(line(5)), 1]}, None, None)}, FIRST + timedelta(days=1))
    lg = League({(1, D[0]): (now, 1, 30), (2, D[0]): (line(5), 1, 30)})
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=1))
    rec = pa.load(b)["players"]["1"]
    assert rec["days"][D[0]][0] == points(cached) and rec["cat_corrections"][D[0]] == points(now)
    assert r["late_filled"] == [] and "late_filled" not in rec
    with pytest.raises(pa.ActualsError, match="neither an incomplete line nor a held one"):
        pa.fill_late_line(rec, D[0], now, points(now), HEADER, "Tatum")


def test_a_complete_day_is_never_touched_or_asked_for(tmp_path):
    b = base(tmp_path)
    today = FIRST + timedelta(days=3)
    c = line(3)
    cache(b, {1: ("Done", {D[2]: [points(c), 1]}, {D[2]: c}, {D[2]: 30}),
              2: ("Cameo", {D[1]: [0.0, 1]}, {D[1]: [0] * 11}, {D[1]: 2})}, today)
    before = (b / pa.CACHE_RELPATH).read_bytes()
    lg = League({(1, D[2]): (line(9), 1, 30), (2, D[1]): ([0] * 11, 1, 2)})    # a real 0-point cameo
    r = pa.recheck_recent(b, source=pa.YahooSource(lg), today=today)
    assert [ids for _d, ids in lg.asked] == [(2,)]                 # only the 0-point game is asked for
    assert r["late_filled"] == [] and r["phantoms"] == []
    assert (b / pa.CACHE_RELPATH).read_bytes() == before           # nothing changed, nothing written


def test_the_recheck_window_is_the_configs_and_required(tmp_path):
    b = base(tmp_path, recheck=2)
    today = FIRST + timedelta(days=5)
    cache(b, {1: ("Old", {D[2]: [0.0, 1]}, {D[2]: [0] * 11}, {D[2]: 0}),
              2: ("New", {D[3]: [0.0, 1]}, {D[3]: [0] * 11}, {D[3]: 0})}, today)
    lg = League({(1, D[2]): (line(1), 1, 20), (2, D[3]): (line(2), 1, 20)})
    r = pa.recheck_recent(b, source=pa.YahooSource(lg), today=today)
    assert r["asked"] == 1 and [d for d, _ in lg.asked] == [D[3]]             # D[2] is outside 2 days
    cfg = json.loads((b / "config" / "league_config.json").read_text())
    del cfg["actuals"]["recheck_days"]
    (b / "config" / "league_config.json").write_text(json.dumps(cfg))
    with pytest.raises(pa.ActualsError, match="recheck_days"):
        pa.recheck_days(b)
    real = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert real["actuals"]["recheck_days"] == 3


# =============================================================================
# s.2b: held lines
# =============================================================================

def test_an_inconsistent_player_is_held_back_and_the_others_are_written_on_the_nights_fetch(tmp_path):
    b = base(tmp_path)
    today = FIRST + timedelta(days=1)
    good, naw = line(1), line(2)
    lg = League({(1, D[0]): (good, 1, 30), (2, D[0]): (bad(naw), 1, 32)}, total={(2, D[0]): 23.75})
    r = pa.update(b, source=pa.YahooSource(lg), ids={"Good": 1, "NAW": 2}, today=today, first_day=FIRST,
                  season=SEASON, echo=lambda *a: None)
    blob = pa.load(b)
    assert blob["players"]["1"]["cat_days"][D[0]] == good
    assert "cat_days" not in blob["players"]["2"] and "PTS" in blob["players"]["2"]["cat_pending"][D[0]]
    assert blob["players"]["2"]["days"][D[0]] == [23.75, 1]                  # the points are kept
    assert r["cat_errors"] == [] and len(r["cat_held"]) == 1 and "categories pending" in r["cat_held"][0]
    cs = pa.category_season(blob, "NAW", FIRST, FIRST)
    assert cs["status"] == "ok" and cs["games"] == 0 and cs["skipped"] == [D[0]]   # never "loading" for it


def _held(tmp_path, today, naw_now, total=None):
    b = base(tmp_path)
    good = line(1)
    cache(b, {1: ("Good", {D[0]: [points(good), 1]}, None, None),
              2: ("NAW", {D[0]: [23.75, 1]}, None, None)}, today,
          extra={2: {"cat_pending": {D[0]: "PTS 19 is not 2 x FGM 7 + 3PTM 2 + FTM 1"}}})
    lg = League({(1, D[0]): (good, 1, 30), (2, D[0]): (naw_now, 1, 32)}, total=total)
    return b, lg


def test_a_held_day_that_becomes_consistent_is_written_with_its_points(tmp_path):
    fixed = line(2)
    b, lg = _held(tmp_path, FIRST + timedelta(days=2), fixed)
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=2))
    rec = pa.load(b)["players"]["2"]
    assert rec["cat_days"][D[0]] == fixed and "cat_pending" not in rec
    assert rec["days"][D[0]] == [points(fixed), 1]                # 23.75 came from the line that didn't add up
    assert r["late_filled"] and r["held"] == [] and r["given_up"] == []


def test_a_held_day_whose_points_agree_is_written_with_no_rewrite(tmp_path):
    b = base(tmp_path)
    c = line(2)
    cache(b, {2: ("NAW", {D[0]: [points(c), 1]}, None, None)}, FIRST + timedelta(days=2),
          extra={2: {"cat_pending": {D[0]: "PTS ..."}}})
    r = pa.backfill_categories(b, source=pa.YahooSource(League({(2, D[0]): (c, 1, 30)})),
                               today=FIRST + timedelta(days=2))
    rec = pa.load(b)["players"]["2"]
    assert rec["cat_days"][D[0]] == c and r["late_filled"] == [] and "late_filled" not in rec


def test_a_held_day_that_never_adds_up_stops_being_asked_for(tmp_path):
    naw = bad(line(2))
    # inside the window (3 days): held again, asked again tomorrow
    b, lg = _held(tmp_path, FIRST + timedelta(days=3), naw, total={(2, D[0]): 23.75})
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=3))
    assert len(r["held"]) == 1 and r["given_up"] == [] and D[0] in pa.load(b)["players"]["2"]["cat_pending"]
    # past it: left empty, recorded once
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    rec = pa.load(b)["players"]["2"]
    assert len(r["given_up"]) == 1 and r["given_up"][0].startswith(f"NAW {D[0]}: Yahoo's line never added up: ")
    assert "cat_pending" not in rec and "never added up" in rec["cat_missing"][D[0]]
    assert D[0] not in rec.get("cat_days", {})
    pa.validate(pa.load(b))
    n = len(lg.asked)
    r = pa.backfill_categories(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=5))
    assert len(lg.asked) == n and r["given_up"] == [] and r["days_missing"] == 0     # never asked again


def test_the_backfill_never_stalls_on_one_player(tmp_path):
    b = base(tmp_path)
    today = FIRST + timedelta(days=4)
    days = {pid: {D[i]: [points(line(pid + i)), 1] for i in range(4)} for pid in (1, 2, 3)}
    cache(b, {pid: (f"P{pid}", days[pid], None, None) for pid in (1, 2, 3)}, today)
    now = {(pid, D[i]): (line(pid + i), 1, 30) for pid in (1, 2, 3) for i in range(4)}
    now[(2, D[0])] = (bad(line(2)), 1, 30)
    r = pa.backfill_categories(b, source=pa.YahooSource(League(now, total={(2, D[0]): points(line(2))})),
                               today=today)
    blob = pa.load(b)
    assert r["days_done"] == D[:4] and r["days_left"] == 0
    assert all(len(blob["players"][str(p)]["cat_days"]) == 4 for p in (1, 3))
    assert len(blob["players"]["2"]["cat_days"]) == 3 and D[0] in blob["players"]["2"]["cat_missing"]


def test_validate_checks_the_new_maps(tmp_path):
    b = base(tmp_path)
    c = line(2)
    with pytest.raises(pa.ActualsError, match="in cat_pending and has categories"):
        cache(b, {2: ("NAW", {D[0]: [points(c), 1], D[1]: [0.0, 0]}, {D[0]: c}, None)}, FIRST + timedelta(days=2),
              extra={2: {"cat_pending": {D[0]: "x"}}})
    with pytest.raises(pa.ActualsError, match="not a played, cached day"):
        cache(b, {2: ("NAW", {D[1]: [0.0, 0]}, None, None)}, FIRST + timedelta(days=2),
              extra={2: {"cat_missing": {D[1]: "x"}}})
    with pytest.raises(pa.ActualsError, match="late_filled"):
        cache(b, {2: ("NAW", {D[0]: [points(c), 1]}, {D[0]: c}, None)}, FIRST + timedelta(days=2),
              extra={2: {"late_filled": {D[0]: {"was": 0.0, "now": 1.0}}}})


# =============================================================================
# the nightly records it
# =============================================================================

def test_the_nightly_records_late_fills_and_held_lines(tmp_path, monkeypatch):
    b = base(tmp_path)

    class Src:
        def cats_day(self, *a, **k):
            return {}

        def recheck_day(self, *a, **k):
            return {}

    monkeypatch.setattr(pa, "update", lambda *a, **k: {
        "days_fetched": [], "through": D[0], "calls": 0, "backfilled": [], "ids": {}, "source": Src(),
        "header": HEADER, "cat_errors": [], "cat_held": ["NAW 2026-11-20: categories pending: PTS 19 ..."],
        "min_errors": []})
    monkeypatch.setattr(pa, "update_extras", lambda *a, **k: {
        "players": 0, "no_id": [], "days_fetched": [], "calls": 0, "backfilled": [], "cap": 150,
        "cat_errors": [], "cat_held": [], "min_errors": []})
    monkeypatch.setattr(pa, "backfill_categories", lambda *a, **k: {
        "days_done": [D[0]], "days_left": 0, "calls": 1, "cap": 20, "corrections": [], "stopped": None,
        "late_filled": ["Zion 2026-11-14: 0.0 cached, 32.8 now (Yahoo's line filled in late)"], "held": [],
        "given_up": ["NAW 2026-11-20: Yahoo's line never added up: PTS 19 ..."], "failed_days": []})
    monkeypatch.setattr(pa, "recheck_recent", lambda *a, **k: {
        "days": 3, "asked": 1, "calls": 2, "settled": [], "late_filled": ["X 2026-11-20: 0.0 cached, 12.5 now"],
        "phantoms": []})
    monkeypatch.setattr(pa, "backfill_minutes", lambda *a, **k: {
        "days_done": [], "days_left": 0, "calls": 0, "cap": 35, "corrections": [], "stopped": None})
    from datetime import datetime
    from zoneinfo import ZoneInfo
    run = nightly.Run(b, "nightly", now=datetime(2026, 10, 23, 0, 5, tzinfo=ZoneInfo("America/Los_Angeles")),
                      echo=lambda *a: None)
    detail = run.step_actuals()
    lines = run.ctx["actuals_lines"]
    assert sum(x.startswith("LATE STAT LINE FILLED:") for x in lines) == 2
    assert any(x.startswith("CATEGORIES PENDING: NAW") for x in lines)
    assert any(x.startswith("CATEGORIES LEFT EMPTY: NAW") for x in lines)
    cats = run.ctx["actuals"]["categories"]
    assert cats["held"] and cats["recheck"]["late_filled"] and "1 player-day(s) of categories pending" in detail


# =============================================================================
# the real cache (skips without it)
# =============================================================================

def test_todays_cache_settles_only_zions_day():
    p = ROOT / pa.CACHE_RELPATH
    if not p.exists():
        pytest.skip("no data/player_actuals.json")
    import copy
    blob = pa.load(ROOT)
    work = copy.deepcopy(blob)
    got = pa.settle_recorded_late_lines(work, blob["cats"])
    assert all(x.startswith("Zion Williamson 2026-11-14:") for x in got)
    pa.validate(work)
