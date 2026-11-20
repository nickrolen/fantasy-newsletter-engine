"""
hub_v2/page_market.py -- the new hub's Market tab (4c3): Available . Stash .
Advice . Block . Moves, printed from the view model (view.market), which
carries payload strings only (modules/hub_v2/market.py made them).

THE PAGE DISPLAYS. Every number is a payload string through clean(). The
script reorders the free-agent rows by the payload's integer orders, hides
rows a filter leaves out, opens and closes an advice row, and opens the one
tooltip (4c2) on a game cell. It computes nothing.

THE ADVICE VIEW is Advice.html v5 as approved (Nick, 11-18), built with the
mockup's own classes (adv-*; the Advice component README): every row starts
closed; a tap opens the reason, the tiles and "Also wanted by". The
activation row is shaded status-il-tint with the status-il bar on its left,
a filled circle-arrow in place of the number, and "Activate from IL . no add".

CSS rules: tokens only (var(--...)); no hex colour, no px literal (the page's
rule for LAYOUT_CSS holds here too).
"""

from __future__ import annotations

import json

from ..live_lines_page import clean

TAP_CLASSES = ("adv-row", "adv-bk", "v2-mkcell", "v2-mvchip")
DOT = " \u00b7 "

CSS = """
.v2-mk-cells{display:flex;justify-content:flex-end}
.v2-mk-s0{background:var(--surface-sunken);color:var(--ink-3)}
.v2-mkcell{all:unset;box-sizing:border-box;cursor:pointer;width:var(--tap-min);min-height:var(--tap-min);display:inline-flex;align-items:center;justify-content:center}
.v2-mkbox{min-width:calc(var(--space-24) + var(--space-2));min-height:calc(var(--space-20) + var(--space-2));border-radius:var(--radius-6);display:inline-flex;align-items:center;justify-content:center;font-size:var(--type-small-size);font-weight:800}
.v2-mkcell[aria-expanded="true"]>.v2-mkbox{box-shadow:0 0 0 var(--hairline) var(--ink)}
.v2-mk-fa td{vertical-align:middle}
.v2-mk-fa .lh-sub{display:block}
.v2-mk-fa th:last-child,.v2-mk-fa td:last-child{text-align:right}
.v2-mk-list{display:flex;flex-direction:column}
.v2-mk-item{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-6) 0}
.v2-mk-item:first-child{border-top:0}
.v2-mk-right{display:flex;flex-direction:column;align-items:flex-end;gap:var(--space-2);text-align:right}
.v2-mv{display:grid;grid-template-columns:var(--space-24) minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-6) 0}
.v2-mv:first-child{border-top:0}
.v2-mv-mark{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:700;text-align:center}
.v2-mv-body{display:flex;flex-direction:column;gap:var(--space-2);min-width:0}
.v2-mv-part{font-size:var(--type-body-size);overflow-wrap:anywhere}
.v2-mv-part b{font-size:var(--type-row-size)}
.v2-mv-add{color:var(--up)}
.v2-mv-wk{display:flex;flex-direction:column;gap:var(--space-2);padding:var(--space-8) 0 var(--space-4);border-top:var(--hairline) solid var(--line)}
.v2-mv-wk:first-child{border-top:0}
.v2-mv-used{display:flex;flex-wrap:wrap;gap:var(--space-2) var(--space-10);font-size:var(--type-meta-size);font-weight:600;color:var(--ink-2)}
.v2-mv-over{color:var(--down);font-weight:800}
.v2-mv-older{padding-top:var(--space-8)}
.v2-mv-drop{color:var(--down)}
.v2-mv-il{color:var(--status-il)}
.v2-mv-trade{color:var(--ink-2)}
.v2-mvchip{min-height:var(--tap-min)}
.v2-mk-block{display:flex;flex-direction:column;gap:var(--space-6);padding-top:var(--space-10)}
.v2-mk-block:first-of-type{padding-top:0}
.v2-mk-tbl{font-size:var(--type-body-size);color:var(--ink-2);overflow-wrap:anywhere}
.v2-mk-tbl b{color:var(--ink);font-weight:800}
.v2-mk-sub{font-size:var(--type-small-size);color:var(--ink-3)}
.adv-cards{display:flex;flex-wrap:wrap;gap:var(--space-6);align-items:center;font-size:var(--type-small-size);color:var(--ink-2)}
.adv{padding:0;gap:0;overflow:hidden}
.adv-head{display:grid;grid-template-columns:auto minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;padding:var(--space-12) var(--space-14) var(--space-8)}
.adv-team{font-size:var(--type-heading-size);font-weight:800;color:var(--ink-strong);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-decoration:none}
.adv-adds{font-size:var(--type-small-size);font-weight:800;color:var(--ink-2);background:var(--surface-sunken);border-radius:var(--radius-pill);padding:var(--space-4) var(--space-8);white-space:nowrap}
.adv-hrow{display:grid;grid-template-columns:var(--adv-dot) minmax(0,1fr) var(--adv-col) var(--space-10);column-gap:var(--space-10);align-items:end;padding:0 var(--space-14) var(--space-6)}
.adv-colh{font-size:var(--type-label-size);font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3);text-align:right}
.adv-row{all:unset;box-sizing:border-box;cursor:pointer;width:100%;display:grid;grid-template-columns:var(--adv-dot) minmax(0,1fr) var(--adv-col) var(--space-10);column-gap:var(--space-10);align-items:center;min-height:var(--row-min);padding:var(--space-10) var(--space-14);border-top:var(--hairline) solid var(--line-soft)}
.adv-row:focus-visible,.adv-bk:focus-visible{outline:var(--hairline) solid var(--accent);outline-offset:calc(-1 * var(--space-2))}
.adv-n{width:var(--adv-dot);height:var(--adv-dot);box-sizing:border-box;border-radius:50%;border:var(--hairline) solid var(--ink-3);color:var(--ink-2);font-size:var(--type-small-size);font-weight:800;display:inline-flex;align-items:center;justify-content:center}
.adv-mv{display:flex;flex-direction:column;gap:var(--space-2);min-width:0}
.adv-add,.adv-drop{display:flex;align-items:baseline;gap:var(--space-6);min-width:0;white-space:nowrap}
.adv-add b{font-size:var(--type-heading-size);font-weight:700;color:var(--ink);overflow:hidden;text-overflow:ellipsis}
.adv-drop span:last-child{font-size:var(--type-body-size);color:var(--ink-2);overflow:hidden;text-overflow:ellipsis}
.adv-sign{font-weight:800;width:var(--space-10);flex:none;text-align:center}
.adv-sign-il{width:auto;font-size:var(--type-label-size);color:var(--status-il)}
.adv-up{color:var(--up)}
.adv-down{color:var(--down)}
.adv-chev{color:var(--ink-3);font-size:var(--type-meta-size);transition:transform .15s}
.adv-row[aria-expanded="true"] .adv-chev{transform:rotate(90deg)}
.adv-then{padding:var(--space-6) var(--space-14) 0 calc(var(--space-14) + var(--adv-dot) + var(--space-10));margin:0 0 calc(-1 * var(--space-8));font-size:var(--type-label-size);font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-3);position:relative;z-index:1}
.adv-det{background:var(--surface-subtle);padding:var(--space-10) var(--space-14) var(--space-12) calc(var(--space-14) + var(--adv-dot) + var(--space-10));display:flex;flex-direction:column;gap:var(--space-8);border-top:var(--hairline) solid var(--line-soft)}
.adv-why{font-size:var(--type-body-size);line-height:1.45;color:var(--ink)}
.adv-mini{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--space-6)}
.adv-mini .lh-kpi--nested{background:var(--surface);border:var(--hairline) solid var(--line-soft);padding:var(--space-6) var(--space-8)}
.adv-mini .lh-kpi__value{font-size:var(--type-heading-size)}
.adv-tag{display:flex;flex-wrap:wrap;gap:var(--space-6);align-items:center;font-size:var(--type-small-size);color:var(--ink-2)}
.adv-flag{display:inline-flex;align-items:center;font-size:var(--type-label-size);font-weight:800;color:var(--status-q);background:var(--status-q-tint);border-radius:var(--radius-pill);padding:var(--space-2) var(--space-6);white-space:nowrap}
.adv-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:var(--space-8);font-size:var(--type-meta-size);color:var(--ink-2);line-height:1.4;padding:0 var(--space-2)}
.adv-row--il{background:var(--status-il-tint);box-shadow:inset var(--adv-bar) 0 0 var(--status-il)}
.adv-ilic{width:var(--adv-dot);height:var(--adv-dot);border-radius:50%;background:var(--status-il);color:var(--surface);display:inline-flex;align-items:center;justify-content:center;font-size:var(--type-body-size);font-weight:800}
.adv-ilk{font-size:var(--type-label-size);font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--status-il)}
.adv-wkrows{display:grid;grid-template-columns:auto auto;column-gap:var(--space-8);row-gap:var(--space-2);align-items:baseline;justify-items:end}
.adv-wkrows .adv-l{font-size:var(--type-small-size);font-weight:700;color:var(--ink-3);white-space:nowrap}
.adv-v{font-family:var(--font-display);font-size:var(--type-reading-size);font-weight:700;color:var(--up);font-variant-numeric:tabular-nums;line-height:1}
.adv-v.adv-v--down{color:var(--down)}
.adv-v.adv-v--flat{color:var(--ink-2)}
.adv-plan{display:grid;grid-template-columns:var(--adv-dot) minmax(0,1fr) var(--adv-col) var(--space-10);column-gap:var(--space-10);align-items:center;padding:var(--space-10) var(--space-14);background:var(--surface-subtle);border-top:var(--hairline) solid var(--line)}
.adv-plan .lh-label{color:var(--ink-2)}
.adv-plan-l{display:flex;flex-direction:column;gap:var(--hairline)}
.adv-plan .adv-v{color:var(--ink-strong)}
.adv-plan .adv-v.adv-v--down{color:var(--down)}
.adv-bk{all:unset;box-sizing:border-box;cursor:pointer;width:100%;display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--tap-min);padding:var(--space-8) var(--space-14);border-top:var(--hairline) solid var(--line-soft);font-size:var(--type-meta-size);color:var(--ink-3)}
.adv-bk b{color:var(--ink-2);font-weight:700}
.adv-bk[aria-expanded="true"] .adv-chev{transform:rotate(90deg)}
.adv-empty{padding:0 var(--space-14) var(--space-14) calc(var(--space-14) + var(--mono-36) + var(--space-6));font-size:var(--type-body-size);color:var(--ink-3)}
.adv-err{padding:var(--space-12) var(--space-14);font-size:var(--type-body-size);color:var(--ink-2)}
"""

