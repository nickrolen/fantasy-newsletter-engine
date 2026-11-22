"""
hub_v2/page_league.py -- the new hub's League tab (4c4): Standings . History .
Awards . Archive, printed from the view model (view.league, view.league_
history), which carries payload strings only (modules/hub_v2/league.py made
them).

THE PAGE DISPLAYS. Every number is a payload string through clean(). The
script switches segments, chips and the draft's season, opens a head-to-head
cell's seasons, and (publish mode) loads a History chip's encrypted file the
first time it opens. It computes nothing.

HISTORY IS LAZY (4c4 s.2): each chip's HTML is rendered at build time
(chip_html). The plaintext preview embeds it (a <template> per chip); the
published page carries only each chip's encrypted file and key (in the
encrypted page), and HUB.part fetches and opens it on the chip's first tap.
AWARDS ARE LAZY TOO (4c5): the whole segment (the races and Player of the
Week, awards_html) is one more part, opened on the segment's first show.

CSS rules: tokens only (var(--...)); no hex colour, no px literal.
"""

from __future__ import annotations

import json

from .text import clean, colh_btn

TAP_CLASSES = ("v2-lg-cell", "v2-lg-why", "v2-lg-game", "v2-lg-issue", "v2-lg-sum", "v2-lg-tile")
PARTS = ("awards",)                     # League's lazy segments beside History's chips (4c5)
DOT = " &middot; "

CSS = """
.v2-lg-pane{display:flex;flex-direction:column;gap:var(--space-20)}
.v2-lg-team{display:flex;align-items:center;gap:var(--space-8);min-width:0;text-decoration:none;color:var(--ink)}
.v2-lg-team b{font-size:var(--type-row-size);font-weight:800;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.v2-lg-rank{font-family:var(--font-display);font-size:var(--type-display-row-size);font-weight:700;min-width:var(--space-14);text-align:center}
.v2-lg-tie{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);vertical-align:super}
.v2-lg-st td{vertical-align:middle;white-space:nowrap}
.v2-lg-st td:first-child{text-align:left;white-space:normal}
.v2-lg-st th:first-child,.v2-lg-st td:first-child{padding-left:var(--space-10)}
.v2-lg-st .v2-lg-team{gap:var(--space-6)}
.v2-lg-st .lh-sub{font-size:var(--type-small-size)}
.v2-lg-blk{display:block}
.v2-lg-st .v2-lg-team b{max-width:20vw}
.v2-lg-st .v2-lg-rank{min-width:var(--space-10)}
.v2-lg-odds{display:flex;flex-direction:column;align-items:flex-end;gap:var(--space-2)}
.v2-lg-odds b{font-weight:800}
.v2-lg-wk{display:flex;flex-direction:column;gap:var(--space-4);padding-top:var(--space-10)}
.v2-lg-wk:first-of-type{padding-top:0}
.v2-lg-wkh{display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-8)}
.v2-lg-row{display:grid;grid-template-columns:var(--space-24) minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-6) 0}
.v2-lg-row:first-child{border-top:0}
.v2-lg-right{display:flex;flex-direction:column;align-items:flex-end;gap:var(--space-2);text-align:right;white-space:nowrap}
.v2-lg-val{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:700;font-variant-numeric:tabular-nums}
.v2-lg-wkn{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);text-transform:uppercase;letter-spacing:var(--type-label-ls)}
.v2-lg-soon{font-size:var(--type-body-size);color:var(--ink-2)}
.v2-lg-issue{all:unset;box-sizing:border-box;cursor:pointer;width:100%;display:grid;grid-template-columns:var(--space-32) minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-6) 0}
.v2-lg-issue:first-child{border-top:0}
.v2-lg-issue:focus-visible{outline:var(--hairline) solid var(--accent)}
.v2-lg-issue:disabled{opacity:.6}
.v2-lg-iwk{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:700;text-align:center}
.v2-lg-chips{display:flex;flex-wrap:wrap;gap:var(--space-6)}
.v2-lg-hist{display:flex;flex-direction:column;gap:var(--space-20)}
.v2-lg-champ{display:grid;grid-template-columns:var(--space-32) minmax(0,1fr);column-gap:var(--space-10);align-items:start;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-8) 0}
.v2-lg-champ:first-child{border-top:0}
.v2-lg-season{font-family:var(--font-display);font-size:var(--type-display-row-size);font-weight:700;font-variant-numeric:tabular-nums}
.v2-lg-line{font-size:var(--type-meta-size);color:var(--ink-2);overflow-wrap:anywhere}
.v2-lg-line b{color:var(--ink);font-weight:800}
.v2-lg-h2h{display:grid;grid-template-columns:var(--tap-min) repeat(var(--n),minmax(0,1fr));gap:var(--space-4);align-items:center}
.v2-lg-hh{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);text-align:center;display:flex;justify-content:center}
.v2-lg-cell{all:unset;box-sizing:border-box;cursor:pointer;min-height:var(--tap-min);display:flex;align-items:center;justify-content:center;border-radius:var(--radius-6);background:var(--surface-subtle);font-size:var(--type-meta-size);font-weight:800;color:var(--ink);font-variant-numeric:tabular-nums}
.v2-lg-cell[aria-expanded="true"]{box-shadow:0 0 0 var(--hairline) var(--ink-strong)}
.v2-lg-cell:focus-visible{outline:var(--hairline) solid var(--accent)}
.v2-lg-diag{min-height:var(--tap-min);display:flex;align-items:center;justify-content:center;color:var(--ink-3);font-size:var(--type-meta-size)}
.v2-lg-pair{display:flex;flex-direction:column;gap:var(--space-4);padding-top:var(--space-10);border-top:var(--hairline) solid var(--line-soft)}
.v2-lg-pl{display:grid;grid-template-columns:var(--space-32) minmax(0,1fr);column-gap:var(--space-10);font-size:var(--type-meta-size);color:var(--ink-2)}
.v2-lg-pl span:first-child{font-weight:800;color:var(--ink);white-space:nowrap}
.v2-lg-tiles .lh-kpi{text-align:left}
.v2-lg-tile{all:unset;box-sizing:border-box;cursor:pointer;display:flex;flex-direction:column;gap:var(--space-2);min-height:var(--tap-min)}
.v2-lg-group{display:flex;flex-direction:column;gap:var(--space-6)}
.v2-lg-group details{border-top:var(--hairline) solid var(--line-soft)}
.v2-lg-group details:first-of-type{border-top:0}
.v2-lg-sum{cursor:pointer;min-height:var(--tap-min);display:flex;align-items:center;justify-content:space-between;gap:var(--space-8);font-size:var(--type-row-size);font-weight:800;color:var(--ink);list-style:none}
.v2-lg-sum::-webkit-details-marker{display:none}
.v2-lg-sum span:last-child{font-size:var(--type-meta-size);font-weight:700;color:var(--ink-2);white-space:nowrap}
.v2-lg-rec{display:grid;grid-template-columns:var(--space-20) minmax(0,1fr) auto;column-gap:var(--space-8);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft)}
.v2-lg-rec .v2-lg-who{display:flex;flex-direction:column;min-width:0;font-size:var(--type-body-size);overflow-wrap:anywhere}
.v2-lg-n{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);text-align:center}
.v2-lg-game{all:unset;box-sizing:border-box;cursor:pointer;min-height:var(--tap-min);min-width:var(--tap-min);display:inline-flex;align-items:center;justify-content:flex-end;gap:var(--space-4)}
.v2-lg-game[aria-expanded="true"] .v2-lg-val{text-decoration:underline}
.v2-lg-dsel{display:flex;flex-wrap:wrap;gap:var(--space-8);align-items:center}
.v2-lg-dr td{vertical-align:middle}
.v2-lg-dr td:nth-child(2),.v2-lg-dr th:nth-child(2){text-align:left;max-width:44vw}
.v2-lg-k{font-size:var(--type-small-size);font-weight:800;color:var(--ink-3);margin-left:var(--space-4)}
.v2-lg-dr--team td:first-child{text-align:left;max-width:52vw}
.v2-lg-dr--team td:nth-child(2),.v2-lg-dr--team th:nth-child(2){text-align:right;max-width:none}
.v2-lg-dr--team th:first-child{text-align:left}
.v2-lg-dteam th{text-align:left;padding-top:var(--space-8)}
.v2-lg-why{all:unset;box-sizing:border-box;cursor:pointer;min-height:var(--tap-min);min-width:var(--tap-min);display:inline-flex;align-items:center;justify-content:flex-end;color:var(--ink-3);text-decoration:underline dotted var(--axis-strong)}
.v2-lg-why[aria-expanded="true"]{color:var(--ink)}
.v2-lg-chg{font-size:var(--type-small-size);font-weight:700;margin-left:var(--space-2)}
.v2-lg-chg--up{color:var(--up)}.v2-lg-chg--down{color:var(--down)}.v2-lg-chg--flat{color:var(--ink-3)}
.v2-lg-trade{display:flex;flex-direction:column;gap:var(--space-4);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-10) 0}
.v2-lg-trade:first-child{border-top:0;padding-top:0}
.v2-lg-th{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-6)}
.v2-lg-side{font-size:var(--type-body-size);color:var(--ink-2);overflow-wrap:anywhere}
.v2-lg-side b{color:var(--ink);font-weight:800}
.v2-lg-load{font-size:var(--type-body-size);color:var(--ink-2)}
.v2-aw-head{display:flex;align-items:center;justify-content:space-between;gap:var(--space-8)}
.v2-aw-st{display:flex;align-items:center;gap:var(--space-6)}
.v2-aw-lead{font-size:var(--type-body-size);font-weight:800;color:var(--ink)}
.v2-aw-shown{font-size:var(--type-meta-size);color:var(--ink-2);overflow-wrap:anywhere}
.v2-aw-side{font-size:var(--type-meta-size);color:var(--ink-2);overflow-wrap:anywhere}
.v2-aw-side b{color:var(--ink);font-weight:800}
.v2-aw-err{font-size:var(--type-body-size);color:var(--ink-2)}
.v2-aw-odds{font-size:var(--type-meta-size);font-weight:800;color:var(--ink)}
.v2-aw-oddsh{display:flex;align-items:center;justify-content:space-between;gap:var(--space-8);border-top:var(--hairline) solid var(--line-soft);padding-top:var(--space-8)}
.v2-aw-oth{display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-6);font-size:var(--type-meta-size);color:var(--ink-2)}
.v2-aw-oth b{color:var(--ink);font-weight:800}
.v2-aw-past{display:grid;grid-template-columns:max-content minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-6) 0}
.v2-aw-past:first-of-type{border-top:0}
.v2-tro{font-variant-numeric:tabular-nums}
.v2-tro td,.v2-tro th{text-align:center}
.v2-tro td:first-child,.v2-tro th:first-child{text-align:left}
.v2-tro .v2-tro-apart{color:var(--ink-3)}
.v2-tro-n{all:unset;position:relative;box-sizing:border-box;cursor:pointer;min-width:var(--tap-min);min-height:var(--tap-min);display:inline-flex;align-items:center;justify-content:center;font-weight:800;color:var(--ink)}
.v2-tro-apart .v2-tro-n{font-weight:400;color:var(--ink-3)}
.v2-tro-z{color:var(--ink-3)}
.v2-mg-past{display:grid;grid-template-columns:max-content minmax(0,1fr) auto;column-gap:var(--space-10);align-items:center;min-height:var(--row-min);border-top:var(--hairline) solid var(--line-soft);padding:var(--space-6) 0}
"""

