"""Task 39 (claude/HANDOFF_HUB_POLISH_2026-11-04.md): the hub's free agents
(status, playable games, the two-week ranking) and the moves feed's colours
and markers. Synthetic where the rule is logic; on the real data where the
point is Kawhi Leonard's real entry (state-dependent tests skip with the
reason, as test_hub's real build does)."""

import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from modules import hub_state as hs, hub_page, hub_publish, transaction_log as tlog  # noqa: E402
from test_transaction_log import _sync, ADD, ADD_DROP, DROP, TRADE, SCHEDULE  # noqa: E402
from test_hub import sample_payload, GEN, visible_text, payload_strings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
D = lambda m, d: date(2026, m, d)                                   # noqa: E731
WEEK3 = [D(11, 2) + timedelta(days=i) for i in range(7)]            # Mon 11-02 .. Sun 11-08
WEEK4 = [D(11, 9) + timedelta(days=i) for i in range(7)]            # Mon 11-09 .. Sun 11-15
WEEKS = {2: (D(10, 26), D(11, 1)), 3: (WEEK3[0], WEEK3[-1]), 4: (WEEK4[0], WEEK4[-1]),
         5: (D(11, 16), D(11, 22))}


def fa_world(tags, overrides=(), today=D(11, 2), dates=None):
    """Free agents F0..Fn-1, each on his own team playing every day of weeks
    3 and 4 unless `dates` says otherwise; the hub's Availability, built for
    free agents as the build does it."""
    names = sorted(tags)
    info = {n: {"nba_team": f"T{n}", "positions": {"SF"}, "proj_fppg": 30.0} for n in names}
    team_dates = {f"T{n}": set((dates or {}).get(n, WEEK3 + WEEK4)) for n in names}
    base = hs.Availability({}, {}, {}, {"players": list(overrides)}, 3, info, team_dates, WEEKS, today)
    return base.for_free_agents(names, tags)


def rest(today):
    return [d for d in WEEK3 if d >= today], WEEK4


# =============================================================================
# 1. GL and Next count playable games: the grid's rule, shared
# =============================================================================

def test_an_override_returning_mid_week_counts_only_the_games_after_it():
    back_thu = {"player_name": "F0", "out_weeks": [2], "return_week": 3, "return_date": "2026-11-05"}
    av = fa_world({"F0": "HEALTHY"}, [back_thu])
    this, nxt = rest(D(11, 2))
    assert av.playable("F0", this) == [D(11, 5), D(11, 6), D(11, 7), D(11, 8)]
    assert len(av.playable("F0", nxt)) == 7


def test_a_tag_only_o_loses_at_most_three_games_across_a_week_boundary():
    """Friday: his team plays Fri, Sun, then Mon, Wed, Fri of next week. The
    tag costs Fri, Sun and Mon (3 games, across the boundary), no more."""
    games = [D(11, 6), D(11, 8), D(11, 9), D(11, 11), D(11, 13)]
    av = fa_world({"F0": "O"}, today=D(11, 6), dates={"F0": games})
    this, nxt = rest(D(11, 6))
    assert av.playable("F0", this) == []
    assert av.playable("F0", nxt) == [D(11, 11), D(11, 13)]
    assert len([d for d in games if not av.plays("F0", d)]) == 3


def test_ofs_counts_nothing_and_a_healthy_player_counts_every_team_game():
    games = [D(11, 3), D(11, 5), D(11, 7), D(11, 10), D(11, 12)]
    av = fa_world({"F0": "OFS", "F1": "HEALTHY", "F2": "Q", "F3": "P"},
                  dates={"F0": games, "F1": games, "F2": games, "F3": games})
    this, nxt = rest(D(11, 2))
    assert (av.playable("F0", this), av.playable("F0", nxt)) == ([], [])
    for n in ("F1", "F2", "F3"):                                    # Q plays, P is healthy
        assert av.playable(n, this + nxt) == games


def test_the_free_agents_count_with_the_grids_own_rule():
    """One rule, not a copy: the grid's players() and the free agents'
    playable() are both Availability.plays()."""
    import inspect
    tags = {"F0": "O", "F1": "OFS", "F2": "Q", "F3": "HEALTHY"}
    over = [{"player_name": "F3", "out_weeks": [3], "return_week": 4, "return_date": "2026-11-11"}]
    names = sorted(tags)
    info = {n: {"nba_team": f"T{n}", "positions": {"SF"}, "proj_fppg": 30.0} for n in names}
    team_dates = {f"T{n}": set(WEEK3 + WEEK4) for n in names}
    grid = hs.Availability({"M": names}, {"M": []}, tags, {"players": over}, 3, info, team_dates,
                           WEEKS, D(11, 2))
    fa = grid.for_free_agents(names, tags)
    for d in WEEK3 + WEEK4:
        assert sorted(grid.players("M", d)) == sorted(n for n in names if fa.plays(n, d)), d
    src = inspect.getsource(hs.rank_free_agents)
    assert "av.playable(" in src and "team_dates" not in src and "has_game" not in src


