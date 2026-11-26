"""AC1: the Advice card rebuilt around days (claude/HANDOFF_AC1_ADVICE_CARD_DAYS_2026-11-26.md;
the design: claude/ADVICE_CARD_DAYS_MOCK_2026-11-25.md). The day strip counts like Team >
Schedule, day by day; the marks, lines and totals; the tiles (Proj points, Win %, Title odds);
the footer; the depth rule; the strip following the "Play for" choice; the page (one tap
control per week with its own readout, 44-point week chips). Synthetic only (the made-up league)."""

from copy import copy
from datetime import date

import pytest

import hub_5d2_world as W
import hub_ac1_fixture as F
import hub_v2_market_fixture as MF
from modules import advice_live as al
from modules.hub_v2 import ranges as R
from modules.hub_v2 import schedule as S

MINUS = "\u2212"


def _plain_av(av, m, roster, extra_info):
    a = copy(av)
    a.rosters = {**av.rosters, m: list(roster)}
    a.info = {**extra_info, **av.info}
    return a


# =============================================================================
# the strip against Team > Schedule
# =============================================================================

def test_the_strip_counts_like_team_schedule_day_by_day():
    """Each box's count is Team > Schedule's own (its Day, sure players), the
    starts under it are the strip's printed starts (schedule.strip_day "s"),
    and the box's change is the same day_fill on an independent route (a real
    Availability copy with the roster replaced), day by day, over week 7 (14
    days) and week 8."""
    w = W.world(today=F.TODAY)
    src, fa_av, m = w["src"], w["fa_av"], "Marcus"
    il = w["next_av"].il.get(m) or {}
    active = [n for n in w["next_av"].rosters[m] if n not in il]
    days = list(w["wk_dates"][7]) + list(w["wk_dates"][8])
    kinds, checked = set(), 0
    for add in w["fa"][:8]:
        for drop in active[-2:]:
            xs = R.move_days(src, fa_av, m, [], {"add": add, "drop": drop, "to_il": None}, days)
            for x, d in zip(xs, days):
                team = src.day(m, d)
                sd = S.strip_day(src, m, d, F.TODAY, {})
                assert x["d"] == d and x["n"] == team.count[0] and x["s"] == sd["s"] == team.starts[0]
                av = src.av_on(d)
                roster = [n for n in av.rosters[m] if n != drop] + [add]
                plain = _plain_av(av, m, roster, fa_av.info)
                plain.grid_status = (lambda base, fa, a_: (lambda n, dd: fa.grid_status(n, dd) if n == a_
                                                           else base.grid_status(n, dd)))(av, fa_av, add)
                b = R.day_fill(plain, m, d, src.light_max, src.standins, src.nba(d))
                assert x["delta"] == b.starts[0] - sd["s"]
                assert x["pts"] == pytest.approx(b.pts[0] - team.pts[0], abs=1e-3)
                box = al.week_block(7, [x])["days"][0]
                assert box["n"] == str(team.count[0])
                kinds.add(box["k"])
                checked += 1
    assert checked == 8 * 2 * len(days)
    assert {"up", "down", "same", "full"} <= kinds                 # every mark is exercised


def test_move_starts_and_the_strip_are_one_source():
    w = W.world(today=F.TODAY)
    src, fa_av, m = w["src"], w["fa_av"], "Tyler"
    days = list(w["wk_dates"][7])
    mv = {"add": w["fa"][3], "drop": w["next_av"].rosters[m][12], "to_il": None}
    xs = R.move_days(src, fa_av, m, [], mv, days)
    ex = R.move_starts(src, fa_av, m, [], mv, days)
    assert ex["delta"] == sum(x["delta"] for x in xs)
    assert ex["gained"] == [x["d"] for x in xs if x["delta"] > 0]
    assert ex["lost"] == [x["d"] for x in xs if x["delta"] < 0]


# =============================================================================
# the engine's strings
# =============================================================================

