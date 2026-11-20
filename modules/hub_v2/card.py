"""
hub_v2/card.py -- ENGINE SIDE of the new player card (4c1; the brief's s.6,
round 2's hybrid; claude/HANDOFF_4C1_PLAYERS_2026-11-18.md s.3).

ONE CARD BUILDER STAYS THE RULE. The new card shows the SAME data the current
card does -- hub_cards.build's card for the player (player_card_builder,
from the same run's data) -- plus the ratings (payload v2 players, from
modules/ratings), in the new design. Nothing here re-derives a figure the
card builder made: it formats the card's numbers into strings, checks the
ones the Players row also shows are equal (FPPG, GP, age), and lays out the
charts. The old card's archetype (player_card_builder.classify_archetype,
card["archetype"]) is NEVER read: only the ratings' archetype appears, and
only when enabled (or in a --archetype-preview build, marked).

    view(card, row, ctx) -> {"key", "hero", "season", "career", "keeper",
                             "history"}: strings, plus percentage strings for
                             the bars (the engine scales them)
4a3: the Season tab's minutes line (MIN and MIN delta, the Players row's
strings) and the last-5 table's MIN (the row's min_g: a game's minutes as
soon as its day has them; "loading" before; a dash on an injured day).

The page (page.card_html) prints it; the card's file is encrypted by its
content (publish.py), as hub_cards' are, and fetched on the tap.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Optional

from .players import tiles

MINUS = "\u2212"
DASH = "\u2014"
UP, DOWN = "\u25b2", "\u25bc"
LAST_N = 5
# the line charts' frame (viewBox units; the design's 356-wide phone chart)
W, H = 356, 160
X0, X1, Y0, Y1 = 36, 300, 12, 128
AGE_LO, AGE_HI = 20, 37
# 4c2 (4c1 decision 9): past this many games the game-by-game BarChart becomes
# a line. At 40 a bar is about 5 px wide in the 356-px phone chart with the
# design's 4 px gaps, and its tap column about 9 px; past it the bars blur into
# a comb and a line reads better (about mid-December for an everyday player)
BAR_MAX_GAMES = 40


class CardError(RuntimeError):
    """A card input is missing or disagrees with the Players row; named."""


def _f(x: float) -> str:
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def _signed1(x: float) -> str:
    return f"+{x:.1f}" if x > 0 else (f"{MINUS}{abs(x):.1f}" if x < 0 else "0.0")


def _day(iso: str) -> str:
    d = date.fromisoformat(str(iso)[:10])
    return f"{d:%a} {d.month:02d}-{d.day:02d}"


def _delta(d: float, unit: str) -> dict:
    if d > 0:
        return {"t": f"{UP} {abs(d):.1f} {unit}", "dir": "up"}
    if d < 0:
        return {"t": f"{DOWN} {abs(d):.1f} {unit}", "dir": "down"}
    return {"t": f"No change {unit}", "dir": ""}


def bars(games: list, fppg: Optional[float], cur_last10: list) -> dict:
    """The BarChart (fantasy points by game, this season): each bar's height
    as a share of the plot's top (the engine's scaling), its tap text, the
    average line's height, and the axis texts (first day, best game, last
    day). games: this season's {date, fp, injured}, in order."""
    opp = {g["date"]: g.get("opponent") or "" for g in cur_last10}
    if not games:
        return {"bars": [], "avg": None, "axis": [], "aria": "No games this season yet."}
    if len(games) > BAR_MAX_GAMES:
        return game_line(games, fppg, opp)
    top = max([g["fp"] for g in games] + [fppg or 0.0, 1.0])
    top = 10.0 * math.ceil(top / 10.0)
    out = []
    for g in games:
        o = opp.get(g["date"], "")
        when = _day(g["date"]) + (f" vs {o}" if o and not o.startswith("@") else f" at {o[1:]}" if o else "")
        if g["injured"]:
            out.append({"h": "0%", "inj": True, "label": f"{when}: injured, no game"})
            continue
        d = g["fp"] - (fppg or 0.0)
        tail = "" if fppg is None else f" ({_signed1(d)} vs his average)"
        out.append({"h": f"{100.0 * max(g['fp'], 0.0) / top:.1f}%", "inj": False,
                    "label": f"{when}: {g['fp']:.1f}{tail}"})
    played = [g for g in games if not g["injured"]]
    best = max(played, key=lambda g: (g["fp"], g["date"])) if played else None
    axis = [_day(games[0]["date"])]
    if best is not None:
        axis.append(f"Best {best['fp']:.1f} ({_day(best['date'])})")
    axis.append(_day(games[-1]["date"]))
    avg = None if fppg is None else {"y": f"{100.0 * fppg / top:.1f}%", "t": f"avg {fppg:.1f}"}
    aria = (f"Fantasy points in each of his {len(played)} games this season"
            + (f", averaging {fppg:.1f}" if fppg is not None else "")
            + (f"; best {best['fp']:.1f}." if best else "."))
    return {"bars": out, "avg": avg, "axis": axis, "aria": aria}


