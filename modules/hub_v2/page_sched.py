"""
hub_v2/page_sched.py -- THE RENDERER for Team > Schedule (5d2 s.1, the mock Nick
approved 11-21 with his changes) and Matchups > Next week (s.2). page.py's
rules carry over: every printed value is an engine string through clean();
no arithmetic; no hex and no px in the CSS; every header opens its
definition (infotips.COLUMNS "sched", "sgrid", "splay").

    schedule_pane(sp, team)   the team page's Schedule pane: the three-week
                              table, the week chips (opening on the week a
                              pickup can still change), each week's tiles,
                              day-by-day strip (tap a day), "Where pickups
                              would help" (that week only), the players by
                              day, and the playoff and Cup weeks
    next_week(nw, teams)      Matchups > Next week (between This week and
                              Last week)
    next_page(card, nw, ...)  a next-week matchup's preview: both teams' day
                              strips side by side
"""

from __future__ import annotations

from .text import clean, colh, colh_btn

CSS = """
.v2-sov{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.v2-sov th{font-size:var(--type-meta-size);color:var(--ink-3);font-weight:700;text-align:right;padding:var(--space-4) var(--space-2);border-bottom:var(--hairline) solid var(--line)}
.v2-sov th:first-child,.v2-sov td:first-child{text-align:left}
.v2-sov td{padding:var(--space-8) var(--space-2);border-bottom:var(--hairline) solid var(--line-soft);text-align:right;font-weight:700;vertical-align:top}
.v2-sov td .lh-sub{display:block;font-weight:500}
.v2-sov .v2-savg{white-space:nowrap}
.v2-sbig{font-size:var(--type-display-row-size);font-weight:800}
.v2-sup{color:var(--up)} .v2-sdown{color:var(--down)}
.v2-stiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-8)}
.v2-stile{background:var(--surface-subtle);border-radius:var(--radius-6);padding:var(--space-8) var(--space-10);min-width:0}
.v2-stile b{display:block;font-size:var(--type-display-row-size);font-weight:800;color:var(--ink);overflow-wrap:anywhere}
.v2-stile span{font-size:var(--type-meta-size);color:var(--ink-3);font-weight:600}
.v2-stile em{display:block;font-style:normal;font-size:var(--type-meta-size);color:var(--ink-2)}
.v2-strip{display:grid;gap:var(--space-2);align-items:end;grid-template-columns:repeat(var(--n),minmax(0,1fr))}
button.v2-sday{all:unset;box-sizing:border-box;display:flex;flex-direction:column;align-items:stretch;cursor:pointer;min-height:var(--tap-min);min-width:0}
.v2-sday[aria-pressed="true"] .v2-slab{background:var(--dark);color:var(--ink-on-dark);border-radius:var(--radius-3)}
.v2-sstack{display:flex;flex-direction:column-reverse;gap:var(--space-2);height:calc(var(--space-6) * 10 + var(--space-2) * 9)}
.v2-sc{height:var(--space-6);border-radius:var(--radius-3);flex:none}
.v2-sc-s{background:var(--team,var(--ink-2))}
.v2-sc-q{background:var(--team-tint,var(--track));box-shadow:inset 0 0 0 var(--hairline) var(--team,var(--ink-2))}
.v2-sc-e{box-shadow:inset 0 0 0 var(--hairline) var(--down);background:var(--status-out-tint)}
.v2-sc-i{background:var(--axis-strong)}
.v2-sline{border-top:var(--space-2) solid var(--ink);margin:var(--space-2) 0}
.v2-sover{display:flex;flex-direction:column-reverse;gap:var(--space-2);min-height:calc(var(--space-6) * 3 + var(--space-2) * 2)}
.v2-slab{font-size:var(--type-small-size);font-weight:700;color:var(--ink-2);text-align:center;line-height:1.2;padding:var(--space-2) 0}
.v2-slab small{display:block;font-size:var(--type-small-size);font-weight:600;color:var(--ink-3)}
.v2-sn{font-size:var(--type-small-size);font-weight:800;text-align:center;color:var(--ink-3);min-height:var(--space-14)}
.v2-sn-e{color:var(--down)} .v2-sn-i{color:var(--ink-2)}
.v2-soff{font-size:var(--type-small-size);color:var(--ink-3);text-align:center;font-weight:700;overflow-wrap:anywhere}
.v2-smark{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);text-align:center;min-height:var(--space-14)}
.v2-slegend{display:flex;flex-wrap:wrap;gap:var(--space-12);font-size:var(--type-meta-size);color:var(--ink-2)}
.v2-slegend i{display:inline-block;width:var(--space-12);height:var(--space-8);border-radius:var(--radius-3);margin-right:var(--space-4);vertical-align:middle}
.v2-sdd{background:var(--surface-subtle);border-radius:var(--radius-6);padding:var(--space-10);font-size:var(--type-body-size)}
.v2-sdd h4{margin:0 0 var(--space-4);font-size:var(--type-body-size)}
.v2-sdd p{margin:var(--space-2) 0;color:var(--ink-2)}
.v2-sgrid{border-collapse:separate;border-spacing:0;font-variant-numeric:tabular-nums}
.v2-sgrid th{font-size:var(--type-small-size);color:var(--ink-3);font-weight:700;padding:0;text-align:center;min-width:var(--tap-min)}
.v2-sgrid th .v2-colh{min-width:var(--tap-min)}
.v2-sgrid th small{display:block;font-size:var(--type-small-size);font-weight:600}
.v2-sgrid th.v2-sh-light{color:var(--status-q)} .v2-sgrid th.v2-sh-over{color:var(--ink-strong)}
.v2-sgrid th.v2-sh-today{box-shadow:inset 0 calc(-1 * var(--space-2)) 0 var(--ink)}
.v2-sgrid td{text-align:center;padding:0;height:var(--tap-min);border-bottom:var(--hairline) solid var(--line-soft);font-size:var(--type-meta-size);min-width:var(--tap-min);position:relative}
.v2-sgrid .v2-sticky{position:sticky;left:0;background:var(--surface);text-align:left;min-width:calc(var(--tap-min) * 3);max-width:calc(var(--tap-min) * 3);padding-right:var(--space-6);z-index:1}
.v2-sgrid td.v2-sticky .lh-name,.v2-sgrid td.v2-sticky b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.v2-sgrid td.v2-sticky .lh-sub{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.v2-sgrid tr.v2-sdim td{opacity:.55}
.v2-sgrid tr.v2-sdim td.v2-sticky{opacity:1}
.v2-sgrid tr.v2-sdim td.v2-sticky .lh-sub{color:var(--down)}
.v2-sgrid td.v2-stot{font-weight:800}
.v2-sgrid td.v2-sspan{font-size:var(--type-meta-size);color:var(--ink-3);text-align:left;padding-left:var(--space-6);font-weight:600}
.v2-sgrid td.v2-sest{box-shadow:inset 0 0 0 var(--hairline) var(--axis-strong)}
.v2-sdot{display:inline-block;width:var(--space-12);height:var(--space-12);border-radius:var(--radius-pill);vertical-align:middle}
.v2-sd-s{background:var(--team,var(--ink-2))}
.v2-sd-q{background:linear-gradient(90deg,var(--team,var(--ink-2)) 50%,var(--team-tint,var(--track)) 50%);box-shadow:inset 0 0 0 var(--hairline) var(--team,var(--ink-2))}
.v2-sd-i{box-shadow:inset 0 0 0 var(--space-2) var(--axis-strong)}
.v2-sx{color:var(--down);font-weight:800;font-size:var(--type-small-size)}
.v2-sb2b{position:absolute;left:0;top:50%;width:var(--space-14);margin-left:calc(-1 * var(--space-6));border-top:var(--space-2) solid var(--axis-strong)}
.v2-spk{display:flex;justify-content:space-between;gap:var(--space-8);padding:var(--space-8) 0;border-bottom:var(--hairline) solid var(--line-soft)}
.v2-spk .lh-sub{display:block}
.v2-snum{text-align:right;white-space:nowrap}
.v2-snum b{font-size:var(--type-display-row-size);font-weight:800}
.v2-swpane[hidden]{display:none}
.v2-nwcard{display:flex;flex-direction:column;gap:var(--space-8)}
.v2-nwside{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:var(--space-8);align-items:center}
.v2-nwnums{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-6)}
.v2-nwlook{background:var(--surface-subtle);border-radius:var(--radius-6);padding:var(--space-8) var(--space-10)}
.v2-nwtag{font-size:var(--type-label-size);font-weight:800;letter-spacing:var(--type-label-ls);text-transform:uppercase;color:var(--ink-3)}
.v2-nwboth{display:grid;grid-template-columns:minmax(0,1fr);gap:var(--space-16)}
@media (min-width:{{bp-mid}}){.v2-nwboth{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
"""

