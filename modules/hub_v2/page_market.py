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

from .text import clean, colh, colh_btn

TAP_CLASSES = ("adv-row", "adv-bk", "adv-crow", "adv-days", "adv-wchip", "v2-mkcell", "v2-mvchip")
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
.adv-tl{display:flex;align-items:center;justify-content:space-between;gap:var(--space-4)}
.adv-tinfo button{min-width:var(--tap-min);min-height:var(--tap-min);margin:calc(-1 * var(--space-12)) calc(-1 * var(--space-12)) calc(-1 * var(--space-12)) 0}
.adv-tsub{font-size:var(--type-small-size);color:var(--ink-3);line-height:1.25;overflow-wrap:anywhere}
.adv-pick{display:flex;flex-direction:column;gap:var(--space-6);min-width:0}
.adv-pick-h{display:flex;align-items:center;justify-content:space-between;padding:0 var(--space-2)}
.adv-chips{display:flex;gap:var(--space-8);overflow-x:auto;scrollbar-width:none;padding:var(--space-2);margin:0 calc(-1 * var(--space-2));min-width:0}
.adv-chips::-webkit-scrollbar{display:none}
.adv-chip{flex:0 0 auto;white-space:nowrap;cursor:pointer;min-width:var(--tap-min);justify-content:center}
.adv-wk[data-on]{background:var(--dark);border-color:var(--dark);color:var(--ink-on-dark)}
.adv-wk[data-on] select{color:var(--ink-on-dark)}
[data-goal-pane]{display:flex;flex-direction:column;gap:var(--space-20);min-width:0}
[data-goal-pane][hidden]{display:none}
.adv-gfoot{display:flex;flex-direction:column;gap:var(--space-6);padding:var(--space-8) var(--space-14) var(--space-14)}
.adv-cost{background:var(--surface);border:var(--hairline) solid var(--line-soft);border-radius:var(--radius-12);overflow:hidden}
.adv-cost-h{display:flex;align-items:baseline;gap:var(--space-8);padding:var(--space-8) var(--space-10) var(--space-4)}
.adv-crow{all:unset;box-sizing:border-box;width:100%;display:grid;grid-template-columns:auto minmax(0,1fr) var(--space-14);gap:var(--space-12);align-items:center;min-height:var(--tap-min);padding:var(--space-6) var(--space-10);border-top:var(--hairline) solid var(--line-soft);font-size:var(--type-body-size);color:var(--ink)}
.adv-crow--btn{cursor:pointer}
.adv-crow--btn[aria-expanded="true"] .adv-chev{transform:rotate(90deg)}
.adv-cv{font-weight:700;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.adv-strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:var(--space-4);padding:var(--space-6) var(--space-10) var(--space-10)}
.adv-strip[hidden]{display:none}
.adv-sc{display:flex;flex-direction:column;align-items:center;gap:var(--space-2);background:var(--surface-subtle);border-radius:var(--radius-9);padding:var(--space-6) var(--space-2)}
.adv-ssub{font-size:var(--type-label-size);color:var(--ink-3)}
.adv-asof{font-size:var(--type-small-size);font-weight:700;color:var(--ink-3)}
/* AC1: the card around days. The strip taps as ONE control (.adv-days, the
   whole grid, 44 points and up) with its own day readout (.adv-dayl): a box is
   too narrow for 44 points across at 360 px. Rest of season's week chips are
   44-point buttons each. */
