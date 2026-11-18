"""
hub_v2/page.py -- the new hub's renderer: the view model (view.py) as one
self-contained HTML page. Built beside modules/hub_page.py; the rules of its
docstring all carry over.

THE PAGE DISPLAYS; THE ENGINE COMPUTES. Every number printed is a payload
string, through clean() (the lore-tag strip and HTML escaping, rule 21). The
renderer does no arithmetic (tests pin it: no round/float/sum/sorted/max/min
in render's source). The page's script does none either, beyond the
payload's AGE in words (the reader's clock) and the stale banner after
STALE_HOURS -- hub_page's own rule, the same words -- and reordering table
rows by the orders the payload carries.

ONE SOURCE FOR EVERY VALUE: the stylesheet is tokens.css(LAYOUT_CSS):
tokens.json compiled into custom properties, the fonts embedded, bundle.css
as it is, then LAYOUT_CSS -- which may hold no hex colour and no px literal
(var(--token) only; media-query widths as {{token}}).

OFFLINE: no http(s) anywhere in the page, fonts embedded, icons inline SVG.

ROUTES (hash): #/home, #/matchups, #/matchups/<id>, #/teams, #/teams/<manager>,
#/players, #/market, #/league. Every screen is in the page; the script shows
the one the hash names (an unknown hash shows Home), so the back button
works and a deep link opens its screen after the unlock (the decrypt shell
keeps the hash).

PLAYER NAMES open the CURRENT player card: the same loader as hub_page (the
bundle once -- inline in preview, HUB.cards() published -- then the player's
history and headshot, then the newsletter's modal), with the 404 message
"The hub has been updated: reload the page to open player cards." The new
card is 4c.

MODES: preview (plaintext, output/hub_v2_preview.html, links to the current
page's sections from the placeholders) and publish (inside the decrypt shell;
publish.py; issues open through window.HUB).
"""

from __future__ import annotations

import json
from datetime import datetime

from ..live_lines_page import clean
from .infotips import tip

# tap targets: an interactive element carries one of these classes (or sits
# in one of TAP_PARENTS); each class's CSS gives it at least tap-min (or
# row-min) of height. tests/test_hub_v2.py checks both halves. Chart tap
# strips (lh-c-hit) are the design's per-point hit areas: full plot height,
# keyboard-reachable, as wide as the point's share of the axis.
TAP_CLASSES = ("lh-card", "lh-rank", "lh-issuebar", "lh-back", "lh-link", "lh-iconbtn", "v2-tap", "lh-c-hit")
TAP_PARENTS = ("lh-tabbar", "lh-seg", "lh-toggle", "lh-info")

ICONS = {
    "home": 'M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z',
    "matchups": 'M4 7h10M4 7l3-3M4 7l3 3M20 17H10M20 17l-3-3M20 17l-3 3',
    "teams": ('M16 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 20c0-3 3-5 6-5s6 2 6 5'
              'M14 15c3 0 8 1 8 5'),
    "players": 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 4-6 8-6s8 2 8 6',
    "market": 'M4 7h16l-1.5 11a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2zM9 7a3 3 0 0 1 6 0',
    "league": 'M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0zM7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4',
}

