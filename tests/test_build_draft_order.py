"""Tests for draft-order construction.

Two things here decide real outcomes -- draft position and, in this league,
payouts -- and both have already been gotten wrong once:

  * the order comes from REGULAR-season standings, not Yahoo's final rank,
    which folds in playoff results
  * ties break on regular-season head-to-head; the stored h2h_season includes
    playoff meetings, which turned a 4-3 series into a 4-4 tie
"""
import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_draft_order", PROJECT_ROOT / "scripts" / "build_draft_order.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _season(records_weeks, schedule_weeks, reg_weeks=4):
    return (
        {"weekly_scores": records_weeks},
        {"regular_season_weeks": reg_weeks, "weeks": schedule_weeks},
    )


@pytest.fixture
def mod():
    return _load()


def test_order_uses_regular_season_not_final_rank(mod):
    """A manager who wins the bracket must not climb the draft order for it."""
    # wk1-2 regular: Nick sweeps. wk3 playoff: Hayden wins.
    rec, sched = _season(
        {
            "Nick":   [{"week": 1, "score": 100}, {"week": 2, "score": 100}, {"week": 3, "score": 10}],
            "Hayden": [{"week": 1, "score": 10},  {"week": 2, "score": 10},  {"week": 3, "score": 100}],
        },
        [
            {"week": 1, "matchups": [{"manager_a": "Nick", "manager_b": "Hayden"}]},
            {"week": 2, "matchups": [{"manager_a": "Nick", "manager_b": "Hayden"}]},
            {"week": 3, "matchups": [{"manager_a": "Nick", "manager_b": "Hayden"}]},
        ],
        reg_weeks=2,
    )
    wl, pts, h2h, reg = mod.regular_season_results(rec, sched)
    assert reg == 2
    assert wl["Nick"] == [2, 0], "playoff week must not count toward standings"
    assert wl["Hayden"] == [0, 2]
    standings, _ = mod.rank_managers(wl, pts, h2h)
    assert standings[0] == "Nick"


def test_tie_breaks_on_regular_season_head_to_head(mod):
    """Benton 4-3 over Garrett must win the slot, not fall through to points."""
    weeks, scores_b, scores_g = [], [], []
    # 7 meetings: Benton wins 4, Garrett wins 3. Garrett scores more overall.
    results = [True, True, True, True, False, False, False]
    for i, benton_wins in enumerate(results, start=1):
        weeks.append({"week": i, "matchups": [{"manager_a": "Benton", "manager_b": "Garrett"}]})
        scores_b.append({"week": i, "score": 100 if benton_wins else 1})
        scores_g.append({"week": i, "score": 1 if benton_wins else 500})
    rec, sched = _season({"Benton": scores_b, "Garrett": scores_g}, weeks, reg_weeks=7)
    wl, pts, h2h, _ = mod.regular_season_results(rec, sched)
    assert wl["Benton"] == [4, 3] and wl["Garrett"] == [3, 4]
    standings, notes = mod.rank_managers(wl, pts, h2h)
    assert standings[0] == "Benton"
    assert pts["Garrett"] > pts["Benton"], "points favour Garrett, h2h must win"


def test_head_to_head_excludes_playoff_meetings(mod):
    """The extra playoff meeting is what created the phantom 4-4 tie."""
    weeks, sb, sg = [], [], []
    for i in range(1, 8):                       # 7 regular meetings, Benton 4-3
        b = i <= 4
        weeks.append({"week": i, "matchups": [{"manager_a": "Benton", "manager_b": "Garrett"}]})
        sb.append({"week": i, "score": 100 if b else 1})
        sg.append({"week": i, "score": 1 if b else 100})
    weeks.append({"week": 8, "matchups": [{"manager_a": "Benton", "manager_b": "Garrett"}]})
    sb.append({"week": 8, "score": 1});  sg.append({"week": 8, "score": 100})   # playoff
    rec, sched = _season({"Benton": sb, "Garrett": sg}, weeks, reg_weeks=7)
    _, _, h2h, _ = mod.regular_season_results(rec, sched)
    assert h2h["Benton"]["Garrett"] == 4
    assert h2h["Garrett"]["Benton"] == 3, "playoff meeting must be excluded"


