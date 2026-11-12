"""One chain per tag across a mid-week season pass (HANDOFF_CAUSAL_LEVERAGE_2026-11-12 s.3).

Before: a mid-week pass anchored every tag at the week in progress's first
day (resolved against the logs) and, in every later week, at NEXT week's first
day -- a whole new chain. A tag fetched Wednesday was charged on next week's
first games although its chain from Wednesday was mostly spent this week.
Now the pass anchors each tag where the live line did (week_state.reconcile_tags,
read from the line's state file: title_odds_run.line_anchors) and every later
week spends the same keyed chain (simulator_betting.TagChain).
"""
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from modules import season_sim as ss
from modules import simulator_betting as sb
from modules import simulator_playoff_odds as spo
from modules.data_loader import FantasyData
from modules.projections import PlayerProjection, TeamProjections

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from league_state import needs_state                      # noqa: E402

MON4 = date(2026, 11, 9)                                   # week 4: Mon 11-09 .. Sun 11-15
WED4, SAT4 = MON4 + timedelta(days=2), MON4 + timedelta(days=5)
MON5, WED5, FRI5 = MON4 + timedelta(days=7), MON4 + timedelta(days=9), MON4 + timedelta(days=11)


def _two_weeks():
    """His team (AAA) plays Wed and Sat of week 4, Mon, Wed and Fri of week 5.
    One manager, one player (82 GP: no untagged misses)."""
    weeks = [{"week": w, "start_date": (MON4 + timedelta(days=7 * (w - 4))).isoformat(),
              "end_date": (MON4 + timedelta(days=7 * (w - 4) + 6)).isoformat()} for w in (4, 5)]
    games = [{"date": d.isoformat(), "home": "AAA", "away": "BBB"} for d in (WED4, SAT4, MON5, WED5, FRI5)]
    data = FantasyData(schedule={"weeks": weeks}, nba_schedule={"games": games}, records={}, current_week=4)
    p = PlayerProjection(player_name="T", nba_team="AAA", positions=["PG"], projected_fppg=40.0,
                         projected_gp=82.0)
    tps = {"Nick": TeamProjections("Nick", {"T": p}, weekly_std_dev=1.0)}
    return data, tps, weeks


def test_a_wednesday_o_tag_is_one_chain_from_wednesday_never_three_more_next_week():
    data, tps, weeks = _two_weeks()
    n = 4000
    draws = sb.KeyedDraws(20261112, n)
    tags = {"T": "O"}
    chain = sb.TagChain(anchors={"T": WED4}, week_info=(4, sb.get_dates_in_week(weeks[0])),
                        observed={}, as_of=WED4)
    blk = sb.tag_blocks(data, tps, tags, draws, None, chain.anchors, chain.week_info, chain.observed,
                        chain.as_of)["T"]
    assert list(blk.games) == [WED4, SAT4, MON5]           # his first 3 games from Wednesday
    k = np.asarray(blk.k)
    assert k.min() >= 1 and k.max() <= 3                    # O: the first game is a certain miss

    def played(week_idx, **kw):
        res = sb.simulate_week_matrix(data, tps, weeks[week_idx], tags, draws, managers=["Nick"], **kw)
        return res["Nick"]["games"]

    healthy5 = sb.simulate_week_matrix(data, tps, weeks[1], {}, draws, managers=["Nick"])["Nick"]["games"]
    assert np.all(healthy5 == 3)
    # week 5 with the chain: only Monday can be missed, and only when the chain
    # runs its full 3 games (Wed, Sat, Mon) -- never Wednesday or Friday of week 5
    lost5 = healthy5 - played(1, tag_chain=chain)
    assert np.array_equal(lost5, (k == 3).astype(float))
    # week 4's remainder from Wednesday, the same chain: the rest of it
    lost4 = 2 - sb.simulate_week_matrix(data, tps, weeks[0], tags, draws, managers=["Nick"], from_date=WED4,
                                        anchors=chain.anchors, tag_week_info=chain.week_info,
                                        observed={})["Nick"]["games"]
    assert np.array_equal(lost4 + lost5, k.astype(float))   # charged once, at most 3, across the boundary
    # the old default anchored the tag at next week's first day: a whole new chain in week 5
    old5 = healthy5 - played(1)
    assert old5.min() >= 1 and old5.mean() > lost5.mean() + 0.9


