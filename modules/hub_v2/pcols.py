"""
hub_v2/pcols.py -- ENGINE SIDE of the Players tab's Detailed groups (5d2 s.3; Nick's
notes item 13, the whole brainstorm kept). Every cell is a string made here;
every sort is an integer order (row indices of v2.players.rows, best first,
"d" and its reverse "a", a missing value last both ways). The page prints and
reorders; it computes nothing.

    v2.players["groups"] = {
      "groups": [{"key", "label", "cols": [col key...]}]   Value, Season, Form,
                 Box score, Schedule, Health, Market, Career, All
      "cols":   {col key: {"label", "num"}}
      "cells":  {col key: [str per row]}
      "tot":    {box key: [str per row]}     the Box score's season totals
      "orders": {col key: {"d": [i...], "a": [i...]}}
      "trend":  [{"values", "aria"} or None per row], "trend_max": float
      "why":    {col key: why a cell is a dash}
      "hidden": [{"what", "why"}]            columns left out, and why
    }

ONE SOURCE (the notes' rule): a column Team > Roster also shows is that
table's string for a rostered player (Start %, vs Proj, Floor, Ceil, Boom %,
Bust %, B2B, Missed, Back, Acquired, Best), and a free agent's is made by the
same function (roster.form_spread, roster.best_game, roster.back_to_backs). A
range column (Next 3 weeks, Semifinals, Finals, Cup) is hub_v2.ranges'
number, the same as Market's and Team > Schedule's.

FREE AGENTS: the daily lines cache (player_actuals) holds every player the
hub names, so the season, form, box score and schedule columns fill for them.
A column that can't (Keep %, Start %, PAR so far for a player never started
on a league roster, Acquired) shows a dash, and its "why" says so. Never a 0
standing in for a missing value.

THE VIEWER (5e): the hub has one shared passphrase, so it cannot know who
is viewing; the "I'm..." picker (remembered in the browser, cosmetic) says
who. Value to you and its Title delta carry one string per manager (vu),
and each manager's order (orders "vtv@<manager>"); the page shows the
viewer's, and the columns only once a team is picked.

CAREER (career_cells): from the player cards (hub_cards' career, ownership
and draft history), which are built with the page; NBA seasons and the NBA
draft slot from data/historical/NBA_SEASONS.json and NBA_DRAFTS.json (4a4).
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

DASH = "\u2014"
MINUS = "\u2212"
DOT = "\u00b7"

GROUPS = (
    ("value", "Value", ("ovr", "pot", "dur", "rank", "posrank", "keep", "vtv", "vtd")),
    ("season", "Season", ("gp", "total", "fppg", "proj", "vsproj", "par", "started", "startpct", "potw", "best")),
    ("form", "Form", ("l7", "l14", "l30", "trend", "floor", "ceil", "boom", "bust", "min", "mind", "streak")),
    ("box", "Box score", ("b_min", "b_pts", "b_reb", "b_ast", "b_stl", "b_blk", "b_to", "b_3pm", "b_fg", "b_fgp",
                          "b_ft", "b_ftp", "sh_pts", "sh_3", "sh_reb", "sh_ast", "sh_stl", "sh_blk", "sh_eff")),
    ("schedule", "Schedule", ("gl", "next", "nx3", "b2b", "semis", "finals", "cup")),
    ("health", "Health", ("status", "back", "avail", "missed", "ilslot")),
    ("market", "Market", ("owner", "acq", "free", "adds", "drops", "owners")),
    ("career", "Career", ("seasons", "cfppg", "bestsea", "kept", "drafted", "arch", "nbasea", "nbadraft")),
)
# 5e: "Value to you", one string per manager (the "I'm..." picker shows the viewer's)
VU_COLS = ("vtv", "vtd")
LABEL = {
    "vtv": "Value to you", "vtd": "Title \u0394 to you",
    "ovr": "OVR", "pot": "POT", "dur": "DUR", "rank": "Rank", "posrank": "Pos rank", "keep": "Keep %",
    "gp": "GP", "total": "Total FP", "fppg": "FPPG", "proj": "Proj", "vsproj": "vs Proj", "par": "PAR so far",
    "started": "Started", "startpct": "Start %", "potw": "POTW", "best": "Best",
    "l7": "L7", "l14": "L14", "l30": "L30", "trend": "Trend", "floor": "Floor", "ceil": "Ceil", "boom": "Boom %",
    "bust": "Bust %", "min": "MIN", "mind": "MIN \u0394", "streak": "Streak",
    "b_min": "MIN", "b_pts": "PTS", "b_reb": "REB", "b_ast": "AST", "b_stl": "STL", "b_blk": "BLK", "b_to": "TO",
    "b_3pm": "3PM", "b_fg": "FGM-A", "b_fgp": "FG%", "b_ft": "FTM-A", "b_ftp": "FT%",
    "sh_pts": "From PTS", "sh_3": "From 3PM", "sh_reb": "From REB", "sh_ast": "From AST", "sh_stl": "From STL",
    "sh_blk": "From BLK", "sh_eff": "From eff.",
    "gl": "GL", "next": "Next", "nx3": "Next 3 wks", "b2b": "B2B", "semis": "Semis", "finals": "Finals", "cup": "Cup",
    "status": "Status", "back": "Back", "avail": "Avail %", "missed": "Missed", "ilslot": "IL slot",
    "owner": "Owner", "acq": "Acquired", "free": "Free since", "adds": "Added", "drops": "Dropped",
    "owners": "Managers",
    "seasons": "Seasons", "cfppg": "Career FPPG", "bestsea": "Best season", "kept": "Kept", "drafted": "Drafted",
    "arch": "Archetype", "nbasea": "NBA seasons", "nbadraft": "NBA draft",
}
TEXT_COLS = {"trend", "status", "owner", "acq", "free", "ilslot", "drafted", "arch", "best", "bestsea", "streak",
             "b_fg", "b_ft", "nbadraft", "back"}
LOW_FIRST = {"rank", "posrank", "bust", "missed", "b_to", "back", "free"}
HOT_COLD = 0.15                 # the newsletter's hot/cold line: +-15% vs projection (projections.py)
STREAK_DAYS = 28                # ... over 4 weeks
STREAK_MIN_GAMES = 4
BOX = (("b_pts", "PTS"), ("b_reb", "REB"), ("b_ast", "AST"), ("b_stl", "ST"), ("b_blk", "BLK"), ("b_to", "TO"),
       ("b_3pm", "3PTM"))
SHARES = (("sh_pts", ("PTS",)), ("sh_3", ("3PTM",)), ("sh_reb", ("REB",)), ("sh_ast", ("AST",)),
          ("sh_stl", ("ST",)), ("sh_blk", ("BLK",)), ("sh_eff", ("FGM", "FGA", "FTM", "FTA", "TO")))
NBA_FILES_FIRST = "2014-15"


class PcolsError(RuntimeError):
    """A Players-column input is missing or inconsistent; named."""


def _f1(x: float) -> str:
    return f"{x:.1f}"


def _signed1(x: float) -> str:
    v = round(float(x), 1)
    return f"+{v:.1f}" if v > 0 else (f"{MINUS}{abs(v):.1f}" if v < 0 else "0.0")


def _md(d: date) -> str:
    return f"{d.month:02d}-{d.day:02d}"


def _pct(x: float) -> str:
    v = round(100.0 * x)
    return f"{MINUS}{abs(v):.0f}%" if v < 0 else f"{v:.0f}%"


def _num(text: str) -> Optional[float]:
    """The order key of a display number ("41.2", "+3.0", "75%", "#3", "C4")."""
    t = str(text).replace(MINUS, "-").replace(",", "").replace("%", "").lstrip("#").strip()
    if t and t[0].isalpha():
        t = t.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    try:
        return float(t)
    except ValueError:
        return None


def _orders(keys: List[Optional[float]], names: List[str], low: bool) -> dict:
    have = [i for i, k in enumerate(keys) if k is not None]
    miss = [i for i, k in enumerate(keys) if k is None]
    asc = sorted(have, key=lambda i: (keys[i], names[i].lower()))
    desc = sorted(have, key=lambda i: (-keys[i], names[i].lower()))
    best = asc if low else desc
    rev = desc if low else asc
    return {"d": best + miss, "a": rev + miss}


def transactions(base) -> List[dict]:
    p = Path(base) / "data" / "transaction_log.jsonl"
    if not p.is_file():
        raise PcolsError("data/transaction_log.jsonl is missing: the Market columns need it")
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("row") == "transaction" and r.get("status") == "successful":
                out.append(r)
    return out


def moves_of(trs: List[dict], first: date) -> dict:
    """{name (as logged): {"adds", "drops", "last_drop": (date, manager) or None}}
    of this season's moves (rule 14: a pre-season move is no move)."""
    out: Dict[str, dict] = {}
    for r in trs:
        day = date.fromisoformat(str(r["league_day"])[:10])
        for x in r.get("players") or []:
            d = out.setdefault(x["name"], {"adds": 0, "drops": 0, "last_drop": None})
            if x.get("action") == "drop":
                who = (x.get("from") or {}).get("manager")
                if d["last_drop"] is None or day >= d["last_drop"][0]:
                    d["last_drop"] = (day, who)
            if day < first:
                continue
            if x.get("action") == "add":
                d["adds"] += 1
            elif x.get("action") == "drop":
                d["drops"] += 1
    return out