def test_slot_order_is_reverse_standings(mod):
    wl = {"Nick": [17, 4], "Benton": [10, 11], "Garrett": [10, 11], "Hayden": [5, 16]}
    pts = {"Nick": 3.0, "Benton": 2.0, "Garrett": 2.5, "Hayden": 1.0}
    h2h = {"Benton": {"Garrett": 4}, "Garrett": {"Benton": 3}}
    from collections import defaultdict
    h = defaultdict(lambda: defaultdict(int))
    for k, v in h2h.items():
        for kk, vv in v.items():
            h[k][kk] = vv
    standings, _ = mod.rank_managers(wl, pts, h)
    assert standings == ["Nick", "Benton", "Garrett", "Hayden"]
    assert list(reversed(standings)) == ["Hayden", "Garrett", "Benton", "Nick"]


def test_real_trades_reconcile_to_even_totals(mod):
    """Every pick is owned by exactly one manager; the league gains none."""
    trades = json.loads((PROJECT_ROOT / "config" / "TRADES.json").read_text(encoding="utf-8"))
    owners = {k: v for k, v in trades["draft_pick_ownership"]["2026"].items()
              if not k.startswith("_")}
    managers = ["Nick", "Hayden", "Benton", "Garrett"]
    rounds = 9
    tally = {m: 0 for m in managers}
    for rnd in range(1, rounds + 1):
        for orig in managers:
            tally[owners.get(f"{rnd}_{orig}", orig)] += 1
    assert sum(tally.values()) == rounds * len(managers)
    # Net movement must sum to zero
    assert sum(v - rounds for v in tally.values()) == 0


def test_every_ownership_entry_matches_a_recorded_trade(mod):
    """draft_pick_ownership must not drift from the trade log."""
    trades = json.loads((PROJECT_ROOT / "config" / "TRADES.json").read_text(encoding="utf-8"))
    sent = set()
    for t in trades["trades"]:
        for side in ("side_a", "side_b"):
            for p in t[side].get("sent_picks", []):
                sent.add(p)
    # "2026 2nd (Nick)" -> ("2026", "2", "Nick")
    import re
    parsed = set()
    for s in sent:
        m = re.match(r"(\d{4})\s+(\d+)[a-z]{2}\s+\((\w+)\)", s)
        if m:
            parsed.add((m.group(1), m.group(2), m.group(3)))
    checked = 0
    for year, entries in trades["draft_pick_ownership"].items():
        if year.startswith("_") or not isinstance(entries, dict):
            continue          # "_note" lives at the top level, not inside a year
        for k in entries:
            if k.startswith("_"):
                continue
            checked += 1
            rnd, orig = k.split("_", 1)
            assert (year, rnd, orig) in parsed, (
                f"ownership entry {year} {k} has no matching sent_picks in the trade log")
    assert checked == len(parsed), (
        f"every traded pick must appear exactly once in ownership: "
        f"{checked} entries vs {len(parsed)} picks in the trade log")
    assert checked > 0


def test_uneven_pick_counts_are_detected_not_silently_reported(mod, capsys, monkeypatch):
    """Uneven counts mean the trade log is incomplete -- the script must say so.

    Roster is 17 with 2 IL, so 15 spots are filled by keepers plus the draft.
    With 6 keepers every manager drafts exactly 9. Any other total is a data
    problem, not a draft order, and must not be printed as if it were fine.
    """
    monkeypatch.setattr("sys.argv", ["b"])
    rc = mod.main()
    out = capsys.readouterr().out
    if "UNEVEN PICK COUNTS" in out:
        assert rc == 1, "uneven counts must be a failure exit, not a clean run"
        assert "missing" in out.lower()
    else:
        assert rc == 0
        # if it claims even, every manager really must be even
        import re
        for m, n in re.findall(r"^\s+(\w+)\s+(\d+)\s+\(even\)", out, re.M):
            assert int(n) == 9


def test_pick_counts_must_equal_fillable_spots_minus_keepers(mod):
    """The invariant itself: 17 - 2 IL - 6 keepers = 9 drafted picks each."""
    from modules.data_loader import LEAGUE_STRUCTURE as LS
    fillable = LS["roster_size"] - LS["il_slots"]
    assert fillable - LS["keepers_per_team"] == LS["total_draft_rounds"], (
        "roster math and total_draft_rounds disagree: "
        f"{LS['roster_size']} - {LS['il_slots']} - {LS['keepers_per_team']} "
        f"!= {LS['total_draft_rounds']}")
