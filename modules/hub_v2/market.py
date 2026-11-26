"""
hub_v2/market.py -- payload["v2"]["market"], the new hub's Market tab (4c3,
claude/HANDOFF_4C3_MARKET_ADVICE_2026-11-18.md s.1-s.2; the approved mockups
design/league-hub/mockups/Market.html and Advice.html v5).

Segments, in the Advice mockup's order: Available . Stash . Advice . Block .
Moves. Advice is there only while league_config advice.hub is "on".

THE ENGINE COMPUTES. Every string the tab prints is made here (or is already
in the payload, or in output/advice_latest.json's strings); the page prints
them and reorders rows by the integer orders carried here. Built inside
hub_state.build after the Players rows (each name's card key and FPPG/L14 come
from v2.players, the one place they live), from the same run's inputs: the
free-agent rows the current page lists (hub_state.rank_free_agents), their
availability (the grid's own Availability.for_free_agents: each game cell's
tooltip lists the days its count counts), the stash rows, the trade block
view, the season's moves (hub_moves) and the advice file.

    market = {
      "segs": [[key, label]],                        the segments, in order
      "available": {"title", "meta", "note", "aside", "cols": [label],
                    "rows": [{"name", "card", "sub", "chips", "fppg", "l14", "proj", "pts",
                              "games": [{"n", "b", "tip"}], "h": "1"|"", "pos": "SF PF"}],
                    "orders": {"l14" | "fppg" | "pts": [row index, best first]},
                    "default": "l14", "pos": [position], "empty"},
      "stash":     {"rows": [{"name", "card", "sub", "proj", "chips"}], "aside", "open_il", "note", "empty"},
      "advice":    None (switched off) | {"intro", "cards": [...], "foot", "error", "empty"},
      "block":     {"cards": [{"m", "stance", "since", "lists": [{"label", "players": [{name, card}]}],
                               "empty"}], "foot"},
      "moves":     {"items": [{"ms": [manager], "when", "time", "week", "marker", "mkind",
                               "head", "parts": [{"marker", "kind", "segs"}], "note", "state"}],
                    "teams": [manager], "empty"},
    }

"What they want" is not shown anywhere (4b decision 6): the trade block's
two lists are On the block and Untouchable, with the team's stance.

THE ADVICE VIEW (Advice.html v5, ADVICE_VIEW_DESIGN_2026-11-18): one card per
team in the page's team order: the header ("Wk 6 vs <team> . Wk 7 vs
<team>", "N adds left"); the activation row first when there is one (priced
against doing nothing, 4c3 s.2.2: advice_v2.price_activation); then each
step ("+ add" over "- drop", the flag when another team's plan adds him,
"Wk 6 +x%" over "Wk 7 +y%"); each row opens to its reason, three tiles
(Starts, Points, Title odds while advice.show_title_odds) and "Also wanted
by"; the plan line when there are two rows or more (the activation counts);
the backup; or the one-sentence state. The strings are advice_live's
(text.v2 / texts.v2 / plan_total.v2 / v2_empty); a file from before 4c3
(no v2 strings) gets the same strings from its numbers through the same
functions (advice_live.v2_texts), and an activation with no numbers shows
dashes, never an invented number.

H54: when advice keeps a returner in IL this week (il_choice "hold"), the
activation row's variant takes its place: the same shading, bar and win-%
columns, the label "Keep in IL this week . no moves", the returner in bold,
a plain sub-line "activate at week N's window" (nobody is dropped this
window, so no red minus) and its numbers AGAINST ACTIVATING NOW (hold.texts.v2;
the tap-open sentence says so). No step, no plan line and no backup follow
(a hold blocks every move); with no adds left the card ends "No adds left.
Resets Monday." as an activation's does. Otherwise nothing in the view changes.

FAILS SOFTLY like the rest of v2 (data.market_soft): a failure leaves v2 out
and says why; nothing is defaulted.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

MINUS = "\u2212"
DASH = "\u2014"
SWAP = "\u21c4"
DOT = " \u00b7 "
POSITIONS = ("PG", "SG", "SF", "PF", "C")
INTRO = ("Best moves for Monday\u2019s window, in order, with how much each one changes your chance to win "
         "this week and next. \u2691: another team wants him too. Tap a move for why.")
IL_LABEL = "Activate from IL \u00b7 no add"
HOLD_LABEL = "Keep in IL this week \u00b7 no moves"


def intro(weeks: list) -> str:
    """5e (Nick's 11-22 screenshot): the intro names the weeks its columns
    price ("weeks 6 and 7"), never "this week and next" (on a Sunday the
    columns are next week and the one after)."""
    ws = [str(w) for w in weeks if w is not None]
    when = ("week " + ws[0]) if len(ws) == 1 else ("weeks " + " and ".join(ws)) if ws else "the coming weeks"
    return (f"Best moves for Monday\u2019s window, in order, with how much each one changes your chance to "
            f"win {when}. \u2691: another team wants him too. Tap a move for why.")          # H54: the hold row (CSS upper-cases it)


class MarketError(RuntimeError):
    pass


def _num(s: str) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").replace(MINUS, "-"))
    except (TypeError, ValueError):
        return None


def order_desc(values: list, names: list) -> list:
    """Row indexes, highest value first, a missing value last, ties by name."""
    return sorted(range(len(values)), key=lambda i: (values[i] is None, -(values[i] or 0.0), names[i]))


# =============================================================================
# Available
# =============================================================================

def available(free: dict, fa_av, col_specs: list, prow: dict) -> dict:
    """The free-agent table: the payload's own rows (hub_state: the top
    free_agents_top_n by projected points over the three columns, plus every
    player dropped in the chat), each a player the hub has a card for.
    col_specs: per column {"w", "label", "sub", "days", "long"}; prow: {name:
    the Players row} (FPPG, L14, card key)."""
    from .data import player_week_tip, bucket, WEEK_GAME_EDGES
    rows = []
    for r in free["rows"]:
        z = prow.get(r["name"])
        if z is None:
            raise MarketError(f"free agent {r['name']} has no Players row")
        games = []
        for i, c in enumerate(col_specs):
            n = r[f"g{i + 1}"]
            if c["w"] is None or n == DASH:
                games.append({"n": DASH, "b": 0, "tip": None})
                continue
            cnt, tip = player_week_tip(fa_av, r["name"], c["w"], c["sub"], c["days"], c["long"])
            if str(cnt) != str(n):
                raise MarketError(f"{r['name']}: {n} games in the free-agent table, {cnt} in its tooltip's days")
            games.append({"n": str(n), "b": bucket(int(n), WEEK_GAME_EDGES), "tip": tip})
        pos = [p for p in str(r["pos"]).replace(" ", "").split(",") if p]
        rows.append({"name": r["name"], "card": r.get("card") or z.get("key") or "", "sub": f"{r['pos']}{DOT}{r['nba']}",
                     "chips": list(r.get("tags") or []), "fppg": z["fppg"], "l14": z["l14"], "proj": r["proj"],
                     "pts": r["pts"], "games": games, "h": "" if r.get("tags") else "1", "pos": " ".join(pos)})
    names = [r["name"] for r in rows]
    orders = {"l14": order_desc([_num(r["l14"]) for r in rows], names),
              "fppg": order_desc([_num(r["fppg"]) for r in rows], names),
              "pts": list(range(len(rows)))}                      # the ranking itself
    weeks = [c["label"] for c in col_specs]
    return {"title": "Best available", "meta": "games: " + DOT.join(weeks), "aside": free["aside"],
            "cols": weeks, "rows": rows, "orders": orders, "default": "l14", "pos": list(POSITIONS),
            "note": ("Tap a game count for the days. FPPG and L14 are actual points per game (L14: the last "
                     "14 days); the games count only games he will play. Each range lists its own best free "
                     "agents (the range's note says how). Healthy: no status tag."),
            "empty": free["empty"] if not rows else ""}


# =============================================================================
# 5d2 s.4: the ranges (item 14)
# =============================================================================

# the sorts beside Pts and Games, each a column too (item 14), from the
# Players groups' cells (one string everywhere: hub_v2/pcols.py); LOW: lower
# is better
RANGE_SORTS = (("pts", "Proj pts"), ("total", "Games"), ("fppg", "FPPG"), ("l14", "L14"), ("l7", "L7"),
               ("l30", "L30"), ("ovr", "OVR"), ("pot", "POT"), ("dur", "DUR"), ("mind", "MIN \u0394"),
               ("avail", "Avail %"), ("age", "Age"))
RANGE_TEXT = (("status", "Status"),)
LOW_SORTS = {"age"}
ROS_GAME_EDGES = (15, 25, 35)                 # 5e: Rest of season's one total column, bucketed for its shade
DEFAULT_RANGE = "next3"


def range_tables(payload: dict, ctx: dict) -> dict:
    """{"list": [{"key", "label", "sub"}], "default", "avail": {key: table},
    "stash": {key: [row]}}: the free agents of Available (the same list for
    every range: the range re-sorts it and counts its games) and the Stash,
    over each of the seven ranges still ahead (hub_v2.ranges: the same days
    as Players and Team > Schedule). Each range's games are counted per
    fantasy week (week 7's column says 14 days), then summed; Proj pts =
    Yahoo's projected FPPG x those games (rank_free_agents' rule)."""
    from .data import player_week_tip, bucket, WEEK_GAME_EDGES
    from .pcols import _orders
    rl = ctx.get("range_list") or []
    if not rl:                                    # the season's last window has closed: no range is ahead
        return {"list": [], "default": None, "avail": {}, "stash": {},
                "sorts": [{"k": k, "label": lab} for k, lab in RANGE_SORTS]}
    fa_av, proj, src = ctx["fa_av"], ctx["proj"], ctx.get("ranges")
    wk = {int(w): list(v) for w, v in ctx["wk_dates"].items()}
    pl = payload["v2"]["players"]
    names_all = [z["name"] for z in pl["rows"]]
    pos_of = {n: i for i, n in enumerate(names_all)}
    gcells = (pl.get("groups") or {}).get("cells")
    if gcells is None:
        raise MarketError("the Players groups are missing: Market's sorts read their cells (one source)")
    fa_all = {r["name"]: r for r in payload["free_agents"]["rows"] + (payload["free_agents"].get("range_rows") or [])}
    own = payload["free_agents"].get("ranges")
    if own is None:
        raise MarketError("the free agents carry no per-range lists (hub_state.range_free_agents): a payload "
                          "from before 5e")
    out_av, out_st = {}, {}
    for r_ in rl:
        if r_.key not in own:
            raise MarketError(f"the free agents have no list for the range {r_.key}")
        free = [fa_all[n] for n in own[r_.key]]          # 5e: this range's own best (decision 2)
        weeks = []
        for w in r_.weeks:
            ds = [d for d in wk[w] if d in set(r_.days)]
            weeks.append({"w": w, "days": ds, "long": len(wk[w]) > 7,
                          "label": f"Wk {w}" + (f" \u00b7 {len(wk[w])} days" if len(wk[w]) > 7 else "")
                          + (" rest" if ds and ds[0] != wk[w][0] else "")})
        rows, keys = [], {k: [] for k, _l in RANGE_SORTS}
        vu_k = []
        # Team > Schedule's pickups link (fit=<manager>): his games on that team's empty-slot days
        fit_days = ({m: src.empty_days(m, list(r_.days)) for m in payload["v2"]["team_order"]}
                    if (r_.key == "next" and src is not None) else {})
        # 5e: "Plays on my light days" (the I'm... picker): his games on the days that team has 4 or
        # fewer players with a game (the day word, hub_v2.ranges' kind), every range; not the
        # empty-slot days fit= uses
        light_days = ({m: [d for d in r_.days if src.day(m, d).kind == "light"]
                       for m in payload["v2"]["team_order"]} if src is not None else {})
        fv = (payload["v2"].get("fa_value") or {}).get("values") or {}
        for r in free:
            n = r["name"]
            pj = proj.get(n)
            pjv = None if pj is None else pj.get("projectedFPPG")
            if pjv is None:
                raise MarketError(f"free agent {n} has no projectedFPPG")
            games, tot = [], 0
            for x in weeks:
                cnt, tip = player_week_tip(fa_av, n, x["w"], "rest" if x["label"].endswith("rest") else "",
                                           x["days"], x["long"])
                tot += cnt
                games.append({"n": str(cnt), "b": bucket(int(cnt), WEEK_GAME_EDGES), "tip": tip})
            pts = float(pjv) * tot
            i = pos_of.get(n)
            if i is None:
                raise MarketError(f"free agent {n} has no Players row")
            cells = {k: gcells[k][i] for k in ("fppg", "l14", "l7", "l30", "ovr", "pot", "dur", "mind", "avail",
                                                 "status")}
            cells["age"] = pl["rows"][i]["age"]
            cells["total"], cells["pts"] = str(tot), f"{pts:.1f}"
            fit = [m for m, ds in fit_days.items() if fa_av.playable(n, ds)]
            light = [m for m, ds in light_days.items() if ds and fa_av.playable(n, ds)]
            row = {"name": n, "cells": cells, "games": games, "fit": " ".join(fit), "light": " ".join(light),
                   "vu": {m: x["tv"] for m, x in fv[n].items()} if n in fv else None}
            vu_k.append({m: x["tv_k"] for m, x in fv[n].items()} if n in fv else None)
            if r_.key == "ros":                          # 5e (5D2 decision 8): totals, the weeks in a tap
                row["games"] = [{"n": str(tot), "b": bucket(int(tot), ROS_GAME_EDGES),
                                 "tip": {"h": f"{n}: {r_.label}", "b": DOT.join(
                                     f"{x['label']} {g['n']}" for x, g in zip(weeks, games)),
                                         "f": f"{tot} games {DOT.strip()} {pts:.1f} proj pts"}}]
            rows.append(row)
            keys["pts"].append(pts)
            keys["total"].append(tot)
            for k in ("fppg", "l14", "l7", "l30", "ovr", "pot", "dur", "mind", "avail", "age"):
                keys[k].append(_num(str(cells[k]).replace("%", "").replace("Prov.", "").strip()))
        nm = [x["name"] for x in rows]
        orders = {k: _orders(keys[k], nm, k in LOW_SORTS)["d"] for k in keys}
        for m in payload["v2"]["team_order"]:          # 5e: Value to you, each manager's own order
            orders[f"vtv@{m}"] = _orders([None if v is None else v.get(m) for v in vu_k], nm, False)["d"]
        ros = r_.key == "ros"
        out_av[r_.key] = {"weeks": ([{"label": f"Games {DOT.strip()} {len(weeks)} wks"}] if ros else
                                    [{"label": x["label"]} for x in weeks]), "rows": rows, "orders": orders,
                          "note": (f"{r_.label}: {r_.sub}. "
                                   + ("Games he will play over the whole range (tap a count for each week's); "
                                      if ros else "Games he will play in each fantasy week of the range ")
                                   + "(a week under way counts its days from today); Proj pts: Yahoo's projected "
                                   "FPPG times those games. Each range lists its own best free agents by "
                                   "projected points over its own days, so a late range can surface players "
                                   "the next weeks don't.")}
        st = []
        for r in payload["stash"]["rows"]:
            n = r["name"]
            pj = proj.get(n)
            pjv = float((pj or {}).get("projectedFPPG") or 0.0)
            g = sum(len(fa_av.playable(n, x["days"])) for x in weeks) if n in fa_av.info else None
            st.append({"name": n, "games": DASH if g is None else str(g),
                       "pts": DASH if g is None else f"{pjv * g:.1f}"})
        out_st[r_.key] = st
    keys_l = [r.key for r in rl]
    default = DEFAULT_RANGE if DEFAULT_RANGE in keys_l else (keys_l[0] if keys_l else None)
    return {"list": [{"key": r.key, "label": r.label, "sub": r.sub} for r in rl], "default": default,
            "avail": out_av, "stash": out_st,
            "sorts": [{"k": k, "label": lab} for k, lab in RANGE_SORTS]}


# =============================================================================
# Stash, Block, Moves
# =============================================================================

def stash(st: dict) -> dict:
    rows = [{"name": r["name"], "card": r.get("card") or "", "sub": f"{r['pos']}{DOT}{r['nba']}",
             "proj": r["proj"], "chips": list(r.get("tags") or []),
             "note": r.get("season_note") or ""} for r in st["rows"]]
    return {"rows": rows, "aside": st["aside"], "open_il": st["open_il"], "note": st["note"],
            "empty": st["empty"] if not rows else ""}


def block(tb: dict, order: list) -> dict:
    by = {c["manager"]: c for c in tb["cards"]}
    if set(by) != set(order):
        raise MarketError(f"the trade block's teams {sorted(by)} are not the league's {sorted(order)}")
    cards = []
    for m in order:
        c = by[m]
        lists = []
        for lst in c["lists"]:
            if lst.get("key") not in ("block", "untouchable"):
                raise MarketError(f"{m}'s trade block has a list {lst.get('key')!r}: only On the block and "
                                  "Untouchable are shown (4b decision 6)")
            lists.append({"label": lst["label"],
                          "players": [{"name": r["name"], "card": r.get("card") or "",
                                       "sub": f"{r['pos']}{DOT}{r['nba']}{DOT}{r['since']}"} for r in lst["rows"]]})
        cards.append({"m": m, "stance": c["mode"]["text"], "kind": c["mode"]["kind"], "since": c["mode_since"],
                      "lists": lists, "empty": c["empty"]})
    return {"cards": cards, "foot": tb["foot"]}


def _season_date(md: str, first: date) -> date:
    """"11/30" in the season that starts at `first` (Oct-Apr)."""
    mo, d = (int(x) for x in md.split("/"))
    y = first.year if mo >= first.month - 3 else first.year + 1
    return date(y, mo, d)


def _minutes(t: str) -> int:
    hm, ap = t.split(" ")
    h, mi = (int(x) for x in hm.split(":"))
    return (h % 12 + (12 if ap.upper() == "PM" else 0)) * 60 + mi


def moves(mv: dict, managers: list, first: date) -> dict:
    """Every move of the season (hub_moves), newest first, each with the
    managers it involves (a trade: both sides) for the team chips."""
    items, weeks = [], []
    for w in mv["weeks"]:
        # 5b (5a decision 7): each budget week's adds used, over the budget marked (the old hub's line)
        weeks.append({"key": str(w["key"]), "label": w["label"],
                      "used": None if w.get("used") is None else
                      [{"m": u["manager"], "text": u["text"], "over": bool(u["over"])} for u in w["used"]],
                      "note": w.get("used_note") or ""})
        for it in w["items"]:
            if it["kind"] == "trade":
                ms = [m for m in managers if any(p["text"].startswith(f"{m} gets ") for p in it["parts"])]
                head, marker, mk = "Trade", SWAP, "trade"
            else:
                ms = [it["who"]] if it["who"] in managers else []
                kinds = {p["kind"] for p in it["parts"]}
                marker, mk = (("+", "add") if "add" in kinds else (MINUS, "drop") if kinds == {"drop"}
                              else ("IL", "il"))
                head = it["who"]
            if not ms:
                raise MarketError(f"a move on {it['date']} ({it.get('what')}) names no manager of the league")
            d = _season_date(it["date"], first)
            items.append({"_k": (d, _minutes(it["time"])), "ms": ms, "when": f"{it['day']} {d:%m-%d}",
                          "time": it["time"], "week": w["label"], "wk": str(w["key"]), "marker": marker, "mkind": mk, "head": head,
                          "parts": [{"marker": p["marker"], "kind": p["kind"], "segs": p.get("segs") or [{"t": p["text"]}]}
                                    for p in it["parts"]],
                          "note": it.get("note") or "", "state": it.get("state") or ""})
    items.sort(key=lambda x: x["_k"], reverse=True)               # stable: the feed's own order breaks ties
    for x in items:
        del x["_k"]
    weeks.reverse()                                              # newest first, as the items
    return {"items": items, "teams": list(managers), "weeks": weeks,
            "empty": "No moves yet this season." if not items else "",
            "note": "Every add, drop, claim and trade this season, newest first. Yahoo logs no IL "
                    "slot changes; the chat's IL steps show while they are pending."}


# =============================================================================
# Advice
# =============================================================================

def _who(name: str, key_of) -> dict:
    out = {"name": name, "card": key_of(name)}
    tags = getattr(key_of, "tags", None)
    if tags is not None:
        out["tags"] = tags(name)
    return out


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _move_lines(d: dict, key_of) -> list:
    """The step row's second line(s): "- drop", or the IL parts."""
    out = []
    if d.get("drop"):
        out.append({"sign": MINUS, "kind": "down", **_who(d["drop"], key_of)})
    if d.get("to_il"):
        out.append({"sign": "IL", "kind": "il", **_who(d["to_il"], key_of)})
    return out


