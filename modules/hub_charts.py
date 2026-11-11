"""
hub_charts.py -- every chart on the hub, as geometry strings (hub polish 3,
tasks 48b, 48c, 48d; Nick, 11-10).

THE PAGE COMPUTES NOTHING (hub_page's rule): each chart here is a dict of
strings -- the SVG viewBox, every path's "d", every marker's centre, every
label's position and text, every tap target's rectangle and the text it
shows -- and hub_page prints them as they are. No library, nothing external:
inline SVG, so the hub still works offline once decrypted.

A chart:
    {"vb": "0 0 W H", "aria": what it shows, "tip0": the caption before a tap,
     "grid":  [{"x1","y1","x2","y2","cls"}]                 axis and guide lines
     "texts": [{"x","y","t","anchor","cls","fill"}]         labels
     "paths": [{"d","stroke","dash","w"}]                   series lines
     "dots":  [{"cx","cy","r","fill"}]                      observed points
     "hits":  [{"x","y","w","h","tip"}]                     tap targets
     "note":  a line under it}

COLOURS: one per manager (MANAGER_COLOURS), the same in every chart -- the
win-% and game-flow charts use the two teams' own. Each is at least 3:1
against the card (#FFFFFF), the WCAG non-text contrast for a graph line, and
every line is also labelled with the manager's name, so colour is never the
only signal (tests/test_hub.py's WCAG test pins the ratios).

Charts:
    title_odds_chart   48d: the four managers' REGULAR-SEASON title odds
                       (title_odds; Nick, 11-10: "the title" always means the
                       regular season), one point per league day -- that day's
                       last row of output/title_odds_history.jsonl, and before
                       the history began, each published stats report placed
                       at the date its data describe (the Monday after its
                       week, from the schedule; Nick, 11-10). x is weeks 1-23
                       of the schedule, a tick per day; markers at week 16 (the
                       playoffs) and week 22 (the Cup). No interpolation.
    winprob_chart      48b: team A's win % through a week, one point per
                       priced live-lines run (modules/winprob_history), the
                       closing line at the window close, and the final
                       (100/0, 50/50 on a tie) once every day is banked.
    gameflow_chart     48c: each team's points added up by league day (solid)
                       and, from the last banked day, the same pricing run's
                       expected points per remaining day (dashed).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

MINUS = "\u2212"

# One colour per manager, every chart (48d). >= 3:1 against #FFFFFF (pinned).
MANAGER_COLOURS = {"Nick": "#1D5FD1", "Hayden": "#B4560C", "Benton": "#7B2FD0", "Garrett": "#0F7B3F"}
CARD = "#FFFFFF"


class ChartError(RuntimeError):
    """A chart's input is missing or inconsistent; the input is named."""


def colour_of(manager: str) -> str:
    c = MANAGER_COLOURS.get(manager)
    if c is None:
        raise ChartError(f"no chart colour for manager {manager!r}: add one to hub_charts.MANAGER_COLOURS")
    return c


# =============================================================================
# formatting
# =============================================================================

def n(x: float) -> str:
    """A coordinate: one decimal, no trailing zero."""
    s = f"{float(x):.1f}"
    return s[:-2] if s.endswith(".0") else s


def pct(x: float) -> str:
    return f"{float(x):.1f}%"


def pts(x: float) -> str:
    return f"{float(x):,.0f}"


def signed(x: float, nd: int = 1) -> str:
    v = round(float(x), nd)
    s = f"{abs(v):,.{nd}f}"
    return ("+" + s) if v > 0 else (MINUS + s) if v < 0 else s


def day_label(d: date) -> str:
    return f"{d:%a} {d.month:02d}-{d.day:02d}"


def clock(dt: datetime) -> str:
    h = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt:%a} {dt.month:02d}-{dt.day:02d}, {h}:{dt:%M} {dt:%p}"


class Frame:
    """A plot area [x0, x1] x [y0, y1] in viewBox pixels over the domain
    [t0, t1] x [v0, v1]; y grows downwards."""

    def __init__(self, x0, x1, y0, y1, t0, t1, v0, v1):
        if t1 <= t0 or v1 <= v0:
            raise ChartError("an empty chart domain")
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.t0, self.t1, self.v0, self.v1 = t0, t1, v0, v1

    def X(self, t) -> float:
        return self.x0 + (self.x1 - self.x0) * (t - self.t0) / (self.t1 - self.t0)

    def Y(self, v) -> float:
        return self.y1 - (self.y1 - self.y0) * (v - self.v0) / (self.v1 - self.v0)