def _x(**kw):
    x = {"d": date(2026, 12, 1), "nba": 6, "n": 8, "s": 8, "delta": 0, "pts": 0.0, "ins": [], "outs": [],
         "in_names": ["Add Guy"], "drop_names": ["Drop Guy"], "out_names": ["Drop Guy"], "full": False}
    x.update(kw)
    return x


def test_marks_and_the_tapped_days_line():
    up = _x(delta=1, pts=31.44, ins=["Add Guy"])
    assert al.day_kind(up) == "up" and al.DAY_MARK["up"] == "+"
    assert al.day_line(up) == ("Tue 12-01 \u00b7 8 of yours play \u00b7 Add Guy plays, Drop Guy doesn\u2019t: "
                               "+1 start (+31.4 pts).")
    down = _x(delta=-1, pts=-24.0, outs=["Drop Guy"])
    assert al.day_kind(down) == "down" and al.day_line(down).endswith(
        f"Add Guy doesn\u2019t play, Drop Guy does: {MINUS}1 start ({MINUS}24.0 pts).")
    both = _x(pts=5.0, ins=["Add Guy"], outs=["Drop Guy"])
    assert al.day_kind(both) == "same" and "both play: the same starts (+5.0 pts)." in al.day_line(both)
    neither = _x()
    assert "neither plays: the same starts." in al.day_line(neither)
    full = _x(n=11, ins=["Add Guy"], full=True)
    assert al.day_kind(full) == "full" and "no room: 11 already play, so no extra start." in al.day_line(full)
    off = _x(nba=0, n=0)
    assert al.day_kind(off) == "off" and al.day_line(off) == "Tue 12-01 \u00b7 no NBA games."
    one = _x(n=1)
    assert "1 of yours plays" in al.day_line(one)


def test_the_total_the_week_lines_and_the_14_day_week():
    assert al.games_text(4, 3) == "+1 \u00b7 4 gained, 3 lost"
    assert al.games_text(1, 3) == f"{MINUS}2 \u00b7 1 gained, 3 lost"
    assert al.games_text(0, 0) == "0 \u00b7 no day changes"
    w = W.world(today=F.TODAY)
    xs = R.move_days(w["src"], w["fa_av"], "Marcus", [], {"add": w["fa"][5], "drop": "x-nobody"}, w["wk_dates"][7])
    b = al.week_block(7, xs)
    assert len(b["days"]) == 14 and b["sub"] == "14 days" and b["line"].startswith("Wk 7 (14 days): ")
    assert b["days"][0]["col"] == 0 and all(x["col"] is None for x in b["days"][1:])
    assert [x["dow"] for x in b["days"][:7]] == list("MTWTFSS")
    assert al.between_text(date(2026, 11, 30), [7, 8], -3) == f"Joins Mon 11-30. Weeks 7\u20138: {MINUS}3 games"
    assert al.between_text(date(2026, 11, 30), [7], 1) == "Joins Mon 11-30. Week 7: +1 game"


def test_the_depth_rule_and_its_thresholds():
    assert (al.DEPTH_MAX_NET, al.DEPTH_MAX_PTS, al.DEPTH_MIN_WIN, al.DEPTH_MIN_TITLE) == (1, 20.0, 0.010, 0.005)
    assert al.is_depth(0, 5.0, 0.012, None) and al.is_depth(-1, -20.0, 0.010, None)
    assert not al.is_depth(2, 5.0, 0.05, None)                      # the days moved
    assert not al.is_depth(0, 21.0, 0.05, None)                     # the points moved (a better player)
    assert not al.is_depth(0, 5.0, 0.009, None)                     # no real gain
    assert al.is_depth(1, 3.0, None, 0.005) and not al.is_depth(1, 3.0, None, 0.004)   # Rest of season


def test_footer_strings():
    assert al.join_text({"kind": "chat", "effective": "2026-11-30"}) == "Joins Mon 11-30 (chat claim)"
    assert al.join_text({"kind": "monday", "effective": "2026-11-30"}) is None
    assert al.adds_text(2) == "Uses 1 of your 2 adds left this week"
    assert al.adds_text(1) == "Uses your last add this week"
    with pytest.raises(al.AdviceInputError):
        al.adds_text(0)
    assert al.keep_text("Drop Guy", "4%") == "Drop Guy\u2019s keep chance: 4%"


