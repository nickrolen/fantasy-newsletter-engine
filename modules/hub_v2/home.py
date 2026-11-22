"""
hub_v2/home.py -- ENGINE SIDE of Home's two 5e cards (claude/HANDOFF_5E_PHONE_
REVIEW_2_2026-11-22.md s.1.2-1.3; Nick's answers on the mocks, 11-22 9:17 AM).
Every string is made here; the page prints them. NO NEW FETCH: everything
comes from the run's own inputs (the league log for last night, the grid's
Day for tonight, the matchup charts' Win % series, the move ledger's view,
the IL slots and tags, the stored tip times).

LAST NIGHT . TONIGHT ("nightly")
- Last night is the previous NBA day on the league clock (Pacific).
  * Each team's best performer: his best STARTED game that night (the game
    that counted), sorted by fantasy points; the night's top performer is
    marked. From the league log (data.lineups), the rows of that day.
  * The swings: one line per matchup, this week's win chance from the run
    before last night's first tip to the latest run, on the Win % chart's own
    points (hub_charts.winprob_points): "Jordan v Tyler: Jordan 41% -> 58%",
    the side whose chance rose named first. On a week's FIRST day last night
    was last week's last day: each of last week's matchups the same way, to
    its final ("Jordan v Tyler: Jordan 41% -> won by 22").
- Tonight is today on the league clock: per team, the starters with a game
  (hub_v2.ranges' Day for today, the games grid's own): "5 of 10", or
  "4 + 1 Q of 10" when a Q's game decides it; the day word (light: 4 or
  fewer of his players with a game; overflow: more than 10; nothing else);
  his players out tonight on the NBA's report. Empty slots are never shown
  (they are 10 minus the number). A day with no NBA games says so. After the
  night's last tip the card keeps tonight until the next run (Nick, 11-22).

MOVES WINDOW ("window")
- The window Monday before its close: "Window open: closes today at 7:25 PM"
  (price_lock.window_close, the stored tip times). Otherwise the next window,
  the first day of the next fantasy week ("Next window: Mon 11-30 . in 6
  days"): windows follow fantasy weeks, so a 14-day week has one.
- Adds left this fantasy week per team, of the budget (the hub's own count:
  transaction_rulings.add_budget_week and the ledger, hub_state's `adds`).
- Pending chat moves from the ledger (move_ledger.hub_view): claims (who
  claimed whom, joining which Monday, whose adds) and drops (free for the
  coming week).
- A team whose moves are blocked: an IL slot held by a player whose tag no
  longer makes him IL-eligible (move_ledger.tag_il_eligible, the rule's one
  definition), named.

No rule numbers in any string (Nick, 11-22). Both cards build SOFTLY
(data.home_soft): a failure leaves {"error"} and the card says "Couldn't
update".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

DOT = " \u00b7 "
ARROW = " \u2192 "
DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SEATS = 10
BENCH_SLOTS = ("BN", "IL", "IL+")


class HomeError(RuntimeError):
    """A Home card's input is missing or inconsistent; named."""


def dmd(d: date) -> str:
    return f"{DOW[d.weekday()]} {d.month:02d}-{d.day:02d}"


def clock(dt: datetime) -> str:
    h = dt.strftime("%I").lstrip("0") or "12"
    return f"{h}:{dt.strftime('%M')} {dt.strftime('%p')}"


def _pct(x: float) -> str:
    return f"{float(x):.0f}%"


def _pts(x: float) -> str:
    return f"{float(x):,.1f}"


def _last(name: str) -> str:
    return name.split(" ", 1)[1] if " " in name else name


# =============================================================================
# the swings
# =============================================================================

def swing(a: str, b: str, pts: list, cutoff: datetime) -> Optional[dict]:
    """One matchup's line: from the last point before `cutoff` (the first
    point when none is) to the last point. pts: [(datetime, pa, pb)]."""
    if not pts:
        return None
    pts = sorted(pts, key=lambda p: p[0])
    before = [p for p in pts if p[0] < cutoff]
    s, e = (before[-1] if before else pts[0]), pts[-1]
    da = float(e[1]) - float(s[1])
    who, w0, w1 = (a, s[1], e[1]) if da >= 0 else (b, s[2], e[2])
    other = b if who == a else a
    return {"who": who, "other": other, "from": _pct(w0), "to": _pct(w1), "delta": abs(da),
            "text": f"{who} v {other}: {who} {_pct(w0)}{ARROW}{_pct(w1)}"}


