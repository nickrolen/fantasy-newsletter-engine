"""5e (claude/HANDOFF_5E_PHONE_REVIEW_2_2026-11-22.md): the "I'm..." picker and
Value to you (s.2), Market's per-range lists and Rest of season as totals,
Advice's wording (s.3). Synthetic only: the made-up league (tests/test_hub_v2.py,
tests/hub_v2_market_fixture.py); no league data."""
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from modules import hub_state as HS                                  # noqa: E402
from modules.hub_v2 import data as D, market, pcols, page, team_value as TVM, infotips   # noqa: E402


# =============================================================================
# s.2 the picker
# =============================================================================

@pytest.fixture(scope="module")
def syn():
    import test_hub_v2 as TH
    p = TH.synth_payload()
    return p, TH.render(p)


def test_no_pick_is_todays_hub(syn):
    """No viewer: no data-viewer on the page, and the viewer-only columns and
    chips are hidden by the page's own CSS until a team is picked."""
    _p, h = syn
    assert 'id="hub" data-viewer' not in h
    css = h[h.index("<style>"):h.index("</style>")]
    assert ".v2-vu,.v2-vu-chip,.v2-vu-v{display:none}" in css
    assert "#hub[data-viewer] th.v2-vu,#hub[data-viewer] td.v2-vu{display:table-cell}" in css
    for m in ("Marcus", "Tyler", "Dana", "Jordan"):
        assert f'#hub[data-viewer="{m}"] .v2-vu-v[data-m="{m}"]{{display:inline}}' in css


def test_the_picker_is_in_the_header_with_every_team_and_says_it_is_not_security(syn):
    _p, h = syn
    hdr = h[h.index('id="app-header"'):h.index("</header>")]
    assert 'id="me-btn"' in hdr and "data-me" in hdr                    # every tab: the header
    sheet = h[h.index('id="me-sheet"'):h.index('<div class="v2-stale-wrap">')]
    assert sorted(re.findall(r'data-me-pick="([A-Za-z]+)"', sheet)) == ["Dana", "Jordan", "Marcus", "Tyler"]
    assert 'data-me-pick=""' in sheet                                    # nobody: today's hub
    title, body = infotips.tip("me")
    assert "not a login" in body and "anyone can pick any team" in body and "this browser" in body


def test_the_viewer_is_remembered_in_the_browser_and_a_storage_error_is_caught():
    js = page.script()
    assert "try{VIEWER=localStorage.getItem('hub.viewer')||'';}catch(e){VIEWER='';}" in js
    assert re.search(r"try\{if\(VIEWER\)\{localStorage\.setItem\('hub\.viewer',VIEWER\);\}else\{localStorage\."
                     r"removeItem\('hub\.viewer'\);\}\}catch\(e\)\{\}", js)
    assert "window.HUBVIEW={get:" in js and "hub:viewer" in js        # other pages read the viewer
    assert "if(VIEWER&&!viewerPick(VIEWER)){VIEWER='';}" in js         # an unknown stored team is nobody


def test_a_pick_turns_on_value_to_you_and_the_light_days_chip(syn):
    p, h = syn
    fv = p["v2"]["fa_value"]["values"]["Free Guy"]
    assert {m: x["tv"] for m, x in fv.items()} == {"Marcus": "+40", "Tyler": "+31", "Dana": "+22", "Jordan": "+13"}
    for m, x in fv.items():                                              # one string per manager, each tagged
        assert f'<span class="v2-vu-v" data-m="{m}">{x["tv"]}</span>' in h
    assert 'class="v2-fchip v2-vu-chip" data-mklight' in h                # Market: plays on my light days
    assert "Games on your empty-slot days" in h                           # fit=, kept and named apart
    assert '<th data-k="vtv" class="v2-vu">' in h                          # the columns, viewer-only
    js = page.script()
    assert "function vuKey(key){return (VIEWER&&(key==='vtv'||key==='vtd'))?key+'@'+VIEWER:key;}" in js
    assert "MK.light&&VIEWER" in js


