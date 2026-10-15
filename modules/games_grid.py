"""
games_grid.py -- C5, the week-ahead games grid.

The largest measured inefficiency in the league is not the draft, it is the
daily lineup: the fill-rate gap between the best and worst manager is about
3,300 points a season, roughly ten times every draft-strategy difference
measured. Nick had fewer than 10 players with a game on 102 of 157 days.

schedule_strength.py already simulates every manager's daily lineup for the
coming week. This module only lays it out: one row per manager, one column
per day, the number who start, and -- the point of it -- the holes.

The signal is the three leading columns, not the day cells.

  STARTS  games that fit a starting lineup this week.
  IDLE    players who had a game and sat.

A RECOVERABLE column sat between them for a few hours on 2026-10-15 and was
withdrawn before it published. It counted the starts an add would bring
without subtracting the starts of the player the add displaces, so on a full
roster it overstated the reachable gain and could exceed the legal maximum --
the same failure as FILLABLE below, differently dressed. The computation is
still in schedule_strength.recoverable_under_budget, unwired, with the defect
written on it.

FILLABLE used to sit there too, and it was Starts restated.
It came from schedule_strength's max_starters(roster + EVERY free agent
playing tonight) - started: the ceiling with unlimited adds. With a ~175-deep
pool that ceiling is always just the day's empty seats, so across 84 measured
cells fillable equalled holes every time, and every manager's total equalled
10 * days_with_games - starts exactly. Two of three key columns, one fact.
Worse, it implied 22 recoverable starts in a week the league caps at 3 adds.
RECOVERABLE asks the reachable question instead (recoverable_under_budget).

IDLE is the column that was missing. It is not derivable from Starts and it
moves: in week 17 of 2025-26, Benton 16 against Hayden 9 on identical 58
starts and 22 holes -- Benton position-clustered, Hayden simply thin. Those
need different fixes and the old grid could not tell them apart.

Rows sort by STARTS; the day cells stay muted, as the detail behind the
totals. Per-day shading was considered and cut: in a four-team league with a
deep wire it is near-uniform, so it would colour noise.

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
            "recoverable": md.get("recoverable_starts"),
            "adds_remaining": md.get("adds_remaining"),
            "unmatched_players": list(md.get("unmatched_players", [])),
        })
    rows.sort(key=lambda r: (-r["startable"], r["manager"]))

    return {
        "week": upcoming.get("week"),
        "days": days,
        "rows": rows,
        "has_free_agents": has_fa,
        "add_budget": upcoming.get("weekly_add_budget"),
        "adds_synced": upcoming.get("add_data_synced"),
        "from_lineups": list(upcoming.get("player_info_from_lineups") or []),
    }


def _cell_text(c: dict) -> str:
    """One day cell for the markdown reference table."""
    if c["off"]:
        return "-"
    parts = [str(c["started"])]
    if c["holes"]:
        parts.append(f"{c['holes']} open: {','.join(c['open_slots'][: c['holes']])}")
    if c["overflow"]:
        parts.append(f"+{c['overflow']} idle")
    return " / ".join(parts)


def _key_cells(r: dict) -> tuple[str, str]:
    """Starts and Idle as text."""
    return str(r["startable"]), str(r["overflow"])


def render_markdown(stats_report: dict) -> str:
    """Section 3 reference table for the drafting chat."""
    grid = build_grid(stats_report)
    if grid is None:
        return ""
    head = ["Manager", "Starts", "Idle"] + [d["label"] for d in grid["days"]]
    lines = [
        f"**Week {grid['week']} Games Grid** (rows sorted by Starts. Rendered "
        "automatically in the HTML -- do NOT reproduce it. You may cite a "
        "manager's Starts or Idle in a preview. Do NOT name players to add: "
        "naming adds is gated advice.)",
        "",
        "| " + " | ".join(head) + " |",
        "|" + "|".join(["---"] * len(head)) + "|",
        "| NBA games | | | " + " | ".join(
            "-" if d["nba_games"] is None else str(d["nba_games"]) for d in grid["days"]
        ) + " |",
    ]
    for r in grid["rows"]:
        st, idle = _key_cells(r)
        lines.append("| " + " | ".join(
            [r["manager"], st, idle]
            + [_cell_text(c) for c in r["cells"]]) + " |")
    unmatched = sorted({p for r in grid["rows"] for p in r["unmatched_players"]})
    if unmatched:
        lines.append("")
        lines.append(f"- Not in PLAYERLIST or LINEUPS, so not counted: {', '.join(unmatched)}")
    return "\n".join(lines) + "\n"


def render_html(stats_report: dict) -> str:
    """The grid as an HTML block, rendered after the Power Rankings content."""
    grid = build_grid(stats_report)
    if grid is None:
        return ""
    e = html.escape
    top_starts = max((r["startable"] for r in grid["rows"]), default=0)

    sub = ("<b>Starts</b>: games that fit a starting lineup this week. "
           "<b>Idle</b>: players who had a game and sat.")

    out = ['<div class="games-grid" data-viz="games-grid">',
           f'<div class="gg-title">Week {e(str(grid["week"]))} Games Grid</div>',
           f'<div class="gg-sub">{sub}</div>',
           '<div class="gg-scroll"><table class="gg-table"><thead><tr>'
           '<th class="gg-mgr-h">Manager</th><th class="gg-key">Starts</th>'
           '<th class="gg-key">Idle</th>']
    for d in grid["days"]:
        n = d["nba_games"]
        sb = "" if n is None else f'<span class="gg-nba">{n} NBA</span>'
        out.append(f'<th class="gg-day-h">{e(d["label"])}{sb}</th>')
    out.append('</tr></thead><tbody>')

    for r in grid["rows"]:
        st, idle = _key_cells(r)
        s_cls = "gg-key gg-top" if r["startable"] == top_starts else "gg-key"
        # Most idle is the most left on the table, not the best: no marker.
        out.append(f'<tr><th class="gg-mgr">{e(r["manager"])}</th>'
                   f'<td class="{s_cls}">{st}</td>'
                   f'<td class="gg-key">{idle}</td>')
        for c in r["cells"]:
            if c["off"]:
                out.append('<td class="gg-day gg-off">-</td>')
                continue
            spans, tip = [], []
            if c["holes"]:
                spans.append(f'<span class="gg-open">{c["holes"]} open</span>')
                tip.append("Open: " + ", ".join(c["open_slots"][: c["holes"]]))
            if c["overflow"]:
                spans.append(f'<span class="gg-idle">+{c["overflow"]} idle</span>')
                tip.append("Had a game, sat: " + ", ".join(c["overflow_players"]))
            if c["injured_with_game"]:
                tip.append(f'{c["injured_with_game"]} injured with a game')
            title = f' title="{e("; ".join(tip))}"' if tip else ""
            full = " gg-full" if c["holes"] == 0 else ""
            out.append(f'<td class="gg-day{full}"{title}>'
                       f'<span class="gg-n">{c["started"]}</span>'
                       f'{"".join(spans)}</td>')
        out.append('</tr>')
    out.append('</tbody></table></div>')

    foot = ["As of report time; rosters change after it. Injuries from "
            "INJURY_OVERRIDES only."]
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
        .games-grid .gg-open, .games-grid .gg-idle { display: block; font-size: 0.7em; white-space: nowrap; }
        .games-grid .gg-open { color: var(--danger-red, #b3261e); }
        .games-grid .gg-idle { color: var(--text-secondary, #777); }
        .games-grid .gg-off { color: var(--text-secondary, #aaa); }
    """
