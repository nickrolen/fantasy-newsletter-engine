"""modules/ratings.py (4a): OVR, POT and the grades, on the formula 4a back-tested.

1. point in time: a rating as of day D does not move when log rows after D are added
2. determinism: the same inputs give the same ratings
3. the scale is monotone; the knots pin the anchors
4. grades are percentiles: the share at or above each band matches the band
5. missing inputs raise, naming them; too few games gives None with a reason
6. the real thing, unstubbed, on today's state (skipped without the league's state)
"""
import copy
import json
from pathlib import Path

import pytest

from modules import keeper_history as kh
from modules import ratings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def history():
    return kh.Inputs.load(ROOT)


def log_schedule(inputs, season):
    """{team: dates} from the log itself (every logged team game, both sides):
    the bbref cache is not in the repo, and for these tests any fixed schedule will do."""
    out = {}
    for r in inputs.log[season]:
        if r["had_game"] and r["nba_team"]:
            out.setdefault(r["nba_team"], set()).add(r["date"])
            opp = str(r.get("nba_opponent") or "").lstrip("@")
            if opp:
                out.setdefault(opp, set()).add(r["date"])
    return {t: sorted(v) for t, v in out.items()}


def rate_at(inputs, season, point):
    snap = kh.snapshot(inputs, kh.next_season(season), point, ages=None, check=False, labels=False)
    last = inputs.log[season][-1]["date"]
    return ratings.rate(snap, inputs, log_schedule(inputs, season), last), snap.as_of


# ---------------------------------------------------------------------------
# 1-2
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_a_rating_as_of_a_day_ignores_every_row_after_it(history):
    season = "2024-25"
    full, as_of = rate_at(history, season, "mid")
    cut = kh.Inputs(log={s: ([r for r in rows if r["date"] <= as_of] if s == season else rows)
                         for s, rows in history.log.items() if s <= season},
                    picks=history.picks, trades=history.trades)
    snap = kh.snapshot(cut, kh.next_season(season), "end", ages=None, check=False, labels=False, as_of=as_of)
    again = ratings.rate(snap, cut, log_schedule(history, season), history.log[season][-1]["date"])
    assert again["players"] == full["players"]
    assert again["replacement_level"] == full["replacement_level"]


@pytest.mark.slow
def test_the_same_inputs_give_the_same_ratings(history):
    a, _ = rate_at(history, "2023-24", "week2")
    b, _ = rate_at(history, "2023-24", "week2")
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


@pytest.mark.slow
def test_historical_ratings_are_in_range_and_the_anchors_hold(history):
    res, _ = rate_at(history, "2022-23", "mid")
    ovr = [p["ovr"] for p in res["players"].values() if p["ovr"] is not None]
    assert max(ovr) == 99 and min(ovr) == 60
    for p in res["players"].values():
        assert (p["ovr"] is None) == (p["ovr_reason"] is not None)
        assert p["ovr"] is None or 40 <= p["ovr"] <= 99


# ---------------------------------------------------------------------------
# 3. the scale
# ---------------------------------------------------------------------------

def test_a_higher_composite_never_gets_a_lower_ovr():
    universe = [i * 7.3 for i in range(60)]
    kn = ratings.knots(universe, [[0, 60], [50, 78], [90, 90], [100, 99]])
    xs = [x / 2.0 for x in range(-1000, 1200)]
    ys = [ratings.scale(x, kn, 40, 99) for x in xs]
    assert all(a <= b for a, b in zip(ys, ys[1:]))
    assert 40 <= ys[0] < 60 and ys[-1] == 99            # 5b s.1b: below the knots it nears 40, never clamps
    assert ratings.scale(0.0, kn, 40, 99) == 60 and ratings.scale(max(universe), kn, 40, 99) == 99


def test_equal_composites_at_two_anchors_keep_the_scale_monotone():
    universe = [0.0] * 40 + [float(i) for i in range(1, 21)]          # the median is 0 too
    kn = ratings.knots(universe, [[0, 60], [50, 78], [90, 90], [100, 99]])
    ys = [ratings.scale(x / 10.0, kn, 40, 99) for x in range(-50, 250)]
    assert all(a <= b for a, b in zip(ys, ys[1:]))
    assert ratings.scale(0.0, kn, 40, 99) == 60


# ---------------------------------------------------------------------------
# 4. grades are percentiles
# ---------------------------------------------------------------------------

def test_the_share_at_or_above_each_band_matches_the_band():
    bands = ratings.config()["grade_bands"]
    p = ratings.percentiles({f"p{i}": float(i) for i in range(200)})
    letters = [ratings.letter(v, bands) for v in p.values()]
    order = [name for _low, name in bands]
    for low, name in bands:
        at_or_above = sum(1 for x in letters if order.index(x) <= order.index(name)) / len(letters)
        assert at_or_above == pytest.approx((100 - low) / 100.0, abs=0.006), name


def test_ties_share_a_percentile_and_none_is_left_out():
    p = ratings.percentiles({"a": 1.0, "b": 1.0, "c": 2.0, "d": None})
    assert p["a"] == p["b"] and "d" not in p and p["c"] > p["a"]


# ---------------------------------------------------------------------------
# 5. missing inputs raise; too few games is None with a reason
# ---------------------------------------------------------------------------

