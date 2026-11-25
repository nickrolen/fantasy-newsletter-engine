"""Advice goals on the hub (claude/HANDOFF_ADVICE_GOALS_2026-11-24.md Part B,
C.6, D): the Starts tile counted like Team > Schedule, the picker, each
goal's cards, the switch, the parts. Synthetic only (the made-up league)."""

from copy import copy
from datetime import date

import pytest

import hub_5d2_world as W
import hub_v2_market_fixture as MF
from modules import advice_live as al
from modules.hub_v2 import ranges as R


# =============================================================================
# Part B: the Starts tile (one source: Team > Schedule's day_fill)
# =============================================================================

def _plain_av(av, m, roster, extra_info):
    """A real Availability (hub_state's own class) with m's roster replaced --
    an independent route to Team > Schedule's count."""
    a = copy(av)
    a.rosters = {**av.rosters, m: list(roster)}
    a.info = {**extra_info, **av.info}
    return a


def test_the_starts_tile_counts_like_team_schedule():
    w = W.world()
    src, fa_av, m = w["src"], w["fa_av"], "Marcus"
    days = list(w["wk_dates"][7])
    il = w["av"].il.get(m) or {}
    active = [n for n in w["next_av"].rosters[m] if n not in il]
    drop = active[-1]
    checked = 0
    for add in w["fa"][:6]:
        mv = {"add": add, "drop": drop, "to_il": None}
        ex = R.move_starts(src, fa_av, m, [], mv, days)
        delta, gained = 0, []
        for d in days:
            av = src.av_on(d)
            a = R.day_fill(av, m, d, src.light_max, src.standins, src.nba(d))
            roster = [n for n in av.rosters[m] if n != drop] + [add]
            plain = _plain_av(av, m, roster, fa_av.info)
            plain.grid_status = (lambda base, fa: (lambda n, d: fa.grid_status(n, d) if n == add
                                                   else base.grid_status(n, d)))(av, fa_av)
            b = R.day_fill(plain, m, d, src.light_max, src.standins, src.nba(d))
            x = b.starts[0] - a.starts[0]
            delta += x
            if x > 0:
                gained.append(d)
        assert (ex["delta"], ex["gained"]) == (delta, gained)
        checked += 1
    assert checked == 6


def test_the_starts_tile_names_the_days_and_explains_the_mean():
    t = al.starts_tile(0.6, {"delta": 1, "gained": [date(2026, 12, 5)], "lost": []})
    assert (t["label"], t["value"], t["sub"]) == ("Starts", "+1", "Sat 12-05")
    assert "Team \u203a Schedule" in t["tip"] and "Simulated: +0.6 starts." in t["tip"]
    assert al.STARTS_DISAGREE not in t["tip"]
    days = [date(2026, 12, d) for d in (1, 2, 3, 4, 5)]
    t = al.starts_tile(-0.2, {"delta": 5, "gained": days, "lost": []})
    assert t["sub"] == "Tue 12-01, Wed 12-02, Thu 12-03, +2 more" and al.STARTS_DISAGREE in t["tip"]
    t = al.starts_tile(0.0, {"delta": 0, "gained": [], "lost": []})
    assert (t["value"], t["sub"]) == ("0", "same days")


def test_points_come_first_and_the_reason_leads_with_points_for_a_better_player():
    t = al.v2_tiles({"dstarts": [0.2, 0.1], "dpts": [30.0, 31.0], "title_odds": 0.004, "title_label": "title odds"},
                    show_title=True)
    assert [x["label"] for x in t] == ["Points", "Exp. starts", "Title odds"]
    assert al.v2_why({"dstarts": [0.2, 0.1], "dpts": [30.0, 31.0]}, {"weeks": [7, 8]}).startswith(
        "+61 points over weeks 7\u20138, mostly a better player")
    assert "expected lineup starts" in al.v2_why({"dstarts": [1.5, 1.0], "dpts": [30.0, 31.0]}, {"weeks": [7, 8]})


# =============================================================================
# Part D: the picker and the cards
# =============================================================================

def _goals_view(**kw):
    from test_hub_v2_market import _payload
    return _payload(advice=MF.advice_with_goals(**kw))["v2"]["market"]["advice"]["goals"]


def test_the_picker_and_each_goals_cards():
    g = _goals_view()
    assert [x["key"] for x in g["picker"]] == ["balanced", "next", "next2"]
    assert [x["key"] for x in g["weeks"]] == ["week:11"]
    nxt = {c["m"]: c for c in g["panes"]["next"]["cards"]}
    assert nxt["Marcus"]["rows"][0]["weeks"][0] == {"label": "Wk 10", "value": "+9.4%", "dir": "up"}
    assert [c["label"] for c in nxt["Marcus"]["costs"]] == ["Week 10 win chance", "Week 11 win chance",
                                                             "Title odds", "Adds"]
    assert nxt["Tyler"]["line"] == al.GOALS_SAME and nxt["Dana"]["line"] == al.GOALS_NOISE
    assert nxt["Jordan"]["line"] == al.EMPTY_V2["adds"]
    far = {c["m"]: c for c in g["panes"]["week:11"]["cards"]}["Marcus"]
    assert far["costs"][0]["strip"] and far["costs"][0]["label"] == "Week 10"
    assert far["as_of"] == "As of 12:04 AM." and "Priced against Pick & Roll Call\u2019s roster today." in far["caveat"]
    assert any(c["label"] == "Roster spot" for c in far["costs"])