def test_tag_chain_replaces_the_other_tag_arguments_never_both():
    data, tps, weeks = _two_weeks()
    chain = sb.TagChain(anchors={"T": WED4}, week_info=(4, sb.get_dates_in_week(weeks[0])), observed={},
                        as_of=WED4)
    with pytest.raises(ValueError, match="tag_chain replaces"):
        sb.simulate_week_matrix(data, tps, weeks[1], {"T": "O"}, sb.KeyedDraws(1, 10), managers=["Nick"],
                                tag_chain=chain, tag_anchor=WED4)


# =============================================================================
# the pass: the week in progress and the later weeks share the line's anchors
# =============================================================================

def _midweek(monkeypatch, recorded_through=8):
    import modules.week_state as wsm
    import test_season_sim as T
    monkeypatch.setattr(spo, "resolve_completed_week", lambda d, w: None)
    data, teams = T._world(recorded_through=recorded_through)
    data.current_week = recorded_through + 1
    w = data.current_week
    entry = next(e for e in data.schedule["weeks"] if e["week"] == w)
    d0 = date.fromisoformat(entry["start_date"])
    as_of = d0 + timedelta(days=3)
    monkeypatch.setattr(ss, "_as_of_for", lambda d, wk: as_of)
    monkeypatch.setattr(wsm, "week_state", lambda d, wk, a, tp=None: SimpleNamespace(
        banked={m: 300.0 for m in teams}, assumptions=("test",), remaining=[as_of], observed={},
        as_of=as_of))
    seen = {}

    def remainder(d, tp, entry, state, seed, n, statuses=None, anchors=None, il_mask=None):
        seen["anchors"] = anchors
        return SimpleNamespace(remaining={m: {"score": np.full(n, 1.0)} for m in teams})
    monkeypatch.setattr(sb, "simulate_week_remainder", remainder)
    real = sb.week_score_matrices

    def matrices(*a, **kw):
        seen["tag_chain"] = kw.get("tag_chain")
        return real(*a, **kw)
    monkeypatch.setattr(ss, "week_score_matrices", matrices)
    return data, teams, w, d0, as_of, seen


def test_a_midweek_pass_with_chain_tags_and_no_anchors_raises(monkeypatch):
    data, teams, w, d0, as_of, seen = _midweek(monkeypatch)
    with pytest.raises(ss.TagAnchorsMissing, match="in progress"):
        ss.run_season(data, num_simulations=20, seed=11, team_projections=teams,
                      injury_statuses={"Nick3": "O"}, through="regular")


@pytest.mark.parametrize("record, match", [({}, "has no anchor"), ({"Nick3": ("Q", None)}, "here but Q")])
def test_a_line_record_for_other_tags_raises(monkeypatch, record, match):
    data, teams, w, d0, as_of, seen = _midweek(monkeypatch)
    with pytest.raises(ss.TagAnchorsMissing, match=match):
        ss.run_season(data, num_simulations=20, seed=11, team_projections=teams,
                      injury_statuses={"Nick3": "O"}, through="regular", tag_anchors=record)


def test_a_midweek_pass_spends_the_lines_anchors_in_both_places(monkeypatch):
    data, teams, w, d0, as_of, seen = _midweek(monkeypatch)
    asked = []

    def record(week):
        asked.append(week)
        return {"Nick3": ("O", as_of), "Hayden5": ("Q", d0)}
    ss.run_season(data, num_simulations=20, seed=11, team_projections=teams,
                  injury_statuses={"Nick3": "O", "Hayden5": "Q"}, through="regular", tag_anchors=record)
    assert asked == [w]
    assert seen["anchors"] == {"Nick3": as_of, "Hayden5": d0}
    ch = seen["tag_chain"]
    assert ch.anchors == seen["anchors"] and ch.week_info[0] == w and ch.as_of == as_of


def test_without_tags_or_without_a_week_in_progress_nothing_is_read(monkeypatch):
    data, teams, w, d0, as_of, seen = _midweek(monkeypatch)

    def never(week):
        raise AssertionError("read")
    ss.run_season(data, num_simulations=20, seed=11, team_projections=teams, injury_statuses={},
                  through="regular", tag_anchors=never)
    assert seen["tag_chain"] is None and seen["anchors"] is None