LAYOUT_CSS = """
.v2-app{min-height:100vh;display:flex;flex-direction:column;padding-bottom:var(--tabbar-height)}
.v2-main{width:100%;max-width:var(--page-max);margin:0 auto;flex:1}
[hidden]{display:none !important}
.v2-stack{display:flex;flex-direction:column;gap:var(--space-20);padding:var(--space-16)}
.v2-sec{display:flex;flex-direction:column;gap:var(--space-10)}
.v2-col{display:flex;flex-direction:column;gap:var(--space-20);min-width:0}
.v2-cols{display:flex;flex-direction:column;gap:var(--space-20)}
.v2-minw{min-width:0;display:flex;flex-direction:column}
.v2-gap8{gap:var(--space-8)}
.v2-p{margin:0;font-size:var(--type-body-size);line-height:var(--type-body-lh);color:var(--ink-2)}
.v2-stale-hd{display:flex;gap:var(--space-8);align-items:center}
.v2-lock{font-size:var(--type-small-size);line-height:var(--type-small-lh);color:var(--ink-on-dark-3)}
.lh-tabbar{position:fixed;left:0;right:0;bottom:0;z-index:4}
.lh-seg button{min-height:var(--tap-min)}
.v2-tap{position:relative;cursor:pointer}
.v2-tap::after{content:"";position:absolute;left:0;right:0;top:50%;height:var(--tap-min);min-width:var(--tap-min);transform:translateY(-50%)}
button.v2-pl{all:unset;cursor:pointer;color:var(--ink);font-weight:var(--type-row-weight);text-decoration:underline dotted var(--axis-strong);text-underline-offset:var(--space-2)}
button.lh-name{all:unset;cursor:pointer;font-size:var(--type-row-size);font-weight:var(--type-row-weight);display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink)}
.v2-topbar{background:var(--surface);border-bottom:var(--hairline) solid var(--line);padding:0 var(--space-16);display:flex;align-items:center;justify-content:space-between;gap:var(--space-8)}
.v2-mono-72{--s:var(--mono-72)}
.v2-mono-36{--s:var(--mono-36)}
.v2-mono-28{--s:var(--mono-28)}
.v2-mcard{text-decoration:none;color:var(--ink);gap:var(--space-12)}
.v2-mpts{display:flex;flex-direction:column;align-items:flex-end}
.v2-mcard .lh-mrow__name,.v2-mside .lh-mrow__name{white-space:normal;overflow-wrap:anywhere}
.v2-banked{font-size:var(--type-display-sm-size);font-weight:600}
.v2-mfoot{display:flex;align-items:center;justify-content:space-between;gap:var(--space-8);padding-top:var(--space-10)}
.v2-note{font-size:var(--type-meta-size);color:var(--ink-2);min-width:0}
.v2-details{font-size:var(--type-meta-size);font-weight:700;color:var(--accent);white-space:nowrap}
.v2-name14{font-size:var(--type-row-size)}
.v2-dsp-sm{font-size:var(--type-display-sm-size);font-weight:700}
.v2-teamgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-10)}
.v2-tcard{text-decoration:none;color:var(--ink);gap:var(--space-10)}
.v2-tc-top{display:flex;align-items:center;gap:var(--space-8);min-width:0}
.v2-tname{font-size:var(--type-row-size);font-weight:800;overflow-wrap:anywhere}
.v2-nested2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-6)}
.v2-tb{display:flex;flex-direction:column;gap:var(--space-6);padding-top:var(--space-10)}
.v2-tb-head{display:flex;align-items:center;justify-content:space-between;gap:var(--space-8)}
.v2-tb-team{display:flex;align-items:center;gap:var(--space-8);font-size:var(--type-body-size);font-weight:800;color:var(--ink);text-decoration:none}
.v2-tb-text{font-size:var(--type-body-size);line-height:var(--type-body-lh);color:var(--ink-2)}
.v2-heat{grid-template-columns:minmax(0,2fr) repeat(var(--n),minmax(0,1fr))}
.v2-heat--tot{grid-template-columns:minmax(0,2fr) repeat(var(--n),minmax(0,1fr)) minmax(0,1fr)}
.v2-heat-h{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);text-transform:uppercase;letter-spacing:var(--type-label-ls)}
.v2-heat-h span{text-align:center;display:flex;flex-direction:column}
.v2-heat-lab{font-size:var(--type-meta-size);font-weight:800;display:flex;align-items:center;gap:var(--space-6);min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.v2-heat-tot{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:700;text-align:right}
.v2-heat-rows{display:flex;flex-direction:column;gap:var(--space-4)}
.lh-heat__cell.v2-s0{background:var(--surface-sunken);color:var(--ink-3)}
.v2-heat-a{color:var(--ink);text-decoration:none;display:flex;align-items:center;gap:var(--space-6);min-width:0}
button.lh-issuebar{width:100%;border:0;border-bottom:var(--hairline) solid var(--line);cursor:pointer;text-align:left}
.v2-ib{display:flex;align-items:center;gap:var(--space-10);min-width:0;color:var(--ink-2)}
.v2-mside a{color:var(--ink);text-decoration:none}
.lh-chart .lh-c-hit{outline:none}
.lh-chart .v2-dot{fill:var(--team)}
.lh-chart .v2-sel{fill:none;stroke:var(--ink-strong);stroke-width:2}
.v2-mhead{background:var(--surface);border-bottom:var(--hairline) solid var(--line);padding:var(--space-14) var(--space-16);display:flex;flex-direction:column;gap:var(--space-12)}
.v2-mside{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;column-gap:var(--space-10)}
.v2-score{font-family:var(--font-display);font-size:var(--type-display-xl-size);line-height:var(--type-display-xl-lh);font-weight:700;font-variant-numeric:tabular-nums;text-align:right}
.v2-wbar-l{display:flex;justify-content:space-between;font-size:var(--type-meta-size);font-weight:800}
.v2-pane{display:flex;flex-direction:column;gap:var(--space-14)}
.v2-para{display:flex;flex-direction:column;gap:var(--space-4)}
.v2-para + .v2-para{border-top:var(--hairline) solid var(--line-soft);padding-top:var(--space-10)}
.v2-missing{display:grid;grid-template-columns:auto minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min)}
.v2-scroll{overflow-x:auto}
.v2-rt[data-mode="simple"] .v2-det{display:none}
.v2-rt .v2-sticky{position:sticky;left:0;background:var(--surface);z-index:1;max-width:45vw}
.v2-rt th.v2-sticky{background:var(--surface-subtle)}
.v2-rt tr.lh-inactive .v2-sticky{background:var(--row-inactive)}
.v2-chips{display:inline-flex;gap:var(--space-4);margin-left:var(--space-4);vertical-align:middle}
.v2-pad{padding:var(--space-12) var(--space-14)}
.v2-keep{display:grid;grid-template-columns:var(--space-32) minmax(0,1fr) minmax(0,1fr) auto;column-gap:var(--space-8);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft)}
.v2-keepv{font-size:var(--type-body-size);font-weight:700;text-align:right}
.v2-move{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:var(--space-10);padding-top:var(--space-10);align-items:start}
.v2-mvp{display:block;font-size:var(--type-body-size);line-height:var(--type-body-lh)}
.v2-mk{font-weight:800;display:inline-block;min-width:var(--space-14)}
.v2-mk--add{color:var(--up)}.v2-mk--drop{color:var(--down)}.v2-mk--trade{color:var(--ink-2)}
.v2-hdr-team{display:flex;align-items:center;gap:var(--space-14);padding:var(--space-14) var(--space-16);background:var(--surface);border-bottom:var(--hairline) solid var(--line)}
.v2-hdr-name{margin:0;font-family:var(--font-display);font-size:var(--type-display-lg-size);line-height:var(--type-display-lg-lh);font-weight:700}
.v2-kpi-head{display:flex;align-items:center;justify-content:space-between;gap:var(--space-4)}
.lh-kpi .lh-delta,.lh-kpi .lh-kpi__ctx{white-space:normal}
.v2-readout-h{font-weight:800;color:var(--ink)}
.v2-issue{position:fixed;inset:0;background:var(--surface);z-index:10;display:flex;flex-direction:column}
.v2-issue iframe{flex:1;border:0;width:100%}
.v2-foot{padding:var(--space-16);font-size:var(--type-small-size);color:var(--ink-2);text-align:center}
.v2-forget{all:unset;cursor:pointer;color:var(--accent);font-weight:700}
.v2-banner{background:var(--status-out-tint);color:var(--status-out);padding:var(--space-10) var(--space-16);font-size:var(--type-body-size);font-weight:700}
.v2-calm{background:var(--surface-sunken);color:var(--ink-2);padding:var(--space-10) var(--space-16);font-size:var(--type-body-size)}
.v2-check{background:var(--dark);color:var(--ink-on-dark);padding:var(--space-10) var(--space-16);font-size:var(--type-meta-size);white-space:pre-wrap}
@media (min-width:{{bp-mid}}){
 .lh-kpis{grid-template-columns:repeat(4,minmax(0,1fr))}
}
@media (min-width:{{bp-wide}}){
 .v2-app{padding-bottom:0}
 .v2-hdr{order:-3}
 .v2-stale-wrap{order:-2}
 .lh-tabbar{order:-1;position:sticky;top:0;bottom:auto;height:auto;border-top:0;border-bottom:var(--hairline) solid var(--line);display:flex;justify-content:center;gap:var(--space-24);padding:var(--space-4) var(--space-16)}
 .lh-tabbar a{flex-direction:row;gap:var(--space-6);font-size:var(--type-body-size);padding:0 var(--space-8)}
 .v2-cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}
 .v2-cols .lh-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
}
"""


# =============================================================================
# small pieces
# =============================================================================

def _icon(path: str, size: str = "20") -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'<path d="{path}"/></svg>')


WARN = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16h.01"/></svg>')
INFO = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>')
DOC = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
       'aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>')
CHEV = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>')
BACK = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>')


class _Ids:
    def __init__(self):
        self.n = 0

    def next(self, p: str) -> str:
        self.n += 1
        return f"{p}{self.n}"


def _info(ids: _Ids, key: str, meta: str = "") -> str:
    title, body = tip(key)
    pid = ids.next("tip")
    return (f'<span class="lh-info">' + (f'<span class="lh-meta v2-info-meta">{clean(meta)}</span>' if meta else "")
            + f'<button type="button" aria-expanded="false" aria-controls="{pid}" aria-label="What {clean(title)} means">'
            f'{INFO}</button><span class="lh-info__pop" id="{pid}" role="note" hidden><b>{clean(title)}</b>'
            f'{clean(body)}</span></span>')


def _pl(name: str, card, cls: str = "v2-pl v2-tap") -> str:
    """A player's name: a button that opens his current card when he has one."""
    if card:
        return f'<button type="button" class="{cls}" data-card="{clean(card)}">{clean(name)}</button>'
    return f'<span>{clean(name)}</span>'


def _mono(team: dict, size: str = "") -> str:
    return f'<span class="lh-mono {team["cls"]}{" v2-mono-" + size if size else ""}" aria-hidden="true">' \
           f'{clean(team["mono"])}</span>'


def _chip(c: dict) -> str:
    kind = {"out": "out", "q": "q", "il": "il"}.get(c["kind"], "neutral")
    return f'<span class="lh-status lh-status--{kind}">{clean(c["text"])}</span>'


