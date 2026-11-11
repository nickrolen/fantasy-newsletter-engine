"""
Hub polish 3 (tasks 48a-48h; claude/HANDOFF_HUB_POLISH3_2026-11-10.md):
the matchup views (Summary, Win %, Game flow, last week's), the win-%
history and its back-fill, the title-odds line chart, season points, the
stash's long absences, three free-agent columns, hidden round-trip drops.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from modules import hub_charts as hc, hub_matchups as hm, winprob_history as wh            # noqa: E402
from modules import hub_moves, hub_page, hub_state as hs                                    # noqa: E402
from test_hub import sample_payload, visible_text, payload_strings, GEN                     # noqa: E402
from test_hub_polish import contrast                                                        # noqa: E402

TZ = ZoneInfo("America/Los_Angeles")
D = lambda m, d: date(2026, m, d)                                                           # noqa: E731
TEAM = {"Nick": "Luka my Balls", "Benton": "Spayed for Cade", "Hayden": "Big Nik Energy",
        "Garrett": "Blink-183"}
MUS = [{"manager_a": "Nick", "manager_b": "Benton"}, {"manager_a": "Hayden", "manager_b": "Garrett"}]
CFG = {"blowout_win_pct": 95.0, "comeback_close_below": 40.0, "comeback_now_at": 50.0,
       "comeback_rise_points": 20.0, "comeback_rise_was_below": 50.0, "close_low": 35.0, "close_high": 65.0}


def _real(*paths):
    for p in paths:
        if not (ROOT / p).exists():
            pytest.skip(f"league state not in this checkout ({p})")


# =============================================================================
# 48a. the newsletter's paragraph
# =============================================================================

def table(rows):
    head = "<tr><th>Team</th><th>Spread</th><th>Total</th><th>Moneyline</th><th>Win Prob</th><th>Avg Score</th></tr>"
    body = "".join(f"<tr><td class=\"team-name\">{t}</td><td>{s}</td><td>{o}</td><td>{m}</td><td>50%</td>"
                   f"<td>1</td></tr>" for t, s, o, m in rows)
    return f'<div class="table-wrapper"><table class="betting-lines-table"><thead>{head}</thead><tbody>{body}</tbody></table></div>'


def issue(blocks, sections=1):
    sec = "".join(f'<div class="matchup-header">{h}</div>{table(r)}' + "".join(f"<p>{p}</p>" for p in ps)
                  for h, r, ps in blocks)
    one = f'<section id="betting-lines"><h2>Betting Lines</h2>{sec}</section>'
    return f"<html><body><section id='other'><p>x</p></section>{one * sections}</body></html>"


GOOD = [("Spayed for Cade vs Luka my Balls",
         [("Spayed for Cade", "+111.0", "u3200", "+205"), ("Luka my Balls", "-111.0", "o3200", "-205")],
         ["Nick is the <b>111.0-point</b> favorite.<!-- lore:benton_streak --> Benton gets 111.",
          "A second paragraph."]),
        ("Big Nik Energy vs Blink-183",
         [("Big Nik Energy", "+121.5", "o3140", "+230"), ("Blink-183", "-121.5", "u3140", "-230")],
         ["Garrett is the favorite."])]


def test_the_newsletter_blocks_match_either_order_text_only():
    by = hm.newsletter_blocks(issue(GOOD), MUS, TEAM, 3)
    nick = by[("Nick", "Benton")]
    assert nick["paragraphs"] == ["Nick is the 111.0-point favorite. Benton gets 111.", "A second paragraph."]
    assert nick["line"] == "Luka my Balls -111.0 / -205, O/U 3200"
    assert by[("Hayden", "Garrett")]["line"] == "Blink-183 -121.5 / -230, O/U 3140"
    assert "lore" not in json.dumps(list(by.values())) and "<" not in json.dumps(list(by.values()))


@pytest.mark.parametrize("html,match", [
    ("<html><section id='x'></section></html>", "no <section"),
    (issue(GOOD, sections=2), "2 betting-lines sections"),
    (issue(GOOD + [GOOD[0]]), "appear twice"),
    (issue([GOOD[0], ("Big Nik Energy vs Somebody", GOOD[1][1], ["x"])]), "matches no matchup"),
    (issue([GOOD[0]]), "has no block"),
])
def test_the_newsletter_parse_raises(html, match):
    with pytest.raises(hm.SummaryError, match=match):
        hm.newsletter_blocks(html, MUS, TEAM, 3)


def test_issue_n_previews_week_n_plus_1_and_before_archiving_it_waits(tmp_path):
    assert hm.monday_preview(tmp_path, 1, MUS, TEAM, {"issues": []})["state"] == "none"
    w = hm.monday_preview(tmp_path, 4, MUS, TEAM, {"issues": [{"week": 2, "plain": "x.html"}]})
    assert (w["state"], w["text"]) == ("waiting", "Monday's preview arrives with the newsletter.")


def test_the_real_week_3_issue_holds_week_4s_matchups():
    _real("output/hub_archive/index.json")
    from modules import hub_archive
    from modules.data_loader import MANAGER_TO_TEAM
    from modules.week_state import week_entry
    from modules.data_loader import load_all_data
    idx = hub_archive.load_index(ROOT)
    if not [e for e in idx["issues"] if int(e["week"]) == 3]:
        pytest.skip("issue 3 not archived here")
    sched = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    mus = [w for w in sched["weeks"] if int(w["week"]) == 4][0]["matchups"]
    pv = hm.monday_preview(ROOT, 4, mus, MANAGER_TO_TEAM, idx)
    assert pv["state"] == "issue" and set(pv["by"]) == {(m["manager_a"], m["manager_b"]) for m in mus}
    assert pv["by"][("Nick", "Benton")]["line"].startswith("Luka my Balls -111.0 / -205")
    assert all(p and "<" not in p for b in pv["by"].values() for p in b["paragraphs"])


# =============================================================================
# 48a. the night's paragraph
# =============================================================================

def facts(**kw):
    f = {"a": "Nick", "b": "Benton", "final": False, "banked_a": 500.0, "banked_b": 450.0, "win_a": 60.0,
         "win_b": 40.0, "leader": "Nick", "games_left_a": 30.2, "games_left_b": 28.9, "prev_a": 58.0,
         "prev_b": 42.0, "prev_leader": "Nick", "close_a": 61.0, "close_b": 39.0,
         "swing": {"day_name": "Tuesday", "pts_a": 250.5, "pts_b": 210.25,
                   "top_a": {"player": "Luka Doncic", "points": 61.5}, "top_b": {"player": "Cade Cunningham", "points": 50.0}},
         "out_a": "", "out_b": "", "last_day": False, "today_name": "Wednesday"}
    f.update(kw)
    f["_extra_numbers"] = [x for x in (f["out_a"], f["out_b"]) if x]          # as night_facts passes them
    if f["leader"] is not None and kw.get("leader") is None and "banked_a" in kw:
        f["leader"] = "Nick" if f["banked_a"] > f["banked_b"] else "Benton" if f["banked_b"] > f["banked_a"] else None
    return f


@pytest.mark.parametrize("kw,want", [
    ({"final": True}, "final"),
    ({"win_a": 96.0, "win_b": 4.0}, "blowout"),
    ({"win_a": 45.0, "win_b": 55.0, "close_b": 39.0, "prev_b": 50.0}, "comeback"),     # below 40 at close, now >= 50
    ({"win_a": 30.0, "win_b": 70.0, "close_b": 45.0, "prev_b": 49.0}, "comeback"),     # rose 21 since the last run
    ({"prev_leader": "Benton", "win_a": 55.0, "win_b": 45.0, "prev_b": 44.0, "close_b": 44.0}, "lead_change"),
    ({"win_a": 64.0, "win_b": 36.0}, "close"),
    # Nick, 11-10: a favourite's rise is no comeback (11-05: Hayden 53.8 -> 75.5) ...
    ({"win_a": 75.5, "win_b": 24.5, "prev_a": 53.8, "prev_b": 46.2, "close_a": 55.0, "close_b": 45.0}, "steady"),
    # ... the underdog's is (a 45 -> 66 rise), and Monday's big underdog who leads by Saturday stays one
    ({"win_a": 66.0, "win_b": 34.0, "prev_a": 45.0, "prev_b": 55.0, "close_a": 45.0, "close_b": 55.0}, "comeback"),
    ({"win_a": 62.0, "win_b": 38.0, "prev_a": 60.0, "prev_b": 40.0, "close_a": 25.0, "close_b": 75.0}, "comeback"),
    ({"win_a": 80.0, "win_b": 20.0, "prev_a": 78.0, "prev_b": 22.0, "close_a": 79.0, "close_b": 21.0}, "steady"),
])
def test_the_framing_is_the_first_that_applies(kw, want):
    assert hm.pick_framing(facts(**kw), CFG) == want


def test_every_framing_has_three_phrasings_and_the_choice_is_deterministic():
    assert all(len(v) >= 3 for v in hm.VARIANTS.values()) and set(hm.VARIANTS) == set(hm.FRAMINGS)
    f = facts()
    one = hm.night_paragraph(f, CFG, season="2026-27", week=4, day="2026-11-11")
    assert one == hm.night_paragraph(facts(), CFG, season="2026-27", week=4, day="2026-11-11")
    texts = {hm.night_paragraph(facts(), CFG, season="2026-27", week=4, day=f"2026-11-{d}")["text"]
             for d in range(10, 16)}
    assert len(texts) >= 2                                           # the hash varies the phrasing


def test_a_paragraph_is_two_to_four_sentences_with_no_causation():
    for kw in ({}, {"final": True}, {"win_a": 97.0, "win_b": 3.0}, {"out_a": "Nick is without A (2 of 3) for the rest of the week."}):
        t = hm.night_paragraph(facts(**kw), CFG, season="2026-27", week=4, day="2026-11-11")["text"]
        n = len(re.findall(r"[.!?](?:\s|$)", t))
        assert 2 <= n <= 4, t
        assert not re.search(r"\b(won it|because|thanks to|carried|due to)\b", t, re.I), t


def test_every_number_in_a_paragraph_is_in_its_inputs_and_a_planted_one_raises(monkeypatch):
    p = hm.night_paragraph(facts(), CFG, season="2026-27", week=4, day="2026-11-11")
    for x in hm.NUMBER.findall(p["text"]):
        assert x in " ".join(p["numbers"]), x
    hm.check_numbers("Nick leads by 50.0.", {"50.0"})
    with pytest.raises(hm.SummaryError, match="42"):
        hm.check_numbers("Nick leads by 50.0 with 42 to go.", {"50.0"})
    monkeypatch.setitem(hm.VARIANTS, "steady", ["{lead} leads {trail} by 999.9, {ls_} to {ts_}."] * 3)
    with pytest.raises(hm.SummaryError, match="999.9"):
        hm.night_paragraph(facts(win_a=80.0, win_b=20.0, prev_a=79.0, prev_b=21.0, close_a=79.0, close_b=21.0),
                           CFG, season="2026-27", week=4, day="2026-11-11")


def test_the_margin_is_the_difference_of_the_printed_scores():
    t = hm.night_paragraph(facts(banked_a=1561.84, banked_b=1422.46, final=True, close_a=None, close_b=None),
                           CFG, season="2026-27", week=1, day="2026-10-25")["text"]
    assert "1,561.8" in t and "1,422.5" in t and "139.3" in t


def test_the_framing_config_is_required():
    with pytest.raises(hm.SummaryError, match="matchup_framing"):
        hm.framing_config({"hub": {}})
    with pytest.raises(hm.SummaryError, match="close_high"):
        hm.framing_config({"hub": {"matchup_framing": {**CFG, "close_high": "x"}}})
    assert hm.framing_config() == CFG                                   # the starting values (Nick to tune)


def test_out_text():
    assert hm.out_text("Nick", [("A B", 3, 3, None), ("C D", 1, 2, "11-14")]) == \
        "Nick is without A B (all 3 of his games) and C D (1 of 2, back 11-14) for the rest of the week."


# =============================================================================
# 48b. the win-% history
# =============================================================================

def line_payload(run_id, at, win_a=60.0, week=9, trigger="nightly", completed=("2026-12-21",)):
    return {"week": week, "as_of": at[:10], "generated_at": at, "completed_dates": list(completed),
            "produced_by": {"run_id": run_id, "trigger": trigger},
            "lines": [{"manager_a": "Nick", "manager_b": "Benton", "win_prob_a": win_a, "win_prob_b": 100 - win_a,
                       "banked_a": 300.0, "banked_b": 280.0, "projected_final_a": 1600.0,
                       "projected_final_b": 1500.0}]}


def test_the_history_is_append_only_and_a_run_is_written_once(tmp_path):
    r = wh.row_from_line(line_payload("r1", "2026-12-22T00:05:00-08:00"))
    assert set(r) == set(wh.ROW_KEYS) and set(r["matchups"][0]) == set(wh.MATCHUP_KEYS)
    assert wh.append(tmp_path, r) is True and wh.append(tmp_path, r) is False
    wh.append(tmp_path, wh.row_from_line(line_payload("r2", "2026-12-23T00:05:00-08:00")))
    before = wh.path_for(tmp_path, 9).read_bytes()
    assert [x["run_id"] for x in wh.read(tmp_path, 9)] == ["r1", "r2"]
    wh.append(tmp_path, wh.row_from_line(line_payload("r3", "2026-12-24T00:05:00-08:00")))
    assert wh.path_for(tmp_path, 9).read_bytes().startswith(before)        # appended, never rewritten
    wh.path_for(tmp_path, 9).write_text('{"schema": 1}\n')
    with pytest.raises(wh.WinProbHistoryError):
        wh.read(tmp_path, 9)
    assert wh.read(tmp_path, 10) == []                                      # no file: a week before it began


def test_every_priced_write_appends_one_row(tmp_path, monkeypatch):
    import refresh_lines as rl
    from modules import calibration_log as cal, week_state as ws
    monkeypatch.setattr(rl, "calibration_records", lambda *a, **k: [])
    monkeypatch.setattr(cal, "append", lambda recs, base: {"added": 0})
    monkeypatch.setattr(ws, "append_tag_log", lambda *a, **k: None)
    monkeypatch.setattr(ws, "tag_record", lambda *a, **k: {})
    (tmp_path / "output").mkdir()
    p = SimpleNamespace(week=9, out_dir=tmp_path / "output", base=tmp_path, seed=1, as_of=D(12, 22),
                        state_path=tmp_path / "output" / "live_lines_week9.state.json", anchors={}, live={},
                        events=[], state=SimpleNamespace(state_hash="h"))
    for rid, at in (("a", "2026-12-22T00:05:00-08:00"), ("b", "2026-12-22T15:20:00-08:00")):
        rl._write(p, None, line_payload(rid, at), 100, {"key": "k"}, "test")
    assert [r["run_id"] for r in wh.read(tmp_path, 9)] == ["a", "b"]
    assert "winprob_history.append" in inspect.getsource(rl._write)


def test_the_history_is_state_ignored_and_new():
    from modules import state_manifest
    m = json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    pats = [p for p in m["patterns"] if p["name"] == "live_lines_week*.winprob.jsonl"]
    assert len(pats) == 1 and pats[0]["dir"] == "output"
    import fnmatch
    other = [p for p in m["patterns"] if p is not pats[0] and p["dir"] == "output"]
    assert not any(fnmatch.fnmatch("live_lines_week4.winprob.jsonl", p["name"]) for p in other)
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "output/live_lines_week4.winprob.jsonl"])
    assert r.returncode == 0


def test_nothing_scores_the_win_pct_history():
    """Pinned like invariant 13 (the title-odds history): the page draws it,
    nothing scores it. Only these files name it."""
    names = {p.relative_to(ROOT).as_posix() for d in ("modules", "scripts") for p in (ROOT / d).glob("*.py")
             if "winprob" in p.read_text(encoding="utf-8")}
    assert names == {"modules/winprob_history.py", "modules/hub_matchups.py", "modules/hub_state.py",
                     "modules/hub_charts.py", "scripts/refresh_lines.py", "scripts/backfill_winprob.py"}
    for scorer in ("modules/calibration_log.py", "modules/backtest_metrics.py", "modules/title_odds_run.py",
                   "modules/closing_line.py"):
        if (ROOT / scorer).exists():
            assert "winprob" not in (ROOT / scorer).read_text(encoding="utf-8")


def test_win_points_place_the_close_and_the_final():
    rows = [wh.row_from_line(line_payload("r1", "2026-11-10T00:07:00-08:00", 48.3, week=4)),
            wh.row_from_line(line_payload("r0", "2026-11-09T00:06:00-08:00", 33.1, week=4))]
    closing = {"week": 4, "closing": {"window_close": "2026-11-09T18:55:00-08:00"},
               "lines": [{"manager_a": "Benton", "manager_b": "Nick", "win_prob_a": 38.9, "win_prob_b": 61.1}]}
    end = datetime(2026, 11, 16, 0, 0, tzinfo=TZ)
    pts = hc.winprob_points("Nick", "Benton", rows, closing, {"at": end, "a": 1500.0, "b": 1400.0})
    assert [(p[0].isoformat()[:16], p[1], p[3]) for p in pts] == [
        ("2026-11-09T00:06", 33.1, "nightly run"), ("2026-11-09T18:55", 61.1, "the closing line"),
        ("2026-11-10T00:07", 48.3, "nightly run"), ("2026-11-16T00:00", 100.0, "final")]
    tie = hc.winprob_points("Nick", "Benton", [], None, {"at": end, "a": 1.0, "b": 1.0})
    assert (tie[0][1], tie[0][2]) == (50.0, 50.0)
    with pytest.raises(hc.ChartError, match="Hayden"):
        hc.winprob_points("Hayden", "Nick", rows, None, None)
    entry = {"week": 4, "start_date": "2026-11-09", "end_date": "2026-11-15"}
    ch = hc.winprob_chart(entry, "Nick", "Benton", pts, TZ)
    assert len(ch["paths"]) == 1 and len(ch["dots"]) == 4 and len(ch["hits"]) == 4
    assert ch["hits"][1]["tip"] == "Mon 11-09, 6:55 PM (the closing line): Nick 61.1%, Benton 38.9%"
    assert {t["t"] for t in ch["texts"] if t["cls"] == "lab"} == {"Nick 100.0%", "Benton 0.0%"}
    assert float(ch["hits"][-1]["x"]) + 9 == pytest.approx(hc.WEEK_X1)            # the final at the axis end
    y50 = [g for g in ch["grid"] if g["cls"] == "g-mid"]
    assert len(y50) == 1                                                          # the 50% line
    _all_strings(ch)


def _all_strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            assert not k.startswith("_"), k
            _all_strings(v)
    elif isinstance(o, list):
        for v in o:
            _all_strings(v)
    else:
        assert isinstance(o, str), o


# =============================================================================
# 48b. the back-fill
# =============================================================================

def _git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)


def test_the_backfill_reads_the_repo_skips_repeats_and_refuses_to_overwrite(tmp_path):
    import backfill_winprob as bw
    st = tmp_path / "state"
    (st / "output").mkdir(parents=True)
    _git(st, "init", "-q")
    _git(st, "config", "user.email", "t@example.com")
    _git(st, "config", "user.name", "t")
    lp = st / "output" / "live_lines_week4.json"
    versions = [line_payload("n1", "2026-11-09T00:06:00-08:00", 33.1, week=4, completed=()),
                line_payload("n1", "2026-11-09T00:06:00-08:00", 33.1, week=4, completed=()),   # the same line again
                line_payload("p1", "2026-11-09T15:15:00-08:00", 62.6, week=4, trigger="pretip", completed=()),
                line_payload("n2", "2026-11-10T00:07:00-08:00", 48.3, week=4)]
    for i, v in enumerate(versions):
        v = dict(v, note=i)                         # every commit changes the file
        lp.write_text(json.dumps(v))
        (st / "other.txt").write_text(str(i))
        _git(st, "add", "-A")
        _git(st, "commit", "-q", "-m", f"run {i}")
    out = tmp_path / "out" / "live_lines_week4.winprob.jsonl"
    r = bw.backfill(tmp_path, 4, st, out)
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert [x["run_id"] for x in rows] == ["n1", "p1", "n2"] and r["versions"] == 4
    assert [x["trigger"] for x in rows] == ["nightly", "pretip", "nightly"]
    with pytest.raises(bw.BackfillError, match="exists"):
        bw.backfill(tmp_path, 4, st, out)
    with pytest.raises(bw.BackfillError, match="not a git checkout"):
        bw.backfill(tmp_path, 4, tmp_path / "nothing", tmp_path / "o2.jsonl")
    assert subprocess.run(["git", "-C", str(st), "status", "--porcelain"], capture_output=True,
                          text=True).stdout == ""                                 # read-only


def test_the_backfill_on_the_real_private_repo_is_read_only(tmp_path):
    _real(".state/.git")
    import backfill_winprob as bw
    status = lambda: subprocess.run(["git", "-C", str(ROOT / ".state"), "status", "--porcelain"],  # noqa: E731
                                    capture_output=True, text=True).stdout
    head = lambda: subprocess.run(["git", "-C", str(ROOT / ".state"), "rev-parse", "HEAD"],        # noqa: E731
                                  capture_output=True, text=True).stdout
    s0, h0 = status(), head()
    r = bw.backfill(ROOT, 4, ROOT / ".state", tmp_path / "w4.jsonl")
    assert r["rows"] and status() == s0 and head() == h0
    ts = [datetime.fromisoformat(x["as_of"]) for x in r["rows"]]
    assert ts == sorted(ts) and all(x["week"] == 4 for x in r["rows"])


# =============================================================================
# 48c. game flow
# =============================================================================

def test_daily_flow_sums_to_banked_and_projected_final():
    import refresh_lines as rl
    days = [D(11, 9), D(11, 10), D(11, 11)]
    state = SimpleNamespace(completed=(days[0],), remaining=tuple(days[1:]),
                            banked_by_day={"Nick": {days[0]: 120.25}},
                            by_day_player={"Nick": {days[0]: {"A": 70.0, "B": 50.25}}})
    score = np.array([400.0, 420.0, 380.0, 410.0])
    res = SimpleNamespace(remaining={"Nick": {"score": score, "games": np.array([9.0, 10.0, 9.0, 10.0])}},
                          day_means={"Nick": {days[1]: 150.0, days[2]: 240.0}})
    f = rl.daily_flow(res, state)["Nick"]
    assert f["banked"] == {"2026-11-09": 120.25} and f["games_left"] == 9.5
    assert sum(f["expected"].values()) == pytest.approx(score.mean(), abs=0.01)
    assert f["top_day"] == {"date": "2026-11-09", "player": "A", "points": 70.0}


def test_the_game_flow_chart_ends_at_the_inputs_and_checks_its_days():
    entry = {"week": 4, "start_date": "2026-11-09", "end_date": "2026-11-11"}
    banked = {"Nick": {"2026-11-09": 120.0}, "Benton": {"2026-11-09": 100.0}}
    exp = {"Nick": {"2026-11-10": 200.0, "2026-11-11": 300.0}, "Benton": {"2026-11-10": 250.0, "2026-11-11": 260.0}}
    ch = hc.gameflow_chart(entry, "Nick", "Benton", banked, exp)
    assert ch["_ends"] == {"Nick": 620.0, "Benton": 610.0} and ch["_banked"] == {"Nick": 120.0, "Benton": 100.0}
    assert [p["dash"] for p in ch["paths"]] == ["", "4 3", "", "4 3"]
    assert any(t["t"] == "Nick +20" for t in ch["texts"])                          # the margin at the last banked day
    with pytest.raises(hc.ChartError, match="expected days"):
        hc.gameflow_chart(entry, "Nick", "Benton", banked, {"Nick": {"2026-11-10": 1.0}, "Benton": exp["Benton"]})
    final = hc.gameflow_chart(entry, "Nick", "Benton", {m: {**banked[m], "2026-11-10": 1.0, "2026-11-11": 2.0}
                                                         for m in banked}, None)
    assert all(p["dash"] == "" for p in final["paths"]) and "Nick 123" in [t["t"] for t in final["texts"]]


def test_a_real_priced_line_carries_days_that_add_up_and_prices_do_not_move():
    _real("data/LINEUPS.xlsx", "output/live_lines_week4.state.json")
    import refresh_lines as rl
    from modules import simulator_betting as sb
    from modules.simulator_betting import KeyedDraws, simulate_week_matrix
    p = rl.prepare(ROOT, 4, D(11, 10), seed=20262027, no_tags=True, reseed=True, dry_run=True)
    res, payload = rl.compute(p, 400)
    for ln in payload["lines"]:
        for s in ("a", "b"):
            assert sum(ln[f"daily_banked_{s}"].values()) == pytest.approx(ln[f"banked_{s}"], abs=0.01)
            assert ln[f"banked_{s}"] + sum(ln[f"daily_expected_{s}"].values()) == \
                pytest.approx(ln[f"projected_final_{s}"], abs=0.01 * 7)
    # the day means are read off the same arrays: no draw added or moved
    from modules.week_state import week_entry
    entry = week_entry(p.data, 4)
    kw = dict(from_date=p.state.as_of, observed=p.state.observed, il_mask=p.il_mask or None)
    a = simulate_week_matrix(p.data, p.teams, entry, None, KeyedDraws(20262027, 200), **kw)
    b = simulate_week_matrix(p.data, p.teams, entry, None, KeyedDraws(20262027, 200), day_means={}, **kw)
    assert all(np.array_equal(a[m][k], b[m][k]) for m in a for k in a[m])


# =============================================================================
# 48d. title odds over the season
# =============================================================================

SCHED = {"weeks": [{"week": w, "start_date": (D(10, 20) + timedelta(days=7 * (w - 1))).isoformat(),
                    "end_date": (D(10, 26) + timedelta(days=7 * (w - 1))).isoformat()} for w in range(1, 24)]}


def hist(at, vals, kind="nightly"):
    return {"as_of": at, "kind": kind, "title_odds": vals}


def test_title_points_take_each_days_last_run_and_place_reports_on_their_monday():
    rows = [hist("2026-11-03T00:05:00-08:00", {"Nick": 50.0, "Benton": 50.0}),
            hist("2026-11-03T15:30:00-08:00", {"Nick": 52.0, "Benton": 48.0}, "pretip"),
            hist("2026-11-04T00:05:00-08:00", {"Nick": 55.0, "Benton": 45.0})]
    rep = lambda w, mode="publish": {"metadata": {"week": w, "run_mode": mode},          # noqa: E731
                                     "power_rankings": [{"manager": "Nick", "title_odds": 40.0},
                                                        {"manager": "Benton", "title_odds": 60.0}]}
    pts = hc.title_points(rows, [rep(1), rep(2)], SCHED)
    assert list(pts) == [D(10, 27), D(11, 3), D(11, 4)]          # week 1's report on week 2's Monday
    assert pts[D(11, 3)]["values"]["Nick"] == 52.0                # the day's last run
    assert pts[D(10, 27)]["source"] == "the published week-1 report"
    with pytest.raises(hc.ChartError, match="not a published report"):
        hc.title_points([], [rep(1, "preview")], SCHED)
    with pytest.raises(hc.ChartError, match="metadata.week"):
        hc.title_points([], [{"metadata": {}}], SCHED)
    with pytest.raises(hc.ChartError, match="week 24"):
        hc.title_points([], [rep(23)], SCHED)


def test_the_title_chart_spans_23_weeks_with_the_playoff_and_cup_marks():
    pts = {D(10, 27): {"values": {"Nick": 40.0, "Benton": 60.0}, "source": "r"},
           D(11, 4): {"values": {"Nick": 55.0, "Benton": 45.0}, "source": "nightly run"}}
    ch = hc.title_odds_chart(pts, SCHED, ["Nick", "Benton"], playoff_week=16, cup_week=22)
    ndays = 23 * 7
    assert sum(1 for g in ch["grid"] if g["cls"] == "g-tick") == ndays + 1                     # a tick per day
    assert [t["t"] for t in ch["texts"] if t["cls"] == "ax" and t["t"].isdigit()] == [str(w) for w in range(1, 24, 2)]
    assert [t["t"] for t in ch["texts"] if t["cls"] == "ax-mark"] == ["Playoffs", "Cup"]
    assert len(ch["dots"]) == 4                                   # only the observed points, nothing between
    assert {t["t"]: t["fill"] for t in ch["texts"] if t["cls"] == "lab"} == \
        {"Nick 55.0%": hc.MANAGER_COLOURS["Nick"], "Benton 45.0%": hc.MANAGER_COLOURS["Benton"]}
    assert ch["hits"][1]["tip"] == "Wed 11-04: Nick 55.0%, Benton 45.0% (nightly run)"
    _all_strings(ch)


def test_the_manager_colours_are_readable_on_the_card():
    """>= 3:1 (WCAG non-text) for the lines, and the end labels are text in
    the same colours: >= 4.5:1. Names label every line, so colour is never
    the only signal."""
    from modules.data_loader import MANAGERS
    assert set(hc.MANAGER_COLOURS) == set(MANAGERS) and len(set(hc.MANAGER_COLOURS.values())) == 4
    for m, c in hc.MANAGER_COLOURS.items():
        assert contrast(c, "#FFFFFF") >= 4.5, (m, c)
    assert ".card{background:#fff;" in hub_page.CSS


# =============================================================================
# 48e. season points
# =============================================================================

def test_the_hubs_pf_is_cup_seeding_points_and_get_cup_seeds(real_payload):
    from modules.simulator_cup_odds import cup_seeding_points, get_cup_seeds
    p, data = real_payload
    pts, seeds = cup_seeding_points(data), get_cup_seeds(data)
    for r in p["power"]["rows"]:
        assert r["pf"] == f"{pts[r['manager']]:,.0f}" and r["seed"] == f"seed {seeds[r['manager']]}"
    assert "the Cup seeds on weeks 1\u201321" in p["power"]["note"]
    src = inspect.getsource(hs.season_points)
    assert "cup_seeding_points(data)" in src and "get_cup_seeds(data)" in src
    assert not re.search(r'get\("score"|\["score"\]', src)                     # never a second sum


def _rule(css, head):
    i = css.index(head)
    return css[i:css.index("}", i)]


@pytest.mark.parametrize("head,n_fixed", [(".pr-row{all:unset", 5), (".pr-h,.pr-row{", 5), (".fa-h,.fa-r{", 5)])
def test_the_tables_fit_a_360px_phone(head, n_fixed):
    """Section padding 16 a side; the flexible name column keeps >= 90 px.
    48e: rank 16, W-L 34, PF 44 (points over "seed N"), odds 56, adds 34.
    48g: Proj 32, three game columns of 30, Pts 44, 10 px row padding."""
    r = _rule(hub_page.CSS, head)
    cols = re.search(r"grid-template-columns:([^;]+);", r).group(1)
    gap = int(re.search(r"gap:(\d+)px", r).group(1))
    pad = int(re.search(r"padding:\d+px (\d+)px", r).group(1))
    fixed = [int(x) for x in re.findall(r"\b(\d+)px", cols)]
    assert len(fixed) == n_fixed
    left = 360 - 2 * 16 - 2 * pad - gap * n_fixed - sum(fixed)
    assert left >= 90, left


# =============================================================================
# 48f. stash: long absences only
# =============================================================================

def test_an_o_player_is_a_stash_only_with_a_live_injury_entry():
    from test_hub_fa_moves import stash_world, rec, WK
    over = [{"player_name": "With Entry", "out_weeks": [4, 5], "return_week": 6, "return_date": "2026-11-23"},
            {"player_name": "Old Entry", "out_weeks": [1], "return_week": 2}]
    av = stash_world({"With Entry": "O", "No Entry": "O", "Old Entry": "O", "Gone": "OFS"}, over)
    rows = hs.stash_rows([rec("With Entry", 30.0), rec("No Entry", 40.0), rec("Old Entry", 35.0),
                          rec("Gone", 20.0)], av, WK[4] + WK[5], 10)
    assert [r["name"] for r in rows] == ["With Entry", "Gone"]
    assert not any("up to" in c["text"] for r in rows for c in r["tags"])
    assert "up to" not in inspect.getsource(hs.stash_rows).split('"""')[-1]
    assert "free_agent_status(" not in inspect.getsource(hs.stash_rows)
    assert "up to" in inspect.getsource(hs.free_agent_status)                    # kept elsewhere