JS = r"""
// 4c4: the League tab -- the History chips (a chip's encrypted file is
// fetched and opened on its first tap in publish mode), head-to-head's phase
// and a cell's seasons, the draft's season. Nothing computed.
var LG={chip:'champions'};
function lgPart(pane){
  if(pane.getAttribute('data-loaded')==='1'){return Promise.resolve();}
  var key=pane.getAttribute('data-lhchip-of')||pane.getAttribute('data-lhpart-of');
  var tpl=document.getElementById('v2-lg-'+key);
  if(tpl){pane.innerHTML=tpl.innerHTML;pane.setAttribute('data-loaded','1');return Promise.resolve();}
  var ref=pane.getAttribute('data-part');
  if(!ref||!window.HUB||!window.HUB.part){return Promise.resolve();}
  if(pane._lgp){return pane._lgp;}               // 5d1: one fetch per part, however many ask
  return pane._lgp=window.HUB.part(JSON.parse(ref)).then(function(p){pane.innerHTML=p.html;pane.setAttribute('data-loaded','1');},
    function(err){if(err&&err.message==='gone'){movedBox();}
      pane._lgp=null;var e=pane.querySelector('.v2-lg-load');if(e){e.textContent='This part of the League could not be opened.';}});
}
function lgChip(key){
  LG.chip=key;
  var bs=document.querySelectorAll('[data-lhchip]');
  for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i].getAttribute('data-lhchip')===key));}
  var ps=document.querySelectorAll('[data-lhchip-of]'),want=null;
  for(var j=0;j<ps.length;j++){var on=ps[j].getAttribute('data-lhchip-of')===key;ps[j].hidden=!on;if(on){want=ps[j];}}
  return want?lgPart(want):Promise.resolve();
}
function lgPhase(ph){
  var bs=document.querySelectorAll('[data-lhphase]');
  for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i].getAttribute('data-lhphase')===ph));}
  var gs=document.querySelectorAll('[data-lhphase-of]');
  for(var j=0;j<gs.length;j++){gs[j].hidden=gs[j].getAttribute('data-lhphase-of')!==ph;}
}
function lgPair(key){
  var cs=document.querySelectorAll('[data-lhpair]');
  for(var i=0;i<cs.length;i++){cs[i].setAttribute('aria-expanded',String(cs[i].getAttribute('data-lhpair')===key));}
  var ps=document.querySelectorAll('[data-lhpair-of]');
  for(var j=0;j<ps.length;j++){ps[j].hidden=ps[j].getAttribute('data-lhpair-of')!==key;}
}
function lgAwView(key,v){
  var bs=document.querySelectorAll('[data-awview^="'+key+'|"]');
  for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i].getAttribute('data-awview')===key+'|'+v));}
  var gs=document.querySelectorAll('[data-awview-of^="'+key+'|"]');
  for(var j=0;j<gs.length;j++){gs[j].hidden=gs[j].getAttribute('data-awview-of')!==key+'|'+v;}
}
// 5d1 s.8: a season picker (data-spick) over its panes (data-spick-of); a
// published past season is a part, opened when picked
function spick(key,season){
  var sel=document.querySelector('[data-spick="'+key+'"]');if(!sel){return;}
  var ok=false;for(var i=0;i<sel.options.length;i++){if(sel.options[i].value===season){ok=true;}}
  if(!season||!ok){season=sel.options[sel.selectedIndex>=0?sel.selectedIndex:0].value;
    for(var d=0;d<sel.options.length;d++){if(sel.options[d].defaultSelected){season=sel.options[d].value;}}}
  sel.value=season;
  var ps=document.querySelectorAll('[data-spick-of^="'+key+'|"]');
  for(var j=0;j<ps.length;j++){var on=ps[j].getAttribute('data-spick-of')===key+'|'+season;ps[j].hidden=!on;
    if(on&&ps[j].getAttribute('data-part')){lgPart(ps[j]);}}
}
function lgDraft(season){spick('draft',season);}
// 5b: the title-odds chart (an encrypted part when published), opened when
// League > Standings is on screen
function lgOdds(){
  var p=document.querySelector('[data-lhpart-of="odds"]');
  if(p&&!p.closest('[hidden]')){lgPart(p);}
}
window.lgOdds=lgOdds;
// 5d1 s.4: #/league/standings?hl=<manager> -- the chart opens with his line
// highlighted and the others dimmed; a tap on the chart (or another line)
// clears it, and the route with it, so the back button works
var LGHL='';
function lgHlApply(){
  var svg=document.querySelector('[data-section="title-odds"] svg.lh-chart');if(!svg){return;}
  svg.classList.toggle('v2-hl',!!LGHL);
  var gs=svg.querySelectorAll('[data-m]');
  for(var i=0;i<gs.length;i++){gs[i].classList.toggle('v2-hl-on',!!LGHL&&gs[i].getAttribute('data-m')===LGHL);}
}
window.lgHl=function(m){
  LGHL=m||'';
  var p=document.querySelector('[data-lhpart-of="odds"]');
  var go=function(){lgHlApply();if(LGHL){var sec=document.querySelector('[data-section="title-odds"]');
    if(sec&&sec.scrollIntoView){sec.scrollIntoView({block:'start'});}}};
  if(p&&!p.closest('[hidden]')){lgPart(p).then(go);}else{go();}
};
document.addEventListener('click',function(e){
  if(!LGHL||!e.target.closest){return;}
  if(e.target.closest('[data-section="title-odds"] svg.lh-chart')){
    LGHL='';lgHlApply();
    try{history.replaceState(null,'','#/league/standings');}catch(x){}
  }
});
// #/league/<segment>[/<chip>[/<a>/<b> | /<season>]]
window.lgRoute=function(parts){
  var seg=document.querySelector('.lh-seg[data-seg="league"]');
  var s=parts[0]||'standings';seen['league']=s;if(seg){pick(seg,s);}
  var q=window.routeQ||{};
  if(s==='awards'){var ap=document.querySelector('[data-lhpart-of="awards"]');
    if(ap){lgPart(ap).then(function(){spick('potw',parts[1]==='potw'?(q.s||''):'');
      if(parts[1]){var sec=document.querySelector('[data-award="'+parts[1]+'"]')||
        document.querySelector('[data-section="'+parts[1]+'"]');
      if(sec&&sec.scrollIntoView){sec.scrollIntoView();}}});}return;}
  if(s!=='history'){return;}
  var c=parts[1]||LG.chip;
  lgChip(c).then(function(){
    if(c==='h2h'&&parts.length>3){lgPair(decodeURIComponent(parts[2])+'|'+decodeURIComponent(parts[3]));}
    if(c==='draft'){spick('draft',parts[2]?decodeURIComponent(parts[2]):(q.s||''));}
    if(c==='trades'){spick('trades',q.s||'');}
  });
};
document.addEventListener('click',function(e){
  var t=e.target.closest('.lh-seg[data-seg="league"] button[data-pane="history"]');
  if(t){setTimeout(function(){lgChip(LG.chip);},0);}
  t=e.target.closest('.lh-seg[data-seg="league"] button[data-pane="standings"]');
  if(t){setTimeout(lgOdds,0);}
  t=e.target.closest('.lh-seg[data-seg="league"] button[data-pane="awards"]');
  if(t){setTimeout(function(){var ap=document.querySelector('[data-lhpart-of="awards"]');if(ap){lgPart(ap);}},0);}
  t=e.target.closest('[data-lhchip]');
  if(t){lgChip(t.getAttribute('data-lhchip'));return;}
  t=e.target.closest('[data-lhphase]');
  if(t){lgPhase(t.getAttribute('data-lhphase'));return;}
  t=e.target.closest('[data-awview]');
  if(t){var av=t.getAttribute('data-awview').split('|');lgAwView(av[0],av[1]);return;}
  t=e.target.closest('[data-lhpair]');
  if(t){var k=t.getAttribute('data-lhpair');lgPair(t.getAttribute('aria-expanded')==='true'?'':k);return;}
});
document.addEventListener('change',function(e){
  var t=e.target;
  if(t.matches&&t.matches('[data-spick]')){                 // 5d1 s.8: the season goes in the route
    var k=t.getAttribute('data-spick'),to=(k==='potw')?'#/league/awards/potw?s=':'#/league/history/'+k+'?s=';
    location.hash=to+encodeURIComponent(t.value);}
});
"""