def _title_tile(tiles: list) -> Optional[dict]:
    """v2_tiles' Title odds tile (the move against standing pat, as today)."""
    return next((t for t in tiles if t.get("label") in ("Title odds", "Playoff odds")), None)


class DayCards:
    """AC1: each move's card around days (claude/ADVICE_CARD_DAYS_MOCK_2026-11-25.md):
    the day strip (Team > Schedule's own fill, ranges.move_days), the tiles
    (Proj points, Win %, Title odds), the depth line and the footer. Every
    string is advice_live's; numbers come from move_days and the move's own.
    strip(m, earlier, mv, weeks) -> {week: days} or None (no range source, or
    an add the free agents' schedule doesn't have); keep(name) -> his Players
    row's keep chance or None."""

    def __init__(self, strip, horizon: dict, keep):
        self.strip, self.hz, self.keep = strip, horizon, keep

    def card(self, m: str, earlier: list, mv, *, weeks: list, win: Optional[list], tiles: list,
             title_gain: Optional[float], adds_left: Optional[int], drops: list,
             far_from: Optional[list] = None, chips: bool = False, notes: list = ()) -> dict:
        """weeks: the strip's weeks; win: [(label, change)] for the Win % tile
        (None: Rest of season); tiles: v2_tiles' (its Title odds tile is kept);
        adds_left: the budget week's adds left before this step (None: no add,
        an activation); drops: the dropped players (their keep chances);
        far_from: a far goal's weeks before its strip (the line above it);
        chips: Rest of season's week chips in place of the strip."""
        from .. import advice_live as al
        title = _title_tile(tiles)
        by = self.strip(m, earlier, mv, list(weeks) + list(far_from or [])) if self.strip else None
        out = {"strip": None, "missing": "", "depth": "", "tiles": [], "notes": [n for n in notes if n],
               "foot": []}
        if by is None:
            out["missing"] = al.DAYS_MISSING
            out["tiles"] = al.day_tiles(None, win, title)
        else:
            between = None
            if far_from:
                bx = [x for w in far_from for x in by[w]]
                g, l = al._gl(bx)
                between = al.between_text(bx[0]["d"] if bx else by[weeks[0]][0]["d"], list(far_from), g - l)
            sv = al.strip_view({w: by[w] for w in weeks}, chips=chips, between=between)
            xs = [x for w in weeks for x in by[w]]
            pts = al.proj_points(xs)
            out["strip"] = sv
            out["tiles"] = al.day_tiles(pts, win, title)
            wg = None if win is None else sum(v for _l, v in win if v is not None)
            if al.is_depth(sv["net"], pts, wg, title_gain if win is None else None):
                out["depth"] = al.DEPTH_TEXT
        if not far_from:
            j = al.join_text(self.hz)
            if j and adds_left is not None:
                out["foot"].append(j)
        if adds_left is not None:
            out["foot"].append(al.adds_text(adds_left))
        for n in drops:
            k = self.keep(n) if self.keep else None
            if k:
                out["foot"].append(al.keep_text(n, k))
        return out


