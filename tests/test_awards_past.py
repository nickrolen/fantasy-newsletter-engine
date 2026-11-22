"""4c6 part B: past seasons' awards for the record book (modules/awards_past,
scripts/build_awards_past.py, data/historical/AWARDS_PAST.json).

A. A season with its own regular-season length: the awards stop at its
   regular_through; wins swung count against the OFFICIAL scores; a trade
   after the regular season is out with its reason.
B. The file: its schema, best(), the script's refusal outside
   data/historical/.
C. The display: Past winners in each award's card (from the side file, never
   the payload), the Records tiles with their tooltips.
D. Real state (slow; skipped without it): 2019-20's missing bracket, 2025-26
   against 4c5's hand-checked week, and the whole build into a temp folder
   equal to the committed file.
"""
import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from modules import awards as A, awards_past as P, keeper_history as kh

ROOT = Path(__file__).resolve().parents[1]


# =============================================================================
# A. a season of its own length
# =============================================================================

def _past(reg=3, bump=None):
    """awards_fixture's season run as a PAST season whose regular season is
    weeks 1..reg (its weeks 4 and 5 are then its playoffs), official scores
    equal to the log's started totals unless bumped."""
    import awards_fixture as AF
    i = AF.inp()
    rows = i["rows"]
    mat = []
    tot = {}
    for r in rows:
        if r["started"]:
            k = (int(r["week"]), r["manager"])
            tot[k] = tot.get(k, 0.0) + float(r["fantasy_points"])
    for w in i["weeks"]:
        for mu in w["matchups"]:
            a, b = mu["manager_a"], mu["manager_b"]
            sa, sb = round(tot.get((w["week"], a), 0.0), 2), round(tot.get((w["week"], b), 0.0), 2)
            if bump and (w["week"], b) in bump:
                sb = round(sb + bump[(w["week"], b)], 2)
            mat.append({"season": AF.SEASON, "week": w["week"], "manager_a": a, "manager_b": b,
                        "score_a": sa, "score_b": sb})
    from modules.data_loader import _LEAGUE_CONFIG
    cfg = copy.deepcopy(_LEAGUE_CONFIG)
    cfg["awards"].update(AF.CFG)
    cfg["season_structure"] = {AF.SEASON: {"regular_through": reg, "bracket": True}}
    pi = P.season_inputs(i["inputs"], AF.SEASON, mat, cfg=cfg, lp=i["lp"], quantile=0.0, tie=0.5,
                         nba=AF.nba_ctx())
    return i, pi, mat


def test_a_season_stops_at_its_own_regular_season():
    i, pi, _mat = _past(reg=3)
    out = P.season_awards(pi)
    assert out["regular_weeks"] == 3 and out["through"] == A._week(pi, 3)["end_date"]
    assert sorted(int(w) for w in out["R"]) == [1, 2, 3]
    mvp = out["awards"]["mvp"]["winner"]
    full = A.compute(i, A._week(i, 3)["end_date"])            # the same award, cut at week 3 by this season's engine
    assert mvp["label"] == full["awards"]["mvp"]["rows"][0]["label"]
    assert mvp["value"] == pytest.approx(round(full["awards"]["mvp"]["rows"][0]["value"], 2))
    # weeks 4-5 (its playoffs) never count
    later = A.compute(i, A._week(i, 4)["end_date"])
    assert later["awards"]["mvp"]["rows"][0]["value"] != pytest.approx(mvp["value"])


