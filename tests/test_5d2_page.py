"""5d2 s.1-s.4: Team > Schedule, Matchups > Next week, the Players tab's
Detailed groups and Market's ranges. Synthetic (tests/hub_5d2_world.py through
the real Availability and the real engine functions), plus one real,
unstubbed test that skips without today's state."""

import json
import re
from datetime import date, timedelta

import pytest

import hub_5d2_world as W
import hub_v2_sched_fixture as SF
from modules.hub_v2 import schedule as S, ranges as R, page_sched as PS, infotips, pcols, text as T

DASH = "\u2014"


@pytest.fixture(scope="module")
def built():
    ctx = SF.sched_ctx()
    sched, nw = S.build(ctx)
    return ctx, sched, nw


# ----------------------------------------------------------------- s.1 Schedule
def test_three_weeks_open_on_the_week_a_pickup_can_change(built):
    ctx, sched, _nw = built
    ws = sched["weeks"]
    assert [w["w"] for w in ws] == [7, 8, 9]
    assert ws[0]["label"].endswith("rest") and "days left" in ws[0]["sub"]          # "Wk 5 rest" fixed
    assert ws[0]["chip"] == "Wk 7 rest"
    assert sched["open"] == 1                                                       # after the close: next week
    ctx2 = dict(ctx, fcols={"mode": "this", "join": ctx["wk_dates"][7][0]})
    assert S.build(ctx2)[0]["open"] == 0                                             # before it: this week


def test_week_7_says_14_days_and_compares_with_the_league():
    w = W.world(today=date(2026, 11, 24))
    ctx = dict(SF.sched_ctx(), ranges=w["src"], week=6, today=date(2026, 11, 24), wk_dates=w["wk_dates"],
               fcols={"mode": "ahead", "join": w["wk_dates"][7][0]}, fa_av=w["fa_av"],
               range_list=R.ranges(w["wk_dates"][7][0], 7, w["wk_dates"]))
    ctx["stakes"] = None
    sched, _ = S.build(ctx)
    w7 = sched["weeks"][1]
    assert w7["w"] == 7 and "14 days" in w7["label"] and "14 days" in w7["chip"] and len(w7["days"]) == 14
    for m in W.MGRS:
        row = sched["teams"][m]["ov"][1]
        t = w["src"].team(m, w["wk_dates"][7])
        assert row["starts"] == R.rng(*t.starts) and row["games"] == R.rng(*t.games)
        avg_lo = sum(w["src"].team(x, w["wk_dates"][7]).starts[0] for x in W.MGRS) / 4
        assert row["avg"].startswith(f"{avg_lo:.1f}")
    assert "14-day week" in sched["note"]


def test_the_numbers_are_the_range_sources(built):
    ctx, sched, _nw = built
    src = ctx["ranges"]
    for i, wk in enumerate(sched["weeks"]):
        days = [date.fromisoformat(d["iso"]) for d in wk["days"]]
        for m in W.MGRS:
            t = src.team(m, days).texts()
            tiles = {x["k"]: x["v"] for x in sched["teams"][m]["panes"][i]["tiles"]}
            assert (tiles["starts"], tiles["games"], tiles["idle"], tiles["empty"], tiles["pts"]) == \
                (t["starts"], t["games"], t["idle"], t["empty"], t["pts"])
            assert tiles["days"] == f"{t['light']} / {t['over']}"
            strip = sched["teams"][m]["panes"][i]["strip"]
            for x, d in zip(strip, days):
                y = src.day(m, d)
                assert (x["s"], x["s"] + x["q"], x["e"], x["i"]) == (y.starts[0], y.starts[1], y.empty[0], y.idle[1])


def test_il_players_never_start_and_their_rows_say_why(built):
    ctx, sched, _nw = built
    seen = 0
    for m in W.MGRS:
        for p in sched["teams"][m]["panes"]:
            for r in p["rows"]:
                if r["il"]:
                    seen += 1
                    assert all(c["c"] in ("il", "", "x") for c in r["cells"]) and r["s"] == "0"
                    assert r["dim"]
                played = sum(1 for c in r["cells"] if c["c"] in ("s", "q", "i"))
                assert int(r["g"]) == played and int(r["s"]) == sum(1 for c in r["cells"] if c["c"] in ("s", "q"))
    assert seen