TAP_CLASSES = ("v2-sday",)

JS = r"""
// 5d2 s.1: Team > Schedule -- the week chips and a day's tap (delegated: the
// team page is a lazy screen)
document.addEventListener('click',function(e){
  var c=e.target.closest?e.target.closest('[data-swk]'):null;
  if(c){var box=c.closest('[data-sched]');
    var bs=box.querySelectorAll('[data-swk]');for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i]===c));}
    var ps=box.querySelectorAll('[data-swpane]');for(var j=0;j<ps.length;j++){ps[j].hidden=ps[j].getAttribute('data-swpane')!==c.getAttribute('data-swk');}
    return;}
  var d=e.target.closest?e.target.closest('.v2-sday'):null;
  if(d){var pane=d.closest('[data-strip]');var on=d.getAttribute('aria-pressed')!=='true';
    var ds=pane.querySelectorAll('.v2-sday');for(var k=0;k<ds.length;k++){ds[k].setAttribute('aria-pressed','false');}
    var dd=pane.querySelectorAll('[data-sdd]');for(var q=0;q<dd.length;q++){dd[q].hidden=true;}
    if(on){d.setAttribute('aria-pressed','true');var x=pane.querySelector('[data-sdd="'+d.getAttribute('data-sday')+'"]');if(x){x.hidden=false;}}
    return;}
});
"""