def _spark(sp: dict, aria: str) -> str:
    return (f'<svg class="lh-spark" width="{sp["w"]}" height="{sp["h"]}" viewBox="0 0 {sp["w"]} {sp["h"]}" '
            f'role="img" aria-label="{clean(aria)}"><polyline points="{sp["points"]}"/>'
            f'<circle cx="{sp["cx"]}" cy="{sp["cy"]}" r="3"/></svg>')


def _segs(segs) -> str:
    out = []
    for x in segs:
        if x.get("card"):
            out.append(_pl(x["t"], x["card"]))
        else:
            t = x["t"]
            lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
            out.append((lead + clean(t) + trail) if t.strip() else t.replace("<", "").replace(">", ""))
    return "".join(out)


def _topbar(href: str, label: str, age: str) -> str:
    return (f'<div class="v2-topbar"><a class="lh-back" href="{href}">{BACK}{clean(label)}</a>'
            f'<span class="lh-meta">Updated <span class="v2-age">{clean(age)}</span></span></div>')


def _seg(group: str, panes: list) -> str:
    """SegmentedTabs over panes [(key, label)]; the first is selected."""
    return (f'<div class="lh-seg" role="tablist" data-seg="{group}">'
            + "".join(f'<button type="button" role="tab" data-pane="{k}" aria-selected="{"true" if i == 0 else "false"}">'
                      f'{clean(lab)}</button>' for i, (k, lab) in enumerate(panes)) + "</div>")


def _chart(ch: dict, cid: str) -> str:
    o = [f'<svg class="lh-chart" width="100%" viewBox="{ch["vb"]}" role="group" aria-label="{clean(ch["aria"])}" '
         f'data-chart="{cid}">']
    o += [f'<line class="{g["cls"]}" x1="{g["x1"]}" y1="{g["y1"]}" x2="{g["x2"]}" y2="{g["y2"]}"/>' for g in ch["grid"]]
    o += [f'<text x="{t["x"]}" y="{t["y"]}" text-anchor="{t["anchor"]}">{clean(t["t"])}</text>' for t in ch["labels"]]
    for ln in ch["lines"]:
        o.append(f'<g class="{ln["cls"]}"><polyline class="lh-c-line{" lh-c-proj" if ln["proj"] else ""}" '
                 f'points="{ln["points"]}"/></g>')
    for e in ch["events"]:
        o.append(f'<circle class="lh-c-event" cx="{e["cx"]}" cy="{e["cy"]}" r="5"/>')
        if e["label"]:
            o.append(f'<text class="lh-c-event-text" x="{e["lx"]}" y="{e["ly"]}" text-anchor="{e["anchor"]}">'
                     f'{clean(e["label"])}</text>')
    if ch["dot"]:
        d = ch["dot"]
        o.append(f'<g class="{d["cls"]}"><circle class="v2-dot" cx="{d["cx"]}" cy="{d["cy"]}" r="4"/></g>')
    for e in ch["ends"]:
        o.append(f'<g class="{e["cls"]}"><text class="lh-c-label" x="{e["x"]}" y="{e["y"]}">{clean(e["t"])}</text></g>')
    o.append('<circle class="v2-sel" r="6" cx="-20" cy="-20"/>')
    for h in ch["hits"]:
        o.append(f'<rect class="lh-c-hit" x="{h["x"]}" y="{h["y"]}" width="{h["w"]}" height="{h["h"]}" tabindex="0" '
                 f'role="button" aria-label="{clean(h["label"])}" data-cx="{h["cx"]}" data-cy="{h["cy"]}" '
                 f'data-head="{clean(h["head"])}" data-body="{clean(h["body"])}"/>')
    o.append("</svg>")
    r0 = ch.get("readout0") or {"head": ch.get("empty") or "", "body": ""}
    o.append(f'<div class="lh-readout" aria-live="polite" data-readout="{cid}">'
             f'<span class="v2-readout-h">{clean(r0["head"])}</span> <span>{clean(r0["body"])}</span></div>')
    if ch.get("empty"):
        o.append(f'<p class="v2-p">{clean(ch["empty"])}</p>')
    return "".join(o)


def _heat(rows: list, cols: list, *, total: bool, label_of) -> str:
    n = len(cols)
    cls = "v2-heat--tot" if total else "v2-heat"
    o = [f'<div class="v2-heat-rows"><div class="lh-heat {cls} v2-heat-h" style="--n:{n}"><span></span>']
    o += [f'<span><span>{clean(c["label"])}</span><span>{clean(c.get("sub", ""))}</span></span>' for c in cols]
    if total:
        o.append('<span>Total</span>')
    o.append("</div>")
    for r in rows:
        o.append(f'<div class="lh-heat {cls}{" " + r["team"]["cls"] if r.get("team") else ""}" style="--n:{n}">'
                 f'<span class="v2-heat-lab">{label_of(r)}</span>')
        o += [f'<span class="lh-heat__cell {"lh-s" + str(c["b"]) if c["b"] else "v2-s0"}">{clean(c["n"])}</span>'
              for c in r["cells"]]
        if total:
            o.append(f'<span class="v2-heat-tot">{clean(r["total"])}</span>')
        o.append("</div>")
    o.append("</div>")
    return "".join(o)


# =============================================================================
# components
# =============================================================================

def _matchup_card(mu: dict) -> str:
    o = [f'<a class="lh-card v2-mcard" href="{mu["href"]}" data-matchup="{mu["id"]}">']
    for s in mu["sides"]:
        t = s["team"]
        o.append(f'<span class="lh-mrow {t["cls"]}">{_mono(t)}'
                 f'<span class="v2-minw"><span class="lh-mrow__name">{clean(s["name"])}</span>'
                 f'<span class="lh-sub">{clean(s["manager"])} &middot; {clean(s["record"])}</span></span>'
                 f'<span class="lh-num v2-mpts"><span class="lh-dsp v2-banked">{clean(s["now"])}</span>'
                 f'<span class="lh-sub">proj {clean(s["proj"])}</span></span>'
                 f'<span class="lh-mrow__win{" lh-team-text" if s["fav"] else ""}">{clean(s["win"])}</span></span>')
    a, b = mu["sides"]
    o.append(f'<span class="lh-winbar" role="img" aria-label="{clean(mu["bar_aria"])}">'
             f'<span class="{a["team"]["cls"]}" style="width:{clean(mu["bar_a"])}"></span>'
             f'<span class="{b["team"]["cls"]}"></span></span>')
    o.append('<span class="lh-tiles3">'
             f'<span class="lh-kpi lh-kpi--nested"><span class="lh-label">Spread</span><span class="lh-kpi__value">{clean(mu["spread"])}</span></span>'
             f'<span class="lh-kpi lh-kpi--nested"><span class="lh-label">Total</span><span class="lh-kpi__value">{clean(mu["total"])}</span></span>'
             f'<span class="lh-kpi lh-kpi--nested"><span class="lh-label">Moneyline</span><span class="lh-kpi__value">{clean(mu["moneyline"])}</span></span>'
             '</span>')
    o.append(f'<span class="lh-divider v2-mfoot"><span class="v2-note" data-note="{clean(mu["note_src"])}">'
             f'{clean(mu["note"])}</span><span class="v2-details">Details &rsaquo;</span></span></a>')
    return "".join(o)