def test_value_to_you_orders_per_manager(syn):
    p, _h = syn
    g = p["v2"]["players"]["groups"]
    for m in ("Marcus", "Tyler", "Dana", "Jordan"):
        assert f"vtv@{m}" in g["orders"] and f"vtd@{m}" in g["orders"]
    rows = p["v2"]["players"]["rows"]
    i = next(k for k, z in enumerate(rows) if z["name"] == "Free Guy")
    assert g["vu"]["vtv"][i]["Marcus"] == "+40"
    j = next(k for k, z in enumerate(rows) if z["kind"] == "rostered")
    assert g["vu"]["vtv"][j] is None and g["cells"]["vtv"][j] == "—"   # rostered: a dash, with its why
    assert "vtv" in pcols.WHY and "vtd" in pcols.WHY


def test_fa_values_swap_the_cheapest_loss_and_use_an_open_spot():
    """team_value._fa_values: the best roster with the free agent in it, for
    every manager; an open active spot (fewer than starters + bench) means no
    drop."""
    val = {"A": 30.0, "B": 20.0, "C": 5.0, "F": 12.0}

    def tot(roster):
        s = sum(val[n] for n in roster)
        return s, {6: s / 2, 7: s / 2}
    ctx = NS(players={n: None for n in val})
    active = {"Full": ["A", "B", "C"] + [f"X{i}" for i in range(12)], "Open": ["A", "B", "C"]}
    for i in range(12):
        val[f"X{i}"] = 10.0
        ctx.players[f"X{i}"] = None
    bases = {m: tot(R) for m, R in active.items()}
    out = TVM._fa_values(ctx, tot, active, bases, ["F"], [6, 7])
    assert out["Full"]["F"]["drop"] == "C" and out["Full"]["F"]["pts"] == pytest.approx(7.0)
    assert out["Open"]["F"]["drop"] is None and out["Open"]["F"]["pts"] == pytest.approx(12.0)
    with pytest.raises(TVM.TeamValueError):
        TVM._fa_values(ctx, tot, active, bases, ["Nobody"], [6, 7])


def test_the_fa_value_view_is_soft_and_carries_title_delta_at_each_price():
    tv = {"weeks": [6, 7], "fa_values": {"M": {"F": {"pts": 10.0, "by_week": {}, "drop": "C"}}},
          "fa_error": None, "fa_seconds": 0.5}
    v = D.fa_value_view(tv, ({"M": 0.05}, "title", None), ["M"], ["F"])
    assert v["values"]["F"]["M"]["tv"] == "+10" and v["values"]["F"]["M"]["td"] == "+0.5"
    v = D.fa_value_view(dict(tv, fa_error="boom"), ({}, "title", None), ["M"], ["F"])
    assert v["error"] == "boom" and v["values"] == {}
    v = D.fa_value_view(tv, ({}, "title", "no stakes"), ["M"], ["F"])
    assert v["values"]["F"]["M"]["td"] == "—"


# =============================================================================
# s.3 Market and Advice
# =============================================================================

class _Av:
    """playable: every day his NBA team plays (no injuries)."""
    def __init__(self, plays):
        self.plays_on = plays

    def playable(self, name, days):
        return [d for d in days if d in self.plays_on[name]]

    tags = {}
    info = {}


def test_each_range_lists_its_own_best_when_the_schedules_differ(monkeypatch):
    """A late-schedule player tops the Cup range and is nowhere in Next week's."""
    early = [date(2026, 12, 1) + timedelta(days=i) for i in range(7)]
    late = [date(2027, 3, 1) + timedelta(days=i) for i in range(7)]
    recs = [{"player_name": n, "projectedFPPG": f, "player_position(s)": "SF"}
            for n, f in (("Early Eddie", 30.0), ("Late Larry", 31.0), ("Both Bo", 20.0))]
    plays = {"Early Eddie": set(early), "Late Larry": set(late), "Both Bo": set(early) | set(late)}
    av = _Av(plays)
    av.info = {n: {"nba_team": "AAA"} for n in plays}
    monkeypatch.setattr(HS, "free_agent_status", lambda av, n, tag, window: {"chips": [], "source": "healthy"})
    rl = [NS(key="next", days=tuple(early)), NS(key="cup", days=tuple(late))]
    names, extra = HS.range_free_agents(recs, [], av, rl, 2, set(), set(), [early], {"Early Eddie"})
    assert names == {"next": ["Early Eddie", "Both Bo"], "cup": ["Late Larry", "Both Bo"]}
    assert sorted(r["name"] for r in extra) == ["Both Bo", "Late Larry"]      # cards and Players rows for them
    assert all("_pts" not in r for r in extra)


