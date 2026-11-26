"""
hub_v2/page_manager.py -- the manager card's renderer (MC2): the strings of
hub_v2/manager.py as one screen per manager, #/manager/<name> and
#/manager/<name>/<tab> (Overview . Career . Rivals . Players . Trophies, the
hero above every tab; on desktop each pane's cards in the hub's two columns).

THE PAGE DISPLAYS; THE ENGINE COMPUTES: every string through clean(), no
arithmetic here (tests/test_mc2_manager.py pins it, as test_hub_v2 pins
page.render). CSS rules: tokens only (var(--...)); no hex colour, no px
literal; media-query widths as {{token}}.

THE FIRST LOAD: published, each card is a lazy screen (publish.lazy_routes):
the page keeps the screen's tag and its top bar; the card, and CSS (inside
the part), arrive when the card is first opened. Only MGR_LINK_CSS (the name
link's dotted underline) and the route lines in PAGE_JS are in the first load.
"""
from __future__ import annotations

from .text import clean

TAP_CLASSES = ("mc-fin", "mc-tile")
# in the first load: a manager's name, a link to his card (the dotted underline player names have)
MGR_LINK_CSS = ("a.v2-mn{color:inherit;font-weight:inherit;text-decoration:underline dotted var(--axis-strong);"
                "text-underline-offset:var(--space-2)}")