# =============================================================================
# 48g. three free-agent columns
# =============================================================================

def test_the_ranking_sums_all_three_columns():
    from test_hub_fa_moves import WK
    weeks = {w: (v[0], v[-1]) for w, v in WK.items()}
    info = {"F0": {"nba_team": "T0", "positions": {"SF"}, "proj_fppg": 10.0}}
    av = hs.Availability({}, {}, {}, {"players": []}, 4, info, {"T0": set(WK[4] + WK[5] + WK[6])}, weeks,
                         D(11, 10)).for_free_agents(["F0"], {"F0": "HEALTHY"})
    row = hs.rank_free_agents([{"player_name": "F0", "projectedFPPG": 10.0}], av, WK[4], WK[5], WK[6])[0]
    assert (row["g1"], row["g2"], row["g3"], row["pts"]) == ("7", "7", "7", "210.0")
    assert hs.PTS_LABEL == "Pts (3 wks)"


# =============================================================================
# 48h. round-trip drops
# =============================================================================

def tx(key, ts, day, *parts, ttype=None):
    ps = []
    for act, mgr, name in parts:
        side = {"type": "team", "manager": mgr, "team_key": mgr}
        ps.append({"action": act, "name": name, "to": side if act == "add" else {"type": "freeagents"},
                   "from": side if act == "drop" else {"type": "freeagents"}})
    t = ttype or ("add/drop" if len(parts) > 1 else parts[0][0])
    return {"key": key, "timestamp": ts, "league_day": day, "type": t, "players": ps}


