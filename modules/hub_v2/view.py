"""
hub_v2/view.py -- the view model: the payload (with payload["v2"]) arranged
into the new hub's screens, for page.py to print.

WHAT HAPPENS HERE: joins (a roster index to its row, a manager to his slot),
routes and ids, and chart geometry -- the one arithmetic the brief allows:
scaling a mark to its number (a sparkline point, a line chart's vertices, a
bar's width). No number is made here that the page prints: every printed
number is a payload string, carried through as is (tests/test_hub_v2.py
checks every number in the rendered page against the payload).

Charts are drawn with the design's classes (lh-chart, lh-c-*, lh-t-<slot>),
never a colour: the team colour comes from the slot class (decision: emit
series and draw with the classes, rather than restyle hub_charts' geometry,
whose hex strokes, 340-wide frame and five-tick axes are the current page's).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

TABS = [("home", "Home"), ("matchups", "Matchups"), ("teams", "Teams"), ("players", "Players"),
        ("market", "Market"), ("league", "League")]
PLACEHOLDER = "Coming in the new hub."
# preview only: where each placeholder's content lives on the current page
CURRENT_LINKS = {
    "league": [("v-chart", "Title odds over the season"), ("v-main", "The newsletter archive")],
}

# chart frames (viewBox units; the design's 356-wide phone chart)
W, H = 356, 190
X0, X1 = 36, 272            # the plot; end labels ("GC 1,612 exp.") to the right of X1
Y0, Y1 = 12, 160
SPARK_W, SPARK_H, SPARK_PAD = 64, 24, 3


class ViewError(RuntimeError):
    pass


def _f(x: float) -> str:
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def team_cls(slot: str) -> str:
    return f"lh-t-{slot}"


# =============================================================================
# geometry
# =============================================================================

def spark(values: List[float], vmax: float) -> dict:
    """A 64x24 sparkline: the polyline's points and its end dot, on the shared
    scale 0..vmax."""
    n = len(values)
    xs = [SPARK_PAD + (SPARK_W - 2 * SPARK_PAD) * (i / (n - 1) if n > 1 else 1.0) for i in range(n)]
    ys = [SPARK_H - SPARK_PAD - (SPARK_H - 2 * SPARK_PAD) * (v / vmax) for v in values]
    return {"points": " ".join(f"{_f(x)},{_f(y)}" for x, y in zip(xs, ys)),
            "cx": _f(xs[-1]), "cy": _f(ys[-1]), "w": str(SPARK_W), "h": str(SPARK_H)}


def _strips(xs: List[float]) -> List[tuple]:
    """Tap strips: each point owns the plot from the midpoint with the one
    before to the midpoint with the one after."""
    out = []
    for i, x in enumerate(xs):
        lo = X0 if i == 0 else (xs[i - 1] + x) / 2
        hi = X1 if i == len(xs) - 1 else (x + xs[i + 1]) / 2
        if hi - lo < 1:
            hi = lo + 1
        out.append((lo, hi))
    return out


def _spread(ys: List[float], gap: float = 12.0) -> List[float]:
    """Two end labels moved apart to at least `gap`."""
    if len(ys) == 2 and abs(ys[0] - ys[1]) < gap:
        mid = (ys[0] + ys[1]) / 2
        lo, hi = (0, 1) if ys[0] <= ys[1] else (1, 0)
        out = list(ys)
        out[lo], out[hi] = mid - gap / 2, mid + gap / 2
        return out
    return list(ys)


def win_chart(win: dict, a: str, b: str, teams: dict) -> dict:
    """Team a's win chance through the week (b's is its mirror), 0-100% with
    the 50% reference, end labels for both, hollow markers where the engine
    recorded a cause, and one tap strip per point."""
    def Y(v):
        return Y1 - (Y1 - Y0) * v / 100.0
    pts = win["points"]
    xs = [X0 + (X1 - X0) * p["x"] for p in pts]
    ys = [Y(p["a"]) for p in pts]
    grid = [{"cls": "lh-c-grid", "x1": _f(X0), "y1": _f(Y(100)), "x2": _f(X1), "y2": _f(Y(100))},
            {"cls": "lh-c-ref", "x1": _f(X0), "y1": _f(Y(50)), "x2": _f(X1), "y2": _f(Y(50))},
            {"cls": "lh-c-base", "x1": _f(X0), "y1": _f(Y(0)), "x2": _f(X1), "y2": _f(Y(0))}]
    ylab = [{"x": _f(X0 - 4), "y": _f(Y(t["v"]) + 3), "t": t["t"], "anchor": "end"} for t in win["yticks"]]
    xlab = [{"x": _f(X0 + (X1 - X0) * t["x"]), "y": _f(Y1 + 16), "t": t["t"], "anchor": "middle"}
            for t in win["ticks"]]
    out = {"vb": f"0 0 {W} {H}", "aria": win["aria"], "grid": grid, "labels": ylab + xlab, "lines": [],
           "events": [], "ends": [], "hits": [], "empty": win["empty"], "dot": None}
    if not pts:
        return out
    out["lines"].append({"cls": team_cls(teams[a]["slot"]), "points": " ".join(f"{_f(x)},{_f(y)}"
                                                                               for x, y in zip(xs, ys)),
                         "proj": False})
    # 4c2 (HUB_PREVIEW_NOTES s.1): no event text on the chart. Each event is a
    # small hollow dot, up or down, and a tap (a 44-px circle) opens the
    # tooltip: the time, the event, the swing -- the engine's strings
    for i, p in enumerate(pts):
        if not p["event"]:
            continue
        tip = p.get("tip") or {"h": p["when"], "b": p["event"], "f": ""}
        out["events"].append({"cx": _f(xs[i]), "cy": _f(ys[i]), "dir": p.get("dir") or "down", "tip": tip,
                              "label": " \u00b7 ".join(x for x in (tip["h"], tip["b"], tip.get("f", "")) if x)})
    last = pts[-1]
    ya, yb = _spread([Y(last["a"]), Y(last["b"])])
    out["ends"] = [{"cls": team_cls(teams[a]["slot"]), "x": _f(xs[-1] + 6), "y": _f(ya + 4),
                    "t": f"{teams[a]['mono']} {last['ta']}"},
                   {"cls": team_cls(teams[b]["slot"]), "x": _f(xs[-1] + 6), "y": _f(yb + 4),
                    "t": f"{teams[b]['mono']} {last['tb']}"}]
    out["dot"] = {"cls": team_cls(teams[a]["slot"]), "cx": _f(xs[-1]), "cy": _f(ys[-1])}
    for (lo, hi), p, x, y in zip(_strips(xs), pts, xs, ys):
        head = p["when"] + (f" \u00b7 {p['cause']}" if p["cause"] else "")
        body = f"{teams[a]['team']} {p['ta']}, {teams[b]['team']} {p['tb']}"
        out["hits"].append({"x": _f(lo), "y": _f(Y0 - 6), "w": _f(hi - lo), "h": _f(Y1 - Y0 + 12),
                            "cx": _f(x), "cy": _f(y), "head": head, "body": body,
                            "label": f"{head}: {body}"})
    out["readout0"] = {"head": "Tap a point to see what changed.", "body": ""}
    return out


def flow_chart(flow: dict, a: str, b: str, teams: dict) -> dict:
    """Points added up by day: banked solid, expected dashed (the same pricing
    run), cumulative from 0, three y labels, end labels in the team colours."""
    n = flow["n_days"]

    def X(i):
        return X0 + (X1 - X0) * i / n

    def Y(v):
        return Y1 - (Y1 - Y0) * v / flow["ymax"]
    grid = [{"cls": "lh-c-grid", "x1": _f(X0), "y1": _f(Y(t["v"])), "x2": _f(X1), "y2": _f(Y(t["v"]))}
            for t in flow["yticks"][1:]]
    grid.append({"cls": "lh-c-base", "x1": _f(X0), "y1": _f(Y(0)), "x2": _f(X1), "y2": _f(Y(0))})
    ylab = [{"x": _f(X0 - 4), "y": _f(Y(t["v"]) + 3), "t": t["t"], "anchor": "end"} for t in flow["yticks"]]
    xlab = [{"x": _f(X(t["i"] + 0.5)), "y": _f(Y1 + 16), "t": t["t"], "anchor": "middle"} for t in flow["ticks"]]
    lines, ends_y, ends = [], [], []
    for m in (a, b):
        s = flow["series"][m]
        cls = team_cls(teams[m]["slot"])
        bk = [(X(i), Y(v)) for i, v in enumerate(s["banked"])]
        lines.append({"cls": cls, "points": " ".join(f"{_f(x)},{_f(y)}" for x, y in bk), "proj": False})
        if s["exp"]:
            nb = len(s["banked"]) - 1
            ex = [(X(nb + i), Y(v)) for i, v in enumerate(s["exp"])]
            lines.append({"cls": cls, "points": " ".join(f"{_f(x)},{_f(y)}" for x, y in ex), "proj": True})
            ends_y.append(ex[-1][1])
        else:
            ends_y.append(bk[-1][1])
    ys = _spread(ends_y)
    end_x = X(n)
    for m, y in zip((a, b), ys):
        s = flow["series"][m]
        ends.append({"cls": team_cls(teams[m]["slot"]), "x": _f(end_x + 6), "y": _f(y + 4), "t": s["label"]})
    xs = [X(i + 1) for i in range(n)]
    hits = []
    for i, ((lo, hi), tip) in enumerate(zip(_strips_days(n, X), flow["tips"])):
        hits.append({"x": _f(lo), "y": _f(Y0 - 6), "w": _f(hi - lo), "h": _f(Y1 - Y0 + 12),
                     "cx": _f(xs[i]), "cy": "", "head": tip.split(": ")[0], "body": tip.split(": ", 1)[1]
                     if ": " in tip else "", "label": tip})
    return {"vb": f"0 0 {W} {H}", "aria": flow["aria"], "grid": grid, "labels": ylab + xlab, "lines": lines,
            "events": [], "ends": ends, "hits": hits, "empty": "", "dot": None,
            "readout0": {"head": "Tap a day for its points.", "body": ""}}


def _strips_days(n: int, X) -> List[tuple]:
    return [(X(i), X(i + 1)) for i in range(n)]


# =============================================================================
# the view model
# =============================================================================

def build(payload: dict, *, mode: str, now: datetime, archive_href: str = "hub_archive/",
          pictures: dict = None) -> dict:
    from ..hub_page import age_words, STALE_HOURS, STALE_TEXT
    if mode not in ("preview", "publish"):
        raise ViewError(f"mode {mode!r}")
    v2 = payload.get("v2")
    if v2 is None:
        err = payload.get("v2_error")
        raise ViewError("the payload has no new-hub keys (payload v2): "
                        + (f"the run recorded {err['stage']}: {err['error']}" if err else
                           "it was built before 4b; rebuild it (python scripts/build_hub_state.py)"))
    if "ratings" not in v2:
        raise ViewError("the payload's new-hub keys predate 4c1 (no Players tab): rebuild it with this "
                        "engine (python scripts/build_hub_state.py)")
    if "players" not in v2:
        raise ViewError("the new hub's Players rows are not attached: they live in their own file since 4c2 "
                        "(output/hub_players.json; hub_v2.data.attach_players)")
    if "roster_cols" not in v2 or "last" not in v2:
        raise ViewError("the payload's new-hub keys predate 4c2 (no roster columns): rebuild it with this "
                        "engine (python scripts/build_hub_state.py)")
    h = payload["header"]
    gen = datetime.fromisoformat(payload["generated_at"])
    words, stale = age_words(gen, now)
    teams_v2 = v2["teams"]
    order = v2["team_order"]
    # 4c3: pictures {manager: data URI} (team_pictures.data_uris, given by the page's builder):
    # a team with one shows it in its TeamMark, over the monogram
    pictures = pictures or {}
    teams = {m: {"cls": team_cls(t["slot"]), "slot": t["slot"], "mono": t["mono"], "team": t["team"],
                 "manager": m, "href": f"#/teams/{m}", "pic": m in pictures} for m, t in teams_v2.items()}
    rosters = payload["rosters"]
    power = {r["manager"]: r for r in payload["power"]["rows"]}
    scale = v2["spark_scale"]

    def player(m, i):
        p = rosters[m]["players"][i]
        return p

    # ------------------------------------------------------------------ matchups
    cards = payload["matchups"]["cards"]
    views = {v["id"]: v for v in payload["matchup_views"]}
    mus = []
    for c, mv in zip(cards, v2["matchups"]):
        a, b = mv["a"], mv["b"]
        sides = []
        for s, m in (("a", a), ("b", b)):
            x = c[s]
            sides.append({"m": m, "team": teams[m], "name": x["team"], "manager": m,
                          "record": power[m]["record"], "now": x["now"], "proj": x["proj"], "win": x["win"],
                          "fav": mv["fav"] == s})
        missing = [{"team": teams[r["m"]], "name": player(r["m"], r["i"])["name"],
                    "card": player(r["m"], r["i"]).get("card"), "chip": r["chip"], "sub": r["sub"]}
                   for r in mv["missing"]]
        sv = views[mv["views"]["sum"]]
        mus.append({
            "id": mv["id"], "route": f"matchups/{mv['id']}", "href": f"#/matchups/{mv['id']}",
            "sides": sides, "bar_a": c["bar_a"],
            "bar_aria": f"Win chance: {c['a']['team']} {c['a']['win']}, {c['b']['team']} {c['b']['win']}",
            "spread": c["spread"], "total": c["total"], "moneyline": c["moneyline"],
            "note": mv["note"], "note_src": mv["note_src"], "clock": payload["matchups"]["clock"],
            "title": f"{c['a']['team']} vs {c['b']['team']}", "sub": sv["sub"],
            "paras": sv["paras"],
            "starts": {"days": mv["starts"]["days"], "note": mv["starts"]["note"],
                       "rows": [{"team": teams[r["m"]], "total": r["total"], "cells": r["cells"]}
                                for r in mv["starts"]["rows"]]},
            "missing": missing,
            "win": win_chart(mv["win"], a, b, teams),
            "flow": flow_chart(mv["flow"], a, b, teams),
            "lines": mv["lines"]})

    # ------------------------------------------------------------------ teams
    team_pages = []
    for m in order:
        t, tv = teams[m], teams_v2[m]
        rb = rosters[m]
        sp = spark(tv["spark"]["values"], scale["max"])
        ex = tv["roster"]["extra"]
        rows = []
        for i, p in enumerate(rb["players"]):
            chips = [{"text": x["text"], "kind": x["kind"]} for x in p["tags"] if x["kind"] in ("out", "q", "il")]
            notes = [x["text"] for x in p["tags"] if x["kind"] not in ("out", "q", "il")]
            rows.append({"i": i, "name": p["name"], "card": p.get("card"), "meta": f"{p['pos']} \u00b7 {p['nba']}",
                         "chips": chips, "notes": notes, "in_il": p["in_il"],
                         "cells": {"fppg": p["fppg"], "gp": ex[i]["gp"], "proj": p["proj"], "next": ex[i]["next"],
                                   "l14": p["l14"], "gl": p["gl"], "keep": p["keep"]}})
        orders = dict(rb["orders"])
        orders.update(tv["roster"]["orders"])
        default = rb["default_order"]
        det = tv["roster"]["detail"]
        rc = v2["roster_cols"]
        for k in rc["keys"]:
            orders["d_" + k] = det["orders"][k]
        for i, r in enumerate(rows):
            vals = det["rows"][i]
            cells = []
            for k, txt in zip(rc["keys"], vals):
                c = {"k": k, "t": txt}
                if k == "ovr" and det["ovr_d"][i]:
                    c["d"] = det["ovr_d"][i]
                if k == "trend" and det["trend"][i]:
                    c["spark"] = spark(det["trend"][i]["values"], det["trend_max"])
                    c["aria"] = det["trend"][i]["aria"]
                cells.append(c)
            r["dcells"] = cells
        active = [rows[i] for i in orders[default] if not rows[i]["in_il"]]
        il = [rows[i] for i in orders[default] if rows[i]["in_il"]]
        keepers = [{"rank": tv["roster"]["keep_rank"][i], "name": rows[i]["name"], "card": rows[i]["card"],
                    "keep": rows[i]["cells"]["keep"], "w": tv["roster"]["keep_w"][i], "meta": rows[i]["meta"]}
                   for i in tv["roster"]["keepers"]]
        keep_all = [{"rank": tv["roster"]["keep_rank"][i], "name": rows[i]["name"], "card": rows[i]["card"],
                     "keep": rows[i]["cells"]["keep"], "w": tv["roster"]["keep_w"][i], "meta": rows[i]["meta"],
                     "in_il": rows[i]["in_il"]} for i in orders["keep"]]
        sched = [{"name": rows[r["i"]]["name"], "card": rows[r["i"]]["card"], "in_il": rows[r["i"]]["in_il"],
                  "cells": r["cells"]} for r in tv["schedule"]["rows"]]
        mweeks = {w["key"]: w for w in payload["moves"]["weeks"]}
        moves = []
        for ref in tv["moves"]:
            w = mweeks[ref["w"]]
            it = w["items"][ref["j"]]
            moves.append({"week": w["label"], "day": it["day"], "date": it["date"], "time": it["time"],
                          "who": it["who"], "parts": it["parts"], "state": it["state"], "note": it["note"]})
        kpi = tv["kpi"]
        team_pages.append({
            "m": m, "team": t, "route": f"teams/{m}", "sub": tv["sub"], "kpi": kpi, "spark": sp,
            "spark_aria": tv["spark"]["aria"], "record": tv["record"], "odds": tv["odds"],
            "adds_left": tv["adds_left"], "injured": tv["injured"],
            "roster": {"active": active, "il": il, "orders": orders, "default": default,
                       "groups": rc["groups"], "cols": rc["cols"], "keys": rc["keys"],
                       "gs": {k: [g["key"] for g in rc["groups"] if k in g["cols"]] for k in rc["keys"]},
                       "why": rc["why"], "notes": rc["notes"]},
            "keepers": keepers, "keep_line": tv["roster"]["keep_line"], "keep_all": keep_all,
            "sched": sched, "moves": moves, "note": rb["note"], "size": rb["size"],
            "pending": [j["text"] for j in rb["pending"]]})

    # ------------------------------------------------------------------ home extras
    ranking = []
    for m in order:
        r = power[m]
        sp = spark(teams_v2[m]["spark"]["values"], scale["max"])
        ranking.append({"rank": r["rank"], "team": teams[m], "record": r["record"], "pf": r["pf"],
                        "odds": r["odds"], "delta": r["delta"], "dir": r["delta_dir"], "spark": sp,
                        "aria": teams_v2[m]["spark"]["aria"]})
    trade = []
    for c in payload["trade_block"]["cards"]:
        trade.append({"team": teams[c["manager"]], "mode": c["mode"]["text"], "since": c["mode_since"],
                      "lists": [{"label": lst["label"],
                                 "players": [{"name": r["name"], "card": r.get("card")} for r in lst["rows"]]}
                                for lst in c["lists"]],
                      "empty": c["empty"]})
    last = None
    if v2["last"] is not None:
        lw = v2["last"]
        lcards = []
        for c in lw["cards"]:
            a, b = c["a"], c["b"]
            sv = views[c["views"]["sum"]]
            sides = [{"m": m, "team": teams[m], "name": teams[m]["team"], "manager": m, "score": sc,
                      "win": w, "won": c["won"] == s}
                     for s, m, sc, w in (("a", a, c["score_a"], c["win_a"]), ("b", b, c["score_b"], c["win_b"]))]
            lcards.append({"id": c["id"], "route": f"matchups/{c['id']}", "href": f"#/matchups/{c['id']}",
                           "sides": sides, "result": c["result"], "line": c["line"], "verdict": c["verdict"],
                           "bar_a": c["win_a"],
                           "bar_aria": f"Final: {teams[a]['team']} {c['score_a']}, {teams[b]['team']} {c['score_b']}",
                           "title": f"{teams[a]['team']} vs {teams[b]['team']}", "sub": sv["sub"],
                           "paras": sv["paras"], "win": win_chart(c["win"], a, b, teams),
                           "flow": flow_chart(c["flow"], a, b, teams)})
        last = {"title": lw["title"], "note": lw["note"], "cards": lcards}
    grid3 = {"cols": v2["grid3"]["cols"], "note": v2["grid3"]["note"],
             "rows": [{"team": teams[r["m"]], "cells": r["cells"]} for r in v2["grid3"]["rows"]]}

    # ------------------------------------------------------------------ the issue bar
    iss = v2["issue"]
    issue = None
    if iss is not None:
        if mode == "publish":
            attr = ("data-issue", iss["file"])
        else:
            attr = ("data-href", archive_href + iss["file"].replace(".enc", ".html"))
        issue = {"text": iss["text"], "attr": attr}

    placeholders = []                                 # every tab is built (4c4: League, the last)

    return {
        "mode": mode, "title": h["title"], "epoch": int(payload["generated_epoch_ms"]),
        "stale_hours": STALE_HOURS, "age": words, "stale": stale,
        "stale_text": STALE_TEXT % payload["generated_text"], "generated_text": payload["generated_text"],
        "mismatch": h.get("engine_mismatch"), "engine_note": h.get("engine_note"),
        "closing_note": h.get("closing_note"),
        "week_label": h["week_label"], "lock": h["lock"]["text"], "issue": issue,
        "line_text": v2["line_text"], "last": last,
        "tabs": [{"key": k, "label": lab, "href": f"#/{k}"} for k, lab in TABS],
        "matchups": mus, "clock": payload["matchups"]["clock"], "ranking": ranking,
        "rank_meta": f"{payload['power']['label']} \u00b7 by week", "spark_note": scale["note"],
        "teams": [teams[m] for m in order], "team_pages": team_pages, "trade": trade,
        "trade_foot": payload["trade_block"]["foot"], "grid3": grid3,
        "sched_cols": v2["sched_cols"], "sched_note": v2["sched_note"],
        "placeholders": placeholders, "odds_label": payload["power"]["label"],
        "players": players(payload, teams),
        "market": market(payload, teams),
        "league": dict(league(payload, teams, mode, archive_href),
                       history=league_history(payload, teams) if "league_history" in v2 else None),
        "pictures": [{"slot": teams_v2[m]["slot"], "uri": uri} for m, uri in sorted(pictures.items())
                     if m in teams_v2],
        "footer": (f"Engine {payload['engine']['key']} \u00b7 actual points through "
                   f"{payload['sources']['actuals_through']}")}


# =============================================================================
# Market (4c3)
# =============================================================================

def market(payload: dict, teams: dict) -> dict:
    """The Market tab from payload v2 market (modules/hub_v2/market.py):
    joins only -- a manager to his team (class, colour slot, route), a card
    key to its route when the card exists. Every printed value is a payload
    string."""
    import json as _json
    mk = payload["v2"].get("market")
    if mk is None:
        raise ViewError("the payload has no v2 market (built before 4c3): rebuild it with this engine "
                        "(python scripts/build_hub_state.py)")
    reg = (payload.get("cards") or {}).get("players") or {}

    def href(key):
        return f"#/players/{key}" if key and key in reg else ""

    def who(p):
        return dict(p, href=href(p.get("card")))
    a = mk["available"]
    av = dict(a, rows=[dict(r, href=href(r["card"])) for r in a["rows"]],
              orders_json=_json.dumps(a["orders"], separators=(",", ":")),
              default_rows=list(a["orders"][a["default"]]))
    st = dict(mk["stash"], rows=[dict(r, href=href(r["card"])) for r in mk["stash"]["rows"]])
    bl = {"foot": mk["block"]["foot"],
          "cards": [dict(c, team=teams[c["m"]],
                         lists=[{"label": lst["label"], "players": [who(p) for p in lst["players"]]}
                                for lst in c["lists"]]) for c in mk["block"]["cards"]]}
    mv = dict(mk["moves"], teams=[teams[m] for m in mk["moves"]["teams"]],
              items=[dict(it, teams=[teams[m] for m in it["ms"]],
                          parts=[dict(p, segs=[dict(x, href=href(x.get("card"))) for x in p["segs"]])
                                 for p in it["parts"]]) for it in mk["moves"]["items"]])
    adv = None
    if mk["advice"] is not None:
        a2 = mk["advice"]
        cards = []
        for c in a2["cards"]:
            rows = [dict(r, adds=[who(p) for p in r["adds"]], lines=[who(x) for x in r["lines"]],
                         also=[teams[o["m"]] for o in r["also"]]) for r in c["rows"]]
            bk = c["backup"]
            if bk is not None:
                bk = dict(bk, add=who(bk["add"]), lines=[who(x) for x in bk["lines"]])
            cards.append(dict(c, team=teams[c["m"]], rows=rows, backup=bk))
        adv = dict(a2, cards=cards)
    return {"segs": mk["segs"], "available": av, "stash": st, "advice": adv, "block": bl, "moves": mv}


# =============================================================================
# Players, the player card and Compare (4c1)
# =============================================================================

def players(payload: dict, teams: dict) -> dict:
    """The Players screen, Compare's data and the pick list, from payload v2
    players (modules/hub_v2/players.py). Joins only: a row's team class, its
    card's route, the filters' labels. Every printed value is a payload string;
    Compare's winners are decided in the page from the integer order keys."""
    import json as _json
    v2 = payload["v2"]
    pl = v2["players"]
    rt = v2["ratings"]
    reg = (payload.get("cards") or {}).get("players") or {}
    rows = []
    for i, z in enumerate(pl["rows"]):
        key = z["key"] if z["key"] and z["key"] in reg else None
        slot = z["chip"]["slot"]
        rows.append({"i": i, "key": key, "name": z["name"], "href": f"#/players/{key}" if key else "",
                     "chip": {"text": z["chip"]["text"], "cls": team_cls(slot) if slot else "",
                              "team": z["chip"]["team"], "m": z["m"]},
                     "meta": z["meta"], "ovr": z["ovr"], "ovr_d": z["ovr_d"], "pot": z["pot"], "fppg": z["fppg"],
                     "next": z["next"], "chips": z["chips"], "kind": z["kind"],
                     "data": {"q": z["q"], "k": z["f"]["k"], "pos": " ".join(z["f"]["pos"]), "nba": z["f"]["nba"],
                              "age": z["f"]["age"], "h": z["f"]["h"]}})
    risers = None
    if pl["risers"] is not None:
        risers = [{"name": rows[r["i"]]["name"], "key": rows[r["i"]]["key"], "reason": r["reason"],
                   "ovr": r["ovr"], "d": r["d"]} for r in pl["risers"]]
    cmp = {"labels": [r["label"] for r in pl["cmp_rows"]], "rows": {}}
    for z, r in zip(pl["rows"], rows):
        if r["key"] is None:
            continue
        cmp["rows"][r["key"]] = {"name": z["name"], "team": z["chip"]["team"], "chip": z["chip"]["text"],
                                 "cls": r["chip"]["cls"], "ovr": z["ovr"], "ring": (z["ring"] or {}).get("cmp") or "",
                                 "ini": z["ini"], "cmp": z["cmp"], "fa": z["kind"] == "fa",
                                 "arch": (z.get("arch") or {}).get("label") or "",
                                 "arch_preview": bool((z.get("arch") or {}).get("preview"))}
    f = pl["filters"]
    return {"rows": rows, "rows_default": [rows[i] for i in pl["orders"][pl["default"]]["d"]],
            "orders": pl["orders"], "orders_json": _json.dumps(pl["orders"], separators=(",", ":")),
            "default": pl["default"], "count": pl["count"], "who": pl["who"], "risers": risers,
            "filters": {"pos": [{"v": x, "t": x} for x in f["pos"]], "nba": [{"v": x, "t": x} for x in f["nba"]],
                        "age": [{"v": a["key"], "t": a["label"]} for a in f["age"]]},
            "error": rt["error"], "as_of": rt["as_of"], "change_note": rt["change_note"], "fa_note": rt["fa_note"],
            "preview_arch": bool(rt.get("preview")),
            "cmp_json": _json.dumps(cmp, separators=(",", ":"), ensure_ascii=True),
            "pick": [r for r in rows if r["key"]]}


