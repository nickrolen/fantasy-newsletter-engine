"""
hub_tap_sweep.py -- the tap and popover sweep of the published new hub (5c,
claude/HANDOFF_5C_PHONE_BUGS_2026-11-20.md section 1-2). SYNTHETIC LEAGUE ONLY:
no league data ever goes into a browser outside Nick's machine.

Why it exists: on 11-20 Nick found, on his phone, an invisible strip that sent
taps to "Forget this phone" and InfoTip popovers running off the screen. They
sat in published-only paths (the decrypt shell, lazy parts) that the preview
tests never opened. This opens the PUBLISHED page through the real v2 shell in
headless Chrome at 390, 360 and 1280 px and, on every screen, segment, chip
and lazy screen (team pages, last week's matchup pages, History, Awards, a
card, Compare), scrolled to the top, the middle and the bottom:

  - elementFromPoint every 16 px: every hit is the element drawn there or its
    own 44-point area (a .v2-tap's centred ::after; the toggle's own); no hit
    on a hidden element, an element of another screen, or #forget outside its
    own button; where one target's area lies over another target's drawn box
    a REAL tap there must reach the drawn one (the page's "a tap reaches what
    is drawn" listener); overlapping tap areas are reported;
  - HUB.forget and HUB.reload are replaced by recorders and every distinct tap
    target is tapped: none may run, no page may (re)load, and the Forget
    question may come only from the Forget button; then Forget asks first,
    Cancel forgets nothing, Forget forgets once;
  - every InfoTip popover opened: inside the viewport with an 8 px margin (7 allowing for sub-pixel rounding) and
    drawn on top (not clipped, not covered); every chart tooltip inside;
  - no script error and no sideways scroll.
5d1: every column header's definition popover is opened and checked like an
InfoTip's; 5d2: Team > Schedule's week chips and a day's tap, the Players
groups (and the Box score's totals), Market's ranges and its ?fit= route,
and next week's matchup previews are states of their own; 5e: the "I'm..." picker opened and a team
picked (Home, Players, Market, the light-days chip) and Home's ?seg= links; a season picker's oldest season (and the draft's first by-team
season) is a state of its own; the title-odds chart opened from a team's odds
(?hl=) is a route of its own. AC1: each Advice goal's first move opened with a
day of its strip tapped (the readout), and Rest of season's week chip opened
with a day in it, are states of their own.

    python scripts/hub_tap_sweep.py PUBLISH_DIR PASSPHRASE [--widths 390,360,1280] [--out report.json]

PUBLISH_DIR: a synthetic publish (tests/test_5c_page.py builds one) -- never
output/hub_publish/ (the real league). Needs `pip install playwright` and a
Chrome (--chrome PATH, or playwright's own). Exit 0: every check passed;
1: a failure (listed); 2: refused or not available here.
"""
import argparse
import contextlib
import functools
import http.server
import json
import sys
import threading
import time
from pathlib import Path

SIZES = [(390, 844), (360, 780), (1280, 800)]