CSS = """
.mc .lh-card{display:flex;flex-direction:column;gap:var(--space-10)}
.mc-hero{display:flex;flex-direction:column;gap:var(--space-12)}
.mc-hrow{display:flex;justify-content:space-between;align-items:center;gap:var(--space-8)}
.mc-top{display:grid;grid-template-columns:var(--mono-72) minmax(0,1fr);column-gap:var(--space-14);align-items:center}
.mc-name{font-family:var(--font-display);font-size:var(--type-display-xl-size);line-height:1;font-weight:800;margin:0;color:var(--ink)}
.mc-bio{font-size:var(--type-body-size);color:var(--ink-2);margin-top:var(--space-4)}
.mc-names{display:flex;flex-wrap:wrap;gap:var(--space-4);margin-top:var(--space-6)}
.mc-tn{font-size:var(--type-small-size);font-weight:700;color:var(--ink-2);background:var(--surface-subtle);border-radius:var(--radius-pill);padding:var(--space-2) var(--space-8)}
.mc-tn--now{background:var(--team-tint);color:var(--team-ink)}
.mc-hon{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:var(--space-6)}
.mc-ht{border-radius:var(--radius-9);padding:var(--space-8) var(--space-10);background:var(--surface-subtle);min-width:0;display:flex;flex-direction:column;gap:var(--space-2)}
.mc-ht b{font-family:var(--font-display);font-size:var(--type-display-lg-size);line-height:1;font-weight:800;color:var(--ink)}
.mc-ht span{font-size:var(--type-small-size);font-weight:800;color:var(--ink-2);line-height:1.2}
.mc-ht em{font-style:normal;font-size:var(--type-small-size);color:var(--ink-3);line-height:1.25}
.mc-ht--lc{background:var(--dark)}
.mc-ht--lc b,.mc-ht--lc span{color:var(--ink-on-dark)} .mc-ht--lc em{color:var(--ink-on-dark-2)}
.mc-k3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-6)}
.mc-k{min-width:0;display:flex;flex-direction:column}
.mc-k b{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:800;font-variant-numeric:tabular-nums;color:var(--ink);white-space:nowrap}
.mc-k small{font-size:var(--type-small-size);color:var(--ink-3);font-weight:600}
.mc-k small.mc-up{color:var(--up)} .mc-k small.mc-down{color:var(--down)}
.mc-foot{font-size:var(--type-small-size);color:var(--ink-3);line-height:1.35;margin:0}
.mc-strip{display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));gap:var(--space-2);align-items:end}
button.mc-fin{all:unset;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;gap:var(--space-2);cursor:pointer;min-height:var(--tap-min);min-width:0}
.mc-marks{display:block;width:100%;min-height:var(--space-14);overflow:hidden;white-space:nowrap;text-align:center;font-size:var(--type-label-size);line-height:1.2;color:var(--team-ink)}
.mc-sq{width:100%;aspect-ratio:1/1.15;border-radius:var(--radius-6);display:flex;align-items:center;justify-content:center;font-family:var(--font-display);font-weight:800;font-size:var(--type-heading-size)}
.mc-p1 .mc-sq{background:var(--team);color:var(--surface)}
.mc-p2 .mc-sq{background:var(--team-tint);color:var(--team-ink)}
.mc-p3 .mc-sq,.mc-p4 .mc-sq{background:var(--surface-subtle);color:var(--ink-3)}
.mc-pre .mc-sq{outline:calc(var(--hairline)*1.5) dashed var(--axis-strong);outline-offset:var(--hairline)}
.mc-live .mc-sq{box-shadow:inset 0 0 0 calc(var(--hairline)*2) var(--team);background:var(--surface);color:var(--team-ink)}
.mc-yr{font-size:var(--type-label-size);font-weight:700;color:var(--ink-3);text-align:center;line-height:1.1}
.mc-ks > b,.mc-bys > b{white-space:nowrap}
button.mc-fin[aria-pressed="true"] .mc-yr{background:var(--dark);color:var(--ink-on-dark);border-radius:var(--radius-3);padding:0 var(--space-2)}
.mc-legend{display:flex;flex-wrap:wrap;gap:var(--space-4) var(--space-12);font-size:var(--type-small-size);color:var(--ink-2)}
.mc-tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-6)}
.mc-tile{display:flex;flex-direction:column;gap:var(--space-2);background:var(--surface-subtle);border-radius:var(--radius-6);padding:var(--space-8) var(--space-10);text-decoration:none;color:var(--ink);min-height:var(--tap-min);min-width:0}
.mc-tile span{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);text-transform:uppercase}
.mc-tile b{font-size:var(--type-heading-size);font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mc-tile em{font-style:normal;font-size:var(--type-meta-size);color:var(--ink-2)}
.mc-li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:var(--space-8);align-items:center;padding:var(--space-8) 0;border-bottom:var(--hairline) solid var(--line-soft);min-height:var(--tap-min)}
.mc-li:last-child{border-bottom:0}
.mc-li .lh-sub{display:block}
.mc-v{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:800;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.mc-v small{display:block;font-family:var(--font-sans);font-size:var(--type-small-size);color:var(--ink-3);font-weight:600}
.mc-muted{opacity:.62}
.mc-fp{display:grid;grid-template-columns:var(--mono-72) minmax(0,1fr);column-gap:var(--space-12);align-items:center}
.mc-ini{width:var(--mono-72);height:var(--mono-72);border-radius:50%;background:var(--team-tint);color:var(--team-ink);display:flex;align-items:center;justify-content:center;font-family:var(--font-display);font-weight:800;font-size:var(--type-title-size)}
.mc-big{font-family:var(--font-display);font-size:var(--type-title-size);font-weight:800}
.mc-ks{display:grid;grid-template-columns:calc(var(--space-32)*2) minmax(0,1fr) auto;gap:var(--space-8);align-items:start;padding:var(--space-6) 0;border-bottom:var(--hairline) solid var(--line-soft)}
.mc-ks:last-child{border-bottom:0}
.mc-chips{display:flex;flex-wrap:wrap;gap:var(--space-4)}
.mc-chip{font-size:var(--type-small-size);font-weight:700;color:var(--ink-2);background:var(--surface-subtle);border-radius:var(--radius-pill);padding:var(--space-2) var(--space-8);white-space:nowrap}
.mc-chip--lc{background:var(--dark);color:var(--ink-on-dark)}
.mc-chip--po{background:var(--team-tint);color:var(--team-ink)}
.mc-chip--apart{background:transparent;color:var(--ink-3);box-shadow:inset 0 0 0 var(--hairline) var(--line);font-weight:600}
.mc-chip--new{box-shadow:inset 0 0 0 calc(var(--hairline)*1.5) var(--team)}
.mc-tc{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:var(--space-6)}
.mc-tcn{background:var(--surface-subtle);border-radius:var(--radius-6);padding:var(--space-6);display:flex;flex-direction:column;gap:var(--space-2);min-width:0;min-height:var(--tap-min)}
.mc-tcn b{font-family:var(--font-display);font-size:var(--type-title-size);font-weight:800;line-height:1.05}
.mc-tcn span{font-size:var(--type-small-size);font-weight:700;color:var(--ink-2);line-height:1.15}
.mc-tcn--lc{background:var(--dark);grid-column:span 2} .mc-tcn--lc b,.mc-tcn--lc span{color:var(--ink-on-dark)}
.mc-tcn--po{background:var(--team-tint)} .mc-tcn--po b,.mc-tcn--po span{color:var(--team-ink)}
.mc-tcn--apart{background:transparent;box-shadow:inset 0 0 0 var(--hairline) var(--line)} .mc-tcn--apart b,.mc-tcn--apart span{color:var(--ink-3)}
.mc-bys{display:grid;grid-template-columns:calc(var(--space-32)*2) minmax(0,1fr);gap:var(--space-8);padding:var(--space-8) 0;border-bottom:var(--hairline) solid var(--line-soft);align-items:start}
.mc-bys:last-child{border-bottom:0}
.mc-aw{display:flex;align-items:center;gap:var(--space-6);flex-wrap:wrap;margin-bottom:var(--space-4)}
.mc-rh{display:grid;grid-template-columns:var(--mono-36) minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center}
.mc-rec{font-family:var(--font-display);font-size:var(--type-display-md-size);font-weight:800;font-variant-numeric:tabular-nums;text-align:right;line-height:1}
.mc-rec small{display:block;font-family:var(--font-sans);font-size:var(--type-small-size);font-weight:700;color:var(--ink-3);margin-top:var(--space-2)}
.mc-bar{display:flex;height:var(--space-6);border-radius:var(--radius-pill);overflow:hidden;gap:var(--space-2)}
.mc-bar i{display:block;height:100%;background:var(--team)}
.mc-r4{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--space-6)}
.mc-r4 > div{background:var(--surface-subtle);border-radius:var(--radius-6);padding:var(--space-6) var(--space-8);min-width:0}
.mc-r4 span{display:block;font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);text-transform:uppercase}
.mc-r4 b{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:800}
.mc-r4 em{display:block;font-style:normal;font-size:var(--type-small-size);color:var(--ink-2)}
.mc-tag{font-size:var(--type-label-size);font-weight:800;text-transform:uppercase;border-radius:var(--radius-pill);padding:0 var(--space-6);background:var(--dark);color:var(--ink-on-dark);margin-left:var(--space-4)}
.mc .lh-chart .v2-c-faint{stroke:var(--axis);stroke-width:1.5}
.mc .lh-chart .v2-c-lab-faint{fill:var(--ink-3);font-weight:600}
.mc .lh-chart .mc-lg .lh-c-line{stroke:var(--ink-3);stroke-width:1.5}
.mc .lh-chart .mc-lg text,.mc .lh-chart g.mc-lg .lh-c-label{fill:var(--ink-3)}
.mc .lh-chart .mc-bar-up{fill:var(--team)} .mc .lh-chart .mc-bar-dn{fill:var(--axis-strong)}
.mc .lh-chart .mc-bar-live{opacity:.5}
.mc .lh-chart .mc-hatch{fill:var(--surface-subtle);stroke:var(--axis);stroke-dasharray:3 3}
.mc .lh-chart .mc-val{font-weight:800;fill:var(--ink-2)}
.mc-tbl td,.mc-tbl th{white-space:nowrap}
.mc-tbl td .lh-sub{display:block}
.mc-pre td{color:var(--ink-3)}
@media (min-width:{{bp-wide}}){
 .mc-dhero{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:var(--space-20);align-items:start}
 .mc-tc{grid-template-columns:repeat(6,minmax(0,1fr))}
}
"""


