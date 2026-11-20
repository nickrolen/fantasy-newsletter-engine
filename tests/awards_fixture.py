"""A made-up awards season (4c5) for tests/test_awards.py and the hub's
synthetic League: the same four made-up managers as tests/test_hub_v2.py, a
made-up player pool, every input modules/awards.compute reads. No real name.

    inp(last="2026-11-10") -> the dict awards.gather would return, the log cut at `last`

The season: weeks of 7 days from Mon 2026-10-05, except WEEK 3, 14 days
(10-19 to 11-01: one week, one window, as the league's week 7). Games every
day but Sunday. Each manager starts a Star, a Wing and a Role player and
benches a Bench player who scores 70+ (bench points must never count).
- Tyler Wing is started but DNP every Tuesday (0 points, no game charged).
- Jordan adds Quinn Rookie (a 2026-27 rookie) from free agency on 10-12 for
  Jordan Role (one add/drop).
- Dana drops Dana Role and adds Pat Journey on 10-12 (two separate Yahoo
  rows, one-to-one in time), drops him 10-26, re-adds him 11-02 for Dana
  Bench: two stints, counted separately.
- Marcus's Role player was a preseason add (10-01).
- Marcus Star <-> Tyler Star trade on 10-19, Marcus sending a pick too.
- A voided add (Tyler, Void Guy) that never reaches the log.
- Prior seasons: Marcus Star (2024-25, 2025-26: improved), Tyler Star
  (declined), Dana Wing (10 prior games: under the 20 needed).
"""
from __future__ import annotations

from datetime import date, timedelta

SEASON = "2026-27"
MGRS = ["Marcus", "Tyler", "Dana", "Jordan"]
PAIRS = [[("Marcus", "Tyler"), ("Dana", "Jordan")], [("Marcus", "Dana"), ("Tyler", "Jordan")],
         [("Marcus", "Jordan"), ("Tyler", "Dana")]]
START = date(2026, 10, 5)
LAST = "2026-11-10"            # week 5's second day
CFG = {"history_top_n": 10, "shown": 5, "most_improved_min_games": 20, "most_improved_min_prior_games": 20,
       "most_improved_prior_spec": "P3", "bust_min_games": 10}
LP = {"spec": "P3", "k0_prior": 10.0, "k0_league_mean": 4.7}

LEVEL = {}
for i, m in enumerate(MGRS):
    LEVEL[f"{m} Star"] = 48.0 + 2 * i
    LEVEL[f"{m} Wing"] = 34.0 + i
    LEVEL[f"{m} Role"] = 24.0 + i
    LEVEL[f"{m} Bench"] = 72.0
LEVEL["Quinn Rookie"] = 40.0
LEVEL["Pat Journey"] = 30.0
PID = {n: 1000 + i for i, n in enumerate(sorted(LEVEL))}


def weeks() -> list:
    out, d = [], START
    for k in range(1, 16):
        n = 14 if k == 3 else 7
        out.append({"week": k, "start_date": d.isoformat(), "end_date": (d + timedelta(days=n - 1)).isoformat(),
                    "days": n, "matchups": [{"manager_a": a, "manager_b": b} for a, b in PAIRS[(k - 1) % 3]]})
        d += timedelta(days=n)
    return out


def week_of(day: str) -> int:
    for w in weeks():
        if w["start_date"] <= day <= w["end_date"]:
            return w["week"]
    raise KeyError(day)


def fp(name: str, d: date) -> float:
    return LEVEL[name] + ((d.toordinal() * 7 + len(name)) % 9) - 4 + 0.5 * (d.toordinal() % 2)


def plays(name: str, d: date) -> tuple:
    """(had_game, is_injured) for the NBA day."""
    if d.weekday() == 6:
        return False, False
    if name == "Tyler Wing" and d.weekday() == 1:
        return True, True
    if name == "Dana Role" and d > date(2026, 10, 11):          # out after week 1
        return True, True
    return True, False


