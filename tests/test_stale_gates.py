"""Three gates that judged today against last week (HANDOFF_STALE_GATES_2026-10-26).

Each compared a CURRENT artifact against STALE state: check_playerlist's
roster coverage against last week's ROSTERS.json, its GP comparison across
the column's change of meaning at week 1, and check_rosters' IL count from
the last completed lineup. Plus the projection overrides that stop Yahoo's
broken rest-of-season rows valuing two rostered players at zero, and a
snapshot that was skipped exactly when the week was unusual.
"""
import importlib.util
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from modules import playerlist_freshness, projection_overrides
from modules.data_loader import DURABILITY_PRIOR, NBA_SCHEDULE_FILE

ROOT = Path(__file__).parent.parent
SNAP = ROOT / "config" / "snapshots"
COLUMNS = ["player_name", "player_nba_team", "player_position(s)",
           "player_total_proj_FP", "player_proj_GP", "projectedFPPG", "age"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, argv):
    old = sys.argv
    sys.argv = ["x", *argv]
    try:
        return mod.main()
    finally:
        sys.argv = old


@pytest.fixture
def check(tmp_path, monkeypatch):
    """check_playerlist in a throwaway tree with the real SCHEDULE, NBA
    schedule and durability prior, and no projection overrides."""
    mod = _load("check_playerlist")
    for rel in (DURABILITY_PRIOR["snapshot"], "config/SCHEDULE.json", NBA_SCHEDULE_FILE):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLAYERLIST", tmp_path / "data" / "PLAYERLIST.xlsx")
    monkeypatch.setattr(mod, "ROSTERS", tmp_path / "config" / "ROSTERS.json")
    monkeypatch.setattr(mod, "SNAPSHOTS", tmp_path / "snapshots")
    mod.PLAYERLIST.parent.mkdir(parents=True, exist_ok=True)
    mod.SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    return mod


def _frame(path):
    df = pd.read_excel(path)
    if "age" not in df.columns:
        df["age"] = 25
    return df[COLUMNS]


def _fetched(mod, frame, when, extra=None):
    """Write a PLAYERLIST the way fetch_playerlist does: data + _fetch stamp."""
    playerlist_freshness.write(frame, mod.PLAYERLIST, "yahoo:test", now=when, extra=extra)


def _rosters(mod, names, synced):
    mod.ROSTERS.write_text(json.dumps({"_last_sync": synced,
                                       "rosters": {"Nick": list(names)}}), encoding="utf-8")


def _in_season(frame, ceiling=77.2):
    """A pre-season frame reshaped the way Yahoo's GP column reads IN SEASON:
    games out of those REMAINING, marked down only for the known-hurt, so the
    pre-season durability haircut no longer shows. Synthesised rather than read
    from a snapshot: a test that names one week's file is the same
    judged-against-stale-state bug this module is about, and the file it used
    to name was removed on 10-27. Lands on the live 10-26 file's shape --
    median ~76, max ~77, ~90% within one game of the median.
    """
    out = frame.copy()
    pre = out["player_proj_GP"].astype(float)
    out["player_proj_GP"] = (ceiling - (pre.max() - pre) * 0.08).round(1)
    out["player_total_proj_FP"] = (out["projectedFPPG"].astype(float)
                                   * out["player_proj_GP"]).round(2)
    return out


def _shift(frame):
    """Stats moved one row against names: the misaligned-scrape signature."""
    out = frame.copy()
    cols = ["player_nba_team", "player_total_proj_FP", "player_proj_GP", "projectedFPPG"]
    out[cols] = out[cols].shift(1)
    return out.dropna(subset=["player_proj_GP"]).reset_index(drop=True)


# 1 -- the rosters must be synced for the week the PLAYERLIST was fetched in
def test_rosters_from_an_earlier_week_than_the_fetch_fail(check, capsys):
    frame = _frame(SNAP / "PLAYERLIST_2026-10-13.xlsx").head(30)
    _fetched(check, frame, datetime(2026, 10, 27, 10, 0))              # week 2
    # the real 10-26 case: ROSTERS.json from 10-19, the day before week 1
    _rosters(check, frame["player_name"].head(10), "2026-10-19T09:00:00")
    assert _run(check, []) == 1
    out = capsys.readouterr().out
    assert "judged against last week's rosters" in out and "before the season" in out
    # and a sync from inside week 1
    _rosters(check, frame["player_name"].head(10), "2026-10-22T09:00:00")
    assert _run(check, []) == 1
    out = capsys.readouterr().out
    assert "-- week 1 -- but this PLAYERLIST was fetched in week 2" in out


