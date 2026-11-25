"""5g s.7 (Nick, 11-25): Step 6 after week N+1's window has closed prints
Monday's closing line (output/closing_line_week<N+1>.json); it prices no line
of its own. The rest of each matchup's preview stays the report's. With no
closing line it raises, naming the file and --own-line (the fallback, marked
published after the first tip, s.2b). Before the close: today's behaviour.
Step 9 logs no new line records for a closing-line issue. The formatter and the
drafting prompt say where the lines come from (s.4)."""
import ast
import inspect
import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import closing_line as cl                            # noqa: E402
from modules import report_builder as rb                          # noqa: E402
from modules.simulator_betting import BettingLine                 # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
WEEKS = [{"week": 5, "start_date": "2026-11-16", "end_date": "2026-11-22"},
         {"week": 6, "start_date": "2026-11-23", "end_date": "2026-11-29"}]


def monday_games(*mondays):
    g = []
    for m in mondays:
        nxt = m + timedelta(days=1)
        g.append({"date": m.isoformat(), "away": "AAA", "home": "BBB", "tip_utc": f"{nxt.isoformat()}T03:00:00Z"})
        g.append({"date": m.isoformat(), "away": "CCC", "home": "DDD", "tip_utc": f"{nxt.isoformat()}T00:00:00Z"})
    return {"games": g}


NBA = monday_games(date(2026, 11, 16), date(2026, 11, 23))      # week 6 closes 11-23 18:55 PT
BEFORE = datetime(2026, 11, 23, 9, 0, tzinfo=LA)
AFTER = datetime(2026, 11, 23, 21, 30, tzinfo=LA)               # Monday night, after the close


def closing_line(**over):
    """Week 6's closing line as on file (output/closing_line_week6.json's lines)."""
    nick = {"manager_a": "Nick", "manager_b": "Garrett", "matchup": "Nick vs Garrett",
            "team_name_a": "Luka my Balls", "team_name_b": "Blink-183",
            "spread_a": -28.5, "spread_b": 28.5, "over_under": 3050, "win_prob_a": 55.36, "win_prob_b": 44.64,
            "moneyline_a": -125, "moneyline_b": 125, "std_dev_a": 167.07, "std_dev_b": 161.6,
            "banked_a": 0.0, "banked_b": 0.0, "remaining_mean_a": 1537.93, "remaining_mean_b": 1509.24,
            "projected_final_a": 1537.93, "projected_final_b": 1509.24}
    hayden = {"manager_a": "Hayden", "manager_b": "Benton", "matchup": "Hayden vs Benton",
              "team_name_a": "Big Nik Energy", "team_name_b": "Spayed for Cade",
              "spread_a": 28.5, "spread_b": -28.5, "over_under": 2600, "win_prob_a": 44.42, "win_prob_b": 55.58,
              "moneyline_a": 125, "moneyline_b": -125, "std_dev_a": 149.5, "std_dev_b": 152.98,
              "banked_a": 0.0, "banked_b": 0.0, "remaining_mean_a": 1284.25, "remaining_mean_b": 1312.97,
              "projected_final_a": 1284.25, "projected_final_b": 1312.97}
    return dict({"kind": "closing", "week": 6, "generated_at": "2026-11-23T18:55:00-08:00",
                 "lines": [nick, hayden]}, **over)


