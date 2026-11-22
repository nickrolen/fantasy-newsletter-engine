"""4a4 s.3-s.4: archetypes v2 (modules/archetypes.py), the archetype's NBA history
(modules/nba_prior.py) and the nine grade tiles (modules/ratings.py; config
ratings.grades, ratings.archetype). claude/HANDOFF_4A4_NBA_HISTORY_OVR_ARCHETYPES_2026-11-20.md.

1. the label: exactly one for every set of standouts in every order; ties are deterministic
2. the blend at 0, 5, 25 and 70 games; a rookie needs 5 games; history with 2 games is labelled
3. the tags: the third standout, efficiency, the trend, "Rookie"
4. the named cases: a Dyson-type is a Ball Hawk; a Booker-type and an Amen-type differ
5. the history: last three PLAYED seasons, 3:2:1 x games, 0-game skipped, point in time;
   the 0-game ruling for availability; who is who (id, unique name, unmatched)
6. the config is required; the archetype ships off; nine tiles in order
7. the real thing, unstubbed (skips without the state or NBA_SEASONS.json)
"""
import copy
import itertools
from pathlib import Path

import pytest

from modules import archetypes as AR
from modules import nba_prior as NP
from modules import ratings

ROOT = Path(__file__).resolve().parents[1]
VALUES = {"FGM": 1.0, "FGA": -0.45, "FTM": 1.0, "FTA": -0.75, "3PTM": 3.0, "PTS": 0.5, "REB": 1.5, "AST": 2.0,
          "ST": 3.0, "BLK": 3.0, "TO": -2.0}


def cfg():
    return copy.deepcopy(ratings.config())


def ac():
    return cfg()["archetype"]


def cats():
    return cfg()["grades"]["categories"]


# =============================================================================
# 1. the label
# =============================================================================

def test_exactly_one_label_for_every_set_and_order():
    allc = AR.every_combination()
    n = sum(len(list(itertools.permutations(c))) for k in range(7) for c in itertools.combinations(AR.SKILLS, k))
    assert len(allc) == n + 1 == 1958                                 # no standout: both all_around and role
    seen = {key for _p, key in allc}
    assert seen | {"star"} == set(AR.LABEL_KEYS) == set(ac()["labels"])   # every style reachable; star by OVR
    pf = ["scoring", "playmaking"]
    for perm, key in allc:
        assert key in AR.LABEL_KEYS
        if not perm:
            assert key in ("all_around", "role")
        else:                                                         # only the pair decides (4a4: pair_first)
            pair = AR.pair_order(list(perm), pf)[:2]
            assert key == AR.PAIRS.get(frozenset(pair), "swiss")
            assert key == AR.label_key(list(reversed(pair)), 0, 3, pf)


def test_scoring_and_playmaking_come_first_from_three_standouts():
    """Nick 11-20: Kyrie -> Bucket Getter, LaMelo -> Floor General, not 3-and-D."""
    a = ac()
    kyrie = AR.classify({"shooting": 89, "steals": 76, "scoring": 75}, 80, None, None, False, a, NAMES)
    lamelo = AR.classify({"shooting": 96, "steals": 89, "playmaking": 84}, None, None, None, False, a, NAMES)
    assert (kyrie["key"], kyrie["tags"][0]) == ("bucket", "Steals")
    assert (lamelo["key"], lamelo["tags"][0]) == ("general", "Steals")
    two = AR.classify({"shooting": 96, "steals": 89}, None, None, None, False, a, NAMES)
    assert two["key"] == "three_d"                                    # two standouts: unchanged


def test_all_around_or_role_player():
    """Nick 11-20: no standout but 3+ skills at or above the rostered median -> All-Around."""
    a = ac()
    assert AR.classify({"scoring": 60, "rebounding": 55, "playmaking": 50, "steals": 40}, None, None, None, False, a,
                       NAMES)["key"] == "all_around"
    assert AR.classify({"scoring": 60, "rebounding": 55, "playmaking": 49.9}, None, None, None, False, a,
                       NAMES)["key"] == "role"


