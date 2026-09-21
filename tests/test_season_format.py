"""The 2026-27 format change: three stages, three champions, uneven keepers.

Two league rules changed at once, and they fail in different ways:

  SCHEDULE   The season is now 15 regular-season weeks (5 meetings against
             each of 3 opponents), a six-week best-of-3 bracket in 16-21, and
             a two-week Cup in 22-23. The old engine assumed the postseason
             was always the last TWO weeks, which would have counted weeks
             16-21 as regular season -- inflating every record, every h2h
             series and the draft order that comes out of them.

  KEEPERS    Through 2026-27 everyone keeps the same number, so one scalar
             works. From 2027-28 the previous season's Cup winner keeps a
             sixth, so the count is per manager and round 10 of the draft has
             three picks in it instead of four. Every invariant written as
             "fillable spots minus keepers_per_team" is wrong from that point.
"""
import json
from pathlib import Path

import pytest

from modules.data_loader import (
    CURRENT_SEASON, LEAGUE_STRUCTURE, MANAGERS, PAYOUTS, POSTSEASON_FORMAT,
    REGULAR_SEASON_WEEKS, SEASON_STRUCTURE, TOTAL_ROUNDS, TOTAL_WEEKS,
    cup_winner, first_keeper_round, is_cup_week, is_playoff_week,
    is_postseason_week, is_regular_season_week, keeper_rules_for, keepers_for,
    live_picks_for, phase_for_week, regular_season_weeks_for, series_length,
    stage_rounds, stage_weeks, uses_three_stage_format,
)
import modules.data_loader as dl

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Which stage a week belongs to
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("week,stage", [
    (1, "regular_season"), (15, "regular_season"),
    (16, "playoffs"), (18, "playoffs"), (19, "playoffs"), (21, "playoffs"),
    (22, "cup"), (23, "cup"),
    (24, None), (0, None),
])
def test_phase_for_week_2026_27(week, stage):
    assert phase_for_week("2026-27", week) == stage


def test_week_16_is_not_regular_season_anymore():
    """The single most consequential line of the change.

    Under the old constant, weeks 16-21 were regular season. Six extra weeks
    of results would land in every W-L record, every head-to-head series and
    therefore in the draft order and the payouts.
    """
    assert is_regular_season_week("2026-27", 15)
    assert not is_regular_season_week("2026-27", 16)
    assert is_playoff_week("2026-27", 16)
    assert is_postseason_week("2026-27", 16)


def test_the_cup_is_postseason_not_regular_season():
    assert is_cup_week("2026-27", 22) and is_cup_week("2026-27", 23)
    assert not is_regular_season_week("2026-27", 22)
    assert is_postseason_week("2026-27", 23)
    assert not is_playoff_week("2026-27", 22), "the Cup is not the bracket"


def test_out_of_season_weeks_are_not_postseason():
    """`not is_regular_season_week` is not the same as "postseason"."""
    assert not is_regular_season_week("2026-27", 99)
    assert not is_postseason_week("2026-27", 99)
    assert phase_for_week("2026-27", 99) is None


# ---------------------------------------------------------------------------
# Old seasons must not be re-shaped by the new format
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("season,last_reg,bracket", [
    ("2017-18", 21, (22, 23)),
    ("2020-21", 16, (17, 18)),
    ("2021-22", 20, (21, 22)),
    ("2025-26", 21, (22, 23)),
])
def test_legacy_seasons_keep_their_two_week_bracket(season, last_reg, bracket):
    assert not uses_three_stage_format(season)
    assert stage_weeks(season, "regular_season") == (1, last_reg)
    assert stage_weeks(season, "playoffs") == bracket
    assert stage_weeks(season, "cup") is None, "there was no Cup before 2026-27"
    assert series_length(season) == 1, "old brackets were single games"


def test_2019_20_has_no_postseason_at_all():
    assert stage_weeks("2019-20", "playoffs") is None
    assert stage_weeks("2019-20", "cup") is None
    assert phase_for_week("2019-20", 20) is None


def test_future_seasons_inherit_the_new_shape_without_being_listed():
    """2027-28 is deliberately not in season_structure yet; it must still work."""
    assert "2027-28" not in SEASON_STRUCTURE
    assert uses_three_stage_format("2027-28")
    assert stage_weeks("2027-28", "regular_season") == (1, 15)
    assert stage_weeks("2027-28", "playoffs") == (16, 21)
    assert stage_weeks("2027-28", "cup") == (22, 23)


# ---------------------------------------------------------------------------
# Bracket shape
# ---------------------------------------------------------------------------

def test_playoff_series_are_best_of_three():
    assert series_length("2026-27", "playoffs") == 3
    rounds = {r["name"]: r["weeks"] for r in stage_rounds("2026-27", "playoffs")}
    assert rounds["Semifinals"] == (16, 18)
    assert rounds["Final"] == (19, 21)
    assert rounds["Third Place"] == (19, 21)
    for name, (first, last) in rounds.items():
        assert last - first + 1 == 3, f"{name} must span three weeks"