def base_with(tmp_path, payload=None):
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    if payload is not None:
        (tmp_path / "output" / "closing_line_week6.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def own_lines():
    """The week-5 report's own week-6 lines (Tuesday 11-24's build): Garrett
    -2.0 v Nick, Benton -51.0 v Hayden, with Benton listed first in the second."""
    a = BettingLine("Nick", "Garrett", 2.0, -2.0, 3040, 49.5, 50.5, 100, -100, 1517.98, 1520.19, 183.2, 184.9,
                    "Luka my Balls", "Blink-183", 0.0, 0.0, 1517.98, 1520.19, 1517.98, 1520.19)
    b = BettingLine("Benton", "Hayden", -51.0, 51.0, 2620, 59.02, 40.98, -145, 145, 1336.5, 1285.5, 150.0, 148.0,
                    "Spayed for Cade", "Big Nik Energy", 0.0, 0.0, 1336.5, 1285.5, 1336.5, 1285.5)
    previews = [SimpleNamespace(manager_a="Nick", manager_b="Garrett", betting_line=a, key_player_a="Luka Doncic",
                                guard_matchup={"advantage": "Even"}),
                SimpleNamespace(manager_a="Benton", manager_b="Hayden", betting_line=b, key_player_a="Cade",
                                guard_matchup={"advantage": "Benton"})]
    return SimpleNamespace(week=6, num_simulations=5000, matchup_previews=previews)


# ============================================================ where the lines come from

def test_before_the_close_the_report_prices_its_own(tmp_path):
    src = cl.for_weekly_build(base_with(tmp_path, closing_line()), 5, WEEKS, NBA, now=BEFORE)
    assert src["kind"] == "own" and src["after_close"] is False and src["week"] == 6
    assert src["close"] == "2026-11-23T18:55:00-08:00"


def test_after_the_close_with_the_file_it_is_the_closing_line(tmp_path):
    src = cl.for_weekly_build(base_with(tmp_path, closing_line()), 5, WEEKS, NBA, now=AFTER)
    assert src["kind"] == "closing" and src["path"] == "output/closing_line_week6.json"
    assert src["payload"]["lines"][0]["spread_a"] == -28.5


def test_after_the_close_with_no_file_it_raises_naming_own_line(tmp_path):
    with pytest.raises(cl.ClosingLineMissing) as e:
        cl.for_weekly_build(base_with(tmp_path), 5, WEEKS, NBA, now=AFTER)
    msg = str(e.value)
    assert "output/closing_line_week6.json is missing" in msg
    assert "--own-line" in msg and "state.py pull" in msg and "closing run" in msg


def test_a_recorded_no_closing_line_is_named(tmp_path):
    base = base_with(tmp_path)
    (base / "output" / "closing_none_week6.json").write_text("{}", encoding="utf-8")
    with pytest.raises(cl.ClosingLineMissing, match="closing_none_week6.json records"):
        cl.for_weekly_build(base, 5, WEEKS, NBA, now=AFTER)


def test_own_line_after_the_close_prices_its_own(tmp_path):
    src = cl.for_weekly_build(base_with(tmp_path), 5, WEEKS, NBA, now=AFTER, own_line=True)
    assert src["kind"] == "own" and src["after_close"] is True


def test_another_weeks_file_raises(tmp_path):
    with pytest.raises(cl.ClosingLineMissing, match="not week 6's closing line"):
        cl.for_weekly_build(base_with(tmp_path, closing_line(week=5)), 5, WEEKS, NBA, now=AFTER)


def test_no_next_week_means_no_lines(tmp_path):
    assert cl.for_weekly_build(base_with(tmp_path), 6, WEEKS, NBA, now=AFTER) is None


# ============================================================ the report's lines

def test_the_reports_lines_equal_the_files():
    bl = own_lines()
    rb.apply_closing_line(bl, closing_line())
    nick, benton = (p.betting_line for p in bl.matchup_previews)
    assert (nick.spread_a, nick.spread_b, nick.win_prob_a, nick.moneyline_a, nick.over_under) == \
        (-28.5, 28.5, 55.36, -125, 3050)
    assert (nick.avg_score_a, nick.projected_final_b) == (1537.93, 1509.24)
    # the second preview lists Benton first: the closing line's sides are swapped to match
    assert (benton.manager_a, benton.spread_a, benton.win_prob_a, benton.moneyline_a) == ("Benton", -28.5, 55.58, -125)
    assert (benton.spread_b, benton.win_prob_b, benton.avg_score_b) == (28.5, 44.42, 1284.25)
    # the rest of each preview is the report's own
    assert bl.matchup_previews[0].key_player_a == "Luka Doncic"
    assert bl.matchup_previews[1].guard_matchup == {"advantage": "Benton"}


def test_a_matchup_missing_from_either_side_raises():
    one = closing_line()
    one["lines"] = one["lines"][:1]
    with pytest.raises(ValueError, match="no Benton v Hayden"):
        rb.apply_closing_line(own_lines(), one)
    extra = closing_line()
    extra["lines"].append(dict(extra["lines"][0], manager_a="X", manager_b="Y", matchup="X vs Y"))
    with pytest.raises(ValueError, match="matchups the report does not"):
        rb.apply_closing_line(own_lines(), extra)
    with pytest.raises(ValueError, match="week 7"):
        rb.apply_closing_line(own_lines(), closing_line(week=7))


def test_the_report_logs_nothing_new_for_a_closing_line():
    """With the closing line, the build publishes no line records of its own."""
    src = inspect.getsource(rb.build_stats_report)
    i = src.index('if (line_source or {}).get("kind") == "closing" and betting_lines is not None:')
    j = src.index("apply_closing_line(betting_lines, line_source[\"payload\"])")
    k = src.index("published_lines = _published_line_records(")
    assert i < j < k and "else:" in src[j:k]


def test_the_metadata_says_what_comes_from_where():
    now = datetime(2026, 11, 30, 21, 5, tzinfo=LA)
    m = rb._lines_metadata({"kind": "closing", "path": "output/closing_line_week6.json",
                            "close": "2026-11-23T18:55:00-08:00", "payload": closing_line()}, 5, True, now)
    assert m["source"] == "closing" and m["file"] == "output/closing_line_week6.json"
    assert "spread, moneyline, over/under" in m["parts"]["lines"]
    assert "positions, starts, health and key players" in m["parts"]["previews"]
    assert m["title_odds"] == "this report's own season pass, after week 5"
    own = rb._lines_metadata({"kind": "own", "after_close": True, "close": "2026-11-23T18:55:00-08:00",
                              "why": "--own-line"}, 5, True, now)
    assert own["source"] == "own" and own["after_close"] is True and own["priced_at"] == now.isoformat(timespec="seconds")


def test_generate_stats_report_decides_before_the_build_and_refuses():
    src = (ROOT / "scripts" / "generate_stats_report.py").read_text(encoding="utf-8")
    assert '"--own-line"' in src
    assert "_cl.for_weekly_build(base_path, week, data.schedule.get(\"weeks\", [])," in src
    assert "except _cl.ClosingLineMissing as e:" in src and 'print(f"REFUSED: {e}")' in src
    assert src.index("for_weekly_build(") < src.index("build_season_performers(")      # before the long build
    assert "now=build_now," in src and "line_source=line_source," in src


# ============================================================ Step 9

def _report(tmp_path, meta):
    p = tmp_path / "output" / "stats_report_week5.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"metadata": dict({"publishable": True, "run_mode": "publish"}, **meta)}),
                 encoding="utf-8")
    return p


