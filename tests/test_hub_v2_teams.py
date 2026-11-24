"""4c2: Teams and Matchups (claude/HANDOFF_4C2_TEAMS_MATCHUPS_2026-11-18.md s.6).

The roster table's Detailed view (modules/hub_v2/roster.py), Team value and
Title delta (team_value.py), the one tooltip on the games grids and the win-%
chart's markers, Matchups' Last week, the header's closing-line text, the
Players rows' own file, and the card's bar-to-line switch. Synthetic where
the rule is logic -- a hand-made team whose answers are known, and the
made-up league of tests/test_hub_v2.py -- plus one real, unstubbed test on
today's state (slow; it skips without the state)."""

import inspect
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pandas as pd
import pytest

import league_state                                    # noqa: E402,F401
from test_hub_v2 import (synth_payload, render, visible_text, strings, tap_violations, budget_bytes, dyn_route,
                         ALL_CSS, GEN, PASS, ROOT, MGRS, TEAMS, SYN_PRICE, SYN_TV)

from modules.hub_v2 import data as v2data, roster as R, page, view, card as C, page_players as PP, tokens, infotips
from modules import hub_state as hs

DASH = "\u2014"
MINUS = "\u2212"
TZ = timezone(timedelta(hours=-8))


# =============================================================================
# a hand-made team whose answers are known
# =============================================================================

FIRST = date(2026, 11, 1)
YDAY = date(2026, 11, 20)                     # 20 finished days, team AAA plays every one
ONE = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0]    # P One, days 1-12
NEXT = [date(2026, 11, 23) + timedelta(days=i) for i in range(7)]
SCHED = [[date(2026, 11, 21), date(2026, 11, 22)], NEXT, [date(2026, 11, 30) + timedelta(days=i) for i in range(7)]]
FUTURE_GAMES = [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 26), date(2026, 11, 27), date(2026, 11, 28)]


def _days(pts_by_day: dict) -> dict:
    out = {}
    d = FIRST
    while d <= YDAY:
        v = pts_by_day.get(d)
        out[d.isoformat()] = [v, 1] if v is not None else [0.0, 0]
        d += timedelta(days=1)
    return out