def game_line(games: list, fppg: Optional[float], opp: dict) -> dict:
    """Past BAR_MAX_GAMES: fantasy points by game as a LineChart (the games he
    played, in order; a game he missed injured is left out, as no point), his
    average as the dashed reference line, a tap strip per game. The same
    "bars" dict shape, with "line" set and no bars."""
    played = [g for g in games if not g["injured"]]
    pts = []
    for g in played:
        o = opp.get(g["date"], "")
        when = _day(g["date"]) + (f" vs {o}" if o and not o.startswith("@") else f" at {o[1:]}" if o else "")
        tail = "" if fppg is None else f" ({_signed1(g['fp'] - fppg)} vs his average)"
        pts.append((_day(g["date"]), g["fp"], f"{when}: {g['fp']:.1f}{tail}"))
    best = max(played, key=lambda g: (g["fp"], g["date"])) if played else None
    aria = (f"Fantasy points in each of his {len(played)} games this season"
            + (f", averaging {fppg:.1f}" if fppg is not None else "")
            + (f"; best {best['fp']:.1f}." if best else "."))
    ch = line(pts, lambda v: f"{v:.0f}", aria, ref=None if fppg is None else (fppg, f"avg {fppg:.1f}"))
    axis = [_day(games[0]["date"])] + ([f"Best {best['fp']:.1f} ({_day(best['date'])})"] if best else []) \
        + [_day(games[-1]["date"])]
    return {"bars": [], "line": ch, "avg": None, "axis": axis, "aria": aria}


