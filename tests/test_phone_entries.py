"""Step 3a: phone entries and the refresh they trigger
(claude/HANDOFF_STEP3A_PHONE_ENTRIES_2026-11-10.md).

  - the grammar: every form parses and round-trips; every malformed form
    refuses with a reason and changes nothing;
  - the injury forms through scripts/overrides.py: 13a (out the day it is
    made), set-return / set-notes / remove, the add refusal, task 26
    (updated_at, last_updated, the history), the comment's before/after equal
    to the file's diff;
  - scripts/apply_entry.py: only Nick (invariant 12), already applied, a
    refusal changes nothing and exits 0, the catch-up of a cancelled run, the
    ledger path (move_ledger.add, the issue number, the budget line);
  - the refresh: needs its cause; during the lock it prices nothing and still
    builds the hub; outside it a priced line's win-% row carries the cause;
    an unchanged one appends none; a chat claim leaves this week's line alone;
  - the nightly paragraph: built only by the nightly run, reused byte for
    byte, compared against the previous NIGHTLY row;
  - 13b both ways and the dedupe; 26's closing-line reconstruction and raise;
  - the workflows: the push trigger never loops, one concurrency group, the
    author check's login, no title in a shell line;
  - the new state files are in the manifest and ignored.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import apply_entry as ae                                 # noqa: E402
import overrides as ov                                   # noqa: E402
import returns_issue as ri                               # noqa: E402
from modules import hub_matchups as hm                   # noqa: E402
from modules import injury_entries as ie                 # noqa: E402
from modules import move_ledger as ml                    # noqa: E402
from modules import nightly                              # noqa: E402
from modules import override_history as oh               # noqa: E402
from modules import phone_entries as pe                  # noqa: E402
from modules import winprob_history as wh                # noqa: E402
from test_refresh_service import svc                     # noqa: E402,F401  (B3's scratch-week fixture)

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 11, 11, 14, 14, tzinfo=LA)          # Wed, week 4 (11-09 .. 11-15)
SCHEDULE = json.loads((ROOT / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
WF = ROOT / "deploy" / "state-repo" / ".github" / "workflows"


# =============================================================================
# a scratch league folder
# =============================================================================

def _project(tmp_path, entries=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHEDULE))
    days = ["2026-11-12", "2026-11-14", "2026-11-16", "2026-11-18", "2026-11-20", "2026-11-23",
            "2026-11-25", "2026-12-01", "2026-12-05", "2026-12-08", "2026-12-09", "2026-12-12"]
    games = {"games": [{"date": f"{d}T00:00:00Z", "home": "AAA", "away": "ZZZ"} for d in days]}
    (tmp_path / "data" / "nba_schedule_2026-27.json").write_text(json.dumps(games))
    players = {"Alpha Player": "AAA", "Coby White": "AAA", "Derrick White": "AAA",
               "Jayson Tatum": "AAA", "Nikola Jokic": "AAA"}
    (tmp_path / "data" / "NBA_PLAYER_REFERENCE.json").write_text(json.dumps({
        "fetched_at": "2026-11-01T00:00:00+00:00",
        "seasons": {"this_season": {"players": players}, "last_completed": {"players": {}}}}))
    pd.DataFrame({"player_name": list(players), "player_nba_team": ["AAA"] * len(players),
                  "projectedFPPG": [30.0] * len(players)}).to_excel(
        tmp_path / "data" / "PLAYERLIST.xlsx", index=False)
    (tmp_path / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": {"Nick": ["Coby White"]}}))
    blob = {"last_updated": "2026-11-09", "players": entries if entries is not None else [
        {"player_name": "Coby White", "nba_team": "AAA", "out_weeks": [3, 4], "notes": "calf",
         "return_week": 5, "return_games": 2, "total_week_games": 3,
         "return_notes": "Possibly returning from calf injury on 11/18", "return_date": "2026-11-18"}]}
    (tmp_path / "config" / "INJURY_OVERRIDES.json").write_text(json.dumps(blob, indent=2))
    return tmp_path


def _hash(base: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(base.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(base).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _entries(base):
    return json.loads((base / "config" / "INJURY_OVERRIDES.json").read_text(encoding="utf-8"))["players"]


def _event(n, title, *, author="nickrolen", sender="nickrolen", action="opened",
           created="2026-11-11T22:10:00Z", labels=()):
    return {"action": action, "sender": {"login": sender},
            "issue": {"number": n, "title": title, "user": {"login": author}, "created_at": created,
                      "labels": [{"name": x} for x in labels], "state": "open"}}


def _apply(base, tmp_path, event, open_issues=(), monkeypatch=None):
    out = tmp_path / "entry_out"
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(event))
    op = tmp_path / "open.json"
    op.write_text(json.dumps(list(open_issues)))
    a = SimpleNamespace(base_path=str(base), out_dir=str(out), event=str(ev), open_issues=str(op),
                        now=NOW.isoformat())
    assert ae.cmd_apply(a) == 0                          # a refusal is never a failed run
    acts = json.loads((out / "actions.json").read_text())
    return acts, out


@pytest.fixture(autouse=True)
def _no_snapshot(monkeypatch):
    # the effect's "before" reads the real line and title odds; not in a scratch folder
    monkeypatch.setattr(ae, "snapshot", lambda base, now: {"week": 4, "lines": None, "title_odds": None})


# =============================================================================
# the grammar
# =============================================================================

CANONICAL = [
    "Injury: Tatum knee, back 12/09",
    "Injury: Tatum knee, out for season",
    "Injury: Coby White back 11/05",
    "Injury: Banchero notes ankle",
    "Injury remove: Coby White",
    "Injury: Tatum, back 12/09",
    "Benton move: +Bane -Alexander-Walker",
    "Nick move: +Bane IL+Edwards",
    "Hayden move: -Wagner IL-Leonard",
    "Trade: Benton gets Tatum; Hayden gets Barnes",
    "Trade: Benton gets Tatum, Jokic; Hayden gets Barnes",
]


@pytest.mark.parametrize("title", CANONICAL)
def test_every_title_form_parses_and_round_trips(title):
    assert pe.format_title(pe.parse_title(title, ["Nick", "Hayden", "Garrett", "Benton"])) == title


@pytest.mark.parametrize("title,form", [
    ("Injury: Tatum knee, back 12/09", "add"), ("Injury: Tatum knee, out for season", "season"),
    ("Injury: Coby White back 11/05", "set-return"), ("Injury: Banchero notes ankle", "set-notes"),
    ("Injury remove: Coby White", "remove"), ("injury: coby white BACK 11/5", "set-return")])
def test_each_injury_form_is_the_right_command(title, form):
    assert pe.parse_title(title)["form"] == form


MALFORMED = [
    ("", "An empty title"),
    ("Injury Tatum back 12/09", "matches none of its forms"),
    ("Injury: Tatum knee back", "matches none of its forms"),
    ("Injury: Tatum, back December 9", "matches none of its forms"),
    ("Injury remove:", "matches none of its forms"),
    ("Tatum is hurt", "is not an entry"),
    ("Nick move:", "a move with no parts"),
    ("Trade: Nick gets Tatum", "exactly two sides"),
    ("Bob move: +Bane", "'Bob' is not a manager"),
    ("Injury: Tatum knee, back 02/30", "is not a day"),
    ("Injury: Tatum knee, back 06/01", "outside the season"),
    ("Injury: Tatum knee, back 11/05", "in the past"),
    ("Injury: White knee, back 12/09", "could be Coby White, Derrick White"),
    ("Injury: Qqqq Zzzz knee, back 12/09", "matches no NBA player"),
    ("Injury: Alpha Player knee, back 12/09\nInjury remove: X", "One entry per issue"),
]


@pytest.mark.parametrize("title,why", MALFORMED)
def test_every_malformed_title_refuses_with_a_reason_and_changes_nothing(tmp_path, title, why):
    base = _project(tmp_path / "lg")
    before = _hash(base)
    acts, out = _apply(base, tmp_path, _event(7, title))
    assert [a["verdict"] for a in acts] == ["refused"]
    text = (out / "7.md").read_text()
    assert why in text and "Accepted forms:" in text, text
    assert acts[0]["label"] == "entry-refused" and not acts[0]["close"]
    assert _hash(base) == before                          # state untouched
    assert (out / "cause.txt").read_text().strip() == ""


def test_dates_are_the_next_such_day_inside_the_season():
    assert pe.resolve_day((12, 9), date(2026, 11, 11), SCHEDULE) == date(2026, 12, 9)
    assert pe.resolve_day((1, 25), date(2026, 11, 11), SCHEDULE) == date(2027, 1, 25)
    assert pe.resolve_day((11, 11), date(2026, 11, 11), SCHEDULE) == date(2026, 11, 11)
    with pytest.raises(pe.TitleRefused, match="in the past"):
        pe.resolve_day((11, 10), date(2026, 11, 11), SCHEDULE)
    with pytest.raises(pe.TitleRefused, match="outside the season"):
        pe.resolve_day((8, 1), date(2026, 11, 11), SCHEDULE)


def test_a_new_entrys_player_is_the_longest_run_of_words_naming_one_player(tmp_path):
    base = _project(tmp_path)
    from modules import nba_reference as nr
    ref = nr.Reference(base)
    res = lambda n: ov.resolve_player(n, ref)
    assert pe.split_subject("Coby White left calf", res) == ("Coby White", "left calf")
    assert pe.split_subject("Tatum knee", res) == ("Jayson Tatum", "knee")
    assert pe.split_subject("Jokic", res) == ("Nikola Jokic", None)
    with pytest.raises(pe.TitleRefused, match="could be Coby White, Derrick White"):
        pe.split_subject("White calf", res)


# =============================================================================
# the injury forms (overrides.py's functions; 13a; task 26)
# =============================================================================

def _blocks(text):
    return [None if b is None else json.loads(b) for b in
            [m.group(1) if m.group(1) else None
             for m in re.finditer(r"(?:```json\n(.*?)\n```|\(no entry\))", text, re.S)]]


def _file_diff(before_players, after_players, name):
    b = next((e for e in before_players if e["player_name"] == name), None)
    a = next((e for e in after_players if e["player_name"] == name), None)
    return b, a


@pytest.mark.parametrize("title,name", [
    ("Injury: Tatum knee, back 12/09", "Jayson Tatum"),
    ("Injury: Jokic, out for season", "Nikola Jokic"),
    ("Injury: Coby White back 12/05", "Coby White"),
    ("Injury: White notes left calf, day to day", None),
    ("Injury: Coby White notes left calf", "Coby White"),
    ("Injury remove: Coby White", "Coby White"),
])
def test_the_comments_before_and_after_equal_the_files_diff(tmp_path, title, name):
    base = _project(tmp_path / "lg")
    before = _entries(base)
    acts, out = _apply(base, tmp_path, _event(11, title))
    if name is None:                                       # "White" is not unique among the entries? it is
        name = "Coby White"
    assert acts[0]["verdict"] == "applied", (out / "11.md").read_text()
    after = _entries(base)
    b, a = _blocks((out / "11.md").read_text())
    assert (b, a) == _file_diff(before, after, name)
    assert acts[0]["close"] is True and acts[0]["label"] is None
    # the history row says the same
    row = oh.read(base)[-1]
    assert (row["before"], row["after"], row["issue"], row["by"]) == (b, a, 11, "issue #11")
    assert row["last_updated_after"] == "2026-11-11"
    assert json.loads((base / "config" / "INJURY_OVERRIDES.json").read_text())["last_updated"] == "2026-11-11"


def test_13a_a_new_entry_is_out_from_the_day_it_is_made_and_carries_updated_at(tmp_path):
    base = _project(tmp_path / "lg")
    acts, out = _apply(base, tmp_path, _event(3, "Injury: Tatum knee, back 12/09"))
    e = next(x for x in _entries(base) if x["player_name"] == "Jayson Tatum")
    assert e["out_weeks"] == [4, 5, 6] and e["return_week"] == 7       # out from Wed 11-11 (week 4)
    assert e["notes"] == "knee" and e["return_date"] == "2026-12-09"
    assert e["updated_at"] == NOW.isoformat(timespec="seconds")
    assert (out / "cause.txt").read_text().strip() == "injury update: Jayson Tatum out, back 12-09"


def test_set_return_changes_only_the_return_date_and_what_follows_from_it(tmp_path):
    base = _project(tmp_path / "lg")
    old = _entries(base)[0]
    acts, out = _apply(base, tmp_path, _event(4, "Injury: Coby White back 12/01"))
    new = _entries(base)[0]
    changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    assert changed <= {"out_weeks", "return_week", "return_games", "total_week_games", "return_notes",
                       "return_date", "updated_at"}
    assert new["notes"] == old["notes"] and new["nba_team"] == old["nba_team"]
    assert new["out_weeks"][0] == old["out_weeks"][0]                    # the out date is untouched
    assert new["out_weeks"] == [3, 4, 5, 6] and new["return_week"] == 7
    assert new["return_notes"] == "Possibly returning from calf injury on 12/01"
    assert (out / "cause.txt").read_text().strip() == "injury update: Coby White back 12-01"


def test_set_notes_changes_only_notes(tmp_path):
    base = _project(tmp_path / "lg")
    old = _entries(base)[0]
    _apply(base, tmp_path, _event(5, "Injury: Coby White notes calf strain, re-evaluated 11-20"))
    new = _entries(base)[0]
    assert {k for k in set(old) | set(new) if old.get(k) != new.get(k)} == {"notes", "updated_at"}
    assert new["notes"] == "calf strain, re-evaluated 11-20"


def test_remove_of_a_name_with_no_entry_refuses_and_an_add_on_an_entry_points_to_the_edit_forms(tmp_path):
    base = _project(tmp_path / "lg")
    before = _hash(base)
    acts, out = _apply(base, tmp_path, _event(6, "Injury remove: Jayson Tatum"))
    assert acts[0]["verdict"] == "refused" and "has no injury entry" in (out / "6.md").read_text()
    acts, out = _apply(base, tmp_path, _event(8, "Injury: Coby White calf, back 12/09"))
    text = (out / "8.md").read_text()
    assert acts[0]["verdict"] == "refused"
    assert "already has an injury entry" in text and "Injury: Coby White back MM/DD" in text
    assert _hash(base) == before


def test_the_desk_edit_commands_write_the_history_too(tmp_path):
    base = _project(tmp_path / "lg")
    a = SimpleNamespace(cmd="set-return", name="Coby White", back="2026-12-08", notes=None, yes=True)
    assert ov.cmd_edit(a, base, now=NOW) == 0
    a = SimpleNamespace(cmd="remove", name="White", back=None, notes=None, yes=True)
    assert ov.cmd_edit(a, base, now=NOW) == 0
    assert [r["action"] for r in oh.read(base)] == ["set-return", "remove"]
    assert {r["by"] for r in oh.read(base)} == {"overrides.py (desk)"}
    assert _entries(base) == []


def test_only_write_change_writes_the_overrides_file():
    srcs = {p.name: p.read_text(encoding="utf-8") for d in ("modules", "scripts")
            for p in (ROOT / d).glob("*.py")}
    writers = {n for n, s in srcs.items()
               if re.search(r"atomic_write_json\([^)]*OVERRIDES", s) or "INJURY_OVERRIDES.json\", \"w" in s}
    assert writers == {"overrides.py"}
    body = srcs["overrides.py"]
    assert body.count("atomic_write_json(base / OVERRIDES") == 1                 # write_change only
    assert "oh.append(base, row)" in body.split("def write_change")[1].split("def ")[0]


# =============================================================================
# apply_entry: who, already, the catch-up, the ledger
# =============================================================================

def test_the_allowed_login_is_one_constant_and_the_workflow_uses_it():
    assert ae.NICK == "nickrolen"
    entry = (WF / "entry.yml").read_text(encoding="utf-8")
    assert entry.count(f"'{ae.NICK}'") == 4                  # refuse: 2, entry: 2
    assert "--author nickrolen" in (WF / "run.yml").read_text(encoding="utf-8")


@pytest.mark.parametrize("author,sender", [("someone", "someone"), ("nickrolen", "someone"),
                                           ("someone", "nickrolen")])
def test_a_non_nick_author_or_sender_is_refused_with_one_comment_and_nothing_else(tmp_path, author,
                                                                                   sender):
    base = _project(tmp_path / "lg")
    before = _hash(base)
    acts, out = _apply(base, tmp_path, _event(9, "Injury remove: Coby White", author=author, sender=sender))
    assert acts == [{"issue": 9, "verdict": "unauthorized", "comment": ae.UNAUTHORIZED, "close": False,
                     "label": None, "unlabel": False, "facts_only": False, "comment_file": "9.md"}]
    assert ae.UNAUTHORIZED == "Only Nick's entries are applied."
    assert _hash(base) == before


def test_an_applied_issue_edited_later_gets_already_applied_and_nothing_else(tmp_path):
    base = _project(tmp_path / "lg")
    _apply(base, tmp_path, _event(12, "Injury: Coby White back 12/01"))
    before = _hash(base)
    acts, out = _apply(base, tmp_path, _event(12, "Injury: Coby White back 12/05", action="edited"))
    assert acts[0]["verdict"] == "already"
    assert (out / "12.md").read_text().startswith("Already applied as set-return Coby White")
    assert "open a new issue to change it" in (out / "12.md").read_text()
    assert _hash(base) == before and (out / "cause.txt").read_text().strip() == ""


def test_an_edited_refused_issue_is_reparsed_and_applied(tmp_path):
    base = _project(tmp_path / "lg")
    acts, _ = _apply(base, tmp_path, _event(13, "Injury: Coby Whte back 12/01"))
    assert acts[0]["verdict"] == "refused"
    acts, _ = _apply(base, tmp_path, _event(13, "Injury: Coby White back 12/01", action="edited",
                                            labels=["entry-refused"]))
    assert acts[0]["verdict"] == "applied" and acts[0]["unlabel"] and acts[0]["close"]


def test_a_cancelled_runs_entry_is_applied_by_the_next_run_in_issue_order(tmp_path):
    base = _project(tmp_path / "lg")
    opened = [{"number": 20, "title": "Injury: Tatum knee, back 12/09", "createdAt": "2026-11-11T22:00:00Z",
               "author": {"login": "nickrolen"}, "labels": []},
              {"number": 19, "title": "not an entry at all", "createdAt": "2026-11-11T21:00:00Z",
               "author": {"login": "nickrolen"}, "labels": [{"name": "entry-refused"}]},
              {"number": 18, "title": "Nightly run failed: x", "createdAt": "2026-11-11T20:00:00Z",
               "author": {"login": "github-actions"}, "labels": [{"name": "run-failed"}]}]
    acts, out = _apply(base, tmp_path, _event(21, "Injury remove: Coby White"), opened)
    assert [(a["issue"], a["verdict"]) for a in acts] == [(20, "applied"), (21, "applied")]
    assert (out / "cause.txt").read_text().strip() == (
        "2 entries: injury update: Jayson Tatum out, back 12-09; injury removed: Coby White")
    assert [r["issue"] for r in oh.read(base)] == [20, 21]


@pytest.fixture
def ledger_world(monkeypatch):
    from test_move_ledger import make_world
    w = make_world(now=datetime(2026, 11, 5, 12, 0, tzinfo=LA))
    monkeypatch.setattr(ml.World, "from_base", classmethod(lambda cls, base=".", now=None, data=None: w))
    return w


def test_a_move_entry_goes_through_move_ledgers_add_with_its_issue_number(tmp_path, ledger_world,
                                                                          monkeypatch):
    called = []
    real = ml.add

    def spy(*a, **k):
        called.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(ml, "add", spy)
    now = datetime(2026, 11, 5, 12, 0, tzinfo=LA)
    res = ae.apply_one(tmp_path, "Benton move: +Bane -Alexander-Walker", 31,
                       datetime(2026, 11, 5, 9, 29, tzinfo=LA), now)
    assert res["verdict"] == "applied" and res["cause"] == "Benton move: +Bane -Alexander-Walker"
    (a, k), = called
    assert a[1] == "Benton move: +Bane -Alexander-Walker" and k["issue"] == 31
    assert k["claimed_at"] == datetime(2026, 11, 5, 9, 29, tzinfo=LA)       # when it was posted
    row = ml.read_rows(tmp_path)[-1]
    assert row["issue"] == 31 and row["claim_week"] == 3 and row["window"] == "2026-11-09"
    assert "Benton: 1 of 3 used in week 3." in res["comment"]
    assert "counts in week 3's budget" in res["comment"]
    assert "This week's line does not change" in res["comment"]
    assert ae.applied_as(tmp_path, 31).startswith("ledger entry 1")


def test_a_move_refused_by_the_ledgers_checks_changes_nothing(tmp_path, ledger_world):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=LA)
    res = ae.apply_one(tmp_path, "Nick move: +Bane", 32, now, now)
    assert res["verdict"] == "refused" and "roster is full" in res["comment"]
    assert not (tmp_path / ml.LEDGER_FILE).exists()


def test_the_same_issue_is_never_two_ledger_entries(tmp_path, ledger_world):
    now = datetime(2026, 11, 5, 12, 0, tzinfo=LA)
    assert ae.apply_one(tmp_path, "Benton move: -Alexander-Walker", 33, now, now)["verdict"] == "applied"
    with pytest.raises(ml.EntryRefused, match="already ledger entry 1"):
        ml.add(tmp_path, "Benton move: +Bane", now=now, issue=33)


# =============================================================================
# the effect comment
# =============================================================================

def test_the_effect_shows_win_and_title_odds_before_and_after_or_says_it_waits():
    before = {"week": 4, "lines": {"Nick|Benton": [55.2, 44.8], "Hayden|Garrett": [10.4, 89.6]},
              "title_odds": {"Hayden": 31.0, "Nick": 50.0}}
    after = {"week": 4, "lines": {"Nick|Benton": [57.0, 43.0], "Hayden|Garrett": [10.4, 89.6]},
             "title_odds": {"Hayden": 27.4, "Nick": 53.6}}
    text = ae.effect_text(before, after, {"outcome": "ok"})
    assert "- Nick vs Benton: Nick 55.2% \u2192 57.0%" in text
    assert "- Hayden vs Garrett: Hayden 10.4% \u2192 10.4% (unchanged)" in text
    assert "- Hayden title odds 31.0% \u2192 27.4%" in text
    assert ae.effect_text(before, before, {"outcome": "locked"}).startswith("Priced after tonight's games")
    assert "12:01 AM run" in ae.effect_text(before, before, {"outcome": "deferred"})
    assert "failed" in ae.effect_text(before, before, {"outcome": "refused", "error": "x"})


# =============================================================================
# the refresh run
# =============================================================================

def test_a_refresh_needs_its_cause(capsys):
    with pytest.raises(ValueError, match="needs its cause"):
        nightly.Run(".", "refresh", now=NOW)
    with pytest.raises(SystemExit):
        nightly.main(["--refresh"])
    with pytest.raises(SystemExit):
        nightly.main(["--cause", "x"])
    assert nightly.Run(".", "refresh", now=NOW, cause="injury removed: Coby White").cause == \
        "injury removed: Coby White"
    assert nightly.Run(".", "nightly", now=NOW).cause == "nightly"
    assert nightly.Run(".", "pretip", now=NOW).cause == "Monday pre-tip"


def _stubbed(mode, tmp_path, **over):
    calls = []
    steps = {n: (lambda n=n: calls.append(n) or f"{n} done") for n in nightly.STEPS[mode]}
    steps.update(over)
    return steps, calls


def test_a_refresh_during_the_lock_prices_nothing_and_still_rebuilds_the_hub(tmp_path, monkeypatch):
    import refresh_service as rs
    from modules import data_loader, price_lock, title_odds_run
    monkeypatch.setattr(data_loader, "load_all_data", lambda *a, **k: SimpleNamespace(nba_schedule={}))
    monkeypatch.setattr(price_lock, "status", lambda now, sched: {"locked": True, "first_tip": "16:00",
                                                                "league_day": "2026-11-11"})
    monkeypatch.setattr(rs, "run", lambda *a, **k: pytest.fail("priced during the lock"))
    monkeypatch.setattr(title_odds_run, "price", lambda *a, **k: pytest.fail("title odds during the lock"))
    run = nightly.Run(tmp_path, "refresh", now=NOW, cause="injury removed: Coby White", echo=lambda *a: None)
    steps, calls = _stubbed("refresh", tmp_path)
    del steps["line"], steps["title_odds"]
    row = run.execute(steps)
    assert row["outcome"] == "locked" and row["exit"] == 0 and row["cause"] == "injury removed: Coby White"
    detail = {s["step"]: s["detail"] for s in row["steps"]}
    assert detail["line"].startswith("locked") and detail["title_odds"] == "locked: nothing priced"
    assert "hub" in calls and "actuals" in calls                       # the facts still update


def test_a_refresh_passes_its_cause_to_the_pricer_and_an_unchanged_line_shows_it(tmp_path, monkeypatch):
    import refresh_service as rs
    from modules import data_loader, price_lock
    monkeypatch.setattr(data_loader, "load_all_data", lambda *a, **k: SimpleNamespace(nba_schedule={}))
    monkeypatch.setattr(price_lock, "status", lambda now, sched: {"locked": False, "first_tip": "16:00"})
    seen = {}

    def fake_run(base, **k):
        seen.update(k)
        return {"exit": 0, "outcome": "unchanged"}
    monkeypatch.setattr(rs, "run", fake_run)
    run = nightly.Run(tmp_path, "refresh", now=NOW, cause="Benton move: +Bane", echo=lambda *a: None)
    run.ctx["tags"] = {}
    assert run.step_line() == "unchanged"                  # a chat claim: this week's line stays
    assert seen["cause"] == "Benton move: +Bane" and seen["trigger"] == "refresh"
    assert not run.ctx.get("locked")                        # title odds are re-priced


def test_a_refresh_before_the_nightly_banks_last_night_is_deferred_not_failed(tmp_path, monkeypatch):
    import refresh_service as rs
    from modules import data_loader
    monkeypatch.setattr(data_loader, "load_all_data", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(rs, "missing_days", lambda data, today: [date(2026, 11, 10)])
    run = nightly.Run(tmp_path, "refresh", now=NOW, cause="injury removed: Coby White", echo=lambda *a: None)
    steps, calls = _stubbed("refresh", tmp_path)
    del steps["banked"]
    row = run.execute(steps)
    assert row["outcome"] == "deferred" and row["exit"] == 0 and calls == ["engine"]


def test_a_priced_refresh_appends_one_win_row_with_its_cause_and_an_unchanged_one_none(svc, tmp_path):
    from test_live_lines import MON
    from test_refresh_service import TAGS
    out = svc(MON, cause="injury update: Nikola Jokic out, back 11-21")
    assert out["outcome"] == "priced", out
    rows = wh.read(tmp_path, 2)
    assert len(rows) == 1 and rows[0]["cause"] == "injury update: Nikola Jokic out, back 11-21"
    assert rows[0]["changed"] == ["no line on disk"]
    out = svc(MON, cause="injury notes: Nikola Jokic")
    assert out["outcome"] == "unchanged" and len(wh.read(tmp_path, 2)) == 1   # an unchanged run: no row
    out = svc(MON, statuses={**TAGS, "B1": "O"}, cause="Benton move: +Bane")  # a tag moved meanwhile
    rows = wh.read(tmp_path, 2)
    assert out["outcome"] == "priced" and len(rows) == 2
    assert (rows[1]["cause"], rows[1]["changed"]) == ("Benton move: +Bane", ["tags"])
    assert wh.label(rows[1]) == "Benton move: +Bane; also moved: tags"


def test_the_tap_text_shows_the_cause_and_rows_before_it_their_trigger():
    from modules import hub_charts as hc
    base = {"schema": 1, "week": 4, "run_id": "r", "as_of": "2026-11-11T14:14:00-08:00",
            "league_day": "2026-11-11", "completed_dates": [],
            "matchups": [{"manager_a": "Nick", "manager_b": "Benton", "win_prob_a": 55.2, "win_prob_b": 44.8,
                          "banked_a": 0, "banked_b": 0, "projected_final_a": 1, "projected_final_b": 1}]}
    old = dict(base, trigger="nightly")
    new = dict(base, trigger="refresh", cause="injury update: Zion Williamson out", changed=["overrides"])
    both = dict(new, changed=["overrides", "tags"])
    pts = hc.winprob_points("Nick", "Benton", [old, new, both], None, None)
    assert [p[3] for p in pts] == ["nightly run", "injury update: Zion Williamson out",
                                   "injury update: Zion Williamson out; also moved: tags"]
    tz = ZoneInfo("America/Los_Angeles")
    entry = next(w for w in SCHEDULE["weeks"] if int(w["week"]) == 4)
    chart = hc.winprob_chart(entry, "Nick", "Benton", pts[1:2], tz)
    assert chart["hits"][0]["tip"] == ("Wed 11-11, 2:14 PM (injury update: Zion Williamson out): "
                                       "Nick 55.2%, Benton 44.8%")


def test_the_lock_note_counts_each_locked_refresh_as_a_change_waiting(tmp_path):
    from modules import hub_state
    rows = [{"mode": "refresh", "outcome": "locked", "started_at": "2026-11-11T17:00:00-08:00"},
            {"mode": "refresh", "outcome": "locked", "started_at": "2026-11-11T18:00:00-08:00"},
            {"mode": "refresh", "outcome": "ok", "started_at": "2026-11-11T12:00:00-08:00"},
            {"mode": "refresh", "outcome": "locked", "started_at": "2026-11-10T18:00:00-08:00"}]
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "nightly_runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    st = {"locked": True, "first_tip": "2026-11-11T16:00-08:00", "league_day": "2026-11-11"}
    assert hub_state.lock_note(st, tmp_path, 4)["text"] == \
        "Lines locked while games are on. 2 changes waiting; priced after tonight's games."
    (tmp_path / "output" / "nightly_runs.jsonl").write_text("")
    assert "first tip" in hub_state.lock_note(st, tmp_path, 4)["text"]


# =============================================================================
# the nightly paragraph (decisions 2-3)
# =============================================================================

def _wrow(trigger, at, win_a):
    return {"trigger": trigger, "as_of": at, "matchups": [{"manager_a": "Nick", "manager_b": "Benton",
                                                           "win_prob_a": win_a, "win_prob_b": 100 - win_a}]}


def test_since_the_last_update_compares_against_the_previous_nightly_row():
    rows = [_wrow("nightly", "2026-11-10T00:05:00-08:00", 50.0),
            _wrow("refresh", "2026-11-10T14:00:00-08:00", 61.0),
            _wrow("pretip", "2026-11-10T15:30:00-08:00", 62.0),
            _wrow("nightly", "2026-11-11T00:05:00-08:00", 64.0)]
    line_at = datetime(2026, 11, 11, 0, 5, tzinfo=LA)
    assert hm.prev_nightly_row(rows, line_at)["as_of"] == "2026-11-10T00:05:00-08:00"
    # a refresh's own line: still last night's row, never the refresh before it
    assert hm.prev_nightly_row(rows, datetime(2026, 11, 11, 15, 0, tzinfo=LA))["as_of"] == \
        "2026-11-11T00:05:00-08:00"


def test_the_nightly_paragraph_is_byte_identical_across_a_later_refresh(tmp_path):
    para = {"head": "Tonight's update \u00b7 Wed 11-11", "framing": "steady",
            "text": "Nick is ahead of Benton, 1,487.5 to 1,446.9, by 40.6. The line gives Nick 69.3%."}
    (tmp_path / "output").mkdir()
    hm.write_night(tmp_path, {"week": 4, "league_day": "2026-11-11", "paras": {"Nick|Benton": para}},
                   run_id="n1")
    raw = hm.night_path(tmp_path).read_bytes()
    stored = hm.read_night(tmp_path)
    assert hm.stored_para(stored, 4, "Nick", "Benton") == para
    assert json.dumps(hm.stored_para(stored, 4, "Nick", "Benton"), sort_keys=True) == \
        json.dumps(para, sort_keys=True)
    assert hm.stored_para(stored, 5, "Nick", "Benton") is None            # next week: none until Tuesday
    assert hm.night_path(tmp_path).read_bytes() == raw                    # reading never rewrites


@pytest.mark.parametrize("mode,night,writes", [("nightly", "build", True), ("refresh", "reuse", False),
                                               ("pretip", "reuse", False)])
def test_only_the_nightly_run_builds_and_stores_the_paragraph(tmp_path, monkeypatch, mode, night, writes):
    import build_hub
    from modules import hub_state
    got = {}

    def fake_build(base, **k):
        got.update(k)
        if k["night_out"] is not None:
            k["night_out"]["night"] = {"week": 4, "league_day": "2026-11-11", "paras": {}}
        return {"header": {"engine_mismatch": False}}
    monkeypatch.setattr(hub_state, "build", fake_build)
    monkeypatch.setattr(hub_state, "write", lambda base, payload: None)
    monkeypatch.setattr(build_hub, "main", lambda argv: 0)
    wrote = []
    monkeypatch.setattr(hm, "write_night", lambda base, n, run_id: wrote.append(run_id))
    from modules import hub_cards                     # task 40: the cards step, stubbed here
    monkeypatch.setattr(hub_cards, "build", lambda base, payload, **k: {"cards": {}, "seconds": 0.0})
    monkeypatch.setattr(hub_cards, "write", lambda base, obj: None)
    monkeypatch.setattr(hub_cards, "coverage", lambda base, payload: {"with": 0, "rostered": 0, "library": 0})
    run = nightly.Run(tmp_path, mode, now=NOW, cause="x" if mode == "refresh" else None)
    run.step_hub()
    assert got["night"] == night and bool(wrote) == writes
    assert "cards_out" in got                         # the run's keepability goes to the cards


def test_only_the_nightly_hub_step_writes_the_paragraph_file():
    import ast
    callers = set()
    for p in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == "write_night":
                        callers.add(f"{p.name}:{fn.name}")
    assert callers == {"nightly.py:step_hub"}


# =============================================================================
# 13b: passed return dates (the nightly run)
# =============================================================================

def _returns_run(base, monkeypatch, tags, fa=None, rostered=("Coby White",), listed=("Coby White",)):
    from modules import data_loader
    from modules.fetch_injury_statuses import Tags
    monkeypatch.setattr(data_loader, "load_all_data", lambda *a, **k: SimpleNamespace(
        get_current_rosters=lambda: {"Nick": list(rostered)},
        playerlist=pd.DataFrame({"player_name": list(listed)})))
    run = nightly.Run(base, "nightly", now=datetime(2026, 11, 19, 0, 5, tzinfo=LA))
    run.ctx["tags"] = Tags(tags, fa if fa is not None else {})
    detail = run.step_returns()
    return run, detail


def test_13b_a_passed_return_with_no_out_tag_is_removed_and_listed(tmp_path, monkeypatch):
    base = _project(tmp_path)
    run, detail = _returns_run(base, monkeypatch, {"Coby White": "Q"})
    assert _entries(base) == []
    assert run.ctx["returns"] == {"removed": [{"player": "Coby White", "return_date": "2026-11-18",
                                               "tag": "Q"}], "issues": []}
    assert detail == "removed Coby White (back 11-18, tag Q)"
    assert oh.read(base)[-1]["by"] == "nightly (13b)" and oh.read(base)[-1]["action"] == "remove"


@pytest.mark.parametrize("tags,want", [({"Coby White": "O"}, "he is still tagged O"),
                                       ({"Coby White": "OFS"}, "he is still tagged OFS")])
def test_13b_a_passed_return_still_tagged_out_opens_one_issue_and_keeps_the_entry(tmp_path, monkeypatch,
                                                                                 tags, want):
    base = _project(tmp_path)
    before = _hash(base)
    run, _ = _returns_run(base, monkeypatch, tags)
    (i,) = run.ctx["returns"]["issues"]
    assert i["title"] == f"Coby White's return date 11-18 has passed; {want}"
    assert "`Injury: Coby White back MM/DD`" in i["body"] and "`Injury remove: Coby White`" in i["body"]
    assert _hash(base) == before                           # nothing removed


def test_13b_an_unknown_tag_asks_rather_than_removes(tmp_path, monkeypatch):
    base = _project(tmp_path)
    run, _ = _returns_run(base, monkeypatch, {}, rostered=(), listed=())
    assert run.ctx["returns"]["issues"][0]["title"].endswith("his Yahoo tag is unknown")
    assert len(_entries(base)) == 1


def test_13b_the_issue_is_one_per_player_while_open(tmp_path, monkeypatch):
    base = _project(tmp_path)
    titles = []
    for night in range(2):                                 # two nights, same state: the same title
        run, _ = _returns_run(base, monkeypatch, {"Coby White": "O"})
        row = {"mode": "nightly", "returns": run.ctx["returns"]}
        f = tmp_path / f"runs{night}.jsonl"
        f.write_text(json.dumps(row) + "\n")
        titles.append(ri.titles(ri.returns_block(str(f), 0)))
    assert titles[0] == titles[1] and len(titles[0]) == 1
    wf = (WF / "run.yml").read_text(encoding="utf-8")
    step = wf[wf.index("Open or close the passed-return issues"):]
    step = step[:step.index("- name:", 10)]
    assert "grep -qxF" in step and "open already" in step        # dedupe by title
    assert "gh issue close" in step                               # an answered one closes


# =============================================================================
# 26: the history and the closing line
# =============================================================================

def _h(at, action, player, before, after, lu_b="2026-11-09", lu_a="2026-11-16"):
    return oh.make_row(at=at, action=action, player=player, before=before, after=after,
                       last_updated_before=lu_b, last_updated_after=lu_a, by="t")


A = {"player_name": "Coby White", "out_weeks": [4], "return_week": 5, "return_date": "2026-11-18"}
B = dict(A, out_weeks=[4, 5], return_week=6, return_date="2026-11-23",
         updated_at="2026-11-16T17:30:00-08:00")
TIP = datetime(2026, 11, 16, 16, 0, tzinfo=LA)


def test_the_history_rebuilds_the_overrides_as_at_the_first_tip():
    rows = [_h(datetime(2026, 11, 16, 9, 0, tzinfo=LA), "add", "Coby White", None, A, "2026-11-09", "2026-11-16"),
            _h(datetime(2026, 11, 16, 17, 30, tzinfo=LA), "set-return", "Coby White", A, B, "2026-11-16"),
            _h(datetime(2026, 11, 16, 18, 0, tzinfo=LA), "add", "Jayson Tatum", None,
               {"player_name": "Jayson Tatum", "out_weeks": [5]}, "2026-11-16")]
    now_file = {"last_updated": "2026-11-16", "players": [B, {"player_name": "Jayson Tatum", "out_weeks": [5]}]}
    rebuilt, undone = oh.as_of(now_file, rows, TIP)
    assert rebuilt["players"] == [A]                        # the 9 AM add stands; both later changes undone
    assert rebuilt["last_updated"] == "2026-11-16" and len(undone) == 2
    assert oh.as_of(now_file, rows, datetime(2026, 11, 17, 0, 5, tzinfo=LA))[0]["players"] == now_file["players"]
    with pytest.raises(oh.OverrideHistoryError, match="no history record"):
        oh.as_of({"players": [dict(B, notes="hand edit")]}, rows[:2], TIP)
    assert oh.changed_after([A, B], TIP) == [B]             # A has no updated_at: before the history


def test_the_closing_line_uses_the_rebuilt_overrides_and_raises_on_an_unrecorded_late_change(tmp_path,
                                                                                            monkeypatch):
    from modules import closing_line as cl
    base = _project(tmp_path, entries=[B])
    oh.append(base, _h(datetime(2026, 11, 16, 17, 30, tzinfo=LA), "set-return", "Coby White", A, B))
    data = SimpleNamespace(playerlist=pd.DataFrame({"player_name": ["Coby White"]}))
    got = cl.overrides_at(base, data, TIP)
    assert [{k: v for k, v in e.items() if k != "_override_spelling"} for e in got["players"]] == [A]
    (base / "output" / "override_history.jsonl").write_text("")              # the record is gone
    got = cl.overrides_at(base, data, TIP)
    assert oh.changed_after(got["players"], TIP) == [B]
    src = (ROOT / "modules" / "closing_line.py").read_text(encoding="utf-8")
    body = src.split("def price(")[1]
    assert "full.injury_overrides = at_tip" in body and "data.injury_overrides = at_tip" in body \
        and "pass_data.injury_overrides = at_tip" in body
    assert "oh.changed_after(ws.governing_overrides(" in body and "raise ClosingRefused(" in body


def test_the_real_closing_line_raises_on_a_governing_entry_changed_after_the_tip(monkeypatch):
    import test_closing_line as tcl
    tcl._real_or_skip()
    from modules import closing_line as cl, tag_records as tr
    from modules.data_loader import load_all_data
    data = load_all_data(ROOT, current_week=None)
    who = sorted(data.get_current_rosters()["Nick"])[0]
    late = {"player_name": who, "out_weeks": [3], "return_week": 4, "return_date": "2026-11-09",
            "updated_at": "2026-11-02T17:00:00-08:00"}
    real = cl.overrides_at
    monkeypatch.setattr(cl, "overrides_at", lambda base, d, m: dict(real(base, d, m),
                                                                   players=[late], last_updated="2026-11-02"))
    monkeypatch.setattr(tr, "for_close", lambda base, monday, first: dict(tr.latest(ROOT), league_day="2026-11-02"))
    monkeypatch.setattr(cl, "check_inputs", lambda *a, **k: {"overrides_last_updated": "x"})
    try:
        with pytest.raises(cl.ClosingRefused, match=f"{re.escape(who)} \\(updated_at 2026-11-02T17:00"):
            cl.price(ROOT, 3, now=datetime(2026, 11, 3, 9, 0, tzinfo=LA), sims=200, title_sims=200,
                     write=False)
    except Exception as e:                                   # noqa: BLE001
        if "ILSlotsError" in type(e).__name__:
            pytest.skip(f"the real IL file is not current ({e})")
        raise


# =============================================================================
# the workflows
# =============================================================================

def _wf(name):
    import yaml
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def test_the_push_trigger_never_loops():
    push = _wf("overrides-push.yml")
    on = push[True]
    assert on["push"]["paths"] == ["config/INJURY_OVERRIDES.json"] and on["push"]["branches"] == ["main"]
    cond = push["jobs"]["refresh"]["if"]
    for guard in ("github.event.head_commit.author.name != 'newsletter-bot'",
                  "github.event.head_commit.committer.name != 'newsletter-bot'",
                  "github.actor != 'github-actions[bot]'"):
        assert guard in cond
    assert push["jobs"]["refresh"]["with"] == {"mode": "refresh", "cause": "injury entries changed (desktop)"}
    # every commit any workflow makes is newsletter-bot's, with the workflow token
    run = (WF / "run.yml").read_text(encoding="utf-8")
    commits = [ln for ln in run.splitlines() if re.search(r"\bgit commit\b", ln)]
    assert len(commits) == 3                                # the entry, the state, the hub
    assert run.count('git config user.name "newsletter-bot"') == 3
    assert "secrets.GITHUB_TOKEN" not in run


def test_the_entry_workflow_calls_the_one_run_definition_and_only_run_yml_has_a_concurrency_group():
    entry = _wf("entry.yml")
    assert entry[True]["issues"]["types"] == ["opened", "edited"]
    assert entry["jobs"]["entry"]["uses"] == "./.github/workflows/run.yml"
    assert entry["jobs"]["entry"]["with"] == {"mode": "refresh", "entry": True}
    assert entry["permissions"] == {"contents": "write", "issues": "write"}
    for name in ("entry.yml", "overrides-push.yml", "nightly.yml", "pretip.yml"):
        assert "concurrency" not in (WF / name).read_text(encoding="utf-8")
    run = _wf("run.yml")
    assert run["jobs"]["run"]["concurrency"] == {"group": "newsletter-state", "cancel-in-progress": False}


def test_no_shell_line_interpolates_an_issue_title():
    for p in WF.glob("*.yml"):
        for ln in p.read_text(encoding="utf-8").splitlines():
            assert "event.issue.title" not in ln, (p.name, ln)


def test_a_refused_entry_runs_no_refresh_and_opens_no_failure_issue():
    run = (WF / "run.yml").read_text(encoding="utf-8")
    branch = run[run.index('if [ "$MODE" = refresh ]; then'):]
    branch = branch[:branch.index("set -- --refresh")]
    assert 'if [ "$ENTRY" = true ] && [ "$APPLIED" != true ]; then' in branch
    assert 'echo "ran=false" >> "$GITHUB_OUTPUT"' in branch and "exit 0" in branch
    jobs = _wf("run.yml")["jobs"]["run"]["steps"]
    close = next(s for s in jobs if s.get("name") == "Close the failure issue")
    assert "inputs.mode != 'refresh'" in close["if"]


# =============================================================================
# state files
# =============================================================================

@pytest.mark.parametrize("rel", ["output/override_history.jsonl", "output/night_paragraph.json"])
def test_the_new_files_are_league_state_and_ignored(rel):
    from modules import state_manifest
    assert state_manifest.load(ROOT).contains(rel)
    assert subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT).returncode == 0