def test_a_missing_config_key_raises_naming_it():
    cfg = copy.deepcopy(ratings.config())
    del cfg["ovr"]["availability_k0"]
    del cfg["grades"]["order"]
    with pytest.raises(ratings.RatingsInputError) as e:
        ratings.config(cfg)
    assert "ratings.ovr.availability_k0" in str(e.value) and "ratings.grades.order" in str(e.value)


def test_no_ratings_block_raises():
    with pytest.raises(ratings.RatingsInputError, match="no \"ratings\" block"):
        ratings.config("not a dict")


def test_bad_anchors_raise():
    cfg = copy.deepcopy(ratings.config())
    cfg["ovr"]["anchors"] = [[0, 60], [50, 50], [100, 99]]
    with pytest.raises(ratings.RatingsInputError, match="anchors"):
        ratings.config(cfg)


@pytest.mark.slow
def test_a_team_missing_from_the_schedule_raises_naming_the_player(history):
    season = "2024-25"
    snap = kh.snapshot(history, kh.next_season(season), "mid", ages=None, check=False, labels=False)
    sched = log_schedule(history, season)
    victim = next(c for c in snap.candidates if c.games)
    team = [r for r in history.log[season] if r["player_name"] == victim.player and r["date"] == snap.as_of][0]["nba_team"]
    del sched[team]
    with pytest.raises(ratings.RatingsInputError, match="not in the NBA schedule"):
        ratings.rate(snap, history, sched, history.log[season][-1]["date"])


@pytest.mark.slow
def test_too_few_games_gives_none_with_a_reason(history):
    res, _ = rate_at(history, "2024-25", "week2")              # nobody has 16 games at week 2
    for p in res["players"].values():
        for attr in ("consistency",):                          # 4a4: durability left the tiles
            g = p["grades"][attr]
            assert g["letter"] is None and g["percentile"] is None
            assert "shows after 16" in g["reason"]
        assert "durability" not in p["grades"]
        for attr in ratings.CATEGORY_GRADES:
            # 4a2: a historical day has no per-category stats (rate() is given no actuals)
            assert p["grades"][attr]["letter"] is None
            assert p["grades"][attr]["reason"] == "no per-category stats for this day"
        assert p["archetype"] is None and p["archetype_reason"]


def test_the_weekly_change_comes_from_the_line_a_week_back():
    v = {"versions": dict(ratings.HISTORY_VERSIONS)}
    lines = [dict(v, as_of="2026-11-01", ovr={"A": 80}), dict(v, as_of="2026-11-05", ovr={"A": 82}),
             dict(v, as_of="2026-11-11", ovr={"A": 85})]
    assert ratings.previous_from_history(lines, "2026-11-12") == {"A": 82}
    assert ratings.previous_from_history(lines, "2026-11-04") is None
    # 4a4: a line of 4a's OVR (no versions) is never compared with the skill OVR
    assert ratings.previous_from_history([{"as_of": "2026-11-05", "ovr": {"A": 82}}], "2026-11-12") is None


# ---------------------------------------------------------------------------
# 6. the real thing, unstubbed, on today's state
# ---------------------------------------------------------------------------

REAL = [ROOT / "config" / "ROSTERS.json", ROOT / "data" / "LINEUPS.xlsx"]


@pytest.mark.slow
@pytest.mark.skipif(not all(p.is_file() for p in REAL), reason="needs the league's real state")
def test_todays_ratings_on_the_real_state(history):
    """4a4: the skill OVR on the fixed scale (config ratings.skill.scale): every
    rating is 40..99 and is the scale of the estimate underneath (no pool
    knots); the top three by OVR are top-ten by this season's FPPG or by POT
    (a star is a star on both); free agents and rostered players share it."""
    res = ratings.for_today(ROOT, history=history)
    P = res["players"]
    assert res["universe"] >= 60
    rated = [p for p in P.values() if p["ovr"] is not None]
    # A player who joined a roster after the live log's last day has no OVR until the
    # nightly logs his first day (by design: "not on the league log's last day yet").
    # On a Monday night after the window that is many players (10 of 66 on 11-16), so
    # they leave the denominator: the 90% check is about broken ratings, not churn.
    settled = [p for p in P.values() if "not on the league log's last day yet" not in (p["ovr_reason"] or "")]
    assert len(rated) >= 0.9 * len(settled)
    from modules import skill as SK
    anchors = ratings.config()["skill"]["scale"]["anchors"]
    assert all(40 <= p["ovr"] <= 99 and p["ovr"] == SK.to_rating(p["ovr_composite"], anchors) for p in rated)
    top10 = {p["player"] for p in sorted(rated, key=lambda p: -(p["pot"] or 0))[:10]}
    top3 = sorted(rated, key=lambda p: (-p["ovr"], -p["ovr_composite"]))[:3]
    assert all(p["player"] in top10 for p in top3), [p["player"] for p in top3]
    assert sum(1 for p in P.values() if (p.get("archetype") or {}).get("key") == "star") == 4
    for p in P.values():
        assert (p["ovr"] is None) == bool(p["ovr_reason"])
        assert p["pot"] is None or 40 <= p["pot"] <= 99
        assert p["grades"]["schedule"]["letter"] is not None or p["grades"]["schedule"]["reason"]
    line = ratings.history_line(res)
    assert line["as_of"] == res["as_of"] and set(line["ovr"]) == {p["player"] for p in rated}
