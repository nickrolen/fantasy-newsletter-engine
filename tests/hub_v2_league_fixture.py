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


def _m(a, ap, b, bp):
    return {"a": a, "a_pts": ap, "b": b, "b_pts": bp}


def PRE_ERA():
    """5f: the made-up league's two pre-Yahoo seasons, in full (standings and
    brackets), consistent the way league.pre_era_season(s) checks them."""
    def st(rows):
        return [{"finish": i + 1, "manager": m, "team": t, "w": w, "l": 21 - w, "pts": p}
                for i, (m, t, w, p) in enumerate(rows)]
    return {"titles_won": {"Marcus": 1, "Tyler": 1}, "playoff_championships": {"Dana": 1, "Jordan": 1},
            "seasons": {
                "2014-15": {"league_champion": "Marcus", "league_runner_up": "Dana",
                            "playoff_champion": "Dana", "playoff_runner_up": "Marcus", "regular_season_games": 21,
                            "standings": st([("Marcus", "Old Cannons", 14, 22100.5), ("Dana", "Early Dana", 12, 22400.0),
                                             ("Tyler", "First Zone", 9, 21000.25), ("Jordan", "Jordan One", 7, 19500.0)]),
                            "bracket": {"semifinals": [_m("Marcus", 1100.5, "Jordan", 950.0),
                                                       _m("Dana", 1200.0, "Tyler", 1150.75)],
                                        "final": _m("Dana", 1300.25, "Marcus", 1250.0),
                                        "third_place": _m("Tyler", 1000.0, "Jordan", 900.5)}},
                "2016-17": {"league_champion": "Tyler", "league_runner_up": "Marcus",
                            "playoff_champion": "Jordan", "playoff_runner_up": "Tyler", "regular_season_games": 21,
                            "standings": st([("Tyler", "Tyler's Team", 16, 28000.0), ("Marcus", "Cannons Two", 11, 26000.0),
                                             ("Jordan", "Jordan Two", 9, 26500.5), ("Dana", "Dana Again", 6, 22000.0)]),
                            "bracket": {"semifinals": [_m("Tyler", 1400.0, "Dana", 1300.0),
                                                       _m("Jordan", 1350.0, "Marcus", 1200.0)],
                                        "final": _m("Jordan", 1500.0, "Tyler", 1400.25),
                                        "third_place": _m("Marcus", 1300.0, "Dana", 1100.0)}}}}


# =============================================================================
# MC2: the made-up league plays EVERY league season, consistently
# =============================================================================
# 2014-15 and 2016-17: PRE_ERA (standings and brackets). 2017-18 to 2025-26:
# every week's result (all_matchups), and from them the standings, the
# brackets, LEAGUEHISTORY's careers and the titles, so League > All-time,
# Champions, the trophy case and the manager card agree by construction
# (tests/test_mc2_manager.py checks it). 2023-24 is a made-up stoppage (19
# weeks, no bracket); 2020-21 ran 16 regular weeks and 2021-22 20.
YAHOO = [f"{y}-{str(y + 1)[2:]}" for y in range(2017, 2026)]
REG_THROUGH = {s: 21 for s in YAHOO} | {"2020-21": 16, "2021-22": 20, "2023-24": 19}
NO_BRACKET = {"2023-24": "a made-up stoppage"}
# the regular-season finish, 1st to 4th, and the bracket: (1 v 4 winner, 2 v 3 winner, final winner, 3rd-place winner)
WORLD_ORDER = {
    "2017-18": ["Dana", "Marcus", "Tyler", "Jordan"], "2018-19": ["Marcus", "Jordan", "Dana", "Tyler"],
    "2019-20": ["Tyler", "Marcus", "Jordan", "Dana"], "2020-21": ["Jordan", "Dana", "Marcus", "Tyler"],
    "2021-22": ["Marcus", "Tyler", "Jordan", "Dana"], "2022-23": ["Dana", "Tyler", "Marcus", "Jordan"],
    "2023-24": ["Jordan", "Marcus", "Tyler", "Dana"], "2024-25": ["Marcus", "Tyler", "Dana", "Jordan"],
    "2025-26": ["Tyler", "Marcus", "Jordan", "Dana"]}
