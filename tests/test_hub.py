"""Step 1b: the hub's invariants (claude/HANDOFF_STEP1B_HUB_PAGE_2026-10-31.md
s.5). Synthetic where the rule is logic; on the real build where the point is
the real data (state-dependent, like test_grid_il_slots: they need the week's
live line, IL file and actuals to be current, and skip with the reason if not)."""

import html as _html
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from modules import hub_state as hs, hub_page, hub_crypto, hub_archive, hub_publish

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=-8))
GEN = datetime(2026, 11, 2, 0, 5, tzinfo=TZ)
PASS = "fake test passphrase only, not real"


# =============================================================================
# a synthetic payload, every number a string
# =============================================================================

# a hub_charts chart, every value a string (hub polish 3)
SAMPLE_CHART = {"vb": "0 0 340 200", "aria": "a chart", "tip0": "Tap a point. Latest: Tue 11-03: Mgr One 70.0%",
                "grid": [{"x1": "30", "y1": "170", "x2": "262", "y2": "170", "cls": "g-line"}],
                "texts": [{"x": "26", "y": "173", "t": "0%", "anchor": "end", "cls": "ax", "fill": ""},
                          {"x": "200", "y": "60", "t": "Mgr One 70.0%", "anchor": "start", "cls": "lab",
                           "fill": "#1D5FD1"}],
                "paths": [{"d": "M30 100 L194 60", "stroke": "#1D5FD1", "dash": "", "w": "2"}],
                "dots": [{"cx": "194", "cy": "60", "r": "3", "fill": "#1D5FD1"}],
                "hits": [{"x": "185", "y": "51", "w": "18", "h": "18", "tip": "Tue 11-03: Mgr One 70.0%"}],
                "note": "One point per priced line."}


