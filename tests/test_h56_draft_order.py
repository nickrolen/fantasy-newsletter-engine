"""
tests/test_h56_draft_order.py -- H56 (Nick, 11-20): Yahoo's pick ORDER for the
2017-18 to 2023-24 drafts is punted; who drafted whom and who kept whom stay;
2018-19's list is dropped (claude/HANDOFF_56_DRAFT_ORDER_PUNT_2026-11-20.md,
claude/LEAGUE_RULES.md "Drafts and keepers by season").

A. The accessor (modules/draft_history): the order or None by season, from
   config; nothing else reads all_drafts.json for it (a grep).
B. Live rounds by draft, from config (2027-28's 10th round holds 3 picks).
C. History > Draft: a punted season by team, no pick numbers; 2018-19's note.
D. Cards: no slot for a punted season.
E. Records: none uses a punted season's order (hub, newsletter, cards, writer).
F. Keepability: the refit's features, and the refit reproducible (slow).
G. Lore, awards, DRAFT_OVR, the pick-value curve.
H. Real state (slow; skipped without it): the publish check passes and no
   punted season's pick number is in any published piece's visible text.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from modules import draft_history as DH                     # noqa: E402

CFG = {"draft_history": {"order_trusted_from": "2024-25", "drafts_dropped": ["2018-19"],
                         "live_rounds": {"2021-22": 7, "2025-26": 7, "2026-27": 9},
                         "live_rounds_default": {"from": "2027-28", "rounds": 10, "last_round_picks": 3}}}


def _pick(season, n, rnd, m, name, keeper=False):
    return {"season": season, "pick_number": n, "round": rnd, "manager": m, "player_key": str(n),
            "player_name": name, "is_keeper": keeper}


RAW = [_pick("2023-24", 1, 1, "Nick", "Mikal Bridges"), _pick("2023-24", 10, 3, "Garrett", "Victor Wembanyama"),
       _pick("2023-24", 40, 10, "Hayden", "Kept Guy", True), _pick("2018-19", 1, 1, "Benton", "Wrong Guy"),
       _pick("2024-25", 2, 1, "Garrett", "Karl-Anthony Towns"), _pick("2024-25", 1, 1, "Benton", "James Harden")]


# =============================================================================
# A. the accessor
# =============================================================================

def test_the_order_is_none_for_every_punted_season_and_kept_for_trusted_ones():
    rows = DH.apply_rule(RAW, CFG)
    assert DH.order("2023-24", rows, CFG) is None and DH.order("2018-19", rows, CFG) is None
    assert [p["player_name"] for p in DH.order("2024-25", rows, CFG)] == ["James Harden", "Karl-Anthony Towns"]
    assert [p["slot"] for p in DH.with_slots(DH.order("2024-25", rows, CFG))] == ["1.01", "1.02"]
    for s in ("2017-18", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"):
        assert not DH.order_trusted(s, CFG)
    for s in ("2024-25", "2025-26", "2026-27", "2031-32"):
        assert DH.order_trusted(s, CFG)


def test_a_punted_season_keeps_who_drafted_and_kept_whom_and_loses_its_numbers():
    before = copy.deepcopy(RAW)
    rows = DH.apply_rule(RAW, CFG)
    assert RAW == before                                            # the input is not changed
    p23 = [p for p in rows if p["season"] == "2023-24"]
    assert {(p["manager"], p["player_name"], p["is_keeper"]) for p in p23} == {
        ("Nick", "Mikal Bridges", False), ("Garrett", "Victor Wembanyama", False), ("Hayden", "Kept Guy", True)}
    assert all(p["pick_number"] is None and p["round"] is None for p in p23)
    assert [p["manager"] for p in p23] == ["Garrett", "Hayden", "Nick"]   # by manager: no trace of Yahoo's order
    assert not any(p["season"] == "2018-19" for p in rows)               # dropped
    assert DH.apply_rule(rows, CFG) == rows                              # idempotent


def test_the_rule_is_required_never_defaulted():
    with pytest.raises(DH.DraftHistoryError):
        DH.rules({})
    bad = copy.deepcopy(CFG)
    del bad["draft_history"]["order_trusted_from"]
    with pytest.raises(DH.DraftHistoryError):
        DH.rules(bad)
    assert DH.rules()["order_trusted_from"] == "2024-25"                  # the real config states it
    assert DH.rules()["drafts_dropped"] == ["2018-19"]


def test_the_real_file_is_unedited_and_read_through_the_rule():
    raw = json.loads((ROOT / DH.DRAFTS_FILE).read_text(encoding="utf-8"))
    assert any(p["season"] == "2023-24" and p["pick_number"] is not None for p in raw)   # Yahoo's record stays
    rows = DH.read(ROOT)
    assert not any(p["season"] == "2018-19" for p in rows)
    assert all(p["pick_number"] is None for p in rows if p["season"] < "2024-25")
    assert all(p["pick_number"] is not None for p in rows if p["season"] >= "2024-25")
    keepers = {(p["season"], p["manager"], p["player_name"]) for p in raw if p["is_keeper"]}
    assert keepers == {(p["season"], p["manager"], p["player_name"]) for p in rows if p["is_keeper"]}


# Writers of Yahoo's record (they rewrite all_drafts.json, never read its order for
# anything shown), and files that only name it (a list of inputs for a cache key).
_ALLOWED = {
    "modules/draft_history.py": "the accessor",
    "scripts/pull_historical_data.py": "writer: re-pulls drafts from Yahoo",
    "scripts/pull_current_draft.py": "writer: patches the season's draft",
    "scripts/rollup_season_to_history.py": "writer: appends a finished season's draft",
    "scripts/backfill_draft_names.py": "writer: backfills names",
    "modules/hub_cards.py": "names the file in the cards' input list (a cache key), reads nothing",
}
_PATH = re.compile(r'(/\s*["\']all_drafts\.json["\']|["\'][^"\']*/all_drafts\.json["\']|\{[^}]*\}/all_drafts\.json)')


def test_no_reader_opens_all_drafts_json_except_the_accessor():
    found = []
    for d in ("modules", "scripts"):
        for f in sorted((ROOT / d).rglob("*.py")):
            rel = f.relative_to(ROOT).as_posix()
            if "__pycache__" in rel:
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if _PATH.search(line) and rel not in _ALLOWED:
                    found.append(f"{rel}:{i}: {line.strip()}")
    assert found == [], found


# =============================================================================
# B. live rounds by draft
# =============================================================================

def test_live_rounds_come_from_config_and_2027_28s_tenth_round_holds_three():
    assert DH.live_rounds("2021-22", CFG) == 7 and DH.live_rounds("2026-27", CFG) == 9
    assert DH.live_rounds("2027-28", CFG) == 10 and DH.live_rounds("2030-31", CFG) == 10
    assert DH.picks_in_round("2027-28", 10, 4, CFG) == 3 and DH.picks_in_round("2027-28", 9, 4, CFG) == 4
    assert DH.picks_in_round("2026-27", 9, 4, CFG) == 4
    with pytest.raises(DH.DraftHistoryError):
        DH.picks_in_round("2026-27", 10, 4, CFG)                       # a keeper round, not live
    with pytest.raises(DH.DraftHistoryError):
        DH.live_rounds("2020-21", CFG)                                 # a snake draft: never valued
    with pytest.raises(DH.DraftHistoryError):
        DH.live_rounds("2022-23", CFG)                                 # not stated: raises, never guessed
    real = DH.rules()
    assert real["live_rounds"]["2026-27"] == 9 and real["live_rounds_default"]["last_round_picks"] == 3
    src = (ROOT / "modules" / "draft_history.py").read_text(encoding="utf-8")
    assert not re.search(r"return\s+(7|9|10)\b", src)                  # no literal round counts


# =============================================================================
# C. History > Draft
# =============================================================================

def _league_inputs():
    import test_hub_v2_league as TL
    inp = TL._inputs()
    extra = [_pick("2023-24", i + 1, 1 + i // 4, m, f"{m} Old{i}") for i, m in enumerate(["Marcus", "Tyler", "Dana", "Jordan"] * 2)]
    extra += [_pick("2023-24", 9, 3, "Dana", "Dana Keeper", True), _pick("2018-19", 1, 1, "Tyler", "Gone Guy"),
              _pick("2017-18", 1, 1, "Marcus", "First Guy")]
    # 5d1: the fixture now has its own punted 2023-24 (for the tap sweep); this test's 2023-24 replaces it
    inp["all_drafts"] = [p for p in inp["all_drafts"] if p["season"] != "2023-24"] + extra
    return inp


def test_a_punted_season_renders_by_team_with_no_pick_numbers_and_2018_19_its_note():
    from modules.hub_v2 import league as L, page_league as PL
    inp = _league_inputs()
    _, h = L.build(inp)
    by = {s["season"]: s for s in h["draft"]["seasons"]}
    assert by["2025-26"]["mode"] == "order" and by["2025-26"]["rows"][0]["pick"] == "1.01"
    s23 = by["2023-24"]
    assert s23["mode"] == "by_team" and s23["order_note"] == DH.PUNTED_NOTE
    assert all(r["pick"] == "" and r["overall"] == "" for r in s23["rows"])
    assert [r["m"] for r in s23["rows"]] == sorted(r["m"] for r in s23["rows"])     # each team's class together
    dana = [r for r in s23["rows"] if r["m"] == "Dana"]
    assert [r["keeper"] for r in dana] == [False, False, True]                      # keepers apart, last
    assert by["2018-19"]["mode"] == "dropped" and by["2018-19"]["rows"] == []
    assert by["2018-19"]["order_note"] == DH.DROPPED_NOTE
    html = PL._draft(_view_draft(h, inp))
    sec = re.search(r'data-spick-of="draft\|2023-24"(.*?)</section>', html, re.S).group(1)       # 5d1 s.8
    assert "v2-lg-dr--team" in sec and "pick order for this season isn" in sec
    assert not re.search(r'<td class="lh-num">\d+\.\d\d', sec) and 'data-colh="draft|pick"' not in sec
    drop = re.search(r'data-spick-of="draft\|2018-19"(.*?)</section>', html, re.S).group(1)
    assert "doesn" in drop and "<table" not in drop


def _view_draft(h, inp):
    teams = {m: {"cls": f"lh-chip--{m.lower()}", "href": "#", "team": f"{m}'s team", "manager": m}
             for m in inp["teams"]}
    return dict(h["draft"], seasons=[dict(s, rows=[dict(r, team=teams.get(r["m"]), href="#") for r in s["rows"]])
                                     for s in h["draft"]["seasons"]])


def test_the_draft_joins_ovr_on_manager_and_player_never_on_the_pick_number():
    from modules.hub_v2 import league as L
    inp = _league_inputs()
    inp["draft_ovr"]["seasons"]["2023-24"] = {"season": "2023-24", "open": "2023-10-24", "deadline": "2024-02-08",
                                              "picks": [{"manager": "Tyler", "player": "Tyler Old1", "is_keeper": False,
                                                         "then": 81, "then_reason": None, "later": 77,
                                                         "later_reason": None}]}
    _, h = L.build(inp)
    s23 = next(s for s in h["draft"]["seasons"] if s["season"] == "2023-24")
    r = next(x for x in s23["rows"] if x["player"] == "Tyler Old1")
    assert (r["then"], r["later"]) == ("81", "77")
    assert next(x for x in s23["rows"] if x["player"] == "Marcus Old0")["then_why"] == "not in the cache"


# =============================================================================
# D. cards
# =============================================================================

def test_a_card_has_no_slot_for_a_punted_season():
    from modules import player_card_builder as PCB
    pv = {"measures": {"fppg": {"rounds": {"1": {"value": 40.0, "n": 8, "basis": "data"}}}}}   # the round table
    career = {"season_breakdown": [{"season": "2023-24", "gp": 60, "fppg": 50.0},
                                   {"season": "2024-25", "gp": 60, "fppg": 45.0}]}
    out = PCB._build_draft_history("X", [{"season": "2023-24", "pick_number": None, "round": None, "manager": "Garrett",
                                          "is_keeper": False},
                                         {"season": "2024-25", "pick_number": 3, "round": 1, "manager": "Nick",
                                          "is_keeper": False}], career, pv)
    assert out[0]["pick_number"] is None and out[0]["roi"] is None and out[0]["expected_fppg"] is None
    assert out[1]["roi"] == 5.0
    src = (ROOT / "modules" / "hub_v2" / "card.py").read_text(encoding="utf-8")
    assert "Drafted' } by" not in src and "'Kept' if d.get('is_keeper') else 'Drafted'" in src
    modal = (ROOT / "modules" / "player_card_modal.py").read_text(encoding="utf-8")
    assert "d.pick_number ? 'Rd '" in modal


def test_the_card_text_says_drafted_by_for_a_punted_season():
    from modules.hub_v2 import card as C
    import inspect
    src = inspect.getsource(C)
    i = src.index('if d.get("pick_number") is None:')
    assert "Drafted" in src[i:i + 200] and "Round" not in src[i:i + 120]


# =============================================================================
# E. records
# =============================================================================

def test_no_record_shows_a_punted_seasons_pick_position():
    from modules.hub_v2 import league as L
    import test_hub_v2_league as TL
    inp = TL._inputs()
    for key in L.PICK_POSITION_RECORDS:
        rows = inp["records_alltime"][f"{key}_top10"]
        rows[0] = dict(rows[0], season="2021-22", player_name="Punted Guy")
    _, h = L.build(inp)
    shown = [x for g in h["records"]["groups"] for lst in g["lists"] if lst["key"] in L.PICK_POSITION_RECORDS
             for x in lst["rows"]]
    assert shown and not any(x["player"] == "Punted Guy" for x in shown)
    assert all(x["rank"] in ("1", "2") for x in shown)                          # ranked again from 1


def test_the_newsletters_steal_and_bust_lists_skip_punted_seasons():
    from modules import report_builder as RB
    import inspect
    src = inspect.getsource(RB)
    assert set(RB.PICK_POSITION_TOP10) == {"biggest_draft_steal_top10", "biggest_draft_bust_top10",
                                            "biggest_draft_steal_totalfp_top10", "biggest_draft_bust_totalfp_top10"}
    assert "_dh.order_trusted(e.get(\"season\"))" in src


def test_the_record_writer_values_only_trusted_slots_and_classes_need_no_order():
    sys.path.insert(0, str(ROOT / "scripts"))
    import backfill_player_records as B
    games = []
    for s, name, m in (("2023-24", "Old Star", "Nick"), ("2024-25", "New Star", "Nick")):
        games += [{"player_name": name, "manager": m, "season": s, "fantasy_points": 60.0} for _ in range(30)]
    drafts = [{"season": "2023-24", "pick_number": None, "round": None, "manager": "Nick", "player_name": "Old Star",
               "is_keeper": False},
              {"season": "2024-25", "pick_number": 20, "round": 5, "manager": "Nick", "player_name": "New Star",
               "is_keeper": False}]
    out = B.compute_draft_manager_leaderboards(games, drafts, pick_games=games)     # 5d1: the pick game set, given
    assert [e["player_name"] for e in out["biggest_draft_steal_top10"]] == ["New Star"]
    with pytest.raises(ValueError):
        B.compute_draft_manager_leaderboards(games, [dict(drafts[0], player_name=f"P{i}") for i in range(8)],
                                             pick_games=games)


def test_the_card_record_book_skips_punted_steals():
    from modules import player_card_builder as PCB
    at = {"biggest_draft_steal_top10": [{"player_name": "X", "season": "2023-24", "delta": 9.0},
                                        {"player_name": "X", "season": "2025-26", "delta": 5.0}],
          "best_season_fppg_top10": [{"player_name": "X", "season": "2023-24", "fppg": 60.0}]}
    got = PCB._find_record_book_appearances("X", at)
    assert [g["season"] for g in got if "Steal" in g["record"]] == ["2025-26"]
    assert [g["season"] for g in got if "Steal" not in g["record"]] == ["2023-24"]


# =============================================================================
# F. keepability
# =============================================================================

def test_rank_unknown_and_undrafted_come_from_who_drafted_whom():
    from modules import keepability_v3 as M
    from types import SimpleNamespace as NS
    punted = NS(kept=False, undrafted=False, draft_rank=None)
    ranked = NS(kept=False, undrafted=False, draft_rank=50)
    free = NS(kept=False, undrafted=True, draft_rank=None)
    kept = NS(kept=True, undrafted=False, draft_rank=None)
    f = M.FEATURES
    assert [f["rank_unknown"](c, {}) for c in (punted, ranked, free, kept)] == [1.0, 0.0, 0.0, 0.0]
    assert [f["undrafted"](c, {}) for c in (punted, ranked, free, kept)] == [0.0, 0.0, 1.0, 0.0]
    assert f["log_draft_rank"](punted, {}) == 0.0 and f["log_draft_rank"](ranked, {}) != 0.0


def test_the_shipped_parameters_are_r0_chosen_after_the_preregistered_check():
    p = json.loads((ROOT / "config" / "keepability_v3_params.json").read_text(encoding="utf-8"))
    # Nick, 11-21: R0 (no draft rank), chosen over R1 after the pre-registered check
    assert p["features"] == ["kept", "undrafted", "level", "availability", "age"]
    assert p["specification"] == "age linear, no draft rank (H56)" and "chose this (R0)" in p["why"]
    sys.path.insert(0, str(ROOT / "scripts"))
    import fit_keepability_v3 as F
    assert F.SPECS["age linear, no draft rank (H56)"] == p["features"]
    assert F.SPECS["age linear, rank unknown (H56)"][3] == "rank_unknown"          # R1 kept, not shipped


def test_a_punted_seasons_candidates_have_no_rank_and_still_know_they_were_drafted():
    from modules import keeper_history as kh
    inputs = kh.Inputs.load(ROOT)
    assert "2018-19" not in inputs.picks
    assert all(p["pick_number"] is None for s in ("2020-21", "2023-24") for p in inputs.picks[s])
    snap = kh.snapshot(inputs, "2024-25", "end", ages=None)                # season 2023-24, punted
    drafted = [c for c in snap.candidates if c.drafted]
    assert drafted and all(c.draft_rank is None and c.draft_pick is None and c.draft_round is None for c in drafted)
    assert all(not c.undrafted for c in drafted)
    snap = kh.snapshot(inputs, "2026-27", "end", ages=None)                # season 2025-26, trusted
    assert any(c.draft_rank for c in snap.candidates)


@pytest.mark.slow
def test_the_refit_reproduces_from_its_inputs():
    sys.path.insert(0, str(ROOT / "scripts"))
    import fit_keepability_v3 as F
    p = json.loads((ROOT / "config" / "keepability_v3_params.json").read_text(encoding="utf-8"))
    snaps = F.dataset(ROOT, use_cache=False)
    assert F.dataset_hash(snaps, p["features"] + [p["level_prior"]["spec"]]) == p["dataset_sha256"]


# =============================================================================
# G. lore, awards, DRAFT_OVR, the pick-value curve
# =============================================================================

def test_the_lore_never_uses_a_punted_round_and_2018_19_is_its_opening_rosters():
    from modules import lore as L
    import inspect
    assert 'd.get("round") is None' in inspect.getsource(L.scan)
    rows = [{"season_key": "2018-19", "date": "2018-10-17", "manager": "Nick", "player_name": "A", "player_id": 1},
            {"season_key": "2018-19", "date": "2018-10-16", "manager": "Nick", "player_name": "B", "player_id": 2},
            {"season_key": "2018-19", "date": "2018-10-16", "manager": "Nick", "player_name": "B", "player_id": 2},
            {"season_key": "2019-20", "date": "2019-10-22", "manager": "Nick", "player_name": "C", "player_id": 3}]
    got = DH.opening_day_stand_ins(rows, CFG)
    assert [(p["season"], p["player_name"], p["source"], p["is_keeper"], p["round"]) for p in got] == \
        [("2018-19", "B", "opening_day_roster", False, None)]


def test_a_bust_exclusion_for_a_punted_pick_says_drafted():
    from modules import awards as A
    import inspect
    src = inspect.getsource(A._busts)
    assert 'else "drafted"' in src


def test_draft_ovr_has_no_order_for_punted_seasons_and_no_2018_19():
    from modules import draft_ovr
    c = draft_ovr.load(ROOT)
    assert c["schema"] == 4 and "2018-19" not in c["seasons"]
    for s, e in c["seasons"].items():
        has = ["pick_number" in p for p in e["picks"]]
        assert all(has) if DH.order_trusted(s) else not any(has), s


def test_one_pick_curve_by_round_from_trusted_finished_drafts():
    """H56 s.4.3, decision 4 (Nick 11-21): DRAFT_ROUND_VALUES.json replaces the
    per-pick DRAFT_PICK_VALUES.json; nothing reads the old file."""
    from modules import draft_values as DV
    t = DV.load(ROOT)
    assert t["drafts"] == ["2024-25", "2025-26"] and t["picks"] == 56
    for m in DV.MEASURES:
        rounds = t["measures"][m]["rounds"]
        assert sorted(map(int, rounds)) == list(range(1, 11))                    # every live round of any draft
        assert all(rounds[str(r)]["basis"] == "curve (no data)" for r in (8, 9, 10))
        vals = [rounds[str(r)]["value"] for r in range(1, 11)]
        assert vals == sorted(vals, reverse=True)                                # later rounds are worth less
    with pytest.raises(DV.DraftValuesError):
        DV.value(t, "par", 11)
    for d in ("modules", "scripts"):
        for f in (ROOT / d).rglob("*.py"):
            if "__pycache__" in str(f) or f.name == "build_draft_pick_values.py":
                continue
            assert not re.search(r"[\"']([^\"']*/)?DRAFT_PICK_VALUES\.json[\"']", f.read_text(encoding="utf-8")), f


def test_the_curve_shrinks_toward_the_log_fit_and_says_what_backs_each_round():
    from modules import draft_values as DV
    lines = [{"season": "x", "round": r, "starts": 10, "par": 100.0 / r + d, "fp": 300.0 + 10 * d}
             for r in (1, 2, 3) for d in (-5, 0, 5)]
    out = DV.round_values(lines, 4)
    par = out["par"]["rounds"]
    assert par["1"]["n"] == 3 and par["4"]["n"] == 0 and par["4"]["basis"] == "curve (no data)"
    assert par["4"]["value"] == par["4"]["curve"]
    with pytest.raises(DV.DraftValuesError):
        DV.round_values([lines[0]], 4)                                            # one round: no curve


@pytest.mark.slow
def test_the_round_values_equal_a_rebuild():
    from modules import draft_values as DV
    fresh = json.loads(json.dumps(DV.build(ROOT)))
    assert fresh == DV.load(ROOT)


# =============================================================================
# H. real state
# =============================================================================

from test_5b import real                                       # noqa: E402,F401 -- the real build, guarded, once


@pytest.mark.slow
def test_real_no_punted_pick_number_in_any_published_piece(real, tmp_path):
    from modules import hub_cards, team_pictures
    from modules.hub_v2 import data as v2data, publish_check as PC
    p, po, ro = real
    draft = po["league_history"]["draft"]
    by = {s["season"]: s for s in draft["seasons"]}
    assert by["2018-19"]["mode"] == "dropped"
    assert all(by[s]["mode"] == "by_team" for s in by if s < "2024-25" and s != "2018-19")
    pub = v2data.attach_players(copy.deepcopy(p), po)
    cards = hub_cards.build(ROOT, p, echo=lambda *a, **k: None)
    pics, _n = team_pictures.data_uris(ROOT, list(pub["v2"]["team_order"]))
    rep = PC.check(ROOT, pub, cards, tmp_path / "publish", pictures=pics, keep_shown=True)
    assert rep["ok"], rep["problems"]
    bad = []
    for where, html in rep["shown"].items():
        for m in re.finditer(r'<b>(\d{4}-\d{2})</b><span class="lh-sub">((?:Round \d+, pick \d+|Pick \d+)[^<]*)', html):
            if not DH.order_trusted(m.group(1)):
                bad.append((where, m.group(0)))
        # 5d1 s.8: each season's draft is its own section (a past one in its own part)
        for m in re.finditer(r'<h2 class="lh-eyebrow">(\d{4}-\d{2}) draft</h2>(.*?)</section>', html, re.S):
            if not DH.order_trusted(m.group(1)) and re.search(r'<td class="lh-num">\d+\.\d\d', m.group(2)):
                bad.append((where, m.group(1)))
        if re.search(r"P\d+ \(R\d+\)", PC.visible_text(html)):
            bad.append((where, "P(R)"))
    assert bad == []