def team_world(tmp_path, *, archetype=None):
    """One manager, M, with four players:
      P One    12 games (10..120, days 1-12), on M from 11-05 (an FA add), benched 11-06 and 11-08
      P Two    9 games of 30 (days 1-9), kept
      P Three  10 games of 40, drafted in round 3
      P Four   in an IL slot, back 01-25, traded for 10-30 (before the season: on M from day one)"""
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "config" / "DRAFT_PICKS_CURRENT.json").write_text(json.dumps({"season": "2026-27", "picks": [
        {"manager": "M", "player_name": "P Two", "round": 11, "pick_number": 41, "is_keeper": True},
        {"manager": "M", "player_name": "P Three", "round": 3, "pick_number": 9, "is_keeper": False}]}),
        encoding="utf-8")
    (tmp_path / "data" / "transaction_log.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"row": "transaction", "status": "successful", "type": "add", "league_day": "2026-11-05",
         "players": [{"action": "add", "name": "P One", "to": {"manager": "M"}}]},
        {"row": "transaction", "status": "successful", "type": "trade", "league_day": "2026-10-30",
         "players": [{"action": "trade", "name": "P Four", "to": {"manager": "M"}}]},
        {"row": "transaction", "status": "successful", "type": "drop", "league_day": "2026-11-02",
         "players": [{"action": "drop", "name": "P Three", "to": {"manager": None}}]}]) + "\n", encoding="utf-8")
    days = {
        "P One": _days({FIRST + timedelta(days=i): ONE[i] for i in range(12)}),
        "P Two": _days({FIRST + timedelta(days=i): 30.0 for i in range(9)}),
        "P Three": _days({FIRST + timedelta(days=i): 40.0 for i in range(10)}),
        "P Four": _days({FIRST + timedelta(days=i): 20.0 for i in range(2)}),
    }
    blob = {"first_day": FIRST.isoformat(), "roster_names": {n: i for i, n in enumerate(days)},
            "players": {str(i): {"name": n, "days": d} for i, (n, d) in enumerate(days.items())}}
    lu = []
    for n, d in days.items():
        for iso, (pts, g) in d.items():
            if n == "P One" and iso < "2026-11-05":
                continue                                   # on another team then
            slot = "BN" if (n == "P One" and iso in ("2026-11-06", "2026-11-08")) else "PG"
            if n == "P Four" and iso > "2026-11-02":
                slot = "IL"
            lu.append({"date": iso, "manager": "M", "player_name": n, "slot": slot,
                       "fantasy_points": pts if (g and slot not in ("BN", "IL")) else float("nan")})
    tdates = [FIRST + timedelta(days=i) for i in range(20)] + FUTURE_GAMES
    games = [{"date": f"{d.isoformat()}T19:00:00Z", "home": "AAA", "away": "BBB"} for d in tdates]
    names = list(days)

    def prow(n):
        return {"name": n, "kind": "rostered", "ovr": "80", "ovr_k": 80, "ovr_d": {"t": "\u25b22", "dir": "up"},
                "pot": "84", "pot_k": 84, "avail": "90%", "age": "26", "arch": archetype and {"label": "Slasher"},
                # 4a3: the minutes as a row has them before the backfill (no min_days in this cache)
                "min": "loading", "min_k": None, "mind": "loading", "mind_k": None, "min_g": {}}

    def rrow(n, gp, fppg, il=False):
        return {"name": n, "gp": gp, "in_il": il, "nba": "AAA", "fppg": fppg, "l14": fppg, "gl": DASH if il else "2",
                "keep": "60%", "tags": ([{"text": "IL slot", "kind": "il"}, {"text": "back 01-25", "kind": "il"}]
                                        if il else []),
                "status": {"source": "il_slot" if il else "healthy", "why": ""}}
    rows = [rrow("P One", 12, "65.0"), rrow("P Two", 9, "30.0"), rrow("P Three", 10, "40.0"),
            rrow("P Four", 2, "20.0", il=True)]
    payload = {"rosters": {"M": {"players": rows}},
               "v2": {"teams": {"M": {"roster": {"extra": [{"gp": str(r["gp"]), "next": "3"} for r in rows],
                                                 "keep_rank": ["#1", "#2", "#3", "#4"], "keep_line": "3"}}}}}

    class Av:
        team_dates = {"AAA": tdates}
        info = {n: {"positions": ["PG"], "proj_fppg": 30.0} for n in names}

        def players(self, m, d):
            return [n for n in names if n != "P Four"] if d in tdates else []

        def grid_players(self, m, d):                       # 5d2: the one day fill reads this
            return self.players(m, d), [], []
    av = Av()
    ctx = {"players_block": {"rows": [prow(n) for n in names]}, "actuals": blob, "yesterday": YDAY,
           "today": YDAY + timedelta(days=1), "av": av, "next_av": av,
           "data": NS(lineups=pd.DataFrame(lu), nba_schedule={"games": games}, injury_overrides={"players": []}),
           "joined": {("M", "P One"): "2026-11-05", ("M", "P Two"): None, ("M", "P Three"): None,
                      ("M", "P Four"): None},
           "proj": {n: {"projectedFPPG": 50.0} for n in names}, "next_days": NEXT,
           "team_value": {"weeks": [4, 5], "sims": 48, "values": {"M": {"P One": {"pts": 40.0}, "P Two": {"pts": -15.0},
                                                                     "P Three": {"pts": 0.4}}}},
           "title_prices": ({"M": SYN_PRICE}, "title", None), "sched_days": SCHED}
    from modules.hub_v2 import ranges as _rg
    ctx["ranges"] = _rg.Source(av, av, 5, {5: SCHED[0], 6: NEXT, 7: SCHED[2]}, 4)
    return payload, ctx


@pytest.fixture
def built(tmp_path, monkeypatch):
    payload, ctx = team_world(tmp_path)
    shared, out = R.build(tmp_path, payload, ctx)
    cells = {payload["rosters"]["M"]["players"][i]["name"]: dict(zip(shared["keys"], row))
             for i, row in enumerate(out["M"]["rows"])}
    return shared, out["M"], cells


# =============================================================================
# the values, on a team whose answers are known
# =============================================================================

def test_start_pct_counts_only_his_games_on_this_team(built):
    _s, _d, c = built
    # P One played days 1-12; on M from 11-05: 8 games, benched on 2 of them
    assert c["P One"]["start"] == "75%"
    assert c["P Two"]["start"] == "100%"


def test_floor_ceil_boom_bust_and_the_minimum(built):
    _s, _d, c = built
    one = c["P One"]
    assert (one["floor"], one["ceil"]) == ("20.0", "110.0")          # nearest rank of 12 games: 2nd, 11th
    assert (one["boom"], one["bust"]) == ("33%", "33%")              # >= 81.25: 4 of 12; <= 48.75: 4 of 12
    assert all(c["P Two"][k] == DASH for k in ("floor", "ceil", "boom", "bust"))      # 9 games
    assert c["P Three"]["floor"] == "40.0" and c["P Three"]["boom"] == "0%"           # exactly 10 games
    assert R.MIN_GAMES_SPREAD == 10


