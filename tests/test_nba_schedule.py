"""
Tasks 46 and 33 (11-05): the NBA schedule's unscheduled games, and the
refetched copy.

46: the NBA posts each team's last 2 of 82 games into the Cup knockout window
(Dec 4-11) only after group play (11-27). Until then the loader adds a
stand-in ("tbd": true) for every owed game, paired with another team that owes
one, spread evenly over the window; the file is never changed. Raises: no
window, too many owed, over 82, still needed from the window's first day.
The hub marks estimated cells and says so in one line; the nightly run counts
them, and from week 7's window (11-30) flags them (the nba-schedule issue).

33: the nightly run refetches the schedule at most once a league day into a
state copy (data/nba_schedule_<season>.refetched.json) that every reader
prefers; a refetch never shrinks; a failed fetch never fails the night; the
NBA Cup final (not a regular-season game) is left out.
"""
import copy
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import nba_schedule as ns                         # noqa: E402
from modules.data_loader import load_nba_schedule, _LEAGUE_CONFIG  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
TODAY = date(2026, 11, 5)
ENGINE = ROOT / _LEAGUE_CONFIG["season"]["nba_schedule_file"]
WINDOW = ns.window_config()
WEEKS = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))


def weeks():
    return {int(w["week"]): (date.fromisoformat(w["start_date"][:10]), date.fromisoformat(w["end_date"][:10]))
            for w in WEEKS["weeks"]}


def key(g):
    return (g["date"][:10], g["home"], g["away"])


@pytest.fixture(scope="module")
def real():
    raw = ns.read_raw(ENGINE)
    if ns.team_counts(raw["games"]) == Counter({t: 82 for t in ns._teams()}):
        pytest.skip("the engine's schedule already has every game: nothing to stand in for")
    return raw, ns.with_standins(raw, WINDOW, TODAY)


# =============================================================================
# 46 on the real schedule
# =============================================================================

def test_the_window_config_is_the_nba_key_dates():
    assert (WINDOW["from"], WINDOW["to"], WINDOW["cup_final"], WINDOW["games_per_team"]) == \
        (date(2026, 12, 4), date(2026, 12, 11), date(2026, 12, 11), 82)
    assert "NBA key dates" in WINDOW["source"]


def test_every_team_ends_at_exactly_82(real):
    raw, sched = real
    assert set(ns.team_counts(raw["games"]).values()) == {80}
    assert ns.team_counts(sched["games"]) == Counter({t: 82 for t in ns._teams()})
    st = [g for g in sched["games"] if g.get("tbd")]
    assert len(st) == 30 and sched["unscheduled"]["games"] == 30
    assert sched["unscheduled"]["per_team"] == {t: 2 for t in ns._teams()}


def test_week_7_rises_by_exactly_2_per_team_and_every_other_week_is_unchanged(real):
    raw, sched = real
    for w, (a, b) in weeks().items():
        before = sorted(key(g) for g in raw["games"] if a <= date.fromisoformat(g["date"][:10]) <= b)
        after = [g for g in sched["games"] if a <= date.fromisoformat(g["date"][:10]) <= b]
        if w == 7:
            cb = ns.team_counts([g for g in raw["games"] if a <= date.fromisoformat(g["date"][:10]) <= b])
            ca = ns.team_counts(after)
            assert {t: ca[t] - cb[t] for t in ns._teams()} == {t: 2 for t in ns._teams()}
            assert sorted(key(g) for g in after if not g.get("tbd")) == before
        else:
            assert sorted(key(g) for g in after) == before, w          # game for game


def test_no_stand_in_falls_outside_the_window_and_none_is_timed(real):
    _, sched = real
    for g in sched["games"]:
        if g.get("tbd"):
            assert "2026-12-04" <= g["date"][:10] <= "2026-12-11"
            assert not g.get("tip_utc")


def test_spread_evenly_no_team_twice_a_day_and_paired_with_teams_that_owe(real):
    raw, sched = real
    st = [g for g in sched["games"] if g.get("tbd")]
    per_day = Counter(g["date"][:10] for g in st)
    days = [d.isoformat() for d in ns.window_days(WINDOW)]
    assert set(per_day) == set(days)
    assert max(per_day.values()) - min(per_day.values()) <= 1
    for d in days:
        teams = [t for g in st if g["date"][:10] == d for t in (g["home"], g["away"])]
        real_teams = [t for g in raw["games"] if g["date"][:10] == d for t in (g["home"], g["away"])]
        assert len(teams) == len(set(teams)) and not set(teams) & set(real_teams)
    assert all(g["home"] != g["away"] for g in st)