def _mono(team: dict, cls: str, size: str) -> str:
    return (f'<span class="lh-mono {cls} v2-mono-{size}" aria-hidden="true">{clean(team["mono"])}</span>')


def _sec(title: str, meta: str = "") -> str:
    return (f'<div class="lh-sechead"><h2 class="lh-eyebrow">{clean(title)}</h2>'
            + (f'<span class="lh-meta">{clean(meta)}</span>' if meta else "") + "</div>")


def _pl(name: str, card) -> str:
    if card:
        return f'<button type="button" class="v2-pl v2-tap" data-card="{clean(card)}">{clean(name)}</button>'
    return clean(name)


def mlink(m: str, text: str = None) -> str:
    """A manager's name, opening his card (the dotted underline player names have)."""
    return f'<a class="v2-mn v2-tap" href="#/manager/{clean(m)}">{clean(text if text is not None else m)}</a>'


def _chart(chart_fn, ch: dict, cid: str) -> str:
    return chart_fn(ch, cid)


def _bars(ch: dict, cid: str) -> str:
    o = [f'<svg class="lh-chart" width="100%" viewBox="{ch["vb"]}" role="group" aria-label="{clean(ch["aria"])}" '
         f'data-chart="{cid}">']
    o += [f'<line class="{g["cls"]}" x1="{g["x1"]}" y1="{g["y1"]}" x2="{g["x2"]}" y2="{g["y2"]}"/>' for g in ch["grid"]]
    o += [f'<text x="{t["x"]}" y="{t["y"]}" text-anchor="{t["anchor"]}">{clean(t["t"])}</text>' for t in ch["labels"]]
    for b in ch["bars"]:
        o.append(f'<rect class="{b["cls"]}" x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="2"/>')
        if b["t"]:
            o.append(f'<text class="mc-val" x="{b["tx"]}" y="{b["ty"]}" text-anchor="middle">{clean(b["t"])}</text>')
    if ch.get("ref"):
        r = ch["ref"]
        o.append(f'<line class="lh-c-ref" x1="{r["x1"]}" y1="{r["y"]}" x2="{r["x2"]}" y2="{r["y"]}"/>')
    o.append('<circle class="v2-sel" r="6" cx="-20" cy="-20"/>')
    for h in ch["hits"]:
        o.append(f'<rect class="lh-c-hit" x="{h["x"]}" y="{h["y"]}" width="{h["w"]}" height="{h["h"]}" tabindex="0" '
                 f'role="button" aria-label="{clean(h["label"])}" data-cx="{h["cx"]}" data-cy="{h["cy"]}" '
                 f'data-head="{clean(h["head"])}" data-body="{clean(h["body"])}"/>')
    o.append("</svg>")
    r0 = ch["readout0"]
    o.append(f'<div class="lh-readout" aria-live="polite" data-readout="{cid}"><span class="v2-readout-h">'
             f'{clean(r0["head"])}</span> <span>{clean(r0["body"])}</span></div>')
    return "".join(o)


