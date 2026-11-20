"""
hub_v2/data.py -- payload["v2"], the new hub's keys (step 4b), built inside
hub_state.build from the same run's inputs.

NEW KEYS ONLY. Nothing here changes an existing payload key: the current page
(modules/hub_page.py) reads those and keeps running until the switch-over.
Player rows are referenced by their index in payload["rosters"][m]["players"]
(the "i" fields), so every name, card key and status comes from the one place
it already lives.

THE ENGINE COMPUTES. Every number the new page shows is a string formatted
here (or already in the payload). Floats appear only beside a string, for
the view model to scale a mark (a sparkline point, a chart line, a bar); the
page never prints them.

    v2 = {
      "teams": {manager: {
          "slot", "mono", "team", "manager", "sub" (the team page's header line),
          "record", "odds", "injured" (count, string), "adds_left" (string),
          "kpi": {"odds" | "win" | "pf" | "adds": {"label", "value", "ctx", "dir"}},
          "spark": {"values": [float], "texts": [str], "labels": [str], "aria"},
          "roster": {"extra": [{"gp", "next"} per player], "orders": {"gp", "next"},
                     "keepers": [i...], "keep_line" (string), "keep_rank": [str per player],
                     "keep_w": [str per player]},
          "schedule": {"rows": [{"i", "cells": [{"n", "b"}]}]},
          "moves": [{"w": week key, "j": item index}]}},
      "team_order": [manager...]       the power-rankings order
      "spark_scale": {"max": float, "top": str, "note": str}
      "grid3": {"cols": [{"label", "sub"}], "rows": [{"m", "cells": [{"n", "b"}], "idle"}], "note",
                "idle_label"}   5b: Idle (this week's, the current grid's) and a dagger on a
                                week with a player out on the NBA's injury report
      "sched_cols": [{"label", "sub"}], "sched_note"
      "matchups": [{"id", "a", "b", "fav", "note", "note_src", "views",
                    "win": {...}, "flow": {...}, "starts": {...}, "missing": [...],
                    "lines": {...}}]          this week's, in the payload's card order
      "issue": {"text", "file", "week"} or None
      "last": {"title", "note", "cards": [...]} or None   last week's matchups, final (4c2)
      "line_text": the header's line string (hub_state's, the same engine string)
    4c2: every games-grid cell carries "tip" {"h", "b", "f"}: the tooltip's
    head (the week or the day), body (the days he plays, who starts) and foot
    (back-to-backs, the days he is out), strings; the win-% points' events carry
    "tip" and "dir". teams[m].roster.detail (modules/hub_v2/roster.py) is added
    after the Players rows.
      "players", "ratings"   (4c1; players_soft, after hub_cards.annotate:
                             modules/hub_v2/players.py)
    }

TEAM SLOTS (league_config hub.team_slots, required): each manager to one of
the design's four colour slots (blue, orange, teal, plum), each slot used
once. MONOGRAMS: two letters from the team's name -- the first letter of
each of its first two words, where a word is a run of letters (digits and
punctuation split words and are dropped); a name of one word gives its
first two letters. Upper case. An empty result or two teams with one
monogram RAISES (V2Error).

FAILS SOFTLY IN THE RUN (build_soft): until the switch-over the current page
is the hub, so a v2 failure must not stop the nightly's hub step. The run
gets payload["v2"] = None and payload["v2_error"] naming the stage and the
error, echoed loudly; the v2 renderer then RAISES with that error. Nothing
is defaulted: v2 is either whole or absent.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

SLOTS = ("blue", "orange", "teal", "plum")
DAGGER = "\u2020"
MINUS = "\u2212"
DASH = "\u2014"
UP, DOWN = "\u25b2", "\u25bc"
SPARK_MAX_POINTS = 8
# starts left by day (the matchup page's HeatGrid): bucket edges on a day's
# starts out of 10 lineup spots -- 0-3, 4-5, 6-7, 8-10
DAY_EDGES = (4, 6, 8)
# a player's games in a week (the team page's Schedule HeatGrid): 0-1, 2, 3, 4+
WEEK_GAME_EDGES = (2, 3, 4)
# win-% chart: a point is an event (a marker with a label) when the engine
# recorded a cause that is not the routine schedule and the line moved
ROUTINE = ("nightly", "Monday pre-tip", "the closing line", "final")
EVENT_MOVE = 0.05
EVENT_LABEL_MAX = 34


class V2Error(RuntimeError):
    """A v2 input is missing or inconsistent; the input is named."""


# =============================================================================
# team slots and monograms
# =============================================================================

def team_slots(league_config: dict = None, managers=None) -> Dict[str, str]:
    """league_config.json hub.team_slots -> {manager: slot}. Required: every
    manager exactly once, every value one of SLOTS, no slot twice."""
    if league_config is None:
        from ..data_loader import _LEAGUE_CONFIG as league_config
    if managers is None:
        from ..data_loader import MANAGERS as managers
    hub = league_config.get("hub")
    if not isinstance(hub, dict) or "team_slots" not in hub:
        raise V2Error("config/league_config.json has no hub.team_slots: each manager's colour slot "
                      f"({', '.join(SLOTS)}) is required")
    ts = hub["team_slots"]
    if not isinstance(ts, dict):
        raise V2Error("config/league_config.json hub.team_slots must be an object")
    got = {k: v for k, v in ts.items() if not str(k).startswith("_")}
    missing = [m for m in managers if m not in got]
    extra = [k for k in got if k not in managers]
    if missing or extra:
        raise V2Error(f"hub.team_slots: missing {missing}, unknown {extra}")
    bad = {k: v for k, v in got.items() if v not in SLOTS}
    if bad:
        raise V2Error(f"hub.team_slots: {bad} -- each must be one of {', '.join(SLOTS)}")
    if len(set(got.values())) != len(got):
        raise V2Error(f"hub.team_slots gives two managers one colour: {got}")
    return {m: got[m] for m in managers}


_WORD = re.compile(r"[^\W\d_]+")


def monogram(team_name: str) -> str:
    """The first letter of each of the first two words (runs of letters), or a
    one-word name's first two letters; upper case. RAISES when that is not two
    letters."""
    words = _WORD.findall(str(team_name or ""))
    if not words:
        raise V2Error(f"team name {team_name!r} has no letters: no monogram")
    mono = (words[0][0] + words[1][0]) if len(words) >= 2 else words[0][:2]
    if len(mono) != 2:
        raise V2Error(f"team name {team_name!r} gives the monogram {mono!r}, not two letters")
    return mono.upper()


def monograms(team_of: Dict[str, str]) -> Dict[str, str]:
    """{manager: monogram}; two teams with one monogram RAISE."""
    out = {m: monogram(t) for m, t in team_of.items()}
    seen = {}
    for m, mono in out.items():
        if mono in seen:
            raise V2Error(f"{team_of[seen[mono]]!r} and {team_of[m]!r} both give the monogram {mono}: "
                          "rename one, or change the rule in modules/hub_v2/data.monogram")
        seen[mono] = m
    return out


# =============================================================================
# formatting
# =============================================================================

def _int(x: float) -> str:
    return f"{float(x):,.0f}"


def _signed_int(x: float) -> str:
    v = int(round(float(x)))
    return (f"+{v:,}" if v > 0 else f"{MINUS}{abs(v):,}" if v < 0 else "0")


def _pct1(x: float) -> str:
    return f"{float(x):.1f}%"


def _md(d: date) -> str:
    return f"{d:%a} {d.month:02d}-{d.day:02d}"


def _lo(text: str) -> int:
    """The low end of a count printed as "6" or "5\u20136" (hub_state._rng)."""
    return int(str(text).split("\u2013")[0])


def first_sentence(text: str) -> str:
    """The text up to its first sentence end ('. ', '! ' or '? ' before a
    capital), or all of it."""
    m = re.search(r"[.!?](?=\s+[A-Z\u201c\"])", text)
    return text[:m.end()] if m else text


def bucket(v: int, edges) -> int:
    """1 + how many edges v reaches: 1..len(edges)+1."""
    return 1 + sum(1 for e in edges if v >= e)


# =============================================================================
# the games grids' tooltips (4c2, HUB_PREVIEW_NOTES s.3): one small dark box,
# {"h": the week or the day, "b": the days or who, "f": the marks}, strings
# =============================================================================

def week_head(w: int, sub: str) -> str:
    return f"Wk {w}" + (" rest" if sub == "rest" else "")


def day_name(d: date, long_week: bool) -> str:
    """"Mon", or "Mon 12-21" in a week longer than seven days (rule 9)."""
    return f"{d:%a}" + (f" {d.month:02d}-{d.day:02d}" if long_week else "")


def b2b_text(days: list, long_week: bool) -> list:
    """["Fri\u2013Sat B2B"] for each pair of consecutive days in `days`."""
    ds = sorted(days)
    return [f"{day_name(x, long_week)}\u2013{day_name(y, long_week)} B2B" for x, y in zip(ds, ds[1:])
            if (y - x).days == 1]


def player_week_tip(av, name: str, w: int, sub: str, days: list, long_week: bool) -> tuple:
    """(count, tip) for a player's week: the days he will play (av.plays, the
    count's own rule), back-to-backs among them, and his team's game days he
    is out ("out Mon"), so the count and the days agree."""
    plays = av.playable(name, days)
    out = [d for d in days if av.has_game(name, d) and d not in plays]
    marks = b2b_text(plays, long_week)
    if out:
        marks.append("out " + ", ".join(day_name(d, long_week) for d in out))
    body = " \u00b7 ".join(day_name(d, long_week) for d in plays) or "No games he will play"
    tip = {"h": week_head(w, sub), "b": body}
    if marks:
        tip["f"] = " \u00b7 ".join(marks)
    return len(plays), tip


def il_tip(w: int, sub: str, back: str) -> dict:
    return {"h": week_head(w, sub), "b": "IL slot" + (f" \u00b7 {back}" if back else "")}


def starters_on(av, m: str, d: date) -> tuple:
    """(starters, maybe, out tonight): the daily fill of who will play (the
    grid's own fit, schedule_strength.fill_daily_lineup_detail), a Q's next
    game added when it fits, and the NBA report's Outs. Names."""
    from ..schedule_strength import fill_daily_lineup_detail

    def fit(ps):
        return fill_daily_lineup_detail([(p, set(av.info[p]["positions"]), float(av.info[p].get("proj_fppg", 0.0)))
                                         for p in ps])[0]
    sure, maybe, nba = av.grid_players(m, d)
    st = fit(sure)
    hi = fit(sure + maybe)
    return st, [p for p in hi if p not in st], nba


# =============================================================================
# the title-odds sparkline
# =============================================================================

def odds_points(base: Path, data, key: str) -> dict:
    """{league day: {manager: odds}} the season chart's points (hub_charts.
    title_points, the same inputs hub_state.title_chart gathers)."""
    from .. import title_odds_history as toh, hub_charts as hc
    rows = toh.read(base)
    sched = data.schedule
    starts = {int(w["week"]): date.fromisoformat(str(w["start_date"])[:10]) for w in sched["weeks"]}
    first_hist = min((datetime.fromisoformat(r["as_of"]).date() for r in rows if r.get(key)), default=None)
    reports = []
    for p in sorted((Path(base) / "output").glob("stats_report_week*.json")):
        try:
            wk = int(p.stem.replace("stats_report_week", ""))
        except ValueError:
            continue
        day = starts.get(wk + 1)
        if first_hist is not None and day is not None and day >= first_hist:
            continue
        reports.append(json.loads(p.read_text(encoding="utf-8")))
    try:
        pts = hc.title_points(rows, reports, sched, key=key)
    except hc.ChartError as e:
        raise V2Error(f"the title-odds sparkline: {e}") from None
    return {d: v["values"] for d, v in pts.items()}


def sparks(points: dict, wk_dates: dict, today: date, managers, label: str) -> tuple:
    """({manager: spark}, scale): each manager's odds at the end of each week
    so far (the last point on or before that week's last day), the current
    week's being its latest point; at most SPARK_MAX_POINTS, oldest first. One
    shared y-scale: 0 to the next multiple of 25 above every value."""
    by_week = []
    for w in sorted(wk_dates):
        days = [d for d in points if wk_dates[w][0] <= d <= wk_dates[w][-1] and d <= today]
        if days:
            by_week.append((w, points[max(days)]))
    by_week = by_week[-SPARK_MAX_POINTS:]
    if not by_week:
        raise V2Error("no title-odds point in any week so far: no sparkline")
    out, top = {}, 0.0
    for m in managers:
        vals = []
        for w, vs in by_week:
            if m not in vs:
                raise V2Error(f"the week-{w} title-odds point has no value for {m}")
            vals.append(float(vs[m]))
        top = max(top, max(vals))
        texts = [_pct1(v) for v in vals]
        out[m] = {"values": vals, "texts": texts, "labels": [f"Wk {w}" for w, _ in by_week],
                  "aria": f"{label} at the end of each week: "
                          + ", ".join(f"week {w} {t}" for (w, _), t in zip(by_week, texts))}
    mx = 25.0 * max(1, math.ceil(top / 25.0))
    scale = {"max": mx, "top": f"{mx:.0f}%",
             "note": f"{label} at the end of each week, and now; every line on one scale, 0\u2013{mx:.0f}%."}
    return out, scale


# =============================================================================
# the matchup charts' series
# =============================================================================

def win_series(entry: dict, a: str, b: str, points: list, tz, team_of: dict, mono: dict = None) -> dict:
    """The Win % chart's points: x the moment's place in the week (0..1), the
    two percentages, the tap text (time, run or cause, both values), and an
    event label where the engine recorded a cause off the routine schedule and
    the line moved. points: hub_charts.winprob_points (the current chart's own)."""
    from ..hub_charts import clock, pct
    from datetime import time as _time
    a0 = date.fromisoformat(str(entry["start_date"])[:10])
    b0 = date.fromisoformat(str(entry["end_date"])[:10])
    t0 = datetime.combine(a0, _time(0), tzinfo=tz)
    span = (datetime.combine(b0 + timedelta(days=1), _time(0), tzinfo=tz) - t0).total_seconds()
    out, prev = [], None
    for dt, pa, pb, lab in points:
        x = min(max((dt - t0).total_seconds() / span, 0.0), 1.0)
        when = "Final" if lab == "final" else clock(dt)
        routine = lab in ROUTINE or lab.endswith(" run")
        moved = prev is not None and abs(pa - prev) >= EVENT_MOVE
        ev = ""
        if not routine and moved:
            own = lab.split("; also moved")[0]
            short = own.split(": ", 1)[1] if ": " in own else own
            short = short.split(", ")[0].split("; ")[0]
            ev = short if len(short) <= EVENT_LABEL_MAX else short[:EVENT_LABEL_MAX - 1].rstrip() + "\u2026"
        cause = "" if lab == "final" else lab
        pt = {"x": x, "a": float(pa), "b": float(pb), "ta": pct(pa), "tb": pct(pb), "when": when,
              "cause": cause, "event": ev}
        if ev:
            # 4c2: a hollow up/down dot, its words in the tooltip only
            from ..hub_charts import signed
            sw = float(pa) - float(prev)
            pt["dir"] = "up" if sw > 0 else "down"
            pt["tip"] = {"h": when, "b": short,
                         "f": ((mono or {}).get(a, team_of[a]) + " " + signed(sw, 1) + "%")}
        out.append(pt)
        prev = pa
    days = [a0 + timedelta(days=i) for i in range((b0 - a0).days + 1)]
    ticks = [{"x": (i + 0.5) / len(days), "t": f"{d:%a}"} for i, d in enumerate(days)]
    last = out[-1] if out else None
    aria = (f"{team_of[a]}'s chance to beat {team_of[b]} through the week: "
            + (f"{last['ta']} now" if last else "no priced line yet")
            + (", with events marked where the engine recorded a cause" if any(p["event"] for p in out) else "")
            + ".")
    return {"points": out, "ticks": ticks, "yticks": [{"v": 0.0, "t": "0%"}, {"v": 50.0, "t": "50%"},
                                                      {"v": 100.0, "t": "100%"}],
            "aria": aria, "empty": "" if out else "No priced line yet this week."}


def flow_series(entry: dict, a: str, b: str, banked: dict, expected: Optional[dict], team_of: dict,
                mono: dict) -> dict:
    """The Game flow chart: each team's points added up by day, banked
    (solid) then the same pricing run's expected days (dashed), with a tap
    text per day and the y ticks. The dashed end is the line's projected
    final (hub_matchups checks the same sums)."""
    from ..hub_charts import day_label
    a0 = date.fromisoformat(str(entry["start_date"])[:10])
    b0 = date.fromisoformat(str(entry["end_date"])[:10])
    days = [a0 + timedelta(days=i) for i in range((b0 - a0).days + 1)]
    iso = [d.isoformat() for d in days]
    nb = len(banked.get(a) or {})
    series = {}
    for m in (a, b):
        run, seq = 0.0, [0.0]
        for d in iso[:nb]:
            run += float(banked[m][d])
            seq.append(run)
        exp = None
        if expected is not None and nb < len(iso):
            e = expected.get(m) or {}
            if set(e) != set(iso[nb:]):
                raise V2Error(f"game flow: the expected days for {m} are {sorted(e)}, not {iso[nb:]}")
            exp, r2 = [run], run
            for d in iso[nb:]:
                r2 += float(e[d])
                exp.append(r2)
        end = exp[-1] if exp else seq[-1]
        kind = "exp." if exp else ("final" if nb == len(iso) else "so far")
        series[m] = {"banked": seq, "exp": exp, "end": end,
                     "label": f"{mono[m]} {_int(end)}" + (" exp." if exp else ""), "kind": kind}
    top = max([v for m in (a, b) for v in series[m]["banked"] + (series[m]["exp"] or [])] + [1.0])
    step = 500 if top > 1000 else 250 if top > 400 else 100
    vmax = step * math.ceil(top / step)
    mid = vmax / 2
    yticks = [{"v": 0.0, "t": "0"}, {"v": mid, "t": _int(mid)}, {"v": float(vmax), "t": _int(vmax)}]
    tips = []
    for i, d in enumerate(days):
        if i < nb:
            tips.append(f"Through {day_label(d)}: {team_of[a]} {_int(series[a]['banked'][i + 1])}, "
                        f"{team_of[b]} {_int(series[b]['banked'][i + 1])}")
        elif series[a]["exp"] is not None:
            j = i - nb + 1
            tips.append(f"Expected through {day_label(d)}: {team_of[a]} {_int(series[a]['exp'][j])}, "
                        f"{team_of[b]} {_int(series[b]['exp'][j])}")
        else:
            tips.append(f"{day_label(d)}: not played yet")
    aria = (f"Points added up by day: {team_of[a]} {_int(series[a]['banked'][-1])}, "
            f"{team_of[b]} {_int(series[b]['banked'][-1])} banked"
            + (f"; projected to finish {_int(series[a]['end'])} to {_int(series[b]['end'])}"
               if series[a]["exp"] else "") + ".")
    return {"n_days": len(days), "nb": nb, "ticks": [{"i": i, "t": f"{d:%a}"} for i, d in enumerate(days)],
            "ymax": float(vmax), "yticks": yticks, "series": series, "tips": tips, "aria": aria}


# =============================================================================
# the build
# =============================================================================

def build_soft(base, ctx: dict, echo=print) -> tuple:
    """(v2, error): build(), or (None, {"stage", "error"}) and a loud echo.
    The nightly must never lose the current hub to the new one."""
    try:
        return build(base, ctx), None
    except Exception as e:                       # noqa: BLE001 -- v2 fails softly until the switch-over
        err = {"stage": "v2", "error": f"{type(e).__name__}: {e}".splitlines()[0][:500]}
        echo(f"NEW HUB KEYS FAILED (payload v2 left out; the current hub goes on): {err['error']}")
        return None, err


def players_soft(base, payload: dict, ctx: dict, echo=print) -> tuple:
    """(v2, error) with v2["players"] and v2["ratings"] added (4c1,
    modules/hub_v2/players.py), after hub_cards.annotate gave the card keys.
    A failure here leaves v2 out, as build_soft does (v2 is whole or absent):
    (None, {"stage": "players", "error"}), echoed loudly. A RATINGS failure is
    not one of these: it is recorded in ctx["ratings"]["error"] and the
    Players tab shows no OVR/POT, saying why."""
    from . import players
    try:
        block, rblock = players.build(base, payload, ctx)
    except Exception as e:                       # noqa: BLE001 -- v2 fails softly until the switch-over
        err = {"stage": "players", "error": f"{type(e).__name__}: {e}".splitlines()[0][:500]}
        echo(f"NEW HUB KEYS FAILED (payload v2 left out; the current hub goes on): {err['error']}")
        return None, err
    v2 = payload["v2"]
    v2["players"], v2["ratings"] = block, rblock
    return v2, None


def teams_soft(base, payload: dict, ctx: dict, echo=print) -> tuple:
    """(v2, error) with each team's roster.detail (4c2, modules/hub_v2/
    roster.py) and Team value (team_value.py) added, after the Players rows.
    A failure leaves v2 out, softly, as build_soft does: (None, {"stage":
    "roster", "error"}), echoed loudly."""
    from . import roster, team_value as tvm
    v2 = payload["v2"]
    try:
        active = {m: [p["name"] for p in rb["players"] if not p["in_il"]] for m, rb in payload["rosters"].items()}
        tv = tvm.compute(data=ctx["data"], now=ctx["now"], week=ctx["week"], wk_dates=ctx["wk_dates"],
                         active=active, pool=list(ctx["pool"]), tag_row=ctx["tag_row"], tags=ctx["tags"])
        prices = tvm.title_prices(base, list(payload["rosters"]), tv["weeks"]) if tv["weeks"] else ({}, "", "")
        wk = {int(w): list(v) for w, v in ctx["wk_dates"].items()}
        today = ctx["today"]
        sched_days = [[d for d in wk.get(ctx["week"], []) if d >= today], wk.get(ctx["week"] + 1, []),
                      wk.get(ctx["week"] + 2, [])]
        shared, detail = roster.build(base, payload, dict(ctx, players_block=v2["players"], team_value=tv,
                                                          title_prices=prices, sched_days=sched_days))
    except Exception as e:                       # noqa: BLE001 -- v2 fails softly until the switch-over
        err = {"stage": "roster", "error": f"{type(e).__name__}: {e}".splitlines()[0][:500]}
        echo(f"NEW HUB KEYS FAILED (payload v2 left out; the current hub goes on): {err['error']}")
        return None, err
    v2["roster_cols"] = shared
    for m, d in detail.items():
        v2["teams"][m]["roster"]["detail"] = d
    v2["team_value"] = {"weeks": tv["weeks"], "seconds": tv["seconds"], "sims": tv["sims"]}
    return v2, None


def market_soft(base, payload: dict, ctx: dict, echo=print) -> tuple:
    """(v2, error) with v2["market"] added (4c3, modules/hub_v2/market.py),
    after the Players rows. A failure leaves v2 out, softly, as build_soft
    does: (None, {"stage": "market", "error"}), echoed loudly."""
    from . import market
    v2 = payload["v2"]
    try:
        v2["market"] = market.build(payload, ctx)
    except Exception as e:                       # noqa: BLE001 -- v2 fails softly until the switch-over
        err = {"stage": "market", "error": f"{type(e).__name__}: {e}".splitlines()[0][:500]}
        echo(f"NEW HUB KEYS FAILED (payload v2 left out; the current hub goes on): {err['error']}")
        v2.pop("market", None)
        return None, err
    return v2, None


def league_soft(base, payload: dict, ctx: dict, echo=print) -> tuple:
    """(v2, error) with v2["league"] and v2["league_history"] added (4c4,
    modules/hub_v2/league.py), after the Market. A failure leaves v2 out,
    softly, as build_soft does: (None, {"stage": "league", "error"}), echoed
    loudly. league_history leaves the payload for the side file with the
    Players rows (players_file), for the payload's size."""
    from . import league
    v2 = payload["v2"]
    try:
        inp = league.gather(base, data=ctx["data"], power=payload["power"], managers=list(v2["team_order"]),
                            teams=v2["teams"], newsletter=payload["newsletter"], now=ctx["now"],
                            ratings=ctx.get("ratings"), ratings_error=ctx.get("ratings_error"), live=ctx.get("live"),
                            awards=ctx.get("awards"))
        v2["league"], v2["league_history"] = league.build(inp)
    except Exception as e:                       # noqa: BLE001 -- v2 fails softly until the switch-over
        err = {"stage": "league", "error": f"{type(e).__name__}: {e}".splitlines()[0][:500]}
        echo(f"NEW HUB KEYS FAILED (payload v2 left out; the current hub goes on): {err['error']}")
        v2.pop("league", None)
        v2.pop("league_history", None)
        return None, err
    return v2, None


PLAYERS_SCHEMA = 1

# 5a (4C5_DECISIONS 13, and the headroom under test_hub_polish3's 400 KB cap):
# the payload keys that ride in the side file too, put back in memory by
# attach_players for the page's builder. Each one grows through the season:
# the awards' races (about 1 KB a week), the title-odds chart (one point per
# pricing run) and Market's moves (one row per move). (v2 sub-block, key).
SIDE_KEYS = (("league", "awards"), ("league", "chart"), ("market", "moves"))
# 5b: each team's roster Detailed columns (v2.teams[m].roster.detail, ~9 KB a
# team) ride in the side file too, under this name
DETAIL_KEY = "teams.roster.detail"

# 5b (5a decision 4): under hub.version "v2" the STORED payload keeps only
# what the published page and the next run read. Measured (5b): the v2
# publish is byte-identical without these, and hub_cards.shown_names (the next
# night's free-agent lines) and headshots.missing never read them. Everything
# else stays: the v2 page reads rosters, moves, cards, matchups, the header,
# free_agents/stash/trade_block (the cards); shown_names reads advice too.
V2_UNREAD = (("power", "chart"), ("power", "chart_title"), ("grid",), ("advice_empty",))


def store_v2(payload: dict) -> dict:
    """The payload as STORED under hub.version "v2" (output/hub_state.json):
    the current page's keys no v2 reader reads (V2_UNREAD) dropped, and
    matchup_views cut to the views v2 reads (each matchup's Summary, this
    week's and last week's: v2.matchups[].views.sum, v2.last.cards[].views.sum). Marked payload["v2_store"] (what was dropped),
    so the current page's builder refuses it (a rollback rebuilds the
    payload first: python scripts/build_hub_state.py). In place; returns
    {name: bytes dropped}."""
    if payload.get("v2") is None:
        return {}
    dropped = {}
    for path in V2_UNREAD:
        node = payload
        for k in path[:-1]:
            node = node.get(k) if isinstance(node, dict) else None
        if isinstance(node, dict) and path[-1] in node:
            dropped[".".join(path)] = len(json.dumps(node.pop(path[-1])))
    keep = {mv["views"]["sum"] for mv in payload["v2"].get("matchups") or []}
    keep |= {c["views"]["sum"] for c in ((payload["v2"].get("last") or {}).get("cards") or [])}
    views = payload.get("matchup_views")
    if isinstance(views, list):
        out = [v for v in views if v.get("id") in keep]
        if len(out) != len(views):
            dropped["matchup_views (all but the Summary views v2 reads)"] = \
                len(json.dumps(views)) - len(json.dumps(out))
            payload["matchup_views"] = out
    payload["v2_store"] = {"dropped": sorted(dropped),
                           "note": "stored under hub.version v2: the current page's own keys are left out; "
                                   "the current page needs a rebuilt payload (python scripts/build_hub_state.py)"}
    return dropped


def players_file(payload: dict) -> dict:
    """Take v2.players OUT of the payload (4c1 decision 8: the payload's size)
    and return it as its own file's object, stamped with the payload's
    generated_at and engine key so a stale file is never shown with a newer
    payload. The payload keeps a pointer: v2["players_file"]. 4c4: League's
    History rides along; 5a: so do SIDE_KEYS (v2["players_file"]["moved"]
    names them)."""
    v2 = payload["v2"]
    block = v2.pop("players")
    v2["players_file"] = {"rows": len(block["rows"]), "generated_at": payload["generated_at"]}
    obj = {"schema": PLAYERS_SCHEMA, "generated_at": payload["generated_at"],
           "engine": (payload.get("engine") or {}).get("key"), "players": block}
    if "league_history" in v2:                 # 4c4: League's History rides in the same side file
        obj["league_history"] = v2.pop("league_history")
        v2["players_file"]["league_history"] = True
    moved = {}
    for blk, key in SIDE_KEYS:
        if isinstance(v2.get(blk), dict) and key in v2[blk]:
            moved[f"{blk}.{key}"] = v2[blk].pop(key)
    det = {m: t["roster"].pop("detail") for m, t in (v2.get("teams") or {}).items()
           if isinstance(t.get("roster"), dict) and "detail" in t["roster"]}
    if det:                                    # 5b: the roster's Detailed columns
        moved[DETAIL_KEY] = det
    if moved:
        obj["moved"] = moved
        v2["players_file"]["moved"] = sorted(moved)
    return obj


def attach_players(payload: dict, obj: Optional[dict]) -> dict:
    """The payload with v2.players put back from its file, in memory, for the
    page's builder. RAISES V2Error when the file is missing or was built for
    another payload."""
    v2 = payload.get("v2")
    if v2 is None or "players" in v2:
        return payload
    if obj is None:
        raise V2Error("the new hub's Players file (output/hub_players.json) is missing: rebuild the payload "
                      "with this engine (python scripts/build_hub_state.py)")
    if obj.get("schema") != PLAYERS_SCHEMA or obj.get("generated_at") != payload.get("generated_at") \
            or obj.get("engine") != (payload.get("engine") or {}).get("key"):
        raise V2Error(f"the Players file was built for {obj.get('generated_at')}, the payload is "
                      f"{payload.get('generated_at')}: rebuild both (python scripts/build_hub_state.py)")
    v2["players"] = obj["players"]
    if (v2.get("players_file") or {}).get("league_history"):
        if "league_history" not in obj:
            raise V2Error("the side file lacks League's History: rebuild both (python scripts/build_hub_state.py)")
        v2["league_history"] = obj["league_history"]
    for name in (v2.get("players_file") or {}).get("moved") or []:       # 5a: SIDE_KEYS
        if name not in (obj.get("moved") or {}):
            raise V2Error(f"the side file lacks {name}: rebuild both (python scripts/build_hub_state.py)")
        if name == DETAIL_KEY:                                             # 5b
            for m, d in obj["moved"][name].items():
                if m not in (v2.get("teams") or {}):
                    raise V2Error(f"the side file's roster Detailed columns name {m}, not a team of the payload")
                v2["teams"][m]["roster"]["detail"] = d
            continue
        blk, key = name.split(".", 1)
        if not isinstance(v2.get(blk), dict):
            raise V2Error(f"the payload has no v2.{blk} to put {name} back into")
        v2[blk][key] = obj["moved"][name]
    return payload


def build(base, ctx: dict) -> dict:
    """payload["v2"] from hub_state.build's own locals (ctx). RAISES V2Error."""
    from .. import hub_charts as hc, winprob_history as wh, keepability_v3 as kv3
    from ..hub_state import build_grid_tab, build_matchups, ODDS_KEY
    from ..week_state import week_entry
    from ..league_clock import league_tz
    from ..simulator_cup_odds import cup_seeding_points

    base = Path(base)
    data, now, week = ctx["data"], ctx["now"], ctx["week"]
    today = now.date()
    managers = list(ctx["managers"])
    team_of = {m: ctx["team_of"].get(m, m) for m in managers}
    slots = team_slots(managers=managers)
    mono = monograms(team_of)
    power, rosters = ctx["power"], ctx["roster_blocks"]
    by_rank = {r["manager"]: r for r in power["rows"]}
    order = [r["manager"] for r in power["rows"]]
    wk_dates = {int(w): list(v) for w, v in ctx["wk_dates"].items()}
    av, next_av = ctx["av"], ctx["next_av"]
    tz = league_tz()

    # --- matchup cards: who's on which side this week
    cards = ctx["matchup_cards"]
    opp, win_of = {}, {}
    for c in cards:
        a, b = c["a"]["manager"], c["b"]["manager"]
        opp[a], opp[b] = b, a
        win_of[a], win_of[b] = c["a"]["win"], c["b"]["win"]

    # --- points for, vs the league average (the PF the power rows print)
    pf_pts = cup_seeding_points(data)
    for m in managers:
        if _int(pf_pts[m]) != by_rank[m]["pf"]:
            raise V2Error(f"PF for {m}: {_int(pf_pts[m])} here, {by_rank[m]['pf']} in the power rows")
    avg = sum(float(pf_pts[m]) for m in managers) / len(managers)
    pf_rank = {m: i + 1 for i, m in enumerate(sorted(managers, key=lambda x: (-float(pf_pts[x]), x)))}

    # --- adds: the budget week resets with the next fantasy week
    budget = int(ctx["budget"])
    nxt = wk_dates.get(week + 1)
    reset = f"resets {_md(nxt[0])}" if nxt else "the season's last week"

    # --- the sparkline: the odds the power rows show (title odds: weeks 1-15)
    key = ODDS_KEY[power["kind"]]
    pts = odds_points(base, data, key)
    spark, scale = sparks(pts, wk_dates, today, managers, power["label"])
    for m in managers:
        if spark[m]["texts"][-1] != by_rank[m]["odds"]:
            raise V2Error(f"the sparkline's latest point for {m} is {spark[m]['texts'][-1]}, "
                          f"the power rows say {by_rank[m]['odds']}")

    # --- three weeks of days: the rest of this week, next week, the week after
    this_days, next_days = list(ctx["this_days"]), list(ctx["next_days"])
    third_days = list(wk_dates.get(week + 2) or [])
    sched_cols = []
    for w, days, sub in ((week, this_days, "rest"), (week + 1, next_days, ""), (week + 2, third_days, "")):
        if days:
            sched_cols.append({"label": f"Wk {w}", "sub": sub, "days": days, "w": w,
                               "long": len(wk_dates.get(w) or days) > 7})

    # --- the 3-week games grid: starts per team per week. The first two
    # columns are the current grid's tabs; the third is the same rule on the
    # week after next, rosters as they will stand with the pending moves
    grid_rows = {t["key"]: {r["manager"]: r for r in t["rows"]} for t in ctx["grid_tabs"]}
    cols3 = [("this", this_days), ("next", next_days)]
    third = None
    if third_days:
        def games_on(d):
            return sum(1 for ds in next_av.team_dates.values() if d in ds) // 2
        third = build_grid_tab(next_av, managers, third_days, ctx["light_max"],
                               {d: games_on(d) for d in third_days}, ctx["standins"])
        grid_rows["third"] = {r["manager"]: r for r in third["rows"]}
        cols3.append(("third", third_days))
    cols3 = [(k, ds) for k, ds in cols3 if ds]
    grid_cells = {m: [] for m in managers}
    for (k, ds), sc in zip(cols3, sched_cols):
        vals = {m: _lo(grid_rows[k][m]["starts"]) for m in managers}
        ranked = sorted(set(vals.values()), reverse=True)
        for m in managers:
            # darkest for the most starts that week; ranks, so a short week compares fairly
            gr = grid_rows[k][m]
            per_day = [f"{day_name(d, sc['long'])} {cell['starts']}{DAGGER if cell.get('nba') else ''}"
                       for d, cell in zip(ds, gr["cells"])]
            # 5b (5a decision 7): the old grid's Idle and its NBA-report mark
            outs = [c["nba_names"] for c in gr["cells"] if c.get("nba") and c.get("nba_names")]
            foot = f"{gr['starts']} starts \u00b7 {gr['idle']} idle"
            if outs:
                foot += f" \u00b7 {DAGGER} out tonight on the NBA's injury report: {', '.join(outs)}"
            tip = {"h": week_head(sc["w"], sc["sub"]), "b": " \u00b7 ".join(per_day), "f": foot}
            grid_cells[m].append({"n": gr["starts"] + (DAGGER if outs else ""),
                                  "b": 4 - min(3, ranked.index(vals[m])), "tip": tip})
    first_k = cols3[0][0] if cols3 else None
    grid3 = {"cols": [{"label": c["label"], "sub": c["sub"]} for c in sched_cols],
             "rows": [{"m": m, "cells": grid_cells[m], "idle": grid_rows[first_k][m]["idle"] if first_k else DASH}
                      for m in order],
             "idle_label": {"label": "Idle", "sub": sched_cols[0]["sub"] if sched_cols else ""},
             "note": ("Starts: games that fit a starting lineup, for players who will play. Shaded by rank "
                      "within each week: darker = more starts than the other teams that week, so a short "
                      "week compares fairly. Weeks after this one count rosters as they will stand with the "
                      "pending moves. Idle: games by players who sit, this week (each week's is in its cell's "
                      f"tap). {DAGGER} a player out tonight on the NBA's injury report. Tap a cell for its "
                      "starts by day.")}

    # --- teams
    teams = {}
    for m in managers:
        rb = rosters[m]
        players = rb["players"]
        rk = by_rank[m]
        # roster extras: games played, next week's games
        extra, sched_rows = [], []
        for i, p in enumerate(players):
            per, tips = [], []
            back = next((t["text"] for t in p["tags"] if str(t["text"]).startswith("back ")), "")
            for c in sched_cols:
                if p["in_il"]:
                    n, tip = None, il_tip(c["w"], c["sub"], back)
                else:
                    n, tip = player_week_tip(av, p["name"], c["w"], c["sub"], c["days"], c["long"])
                per.append(n)
                tips.append(tip)
            nxt_n = per[1] if len(per) > 1 else None
            extra.append({"gp": str(int(p["gp"])), "next": DASH if nxt_n is None else str(nxt_n)})
            sched_rows.append({"i": i, "cells": [{"n": DASH if n is None else str(n),
                                                  "b": 0 if n is None else bucket(n, WEEK_GAME_EDGES), "tip": tip}
                                                 for n, tip in zip(per, tips)]})
        nm = lambda i: players[i]["name"]
        ord_gp = sorted(range(len(players)), key=lambda i: (-int(players[i]["gp"]), nm(i)))
        ord_next = sorted(range(len(players)),
                          key=lambda i: (-(int(extra[i]["next"]) if extra[i]["next"] != DASH else -1), nm(i)))
        sched_order = rb["orders"][rb["default_order"]]
        keep_order = rb["orders"]["keep"]
        k = kv3.line_for(ctx["keeper_watch"], m)
        keep_rank = [""] * len(players)
        for pos, i in enumerate(keep_order):
            keep_rank[i] = f"#{pos + 1}"
        keep_w = [p["keep"] if str(p["keep"]).endswith("%") else "0%" for p in players]
        injured = sum(1 for p in players if p["status"]["source"] != "healthy")
        used = len((ctx["adds"] or {}).get(m, []))
        left = max(0, budget - used)
        over = used - budget
        # moves: this team's rows of the season's feed, newest week first
        moves = []
        for w in reversed(ctx["moves"]["weeks"]):
            for j, it in enumerate(w["items"]):
                if it["who"] == m or (str(it.get("kind")) == "trade" and
                                      any(str(x["text"]).startswith(f"{m} ") for x in it["parts"])):
                    moves.append({"w": w["key"], "j": j})
        d = rk["delta_dir"]
        odds_ctx = (f"{rk['delta']} pts since the last run" if d in ("up", "down") else
                    "No change since the last run" if d == "flat" else "Change appears from the second run")
        o = opp.get(m)
        teams[m] = {
            "slot": slots[m], "mono": mono[m], "team": team_of[m], "manager": m,
            "sub": f"{m} \u00b7 {rk['record']} \u00b7 Power #{rk['rank']} \u00b7 {rk['pf']} PF",
            "record": rk["record"], "odds": rk["odds"], "injured": str(injured),
            "adds_left": str(left),
            "kpi": {
                "odds": {"label": power["label"], "value": rk["odds"], "ctx": odds_ctx,
                         "dir": d if d in ("up", "down") else "flat"},
                "win": {"label": "This week", "value": win_of.get(m, DASH),
                        "ctx": f"to beat {team_of[o]}" if o else "No matchup this week", "dir": ""},
                "pf": {"label": "Points for", "value": rk["pf"],
                       "ctx": f"#{pf_rank[m]} of {len(managers)} \u00b7 {_signed_int(float(pf_pts[m]) - avg)} "
                              "vs league avg", "dir": ""},
                "adds": {"label": "Adds left", "value": str(left),
                         "ctx": (f"{over} over the {budget} \u00b7 {reset}" if over > 0 else
                                 f"of {budget} \u00b7 {reset}"), "dir": "down" if over > 0 else ""}},
            "spark": spark[m],
            "roster": {"extra": extra, "orders": {"gp": ord_gp, "next": ord_next},
                       "keepers": list(keep_order[:k]), "keep_line": str(k), "keep_rank": keep_rank,
                       "keep_w": keep_w},
            "schedule": {"rows": [sched_rows[i] for i in sched_order]},
            "moves": moves}

    # --- this week's matchups: the pages' data
    entry = week_entry(data, week)
    rows = wh.read(base, week)
    closing = None
    cp = base / "output" / f"closing_line_week{week}.json"
    if cp.is_file():
        closing = json.loads(cp.read_text(encoding="utf-8"))
    close_cards = build_matchups(closing)["cards"] if closing else []
    line = ctx["line"]
    views = {v["id"]: v for v in ctx["matchup_views"]}
    this_tab = grid_rows["this"]
    days_hdr = [{"dow": f"{d:%a}", "day": str(d.day)} for d in this_days]
    mus = []
    for i, (c, ln) in enumerate(zip(cards, line["lines"])):
        a, b = c["a"]["manager"], c["b"]["manager"]
        if (ln["manager_a"], ln["manager_b"]) != (a, b):
            raise V2Error(f"matchup {i}: the card is {a} vs {b}, the line {ln['manager_a']} vs {ln['manager_b']}")
        pa, pb = float(ln["win_prob_a"]), float(ln["win_prob_b"])
        fav = "a" if pa > pb else "b" if pb > pa else ""
        # the card's one-line note: tonight's paragraph's first sentence, else starts left
        sv = views.get(c["views"]["sum"])
        if sv is None:
            raise V2Error(f"matchup {a} vs {b}: no Summary view {c['views']['sum']}")
        night = [p for p in sv["paras"] if str(p.get("head") or "").startswith(("Tonight's update", "Final"))]
        if night:
            note, src = first_sentence(night[0]["text"]), "night"
        else:
            note = (f"Starts left: {team_of[a]} {this_tab[a]['starts']}, {team_of[b]} {this_tab[b]['starts']}"
                    if this_days else "Every day of the week is banked.")
            src = "starts"
        # series: the same inputs the current charts draw
        has_daily = "daily_banked_a" in ln and "daily_expected_a" in ln
        if has_daily:
            banked = {a: dict(ln["daily_banked_a"]), b: dict(ln["daily_banked_b"])}
            expected = {a: dict(ln["daily_expected_a"]), b: dict(ln["daily_expected_b"])}
        else:
            from ..hub_matchups import week_flow
            fl = week_flow(data, week, date.fromisoformat(str(line["as_of"])[:10]))
            banked, expected = {m: fl["banked"][m] for m in (a, b)}, None
        try:
            wpts = hc.winprob_points(a, b, rows, closing, None)
        except hc.ChartError as e:
            raise V2Error(str(e)) from None
        win = win_series(entry, a, b, wpts, tz, team_of, mono)
        flow = flow_series(entry, a, b, banked, expected, team_of, mono)
        for m, s in ((a, "a"), (b, "b")):
            if _int(flow["series"][m]["banked"][-1]) != c[s]["now"]:
                raise V2Error(f"game flow for {m}: banked {_int(flow['series'][m]['banked'][-1])}, "
                              f"the card says {c[s]['now']}")
        # starts left by day
        srows = []
        for m in (a, b):
            r = this_tab[m]
            cells = []
            for d, x in zip(this_days, r["cells"]):
                st, maybe, nba = starters_on(av, m, d)
                foot = [f"{x['starts']} starts"]
                if maybe:
                    foot.append("if Q plays: " + ", ".join(maybe))
                if nba:
                    foot.append("out tonight: " + ", ".join(nba))
                cells.append({"n": x["starts"], "b": bucket(_lo(x["starts"]), DAY_EDGES),
                              "tip": {"h": f"{d:%a} {d.month:02d}-{d.day:02d} \u00b7 {team_of[m]}",
                                      "b": ", ".join(st) or "Nobody starts", "f": " \u00b7 ".join(foot)}})
            srows.append({"m": m, "total": r["starts"], "cells": cells})
        # who's missing: either side's players who are not healthy, in roster order
        missing = []
        for m in (a, b):
            rb = rosters[m]
            for j in rb["orders"][rb["default_order"]]:
                p = rb["players"][j]
                if p["status"]["source"] == "healthy" and not p["in_il"]:
                    continue
                kinds = [t for t in p["tags"] if t["kind"] in ("out", "q", "il")]
                if not kinds:
                    continue
                k0 = kinds[0]["kind"]
                backs = [t["text"] for t in p["tags"] if t["kind"] == k0 and str(t["text"]).startswith("back ")]
                if k0 == "il":
                    chip = "IL" + (f" \u00b7 {backs[0]}" if backs else "")
                elif k0 == "q":
                    chip = "Q"
                else:
                    chip = "Out" + (" \u00b7 " + kinds[0]["text"].split(", ", 1)[1]
                                    if ", " in kinds[0]["text"] else "")
                why = p["status"]["why"] or kinds[0]["text"]
                missing.append({"m": m, "i": j, "chip": {"text": chip, "kind": k0},
                                "sub": f"{team_of[m]} \u00b7 {why}"})
        # the lines, and how they moved since Monday's closing line
        cl = None
        for cc in close_cards:
            if {cc["a"]["manager"], cc["b"]["manager"]} == {a, b}:
                cl = cc
        lines = {"rows": [], "note": ""}
        cl_ln = None
        if closing is not None:
            for x in closing["lines"]:
                if {x["manager_a"], x["manager_b"]} == {a, b}:
                    cl_ln = x
        for lab, key_ in (("Spread", "spread"), ("Total", "total"), ("Moneyline", "moneyline")):
            now_t = c[key_]
            if cl is None:
                ctx_t = "No closing line yet"
            elif key_ == "total":
                dlt = float(ln["over_under"]) - float(cl_ln["over_under"])
                ctx_t = (f"{UP if dlt > 0 else DOWN} {_int(abs(dlt))} since the close" if dlt else
                         "Unchanged since the close")
            else:
                was = cl[key_]
                if key_ == "moneyline" and cl["a"]["manager"] != a:
                    was = " / ".join(reversed(was.split(" / ")))
                ctx_t = "Unchanged since the close" if was == now_t else f"Was {was} at the close"
            lines["rows"].append({"label": lab, "value": now_t, "ctx": ctx_t, "close": cl[key_] if cl else DASH})
        if cl is not None:
            ca = cl["a"]["win"] if cl["a"]["manager"] == a else cl["b"]["win"]
            lines["rows"].append({"label": "Win %", "value": c["a"]["win"],
                                  "ctx": f"{team_of[a]} \u00b7 was {ca} at the close", "close": ca})
            lines["note"] = ("The close is the official line, priced once after Monday's window "
                             f"({closing['closing']['window_close'][:10]}).")
        else:
            lines["note"] = "The closing line is priced once after Monday's window closes."
        mus.append({"id": f"w{week}-{i}", "a": a, "b": b, "fav": fav, "note": note, "note_src": src,
                    "views": dict(c["views"]), "win": win, "flow": flow,
                    "starts": {"days": days_hdr, "rows": srows,
                               "note": "Darker = more starts that day, of 10 lineup spots (0\u20133, 4\u20135, "
                                       "6\u20137, 8\u201310). Tap a day for who starts."},
                    "missing": missing})
        mus[-1]["lines"] = lines

    # --- last week's matchups, final, with how the closing line did (4c2)
    last = last_week(base, data, week, ctx.get("matchups_last"), team_of, mono, tz)

    # --- the issue bar
    cur = (ctx["newsletter"] or {}).get("current")
    issue = ({"text": f"Week {cur['week']} issue", "week": cur["week"], "file": cur["file"]} if cur else None)

    return {"schema": 1, "teams": teams, "team_order": order, "spark_scale": scale,
            "grid3": grid3,
            "sched_cols": [{"label": c["label"], "sub": c["sub"]} for c in sched_cols],
            "sched_note": ("Games he will play each week: not in an IL slot, not out under a tag or an "
                           "injury entry. Darker = more games (0\u20131, 2, 3, 4+)."),
            "matchups": mus, "issue": issue, "last": last, "line_text": ctx.get("line_text") or ""}


# =============================================================================
# last week (4c2; 4b decision 11)
# =============================================================================

def line_verdict(close_ln: dict, a: str, b: str, fa: int, fb: int) -> tuple:
    """(line text, verdict) for a matchup's closing line against its printed
    final scores: the spread's favourite and how it went."""
    from ..hub_state import _signed
    from ..hub_charts import pts
    sa, sb = (float(close_ln["spread_a"]), float(close_ln["spread_b"])) if close_ln["manager_a"] == a else \
        (float(close_ln["spread_b"]), float(close_ln["spread_a"]))
    wa = float(close_ln["win_prob_a"]) if close_ln["manager_a"] == a else float(close_ln["win_prob_b"])
    if sa == sb:
        return "Pick'em at the close", ("Tied" if fa == fb else f"{a if fa > fb else b} won by {pts(abs(fa - fb))}")
    fav, spread, wf = (a, sa, wa) if sa < sb else (b, sb, 100.0 - wa)
    dog = b if fav == a else a
    text = f"{fav} {_signed(spread)} \u00b7 {wf:.0f}% at the close"
    margin = (fa - fb) if fav == a else (fb - fa)
    need = -spread
    if margin > need:
        verdict = f"{fav} covered: won by {pts(margin)}"
    elif margin == need:
        verdict = f"Push: {fav} won by exactly {pts(margin)}"
    elif margin > 0:
        verdict = f"{fav} won by {pts(margin)}, short of the spread"
    elif margin == 0:
        verdict = "Tied: the favourite did not win"
    else:
        verdict = f"Upset: {dog} won by {pts(-margin)}"
    return text, verdict


def last_week(base, data, week: int, cur_last: Optional[dict], team_of: dict, mono: dict, tz) -> Optional[dict]:
    """Last week's matchups as they ended: final scores (equal to the current
    hub's, hub_matchups' last-week block: RAISES otherwise), the closing line
    and its verdict ("No closing line that week" without one), and each
    matchup's Win % and Game flow as at the end (the final point; every day
    banked). None in week 1."""
    from .. import hub_charts as hc, winprob_history as wh
    from ..hub_matchups import week_flow
    from ..week_state import week_entry
    from datetime import time as _time
    lw = int(week) - 1
    if lw < 1:
        return None
    if cur_last is None:
        raise V2Error(f"week {week}: the payload has no last-week block to match")
    e2 = week_entry(data, lw)
    end2 = date.fromisoformat(str(e2["end_date"])[:10])
    flow = week_flow(data, lw, end2 + timedelta(days=1))
    rows2 = wh.read(base, lw)
    cp = Path(base) / "output" / f"closing_line_week{lw}.json"
    close2 = json.loads(cp.read_text(encoding="utf-8")) if cp.is_file() else None
    at = datetime.combine(end2 + timedelta(days=1), _time(0), tzinfo=tz)
    cards = []
    mus = e2.get("matchups", [])
    if len(mus) != len(cur_last["cards"]):
        raise V2Error(f"week {lw}: {len(mus)} matchups, the payload's last-week block has {len(cur_last['cards'])}")
    for i, (mu, lc) in enumerate(zip(mus, cur_last["cards"])):
        a, b = mu["manager_a"], mu["manager_b"]
        fa_, fb_ = float(flow["total"][a]), float(flow["total"][b])
        if (lc["a"]["manager"], lc["b"]["manager"]) != (a, b) or hc.pts(fa_) != lc["a"]["score"] \
                or hc.pts(fb_) != lc["b"]["score"]:
            raise V2Error(f"week {lw} {a} vs {b}: {hc.pts(fa_)}\u2013{hc.pts(fb_)} here, "
                          f"{lc['a']['score']}\u2013{lc['b']['score']} in the payload's results")
        fa, fb = int(round(fa_)), int(round(fb_))
        close_ln = None
        if close2 is not None:
            for x in close2["lines"]:
                if {x["manager_a"], x["manager_b"]} == {a, b}:
                    close_ln = x
            if close_ln is None:
                raise V2Error(f"closing_line_week{lw}.json has no line for {a} vs {b}")
        if close_ln is None:
            ltext, verdict = "No closing line that week", ""
        else:
            ltext, verdict = line_verdict(close_ln, a, b, fa, fb)
        wpts = hc.winprob_points(a, b, rows2, close2, {"at": at, "a": fa_, "b": fb_})
        win = win_series(e2, a, b, wpts, tz, team_of, mono)
        fl = flow_series(e2, a, b, {a: flow["banked"][a], b: flow["banked"][b]}, None, team_of, mono)
        win_a = "100.0%" if fa > fb else "0.0%" if fa < fb else "50.0%"
        win_b = "100.0%" if fb > fa else "0.0%" if fb < fa else "50.0%"
        cards.append({"id": f"w{lw}-{i}", "a": a, "b": b, "score_a": lc["a"]["score"], "score_b": lc["b"]["score"],
                      "result": lc["result"], "line": ltext, "verdict": verdict, "views": dict(lc["views"]),
                      "win_a": win_a, "win_b": win_b, "won": "a" if fa > fb else "b" if fb > fa else "",
                      "win": win, "flow": fl})
    return {"week": lw, "title": cur_last["title"], "cards": cards,
            "note": ("How last week ended, and how Monday's closing line did: the favourite by the spread, "
                     "against the final scores. Tap a matchup for its charts at the end.")}
