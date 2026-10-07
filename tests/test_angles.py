"""Angle selector: unusualness x consequence, recency only breaks ties."""

import json
import pytest
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from modules import angles as A  # noqa: E402

M = ["Nick", "Hayden", "Benton", "Garrett"]
PAIRS = [[("Nick", "Hayden"), ("Benton", "Garrett")],
         [("Nick", "Benton"), ("Hayden", "Garrett")],
         [("Nick", "Garrett"), ("Hayden", "Benton")]]


def _season(name, weeks=21, seed=0, fixed=None):
    rng = random.Random(seed)
    out = []
    for w in range(1, weeks + 1):
        for a, b in PAIRS[w % 3]:
            sa, sb = rng.gauss(1600, 150), rng.gauss(1600, 150)
            if fixed and (w, a, b) in fixed:
                sa, sb = fixed[(w, a, b)]
            out.append({"season": name, "week": w, "manager_a": a,
                        "manager_b": b, "score_a": sa, "score_b": sb})
    return out


HIST = A.History.build(
    [m for i in range(9) for m in _season(f"20{10 + i}-{11 + i}", seed=i)],
    lambda s: 21)


def test_history_is_prior_seasons_only(tmp_path):
    (tmp_path / "data" / "historical").mkdir(parents=True)
    allm = _season("2024-25", seed=1) + _season("2025-26", seed=2)
    (tmp_path / "data" / "historical" / "all_matchups.json").write_text(
        json.dumps(allm))
    sm, prior = A.season_matchups(tmp_path, "2025-26", 5)
    assert {m["season"] for m in prior} == {"2024-25"}
    assert max(m["week"] for m in sm) == 5


def test_same_swing_matters_more_late():
    """A 300-point week moves the Cup race more with 2 weeks left than 20."""
    def cons(week):
        fixed = {(week, *PAIRS[week % 3][0]): (1900, 1600),
                 (week, *PAIRS[week % 3][1]): (1600, 1600)}
        sm = [m for m in _season("x", fixed=fixed, seed=5)]
        for m in sm:
            if m["week"] < week:
                m["score_a"] = m["score_b"] = 1600.0
        return A.consequence(sm, week, 21, 21, HIST.sigma)
    a, b = PAIRS[1 % 3][0][0], PAIRS[20 % 3][0][0]
    assert cons(20)[b]["cup"] > cons(1)[a]["cup"]


def test_blowout_scores_on_cup_squeaker_on_standings():
    """Nick, 10-07: the blowout's points move Cup seeding; the squeaker's
    result moves the standings. Same week, everything else level."""
    w = 18
    (a1, b1), (a2, b2) = PAIRS[w % 3]
    fixed = {(w, a1, b1): (2100, 1600), (w, a2, b2): (1603, 1600)}
    sm = _season("x", fixed=fixed, seed=3)
    for m in sm:
        if m["week"] < w:
            m["score_a"], m["score_b"] = (1601.0, 1600.0) if m["week"] % 2 \
                else (1600.0, 1601.0)
    c = A.consequence(sm, w, 21, 21, HIST.sigma)
    assert c[a1]["cup"] > c[a2]["cup"]


def test_dead_race_has_no_consequence_and_the_week_has_no_lead():
    sm = _season("x", seed=4)
    fixed = {"Nick": 3000.0, "Hayden": 2500.0, "Benton": 2000.0,
             "Garrett": 1500.0}     # every race decided long ago
    for m in sm:
        m["score_a"], m["score_b"] = fixed[m["manager_a"]], \
            fixed[m["manager_b"]]
    c = A.consequence(sm, 21, 21, 21, HIST.sigma)
    assert c["Nick"]["cup"] < 1e-6 and c["Nick"]["standings"] < 1e-6
    sel = A.run_week(sm, 21, HIST, 21, 21)
    assert sel["dead"] and "moved" in sel["dead"]
    assert any("Title race" in x for x in sel["race_state"])
    md = A.render_markdown(sel)
    assert "NO LEAD THIS WEEK" in md and "Do NOT" in md


def test_more_chances_means_less_unusual():
    assert A._u(0.05, 1000, 4) < A._u(0.05, 1000, 1)


def test_recency_only_breaks_ties():
    def ang(fam, mgr, sc):
        a = A.Angle(fam, (mgr,), f"{fam} {mgr}", 1.0)
        a.score = sc
        return a
    clear = [ang("score", "Nick", 1.0), ang("streak", "Hayden", 0.5)]
    ranked, moved = A.rank(clear, {("score", "Nick"): 20})
    assert ranked[0].managers == ("Nick",) and moved == 0
    tied = [ang("score", "Nick", 1.0), ang("streak", "Hayden", 0.99)]
    ranked, moved = A.rank(tied, {("score", "Nick"): 20,
                                  ("streak", "Hayden"): 3})
    assert ranked[0].managers == ("Hayden",) and moved == 2


