"""Tasks 41-43a (claude/HANDOFF_HUB_FREE_AGENTS_MOVES_2026-11-05.md): the hub's
free-agent columns by the add rule, the stash table, moves by budget week, and
pending ledger moves in next week's games grid. Synthetic where the rule is
logic; on the real data where the point is the real season (state-dependent
tests skip with the reason, as test_hub's real build does)."""

import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from modules import hub_state as hs, hub_page, hub_moves, move_ledger as ml  # noqa: E402
from modules import transaction_log as tlog, transaction_rulings as tr     # noqa: E402
from test_hub import sample_payload, GEN, visible_text, payload_strings     # noqa: E402
from test_transaction_log import _sync, _ts, _player, raw, ADD, ADD_DROP, DROP, TRADE, SCHEDULE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LA = ZoneInfo("America/Los_Angeles")
D = lambda m, d: date(2026, m, d)                                   # noqa: E731
MGRS = ["Nick", "Hayden", "Garrett", "Benton"]


def week_days(a: date, n: int):
    return [a + timedelta(days=i) for i in range(n)]


# weeks 3-7 of the real calendar, week 7 a 14-day fantasy week (rule 9); 22-23 the season's end
WK = {3: week_days(D(11, 2), 7), 4: week_days(D(11, 9), 7), 5: week_days(D(11, 16), 7),
      6: week_days(D(11, 23), 7), 7: week_days(D(11, 30), 14),
      22: week_days(date(2027, 3, 29), 7), 23: week_days(date(2027, 4, 5), 7)}


def monday_games(*mondays, last_tip_utc_hour=3):
    """An NBA schedule whose only games are on the given Mondays, the last one
    tipping 7:00 PM Pacific (03:00 UTC the next day): the window closes 6:55 PM."""
    g = []
    for m in mondays:
        nxt = m + timedelta(days=1)
        g.append({"date": m.isoformat(), "away": "AAA", "home": "BBB",
                  "tip_utc": f"{nxt.isoformat()}T0{last_tip_utc_hour}:00:00Z"})
        g.append({"date": m.isoformat(), "away": "CCC", "home": "DDD", "tip_utc": f"{nxt.isoformat()}T00:00:00Z"})
    return {"games": g}


NBA = monday_games(D(11, 2), D(11, 9), D(11, 16), D(11, 23), D(11, 30), date(2027, 3, 29), date(2027, 4, 5))
ALWAYS = lambda d: 1                                                # noqa: E731


def at(d: date, hh, mm=0):
    return datetime.combine(d, time(hh, mm), tzinfo=LA)


# =============================================================================
# 41. the free-agent columns follow the add rule
# =============================================================================

def test_before_mondays_window_close_the_columns_are_this_week_and_next():
    for now in (at(D(11, 2), 0, 1), at(D(11, 2), 16, 15), at(D(11, 2), 18, 54)):   # 12:01, pre-tip, 1 min before
        c = hs.free_agent_columns(now, 3, WK, NBA, ALWAYS)
        assert c["mode"] == "this"
        assert [x["label"] for x in c["cols"]] == ["GL", "Next"]
        assert c["cols"][0]["days"] == WK[3] and c["cols"][1]["days"] == WK[4]
        assert [x["week"] for x in c["cols"]] == [3, 4]


def test_from_the_close_the_columns_are_the_next_two_weeks_decided_by_the_clock():
    # Monday 6:55 PM (the close itself), Monday 9 PM, Tuesday's 12:01 build, Sunday
    for now in (at(D(11, 2), 18, 55), at(D(11, 2), 21), at(D(11, 3), 0, 1), at(D(11, 8), 23, 30)):
        c = hs.free_agent_columns(now, 3, WK, NBA, ALWAYS)
        assert c["mode"] == "ahead", now
        assert [x["label"] for x in c["cols"]] == ["Wk 4", "Wk 5"]
        assert c["cols"][0]["days"] == WK[4] and c["cols"][1]["days"] == WK[5]
        assert c["join"] == D(11, 9)


def test_the_close_is_the_last_tip_minus_five_minutes_not_a_fixed_hour():
    late = monday_games(D(11, 2), last_tip_utc_hour=5)                  # last tip 9:00 PM Pacific
    assert hs.free_agent_columns(at(D(11, 2), 20), 3, WK, late, ALWAYS)["mode"] == "this"
    assert hs.free_agent_columns(at(D(11, 2), 20, 55), 3, WK, late, ALWAYS)["mode"] == "ahead"