def test_the_handoffs_table():
    k = lambda *s: AR.label_key(list(s))
    assert k("scoring", "playmaking") == "engine"
    assert k("playmaking") == k("playmaking", "shooting") == k("playmaking", "steals") == "general"
    assert k("scoring") == k("scoring", "shooting") == k("scoring", "steals") == "bucket"
    assert k("shooting") == "shooter"
    assert k("shooting", "rebounding") == k("shooting", "blocks") == "stretch"
    assert k("shooting", "steals") == "three_d"
    assert k("scoring", "rebounding") == k("scoring", "blocks") == "interior"
    assert k("playmaking", "rebounding") == "point_forward"
    assert k("rebounding") == "glass"
    assert k("blocks") == k("blocks", "rebounding") == "anchor"
    assert k("steals") == k("steals", "blocks") == "hawk"
    assert k("rebounding", "steals") == k("playmaking", "blocks") == "swiss"


def test_percentile_ties_break_by_the_skills_order():
    p = {s: 80.0 for s in AR.SKILLS[:3]}
    assert AR.ordered_standouts(p, 70) == ["scoring", "shooting", "playmaking"]
    p = {"blocks": 90.0, "steals": 90.0, "rebounding": 75.0}
    assert AR.ordered_standouts(p, 70) == ["steals", "blocks", "rebounding"]
    assert AR.pair_order(["shooting", "playmaking", "scoring"], ["scoring", "playmaking"]) == \
        ["playmaking", "scoring", "shooting"]
    assert AR.ordered_standouts({"blocks": 69.99}, 70) == []


# =============================================================================
# 2. the blend
# =============================================================================

THIS = {k: 1.0 for k in VALUES}
HIST = {k: 3.0 for k in VALUES}


@pytest.mark.parametrize("g,want", [(0, 3.0), (5, (5 * 1 + 25 * 3) / 30), (25, 2.0), (70, (70 * 1 + 25 * 3) / 95)])
def test_the_blend_at_0_5_25_and_70_games(g, want):
    b = AR.blend(THIS if g else None, g, HIST, ac())
    assert b["per_stat"]["PTS"] == pytest.approx(want)
    assert b["basis"] == ("history" if g == 0 else "blend")


def test_a_rookie_needs_5_games():
    a = ac()
    assert AR.blend(THIS, 4, None, a) is None
    assert AR.blend(THIS, 5, None, a)["basis"] == "this season"
    assert AR.blend(None, 0, None, a) is None


def test_history_and_2_games_is_labelled_mostly_from_history():
    b = AR.blend(THIS, 2, HIST, ac())
    assert b["per_stat"]["AST"] == pytest.approx((2 * 1 + 25 * 3) / 27)


def test_features_sum_the_configs_categories_and_the_turnover_share():
    per = {k: v * {"PTS": 20, "3PTM": 2, "AST": 5, "REB": 6, "ST": 1, "BLK": 1, "TO": 3, "FGM": 8, "FGA": 17,
                   "FTM": 4, "FTA": 5}[k] for k, v in VALUES.items()}
    f = AR.features(per, cats())
    assert f["scoring"] == pytest.approx(10.0) and f["shooting"] == pytest.approx(6.0)
    assert f["playmaking"] == pytest.approx(10.0) and f["steals"] == f["blocks"] == pytest.approx(3.0)
    assert f["efficiency"] == pytest.approx(8 - 0.45 * 17 + 4 - 0.75 * 5 - 6)
    gross = sum(per.values()) + 6
    assert f["to_share"] == pytest.approx(6 / gross)


# =============================================================================
# 3. the tags
# =============================================================================

NAMES = {"scoring": "Scoring", "shooting": "Shooting", "playmaking": "Playmaking", "rebounding": "Rebounding",
         "steals": "Steals", "blocks": "Blocks"}


def test_the_third_standout_is_a_tag_and_four_standouts_are_still_a_style():
    a = ac()
    r = AR.classify({"steals": 95, "blocks": 90, "rebounding": 72}, None, None, None, False, a, NAMES)
    assert r["key"] == "hawk" and r["tags"] == ["Rebounding"]
    r = AR.classify({s: 90 for s in AR.SKILLS[:4]}, None, None, None, False, a, NAMES)
    assert r["key"] == "engine"                                       # 4a4: star is the top OVRs, not a count


