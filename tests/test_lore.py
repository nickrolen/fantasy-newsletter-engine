"""League lore: proposals that are honest about chance, entries that can't
go stale silently, and the review loop."""

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from modules import lore as L  # noqa: E402
from modules import claim_check as cc  # noqa: E402
import review_lore  # noqa: E402

MGRS = ["Nick", "Hayden", "Benton", "Garrett"]
PAIRS = [[("Nick", "Hayden"), ("Benton", "Garrett")],
         [("Nick", "Benton"), ("Hayden", "Garrett")],
         [("Nick", "Garrett"), ("Hayden", "Benton")]]
MONTH_OF_WEEK = {w: (10, 11, 11, 11, 12, 12, 12, 12, 1, 1, 1, 1, 2, 2, 2, 3,
                     3, 3, 3, 4, 4, 4, 4)[w - 1] for w in range(1, 24)}


def _season(s, rng, edge=None, weeks=21):
    out = []
    for w in range(1, weeks + 1):
        for a, b in PAIRS[w % 3]:
            sa, sb = rng.gauss(1600, 150), rng.gauss(1600, 150)
            if edge and MONTH_OF_WEEK[w] == edge[1] and edge[0] in (a, b):
                hi, lo = max(sa, sb) + 1, min(sa, sb)
                if rng.random() < edge[2]:
                    sa, sb = (hi, lo) if a == edge[0] else (lo, hi)
            out.append({"season": s, "week": w, "manager_a": a,
                        "manager_b": b, "score_a": sa, "score_b": sb})
    return out


def _world(seed, edge=None, seasons=9):
    rng = random.Random(seed)
    m = []
    for i in range(seasons):
        m += _season(f"{2017 + i}-{(18 + i) % 100:02d}", rng, edge)
    games = L.games_from_matchups(m)
    months = {(g.season, g.week): MONTH_OF_WEEK[g.week] for g in games}
    return games, months


def _scan(games, months, perms=400):
    cells = L.scan(games, months, lambda s: 19, perms=perms, seed=1)
    L.benjamini_hochberg(cells)
    return cells


def test_pure_chance_yields_no_tendency():
    """Coin-flip league, nine seasons: some cells will look striking, none
    may be proposed as a tendency."""
    for seed in (1, 2, 3):
        cells = _scan(*_world(seed))
        assert not [c for c in cells if L.strength_of(c) == "tendency"]


def test_striking_chance_cells_are_offered_only_as_facts():
    cells = _scan(*_world(2))
    lore = {"entries": []}
    new = L.propose(lore, cells, today="2026-10-07")
    for e in new:
        assert e["strength"] == "fact"
        assert "not a pattern" in e["evidence"]["note"]


def test_a_real_effect_is_found():
    games, months = _world(4, edge=("Garrett", 12, 0.95))
    cells = _scan(games, months, perms=1000)
    found = {c.id: L.strength_of(c) for c in cells}
    assert found.get("month-garrett-dec") == "tendency"


def test_rejection_is_logged_not_destroyed():
    """Nick: 34 items in one sitting, he'll misjudge one around item 29.
    A rejected entry stays, isn't re-proposed, and can be brought back."""
    cells = _scan(*_world(4, edge=("Garrett", 12, 0.95)), perms=1000)
    lore = {"entries": []}
    L.propose(lore, cells)
    n = len(lore["entries"])
    for e in lore["entries"]:
        L.decide(e, "rejected", today="2026-10-07")
    assert L.propose(lore, cells) == []
    assert len(lore["entries"]) == n
    e = lore["entries"][0]
    assert e["decisions"][-1] == {"on": "2026-10-07", "from": "proposed",
                                  "to": "rejected"}
    assert L.undo(e) and e["status"] == "proposed"
    assert len(e["decisions"]) == 2