def test_every_week_of_a_series_is_played():
    """A 2-0 series still plays its third week, so the sim must not stop early."""
    assert POSTSEASON_FORMAT["stages"]["playoffs"]["all_weeks_played"] is True


def test_the_cup_is_single_games_not_series():
    assert series_length("2026-27", "cup") == 1
    rounds = {r["name"]: r["weeks"] for r in stage_rounds("2026-27", "cup")}
    assert rounds["Cup Semifinals"] == (22, 22)
    assert rounds["Cup Final"] == (23, 23)


def test_the_stages_tile_the_whole_season_with_no_gap_or_overlap():
    spans = [stage_weeks("2026-27", s)
             for s in ("regular_season", "playoffs", "cup")]
    assert spans[0][0] == 1
    for (a_first, a_last), (b_first, b_last) in zip(spans, spans[1:]):
        assert b_first == a_last + 1, f"gap or overlap between {a_last} and {b_first}"
    assert spans[-1][1] == SEASON_STRUCTURE["2026-27"]["total_weeks"]


def test_fifteen_regular_weeks_is_five_meetings_per_opponent():
    reg = POSTSEASON_FORMAT["stages"]["regular_season"]
    meetings = reg["meetings_per_opponent"]
    assert meetings % 2 == 1, "an even number of meetings lets a season series draw"
    assert meetings * (len(MANAGERS) - 1) == reg["weeks"][1] - reg["weeks"][0] + 1


# ---------------------------------------------------------------------------
# Keepers: uniform this season, asymmetric from 2027-28
# ---------------------------------------------------------------------------

def test_2026_27_is_the_last_uniform_keeper_year():
    assert keeper_rules_for("2026-27") == {"base": 6, "cup_winner_bonus": 0}
    assert set(keepers_for("2026-27").values()) == {6}
    assert set(live_picks_for("2026-27").values()) == {9}
    assert set(first_keeper_round("2026-27").values()) == {10}


def test_2027_28_gives_the_cup_winner_a_sixth_keeper(monkeypatch):
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2026-27", "Benton")

    keepers = dl.keepers_for("2027-28")
    live = dl.live_picks_for("2027-28")
    first = dl.first_keeper_round("2027-28")

    assert keepers["Benton"] == 6 and live["Benton"] == 9 and first["Benton"] == 10
    for m in MANAGERS:
        if m == "Benton":
            continue
        assert keepers[m] == 5 and live[m] == 10 and first[m] == 11

    assert sum(live.values()) == 39
    assert sum(keepers.values()) == 21
    assert sum(live.values()) + sum(keepers.values()) == TOTAL_ROUNDS * len(MANAGERS) == 60


def test_round_ten_holds_three_picks_not_four(monkeypatch):
    """The concrete consequence: one round of the 2027-28 board is short."""
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2026-27", "Garrett")
    live = dl.live_picks_for("2027-28")
    in_round_10 = [m for m in MANAGERS if live[m] >= 10]
    assert len(in_round_10) == 3
    assert "Garrett" not in in_round_10


def test_an_unrecorded_cup_winner_is_not_guessed():
    """Deliberate: one keeper visibly missing beats one silently misassigned.

    Handing the bonus to the wrong manager would quietly corrupt a draft
    order. Short totals show up immediately in build_draft_order's even/uneven
    check, which is exactly where a human should be asked.
    """
    assert cup_winner("2026-27") is None, (
        "the 2026-27 Cup has not been played yet; if this fails, record it and "
        "update this test")
    counts = keepers_for("2027-28")
    assert set(counts.values()) == {5}
    assert sum(counts.values()) == 20, "one short of 21 -- intentionally visible"


def test_the_bonus_follows_the_previous_seasons_cup(monkeypatch):
    """2027-28 keepers depend on the 2026-27 Cup, not the 2027-28 one."""
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2026-27", "Nick")
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2027-28", "Hayden")
    assert dl.keepers_for("2027-28")["Nick"] == 6
    assert dl.keepers_for("2027-28")["Hayden"] == 5


def test_keepers_always_occupy_the_last_rounds(monkeypatch):
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2026-27", "Hayden")
    for season in ("2026-27", "2027-28"):
        live = dl.live_picks_for(season)
        first = dl.first_keeper_round(season)
        for m in MANAGERS:
            assert first[m] == live[m] + 1
            assert TOTAL_ROUNDS - first[m] + 1 == dl.keepers_for(season, m)


# ---------------------------------------------------------------------------
# Config agrees with itself
# ---------------------------------------------------------------------------