# =============================================================================
# League (4c4)
# =============================================================================

def _spread_n(ys: List[float], gap: float = 12.0, lo: float = Y0, hi: float = Y1 - 2) -> List[float]:
    """End labels moved apart to at least `gap`, in their order, kept inside
    [lo, hi] (layout only: the labels' own strings are the engine's)."""
    idx = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = [ys[i] for i in idx]
    for k in range(1, len(pos)):
        if pos[k] - pos[k - 1] < gap:
            pos[k] = pos[k - 1] + gap
    over = pos[-1] - hi if pos else 0
    if over > 0:
        pos = [p - over for p in pos]
        for k in range(len(pos) - 2, -1, -1):
            if pos[k + 1] - pos[k] < gap:
                pos[k] = pos[k + 1] - gap
    if pos and pos[0] < lo - gap:
        pos = [p + (lo - gap - pos[0]) for p in pos]
    out = [0.0] * len(ys)
    for k, i in enumerate(idx):
        out[i] = pos[k]
    return out


def title_chart(c: dict, teams: dict, order: list) -> dict:
    """The title-odds lines (one per manager, his slot class), 0-100% with the
    50% reference, direct end labels, a hollow marker per engine event (its
    words in the tooltip only), and one tap strip per run."""
    def Y(v):
        return Y1 - (Y1 - Y0) * v / 100.0
    pts = c["points"]
    xs = [X0 + (X1 - X0) * p["x"] for p in pts]
    grid = []
    for t in c["yticks"]:
        cls = "lh-c-base" if t["v"] == 0 else "lh-c-ref" if t["v"] == 50 else "lh-c-grid"
        grid.append({"cls": cls, "x1": _f(X0), "y1": _f(Y(t["v"])), "x2": _f(X1), "y2": _f(Y(t["v"]))})
    ylab = [{"x": _f(X0 - 4), "y": _f(Y(t["v"]) + 3), "t": t["t"], "anchor": "end"} for t in c["yticks"]]
    # a week tick too close to the right edge would run into the end labels: left out (layout only)
    xlab = [{"x": _f(X0 + (X1 - X0) * t["x"]), "y": _f(Y1 + 16), "t": t["t"], "anchor": "start"} for t in c["ticks"]
            if X0 + (X1 - X0) * t["x"] <= X1 - 16]
    out = {"vb": f"0 0 {W} {H}", "aria": c["aria"], "grid": grid, "labels": ylab + xlab, "lines": [],
           "events": [], "ends": [], "hits": [], "empty": c["empty"], "dot": None,
           "readout0": {"head": "Tap a point for its run.", "body": ""}}
    if not pts:
        return out
    for m in order:
        out["lines"].append({"cls": team_cls(teams[m]["slot"]),
                             "points": " ".join(f"{_f(x)},{_f(Y(p['vals'][m]))}" for x, p in zip(xs, pts)),
                             "proj": False})
    for e in c["events"]:
        i, m = e["i"], e["m"]
        tip = e["tip"]
        out["events"].append({"cx": _f(xs[i]), "cy": _f(Y(pts[i]["vals"][m])), "dir": e["dir"], "tip": tip,
                              "label": " \u00b7 ".join(x for x in (tip["h"], tip["b"], tip.get("f", "")) if x)})
    last = pts[-1]
    ys = _spread_n([Y(last["vals"][m]) for m in order])
    out["ends"] = [{"cls": team_cls(teams[m]["slot"]), "x": _f(xs[-1] + 6), "y": _f(y + 4),
                    "t": f"{teams[m]['mono']} {last['texts'][m]}"} for m, y in zip(order, ys)]
    for (lo, hi), p, x in zip(_strips(xs), pts, xs):
        out["hits"].append({"x": _f(lo), "y": _f(Y0 - 6), "w": _f(hi - lo), "h": _f(Y1 - Y0 + 12),
                            "cx": _f(x), "cy": "", "head": p["head"], "body": p["body"],
                            "label": f"{p['head']}: {p['body']}"})
    return out