def test_refresh_advances_the_numbers_and_flags_a_dead_tendency():
    """The recurring failure mode: a value derived once and never advanced.
    An approved entry re-renders from its definition on every refresh, and
    a tendency that stops holding goes stale."""
    games, months = _world(4, edge=("Garrett", 12, 0.95))
    cells = _scan(games, months, perms=1000)
    lore = {"entries": []}
    L.propose(lore, cells)
    e = next(x for x in lore["entries"] if x["id"] == "month-garrett-dec")
    e["status"] = "approved"
    before = e["text"]
    # six more seasons of Garrett losing every December game
    rng = random.Random(9)
    more = []
    for i in range(6):
        more += _season(f"{2026 + i}-{(27 + i) % 100:02d}", rng,
                        edge=("Garrett", 12, 0.0))
    for x in more:
        if MONTH_OF_WEEK[x["week"]] == 12 and "Garrett" in (x["manager_a"],
                                                            x["manager_b"]):
            g_a = x["manager_a"] == "Garrett"
            lo, hi = sorted([x["score_a"], x["score_b"]])
            x["score_a"], x["score_b"] = (lo, hi + 1) if g_a else (hi + 1, lo)
    games2 = games + L.games_from_matchups(more)
    months2 = {(g.season, g.week): MONTH_OF_WEEK[g.week] for g in games2}
    cells2 = _scan(games2, months2, perms=1000)
    changed = L.refresh(lore, cells2)
    assert e["text"] != before
    assert e["stale"] and "month-garrett-dec" in changed


def test_fact_rerenders_and_never_goes_stale():
    games, months = _world(2)
    cells = _scan(games, months)
    lore = {"entries": []}
    L.propose(lore, cells)
    facts = [e for e in lore["entries"] if e["strength"] == "fact"]
    if not facts:
        pytest.skip("no striking cell in this world")
    facts[0]["status"] = "approved"
    L.refresh(lore, cells)
    assert facts[0]["stale"] is False


def test_loyalty_is_a_count_not_a_test():
    drafts = [{"season": f"{2017 + i}-{18 + i}", "manager": "Nick",
               "player_name": "Joel Embiid", "round": 1,
               "is_keeper": i % 2 == 0} for i in range(L.LOYALTY_MIN_SEASONS)]
    cells = L.scan([], {}, lambda s: 19, drafts=drafts, positions={},
                   perms=10)
    c = next(c for c in cells if c.family == "loyalty")
    assert not c.tested and L.strength_of(c) == "fact"
    assert "Joel Embiid" in c.render()


# ------------------------------------------------------------ claim check

class _V(cc.Vocabulary):
    def __init__(self, aliases=None):
        super().__init__(MGRS, {}, aliases or {},
                         ["Nickeil Alexander-Walker", "Karl-Anthony Towns"])


def test_written_lore_makes_reputations_sayable_not_numbers():
    e = {"id": "w1", "kind": "written", "status": "approved",
         "strength": "written",
         "text": "Benton has a blunder habit, 7 straight seasons of it.",
         "entities": ["Benton"]}
    v = _V()
    pool = cc.build_pool(v, [], [], [e])
    ok = "### **1. X**\n\nBenton's blunder habit strikes. <!--lore:w1-->"
    assert cc.check(ok, pool, v, {"w1": e}) == []
    bad = ("### **1. X**\n\nBenton's blunder habit, 7 straight seasons. "
           "<!--lore:w1-->")
    assert [f.token for f in cc.check(bad, pool, v, {"w1": e})] == ["7"]


def test_fact_told_as_character_is_flagged():
    e = {"id": "f1", "kind": "derived", "strength": "fact",
         "status": "approved",
         "text": "Benton is 6-22 in February matchups.", "values": [6, 22],
         "entities": ["Benton"]}
    v = _V()
    pool = cc.build_pool(v, [], [], [e])
    hist = "### **1. X**\n\nBenton is 6-22 in February. <!--lore:f1-->"
    assert cc.check(hist, pool, v, {"f1": e}) == []
    char = ("### **1. X**\n\nBenton always collapses in February: 6-22. "
            "<!--lore:f1-->")
    assert "fact_as_tendency" in {f.kind for f in
                                  cc.check(char, pool, v, {"f1": e})}