def _path(points) -> str:
    return " ".join(("M" if i == 0 else "L") + f"{n(x)} {n(y)}" for i, (x, y) in enumerate(points))


def _spread_labels(ys: List[float], gap: float, lo: float, hi: float) -> List[float]:
    """End labels' y, moved apart to at least `gap`, kept inside [lo, hi],
    in the given order's ranks (smallest y first)."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    prev = None
    for i in order:
        y = max(out[i], lo)
        if prev is not None and y < prev + gap:
            y = prev + gap
        out[i] = y
        prev = y
    over = (prev or lo) - hi
    if over > 0:
        for i in order:
            out[i] -= over
    return out


def _empty(vb: str, aria: str, tip0: str, note: str) -> dict:
    return {"vb": vb, "aria": aria, "tip0": tip0, "grid": [], "texts": [], "paths": [], "dots": [],
            "hits": [], "note": note}


# =============================================================================
# 48d. title odds over the season
# =============================================================================

TITLE_W, TITLE_H = 340, 230


def _league_day(as_of: str) -> date:
    """The league day of a row's as_of (stored with its Pacific offset)."""
    return datetime.fromisoformat(as_of).date()


def title_points(history_rows: list, reports: list, schedule: dict, key: str = "title_odds") -> dict:
    """{league day: {"values": {manager: odds}, "source": text}}: one point
    per league day. A day with history rows takes its LAST row (by as_of).
    Before the history's first day, a published stats report fills its day:
    the day its data describe, the Monday after its week (the first day of
    week N+1 in the schedule; Nick, 11-10). RAISES when a report's week or
    that Monday cannot be determined, or a report is not a published one."""
    weeks = {int(w["week"]): date.fromisoformat(str(w["start_date"])[:10]) for w in schedule.get("weeks", [])}
    out: Dict[date, dict] = {}
    rows = sorted((r for r in history_rows if r.get(key)), key=lambda r: r["as_of"])
    for r in rows:                                            # the day's last row wins
        out[_league_day(r["as_of"])] = {"values": {m: float(v) for m, v in r[key].items()},
                                        "source": f"{(r.get('kind') or 'run')} run"}
    first_hist = min(out) if out else None
    for rep in reports:
        meta = rep.get("metadata") or {}
        wk = meta.get("week")
        if wk is None:
            raise ChartError("a stats report has no metadata.week: the date its odds describe "
                             "cannot be determined")
        if meta.get("run_mode") != "publish":
            raise ChartError(f"stats_report_week{wk}.json is not a published report "
                             f"(run_mode {meta.get('run_mode')!r}): its odds are not a published point")
        day = weeks.get(int(wk) + 1)
        if day is None:
            raise ChartError(f"stats_report_week{wk}.json: week {int(wk) + 1} is not in "
                             "config/SCHEDULE.json, so the Monday its odds describe is unknown")
        if first_hist is not None and day >= first_hist:
            continue                                          # the history covers it
        vals = {p["manager"]: float(p[key]) for p in rep.get("power_rankings") or [] if key in p}
        if not vals:
            raise ChartError(f"stats_report_week{wk}.json has no {key} in its power rankings")
        out[day] = {"values": vals, "source": f"the published week-{wk} report"}
    return dict(sorted(out.items()))