def race_chart(c: dict, teams: dict) -> dict:
    """An awards race (4c5): today's top 5's running measure by finished week,
    one line per player in his team's colour (a gap where he was outside a
    week's stored top 10), y from the engine's ticks, direct end labels, one
    tap strip per week (the readout: the week and every value). Layout only:
    every printed string is the engine's."""
    n = len(c["weeks"])
    lo, hi = float(c["ymin"]), float(c["ymax"])

    def Y(v):
        return Y1 - (Y1 - Y0) * (float(v) - lo) / ((hi - lo) or 1.0)
    xs = [X0 + (X1 - X0) * t["x"] for t in c["ticks"]]
    grid = [{"cls": "lh-c-base" if t["v"] == lo else "lh-c-grid", "x1": _f(X0), "y1": _f(Y(t["v"])), "x2": _f(X1),
             "y2": _f(Y(t["v"]))} for t in c["yticks"]]
    ylab = [{"x": _f(X0 - 4), "y": _f(Y(t["v"]) + 3), "t": t["t"], "anchor": "end"} for t in c["yticks"]]
    xlab = [{"x": _f(x), "y": _f(Y1 + 16), "t": t["t"], "anchor": "middle" if 0 < i < n - 1 else
             ("start" if i == 0 else "end")} for i, (x, t) in enumerate(zip(xs, c["ticks"]))]
    out = {"vb": f"0 0 {W} {H}", "aria": c["aria"], "grid": grid, "labels": ylab + xlab, "lines": [],
           "events": [], "ends": [], "hits": [], "empty": "", "dot": None,
           "readout0": {"head": "Tap a week for its values.", "body": ""}}
    ends = []
    for sr in c["series"]:
        cls = team_cls(teams[sr["m"]]["slot"])
        run = []
        for x, v in zip(xs, sr["vals"]):
            if v is None:
                if run:
                    out["lines"].append({"cls": cls, "points": " ".join(run), "proj": False})
                run = []
                continue
            run.append(f"{_f(x)},{_f(Y(v))}")
        if run:
            out["lines"].append({"cls": cls, "points": " ".join(run), "proj": False})
        last = max(i for i, v in enumerate(sr["vals"]) if v is not None)
        ends.append((cls, xs[last], Y(sr["vals"][last]), sr["end"]))
    ys = _spread_n([e[2] for e in ends])
    out["ends"] = [{"cls": cls, "x": _f(x + 6), "y": _f(y + 4), "t": t} for (cls, x, _y, t), y in zip(ends, ys)]
    for (a, b), pt, x in zip(_strips(xs), c["points"], xs):
        out["hits"].append({"x": _f(a), "y": _f(Y0 - 6), "w": _f(b - a), "h": _f(Y1 - Y0 + 12), "cx": _f(x),
                            "cy": "", "head": pt["head"], "body": pt["body"], "label": f"{pt['head']}: {pt['body']}"})
    return out


