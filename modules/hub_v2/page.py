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
#/players, #/players/<key>, #/players/compare/<a>[/<b>], #/market (4c3: page_market.py), #/league. Every screen is in the page; the script shows
the one the hash names (an unknown hash shows Home), so the back button
works and a deep link opens its screen after the unlock (the decrypt shell
keeps the hash).

PLAYER NAMES open the NEW player card (4c1): #/players/<key>, the card
rendered at build time (page_players.card_html) -- inline in preview, its
encrypted file published (HUB.cards() gives the index, HUB.part the card,
HUB.photo the headshot) -- with the 404 message "The hub has been updated:
reload the page to open player cards." Players, the card and Compare are
page_players.py; routes #/players, #/players/<key>, #/players/compare/<a>
(pick the second player) and #/players/compare/<a>/<b>.

MODES: preview (plaintext, output/hub_v2_preview.html, links to the current
page's sections from the placeholders) and publish (inside the decrypt shell;
publish.py; issues open through window.HUB).
"""

from __future__ import annotations

import json
from datetime import datetime

from .text import clean
from .infotips import tip
from . import page_players as pp
from . import page_market as pm
from . import page_league as pl

# tap targets: an interactive element carries one of these classes (or sits
# in one of TAP_PARENTS); each class's CSS gives it at least tap-min (or
# row-min) of height. tests/test_hub_v2.py checks both halves. Chart tap
# strips (lh-c-hit) are the design's per-point hit areas: full plot height,
# keyboard-reachable, as wide as the point's share of the axis.
TAP_CLASSES = ("lh-card", "lh-rank", "lh-issuebar", "lh-back", "lh-link", "lh-iconbtn", "v2-tap", "lh-c-hit",
               "v2-fchip", "v2-btn", "v2-pick", "v2-bar", "v2-gtile", "v2-cell", "v2-dchip", "v2-ev-hit") + pm.TAP_CLASSES + pl.TAP_CLASSES
# 4c2: the roster table's Detailed chip groups (roster.GROUPS, plus "all"): the
# CSS shows a column when the table's data-group is one of its groups
DETAIL_GROUPS = ("value", "form", "schedule", "health", "keeper", "profile", "all")
TAP_PARENTS = ("lh-tabbar", "lh-seg", "lh-toggle", "lh-info")
# 5c (the tap sweep): a .v2-tap's 44-point area (its ::after) is centred on
# it, so where two tap targets sit one above the other (a player's name over
# his team chip: the draft, awards, Market's lists, trades) the later one's
# area lay over the bottom or top of the other: a tap on the drawn name
# opened the team. CSS cannot order every area under every target (the areas
# would fall under the rows' boxes), so the page's first click listener does
# it (PAGE_JS, "a tap reaches what is drawn"): a tap that reached a .v2-tap
# through its area, on a point where another tap target is drawn, goes to
# that target instead.

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
.v2-stale-hd{display:flex;gap:var(--space-8);align-items:center;justify-content:space-between}
.v2-lock{font-size:var(--type-small-size);line-height:var(--type-small-lh);color:var(--ink-on-dark-3)}
.lh-tabbar{position:fixed;left:0;right:0;bottom:0;z-index:4}
.lh-seg button{min-height:var(--tap-min)}
.v2-tap{position:relative;cursor:pointer}
.v2-tap::after{content:"";position:absolute;left:0;right:0;top:50%;height:var(--tap-min);min-width:var(--tap-min);transform:translateY(-50%)}
button.v2-pl{all:unset;position:relative;cursor:pointer;color:var(--ink);font-weight:var(--type-row-weight);text-decoration:underline dotted var(--axis-strong);text-underline-offset:var(--space-2)}
button.lh-name{all:unset;position:relative;cursor:pointer;font-size:var(--type-row-size);font-weight:var(--type-row-weight);display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink)}
.v2-topbar{background:var(--surface);border-bottom:var(--hairline) solid var(--line);padding:0 var(--space-16);display:flex;align-items:center;justify-content:space-between;gap:var(--space-8)}
.v2-mono-72{--s:var(--mono-72)}
.v2-mono-36{--s:var(--mono-36)}
.v2-mono-28{--s:var(--mono-28)}
.v2-pic{position:relative}
.v2-pic::after{content:"";position:absolute;inset:0;border-radius:inherit;background:transparent center/cover no-repeat}
.v2-bigpic{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:inherit;opacity:0}
.v2-bigpic-on .v2-bigpic{opacity:1}
.v2-bigpic-on::after{content:none}
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
.v2-forget{all:unset;position:relative;cursor:pointer;color:var(--accent);font-weight:700}
.v2-ask{position:fixed;left:0;right:0;bottom:var(--tabbar-height);z-index:12;display:flex;justify-content:center;padding:var(--space-16)}
.v2-ask-box{width:100%;max-width:var(--reading-max);background:var(--dark);color:var(--ink-on-dark);border-radius:var(--radius-14);padding:var(--space-14) var(--space-16);display:flex;flex-direction:column;gap:var(--space-12);font-size:var(--type-body-size);line-height:var(--type-body-lh);text-align:left}
.v2-ask-row{display:flex;gap:var(--space-8);justify-content:flex-end}
.lh-info__pop{max-width:calc(100vw - 2 * var(--space-16))}
.v2-banner{background:var(--status-out-tint);color:var(--status-out);padding:var(--space-10) var(--space-16);font-size:var(--type-body-size);font-weight:700}
.v2-calm{background:var(--surface-sunken);color:var(--ink-2);padding:var(--space-10) var(--space-16);font-size:var(--type-body-size)}
.v2-check{background:var(--dark);color:var(--ink-on-dark);padding:var(--space-10) var(--space-16);font-size:var(--type-meta-size);white-space:pre-wrap}
.lh-heat__cell.v2-cell{min-height:var(--tap-min);height:auto;width:100%;border:0;padding:0;font-family:inherit;cursor:pointer}
.v2-cell[aria-expanded="true"]{outline:var(--hairline) solid var(--ink-strong);outline-offset:var(--space-2)}
.lh-chart .v2-ev--up{stroke:var(--up)}
.lh-chart .v2-ev-hit{fill:transparent;cursor:pointer;outline:none}
.lh-chart .v2-ev-hit:focus-visible{stroke:var(--accent);stroke-width:2}
.lh-table th button.v2-tap{position:relative}
.v2-rt th button.v2-tap{min-width:var(--tap-min);justify-content:flex-end}
.v2-rt th.v2-sticky button.v2-tap{justify-content:flex-start}
.v2-rt .v2-dc{display:none}
.v2-rt[data-mode="detailed"] .v2-sc{display:none}
.v2-dchips{display:flex;gap:var(--space-6);overflow-x:auto;padding:0 var(--space-14) var(--space-8)}
button.v2-dchip{min-height:var(--tap-min);padding:0 var(--space-12);border:var(--hairline) solid var(--line);border-radius:var(--radius-pill);background:var(--surface);font-family:inherit;font-size:var(--type-meta-size);font-weight:800;color:var(--ink-2);white-space:nowrap;cursor:pointer}
button.v2-dchip[aria-selected="true"]{background:var(--dark);color:var(--ink-on-dark);border-color:var(--dark)}
.v2-gnote{display:none}
.v2-ovrd{font-size:var(--type-small-size);font-weight:700;margin-left:var(--space-2)}
.v2-ovrd--up{color:var(--up)}.v2-ovrd--down{color:var(--down)}.v2-ovrd--flat{color:var(--ink-3)}
.v2-rt .lh-spark{display:inline-block;vertical-align:middle}
.v2-lcard{text-decoration:none;color:var(--ink);gap:var(--space-8)}
.v2-lline{font-size:var(--type-meta-size);color:var(--ink-2)}
.v2-lverdict{font-size:var(--type-meta-size);font-weight:800;color:var(--ink)}
.v2-won{font-weight:800}
@media (min-width:{{bp-mid}}){
 .lh-kpis{grid-template-columns:repeat(4,minmax(0,1fr))}
}
@media (min-width:{{bp-wide}}){
 .v2-app{padding-bottom:0}
 .v2-ask{bottom:0}
 .v2-hdr{order:-3}
 .v2-stale-wrap{order:-2}
 .lh-tabbar{order:-1;position:sticky;top:0;bottom:auto;height:auto;border-top:0;border-bottom:var(--hairline) solid var(--line);display:flex;justify-content:center;gap:var(--space-24);padding:var(--space-4) var(--space-16)}
 .lh-tabbar a{flex-direction:row;gap:var(--space-6);font-size:var(--type-body-size);padding:0 var(--space-8)}
 .v2-cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}
 .v2-cols .lh-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
}
"""
# 4c2: one rule per Detailed chip group: the table shows a column when its
# data-group is one of the column's groups; the group's note shows likewise
LAYOUT_CSS += "".join(f'.v2-rt[data-mode="detailed"][data-group="{g}"] .v2-g-{g}{{display:table-cell}}\n'
                      f'.v2-rtwrap[data-mode="detailed"][data-group="{g}"] .v2-gnote[data-gnote="{g}"]'
                      '{display:block}\n' for g in DETAIL_GROUPS)


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