def line(points: list, ylab, aria: str, mark: Optional[int] = None, ref: Optional[tuple] = None) -> dict:
    """A small LineChart: points [(x label, value, tap text)], 0 to the next
    10 above the top, three y labels, a tap strip per point. mark: the index
    to draw as the end dot (default: the last). ref: (value, label) drawn as
    a dashed reference line with its label (the game line's average)."""
    if not points:
        return {"vb": f"0 0 {W} {H}", "aria": aria, "points": "", "grid": [], "labels": [], "hits": [],
                "dot": None, "empty": "No seasons yet."}
    vals = [v for _x, v, _t in points]
    lo = min(0.0, 10.0 * math.floor(min(vals) / 10.0))
    hi = 10.0 * math.ceil(max(vals + [lo + 1.0]) / 10.0)
    if hi <= lo:
        hi = lo + 10.0
    n = len(points)

    def X(i):
        return X0 + (X1 - X0) * (i / (n - 1) if n > 1 else 0.5)

    def Y(v):
        return Y1 - (Y1 - Y0) * (v - lo) / (hi - lo)
    xs = [X(i) for i in range(n)]
    ys = [Y(v) for v in vals]
    mid = (lo + hi) / 2
    grid = [{"cls": "lh-c-grid", "x1": _f(X0), "y1": _f(Y(hi)), "x2": _f(X1), "y2": _f(Y(hi))},
            {"cls": "lh-c-grid", "x1": _f(X0), "y1": _f(Y(mid)), "x2": _f(X1), "y2": _f(Y(mid))},
            {"cls": "lh-c-base", "x1": _f(X0), "y1": _f(Y(lo)), "x2": _f(X1), "y2": _f(Y(lo))}]
    labels = [{"x": _f(X0 - 4), "y": _f(Y(v) + 3), "t": ylab(v), "anchor": "end"} for v in (lo, mid, hi)]
    if ref is not None:
        grid.append({"cls": "lh-c-ref", "x1": _f(X0), "y1": _f(Y(ref[0])), "x2": _f(X1), "y2": _f(Y(ref[0]))})
        labels.append({"x": _f(X1 + 4), "y": _f(Y(ref[0]) + 3), "t": ref[1], "anchor": "start"})
    labels += [{"x": _f(xs[0]), "y": _f(Y1 + 16), "t": points[0][0], "anchor": "start" if n > 1 else "middle"}]
    if n > 1:
        labels.append({"x": _f(xs[-1]), "y": _f(Y1 + 16), "t": points[-1][0], "anchor": "end"})
    hits = []
    for i in range(n):
        a = X0 if i == 0 else (xs[i - 1] + xs[i]) / 2
        b = X1 if i == n - 1 else (xs[i] + xs[i + 1]) / 2
        hits.append({"x": _f(a), "y": _f(Y0 - 6), "w": _f(max(b - a, 1.0)), "h": _f(Y1 - Y0 + 12),
                     "cx": _f(xs[i]), "cy": _f(ys[i]), "head": points[i][0], "body": points[i][2],
                     "label": f"{points[i][0]}: {points[i][2]}"})
    k = n - 1 if mark is None else mark
    return {"vb": f"0 0 {W} {H}", "aria": aria, "points": " ".join(f"{_f(x)},{_f(y)}" for x, y in zip(xs, ys)),
            "grid": grid, "labels": labels, "hits": hits, "dot": {"cx": _f(xs[k]), "cy": _f(ys[k])}, "empty": ""}


def age_curve(age, curve: dict) -> dict:
    """The Keeper tab's age curve: this league's expected change in scoring
    from one season to the next, by age (ratings.age_multiplier, the curve POT
    uses), his age marked."""
    from ..ratings import age_multiplier
    pts = []
    for a in range(AGE_LO, AGE_HI + 1):
        ch = 100.0 * (age_multiplier(a, curve) - 1.0)
        pts.append((str(a), ch, f"at {a}: {_signed1(ch)}% next season"))
    mark = None
    text = "No age on record: no place on the curve."
    if age is not None:
        a = int(age)
        if AGE_LO <= a <= AGE_HI:
            mark = a - AGE_LO
        ch = 100.0 * (age_multiplier(a, curve) - 1.0)
        text = f"At {a}, this league's age curve expects {_signed1(ch)}% scoring next season."
    ch = line(pts, lambda v: f"{_signed1(v)}%", "This league's age curve: the expected change in a player's "
              "scoring from one season to the next, by age" + (f", with him at {int(age)}" if age is not None else ""),
              mark=mark)
    if mark is None:
        ch["dot"] = None
    return {"chart": ch, "text": text}


