"""Task 49 (simple form) and D everywhere: claude/HANDOFF_TRADE_BLOCK_2026-11-11.md.

  - the grammar: every "Block:" form round-trips; malformed titles refuse and
    change nothing (state hash); a player on another roster refuses; the
    trade deadline refuses; a player moves between the lists;
  - the history: before/after equals the file's diff; one writer;
  - the upkeep: a dropped player is taken off; a trade cleans both teams;
    the deadline clears everything, once;
  - the facts-only refresh: no pricer called, the hub rebuilt, no win-% row,
    the cause recorded; its real steps and CLI validation run (not stubbed);
  - the view: order, chips, dates, the empty text; the page computes nothing;
    360 px; the plaintext scan on a fake-passphrase scratch build;
  - the drafting prompts carry the block with its dates;
  - D: his next game out in GL, the free agents and the grid; later games
    count; pricing never calls Availability.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import apply_entry as ae                                 # noqa: E402
from modules import hub_page, hub_publish                # noqa: E402
from modules import hub_state as hs                      # noqa: E402
from modules import move_ledger as ml                    # noqa: E402
from modules import nightly                              # noqa: E402
from modules import phone_entries as pe                  # noqa: E402
from modules import trade_block as tb                    # noqa: E402
from test_refresh_service import svc                     # noqa: E402,F401  (B3's scratch-week fixture)

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 11, 11, 14, 14, tzinfo=LA)          # Wed, week 4
MANAGERS = ["Nick", "Hayden", "Benton", "Garrett"]
ROSTERS = {"Nick": ["Coby White", "Derrick White", "Nikola Jokic"],
           "Hayden": ["Jayson Tatum", "Kyrie Irving"],
           "Benton": ["Victor Wembanyama", "Klay Thompson"],
           "Garrett": ["Zion Williamson", "Paolo Banchero", "Tyler Herro"]}
WF = ROOT / "deploy" / "state-repo" / ".github" / "workflows"


def test_the_fixture_managers_are_the_configs():
    from modules.data_loader import MANAGERS as CFG
    assert sorted(CFG) == sorted(MANAGERS)


# =============================================================================
# a scratch league
# =============================================================================

def _league(tmp_path, rosters=None):
    b = tmp_path / "lg"
    (b / "config").mkdir(parents=True)
    (b / "output").mkdir()
    (b / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": rosters or ROSTERS}))
    return b


def _hash(base: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(base.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(base).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _file(base):
    return json.loads((base / tb.PATH).read_text(encoding="utf-8"))


def _apply(base, title, issue=1, now=NOW, created=None):
    p = pe.parse_title(title, MANAGERS)
    return tb.apply(base, p, issue=issue, created_at=created or now, now=now)


@pytest.fixture(autouse=True)
def _no_snapshot(monkeypatch):
    monkeypatch.setattr(ae, "snapshot", lambda base, now: {"week": 4, "lines": None, "title_odds": None})


def _event(n, title, *, action="opened", created="2026-11-11T21:50:00Z"):
    return {"action": action, "sender": {"login": "nickrolen"},
            "issue": {"number": n, "title": title, "user": {"login": "nickrolen"}, "created_at": created,
                      "labels": [], "state": "open"}}


def _cmd_apply(base, tmp_path, event, open_issues=(), monkeypatch=None):
    out = tmp_path / "entry_out"
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(event))
    op = tmp_path / "open.json"
    op.write_text(json.dumps(list(open_issues)))
    gh = tmp_path / "gh_output.txt"
    gh.write_text("")
    if monkeypatch is not None:
        monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    a = SimpleNamespace(base_path=str(base), out_dir=str(out), event=str(ev), open_issues=str(op),
                        now=NOW.isoformat())
    assert ae.cmd_apply(a) == 0                          # a refusal is never a failed run
    acts = json.loads((out / "actions.json").read_text())
    outputs = dict(x.split("=", 1) for x in gh.read_text().splitlines() if "=" in x)
    return acts, out, outputs


# =============================================================================
# the grammar
# =============================================================================

CANONICAL = [
    "Block: Garrett untouchable Zion Williamson",
    "Block: Garrett untouchable Zion Williamson, Paolo Banchero",
    "Block: Garrett on the block Tyler Herro",
    "Block: Garrett on the block Tyler Herro, Banchero",
    "Block: Garrett remove Tyler Herro",
    "Block: Garrett remove Herro, Zion Williamson",
    "Block: Garrett buying",
    "Block: Garrett selling",
    "Block: Garrett neutral",
    "Block: Garrett clear",
]


@pytest.mark.parametrize("title", CANONICAL)
def test_every_block_form_round_trips(title):
    p = pe.parse_title(title, MANAGERS)
    assert p["kind"] == "block" and pe.format_title(p) == title


def test_keywords_and_managers_match_in_any_case_and_canonicalise():
    p = pe.parse_title("block:  garrett ON THE   Block herro ,zion", MANAGERS)
    assert (p["manager"], p["action"], p["players"]) == ("Garrett", "block", ["herro", "zion"])
    assert pe.format_title(p) == "Block: Garrett on the block herro, zion"
    assert pe.parse_title("BLOCK: nick Selling", MANAGERS)["mode"] == "selling"


def test_the_refusal_lists_the_block_forms():
    for f in ("Block: <Manager> untouchable", "Block: <Manager> on the block", "Block: <Manager> remove",
              "Block: <Manager> buying | selling | neutral", "Block: <Manager> clear"):
        assert f in pe.forms_text()


MALFORMED = [
    "Block: Bob selling",                       # not a manager
    "Block: Garrett",                           # nothing to do
    "Block: Garrett sell",                      # not a mode
    "Block: Garrett untouchable",               # no player
    "Block: Garrett on the block",              # no player
    "Block: Garrett remove",                    # no player
    "Block: Garrett untouchable Zion,, Herro",  # an empty name
    "Block: Garrett on the block Herro, herro",  # twice
    "Block: Garrett selling now",               # trailing words
    "Block: Garrett clear Herro",               # clear takes nothing
    "Block Garrett selling",                    # no colon
    "Block: Garrett untouchable: Zion",         # stray colon makes it no form
]


@pytest.mark.parametrize("title", MALFORMED)
def test_a_malformed_block_title_is_refused_and_changes_nothing(title, tmp_path, monkeypatch):
    base = _league(tmp_path)
    before = _hash(base)
    acts, out, outputs = _cmd_apply(base, tmp_path, _event(5, title), monkeypatch=monkeypatch)
    assert acts[0]["verdict"] == "refused" and acts[0]["label"] == "entry-refused"
    text = (out / "5.md").read_text()
    assert text.startswith("**Refused** (nothing was changed)") and "Block: <Manager> clear" in text
    assert outputs["applied"] == "false" and outputs["facts_only"] == "false"
    assert _hash(base) == before


def test_a_player_on_another_roster_is_refused_and_nothing_changes(tmp_path):
    base = _league(tmp_path)
    before = _hash(base)
    with pytest.raises(tb.BlockRefused, match="Kyrie Irving is on Hayden's roster, not Garrett's"):
        _apply(base, "Block: Garrett on the block Kyrie Irving")
    # all or nothing: one good player and one on another roster
    with pytest.raises(tb.BlockRefused, match="on Hayden's roster"):
        _apply(base, "Block: Garrett on the block Tyler Herro, Tatum")
    with pytest.raises(tb.BlockRefused, match="matches no player"):
        _apply(base, "Block: Garrett untouchable LeBron James")
    assert _hash(base) == before


def test_an_ambiguous_name_lists_the_candidates(tmp_path):
    base = _league(tmp_path)
    with pytest.raises(tb.BlockRefused, match="could be Coby White, Derrick White"):
        _apply(base, "Block: Nick on the block White")
    assert _apply(base, "Block: Nick on the block Coby White")["players"] == ["Coby White"]


def test_after_the_trade_deadline_every_block_entry_is_refused(tmp_path):
    base = _league(tmp_path)
    before = _hash(base)
    dl = ml.trade_deadline()
    on_day = datetime(dl.year, dl.month, dl.day, 23, 0, tzinfo=LA)
    after = datetime(dl.year, dl.month, dl.day + 1, 9, 0, tzinfo=LA)
    for t in ("Block: Garrett selling", "Block: Garrett untouchable Zion Williamson", "Block: Garrett clear"):
        with pytest.raises(tb.BlockRefused, match="the trade deadline has passed"):
            _apply(base, t, now=after)
    assert _hash(base) == before
    assert _apply(base, "Block: Garrett selling", now=on_day)["after"]["mode"] == "selling"   # the day itself


def test_a_block_player_marked_untouchable_moves_and_the_comment_says_so(tmp_path, monkeypatch):
    base = _league(tmp_path)
    _apply(base, "Block: Garrett on the block Tyler Herro", issue=1)
    acts, out, _ = _cmd_apply(base, tmp_path, _event(2, "Block: Garrett untouchable Herro"),
                              monkeypatch=monkeypatch)
    assert acts[0]["verdict"] == "applied"
    t = _file(base)["teams"]["Garrett"]
    assert t["block"] == [] and t["untouchable"] == [{"player": "Tyler Herro", "set": "2026-11-11"}]
    assert "Tyler Herro moved from On the block to Untouchable." in (out / "2.md").read_text()
    assert tb.read_history(base)[-1]["moved"] == ["Tyler Herro"]


def test_nothing_to_change_refuses(tmp_path):
    base = _league(tmp_path)
    _apply(base, "Block: Garrett untouchable Zion Williamson")
    _apply(base, "Block: Garrett selling", issue=2)
    before = _hash(base)
    with pytest.raises(tb.BlockRefused, match="already untouchable"):
        _apply(base, "Block: Garrett untouchable Williamson", issue=3)
    with pytest.raises(tb.BlockRefused, match="already selling"):
        _apply(base, "Block: Garrett selling", issue=3)
    with pytest.raises(tb.BlockRefused, match="on Garrett's lists matches no player"):
        _apply(base, "Block: Garrett remove Herro", issue=3)
    with pytest.raises(tb.BlockRefused, match="nothing to clear"):
        _apply(base, "Block: Nick clear", issue=3)
    with pytest.raises(tb.BlockRefused, match="nothing to remove"):
        _apply(base, "Block: Nick remove Coby White", issue=3)
    assert _hash(base) == before


def test_each_item_carries_the_day_the_issue_was_made(tmp_path):
    base = _league(tmp_path)
    made = datetime(2026, 11, 10, 23, 50, tzinfo=LA)     # applied after midnight by the catch-up
    ch = _apply(base, "Block: Garrett untouchable Zion Williamson", created=made)
    assert ch["after"]["untouchable"] == [{"player": "Zion Williamson", "set": "2026-11-10"}]


# =============================================================================
# apply_entry: the path, the comment, already applied, facts_only
# =============================================================================

def test_a_block_entry_is_applied_with_its_before_and_after_and_facts_only(tmp_path, monkeypatch):
    base = _league(tmp_path)
    acts, out, outputs = _cmd_apply(base, tmp_path, _event(7, "Block: Garrett selling"), monkeypatch=monkeypatch)
    assert acts[0]["verdict"] == "applied" and acts[0]["close"] and acts[0]["facts_only"]
    assert outputs == {"applied": "true", "cause": "trade block: Garrett selling", "facts_only": "true"}
    text = (out / "7.md").read_text()
    assert text.startswith("**Applied:** trade block, Garrett: selling (`config/TRADE_BLOCK.json`).")
    blocks = re.findall(r"```json\n(.*?)\n```", text, flags=re.S)
    assert [json.loads(b) for b in blocks] == [tb.empty_team(), _file(base)["teams"]["Garrett"]]
    assert "No prices change." in text
    assert tb.read_history(base)[0]["issue"] == 7 and tb.read_history(base)[0]["by"] == "issue #7"


def test_an_applied_block_issue_edited_later_is_already_applied(tmp_path, monkeypatch):
    base = _league(tmp_path)
    _cmd_apply(base, tmp_path, _event(8, "Block: Garrett buying"), monkeypatch=monkeypatch)
    before = _hash(base)
    acts, out, _ = _cmd_apply(base, tmp_path, _event(8, "Block: Garrett selling", action="edited"),
                              monkeypatch=monkeypatch)
    assert acts[0]["verdict"] == "already"
    assert (out / "8.md").read_text().startswith("Already applied as trade block mode for Garrett")
    assert _hash(base) == before


def test_a_block_entry_and_an_injury_entry_together_are_not_facts_only(tmp_path, monkeypatch):
    base = _league(tmp_path)
    calls = []
    monkeypatch.setattr(ae, "apply_one", lambda b, title, n, c, now: (
        calls.append(n) or {"verdict": "applied", "cause": title, "comment": "x",
                            "facts_only": title.startswith("Block")}))
    open_ = [{"number": 3, "title": "Injury remove: Coby White", "createdAt": "2026-11-11T21:00:00Z",
              "author": {"login": "nickrolen"}, "labels": []}]
    acts, _, outputs = _cmd_apply(base, tmp_path, _event(4, "Block: Garrett selling"), open_,
                                  monkeypatch=monkeypatch)
    assert calls == [3, 4] and outputs["facts_only"] == "false" and outputs["applied"] == "true"


# =============================================================================
# the file and its history
# =============================================================================

def _apply_diff(before: dict, row: dict) -> dict:
    out = json.loads(json.dumps(before))
    for m, t in row["after"].items():
        assert out["teams"][m] == row["before"][m]
        out["teams"][m] = t
    return out


def test_every_history_row_is_the_files_diff(tmp_path):
    base = _league(tmp_path)
    titles = ["Block: Garrett untouchable Zion Williamson, Banchero", "Block: Garrett on the block Herro",
              "Block: Garrett untouchable Herro", "Block: Garrett selling", "Block: Garrett remove Williamson",
              "Block: Nick buying", "Block: Garrett clear", "Block: Garrett neutral"]
    prev = tb.empty()
    for i, t in enumerate(titles, start=1):
        try:
            _apply(base, t, issue=i)
        except tb.BlockRefused:
            assert t == "Block: Garrett neutral"        # clear left him neutral already
            continue
        now_ = _file(base)
        row = tb.read_history(base)[-1]
        assert _apply_diff(prev, row) == now_
        assert set(row["after"]) == {m for m in MANAGERS if now_["teams"][m] != prev["teams"][m]}
        prev = now_
    assert [r["action"] for r in tb.read_history(base)] == ["untouchable", "block", "untouchable", "mode",
                                                            "remove", "mode", "clear"]
    assert _file(base)["teams"]["Garrett"] == {"mode": "neutral", "mode_set": "2026-11-11",
                                               "untouchable": [], "block": []}


def test_only_write_change_writes_the_file_and_its_history():
    srcs = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
            for d in ("modules", "scripts") for p in (ROOT / d).glob("*.py")}
    write = re.compile(r"(atomic_write_json|write_text|write_bytes|append_rows|open)\([^)]*"
                       r"(TRADE_BLOCK|trade_block_history|tb\.PATH|tb\.HISTORY|tb\.path_for|"
                       r"tb\.history_path|trade_block\.)")
    assert {n for n, s in srcs.items() if write.search(s)} == set()
    for n, s in srcs.items():
        if n != "modules/trade_block.py":
            assert "trade_block_history" not in s, n
    body = srcs["modules/trade_block.py"]
    assert body.count("atomic_write_json(") == 1 and body.count("append_rows(") == 1
    wc = body.split("def write_change")[1].split("\ndef ")[0]
    assert "atomic_write_json(path_for(base), after" in wc and "append_rows(history_path(base), [row])" in wc
    assert wc.index("atomic_write_json(") < wc.index("append_rows(")         # the file, then its row


def test_no_file_is_the_empty_block_but_a_lost_file_with_a_history_raises(tmp_path):
    base = _league(tmp_path)
    assert tb.load(base) == tb.empty() and tb.is_empty(tb.load(base))
    _apply(base, "Block: Garrett selling")
    (base / tb.PATH).rename(base / "config" / "moved_away.json")
    with pytest.raises(tb.TradeBlockError, match="the file was lost"):
        tb.load(base)


def test_a_malformed_file_raises(tmp_path):
    base = _league(tmp_path)
    good = tb.empty()
    cases = [dict(good, season="2025-26"),
             dict(good, teams={m: tb.empty_team() for m in MANAGERS[:3]}),
             dict(good, teams=dict(good["teams"], Nick=dict(tb.empty_team(), mode="hold"))),
             dict(good, teams=dict(good["teams"], Nick=dict(tb.empty_team(), mode="selling"))),
             dict(good, teams=dict(good["teams"], Nick=dict(
                 tb.empty_team(), untouchable=[{"player": "Coby White", "set": "2026-11-11"}],
                 block=[{"player": "Coby White", "set": "2026-11-11"}])))]
    for c in cases:
        (base / tb.PATH).write_text(json.dumps(c))
        with pytest.raises(tb.TradeBlockError):
            tb.load(base)


def test_a_change_that_changes_nothing_is_not_written(tmp_path):
    base = _league(tmp_path)
    with pytest.raises(tb.TradeBlockError, match="changes nothing"):
        tb.write_change(base, tb.empty(), tb.empty(), action="clear", by="t", now=NOW)
    assert not (base / tb.PATH).exists() and not (base / tb.HISTORY).exists()


# =============================================================================
# the nightly upkeep
# =============================================================================

def test_a_dropped_player_is_taken_off_by_the_nightly_run(tmp_path):
    base = _league(tmp_path)
    _apply(base, "Block: Garrett on the block Tyler Herro, Banchero")
    rosters = dict(ROSTERS, Garrett=["Zion Williamson", "Paolo Banchero"])       # Herro dropped
    (base / "config" / "ROSTERS.json").write_text(json.dumps({"rosters": rosters}))
    run = nightly.Run(base, "nightly", now=NOW, echo=lambda *a: None)
    detail = run.step_trade_block()
    assert detail == "Tyler Herro taken off Garrett's block (no longer on his roster)"
    assert run.ctx["trade_block"]["removed"] == [{"manager": "Garrett", "player": "Tyler Herro", "list": "block"}]
    assert [e["player"] for e in _file(base)["teams"]["Garrett"]["block"]] == ["Paolo Banchero"]
    row = tb.read_history(base)[-1]
    assert (row["action"], row["by"], row["issue"]) == ("roster", "nightly", None)
    assert run.step_trade_block() == "nothing to change" and len(tb.read_history(base)) == 2


def test_a_trade_between_two_teams_cleans_both_blocks(tmp_path):
    base = _league(tmp_path)
    _apply(base, "Block: Garrett on the block Tyler Herro", issue=1)
    _apply(base, "Block: Hayden untouchable Kyrie Irving", issue=2)
    rosters = dict(ROSTERS, Garrett=["Zion Williamson", "Paolo Banchero", "Kyrie Irving"],
                   Hayden=["Jayson Tatum", "Tyler Herro"])
    out = tb.upkeep(base, rosters, NOW.date(), NOW)
    assert sorted((r["manager"], r["player"]) for r in out["removed"]) == [("Garrett", "Tyler Herro"),
                                                                          ("Hayden", "Kyrie Irving")]
    assert sorted(out["row"]["after"]) == ["Garrett", "Hayden"]
    assert tb.is_empty(_file(base))
    assert _apply_diff(dict(tb.empty(), teams={**tb.empty()["teams"], **out["row"]["before"]}),
                       out["row"]) == _file(base)


def test_the_day_after_the_deadline_clears_everything_once(tmp_path):
    base = _league(tmp_path)
    _apply(base, "Block: Garrett selling", issue=1)
    _apply(base, "Block: Nick untouchable Jokic", issue=2)
    dl = ml.trade_deadline()
    on_day = datetime(dl.year, dl.month, dl.day, 0, 5, tzinfo=LA)
    assert tb.upkeep(base, ROSTERS, on_day.date(), on_day)["cleared"] is False   # the day itself: kept
    nxt = datetime(dl.year, dl.month, dl.day + 1, 0, 5, tzinfo=LA)
    out = tb.upkeep(base, ROSTERS, nxt.date(), nxt)
    assert out["cleared"] and tb.is_empty(_file(base))
    assert all(t == tb.empty_team() for t in _file(base)["teams"].values())
    rows = tb.read_history(base)
    assert rows[-1]["action"] == "deadline" and sorted(rows[-1]["after"]) == ["Garrett", "Nick"]
    again = tb.upkeep(base, ROSTERS, nxt.date().replace(day=nxt.day + 1), nxt)
    assert again["cleared"] is False and len(tb.read_history(base)) == len(rows)    # once


def test_no_file_and_nothing_to_do_creates_no_file(tmp_path):
    base = _league(tmp_path)
    assert tb.upkeep(base, ROSTERS, NOW.date(), NOW)["row"] is None
    assert not (base / tb.PATH).exists()


def test_the_upkeep_runs_in_the_nightly_after_the_sync_and_never_prices(tmp_path, monkeypatch):
    s = nightly.STEPS["nightly"]
    assert s.index("sync") + 1 == s.index("trade_block") < s.index("line")
    assert [m for m, st in nightly.STEPS.items() if "trade_block" in st] == ["nightly"]
    import refresh_service as rs
    from modules import title_odds_run as tor
    monkeypatch.setattr(rs, "run", lambda *a, **k: pytest.fail("the upkeep priced a line"))
    monkeypatch.setattr(tor, "price", lambda *a, **k: pytest.fail("the upkeep priced title odds"))
    base = _league(tmp_path)
    _apply(base, "Block: Garrett on the block Tyler Herro")
    run = nightly.Run(base, "nightly", now=NOW, echo=lambda *a: None)
    steps = {n: (lambda n=n: n) for n in nightly.STEPS["nightly"] if n != "trade_block"}
    row = run.execute(steps)
    assert row["outcome"] == "ok" and row["trade_block"] == {"cleared": False, "removed": []}


# =============================================================================
# the facts-only refresh
# =============================================================================

def test_the_facts_only_steps_are_the_refreshs_without_the_pricers():
    full, facts = nightly.STEPS["refresh"], nightly.STEPS["refresh_facts"]
    assert "line" not in facts and "title_odds" not in facts
    assert [s for s in facts if s != "line_engine"] == [s for s in full if s not in ("line", "title_odds")]
    assert facts.index("sync") < facts.index("line_engine") < facts.index("hub")


def test_a_facts_only_refresh_calls_neither_pricer_and_rebuilds_the_hub(tmp_path, monkeypatch):
    import refresh_service as rs
    from modules import title_odds_run as tor, winprob_history as wh
    monkeypatch.setattr(rs, "run", lambda *a, **k: pytest.fail("a facts-only refresh priced the line"))
    monkeypatch.setattr(tor, "price", lambda *a, **k: pytest.fail("a facts-only refresh priced title odds"))
    monkeypatch.setattr(wh, "append", lambda *a, **k: pytest.fail("a facts-only refresh wrote a win-% row"))
    run = nightly.Run(tmp_path, "refresh", now=NOW, cause="trade block: Garrett selling", facts_only=True,
                      echo=lambda *a: None)
    calls = []
    steps = {n: (lambda n=n: calls.append(n) or f"{n} done") for n in nightly.STEPS["refresh_facts"]}
    row = run.execute(steps)
    assert calls == list(nightly.STEPS["refresh_facts"]) and "hub" in calls
    assert row["outcome"] == "ok" and row["exit"] == 0 and row["mode"] == "refresh"
    assert row["facts_only"] is True and row["cause"] == "trade block: Garrett selling"
    assert [s["step"] for s in row["steps"]] == list(nightly.STEPS["refresh_facts"])
    assert not (tmp_path / "output" / "title_odds_history.jsonl").exists()
    # the hub's lock note counts only locked runs as changes waiting: never this one
    assert row["outcome"] != "locked"


def test_the_real_cli_and_line_engine_step_of_a_facts_only_refresh(tmp_path, monkeypatch):
    """The 11-11 lesson: the new run path's real validation, not a stub -- the
    CLI's flags, the Run, the line_engine step on a real line file and the
    real engine check, and the run row the effect comment reads."""
    from modules import calibration_log as cal
    with pytest.raises(SystemExit):
        nightly.main(["--facts-only", "--cause", "x"])                      # needs --refresh
    with pytest.raises(ValueError, match="refresh's switch"):
        nightly.Run(tmp_path, "nightly", now=NOW, facts_only=True)
    (tmp_path / "output").mkdir()
    line = {"week": 4, "engine": {"commit": "abc1234", "dirty": False}, "generated_at": NOW.isoformat(),
            "lines": []}
    (tmp_path / "output" / "live_lines_week4.json").write_text(json.dumps(line))
    engine = {"commit": "abc1234", "dirty": False}
    monkeypatch.setattr(cal, "engine_version", lambda base=".": dict(engine))
    for name in nightly.STEPS["refresh_facts"]:
        if name == "sync":
            monkeypatch.setattr(nightly.Run, "step_sync", lambda self: setattr(self, "week", 4) or "synced")
        elif name != "line_engine":
            monkeypatch.setattr(nightly.Run, f"step_{name}", lambda self, n=name: f"{n} done")
    rc = nightly.main(["--refresh", "--facts-only", "--cause", "trade block: Garrett selling",
                       "--base-path", str(tmp_path)])
    rows = [json.loads(x) for x in (tmp_path / nightly.RUNS_FILE).read_text().splitlines()]
    assert rc == 0 and rows[-1]["outcome"] == "ok" and rows[-1]["facts_only"] is True
    assert {s["step"]: s["detail"] for s in rows[-1]["steps"]}["line_engine"] == "week 4's line is engine abc1234's"
    assert ae.effect_text({}, {"week": 4}, rows[-1]) == "No prices change; the hub's trade block is updated."
    # just after set-engine (11-11 review): the line on disk is the previous CLEAN
    # engine's -> the run goes on and the hub shows it with a note (no deferral)
    engine["commit"] = "def5678"
    rc = nightly.main(["--refresh", "--facts-only", "--cause", "trade block: Garrett buying",
                       "--base-path", str(tmp_path)])
    rows = [json.loads(x) for x in (tmp_path / nightly.RUNS_FILE).read_text().splitlines()]
    assert rc == 0 and rows[-1]["outcome"] == "ok"
    assert "previous engine's (abc1234)" in {s["step"]: s["detail"] for s in rows[-1]["steps"]}["line_engine"]
    # a DIRTY or unknown previous engine is still never shown -> deferred, nothing built
    line["engine"] = {"commit": "abc1234", "dirty": True}
    (tmp_path / "output" / "live_lines_week4.json").write_text(json.dumps(line))
    rc = nightly.main(["--refresh", "--facts-only", "--cause", "trade block: Garrett neutral",
                       "--base-path", str(tmp_path)])
    rows = [json.loads(x) for x in (tmp_path / nightly.RUNS_FILE).read_text().splitlines()]
    assert rc == 0 and rows[-1]["outcome"] == "deferred"
    assert [s["step"] for s in rows[-1]["steps"]][-1] == "line_engine"
    assert ae.effect_text({}, {"week": 4}, rows[-1]).startswith(
        "No prices change. The hub's trade block updates with the next run that rebuilds the hub (week 4's "
        "line on disk was priced by engine abc1234")


def test_the_effect_comment_of_a_facts_only_refresh():
    assert ae.effect_text({}, {"week": 4}, {"facts_only": True, "outcome": "ok"}) == \
        "No prices change; the hub's trade block is updated."
    t = ae.effect_text({}, {"week": 4}, {"facts_only": True, "outcome": "refused", "error": "boom"})
    assert t.startswith("No prices change. The hub's refresh failed (boom)")
    # a priced refresh is unchanged by the switch
    assert ae.effect_text({}, {"week": 4}, {"outcome": "locked"}).startswith("Priced after tonight's games")


def test_the_workflow_passes_facts_only_only_for_an_entry_that_is_all_block():
    import yaml
    run = yaml.safe_load((WF / "run.yml").read_text(encoding="utf-8"))
    step = next(s for s in run["jobs"]["run"]["steps"] if s.get("id") == "run")
    assert step["env"]["FACTS_ONLY"] == "${{ steps.entry.outputs.facts_only }}"
    body = step["run"]
    assert 'if [ "$ENTRY" = true ] && [ "$FACTS_ONLY" = true ]; then' in body
    assert 'set -- --refresh --facts-only --cause "$c"' in body and 'set -- --refresh --cause "$c"' in body
    assert body.count("--facts-only") == 1


# =============================================================================
# the hub: the view
# =============================================================================

def _power(order):
    return [{"rank": str(i), "manager": m, "team": f"Team {m}"} for i, m in enumerate(order, start=1)]


def _roster_blocks():
    return {m: {"players": [{"name": n, "pos": "PG", "nba": "AAA"} for n in v]} for m, v in ROSTERS.items()}


def test_the_view_follows_power_rankings_with_chips_dates_and_the_empty_text(tmp_path):
    base = _league(tmp_path)
    _apply(base, "Block: Garrett selling", issue=1)
    _apply(base, "Block: Garrett untouchable Zion Williamson", issue=2,
           created=datetime(2026, 11, 9, 10, 0, tzinfo=LA))
    _apply(base, "Block: Garrett on the block Herro", issue=3)
    _apply(base, "Block: Hayden buying", issue=4)
    v = hs.trade_block_view(tb.current(base, ROSTERS), _power(["Hayden", "Garrett", "Nick", "Benton"]),
                            _roster_blocks(), date(2027, 3, 4), NOW.date())
    assert [c["manager"] for c in v["cards"]] == ["Hayden", "Garrett", "Nick", "Benton"]
    g = v["cards"][1]
    assert g["mode"] == {"text": "Selling", "kind": "sell"} and g["mode_since"] == "since 11-11"
    assert [(lst["label"], [r["name"] for r in lst["rows"]], [r["since"] for r in lst["rows"]])
            for lst in g["lists"]] == [("Untouchable", ["Zion Williamson"], ["since 11-09"]),
                                       ("On the block", ["Tyler Herro"], ["since 11-11"])]
    assert g["lists"][0]["rows"][0] == {"name": "Zion Williamson", "pos": "PG", "nba": "AAA", "since": "since 11-09"}
    h = v["cards"][0]
    assert h["mode"] == {"text": "Buying", "kind": "buy"} and h["lists"] == [] and h["empty"] == "Nothing listed."
    n = v["cards"][2]
    assert n["mode"] == {"text": "Neutral", "kind": "neu"} and n["mode_since"] == "" and n["empty"] == "Nothing listed."
    assert v["foot"] == "Text Nick to change your block. Clears at the trade deadline (03-04)."
    after = hs.trade_block_view(tb.current(base, ROSTERS), _power(MANAGERS), _roster_blocks(),
                                date(2027, 3, 4), date(2027, 3, 5))
    assert after["foot"].startswith("The trade deadline (03-04) has passed")
    assert all(isinstance(val, str) for c in v["cards"] for val in (c["manager"], c["team"], c["empty"],
                                                                     c["mode_since"], *c["mode"].values()))


def test_a_listed_player_no_longer_on_the_roster_is_not_shown_until_the_nightly_takes_him_off(tmp_path):
    base = _league(tmp_path)
    _apply(base, "Block: Garrett on the block Tyler Herro, Banchero")
    rosters = dict(ROSTERS, Garrett=["Zion Williamson", "Paolo Banchero"])
    cur = tb.current(base, rosters)
    assert [e["player"] for e in cur["teams"]["Garrett"]["block"]] == ["Paolo Banchero"]
    assert len(_file(base)["teams"]["Garrett"]["block"]) == 2                  # the file is the nightly's


def test_the_hub_payload_builds_the_view_from_the_one_read():
    src = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    assert "trade_block_view(tb.current(base, rosters), power[\"rows\"], roster_blocks," in src
    assert '"trade_block": tblock,' in src


def _page(**over):
    from test_hub import GEN, sample_payload
    p = sample_payload(**over)
    return p, hub_page.render(p, now=GEN)


def test_the_power_card_links_to_the_view_and_the_view_links_back():
    p, page = _page()
    card = page[page.index("<h2>Power rankings</h2>"):page.index("<h2>Games grid</h2>")]
    link = card.index('data-open="v-block"')
    assert link > card.index('data-open="v-chart" style')                     # the bottom of the card
    assert card.index("Trade block &rarr;</button></div>") > link             # inside it, last
    main = page[page.index('id="v-main"'):page.index('id="v-roster-')]
    assert main.count("v-block") == 1                                       # nothing else on the main page
    view = page[page.index('id="v-block"'):]
    view = view[:view.index('<div class="view"', 10)]
    assert '<a href="#" class="back" data-open="v-main">&larr; Power rankings</a>' in view
    assert [m for m in re.findall(r'data-manager="([^"]+)"', view)] == ["Mgr One", "Mgr Two"]
    assert '<span class="chip sell">Selling</span><span class="s">since 11-01</span>' in view
    assert '<span class="chip neu">Neutral</span></span>' in view
    assert '<div class="tb-k">Untouchable</div>' in view and "Zed Alpha" in view and "since 11-01" in view
    assert '<div class="empty">Nothing listed.</div>' in view
    assert "Text Nick to change your block. Clears at the trade deadline (03-04)." in view


def test_every_number_on_the_view_is_a_payload_string():
    from test_hub import GEN, payload_strings, visible_text
    p, page = _page()
    view = page[page.index('id="v-block"'):]
    view = view[:view.index('<div class="view"', 10)]
    known = " ".join(payload_strings(p["trade_block"]))
    for n in re.findall(r"\d+(?:[.,-]\d+)*", visible_text(view)):
        assert n in known, n


def test_the_mode_chips_are_readable():
    from test_hub_polish import contrast
    for k, (bg, fg) in hub_page.MODE_CHIP_COLOURS.items():
        assert contrast(fg, bg) >= 4.5, k
        assert f".chip.{k}{{background:{bg};color:{fg}}}" in hub_page.CSS
    assert set(hs.MODE_CHIP_KIND.values()) == set(hub_page.MODE_CHIP_COLOURS)


def test_the_view_fits_a_360px_phone():
    """No fixed widths: the name column shrinks and wraps (min-width 0,
    overflow-wrap), the since text keeps its width. At 360 px, less the
    section (16 a side) and the card (14 a side), 11 px "since MM-DD" (about
    11 chars x 7 px) and the 8 px gap leave >= 150 px for a name."""
    css = hub_page.CSS
    rules = {m.group(1): m.group(2) for m in re.finditer(r"(\.tb-[^{]+)\{([^}]*)\}", css)}
    for sel, body in rules.items():
        assert not re.search(r"(?<![-\w])(min-)?width:\d+px", body), sel
    assert "min-width:0" in rules[".tb-r .pn"] and "overflow-wrap:anywhere" in rules[".tb-r .pn .n"]
    assert "min-width:0" in rules[".tb-t"] and "overflow-wrap:anywhere" in rules[".tb-t .n"]
    pad = int(re.search(r"padding:\d+px (\d+)px", rules[".tb-l"]).group(1))
    gap = int(re.search(r"gap:(\d+)px", rules[".tb-r"]).group(1))
    assert 360 - 2 * 16 - 2 * pad - gap - 11 * 7 >= 150


def test_the_publish_directory_carries_no_block_name_in_plaintext(tmp_path):
    """The plaintext scan on a fake-passphrase scratch build: the trade block's
    names are on the page (the negative control) and nowhere in the publish
    directory."""
    from test_hub import GEN, PASS, TERMS, publish_world
    p = publish_world(tmp_path)
    p["trade_block"]["cards"][0]["lists"][0]["rows"].append(
        {"name": "Block Only Guy", "pos": "C", "nba": "ZZZ", "since": "since 11-11"})
    terms = TERMS + ["Block Only Guy"]
    assert hub_publish.hits(hub_page.render(p, now=GEN, mode="publish").encode(), terms)
    hub_publish.build(tmp_path, p, PASS, terms=terms, iterations=1000, now=GEN)
    assert hub_publish.scan_dir(hub_publish.publish_dir(tmp_path), terms)["hits"] == {}


# =============================================================================
# the drafting prompts
# =============================================================================

def test_the_drafting_prompts_carry_the_block_with_its_dates(tmp_path):
    from test_prepare_prompts import MANAGERS as PM, build, league, part
    b = league(tmp_path)
    block = {"schema": 1, "season": "2026-27", "teams": {m: tb.empty_team() for m in PM}}
    block["teams"]["Bob"] = {"mode": "selling", "mode_set": "2026-11-03",
                             "untouchable": [{"player": "Bob Player1", "set": "2026-11-02"}],
                             "block": [{"player": "Bob Player3", "set": "2026-11-04"},
                                       {"player": "Gone Player", "set": "2026-11-04"}]}
    (b / "config" / "TRADE_BLOCK.json").write_text(json.dumps(block))
    out = build(b)
    p3 = part(out, 3)
    s10 = p3[p3.index("### Section 10: Rumor Mill"):]
    assert ("- **Bob** (Team B): selling since 11-03; Untouchable: Bob Player1 (since 11-02); "
            "On the block: Bob Player3 (since 11-04).") in s10
    assert "- **Ann** (Team A): neutral; nothing listed." in s10
    assert "Gone Player" not in out                                    # not on his roster: the hub's read
    assert "- **Trade block:** config\\TRADE_BLOCK.json, 2 player(s) listed, 1 team(s) buying or selling" in out
    assert s10.index("**The trade block**") < s10.index("Use the rumor_mill data")


def test_with_nothing_entered_the_prompts_say_so(tmp_path):
    from test_prepare_prompts import MANAGERS as PM, build, league, part
    out = build(league(tmp_path))
    assert all(f"- **{m}** (" in part(out, 3) and "neutral; nothing listed." in part(out, 3) for m in PM)
    assert "config\\TRADE_BLOCK.json does not exist yet: nothing entered this season" in out


# =============================================================================
# D: out for his next game everywhere the hub counts games (Nick, 11-11)
# =============================================================================

MON, TUE, WED = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)


def _av(tags, nba_outs=None):
    names = ["P0", "P1", "P2"]
    info = {n: {"nba_team": f"T{i}", "positions": {"PG"}, "proj_fppg": 40.0} for i, n in enumerate(names)}
    team_dates = {f"T{i}": {MON, TUE, WED} for i in range(3)}
    return hs.Availability({"M": names}, {"M": []}, tags, {"players": []}, 5, info, team_dates,
                           {5: (MON, date(2026, 11, 22))}, MON, nba_outs)


def test_d_is_out_for_his_next_game_in_games_left_and_his_later_games_count():
    av = _av({"P1": "D"})
    assert av.playable("P1", [MON, TUE, WED]) == [TUE, WED]               # the rosters' GL
    assert av.playable("P0", [MON, TUE, WED]) == [MON, TUE, WED]
    assert av.out("P1", MON) and not av.out("P1", TUE)
    assert av.players("M", MON) == ["P0", "P2"] and av.players("M", TUE) == ["P0", "P1", "P2"]


def test_d_is_out_for_his_next_game_in_the_free_agents_columns_and_points():
    av = _av({})
    fa = av.for_free_agents(["P1", "P2"], {"P1": "D", "P2": "HEALTHY"})
    rows = hs.rank_free_agents([{"player_name": "P1", "projectedFPPG": 30.0},
                                {"player_name": "P2", "projectedFPPG": 30.0}], fa, [MON, TUE], [WED])
    by = {r["name"]: r for r in rows}
    assert (by["P1"]["g1"], by["P1"]["g2"], by["P1"]["pts"]) == ("1", "1", "60.0")
    assert (by["P2"]["g1"], by["P2"]["g2"], by["P2"]["pts"]) == ("2", "1", "90.0")
    assert by["P1"]["tags"] == [{"text": "D", "kind": "q"}]


def test_the_grid_is_unchanged_and_agrees_with_the_counts():
    av = _av({"P1": "D", "P2": "Q"})
    assert [av.grid_status("P1", d) for d in (MON, TUE, WED)] == ["out", "plays", "plays"]
    assert [av.grid_status("P2", d) for d in (MON, TUE, WED)] == ["maybe", "plays", "plays"]
    for d in (MON, TUE, WED):                       # one rule: the grid's "out" is out()
        assert (av.grid_status("P1", d) == "out") == av.out("P1", d)
    # an NBA-report Out on a D player's next game keeps its mark, as since 3b
    av = _av({"P1": "D"}, nba_outs={"P1": MON.isoformat()})
    assert av.grid_status("P1", MON) == "nba" and av.grid_players("M", MON)[2] == ["P1"]


def test_the_d_rule_has_one_home():
    src = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    cls = src[src.index("class Availability"):src.index("\nPTS_LABEL")]
    assert cls.count('== "D"') == 1
    assert '== "D"' in cls[cls.index("    def out(self"):cls.index("    def out_firm(self")]
    assert 'norm in ("D", "Q")' not in cls


def _refuse_availability(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a pricing path called hub_state.Availability")
    monkeypatch.setattr(hs.Availability, "__init__", boom)
    for name in ("out", "out_firm", "plays", "playable", "players", "grid_status"):
        monkeypatch.setattr(hs.Availability, name, boom)


def test_pricing_a_line_never_calls_availability(svc, monkeypatch):
    from test_live_lines import MON as LMON
    _refuse_availability(monkeypatch)
    out = svc(LMON)
    assert out["outcome"] == "priced", out


def test_the_pricing_modules_never_name_availability():
    for rel in ("modules/simulator_betting.py", "modules/season_sim.py", "modules/simulator_title_odds.py",
                "modules/title_odds_run.py", "modules/closing_line.py", "modules/week_state.py",
                "scripts/refresh_lines.py", "scripts/refresh_service.py"):
        s = (ROOT / rel).read_text(encoding="utf-8")
        assert "Availability" not in s and "hub_state" not in s, rel


from league_state import needs_state                       # noqa: E402


@needs_state("data/LINEUPS.xlsx", "data/PLAYERLOG.xlsx", "data/PLAYERLIST.xlsx", "config/RECORDS.json",
             why="the title odds' season pass on the real season")
def test_a_season_pass_never_calls_availability(monkeypatch):
    from modules import season_sim as ss
    from modules.data_loader import load_all_data
    from modules.fetch_injury_statuses import Tags
    _refuse_availability(monkeypatch)
    sp = ss.run_season(load_all_data(ROOT, current_week=None), 200, 12345,
                       injury_statuses=Tags.none(), through="regular")
    assert sp is not None


@pytest.mark.parametrize("mode,ok", [("nightly", False), ("pretip", False), ("refresh", True),
                                     ("poll", True), ("afternoon", True)])
def test_only_runs_that_may_not_price_show_the_previous_engines_line(mode, ok, monkeypatch, tmp_path):
    """11-11 review: a locked refresh or a facts-only run, right after
    set-engine, builds the hub on the previous clean engine's line with a note
    (it was failing the hub build); a nightly or pre-tip run never does."""
    from modules import hub_state
    seen = {}

    class Stop(Exception):
        pass

    def fake_build(*a, **k):
        seen.update(k)
        raise Stop
    monkeypatch.setattr(hub_state, "build", fake_build)
    r = nightly.Run(tmp_path, mode, now=NOW, **({"cause": "x"} if mode == "refresh" else {}))
    monkeypatch.setattr(nightly.Run, "_afternoon_unchanged", lambda self: False)
    with pytest.raises(Stop):
        r.step_hub()
    assert seen["previous_engine_ok"] is ok


def test_the_hub_page_prints_the_engine_note_calmly():
    from modules import hub_page
    from test_hub import sample_payload, GEN, visible_text
    p = sample_payload()
    p["header"]["engine_note"] = "Lines priced by the previous engine version (abc1234); they re-price soon."
    page = hub_page.render(p, now=GEN)
    assert "previous engine version (abc1234)" in visible_text(page)
    assert "Do not price anything off this page" not in visible_text(page)


def test_an_nba_report_out_counts_as_out_everywhere_the_hub_counts_games():
    """Nick, 11-11: like D, a game the NBA's injury report has him Out for is
    out in the rosters' games left and the free agents' counts too (plays()),
    and the grid keeps its dagger mark for it."""
    from modules.hub_state import Availability
    from modules import absence
    from datetime import date as _d
    av = Availability.__new__(Availability)
    tonight, later = _d(2026, 11, 11), _d(2026, 11, 13)
    av.absence = absence
    av.tags, av.over, av.today = {"Zion Williamson": "Q"}, {}, tonight
    av.info = {"Zion Williamson": {"nba_team": "NOP"}}
    av.team_dates = {"NOP": {tonight, later}}
    av.nba_outs = {"Zion Williamson": tonight}
    av.weeks = {4: (_d(2026, 11, 9), _d(2026, 11, 15))}
    assert av.out("Zion Williamson", tonight) and not av.plays("Zion Williamson", tonight)
    assert av.plays("Zion Williamson", later)                 # that game only
    assert av.grid_status("Zion Williamson", tonight) == "nba"