def _pictures_style(pics: list) -> str:
    """4c3: each team picture once, as its slot's TeamMark background (data
    URIs: the page stays offline; encrypted in publish mode). Only base64
    characters reach the style, so nothing in it can close it."""
    import re as _re
    rules = []
    for p in pics:
        if not _re.fullmatch(r"data:image/(jpeg|png|gif|webp);base64,[A-Za-z0-9+/=]+", p["uri"]) \
                or p["slot"] not in ("blue", "orange", "teal", "plum"):
            raise ValueError(f"a team picture that is not a base64 image data URI (slot {p['slot']!r})")
        rules.append(f'.v2-pic-{p["slot"]}::after{{background-image:url("{p["uri"]}")}}')
    return f'<style id="v2-pics">{"".join(rules)}</style>' if rules else ""


def _pl(name: str, card, cls: str = "v2-pl v2-tap") -> str:
    """A player's name: a button that opens his current card when he has one."""
    if card:
        return f'<button type="button" class="{cls}" data-card="{clean(card)}">{clean(name)}</button>'
    return f'<span>{clean(name)}</span>'


def _mono(team: dict, size: str = "") -> str:
    """TeamMark: the monogram in the manager's colour, with his picture drawn
    over it when the page has one (4c3; v2-pic-<slot>, defined once in the
    page's pictures style). A picture that fails to draw leaves the monogram."""
    pic = f' v2-pic v2-pic-{team["slot"]}' if team.get("pic") else ""
    ref = team.get("pic_ref") if size == "72" else None      # 5b: the full picture, a lazy part
    big = f" data-pic='{clean(json.dumps(ref, separators=(',', ':')))}'" if ref else ""
    return f'<span class="lh-mono {team["cls"]}{" v2-mono-" + size if size else ""}{pic}"{big} aria-hidden="true">' \
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


LAZY_TOKEN = "@@v2-screen-part-{n}@@"


def _lazy(html: str, vm: dict) -> str:
    """5b (the first load): published, a screen whose route is in
    vm["lazy_screens"] (the team pages and last week's matchup pages,
    publish.LAZY_SCREENS) leaves the page: its content is kept in
    vm["_screen_html"] (publish.build seals each as a part) and the page
    keeps the screen's own tag, its top bar and "Opening...", with
    data-screen-part (LAZY_TOKEN, filled with the part's ref by
    publish.build). route() opens the part on the screen's first show and
    routes again. Anywhere else (the preview), the screen as it is."""
    import re as _re
    import html as _h
    lz = vm.get("lazy_screens")
    if not lz:
        return html
    m = _re.match(r'(<section class="v2-screen" data-route="([^"]+)"[^>]*>)(.*)</section>\Z', html, _re.S)
    if not m or _h.unescape(m.group(2)) not in lz:
        return html
    store = vm.setdefault("_screen_html", [])
    n = len(store)
    store.append({"route": _h.unescape(m.group(2)), "html": m.group(3)})
    top = _re.match(r'<div class="v2-topbar">.*?</div>', m.group(3), _re.S)
    return (m.group(1)[:-1] + f" data-screen-part='{LAZY_TOKEN.format(n=n)}'>" + (top.group(0) if top else "")
            + '<p class="v2-card-load v2-screen-load">Opening&hellip;</p></section>')


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
        o.append(f'<circle class="lh-c-event v2-ev--{clean(e["dir"])}" cx="{e["cx"]}" cy="{e["cy"]}" r="4"/>')
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
    for e in ch["events"]:                         # on top of the strips: a 44-px circle per marker
        o.append(f'<circle class="v2-ev-hit" cx="{e["cx"]}" cy="{e["cy"]}" r="22" tabindex="0" role="button" '
                 f'aria-label="{clean(e["label"])}"{_tip_attrs(e["tip"])}/>')
    o.append("</svg>")
    r0 = ch.get("readout0") or {"head": ch.get("empty") or "", "body": ""}
    o.append(f'<div class="lh-readout" aria-live="polite" data-readout="{cid}">'
             f'<span class="v2-readout-h">{clean(r0["head"])}</span> <span>{clean(r0["body"])}</span></div>')
    if ch.get("empty"):
        o.append(f'<p class="v2-p">{clean(ch["empty"])}</p>')
    return "".join(o)


def _tip_attrs(tip: dict) -> str:
    """The one tooltip (4c2): its three strings on the element that opens it."""
    return (f' data-tip-h="{clean(tip["h"])}" data-tip-b="{clean(tip["b"])}"'
            + (f' data-tip-f="{clean(tip["f"])}"' if tip.get("f") else "") + ' aria-expanded="false"')


def _tip_label(tip: dict, n: str) -> str:
    return clean(" \u00b7 ".join(x for x in (tip["h"], n, tip["b"], tip.get("f", "")) if x))


def _cell(c: dict) -> str:
    """A games-grid cell: a tap that opens its tooltip (the days, who starts)."""
    cls = "lh-s" + str(c["b"]) if c["b"] else "v2-s0"
    if not c.get("tip"):
        return f'<span class="lh-heat__cell {cls}">{clean(c["n"])}</span>'
    return (f'<button type="button" class="lh-heat__cell v2-cell {cls}"{_tip_attrs(c["tip"])} '
            f'aria-label="{_tip_label(c["tip"], c["n"])}">{clean(c["n"])}</button>')


def _heat(rows: list, cols: list, *, total: bool, label_of, total_head: dict = None) -> str:
    n = len(cols)
    cls = "v2-heat--tot" if total else "v2-heat"
    o = [f'<div class="v2-heat-rows"><div class="lh-heat {cls} v2-heat-h" style="--n:{n}"><span></span>']
    o += [f'<span><span>{clean(c["label"])}</span><span>{clean(c.get("sub", ""))}</span></span>' for c in cols]
    if total and total_head:                       # 5b: the games grid's Idle
        o.append(f'<span><span>{clean(total_head["label"])}</span><span>{clean(total_head.get("sub", ""))}</span></span>')
    elif total:
        o.append('<span>Total</span>')
    o.append("</div>")
    for r in rows:
        o.append(f'<div class="lh-heat {cls}{" " + r["team"]["cls"] if r.get("team") else ""}" style="--n:{n}">'
                 f'<span class="v2-heat-lab">{label_of(r)}</span>')
        o += [_cell(c) for c in r["cells"]]
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


