"""
live_lines_page.py -- the live line as a page.

scripts/refresh_lines.py writes output/live_lines_weekN.json and nothing read
it. This renders it: one static, self-contained HTML file that opens from the
filesystem on Windows -- no server, no build step, no external asset, no
JavaScript. D1's PWA is a separate item.

WHAT IT IS (Nick, 10-22)
    A sportsbook page: the current score and the available bets, nothing else.
    Not busy. No comparison sentence, no preview prose -- the newsletter's
    betting section is the design vein, not a template to reproduce.

WHAT LAST YEAR'S VERSION NEVER HAD TO SHOW
    That one was static: one line per matchup, published Monday, never
    updated. This one is live. The score moves, the line moves with it, and
    the page is regenerated through the week, so it carries:
      - the score so far beside the projection, as display_a already renders
        it ("0 -> 1500" before any games, "912 -> 1498" mid-week);
      - how fresh it is, unmissably (as_of, generated_at, and the age in
        words) -- a live page that does not say how fresh it is becomes a
        confidently stale page;
      - the week clock: how many of the week's NBA game-days are played,
        which is a sportsbook's analogue and stays out of the way.

THE PAGE DISPLAYS; THE ENGINE COMPUTES
    Every number on it comes from the payload as a string or a straight
    format of the payload's own value. Nothing is rounded here and nothing is
    recomputed, so the page cannot disagree with the line that was priced.

IT REFUSES A PAYLOAD FROM ANOTHER ENGINE
    output/live_lines_week1.json, written 2026-10-20, still carries the
    caveat "the 10% injury discount applies to the simulated remainder only"
    -- a mechanism deleted on 10-21. Rendering it today would print a false
    explanation of how the numbers were made. So the payload records the
    engine that produced it and this module compares it against the current
    one, through E1's calibration_log.engine_version / engine_key: one
    definition, two consumers. A mismatch raises EngineMismatch; rendering it
    anyway takes an explicit allow_engine_mismatch, and then the page says so
    at the top in the loudest element on it.

VOICE
    "Banked" and "expected remaining" never appear as labels (VOICE.md): the
    decomposition ships as "912 -> 1498". Lore tags never reach a rendered
    page (VOICE.md rule 21), so every string taken from the payload is
    stripped of them with claim_check's own pattern before it is escaped.
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import calibration_log as cal
from .claim_check import LORE_TAG

CSS = """
:root{--bg:#0f1216;--card:#171c22;--line:#232a33;--ink:#e8edf3;--dim:#93a1b1;
--pos:#4ec9a0;--neg:#e2635b;--warn:#f0a63c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:20px 16px 56px}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 14px;
border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:18px}
h1{font-size:22px;margin:0;letter-spacing:.2px}
.stamp{color:var(--dim);font-size:13px;font-variant-numeric:tabular-nums}
.age{color:var(--ink);background:var(--line);border-radius:999px;padding:2px 9px;font-size:12px}
.age.stale{background:#4a3410;color:var(--warn)}
.clock{width:100%;display:flex;align-items:center;gap:10px;color:var(--dim);font-size:12px}
.bar{flex:1;height:4px;background:var(--line);border-radius:2px;overflow:hidden}
.bar span{display:block;height:100%;background:var(--pos)}
.mismatch{background:#4a1714;border:1px solid var(--neg);color:#ffd9d6;
padding:12px 14px;border-radius:8px;margin:0 0 18px;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
margin-bottom:14px;overflow:hidden}
table{width:100%;border-collapse:collapse}
th{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.6px;
text-align:right;font-weight:600;padding:10px 12px 6px}
th.team{text-align:left}
td{padding:10px 12px;border-top:1px solid var(--line);text-align:right;
font-variant-numeric:tabular-nums}
td.team{text-align:left;font-weight:600}
td.score{color:var(--ink);white-space:nowrap}
.fav td{background:rgba(78,201,160,.06)}
.ou{display:flex;justify-content:space-between;color:var(--dim);
font-size:12px;padding:9px 12px;border-top:1px solid var(--line)}
.notes{margin-top:22px;font-size:13px;color:var(--dim)}
.notes h2{font-size:11px;text-transform:uppercase;letter-spacing:.6px;
color:var(--dim);margin:18px 0 6px}
.notes ul{margin:0;padding-left:18px}
.notes li{margin:3px 0}
.ev{color:var(--ink)}
.ev.cleared{color:var(--warn)}
footer{margin-top:24px;padding-top:12px;border-top:1px solid var(--line);
color:var(--dim);font-size:11.5px;font-variant-numeric:tabular-nums}
"""


class EngineMismatch(RuntimeError):
    """The payload was priced by an engine that is not the one on disk."""


class LiveLinesPayloadError(ValueError):
    """The payload is not a live-lines payload."""


def clean(value) -> str:
    """A payload string, lore-tag-free and HTML-escaped. Rule 21: a tag must
    never reach a rendered page, and escaping one would only make it
    visible."""
    return html.escape(LORE_TAG.sub("", str(value)).strip())


def payload_engine_key(payload: dict) -> Optional[str]:
    """The engine that priced this payload, through E1's own function."""
    engine = payload.get("engine")
    if not isinstance(engine, dict) or not engine.get("commit"):
        return None
    return cal.engine_key({"engine_commit": engine.get("commit"),
                           "engine_dirty": engine.get("dirty")})


def current_engine_key(base_path=".") -> str:
    live = cal.engine_version(base_path)
    return cal.engine_key({"engine_commit": live["commit"], "engine_dirty": live["dirty"]})


def engine_check(payload: dict, base_path=".") -> dict:
    """{"payload", "current", "ok", "why"} -- never a second comparison."""
    theirs = payload_engine_key(payload)
    ours = current_engine_key(base_path)
    if theirs is None:
        return {"payload": None, "current": ours, "ok": False,
                "why": ("this payload does not say which engine priced it, so its "
                        "numbers and its caveats cannot be trusted to describe the "
                        "simulator on disk -- re-run scripts/refresh_lines.py")}
    if theirs != ours:
        return {"payload": theirs, "current": ours, "ok": False,
                "why": (f"priced by engine {theirs}, and the engine on disk is {ours}. "
                        "The betting path has changed since, so the numbers and the "
                        "caveats below describe a simulator that no longer exists -- "
                        "re-run scripts/refresh_lines.py")}
    return {"payload": theirs, "current": ours, "ok": True, "why": ""}


def _age(as_of: str, generated_at: str, now: datetime) -> tuple:
    """(words, is it stale) for the freshness chip."""
    try:
        stamp = datetime.fromisoformat(generated_at)
    except (TypeError, ValueError):
        return "age unknown", True
    seconds = (now - stamp).total_seconds()
    if seconds < 0:
        return "just now", False
    hours = seconds / 3600.0
    if hours < 1:
        words = f"{int(seconds // 60)} min old"
    elif hours < 36:
        words = f"{int(round(hours))} h old"
    else:
        words = f"{int(round(hours / 24))} days old"
    return words, hours >= 36


def _odds(value) -> str:
    """American odds as published: +145 / -145."""
    n = int(value)
    return f"+{n}" if n > 0 else str(n)


def _spread(value) -> str:
    """The spread as priced, keeping its own precision."""
    f = float(value)
    text = f"{f:g}"
    return f"+{text}" if f > 0 else text


def render(payload: dict, *, base_path=".", now: datetime = None,
           allow_engine_mismatch: bool = False) -> str:
    """The page, as one self-contained HTML string.

    Raises EngineMismatch unless the payload's engine is the one on disk, or
    allow_engine_mismatch is set -- in which case the page carries the
    mismatch as its first and loudest element.
    """
    for key in ("week", "as_of", "lines"):
        if key not in payload:
            raise LiveLinesPayloadError(f"the payload has no {key!r}")
    now = now or datetime.now()
    check = engine_check(payload, base_path)
    if not check["ok"] and not allow_engine_mismatch:
        raise EngineMismatch(
            f"week {payload['week']} live lines: {check['why']}. Pass "
            "allow_engine_mismatch to render it anyway; the page will say so.")

    week = clean(payload["week"])
    as_of = clean(payload["as_of"])
    generated = clean(payload.get("generated_at", ""))
    age, stale = _age(payload.get("as_of"), payload.get("generated_at"), now)
    done = len(payload.get("completed_dates") or [])
    left = len(payload.get("remaining_dates") or [])
    total_days = done + left

    out = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f"<title>Week {week} live lines</title>", f"<style>{CSS}</style>",
           "</head><body><div class=\"wrap\">"]

    out.append("<header>")
    out.append(f"<h1>Week {week}</h1>")
    out.append(f'<div class="stamp">as of {as_of}'
               + (f" &middot; computed {generated}" if generated else "") + "</div>")
    out.append(f'<div class="age{" stale" if stale else ""}">{clean(age)}</div>')
    if total_days:
        pct = int(round(100.0 * done / total_days))
        out.append('<div class="clock">'
                   f'<span>{done} of {total_days} game days played</span>'
                   f'<span class="bar"><span style="width:{pct}%"></span></span></div>')
    out.append("</header>")

    if not check["ok"]:
        out.append(f'<p class="mismatch"><strong>Do not price anything off this page.</strong> '
                   f'{clean(check["why"])}.</p>')

    for line in payload["lines"]:
        out.append(_card(line))

    out.append(_notes(payload))
    engine_label = check["payload"] or "unknown"
    out.append("<footer>"
               f"seed {clean(payload.get('seed', '-'))} &middot; "
               f"{clean(payload.get('num_simulations', '-'))} simulations &middot; "
               f"state {clean(payload.get('state_hash', '-'))} &middot; "
               f"engine {clean(engine_label)}"
               "</footer>")
    out.append("</div></body></html>")
    return "\n".join(out)


