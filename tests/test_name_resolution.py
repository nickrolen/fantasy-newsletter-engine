"""
One name resolver, used by the engine and by the gates that check its inputs.

STATUS_2026-10-12 sec.3 item 2 said check_playerlist was wrong to call Shai
Gilgeous-Alexander and Nickeil Alexander-Walker missing. Measured, it was the
only thing telling the truth: FantasyData.get_player_projection had the full
four-step ladder and returned 46.12 and 32.66, but the simulators never call
it. load_team_projections -> resolve_projection had its own copy that stopped
at step two, so both players projected 0.0 in every playoff, title and Cup
simulation. Two copies of one rule had drifted.

And the shared resolver had its own flaw: its initial step matched any two
names reducing to the same last name and first letter, so "Lonzo Ball" got
LaMelo Ball's projection (measured against the real PLAYERLIST, with Danny ->
Draymond Green, Justin -> Jrue Holiday, Thaddeus -> Trae Young).
"""

import re
from pathlib import Path

import pandas as pd
import pytest

from modules.data_loader import (
    FantasyData, PlayerIndex, UnknownTeam, MANAGER_TO_TEAM, initial_match,
    manager_for_team,
)

ROOT = Path(__file__).parent.parent

YAHOO = pd.DataFrame({
    "player_name": ["S. Gilgeous-Alexander", "N. Alexander-Walker", "LaMelo Ball",
                    "Draymond Green", "Jrue Holiday", "Trae Young",
                    "Nikola Jokić", "Bobby Portis Jr."],
    "player_nba_team": ["OKC", "ATL", "CHA", "GSW", "POR", "ATL", "DEN", "MIL"],
    "player_position(s)": ["PG,SG"] * 8,
    "player_total_proj_FP": [46.12 * 70, 32.66 * 70, 2800, 1900, 1800, 3300, 4366.9, 1500],
    "player_proj_GP": [70] * 8,
    "projectedFPPG": [46.12, 32.66, 40.0, 27.1, 25.7, 47.1, 61.51, 21.4],
})

SAME = [("Shai Gilgeous-Alexander", "S. Gilgeous-Alexander"),
        ("Nickeil Alexander-Walker", "N. Alexander-Walker"),
        ("Nikola Jokic", "Nikola Jokić"),
        ("Bobby Portis", "Bobby Portis Jr.")]
DIFFERENT = [("Lonzo Ball", "LaMelo Ball"), ("Danny Green", "Draymond Green"),
             ("Justin Holiday", "Jrue Holiday"), ("Thaddeus Young", "Trae Young")]


@pytest.mark.parametrize("roster,yahoo", SAME)
def test_the_resolver_finds_real_respellings(roster, yahoo):
    assert PlayerIndex({n: n for n in YAHOO["player_name"]}).get(roster) == yahoo


@pytest.mark.parametrize("roster,yahoo", DIFFERENT)
def test_the_resolver_does_not_hand_one_player_anothers_projection(roster, yahoo):
    assert PlayerIndex({n: n for n in YAHOO["player_name"]}).get(roster) is None
    assert not initial_match(roster, yahoo)


def _data():
    pl = YAHOO.copy()
    from modules.data_loader import normalize_player_name
    pl["_name_key"] = pl["player_name"].map(normalize_player_name)
    return FantasyData(playerlist=pl, injury_overrides={"players": []})


@pytest.mark.parametrize("roster,yahoo", SAME)
def test_the_simulators_see_the_same_projection_as_the_accessor(roster, yahoo):
    # load_team_projections looks each rostered name up exactly this way.
    from modules.projections import resolve_projection, load_player_projections
    data = _data()
    found = resolve_projection(load_player_projections(data), roster)
    expected = float(YAHOO.set_index("player_name").loc[yahoo, "projectedFPPG"])
    assert found is not None and found.projected_fppg == pytest.approx(expected)
    assert data.get_player_projection(roster) == pytest.approx(expected)


@pytest.mark.parametrize("roster,yahoo", DIFFERENT)
def test_neither_path_resolves_a_different_player(roster, yahoo):
    from modules.projections import resolve_projection, load_player_projections
    data = _data()
    assert resolve_projection(load_player_projections(data), roster) is None
    assert data.get_player_projection(roster) is None


def test_the_player_card_lookup_uses_the_resolver(tmp_path):
    from modules.player_card_builder import _load_playerlist
    YAHOO.to_excel(tmp_path / "PLAYERLIST.xlsx", index=False)
    pl = _load_playerlist(tmp_path)
    assert pl.get("Shai Gilgeous-Alexander")["projectedFPPG"] == 46.12
    assert pl.get("Lonzo Ball") is None


# ---------------------------------------------------------------------------
# No second copy of the ladder
# ---------------------------------------------------------------------------

# Files allowed to call normalize_player_name directly, and why. Anything new
# that joins one file's names into another's must go through PlayerIndex.
NORMALISE_ALLOWED = {
    "modules/data_loader.py": "defines the resolver",
    "scripts/fetch_playerlist.py": "keys basketball-reference ages, a source "
                                   "with its own spelling rules",
    "scripts/check_playerlist.py": "duplicate detection within one file, and "
                                   "the week-over-week join (renames are "
                                   "reported separately)",
}


def test_no_other_file_carries_its_own_name_matching():
    offenders = []
    for path in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in NORMALISE_ALLOWED:
            continue
        code = path.read_text(encoding="utf-8")
        if re.search(r"normalize_player_name\(", code):
            offenders.append(rel)
    assert not offenders, (
        f"{offenders} match player names with normalize_player_name, which "
        f"stops at accents. Use PlayerIndex (data_loader).")


# ---------------------------------------------------------------------------
# Team names: Benton renamed his team, and the ingest paths would have
# written every one of his rows under manager ""
# ---------------------------------------------------------------------------

def test_an_unknown_team_raises():
    with pytest.raises(UnknownTeam, match="manager_to_team"):
        manager_for_team("Smaxey")
    assert manager_for_team(MANAGER_TO_TEAM["Benton"]) == "Benton"


def test_team_names_are_unique():
    assert len(set(MANAGER_TO_TEAM.values())) == len(MANAGER_TO_TEAM)


def test_no_ingest_path_defaults_an_unknown_team_to_a_blank_manager():
    pattern = re.compile(r"TEAM_TO_MANAGER\.get\([^)]*\)")
    offenders = []
    for path in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{n}")
    assert not offenders, (
        f"{offenders}: TEAM_TO_MANAGER.get() turns a renamed team into a "
        f"blank manager. Use manager_for_team(), which raises.")
