// The hub's published page in jsdom (40b s.2): unlock the shell, tap a
// player name, report what the page shows. Run by tests/test_40b_fa_actuals.py
// only where node and jsdom are installed (NODE_PATH); nothing leaves the
// machine: every "fetch" reads the test's own publish directory.
//
//   node hub_loader.js <publish dir> <passphrase> <scenario JSON>
//
// scenario: {"gone": [paths answered 404], "corrupt": [paths whose bytes are
// flipped], "tap": card key, "reload": click Reload after, "session": a
// sessionStorage value to start with (no passphrase typed)}
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
const asked = [];

const dom = new JSDOM(html, {
  url: 'https://hub.test/', runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(w) {
    Object.defineProperty(w, 'crypto', { value: nodeCrypto.webcrypto, configurable: true });
    w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.Blob = Blob; w.Response = Response; w.DecompressionStream = DecompressionStream;
    w.URL.createObjectURL = () => 'blob:test';
    if (sc.session) { w.sessionStorage.setItem('hub-key-reload', sc.session); }
    w.fetch = (file) => {
      const rel = String(file).replace(/^\.\//, '');
      asked.push(rel);
      if ((sc.gone || []).includes(rel)) {
        return Promise.resolve({ ok: false, status: 404, arrayBuffer: () => Promise.reject(new Error('404')) });
      }
      let buf;
      try { buf = fs.readFileSync(path.join(dir, rel)); } catch (e) {
        return Promise.resolve({ ok: false, status: 404, arrayBuffer: () => Promise.reject(new Error('404')) });
      }
      if ((sc.corrupt || []).includes(rel)) { buf = Buffer.from(buf); for (let i = 12; i < buf.length; i++) { buf[i] ^= 0xff; } }
      const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
      return Promise.resolve({ ok: true, status: 200, arrayBuffer: () => Promise.resolve(ab) });
    };
  },
});
const w = dom.window;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, ms = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) { return true; } await sleep(25); }
  return false;
}
(async () => {
  const out = {};
  await until(() => w.document.getElementById('unlock') && (!w.document.getElementById('unlock').hidden || w.HUB));
  if (!w.HUB) {
    out.prompted = true;
    w.document.getElementById('pass').value = pass;
    w.document.getElementById('unlock').dispatchEvent(new w.Event('submit', { cancelable: true }));
  } else {
    out.prompted = false;
  }
  out.mounted = await until(() => !!w.HUB && !!w.document.querySelector('[data-card]'));
  if (out.mounted && sc.tap) {
    const el = w.document.querySelector(`[data-card="${sc.tap}"]`);
    el.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
    await until(() => w.document.getElementById('hub-moved') || w.document.querySelector('.stale') ||
                      (w.document.getElementById('pc-modal') && w.document.getElementById('pc-modal').classList.length));
    await sleep(300);
  }
  const moved = w.document.getElementById('hub-moved');
  out.moved = moved ? moved.textContent : null;
  out.moved_button = moved ? !!moved.querySelector('button.reload') : false;
  out.alerts = Array.from(w.document.querySelectorAll('.stale')).filter((d) => d.id !== 'hub-moved' && d.id !== 'stale')
    .map((d) => d.textContent);
  out.modal = !!(w.document.getElementById('pc-modal'));
  if (sc.reload && moved) {
    moved.querySelector('button.reload').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    out.session_after_reload = w.sessionStorage.getItem('hub-key-reload');
  }
  out.asked = asked;
  out.errors = errors;
  process.stdout.write(JSON.stringify(out));
  w.close();
  process.exit(0);
})().catch((e) => { process.stdout.write(JSON.stringify({ crash: String(e && e.stack || e) })); process.exit(2); });
