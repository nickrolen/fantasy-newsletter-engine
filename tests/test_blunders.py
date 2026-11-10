"""
F2 (HANDOFF_MONDAY_FIXES_2026-11-09): blunders count rearrangements, through
one function (modules/blunders) on the exact fill (modules/lineup_fill).
"""

from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from modules import blunders as bl, lineup_fill       # noqa: E402


def rows(spec):
    """(name, slot, positions, fp or None, injured) -> Rows, as PLAYERLOG reads:
    fp None is no game; an injured row is a DNP."""
    out = []
    for name, slot, pos, fp, inj in spec:
        appeared = fp is not None and not inj
        out.append(bl.Row(name=name, slot=bl.norm_slot(slot), positions=bl.parse_positions(pos),
                          fp=fp if appeared else None, appeared=appeared))
    return out


# Nick, Fri 11-06 (LINEUPS / PLAYERLOG): Jalen Johnson started at PF and did
# not play; Derrick White (PG,SG) sat on the bench and scored 38.00.
NICK_1106 = [
    ("Luka Doncic", "PG", "PG,SG", 58.65, False),
    ("Dyson Daniels", "SG", "SG,SF", 48.20, False),
    ("Damian Lillard", "G", "PG", 27.15, False),
    ("Jaylen Brown", "SF", "SG,SF,PF", 32.95, False),
    ("Jalen Johnson", "PF", "SF,PF", 0.0, True),
    ("Domantas Sabonis", "F", "PF,C", 33.35, False),
    ("Donovan Clingan", "C", "C", 41.15, False),
    ("Evan Mobley", "C", "PF,C", 45.15, False),
    ("Tyler Herro", "Util", "PG,SG", 39.30, False),
    ("Trae Young", "Util", "PG", 29.80, False),
    ("Derrick White", "BN", "PG,SG", 38.00, False),
    ("Desmond Bane", "BN", "SG,SF", None, False),
    ("Miles Bridges", "BN", "PF", None, False),
    ("Karl-Anthony Towns", "BN", "PF,C", None, False),
    ("Julius Randle", "BN", "PF", None, False),
    ("Anthony Edwards", "IL", "PG,SG", 0.0, True),
    ("Paolo Banchero", "IL", "PF", None, False),
]

# Nick, Mon 11-02: the direct case -- Bridges (PF) straight into Johnson's PF.
NICK_1102 = [
    ("Luka Doncic", "PG", "PG,SG", 81.2, False),
    ("Desmond Bane", "SG", "SG,SF", 27.85, False),
    ("Damian Lillard", "G", "PG", 34.55, False),
    ("Jaylen Brown", "SF", "SG,SF,PF", 56.25, False),
    ("Jalen Johnson", "PF", "SF,PF", 0.0, True),
    ("Domantas Sabonis", "F", "PF,C", 19.7, False),
    ("Donovan Clingan", "C", "C", 53.3, False),
    ("Karl-Anthony Towns", "C", "PF,C", 33.3, False),
    ("Trae Young", "Util", "PG", 31.85, False),
    ("Evan Mobley", "Util", "PF,C", 35.55, False),
    ("Dyson Daniels", "BN", "SG,SF", 31.0, False),
    ("Tyler Herro", "BN", "PG,SG", 41.9, False),
    ("Julius Randle", "BN", "PF", 23.55, False),
    ("Derrick White", "BN", "PG,SG", 10.1, False),
    ("Miles Bridges", "BN", "PF", 48.45, False),
    ("Anthony Edwards", "IL", "PG,SG", 0.0, True),
    ("Paolo Banchero", "IL", "PF", 0.0, True),
]


def test_nicks_1106_is_one_blunder_of_38_points_by_a_reshuffle():
    d = bl.day("2026-11-06", rows(NICK_1106))
    assert (d.count, d.points) == (1, 38.00)
    b = d.blunders[0]
    assert (b.bench_player, b.available_slot, b.dnp_starter) == ("Derrick White", "PF", "Jalen Johnson")
    assert b.moves, "a reshuffle"
    # the moves end in Johnson's PF seat, and each move is legal for the mover
    pos = {n: bl.parse_positions(p) for n, _s, p, _f, _i in NICK_1106}
    elig = dict(lineup_fill.SEATS)
    assert b.moves[-1][2] == "PF"
    for who, _frm, to in b.moves:
        assert pos[who] & elig[to], (who, to)