def awards_view(aw: dict, teams: dict, href, past: Optional[dict] = None) -> dict:
    """League > Awards (4c5): the races and Player of the Week with their
    joins (a manager to his team mark, a card key to its route) and each
    race chart's geometry. Every printed value is the engine's string.
    past (4c6): the side file's Past winners (v2.league_history.awards_past),
    joined into each award's card."""
    races = []
    for a in aw.get("races") or []:
        rows = [dict(r, team=teams.get(r["m"]), href=href(r["card"]) if r.get("card") else "",
                     sides=[dict(sd, team=teams.get(sd["m"]),
                                 players=[dict(x, href=href(x["card"])) for x in sd["players"]])
                            for sd in r.get("sides") or []])
                for r in a["rows"]]
        odds = a.get("odds")
        if odds:                                     # 4c6: MVP's odds block, its others and its chart
            odds = dict(odds, others=[dict(o, team=teams.get(o["m"]), href=href(o["card"]))
                                      for o in odds.get("others") or []],
                        geom=race_chart(odds["chart"], teams) if odds.get("chart") else None)
        pa = ((past or {}).get("by_award") or {}).get(a["key"])
        if pa:                                       # 4c6: Past winners, with their team marks
            pa = dict(pa, rows=[dict(r, team=teams.get(r["m"]) if r["m"] else None,
                                     href=href(r["card"]) if r["card"] else "") for r in pa["rows"]])
        races.append(dict(a, rows=rows, odds=odds, past=pa,
                          geom=race_chart(a["chart"], teams) if a.get("chart") else None))
    potw = [dict(s, rows=[dict(r, team=teams.get(r["m"]), href=href(r["card"])) for r in s["rows"]])
            for s in aw["potw"]]
    return dict(aw, races=races, potw=potw, past=past or {})