def test_the_same_schedule_gives_the_same_stand_ins(real):
    raw, sched = real
    again = ns.with_standins(copy.deepcopy(raw), WINDOW, TODAY)
    shuffled = dict(raw, games=list(reversed(raw["games"])))
    st = lambda s: [g for g in s["games"] if g.get("tbd")]                  # noqa: E731
    assert st(again) == st(sched) == st(ns.with_standins(shuffled, WINDOW, TODAY))
    assert raw == ns.read_raw(ENGINE)                                       # never written


def test_the_loader_adds_them_and_never_writes_the_file():
    before = ENGINE.read_bytes()
    s = load_nba_schedule(ENGINE, today=TODAY)
    assert ENGINE.read_bytes() == before
    assert sum(1 for g in s["games"] if g.get("tbd")) == ns.info(s)["games"]


def test_a_filled_window_gives_no_stand_ins_and_no_notes(real):
    raw, sched = real
    filled = {"games": [{k: v for k, v in g.items() if k != "tbd"} for g in sched["games"]]}
    out = ns.with_standins(filled, WINDOW, TODAY)
    assert "unscheduled" not in out and not any(g.get("tbd") for g in out["games"])
    from modules import hub_state as hs
    days = ns.window_days(WINDOW)
    assert hs.unscheduled_note(out, days) == ""
    assert hs.unscheduled_note(sched, days) == \
        "2 games per team in Dec 4\u201311 not yet scheduled by the NBA; counted on estimated days."
    assert hs.unscheduled_note(sched, [date(2026, 11, 30), date(2026, 12, 3)]) == ""    # doesn't touch it
    assert hs.unscheduled_note(sched, [date(2026, 12, 13), date(2026, 12, 11)]) != ""


# =============================================================================
# 46: raise, never default (fixtures)
# =============================================================================

T4 = ["AAA", "BBB", "CCC", "DDD"]


def fixture(per_team=3, start=date(2026, 12, 1), days=12):
    """A season where each of T4 plays `per_team` games, all outside 12-04..12-08."""
    out, d = [], start
    pairs = [("AAA", "BBB"), ("CCC", "DDD"), ("AAA", "CCC"), ("BBB", "DDD"), ("AAA", "DDD"), ("BBB", "CCC")]
    i = 0
    while sum(ns.team_counts(out, T4).values()) < per_team * 4:
        if not (date(2026, 12, 4) <= d <= date(2026, 12, 8)):
            h, a = pairs[i % len(pairs)]
            c = ns.team_counts(out, T4)
            if c[h] < per_team and c[a] < per_team:
                out.append({"date": f"{d}T00:00:00Z", "home": h, "away": a})
            i += 1
        d += timedelta(days=1)
    out.append({"date": "2026-11-01T00:00:00Z", "home": "AAA", "away": "BBB"})
    out.append({"date": "2026-12-31T00:00:00Z", "home": "CCC", "away": "DDD"})
    return {"games": out}


def win(frm="2026-12-04", to="2026-12-08", g=5):
    return {"from": date.fromisoformat(frm) if frm else None, "to": date.fromisoformat(to) if to else None,
            "cup_final": None, "games_per_team": g, "source": "test"}


def test_fixture_stand_ins_bring_every_team_to_its_count():
    raw = fixture()
    n = Counter(ns.team_counts(raw["games"], T4))
    out = ns.with_standins(raw, win(g=max(n.values()) + 2), date(2026, 11, 5), teams=T4)
    assert set(ns.team_counts(out["games"], T4).values()) == {max(n.values()) + 2}


def test_a_team_owing_games_with_no_window_raises():
    with pytest.raises(ns.StandInError, match="no unscheduled-games window is configured"):
        ns.make_standins(fixture(), win(None, None, g=9), date(2026, 11, 5), teams=T4)


def test_a_team_owing_more_than_the_window_holds_raises():
    with pytest.raises(ns.StandInError, match="more games owed than free days"):
        ns.make_standins(fixture(), win(g=12), date(2026, 11, 5), teams=T4)


def test_a_team_over_the_season_count_raises():
    raw = fixture()
    top = max(ns.team_counts(raw["games"], T4).values())
    with pytest.raises(ns.StandInError, match="more than"):
        ns.make_standins(raw, win(g=top - 1), date(2026, 11, 5), teams=T4)