def _mv(d: dict) -> dict:
    return {"add": d.get("add"), "drop": d.get("drop"), "to_il": d.get("to_il")}


def goals_view(latest: dict, order: list, team_of: dict, key_of, *, show_title: bool,
               dcards: "DayCards") -> Optional[dict]:
    """Advice goals (Part D): the picker's public chips and each goal's cards
    (every string the engine's: advice_live.goals_payload's texts). None when
    the goals are off, failed, or nothing but Balanced is public."""
    from .. import advice_live as al
    g = latest.get("goals")
    if not g or g.get("error") or not al.goals_on():
        return None
    picker = [x for x in g.get("goals") or [] if x.get("public")]
    if len(picker) <= 1:
        return None
    panes = {}
    hz = latest["horizon"]
    for x in picker:
        if x["key"] == "balanced":
            continue
        cards = []
        for m in order:
            e = (g["managers"].get(m) or {}).get(x["key"]) or {}
            base = latest["managers"][m]
            card = {"m": m, "vs": x["sub"], "adds": _plural(int(base["adds_left"]), "add left", "adds left"),
                    "rows": [], "line": "", "costs": [], "caveat": None, "as_of": None}
            if e.get("opponent"):
                card["vs"] = f"{x['sub']} vs {team_of[e['opponent']]}"
            if e.get("pending"):
                card["line"] = e["pending"]
            elif e.get("error") or e.get("not_priced") or not e.get("texts"):
                card["line"] = GOAL_UNPRICED
            else:
                t = e["texts"]
                card["line"] = t.get("line") or ""
                if e.get("vs_balanced") == "different":
                    earlier = []
                    act = base.get("activation")
                    if act and (base.get("il_choice") or {}).get("choice") != "hold":
                        earlier.append({"activate": list(act.get("back") or []), "drop": None})
                        earlier += [{"drop": n} for n in act.get("drops") or []]
                    for k, d in enumerate(e.get("plan") or [], 1):
                        tx = (d.get("text") or {}).get("v2") or al.v2_texts(d, hz, base["opponents"],
                                                                            show_title=show_title)
                        tv = float(d.get("target") or 0.0)
                        if x["target"] == "wins" and len(x["weeks"]) > 1:
                            val = f"{tv:+.2f} wins".replace("-", "\u2212")
                            lab = f"Wks {x['weeks'][0]}\u2013{x['weeks'][-1]}"
                        elif x["target"] == "rs_title":
                            val, lab = al._pct(tv), "Title odds"
                        else:
                            val, lab = al._pct(tv), f"Wk {x['weeks'][0]}"
                        gw = [int(w) for w in x["weeks"]]
                        first = int(hz["weeks"][0])
                        if x["target"] == "rs_title":
                            win, far = None, None
                        elif len(gw) == 1:
                            win = [(f"Wk {gw[0]}", tv)]
                            far = list(range(first, gw[0])) if not x["near"] and gw[0] > first else None
                        else:                     # each week's own change: the step's dwp (Balanced's weeks)
                            hw = [w for w in hz["weeks"] if w is not None]
                            win = [(f"Wk {w}", d["dwp"][hw.index(w)] if w in hw else None) for w in gw]
                            far = None
                        dc = dcards.card(m, list(earlier), _mv(d), weeks=gw, win=win, tiles=tx["tiles"],
                                        title_gain=d.get("title_odds"),
                                        adds_left=int(base["adds_left"]) - (k - 1),
                                        drops=[d["drop"]] if d.get("drop") else [], far_from=far,
                                        chips=x["target"] == "rs_title",
                                        notes=[al.FLAT_TEXT if d.get("flat") else ""])
                        card["rows"].append({"kind": "step", "n": str(k), "label": "",
                                             "adds": [_who(d["add"], key_of)], "lines": _move_lines(d, key_of),
                                             "weeks": [{"label": lab, "value": val,
                                                        "dir": "up" if tv > 0 else "down" if tv < 0 else "flat"}],
                                             "why": "", "card": dc, "tiles": dc["tiles"],
                                             "followup": "", "also": [], "flag": False})
                        earlier.append(_mv(d))
                    card["costs"] = t.get("costs") or []
                    if t.get("caveat"):
                        card["caveat"] = t["caveat"] + (f" Priced against {team_of[e['opponent']]}\u2019s roster today."
                                                        if e.get("opponent") else "")
                if not x["near"]:
                    card["as_of"] = t.get("as_of")
            cards.append(card)
        panes[x["key"]] = {"intro": x.get("intro") or "", "cards": cards, "near": x["near"]}
    return {"picker": [{"key": x["key"], "chip": x["chip"]} for x in picker if x["key"] == "balanced" or
                       not x["key"].startswith("week:")],
            "weeks": [{"key": x["key"], "chip": x["chip"], "label": f"{x['chip']}"} for x in picker
                      if x["key"].startswith("week:")],
            "panes": panes}


