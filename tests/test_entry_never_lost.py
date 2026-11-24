"""5f item 3: a phone entry is never silently lost.

11-23: Nick opened issue #21, "Hayden move: +Dyson Daniels -Day'Ron Sharpe".
Nothing was saved, no comment was posted, and the issue stayed open; he found
out only because the reviewer checked the ledger. The rule: an entry that
passed its own checks is saved BEFORE the refresh (apply -> commit -> answer
-> refresh), a refresh failure afterwards is a failed refresh, not a lost
entry, and the issue is answered either way. Synthetic: a scratch league and
a fake run; the workflow by its source.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))

import apply_entry as ae                                 # noqa: E402
from modules import move_ledger as ml                    # noqa: E402
from test_phone_entries import _project, _event, _hash, WF  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=LA)
TITLE = "Benton move: +Bane -Alexander-Walker"


@pytest.fixture(autouse=True)
def _no_snapshot(monkeypatch):
    monkeypatch.setattr(ae, "snapshot", lambda base, now: {"week": 3, "lines": None, "title_odds": None})


@pytest.fixture
def world(monkeypatch):
    from test_move_ledger import make_world
    w = make_world(now=NOW)
    monkeypatch.setattr(ml.World, "from_base", classmethod(lambda cls, base=".", now=None, data=None: w))
    return w


def _apply(base, tmp_path, event, open_issues=()):
    out = tmp_path / "entry_out"
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(event))
    op = tmp_path / "open.json"
    op.write_text(json.dumps(list(open_issues)))
    a = SimpleNamespace(base_path=str(base), out_dir=str(out), event=str(ev), open_issues=str(op),
                        now=NOW.isoformat())
    assert ae.cmd_apply(a) == 0
    return json.loads((out / "actions.json").read_text()), out


def _effect(base, out, rows):
    runs = out.parent / "runs.jsonl"
    runs.write_text("".join(json.dumps(r) + "\n" for r in rows))
    a = SimpleNamespace(base_path=str(base), out_dir=str(out), runs_file=str(runs), skip=0)
    assert ae.cmd_effect(a) == 0
    return (out / "effect.md").read_text()


# --- the order: apply, commit, answer, THEN refresh (a source pin) ---------------

def _steps():
    import yaml
    return yaml.safe_load((WF / "run.yml").read_text(encoding="utf-8"))["jobs"]["run"]["steps"]


def test_the_entry_is_committed_and_answered_before_the_refresh_runs():
    steps = _steps()
    ids = [s.get("id") or s.get("name") for s in steps]
    order = [ids.index(x) for x in ("entry-list", "entry", "entry-commit", "entry-answer", "run")]
    assert order == sorted(order)
    commit = next(s for s in steps if s.get("id") == "entry-commit")
    assert "git push" in commit["run"] and "state_overlay.py out" in commit["run"]
    run = next(s for s in steps if s.get("id") == "run")
    assert "always()" not in str(run.get("if", ""))      # an entry run's refresh never runs on an unsaved entry
    eff = next(s for s in steps if s.get("name") == "Comment the entry's effect")
    assert eff["if"].startswith("always()") and "steps.entry-commit.outcome == 'success'" in eff["if"]
    # the run's own row comes after the answer: the entry's comment never waits on the refresh
    assert ids.index("entry-answer") < ids.index("run") < ids.index("Comment the entry's effect")


def test_a_failed_commit_answers_unsaved_and_a_dead_entry_step_answers_too():
    steps = _steps()
    ans = next(s for s in steps if s.get("id") == "entry-answer")
    assert ans["if"] == "always() && steps.entry.outcome == 'success'"
    assert 'if [ "$COMMITTED" = failure ]' in ans["run"] and "apply_entry.py unsaved" in ans["run"]
    dead = next(s for s in steps if s.get("name") == "Answer an entry step that failed")
    assert "steps.entry.outcome == 'failure'" in dead["if"] and "gh issue comment" in dead["run"]


def test_a_desk_refresh_and_the_nightly_catch_up_missed_entries_softly():
    steps = _steps()
    for sid in ("entry-list", "entry", "entry-commit", "entry-answer"):
        s = next(x for x in steps if x.get("id") == sid)
        assert s["continue-on-error"] == "${{ !inputs.entry }}", sid
    lst = next(x for x in steps if x.get("id") == "entry-list")
    assert lst["if"] == "inputs.entry || inputs.mode == 'refresh' || inputs.mode == 'nightly'"
    # pretip / closing / afternoon runs never apply an entry
    app = next(x for x in steps if x.get("id") == "entry")
    assert "pretip" not in app["if"] and "afternoon" not in app["if"]


# --- a refresh failure still leaves the entry saved, and answered -------------------

def test_a_refresh_failure_leaves_the_entry_in_the_ledger_and_comments(tmp_path, world):
    base = _project(tmp_path / "lg")
    acts, out = _apply(base, tmp_path, _event(21, TITLE, created="2026-11-05T17:29:00Z"))
    assert acts[0]["verdict"] == "applied" and acts[0]["close"]
    comment = (out / "21.md").read_text()
    assert comment.startswith("**Applied:** ledger entry 1:")
    assert [e["issue"] for e in ml.entries(ml.read_rows(base))] == [21]
    # the refresh then refuses (11-23's sparkline mismatch)
    text = _effect(base, out, [{"mode": "refresh", "outcome": "refused",
                                "error": "StepRefused: the sparkline's latest point for Nick is 31.3%"}])
    assert text.startswith("The refresh failed (StepRefused") and "The entry stands" in text
    assert [e["issue"] for e in ml.entries(ml.read_rows(base))] == [21]   # still saved


def test_a_comment_that_fails_after_the_save_still_says_applied(tmp_path, world, monkeypatch):
    base = _project(tmp_path / "lg")
    monkeypatch.setattr(ae, "ledger_comment", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    acts, out = _apply(base, tmp_path, _event(21, TITLE))
    assert acts[0]["verdict"] == "applied" and acts[0]["close"]
    assert "**Applied:** ledger entry 1" in (out / "21.md").read_text()
    assert "could not be written: RuntimeError: boom" in (out / "21.md").read_text()


def test_a_snapshot_that_fails_never_stops_the_entry(tmp_path, world, monkeypatch):
    base = _project(tmp_path / "lg")
    monkeypatch.setattr(ae, "snapshot", lambda base, now: (_ for _ in ()).throw(ValueError("no line")))
    acts, out = _apply(base, tmp_path, _event(21, TITLE))
    assert acts[0]["verdict"] == "applied"
    assert json.loads((out / "before.json").read_text())["error"] == "ValueError: no line"


def test_an_engine_error_is_answered_and_nothing_is_saved(tmp_path, world, monkeypatch):
    """Every writer writes last, after its checks: an error that escapes one
    was raised before anything was saved."""
    base = _project(tmp_path / "lg")
    before = _hash(base)
    monkeypatch.setattr(ml, "add", lambda *a, **k: (_ for _ in ()).throw(KeyError("World broke")))
    acts, out = _apply(base, tmp_path, _event(21, TITLE))
    assert acts[0]["verdict"] == "error" and not acts[0]["close"] and acts[0]["label"] == "entry-refused"
    assert (out / "21.md").read_text().startswith("**Not applied** (nothing was saved)")
    assert "KeyError" in (out / "21.md").read_text()
    assert _hash(base) == before


def test_an_injury_entry_whose_comment_fails_after_the_save_is_still_applied(tmp_path, monkeypatch):
    base = _project(tmp_path / "lg")
    monkeypatch.setattr(ae, "_json_block", lambda obj: (_ for _ in ()).throw(TypeError("no json")))
    acts, out = _apply(base, tmp_path, _event(23, "Injury remove: Coby White"))
    assert acts[0]["verdict"] == "applied" and acts[0]["close"]
    assert "could not be written: TypeError: no json" in (out / "23.md").read_text()
    blob = json.loads((base / "config" / "INJURY_OVERRIDES.json").read_text())
    assert blob["players"] == []                                   # saved


def test_every_writer_writes_after_its_last_raise():
    """The guarantee apply_guarded rests on, pinned by source: in each writer
    apply_one calls, the write comes after every raise (its checks)."""
    import inspect
    import overrides as ov
    from modules import trade_block as tb
    for fn, call in ((ml.add, "write_entries(base, rows, [row])"), (ov.apply, "write_change(base,"),
                     (tb.apply, "row = write_change(base, blob, new")):
        body = inspect.getsource(fn)
        assert call in body, fn.__name__
        assert body.rfind("raise ") < body.index(call), fn.__name__


def test_a_refused_entry_still_changes_nothing(tmp_path, world):
    base = _project(tmp_path / "lg")
    before = _hash(base)
    acts, out = _apply(base, tmp_path, _event(22, "Nick move: +Bane"))     # Nick's roster is full
    assert acts[0]["verdict"] == "refused" and acts[0]["label"] == "entry-refused"
    assert (out / "22.md").read_text().startswith("**Refused** (nothing was changed)")
    assert _hash(base) == before


def test_an_unsaved_entry_is_answered_not_saved_and_left_open(tmp_path, world):
    base = _project(tmp_path / "lg")
    acts, out = _apply(base, tmp_path, _event(21, TITLE))
    log = tmp_path / "entry-commit.log"
    log.write_text("entry committed?\nthe private repo moved: the entry is on branch rescue/run-7, not merged\n")
    assert ae.main(["unsaved", "--out-dir", str(out), "--log", str(log)]) == 0
    act = json.loads((out / "actions.json").read_text())[0]
    assert (act["verdict"], act["close"], act["label"]) == ("unsaved", False, None)
    text = (out / "21.md").read_text()
    assert text.startswith("**Checked, but NOT saved**") and "rescue/run-7" in text
    assert "next run applies it again" in text


def test_the_catch_up_without_an_issue_event_applies_the_open_entries(tmp_path, world):
    base = _project(tmp_path / "lg")
    opened = [{"number": 21, "title": TITLE, "createdAt": "2026-11-05T17:29:00Z",
               "author": {"login": "nickrolen"}, "labels": []}]
    acts, out = _apply(base, tmp_path, {"ref": "refs/heads/main", "pusher": {"name": "nickrolen"}}, opened)
    assert [(a["issue"], a["verdict"]) for a in acts] == [(21, "applied")]
    assert ae.applied_as(base, 21).startswith("ledger entry 1")
    # the nightly's row is this run's effect
    text = _effect(base, out, [{"mode": "nightly", "outcome": "ok"}])
    assert text.startswith("**Effect**")