def title_odds_chart(points: dict, schedule: dict, managers: list, *, playoff_week: int, cup_week: int,
                     label: str = "Title odds") -> dict:
    """48d: one line per manager over weeks 1..last of the schedule."""
    wks = sorted(schedule.get("weeks", []), key=lambda w: int(w["week"]))
    if not wks:
        raise ChartError("config/SCHEDULE.json has no weeks")
    start = date.fromisoformat(str(wks[0]["start_date"])[:10])
    end = date.fromisoformat(str(wks[-1]["end_date"])[:10])
    ndays = (end - start).days + 1
    vb = f"0 0 {TITLE_W} {TITLE_H}"
    f = Frame(30, 262, 14, TITLE_H - 34, 0, ndays, 0, 100)

    def xd(d: date) -> float:                                 # a day's centre
        return f.X((d - start).days + 0.5)

    grid, texts = [], []
    for v in (0, 25, 50, 75, 100):
        grid.append({"x1": n(f.x0), "y1": n(f.Y(v)), "x2": n(f.x1), "y2": n(f.Y(v)),
                     "cls": "g-mid" if v == 50 else "g-line"})
        texts.append({"x": n(f.x0 - 4), "y": n(f.Y(v) + 3), "t": f"{v}%", "anchor": "end", "cls": "ax",
                      "fill": ""})
    for i in range(ndays + 1):                                # a tick per day
        grid.append({"x1": n(f.X(i)), "y1": n(f.y1), "x2": n(f.X(i)), "y2": n(f.y1 + 3), "cls": "g-tick"})
    for w in wks:
        a = date.fromisoformat(str(w["start_date"])[:10])
        b = date.fromisoformat(str(w["end_date"])[:10])
        mid = f.X(((a - start).days + (b - start).days + 1) / 2)
        if int(w["week"]) % 2 == 1 or w is wks[-1]:          # odd weeks: 23 labels do not fit 360 px
            texts.append({"x": n(mid), "y": n(f.y1 + 13), "t": str(int(w["week"])), "anchor": "middle",
                          "cls": "ax", "fill": ""})
        grid.append({"x1": n(f.X((a - start).days)), "y1": n(f.y1), "x2": n(f.X((a - start).days)),
                     "y2": n(f.y1 + 6), "cls": "g-week"})
    texts.append({"x": n((f.x0 + f.x1) / 2), "y": n(f.y1 + 27), "t": "Week", "anchor": "middle",
                  "cls": "ax", "fill": ""})
    for wk, name in ((playoff_week, "Playoffs"), (cup_week, "Cup")):
        hit = [w for w in wks if int(w["week"]) == int(wk)]
        if not hit:
            raise ChartError(f"week {wk} ({name}) is not in config/SCHEDULE.json")
        x = f.X((date.fromisoformat(str(hit[0]["start_date"])[:10]) - start).days)
        grid.append({"x1": n(x), "y1": n(f.y0), "x2": n(x), "y2": n(f.y1), "cls": "g-mark"})
        texts.append({"x": n(x + 2), "y": n(f.y0 + 8), "t": name, "anchor": "start", "cls": "ax-mark",
                      "fill": ""})

    days = [d for d in points if start <= d <= end]
    if not days:
        out = _empty(vb, f"{label} over the season: no points yet", "No title-odds run yet.",
                     "Points appear from the first run.")
        out.update(grid=grid, texts=texts)
        return out
    paths, dots, ends = [], [], []
    for m in managers:
        ps = [(xd(d), f.Y(points[d]["values"][m])) for d in days if m in points[d]["values"]]
        if not ps:
            raise ChartError(f"no {label.lower()} point for {m}")
        c = colour_of(m)
        paths.append({"d": _path(ps), "stroke": c, "dash": "", "w": "1.6"})
        dots += [{"cx": n(x), "cy": n(y), "r": "1.6", "fill": c} for x, y in ps]
        last = max(d for d in days if m in points[d]["values"])
        ends.append((m, xd(last), f.Y(points[last]["values"][m]), points[last]["values"][m]))
    ly = _spread_labels([e[2] for e in ends], 11, f.y0 + 4, f.y1 - 2)
    for (m, x, _y, v), y in zip(ends, ly):
        texts.append({"x": n(x + 5), "y": n(y + 3), "t": f"{m} {pct(v)}", "anchor": "start",
                      "cls": "lab", "fill": colour_of(m)})
    hits = []
    xs = [xd(d) for d in days]
    for i, d in enumerate(days):
        left = f.x0 if i == 0 else (xs[i - 1] + xs[i]) / 2
        right = f.x1 if i == len(days) - 1 else (xs[i] + xs[i + 1]) / 2
        vals = points[d]["values"]
        order = sorted(vals, key=lambda m: (-vals[m], m))
        tip = (f"{day_label(d)}: " + ", ".join(f"{m} {pct(vals[m])}" for m in order)
               + f" ({points[d]['source']})")
        hits.append({"x": n(left), "y": n(f.y0), "w": n(max(right - left, 0.5)), "h": n(f.y1 - f.y0),
                     "tip": tip})
    tip0 = "Tap a day for all four. Latest: " + hits[-1]["tip"]
    note = (f"{label}: each manager's chance to win the regular-season title (the power column's "
            "title odds), one point per day: that day's last run.")
    if any("report" in points[d]["source"] for d in days):
        note += (" Before the nightly runs began, each published report's odds sit on the Monday its "
                 "data describe.")
    note += (" Nothing is filled in between points. The regular season ends after week 15, so the lines "
             "go flat from week 16; the axis runs to week 23.")
    return {"vb": vb, "aria": f"{label}, one line per manager, weeks 1 to {int(wks[-1]['week'])}",
            "tip0": tip0, "grid": grid, "texts": texts, "paths": paths, "dots": dots, "hits": hits,
            "note": note}


