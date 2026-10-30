"""Step 5.75 (scripts/backfill_player_records.py) keeps what the record book
needs, every week.

On 2026-10-30 a run with week 1 in PLAYERLOG wrote config/RECORDS.json with
  - 40 manager-season entries stripped of reg_wins/reg_losses/reg_weeks, so
    they rendered "all games" next to scoped rows, and
  - Benton's 2023-24 8-game losing streak twice in longest_loss_streak_top10
    (he lost 8 straight twice that season), a record's slot lost.
Both would have recurred every week.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_player_records as b                       # noqa: E402
from modules.data_loader import CURRENT_SEASON, is_regular_season_week   # noqa: E402


def _recount():
    rows = json.loads((ROOT / "data" / "historical" / "all_matchups.json").read_text(
        encoding="utf-8"))
    out = {}
    for r in rows:
        if not is_regular_season_week(r["season"], r["week"]):
            continue
        for side in ("manager_a", "manager_b"):
            out.setdefault((r["season"], r[side]), {"reg_wins": 0, "reg_losses": 0,
                                                    "reg_weeks": 0})["reg_weeks"] += 1
        if r.get("winner"):
            out[(r["season"], r["winner"])]["reg_wins"] += 1
            out[(r["season"], r["loser"])]["reg_losses"] += 1
    return out


@pytest.fixture(scope="module")
def after_a_run(tmp_path_factory):
    """One real run on the project's own data (current-season PLAYERLOG
    included), against a RECORDS.json that already carries the competitive
    record on its season entries. Only the RECORDS path is redirected."""
    recount = _recount()
    seeded = [{"manager": m, "season": s, "wins": 0, "losses": 0, "total_fp": 0.0,
               "weeks": 0, "fppg_per_week": 0.0, **rec}
              for (s, m), rec in sorted(recount.items())]
    path = tmp_path_factory.mktemp("records") / "RECORDS.json"
    path.write_text(json.dumps({"all_time": {k: list(seeded) for k in b.SEASON_TOP10_KEYS},
                                "last_updated_week": 1}), encoding="utf-8")
    saved = b.RECORDS_FILE
    b.RECORDS_FILE = path
    try:
        b.main()
    finally:
        b.RECORDS_FILE = saved
    return json.loads(path.read_text(encoding="utf-8")), recount


def test_the_run_had_current_season_data(after_a_run):
    pl = b.load_current_playerlog()
    assert not pl.empty and pl["week"].max() >= 1, "no current-season PLAYERLOG to test against"


def test_a_run_keeps_the_competitive_record_on_every_season_entry(after_a_run):
    records, recount = after_a_run
    checked = 0
    for key in b.SEASON_TOP10_KEYS:
        entries = records["all_time"].get(key, [])
        assert entries, key
        for e in entries:
            tag = f"{key} {e['season']} {e['manager']}"
            assert all(f in e for f in b.COMPETITIVE_FIELDS), tag
            assert e["reg_weeks"] > 0, tag
            assert e["reg_wins"] <= e["wins"] and e["reg_losses"] <= e["losses"], tag
            want = recount.get((e["season"], e["manager"]))
            if want:
                assert {f: e[f] for f in b.COMPETITIVE_FIELDS} == want, tag
                checked += 1
    assert checked >= 40


def test_no_top10_holds_a_duplicate_after_a_run(after_a_run):
    records, _ = after_a_run
    for key, entries in records["all_time"].items():
        if key.endswith("_top10") and isinstance(entries, list):
            assert len(b.unique_entries(entries)) == len(entries), key
    loss = records["all_time"]["longest_loss_streak_top10"]
    assert len(loss) == 10
    assert sum(1 for e in loss if (e["manager"], e["season"], e["length"])
               == ("Benton", "2023-24", 8)) == 1


def test_two_equal_streaks_in_one_season_are_one_record_and_the_next_fills_the_slot():
    def mu(week, w, lo):
        return {"season": "2001-02", "week": week, "manager_a": w, "manager_b": lo,
                "winner": w, "loser": lo}
    ms = ([mu(1, "B", "A"), mu(2, "B", "A"), mu(3, "A", "B")]      # A: L L W
          + [mu(4, "B", "A"), mu(5, "B", "A")])                     # A: L L
    _, loss = b._compute_streaks(ms)
    assert loss == [{"length": 2, "manager": "A", "season": "2001-02"},
                    {"length": 1, "manager": "B", "season": "2001-02"}]


def test_the_current_season_record_comes_from_starter_totals_and_the_schedule():
    games = [{"season": CURRENT_SEASON, "manager": m, "week": 1, "fantasy_points": fp}
             for m, fp in (("Nick", 60.0), ("Nick", 40.0), ("Benton", 90.0),
                           ("Hayden", 50.0), ("Garrett", 50.0))]
    sched = {"weeks": [{"week": 1, "matchups": [{"manager_a": "Nick", "manager_b": "Benton"},
                                                {"manager_a": "Hayden", "manager_b": "Garrett"}]},
                       {"week": 2, "matchups": [{"manager_a": "Nick", "manager_b": "Hayden"}]}]}
    rec = b.current_season_record(games, sched, CURRENT_SEASON)
    assert rec["Nick"] == {"wins": 1, "losses": 0, "reg_wins": 1, "reg_losses": 0, "reg_weeks": 1}
    assert rec["Benton"]["losses"] == 1
    assert rec["Hayden"] == {"wins": 0, "losses": 0, "reg_wins": 0, "reg_losses": 0,
                             "reg_weeks": 1}                        # a tie
    assert all(r["reg_weeks"] == 1 for r in rec.values())           # week 2 not played yet


def test_a_damaged_write_is_refused_not_written():
    entry = {"manager": "Nick", "season": "2020-21", "wins": 10, "losses": 5, "weeks": 15}
    with pytest.raises(RuntimeError, match="no competitive record"):
        b.check_written_leaderboards({"best_manager_season_top10": [entry]})
    streak = {"length": 8, "manager": "Benton", "season": "2023-24"}
    with pytest.raises(RuntimeError, match="duplicate"):
        b.check_written_leaderboards({"longest_loss_streak_top10": [streak, dict(streak)]})


def test_career_baselines_are_the_ones_the_weekly_pipeline_derives(after_a_run):
    """report_builder._patch_cumulative_records derives the baseline as
    started AND had_game AND NOT is_injured. Counting only fp > 0 here wrote
    Vucevic 22,708.6 / 570 against 22,708.2 / 571 (one -0.4 game)."""
    records, _ = after_a_run
    from collections import defaultdict
    rows = json.loads((ROOT / "data" / "historical" / "HISTORICAL_PLAYERLOG.json").read_text(
        encoding="utf-8"))
    pure, by_mgr = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r.get("season_key") == CURRENT_SEASON:
            continue
        if not (r.get("started") and r.get("had_game")) or r.get("is_injured"):
            continue
        fp = float(r.get("fantasy_points") or 0.0)
        for store, key in ((pure, r["player_name"]), (by_mgr, (r["player_name"], r.get("manager", "")))):
            store[key][0] += fp
            store[key][1] += 1
    checked = 0
    for key, store, ident in (
            ("career_total_fp_top10", pure, lambda e: e["player_name"]),
            ("career_fppg_top10", pure, lambda e: e["player_name"]),
            ("career_total_fp_by_manager_top10", by_mgr, lambda e: (e["player_name"], e["manager"]))):
        for e in records["all_time"][key]:
            want = store.get(ident(e))
            if not want:
                continue
            checked += 1
            assert abs(e["historical_fp"] - want[0]) < 0.05 and e["historical_gp"] == want[1], (
                key, ident(e), e["historical_fp"], e["historical_gp"], round(want[0], 1), want[1])
    assert checked >= 20