GOAL_UNPRICED = "This goal could not be priced for this team tonight. Balanced\u2019s advice stands."


def advice_view(latest: Optional[dict], order: list, team_of: dict, key_of, *, show_title: bool,
                strip=None, keep=None) -> dict:
    """The Advice segment's cards from advice_latest.json (every string the
    engine's; see the module docstring). AC1: each move's card is built around
    its days (DayCards): strip(m, earlier, mv, weeks) -> ranges.move_days by
    week (Team > Schedule's own fill), or None without a range source; keep(name)
    -> his Players row's keep chance. view["goals"] (Part D): the picker and
    each goal's cards, or None."""
    from .. import advice_live as al
    view = {"intro": INTRO, "cards": [], "foot": "", "error": "", "empty": "", "goals": None}
    if latest is None:
        view["empty"] = "Advice is being rebuilt; it returns here once it is ready."
        return view
    view["foot"] = latest["updated_text"]
    if latest.get("error"):
        view["error"] = "Advice could not be updated. The last pick is not shown: it may no longer stand."
        return view
    if latest.get("season_over"):
        view["empty"] = latest["season_over"]
        return view
    hz = latest["horizon"]
    view["intro"] = intro(hz.get("weeks") or [])
    cards = DayCards(strip, hz, keep)
    hweeks = [int(w) for w in hz.get("weeks") or [] if w is not None]

    def bal_win(d: dict) -> list:
        return [(f"Wk {w}", (d.get("dwp") or [None] * 2)[k] if str(w) in opps and opps.get(str(w)) else None)
                for k, w in enumerate(hweeks)]
    for m in order:
        e = latest["managers"].get(m)
        if e is None:
            raise MarketError(f"advice_latest.json has no advice for {m}")
        opps = e["opponents"]
        vs = DOT.join(f"Wk {w} vs {team_of[o] if o else 'no matchup'}" for w, o in opps.items())
        card = {"m": m, "vs": vs, "adds": _plural(int(e["adds_left"]), "add left", "adds left"),
                "rows": [], "plan": None, "title": None, "backup": None, "empty": ""}
        plan = e.get("plan") or ([e["move"]] if e.get("move") else [])
        act = e.get("activation")
        hold = e.get("hold") if (e.get("il_choice") or {}).get("choice") == "hold" else None
        if hold is not None:                                     # H54: keep him in IL this week
            tx = hold["texts"]["v2"]
            card["rows"].append({"kind": "act", "hold": True, "label": HOLD_LABEL,
                                 "adds": [_who(n, key_of) for n in hold["back"]],
                                 "lines": [{"sign": "", "kind": "note", "name": tx["sub"], "card": None}],
                                 "weeks": tx["weeks"], "why": tx["why"], "tiles": tx["tiles"],
                                 "followup": "", "also": [], "flag": False})
        elif act:
            tx = (act.get("texts") or {}).get("v2")
            if tx is None:                                       # a file from before 4c3: not priced
                tx = {"weeks": [{"label": f"Wk {w}", "value": DASH, "dir": "flat"} for w in opps],
                      "tiles": [], "why": act["text"]}
            why = tx["why"] if tx["why"] == al.FIRST_TEXT else ""
            if act.get("dwp") is not None:
                dc = cards.card(m, [], [{"activate": list(act["back"])}] + [{"drop": n} for n in act["drops"]],
                                weeks=hweeks, win=bal_win(act), tiles=tx["tiles"], title_gain=act.get("title_odds"),
                                adds_left=None, drops=list(act["drops"]), notes=[why])
            else:                                                # before 4c3: not priced, no numbers to show
                dc = None
            card["rows"].append({"kind": "act", "label": IL_LABEL,
                                 "adds": [_who(n, key_of) for n in act["back"]],
                                 "lines": [{"sign": MINUS, "kind": "down", **_who(n, key_of)} for n in act["drops"]],
                                 "weeks": tx["weeks"], "why": "" if dc else tx["why"], "card": dc,
                                 "tiles": dc["tiles"] if dc else tx["tiles"],
                                 "followup": "", "also": [], "flag": False})
        earlier = []
        if act and hold is None:
            earlier.append({"activate": list(act.get("back") or []), "drop": None})
            earlier += [{"drop": n} for n in act.get("drops") or []]
        for k, d in enumerate(plan, 1):
            tx = d["text"].get("v2") or al.v2_texts(d, hz, opps, show_title=show_title)
            also = list(d.get("also_wanted_by") or (e["also_wanted_by"] if k == 1 else []))
            dc = cards.card(m, list(earlier), _mv(d), weeks=hweeks, win=bal_win(d), tiles=tx["tiles"],
                            title_gain=d.get("title_odds"), adds_left=int(e["adds_left"]) - (k - 1),
                            drops=[d["drop"]] if d.get("drop") else [],
                            notes=[al.FLAT_TEXT if d.get("flat") else ""])
            earlier.append(_mv(d))
            card["rows"].append({"kind": "step", "n": str(d.get("step", k)), "label": "",
                                 "adds": [_who(d["add"], key_of)], "lines": _move_lines(d, key_of),
                                 "weeks": tx["weeks"], "why": "", "card": dc, "tiles": dc["tiles"],
                                 "followup": d["text"].get("followup") or "",
                                 "also": [{"m": o, "team": team_of[o]} for o in also], "flag": bool(also)})
        t = e.get("plan_total")
        if t is not None and len(card["rows"]) >= 2:
            pv = t.get("v2")
            if pv is None:                                       # before 4c3: the steps' total, no activation
                rows = len(plan)
                title = (f"{t['title_label']} {al._pct(t['title_odds'] or 0.0)}"
                         if show_title and t.get("title_label") else None)
                pv = {"weeks": al.v2_weeks(t, hz, opps), "label": al.PLAN_LABELS.get(rows, f"All {rows}"),
                      "rows": rows, "title": title}
            if pv["rows"] >= 2:
                card["plan"] = {"label": pv["label"], "title": pv["title"] if show_title else None,
                                "weeks": pv["weeks"]}
        # Nick, 11-19: a one-row card shows its title-odds change too, not only
        # behind the tap ("Even though its only one move, it should still show
        # title odds change"). The plan line carries it from two rows; one row
        # gets a title line of its own, the engine's string.
        if show_title and card["plan"] is None and len(card["rows"]) == 1:
            src = hold if hold is not None else (act if act else (plan[0] if plan else None))
            if src is not None and src.get("title_label") and src.get("title_odds") is not None:
                card["title"] = f"{src['title_label']} {al._pct(src['title_odds'])}"
        b = e.get("backup")
        if b is not None:
            tx = b["text"].get("v2") or al.v2_texts(b, hz, opps, show_title=show_title)
            first = plan[0]["add"] if len(plan) > 1 else None
            bearly = earlier[:1 + len((act or {}).get("drops") or [])] if (act and hold is None) else []
            dc = cards.card(m, list(bearly), _mv(b), weeks=hweeks, win=bal_win(b), tiles=tx["tiles"],
                            title_gain=b.get("title_odds"), adds_left=int(e["adds_left"]),
                            drops=[b["drop"]] if b.get("drop") else [],
                            notes=[al.FLAT_TEXT if b.get("flat") else ""])
            card["backup"] = {"if": f"If {first} is gone:" if first else "If he\u2019s gone:",
                              "add": _who(b["add"], key_of), "lines": _move_lines(b, key_of),
                              "weeks": tx["weeks"], "tiles": dc["tiles"], "why": "", "card": dc}
        if hold is not None:                                     # H54: no steps; the adds state only
            if int(e["adds_left"]) <= 0:
                card["empty"] = e.get("v2_empty") or al.EMPTY_V2["adds"]
        elif not plan:                                           # the one-sentence state
            code = ("adds" if int(e["adds_left"]) <= 0 else
                    "bar" if (e.get("note") or "").startswith("nothing clears") else "pat")
            card["empty"] = e.get("v2_empty") or al.EMPTY_V2[code]
        view["cards"].append(card)
    view["goals"] = goals_view(latest, order, team_of, key_of, show_title=show_title, dcards=cards)
    return view