# =============================================================================
# 48b. win % over the week
# =============================================================================

WEEK_W, WEEK_H = 340, 200
WEEK_X1 = 236                       # the plot's right edge: room for "Garrett 1,753 exp." after it


def _week_bounds(entry: dict, tz) -> tuple:
    a = date.fromisoformat(str(entry["start_date"])[:10])
    b = date.fromisoformat(str(entry["end_date"])[:10])
    t0 = datetime.combine(a, time(0), tzinfo=tz)
    t1 = datetime.combine(b + timedelta(days=1), time(0), tzinfo=tz)
    days = [a + timedelta(days=i) for i in range((b - a).days + 1)]
    return t0, t1, days


def _day_axis(f: Frame, days: list, t0: datetime, grid: list, texts: list) -> None:
    for i, d in enumerate(days):
        x = f.X((datetime.combine(d, time(0), tzinfo=t0.tzinfo) - t0).total_seconds())
        grid.append({"x1": n(x), "y1": n(f.y0), "x2": n(x), "y2": n(f.y1), "cls": "g-day"})
        xm = f.X((datetime.combine(d, time(12), tzinfo=t0.tzinfo) - t0).total_seconds())
        texts.append({"x": n(xm), "y": n(f.y1 + 12), "t": f"{d:%a}"[0], "anchor": "middle", "cls": "ax",
                      "fill": ""})
        texts.append({"x": n(xm), "y": n(f.y1 + 22), "t": str(d.day), "anchor": "middle", "cls": "ax",
                      "fill": ""})


def winprob_points(a: str, b: str, rows: list, closing: Optional[dict], final: Optional[dict]) -> list:
    """[(datetime, win % a, win % b, label)], time order. rows: the week's
    win-% history; closing: closing_line_weekN.json or None; final: {"at":
    datetime, "a": points, "b": points} once every day is banked, else None.
    RAISES when a row or the closing line has no line for this matchup."""
    def pick(lines, where):
        for ln in lines:
            if (ln["manager_a"], ln["manager_b"]) == (a, b):
                return float(ln["win_prob_a"]), float(ln["win_prob_b"])
            if (ln["manager_a"], ln["manager_b"]) == (b, a):
                return float(ln["win_prob_b"]), float(ln["win_prob_a"])
        raise ChartError(f"{where} has no line for {a} vs {b}")
    from .winprob_history import label
    out = []
    for r in rows:
        pa, pb = pick(r["matchups"], f"win-% row {r['run_id']}")
        out.append((datetime.fromisoformat(r["as_of"]), pa, pb, label(r)))
    if closing is not None:
        pa, pb = pick(closing["lines"], f"closing_line_week{closing['week']}.json")
        out.append((datetime.fromisoformat(closing["closing"]["window_close"]), pa, pb, "the closing line"))
    out.sort(key=lambda x: x[0])
    if final is not None:
        fa, fb = float(final["a"]), float(final["b"])
        pa = 100.0 if fa > fb else 0.0 if fa < fb else 50.0
        out.append((final["at"], pa, 100.0 - pa, "final"))
    return out