def test_rest_of_season_is_one_total_column_with_the_weeks_in_its_tap():
    import test_hub_v2 as TH
    p = TH.synth_payload()
    rg = p["v2"]["market"]["ranges"]
    ros = rg["avail"]["ros"]
    assert len(ros["weeks"]) == 1 and ros["weeks"][0]["label"].startswith("Games")
    for r in ros["rows"]:
        assert len(r["games"]) == 1 and r["games"][0]["n"] == r["cells"]["total"]
        assert "Wk 9" in r["games"][0]["tip"]["b"] and "proj pts" in r["games"][0]["tip"]["f"]
    assert len(rg["avail"]["next3"]["weeks"]) == 3                       # the other ranges keep their weeks


def test_advice_names_its_weeks_and_labels_its_starts_expected():
    assert "win weeks 6 and 7" in market.intro([6, 7])
    assert "this week and next" not in market.intro([6, 7])
    assert "win week 15" in market.intro([15, None])
    from modules import advice_live as al
    t = al.v2_tiles({"dstarts": [1.0, 0.5], "dpts": [10, 5]}, show_title=False)
    assert t[0]["label"] == "Exp. starts"
    assert "expected lineup starts" in al.v2_why({"dstarts": [1.0, 0.5]}, {"weeks": [6, 7]})
    title, body = infotips.tip("advice")
    assert "Expected starts" in body and "Schedule" in body                  # why the two numbers differ


# =============================================================================
# s.1 Matchups > Next week, Home's two cards (Nick's answers, 11-22 9:17 AM)
# =============================================================================

def _home_of(h):
    return re.search(r'data-route="home">(.*?)<section class="v2-screen"', h, re.S).group(1)


def test_matchups_order_ends_with_next_week(syn):
    _p, h = syn
    mu = re.search(r'data-route="matchups" hidden>(.*?)<section class="v2-screen"', h, re.S).group(1)
    order = [mu.index(x) for x in ("This week", 'data-section="grid"', 'data-section="last"',
                                   'data-section="next"')]
    assert order == sorted(order)


def test_next_week_card_is_last_weeks_pattern_one_link_no_underline(syn):
    p, h = syn
    sec = h[h.index('data-section="next"'):]
    sec = sec[:sec.index("</section>")]
    cards = re.findall(r'<a class="lh-card v2-lcard v2-nxcard"[^>]*>(.*?)</a>', sec, re.S)
    assert cards and all("<a " not in c and "<button" not in c for c in cards)   # one tap target each
    css = h[h.index("<style>"):h.index("</style>")]
    assert ".v2-nxcard,.v2-nxcard *{text-decoration:none}" in css
    assert ".v2-lcard{text-decoration:none" in css
    assert sec.count('class="v2-nxnote"') == 1                                  # one note, the section's
    assert "Early look — the line is set at Monday" in sec
    assert all(c.count("Startable games") == 1 for c in cards)                  # labelled once
    nw = p["v2"]["next_week"]
    for c, html_ in zip(nw["cards"], cards):
        assert c["look"]["line"].startswith("Early look: ") and c["look"]["line"] in html_.replace("&middot;", "·")
        assert "Day by day, both teams" in html_ and "Preview &rsaquo;" in html_


def test_next_week_chips_collapse_after_three():
    from modules.hub_v2 import schedule as S
    assert S.CHIPS_SHOWN == 3
    assert S._back({"tags": [{"text": "IL slot", "kind": "il"}, {"text": "back 01-25", "kind": "il"}]}) == \
        " · back 01-25"
    assert S._tagword({"tags": [{"text": "out, back 11-27", "kind": "out"}]}) == "O · "
    assert S._back({"tags": [{"text": "out, back 11-27", "kind": "out"}]}) == " · back 11-27"