def sample_payload(**over) -> dict:
    side = lambda t, m, now, proj, win: {"team": t, "manager": m, "now": now, "proj": proj, "win": win}
    players = [
        {"name": "Zed Alpha", "pos": "PG", "nba": "AAA", "fppg": "41.3", "proj": "44.2", "l14": "40.9",
         "gl": "4", "keep": "91%", "keep_strong": True, "in_il": False,
         "tags": [{"text": "Q", "kind": "q"}], "status": {"source": "tag", "why": "Q tag"}},
        {"name": "Yan Beta", "pos": "C", "nba": "BBB", "fppg": "\u2014", "proj": "30.8", "l14": "\u2014",
         "gl": "\u2014", "keep": "6%", "keep_strong": False, "in_il": True,
         "tags": [{"text": "IL slot", "kind": "il"}, {"text": "back 12-14", "kind": "il"}],
         "status": {"source": "il_slot", "why": "IL slot"}},
    ]
    p = {
        "schema": 1, "generated_at": GEN.isoformat(), "generated_epoch_ms": int(GEN.timestamp() * 1000),
        "generated_text": "Mon Nov 2, 12:05 AM Pacific", "league_day": "2026-11-02", "week": 3,
        "engine": {"commit": "abc1234", "dirty": False, "key": "abc1234"},
        "header": {"title": "League Hub", "week_label": "Week 3 \u00b7 Mon Nov 2",
                   "lock": {"locked": False, "text": "Lines are live until today's first tip, 4:00 PM Pacific."},
                   "line_text": "Line priced Mon Nov 2, 12:03 AM Pacific", "engine_mismatch": None},
        "matchups": {"clock": "0 of 7 game days played", "cards": [
            {"a": side("Team Uno", "Mgr One", "0", "1,702", "70.0%"),
             "b": side("Team Dos", "Mgr Two", "0", "1,595", "30.0%"),
             "bar_a": "70.0%", "spread": "Mgr One \u2212107", "total": "3,300", "moneyline": "\u2212235 / +235",
             "views": {"sum": "v-mu3-0-sum", "win": "v-mu3-0-win", "flow": "v-mu3-0-flow"}}],
            "buttons": {"sum": "Summary", "win": "Win %", "flow": "Game flow"},
            "last": {"view": "v-last", "link": "Last week's matchups", "title": "Week 2 \u00b7 Oct 26\u2013Nov 1",
                     "note": "How last week ended.",
                     "cards": [{"a": {"team": "Team Uno", "manager": "Mgr One", "score": "1,567"},
                                "b": {"team": "Team Dos", "manager": "Mgr Two", "score": "1,317"},
                                "result": "Final: Mgr One by 250",
                                "views": {"sum": "v-mu2-0-sum", "win": "v-mu2-0-win", "flow": "v-mu2-0-flow"}}]}},
        "matchup_views": [
            {"id": f"v-mu{w}-0-{k}", "back": "v-main" if w == 3 else "v-last",
             "back_label": "Hub" if w == 3 else "Last week's matchups", "title": "Team Uno vs Team Dos",
             "sub": f"Week {w} \u00b7 x", "kind": "summary" if k == "sum" else "chart",
             **({"paras": [{"head": "Monday's preview (newsletter line: Team Uno -107.0 / -235, O/U 3300)",
                            "text": "Mgr One leads Mgr Two by 11.5, 120.5 to 109.0."}]} if k == "sum" else
                {"chart": SAMPLE_CHART})}
            for w in (3, 2) for k in ("sum", "win", "flow")],
        "power": {"kind": "title", "label": "Title odds", "as_of": "Title odds as of Mon Nov 2",
                  "note": "Change appears from the second run.",
                  "rows": [{"rank": "1", "manager": "Mgr One", "team": "Team Uno", "record": "2-0",
                            "odds": "58.5%", "delta": "\u25b2 3.0", "delta_dir": "up", "adds": "1 / 3",
                            "adds_over": False, "pf": "3,207", "seed": "seed 1"},
                           {"rank": "2", "manager": "Mgr Two", "team": "Team Dos", "record": "0-2",
                            "odds": "41.5%", "delta": "\u25bc 3.0", "delta_dir": "down", "adds": "0 / 3",
                            "adds_over": False, "pf": "2,911", "seed": "seed 2"}],
                  "chart_title": "Title odds", "chart": SAMPLE_CHART},
        "rosters": {"Mgr One": {"manager": "Mgr One", "team": "Team Uno", "subtitle": "Mgr One \u00b7 2-0 \u00b7 #1",
                                "odds": "58.5%", "odds_label": "Title odds", "adds": "1 of 3",
                                "starts": "48 starts", "size": "Active 15/15 \u00b7 IL 1/2",
                                "players": players, "orders": {"name": [1, 0], "fppg": [0, 1], "proj": [0, 1],
                                                               "l14": [0, 1], "gl": [0, 1], "keep": [0, 1]},
                                "default_order": "proj", "note": "Keep is the chance he is one of your 5 keepers.",
                                "pending": [{"text": "+ Joe Claimed joins Mon 11-09 (claimed Thu 11-05)"}]},
                    "Mgr Two": {"manager": "Mgr Two", "team": "Team Dos", "subtitle": "Mgr Two \u00b7 0-2 \u00b7 #2",
                                "odds": "41.5%", "odds_label": "Title odds", "adds": "0 of 3",
                                "starts": "45 starts", "size": "Active 15/15 \u00b7 IL 0/2",
                                "players": [], "orders": {k: [] for k in ("name", "fppg", "proj", "l14", "gl", "keep")},
                                "default_order": "proj", "note": "n", "pending": []}},
        "grid": {"tabs": [
            {"key": "this", "label": "Rest of this week", "note": "From Mon Nov 2.", "range": "Nov 2\u20138",
             "days": [{"dow": "M", "day": "2", "date": "2026-11-02"}],
             "schedule_note": "",
             "rows": [{"manager": "Mgr One", "cells": [{"n": "11", "kind": "over", "overflow": "1", "starts": "10",
                                                        "est": ""}],
                       "starts": "10", "idle": "1"}]},
            {"key": "next", "label": "Next week", "note": "As rosters stand today.", "range": "Nov 9\u201315",
             "days": [{"dow": "M", "day": "9", "date": "2026-11-09"}],
             "schedule_note": "",
             "rows": [{"manager": "Mgr One", "cells": [{"n": "3", "kind": "light", "overflow": "0", "starts": "3",
                                                        "est": ""}],
                       "starts": "3", "idle": "0"}]}],
            "legend": {"light": "Light night (4 or fewer)", "over": "More than 10: some sit",
                       "est": "Estimated: games the NBA has not scheduled yet"},
            "foot": "Starts: games that fit a starting lineup."},
        "free_agents": {"rows": [{"name": "Free Agent", "pos": "SF", "nba": "CCC", "proj": "39.0", "g1": "3",
                                  "g2": "4", "g3": "0", "pts": "273.0", "tags": [], "status": "healthy"},
                                 {"name": "Hurt Agent", "pos": "PG", "nba": "DDD", "proj": "41.5", "g1": "0",
                                  "g2": "0", "g3": "0", "pts": "0.0", "status": "override",
                                  "tags": [{"text": "O \u00b7 back 11-23", "kind": "out"}]}],
                        "aside": "by projected points, rest of this week + next", "pts_label": "Pts (2 wks)",
                        "mode": "this", "cols": ["GL", "Next", "Wk 5"], "weeks": [3, 4, 5],
                        "empty": "No pickup joins a roster again this season.", "schedule_note": "",
                        "note": "Chat claims arrive with the ledger."},
        "stash": {"rows": [{"name": "Hurt Agent", "pos": "PG", "nba": "DDD", "proj": "41.5", "status": "override",
                            "tags": [{"text": "O \u00b7 back 11-23", "kind": "out"}], "season": False,
                            "season_note": ""},
                           {"name": "Gone Agent", "pos": "C", "nba": "EEE", "proj": "33.3", "status": "season_out",
                            "tags": [{"text": "OFS \u00b7 season", "kind": "out"}], "season": True,
                            "season_note": "an IL slot all season: keeper value only"}],
                  "aside": "tagged O or OFS, by projection", "open_il": "Open IL slots now: Mgr Two 2.",
                  "empty": "No free agent is tagged O or OFS.", "note": "A display, not advice."},
        "advice": None, "advice_empty": "Advice is being rebuilt; it returns here once it is ready.",
        "moves": {"weeks": [{"key": "pre", "label": "Pre-season", "used": None, "used_note": "Count nowhere.",
                             "items": []},
                            {"key": "3", "label": "Week 3 \u00b7 Nov 2\u20138", "used_note": "Adds used.",
                             "used": [{"manager": "Mgr One", "text": "Mgr One 1 of 3", "over": False},
                                      {"manager": "Mgr Two", "text": "Mgr Two 0 of 3", "over": False}],
                             "items": [{"day": "Mon", "date": "11/2", "time": "6:11 AM", "who": "Mgr One",
                             "what": "added Free Guy", "note": "week 2 claim", "state": "Applied",
                             "kind": "add", "parts": [{"kind": "add", "marker": "+", "text": "added Free Guy"}]},
                            {"day": "Mon", "date": "11/2", "time": "6:12 AM", "who": "Mgr Two",
                             "what": "added New Guy, dropped Old Guy", "note": "", "state": "Applied",
                             "kind": "add-drop",
                             "parts": [{"kind": "add", "marker": "+", "text": "added New Guy"},
                                       {"kind": "drop", "marker": "\u2212", "text": "dropped Old Guy"}]},
                            {"day": "Sun", "date": "11/1", "time": "8:45 PM", "who": "Trade:",
                             "what": "Mgr One gets A Guy; Mgr Two gets B Guy", "note": "", "state": "Applied",
                             "kind": "trade",
                             "parts": [{"kind": "trade", "marker": "\u21c4", "text": "Mgr One gets A Guy"},
                                       {"kind": "trade", "marker": "\u21c4", "text": "Mgr Two gets B Guy"}]},
                            {"day": "Sun", "date": "10/25", "time": "10:35 PM", "who": "Mgr Two",
                             "what": "dropped Kept Drop", "note": "", "state": "Applied",
                             "kind": "drop", "parts": [{"kind": "drop", "marker": "\u2212",
                                                       "text": "dropped Kept Drop"}]}]}],
                  "default": "3", "empty": "No moves in this week.", "note": "by budget week."},
        "newsletter": {"current": {"week": "2", "label": "Week 2 \u00b7 Oct 26\u2013Nov 1",
                                   "file": "week02-aaaaaaaaaaaa.enc", "size": "2.4 MB"},
                       "archive": [], "empty": "No issue archived yet.", "note": "Past issues."},
        "sources": {"line": "output/live_lines_week3.json", "title_odds": "x", "actuals_through": "2026-11-01",
                    "tags": "t", "il_slots": "i"},
    }
    p.update(over)
    return p


