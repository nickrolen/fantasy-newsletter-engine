"""The newsletter's betting table reads each number from the END of its part,
so a team name with digits ("Blink-183") never leaks into the table (week-3
issue, 11-09: Blink-183's moneyline printed as -183 and its average as 183)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import newsletter_html_generator as g  # noqa: E402

LINES = [
    "*Line: Blink-183 -121.5 (Big Nik Energy +121.5) | O/U: 3140*",
    "*Win Prob: Big Nik Energy 30.18% | Blink-183 69.82%*",
    "*Moneyline: Big Nik Energy +230 | Blink-183 -230*",
    "*Avg Score: Big Nik Energy 1509.89 | Blink-183 1631.56*",
]


def _data(lines):
    return g.parse_all_betting_lines([g.parse_betting_line(x) for x in lines])


def test_a_team_name_with_digits_never_becomes_a_number():
    d = _data(LINES)
    assert (d["ml_1"], d["ml_2"]) == ("+230", "-230")
    assert (d["ml_team1"], d["ml_team2"]) == ("Big Nik Energy", "Blink-183")
    assert (d["avg_1"], d["avg_2"]) == ("1509.89", "1631.56")
    assert d["avg_team2"] == "Blink-183"
    assert (d["win_prob_1"], d["win_prob_2"]) == ("30.18%", "69.82%")
    assert d["prob_team2"] == "Blink-183"
    assert d["team1_spread"] == ("Blink-183", "-121.5")


def test_the_digit_team_first_too():
    d = _data(["*Moneyline: Blink-183 -230 | Big Nik Energy +230*",
               "*Avg Score: Blink-183 1631.56 | Big Nik Energy 1509.89*"])
    assert (d["ml_1"], d["ml_team1"]) == ("-230", "Blink-183")
    assert (d["avg_1"], d["avg_team1"]) == ("1631.56", "Blink-183")


def test_the_table_prints_the_real_numbers():
    html = g.build_betting_table_from_data(_data(LINES), "Big Nik Energy", "Blink-183")
    assert "-230" in html and "1631.56" in html
    assert ">-183<" not in html and ">183<" not in html