def test_the_trade_block_left_home_and_stays_on_market(syn):
    _p, h = syn
    home = _home_of(h)
    assert 'data-section="trade"' not in home and "Trade block" not in home
    assert re.findall(r'data-section="(\w+)"', home) == ["matchups", "nightly", "power", "teams", "window"]
    mk = re.search(r'data-route="market"(.*?)<section class="v2-screen"', h, re.S).group(1)
    assert 'data-pane="block"' in mk


def test_last_nights_best_per_team_sorted_with_the_top_marked(syn):
    p, h = syn
    n = p["v2"]["home"]["nightly"]
    best = n["last"]["best"]
    assert [x["m"] for x in best] == ["Jordan", "Dana", "Tyler", "Marcus"]
    assert [x["fp_text"] for x in best] == ["56.0", "50.0", "44.0", "38.0"]     # the bench's 55+ never counts
    assert [x["top"] for x in best] == [True, False, False, False]
    assert all(x["name"].endswith("Big") for x in best)
    home = _home_of(h)
    assert home.count('v2-hm-topmk">Top</span>') == 1


def test_one_swing_line_per_matchup(syn):
    p, _h = syn
    n = p["v2"]["home"]["nightly"]
    assert [s["text"] for s in n["swings"]] == ["Jordan v Dana: Jordan 48% → 59%",
                                                "Marcus v Tyler: Marcus 55% → 64%"]
    assert all(s["href"] == "#/matchups" for s in n["swings"])
    assert "Win % chart" in n["swing_note"]


def test_on_a_weeks_first_day_last_weeks_finals():
    from modules.hub_v2 import home as H
    from datetime import datetime, timezone
    tz = timezone(timedelta(hours=-8))
    sun = datetime(2026, 11, 29, 0, 0, tzinfo=tz)
    pts = [((sun - timedelta(hours=1)).isoformat(), 59.0, 41.0), ((sun + timedelta(hours=20)).isoformat(), 30.0, 70.0)]
    s = H.final_swing("Tyler", "Jordan", H._pts_of(pts), sun + timedelta(hours=12), 1500.0, 1522.0)
    assert s["text"] == "Jordan v Tyler: Jordan 41% → won by 22"
    s = H.final_swing("Tyler", "Jordan", H._pts_of(pts), sun + timedelta(hours=12), 1600.0, 1522.0)
    assert s["text"] == "Tyler v Jordan: Tyler 59% → won by 78"


def _world_ctx(today, now_h=1):
    import hub_5d2_world as W
    from datetime import datetime, timezone, time
    w = W.world(today=today)
    tz = timezone(timedelta(hours=-8))
    import pandas as pd
    sched = {"games": [{"date": d.isoformat(), "home": "AAA", "away": "BBB"}
                       for d in sorted({d for ds in w["team_dates"].values() for d in ds})
                       for _k in range(w["src"].nba(d))]}
    return w, {"now": datetime.combine(today, time(now_h), tzinfo=tz), "today": today, "week": w["week"],
               "wk_dates": w["wk_dates"], "nba_schedule": sched,
               "lineups": pd.DataFrame(columns=["date", "manager", "player_name", "slot", "fantasy_points"]),
               "managers": w["managers"], "src": w["src"], "swing_raw": None, "card_of": lambda n: None,
               "team_of": w["teams"], "budget": 3, "adds_left": {m: 3 for m in w["managers"]},
               "ledger": {}, "il_slots": {}, "tags": {}}


def test_tonight_is_the_grids_day_for_today_and_a_q_is_said_in_words():
    from modules.hub_v2 import home as H
    w, ctx = _world_ctx(date(2026, 11, 24))
    t = H.nightly(ctx)["tonight"]
    for r in t["rows"]:
        d = w["src"].day(r["m"], date(2026, 11, 24))             # the games grid's own Day (one memo)
        assert r["starts"] == list(d.starts)
        lo, hi = d.starts
        assert r["big"] == (str(lo) if lo == hi else f"{lo} + {hi - lo} Q") and r["of"] == "of 10"
        assert "–" not in r["big"]
    assert "empty" not in json_dump(t["rows"])                     # never the empty-slot count


