// The new hub's published index.html in jsdom (5a): the v2 shell's open step
// (gunzip), its old-browser message, a wrong passphrase, and the current
// hub's #v-... links landing on the new screens. Run by tests/test_hub_switch.py
// only where node and jsdom are installed (NODE_PATH or HUB_TEST_JSDOM).
// Nothing leaves the machine: every fetch reads the test's own publish folder.
//
//   node shell_v2.js <publish dir> <passphrase> <scenario JSON>
//
// scenario: {"old": true (no DecompressionStream), "hash": "#v-roster-X" (the
// URL's hash at load), "part": true (open the first data-part pane's file),
// "forget": true (5c: "Forget this phone" asks first, in the page: HUB.forget
// and window.confirm recorded, never run)}
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');
const nodeCrypto = require('crypto');

const [dir, pass, scenarioText] = process.argv.slice(2);
const sc = JSON.parse(scenarioText || '{}');
const html = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => { if (!/navigation|Not implemented/.test(String(e.message))) errors.push(String(e.message)); });
vc.on('error', (e) => errors.push(String(e)));
const dom = new JSDOM(html, {
  url: 'https://hub.test/' + (sc.hash || ''), runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(w) {
    Object.defineProperty(w, 'crypto', { value: nodeCrypto.webcrypto, configurable: true });
    w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.Blob = Blob; w.Response = Response;
    if (!sc.old) { w.DecompressionStream = DecompressionStream; }
    w.URL.createObjectURL = () => 'blob:test';
    w.scrollTo = () => {};
    w.fetch = (file) => {
      const rel = String(file).replace(/^\.\//, '');
      let buf;
      try { buf = fs.readFileSync(path.join(dir, rel)); } catch (e) {
        return Promise.resolve({ ok: false, status: 404, arrayBuffer: () => Promise.reject(new Error('404')) });
      }
      const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
      return Promise.resolve({ ok: true, status: 200, arrayBuffer: () => Promise.resolve(ab) });
    };
  },
});
const w = dom.window;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) { return true; } await sleep(25); }
  return false;
}
(async () => {
  const out = {};
  const d = w.document;
  await until(() => d.getElementById('unlock') && !d.getElementById('unlock').hidden);
  out.form = !!d.getElementById('unlock') && !d.getElementById('unlock').hidden;
  out.msg_before = (d.getElementById('msg') || {}).textContent || '';
  out.button_disabled = !!(d.getElementById('go') || {}).disabled;
  if (!out.button_disabled) {
    d.getElementById('pass').value = pass;
    d.getElementById('unlock').dispatchEvent(new w.Event('submit', { cancelable: true }));
    await until(() => w.HUB || ((d.getElementById('msg') || {}).textContent || '') !== '');
    await sleep(100);
  }
  out.mounted = !!w.HUB;
  out.msg = (d.getElementById('msg') || {}).textContent || '';
  if (w.HUB) {
    const vis = [...d.querySelectorAll('.v2-screen')].filter((s) => !s.hidden).map((s) => s.getAttribute('data-route'));
    out.screen = vis;
    out.hash = w.location.hash;
    const sel = [...d.querySelectorAll('.v2-screen:not([hidden]) .lh-seg [aria-selected="true"]')].map((b) => b.getAttribute('data-pane'));
    out.selected = sel;
    out.cmp_rows = d.querySelectorAll('.v2-cmp-row').length;
    out.cmp_text = ((d.getElementById('cmp-rows') || {}).textContent || '').slice(0, 200);
    if (sc.forget) {
      const calls = [];
      const realForget = w.HUB.forget;
      w.HUB.forget = () => { calls.push('forget'); };
      w.confirm = () => { calls.push('confirm'); return true; };
      const shown = () => !d.getElementById('forget-ask').hidden;
      const click = (id) => d.getElementById(id).dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
      const f = {};
      f.stored_before = w.localStorage.getItem('hub-key-v1') !== null;
      click('forget'); f.asked = shown(); f.question = d.getElementById('forget-q').textContent;
      f.buttons = [...d.querySelectorAll('#forget-ask button')].map((b) => b.textContent);
      f.focus = (d.activeElement || {}).id || '';
      f.calls_on_ask = calls.slice();
      click('forget-no'); f.after_cancel = [shown(), calls.slice()];
      click('forget'); d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      f.after_escape = [shown(), calls.slice()];
      click('forget'); click('forget-yes'); f.after_yes = [shown(), calls.slice()];
      f.stored_after_stub = w.localStorage.getItem('hub-key-v1') !== null;
      try { realForget(); } catch (e) { /* jsdom: location.reload is not implemented */ }
      f.stored_after_real = w.localStorage.getItem('hub-key-v1') !== null;
      out.forget = f;
    }
    if (sc.d5) {
      // 5d1: the title-odds highlight (s.4), a column's definition (s.5), the season picker (s.8)
      const r = {};
      const go = async (h) => { w.location.hash = h; await sleep(50); };
      await go('#/league/standings?hl=' + sc.d5);
      await until(() => d.querySelector('[data-section="title-odds"] svg.lh-chart'));
      await sleep(100);
      let svg = d.querySelector('[data-section="title-odds"] svg.lh-chart');
      r.hl_on = !!svg && svg.classList.contains('v2-hl');
      r.hl_lines = svg ? [...svg.querySelectorAll('.v2-hl-on')].map((g) => g.getAttribute('data-m')) : [];
      svg.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
      r.hl_after_tap = svg.classList.contains('v2-hl');
      r.hash_after_tap = w.location.hash;
      // a column's definition: Standings' W-L (no sort)
      const wl = d.querySelector('[data-colh="standings|wl"]');
      wl.click(); const pop = d.getElementById('v2-colpop');
      r.pop_wl = pop && !pop.hidden ? pop.textContent : '';
      r.pop_wl_sort = pop ? pop.querySelectorAll('.v2-colsort-b').length : -1;
      wl.click(); r.pop_closed = !pop || pop.hidden;
      // a sortable one: Players' FPPG, sorted from inside the popover
      await go('#/players');
      const fp = d.querySelector('[data-colh="players|fppg"]');
      const tbl = d.getElementById('pl-table');
      const before = tbl.getAttribute('data-pcol');
      fp.click();
      r.players_sorted_by_tap = tbl.getAttribute('data-pcol') !== before;
      const sb = d.querySelector('#v2-colpop .v2-colsort-b');
      r.pop_fp_sort = !!sb;
      if (sb) { sb.click(); }
      r.players_sorted_from_pop = tbl.getAttribute('data-pcol') === 'fppg';
      r.pop_fp_state = (d.querySelector('#v2-colpop .v2-colsort-st') || {}).textContent || '';
      d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      r.pop_escape_closed = d.getElementById('v2-colpop').hidden;
      // the season picker: History > Trades
      await go('#/league/history/trades');
      await until(() => d.querySelector('[data-spick="trades"]'));
      const sel = d.querySelector('[data-spick="trades"]');
      r.seasons = sel ? [...sel.options].map((o) => o.value) : [];
      r.default_season = sel ? sel.value : '';
      if (sel && sel.options.length > 1) {
        const past = sel.options[sel.options.length - 1].value;
        sel.value = past; sel.dispatchEvent(new w.Event('change', { bubbles: true }));
        await sleep(100);
        r.hash_after_pick = w.location.hash;
        const pane = d.querySelector('[data-spick-of="trades|' + past + '"]');
        await until(() => pane && pane.getAttribute('data-loaded') === '1');
        r.past_loaded = !!pane && !pane.hidden && pane.getAttribute('data-loaded') === '1';
        r.past_text = pane ? pane.textContent.slice(0, 80) : '';
        r.other_panes_hidden = [...d.querySelectorAll('[data-spick-of^="trades|"]')].filter((x) => !x.hidden).length === 1;
      }
      r.all_issues = (d.querySelector('a.v2-allissues') || {}).getAttribute ? d.querySelector('a.v2-allissues').getAttribute('href') : '';
      out.d5 = r;
    }
    if (sc.part) {
      const pane = d.querySelector('[data-part]');
      const ref = JSON.parse(pane.getAttribute('data-part'));
      try { const obj = await w.HUB.part(ref); out.part_html = (obj.html || '').length; } catch (e) { out.part_error = String(e); }
    }
  }
  out.errors = errors;
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { process.stdout.write(JSON.stringify({ fatal: String(e), errors })); process.exit(0); });