# =============================================================================
# the card, by "Play for" choice
# =============================================================================

def _view():
    from test_hub_v2_market import _payload
    p = _payload(advice=F.advice())
    F.advice_view(p)
    return p["v2"]["market"]["advice"]


def _row(cards, m, k=0):
    return next(c for c in cards if c["m"] == m)["rows"][k]


def test_balanced_has_the_two_matchup_weeks_the_tiles_and_the_footer():
    a = _view()
    r = _row(a["cards"], "Marcus")
    c = r["card"]
    sv = c["strip"]
    assert [b["week"] for b in sv["weeks"]] == [7, 8] and sv["per_week"] and len(sv["weeks"][0]["days"]) == 14
    assert [t["label"] for t in c["tiles"]] == ["Proj points", "Win %", "Title odds"]
    assert [x["label"] for x in c["tiles"][1]["rows"]] == ["Wk 7", "Wk 8"]
    assert c["tiles"][1]["rows"][0]["value"] == r["weeks"][0]["value"]        # the row's own Wk 7 number
    assert c["foot"] == ["Joins Mon 11-30 (chat claim)", "Uses 1 of your 2 adds left this week",
                         f"{F.world()['names']['m_drop1']}\u2019s keep chance: 4%"]
    r2 = _row(a["cards"], "Marcus", 1)
    assert r2["card"]["foot"][1] == "Uses your last add this week"       # step 2: the second of two adds
    assert r["why"] == "" and all(t["label"] not in ("Points", "Exp. starts", "Starts") for t in c["tiles"])
    assert "expected lineup" not in str(a["cards"])                     # the starts sentence is gone


def test_proj_points_is_the_sum_of_the_strip_days():
    w = W.world(today=F.TODAY)
    N = F.world()["names"]
    a = _view()
    c = _row(a["cards"], "Marcus")["card"]
    days = [d for k in (7, 8) for d in w["wk_dates"][k]]
    xs = R.move_days(w["src"], w["fa_av"], "Marcus", [], {"add": N["m_add1"], "drop": N["m_drop1"], "to_il": None}, days)
    assert c["tiles"][0]["value"] == f"{sum(x['pts'] for x in xs):+.0f}".replace("-", MINUS)
    g = sum(x["delta"] for x in xs if x["delta"] > 0)
    l = -sum(x["delta"] for x in xs if x["delta"] < 0)
    assert c["strip"]["total"] == al.games_text(g, l)


def test_the_depth_line_shows_on_a_move_whose_days_barely_move():
    a = _view()
    t = _row(a["cards"], "Tyler")["card"]
    assert t["depth"] == al.DEPTH_TEXT
    assert abs(t["strip"]["net"]) <= al.DEPTH_MAX_NET
    assert _row(a["cards"], "Marcus")["card"]["depth"] == ""


def test_the_strip_follows_the_play_for_choice():
    g = _view()["goals"]["panes"]
    one = _row(g["next"]["cards"], "Marcus")["card"]
    assert [b["week"] for b in one["strip"]["weeks"]] == [7] and not one["strip"]["per_week"]
    assert [x["label"] for x in one["tiles"][1]["rows"]] == ["Wk 7"]
    three = _row(g["next3"]["cards"], "Marcus")["card"]
    assert [b["week"] for b in three["strip"]["weeks"]] == [7, 8, 9] and three["strip"]["per_week"]
    assert [(x["label"], x["value"]) for x in three["tiles"][1]["rows"]][2] == ("Wk 9", "\u2014")  # raised (AC1 result)
    far = _row(g["week:9"]["cards"], "Marcus")["card"]
    assert [b["week"] for b in far["strip"]["weeks"]] == [9]
    assert far["strip"]["between"].startswith("Joins Mon 11-30. Weeks 7\u20138: ")
    assert [x["label"] for x in far["tiles"][1]["rows"]] == ["Wk 9"]
    assert not any(f.startswith("Joins") for f in far["foot"])           # said once, above the strip
    ros = _row(g["ros"]["cards"], "Marcus")["card"]
    assert ros["strip"]["weeks"] == [] and [c["week"] for c in ros["strip"]["chips"]] == list(range(7, 16))
    assert [t["label"] for t in ros["tiles"]] == ["Proj points", "Title odds"]           # no Win %
    assert sum(c["block"]["net"] for c in ros["strip"]["chips"]) == ros["strip"]["net"]
    assert len(ros["strip"]["chips"][0]["block"]["days"]) == 14
    # a goal with the same move as Balanced: its one line, no card
    assert next(c for c in g["next2"]["cards"] if c["m"] == "Marcus")["line"] == al.GOALS_SAME


