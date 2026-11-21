"""4a4 s.2 (Nick, 11-20, option 2): the accepted skill OVR.
1. OVR is skill only: the same record gives the same OVR whatever his team's games
   (games left, availability); DUR is where how often he plays goes
2. the fixed scale: OVR is the scale of the estimate alone, no pool
3. the provisional marker's rule (NBA games before this season + this season < 25)
   and where it shows (table, hero with its InfoTip, Compare, the roster grid)
4. Awards' replacement level is its own setting (raises when missing)
Synthetic records only."""
import copy
import re
from types import SimpleNamespace

import pytest

from modules import ratings, skill as SK
from modules import awards

VALUES = {"PTS": 1.0}


def _season(gp, ppg):
    return {"gp": gp, "stats": {"PTS": round(gp * ppg)}}


def _history(players: dict, drafts: dict = None):
    """A stand-in for nba_prior.History: name -> (pid, entry)."""
    ids = {n: str(i + 1) for i, n in enumerate(sorted(players))}
    blob = {"players": {ids[n]: {"seasons": e} for n, e in players.items() if e is not None}}
    idx = SimpleNamespace(resolve=lambda n: (ids.get(n), ("id" if players.get(n) else "id, no seasons")
                                             if n in ids else "unmatched"))
    return SimpleNamespace(index=idx, blob=blob, values=VALUES, drafts={"players": drafts or {}}, _unmatched=set())


def _sx(cfg=None):
    cfg = cfg or ratings.config()
    sc = ratings.skill_config(cfg, "pot")
    return {"sc": sc, "sco": ratings.skill_config(cfg, "ovr"), "prov": int(cfg["skill"]["provisional_games"]),
            "base": {1: 15.0, 2: 18.0, 3: 20.0, 4: 22.0}, "rc": {"a": 30.0, "b": -5.0},
            "scale": sc["scale"]["anchors"], "dur": sc["durability"]["anchors"]}


VET = {"2023-24": _season(70, 30), "2024-25": _season(70, 32), "2025-26": _season(70, 31)}


# ---- 1. skill only

def test_ovr_does_not_move_with_games_left_or_availability_dur_does():
    h, sx = _history({"Vet": VET}), _sx()
    full = ratings._skill_of("Vet", "2026-27", 28, 15, 33.0, 15, h, sx)       # played every team game
    half = ratings._skill_of("Vet", "2026-27", 28, 15, 33.0, 30, h, sx)       # half of them
    assert full["ovr"] == half["ovr"] and full["E_ovr"] == half["E_ovr"]
    assert full["dur"] > half["dur"]
    # no schedule input at all: _skill_of takes no games-left or horizon argument
    import inspect
    assert set(inspect.signature(ratings._skill_of).parameters) == {"name", "season", "age", "g", "f", "tg",
                                                                     "history", "sx"}


def test_ovr_and_pot_are_their_own_weights():
    h, sx = _history({"Vet": VET}), _sx()
    r = ratings._skill_of("Vet", "2026-27", 28, 30, 45.0, 30, h, sx)
    ovr_w = sx["sco"]["this_season_weight"]
    pot_w = sx["sc"]["this_season_weight"]
    assert ovr_w == 10 and pot_w == 2 and sx["sco"]["k_rookie"] == 3                # Nick, 11-20: s2b's settings
    assert r["share_ovr"] > r["share"] and r["E_ovr"] > r["E"]                      # OVR follows a hot season more


# ---- 2. the fixed scale

def test_ovr_is_the_scale_of_the_estimate_alone():
    h, sx = _history({"Vet": VET, "Other": {"2025-26": _season(70, 55)}}), _sx()
    alone = ratings._skill_of("Vet", "2026-27", 28, 10, 30.0, 10, h, sx)
    assert alone["ovr"] == SK.to_rating(alone["E_ovr"], ratings.config()["skill"]["scale"]["anchors"])
    anchors = ratings.config()["skill"]["scale"]["anchors"]
    assert [SK.to_rating(x, anchors) for x, _y in anchors] == [y for _x, y in anchors]   # the anchors are the scale


# ---- 3. provisional

@pytest.mark.parametrize("entry,g,want", [
    (None, 24, True), (None, 25, False),                                  # no NBA record: 25 games this season
    ({"2025-26": _season(10, 20)}, 14, True), ({"2025-26": _season(10, 20)}, 15, False),   # a short career counts
    (VET, 0, False),                                                      # a veteran is never provisional
])
def test_the_provisional_rule(entry, g, want):
    h = _history({"P": entry}, drafts={"1": {"pick": 12}})
    r = ratings._skill_of("P", "2026-27", 21, g, 25.0 if g else None, max(g, 1), h, _sx())
    assert r["provisional"] is want
    assert ratings.config()["skill"]["provisional_games"] == 25


def test_provisional_is_required_config():
    c = copy.deepcopy(ratings.config())
    del c["skill"]["provisional_games"]
    with pytest.raises(ratings.RatingsInputError, match="provisional_games"):
        ratings.config(c)


def test_prov_shows_on_the_table_the_hero_compare_and_the_roster_grid(monkeypatch):
    import test_hub_v2 as T
    from modules.hub_v2 import infotips, publish as v2pub
    from test_hub_v2_players import synth_cards
    real = T.synth_ratings
    who = {}

    def thin(r, prev):
        res = real(r, prev)
        n = sorted(res["players"])[0]
        res["players"][n]["ovr_provisional"] = True
        who["n"] = n
        return res
    monkeypatch.setattr(T, "synth_ratings", thin)
    p = T.synth_payload()
    rows = p["v2"]["players"]["rows"]
    z = next(z for z in rows if z["name"] == who["n"])
    assert z["prov"] and sum(1 for y in rows if y["prov"]) == 1
    h = T.render(p)
    sec = re.search(r'data-route="players"(.*?)</section></div></section>', h, re.S).group(1)
    assert sec.count('<span class="v2-prov">Prov.</span>') == 1
    card = v2pub.card_html_all(p, synth_cards(p))[z["key"]]
    assert '<span class="v2-prov">OVR Prov.</span>' in card
    tip = infotips.tip("prov")
    assert tip[1] == "Small sample: this rating will settle as he plays more."
    others = [c for k, c in v2pub.card_html_all(p, synth_cards(p)).items() if k != z["key"]]
    assert not any("OVR Prov." in c for c in others)
    assert "p.prov" in h and "'Prov.'" in h                                      # Compare draws it from the data


# ---- 4. awards

def test_awards_replacement_level_is_its_own_setting():
    import json
    from pathlib import Path
    live = json.loads((Path(__file__).resolve().parents[1] / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert awards.replacement_quantile(live) == 0.0                     # 4a's meaning of R, kept by the awards
    for bad in ({}, {"awards": {}}, {"awards": {"replacement_quantile": 1.5}}, {"awards": {"replacement_quantile": True}}):
        with pytest.raises(awards.AwardsInputError, match="replacement_quantile"):
            awards.replacement_quantile(bad)