def test_franchise_star_is_the_four_best_ovrs_with_the_style_as_first_tag():
    from modules import ratings
    cfg = ratings.config()
    mk = lambda ovr, e, key, label, tags: {"ovr": ovr, "ovr_composite": e,
                                           "archetype": {"key": key, "label": label, "standouts": [], "tags": tags}}
    players = {"Wemby": mk(97, 57.0, "interior", "Interior Force", ["Rebounding"]),
               "Luka": mk(96, 56.3, "star_less", "Engine", []), "Jokic": mk(93, 51.8, "general", "Floor General", []),
               "AD": mk(81, 36.9, "anchor", "Paint Anchor", ["Efficient"])}
    fas = {"FA Guy": mk(93, 52.0, "bucket", "Bucket Getter", ["Steals", "Efficient", "Breakout"]),
           "FA Low": mk(60, 20.0, "role", "Role Player", [])}
    stars = ratings.assign_stars(players, fas, cfg)
    assert stars == ["Wemby", "Luka", "FA Guy", "Jokic"]              # ties by the estimate underneath
    assert players["Wemby"]["archetype"]["label"] == "Franchise Star"
    assert players["Wemby"]["archetype"]["tags"] == ["Interior Force", "Rebounding"]
    assert fas["FA Guy"]["archetype"]["tags"] == ["Bucket Getter", "Steals", "Efficient"]     # at most 3
    assert players["AD"]["archetype"]["key"] == "anchor"                                      # not a star now
    assert ratings.assign_stars(players, fas, cfg) == stars                                   # idempotent
    assert players["Wemby"]["archetype"]["tags"] == ["Interior Force", "Rebounding"]


def test_efficiency_and_turnovers():
    a = ac()
    r = AR.classify({}, 70.0, 99.0, None, False, a, NAMES)
    assert r["key"] == "role" and r["tags"] == ["Efficient"]                # efficient wins
    r = AR.classify({}, 69.9, 85.0, None, False, a, NAMES)
    assert r["tags"] == ["Turnover-prone"]
    assert AR.classify({}, 50.0, 84.9, None, False, a, NAMES)["tags"] == []


def test_the_trend_and_rookie():
    a = ac()
    assert AR.trend_of(36.0, 15, 30.0, a) == "breakout"
    assert AR.trend_of(35.9, 15, 30.0, a) is None
    assert AR.trend_of(24.0, 15, 30.0, a) == "down"
    assert AR.trend_of(40.0, 14, 30.0, a) is None                           # under 15 games
    assert AR.trend_of(40.0, 20, None, a) is None
    r = AR.classify({"shooting": 90, "steals": 80, "rebounding": 75}, 80.0, None, "breakout", False, a, NAMES)
    assert r["tags"] == ["Rebounding", "Efficient", "Breakout"]
    r = AR.classify({"shooting": 90}, None, None, "breakout", True, a, NAMES)
    assert r["tags"] == ["Rookie"]                                          # in place of the trend


# =============================================================================
# 4. the named cases (4a2's real-data review, 11-20)
# =============================================================================

def test_a_dyson_type_is_a_ball_hawk_not_a_paint_anchor():
    a = ac()
    assert AR.classify({"steals": 99, "blocks": 40, "rebounding": 50}, 80, None, None, False, a, NAMES)["key"] == "hawk"


def test_a_booker_type_and_an_amen_type_do_not_share_a_label():
    a = ac()
    booker = AR.classify({"scoring": 83, "playmaking": 75, "shooting": 60}, 75, None, None, False, a, NAMES)
    amen = AR.classify({"steals": 78, "rebounding": 70, "blocks": 70, "scoring": 50}, 75, None, None, False, a, NAMES)
    assert booker["key"] == "engine" and amen["key"] == "swiss"
    assert booker["label"] != amen["label"]


# =============================================================================
# 5. the history
# =============================================================================