def test_week_7s_fourteen_days_are_one_column():
    c = hs.free_agent_columns(at(D(11, 24), 12), 6, WK, NBA, ALWAYS)
    assert [x["label"] for x in c["cols"]] == ["Wk 7", hs.DASH] or [x["label"] for x in c["cols"]][0] == "Wk 7"
    c = hs.free_agent_columns(at(D(11, 17), 12), 5, WK, NBA, ALWAYS)
    assert [x["label"] for x in c["cols"]] == ["Wk 6", "Wk 7"]
    assert len(c["cols"][1]["days"]) == 14
    # a free agent whose team plays every day of week 7 counts 14 games in ONE column
    names = ["F0"]
    info = {"F0": {"nba_team": "T0", "positions": {"SF"}, "proj_fppg": 10.0}}
    weeks = {w: (v[0], v[-1]) for w, v in WK.items()}
    av = hs.Availability({}, {}, {}, {"players": []}, 5, info, {"T0": set(WK[6] + WK[7])}, weeks,
                         D(11, 17)).for_free_agents(names, {"F0": "HEALTHY"})
    row = hs.rank_free_agents([{"player_name": "F0", "projectedFPPG": 10.0}], av, c["cols"][0]["days"],
                              c["cols"][1]["days"])[0]
    assert (row["g1"], row["g2"], row["pts"]) == ("7", "14", "210.0")


def test_a_week_with_no_nba_games_in_the_stored_schedule_raises():
    no_wk5 = lambda d: 0 if d in WK[5] else 1                         # noqa: E731
    with pytest.raises(hs.HubInputError, match="week 5 .*no NBA game"):
        hs.free_agent_columns(at(D(11, 3), 12), 3, WK, NBA, no_wk5)
    # before the close week 5 is not shown, so nothing raises
    assert hs.free_agent_columns(at(D(11, 2), 12), 3, WK, NBA, no_wk5)["mode"] == "this"


def test_past_the_seasons_last_week_there_is_no_column_and_after_the_last_window_no_pickup():
    c = hs.free_agent_columns(at(date(2027, 3, 30), 12), 22, WK, NBA, ALWAYS)
    assert [x["label"] for x in c["cols"]] == ["Wk 23", hs.DASH]
    assert c["cols"][1] == {"label": hs.DASH, "days": [], "week": None}
    c = hs.free_agent_columns(at(date(2027, 4, 6), 12), 23, WK, NBA, ALWAYS)
    assert [x["label"] for x in c["cols"]] == [hs.DASH, hs.DASH] and c["join"] is None
    with pytest.raises(hs.HubInputError, match="not in config/SCHEDULE.json"):
        hs.free_agent_columns(at(date(2027, 4, 20), 12), 24, WK, NBA, ALWAYS)


def test_the_page_prints_the_column_labels_from_the_payload():
    p = sample_payload()
    p["free_agents"].update(cols=["Wk 4", "Wk 5"], mode="ahead", weeks=[4, 5])
    text = visible_text(hub_page.render(p, now=GEN))
    sec = text[text.index("Best free agents"):text.index("Stash candidates")]
    assert "Wk 4" in sec and "Wk 5" in sec and " GL " not in sec and "Next" not in sec


def _real_data():
    from modules.data_loader import load_all_data
    if not (ROOT / "config" / "INJURY_OVERRIDES.json").exists():
        pytest.skip("league state not in this checkout")
    return load_all_data(ROOT, current_week=None)