def test_far_goals_are_hidden_until_far_public():
    g = _goals_view(far_public=False)
    assert [x["key"] for x in g["picker"]] == ["balanced", "next", "next2"] and g["weeks"] == []
    assert "week:11" not in g["panes"]


def test_no_picker_when_the_goals_failed_or_are_off():
    assert _goals_view(error="RuntimeError: x") is None
    old = al.goals_on
    try:
        al.goals_on = lambda cfg=None: False
        assert _goals_view() is None
    finally:
        al.goals_on = old


@pytest.mark.slow
def test_the_page_carries_the_picker_and_the_goal_panes():
    import test_hub_v2 as T2
    from test_hub_v2_market import _payload
    h = T2.render(_payload(advice=MF.advice_with_goals()))
    a = h[h.index('data-pane-of="advice"'):]
    a = a[:a.index('<div class="v2-sec"', 10) if '<div class="v2-sec"' in a[10:] else len(a)]
    assert 'data-goal="balanced" aria-pressed="true"' in a and 'data-goal="next"' in a
    assert 'data-goalweek' in a and '<option value="week:11">Wk 11</option>' in a
    assert 'data-goal-pane="balanced"' in a and 'data-goal-pane="next" hidden' in a
    assert "Same move as Balanced." in a and "What it costs" in a
    assert 'id="gnext-' in a and 'id="gweek-11-' in a                 # the panes' own ids


@pytest.mark.slow
def test_publish_makes_each_goal_a_part_and_keeps_the_first_load():
    import shutil
    import tempfile
    from pathlib import Path
    import test_hub_v2 as T2
    from test_hub_v2_players import synth_cards
    from modules.hub_v2 import publish as v2pub
    from test_hub_v2_market import _payload
    sizes = {}
    for label, adv in (("without", MF.advice_latest()), ("with", MF.advice_with_goals())):
        with tempfile.TemporaryDirectory() as tmp:
            base, out = Path(tmp) / "base", Path(tmp) / "out"
            base.mkdir()
            e = T2._archive(base)
            p = _payload(advice=adv)
            p["v2"]["issue"]["file"] = e["enc"]
            p["newsletter"]["current"]["file"] = e["enc"]
            rep = v2pub.build(base, p, T2.PASS, salt=b"\x09" * 16, out_dir=out, iterations=1000, terms=T2.TERMS,
                              now=T2.GEN, pictures=[], cards=synth_cards(p))
            sizes[label] = (rep["served_bytes"], rep.get("advice_goal_parts") or {})
            if label == "with":
                html = (out / "index.html").read_text(encoding="utf-8")
                assert "Streak Guy" not in html                    # encrypted, never plaintext
    assert sizes["without"][1] == {} and set(sizes["with"][1]) == {"next", "next2", "week:11"}
    assert sizes["with"][0] <= 240_000                              # the first load (index.html as served)
    print("first load without / with goals:", sizes["without"][0], sizes["with"][0], sizes["with"][1])


@pytest.mark.slow
def test_the_4b_rules_hold_on_the_picker_and_the_goal_cards():
    import re
    import test_hub_v2 as T2
    from test_hub_v2_market import _payload
    h = T2.render(_payload(advice=MF.advice_with_goals()))
    assert not [b for b in T2.tap_violations(h) if any(c.startswith(("adv",)) for c in b[1])]
    i = h.index('data-pane-of="advice"')
    a = h[i:h.find('data-pane-of="', i + 20)]
    for b in re.findall(r'<button type="button" class="adv-(?:row|bk|crow adv-crow--btn)[^>]*>', a):
        assert 'aria-controls="' in b and 'aria-expanded="false"' in b
    ids = re.findall(r'id="([^"]+)"', a)
    assert len(ids) == len(set(ids))                                     # the panes' ids never collide
    for c in re.findall(r'<button type="button" class="v2-fchip adv-chip"[^>]*>', a):
        assert "data-goal=" in c and "aria-pressed=" in c


def test_moved_keeps_the_hubs_name_rules_for_an_accented_name():
    """11-25 (the reviewer, on the real state): Moved merged the player info into
    a plain dict, so a roster's "Luka Doncic" missed info's "Luka Dončić" and
    day_fill raised KeyError. The info must keep PlayerIndex's rules, as the
    Availability it wraps does."""
    from modules.data_loader import PlayerIndex
    from modules.hub_v2.ranges import Moved

    class _Av:
        rosters = {"M1": ["Luka Doncic", "A Player"]}
        il = {}
        info = PlayerIndex({"Luka Dončić": {"nba_team": "LAL", "positions": ["PG"], "proj_fppg": 50.0},
                            "A Player": {"nba_team": "BOS", "positions": ["C"], "proj_fppg": 30.0}})
        team_dates = {}

    class _Fa:
        info = {"Free Guy": {"nba_team": "NYK", "positions": ["SF"], "proj_fppg": 25.0}}

    mv = Moved(_Av(), _Fa(), "M1", [{"add": "Free Guy", "drop": "A Player"}])
    assert mv.info["Luka Doncic"]["nba_team"] == "LAL"
    assert mv.info["Free Guy"]["nba_team"] == "NYK"
    assert "Free Guy" in mv.rosters["M1"] and "A Player" not in mv.rosters["M1"]