def test_round_trip_drops_rule_a_and_b_and_the_buzelis_drop_stays():
    from modules.transaction_rulings import Ruling
    void = lambda d, m, p: Ruling(d, m, "add", p, "void", "Nick", d, "")                      # noqa: E731
    rulings = [void("2026-11-09", "Benton", "Ty Jerome"), void("2026-11-09", "Benton", "Anthony Davis"),
               void("2026-10-25", "Hayden", "Franz Wagner")]
    txs = [tx("k1", 100, "2026-11-09", ("drop", "Benton", "Anthony Davis")),               # (b): next add voided
           tx("k2", 200, "2026-11-09", ("add", "Benton", "Ty Jerome")),
           tx("k3", 300, "2026-11-09", ("add", "Benton", "Anthony Davis"), ("drop", "Benton", "Ty Jerome")),  # (a)
           tx("k4", 50, "2026-10-25", ("add", "Hayden", "Franz Wagner"), ("drop", "Hayden", "Matas Buzelis")),
           tx("k5", 60, "2026-10-25", ("drop", "Nick", "Real Drop"))]
    assert hub_moves.round_trip_drops(txs, rulings) == {"k1": ["Anthony Davis"], "k3": ["Ty Jerome"]}


def test_real_round_trip_drops_are_the_six_listed_in_the_result():
    _real("data/transaction_log.jsonl", "config/TRANSACTION_RULINGS.json")
    from modules import transaction_log as tlog, transaction_rulings as tr
    sched = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    txs = tlog.transactions(ROOT)
    h = hub_moves.round_trip_drops(txs, tr.load_all(ROOT, sched))
    by = {t["key"]: t for t in txs}
    got = sorted((by[k]["time"][:16], [p["from"]["manager"] for p in by[k]["players"] if p["action"] == "drop"][0],
                  n) for k, v in h.items() for n in v)
    want = [("2026-10-25T22:40", "Hayden", "Franz Wagner"), ("2026-10-26T07:29", "Garrett", "Paul George"),
            ("2026-11-07T15:50", "Benton", "Davion Mitchell"), ("2026-11-07T15:54", "Benton", "Jabari Smith Jr."),
            ("2026-11-09T00:47", "Benton", "Anthony Davis"), ("2026-11-09T15:18", "Benton", "Ty Jerome")]
    assert got[:len(want)] == want
    # the Buzelis drop (a real drop in a voided add/drop, Nick kept it 11-05) is shown
    from modules.league_clock import league_now
    wk = max(int(w["week"]) for w in sched["weeks"]
             if date.fromisoformat(str(w["start_date"])[:10]) <= league_now().date())
    rows = hub_moves.build(ROOT, sched, wk, managers=["Nick", "Hayden", "Benton", "Garrett"], budget=3)
    texts = [x["what"] for t in rows["weeks"] for x in t["items"]]
    assert "dropped Matas Buzelis" in texts
    for _when, m, n in want:
        assert not any(x["who"] == m and any(pt["text"] == f"dropped {n}" for pt in x["parts"])
                       for t in rows["weeks"] for x in t["items"]), (m, n)