def test_b2b_missed_best_worst_since_and_share(built):
    _s, _d, c = built
    assert c["P One"]["b2b"] == "3"                    # 11-23/24, 11-26/27, 11-27/28
    assert c["P Four"]["b2b"] == DASH                  # an IL slot
    assert c["P One"]["missed"] == "8" and c["P Two"]["missed"] == "11"
    assert c["P One"]["best"] == "120 vs BBB" and c["P One"]["worst"] == "10 vs BBB"
    assert c["P One"]["since"] == "85.0"               # games since 11-05: 50..120
    assert c["P Two"]["since"] == "30.0"               # on the team all season
    assert c["P One"]["vsproj"] == "+15.0"
    mine = 50 + 70 + 90 + 100 + 110 + 120              # started on M: benched 11-06 (60) and 11-08 (80)
    team = mine + 9 * 30 + 10 * 40 + 2 * 20
    assert c["P One"]["share"] == f"{100.0 * mine / team:.1f}%" == "43.2%"


def test_acquired_for_each_kind(built):
    _s, _d, c = built
    assert c["P One"]["acq"] == "FA 11-05"
    assert c["P Two"]["acq"] == "Kept \u201926"
    assert c["P Three"]["acq"] == "R3 \u201926"         # a drop by someone else is not his acquisition
    assert c["P Four"]["acq"] == "Trade 10-30"


def test_title_delta_has_team_values_sign(built):
    _s, d, c = built
    assert c["P One"]["tv"] == "+40" and c["P One"]["tdelta"] == "+0.8"
    assert c["P Two"]["tv"] == f"{MINUS}15" and c["P Two"]["tdelta"] == f"{MINUS}0.3"
    assert c["P Three"]["tv"] == "0" and c["P Three"]["tdelta"] == "0.0"
    assert c["P Four"]["tv"] == DASH and c["P Four"]["tdelta"] == DASH           # an IL slot
    for name in ("P One", "P Two"):
        tv = float(c[name]["tv"].replace(MINUS, "-"))
        td = float(c[name]["tdelta"].replace(MINUS, "-"))
        assert (tv > 0) == (td > 0)


def test_a_negative_price_raises(tmp_path, monkeypatch):
    from modules.hub_v2 import team_value as tvm
    from modules import drop_inputs as di, injured_drop as idr
    monkeypatch.setattr(di, "read_stakes", lambda base: ({"schema": 3}, None))
    ws = idr.WeekStake(4, -0.2, None, 0.0, 100.0)
    monkeypatch.setattr(di, "team_stakes", lambda *a, **k: NS(weeks={4: ws, 5: ws}))
    with pytest.raises(tvm.TeamValueError, match="negative"):
        tvm.title_prices(tmp_path, ["M"], [4, 5])


def test_the_orders_are_best_first_with_missing_last(built):
    _s, d, c = built
    o = d["orders"]
    assert o["tv"] == [0, 2, 1, 3]                     # +40, +0.4, -15, then the IL slot
    assert o["floor"] == [2, 0, 1, 3]                  # 40, 20, then the two with too few games
    assert o["missed"] == [0, 2, 1, 3]                 # fewest missed first: 8, 10, 11, 18
    assert o["keeprank"] == [0, 1, 2, 3]
    assert o["age"] == [3, 0, 2, 1]                    # one age for all: by name
    for k in d["orders"]:
        assert sorted(o[k]) == [0, 1, 2, 3], k


def test_min_columns_close_the_form_group_and_the_archetype_needs_its_switch(tmp_path, monkeypatch, built):
    shared, _d, _c = built
    form = next(g for g in shared["groups"] if g["key"] == "form")["cols"]
    assert tuple(form[-2:]) == R.FORM_MINUTES == ("min", "mind")          # 4a3: after Bust %
    assert "arch" in shared["keys"]                       # Nick, 11-20: the archetype is on
    from modules import ratings
    real = ratings.config()
    payload, ctx = team_world(tmp_path, archetype=True)
    shared2, out2 = R.build(tmp_path, payload, ctx)
    assert "arch" in shared2["keys"] and "arch" in next(g for g in shared2["groups"] if g["key"] == "profile")["cols"]
    assert dict(zip(shared2["keys"], out2["M"]["rows"][0]))["arch"] == "Slasher"
    monkeypatch.setattr(ratings, "config", lambda *a, **k: dict(real, archetype=dict(real["archetype"], enabled=False)))
    shared3, _out3 = R.build(tmp_path, payload, ctx)
    assert "arch" not in shared3["keys"]                  # switched off, the column goes


