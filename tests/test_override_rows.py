"""5f item 1: a projection override reaches its player even outside Yahoo's pool.

Evan Mobley (11-18 on): a free agent Yahoo projects at 0 GP / 0 FP, so he sorts
out of the 175-player pool and his override (37.4 FPPG over his team's games)
had no row to patch -- invisible on Market and in Advice, his injury entry
inert. fetch_playerlist now adds every live override's player by Yahoo id:
Yahoo's own row from the same table searched by name and kept by id, or, if
that fails, a row BUILT from his last known snapshot row and marked as built.
No network: Yahoo's pages are synthetic here.
"""
import importlib.util
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules import playerlist_freshness, projection_overrides  # noqa: E402
from modules.data_loader import DURABILITY_PRIOR, NBA_SCHEDULE_FILE, free_agents  # noqa: E402

KEY = "478.l.16778"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_5f", ROOT / "scripts" / f"{name}.py")
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


def _mobley(**over):
    e = {"yahoo_id": "6514", "player_name": "Evan Mobley",
         "set": {"projectedFPPG": 37.4, "player_proj_GP": "team"},
         "replaces": {"projectedFPPG": 0.0, "player_proj_GP": 0.0},
         "reason": "Yahoo's rest-of-season row is 0 GP / 0 FP", "source": "test",
         "added": "2026-11-16", "review_by": "2026-12-07"}
    e.update(over)
    return e


# The pool: three Cavaliers and others, Mobley not among them.
POOL = [("1", "Donovan Mitchell", "CLE", "SG", 60.0, 2700.0),
        ("2", "Darius Garland", "CLE", "PG", 58.0, 2088.0),
        ("3", "Jarrett Allen", "CLE", "C", 61.0, 1952.0),
        ("4", "Domantas Sabonis", "SAC", "C", 62.0, 3100.0)]


def _collect(owner_for=None):
    def collect(league_id, status, limit, label):
        out = {}
        for i, n, t, p, g, f in POOL:
            owned = (owner_for or {}).get(n)
            if status == "T" and not owned:
                continue
            out[i] = {"yahoo_id": i, "player_name": n, "nba_team": t, "positions": p,
                      "proj_gp": str(g), "total_fp": f"{f:,.2f}", "owner": owned}
        return out
    return collect


def _search_page(rows):
    """Yahoo's S_PSR table as its search returns it: a header row, then rows."""
    head = ("<tr><th></th><th></th><th>Players</th><th>Opp</th><th>Roster Status</th>"
            "<th>GP*</th><th>Fan Pts</th></tr>")
    body = "".join(
        f'<tr class="player-row"><td></td><td></td><td><a href="https://sports.yahoo.com/nba/players/{i}/" '
        f'class="name">{n}</a> <span>{t} - {p}</span></td><td>@BOS</td><td>FA</td>'
        f"<td>{g}</td><td>{f}</td></tr>" for i, n, t, p, g, f in rows)
    return f"<table>{head}{body}</table>"