.adv-games{display:flex;flex-direction:column;gap:var(--space-4)}
.adv-gh{display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-8)}
.adv-gt{font-family:var(--font-display);font-size:var(--type-display-sm-size);font-weight:700;color:var(--ink-strong);font-variant-numeric:tabular-nums}
.adv-wl{font-size:var(--type-small-size);font-weight:700;color:var(--ink-2);padding-top:var(--space-4)}
.adv-days{all:unset;box-sizing:border-box;cursor:pointer;width:100%;min-height:var(--tap-min);display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:var(--space-2)}
.adv-days:focus-visible,.adv-wchip:focus-visible{outline:var(--hairline) solid var(--accent);outline-offset:var(--space-2)}
.adv-dh{font-size:var(--type-label-size);font-weight:800;color:var(--ink-3);text-align:center}
.adv-dy{display:flex;flex-direction:column;align-items:center;gap:var(--hairline);border-radius:var(--radius-6);padding:var(--space-2) 0;background:var(--surface);box-shadow:inset 0 0 0 var(--hairline) var(--line);min-width:0}
.adv-dd{font-size:var(--type-label-size);color:var(--ink-3)}
.adv-dn{font-family:var(--font-display);font-size:var(--type-heading-size);font-weight:700;color:var(--ink);font-variant-numeric:tabular-nums;line-height:1}
.adv-dm{font-size:var(--type-label-size);font-weight:800;color:var(--ink-3)}
.adv-dy--up{box-shadow:inset 0 0 0 var(--space-2) var(--up)}
.adv-dy--up .adv-dm{color:var(--up)}
.adv-dy--down{box-shadow:inset 0 0 0 var(--space-2) var(--down)}
.adv-dy--down .adv-dm{color:var(--down)}
.adv-dy--full{background:var(--surface-sunken);box-shadow:none}
.adv-dy--off{background:transparent;box-shadow:none}
.adv-dy--off .adv-dn{color:var(--ink-3)}
.adv-dy[data-on]{outline:var(--hairline) solid var(--ink-strong);outline-offset:var(--hairline)}
.adv-c1{grid-column-start:2}.adv-c2{grid-column-start:3}.adv-c3{grid-column-start:4}.adv-c4{grid-column-start:5}.adv-c5{grid-column-start:6}.adv-c6{grid-column-start:7}
.adv-dayl{margin:0;min-height:calc(var(--type-small-size) * 2.7);font-size:var(--type-small-size);line-height:1.35;color:var(--ink-2)}
.adv-wchips{display:flex;flex-wrap:wrap;gap:var(--space-4)}
.adv-wchip{all:unset;box-sizing:border-box;cursor:pointer;min-width:var(--tap-min);min-height:var(--tap-min);display:inline-flex;flex-direction:column;align-items:center;justify-content:center;border-radius:var(--radius-9);background:var(--surface);box-shadow:inset 0 0 0 var(--hairline) var(--line);padding:var(--space-2) var(--space-6)}
.adv-wchip[aria-expanded="true"]{box-shadow:inset 0 0 0 var(--space-2) var(--ink-strong)}
.adv-wchip .adv-v{font-size:var(--type-heading-size)}
.adv-wblk{display:flex;flex-direction:column;gap:var(--space-4)}
.adv-wblk[hidden]{display:none}
.adv-depth{font-size:var(--type-body-size);font-weight:700;color:var(--ink)}
.adv-foot{display:flex;flex-direction:column;gap:var(--space-2);font-size:var(--type-small-size);color:var(--ink-2)}
.adv-tagc{display:inline-flex;align-items:center;font-size:var(--type-label-size);font-weight:800;color:var(--ink-2);background:var(--surface-sunken);border-radius:var(--radius-pill);padding:0 var(--space-4);white-space:nowrap}
.adv-tagc--out{color:var(--status-out);background:var(--status-out-tint)}
.adv-tagc--q{color:var(--status-q);background:var(--status-q-tint)}
.adv-trows{display:grid;grid-template-columns:auto auto;justify-content:start;column-gap:var(--space-6);align-items:baseline}
.adv-trows .adv-l{font-size:var(--type-small-size);font-weight:700;color:var(--ink-3)}
.adv-trows .adv-v{font-size:var(--type-heading-size)}
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
// 5d2 s.4: the range picker (the route carries it: #/market?r=next) and
// Team > Schedule's link (?fit=<manager>: his games on that team's empty-slot days)
MK.r='';MK.fit='';
function mkTable(){var b=document.querySelector('[data-section="available"] [data-mkrange]:not([hidden]) table');return b;}
function mkFilter(){
  var tbs=document.querySelectorAll('[data-section="available"] table[data-mkt]'),any=false;
  for(var b=0;b<tbs.length;b++){var vis=!tbs[b].closest('[data-mkrange]').hidden;
    var trs=tbs[b].querySelectorAll('tbody tr[data-i]');
    for(var i=0;i<trs.length;i++){var t=trs[i],ok=true;
      if(MK.pos&&(' '+t.getAttribute('data-pos')+' ').indexOf(' '+MK.pos+' ')<0){ok=false;}
      if(MK.h&&t.getAttribute('data-h')!=='1'){ok=false;}
      if(MK.fit&&(' '+t.getAttribute('data-fit')+' ').indexOf(' '+MK.fit+' ')<0){ok=false;}
      if(MK.light&&VIEWER&&(' '+(t.getAttribute('data-light')||'')+' ').indexOf(' '+VIEWER+' ')<0){ok=false;}
      t.hidden=!ok;if(ok&&vis){any=true;}}}
  var n=document.getElementById('mk-fa-none');if(n){n.hidden=any;}
  var f=document.querySelector('[data-mkfit]');if(f){f.hidden=!MK.fit;}
}
function mkRange(key,push){
  if(!key){return;}MK.r=key;
  var ss=document.querySelectorAll('[data-mkr]');for(var i=0;i<ss.length;i++){ss[i].value=key;}
  var bs=document.querySelectorAll('[data-route="market"] [data-mkrange]');
  for(var j=0;j<bs.length;j++){var b=bs[j],on=b.getAttribute('data-mkrange')===key;b.hidden=!on;
    if(on&&b.getAttribute('data-part')&&!b.getAttribute('data-loaded')&&window.HUB&&window.HUB.part){mkLoad(b);}}
  mkFilter();
  if(push){var q='?r='+key+(MK.fit?'&fit='+MK.fit:'');try{history.replaceState(null,'','#/market'+q);}catch(e){}}
}
function mkLoad(b){b.setAttribute('data-loaded','1');
  window.HUB.part(JSON.parse(b.getAttribute('data-part'))).then(function(p){b.innerHTML=p.html;mkFilter();},
    function(){b.innerHTML='<p class="v2-card-load v2-pad">This range could not be opened. Reload the page.</p>';});}