JS_LIB = r"""
window.__sw = (function(){
const INTER='a[href],button,select,input,label,[role=button],[data-tip-h],.v2-tap,.lh-c-hit,[tabindex]';
function inter(el){return (el&&el.closest)?el.closest(INTER):null;}
function vis(el){if(el.closest('[hidden]')){return false;}var cs=getComputedStyle(el);
  return cs.visibility!=='hidden'&&cs.display!=='none'&&cs.opacity!=='0';}
function desc(el){if(!el){return 'null';}var s=el.tagName.toLowerCase();if(el.id){s+='#'+el.id;}
  if(el.className&&typeof el.className==='string'){s+='.'+el.className.trim().split(/\s+/).slice(0,3).join('.');}
  var t=(el.textContent||'').trim().replace(/\s+/g,' ').slice(0,24);return s+(t?' "'+t+'"':'');}
function inR(r,x,y,e){e=e||0;return x>=r.left-e&&x<=r.right+e&&y>=r.top-e&&y<=r.bottom+e;}
function tapArea(el){var r=el.getBoundingClientRect(),a=[{left:r.left,right:r.right,top:r.top,bottom:r.bottom}];
  if(el.matches&&el.matches('.lh-toggle button')){a.push({left:r.left,right:r.right,top:r.top-7,bottom:r.bottom+7});}  // the design's own 44px area
  if(el.classList&&el.classList.contains('v2-tap')){var cy=r.top+r.height/2,w=Math.max(r.width,44);
    a.push({left:r.left,right:r.left+w,top:cy-22,bottom:cy+22});}
  return a;}
function inArea(el,x,y){var a=tapArea(el);for(var i=0;i<a.length;i++){if(inR(a[i],x,y,1.5)){return true;}}return false;}
function screen(){var s=document.querySelectorAll('.v2-screen');for(var i=0;i<s.length;i++){if(!s[i].hidden){return s[i];}}return null;}
function grid(res){
  var vw=document.documentElement.clientWidth,vh=window.innerHeight,scr=screen();
  var fg=document.getElementById('forget');
  for(var y=4;y<vh-2;y+=16){for(var x=4;x<vw-2;x+=16){
    var el=document.elementFromPoint(x,y);if(!el){continue;}
    res.points++;
    if(!vis(el)){res.hidden.push(desc(el)+' @'+x+','+y);continue;}
    var s=el.closest('.v2-screen');if(s&&s!==scr){res.other.push(desc(el)+' @'+x+','+y);continue;}
    if(fg&&el.closest('#forget')){res.forget_hits++;if(!inArea(fg,x,y)){res.forget_stray.push('@'+x+','+y);}}
    var I=inter(el);
    if(I){res.tap_points++;var k=I.getAttribute('data-sw');if(!k){k=String(res.ntag++);I.setAttribute('data-sw',k);}}
    var r=el.getBoundingClientRect();
    if(inR(r,x,y,1.5)){continue;}
    if(I&&inArea(I,x,y)){
      // I's own 44-point area: does it cover another tap target drawn here?
      var st=document.elementsFromPoint(x,y);
      for(var j=0;j<st.length;j++){var E=st[j];if(E===el){continue;}
        if(!inR(E.getBoundingClientRect(),x,y,0)||!vis(E)){continue;}
        var J=inter(E);
        if(J&&J!==I&&!J.contains(I)&&!I.contains(J)){res.steal.push(desc(I)+' covers '+desc(J)+' @'+x+','+y);res.stealv.push({sy:window.scrollY,x:x,y:y,pair:desc(I)+' covers '+desc(J),href:J.getAttribute('href')||'',ihref:I.getAttribute('href')||''});}
        break;}
      continue;}
    if(I){res.outside_tap.push(desc(el)+' (tap '+desc(I)+') @'+x+','+y);}
    else{res.outside.push(desc(el)+' ['+[r.left,r.top,r.right,r.bottom].map(Math.round)+'] @'+x+','+y);}
  }}
}
function overlaps(res){
  var scr=screen();if(!scr){return;}
  var els=[].slice.call(scr.querySelectorAll(INTER)).filter(function(e){return vis(e)&&e.getClientRects().length;});
  var sy=window.scrollY,A=els.map(function(e){return tapArea(e).map(function(r){return {l:r.left,r:r.right,t:r.top+sy,b:r.bottom+sy};});});
  for(var i=0;i<els.length;i++){for(var j=i+1;j<els.length;j++){
    if(els[i].contains(els[j])||els[j].contains(els[i])){continue;}
    var hit=false;
    for(var a=0;a<A[i].length&&!hit;a++){for(var b=0;b<A[j].length&&!hit;b++){var p=A[i][a],q=A[j][b];
      var w=Math.min(p.r,q.r)-Math.max(p.l,q.l),h=Math.min(p.b,q.b)-Math.max(p.t,q.t);
      if(w>1&&h>1){hit=true;res.overlap.push(desc(els[i])+' & '+desc(els[j])+' ('+Math.round(w)+'x'+Math.round(h)+')');}}}
  }}
}
async function sweep(){
  var res={points:0,tap_points:0,hidden:[],other:[],outside:[],outside_tap:[],steal:[],stealv:[],overlap:[],forget_hits:0,
           forget_stray:[],ntag:Number(document.body.getAttribute('data-swn')||0)};
  var H=document.documentElement.scrollHeight,vh=window.innerHeight;
  var ys=[0,Math.max(0,Math.round((H-vh)/2)),Math.max(0,H-vh)];
  for(var i=0;i<ys.length;i++){window.scrollTo(0,ys[i]);await new Promise(function(r){requestAnimationFrame(function(){r();});});grid(res);}
  window.scrollTo(0,0);overlaps(res);
  document.body.setAttribute('data-swn',String(res.ntag));
  res.sideways=document.documentElement.scrollWidth>document.documentElement.clientWidth+1;
  return res;
}
async function popovers(){
  var out=[],scr=screen(),vw=document.documentElement.clientWidth,vh=window.innerHeight;
  var bs=[].slice.call(document.querySelectorAll('.lh-info > button')).filter(function(b){return vis(b)&&b.getClientRects().length&&(!scr||scr.contains(b));});
  for(var i=0;i<bs.length;i++){var b=bs[i];b.scrollIntoView({block:'center'});await new Promise(function(r){setTimeout(r,60);});
    b.click();await new Promise(function(r){requestAnimationFrame(function(){r();});});
    var p=document.getElementById(b.getAttribute('aria-controls'));
    var r=p.getBoundingClientRect(),bad=[];
    if(p.hidden){bad.push('did not open');}
    if(r.left<7){bad.push('left '+r.left.toFixed(1));}if(r.right>vw-7){bad.push('right '+(vw-r.right).toFixed(1));}
    if(r.top<7){bad.push('top '+r.top.toFixed(1));}if(r.bottom>vh-7){bad.push('bottom '+(vh-r.bottom).toFixed(1));}
    var pts=[[r.left+r.width/2,r.top+r.height/2],[r.left+4,r.top+4],[r.right-4,r.top+4],[r.left+4,r.bottom-4],[r.right-4,r.bottom-4]];
    for(var k=0;k<pts.length;k++){var e=document.elementFromPoint(pts[k][0],pts[k][1]);if(!e||!p.contains(e)){bad.push('covered/clipped at '+k+' by '+desc(e));break;}}
    out.push({tip:desc(b.closest('.lh-info'))+' '+(b.getAttribute('aria-label')||''),ok:!bad.length,bad:bad,
              rect:[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)]});
    b.click();await new Promise(function(r){setTimeout(r,0);});}
  var ts=[].slice.call(document.querySelectorAll('[data-tip-h]')).filter(function(t){return vis(t)&&t.getClientRects().length&&(!scr||scr.contains(t));});
  var tips=[];
  for(var j=0;j<ts.length;j++){var t=ts[j];t.scrollIntoView({block:'center'});await new Promise(function(r){setTimeout(r,60);});
    t.dispatchEvent(new MouseEvent('click',{bubbles:true}));await new Promise(function(r){requestAnimationFrame(function(){r();});});
    var box=document.getElementById('v2-tip'),q=box?box.getBoundingClientRect():null,bb=[];
    if(!box||box.hidden){bb.push('did not open');}
    else{if(q.left<7){bb.push('left '+q.left.toFixed(1));}if(q.right>vw-7){bb.push('right');}
      if(q.top<7){bb.push('top '+q.top.toFixed(1));}if(q.bottom>vh-7){bb.push('bottom');}}
    tips.push({tip:desc(t),ok:!bb.length,bad:bb,rect:q?[Math.round(q.left),Math.round(q.top),Math.round(q.width),Math.round(q.height)]:null,vw:vw});
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));}
  // 5d1 s.5: every column header's definition popover, opened and checked like an InfoTip's
  var hs=[].slice.call(document.querySelectorAll('[data-colh]')).filter(function(b){return vis(b)&&b.getClientRects().length&&(!scr||scr.contains(b));});
  for(var c=0;c<hs.length;c++){var hb=hs[c];hb.scrollIntoView({block:'center'});await new Promise(function(r){setTimeout(r,40);});
    hb.click();await new Promise(function(r){requestAnimationFrame(function(){r();});});
    var cp=document.getElementById('v2-colpop'),cr=cp?cp.getBoundingClientRect():null,cb=[];
    if(!cp||cp.hidden){cb.push('did not open');}
    else{if(cr.left<7){cb.push('left '+cr.left.toFixed(1));}if(cr.right>vw-7){cb.push('right '+(vw-cr.right).toFixed(1));}
      if(cr.top<7){cb.push('top '+cr.top.toFixed(1));}if(cr.bottom>vh-7){cb.push('bottom '+(vh-cr.bottom).toFixed(1));}
      var cps=[[cr.left+cr.width/2,cr.top+cr.height/2],[cr.left+4,cr.top+4],[cr.right-4,cr.top+4],[cr.left+4,cr.bottom-4],[cr.right-4,cr.bottom-4]];
      for(var q=0;q<cps.length;q++){var ce=document.elementFromPoint(cps[q][0],cps[q][1]);if(!ce||!cp.contains(ce)){cb.push('covered/clipped at '+q+' by '+desc(ce));break;}}}
    out.push({tip:'column '+hb.getAttribute('data-colh'),ok:!cb.length,bad:cb,
              rect:cr?[Math.round(cr.left),Math.round(cr.top),Math.round(cr.width),Math.round(cr.height)]:null});
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    await new Promise(function(r){setTimeout(r,0);});}
  window.scrollTo(0,0);
  return {pops:out,tips:tips};
}
async function clicks(h0){
  var bad=[],n=0,ts=[].slice.call(document.querySelectorAll('[data-sw]'));
  for(var i=0;i<ts.length;i++){var el=ts[i];
    if(!el.isConnected||el.closest('[hidden]')||el.closest('#forget')||el.closest('#forget-ask')){continue;}
    if(el.getAttribute('data-swc')){continue;}el.setAttribute('data-swc','1');
    el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true,view:window}));n++;await new Promise(function(r){setTimeout(r,0);});
    var fa=document.getElementById('forget-ask');if(fa&&!fa.hidden){bad.push('the Forget question from '+desc(el));fa.hidden=true;}
    var iv=document.getElementById('issue-view');if(iv&&!iv.hidden){document.getElementById('issue-close').click();}
    if(location.hash!==h0){location.hash=h0;await new Promise(function(r){setTimeout(r,40);});}
  }
  document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  return {clicked:n,bad:bad};
}
return {sweep:sweep,popovers:popovers,clicks:clicks,screen:function(){var s=screen();return s?s.getAttribute('data-route'):null;}};
})();
"""