def _team_card(tp: dict, odds_label: str) -> str:
    t = tp["team"]
    tiles = [("Record", tp["record"]), (odds_label, tp["odds"]), ("Adds left", tp["adds_left"]),
             ("Injured", tp["injured"])]
    return (f'<a class="lh-card v2-tcard {t["cls"]}" href="{t["href"]}">'
            f'<span class="v2-tc-top">{_mono(t)}<span class="v2-minw"><span class="v2-tname">{clean(t["team"])}</span>'
            f'<span class="lh-sub">{clean(t["manager"])}</span></span></span><span class="v2-nested2">'
            + "".join(f'<span class="lh-kpi lh-kpi--nested"><span class="lh-label">{clean(lab)}</span>'
                      f'<span class="lh-kpi__value">{clean(v)}</span></span>' for lab, v in tiles)
            + "</span></a>")


def _ranking(vm: dict, ids: _Ids) -> str:
    o = ['<section class="lh-card v2-gap8" data-section="power"><div class="lh-sechead">'
         f'<h2 class="lh-eyebrow">Power rankings</h2>{_info(ids, "title_odds", vm["rank_meta"])}</div>']
    for r in vm["ranking"]:
        t = r["team"]
        d = r["dir"] if r["dir"] in ("up", "down") else "flat"
        o.append(f'<a class="lh-rank {t["cls"]}" href="{t["href"]}"><span class="lh-rank__n">{clean(r["rank"])}</span>'
                 f'{_mono(t, "28")}<span class="v2-minw"><span class="lh-mrow__name v2-name14">{clean(t["team"])}</span>'
                 f'<span class="lh-sub lh-num">{clean(r["record"])} &middot; {clean(r["pf"])} PF</span></span>'
                 f'{_spark(r["spark"], r["aria"])}<span class="lh-rank__right lh-num">'
                 f'<span class="lh-dsp v2-dsp-sm">{clean(r["odds"])}</span>'
                 f'<span class="lh-delta lh-delta--{d}">{clean(r["delta"])}</span></span></a>')
    o.append(f'<span class="lh-sub">{clean(vm["spark_note"])}</span></section>')
    return "".join(o)


def _trade(vm: dict) -> str:
    o = ['<section class="lh-card" data-section="trade"><div class="lh-sechead"><h2 class="lh-eyebrow">Trade block</h2></div>']
    for c in vm["trade"]:
        t = c["team"]
        o.append(f'<div class="lh-divider v2-tb"><div class="v2-tb-head"><a class="v2-tb-team v2-tap {t["cls"]}" '
                 f'href="{t["href"]}"><span class="lh-swatch"></span>{clean(t["team"])}</a>'
                 f'<span class="lh-status lh-status--neutral">{clean(c["mode"])}</span></div>')
        for lst in c["lists"]:
            o.append(f'<span class="v2-tb-text">{clean(lst["label"])}: '
                     + ", ".join(_pl(p["name"], p["card"]) for p in lst["players"]) + "</span>")
        if c["empty"]:
            o.append(f'<span class="v2-tb-text">{clean(c["empty"])}</span>')
        o.append("</div>")
    o.append(f'<span class="lh-sub">{clean(vm["trade_foot"])}</span></section>')
    return "".join(o)


def _kpi(k: dict, team: dict, ids: _Ids, key: str, spark_html: str = "") -> str:
    cls = {"up": "lh-delta lh-delta--up", "down": "lh-delta lh-delta--down"}.get(k["dir"], "lh-kpi__ctx")
    value_cls = "lh-kpi__value lh-team-text" if key == "win" else "lh-kpi__value"
    tipkey = {"odds": "title_odds", "win": "win"}.get(key)
    head = f'<span class="lh-label">{clean(k["label"])}</span>'
    if tipkey:
        head = f'<span class="v2-kpi-head">{head}{_info(ids, tipkey)}</span>'
    body = (f'<span class="lh-kpi__row"><span class="{value_cls}">{clean(k["value"])}</span>{spark_html}</span>'
            if spark_html else f'<span class="{value_cls}">{clean(k["value"])}</span>')
    return f'<div class="lh-kpi {team["cls"]}">{head}{body}<span class="{cls}">{clean(k["ctx"])}</span></div>'


ROSTER_COLS = [("name", "Player", False), ("fppg", "FPPG", False), ("gp", "GP", False), ("proj", "Proj", False),
               ("next", "Next", False), ("l14", "L14", True), ("gl", "GL", True), ("keep", "Keep", True)]


def _roster(tp: dict, ids: _Ids) -> str:
    r = tp["roster"]
    default = r["default"]
    o = ['<section class="lh-card lh-card--flush" data-section="roster"><div class="lh-sechead v2-pad">'
         f'<h2 class="lh-eyebrow">Roster</h2>{_info(ids, "proj")}'
         '<div class="lh-toggle" role="group" aria-label="Table detail"><button type="button" aria-pressed="true" '
         'data-mode="simple">Simple</button><button type="button" aria-pressed="false" data-mode="detailed">Detailed'
         '</button></div></div>'
         f'<div class="v2-scroll"><table class="lh-table v2-rt" data-mode="simple" data-sort="{clean(default)}" '
         f'data-dir="1" data-orders=\'{clean(json.dumps(r["orders"], separators=(",", ":")))}\'><thead><tr>']
    for k, lab, det in ROSTER_COLS:
        cls = " ".join(x for x in ("v2-sticky" if k == "name" else "", "v2-det" if det else "") if x)
        sort = f' aria-sort="descending"' if k == default else ""
        o.append(f'<th{" class=" + chr(34) + cls + chr(34) if cls else ""}{sort} data-k="{k}"><button type="button" '
                 f'class="v2-tap" data-sort="{k}">{clean(lab)}<span class="v2-arrow">{" &#9662;" if k == default else ""}'
                 f'</span></button></th>')
    o.append("</tr></thead>")

    def row(p, inactive):
        cells = [f'<td class="v2-sticky">{_pl(p["name"], p["card"], "lh-name v2-tap")}'
                 f'<span class="lh-sub">{clean(p["meta"])}'
                 + (f'<span class="v2-chips">{"".join(_chip(c) for c in p["chips"])}</span>' if p["chips"] else "")
                 + "".join(f" &middot; {clean(n)}" for n in p["notes"]) + "</span></td>"]
        for k, _lab, det in ROSTER_COLS[1:]:
            cells.append(f'<td{" class=" + chr(34) + "v2-det" + chr(34) if det else ""}>{clean(p["cells"][k])}</td>')
        return f'<tr data-i="{p["i"]}"{" class=" + chr(34) + "lh-inactive" + chr(34) if inactive else ""}>' + "".join(cells) + "</tr>"
    o.append('<tbody class="v2-active">' + "".join(row(p, False) for p in r["active"]) + "</tbody>")
    if r["il"]:
        o.append(f'<tbody class="v2-il"><tr class="lh-group"><td colspan="{len(ROSTER_COLS)}">IL slots</td></tr>'
                 + "".join(row(p, True) for p in r["il"]) + "</tbody>")
    o.append("</table></div>"
             f'<div class="lh-table-note">{clean(tp["size"])}. {clean(tp["note"])} GP is games played; Next is next '
             "week's games he will play. Tap a column to sort; Detailed adds L14, GL and Keep.</div>"
             + "".join(f'<div class="lh-table-note">{clean(x)}</div>' for x in tp["pending"]) + "</section>")
    return "".join(o)