# =============================================================================
# the block
# =============================================================================

def _strip_fn(ctx: dict):
    """AC1: a move's days by week, from the one range source (ctx["ranges"],
    Team > Schedule's) and the free agents' Availability (ranges.move_days);
    None without them. The days of each week from the move's effective day.
    One memo per build: a step priced under several goals is filled once."""
    from datetime import date as _date
    from . import ranges
    src, fa_av, wk = ctx.get("ranges"), ctx.get("fa_av"), ctx.get("wk_dates")
    adv = ctx.get("advice") or {}
    hz = adv.get("horizon")
    if src is None or fa_av is None or not wk or not hz:
        return None
    eff = _date.fromisoformat(hz["effective"])
    memo = {}

    def strip(m, earlier, mv, weeks):
        out = {}
        try:
            for w in weeks:
                ds = wk.get(int(w)) or wk.get(str(w))
                if ds is None:
                    raise MarketError(f"week {w} is not in the fantasy weeks (config/SCHEDULE.json)")
                out[int(w)] = ranges.move_days(src, fa_av, m, earlier, mv, [d for d in ds if d >= eff], memo)
        except ranges.RangeError:
            return None              # his games can't be counted here: the card says so (DAYS_MISSING)
        return out
    return strip


def _keep_fn(prow: dict):
    """AC1: the dropped player's keep chance, as his Players row shows it
    (rostered rows only; a dash is none)."""
    def keep(name):
        z = prow.get(name)
        if not z or z.get("kind") != "rostered" or not z.get("keep") or z["keep"] == DASH:
            return None
        return z["keep"]
    return keep