def test_rosters_synced_earlier_in_the_same_week_pass(check, capsys):
    """The correct order: Steps 3-4.5, THEN the fetch. ROSTERS is older than
    the fetch stamp and that is right -- which is why the guard is the
    fantasy week, not "not older than the stamp"."""
    frame = _frame(SNAP / "PLAYERLIST_2026-10-13.xlsx").head(30)
    _fetched(check, frame, datetime(2026, 10, 27, 10, 0))
    _rosters(check, frame["player_name"].head(10), "2026-10-27T08:00:00")
    _run(check, [])
    out = capsys.readouterr().out
    assert "judged against last" not in out
    assert "rosters synced 2026-10-27 08:00 (_last_sync), week 2; fetched in week 2" in out


# 2 -- the GP comparison compares like with like
def test_a_pre_season_baseline_against_an_in_season_file_is_said_not_failed(check, capsys):
    shutil.copy2(SNAP / "PLAYERLIST_2026-10-13.xlsx", check.SNAPSHOTS / "PLAYERLIST_2026-10-13.xlsx")
    _fetched(check, _in_season(_frame(SNAP / "PLAYERLIST_2026-10-13.xlsx")),
             datetime(2026, 10, 26, 17, 53))
    _run(check, [])
    out = capsys.readouterr().out
    assert "GP not compared" in out and "changed meaning at week 1" in out
    assert "signature of stats shifted" not in out


def test_a_one_row_shift_against_the_same_baseline_still_fails(check, capsys):
    shutil.copy2(SNAP / "PLAYERLIST_2026-10-05.xlsx", check.SNAPSHOTS / "PLAYERLIST_2026-10-05.xlsx")
    real = _frame(SNAP / "PLAYERLIST_2026-10-13.xlsx").sort_values(
        "player_total_proj_FP", ascending=False).reset_index(drop=True)
    _fetched(check, real, datetime(2026, 10, 13, 16, 0))           # Yahoo's real refresh
    _run(check, [])
    assert "signature of stats shifted" not in capsys.readouterr().out
    _fetched(check, _shift(real), datetime(2026, 10, 13, 16, 0))   # the same, shifted
    assert _run(check, []) == 1
    out = capsys.readouterr().out
    assert "signature of stats shifted" in out and "share of" in out


# 3 -- IL membership is today's, and the fallback says what it cannot see
def test_il_membership_comes_from_the_live_roster_and_the_fallback_names_itself():
    cr = _load("check_rosters")
    rosters = {"Garrett": ["Cooper Flagg", "Kon Knueppel", "Alex Sarr"],
               "Nick": ["Paolo Banchero", "Derrick White"]}
    live = {"Garrett": ["Cooper Flagg", "Kon Knueppel"], "Nick": ["Paolo Banchero"],
            "Hayden": ["Someone Else"]}
    counts, source = cr.players_on_il(rosters, live=live)
    assert counts == {"Garrett": 2, "Nick": 1} and source == "the live Yahoo roster"
    # the 10-26 case: the last lineup predates the IL moves
    lineups = pd.DataFrame([
        {"date": "2026-10-25", "manager": "Garrett", "player_name": "Cooper Flagg", "slot": "BN"},
        {"date": "2026-10-25", "manager": "Nick", "player_name": "Paolo Banchero", "slot": "PF"},
    ])
    counts, source = cr.players_on_il(rosters, lineups=lineups)
    assert counts == {"Garrett": 0, "Nick": 0}
    assert "latest lineup" in source and "2026-10-25" in source and "not seen" in source