WORLD_BRACKET = {
    "2017-18": ("Dana", "Tyler", "Tyler", "Marcus"), "2018-19": ("Marcus", "Jordan", "Marcus", "Dana"),
    "2019-20": ("Dana", "Marcus", "Marcus", "Tyler"), "2020-21": ("Jordan", "Marcus", "Jordan", "Tyler"),
    "2021-22": ("Marcus", "Jordan", "Jordan", "Dana"), "2022-23": ("Dana", "Tyler", "Dana", "Marcus"),
    "2024-25": ("Marcus", "Dana", "Marcus", "Jordan"), "2025-26": ("Tyler", "Jordan", "Jordan", "Marcus")}
# each manager's team name by season (the current one is the payload's)
OLD_NAMES = {"Marcus": {"2017-18": "Brick City", "2018-19": "Brick City", "2019-20": "Pump Fake Nation",
                        "2020-21": "Pump Fake Nation"},
             "Dana": {"2017-18": "Dana's Dimes", "2018-19": "Dana's Dimes"}}
# a gap in the record book's sense: who wins a regular-season meeting (k = the pair's k-th meeting that season)
UPSET = {1: {1, 3, 5, 8, 10}, 2: {2, 5, 9}, 3: {4, 11}}


def _h(*xs) -> int:
    import hashlib
    return int(hashlib.sha256("|".join(map(str, xs)).encode()).hexdigest()[:8], 16)


def _game(s, w, a, b, win):
    hi = 1450.0 + 4 * w + _h(s, w, a, b, "w") % 260 + _h(s, a) % 40
    lo = hi - 15.5 - _h(s, w, a, b, "l") % 330
    sa, sb = (hi, round(lo, 2)) if win == a else (round(lo, 2), hi)
    sa, sb = round(sa, 2), round(sb, 2)
    return {"season": s, "week": w, "manager_a": a, "manager_b": b, "score_a": sa, "score_b": sb,
            "winner": win, "loser": b if win == a else a, "margin": round(abs(sa - sb), 2)}


def world_matchups() -> list:
    out = []
    for s in YAHOO:
        order = WORLD_ORDER[s]
        rk = {m: i for i, m in enumerate(order)}
        met: dict = {}
        reg = REG_THROUGH[s]
        for w in range(1, reg + 1):
            for a, b in PAIRS[(w - 1) % 3]:
                key = tuple(sorted((a, b)))
                k = met.get(key, 0)
                met[key] = k + 1
                good, bad = (a, b) if rk[a] < rk[b] else (b, a)
                gap = abs(rk[a] - rk[b])
                out.append(_game(s, w, a, b, bad if k in UPSET[gap] else good))
        if s in NO_BRACKET:
            continue
        w1, w2, fin, third = WORLD_BRACKET[s]
        o = order
        semis = [(o[0], o[3], w1), (o[1], o[2], w2)]
        for a, b, win in semis:
            out.append(_game(s, reg + 1, a, b, win))
        winners = [x[2] for x in semis]
        losers = [a if win == b else b for a, b, win in semis]
        out.append(_game(s, reg + 2, winners[0], winners[1], fin))
        out.append(_game(s, reg + 2, losers[0], losers[1], third))
    return out