# =============================================================================
# the page: views open and close; the main page gains only the buttons
# =============================================================================

def test_every_view_opens_and_has_a_way_back():
    page = hub_page.render(sample_payload(), now=GEN)
    ids = set(re.findall(r'class="view" id="([^"]+)"', page))
    for target in set(re.findall(r'data-open="([^"]+)"', page)):
        assert target in ids, target
    for v in sample_payload()["matchup_views"]:
        block = page[page.index(f'id="{v["id"]}"'):]
        block = block[:block.index("</section></div>")]
        assert f'class="back" data-open="{v["back"]}"' in block
    assert 'id="v-last"' in page and 'data-open="v-last"' in page


def test_the_main_page_gains_only_the_buttons_pf_and_the_columns():
    p = sample_payload()
    page = hub_page.render(p, now=GEN)
    main = page[page.index('id="v-main"'):page.index('class="view" id="v-roster-')]
    assert main.count('class="mbtn"') == 3 * len(p["matchups"]["cards"])
    assert "<svg" not in main and 'class="para"' not in main and "Last week's matchups" in visible_text(main)
    assert ">PF<" in main and "3,207" in main and ">Wk 5<" in main
    assert "seed 1" not in main                     # the seed line under PF is gone (Nick, 11-11)


def test_the_charts_and_paragraphs_are_printed_as_is_and_the_page_computes_nothing():
    p = sample_payload()
    page = hub_page.render(p, now=GEN)
    assert 'd="M30 100 L194 60"' in page and 'data-tip="Tue 11-03: Mgr One 70.0%"' in page
    assert "Mgr One leads Mgr Two by 11.5, 120.5 to 109.0." in page
    for fn in (hub_page._svg, hub_page._mbtns):
        src = inspect.getsource(fn)
        for banned in ("round", "float", "sum", "sorted", "max", "min", "int"):
            assert not re.search(rf"\b{banned}\(", src), (fn.__name__, banned)
    js = hub_page.PAGE_JS[hub_page.PAGE_JS.index("closest('[data-tip]')") - 40:]
    js = js[:js.index("return;}") + 8]
    assert not re.search(r"[-+*/]\s*\d|parse(Int|Float)|Number\(|Math\.", js), js