# =============================================================================
# the build (in hub_state, after the roster's Detailed columns)
# =============================================================================

def build(base, payload: dict, ctx: dict) -> dict:
    from .. import player_actuals as pa
    from ..data_loader import PlayerIndex
    from . import roster as R
    v2 = payload["v2"]
    block = v2["players"]
    rows = block["rows"]
    names = [z["name"] for z in rows]
    actuals, yesterday = ctx["actuals"], ctx["yesterday"]
    first = date.fromisoformat(actuals["first_day"])
    proj = ctx["proj"]
    src = ctx["ranges"]
    av = src.av
    fa_av = ctx.get("fa_av")
    fa_ok = set(ctx.get("fa_ok") or [])
    rl = {r.key: r for r in ctx["range_list"]}
    sched_days = [d for ds in ctx["sched_days"] for d in ds]
    this_days = list(ctx["sched_days"][0]) if ctx["sched_days"] else []
    opp = R.opponents(ctx["data"].nba_schedule)
    header = actuals.get("cats") or {}
    cat_vals = dict(zip(header.get("order") or [], header.get("values") or []))
    # the roster's strings (one source) by player
    rc = v2.get("roster_cols") or {}
    rdet = {}
    for m, t in v2["teams"].items():
        det = t["roster"].get("detail")
        if det is None:
            raise PcolsError(f"{m}'s roster Detailed columns are missing: build them first (roster.build)")
        for p, vals in zip(payload["rosters"][m]["players"], det["rows"]):
            rdet[p["name"]] = dict(zip(rc["keys"], vals))
    rblock = {p["name"]: (m, p) for m, rb in payload["rosters"].items() for p in rb["players"]}
    par = PlayerIndex(dict(ctx.get("par") or {}))
    potw = PlayerIndex(dict(ctx.get("potw_wins") or {}))
    potw_ok = ctx.get("potw_wins") is not None
    lu = ctx["data"].lineups
    lu = lu[lu["date"].astype(str) <= yesterday.isoformat()]
    st_rows = lu[~lu["slot"].astype(str).isin(("BN", "IL", "IL+"))]
    started_days = {}
    for n, dd in zip(st_rows["player_name"], st_rows["date"]):
        started_days.setdefault(n, set()).add(str(dd)[:10])
    started_idx = PlayerIndex({k: v for k, v in started_days.items()})
    mv = moves_of(transactions(base), first)
    mv_idx = PlayerIndex(mv)

    cells = {k: [] for _g, _l, cols in GROUPS for k in cols if _g != "career"}
    keys = {k: [] for k in cells}
    tot = {k: [] for k, _c in BOX}
    tot.update({"b_min": [], "b_fg": [], "b_fgp": [], "b_ft": [], "b_ftp": []})
    trend, tmax = [], 1.0
    fppgs = {}

    def put(k, text, key=None):
        cells[k].append(text)
        keys[k].append(key)

    for z in rows:
        n = z["name"]
        rostered = z["kind"] == "rostered"
        rd = rdet.get(n) if rostered else None
        if rostered and rd is None:
            raise PcolsError(f"{n} is rostered but not in any roster's Detailed columns")
        days = pa.find_days(actuals, n)
        games = []
        if days is not None:
            d = first
            while d <= yesterday:
                v = days.get(d.isoformat())
                if v is not None and int(v[1]) == 1:
                    games.append((d, float(v[0])))
                d += timedelta(days=1)
        pts = [g[1] for g in games]
        gp = len(games)
        covered = z["total"] != DASH
        fppg = (sum(pts) / gp) if gp else None
        fppgs[n] = fppg if covered else None
        team = str(z["nba"]).upper() if z["nba"] != DASH else ""

        # ------------------------------------------------ Value
        put("ovr", z["ovr"] + (" Prov." if z.get("prov") else ""), z.get("ovr_k"))
        put("pot", z["pot"], z.get("pot_k"))
        put("dur", z["dur"], z.get("dur_k"))
        put("rank", "", None)                                 # filled after the loop
        put("posrank", "", None)
        put("keep", z["keep"], _num(z["keep"]) if rostered else None)

        # ------------------------------------------------ Season
        put("gp", z["gp"] if covered else DASH, gp if covered else None)
        put("total", z["total"], _num(z["total"]))
        put("fppg", z["fppg"], _num(z["fppg"]))
        pj = proj.get(n)
        pjv = None if pj is None else pj.get("projectedFPPG")
        pjv = None if pjv is None or (isinstance(pjv, float) and math.isnan(pjv)) else float(pjv)
        put("proj", DASH if pjv is None else _f1(pjv), pjv)
        if rostered:
            put("vsproj", rd["vsproj"], _num(rd["vsproj"]))
        elif fppg is None or pjv is None or not covered:
            put("vsproj", DASH)
        else:
            dv = round(fppg, 1) - round(pjv, 1)
            put("vsproj", _signed1(dv), dv)
        pv = par.get(n)
        put("par", DASH if pv is None else _signed1(pv), pv)
        sd = started_idx.get(n) or set()
        played = {g[0].isoformat() for g in games}
        ns = len(sd & played)
        put("started", str(ns) if (sd or rostered) else DASH, ns if (sd or rostered) else None)
        if rostered:
            put("startpct", rd["start"], _num(rd["start"]))
        else:
            put("startpct", DASH)
        if potw_ok:
            w = potw.get(n) or 0
            put("potw", str(w), w)
        else:
            put("potw", DASH)
        if rostered:
            put("best", rd["best"], max(pts) if pts else None)
        else:
            b = R.best_game(games, team, opp)
            put("best", b[0] if b else DASH, b[1] if b else None)

        # ------------------------------------------------ Form
        for k, nd in (("l7", 7), ("l30", 30)):
            a = max(first, yesterday - timedelta(days=nd - 1))
            w = [p for dd, p in games if dd >= a]
            put(k, _f1(sum(w) / len(w)) if w and covered else DASH, (sum(w) / len(w)) if w and covered else None)
        put("l14", z["l14"], _num(z["l14"]))
        last = pts[-R.TREND_GAMES:] if covered else []
        if last:
            trend.append({"values": [round(x, 1) for x in last],
                          "aria": f"His last {len(last)} games: " + ", ".join(f"{x:.1f}" for x in last)})
            tmax = max(tmax, max(last))
            put("trend", "", sum(last) / len(last))
        else:
            trend.append(None)
            put("trend", DASH)
        if rostered:
            for k in ("floor", "ceil", "boom", "bust"):
                put(k, rd[k], _num(rd[k]))
        else:
            sp = R.form_spread(pts, fppg) if covered else None
            for k in ("floor", "ceil", "boom", "bust"):
                put(k, sp[0][k] if sp else DASH, sp[1][k] if sp else None)
        put("min", z["min"], z.get("min_k"))
        put("mind", z["mind"], z.get("mind_k"))
        a = max(first, yesterday - timedelta(days=STREAK_DAYS - 1))
        w = [p for dd, p in games if dd >= a]
        if not covered or pjv is None or pjv <= 0 or len(w) < STREAK_MIN_GAMES:
            put("streak", DASH)
        else:
            r = (sum(w) / len(w)) / pjv - 1.0
            put("streak", "Hot" if r > HOT_COLD else "Cold" if r < -HOT_COLD else "", r)

        # ------------------------------------------------ Box score
        cs = pa.category_season(actuals, n, first, yesterday) if covered else {"status": "not_cached"}
        mg = pa.minutes_games(actuals, n, first, yesterday) if covered else {"status": "not_cached"}
        if cs["status"] == "ok" and cs["games"]:
            g0, t0 = cs["games"], cs["totals"]
            for k, c in BOX:
                put(k, _f1(t0[c] / g0), t0[c] / g0)
                tot[k].append(f"{int(t0[c]):,}")
            fg = (f"{t0['FGM'] / g0:.1f}-{t0['FGA'] / g0:.1f}", f"{int(t0['FGM'])}-{int(t0['FGA'])}")
            ft = (f"{t0['FTM'] / g0:.1f}-{t0['FTA'] / g0:.1f}", f"{int(t0['FTM'])}-{int(t0['FTA'])}")
            put("b_fg", fg[0], t0["FGM"] / g0)
            tot["b_fg"].append(fg[1])
            put("b_ft", ft[0], t0["FTM"] / g0)
            tot["b_ft"].append(ft[1])
            for k, m_, a_ in (("b_fgp", "FGM", "FGA"), ("b_ftp", "FTM", "FTA")):
                if t0[a_]:
                    v = t0[m_] / t0[a_]
                    put(k, f"{100.0 * v:.1f}%", v)
                    tot[k].append(f"{100.0 * v:.1f}%")
                else:
                    put(k, DASH)
                    tot[k].append(DASH)
            fp = sum(t0[c] * float(cat_vals[c]) for c in t0 if c in cat_vals)
            for k, cats in SHARES:
                if fp > 0:
                    s = sum(t0[c] * float(cat_vals[c]) for c in cats) / fp
                    put(k, _pct(s), s)
                else:
                    put(k, DASH)
        else:
            for k, _c in BOX:
                put(k, "loading" if cs["status"] == "loading" else DASH)
                tot[k].append("loading" if cs["status"] == "loading" else DASH)
            for k in ("b_fg", "b_ft", "b_fgp", "b_ftp"):
                put(k, "loading" if cs["status"] == "loading" else DASH)
                tot[k].append("loading" if cs["status"] == "loading" else DASH)
            for k, _c in SHARES:
                put(k, "loading" if cs["status"] == "loading" else DASH)
        if mg["status"] == "ok" and mg["games"]:
            tm = sum(m for _i, m in mg["games"])
            put("b_min", _f1(tm / len(mg["games"])), tm / len(mg["games"]))
            tot["b_min"].append(f"{int(tm):,}")
        else:
            put("b_min", "loading" if mg["status"] == "loading" else DASH)
            tot["b_min"].append("loading" if mg["status"] == "loading" else DASH)

        # ------------------------------------------------ Schedule
        fa_here = (not rostered) and fa_av is not None and n in fa_ok
        if rostered:
            p = rblock[n][1]
            put("gl", p["gl"], _num(p["gl"]))
            put("next", z["next"], _num(z["next"]))
            put("b2b", rd["b2b"], _num(rd["b2b"]))
        elif fa_here:
            g = src.player_games(n, this_days, fa_av)
            put("gl", str(g), g)
            put("next", z["next"], _num(z["next"]))
            tds = fa_av.team_dates.get(team, ())
            b2 = len(R.back_to_backs([d for d in tds if d in set(sched_days)]))
            put("b2b", str(b2), b2)
        else:
            for k in ("gl", "next", "b2b"):
                put(k, DASH)
        for k, rk in (("nx3", "next3"), ("semis", "semis"), ("finals", "finals"), ("cup", "cup")):
            r_ = rl.get(rk)
            if r_ is None or not (rostered or fa_here):
                put(k, DASH)
            else:
                g = src.player_games(n, r_.days) if rostered else src.player_games(n, r_.days, fa_av)
                put(k, str(g), g)

        # ------------------------------------------------ Health
        st = " \u00b7 ".join(c["text"] for c in z["chips"]) or ("Healthy" if z["healthy"] else DASH)
        put("status", st, None)
        if rostered:
            put("back", rd["back"], None)
        else:
            bk = next((c["text"] for c in z["chips"] if "back " in str(c["text"])), None)
            put("back", bk.split("back ")[-1] if bk else DASH, None)
        put("avail", z["avail"], _num(z["avail"]))
        if rostered:
            put("missed", rd["missed"], _num(rd["missed"]))
        elif covered and team and team in av.team_dates:
            tds = [d for d in av.team_dates[team] if first <= d <= yesterday]
            mi = sum(1 for d in tds if d.isoformat() not in played)
            put("missed", str(mi), mi)
        else:
            put("missed", DASH)
        put("ilslot", "IL slot" if (rostered and rblock[n][1]["in_il"]) else DASH, None)

        # ------------------------------------------------ Market
        put("owner", z["chip"]["team"] if rostered else "Free agent", None)
        put("acq", rd["acq"] if rostered else DASH, None)
        x = mv_idx.get(n) or {"adds": 0, "drops": 0, "last_drop": None}
        if rostered:
            put("free", DASH)
        elif x["last_drop"] is not None:
            dday, who = x["last_drop"]
            put("free", f"Dropped by {who} {_md(dday)}" if who else f"Dropped {_md(dday)}", dday.toordinal())
        else:
            put("free", "Not rostered this season", None)
        put("adds", str(x["adds"]), x["adds"])
        put("drops", str(x["drops"]), x["drops"])
        put("owners", "", None)                                # career_cells (the cards)

    # ranks: FPPG among every player in the table, and by his first position
    have = sorted([n for n in names if fppgs.get(n) is not None], key=lambda n: -fppgs[n])
    rank_of = {n: i + 1 for i, n in enumerate(have)}
    pos_rank = {}
    for posn in ("PG", "SG", "SF", "PF", "C"):
        ps = [n for n in have if (rows[names.index(n)]["pos"].split(",") or [""])[0] == posn]
        for i, n in enumerate(ps):
            pos_rank[n] = (posn, i + 1)
    for i, n in enumerate(names):
        if n in rank_of:
            cells["rank"][i], keys["rank"][i] = f"#{rank_of[n]}", rank_of[n]
        else:
            cells["rank"][i] = DASH
        if n in pos_rank:
            pp, k = pos_rank[n]
            cells["posrank"][i], keys["posrank"][i] = f"{pp}{k}", k
        else:
            cells["posrank"][i] = DASH
    vu = value_to_you(v2.get("fa_value"), rows)
    for k in VU_COLS:
        cells[k] = [DASH if x is None else "" for x in vu[k]]
        keys[k] = [None] * len(rows)
    orders = {k: _orders(keys[k], names, k in LOW_FIRST) for k in cells}
    for k in VU_COLS:                            # each manager's own order of his values
        for m in vu["managers"]:
            orders[f"{k}@{m}"] = _orders([None if x is None else x[m][1] for x in vu[k]], names, False)
    return {"cells": cells, "tot": tot, "orders": orders, "trend": trend, "trend_max": round(float(tmax), 1),
            "vu": {k: [None if x is None else {m: t for m, (t, _v) in x.items()} for x in vu[k]] for k in VU_COLS},
            "vu_error": vu["error"],
            "ranges": {k: (rl[r].sub if r in rl else None) for k, r in (("nx3", "next3"), ("semis", "semis"),
                                                                         ("finals", "finals"), ("cup", "cup"))}}


