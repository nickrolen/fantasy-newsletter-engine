"""Contract tests between fun_facts_generator and content_freshness.

These two modules previously drifted apart silently: the generator emitted
subcategories the freshness layer had no cooldown entry for, and fact keys
were built from detail fields the generator never emitted (collapsing
distinct facts onto one key). These tests make the contract explicit.
"""
import re
from pathlib import Path

from modules.content_freshness import COOLDOWN_PERIODS, make_fact_key

GENERATOR_SRC = (
    Path(__file__).parent.parent / "modules" / "fun_facts_generator.py"
).read_text(encoding="utf-8")

EMITTED = sorted(set(re.findall(r'subcategory="([a-z_]+)"', GENERATOR_SRC)))


def test_every_emitted_subcategory_has_a_cooldown_entry():
    missing = [s for s in EMITTED if s not in COOLDOWN_PERIODS]
    assert missing == [], f"subcategories with no cooldown policy: {missing}"


def test_upset_keys_distinguish_rivalries():
    k1 = make_fact_key("h2h_upset", underdog="Ann", favorite="Bob")
    k2 = make_fact_key("h2h_upset", underdog="Cal", favorite="Dee")
    assert k1 != k2
    # Same pair is the same fact regardless of field order
    assert k1 == make_fact_key("h2h_upset", underdog="Bob", favorite="Ann")


def test_sweep_keys_are_directional():
    assert (make_fact_key("season_sweep", sweeper="Ann", swept="Bob")
            != make_fact_key("season_sweep", sweeper="Bob", swept="Ann"))


def test_blowout_keys_distinguish_matchups():
    k1 = make_fact_key("blowout", winner="Ann", loser="Bob", margin=120.0)
    k2 = make_fact_key("blowout", winner="Cal", loser="Dee", margin=80.0)
    assert k1 != k2


def test_milestone_keys_include_matchup_and_number():
    k1 = make_fact_key("h2h_milestone", matchup="ann_vs_bob", total=40)
    k2 = make_fact_key("h2h_milestone", matchup="ann_vs_bob", total=50)
    k3 = make_fact_key("h2h_milestone", matchup="cal_vs_dee", total=40)
    assert len({k1, k2, k3}) == 3


def test_dominance_keys_distinguish_rivals():
    k1 = make_fact_key("h2h_dominance", dominant="Ann", dominated="Bob")
    k2 = make_fact_key("h2h_dominance", dominant="Ann", dominated="Cal")
    assert k1 != k2