def test_check_rosters_says_where_il_came_from(tmp_path, monkeypatch, capsys):
    cr = _load("check_rosters")
    monkeypatch.setattr(cr, "ROSTERS", tmp_path / "ROSTERS.json")
    monkeypatch.setattr(cr, "PLAYERLIST", tmp_path / "none.xlsx")
    monkeypatch.setattr(cr, "LINEUPS", tmp_path / "none.xlsx")
    names = {m: [f"{m} {i}" for i in range(15)] for m in ("Nick", "Hayden", "Benton", "Garrett")}
    names["Nick"].append("Paolo Banchero")
    cr.ROSTERS.write_text(json.dumps({"rosters": names}), encoding="utf-8")
    monkeypatch.setattr(cr, "live_il_names", lambda: {"Nick": ["Paolo Banchero"]})
    assert _run(cr, ["--strict"]) == 0                      # 15 + 1 on IL is right
    assert "IL membership from the live Yahoo roster" in capsys.readouterr().out

    def down():
        raise RuntimeError("league unreachable")
    monkeypatch.setattr(cr, "live_il_names", down)
    _run(cr, [])
    out = capsys.readouterr().out
    assert "the live roster was not reachable: RuntimeError: league unreachable" in out


# 4 -- an override past its review date fails; so does one Yahoo has moved on from
def _entry(**over):
    e = {"yahoo_id": "10592", "player_name": "Cameron Boozer",
         "set": {"projectedFPPG": 33.17, "player_proj_GP": "team"},
         "replaces": {"player_proj_GP": 0.0, "player_total_proj_FP": 0.0},
         "reason": "rest-of-season row is 0/0.00", "source": "S_PS7",
         "added": "2026-10-27", "review_by": "2026-11-03"}
    e.update(over)
    return e


def _records(boozer_gp=0.0, boozer_fp=0.0):
    rows = [("1", "Ty Jerome", "MEM", 76.2, 2590.8), ("2", "Zach Edey", "MEM", 76.2, 2198.4),
            ("3", "Jaylen Wells", "MEM", 74.0, 1696.8), ("10592", "Cameron Boozer", "MEM", boozer_gp, boozer_fp),
            ("4", "Domantas Sabonis", "SAC", 76.2, 3288.8)]
    return [{"_yahoo_id": i, "player_name": n, "player_nba_team": t, "player_proj_GP": g,
             "player_total_proj_FP": f, "projectedFPPG": round(f / g, 2) if g else 0.0}
            for i, n, t, g, f in rows]


def test_an_override_past_its_review_date_fails(tmp_path):
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"overrides": [_entry()]}), encoding="utf-8")
    entries = projection_overrides.load(path)
    applied, unapplied = projection_overrides.apply(_records(), entries)
    recorded = json.loads(projection_overrides.stamp_value(applied, unapplied))
    fails, warns, lines = projection_overrides.review(entries, recorded, date(2026, 11, 3))
    assert fails == [] and warns == [] and "Cameron Boozer: FPPG 0.00 -> 33.17" in lines[0]
    fails, _, _ = projection_overrides.review(entries, recorded, date(2026, 11, 4))
    assert len(fails) == 1 and "due for review on 2026-11-03" in fails[0]
    # Yahoo fixed the row upstream: still applied, but it must be looked at
    applied, unapplied = projection_overrides.apply(_records(70.0, 2100.0), entries)
    recorded = json.loads(projection_overrides.stamp_value(applied, unapplied))
    fails, _, _ = projection_overrides.review(entries, recorded, date(2026, 10, 28))
    assert len(fails) == 1 and "has changed since its override was written" in fails[0]


def test_a_malformed_override_raises_rather_than_loading_nothing(tmp_path):
    path = tmp_path / "o.json"
    for bad in (_entry(review_by="next week"), _entry(set={"player_total_proj_FP": 1}),
                {k: v for k, v in _entry().items() if k != "reason"}):
        path.write_text(json.dumps({"overrides": [bad]}), encoding="utf-8")
        with pytest.raises(projection_overrides.OverrideError):
            projection_overrides.load(path)


def test_an_override_is_not_applied_to_a_different_player_on_the_same_id():
    recs = _records()
    recs[3]["player_name"] = "Somebody Else"
    applied, unapplied = projection_overrides.apply(recs, [_entry()])
    assert applied == [] and "Somebody Else" in unapplied[0]["why"]
    assert recs[3]["projectedFPPG"] == 0.0