def wait_ready(page):
    page.wait_for_function("""() => { const s=[...document.querySelectorAll('.v2-screen')].find(x=>!x.hidden);
        if(!s) return false; if(s.getAttribute('data-screen-part') && !s.getAttribute('data-loaded')) return false;
        if(s.querySelector('.v2-card-load')) return false;
        const p=[...s.querySelectorAll('[data-part]')].filter(x=>!x.closest('[hidden]') && x.getAttribute('data-loaded')!=='1');
        return p.length===0; }""", timeout=8000)
    page.wait_for_timeout(120)


def go(page, route):
    page.evaluate("r => { location.hash = '#/' + r; }", route)
    page.wait_for_timeout(60)
    wait_ready(page)


def states_for(page, route):
    """[(label, js to apply)] for a route: as it opens, then each segment pane and
    the Detailed toggle in the visible screen."""
    segs = page.evaluate("""() => { const s=[...document.querySelectorAll('.v2-screen')].find(x=>!x.hidden);
        const out=[]; s.querySelectorAll('.lh-seg[data-seg] button').forEach(b=>{
          const k=b.closest('.lh-seg').getAttribute('data-seg'); if(k!=='league') out.push([k,b.getAttribute('data-pane')]); });
        if(s.querySelector('.lh-toggle button[data-mode="detailed"]')) out.push(['toggle','detailed']);
        // 5d1 s.8: a season picker's oldest season (a past part), and the draft's first by-team season
        s.querySelectorAll('select[data-spick]').forEach(x=>{ if(x.closest('[hidden]')) return; const v=[...x.options].map(o=>o.value);
          if(v.length>1) out.push(['spick', x.getAttribute('data-spick')+'|'+v[v.length-1]]);
          if(x.getAttribute('data-spick')==='draft' && v.includes('2023-24')) out.push(['spick','draft|2023-24']); });
        // 5d2: Team > Schedule's week chips and a day's tap; the Players groups (and the Box score's
        // totals); Market's ranges
        s.querySelectorAll('[data-swk]').forEach(b=>out.push(['swk', b.getAttribute('data-swk')]));
        if(s.querySelector('[data-sched] .v2-sday')) out.push(['sday','0']);
        s.querySelectorAll('[data-pgrp]').forEach(b=>out.push(['pgrp', b.getAttribute('data-pgrp')]));
        if(s.querySelector('[data-pgroup="box"]')) out.push(['boxv','tot']);
        const r=s.querySelector('[data-section="available"]')?s.querySelector('select[data-mkr]'):null;
        if(r){[...r.options].forEach(o=>out.push(['mkr', o.value]));}
        // Advice goals (Part D): each goal chip, each week of "A week", a far goal's cost strip opened
        s.querySelectorAll('[data-goal]').forEach(b=>out.push(['goal', b.getAttribute('data-goal')]));
        const gw=s.querySelector('select[data-goalweek]');
        if(gw){[...gw.options].filter(o=>o.value).forEach(o=>out.push(['goal', o.value]));
          const f=[...gw.options].find(o=>o.value); if(f) out.push(['goalstrip', f.value]);}
        // AC1: each goal's first move opened and a day of its strip tapped (the readout), Rest of
        // season's week chip opened and a day in it; Balanced's too (with or without goals)
        if(s.querySelector('[data-pane-of="advice"] .adv-days')||s.querySelector('[data-goal-pane]')){
          out.push(['advday','balanced']);
          s.querySelectorAll('[data-goal]').forEach(b=>{const g=b.getAttribute('data-goal');
            if(g!=='balanced') out.push(['advday', g]); if(g==='ros') out.push(['advchip', g]);});
          if(gw){const f2=[...gw.options].find(o=>o.value); if(f2) out.push(['advday', f2.value]);}}
        // 5e: the "I'm..." picker opened, and a team picked (Value to you, the light-days chip)
        if(document.getElementById('me-btn')&&['home','players','market'].includes(s.getAttribute('data-route'))){
          out.push(['me','open']); out.push(['me','pick']);
          if(s.querySelector('[data-mklight]')) out.push(['me','light']);}
        return out; }""")
    return segs