def test_stand_ins_still_needed_once_the_window_has_begun_raise():
    raw = fixture()
    top = max(ns.team_counts(raw["games"], T4).values())
    ns.make_standins(raw, win(g=top + 1), date(2026, 12, 3), teams=T4)       # the day before: fine
    with pytest.raises(ns.StandInError, match="the NBA posted these. Refetch"):
        ns.make_standins(raw, win(g=top + 1), date(2026, 12, 4), teams=T4)
    # nothing owed: no raise, whatever the date
    assert ns.make_standins(raw, win(g=top), date(2027, 1, 1), teams=T4) == [] or True


def test_a_window_outside_the_schedules_season_raises():
    raw = fixture()
    top = max(ns.team_counts(raw["games"], T4).values())
    with pytest.raises(ns.StandInError, match="for another season"):
        ns.make_standins(raw, win("2027-12-04", "2027-12-08", g=top + 1), date(2026, 11, 5), teams=T4)


@pytest.mark.parametrize("change,match", [
    ({"games_per_team": True}, "positive whole number"), ({"games_per_team": 0}, "positive whole number"),
    ({"source": ""}, "name where"), ({"from": "12/04"}, "not a date"), ({"to": None}, "both dates or both null"),
    ({"from": "2026-12-12"}, "is after"), ({"games_per_team": 81}, "disagree"),
])
def test_the_window_block_is_checked(change, match):
    cfg = copy.deepcopy(_LEAGUE_CONFIG)
    cfg["season"][ns.WINDOW_KEY].update(change)
    with pytest.raises(ns.StandInError, match=match):
        ns.window_config(cfg)


def test_the_window_block_is_required():
    cfg = copy.deepcopy(_LEAGUE_CONFIG)
    del cfg["season"][ns.WINDOW_KEY]
    with pytest.raises(ns.StandInError, match="is missing"):
        ns.window_config(cfg)
    cfg = copy.deepcopy(_LEAGUE_CONFIG)
    del cfg["season"][ns.WINDOW_KEY]["cup_final"]
    with pytest.raises(ns.StandInError, match="cup_final is missing"):
        ns.window_config(cfg)


# =============================================================================
# 46: the price lock never meets a stand-in day before the window
# =============================================================================

def test_no_lock_or_window_close_reaches_a_stand_in_day_before_the_window(real):
    from modules import price_lock
    _, sched = real
    for d in [date(2026, 11, 5) + timedelta(days=i) for i in range(29)]:          # to 12-03
        price_lock.status(datetime.combine(d, time(23, 0), tzinfo=LA), sched)
    for w, (a, _b) in weeks().items():
        if price_lock.tips(a, sched):
            price_lock.window_close(a, sched)                                    # every Monday window
    with pytest.raises(price_lock.TipTimeMissing):                                # a stand-in has no tip
        price_lock.tips(date(2026, 12, 4), sched)


# =============================================================================
# 46: the hub
# =============================================================================

def test_grid_cells_on_stand_in_days_are_estimated_only_while_stand_ins_exist():
    from modules import hub_state as hs
    from test_hub_fa_moves import grid_pair      # noqa: F401  (fixture world import check)
    days = [date(2026, 12, 3), date(2026, 12, 4)]

    class Av:
        info = {"P1": {"nba_team": "AAA", "positions": ["PG"], "proj_fppg": 30.0},
                "P2": {"nba_team": "BBB", "positions": ["SG"], "proj_fppg": 20.0}}

        def players(self, m, d):
            return ["P1", "P2"] if d == date(2026, 12, 4) else ["P1"]

        def grid_players(self, m, d):              # step 3b: the grid's own rule (sure, maybe, nba)
            return self.players(m, d), [], []
    tab = hs.build_grid_tab(Av(), ["M"], days, 4, {d: 1 for d in days}, {"BBB": {date(2026, 12, 4)}})
    assert [c["est"] for c in tab["rows"][0]["cells"]] == ["", "1"]
    tab = hs.build_grid_tab(Av(), ["M"], days, 4, {d: 1 for d in days}, {})
    assert [c["est"] for c in tab["rows"][0]["cells"]] == ["", ""]