# 5 -- applied to the written PLAYERLIST, and it survives a refetch
def test_an_override_reaches_the_written_file_and_survives_a_refetch(tmp_path, monkeypatch, capsys):
    fp = _load("fetch_playerlist")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "PROJECTION_OVERRIDES.json").write_text(
        json.dumps({"overrides": [_entry()]}), encoding="utf-8")
    monkeypatch.setattr(fp, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fp, "ROSTERS", tmp_path / "none.json")

    def collect(league_id, status, limit, label):      # Yahoo, as it was on 10-26
        rows = {}
        for r in _records():
            rows[r["_yahoo_id"]] = {"yahoo_id": r["_yahoo_id"], "player_name": r["player_name"],
                                    "nba_team": r["player_nba_team"], "positions": "PF",
                                    "proj_gp": str(r["player_proj_GP"]),
                                    "total_fp": f"{r['player_total_proj_FP']:,.2f}",
                                    "owner": "Kevin Quran't" if status == "T" else None}
        return rows
    monkeypatch.setattr(fp, "collect", collect)
    out = tmp_path / "PL.xlsx"
    for _ in range(2):                                   # this week's fetch, then next week's
        assert _run(fp, ["--execute", "--out", str(out), "--no-bbref-ages", "--league-key", "478.l.16778"]) == 0
        df = pd.read_excel(out)
        b = df[df["player_name"] == "Cameron Boozer"].iloc[0]
        assert (b["projectedFPPG"], b["player_proj_GP"]) == (33.17, 76.2)    # "team": the MEM max
        assert b["player_total_proj_FP"] == pytest.approx(33.17 * 76.2, abs=0.01)
        rec = projection_overrides.from_stamp(playerlist_freshness.read_stamp(out))
        assert rec["applied"][0]["yahoo"]["player_proj_GP"] == 0.0           # upstream still recorded
    assert "Cameron Boozer: Yahoo 0 GP / 0.00 FPPG -> 76.2 GP / 33.17 FPPG" in capsys.readouterr().out


# 6 -- --snapshot records the week even when the gate fails
def test_snapshot_is_written_from_a_failing_file_and_the_exit_stays_non_zero(check, capsys):
    frame = _frame(SNAP / "PLAYERLIST_2026-10-13.xlsx")
    frame.loc[0, ["player_total_proj_FP", "player_proj_GP", "projectedFPPG"]] = 0.0   # Yahoo's zero row
    _fetched(check, frame, datetime.now())
    assert _run(check, ["--snapshot"]) == 1
    taken = check.SNAPSHOTS / f"PLAYERLIST_{date.today().isoformat()}.xlsx"
    assert taken.is_file()
    assert pd.read_excel(taken)["player_name"].tolist() == frame["player_name"].tolist()
    out = capsys.readouterr().out
    assert "SNAPSHOT TAKEN FROM A FILE THAT FAILED THE GATE" in out and "below 5.0 FPPG" in out
    assert out.index("Saved baseline") < out.index("RESULT: DO NOT")


# the order, and the dead-override message
def test_the_workflow_fetches_playerlist_after_the_roster_gate():
    doc = (ROOT / "WEEKLY_WORKFLOW.md").read_text(encoding="utf-8")
    quick = doc[doc.index("## Quick Reference"):]
    assert quick.index("check_rosters.py") < quick.index("fetch_playerlist.py --execute") \
        < quick.index("check_playerlist.py --snapshot")
    assert doc.index("## Step 4: Sync") < doc.index("## Step 4.75: Update PLAYERLIST") \
        < doc.index("## Step 5:")
    assert "## Step 2.5" not in doc


