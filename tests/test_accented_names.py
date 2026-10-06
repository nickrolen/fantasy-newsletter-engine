"""Accented player names must resolve in EVERY consumer, not most of them.

PLAYERLIST keeps Yahoo's spelling. LINEUPS, PLAYERLOG and ROSTERS strip
diacritics on the way in, so every join from a roster into PLAYERLIST
compares two different strings for the same player.

This was "fixed" once. Three call sites were changed -- get_player_projection,
resolve_projection, player_card_builder -- and the rest were not. Five modules
went on missing, and the miss is silent: it falls through to a default and
publishes it as measured. Keepability scored Nikola Jokic, the highest
projected player in the league, at 0.0 projected FPPG and age 27, three days
before a keeper deadline.

So these tests are deliberately written against EVERY consumer and against the
real spreadsheet, not against a fixture. A fix that covers four of five fails
here.
"""
import importlib.util
import json

import pandas as pd
import pytest

from pathlib import Path

from modules.data_loader import PlayerIndex, normalize_player_name

PROJECT_ROOT = Path(__file__).parent.parent
PLAYERLIST = PROJECT_ROOT / "data" / "PLAYERLIST.xlsx"


def _accented():
    """The real accented names in the live PLAYERLIST."""
    frame = pd.read_excel(PLAYERLIST)
    return [n for n in frame["player_name"]
            if any(ord(c) > 127 for c in str(n))]


def _stripped(name):
    """What the roster files call this player."""
    import unicodedata
    return unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()


# ---------------------------------------------------------------------------
# The mapping itself
# ---------------------------------------------------------------------------

def test_lookups_match_across_spellings():
    index = PlayerIndex()
    index["Nikola Jokić"] = 61.51
    assert index.get("Nikola Jokic") == 61.51
    assert index["Nikola Jokic"] == 61.51
    assert "Nikola Jokic" in index


def test_keys_keep_the_original_spelling():
    """Anything that prints a key must still print what Yahoo wrote."""
    index = PlayerIndex({"Luka Dončić": 1})
    assert list(index.keys()) == ["Luka Dončić"]
    assert list(index.items()) == [("Luka Dončić", 1)]


def test_a_real_miss_still_misses():
    """Permissive about spelling, not about identity."""
    index = PlayerIndex({"Nikola Jokić": 1})
    assert index.get("Nikola Jovic") is None
    assert index.get("Nobody At All", "DEFAULT") == "DEFAULT"
    with pytest.raises(KeyError):
        index["Nobody At All"]


def test_it_behaves_like_a_dict_otherwise():
    index = PlayerIndex({"Jusuf Nurkić": 1})
    index.setdefault("Jusuf Nurkic", 99)          # resolves, does not overwrite
    assert index["Jusuf Nurkić"] == 1
    index.update({"Egor Dëmin": 2})
    assert index.get("Egor Demin") == 2
    del index["Egor Demin"]
    assert "Egor Dëmin" not in index
    assert len(index) == 1


# ---------------------------------------------------------------------------
# Every consumer, against the real spreadsheet
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def playerlist():
    if not PLAYERLIST.is_file():
        pytest.skip("PLAYERLIST.xlsx not present")
    return pd.read_excel(PLAYERLIST)


def test_the_live_playerlist_still_has_accented_names(playerlist):
    """If this ever fails the rest of the file proves nothing."""
    names = _accented()
    assert names, "no accented names in PLAYERLIST -- these tests are vacuous"


def test_schedule_strength_finds_them(playerlist):
    from modules.schedule_strength import build_player_info_map
    info = build_player_info_map(playerlist)
    for name in _accented():
        assert info.get(_stripped(name)) is not None, (
            f"schedule_strength drops {name}; his games are never counted")


def test_rumor_mill_ages_find_them(playerlist):
    from modules.rumor_mill_analyzer import load_player_ages

    class Stub:
        pass
    data = Stub()
    data.playerlist = playerlist
    ages = load_player_ages(data)
    for name in _accented():
        got = ages.get(_stripped(name))
        assert got is not None, f"rumor mill has no age for {name}"
        assert got != 26 or int(playerlist.loc[
            playerlist["player_name"] == name, "age"].iloc[0]) == 26, (
            f"{name} fell through to the default age of 26")