def visible_text(page: str) -> str:
    page = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
    page = re.sub(r"<style.*?</style>", " ", page, flags=re.S)
    page = re.sub(r"<[^>]+>", " ", page)
    return _html.unescape(page)


def payload_strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from payload_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from payload_strings(v)
    elif isinstance(o, str):
        yield o


# =============================================================================
# 2. the hub computes nothing
# =============================================================================

def test_every_number_on_the_page_is_a_payload_string():
    p = sample_payload()
    now = GEN + timedelta(hours=2)
    text = visible_text(hub_page.render(p, now=now))
    known = " ".join(payload_strings(p))
    # the renderer's own heading ("Moves \u00b7 last 7 days"), and the age in words,
    # the one value worked out from the reader's clock (hub_page's docstring)
    static = ({"7", str(hub_page.STALE_HOURS)}
              | set(re.findall(r"\d+", hub_page.age_words(GEN, now)[0])))
    for n in re.findall(r"\d+(?:[.,]\d+)*", text):
        assert n in known or n in static, f"{n!r} on the page is in no payload string"


def test_a_payload_string_is_printed_as_is():
    p = sample_payload()
    p["matchups"]["cards"][0]["total"] = "987,654.3"
    p["rosters"]["Mgr One"]["players"][0]["keep"] = "12345%"
    page = hub_page.render(p, now=GEN)
    assert "987,654.3" in page and "12345%" in page


def test_the_renderer_does_no_arithmetic_on_the_payload():
    import inspect
    src = inspect.getsource(hub_page.render)
    for banned in ("round", "float", "sum", "sorted", "max", "min"):
        assert not re.search(rf"\b{banned}\(", src), f"hub_page.render calls {banned}("


