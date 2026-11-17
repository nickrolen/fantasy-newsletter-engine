"""H51 E (FIXES item 2): update_leaguehistory SETS record_current_season and
total_moves_current_season from their sources (it never wrote them: (0-0) and
0 for everyone after week 4), and --fill-current-season sets them for the
weeks already played, touching nothing else. On a temp copy of the real state
(LEAGUEHISTORY.xlsx is state: never written here)."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
NEED = ["data/LEAGUEHISTORY.xlsx", "config/RECORDS.json", "config/SCHEDULE.json",
        "config/TRANSACTION_RULINGS.json"]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def copy(tmp_path):
    if not all((ROOT / r).is_file() for r in NEED):
        pytest.skip("league state not in this checkout (LEAGUEHISTORY, RECORDS, the rulings)")
    for r in NEED + [p.relative_to(ROOT).as_posix() for p in (ROOT / "data").glob("waivers_week*.txt")]:
        (tmp_path / r).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / r, tmp_path / r)
    return tmp_path


def _sheet(path):
    ws = load_workbook(path).active
    head = [c.value for c in ws[1]]
    return {str(ws.cell(row=r, column=1 + head.index("manager_name")).value).strip():
            {h: ws.cell(row=r, column=1 + i).value for i, h in enumerate(head)}
            for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=1 + head.index("manager_name")).value}


@pytest.mark.slow
def test_fill_sets_both_columns_from_their_sources_idempotently_and_touches_nothing_else(copy):
    ul = _load("update_leaguehistory")
    from modules.data_loader import CURRENT_SEASON
    from modules.season_outcomes import build_matchups, build_standings
    from modules import transaction_rulings as tr
    before = _sheet(copy / "data" / "LEAGUEHISTORY.xlsx")
    dry = ul.fill_current_season(copy, dry_run=True, echo=lambda *a: None)
    assert _sheet(copy / "data" / "LEAGUEHISTORY.xlsx") == before          # a dry run writes nothing
    out = ul.fill_current_season(copy, dry_run=False, echo=lambda *a: None)
    after = _sheet(copy / "data" / "LEAGUEHISTORY.xlsx")
    # the values match RECORDS.json (every week played) and the add table
    records = json.loads((copy / "config" / "RECORDS.json").read_text(encoding="utf-8"))
    sched = json.loads((copy / "config" / "SCHEDULE.json").read_text(encoding="utf-8"))
    rows = [r for r in build_matchups(CURRENT_SEASON, records, sched) if r["week"] <= out["through"]]
    st = {r["manager"]: r for r in build_standings(CURRENT_SEASON, rows)}
    counts = tr.adds_by_budget_week(copy, sched)
    for m, row in after.items():
        assert row["record_current_season"] == f"({st[m]['wins']}-{st[m]['losses']})"
        assert row["total_moves_current_season"] == sum(
            len(by.get(m, [])) for wk, by in counts.items() if wk <= out["through"])
        # nothing else moved
        assert {k: v for k, v in row.items() if k not in ul.SET_COLUMNS} == \
               {k: v for k, v in before[m].items() if k not in ul.SET_COLUMNS}
    assert dry["values"] == out["values"]
    # SET, not added: a second run changes nothing
    ul.fill_current_season(copy, dry_run=False, echo=lambda *a: None)
    assert _sheet(copy / "data" / "LEAGUEHISTORY.xlsx") == after


@pytest.mark.slow
def test_the_rollovers_reconciliation_passes_on_the_result(copy, monkeypatch, capsys):
    """rollover_leaguehistory's dry run on the filled copy: record_current_season
    covers the regular season it reads from RECORDS.json (no "must reconcile")."""
    ul = _load("update_leaguehistory")
    ul.fill_current_season(copy, dry_run=False, echo=lambda *a: None)
    ro = _load("rollover_leaguehistory")
    monkeypatch.setattr(ro, "LEAGUEHISTORY", copy / "data" / "LEAGUEHISTORY.xlsx")
    monkeypatch.setattr(ro, "RECORDS", copy / "config" / "RECORDS.json")
    monkeypatch.setattr(ro, "SCHEDULE", copy / "config" / "SCHEDULE.json")
    # mid-season there is no champion yet: name one so the dry run reaches the reconciliation
    monkeypatch.setattr(sys, "argv", ["rollover_leaguehistory.py", "--champion", "Nick",
                                      "--regular-season-winner", "Nick"])
    assert ro.main() == 0, capsys.readouterr().out
    assert "must reconcile" not in capsys.readouterr().out


def test_a_tie_raises_rather_than_write_a_record_the_rollover_cannot_read(tmp_path, monkeypatch):
    ul = _load("update_leaguehistory")
    from modules import season_outcomes, transaction_rulings as tr
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "RECORDS.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "SCHEDULE.json").write_text('{"weeks": []}', encoding="utf-8")
    monkeypatch.setattr(season_outcomes, "build_matchups", lambda *a: [{"week": 1}])
    monkeypatch.setattr(season_outcomes, "build_standings", lambda *a: [
        {"manager": "Nick", "wins": 0, "losses": 0, "ties": 1}])
    monkeypatch.setattr(tr, "adds_by_budget_week", lambda *a, **k: {})
    with pytest.raises(ValueError, match="tied week"):
        ul.current_season_values(tmp_path, 1)


def test_weekly_runs_set_the_columns_and_never_add_them():
    src = (ROOT / "scripts" / "update_leaguehistory.py").read_text(encoding="utf-8")
    assert src.count("set_current_season(ws, col_idx, current_season_values(base, args.week))") == 2
    assert "get_number(r, \"total_moves_current_season\")" not in src