def test_step_9_logs_nothing_for_a_closing_line_issue(tmp_path, capsys):
    import newsletter_html_generator as nhg
    p = _report(tmp_path, {"published_lines": [], "lines": {"source": "closing", "week": 6}})
    out = nhg.log_published_lines(p, sendable=True)
    assert out["logged"] == 0 and out["why_not"] is None and out.get("closing")
    assert "calibration log: the issue printed week 6's closing line (already logged)" in capsys.readouterr().out
    assert not (tmp_path / "data" / "calibration" / "published_lines.json").exists()


def test_step_9_refuses_a_closing_issue_that_carries_its_own_records(tmp_path, capsys):
    import newsletter_html_generator as nhg
    p = _report(tmp_path, {"published_lines": [{"week": 6}], "lines": {"source": "closing", "week": 6}})
    out = nhg.log_published_lines(p, sendable=True)
    assert out["logged"] == 0 and "rebuild it with Step 6" in out["why_not"]


# ============================================================ the formatter and the prompt

def _section3(meta_lines):
    import format_stats_report as fsr
    bl = own_lines()
    if meta_lines["source"] == "closing":
        rb.apply_closing_line(bl, closing_line())
    la = {"week": 6, "num_simulations": 5000, "matchup_previews": [
        {"week": 6, "manager_a": p.manager_a, "manager_b": p.manager_b,
         "team_name_a": p.betting_line.team_name_a, "team_name_b": p.betting_line.team_name_b,
         "betting_line": asdict(p.betting_line)} for p in bl.matchup_previews]}
    data = {"metadata": {"week": 5, "lines": meta_lines}, "looking_ahead": la}
    return fsr.format_section_3_betting_lines(data, {"scoring_trends": {}}), la


