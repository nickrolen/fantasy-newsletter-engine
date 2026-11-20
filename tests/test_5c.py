"""5c (claude/HANDOFF_5C_PHONE_BUGS_2026-11-20.md): the bugs Nick found on his
phone, the text audit, the free agents' fallback team, and the phantom games.

  s.3  Champions prints the season's team NAME, never the team's dict; the v2
      renderers' clean() refuses anything that is not a string; no published
      page, part, lazy screen or card shows object text (the text audit)
  s.4  a free agent with no NBA team in the player info or PLAYERLIST gets
      basketball-reference's this-season team; it never overrides a current
      source; an untagged one keeps Next a dash and never fails the build
  s.5  the draft's "Now" shows a rated free agent's OVR (found by the audit)
  s.6  a phantom game (0 points, 1 game, every category 0, Yahoo now says
      games played 0) is corrected and recorded and the minutes' backfill
      goes on; any other disagreement still raises; the corrected day reads
      exactly as a day he did not play
  s.1, s.2 (the page): see test_5c_page.py
No network.
"""
import copy
import json
from datetime import date, timedelta

import pytest

import league_state                                    # noqa: F401
from modules import player_actuals as pa, ratings
from modules.hub_v2 import text as T, players as P, publish_check as PC, page_league as PL
from test_4a3_minutes import backfill_world, iso, MinLeague, _step
from test_4a2_category_stats import FIRST, HEADER


# =============================================================================
# s.3 clean() and the Champions name
# =============================================================================

@pytest.mark.parametrize("bad", [{"cls": "lh-t-orange", "team": "Blink-183"}, ["a"], True, False, None, 3, 2.5,
                                 b"bytes"])
def test_clean_refuses_anything_that_is_not_a_string(bad):
    with pytest.raises(T.NotAString, match="clean\\(\\) takes a payload string"):
        T.clean(bad)


def test_clean_still_strips_lore_and_escapes():
    assert T.clean("a <b> & c <!-- lore:x -->") == "a &lt;b&gt; &amp; c"


def test_every_v2_renderer_uses_the_strict_clean():
    from modules.hub_v2 import page, page_market, page_players
    for m in (page, PL, page_market, page_players):
        assert m.clean is T.clean, m.__name__


def _champ_view():
    team = {"cls": "lh-t-orange", "slot": "orange", "mono": "BL", "team": "Today's Name", "manager": "Garrett",
            "href": "#/teams/Garrett", "pic": True}
    rows = [{"season": "2019-20", "kind": "played", "m": "Garrett", "team": "Blink-183", "who": "Garrett",
             "lines": [{"k": "Runner-up", "t": "Nick (Luka)"}]},
            {"season": "2014-15", "kind": "records", "m": "Garrett", "team": "", "who": "Garrett",
             "lines": [{"k": "Records only", "t": "before the Yahoo data"}]}]
    from modules.hub_v2 import view
    h = {"champions": {"meta": "m", "note": "n", "rows": rows}}
    teams = {"Garrett": team}
    ch = dict(h["champions"], rows=[dict(r, season_team=r["team"], team=teams.get(r["m"]) if r["m"] else None)
                                    for r in h["champions"]["rows"]])
    return ch, view


def test_champions_prints_the_seasons_team_name_and_never_a_dict():
    from modules.hub_v2 import page
    import inspect
    from modules.hub_v2 import view
    src = inspect.getsource(view.league_history)
    assert 'season_team=r["team"]' in src                    # the view keeps the season's name
    ch, _ = _champ_view()
    html = PL._champions(ch, page._mono)
    txt = PC.visible_text(html)
    assert "Blink-183" in txt and "Today's Name" not in txt.split("Blink-183")[0][-40:]
    assert not PC.OBJECT_TEXT.search(txt), txt
    assert "'cls'" not in html and "{&#x27;" not in html
    # a season before the Yahoo data has no team name: the manager is the title, no empty <b>
    assert '<b class="v2-name14"></b>' not in html and html.count('<b class="v2-name14">Garrett</b>') == 1


def test_a_dict_where_the_name_goes_raises_instead_of_printing():
    from modules.hub_v2 import page
    ch, _ = _champ_view()
    ch["rows"][0]["season_team"] = ch["rows"][0]["team"]          # the 11-20 bug: the dict as the name
    with pytest.raises(T.NotAString):
        PL._champions(ch, page._mono)