def _keepers(tp: dict, ids: _Ids) -> str:
    t = tp["team"]
    o = ['<section class="lh-card v2-gap8" data-section="keepers"><div class="lh-sechead">'
         f'<h2 class="lh-eyebrow">Likely keepers</h2>{_info(ids, "keep", "Top " + tp["keep_line"] + " by keep chance")}</div>']
    for k in tp["keepers"]:
        o.append(f'<div class="v2-keep {t["cls"]}"><span class="lh-rank__n">{clean(k["rank"])}</span>'
                 f'<span class="v2-minw">{_pl(k["name"], k["card"])}<span class="lh-sub">{clean(k["meta"])}</span></span>'
                 f'<span class="lh-bar-h" role="img" aria-label="Keep chance {clean(k["keep"])}">'
                 f'<span style="width:{clean(k["w"])}"></span></span>'
                 f'<span class="lh-num v2-keepv">{clean(k["keep"])}</span></div>')
    o.append("</section>")
    return "".join(o)


def _team_page(tp: dict, vm: dict, ids: _Ids) -> str:
    t = tp["team"]
    k = tp["kpi"]
    o = [f'<section class="v2-screen" data-route="{clean(tp["route"])}" data-detail="1" hidden>',
         _topbar("#/teams", "Teams", vm["age"]),
         f'<div class="v2-hdr-team">{_mono(t, "72")}<div class="v2-minw"><h1 class="v2-hdr-name">{clean(t["team"])}</h1>'
         f'<span class="lh-meta">{clean(tp["sub"])}</span></div></div><div class="v2-stack">',
         _seg("team", [("roster", "Roster"), ("schedule", "Schedule"), ("moves", "Moves"), ("keepers", "Keepers")])]
    # roster
    o.append('<div class="v2-pane" data-pane-of="roster"><div class="v2-cols"><div class="v2-col"><div class="lh-kpis">'
             + _kpi(k["odds"], t, ids, "odds", _spark(tp["spark"], tp["spark_aria"]))
             + _kpi(k["win"], t, ids, "win") + _kpi(k["pf"], t, ids, "pf") + _kpi(k["adds"], t, ids, "adds")
             + "</div>" + _keepers(tp, ids) + '</div><div class="v2-col">' + _roster(tp, ids) + "</div></div></div>")
    # schedule
    o.append('<div class="v2-pane" data-pane-of="schedule" hidden><section class="lh-card v2-gap8">'
             '<div class="lh-sechead"><h2 class="lh-eyebrow">Games, next 3 weeks</h2></div>'
             + _heat(tp["sched"], vm["sched_cols"], total=False, label_of=lambda r: _pl(r["name"], r["card"]))
             + f'<span class="lh-sub">{clean(vm["sched_note"])}</span></section></div>')
    # moves
    o.append('<div class="v2-pane" data-pane-of="moves" hidden><section class="lh-card v2-gap8">'
             '<div class="lh-sechead"><h2 class="lh-eyebrow">Moves</h2><span class="lh-meta">newest first</span></div>')
    if not tp["moves"]:
        o.append('<p class="v2-p">No moves this season.</p>')
    for mv in tp["moves"]:
        o.append('<div class="lh-divider v2-move"><div class="v2-minw">'
                 f'<span class="lh-sub">{clean(mv["week"])} &middot; {clean(mv["day"])} {clean(mv["date"])} &middot; '
                 f'{clean(mv["time"])}</span>'
                 + "".join(f'<span class="v2-mvp"><span class="v2-mk v2-mk--{clean(x["kind"])}">{clean(x["marker"])}</span>'
                           f'{_segs(x["segs"]) if x.get("segs") else clean(x["text"])}</span>' for x in mv["parts"])
                 + (f'<span class="lh-sub">{clean(mv["note"])}</span>' if mv["note"] else "")
                 + f'</div><span class="lh-status lh-status--neutral">{clean(mv["state"])}</span></div>')
    o.append("</section></div>")
    # keepers
    o.append('<div class="v2-pane" data-pane-of="keepers" hidden><section class="lh-card lh-card--flush">'
             f'<div class="lh-sechead v2-pad"><h2 class="lh-eyebrow">Keep chance</h2>{_info(ids, "keep")}</div>'
             '<table class="lh-table"><thead><tr><th>Player</th><th>Keep</th><th>Rank</th></tr></thead><tbody>')
    for kk in tp["keep_all"]:
        o.append(f'<tr{" class=" + chr(34) + "lh-inactive" + chr(34) if kk["in_il"] else ""}><td>'
                 f'{_pl(kk["name"], kk["card"], "lh-name v2-tap")}<span class="lh-sub">{clean(kk["meta"])}</span></td>'
                 f'<td>{clean(kk["keep"])}</td><td>{clean(kk["rank"])}</td></tr>')
    o.append(f'</tbody></table><div class="lh-table-note">Rank is his place on the team by keep chance; the top '
             f'{clean(tp["keep_line"])} are the likely keepers.</div></section></div>')
    o.append("</div></section>")
    return "".join(o)