JS = r"""
// 4c3: the Market tab -- the free agents' filters and sort, the moves' team
// chips, the advice rows (closed at first; a tap opens and closes). Nothing
// computed: the orders are the payload's.
var MK={pos:'',h:'',mv:''};
// 5b: Market > Moves' older budget weeks: an encrypted part when published
// (a template in the preview), opened on "Show older weeks"
function mvOlder(btn){
  var box=btn.closest('[data-mvolder-of]');if(!box||box.getAttribute('data-loaded')){return;}
  var put=function(html){box.innerHTML=html;box.setAttribute('data-loaded','1');mvFilter(MK.mv);};
  var tpl=document.getElementById('v2-mk-older');
  if(tpl){put(tpl.innerHTML);return;}
  var ref=box.getAttribute('data-part');
  if(!ref||!window.HUB||!window.HUB.part){return;}
  btn.disabled=true;btn.textContent='Opening\u2026';
  window.HUB.part(JSON.parse(ref)).then(function(p){put(p.html);},function(err){
    if(err&&err.message==='gone'){movedBox();}
    btn.disabled=false;btn.textContent='The older weeks could not be opened. Try again';});
}
function mkFilter(){
  var tb=document.getElementById('mk-fa');if(!tb){return;}
  var trs=tb.querySelectorAll('tbody tr[data-i]'),any=false;
  for(var i=0;i<trs.length;i++){var t=trs[i],ok=true;
    if(MK.pos&&(' '+t.getAttribute('data-pos')+' ').indexOf(' '+MK.pos+' ')<0){ok=false;}
    if(MK.h&&t.getAttribute('data-h')!=='1'){ok=false;}
    t.hidden=!ok;if(ok){any=true;}}
  var n=document.getElementById('mk-fa-none');if(n){n.hidden=any;}
}
function mvFilter(m){
  MK.mv=m;
  var bs=document.querySelectorAll('[data-mvf]');
  for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i].getAttribute('data-mvf')===m));}
  var it=document.querySelectorAll('#mk-moves [data-ms]');
  for(var j=0;j<it.length;j++){it[j].hidden=!!m&&(' '+it[j].getAttribute('data-ms')+' ').indexOf(' '+m+' ')<0;}
}
document.addEventListener('click',function(e){
  var t=e.target.closest('.adv-row[aria-controls],.adv-bk[aria-controls]');
  if(t&&!e.target.closest('[data-card]')&&!e.target.closest('a')){
    var open=t.getAttribute('aria-expanded')==='true';t.setAttribute('aria-expanded',String(!open));
    document.getElementById(t.getAttribute('aria-controls')).hidden=open;return;}
  t=e.target.closest('[data-mkh]');
  if(t){var on=t.getAttribute('aria-pressed')!=='true';t.setAttribute('aria-pressed',String(on));MK.h=on?'1':'';mkFilter();return;}
  t=e.target.closest('[data-mvf]');
  if(t){mvFilter(t.getAttribute('data-mvf'));return;}
  t=e.target.closest('[data-mvolder]');
  if(t){mvOlder(t);return;}
});
document.addEventListener('change',function(e){
  var t=e.target;
  if(t.matches&&t.matches('[data-mkpos]')){MK.pos=t.value;mkFilter();return;}
  if(t.matches&&t.matches('[data-mksort]')){var tb=document.getElementById('mk-fa');
    tb.setAttribute('data-sort','');sortTable(tb,t.value);return;}
});
"""