APPLY_5D2 = """([k,p]) => { const s=[...document.querySelectorAll('.v2-screen')].find(x=>!x.hidden);
  const seg=(g,pn)=>{const b=s.querySelector('.lh-seg[data-seg="'+g+'"] button[data-pane="'+pn+'"]'); if(b) b.click();};
  if(k==='swk'){seg('team','schedule'); const b=s.querySelector('[data-swk="'+p+'"]'); if(b) b.click();}
  else if(k==='sday'){seg('team','schedule'); const b=s.querySelector('[data-swpane]:not([hidden]) .v2-sday'); if(b) b.click();}
  else if(k==='pgrp'){const b=s.querySelector('[data-pgrp="'+p+'"]'); if(b) b.click();}
  else if(k==='boxv'){const g=s.querySelector('[data-pgrp="box"]'); if(g) g.click();
    setTimeout(()=>{const b=s.querySelector('[data-pgroup="box"] [data-boxv="tot"]'); if(b) b.click();},300);}
  else if(k==='mkr'){seg('market','available'); const x=s.querySelector('select[data-mkr]'); x.value=p;
    x.dispatchEvent(new Event('change',{bubbles:true}));}
  else if(k==='goal'||k==='goalstrip'){seg('market','advice');
    if(p.indexOf('week:')===0){const x=s.querySelector('select[data-goalweek]'); x.value=p;
      x.dispatchEvent(new Event('change',{bubbles:true}));}
    else{const b=s.querySelector('[data-goal="'+p+'"]'); if(b) b.click();}
    if(k==='goalstrip'){setTimeout(()=>{const c=s.querySelector('[data-goal-pane]:not([hidden]) .adv-crow--btn');
      if(c) c.click(); const r=s.querySelector('[data-goal-pane]:not([hidden]) .adv-row'); if(r) r.click();},400);}}
  else if(k==='advday'||k==='advchip'){seg('market','advice');
    if(p.indexOf('week:')===0){const x=s.querySelector('select[data-goalweek]'); x.value=p;
      x.dispatchEvent(new Event('change',{bubbles:true}));}
    else{const b=s.querySelector('[data-goal="'+p+'"]'); if(b) b.click();}
    setTimeout(()=>{const pane=s.querySelector('[data-goal-pane]:not([hidden])')||s.querySelector('[data-pane-of="advice"]');
      if(!pane) return; const r=pane.querySelector('.adv-row'); if(r&&r.getAttribute('aria-expanded')!=='true') r.click();
      const det=pane.querySelector('.adv-det:not([hidden])'); if(!det) return;
      if(k==='advchip'){const c=det.querySelector('.adv-wchip'); if(c) c.click();}
      const d=[...det.querySelectorAll('.adv-dy')].find(x=>x.offsetParent); if(d) d.click();},400);}
  else if(k==='me'){const sh=document.getElementById('me-sheet');
    if(p==='open'){if(sh.hidden) document.getElementById('me-btn').click();}
    else{const b=document.querySelector('[data-me-pick]:not([data-me-pick=""])'); if(b) b.click();
      if(p==='light'){seg('market','available'); const c=s.querySelector('[data-mklight]'); if(c) c.click();}
      if(s.querySelector('[data-pgrp="value"]')){const g=s.querySelector('[data-pgrp="value"]'); g.click();}}} }"""


