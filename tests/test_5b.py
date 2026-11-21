"""5b (claude/HANDOFF_5B_FA_RATINGS_AND_FIRST_LOAD_2026-11-20.md s.5): the free
agents' OVR and POT, the unproven players' prior (s.1a), the bottom of the
scale (s.1b), the first load (lazy screens, the picture split, the lazy
chart and older moves), the stored payload under v2, and the two parity gaps
(the games grid's Idle and dagger, Moves' adds used). Synthetic where the rule
is logic; the real, unstubbed tests are slow and skip without the state.
Made-up names only, except in the real tests (which print none)."""

import copy
import html as _html
import json
import math
import re
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import league_state                                    # noqa: E402,F401
from test_hub_v2 import (synth_payload, render, visible_text, GEN, PASS, TERMS, ROOT, FA_NAME, MGRS, _archive,
                         budget_bytes)

from modules import ratings
from modules.hub_v2 import (players as P, publish as v2pub, data as v2data, page, page_market as PM,
                            market as v2market, view, publish_check as pc)

DASH = "—"
AS_OF = "2026-11-19"
LAST = "2027-04-11"


# =============================================================================
# a made-up ratings result to rate free agents against (rate()'s shape)
# =============================================================================

def _days(first: str, n: int, step: int = 2) -> list:
    d0 = date.fromisoformat(first)
    return [(d0 + timedelta(days=step * i)).isoformat() for i in range(n)]


def _result(R: float = 24.0, prior: float = 24.0, previous: dict = None) -> dict:
    from modules import keepability_v3 as M
    cfg = ratings.config()
    lp = M.level_config(M.load_params())
    dbt = {"AAA": _days("2026-10-20", 80), "BBB": _days("2026-10-21", 80)}
    universe = [float(i * 50) for i in range(40)]              # the rostered players' composites
    raw = {k: {f"R{i}": float(i) for i in range(20)} for k in ratings.COMPUTED_GRADES}
    basis = {"cfg": cfg, "lp": lp, "R": R, "unproven_prior": prior, "mean_av": 0.9, "sd_med": 10.0,
             "league_mean": 35.0, "season_over": False, "dates_by_team": dbt,
             "horizon": ("2026-11-20", "2026-12-13"), "values": None, "actuals": None,
             "previous": dict(previous or {}), "raw": raw,
             "history": None, "arch_ref": None, "skill_ctx": None, "unproven_rule": False}   # 4a's OVR, no 5b rule
    return {"as_of": AS_OF, "season": "2026-27", "last_day": LAST, "players": {"R0": {"ovr": 60}},
            "knots": {"ovr": ratings.knots(universe, cfg["ovr"]["anchors"]),
                      "pot": ratings.knots([float(30 + i) for i in range(40)], cfg["pot"]["anchors"])},
            "free_agents": None, "basis": basis}


def _spec(name="New Guy", fppg=40.0, games=15, team_games=15, prev_lines=(), drafted=False, age=24, team="AAA"):
    return {"name": name, "team": team, "games": games, "fppg": fppg, "team_games": team_games,
            "scores": [fppg + (3.0 if i % 2 else -3.0) for i in range(games)], "prev_lines": list(prev_lines),
            "prior_av": (0, 0), "drafted": drafted, "age": age}


# =============================================================================
# s.1 free agents
# =============================================================================

def test_rating_free_agents_never_moves_a_rostered_player():
    res = _result()
    before = copy.deepcopy({k: res[k] for k in ("players", "knots")})
    before_basis = copy.deepcopy({k: v for k, v in res["basis"].items() if k not in ("cfg", "lp")})
    out = ratings.rate_free_agents(res, [_spec(), _spec("Old Hand", prev_lines=[("2025-26", 60, 38.0)])])
    assert set(out) == {"New Guy", "Old Hand"}
    assert {k: res[k] for k in ("players", "knots")} == before
    assert {k: v for k, v in res["basis"].items() if k not in ("cfg", "lp")} == before_basis