def final_swing(a: str, b: str, pts: list, cutoff: datetime, fa: float, fb: float) -> dict:
    """Last week's matchup to its final, from the run before its last day's
    first tip: "Jordan v Tyler: Jordan 41% -> won by 22"."""
    pts = sorted(pts, key=lambda p: p[0])
    before = [p for p in pts if p[0] < cutoff] or pts[:1]
    s = before[-1] if before else None
    if round(fa) == round(fb):
        w0 = _pct(s[1]) if s else "\u2014"
        return {"who": a, "other": b, "text": f"{a} v {b}: tied ({a} was {w0})", "delta": 0.0}
    who, other = (a, b) if fa > fb else (b, a)
    w0 = (_pct(s[1] if who == a else s[2])) if s else "\u2014"
    return {"who": who, "other": other, "delta": 100.0 - float((s[1] if who == a else s[2]) if s else 0.0),
            "text": f"{who} v {other}: {who} {w0}{ARROW}won by {round(abs(fa - fb)):,}"}


# =============================================================================
# Last night . Tonight
# =============================================================================

def nightly(ctx: dict) -> dict:
    """The card's model (the module docstring). ctx: "now", "today", "week",
    "wk_dates", "nba_schedule", "lineups" (the league log's DataFrame),
    "managers" (the page's team order), "src" (hub_v2.ranges.Source),
    "swing_raw" ({"this": [{"a","b","pts"}], "last": [{"a","b","pts","fa",
    "fb","id"}] or None}), "card_of" (name -> card key or None)."""
    from .. import price_lock
    today, week = ctx["today"], int(ctx["week"])
    wk = {int(w): list(v) for w, v in ctx["wk_dates"].items()}
    sched = ctx["nba_schedule"]
    managers = list(ctx["managers"])
    card_of = ctx["card_of"]
    y = today - timedelta(days=1)
    first_day = week in wk and today == wk[week][0]
    out = {"run": clock(ctx["now"]), "last": {}, "tonight": {}}

    # --- last night: each team's best started game
    lu = ctx["lineups"]
    day = lu[lu["date"].astype(str).str[:10] == y.isoformat()]
    st = day[~day["slot"].astype(str).isin(BENCH_SLOTS)]
    src = ctx["src"]
    n_games = _games_on(y, sched)
    best = []
    for m in managers:
        rows = st[st["manager"] == m]
        rows = rows[rows["fantasy_points"].notna()]
        if rows.empty:
            continue
        r = rows.loc[rows["fantasy_points"].astype(float).idxmax()]
        best.append({"m": m, "name": str(r["player_name"]), "card": card_of(str(r["player_name"])),
                     "nba": str(r.get("nba_team") or ""), "fp": float(r["fantasy_points"])})
    best.sort(key=lambda x: (-x["fp"], x["m"]))
    top = best[0]["fp"] if best else None
    for x in best:
        x["top"] = top is not None and x["fp"] == top
        x["fp_text"] = _pts(x["fp"])
    if n_games == 0:
        empty = f"No NBA games last night ({dmd(y)})."
    elif not best:
        empty = f"Last night's games ({dmd(y)}) aren't in the league log yet."
    else:
        empty = ""
    out["last"] = {"day": dmd(y), "games": n_games, "sub": (f"{dmd(y)}{DOT}{n_games} NBA game"
                                                            + ("" if n_games == 1 else "s")) if n_games else dmd(y),
                   "best": [{k: v for k, v in x.items() if k != "fp"} for x in best], "empty": empty}

    # --- the swings, one line per matchup
    raw = ctx["swing_raw"] or {}
    tip = _first_tip(y, sched)
    cutoff = tip or datetime.combine(y, datetime.min.time(), tzinfo=ctx["now"].tzinfo)
    lines, swing_head = [], ""
    if first_day and raw.get("last"):
        swing_head = f"Week {week - 1}'s finals"
        for x in raw["last"]:
            s = final_swing(x["a"], x["b"], _pts_of(x["pts"]), cutoff, x["fa"], x["fb"])
            lines.append(dict(s, href=f"#/matchups/{x['id']}"))
        out["swing_note"] = (f"Each matchup from the run before {dmd(y)}'s first game to its final, on its "
                             "Win % chart.")
    elif not first_day and n_games:
        swing_head = "Win chance, last night"
        for x in raw.get("this") or []:
            s = swing(x["a"], x["b"], _pts_of(x["pts"]), cutoff)
            if s is not None:
                lines.append(dict(s, href="#/matchups"))
        out["swing_note"] = (f"This week's win chance from the run before {dmd(y)}'s first game"
                             + (f" ({clock(tip)})" if tip else "") + " to the latest run, on each matchup's "
                             "Win % chart.")
    else:
        out["swing_note"] = ""
    lines.sort(key=lambda s: (-s["delta"], s["text"]))
    out["swings"] = [{k: v for k, v in s.items() if k in ("text", "href", "who", "other")} for s in lines]
    out["swing_head"] = swing_head

    # --- tonight
    n_tonight = _games_on(today, sched)
    t = {"day": dmd(today), "games": n_tonight, "rows": [], "empty": ""}
    if n_tonight == 0:
        nxt = next((today + timedelta(days=k) for k in range(1, 15) if _games_on(today + timedelta(days=k), sched)),
                   None)
        t["empty"] = "No NBA games tonight." + (f" Next games: {dmd(nxt)}." if nxt else "")
        t["sub"] = dmd(today)
    else:
        ft = _first_tip(today, sched)
        t["sub"] = (f"{dmd(today)}{DOT}{n_tonight} NBA game{'' if n_tonight == 1 else 's'}"
                    + (f"{DOT}first tip {clock(ft)}" if ft else ""))
        for m in managers:
            d = src.day(m, today)
            lo, hi = d.starts
            big = str(lo) if lo == hi else f"{lo} + {hi - lo} Q"
            word = "Light day" if d.kind == "light" else "Overflow day" if d.kind == "over" else ""
            t["rows"].append({"m": m, "big": big, "of": f"of {SEATS}", "word": word,
                              "word_kind": d.kind if word else "",
                              "out": [{"name": n, "last": _last(n), "card": card_of(n)} for n in d.nba_out],
                              "starts": [lo, hi]})
    out["tonight"] = t
    out["note"] = ("Last night: each team's best started game (the games that counted), the night's best "
                   "marked. Tonight: starters with a game, of the 10 lineup spots (\u201c4 + 1 Q\u201d: a "
                   "fifth if his Q plays). Light day: 4 or fewer of a team's players have a game; overflow: "
                   "more than 10. \u2020 out tonight on the NBA's injury report.")
    return out