# =============================================================================
# 2. status chips
# =============================================================================

def chip(av, name, today=D(11, 2)):
    this, nxt = rest(today)
    st = hs.free_agent_status(av, name, av.tags.get(name), this + nxt)
    return st["source"], [c["text"] for c in st["chips"]], [c["kind"] for c in st["chips"]]


def test_the_status_chip_for_each_case():
    over = [{"player_name": "F0", "out_weeks": [3, 4, 5], "return_week": 6, "return_date": "2026-11-23"},
            {"player_name": "F1", "out_weeks": [3, 4]},
            {"player_name": "F2", "out_weeks": [3], "return_week": 4},
            {"player_name": "F8", "out_weeks": [1, 2], "return_week": 3, "return_date": "2026-11-01"}]
    av = fa_world({"F0": "O", "F1": "Q", "F2": "HEALTHY", "F3": "O", "F4": "OFS", "F5": "Q", "F6": "D",
                   "F7": "P", "F8": "Q", "F9": "SUSP"}, over)
    assert chip(av, "F0") == ("override", ["O \u00b7 back 11-23"], ["out"])
    assert chip(av, "F1") == ("override", ["O \u00b7 no return date"], ["out"])
    assert chip(av, "F2") == ("override", ["O \u00b7 back 11-09"], ["out"])     # return week's first day
    assert chip(av, "F3") == ("tag", ["O \u00b7 up to 3 games"], ["out"])
    assert chip(av, "F4") == ("season_out", ["OFS \u00b7 season"], ["out"])
    assert chip(av, "F5") == ("tag", ["Q"], ["q"])
    assert chip(av, "F6") == ("tag", ["D"], ["q"])
    assert chip(av, "F7") == ("healthy", [], [])                                  # P is healthy
    assert chip(av, "F8") == ("tag", ["Q"], ["q"])           # an entry whose dates have passed is not his status
    assert chip(av, "F9") == ("note", ["SUSP"], ["q"])


def test_ofs_wins_over_an_injury_entry():
    over = [{"player_name": "F0", "out_weeks": [3, 4], "return_week": 5, "return_date": "2026-11-17"}]
    av = fa_world({"F0": "OFS"}, over)
    assert chip(av, "F0")[1] == ["OFS \u00b7 season"]


def test_free_agent_tags_raise_rather_than_default():
    row = {"run_id": "r1", "tags": {"rostered": {"Was Rostered": "O"},
                                    "free_agents": {"Free One": "Q", "Free Two": "HEALTHY"},
                                    "free_agents_assumed_healthy": False}}
    assert hs.free_agent_tags(row, ["Free One", "Was Rostered"]) == {"Free One": "Q", "Was Rostered": "O"}
    with pytest.raises(hs.HubInputError, match="no tag for free agent"):
        hs.free_agent_tags(row, ["Free One", "Nobody Here"])
    none = {"run_id": "r2", "tags": {"rostered": {}, "free_agents": None, "free_agents_assumed_healthy": True}}
    with pytest.raises(hs.HubInputError, match="carries no free-agent tags"):
        hs.free_agent_tags(none, ["Free One"])
    odd = {"run_id": "r3", "tags": {"rostered": {}, "free_agents": {"Free One": "GTD"}}}
    with pytest.raises(hs.HubInputError, match="Free One"):
        hs.free_agent_tags(odd, ["Free One"])


# =============================================================================
# 3. the ranking: points over the two weeks, then Proj, then name
# =============================================================================

def rec(name, proj):
    return {"player_name": name, "projectedFPPG": proj, "player_position(s)": "SF"}