def value_to_you(fv: Optional[dict], rows: list) -> dict:
    """5e: per Players row, {manager: (text, key)} for Value to you (vtv) and
    its Title delta (vtd), or None (a rostered player, or a free agent the
    nightly didn't price: only Market's screened free agents are)."""
    fv = fv or {}
    vals = fv.get("values") or {}
    ms = sorted({m for v in vals.values() for m in v})
    out = {"vtv": [], "vtd": [], "managers": ms, "error": fv.get("error")}
    for z in rows:
        v = vals.get(z["name"]) if z["kind"] != "rostered" else None
        if not v or set(v) != set(ms):
            out["vtv"].append(None)
            out["vtd"].append(None)
            continue
        out["vtv"].append({m: (v[m]["tv"], v[m]["tv_k"]) for m in ms})
        out["vtd"].append({m: (v[m]["td"], v[m]["td_k"]) for m in ms})
    return out


WHY = {
    "vtv": "Rostered, or a free agent outside Market's lists (only they are priced each night); pick your team "
           "with \u201cI'm\u2026\u201d to see it",
    "vtd": "As Value to you; a dash too while the stakes file is missing",
    "rank": "No games this season (or his daily lines aren't cached yet)",
    "posrank": "No games this season, or no position on record",
    "keep": "Free agents have no keep chance",
    "gp": "His daily lines aren't cached yet (new to the hub's lists)",
    "vsproj": "No games yet, or no Yahoo projection",
    "proj": "No Yahoo projection for him",
    "par": "Never started on a league roster this season: PAR counts started games only",
    "started": "Never on a league roster this season",
    "startpct": "Free agents start nowhere: Start % is his share of starts on his team",
    "potw": "The Player of the Week list could not be read on this run",
    "best": "No games this season",
    "l7": "No games in the window", "l30": "No games in the window",
    "trend": "No games yet",
    "floor": "Fewer than 10 games", "ceil": "Fewer than 10 games", "boom": "Fewer than 10 games",
    "bust": "Fewer than 10 games",
    "streak": "Fewer than 4 games in the last 4 weeks, or no projection; blank: neither hot nor cold",
    "b_min": "\"loading\" until the nightly has every game's minutes; a dash: no games",
    "gl": "His NBA team isn't on record (or no tag for him)",
    "next": "IL slot, or his NBA team isn't on record",
    "nx3": "The range has passed, or his NBA team isn't on record",
    "semis": "The range has passed, or his NBA team isn't on record",
    "finals": "The range has passed, or his NBA team isn't on record",
    "cup": "The range has passed, or his NBA team isn't on record",
    "b2b": "IL slot, or his NBA team isn't on record",
    "back": "Not out",
    "missed": "No games on record",
    "ilslot": "Not in an IL slot",
    "acq": "A free agent",
    "free": "Rostered",
    "seasons": "No season on a league roster",
    "cfppg": "No season on a league roster",
    "bestsea": "No season on a league roster",
    "drafted": "Never drafted or kept in the league",
    "nbasea": "Not matched in the NBA season file",
    "nbadraft": "Not in the 2014\u20132026 NBA drafts on file (undrafted, earlier, or not matched)",
}
for _k, _c in BOX:
    WHY[_k] = "\"loading\" until the nightly has every game's categories; a dash: no games"
