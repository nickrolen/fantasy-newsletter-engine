"""
games_grid.py -- C5, the week-ahead games grid.

The largest measured inefficiency in the league is not the draft, it is the
daily lineup: the fill-rate gap between the best and worst manager is about
3,300 points a season, roughly ten times every draft-strategy difference
measured. Nick had fewer than 10 players with a game on 102 of 157 days.

schedule_strength.py already simulates every manager's daily lineup for the
coming week. This module only lays it out: one row per manager, one column
per day, the number who start, and -- the point of it -- the holes.

The signal is the two leading columns, not the day cells. STARTS is the week's
simulated started games; FILLABLE is how many empty slots a healthy free
agent with a game that night could fill (exact matching of open seats to
positions, count_fillable in schedule_strength). In a four-team league the
wire is deep and Util seats are open most nights, so nearly every hole is
fillable and per-day shading is near-uniform -- but a week like Garrett
50/20 against Benton 39/31 separates the league at a glance. Rows sort by
STARTS; the day cells stay muted, as the detail behind the totals.

There is no streamer board, deliberately. One was built and cut before
week 1: per manager it collapsed into identical pairs, and scored against
all four rosters it came out near-uniform too (every row 4/4/4/4 or close).
That is not a display problem. It is the same fact the near-uniform day
shading showed: in a four-team league with a ~175-deep free-agent pool,
availability is not scarce -- fit is. "Who plays most this week" is the
same answer for everyone. The personalised question is what an add is worth
to THIS roster after the drop, which is C2, built on marginal_value (C1).

Numbers are rendered from the stats report JSON straight into the HTML, never
through the drafting chat, so they cannot be retyped wrong.

Caveats the grid states on its face:
  - As of the report run. Rosters change after it.
  - Injuries are INJURY_OVERRIDES only, the same input the betting lines use.
  - Free agents are PLAYERLIST's top ~175, so "fillable" can undercount.
"""

from __future__ import annotations

import html
from datetime import date, timedelta
from typing import Optional

STARTING_SLOTS = 10
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def build_grid(stats_report: dict) -> Optional[dict]:
    """The grid for the week the report previews, or None if it has no data."""
    upcoming = ((stats_report or {}).get("schedule_strength") or {}).get("upcoming_week") or {}
    managers = upcoming.get("managers")
    if not managers or not upcoming.get("start_date"):
        return None

    start = date.fromisoformat(upcoming["start_date"])
    end = date.fromisoformat(upcoming["end_date"])
    games_by_day = upcoming.get("nba_games_by_day") or {}
    has_fa = upcoming.get("free_agent_pool_size") is not None

    days = []
    d = start
    while d <= end:
        iso = d.isoformat()
        days.append({
            "date": iso,
            "label": f"{_WEEKDAYS[d.weekday()]} {d.month}/{d.day}",
            "nba_games": games_by_day.get(iso),
        })
        d += timedelta(days=1)

    rows = []
    for mgr, md in managers.items():
        by_date = {x["date"]: x for x in md.get("daily_detail", [])}
        cells, holes_total, fillable_total, overflow_total = [], 0, 0, 0
        for day in days:
            x = by_date.get(day["date"])
            if x is None or day["nba_games"] == 0:
                cells.append({"date": day["date"], "off": True})
                continue
            started = int(x.get("started", 0))
            holes = max(0, STARTING_SLOTS - started)
            fillable = x.get("fillable")
            overflow = int(x.get("benched", 0))
            holes_total += holes
            overflow_total += overflow
            if fillable is not None:
                fillable_total += int(fillable)
            cells.append({
                "date": day["date"],
                "off": False,
                "started": started,
                "holes": holes,
                "open_slots": list(x.get("open_slots", [])),
                "fillable": fillable,
                "overflow": overflow,
                "overflow_players": list(x.get("benched_players", [])),
                "injured_with_game": int(x.get("injured_with_game", 0)),
            })
        rows.append({
            "manager": mgr,
            "cells": cells,
            "startable": int(md.get("startable_games", 0)),
            "holes": holes_total,
            "fillable": fillable_total if has_fa else None,
            "overflow": overflow_total,
            "unmatched_players": list(md.get("unmatched_players", [])),
        })
    rows.sort(key=lambda r: (-r["startable"], r["manager"]))

    return {
        "week": upcoming.get("week"),
        "days": days,
        "rows": rows,
        "has_free_agents": has_fa,
        "from_lineups": list(upcoming.get("player_info_from_lineups") or []),
    }


def _cell_text(c: dict) -> str:
    if c["off"]:
        return "-"
    text = str(c["started"])
    if c["fillable"]:
        slots = ",".join(c["open_slots"][: c["holes"]])
        text += f" ({c['fillable']} fillable: {slots})"
    elif c["holes"]:
        text += f" ({c['holes']} open)"
    if c["overflow"]:
        text += f" +{c['overflow']} bench"
    return text


def render_markdown(stats_report: dict) -> str:
    """Section 3 reference table for the drafting chat."""
    grid = build_grid(stats_report)
    if grid is None:
        return ""
    head = ["Manager", "Starts", "Fillable holes"] + [d["label"] for d in grid["days"]]
    lines = [
        f"**Week {grid['week']} Games Grid** (rows sorted by Starts. Rendered "
        "automatically in the HTML -- do NOT reproduce it. You may cite a "
        "manager's Starts and Fillable holes in a preview.)",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "|".join(["---"] * len(head)) + "|",
        "| NBA games | | | " + " | ".join(
            "-" if d["nba_games"] is None else str(d["nba_games"]) for d in grid["days"]
        ) + " |",
    ]
    for r in grid["rows"]:
        fill = "?" if r["fillable"] is None else str(r["fillable"])
        lines.append("| " + " | ".join(
            [r["manager"], str(r["startable"]), fill]
            + [_cell_text(c) for c in r["cells"]]) + " |")
    unmatched = sorted({p for r in grid["rows"] for p in r["unmatched_players"]})
    if unmatched:
        lines.append("")
        lines.append(f"- Not in PLAYERLIST or LINEUPS, so not counted: {', '.join(unmatched)}")
    return "\n".join(lines) + "\n"


