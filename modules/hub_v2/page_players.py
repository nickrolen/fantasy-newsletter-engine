"""
hub_v2/page_players.py -- THE RENDERER for the Players tab, the new player
card and Compare (4c1). page.py's rules carry over: every printed number is a
payload (or card view) string through clean(); no arithmetic (tests pin it:
no round/float/sum/sorted/max/min/int in these functions); no hex and no px
in the CSS.

    players_screen(vm, ids)   #/players: search, All/Rostered/Free agents,
                              the filter chips, the sortable table, Risers
    card_screen(vm)           #/players/<key>: the shell the card loads into
    compare_screens(vm)       #/players/compare/<a> (pick the second player)
                              and #/players/compare/<a>/<b>
    card_html(cv)             one player's card, rendered by the ENGINE side
                              at build time and shipped in his encrypted card
                              file (publish) or inline (preview): the page
                              only inserts it

Bars and percentile bars are scaled by the engine (percentage strings); the
OVR ring's arc is the engine's dash string.
"""

from __future__ import annotations

from ..live_lines_page import clean
from .infotips import tip

SEARCH = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
          'aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>')
INFO = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>')
BACK = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>')

PLAYER_COLS = [("name", "Player"), ("ovr", "OVR"), ("pot", "POT"), ("fppg", "FPPG"), ("next", "Next")]

