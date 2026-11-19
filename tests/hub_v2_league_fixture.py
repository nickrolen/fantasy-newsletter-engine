"""The synthetic League (4c4): made-up inputs for modules/hub_v2/league.build,
the same four made-up teams as tests/test_hub_v2.py. No real name anywhere.

inputs(p) -> the dict league.gather would return, for the synthetic payload p
add_league(p) -> p with v2.league and v2.league_history (as attach_players
puts the side file back), by the real league.build
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=-8))
MGRS = ["Marcus", "Tyler", "Dana", "Jordan"]
WEEK1 = date(2026, 10, 5)
# a week's pairings, rotating
PAIRS = [[("Marcus", "Tyler"), ("Dana", "Jordan")], [("Marcus", "Dana"), ("Tyler", "Jordan")],
         [("Marcus", "Jordan"), ("Tyler", "Dana")]]
# weeks 1-8: Tyler and Jordan end level at 4-3-1 and level head to head (1-1-1): points decide;
# week 3's Tyler-Jordan is a TIE (a T for both); Marcus's last result is a win run
SCORES = {
    1: {"Marcus": 1500.0, "Tyler": 1400.0, "Dana": 1300.0, "Jordan": 1350.0},
    2: {"Marcus": 1450.0, "Dana": 1420.0, "Tyler": 1388.0, "Jordan": 1388.0},
    3: {"Marcus": 1320.0, "Jordan": 1410.0, "Tyler": 1500.0, "Dana": 1480.0},
    4: {"Marcus": 1610.0, "Tyler": 1500.0, "Dana": 1450.0, "Jordan": 1460.0},
    5: {"Marcus": 1555.0, "Dana": 1600.0, "Tyler": 1470.0, "Jordan": 1300.0},
    6: {"Marcus": 1700.0, "Jordan": 1450.0, "Tyler": 1525.0, "Dana": 1490.0},
    7: {"Marcus": 1650.0, "Tyler": 1660.0, "Dana": 1700.0, "Jordan": 1500.0},
    8: {"Marcus": 1720.0, "Dana": 1500.0, "Tyler": 1410.0, "Jordan": 1580.0},
}


def weeks() -> list:
    out = []
    for k in range(1, 16):
        a = WEEK1 + timedelta(days=7 * (k - 1))
        pr = PAIRS[(k - 1) % 3]
        out.append({"week": k, "start_date": a.isoformat(), "end_date": (a + timedelta(days=6)).isoformat(),
                    "matchups": [{"manager_a": x, "manager_b": y} for x, y in pr]})
    return out


def _scores_by_manager() -> dict:
    out = {m: [] for m in MGRS}
    for w, sc in SCORES.items():
        for m, v in sc.items():
            out[m].append({"week": w, "score": v})
    return out


def _run(at: datetime, kind: str, week: int, odds: dict) -> dict:
    return {"run_id": at.isoformat() + "-" + kind, "produced_by": "synthetic", "as_of": at.isoformat(),
            "engine": {"commit": "abc1234", "dirty": False}, "engine_key": "abc1234", "seed": 1,
            "num_simulations": 1000, "title_odds": odds, "kind": kind, "week": week}


def history_rows() -> list:
    rows = []
    base = {"Marcus": 30.0, "Tyler": 30.0, "Dana": 20.0, "Jordan": 20.0}
    t = datetime(2026, 10, 27, 0, 5, tzinfo=TZ)        # week 4's first night: the history begins
    step = 0
    while t < datetime(2026, 12, 2, 0, 6, tzinfo=TZ):
        step += 1
        m = dict(base)
        m["Marcus"] = min(70.0, 30.0 + step * 1.1)
        m["Tyler"] = max(5.0, 30.0 - step * 0.5)
        m["Dana"] = max(5.0, 20.0 - step * 0.3)
        m["Jordan"] = 100.0 - m["Marcus"] - m["Tyler"] - m["Dana"]
        wk = 1 + (t.date() - WEEK1).days // 7
        rows.append(_run(t, "nightly", wk, {k: round(v, 3) for k, v in m.items()}))
        if t.weekday() == 0:                            # each Monday's closing line, priced in the evening
            c = {k: round(v, 3) for k, v in m.items()}
            c["Marcus"] = round(c["Marcus"] + 0.7, 3)
            c["Jordan"] = round(c["Jordan"] - 0.7, 3)
            rows.append(_run(t.replace(hour=18, minute=55), "closing", wk, c))
        t += timedelta(days=1)
    return rows


def reports() -> dict:
    out = {}
    for wk, ranks in ((1, ["Tyler", "Marcus", "Jordan", "Dana"]), (2, ["Marcus", "Tyler", "Dana", "Jordan"]),
                      (3, ["Marcus", "Dana", "Tyler", "Jordan"])):
        a = WEEK1 + timedelta(days=7 * (wk - 1))
        odds = [40.0, 30.0, 20.0, 10.0]
        out[wk] = {"metadata": {"run_mode": "publish", "week": wk,
                                "date_range": {"start": a.isoformat(), "end": (a + timedelta(days=6)).isoformat()}},
                   "power_rankings": [{"rank": i + 1, "manager": m, "title_odds": odds[i], "record": f"{wk - 1}-1"}
                                      for i, m in enumerate(ranks)]}
    return out


def _rec_entry(i: int) -> dict:
    """One made-up record-book row that every RECORD_BOOK formatter can read."""
    m = MGRS[i % 4]
    o = MGRS[(i + 1) % 4]
    return {"score": 2000.0 - 10 * i, "manager": m, "season": "2024-25", "week": 1 + i % 3, "margin": 300.5 - i,
            "winner": m, "loser": o, "total_fp": 3000.0 - i, "length": 9 - i, "wins": 15 - i, "losses": 5 + i,
            "fantasy_points": 90.5 - i, "player_name": f"{m} Guard", "date": "2024-10-20", "delta": 12.5 - i,
            "weekly_fp": 300.5 - i, "weekly_fppg": 70.5 - i, "games": 4, "fppg": 55.5 - i, "count": 40 - i, "gp": 60,
            "consecutive_seasons": 7 - i, "combined_fp": 500.5 - i, "player1": f"{m} Guard", "player2": f"{m} Big",
            "post_trade_fp": 2500.0 - i}


def records_alltime() -> dict:
    from modules.hub_v2 import league
    return {f"{key}_top10": [_rec_entry(i) for i in range(3)] for key, *_rest in league.RECORD_BOOK}


def all_matchups() -> list:
    out = []
    for s in ("2024-25", "2025-26"):
        for w in range(1, 24):
            pr = PAIRS[(w - 1) % 3]
            for j, (a, b) in enumerate(pr):
                sa = 1500.0 + 10 * w + 37 * j
                sb = 1490.0 + 13 * w - 5 * j
                out.append({"season": s, "week": w, "manager_a": a, "manager_b": b, "score_a": sa, "score_b": sb,
                            "winner": a if sa > sb else b, "loser": b if sa > sb else a, "margin": abs(sa - sb)})
    return out


def inputs(p: dict) -> dict:
    teams = {m: {k: p["v2"]["teams"][m][k] for k in ("slot", "mono", "team")} for m in MGRS}
    nl = p["newsletter"]
    files = ([nl["current"]] if nl.get("current") else []) + list(nl.get("archive") or [])
    plain = {i["file"]: i["file"].replace(".enc", ".html") for i in files}
    picks_cur = []
    n = 0
    for rd in (1, 2, 3):
        for m in MGRS:
            if rd == 3 and m != "Jordan":
                continue                                # Jordan made one more pick (a made-up pick trade)
            n += 1
            picks_cur.append({"season": "2026-27", "pick_number": n, "round": rd, "manager": m,
                              "player_key": str(100 + n), "player_name": f"{m} Guard" if rd == 1 else f"{m} Wing" if rd == 2
                              else "Free Guy", "is_keeper": False})
    for m in MGRS:
        n += 1
        picks_cur.append({"season": "2026-27", "pick_number": n, "round": 4, "manager": m, "player_key": str(100 + n),
                          "player_name": f"{m} Big", "is_keeper": True})
    past = [{"season": "2025-26", "pick_number": i + 1, "round": 1, "manager": m, "player_key": str(200 + i),
             "player_name": f"{m} Guard", "is_keeper": False} for i, m in enumerate(MGRS)]
    cache = {"schema": 1, "deadline_fraction": 0.78, "seasons": {"2025-26": {
        "season": "2025-26", "open": "2025-10-21", "deadline": "2026-02-28",
        "picks": [{"pick_number": i + 1, "round": 1, "manager": m, "player": f"{m} Guard", "is_keeper": False,
                   "then": [74, None, 80, 66][i],
                   "then_reason": [None, "no earlier season of his in the league log: his opening-day level is the league average",
                                   None, None][i],
                   "later": [81, 77, None, 66][i], "later_reason": [None, None, "not on a roster that day", None][i]}
                  for i, m in enumerate(MGRS)]}}}
    now_ovr = {f"{m} {k}": v for m in MGRS for k, v in (("Guard", 88), ("Wing", 71), ("Big", 79))}
    live_then = {"open": "2026-10-05", "players": {
        **{f"{m} Guard": (84, None) for m in MGRS}, **{f"{m} Wing": (73, None) for m in MGRS},
        **{f"{m} Big": (None, "no earlier season of his in the league log: his opening-day level is the league "
                              "average") for m in MGRS}, "Free Guy": (61, None)}}
    standings_rows = []
    for s, (c, r, f1) in (("2024-25", ("Marcus", "Dana", "Marcus")), ("2025-26", ("Jordan", "Tyler", "Tyler"))):
        for i, m in enumerate(MGRS):
            standings_rows.append({"season": s, "manager": m, "rank": i + 1, "wins": 12, "losses": 11, "ties": 0,
                                   "points_for": 36000.0, "reg_wins": 11, "reg_losses": 10,
                                   "regular_season_rank": 1 if m == f1 else 2 + (i % 3) if m != f1 else 1,
                                   "playoff_rank": 1 if m == c else 2 if m == r else 3 + (i % 2)})
    for i, m in enumerate(MGRS):                         # a season with no bracket played
        standings_rows.append({"season": "2023-24", "manager": m, "rank": i + 1, "wins": 10, "losses": 9, "ties": 0,
                               "points_for": 30000.0, "reg_wins": 10, "reg_losses": 9,
                               "regular_season_rank": i + 1, "playoff_rank": None})
    return {
        "managers": list(MGRS), "teams": teams, "season": "2026-27",
        "now": datetime.fromisoformat(p["generated_at"]), "reg_weeks": 15, "weeks": weeks(),
        "weekly_scores": _scores_by_manager(), "records_week": 8, "power": copy.deepcopy(p["power"]),
        "history_rows": history_rows(), "reports": reports(),
        "season_structure": {"2023-24": {"regular_through": 19, "bracket": False, "note": "a made-up stoppage"},
                             "2024-25": {"regular_through": 21, "bracket": True},
                             "2025-26": {"regular_through": 21, "bracket": True}},
        "pre_data_era": {"titles_won": {"Marcus": 1, "Tyler": 1}, "playoff_championships": {"Dana": 1, "Jordan": 1}},
        "cup_winners": {"2026-27": None},
        "leaguehistory": [{"manager_name": m, "seasons_completed": 11,
                           "regular_season_record": f"({100 + 3 * i}-{90 - 2 * i})", "playoff_record": f"({8 + i}-{9 - i})",
                           "titles_won": i, "playoff_championships": 3 - i,
                           "total_points_scored_to_date": 330000.5 + 1000 * i + sum(SCORES[w][m] for w in SCORES),
                           "total_points_current_season": sum(SCORES[w][m] for w in SCORES)}
                          for i, m in enumerate(MGRS)],
        "all_standings": standings_rows, "all_matchups": all_matchups(), "all_drafts": past,
        "all_trades": [{"season": "2025-26", "timestamp": None, "date": "2025-12-08", "trader_team": "Glass Cannons",
                        "tradee_team": "Zone Defense", "trader_manager": "Marcus", "tradee_manager": "Tyler",
                        "players": [{"player_name": "Marcus Wing", "from_manager": "Marcus", "to_manager": "Tyler",
                                     "from_team": "Glass Cannons", "to_team": "Zone Defense"},
                                    {"player_name": "Tyler Wing", "from_manager": "Tyler", "to_manager": "Marcus",
                                     "from_team": "Zone Defense", "to_team": "Glass Cannons"}],
                        "picks": {"Marcus": ["2026 4th (Marcus)"], "Tyler": ["2026 8th (Tyler)"]}}],
        "all_teams": {s: {f"t.{i}": {"manager": m, "team_name": p["v2"]["teams"][m]["team"]}
                          for i, m in enumerate(MGRS)} for s in ("2023-24", "2024-25", "2025-26")},
        "season_teams": {},
        "trades_now": [{"season": "2026-27", "timestamp": None, "date": "2026-11-20", "trader_team": "Pick & Roll Call",
                        "tradee_team": "Fast Break Bros", "trader_manager": "Dana", "tradee_manager": "Jordan",
                        "players": [{"player_name": "Dana Wing", "from_manager": "Dana", "to_manager": "Jordan",
                                     "from_team": "Pick & Roll Call", "to_team": "Fast Break Bros"}]}],
        "potw": {"2026-27": [{"week": w, "player": f"{MGRS[w % 4]} Guard", "manager": MGRS[w % 4],
                              "total_fp": 210.5 + w, "games": 4, "fppg": 52.6} for w in range(1, 9)],
                 "2025-26": [{"week": 1, "player": "Marcus Big", "manager": "Marcus"}]},
        "records_alltime": records_alltime(),
        "draft_current": {"season": "2026-27", "picks": picks_cur}, "draft_ovr": cache,
        "live_then": live_then, "live_error": None, "now_ovr": now_ovr, "ratings_error": None,
        "newsletter": nl, "issue_plain": plain, "issue_heads": {f: "A made-up headline" for f in plain},
    }


def add_league(p: dict) -> dict:
    from modules.hub_v2 import league
    p["v2"]["league"], p["v2"]["league_history"] = league.build(inputs(p))
    return p