def _matchup_page(mu: dict, vm: dict, ids: _Ids) -> str:
    o = [f'<section class="v2-screen" data-route="{clean(mu["route"])}" data-detail="1" hidden>',
         _topbar("#/matchups", "Matchups", vm["age"]), '<div class="v2-mhead">']
    for s in mu["sides"]:
        t = s["team"]
        o.append(f'<div class="v2-mside {t["cls"]}">{_mono(t, "36")}<span class="v2-minw">'
                 f'<a class="lh-mrow__name v2-tap" href="{t["href"]}">{clean(s["name"])}</a>'
                 f'<span class="lh-sub">{clean(s["manager"])} &middot; {clean(s["record"])} &middot; proj {clean(s["proj"])}</span>'
                 f'</span><span class="v2-score">{clean(s["now"])}</span></div>')
    a, b = mu["sides"]
    o.append(f'<span class="lh-winbar" role="img" aria-label="{clean(mu["bar_aria"])}">'
             f'<span class="{a["team"]["cls"]}" style="width:{clean(mu["bar_a"])}"></span><span class="{b["team"]["cls"]}"></span></span>'
             f'<span class="v2-wbar-l"><span class="{a["team"]["cls"]} lh-team-text">{clean(a["team"]["mono"])} {clean(a["win"])}</span>'
             f'{_info(ids, "win")}'
             f'<span class="{b["team"]["cls"]} lh-team-text">{clean(b["team"]["mono"])} {clean(b["win"])}</span></span>'
             f'<span class="lh-meta">{clean(mu["sub"])}</span></div><div class="v2-stack">')
    o.append(_seg("matchup", [("summary", "Summary"), ("win", "Win %"), ("flow", "Game flow"), ("lines", "Lines")]))
    # summary
    o.append('<div class="v2-pane" data-pane-of="summary"><section class="lh-card">')
    for p in mu["paras"]:
        o.append('<div class="v2-para">' + (f'<h3 class="lh-eyebrow">{clean(p["head"])}</h3>' if p["head"] else "")
                 + f'<p class="v2-p">{clean(p["text"])}</p></div>')
    o.append('</section><section class="lh-card v2-gap8"><h2 class="lh-eyebrow">Starts left</h2>'
             + (_heat(mu["starts"]["rows"], [{"label": d["dow"], "sub": d["day"]} for d in mu["starts"]["days"]],
                      total=True, label_of=lambda r: f'<span class="lh-swatch"></span>{clean(r["team"]["team"])}')
                if mu["starts"]["days"] else '<p class="v2-p">No days left this week.</p>')
             + f'<span class="lh-sub">{clean(mu["starts"]["note"])}</span></section>'
             '<section class="lh-card v2-gap8"><h2 class="lh-eyebrow">Who\'s missing</h2>')
    if not mu["missing"]:
        o.append('<p class="v2-p">Everyone is available.</p>')
    for x in mu["missing"]:
        o.append(f'<div class="v2-missing lh-divider {x["team"]["cls"]}"><span class="lh-swatch"></span>'
                 f'<span class="v2-minw">{_pl(x["name"], x["card"])}<span class="lh-sub">{clean(x["sub"])}</span></span>'
                 f'{_chip(x["chip"])}</div>')
    o.append("</section></div>")
    # win %
    o.append('<div class="v2-pane" data-pane-of="win" hidden><section class="lh-card v2-gap8"><div class="lh-sechead">'
             f'<h2 class="lh-eyebrow">Win chance this week</h2>{_info(ids, "win", a["team"]["team"])}</div>'
             + _chart(mu["win"], ids.next("ch")) + "</section></div>")
    # game flow
    o.append('<div class="v2-pane" data-pane-of="flow" hidden><section class="lh-card v2-gap8"><div class="lh-sechead">'
             '<h2 class="lh-eyebrow">Game flow</h2><span class="lh-meta">Points by day &middot; dashed = projected</span></div>'
             + _chart(mu["flow"], ids.next("ch")) + "</section></div>")
    # lines
    o.append('<div class="v2-pane" data-pane-of="lines" hidden><section class="lh-card v2-gap8"><div class="lh-sechead">'
             f'<h2 class="lh-eyebrow">The lines</h2>{_info(ids, "lines")}</div><div class="lh-kpis">')
    for r in mu["lines"]["rows"]:
        o.append(f'<div class="lh-kpi lh-kpi--nested"><span class="lh-label">{clean(r["label"])}</span>'
                 f'<span class="lh-kpi__value">{clean(r["value"])}</span><span class="lh-kpi__ctx">{clean(r["ctx"])}</span></div>')
    o.append(f'</div><span class="lh-sub">{clean(mu["lines"]["note"])}</span></section></div>')
    o.append("</div></section>")
    return "".join(o)


# =============================================================================
# the page
# =============================================================================