def _strip(days: list, key: str, tcls: str = "") -> str:
    o = [f'<div class="{tcls}" data-strip="{clean(key)}"><div class="v2-strip" style="--n:{len(days)}">']
    for x in days:
        cells = ("".join('<span class="v2-sc v2-sc-s"></span>' for _ in range(x["s"]))
                 + "".join('<span class="v2-sc v2-sc-q"></span>' for _ in range(x["q"]))
                 + "".join('<span class="v2-sc v2-sc-e"></span>' for _ in range(x["e"])))
        if x["off"]:
            cells = '<span class="v2-soff">no NBA games</span>'
        over = "".join('<span class="v2-sc v2-sc-i"></span>' for _ in range(min(x["i"], 3)))
        lab_cls = {"i": " v2-sn-i", "e": " v2-sn-e"}.get(x["lab_k"], "")
        mark = ("~" if x["est"] else "") + ("\u2020" if x["nba"] else "")
        o.append(f'<button type="button" class="v2-sday" data-sday="{clean(x["iso"])}" aria-pressed="false" '
                 f'aria-label="{clean(x["aria"])}"><span class="v2-sn{lab_cls}">{clean(x["lab"])}</span>'
                 f'<span class="v2-sover">{over}</span><span class="v2-sline"></span>'
                 f'<span class="v2-sstack">{cells}</span>'
                 f'<span class="v2-slab">{clean(x["dow"])}<small>{clean(x["d"])}</small></span>'
                 f'<span class="v2-smark">{clean(mark)}</span></button>')
    o.append("</div>")
    for x in days:
        o.append(f'<div class="v2-sdd" data-sdd="{clean(x["iso"])}" hidden><h4>{clean(x["dd"]["head"])}</h4>'
                 + "".join(f'<p><b>{clean(a)}{" (" + clean(n) + ")" if n else ""}:</b> {clean(t)}</p>'
                           for a, n, t in x["dd"]["lines"]) + "</div>")
    o.append("</div>")
    return "".join(o)