def roster(m: str, d: date) -> list:
    """[(player, started)] for manager m on day d."""
    s = d.isoformat()
    star = {"Marcus": "Marcus Star", "Tyler": "Tyler Star"}.get(m, f"{m} Star")
    if s >= "2026-10-19" and m in ("Marcus", "Tyler"):
        star = {"Marcus": "Tyler Star", "Tyler": "Marcus Star"}[m]
    out = [(star, True), (f"{m} Wing", True)]
    if m == "Jordan":
        out.append(("Quinn Rookie", True) if s >= "2026-10-12" else ("Jordan Role", True))
    elif m == "Dana":
        if s < "2026-10-12":
            out.append(("Dana Role", True))
        elif s <= "2026-10-25" or s >= "2026-11-02":
            out.append(("Pat Journey", True))
    else:
        out.append((f"{m} Role", True))
    if not (m == "Dana" and s >= "2026-11-02"):
        out.append((f"{m} Bench", False))
    return out


def _row(season: str, week: int, d: date, m: str, n: str, started: bool, played=None) -> dict:
    hg, inj = plays(n, d) if played is None else played
    pts = 0.0 if (not hg or inj) else fp(n, d)
    return {"season_key": season, "week": week, "date": d.isoformat(), "manager": m, "player_name": n,
            "player_id": PID.get(n, 9999), "slot": "UTIL" if started else "BN", "fantasy_points": pts,
            "started": started, "nba_team": "AAA", "had_game": hg, "is_injured": inj}


def log(last: str = LAST) -> list:
    rows, d = [], START
    while d.isoformat() <= last:
        for m in MGRS:
            for n, st in roster(m, d):
                rows.append(_row(SEASON, week_of(d.isoformat()), d, m, n, st))
        d += timedelta(days=1)
    rows.sort(key=lambda r: (r["date"], r["manager"], r["player_name"]))
    return rows


