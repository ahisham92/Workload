/* Selecao+ — kit.js: the control kit's moving parts (styles in kit.css).
 *
 *  - kit.toast(): a message bar that closes itself: an icon and a word for
 *    how it stands, the message, a close button; the pointer over it holds it.
 *  - Number boxes: every number field takes a sum ("6*7.5", "40/5 + 2"),
 *    shows what it will keep ("= 45 h") while you type, keeps to its lowest
 *    and highest, steps with the arrow keys (Shift for a tenth), Enter keeps
 *    it, Escape puts it back. Nothing is sent until the sum is whole, so an
 *    edit never saves half a sum.
 *  - The finder: Ctrl K (or the search button in the top bar) finds any tab,
 *    project or person by a few letters of its name and goes there.
 *  - Initials: each person on the Team table gets a round badge with their
 *    initials in their own colour.
 * Spreadsheet cells (sheet.js) keep their own plain fields.
 */
(function () {
  'use strict';

  const ICON = {
    info: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/></svg>',
    ok: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16.5 9.5"/></svg>',
    warn: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 4.2 2.6 17.6A2 2 0 0 0 4.3 20.6h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4.5M12 17.2v.3"/></svg>',
    bad: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m6 6 12 12M18 6 6 18"/></svg>',
    search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    folder: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    person: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/></svg>',
  };
  /* The word that goes with each colour, so the colour is never the only sign. */
  const WORD = { ok: 'Done', warn: 'Note', bad: 'Problem', info: '' };
  const sevOf = (kind) => (kind === 'bad' || kind === 'warn' || kind === 'ok' ? kind : 'info');

  function h(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'html') node.innerHTML = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
    return node;
  }

  /* --------------------------------------------------------- message bars */
  function infoBar({ kind = 'info', message = '', word, action = null, onClose = null }) {
    const sev = sevOf(kind);
    const say = word === undefined ? WORD[sev] : word;
    return h('div', { class: 'infobar', 'data-sev': sev, role: sev === 'bad' ? 'alert' : 'status' },
      h('span', { class: 'k-ico infobar-ico', html: ICON[sev] }),
      h('div', { class: 'infobar-body' },
        say ? h('span', { class: 'infobar-word' }, say) : null,
        h('span', { class: 'infobar-text' }, message)),
      action,
      onClose ? h('button', { type: 'button', class: 'infobar-close', 'aria-label': 'Close', title: 'Close', html: ICON.close, onclick: onClose }) : null);
  }

  function toast(message, kind = '') {
    const host = document.getElementById('toasts');
    if (!host) return null;
    const life = kind === 'bad' ? 8000 : 3800;
    let timer = null;
    let left = life;
    let since = 0;
    const leave = () => {
      clearTimeout(timer);
      bar.classList.add('is-leaving');
      setTimeout(() => bar.remove(), 260);
    };
    const bar = infoBar({ kind, message, onClose: leave });
    bar.classList.add('toast', sevOf(kind));
    bar.style.setProperty('--life', `${life}ms`);
    const run = () => { since = Date.now(); timer = setTimeout(leave, left); };
    bar.addEventListener('pointerenter', () => { clearTimeout(timer); left -= Date.now() - since; });
    bar.addEventListener('pointerleave', run);
    // Never more than three at once: the oldest goes.
    while (host.children.length >= 3) host.firstElementChild.remove();
    host.append(bar);
    run();
    return bar;
  }

  /* ----------------------------------------------------------- number boxes */
  /** A sum as typed: numbers, + - * / and brackets; "," as a decimal point. */
  function evaluate(text) {
    let s = String(text).trim().replace(/[×x]/g, '*').replace(/÷/g, '/').replace(/−/g, '-')
      .replace(/\s*(h|hrs?|hours?|%|mm|weeks?|days?)\s*$/i, '');
    s = s.replace(/(\d),(\d{3})(?!\d)/g, '$1$2');   // 1,000 is a thousand
    if (!s.includes('.') && /^[\d\s,+\-*/()]+$/.test(s)) s = s.replace(/(\d),(\d)/g, '$1.$2');   // 7,5 is 7.5
    s = s.replace(/,/g, '');
    if (!s || !/^[\d\s.+\-*/()]+$/.test(s)) return null;
    let i = 0;
    const peek = () => { while (s[i] === ' ') i += 1; return s[i]; };
    function num() {
      const c = peek();
      if (c === '(') { i += 1; const v = sum(); if (peek() !== ')') throw 0; i += 1; return v; }
      if (c === '-') { i += 1; return -num(); }
      if (c === '+') { i += 1; return num(); }
      const m = /^\d*\.?\d+|^\d+\.?/.exec(s.slice(i));
      if (!m) throw 0;
      i += m[0].length;
      return parseFloat(m[0]);
    }
    function product() {
      let v = num();
      for (;;) {
        const c = peek();
        if (c === '*') { i += 1; v *= num(); } else if (c === '/') { i += 1; const d = num(); if (!d) throw 0; v /= d; } else return v;
      }
    }
    function sum() {
      let v = product();
      for (;;) {
        const c = peek();
        if (c === '+') { i += 1; v += product(); } else if (c === '-') { i += 1; v -= product(); } else return v;
      }
    }
    try {
      const v = sum();
      if (peek() !== undefined || !Number.isFinite(v)) return null;
      return v;
    } catch (_) { return null; }
  }
  const PLAIN = /^\s*-?(\d+([.,]\d*)?|[.,]\d+)?\s*$/;

  function decimalsOf(input) {
    const step = input.getAttribute('step');
    if (!step || step === 'any') return 2;
    const d = (step.split('.')[1] || '').length;
    return Math.max(d, 0);
  }
  const tidy = (v, input) => {
    const d = Math.max(decimalsOf(input), 2);
    return String(Number(v.toFixed(d)));
  };

  function unitOf(input) {
    if (input.dataset.unit !== undefined) return input.dataset.unit;
    const label = (input.closest('label')?.textContent || input.getAttribute('aria-label')
      || input.placeholder || input.name || '').toLowerCase();
    if (/%|percent|share/.test(label)) return '%';
    if (/\bmm\b|man-month|budget/.test(label)) return 'MM';
    if (/hour|\bh\b/.test(label)) return 'h';
    if (/week/.test(label)) return 'weeks';
    if (/day/.test(label)) return 'days';
    return '';
  }

  let bubble = null;
  function say(input, text, bad = false) {
    if (!text) { if (bubble) bubble.hidden = true; return; }
    if (!bubble) {
      bubble = h('div', { class: 'numbox-say', role: 'status', 'aria-live': 'polite' });
      document.body.append(bubble);
    }
    bubble.textContent = text;
    bubble.classList.toggle('is-bad', bad);
    bubble.hidden = false;
    const r = input.getBoundingClientRect();
    bubble.style.position = 'fixed';
    bubble.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 220))}px`;
    bubble.style.top = `${r.bottom + 4}px`;
  }
  let sayTimer = null;
  const sayFor = (input, text, bad, ms = 2600) => {
    say(input, text, bad);
    clearTimeout(sayTimer);
    sayTimer = setTimeout(() => say(null, ''), ms);
  };

  function bounds(input) {
    const lo = input.getAttribute('min');
    const hi = input.getAttribute('max');
    return [lo === null || lo === '' ? -Infinity : Number(lo), hi === null || hi === '' ? Infinity : Number(hi)];
  }

  /** Turn what was typed into the number to keep; false if it cannot be. */
  function commit(input) {
    const raw = input.value;
    if (raw.trim() === '') return true;
    let v = evaluate(raw);
    if (v === null) {
      const back = input._kitBefore ?? '';
      input.value = back;
      sayFor(input, back === '' ? 'Not a number, so left empty' : `Not a number, so kept ${back}`, true);
      return false;
    }
    const unit = unitOf(input);
    const [lo, hi] = bounds(input);
    if (v < lo) { v = lo; sayFor(input, `The least is ${lo}${unit ? ` ${unit}` : ''}, so set to that`, true); }
    else if (v > hi) { v = hi; sayFor(input, `The most is ${hi}${unit ? ` ${unit}` : ''}, so set to that`, true); }
    else if (!PLAIN.test(raw)) sayFor(input, `${raw.trim()} = ${tidy(v, input)}${unit ? ` ${unit}` : ''}`, false, 1800);
    else say(null, '');
    const next = tidy(v, input);
    if (input.value !== next) input.value = next;
    return true;
  }

  function stepBy(input, dir, fine) {
    const step = Number(input.getAttribute('step')) || 1;
    const by = fine ? step / 10 : step;
    const now = evaluate(input.value) ?? 0;
    const [lo, hi] = bounds(input);
    const v = Math.min(hi, Math.max(lo, now + dir * by));
    input.value = tidy(v, input);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    clearTimeout(input._kitStepTimer);
    input._kitStepTimer = setTimeout(() => input.dispatchEvent(new Event('change', { bubbles: true })), 500);
  }

  const isNum = (t) => t && t.tagName === 'INPUT' && t.dataset.kitNum === '1';

  function upgrade(input) {
    if (input.dataset.kitNum || input.closest('table.gsheet, .no-kit')) return;
    input.dataset.kitNum = '1';
    try { input.type = 'text'; } catch (_) { return; }
    input.inputMode = 'decimal';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.classList.add('k-number');
    if (!input.title) input.title = 'A number, or a sum like 6*7.5. Arrow keys step it.';
  }

  document.addEventListener('focusin', (e) => {
    if (isNum(e.target)) e.target._kitBefore = e.target.value;
  }, true);
  document.addEventListener('focusout', (e) => {
    // A warning stays up for its few seconds; a running sum goes.
    if (isNum(e.target) && bubble && !bubble.classList.contains('is-bad')) say(null, '');
  }, true);
  // While a sum is half typed, the page is not told: it hears the whole number.
  document.addEventListener('input', (e) => {
    const t = e.target;
    if (!isNum(t)) return;
    const raw = t.value;
    if (PLAIN.test(raw)) { if (bubble && !bubble.hidden && !bubble.classList.contains('is-bad')) say(null, ''); return; }
    e.stopImmediatePropagation();
    const v = evaluate(raw);
    const unit = unitOf(t);
    if (v === null) say(t, 'Finish the sum, or type a number', true);
    else say(t, `= ${tidy(v, t)}${unit ? ` ${unit}` : ''}`);
  }, true);
  document.addEventListener('change', (e) => {
    if (isNum(e.target)) commit(e.target);
  }, true);
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (!isNum(t)) return;
    if (e.key === 'Enter') {
      if (!PLAIN.test(t.value)) {
        commit(t);
        t.dispatchEvent(new Event('input', { bubbles: true }));
      }
    } else if (e.key === 'Escape' && t._kitBefore !== undefined && t.value !== t._kitBefore) {
      e.preventDefault();
      e.stopPropagation();
      t.value = t._kitBefore;
      say(null, '');
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      stepBy(t, e.key === 'ArrowUp' ? 1 : -1, e.shiftKey);
    }
  }, true);
  // A form sent with a sum still in a box sends the number instead.
  document.addEventListener('submit', (e) => {
    for (const input of e.target.querySelectorAll('input[data-kit-num="1"]')) commit(input);
  }, true);
  window.addEventListener('scroll', () => { if (bubble && !bubble.hidden) say(null, ''); }, true);

  /* ------------------------------------------------------------ initials */
  const AV_COLOURS = ['#1d5fa6', '#6d4bd8', '#0d8f7f', '#c2531a', '#b03a78', '#2f7d3a', '#0f6f8f', '#8a5a00'];
  function initials(name) {
    const parts = String(name).replace(/[^\p{L}\s'-]/gu, ' ').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '';
    return (parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  function colourFor(name) {
    let n = 0;
    for (const ch of String(name)) n = (n * 31 + ch.codePointAt(0)) >>> 0;
    return AV_COLOURS[n % AV_COLOURS.length];
  }
  function avatar(name) {
    // Drawn from an attribute, so the cell still reads (and sorts) as the name.
    const a = h('span', { class: 'k-avatar', 'aria-hidden': 'true', 'data-initials': initials(name) });
    a.style.setProperty('--av', colourFor(name));
    return a;
  }
  /** The first cell of each row on the Team table: a name. */
  function dressPeople(root) {
    for (const cell of root.querySelectorAll('#view-team table tbody tr > td:first-child')) {
      if (cell.querySelector('.k-avatar, input, select, button')) continue;
      const name = cell.textContent.trim();
      if (!name || name.length > 40 || /\d/.test(name)) continue;
      cell.prepend(avatar(name));
    }
  }

  /* ------------------------------------------------------------ the finder */
  const PATH_WORDS = { plan: 'Plan the week', workload: "See how we're doing", results: "See how we're doing", setup: 'Set up' };
  const norm = (t) => String(t).toLowerCase().replace(/\s+/g, '');
  /** Every word typed is somewhere in the text; spaces and case do not count. */
  function matches(text, query) {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const flat = norm(text);
    return words.every((w) => flat.includes(w));
  }
  function marked(text, query) {
    const frag = document.createDocumentFragment();
    const words = query.toLowerCase().split(/\s+/).filter(Boolean).sort((a, b) => b.length - a.length);
    if (!words.length) { frag.append(text); return frag; }
    const lower = text.toLowerCase();
    const hits = new Array(text.length).fill(false);
    for (const w of words) {
      let at = lower.indexOf(w);
      while (at >= 0) { for (let k = at; k < at + w.length; k += 1) hits[k] = true; at = lower.indexOf(w, at + 1); }
    }
    let run = '';
    let on = false;
    const flush = () => { if (!run) return; frag.append(on ? h('mark', {}, run) : run); run = ''; };
    for (let k = 0; k < text.length; k += 1) {
      if (hits[k] !== on) { flush(); on = hits[k]; }
      run += text[k];
    }
    flush();
    return frag;
  }

  function finderItems() {
    const items = [];
    for (const tab of document.querySelectorAll('#tabs .tab[data-view]')) {
      if (tab.id === 'tab-admin' && tab.hidden) continue;
      const label = tab.textContent.replace(/\s+/g, ' ').trim();
      const icon = tab.querySelector('svg');
      items.push({
        group: 'Tabs', title: label, sub: PATH_WORDS[tab.dataset.tone] || '',
        icon: icon ? icon.outerHTML : ICON.folder, tone: tab.dataset.tone,
        go: () => window.switchView(tab.dataset.view),
      });
    }
    try {
      for (const p of (typeof state !== 'undefined' && state.projects) || []) {
        items.push({
          group: 'Projects', title: `${p.number} ${p.name || ''}`.trim(), sub: p.status || '',
          icon: ICON.folder,
          go: () => { window.switchView('projects'); if (typeof openProject === 'function') openProject(p.number); },
        });
      }
      const people = (typeof state !== 'undefined' && state.reference && state.reference.engineers) || [];
      for (const e of people) {
        const name = e.name || e.full_name || e.short_name;
        items.push({
          group: 'People', title: name, sub: [e.grade, e.team].filter(Boolean).join(', '),
          avatar: e.short_name || name,
          go: () => {
            window.switchView('team');
            setTimeout(() => {
              const row = [...document.querySelectorAll('#view-team tbody tr')]
                .find((r) => r.textContent.includes(e.short_name || name));
              if (row) { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); row.classList.add('k-flash'); setTimeout(() => row.classList.remove('k-flash'), 1800); }
            }, 350);
          },
        });
      }
    } catch (_) { /* no unit open yet */ }
    return items;
  }

  let finder = null;
  function openFinder() {
    if (finder) return;
    const scrim = h('div', { class: 'k-find-scrim' });
    const input = h('input', { type: 'search', placeholder: 'Find a tab, project or person', 'aria-label': 'Find', autocomplete: 'off', spellcheck: 'false', enterkeyhint: 'go' });
    const list = h('div', { class: 'k-find-list', role: 'listbox', id: 'k-find-list', 'aria-label': 'What was found' });
    input.setAttribute('aria-controls', 'k-find-list');
    const box = h('div', { class: 'k-find', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Find' },
      h('label', { class: 'pick-search' }, h('span', { html: ICON.search, style: 'display:grid' }), input),
      list,
      h('div', { class: 'k-find-foot' },
        h('span', {}, h('kbd', {}, '↑'), ' ', h('kbd', {}, '↓'), ' move'),
        h('span', {}, h('kbd', {}, 'Enter'), ' go'),
        h('span', {}, h('kbd', {}, 'Esc'), ' close')));
    document.body.append(scrim, box);
    const all = finderItems();
    finder = { scrim, box, input, list, all, rows: [], at: 0, back: document.activeElement };
    const draw = () => {
      const q = input.value.trim();
      const found = q ? all.filter((it) => matches(`${it.title} ${it.sub}`, q)) : all.filter((it) => it.group === 'Tabs');
      found.sort((a, b) => (q ? (norm(b.title).startsWith(norm(q.split(/\s+/)[0])) - norm(a.title).startsWith(norm(q.split(/\s+/)[0]))) : 0));
      list.replaceChildren();
      finder.rows = [];
      let group = null;
      for (const it of found.slice(0, 60)) {
        if (it.group !== group) { group = it.group; list.append(h('div', { class: 'k-find-group', role: 'presentation' }, group)); }
        const ico = it.avatar ? avatar(it.avatar) : h('span', { class: 'k-row-ico', html: it.icon });
        if (it.tone) {
          ico.dataset.tone = it.tone;
          ico.style.setProperty('--row-tone', 'var(--tone)');
        }
        const row = h('button', { type: 'button', class: 'k-row', role: 'option', id: `k-find-${finder.rows.length}`, tabindex: '-1' },
          ico, h('span', { class: 'k-row-main' }, h('b', {}, marked(it.title, q)), it.sub ? h('small', {}, it.sub) : null));
        row.addEventListener('click', () => { closeFinder(false); it.go(); });
        row.addEventListener('pointermove', () => markRow(finder.rows.indexOf(row)));
        finder.rows.push(row);
        list.append(row);
      }
      if (!finder.rows.length) list.append(h('div', { class: 'pick-none' }, `Nothing called "${q}". Try fewer letters.`));
      markRow(0);
    };
    input.addEventListener('input', draw);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); markRow(finder.at + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); markRow(finder.at - 1); }
      else if (e.key === 'Enter') { e.preventDefault(); const row = finder.rows[finder.at]; if (row) row.click(); }
      else if (e.key === 'Escape') { e.preventDefault(); closeFinder(true); }
    });
    scrim.addEventListener('click', () => closeFinder(true));
    draw();
    input.focus();
  }
  function markRow(i) {
    if (!finder || !finder.rows.length) return;
    finder.at = Math.max(0, Math.min(finder.rows.length - 1, i));
    finder.rows.forEach((r, k) => { r.classList.toggle('is-on', k === finder.at); r.setAttribute('aria-selected', String(k === finder.at)); });
    finder.input.setAttribute('aria-activedescendant', finder.rows[finder.at].id);
    finder.rows[finder.at].scrollIntoView({ block: 'nearest' });
  }
  function closeFinder(refocus) {
    if (!finder) return;
    const { scrim, box, back } = finder;
    finder = null;
    scrim.remove();
    box.remove();
    if (refocus && back && back.focus) back.focus({ preventScroll: true });
  }
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
      const shell = document.getElementById('tabs');
      if (!shell || shell.hidden) return;
      e.preventDefault();
      if (finder) closeFinder(true); else openFinder();
    }
  });
  function addFindButton() {
    const bar = document.querySelector('#topbar .topbar-actions');
    if (!bar || bar.querySelector('.k-find-btn')) return;
    const mac = /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent);
    const btn = h('button', { type: 'button', class: 'k-find-btn', 'aria-label': 'Find a tab, project or person', title: 'Find a tab, project or person' },
      h('span', { html: ICON.search, style: 'display:grid' }), h('span', {}, 'Find'), h('kbd', {}, mac ? '⌘ K' : 'Ctrl K'));
    btn.addEventListener('click', openFinder);
    bar.prepend(btn);
  }

  /* -------------------------------------------------- now, and as it changes */
  function scan(root) {
    if (root.nodeType !== 1) return;
    if (root.matches('input[type="number"]')) upgrade(root);
    for (const i of root.querySelectorAll('input[type="number"]')) upgrade(i);
  }
  let peopleQueued = false;
  function start() {
    scan(document.body);
    addFindButton();
    dressPeople(document);
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) scan(n);
      if (!peopleQueued) {
        peopleQueued = true;
        requestAnimationFrame(() => { peopleQueued = false; dressPeople(document); });
      }
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  window.kit = { toast, infoBar, evaluate, avatar, initials, openFinder, icon: ICON };
})();