LEGEND = ('<div class="v2-slegend"><span><i class="v2-sc-s"></i>Starts</span>'
          '<span><i class="v2-sc-q"></i>Starts if the Q plays</span>'
          '<span><i class="v2-sc-e"></i>Empty slot</span>'
          '<span><i class="v2-sc-i"></i>Idle (over the line of 10)</span>'
          '<span>~ estimated day &middot; &dagger; out tonight (NBA report)</span></div>')


def _grid(p: dict, pl_link) -> str:
    o = ['<div class="v2-scroll"><table class="v2-sgrid"><thead><tr>'
         f'<th class="v2-sticky">{colh_btn("sgrid", "player", "Player")}</th>']
    for h in p["heads"]:
        cls = " ".join(c for c in (("v2-sh-light" if h["kind"] == "light" else "v2-sh-over" if h["kind"] == "over"
                                    else ""), "v2-sh-today" if h["today"] else "") if c)
        mk = ("~" if h["est"] else "") + ("\u2020" if h["nba"] else "")
        o.append(f'<th class="{cls}">' + colh_btn("sgrid", "day", f'{clean(h["dow"])}<small>{clean(h["d"])}'
                                                                f'{clean(mk)}</small>') + "</th>")
    o.append(f'<th>{colh_btn("sgrid", "g", "G")}</th><th>{colh_btn("sgrid", "s", "S")}</th></tr></thead><tbody>')
    il_started = False
    n_days = len(p["heads"])
    for r in p["rows"]:
        if r["il"] and not il_started:
            il_started = True
            o.append(f'<tr><td class="v2-sticky"><b>IL slots</b></td><td class="v2-sspan" colspan="{n_days + 2}">'
                     "don't score while there</td></tr>")
        cells = []
        for c in r["cells"]:
            k = c["c"]
            inner = {"s": '<span class="v2-sdot v2-sd-s" aria-label="starts"></span>',
                     "q": '<span class="v2-sdot v2-sd-q" aria-label="starts if he plays"></span>',
                     "i": '<span class="v2-sdot v2-sd-i" aria-label="idle"></span>',
                     "out": '<span class="v2-sx">OUT</span>', "nba": '<span class="v2-sx">OUT&dagger;</span>',
                     "il": '<span class="v2-sx">IL</span>', "x": "", "": ""}[k]
            b2b = '<span class="v2-sb2b" aria-hidden="true"></span>' if c.get("b2b") else ""
            cells.append(f'<td{" class=" + chr(34) + "v2-sest" + chr(34) if c.get("est") else ""}>{b2b}{inner}</td>')
        o.append(f'<tr{" class=" + chr(34) + "v2-sdim" + chr(34) if r["dim"] else ""}>'
                 f'<td class="v2-sticky">{pl_link(r["name"], r["card"])}<span class="lh-sub">{clean(r["sub"])}</span></td>'
                 + "".join(cells) + f'<td class="v2-stot">{clean(r["g"])}</td><td class="v2-stot">{clean(r["s"])}</td></tr>')
    o.append("</tbody></table></div>")
    o.append('<div class="lh-table-note"><span class="v2-sdot v2-sd-s"></span> starts &middot; '
             '<span class="v2-sdot v2-sd-q"></span> starts if the Q plays &middot; <span class="v2-sdot v2-sd-i"></span> '
             'idle: has a game and sits &middot; OUT: out (tag, injury entry; &dagger; the NBA report tonight) &middot; '
             'IL: in an IL slot &middot; a bar between two days: a back-to-back &middot; a boxed cell or ~: an '
             'estimated game the NBA hasn\'t scheduled yet. A gold day: a light day (4 or fewer players with a game); a '
             'dark day: an overflow day (more than 10). Tap a header for its definition.</div>')
    return "".join(o)