def _team(t: dict, mono, sub: str = "", size: str = "28") -> str:
    return (f'<a class="v2-lg-team v2-tap" href="{t["href"]}">{mono(t, size)}<span class="v2-minw">'
            f'<b>{clean(t["team"])}</b>' + (f'<span class="lh-sub">{clean(sub)}</span>' if sub else "")
            + "</span></a>")


def _mgr(t: dict, mono, sub: str = "") -> str:
    """A table's team cell where width is short: the monogram and the manager's
    first name (the README's rule for people), the team's name in its label."""
    return (f'<a class="v2-lg-team v2-tap" href="{t["href"]}" aria-label="{clean(t["team"])}, {clean(t["manager"])}">'
            f'{mono(t, "24")}<span class="v2-minw"><b>{clean(t["manager"])}</b>'
            + (f'<span class="lh-sub">{clean(sub)}</span>' if sub else "") + "</span></a>")


def _chip(t: dict) -> str:
    return (f'<a class="lh-chip {t["cls"]} v2-tap" href="{t["href"]}"><span class="lh-swatch"></span>'
            f'{clean(t["team"])}</a>')


def _name(p: str, href: str, bold: bool = False) -> str:
    inner = f"<b>{clean(p)}</b>" if bold else clean(p)
    if href:
        return f'<a class="v2-pl v2-tap" href="{clean(href)}">{inner}</a>'
    return f"<span>{inner}</span>"


def _tip(tip: dict) -> str:
    return (f' data-tip-h="{clean(tip["h"])}" data-tip-b="{clean(tip["b"])}"'
            + (f' data-tip-f="{clean(tip["f"])}"' if tip.get("f") else "") + ' aria-expanded="false"')


def _why(text: str, who: str, reason: str) -> str:
    """A "\u2014" with its reason one tap away (the shared tooltip)."""
    if not reason:
        return clean(text)
    return (f'<button type="button" class="v2-lg-why"{_tip({"h": who, "b": reason})} '
            f'aria-label="{clean(who)}: {clean(reason)}">{clean(text)}</button>')


# =============================================================================
# Standings
# =============================================================================

def odds_html(lg: dict, chart) -> str:
    """The title-odds chart and its note (5b: an encrypted part when
    published, opened when Standings shows; inline in the preview)."""
    return chart(lg["chart"], "lg-odds") + f'<span class="lh-sub">{clean(lg["chart_note"])}</span>'


def _standings(lg: dict, ids, info, mono, chart) -> str:
    st = lg["standings"]
    o = ['<section class="lh-card lh-card--flush" data-section="standings"><div class="lh-sechead v2-pad">'
         f'<h2 class="lh-eyebrow">{clean(st["title"])}</h2><span class="lh-meta">{clean(st["meta"])}</span></div>'
         '<div class="v2-scroll"><table class="lh-table v2-lg-st"><thead><tr>'
         + "".join(f'<th>{colh_btn("standings", k, clean(lab))}</th>' for k, lab in (
             ("team", "Team"), ("wl", "W-L"), ("pf", "PF"), ("strk", "Strk"), ("title", st["odds_label"].split(" ")[0])))
         + '</tr></thead><tbody>']
    for r in st["rows"]:
        t = r["team"]
        d = r["dir"] if r["dir"] in ("up", "down") else "flat"
        tie = ('<span class="v2-lg-tie" aria-label="tie broken: see the note">*</span>' if r["tie"] else "")
        o.append(f'<tr><td><span class="v2-lg-team"><span class="v2-lg-rank">{clean(r["rank"])}{tie}</span>'
                 + _mgr(t, mono) + "</span></td>"
                 f'<td class="lh-num">{clean(r["record"])}</td><td class="lh-num">{clean(r["pf"])}</td>'
                 f'<td class="lh-num">{clean(r["streak"])}</td><td class="lh-num"><a class="v2-lg-odds v2-oddslink" '
                 f'href="{t["odds_href"]}" aria-label="{clean(t["team"])}: title odds {clean(r["odds"])}, on the chart">'
                 f'<b>{clean(r["odds"])}</b>'
                 f'<span class="lh-delta lh-delta--{d}">{clean(r["delta"])}</span></a></td></tr>')
    o.append("</tbody></table></div>")
    note = st["note"] + ("".join(" * " + x for x in st["ties"]) if st["ties"] else "")
    o.append(f'<div class="lh-table-note">{clean(note)}</div></section>')
    ref = (lg.get("parts") or {}).get("odds")       # 5b: published, the chart is a lazy part
    body = (f'<div class="v2-lg-hist" data-lhpart-of="odds" data-part=\'{clean(json.dumps(ref, separators=(",", ":")))}\'>'
            '<p class="v2-lg-load">Loading the chart&hellip;</p></div>') if ref else odds_html(lg, chart)
    o.append('<section class="lh-card v2-gap8" data-section="title-odds"><div class="lh-sechead">'
             f'<h2 class="lh-eyebrow">{clean(st["odds_label"])} over the season</h2>'
             f'{info(ids, "title_odds", "tap a point")}</div>' + body + '</section>')
    pw = lg["power"]
    o.append('<section class="lh-card v2-gap8" data-section="power-history"><div class="lh-sechead">'
             '<h2 class="lh-eyebrow">Power rankings by week</h2></div>')
    if not pw["weeks"]:
        o.append(f'<p class="v2-p">{clean(pw["empty"])}</p>')
    for w in pw["weeks"]:
        o.append(f'<div class="v2-lg-wk"><div class="v2-lg-wkh"><span class="lh-label">{clean(w["label"])}</span>'
                 f'<span class="lh-meta">{clean(w["sub"])}</span></div>')
        for r in w["rows"]:
            t = r["team"]
            d = r["dir"] if r["dir"] in ("up", "down") else "flat"
            o.append(f'<div class="v2-lg-row {t["cls"]}"><span class="lh-rank__n">{clean(r["rank"])}</span>'
                     + _team(t, mono, r["record"], "28")
                     + f'<a class="v2-lg-right v2-oddslink" href="{t["odds_href"]}" '
                       f'aria-label="{clean(t["team"])}: title odds {clean(r["odds"])} that week, on the chart">'
                       f'<span class="lh-dsp v2-dsp-sm lh-num">{clean(r["odds"])}</span>'
                       f'<span class="lh-delta lh-delta--{d}">{clean(r["move"])}</span></a></div>')
        o.append("</div>")
    o.append(f'<span class="lh-sub">{clean(pw["note"])}</span></section>')
    return "".join(o)