SIMPLE_COLS = [("name", "Player", False), ("fppg", "FPPG", False), ("gp", "GP", False), ("proj", "Proj", False),
               ("next", "Next", False)]


def _dcell(c: dict) -> str:
    """A Detailed cell's inside: the engine's string; OVR with its weekly
    change; Trend as its sparkline (the view's geometry)."""
    if c.get("spark"):
        return _spark(c["spark"], c["aria"])
    t = clean(c["t"])
    if c.get("d"):
        t += f'<span class="v2-ovrd v2-ovrd--{clean(c["d"]["dir"])}">{clean(c["d"]["t"])}</span>'
    return t


def _roster(tp: dict, ids: _Ids) -> str:
    """The RosterTable: Simple (FPPG, GP, Proj, Next) and Detailed, whose chip
    row (Value, Form, Schedule, Health, Keeper, Profile, All) picks the columns
    shown; the name stays pinned and the table scrolls sideways. Every cell is
    a payload string; sorting uses the payload's orders."""
    r = tp["roster"]
    default = r["default"]
    groups = r["groups"]
    g0 = groups[0]["key"]
    o = [f'<section class="lh-card lh-card--flush v2-rtwrap" data-section="roster" data-mode="simple" '
         f'data-group="{clean(g0)}"><div class="lh-sechead v2-pad">'
         f'<h2 class="lh-eyebrow">Roster</h2>{_info(ids, "proj")}'
         '<div class="lh-toggle" role="group" aria-label="Table detail"><button type="button" aria-pressed="true" '
         'data-mode="simple">Simple</button><button type="button" aria-pressed="false" data-mode="detailed">Detailed'
         '</button></div></div>'
         '<div class="v2-dchips" role="tablist" aria-label="Columns" hidden>'
         + "".join(f'<button type="button" class="v2-dchip" role="tab" data-dgroup="{clean(g["key"])}" '
                   f'aria-selected="{"true" if g["key"] == g0 else "false"}">{clean(g["label"])}</button>' for g in groups)
         + '</div>'
         f'<div class="v2-scroll"><table class="lh-table v2-rt" data-mode="simple" data-group="{clean(g0)}" '
         f'data-sort="{clean(default)}" data-dir="1" '
         f'data-orders=\'{clean(json.dumps(r["orders"], separators=(",", ":")))}\'><thead><tr>']
    for k, lab, _det in SIMPLE_COLS:
        cls = "v2-sticky" if k == "name" else "v2-sc"
        sort = f' aria-sort="descending"' if k == default else ""
        o.append(f'<th class="{cls}"{sort} data-k="{k}"><button type="button" '
                 f'class="v2-tap" data-sort="{k}">{clean(lab)}<span class="v2-arrow">{" &#9662;" if k == default else ""}'
                 f'</span></button></th>')
    for k in r["keys"]:
        gcls = " ".join(f"v2-g-{g}" for g in r["gs"][k])
        o.append(f'<th class="v2-dc {gcls}" data-k="d_{k}"><button type="button" class="v2-tap" data-sort="d_{k}">'
                 f'{clean(r["cols"][k]["label"])}<span class="v2-arrow"></span></button></th>')
    o.append("</tr></thead>")

    def row(p, inactive):
        cells = [f'<td class="v2-sticky">{_pl(p["name"], p["card"], "lh-name v2-tap")}'
                 f'<span class="lh-sub">{clean(p["meta"])}'
                 + (f'<span class="v2-chips">{"".join(_chip(c) for c in p["chips"])}</span>' if p["chips"] else "")
                 + "".join(f" &middot; {clean(n)}" for n in p["notes"]) + "</span></td>"]
        for k, _lab, _det in SIMPLE_COLS[1:]:
            cells.append(f'<td class="v2-sc">{clean(p["cells"][k])}</td>')
        for c in p["dcells"]:
            gcls = " ".join(f"v2-g-{g}" for g in r["gs"][c["k"]])
            cells.append(f'<td class="v2-dc {gcls}">{_dcell(c)}</td>')
        return f'<tr data-i="{p["i"]}"{" class=" + chr(34) + "lh-inactive" + chr(34) if inactive else ""}>' + "".join(cells) + "</tr>"
    o.append('<tbody class="v2-active">' + "".join(row(p, False) for p in r["active"]) + "</tbody>")
    if r["il"]:
        o.append(f'<tbody class="v2-il"><tr class="lh-group"><td colspan="{len(SIMPLE_COLS) + len(r["keys"])}">IL slots'
                 '</td></tr>' + "".join(row(p, True) for p in r["il"]) + "</tbody>")
    o.append("</table></div>"
             f'<div class="lh-table-note">{clean(tp["size"])}. {clean(tp["note"])} GP is games played; Next is next '
             "week's games he will play. Tap a column to sort; Detailed picks a group of columns.</div>")
    for g in groups:
        o.append(f'<div class="lh-table-note v2-gnote" data-gnote="{clean(g["key"])}">'
                 + " ".join(f'<b>{clean(r["cols"][k]["label"])}</b>: {clean(r["cols"][k]["tip"])}'
                            + (f' &mdash; when there is none: {clean(r["why"][k])}.' if k in r["why"] else "")
                            for k in g["cols"]) + "</div>")
    o.append("".join(f'<div class="lh-table-note v2-gnote" data-gnote="{clean(g["key"])}">{clean(n)}</div>'
                     for g in groups for n in r["notes"]))
    o.append("".join(f'<div class="lh-table-note">{clean(x)}</div>' for x in tp["pending"]) + "</section>")
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


def _last_week(lw: dict) -> str:
    """Matchups' Last week (4b decision 11): final scores and how the closing
    line did; each opens the matchup as it stood at the end."""
    o = ['<section class="v2-sec" data-section="last"><div class="lh-sechead"><h2 class="lh-eyebrow">Last week</h2>'
         f'<span class="lh-meta lh-meta--canvas">{clean(lw["title"])}</span></div>']
    for lc in lw["cards"]:
        o.append(f'<a class="lh-card v2-lcard" href="{lc["href"]}" data-last="{clean(lc["id"])}">')
        for s in lc["sides"]:
            t = s["team"]
            o.append(f'<span class="lh-mrow {t["cls"]}">{_mono(t)}'
                     f'<span class="v2-minw"><span class="lh-mrow__name">{clean(s["name"])}</span>'
                     f'<span class="lh-sub">{clean(s["manager"])}</span></span>'
                     f'<span class="lh-num v2-mpts"><span class="lh-dsp v2-banked{" v2-won" if s["won"] else ""}">'
                     f'{clean(s["score"])}</span></span></span>')
        o.append(f'<span class="v2-lverdict">{clean(lc["result"])}</span>'
                 f'<span class="v2-lline">{"Closing line: " if lc["verdict"] else ""}{clean(lc["line"])}</span>'
                 + (f'<span class="v2-lverdict">{clean(lc["verdict"])}</span>' if lc["verdict"] else "")
                 + '<span class="lh-divider v2-mfoot"><span class="v2-note">Final charts</span>'
                 '<span class="v2-details">Details &rsaquo;</span></span></a>')
    o.append(f'<span class="lh-sub">{clean(lw["note"])}</span></section>')
    return "".join(o)