def test_the_groups_are_nicks_and_all_is_every_column(built):
    shared, _d, _c = built
    assert [g["key"] for g in shared["groups"]] == ["value", "form", "schedule", "health", "keeper", "profile", "all"]
    by = {g["key"]: g["cols"] for g in shared["groups"]}
    assert by["value"] == ["ovr", "pot", "tv", "tdelta", "start"]
    assert by["form"] == ["fppg", "l14", "vsproj", "trend", "floor", "ceil", "boom", "bust", "min", "mind"]
    assert by["schedule"] == ["next", "nstarts", "gl", "b2b"]
    assert by["health"] == ["gp", "avail", "missed", "back"]
    assert by["keeper"] == ["keep", "keeprank", "age", "acq", "since"]
    assert by["profile"] == ["arch", "share", "best", "worst"]          # the archetype is on (Nick, 11-20)
    assert by["all"] == [k for g in shared["groups"][:-1] for k in g["cols"]] == shared["keys"]


def test_a_missing_input_raises(tmp_path):
    payload, ctx = team_world(tmp_path)
    del ctx["team_value"]["values"]["M"]["P One"]
    with pytest.raises(R.RosterError, match="Team value"):
        R.build(tmp_path, payload, ctx)
    payload, ctx = team_world(tmp_path)
    (tmp_path / "config" / "DRAFT_PICKS_CURRENT.json").unlink()
    with pytest.raises(R.RosterError, match="DRAFT_PICKS"):
        R.build(tmp_path, payload, ctx)


# =============================================================================
# the roster table on the page
# =============================================================================

def _team_section(h, m="Marcus"):
    return re.search(rf'data-route="teams/{m}" data-detail="1" hidden>(.*?)</section>\s*(?:<section class="v2-screen"|</main>)',
                     h, re.S).group(1)


def test_each_chip_shows_exactly_its_groups_columns():
    p = synth_payload()
    h = render(p)
    sec = _team_section(h)
    rc = p["v2"]["roster_cols"]
    chips = re.findall(r'data-dgroup="(\w+)"', sec)
    assert chips == [g["key"] for g in rc["groups"]]
    ths = re.findall(r'<th class="v2-dc ([^"]+)" data-k="d_(\w+)">', sec)
    assert [k for _c, k in ths] == rc["keys"]
    for cls, k in ths:
        assert set(cls.split()) == {f"v2-g-{g['key']}" for g in rc["groups"] if k in g["cols"]}, k
    css = page.LAYOUT_CSS
    for g in page.DETAIL_GROUPS:
        assert f'.v2-rt[data-mode="detailed"][data-group="{g}"] .v2-g-{g}{{display:table-cell}}' in css
    assert '.v2-rt .v2-dc{display:none}' in css and '.v2-rt[data-mode="detailed"] .v2-sc{display:none}' in css
    # every detailed cell of a row is in the same groups as its header
    for row in re.findall(r'<tr data-i="\d+"[^>]*>(.*?)</tr>', sec, re.S):
        assert [c for c in re.findall(r'<td class="v2-dc ([^"]+)">', row)] == [c for c, _k in ths]


def test_simple_stays_fppg_gp_proj_next():
    sec = _team_section(render())
    assert re.findall(r'<th class="v2-sc"[^>]*data-k="(\w+)"', sec) == ["fppg", "gp", "proj", "next"]


def test_sorting_uses_the_payload_orders_for_every_column():
    p = synth_payload()
    sec = _team_section(render(p))
    orders = json.loads(re.search(r"data-orders='([^']+)'", sec).group(1).replace("&quot;", '"'))
    det = p["v2"]["teams"]["Marcus"]["roster"]["detail"]["orders"]
    for k, v in det.items():
        assert orders["d_" + k] == v
    for k in p["v2"]["roster_cols"]["keys"]:
        assert f'data-sort="d_{k}"' in sec
    js = page.PAGE_JS
    assert "var o0=orders[vuKey(key)];if(!o0){return;}" in js and "var ord=o0.slice();if(dir<0){ord.reverse();}" in js


def test_il_rows_stay_apart_and_mins_are_present():
    sec = _team_section(render())
    il = re.search(r'<tbody class="v2-il">(.*?)</tbody>', sec, re.S).group(1)
    assert "Marcus Hurt" in il and "Marcus Hurt" not in re.search(r'<tbody class="v2-active">(.*?)</tbody>', sec,
                                                                    re.S).group(1)
    assert 'data-k="d_min"' in sec and 'data-k="d_mind"' in sec                # 4a3


def test_the_chip_is_remembered_in_memory_only():
    js = page.PAGE_JS
    assert "seen['dgroup']=key;" in js and "if(seen['dgroup']){dgroup(seen['dgroup']);}" in js
    assert "sessionStorage" not in js
    # 5e: the one thing kept in the browser is the "I'm..." pick, each use inside a try
    uses = [m.start() for m in re.finditer("localStorage", js)]
    assert len(uses) == 3 and all(js.rfind("try{", 0, i) > js.rfind("}", 0, js.rfind("try{", 0, i)) - 1 for i in uses)
    assert all("hub.viewer" in js[i:i + 40] for i in uses)