def test_a_free_agents_availability_is_his_nba_games_over_his_teams():
    res = _result()
    f = ratings.rate_free_agents(res, [_spec(games=12, team_games=16)])["New Guy"]
    c = f["components"]
    k0 = ratings.config()["ovr"]["availability_k0"]
    assert c["games"] == 12 and c["team_games"] == 16 and c["source"] == "NBA season"
    assert c["availability"] == pytest.approx((12 + k0 * 0.9) / (16 + k0))      # A0: the rostered mean
    assert c["games_remaining"] == sum(1 for d in res["basis"]["dates_by_team"]["AAA"] if AS_OF < d <= LAST)


def test_nba_season_counts_every_nba_game_and_his_teams_games():
    days = {d: [30.0, 1] if i % 4 else [0.0, 0] for i, d in enumerate(_days("2026-10-20", 31, 1))}
    blob = {"first_day": "2026-10-20", "roster_names": {}, "extra_names": {"Free Guy": 7},
            "players": {"7": {"name": "Free Guy", "days": days}}}
    dbt = {"AAA": _days("2026-10-20", 16)}
    st = ratings.nba_season(blob, dbt, "2026-11-19")("Free Guy", "AAA")
    played = sum(1 for i in range(31) if i % 4)
    assert st["games"] == played and st["fppg"] == pytest.approx(30.0)
    assert st["team_games"] == sum(1 for d in dbt["AAA"] if "2026-10-20" <= d <= "2026-11-19")
    assert ratings.nba_season(blob, dbt, "2026-11-20")("Free Guy", "AAA") is None     # a day not cached
    assert ratings.nba_season(blob, dbt, "2026-11-19")("Free Guy", "ZZZ") is None     # no such team


def test_a_free_agent_the_inputs_cannot_rate_says_why():
    sp = {"name": "No Team", "team": None, "age": None, "reason": "no NBA team on record"}
    f = ratings.rate_free_agents(_result(), [sp])["No Team"]
    assert f["ovr"] is None and f["pot"] is None and f["ovr_reason"] == "no NBA team on record"
    assert all(g["letter"] is None for g in f["grades"].values())


def test_free_agents_grades_are_percentiles_among_the_rostered_players():
    assert ratings.pct_among([1.0, 2.0, 3.0, 4.0], 2.0) == 37.5            # a rostered player's own value
    assert ratings.percentiles({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0})["b"] == 37.5
    assert ratings.pct_among([1.0, 2.0], 9.0) == 100.0 and ratings.pct_among([1.0, 2.0], 0.0) == 0.0


def test_the_history_line_carries_the_free_agents_and_old_lines_still_read(tmp_path):
    res = _result()
    res["players"] = {"Ros Ter": {"ovr": 80, "pot": 81, "components": {"level": 40.0, "availability": 0.9,
                                                                      "games_remaining": 60}}}
    res["free_agents"] = ratings.rate_free_agents(res, [_spec()])
    line = ratings.history_line(res)
    assert set(line["ovr"]) == {"Ros Ter", "New Guy"} and line["fa"] == ["New Guy"]
    assert "New Guy" in line["terms"] and "New Guy" in line["pot"]
    old = {"as_of": "2026-11-05", "season": "2026-27", "ovr": {"Ros Ter": 78}, "pot": {"Ros Ter": 80},
           "terms": {}}                                                  # before 5b: no "fa"
    (tmp_path / "output").mkdir()
    (tmp_path / ratings.HISTORY_RELPATH).write_text(json.dumps(old) + "\n", encoding="utf-8")
    ratings.append_history(tmp_path, dict(line, as_of="2026-11-12"))
    lines = ratings.read_history(tmp_path)
    assert [l["as_of"] for l in lines] == ["2026-11-05", "2026-11-12"] and "fa" not in lines[0]
    assert ratings.previous_from_history(lines, "2026-11-19") == {"Ros Ter": 80, "New Guy": line["ovr"]["New Guy"]}


def test_a_free_agent_gets_his_weekly_change_from_last_weeks_line():
    f = ratings.rate_free_agents(_result(previous={"New Guy": 60}), [_spec()])["New Guy"]
    assert f["ovr_change"] == f["ovr"] - 60
    assert ratings.rate_free_agents(_result(), [_spec()])["New Guy"]["ovr_change"] is None   # no line: no marker