# =============================================================================
# Awards and Archive
# =============================================================================

def _aw_info(a: dict, icon: str) -> str:
    """The award's InfoTip (its one-line definition), ids unique in the part."""
    pid = f"awtip-{clean(a['key'])}"
    return (f'<span class="lh-info"><span class="lh-meta v2-info-meta">{clean(a["meta"])}</span>'
            f'<button type="button" aria-expanded="false" aria-controls="{pid}" aria-label="What {clean(a["name"])} means">'
            f'{icon}</button><span class="lh-info__pop" id="{pid}" role="note" hidden><b>{clean(a["name"])}</b>'
            f'{clean(a["info"])}</span></span>')


def _odds_block(a: dict, icon: str) -> str:
    """4c6: MVP's odds under its rows -- "Odds to win" with its InfoTip and
    day, anyone else at 1% or more, everyone else, the odds' history note
    (no backfill), or why there are none. Engine strings only."""
    od = a.get("odds")
    if not od:
        return ""
    pid = f"awtip-{clean(a['key'])}-odds"
    o = [f'<div class="v2-aw-oddsh"><span class="lh-label">Odds to win</span><span class="lh-info">'
         f'<span class="lh-meta v2-info-meta">{clean(od["as_of"])}</span>'
         f'<button type="button" aria-expanded="false" aria-controls="{pid}" aria-label="What the MVP odds mean">'
         f'{icon}</button><span class="lh-info__pop" id="{pid}" role="note" hidden><b>MVP odds</b>'
         f'{clean(od["info"])}</span></span></div>']
    if od["error"]:
        o.append(f'<p class="v2-aw-err">{clean(od["error"])}</p>')
    else:
        if od["others"]:
            o.append('<span class="v2-aw-oth"><span>Also in the running:</span>'
                     + DOT.join(f'{_name(x["label"], x["href"])} <b>{clean(x["odds"])}</b>' for x in od["others"])
                     + "</span>")
        o.append(f'<span class="lh-sub">{clean(od["field"])}</span>')
    o.append(f'<span class="lh-sub">{clean(od["history"])}</span>')
    return "".join(o)


def _charts(a: dict, chart) -> str:
    """The race chart; for MVP with two weeks of odds (4c6), a PAR / Odds
    toggle over the race chart and the odds-over-weeks chart."""
    og = (a.get("odds") or {}).get("geom")
    if not a.get("geom") and not og:
        return ""
    if not og:
        return chart(a["geom"], "aw-" + a["key"])
    if not a.get("geom"):
        return chart(og, "aw-" + a["key"] + "-odds")
    k = clean(a["key"])
    return (f'<div class="v2-fchips" role="group" aria-label="{clean(a["name"])} chart">'
            f'<button type="button" class="v2-fchip" data-awview="{k}|par" aria-pressed="true">{clean(a["unit"])}</button>'
            f'<button type="button" class="v2-fchip" data-awview="{k}|odds" aria-pressed="false">Odds</button></div>'
            f'<div data-awview-of="{k}|par">' + chart(a["geom"], "aw-" + a["key"]) + "</div>"
            f'<div data-awview-of="{k}|odds" hidden>' + chart(og, "aw-" + a["key"] + "-odds") + "</div>")


def _past(a: dict) -> str:
    """4c6: the award's Past winners, collapsed (a <details>): season,
    winner (his card), the manager and his team that season, the value and
    the shown-with figure; a season without one says why."""
    p = a.get("past")
    if not p or not p.get("rows"):
        return ""
    o = [f'<details class="v2-lg-group"><summary class="v2-lg-sum"><span>Past winners</span>'
         f'<span>{clean(p["rows"][0]["season"])} back to {clean(p["rows"][-1]["season"])}</span></summary>']
    for r in p["rows"]:
        if r["none"]:
            o.append(f'<div class="v2-aw-past"><span class="v2-lg-wkn">{clean(r["season"])}</span>'
                     f'<span class="lh-sub">{clean(r["none"])}</span><span></span></div>')
            continue
        who = _name(r["label"], r["href"], True) if r["player"] else f'<b class="v2-name14">{clean(r["label"])}</b>'
        t = r["team"]
        then = "" if t and r["team_name"] == t["team"] else r["team_name"]     # that season's name, when it differs
        o.append(f'<div class="v2-aw-past"><span class="v2-lg-wkn">{clean(r["season"])}</span>'
                 f'<span class="v2-minw">{who}<span class="lh-sub">{(_chip(t) + " ") if t else ""}'
                 + (f'then {clean(then)}' if then else "") + '</span>'
                 f'<span class="v2-aw-shown">{clean(r["shown"])}</span>'
                 + (f'<span class="lh-sub">{clean(r["sub"])}</span>' if r["sub"] else "") + "</span>"
                 f'<span class="v2-lg-right"><span class="v2-lg-val">{clean(r["value"])}</span>'
                 f'<span class="lh-sub">{clean(r["unit"])}</span></span></div>')
    o.append("</details>")
    return "".join(o)


def _race(a: dict, mono, chart, icon: str) -> str:
    st = "neutral"
    o = [f'<section class="lh-card v2-gap8" data-section="award" data-award="{clean(a["key"])}">'
         f'<div class="v2-aw-head"><span class="v2-aw-st"><h2 class="lh-eyebrow">{clean(a["name"])}</h2>'
         f'<span class="lh-status lh-status--{st}">{clean(a["status"])}</span></span>{_aw_info(a, icon)}</div>']
    if a["error"]:
        o.append(f'<p class="v2-aw-err">{clean(a["error"])}</p></section>')
        return "".join(o)
    if a["leader"]:
        o.append(f'<p class="v2-aw-lead">{clean(a["leader"])}</p>')
    if a["empty"]:                       # 5e: Rookie of the Year can list only rookies under the minimum
        o.append(f'<p class="v2-p">{clean(a["empty"])}</p>')
    for r in a["rows"]:
        t = r["team"]
        d = r["dir"] if r["dir"] in ("up", "down", "flat") else "flat"
        cls = f' {t["cls"]}' if t else ""
        if r["player"]:
            who = _name(r["label"], r["href"], True)
        else:
            who = f'<b class="v2-name14">{clean(r["label"])}</b>'
        sides = "".join(f'<span class="v2-aw-side">{_chip(sd["team"]) if sd["team"] else clean(sd["m"])} '
                        f'<b>{clean(sd["par"])}:</b> '
                        + (", ".join(_name(x["name"], x["href"]) for x in sd["players"]) or "no player")
                        + (f" + {clean(sd['picks'])}" if sd["picks"] else "") + "</span>" for sd in r["sides"])
        move = (f'<span class="lh-delta lh-delta--{d}">{clean(r["move"])}</span>' if r["move"] else "")
        o.append(f'<div class="v2-lg-row{cls}"><span class="lh-rank__n">{clean(r["rank"])}</span>'
                 f'<span class="v2-minw">{who}<span class="lh-sub">{_chip(t) if t and r["player"] else ""}</span>'
                 f'<span class="v2-aw-shown">{clean(r["shown"])}</span>'
                 + (f'<span class="v2-aw-odds">{clean(r["odds"])}</span>' if r.get("odds") else "")
                 + f'{sides}'
                 + (f'<span class="lh-sub">{clean(r["sub"])}</span>' if r["sub"] else "") + '</span>'
                 f'<span class="v2-lg-right"><span class="v2-lg-val">{clean(r["value"])}</span>'
                 f'<span class="lh-sub">{clean(r["unit"])}</span>{move}</span></div>')
    o.append(_odds_block(a, icon))
    o.append(_charts(a, chart))
    o.append(_past(a))
    for x in (a["excluded"], a["source"]):
        if x:
            o.append(f'<span class="lh-sub">{clean(x)}</span>')
    o.append("</section>")
    return "".join(o)