# =============================================================================
# 3. freshness always shown; the stale banner over 36 hours (a fake clock)
# =============================================================================

def test_freshness_is_shown_and_not_stale_under_36_hours():
    page = hub_page.render(sample_payload(), now=GEN + timedelta(hours=35))
    assert 'id="stale" hidden' in page and "35 hours ago" in page
    assert "Mon Nov 2, 12:05 AM Pacific" in page


def test_a_payload_over_36_hours_old_carries_the_stale_banner_first():
    page = hub_page.render(sample_payload(), now=GEN + timedelta(hours=37))
    m = re.search(r'<div class="stale" id="stale"([^>]*)>', page)
    assert m and "hidden" not in m.group(1)
    assert page.index('id="stale"') < page.index('id="v-main"')
    assert "2 days ago" in page and "more than 36 hours old" in page


def test_the_page_script_refreshes_the_age_on_the_readers_clock():
    page = hub_page.render(sample_payload(), now=GEN)
    assert f'data-epoch="{int(GEN.timestamp() * 1000)}"' in page and 'data-stale-hours="36"' in page
    assert "Date.now()" in hub_page.PAGE_JS


# =============================================================================
# 11. no Section 10 output: advice is null and the slot is its empty state
# =============================================================================

def test_advice_slot_is_empty_and_a_non_null_advice_refuses():
    p = sample_payload()
    assert p["advice"] is None
    assert "Advice is being rebuilt; it returns here once it is ready." in hub_page.render(p, now=GEN)
    with pytest.raises(ValueError):
        hub_page.render(sample_payload(advice={"trades": []}), now=GEN)


def test_the_hub_never_reads_section_10():
    src = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    assert "advice_runner" not in src and "build_advice" not in src and "advice_render" not in src


# =============================================================================
# 13. roster size: active and IL counted apart
# =============================================================================

def test_fifteen_with_no_one_in_il_is_a_full_active_roster():
    assert hs.roster_size_text(15, 0, 15, 2) == "Active 15/15 \u00b7 IL 0/2"
    assert hs.roster_size_text(17, 2, 15, 2) == "Active 15/15 \u00b7 IL 2/2"
    assert "17" not in hs.roster_size_text(15, 0, 15, 2)
    with pytest.raises(hs.HubInputError):
        hs.roster_size_text(17, 0, 15, 2)


# =============================================================================
# 10. the grid's counting rule (s.1a)
# =============================================================================

MON, TUE = date(2026, 11, 2), date(2026, 11, 3)
NEXT_MON = date(2026, 11, 9)
WEEKS = {3: (date(2026, 11, 2), date(2026, 11, 8)), 4: (date(2026, 11, 9), date(2026, 11, 15)),
         8: (date(2026, 12, 7), date(2026, 12, 13))}
POS = ["PG", "SG", "SF", "PF", "C", "PG", "SG", "SF", "PF", "C", "C", "PG", "SF"]


def world(n, tags=None, il=(), overrides=()):
    names = [f"P{i}" for i in range(n)]
    info = {nm: {"nba_team": f"T{i}", "positions": {POS[i % len(POS)]}, "proj_fppg": 40.0 - i}
            for i, nm in enumerate(names)}
    team_dates = {f"T{i}": {MON, TUE, NEXT_MON} for i in range(n)}
    av = hs.Availability({"M": names}, {"M": list(il)}, tags or {}, {"players": list(overrides)},
                         3, info, team_dates, WEEKS, MON)
    return av, names


def test_an_il_slot_player_and_an_o_tagged_day_are_excluded():
    av, names = world(6, tags={"P1": "O", "P2": "Q", "P3": "OFS"}, il=["P0"])
    assert av.players("M", MON) == ["P2", "P4", "P5"]          # Q plays; O, OFS and IL do not
    # the O tag's three games are MON, TUE and NEXT_MON, so it reaches next week; OFS and IL stay out
    assert av.players("M", NEXT_MON) == ["P2", "P4", "P5"]


def test_an_o_tag_costs_at_most_three_games_from_today():
    """Nick, 11-03: an O tag with no injury entry misses at most his team's
    next 3 games (absence.MAX_TAG_GAMES), counted from today."""
    from modules import absence
    assert absence.MAX_TAG_GAMES == 3
    wed, thu, fri = date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)
    info = {"P0": {"nba_team": "T0", "positions": {"PG"}, "proj_fppg": 40.0}}
    team_dates = {"T0": {MON, wed, thu, fri, NEXT_MON}}
    av = hs.Availability({"M": ["P0"]}, {"M": []}, {"P0": "O"}, {"players": []},
                         3, info, team_dates, WEEKS, MON)
    assert [av.players("M", d) for d in (MON, wed, thu, fri, NEXT_MON)] == [[], [], [], ["P0"], ["P0"]]
    later = hs.Availability({"M": ["P0"]}, {"M": []}, {"P0": "O"}, {"players": []},
                            3, info, team_dates, WEEKS, wed)        # counted from today, not Monday
    assert [later.players("M", d) for d in (wed, thu, fri, NEXT_MON)] == [[], [], [], ["P0"]]


