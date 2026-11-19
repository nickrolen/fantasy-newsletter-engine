"""4b: the new hub's shell (modules/hub_v2; claude/HANDOFF_4B_HUB_SHELL_2026-11-14.md
s.6-7). Synthetic where the rule is logic -- a made-up league (the design
system's placeholder teams) -- and one real, unstubbed test that builds the
v2 preview from today's inputs (state-dependent like tests/test_hub.py's
`real`: it skips, with the reason, when they are not current)."""

import html as _html
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import league_state                                    # noqa: E402

from modules.hub_v2 import data as v2data, view, page, tokens, publish as v2pub, infotips

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=-8))
GEN = datetime(2026, 12, 2, 0, 5, tzinfo=TZ)
PASS = "fake test passphrase only, not real"
MGRS = ["Marcus", "Tyler", "Dana", "Jordan"]
TEAMS = {"Marcus": "Glass Cannons", "Tyler": "Zone Defense", "Dana": "Pick & Roll Call", "Jordan": "Fast Break Bros"}
SLOTS = {"Marcus": "blue", "Tyler": "teal", "Dana": "orange", "Jordan": "plum"}
DASH = "\u2014"


# =============================================================================
# a synthetic payload: every number a string, the v2 block as data.build makes it
# =============================================================================

def _players(m):
    names = [f"{m} Guard", f"{m} Wing", f"{m} Big", f"{m} Bench", f"{m} Hurt"]
    out = []
    for j, n in enumerate(names):
        hurt = j == 4
        q = j == 1
        tags = ([{"text": "IL slot", "kind": "il"}, {"text": "back 12-14", "kind": "il"}] if hurt else
                [{"text": "Q", "kind": "q"}] if q else [{"text": "since 11-09", "kind": "new"}] if j == 3 else [])
        out.append({"name": n, "pos": "PG,SG", "nba": "AAA", "fppg": f"{45 - j * 5}.{j}", "gp": 10 + j,
                    "proj": f"{44 - j * 4}.{j}", "l14": f"{43 - j * 3}.{j}", "gl": DASH if hurt else str(3 - j % 2),
                    "keep": f"{90 - j * 17}%", "keep_strong": j < 2, "in_il": hurt, "tags": tags,
                    "status": ({"source": "il_slot", "why": "IL slot"} if hurt else
                               {"source": "tag", "why": "Q tag, expected to miss ~0.6 of 3 games"} if q else
                               {"source": "healthy", "why": ""}),
                    "card": n.lower().replace(" ", "-")})
    return out


def _win():
    pts = []
    for i, (a, cause, ev) in enumerate([(55.0, "nightly", ""), (57.2, "Monday pre-tip", ""),
                                        (48.1, "tag update: Marcus Wing healthy\u2192Q", "Marcus Wing healthy\u2192Q"),
                                        (61.4, "nightly", ""), (64.0, "nightly", "")]):
        pts.append({"x": 0.05 + i * 0.12, "a": a, "b": 100 - a, "ta": f"{a:.1f}%", "tb": f"{100 - a:.1f}%",
                    "when": f"Tue 12-0{i + 1}, 12:06 AM", "cause": cause, "event": ev})
    return {"points": pts, "ticks": [{"x": (i + 0.5) / 7, "t": d} for i, d in
                                     enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])],
            "yticks": [{"v": 0.0, "t": "0%"}, {"v": 50.0, "t": "50%"}, {"v": 100.0, "t": "100%"}],
            "aria": "Glass Cannons' chance to beat Zone Defense through the week: 64.0% now.", "empty": ""}


def _flow(a, b):
    return {"n_days": 7, "nb": 3, "ticks": [{"i": i, "t": d} for i, d in
                                            enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])],
            "ymax": 2000.0, "yticks": [{"v": 0.0, "t": "0"}, {"v": 1000.0, "t": "1,000"}, {"v": 2000.0, "t": "2,000"}],
            "series": {a: {"banked": [0, 250, 500, 760], "exp": [760, 1000, 1200, 1400, 1612], "end": 1612,
                           "label": "GC 1,612 exp.", "kind": "exp."},
                       b: {"banked": [0, 240, 470, 700], "exp": [700, 950, 1150, 1350, 1548], "end": 1548,
                           "label": "ZD 1,548 exp.", "kind": "exp."}},
            "tips": [f"Through Mon 11-3{i}: Glass Cannons 250, Zone Defense 240" for i in range(7)],
            "aria": "Points added up by day: Glass Cannons 760, Zone Defense 700 banked."}


def synth_payload() -> dict:
    """The 4b synthetic payload, plus (4c1) its Players block by the real engine path."""
    return add_synth_players(_synth_payload_4b())