def _mgr_award(a: dict, icon: str) -> str:
    """4c7 C: one manager award: every manager this season (rank, team mark,
    the measure, what it's shown with), then its Past winners, collapsed."""
    o = [f'<section class="lh-card v2-gap8" data-section="mgr-award" data-mgr-award="{clean(a["key"])}">'
         f'<div class="v2-aw-head"><span class="v2-aw-st"><h2 class="lh-eyebrow">{clean(a["name"])}</h2>'
         + (f'<span class="lh-status lh-status--neutral">{clean(a["status"])}</span>' if a["status"] else "")
         + f'</span>{_aw_info(a, icon) if a.get("info") else ""}</div>']
    if a["none"] and not a["rows"]:
        o.append(f'<p class="v2-p">{clean(a["none"])}</p>')
    for r in a["rows"]:
        t = r["team"]
        cls = f' {t["cls"]}' if t else ""
        who = _chip(t) if t else f'<b class="v2-name14">{clean(r["m"])}</b>'
        o.append(f'<div class="v2-lg-row{cls}"><span class="lh-rank__n">{clean(r["rank"])}</span>'
                 f'<span class="v2-minw">{who}<span class="v2-aw-shown">{clean(r["shown"])}</span>'
                 + (f'<span class="lh-sub">{clean(r["sub"])}</span>' if r["sub"] else "") + '</span>'
                 f'<span class="v2-lg-right"><span class="v2-lg-val">{clean(r["value"])}</span>'
                 f'<span class="lh-sub">{clean(a["unit"])}</span></span></div>')
    p = a.get("past")
    if p and p.get("rows"):
        o.append(f'<details class="v2-lg-group"><summary class="v2-lg-sum"><span>Past winners</span>'
                 f'<span>{clean(p["rows"][0]["season"])} back to {clean(p["rows"][-1]["season"])}</span></summary>')
        for r in p["rows"]:
            if r["none"]:
                o.append(f'<div class="v2-mg-past"><span class="v2-lg-wkn">{clean(r["season"])}</span>'
                         f'<span class="lh-sub">{clean(r["none"])}</span><span></span></div>')
                continue
            who = " ".join(_chip(t) for t in r["teams"]) or clean(", ".join(r["ms"]))
            o.append(f'<div class="v2-mg-past"><span class="v2-lg-wkn">{clean(r["season"])}</span>'
                     f'<span class="v2-minw">{who}<span class="v2-aw-shown">{clean(r["shown"])}</span>'
                     + (f'<span class="lh-sub">{clean(r["sub"])}</span>' if r["sub"] else "") + '</span>'
                     f'<span class="v2-lg-right"><span class="v2-lg-val">{clean(r["value"])}</span>'
                     f'<span class="lh-sub">{clean(r["unit"])}</span></span></div>')
        o.append("</details>")
    o.append("</section>")
    return "".join(o)


def _potw_past(rows: list) -> str:
    """4c7: Player of the Week by past season (most wins, best winning week)."""
    if not rows:
        return ""
    o = [f'<details class="v2-lg-group"><summary class="v2-lg-sum"><span>Past seasons</span>'
         f'<span>{clean(rows[0]["season"])} back to {clean(rows[-1]["season"])}</span></summary>']
    for x in rows:
        most = ", ".join(_name(w["player"], w["href"], True) + " " + " ".join(_chip(t) for t in w["teams"])
                         for w in x["most"])
        wins = x["most"][0]["wins"] if x["most"] else ""
        o.append(f'<div class="v2-mg-past"><span class="v2-lg-wkn">{clean(x["season"])}</span>'
                 f'<span class="v2-minw"><span class="lh-sub">Most wins</span>{most}</span>'
                 f'<span class="v2-lg-right"><span class="v2-lg-val">{clean(wins)}</span>'
                 f'<span class="lh-sub">of {clean(x["weeks"])} weeks</span></span></div>')
        b = x["best"]
        if b:
            o.append(f'<div class="v2-mg-past"><span class="v2-lg-wkn"></span>'
                     f'<span class="v2-minw"><span class="lh-sub">Best week</span>{_name(b["player"], b["href"], True)}'
                     f'<span class="lh-sub">{(_chip(b["team"]) + " ") if b["team"] else ""}{clean(b["sub"])}</span></span>'
                     f'<span class="v2-lg-right"><span class="v2-lg-val">{clean(b["pts"])}</span>'
                     f'<span class="lh-sub">pts</span></span></div>')
    o.append("</details>")
    return "".join(o)


def awards_html(aw: dict, mono, chart, icon: str, season_refs: dict = None) -> str:
    """League > Awards (4c5): one section per award (name, Live/Final, its
    InfoTip; the top rows with the shown-with figures and the move; "new
    leader"; the race chart), then Player of the Week by season. Rendered at
    build time: a <template> in the preview, an encrypted part when published."""
    o = []
    if aw.get("races_error"):
        o.append(f'<section class="lh-card"><h2 class="lh-eyebrow">Awards</h2>'
                 f'<p class="v2-aw-err">{clean(aw["races_error"])}</p></section>')
    for a in aw.get("races") or []:
        o.append(_race(a, mono, chart, icon))
    if aw.get("races"):
        o.append(f'<span class="lh-sub">{clean(aw["par_note"])} {clean(aw["races_note"])}</span>')
    past = aw.get("past") or {}
    if past.get("note") or past.get("error"):
        o.append(f'<span class="lh-sub">{clean(past.get("error") or past["note"])}</span>')
    if aw.get("managers") or aw.get("managers_error"):       # 4c7 C: the manager awards
        o.append('<h2 class="lh-eyebrow v2-pad" data-section="mgr-awards">Manager awards</h2>')
        if aw.get("managers_error"):
            o.append(f'<section class="lh-card"><p class="v2-aw-err">{clean(aw["managers_error"])}</p></section>')
        for a in aw.get("managers") or []:
            o.append(_mgr_award(a, icon))
        o.append(f'<span class="lh-sub">{clean(aw.get("managers_note") or "")}</span>')
    o.append('<section class="lh-card v2-gap8" data-section="potw"><div class="lh-sechead">'
             '<h2 class="lh-eyebrow">Player of the Week</h2></div>')
    with_rows = [x for x in aw["potw"] if x["rows"]]
    seasons = [x["season"] for x in with_rows]
    default, note = spick_default(seasons, aw.get("potw_current") or "", "Player of the week")
    if seasons:                                      # 5d1 s.8: one season at a time
        o.append(_spick("potw", seasons, default, note, "Player of the week season"))
    for x in with_rows:
        o.append(_spane("potw", x["season"], default, (season_refs or {}).get(x["season"]),
                        lambda x=x: potw_season_html(x)))
    o.append(_potw_past(aw.get("potw_past") or []))
    o.append(f'<span class="lh-sub">{clean(aw["potw_note"])}</span></section>')
    return "".join(o)


def potw_season_html(s: dict) -> str:
    """One season's Players of the week, newest week first."""
    o = [f'<div class="v2-lg-wk"><span class="lh-label">{clean(s["season"])}</span>']
    for r in s["rows"]:
        t = r["team"]
        sub = (_chip(t) if t else "")
        o.append(f'<div class="v2-lg-row"><span class="v2-lg-wkn">{clean(r["week"])}</span>'
                 f'<span class="v2-minw">{_name(r["player"], r["href"], True)}'
                 f'<span class="lh-sub">{sub}</span></span><span class="v2-lg-right">'
                 f'<span class="v2-lg-val">{clean(r["pts"])}</span><span class="lh-sub">{clean(r["sub"])}</span>'
                 "</span></div>")
    o.append("</div>")
    return "".join(o)