def test_back_to_backs_and_light_and_overflow_marks(built):
    ctx, sched, _nw = built
    assert any(c.get("b2b") for t in sched["teams"].values() for q in t["panes"] for r in q["rows"]
               for c in r["cells"])
    p = sched["teams"]["Marcus"]["panes"][1]
    kinds = {h["kind"] for h in p["heads"]}
    assert kinds <= {"off", "light", "over", "normal"}
    for h, x in zip(p["heads"], p["strip"]):
        assert h["kind"] == x["kind"]
    assert all(not h["nba"] for h in p["heads"] if not h["today"])        # the report's mark: today only


def test_estimated_days_are_marked():
    w = W.world(today=date(2026, 11, 24))
    src = R.Source(w["av"], w["next_av"], w["week"], w["wk_dates"], 4,
                   {W.NBA[k]: {date(2026, 12, 4), date(2026, 12, 11)} for k in range(30)})
    ctx = dict(SF.sched_ctx(), ranges=src, week=6, today=date(2026, 11, 24), wk_dates=w["wk_dates"],
               fcols={"mode": "ahead", "join": w["wk_dates"][7][0]}, fa_av=w["fa_av"], stakes=None,
               range_list=R.ranges(w["wk_dates"][7][0], 7, w["wk_dates"]))
    sched, _ = S.build(ctx)
    p = sched["teams"]["Marcus"]["panes"][1]
    est = [x for x in p["strip"] if x["est"]]
    assert est and {x["iso"] for x in est} <= {"2026-12-04", "2026-12-11"}
    assert any(c.get("est") for r in p["rows"] for c in r["cells"])


def test_pickups_only_for_the_join_week_count_games_on_empty_slot_days(built):
    ctx, sched, _nw = built
    src = ctx["ranges"]
    for m in W.MGRS:
        pk = sched["teams"][m]["pickups"]
        assert pk["w"] == 8 and "rule 7" in pk["lead"]
        days = ctx["wk_dates"][8]
        assert pk["total"] == R.rng(*src.team(m, days).empty)
        assert len(pk["chips"]) == int(pk["ndays"]) == len(src.empty_days(m, days))
        for f in pk["fas"]:
            assert f["n"] == str(src.games_on_empty(m, f["name"], ctx["fa_av"], days))
            assert "on days you have an empty slot" in f["text"] and "starts" not in f["text"]
        assert pk["adds"].startswith("2 of 3 adds left") and pk["window"]
        assert pk["href"] == f"#/market?r=next&fit={m}"


def test_the_playoff_and_cup_weeks(built):
    ctx, sched, _nw = built
    po = sched["teams"]["Marcus"]["playoffs"]
    assert [c["key"] for c in po["cols"]] == ["semis", "finals", "cup"]
    rl = {r.key: r for r in ctx["range_list"]}
    src = ctx["ranges"]
    for r in po["rows"]:
        assert r["cells"] == [str(src.player_games(r["name"], rl[k].days)) for k in ("semis", "finals", "cup")]


def test_the_words_light_and_overflow_and_no_short_day(built):
    _ctx, sched, nw = built
    blob = json.dumps(sched) + json.dumps(nw)
    assert "short day" not in blob.lower() and "light day" in blob.lower() and "overflow day" in blob.lower()
    assert "Light day: 4 or fewer" in sched["note"]


def test_the_pane_renders_with_a_definition_on_every_header(built):
    _ctx, sched, _nw = built
    t = {"cls": "lh-t-blue", "slot": "blue"}
    h = PS.schedule_pane({"weeks": sched["weeks"], "open": sched["open"], "note": sched["note"],
                          "team": sched["teams"]["Marcus"]}, t, lambda n, c: f"<span>{n}</span>")
    for th in re.findall(r"<th[^>]*>(.*?)</th>", h, re.S):
        assert "data-colh=" in th
    assert re.search(r'data-swk="8" aria-pressed="true"', h) and re.search(r'data-swk="7" aria-pressed="false"', h)
    assert "Where pickups would help" in h and "starts for you" not in h
    for k in ("week", "starts", "avg", "rank", "opp"):
        infotips.column("sched", k)