def world_standings(matchups=None) -> list:
    """all_standings rows from the games, by the one ranking rule
    (data_loader.standings_order) and the bracket's single games."""
    from modules.data_loader import Record, standings_order
    matchups = world_matchups() if matchups is None else matchups
    rows = []
    for s in YAHOO:
        games = [g for g in matchups if g["season"] == s]
        reg = REG_THROUGH[s]
        allw = {m: [0, 0, 0] for m in MGRS}
        regw = {m: Record() for m in MGRS}
        h2h = {m: {} for m in MGRS}
        pts = {m: 0.0 for m in MGRS}
        rpts = {m: 0.0 for m in MGRS}
        for g in games:
            a, b = g["manager_a"], g["manager_b"]
            pts[a] += g["score_a"]
            pts[b] += g["score_b"]
            allw[g["winner"]][0] += 1
            allw[g["loser"]][1] += 1
            if g["week"] <= reg:
                rpts[a] += g["score_a"]
                rpts[b] += g["score_b"]
                regw[g["winner"]] = regw[g["winner"]].add("win")
                regw[g["loser"]] = regw[g["loser"]].add("loss")
                for x, y, o in ((g["winner"], g["loser"], "win"), (g["loser"], g["winner"], "loss")):
                    h2h[x][y] = h2h[x].get(y, Record()).add(o)
        order = standings_order(regw, h2h, rpts, list(MGRS))
        if order != WORLD_ORDER[s]:
            raise AssertionError(f"the made-up {s} finishes {order}, not {WORLD_ORDER[s]}")
        place = {}
        if s not in NO_BRACKET:
            w1, w2, fin, third = WORLD_BRACKET[s]
            fl = [g for g in games if g["week"] == reg + 2]
            final = next(g for g in fl if {g["manager_a"], g["manager_b"]} == {w1, w2})
            cons = next(g for g in fl if g is not final)
            place = {final["winner"]: 1, final["loser"]: 2, cons["winner"]: 3, cons["loser"]: 4}
        ag = sorted(MGRS, key=lambda m: (-allw[m][0], -pts[m], m))
        for m in MGRS:
            rows.append({"season": s, "manager": m, "rank": ag.index(m) + 1, "rank_basis": "all_games_record",
                         "wins": allw[m][0], "losses": allw[m][1], "ties": 0, "points_for": round(pts[m], 1),
                         "reg_wins": regw[m].wins, "reg_losses": regw[m].losses, "reg_ties": 0,
                         "regular_season_rank": order.index(m) + 1, "playoff_rank": place.get(m)})
    return rows


def world_leaguehistory(standings, matchups, current_scores) -> list:
    """LEAGUEHISTORY.xlsx's rows: the careers through 2025-26 (the pre-Yahoo
    seasons + the games), the titles as the standings and PRE_ERA give them."""
    pre = PRE_ERA()["seasons"]
    out = []
    for m in MGRS:
        w = sum(x["w"] for v in pre.values() for x in v["standings"] if x["manager"] == m)
        l = sum(x["l"] for v in pre.values() for x in v["standings"] if x["manager"] == m)
        w += sum(r["reg_wins"] for r in standings if r["manager"] == m)
        l += sum(r["reg_losses"] for r in standings if r["manager"] == m)
        pw = pl = 0
        for v in pre.values():
            br = v["bracket"]
            for g in br["semifinals"] + [br["final"], br["third_place"]]:
                if m in (g["a"], g["b"]):
                    won = (g["a_pts"] > g["b_pts"]) == (g["a"] == m)
                    pw += won
                    pl += not won
        for g in matchups:
            if g["week"] > REG_THROUGH[g["season"]] and m in (g["manager_a"], g["manager_b"]):
                pw += g["winner"] == m
                pl += g["loser"] == m
        titles = sum(1 for v in pre.values() if v["league_champion"] == m) + \
            sum(1 for r in standings if r["manager"] == m and r["regular_season_rank"] == 1)
        ptitles = sum(1 for v in pre.values() if v["playoff_champion"] == m) + \
            sum(1 for r in standings if r["manager"] == m and r["playoff_rank"] == 1)
        done = sum(x["pts"] for v in pre.values() for x in v["standings"] if x["manager"] == m) + \
            sum(r["points_for"] for r in standings if r["manager"] == m)
        cur = sum(current_scores[w_][m] for w_ in current_scores)
        out.append({"manager_name": m, "seasons_completed": 11, "regular_season_record": f"({w}-{l})",
                    "playoff_record": f"({pw}-{pl})", "titles_won": titles, "playoff_championships": ptitles,
                    "total_points_scored_to_date": round(done + cur, 2), "total_points_current_season": cur})
    return out


def world_teams(p) -> dict:
    return {s: {f"t.{i}": {"manager": m, "team_name": (OLD_NAMES.get(m) or {}).get(s) or p["v2"]["teams"][m]["team"]}
                for i, m in enumerate(MGRS)} for s in YAHOO}


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
    out = {f"{key}_top10": [_rec_entry(i) for i in range(3)] for key, *_rest in league.RECORD_BOOK}
    # MC2: the franchise player per manager (backfill_player_records.franchise_badges_from's shape)
    out["franchise_badges"] = {m: {"player": f"{m} Guard", "total_fp": 18402.5 - 900 * i, "gp": 512 - 30 * i,
                                   "seasons": 7 - i, "first": "2017-18", "last": "2024-25"}
                               for i, m in enumerate(MGRS)}
    return out