def _hero(c: dict, cls: str) -> str:
    h = c["hero"]
    o = ['<section class="lh-card mc-hero"><div class="mc-dhero"><div>',
         f'<div class="mc-hrow"><span class="lh-meta">Manager</span>'
         f'<a class="lh-btn v2-btn" href="{clean(h["team_href"])}">Team page &rsaquo;</a></div>',
         f'<div class="mc-top">{_mono(c["team"], cls, "72")}<div class="v2-minw"><h1 class="mc-name">{clean(h["name"])}</h1>'
         f'<span class="mc-bio">{clean(h["bio"])}</span><span class="mc-names">'
         + "".join(f'<span class="mc-tn{" mc-tn--now" if n["now"] else ""}">{clean(n["t"])}</span>' for n in h["names"])
         + "</span></div></div></div><div>",
         '<div class="mc-hon">' + "".join(
             f'<div class="mc-ht{" mc-ht--lc" if x["k"] == "lc" else ""}"><b>{clean(x["n"])}</b>'
             f'<span>{clean(x["label"])}</span><em>{clean(x["sub"])}</em></div>' for x in h["hon"]) + "</div>",
         '<div class="mc-k3">' + "".join(
             f'<div class="mc-k"><span class="lh-label">{clean(k["label"])}</span><b>{clean(k["v"])}</b>'
             f'<small>{clean(k["sub"])}</small></div>' for k in h["kpis"]) + "</div>",
         f'</div></div><p class="mc-foot">{clean(h["foot"])}</p></section>']
    return "".join(o)