def build(payload: dict, ctx: dict) -> dict:
    """v2["market"]. ctx: "fa_av", "col_specs",
    "advice" (advice_latest.json, or None when advice.hub is off),
    "show_title", "first_day" (the season's first fantasy day)."""
    v2 = payload["v2"]
    order = list(v2["team_order"])
    team_of = {m: v2["teams"][m]["team"] for m in order}
    prow = {}
    for z in v2["players"]["rows"]:
        prow.setdefault(z["name"], z)

    def key_of(name):
        z = prow.get(name)
        return (z.get("key") or "") if z else ""

    def tags_of(name):                       # AC1: the move's tags (his Players row's status chips)
        z = prow.get(name)
        return [str(c["text"]) for c in (z.get("chips") or []) if c.get("kind") in ("out", "q", "il")] if z else []
    key_of.tags = tags_of
    segs = [["available", "Available"], ["stash", "Stash"]]
    adv = None
    if ctx["advice_on"]:
        segs.append(["advice", "Advice"])
        adv = advice_view(ctx["advice"], order, team_of, key_of, show_title=ctx["show_title"],
                          strip=_strip_fn(ctx), keep=_keep_fn(prow))
    segs += [["block", "Block"], ["moves", "Moves"]]
    return {"segs": segs,
            "available": available(payload["free_agents"], ctx["fa_av"], ctx["col_specs"], prow),
            "stash": stash(payload["stash"]),
            "advice": adv,
            "block": block(payload["trade_block"], order),
            "moves": moves(payload["moves"], order, ctx["first_day"]),
            "ranges": range_tables(payload, ctx)}                      # 5d2 s.4
