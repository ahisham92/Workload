/* The loading bar: a container ship sails along the water while the server
   works, and ties up at the quay when it is done -- the same ship as AHM's
   Triton.  It comes up for anything that takes more than a moment (opening a
   unit, an upload, a download, a slow page), so a wait never looks like a
   stuck page.  Quick answers never show it: the veil fades in only after a
   short delay.

   voyage.during(label, fn)  -- keep the ship up, with this label, while fn runs
   voyage.trip(label)        -- one request; returns a function to call when done
   The page's first load is a trip of its own, ended by voyage.ready(). */

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

  // How far the ship gets while waiting: most of the way in the first few
  // seconds, then ever slower, never reaching the quay before the work is done.
  const CREEP_SECONDS = 4;
  const CREEP_MAX = 0.92;

  const open = [];   // { label, began } for each piece of work under way
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

  function words() {
    const label = open.length ? open[0].label : 'Done';
    const seconds = Math.floor((performance.now() - since) / 1000);
    if (landing || seconds < 3) return `${label}…`;
    if (seconds < 20) return `${label}… ${seconds} s`;
    return `${label}… ${seconds} s. Still working: big files take a while.`;
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
      const t = (now - since) / 1000;
      shown = Math.max(shown, CREEP_MAX * (1 - Math.exp(-t / CREEP_SECONDS)));
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

  function begin(label) {
    if (!veil) build();
    const work = { label: label || 'Loading' };
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
    return function end() {
      if (ended) return;
      ended = true;
      open.splice(open.indexOf(work), 1);
      if (!open.length) landing = true;
      if (!frame) frame = requestAnimationFrame(tick);
    };
  }

  async function during(label, work) {
    const end = begin(label);
    try { return await work(); } finally { end(); }
  }

  // The first load: the veil is in the page already, so it is up while the
  // scripts and the first requests come in.
  let first = null;
  function startPage() {
    build();
    if (!veil.hasAttribute('data-opening')) return;
    first = begin(veil.getAttribute('data-opening') || 'Opening');
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

  return { trip: begin, during, ready, labelFor };
})();