def _pickups(pk: dict, pl_link) -> str:
    o = ['<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Where pickups would help</h2>'
         f'<span class="lh-meta">{clean(pk["head"])}</span></div>',
         f'<p class="v2-p">{clean(pk["lead"])}</p>',
         f'<p class="v2-p">Empty slots: <b>{clean(pk["total"])}</b>, on {clean(pk["ndays"])} days:</p>',
         '<div class="v2-fchips">' + "".join(f'<span class="lh-chip lh-chip--fa">{clean(c)}</span>' for c in pk["chips"])
         + "</div>",
         f'<p class="v2-p">{clean(pk["adds"])}. {clean(pk["window"])}</p>',
         '<h3 class="lh-eyebrow">Free agents with games on those days</h3>']
    for f in pk["fas"]:
        o.append(f'<div class="v2-spk"><span class="v2-minw">{pl_link(f["name"], f["card"])}'
                 f'<span class="lh-sub">{clean(f["meta"])}</span><span class="lh-sub">{clean(f["g"])} games that week</span>'
                 f'</span><span class="v2-snum"><b>{clean(f["n"])}</b><span class="lh-sub">on your empty-slot days</span>'
                 "</span></div>")
    if pk["none"]:
        o.append(f'<p class="v2-p">{clean(pk["none"])}</p>')
    o.append(f'<a class="v2-btn lh-link" href="{clean(pk["href"])}">Market: free agents who play those days &rsaquo;</a>'
             '<span class="lh-sub">Games on days you have an empty slot. Not advice: what a pickup is worth to you, '
             'with the drop it needs, is Market &rsaquo; Advice.</span></section>')
    return "".join(o)


def _playoffs(po: dict, pl_link) -> str:
    o = ['<section class="lh-card lh-card--flush v2-gap8"><div class="lh-sechead v2-pad"><h2 class="lh-eyebrow">'
         'The playoff and Cup weeks</h2><span class="lh-meta">games he will play</span></div>'
         '<div class="v2-scroll"><table class="lh-table"><thead><tr>'
         f'<th class="v2-sticky">{colh_btn("splay", "player", "Player")}</th>'
         + "".join(f'<th>{colh_btn("splay", c["key"], clean(c["label"]) + "<small> " + clean(c["sub"]) + "</small>")}</th>'
                   for c in po["cols"]) + "</tr></thead><tbody>"]
    for r in po["rows"]:
        o.append(f'<tr{" class=" + chr(34) + "lh-inactive" + chr(34) if r["il"] else ""}><td class="v2-sticky">'
                 f'{pl_link(r["name"], r["card"])}{"<span class=" + chr(34) + "lh-sub" + chr(34) + ">IL slot</span>" if r["il"] else ""}</td>'
                 + "".join(f"<td>{clean(c)}</td>" for c in r["cells"]) + "</tr>")
    o.append('<tr><td class="v2-sticky"><b>Team startable</b></td>' + "".join(f"<td><b>{clean(c)}</b></td>" for c in po["team"])
             + f'</tr></tbody></table></div><div class="lh-table-note">{clean(po["note"])}</div></section>')
    return "".join(o)