# =============================================================================
# s.5 the text audit itself
# =============================================================================

@pytest.mark.parametrize("html", [
    "<p>{'cls': 'lh-t-orange'}</p>", "<td>None</td>", "<span>[object Object]</span>", "<b>undefined</b>",
    "<td>NaN</td>", '<button data-tip-b="x True}">i</button>', '<script type="application/json" id="v2-cmp">'
    '{"rows": {"a": {"name": "False}"}}}</script>'])
def test_the_audit_finds_object_text_in_text_attributes_and_data(html):
    a = PC.text_audit({"x": html})
    assert len(a["object_hits"]) == 1, a


@pytest.mark.parametrize("html", ["<p>Paul George ( )</p>", "<p>A &middot; <b></b> &middot; B</p>"])
def test_the_audit_finds_empty_values(html):
    assert len(PC.text_audit({"x": html})["empty_hits"]) == 1


def test_the_audit_ignores_scripts_styles_and_ordinary_words():
    html = ("<style>.x{content:'None'}</style><script>var a=undefined,b=NaN;</script>"
            "<p>Nonetheless, Undefined-ish words and Nancy (NOP) are fine</p><td></td><td>\u2014</td>")
    a = PC.text_audit({"x": html})
    assert a["object_hits"] == [] and a["empty_hits"] == [] and a["empty_cells"] == 1 and a["dash_cells"] == 1


# =============================================================================
# s.4 the free agents' fallback team
# =============================================================================

def test_the_reference_is_a_fallback_only():
    ref = {"Evan Mobley": "CLE", "Paul George": "LAC"}
    info = {"Paul George": {"nba_team": "PHI"}}
    proj = {}
    assert P.fa_team("Evan Mobley", info, proj, ref) == "CLE"                   # neither source: the reference
    assert P.fa_team("Paul George", info, proj, ref) == "PHI"                   # the player info wins
    assert P.fa_team("Kel Ware", {}, {"Kel Ware": {"player_nba_team": "MIA"}}, {"Kel Ware": "OKC"}) == "MIA"
    assert P.fa_team("Nobody", {}, {}, ref) is None and P.fa_team("Evan Mobley", {}, {}, None) is None


def test_reference_teams_reads_this_season_only_and_no_file_is_no_fallback(tmp_path):
    (tmp_path / "data").mkdir()
    assert dict(P.reference_teams(tmp_path)) == {}
    (tmp_path / "data" / "NBA_PLAYER_REFERENCE.json").write_text(json.dumps({"seasons": {
        "last_completed": {"players": {"Old Guy": "BOS", "Evan Mobley": "PHI"}},
        "this_season": {"players": {"Evan Mobley": "cle", "Two Teams": None}}}}))
    ref = P.reference_teams(tmp_path)
    assert dict(ref) == {"Evan Mobley": "CLE"} and ref.get("Old Guy") is None


def test_an_untagged_fallback_free_agent_never_fails_the_build():
    """The 11-20 tag record has no tag for Mobley or Jalen Williams (they are
    not in PLAYERLIST, where the free agents' tags come from): free_agent_tags
    raises for them, and the Players rows must not. players.build skips the
    tag for such a player (Next stays a dash); the rest still must have tags."""
    import inspect
    src = inspect.getsource(P.build)
    assert "except HubInputError" in src and "fa_info[n]" in src
    assert "extra_info=fa_info" in src


# =============================================================================
# s.5 the draft's "Now" for a rated free agent
# =============================================================================

def test_the_draft_now_shows_a_rated_free_agents_ovr():
    import inspect
    from modules.hub_v2 import league
    src = inspect.getsource(league.gather)
    assert 'ratings.get("free_agents")' in src and "now_ovr.setdefault(n, p[\"ovr\"])" in src
    assert '"not on a roster today: free agents have no OVR"' not in inspect.getsource(league)


# =============================================================================
# s.6 the phantom games
# =============================================================================

