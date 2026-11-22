"""4a4 review (Nick, 11-20, 9:23 PM Mountain): the archetype's quality rules.
- Franchise Star needs games this season: min(star_min_games, ceil(share x the
  most games anyone has played)), so week 1 works and a returning player waits.
- No standout skill: All-Around when OVR is at or above a fixed
  all_around_ovr (75; Nick, 11-20 10:20 PM Mountain, replacing the rostered
  median), else Role Player.
"""
import copy

from modules import ratings


def _cfg():
    return {"archetype": {"star_count": 2, "star_min_games": 10, "star_min_share": 0.7, "all_around_ovr": 75,
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


def test_no_standout_is_all_around_at_or_above_the_fixed_ovr_cutoff():
    """5d1 s.1: a fixed 75, not the rostered median: the pool around him doesn't move it."""
    pl = {"Top": _p(95, 16), "Castle": _p(78, 16, "role", "Role Player"), "Siakam": _p(76, 16, "role", "Role Player"),
          "Edge": _p(75, 16, "role", "Role Player"), "Mikal": _p(72, 16, "all_around", "All-Around"),
          "Big1": _p(90, 16), "Big2": _p(88, 16), "Big3": _p(86, 16)}          # median 87: the old rule said Role Player
    c = _cfg()
    c["archetype"]["star_count"] = 1
    ratings.assign_stars(pl, None, c)
    assert {n: pl[n]["archetype"]["key"] for n in ("Castle", "Siakam", "Edge", "Mikal")} == \
        {"Castle": "all_around", "Siakam": "all_around", "Edge": "all_around", "Mikal": "role"}
    once = copy.deepcopy(pl)
    ratings.assign_stars(pl, None, c)                                # idempotent
    assert {n: p["archetype"]["key"] for n, p in pl.items()} == {n: p["archetype"]["key"] for n, p in once.items()}
    c["archetype"]["all_around_ovr"] = 77                            # the config decides, nothing else
    ratings.assign_stars(pl, None, c)
    assert pl["Castle"]["archetype"]["key"] == "all_around" and pl["Siakam"]["archetype"]["key"] == "role"


def test_the_cutoff_is_required_never_defaulted():
    import pytest
    c = _cfg()
    del c["archetype"]["all_around_ovr"]
    with pytest.raises(KeyError):
        ratings.assign_stars({"A": _p(80, 16, "role", "Role Player")}, None, c)


def test_a_star_with_no_standout_keeps_his_quality_label_as_first_tag():
    pl = {"Star": _p(95, 16, "role", "Role Player"), "B": _p(70, 16), "C": _p(60, 16)}
    c = _cfg()
    c["archetype"]["star_count"] = 1
    ratings.assign_stars(pl, None, c)
    assert pl["Star"]["archetype"]["key"] == "star" and pl["Star"]["archetype"]["tags"][0] == "All-Around"