def _synth_payload_4b() -> dict:
    rosters = {}
    for m in MGRS:
        ps = _players(m)
        n = len(ps)
        rosters[m] = {"manager": m, "team": TEAMS[m], "subtitle": f"{m} \u00b7 2-1 \u00b7 #1", "odds": "38.0%",
                      "odds_label": "Title odds", "adds": "1 of 3", "starts": "40 starts",
                      "size": "Active 4/15 \u00b7 IL 1/2", "players": ps,
                      "orders": {k: list(range(n)) for k in ("name", "fppg", "proj", "l14", "gl", "keep")},
                      "default_order": "proj", "pending": [],
                      "note": "FPPG and L14 are actual points per game. Keep is the chance he is one of your 5 keepers."}
    power_rows = [{"rank": str(i + 1), "manager": m, "team": TEAMS[m], "record": f"{3 - i % 3}-{i % 3}",
                   "odds": f"{40 - i * 8}.0%", "delta": ["\u25b2 6.0", "\u25bc 2.0", "\u2013 0.0", DASH][i],
                   "delta_dir": ["up", "down", "flat", "none"][i], "adds": "1 / 3", "adds_over": False,
                   "pf": f"7,{412 - i * 100}", "seed": "seed 1"} for i, m in enumerate(MGRS)]
    side = lambda m, now, proj, win: {"team": TEAMS[m], "manager": m, "now": now, "proj": proj, "win": win}
    cards = [{"a": side("Marcus", "760", "1,612", "64.0%"), "b": side("Tyler", "700", "1,548", "36.0%"),
              "bar_a": "64.0%", "spread": "Marcus \u221264", "total": "3,160", "moneyline": "\u2212178 / +178",
              "views": {"sum": "v-mu9-0-sum", "win": "v-mu9-0-win", "flow": "v-mu9-0-flow"}},
             {"a": side("Dana", "690", "1,500", "48.0%"), "b": side("Jordan", "720", "1,520", "52.0%"),
              "bar_a": "48.0%", "spread": "Jordan \u221220", "total": "3,020", "moneyline": "+110 / \u2212110",
              "views": {"sum": "v-mu9-1-sum", "win": "v-mu9-1-win", "flow": "v-mu9-1-flow"}}]
    views = []
    for i, c in enumerate(cards):
        views.append({"id": c["views"]["sum"], "back": "v-main", "back_label": "Hub",
                      "title": f"{c['a']['team']} vs {c['b']['team']}", "sub": "Week 9 \u00b7 Summary \u00b7 3 of 7 days banked",
                      "kind": "summary", "paras": [
                          {"head": "Tonight's update \u00b7 Wed 12-02",
                           "text": f"{c['a']['manager']} leads by 60, 760 to 700. The line gives 64.0%."},
                          {"head": "Monday's preview", "text": "A close one on paper."}]})
    teams = {}
    for i, m in enumerate(MGRS):
        ps = rosters[m]["players"]
        teams[m] = {
            "slot": SLOTS[m], "mono": v2data.monogram(TEAMS[m]), "team": TEAMS[m], "manager": m,
            "sub": f"{m} \u00b7 {power_rows[i]['record']} \u00b7 #{i + 1} \u00b7 {power_rows[i]['pf']} PF",
            "record": power_rows[i]["record"], "odds": power_rows[i]["odds"], "injured": "2", "adds_left": "2",
            "kpi": {"odds": {"label": "Title odds", "value": power_rows[i]["odds"], "ctx": "\u25b2 6.0 pts since the last run",
                             "dir": "up"},
                    "win": {"label": "This week", "value": "64.0%", "ctx": "to beat Zone Defense", "dir": ""},
                    "pf": {"label": "Points for", "value": power_rows[i]["pf"], "ctx": "#1 of 4 \u00b7 +276 vs league avg",
                           "dir": ""},
                    "adds": {"label": "Adds left", "value": "2", "ctx": "of 3 \u00b7 resets Mon 12-07", "dir": ""}},
            "spark": {"values": [22.0, 27.0, 32.0, 40.0 - i * 8], "texts": ["22.0%", "27.0%", "32.0%", power_rows[i]["odds"]],
                      "labels": ["Wk 6", "Wk 7", "Wk 8", "Wk 9"],
                      "aria": "Title odds at the end of each week: week 6 22.0%, week 7 27.0%, week 8 32.0%"},
            "roster": {"extra": [{"gp": str(p["gp"]), "next": DASH if p["in_il"] else "3"} for p in ps],
                       "orders": {"gp": list(range(len(ps))), "next": list(range(len(ps)))},
                       "keepers": [0, 1, 2], "keep_line": "3", "keep_rank": [f"#{j + 1}" for j in range(len(ps))],
                       "keep_w": [p["keep"] for p in ps]},
            "schedule": {"rows": [{"i": j, "cells": [{"n": "2", "b": 2}, {"n": "4", "b": 4}, {"n": "3", "b": 3}]}
                                  for j in range(len(ps))]},
            "moves": [{"w": "9", "j": 0}] if m == "Marcus" else []}
    mus = []
    for i, c in enumerate(cards):
        a, b = c["a"]["manager"], c["b"]["manager"]
        mus.append({"id": f"w9-{i}", "a": a, "b": b, "fav": "a" if i == 0 else "b",
                    "note": f"{a} leads by 60, 760 to 700.", "note_src": "night", "views": c["views"],
                    "win": _win(), "flow": _flow(a, b),
                    "starts": {"days": [{"dow": "Thu", "day": "3"}, {"dow": "Fri", "day": "4"}],
                               "rows": [{"m": a, "total": "17", "cells": [{"n": "8", "b": 4}, {"n": "9", "b": 4}]},
                                        {"m": b, "total": "11", "cells": [{"n": "5", "b": 2}, {"n": "6", "b": 3}]}],
                               "note": "Darker = more starts that day, of 10 lineup spots."},
                    "missing": [{"m": a, "i": 4, "chip": {"text": "IL \u00b7 back 12-14", "kind": "il"},
                                 "sub": f"{TEAMS[a]} \u00b7 IL slot"},
                                {"m": a, "i": 1, "chip": {"text": "Q", "kind": "q"},
                                 "sub": f"{TEAMS[a]} \u00b7 Q tag, expected to miss ~0.6 of 3 games"}],
                    "lines": {"rows": [{"label": "Spread", "value": c["spread"], "ctx": "Was Marcus \u221250 at the close",
                                        "close": "Marcus \u221250"},
                                       {"label": "Total", "value": c["total"], "ctx": "\u25b2 40 since the close",
                                        "close": "3,120"}],
                              "note": "The close is the official line."}})
    v2 = {"schema": 1, "teams": teams, "team_order": MGRS,
          "spark_scale": {"max": 50.0, "top": "50%", "note": "Title odds at the end of each week, and now; 0\u201350%."},
          "grid3": {"cols": [{"label": "Wk 9", "sub": "rest"}, {"label": "Wk 10", "sub": ""}, {"label": "Wk 11", "sub": ""}],
                    "rows": [{"m": m, "cells": [{"n": "15", "b": 4 - j}, {"n": "45", "b": 2}, {"n": "44", "b": 3}]}
                             for j, m in enumerate(MGRS)], "note": "Starts: games that fit a starting lineup."},
          "sched_cols": [{"label": "Wk 9", "sub": "rest"}, {"label": "Wk 10", "sub": ""}, {"label": "Wk 11", "sub": ""}],
          "sched_note": "Games he will play each week.", "matchups": mus,
          "issue": {"text": "Week 8 issue", "week": "8", "file": "week08-aaaaaaaaaaaa.enc"}}
    return {
        "schema": 1, "generated_at": GEN.isoformat(), "generated_epoch_ms": int(GEN.timestamp() * 1000),
        "generated_text": "Wed Dec 2, 12:05 AM Pacific", "league_day": "2026-12-02", "week": 9,
        "engine": {"commit": "abc1234", "dirty": False, "key": "abc1234"},
        "header": {"title": "League Hub", "week_label": "Week 9 \u00b7 Wed Dec 2",
                   "lock": {"locked": False, "text": "Lines are live until today's first tip, 4:00 PM Pacific."},
                   "line_text": "Line priced Wed Dec 2, 12:03 AM Pacific", "engine_mismatch": None, "engine_note": None},
        "matchups": {"clock": "3 of 7 game days played", "cards": cards,
                     "buttons": {"sum": "Summary", "win": "Win %", "flow": "Game flow"}, "last": None},
        "matchup_views": views,
        "power": {"kind": "title", "label": "Title odds", "rows": power_rows, "as_of": "x", "note": "n"},
        "rosters": rosters,
        "moves": {"weeks": [{"key": "9", "label": "Week 9 \u00b7 Nov 30\u2013Dec 6", "used": None, "used_note": "",
                             "items": [{"day": "Mon", "date": "11/30", "time": "6:11 AM", "who": "Marcus",
                                        "what": "added Free Guy", "note": "", "state": "Applied", "kind": "add",
                                        "parts": [{"kind": "add", "marker": "+", "text": "added Free Guy",
                                                   "segs": [{"t": "added "}, {"t": "Free Guy", "card": "free-guy"}]}]}]}],
                  "default": "9", "empty": "", "note": ""},
        "trade_block": {"title": "Trade block", "link": "Trade block", "foot": "Text Nick to change your block.",
                        "cards": [{"manager": m, "team": TEAMS[m], "mode": {"text": "Selling" if m == "Jordan" else "Neutral",
                                                                         "kind": "neu"}, "mode_since": "",
                                   "lists": ([{"label": "On the block", "key": "block",
                                               "rows": [{"name": "Jordan Bench", "pos": "C", "nba": "BBB",
                                                         "since": "since 11-30", "card": "jordan-bench"}]}]
                                             if m == "Jordan" else []),
                                   "empty": "" if m == "Jordan" else "Nothing listed."} for m in MGRS]},
        "newsletter": {"current": {"week": "8", "label": "Week 8", "file": "week08-aaaaaaaaaaaa.enc", "size": "2.4 MB"},
                       "archive": [], "empty": "", "note": ""},
        "sources": {"actuals_through": "2026-12-01"},
        "v2": v2, "v2_error": None,
    }