def league(payload: dict, teams: dict, mode: str, archive_href: str) -> dict:
    """The League tab from payload v2.league (modules/hub_v2/league.py): joins
    (a manager to his team mark, a card key to its route, an issue to how it
    opens) and the title chart's geometry. Every printed value is a payload
    string. The History chips' content is league_history(), built from the
    side file (v2.league_history) and, in publish mode, loaded on tap."""
    v2 = payload["v2"]
    lg = v2.get("league")
    if lg is None:
        raise ViewError("the payload has no v2 league (built before 4c4): rebuild it with this engine "
                        "(python scripts/build_hub_state.py)")
    reg = (payload.get("cards") or {}).get("players") or {}
    order = v2["team_order"]

    def href(key):
        return f"#/players/{key}" if key and key in reg else ""
    st = dict(lg["standings"], rows=[dict(r, team=teams[r["m"]]) for r in lg["standings"]["rows"]])
    pw = dict(lg["power"], weeks=[dict(w, rows=[dict(r, team=teams[r["m"]]) for r in w["rows"]])
                                  for w in lg["power"]["weeks"]])
    aw = awards_view(lg["awards"], teams, href, past=(v2.get("league_history") or {}).get("awards_past"))
    issues = []
    for i in lg["archive"]["issues"]:
        attr = ("data-issue", i["file"]) if mode == "publish" else ("data-href", archive_href + i["plain"])
        issues.append(dict(i, attr=attr))
    return {"segs": lg["segs"], "standings": st, "chart": title_chart(lg["chart"], teams, order),
            "chart_note": lg["chart"]["note"], "power": pw, "awards": aw,
            "archive": dict(lg["archive"], issues=issues), "chips": lg["chips"], "history": None, "parts": None}