def _card(line: dict) -> str:
    a_fav = float(line["spread_a"]) < float(line["spread_b"])
    rows = []
    for side, favourite in (("a", a_fav), ("b", not a_fav)):
        rows.append(
            f'<tr class="{"fav" if favourite else ""}">'
            f'<td class="team">{clean(line[f"team_name_{side}"])}</td>'
            f'<td class="score">{clean(line[f"display_{side}"])}</td>'
            f'<td>{clean(_spread(line[f"spread_{side}"]))}</td>'
            f'<td>{clean(_odds(line[f"moneyline_{side}"]))}</td>'
            f'<td>{clean(line[f"win_prob_{side}"])}%</td>'
            "</tr>")
    return ("<section class=\"card\"><table>"
            '<thead><tr><th class="team">Matchup</th><th>Score &rarr; projected</th>'
            "<th>Spread</th><th>Money</th><th>Win</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
            f'<div class="ou"><span>Over / under</span>'
            f'<span>{clean(line["over_under"])}</span></div></section>')


def _notes(payload: dict) -> str:
    """Tag events, assumptions and caveats, as the payload states them.

    The `cleared` event is the one that explains a line moving for a reason
    the matchup numbers do not show, so it is marked rather than listed flat.
    """
    blocks = []
    events = payload.get("tag_events") or []
    if events:
        items = []
        for e in events:
            kind = "cleared" if str(e.get("event", "")).startswith("cleared") else ""
            anchor = e.get("anchor")
            tail = f" &middot; anchored {clean(anchor)}" if anchor else ""
            basis = e.get("basis")
            items.append(
                f'<li><span class="ev {kind}">{clean(e.get("player", "?"))} '
                f'{clean(e.get("tag", ""))}</span> &mdash; {clean(e.get("event", ""))}'
                f'{tail}{(" &middot; " + clean(basis)) if basis else ""}</li>')
        blocks.append("<h2>Injury tags this week</h2><ul>" + "".join(items) + "</ul>")
    for label, key in (("Assumptions", "assumptions"), ("How these are priced", "caveats")):
        rows = payload.get(key) or []
        if rows:
            blocks.append(f"<h2>{label}</h2><ul>"
                          + "".join(f"<li>{clean(r)}</li>" for r in rows) + "</ul>")
    return f'<div class="notes">{"".join(blocks)}</div>' if blocks else ""


# =============================================================================
# the file
# =============================================================================

def payload_path(week: int, base_path=".") -> Path:
    return Path(base_path) / "output" / f"live_lines_week{int(week)}.json"


def page_path(week: int, base_path=".") -> Path:
    return Path(base_path) / "output" / f"live_lines_week{int(week)}.html"


def load_payload(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_page(payload: dict, out_path=None, base_path=".", **kwargs) -> Path:
    """Render and write. One static file, nothing beside it."""
    page = render(payload, base_path=base_path, **kwargs)
    path = Path(out_path) if out_path else page_path(payload["week"], base_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