CSS = """
.v2-search{display:flex;align-items:center;gap:var(--space-8);background:var(--surface);border:var(--hairline) solid var(--line);border-radius:var(--radius-12);padding:0 var(--space-12);min-height:var(--tap-min);color:var(--ink-3)}
.v2-search input{all:unset;flex:1;min-width:0;min-height:var(--tap-min);font-size:var(--type-row-size);color:var(--ink)}
.v2-fchips{display:flex;flex-wrap:wrap;gap:var(--space-8)}
.v2-fchip{position:relative;display:inline-flex;align-items:center;gap:var(--space-4);min-height:var(--tap-min);padding:0 var(--space-12);border-radius:var(--radius-pill);border:var(--hairline) solid var(--line);background:var(--surface);font-size:var(--type-meta-size);font-weight:700;color:var(--ink-2);cursor:pointer}
button.v2-fchip[aria-pressed="true"]{background:var(--dark);border-color:var(--dark);color:var(--ink-on-dark)}
.v2-fchip select{all:unset;cursor:pointer;font-weight:800;color:var(--ink)}
button.lh-back{background:none;border:0;padding:0;cursor:pointer;font-family:inherit}
.v2-pt .v2-sticky{position:sticky;left:0;background:var(--surface);z-index:1;max-width:48vw}
.v2-pt th.v2-sticky{background:var(--surface-subtle)}
.v2-pt .lh-sub{display:flex;align-items:center;gap:var(--space-6);flex-wrap:wrap}
.v2-mini{font-size:var(--type-small-size);padding:var(--space-2) var(--space-8);min-height:0}
.v2-ovrcell{white-space:nowrap}
.v2-riser{display:flex;justify-content:space-between;align-items:center;gap:var(--space-10);min-height:var(--row-min);padding-top:var(--space-6)}
.v2-riser .lh-num{display:flex;align-items:baseline;gap:var(--space-6)}
.v2-ovr-dsp{font-family:var(--font-display);font-size:var(--type-display-row-size);font-weight:700}
.v2-empty{padding:var(--space-12) var(--space-14)}
.v2-hero-bar{display:flex;align-items:center;justify-content:space-between;gap:var(--space-8)}
.v2-btn{min-height:var(--tap-min);display:inline-flex;align-items:center;text-decoration:none}
.v2-hs{position:relative;align-items:center}
.v2-ini{font-family:var(--font-display);font-size:var(--type-display-xl-size);font-weight:700;color:var(--ink-3)}
.v2-hs img{position:absolute;inset:0}
.v2-hero-r{display:flex;flex-direction:column;gap:var(--space-10);min-width:0}
.v2-ratings{display:flex;gap:var(--space-12);align-items:center;flex-wrap:wrap}
.v2-potcol{display:flex;flex-direction:column;gap:var(--space-2)}
.v2-fa-tile{display:flex;flex-direction:column;gap:var(--space-4);min-width:0}
.v2-chiprow{display:flex;flex-wrap:wrap;gap:var(--space-6);align-items:center}
.v2-arch-k{font-size:var(--type-meta-size);color:var(--ink-2)}
.v2-arch-h{font-size:var(--type-heading-size);font-weight:800}
.v2-preview{font-size:var(--type-label-size);font-weight:800;letter-spacing:var(--type-label-ls);text-transform:uppercase;color:var(--status-q);background:var(--status-q-tint);border-radius:var(--radius-pill);padding:var(--space-2) var(--space-8)}
.v2-gnote{font-size:var(--type-small-size);color:var(--ink-3);text-align:center}
.v2-bars>button.v2-bar{all:unset;flex:1;display:flex;align-items:flex-end;align-self:stretch;min-height:var(--tap-min);cursor:pointer}
.v2-bar>span{display:block;width:100%;background:var(--team,var(--ink-2));border-radius:var(--radius-3) var(--radius-3) 0 0}
.v2-bar[aria-pressed="true"]>span{background:var(--ink-strong)}
.v2-bar>span.v2-inj{background:var(--axis);height:var(--space-4)}
.v2-bars .lh-bars__avg{bottom:var(--y)}
.v2-bars .lh-bars__avglabel{bottom:var(--y)}
.v2-axis{display:flex;justify-content:space-between;gap:var(--space-8);font-size:var(--type-small-size);color:var(--ink-3)}
.v2-last td:first-child{white-space:nowrap}
.v2-list{display:flex;flex-direction:column}
.v2-li{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft)}
.v2-li .lh-sub{display:block}
.v2-keepbig{font-family:var(--font-display);font-size:var(--type-display-lg-size);font-weight:700}
.v2-cmp-hero{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--space-12)}
.v2-cmp-side{display:flex;flex-direction:column;gap:var(--space-8);align-items:flex-start;min-width:0}
.v2-cmp-side.v2-right{align-items:flex-end;text-align:right}
.v2-hs-cmp{width:var(--headshot-compare);height:var(--headshot-compare)}
.v2-hs-cmp .v2-ini{font-size:var(--type-display-lg-size)}
.v2-cmp-name{font-family:var(--font-display);font-size:var(--type-title-size);font-weight:700;line-height:1;min-height:var(--tap-min);display:flex;align-items:flex-end;overflow-wrap:anywhere}
.v2-ring-sm{width:var(--ring-compare);height:var(--ring-compare)}
.v2-ring-sm .lh-ring__value{font-size:var(--type-title-size)}
.v2-cmp-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr) minmax(0,1fr);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);font-variant-numeric:tabular-nums}
.v2-cmp-row>span:first-child{text-align:left}
.v2-cmp-row>span:last-child{text-align:right}
.v2-cmp-lab{text-align:center;font-size:var(--type-label-size);font-weight:800;letter-spacing:var(--type-label-ls);text-transform:uppercase;color:var(--ink-3)}
.v2-cmp-v{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:600;color:var(--ink-2)}
.v2-cmp-v.v2-win{font-weight:800;color:var(--ink-strong)}
.v2-pick{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);text-decoration:none;color:var(--ink);cursor:pointer;background:transparent;width:100%;text-align:left;font:inherit;border-left:0;border-right:0;border-bottom:0;padding:0}
.v2-pick .lh-sub{display:block}
.v2-cline .lh-c-line{stroke:var(--team,var(--ink-2))}
.v2-cline .v2-dot{fill:var(--team,var(--ink-2))}
button.v2-gtile{all:unset;box-sizing:border-box;cursor:pointer;min-height:var(--tap-min);background:var(--surface);border:var(--hairline) solid var(--line);border-radius:var(--radius-12);display:flex;flex-direction:column;align-items:center;gap:var(--space-4);padding:var(--space-8)}
button.v2-gtile[aria-pressed="true"]{border-color:var(--ink-strong)}
.v2-card-load{padding:var(--space-16);color:var(--ink-2);font-size:var(--type-body-size)}
"""


# =============================================================================
# small pieces
# =============================================================================

def _info(ids, key: str, meta: str = "") -> str:
    title, body = tip(key)
    pid = ids.next("tip")
    return (f'<span class="lh-info">' + (f'<span class="lh-meta">{clean(meta)}</span>' if meta else "")
            + f'<button type="button" aria-expanded="false" aria-controls="{pid}" aria-label="What {clean(title)} means">'
            f'{INFO}</button><span class="lh-info__pop" id="{pid}" role="note" hidden><b>{clean(title)}</b>'
            f'{clean(body)}</span></span>')