def test_wins_swung_count_against_the_official_scores():
    """Make every regular-season week a 0.01-point OFFICIAL win for the MVP's
    team: without him each week with positive PAR is lost, so his wins
    swung are exactly those weeks -- whatever the log's own totals say."""
    _i, pi, _mat = _past(reg=3)
    end = A._week(pi, 3)["end_date"]
    top = A.compute(pi, end, only=("mvp",))["awards"]["mvp"]["rows"][0]
    R = A.compute(pi, end, only=("mvp",))["R"]
    week_par = {}
    for r in pi["rows"]:
        if r["started"] and kh.appeared(r) and r["player_name"] == top["key"] and int(r["week"]) <= 3:
            k = (int(r["week"]), r["manager"])
            week_par[k] = week_par.get(k, 0.0) + r["fantasy_points"] - R[int(r["week"])]["R"]
    off = copy.deepcopy(pi["official_totals"])
    for (w, m) in week_par:
        opp = A._opponent(A._week(pi, w), m)
        off[w][opp] = round(off[w][m] - 0.01, 2)
    got = A.compute(dict(pi, official_totals=off), end, only=("mvp",))["awards"]["mvp"]["rows"]
    him = next(r for r in got if r["key"] == top["key"])
    assert him["swung"] == sum(1 for v in week_par.values() if v > 0.01) >= 1
    assert len(week_par) >= 2


def test_a_trade_after_the_regular_season_is_out_with_its_reason():
    i, pi, _ = _past(reg=2)                                # the fixture's trade (week 3) is now after it
    out = P.season_awards(pi)
    assert out["awards"]["trade"]["winner"] is None and out["awards"]["trade"]["none"] == "no regular-season trade"
    res = A.compute(pi, A._week(pi, 2)["end_date"], only=P.PAST)
    assert any(e["kind"] == "after the regular season" for e in res["awards"]["trade"]["excluded"])


def test_season_inputs_raise_on_a_missing_week():
    import awards_fixture as AF
    i = AF.inp()
    from modules.data_loader import _LEAGUE_CONFIG
    cfg = copy.deepcopy(_LEAGUE_CONFIG)
    cfg["season_structure"] = {AF.SEASON: {"regular_through": 3}}
    with pytest.raises(P.AwardsPastError, match="missing"):
        P.season_inputs(i["inputs"], AF.SEASON, [], cfg=cfg, lp=i["lp"], quantile=0.0, tie=0.5, nba=AF.nba_ctx())


def test_most_improved_reads_the_league_log_in_a_past_season():
    i, pi, _ = _past(reg=3)
    assert pi["fppg_source"] == "log" and pi["act_by_id"] == {}
    (g, pts), why = A._actual(pi, "Marcus Star", None, A._week(pi, 3)["end_date"])
    mine = [r for r in pi["rows"] if r["player_name"] == "Marcus Star" and kh.appeared(r)
            and r["date"] <= A._week(pi, 3)["end_date"]]
    assert why is None and g == len(mine) and pts == pytest.approx(sum(r["fantasy_points"] for r in mine))


# =============================================================================
# B. the file
# =============================================================================

def test_the_files_schema():
    import awards_fixture as AF
    b = AF.past_blob()
    P.validate(b)
    assert b["best"]["mvp"]["season"] == "2025-26" and b["best"]["trade"]["season"] == "2024-25"
    for bad in (lambda x: x.update(schema=1), lambda x: x["seasons"]["2024-25"]["awards"].pop("trade"),
                lambda x: x["seasons"]["2024-25"]["awards"]["mvp"].update(winner=None),
                lambda x: x["seasons"]["2024-25"]["awards"]["mvp"]["top"].append(dict(x["seasons"]["2024-25"]["awards"]["mvp"]["top"][0], value=9e9)),
                lambda x: x.pop("best")):
        y = copy.deepcopy(b)
        bad(y)
        with pytest.raises(P.AwardsPastError):
            P.validate(y)


def test_write_refuses_outside_data_historical(tmp_path):
    import awards_fixture as AF
    b = AF.past_blob()
    for out in (tmp_path / "AWARDS_PAST.json", tmp_path / "data" / "AWARDS_PAST.json",
                tmp_path / "data" / "historical" / ".." / "x.json", Path("..") / "x.json"):
        with pytest.raises(P.AwardsPastError, match="refused"):
            P.write(b, out, tmp_path)
    p = P.write(b, Path("data") / "historical" / "AWARDS_PAST.json", tmp_path)
    assert P.load(tmp_path) == json.loads(p.read_text(encoding="utf-8"))


