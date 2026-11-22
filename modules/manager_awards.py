"""manager_awards.py -- the manager awards (4c7 C; claude/HANDOFF_4C7_AWARDS_
EXTENSION_2026-11-22.md, 5D_NOTES_PART2 item 16 C). Every season, past and
present: this season live in League > Awards (modules/hub_state.awards_step),
past seasons in data/historical/AWARDS_PAST.json (modules/awards_past).

ONE INPUT: modules/awards' own `inp` (awards.gather this season, awards_past.
season_inputs a past one) and its compute() result on that inp, so every
award here counts the same rows, the same regular season and the same
replacement level R as the player awards. Through the regular season only
(the season's own regular_through; weeks 1-15 this season).

THE FOUR AWARDS (one row per manager, ranked; every manager is in the race)
- LINEUP MANAGER OF THE YEAR (the league's most important skill: LEAGUE_
  RULES, daily management; 5e, 4C7 decision 3): the share of ALL his daily
  starting slots that were filled = filled slots / (10 x days). A slot is
  filled when its player's NBA team played that day (the log's had_game:
  the player had a game, whether or not he then sat with an injury). The
  days are the regular season's days with an NBA game (a day on which any
  league player's team played), through the cut, on which his roster is
  logged. Players in an IL or IL+ slot are never starters. This is the fill
  rate the league measured for 2025-26 (Nick 73, Garrett 68, Hayden 67,
  Benton 66 over the whole season; this function, over the whole season,
  gives 72.4, 67.8, 66.1, 66.3: claude/5E_RESULT). It replaced 4c7's
  "started over fillable" (every winner scored 98.8-100%).
  RAISES if a day's starts exceed the ten seats (a broken log).
- DRAFT OF THE YEAR: the most PAR from his draft class: the players he
  drafted that season (keepers apart: they are shown beside it, never
  counted), in HIS starts in the regular season (draft_values.pick_game's
  game set), PAR as the awards count it. The pick order is not needed. A
  season without a draft list (2018-19, H56) has no award, and says so.
- WAIVER KING: the most PAR from all of his pickups that season, each stint
  as Best pickup counts it (modules/awards: this season the move ledger's
  in-season free-agent adds; a past season the daily rosters).
- UNLUCKIEST SEASON (the reviewer's default, Nick to confirm): the most
  losses in weeks where his score beat that week's league median (a tie in
  such a week counts half, the config's tie_win_value), with his points
  against beside it. Ties on losses go to more points against. Scores are
  the official ones (all_matchups) for a past season; this season's are the
  log's started totals (equal to RECORDS), finished weeks only.

Biggest blowout and closest game are NOT here: the record book already has
both (RECORDS biggest_blowout_top10, closest_game_top10; History > Records).
"""
from __future__ import annotations

from statistics import median
from typing import Optional

KEYS = ("lineup", "draft", "waiver", "unlucky")
NAMES = {"lineup": "Lineup manager of the year", "draft": "Draft of the year", "waiver": "Waiver king",
         "unlucky": "Unluckiest season"}
INFO = {
    "lineup": "The best fill rate: the share of all his daily starting slots (10 a day) holding a player "
              "whose NBA team played that day. Every regular-season day with NBA games counts, so empty slots "
              "on light days count against him. Regular season only.",
    "draft": "The most PAR from the players he drafted that season, in his own starts in the regular season. "
             "Keepers are shown apart and not counted; the pick order isn't needed.",
    "waiver": "The most PAR from all of his pickups that season, each counted as Best pickup counts it: "
              "from the add, in his starts, through the regular season.",
    "unlucky": "The most losses in weeks when his score beat that week's league median (a tie counts half), "
               "with his points against beside it. Regular season only.",
}
UNITS = {"lineup": "fill rate", "draft": "PAR", "waiver": "PAR", "unlucky": "losses"}
DOT, MINUS = " \u00b7 ", "\u2212"


class ManagerAwardsError(RuntimeError):
    pass


def _d1(x) -> str:
    v = round(float(x), 1)
    s = f"{abs(v):,.1f}"
    return (MINUS + s) if v < 0 else s


def _pct(x) -> str:
    return f"{100 * float(x):.1f}%"


def _half(x) -> str:
    v = round(float(x) * 2) / 2
    return str(int(v)) if v == int(v) else f"{v:.1f}"


def _positions(r: dict) -> frozenset:
    p = frozenset(x.strip() for x in str(r.get("positions") or "").split(",") if x.strip())
    if not p:
        raise ManagerAwardsError(f"log row {r['player_name']} {r['date']} has no positions")
    return p


def _rows(inp: dict, res: dict) -> list:
    cut, reg = res["cut"], inp["reg"]
    return [r for r in inp["rows"] if r["date"] <= cut and int(r["week"]) <= reg]


SEATS = 10