def test_every_card_string_is_filled():
    """The publish check's rule on the cards: no None / NaN / undefined, no empty box."""
    def strings(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
        elif isinstance(o, str):
            yield o
    a = _view()
    for s_ in strings(a):
        assert not any(b in s_ for b in ("None", "NaN", "undefined")), s_
    for cards in [a["cards"]] + [p["cards"] for p in a["goals"]["panes"].values()]:
        for c in cards:
            for r in c["rows"]:
                sv = (r.get("card") or {}).get("strip")
                for b in (sv["weeks"] + [ch["block"] for ch in sv["chips"] or []]) if sv else []:
                    assert all(x["n"] and x["mark"] and x["line"] and x["d"] for x in b["days"])


def test_without_a_range_source_the_card_says_so():
    from test_hub_v2_market import _payload
    a = _payload(advice=F.advice())["v2"]["market"]["advice"]           # the plain fixture: no range source
    c = _row(a["cards"], "Marcus")["card"]
    assert c["strip"] is None and c["missing"] == al.DAYS_MISSING
    assert [t["label"] for t in c["tiles"]] == ["Win %", "Title odds"]


# =============================================================================
# the page
# =============================================================================

def _page():
    import test_hub_v2 as T2
    from test_hub_v2_market import _payload
    p = _payload(advice=F.advice())
    F.advice_view(p)
    return T2.render(p)


@pytest.mark.slow
def test_the_page_draws_one_tap_control_per_week_with_its_readout():
    import re
    import test_hub_v2 as T2
    h = _page()
    i = h.index('data-pane-of="advice"')
    a = h[i:h.find('data-pane-of="', i + 20)]
    btns = re.findall(r'<button type="button" class="adv-days" data-days data-out="([^"]+)"', a)
    assert btns
    for rid in set(btns):
        assert f'<p class="adv-dayl" id="{rid}" aria-live="polite">' in a
    assert a.count('class="adv-dy ') == len(re.findall(r'data-l="[^"]+"', a))       # every box carries its line
    chips = re.findall(r'<button type="button" class="adv-wchip" aria-expanded="false" aria-controls="([^"]+)"', a)
    assert len(chips) == 9 and all(f'<div class="adv-wblk" id="{c}" hidden>' in a for c in chips)
    ids = re.findall(r'id="([^"]+)"', a)
    assert len(ids) == len(set(ids))
    assert not [b for b in T2.tap_violations(h) if any(c.startswith("adv") for c in b[1])]
    for gone in ("Exp. starts", "expected lineup", "Simulated:"):
        assert gone not in a
    assert "Most of this is depth" in a and "Proj points" in a and "Joins Mon 11-30 (chat claim)" in a


def test_the_tap_classes_include_the_strip_and_the_week_chips():
    from modules.hub_v2 import page_market as pm
    assert {"adv-days", "adv-wchip"} <= set(pm.TAP_CLASSES)
    assert ".adv-days{all:unset;box-sizing:border-box;cursor:pointer;width:100%;min-height:var(--tap-min)" in pm.CSS
    assert "min-width:var(--tap-min);min-height:var(--tap-min)" in pm.CSS[pm.CSS.index(".adv-wchip{"):]