# =============================================================================
# 4c1: the synthetic league's Players block, made by the REAL engine path
# (modules/hub_v2/players.build) on made-up inputs: a cache of daily lines
# that gives each roster row its own FPPG and L14, a ratings result, and a
# stand-in for the free agents' availability
# =============================================================================

SYN_YESTERDAY = (GEN - timedelta(days=1)).date()
SYN_FIRST = SYN_YESTERDAY - timedelta(days=29)
FA_NAME, FA_KEY = "Free Guy", "free-guy"
GRADE_KEYS = ["scoring", "playmaking", "rebounding", "stocks", "efficiency", "durability", "consistency", "schedule"]
LETTERS = ["A+", "A", "B+", "B", "C+", "C", "D+", "D"]


def _syn_days(fppg: str, l14: str, gp: int) -> dict:
    """Every day from SYN_FIRST to SYN_YESTERDAY: 5 games in the last 14 days
    averaging l14, the rest before them, so the season averages fppg."""
    F, L = float(fppg), float(l14)
    days = [SYN_FIRST + timedelta(days=i) for i in range((SYN_YESTERDAY - SYN_FIRST).days + 1)]
    recent = [d for d in days if d > SYN_YESTERDAY - timedelta(days=14)]
    old = [d for d in days if d not in recent]
    out = {d.isoformat(): [0.0, 0] for d in days}
    for d in recent[:5]:
        out[d.isoformat()] = [round(L, 4), 1]
    per_old = (F * gp - 5 * L) / (gp - 5)
    for d in old[:gp - 5]:
        out[d.isoformat()] = [round(per_old, 4), 1]
    return out


class _FakeAv:
    team_dates = {"AAA": [SYN_FIRST + timedelta(days=i) for i in range(0, 40, 2)]}

    def playable(self, name, days):
        return list(days)[:3]