def winprob_chart(entry: dict, a: str, b: str, points: list, tz) -> dict:
    t0, t1, days = _week_bounds(entry, tz)
    vb = f"0 0 {WEEK_W} {WEEK_H}"
    f = Frame(30, WEEK_X1, 12, WEEK_H - 30, 0, (t1 - t0).total_seconds(), 0, 100)
    grid, texts = [], []
    for v in (0, 25, 50, 75, 100):
        grid.append({"x1": n(f.x0), "y1": n(f.Y(v)), "x2": n(f.x1), "y2": n(f.Y(v)),
                     "cls": "g-mid" if v == 50 else "g-line"})
        texts.append({"x": n(f.x0 - 4), "y": n(f.Y(v) + 3), "t": f"{v}%", "anchor": "end", "cls": "ax", "fill": ""})
    _day_axis(f, days, t0, grid, texts)
    ca, cb = colour_of(a), colour_of(b)
    if not points:
        out = _empty(vb, f"{a}'s win % against {b}: no priced run yet", "No priced run yet this week.",
                     "A point appears with each priced line.")
        out.update(grid=grid, texts=texts)
        return out

    def X(dt):
        s = (dt - t0).total_seconds()
        return f.X(min(max(s, 0.0), f.t1))
    ps = [(X(dt), f.Y(pa)) for dt, pa, _pb, _l in points]
    paths = [{"d": _path(ps), "stroke": ca, "dash": "", "w": "2"}]
    dots = [{"cx": n(x), "cy": n(y), "r": "3", "fill": ca} for x, y in ps]
    last = points[-1]
    ly = _spread_labels([f.Y(last[1]), f.Y(last[2])], 12, f.y0 + 4, f.y1 - 2)
    texts.append({"x": n(ps[-1][0] + 6), "y": n(ly[0] + 4), "t": f"{a} {pct(last[1])}", "anchor": "start",
                  "cls": "lab", "fill": ca})
    texts.append({"x": n(ps[-1][0] + 6), "y": n(ly[1] + 4), "t": f"{b} {pct(last[2])}", "anchor": "start",
                  "cls": "lab", "fill": cb})
    hits = []
    for (dt, pa, pb, lab), (x, y) in zip(points, ps):
        when = "Final" if lab == "final" else f"{clock(dt)} ({lab})"
        hits.append({"x": n(x - 9), "y": n(y - 9), "w": "18", "h": "18",
                     "tip": f"{when}: {a} {pct(pa)}, {b} {pct(pb)}"})
    return {"vb": vb, "aria": f"{a}'s win % against {b} through the week ({b}'s is its mirror)",
            "tip0": "Tap a point. Latest: " + hits[-1]["tip"], "grid": grid, "texts": texts,
            "paths": paths, "dots": dots, "hits": hits,
            "note": (f"{a}'s chance to win, one point per priced line: the nightly run, Monday's pre-tip "
                     f"runs and any forced run, plus the closing line at the window close and the final "
                     f"once every day is banked. {b}'s is the rest of 100%. Gaps between points are "
                     "nights the line did not change.")}


# =============================================================================
# 48c. game flow
# =============================================================================

