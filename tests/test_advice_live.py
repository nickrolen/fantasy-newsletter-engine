"""
tests/test_advice_live.py -- advice v2 live (modules/advice_live; V2,
claude/HANDOFF_ADVICE_V2_2026-11-11.md).

A. The ledger's inputs: a claimed player is never in the pool (scenario 9's
   ledger side), a chat-dropped player is from his window, a Monday pool keeps
   a drop effective next Monday out; the second week's rosters; the adds left
   come only from the one counter (a source pin) and a team at 3 in the claim
   week has none (scenario 10's ledger side).
B. Bracket and Cup weeks: the pairing, a tied week to the higher seed.
C. The outputs: one writer; the history row is enough to score later; a
   failed step is recorded and never stops the run; Monday's 12:01 row is
   published.
D. Through the real step: one nightly run's advice step on Nick's real state
   (read in place, writes redirected to a temp folder), writing both outputs;
   the facts-only refresh does not run it.
E. The hub: the switch (required, ships off); off shows no link and no view,
   on shows them; the page computes nothing; 360 px; the plaintext scan on a
   fake-passphrase scratch build.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from modules import advice_live as al, hub_page, hub_publish, move_ledger as ml, nightly

import test_move_ledger as TL

ROOT = Path(__file__).resolve().parents[1]


# =============================================================================
# A. the ledger's inputs
# =============================================================================

def _pl(w):
    return list(w.playerlist)


def test_a_claimed_player_is_never_in_the_pool_and_a_chat_drop_is_from_his_window():
    w, rows = TL.make_world(), []                       # Thursday of week 3: chat claims join Mon 11-09
    TL.enter(w, rows, "Nick move: +Bane IL+Edwards")
    TL.enter(w, rows, "Benton move: -Alexander-Walker")
    lv = al.ledger_view(w, rows, [], (4, 5), _pl(w))
    assert "Desmond Bane" in lv["reserved"] and "Desmond Bane" not in lv["pool"]
    assert "Nickeil Alexander-Walker" in lv["pool"]                       # rule 11: free for the coming week
    nick_act, nick_il = lv["rosters"][0]["Nick"]
    assert "Desmond Bane" in nick_act and "Anthony Edwards" in nick_il
    assert "Nickeil Alexander-Walker" not in lv["rosters"][0]["Benton"][0]
    for m, (a, i) in lv["rosters"][0].items():                            # nobody's player is in the pool
        assert not (set(a) | set(i)) & set(lv["pool"])


def test_a_claim_then_drop_before_he_joins_frees_him_again():
    w, rows = TL.make_world(), []
    TL.enter(w, rows, "Nick move: +Bane IL+Edwards")
    TL.enter(w, rows, "Nick move: -Bane")                                 # rule 12
    lv = al.ledger_view(w, rows, [], (4, 5), _pl(w))
    assert "Desmond Bane" not in lv["reserved"] and "Desmond Bane" in lv["pool"]


def test_on_a_monday_a_drop_effective_next_monday_is_not_in_this_weeks_pool():
    """Monday 11-09 before the close: the Monday move's pool. A chat drop
    posted this morning takes effect Mon 11-16; this week he is still Benton's
    (rule 11), so he is not in the pool now -- and he is gone from Benton's
    second-week roster. A claim posted this morning is reserved at once."""
    w, rows = TL.make_world(now=TL.at("2026-11-09", 10)), []
    TL.enter(w, rows, "Benton move: -Alexander-Walker", claimed_at=TL.at("2026-11-09", 9))
    TL.enter(w, rows, "Hayden move: +Booker -Pat Hayden01", claimed_at=TL.at("2026-11-09", 9, 30))
    lv = al.ledger_view(w, rows, [], (4, 5), _pl(w))
    assert "Nickeil Alexander-Walker" not in lv["pool"]
    assert "Nickeil Alexander-Walker" in lv["rosters"][0]["Benton"][0]
    assert "Nickeil Alexander-Walker" not in lv["rosters"][1]["Benton"][0]
    assert "Devin Booker" in lv["reserved"] and "Devin Booker" not in lv["pool"]
    assert "Devin Booker" in lv["rosters"][1]["Hayden"][0] and "Devin Booker" not in lv["rosters"][0]["Hayden"][0]


def test_adds_left_come_from_the_one_counter_and_three_used_leaves_none():
    w = TL.make_world(yahoo={3: {"Nick": ["A", "B", "C"], "Hayden": ["D"]}})
    rows = []
    left = al.adds_left(w, rows, [], 3, 3, TL.M)
    assert left == {"Nick": 0, "Hayden": 2, "Garrett": 3, "Benton": 3}
    w2 = TL.make_world(yahoo={3: {"Hayden": ["D"]}})
    TL.enter(w2, rows, "Hayden move: +Bane -Pat Hayden01")                 # a pending claim of week 3 counts
    assert al.adds_left(w2, rows, [], 3, 3, TL.M)["Hayden"] == 1


def test_the_adds_count_has_one_source():
    """advice_live counts adds only through move_ledger.adds_used (which is
    transaction_rulings.adds_by_budget_week plus the pending claims): no
    second count of its own."""
    src = (ROOT / "modules" / "advice_live.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert calls.count("adds_used") == 1
    code = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
        {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and not n.value.startswith("\n") and len(n.value) < 80]
    for bad in ("adds_by_budget_week", "add_budget_week", "build_add_budget", "transaction_log", "transactions"):
        assert bad not in code, bad
    assert not [s_ for s_ in strings if "waivers_week" in s_]
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build")
    assert "adds_left" in {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Name)}


# =============================================================================
# B. bracket and Cup weeks
# =============================================================================

def test_a_bracket_week_ties_to_the_higher_seed():
    seeds = {"A": 1, "B": 4, "C": 2, "D": 3}
    m = al.pairing_map([("A", "B"), ("C", "D")], seeds)
    assert m == {"A": ("B", 1.0), "B": ("A", 0.0), "C": ("D", 1.0), "D": ("C", 0.0)}
    with pytest.raises(al.AdviceInputError):
        al.pairing_map([("A", "Z")], seeds)


def test_series_results_are_best_of_three_with_ties_to_the_higher_seed():
    seeds = {"A": 1, "B": 4, "C": 2, "D": 3}
    sc = {16: {"A": 10, "B": 12, "C": 5, "D": 5}, 17: {"A": 9, "B": 9, "C": 1, "D": 9},
          18: {"A": 2, "B": 1, "C": 1, "D": 0}}
    assert al.series_results([("A", "B"), ("C", "D")], sc, seeds) == [("A", "B"), ("C", "D")]
    sc[17]["A"] = 8                                                        # B now wins 2 of 3
    assert al.series_results([("A", "B")], sc, seeds) == [("B", "A")]


def test_the_phases():
    assert al.phase_of(15) == "regular_season"
    assert al.phase_of(16) == al.phase_of(21) == "playoffs"
    assert al.phase_of(22) == al.phase_of(23) == "cup"


# =============================================================================
# C. the outputs
# =============================================================================

def test_one_writer_of_both_outputs():
    hits = []
    for p in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        if "advice_latest" in src or "advice_history" in src or "LATEST_FILE" in src and p.name == "advice_live.py":
            for m in re.finditer(r"(atomic_write_json|append_rows|write_text)\(([^\n]*)", src):
                hits.append((p.name, m.group(0)[:90]))
    writers = [h for h in hits if h[0] == "advice_live.py"]
    assert len(writers) == 2 and all("LATEST_FILE" in w[1] or "HISTORY_FILE" in w[1] for w in writers)
    src = (ROOT / "modules" / "advice_live.py").read_text(encoding="utf-8")
    write_fn = src[src.index("def write("):src.index("def read_latest(")]
    assert "atomic_write_json(base / LATEST_FILE" in write_fn and "append_rows(base / HISTORY_FILE" in write_fn
    assert src.count("atomic_write_json(") == 1 and src.count("append_rows(") == 1


def _fake_latest(err=None):
    mv = {"kind": "add_drop", "add": "Free Guy", "drop": "Yan Beta", "to_il": None, "followup_drop": None,
          "describe": "add Free Guy, drop Yan Beta", "score": 0.08, "flat": False, "dwp": [0.05, 0.03],
          "wp_base": [0.5, 0.6], "dpts": [40.0, 22.0], "dstarts": [1.0, 0.5], "dT_horizon": 0.02,
          "dT_later": 0.01, "dT_rs": 0.03, "dT_po": 0.0, "dpts_later": 50.0, "title_odds": 0.015,
          "title_label": "title odds", "reason": "+1.5 starts"}
    hz = {"kind": "monday", "label": "Monday move", "weeks": [3, 4], "effective": "2026-11-02",
          "budget_week": 3, "closes": "2026-11-02T18:55-08:00"}
    mv["text"] = {"move": al.move_text(mv), "numbers": al.numbers_text(mv, hz, {"3": "Mgr Two", "4": "Mgr Two"}),
                  "reason": al.reason_text(mv, hz), "followup": ""}
    bk = dict(mv, add="Backup Guy", describe="add Backup Guy, drop Yan Beta")
    bk["text"] = dict(mv["text"], move=al.move_text(bk))
    mans = {"Mgr One": {"adds_left": 2, "opponents": {"3": "Mgr Two", "4": "Mgr Two"}, "also_wanted_by": ["Mgr Two"],
                        "move": mv, "backup": bk, "note": "", "bar": 0.0},
            "Mgr Two": {"adds_left": 0, "opponents": {"3": "Mgr One", "4": "Mgr One"}, "also_wanted_by": [],
                        "move": None, "backup": None, "note": "no adds left", "bar": None,
                        "empty": "No adds left this week (week 3's budget)"}}
    return {"schema": 1, "run_id": "r1", "mode": "poll", "cause": "Monday move: Mgr Two added Free Guy",
            "cause_text": "Mgr Two added Free Guy", "as_of": "2026-11-02T00:14:00-08:00",
            "updated_text": "Updated 12:14 AM after Mgr Two added Free Guy.", "league_day": "2026-11-02",
            "horizon": hz, "weighting": "w", "settings": {}, "inputs": {"anchor": "2026-11-02"}, "seconds": {},
            "managers": {} if err else mans, "error": err}


def test_the_display_strings():
    p = _fake_latest()
    mv = p["managers"]["Mgr One"]["move"]
    assert mv["text"]["move"] == "Add Free Guy, drop Yan Beta"
    assert mv["text"]["numbers"] == ("+5.0% vs Mgr Two this week, +3.0% vs Mgr Two next week "
                                     "\u00b7 title odds +1.5%")
    assert mv["text"]["reason"].startswith("+1.5 starts (this week +1.0, next week +0.5); +62 pts")
    chat = dict(p["horizon"], kind="chat", label="Chat move (effective Mon 11-09)")
    assert "next week" in al.numbers_text(mv, chat, {"3": "X", "4": None}) and \
        "no matchup set the week after (week 4)" in al.numbers_text(mv, chat, {"3": "X", "4": None})
    cup = dict(mv, title_label=None, title_odds=None)
    assert "no title odds at stake in the Cup" in al.numbers_text(cup, p["horizon"], {"3": "X", "4": "Y"})
    assert al.move_text(dict(mv, kind="il_swap", drop="P", to_il="L")) == \
        "Drop P from the IL slot, move L into it, add Free Guy"
    assert al.cause_text("poll", "Monday moves: A added X; B dropped Y") == "A added X; B dropped Y"
    assert al.cause_text("nightly", None) == "the nightly run"


def test_the_history_row_is_enough_to_score_later():
    p = _fake_latest()
    row = al.history_row(p, published=True)
    assert row["published"] is True and row["as_of"] and row["horizon"]["weeks"] == [3, 4]
    t = row["managers"]["Mgr One"]["top"]
    for k in ("kind", "add", "drop", "to_il", "followup_drop", "dwp", "wp_base", "dpts", "dstarts",
              "dT_later", "title_odds", "score"):
        assert k in t, k
    assert row["managers"]["Mgr One"]["opponents"] == {"3": "Mgr Two", "4": "Mgr Two"}
    assert row["managers"]["Mgr Two"]["top"] is None
    json.dumps(row)


def test_only_mondays_1201_nightly_row_is_published():
    from modules import advice_v2 as av
    LA = TL.LA
    mon = date(2026, 11, 16)
    hz = av.Horizon(av.MONDAY, (5, 6), 5, mon, datetime(2026, 11, 16, 18, 55, tzinfo=LA))
    at = datetime(2026, 11, 16, 0, 2, tzinfo=LA)
    assert al.is_published("nightly", at, hz, mon)
    assert not al.is_published("poll", at, hz, mon)
    assert not al.is_published("nightly", at + timedelta(days=1), hz, mon)
    chat = av.Horizon(av.CHAT, (6, 7), 5, date(2026, 11, 23), hz.closes)
    assert not al.is_published("nightly", at, chat, mon)


def test_a_failed_step_is_recorded_both_outputs_and_never_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise al.AdviceInputError("no usable stakes: test")
    monkeypatch.setattr(al, "build", boom)
    now = datetime(2026, 11, 12, 0, 5, tzinfo=TL.LA)
    out = al.run_step(tmp_path, now, run_id="run-x", mode="nightly", cause="nightly")
    assert out["block"]["error"].startswith("AdviceInputError: no usable stakes")
    assert out["lines"] == ["ADVICE FAILED: AdviceInputError: no usable stakes: test"]
    latest = al.read_latest(tmp_path)
    assert latest["error"] and latest["managers"] == {} and "could not be updated" in latest["updated_text"]
    rows = al.read_history(tmp_path)
    assert len(rows) == 1 and rows[0]["error"] and rows[0]["published"] is False
    view = al.hub_view(latest, [{"manager": "Mgr One", "team": "Team Uno"}])
    assert view["cards"][0]["empty"] == "Advice could not be updated." and not view["cards"][0]["move"]
    assert "may no longer stand" in view["foot"]


def test_a_failed_advice_step_does_not_stop_the_run_and_the_hub_still_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(nightly, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(al, "build", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    run = nightly.Run(tmp_path, "nightly", now=datetime(2026, 11, 12, 0, 5, tzinfo=TL.LA), echo=lambda *a: None)
    done = []
    stubs = {s: (lambda s=s: done.append(s) or "stub") for s in nightly.STEPS["nightly"] if s != "advice"}
    row = run.execute(stubs)
    assert row["outcome"] == "ok" and "hub" in done
    assert row["advice"]["error"].startswith("KeyError")
    assert [s["step"] for s in row["steps"]] == list(nightly.STEPS["nightly"])


def test_every_pricing_mode_runs_advice_and_the_facts_only_refresh_does_not():
    for mode in ("nightly", "refresh", "pretip", "poll", "afternoon"):
        st = nightly.STEPS[mode]
        assert "advice" in st, mode
        assert st.index("title_odds") < st.index("advice") < st.index("actuals") < st.index("hub"), mode
    assert "advice" not in nightly.STEPS["refresh_facts"] and "advice" not in nightly.STEPS["closing"]


def test_the_facts_only_refresh_never_runs_the_advice_step(tmp_path, monkeypatch):
    monkeypatch.setattr(nightly, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(al, "run_step", lambda *a, **k: pytest.fail("advice ran in a facts-only refresh"))
    run = nightly.Run(tmp_path, "refresh", now=datetime(2026, 11, 12, 15, 0, tzinfo=TL.LA),
                      cause="trade block: Nick buying", facts_only=True, echo=lambda *a: None)
    stubs = {s: (lambda: "stub") for s in nightly.STEPS["refresh_facts"]}
    row = run.execute(stubs)
    assert row["outcome"] == "ok" and "advice" not in row
    assert "advice" not in [s["step"] for s in row["steps"]]


# =============================================================================
# D. through the real step, on Nick's real state (read in place)
# =============================================================================

REAL = [ROOT / "output" / "tag_records.jsonl", ROOT / "output" / "stakes.json", ROOT / "config" / "ROSTERS.json",
        ROOT / "data" / "PLAYERLIST.xlsx", ROOT / "data" / "IL_SLOTS.json"]


@pytest.mark.skipif(not all(p.is_file() for p in REAL), reason="needs the league's real state")
def test_a_nightly_runs_advice_step_on_the_real_state_writes_both_outputs(tmp_path, monkeypatch):
    """The real step, nothing stubbed in it: nightly.Run.step_advice ->
    advice_live.run_step -> build (the live files, read in place) ->
    advise_all -> write. Only the paths it writes (and the run record) are
    redirected to a temp folder; the other steps of the run are stubbed (they
    call Yahoo). The clock is the latest tag fetch's, so the state is
    self-consistent whenever the suite runs."""
    from modules import tag_records
    monkeypatch.setattr(al, "LATEST_FILE", tmp_path / "advice_latest.json")
    monkeypatch.setattr(al, "HISTORY_FILE", tmp_path / "advice_history.jsonl")
    monkeypatch.setattr(nightly, "RUNS_FILE", tmp_path / "runs.jsonl")
    now = datetime.fromisoformat(tag_records.latest(ROOT)["taken_at"]) + timedelta(minutes=1)
    run = nightly.Run(ROOT, "nightly", now=now, echo=lambda *a: None)
    stubs = {s: (lambda: "stub") for s in nightly.STEPS["nightly"] if s != "advice"}
    row = run.execute(stubs)
    assert row["outcome"] == "ok"
    assert row["advice"]["error"] is None, row["advice"]["error"]
    latest = json.loads((tmp_path / "advice_latest.json").read_text(encoding="utf-8"))
    hist = [json.loads(x) for x in (tmp_path / "advice_history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(hist) == 1 and hist[0]["run_id"] == latest["run_id"] == run.run_id
    assert set(latest["managers"]) == {"Nick", "Hayden", "Benton", "Garrett"}
    assert latest["horizon"]["kind"] in ("monday", "chat")
    reserved = set(latest["inputs"]["reserved"])
    for m, e in latest["managers"].items():
        for key in ("move", "backup"):
            if e[key] is not None:
                assert e[key]["add"] not in reserved and e[key]["text"]["move"]
        if e["move"] is None:
            assert e["empty"]
    assert run.ctx["advice_lines"] and all(l.startswith("ADVICE ") for l in run.ctx["advice_lines"])
    assert not (ROOT / "output" / "advice_latest.json").exists() or \
        (ROOT / "output" / "advice_latest.json").stat().st_mtime < now.timestamp()


# =============================================================================
# E. the hub
# =============================================================================

def test_the_switch_is_required_and_ships_off():
    from modules.data_loader import UnspecifiedRule
    assert al.hub_switch() == "off"
    cfg = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))
    assert cfg["advice"]["hub"] == "off"
    assert al.hub_switch({"advice": {"hub": "on"}}) == "on"
    with pytest.raises(UnspecifiedRule):
        al.hub_switch({"advice": {}})
    with pytest.raises(UnspecifiedRule):
        al.hub_switch({})
    with pytest.raises(al.AdviceInputError):
        al.hub_switch({"advice": {"hub": "yes"}})


def test_the_hub_reads_advice_only_behind_the_switch():
    src = (ROOT / "modules" / "hub_state.py").read_text(encoding="utf-8")
    assert ('advice = al.hub_view(al.read_latest(base), power["rows"]) if al.hub_switch() == "on" else None'
            in src)
    assert '"advice": advice,' in src


def _page(advice):
    from test_hub import GEN, sample_payload
    p = sample_payload(advice=advice)
    return p, hub_page.render(p, now=GEN)


def _view(page):
    v = page[page.index('id="v-advice"'):]
    return v[:v.index('<div class="view"', 10)] if '<div class="view"' in v[10:] else v


def test_switch_off_shows_no_link_and_no_view():
    p, page = _page(None)
    assert "v-advice" not in page and "Advice &rarr;" not in page
    assert "Advice is being rebuilt; it returns here once it is ready." in page


def test_switch_on_shows_the_link_beside_the_trade_block_and_the_view():
    view = al.hub_view(_fake_latest(), [{"manager": "Mgr One", "team": "Team Uno"},
                                        {"manager": "Mgr Two", "team": "Team Dos"}])
    p, page = _page(view)
    card = page[page.index("<h2>Power rankings</h2>"):page.index("<h2>Games grid</h2>")]
    assert card.index('data-open="v-block"') < card.index('data-open="v-advice"')
    assert "Advice &rarr;</button></div>" in card
    assert "Advice is being rebuilt" not in page
    v = _view(page)
    assert '<a href="#" class="back" data-open="v-main">&larr; Power rankings</a>' in v
    assert re.findall(r'data-manager="([^"]+)"', v) == ["Mgr One", "Mgr Two"]       # power-rankings order
    assert '<div class="ad-k">Monday move</div>' in v
    assert '<div class="ad-m">Add Free Guy, drop Yan Beta</div>' in v
    assert "+5.0% vs Mgr Two this week, +3.0% vs Mgr Two next week \u00b7 title odds +1.5%" in v.replace(
        "&middot;", "\u00b7")
    assert "Also wanted by Mgr Two" in v and "If he&#x27;s gone: Add Backup Guy" in v.replace("&#39;", "&#x27;")
    assert '<div class="empty">No adds left this week (week 3&#x27;s budget)</div>' in v.replace("&#39;", "&#x27;")
    assert "Updated 12:14 AM after Mgr Two added Free Guy." in v


def test_no_move_reads_no_move_beats_standing_pat():
    latest = _fake_latest()
    latest["managers"]["Mgr Two"] = dict(latest["managers"]["Mgr Two"], adds_left=3, note="standing pat",
                                         empty="No move beats standing pat")
    view = al.hub_view(latest, [{"manager": "Mgr Two", "team": "Team Dos"}])
    assert view["cards"][0]["empty"] == "No move beats standing pat"


def test_every_number_on_the_view_is_a_payload_string():
    from test_hub import payload_strings, visible_text
    view = al.hub_view(_fake_latest(), [{"manager": "Mgr One", "team": "Team Uno"},
                                        {"manager": "Mgr Two", "team": "Team Dos"}])
    p, page = _page(view)
    known = " ".join(payload_strings(p["advice"]))
    for n in re.findall(r"\d+(?:[.,:-]\d+)*", visible_text(_view(page))):
        assert n in known, n


def test_the_view_fits_a_360px_phone():
    css = hub_page.CSS
    rules = {m.group(1): m.group(2) for m in re.finditer(r"(\.ad-[^{]+)\{([^}]*)\}", css)}
    assert set(rules) >= {".ad-b", ".ad-k", ".ad-m", ".ad-n", ".ad-s"}
    for sel, body in rules.items():
        assert not re.search(r"(?<![-\w])(min-|max-)?width:\d+px", body), sel
    for sel in (".ad-m", ".ad-n", ".ad-s"):
        assert "overflow-wrap:anywhere" in rules[sel], sel


def test_the_publish_directory_carries_no_advice_name_in_plaintext(tmp_path):
    from test_hub import GEN, PASS, TERMS, publish_world
    p = publish_world(tmp_path)
    latest = _fake_latest()
    latest["managers"]["Mgr One"]["move"]["text"]["move"] = "Add Advice Only Guy, drop Yan Beta"
    p["advice"] = al.hub_view(latest, [{"manager": "Mgr One", "team": "Team Uno"},
                                       {"manager": "Mgr Two", "team": "Team Dos"}])
    terms = TERMS + ["Advice Only Guy"]
    assert hub_publish.hits(hub_page.render(p, now=GEN, mode="publish").encode(), terms)   # negative control
    hub_publish.build(tmp_path, p, PASS, terms=terms, iterations=1000, now=GEN)
    assert hub_publish.scan_dir(hub_publish.publish_dir(tmp_path), terms)["hits"] == {}


def test_the_state_manifest_declares_both_outputs_and_git_ignores_them():
    m = json.loads((ROOT / "config" / "STATE_MANIFEST.json").read_text(encoding="utf-8"))
    paths = {f["path"] for f in m["files"]}
    assert {"output/advice_latest.json", "output/advice_history.jsonl"} <= paths
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "output/advice_latest.json" in gi and "output/advice_history.jsonl" in gi