def _team_link(t: dict, cls: str = "") -> str:
    return (f'<a class="lh-chip {t["cls"]} v2-tap{" " + cls if cls else ""}" href="{t["href"]}">'
            f'<span class="lh-swatch"></span>{clean(t["team"])}</a>')


def _name(p: dict, bold: bool = False) -> str:
    inner = f"<b>{clean(p['name'])}</b>" if bold else clean(p["name"])
    if p.get("href"):
        return f'<a class="v2-pl v2-tap" href="{clean(p["href"])}">{inner}</a>'
    return f"<span>{inner}</span>"


def _chips(chips: list) -> str:
    out = []
    for c in chips:
        kind = {"out": "out", "q": "q", "il": "il"}.get(c.get("kind"), "neutral")
        out.append(f'<span class="lh-status lh-status--{kind}">{clean(c["text"])}</span>')
    return "".join(out)


def _cell(c: dict, name: str) -> str:
    cls = ("lh-s" + str(c["b"])) if c["b"] else "v2-mk-s0"
    if not c.get("tip"):
        return f'<span class="v2-mkcell v2-mkcell--off"><span class="v2-mkbox {cls}">{clean(c["n"])}</span></span>'
    tip = c["tip"]
    attrs = (f' data-tip-h="{clean(tip["h"])}" data-tip-b="{clean(tip["b"])}"'
             + (f' data-tip-f="{clean(tip["f"])}"' if tip.get("f") else "") + ' aria-expanded="false"')
    label = clean(" \u00b7 ".join(x for x in (name, tip["h"], c["n"] + " games", tip["b"], tip.get("f", "")) if x))
    return (f'<button type="button" class="v2-mkcell"{attrs} aria-label="{label}">'
            f'<span class="v2-mkbox {cls}">{clean(c["n"])}</span></button>')