def _awards_pane(lg: dict, mode: str) -> str:
    """The Awards segment's lazy pane: its encrypted part's ref (publish) or
    the preview's template, loaded on the segment's first show."""
    ref = (lg.get("parts") or {}).get("awards")
    have = bool(ref) if mode == "publish" else bool(lg.get("awards_html"))
    msg = "Loading the awards&hellip;" if have else "The awards are not in this build."
    attr = f" data-part='{clean(json.dumps(ref, separators=(',', ':')))}'" if (mode == "publish" and ref) else ""
    return f'<div class="v2-lg-hist" data-lhpart-of="awards"{attr}><p class="v2-lg-load">{msg}</p></div>'


def _archive(ar: dict, doc: str, chev: str) -> str:
    o = ['<section class="lh-card v2-gap8" data-section="archive"><div class="lh-sechead">'
         '<h2 class="lh-eyebrow">Newsletter archive</h2></div>']
    if not ar["issues"]:
        o.append(f'<p class="v2-p">{clean(ar["empty"])}</p>')
    o.append('<div class="v2-mk-list">')
    for i in ar["issues"]:
        k, v = i["attr"]
        head = f'<span class="lh-sub">{clean(i["headline"])}</span>' if i["headline"] else ""
        o.append(f'<button type="button" class="v2-lg-issue" {k}="{clean(v)}" '
                 f'aria-label="Open the week {clean(i["week"])} issue"><span class="v2-lg-iwk">{clean(i["week"])}</span>'
                 f'<span class="v2-minw"><b class="v2-name14">{clean(i["label"])}</b>{head}'
                 f'<span class="lh-sub">{clean(i["size"])}</span></span>{chev}</button>')
    o.append(f'</div><span class="lh-sub">{clean(ar["note"])}</span></section>')
    return "".join(o)


# =============================================================================
# History: one chip's HTML (inline in preview, an encrypted file when published)
# =============================================================================

def _champions(c: dict, mono) -> str:
    o = ['<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Champions</h2>'
         f'<span class="lh-meta">{clean(c["meta"])}</span></div><div class="v2-mk-list">']
    for r in c["rows"]:
        t = r["team"]
        head = (f'{mono(t, "28")}' if t else '<span></span>')
        # 5c: the season's team name (a string); a season before the Yahoo
        # data has no team name on record, so the manager is the title alone
        title = ("" if not t else
                 f'<b class="v2-name14">{clean(r["season_team"])}</b><span class="lh-sub">{clean(r["who"])}</span>'
                 if r["season_team"] else f'<b class="v2-name14">{clean(r["who"])}</b>')
        lines = "".join(f'<span class="v2-lg-line"><b>{clean(x["k"])}:</b> {clean(x["t"])}</span>' for x in r["lines"])
        o.append(f'<div class="v2-lg-champ">{head}<span class="v2-minw"><span class="v2-lg-season">'
                 f'{clean(r["season"])}</span>{title}{lines}</span></div>')
    o.append(f'</div><span class="lh-sub">{clean(c["note"])}</span></section>')
    return "".join(o)


def _alltime(a: dict, mono) -> str:
    o = ['<section class="lh-card lh-card--flush"><div class="lh-sechead v2-pad"><h2 class="lh-eyebrow">All-time standings'
         f'</h2><span class="lh-meta">{clean(a["meta"])}</span></div><div class="v2-scroll"><table class="lh-table v2-lg-st">'
         "<thead><tr>" + "".join(f'<th>{colh_btn("alltime", k, lab)}</th>' for k, lab in (
             ("team", "Team"), ("wl", "W-L"), ("pf", "PF"), ("titles", "Titles"), ("playoff", "Playoff")))
         + "</tr></thead><tbody>"]
    for r in a["rows"]:
        o.append(f'<tr><td><span class="v2-lg-team"><span class="v2-lg-rank">{clean(r["rank"])}</span>'
                 + _mgr(r["team"], mono, "Playoffs " + r["post"]) + "</span></td>"
                 f'<td class="lh-num">{clean(r["record"])}<span class="lh-sub v2-lg-blk">{clean(r["pct"])}</span></td>'
                 f'<td class="lh-num">{clean(r["pf"])}</td><td class="lh-num">{clean(r["titles"])}</td>'
                 f'<td class="lh-num">{clean(r["playoff_titles"])}</td></tr>')
    o.append(f'</tbody></table></div><div class="lh-table-note">{clean(a["note"])}</div></section>')
    o.append(_trophy(a.get("trophy")))
    return "".join(o)


def _trophy(tc) -> str:
    """4c7 B: the trophy case, one row per manager (trophy_case.build); a
    count taps open its seasons; Bust and Unluckiest are muted, apart."""
    if not tc:
        return ""
    o = ['<section class="lh-card lh-card--flush" data-section="trophy"><div class="lh-sechead v2-pad">'
         '<h2 class="lh-eyebrow">Trophy case</h2></div>']
    if tc.get("error") and not tc.get("rows"):
        o.append(f'<p class="v2-p v2-pad">{clean(tc["error"])}</p></section>')
        return "".join(o)
    o.append('<div class="v2-scroll"><table class="lh-table v2-tro"><thead><tr>'
             f'<th>{colh_btn("trophy", "team", "Manager")}</th>'
             + "".join(('<th class="v2-tro-apart">' if k in ("bust", "unlucky") else "<th>")
                       + colh_btn("trophy", k, clean(lab)) + "</th>" for k, lab in tc["cols"])
             + "</tr></thead><tbody>")
    for r in tc["rows"]:
        o.append(f'<tr><td>{_chip(r["team"])}</td>')
        for c in r["cells"]:
            cls = ' class="v2-tro-apart"' if c["apart"] else ""
            if c["tip"]:
                o.append(f'<td{cls}><button type="button" class="v2-tro-n v2-tap"{_tip(c["tip"])} '
                         f'aria-label="{clean(c["tip"]["h"])}: {clean(c["n"])}. Tap for the seasons.">'
                         f'{clean(c["n"])}</button></td>')
            else:
                o.append(f'<td{cls}><span class="v2-tro-z">{clean(c["n"])}</span></td>')
        o.append("</tr>")
    o.append(f'</tbody></table></div><div class="lh-table-note">{clean(tc["note"])}'
             + (f' {clean(tc["error"])}' if tc.get("error") else "") + "</div></section>")
    return "".join(o)


def _h2h(h: dict, mono) -> str:
    n = str(len(h["cols"]))
    o = ['<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Head to head</h2></div>'
         '<div class="v2-fchips" role="group" aria-label="Phase">']
    for i, (k, lab) in enumerate(h["phases"]):
        o.append(f'<button type="button" class="v2-fchip" data-lhphase="{k}" aria-pressed="{"true" if i == 0 else "false"}">'
                 f'{clean(lab)}</button>')
    o.append("</div>")
    for i, (k, lab) in enumerate(h["phases"]):
        o.append(f'<div class="v2-lg-h2h" data-lhphase-of="{k}" style="--n:{n}" role="table" '
                 f'aria-label="{clean(lab)}: each row against each column"{"" if i == 0 else " hidden"}>'
                 '<span role="columnheader"></span>'
                 + "".join(f'<span class="v2-lg-hh" role="columnheader" aria-label="{clean(t["manager"])}">'
                           f'{mono(t, "28")}</span>' for t in h["cols"]))
        for r in h["grid"][k]:
            o.append(f'<a class="v2-lg-team v2-tap" href="{r["team"]["href"]}" role="rowheader" '
                     f'aria-label="{clean(r["team"]["manager"])}">{mono(r["team"], "28")}</a>')
            for c, t in zip(r["cells"], h["cols"]):
                if c is None:
                    o.append('<span class="v2-lg-diag" aria-hidden="true">&mdash;</span>')
                    continue
                o.append(f'<button type="button" class="v2-lg-cell" data-lhpair="{clean(c["key"])}" aria-expanded="false" '
                         f'aria-label="{clean(r["team"]["manager"])} against {clean(t["manager"])}, {clean(lab)}: '
                         f'{clean(c["t"])}. Tap for each season.">{clean(c["t"])}</button>')
        o.append("</div>")
    for key, p in h["pairs"].items():
        o.append(f'<div class="v2-lg-pair" data-lhpair-of="{clean(key)}" hidden><b class="v2-name14">{clean(p["title"])}</b>'
                 f'<span class="lh-sub">{clean(p["total"])}</span>'
                 + "".join(f'<span class="v2-lg-pl"><span>{clean(x["season"])}</span><span>{clean(x["t"])}</span></span>'
                           for x in p["lines"]) + "</div>")
    o.append(f'<span class="lh-sub">{clean(h["note"])}</span></section>')
    return "".join(o)