def test_a_rostered_risers_reason_ranks_him_among_the_rostered_players_only():
    then = {"A": [40.0, 0.80, 60], "B": [41.0, 0.90, 60], "C": [42.0, 0.85, 60]}
    now = {"A": [43.0, 0.80, 57], "B": [41.0, 0.90, 57], "C": [42.0, 0.85, 57]}
    base = P.riser_reason("A", now, then)
    then2, now2 = dict(then, F=[50.0, 0.5, 60]), dict(now, F=[30.0, 0.9, 57])         # a free agent in both
    assert P.riser_reason("A", now2, then2, pool={"A", "B", "C"}) == base
    assert P.riser_reason("F", now2, then2, pool={"A", "B", "C", "F"}).startswith("playing more")


# =============================================================================
# s.1a unproven players
# =============================================================================

def test_who_is_unproven():
    assert ratings.is_unproven(SimpleNamespace(prev_lines=[], undrafted=True))
    assert not ratings.is_unproven(SimpleNamespace(prev_lines=[], undrafted=False))           # drafted (or kept)
    assert not ratings.is_unproven(SimpleNamespace(prev_lines=[("2025-26", 30, 25.0)], undrafted=True))


def test_the_unproven_rule_is_retired_by_the_skill_ovr():
    """4a4 s.2: the skill OVR rates a player with no NBA record from his draft
    slot (undrafted: pick 60), so 5b's unproven prior is retired: the config
    block is gone and asking for the rule raises, naming why."""
    cfg = ratings.config()
    assert "unproven" not in cfg
    with pytest.raises(ratings.RatingsInputError, match="retired by 4a4"):
        ratings.rate(SimpleNamespace(), None, {}, "2027-04-11", cfg=cfg, unproven_rule=True)
    out = ratings.rate_free_agents(_result(), [_spec("Hot New", fppg=40.0)])
    assert not out["Hot New"]["components"]["unproven"]            # 4a's OVR without the rule: the league mean
    assert out["Hot New"]["components"]["prior_kind"] == "league mean"


def test_shrink_is_keepability_v3s_rule():
    assert ratings.shrink(40.0, 0, 24.0, 15) == 24.0 and ratings.shrink(None, 3, 24.0, 15) == 24.0
    assert ratings.shrink(40.0, 15, 24.0, 15) == pytest.approx(32.0)


# =============================================================================
# s.1b the bottom of the scale
# =============================================================================