# =============================================================================
# the segments
# =============================================================================

def _available(a: dict, ids, info) -> str:
    o = ['<div class="v2-fchips">',
         '<button type="button" class="v2-fchip" data-mkh="1" aria-pressed="false">Healthy</button>',
         '<label class="v2-fchip">Position<select data-mkpos aria-label="Position"><option value="">Any</option>'
         + "".join(f'<option value="{clean(p)}">{clean(p)}</option>' for p in a["pos"]) + "</select></label>",
         '<label class="v2-fchip">Sort<select data-mksort aria-label="Sort">'
         + "".join(f'<option value="{k}"{" selected" if k == a["default"] else ""}>{clean(lab)}</option>'
                   for k, lab in (("l14", "L14"), ("fppg", "FPPG"), ("pts", "Projected pts")))
         + "</select></label></div>"]
    o.append('<section class="lh-card lh-card--flush" data-section="available"><div class="lh-sechead v2-pad">'
             f'<h2 class="lh-eyebrow">{clean(a["title"])}</h2><span class="lh-meta">{clean(a["meta"])}</span></div>')
    if not a["rows"]:
        o.append(f'<p class="v2-p v2-pad">{clean(a["empty"])}</p></section>')
        return "".join(o)
    o.append(f'<div class="v2-scroll"><table class="lh-table v2-mk-fa" id="mk-fa" data-sort="{clean(a["default"])}" '
             f'data-dir="1" data-orders=\'{clean(a["orders_json"])}\'><thead><tr><th>Player</th>')
    for k, lab in (("fppg", "FPPG"), ("l14", "L14")):
        on = k == a["default"]
        o.append(f'<th data-k="{k}"{" aria-sort=" + chr(34) + "descending" + chr(34) if on else ""}>'
                 f'<button type="button" class="v2-tap" data-sort="{k}">{clean(lab)}'
                 f'<span class="v2-arrow">{" &#9662;" if on else ""}</span></button></th>')
    cols = clean(DOT.join(a["cols"]))
    o.append(f'<th>Games<span class="lh-sub">{cols}</span></th></tr></thead><tbody>')
    for i in a["default_rows"]:
        r = a["rows"][i]
        o.append(f'<tr data-i="{i}" data-h="{r["h"]}" data-pos="{clean(r["pos"])}"><td>{_name(r)}'
                 f'<span class="lh-sub">{clean(r["sub"])} {_chips(r["chips"])}</span></td>'
                 f'<td class="lh-num">{clean(r["fppg"])}</td><td class="lh-num">{clean(r["l14"])}</td>'
                 f'<td><span class="v2-mk-cells">' + "".join(_cell(c, r["name"]) for c in r["games"])
                 + "</span></td></tr>")
    o.append('</tbody></table></div><p class="v2-p v2-pad" id="mk-fa-none" hidden>No free agent on this list '
             f'matches.</p><div class="lh-table-note">{clean(a["note"])}</div></section>')
    o.append(f'<span class="lh-sub">{clean(a["aside"])}</span>')
    return "".join(o)