def synth_ratings(rosters: dict, previous: bool) -> dict:
    """A ratings result for the synthetic rostered players (ratings.rate's shape)."""
    players = {}
    k = 0
    for m in MGRS:
        for j, p in enumerate(rosters[m]["players"]):
            k += 1
            ovr = 95 - k * 2
            grades = {}
            for gi, g in enumerate(GRADE_KEYS):
                if j == 3 and g in GRADE_KEYS[:5]:
                    grades[g] = {"letter": None, "percentile": None, "value": None, "reason": "stats still loading"}
                else:
                    li = (k + gi) % 8
                    pct = [97.0, 88.0, 75.0, 55.0, 35.0, 20.0, 8.0, 2.0][li]
                    grades[g] = {"letter": LETTERS[li], "percentile": pct, "value": 9.0 if g == "schedule" else 1.0,
                                 "reason": None}
            players[p["name"]] = {
                "player": p["name"], "manager": m, "nba_team": "AAA", "ovr": ovr,
                "ovr_change": ({1: 3, 2: 2, 3: -1}.get(k, 0) if previous else None), "ovr_reason": None,
                "ovr_composite": 1000.0 - k, "pot": ovr + 1, "pot_reason": None, "pot_value": 80.0 - k,
                "components": {"level": 40.0 - k, "availability": 0.9 - k / 100.0, "games_remaining": 60 - k,
                               "game_sd": 10.0, "games": 10, "team_games": 12, "fppg": 40.0, "age": 25 + j},
                "grades": grades, "archetype": None, "archetype_reason": "off"}
    return {"as_of": SYN_YESTERDAY.isoformat(), "season": "2026-27", "players": players,
            "schedule_horizon": [GEN.date().isoformat(), (GEN.date() + timedelta(days=20)).isoformat()]}


def add_synth_players(p: dict, previous: bool = True) -> dict:
    """payload["v2"]["players"] and ["ratings"], by players.build on made-up inputs."""
    from modules.hub_v2 import players as v2players
    reg = {}
    for m in MGRS:
        for pl in p["rosters"][m]["players"]:
            reg[pl["card"]] = {"name": pl["name"], "kind": "rostered", "manager": m,
                               "status": [{"text": f"{TEAMS[m]} \u00b7 {m}", "kind": "own"}] + list(pl["tags"])}
    reg[FA_KEY] = {"name": FA_NAME, "kind": "free_agent", "manager": "",
                   "status": [{"text": "Free agent", "kind": "fa"}]}
    p["cards"] = {"players": dict(sorted(reg.items()))}
    blob = {"first_day": SYN_FIRST.isoformat(), "roster_names": {}, "players": {}}
    pid = 0
    for m in MGRS:
        for pl in p["rosters"][m]["players"]:
            pid += 1
            blob["roster_names"][pl["name"]] = pid
            blob["players"][str(pid)] = {"name": pl["name"], "days": _syn_days(pl["fppg"], pl["l14"], pl["gp"])}
    blob["players"]["999"] = {"name": FA_NAME, "days": _syn_days("31.5", "33.0", 9)}
    res = synth_ratings(p["rosters"], previous)
    prev = None
    if previous:
        prev = {"as_of": (SYN_YESTERDAY - timedelta(days=7)).isoformat(), "season": "2026-27",
                "ovr": {n: r["ovr"] - (r["ovr_change"] or 0) for n, r in res["players"].items()},
                "pot": {n: r["pot"] - 1 for n, r in res["players"].items()},
                "terms": {n: [r["components"]["level"] - (2.0 if i % 3 == 0 else 0.0),
                              r["components"]["availability"] - (0.1 if i % 3 == 1 else 0.0),
                              r["components"]["games_remaining"] + 3]
                          for i, (n, r) in enumerate(sorted(res["players"].items()))}}
    av = _FakeAv()
    ctx = {"ratings": {"result": res, "error": None, "previous_line": prev},
           "actuals": blob, "yesterday": SYN_YESTERDAY, "av": av,
           "info": {FA_NAME: {"nba_team": "AAA"}},
           "next_days": [GEN.date() + timedelta(days=5 + i) for i in range(7)],
           "proj": {FA_NAME: {"player_position(s)": "SF,PF", "player_nba_team": "AAA", "age": 24}},
           "keeper_watch": {"players": [{"manager": m, "player_name": pl["name"], "age": 25 + j}
                                        for m in MGRS for j, pl in enumerate(p["rosters"][m]["players"])]},
           "tag_row": {}, "no_id": [], "fa_av": lambda names: av}
    p["v2"]["players"], p["v2"]["ratings"] = v2players.build(ROOT, p, ctx)
    return p


def render(p=None, mode="preview", now=None):
    p = p or synth_payload()
    return page.render(view.build(p, mode=mode, now=now or GEN + timedelta(hours=2)))


def dyn_route(href: str) -> str:
    """The screen a hash opens (4c1: the player card and Compare are one screen
    each, filled by the script): the page script's own mapping."""
    parts = href.split("/")
    if parts[0] == "players" and len(parts) > 1 and parts[1]:
        if parts[1] == "compare":
            return "compare" if len(parts) > 3 and parts[3] else "compare-pick"
        return "player"
    return href


ALL_CSS = page.LAYOUT_CSS + page.pp.CSS          # the renderer's own CSS (4c1: Players, the card, Compare)


def visible_text(h: str) -> str:
    h = re.sub(r"<script.*?</script>", " ", h, flags=re.S)
    h = re.sub(r"<style.*?</style>", " ", h, flags=re.S)
    h = re.sub(r"<[^>]+>", " ", h)
    return _html.unescape(h)


def strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


# =============================================================================
# 7. structure
# =============================================================================

def test_six_tabs_in_order_and_every_route_resolves():
    h = render()
    nav = re.search(r'<nav class="lh-tabbar".*?</nav>', h, re.S).group(0)
    assert re.findall(r'data-tab="(\w+)"', nav) == ["home", "matchups", "teams", "players", "market", "league"]
    routes = set(re.findall(r'data-route="([^"]+)"', h))
    for href in set(re.findall(r'href="#/([^"]*)"', h)):
        assert dyn_route(href) in routes, f"#/{href} has no screen"
    for m in MGRS:
        assert f"teams/{m}" in routes
    assert {"matchups/w9-0", "matchups/w9-1", "home", "matchups", "teams"} <= routes