# =============================================================================
# the real build (one, shared)
# =============================================================================

@pytest.fixture(scope="module")
def real_payload():
    _real("output/title_odds_latest.json", "output/tag_records.jsonl", "data/transaction_log.jsonl",
          "output/hub_archive/index.json")
    from modules.data_loader import load_all_data
    data = load_all_data(ROOT, current_week=None)
    try:
        p = hs.build(ROOT, data=data, allow_engine_mismatch=True, echo=lambda *a: None)
    except hs.HubInputError as e:
        pytest.skip(f"the real hub does not build on this checkout's state: {e}")
    return p, data


def test_real_views_for_every_card_this_week_and_last(real_payload):
    p, _data = real_payload
    ids = {v["id"] for v in p["matchup_views"]}
    for c in p["matchups"]["cards"]:
        assert set(c["views"]) == {"sum", "win", "flow"} and set(c["views"].values()) <= ids
    if p["week"] > 1:
        last = p["matchups"]["last"]
        assert last and all(set(c["views"].values()) <= ids for c in last["cards"])
        assert all(c["result"].startswith("Final") for c in last["cards"])
    for v in p["matchup_views"]:
        if v["kind"] == "chart":
            _all_strings(v["chart"])
        else:
            assert v["paras"] and all(isinstance(x["text"], str) and x["text"] for x in v["paras"])
    _all_strings(p["power"]["chart"])
    assert p["power"]["chart_title"] == "Title odds"
    assert len(json.dumps(p)) < 400_000