def _tiles(tiles: list) -> str:
    o = ['<div class="lh-kpis v2-lg-tiles">']
    for t in tiles:
        inner = (f'<span class="lh-label">{clean(t["label"])}</span><span class="lh-kpi__value">{clean(t["value"])}</span>'
                 f'<span class="lh-kpi__ctx">{clean(t["who"])} &middot; {clean(t["ctx"])}</span>')
        o.append(f'<div class="lh-kpi"><button type="button" class="v2-lg-tile"{_tip(t["tip"])} '
                 f'aria-label="{clean(t["label"])}: {clean(t["value"])}, {clean(t["who"])}, {clean(t["ctx"])}. '
                 f'Tap for more.">{inner}</button></div>')
    o.append("</div>")
    return "".join(o)


def _records(r: dict) -> str:
    o = ['<div class="lh-kpis v2-lg-tiles">']
    for t in r["tiles"]:
        inner = (f'<span class="lh-label">{clean(t["label"])}</span><span class="lh-kpi__value">{clean(t["value"])}</span>'
                 f'<span class="lh-kpi__ctx">{clean(t["who"])} &middot; {clean(t["ctx"])}</span>')
        if t["tip"]:
            o.append(f'<div class="lh-kpi"><button type="button" class="v2-lg-tile"{_tip(t["tip"])} '
                     f'aria-label="{clean(t["label"])}: {clean(t["value"])}, {clean(t["who"])}. Tap for the game.">'
                     f"{inner}</button></div>")
        else:
            o.append(f'<div class="lh-kpi">{inner}</div>')
    o.append("</div>")
    for g in r["groups"]:
        o.append(f'<section class="lh-card v2-lg-group"><h2 class="lh-eyebrow">{clean(g["label"])}</h2>')
        for lst in g["lists"]:
            top = lst["rows"][0]
            o.append(f'<details><summary class="v2-lg-sum"><span>{clean(lst["label"])}</span>'
                     f'<span>{clean(top["value"])}</span></summary>')
            for x in lst["rows"]:
                val = f'<span class="v2-lg-val">{clean(x["value"])}</span>'
                if x["tip"]:
                    val = (f'<button type="button" class="v2-lg-game"{_tip(x["tip"])} '
                           f'aria-label="{clean(lst["label"])} #{clean(x["rank"])}: {clean(x["value"])}. Tap for the game.">'
                           f"{val}</button>")
                who = (_name(x["who"], x["href"]) if x["player"] and x["href"] else f"<span>{clean(x['who'])}</span>")
                o.append(f'<div class="v2-lg-rec"><span class="v2-lg-n">{clean(x["rank"])}</span><span class="v2-lg-who">'
                         f'{who}<span class="lh-sub">{clean(x["ctx"])}</span></span>{val}</div>')
            o.append("</details>")
        o.append("</section>")
    if r.get("award_tiles") or r.get("award_note"):          # 4c6: the awards' best seasons
        o.append('<section class="lh-card v2-gap8" data-section="award-records"><h2 class="lh-eyebrow">Awards</h2>'
                 + (_tiles(r["award_tiles"]) if r.get("award_tiles") else "")
                 + f'<span class="lh-sub">{clean(r.get("award_note") or "")}</span></section>')
    o.append(f'<span class="lh-sub">{clean(r["note"])}</span>')
    return "".join(o)


def _draft(d: dict, refs: dict = None) -> str:
    """History > Draft: the season picker (5d1 s.8) over one pane per draft;
    refs {season: part ref}: published, a past season is its own part."""
    by = {x["season"]: x for x in d["seasons"]}
    o = [_spick("draft", list(by), d["default"], "", "Draft season")]
    for x in d["seasons"]:
        o.append(_spane("draft", x["season"], d["default"], (refs or {}).get(x["season"]),
                        lambda x=x: draft_season_html(x)))
    o.append(f'<span class="lh-sub">{clean(d["note"])}</span>')
    return "".join(o)


def draft_season_html(s: dict) -> str:
    """One draft's section (H56: numbered, by team, or dropped)."""
    mode = s.get("mode", "order")
    o = []
    o.append(f'<section class="lh-card lh-card--flush"><div class="lh-sechead v2-pad">'
             f'<h2 class="lh-eyebrow">{clean(s["season"])} draft</h2><span class="lh-meta">{clean(s["meta"])}</span>'
             '</div>')
    if mode == "dropped":                         # H56: 2018-19's list doesn't match the rosters
        o.append(f'<p class="v2-p v2-pad">{clean(s["order_note"])}</p></section>')
        return "".join(o)
    if mode == "by_team":                         # H56: the order is punted; each team's class
        o.append(f'<p class="lh-sub v2-pad">{clean(s["order_note"])}</p>'
                 '<div class="v2-scroll"><table class="lh-table v2-lg-dr v2-lg-dr--team"><thead><tr>'
                 f'<th>{colh_btn("draft", "player", "Player")}</th><th>{colh_btn("draft", "then", "Then")}</th>'
                 f'<th>{colh_btn("draft", s["later_label"].lower(), clean(s["later_label"]))}</th></tr></thead><tbody>')
        last = None
        for r in s["rows"]:
            if r["m"] != last:
                t = r["team"]
                o.append(f'<tr class="v2-lg-dteam"><th colspan="3" scope="colgroup">'
                         f'{_chip(t) if t else clean(r["m"])}</th></tr>')
                last = r["m"]
            k = '<span class="v2-lg-k">K</span>' if r["keeper"] else ""
            chg = (f'<span class="v2-lg-chg v2-lg-chg--{r["dir"]}">{clean(r["chg"])}</span>' if r["chg"] else "")
            o.append(f'<tr><td>{_name(r["player"], r["href"], True)}{k}</td>'
                     f'<td class="lh-num">{_why(r["then"], r["player"], r["then_why"])}</td>'
                     f'<td class="lh-num">{_why(r["later"], r["player"], r["later_why"])}{chg}</td></tr>')
        o.append(f'</tbody></table></div><div class="lh-table-note">{clean(s["drafted"])}</div></section>')
        return "".join(o)
    o.append('<div class="v2-scroll"><table class="lh-table v2-lg-dr"><thead><tr>'
             f'<th>{colh_btn("draft", "pick", "Pick")}</th>'
             f'<th>{colh_btn("draft", "player", "Player")}</th><th>{colh_btn("draft", "then", "Then")}</th>'
             f'<th>{colh_btn("draft", s["later_label"].lower(), clean(s["later_label"]))}</th></tr></thead><tbody>')
    for r in s["rows"]:
        t = r["team"]
        team = _chip(t) if t else clean(r["m"])
        k = '<span class="v2-lg-k">K</span>' if r["keeper"] else ""
        chg = (f'<span class="v2-lg-chg v2-lg-chg--{r["dir"]}">{clean(r["chg"])}</span>' if r["chg"] else "")
        o.append(f'<tr><td class="lh-num">{clean(r["pick"])}{k}</td><td>{_name(r["player"], r["href"], True)}'
                 f'<span class="lh-sub">{team}</span></td>'
                 f'<td class="lh-num">{_why(r["then"], r["player"], r["then_why"])}</td>'
                 f'<td class="lh-num">{_why(r["later"], r["player"], r["later_why"])}{chg}</td></tr>')
    o.append(f'</tbody></table></div><div class="lh-table-note">{clean(s["drafted"])}</div></section>')
    return "".join(o)