@pytest.fixture
def fetch(tmp_path, monkeypatch):
    fp = _load("fetch_playerlist")
    (tmp_path / "config" / "snapshots").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    (tmp_path / "config" / "PROJECTION_OVERRIDES.json").write_text(
        json.dumps({"overrides": [_mobley()]}), encoding="utf-8")
    monkeypatch.setattr(fp, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(fp, "ROSTERS", tmp_path / "none.json")
    monkeypatch.setattr(fp, "AGES", tmp_path / "ages.json")
    monkeypatch.setattr(fp, "PLAYERLIST", tmp_path / "data" / "PLAYERLIST.xlsx")
    monkeypatch.setattr(fp, "collect", _collect())
    monkeypatch.setattr(fp, "time", type("T", (), {"sleep": staticmethod(lambda s: None)}))
    fp._searched = []
    return fp


def _searching(fp, monkeypatch, page):
    def search(league_id, name):
        fp._searched.append(name)
        if isinstance(page, Exception):
            raise page
        return page
    monkeypatch.setattr(fp, "fetch_search_page", search)


def _write_out(fp, tmp_path):
    out = tmp_path / "PL.xlsx"
    assert _run(fp, ["--execute", "--out", str(out), "--no-bbref-ages", "--league-key", KEY]) == 0
    return out, pd.read_excel(out), playerlist_freshness.read_stamp(out)


def test_an_overridden_free_agent_outside_the_pool_is_fetched_by_search_and_patched(
        fetch, tmp_path, monkeypatch, capsys):
    _searching(fetch, monkeypatch, _search_page([("6514", "Evan Mobley", "CLE", "PF,C", "0", "0.00")]))
    out, df, st = _write_out(fetch, tmp_path)
    assert fetch._searched == ["Evan Mobley"]
    m = df[df["player_name"] == "Evan Mobley"].iloc[0]
    assert (m["projectedFPPG"], m["player_proj_GP"]) == (37.4, 61.0)      # "team": CLE's max
    assert m["player_total_proj_FP"] == pytest.approx(37.4 * 61.0, abs=0.01)
    assert (m["player_nba_team"], m["player_position(s)"], int(m["yahoo_id"])) == ("CLE", "PF,C", 6514)
    assert len(df) == len(POOL) + 1
    rec = projection_overrides.from_stamp(st)
    assert rec["applied"][0]["replaces_matches"] is True and not rec["unapplied"]
    assert rec["applied"][0]["yahoo"]["player_proj_GP"] == 0.0              # upstream recorded
    x = projection_overrides.extras_from_stamp(st)
    assert x == {"pool_limit": 175, "rows": [
        {"yahoo_id": "6514", "player_name": "Evan Mobley", "how": "search"}]}
    assert "Evan Mobley (id 6514): Yahoo's row, by search" in capsys.readouterr().out


def test_a_search_row_with_another_id_is_not_taken_and_a_row_is_built_from_the_last_snapshot(
        fetch, tmp_path, monkeypatch, capsys):
    # Yahoo returns a namesake (or ignores the search): never taken by name alone
    _searching(fetch, monkeypatch, _search_page([("9999", "Evan Mobley", "LAL", "SF", "70", "700.00")]))
    old = pd.DataFrame([{"player_name": "Evan Mobley", "player_nba_team": "CLE",
                         "player_position(s)": "PF,C", "player_total_proj_FP": 2619.0,
                         "player_proj_GP": 69.3, "projectedFPPG": 37.79, "age": 25}])
    old.to_excel(tmp_path / "config" / "snapshots" / "PLAYERLIST_2026-11-09.xlsx", index=False)
    # a newer snapshot without him is skipped, not taken
    pd.DataFrame([{"player_name": "Jarrett Allen", "player_nba_team": "CLE",
                   "player_position(s)": "C", "player_total_proj_FP": 1.0, "player_proj_GP": 1.0,
                   "projectedFPPG": 1.0, "age": 28}]).to_excel(
        tmp_path / "config" / "snapshots" / "PLAYERLIST_2026-11-16.xlsx", index=False)
    out, df, st = _write_out(fetch, tmp_path)
    m = df[df["player_name"] == "Evan Mobley"]
    assert len(m) == 1 and m.iloc[0]["player_nba_team"] == "CLE"
    assert (m.iloc[0]["projectedFPPG"], m.iloc[0]["player_proj_GP"]) == (37.4, 61.0)
    x = projection_overrides.extras_from_stamp(st)["rows"][0]
    assert x["how"] == "built" and x["from"] == "config/snapshots/PLAYERLIST_2026-11-09.xlsx"
    assert "no row with id 6514" in x["search"]
    rec = projection_overrides.from_stamp(st)
    a = rec["applied"][0]
    assert a["built"] is True and a["replaces_matches"] is None
    assert a["yahoo"] == {"player_proj_GP": None, "player_total_proj_FP": None, "projectedFPPG": None}
    printed = capsys.readouterr().out
    assert "BUILT from config/snapshots/PLAYERLIST_2026-11-09.xlsx (CLE, PF,C)" in printed
    # the review still runs on it: review_by fails when due; replaces is said, not faked
    entries = [_mobley()]
    fails, warns, lines = projection_overrides.review(entries, rec, date(2026, 12, 7))
    assert fails == [] and "BUILT" in lines[0] and "was not checked" in warns[0]
    fails, _, _ = projection_overrides.review(entries, rec, date(2026, 12, 8))
    assert len(fails) == 1 and "due for review on 2026-12-07" in fails[0]


def test_a_failed_search_and_no_snapshot_leaves_him_out_and_says_so(fetch, tmp_path, monkeypatch, capsys):
    _searching(fetch, monkeypatch, OSError("no network"))
    out, df, st = _write_out(fetch, tmp_path)
    assert "Evan Mobley" not in set(df["player_name"]) and len(df) == len(POOL)
    assert projection_overrides.extras_from_stamp(st)["rows"] == []
    rec = projection_overrides.from_stamp(st)
    assert rec["unapplied"][0]["why"] == "not in this fetch"
    printed = capsys.readouterr().out
    assert "NOT ADDED -- Evan Mobley: Yahoo search failed (OSError: no network)" in printed
    assert "no PLAYERLIST snapshot has him" in printed


def test_a_player_already_in_the_fetch_is_not_searched_or_doubled(fetch, tmp_path, monkeypatch):
    global POOL
    _searching(fetch, monkeypatch, _search_page([]))
    pool = POOL + [("6514", "Evan Mobley", "CLE", "PF,C", 0.0, 0.0)]
    monkeypatch.setattr(sys.modules[__name__], "POOL", pool)
    monkeypatch.setattr(fetch, "collect", _collect({"Evan Mobley": "Kevin Quran't"}))
    out, df, st = _write_out(fetch, tmp_path)
    assert fetch._searched == [] and (df["player_name"] == "Evan Mobley").sum() == 1
    assert projection_overrides.extras_from_stamp(st)["rows"] == []


def test_the_built_row_needs_an_override_that_sets_both_numbers(fetch, tmp_path, monkeypatch, capsys):
    (tmp_path / "config" / "PROJECTION_OVERRIDES.json").write_text(
        json.dumps({"overrides": [_mobley(set={"projectedFPPG": 37.4})]}), encoding="utf-8")
    _searching(fetch, monkeypatch, _search_page([]))
    pd.DataFrame([{"player_name": "Evan Mobley", "player_nba_team": "CLE", "player_position(s)": "PF,C",
                   "player_total_proj_FP": 1.0, "player_proj_GP": 1.0, "projectedFPPG": 1.0}]).to_excel(
        tmp_path / "config" / "snapshots" / "PLAYERLIST_2026-11-09.xlsx", index=False)
    out, df, st = _write_out(fetch, tmp_path)
    assert "Evan Mobley" not in set(df["player_name"])
    assert "does not set both projectedFPPG and player_proj_GP" in capsys.readouterr().out


# --- check_playerlist: expected and reported; never a shift, jump or duplicate ---

@pytest.fixture
def check(tmp_path, monkeypatch):
    mod = _load("check_playerlist")
    for rel in (DURABILITY_PRIOR["snapshot"], "config/SCHEDULE.json", NBA_SCHEDULE_FILE):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / rel).is_file():
            shutil.copy2(ROOT / rel, tmp_path / rel)
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "PLAYERLIST", tmp_path / "data" / "PLAYERLIST.xlsx")
    monkeypatch.setattr(mod, "ROSTERS", tmp_path / "config" / "ROSTERS.json")
    monkeypatch.setattr(mod, "SNAPSHOTS", tmp_path / "snapshots")
    mod.PLAYERLIST.parent.mkdir(parents=True, exist_ok=True)
    mod.SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "PROJECTION_OVERRIDES.json").write_text(
        json.dumps({"overrides": [_mobley()]}), encoding="utf-8")
    return mod