def test_a_game_angle_counts_both_teams_a_subject_angle_only_him():
    cons = {"Nick": {"cup": 0.0, "standings": 0.0, "bracket": 0.0},
            "Benton": {"cup": 0.4, "standings": 0.0, "bracket": 0.0}}
    game = A.Angle("margin", ("Nick", "Benton"), "g", 1.0)
    lead = A.Angle("standings", ("Nick", "Benton"), "s", 1.0)
    A.score([game, lead], cons)
    assert game.consequence == 0.4 and lead.consequence == 0.0


def test_replay_2025_26_runs_and_is_deterministic():
    import angles_report
    r1, *_ = angles_report.replay(ROOT, "2025-26")
    r2, *_ = angles_report.replay(ROOT, "2025-26")
    assert [s["lead"]["text"] for *_, s in r1] == \
        [s["lead"]["text"] for *_, s in r2]
    assert len(r1) == 23 and all(s["lead"] for *_, s in r1)


def test_report_still_builds_when_angles_fail(tmp_path):
    import format_stats_report as fmt
    block = fmt.build_angles_block(tmp_path, {"metadata": {"week": 3}}, None,
                                   3, tmp_path / "x.md")
    assert "unavailable" in block


def test_2025_26_postseason_leads_with_the_bracket():
    """The 4 seed knocking out the 17-4 1 seed, then the title, are the
    stories of weeks 22-23 -- not a team's -33% score."""
    import angles_report
    rows, *_ = angles_report.replay(ROOT, "2025-26")
    leads = {w: s["lead"]["text"] for w, _, s in rows}
    assert leads[22].startswith(
        "Hayden (4 seed) knocked Nick (1 seed) out of the semifinals")
    assert leads[23] == "Garrett (3 seed) won the playoff championship over Hayden (4 seed)"
    # an expected title is still the title: a decisive game is never "no lead"
    assert not dict((w, s["dead"]) for w, _, s in rows)[23]


def test_bracket_stakes_come_from_the_payouts():
    """Champion collects, 3rd and 4th both pay: semis and final are
    decisive (1), the third-place game decides nothing (0)."""
    br = next(b for b in A.bracket_structure("2026-27")
              if b["stage"] == "playoffs")
    v = br["values"]
    sw = {k: abs(A._expected(v, k, 1.0) - A._expected(v, k, 0.5))
          for k in ("semis", "final", "third")}
    assert sw["semis"] == sw["final"] > 0 and sw["third"] == 0
    cup = next(b for b in A.bracket_structure("2026-27") if b["stage"] == "cup")
    cw = {k: abs(A._expected(cup["values"], k, 1.0) -
                 A._expected(cup["values"], k, 0.5)) for k in ("semis", "final")}
    assert cw["semis"] * 2 == cw["final"]


def test_best_of_three_series_odds():
    assert A._p_series(0, 0, 2) == 0.5
    assert A._p_series(1, 0, 2) == 0.75
    assert A._p_series(2, 1, 2) == 1.0


def test_a_score_is_a_points_story_a_streak_a_wins_story():
    cons = {"Nick": {"cup": 0.3, "standings": 0.2, "bracket": 0.0}}
    sc = A.Angle("score", ("Nick",), "s", 1.0)
    st = A.Angle("streak", ("Nick",), "t", 1.0)
    A.score([sc, st], cons)
    assert sc.parts["standings"] == 0 and sc.consequence == 0.3
    assert st.parts["cup"] == 0 and st.consequence == 0.2


def test_a_margin_gets_one_bite_not_two():
    """Nick, 10-07: summing the Cup and standings terms let margins -- the
    only angle eligible for both -- lead 11 of 23 weeks on arithmetic."""
    cons = {"Nick": {"cup": 0.3, "standings": 0.3, "bracket": 0.0},
            "Hayden": {"cup": 0.3, "standings": 0.3, "bracket": 0.0}}
    mg = A.Angle("margin", ("Nick", "Hayden"), "m", 1.0)
    sc = A.Angle("score", ("Nick",), "s", 1.0)
    A.score([mg, sc], cons)
    assert mg.consequence == sc.consequence == 0.3


def test_last_weeks_lead_again_is_scored_on_what_is_new():
    """Weeks 4 and 5 of 2025-26 led with "Garrett scored X, -18%" twice."""
    import angles_report
    rows, *_ = angles_report.replay(ROOT, "2025-26")
    by = {w: s for w, _, s in rows}
    assert "Garrett scored" in by[4]["lead"]["text"]
    g5 = next(a for a in by[5]["all"] if a["text"].startswith("Garrett scored"))
    assert g5["repeat"] and "continues last week's lead" in g5["text"]
    assert not by[5]["lead"]["text"].startswith("Garrett scored")