def _linear(value, kn, lo, hi):
    xs, ys = [], []
    for x, y in kn:
        if xs and x <= xs[-1]:
            continue
        xs.append(x); ys.append(y)
    i = 0 if value <= xs[0] else (len(xs) - 2 if value >= xs[-1] else max(j for j in range(len(xs) - 1) if xs[j] <= value))
    v = ys[i] + (value - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
    return int(math.floor(min(max(v, lo), hi) + 0.5))


def test_no_pile_up_at_the_floor_and_no_rostered_rating_moves():
    universe = [float(i * 30) for i in range(60)]
    kn = ratings.knots(universe, [[0, 60], [50, 78], [90, 90], [100, 99]])
    for x in universe + [x + 0.5 for x in universe]:              # at or above the rostered minimum: unchanged
        assert ratings.scale(x, kn, 40, 99) == _linear(x, kn, 40, 99)
    below = [-300.0 * i for i in range(1, 7)]
    olds = [_linear(x, kn, 40, 99) for x in below]
    news = [ratings.scale(x, kn, 40, 99) for x in below]
    assert olds.count(40) >= 3                                    # the old rule piles them on the floor
    assert 40 not in news and len(set(news)) == len(news)         # distinct composites, distinct ratings
    assert news == sorted(news, reverse=True)
    # unrounded, it keeps falling and never reaches the floor (far out, two may round alike)
    far = [ratings.scale(-300.0 * i, kn, 40, 99) for i in range(1, 40)]
    assert min(far) >= 40 and far == sorted(far, reverse=True)


def test_equal_ovrs_sort_by_the_composite_underneath(monkeypatch):
    import test_hub_v2 as T
    real = T.synth_ratings

    def tie(r, prev):
        res = real(r, prev)
        names = sorted(res["players"])[:2]
        for n, c in zip(names, (500.0, 900.0)):
            res["players"][n].update(ovr=70, ovr_composite=c)
        return res
    monkeypatch.setattr(T, "synth_ratings", tie)
    p = T.synth_payload()
    rows = p["v2"]["players"]["rows"]
    a, b = sorted(T.synth_ratings(p["rosters"], True)["players"])[:2]
    d = [rows[i]["name"] for i in p["v2"]["players"]["orders"]["ovr"]["d"]]
    assert d.index(b) < d.index(a)                                # the higher composite first
    asc = [rows[i]["name"] for i in p["v2"]["players"]["orders"]["ovr"]["a"]]
    assert asc.index(a) < asc.index(b)


# =============================================================================
# s.2 the first load
# =============================================================================

def _published(tmp_path, pics=None):
    e = _archive(tmp_path)
    p = synth_payload()
    p["v2"]["issue"]["file"] = e["enc"]
    out = tmp_path / "_to_delete" / "5b" / "publish"
    rep = v2pub.build(tmp_path, p, PASS, salt=b"\x05" * 16, out_dir=out, iterations=1000, terms=TERMS, now=GEN,
                      pictures=pics or {})
    sh = (out / "index.html").read_text(encoding="utf-8")
    inner = v2pub.open_inner(PASS, json.loads(re.search(r'id="hub-bundle">(.*?)</script>', sh, re.S).group(1)))
    return p, out, rep, inner["page"]


def test_team_pages_and_last_weeks_matchups_are_lazy_screens(tmp_path):
    p, out, rep, pg = _published(tmp_path)
    routes = {f"teams/{m}" for m in MGRS} | {c["route"] for c in (p["v2"].get("last") or {}).get("cards") or []
                                             if "route" in c}
    shells = dict(re.findall(r'<section class="v2-screen" data-route="([^"]+)"[^>]*data-screen-part=\'([^\']*)\'', pg))
    assert {f"teams/{m}" for m in MGRS} <= set(shells)
    for r, raw in shells.items():
        h = pc.open_part(out, json.loads(_html.unescape(raw)))["html"]
        assert 'class="v2-topbar"' in h and len(h) > 500
        sec = re.search(rf'data-route="{re.escape(r)}"[^>]*>(.*?)</section>', pg, re.S).group(1)
        assert "Opening&hellip;" in sec and 'data-section="roster"' not in sec       # only the shell inline
    assert "function lazyScreen(" in pg and "if(lazyScreen(target))" in pg
    assert len(rep["screen_parts"]) == len(shells)


def test_the_title_odds_chart_and_older_moves_are_lazy_parts(tmp_path):
    p, out, rep, pg = _published(tmp_path)
    assert 'data-chart="lg-odds"' not in pg and 'data-lhpart-of="odds"' in pg
    ref = re.search(r'data-lhpart-of="odds" data-part=\'([^\']*)\'', pg).group(1)
    assert 'data-chart="lg-odds"' in pc.open_part(out, json.loads(_html.unescape(ref)))["html"]
    mref = re.search(r'data-mvolder-of="1" data-part=\'([^\']*)\'', pg).group(1)
    older = pc.open_part(out, json.loads(_html.unescape(mref)))["html"]
    assert "Week 8" in older and "v2-mv-over" in older and "Week 8" not in pg.split('data-mvolder-of')[0][-3000:]
    assert "window.lgOdds" in pg and "function mvOlder(" in pg


def test_preview_keeps_everything_inline():
    h = render(synth_payload())
    assert "data-screen-part='" not in h and 'data-chart="lg-odds"' in h and 'id="v2-mk-older"' in h


# =============================================================================
# s.3 the stored payload under v2
# =============================================================================

def _fixed_iv(monkeypatch):
    from modules import hub_crypto
    monkeypatch.setattr(hub_crypto, "secrets", SimpleNamespace(token_bytes=lambda n: b"\x07" * n))


def _files(d: Path) -> dict:
    return {str(f.relative_to(d)): f.read_bytes() for f in sorted(d.rglob("*")) if f.is_file()}


def test_store_v2_drops_only_what_no_v2_reader_reads_and_the_publish_is_byte_identical(tmp_path, monkeypatch):
    _fixed_iv(monkeypatch)
    e = _archive(tmp_path)
    p = synth_payload()
    p["v2"]["issue"]["file"] = e["enc"]
    p["grid"] = {"tabs": [], "legend": {}, "foot": ""}
    p["power"]["chart"] = {"lines": [1, 2, 3]}
    p["power"]["chart_title"] = "Title odds"
    p["advice_empty"] = "x"
    p["matchup_views"].append({"id": "v-unread-win", "paras": ["never read by v2"]})
    q = copy.deepcopy(p)
    dropped = v2data.store_v2(q)
    assert set(dropped) >= {"grid", "power.chart", "power.chart_title", "advice_empty"}
    assert "grid" not in q and "chart" not in q["power"] and q["v2_store"]["dropped"] == sorted(dropped)
    assert all(v["id"] != "v-unread-win" for v in q["matchup_views"])
    from modules import hub_cards
    assert hub_cards.shown_names(q) == hub_cards.shown_names(p)
    for x, d in ((p, "a"), (q, "b")):
        v2pub.build(tmp_path, x, PASS, salt=b"\x01" * 16, out_dir=tmp_path / d, iterations=1000, terms=TERMS, now=GEN)
    assert _files(tmp_path / "a") == _files(tmp_path / "b")


def test_the_current_page_refuses_a_payload_stored_under_v2(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_hub
    from modules import hub_version, hub_state, hub_archive
    q = synth_payload()
    v2data.store_v2(q)
    sp = tmp_path / "state.json"
    sp.write_text(json.dumps(q), encoding="utf-8")
    monkeypatch.setattr(hub_version, "version", lambda base=None, cfg=None: "v1")
    monkeypatch.setattr(hub_archive, "verify", lambda base: {"issues": []})
    with pytest.raises(hub_state.HubInputError, match="stored under hub.version v2"):
        build_hub.run(ROOT, state=sp, out_dir=tmp_path / "o", echo=lambda *a, **k: None)


# =============================================================================
# s.4 parity: the games grid's Idle and dagger, Moves' adds used
# =============================================================================

def test_the_games_grid_has_its_idle_column_and_the_nba_report_mark():
    h = render(synth_payload())
    grid = re.search(r'data-section="grid"(.*?)</section>', h, re.S).group(1)
    assert "<span>Idle</span>" in grid and "†" in grid
    assert "out tonight on the NBA&#x27;s injury report" in grid or "out tonight on the NBA's injury report" in grid


def test_moves_has_each_weeks_adds_used_over_the_budget_in_red():
    mv = synth_payload()["moves"]
    out = v2market.moves(mv, list(MGRS), date(2026, 10, 20))
    assert [w["key"] for w in out["weeks"]] == ["9", "8"]                     # newest first
    over = [u for w in out["weeks"] for u in (w["used"] or []) if u["over"]]
    assert over and over[0]["m"] == "Tyler"
    h = render(synth_payload())
    mk = h[h.index('id="mk-moves"'):]
    assert "Adds used:" in mk and 'data-ms="Marcus"' in mk
    older = PM.moves_older_html(view.build(synth_payload(), mode="preview", now=GEN)["market"]["moves"])
    assert 'class="v2-mv-over">Tyler 4 of 3 (over)' in older


# =============================================================================
# the real, unstubbed tests (slow; skip without the state)
# =============================================================================

@pytest.fixture(scope="module")
def real():
    from modules import hub_state as hs, player_actuals
    from modules.league_clock import league_now
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_latest.json",
              ROOT / "config" / "ROSTERS.json", ROOT / "output" / "hub_archive" / "index.json"]
    if not all(q.exists() for q in needed):
        pytest.skip("no league state on this machine")
    league_state.skip_if_actuals_behind()
    try:
        po, ro = {}, {}
        p = hs.build(ROOT, now=league_now(), allow_engine_mismatch=True, echo=lambda *a, **k: None,
                     players_out=po, ratings_out=ro)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        pytest.skip(f"the hub's real inputs are not current today ({e})")
    return p, po, ro


@pytest.mark.slow
def test_real_free_agents_are_rated_on_the_rostered_players_scale(real):
    p, po, ro = real
    res = ro["result"]
    assert ro.get("fa_error") is None and res["free_agents"]
    fas = res["free_agents"]
    rated = [f for f in fas.values() if f["ovr"] is not None]
    rows = [z for z in po["players"]["rows"] if z["kind"] == "fa"]
    assert len(rated) >= len(rows) - 5 and all(z["name"] in fas for z in rows)
    assert all(f["ovr"] > 40 for f in rated) and all(f["pot"] is None or f["pot"] > 40 for f in fas.values())
    xs = [f["ovr_composite"] for f in rated]
    ys = [f["components"]["fppg"] or 0.0 for f in rated]
    rk = lambda v: [sorted(v).index(x) for x in v]
    assert statistics.correlation(rk(xs), rk(ys)) > 0.2                   # OVR follows FPPG, loosely
    # 4a4: the skill OVR is the same rule for both: a rostered player rated as a free agent
    # (his NBA season in place of the league log) lands within a point of his rostered OVR
    from modules import keeper_history as kh
    live = kh.live_inputs(ROOT)
    ages = kh.load_ages(kh.age_seasons(), ROOT, fetch=ratings._nofetch)
    ros = sorted((n for n, r in res["players"].items() if r["ovr"] is not None and r["nba_team"]),
                 key=lambda n: -res["players"][n]["ovr"])[:8]
    sp = ratings.free_agent_specs(ros, {n: res["players"][n]["nba_team"] for n in ros}, live[0], live[1],
                                  res["basis"]["actuals"], res["basis"]["dates_by_team"], res["as_of"], ages)
    got = ratings.rate_free_agents(res, sp)
    off = {n: (got[n]["ovr"], res["players"][n]["ovr"]) for n in ros
           if got[n]["ovr"] is None or abs(got[n]["ovr"] - res["players"][n]["ovr"]) > 1}
    assert not off, off
    # the history line carries them, named
    assert set(ro["line"]["fa"]) <= set(fas) and set(ro["line"]["ovr"]) >= set(res["players"]) - {
        n for n, r in res["players"].items() if r["ovr"] is None}


@pytest.mark.slow
def test_real_rostered_players_outside_1a_are_untouched_by_the_free_agents(real):
    p, po, ro = real
    res = copy.deepcopy({k: v for k, v in ro["result"].items() if k not in ("basis", "free_agents")})
    again = ratings.rate_free_agents(ro["result"], [])
    assert again == {}
    assert {k: ro["result"][k] for k in res} == res


@pytest.mark.slow
def test_real_first_load_and_payload_have_their_room(real, tmp_path):
    from modules import hub_cards, team_pictures
    p, po, ro = real
    pub = v2data.attach_players(copy.deepcopy(p), po)
    cards = hub_cards.build(ROOT, p, echo=lambda *a, **k: None)
    pics, _n = team_pictures.data_uris(ROOT, list(pub["v2"]["team_order"]))
    rep = pc.check(ROOT, pub, cards, tmp_path / "check" / "publish", pictures=pics)
    assert rep["ok"], rep["problems"]
    assert rep["first_load"] <= 240_000
    assert rep["opened"]["screens"] >= 4 and rep["opened"]["pictures"] == len(pics)
    stored = copy.deepcopy(p)
    v2data.store_v2(stored)
    assert len(json.dumps(stored)) <= 300_000                             # 25% under test_hub_polish3's cap
    # no free agent on the floor, and distinct composites below the rostered minimum rate distinctly
    fas = [f for f in ro["result"]["free_agents"].values() if f["ovr"] is not None]
    assert not [f for f in fas if f["ovr"] <= 40]