def test_availability_refuses_without_today():
    info = {"P0": {"nba_team": "T0", "positions": {"PG"}, "proj_fppg": 40.0}}
    with pytest.raises(hs.HubInputError):
        hs.Availability({"M": ["P0"]}, {"M": []}, {}, {"players": []}, 3, info, {"T0": {MON}}, WEEKS, None)


def test_an_overrides_dates_are_respected():
    ret = {"player_name": "P0", "out_weeks": [1, 2], "return_week": 3, "return_date": "2026-11-03"}
    out = {"player_name": "P1", "out_weeks": [3], "return_week": 4, "return_date": "2026-11-09"}
    mid = {"player_name": "P2", "out_weeks": [3], "out_from": "2026-11-03"}
    av, _ = world(4, overrides=[ret, out, mid])
    assert av.players("M", MON) == ["P2", "P3"]                # P0 back 11-03; P1 out all week
    assert av.players("M", TUE) == ["P0", "P3"]                # P0 back, P2 out from 11-03
    assert av.players("M", NEXT_MON) == ["P0", "P1", "P2", "P3"]


def test_a_day_of_eleven_shows_overflow_one_and_starts_ten():
    av, _ = world(11)
    tab = hs.build_grid_tab(av, ["M"], [MON], 4, {MON: 6})
    cell = tab["rows"][0]["cells"][0]
    assert (cell["n"], cell["overflow"], cell["kind"]) == ("11", "1", "over")
    assert tab["rows"][0]["starts"] == "10" and tab["rows"][0]["idle"] == "1"


def test_light_nights_and_no_game_days():
    av, _ = world(3)
    tab = hs.build_grid_tab(av, ["M"], [MON, date(2026, 11, 4)], 4, {MON: 6, date(2026, 11, 4): 0})
    assert [c["kind"] for c in tab["rows"][0]["cells"]] == ["light", "off"]


def test_odds_column_switches_from_week_15_and_in_the_cup():
    cfg = {"regular_season_weeks": 15}
    assert hs.odds_kind(14, cfg, [22, 23]) == "title"
    assert hs.odds_kind(15, cfg, [22, 23]) == "playoff"
    assert hs.odds_kind(22, cfg, [22, 23]) == "cup"


# =============================================================================
# 7, 8. encryption: round trip; wrong / missing / short passphrase
# =============================================================================

def test_round_trip_through_the_shell_with_the_pages_algorithm():
    inner = json.dumps({"page": "<p>hello</p>", "issues": {}}).encode()
    shell = hub_page.shell_html(hub_crypto.bundle_json(hub_crypto.make_bundle(PASS, inner)))
    bundle = json.loads(re.search(r'<script type="application/json" id="hub-bundle">(.*?)</script>',
                                  shell, re.S).group(1))
    assert bundle["kdf"] == "PBKDF2-SHA256" and bundle["iter"] >= 600_000
    assert len(hub_crypto.unb64(bundle["salt"])) == 16 and len(hub_crypto.unb64(bundle["iv"])) == 12
    assert hub_crypto.open_bundle(PASS, bundle) == inner


def test_a_new_build_has_a_new_salt_and_iv():
    a = hub_crypto.make_bundle(PASS, b"x", iterations=1000)
    b = hub_crypto.make_bundle(PASS, b"x", iterations=1000)
    assert a["salt"] != b["salt"] and a["iv"] != b["iv"] and a["ct"] != b["ct"]


def test_a_wrong_passphrase_does_not_open():
    from cryptography.exceptions import InvalidTag
    b = hub_crypto.make_bundle(PASS, b"secret", iterations=1000)
    with pytest.raises(InvalidTag):
        hub_crypto.open_bundle(PASS + "x", b)


def test_missing_and_short_passphrases_refuse_and_never_echo_it():
    with pytest.raises(hub_crypto.PassphraseMissing):
        hub_crypto.passphrase_from_env({})
    with pytest.raises(hub_crypto.PassphraseMissing):
        hub_crypto.passphrase_from_env({"HUB_PASSPHRASE": ""})
    with pytest.raises(hub_crypto.PassphraseTooShort) as e:
        hub_crypto.passphrase_from_env({"HUB_PASSPHRASE": "hunter2hunter2"})
    assert "hunter2" not in str(e.value)
    assert hub_crypto.passphrase_from_env({"HUB_PASSPHRASE": PASS}) == PASS