def test_the_script_refuses_outside_data_historical_before_building(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_awards_past.py"), "--out",
                        str(tmp_path / "x.json")], capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert r.returncode == 1 and "REFUSED" in r.stdout and not (tmp_path / "x.json").exists()


def test_the_committed_file_is_valid_and_public():
    """data/historical/AWARDS_PAST.json, when built: valid, ASCII, and not a
    state file (public history, committed like DRAFT_OVR.json)."""
    from modules import state_manifest
    p = ROOT / P.FILE
    if not p.is_file():
        pytest.skip("not built on this machine")
    P.validate(json.loads(p.read_text(encoding="utf-8")))
    p.read_bytes().decode("ascii")
    assert not state_manifest.load(ROOT).contains(P.FILE.as_posix())


# =============================================================================
# C. the display
# =============================================================================

def _hub():
    from test_hub_v2 import synth_payload
    return synth_payload()


def test_past_winners_ride_in_the_side_file_and_show_in_each_awards_card():
    from datetime import datetime
    from modules.hub_v2 import view, page, page_league as PL
    p = _hub()
    assert "awards_past" not in p["v2"]["league"]["awards"]          # off the payload
    past = p["v2"]["league_history"]["awards_past"]
    assert set(past["by_award"]) == set(P.PAST) and past["error"] == ""
    vm = view.build(p, mode="preview", now=datetime.fromisoformat(p["generated_at"]))
    h = PL.awards_html(vm["league"]["awards"], page._mono, page._chart, page.INFO)
    for k in P.PAST:
        sec = re.search(rf'data-award="{k}".*?</section>', h, re.S).group(0)
        assert "<summary" in sec and "Past winners" in sec
    trade = re.search(r'data-award="trade".*?</section>', h, re.S).group(0)
    assert "no regular-season trade" in trade and "2025-26" in trade
    mvp = re.search(r'data-award="mvp".*?</section>', h, re.S).group(0)
    assert "Tyler Star" in mvp and "wins swung: 2.5" in mvp and "1,810.2" in mvp
    assert "Zone Defense Zone Defense" not in mvp                     # that season's name only when it differs
    for k in ("pickup", "roy", "bust"):                                # 4c7: every award has its past
        assert "Past winners" in re.search(rf'data-award="{k}".*?</section>', h, re.S).group(0)
    assert "Past winners, 2024-25 to 2025-26" in h


def test_records_get_one_tile_per_award_with_its_tooltip():
    from modules.hub_v2 import page_league as PL
    from test_hub_v2 import tap_violations
    p = _hub()
    rec = p["v2"]["league_history"]["records"]
    assert [t["key"] for t in rec["award_tiles"]] == [f"award_{k}" for k in P.PAST] + [
        "award_lineup", "award_draft", "award_waiver", "award_unlucky", "award_potw_wins", "award_potw_week"]
    t = rec["award_tiles"][0]
    # MVP ranks per regular-season week (Nick, 11-19): 1,810.2 PAR over 21 weeks
    assert t["value"] == "86.2 PAR a week" and t["ctx"].endswith("1,810.2 PAR over 21 weeks") \
        and t["tip"]["f"].endswith("per regular-season week")
    from modules.hub_v2 import view
    h = PL.chip_html(view.league_history(p, {m: dict(v) for m, v in p["v2"]["teams"].items()}), "records", None)
    sec = re.search(r'data-section="award-records".*?</section>', h, re.S).group(0)
    assert sec.count('class="v2-lg-tile"') == 12 and sec.count("data-tip-h=") == 12 and "aria-label=" in sec
    assert not tap_violations("<body>" + sec + "</body>")


def test_without_the_file_the_awards_and_records_say_so():
    import hub_v2_league_fixture as LF
    from modules.hub_v2 import league as L
    i = LF.inputs(_hub())
    i["awards_past"], i["awards_past_error"] = None, "Past seasons' awards are not built yet (x)."
    lg, hist = L.build(i)
    assert hist["awards_past"] == {"error": "Past seasons' awards are not built yet (x).", "by_award": {}, "note": ""}
    assert hist["records"]["award_tiles"] == [] and "not built" in hist["records"]["award_note"]