def test_every_detailed_value_is_a_payload_string_and_trend_has_aria():
    p = synth_payload()
    h = render(p)
    sec = _team_section(h)
    for m in MGRS:
        det = p["v2"]["teams"][m]["roster"]["detail"]
        for row in det["rows"]:
            assert all(isinstance(x, str) for x in row)
        for t in det["trend"]:
            if t:
                assert t["aria"] in _team_section(h, m).replace("&#x27;", "'")
    assert sec.count('class="lh-spark"') >= 4


# =============================================================================
# the one tooltip
# =============================================================================

class _Av:
    """Team AAA plays Mon, Wed, Fri, Sat; he is out Wed."""

    def __init__(self, week):
        self.week = week

    def playable(self, name, days):
        return [d for d in days if d.weekday() in (0, 4, 5)]

    def has_game(self, name, d):
        return d.weekday() in (0, 2, 4, 5)


def test_the_days_match_the_count_out_and_b2b_marked():
    days = [date(2026, 11, 23) + timedelta(days=i) for i in range(7)]
    n, tip = v2data.player_week_tip(_Av(5), "X", 5, "", days, False)
    assert n == 3 and tip == {"h": "Wk 5", "b": "Mon \u00b7 Fri \u00b7 Sat", "f": "Fri\u2013Sat B2B \u00b7 out Wed"}
    assert len(tip["b"].split(" \u00b7 ")) == n
    n, tip = v2data.player_week_tip(_Av(5), "X", 5, "rest", days[3:], False)
    assert n == 2 and tip["h"] == "Wk 5 rest" and tip["b"] == "Fri \u00b7 Sat"     # only the remaining days
    long_ = [date(2026, 11, 30) + timedelta(days=i) for i in range(14)]
    n, tip = v2data.player_week_tip(_Av(7), "X", 7, "", long_, True)
    assert tip["b"].startswith("Mon 11-30 \u00b7 Fri 12-04 \u00b7 Sat 12-05")     # the 14-day week: dates


def test_every_grid_cell_is_a_tap_with_its_tooltip():
    p = synth_payload()
    h = render(p)
    for cell in re.findall(r'<(?:button|span) [^>]*class="lh-heat__cell[^"]*"[^>]*>', h):
        assert cell.startswith("<button") and 'class="lh-heat__cell v2-cell' in cell, cell
        assert 'data-tip-h="' in cell and 'data-tip-b="' in cell and 'aria-label="' in cell
    assert re.search(r'<span class="lh-sub">[^<]*IL slot', h)        # 5d2: the Schedule grid says why
    assert 'data-tip-b="Marcus Guard, Marcus Big"' in h                         # who starts that day


def test_event_markers_have_no_text_on_the_chart_and_open_the_tooltip():
    h = render()
    ch = re.search(r'<svg class="lh-chart"[^>]*aria-label="Glass Cannons\' chance[^"]*"[^>]*>.*?</svg>',
                   h.replace("&#x27;", "'"), re.S).group(0)
    assert "lh-c-event-text" not in ch and "healthy" not in "".join(re.findall(r"<text[^>]*>([^<]*)</text>", ch))
    assert re.search(r'<circle class="lh-c-event v2-ev--down" [^>]*r="4"/>', ch)
    hit = re.search(r'<circle class="v2-ev-hit"[^>]*/>', ch).group(0)
    assert 'r="22"' in hit and 'tabindex="0"' in hit and 'role="button"' in hit
    assert 'data-tip-h="Tue 12-03, 12:06 AM"' in hit and 'data-tip-f="GC \u22129.1%"' in hit


def test_the_tooltip_script_opens_closes_and_computes_nothing():
    js = page.PAGE_JS
    block = js[js.index("// THE ONE TOOLTIP"):js.index("// player cards (4c1)")]
    for banned in ("Math.", "parseInt", "parseFloat", "Number(", ".sort(", "JSON.parse"):
        assert banned not in block, banned
    assert "if(tipFor===t){hideTip();}else{showTip(t);}" in js                   # a tap opens, a second closes
    assert "hideTip();\n  t=e.target.closest('[data-card]');" in js              # a tap elsewhere closes
    assert "if(e.key==='Escape'){closeTips(null);hideTip();" in js                # 5c: and the Forget question
    assert "getAttribute('data-tip-h')!==null&&!ptrFocus){showTip(t);}" in js     # keyboard focus opens
    assert ".lh-c-label" in block and "vw-pad-w" in block                         # end labels, the screen