def _status(c: dict) -> str:
    kind = {"out": "out", "q": "q", "il": "il"}.get(c["kind"], "neutral")
    return f'<span class="lh-status lh-status--{kind}">{clean(c["text"])}</span>'


def _chip(chip: dict, small: bool = True, link: bool = False) -> str:
    cls = " v2-mini" if small else ""
    if not chip["cls"]:
        return f'<span class="lh-chip lh-chip--fa{cls}">{clean(chip["text"])}</span>'
    inner = f'<span class="lh-swatch"></span>{clean(chip["text"])}'
    if link and chip.get("m"):
        return (f'<a class="lh-chip {chip["cls"]}{cls} v2-tap" href="#/teams/{clean(chip["m"])}" '
                f'aria-label="{clean(chip["team"])}">{inner}</a>')
    return f'<span class="lh-chip {chip["cls"]}{cls}" title="{clean(chip["team"])}">{inner}</span>'


def _delta(d) -> str:
    if not d:
        return ""
    return f' <span class="lh-delta lh-delta--{clean(d["dir"])}">{clean(d["t"])}</span>'


def _name(r: dict) -> str:
    if r["key"]:
        return f'<a class="lh-name v2-tap" href="{clean(r["href"])}">{clean(r["name"])}</a>'
    return f'<span class="lh-name">{clean(r["name"])}</span>'


# =============================================================================
# the Players screen
# =============================================================================

def players_screen(vm: dict, ids) -> str:
    pv = vm["players"]
    o = ['<section class="v2-screen" data-route="players" hidden><div class="v2-stack">']
    if pv["error"]:
        o.append(f'<div class="v2-banner" role="status">The ratings failed on this run: no OVR or POT. '
                 f'{clean(pv["error"])}</div>')
    if pv["preview_arch"]:
        o.append('<div class="v2-calm">Archetype preview: the labels are shown for review only (local preview; '
                 'the archetype is off in the hub).</div>')
    o.append(f'<label class="v2-search">{SEARCH}<input type="search" id="pl-search" autocomplete="off" '
             f'placeholder="Search {clean(pv["count"])}" aria-label="Search players"></label>')
    o.append('<div class="lh-seg" role="tablist" data-filter="k" aria-label="Which players">'
             '<button type="button" role="tab" data-v="" aria-selected="true">All</button>'
             '<button type="button" role="tab" data-v="r" aria-selected="false">Rostered</button>'
             '<button type="button" role="tab" data-v="fa" aria-selected="false">Free agents</button></div>')
    o.append('<div class="v2-fchips">')
    for key, label in (("pos", "Position"), ("nba", "Team"), ("age", "Age")):
        o.append(f'<label class="v2-fchip">{clean(label)}<select data-filter="{key}" aria-label="{clean(label)}">'
                 '<option value="">Any</option>'
                 + "".join(f'<option value="{clean(x["v"])}">{clean(x["t"])}</option>' for x in pv["filters"][key])
                 + "</select></label>")
    o.append('<button type="button" class="v2-fchip" data-filter="h" aria-pressed="false">Healthy only</button></div>')
    o.append('<section class="lh-card lh-card--flush" data-section="players"><div class="lh-sechead v2-pad">'
             f'<h2 class="lh-eyebrow">Players</h2>{_info(ids, "ovr", pv["count"])}</div>'
             f'<div class="v2-scroll"><table class="lh-table v2-pt" id="pl-table" data-pcol="{clean(pv["default"])}" '
             f'data-pdir="d" data-porders=\'{clean(pv["orders_json"])}\'><thead><tr>')
    for k, lab in PLAYER_COLS:
        sort = ' aria-sort="descending"' if k == pv["default"] else ""
        cls = ' class="v2-sticky"' if k == "name" else ""
        o.append(f'<th{cls}{sort} data-k="{k}"><button type="button" class="v2-tap" data-psort="{k}">{clean(lab)}'
                 f'<span class="v2-arrow">{" &#9662;" if k == pv["default"] else ""}</span></button></th>')
    o.append('</tr></thead><tbody>')
    for r in pv["rows_default"]:                 # the engine's default order (OVR, best first)
        d = r["data"]
        sub = (_chip(r["chip"]) + f'<span>{clean(r["meta"])}</span>'
               + "".join(_status(c) for c in r["chips"]))
        o.append(f'<tr data-i="{r["i"]}" data-q="{clean(d["q"])}" data-k="{clean(d["k"])}" data-pos="{clean(d["pos"])}" '
                 f'data-nba="{clean(d["nba"])}" data-age="{clean(d["age"])}" data-h="{clean(d["h"])}">'
                 f'<td class="v2-sticky">{_name(r)}<span class="lh-sub">{sub}</span></td>'
                 f'<td class="v2-ovrcell"><span class="lh-ovr">{clean(r["ovr"])}</span>{_delta(r["ovr_d"])}</td>'
                 f'<td><span class="lh-pot">{clean(r["pot"])}</span></td><td>{clean(r["fppg"])}</td>'
                 f'<td>{clean(r["next"])}</td></tr>')
    o.append('</tbody></table></div><p class="v2-p v2-empty" id="pl-none" hidden>No player matches.</p>'
             f'<div class="lh-table-note">{clean(pv["who"])} Ratings as of {clean(pv["as_of"])}. '
             f'{clean(pv["change_note"])} Next is next week\'s games he will play. '
             'Tap a column to sort; tap again to reverse. Open any player and tap Compare to put two side by side.'
             '</div></section>')
    if pv["risers"] is not None:
        o.append('<section class="lh-card v2-gap8" data-section="risers"><div class="lh-sechead">'
                 '<h2 class="lh-eyebrow">Risers this week</h2><span class="lh-meta">OVR change</span></div>')
        if not pv["risers"]:
            o.append('<p class="v2-p">No player\'s OVR rose this week.</p>')
        for r in pv["risers"]:
            nm = (f'<a class="lh-name v2-tap" href="#/players/{clean(r["key"])}">{clean(r["name"])}</a>'
                  if r["key"] else f'<b>{clean(r["name"])}</b>')
            o.append(f'<div class="lh-divider v2-riser"><span class="v2-minw">{nm}'
                     f'<span class="lh-sub">{clean(r["reason"])}</span></span><span class="lh-num">'
                     f'<span class="v2-ovr-dsp">{clean(r["ovr"])}</span>'
                     f'<span class="lh-delta lh-delta--up">{clean(r["d"])}</span></span></div>')
        o.append("</section>")
    o.append("</div></section>")
    return "".join(o)