def prior_log() -> dict:
    """{season: rows} for 2024-25 and 2025-26."""
    out = {}
    for season, d0, spec in (("2024-25", date(2024, 10, 22), {"Marcus Star": (25, 38.0)}),
                             ("2025-26", date(2025, 10, 21), {"Marcus Star": (30, 40.0), "Tyler Star": (30, 58.0),
                                                              "Dana Wing": (10, 30.0)})):
        rows = []
        for n, (g, lvl) in spec.items():
            for k in range(g):
                d = d0 + timedelta(days=k)
                r = _row(season, 1 + k // 7, d, "Marcus", n, True, (True, False))
                r["fantasy_points"] = lvl
                rows.append(r)
        out[season] = sorted(rows, key=lambda r: (r["date"], r["manager"], r["player_name"]))
    return out


def picks() -> list:
    out, n = [], 0
    for m in MGRS:
        out.append({"season": SEASON, "pick_number": None, "round": 10, "manager": m, "player_key": str(PID[f"{m} Star"]),
                    "player_name": f"{m} Star", "is_keeper": True})
    for kind in ("Wing", "Role", "Bench"):
        for m in MGRS:
            n += 1
            out.append({"season": SEASON, "pick_number": n, "round": 1 + n // 5, "manager": m,
                        "player_key": str(PID[f"{m} {kind}"]), "player_name": f"{m} {kind}", "is_keeper": False})
    return out


def trades() -> list:
    return [{"season": SEASON, "timestamp": None, "date": "2026-10-19", "week": 3,
             "trader_team": "Glass Cannons", "tradee_team": "Zone Defense",
             "trader_manager": "Marcus", "tradee_manager": "Tyler",
             "players": [{"player_name": "Marcus Star", "from_manager": "Marcus", "to_manager": "Tyler"},
                         {"player_name": "Tyler Star", "from_manager": "Tyler", "to_manager": "Marcus"}],
             "picks": {"Marcus": ["2027 2nd (Marcus)"], "Tyler": []}}]


def _p(action, name, m):
    side = {"manager": m, "type": "team"}
    fa = {"manager": None, "type": "freeagents"}
    return {"action": action, "name": name, "player_key": f"478.p.{PID.get(name, 9999)}",
            "from": fa if action == "add" else side, "to": side if action == "add" else fa}


def transactions() -> list:
    t = []

    def tx(day, ts, typ, players, rulings=()):
        t.append({"key": f"k{len(t)}", "league_day": day, "timestamp": ts, "status": "successful", "type": typ,
                  "players": players, "rulings": list(rulings), "row": "transaction", "time": day + "T10:00:00-07:00"})
    tx("2026-10-01", 1, "add", [_p("add", "Marcus Role", "Marcus")])
    tx("2026-10-12", 100, "drop", [_p("drop", "Dana Role", "Dana")])
    tx("2026-10-12", 101, "add", [_p("add", "Pat Journey", "Dana")])
    tx("2026-10-12", 102, "add/drop", [_p("add", "Quinn Rookie", "Jordan"), _p("drop", "Jordan Role", "Jordan")])
    tx("2026-10-13", 110, "add", [_p("add", "Void Guy", "Tyler")], [{"kind": "void", "player": "Void Guy"}])
    tx("2026-10-26", 200, "drop", [_p("drop", "Pat Journey", "Dana")])
    tx("2026-11-02", 300, "add/drop", [_p("add", "Pat Journey", "Dana"), _p("drop", "Dana Bench", "Dana")])
    return t


def preseason() -> dict:
    from modules.data_loader import PlayerIndex
    idx = PlayerIndex()
    for i, m in enumerate(MGRS):
        idx[f"{m} Star"] = LEVEL[f"{m} Star"] - 3          # beat
        idx[f"{m} Wing"] = LEVEL[f"{m} Wing"] + 6 + i      # short: busts
        idx[f"{m} Bench"] = LEVEL[f"{m} Bench"] + 1
        if m != "Jordan":
            idx[f"{m} Role"] = LEVEL[f"{m} Role"] + 2
    return {"by_name": idx, "file": "PLAYERLIST_made_up.xlsx", "fetched": "2026-10-01"}


def actuals(last: str = LAST) -> dict:
    players = {}
    for n in LEVEL:
        days, d = {}, START
        while d.isoformat() <= last:
            hg, inj = plays(n, d)
            g = int(hg and not inj)
            days[d.isoformat()] = [fp(n, d) if g else 0.0, g]
            d += timedelta(days=1)
        players[str(PID[n])] = {"name": n, "days": days}
    return {"first_day": START.isoformat(), "players": players}


def inp(last: str = LAST, *, rows: list = None, rookies: dict = None, extra_trades: list = None) -> dict:
    """The dict awards.gather returns, made up, the log cut at `last`."""
    from modules import keeper_history as kh
    from modules.data_loader import PlayerIndex
    rows = log(last) if rows is None else rows
    lg = {SEASON: rows, **prior_log()}
    inputs = kh.Inputs(log=lg, picks={SEASON: picks()}, trades=trades() + list(extra_trades or []))
    ws = weeks()
    wk_of = {}
    for w in ws:
        d0, d1 = date.fromisoformat(w["start_date"]), date.fromisoformat(w["end_date"])
        for i in range((d1 - d0).days + 1):
            wk_of[(d0 + timedelta(days=i)).isoformat()] = w["week"]
    act = actuals(last)
    by_id, by_name = {}, PlayerIndex()
    for pid, rec in act["players"].items():
        by_id[int(pid)] = rec
        by_name[rec["name"]] = rec
    rk = rookies if rookies is not None else {**{n: "2015-16" for n in LEVEL}, "Quinn Rookie": SEASON}
    return {"root": None, "season": SEASON, "inputs": inputs, "rows": rows, "weeks": ws, "reg": 15,
            "week_of": wk_of, "days": sorted({r["date"] for r in rows}), "cfg": dict(CFG), "quantile": 0.0,
            "lp": dict(LP), "transactions": transactions(), "ledger": [], "rookies": rk,
            "preseason": preseason(), "preseason_rel": "config/snapshots/PLAYERLIST_made_up.xlsx",
            "actuals_first": act["first_day"], "act_by_id": by_id, "act_by_name": by_name, "tie_value": 0.5}


def races(last: str = LAST) -> dict:
    """The hub's awards record (hub_state.awards_step's shape) for the
    synthetic League: the real engine on the made-up season."""
    from modules import awards as A
    i = inp(last)
    res = A.compute(i, last)
    lines = A.pending(i, [])
    return {"races": A.races(res, lines, i["cfg"]), "pending": lines, "through": last, "week": res["week"],
            "on_file": 0, "error": None, "seconds": 0.0}