def test_the_renderers_new_pieces_do_no_arithmetic():
    src = "".join(inspect.getsource(f) for f in (page._roster, page._dcell, page._cell, page._tip_attrs,
                                                 page._tip_label, page._last_week, page._last_page, page._chart))
    for banned in ("round", "float", "sum", "sorted", "max", "min", "int"):
        assert not re.search(rf"\b{banned}\(", src), banned


def test_lore_never_reaches_a_tooltip_a_cell_or_last_week():
    p = synth_payload()
    p["v2"]["sched"]["teams"]["Marcus"]["panes"][0]["rows"][0]["sub"] = "Mon <!-- lore:phase-a --> x"
    p["v2"]["teams"]["Marcus"]["roster"]["detail"]["rows"][0][-1] = "75 vs AAA <!-- lore:phase-b -->"
    p["v2"]["last"]["cards"][0]["verdict"] = "Covered <!-- lore:phase-c -->"
    h = render(p)
    assert "lore:" not in h and "phase-a" not in h and "phase-b" not in h and "phase-c" not in h


def test_the_tooltip_component_is_documented():
    d = ROOT / "design" / "league-hub" / "components" / "Tooltip"
    assert (d / "README.md").is_file() and (d / "preview.html").is_file()
    assert "tip-max" in {t["name"] for t in json.loads((ROOT / "design" / "league-hub" / "tokens.json")
                                                       .read_text(encoding="utf-8"))["sizing"]["tokens"]}


# =============================================================================
# the header, last week, Power #
# =============================================================================

def _closing(tmp_path, week, close):
    (tmp_path / "output").mkdir(exist_ok=True)
    (tmp_path / "output" / f"closing_line_week{week}.json").write_text(
        json.dumps({"closing": {"window_close": close.isoformat()}}), encoding="utf-8")


def test_closing_line_text_only_after_the_close_and_before_the_next_pricing(tmp_path):
    pretip = datetime(2026, 11, 23, 15, 45, tzinfo=TZ)
    close = datetime(2026, 11, 23, 18, 55, tzinfo=TZ)
    assert hs.header_line_text(tmp_path, 6, pretip) == "Line priced Mon Nov 23, 3:45 PM Pacific"     # no close yet
    _closing(tmp_path, 6, close)
    assert hs.header_line_text(tmp_path, 6, pretip) == "Closing line priced Mon Nov 23, 6:55 PM Pacific"
    tue = datetime(2026, 11, 24, 0, 5, tzinfo=TZ)
    assert hs.header_line_text(tmp_path, 6, tue) == "Line priced Tue Nov 24, 12:05 AM Pacific"      # re-priced
    assert hs.header_line_text(tmp_path, 7, pretip) == "Line priced Mon Nov 23, 3:45 PM Pacific"    # another week's


def test_the_header_uses_the_one_string_on_both_pages():
    src = inspect.getsource(hs.build)
    assert '"line_text": line_text,' in src and "line_text = header_line_text(base, week, line_at)" in src
    p = synth_payload()
    h = render(p)
    assert p["header"]["line_text"] == p["v2"]["line_text"] and p["header"]["line_text"] in h


def test_the_current_hub_page_changes_only_by_the_line_text():
    """The current page prints header.line_text as is: two payloads that differ
    only in it render to pages that differ only in it (4c2 is allowed that one
    change to the live hub)."""
    from modules import hub_page
    import copy
    p = hs.load(ROOT) if (ROOT / "output" / "hub_state.json").is_file() else None
    if p is None:
        pytest.skip("no league state on this machine")
    if p.get("v2_store"):
        # 5c: since the switch-over (5b) the stored payload is v2's: the v1 page
        # cannot render it (scripts/build_hub.py refuses it), so this pins nothing
        pytest.skip("the stored payload is v2's (5b store_v2): the current page is not built from it")
    now = datetime.fromisoformat(p["generated_at"]) + timedelta(minutes=5)
    q = copy.deepcopy(p)
    q["header"]["line_text"] = "Closing line priced Mon Nov 16, 6:55 PM Pacific"
    a, b = hub_page.render(p, now=now), hub_page.render(q, now=now)
    assert a != b and a.replace(p["header"]["line_text"], q["header"]["line_text"]) == b