def test_the_greedy_it_replaces_missed_it():
    """2f5db12's straight-into-a-slot greedy: White fits no open seat."""
    starters_open = [s for n, s, p, f, i in NICK_1106 if s not in ("BN", "IL", "IL+") and (f is None or i)]
    assert starters_open == ["PF"]
    assert not (bl.parse_positions("PG,SG") & dict(lineup_fill.SEATS)["PF"])


def test_the_direct_case_still_counts():
    d = bl.day("2026-11-02", rows(NICK_1102))
    assert d.count == 1
    b = d.blunders[0]
    assert (b.bench_player, b.bench_player_fp, b.available_slot, b.dnp_starter, b.moves) == \
        ("Miles Bridges", 48.45, "PF", "Jalen Johnson", ())


def test_no_double_counting_when_two_bench_players_could_use_one_seat():
    """One open seat; Bridges, Randle (both PF) and Herro (by a reshuffle)
    could each take it: one blunder, the highest scorer's points."""
    d = bl.day("2026-11-02", rows(NICK_1102))
    assert (d.count, d.points) == (1, 48.45)
    spec = [("A", "PG", "PG", 30.0, False), ("B", "SG", "SG", 30.0, False), ("C1", "G", "PG", 30.0, False),
            ("D", "SF", "SF", 30.0, False), ("E", "PF", "PF", None, False), ("F1", "F", "SF", 30.0, False),
            ("G1", "C", "C", 30.0, False), ("H", "C", "C", 30.0, False), ("I", "Util", "C", 30.0, False),
            ("J", "Util", "C", 30.0, False),
            ("X", "BN", "PF", 20.0, False), ("Y", "BN", "PF", 25.0, False)]
    d = bl.day("d", rows(spec))
    assert (d.count, d.points, d.blunders[0].bench_player) == (1, 25.0, "Y")


def test_a_day_where_no_rearrangement_helps_is_zero():
    """C is open (its starter DNP); the bench player is a PG, and no starter
    who played can move to C to free a seat he fits."""
    spec = [("A", "PG", "PG", 30.0, False), ("B", "SG", "SG", 30.0, False), ("C1", "G", "PG,SG", 30.0, False),
            ("D", "SF", "SF", 30.0, False), ("E", "PF", "PF", 30.0, False), ("F1", "F", "SF,PF", 30.0, False),
            ("G1", "C", "C", 0.0, True), ("H", "C", "C", 30.0, False), ("I", "Util", "PG", 30.0, False),
            ("J", "Util", "SG", 30.0, False),
            ("K", "BN", "PG", 40.0, False)]
    assert bl.day("d", rows(spec)).count == 0


def test_il_slots_never_count():
    """A player in an IL slot who scored is no blunder, and an IL slot is no
    seat: an open starter seat alone makes the blunder."""
    base = [(n, s, p, f, i) for n, s, p, f, i in NICK_1106 if n != "Derrick White"]
    il_scorer = base + [("Derrick White", "IL", "PG,SG", 38.0, False)]
    assert bl.day("d", rows(il_scorer)).count == 0
    il_plus = base + [("Derrick White", "IL+", "PG,SG", 38.0, False)]
    assert bl.day("d", rows(il_plus)).count == 0


def test_a_bench_player_with_no_points_or_injured_is_no_blunder_and_a_zero_point_starter_holds_his_seat():
    spec = [r for r in NICK_1106 if r[0] != "Derrick White"]
    assert bl.day("d", rows(spec + [("Derrick White", "BN", "PG,SG", 0.0, False)])).count == 0
    assert bl.day("d", rows(spec + [("Derrick White", "BN", "PG,SG", 0.0, True)])).count == 0
    # Johnson played and scored 0: he held PF, so White is not a blunder
    played = [(n, s, p, (0.0 if n == "Jalen Johnson" else f), (False if n == "Jalen Johnson" else i))
              for n, s, p, f, i in NICK_1106]
    assert bl.day("d", rows(played)).count == 0