def fill(inp: dict, res: dict) -> dict:
    """{manager: {"filled", "slots", "days"}} over the regular season through
    res's cut (the module docstring): slots = 10 x his logged days with an NBA
    game. RAISES on a day whose starts exceed the ten seats."""
    from .data_loader import IL_SLOTS
    rows = _rows(inp, res)
    nba_days = {r["date"] for r in rows if r.get("had_game")}
    by: dict = {}
    for r in rows:
        by.setdefault((r["manager"], r["date"]), []).append(r)
    out: dict = {}
    for (m, d), rs in sorted(by.items()):
        st = [r for r in rs if r["started"] and r.get("slot") not in IL_SLOTS]
        if len(st) > SEATS:
            raise ManagerAwardsError(f"{inp['season']} {m} {d}: {len(st)} starts but the seats hold {SEATS}")
        if d not in nba_days:
            continue
        x = out.setdefault(m, {"filled": 0, "slots": 0, "days": 0})
        x["filled"] += sum(1 for r in st if r.get("had_game"))
        x["slots"] += SEATS
        x["days"] += 1
    return out


def _par_rows(inp: dict, res: dict) -> dict:
    """{(player, manager): [(date, PAR)]} for every started game he played."""
    from . import keeper_history as kh
    R = res["R"]
    out: dict = {}
    for r in _rows(inp, res):
        if r["started"] and kh.appeared(r):
            out.setdefault((r["player_name"], r["manager"]), []).append(
                (r["date"], float(r["fantasy_points"]) - R[int(r["week"])]["R"]))
    return out


def draft_class(inp: dict, res: dict) -> Optional[dict]:
    """{manager: {"par", "picks": [(name, PAR)], "keepers_par", "keepers": n}}
    or None when the season has no draft list."""
    from . import keeper_history as kh
    picks = inp["inputs"].picks.get(inp["season"])
    if not picks:
        return None
    names = kh.Names(inp["rows"])
    par = _par_rows(inp, res)
    out: dict = {}
    for p in picks:
        n = names.canon(p["player_name"], p.get("player_key")) or p["player_name"]
        v = sum(x for _d, x in par.get((n, p["manager"]), []))
        x = out.setdefault(p["manager"], {"par": 0.0, "picks": [], "keepers_par": 0.0, "keepers": 0})
        if p.get("is_keeper"):
            x["keepers_par"] += v
            x["keepers"] += 1
        else:
            x["par"] += v
            x["picks"].append((n, v))
    return out


def waiver(res: dict) -> dict:
    """{manager: {"par", "n", "best": (name, PAR)}} from Best pickup's stints."""
    out: dict = {}
    for s in res["awards"]["pickup"].get("stints") or []:
        x = out.setdefault(s["m"], {"par": 0.0, "n": 0, "best": None})
        x["par"] += float(s["value"])
        x["n"] += 1
        if x["best"] is None or s["value"] > x["best"][1]:
            x["best"] = (s["player"], float(s["value"]))
    return out


def unlucky(inp: dict, res: dict) -> dict:
    """{manager: {"losses" (a tie half), "weeks_above", "pa"}} over the
    finished regular-season weeks."""
    from . import awards as A
    tie = A._tie_value(inp)
    totals = res["totals"]
    out: dict = {}
    for w in res["finished"]:
        sc = totals.get(w) or {}
        wk = A._week(inp, w)
        pairs = [(mu["manager_a"], mu["manager_b"]) for mu in wk.get("matchups") or []]
        if not pairs:
            continue
        ms = [m for p in pairs for m in p]
        miss = [m for m in ms if m not in sc]
        if miss:
            raise ManagerAwardsError(f"{inp['season']} week {w}: no score for {miss}")
        med = median(sc[m] for m in ms)
        for a, b in pairs:
            for m, o in ((a, b), (b, a)):
                x = out.setdefault(m, {"losses": 0.0, "weeks_above": 0, "pa": 0.0, "weeks": 0})
                x["pa"] += sc[o]
                x["weeks"] += 1
                if round(sc[m], 2) > round(med, 2):
                    x["weeks_above"] += 1
                    if round(sc[m], 2) < round(sc[o], 2):
                        x["losses"] += 1.0
                    elif round(sc[m], 2) == round(sc[o], 2):
                        x["losses"] += 1.0 - tie
    return out


def _award(key: str) -> dict:
    return {"key": key, "name": NAMES[key], "info": INFO[key], "unit": UNITS[key], "rows": [], "none": "",
            "winners": []}


def _finish(a: dict, tiebreak) -> dict:
    a["rows"].sort(key=lambda r: (-round(r["value"], 6), tiebreak(r), r["m"]))
    for i, r in enumerate(a["rows"], 1):
        r["rank"] = i
    if a["rows"]:
        top = round(a["rows"][0]["value"], 6)
        a["winners"] = [r["m"] for r in a["rows"] if round(r["value"], 6) == top
                        and tiebreak(r) == tiebreak(a["rows"][0])]
    return a