def _stash(s: dict) -> str:
    o = ['<section class="lh-card" data-section="stash"><div class="lh-sechead"><h2 class="lh-eyebrow">Stash</h2>'
         f'<span class="lh-meta">{clean(s["aside"])}</span></div>']
    if not s["rows"]:
        o.append(f'<p class="v2-p">{clean(s["empty"])}</p>')
    o.append('<div class="v2-mk-list">')
    for r in s["rows"]:
        o.append(f'<div class="v2-mk-item"><span class="v2-minw">{_name(r)}<span class="lh-sub">{clean(r["sub"])}'
                 f'{" &middot; " + clean(r["note"]) if r["note"] else ""}</span></span>'
                 f'<span class="v2-mk-right">{_chips(r["chips"])}<span class="lh-sub">Proj {clean(r["proj"])}</span>'
                 "</span></div>")
    o.append(f'</div><span class="lh-sub">{clean(s["open_il"])}</span><span class="lh-sub">{clean(s["note"])}</span>'
             "</section>")
    return "".join(o)


def _block(b: dict) -> str:
    o = ['<section class="lh-card" data-section="block"><div class="lh-sechead"><h2 class="lh-eyebrow">Trade block</h2>'
         "</div>"]
    for c in b["cards"]:
        o.append(f'<div class="lh-divider v2-mk-block"><div class="v2-tb-head">{_team_link(c["team"])}'
                 f'<span class="lh-status lh-status--neutral">{clean(c["stance"])}'
                 f'{" &middot; " + clean(c["since"]) if c["since"] else ""}</span></div>')
        for lst in c["lists"]:
            o.append(f'<span class="v2-mk-tbl"><b>{clean(lst["label"])}:</b> '
                     + ", ".join(_name(p) + f' <span class="v2-mk-sub">{clean(p["sub"])}</span>'
                                 for p in lst["players"]) + "</span>")
        if c["empty"]:
            o.append(f'<span class="v2-mk-tbl">{clean(c["empty"])}</span>')
        o.append("</div>")
    o.append(f'<span class="lh-sub">{clean(b["foot"])}</span></section>')
    return "".join(o)