def view(card: dict, row: dict, ctx: dict) -> dict:
    """The new card's strings for one player. card: hub_cards.build's card
    (every season's games: the preview's, or the published card with its
    history re-joined); row: his v2 Players row; ctx: {"season": the current
    season key, "curve": ratings' age curve, "team_size": {manager: n}}."""
    name = card["player_name"]
    if name != row["name"]:
        raise CardError(f"card {card.get('card')}: the card is {name}, the Players row {row['name']}")
    cs = card.get("current_season")
    fppg = None if cs is None else float(cs["fppg"])
    fppg_t = DASH if fppg is None else f"{fppg:.1f}"
    if fppg_t != row["fppg"]:
        raise CardError(f"{name}: the card's FPPG is {fppg_t}, the Players row's {row['fppg']} (one FPPG everywhere)")
    gp_t = "0" if cs is None else str(int(cs["gp"]))
    if cs is not None and gp_t != row["gp"]:
        raise CardError(f"{name}: the card's GP is {gp_t}, the Players row's {row['gp']}")
    age = card.get("age")
    age_t = DASH if age is None else str(age)
    if age_t != row["age"]:
        raise CardError(f"{name}: the card's age is {age_t}, the Players row's {row['age']}")
    rostered = row["kind"] == "rostered"

    # ---------------------------------------------------------------- hero
    bio = " \u00b7 ".join(x for x in (card.get("positions") or row["pos"] or "", card.get("nba_team") or "",
                                       f"Age {age_t}" if age is not None else "") if x)
    notes = [c["text"] for c in card.get("status") or [] if c.get("kind") == "new"]
    hero = {"name": name, "bio": bio, "ini": row["ini"], "chip": row["chip"], "m": row["m"],
            "chips": row["chips"], "healthy": row["healthy"], "notes": notes,
            "ovr": row["ovr"], "ovr_d": (row["ovr_d"] or {}).get("long", ""),
            "ovr_dir": (row["ovr_d"] or {}).get("dir", ""), "ring": (row["ring"] or {}).get("hero"),
            "pot": row["pot"], "pot_d": (row["pot_d"] or {}).get("long", ""),
            "pot_dir": (row["pot_d"] or {}).get("dir", ""),
            "ovr_note": row["ovr_note"], "arch": row.get("arch")}

    # ---------------------------------------------------------------- season
    comps = card.get("season_comps") or {}
    if fppg is None:
        k_fppg = {"label": "FPPG", "value": DASH, "ctx": card.get("season_note") or "No games this season yet",
                  "dir": ""}
    elif comps.get("previous_fppg") is not None:
        d = _delta(fppg - float(comps["previous_fppg"]), f"vs last season ({float(comps['previous_fppg']):.1f})")
        k_fppg = {"label": "FPPG", "value": fppg_t, "ctx": d["t"], "dir": d["dir"]}
    else:
        k_fppg = {"label": "FPPG", "value": fppg_t, "ctx": "No earlier season in the league log", "dir": ""}
    k_gp = {"label": "Games", "value": gp_t,
            "ctx": f"of {row['team_gp']} team games" if row["team_gp"] != DASH else "No NBA team on record",
            "dir": ""}
    k_tot = {"label": "Total FP", "value": DASH if cs is None else f"{float(cs['total_fp']):,.0f}",
             "ctx": row["total_rank"] or "No games this season yet", "dir": ""}
    k_l14 = {"label": "Last 14", "value": row["l14"], "ctx": row.get("l14_ctx") or "No games in the last 14 days",
             "dir": row.get("l14_dir") or ""}
    games = [g for g in card.get("sparkline") or [] if g.get("season") == ctx["season"]]
    games.sort(key=lambda g: g["date"])
    bar = bars(games, fppg, card.get("last_10") or [])
    last = []
    min_g = row.get("min_g") or {}
    for g in (card.get("last_10") or [])[:LAST_N]:
        o = g.get("opponent") or ""
        iso = str(g["date"])[:10]
        last.append({"day": _day(g["date"]), "opp": o or DASH,
                     "fp": "INJ" if g.get("injured") else f"{float(g['fp']):.1f}",
                     "min": DASH if g.get("injured") else min_g.get(iso, "loading")})
    if row["min_k"] is None and row["min"] == DASH:
        minutes = ""                                   # no games: the tiles say so
    elif row["min_k"] is None:
        minutes = f"MIN {row['min']} \u00b7 MIN \u0394 {row['mind']}"
    else:
        minutes = f"MIN {row['min']} a game this season \u00b7 MIN \u0394 {row['mind']}"
    keep = {"text": card.get("keep_text") or ("Free agents have no keep chance." if not rostered else DASH)}
    season = {"kpis": [k_fppg, k_gp, k_tot, k_l14],
              "league": (card.get("league_season") or {}).get("text") or "",
              "grades": tiles(row["grades"]), "bars": bar, "keep": keep, "last": last, "minutes": minutes}

    # ---------------------------------------------------------------- career
    car = card.get("career") or {}
    crows = []
    pts = []
    for s in car.get("season_breakdown") or []:
        crows.append({"season": s["season"], "gp": str(int(s["gp"])), "fppg": f"{float(s['fppg']):.1f}",
                      "total": f"{float(s['total_fp']):,.0f}", "who": ", ".join(s.get("managers") or []) or DASH})
        pts.append((s["season"], float(s["fppg"]), f"{float(s['fppg']):.1f} FPPG in {int(s['gp'])} games"))
    career = {"rows": crows,
              "total": ({"gp": str(int(car["career_gp"])), "fppg": f"{float(car['career_fppg']):.1f}",
                         "total": f"{float(car['career_fp']):,.0f}",
                         "seasons": f"{int(car['seasons_played'])} season" + ("s" if int(car["seasons_played"]) != 1 else "")}
                        if crows else None),
              "chart": line(pts, lambda v: f"{v:.0f}", f"His FPPG in each season in the league"
                            + (f", {pts[0][0]} to {pts[-1][0]}" if pts else "")),
              "note": "Seasons on a league roster (this season: every NBA game)." if crows else
                      "He has not been on a league roster before."}

    # ---------------------------------------------------------------- keeper
    if rostered:
        kp = card.get("keep_k5_pct") or DASH
        keeper = {"keep": kp, "keep_ctx": card.get("keep_text") or "",
                  "rank": f"{row['keep_rank']} of {ctx['team_size'].get(row['m'], DASH)} on {row['chip']['team']}"
                  if row["keep_rank"] else DASH,
                  "pot": row["pot"], "pot_d": hero["pot_d"], "pot_dir": hero["pot_dir"]}
    else:
        keeper = {"keep": DASH, "keep_ctx": "Free agents have no keep chance.", "rank": DASH,
                  "pot": DASH, "pot_d": "", "pot_dir": ""}
    keeper["curve"] = age_curve(age, ctx["curve"])

    # ---------------------------------------------------------------- history
    own = []
    for t in card.get("ownership_timeline") or []:
        ev = ", ".join(f"{e['manager']} ({str(e.get('acquired_via') or '').replace('_', ' ')})".replace(" ()", "")
                       for e in t.get("events") or [])
        own.append({"season": t["season"], "text": ev or DASH})
    drafts = []
    for d in card.get("draft_history") or []:
        bits = [f"Round {d['round']}, pick {d['pick_number']}" if d.get("round") else f"Pick {d['pick_number']}",
                d["manager"]]
        if d.get("is_keeper"):
            bits.append("kept")
        if d.get("roi_label"):
            bits.append(f"{d['roi_label']} ({_signed1(float(d['roi']))} FPPG vs the slot)")
        drafts.append({"season": d["season"], "text": " \u00b7 ".join(bits)})
    trades = []
    for t in card.get("trade_history") or []:
        back = ", ".join(t.get("received_back") or [])
        trades.append({"season": t["season"], "text": f"{t['from_manager']} \u2192 {t['to_manager']}"
                       + (f" ({t['date']})" if t.get("date") else "") + (f", for {back}" if back else "")})
    records = []
    for r in card.get("record_book") or []:
        v = r.get("value")
        vt = DASH if v is None else (f"{float(v):,.1f}" if not float(v).is_integer() else f"{float(v):,.0f}")
        records.append({"record": r["record"], "rank": f"#{r['rank']}", "value": vt,
                        "detail": str(r.get("detail") or r.get("season") or "").replace(" | ", " \u00b7 ")})
    history = {"own": own, "drafts": drafts, "trades": trades, "records": records}
    return {"key": card.get("card") or row["key"], "hero": hero, "season": season, "career": career,
            "keeper": keeper, "history": history}


def views(payload: dict, cards_obj: dict) -> dict:
    """{card key: view} for every player in payload v2's Players list that
    has a card (hub_cards.build's output for the same payload)."""
    from ..data_loader import CURRENT_SEASON
    from ..ratings import config as rcfg
    v2 = payload["v2"]
    rows = {z["key"]: z for z in v2["players"]["rows"] if z["key"]}
    missing = sorted(set(rows) - set(cards_obj["cards"]))
    if missing:
        raise CardError(f"no card built for {missing[:5]}")
    ctx = {"season": CURRENT_SEASON, "curve": rcfg()["pot"]["age_curve"],
           "team_size": {m: str(len(rb["players"])) for m, rb in payload["rosters"].items()}}
    return {k: view(cards_obj["cards"][k], rows[k], ctx) for k in sorted(rows)}
