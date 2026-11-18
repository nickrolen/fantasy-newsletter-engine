"""H52 D (Nick, 11-17: "yes to both"):
  1. claim_check flags "made N adds" / "N adds" / "added N players" above the
     card's joined_week_adds (adff247's "New players" line's safety net);
  2. move_ledger.World.eligible_tags is required (no ("O", "OFS") default).
"""
import dataclasses
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import claim_check as cc                           # noqa: E402
from modules import move_ledger as ml                           # noqa: E402

TEAMS = {"Nick": "Nick's Team", "Hayden": "Hayden's Team", "Benton": "Blink-183", "Garrett": "Garrett's Team"}
# week 4's real split (H51 D, checked against data/waivers_week4.txt and the claim_week rulings)
WEEK4 = {"Nick": (3, 3), "Hayden": (0, 2), "Benton": (2, 1), "Garrett": (1, 0)}


def cards():
    return [{"manager": m, "joined_week_adds": a, "joined_claims": c} for m, (a, c) in WEEK4.items()]


def vocab():
    return cc.Vocabulary(list(WEEK4), TEAMS, {}, ["Devin Booker", "Pascal Siakam"])


def found(text, cs=None):
    return cc.adds_claim_findings(text, vocab(), cards() if cs is None else cs)


def test_more_adds_than_the_card_is_a_finding():
    f = found("Nick made six adds, the most in the league.")
    assert len(f) == 1 and f[0].kind == "adds_over_card" and f[0].token.lower() == "made six adds"
    assert "Nick made 3 add(s) this week" in f[0].sentence
    assert found("Hayden added two players before the deadline.")[0].token == "added two players"
    assert len(found("With 6 adds, Nick rebuilt the bench.")) == 1


def test_joined_players_and_true_counts_are_not():
    assert found("Six players joined Nick's roster this week.") == []
    assert found("Nick made three adds, and Benton two.") == []                # 3 <= 3
    assert found("Benton made 2 adds; Garrett made one add.") == []
    assert found("Nick has two adds left this week.") == []                    # the budget, not adds made
    assert found("Somebody made nine adds.") == []                             # no manager to pin it on


def test_the_nearest_manager_before_the_phrase_owns_it():
    f = found("Benton watched while Garrett made two adds.")
    assert len(f) == 1 and "Garrett made 1 add(s)" in f[0].sentence


def test_a_card_without_the_split_cannot_vouch_for_an_add_count():
    f = found("Nick made three adds.", cs=[{"manager": "Nick"}])
    assert len(f) == 1 and "no joined_week_adds" in f[0].sentence


def test_check_draft_runs_the_rule_with_the_cards():
    import check_draft
    src = inspect.getsource(check_draft.run)
    assert "cc.adds_claim_findings(draft_text, vocab, cards)" in src
    assert "adds_over_card" in check_draft.KIND_ORDER and "adds_over_card" in check_draft.KIND_LABEL


def test_world_eligible_tags_is_required():
    f = {x.name: x for x in dataclasses.fields(ml.World)}["eligible_tags"]
    assert f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
    assert "eligible_tags=il_eligible_tags()" in inspect.getsource(ml.World.from_base)