# ----------------------------------------------------------------- s.2 Next week
def test_next_week_is_the_same_startable_and_an_early_look(built):
    ctx, sched, nw = built
    assert nw["week"] == 8 and nw["unknown"] is None and len(nw["cards"]) == 2
    assert nw["early"] == "Early look \u2014 the line is set at Monday's close."
    pane = sched["weeks"].index(next(w for w in sched["weeks"] if w["w"] == 8))
    for c in nw["cards"]:
        for s in (c["a"], c["b"]):
            assert s["starts"] == sched["teams"][s["m"]]["ov"][pane]["starts"]        # one number
        row = ctx["stakes"]["teams"][c["a"]["m"]]["regular_season"]["8"]
        assert c["look"]["win_a"] == f"{100.0 * row['n_win'] / 50000:.0f}%" and "title-odds simulation" in c["look"]["src"]
    h = PS.next_week(nw, {m: {"cls": "lh-t-blue", "href": f"#/teams/{m}"} for m in W.MGRS}, lambda t: "")
    assert "Early look" in h and 'href="#/matchups/next/0"' in h


def test_a_playoff_week_says_its_opponent_is_not_set():
    w = W.world(today=date(2027, 2, 2))
    ctx = dict(SF.sched_ctx(today=date(2027, 2, 2)), stakes=None, title_latest={"finish_distribution": {
        m: {"1": 40.0, "2": 30.0, "3": 20.0, "4": 10.0} for m in W.MGRS}})
    import modules.advice_live as al
    orig = al.bracket_opponents
    al.bracket_opponents = lambda data, week: {}
    try:
        sched, nw = S.build(ctx)
    finally:
        al.bracket_opponents = orig
    assert nw["week"] == 16 and nw["cards"] == [] and nw["unknown"]["text"] == "Opponent set after week 15."
    assert nw["unknown"]["poss"]["cols"] == ["#1", "#2", "#3", "#4"]
    assert any(r["opp"]["text"] == "Opponent set after week 15" for r in sched["teams"]["Marcus"]["ov"])


def test_after_the_last_week_next_week_is_hidden():
    ctx = SF.sched_ctx(today=date(2027, 4, 6))
    ctx["fcols"] = {"mode": "ahead", "join": None}
    import modules.advice_live as al
    orig = al.bracket_opponents
    al.bracket_opponents = lambda data, week: {}
    try:
        sched, nw = S.build(ctx)
    finally:
        al.bracket_opponents = orig
    assert nw is None and all(t["pickups"] is None for t in sched["teams"].values())


# ----------------------------------------------------------------- s.3 Players groups
def test_every_players_column_has_a_definition_and_the_viewer_columns_are_hidden():
    sh = pcols.shared(True)
    for g in sh["groups"]:
        for k in g["cols"]:
            infotips.column("players", k)
    assert [g["key"] for g in sh["groups"]] == ["value", "season", "form", "box", "schedule", "health", "market",
                                                "career", "all"]
    assert "Value to you" in sh["hidden"][0]["what"] and "passphrase" in sh["hidden"][0]["why"]
    assert all(k in sh["why"] for k in ("keep", "startpct", "par"))


def test_the_synthetic_groups_render_and_a_free_agent_never_gets_a_made_up_zero():
    import test_hub_v2 as TH
    p = TH.synth_payload()
    g = p["v2"]["players"]["groups"]
    rows = p["v2"]["players"]["rows"]
    for i, z in enumerate(rows):
        if z["kind"] == "fa":
            assert g["cells"]["keep"][i] == DASH and g["cells"]["startpct"][i] == DASH
    h = TH.render(p)
    for key in ("value", "season", "form", "box", "schedule", "health", "market", "career", "all"):
        assert f'data-pgroup="{key}"' in h and f'data-pgrp="{key}"' in h
    assert 'data-boxv="tot"' in h


def test_one_source_rostered_cells_are_the_roster_tables():
    import test_hub_v2 as TH
    p = TH.synth_payload()
    g = p["v2"]["players"]["groups"]
    rows = p["v2"]["players"]["rows"]
    rc = p["v2"]["roster_cols"]
    shared = {"startpct": "start", "vsproj": "vsproj", "floor": "floor", "ceil": "ceil", "boom": "boom",
              "bust": "bust", "b2b": "b2b", "missed": "missed", "back": "back", "acq": "acq", "best": "best"}
    n = 0
    for m, t in p["v2"]["teams"].items():
        det = t["roster"]["detail"]
        for pl, vals in zip(p["rosters"][m]["players"], det["rows"]):
            i = next(k for k, z in enumerate(rows) if z["name"] == pl["name"])
            d = dict(zip(rc["keys"], vals))
            for a, b in shared.items():
                assert g["cells"][a][i] == d[b], (pl["name"], a)
                n += 1
    assert n