def card_screen(vm: dict) -> str:
    return ('<section class="v2-screen" data-route="player" data-detail="1" hidden>'
            f'<div class="v2-topbar"><button type="button" class="lh-back" data-back="#/players">{BACK}Back</button>'
            f'<span class="lh-meta">Updated <span class="v2-age">{clean(vm["age"])}</span></span></div>'
            '<div id="card-body"><p class="v2-card-load">Opening the card&hellip;</p></div></section>')


def compare_screens(vm: dict) -> str:
    pv = vm["players"]
    o = ['<section class="v2-screen" data-route="compare-pick" data-detail="1" hidden>'
         f'<div class="v2-topbar"><button type="button" class="lh-back" data-back="#/players">{BACK}Back</button>'
         '<span class="lh-meta">Compare</span></div><div class="v2-stack">'
         '<h2 class="lh-eyebrow">Compare <span id="cmp-a-name"></span> with</h2>'
         f'<label class="v2-search">{SEARCH}<input type="search" id="cmp-search" autocomplete="off" '
         'placeholder="Search for a player" aria-label="Search for the second player"></label>'
         '<section class="lh-card v2-list" id="cmp-pick">']
    for r in pv["pick"]:
        o.append(f'<button type="button" class="v2-pick" data-pick="{clean(r["key"])}" data-q="{clean(r["data"]["q"])}">'
                 f'<span class="v2-minw"><span class="lh-name">{clean(r["name"])}</span>'
                 f'<span class="lh-sub">{clean(r["chip"]["team"])} &middot; {clean(r["meta"])}</span></span>'
                 f'<span class="lh-ovr">{clean(r["ovr"])}</span></button>')
    o.append('</section></div></section>')
    o.append('<section class="v2-screen" data-route="compare" data-detail="1" hidden>'
             f'<div class="v2-topbar"><button type="button" class="lh-back" data-back="#/players">{BACK}Back</button>'
             '<span class="lh-meta">Compare</span></div><div class="v2-stack"><section class="lh-hero">'
             '<div class="v2-cmp-hero" id="cmp-hero"></div></section><section class="lh-card" id="cmp-rows"></section>'
             '<div class="lh-table-note">The better value in each row is in bold. Age has no winner, and a missing '
             'value wins nothing. Nothing here is a verdict: it is the numbers side by side.</div></div></section>')
    blob = pv["cmp_json"].replace("</", "<\\/")
    o.append(f'<script type="application/json" id="v2-cmp">{blob}</script>')
    return "".join(o)