def run(url: str, passphrase: str, sizes=SIZES, chrome: str = None) -> dict:
    """The sweep of the hub served at url, unlocked with passphrase."""
    from playwright.sync_api import sync_playwright
    report = {"widths": {}, "errors": []}
    with sync_playwright() as pw:
        br = pw.chromium.launch(**({"executable_path": chrome} if chrome else {}))
        for w, h in sizes:
            ctx = br.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            errs, loads = [], []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("load", lambda: loads.append(time.time()))
            page.goto(url)
            page.fill("#pass", passphrase)
            page.click("#go")
            page.wait_for_selector("#hub", timeout=20000)
            page.evaluate("""() => { window.__calls=[]; HUB.forget=function(){__calls.push('forget');};
                HUB.reload=function(){__calls.push('reload');}; }""")
            page.add_script_tag(content=JS_LIB)
            n_loads0 = len(loads)
            routes = page.evaluate("""() => {
              const r=[...document.querySelectorAll('.v2-screen[data-route]')].map(s=>s.getAttribute('data-route'))
                .filter(x=>!['player','compare','compare-pick'].includes(x));
              const keys=[...new Set([...document.querySelectorAll('[data-card]')].map(a=>a.getAttribute('data-card')))];
              const out=r.slice(); if(keys.length){out.push('players/'+keys[0]); out.push('players/'+keys[keys.length-1]);
                out.push('players/compare/'+keys[0]); if(keys.length>1) out.push('players/compare/'+keys[0]+'/'+keys[1]);}
              const segs=[...document.querySelectorAll('.lh-seg[data-seg="league"] button')].map(b=>b.getAttribute('data-pane'));
              segs.forEach(s=>{ if(s!=='history') out.push('league/'+s); });
              const chips=[...document.querySelectorAll('[data-lhchip]')].map(b=>b.getAttribute('data-lhchip'));
              chips.forEach(c=>out.push('league/history/'+c));
              // 5d1 s.4: the title-odds chart opened from a team's odds, his line highlighted
              const hl=document.querySelector('a.v2-rank-odds'); if(hl) out.push(hl.getAttribute('href').slice(2));
              // 5d2: Market opened from Team > Schedule's pickups link (?r=next&fit=<manager>)
              const tm=document.querySelector('.v2-screen[data-route^="teams/"]');
              if(tm&&document.querySelector('select[data-mkr] option[value="next"]')) out.push('market?r=next&fit='+tm.getAttribute('data-route').slice(6));
              // 5e: Home's Moves window links open Market on its segment
              if(document.querySelector('a[href="#/market?seg=moves"]')) out.push('market?seg=moves');
              return out; }""")
            W = {"states": [], "routes": routes}
            for route in routes:
                try:
                    go(page, route)
                except Exception as e:                       # noqa: BLE001
                    W["states"].append({"state": route, "error": f"did not open: {e}"[:200]})
                    continue
                page.evaluate("() => { if(window.HUBVIEW) HUBVIEW.set(''); const sh=document.getElementById('me-sheet');"
                              " if(sh) sh.hidden=true; }")             # 5e: every route opens with nobody picked
                labels = [("as opened", None)] + [(f"{k}:{p}", (k, p)) for k, p in states_for(page, route)]
                for lab, sp in labels:
                    if sp:
                        k, p = sp
                        if k == "spick":                       # 5d1 s.8: pick a past season (the route changes)
                            page.evaluate("(kv) => { const [k,v]=kv.split('|'); const x=document.querySelector("
                                          "'select[data-spick=\"'+k+'\"]'); x.value=v; x.dispatchEvent(new Event('change',{bubbles:true})); }",
                                          p)
                        elif k in ("swk", "sday", "pgrp", "boxv", "mkr", "me", "goal", "goalstrip", "advday",
                                   "advchip"):                          # 5d2, 5e, goals, AC1
                            page.evaluate(APPLY_5D2, [k, p])
                            page.wait_for_timeout(500)
                        elif k == "toggle":
                            page.evaluate("() => { const s=[...document.querySelectorAll('.v2-screen')].find(x=>!x.hidden);"
                                          " s.querySelector('.lh-toggle button[data-mode=\"detailed\"]').click(); }")
                        else:
                            page.evaluate("([k,p]) => { const s=[...document.querySelectorAll('.v2-screen')].find(x=>!x.hidden);"
                                          " const b=s.querySelector('.lh-seg[data-seg=\"'+k+'\"] button[data-pane=\"'+p+'\"]'); if(b) b.click(); }",
                                          [k, p])
                        page.wait_for_timeout(80)
                        try:
                            wait_ready(page)
                        except Exception:                    # noqa: BLE001
                            pass
                    res = page.evaluate("() => __sw.sweep()")
                    # every distinct covered target: a REAL tap (trusted, with a point) where it is drawn
                    seen_pairs, verified = set(), []
                    h_before = page.evaluate("() => location.hash")
                    for sv in res["stealv"]:
                        if sv["pair"] in seen_pairs:
                            continue
                        seen_pairs.add(sv["pair"])
                        page.evaluate("y => window.scrollTo(0, y)", sv["sy"])
                        page.wait_for_timeout(30)
                        page.mouse.click(sv["x"], sv["y"])
                        page.wait_for_timeout(120)
                        h = page.evaluate("() => location.hash")
                        ok = (h == sv["href"]) if sv["href"].startswith("#") else (h == h_before)
                        verified.append({"pair": sv["pair"], "went": h, "want": sv["href"] or "(stay)", "ok": ok})
                        if h != h_before:
                            page.evaluate("h => { location.hash = h; }", h_before)
                            page.wait_for_timeout(80)
                            try:
                                wait_ready(page)
                            except Exception:            # noqa: BLE001
                                pass
                        page.evaluate("() => { document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); }")
                    res["verified"] = verified
                    del res["stealv"]
                    pt = page.evaluate("() => __sw.popovers()")
                    h0 = page.evaluate("() => location.hash")
                    ck = page.evaluate("h => __sw.clicks(h)", h0)
                    if page.evaluate("() => location.hash") != h0:
                        go(page, route)
                    W["states"].append({"state": f"{route} [{lab}]", "screen": page.evaluate("() => __sw.screen()"),
                                        "sweep": res, "pops": pt["pops"], "tips": pt["tips"], "clicks": ck})
            # the Forget button: asks first; Cancel forgets nothing; Forget forgets once
            go(page, "home")
            page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
            page.click("#forget")
            asked = page.evaluate("() => !document.getElementById('forget-ask').hidden")
            q = page.evaluate("() => document.getElementById('forget-q').textContent")
            page.click("#forget-no")
            after_cancel = page.evaluate("() => [document.getElementById('forget-ask').hidden, __calls.slice()]")
            page.click("#forget")
            page.click("#forget-yes")
            after_yes = page.evaluate("() => __calls.slice()")
            stored = page.evaluate("() => localStorage.getItem('hub-key-v1') !== null")
            W["forget"] = {"asked": asked, "question": q, "after_cancel": after_cancel, "after_yes": after_yes,
                           "key_still_stored_with_stub": stored}
            W["calls_before_forget_test"] = None
            W["page_loads_after_unlock"] = len(loads) - n_loads0
            W["errors"] = errs
            report["widths"][str(w)] = W
            ctx.close()
        br.close()
    return report