def render_html(stats_report: dict) -> str:
    """The grid as an HTML block for the Betting Lines section."""
    grid = build_grid(stats_report)
    if grid is None:
        return ""
    e = html.escape
    top_starts = max((r["startable"] for r in grid["rows"]), default=0)

    out = ['<div class="games-grid" data-viz="games-grid">',
           f'<div class="gg-title">Week {e(str(grid["week"]))} Games Grid</div>',
           '<div class="gg-sub"><b>Starts</b>: simulated started games this week. '
           '<b>Fillable</b>: empty slots a free agent with a game that night '
           'could fill. Daily starters out of 10 to the right.</div>',
           '<div class="gg-scroll"><table class="gg-table"><thead><tr>'
           '<th class="gg-mgr-h">Manager</th><th class="gg-key">Starts</th>'
           '<th class="gg-key">Fillable</th>']
    for d in grid["days"]:
        n = d["nba_games"]
        sub = "" if n is None else f'<span class="gg-nba">{n} NBA</span>'
        out.append(f'<th class="gg-day-h">{e(d["label"])}{sub}</th>')
    out.append('</tr></thead><tbody>')

    for r in grid["rows"]:
        fill = "?" if r["fillable"] is None else str(r["fillable"])
        s_cls = "gg-key gg-top" if r["startable"] == top_starts else "gg-key"
        f_cls = "gg-key"  # most fillable = most room, not "best": no marker
        out.append(f'<tr><th class="gg-mgr">{e(r["manager"])}</th>'
                   f'<td class="{s_cls}">{r["startable"]}</td>'
                   f'<td class="{f_cls}">{fill}</td>')
        for c in r["cells"]:
            if c["off"]:
                out.append('<td class="gg-day gg-off">-</td>')
                continue
            notes, tip = [], []
            if c["fillable"]:
                notes.append(f'{c["fillable"]} fillable')
                tip.append("Open: " + ", ".join(c["open_slots"][: c["holes"]]))
            elif c["holes"]:
                notes.append(f'{c["holes"]} open')
                tip.append("No free agent with a game fits the open slots")
            if c["overflow"]:
                notes.append(f'+{c["overflow"]} bench')
                tip.append("Benched with a game: " + ", ".join(c["overflow_players"]))
            if c["injured_with_game"]:
                tip.append(f'{c["injured_with_game"]} injured with a game')
            note_html = f'<span class="gg-note">{e(" / ".join(notes))}</span>' if notes else ""
            title = f' title="{e("; ".join(tip))}"' if tip else ""
            full = " gg-full" if c["holes"] == 0 else ""
            out.append(f'<td class="gg-day{full}"{title}>'
                       f'<span class="gg-n">{c["started"]}</span>{note_html}</td>')
        out.append('</tr>')
    out.append('</tbody></table></div>')

    foot = ["As of report time; rosters change after it. Injuries from "
            "INJURY_OVERRIDES only. Free agents are Yahoo's top ~175. Three "
            "adds a week."]
    unmatched = sorted({p for r in grid["rows"] for p in r["unmatched_players"]})
    if unmatched:
        foot.append("Not counted (no team on file): " + ", ".join(unmatched) + ".")
    out.append(f'<div class="gg-foot">{e(" ".join(foot))}</div></div>')
    return "\n".join(out)


def get_css() -> str:
    """Styles for render_html. Plain CSS -- no f-string braces to escape."""
    return """
        .games-grid { margin: 0 0 28px; }
        .games-grid .gg-title { font-weight: 700; font-size: 1.05em; color: var(--primary-blue); }
        .games-grid .gg-sub, .games-grid .gg-foot { font-size: 0.82em; color: var(--text-secondary, #666); margin: 4px 0 10px; }
        .games-grid .gg-foot { margin-top: 8px; }
        .games-grid .gg-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        .games-grid .gg-table { border-collapse: collapse; width: 100%; min-width: 600px; font-variant-numeric: tabular-nums; }
        .games-grid th, .games-grid td { border: 1px solid var(--border-color, #ddd); padding: 6px; text-align: center; vertical-align: middle; }
        .games-grid thead th { font-size: 0.8em; font-weight: 600; background: var(--primary-blue); color: #fff; white-space: nowrap; }
        .games-grid thead th.gg-day-h { opacity: 0.85; font-weight: 500; }
        .games-grid .gg-nba { display: block; font-weight: 400; font-size: 0.85em; opacity: 0.85; }
        .games-grid .gg-mgr { text-align: left; font-weight: 600; background: var(--light-gray); white-space: nowrap; }
        .games-grid td.gg-key { font-size: 1.35em; font-weight: 700; background: var(--light-gray); }
        .games-grid td.gg-top { color: var(--primary-blue); box-shadow: inset 0 -3px 0 var(--accent-gold); }
        .games-grid .gg-day { color: var(--text-secondary, #777); }
        .games-grid .gg-day .gg-n { font-weight: 500; }
        .games-grid .gg-day.gg-full .gg-n { color: var(--text-primary, #222); font-weight: 700; }
        .games-grid .gg-n { display: block; font-size: 0.98em; }
        .games-grid .gg-note { display: block; font-size: 0.7em; white-space: nowrap; color: var(--text-secondary, #777); }
        .games-grid .gg-off { color: var(--text-secondary, #aaa); }
    """