def potw_log() -> dict:
    """2025-26 week 1 in the league log for its Player of the Week (made up):
    two started games and a bench game that must not count."""
    rows = []
    for d, st, pts in (("2025-10-21", True, 61.5), ("2025-10-23", False, 99.0), ("2025-10-25", True, 48.0)):
        rows.append({"season_key": "2025-26", "week": 1, "date": d, "manager": "Marcus", "player_name": "Marcus Big",
                     "fantasy_points": pts, "started": st, "had_game": True, "is_injured": False})
    return {"2025-26": rows}


def inputs(p: dict) -> dict:
    import awards_fixture as AF
    from modules.data_loader import results_from
    from modules.hub_v2 import league
    teams = {m: {k: p["v2"]["teams"][m][k] for k in ("slot", "mono", "team")} for m in MGRS}
    # Home's records (the power rows) and the Standings count the same weeks (4c5)
    recs = results_from(SCORES, {w["week"]: w["matchups"] for w in weeks()}, 15)[0]
    power = copy.deepcopy(p["power"])
    for r in power["rows"]:
        r["record"] = str(recs[r["manager"]])
    potw = {"2026-27": [{"week": w, "player": f"{MGRS[w % 4]} Guard", "manager": MGRS[w % 4],
                         "total_fp": 210.5 + w, "games": 4, "fppg": 52.6} for w in range(1, 9)],
            "2025-26": [{"week": 1, "player": "Marcus Big", "manager": "Marcus"},
                        {"week": 2, "player": "Tyler Big", "manager": "Tyler"}]}
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
    # 5d1: a punted season (H56: shown by team, no pick numbers), so the tap sweep reaches the by-team table
    past += [{"season": "2023-24", "pick_number": i + 1, "round": 1, "manager": m, "player_key": str(300 + i),
              "player_name": f"{m} Guard", "is_keeper": False} for i, m in enumerate(MGRS)]
    past += [{"season": "2023-24", "pick_number": 5 + i, "round": 2, "manager": m, "player_key": str(310 + i),
              "player_name": f"{m} Big", "is_keeper": True} for i, m in enumerate(MGRS)]
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
    games = world_matchups()
    standings_rows = world_standings(games)
    return {
        "managers": list(MGRS), "teams": teams, "season": "2026-27",
        "now": datetime.fromisoformat(p["generated_at"]), "reg_weeks": 15, "weeks": weeks(),
        "weekly_scores": _scores_by_manager(), "records_week": 8, "power": power,
        "history_rows": history_rows(), "reports": reports(),
        "season_structure": {s: ({"regular_through": REG_THROUGH[s], "bracket": False, "note": NO_BRACKET[s]}
                                 if s in NO_BRACKET else {"regular_through": REG_THROUGH[s], "bracket": True})
                             for s in YAHOO},
        "pre_data_era": PRE_ERA(),
        "cup_winners": {"2026-27": None},
        # MC2: careers and titles from the made-up world (consistent with the standings and PRE_ERA)
        "leaguehistory": world_leaguehistory(standings_rows, games, SCORES),
        "all_standings": standings_rows, "all_matchups": games, "all_drafts": past,
        "all_trades": [{"season": "2025-26", "timestamp": None, "date": "2025-12-08", "trader_team": "Glass Cannons",
                        "tradee_team": "Zone Defense", "trader_manager": "Marcus", "tradee_manager": "Tyler",
                        "players": [{"player_name": "Marcus Wing", "from_manager": "Marcus", "to_manager": "Tyler",
                                     "from_team": "Glass Cannons", "to_team": "Zone Defense"},
                                    {"player_name": "Tyler Wing", "from_manager": "Tyler", "to_manager": "Marcus",
                                     "from_team": "Zone Defense", "to_team": "Glass Cannons"}],
                        "picks": {"Marcus": ["2026 4th (Marcus)"], "Tyler": ["2026 8th (Tyler)"]}},
                       # 5d1: a past season's trade with Yahoo's structured picks (H56) and one reversed by a ruling
                       {"season": "2023-24", "timestamp": None, "date": "2024-01-15", "trader_team": "Glass Cannons",
                        "tradee_team": "Pick & Roll Call", "trader_manager": "Marcus", "tradee_manager": "Dana",
                        "players": [{"player_name": "Marcus Guard", "from_manager": "Marcus", "to_manager": "Dana",
                                     "from_team": "Glass Cannons", "to_team": "Pick & Roll Call"}],
                        "draft_picks": [{"round": 1, "draft": "2024-25", "original_manager": "Dana",
                                         "from_manager": "Dana", "to_manager": "Marcus", "source": "yahoo",
                                         "draft_how": "rule"}],
                        "draft_picks_reversed": [{"round": 3, "draft": "2024-25", "original_manager": "Marcus",
                                                  "from_manager": "Marcus", "to_manager": "Dana", "source": "yahoo",
                                                  "draft_how": "rule", "reversed": "made up"}]}],
        "all_teams": world_teams(p),
        "season_teams": {},
        "trades_now": [{"season": "2026-27", "timestamp": None, "date": "2026-11-20", "trader_team": "Pick & Roll Call",
                        "tradee_team": "Fast Break Bros", "trader_manager": "Dana", "tradee_manager": "Jordan",
                        "players": [{"player_name": "Dana Wing", "from_manager": "Dana", "to_manager": "Jordan",
                                     "from_team": "Pick & Roll Call", "to_team": "Fast Break Bros"}]}],
        "potw": potw, "potw_fill": league.potw_from_log(potw, potw_log()),
        "banked": {}, "cup_weeks": {**{s: [] for s in YAHOO}, "2026-27": [22, 23]},
        "awards_rec": AF.races(odds=True),
        "awards_past": AF.past_blob(), "awards_past_error": None,
        "records_alltime": records_alltime(),
        "draft_current": {"season": "2026-27", "picks": picks_cur}, "draft_ovr": cache,
        "live_then": live_then, "live_error": None, "now_ovr": now_ovr, "ratings_error": None,
        "newsletter": nl, "issue_plain": plain, "issue_heads": {f: "A made-up headline" for f in plain},
    }