def test_kawhis_real_entry_is_still_zero_in_the_weeks_he_is_out_after_the_switch():
    """Thursday 11-05, after Monday 11-02's window closed: the columns are
    weeks 4 and 5, and Kawhi Leonard's real entry (back 11-23) plays 0 in both."""
    from modules.schedule_strength import build_player_info_map
    from modules.simulator_betting import schedule_week_dates
    data = _real_data()
    e = [x for x in (data.injury_overrides or {}).get("players", []) if x["player_name"] == "Kawhi Leonard"]
    if not e or not {4, 5} <= set(e[0].get("out_weeks", [])):
        pytest.skip("Kawhi Leonard's INJURY_OVERRIDES entry no longer covers weeks 4-5")
    info = build_player_info_map(data.playerlist)
    if "Kawhi Leonard" not in info:
        pytest.skip("Kawhi Leonard is not in PLAYERLIST")
    now = at(D(11, 5), 12)
    wk = schedule_week_dates(data)
    base = hs.Availability.from_data(data, {}, {}, {}, data.injury_overrides, 3, info, now.date())
    c = hs.free_agent_columns(now, 3, wk, data.nba_schedule,
                              lambda d: sum(1 for ds in base.team_dates.values() if d in ds) // 2)
    assert c["mode"] == "ahead" and [x["week"] for x in c["cols"]] == [4, 5]
    for tag in ("HEALTHY", "O", "Q"):
        av = base.for_free_agents(["Kawhi Leonard"], {"Kawhi Leonard": tag})
        assert sum(1 for d in c["cols"][0]["days"] + c["cols"][1]["days"] if av.has_game("Kawhi Leonard", d))
        row = hs.rank_free_agents([{"player_name": "Kawhi Leonard", "projectedFPPG": 39.0}], av,
                                  c["cols"][0]["days"], c["cols"][1]["days"])[0]
        assert (row["g1"], row["g2"], row["pts"]) == ("0", "0", "0.0")


# =============================================================================
# 42. the stash candidates
# =============================================================================

def stash_world(tags, overrides=()):
    names = sorted(tags)
    info = {n: {"nba_team": f"T{n}", "positions": {"SF"}, "proj_fppg": 30.0} for n in names}
    weeks = {w: (v[0], v[-1]) for w, v in WK.items()}
    td = {f"T{n}": set(WK[3] + WK[4]) for n in names}
    return hs.Availability({}, {}, {}, {"players": list(overrides)}, 3, info, td, weeks, D(11, 5)) \
        .for_free_agents(names, tags)


def rec(name, proj):
    return {"player_name": name, "projectedFPPG": proj, "player_position(s)": "SF"}


def test_the_stash_is_only_o_and_ofs_free_agents_by_projection_with_their_status():
    over = [{"player_name": "Out Back", "out_weeks": [3, 4, 5], "return_week": 6, "return_date": "2026-11-23"},
            {"player_name": "Q Entry", "out_weeks": [3, 4], "return_week": 5, "return_date": "2026-11-18"}]
    tags = {"Out Back": "O", "Season Gone": "OFS", "O Only": "O", "Q Entry": "Q", "Healthy": "HEALTHY",
            "Day To Day": "D"}
    av = stash_world(tags, over)
    recs = [rec("Out Back", 30.0), rec("Season Gone", 45.0), rec("O Only", 20.0), rec("Q Entry", 50.0),
            rec("Healthy", 60.0), rec("Day To Day", 55.0)]
    rows = hs.stash_rows(recs, av, WK[4] + WK[5], 10)
    # a Q player with an injury entry and a healthy one cannot go straight into IL (rule 2)
    assert [r["name"] for r in rows] == ["Season Gone", "Out Back", "O Only"]
    chips = {r["name"]: [c["text"] for c in r["tags"]] for r in rows}
    assert chips == {"Season Gone": ["OFS · season"], "Out Back": ["O · back 11-23"],
                     "O Only": ["O · up to 3 games"]}
    assert [r["season"] for r in rows] == [True, False, False]
    assert rows[0]["season_note"] == "an IL slot all season: keeper value only"
    assert hs.stash_rows(recs, av, WK[4] + WK[5], 2) == rows[:2]           # top N
    assert all(isinstance(v, str) for r in rows for k, v in r.items() if k not in ("tags", "season"))


def test_the_stash_reads_the_il_eligible_tags_from_the_config(monkeypatch):
    av = stash_world({"Out One": "O", "Season Gone": "OFS"})
    recs = [rec("Out One", 30.0), rec("Season Gone", 45.0)]
    assert [r["name"] for r in hs.stash_rows(recs, av, WK[4], 10)] == ["Season Gone", "Out One"]
    monkeypatch.setattr(ml, "il_eligible_tags", lambda cfg=None: ("O",))
    assert [r["name"] for r in hs.stash_rows(recs, av, WK[4], 10)] == ["Out One"]


def test_stash_top_n_is_a_required_config_key():
    cfg = {"hub": {"free_agents_top_n": 10, "light_night_max": 4}}
    with pytest.raises(hs.HubInputError, match="stash_top_n"):
        hs.hub_config(cfg)
    for bad in (0, -1, "5", True, None):
        with pytest.raises(hs.HubInputError, match="stash_top_n"):
            hs.hub_config({"hub": dict(cfg["hub"], stash_top_n=bad)})
    assert hs.hub_config()["stash_top_n"] >= 1


def test_open_il_slots_text():
    assert hs.open_il_text(MGRS, {"Nick": ["a", "b"], "Hayden": ["c"], "Garrett": [], "Benton": ["d", "e"]},
                           2) == "Open IL slots now: Hayden 1, Garrett 2."
    assert hs.open_il_text(MGRS, {m: ["x", "y"] for m in MGRS}, 2) == "No team has an open IL slot now."


def test_the_page_prints_the_stash_under_the_free_agents_and_computes_nothing():
    p = sample_payload()
    page = hub_page.render(p, now=GEN)
    assert page.index("Best free agents") < page.index("Stash candidates") < page.index("<h2>Advice</h2>")
    sec = page[page.index("Stash candidates"):page.index("<h2>Advice</h2>")]
    text = visible_text(sec)
    for s in ("Open IL slots now: Mgr Two 2.", "OFS · season", "an IL slot all season: keeper value only",
              "Hurt Agent", "41.5"):
        assert s in text
    known = " ".join(payload_strings(p["stash"]))
    for n in re.findall(r"\d+(?:[.,]\d+)*", text):
        assert n in known, n


# =============================================================================
# 43. moves by budget week
# =============================================================================

PRE_ADD = raw(9, _ts(2026, 10, 20, 9, 0), "add/drop", _player("Early Guy", 9, "add", dst="Blink-183"),
              _player("Old Guy", 10, "drop", src="Blink-183"))
VOID_ADD = raw(8, _ts(2026, 11, 3, 7, 28), "add", _player("Void Guy", 8, "add", dst="Blink-183"))
VOID = tr.Ruling("2026-11-03", "Garrett", "add", "Void Guy", "void", "Nick", "2026-11-04", "test")
CLAIMED = tr.ClaimWeek("Nick", "Miles Bridges", "add", "2026-11-02", 2, "Nick", "2026-11-02", "test")
COUNTS = {2: {"Nick": ["Miles Bridges"]}, 3: {"Benton": ["Davion Mitchell"]}}


def entry(i, manager, add=(), drop=(), claim_week=3, window="2026-11-09", claimed="2026-11-04T10:00:00-08:00",
          voided=None):
    return {"row": "entry", "id": i, "kind": "move", "text": "t", "claimed_at": claimed, "claim_week": claim_week,
            "window_week": claim_week + 1, "window": window, "voided": voided,
            "parsed": {"manager": manager, "add": list(add), "drop": list(drop), "il_place": [], "il_activate": []}}


def moves(tmp_path, *, counts=COUNTS, rulings=(VOID, CLAIMED), entries=(), states=(), live=(), mode="shadow",
          week=3, ledger=None, txs=(ADD, ADD_DROP, DROP, TRADE, PRE_ADD, VOID_ADD)):
    _sync(tmp_path, list(txs), rulings=list(rulings))
    return hub_moves.by_week(tlog.transactions(tmp_path), list(rulings), SCHEDULE, ledger, counts, week=week,
                             managers=MGRS, budget=3, mode=mode, ledger_entries=list(entries),
                             ledger_states=list(states), live_claims=list(live))


def tab(feed, key):
    return next(t for t in feed["weeks"] if t["key"] == key)


def test_every_transaction_lands_in_exactly_one_week_the_budget_week_by_the_one_counter(tmp_path):
    feed = moves(tmp_path)
    assert [t["key"] for t in feed["weeks"]] == ["pre", "2", "3"] and feed["default"] == "3"
    whats = {t["key"]: [x["what"] for x in t["items"]] for t in feed["weeks"]}
    # Bridges (Yahoo 11-02, week 3) was claimed in week 2: his add/drop is under week 2, the drop with it
    assert whats["2"] == ["added Miles Bridges, dropped Ty Jerome"]
    assert "week 2 claim" in tab(feed, "2")["items"][0]["note"]
    assert sorted(whats["3"]) == sorted(["added Davion Mitchell", "dropped Kawhi Leonard", "added Void Guy",
                                         "Hayden gets Jayson Tatum; Benton gets Scottie Barnes"])
    assert whats["pre"] == ["added Early Guy, dropped Old Guy"]
    assert sum(len(v) for v in whats.values()) == 6                 # six transactions, each once


def test_adds_used_are_the_counters_totals(tmp_path):
    feed = moves(tmp_path)
    assert [u["text"] for u in tab(feed, "2")["used"]] == ["Nick 1 of 3", "Hayden 0 of 3", "Garrett 0 of 3",
                                                           "Benton 0 of 3"]
    assert [u["text"] for u in tab(feed, "3")["used"]] == ["Nick 0 of 3", "Hayden 0 of 3", "Garrett 0 of 3",
                                                           "Benton 1 of 3"]
    assert tab(feed, "pre")["used"] is None and "rule 14" in tab(feed, "pre")["used_note"]


def test_the_log_and_the_counter_must_agree_or_the_build_raises(tmp_path):
    with pytest.raises(hub_moves.MovesError, match="week 3 Benton"):
        moves(tmp_path, counts={2: {"Nick": ["Miles Bridges"]}})
    with pytest.raises(hub_moves.MovesError, match="Void Guy"):
        moves(tmp_path / "b", counts={**COUNTS, 3: {"Benton": ["Davion Mitchell"], "Garrett": ["Void Guy"]}})


def test_a_voided_add_is_struck_marked_and_counts_nowhere(tmp_path):
    feed = moves(tmp_path)
    it = next(x for x in tab(feed, "3")["items"] if x["what"] == "added Void Guy")
    assert it["state"] == "Voided" and "voided" in it["note"]
    assert it["parts"] == [{"kind": "add", "marker": "+", "text": "added Void Guy", "void": True}]
    assert "Garrett 0 of 3" in [u["text"] for u in tab(feed, "3")["used"]]
    page = hub_page.render(sample_payload(moves=feed), now=GEN)
    assert '<span class="mvp add void"><span class="mk">+</span><span class="t">added Void Guy</span></span>' in page
    assert ".mvp.void .t{text-decoration:line-through}" in page


def test_pending_ledger_entries_sit_under_their_claim_week(tmp_path):
    ents = [entry(1, "Hayden", add=["Pending Guy"], claim_week=3),
            entry(2, "Garrett", drop=["Gone Guy"], claim_week=2, window="2026-11-02",
                  claimed="2026-10-30T09:00:00-07:00"),
            entry(3, "Nick", add=["Miles Bridges"], claim_week=2, window="2026-11-02",
                  claimed="2026-10-30T08:00:00-07:00"),                          # applied
            entry(4, "Benton", add=["Typo Guy"], voided={"reason": "typo"}),       # Nick's typo
            entry(5, "Hayden", add=["Davion Mitchell"], window="2026-11-02", claim_week=2,
                  claimed="2026-10-31T08:00:00-07:00")]                            # flagged
    states = [{"row": "state", "entry": 3, "state": "applied"},
              {"row": "state", "entry": 2, "state": "missing"},
              {"row": "state", "entry": 5, "state": "conflict"}]
    feed = moves(tmp_path, entries=ents, states=states)
    w3 = [(x["who"], x["what"], x["state"]) for x in tab(feed, "3")["items"] if x.get("kind") == "ledger"]
    w2 = [(x["who"], x["what"], x["state"]) for x in tab(feed, "2")["items"] if x.get("kind") == "ledger"]
    assert w3 == [("Hayden", "claimed Pending Guy", "Pending")]
    assert sorted(w2) == [("Garrett", "dropped Gone Guy", "Missing"), ("Hayden", "claimed Davion Mitchell",
                                                                        "Conflict")]
    assert "Typo Guy" not in str(feed)                                    # a ledger void is no move
    # shadow mode: a pending claim is listed, not counted
    assert "Hayden 0 of 3" in [u["text"] for u in tab(feed, "3")["used"]]


def test_a_pending_entry_already_in_yahoos_log_shows_once_as_the_yahoo_move(tmp_path):
    # Bridges' claim (week 2) applied in Yahoo 11-02 but not yet verified: Yahoo's move shows it
    e = entry(1, "Nick", add=["Miles Bridges"], drop=["Ty Jerome"], claim_week=2, window="2026-11-02",
              claimed="2026-10-30T08:00:00-07:00")
    feed = moves(tmp_path, entries=[e])
    assert [x["what"] for x in tab(feed, "2")["items"]] == ["added Miles Bridges, dropped Ty Jerome"]


def test_on_mode_counts_a_live_claim_at_once_and_never_twice(tmp_path):
    live = [{"manager": "Hayden", "player": "Pending Guy", "window": "2026-11-09", "claim_week": 3, "entry": 1},
            {"manager": "Nick", "player": "Miles Bridges", "window": "2026-11-02", "claim_week": 2, "entry": 2}]
    ledger = [{"manager": "Nick", "player": "Miles Bridges", "window": "2026-11-02", "claim_week": 2, "entry": 2}]
    feed = moves(tmp_path, rulings=(VOID,), live=live, mode="on", ledger=ledger)
    assert "Hayden 1 of 3" in [u["text"] for u in tab(feed, "3")["used"]]
    assert "Nick 1 of 3" in [u["text"] for u in tab(feed, "2")["used"]]  # in the log already: once
    assert "counts the moment it is posted" in tab(feed, "3")["used_note"]
    shadow = moves(tmp_path / "s", live=live)
    assert "Hayden 0 of 3" in [u["text"] for u in tab(shadow, "3")["used"]]


def test_a_move_placed_after_the_current_week_or_two_weeks_in_one_move_raises(tmp_path):
    with pytest.raises(hub_moves.MovesError, match="after the current week"):
        moves(tmp_path, week=2, counts=COUNTS)
    two = raw(7, _ts(2026, 11, 2, 6, 30), "add", _player("Miles Bridges", 2, "add", dst="Luka my Balls"),
              _player("Other Guy", 11, "add", dst="Luka my Balls"))
    with pytest.raises(hub_moves.MovesError, match="different weeks"):
        moves(tmp_path / "b", txs=(two,), counts={2: {"Nick": ["Miles Bridges"]}, 3: {"Nick": ["Other Guy"]}})


def test_the_week_picker_shows_the_default_week_and_hides_the_others():
    p = sample_payload()
    page = hub_page.render(p, now=GEN)
    assert '<option value="3" selected>Week 3 · Nov 2–8</option>' in page
    assert '<option value="pre">Pre-season</option>' in page
    assert '<div class="card" data-mvw="3">' in page and '<div class="card" data-mvw="pre" hidden>' in page
    text = visible_text(page)
    assert "Mgr One 1 of 3" in text and "last 7 days" not in text
    js = hub_page.PAGE_JS[hub_page.PAGE_JS.index("var wk="):hub_page.PAGE_JS.index("function openFrame")]
    # it shows one week's card and hides the rest: no number is parsed, rounded or worked out
    assert not re.search(r"parseInt|parseFloat|Number\(|Math\.|toFixed|\*|\.textContent=", js)


@pytest.fixture(scope="module")
def real_moves():
    from modules.data_loader import load_all_data, MANAGERS
    if not (ROOT / "data" / "transaction_log.jsonl").exists() or not (ROOT / "data" / "waivers_week1.txt").exists():
        pytest.skip("league state not in this checkout (the transaction log and the waivers files)")
    data = load_all_data(ROOT, current_week=None)
    from modules import week_state as ws
    from modules.league_clock import league_now
    week = ws.week_for_date(data, league_now().date())
    return {"week": week, "schedule": data.schedule,
            "feed": hub_moves.build(ROOT, data.schedule, week, managers=list(MANAGERS), budget=3)}


def test_real_every_transaction_lands_in_one_week_by_add_budget_week(real_moves):
    sched = real_moves["schedule"]
    txs = tlog.transactions(ROOT)
    rulings = tr.load_all(ROOT, sched)
    ledger = tr.ledger_by_mode(ROOT)
    first = min(date.fromisoformat(str(w["start_date"])[:10]) for w in sched["weeks"])
    n_items = {t["key"]: len([x for x in t["items"] if x.get("kind") != "ledger"]) for t in real_moves["feed"]["weeks"]}
    want = {}
    for t in txs:
        pl = hub_moves.place(t, rulings, sched, ledger, first)
        for p in t["players"]:
            if p["action"] == "add" and t["type"] != "trade":
                bw = tr.add_budget_week({"date": t["league_day"], "manager": p["to"]["manager"], "player": p["name"]},
                                        rulings, sched, ledger)
                if bw is not None:
                    assert pl["bucket"] == bw, (t["key"], p["name"])
        want[str(pl["bucket"])] = want.get(str(pl["bucket"]), 0) + 1
    assert sum(n_items.values()) == len(txs)
    assert {k: v for k, v in n_items.items() if v} == want


def test_real_adds_used_equal_adds_by_budget_week(real_moves):
    counts = tr.adds_by_budget_week(ROOT, real_moves["schedule"])
    for t in real_moves["feed"]["weeks"]:
        if t["key"] == hub_moves.PRE:
            assert t["used"] is None
            continue
        w = int(t["key"])
        assert [u["text"] for u in t["used"]] == [f"{m} {len(counts.get(w, {}).get(m, []))} of 3"
                                                  for m in [u["manager"] for u in t["used"]]]


def test_real_pre_season_and_voided_moves(real_moves):
    tabs = {t["key"]: t for t in real_moves["feed"]["weeks"]}
    pre = [x["what"] for x in tabs["pre"]["items"]]
    for name in ("Jaren Jackson Jr.", "Julius Randle", "Isaiah Hartenstein", "Day'Ron Sharpe"):
        assert any(f"added {name}" in w for w in pre), name                # rule 14: counted nowhere
    voided = {(t["key"], p["text"]) for t in real_moves["feed"]["weeks"] for x in t["items"]
              for p in x["parts"] if p.get("void")}
    assert voided == {("1", "added Franz Wagner"), ("2", "added Paul George")}
    pg = [x for x in tabs["2"]["items"] if x["who"] == "Garrett" and "added Paul George" in x["what"]]
    assert len(pg) == 1 and pg[0]["state"] == "Voided"


# =============================================================================
# 43a. next week's grid with the pending moves
# =============================================================================

sys.path.insert(0, str(ROOT / "scripts"))
from test_move_ledger import make_world, enter, at as lat                 # noqa: E402


def grid_pair(w, rows, plays_only=None):
    """(this tab, next tab, next tab with no entries) for the ledger's test world."""
    names = sorted({n for v in w.rosters.values() for n in v} | {"Desmond Bane"})
    info = {n: {"nba_team": f"T{n}", "positions": {"PG", "SG", "SF", "PF", "C"}, "proj_fppg": 20.0} for n in names}
    every = WK[3] + WK[4]
    td = {f"T{n}": set((plays_only or {}).get(n, every)) for n in names}
    weeks = {w_: (v[0], v[-1]) for w_, v in WK.items()}
    tags = {n: t for n, t in w.tags.items() if n in names and t in ("O", "OFS")}
    av = hs.Availability(w.rosters, w.il, tags, {"players": []}, 3, info, td, weeks, w.now.date())
    after = ml.rosters_after(w, rows, [], 4)
    nxt = av.with_rosters(after["rosters"], after["il"], tags)
    games = {d: 5 for d in every}
    return (hs.build_grid_tab(av, MGRS, [d for d in WK[3] if d >= w.now.date()], 4, games),
            hs.build_grid_tab(nxt, MGRS, WK[4], 4, games),
            hs.build_grid_tab(av, MGRS, WK[4], 4, games), after)


def cells(tab_, m):
    return [int(c["n"]) for c in next(r for r in tab_["rows"] if r["manager"] == m)["cells"]]


def test_next_weeks_grid_counts_a_pending_claim_drop_and_il_placement_and_this_week_does_not_move():
    w = make_world(now=lat("2026-11-05"), tags={"Pat Benton01": "O"})
    rows = []
    enter(w, rows, "Nick move: +Desmond Bane -Pat Nick01")
    enter(w, rows, "Garrett move: -Pat Garrett01")
    enter(w, rows, "Benton move: IL+Pat Benton01")
    # Bane's team plays only Monday 11-09 of week 4
    this_, nxt, base_next, after = grid_pair(w, rows, plays_only={"Desmond Bane": [D(11, 9)]})
    this0, _, _, _ = grid_pair(w, [], plays_only={"Desmond Bane": [D(11, 9)]})
    assert this_ == this0                                                   # this week's don't move
    assert after["lines"] == ["Benton: move Pat Benton01 into an IL slot", "Nick: drop Pat Nick01",
                              "Garrett: drop Pat Garrett01", "Nick: add Desmond Bane"]   # the checklist's order
    assert [a - b for a, b in zip(cells(nxt, "Garrett"), cells(base_next, "Garrett"))] == [-1] * 7
    assert [a - b for a, b in zip(cells(nxt, "Benton"), cells(base_next, "Benton"))] == [-1] * 7
    assert [a - b for a, b in zip(cells(nxt, "Nick"), cells(base_next, "Nick"))] == [0] + [-1] * 6
    assert cells(nxt, "Hayden") == cells(base_next, "Hayden")


def test_a_settled_or_closed_entry_does_not_move_next_weeks_grid():
    w = make_world(now=lat("2026-11-05"))
    rows = []
    enter(w, rows, "Garrett move: -Pat Garrett01")
    applied = [{"row": "state", "entry": 1, "state": "applied"}]
    assert ml.rosters_after(w, rows, applied, 4)["lines"] == []
    late = make_world(now=lat("2026-11-09", 19, 0))                        # after the 11-09 window closed
    assert ml.rosters_after(late, rows, [], 4)["lines"] == []


def test_the_next_week_grid_reads_no_ledger_mode():
    import inspect
    for fn in (hs.next_week_availability, ml.rosters_after):
        assert "mode(" not in inspect.getsource(fn)                       # a fact in both modes


# =============================================================================
# the real build with a scratch ledger (never written: read_rows patched)
# =============================================================================

@pytest.fixture(scope="module", params=["shadow", "on"])
def real_with_ledger(request):
    from modules import player_actuals
    from modules.league_clock import league_now
    from modules.data_loader import load_all_data
    needed = [ROOT / "data" / "player_actuals.json", ROOT / "output" / "title_odds_latest.json",
              ROOT / "output" / "tag_records.jsonl", ROOT / "data" / "transaction_log.jsonl"]
    if not all(p.exists() for p in needed):
        pytest.skip("league state not in this checkout (the hub's real inputs)")
    if (ROOT / ml.LEDGER_FILE).exists():
        pytest.skip("a real move ledger exists: this test layers a scratch one over an empty ledger")
    mp = pytest.MonkeyPatch()
    now = league_now()
    try:
        base = hs.build(ROOT, now=now, allow_engine_mismatch=True)
    except (hs.HubInputError, player_actuals.ActualsError) as e:
        mp.undo()
        pytest.skip(f"the hub's real inputs are not current today ({e})")
    data = load_all_data(ROOT, current_week=None)
    world = ml.World.from_base(ROOT, now, data=data)
    fa = [r["name"] for r in base["free_agents"]["rows"] if r["status"] == "healthy" and not r["tags"]]
    stash = [r["name"] for r in base["stash"]["rows"]]
    if not fa or not stash:
        mp.undo()
        pytest.skip("no healthy free agent or no stash candidate today")
    drop_n = sorted(n for n in world.rosters["Nick"] if n not in world.il.get("Nick", []))[0]
    drop_h = sorted(n for n in world.rosters["Hayden"] if n not in world.il.get("Hayden", []))[0]
    rows = []
    try:
        rows.append(ml.make_entry(world, f"Nick move: +{fa[0]} -{drop_n}", rows, [], entered_by="test"))
        rows.append(ml.make_entry(world, f"Hayden move: +{stash[0]} -{drop_h}", rows, [], entered_by="test"))
    except ml.EntryRefused as e:
        mp.undo()
        pytest.skip(f"the scratch claims are refused today ({e})")
    mp.setattr(ml, "read_rows", lambda base_path=".": [dict(r) for r in rows])
    mp.setattr(ml, "read_states", lambda base_path=".": [])
    if request.param == "on":
        mp.setattr(ml, "mode", lambda cfg=None: "on")
    try:
        led = hs.build(ROOT, now=now, allow_engine_mismatch=True)
    finally:
        mp.undo()
    return {"base": base, "led": led, "fa": fa[0], "stash": stash[0], "drop_n": drop_n, "drop_h": drop_h,
            "mode": request.param, "data": data, "now": now, "rows": rows}


def test_real_a_chat_claimed_stash_candidate_leaves_the_stash_and_the_free_agents(real_with_ledger):
    r = real_with_ledger
    assert r["stash"] not in [x["name"] for x in r["led"]["stash"]["rows"]]
    assert r["stash"] not in [x["name"] for x in r["led"]["free_agents"]["rows"]]
    assert r["fa"] not in [x["name"] for x in r["led"]["free_agents"]["rows"]]
    # the chat-dropped players are listed, available from the window
    for n in (r["drop_n"], r["drop_h"]):
        row = next(x for x in r["led"]["free_agents"]["rows"] if x["name"] == n)
        assert row["tags"][0]["text"].startswith("available from ")
        if r["led"]["free_agents"]["mode"] == "ahead":
            assert row["g1"].isdigit()


def test_real_next_weeks_grid_moves_by_the_claim_and_drop_and_this_weeks_does_not(real_with_ledger):
    from modules.schedule_strength import build_player_info_map, augment_player_info_from_lineups
    from modules import tag_records
    r = real_with_ledger
    b_this, b_next = r["base"]["grid"]["tabs"]
    l_this, l_next = r["led"]["grid"]["tabs"]
    assert b_this == l_this
    assert l_next["note"].startswith("As rosters stand with pending moves")
    assert f"Nick: add {r['fa']}" in l_next["note"] and f"Nick: drop {r['drop_n']}" in l_next["note"]
    for m in ("Garrett", "Benton"):
        assert [x for x in l_next["rows"] if x["manager"] == m] == [x for x in b_next["rows"] if x["manager"] == m]
    # Nick: + the claimed player's playable days, - the dropped player's
    data = r["data"]
    info = build_player_info_map(data.playerlist)
    augment_player_info_from_lineups(info, data.get_current_rosters(), data.lineups)
    tag_row = tag_records.latest(ROOT)
    tags = dict(tag_records.hub_tags(tag_row, [n for v in data.get_current_rosters().values() for n in v]))
    tags.update({n: t for n, t in hs.free_agent_tags(tag_row, [r["fa"]]).items() if tag_records.kept_for_hub(t)})
    av = hs.Availability.from_data(data, {"x": [r["fa"], r["drop_n"]]}, {}, tags, data.injury_overrides,
                                   r["led"]["week"], info, r["now"].date())
    days = [date.fromisoformat(d["date"]) for d in l_next["days"]]
    want = [int(av.plays(r["fa"], d)) - int(av.plays(r["drop_n"], d)) for d in days]
    nick = lambda tab_: [int(c["n"]) for c in next(x for x in tab_["rows"] if x["manager"] == "Nick")["cells"]]  # noqa
    assert [a - b for a, b in zip(nick(l_next), nick(b_next))] == want


def test_real_this_weeks_adds_used_agree_between_the_power_table_and_the_moves(real_with_ledger):
    p = real_with_ledger["led"]
    wk = next(t for t in p["moves"]["weeks"] if t["key"] == p["moves"]["default"])
    power = {x["manager"]: x["adds"].split(" / ")[0] for x in p["power"]["rows"]}
    for u in wk["used"]:
        assert u["text"].split(" ")[1] == power[u["manager"]], (u, power)
    # on mode counts the scratch claims the moment they are posted; shadow does not
    base_power = {x["manager"]: int(x["adds"].split(" / ")[0]) for x in real_with_ledger["base"]["power"]["rows"]}
    led_power = {x["manager"]: int(x["adds"].split(" / ")[0]) for x in p["power"]["rows"]}
    delta = 1 if real_with_ledger["mode"] == "on" else 0
    assert led_power["Nick"] == base_power["Nick"] + delta and led_power["Hayden"] == base_power["Hayden"] + delta
    pend = [x for t in p["moves"]["weeks"] for x in t["items"] if x.get("kind") == "ledger"]
    assert {x["who"] for x in pend} == {"Nick", "Hayden"} and all(x["state"] == "Pending" for x in pend)
    assert all(x in wk["items"] for x in pend)                                # under their claim week


def test_real_payload_mode_follows_the_clock_against_this_weeks_close(real_with_ledger):
    from modules import price_lock
    from modules.simulator_betting import schedule_week_dates
    p, data, now = real_with_ledger["led"], real_with_ledger["data"], real_with_ledger["now"]
    close = price_lock.window_close(schedule_week_dates(data)[p["week"]][0], data.nba_schedule)
    fa = p["free_agents"]
    if now < close:
        assert fa["mode"] == "this" and fa["cols"] == ["GL", "Next"]
    else:
        assert fa["mode"] == "ahead" and fa["weeks"][0] == p["week"] + 1