def test_a_monday_fetch_prices_exactly_as_before():
    """No week in progress (the 12:01 AM Monday run): the pass is the one it
    always was, by hash -- 0eb18da9fa773399 is this fixture's pass at HEAD
    40b5454, before s.3 (computed 11-12 with HEAD's modules), with or without
    anchors offered."""
    import test_season_sim as T
    mp = pytest.MonkeyPatch()
    mp.setattr(spo, "resolve_completed_week", lambda d, w: None)
    try:
        for kw in ({}, {"tag_anchors": {}}):
            data, teams = T._world(recorded_through=8)
            sp = ss.run_season(data, num_simulations=300, seed=11, team_projections=teams,
                               injury_statuses={"Nick3": "O", "Hayden5": "Q", "Benton1": "D"},
                               through="playoffs", **kw)
            h = hashlib.sha256()
            for k in ("reg_finish", "reg_points", "playoff_finish"):
                h.update(np.ascontiguousarray(getattr(sp, k)).tobytes())
            for wk in sorted(sp.week_margins):
                h.update(np.nan_to_num(sp.week_margins[wk], nan=-1e9).tobytes())
            assert h.hexdigest()[:16] == "0eb18da9fa773399", kw
    finally:
        mp.undo()


# =============================================================================
# real data, unstubbed: the new run path
# =============================================================================

@needs_state("data/LINEUPS.xlsx", "data/PLAYERLOG.xlsx", "data/PLAYERLIST.xlsx", "config/RECORDS.json",
             "data/IL_SLOTS.json", "output/tag_records.jsonl", "output/stakes.json",
             why="the season pass on the real state, mid-week, against the real live line")
def test_the_real_midweek_pass_prices_its_week_as_the_live_line_does_with_tags():
    """Invariant 7 with tags: the pass's week in progress equals the live line
    (refresh_lines.prepare + simulate_week_remainder, dry), seed and n the
    same, bit for bit, now that both anchor each tag the same way."""
    import importlib
    import json
    from modules import tag_records, title_odds_run as tor
    from modules.data_loader import load_all_data
    from modules.season_sim import in_progress_weeks
    sys.path.insert(0, str(ROOT / "scripts"))
    rl = importlib.import_module("refresh_lines")
    data = load_all_data(ROOT, current_week=None)
    from modules.data_loader import regular_season_weeks_for, CURRENT_SEASON
    pend = in_progress_weeks(data, regular_season_weeks_for(CURRENT_SEASON))
    live_w = [w for w in pend if ss._as_of_for(data, w) <= date.fromisoformat(
        next(e for e in data.schedule["weeks"] if e["week"] == w)["end_date"][:10])]
    sf = ROOT / "output" / (f"live_lines_week{live_w[0]}.state.json" if live_w else "x")
    if not live_w or not sf.is_file():
        pytest.skip("no week in progress with a live line today")
    w = live_w[0]
    state = json.loads(sf.read_text(encoding="utf-8"))
    row = tag_records.latest(ROOT)
    tags = tag_records.as_tags(row)
    from modules import absence
    if not any(absence.chain_tag(t) for t in (state.get("tags") or {}).values() for t in [t["tag"]]):
        pytest.skip("no chain tags in this week's line")
    as_of = ss._as_of_for(data, w)
    if state.get("as_of") != as_of.isoformat():
        pytest.skip(f"the line is as of {state.get('as_of')}, the logs at {as_of}: not the same moment")
    n = 300
    sp = tor.run_pass(data, seed=int(state["seed"]), sims=n, statuses=tags, through="regular",
                      tag_anchors=tor.line_anchors(ROOT))
    p = rl.prepare(ROOT, w, as_of, seed=int(state["seed"]), statuses=tags, dry_run=True)
    assert {k: v for k, v in p.anchors.items()} == {k: v[1] for k, v in tor.line_anchors(ROOT)(w).items()
                                                     if absence.chain_tag(v[0])}
    rem = sb.simulate_week_remainder(p.data, p.teams, p.entry, p.state, p.seed, n, p.live or None,
                                     p.anchors, il_mask=p.il_mask or None,
                                     **({"nba_outs": p.nba_outs} if p.nba_outs else {}))
    for mu in p.entry["matchups"]:
        a, b = mu["manager_a"], mu["manager_b"]
        line = (p.state.banked[a] + rem.remaining[a]["score"]) - (p.state.banked[b] + rem.remaining[b]["score"])
        assert np.array_equal(sp.week_margins[w][:, sp.managers.index(a)], line), (a, b)
