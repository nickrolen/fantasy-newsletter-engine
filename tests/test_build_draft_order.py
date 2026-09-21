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
    # The season reset clears the trade LOG but preserves pick OWNERSHIP, so
    # after a reset the two live in different places. Read the log back out of
    # the archive when the live one is empty.
    if not trades.get("trades"):
        arc = PROJECT_ROOT / "archive"
        for d in sorted((x for x in arc.iterdir() if x.is_dir()), reverse=True) if arc.is_dir() else []:
            f = d / "config" / "TRADES.json"
            if f.is_file():
                archived = json.loads(f.read_text(encoding="utf-8"))
                if archived.get("trades"):
                    trades = {**trades, "trades": archived["trades"]}
                    break
    if not trades.get("trades"):
        pytest.skip("no trade log available (live or archived) to check against")
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

    Roster is 17 with 2 IL, so 15 rounds are filled by keepers plus the draft.
    A manager's live-pick count is 15 minus their keeper count. That is 9 for
    everyone in 2026-27, but NOT from 2027-28, when the Cup winner keeps a
    sixth and drafts 9 while the other three draft 10. Either way an
    unexpected total is a data problem, not a draft order, and must not be
    printed as if it were fine.
    """
    from modules.data_loader import live_picks_for
    monkeypatch.setattr("sys.argv", ["b"])
    rc = mod.main()
    out = capsys.readouterr().out
    if "UNEVEN PICK COUNTS" in out:
        assert rc == 1, "uneven counts must be a failure exit, not a clean run"
        assert "missing" in out.lower()
    else:
        assert rc == 0
        # if it claims even, every manager really must have their own expected total
        import re
        expected = live_picks_for()
        for m, n in re.findall(r"^\s+(\w+)\s+(\d+)\s+\(even\)", out, re.M):
            assert int(n) == expected.get(m, min(expected.values())), (
                f"{m} shows {n} picks, expected {expected.get(m)}")


def test_pick_counts_must_equal_fillable_spots_minus_keepers():
    """The invariant, stated so it survives asymmetric keeper counts.

    The old form of this test was `fillable - keepers_per_team ==
    total_draft_rounds`, which silently assumes every manager keeps the same
    number. That stops being true in 2027-28, when the Cup winner keeps a
    sixth. The durable statement is about the whole draft board, not one
    manager: every one of the 15 x 4 = 60 slots is either a keeper or a live
    pick, and each manager's live picks are 15 minus their own keepers.
    """
    from modules.data_loader import (LEAGUE_STRUCTURE as LS, MANAGERS,
                                     TOTAL_ROUNDS, keepers_for, live_picks_for)

    assert TOTAL_ROUNDS == LS["roster_size"] - LS["il_slots"], (
        "you draft into every non-IL roster spot: "
        f"{LS['roster_size']} - {LS['il_slots']} != {TOTAL_ROUNDS}")

    keepers, live = keepers_for(), live_picks_for()
    for m in MANAGERS:
        assert keepers[m] + live[m] == TOTAL_ROUNDS, (
            f"{m}: {keepers[m]} keepers + {live[m]} live picks != {TOTAL_ROUNDS} rounds")
    assert sum(keepers.values()) + sum(live.values()) == TOTAL_ROUNDS * len(MANAGERS)


def test_the_scalar_round_counts_still_match_while_keepers_are_uniform():
    """league_structure.keepers_per_team / total_draft_rounds are scalars and
    describe the CURRENT season only. While that season is uniform they must
    agree with keepers_for(); once it is not, they stop being meaningful and
    this test stops applying rather than failing misleadingly."""
    from modules.data_loader import LEAGUE_STRUCTURE as LS, keepers_for, live_picks_for
    counts = set(keepers_for().values())
    if len(counts) != 1:
        pytest.skip("keeper counts are no longer uniform; the scalars do not apply")
    assert counts.pop() == LS["keepers_per_team"]
    assert set(live_picks_for().values()).pop() == LS["total_draft_rounds"]


def test_falls_back_to_the_archive_after_the_season_reset(mod, tmp_path, monkeypatch):
    """The draft order is set AFTER the reset, which clears RECORDS.json.

    The standings that determine it then live only in
    archive/<season>/config/. Without this the script simply stops working at
    exactly the moment it is needed.
    """
    live_rec = tmp_path / "config" / "RECORDS.json"
    live_sched = tmp_path / "config" / "SCHEDULE.json"
    live_rec.parent.mkdir(parents=True, exist_ok=True)
    live_rec.write_text(json.dumps({"weekly_scores": {}}), encoding="utf-8")   # post-reset
    live_sched.write_text(json.dumps({"weeks": []}), encoding="utf-8")

    arc = tmp_path / "archive" / "2025-26" / "config"
    arc.mkdir(parents=True)
    (arc / "RECORDS.json").write_text(json.dumps({
        "weekly_scores": {"Nick": [{"week": 1, "score": 100}],
                          "Hayden": [{"week": 1, "score": 10}]}}), encoding="utf-8")
    (arc / "SCHEDULE.json").write_text(json.dumps({
        "regular_season_weeks": 1,
        "weeks": [{"week": 1, "matchups": [{"manager_a": "Nick", "manager_b": "Hayden"}]}],
    }), encoding="utf-8")

    monkeypatch.setattr(mod, "ARCHIVE", tmp_path / "archive")
    r, s, season = mod.resolve_season_files(live_rec, live_sched)
    assert season == "2025-26"
    assert r == arc / "RECORDS.json"
    assert s == arc / "SCHEDULE.json"


def test_live_records_win_when_they_have_data(mod, tmp_path, monkeypatch):
    live_rec = tmp_path / "RECORDS.json"
    live_sched = tmp_path / "SCHEDULE.json"
    live_rec.write_text(json.dumps({"weekly_scores": {"Nick": [{"week": 1, "score": 1}]}}),
                        encoding="utf-8")
    live_sched.write_text(json.dumps({"weeks": []}), encoding="utf-8")
    monkeypatch.setattr(mod, "ARCHIVE", tmp_path / "nope")
    r, s, season = mod.resolve_season_files(live_rec, live_sched)
    assert season is None and r == live_rec


def test_the_board_is_short_a_pick_in_the_cup_winners_keeper_round(mod, capsys,
                                                                   monkeypatch):
    """2027-28: the Cup winner keeps 6, so round 10 has three picks, not four.

    The old script printed one number of rounds for everybody and tallied
    against it. Applied to 2027-28 that hands the Cup winner a tenth pick he
    does not have and reports the board as even.
    """
    import modules.data_loader as dl
    monkeypatch.setitem(dl.KEEPER_RULES["cup_winners"], "2026-27", "Benton")
    monkeypatch.setattr("sys.argv", ["b", "--season", "2027-28"])

    rc = mod.main()
    out = capsys.readouterr().out

    assert "Keepers for 2027-28 are NOT uniform" in out
    assert "Benton   keeps 6" in out and "drafts rounds 1-9" in out
    assert "(keeper: Benton)" in out, "round 10 must show Benton's slot as a keeper"
    assert "expected 39" in out, "39 live picks, not 40"
    assert rc in (0, 1)


def test_a_uniform_season_prints_no_asymmetry_notice(mod, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["b"])
    mod.main()
    out = capsys.readouterr().out
    assert "are NOT uniform" not in out
    assert "(keeper:" not in out


def test_regular_season_boundary_is_weeks_not_rounds(mod):
    """The fallback used to be total_draft_rounds -- a round count, as weeks."""
    from modules.data_loader import regular_season_weeks_for
    _, _, _, reg = mod.regular_season_results(
        {"weekly_scores": {}}, {"weeks": []}, "2026-27")
    assert reg == regular_season_weeks_for("2026-27") == 15
    _, _, _, reg = mod.regular_season_results(
        {"weekly_scores": {}}, {"weeks": []}, "2021-22")
    assert reg == 20
