"""
hub_v2/manager.py -- ENGINE SIDE of the manager card (MC2; claude/HANDOFF_
MC2_MANAGER_CARD_BUILD_2026-11-25.md, the card MC1 mocked with Nick's answers).

One card per manager, every string made here; chart geometry here too (as
the player card's card.py does: floats only place a mark). The page
(page_manager.py) prints. Each card is a lazy screen (#/manager/<name>,
publish.lazy_routes): only its top bar is in the first load.

    build(inp, results, extra) -> {"order": [managers], "cards": {m: card}}

ONE SOURCE FOR EACH FACT (handoff s.1):
  titles           modules/trophy_case.build() (League > All-time's trophy
                   case and its Titles column read the same)
  record, win %,   hub_v2/league.alltime(): League > All-time's own rows
  all-time rank
  finishes         season_outcomes over all_standings (league_champion,
                   playoff_champion; regular_season_rank, playoff_rank) and
                   league.pre_era_seasons() for 2014-15 and 2016-17
  team names       league._season_team (the Champions page's), the pre-Yahoo
                   seasons' from config, this season's the payload's
  franchise player RECORDS all_time franchise_badges (backfill_player_
                   records.franchise_badges_from: started games, answer 7)
  money            modules/money (config payouts_by_season)

LEAGUE_RULES applies throughout: "champion" / "title" unqualified is the
League Champion; the bracket's winner is always the Playoff Champion; the Cup
is always named; every money line names its pot; 2015-16 is in no list.

RAISE RATHER THAN DEFAULT: a missing input raises ManagerError naming it. The
whole card is soft (hub_v2/data.league_soft): a failure leaves the cards out,
names stay plain, and the run row says why (data.soft_notes).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional

from . import league as L

MINUS = "−"
DASH = "—"
NDASH = "–"
DOT = " · "
STAR, DIAMOND = "★", "◆"
TABS = [("overview", "Overview"), ("career", "Career"), ("rivals", "Rivals"), ("players", "Players"),
        ("trophies", "Trophies")]
PHASES = [("reg", "Regular season"), ("post", "Postseason"), ("cup", "Cup")]
# the record book's lists that are not honours (a #1 there is not "a record he holds"), and the neutral one
NOT_HONOURS = ("lowest_weekly_score", "longest_loss_streak", "worst_manager_season", "lowest_single_game",
               "biggest_draft_bust", "closest_game")
TEAM_GROUPS = ("Team weeks", "Team seasons")
# chart frames (viewBox units, the player card's phone width)
W = 356


class ManagerError(RuntimeError):
    """A manager-card input is missing or contradictory; named."""


def _f(x: float) -> str:
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _signed0(x: float) -> str:
    r = int(round(x))
    return f"+{r:,}" if r > 0 else (f"{MINUS}{-r:,}" if r < 0 else "0")


def _signed1(x: float) -> str:
    return f"+{x:,.1f}" if x > 0 else (f"{MINUS}{-x:,.1f}" if x < 0 else "0.0")


def _short(season: str) -> str:
    return season[2:]                               # 2018-19 -> 18-19


def _span(seasons: List[str], current: str) -> str:
    """A run of seasons: "2014-15", "2017-18 to 2018-19", "2021-22 on"."""
    if seasons[-1] == current:
        return f"{seasons[0]} on" if len(seasons) > 1 else f"{current} on"
    return seasons[0] if len(seasons) == 1 else f"{seasons[0]} to {seasons[-1]}"


def _rec3(w: int, l: int, t: int = 0) -> str:
    return L._rec(w, l, t)


def _pct3(w: int, l: int, t: int = 0) -> str:
    g = w + l + t
    return f"{(w + 0.5 * t) / g:.3f}".lstrip("0") if g else DASH


# =============================================================================
# the season list: every league season, each manager's finish and result
# =============================================================================

def seasons_table(inp: dict, results: dict) -> dict:
    """{"seasons": [chronological], "rows": {season: {m: {...}}}}: each
    finished season's regular-season finish, W-L, points, playoff result and
    team, from all_standings (Yahoo) and the pre-Yahoo config, plus this
    season live. The one place the card reads finishes."""
    from ..season_outcomes import league_champion, playoff_champion
    ms = inp["managers"]
    out: Dict[str, dict] = {}
    pre = L.pre_era_seasons(inp["pre_data_era"] or {})
    for s, v in pre.items():
        br = v["bracket"]
        semi_l = [x["loser"] for x in br["semifinals"]]
        out[s] = {}
        for r in v["standings"]:
            m = r["manager"]
            po = ("won" if m == v["playoff_champion"] else "final" if m == v["playoff_runner_up"]
                  else "semi" if m in semi_l else "none")
            out[s][m] = {"kind": "pre", "finish": r["finish"], "w": r["w"], "l": r["l"], "t": 0,
                         "team": v["teams"][m], "po": po, "ppw": None, "lg_ppw": None,
                         "lc": m == v["league_champion"], "pc": m == v["playoff_champion"],
                         "bracket": True}
    by: Dict[str, list] = {}
    for r in inp["all_standings"]:
        by.setdefault(r["season"], []).append(r)
    ss = inp["season_structure"]
    reg_pts: Dict[str, Dict[str, list]] = {}
    for g in inp["all_matchups"]:
        s, w = g["season"], int(g["week"])
        if g["score_a"] == 0 and g["score_b"] == 0:
            continue
        if w <= L._reg_through(inp, s):
            d = reg_pts.setdefault(s, {})
            d.setdefault(g["manager_a"], []).append(float(g["score_a"]))
            d.setdefault(g["manager_b"], []).append(float(g["score_b"]))
    for s in sorted(by):
        rs = by[s]
        lc, pc = league_champion(rs), playoff_champion(rs)
        bracket = (ss.get(s) or {}).get("bracket") is not False
        pts = reg_pts.get(s) or {}
        allp = [x for v in pts.values() for x in v]
        lg = sum(allp) / len(allp) if allp else None
        out[s] = {}
        for r in rs:
            m = r["manager"]
            pr = r.get("playoff_rank")
            po = ("none_held" if not bracket else "won" if pr == 1 else "final" if pr == 2
                  else "semi" if pr in (3, 4) else None)
            if po is None:
                raise ManagerError(f"all_standings {s} {m}: playoff_rank {pr!r} in a season with a bracket")
            mine = pts.get(m) or []
            out[s][m] = {"kind": "yahoo", "finish": int(r["regular_season_rank"]), "w": int(r["reg_wins"]),
                         "l": int(r["reg_losses"]), "t": int(r.get("reg_ties") or 0),
                         "team": L._season_team(inp, s, m), "po": po,
                         "ppw": (sum(mine) / len(mine)) if mine else None, "lg_ppw": lg,
                         "lc": m == lc, "pc": m == pc, "bracket": bracket}
    # this season, live: the regular season so far (the Standings' order and records)
    cur = inp["season"]
    st = L.standings(inp, results)
    reg = inp["reg_weeks"]
    mine: Dict[str, list] = {m: [] for m in ms}
    for w, rows in results.items():
        if w > reg:
            continue
        for a, b, sa, sb, _o in rows:
            mine[a].append(sa)
            mine[b].append(sb)
    allp = [x for v in mine.values() for x in v]
    lg = sum(allp) / len(allp) if allp else None
    out[cur] = {}
    for r in st["rows"]:
        m = r["m"]
        w, l, t = L._wl(r["record"])
        out[cur][m] = {"kind": "live", "finish": int(r["rank"]), "w": w, "l": l, "t": t,
                       "team": inp["teams"][m]["team"], "po": "live",
                       "ppw": (sum(mine[m]) / len(mine[m])) if mine[m] else None, "lg_ppw": lg,
                       "lc": False, "pc": False, "bracket": True}
    seasons = sorted(out)
    for s in seasons:
        if sorted(out[s]) != sorted(ms):
            raise ManagerError(f"{s}: the season's managers {sorted(out[s])} are not {sorted(ms)}")
    return {"seasons": seasons, "rows": out, "through": max([w for w in results if w <= reg], default=0)}


# =============================================================================
# every meeting between two managers (rivalries, runs)
# =============================================================================

def meetings(inp: dict, results: dict) -> List[dict]:
    """Every game in order: the pre-Yahoo brackets (2014-15, 2016-17: semis,
    final, 3rd place), all_matchups (2017-18 on) and this season.
    {"season", "week", "a", "b", "sa", "sb", "phase": reg|post|cup, "pre"}."""
    out = []
    for s, v in L.pre_era_seasons(inp["pre_data_era"] or {}).items():
        br = v["bracket"]
        for i, g in enumerate(br["semifinals"]):
            out.append({"season": s, "week": 101, "a": g["a"], "b": g["b"], "sa": g["a_pts"], "sb": g["b_pts"],
                        "phase": "post", "pre": True, "label": "semifinal", "k": i})
        for k, lab in (("final", "final"), ("third_place", "3rd-place game")):
            g = br[k]
            out.append({"season": s, "week": 102, "a": g["a"], "b": g["b"], "sa": g["a_pts"], "sb": g["b_pts"],
                        "phase": "post", "pre": True, "label": lab, "k": 0})
    cups = inp.get("cup_weeks") or {}
    for g in inp["all_matchups"]:
        if g["score_a"] == 0 and g["score_b"] == 0:
            continue
        s, w = g["season"], int(g["week"])
        ph = "cup" if w in (cups.get(s) or []) else "post" if w > L._reg_through(inp, s) else "reg"
        out.append({"season": s, "week": w, "a": g["manager_a"], "b": g["manager_b"], "sa": float(g["score_a"]),
                    "sb": float(g["score_b"]), "phase": ph, "pre": False, "label": "", "k": 0})
    cur = inp["season"]
    for w in sorted(results):
        for a, b, sa, sb, _o in results[w]:
            ph = "cup" if w in (cups.get(cur) or []) else "post" if w > inp["reg_weeks"] else "reg"
            out.append({"season": cur, "week": w, "a": a, "b": b, "sa": sa, "sb": sb, "phase": ph, "pre": False,
                        "label": "", "k": 0})
    out.sort(key=lambda g: (g["season"], g["week"], g["k"]))
    return out


def _when(g: dict, cur: str) -> str:
    if g["pre"]:
        return f"{g['season']} {g['label']}"
    return ("this season" if g["season"] == cur else g["season"]) + f", week {g['week']}"


def _short_when(g: dict) -> str:
    return f"{_short(g['season'])} {g['label']}" if g["pre"] else f"{_short(g['season'])} wk {g['week']}"


def runs(games: List[dict], me: str, opp: str) -> dict:
    """Each side's longest run of wins over the other across every meeting
    in a row, regular season, playoffs and Cup alike, across seasons; a T
    ends a run (LEAGUE_RULES "Streaks"; answer 6). {me: (n, first, last),
    opp: ...} with n 0 when he never beat the other."""
    seq = [g for g in games if {g["a"], g["b"]} == {me, opp}]
    best = {me: (0, None, None), opp: (0, None, None)}
    cur_who, n, first = None, 0, None
    for g in seq:
        sa, sb = (g["sa"], g["sb"]) if g["a"] == me else (g["sb"], g["sa"])
        who = me if sa > sb else opp if sb > sa else None
        if who is None or who != cur_who:
            cur_who, n, first = who, (1 if who else 0), g
        else:
            n += 1
        if who and n > best[who][0]:
            best[who] = (n, first, g)
    return best


# =============================================================================
# the card
# =============================================================================

def _hits_for(xs: List[float], x0: float, x1: float) -> List[tuple]:
    out = []
    for i, x in enumerate(xs):
        lo = x0 if i == 0 else (xs[i - 1] + x) / 2
        hi = x1 if i == len(xs) - 1 else (x + xs[i + 1]) / 2
        out.append((lo, max(hi, lo + 1)))
    return out


def _spread(ys: List[float], gap: float, lo: float, hi: float) -> List[float]:
    idx = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = [ys[i] for i in idx]
    for k in range(1, len(pos)):
        if pos[k] - pos[k - 1] < gap:
            pos[k] = pos[k - 1] + gap
    over = pos[-1] - hi if pos else 0
    if over > 0:
        pos = [p - over for p in pos]
    out = [0.0] * len(ys)
    for k, i in enumerate(idx):
        out[i] = pos[k]
    return out


def odds_chart(inp: dict, me: str, cls: dict) -> dict:
    """This season's title odds: one point per finished week (the first run
    after the week ended: its result priced) plus today's (the latest run);
    his line bold, the others faint, end labels. page._chart's shape."""
    from datetime import date, timedelta
    H_, X0, X1, Y0, Y1 = 170, 36, 286, 12, 132
    rows = [r for r in inp["history_rows"] if r.get("title_odds")]
    rows.sort(key=lambda r: r["as_of"])
    ms = inp["managers"]
    pts = []
    seen = set()
    for wk in sorted(inp["weeks"], key=lambda w: int(w["week"])):
        if int(wk["week"]) > inp["reg_weeks"]:
            break
        end = date.fromisoformat(str(wk["end_date"])[:10])
        nxt = [r for r in rows if r["as_of"][:10] > end.isoformat()]
        # the week's end point is the first run after it, in the week that follows (a week the history
        # had not begun for has no point); never a run after today
        if not nxt or nxt[0]["as_of"][:10] > min(inp["now"].date(), end + timedelta(days=7)).isoformat():
            continue
        r = nxt[0]
        if r["run_id"] in seen:
            continue
        seen.add(r["run_id"])
        pts.append((f"wk {int(wk['week'])}", f"after week {int(wk['week'])}", r))
    if rows and rows[-1]["run_id"] not in seen:
        pts.append(("now", "today", rows[-1]))
    out = {"vb": f"0 0 {W} {H_}", "aria": f"Title odds this season, {me} and the other three, at each week's end",
           "grid": [], "labels": [], "lines": [], "events": [], "ends": [], "hits": [], "dot": None,
           "empty": "" if pts else "No title odds yet this season.",
           "readout0": {"head": "Tap a week for everyone's odds.", "body": ""}}
    if not pts:
        return out
    top = max(50.0, 25.0 * math.ceil(max(float(r["title_odds"][m]) for _a, _b, r in pts for m in ms) / 25.0))

    def Y(v):
        return Y1 - (Y1 - Y0) * v / top
    n = len(pts)
    xs = [X0 + (X1 - X0) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
    for v in [25.0 * k for k in range(int(top // 25) + 1)]:
        out["grid"].append({"cls": "lh-c-base" if v == 0 else "lh-c-grid", "x1": _f(X0), "y1": _f(Y(v)),
                            "x2": _f(X1), "y2": _f(Y(v))})
        out["labels"].append({"x": _f(X0 - 4), "y": _f(Y(v) + 3), "t": f"{v:.0f}%", "anchor": "end"})
    out["labels"].append({"x": _f(xs[0]), "y": _f(Y1 + 16), "t": pts[0][0], "anchor": "start" if n > 1 else "middle"})
    if n > 1:
        out["labels"].append({"x": _f(xs[-1]), "y": _f(Y1 + 16), "t": pts[-1][0], "anchor": "end"})
    order = [m for m in ms if m != me] + [me]               # his line drawn last, on top
    for m in order:
        out["lines"].append({"cls": cls[m], "m": m, "proj": False, "style": "" if m == me else "faint",
                             "points": " ".join(f"{_f(x)},{_f(Y(float(r['title_odds'][m])))}"
                                                for x, (_a, _b, r) in zip(xs, pts))})
    last = pts[-1][2]["title_odds"]
    ys = _spread([Y(float(last[m])) for m in order], 12.0, Y0, Y1 - 2)
    out["ends"] = [{"cls": cls[m], "m": m, "style": "" if m == me else "faint", "x": _f(xs[-1] + 6),
                    "y": _f(y + 4), "t": f"{m} {float(last[m]):.0f}%"} for m, y in zip(order, ys)]
    out["dot"] = {"cls": cls[me], "cx": _f(xs[-1]), "cy": _f(Y(float(last[me])))}
    for (lo, hi), x, (lab, head, r) in zip(_hits_for(xs, X0, X1), xs, pts):
        body = DOT.join(f"{m} {float(r['title_odds'][m]):.1f}%" for m in sorted(ms, key=lambda k: -float(r['title_odds'][k])))
        out["hits"].append({"x": _f(lo), "y": _f(Y0 - 6), "w": _f(hi - lo), "h": _f(Y1 - Y0 + 12), "cx": _f(x),
                            "cy": _f(Y(float(r["title_odds"][me]))), "head": head.capitalize(), "body": body,
                            "label": f"{head}: {body}"})
    return out


def bar_chart(bars: List[dict], aria: str, unit_fmt, *, signed: bool, ref: Optional[tuple] = None,
              under: Optional[List[str]] = None) -> dict:
    """A small bar chart: bars [{"x": label, "v": float or None, "kind": ""|"live"|"none", "head", "body"}];
    a value-less bar is hatched (its season has no points on record). signed:
    bars rise and fall from 0. ref: (value, label), a dashed line."""
    H_, X0, X1, Y0, Y1 = 186, 34, 350, 14, 136 if not under else 126
    vals = [b["v"] for b in bars if b["v"] is not None] + ([ref[0]] if ref else [])
    if signed:
        top = max([50.0] + [50.0 * math.ceil(abs(v) / 50.0) for v in vals])
        lo, hi = -top, top
    else:
        step = 10.0 if max(vals or [1.0]) <= 60 else 50.0
        lo, hi = 0.0, max(step, step * math.ceil(max(vals or [1.0]) / step))

    def Y(v):
        return Y1 - (Y1 - Y0) * (v - lo) / (hi - lo)
    n = len(bars)
    slot = (X1 - X0) / max(n, 1)
    bw = min(26.0, slot * 0.66)
    out = {"vb": f"0 0 {W} {H_}", "aria": aria, "grid": [], "labels": [], "bars": [], "hits": [], "ref": None,
           "readout0": {"head": "Tap a season.", "body": ""}}
    for v in ((lo, 0.0, hi) if signed else (lo, (lo + hi) / 2, hi)):
        out["grid"].append({"cls": "lh-c-base" if v == 0 else "lh-c-grid", "x1": _f(X0), "y1": _f(Y(v)),
                            "x2": _f(X1), "y2": _f(Y(v))})
        out["labels"].append({"x": _f(X0 - 4), "y": _f(Y(v) + 3), "t": unit_fmt(v), "anchor": "end"})
    for i, b in enumerate(bars):
        cx = X0 + slot * (i + 0.5)
        x = cx - bw / 2
        if b["v"] is None:
            out["bars"].append({"x": _f(x), "y": _f(Y0), "w": _f(bw), "h": _f(Y1 - Y0), "cls": "mc-hatch",
                                "t": "", "ty": ""})
            cy = (Y0 + Y1) / 2
        else:
            y0, y1 = sorted((Y(0.0 if signed else lo), Y(b["v"])))
            cls = "mc-bar-up" if (b["v"] >= 0 or not signed) else "mc-bar-dn"
            if b.get("kind") == "live":
                cls += " mc-bar-live"
            ty = (y0 - 3) if (b["v"] >= 0 or not signed) else (y1 + 10)
            out["bars"].append({"x": _f(x), "y": _f(y0), "w": _f(bw), "h": _f(max(y1 - y0, 1.0)), "cls": cls,
                                "t": b.get("t", ""), "ty": _f(ty), "tx": _f(cx)})
            cy = Y(b["v"])
        # a season's label in two lines ("18" over "19"): thirteen fit the phone's width
        ly = Y1 + 13
        for j, part in enumerate(str(b["x"]).split("-")):
            out["labels"].append({"x": _f(cx), "y": _f(ly + 11 * j), "t": part, "anchor": "middle"})
        if under:
            out["labels"].append({"x": _f(cx), "y": _f(ly + 24), "t": under[i], "anchor": "middle"})
        out["hits"].append({"x": _f(X0 + slot * i), "y": _f(Y0 - 6), "w": _f(slot), "h": _f(Y1 - Y0 + 12),
                            "cx": _f(cx), "cy": _f(cy), "head": b["head"], "body": b["body"],
                            "label": f"{b['head']}: {b['body']}"})
    if ref is not None:
        out["ref"] = {"x1": _f(X0), "x2": _f(X1), "y": _f(Y(ref[0])), "t": ref[1]}
    return out


def fill_chart(series: List[tuple], me: str, cls_me: str) -> dict:
    """His share of the daily slots filled, against the league's, by season:
    series [(season, his %, league %)], two lines (his solid, the league's
    dashed), page._chart's shape."""
    H_, X0, X1, Y0, Y1 = 160, 36, 286, 12, 124
    out = {"vb": f"0 0 {W} {H_}", "aria": f"{me}'s share of all daily lineup slots filled, against the league's, "
           "by season", "grid": [], "labels": [], "lines": [], "events": [], "ends": [], "hits": [], "dot": None,
           "empty": "" if series else "No finished season with lineup data.",
           "readout0": {"head": "Tap a season.", "body": ""}}
    if not series:
        return out
    vals = [v for _s, a, b in series for v in (a, b)]
    lo = 5.0 * math.floor(min(vals) / 5.0)
    hi = max(lo + 5.0, 5.0 * math.ceil(max(vals) / 5.0))

    def Y(v):
        return Y1 - (Y1 - Y0) * (v - lo) / (hi - lo)
    n = len(series)
    xs = [X0 + (X1 - X0) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
    for v in (lo, (lo + hi) / 2, hi):
        out["grid"].append({"cls": "lh-c-base" if v == lo else "lh-c-grid", "x1": _f(X0), "y1": _f(Y(v)),
                            "x2": _f(X1), "y2": _f(Y(v))})
        out["labels"].append({"x": _f(X0 - 4), "y": _f(Y(v) + 3), "t": f"{v:.0f}%", "anchor": "end"})
    out["labels"].append({"x": _f(xs[0]), "y": _f(Y1 + 16), "t": _short(series[0][0]),
                          "anchor": "start" if n > 1 else "middle"})
    if n > 1:
        out["labels"].append({"x": _f(xs[-1]), "y": _f(Y1 + 16), "t": _short(series[-1][0]), "anchor": "end"})
    out["lines"].append({"cls": "mc-lg", "m": "", "proj": False, "style": "dash",
                         "points": " ".join(f"{_f(x)},{_f(Y(b))}" for x, (_s, _a, b) in zip(xs, series))})
    out["lines"].append({"cls": cls_me, "m": "", "proj": False, "style": "",
                         "points": " ".join(f"{_f(x)},{_f(Y(a))}" for x, (_s, a, _b) in zip(xs, series))})
    la, lb = series[-1][1], series[-1][2]
    ya, yb = _spread([Y(la), Y(lb)], 12.0, Y0, Y1 - 2)
    out["ends"] = [{"cls": cls_me, "x": _f(xs[-1] + 6), "y": _f(ya + 4), "t": f"{la:.1f}%"},
                   {"cls": "mc-lg", "x": _f(xs[-1] + 6), "y": _f(yb + 4), "t": f"league {lb:.1f}%"}]
    out["dot"] = {"cls": cls_me, "cx": _f(xs[-1]), "cy": _f(Y(la))}
    for (a0, a1), x, (s, a, b) in zip(_hits_for(xs, X0, X1), xs, series):
        body = f"{me} {a:.1f}%{DOT}the league {b:.1f}%"
        out["hits"].append({"x": _f(a0), "y": _f(Y0 - 6), "w": _f(a1 - a0), "h": _f(Y1 - Y0 + 12), "cx": _f(x),
                            "cy": _f(Y(a)), "head": s, "body": body, "label": f"{s}: {body}"})
    return out


def _ages(extra: dict):
    """(season, name) -> age on Feb 1 (keeper_history.age_for over the
    basketball-reference cache, read only: no fetch), or None."""
    from ..keeper_history import age_for, AgeNotFound
    from ..data_loader import PlayerIndex
    cache = (extra.get("bbref_ages") or {}).get("seasons") or {}
    idx = {s: PlayerIndex(v.get("ages") or {}) for s, v in cache.items()}

    def get(season, name):
        try:
            return age_for(idx, season, name)[0]
        except AgeNotFound:
            return None
    return get


def build(inp: dict, results: dict, extra: dict) -> dict:
    """Every manager's card. inp: league.gather's inputs; results:
    league.week_results(inp); extra: manager_inputs(...)."""
    from .. import trophy_case as TC
    from .. import money as MO
    ms = inp["managers"]
    cur = inp["season"]
    cls = {m: f"lh-t-{inp['teams'][m]['slot']}" for m in ms}
    tab = seasons_table(inp, results)
    seasons, srows = tab["seasons"], tab["rows"]
    done = [s for s in seasons if s != cur]
    cfg = {"managers": list(ms), "pre_data_era": inp.get("pre_data_era") or {},
           "keeper_rules": {"cup_winners": inp.get("cup_winners") or {}}}
    tc = TC.build(inp.get("base") or ".", past=inp.get("awards_past"), standings=inp["all_standings"], cfg=cfg,
                  managers=ms)
    tcm = {r["m"]: r for r in tc["managers"]}
    at = L.alltime(inp, results)
    atm = {r["m"]: r for r in at["rows"]}
    games = meetings(inp, results)
    rec_all = inp["records_alltime"] or {}
    past = inp.get("awards_past")
    st = L.standings(inp, results)
    stm = {r["m"]: r for r in st["rows"]}
    power = {r["manager"]: r for r in inp["power"]["rows"]}
    ages = _ages(extra)
    keepers = _keepers(inp)
    trades = _trades(inp)
    money = _money(inp, srows, done, extra)
    cards = {}
    for m in ms:
        cards[m] = _card(m, inp, results, extra, tab, tcm, atm, games, rec_all, past, stm, power, ages,
                         keepers, trades, money, cls)
    return {"order": list(ms), "cards": cards}


def _keepers(inp: dict) -> Dict[str, Dict[str, List[str]]]:
    """{season: {manager: [kept players]}}: all_drafts' keepers (2021-22 on:
    LEAGUE_RULES "Drafts and keepers by season") and this season's draft."""
    out: Dict[str, Dict[str, list]] = {}
    for r in list(inp["all_drafts"]) + list((inp.get("draft_current") or {}).get("picks") or []):
        if r.get("is_keeper"):
            s = r.get("season") or (inp.get("draft_current") or {}).get("season")
            out.setdefault(s, {}).setdefault(r["manager"], []).append(r["player_name"])
    return out


def _trades(inp: dict) -> List[dict]:
    """Every completed trade, past (all_trades.json) and this season
    (TRADES.json): {"season", "date", "a", "b"}."""
    out = []
    for t in list(inp["all_trades"]) + list(inp.get("trades_now") or []):
        a, b = t.get("trader_manager"), t.get("tradee_manager")
        if not a or not b:
            raise ManagerError(f"a {t.get('season')} trade has no managers")
        out.append({"season": t["season"], "date": str(t.get("date") or "")[:10], "a": a, "b": b})
    return out


def _money(inp: dict, srows: dict, done: List[str], extra: dict) -> dict:
    """{season: {m: {"regular", "playoffs"}}} for every finished season
    (modules/money), plus this season's regular-season pot once weeks
    1-15 are all played; {season: "why"} for a season with no playoff pot."""
    from .. import money as MO
    out, why = {}, {}
    for s in done:
        rows = srows[s]
        order = sorted(rows, key=lambda m: rows[m]["finish"])
        any_r = next(iter(rows.values()))
        if any_r["bracket"]:
            ch = [m for m, r in rows.items() if r["po"] == "won"]
            ru = [m for m, r in rows.items() if r["po"] == "final"]
            sl = [m for m, r in rows.items() if r["po"] == "semi"]
            if len(ch) != 1 or len(ru) != 1 or len(sl) != 2:
                raise ManagerError(f"{s}: the bracket's places are not one champion, one runner-up and two "
                                   "semifinal losers")
            br = {"champion": ch[0], "runner_up": ru[0], "semifinal_losers": sl}
        else:
            br = None
            why[s] = (inp["season_structure"].get(s) or {}).get("note") or "no bracket was played"
        out[s] = MO.nets(s, order, br, extra.get("config"))
    return {"nets": out, "no_bracket": why}


def _card(m, inp, results, extra, tab, tcm, atm, games, rec_all, past, stm, power, ages, keepers, trades,
          money, cls) -> dict:
    ms = inp["managers"]
    cur = inp["season"]
    seasons, srows = tab["seasons"], tab["rows"]
    mine = {s: srows[s][m] for s in seasons}
    team = inp["teams"][m]
    route = f"manager/{m}"

    # ---------------------------------------------------------------- hero
    names, run = [], []
    for s in seasons:
        t = mine[s]["team"]
        if run and run[-1][0] == t:
            run[-1][1].append(s)
        else:
            run.append((t, [s]))
    for t, ss in reversed(run):
        names.append({"t": f"{t}{DOT}{_span(ss, cur)}", "now": ss[-1] == cur})
    n_seasons = len(seasons)
    tc = tcm[m]
    def _list(k):
        return ", ".join(_short(x["season"]) for x in tc["items"][k])
    cup_played = any(v for s, v in (inp.get("cup_winners") or {}).items() if not s.startswith("_"))
    hon = [{"k": "lc", "n": str(tc["counts"]["league"]), "label": "League Championships"
            if tc["counts"]["league"] != 1 else "League Championship", "sub": _list("league") or "none yet"},
           {"k": "po", "n": str(tc["counts"]["playoff"]), "label": "Playoff titles"
            if tc["counts"]["playoff"] != 1 else "Playoff title", "sub": _list("playoff") or "none yet"},
           {"k": "cup", "n": str(tc["counts"]["cup"]), "label": "Cup",
            "sub": _list("cup") or ("none yet" if cup_played else "the first Cup is this season")}]
    a = atm[m]
    pre_s = [s for s in seasons if mine[s]["kind"] == "pre"]
    yahoo_s = [s for s in seasons if mine[s]["kind"] == "yahoo"]
    hero = {"name": m, "team": team["team"],
            "bio": f"{team['team']}{DOT}{_ord(n_seasons)} season{DOT}in the league since {seasons[0]}",
            "names": names, "hon": hon,
            "kpis": [{"label": "Career record", "v": a["record"], "sub": "regular season"},
                     {"label": "Win %", "v": a["pct"], "sub": "a T counts half"},
                     {"label": "All-time rank", "v": _ord(int(a["rank"])), "sub": f"of {len(ms)}, by win %"}],
            "foot": (f"{n_seasons} seasons: " + (" and ".join(pre_s) + " are standings and brackets only (no "
                     "weekly scores or stats), " if pre_s else "")
                     + (f"{yahoo_s[0]} to {yahoo_s[-1]} from Yahoo, " if yahoo_s else "")
                     + f"this season live through week {tab['through']}. 2015-16 was not played."),
            "team_href": f"#/teams/{m}"}

    # ---------------------------------------------------------------- overview: this season
    me_now = mine[cur]
    pr = power.get(m)
    if pr is None:
        raise ManagerError(f"the power rows have no {m}")
    gap = None if me_now["ppw"] is None or me_now["lg_ppw"] is None else me_now["ppw"] - me_now["lg_ppw"]
    rank = int(stm[m]["rank"])
    season = {"meta": (f"week {tab['through']}{DOT}{_ord(rank)}, {stm[m]['record']}" if tab["through"]
                       else "no week played yet"),
              "kpis": [{"label": inp["power"]["label"], "v": pr["odds"],
                        "sub": (pr["delta"] + " since the run before") if pr["delta"] else "",
                        "dir": pr["delta_dir"] or ""},
                       {"label": "Record", "v": stm[m]["record"], "sub": f"{_ord(rank)} of {len(ms)}", "dir": ""},
                       {"label": "Pts a week", "v": DASH if gap is None else _signed0(gap),
                        "sub": "vs the league" if gap is not None else "no week played yet", "dir": ""}],
              "chart": odds_chart(inp, m, cls)}

    # ---------------------------------------------------------------- overview: every season (the strip)
    strip = []
    for s in seasons:
        r = mine[s]
        marks = (STAR if r["lc"] else "") + (DIAMOND if r["pc"] else "") + ("" if r["bracket"] else "–")
        if r["kind"] == "live":
            body = f"{_ord(r['finish'])} so far, {_rec3(r['w'], r['l'], r['t'])} through week {tab['through']}."
        else:
            bits = [f"{_ord(r['finish'])}, {_rec3(r['w'], r['l'], r['t'])}."]
            po = _po_text(r, s, srows, m, inp)
            if r["lc"]:
                bits.append("League Championship;")
            else:
                po = po[:1].upper() + po[1:]
            bits.append(po + ".")
            body = " ".join(bits)
        body += f" Team: {r['team']}."
        if r["kind"] == "pre":
            body += " Standings and brackets only."
        strip.append({"s": s, "yr": _short(s)[:2], "yr2": _short(s)[3:], "place": str(r["finish"]),
                      "p": f"mc-p{r['finish']}",
                      "kind": r["kind"], "marks": marks, "tip": f"{s}{DOT}{body}"})
    sel = max(range(len(strip)), key=lambda i: (mine[seasons[i]]["lc"], mine[seasons[i]]["pc"], -i)) \
        if strip else None
    strip_v = {"cells": strip, "n": str(len(strip)), "readout": strip[sel]["tip"] if sel is not None else "",
               "sel": seasons[sel] if sel is not None else "",
               "note": "2015-16 was not played (no square)."}

    # ---------------------------------------------------------------- rivals
    rivals = _rivals(m, inp, games, cls)

    # ---------------------------------------------------------------- players
    players = _players(m, inp, rec_all, past, keepers, ages, trades)

    # ---------------------------------------------------------------- career
    career = _career(m, inp, extra, tab, mine, past, keepers, ages, trades)

    # ---------------------------------------------------------------- trophies
    trophies = _trophies(m, inp, tc, mine, srows, rec_all, money)

    # ---------------------------------------------------------------- at a glance
    best_s = max((s for s in seasons if mine[s]["kind"] == "yahoo"),
                 key=lambda s: ((mine[s]["w"] + 0.5 * mine[s]["t"]) / max(1, mine[s]["w"] + mine[s]["l"] + mine[s]["t"]),
                                mine[s]["ppw"] or 0.0), default=None)
    glance = []
    fp = players["franchise"]
    glance.append({"k": "Franchise player", "b": fp["name"] if fp else DASH,
                   "e": (f"{fp['sub_short']}" if fp else "not in the record book yet"), "tab": "players"})
    rr = [r for r in rivals["phases"][0]["rows"] if r["g"]]
    if rr:
        bestr = max(rr, key=lambda r: (r["_pct"], r["o"]))
        glance.append({"k": "Best rivalry", "b": f"v {bestr['o']} {bestr['rec']}",
                       "e": f"{bestr['pct_s']}{DOT}longest run {bestr['his_run']['v']}", "tab": "rivals"})
        nem = rivals["nemesis"]
        glance.append({"k": "Nemesis", "b": f"v {nem['o']} {nem['rec']}" if nem else "No nemesis",
                       "e": nem["sub"] if nem else ".500 or better against everyone", "tab": "rivals"})
    if best_s:
        r = mine[best_s]
        g = "" if r["ppw"] is None or r["lg_ppw"] is None else f"{_signed0(r['ppw'] - r['lg_ppw'])} a week{DOT}"
        glance.append({"k": "Best season", "b": f"{best_s}{DOT}{_rec3(r['w'], r['l'], r['t'])}",
                       "e": f"{g}{_ord(r['finish'])}", "tab": "career"})
    rh = trophies["records"]
    glance.append({"k": "Records he holds", "b": f"{len(rh['rows'])} league record" + ("" if len(rh["rows"]) == 1 else "s"),
                   "e": rh["more"], "tab": "trophies"})
    sty = career["style"]
    glance.append({"k": "His style", "b": sty["glance_b"], "e": sty["glance_e"], "tab": "career"})
    for t in glance:
        t["href"] = f"#/{route}/{t['tab']}"
    return {"m": m, "route": route, "team": dict(team), "hero": hero,
            "overview": {"season": season, "strip": strip_v, "glance": glance},
            "career": career, "rivals": rivals, "players": players, "trophies": trophies,
            "tabs": [{"k": k, "t": t} for k, t in TABS]}


def _po_text(r: dict, s: str, srows: dict, m: str, inp: dict) -> str:
    if not r["bracket"]:
        note = (inp["season_structure"].get(s) or {}).get("note") or "none played"
        return f"no playoffs that season ({note})"
    other = {x: v for x, v in srows[s].items() if x != m}
    if r["po"] == "won":
        ru = next((x for x, v in other.items() if v["po"] == "final"), None)
        return f"won the playoffs over {ru}" if ru else "won the playoffs"
    if r["po"] == "final":
        ch = next((x for x, v in other.items() if v["po"] == "won"), None)
        return f"lost the playoff final to {ch}" if ch else "lost the playoff final"
    return "lost in the playoff semifinals"


PO_SHORT = {"won": "Won " + DIAMOND, "final": "Final", "semi": "Semi", "none_held": "none held", "live": "so far"}


def _career(m, inp, extra, tab, mine, past, keepers, ages, trades) -> dict:
    cur = inp["season"]
    seasons = tab["seasons"]
    bars, rows = [], []
    for s in seasons:
        r = mine[s]
        if r["ppw"] is None or r["lg_ppw"] is None:
            if r["kind"] == "pre":
                bars.append({"x": _short(s), "v": None, "kind": "none", "head": s,
                             "body": "standings and brackets only: no weekly scores on record"})
            continue
        d = r["ppw"] - r["lg_ppw"]
        bars.append({"x": _short(s), "v": d, "kind": "live" if r["kind"] == "live" else "", "t": _signed0(d),
                     "head": s + (" so far" if r["kind"] == "live" else ""),
                     "body": f"{m} {r['ppw']:,.0f} a week{DOT}the league {r['lg_ppw']:,.0f}{DOT}{_signed0(d)}"})
    ppw = bar_chart(bars, f"{m}'s regular-season points a week against the league's average, by season",
                    lambda v: _signed0(v) if v else "0", signed=True)
    for s in reversed(seasons):
        r = mine[s]
        rows.append({"s": s, "team": r["team"] if r["kind"] != "pre" else f"{r['team']} (standings only)",
                     "fin": _ord(r["finish"]) + (f" {STAR}" if r["lc"] else ""),
                     "wl": _rec3(r["w"], r["l"], r["t"]),
                     "ppw": DASH if r["ppw"] is None else f"{r['ppw']:,.0f}",
                     "gap": "" if r["ppw"] is None or r["lg_ppw"] is None else _signed0(r["ppw"] - r["lg_ppw"]),
                     "po": PO_SHORT[r["po"]], "pre": r["kind"] == "pre", "live": r["kind"] == "live"})
    pre = [s for s in seasons if mine[s]["kind"] == "pre"]
    note = ((" and ".join(pre) + ": standings and brackets only (Yahoo's final standings and brackets); no weekly "
             "scores, so no points a week. ") if pre else "") + "2015-16 was not played. " + \
        "Points a week are the regular season's, because seasons ran 16 to 21 weeks."
    # his style: lineup fill and pickups (the awards' own counts, finished seasons), keepers' age, trades
    fill, adds, lg_adds = [], [], []
    seas_p = sorted((past or {}).get("seasons") or {})
    for s in seas_p:
        mg = past["seasons"][s]["managers"]
        tops = mg["lineup"]["top"]
        me_l = next((x for x in tops if x["m"] == m), None)
        if me_l is not None:
            for k in ("filled", "slots"):
                if any(k not in x for x in tops):
                    raise ManagerError(f"AWARDS_PAST {s} lineup rows lack {k}")
            lg = 100.0 * sum(x["filled"] for x in tops) / sum(x["slots"] for x in tops)
            fill.append((s, 100.0 * me_l["filled"] / me_l["slots"], lg))
        wv = mg["waiver"]["top"]
        me_w = next((x for x in wv if x["m"] == m), None)
        if me_w is not None:
            if any("n" not in x for x in wv):
                raise ManagerError(f"AWARDS_PAST {s} waiver rows lack n (pickups)")
            adds.append((s, int(me_w["n"]), False))
            lg_adds += [int(x["n"]) for x in wv]
    n_now = (extra.get("adds_now") or {}).get(m)
    if n_now is not None:
        adds.append((cur, int(n_now), True))
    tr_by = {}
    for t in trades:
        if m in (t["a"], t["b"]):
            tr_by[t["season"]] = tr_by.get(t["season"], 0) + 1
    lg_avg = (sum(lg_adds) / len(lg_adds)) if lg_adds else None
    pbars = [{"x": _short(s), "v": float(n), "kind": "live" if live else "", "t": str(n),
              "head": s + (" so far" if live else ""),
              "body": (f"{n} pickups" + (f"{DOT}{tr_by.get(s, 0)} trade" + ("" if tr_by.get(s, 0) == 1 else "s")))}
             for s, n, live in adds]
    pick_ch = bar_chart(pbars, f"{m}'s pickups a season" + (", against the league's average" if lg_avg else ""),
                        lambda v: f"{v:.0f}", signed=False,
                        ref=(lg_avg, f"avg {lg_avg:.0f}") if lg_avg is not None else None,
                        under=[("⇄" + str(tr_by[s])) if tr_by.get(s) else "·" for s, _n, _l in adds])
    # keepers' average age
    kept_ages, lg_ages, missing = [], [], 0
    for s, by in keepers.items():
        for who, names in by.items():
            for nm in names:
                a = ages(s, nm)
                if a is None:
                    missing += who == m
                    continue
                lg_ages.append(a)
                if who == m:
                    kept_ages.append(a)
    k_avg = sum(kept_ages) / len(kept_ages) if kept_ages else None
    lg_k = sum(lg_ages) / len(lg_ages) if lg_ages else None
    lean = "" if k_avg is None or lg_k is None else ("leans young" if k_avg < lg_k - 0.3 else
                                                      "leans old" if k_avg > lg_k + 0.3 else "about the league's")
    n_tr = sum(tr_by.values())
    with_ = {}
    for t in trades:
        if m in (t["a"], t["b"]):
            o = t["b"] if t["a"] == m else t["a"]
            with_[o] = with_.get(o, 0) + 1
    most = max(sorted(with_), key=lambda o: with_[o]) if with_ else None
    fill_last = fill[-1] if fill else None
    style = {"fill": fill_chart(fill, m, f"lh-t-{inp['teams'][m]['slot']}"),
             "fill_note": ("Lineup: his started games over every daily slot (10 a day with NBA games), against the "
                           "league's, each finished season since " + fill[0][0] + "." if fill else
                           "No finished season with lineup data yet."),
             "picks": pick_ch,
             "picks_note": ("Pickups a season: players added, from the daily rosters (the awards' own count) for "
                            "finished seasons" + (f"; this season from the move log, {n_now} so far (3 a week "
                                                  "allowed)" if n_now is not None else "")
                            + (f". Dashed: the league's average, {lg_avg:.0f} a season." if lg_avg else ".")
                            + " ⇄ = his trades that season."),
             "tiles": [{"k": "Keepers' average age", "b": DASH if k_avg is None else f"{k_avg:.1f}",
                        "e": ("no keepers on record" if k_avg is None else
                              f"league {lg_k:.1f}{DOT}{lean}" + (f"{DOT}{missing} without an age" if missing else ""))},
                       {"k": "Trades", "b": f"{n_tr} in {len(tr_by)} season" + ("" if len(tr_by) == 1 else "s"),
                        "e": f"most with {most} ({with_[most]})" if most else "none on record"}],
             "glance_b": (f"Lineup: {fill_last[1]:.1f}%" if fill_last else f"{n_tr} trades"),
             "glance_e": ((f"league {fill_last[2]:.1f}%" if fill_last else "")
                          + (f"{DOT}keepers {lean}" if lean else ""))}
    return {"ppw": ppw, "ppw_note": "Per regular-season week, against that season's league average. "
            + ("Hatched: standings and brackets only. " if pre else "") + "This season's bar is faint: live.",
            "rows": rows, "note": note, "style": style}


def _rivals(m, inp, games, cls) -> dict:
    cur = inp["season"]
    ms = inp["managers"]
    opps = [o for o in ms if o != m]
    phases = []
    for k, lab in PHASES:
        rows = []
        for o in opps:
            gs = [g for g in games if {g["a"], g["b"]} == {m, o} and g["phase"] == k]
            w = l = t = 0
            for g in gs:
                sa, sb = (g["sa"], g["sb"]) if g["a"] == m else (g["sb"], g["sa"])
                w += sa > sb
                l += sb > sa
                t += sa == sb
            n = w + l + t
            pct = (w + 0.5 * t) / n if n else 0.0
            rows.append({"o": o, "g": n, "rec": _rec3(w, l, t), "_pct": pct, "pct_s": _pct3(w, l, t),
                         "pct": f"{100 * pct:.1f}%" if n else DASH,
                         "bar": f"{100 * pct:.1f}%" if n else "50%",
                         "pre": any(g["pre"] for g in gs)})
        phases.append({"k": k, "t": lab, "rows": rows})
    # each opponent's shared lines: runs, biggest win, worst loss, last meeting, playoffs
    info = {}
    for o in opps:
        gs = [g for g in games if {g["a"], g["b"]} == {m, o}]
        rn = runs(games, m, o)

        def run_v(who):
            n, a, b = rn[who]
            if not n:
                return {"v": DASH, "e": "never"}
            span = _short_when(a) if a is b else f"{_short_when(a)} → {_short_when(b)}"
            return {"v": f"W{n}", "e": span}
        wins = [(g, (g["sa"] - g["sb"]) if g["a"] == m else (g["sb"] - g["sa"])) for g in gs]
        bw = max(wins, key=lambda x: x[1], default=None)
        wl = min(wins, key=lambda x: x[1], default=None)
        last = gs[-1] if gs else None
        post = phases[1]["rows"][opps.index(o)]
        if last is not None:
            d = (last["sa"] - last["sb"]) if last["a"] == m else (last["sb"] - last["sa"])
            last_t = (("Won by " if d > 0 else "Lost by " if d < 0 else "Tied") + (f"{abs(d):,.1f}" if d else "")
                      + f"{DOT}{_when(last, cur)}")
        else:
            last_t = "They have not met."
        info[o] = {"his_run": run_v(m), "their_run": run_v(o),
                   "big_win": {"v": _signed1(bw[1]) if bw and bw[1] > 0 else DASH,
                               "e": _when(bw[0], cur) if bw and bw[1] > 0 else "never beaten him"},
                   "worst_loss": {"v": _signed1(wl[1]) if wl and wl[1] < 0 else DASH,
                                  "e": _when(wl[0], cur) if wl and wl[1] < 0 else "never lost to him"},
                   "last": f"Last meeting: {last_t}", "post": f"playoffs {post['rec']}" if post["g"] else "no playoff meeting",
                   "team": inp["teams"][o]["team"], "cls": cls[o]}
    for ph in phases:
        for r in ph["rows"]:
            r.update(info[r["o"]])
    reg = phases[0]["rows"]
    losing = [r for r in reg if r["g"] and r["_pct"] < 0.5]
    nem = min(losing, key=lambda r: (r["_pct"], r["o"])) if losing else None
    nemesis = None
    if nem is not None:
        nemesis = {"o": nem["o"], "rec": nem["rec"], "sub": f"{nem['pct_s']}{DOT}{nem['post']}"}
        for ph in phases:
            for r in ph["rows"]:
                r["nemesis"] = r["o"] == nem["o"]
    for ph in phases:
        for r in ph["rows"]:
            r.setdefault("nemesis", False)
        ph["rows"].sort(key=lambda r: (r["g"] == 0, -r["_pct"], r["o"]))
    w = sum(L._wl(r["rec"])[0] for r in reg)
    l = sum(L._wl(r["rec"])[1] for r in reg)
    t = sum(L._wl(r["rec"])[2] for r in reg)
    cupw = inp.get("cup_weeks") or {}
    first_cup = min((s for s, v in cupw.items() if v), default=None)
    pre_any = any(r["pre"] for r in phases[1]["rows"])
    intro = {"reg": (f"Against all three: {_rec3(w, l, t)}. The regular season's head to head starts in 2017-18 "
                     "(the Yahoo data): the two seasons before it have standings only, so this won't sum to his "
                     "career record."),
             "post": ("The bracket and the third-place games"
                      + (", the 2014-15 and 2016-17 brackets included (standings and brackets only)" if pre_any else "")
                      + "."),
             "cup": (("No Cup played yet: the first is weeks 22" + NDASH + f"23 of {first_cup}.") if first_cup else
                     "No Cup yet.")}
    for ph in phases:
        ph["intro"] = intro[ph["k"]]
        ph["empty"] = ph["k"] == "cup" and not any(r["g"] for r in ph["rows"])
    return {"phases": phases, "nemesis": nemesis,
            "note": "Runs count every meeting in a row, across seasons: regular season, playoffs and Cup; a T ends "
                    "a run. Biggest win and worst loss are over every meeting."}


def _players(m, inp, rec_all, past, keepers, ages, trades) -> dict:
    # franchise player: the record book's (started games, answer 7)
    badges = rec_all.get("franchise_badges") or {}
    b = badges.get(m)
    fp = None
    if b:
        how = _how_he_came(inp, m, b["player"])
        bits = []
        if b.get("first") and b.get("last"):
            bits.append(b["first"] if b["first"] == b["last"] else f"{b['first']} to {b['last']}")
        if b.get("seasons"):
            bits.append(f"{int(b['seasons'])} season" + ("" if int(b["seasons"]) == 1 else "s")
                        + (f", {int(b['gp']):,} starts" if b.get("gp") else ""))
        if how:
            bits.append(how)
        fp = {"name": b["player"], "card": L._slug(b["player"]), "ini": "".join(w[0] for w in b["player"].split()[:2]),
              "pts": f"{float(b['total_fp']):,.1f}", "sub": DOT.join(bits),
              "sub_short": (f"{int(b['seasons'])} seasons{DOT}" if b.get("seasons") else "")
              + f"{float(b['total_fp']):,.0f} pts"}
    # best pickups: the awards' season top-fives (AWARDS_PAST keeps five a season)
    pk = []
    for s, v in sorted(((past or {}).get("seasons") or {}).items()):
        a = v["awards"]["pickup"]
        win = (a.get("winner") or {}).get("player")
        for x in a.get("top") or []:
            if x["m"] == m:
                pk.append({"name": x["player"], "card": L._slug(x["player"]), "v": f"{float(x['value']):,.1f}",
                           "unit": "PAR", "_v": float(x["value"]),
                           "sub": f"{s}{DOT}added {str(x.get('add_day') or '')[5:]}"
                                  + (f"{DOT}Best pickup" if x["player"] == win else "")})
    pk.sort(key=lambda x: -x["_v"])
    # best trades: the awards' trade rows (each side's PAR, picks estimated), his gap
    tr = []
    for s, v in sorted(((past or {}).get("seasons") or {}).items()):
        a = v["awards"]["trade"]
        win_label = (a.get("winner") or {}).get("label")
        for x in a.get("top") or []:
            sides = x.get("sides") or {}
            if m not in sides:
                continue
            o = next(k for k in sides if k != m)
            gap = float(sides[m]["par"]) - float(sides[o]["par"])
            got = ", ".join(sides[m].get("got") or []) or "picks"
            gave = ", ".join(sides[o].get("got") or []) or "picks"
            tr.append({"o": o, "when": f"{s}, {str(x.get('date') or '')[5:]}", "got": got, "gave": gave, "_v": gap,
                       "v": _signed1(gap), "unit": "Trade of the Year" if x.get("label") == win_label and gap > 0
                       else "PAR gap"})
    tr.sort(key=lambda x: -x["_v"])
    best_tr = [x for x in tr if x["_v"] > 0][:3]
    worst = min(tr, key=lambda x: x["_v"]) if tr and tr[-1]["_v"] < 0 else None
    n_tr_all = sum(1 for t in trades if m in (t["a"], t["b"]) and t["season"] != inp["season"])
    # draft classes: Draft of the year's measure, his class each season
    dr = []
    for s, v in sorted(((past or {}).get("seasons") or {}).items()):
        top = v["managers"]["draft"]["top"]
        x = next((r for r in top if r["m"] == m), None)
        if x is not None:
            dr.append({"s": s, "v": f"{float(x['value']):,.0f}", "_v": float(x["value"]),
                       "name": x.get("best") or "", "card": L._slug(x["best"]) if x.get("best") else None,
                       "won": m in (v["managers"]["draft"].get("winners") or [])})
    dr.sort(key=lambda x: -x["_v"])
    no_list = [s for s, v in sorted(((past or {}).get("seasons") or {}).items())
               if not v["managers"]["draft"]["top"]]
    # keepers by season
    ks = []
    prev = set()
    for s in sorted(keepers):
        names = sorted(keepers[s].get(m) or [])
        if not names:
            prev = set()
            continue
        ag = [ages(s, n) for n in names]
        known = [a for a in ag if a is not None]
        ks.append({"s": s, "names": [{"t": n.split()[-1] if len(n.split()) > 1 else n, "full": n,
                                      "card": L._slug(n), "new": n not in prev and bool(prev)} for n in names],
                   "age": f"{sum(known) / len(known):.1f}" if known else DASH})
        prev = set(names)
    ks.reverse()
    return {"franchise": fp,
            "franchise_note": ("Most fantasy points for him in his started games, every season in the league "
                               "log (the record book's franchise player)."),
            "pickups": pk[:3],
            "pickups_note": ("PAR for him in his starts after the add. From each finished season's five best "
                             "pickups in the league (the awards keep five a season)." if pk else
                             "No pickup of his is among a finished season's five best (the awards keep five a "
                             "season)."),
            "trades": best_tr, "worst_trade": worst,
            "trades_note": (f"Each side's PAR in its own starts after the trade, picks estimated; his side's minus "
                            f"the other's. {len(tr)} of his {n_tr_all} past trades are measured (the awards keep each "
                            "season's top five)." if n_tr_all else "No past trade on record."),
            "drafts": dr[:3],
            "drafts_note": ("Draft of the year's measure: his draft class's PAR, keepers apart, with its best pick. "
                            "No pick numbers before 2024-25 (their order isn't trusted)."
                            + (f" No {', '.join(no_list)}: that draft list isn't on record." if no_list else "")),
            "keepers": ks,
            "keepers_note": ("Six a season from 2021-22 (full-pool snake drafts before). Outlined: kept for the first "
                             "time. Ages on February 1 of the season (basketball-reference).")}


def _how_he_came(inp: dict, m: str, player: str) -> str:
    rows = sorted((r for r in inp["all_drafts"] if r["manager"] == m and r["player_name"] == player),
                  key=lambda r: r["season"])
    if not rows:
        return ""
    kept = sum(1 for r in rows if r.get("is_keeper"))
    first = "kept" if rows[0].get("is_keeper") else "drafted"
    if first == "drafted" and kept:
        return f"drafted, then kept {kept} time" + ("" if kept == 1 else "s")
    if first == "kept":
        return f"kept {kept} time" + ("" if kept == 1 else "s")
    return "drafted"


def _trophies(m, inp, tc, mine, srows, rec_all, money) -> dict:
    from .. import trophy_case as TC
    cur = inp["season"]
    case = []
    for k in TC.ORDER:
        n = tc["counts"][k]
        its = tc["items"][k]
        case.append({"k": k, "n": str(n), "label": TC.LABELS[k], "apart": k in TC.APART,
                     "tip": None if not its else {"h": f"{m}: {TC.LABELS[k]}",
                                                  "b": "; ".join(f"{x['season']} {x['what']}".strip()
                                                                 for x in its)[:400],
                                                  "f": f"{n} in all"}})
    # by season, newest first
    lab = {"league": "League Championship", "playoff": "Playoff title", "cup": "Cup", "mvp": "MVP",
           "pickup": "Best pickup", "roy": "Rookie of the Year", "trade": "Trade of the Year",
           "improved": "Most improved", "lineup": "Lineup manager", "draft": "Draft of the year",
           "waiver": "Waiver king", "bust": "Bust of the Year", "unlucky": "Unluckiest season"}
    by: Dict[str, list] = {}
    for k in TC.ORDER:
        for x in tc["items"][k]:
            s = x["season"]
            r = mine.get(s)
            what = x["what"]
            if k == "league" and r is not None:
                what = _rec3(r["w"], r["l"], r["t"]) + (f"{DOT}standings and brackets only" if r["kind"] == "pre" else "")
            elif k == "playoff" and r is not None:
                ru = next((o for o, v in srows[s].items() if v["po"] == "final"), None)
                what = (f"over {ru}" if ru else "") + (f"{DOT}standings and brackets only" if r["kind"] == "pre" else "")
            by.setdefault(s, []).append({"k": k, "t": lab[k], "what": what.strip(),
                                         "cls": "lc" if k == "league" else "po" if k == "playoff" else
                                         "apart" if k in TC.APART else ""})
    by_season = [{"s": s, "items": by[s]} for s in sorted(by, reverse=True)]
    # records he holds: his #1s, team records first, then his players'; the rest of his top-10 places counted
    rows, more = [], 0
    holder = {"biggest_blowout": lambda e: e.get("winner")}
    for key, label, group, val, _who in L.RECORD_BOOK:
        if key in NOT_HONOURS:
            continue
        top = rec_all.get(f"{key}_top10")
        if not isinstance(top, list) or not top:
            continue
        get = holder.get(key, lambda e: e.get("manager"))
        for i, e in enumerate(top):
            if get(e) != m:
                continue
            if i == 0:
                ctx = str(e.get("season") or "")
                if e.get("week") is not None:
                    ctx += f", week {int(e['week'])}"
                p = e.get("player_name")
                team = group in TEAM_GROUPS
                p = None if team else p                  # a team record is his own, not a player's
                rows.append({"label": label, "team": team, "v": val(e),
                             "ctx": (f"{p}{DOT}" if p else "") + ctx, "card": L._slug(p) if p else None,
                             "player": p or ""})
            else:
                more += 1
    rows.sort(key=lambda r: not r["team"])
    # money: each finished season's nets, both pots (modules/money)
    mrows, total, tot_r, tot_p = [], 0, 0, 0
    for s in sorted(money["nets"], reverse=True):
        v = money["nets"][s].get(m)
        if v is None:
            raise ManagerError(f"money {s}: no net for {m}")
        r = mine[s]
        reg_t = f"Regular season: {_dollars(v['regular'])} ({_ord(r['finish'])})"
        if v["playoffs"] is None:
            po_t = f"Playoffs: no playoff pot ({money['no_bracket'].get(s, 'no bracket')})"
        else:
            po_t = f"Playoffs: {_dollars(v['playoffs'])} ({ {'won': 'Playoff Champion', 'final': 'runner-up', 'semi': 'semifinal'}[r['po']] })"
        net = v["regular"] + (v["playoffs"] or 0)
        total += net
        tot_r += v["regular"]
        tot_p += v["playoffs"] or 0
        mrows.append({"s": s, "reg": reg_t, "po": po_t, "net": _dollars(net)})
    money_v = {"total": _dollars(total), "reg": _dollars(tot_r), "po": _dollars(tot_p), "rows": mrows,
               "note": ("Every finished season, both pots: $150 and $75 through 2025-26 (everyone but the winner "
                        "paid in full), $180 and $90 from 2026-27 (2nd and the playoff runner-up break even). "
                        "This season shows once a pot is decided. The Cup carries no money.")}
    return {"case": case, "by_season": by_season,
            "records": {"rows": rows, "more": (f"and {more} other top-10 place" + ("" if more == 1 else "s"))
                        if more else "no other top-10 place",
                        "note": ("His #1s in the record book (team records first, then his players' for him); "
                                 "low marks and the closest game are not counted.")},
            "money": money_v,
            "note": ("Finished seasons. League Championships: first in the regular season; Playoff titles: the "
                     "bracket; the Cup from 2026-27. Bust and Unluckiest are kept apart, not honours. Tap a count "
                     "for its seasons.")}


def _dollars(v: int) -> str:
    from ..money import dollars
    return dollars(v)


# =============================================================================
# the extra inputs (the real run)
# =============================================================================

def manager_inputs(base, *, schedule: dict) -> dict:
    """What the card reads beyond league.gather's inputs: the basketball-
    reference age cache (read only: never fetched here), this season's adds
    per manager (transaction_rulings.adds_by_budget_week, the one counter),
    the league config (money)."""
    from .. import transaction_rulings as tr
    from ..data_loader import _LEAGUE_CONFIG
    base = Path(base)
    p = base / "data" / "historical" / "BBREF_AGES.json"
    ages = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"seasons": {}}
    counts = tr.adds_by_budget_week(base, schedule)
    adds: Dict[str, int] = {}
    for _w, by in counts.items():
        for m, names in by.items():
            adds[m] = adds.get(m, 0) + len(names)
    return {"bbref_ages": ages, "adds_now": adds, "config": _LEAGUE_CONFIG}


def build_soft(inp: dict, base=None, extra: Optional[dict] = None) -> dict:
    """build(), softly: {"order", "cards"} or {"error": "..."} (the run row
    names it; the hub's names stay plain)."""
    try:
        if extra is None:
            from ..transaction_rulings import _schedule
            b = base or inp.get("base") or "."
            extra = manager_inputs(b, schedule=_schedule(b))
        from .. import money as MO
        MO.check_engine_payouts(inp["season"], extra.get("config"))
        return build(inp, L.week_results(inp), extra)
    except Exception as e:                       # noqa: BLE001 -- the card fails softly
        return {"error": f"{type(e).__name__}: {e}".splitlines()[0][:400], "order": [], "cards": {}}