def json_dump(x):
    import json
    return json.dumps(x)


class _Src:
    """day(): ranges.day_fill on N players with a game (NBA games given)."""
    def __init__(self, n_with_game):
        self.n = n_with_game

    def day(self, m, d):
        from modules.hub_v2 import ranges as R
        names = [f"P{i}" for i in range(self.n[m])]
        pos = [["PG"], ["SG"], ["SF"], ["PF"], ["C"]]
        av = NS(info={p: {"positions": pos[i % 5], "proj_fppg": 30.0 - i} for i, p in enumerate(names)},
                grid_players=lambda m_, d_: (names, [], []), team_dates={})
        return R.day_fill(av, m, d, 4, nba=5)


def test_the_day_words_4_light_5_and_10_nothing_11_overflow():
    from modules.hub_v2 import home as H
    _w, ctx = _world_ctx(date(2026, 11, 24))
    ctx["src"] = _Src({"Marcus": 4, "Tyler": 5, "Dana": 10, "Jordan": 11})
    rows = {r["m"]: r for r in H.nightly(ctx)["tonight"]["rows"]}
    assert rows["Marcus"]["word"] == "Light day"
    assert rows["Tyler"]["word"] == "" and rows["Dana"]["word"] == ""          # 5 has 5 empty slots: no word
    assert rows["Jordan"]["word"] == "Overflow day"
    assert rows["Tyler"]["big"] == "5" and rows["Jordan"]["big"] == "10"


def test_a_day_with_no_nba_games_says_so():
    from modules.hub_v2 import home as H
    _w, ctx = _world_ctx(date(2026, 11, 26))                        # the made-up league's Thanksgiving
    t = H.nightly(ctx)["tonight"]
    assert t["rows"] == [] and t["empty"].startswith("No NBA games tonight.") and "Next games: Fri 11-27" in t["empty"]