def test_points_are_the_best_total_keeping_the_starters_who_played_minus_the_actual():
    """Never a swap gain: a bench player outscoring a starter who played is
    the what-if's swap, not a blunder point."""
    d = bl.day("d", rows(NICK_1106))
    played = [(n, bl.parse_positions(p), f) for n, s, p, f, i in NICK_1106
              if s not in ("IL", "IL+") and f and not i and f > 0]
    assert lineup_fill.max_starters([p for _n, p, _f in played]) - 9 == d.count
    # a bench star beside a weak starter who played: still no blunder points
    swap = [(n, s, p, (5.0 if n == "Trae Young" else f), i) for n, s, p, f, i in NICK_1106] \
        + [("Star", "BN", "PG", 70.0, False)]
    d2 = bl.day("d", rows(swap))
    assert d2.count == 1 and d2.points == 70.0          # the Star takes the one open seat by a reshuffle,
    assert all(b.bench_player != "Trae Young" for b in d2.blunders)   # nobody who played is benched


def test_bad_input_raises():
    spec = [("A", "C", "C", 30.0, False), ("B", "C", "C", 30.0, False), ("C3", "C", "C", 30.0, False)]
    with pytest.raises(bl.BlunderInputError, match="more starters who played at C"):
        bl.day("d", rows(spec))
    with pytest.raises(bl.BlunderInputError, match="unknown lineup slot"):
        bl.norm_slot("DH")
    with pytest.raises(bl.BlunderInputError, match="missing"):
        bl._fp(float("nan"), "A", "d")


def test_a_stale_position_listing_takes_the_seat_yahoo_gave_him():
    """Garrett 2025-11-17: Cooper Flagg listed PG,SG, seated at SF."""
    spec = [("Flagg", "SF", "PG,SG", 18.0, False), ("X", "BN", "SF", 20.0, False)]
    d = bl.day("d", rows(spec))
    assert d.stale_positions == ["Flagg"]


def test_exact_fill_start_keeps_the_start_and_is_unchanged_without_one():
    players = [("a", frozenset({"PF"}), 1.0), ("b", frozenset({"SF", "PF"}), 5.0),
               ("c", frozenset({"PG"}), 3.0)]
    assert lineup_fill.exact_fill(players)[0] == ["b", "c", "a"]
    pf = next(i for i, (n, _e) in enumerate(lineup_fill.SEATS) if n == "PF")
    started, benched, assign = lineup_fill.exact_fill(players, start={pf: 0})
    assert "a" in started and set(started) == {"a", "b", "c"}
    with pytest.raises(ValueError, match="not eligible"):
        lineup_fill.exact_fill(players, start={pf: 2})
    with pytest.raises(ValueError, match="twice"):
        lineup_fill.exact_fill(players, start={pf: 0, pf + 1: 0})


# =============================================================================
# every caller uses the one function
# =============================================================================

