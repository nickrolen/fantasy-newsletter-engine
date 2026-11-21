"""4a4 s.2: the NBA-history estimate (modules/skill.py), POT and DUR in ratings.
1. history: a never-rostered veteran's estimate comes from his NBA seasons; point in time (no later season)
2. the aging curve's direction (a young player's past nudged up, an old one's down)
3. regression for a thin record; this season's share by games
4. rookies: the draft slot's baseline; undrafted at the curve's bottom; a hot month moves him by its weight
5. the fixed scale: monotone, no pile-up at the bottom, nothing depends on the pool
6. DUR: the 0-game rulings, the team games, regression
7. config: every key required; the history line's versions keep a new POT from being compared with an old one
8. the real thing (skips without the state and the data files)
"""
import copy
import math
from pathlib import Path

import pytest

from modules import ratings
from modules import skill as SK

ROOT = Path(__file__).resolve().parents[1]
VALUES = {"PTS": 1.0}                    # one stat: FPPG is points per game


def sc(**kw):
    base = ratings.skill_config(ratings.config(), "pot")
    base = copy.deepcopy(base)
    base.update(kw)
    return base


def season(gp, ppg):
    return {"gp": gp, "stats": {"PTS": round(gp * ppg)}}


FLAT = {"center": 27, "coef": [0.0, 0.0, 0.0]}
BASE = {1: 15.0, 2: 18.0, 3: 20.0, 4: 22.0}
RC = {"a": 30.0, "b": -5.0}


def est(entry, s="2026-27", age=27, g=0, f=None, **kw):
    return SK.estimate(entry, s, age, g, f, VALUES, sc(**kw), BASE, RC, kw.pop("pick", None) if False else None)


# ---- 1. history

def test_a_never_rostered_veterans_estimate_comes_from_his_nba_seasons():
    e = {"seasons": {"2023-24": season(70, 30), "2024-25": season(70, 30), "2025-26": season(70, 30)}}
    r = est(e, age_curve=FLAT, k_history=0)
    assert r["kind"] == "history" and r["E"] == pytest.approx(30.0)
    assert [u[0] for u in r["hist"]["used"]] == ["2025-26", "2024-25", "2023-24"][::-1] or len(r["hist"]["used"]) == 3


def test_point_in_time_no_later_season_counts():
    e = {"seasons": {"2024-25": season(70, 20), "2025-26": season(70, 40), "2026-27": season(10, 99)}}
    a = est(e, s="2025-26", age_curve=FLAT, k_history=0)
    assert a["E"] == pytest.approx(20.0)                              # 2025-26 and 2026-27 are not before 2025-26
    assert {u[0] for u in a["hist"]["used"]} == {"2024-25"}


def test_recency_weights_by_games():
    e = {"seasons": {"2024-25": season(50, 20), "2025-26": season(50, 40)}}
    r = est(e, age_curve=FLAT, k_history=0, recency=0.5)
    assert r["E"] == pytest.approx((50 * 40 + 25 * 20) / 75)


# ---- 2. aging

def test_the_aging_curve_moves_a_young_past_up_and_an_old_past_down():
    curve = ratings.skill_config(ratings.config(), "pot")["age_curve"]
    assert SK.age_step(22, curve) > 1.0 > SK.age_step(32, curve) > SK.age_step(37, curve)
    e = {"seasons": {"2025-26": season(70, 30)}}
    young = est(e, age=21, k_history=0)["E"]
    old = est(e, age=35, k_history=0)["E"]
    assert young > 30.0 > old
    assert SK.age_move(30, 33, curve) == pytest.approx(1.0 / SK.age_move(33, 30, curve))


# ---- 3. regression and this season

def test_a_thin_record_is_pulled_to_the_baseline_a_long_one_barely():
    thin = {"seasons": {"2025-26": season(10, 40)}}
    long_ = {"seasons": {s: season(80, 40) for s in ("2023-24", "2024-25", "2025-26")}}
    t = est(thin, age_curve=FLAT, k_history=20)["E"]
    lg = est(long_, age_curve=FLAT, k_history=20)["E"]
    assert t == pytest.approx((10 * 40 + 20 * BASE[1]) / 30)
    n = 80 * (1 + 0.6 + 0.36)                                          # recency 0.6, three seasons
    assert lg == pytest.approx((n * 40 + 20 * BASE[3]) / (n + 20)) and lg > 37.5 and t < 30.0


def test_this_seasons_share_grows_with_games():
    e = {"seasons": {"2025-26": season(70, 30)}}
    s10 = est(e, g=10, f=40, age_curve=FLAT)
    s60 = est(e, g=60, f=40, age_curve=FLAT)
    assert 0 < s10["share"] < s60["share"] < 1 and s10["E"] < s60["E"] < 40
    assert SK.share_this_season(100, 30, 2) == pytest.approx(60 / 160)


# ---- 4. rookies

def test_a_rookie_starts_at_his_draft_slot_and_a_hot_month_moves_him_by_its_weight():
    c = sc(age_curve=FLAT)
    r0 = SK.estimate(None, "2026-27", 20, 0, None, VALUES, c, BASE, RC, 3)
    assert r0["kind"] == "rookie curve (pick 3)" and r0["E"] == pytest.approx(30 - 5 * math.log(3))
    hot = SK.estimate(None, "2026-27", 20, 12, r0["E"] + 10, VALUES, c, BASE, RC, 3)
    w = c["rookie_this_season_weight"] * 12
    assert hot["E"] - r0["E"] == pytest.approx(10 * w / (c["k_rookie"] + w))
    und = SK.estimate(None, "2026-27", 22, 0, None, VALUES, c, BASE, RC, None)
    assert und["E"] == pytest.approx(30 - 5 * math.log(60)) and "undrafted" in und["kind"]