def test_alias_lets_a_nickname_own_its_number():
    report = {"players": [{"player_name": "Nickeil Alexander-Walker",
                           "fppg": 33.26},
                          {"player_name": "Karl-Anthony Towns",
                           "fppg": 38.79}]}
    text = "### **10. X**\n\nTowns (38.79 FPPG) and NAW (33.26 FPPG)."
    v = _V()
    pool = cc.build_pool(v, [("r", report)], [], [])
    assert [f.token for f in cc.check(text, pool, v)] == ["33.26"]
    v2 = _V({"NAW": "Nickeil Alexander-Walker"})
    pool2 = cc.build_pool(v2, [("r", report)], [], [])
    assert cc.check(text, pool2, v2) == []


def test_alias_proposals_need_evidence():
    players = {"Norman Powell", "Victor Wembanyama",
               "Shai Gilgeous-Alexander"}
    drafts = ["## Power Rankings\n\nNick on top.",
              "## Power Rankings\n\nStill Nick.",
              "Wemby again. Victor Wembanyama posted 70.",
              "Wemby, that is Wembanyama, is unreal.",
              "SGA was quiet.", "SGA bounced back."]
    lore = {"entries": []}
    got = {e["alias"]: e["name"] for e in
           L.propose_aliases(lore, drafts, players)}
    assert got == {"Wemby": "Victor Wembanyama",
                   "SGA": "Shai Gilgeous-Alexander"}


# ------------------------------------------------------------ review loop

def _answers(*xs):
    it = iter(xs)
    return lambda prompt="": next(it)


def test_review_saves_after_every_decision():
    lore = {"entries": [
        {"id": "a", "kind": "written", "status": "proposed", "text": "A"},
        {"id": "b", "kind": "written", "status": "proposed", "text": "B"},
        {"id": "c", "kind": "written", "status": "proposed", "text": "C"}]}
    saves = []
    review_lore.review(lore, lambda d: saves.append(
        [e["status"] for e in d["entries"]]),
        ask=_answers("a", "r", "q"), out=lambda *a: None)
    assert saves == [["approved", "proposed", "proposed"],
                     ["approved", "rejected", "proposed"]]


def test_undo_reverts_the_previous_decision_and_reshows_it():
    lore = {"entries": [
        {"id": "a", "kind": "written", "status": "proposed", "text": "A"},
        {"id": "b", "kind": "written", "status": "proposed", "text": "B"}]}
    review_lore.review(lore, lambda d: None,
                       ask=_answers("r", "u", "a", "s"), out=lambda *a: None)
    a = lore["entries"][0]
    assert a["status"] == "approved"
    assert [d["to"] for d in a["decisions"]] == ["rejected", "proposed",
                                                 "approved"]


def test_sitting_walks_one_manager_then_takes_his_own_words(tmp_path):
    lore = {"entries": [
        {"id": "f", "kind": "derived", "status": "proposed", "text": "F",
         "definition": {"manager": "Benton"}, "entities": ["Benton"]},
        {"id": "g", "kind": "derived", "status": "proposed", "text": "G",
         "definition": {"manager": "Garrett"}, "entities": ["Garrett"]}]}
    t = review_lore.sitting(
        lore, "Benton", tmp_path, lambda d: None,
        ask=_answers("a", "Benton forgets his lineup when it matters.", ""),
        out=lambda *a: None)
    assert lore["entries"][1]["status"] == "proposed"      # Garrett untouched
    w = [e for e in lore["entries"] if e["kind"] == "written"]
    assert len(w) == 1 and w[0]["status"] == "approved"
    assert w[0]["entities"] == ["Benton"] and t["added"] == 1


def test_no_code_reads_chat_exports():
    """Nick, 10-07: no chat logs on disk, and no code that reads them."""
    root = Path(__file__).resolve().parent.parent
    for f in list((root / "modules").glob("*.py")) + \
            list((root / "scripts").glob("*.py")):
        assert "lore_sources" not in f.read_text(encoding="utf-8"), f.name
