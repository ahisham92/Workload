/* The loading bar: a container ship sails along the water while the server
   works, and ties up at the quay when it is done -- the same ship as AHM's
   Triton.  It comes up for anything that takes more than a moment (opening a
   unit, an upload, a download, a slow page), so a wait never looks like a
   stuck page.  Quick answers never show it: the veil fades in only after a
   short delay.

   voyage.during(label, fn, key)  -- keep the ship up, with this label, while fn runs
   voyage.trip(label, key)        -- one request; returns a function to call when done
   The page's first load is a trip of its own, ended by voyage.ready().

   The words under the ship say how long is LEFT, not how long it has been:
   this browser remembers how long each kind of work (the key; by default the
   label) took before, and counts down from that.  With nothing remembered yet
   it starts from a fair guess for that kind of work.  Past the estimate it
   says "almost done" rather than counting up or going below zero. */

const voyage = (() => {
  const SHIP = `<svg class="ship" viewBox="0 0 64 26" aria-hidden="true">
  <path class="hull" d="M2 15h58l-5 8H8z"/><path class="boot" d="M5.2 20h52.6l-2 3H8z"/>
  <rect class="bridge" x="6" y="5" width="7" height="10" rx="1"/><rect class="win" x="7" y="7" width="5" height="1.6"/>
  <rect class="funnel" x="8" y="1.5" width="3" height="3.5"/>
  <g class="boxes"><rect x="16" y="10" width="8" height="5" fill="#e0583a"/><rect x="25" y="10" width="8" height="5" fill="#f2b033"/>
  <rect x="34" y="10" width="8" height="5" fill="#2f9e6e"/><rect x="43" y="10" width="8" height="5" fill="#1e8fc0"/>
  <rect x="20" y="5" width="8" height="5" fill="#1e8fc0"/><rect x="29" y="5" width="8" height="5" fill="#e0583a"/>
  <rect x="38" y="5" width="8" height="5" fill="#f2b033"/></g>
  <path class="line" d="M60 14.5Q67 13 74.5 9.5M56 15Q66 14.5 74 10.5"/></svg>`;

  // How far the ship gets while waiting: in step with the time expected, up to
  // ON_TIME of the way when that time is up, then ever slower, never reaching
  // the quay before the work is done.
  const ON_TIME = 0.9;
  const CREEP_MAX = 0.97;

  // How long each kind of work took before, kept in this browser only.
  const MEMORY = 'selecao.voyage.times';
  const KEEP = 80;                     // kinds of work remembered at most
  let times = null;
  function remembered() {
    if (times) return times;
    times = {};
    try {
      const kept = JSON.parse(localStorage.getItem(MEMORY) || '{}');
      if (kept && typeof kept === 'object') times = kept;
    } catch (_) { /* private window or blocked storage: start from guesses */ }
    return times;
  }
  function remember(key, ms) {
    if (!key || !(ms > 0)) return;
    const all = remembered();
    const before = all[key] && all[key].ms;
    // Lean on the latest runs without letting one odd run swing it.
    const ms2 = before ? before * 0.6 + ms * 0.4 : ms;
    delete all[key];
    all[key] = { ms: Math.round(ms2) };
    const keys = Object.keys(all);
    for (let i = 0; i < keys.length - KEEP; i += 1) delete all[keys[i]];
    try { localStorage.setItem(MEMORY, JSON.stringify(all)); } catch (_) { /* fine */ }
  }

  /** A first guess, in ms, for work never timed in this browser. */
  function guess(label) {
    const l = (label || '').toLowerCase();
    if (/reading the timesheets/.test(l)) return 20000;
    if (/upload/.test(l)) return 15000;
    if (/download/.test(l)) return 8000;
    if (/^opening/.test(l)) return 5000;
    return 2500;
  }
  function expected(key, label) {
    const known = remembered()[key];
    return known && known.ms > 0 ? known.ms : guess(label);
  }

  const open = [];   // { label, key, began, ms } for each piece of work under way
  let veil = null;
  let bar = null;
  let text = null;
  let since = 0;     // when the current voyage began
  let shown = 0;     // how far along the bar is, 0..1
  let landing = false;
  let frame = null;
  let hideTimer = null;

  function build() {
    veil = document.getElementById('voyage');
    if (!veil) {
      veil = document.createElement('div');
      veil.id = 'voyage';
      veil.className = 'voyage-veil';
      veil.hidden = true;
      document.body.append(veil);
    }
    veil.setAttribute('role', 'status');
    veil.setAttribute('aria-live', 'polite');
    veil.innerHTML = `<div class="voyage-box">
      <div class="voyage"><span class="sea"><i>${SHIP}</i></span><span class="quay" aria-hidden="true"><b></b></span></div>
      <p class="voyage-text"></p></div>`;
    bar = veil.querySelector('.sea i');
    text = veil.querySelector('.voyage-text');
  }

  /** When all the work under way should be done, by what we know. */
  function due() {
    return open.reduce((latest, w) => Math.max(latest, w.began + w.ms), since);
  }

  /** "about 12 s left", "about 2 min left": never below zero, never frozen. */
  function left(ms) {
    const seconds = Math.ceil(ms / 1000);
    if (seconds < 60) return `about ${seconds} s left`;
    return `about ${Math.round(seconds / 60)} min left`;
  }

  function words() {
    const label = open.length ? open[0].label : 'Done';
    const now = performance.now();
    if (landing || now - since < 1500) return `${label}…`;
    const remaining = due() - now;
    if (remaining >= 1000) return `${label}… ${left(remaining)}`;
    const over = now - due();
    if (over > 20000) return `${label}… almost done. Big files take a while.`;
    return `${label}… almost done`;
  }

  function paint() {
    bar.style.width = `${Math.max(shown * 100, 1)}%`;
    veil.querySelector('.voyage').classList.toggle('moored', shown >= 0.9995);
    const said = words();
    if (text.textContent !== said) text.textContent = said;
  }

  function tick() {
    const now = performance.now();
    if (landing) {
      shown = Math.min(1, shown + 0.06);
    } else {
      const span = Math.max(due() - since, 1);
      const t = now - since;
      const there = t <= span
        ? ON_TIME * (t / span)
        : ON_TIME + (CREEP_MAX - ON_TIME) * (1 - Math.exp(-(t - span) / span));
      shown = Math.max(shown, there);
    }
    paint();
    if (landing && shown >= 1) {
      frame = null;
      hideTimer = setTimeout(hide, 450);   // a moment at the quay, then gone
      return;
    }
    frame = requestAnimationFrame(tick);
  }

  function hide() {
    hideTimer = null;
    if (open.length) return;
    veil.hidden = true;
    veil.classList.remove('voyage-quick');
    landing = false;
    shown = 0;
  }

  function begin(label, key) {
    if (!veil) build();
    const named = label || 'Loading';
    const kind = key || named;
    const work = { label: named, key: kind, began: performance.now(), ms: expected(kind, named) };
    if (!open.length && (veil.hidden || landing)) {
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
      if (veil.hidden) { since = performance.now(); shown = 0; }
      landing = false;
      veil.hidden = false;
      // Showing straight after another voyage: no fade-in delay.
      veil.classList.toggle('voyage-quick', shown > 0);
    }
    landing = false;
    open.push(work);
    paint();
    if (!frame) frame = requestAnimationFrame(tick);
    let ended = false;
    return function end(failed) {
      if (ended) return;
      ended = true;
      if (failed !== true) remember(work.key, performance.now() - work.began);
      open.splice(open.indexOf(work), 1);
      if (!open.length) landing = true;
      if (!frame) frame = requestAnimationFrame(tick);
    };
  }

  async function during(label, work, key) {
    const end = begin(label, key);
    let failed = true;
    try {
      const result = await work();
      failed = false;
      return result;
    } finally { end(failed); }
  }

  // The first load: the veil is in the page already, so it is up while the
  // scripts and the first requests come in.
  let first = null;
  function startPage() {
    build();
    if (!veil.hasAttribute('data-opening')) return;
    const opening = veil.getAttribute('data-opening') || 'Opening';
    first = begin(opening, `page ${opening}`);
  }
  function ready() { if (first) { first(); first = null; } }

  // Loaded straight after the veil, so it is up before the rest of the page.
  if (document.getElementById('voyage') || document.readyState !== 'loading') {
    startPage();
  } else {
    document.addEventListener('DOMContentLoaded', startPage);
  }

  /** What a request is doing, in words, from its address and method. */
  function labelFor(path, method = 'GET') {
    const p = path.split('?')[0];
    if (/\/open$/.test(p)) return 'Opening the unit';
    if (/download|kit/.test(p) || (/import-key$/.test(p) && method === 'POST')) {
      return 'Preparing the download';
    }
    if (/from-timesheets|upload|replace|exports\/stage/.test(p)) return 'Uploading';
    if (/exports\/apply/.test(p)) return 'Reading the timesheets in';
    if (method === 'DELETE') return 'Removing';
    if (method !== 'GET') return 'Saving';
    return 'Loading';
  }

  /** The kind of a request for timing: its method and address, ids left out. */
  function keyFor(path, method = 'GET') {
    const p = path.split('?')[0]
      .split('/').map((part) => (/\d/.test(part) ? ':id' : part)).join('/');
    return `${method.toUpperCase()} ${p}`;
  }

  return { trip: begin, during, ready, labelFor, keyFor };
})();