def _week_head(w: dict) -> str:
    """5b (5a decision 7): a budget week's label and its adds used, each
    manager's (data-ms: the team chips filter it), over the budget in red."""
    if w["used"] is None:
        used = f'<span class="lh-sub">{clean(w["note"])}</span>' if w["note"] else ""
    else:
        used = ('<span class="v2-mv-used"><span>Adds used:</span>' + "".join(
            f'<span data-ms="{clean(u["m"])}"{" class=" + chr(34) + "v2-mv-over" + chr(34) if u["over"] else ""}>'
            f'{clean(u["text"])}{" (over)" if u["over"] else ""}</span>' for u in w["used"]) + "</span>")
    return f'<div class="v2-mv-wk"><b class="v2-name14">{clean(w["label"])}</b>{used}</div>'


def _week_items(mv: dict, weeks: list) -> str:
    o = []
    for w in weeks:
        mine = [it for it in mv["items"] if it.get("wk") == w["key"]]
        if not mine and w["used"] is None:
            continue
        o.append(_week_head(w))
        o.extend(_move_row(it) for it in mine)
    return "".join(o)


def moves_older_html(mv: dict) -> str:
    """Every budget week but the latest (5b: Market > Moves' lazy part), or
    "" when there is none."""
    weeks = mv.get("weeks") or []
    return _week_items(mv, weeks[1:]) if len(weeks) > 1 else ""


def _moves(mv: dict, parts: dict = None, mode: str = "preview") -> str:
    o = ['<div class="v2-fchips" role="group" aria-label="Team">'
         '<button type="button" class="v2-fchip v2-mvchip" data-mvf="" aria-pressed="true">All teams</button>']
    for t in mv["teams"]:
        o.append(f'<button type="button" class="v2-fchip v2-mvchip {t["cls"]}" data-mvf="{clean(t["manager"])}" '
                 f'aria-pressed="false"><span class="lh-swatch"></span>{clean(t["team"])}</button>')
    o.append('</div><section class="lh-card" data-section="moves" id="mk-moves"><div class="lh-sechead">'
             '<h2 class="lh-eyebrow">Moves</h2></div>')
    if not mv["items"]:
        o.append(f'<p class="v2-p">{clean(mv["empty"])}</p>')
    weeks = mv.get("weeks") or []
    o.append('<div class="v2-mk-list">')
    o.append(_week_items(mv, weeks[:1]))
    older = moves_older_html(mv)
    if older:
        # published: an encrypted part (publish.market_files); the preview: a template. A page
        # rendered in publish mode without the part (a test's) carries them inline.
        ref = (parts or {}).get("moves_older")
        if ref or mode != "publish":
            attr = f" data-part='{clean(json.dumps(ref, separators=(',', ':')))}'" if ref else ""
            o.append(f'<div class="v2-mv-older" data-mvolder-of="1"{attr}><button type="button" class="lh-btn v2-btn" '
                     'data-mvolder="1">Show older weeks</button></div>')
            if not ref:
                o.append(f'<template id="v2-mk-older">{older}</template>')
        else:
            o.append(older)
    o.append(f'</div><span class="lh-sub">{clean(mv["note"])}</span></section>')
    return "".join(o)


def _move_row(it: dict) -> str:
    head = " &middot; ".join(_team_link(t) for t in it["teams"]) if it["mkind"] != "trade" else (
        "Trade &middot; " + f" {chr(8644)} ".join(_team_link(t) for t in it["teams"]))
    parts = "".join(f'<span class="v2-mv-part"><span class="v2-mv-{clean(p["kind"])}">{clean(p["marker"])}</span> '
                    + "".join(_seg(x) for x in p["segs"]) + "</span>" for p in it["parts"])
    meta = " &middot; ".join(clean(x) for x in (it["note"], it["state"] if it["state"] != "Applied" else "") if x)
    return (f'<div class="v2-mv" data-ms="{clean(" ".join(it["ms"]))}"><span class="v2-mv-mark v2-mv-{it["mkind"]}" '
            f'aria-hidden="true">{clean(it["marker"])}</span><span class="v2-mv-body"><span class="lh-sub">{head}</span>'
            f'{parts}{"<span class=" + chr(34) + "lh-sub" + chr(34) + ">" + meta + "</span>" if meta else ""}</span>'
            f'<span class="v2-mk-right"><span class="lh-sub">{clean(it["when"])}</span>'
            f'<span class="lh-sub">{clean(it["time"])}</span></span></div>')