def test_the_formatter_projections_find_them():
    spec = importlib.util.spec_from_file_location(
        "format_stats_report", PROJECT_ROOT / "scripts" / "format_stats_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    projections = mod.load_player_projections(PROJECT_ROOT)
    if not projections:
        pytest.skip("projections could not be loaded")
    for name in _accented():
        assert projections.get(_stripped(name)) is not None, (
            f"the formatter has no projection for {name}")


def test_the_projection_lookup_finds_them(playerlist):
    from modules.data_loader import FantasyData, load_playerlist
    data = FantasyData(playerlist=load_playerlist(PLAYERLIST))
    for name in _accented():
        assert data.get_player_projection(_stripped(name)) is not None, (
            f"get_player_projection misses {name}")


# ---------------------------------------------------------------------------
# The guard against fixing this halfway again
# ---------------------------------------------------------------------------

CROSS_SOURCE_LOOKUPS = {
    "modules/keepability_v2.py":        ["player_info = PlayerIndex()"],
    "modules/schedule_strength.py":     ["info: dict[str, dict] = PlayerIndex()"],
    "modules/rumor_mill_analyzer.py":   ["ages = PlayerIndex()",
                                         "keepability_lookup = PlayerIndex()"],
    "modules/season_performers.py":     ["proj_lookup = PlayerIndex("],
    "modules/report_builder.py":        ["proj_by_player = PlayerIndex()",
                                         "injury_lookup = PlayerIndex()",
                                         "pl_lookup = PlayerIndex()",
                                         "player_season = PlayerIndex()"],
    "modules/fetch_injury_statuses.py": ["injury_statuses = PlayerIndex()"],
    "scripts/format_stats_report.py":   ["keeper_lookup = PlayerIndex()",
                                         "projections = PlayerIndex()"],
}


@pytest.mark.parametrize("path,expected", sorted(CROSS_SOURCE_LOOKUPS.items()))
def test_every_cross_source_lookup_is_accent_tolerant(path, expected):
    """Each of these joins PLAYERLIST against roster-sourced names.

    A plain dict here is the bug. Named one by one so that reverting any
    single site fails by name rather than hiding in an aggregate.
    """
    src = (PROJECT_ROOT / path).read_text(encoding="utf-8")
    for construction in expected:
        assert construction in src, (
            f"{path} no longer builds this lookup with PlayerIndex: "
            f"{construction!r}. A plain dict here silently drops every "
            f"accented name.")


# ---------------------------------------------------------------------------
# Yahoo renames players (2026-10-05)
# ---------------------------------------------------------------------------

def test_an_abbreviated_first_name_resolves():
    """Yahoo rewrote Shai Gilgeous-Alexander as "S. Gilgeous-Alexander".
    No projection changed, only the spelling, while all_drafts,
    HISTORICAL_PLAYERLOG, all_trades and the roster kept the old form."""
    index = PlayerIndex({"S. Gilgeous-Alexander": 46.12})
    assert index.get("Shai Gilgeous-Alexander") == 46.12
    assert index.get("S. Gilgeous-Alexander") == 46.12


def test_a_generational_suffix_resolves_either_way():
    assert PlayerIndex({"Bobby Portis Jr.": 26.69}).get("Bobby Portis") == 26.69
    assert PlayerIndex({"Bobby Portis": 26.69}).get("Bobby Portis Jr.") == 26.69
    assert PlayerIndex({"Jimmy Butler III": 1}).get("Jimmy Butler") == 1


def test_it_refuses_to_guess_between_two_players():
    """Jalen and Jaylen Williams reduce to the same initial form. A wrong
    projection on a real player is worse than a missing one."""
    index = PlayerIndex({"Jalen Williams": 1, "Jaylen Williams": 2})
    assert index.get("J. Williams") is None
    assert index.get("Jalen Williams") == 1
    assert index.get("Jaylen Williams") == 2


def test_a_single_word_name_does_not_match_everything():
    index = PlayerIndex({"Shai Gilgeous-Alexander": 46.12})
    assert index.get("Gilgeous-Alexander") is None


def test_the_live_lookup_resolves_both_spellings():
    from modules.data_loader import FantasyData, load_playerlist
    if not PLAYERLIST.is_file():
        pytest.skip("PLAYERLIST.xlsx not present")
    data = FantasyData(playerlist=load_playerlist(PLAYERLIST))
    for old_form in ("Shai Gilgeous-Alexander", "Bobby Portis"):
        assert data.get_player_projection(old_form) is not None, (
            f"{old_form} is how every other file in the project spells him")
    assert data.get_player_projection("Nobody At All") is None


def test_the_gate_reports_a_rename(tmp_path):
    """A rename looks like one player leaving and another arriving, which
    is why nothing flagged it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_playerlist", PROJECT_ROOT / "scripts" / "check_playerlist.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._without_suffix("Bobby Portis Jr.") == mod._without_suffix("Bobby Portis")
    assert (mod._last_name_with_initial("S. Gilgeous-Alexander")
            == mod._last_name_with_initial("Shai Gilgeous-Alexander"))


def test_free_agents_does_not_list_a_respelled_rostered_player():
    """Yahoo wrote 'S. Gilgeous-Alexander' (2026-10-05); rosters say 'Shai'.
    The old get_free_agents() compared normalised names and listed him."""
    import pandas as pd
    from modules.data_loader import free_agents
    pl = pd.DataFrame({"player_name": ["S. Gilgeous-Alexander", "Bobby Portis Jr.",
                                        "Nikola Jokic", "Josh Hart"]})
    rosters = {"Nick": ["Shai Gilgeous-Alexander", "Bobby Portis"], "Hayden": ["Nikola Jokic"]}
    assert free_agents(pl, rosters)["player_name"].tolist() == ["Josh Hart"]


def test_get_free_agents_takes_rosters_instead_of_reading_config():
    import pandas as pd
    from modules.data_loader import FantasyData
    fd = FantasyData.__new__(FantasyData)
    fd.playerlist = pd.DataFrame({"player_name": ["A", "B"]})
    assert fd.get_free_agents(rosters={"Nick": ["A"]})["player_name"].tolist() == ["B"]