def league_history(payload: dict, teams: dict) -> dict:
    """History's six chips from v2.league_history (the side file, put back by
    data.attach_players): joins only."""
    v2 = payload["v2"]
    h = v2.get("league_history")
    if h is None:
        raise ViewError("the new hub's League history is not attached: it lives in the side file "
                        "(output/hub_players.json; hub_v2.data.attach_players)")
    reg = (payload.get("cards") or {}).get("players") or {}

    def href(key):
        return f"#/players/{key}" if key and key in reg else ""
    ch = dict(h["champions"], rows=[dict(r, team=teams.get(r["m"]) if r["m"] else None)
                                    for r in h["champions"]["rows"]])
    at = dict(h["alltime"], rows=[dict(r, team=teams[r["m"]]) for r in h["alltime"]["rows"]])
    hh = h["h2h"]
    grid = {ph: [dict(r, team=teams[r["m"]]) for r in rows] for ph, rows in hh["grid"].items()}
    h2 = dict(hh, cols=[teams[m] for m in hh["order"]], grid=grid,
              pairs={k: dict(v, ta=teams[v["a"]], tb=teams[v["b"]]) for k, v in hh["pairs"].items()})
    rc = dict(h["records"], groups=[dict(g, lists=[dict(lst, rows=[dict(r, href=href(r["card"]))
                                                                       for r in lst["rows"]])
                                                   for lst in g["lists"]]) for g in h["records"]["groups"]])
    dr = dict(h["draft"], seasons=[dict(s, rows=[dict(r, team=teams.get(r["m"]), href=href(r["card"]))
                                                 for r in s["rows"]]) for s in h["draft"]["seasons"]])
    tr = dict(h["trades"], items=[dict(it, teams=[teams[m] for m in it["ms"]],
                                       sides=[dict(sd, team=teams[sd["m"]],
                                                   gets=[dict(g, href=href(g["card"])) for g in sd["gets"]])
                                              for sd in it["sides"]]) for it in h["trades"]["items"]])
    return {"chips": h["chips"], "champions": ch, "alltime": at, "h2h": h2, "records": rc, "draft": dr,
            "trades": tr}