def test_home_sections_are_in_page_map_order():
    h = render()
    home = re.search(r'data-route="home">(.*?)<section class="v2-screen"', h, re.S).group(1)
    assert re.findall(r'data-section="(\w+)"', home) == ["matchups", "power", "teams", "trade"]
    assert home.index("lh-issuebar") < home.index('data-section="matchups"')
    assert "Week 8 issue" in home                      # until 4d's headline


def test_placeholders_say_coming_and_link_the_current_page_only_in_preview():
    pv, pb = render(), render(mode="publish")
    for key in ("market", "league"):                      # Players is built (4c1)
        sec = lambda h: re.search(rf'data-route="{key}".*?</section></div></section>', h, re.S).group(0)
        assert view.PLACEHOLDER in sec(pv) and view.PLACEHOLDER in sec(pb)
        assert "hub_preview.html#" in sec(pv) and "hub_preview.html" not in sec(pb)


def test_player_names_carry_the_card_key_and_open_the_new_card():
    h = render()
    assert 'data-card="marcus-guard"' in h and 'data-card="jordan-bench"' in h and 'data-card="free-guy"' in h
    js = page.PAGE_JS
    # 4c1: a name opens the NEW card (#/players/<key>), never the old modal
    assert "function openCard(key){location.hash='#/players/'+key;}" in js
    assert "window.pcShow" not in js and "The hub has been updated: reload the page to open player cards." in js


def test_detail_pages_hide_the_header_and_keep_freshness():
    h = render()
    for m in MGRS:
        sec = re.search(rf'data-route="teams/{m}" data-detail="1" hidden>(.*?)</section>\s*(?:<section|</main>)', h, re.S)
        assert sec and 'class="v2-age"' in sec.group(1)


# =============================================================================
# the page displays; the engine computes
# =============================================================================

def test_every_number_on_the_page_is_a_payload_string():
    p = synth_payload()
    now = GEN + timedelta(hours=2)
    text = visible_text(page.render(view.build(p, mode="preview", now=now)))
    known = " ".join(strings(p)) + " " + " ".join(" ".join(infotips.TIPS[k]) for k in infotips.TIPS)
    from modules.hub_page import age_words, STALE_HOURS
    static = {str(STALE_HOURS), "10", "130"} | set(re.findall(r"\d+", age_words(GEN, now)[0]))
    for n in re.findall(r"\d+(?:[.,]\d+)*", text):
        assert n in known or n in static, f"{n!r} on the page is in no payload string"


def test_a_payload_string_is_printed_as_is():
    p = synth_payload()
    p["matchups"]["cards"][0]["total"] = "987,654.3"
    p["v2"]["teams"]["Marcus"]["kpi"]["pf"]["ctx"] = "#9 of 9 \u00b7 +12,345 vs league avg"
    h = render(p)
    assert "987,654.3" in h and "+12,345 vs league avg" in h


def test_the_renderer_does_no_arithmetic():
    src = "".join(inspect.getsource(f) for f in (page.render, page._matchup_card, page._team_card, page._ranking,
                                                 page._trade, page._kpi, page._roster, page._keepers, page._team_page,
                                                 page._matchup_page, page._chart, page._heat, page._spark))
    for banned in ("round", "float", "sum", "sorted", "max", "min", "int"):
        assert not re.search(rf"\b{banned}\(", src), f"the renderer calls {banned}("
    # the page's script reorders by the payload's orders and never compares values
    assert ".sort(" not in page.PAGE_JS


def test_a_payload_without_v2_raises_with_the_runs_error():
    p = synth_payload()
    p["v2"], p["v2_error"] = None, {"stage": "v2", "error": "V2Error: boom"}
    with pytest.raises(view.ViewError, match="boom"):
        view.build(p, mode="preview", now=GEN)
    p.pop("v2"), p.pop("v2_error")
    with pytest.raises(view.ViewError, match="rebuild"):
        view.build(p, mode="preview", now=GEN)


def test_freshness_and_the_stale_banner():
    h = render(now=GEN + timedelta(hours=35))
    assert 'id="stale" role="status" hidden' in h and "35 hours ago" in h
    h = render(now=GEN + timedelta(hours=37))
    assert 'id="stale" role="status">' in h and "not run since Wed Dec 2, 12:05 AM Pacific" in h


# =============================================================================
# lore never reaches it
# =============================================================================

def test_a_lore_tag_in_a_payload_string_never_reaches_the_page():
    p = synth_payload()
    p["v2"]["matchups"][0]["note"] = "A note <!-- lore:phase-x --> here."
    p["matchup_views"][0]["paras"][0]["text"] = "Text <!-- lore:phase-y -->."
    h = render(p)
    assert "lore:" not in h and "phase-x" not in h and "phase-y" not in h


TERMS = ["Marcus", "Tyler", "Glass Cannons", "Zone Defense", "Marcus Guard", "Jordan Bench", "<!-- lore:", "phase-x"]


def _archive(tmp_path):
    from modules import hub_archive
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "STATE_MANIFEST.json").write_bytes((ROOT / "config" / "STATE_MANIFEST.json").read_bytes())
    (tmp_path / "output").mkdir(exist_ok=True)
    (tmp_path / "output" / "WEEK8_NEWSLETTER.html").write_bytes(b"<html>Glass Cannons won</html>")
    return hub_archive.archive_issue(tmp_path, 8, avoid=TERMS, now=GEN)["entry"]