def test_the_ranking_orders_by_two_week_points_then_proj_then_name():
    over = [{"player_name": "F0", "out_weeks": [3, 4, 5], "return_week": 6, "return_date": "2026-11-23"}]
    four = [D(11, 3), D(11, 5), D(11, 10), D(11, 12)]          # 4 games
    two = [D(11, 3), D(11, 10)]                                # 2 games
    av = fa_world({"F0": "O", "F1": "HEALTHY", "F2": "HEALTHY", "F3": "HEALTHY", "F4": "HEALTHY"}, over,
                  dates={"F0": WEEK3 + WEEK4, "F1": two, "F2": four, "F3": four, "F4": four})
    records = [rec("F0", 45.0), rec("F1", 40.0), rec("F2", 20.0), rec("F3", 20.0), rec("F4", 25.0)]
    rows = hs.rank_free_agents(records, av, *rest(D(11, 2)))
    # F4 25x4=100; F1 40x2=80 ties F2 and F3 (20x4=80): higher Proj first (F1), then name; F0 last at 0
    assert [r["name"] for r in rows] == ["F4", "F1", "F2", "F3", "F0"]
    assert [r["pts"] for r in rows] == ["100.0", "80.0", "80.0", "80.0", "0.0"]
    f0 = rows[-1]
    assert (f0["proj"], f0["g1"], f0["g2"], f0["status"]) == ("45.0", "0", "0", "override")
    assert all(isinstance(v, str) for r in rows for k, v in r.items()
               if not k.startswith("_") and k not in ("tags",))


def test_a_free_agent_with_no_projection_refuses():
    av = fa_world({"F0": "HEALTHY"})
    with pytest.raises(hs.HubInputError, match="no projectedFPPG"):
        hs.rank_free_agents([rec("F0", float("nan"))], av, *rest(D(11, 2)))


def test_a_free_agent_with_no_nba_team_refuses():
    info = {"F0": {"nba_team": None, "positions": {"SF"}, "proj_fppg": 1.0}}
    base = hs.Availability({}, {}, {}, {"players": []}, 3, info, {}, WEEKS, D(11, 2))
    with pytest.raises(hs.HubInputError, match="no NBA team"):
        base.for_free_agents(["F0"], {"F0": "HEALTHY"})


# =============================================================================
# 4. the page prints the free agents and computes nothing (1b's tests run on
#    the same sample payload, now carrying these fields)
# =============================================================================

def test_the_free_agent_table_prints_pts_and_the_status_chips():
    p = sample_payload()
    page = hub_page.render(p, now=GEN)
    text = visible_text(page)
    for s in ("Pts (2 wks)", "273.0", "O \u00b7 back 11-23", "by projected points, rest of this week + next"):
        assert s in text
    assert 'data-status="override"' in page and '<span class="chip out">O \u00b7 back 11-23</span>' in page


def test_the_free_agent_numbers_on_the_page_are_payload_strings():
    p = sample_payload()
    page = hub_page.render(p, now=GEN)
    sec = page[page.index("Best free agents"):page.index("<h2>Advice</h2>")]
    known = " ".join(payload_strings(p["free_agents"])) + " " + " ".join(payload_strings(p["stash"]))
    for n in re.findall(r"\d+(?:[.,]\d+)*", visible_text(sec)):
        assert n in known, n


# =============================================================================
# 5. the moves feed: colour, marker, both parts of an add/drop
# =============================================================================

def test_the_feed_items_carry_each_parts_kind_and_marker(tmp_path):
    _sync(tmp_path, [ADD, ADD_DROP, DROP, TRADE])
    items = {t["type"]: tlog.feed_item(t, SCHEDULE) for t in tlog.transactions(tmp_path)}
    assert items["add"]["parts"] == [{"kind": "add", "marker": "+", "text": "added Davion Mitchell"}]
    assert items["drop"]["parts"] == [{"kind": "drop", "marker": "\u2212", "text": "dropped Kawhi Leonard"}]
    assert items["add/drop"]["parts"] == [{"kind": "add", "marker": "+", "text": "added Miles Bridges"},
                                          {"kind": "drop", "marker": "\u2212", "text": "dropped Ty Jerome"}]
    assert [x["kind"] for x in items["trade"]["parts"]] == ["trade", "trade"]
    assert all(x["marker"] == "\u21c4" for x in items["trade"]["parts"])
    for it in items.values():                                       # `what` is the parts, joined
        sep = "; " if it["kind"] == "trade" else ", "
        assert it["what"] == sep.join(x["text"] for x in it["parts"])


