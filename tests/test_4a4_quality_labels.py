"""4a4 review (Nick, 11-20, 9:23 PM Mountain): the archetype's quality rules.
- Franchise Star needs games this season: min(star_min_games, ceil(share x the
  most games anyone has played)), so week 1 works and a returning player waits.
- No standout skill: All-Around when OVR is at or above the rostered median,
  else Role Player.
"""
import copy

from modules import ratings


def _cfg():
    return {"archetype": {"star_count": 2, "star_min_games": 10, "star_min_share": 0.7,
                          "labels": {"star": "Franchise Star", "role": "Role Player", "all_around": "All-Around",
                                     "engine": "Engine", "general": "Floor General"}}}


def _p(ovr, g, key="engine", label="Engine"):
    return {"ovr": ovr, "ovr_composite": float(ovr), "skill": {"games": g},
            "archetype": {"key": key, "label": label, "tags": [], "standouts": []}}


def test_a_returning_player_is_not_a_star_until_he_has_played():
    pl = {"A": _p(97, 16), "B": _p(96, 15), "Hali": _p(95, 4), "C": _p(90, 16)}
    assert ratings.assign_stars(pl, None, _cfg()) == ["A", "B"]
    pl = {"A": _p(97, 16), "Hali": _p(99, 4), "C": _p(90, 16)}
    assert ratings.assign_stars(pl, None, _cfg()) == ["A", "C"]
    assert pl["Hali"]["archetype"]["key"] == "engine"


def test_week_one_needs_most_of_the_games_played_so_far():
    pl = {"A": _p(97, 3), "B": _p(96, 2), "C": _p(90, 3)}
    assert ratings.assign_stars(pl, None, _cfg()) == ["A", "C"]      # need min(10, ceil(0.7 x 3) = 3)


def test_no_standout_is_all_around_at_or_above_the_rostered_median_ovr():
    pl = {"Top": _p(90, 16), "Siakam": _p(80, 16, "role", "Role Player"), "Mid": _p(80, 16),
          "Low": _p(70, 16, "all_around", "All-Around"), "Bottom": _p(60, 16)}
    c = _cfg()
    c["archetype"]["star_count"] = 1
    ratings.assign_stars(pl, None, c)
    assert pl["Siakam"]["archetype"]["key"] == "all_around"          # 80 >= median 80
    assert pl["Low"]["archetype"]["key"] == "role"                   # 70 < 80
    once = copy.deepcopy(pl)
    ratings.assign_stars(pl, None, c)                                # idempotent
    assert {n: p["archetype"]["key"] for n, p in pl.items()} == {n: p["archetype"]["key"] for n, p in once.items()}


def test_a_star_with_no_standout_keeps_his_quality_label_as_first_tag():
    pl = {"Star": _p(95, 16, "role", "Role Player"), "B": _p(70, 16), "C": _p(60, 16)}
    c = _cfg()
    c["archetype"]["star_count"] = 1
    ratings.assign_stars(pl, None, c)
    assert pl["Star"]["archetype"]["key"] == "star" and pl["Star"]["archetype"]["tags"][0] == "All-Around"