def _overview(c: dict, cid: str, chart_fn) -> str:
    ov = c["overview"]
    s = ov["season"]
    a = ['<section class="lh-card">', _sec("This season", s["meta"]), '<div class="mc-k3">']
    for k in s["kpis"]:
        d = {"up": " mc-up", "down": " mc-down"}.get(k["dir"], "")
        a.append(f'<div class="mc-k"><span class="lh-label">{clean(k["label"])}</span><b>{clean(k["v"])}</b>'
                 f'<small class="{d.strip()}">{clean(k["sub"])}</small></div>')
    a.append('</div><span class="lh-label">Title odds over the season</span>')
    a.append(chart_fn(s["chart"], f"{cid}-odds"))
    a.append("</section>")
    st = ov["strip"]
    b = ['<section class="lh-card">', _sec("Every season", "regular-season finish"),
         f'<div class="mc-strip" style="--n:{clean(st["n"])}">']
    for x in st["cells"]:
        kind = {"pre": " mc-pre", "live": " mc-live"}.get(x["kind"], "")
        b.append(f'<button type="button" class="mc-fin v2-gtile {x["p"]}{kind}" data-grid="{cid}-fin" '
                 f'data-tip="{clean(x["tip"])}" aria-pressed="{"true" if x["s"] == st["sel"] else "false"}" '
                 f'aria-label="{clean(x["tip"])}"><span class="mc-marks">{clean(x["marks"])}</span>'
                 f'<span class="mc-sq">{clean(x["place"])}</span><span class="mc-yr">{clean(x["yr"])}<br>{clean(x["yr2"])}</span>'
                 '</button>')
    b.append('</div><div class="mc-legend"><span>&#9733; League Championship</span><span>&#9670; Playoff title</span>'
             '<span>&ndash; no playoffs that season</span><span>dashed: standings and brackets only</span>'
             '<span>outlined: this season, so far</span></div>')
    b.append(f'<p class="v2-p" aria-live="polite" data-readout="{cid}-fin">{clean(st["readout"])}</p>'
             f'<span class="lh-sub">{clean(st["note"])}</span></section>')
    g = ['<section class="lh-card">', _sec("At a glance"), '<div class="mc-tiles">']
    for t in ov["glance"]:
        g.append(f'<a class="mc-tile" href="{clean(t["href"])}"><span>{clean(t["k"])}</span><b>{clean(t["b"])}</b>'
                 f'<em>{clean(t["e"])}</em></a>')
    g.append("</div></section>")
    return ('<div class="v2-cols"><div class="v2-col">' + "".join(a) + '</div><div class="v2-col">'
            + "".join(b) + "".join(g) + "</div></div>")


def _career(c: dict, cid: str, chart_fn) -> str:
    k = c["career"]
    a = ['<section class="lh-card">', _sec("Points a week vs the league", "regular season"),
         _bars(k["ppw"], f"{cid}-ppw"), f'<span class="lh-sub">{clean(k["ppw_note"])}</span></section>']
    t = ['<section class="lh-card lh-card--flush">', '<div class="v2-pad">', _sec("Season by season"), "</div>",
         '<div class="v2-scroll"><table class="lh-table mc-tbl"><thead><tr><th>Season</th><th>Finish</th><th>W-L</th><th>Pts/wk</th>'
         '<th>Playoffs</th></tr></thead><tbody>']
    for r in k["rows"]:
        t.append(f'<tr{" class=" + chr(34) + "mc-pre" + chr(34) if r["pre"] else ""}><td><b>{clean(r["s"])}</b>'
                 f'<span class="lh-sub">{clean(r["team"])}</span></td><td>{clean(r["fin"])}</td><td>{clean(r["wl"])}</td>'
                 f'<td>{clean(r["ppw"])}<span class="lh-sub">{clean(r["gap"])}</span></td><td>{clean(r["po"])}</td></tr>')
    t.append(f'</tbody></table></div><div class="lh-table-note">{clean(k["note"])}</div></section>')
    sty = k["style"]
    s = ['<section class="lh-card">', _sec("His style"), '<span class="lh-label">Lineup: share of all daily slots '
         'filled</span>', chart_fn(sty["fill"], f"{cid}-fill"), f'<span class="lh-sub">{clean(sty["fill_note"])}</span>',
         '<span class="lh-label">Pickups a season</span>', _bars(sty["picks"], f"{cid}-picks"),
         f'<span class="lh-sub">{clean(sty["picks_note"])}</span><div class="mc-tiles">']
    for x in sty["tiles"]:
        s.append(f'<div class="mc-tile mc-tl"><span>{clean(x["k"])}</span><b>{clean(x["b"])}</b><em>{clean(x["e"])}</em></div>')
    s.append("</div></section>")
    return ('<div class="v2-cols"><div class="v2-col">' + "".join(a) + "".join(s) + '</div><div class="v2-col">'
            + "".join(t) + "</div></div>")