def compute(inp: dict, res: dict, managers: Optional[list] = None) -> dict:
    """The four awards as of res's cut: {"season", "through", "week", "final",
    "awards": {key: {"rows": [{"m", "value", "shown", "sub", "rank"}],
    "winners", "none", ...}}}. res: awards.compute on this inp with "pickup"
    computed (Waiver king reads its stints)."""
    out = {"season": inp["season"], "through": res["cut"], "week": res["week"], "final": res["final"],
           "reg": inp["reg"], "finished": list(res["finished"]), "awards": {k: _award(k) for k in KEYS}}
    if not res["week"] or not res["R"]:
        for a in out["awards"].values():
            a["none"] = "no week played yet"
        return out
    ms = sorted(managers or {r["manager"] for r in inp["rows"]})

    a = out["awards"]["lineup"]
    f = fill(inp, res)
    for m in ms:
        x = f.get(m)
        if not x or not x["slots"]:
            continue
        a["rows"].append({"m": m, "value": x["filled"] / x["slots"], "shown": _pct(x["filled"] / x["slots"]),
                          "sub": f"{x['filled']:,} of {x['slots']:,} slots filled" + DOT
                                 + f"{x['slots'] - x['filled']:,} empty over {x['days']} days with NBA games",
                          "filled": x["filled"], "slots": x["slots"], "days": x["days"]})
    _finish(a, lambda r: -r["filled"])

    a = out["awards"]["draft"]
    dc = draft_class(inp, res)
    if dc is None:
        a["none"] = f"{inp['season']} has no draft list (H56: it didn't match the opening rosters)"
    else:
        for m in ms:
            x = dc.get(m) or {"par": 0.0, "picks": [], "keepers_par": 0.0, "keepers": 0}
            best = max(x["picks"], key=lambda t: t[1], default=None)
            a["rows"].append({"m": m, "value": x["par"], "shown": f"{len(x['picks'])} picks"
                              + (f"{DOT}best: {best[0]} {_d1(best[1])}" if best else ""),
                              "sub": (f"keepers apart: {x['keepers']} kept, {_d1(x['keepers_par'])} PAR"
                                      if x["keepers"] else "no keepers that season"),
                              "picks": len(x["picks"]), "keepers_par": x["keepers_par"],
                              "best": best[0] if best else None})
        _finish(a, lambda r: 0)

    a = out["awards"]["waiver"]
    wv = waiver(res)
    for m in ms:
        x = wv.get(m) or {"par": 0.0, "n": 0, "best": None}
        a["rows"].append({"m": m, "value": x["par"], "shown": f"{x['n']} pickup{'s' if x['n'] != 1 else ''}"
                          + (f"{DOT}best: {x['best'][0]} {_d1(x['best'][1])}" if x["best"] else ""),
                          "sub": "", "n": x["n"], "best": x["best"][0] if x["best"] else None})
    _finish(a, lambda r: 0)

    a = out["awards"]["unlucky"]
    if not res["finished"]:
        a["none"] = "no finished week yet"
    else:
        u = unlucky(inp, res)
        for m in ms:
            x = u.get(m) or {"losses": 0.0, "weeks_above": 0, "pa": 0.0, "weeks": 0}
            a["rows"].append({"m": m, "value": x["losses"],
                              "shown": f"lost {_half(x['losses'])} of {x['weeks_above']} week"
                                       f"{'' if x['weeks_above'] == 1 else 's'} above the median",
                              "sub": f"{_d1(x['pa'])} points against in {x['weeks']} weeks",
                              "weeks_above": x["weeks_above"], "pa": round(x["pa"], 2)})
        _finish(a, lambda r: -r["pa"])
    for k in KEYS:
        b = out["awards"][k]
        if not b["rows"] and not b["none"]:
            b["none"] = "no manager qualifies"
    return out


def value_text(key: str, v: float) -> str:
    return _pct(v) if key == "lineup" else _half(v) if key == "unlucky" else _d1(v)


def view(rec: dict) -> list:
    """The display model (engine strings only): per award its name, InfoTip,
    unit, status, and its rows {"rank", "m", "value", "shown", "sub"}."""
    st = "Final" if rec["final"] else ("Live" if rec["week"] else "Not started")
    meta = (f"weeks 1\u2013{rec['reg']}" if rec["final"] else
            f"through week {rec['week']}" + ("" if rec["week"] in rec.get("finished", ()) else " (in progress)")
            if rec["week"] else "")
    out = []
    for k in KEYS:
        a = rec["awards"][k]
        out.append({"key": k, "name": a["name"], "info": a["info"], "unit": a["unit"], "status": st,
                    "none": a["none"], "meta": meta,
                    "rows": [{"rank": str(r["rank"]), "m": r["m"], "value": value_text(k, r["value"]),
                              "shown": r["shown"], "sub": r["sub"]} for r in a["rows"]]})
    return out
