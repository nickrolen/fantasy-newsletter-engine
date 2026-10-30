"""An add's effective date (HANDOFF_EFFECTIVE_DATE_RULING 2026-10-30, Part A).

Hayden added Zach LaVine late on Sunday 10-25, after every game that day had
finished; the league counts it as a week 2 move. Yahoo's roster for 10-25
lists LaVine on Hayden's bench anyway, so the 10-26 log pull has a 10-25
bench row worth 44.25, and Hayden's week 1 card carried a 44.2-point blunder
("LaVine on the bench while Castle, with no game, held SG") he could not have
avoided. The ruling takes the player off the roster for the days before
`effective` -- at load time, in every reader, never by rewriting the logs.
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import transaction_rulings as tr          # noqa: E402

SCHEDULE = {"weeks": [{"week": 1, "start_date": "2026-10-20", "end_date": "2026-10-25"},
                      {"week": 2, "start_date": "2026-10-26", "end_date": "2026-11-01"}]}
LAVINE = {"kind": "effective_date", "manager": "Hayden", "player": "Zach LaVine", "type": "add",
          "transaction_date": "2026-10-26", "effective": "2026-10-26", "by": "Nick",
          "on": "2026-10-30", "reason": "added after Sunday's games"}


def world(tmp_path, rulings, files=None):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / tr.RULINGS_FILE).write_text(json.dumps({"rulings": rulings}))
    (tmp_path / "config" / "SCHEDULE.json").write_text(json.dumps(SCHEDULE))
    files = files if files is not None else {2: ["- [2026-10-26] Hayden: Zach LaVine"]}
    for wk, lines in files.items():
        (tmp_path / "data" / f"waivers_week{wk}.txt").write_text(
            "# Waiver Adds\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def lineups():
    return pd.DataFrame([
        {"date": "2026-10-25", "manager": "Hayden", "player_name": "Zach LaVine", "slot": "BN"},
        {"date": "2026-10-26", "manager": "Hayden", "player_name": "Zach LaVine", "slot": "SG"},
        {"date": "2026-10-25", "manager": "Hayden", "player_name": "Stephon Castle", "slot": "SG"},
        {"date": "2026-10-21", "manager": "Garrett", "player_name": "Zach LaVine", "slot": "BN"},
        {"date": "2026-10-25", "manager": "Hayden", "player_name": "Matas Buzelis", "slot": "BN"},
    ])


def test_the_10_25_row_is_dropped_for_hayden_and_nothing_else(tmp_path):
    base = world(tmp_path, [LAVINE])
    said = []
    got = tr.apply_effective_dates(lineups(), base, "lineups", echo=said.append)
    assert len(got) == 4
    assert not ((got["date"] == "2026-10-25") & (got["player_name"] == "Zach LaVine")).any()
    assert ((got["manager"] == "Garrett") & (got["player_name"] == "Zach LaVine")).any()
    assert ((got["date"] == "2026-10-26") & (got["player_name"] == "Zach LaVine")).any()
    assert "dropped 1 row(s) before 2026-10-26" in said[0]
    plog = pd.DataFrame([{"date": "2026-10-25", "manager": "Hayden", "player_name": "Zach LaVine",
                          "started": False, "fantasy_points": 44.25}])
    assert tr.apply_effective_dates(plog, base, "playerlog", echo=lambda *_: None).empty


def test_a_started_row_before_effective_raises(tmp_path):
    base = world(tmp_path, [LAVINE])
    df = lineups()
    df.loc[0, "slot"] = "UTIL"
    with pytest.raises(tr.RulingError, match="STARTED lineups row.*2026-10-25"):
        tr.apply_effective_dates(df, base, "lineups", echo=lambda *_: None)
    plog = pd.DataFrame([{"date": "2026-10-25", "manager": "Hayden", "player_name": "Zach LaVine",
                          "started": True, "fantasy_points": 44.25}])
    with pytest.raises(tr.RulingError, match="STARTED playerlog"):
        tr.apply_effective_dates(plog, base, "playerlog", echo=lambda *_: None)


def test_a_ruling_matching_no_add_raises(tmp_path):
    base = world(tmp_path, [{**LAVINE, "player": "Zach Randolph"}])
    with pytest.raises(tr.RulingError, match="matches no add"):
        tr.apply_effective_dates(lineups(), base, "lineups", echo=lambda *_: None)
    base = world(tmp_path, [LAVINE], files={})
    (tmp_path / "data" / "waivers_week2.txt").unlink()
    with pytest.raises(tr.RulingError, match="matches no add"):
        tr.apply_effective_dates(lineups(), base, "lineups", echo=lambda *_: None)


def test_an_unknown_kind_raises(tmp_path):
    world(tmp_path, [{**LAVINE, "kind": "retroactive"}])
    with pytest.raises(tr.RulingError, match="unknown kind"):
        tr.load_all(tmp_path)


def test_the_add_counts_in_the_week_containing_effective(tmp_path):
    """Stamped Sunday 10-25 (week 1) by a sync run in Phoenix, effective
    Monday 10-26 (week 2): it leaves week 1's count and joins week 2's."""
    from modules.weekly_stats import load_waiver_adds
    rule = {**LAVINE, "transaction_date": "2026-10-25"}
    base = world(tmp_path, [rule], files={1: ["- [2026-10-25] Hayden: Zach LaVine"],
                                          2: ["- [2026-10-26] Hayden: Franz Wagner"]})
    w1, _ = tr.waiver_lines(base / "data" / "waivers_week1.txt", base, 1, SCHEDULE)
    w2, _ = tr.waiver_lines(base / "data" / "waivers_week2.txt", base, 2, SCHEDULE)
    assert load_waiver_adds("x", lines=w1)["Hayden"] == []
    assert load_waiver_adds("x", lines=w2)["Hayden"] == ["Franz Wagner", "Zach LaVine"]
    # the sync: re-dated into week 2, out of week 1
    txn = {"type": "add", "manager": "Hayden", "player_name": "Zach LaVine",
           "date": date(2026, 10, 25), "details": {}}
    rulings = tr.load_all(base)
    wk1, _ = tr.apply_to_transactions([txn], rulings, since=date(2026, 10, 20),
                                      until=date(2026, 10, 25), echo=lambda *_: None)
    wk2, applied = tr.apply_to_transactions([txn], rulings, since=date(2026, 10, 26),
                                            echo=lambda *_: None)
    assert wk1 == [] and [t["date"] for t in wk2] == [date(2026, 10, 26)] and len(applied) == 1


def test_the_real_ruling_is_on_file():
    got = [(r.manager, r.player, r.transaction_date, r.effective)
           for r in tr.effective_dates(tr.load_all(ROOT))]
    assert ("Hayden", "Zach LaVine", "2026-10-26", "2026-10-26") in got


def _raw_lavine_row():
    path = ROOT / "data" / "LINEUPS.xlsx"
    if not path.is_file():
        return False
    raw = pd.read_excel(path)
    return bool(((raw["manager"] == "Hayden") & (raw["player_name"] == "Zach LaVine")
                 & (pd.to_datetime(raw["date"]).dt.strftime("%Y-%m-%d") == "2026-10-25")).any())


@pytest.mark.skipif(not _raw_lavine_row(), reason="the 10-26 log (Hayden's 10-25 LaVine row) is gone")
def test_haydens_week_1_card_on_the_10_26_data():
    from modules.data_loader import load_all_data
    from modules.weekly_stats import compute_weekly_report, load_waiver_adds
    from modules.what_if_analyzer import analyze_weekly_what_if
    from modules.report_builder import build_report_cards
    data = load_all_data(ROOT, current_week=1)
    assert not ((data.lineups["manager"] == "Hayden") & (data.lineups["player_name"] == "Zach LaVine")
                & (data.lineups["date"] < "2026-10-26")).any()
    report = compute_weekly_report(data, 1, load_waiver_adds(str(ROOT / "data" / "waivers_week1.txt")))
    mr = {}
    for m in report.matchups:
        mr[m.manager_a] = {"score": m.score_a, "opponent_score": m.score_b}
        mr[m.manager_b] = {"score": m.score_b, "opponent_score": m.score_a}
    wi = analyze_weekly_what_if(data, 1, mr)
    card = [c for c in build_report_cards(report, data, wi) if c["manager"] == "Hayden"][0]
    assert (card["blunders"], card["blunder_points"], card["games_left_on_bench"]) == (0, 0, 1)
    assert "Zach LaVine" not in json.dumps([b.to_dict() for b in wi.manager_analysis["Hayden"].blunders])