def test_each_kind_renders_its_class_and_marker_and_an_add_drop_shows_both(tmp_path):
    from modules import hub_moves
    _sync(tmp_path, [ADD, ADD_DROP, DROP, TRADE])
    feed = hub_moves.by_week(tlog.transactions(tmp_path), [], SCHEDULE, None,
                             {3: {"Benton": ["Davion Mitchell"], "Nick": ["Miles Bridges"]}}, week=3,
                             managers=["Nick", "Hayden", "Garrett", "Benton"], budget=3, mode="shadow")
    page = hub_page.render(sample_payload(moves=feed), now=GEN)
    for kind, marker, text in (("add", "+", "added Davion Mitchell"), ("drop", "\u2212", "dropped Kawhi Leonard"),
                               ("trade", "\u21c4", "Hayden gets Jayson Tatum")):
        assert f'<span class="mvp {kind}"><span class="mk">{marker}</span>{text}</span>' in page
    both = re.search(r'<b>Nick</b>(<span class="mvp [^"]+">.*?</span></span>)+', page).group(0)
    assert both.index('mvp add"><span class="mk">+</span>added Miles Bridges') < \
        both.index('mvp drop"><span class="mk">\u2212</span>dropped Ty Jerome')


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_move_colours_are_readable_on_the_card_and_the_page():
    """WCAG AA for body text (4.5:1) on the card the feed sits in and on the
    page around it; green, red and purple as Nick asked, and the CSS uses
    exactly these."""
    css = hub_page.CSS
    assert ".card{background:#fff;" in css and "body{margin:0;background:#F4F5F7;" in css
    for kind, colour in hub_page.MOVE_COLOURS.items():
        assert f".mvp.{kind}{{color:{colour}}}" in css
        for bg in ("#FFFFFF", "#F4F5F7"):
            assert contrast(colour, bg) >= 4.5, (kind, colour, bg)
    r = (lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)])
    assert max(r(hub_page.MOVE_COLOURS["add"])) == r(hub_page.MOVE_COLOURS["add"])[1]       # green
    assert max(r(hub_page.MOVE_COLOURS["drop"])) == r(hub_page.MOVE_COLOURS["drop"])[0]     # red
    pr, pg, pb = r(hub_page.MOVE_COLOURS["trade"])
    assert pr > pg and pb > pg                                                              # purple
    assert set(tlog.PART_MARKER) == set(hub_page.MOVE_COLOURS)


# =============================================================================
# 6. scratch builds never write league state
# =============================================================================

def test_a_scratch_build_refuses_a_state_path():
    assert hub_publish.scratch_refusal(ROOT, ROOT / "output" / "hub_state.json")
    assert hub_publish.scratch_refusal(ROOT, ROOT / "output" / "hub_archive" / "x" / "hub_preview.html")
    assert hub_publish.scratch_refusal(ROOT, ROOT / "_to_delete" / "scratch" / "hub_state.json") == ""
    assert hub_publish.scratch_refusal(ROOT, ROOT / "output" / "hub_preview.html") == ""


def test_build_hub_state_refuses_out_to_a_state_path_before_building(capsys):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_hub_state
    target = ROOT / "output" / "hub_state.json"
    before = target.stat().st_mtime_ns if target.exists() else None
    assert build_hub_state.main(["--base-path", str(ROOT), "--out", str(target)]) == 1
    assert "league state" in capsys.readouterr().out
    assert (target.stat().st_mtime_ns if target.exists() else None) == before


# =============================================================================
# 7. Kawhi Leonard's real entry (Nick, 11-04)
# =============================================================================

def _real_data():
    if not (ROOT / "config" / "INJURY_OVERRIDES.json").exists() or \
            not (ROOT / "data" / "PLAYERLIST.xlsx").exists():
        pytest.skip("league state not in this checkout (the hub's real inputs)")
    from modules.data_loader import load_all_data
    return load_all_data(ROOT, current_week=None)


def _kawhi_entry(data):
    e = [x for x in (data.injury_overrides or {}).get("players", []) if x["player_name"] == "Kawhi Leonard"]
    if not e or 3 not in e[0].get("out_weeks", []) or 4 not in e[0].get("out_weeks", []):
        pytest.skip("Kawhi Leonard's INJURY_OVERRIDES entry no longer covers weeks 3-4")
    return e[0]


def test_kawhis_real_entry_plays_nothing_in_weeks_3_and_4():
    """On 11-04 (week 3): GL 0 and Next 0, whatever his tag, from his real
    entry (out weeks 2-5, back 11-23) on the real schedule."""
    from modules.schedule_strength import build_player_info_map
    from modules.simulator_betting import schedule_week_dates
    data = _real_data()
    _kawhi_entry(data)
    info = build_player_info_map(data.playerlist)
    if "Kawhi Leonard" not in info:
        pytest.skip("Kawhi Leonard is not in PLAYERLIST")
    today = D(11, 4)
    wk = schedule_week_dates(data)
    this, nxt = [d for d in wk[3] if d >= today], list(wk[4])
    base = hs.Availability.from_data(data, {}, {}, {}, data.injury_overrides, 3, info, today)
    for tag in ("HEALTHY", "O", "Q"):
        av = base.for_free_agents(["Kawhi Leonard"], {"Kawhi Leonard": tag})
        assert sum(1 for d in this + nxt if av.has_game("Kawhi Leonard", d)) > 0     # his team plays
        assert (len(av.playable("Kawhi Leonard", this)), len(av.playable("Kawhi Leonard", nxt))) == (0, 0)
        st = hs.free_agent_status(av, "Kawhi Leonard", tag, this + nxt)
        assert [c["text"] for c in st["chips"]] == ["O \u00b7 back 11-23"]