def _games_on(d: date, sched) -> int:
    """NBA games on the league day d, from the stored schedule."""
    iso = d.isoformat()
    return sum(1 for g in (sched or {}).get("games", []) if str(g.get("date", ""))[:10] == iso)


def _first_tip(d: date, sched) -> Optional[datetime]:
    """The day's first tip, or None (no games, or a game without its time yet)."""
    from .. import price_lock
    try:
        return price_lock.first_tip(d, sched)
    except price_lock.TipTimeMissing:
        return None


def _pts_of(raw: list) -> list:
    return [(datetime.fromisoformat(t), float(a), float(b)) for t, a, b in raw]


# =============================================================================
# Moves window
# =============================================================================

def window(ctx: dict) -> dict:
    """The card's model (the module docstring). ctx: "now", "today", "week",
    "wk_dates", "nba_schedule", "managers", "team_of", "budget", "adds_left",
    "ledger" (move_ledger.hub_view), "il_slots", "tags", "card_of"."""
    from .. import price_lock
    from ..move_ledger import il_eligible_tags, tag_il_eligible
    now, today, week = ctx["now"], ctx["today"], int(ctx["week"])
    wk = {int(w): list(v) for w, v in ctx["wk_dates"].items()}
    sched = ctx["nba_schedule"]
    budget = int(ctx["budget"])
    card_of = ctx["card_of"]

    def week_of(d: date) -> Optional[int]:
        return next((w for w, ds in wk.items() if ds[0] <= d <= ds[-1]), None)

    def length_note(w: int) -> str:
        ds = wk[w]
        if len(ds) <= 7:
            return ""
        return (f"Week {w} is one {len(ds)}-day week: one window, and its {budget} adds cover all {len(ds)} "
                f"days. {dmd(ds[0] + timedelta(days=7))} is not a window.")
    out = {"open": False, "head": "", "sub": ""}
    close = None
    if week in wk and today == wk[week][0]:
        try:
            close = price_lock.window_close(today, sched)
        except (price_lock.NoGames, price_lock.TipTimeMissing):
            close = None
    if close is not None and now < close:
        out.update(open=True, head=f"Window open: closes today at {clock(close)}",
                   sub=" ".join(x for x in ("Five minutes before tonight's last game starts.",
                                            length_note(week)) if x))
    elif (week + 1) not in wk:
        out.update(head="No window is left this season.")
    else:
        d0 = wk[week + 1][0]
        n = (d0 - today).days
        out["head"] = f"Next window: {dmd(d0)}{DOT}" + ("tomorrow" if n == 1 else f"in {n} days")
        if len(wk[week + 1]) > 7:
            out["sub"] = length_note(week + 1)
        elif len(wk[week]) > 7 and today < wk[week][0] + timedelta(days=7):
            out["sub"] = (f"Week {week} is one {len(wk[week])}-day week, so "
                          f"{dmd(wk[week][0] + timedelta(days=7))} is not a window.")
    # adds left this fantasy week
    out["adds_week"] = week
    out["adds"] = [{"m": m, "left": str(int(ctx["adds_left"][m])), "zero": int(ctx["adds_left"][m]) <= 0}
                   for m in ctx["managers"]]
    out["adds_of"] = f"of {budget}"
    # pending chat moves
    lv = ctx["ledger"]
    moves = []
    for c in lv.get("live_claims") or []:
        wd = date.fromisoformat(c["window"])
        moves.append({"m": c["manager"], "kind": "claim", "player": c["player"], "card": card_of(c["player"]),
                      "text": f"{c['manager']} claimed {c['player']}",
                      "sub": f"joins {dmd(wd)}{DOT}used one of week {int(c['claim_week'])}'s adds"})
    for n, info in sorted((lv.get("dropped") or {}).items(), key=lambda kv: (kv[1]["window"], kv[0])):
        wd = date.fromisoformat(info["window"])
        w = week_of(wd)
        moves.append({"m": info["manager"], "kind": "drop", "player": n, "card": card_of(n),
                      "text": f"{info['manager']} dropped {n}",
                      "sub": (f"free for week {w} now: anyone may claim him" if w else
                              f"free from {dmd(wd)}")})
    out["moves"] = moves
    out["moves_sub"] = "they apply in the next window" if moves else ""
    # blocked: an IL slot held by a player whose tag no longer allows it
    elig = il_eligible_tags()
    blocked = []
    for m in ctx["managers"]:
        for n in ctx["il_slots"].get(m) or []:
            if not tag_il_eligible(ctx["tags"].get(n), elig):
                blocked.append({"m": m, "player": n, "card": card_of(n),
                                "text": (f"{ctx['team_of'].get(m, m)} can't make moves: {n} is in an IL slot "
                                         "without an O, OFS, Q or D tag. Moves open again once he leaves it.")})
    out["blocked"] = blocked
    out["note"] = ("Moves happen once a fantasy week, on its Monday, until five minutes before the last game "
                   "starts. A claim in the group chat uses the week it's posted in and joins the next Monday; "
                   "a drop frees the player for the coming week at once.")
    return out