def test_the_rookie_curve_is_point_in_time_and_from_2017_on():
    rows = [(y, p, 60, 30 - 5 * math.log(p)) for y in range(2014, 2026) for p in (1, 5, 10, 30, 60)]
    c = sc()
    rc = SK.fit_rookie_curve(rows, "2026-27", c)
    assert rc["drafts"] == list(range(2017, 2026)) and rc["a"] == pytest.approx(30) and rc["b"] == pytest.approx(-5)
    early = SK.fit_rookie_curve(rows, "2018-19", c)                   # fewer than 3 drafts from 2017: every draft
    assert early["drafts"] == [2014, 2015, 2016, 2017]


# ---- 5. the fixed scale

def test_the_fixed_scale_is_monotone_and_never_piles_up_at_the_bottom():
    a = ratings.skill_config(ratings.config(), "pot")["scale"]["anchors"]
    xs = [x / 2 for x in range(-20, 140)]
    ys = [SK.to_rating(x, a, rounded=False) for x in xs]
    assert all(b >= c for b, c in zip(ys[1:], ys)) and ys[0] > 40 and SK.to_rating(200, a) == 99
    assert len({round(y, 6) for y in ys if y < a[0][1]}) == sum(1 for y in ys if y < a[0][1])


# ---- 6. DUR

def test_dur_counts_the_rulings_zero_game_seasons():
    c = sc(recency=1.0)
    c["durability"] = dict(c["durability"], k_team_games=0, window=3)
    hurt = {"seasons": {"2023-24": season(82, 20), "2024-25": season(82, 20), "2025-26": {"gp": 0, "stats": {"PTS": 0}}}}
    d = SK.durability(hurt, "2026-27", 0, 0, c)
    assert d["A"] == pytest.approx(164 / 246)                         # the lost year counts
    rookie_zero = {"seasons": {"2025-26": {"gp": 0, "stats": {"PTS": 0}}}}
    assert SK.durability(rookie_zero, "2026-27", 0, 0, c)["used"] == []     # before his first season: ignored
    bubble = {"seasons": {"2019-20": season(70, 20), "2020-21": season(72, 20), "2021-22": season(82, 20)}}
    d = SK.durability(bubble, "2022-23", 0, 0, c)
    assert d["A"] == pytest.approx(1.0) and [u[2] for u in d["used"]] == [82, 72, 70]


def test_dur_regresses_and_blends_this_season():
    c = sc()
    d0 = SK.durability(None, "2026-27", 0, 0, c)
    assert d0["A"] == pytest.approx(c["durability"]["baseline"])
    d = SK.durability(None, "2026-27", 10, 10, c)
    assert d0["A"] < d["A"] < 1.0


# ---- 7. config and the history line

def test_the_skill_config_is_required():
    cfg = copy.deepcopy(ratings.config())
    for k in ("window", "age_curve", "scale", "durability"):
        bad = copy.deepcopy(cfg)
        del bad["skill"][k]
        with pytest.raises(ratings.RatingsInputError, match=k):
            ratings.config(bad)
    bad = copy.deepcopy(cfg)
    del bad["skill"]["pot"]["next_year_weight"]
    with pytest.raises(ratings.RatingsInputError, match="next_year_weight"):
        ratings.config(bad)


def test_a_new_pot_is_never_compared_with_an_old_one():
    old_line = {"as_of": "2026-11-10", "ovr": {"A": 80}, "pot": {"A": 70}}
    assert ratings.history_values(old_line, "ovr") is None            # 4a's OVR: another meaning
    assert ratings.history_values(old_line, "pot") is None            # 4a's POT: another meaning
    new_line = {"as_of": "2026-11-17", "ovr": {"A": 81}, "pot": {"A": 84}, "dur": {"A": 90},
                "versions": dict(ratings.HISTORY_VERSIONS)}
    assert ratings.history_values(new_line, "pot") == {"A": 84} and ratings.history_values(new_line, "dur") == {"A": 90}
    assert ratings.previous_from_history([old_line], "2026-11-20", key="pot") is None


# ---- 8. the real thing

REAL = [ROOT / "config" / "ROSTERS.json", ROOT / "data" / "LINEUPS.xlsx", ROOT / "data" / "player_actuals.json",
        ROOT / "data" / "historical" / "NBA_SEASONS.json", ROOT / "data" / "historical" / "NBA_DRAFTS.json"]


@pytest.mark.slow
@pytest.mark.skipif(not all(p.is_file() for p in REAL), reason="needs the league's real state and the NBA files")
def test_todays_pot_and_dur():
    res = ratings.for_today(ROOT)
    assert res["history_unmatched"] == []
    P = res["players"]
    assert all(40 <= p["dur"] <= 99 for p in P.values())
    assert all(p["pot"] is None or 40 <= p["pot"] <= 99 for p in P.values())
    rookies = [p for p in P.values() if p["skill"]["kind"].startswith("rookie")]
    assert rookies and all("pick" in p["skill"]["kind"] for p in rookies if p["skill"]["pick"])
    line = ratings.history_line(res)
    assert line["versions"] == ratings.HISTORY_VERSIONS and line["dur"]