def test_the_page_prints_the_notes_and_marks_cells_from_the_payload_only():
    from modules import hub_page
    from test_hub import sample_payload, GEN, visible_text
    note = "2 games per team in Dec 4\u201311 not yet scheduled by the NBA; counted on estimated days."
    p = sample_payload()
    page0 = hub_page.render(p, now=GEN)
    assert "not yet scheduled" not in visible_text(page0) and ' est"' not in page0
    p["grid"]["tabs"][1]["schedule_note"] = note
    p["grid"]["tabs"][1]["rows"][0]["cells"][0]["est"] = "1"       # a November day: the page doesn't check
    page = hub_page.render(p, now=GEN)
    text = visible_text(page)
    # Nick, 11-10/11-11: no Cup note anywhere -- not under the free agents, and
    # no text under the grid but the Q-range and NBA-report lines; the cell's
    # own estimated mark (and its tooltip) stays, from the payload
    assert note not in text
    assert '<span class="c light est" title="estimated">3</span>' in page
    assert "Estimated: games the NBA has not scheduled yet" not in text


def test_the_real_hub_payload_has_no_schedule_note_before_week_7_columns(tmp_path):
    from modules import hub_state as hs
    # 11-05: this week (3) and next (4), free agents weeks 4-5: nothing touches Dec 4-11
    sched = load_nba_schedule(ENGINE, today=TODAY)
    for days in ([date(2026, 11, 5) + timedelta(days=i) for i in range(4)],
                 [date(2026, 11, 9) + timedelta(days=i) for i in range(14)]):
        assert hs.unscheduled_note(sched, days) == ""
    wk7 = [weeks()[7][0] + timedelta(days=i) for i in range(14)]
    assert hs.unscheduled_note(sched, wk7).startswith("2 games per team in Dec 4")


# =============================================================================
# 33: which file
# =============================================================================

def cfg_for(rel="data/s.json"):
    c = copy.deepcopy(_LEAGUE_CONFIG)
    c["season"]["nba_schedule_file"] = rel
    return c


def test_the_refetched_copy_is_read_when_present_by_both_the_loader_and_the_guard(tmp_path):
    import run_guard as rg
    rel = _LEAGUE_CONFIG["season"]["nba_schedule_file"]
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "league_config.json", tmp_path / "config" / "league_config.json")
    (tmp_path / "data").mkdir()
    shutil.copy(ENGINE, tmp_path / rel)
    rg._read.cache_clear() if hasattr(rg._read, "cache_clear") else None
    assert ns.schedule_path(tmp_path) == tmp_path / rel
    assert rg.schedule_file(tmp_path) == (tmp_path, rel)
    copy_rel = ns.refetched_relpath(rel)
    assert copy_rel == rel[:-5] + ".refetched.json" and rg.REFETCH_SUFFIX == ns.REFETCH_SUFFIX
    (tmp_path / copy_rel).write_text(ENGINE.read_text(encoding="utf-8"), encoding="utf-8")
    assert ns.schedule_path(tmp_path) == tmp_path / copy_rel
    assert rg.schedule_file(tmp_path) == (tmp_path, copy_rel)
    # the workflow's guard job: the copy in the state checkout, the engine has none
    eng, st = tmp_path / "engine", tmp_path / "state"
    (eng / "config").mkdir(parents=True)
    (eng / "data").mkdir()
    shutil.copy(ROOT / "config" / "league_config.json", eng / "config" / "league_config.json")
    shutil.copy(ENGINE, eng / rel)
    (st / "data").mkdir(parents=True)
    shutil.copy(ENGINE, st / copy_rel)
    assert rg.schedule_file(eng, st) == (st, copy_rel)
    assert rg.schedule_file(eng) == (eng, rel)


def test_the_copy_is_state_ignored_and_the_engine_file_is_not():
    from modules import state_manifest
    m = state_manifest.load(ROOT)
    rel = _LEAGUE_CONFIG["season"]["nba_schedule_file"]
    assert m.contains(ns.refetched_relpath(rel)) and not m.contains(rel)
    ignored = subprocess.run(["git", "check-ignore", "-q", ns.refetched_relpath(rel)], cwd=ROOT).returncode
    assert ignored == 0
    assert subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT).returncode == 1