def _phantom_world(tmp_path, pid=1, day=1, shape="phantom", gp_now=0):
    """backfill_world with player `pid`'s day `day` cached in `shape`, and
    Yahoo now saying games played gp_now for it:
      phantom   [0.0, 1], every category 0
      played    the day as fetched: real points and categories
      corrected [0.0, 1], categories that score Yahoo's total now (a stat
                correction kept in cat_corrections: Zion Williamson, 11-14)
      nocats    [0.0, 1], no categories cached yet"""
    b, lines, mins, lg = backfill_world(tmp_path, n_players=5, n_days=4, idle=lambda p, i: False)
    blob = pa.load(b)
    rec = blob["players"][str(pid)]
    if shape == "phantom":
        rec["days"][iso(day)] = [0.0, 1]
        rec["cat_days"][iso(day)] = [0] * len(HEADER["order"])
    elif shape == "corrected":
        rec["cat_corrections"] = {iso(day): rec["days"][iso(day)][0]}
        rec["days"][iso(day)] = [0.0, 1]
    elif shape == "nocats":
        rec["days"][iso(day)] = [0.0, 1]
        rec["cat_days"].pop(iso(day))
    pa.write(b, blob, FIRST + timedelta(days=4))
    lg.gp_now[(pid, iso(day))] = gp_now
    return b, lg


def test_a_phantom_game_is_corrected_recorded_and_the_backfill_goes_on(tmp_path):
    b, lg = _phantom_world(tmp_path)
    r = pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    assert r["days_done"] == [iso(i) for i in range(4)] and r["days_left"] == 0
    assert r["corrections"] == [f"Player 1 {iso(1)}: a phantom game (games played 1 with no stats when fetched; "
                                "Yahoo now says 0): rewritten as no game"]
    rec = pa.load(b)["players"]["1"]                                  # validate() passes on the load
    assert rec["days"][iso(1)] == [0.0, 0] and rec["cat_days"][iso(1)] == [0] * 11 and rec["min_days"][iso(1)] == 0
    # never asked again: neither backfill plans the day
    blob = pa.load(b)
    assert pa.backfill_plan(blob, FIRST + timedelta(days=3), key="min_days") == {}
    assert pa.backfill_plan(blob, FIRST + timedelta(days=3), key="cat_days") == {}
    n = len(lg.game_calls)
    assert pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))["calls"] == 0
    assert len(lg.game_calls) == n


@pytest.mark.parametrize("shape", ["played", "corrected", "nocats"])
def test_any_other_disagreement_still_raises_and_writes_nothing_for_the_day(tmp_path, shape):
    b, lg = _phantom_world(tmp_path, shape=shape)
    before = pa.load(b)["players"]["1"]["days"][iso(1)]
    with pytest.raises(pa.MinutesError, match=f"{iso(1)} line for Player 1 now says games played '0', but the "
                                              "cache has him playing"):
        pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    after = pa.load(b)["players"]["1"]
    assert after["days"][iso(1)] == before and iso(1) not in (after.get("min_days") or {})


def test_a_stat_corrected_zero_day_is_not_a_phantom():
    rec = {"days": {"d": [0.0, 1]}, "cat_days": {"d": [0] * 11}, "cat_corrections": {"d": 32.8}}
    assert not pa.is_phantom(rec, "d")
    with pytest.raises(pa.ActualsError, match="not a phantom game"):
        pa.correct_phantom(rec, "d", 11)


def test_the_corrected_day_reads_as_if_he_had_not_played(tmp_path):
    b, lg = _phantom_world(tmp_path)
    phantom = pa.load(b)
    pa.backfill_minutes(b, source=pa.YahooSource(lg), today=FIRST + timedelta(days=4))
    fixed = pa.load(b)
    never = copy.deepcopy(fixed)                    # the same cache with the day never a game at all
    never["players"]["1"]["days"][iso(1)] = [0.0, 0]
    last = FIRST + timedelta(days=3)
    name = fixed["players"]["1"]["name"]
    fixed["roster_names"] = never["roster_names"] = phantom["roster_names"] = {name: 1}
    p_pts, p_gp = pa.season(phantom, name, last)
    f_pts, f_gp = pa.season(fixed, name, last)
    assert (f_pts, f_gp) == pa.season(never, name, last) and f_gp == p_gp - 1 and f_pts == p_pts
    dates = {"BOS": [iso(i) for i in range(4)]}
    fs = ratings.nba_season(fixed, dates, iso(3))(name, "BOS")
    ps = ratings.nba_season(phantom, dates, iso(3))(name, "BOS")
    assert fs["games"] == ps["games"] - 1 and fs["team_games"] == 4 and 0.0 not in fs["scores"]
    assert fs["fppg"] > ps["fppg"]                                       # the 0-point game is gone
    assert fs["games"] / fs["team_games"] < ps["games"] / ps["team_games"]   # availability: one game fewer
    cs = pa.category_season(fixed, name, FIRST, last)
    assert cs == pa.category_season(never, name, FIRST, last)