for _k, _c in SHARES:
    WHY[_k] = "\"loading\" until the nightly has every game's categories; a dash: no games"
for _k in ("b_fg", "b_ft", "b_fgp", "b_ftp"):
    WHY[_k] = "\"loading\" until the nightly has every game's categories; a dash: no games (or no attempts)"


# =============================================================================
# Career (with the page: the player cards), and the groups' shared block
# =============================================================================

def career_cells(base, payload: dict, cards_obj: Optional[dict]) -> dict:
    """{"cells", "orders", "owners": [str per row]}: the Career group from the
    player cards (hub_cards.build's career, ownership timeline and draft
    history), NBA seasons and the NBA draft from 4a4's files. Without cards
    every cell is a dash saying why."""
    from ..data_loader import PlayerIndex
    from .. import player_actuals as pa
    block = payload["v2"]["players"]
    rows = block["rows"]
    names = [z["name"] for z in rows]
    cards = {}
    for k, c in ((cards_obj or {}).get("cards") or {}).items():
        cards[c.get("player_name")] = c
    cidx = PlayerIndex(cards)
    cols = ("seasons", "cfppg", "bestsea", "kept", "drafted", "arch", "nbasea", "nbadraft")
    cells = {k: [] for k in cols}
    keys = {k: [] for k in cols}
    owners, okeys = [], []
    def _read(rel):
        if base is None:
            return None
        f = Path(base) / "data" / "historical" / rel
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    seasons_blob, drafts_blob = _read("NBA_SEASONS.json"), _read("NBA_DRAFTS.json")
    actuals = pa.load(base, required=False) if base is not None else None
    ids = {}
    if actuals is not None:
        for nm, pid in list((actuals.get("extra_names") or {}).items()) + list((actuals.get("roster_names") or {}).items()):
            ids[nm] = str(pid)
    id_idx = PlayerIndex(ids)

    def put(k, t, v=None):
        cells[k].append(t)
        keys[k].append(v)
    for z in rows:
        n = z["name"]
        c = cidx.get(n) if cards else None
        car = (c or {}).get("career") or {}
        sb = car.get("season_breakdown") or []
        if sb:
            put("seasons", str(len(sb)), len(sb))
            put("cfppg", f"{float(car['career_fppg']):.1f}", float(car["career_fppg"]))
            b = max(sb, key=lambda s: (float(s["fppg"]), s["season"]))
            put("bestsea", f"{float(b['fppg']):.1f} ({b['season']})", float(b["fppg"]))
        else:
            for k in ("seasons", "cfppg", "bestsea"):
                put(k, DASH)
        dh = (c or {}).get("draft_history") or []
        kept = sum(1 for d in dh if d.get("is_keeper"))
        put("kept", str(kept) if c else DASH, kept if c else None)
        drafted = [d for d in dh if not d.get("is_keeper")]
        if drafted:
            d0 = sorted(drafted, key=lambda d: d["season"])[0]
            yr = "\u2019" + str(d0["season"])[2:4]
            put("drafted", (f"{d0['manager']} {yr} R{d0['round']}" if d0.get("pick_number") is not None
                            and d0.get("round") else f"{d0['manager']} {yr}"), None)
        else:
            put("drafted", DASH)
        a = z.get("arch")
        put("arch", (a or {}).get("label") or DASH)
        tl = (c or {}).get("ownership_timeline") or []
        mgrs = sorted({e["manager"] for t in tl for e in (t.get("events") or []) if e.get("manager")})
        owners.append(str(len(mgrs)) if c else DASH)
        okeys.append(len(mgrs) if c else None)
        pid = id_idx.get(n)
        if seasons_blob is not None and pid is not None and pid in (seasons_blob.get("players") or {}):
            ss = sorted((seasons_blob["players"][pid].get("seasons") or {}).keys())
            plus = "+" if ss and ss[0] == NBA_FILES_FIRST else ""
            put("nbasea", f"{len(ss)}{plus}", len(ss))
        else:
            put("nbasea", DASH)
        if drafts_blob is not None and pid is not None and pid in (drafts_blob.get("players") or {}):
            d = drafts_blob["players"][pid]
            put("nbadraft", f"{d['year']} #{d['pick']}", -int(d["pick"]))
        else:
            put("nbadraft", DASH)
    orders = {k: _orders(keys[k], names, False) for k in cols}
    orders["owners"] = _orders(okeys, names, False)
    return {"cells": cells, "orders": orders, "owners": owners}


HIDDEN: list = []                # 5e: the "I'm..." picker shows Value to you (it was hidden in 5d2)


def shared(arch_on: bool) -> dict:
    """The groups' definition (labels, numbers right-aligned, the dash reasons)."""
    groups = []
    for gk, gl, cols in GROUPS:
        cs = [c for c in cols if c != "arch" or arch_on]
        groups.append({"key": gk, "label": gl, "cols": cs})
    allc = [c for g in groups for c in g["cols"]]
    groups.append({"key": "all", "label": "All", "cols": allc})
    return {"groups": groups, "cols": {k: {"label": LABEL[k], "num": k not in TEXT_COLS} for k in allc},
            "why": {k: WHY[k] for k in allc if k in WHY}, "hidden": HIDDEN}