def _pool_frame(n=40):
    teams = ["BOS", "NYK", "MIL", "DEN", "LAL", "GSW", "PHX", "DAL"]
    rows = []
    for i in range(n):
        gp = 60.0 - (i % 5)
        fppg = 50.0 - i * 0.5
        rows.append({"player_name": f"Player {chr(65 + i // 26)}{chr(65 + i % 26)}",
                     "player_nba_team": teams[i % len(teams)], "player_position(s)": "SF",
                     "player_total_proj_FP": round(fppg * gp, 2), "player_proj_GP": gp,
                     "projectedFPPG": fppg, "age": 26, "yahoo_id": 1000 + i})
    return pd.DataFrame(rows)


def _with_mobley(frame, now_fppg=37.4, gp=60.0):
    row = {"player_name": "Evan Mobley", "player_nba_team": "CLE", "player_position(s)": "PF,C",
           "player_total_proj_FP": round(now_fppg * gp, 2), "player_proj_GP": gp,
           "projectedFPPG": now_fppg, "age": 25, "yahoo_id": 6514}
    out = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    return out.sort_values("player_total_proj_FP", ascending=False).reset_index(drop=True)


def _stamp(how="search"):
    applied = [{"yahoo_id": "6514", "player_name": "Evan Mobley",
                "yahoo": ({"player_proj_GP": 0.0, "player_total_proj_FP": 0.0, "projectedFPPG": 0.0}
                          if how == "search" else
                          {"player_proj_GP": None, "player_total_proj_FP": None, "projectedFPPG": None}),
                "now": {"player_proj_GP": 60.0, "player_total_proj_FP": 2244.0, "projectedFPPG": 37.4},
                "replaces": _mobley()["replaces"], "replaces_matches": True if how == "search" else None,
                "reason": "r", "review_by": "2026-12-07", **({"built": True} if how == "built" else {})}]
    x = {"yahoo_id": "6514", "player_name": "Evan Mobley", "how": how}
    if how == "built":
        x.update({"from": "config/snapshots/PLAYERLIST_2026-11-09.xlsx", "search": "s"})
    return {projection_overrides.STAMP_KEY: projection_overrides.stamp_value(applied, []),
            projection_overrides.EXTRA_KEY: projection_overrides.extra_value([x], 175)}


class _Nov24(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 24)


@pytest.fixture
def on_1124(check, monkeypatch):
    import modules.league_clock as lc
    monkeypatch.setattr(playerlist_freshness, "date", _Nov24)
    monkeypatch.setattr(check, "date", _Nov24)
    monkeypatch.setattr(lc, "league_today", lambda *a, **k: _Nov24.today())


