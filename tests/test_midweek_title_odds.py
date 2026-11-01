"""Mid-week title odds equal the live line (step 1a; design s.4, invariant 7).

The season pass prices the week in progress as the banked points plus B2's
simulate_week_remainder, with the run's seed and n (modules/season_sim.py).
The live line (scripts/refresh_lines.py) prices the same week the same way.
Tests already covered week 1 complete and weeks 9, 16 and 23 at their start;
this is the mid-week as-of: real week-1 logs cut off after Thursday 10-22, so
Tuesday to Thursday are banked and Friday to Sunday are simulated. The pass's
week-1 score arrays must EQUAL the live line's, matchup by matchup, for the
same seed -- bit for bit, because both call the one keyed draw.
"""
import copy
import importlib
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from league_state import needs_state                       # noqa: E402

rl = importlib.import_module("refresh_lines")
CUT = date(2026, 10, 23)          # the first day NOT banked: 10-20..10-22 are in the logs
N = 1500


@needs_state("data/LINEUPS.xlsx", "data/PLAYERLOG.xlsx", "data/PLAYERLIST.xlsx",
             "config/RECORDS.json", "output/live_lines_week1.state.json",
             why="builds a mid-week as-of from the real week-1 logs")
def test_the_season_pass_prices_the_week_in_progress_as_the_live_line_does(monkeypatch):
    from modules import season_sim as ss
    from modules import simulator_betting as sb
    from modules.data_loader import MANAGERS, load_all_data
    from modules.fetch_injury_statuses import Tags

    data = load_all_data(ROOT, current_week=None)
    for name in ("lineups", "playerlog"):
        df = getattr(data, name)
        setattr(data, name, df[pd.to_datetime(df["date"]) < pd.Timestamp(CUT)].copy())
    data.records = copy.deepcopy(data.records)
    for m, entries in (data.records.get("weekly_scores") or {}).items():
        data.records["weekly_scores"][m] = [e for e in entries if int(e.get("week", 0)) != 1]
    data.current_week = 1

    # the live line, as refresh_lines.price prices it (dry: nothing written)
    p = rl.prepare(ROOT, 1, CUT, no_tags=True, dry_run=True, data=data,
                   assume_tags_since_week_start=True)
    assert p.state.completed and p.state.remaining, "not a mid-week as-of"
    live = sb.simulate_week_remainder(p.data, p.teams, p.entry, p.state, p.seed, N, p.live or None,
                                      p.anchors, il_mask=p.il_mask or None)

    # the season pass, same seed and n: catch its score matrices
    seen = {}
    real = ss.scores_at

    def spy(mats, i):
        seen.setdefault("mats", mats)
        return real(mats, i)
    monkeypatch.setattr(ss, "scores_at", spy)
    sp = ss.run_season(data, N, p.seed, injury_statuses=Tags.none(), through="regular")
    assert 1 in sp.in_progress and 1 not in sp.simulated_weeks
    assert sp.in_progress[1]["as_of"] == CUT.isoformat()
    assert sp.in_progress[1]["banked"] == dict(p.state.banked)

    week1 = seen["mats"][1]
    for m in MANAGERS:
        want = float(p.state.banked.get(m, 0.0)) + np.asarray(live.remaining[m]["score"], float)
        assert np.array_equal(week1[m], want), m
    # and so the matchup distributions -- what a line and a title race read
    for mu in p.entry["matchups"]:
        a, b = mu["manager_a"], mu["manager_b"]
        line = next(ln for ln in live.lines if {ln.manager_a, ln.manager_b} == {a, b})
        pa = float(np.mean(week1[line.manager_a] > week1[line.manager_b]))
        pt = float(np.mean(week1[line.manager_a] == week1[line.manager_b]))
        assert abs(100 * (pa + pt / 2) - line.win_prob_a) < 1e-9 or \
            abs(100 * pa - line.win_prob_a) < 1e-9, (a, b, pa, line.win_prob_a)
