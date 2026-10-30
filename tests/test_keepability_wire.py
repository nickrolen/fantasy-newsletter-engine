"""Keepability v3, step C: wired into the weekly build.

HANDOFF_KEEPABILITY_C_WIRE_2026-10-29, section 4 (tests 1-7), plus the
consumers of sections 5-7: power rankings' keeper quality, the rumor mill's
value display and the player cards.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import advice as adv                           # noqa: E402
from modules import keepability_v3 as M                     # noqa: E402

MANAGERS = ("Benton", "Garrett", "Hayden", "Nick")
TIER_WORDS = ("Lock", "Strong Hold", "On the Bubble", "Sell High", "Stash", "Waiver Wire")


def _kw(n=10, week=3, line_k=None, cup_winner=None, first_time=True, shift=0.0):
    """A synthetic v3 keeper_watch: n players per team, probabilities from
    scores through the real model function."""
    scored = {m: [(f"{m} P{i}", 3.0 - 0.5 * i + (shift if i == 7 else 0.0)) for i in range(1, n + 1)]
              for m in MANAGERS}
    missing = {0: 0.3, 1: 0.5, 2: 0.2}
    p5 = M.probabilities_from_scores(scored, 5, missing)
    p6 = M.probabilities_from_scores(scored, 6, missing)
    players = []
    for m in MANAGERS:
        rows = sorted(({"player_name": nm, "manager": m, "score": s, "keep_k5": round(p5[m][nm], 4),
                        "keep_k6": round(p6[m][nm], 4), "level": 40.0 - i, "kept_this_season": i <= 6,
                        "age": 25} for i, (nm, s) in enumerate(scored[m], 1)),
                      key=lambda r: -r["keep_k5"])
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        players += rows
    kw = {"model": "keepability v3", "season": "2026-27", "decision": "2027-28", "week": week,
          "as_of": "2026-11-15", "as_of_point": "week2", "params": {}, "cup_winner": cup_winner,
          "line_k": line_k, "missing_keepers": missing, "players": players,
          "switch_weeks": M.switch_weeks("2026-27")}
    kw["summary"] = M.summary_facts(kw, None)
    kw["summary"]["first_time"] = first_time
    return kw


# ---------------------------------------------------------------------------
# 1. every rostered player, v3 probabilities; per roster they sum to <= K
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def live():
    from modules.data_loader import load_all_data
    from modules.report_builder import build_keeper_watch
    if not (ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").is_file():
        pytest.skip("history not present")
    data = load_all_data(ROOT)
    return data, build_keeper_watch(data, data.current_week)


def test_keeper_watch_holds_v3_probabilities_for_every_rostered_player(live):
    data, kw = live
    assert kw["model"] == "keepability v3" and kw["week"] == data.current_week
    rosters = {m: list(v) for m, v in data.get_current_rosters().items() if v}
    got = {(p["manager"], p["player_name"]) for p in kw["players"]}
    want = {(m, n) for m, v in rosters.items() for n in v}
    assert got == want and len(kw["players"]) == len(want)
    for m in rosters:
        mine = sorted((p for p in kw["players"] if p["manager"] == m), key=lambda p: p["rank"])
        assert [p["rank"] for p in mine] == list(range(1, len(mine) + 1))
        assert all(0.0 <= p["keep_k5"] <= p["keep_k6"] <= 1.0 for p in mine)
        assert [p["keep_k5"] for p in mine] == sorted((p["keep_k5"] for p in mine), reverse=True)
        # keepers not yet arrived: never MORE than K, and below it early on
        assert sum(p["keep_k5"] for p in mine) <= 5 + 1e-6
        assert sum(p["keep_k6"] for p in mine) <= 6 + 1e-6
    for p in kw["players"]:
        assert p["level"] is not None and p["age"] is not None and p["level_prior_kind"]


# ---------------------------------------------------------------------------
# 2. a missing history or parameters file raises; no v1 fallback
# ---------------------------------------------------------------------------

class _Data:
    def __init__(self, base):
        self.base_path = str(base)

    def get_current_rosters(self):
        return {"Nick": ["Luka Doncic"]}


def test_a_missing_history_raises(tmp_path):
    from modules.report_builder import build_keeper_watch
    with pytest.raises(M.KeepabilityInputError, match="HISTORICAL_PLAYERLOG"):
        build_keeper_watch(_Data(tmp_path), 3)


def test_a_missing_parameters_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "PARAMS_FILE", tmp_path / "nope.json")
    with pytest.raises(M.ParamsError, match="missing"):
        M.keeper_watch(_Data(ROOT), 3, root=ROOT)


def test_there_is_no_older_formula_to_fall_back_to():
    import modules.report_builder as rb
    assert not hasattr(rb, "_build_keeper_watch_v1")
    src = (ROOT / "modules" / "report_builder.py").read_text(encoding="utf-8")
    assert "build_keepability_report" not in src and "_build_keeper_watch_v1" not in src


# ---------------------------------------------------------------------------
# 3. the as-of model switches at the stated weeks
# ---------------------------------------------------------------------------

def test_the_as_of_model_switches_halfway():
    sw = M.switch_weeks("2026-27")                        # regular season through week 15
    assert sw == {"mid_week": 8, "regular_through": 15, "to_mid": 5, "to_end": 12}
    got = {w: M.as_of_point_for(w, "2026-27") for w in (1, 2, 4, 5, 11, 12, 15, 21)}
    assert got == {1: "week2", 2: "week2", 4: "week2", 5: "mid", 11: "mid",
                   12: "end", 15: "end", 21: "end"}
    sw = M.switch_weeks("2025-26")                        # 21 weeks: mid 11
    assert (sw["to_mid"], sw["to_end"]) == (7, 16)        # 6.5 -> 7; 16 exactly halfway -> end


# ---------------------------------------------------------------------------
# 4. the weekly snapshot is written once, never overwritten
# ---------------------------------------------------------------------------

def test_the_weekly_snapshot_is_written_once(tmp_path):
    kw = _kw(week=3)
    first = M.publish_snapshot(kw, tmp_path, published_at="2026-11-16T09:00:00")
    path = Path(first["path"])
    assert first["wrote"] and path.name == "2026-27_week03.json"
    before = path.read_bytes()
    again = M.publish_snapshot(kw, tmp_path)
    assert not again["wrote"] and "identical" in again["why"]
    changed = _kw(week=3, shift=2.0)
    refused = M.publish_snapshot(changed, tmp_path)
    assert not refused["wrote"] and "never rewritten" in refused["why"]
    assert path.read_bytes() == before
    rec = json.loads(before)
    assert {"player_name", "manager", "rank", "keep_k5", "keep_k6"} <= set(rec["players"][0])


def test_next_week_reads_the_last_published_week(tmp_path):
    M.publish_snapshot(_kw(week=2), tmp_path)
    M.publish_snapshot(_kw(week=3), tmp_path)
    assert M.latest_snapshot(tmp_path, "2026-27", 5)["week"] == 3
    assert M.latest_snapshot(tmp_path, "2026-27", 3)["week"] == 2
    assert M.latest_snapshot(tmp_path, "2026-27", 2) is None
    # player 7 jumps above the line on every team
    prev = M.latest_snapshot(tmp_path, "2026-27", 4)
    now = _kw(week=4, shift=2.0)
    sm = M.summary_facts(now, prev)
    assert not sm["first_time"] and sm["compared_with_week"] == 3
    ins = {c["player"] for c in sm["crossed"] if c["direction"] == "in"}
    outs = {c["player"] for c in sm["crossed"] if c["direction"] == "out"}
    assert ins == {f"{m} P7" for m in MANAGERS} and len(outs) == 4
    assert sm["risers"] and all(r["change"] > 0 for r in sm["risers"])
    assert sm["fallers"] and all(r["change"] < 0 for r in sm["fallers"])


# ---------------------------------------------------------------------------
# 5. Section 10 protects each manager's top 6 by v3; a stale stamp raises
# ---------------------------------------------------------------------------

def test_section10_protects_the_top_six_by_keep_chance():
    kw = _kw(week=3)
    rosters = {m: [p["player_name"] for p in kw["players"] if p["manager"] == m] for m in MANAGERS}
    prot, wk = adv.protected_keepers(kw, 3, rosters, {m: 6 for m in MANAGERS})
    assert wk == 3
    for m in MANAGERS:
        top6 = [p["player_name"] for p in sorted((p for p in kw["players"] if p["manager"] == m),
                                                  key=lambda p: -p["keep_k5"])][:6]
        assert prot[m] == top6
    with pytest.raises(ValueError, match="stale"):
        adv.protected_keepers(kw, 4, rosters, {m: 6 for m in MANAGERS})
    old = {"week": 3, "players": [{"player_name": "A", "manager": "Nick", "keepability_score": 70}]}
    with pytest.raises(ValueError, match="v3"):
        adv.protected_keepers(old, 3, {"Nick": ["A"]}, {"Nick": 6})


def test_c3_deltas_value_the_post_trade_roster():
    kw = _kw(week=3)
    kd = adv.keepability_index(kw)
    nick = [p["player_name"] for p in kw["players"] if p["manager"] == "Nick"]
    gar = [p["player_name"] for p in kw["players"] if p["manager"] == "Garrett"]
    # Nick sends his best for Garrett's 8th
    da = kd.side("Nick", nick, ["Nick P1"], ["Garrett P8"])
    after = [n for n in nick if n != "Nick P1"] + ["Garrett P8"]
    score = {p["player_name"]: p["score"] for p in kw["players"]}
    pa = M.probabilities_from_scores({"Nick": [(n, score[n]) for n in after]}, 5, kw["missing_keepers"])["Nick"]
    pb = {p["player_name"]: p["keep_k5"] for p in kw["players"]}
    assert da == pytest.approx(100 * (pa["Garrett P8"] - pb["Nick P1"]), abs=0.06)
    assert da < 0
    # an identical swap moves nothing
    assert kd.side("Nick", nick, ["Nick P8"], ["Garrett P8"]) == pytest.approx(0.0, abs=0.06)
    assert not adv.keepability_index(None)


# ---------------------------------------------------------------------------
# 6. nothing in the weekly build imports keepability_v2
# ---------------------------------------------------------------------------

WEEKLY_BUILD = ["modules.report_builder", "modules.advice_runner", "modules.advice",
                "modules.rumor_mill_analyzer", "modules.stats_corner_viz",
                "modules.player_card_builder", "modules.player_card_modal",
                "generate_stats_report", "format_stats_report", "newsletter_html_generator",
                "generate_player_card_preview"]


def test_no_module_in_the_weekly_build_imports_keepability_v2():
    code = ("import sys; sys.path.insert(0, 'scripts'); sys.path.insert(0, '.');\n"
            + "".join(f"import {m}\n" for m in WEEKLY_BUILD)
            + "print('modules.keepability_v2' in sys.modules)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       timeout=170)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip().splitlines()[-1] == "False"
    allowed = {"modules/keepability_v2.py", "scripts/keeper_backtest.py"}
    for f in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        rel = f.relative_to(ROOT).as_posix()
        if rel in allowed:
            continue
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from\s+\S*keepability_v2\s+import|import\s+\S*keepability_v2"
                             r"|from\s+\S+\s+import\s+keepability_v2)", src, re.M), rel


# ---------------------------------------------------------------------------
# 7. the keeper-watch render
# ---------------------------------------------------------------------------

def _rows(html):
    return re.findall(r'<tr class="sc-kw3-(row|line)"[^>]*>(.*?)</tr>', html, re.S)


def test_the_render_shows_eight_a_line_after_five_and_the_cup_label():
    from modules.stats_corner_viz import render_keeper_watch
    html = render_keeper_watch(_kw(), summary_html="<p>Summary.</p>")
    assert html.count('class="sc-kw3-row"') == 4 * 8
    assert html.count('class="sc-kw3-line"') == 4
    assert html.count("6 if he wins the Cup") == 4
    for team in re.findall(r'<div class="sc-kw3-team".*?</table>', html, re.S):
        kinds = [k for k, _ in _rows(team)]
        assert kinds == ["row"] * 5 + ["line"] + ["row"] * 3
        rows = [body for k, body in _rows(team) if k == "row"]
        assert "6 if he wins the Cup" in rows[5]
        assert all("6 if he wins the Cup" not in r for i, r in enumerate(rows) if i != 5)
    assert "<p>Summary.</p>" in html
    assert "one in" in html                               # the early-season note, first week
    for w in TIER_WORDS:
        assert w not in html, w


def test_once_the_cup_is_decided_the_line_sits_at_each_teams_count():
    from modules.stats_corner_viz import render_keeper_watch
    kw = _kw(line_k={"Benton": 5, "Garrett": 6, "Hayden": 5, "Nick": 5}, cup_winner="Garrett",
             first_time=False)
    html = render_keeper_watch(kw)
    assert "6 if he wins the Cup" not in html and "one in" not in html
    for team in re.findall(r'<div class="sc-kw3-team".*?</table>', html, re.S):
        kinds = [k for k, _ in _rows(team)]
        at = 6 if 'data-manager="Garrett"' in team else 5
        assert kinds.index("line") == at


def test_a_report_from_before_v3_renders_no_keeper_watch():
    from modules.stats_corner_viz import render_keeper_watch
    old = {"players": [{"player_name": "A", "manager": "Nick", "keeper_tier": "Lock",
                        "keepability_score": 70.0}]}
    assert render_keeper_watch(old) == ""


def test_the_drafters_summary_is_lifted_into_the_panel():
    import newsletter_html_generator as g
    md = ("**Top Available Free Agents**\n\n| a |\n|---|\n| 1 |\n\nCommentary.\n\n"
          "**Keeper Watch**\n\nBenton's line is the most crowded: Boozer 31%, Mitchell 30%.\n"
          "Still the first paragraph.\n\nA second paragraph.\n")
    out = g.keeper_watch_summary_html(md)
    assert out.count("<p>") == 2 and "Still the first paragraph." in out
    assert "Boozer" not in g.parse_section(md, "Stats Corner")


def test_the_drafter_gets_the_facts_and_the_language_rule():
    import format_stats_report as F
    lines = "\n".join(F.format_keeper_watch_facts(_kw()))
    assert "KEEPER WATCH -- SUMMARY FACTS" in lines and "Most crowded line" in lines
    assert "6 if he wins the Cup" in lines
    tmpl = (ROOT / "templates" / "newsletter_template.md").read_text(encoding="utf-8")
    assert "**Keeper Watch**" in tmpl and "never certainty" in tmpl and "never choose" in tmpl


# ---------------------------------------------------------------------------
# sections 5-7: power rankings, rumor mill, cards
# ---------------------------------------------------------------------------

def test_keeper_quality_is_the_expected_level_of_likely_keepers():
    from modules.report_builder import keeper_quality_from
    kw = _kw()
    q, top = keeper_quality_from(kw, MANAGERS)
    for m in MANAGERS:
        mine = [p for p in kw["players"] if p["manager"] == m]
        assert q[m] == round(sum(p["keep_k5"] * p["level"] for p in mine) / 5, 1)
        assert top[m] == [p["player_name"] for p in sorted(mine, key=lambda p: p["rank"])][:5]
    assert keeper_quality_from(None, MANAGERS) == ({}, {})
    with pytest.raises(ValueError):
        keeper_quality_from({"players": [{"player_name": "A", "manager": "Nick",
                                          "keepability_score": 70}]}, MANAGERS)


def test_rumor_mill_value_is_projected_production_with_keep_chance_beside():
    from types import SimpleNamespace
    from modules import rumor_mill_analyzer as R
    src = (ROOT / "modules" / "rumor_mill_analyzer.py").read_text(encoding="utf-8")
    assert "keepability_score" not in src and "keeper_tier" not in src
    p = SimpleNamespace(effective_fppg=41.24, projected_fppg=38.0)
    assert R.projected_production(p) == pytest.approx(41.24)
    assert R.projected_production(SimpleNamespace(effective_fppg=0, projected_fppg=38.0)) == 38.0
    idea = R.TradeIdea("Nick", "Garrett", ["A"], ["B"], "r", 1.0)
    tiers = {"Nick": {"all_sorted": [SimpleNamespace(player_name="A", effective_fppg=40.0, projected_fppg=39.0,
                                                     keep_k5=0.5, keep_rank=4)]},
             "Garrett": {"all_sorted": [SimpleNamespace(player_name="B", effective_fppg=35.0, projected_fppg=36.0,
                                                        keep_k5=0.2, keep_rank=7)]}}
    R._attach_values([idea], tiers)
    assert idea.values["A"] == {"proj_fppg": 40.0, "keep_k5": 0.5, "keep_rank": 4, "manager": "Nick"}


def test_the_card_shows_keep_chance_and_rank_on_his_team():
    from modules.player_card_builder import _keep_fields
    f = _keep_fields({"keep_k5": 0.4061, "keep_k6": 0.55, "rank": 4, "manager": "Garrett", "level": 43.9})
    assert f["keep_text"] == "41% to be kept — 4th on Garrett's roster"
    assert f["keep_k6_pct"] == "55%"
    assert _keep_fields({"keeper_tier": "Lock", "keepability_score": 70}) == {}
    modal = (ROOT / "modules" / "player_card_modal.py").read_text(encoding="utf-8")
    for w in ("Strong Hold", "On the Bubble", "keeper_tier"):
        assert w not in modal