def schedule_pane(sp: dict, t: dict, pl_link) -> str:
    """The Schedule pane of a team page (vm team page "sched2")."""
    tm = sp["team"]
    o = [f'<div class="{t["cls"]}" data-sched="1"><section class="lh-card v2-gap8"><div class="lh-sechead">'
         '<h2 class="lh-eyebrow">Startable games</h2><span class="lh-meta">games that fit your daily 10</span></div>'
         f'<div class="v2-scroll"><table class="v2-sov"><thead><tr><th>{colh_btn("sched", "week", "Week")}</th>'
         f'<th>{colh_btn("sched", "starts", "You")}</th><th>{colh_btn("sched", "avg", "League avg")}</th>'
         f'<th>{colh_btn("sched", "rank", "Rank")}</th><th>{colh_btn("sched", "opp", "Opponent")}</th></tr></thead><tbody>']
    for r in tm["ov"]:
        op = r["opp"]
        oc = (f'{clean(op["text"])}<span class="lh-sub">{clean(r["ostarts"])}'
              f'{" &middot; " if r["edge"] else ""}<span class="{ {"up": "v2-sup", "down": "v2-sdown"}.get(r["edge_dir"], "")}">'
              f'{clean(r["edge"])}</span></span>' if op["m"] else f'<span class="lh-sub">{clean(op["text"])}</span>')
        o.append(f'<tr><td><b>{clean(r["label"])}</b><span class="lh-sub">{clean(r["sub"])}</span></td>'
                 f'<td><span class="v2-sbig lh-team-text">{clean(r["starts"])}</span>'
                 f'<span class="lh-sub">of {clean(r["games"])} games</span></td>'
                 f'<td class="v2-savg">{clean(r["avg"])}</td><td>{clean(r["rank"])}</td><td>{oc}</td></tr>')
    o.append(f'</tbody></table></div><span class="lh-sub">{clean(sp["note"])}</span></section>')
    o.append('<div class="v2-fchips" role="tablist" aria-label="Week">')
    for i, w in enumerate(sp["weeks"]):
        o.append(f'<button type="button" class="v2-fchip" data-swk="{w["w"]}" '
                 f'aria-pressed="{"true" if i == sp["open"] else "false"}">{clean(w["chip"])}</button>')
    o.append("</div>")
    for i, (w, p) in enumerate(zip(sp["weeks"], tm["panes"])):
        op = p["opp"]
        o.append(f'<div class="v2-swpane" data-swpane="{w["w"]}"{"" if i == sp["open"] else " hidden"}>'
                 '<section class="lh-card v2-gap8"><div class="lh-sechead">'
                 f'<h2 class="lh-eyebrow">{clean(p["label"])}</h2><span class="lh-meta">{clean(p["sub"])} &middot; '
                 f'{"vs " + clean(op["text"]) if op["m"] else clean(op["text"])}</span></div><div class="v2-stiles">'
                 + "".join(f'<div class="v2-stile"><span>{clean(x["label"])}</span><b>{clean(x["v"])}</b>'
                           f'<em>{clean(x["ctx"])}</em></div>' for x in p["tiles"])
                 + '</div><h3 class="lh-eyebrow">Day by day</h3>'
                 + _strip(p["strip"], f'{t["slot"]}-{w["w"]}') + LEGEND
                 + '<span class="lh-sub">Tap a day for who starts, who sits and who is out.</span></section>')
        if tm["pickups"] is not None and tm["pickups"]["w"] == w["w"]:
            o.append(_pickups(tm["pickups"], pl_link))
        o.append('<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Players by day</h2>'
                 f'<span class="lh-meta">{clean(p["label"])}</span></div>{_grid(p, pl_link)}</section></div>')
    if tm["playoffs"] is not None:
        o.append(_playoffs(tm["playoffs"], pl_link))
    o.append("</div>")
    return "".join(o)


# =============================================================================
# Matchups > Next week
# =============================================================================