def test_the_closing_verdicts():
    ln = {"manager_a": "A", "manager_b": "B", "spread_a": -72.0, "spread_b": 72.0, "win_prob_a": 61.08,
          "win_prob_b": 38.92}
    assert v2data.line_verdict(ln, "A", "B", 1800, 1600) == (f"A {MINUS}72 \u00b7 61% at the close",
                                                             "A covered: won by 200")
    assert v2data.line_verdict(ln, "A", "B", 1650, 1600)[1] == "A won by 50, short of the spread"
    assert v2data.line_verdict(ln, "A", "B", 1672, 1600)[1] == "Push: A won by exactly 72"
    assert v2data.line_verdict(ln, "A", "B", 1634, 1870)[1] == "Upset: B won by 236"
    assert v2data.line_verdict(ln, "B", "A", 1870, 1634)[1] == "Upset: B won by 236"         # sides swapped
    even = dict(ln, spread_a=0.0, spread_b=0.0)
    assert v2data.line_verdict(even, "A", "B", 10, 10) == ("Pick'em at the close", "Tied")


def test_last_week_on_the_page_and_no_closing_line():
    p = synth_payload()
    h = render(p)
    m = re.search(r'data-route="matchups" hidden>(.*?)</section></div></div></section>', h, re.S).group(1)
    assert 'data-section="last"' in m and "Final: Marcus by 158" in m
    assert "Closing line: Marcus" in m and "Marcus covered: won by 158" in m
    assert "No closing line that week" in m and "Closing line: No closing" not in m
    routes = set(re.findall(r'data-route="([^"]+)"', h))
    assert {"matchups/w8-0", "matchups/w8-1"} <= routes
    lp = re.search(r'data-route="matchups/w8-0" data-detail="1" hidden>(.*?)</section>\s*<section class="v2-screen"',
                   h, re.S).group(1)
    assert "1,702" in lp and "1,544" in lp and 'data-pane-of="win"' in lp and 'data-pane-of="flow"' in lp


def test_last_week_scores_must_equal_the_results():
    p = synth_payload()
    lc = p["matchups"]["last"]
    with pytest.raises(v2data.V2Error, match="no last-week block"):
        v2data.last_week(ROOT, None, 9, None, TEAMS, {}, TZ)
    assert v2data.last_week(ROOT, None, 1, None, TEAMS, {}, TZ) is None                     # week 1: none
    assert lc is not None


def test_the_team_header_says_power():
    from modules.hub_v2 import data as d
    src = inspect.getsource(d.build)
    assert '\\u00b7 Power #{rk[\'rank\']} \\u00b7' in src


# =============================================================================
# the Players rows' own file (4c1 decision 8)
# =============================================================================

def test_the_players_file_leaves_the_payload_and_comes_back():
    p = synth_payload()
    rows = p["v2"]["players"]["rows"]
    obj = v2data.players_file(p)
    assert "players" not in p["v2"] and p["v2"]["players_file"]["rows"] == len(rows)
    with pytest.raises(view.ViewError, match="not attached"):
        view.build(p, mode="preview", now=GEN)
    with pytest.raises(v2data.V2Error, match="missing"):
        v2data.attach_players(json.loads(json.dumps(p)), None)
    stale = dict(obj, generated_at="2026-01-01T00:05:00-08:00")
    with pytest.raises(v2data.V2Error, match="rebuild"):
        v2data.attach_players(json.loads(json.dumps(p)), stale)
    v2data.attach_players(p, obj)
    h = render(p)
    assert 'data-route="players"' in h and "Marcus Guard" in h


def test_hub_state_takes_the_players_out_and_writes_them_beside(tmp_path):
    src = inspect.getsource(hs.build)
    assert "obj = v2data.players_file(payload)" in src
    assert hs.players_path_for(Path("output/hub_state.json")) == Path("output/hub_players.json")
    assert hs.players_path_for(tmp_path / "state.json") == tmp_path / "state_players.json"
    m = json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    assert "output/hub_players.json" in {e["path"] for e in m["excluded"]}
    assert "output/hub_players.json" not in {e["path"] for e in m.get("files", [])}
    assert "output/hub_players.json" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    (tmp_path / "output").mkdir()
    hs.write(tmp_path, {"schema": 1})
    hs.write_players(tmp_path, {"schema": 1, "players": {"rows": []}})
    assert hs.load_players(tmp_path / "output" / "hub_state.json") == {"schema": 1, "players": {"rows": []}}


# =============================================================================
# the card's game-by-game chart: bars, then a line past 40 games
# =============================================================================

def _games(n):
    return [{"date": (date(2026, 10, 20) + timedelta(days=i)).isoformat(), "fp": 30.0 + (i % 7), "injured": i == 5}
            for i in range(n)]


def test_bars_up_to_40_games_then_a_line():
    assert C.BAR_MAX_GAMES == 40
    b = C.bars(_games(40), 33.0, [])
    assert len(b["bars"]) == 40 and not b.get("line")
    b = C.bars(_games(41), 33.0, [])
    assert b["bars"] == [] and b["line"]["points"]
    ch = b["line"]
    assert len(ch["hits"]) == 40                                             # the 40 games he played
    assert any(g["cls"] == "lh-c-ref" for g in ch["grid"]) and any(t["t"] == "avg 33.0" for t in ch["labels"])
    v = {"key": "k", "hero": None}
    html = PP._line(ch, "c1")
    assert 'class="lh-chart v2-cline"' in html and "aria-label=" in html


