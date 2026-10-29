"""One clinch rule (HANDOFF_ONE_CLINCH_RULE_2026-10-28).

Clinch and elimination -- the title, and safe from / certain to pay into the
league pot -- are decided in ONE place: season_sim.regular_season_exact, a
max-flow over the actual remaining pairings. angles.decided_status and
marginal_value.title_eliminated call it; the per-rival and leader-only bounds
they used to carry are gone. The season-over path still settles on
final_order (the tiebreaks).
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from modules import angles as A  # noqa: E402
from modules import marginal_value as mv  # noqa: E402
from modules import season_sim as ss  # noqa: E402
from modules.data_loader import Record  # noqa: E402
from modules.standing_threads import money_events  # noqa: E402


def _game(w, a, b, winner=None):
    sa, sb = (1500.0, 1500.0) if winner is None else (
        (1600.0, 1400.0) if winner == a else (1400.0, 1600.0))
    return {"season": "x", "week": w, "manager_a": a, "manager_b": b,
            "score_a": sa, "score_b": sb}


def _pairs(w, *pairs):
    return [{"week": w, "manager_a": a, "manager_b": b} for a, b in pairs]


# After week 4: Nick 3-1, Hayden 3-1, Benton 1-3, Garrett 1-3. Weeks 5-6 are
# Nick v Hayden and Benton v Garrett. Benton's best is 3; one of Nick and
# Hayden reaches 4 because they play each other. The per-rival bound (Nick's
# 3 > Benton's best 3? no) and the leader-only bound (1 + 2 < 3? no) both
# called him alive.
FOUR = [_game(1, "Nick", "Benton", "Nick"), _game(1, "Hayden", "Garrett", "Hayden"),
        _game(2, "Nick", "Garrett", "Nick"), _game(2, "Hayden", "Benton", "Hayden"),
        _game(3, "Nick", "Hayden", "Nick"), _game(3, "Benton", "Garrett", "Benton"),
        _game(4, "Nick", "Garrett", "Garrett"), _game(4, "Hayden", "Benton", "Hayden")]
LATER = _pairs(5, ("Nick", "Hayden"), ("Benton", "Garrett")) + \
    _pairs(6, ("Nick", "Hayden"), ("Benton", "Garrett"))


# 1 -- eliminated by the pairings, and the newsletter line fires
def test_a_rival_out_by_the_pairings_is_out_and_the_line_fires():
    recs = {"Nick": Record(3, 1), "Hayden": Record(3, 1), "Benton": Record(1, 3),
            "Garrett": Record(1, 3)}
    left = [("Nick", "Hayden"), ("Benton", "Garrett")] * 2
    assert recs["Benton"].standing + 2 >= max(r.standing for r in recs.values())  # the old bound: alive
    assert mv.title_eliminated(recs, left, "Benton")
    st = A.decided_status(FOUR, 4, 6, pairings=LATER)
    assert ("out_of_title", "Benton") in st
    assert ("out_of_title", "Benton") not in A.decided_status(FOUR, 3, 6, pairings=LATER)
    assert ("out_of_title", "Benton") in money_events(FOUR, 4, None, 6, LATER)
    from test_angles import HIST
    texts = [a.text for a in A.decided_angles(FOUR, 4, 6, HIST, LATER)]
    assert any(t.startswith("Benton can no longer win the regular season (weeks 1-6)")
               for t in texts), texts


# 2 -- the season-over path settles on final_order, and needs no pairings
def test_the_season_over_path_settles_on_final_order():
    sm = FOUR + [_game(5, "Nick", "Hayden", "Hayden"), _game(5, "Benton", "Garrett", "Benton"),
                 _game(6, "Nick", "Hayden", "Nick"), _game(6, "Benton", "Garrett", "Garrett")]
    order = A.final_order(sm, 6)
    st = A.decided_status(sm, 6, 6)                       # left == 0: no pairings asked for
    assert ("clinched_title", order[0]) in st
    assert {m for ev, m in st if ev == "out_of_title"} == set(order[1:])
    assert {m for ev, m in st if ev == "will_pay"} == set(order[2:])
    assert {m for ev, m in st if ev == "safe_from_paying"} == set(order[:2])


# 5 -- a tied week counts half, and here it decides the race
def test_a_tied_week_is_half_and_decides_whether_a_rival_can_catch_the_leader():
    """Weeks 1-3; week 4 is Nick v Garrett and Hayden v Benton. With week 1
    Nick v Hayden TIED, Nick has 2.5 and Hayden can reach 2.5: alive (the tie
    goes to the tiebreaks). Had Nick won week 1, Nick has 3 and Hayden's best
    is 2: out."""
    def season(week1_winner):
        return [_game(1, "Nick", "Hayden", week1_winner), _game(1, "Benton", "Garrett", "Benton"),
                _game(2, "Nick", "Benton", "Nick"), _game(2, "Hayden", "Garrett", "Hayden"),
                _game(3, "Nick", "Garrett", "Nick"), _game(3, "Hayden", "Benton", "Benton")]
    week4 = _pairs(4, ("Nick", "Garrett"), ("Hayden", "Benton"))
    tied = A.decided_status(season(None), 3, 4, pairings=week4)
    assert ("out_of_title", "Hayden") not in tied
    won = A.decided_status(season("Nick"), 3, 4, pairings=week4)
    assert ("out_of_title", "Hayden") in won
    recs, _h, _p = A._records(season(None), 3)
    assert recs["Nick"].standing == 2.5 and recs["Hayden"].standing == 1.5


# 3 -- nobody else decides clinch or elimination
EVENTS = {"clinched_title", "out_of_title", "safe_from_paying", "will_pay"}
EXACT = {"regular_season_exact", "races_exact"}


def _calls(fn) -> set:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            out.add(f.id if isinstance(f, ast.Name) else getattr(f, "attr", None))
    return out


def _emits_event(fn) -> bool:
    """A function that ADDS or APPENDS an (event, manager) tuple decides one."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in ("add", "append"):
            for arg in node.args:
                if isinstance(arg, ast.Tuple) and arg.elts:
                    for sub in ast.walk(arg.elts[0]):
                        if isinstance(sub, ast.Constant) and sub.value in EVENTS:
                            return True
    return False


def test_no_module_decides_clinch_or_elimination_but_through_the_one_function():
    import re
    offenders, deciders = [], []
    for path in sorted((ROOT / "modules").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if path.name == "season_sim.py":
                if fn.name in ("_fits_under", "_can_reach", "regular_season_exact"):
                    continue
            elif fn.name in ("_fits_under", "_can_reach"):
                offenders.append(f"{path.name}:{fn.name} (a second copy of the flow)")
                continue
            decides = re.search(r"clinch|eliminat", fn.name) or _emits_event(fn)
            if decides and path.name != "season_sim.py":
                deciders.append(f"{path.name}:{fn.name}")
                if not (_calls(fn) & EXACT):
                    offenders.append(f"{path.name}:{fn.name}")
    assert not offenders, offenders
    assert set(deciders) == {"angles.py:decided_status", "marginal_value.py:title_eliminated"}


def test_the_title_odds_readout_carries_the_pairings_the_check_reads():
    from test_season_sim import _world
    from modules.simulator_title_odds import title_readout
    data, teams = _world(recorded_through=8)
    sp = ss.run_season(data, num_simulations=50, seed=3, team_projections=teams,
                       through="regular")
    res = title_readout(sp)
    assert res.remaining_pairs == list(sp.remaining_pairs) and res.remaining_pairs