def test_the_season_block_matches_the_format():
    reg = stage_weeks(CURRENT_SEASON, "regular_season")
    assert REGULAR_SEASON_WEEKS == reg[1]
    assert dl.PLAYOFF_START_WEEK == reg[1] + 1
    assert TOTAL_WEEKS == stage_weeks(CURRENT_SEASON, "cup")[1]
    assert regular_season_weeks_for(CURRENT_SEASON) == REGULAR_SEASON_WEEKS


def test_total_rounds_is_the_non_il_roster():
    assert TOTAL_ROUNDS == LEAGUE_STRUCTURE["roster_size"] - LEAGUE_STRUCTURE["il_slots"]
    assert (LEAGUE_STRUCTURE["starters"] + LEAGUE_STRUCTURE["bench"]
            + LEAGUE_STRUCTURE["il_slots"] == LEAGUE_STRUCTURE["roster_size"])


def test_payouts_are_recorded_and_internally_consistent():
    for key in ("league_champion", "playoff_champion", "cup_champion"):
        assert key in PAYOUTS, f"{key} payout missing from config"
    for key in ("league_champion", "playoff_champion"):
        entry = PAYOUTS[key]
        assert entry["total"] == entry["per_payer"] * 2, (
            f"{key}: two payers, so total must be twice per_payer")
    assert PAYOUTS["league_champion"]["total"] == 180
    assert PAYOUTS["playoff_champion"]["total"] == 90
    assert PAYOUTS["cup_champion"]["total"] == 0, "the Cup pays a keeper, not cash"
    assert "keeper" in PAYOUTS["cup_champion"]["prize"].lower()


def test_the_three_titles_each_name_the_stage_that_decides_them():
    stages = POSTSEASON_FORMAT["stages"]
    assert stages["regular_season"]["title_key"] == "league_champion"
    assert stages["playoffs"]["title_key"] == "playoff_champion"
    assert stages["cup"]["title_key"] == "cup_champion"
    for stage in stages.values():
        assert stage["title_key"] in PAYOUTS, (
            f"{stage['title_key']} has a title but no payout entry")


def test_config_is_the_only_place_the_week_numbers_live():
    """No module may hardcode the old boundary as a literal.

    The boundary moved once already and will move again; the point of
    season_structure is that it moves in one file.
    """
    import re
    bad = re.compile(r"week\s*[<>]=?\s*(21|22)\b|(21|22)\s*[<>]=?\s*week\b")
    offenders = []
    for d in ("modules", "scripts"):
        for f in sorted((PROJECT_ROOT / d).glob("*.py")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if bad.search(line):
                    offenders.append(f"{d}/{f.name}:{i}: {line.strip()}")
    assert offenders == [], (
        "hardcoded regular/playoff week boundary -- use is_regular_season_week "
        "or phase_for_week:\n  " + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# The integrity check actually catches a broken config
# ---------------------------------------------------------------------------

import copy
import importlib.util


@pytest.fixture(scope="module")
def verify():
    spec = importlib.util.spec_from_file_location(
        "verify_project_integrity",
        PROJECT_ROOT / "scripts" / "verify_project_integrity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cfg():
    return json.loads(
        (PROJECT_ROOT / "config" / "league_config.json").read_text(encoding="utf-8"))


def test_the_real_config_passes(verify, cfg):
    assert verify._check_season_format(cfg, []) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["season"].__setitem__("regular_season_weeks", 21),
     "regular_season_weeks"),
    (lambda c: c["season"].__setitem__("playoff_start_week", 22),
     "playoff_start_week"),
    (lambda c: c["season"].__setitem__("total_weeks", 21), "total_weeks"),
    (lambda c: c["postseason_format"]["stages"]["playoffs"].__setitem__("weeks", [18, 21]),
     "gap or overlap"),
    (lambda c: c["postseason_format"]["stages"]["regular_season"].__setitem__(
        "meetings_per_opponent", 4), "even"),
    (lambda c: c["league_structure"].__setitem__("total_rounds", 13), "total_rounds"),
    (lambda c: c["league_structure"].__setitem__("keepers_per_team", 5),
     "keepers_per_team"),
    (lambda c: c["league_structure"].__setitem__("total_draft_rounds", 10),
     "total_draft_rounds"),
    (lambda c: c["season_structure"]["2026-27"].__setitem__("regular_through", 21),
     "regular_through"),
    (lambda c: c["payouts"]["league_champion"].__setitem__("per_payer", 50),
     "per_payer"),
    (lambda c: c["keeper_rules"].pop("cup_winners"), "cup_winners"),
])
def test_a_broken_config_is_caught(verify, cfg, mutate, expect):
    """Each of these silently produces wrong output if it slips through."""
    broken = copy.deepcopy(cfg)
    mutate(broken)
    failures = verify._check_season_format(broken, [])
    assert any(expect in f for f in failures), (
        f"expected a failure mentioning {expect!r}, got {failures}")