def _rivals(c: dict, cid: str, teams: dict) -> str:
    rv = c["rivals"]
    mine = f'lh-t-{c["team"]["slot"]}'
    o = ['<section class="lh-card">', _sec("Head to head"),
         f'<div class="lh-seg" role="tablist" data-seg="mgrph">'
         + "".join(f'<button type="button" role="tab" data-pane="{p["k"]}" aria-selected="{"true" if i == 0 else "false"}">'
                   f'{clean(p["t"])}</button>' for i, p in enumerate(rv["phases"])) + "</div>"]
    for i, p in enumerate(rv["phases"]):
        o.append(f'<div class="v2-pane" data-pane-of="{p["k"]}"{"" if i == 0 else " hidden"}>'
                 f'<p class="v2-p">{clean(p["intro"])}</p>')
        if p["empty"]:
            o.append("</div>")
            continue
        o.append('<div class="v2-cols">')
        for r in p["rows"]:
            t = teams[r["o"]]
            o.append(f'<div class="lh-card {r["cls"]}"><div class="mc-rh">{_mono(t, r["cls"], "36")}'
                     f'<div class="v2-minw"><b>v {mlink(r["o"])}{"<span class=" + chr(34) + "mc-tag" + chr(34) + ">Nemesis</span>" if r["nemesis"] else ""}</b>'
                     f'<span class="lh-sub">{clean(r["team"])}{" &middot; " if r["post"] else ""}{clean(r["post"])}</span></div>'
                     f'<span class="mc-rec">{clean(r["rec"])}<small>{clean(r["pct"])}</small></span></div>'
                     f'<div class="mc-bar"><i style="width:{clean(r["bar"])}" class="{mine}"></i>'
                     f'<i class="{r["cls"]}" style="flex:1"></i></div>'
                     f'<div class="mc-r4"><div><span>His longest run</span><b>{clean(r["his_run"]["v"])}</b>'
                     f'<em>{clean(r["his_run"]["e"])}</em></div><div><span>{clean(r["o"])}&rsquo;s longest</span>'
                     f'<b>{clean(r["their_run"]["v"])}</b><em>{clean(r["their_run"]["e"])}</em></div>'
                     f'<div><span>Biggest win</span><b>{clean(r["big_win"]["v"])}</b><em>{clean(r["big_win"]["e"])}</em></div>'
                     f'<div><span>Worst loss</span><b>{clean(r["worst_loss"]["v"])}</b><em>{clean(r["worst_loss"]["e"])}</em></div></div>'
                     f'<span class="lh-sub">{clean(r["last"])}</span></div>')
        o.append("</div></div>")
    o.append(f'<span class="lh-sub">{clean(rv["note"])}</span></section>')
    return "".join(o)