def sync_power(inp: dict) -> dict:
    """After a test changes the weekly scores: Home's records (the power rows)
    follow them, as the real build's one source makes them (4c5)."""
    from modules.data_loader import results_from
    sc = {}
    for m, es in inp["weekly_scores"].items():
        for e in es:
            sc.setdefault(int(e["week"]), {})[m] = float(e["score"])
    recs = results_from(sc, {w["week"]: w["matchups"] for w in inp["weeks"]}, inp["reg_weeks"])[0]
    inp["power"] = copy.deepcopy(inp["power"])
    for r in inp["power"]["rows"]:
        r["record"] = str(recs[r["manager"]])
    return inp


# MC2: the manager card's own inputs beyond the League's (made up): no ages on
# record but the keepers' own, this season's adds per manager, the real config
# (its payouts_by_season)
AGES = {"seasons": {"2023-24": {"ages": {f"{m} Big": 24 + i for i, m in enumerate(MGRS)}},
                    "2026-27": {"ages": {f"{m} Big": 27 + i for i, m in enumerate(MGRS)}}}}
ADDS_NOW = {"Marcus": 11, "Tyler": 7, "Dana": 4, "Jordan": 9}


def manager_extra() -> dict:
    from modules.data_loader import _LEAGUE_CONFIG
    return {"bbref_ages": AGES, "adds_now": dict(ADDS_NOW), "config": _LEAGUE_CONFIG}


def add_league(p: dict, managers: bool = True) -> dict:
    from modules.hub_v2 import league, manager
    inp = inputs(p)
    p["v2"]["league"], p["v2"]["league_history"] = league.build(inp)
    if managers:                                  # MC2: the cards, as data.league_soft adds them
        p["v2"]["league"]["managers"] = manager.build(inp, league.week_results(inp), manager_extra())
    return p