function mkRoute(){
  var h=location.hash;if(h.indexOf('#/market')!==0){return;}
  var qi=h.indexOf('?'),q={};
  if(qi>=0){h.slice(qi+1).split('&').forEach(function(kv){var p=kv.split('=');q[p[0]]=decodeURIComponent(p[1]||'');});}
  MK.fit=q.fit||'';
  if(q.r){mkRange(q.r,false);}else{mkFilter();}
}
window.addEventListener('hashchange',mkRoute);
document.addEventListener('hub:viewer',function(){mkFilter();});
setTimeout(mkRoute,0);
function mvFilter(m){
  MK.mv=m;
  var bs=document.querySelectorAll('[data-mvf]');
  for(var i=0;i<bs.length;i++){bs[i].setAttribute('aria-pressed',String(bs[i].getAttribute('data-mvf')===m));}
  var it=document.querySelectorAll('#mk-moves [data-ms]');
  for(var j=0;j<it.length;j++){it[j].hidden=!!m&&(' '+it[j].getAttribute('data-ms')+' ').indexOf(' '+m+' ')<0;}
}
// Advice goals (Part D): one picker for the page (Nick, 11-25: every card
// switches together); the goal is in the route (#/market?goal=week:12) and
// remembered for the session, like Market's range. A goal's cards are an
// encrypted part when published, opened on its chip's first tap.
MK.goal='';
function advGoal(key,push){
  var panes=document.querySelectorAll('[data-route="market"] [data-goal-pane]');if(!panes.length){return;}
  var has=false;for(var i=0;i<panes.length;i++){if(panes[i].getAttribute('data-goal-pane')===key){has=true;}}
  if(!key||!has){key='balanced';}
  MK.goal=key;
  for(var j=0;j<panes.length;j++){var b=panes[j],on=b.getAttribute('data-goal-pane')===key;b.hidden=!on;
    if(on&&b.getAttribute('data-part')&&!b.getAttribute('data-loaded')&&window.HUB&&window.HUB.part){advLoad(b);}}
  var cs=document.querySelectorAll('[data-goal]');for(var k=0;k<cs.length;k++){
    cs[k].setAttribute('aria-pressed',String(cs[k].getAttribute('data-goal')===key));}
  var wk=key.indexOf('week:')===0,sel=document.querySelector('[data-goalweek]');
  if(sel){sel.value=wk?key:'';var lab=sel.parentNode;
    if(wk){lab.setAttribute('data-on','');}else{lab.removeAttribute('data-on');}
    var l=lab.querySelector('[data-goalwk-l]');if(l){l.textContent=wk?'Wk '+key.slice(5):'A week';}}
  try{sessionStorage.setItem('hub.goal',key);}catch(e){}
  if(push){try{history.replaceState(null,'','#/market?goal='+encodeURIComponent(key));}catch(e){}}
}
function advLoad(b){b.setAttribute('data-loaded','1');b.innerHTML='<p class="v2-card-load v2-pad">Opening\u2026</p>';
  window.HUB.part(JSON.parse(b.getAttribute('data-part'))).then(function(p){b.innerHTML=p.html;},
    function(){b.innerHTML='<p class="v2-card-load v2-pad">This goal could not be opened. Reload the page.</p>';});}