def render(vm: dict, *, cards: dict = None) -> str:
    """The page as one HTML string. cards: the preview's plaintext card bundle
    (hub_cards.preview_bundle), embedded only in preview."""
    from . import tokens
    if cards is not None and vm["mode"] != "preview":
        raise ValueError("the cards are embedded only in the plaintext preview")
    ids = _Ids()
    o = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">', '<meta name="robots" content="noindex">',
         f"<title>{clean(vm['title'])}</title>", f"<style>{tokens.css(LAYOUT_CSS)}</style></head><body>",
         f'<div class="v2-app" id="hub" data-epoch="{vm["epoch"]}" data-stale-hours="{vm["stale_hours"]}">']
    # header (tab roots), then the banners, then the tab bar (a top bar on desktop)
    o.append('<header class="lh-header lh-on-dark v2-hdr" id="app-header"><div class="v2-stale-hd">'
             f'<span class="v2-minw"><span class="lh-header__title">{clean(vm["title"])}</span>'
             f'<span class="lh-header__date">{clean(vm["week_label"])}</span></span></div>'
             f'<div class="lh-fresh"><span class="lh-fresh__dot" id="fresh-dot"{" hidden" if vm["stale"] else ""}></span>'
             f'<span>Updated <span class="v2-age">{clean(vm["age"])}</span> ({clean(vm["generated_text"])})</span></div>'
             f'<span class="v2-lock">{clean(vm["lock"])}</span></header>')
    o.append('<div class="v2-stale-wrap">')
    if vm["mismatch"]:
        o.append(f'<div class="v2-banner" role="status"><b>Do not price anything off this page.</b> '
                 f'{clean(vm["mismatch"])}.</div>')
    if vm["engine_note"]:
        o.append(f'<div class="v2-calm">{clean(vm["engine_note"])}</div>')
    if vm.get("closing_note"):                     # H52: a refused closing line, the night went on
        o.append(f'<div class="v2-calm">{clean(vm["closing_note"])}</div>')
    o.append(f'<div class="lh-stale" id="stale" role="status"{"" if vm["stale"] else " hidden"}>{WARN}'
             f'<span>{clean(vm["stale_text"])}</span></div></div>')
    o.append('<nav class="lh-tabbar" aria-label="Main">' + "".join(
        f'<a href="{t["href"]}" data-tab="{t["key"]}"{" aria-current=" + chr(34) + "page" + chr(34) if t["key"] == "home" else ""}>'
        f'{_icon(ICONS[t["key"]], "22")}<span>{clean(t["label"])}</span></a>' for t in vm["tabs"]) + "</nav>")
    o.append('<main class="v2-main">')

    # ---------------------------------------------------------------- home
    o.append('<section class="v2-screen" data-route="home">')
    if vm["issue"]:
        k, v = vm["issue"]["attr"]
        o.append(f'<button type="button" class="lh-issuebar" {k}="{clean(v)}"><span class="v2-ib">{DOC}'
                 f'<span class="v2-note"><strong>Latest issue</strong> &middot; {clean(vm["issue"]["text"])}</span></span>'
                 f'{CHEV}</button>')
    o.append('<div class="v2-stack"><div class="v2-cols"><div class="v2-col">'
             '<section class="v2-sec" data-section="matchups"><div class="lh-sechead">'
             f'<h2 class="lh-eyebrow">This week\'s matchups</h2><span class="lh-meta lh-meta--canvas">{clean(vm["clock"])}</span></div>'
             + "".join(_matchup_card(mu) for mu in vm["matchups"]) + "</section>"
             + _ranking(vm, ids) + '</div><div class="v2-col">'
             '<section class="v2-sec" data-section="teams"><div class="lh-sechead"><h2 class="lh-eyebrow">Teams</h2></div>'
             '<div class="v2-teamgrid">' + "".join(_team_card(tp, vm["odds_label"]) for tp in vm["team_pages"])
             + "</div></section>" + _trade(vm) + "</div></div></div></section>")

    # ---------------------------------------------------------------- matchups
    g = vm["grid3"]
    o.append('<section class="v2-screen" data-route="matchups" hidden><div class="v2-stack"><div class="v2-cols">'
             '<section class="v2-sec"><div class="lh-sechead">'
             f'<h2 class="lh-eyebrow">This week\'s matchups</h2><span class="lh-meta lh-meta--canvas">{clean(vm["clock"])}</span></div>'
             + "".join(_matchup_card(mu) for mu in vm["matchups"]) + "</section>"
             '<section class="lh-card v2-gap8" data-section="grid"><div class="lh-sechead"><h2 class="lh-eyebrow">Games grid</h2>'
             '<span class="lh-meta">starts per week</span></div>'
             + _heat(g["rows"], g["cols"], total=False,
                     label_of=lambda r: f'<a class="v2-heat-a v2-tap {r["team"]["cls"]}" href="{r["team"]["href"]}">'
                                        f'<span class="lh-swatch"></span>{clean(r["team"]["team"])}</a>')
             + f'<span class="lh-sub">{clean(g["note"])}</span></section></div></div></section>')
    for mu in vm["matchups"]:
        o.append(_matchup_page(mu, vm, ids))

    # ---------------------------------------------------------------- teams
    o.append('<section class="v2-screen" data-route="teams" hidden><div class="v2-stack"><section class="v2-sec">'
             '<div class="lh-sechead"><h2 class="lh-eyebrow">Teams</h2></div><div class="v2-teamgrid">'
             + "".join(_team_card(tp, vm["odds_label"]) for tp in vm["team_pages"]) + "</div></section></div></section>")
    for tp in vm["team_pages"]:
        o.append(_team_page(tp, vm, ids))

    # ---------------------------------------------------------------- placeholders
    for ph in vm["placeholders"]:
        o.append(f'<section class="v2-screen" data-route="{ph["key"]}" hidden><div class="v2-stack"><section class="lh-card">'
                 f'<h2 class="lh-eyebrow">{clean(ph["label"])}</h2><p class="v2-p">{clean(ph["text"])}</p>'
                 + "".join(f'<a class="lh-link" href="{clean(x["href"])}">{clean(x["t"])} on the current hub &rsaquo;</a>'
                           for x in ph["links"]) + "</section></div></section>")
    o.append("</main>")
    o.append(f'<footer class="v2-foot">{clean(vm["footer"])}'
             + (' &middot; <button type="button" class="v2-forget v2-tap" id="forget">Forget this phone</button>'
                if vm["mode"] == "publish" else " &middot; local preview, not published") + "</footer>")
    o.append('<div class="v2-issue" id="issue-view" hidden><div class="v2-topbar"><button type="button" class="lh-back" '
             f'id="issue-close">{BACK}Back to the hub</button></div><iframe id="issue-frame" title="Newsletter"></iframe></div>')
    o.append("</div>")
    if cards is not None:
        blob = json.dumps(cards, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
        o.append(f'<script type="application/json" id="hub-cards">{blob}</script>')
    o.append(f"<script>{PAGE_JS}</script></body></html>")
    return "\n".join(o)


PAGE_JS = r"""
(function(){
var hub=document.getElementById('hub');
var header=document.getElementById('app-header');
var seen={};                       // segmented-tab choice per kind, for the session
function screens(){return document.querySelectorAll('.v2-screen');}
function route(){
  var r=location.hash.replace(/^#\/?/,'')||'home';
  var target=null,all=screens();
  for(var i=0;i<all.length;i++){if(all[i].getAttribute('data-route')===r){target=all[i];}}
  if(!target){r='home';for(var j=0;j<all.length;j++){if(all[j].getAttribute('data-route')==='home'){target=all[j];}}}
  for(var k=0;k<all.length;k++){all[k].hidden=(all[k]!==target);}
  header.hidden=!!target.getAttribute('data-detail');
  var tab=r.split('/')[0];
  var ts=document.querySelectorAll('.lh-tabbar a');
  for(var t=0;t<ts.length;t++){if(ts[t].getAttribute('data-tab')===tab){ts[t].setAttribute('aria-current','page');}
    else{ts[t].removeAttribute('aria-current');}}
  var segs=target.querySelectorAll('.lh-seg');
  for(var s=0;s<segs.length;s++){var kind=segs[s].getAttribute('data-seg');if(seen[kind]){pick(segs[s],seen[kind]);}}
  window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);
function age(){
  var ms=Date.now()-Number(hub.getAttribute('data-epoch'));
  var lim=Number(hub.getAttribute('data-stale-hours'))*3600000,w;
  var m=Math.floor(ms/60000);
  if(ms<60000){w='just now';}
  else if(m<60){w=m+(m===1?' minute':' minutes')+' ago';}
  else if(ms<lim){var h=Math.round(ms/3600000);w=h+(h===1?' hour':' hours')+' ago';}
  else{var d=Math.round(ms/86400000);w=d+(d===1?' day':' days')+' ago';}
  var as=document.querySelectorAll('.v2-age');for(var i=0;i<as.length;i++){as[i].textContent=w;}
  document.getElementById('stale').hidden=!(ms>=lim);
  var dot=document.getElementById('fresh-dot');if(dot){dot.hidden=(ms>=lim);}
}
age();setInterval(age,60000);
function pick(seg,key){
  var bs=seg.querySelectorAll('button');
  for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-selected',String(bs[i].getAttribute('data-pane')===key));}
  var root=seg.parentNode,ps=root.querySelectorAll(':scope > [data-pane-of]');
  for(var j=0;j<ps.length;j++){ps[j].hidden=(ps[j].getAttribute('data-pane-of')!==key);}
}
function sortTable(tbl,key){
  var orders=JSON.parse(tbl.getAttribute('data-orders'));
  var dir=(tbl.getAttribute('data-sort')===key)?-Number(tbl.getAttribute('data-dir')):1;
  var ord=orders[key].slice();if(dir<0){ord.reverse();}
  var bodies=tbl.querySelectorAll('tbody');
  for(var b=0;b<bodies.length;b++){
    var rows={},rs=bodies[b].querySelectorAll('tr[data-i]');
    for(var i=0;i<rs.length;i++){rows[rs[i].getAttribute('data-i')]=rs[i];}
    for(var j=0;j<ord.length;j++){var r=rows[String(ord[j])];if(r){bodies[b].appendChild(r);}}
  }
  tbl.setAttribute('data-sort',key);tbl.setAttribute('data-dir',String(dir));
  var ths=tbl.querySelectorAll('th[data-k]');
  for(var t=0;t<ths.length;t++){
    var on=ths[t].getAttribute('data-k')===key,ar=ths[t].querySelector('.v2-arrow');
    var down=(key==='name')?(dir<0):(dir>0);
    if(on){ths[t].setAttribute('aria-sort',down?'descending':'ascending');ar.textContent=down?' \u25be':' \u25b4';}
    else{ths[t].removeAttribute('aria-sort');ar.textContent='';}
  }
}
function readout(hit){
  var svg=hit.closest('svg'),sel=svg.querySelector('.v2-sel');
  var cy=hit.getAttribute('data-cy');
  if(cy){sel.setAttribute('cx',hit.getAttribute('data-cx'));sel.setAttribute('cy',cy);}
  var ro=document.querySelector('[data-readout="'+svg.getAttribute('data-chart')+'"]');
  ro.children[0].textContent=hit.getAttribute('data-head');ro.children[1].textContent=hit.getAttribute('data-body');
}
function closeTips(except){
  var bs=document.querySelectorAll('.lh-info > button[aria-expanded="true"]');
  for(var i=0;i<bs.length;i++){if(bs[i]!==except){bs[i].setAttribute('aria-expanded','false');
    document.getElementById(bs[i].getAttribute('aria-controls')).hidden=true;}}
}
// player cards (task 40): the current card, as hub_page loads it
var cardsP=null;
function cardsBundle(){
  if(cardsP){return cardsP;}
  var el=document.getElementById('hub-cards');
  var p=el?Promise.resolve(JSON.parse(el.textContent)):
    ((window.HUB&&window.HUB.cards)?window.HUB.cards():Promise.reject(new Error('no cards')));
  cardsP=p.then(function(b){
    return (b.code?window.HUB.part(b.code):Promise.resolve(b)).then(function(code){
      var st=document.createElement('style');st.textContent=code.css;document.head.appendChild(st);
      var sc=document.createElement('script');sc.textContent=code.js;document.body.appendChild(sc);
      window.pcPhotoLoader=(window.HUB&&window.HUB.photo)?function(ref){
        return window.HUB.photo(ref).catch(function(err){if(err&&err.message==='gone'){movedBox();}throw err;});}:null;
      return b;});});
  cardsP.catch(function(){cardsP=null;});
  return cardsP;
}
function openCard(key){
  cardsBundle().then(function(b){
    var c=b.cards[key];
    if(!c){throw new Error('no card');}
    if(c.hist&&!c.histIn){return window.HUB.part(c.hist).then(function(prior){
      c.sparkline=prior.concat(c.sparkline);c.histIn=true;return c;});}
    return c;
  }).then(function(c){window.pcShow(c);},function(err){
    if(err&&err.message==='gone'){movedBox();return;}
    alertBox((err&&err.message==='old browser')?'This browser is too old to open player cards.':
      'That player card could not be opened.');});
}
function alertBox(msg){var d=document.createElement('div');d.className='lh-stale';d.setAttribute('role','status');
  d.textContent=msg;hub.insertBefore(d,hub.firstChild);}
function movedBox(){
  if(document.getElementById('hub-moved')){return;}
  var d=document.createElement('div');d.className='lh-stale';d.id='hub-moved';d.setAttribute('role','status');
  d.appendChild(document.createTextNode('The hub has been updated: reload the page to open player cards. '));
  var b=document.createElement('button');b.type='button';b.className='lh-btn';b.textContent='Reload';
  b.addEventListener('click',function(){if(window.HUB&&window.HUB.reload){window.HUB.reload();}else{location.reload();}});
  d.appendChild(b);hub.insertBefore(d,hub.firstChild);
}
function openFrame(url){document.getElementById('issue-frame').src=url;document.getElementById('issue-view').hidden=false;}
document.addEventListener('click',function(e){
  var t=e.target.closest('[data-card]');
  if(t){e.preventDefault();e.stopPropagation();openCard(t.getAttribute('data-card'));return;}
  t=e.target.closest('.lh-info > button');
  if(t){var open=t.getAttribute('aria-expanded')==='true';closeTips(t);
    t.setAttribute('aria-expanded',String(!open));document.getElementById(t.getAttribute('aria-controls')).hidden=open;return;}
  if(!e.target.closest('.lh-info__pop')){closeTips(null);}
  t=e.target.closest('.lh-seg button');
  if(t){var seg=t.closest('.lh-seg');seen[seg.getAttribute('data-seg')]=t.getAttribute('data-pane');pick(seg,t.getAttribute('data-pane'));return;}
  t=e.target.closest('.lh-toggle button');
  if(t){var tg=t.closest('.lh-toggle'),bs=tg.querySelectorAll('button');
    for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i]===t));}
    var mode=t.getAttribute('data-mode');seen['detail']=mode;
    var tb=document.querySelectorAll('.v2-rt');for(var j=0;j<tb.length;j++){tb[j].setAttribute('data-mode',mode);}
    var tgs=document.querySelectorAll('.lh-toggle button');
    for(var k=0;k<tgs.length;k++){tgs[k].setAttribute('aria-pressed',String(tgs[k].getAttribute('data-mode')===mode));}
    return;}
  t=e.target.closest('[data-sort]');
  if(t){sortTable(t.closest('table'),t.getAttribute('data-sort'));return;}
  t=e.target.closest('.lh-c-hit');
  if(t){readout(t);return;}
  t=e.target.closest('[data-href]');
  if(t){openFrame(t.getAttribute('data-href'));return;}
  t=e.target.closest('[data-issue]');
  if(t){var f=t.getAttribute('data-issue');if(!window.HUB){return;}
    t.disabled=true;
    window.HUB.openIssue(f).then(function(url){t.disabled=false;openFrame(url);},
      function(){t.disabled=false;alertBox('That issue could not be opened.');});return;}
  if(e.target.closest('#issue-close')){document.getElementById('issue-view').hidden=true;
    document.getElementById('issue-frame').removeAttribute('src');return;}
  if(e.target.closest('#forget')){if(window.HUB){window.HUB.forget();}return;}
});
// keyboard focus on a chart point reads it (its ring marks the focus)
document.addEventListener('focusin',function(e){
  var t=e.target;if(t.classList&&t.classList.contains('lh-c-hit')){readout(t);}
});
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){closeTips(null);return;}
  var t=e.target;
  if(t.classList&&t.classList.contains('lh-c-hit')&&(e.key==='Enter'||e.key===' ')){e.preventDefault();readout(t);}
});
// scrub: a finger moving over a chart reads the strip under it
document.addEventListener('pointermove',function(e){
  if(e.pointerType==='mouse'&&!e.buttons){return;}
  var el=document.elementFromPoint(e.clientX,e.clientY);
  if(el&&el.classList&&el.classList.contains('lh-c-hit')){readout(el);}
});
// preview only (#check130 after the route): the page at 130% root size, and
// every clipped text in the roster tables and matchup cards listed on top
function check130(){
  if(location.search.indexOf('check130')<0){return;}
  // every element's text 1.3x (the type is in px, so a root size alone would
  // change nothing): what a phone's larger-text setting does
  var all=document.querySelectorAll('body *'),fs=[];
  for(var a=0;a<all.length;a++){fs.push(parseFloat(getComputedStyle(all[a]).fontSize));}
  for(var b=0;b<all.length;b++){all[b].style.fontSize=(fs[b]*1.3)+'px';}
  setTimeout(function(){
    var els=document.querySelectorAll('.v2-rt td, .v2-rt th, .v2-mcard *, .v2-tcard *, .lh-kpi *'),bad=[];
    for(var i=0;i<els.length;i++){var x=els[i];
      if(x.offsetParent===null||!x.getClientRects().length||x.closest('[hidden]')){continue;}
      if(x.scrollWidth>x.clientWidth+1||x.scrollHeight>x.clientHeight+1){
        var cs=getComputedStyle(x);if(cs.overflow!=='visible'||cs.textOverflow==='ellipsis'){bad.push((x.className||x.tagName)+': '+x.textContent.slice(0,40));}}
      var box=x.closest('.lh-kpi, .v2-mcard, .v2-tcard');
      if(box&&x.getBoundingClientRect().right>box.getBoundingClientRect().right+1){bad.push((x.className||x.tagName)+' (past its tile): '+x.textContent.slice(0,40));}}
    var d=document.createElement('div');d.className='v2-check';
    d.textContent='Text-size check at 130%: '+(bad.length?bad.length+' clipped on this screen:\n'+bad.join('\n'):'nothing clipped on this screen.');
    hub.insertBefore(d,hub.firstChild);},300);
}
route();check130();
})();
"""