def test_published_groups_and_ranges_are_lazy_parts(tmp_path):
    import test_hub_v2 as TH
    from modules.hub_v2 import publish as v2pub
    p = TH.synth_payload()
    e = TH._archive(tmp_path)
    p["v2"]["issue"]["file"] = e["enc"]
    rep = v2pub.build(tmp_path, p, TH.PASS, salt=b"\x02" * 16, out_dir=tmp_path / "_to_delete" / "x" / "publish",
                      iterations=1000, terms=TH.TERMS, now=TH.GEN, strict_issues=False)
    assert set(rep["players_parts"]) == {"value", "season", "form", "box", "schedule", "health", "market", "career",
                                         "all"}
    assert rep["market_range_parts"] and "next3" not in rep["market_range_parts"]     # the default stays inline


# ----------------------------------------------------------------- s.4 Market ranges
def test_market_ranges_count_the_range_days_and_carry_the_sorts():
    import test_hub_v2 as TH
    p = TH.synth_payload()
    rg = p["v2"]["market"]["ranges"]
    assert rg["default"] == "next3" and [x["key"] for x in rg["list"]][:3] == ["next", "next2", "next3"]
    t = rg["avail"]["next3"]
    a = p["v2"]["market"]["available"]
    for r, r0 in zip(t["rows"], a["rows"]):
        assert [c["n"] for c in r["games"]] == [c["n"] for c in r0["games"]]          # today's columns
        assert r["cells"]["total"] == str(sum(int(c["n"]) for c in r["games"]))
    assert {x["k"] for x in rg["sorts"]} >= {"pts", "total", "ovr", "pot", "dur", "l7", "l30", "mind", "avail", "age"}
    for x in rg["sorts"]:
        infotips.column("market", x["k"])
    h = TH.render(p)
    assert 'data-mkr' in h and "history.replaceState(null,'','#/market'+q)" in __import__(
        "modules.hub_v2.page", fromlist=["script"]).script()


# ----------------------------------------------------------------- real (skips without state)
@pytest.mark.slow
def test_real_the_same_range_gives_the_same_numbers_everywhere():
    import league_state
    from pathlib import Path
    from modules import hub_state as HS
    root = Path(__file__).resolve().parents[1]
    league_state.skip_if_actuals_behind(root=root)       # H51: the shared guard
    cap = {}
    orig = HS.next_week_availability

    def wrap(*a, **k):
        r = orig(*a, **k)
        cap["next_av"] = r[0]
        return r
    HS.next_week_availability = wrap
    try:
        po = {}
        p = HS.build(root, allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po)
    finally:
        HS.next_week_availability = orig
    assert p.get("v2_error") is None, p.get("v2_error")
    v2 = p["v2"]
    sched_t = po["moved"]["sched.teams"]
    sched = v2["sched"]
    # Next week's startable is Team > Schedule's for that week
    nw = v2["next_week"]
    if nw and nw["cards"]:
        i = [w["w"] for w in sched["weeks"]].index(nw["week"])
        for c in nw["cards"]:
            for s in (c["a"], c["b"]):
                assert s["starts"] == sched_t[s["m"]]["ov"][i]["starts"]
    # Market's range games are the Players' Schedule columns for the same free agent
    rows = po["players"]["rows"]
    g = po["players"]["groups"]
    rg = po["moved"]["market.ranges"]                     # SIDE_KEYS: the ranges ride in the side file
    names = {z["name"]: i for i, z in enumerate(rows)}
    for key, col in (("next3", "nx3"), ("semis", "semis"), ("finals", "finals"), ("cup", "cup")):
        if key not in rg["avail"]:
            continue
        for r in rg["avail"][key]["rows"]:
            assert r["cells"]["total"] == g["cells"][col][names[r["name"]]], (key, r["name"])