function advRoute(){
  var h=location.hash;if(h.indexOf('#/market')!==0){return;}
  var qi=h.indexOf('?'),q={};
  if(qi>=0){h.slice(qi+1).split('&').forEach(function(kv){var p=kv.split('=');q[p[0]]=decodeURIComponent(p[1]||'');});}
  var g=q.goal;if(!g){try{g=sessionStorage.getItem('hub.goal')||'';}catch(e){g='';}}
  if(g){advGoal(g,false);}
}
window.addEventListener('hashchange',advRoute);
setTimeout(advRoute,0);
// AC1: a tap on the strip shows that day's line in the card's readout (the
// engine's line, carried on the box); a keyboard press steps to the next day.
// A week chip (Rest of season) opens its week's days and closes the others.
function advDay(btn,e){
  var out=document.getElementById(btn.getAttribute('data-out'));if(!out){return;}
  var box=e.target.closest?e.target.closest('.adv-dy'):null;
  var ds=btn.querySelectorAll('.adv-dy');
  if(!box||!btn.contains(box)){var cur=btn.querySelector('.adv-dy[data-on]'),i=-1;
    for(var k=0;k<ds.length;k++){if(ds[k]===cur){i=k;}}box=ds[(i+1)%ds.length];}
  var on=out.closest('.adv-games').querySelectorAll('.adv-dy[data-on]');
  for(var j=0;j<on.length;j++){on[j].removeAttribute('data-on');}
  if(box){box.setAttribute('data-on','');out.textContent=box.getAttribute('data-l');}
}
document.addEventListener('click',function(e){
  var t=e.target.closest('[data-days]');
  if(t){advDay(t,e);return;}
  t=e.target.closest('.adv-wchip[aria-controls]');
  if(t){var o0=t.getAttribute('aria-expanded')==='true',cs=t.parentNode.querySelectorAll('.adv-wchip');
    for(var c=0;c<cs.length;c++){cs[c].setAttribute('aria-expanded','false');
      var bb=document.getElementById(cs[c].getAttribute('aria-controls'));if(bb){bb.hidden=true;}}
    if(!o0){t.setAttribute('aria-expanded','true');document.getElementById(t.getAttribute('aria-controls')).hidden=false;}
    return;}
  t=e.target.closest('[data-goal]');
  if(t){advGoal(t.getAttribute('data-goal'),true);return;}
  t=e.target.closest('.adv-crow--btn[aria-controls]');
  if(t){var o=t.getAttribute('aria-expanded')==='true';t.setAttribute('aria-expanded',String(!o));
    document.getElementById(t.getAttribute('aria-controls')).hidden=o;return;}
  t=e.target.closest('.adv-row[aria-controls],.adv-bk[aria-controls]');
  if(t&&!e.target.closest('[data-card]')&&!e.target.closest('a')){
    var open=t.getAttribute('aria-expanded')==='true';t.setAttribute('aria-expanded',String(!open));
    document.getElementById(t.getAttribute('aria-controls')).hidden=open;return;}
  t=e.target.closest('[data-mkh]');
  if(t){var on=t.getAttribute('aria-pressed')!=='true';t.setAttribute('aria-pressed',String(on));MK.h=on?'1':'';mkFilter();return;}
  t=e.target.closest('[data-mklight]');
  if(t){var on2=t.getAttribute('aria-pressed')!=='true';t.setAttribute('aria-pressed',String(on2));
    MK.light=on2?'1':'';mkFilter();return;}
  t=e.target.closest('[data-mkfit]');
  if(t){MK.fit='';mkRange(MK.r||(document.querySelector('[data-mkr]')||{}).value,true);mkFilter();return;}
  t=e.target.closest('[data-mvf]');
  if(t){mvFilter(t.getAttribute('data-mvf'));return;}
  t=e.target.closest('[data-mvolder]');
  if(t){mvOlder(t);return;}
});
document.addEventListener('change',function(e){
  var t=e.target;
  if(t.matches&&t.matches('[data-mkpos]')){MK.pos=t.value;mkFilter();return;}
  if(t.matches&&t.matches('[data-mksort]')){var tb=mkTable();if(!tb){return;}
    tb.setAttribute('data-sort','');sortTable(tb,t.value);return;}
  if(t.matches&&t.matches('[data-mkr]')){mkRange(t.value,true);return;}
  if(t.matches&&t.matches('[data-goalweek]')){if(t.value){advGoal(t.value,true);}return;}
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

DASH_HTML = "&mdash;"
RANGE_COLS = (("pts", "Proj pts"), ("total", "Games"), ("fppg", "FPPG"), ("l14", "L14"), ("l7", "L7"),
              ("l30", "L30"), ("ovr", "OVR"), ("pot", "POT"), ("dur", "DUR"), ("mind", "MIN \u0394"),
              ("avail", "Avail %"), ("status", "Status"), ("age", "Age"))


def range_table(t: dict, default: bool) -> str:
    """5d2 s.4: one range's Available table: Proj pts and Games over the range,
    the games per fantasy week (tap a count for its days), and the sorts as
    columns. The default range's table is the page's #mk-fa; the others are
    lazy parts (publish.market_range_files)."""
    tid = ' id="mk-fa"' if default else ""
    o = [f'<div class="v2-scroll"><table class="lh-table v2-mk-fa"{tid} data-mkt="{clean(t["key"])}" data-sort="pts" '
         f'data-dir="1" data-orders=\'{clean(t["orders_json"])}\'><thead><tr><th>{colh_btn("market", "name", "Player")}</th>']
    o.append('<th data-k="vtv" class="v2-vu"><button type="button" class="v2-tap" data-sort="vtv"'   # 5e
             f'{colh("market", "vtv")}>Value to you<span class="v2-arrow"></span></button></th>')
    for k, lab in RANGE_COLS[:2]:
        on = k == "pts"
        o.append(f'<th data-k="{k}"{" aria-sort=" + chr(34) + "descending" + chr(34) if on else ""}>'
                 f'<button type="button" class="v2-tap" data-sort="{k}"{colh("market", k)}>{clean(lab)}'
                 f'<span class="v2-arrow">{" &#9662;" if on else ""}</span></button></th>')
    o.append(f'<th>{colh_btn("market", "games", "By week")}<span class="lh-sub">'
             f'{clean(DOT.join(w["label"] for w in t["weeks"]))}</span></th>')
    for k, lab in RANGE_COLS[2:]:
        if k == "status":
            o.append(f'<th>{colh_btn("market", k, clean(lab))}</th>')
            continue
        o.append(f'<th data-k="{k}"><button type="button" class="v2-tap" data-sort="{k}"{colh("market", k)}>'
                 f'{clean(lab)}<span class="v2-arrow"></span></button></th>')
    o.append("</tr></thead><tbody>")
    for i in t["default_rows"]:
        r = t["rows"][i]
        c = r["cells"]
        vu = r.get("vu")
        o.append(f'<tr data-i="{i}" data-h="{r["h"]}" data-pos="{clean(r["pos"])}" data-fit="{clean(r["fit"])}" '
                 f'data-light="{clean(r.get("light") or "")}">'
                 f'<td>{_name(r)}<span class="lh-sub">{clean(r["sub"])} {_chips(r["chips"])}</span></td>'
                 '<td class="lh-num v2-vu">' + (DASH_HTML if not vu else "".join(
                     f'<span class="v2-vu-v" data-m="{clean(m)}">{clean(t)}</span>' for m, t in vu.items()))
                 + "</td>"
                 f'<td class="lh-num">{clean(c["pts"])}</td><td class="lh-num">{clean(c["total"])}</td>'
                 '<td><span class="v2-mk-cells">' + "".join(_cell(g, r["name"]) for g in r["games"]) + "</span></td>"
                 + "".join(f'<td class="lh-num">{clean(c[k])}</td>' for k, _l in RANGE_COLS[2:]) + "</tr>")
    o.append(f'</tbody></table></div><div class="lh-table-note">{clean(t["note"])}</div>')
    return "".join(o)


def _available(a: dict, ids, info, parts: dict = None) -> str:
    rg = a["ranges"]
    parts = parts or {}
    o = ['<div class="v2-fchips">',
         '<label class="v2-fchip">Range<select data-mkr aria-label="Range">'
         + "".join(f'<option value="{clean(t["key"])}"{" selected" if t["key"] == rg["default"] else ""}>'
                   f'{clean(t["label"])}</option>' for t in rg["tabs"]) + "</select></label>",
         '<button type="button" class="v2-fchip" data-mkh="1" aria-pressed="false">Healthy</button>',
         '<label class="v2-fchip">Position<select data-mkpos aria-label="Position"><option value="">Any</option>'
         + "".join(f'<option value="{clean(p)}">{clean(p)}</option>' for p in a["pos"]) + "</select></label>",
         '<label class="v2-fchip">Sort<select data-mksort aria-label="Sort">'
         + "".join(f'<option value="{clean(x["k"])}"{" selected" if x["k"] == "pts" else ""}>{clean(x["label"])}</option>'
                   for x in rg["sorts"]) + "</select></label>",
         '<button type="button" class="v2-fchip" data-mkfit="" aria-pressed="true" hidden>Games on your empty-slot '
         'days &times;</button>',
         # 5e: the viewer's light days (4 or fewer of his players with a game), not the empty-slot days above
         '<button type="button" class="v2-fchip v2-vu-chip" data-mklight aria-pressed="false">Plays on my light '
         'days</button>' + colh_btn("market", "light", "&#9432;").replace('class="v2-tap v2-colh"',
                                                                         'class="v2-tap v2-colh v2-vu-chip"')
         + '</div>']
    o.append('<section class="lh-card lh-card--flush" data-section="available"><div class="lh-sechead v2-pad">'
             f'<h2 class="lh-eyebrow">{clean(a["title"])}</h2><span class="lh-meta" data-mkr-sub>'
             + "".join(f'<span data-mkrange="{clean(t["key"])}"{"" if t["key"] == rg["default"] else " hidden"}>'
                       f'{clean(t["sub"])}</span>' for t in rg["tabs"]) + "</span></div>")
    if not a["rows"] or not rg["tabs"]:
        o.append(f'<p class="v2-p v2-pad">{clean(a["empty"] or "No pickup joins a roster again this season.")}</p></section>')
        return "".join(o)
    for t in rg["tabs"]:
        on = t["key"] == rg["default"]
        ref = parts.get(t["key"])
        if ref is not None and not on:
            o.append(f'<div data-mkrange="{clean(t["key"])}" hidden data-part=\'{clean(json.dumps(ref, separators=(",", ":")))}\'>'
                     '<p class="v2-part-load v2-pad">Opening&hellip;</p></div>')
        else:
            o.append(f'<div data-mkrange="{clean(t["key"])}"{"" if on else " hidden"}>{range_table(t, on)}</div>')
    o.append('<p class="v2-p v2-pad" id="mk-fa-none" hidden>No free agent on this list matches.</p>'
             f'<div class="lh-table-note">{clean(a["note"])}</div></section>')
    o.append(f'<span class="lh-sub">{clean(a["aside"])}</span>')
    return "".join(o)


def _stash(s: dict) -> str:
    o = ['<section class="lh-card" data-section="stash"><div class="lh-sechead"><h2 class="lh-eyebrow">Stash</h2>'
         f'<span class="lh-meta">{clean(s["aside"])}</span></div>']
    if not s["rows"]:
        o.append(f'<p class="v2-p">{clean(s["empty"])}</p>')
    o.append('<div class="v2-mk-list">')
    rg = s.get("ranges") or {"tabs": [], "default": None}
    if rg["tabs"]:
        o.append('<div class="v2-fchips"><label class="v2-fchip">Range<select data-mkr aria-label="Range">'
                 + "".join(f'<option value="{clean(t["key"])}"{" selected" if t["key"] == rg["default"] else ""}>'
                           f'{clean(t["label"])}</option>' for t in rg["tabs"]) + "</select></label></div>")
    for r in s["rows"]:
        rr = "".join(f'<span class="lh-sub" data-mkrange="{clean(t["key"])}"{"" if t["key"] == rg["default"] else " hidden"}>'
                     f'{clean(t["stash"][r["name"]]["games"])} games &middot; {clean(t["stash"][r["name"]]["pts"])} pts '
                     f'({clean(t["label"])})</span>' for t in rg["tabs"] if r["name"] in t["stash"])
        o.append(f'<div class="v2-mk-item"><span class="v2-minw">{_name(r)}<span class="lh-sub">{clean(r["sub"])}'
                 f'{" &middot; " + clean(r["note"]) if r["note"] else ""}</span></span>'
                 f'<span class="v2-mk-right">{_chips(r["chips"])}<span class="lh-sub">Proj {clean(r["proj"])}</span>'
                 f"{rr}</span></div>")
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


INFO_SVG = ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>')


def _tip(ids, title: str, body: str) -> str:
    """An InfoTip with the engine's own text (a tile's: Part B's Starts)."""
    pid = ids.next("tip")
    return (f'<span class="lh-info adv-tinfo"><button type="button" aria-expanded="false" aria-controls="{pid}" '
            f'aria-label="What {clean(title)} means">{INFO_SVG}</button><span class="lh-info__pop" id="{pid}" '
            f'role="note" hidden><b>{clean(title)}</b>{clean(body)}</span></span>')


def _tiles(tiles: list, ids=None) -> str:
    """Part B: Points, Starts (the days under the number, the simulated mean in
    its InfoTip), Title odds -- in the engine's order."""
    if not tiles:
        return ""
    o = ['<div class="adv-mini">']
    for t in tiles:
        d = {"up": " adv-up", "down": " adv-down"}.get(t["dir"], "")
        tip = _tip(ids, t["label"], t["tip"]) if (t.get("tip") and ids is not None) else ""
        sub = f'<span class="adv-tsub">{clean(t["sub"])}</span>' if t.get("sub") else ""
        if t.get("rows"):                                       # AC1: Win %, one row per week
            val = ('<span class="adv-trows">' + "".join(
                f'<span class="adv-l">{clean(r["label"])}</span><span class="adv-v'
                f'{"" if r["dir"] == "up" else " adv-v--down" if r["dir"] == "down" else " adv-v--flat"}">'
                f'{clean(r["value"])}</span>' for r in t["rows"]) + "</span>")
        else:
            val = f'<span class="lh-kpi__value{d}">{clean(t["value"])}</span>'
        o.append(f'<div class="lh-kpi lh-kpi--nested"><span class="adv-tl"><span class="lh-label">{clean(t["label"])}'
                 f'</span>{tip}</span>{val}{sub}</div>')
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
                       f'<span>{clean(x["name"])}{_tagc(x)}</span></span>')
    return "".join(out)


def _cards(players: list) -> str:
    """Every player a row names, each opening his card (4c1), in the opened part."""
    linked = [p for p in players if p.get("href")]
    if not linked:
        return ""
    return '<div class="adv-cards">Cards: ' + " &middot; ".join(_name(p) for p in linked) + "</div>"


def _tagc(p: dict) -> str:
    """AC1: the move's tags (his status chips, the Players row's text)."""
    out = []
    for t in p.get("tags") or []:
        k = " adv-tagc--out" if t.startswith(("O", "OFS")) and not t.startswith("OVR") else \
            " adv-tagc--q" if t.startswith(("Q", "D")) else ""
        out.append(f' <span class="adv-tagc{k}">{clean(t)}</span>')
    return "".join(out)


def _strip_days(b: dict, out_id: str) -> str:
    """One week's boxes: ONE tap control (the whole grid), with the weekday
    letters over it; each box carries its engine line for the readout."""
    o = [f'<button type="button" class="adv-days" data-days data-out="{out_id}" '
         f'aria-label="{clean(b["line"])}. Tap a day for its line.">']
    o.append("".join(f'<span class="adv-dh" aria-hidden="true">{ch}</span>' for ch in "MTWTFSS"))
    for x in b["days"]:
        col = f' adv-c{x["col"]}' if x.get("col") else ""
        o.append(f'<span class="adv-dy adv-dy--{x["k"]}{col}" data-l="{clean(x["line"])}">'
                 f'<span class="adv-dd">{clean(x["d"])}</span><span class="adv-dn">{clean(x["n"])}</span>'
                 f'<span class="adv-dm">{clean(x["mark"])}</span></span>')
    o.append("</button>")
    return "".join(o)


def _day_card(c: dict, ids) -> str:
    """AC1: Games (the day strip, or Rest of season's week chips), the depth
    line, the tiles; every string the engine's (market.DayCards)."""
    o = []
    for n in c.get("notes") or []:
        o.append(f'<div class="adv-why">{clean(n)}</div>')
    sv = c.get("strip")
    if sv:
        rid = ids.next("dayl")
        o.append(f'<div class="adv-games"><div class="adv-gh"><span class="lh-label">{clean(sv["label"])}</span>'
                 f'<span class="adv-gt">{clean(sv["total"])}</span></div>')
        if sv.get("between"):
            o.append(f'<span class="lh-sub">{clean(sv["between"])}</span>')
        if sv.get("chips"):
            o.append('<div class="adv-wchips">')
            bids = []
            for ch in sv["chips"]:
                bid = ids.next("wk")
                bids.append((bid, ch))
                d = {"up": "", "down": " adv-v--down"}.get(ch["dir"], " adv-v--flat")
                o.append(f'<button type="button" class="adv-wchip" aria-expanded="false" aria-controls="{bid}" '
                         f'aria-label="{clean(ch["aria"])}"><span class="adv-l">{clean(ch["label"])}</span>'
                         f'<span class="adv-v{d}">{clean(ch["value"])}</span></button>')
            o.append("</div>")
            for bid, ch in bids:
                o.append(f'<div class="adv-wblk" id="{bid}" hidden><span class="adv-wl">{clean(ch["block"]["line"])}</span>'
                         + _strip_days(ch["block"], rid) + "</div>")
        else:
            for b in sv["weeks"]:
                if sv.get("per_week"):
                    o.append(f'<span class="adv-wl">{clean(b["line"])}</span>')
                o.append(_strip_days(b, rid))
        o.append(f'<p class="adv-dayl" id="{rid}" aria-live="polite">{clean(sv["hint"])}</p></div>')
    elif c.get("missing"):
        o.append(f'<div class="adv-why">{clean(c["missing"])}</div>')
    if c.get("depth"):
        o.append(f'<div class="adv-depth">{clean(c["depth"])}</div>')
    o.append(_tiles(c["tiles"], ids))
    return "".join(o)


def _foot(lines: list) -> str:
    return '<div class="adv-foot">' + "".join(f"<span>{clean(x)}</span>" for x in lines) + "</div>"


def _adv_row(r: dict, ids) -> str:
    did = ids.next("adv")
    adds = ", ".join(f"<b>{clean(p['name'])}</b>{_tagc(p)}" for p in r["adds"])
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
    det = [f'<div class="adv-det" id="{did}" hidden>']
    if r.get("why"):
        det.append(f'<div class="adv-why">{clean(r["why"])}</div>')
    if r.get("followup"):
        det.append(f'<div class="adv-why">{clean(r["followup"])}</div>')
    if r.get("card"):
        det.append(_day_card(r["card"], ids))
    else:
        det.append(_tiles(r["tiles"], ids))
    if r.get("card") and r["card"]["foot"]:
        det.append(_foot(r["card"]["foot"]))
    if r["also"]:
        det.append('<div class="adv-tag">Also wanted by ' + "".join(_team_link(t) for t in r["also"]) + "</div>")
    det.append(_cards(r["adds"] + r["lines"]))
    det.append("</div>")
    return head + "".join(det)


class PaneIds:
    """Unique ids inside a goal's pane, which may be its own encrypted part
    (rendered apart from the page): every id carries the goal's prefix."""

    def __init__(self, key: str):
        self.p = "g" + "".join(ch if ch.isalnum() else "-" for ch in key) + "-"
        self.n = 0

    def next(self, p: str = "") -> str:
        self.n += 1
        return f"{self.p}{p}{self.n}"


def _goal_costs(costs: list, ids) -> str:
    if not costs:
        return ""
    o = ['<div class="adv-cost"><div class="adv-cost-h"><span class="lh-label">What it costs</span>'
         '<span class="lh-sub">against Balanced\u2019s advice</span></div>']
    for c in costs:
        d = {"up": " adv-up", "down": " adv-down"}.get(c.get("dir"), "")
        if c.get("strip"):
            sid = ids.next("strip")
            o.append(f'<button type="button" class="adv-crow adv-crow--btn" aria-expanded="false" aria-controls="{sid}">'
                     f'<span>{clean(c["label"])}</span><span class="adv-cv{d}">{clean(c["value"])}</span>'
                     f'<span class="adv-chev" aria-hidden="true">&rsaquo;</span></button>'
                     f'<div class="adv-strip" id="{sid}" hidden>'
                     + "".join(f'<span class="adv-sc"><span class="adv-l">Wk {clean(str(x["week"]))}</span>'
                               f'<span class="adv-v{"" if x["dir"] == "up" else " adv-v--down" if x["dir"] == "down" else " adv-v--flat"}">'
                               f'{clean(x["value"])}</span>'
                               + (f'<span class="adv-ssub">{clean(x["sub"])}</span>' if x.get("sub") else "") + "</span>"
                               for x in c["strip"]) + "</div>")
        else:
            o.append(f'<div class="adv-crow"><span>{clean(c["label"])}</span><span class="adv-cv{d}">'
                     f'{clean(c["value"])}</span><span></span></div>')
    o.append("</div>")
    return "".join(o)


def goal_pane_html(key: str, pane: dict, mark_of) -> str:
    """One goal's cards (Part D): rendered into the page (the preview) or as
    its own encrypted part, opened on the chip's first tap (publish)."""
    ids = PaneIds(key)
    o = [f'<div class="adv-intro"><span>{clean(pane["intro"])}</span></div>']
    for c in pane["cards"]:
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
            if c["costs"] or c["caveat"] or c["as_of"]:
                o.append('<div class="adv-gfoot">' + _goal_costs(c["costs"], ids)
                         + (f'<span class="adv-asof">{clean(c["as_of"])}</span>' if c["as_of"] else "")
                         + (f'<span class="lh-sub">{clean(c["caveat"])}</span>' if c["caveat"] else "") + "</div>")
        else:
            o.append(f'<div class="adv-empty">{clean(c["line"])}</div>')
        o.append("</section>")
    return "".join(o)


def _goal_picker(g: dict, ids, info) -> str:
    o = ['<div class="adv-pick" role="group" aria-label="Play for"><span class="adv-pick-h">'
         f'<span class="lh-label">Play for</span>{info}</span><div class="adv-chips" data-goalchips>']
    for x in g["picker"]:
        o.append(f'<button type="button" class="v2-fchip adv-chip" data-goal="{clean(x["key"])}" '
                 f'aria-pressed="{"true" if x["key"] == "balanced" else "false"}">{clean(x["chip"])}</button>')
    if g["weeks"]:
        # Market's own pattern (the Range chip): a visible select is the chip's content
        o.append('<label class="v2-fchip adv-chip adv-wk"><select data-goalweek aria-label="A week">'
                 '<option value="" selected>A week \u25be</option>'
                 + "".join(f'<option value="{clean(x["key"])}">{clean(x["label"])}</option>' for x in g["weeks"])
                 + "</select></label>")
    o.append("</div></div>")
    return "".join(o)


def _advice(av: dict, ids, info, mark_of, gparts: dict = None, ginfo: str = "") -> str:
    g = av.get("goals")
    o = []
    if g and not (av["error"] or av["empty"]):
        o.append(_goal_picker(g, ids, ginfo))
        o.append('<div data-goal-pane="balanced">')
    o.append(f'<div class="adv-intro"><span>{clean(av["intro"])}</span>{info}</div>')
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
                     f'<div class="adv-det" id="{did}" hidden>{_weeks(b["weeks"])}'
                     + (f'<div class="adv-why">{clean(b["why"])}</div>' if b.get("why") else "")
                     + (_day_card(b["card"], ids) + (_foot(b["card"]["foot"]) if b["card"]["foot"] else "")
                        if b.get("card") else _tiles(b["tiles"], ids))
                     + f'{_cards([b["add"]] + b["lines"])}</div>')
        if c["empty"]:
            o.append(f'<div class="adv-empty">{clean(c["empty"])}</div>')
        o.append("</section>")
    if g and not (av["error"] or av["empty"]):
        o.append("</div>")
        for k, pane in g["panes"].items():
            ref = (gparts or {}).get(k)
            if ref:                                   # publish: its own part, opened on the first tap
                o.append(f'<div data-goal-pane="{clean(k)}" hidden data-part=\'{clean(json.dumps(ref, separators=(",", ":")))}\'>'
                         "</div>")
            else:                                     # the preview: inline
                o.append(f'<div data-goal-pane="{clean(k)}" hidden>{goal_pane_html(k, pane, mark_of)}</div>')
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
            o.append(_available(mk["available"], ids, info_of, (mk.get("parts") or {}).get("ranges")))
        elif k == "stash":
            o.append(_stash(mk["stash"]))
        elif k == "advice":
            gp = (mk.get("parts") or {}).get("goals")
            o.append(_advice(mk["advice"], ids, info_of(ids, "advice"), mark_of, gp,
                             info_of(ids, "advice_goals") if (mk["advice"] or {}).get("goals") else ""))
        elif k == "block":
            o.append(_block(mk["block"]))
        elif k == "moves":
            o.append(_moves(mk["moves"], mk.get("parts"), vm.get("mode", "preview")))
        o.append("</div>")
    o.append("</div></section>")
    return "".join(o)