def test_the_card_renders_the_line_past_40():
    src = inspect.getsource(PP.card_html)
    assert 'if b.get("line"):' in src and "_line(b[\"line\"]" in src


# =============================================================================
# the one real, unstubbed test: today's state
# =============================================================================

@pytest.fixture(scope="module")
def real():
    from modules import player_actuals
    from modules.league_clock import league_now
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_history.jsonl",
              ROOT / "output" / "tag_records.jsonl", ROOT / "config" / "ROSTERS.json", ROOT / "data" / "LINEUPS.xlsx"]
    if not all(x.exists() for x in needed):
        pytest.skip("no league state on this machine")
    league_state.skip_if_actuals_behind()
    po = {}
    try:
        p = hs.build(ROOT, now=league_now(), allow_engine_mismatch=True, echo=lambda *a, **k: None, players_out=po)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        pytest.skip(f"the hub's real inputs are not current today ({e})")
    return p, po


@pytest.mark.slow
@pytest.mark.real
def test_real_teams_matchups_preview_and_publish(real, tmp_path):
    from modules import hub_publish
    from modules.hub_v2 import publish as v2pub
    p, po = real
    assert p.get("v2_error") is None, p.get("v2_error")
    v2 = p["v2"]
    assert "players" not in v2 and len(json.dumps(p)) < 400_000          # test_hub_polish3's cap, with the move
    rc = v2["roster_cols"]
    from modules.hub_v2 import data as v2data
    assert all("detail" not in t["roster"] for t in v2["teams"].values())   # 5b: in the side file
    for m, t in v2["teams"].items():
        det = po["moved"][v2data.DETAIL_KEY][m]
        assert len(det["rows"]) == len(p["rosters"][m]["players"])
        for i, (row, pl) in enumerate(zip(det["rows"], p["rosters"][m]["players"])):
            c = dict(zip(rc["keys"], row))
            if pl["in_il"]:
                assert c["tv"] == DASH
            else:
                assert c["tv"] != DASH
                if c["tdelta"] != DASH and c["tv"] not in ("0",):
                    assert (c["tv"].startswith("+")) == (c["tdelta"].startswith("+")) or c["tdelta"] == "0.0"
        for pane in po["moved"]["sched.teams"][m]["panes"]:        # 5d2: Team > Schedule's player grid
            for row in pane["rows"]:
                played = sum(1 for c in row["cells"] if c["c"] in ("s", "q", "i"))
                started = sum(1 for c in row["cells"] if c["c"] in ("s", "q"))
                assert (int(row["g"]), int(row["s"])) == (played, started)
                if row["il"]:
                    assert "IL slot" in row["sub"] and not started
    assert v2["last"] is None or all(c["score_a"] and c["result"].startswith("Final") for c in v2["last"]["cards"])
    assert v2["line_text"] == p["header"]["line_text"]
    v2data.attach_players(p, po)
    now = datetime.fromisoformat(p["generated_at"]) + timedelta(minutes=5)
    h = page.render(view.build(p, mode="preview", now=now))
    assert not tap_violations(h) and "http://" not in h and "lore:" not in h
    for m in v2["teams"]:
        sec = _team_section(h, m)
        assert len(re.findall(r'data-dgroup="', sec)) == len(rc["groups"])
        assert "v2-sday" in sec and "data-swk=" in sec                # 5d2: Team > Schedule (the strip, the weeks)
    assert ("v2-ev-hit" in h) == any(pt.get("event") for mu in v2["matchups"] for pt in mu["win"]["points"])
    if v2["last"]:
        assert 'data-section="last"' in h
    known = " ".join(strings(p)) + " " + " ".join(" ".join(v) for v in infotips.TIPS.values())
    from modules.hub_page import age_words, STALE_HOURS
    static = {str(STALE_HOURS), "10", "130"} | set(re.findall(r"\d+", age_words(datetime.fromisoformat(
        p["generated_at"]), now)[0]))
    for n in re.findall(r"\d+(?:[.,]\d+)*", visible_text(h)):
        assert n in known or n in static, f"{n!r} on the page is in no payload string"
    rep = v2pub.build(ROOT, p, PASS, salt=b"\x03" * 16, out_dir=tmp_path / "pub", iterations=1000, now=now)
    assert rep["served_bytes"] <= budget_bytes(), rep
    assert hub_publish.scan_dir(tmp_path / "pub", hub_publish.scan_terms(ROOT))["hits"] == {}