def _players(c: dict) -> str:
    p = c["players"]
    a = ['<section class="lh-card">', _sec("Franchise player", "most points for him")]
    f = p["franchise"]
    if f:
        a.append(f'<div class="mc-fp"><span class="mc-ini">{clean(f["ini"])}</span><div class="v2-minw">'
                 f'<b>{_pl(f["name"], f["card"])}</b><span class="lh-sub">{clean(f["sub"])}</span>'
                 f'<span class="mc-big">{clean(f["pts"])}</span><span class="lh-sub">fantasy points for him</span></div></div>')
    else:
        a.append('<p class="v2-p">Not in the record book yet.</p>')
    a.append(f'<span class="lh-sub">{clean(p["franchise_note"])}</span></section>')
    b = ['<section class="lh-card">', _sec("Best pickups", "PAR for him")]
    for x in p["pickups"]:
        b.append(f'<div class="mc-li"><span><b>{_pl(x["name"], x["card"])}</b><span class="lh-sub">{clean(x["sub"])}</span></span>'
                 f'<span class="mc-v">{clean(x["v"])}<small>{clean(x["unit"])}</small></span></div>')
    b.append(f'<span class="lh-sub">{clean(p["pickups_note"])}</span></section>')
    t = ['<section class="lh-card">', _sec("Best trades", "PAR gap, picks estimated")]
    for x in p["trades"]:
        t.append(f'<div class="mc-li"><span><b>{mlink(x["o"])} &middot; {clean(x["when"])}</b>'
                 f'<span class="lh-sub">got {clean(x["got"])}; gave {clean(x["gave"])}</span></span>'
                 f'<span class="mc-v">{clean(x["v"])}<small>{clean(x["unit"])}</small></span></div>')
    w = p["worst_trade"]
    if w:
        t.append(f'<div class="mc-li mc-muted"><span><b>Worst: {mlink(w["o"])} &middot; {clean(w["when"])}</b>'
                 f'<span class="lh-sub">gave {clean(w["gave"])}; got {clean(w["got"])}</span></span>'
                 f'<span class="mc-v">{clean(w["v"])}<small>PAR gap</small></span></div>')
    t.append(f'<span class="lh-sub">{clean(p["trades_note"])}</span></section>')
    d = ['<section class="lh-card">', _sec("Best draft classes", "PAR, keepers apart")]
    for x in p["drafts"]:
        d.append(f'<div class="mc-li"><span><b>{clean(x["s"])} draft{" &middot; Draft of the year" if x["won"] else ""}</b>'
                 f'<span class="lh-sub">best pick: {_pl(x["name"], x["card"]) if x["name"] else "&mdash;"}</span></span>'
                 f'<span class="mc-v">{clean(x["v"])}<small>PAR</small></span></div>')
    d.append(f'<span class="lh-sub">{clean(p["drafts_note"])}</span></section>')
    k = ['<section class="lh-card">', _sec("Keepers by season", "average age")]
    for x in p["keepers"]:
        k.append(f'<div class="mc-ks"><b>{clean(x["s"])}</b><span class="mc-chips">'
                 + "".join(f'<span class="mc-chip{" mc-chip--new" if n["new"] else ""}" title="{clean(n["full"])}">'
                           f'{clean(n["t"])}</span>' for n in x["names"])
                 + f'</span><span class="mc-v">{clean(x["age"])}</span></div>')
    if not p["keepers"]:
        k.append('<p class="v2-p">No keepers on record.</p>')
    k.append(f'<span class="lh-sub">{clean(p["keepers_note"])}</span></section>')
    return ('<div class="v2-cols"><div class="v2-col">' + "".join(a) + "".join(b) + "".join(d)
            + '</div><div class="v2-col">' + "".join(t) + "".join(k) + "</div></div>")