def test_the_nightly_records_the_corrections(tmp_path, monkeypatch):
    ok = {"days_done": [iso(0)], "days_left": 0, "calls": 1, "cap": 20, "stopped": None,
          "corrections": ["Zed 2026-10-20: a phantom game (...): rewritten as no game"]}
    run, detail, called = _step(tmp_path, monkeypatch, "nightly", lambda: dict(ok, seconds=0.1, days_missing=1))
    assert run.ctx["actuals"]["minutes"]["backfill"]["corrections"] == ok["corrections"]
    assert "1 phantom game(s) corrected" in detail
    assert run.ctx["actuals_lines"] == ["PHANTOM GAME CORRECTED: " + ok["corrections"][0]]
    assert run.ctx["actuals"]["minutes"]["error"] is None


def test_the_category_backfill_never_reads_games_played():
    """The only read-back of the games count is the minutes' backfill: the
    category backfill's league-scoped line has no stat 0, and the daily
    passes never refetch a day (so a corrected day cannot come back)."""
    import inspect
    assert "GP_STAT" not in inspect.getsource(pa.YahooSource.cats_day)
    assert "GP_STAT" not in inspect.getsource(pa.backfill_categories)
    src = inspect.getsource(pa.plan)
    assert "not in have" in src


# =============================================================================
# the real thing, unstubbed (skips without state)
# =============================================================================

def test_real_the_cache_holds_the_three_phantoms_and_nothing_else_of_their_shape():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if not (root / pa.CACHE_RELPATH).is_file():
        pytest.skip("no data/player_actuals.json here")
    blob = pa.load(root)
    found = sorted((rec["name"], d) for rec in blob["players"].values() for d in rec["days"] if pa.is_phantom(rec, d))
    # 11-20: the three the reviewer found. A later night may correct them (0) or add one: then read the run row.
    assert len(found) <= 6, found
    for rec in blob["players"].values():
        for d, v in rec["days"].items():
            if int(v[1]) == 1 and float(v[0]) == 0.0:
                assert pa.is_phantom(rec, d) or d in (rec.get("cat_corrections") or {}), (rec["name"], d)


from test_5b import real                                       # noqa: E402,F401 -- the real build, once


@pytest.mark.slow
def test_real_the_fallback_team_reaches_only_free_agents_without_one_and_overrides_nothing(real):
    import pandas as pd
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    p, po, ro = real
    ref = P.reference_teams(root)
    pl = pd.read_excel(root / "data" / "PLAYERLIST.xlsx")
    plt = {str(r.player_name): str(r.player_nba_team).upper() for r in pl.itertuples()
           if isinstance(r.player_nba_team, str)}
    for z in po["players"]["rows"]:
        if z["kind"] != "fa":
            continue
        if z["name"] in plt:
            assert z["nba"] == plt[z["name"]], z["name"]                       # a current source wins
        elif ref.get(z["name"]):
            assert z["nba"] == ref.get(z["name"]), z["name"]                   # the fallback
            f = ro["result"]["free_agents"][z["name"]]
            assert f["nba_team"] == z["nba"] and (f["ovr"] is not None or f["ovr_reason"]), z["name"]
            assert "no NBA team on record" not in str(f.get("ovr_reason"))


@pytest.mark.slow
def test_real_no_object_text_in_the_published_hub(real, tmp_path):
    from modules import hub_cards, team_pictures
    from modules.hub_v2 import data as v2data
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    p, po, ro = real
    pub = v2data.attach_players(copy.deepcopy(p), po)
    cards = hub_cards.build(root, p, echo=lambda *a, **k: None)
    pics, _n = team_pictures.data_uris(root, list(pub["v2"]["team_order"]))
    rep = PC.check(root, pub, cards, tmp_path / "check" / "publish", pictures=pics)
    a = rep["text_audit"]
    assert rep["ok"] and a["object_hits"] == [] and a["empty_hits"] == [], rep["problems"]
    assert a["pieces"] >= 50 and a["chars"] > 100_000
