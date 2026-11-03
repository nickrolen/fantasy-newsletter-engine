"""Step 1b: the player-actuals cache (modules/player_actuals; Nick's eight
conditions, 11-02). A fake Yahoo source, so nothing here touches the network."""

import json
from datetime import date

import pytest

from modules import player_actuals as pa

FIRST = date(2026, 10, 20)
TODAY = date(2026, 10, 25)          # finished days: 10-20 .. 10-24


class FakeSource:
    """{(pid, day): [points, games]}; anything else -> not played, 0 points.
    fail_on: (pid, day) that raises like a failed Yahoo line."""

    def __init__(self, lines=None, fail_on=None):
        self.lines = lines or {}
        self.fail_on = fail_on
        self.calls = 0
        self.asked = []

    def day(self, pids, d, names):
        self.calls += 2
        self.asked.append((d, tuple(pids)))
        out = {}
        for p in pids:
            if self.fail_on == (p, d):
                raise pa.ActualsError(f"Yahoo returned no {d} games-played stat for {names[p]}")
            out[p] = list(self.lines.get((p, d), [0.0, 0]))
        return out


def run(tmp_path, ids, source, today=TODAY):
    return pa.update(tmp_path, source=source, ids=ids, today=today, first_day=FIRST,
                     season="2026-27", echo=lambda *a: None)


def test_fetches_only_finished_days_and_never_today(tmp_path):
    src = FakeSource({(1, date(2026, 10, 21)): [40.5, 1]})
    r = run(tmp_path, {"A": 1}, src)
    assert r["days_fetched"] == ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24"]
    blob = pa.load(tmp_path)
    assert "2026-10-25" not in blob["players"]["1"]["days"]
    assert blob["players"]["1"]["days"]["2026-10-21"] == [40.5, 1]


def test_a_finished_day_is_fetched_once_and_a_quiet_run_leaves_the_file_alone(tmp_path):
    run(tmp_path, {"A": 1, "B": 2}, FakeSource())
    before = (tmp_path / pa.CACHE_RELPATH).read_bytes()
    src = FakeSource()
    r = run(tmp_path, {"A": 1, "B": 2}, src)
    assert r["days_fetched"] == [] and src.calls == 0
    assert (tmp_path / pa.CACHE_RELPATH).read_bytes() == before
    # the next night: only the day just finished
    src2 = FakeSource()
    r2 = run(tmp_path, {"A": 1, "B": 2}, src2, today=date(2026, 10, 26))
    assert r2["days_fetched"] == ["2026-10-25"]
    assert src2.asked == [(date(2026, 10, 25), (1, 2))]


def test_a_new_pickup_is_backfilled_once_alone(tmp_path):
    run(tmp_path, {"A": 1}, FakeSource())
    src = FakeSource()
    r = run(tmp_path, {"A": 1, "Bane": 9}, src)
    assert r["backfilled"] == ["Bane"]
    assert all(pids == (9,) for _d, pids in src.asked) and len(src.asked) == 5


def test_a_failed_line_refuses_naming_date_and_player_and_writes_no_partial_day(tmp_path):
    src = FakeSource(fail_on=(2, date(2026, 10, 22)))
    with pytest.raises(pa.ActualsError, match=r"2026-10-22.*B"):
        run(tmp_path, {"A": 1, "B": 2}, src)
    blob = pa.load(tmp_path)
    for pid in ("1", "2"):
        days = blob["players"][pid]["days"]
        assert sorted(days) == ["2026-10-20", "2026-10-21"]      # completed days kept
        assert "2026-10-22" not in days                          # no partial day


def test_write_refuses_today_or_later(tmp_path):
    blob = pa.empty("2026-27", FIRST)
    blob["players"]["1"] = {"name": "A", "days": {"2026-10-25": [10.0, 1]}}
    blob["roster_names"] = {"A": 1}
    with pytest.raises(pa.ActualsError, match="not finished"):
        pa.write(tmp_path, blob, TODAY)


def test_games_value_and_the_points_without_a_game_check():
    assert pa.games_value("1", "A", TODAY) == 1
    assert pa.games_value("0", "A", TODAY) == 0
    assert pa.games_value("-", "A", TODAY) == 0
    with pytest.raises(pa.ActualsError):
        pa.games_value("2", "A", TODAY)
    blob = pa.empty("2026-27", FIRST)
    blob["players"]["1"] = {"name": "A", "days": {"2026-10-20": [5.0, 0]}}
    with pytest.raises(pa.ActualsError, match="no game"):
        pa.validate(blob)


def test_parse_game_lines_reads_stat_zero():
    raw = {"fantasy_content": {"players": {
        "0": {"player": [[{"player_key": "466.p.6014"}, {"player_id": "6014"}],
                         {"player_stats": {"stats": [{"stat": {"stat_id": "0", "value": "1"}},
                                                     {"stat": {"stat_id": "2", "value": "30"}}]}}]},
        "1": {"player": [[{"player_id": "6355"}],
                         {"player_stats": {"stats": [{"stat": {"stat_id": "0", "value": "0"}}]}}]},
        "count": 2}}}
    assert pa.parse_game_lines(raw) == {6014: "1", 6355: "0"}


def test_season_and_l14_windows_and_the_dash(tmp_path):
    lines = {(1, date(2026, 10, 20 + i)): [10.0 * (i + 1), 1] for i in range(5)}
    run(tmp_path, {"A": 1, "Hurt": 2}, FakeSource(lines))
    blob = pa.load(tmp_path)
    pts, gp = pa.season(blob, "A", date(2026, 10, 24))
    assert (pts, gp) == (150.0, 5) and pa.fppg_text(pts, gp) == "30.0"
    assert pa.fppg_text(*pa.season(blob, "Hurt", date(2026, 10, 24))) == "\u2014"
    # L14 is the last 14 finished days, clipped to the season's first day
    assert pa.last14(blob, "A", date(2026, 10, 24)) == (150.0, 5)


def test_l14_is_fourteen_days(tmp_path):
    first = date(2026, 10, 1)
    lines = {(1, date(2026, 10, d)): [1.0 if d < 18 else 100.0, 1] for d in range(1, 32)}
    src = FakeSource(lines)
    pa.update(tmp_path, source=src, ids={"A": 1}, today=date(2026, 11, 1), first_day=first,
              season="2026-27", echo=lambda *a: None)
    blob = pa.load(tmp_path)
    assert pa.last14(blob, "A", date(2026, 10, 31)) == (1400.0, 14)       # 10-18 .. 10-31


def test_a_reader_refuses_a_player_the_cache_has_not_seen(tmp_path):
    run(tmp_path, {"A": 1}, FakeSource())
    blob = pa.load(tmp_path)
    with pytest.raises(pa.ActualsStale, match="fetch_player_actuals"):
        pa.season(blob, "Desmond Bane", date(2026, 10, 24))
    with pytest.raises(pa.ActualsStale, match="lacks A"):
        pa.season(blob, "A", date(2026, 10, 25))                          # not fetched yet


def test_the_cache_is_state_in_the_manifest():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    m = json.loads((root / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    assert "data/player_actuals.json" in {f["path"] for f in m["files"]}