def failures(report: dict) -> list:
    """Every failed check, one line each (empty: the sweep passed)."""
    out = []
    for w, W in report["widths"].items():
        for s in W["states"]:
            if "error" in s:
                out.append(f"{w}px {s['state']}: {s['error']}")
                continue
            sw = s["sweep"]
            for k, what in (("hidden", "a hidden element hit"), ("other", "another screen's element hit"),
                            ("forget_stray", "#forget hit outside its button"),
                            ("outside_tap", "a tap target hit outside its box and its 44-point area")):
                for x in sw[k][:3]:
                    out.append(f"{w}px {s['state']}: {what}: {x}")
            for v in sw.get("verified", []):
                if not v["ok"]:
                    out.append(f"{w}px {s['state']}: a tap on {v['pair']} went to {v['went']}, not {v['want']}")
            if sw["sideways"]:
                out.append(f"{w}px {s['state']}: the page scrolls sideways")
            for p in s["pops"]:
                if not p["ok"]:
                    out.append(f"{w}px {s['state']}: popover {p['tip']}: {p['bad']} {p['rect']}")
            for t in s["tips"]:
                if not t["ok"]:
                    out.append(f"{w}px {s['state']}: chart tooltip {t['tip']}: {t['bad']} {t.get('rect')}")
            for x in s["clicks"]["bad"]:
                out.append(f"{w}px {s['state']}: {x}")
        f = W["forget"]
        if not (f["asked"] and f["after_cancel"] == [True, []] and f["after_yes"] == ["forget"]):
            out.append(f"{w}px: Forget: {f}")
        if W["page_loads_after_unlock"]:
            out.append(f"{w}px: {W['page_loads_after_unlock']} page load(s) after the unlock")
        for e in W["errors"][:5]:
            out.append(f"{w}px: script error: {e[:200]}")
    return out


