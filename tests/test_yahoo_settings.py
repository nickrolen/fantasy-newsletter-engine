"""The settings-drift check (step 1a; design s.4, s.6.1a, invariant 9).

Co-commissioners (10-30) can change a Yahoo setting without Nick, so every
setting the engine models is compared with config/league_config.json, and a
difference refuses by name. The fixture is the league/<key>/settings response
read 10-31, scrubbed to the compared fields (yahoo_settings.scrub).
"""
import copy
import json
from pathlib import Path

import pytest

from modules import yahoo_settings as ys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "yahoo_settings_2026-10-31.json")
                     .read_text(encoding="utf-8"))
CFG = json.loads((ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))


def _meta(raw):
    return raw["fantasy_content"]["league"][0]


def _st(raw):
    return raw["fantasy_content"]["league"][1]["settings"][0]


def _stat(raw, abbr):
    sid = next(s["stat"]["stat_id"] for s in _st(raw)["stat_categories"]["stats"]
               if s["stat"]["abbr"] == abbr)
    return next(s for s in _st(raw)["stat_modifiers"]["stats"] if s["stat"]["stat_id"] == sid)


def _pos(raw, name):
    return next(p for p in _st(raw)["roster_positions"]
                if p["roster_position"]["position"] == name)["roster_position"]


def test_the_fixture_passes():
    got = ys.check(FIXTURE)
    assert got["max_weekly_adds"] == 6 and got["roster"]["IL"] == 2
    assert got["stat_values"]["TO"] == -2.0 and got["uses_playoff"] is False


CHANGES = {
    "num_teams": lambda r: _meta(r).update(num_teams=6),
    "weeks.start_week": lambda r: _meta(r).update(start_week=2),
    "weeks.end_week": lambda r: _meta(r).update(end_week=21),
    "weeks.start_date": lambda r: _meta(r).update(start_date="2026-10-21"),
    "weeks.end_date": lambda r: _meta(r).update(end_date="2027-03-28"),
    "roster.C": lambda r: _pos(r, "C").update(count=1),
    "roster.IL": lambda r: _pos(r, "IL").update(count=3),
    "roster.BN": lambda r: _pos(r, "BN").update(count=4),
    "max_weekly_adds": lambda r: _st(r).update(max_weekly_adds="3"),
    "scoring_type": lambda r: _st(r).update(scoring_type="head"),
    "uses_playoff": lambda r: _st(r).update(uses_playoff="1"),
    "waiver_time_days": lambda r: _st(r).update(waiver_time="2"),
    "uses_faab": lambda r: _st(r).update(uses_faab="1"),
    "can_trade_draft_picks": lambda r: _st(r).update(can_trade_draft_picks="0"),
    "trade_deadline": lambda r: _st(r).update(trade_end_date="2027-03-18"),
    "stat_values.TO": lambda r: _stat(r, "TO")["stat"].update(value="-1"),
    "stat_values.FGA": lambda r: _stat(r, "FGA")["stat"].update(value="-0.5"),
}


@pytest.mark.parametrize("name", sorted(CHANGES))
def test_each_modelled_setting_changed_in_yahoo_refuses_by_name(name):
    raw = copy.deepcopy(FIXTURE)
    CHANGES[name](raw)
    with pytest.raises(ys.SettingsDrift, match=rf"Yahoo setting {name.replace('.', '[.]')} changed "
                                               r"from .* to .*; update config or revert in Yahoo"):
        ys.check(raw)


def test_a_disabled_scoring_category_refuses():
    raw = copy.deepcopy(FIXTURE)
    next(s for s in _st(raw)["stat_categories"]["stats"]
         if s["stat"]["abbr"] == "BLK")["stat"]["enabled"] = "0"
    with pytest.raises(ys.SettingsDrift, match="stat_values.BLK"):
        ys.check(raw)


def test_every_difference_is_named_at_once():
    raw = copy.deepcopy(FIXTURE)
    CHANGES["roster.C"](raw)
    CHANGES["max_weekly_adds"](raw)
    with pytest.raises(ys.SettingsDrift) as e:
        ys.check(raw)
    assert "roster.C" in str(e.value) and "max_weekly_adds" in str(e.value)


@pytest.mark.parametrize("key", ["max_weekly_adds", "uses_playoff", "stat_modifiers",
                                 "roster_positions", "waiver_time"])
def test_a_modelled_setting_missing_from_yahoo_raises(key):
    raw = copy.deepcopy(FIXTURE)
    del _st(raw)[key]
    with pytest.raises(ys.SettingMissing, match=key):
        ys.check(raw)


def test_a_missing_yahoo_max_adds_setting_raises():
    cfg = copy.deepcopy(CFG)
    del cfg["roster_moves"]["yahoo_max_adds_setting"]
    with pytest.raises(ys.SettingMissing, match="yahoo_max_adds_setting"):
        ys.check(FIXTURE, cfg)


@pytest.mark.parametrize("key", ["scoring_type", "uses_playoff", "waiver_time_days", "uses_faab",
                                 "can_trade_draft_picks", "trade_deadline", "stat_values"])
def test_a_missing_yahoo_settings_key_in_config_raises(key):
    cfg = copy.deepcopy(CFG)
    del cfg["yahoo_settings"][key]
    with pytest.raises(ys.SettingMissing, match=key):
        ys.check(FIXTURE, cfg)


def test_yahoo_shows_six_and_the_league_enforces_three_on_purpose():
    assert CFG["roster_moves"]["yahoo_max_adds_setting"] == 6
    assert CFG["league_structure"]["weekly_add_budget"] == 3
    assert "rule 7" in CFG["roster_moves"]["_yahoo_max_adds_comment"]


def test_the_fixture_holds_no_account_identifiers():
    text = json.dumps(FIXTURE).lower()
    for word in ("password", "edit_key", "sendbird", "iris", "invitation", "url", "league_key",
                 "logo", "draft_time"):
        assert word not in text, word
    assert set(_meta(FIXTURE)) == set(ys.SCRUB_META)
    assert set(_st(FIXTURE)) == set(ys.SCRUB_SETTINGS)


def test_scrub_keeps_only_the_compared_fields():
    raw = copy.deepcopy(FIXTURE)
    _meta(raw).update(password="hunter2", name="A League", url="https://x")
    _st(raw).update(sendbird_channel_url="abc", persistent_url="https://y")
    clean = ys.scrub(raw)
    assert "hunter2" not in json.dumps(clean) and "https" not in json.dumps(clean)
    assert ys.check(clean) == ys.check(FIXTURE)