def _last_page(lc: dict, vm: dict, ids: _Ids) -> str:
    """Last week's matchup as it stood at the end: Summary (the final
    paragraph, Monday's preview, the closing line), Win % and Game flow."""
    o = [f'<section class="v2-screen" data-route="{clean(lc["route"])}" data-detail="1" hidden>',
         _topbar("#/matchups", "Matchups", vm["age"]), '<div class="v2-mhead">']
    for s in lc["sides"]:
        t = s["team"]
        o.append(f'<div class="v2-mside {t["cls"]}">{_mono(t, "36")}<span class="v2-minw">'
                 f'<a class="lh-mrow__name v2-tap" href="{t["href"]}">{clean(s["name"])}</a>'
                 f'<span class="lh-sub">{clean(s["manager"])} &middot; final</span>'
                 f'</span><span class="v2-score">{clean(s["score"])}</span></div>')
    a, b = lc["sides"]
    o.append(f'<span class="lh-winbar" role="img" aria-label="{clean(lc["bar_aria"])}">'
             f'<span class="{a["team"]["cls"]}" style="width:{clean(lc["bar_a"])}"></span><span class="{b["team"]["cls"]}"></span></span>'
             f'<span class="lh-meta">{clean(lc["result"])} &middot; {clean(lc["sub"])}</span></div><div class="v2-stack">')
    o.append(_seg("lastmu", [("summary", "Summary"), ("win", "Win %"), ("flow", "Game flow")]))
    o.append('<div class="v2-pane" data-pane-of="summary"><section class="lh-card v2-gap8">'
             '<h2 class="lh-eyebrow">The closing line</h2>'
             f'<p class="v2-p">{clean(lc["line"])}</p>'
             + (f'<p class="v2-p"><b>{clean(lc["verdict"])}</b></p>' if lc["verdict"] else "")
             + '</section><section class="lh-card">')
    for p in lc["paras"]:
        o.append('<div class="v2-para">' + (f'<h3 class="lh-eyebrow">{clean(p["head"])}</h3>' if p["head"] else "")
                 + f'<p class="v2-p">{clean(p["text"])}</p></div>')
    o.append("</section></div>")
    o.append('<div class="v2-pane" data-pane-of="win" hidden><section class="lh-card v2-gap8"><div class="lh-sechead">'
             f'<h2 class="lh-eyebrow">Win chance through the week</h2>{_info(ids, "win", a["team"]["team"])}</div>'
             + _chart(lc["win"], ids.next("ch")) + "</section></div>")
    o.append('<div class="v2-pane" data-pane-of="flow" hidden><section class="lh-card v2-gap8"><div class="lh-sechead">'
             '<h2 class="lh-eyebrow">Game flow</h2><span class="lh-meta">Points by day &middot; final</span></div>'
             + _chart(lc["flow"], ids.next("ch")) + "</section></div>")
    o.append("</div></section>")
    return "".join(o)


# =============================================================================
# the page
# =============================================================================

def render(vm: dict, *, cards: dict = None) -> str:
    """The page as one HTML string. cards: the preview's plaintext new-card
    bundle ({"cards": {key: {"html", "photo"}}}, publish.preview_cards),
    embedded only in preview."""
    from . import tokens
    if cards is not None and vm["mode"] != "preview":
        raise ValueError("the cards are embedded only in the plaintext preview")
    ids = _Ids()
    o = ["<!DOCTYPE html>", '<html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">', '<meta name="robots" content="noindex">',
         f"<title>{clean(vm['title'])}</title>", f"<style>{tokens.css(LAYOUT_CSS + pp.CSS + pm.CSS + pl.CSS)}</style>",
         _pictures_style(vm.get("pictures") or []) + "</head><body>",
         f'<div class="v2-app" id="hub" data-epoch="{vm["epoch"]}" data-stale-hours="{vm["stale_hours"]}">']
    # header (tab roots), then the banners, then the tab bar (a top bar on desktop)
    o.append('<header class="lh-header lh-on-dark v2-hdr" id="app-header"><div class="v2-stale-hd">'
             f'<span class="v2-minw"><span class="lh-header__title">{clean(vm["title"])}</span>'
             f'<span class="lh-header__date">{clean(vm["week_label"])}</span></span>'
             f'<button type="button" class="lh-iconbtn" data-go="search" aria-label="Search players">{pp.SEARCH}</button></div>'
             f'<div class="lh-fresh"><span class="lh-fresh__dot" id="fresh-dot"{" hidden" if vm["stale"] else ""}></span>'
             f'<span>Updated <span class="v2-age">{clean(vm["age"])}</span> ({clean(vm["generated_text"])})</span></div>'
             f'<span class="v2-lock">{clean(vm["line_text"])}</span>'
             f'<span class="v2-lock">{clean(vm["lock"])}</span>'
             + (f'<span class="v2-lock">{clean(vm["nba"]["text"])}</span>' if (vm.get("nba") or {}).get("text") else "")
             + '</header>')
    o.append('<div class="v2-stale-wrap">')
    if vm["mismatch"]:
        o.append(f'<div class="v2-banner" role="status"><b>Do not price anything off this page.</b> '
                 f'{clean(vm["mismatch"])}.</div>')
    if vm["engine_note"]:
        o.append(f'<div class="v2-calm">{clean(vm["engine_note"])}</div>')
    if vm.get("closing_note"):                     # H52: a refused closing line, the night went on
        o.append(f'<div class="v2-calm">{clean(vm["closing_note"])}</div>')
    for f in (vm.get("nba") or {}).get("flags") or []:     # 5a: the NBA report's flags, as the current header shows them
        o.append(f'<div class="v2-calm">{clean(f)}</div>')
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
             + _heat(g["rows"], g["cols"], total=bool(g.get("idle_label")), total_head=g.get("idle_label"),
                     label_of=lambda r: f'<a class="v2-heat-a v2-tap {r["team"]["cls"]}" href="{r["team"]["href"]}">'
                                        f'<span class="lh-swatch"></span>{clean(r["team"]["team"])}</a>')
             + f'<span class="lh-sub">{clean(g["note"])}</span></section>'
             + (_last_week(vm["last"]) if vm["last"] else "") + "</div></div></section>")
    for mu in vm["matchups"]:
        o.append(_matchup_page(mu, vm, ids))
    for lc in (vm["last"] or {}).get("cards", []):
        o.append(_lazy(_last_page(lc, vm, ids), vm))

    # ---------------------------------------------------------------- teams
    o.append('<section class="v2-screen" data-route="teams" hidden><div class="v2-stack"><section class="v2-sec">'
             '<div class="lh-sechead"><h2 class="lh-eyebrow">Teams</h2></div><div class="v2-teamgrid">'
             + "".join(_team_card(tp, vm["odds_label"]) for tp in vm["team_pages"]) + "</div></section></div></section>")
    for tp in vm["team_pages"]:
        o.append(_lazy(_team_page(tp, vm, ids), vm))

    # ---------------------------------------------------------------- players (4c1)
    o.append(pp.players_screen(vm, ids))
    o.append(pp.card_screen(vm))
    o.append(pp.compare_screens(vm))

    # ---------------------------------------------------------------- market (4c3)
    o.append(pm.market_screen(vm, ids, _info, lambda t: _mono(t)))

    # ---------------------------------------------------------------- league (4c4)
    if vm["mode"] == "preview" and vm["league"].get("awards") is not None:    # 4c5: Awards, a template
        vm["league"]["awards_html"] = pl.awards_html(vm["league"]["awards"], _mono, _chart, INFO)
    o.append(pl.league_screen(vm, ids, _info, _mono, _chart, DOC, CHEV))

    # ---------------------------------------------------------------- placeholders
    for ph in vm["placeholders"]:
        o.append(f'<section class="v2-screen" data-route="{ph["key"]}" hidden><div class="v2-stack"><section class="lh-card">'
                 f'<h2 class="lh-eyebrow">{clean(ph["label"])}</h2><p class="v2-p">{clean(ph["text"])}</p>'
                 + "".join(f'<a class="lh-link" href="{clean(x["href"])}">{clean(x["t"])} on the current hub &rsaquo;</a>'
                           for x in ph["links"]) + "</section></div></section>")
    o.append("</main>")
    o.append(f'<footer class="v2-foot">{clean(vm["footer"])}'
             + (' &middot; <button type="button" class="v2-forget v2-tap" id="forget" aria-haspopup="dialog" '
                'aria-controls="forget-ask">Forget this phone</button>'
                if vm["mode"] == "publish" else " &middot; local preview, not published") + "</footer>")
    if vm["mode"] == "publish":
        # 5c (Nick, 11-20): Forget asks first, in the page (no browser confirm())
        o.append(FORGET_ASK)
    o.append('<div class="v2-issue" id="issue-view" hidden><div class="v2-topbar"><button type="button" class="lh-back" '
             f'id="issue-close">{BACK}Back to the hub</button></div><iframe id="issue-frame" title="Newsletter"></iframe></div>')
    o.append("</div>")
    if vm["mode"] == "preview":                    # 4c4: History's chips, plaintext, this machine only
        o.append(pl.templates(vm["league"], _mono))
    if cards is not None:
        blob = json.dumps(cards, separators=(",", ":"), ensure_ascii=True).replace("</", "<\\/")
        o.append(f'<script type="application/json" id="v2-cards">{blob}</script>')
    o.append(f"<script>{script()}</script></body></html>")
    return "\n".join(o)