def _season(gp, pts=200, ast=50):
    st = {k: 0 for k in VALUES}
    st.update(PTS=pts * gp // 10, AST=ast * gp // 10)
    return {"gp": gp, "stats": st}


def test_history_is_the_last_three_played_seasons_weighted_3_2_1_by_games():
    e = {"name": "X", "seasons": {"2020-21": _season(60, 100), "2022-23": _season(50, 300), "2023-24": _season(40, 200),
                                  "2024-25": _season(0), "2025-26": _season(20, 400), "2026-27": _season(10, 999)}}
    h = NP.history_per_game(e, "2026-27", VALUES, [3, 2, 1])
    assert [u[0] for u in h["used"]] == ["2025-26", "2023-24", "2022-23"]   # 0 games skipped; 2026-27 not before
    w = {"2025-26": 3 * 20, "2023-24": 2 * 40, "2022-23": 1 * 50}
    pts = {"2025-26": 40 * 0.5, "2023-24": 20 * 0.5, "2022-23": 30 * 0.5}
    assert h["per_stat"]["PTS"] == pytest.approx(sum(w[s] * pts[s] for s in w) / sum(w.values()))
    assert NP.history_per_game(e, "2020-21", VALUES, [3, 2, 1]) is None     # nothing before: a rookie then
    assert NP.history_per_game(None, "2026-27", VALUES, [3, 2, 1]) is None


def test_the_zero_game_ruling():
    seasons = {"2021-22": _season(0), "2022-23": _season(70), "2023-24": _season(0), "2024-25": _season(60),
               "2025-26": _season(0)}
    c = lambda s, at="2026-27": NP.counts_for_availability(seasons, s, at)
    assert c("2022-23") and c("2024-25")
    assert c("2023-24")                       # between two seasons he played
    assert c("2025-26")                       # immediately before this one
    assert not c("2021-22")                   # before his first season
    assert not c("2025-26", "2027-28")        # after his last (not immediately before)
    assert NP.team_games("2020-21", {"team_games": {"default": 82, "2020-21": 72}}) == 72


def test_who_is_who():
    blob = {"players": {"1": {"name": "Nikola Jokic", "seasons": {}}, "2": {"name": "Jalen Williams", "seasons": {}},
                        "3": {"name": "Jalen Williams", "seasons": {}}}}
    ix = NP.Index(blob, {"Nikola Jokic": 1, "Rookie Guy": 99})
    assert ix.resolve("Nikola Jokic") == ("1", "id")
    assert ix.resolve("Nikola Jokić") == ("1", "name")              # accents, by the unique name
    assert ix.resolve("Rookie Guy") == ("99", "id, no seasons")           # the id still finds his draft pick
    assert ix.entry("Rookie Guy") == (None, "id, no seasons")
    assert ix.resolve("Jalen Williams") == (None, "unmatched")     # two of them: never guessed
    h = NP.History(blob, VALUES, {})
    h.per_game("Jalen Williams", "2026-27", [3, 2, 1])
    assert h.unmatched() == ["Jalen Williams"]


# =============================================================================
# 6. the config
# =============================================================================

def test_the_archetype_is_on_and_every_key_is_required():
    c = cfg()
    assert c["archetype"]["enabled"] is True          # Nick, 11-20: turn them on
    for k in ("history_games", "history_weights", "min_games_rookie", "standout_pct", "star_count", "efficient_pct",
              "turnover_pct", "trend_min_games", "trend_margin", "labels", "tags", "pair_first", "all_around_min",
              "all_around_pct", "all_around_ovr", "star_min_games", "star_min_share"):
        bad = copy.deepcopy(c)
        del bad["archetype"][k]
        with pytest.raises(ratings.RatingsInputError, match=k):
            ratings.config(bad)
    bad = copy.deepcopy(c)
    del bad["archetype"]["labels"]["swiss"]
    with pytest.raises(ratings.RatingsInputError, match="labels"):
        ratings.config(bad)


def test_nine_tiles_in_order():
    c = cfg()
    assert c["grades"]["order"] == ["scoring", "shooting", "playmaking", "rebounding", "steals", "blocks",
                                    "efficiency", "consistency", "schedule"]
    assert list(ratings.CATEGORY_GRADES) == c["grades"]["order"][:7]
    assert all(c["grades"]["min_games"][g] == 5 for g in ratings.CATEGORY_GRADES)
    from modules.hub_v2 import infotips
    for g in c["grades"]["order"]:
        assert infotips.tip("grade_" + g)[0] == c["grades"]["labels"][g]
    assert "this season" in infotips.tip("archetype")[1] and "last three seasons" in infotips.tip("archetype")[1]


# =============================================================================
# 7. the real thing
# =============================================================================

REAL = [ROOT / "config" / "ROSTERS.json", ROOT / "data" / "LINEUPS.xlsx", ROOT / "data" / "player_actuals.json",
        ROOT / "data" / "historical" / "NBA_SEASONS.json"]


@pytest.mark.slow
@pytest.mark.skipif(not all(p.is_file() for p in REAL), reason="needs the league's real state and NBA_SEASONS.json")
def test_todays_archetypes_build():
    res = ratings.for_today(ROOT)
    assert res["history_unmatched"] == []
    labelled = 0
    for p in res["players"].values():
        assert p["archetype_enabled"] is True
        a = p["archetype"]
        if a is None:
            assert p["archetype_reason"]
            continue
        labelled += 1
        assert a["key"] in AR.LABEL_KEYS and len(a["tags"]) <= 3
        assert all(a["skills"][s] >= 70 for s in a["standouts"])
    assert labelled >= 0.9 * len(res["players"])