def summary(report: dict) -> list:
    lines = []
    for w, W in report["widths"].items():
        S = [s for s in W["states"] if "sweep" in s]
        pts = sum(s["sweep"]["points"] for s in S)
        ver = [v["ok"] for s in S for v in s["sweep"].get("verified", [])]
        lines.append(f"{w}px: {len(W['states'])} states, {pts:,} points, "
                     f"{sum(len(s['pops']) for s in S)} popovers, {sum(len(s['tips']) for s in S)} chart tooltips, "
                     f"{sum(s['clicks']['clicked'] for s in S)} taps; covered targets tapped {len(ver)} "
                     f"(reached the drawn one: {sum(ver)}); overlapping tap areas "
                     f"{sum(len(s['sweep']['overlap']) for s in S)}; script errors {len(W['errors'])}")
    return lines


@contextlib.contextmanager
def serve(directory):
    """The publish directory over http on a free local port (fetch needs a server)."""
    handler = functools.partial(_Quiet, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    finally:
        srv.shutdown()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("publish_dir")
    ap.add_argument("passphrase")
    ap.add_argument("--widths", default="390,360,1280")
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    d = Path(a.publish_dir).resolve()
    if d.parts[-2:] == ("output", "hub_publish"):
        print("REFUSED: the sweep opens a SYNTHETIC publish only, never the real league's")
        return 2
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("NOT AVAILABLE: pip install playwright (and a Chrome)")
        return 2
    want = [s for s in SIZES if str(s[0]) in a.widths.split(",")]
    with serve(d) as url:
        rep = run(url, a.passphrase, want, chrome=a.chrome)
    if a.out:
        Path(a.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for line in summary(rep):
        print(line)
    bad = failures(rep)
    print("PASS: every check passed." if not bad else "FAIL:\n  - " + "\n  - ".join(bad[:60]))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