def test_the_shell_says_wrong_passphrase_and_nothing_else():
    shell = hub_page.shell_html('{"v":1}')
    assert "Wrong passphrase." in shell
    assert "remember" in shell.lower() and "localStorage" in shell
    # a stored key from another build (another salt) is dropped, not tried and failed loudly
    assert "s.salt!==B.salt" in hub_page.SHELL_JS


def test_the_shell_and_page_load_nothing_external():
    for text in (hub_page.shell_html('{"v":1}'), hub_page.render(sample_payload(), now=GEN)):
        assert not re.search(r"(src|href)=[\"']https?:", text)
        assert "fonts.googleapis" not in text and "@import" not in text


# =============================================================================
# 4. the archive is never rewritten; 1. nothing in the publish directory is plaintext
# =============================================================================

TERMS = ["Mgr One", "Mgr Two", "Team Uno", "Team Dos", "Zed Alpha", "Yan Beta", "Free Agent",
         "Free Guy", "<!-- lore:", "phase-mgr-one"]


def seed(tmp_path, week, body):
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)
    (out / f"WEEK{week}_NEWSLETTER.html").write_bytes(body)
    return hub_archive.archive_issue(tmp_path, week, avoid=TERMS, now=GEN)


def test_an_archived_issue_is_byte_identical_and_never_rewritten(tmp_path):
    body = b"<html>Week 1 -- Mgr One beat Mgr Two</html>"
    r = seed(tmp_path, 1, body)
    e = r["entry"]
    d = hub_archive.archive_dir(tmp_path)
    assert (d / e["plain"]).read_bytes() == body
    assert hub_crypto.open_sealed(hub_crypto.unb64(e["key_b64"]), (d / e["enc"]).read_bytes()) == body
    assert hub_archive.archive_issue(tmp_path, 1, avoid=TERMS, now=GEN)["wrote"] is False
    (tmp_path / "output" / "WEEK1_NEWSLETTER.html").write_bytes(body + b" edited")
    with pytest.raises(hub_archive.ArchiveConflict):
        hub_archive.archive_issue(tmp_path, 1, avoid=TERMS, now=GEN)
    with pytest.raises(hub_archive.IssueChanged):
        hub_archive.verify(tmp_path)
    assert (d / e["plain"]).read_bytes() == body              # untouched


def test_archive_needs_the_scan_terms(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "WEEK1_NEWSLETTER.html").write_bytes(b"x")
    with pytest.raises(hub_archive.ArchiveError):
        hub_archive.archive_issue(tmp_path, 1)


def publish_world(tmp_path):
    r = seed(tmp_path, 2, b"<html>Team Uno 1735 def. Team Dos; <!-- lore:phase-mgr-one --></html>")
    p = sample_payload()
    p["newsletter"]["current"]["file"] = r["entry"]["enc"]
    return p


def test_the_publish_directory_holds_only_ciphertext(tmp_path):
    p = publish_world(tmp_path)
    rep = hub_publish.build(tmp_path, p, PASS, terms=TERMS, iterations=1000, now=GEN)
    assert sorted(rep["files"]) == ["index.html", f"issues/{p['newsletter']['current']['file']}"]
    scan = hub_publish.scan_dir(hub_publish.publish_dir(tmp_path), TERMS)
    assert scan["hits"] == {}
    # the negative control: the plaintext page and issue DO trip the scan
    assert hub_publish.hits(hub_page.render(p, now=GEN, mode="publish").encode(), TERMS)
    assert hub_publish.hits((hub_archive.archive_dir(tmp_path) /
                             p["newsletter"]["current"]["file"].replace(".enc", ".html")).read_bytes(), TERMS)


def test_a_stray_file_in_the_publish_directory_refuses(tmp_path):
    p = publish_world(tmp_path)
    hub_publish.build(tmp_path, p, PASS, terms=TERMS, iterations=1000, now=GEN)
    (hub_publish.publish_dir(tmp_path) / "hub_preview.html").write_text("Mgr One")
    with pytest.raises(hub_publish.PublishError, match="hub_preview"):
        hub_publish.build(tmp_path, p, PASS, terms=TERMS, iterations=1000, now=GEN)


def test_the_published_page_decrypts_to_the_hub_and_the_issue_keys(tmp_path):
    p = publish_world(tmp_path)
    hub_publish.build(tmp_path, p, PASS, terms=TERMS, iterations=1000, now=GEN)
    shell = (hub_publish.publish_dir(tmp_path) / "index.html").read_text(encoding="utf-8")
    bundle = json.loads(re.search(r'id="hub-bundle">(.*?)</script>', shell, re.S).group(1))
    inner = json.loads(hub_crypto.open_bundle(PASS, bundle))
    assert "Team Uno" in inner["page"] and "data-issue" in inner["page"]
    f = p["newsletter"]["current"]["file"]
    sealed = (hub_publish.publish_dir(tmp_path) / "issues" / f).read_bytes()
    assert b"Team Uno" in hub_crypto.open_sealed(hub_crypto.unb64(inner["issues"][f]), sealed)