# =============================================================================
# one player's card (rendered at build time; the page only inserts it)
# =============================================================================

class _CardIds:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.n = 0

    def next(self, p: str) -> str:
        self.n += 1
        return f"{self.prefix}{p}{self.n}"


def _kpi(k: dict, ids, tipkey: str = "") -> str:
    cls = {"up": "lh-delta lh-delta--up", "down": "lh-delta lh-delta--down"}.get(k["dir"], "lh-kpi__ctx")
    head = f'<span class="lh-label">{clean(k["label"])}</span>'
    if tipkey:
        head = f'<span class="v2-kpi-head">{head}{_info(ids, tipkey)}</span>'
    return (f'<div class="lh-kpi">{head}<span class="lh-kpi__value">{clean(k["value"])}</span>'
            f'<span class="{cls}">{clean(k["ctx"])}</span></div>')


def _grade(t: dict, gid: str) -> str:
    """A GradeTile; a tap shows its explanation under the grid (one InfoTip
    per section, so the eight tiles carry their words on the tap)."""
    title, body = tip("grade_" + t["key"])
    head = (f'<button type="button" class="lh-grade v2-gtile {t["cls"]}" aria-pressed="false" data-grid="{gid}" '
            f'data-tip="{clean(title)}: {clean(body)}" ')
    if t["letter"] == "\u2014" or not t["cls"]:
        return (head + f'aria-label="{clean(t["name"])}: no grade, {clean(t["reason"])}">'
                '<span class="lh-grade__letter">&mdash;</span>'
                f'<span class="lh-grade__name">{clean(t["name"])}</span>'
                f'<span class="lh-grade__pct">{clean(t["reason"])}</span></button>')
    extra = f' &middot; {clean(t["count"])}' if t["count"] else ""
    return (head + f'aria-label="{clean(t["name"])}: {clean(t["letter"])}, {clean(t["pct"])}">'
            f'<span class="lh-grade__letter">{clean(t["letter"])}</span>'
            f'<span class="lh-grade__name">{clean(t["name"])}</span><span class="lh-grade__bar" aria-hidden="true">'
            f'<span style="width:{clean(t["w"])}"></span></span>'
            f'<span class="lh-grade__pct">{clean(t["pct"])}{extra}</span></button>')


def _line(ch: dict, cid: str) -> str:
    o = [f'<svg class="lh-chart v2-cline" width="100%" viewBox="{ch["vb"]}" role="group" '
         f'aria-label="{clean(ch["aria"])}" data-chart="{cid}">']
    o += [f'<line class="{g["cls"]}" x1="{g["x1"]}" y1="{g["y1"]}" x2="{g["x2"]}" y2="{g["y2"]}"/>' for g in ch["grid"]]
    o += [f'<text x="{t["x"]}" y="{t["y"]}" text-anchor="{t["anchor"]}">{clean(t["t"])}</text>' for t in ch["labels"]]
    if ch["points"]:
        o.append(f'<polyline class="lh-c-line" points="{ch["points"]}"/>')
    if ch["dot"]:
        o.append(f'<circle class="v2-dot" cx="{ch["dot"]["cx"]}" cy="{ch["dot"]["cy"]}" r="4"/>')
    o.append('<circle class="v2-sel" r="6" cx="-20" cy="-20"/>')
    for h in ch["hits"]:
        o.append(f'<rect class="lh-c-hit" x="{h["x"]}" y="{h["y"]}" width="{h["w"]}" height="{h["h"]}" tabindex="0" '
                 f'role="button" aria-label="{clean(h["label"])}" data-cx="{h["cx"]}" data-cy="{h["cy"]}" '
                 f'data-head="{clean(h["head"])}" data-body="{clean(h["body"])}"/>')
    o.append("</svg>")
    o.append(f'<div class="lh-readout" aria-live="polite" data-readout="{cid}"><span class="v2-readout-h">'
             'Tap a point for its value.</span> <span></span></div>')
    if ch["empty"]:
        o.append(f'<p class="v2-p">{clean(ch["empty"])}</p>')
    return "".join(o)