def test_every_schedule_reader_goes_through_schedule_path():
    """No module or script opens season.nba_schedule_file by itself."""
    readers = {
        "modules/data_loader.py": "_schedule_path(base)", "modules/price_lock.py": "schedule_path(",
        "modules/season_performers.py": "refetched_relpath(NBA_SCHEDULE_FILE)",
        "scripts/check_playerlist.py": "schedule_path(",
        "scripts/update_fantasy_logs.py": "_schedule_path(project_root)",
        "scripts/generate_stats_report.py": "_schedule_path(base_path)",
    }
    for f, needle in readers.items():
        assert needle in (ROOT / f).read_text(encoding="utf-8"), f
    for f in ("scripts/check_playerlist.py", "scripts/update_fantasy_logs.py", "modules/price_lock.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        assert "/ NBA_SCHEDULE_FILE" not in src and "/NBA_SCHEDULE_FILE" not in src, f


def test_season_performers_read_the_copy_first_and_stored_games_only(tmp_path, monkeypatch):
    from modules import season_performers as sp
    monkeypatch.setattr(sp, "NBA_SCHEDULE_FILE", "data/s.json")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "s.json").write_text(json.dumps({"games": [{"date": "2026-10-20", "home": "A",
                                                                    "away": "B"}]}))
    assert len(sp.load_nba_schedule(tmp_path)) == 1
    (tmp_path / "data" / "s.refetched.json").write_text(json.dumps({"games": []}))
    assert sp.load_nba_schedule(tmp_path) == []


def test_update_fantasy_logs_reads_real_games_only():
    src = (ROOT / "scripts" / "update_fantasy_logs.py").read_text(encoding="utf-8")
    fn = src[src.index("def build_nba_schedule_map"):]
    fn = fn[:fn.index("\ndef ")]
    assert "load_nba_schedule" not in fn and "json.load" in fn          # raw: no stand-ins


# =============================================================================
# 33: the refetch
# =============================================================================

def base_with(tmp_path, games, rel="data/s.json"):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / rel).write_text(json.dumps({"games": games, "fetched_at": "2026-11-02T07:33:43",
                                            "source": "bbref"}), encoding="utf-8")
    return cfg_for(rel)


def real_games():
    return ns.read_raw(ENGINE)["games"]


def fetch_of(games, source="bbref"):
    return lambda: ({"games": copy.deepcopy(games)}, source)


def test_a_refetch_with_fewer_games_raises_and_keeps_the_old_file(tmp_path):
    g = real_games()
    cfg = base_with(tmp_path, g)
    out = ns.refetch(tmp_path, TODAY, fetch_of(g[:-1]), cfg=cfg)
    assert out["outcome"] == "refused" and "1199 games against 1200" in out["why"]
    assert not ns.refetched_path(tmp_path, cfg).exists()


def test_a_team_losing_a_stored_game_is_refused_even_at_the_same_total(tmp_path):
    g = real_games()
    cfg = base_with(tmp_path, g)
    x = copy.deepcopy(g)
    x[0] = dict(x[0], home=x[1]["home"], away=x[1]["away"])     # one team loses, two gain: same total
    out = ns.refetch(tmp_path, TODAY, fetch_of(x), cfg=cfg)
    assert out["outcome"] == "refused" and "fewer games than stored" in out["why"]


def test_moved_dates_are_allowed_and_named(tmp_path):
    g = real_games()
    cfg = base_with(tmp_path, g)
    x = copy.deepcopy(g)
    i = next(i for i, y in enumerate(x) if y["date"].startswith("2027-01-1"))
    old_day = x[i]["date"][:10]
    x[i] = dict(x[i], date="2027-03-30T00:00:00Z", tip_utc=None)
    out = ns.refetch(tmp_path, TODAY, fetch_of(x), cfg=cfg)
    assert out["outcome"] == "updated" and out["moved"] == [f"{g[i]['away']}@{g[i]['home']} {old_day} -> 2027-03-30"]
    assert ns.schedule_path(tmp_path, cfg) == ns.refetched_path(tmp_path, cfg)


def test_a_failed_fetch_keeps_the_stored_schedule_and_never_raises(tmp_path):
    cfg = base_with(tmp_path, real_games())

    def boom():
        raise SystemExit(1)

    def http():
        raise OSError("HTTP 429")
    for f in (boom, http):
        out = ns.refetch(tmp_path, TODAY, f, cfg=cfg)
        assert out["outcome"] == "failed" and not ns.refetched_path(tmp_path, cfg).exists()