def test_an_unrostered_override_is_inert_not_dead_and_a_typo_is_still_a_typo(tmp_path):
    """Overrides describe injuries, not rosters (STATUS_2026-10-28). The 10-27
    check called Cason Wallace a DEAD ENTRY and said "Remove the entry"; that
    was the overruled theory. Now: a real NBA player on no roster is one
    inert line, a near miss is a typo, and the old text is gone."""
    from modules import nba_reference as nr
    ref = nr.Reference(tmp_path, cache={"fetched_at": "2026-10-28", "seasons": {
        "this_season": {"players": {"Cason Wallace": "OKC", "Derrick White": "BOS"}}}},
        playerlist={}, rostered=[])
    assert ref.resolve("Cason Wallace") and not ref.in_league_files("Cason Wallace")
    assert ref.resolve("Derik White") is None and ref.near("Derik White") == "Derrick White"
    assert "Probably a typo" in ref.unknown_message("Derik White")
    src = (ROOT / "scripts" / "verify_project_integrity.py").read_text(encoding="utf-8")
    assert "DEAD ENTRY" not in src and "Remove the entry" not in src


# 5 -- the shift check reads the NBA team, which the calendar does not move
# (HANDOFF two small fixes, 2026-10-28). Both files are real Yahoo fetches two
# days apart; the old in-season GP-share comparison failed this pair at 28%.
def _live_pair(check, live=None):
    shutil.copy2(SNAP / "PLAYERLIST_2026-10-26.xlsx", check.SNAPSHOTS / "PLAYERLIST_2026-10-26.xlsx")
    frame = _frame(SNAP / "PLAYERLIST_2026-10-28.xlsx") if live is None else live
    _fetched(check, frame, datetime(2026, 10, 28, 0, 30))
    _rosters(check, frame["player_name"].head(10), "2026-10-26T23:04:00")


def test_an_ordinary_pair_of_fetches_days_apart_does_not_fail(check, capsys):
    _live_pair(check)
    assert _run(check, []) == 0
    out = capsys.readouterr().out
    assert "no player changed NBA team" in out
    assert "GP direction not compared: in season" in out           # says which, and why
    assert "larger share" not in out


def test_a_shifted_live_file_fails_and_names_the_rows(check, capsys):
    _live_pair(check, _shift(_frame(SNAP / "PLAYERLIST_2026-10-28.xlsx")))
    assert _run(check, []) == 1
    out = capsys.readouterr().out
    assert "on a different NBA team than last week" in out and "not trades" in out
    assert "Luka Don" in out and "LAL -> DEN" in out


def test_a_shift_confined_to_a_few_rows_still_fails_on_its_neighbours(check, capsys):
    live = _frame(SNAP / "PLAYERLIST_2026-10-28.xlsx")
    part = pd.concat([live.iloc[:-12], _shift(live.iloc[-13:])]).reset_index(drop=True)
    _live_pair(check, part)
    assert _run(check, []) == 1
    assert "on the team the player in the next or previous row had" in capsys.readouterr().out


def test_a_real_trade_is_reported_not_failed(check, capsys):
    live = _frame(SNAP / "PLAYERLIST_2026-10-28.xlsx").copy()
    i = live.index[live["player_name"].str.startswith("Luka")][0]
    j = live.index[live["player_name"] == "Jayson Tatum"][0]
    live.loc[i, "player_nba_team"] = "MIA"                     # nobody near him was MIA
    live.loc[j, "player_nba_team"] = "POR"
    _live_pair(check, live)
    assert _run(check, []) == 0
    out = capsys.readouterr().out
    assert "2 player(s) changed NBA teams" in out and "LAL -> MIA" in out and "BOS -> POR" in out


def test_the_pre_season_path_still_fails_a_shift_at_the_measured_rate(check, capsys):
    import re
    shutil.copy2(SNAP / "PLAYERLIST_2026-10-05.xlsx", check.SNAPSHOTS / "PLAYERLIST_2026-10-05.xlsx")
    real = _frame(SNAP / "PLAYERLIST_2026-10-13.xlsx").sort_values(
        "player_total_proj_FP", ascending=False).reset_index(drop=True)
    _fetched(check, _shift(real), datetime(2026, 10, 13, 16, 0))
    assert _run(check, []) == 1
    out = capsys.readouterr().out
    rate = re.search(r"players \((\d+)%\) have a larger share", out)
    assert rate and 44 <= int(rate.group(1)) <= 50, out          # measured 47% on 10-27
    assert "compared as a share of games remaining (both files pre-season shaped)" in out