def _seg(x: dict) -> str:
    if x.get("href"):
        return f'<a class="v2-pl v2-tap" href="{clean(x["href"])}"><b>{clean(x["t"])}</b></a>'
    t = x["t"]
    lead, trail = t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):]
    return (lead + clean(t) + trail) if t.strip() else t.replace("<", "").replace(">", "")


# =============================================================================
# the Advice view (Advice.html v5)
# =============================================================================

def _weeks(weeks: list) -> str:
    o = ['<span class="adv-wkrows">']
    for w in weeks:
        d = {"up": "", "down": " adv-v--down"}.get(w["dir"], " adv-v--flat")
        o.append(f'<span class="adv-l">{clean(w["label"])}</span><span class="adv-v{d}">{clean(w["value"])}</span>')
    o.append("</span>")
    return "".join(o)


def _tiles(tiles: list) -> str:
    if not tiles:
        return ""
    o = ['<div class="adv-mini">']
    for t in tiles:
        d = {"up": " adv-up", "down": " adv-down"}.get(t["dir"], "")
        o.append(f'<div class="lh-kpi lh-kpi--nested"><span class="lh-label">{clean(t["label"])}</span>'
                 f'<span class="lh-kpi__value{d}">{clean(t["value"])}</span></div>')
    o.append("</div>")
    return "".join(o)


def _lines(lines: list) -> str:
    """The row's second line(s), plain text: the row itself is the tap that
    opens it (no link inside a button); the names' cards are in the opened part."""
    out = []
    for x in lines:
        if x["kind"] == "note":           # H54: the hold row's sub-line, no sign
            out.append(f'<span class="adv-drop"><span>{clean(x["name"])}</span></span>')
        elif x["kind"] == "il":
            out.append(f'<span class="adv-drop"><span class="adv-sign adv-sign-il">IL</span>'
                       f'<span>{clean(x["name"])}</span></span>')
        else:
            out.append(f'<span class="adv-drop"><span class="adv-sign adv-down">{clean(x["sign"])}</span>'
                       f'<span>{clean(x["name"])}</span></span>')
    return "".join(out)


def _cards(players: list) -> str:
    """Every player a row names, each opening his card (4c1), in the opened part."""
    linked = [p for p in players if p.get("href")]
    if not linked:
        return ""
    return '<div class="adv-cards">Cards: ' + " &middot; ".join(_name(p) for p in linked) + "</div>"


def _adv_row(r: dict, ids) -> str:
    did = ids.next("adv")
    adds = ", ".join(f"<b>{clean(p['name'])}</b>" for p in r["adds"])
    flag = ' <span class="adv-flag" title="Also in another team\u2019s plan" aria-label="Another team wants him too">&#9873;</span>' \
        if r["flag"] else ""
    if r["kind"] == "act":
        head = (f'<button type="button" class="adv-row adv-row--il" aria-expanded="false" aria-controls="{did}">'
                f'<span class="adv-ilic" aria-hidden="true">&#8634;</span><span class="adv-mv">'
                f'<span class="adv-ilk">{clean(r["label"])}</span><span class="adv-add">{adds}</span>{_lines(r["lines"])}</span>')
    else:
        head = (f'<button type="button" class="adv-row" aria-expanded="false" aria-controls="{did}">'
                f'<span class="adv-n" aria-label="Step {clean(r["n"])}">{clean(r["n"])}</span><span class="adv-mv">'
                f'<span class="adv-add"><span class="adv-sign adv-up">+</span>{adds}{flag}</span>{_lines(r["lines"])}</span>')
    head += f'{_weeks(r["weeks"])}<span class="adv-chev" aria-hidden="true">&rsaquo;</span></button>'
    det = [f'<div class="adv-det" id="{did}" hidden><div class="adv-why">{clean(r["why"])}</div>']
    if r.get("followup"):
        det.append(f'<div class="adv-why">{clean(r["followup"])}</div>')
    det.append(_tiles(r["tiles"]))
    if r["also"]:
        det.append('<div class="adv-tag">Also wanted by ' + "".join(_team_link(t) for t in r["also"]) + "</div>")
    det.append(_cards(r["adds"] + r["lines"]))
    det.append("</div>")
    return head + "".join(det)


