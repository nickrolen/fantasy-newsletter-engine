"""Greedy lineup assignment: eligibility, preference, negative-FP regression."""
from modules.lineup_optimizer import AvailablePlayer, optimize_lineup


def _p(name, positions, fp):
    return AvailablePlayer(name=name, positions=positions, projected_fp=fp)


def test_fills_slots_respecting_eligibility():
    players = [
        _p("PointGod", ["PG"], 40), _p("Shooter", ["SG"], 35),
        _p("Wing", ["SF"], 30), _p("Big", ["PF"], 28), _p("Center", ["C"], 45),
        _p("Combo", ["PG", "SG"], 25), _p("Forward2", ["SF", "PF"], 22),
        _p("Util1", ["SG", "SF"], 20), _p("Util2", ["PF", "C"], 18),
        _p("Util3", ["PG"], 15),
    ]
    result = optimize_lineup(players)
    started = {s.player_name for s in result.starters}
    assert "Center" in started and "PointGod" in started
    assert result.num_starters == 10
    assert result.unfilled_slots == []


def test_higher_fp_wins_contested_slot():
    players = [_p("Star", ["C"], 60), _p("Backup", ["C"], 20)]
    result = optimize_lineup(players, slots=["C"])
    assert [s.player_name for s in result.starters] == ["Star"]
    assert result.bench == ["Backup"]


def test_negative_fp_player_still_assigned():
    # Regression: the old best_fp = -1 sentinel silently refused to seat
    # players with negative projected/actual FP, dropping them from
    # reconstructed lineups.
    players = [_p("RoughNight", ["C"], -2.0)]
    result = optimize_lineup(players, slots=["C"])
    assert [s.player_name for s in result.starters] == ["RoughNight"]