def test_the_preview_never_lands_in_the_publish_directory():
    src = (ROOT / "scripts" / "build_hub.py").read_text(encoding="utf-8")
    assert 'base / "output" / "hub_preview.html"' in src
    assert hub_publish.PUBLISH_RELDIR == Path("output") / "hub_publish"
    # and the publish step writes only the shell and the issues (the stray test above refuses more)
    pub = (ROOT / "modules" / "hub_publish.py").read_text(encoding="utf-8")
    assert "hub_preview" not in pub


# =============================================================================
# 9. every new file is classified
# =============================================================================

def test_every_hub_path_is_classified_and_ignored():
    m = json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    files = {f["path"] for f in m["files"]}
    dirs = {d["path"] for d in m["dirs"]}
    excluded = {e["path"] for e in m["excluded"]}
    assert {"data/player_actuals.json", "output/hub_state.json"} <= files
    assert "output/hub_archive" in dirs
    assert {"output/hub_preview.html", "output/hub_publish/"} <= excluded
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for line in ("data/player_actuals.json", "output/hub_state.json", "output/hub_archive/",
                 "output/hub_preview.html", "output/hub_publish/"):
        assert line in gi


# =============================================================================
# 6. keep chances are never written to data/keepability/ (source)
# =============================================================================

def test_no_hub_module_can_write_a_keepability_snapshot():
    for f in ("hub_state.py", "hub_page.py", "hub_publish.py", "hub_archive.py", "player_actuals.py"):
        src = (ROOT / "modules" / f).read_text(encoding="utf-8")
        for banned in ("publish_snapshot", "snapshot_path", "SNAPSHOT_DIR", "data/keepability",
                       "\"keepability\""):
            assert banned not in src, f"{f} mentions {banned}"


# =============================================================================
# the real build (state-dependent: today's line, IL file and actuals)
# =============================================================================

@pytest.fixture(scope="module")
def real():
    from modules import player_actuals, live_lines_page
    from modules.league_clock import league_now
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_history.jsonl",
              ROOT / "output" / "title_odds_latest.json", ROOT / "output" / "tag_records.jsonl",
              ROOT / "data" / "transaction_log.jsonl", ROOT / "config" / "ROSTERS.json"]
    if not all(p.exists() for p in needed):
        pytest.skip("league state not in this checkout (the hub's real inputs)")
    kdir = ROOT / "data" / "keepability"
    before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in kdir.glob("*")} if kdir.is_dir() else {}
    from modules import keepability_v3

    def no_publish(*a, **k):
        raise AssertionError("the hub build wrote a keepability snapshot")
    orig = keepability_v3.publish_snapshot
    keepability_v3.publish_snapshot = no_publish
    try:
        now = league_now()
        payload = hs.build(ROOT, now=now, allow_engine_mismatch=True)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        pytest.skip(f"the hub's real inputs are not current today ({e}); these tests are "
                    "state-dependent like test_grid_il_slots")
    finally:
        keepability_v3.publish_snapshot = orig
    after = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in kdir.glob("*")} if kdir.is_dir() else {}
    return {"payload": payload, "now": now, "keep_before": before, "keep_after": after}


def test_real_build_wrote_nothing_to_keepability(real):
    assert real["keep_before"] == real["keep_after"]


def test_real_power_order_is_build_power_rankings_and_odds_the_latest_run(real):
    """Invariant 6 of step 1c: the hub reads output/title_odds_latest.json, and
    its power-rankings order equals build_power_rankings' on that run."""
    from modules.data_loader import load_all_data, MANAGERS
    from modules.report_builder import build_power_rankings
    from modules import keepability_v3, title_odds_history as toh, title_odds_run as tor_mod
    p = real["payload"]
    data = load_all_data(ROOT, current_week=None)
    tor, latest, _prev = hs.title_odds_inputs(ROOT, data, MANAGERS)
    assert latest == tor_mod.load_latest(ROOT)
    kw = keepability_v3.keeper_watch(data, p["week"] - 1, root=ROOT)
    ranked = build_power_rankings(tor, data.records, data.leaguehistory, keeper_watch=kw)
    assert [r["manager"] for r in p["power"]["rows"]] == [r["manager"] for r in ranked]
    for r in p["power"]["rows"]:
        assert r["odds"] == f"{latest['title_odds'][r['manager']]:.1f}%"
    # the latest run has its history row, with the same odds
    row = next(r for r in toh.read(ROOT) if r["run_id"] == latest["run_id"])
    assert row["title_odds"] == latest["title_odds"]