# 5c: "Forget this phone" asks first (Nick, 11-20; the reviewer's call): an
# in-page confirm, never the browser's confirm() dialog
FORGET_ASK = ('<div class="v2-ask" id="forget-ask" role="alertdialog" aria-modal="true" aria-labelledby="forget-q" '
              'hidden><div class="v2-ask-box"><span id="forget-q">Forget this phone? You\'ll need the passphrase '
              'again.</span><span class="v2-ask-row"><button type="button" class="lh-btn v2-btn" id="forget-no">'
              'Cancel</button><button type="button" class="lh-btn v2-btn" id="forget-yes">Forget</button></span>'
              '</div></div>')


def script() -> str:
    """The page's one script: PAGE_JS with each tab's own script INSIDE its
    closure, before the first route() (4c4). Market's (4c3) used to follow the
    closure, where sortTable was not defined: its Sort select threw
    "sortTable is not defined". League's needs pick() and movedBox() too, and
    its routes must exist before the first route()."""
    tail = "route();check130();\n})();\n"
    if not PAGE_JS.endswith(tail):
        raise ValueError("PAGE_JS no longer ends with its first route() call")
    return PAGE_JS[:-len(tail)] + pm.JS + pl.JS + tail


PAGE_JS = r"""
(function(){
var hub=document.getElementById('hub');
var header=document.getElementById('app-header');
var seen={};                       // segmented-tab choice per kind, for the session
// 5c: A TAP REACHES WHAT IS DRAWN. A tap that reached a .v2-tap through its
// 44-point area (outside its own box), on a point where another tap target
// is drawn (its own box), goes to that one: the areas fill blank space only.
// Pointer taps only (a keyboard click has no point). Layout only.
var TAPSEL='a[href],button,select,input,label,[role="button"],[data-tip-h],[data-card],.lh-c-hit';
function inBox(el,x,y){var b=el.getBoundingClientRect();return x>=b.left&&x<=b.right&&y>=b.top&&y<=b.bottom;}
function drawnTap(t,x,y){
  if(inBox(t,x,y)){return null;}
  var st=document.elementsFromPoint(x,y);
  for(var i=0;i<st.length;i++){var el=st[i];
    if(el===t||t.contains(el)||el.contains(t)||!inBox(el,x,y)){continue;}
    var I=el.closest(TAPSEL);
    return (I&&I!==t&&!I.contains(t)&&!t.contains(I))?I:null;}
  return null;
}
document.addEventListener('click',function(e){
  if(!e.detail||(!e.clientX&&!e.clientY)){return;}
  var t=e.target&&e.target.closest?e.target.closest('.v2-tap'):null;if(!t){return;}
  var I=drawnTap(t,e.clientX,e.clientY);if(!I){return;}
  e.preventDefault();e.stopImmediatePropagation();
  if(typeof I.click==='function'){I.click();}else{I.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));}
},true);
function screens(){return document.querySelectorAll('.v2-screen');}
var depth=0,focusSearch=false;    // hash changes since the page opened (the back buttons), the header's search
function legacy(){                // 5a: the current hub's #v-... links land on their new screens
  var h=location.hash.replace(/^#/,'');if(!h||h.charAt(0)==='/'){return;}
  var m,to=null,sg=null,pn=null;
  if(h==='v-main'){to='home';}
  else if(h==='v-last'){to='matchups';}
  else if(h==='v-chart'){to='league/standings';}
  else if(h==='v-block'||h==='v-advice'){to='market';sg='market';pn=(h==='v-block')?'block':'advice';}
  else if((m=/^v-roster-(.+)$/.exec(h))){to='teams/'+m[1];}
  else if((m=/^v-mu(\d+)-(\d+)-(sum|win|flow)$/.exec(h))){to='matchups/w'+m[1]+'-'+m[2];sg='matchup';
    pn={sum:'summary',win:'win',flow:'flow'}[m[3]];}
  if(to===null){return;}
  if(sg&&document.querySelector('.lh-seg[data-seg="'+sg+'"] [data-pane="'+pn+'"]')){seen[sg]=pn;
    if(sg==='matchup'){seen['lastmu']=pn;}}
  try{history.replaceState(null,'','#/'+to);}catch(e){location.hash='#/'+to;}
}
function route(){
  legacy();
  var r=location.hash.replace(/^#\/?/,'')||'home';
  var parts=r.split('/'),want=r,dyn='';
  if(parts[0]==='league'&&parts.length>1&&parts[1]){want='league';dyn='league';}
  if(parts[0]==='players'&&parts.length>1&&parts[1]){
    if(parts[1]==='compare'){dyn=(parts.length>3&&parts[3])?'compare':'compare-pick';}else{dyn='player';}
    want=dyn;
  }
  var target=null,all=screens();
  for(var i=0;i<all.length;i++){if(all[i].getAttribute('data-route')===want){target=all[i];}}
  if(!target){r='home';for(var j=0;j<all.length;j++){if(all[j].getAttribute('data-route')==='home'){target=all[j];}}}
  for(var k=0;k<all.length;k++){all[k].hidden=(all[k]!==target);}
  header.hidden=!!target.getAttribute('data-detail');
  var tab=r.split('/')[0];
  var ts=document.querySelectorAll('.lh-tabbar a');
  for(var t=0;t<ts.length;t++){if(ts[t].getAttribute('data-tab')===tab){ts[t].setAttribute('aria-current','page');}
    else{ts[t].removeAttribute('aria-current');}}
  hideTip();
  if(lazyScreen(target)){window.scrollTo(0,0);return;}
  if(seen['dgroup']){dgroup(seen['dgroup']);}
  var segs=target.querySelectorAll('.lh-seg[data-seg]');
  for(var s=0;s<segs.length;s++){var kind=segs[s].getAttribute('data-seg');if(seen[kind]){pick(segs[s],seen[kind]);}}
  window.scrollTo(0,0);
  bigPic(target);
  if(dyn==='player'){showCard(parts[1]);}
  else if(dyn==='compare-pick'){showPick(parts[2]);}
  else if(dyn==='compare'){showCompare(parts[2],parts[3]);}
  else if(dyn==='league'&&window.lgRoute){window.lgRoute(parts.slice(1));}
  if(window.lgOdds){window.lgOdds();}
  if(r==='players'&&focusSearch){focusSearch=false;var sf=document.getElementById('pl-search');if(sf){sf.focus();}}
}
window.addEventListener('hashchange',function(){depth++;route();});
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
  hideTip();
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
// 5c: an open InfoTip popover is placed by the page, inside the screen (Nick's
// phone, 11-20: the left KPI tile's ran off the left edge), and fixed, so no
// scrolling table clips it: below its button, above when there is no room,
// its right edge on the button's as the design has it, then moved in from
// either edge. Layout only.
function placePop(btn,pop){
  var pad=8,vw=document.documentElement.clientWidth,vh=document.documentElement.clientHeight;
  pop.style.position='fixed';pop.style.right='auto';pop.style.left='0px';pop.style.top='0px';
  var a=btn.getBoundingClientRect(),w=pop.offsetWidth,h=pop.offsetHeight;
  var left=a.right+pad-w,top=a.bottom+4;
  if(top+h>vh-pad){top=a.top-4-h;}
  if(top<pad){top=pad;}
  if(left+w>vw-pad){left=vw-pad-w;}
  if(left<pad){left=pad;}
  pop.style.left=left+'px';pop.style.top=top+'px';
}
function placePops(){
  var bs=document.querySelectorAll('.lh-info > button[aria-expanded="true"]');
  for(var i=0;i<bs.length;i++){placePop(bs[i],document.getElementById(bs[i].getAttribute('aria-controls')));}
}
// THE ONE TOOLTIP (4c2; design/league-hub/components/Tooltip): a small dark
// box with the engine's three strings (data-tip-h / -b / -f). A tap opens it
// (a second tap or a tap elsewhere closes it), keyboard focus opens it, Escape
// closes it. It sits above its anchor (below when there is no room), inside
// the screen, and never over a chart's end labels. Layout only: no number is
// made here.
var TIP=null,tipFor=null,ptrFocus=false;
function tipBox(){
  if(!TIP){TIP=document.createElement('div');TIP.className='lh-tip';TIP.id='v2-tip';
    TIP.setAttribute('role','status');TIP.hidden=true;hub.appendChild(TIP);}
  return TIP;
}
function placeTip(el,box){
  // 5c: measured at the screen's left edge, so its width is its own, not what
  // was left of the screen where the last tip stood (it grew past the edge)
  box.style.left='0px';box.style.top='0px';
  var a=el.getBoundingClientRect(),w=box.offsetWidth,h=box.offsetHeight;
  var vw=document.documentElement.clientWidth,vh=document.documentElement.clientHeight,pad=8;
  var left=a.left+a.width/2-w/2,top=a.top-h-pad;
  if(top<pad){top=a.bottom+pad;}
  if(top+h>vh-pad){top=vh-pad-h;}
  if(left+w>vw-pad){left=vw-pad-w;}
  if(left<pad){left=pad;}
  var svg=el.closest('svg');
  if(svg){
    var labs=svg.querySelectorAll('.lh-c-label');
    for(var i=0;i<labs.length;i++){var r=labs[i].getBoundingClientRect();
      if(left+w>r.left&&left<r.right&&top<r.bottom&&top+h>r.top){left=r.left-pad-w;}}
    if(left<pad){left=pad;var s=svg.getBoundingClientRect();top=s.bottom+pad;}
    // 5c (the sweep, 360 px): an end label past the screen's edge moved the
    // tip right, off the screen: back inside, below the chart
    else if(left+w>vw-pad){left=vw-pad-w;var s2=svg.getBoundingClientRect();top=s2.bottom+pad;}
    if(top+h>vh-pad){top=vh-pad-h;}
    if(top<pad){top=pad;}
  }
  box.style.left=left+'px';box.style.top=top+'px';
}
function showTip(el){
  hideTip();
  var box=tipBox();box.textContent='';
  var hd=document.createElement('b');hd.textContent=el.getAttribute('data-tip-h');box.appendChild(hd);
  var bd=document.createElement('span');bd.textContent=el.getAttribute('data-tip-b');box.appendChild(bd);
  var ft=el.getAttribute('data-tip-f');
  if(ft){var fe=document.createElement('span');fe.textContent=ft;box.appendChild(fe);}
  box.hidden=false;tipFor=el;el.setAttribute('aria-expanded','true');
  placeTip(el,box);
}
function hideTip(){
  if(TIP){TIP.hidden=true;}
  if(tipFor){tipFor.setAttribute('aria-expanded','false');tipFor=null;}
}
document.addEventListener('pointerdown',function(){ptrFocus=true;},true);
document.addEventListener('keydown',function(){ptrFocus=false;},true);
window.addEventListener('scroll',function(){hideTip();placePops();},true);
window.addEventListener('resize',function(){hideTip();placePops();});
// the roster's Detailed chip row: the group of columns shown, kept for the session
function dgroup(key){
  seen['dgroup']=key;
  var ws=document.querySelectorAll('.v2-rtwrap');
  for(var i=0;i<ws.length;i++){ws[i].setAttribute('data-group',key);
    var t=ws[i].querySelector('.v2-rt');if(t){t.setAttribute('data-group',key);}
    var cs=ws[i].querySelectorAll('.v2-dchip');
    for(var j=0;j<cs.length;j++){cs[j].setAttribute('aria-selected',String(cs[j].getAttribute('data-dgroup')===key));}}
}
// player cards (4c1): the NEW card, rendered at build time; inline in
// preview (#v2-cards), published as encrypted files (HUB.cards() gives the
// index, HUB.part a card, HUB.photo a headshot)
var cardsP=null,photos={},shownKey=null;
function cardIndex(){
  if(cardsP){return cardsP;}
  var el=document.getElementById('v2-cards');
  cardsP=el?Promise.resolve(JSON.parse(el.textContent)):
    ((window.HUB&&window.HUB.cards)?window.HUB.cards():Promise.reject(new Error('no cards')));
  cardsP.catch(function(){cardsP=null;});
  return cardsP;
}
function cardOf(key){
  return cardIndex().then(function(ix){
    var c=ix.cards[key];
    if(!c){throw new Error('no card');}
    if(c.html!==undefined){return c;}
    if(!c.got){c.got=window.HUB.part(c.card).then(function(p){return {html:p.html,photo:c.photo};});
      c.got.catch(function(){c.got=null;});}
    return c.got;});
}
function photoOf(c,key){
  if(!c.photo){return Promise.resolve(null);}
  if(typeof c.photo==='string'){return Promise.resolve(c.photo);}
  if(!photos[key]){photos[key]=window.HUB.photo(c.photo);photos[key].catch(function(){photos[key]=null;});}
  return photos[key];
}
function putPhoto(slot,url){
  if(!slot||!url){return;}
  var img=document.createElement('img');img.alt='';
  img.addEventListener('error',function(){img.remove();});     // never a broken image: the initials stay
  img.src=url;slot.appendChild(img);
}
function cardMessage(body,err){
  if(err&&err.message==='gone'){movedBox();}
  var p=document.createElement('p');p.className='v2-card-load';
  p.textContent=(err&&err.message==='old browser')?'This browser is too old to open player cards.':
    (err&&err.message==='gone')?'The hub has been updated: reload the page to open player cards.':
    'That player card could not be opened.';
  body.textContent='';body.appendChild(p);
}
function showCard(key){
  var body=document.getElementById('card-body');
  var cur=body.querySelector('[data-card-key]');
  if(cur&&cur.getAttribute('data-card-key')===key){return;}
  shownKey=key;
  var wait=document.createElement('p');wait.className='v2-card-load';wait.textContent='Opening the card\u2026';
  body.textContent='';body.appendChild(wait);
  cardOf(key).then(function(c){
    if(shownKey!==key){return;}
    body.innerHTML=c.html;                         // the engine's HTML: every string through clean()
    var seg=body.querySelector('.lh-seg[data-seg]');if(seg&&seen.card){pick(seg,seen.card);}
    photoOf(c,key).then(function(u){putPhoto(body.querySelector('[data-photo-slot]'),u);},function(){});
  },function(err){if(shownKey===key){cardMessage(body,err);}});
}
function openCard(key){location.hash='#/players/'+key;}
// the Players table: search (folded, as the engine folds the keys), filters, sort
var FOLD={'\u00f8':'o','\u0111':'d','\u0142':'l','\u00df':'ss','\u00e6':'ae','\u0153':'oe','\u0131':'i','\u00f0':'d','\u00fe':'th'};
function fq(s){
  s=String(s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  return s.replace(/[\u00f8\u0111\u0142\u00df\u00e6\u0153\u0131\u00f0\u00fe]/g,function(c){return FOLD[c];}).trim();
}
var PF={k:'',pos:'',nba:'',age:'',h:''};
function plFilter(){
  var inp=document.getElementById('pl-search');if(!inp){return;}
  var q=fq(inp.value),trs=document.querySelectorAll('#pl-table tbody tr'),any=false;
  for(var i=0;i<trs.length;i++){var t=trs[i],ok=true;
    if(q&&t.getAttribute('data-q').indexOf(q)<0){ok=false;}
    if(PF.k&&t.getAttribute('data-k')!==PF.k){ok=false;}
    if(PF.pos&&(' '+t.getAttribute('data-pos')+' ').indexOf(' '+PF.pos+' ')<0){ok=false;}
    if(PF.nba&&t.getAttribute('data-nba')!==PF.nba){ok=false;}
    if(PF.age&&t.getAttribute('data-age')!==PF.age){ok=false;}
    if(PF.h&&t.getAttribute('data-h')!=='1'){ok=false;}
    t.hidden=!ok;if(ok){any=true;}}
  document.getElementById('pl-none').hidden=any;
}
function plSort(key){
  var tbl=document.getElementById('pl-table'),orders=JSON.parse(tbl.getAttribute('data-porders'));
  var dir=(tbl.getAttribute('data-pcol')===key&&tbl.getAttribute('data-pdir')==='d')?'a':'d';
  var ord=orders[key][dir],body=tbl.querySelector('tbody'),rows={},rs=body.querySelectorAll('tr[data-i]');
  for(var i=0;i<rs.length;i++){rows[rs[i].getAttribute('data-i')]=rs[i];}
  for(var j=0;j<ord.length;j++){var r=rows[String(ord[j])];if(r){body.appendChild(r);}}
  tbl.setAttribute('data-pcol',key);tbl.setAttribute('data-pdir',dir);
  var ths=tbl.querySelectorAll('th[data-k]');
  for(var t=0;t<ths.length;t++){var on=ths[t].getAttribute('data-k')===key,ar=ths[t].querySelector('.v2-arrow');
    var down=(key==='name')?(dir==='a'):(dir==='d');
    if(on){ths[t].setAttribute('aria-sort',down?'descending':'ascending');ar.textContent=down?' \u25be':' \u25b4';}
    else{ths[t].removeAttribute('aria-sort');ar.textContent='';}}
}
// Compare: the better value in a row is the one whose ENGINE order key is
// larger; a missing key (null) wins nothing, and Age's keys are all null
var CMP=null,cmpA='';
function cmpData(){if(!CMP){CMP=JSON.parse(document.getElementById('v2-cmp').textContent);}return CMP;}
function mk(tag,cls,text){var e=document.createElement(tag);if(cls){e.className=cls;}if(text!==undefined){e.textContent=text;}return e;}
var RING='<svg width="56" height="56" viewBox="0 0 56 56" role="img"><circle class="lh-ring__track" cx="28" cy="28" r="22" '+
  'fill="none" stroke-width="5"/><circle class="lh-ring__arc" cx="28" cy="28" r="22" fill="none" stroke-width="5" '+
  'stroke-linecap="round" transform="rotate(-90 28 28)"/></svg><div class="lh-ring__inner"><span class="lh-ring__value"></span></div>';
function cmpSide(p,key,right){
  var s=mk('div','v2-cmp-side'+(right?' v2-right':''));
  var hs=mk('div','lh-headshot v2-hs v2-hs-cmp');hs.appendChild(mk('span','v2-ini',p.ini));s.appendChild(hs);
  cardOf(key).then(function(c){return photoOf(c,key);}).then(function(u){putPhoto(hs,u);},function(){});
  var nm=mk('a','v2-cmp-name v2-tap',p.name);nm.href='#/players/'+key;s.appendChild(nm);
  var chip=mk('span',p.cls?('lh-chip v2-mini '+p.cls):'lh-chip lh-chip--fa v2-mini');
  if(p.cls){chip.appendChild(mk('span','lh-swatch'));}
  chip.appendChild(document.createTextNode(p.chip));s.appendChild(chip);
  if(p.ring){
    var ring=mk('div','lh-ring v2-ring-sm '+p.cls);ring.innerHTML=RING;
    ring.querySelector('svg').setAttribute('aria-label','Overall rating '+p.ovr+' of 99');
    ring.querySelector('.lh-ring__arc').setAttribute('stroke-dasharray',p.ring);
    ring.querySelector('.lh-ring__value').textContent=p.ovr;s.appendChild(ring);
    if(p.prov){s.appendChild(mk('span','v2-prov','Prov.'));}
  }else{s.appendChild(mk('span','lh-sub',p.fa?'Free agent: no OVR':'No OVR on this run'));}
  if(p.arch){var a=mk('span','v2-chiprow');a.appendChild(mk('span','v2-arch-h',p.arch));
    if(p.arch_preview){a.appendChild(mk('span','v2-preview','Preview'));}s.appendChild(a);}
  return s;
}
function showCompare(a,b){
  var D=cmpData(),A=D.rows[a],B=D.rows[b],hero=document.getElementById('cmp-hero'),rows=document.getElementById('cmp-rows');
  hero.textContent='';rows.textContent='';
  if(!A||!B){rows.appendChild(mk('p','v2-p','One of these players is not in the hub any more.'));return;}
  hero.appendChild(cmpSide(A,a,false));hero.appendChild(cmpSide(B,b,true));
  for(var i=0;i<D.labels.length;i++){
    var x=A.cmp[i],y=B.cmp[i];
    var xw=(x.k!==null&&y.k!==null&&x.k>y.k),yw=(x.k!==null&&y.k!==null&&y.k>x.k);
    var r=mk('div','v2-cmp-row');
    r.appendChild(mk('span','v2-cmp-v'+(xw?' v2-win':''),x.t));r.appendChild(mk('span','v2-cmp-lab',D.labels[i]));
    r.appendChild(mk('span','v2-cmp-v'+(yw?' v2-win':''),y.t));rows.appendChild(r);
  }
}
function showPick(a){
  cmpA=a;var A=cmpData().rows[a];
  document.getElementById('cmp-a-name').textContent=A?A.name:'';
  var inp=document.getElementById('cmp-search');inp.value='';pickFilter();
}
function pickFilter(){
  var q=fq(document.getElementById('cmp-search').value),bs=document.querySelectorAll('.v2-pick');
  for(var i=0;i<bs.length;i++){bs[i].hidden=(bs[i].getAttribute('data-pick')===cmpA)||(q!==''&&bs[i].getAttribute('data-q').indexOf(q)<0);}
}
function alertBox(msg){var d=document.createElement('div');d.className='lh-stale';d.setAttribute('role','status');
  d.textContent=msg;hub.insertBefore(d,hub.firstChild);}
// 5b: a lazy screen (a team page, last week's matchup page): published, its
// content is an encrypted part, opened on its first show; then route() runs
// again, so the screen is set up as if it had been there all along. True
// while it is opening.
function lazyScreen(scr){
  var ref=scr.getAttribute('data-screen-part');
  if(!ref||scr.getAttribute('data-loaded')){return false;}
  if(scr.getAttribute('data-loading')){return true;}
  if(!window.HUB||!window.HUB.part){return true;}
  scr.setAttribute('data-loading','1');
  window.HUB.part(JSON.parse(ref)).then(function(p){
    scr.innerHTML=p.html;scr.setAttribute('data-loaded','1');scr.removeAttribute('data-loading');
    if(!scr.hidden){route();}
  },function(err){
    scr.removeAttribute('data-loading');if(err&&err.message==='gone'){movedBox();}
    var e=scr.querySelector('.v2-screen-load');if(e){e.textContent=(err&&err.message==='old browser')?
      'This browser is too old to open this page.':'This page could not be opened. Go back and try again.';}
  });
  return true;
}
// 5b: a team page's full-size picture (its 72 TeamMark): an encrypted part
// opened with the page; the small copy (inline) shows until it arrives, and
// stays if it cannot be opened. Only a base64 image data URI is drawn.
function bigPic(scr){
  var el=scr.querySelector('[data-pic]');
  if(!el||el.getAttribute('data-pic-on')||!window.HUB||!window.HUB.part){return;}
  el.setAttribute('data-pic-on','1');
  window.HUB.part(JSON.parse(el.getAttribute('data-pic'))).then(function(p){
    var u=String((p&&p.pic)||'');
    if(!/^data:image\/(jpeg|png|gif|webp);base64,[A-Za-z0-9+\/=]+$/.test(u)){return;}
    var img=document.createElement('img');img.alt='';img.className='v2-bigpic';
    img.addEventListener('load',function(){el.classList.add('v2-bigpic-on');el.setAttribute('data-pic-on','2');});
    img.addEventListener('error',function(){img.remove();});      // the small copy stays
    img.src=u;el.appendChild(img);
  },function(){el.removeAttribute('data-pic-on');});
}
function movedBox(){
  if(document.getElementById('hub-moved')){return;}
  var d=document.createElement('div');d.className='lh-stale';d.id='hub-moved';d.setAttribute('role','status');
  d.appendChild(document.createTextNode('The hub has been updated: reload the page to open player cards. '));
  var b=document.createElement('button');b.type='button';b.className='lh-btn';b.textContent='Reload';
  b.addEventListener('click',function(){if(window.HUB&&window.HUB.reload){window.HUB.reload();}else{location.reload();}});
  d.appendChild(b);hub.insertBefore(d,hub.firstChild);
}
// 5c: "Forget this phone" asks first, in the page; only its Forget button forgets
function askForget(on){
  var a=document.getElementById('forget-ask');if(!a){return;}
  a.hidden=!on;var f=document.getElementById(on?'forget-no':'forget');if(f){f.focus();}
}
function openFrame(url){document.getElementById('issue-frame').src=url;document.getElementById('issue-view').hidden=false;}
document.addEventListener('click',function(e){
  var t=e.target.closest('[data-tip-h]');
  if(t){ptrFocus=false;if(tipFor===t){hideTip();}else{showTip(t);}return;}
  hideTip();
  t=e.target.closest('[data-card]');
  if(t){e.preventDefault();e.stopPropagation();openCard(t.getAttribute('data-card'));return;}
  t=e.target.closest('[data-go="search"]');
  if(t){focusSearch=true;if(location.hash==='#/players'){route();}else{location.hash='#/players';}return;}
  t=e.target.closest('[data-back]');
  if(t){if(depth>0){history.back();}else{location.hash=t.getAttribute('data-back');}return;}
  t=e.target.closest('.lh-seg[data-filter] button');
  if(t){var fs=t.closest('.lh-seg'),fb=fs.querySelectorAll('button');
    for(var f=0;f<fb.length;f++){fb[f].setAttribute('aria-selected',String(fb[f]===t));}
    PF.k=t.getAttribute('data-v');plFilter();return;}
  t=e.target.closest('button[data-filter="h"]');
  if(t){var on=t.getAttribute('aria-pressed')!=='true';t.setAttribute('aria-pressed',String(on));PF.h=on?'1':'';plFilter();return;}
  t=e.target.closest('[data-psort]');
  if(t){plSort(t.getAttribute('data-psort'));return;}
  t=e.target.closest('[data-pick]');
  if(t){location.hash='#/players/compare/'+cmpA+'/'+t.getAttribute('data-pick');return;}
  t=e.target.closest('.v2-bar');
  if(t){var bb=t.parentNode.querySelectorAll('.v2-bar');for(var q=0;q<bb.length;q++){bb[q].setAttribute('aria-pressed',String(bb[q]===t));}
    var ro=document.querySelector('[data-readout="'+t.parentNode.getAttribute('data-bars')+'"]');if(ro){ro.textContent=t.getAttribute('data-label');}return;}
  t=e.target.closest('.v2-gtile');
  if(t){var gg=t.parentNode.querySelectorAll('.v2-gtile');for(var g=0;g<gg.length;g++){gg[g].setAttribute('aria-pressed',String(gg[g]===t));}
    var gr=document.querySelector('[data-readout="'+t.getAttribute('data-grid')+'"]');if(gr){gr.textContent=t.getAttribute('data-tip');}return;}
  t=e.target.closest('.lh-info > button');
  if(t){var open=t.getAttribute('aria-expanded')==='true';closeTips(t);
    var pp=document.getElementById(t.getAttribute('aria-controls'));
    t.setAttribute('aria-expanded',String(!open));pp.hidden=open;if(!open){placePop(t,pp);}return;}
  if(!e.target.closest('.lh-info__pop')){closeTips(null);}
  t=e.target.closest('.lh-seg[data-seg] button');
  if(t){var seg=t.closest('.lh-seg');seen[seg.getAttribute('data-seg')]=t.getAttribute('data-pane');pick(seg,t.getAttribute('data-pane'));return;}
  t=e.target.closest('.lh-toggle button');
  if(t){var tg=t.closest('.lh-toggle'),bs=tg.querySelectorAll('button');
    for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i]===t));}
    var mode=t.getAttribute('data-mode');seen['detail']=mode;
    var tb=document.querySelectorAll('.v2-rt');for(var j=0;j<tb.length;j++){tb[j].setAttribute('data-mode',mode);}
    var rw=document.querySelectorAll('.v2-rtwrap');for(var w=0;w<rw.length;w++){rw[w].setAttribute('data-mode',mode);
      var ch=rw[w].querySelector('.v2-dchips');if(ch){ch.hidden=(mode!=='detailed');}}
    var tgs=document.querySelectorAll('.lh-toggle button');
    for(var k=0;k<tgs.length;k++){tgs[k].setAttribute('aria-pressed',String(tgs[k].getAttribute('data-mode')===mode));}
    return;}
  t=e.target.closest('[data-dgroup]');
  if(t){dgroup(t.getAttribute('data-dgroup'));return;}
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
  if(e.target.closest('#forget')){askForget(true);return;}
  if(e.target.closest('#forget-no')){askForget(false);return;}
  if(e.target.closest('#forget-yes')){askForget(false);if(window.HUB){window.HUB.forget();}return;}
});
// keyboard focus on a chart point reads it (its ring marks the focus)
document.addEventListener('focusin',function(e){
  var t=e.target;if(t.classList&&t.classList.contains('lh-c-hit')){readout(t);}
  if(t.getAttribute&&t.getAttribute('data-tip-h')!==null&&!ptrFocus){showTip(t);}
});
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){closeTips(null);hideTip();var fa=document.getElementById('forget-ask');
    if(fa&&!fa.hidden){askForget(false);}return;}
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
document.addEventListener('input',function(e){
  if(e.target.id==='pl-search'){plFilter();}else if(e.target.id==='cmp-search'){pickFilter();}
});
document.addEventListener('change',function(e){
  var f=e.target.getAttribute&&e.target.getAttribute('data-filter');
  if(f&&e.target.tagName==='SELECT'){PF[f]=e.target.value;plFilter();}
});
route();check130();
})();
"""