def test_the_publish_mode_file_holds_only_ciphertext_and_round_trips(tmp_path):
    e = _archive(tmp_path)
    p = synth_payload()
    p["v2"]["issue"]["file"] = e["enc"]
    out = tmp_path / "_to_delete" / "4b" / "publish"
    rep = v2pub.build(tmp_path, p, PASS, salt=b"\x01" * 16, out_dir=out, iterations=1000, terms=TERMS, now=GEN)
    assert rep["files"] == ["index.html"]
    sh = (out / "index.html").read_text(encoding="utf-8")
    from modules import hub_publish
    assert hub_publish.scan_dir(out, TERMS)["hits"] == {}
    assert "font-src data:" in sh and "DecompressionStream('gzip')" in sh
    bundle = json.loads(re.search(r'id="hub-bundle">(.*?)</script>', sh, re.S).group(1))
    assert bundle["z"] == "gzip"
    inner = v2pub.open_inner(PASS, bundle)
    assert "Glass Cannons" in inner["page"] and f'data-issue="{e["enc"]}"' in inner["page"]
    assert e["enc"] in inner["issues"]
    assert hub_publish.hits(inner["page"].encode(), TERMS)          # the negative control


def test_publish_refuses_the_live_publish_directory(tmp_path):
    with pytest.raises(v2pub.V2PublishError, match="hub_publish"):
        v2pub.build(tmp_path, synth_payload(), PASS, salt=b"\x01" * 16, out_dir=tmp_path / "output" / "hub_publish",
                    iterations=1000, terms=TERMS, now=GEN)


def test_the_current_shell_is_untouched():
    from modules import hub_page
    s = hub_page.shell_html('{"v":1}')
    assert "font-src" not in s and v2pub.OPEN_TO not in s
    assert s.count(v2pub.CSP_FROM) == 1 and s.count(v2pub.OPEN_FROM) == 1


# =============================================================================
# one source for every value: the token check
# =============================================================================

def test_the_renderers_own_css_has_no_hex_and_no_px():
    css = ALL_CSS
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", css), "a hex colour in the renderer's CSS"
    assert not re.search(r"\d(?:\.\d+)?px", css), "a px literal in the renderer's CSS"
    assert not re.search(r"\d(?:\.\d+)?px", page.render.__doc__ or "")


def test_every_var_resolves_to_a_token_and_media_queries_come_from_tokens():
    vals = tokens.values()
    whole = tokens.css(ALL_CSS)
    for name in set(re.findall(r"var\(--([a-z0-9-]+)", ALL_CSS + tokens.BUNDLE.read_text(encoding="utf-8"))):
        assert name in vals or name in ("team", "team-tint", "team-ink", "g", "g-tint", "s", "n", "y"), name
    assert "{{" not in whole
    assert f"@media (min-width:{vals['bp-wide']})" in whole and f"@media (min-width:{vals['bp-mid']})" in whole
    with pytest.raises(tokens.TokenError):
        tokens.fill("@media (min-width:{{no-such-token}}){}")


def test_bundle_css_is_appended_unchanged_but_its_fonts():
    whole = tokens.css("")
    raw = tokens.BUNDLE.read_text(encoding="utf-8")
    stripped = re.sub(r"url\(\.\./fonts/[^)]+\)", "URL", raw)
    got = re.sub(r"url\(data:font/woff2;base64,[^)]+\)", "URL", whole)
    assert stripped in got
    assert "../fonts/" not in whole


def test_the_page_is_offline():
    for h in (render(), render(mode="publish")):
        assert "http://" not in h and "https://" not in h
        assert not [u for u in re.findall(r"url\(([^)]*)\)", h) if not u.startswith("data:")]
        assert not re.search(r"\bsrc=\"(?!data:)", h)


# =============================================================================
# accessibility
# =============================================================================

INTERACTIVE = re.compile(r"<(a|button)\b([^>]*)>|<(rect|span|div)\b([^>]*\b(?:role=\"button\"|tabindex=)[^>]*)>")


def _classes(attrs: str) -> set:
    m = re.search(r'class="([^"]*)"', attrs)
    return set(m.group(1).split()) if m else set()


def tap_violations(h: str) -> list:
    """Interactive elements with neither a tap class nor a tap parent."""
    body = re.search(r"<body>(.*)</body>", h, re.S).group(1)
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    # every interactive element: a tap class of its own, or a tap parent
    stack, bad = [], []
    for m in re.finditer(r"<(/?)([a-z0-9]+)\b([^>]*?)(/?)>", body):
        close, tag, attrs, selfclose = m.groups()
        if close:
            while stack and stack[-1][0] != tag:
                stack.pop()
            if stack:
                stack.pop()
            continue
        cls = _classes(attrs)
        inter = tag in ("a", "button") or 'role="button"' in attrs or "tabindex=" in attrs
        if inter and not (cls & set(page.TAP_CLASSES)) and not any(c & set(page.TAP_PARENTS) for _t, c in stack):
            bad.append((tag, sorted(cls)))
        if not selfclose and tag not in ("input", "br", "img", "meta", "line", "circle", "polyline", "path", "rect"):
            stack.append((tag, cls))
    return bad


def test_every_tap_target_is_at_least_44px():
    bad = tap_violations(render())
    assert not bad, f"interactive elements without a 44px tap class: {bad[:5]}"
    # and each tap class's CSS gives the height
    css = tokens.css(ALL_CSS)
    for c in page.TAP_CLASSES:
        if c == "lh-c-hit":
            continue                      # the design's chart strips: full plot height (README LineChart)
        rules = re.findall(rf"\.{re.escape(c)}(?:[\w:\-\[\]=\"]*)\s*\{{([^}}]*)\}}", css)
        ok = any(re.search(r"(min-)?height:\s*var\(--(tap-min|row-min)\)", r) for r in rules) or c == "lh-card"
        assert ok, f".{c} sets no tap-min height"
    for parent in page.TAP_PARENTS:
        assert re.search(rf"\.{parent}[^{{]*(?:a|button)[^{{]*\{{[^}}]*(min-(?:height|width):\s*var\(--tap-min\)|inset)", css), parent