def next_week(nw: dict, teams: dict, mono) -> str:
    o = ['<section class="v2-sec" data-section="next"><div class="lh-sechead">'
         f'<h2 class="lh-eyebrow">{clean(nw["label"])}</h2><span class="lh-meta lh-meta--canvas">{clean(nw["sub"])}</span></div>']
    if nw["unknown"] is not None:
        u = nw["unknown"]
        o.append(f'<div class="lh-card v2-gap8"><p class="v2-p"><b>{clean(u["text"])}</b></p>')
        if u["poss"]:
            ps = u["poss"]
            o.append(f'<p class="v2-p">{clean(ps["text"])}</p><table class="lh-table"><thead><tr>'
                     f'<th>{colh_btn("nextwk", "team", "Team")}</th>'
                     + "".join(f'<th>{colh_btn("nextwk", "seed", clean(c))}</th>' for c in ps["cols"])
                     + "</tr></thead><tbody>"
                     + "".join(f'<tr><td>{clean(r["team"])}</td>' + "".join(f"<td>{clean(c)}</td>" for c in r["cells"])
                               + "</tr>" for r in ps["rows"]) + "</tbody></table>")
        o.append(f'<span class="lh-sub">{clean(nw["note"])}</span></div></section>')
        return "".join(o)
    for c in nw["cards"]:
        o.append(f'<a class="lh-card v2-nwcard" href="#/{clean(c["route"])}" data-next="{clean(c["id"])}">'
                 f'<span class="v2-nwtag">{clean(nw["early"])}</span>')
        for s in (c["a"], c["b"]):
            t = teams[s["m"]]
            o.append(f'<span class="v2-nwside {t["cls"]}">{mono(t)}<span class="v2-minw"><span class="lh-mrow__name">'
                     f'{clean(s["team"])}</span><span class="lh-sub">{clean(s["m"])} &middot; {clean(s["record"])}</span></span>'
                     f'<span class="v2-snum"><b class="lh-team-text">{clean(s["starts"])}</b>'
                     '<span class="lh-sub">startable</span></span></span>')
            if s["injuries"]:
                o.append(f'<span class="lh-sub">Out or IL: {clean("; ".join(s["injuries"]))}</span>')
        lk = c["look"]
        if lk:
            o.append(f'<span class="v2-nwlook"><b>{clean(lk["margin"])}</b> &middot; {clean(c["a"]["team"])} '
                     f'{clean(lk["win_a"])}, {clean(c["b"]["team"])} {clean(lk["win_b"])}'
                     f'<span class="lh-sub">{clean(lk["src"])}</span></span>')
        else:
            o.append('<span class="lh-sub">No early look on this run: the title-odds simulation has not priced this '
                     'week.</span>')
        o.append('<span class="lh-divider v2-mfoot"><span class="v2-note">Day by day, both teams</span>'
                 '<span class="v2-details">Preview &rsaquo;</span></span></a>')
    o.append(f'<span class="lh-sub">{clean(nw["note"])}</span></section>')
    return "".join(o)


def next_page(c: dict, nw: dict, strips: dict, teams: dict, mono, topbar) -> str:
    """A next-week matchup's preview: both teams' day strips side by side."""
    o = [f'<section class="v2-screen" data-route="{clean(c["route"])}" data-detail="1" hidden>', topbar,
         '<div class="v2-stack"><section class="lh-card v2-gap8"><div class="lh-sechead">'
         f'<h2 class="lh-eyebrow">{clean(nw["label"])}</h2><span class="lh-meta">{clean(nw["sub"])}</span></div>'
         f'<span class="v2-nwtag">{clean(nw["early"])}</span>']
    lk = c["look"]
    if lk:
        o.append(f'<p class="v2-p"><b>{clean(lk["margin"])}</b> &middot; {clean(c["a"]["team"])} {clean(lk["win_a"])}, '
                 f'{clean(c["b"]["team"])} {clean(lk["win_b"])}</p><span class="lh-sub">{clean(lk["src"])}</span>')
    o.append('</section><div class="v2-nwboth">')
    for s in (c["a"], c["b"]):
        t = teams[s["m"]]
        o.append(f'<section class="lh-card v2-gap8 {t["cls"]}"><div class="v2-nwside">{mono(t)}<span class="v2-minw">'
                 f'<a class="lh-mrow__name v2-tap" href="{t["href"]}">{clean(s["team"])}</a>'
                 f'<span class="lh-sub">{clean(s["m"])} &middot; {clean(s["record"])}</span></span></div>'
                 '<div class="v2-nwnums">'
                 f'<div class="v2-stile"><span>Startable</span><b>{clean(s["starts"])}</b></div>'
                 f'<div class="v2-stile"><span>Light days</span><b>{clean(s["light"])}</b></div>'
                 f'<div class="v2-stile"><span>Overflow days</span><b>{clean(s["over"])}</b></div></div>'
                 + (_strip(strips[s["m"]], f'n-{s["m"]}') if strips.get(s["m"]) else "")
                 + (f'<span class="lh-sub">Out or IL: {clean("; ".join(s["injuries"]))}</span>' if s["injuries"] else "")
                 + "</section>")
    o.append(f'</div>{LEGEND}<span class="lh-sub">{clean(nw["note"])}</span></div></section>')
    return "".join(o)