def gameflow_chart(entry: dict, a: str, b: str, banked: dict, expected: Optional[dict]) -> dict:
    """banked: {manager: {iso day: points}} for the banked days, in order;
    expected: {manager: {iso day: expected points}} for the remaining days
    (the same pricing run), or None when the line carries none. Cumulative
    points at the end of each league day; solid through the last banked day,
    dashed from there to the last game day."""
    a0 = date.fromisoformat(str(entry["start_date"])[:10])
    b0 = date.fromisoformat(str(entry["end_date"])[:10])
    days = [a0 + timedelta(days=i) for i in range((b0 - a0).days + 1)]
    iso = [d.isoformat() for d in days]
    for m in (a, b):
        extra = set(banked.get(m) or {}) | set((expected or {}).get(m) or {})
        if not extra <= set(iso):
            raise ChartError(f"game flow for week {entry['week']}: days outside the week for {m}: "
                             f"{sorted(extra - set(iso))}")
    nb = len(banked.get(a) or {})
    if set((banked.get(a) or {})) != set(iso[:nb]) or set((banked.get(b) or {})) != set(iso[:nb]):
        raise ChartError(f"game flow for week {entry['week']}: the banked days are not the week's first {nb}")
    cum = {}
    for m in (a, b):
        run, seq = 0.0, [0.0]
        for d in iso[:nb]:
            run += float(banked[m][d])
            seq.append(run)
        exp_seq = None
        if expected is not None and nb < len(iso):
            e = expected.get(m) or {}
            if set(e) != set(iso[nb:]):
                raise ChartError(f"game flow for week {entry['week']}: the expected days for {m} are "
                                 f"{sorted(e)}, not the remaining {iso[nb:]}")
            exp_seq, r2 = [run], run
            for d in iso[nb:]:
                r2 += float(e[d])
                exp_seq.append(r2)
        cum[m] = (seq, exp_seq)
    top = max([v for m in (a, b) for v in cum[m][0] + (cum[m][1] or [])] + [1.0])
    step = 500 if top > 1000 else 250 if top > 400 else 100
    vmax = step * int(-(-top // step))
    vb = f"0 0 {WEEK_W} {WEEK_H}"
    f = Frame(34, WEEK_X1, 12, WEEK_H - 30, 0, len(days), 0, vmax)
    grid, texts = [], []
    v = 0
    while v <= vmax:
        grid.append({"x1": n(f.x0), "y1": n(f.Y(v)), "x2": n(f.x1), "y2": n(f.Y(v)), "cls": "g-line"})
        texts.append({"x": n(f.x0 - 4), "y": n(f.Y(v) + 3), "t": pts(v), "anchor": "end", "cls": "ax", "fill": ""})
        v += step
    for i, d in enumerate(days):
        grid.append({"x1": n(f.X(i)), "y1": n(f.y0), "x2": n(f.X(i)), "y2": n(f.y1), "cls": "g-day"})
        texts.append({"x": n(f.X(i + 0.5)), "y": n(f.y1 + 12), "t": f"{d:%a}"[0], "anchor": "middle",
                      "cls": "ax", "fill": ""})
        texts.append({"x": n(f.X(i + 0.5)), "y": n(f.y1 + 22), "t": str(d.day), "anchor": "middle",
                      "cls": "ax", "fill": ""})
    paths, dots, ends = [], [], []
    for m in (a, b):
        c = colour_of(m)
        seq, exp_seq = cum[m]
        solid = [(f.X(i), f.Y(v)) for i, v in enumerate(seq)]
        paths.append({"d": _path(solid), "stroke": c, "dash": "", "w": "2"})
        dots += [{"cx": n(x), "cy": n(y), "r": "2.5", "fill": c} for x, y in solid[1:]]
        if exp_seq is not None:
            dash = [(f.X(nb + i), f.Y(v)) for i, v in enumerate(exp_seq)]
            paths.append({"d": _path(dash), "stroke": c, "dash": "4 3", "w": "2"})
            ends.append((m, dash[-1][0], dash[-1][1], exp_seq[-1], "expected"))
        else:
            ends.append((m, solid[-1][0], solid[-1][1], seq[-1], "final" if nb == len(iso) else "so far"))
    ly = _spread_labels([e[2] for e in ends], 12, f.y0 + 4, f.y1 - 2)
    for (m, x, _y, v, kind), y in zip(ends, ly):
        texts.append({"x": n(x + 6), "y": n(y + 4), "t": f"{m} {pts(v)}" + (" exp." if kind == "expected" else ""),
                      "anchor": "start", "cls": "lab", "fill": colour_of(m)})
    if nb:
        ma, mb = cum[a][0][-1], cum[b][0][-1]
        lead = a if ma > mb else b if mb > ma else None
        txt = f"{lead} +{pts(abs(round(ma) - round(mb)))}" if lead else "Tied"   # of the printed totals
        grid.append({"x1": n(f.X(nb)), "y1": n(f.y0), "x2": n(f.X(nb)), "y2": n(f.y1), "cls": "g-now"})
        left = nb > len(days) / 2                            # the open side of the line
        texts.append({"x": n(f.X(nb) + (-3 if left else 3)), "y": n(f.y0 + 9), "t": txt,
                      "anchor": "end" if left else "start", "cls": "lab", "fill": ""})
    hits = []
    for i, d in enumerate(days):
        if i < nb:
            tip = (f"Through {day_label(d)}: {a} {pts(cum[a][0][i + 1])} ({pts(banked[a][iso[i]])} that day), "
                   f"{b} {pts(cum[b][0][i + 1])} ({pts(banked[b][iso[i]])})")
        elif cum[a][1] is not None:
            j = i - nb + 1
            tip = (f"Expected through {day_label(d)}: {a} {pts(cum[a][1][j])}, {b} {pts(cum[b][1][j])}")
        else:
            tip = f"{day_label(d)}: not played yet"
        hits.append({"x": n(f.X(i)), "y": n(f.y0), "w": n(f.X(i + 1) - f.X(i)), "h": n(f.y1 - f.y0), "tip": tip})
    note = ("Points added up by day: solid lines are banked points, dashed lines the same pricing run's "
            "expected points for each remaining day, ending at the line's projected finals.")
    if expected is None and nb < len(iso):
        note += " The expected days appear once the line is next priced."
    tip0 = "Tap a day. " + (hits[nb - 1]["tip"] if nb else hits[0]["tip"])
    return {"vb": vb, "aria": f"{a} and {b}'s points added up by day", "tip0": tip0, "grid": grid,
            "texts": texts, "paths": paths, "dots": dots, "hits": hits, "note": note,
            "_ends": {m: (cum[m][1][-1] if cum[m][1] is not None else cum[m][0][-1]) for m in (a, b)},
            "_banked": {m: cum[m][0][-1] for m in (a, b)}}