def test_no_text_under_10px():
    css = tokens.css(ALL_CSS)
    vals = tokens.values()
    for m in re.findall(r"font-size:\s*([^;}]+)", css):
        m = m.strip()
        if m.endswith("px"):
            assert float(m[:-2]) >= 10, m
        elif m.startswith("var(--"):
            v = vals[m[6:-1]]
            assert float(v.replace("px", "")) >= 10, (m, v)
        elif m.startswith("calc(var(--s)"):
            pass                                        # the monogram: 0.36 x its size (>= 28px)
        else:
            assert m in ("inherit",), m


def test_every_chart_has_an_aria_label_and_nothing_is_hover_only():
    h = render()
    svgs = re.findall(r"<svg\b([^>]*)>", h)
    charts = [a for a in svgs if re.search(r'class="lh-(chart|spark)', a)]
    assert len(charts) >= 4
    for a in charts:
        assert re.search(r'aria-label="[^"]{10,}"', a), a
    css = tokens.css(ALL_CSS)
    assert ":hover" not in css
    assert not re.search(r"mouseover|mouseenter|mouseleave", page.PAGE_JS)


def test_charts_use_the_design_classes_and_no_colour():
    h = render()
    ch = re.findall(r"<svg class=\"lh-chart.*?</svg>", h, re.S)
    assert ch
    for c in ch:
        assert not re.search(r"#[0-9A-Fa-f]{6}\b", c)
        assert "lh-c-line" in c and re.search(r'class="lh-t-(blue|teal|orange|plum)"', c)
    assert 'class="lh-c-event"' in h and "Marcus Wing healthy" in h


def test_desktop_two_columns_and_top_bar():
    css = tokens.css(ALL_CSS)
    wide = css[css.index(f"@media (min-width:{tokens.values()['bp-wide']})"):]
    assert ".v2-cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))" in wide
    assert ".lh-tabbar{order:-1;position:sticky;top:0" in wide


# =============================================================================
# the size budget
# =============================================================================

def budget_bytes():
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    kb = cfg["hub"]["first_load_budget_kb"]
    assert isinstance(kb, int) and kb > 0
    return kb * 1000


def test_the_synthetic_publish_page_is_within_the_budget(tmp_path):
    e = _archive(tmp_path)
    p = synth_payload()
    p["v2"]["issue"]["file"] = e["enc"]
    rep = v2pub.build(tmp_path, p, PASS, salt=b"\x01" * 16, out_dir=tmp_path / "pub", iterations=1000, terms=TERMS,
                      now=GEN)
    assert rep["served_bytes"] <= budget_bytes()
    assert rep["fonts_served_bytes"] > 50_000              # the fonts are in it


# =============================================================================
# team slots and monograms
# =============================================================================

def test_monogram_rule():
    assert v2data.monogram("Glass Cannons") == "GC"
    assert v2data.monogram("Pick & Roll Call") == "PR"
    assert v2data.monogram("Blink-183") == "BL"
    assert v2data.monogram("big nik energy") == "BN"
    assert v2data.monogram("Jokic\u0301 Fans") == "JF"
    for bad in ("", "123", "!!", "X"):
        with pytest.raises(v2data.V2Error):
            v2data.monogram(bad)
    with pytest.raises(v2data.V2Error, match="both give the monogram"):
        v2data.monograms({"a": "Glass Cannons", "b": "Green Cats"})


def _cfg(ts):
    return {"hub": {"team_slots": ts}}


def test_team_slots_are_required_and_complete():
    good = {"_c": "x", "Marcus": "blue", "Tyler": "teal", "Dana": "orange", "Jordan": "plum"}
    assert v2data.team_slots(_cfg(good), MGRS) == SLOTS
    with pytest.raises(v2data.V2Error, match="team_slots"):
        v2data.team_slots({"hub": {}}, MGRS)
    with pytest.raises(v2data.V2Error, match="missing"):
        v2data.team_slots(_cfg({k: v for k, v in good.items() if k != "Dana"}), MGRS)
    with pytest.raises(v2data.V2Error, match="one of"):
        v2data.team_slots(_cfg(dict(good, Dana="green")), MGRS)
    with pytest.raises(v2data.V2Error, match="two managers"):
        v2data.team_slots(_cfg(dict(good, Dana="blue")), MGRS)


def test_the_leagues_slots_are_nicks_decision():
    from modules.data_loader import _LEAGUE_CONFIG, MANAGERS
    assert v2data.team_slots(_LEAGUE_CONFIG, MANAGERS) == {"Nick": "blue", "Hayden": "teal", "Benton": "plum",
                                                          "Garrett": "orange"}


# =============================================================================
# the engine's helpers
# =============================================================================

def test_first_sentence_and_buckets():
    assert v2data.first_sentence("Benton's chance has climbed to 88.9%, from 38.9%. Benton leads by 39.6.") == \
        "Benton's chance has climbed to 88.9%, from 38.9%."
    assert v2data.first_sentence("One sentence only") == "One sentence only"
    assert [v2data.bucket(n, v2data.DAY_EDGES) for n in (0, 3, 4, 6, 8, 10)] == [1, 1, 2, 3, 4, 4]


def test_win_series_marks_only_a_moving_non_routine_cause():
    entry = {"start_date": "2026-11-30", "end_date": "2026-12-06"}
    t = lambda d, h: datetime(2026, 11, 30, h, tzinfo=TZ) + timedelta(days=d)
    pts = [(t(0, 0), 55.0, 45.0, "nightly"), (t(0, 15), 55.0, 45.0, "tag update: X healthy\u2192Q, Y Q\u2192O"),
           (t(1, 0), 50.0, 50.0, "tag update: X healthy\u2192Q, Y Q\u2192O"), (t(2, 0), 60.0, 40.0, "nightly run"),
           (t(3, 0), 64.0, 36.0, "injury entries changed (desktop); also moved: tags")]
    ws = v2data.win_series(entry, "A", "B", pts, TZ, {"A": "Team A", "B": "Team B"})
    ev = [p["event"] for p in ws["points"]]
    assert ev == ["", "", "X healthy\u2192Q", "", "injury entries changed (desktop)"]
    assert all(0.0 <= p["x"] <= 1.0 for p in ws["points"])