def _trades(tr: dict, refs: dict = None) -> str:
    """History > Trades: the season picker (5d1 s.8) over one pane per season
    with trades, newest first; refs {season: part ref}: published, a past
    season is its own part, opened when picked."""
    seasons = []
    for it in tr["items"]:                           # newest first already
        if it["season"] not in seasons:
            seasons.append(it["season"])
    o = ['<section class="lh-card v2-gap8"><div class="lh-sechead"><h2 class="lh-eyebrow">Trades</h2>'
         f'<span class="lh-meta">{clean(tr["count"])}</span></div>']
    if not tr["items"]:
        o.append(f'<p class="v2-p">{clean(tr["empty"])}</p>')
    else:
        default, note = spick_default(seasons, tr.get("current") or "", "trade")
        o.append(_spick("trades", seasons, default, note, "Trades season"))
        for se in seasons:
            o.append(_spane("trades", se, default, (refs or {}).get(se), lambda se=se: trades_season_html(tr, se)))
    o.append(f'<span class="lh-sub">{clean(tr["note"])}</span></section>')
    return "".join(o)


def trades_season_html(tr: dict, season: str) -> str:
    """One season's trades, newest first."""
    o = ['<div class="v2-mk-list">']
    for it in tr["items"]:
        if it["season"] != season:
            continue
        o.append(f'<div class="v2-lg-trade"><span class="lh-sub">{clean(it["date"])} &middot; {clean(it["season"])}</span>'
                 f'<span class="v2-lg-th">{_chip(it["teams"][0])} &#8644; {_chip(it["teams"][1])}</span>')
        for sd in it["sides"]:
            gets = ", ".join(_name(g["t"], g["href"]) for g in sd["gets"]) or "nothing recorded"
            o.append(f'<span class="v2-lg-side"><b>{clean(sd["m"])} gets:</b> {gets}</span>')
        if it.get("ruling"):
            o.append(f'<span class="lh-sub">{clean(it["ruling"])}</span>')
        o.append("</div>")
    o.append("</div>")
    return "".join(o)


# =============================================================================
# 5d1 s.8 (Nick, 11-20): a season picker on the lists that grow every season
# (Player of the week, History > Trades, History > Draft). The current season
# shows by default; before it has an entry (week 1), the latest season with
# entries, and the picker says so. The season is in the route (?s=, and the
# draft's /<season>), so the back button and a shared link work. Published,
# each past season is its own encrypted part, opened only when picked
# (past_seasons), so the first load doesn't grow with the years.
# =============================================================================

SEASONAL = ("draft", "trades")                       # History chips with a season picker (and Awards' potw)


def spick_default(seasons: list, current: str, what: str) -> tuple:
    """(the season shown first, the picker's note): the current season when
    it has an entry, else the newest that has, saying so."""
    if not seasons:
        return "", ""
    if current in seasons:
        return current, ""
    return seasons[0], f"No {what} in {current} yet: showing {seasons[0]}."


def _spick(key: str, seasons: list, default: str, note: str, aria: str) -> str:
    o = [f'<div class="v2-lg-dsel"><label class="v2-fchip v2-spick">Season<select data-spick="{clean(key)}" '
         f'aria-label="{clean(aria)}">']
    for se in seasons:
        o.append(f'<option value="{clean(se)}"{" selected" if se == default else ""}>{clean(se)}</option>')
    o.append("</select></label>")
    if note:
        o.append(f'<span class="lh-sub v2-spick-note">{clean(note)}</span>')
    o.append("</div>")
    return "".join(o)


def _spane(key: str, season: str, default: str, ref, html_fn) -> str:
    """One season's pane: inline, or (a published past season) its part's ref
    and a loading line, filled when it is picked."""
    hid = "" if season == default else " hidden"
    attr = f'data-spick-of="{clean(key)}|{clean(season)}"'
    if ref is not None and season != default:
        return (f'<div {attr} data-part=\'{clean(json.dumps(ref, separators=(",", ":")))}\'{hid}>'
                '<p class="v2-lg-load">Loading the season&hellip;</p></div>')
    return f'<div {attr}{hid}>{html_fn()}</div>'


def past_seasons(model: dict, which: str) -> dict:
    """{season: its pane's HTML} for every season but the default one, of
    "draft", "trades" (History) or "potw" (Awards): publish seals each."""
    if which == "draft":
        return {x["season"]: draft_season_html(x) for x in model["seasons"] if x["season"] != model["default"]}
    if which == "trades":
        seasons = list(dict.fromkeys(it["season"] for it in model["items"]))
        default, _n = spick_default(seasons, model.get("current") or "", "trade")
        return {se: trades_season_html(model, se) for se in seasons if se != default}
    if which == "potw":
        seasons = [x["season"] for x in model["potw"] if x["rows"]]
        default, _n = spick_default(seasons, model.get("potw_current") or "", "Player of the week")
        return {x["season"]: potw_season_html(x) for x in model["potw"] if x["rows"] and x["season"] != default}
    raise ValueError(f"no season picker {which!r}")


def chip_html(h: dict, chip: str, mono, season_refs: dict = None) -> str:
    """One History chip's HTML, from view.league_history's model. 5d1:
    season_refs {season: part ref} for a SEASONAL chip, published."""
    if chip == "champions":
        return _champions(h["champions"], mono)
    if chip == "alltime":
        return _alltime(h["alltime"], mono)
    if chip == "h2h":
        return _h2h(h["h2h"], mono)
    if chip == "records":
        return _records(h["records"])
    if chip == "draft":
        return _draft(h["draft"], season_refs)
    if chip == "trades":
        return _trades(h["trades"], season_refs)
    raise ValueError(f"no History chip {chip!r}")


def _history(lg: dict, mode: str) -> str:
    chips = lg["chips"]
    o = ['<div class="v2-lg-chips" role="group" aria-label="History">']
    for i, (k, lab) in enumerate(chips):
        o.append(f'<button type="button" class="v2-fchip" data-lhchip="{k}" aria-pressed="{"true" if i == 0 else "false"}">'
                 f"{clean(lab)}</button>")
    o.append("</div>")
    parts = lg.get("parts") or {}
    have = bool(parts) if mode == "publish" else bool(lg.get("history"))
    msg = ("Loading this part of the history&hellip;" if have else
           "The history is not in this build: its file was not built with this page.")
    for i, (k, _lab) in enumerate(chips):
        ref = parts.get(k)
        attr = f" data-part='{clean(json.dumps(ref, separators=(',', ':')))}'" if (mode == "publish" and ref) else ""
        o.append(f'<div class="v2-lg-hist" data-lhchip-of="{k}"{attr}{"" if i == 0 else " hidden"}>'
                 f'<p class="v2-lg-load">{msg}</p></div>')
    return "".join(o)


def templates(lg: dict, mono) -> str:
    """The preview's History, every chip's HTML in a <template>, and the
    Awards segment's (plaintext, this machine only); the published page never
    carries them."""
    out = ""
    if lg.get("awards_html"):
        out += f'<template id="v2-lg-awards">{lg["awards_html"]}</template>'
    h = lg.get("history")
    if not h:
        return out
    return out + "".join(f'<template id="v2-lg-{k}">{chip_html(h, k, mono)}</template>' for k, _lab in h["chips"])


def league_screen(vm: dict, ids, info, mono, chart, doc: str, chev: str) -> str:
    lg = vm["league"]
    o = ['<section class="v2-screen" data-route="league" hidden><div class="v2-stack"><div class="v2-sec">',
         '<div class="lh-seg" role="tablist" data-seg="league">']
    for i, (k, lab) in enumerate(lg["segs"]):
        o.append(f'<button type="button" role="tab" data-pane="{k}" aria-selected="{"true" if i == 0 else "false"}">'
                 f"{clean(lab)}</button>")
    o.append("</div>")
    o.append('<div class="v2-lg-pane" data-pane-of="standings">' + _standings(lg, ids, info, mono, chart) + "</div>")
    o.append('<div class="v2-lg-pane" data-pane-of="history" hidden>' + _history(lg, vm["mode"]) + "</div>")
    o.append('<div class="v2-lg-pane" data-pane-of="awards" hidden>' + _awards_pane(lg, vm["mode"]) + "</div>")
    o.append('<div class="v2-lg-pane" data-pane-of="archive" hidden>' + _archive(lg["archive"], doc, chev) + "</div>")
    o.append("</div></div></section>")
    return "".join(o)