def _rows(items: list, head_key: str, body_key: str, empty: str) -> str:
    if not items:
        return f'<p class="v2-p">{clean(empty)}</p>'
    return "".join(f'<div class="v2-li"><span class="v2-minw"><b>{clean(x[head_key])}</b>'
                   f'<span class="lh-sub">{clean(x[body_key])}</span></span><span></span></div>' for x in items)


def card_html(cv: dict) -> str:
    """One player's card: the hero, then Season / Career / Keeper / History."""
    key = cv["key"]
    ids = _CardIds(f"c-{key}-")
    h = cv["hero"]
    chip = {"text": h["chip"]["team"] if h["chip"]["slot"] else "Free agent",
            "cls": f'lh-t-{h["chip"]["slot"]}' if h["chip"]["slot"] else "", "team": h["chip"]["team"], "m": h["m"]}
    tcls = chip["cls"]
    o = [f'<div class="v2-cardwrap{" " + tcls if tcls else ""}" data-card-key="{clean(key)}"><section class="lh-hero">'
         '<div class="v2-hero-bar"><span class="lh-meta">Player</span>'
         f'<a class="lh-btn v2-btn" href="#/players/compare/{clean(key)}">Compare</a></div>'
         '<div class="lh-hero__top">'
         f'<div class="lh-headshot v2-hs" data-photo-slot="1" role="img" aria-label="{clean(h["name"])}">'
         f'<span class="v2-ini" aria-hidden="true">{clean(h["ini"])}</span></div><div class="v2-hero-r">']
    if h["ring"]:
        o.append('<div class="v2-ratings">'
                 f'<div class="lh-ring {tcls}"><svg width="80" height="80" viewBox="0 0 80 80" role="img" '
                 f'aria-label="Overall rating {clean(h["ovr"])} of 99"><circle class="lh-ring__track" cx="40" cy="40" r="34" '
                 'fill="none" stroke-width="7"/><circle class="lh-ring__arc" cx="40" cy="40" r="34" fill="none" '
                 f'stroke-width="7" stroke-linecap="round" stroke-dasharray="{clean(h["ring"])}" transform="rotate(-90 40 40)"/>'
                 f'</svg><div class="lh-ring__inner"><span class="lh-ring__value">{clean(h["ovr"])}</span>'
                 '<span class="lh-ring__label">OVR</span></div></div>'
                 f'<div class="v2-potcol"><span class="v2-kpi-head"><span class="lh-pot__label">POT</span>{_info(ids, "pot")}</span>'
                 f'<span class="lh-pot__value">{clean(h["pot"])}</span>'
                 + (f'<span class="lh-delta lh-delta--{clean(h["pot_dir"])}">POT {clean(h["pot_d"])}</span>' if h["pot_d"] else "")
                 + (f'<span class="lh-delta lh-delta--{clean(h["ovr_dir"])}">OVR {clean(h["ovr_d"])}</span>' if h["ovr_d"] else "")
                 + f'</div>{_info(ids, "ovr")}</div>')
    else:
        o.append(f'<div class="v2-fa-tile"><span class="lh-label">OVR</span><span class="lh-pot__value">&mdash;</span>'
                 f'<span class="lh-sub">{clean(h["ovr_note"])}</span></div>')
    o.append(f'<div class="v2-chiprow">{_chip(chip, small=False, link=True)}</div></div></div>')
    status = "".join(_status(c) for c in h["chips"]) or '<span class="lh-status lh-status--ok">Healthy</span>'
    o.append(f'<div class="v2-potcol"><h1 class="lh-hero__name">{clean(h["name"])}</h1>'
             f'<span class="lh-hero__bio">{clean(h["bio"])}</span><span class="v2-chiprow">{status}'
             + "".join(f'<span class="lh-sub">{clean(n)}</span>' for n in h["notes"]) + '</span></div>')
    if h.get("arch"):
        a = h["arch"]
        o.append('<div class="lh-hero__arch"><span class="v2-chiprow"><span class="v2-arch-h">'
                 f'{clean(a["label"])}</span>' + ('<span class="v2-preview">Preview</span>' if a["preview"] else "")
                 + f'</span><span class="v2-arch-k">{clean(a["kw"])}</span></div>')
    o.append('</section><div class="v2-stack"><div class="v2-pane-host">')
    o.append('<div class="lh-seg" role="tablist" data-seg="card">'
             + "".join(f'<button type="button" role="tab" data-pane="{k}" aria-selected="{"true" if i == 0 else "false"}">'
                       f'{lab}</button>' for i, (k, lab) in enumerate((("season", "Season"), ("career", "Career"),
                                                                       ("keeper", "Keeper"), ("history", "History"))))
             + "</div>")
    s = cv["season"]
    # Season
    o.append('<div class="v2-pane" data-pane-of="season"><section class="lh-card v2-gap8"><div class="lh-kpis">'
             + _kpi(s["kpis"][0], ids, "fppg") + _kpi(s["kpis"][1], ids) + _kpi(s["kpis"][2], ids)
             + _kpi(s["kpis"][3], ids) + "</div>"
             + (f'<span class="lh-sub">{clean(s["league"])}</span>' if s["league"] else "")
             + (f'<span class="v2-kpi-head"><span class="lh-sub">{clean(s["minutes"])}</span>{_info(ids, "min")}</span>'
                if s.get("minutes") else "") + "</section>")
    o.append(f'<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Attributes</h2>'
             f'{_info(ids, "grades", "vs rostered players")}</div>')
    if s["grades"]:
        gid = ids.next("g")
        o.append('<div class="lh-grades">' + "".join(_grade(t, gid) for t in s["grades"]) + "</div>"
                 f'<div class="lh-readout" aria-live="polite" data-readout="{gid}">Tap a grade for what it measures.</div>')
    else:
        o.append('<p class="v2-p">No grades: he has no rating on this run (the reason is under OVR).</p>')
    o.append("</section>")
    b = s["bars"]
    o.append('<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Fantasy points by game'
             '</h2><span class="lh-meta">this season</span></div>')
    if b.get("line"):                              # 4c2: past card.BAR_MAX_GAMES, a line
        o.append(_line(b["line"], ids.next("ch")))
        o.append('<div class="v2-axis">' + "".join(f"<span>{clean(t)}</span>" for t in b["axis"]) + "</div>")
    elif b["bars"]:
        cid = ids.next("bars")
        o.append(f'<div class="lh-bars v2-bars{" " + tcls if tcls else ""}" role="group" aria-label="{clean(b["aria"])}" '
                 f'data-bars="{cid}">')
        for x in b["bars"]:
            inner = '<span class="v2-inj"></span>' if x["inj"] else f'<span style="height:{clean(x["h"])}"></span>'
            o.append(f'<button type="button" class="v2-bar" aria-pressed="false" aria-label="{clean(x["label"])}" '
                     f'data-label="{clean(x["label"])}">{inner}</button>')
        if b["avg"]:
            o.append(f'<span class="lh-bars__avg" style="--y:{clean(b["avg"]["y"])}"></span>'
                     f'<span class="lh-bars__avglabel" style="--y:{clean(b["avg"]["y"])}">{clean(b["avg"]["t"])}</span>')
        o.append("</div>")
        o.append('<div class="v2-axis">' + "".join(f"<span>{clean(t)}</span>" for t in b["axis"]) + "</div>")
        o.append(f'<div class="lh-readout" aria-live="polite" data-readout="{cid}">Tap a bar for the game.</div>')
    else:
        o.append(f'<p class="v2-p">{clean(b["aria"])}</p>')
    o.append("</section>")
    o.append('<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Keeper outlook</h2>'
             f'{_info(ids, "keep")}</div><p class="v2-p">{clean(s["keep"]["text"])}</p></section>')
    o.append('<section class="lh-card lh-card--flush"><div class="lh-sechead v2-pad"><h2 class="lh-eyebrow">Last 5 games'
             '</h2></div>')
    if s["last"]:
        o.append('<table class="lh-table v2-last"><thead><tr><th>Day</th><th>Opp</th><th>FP</th><th>MIN</th></tr></thead>'
                 '<tbody>'
                 + "".join(f'<tr><td>{clean(g["day"])}</td><td>{clean(g["opp"])}</td><td>{clean(g["fp"])}</td>'
                           f'<td>{clean(g["min"])}</td></tr>' for g in s["last"]) + "</tbody></table>")
    else:
        o.append('<p class="v2-p v2-empty">No games this season yet.</p>')
    o.append("</section></div>")
    # Career
    c = cv["career"]
    o.append('<div class="v2-pane" data-pane-of="career" hidden><section class="lh-card v2-gap8"><div class="lh-sechead">'
             '<h2 class="lh-eyebrow">FPPG by season</h2></div>' + _line(c["chart"], ids.next("ch")) + "</section>")
    o.append('<section class="lh-card lh-card--flush"><div class="lh-sechead v2-pad"><h2 class="lh-eyebrow">By season</h2>'
             '</div>')
    if c["rows"]:
        o.append('<div class="v2-scroll"><table class="lh-table"><thead><tr><th>Season</th><th>GP</th><th>FPPG</th>'
                 '<th>Total</th><th>With</th></tr></thead><tbody>'
                 + "".join(f'<tr><td>{clean(r["season"])}</td><td>{clean(r["gp"])}</td><td>{clean(r["fppg"])}</td>'
                           f'<td>{clean(r["total"])}</td><td>{clean(r["who"])}</td></tr>' for r in c["rows"]))
        t = c["total"]
        o.append(f'<tr class="lh-group"><td>Career &middot; {clean(t["seasons"])}</td><td>{clean(t["gp"])}</td>'
                 f'<td>{clean(t["fppg"])}</td><td>{clean(t["total"])}</td><td></td></tr></tbody></table></div>')
    o.append(f'<div class="lh-table-note">{clean(c["note"])}</div></section></div>')
    # Keeper
    k = cv["keeper"]
    o.append('<div class="v2-pane" data-pane-of="keeper" hidden><section class="lh-card v2-gap8"><div class="lh-kpis">'
             f'<div class="lh-kpi"><span class="v2-kpi-head"><span class="lh-label">Keep %</span>{_info(ids, "keep")}</span>'
             f'<span class="lh-kpi__value">{clean(k["keep"])}</span><span class="lh-kpi__ctx">{clean(k["keep_ctx"])}</span></div>'
             f'<div class="lh-kpi"><span class="v2-kpi-head"><span class="lh-label">POT</span>{_info(ids, "pot")}</span>'
             f'<span class="lh-kpi__value">{clean(k["pot"])}</span><span class="lh-kpi__ctx">{clean(k["rank"])}</span>'
             + (f'<span class="lh-delta lh-delta--{clean(k["pot_dir"])}">{clean(k["pot_d"])}</span>' if k["pot_d"] else "")
             + '</div></div></section>')
    o.append('<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">The age curve</h2>'
             f'{_info(ids, "age_curve")}</div><p class="v2-p">{clean(k["curve"]["text"])}</p>'
             + _line(k["curve"]["chart"], ids.next("ch")) + "</section></div>")
    # History
    hs = cv["history"]
    o.append('<div class="v2-pane" data-pane-of="history" hidden>'
             '<section class="lh-card v2-gap8"><h2 class="lh-eyebrow">Ownership</h2>'
             + _rows(hs["own"], "season", "text", "Never on a league roster.") + "</section>"
             '<section class="lh-card v2-gap8"><h2 class="lh-eyebrow">Draft</h2>'
             + _rows(hs["drafts"], "season", "text", "Never drafted in this league.") + "</section>"
             '<section class="lh-card v2-gap8"><h2 class="lh-eyebrow">Trades</h2>'
             + _rows(hs["trades"], "season", "text", "Never traded in this league.") + "</section>"
             '<section class="lh-card v2-gap8"><h2 class="lh-eyebrow">Record book</h2>')
    if hs["records"]:
        o.append("".join(f'<div class="v2-li"><span class="v2-minw"><b>{clean(r["record"])}</b>'
                         f'<span class="lh-sub">{clean(r["detail"])}</span></span>'
                         f'<span class="lh-num">{clean(r["rank"])} &middot; {clean(r["value"])}</span></div>'
                         for r in hs["records"]))
    else:
        o.append('<p class="v2-p">No record-book entries.</p>')
    o.append("</section></div></div></div></div>")
    return "".join(o)