def _window_ctx(today, now, close_at):
    """A schedule whose window Monday's last tip is close_at + 5 minutes."""
    w, ctx = _world_ctx(today)
    from datetime import timezone
    tip = (close_at + timedelta(minutes=5)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx["nba_schedule"] = {"games": [{"date": close_at.date().isoformat(), "home": "AAA", "away": "BBB",
                                      "tip_utc": tip}]}
    ctx["now"] = now
    return w, ctx


def test_moves_window_on_its_monday_before_and_after_the_close():
    from modules.hub_v2 import home as H
    from datetime import datetime
    from modules.league_clock import league_tz
    tz = league_tz()
    mon = date(2026, 11, 23)
    close = datetime(2026, 11, 23, 19, 25, tzinfo=tz)
    _w, ctx = _window_ctx(mon, datetime(2026, 11, 23, 9, 0, tzinfo=tz), close)
    ctx["week"] = 6
    w = H.window(ctx)
    assert w["open"] and w["head"] == "Window open: closes today at 7:25 PM"
    ctx["now"] = datetime(2026, 11, 23, 19, 30, tzinfo=tz)
    w = H.window(ctx)
    assert not w["open"] and w["head"] == "Next window: Mon 11-30 · in 7 days"
    assert "Mon 12-07 is not a window" in w["sub"]                              # week 7: 14 days, one window


def test_week_7_has_one_window_and_12_07_is_not_one():
    from modules.hub_v2 import home as H
    from datetime import datetime
    from modules.league_clock import league_tz
    tz = league_tz()
    for today, n in ((date(2026, 12, 1), 13), (date(2026, 12, 7), 7)):
        _w, ctx = _world_ctx(today)
        ctx["week"] = 7
        ctx["now"] = datetime.combine(today, datetime.min.time(), tzinfo=tz) + timedelta(hours=9)
        w = H.window(ctx)
        assert not w["open"] and w["head"] == f"Next window: Mon 12-14 · in {n} days"
    assert "Mon 12-07 is not a window" in H.window(dict(ctx, today=date(2026, 12, 1),
                                                         now=ctx["now"] - timedelta(days=6)))["sub"]


def test_moves_window_counts_adds_through_the_hubs_own_count():
    """Adds left come from hub_state's `adds` (transaction_rulings.add_budget_week via
    adds_by_budget_week, plus the ledger's claims): the same count as everywhere."""
    src = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    i = src.index("v2data.home_soft(")
    assert '"adds_left": {m: max(0, int(budget) - len((adds or {}).get(m, []))) for m in managers}' in src[i:i + 900]
    assert "adds = {m: list(v) for m, v in tr.adds_by_budget_week(base, sched).get(week, {}).items()}" in src


def test_a_pending_claim_a_drop_and_a_blocked_team(syn):
    p, h = syn
    w = p["v2"]["home"]["window"]
    assert [x["text"] for x in w["moves"]] == ["Dana claimed Free Guy", "Dana dropped Dana Bench"]
    assert w["moves"][0]["sub"] == "joins Mon 12-07 · used one of week 9's adds"
    assert w["moves"][1]["sub"].startswith("free for week 10 now")
    assert w["blocked"][0]["player"] == "Tyler Hurt" and "can't make moves" in w["blocked"][0]["text"]
    assert [x["left"] for x in w["adds"]] == ["2", "3", "0", "1"]
    home = _home_of(h)
    assert 'href="#/market?seg=moves"' in home and 'href="#/market?seg=advice"' in home


def test_a_failed_home_card_says_it_couldnt_update_and_never_fails_v2():
    import test_hub_v2 as TH
    p = TH.synth_payload()
    p["v2"]["home"] = {"nightly": {"error": "Boom: no log"}, "window": p["v2"]["home"]["window"]}
    h = TH.render(p)
    home = _home_of(h)
    assert "Couldn’t update on this run." in home and "Boom: no log" in home
    assert D.soft_notes(p) == ["Last night · Tonight couldn't update: Boom: no log"]


def test_no_rule_numbers_in_the_ui(syn):
    import test_hub_v2 as TH
    from modules.hub_v2 import publish_check as PC
    _p, h = syn
    t = TH.visible_text(h)
    assert not re.search(r"\brules?\s+\d", t, re.I), re.search(r".{40}\brules?\s+\d.{20}", t, re.I).group(0)
    assert PC.rule_audit({"x": "<p>a claim (rule 7)</p>"}) and not PC.rule_audit({"x": "<p>the rules</p>"})


def test_2019_20_rookie_of_the_year_has_no_winner():
    import json
    b = json.loads((ROOT / "data/historical/AWARDS_PAST.json").read_text(encoding="utf-8"))
    a = b["seasons"]["2019-20"]["awards"]["roy"]
    assert a["winner"] is None and a["none"] == "No winner: no rookie reached 10 starts"
    assert {r["label"] for r in a["ineligible"]} >= {"Ja Morant", "Zion Williamson"}


def test_draft_of_the_year_alltime_list_is_the_keeper_era_only():
    """5E decision 5 (Nick, 11-23): the 13-pick full-pool snake drafts before the
    keeper era are a different game, so Records' all-time Draft of the year list
    starts at league_structure keeper_era_start (2021-22). Each season's own
    winner is still listed for every season."""
    import json
    from pathlib import Path
    from modules.data_loader import KEEPER_ERA_START
    blob = json.loads((Path(__file__).parent.parent / "data" / "historical" / "AWARDS_PAST.json")
                      .read_text(encoding="utf-8"))
    rows = blob["alltime"]["draft"]
    assert rows and all(r["season"] >= KEEPER_ERA_START for r in rows)
    assert any(s < KEEPER_ERA_START for s in blob["seasons"])       # earlier seasons still have their awards
    src = (Path(__file__).parent.parent / "modules" / "awards_past.py").read_text(encoding="utf-8")
    assert "if s < KEEPER_ERA_START:" in src