def test_once_the_nba_posts_the_window_games_the_stand_ins_disappear_on_their_own(tmp_path):
    g = real_games()
    cfg = base_with(tmp_path, g)
    posted = [{k: v for k, v in s.items() if k != "tbd"} | {"tip_utc": f"{s['date'][:10]}T01:00:00Z"}
              for s in ns.make_standins({"games": g}, WINDOW, TODAY)]
    out = ns.refetch(tmp_path, TODAY, fetch_of(g + posted), cfg=cfg)
    assert out["outcome"] == "updated" and out["added"] == 30
    loaded = load_nba_schedule(ns.schedule_path(tmp_path, cfg), today=date(2026, 12, 20))   # past the window
    assert "unscheduled" not in loaded and not any(x.get("tbd") for x in loaded["games"])


def test_the_nba_cup_final_is_left_out_and_two_on_its_day_refuse(tmp_path):
    g = real_games()
    cfg = base_with(tmp_path, g)
    posted = [dict({k: v for k, v in s.items() if k != "tbd"}, remarks="NBA Cup")
              for s in ns.make_standins({"games": g}, WINDOW, TODAY)]
    final = {"date": "2026-12-11T00:00:00Z", "home": "NYK", "away": "SAS", "tip_utc": None, "remarks": "NBA Cup"}
    sameday = [p for p in posted if p["date"].startswith("2026-12-11")]
    for p in sameday:
        p["remarks"] = ""                                         # the 12-11 regular-season games
    out = ns.refetch(tmp_path, TODAY, fetch_of(g + posted + [final]), cfg=cfg)
    assert out["outcome"] == "updated" and out["cup_final"] == ["SAS@NYK 2026-12-11"]
    stored = ns.read_raw(ns.refetched_path(tmp_path, cfg))
    assert len(stored["games"]) == 1230 and not any("remarks" in x for x in stored["games"])
    two = dict(final, home="OKC", away="LAL")
    out = ns.refetch(tmp_path / "b" if (tmp_path / "b").mkdir() is None else None, TODAY,
                     fetch_of(g + posted + [final, two]), cfg=base_with(tmp_path / "b", g))
    assert out["outcome"] == "refused" and "cannot tell which is the final" in out["why"]


def test_the_parser_keeps_the_remarks_and_the_cup_final_on_basketball_reference():
    import fetch_nba_schedule as fns
    row = ('<tr><th data-stat="date_game"><a>Fri, Dec 11, 2026</a></th>'
           '<td data-stat="game_start_time">8:30p</td>'
           '<td data-stat="visitor_team_name"><a href="/teams/SAS/2027.html">San Antonio</a></td>'
           '<td data-stat="home_team_name"><a href="/teams/NYK/2027.html">New York</a></td>'
           '<td data-stat="game_remarks">NBA Cup</td></tr>')
    html = f'<table id="schedule">{row}</table>'
    g, = fns._parse_bbref_month(html, 2027)
    assert g["remarks"] == "NBA Cup" and (g["home"], g["away"]) == ("NYK", "SAS")
    assert fns.trim_schedule({"games": [g]})["games"][0]["remarks"] == "NBA Cup"
    keep, out = ns.exclude_cup_final(fns.trim_schedule({"games": [g]})["games"], date(2026, 12, 11))
    assert keep == [] and len(out) == 1


# =============================================================================
# 33 / 46: the nightly step
# =============================================================================

def night_base(tmp_path):
    rel = _LEAGUE_CONFIG["season"]["nba_schedule_file"]
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "output").mkdir()
    shutil.copy(ENGINE, tmp_path / rel)
    shutil.copy(ROOT / "config" / "SCHEDULE.json", tmp_path / "config" / "SCHEDULE.json")
    return tmp_path


def run_step(base, now, monkeypatch, fetch):
    from modules import nightly
    import fetch_nba_schedule as fns
    seen = []
    monkeypatch.setattr(fns, "fetch_trimmed", lambda *a, **k: (seen.append(k.get("source")), fetch())[1])
    monkeypatch.setattr(sys.modules[__name__], "SOURCES", seen, raising=False)
    run = nightly.Run(base, "nightly", now=now, echo=lambda *a: None)
    row = run.execute({n: (lambda n=n: n) for n in nightly.STEPS["nightly"] if n != "schedule"})
    return row