CLOSING_META = {"source": "closing", "week": 6, "file": "output/closing_line_week6.json",
                "close": "2026-11-23T18:55:00-08:00", "title_odds": "this report's own season pass, after week 5"}
OWN_LATE_META = {"source": "own", "week": 6, "after_close": True, "close": "2026-11-23T18:55:00-08:00",
                 "priced_at": "2026-11-24T15:43:27-08:00"}


def test_the_formatters_betting_lines_block_for_the_closing_line():
    text, _ = _section3(CLOSING_META)
    assert "*Lines: Monday's closing line for week 6 (output/closing_line_week6.json" in text
    assert "- Spread: Nick -28.5 (Garrett +28.5)" in text
    assert "- Win Prob: Benton 55.58% | Hayden 44.42%" in text


def test_the_formatters_betting_lines_block_for_an_own_line_after_the_close():
    text, _ = _section3(OWN_LATE_META)
    assert ("*Lines: this report's own (--own-line). These week-6 lines were priced Tuesday 11-24 from "
            "the end of week 5: they do not count Monday 11-23's games.") in text
    assert "- Spread: Nick +2.0 (Garrett -2.0)" in text


def test_the_prompt_line_for_both_cases():
    assert cl.lines_text(CLOSING_META, 5)["prompt"] == (
        "These week-6 lines are Monday's closing line, set when the add window closed. Say so in one "
        "sentence in the Betting Lines section; the hub carries the live line from here.")
    assert cl.lines_text(OWN_LATE_META, 5)["prompt"] == (
        "These week-6 lines were priced Tuesday 11-24 from the end of week 5: they do not count Monday "
        "11-23's games. Say so in one sentence in the Betting Lines section, and point readers to the "
        "hub for the live line.")
    with pytest.raises(cl.LinesUnknown, match="rerun Step 6"):
        cl.lines_text(None, 5)
    template = (ROOT / "templates" / "NEWSLETTER_PROMPTS.md").read_text(encoding="utf-8")
    part1 = template.split("## PART 1", 1)[1].split("## PART 2", 1)[0]
    assert "**Betting Lines:** [FILL IN: where this issue's betting lines come from]" in part1


# ============================================================ next week's upset detection

@pytest.mark.parametrize("meta", [CLOSING_META, OWN_LATE_META], ids=["closing", "own"])
def test_next_weeks_upset_detection_reads_the_line_the_issue_printed(tmp_path, meta):
    import format_stats_report as fsr
    _, la = _section3(meta)
    (tmp_path / "stats_report_week5.json").write_text(json.dumps({"metadata": {"week": 5, "lines": meta},
                                                                  "looking_ahead": la}), encoding="utf-8")
    pred = fsr.load_last_week_betting_predictions(6, tmp_path)
    ng = pred[("Garrett", "Nick")]
    if meta["source"] == "closing":
        assert (ng["favorite"], ng["spread"], ng["win_prob_favorite"]) == ("Nick", -28.5, 55.36)
        assert pred[("Benton", "Hayden")]["favorite"] == "Benton"
    else:
        assert (ng["favorite"], ng["spread"], ng["win_prob_favorite"]) == ("Garrett", -2.0, 50.5)