def _snapshot(check, frame, name="PLAYERLIST_2026-11-16.xlsx", extra=None):
    playerlist_freshness.write(frame, check.SNAPSHOTS / name, "yahoo:test",
                               now=datetime(2026, 11, 16, 1, 0), extra=extra)


def test_check_reports_the_extra_row_and_counts_it_as_nothing_else(check, on_1124, capsys):
    base = _pool_frame()
    _snapshot(check, base)                                   # last week: no Mobley
    live = _with_mobley(base)
    playerlist_freshness.write(live, check.PLAYERLIST, "yahoo:test",
                               now=datetime(2026, 11, 24, 0, 41), extra=_stamp())
    rc = _run(check, [])
    out = capsys.readouterr().out
    assert "1 override row added outside Yahoo's 175: Evan Mobley (Yahoo's row, by search)" in out
    assert "Evan Mobley: FPPG 0.00 -> 37.40" in out                    # the override check ran
    assert "duplicate" not in out and "shifted" not in out
    assert "moved more than" not in out                               # no FPPG jump
    assert f"({len(base)} players in both)" in out
    assert "FAILURES" not in out, out
    assert rc == 0


def test_identical_pool_files_are_still_identical_with_the_extra_row_left_out(check, on_1124, capsys):
    """Size and the identical-file check compare the pool only: last week's
    snapshot already had him as an extra row, this week's does too."""
    base = _pool_frame()
    _snapshot(check, _with_mobley(base), extra=_stamp())
    playerlist_freshness.write(_with_mobley(base), check.PLAYERLIST, "yahoo:test",
                               now=datetime(2026, 11, 24, 0, 41), extra=_stamp())
    assert _run(check, []) == 0
    out = capsys.readouterr().out
    assert f"({len(base)} players in both)" in out and "projections unchanged since" in out


def test_a_built_extra_row_is_reported_as_built_and_warns_not_fails(check, on_1124, capsys):
    base = _pool_frame()
    _snapshot(check, base)
    playerlist_freshness.write(_with_mobley(base), check.PLAYERLIST, "yahoo:test",
                               now=datetime(2026, 11, 24, 0, 41), extra=_stamp("built"))
    assert _run(check, []) == 0
    out = capsys.readouterr().out
    assert "Evan Mobley (BUILT from config/snapshots/PLAYERLIST_2026-11-09.xlsx)" in out
    assert "'replaces'" in out and "was not checked" in out


def test_a_shift_in_the_pool_still_fails_with_an_extra_row_present(check, on_1124, capsys):
    base = _pool_frame()
    _snapshot(check, base)
    shifted = base.copy()
    shifted["player_nba_team"] = shifted["player_nba_team"].shift(1).fillna("CLE")
    playerlist_freshness.write(_with_mobley(shifted), check.PLAYERLIST, "yahoo:test",
                               now=datetime(2026, 11, 24, 0, 41), extra=_stamp())
    assert _run(check, []) == 1
    assert "stats shifted against names" in capsys.readouterr().out


def test_a_stamped_extra_row_missing_from_the_file_fails(check, on_1124, capsys):
    base = _pool_frame()
    _snapshot(check, base)
    playerlist_freshness.write(base, check.PLAYERLIST, "yahoo:test",
                               now=datetime(2026, 11, 24, 0, 41), extra=_stamp())
    assert _run(check, []) == 1
    assert "override rows that are not in the file: ['Evan Mobley']" in capsys.readouterr().out


def test_the_free_agent_views_see_him_like_any_other_free_agent():
    """Market, Advice, Players and the cards take free agents from
    data_loader.free_agents: PLAYERLIST rows on no roster. A row in the file is
    all he needed."""
    frame = _with_mobley(_pool_frame(6))
    fa = free_agents(frame, {"Nick": ["Player AA", "Player AB"]})
    assert "Evan Mobley" in set(fa["player_name"])
    assert fa[fa["player_name"] == "Evan Mobley"].iloc[0]["projectedFPPG"] == 37.4


def test_his_injury_entry_applies_once_he_has_a_row():
    """Before: 'match no rostered player and nothing in PLAYERLIST: inert'."""
    from modules.data_loader import resolve_injury_overrides
    entry = {"player_name": "Evan Mobley", "nba_team": "CLE", "out_weeks": [5],
             "return_week": 6, "return_date": "2026-11-29"}
    before = resolve_injury_overrides({"players": [entry]}, {"Nick": []}, list(_pool_frame(6)["player_name"]))
    after = resolve_injury_overrides({"players": [entry]}, {"Nick": []},
                                     list(_with_mobley(_pool_frame(6))["player_name"]))
    assert before["_unresolved"] == ["Evan Mobley"] and after["_unresolved"] == []