def test_flow_series_ends_at_banked_plus_expected():
    entry = {"start_date": "2026-11-30", "end_date": "2026-12-06", "week": 9}
    days = ["2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04", "2026-12-05", "2026-12-06"]
    banked = {"A": {d: 100.0 for d in days[:3]}, "B": {d: 90.0 for d in days[:3]}}
    exp = {"A": {d: 50.0 for d in days[3:]}, "B": {d: 60.0 for d in days[3:]}}
    fs = v2data.flow_series(entry, "A", "B", banked, exp, {"A": "Team A", "B": "Team B"}, {"A": "TA", "B": "TB"})
    assert fs["series"]["A"]["end"] == 500.0 and fs["series"]["B"]["end"] == 510.0
    assert fs["series"]["A"]["label"] == "TA 500 exp." and fs["nb"] == 3
    with pytest.raises(v2data.V2Error):
        v2data.flow_series(entry, "A", "B", banked, {"A": {}, "B": {}}, {"A": "a", "B": "b"}, {"A": "a", "B": "b"})


def test_v2_fails_softly_in_the_run():
    def boom(base, ctx):
        raise v2data.V2Error("a test failure")
    orig = v2data.build
    v2data.build = boom
    said = []
    try:
        v2, err = v2data.build_soft(ROOT, {}, echo=said.append)
    finally:
        v2data.build = orig
    assert v2 is None and err == {"stage": "v2", "error": "V2Error: a test failure"}
    assert said and "NEW HUB KEYS FAILED" in said[0]


def test_hub_state_builds_v2_softly_and_only_adds_keys():
    src = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    assert 'payload["v2"], payload["v2_error"] = v2data.build_soft(' in src


def test_the_preview_path_is_classified_and_ignored():
    m = json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    assert "output/hub_v2_preview.html" in {e["path"] for e in m["excluded"]}
    assert "output/hub_v2_preview.html" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_every_infotip_is_written_once():
    h = render()
    for k in ("title_odds", "win", "keep", "proj", "lines"):
        title, body = infotips.tip(k)
        assert _html.escape(body) in h, k
    with pytest.raises(KeyError):
        infotips.tip("nope")


# =============================================================================
# the one real, unstubbed test: today's inputs, the v2 preview and its size
# =============================================================================

@pytest.fixture(scope="module")
def real_payload():
    from modules import hub_state as hs, player_actuals
    from modules.league_clock import league_now
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_history.jsonl",
              ROOT / "output" / "title_odds_latest.json", ROOT / "output" / "tag_records.jsonl",
              ROOT / "config" / "ROSTERS.json"]
    if not all(p.exists() for p in needed):
        pytest.skip("no league state on this machine")
    league_state.skip_if_actuals_behind()   # H51: a cache a day behind is normal
    try:
        return hs.build(ROOT, now=league_now(), allow_engine_mismatch=True, echo=lambda *a, **k: None)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        pytest.skip(f"the hub's real inputs are not current today ({e})")


@pytest.mark.slow
def test_real_v2_preview_from_todays_inputs(real_payload, tmp_path):
    from modules.data_loader import MANAGERS
    from modules import hub_publish
    p = real_payload
    assert p.get("v2_error") is None, p.get("v2_error")
    v2 = p["v2"]
    assert set(v2["teams"]) == set(MANAGERS)
    assert {m: t["slot"] for m, t in v2["teams"].items()} == {"Nick": "blue", "Hayden": "teal", "Benton": "plum",
                                                               "Garrett": "orange"}
    assert len({t["mono"] for t in v2["teams"].values()}) == 4
    assert v2["team_order"] == [r["manager"] for r in p["power"]["rows"]]
    assert len(v2["matchups"]) == len(p["matchups"]["cards"])
    for m, t in v2["teams"].items():
        assert t["spark"]["texts"][-1] == next(r["odds"] for r in p["power"]["rows"] if r["manager"] == m)
        assert len(t["roster"]["extra"]) == len(p["rosters"][m]["players"])
    now = datetime.fromisoformat(p["generated_at"]) + timedelta(minutes=5)
    h = page.render(view.build(p, mode="preview", now=now))
    text = visible_text(h)
    known = " ".join(strings(p)) + " " + " ".join(" ".join(v) for v in infotips.TIPS.values())
    from modules.hub_page import age_words, STALE_HOURS
    static = {str(STALE_HOURS), "10", "130"} | set(re.findall(r"\d+", age_words(datetime.fromisoformat(
        p["generated_at"]), now)[0]))
    for n in re.findall(r"\d+(?:[.,]\d+)*", text):
        assert n in known or n in static, f"{n!r} on the page is in no payload string"
    routes = set(re.findall(r'data-route="([^"]+)"', h))
    for m in MANAGERS:
        assert f"teams/{m}" in routes
    for href in set(re.findall(r'href="#/([^"]*)"', h)):
        assert dyn_route(href) in routes
    assert "http://" not in h and "https://" not in h and "lore:" not in h
    assert not tap_violations(h)
    for a in [a for a in re.findall(r"<svg\b([^>]*)>", h) if re.search(r'class="lh-(chart|spark)', a)]:
        assert re.search(r'aria-label="[^"]{10,}"', a), a
    # publish mode, a throwaway key, to a scratch folder: the budget and the scan
    rep = v2pub.build(ROOT, p, PASS, salt=b"\x02" * 16, out_dir=tmp_path / "pub", iterations=1000,
                      now=now)
    assert rep["served_bytes"] <= budget_bytes(), rep
    assert hub_publish.scan_dir(tmp_path / "pub", hub_publish.scan_terms(ROOT))["hits"] == {}