# =============================================================================
# D. real state
# =============================================================================

def _needs():
    import league_state
    return league_state.needs_state("data/historical/HISTORICAL_PLAYERLOG.json", "data/historical/all_matchups.json",
                                    "config/keepability_v3_params.json", why="past seasons, from the league log")


@pytest.mark.slow
@_needs()
def test_real_2019_20_has_no_bracket_and_its_awards_stop_at_week_19():
    from modules.data_loader import _LEAGUE_CONFIG
    from modules import keepability_v3 as M
    inputs = kh.Inputs.load(ROOT)
    mat = json.loads((ROOT / "data/historical/all_matchups.json").read_text(encoding="utf-8"))
    assert _LEAGUE_CONFIG["season_structure"]["2019-20"]["bracket"] is False
    pi = P.season_inputs(inputs, "2019-20", mat, cfg=_LEAGUE_CONFIG, lp=M.level_config(M.load_params()),
                         quantile=0.0, tie=0.5)
    assert pi["reg"] == 19 and max(int(w["week"]) for w in pi["weeks"]) == 19     # nothing after it was played
    out = P.season_awards(pi)
    assert out["regular_weeks"] == 19 and out["awards"]["mvp"]["winner"] is not None
    assert out["checks"]["short_weeks"] == [17] and out["checks"]["flips"] == 0


@pytest.mark.slow
@_needs()
def test_real_2025_26_matches_4c5s_hand_checked_week():
    """2025-26 week 12 (4C5_RESULT): Nick 1,713.20 beat Benton 1,708.05;
    Doncic's 3 starts (149.90) swapped for R = 27.011 flip it. In the past
    build his 2025-26 wins swung include that week, and the official totals
    equal the log's (0 of 84 team-weeks differ), so the counts are 4c5's."""
    from modules.data_loader import _LEAGUE_CONFIG
    from modules import keepability_v3 as M
    inputs = kh.Inputs.load(ROOT)
    mat = json.loads((ROOT / "data/historical/all_matchups.json").read_text(encoding="utf-8"))
    pi = P.season_inputs(inputs, "2025-26", mat, cfg=_LEAGUE_CONFIG, lp=M.level_config(M.load_params()),
                         quantile=0.0, tie=0.5)
    assert P.checks(pi)["off"] == 0
    out = P.season_awards(pi)
    end = out["through"]
    res = A.compute(pi, end, only=("mvp",))
    luka = next(r for r in res["awards"]["mvp"]["rows"] if r["key"] == "Luka Doncic")
    assert pi["official_totals"][12]["Nick"] == 1713.20 and pi["official_totals"][12]["Benton"] == 1708.05
    assert res["R"][12]["R"] == pytest.approx(27.011, abs=5e-4)
    his = {}
    for r in pi["rows"]:
        if r["started"] and kh.appeared(r) and r["player_name"] == "Luka Doncic" and int(r["week"]) == 12:
            x = his.setdefault((12, r["manager"]), [0.0, 0])
            x[0] += r["fantasy_points"]
            x[1] += 1
    assert A.wins_swung(his, pi["official_totals"], pi, res["R"], [12]) == (1.0, 0.0)
    no_off = dict(pi, official_totals=None)
    log_based = next(r for r in A.compute(no_off, end, only=("mvp",))["awards"]["mvp"]["rows"]
                     if r["key"] == "Luka Doncic")
    assert log_based["swung"] == luka["swung"] >= 1
    top = out["awards"]["mvp"]["top"]
    assert any(r["label"] == "Luka Doncic" and r["swung"] == luka["swung"] for r in top)


@pytest.mark.slow
@_needs()
def test_real_past_awards_build_into_a_temp_folder_equals_the_committed_file(tmp_path):
    blob = P.build(ROOT)
    p = P.write(blob, Path("data") / "historical" / "AWARDS_PAST.json", tmp_path)
    assert sorted(blob["seasons"]) == P.seasons()
    committed = ROOT / P.FILE
    if committed.is_file():
        assert p.read_bytes() == committed.read_bytes()