def test_real_injury_status_equals_team_health(real):
    from modules.data_loader import load_all_data
    from modules.report_builder import build_current_team_health
    from modules.roster_plan import load_il_slots
    p = real["payload"]
    data = load_all_data(ROOT, current_week=None)
    from modules import tag_records
    rosters_ = data.get_current_rosters()
    tags = tag_records.hub_tags(tag_records.latest(ROOT), [n for v in rosters_.values() for n in v])
    health = build_current_team_health(data, p["week"] - 1, injury_statuses=tags,
                                       il_state=load_il_slots(ROOT, data))
    rosters = data.get_current_rosters()
    for m, rb in p["rosters"].items():
        th = {x["player"]: x for x in health["teams"][m]["injured_players"]}
        assert sorted(x["name"] for x in rb["players"]) == sorted(rosters[m])
        for x in rb["players"]:
            want = ({"source": th[x["name"]]["source"], "why": th[x["name"]]["why"]}
                    if x["name"] in th else {"source": "healthy", "why": ""})
            assert x["status"] == want, x["name"]


def test_real_grid_tabs_are_the_rest_of_this_week_and_next_week(real):
    from modules.data_loader import load_all_data
    from modules.simulator_betting import schedule_week_dates
    p = real["payload"]
    wk = schedule_week_dates(load_all_data(ROOT, current_week=None))
    today = real["now"].date()
    this, nxt = p["grid"]["tabs"]
    assert [d["date"] for d in this["days"]] == [d.isoformat() for d in wk[p["week"]] if d >= today]
    assert [d["date"] for d in nxt["days"]] == [d.isoformat() for d in wk[p["week"] + 1]]
    assert nxt["label"] == "Next week" and nxt["note"].startswith("As rosters stand")


def test_real_payload_advice_is_null_and_sizes_count_apart(real):
    p = real["payload"]
    assert p["advice"] is None
    for rb in p["rosters"].values():
        assert re.fullmatch(r"Active \d+/15 \u00b7 IL \d/2", rb["size"])


@pytest.mark.skipif(not (ROOT / "output" / "hub_publish" / "index.html").exists(),
                    reason="no publish directory built on this machine (python scripts/build_hub.py)")
def test_real_publish_directory_has_no_plaintext():
    terms = hub_publish.scan_terms(ROOT)
    assert len(terms) > 100
    scan = hub_publish.scan_dir(ROOT / "output" / "hub_publish", terms)
    assert scan["files"] and scan["hits"] == {}


# --- 11-05: "remember this phone" survives the nightly rebuild ----------------

def _bundle_of(tmp_path):
    shell = (hub_publish.publish_dir(tmp_path) / "index.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'id="hub-bundle">(.*?)</script>', shell, re.S).group(1))


def test_a_remembered_phone_still_opens_the_next_nights_build(tmp_path):
    """Nick, 11-05: the hub asked for the passphrase again the morning after
    "remember this phone", because every build drew a new salt. The salt is
    now the hub's own (output/hub_salt.json): the key a phone stored from
    last night's page opens tonight's, while the IV still changes."""
    p = publish_world(tmp_path)
    hub_publish.build(tmp_path, p, PASS, terms=TERMS, iterations=1000, now=GEN)
    first = _bundle_of(tmp_path)
    stored = hub_crypto.derive_key(PASS, hub_crypto.unb64(first["salt"]), first["iter"])
    assert (tmp_path / "output" / "hub_salt.json").is_file()
    hub_publish.build(tmp_path, p, PASS, terms=TERMS, iterations=1000, now=GEN)
    second = _bundle_of(tmp_path)
    assert second["salt"] == first["salt"] and second["iv"] != first["iv"]
    assert hub_crypto.open_sealed(stored, hub_crypto.unb64(second["iv"]) + hub_crypto.unb64(second["ct"]))
    # a changed passphrase: the stored key fails, and the shell drops it and asks again
    hub_publish.build(tmp_path, p, PASS + " changed", terms=TERMS, iterations=1000, now=GEN)
    third = _bundle_of(tmp_path)
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag):
        hub_crypto.open_sealed(stored, hub_crypto.unb64(third["iv"]) + hub_crypto.unb64(third["ct"]))
    assert "function(){clearStored();return false;}" in hub_page.SHELL_JS


def test_the_hub_salt_is_created_once_and_a_malformed_one_raises(tmp_path):
    a = hub_publish.hub_salt(tmp_path)
    assert hub_publish.hub_salt(tmp_path) == a and len(a) == 16
    (tmp_path / "output" / "hub_salt.json").write_text('{"salt": 3}', encoding="utf-8")
    with pytest.raises(hub_publish.PublishError, match="malformed"):
        hub_publish.hub_salt(tmp_path)


def test_the_hub_salt_is_league_state_and_ignored():
    import subprocess
    from modules import state_manifest as sm
    rel = "output/hub_salt.json"
    assert sm.load(ROOT).contains(rel)
    r = subprocess.run(["git", "check-ignore", "--no-index", rel], cwd=str(ROOT), capture_output=True, text=True)
    assert r.stdout.split() == [rel]