def test_every_caller_uses_the_one_function():
    import update_leaguehistory as ulh
    from modules import what_if_analyzer as wia, report_builder as rb
    src = inspect.getsource(ulh.compute_weekly_blunders_from_lineups)
    assert "bl.week_from_frames" in src and "bl.counts" in src
    assert not hasattr(ulh, "_can_fill_slot") and not hasattr(ulh, "SLOT_POSITIONS")
    daily = inspect.getsource(wia.analyze_daily_what_if)
    assert "bl.day(" in daily and "Blunder(" not in daily
    assert wia.Blunder is bl.Blunder
    # RECORDS' cumulative blunders are the what-if's counts
    rsrc = inspect.getsource(rb)
    assert re.search(r"m: a\.total_blunders for m, a in what_if\.manager_analysis\.items\(\)", rsrc)
    # nothing else builds a Blunder or matches bench players into seats for one
    for path in list((ROOT / "modules").glob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        if path.name == "blunders.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "Blunder(" not in text, path.name
        assert "compute_weekly_blunders" not in text or path.name == "update_leaguehistory.py", path.name


def test_the_recompute_reads_the_one_function():
    import recompute_blunders as rcb
    assert "bl.week_from_frames" in inspect.getsource(rcb.weekly)


def test_recompute_sets_never_adds_and_a_second_apply_changes_nothing(tmp_path, monkeypatch):
    import recompute_blunders as rcb
    from openpyxl import Workbook
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    wb = Workbook()
    ws = wb.active
    ws.append(["manager_name", "total_points_current_season", rcb.COLUMN])
    for m, v in (("Nick", 1), ("Hayden", 1), ("Benton", 0), ("Garrett", 0)):
        ws.append([m, 100.0, v])
    wb.save(tmp_path / rcb.LEAGUEHISTORY)
    (tmp_path / rcb.LEDGER).write_text(json.dumps({"2026-2027": {"applied_weeks": [1, 2, 3]}}))
    (tmp_path / rcb.RECORDS).write_text(json.dumps({
        "last_history_week": 3, "cumulative_blunders": {"Nick": 1, "Hayden": 0, "Benton": 0, "Garrett": 0},
        "single_week_blunders_high": {"Nick": {"count": 1, "week": 3}}, "other": {"kept": True}}))

    def fake_weekly(base, season, weeks):
        d3 = bl.day("2026-11-06", rows(NICK_1106))
        d2 = bl.day("2026-11-02", rows(NICK_1102))
        return {w: ({"Nick": [d2, d3]} if w == 3 else {}) for w in weeks}

    monkeypatch.setattr(rcb, "weekly", fake_weekly)
    monkeypatch.setattr("modules.data_loader.CURRENT_SEASON_LONG", "2026-2027")
    assert rcb.main(["--base-path", str(tmp_path)]) == 0                  # report only
    assert json.loads((tmp_path / rcb.RECORDS).read_text())["cumulative_blunders"]["Nick"] == 1
    assert rcb.main(["--base-path", str(tmp_path), "--apply"]) == 0
    rec = json.loads((tmp_path / rcb.RECORDS).read_text())
    assert rec["cumulative_blunders"] == {"Nick": 2, "Hayden": 0, "Benton": 0, "Garrett": 0}
    assert rec["single_week_blunders_high"]["Nick"] == {"count": 2, "week": 3}
    assert rec["other"] == {"kept": True}
    lh = pd.read_excel(tmp_path / rcb.LEAGUEHISTORY)
    assert dict(zip(lh["manager_name"], lh[rcb.COLUMN])) == {"Nick": 2, "Hayden": 0, "Benton": 0, "Garrett": 0}
    assert list(lh["total_points_current_season"]) == [100.0] * 4
    before = ((tmp_path / rcb.RECORDS).read_bytes(), (tmp_path / rcb.LEAGUEHISTORY).read_bytes())
    p = rcb.plan(tmp_path)
    assert rcb.apply(tmp_path, p) == []
    assert ((tmp_path / rcb.RECORDS).read_bytes(), (tmp_path / rcb.LEAGUEHISTORY).read_bytes()) == before


# =============================================================================
# on the real files (league state; skipped where it isn't)
# =============================================================================

def _real_week(week):
    lu, pl = ROOT / "data" / "LINEUPS.xlsx", ROOT / "data" / "PLAYERLOG.xlsx"
    if not (lu.is_file() and pl.is_file()):
        pytest.skip("no league state here")
    import update_leaguehistory as ulh
    from modules.transaction_rulings import apply_effective_dates
    plog = apply_effective_dates(pd.read_excel(pl), ROOT, "playerlog")
    lus = apply_effective_dates(pd.read_excel(lu), ROOT, "lineups")
    if not ((lus["season_year"] == "2026-2027") & (lus["week"] == week)).any():
        pytest.skip(f"no week {week} here")
    return ulh.compute_weekly_blunders_from_lineups(lus, plog, "2026-2027", week)


def test_nicks_real_week_3_is_two():
    assert _real_week(3).get("Nick") == 2
