"""5g s.3 and s.6 (claude/HANDOFF_5G_WEEKLY_BUILD_FIXES_2026-11-25.md):

  s.6  the claim check reads "week-6 adds" as a week label, not a count of 6
       (week 5's five false positives, output/claim_check_week5.md);
  s.3  generate_rosters.py --week N refuses once week N+1's Monday window has
       closed (it would rebuild ROSTERS.json from week N's lineups and drop
       every move made in that window), unless --force.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import claim_check as cc                           # noqa: E402
from modules.league_clock import league_tz                      # noqa: E402

TEAMS = {"Nick": "Luka my Balls", "Hayden": "Big Nik Energy", "Benton": "Spayed for Cade",
         "Garrett": "Blink-183"}
# week 5's cards (joined_week_adds, joined_claims), from output/claim_check_week5.md
WEEK5 = {"Nick": (1, 0), "Hayden": (1, 2), "Benton": (3, 1), "Garrett": (2, 0)}


def found(text):
    cards = [{"manager": m, "joined_week_adds": a, "joined_claims": c} for m, (a, c) in WEEK5.items()]
    vocab = cc.Vocabulary(list(WEEK5), TEAMS, {}, ["Wendell Carter Jr.", "Fred VanVleet", "VJ Edgecombe",
                                                    "Desmond Bane", "Rudy Gobert", "Mikal Bridges",
                                                    "Jonathan Kuminga", "Damian Lillard", "AJ Dybantsa",
                                                    "Naz Reid", "Julius Randle"])
    return cc.adds_claim_findings(text, vocab, cards)


# the five sentences of week 5's issue that were flagged (S2 L42, L54, L60 x2, S10 L404)
WEEK5_SENTENCES = [
    "Garrett is out of moves. He has already used all three week-6 adds, on Wendell Carter Jr., "
    "Fred VanVleet and VJ Edgecombe, the last of whom he dropped on Nov 16.",
    "Hayden's pickups paid. Bane, his one week-5 add, produced the best return of any new player "
    "this week.",
    "Benton reshuffled. Four new players joined: Rudy Gobert, Mikal Bridges and Jonathan Kuminga as "
    "week-5 adds, and Damian Lillard as a week-4 claim.",
    "Benton is done for the week. He has spent all three week-6 adds, on AJ Dybantsa, Naz Reid and "
    "Julius Randle, and Bridges is no longer on the roster.",
    "Benton and Garrett have used all three week-6 adds; Nick has two left and Hayden one.",
]


@pytest.mark.parametrize("sentence", WEEK5_SENTENCES)
def test_week_5s_five_sentences_are_not_findings(sentence):
    assert found(sentence) == []


@pytest.mark.parametrize("label", ["week-6 adds", "week 6 adds", "Week-6 adds", "week 12 adds",
                                   "wk-6 adds"])
def test_a_number_joined_to_week_is_a_label(label):
    assert found(f"Benton used all his {label}.") == []


def test_a_real_count_over_the_card_is_still_a_finding():
    f = found("Garrett made 6 adds this week.")
    assert len(f) == 1 and f[0].kind == "adds_over_card"
    f = found("With 6 adds, Benton rebuilt the bench.")
    assert len(f) == 1
    # a label and a count in one sentence: only the count is read
    f = found("Garrett burned 4 adds and then all three week-6 adds.")
    assert [x.token.lower() for x in f] == ["burned 4 adds"]


# =============================================================================
# s.3: Step 3 must not undo Monday's moves
# =============================================================================

def _gr():
    import generate_rosters
    return generate_rosters


# week 5 = 11-16..11-22, week 6 opens Monday 11-23; the close is 5 minutes before
# that night's last tip (price_lock.window_close), here put at 19:25 Pacific
WEEKS = [{"week": 5, "start_date": "2026-11-16", "end_date": "2026-11-22"},
         {"week": 6, "start_date": "2026-11-23", "end_date": "2026-11-29"}]
CLOSE = datetime(2026, 11, 23, 19, 25, tzinfo=league_tz())


def close_of(day, _sched=None):
    assert str(day) == "2026-11-23"
    return CLOSE


def test_step_3_refuses_after_the_next_windows_close():
    gr = _gr()
    with pytest.raises(gr.RostersAfterClose) as e:
        gr.check_not_after_close(5, WEEKS, None, now=datetime(2026, 11, 24, 15, 0, tzinfo=league_tz()),
                                 window_close=close_of)
    msg = str(e.value)
    assert "week 6's window closed" in msg and "--force" in msg
    assert "closing run" in msg and "nightly" in msg            # the cloud keeps ROSTERS.json current
    # a minute after the close: refused too
    with pytest.raises(gr.RostersAfterClose):
        gr.check_not_after_close(5, WEEKS, None, now=CLOSE, window_close=close_of)


def test_step_3_runs_before_the_close():
    gr = _gr()
    assert gr.check_not_after_close(5, WEEKS, None, now=datetime(2026, 11, 23, 9, 0, tzinfo=league_tz()),
                                    window_close=close_of) is None
    # the last week of the schedule has no next window: nothing to protect
    assert gr.check_not_after_close(6, WEEKS, None, now=datetime(2026, 12, 1, tzinfo=league_tz()),
                                    window_close=close_of) is None


def test_step_3_main_refuses_and_force_overrides(monkeypatch, capsys):
    gr = _gr()
    calls = []
    monkeypatch.setattr(gr, "_guard_inputs", lambda base: (WEEKS, None))
    monkeypatch.setattr(gr, "league_now", lambda: datetime(2026, 11, 24, 15, 0, tzinfo=league_tz()))
    monkeypatch.setattr(gr, "_window_close", close_of)
    monkeypatch.setattr(gr, "generate_rosters", lambda *a, **k: calls.append((a, k)) or 0)
    assert gr.main(["--week", "5"]) == 1
    assert calls == []
    out = capsys.readouterr().out
    assert "REFUSED" in out and "--force" in out
    assert gr.main(["--week", "5", "--force"]) == 0
    assert len(calls) == 1
    assert "WARNING" in capsys.readouterr().out


# =============================================================================
# s.4: the workflow says the Monday-night build, and the afternoon run
# =============================================================================

def test_the_workflow_has_the_afternoon_run_and_the_monday_night_build():
    wf = (ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    first = wf.split("## Before You Start", 1)[0]
    assert "| **Afternoon** (step 3b" in first
    assert ("On any game day, a local run that writes state collides with the cloud's runs: the afternoon "
            "run (every game day), Monday's pre-tip runs and Monday's closing run.") in first
    assert "**Pull right before Step 6, and push as soon as the build is done.**" in first
    night = first.split("**The Monday-night build", 1)[1]
    assert "**Skip Steps 0, 1, 3, 4 and 4.75: the cloud has done them.**" in night
    assert "**Steps 2, 5, 5.75, 6, 6.5, 7, 7.5, 8, 9**" in night
    assert "**before the 12:05 AM nightly**" in night and "Closing line priced" in night
    assert "**Fallback: the old Monday-morning build**" in night and "(the Tuesday case" in night
    assert "--own-line" in night