def test_a_streak_extended_is_news_only_by_the_extension():
    p = HIST.p_streak_again(6)
    assert 0 < p < 1 and A._u(p, 1000) < A._u(A._tail_ge(HIST.runs, 6), 1000)


def test_the_title_clinch_leads_its_week():
    """Nick, 10-07: "Nick locks up the championship" should lead the week
    it happened -- week 18 of 2025-26, with 3 weeks left."""
    import angles_report
    rows, *_ = angles_report.replay(ROOT, "2025-26")
    by = {w: s for w, _, s in rows}
    assert by[18]["lead"]["text"].startswith(
        "Nick clinched the regular-season title")
    # the final day settles who pays, on the tiebreak (both 10-11)
    assert "Garrett will finish 3rd or 4th in the regular season" in \
        by[21]["lead"]["text"]


def test_the_title_race_is_a_standing_thread_every_week():
    import angles_report
    rows, *_ = angles_report.replay(ROOT, "2025-26")
    for w, _, s in rows:
        if w <= 21:
            md = A.render_markdown(s)
            assert "Title race" in md, w


def test_decided_is_exact_and_ties_wait_for_the_tiebreak():
    sm = []
    for w in range(1, 4):
        for (a, b), (sa, sb) in zip(PAIRS[w % 3], [(2, 1), (2, 1)]):
            sm.append({"season": "x", "week": w, "manager_a": a,
                       "manager_b": b, "score_a": sa, "score_b": sb})
    st = A.decided_status(sm, 2, 4)
    assert not any(ev == "clinched_title" for ev, _ in st)
    lead, need = A.magic_number(sm, 2, 4)
    assert need >= 1
    final = A.final_order(sm, 3)
    assert len(final) == 4


def test_live_2026_27_path_from_schedule_and_records(tmp_path):
    """In season, this season's games aren't in all_matchups.json yet: they
    come from SCHEDULE.json pairings and RECORDS.json weekly scores, on the
    2026-27 clock (15-week regular season, Cup race through 21)."""
    import shutil
    (tmp_path / "data" / "historical").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "output").mkdir()
    shutil.copy(ROOT / "data" / "historical" / "all_matchups.json",
                tmp_path / "data" / "historical")
    sm = _season("2026-27", weeks=3, seed=2)
    sched = {"weeks": [{"week": w, "start_date": "2026-10-19",
                        "matchups": [{"manager_a": a, "manager_b": b}
                                     for a, b in PAIRS[w % 3]]}
                       for w in (1, 2, 3)]}
    rec = {"weekly_scores": {}}
    for m in sm:
        for side in ("a", "b"):
            rec["weekly_scores"].setdefault(m[f"manager_{side}"], []).append(
                {"week": m["week"], "score": m[f"score_{side}"]})
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(sched))
    (tmp_path / "config" / "RECORDS.json").write_text(json.dumps(rec))
    sel = A.for_report(tmp_path, "2026-27", 3, [])
    assert sel["lead"] is not None
    assert any("Title race (12 weeks left)" in x for x in sel["race_state"])
    assert any("weeks 1-21" in x for x in sel["race_state"])


def test_every_liability_line_names_its_pot_and_window():
    """Nick, 10-07: never "safe from paying" or "certain to pay"
    unqualified. Before the semis resolve, an unqualified "safe" is false."""
    terms = A._pot_terms(15)
    for ev, tmpl in A.DECIDED_TEXT.items():
        line = tmpl.format(m="Nick", rec="9-3", left=3, payers="3rd or 4th",
                           **terms)
        assert "weeks 1-15" in line and "$" in line, ev
        if ev in ("safe_from_paying", "will_pay"):
            assert "playoff pot is still open" in line, ev
        assert "safe from paying" not in line and "certain to pay" not in line


def test_a_tied_bracket_week_goes_to_the_higher_seed():
    g = {"manager_a": "Hayden", "manager_b": "Nick", "score_a": 1500.0,
         "score_b": 1500.0}
    assert A._game_winner(g, {"Nick": 1, "Hayden": 4}, "higher_seed") == "Nick"
    with pytest.raises(ValueError):
        A._game_winner(g, {"Nick": 1, "Hayden": 4}, "coin_flip")


def test_third_place_stakes_come_from_config(monkeypatch):
    import modules.data_loader as dl
    br = next(b for b in A.bracket_structure("2026-27") if b["stage"] == "playoffs")
    assert br["values"][3] == br["values"][4]          # pride only, for now
    cup = next(b for b in A.bracket_structure("2026-27") if b["stage"] == "cup")
    assert any(r["kind"] == "third" for r in cup["rounds"])