def _advice(av: dict, ids, info, mark_of) -> str:
    o = [f'<div class="adv-intro"><span>{clean(av["intro"])}</span>{info}</div>']
    if av["error"] or av["empty"]:
        o.append(f'<section class="lh-card adv"><div class="adv-err">{clean(av["error"] or av["empty"])}</div></section>')
    for c in av["cards"]:
        t = c["team"]
        o.append(f'<section class="lh-card adv {t["cls"]}" data-manager="{clean(t["manager"])}"><div class="adv-head">'
                 f'{mark_of(t)}<span class="v2-minw"><a class="adv-team v2-tap" href="{t["href"]}">{clean(t["team"])}</a>'
                 f'<span class="lh-sub">{clean(c["vs"])}</span></span><span class="adv-adds">{clean(c["adds"])}</span></div>')
        if c["rows"]:
            o.append('<div class="adv-hrow"><span></span><span></span><span class="adv-colh">Win % change</span>'
                     "<span></span></div>")
            for k, r in enumerate(c["rows"]):
                if k:
                    o.append('<div class="adv-then" aria-hidden="true">then</div>')
                o.append(_adv_row(r, ids))
        if c["plan"]:
            p = c["plan"]
            o.append(f'<div class="adv-plan"><span></span><span class="adv-plan-l"><span class="lh-label">'
                     f'{clean(p["label"])}</span>'
                     + (f'<span class="lh-sub">{clean(p["title"])}</span>' if p["title"] else "")
                     + f'</span>{_weeks(p["weeks"])}<span></span></div>')
        elif c.get("title"):                                     # one row: its title-odds line (Nick, 11-19)
            o.append(f'<div class="adv-plan adv-title"><span></span><span class="adv-plan-l">'
                     f'<span class="lh-sub">{clean(c["title"])}</span></span><span></span><span></span></div>')
        if c["backup"]:
            b = c["backup"]
            did = ids.next("adv")
            o.append(f'<button type="button" class="adv-bk" aria-expanded="false" aria-controls="{did}"><span>'
                     f'{clean(b["if"])} <b>+ {clean(b["add"]["name"])}'
                     + "".join(f' {clean(x["sign"])} {clean(x["name"])}' for x in b["lines"])
                     + '</b></span><span class="adv-chev" aria-hidden="true">&rsaquo;</span></button>'
                     f'<div class="adv-det" id="{did}" hidden>{_weeks(b["weeks"])}<div class="adv-why">{clean(b["why"])}</div>'
                     f'{_tiles(b["tiles"])}{_cards([b["add"]] + b["lines"])}</div>')
        if c["empty"]:
            o.append(f'<div class="adv-empty">{clean(c["empty"])}</div>')
        o.append("</section>")
    if av["foot"]:
        o.append(f'<span class="lh-sub">{clean(av["foot"])}</span>')
    return "".join(o)


def market_screen(vm: dict, ids, info_of, mark_of) -> str:
    """The Market tab (#/market): the segments over their panes; the first is
    selected (a later visit keeps the session's choice: the page's `seen`)."""
    mk = vm["market"]
    o = ['<section class="v2-screen" data-route="market" hidden><div class="v2-stack">',
         '<div class="lh-seg" role="tablist" data-seg="market">'
         + "".join(f'<button type="button" role="tab" data-pane="{k}" aria-selected="{"true" if i == 0 else "false"}">'
                   f'{clean(lab)}</button>' for i, (k, lab) in enumerate(mk["segs"])) + "</div>"]
    for i, (k, _lab) in enumerate(mk["segs"]):
        o.append(f'<div class="v2-sec" data-pane-of="{k}"{"" if i == 0 else " hidden"}>')
        if k == "available":
            o.append(_available(mk["available"], ids, info_of))
        elif k == "stash":
            o.append(_stash(mk["stash"]))
        elif k == "advice":
            o.append(_advice(mk["advice"], ids, info_of(ids, "advice"), mark_of))
        elif k == "block":
            o.append(_block(mk["block"]))
        elif k == "moves":
            o.append(_moves(mk["moves"], mk.get("parts"), vm.get("mode", "preview")))
        o.append("</div>")
    o.append("</div></section>")
    return "".join(o)
