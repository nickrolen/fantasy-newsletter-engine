"""The games grid plays the IL slots the betting lines play (HANDOFF_WEEK2_GRID_
AND_RULINGS 2026-10-30, s.1).

schedule_strength never read data/IL_SLOTS.json. On the 10-26 build Garrett's
Cooper Flagg and Kon Knueppel and Hayden's Kawhi Leonard -- all three in IL
slots for week 2 -- were counted as healthy starters (Garrett 50 Starts,
Hayden 47) while the betting lines had them out all week. An IL slot is fixed
for the week, both directions (LEAGUE_RULES 2026-27 IL rule 5).
"""
from datetime import date
from pathlib import Path

import pytest

from modules import schedule_strength as ss
import il_state

ROOT = Path(__file__).resolve().parents[1]
MON, TUE = date(2026, 10, 26), date(2026, 10, 27)


def info(team, pos, proj):
    return {"nba_team": team, "positions": set(pos.split(",")), "proj_fppg": proj}


def test_an_il_occupant_contributes_no_game_and_his_day_goes_to_who_is_available():
    # Healthy, no override, in an IL slot: the case that broke.
    pinfo = ss.PlayerIndex({"Flagg": info("DAL", "SF", 40.0), "Bench Guy": info("DAL", "SF", 20.0)})
    for p in range(9):
        pinfo[f"Filler {p}"] = info("BOS", "PG,SG,SF,PF,C", 30.0)
    roster = ["Flagg", "Bench Guy"] + [f"Filler {p}" for p in range(9)]
    sched = {MON: {"DAL", "BOS"}, TUE: {"DAL"}}

    plain = ss.simulate_daily_lineups("Garrett", roster, pinfo, sched, {})
    masked = ss.simulate_daily_lineups("Garrett", roster, pinfo, sched, {}, il_slot={"Flagg"})

    row = {p["player"]: p for p in masked["player_breakdown"]}["Flagg"]
    assert (row["total_games"], row["healthy_games"], row["started_games"]) == (0, 0, 0)
    assert row["in_il_slot"] and row["injury_status"] == "IL slot (out all week)"
    before = {p["player"]: p for p in plain["player_breakdown"]}
    assert before["Flagg"]["started_games"] == 2 and before["Bench Guy"]["started_games"] == 1
    after = {p["player"]: p for p in masked["player_breakdown"]}
    assert after["Bench Guy"]["started_games"] == 2          # Monday's seat goes to him
    assert masked["total_games"] == plain["total_games"] - 2
    assert masked["healthy_games"] == plain["healthy_games"] - 2


def test_the_mask_holds_even_with_an_override_saying_he_returns():
    pinfo = ss.PlayerIndex({"Kawhi": info("LAC", "SF", 45.0)})
    r = ss.simulate_daily_lineups("Hayden", ["Kawhi"], pinfo, {MON: {"LAC"}, TUE: {"LAC"}},
                                  {"Kawhi": TUE}, il_slot={"Kawhi"})
    assert r["startable_games"] == 0 and r["total_games"] == 0


@pytest.fixture(scope="module")
def real():
    """The project's own inputs, report week 1, the IL slots the last sync wrote."""
    from modules.data_loader import load_all_data
    from modules.projections import load_all_team_projections
    from modules.roster_plan import for_run, week_rosters
    data = load_all_data(ROOT, current_week=1)
    data.il_slots = il_state.as_last_synced(2)
    up = ss.build_schedule_strength(data, 1)["upcoming_week"]
    teams = load_all_team_projections(data)
    week_teams, mask = week_rosters(for_run(data, teams, {}), teams, 2)
    return data, up, week_teams, mask or {}


def test_the_grid_and_the_betting_simulator_agree_on_who_can_play(real):
    data, up, week_teams, mask = real
    assert up["il_slots"] == {m: sorted(v) for m, v in sorted(mask.items()) if v}
    for m, md in up["managers"].items():
        grid_available = {p["player"] for p in md["player_breakdown"] if not p["in_il_slot"]}
        sim_available = set(week_teams[m].players) - set(mask.get(m, ()))
        assert grid_available == sim_available, m


def test_every_il_occupant_counts_zero_games_in_the_locked_week(real):
    data, up, _teams, mask = real
    assert any(mask.values()), "the last sync put nobody on IL: nothing to check"
    for m, names in mask.items():
        rows = {p["player"]: p for p in up["managers"][m]["player_breakdown"]}
        for n in names:
            assert (rows[n]["total_games"], rows[n]["healthy_games"],
                    rows[n]["started_games"]) == (0, 0, 0), (m, n)