@pytest.fixture(scope="module")
def real_all_free_agents():
    """The real build with every free agent listed (top N lifted), so the
    whole ranking can be checked."""
    from modules import player_actuals
    from modules.league_clock import league_now
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_latest.json",
              ROOT / "output" / "tag_records.jsonl", ROOT / "data" / "transaction_log.jsonl"]
    if not all(p.exists() for p in needed):
        pytest.skip("league state not in this checkout (the hub's real inputs)")
    orig = hs.hub_config
    hs.hub_config = lambda *a, **k: dict(orig(*a, **k), free_agents_top_n=10 ** 6)
    try:
        now = league_now()
        payload = hs.build(ROOT, now=now, allow_engine_mismatch=True)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        pytest.skip(f"the hub's real inputs are not current today ({e}); state-dependent like test_hub")
    finally:
        hs.hub_config = orig
    return payload


def _games(r):
    """Every column's games (three since hub polish 3, 48g); a chat-dropped
    player's first column is a dash before the window closes (he plays from
    the next Monday)."""
    return sum(int(r[k]) for k in ("g1", "g2", "g3") if r.get(k, "").isdigit())


def test_real_kawhi_scores_nothing_and_ranks_below_every_healthy_free_agent_with_games(real_all_free_agents):
    p = real_all_free_agents
    rows = p["free_agents"]["rows"]
    names = [r["name"] for r in rows]
    if "Kawhi Leonard" not in names:
        pytest.skip("Kawhi Leonard is not a free agent today")
    if max(w for w in p["free_agents"]["weeks"] if w is not None) > 5:
        pytest.skip("the columns reach past week 5: no longer inside Kawhi's out weeks (back 11-23)")
    k = rows[names.index("Kawhi Leonard")]
    assert (k["g1"], k["g2"], k["pts"]) == ("0", "0", "0.0")
    assert [c["text"] for c in k["tags"]] == ["O \u00b7 back 11-23"]
    healthy_with_games = [i for i, r in enumerate(rows)
                          if r["status"] == "healthy" and _games(r) > 0]
    assert healthy_with_games and max(healthy_with_games) < names.index("Kawhi Leonard")


def test_real_free_agents_are_ranked_by_points_then_proj_then_name(real_all_free_agents):
    rows = real_all_free_agents["free_agents"]["rows"]
    keys = [(-float(r["pts"]), -float(r["proj"]), r["name"]) for r in rows]
    # the strings are rounded to 0.1; the order is the unrounded one, so it is
    # sorted wherever the rounded values differ
    for a, b in zip(keys, keys[1:]):
        assert a[:1] <= b[:1]
    for r in rows:                     # Pts = Proj x (both columns' games), up to the strings' rounding
        games = _games(r)
        assert abs(float(r["pts"]) - float(r["proj"]) * games) <= 0.05 * games + 0.05 + 1e-9, r["name"]


def test_real_payload_lists_the_configured_top_n():
    from modules.hub_state import hub_config
    assert int(hub_config()["free_agents_top_n"]) == 10


# --- reviewing session, 11-04 ---------------------------------------------

def test_hub_tags_keep_an_ofs_tag_for_a_rostered_player():
    """The 1c-i hub tags kept only the tags the line chains, so a rostered
    OFS player showed as healthy and counted in the grid."""
    from modules import tag_records
    row = {"tags": {"rostered": {"Player One": "OFS", "Player Two": "O", "Player Three": "Q"}}}
    got = tag_records.hub_tags(row, ["Player One", "Player Two", "Player Three", "Player Four"])
    assert got.get("Player One") == "OFS"
    assert got.get("Player Two") == "O"
    assert "Player Four" not in got


def test_roster_games_left_counts_playable_games():
    """Roster GL follows the grid and the free agents (Nick, 11-04): games he
    will play, not his team's games. Pinned at the source line."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules" / "hub_state.py").read_text(encoding="utf-8")
    assert "gl = len(av.playable(n, this_days))" in src
    assert 'gl = sum(1 for d in this_days if d in team_dates' not in src