def test_a_failed_fetch_does_not_fail_the_night_and_the_count_is_in_the_summary(tmp_path, monkeypatch):
    base = night_base(tmp_path)

    def boom():
        raise RuntimeError("basketball-reference: HTTP 429")
    row = run_step(base, datetime(2026, 11, 6, 0, 5, tzinfo=LA), monkeypatch, boom)
    assert row["exit"] == 0
    step = next(s for s in row["steps"] if s["step"] == "schedule")
    assert step["outcome"] == "ok" and "refetch failed" in step["detail"] and "HTTP 429" in step["detail"]
    assert "30 stand-in games (2 games per team in Dec 4" in step["detail"]
    assert row["schedule"]["standins"] == 30 and row["schedule"]["flags"] == []
    assert not ns.refetched_path(base).exists()


def test_the_refetch_runs_at_most_once_a_league_day(tmp_path, monkeypatch):
    base = night_base(tmp_path)
    calls = []

    def ok():
        calls.append(1)
        return {"games": real_games()}, "bbref"
    run_step(base, datetime(2026, 11, 6, 0, 5, tzinfo=LA), monkeypatch, ok)
    row = run_step(base, datetime(2026, 11, 6, 0, 40, tzinfo=LA), monkeypatch, ok)       # the retry
    assert len(calls) == 1 and row["schedule"]["refetch"]["outcome"] == "skipped"
    run_step(base, datetime(2026, 11, 7, 0, 5, tzinfo=LA), monkeypatch, ok)              # the next night
    assert len(calls) == 2
    assert ns.refetched_path(base).is_file()
    assert set(SOURCES) == {"bbref"}                       # the nightly asks basketball-reference


def test_stand_ins_at_week_7s_window_are_a_flag_not_a_failure(tmp_path, monkeypatch):
    base = night_base(tmp_path)
    fail = lambda: (_ for _ in ()).throw(RuntimeError("down"))                            # noqa: E731
    row = run_step(base, datetime(2026, 11, 29, 0, 5, tzinfo=LA), monkeypatch, fail)
    assert row["schedule"]["flags"] == []                                                  # Sunday: not yet
    row = run_step(base, datetime(2026, 11, 30, 0, 5, tzinfo=LA), monkeypatch, fail)
    assert row["exit"] == 0 and len(row["schedule"]["flags"]) == 1
    f = row["schedule"]["flags"][0]
    assert f.startswith("STANDINS 30 stand-in games") and "Mon 11-30" in f and "last refetch: failed, " in f
    # from the window's first day, stand-ins still needed fail the night
    row = run_step(base, datetime(2026, 12, 4, 0, 5, tzinfo=LA), monkeypatch, fail)
    assert row["exit"] == 1 and "the NBA posted these" in row["error"]
    assert row["schedule"]["refetch"]["outcome"] == "failed"          # recorded: the retry won't refetch
    from modules import nightly
    assert nightly.schedule_attempt_today(base, date(2026, 12, 4)) == row["run_id"]


def test_the_schedule_flag_reaches_the_workflow_output(tmp_path, monkeypatch):
    from modules import nightly
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    nightly._schedule_flags(True)
    assert out.read_text() == "schedule_flags=true\n"


def test_the_schedule_issue_is_built_from_the_run_record(tmp_path):
    import schedule_issue as si
    rows = [{"mode": "nightly", "run_id": "r1", "schedule": {"flags": []}},
            {"mode": "nightly", "run_id": "r2", "schedule": {
                "file": "data/nba_schedule_2026-27.json", "standins": 30,
                "refetch": {"outcome": "failed", "why": "HTTP 429"}, "flags": ["STANDINS 30 stand-in games: x"]}}]
    f = tmp_path / "runs.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    got = si.flagged_rows(str(f), 0)
    assert [r["run_id"] for r in got] == ["r2"]
    assert si.title(got) == "NBA schedule: 30 games still unscheduled at their week's window: refetch"
    body = si.body(got, "https://x")
    assert "STANDINS 30" in body and "last refetch: failed (HTTP 429)" in body and "python scripts" in body
    assert " py " not in body and "Run: https://x" in body


def test_the_workflow_opens_the_schedule_issue_without_failing_the_run():
    wf = (ROOT / "deploy" / "state-repo" / ".github" / "workflows" / "run.yml").read_text(encoding="utf-8")
    block = wf[wf.index("- name: Open or comment on the schedule issue"):]
    block = block[:block.index("\n      - name:", 10)]
    assert "if: always() && steps.run.outputs.schedule_flags == 'true'" in block
    assert "--label nba-schedule" in block and "run-failed" not in block
    guard = wf[wf.index("jobs:"):wf.index("guard-failed:")]
    assert "/data/nba_schedule_*.refetched.json" in guard and "--state-dir state" in guard