# --- 11-11 (Nick, the 48-check): the paragraph states an absence only when
# something firm backs it; a bare Yahoo O tag is "listed as out for his next
# game"; Q and D are not mentioned (case: Herro, a late scratch then Q again)

class _AbsAv:
    def __init__(self, tags, over=None, nba=None, il=None):
        from modules import absence
        from datetime import date as _d
        self.absence = absence
        self.rosters = {"Nick": sorted(set(tags) | set(over or {}) | set(nba or {}))}
        self.il = il or {}
        self.tags = tags
        self.over = over or {}
        self.nba_outs = nba or {}
        self.weeks = {4: (_d(2026, 11, 9), _d(2026, 11, 15)), 5: (_d(2026, 11, 16), _d(2026, 11, 22)),
                      6: (_d(2026, 11, 23), _d(2026, 11, 29))}

    def has_game(self, n, d):
        return True

    def week_of(self, d):
        return next(w for w, (a, b) in self.weeks.items() if a <= d <= b)

    def override_covers(self, n, days):
        from modules.hub_state import override_out_on
        e = self.over.get(n)
        if e and any(override_out_on(e, d, self.week_of(d), self.weeks[self.week_of(d)][0]) for d in days):
            return e
        return None


DAYS = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 14)]


def test_a_bare_o_tag_is_listed_not_stated_and_q_d_are_silent():
    t = hm.absence_text(_AbsAv({"Tyler Herro": "O", "Ja Morant": "Q", "Joel Embiid": "D"}), "Nick", DAYS)
    assert t == "Nick's Tyler Herro is listed as out for his next game."
    assert "without" not in t and "Morant" not in t and "Embiid" not in t
    assert hm.absence_text(_AbsAv({"Ja Morant": "Q"}), "Nick", DAYS) == ""


def test_an_entry_ofs_or_nba_out_is_stated_with_its_backing():
    over = {"Tyler Herro": {"player_name": "Tyler Herro", "out_weeks": [4, 5], "return_week": 6,
                            "return_date": "2026-11-23"}}
    t = hm.absence_text(_AbsAv({"Tyler Herro": "O", "Kyrie Irving": "OFS", "Zion Williamson": "Q"}, over,
                               {"Zion Williamson": date(2026, 11, 12)}), "Nick", DAYS)
    assert t == ("Nick is without Kyrie Irving (out for the season), Tyler Herro (all 3 of his games, "
                 "back 11-23) and Zion Williamson (out Thursday, per the NBA report).")


def test_firm_and_listed_share_one_sentence_and_il_players_are_left_out():
    over = {"A B": {"player_name": "A B", "out_weeks": [4], "return_week": 5, "return_date": "2026-11-16"}}
    t = hm.absence_text(_AbsAv({"A B": "O", "C D": "O", "E F": "O"}, over, il={"Nick": {"E F": 1}}),
                        "Nick", DAYS)
    assert t == "Nick is without A B (all 3 of his games, back 11-16); C D is listed as out for his next game."