def _trophies(c: dict, tip_attrs) -> str:
    tr = c["trophies"]
    a = ['<section class="lh-card">', _sec("Trophy case", "finished seasons"), '<div class="mc-tc">']
    for x in [x for x in tr["case"] if not x["apart"]]:
        cls = {"league": " mc-tcn--lc", "playoff": " mc-tcn--po"}.get(x["k"], "")
        attrs = (tip_attrs(x["tip"]) + ' role="button" tabindex="0"') if x["tip"] else ""
        a.append(f'<div class="mc-tcn{cls}{" v2-tap" if x["tip"] else ""}"{attrs}><b>{clean(x["n"])}</b>'
                 f'<span>{clean(x["label"])}</span></div>')
    a.append('</div><span class="lh-label">Kept apart, not honours</span><div class="mc-tc">')
    for x in [x for x in tr["case"] if x["apart"]]:
        attrs = (tip_attrs(x["tip"]) + ' role="button" tabindex="0"') if x["tip"] else ""
        a.append(f'<div class="mc-tcn mc-tcn--apart{" v2-tap" if x["tip"] else ""}"{attrs}><b>{clean(x["n"])}</b>'
                 f'<span>{clean(x["label"])}</span></div>')
    a.append(f'</div><span class="lh-sub">{clean(tr["note"])}</span></section>')
    b = ['<section class="lh-card">', _sec("By season")]
    for s in tr["by_season"]:
        b.append(f'<div class="mc-bys"><b>{clean(s["s"])}</b><div>')
        for x in s["items"]:
            cl = {"lc": " mc-chip--lc", "po": " mc-chip--po", "apart": " mc-chip--apart"}.get(x["cls"], "")
            b.append(f'<span class="mc-aw"><span class="mc-chip{cl}">{clean(x["t"])}</span>'
                     f'<span class="lh-sub">{clean(x["what"])}</span></span>')
        b.append("</div></div>")
    if not tr["by_season"]:
        b.append('<p class="v2-p">No honours yet.</p>')
    b.append("</section>")
    rh = tr["records"]
    r = ['<section class="lh-card">', _sec("Records he holds", "#1 in the record book")]
    for x in rh["rows"]:
        r.append(f'<div class="mc-li"><span><b>{clean(x["label"])}</b><span class="lh-sub">{clean(x["ctx"])}</span></span>'
                 f'<span class="mc-v">{clean(x["v"])}</span></div>')
    if not rh["rows"]:
        r.append('<p class="v2-p">No #1 in the record book.</p>')
    r.append(f'<span class="lh-sub">{clean(rh["more"])}. {clean(rh["note"])}</span></section>')
    mo = tr["money"]
    m = ['<section class="lh-card">', _sec("Money", "both pots, finished seasons"),
         f'<div class="mc-k3"><div class="mc-k"><span class="lh-label">Career net</span><b>{clean(mo["total"])}</b>'
         f'<small>both pots</small></div><div class="mc-k"><span class="lh-label">Regular season</span>'
         f'<b>{clean(mo["reg"])}</b><small>the League Championship pot</small></div><div class="mc-k">'
         f'<span class="lh-label">Playoffs</span><b>{clean(mo["po"])}</b><small>the playoff pot</small></div></div>']
    for x in mo["rows"]:
        m.append(f'<div class="mc-li"><span><b>{clean(x["s"])}</b><span class="lh-sub">{clean(x["reg"])}</span>'
                 f'<span class="lh-sub">{clean(x["po"])}</span></span><span class="mc-v">{clean(x["net"])}</span></div>')
    m.append(f'<span class="lh-sub">{clean(mo["note"])}</span></section>')
    return ('<div class="v2-cols"><div class="v2-col">' + "".join(a) + "".join(r) + "".join(m)
            + '</div><div class="v2-col">' + "".join(b) + "</div></div>")


def card_screen(c: dict, teams: dict, age: str, back_icon: str, chart_fn, tip_attrs, css: str) -> str:
    """One manager's screen (#/manager/<name>): the top bar, then (lazy when
    published) the card: its CSS, the hero, the tabs and their panes."""
    cls = f'lh-t-{c["team"]["slot"]}'
    cid = f'mc-{c["m"]}'
    o = [f'<section class="v2-screen" data-route="{clean(c["route"])}" data-detail="1" hidden>',
         f'<div class="v2-topbar"><button type="button" class="lh-back" data-back="#/league/history/alltime">'
         f'{back_icon}Back</button><span class="lh-meta">Updated <span class="v2-age">{clean(age)}</span></span></div>',
         f'<style>{css}</style><div class="v2-stack mc {cls}">', _hero(c, cls),
         '<div class="lh-seg" role="tablist" data-seg="mgr">'
         + "".join(f'<button type="button" role="tab" data-pane="{t["k"]}" aria-selected="{"true" if i == 0 else "false"}">'
                   f'{clean(t["t"])}</button>' for i, t in enumerate(c["tabs"])) + "</div>",
         f'<div class="v2-pane" data-pane-of="overview">{_overview(c, cid, chart_fn)}</div>',
         f'<div class="v2-pane" data-pane-of="career" hidden>{_career(c, cid, chart_fn)}</div>',
         f'<div class="v2-pane" data-pane-of="rivals" hidden>{_rivals(c, cid, teams)}</div>',
         f'<div class="v2-pane" data-pane-of="players" hidden>{_players(c)}</div>',
         f'<div class="v2-pane" data-pane-of="trophies" hidden>{_trophies(c, tip_attrs)}</div>',
         "</div></section>"]
    return "".join(o)


def screens(vm: dict, back_icon: str, chart_fn, tip_attrs, lazy) -> str:
    """Every manager's screen (vm["managers"]: the view's), each through
    page._lazy (published: a lazy part)."""
    mg = vm.get("managers") or {}
    if not mg.get("cards"):
        return ""
    from . import tokens
    css = tokens.fill(CSS)
    teams = {m: c["team"] for m, c in mg["cards"].items()}
    return "".join(lazy(card_screen(mg["cards"][m], teams, vm["age"], back_icon, chart_fn, tip_attrs, css), vm)
                   for m in mg["order"])


