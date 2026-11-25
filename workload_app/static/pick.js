/* Selecao+ — pick.js: every drop-down drawn as the app's own list.
 *
 * The phone and the browser each draw a plain <select> their own way: a white
 * box with a cramped arrow that matches nothing else on the page. Each one is
 * dressed instead in a button in the tab's colour that opens a list (a sheet
 * from the bottom on a phone). The real <select> stays in the page, hidden,
 * and is still what the rest of the app reads and writes: choosing here sets
 * its value and fires its "change", and anything that changes it (new
 * options, a value set in code, disabled or hidden) shows on the button at
 * once. Keyboard: arrows, Home/End, Enter or Space, Escape, and typing the
 * first letters of an option.
 *
 * A long list (eight choices or more) opens with a search box: every word
 * typed must be in the choice, spaces and capitals do not count ("ap 12"
 * finds "Apapa Berth 12"), the letters found are marked, and choices that
 * start with the first word come first. The last five picked from that list
 * sit on top under "Recent" (kept in this browser only).
 *
 * Spreadsheet cells (sheet.js) keep their own plain drop-downs.
 */
(function () {
  'use strict';

  const CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
  const TICK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  const skip = (s) => s.multiple || s.size > 1 || s.closest('table.gsheet, .no-pick, [data-no-pick]');
  const phone = () => window.matchMedia('(max-width: 700px)').matches;
  let uid = 0;
  let open = null; // { select, button, list, sheet }

  // --- keeping the button in step with its <select> --------------------------
  const refreshSoon = new Set();
  let queued = false;
  function queue(select) {
    if (!select || !select._pick) return;
    refreshSoon.add(select);
    if (queued) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      for (const s of refreshSoon) refresh(s);
      refreshSoon.clear();
    });
  }
  // A value set in code fires no event, so the setters say so themselves.
  function watchSetter(proto, prop, selectOf) {
    const d = Object.getOwnPropertyDescriptor(proto, prop);
    if (!d || !d.set) return;
    Object.defineProperty(proto, prop, {
      configurable: true, enumerable: d.enumerable, get: d.get,
      set(v) { d.set.call(this, v); queue(selectOf(this)); },
    });
  }
  watchSetter(HTMLSelectElement.prototype, 'value', (s) => s);
  watchSetter(HTMLSelectElement.prototype, 'selectedIndex', (s) => s);
  watchSetter(HTMLOptionElement.prototype, 'selected', (o) => o.parentElement && o.closest('select'));

  function labelOf(select) {
    const named = select.getAttribute('aria-label');
    if (named) return named;
    const by = select.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map((id) => document.getElementById(id)?.textContent || '').join(' ').trim();
      if (t) return t;
    }
    const wrap = select.closest('label');
    if (wrap) {
      const span = wrap.querySelector(':scope > span');
      if (span) return span.textContent.trim();
    }
    if (select.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(select.id)}"]`);
      if (lab) return lab.textContent.trim();
    }
    return '';
  }

  function refresh(select) {
    const p = select._pick;
    if (!p) return;
    const opt = select.options[select.selectedIndex];
    p.text.textContent = opt ? opt.textContent : '';
    p.button.disabled = select.disabled;
    p.button.hidden = select.hidden || select.style.display === 'none';
    const name = labelOf(select);
    if (name) p.button.setAttribute('aria-label', `${name}: ${p.text.textContent}`);
    if (select.title) p.button.title = select.title;
    // The button is as wide as the longest choice, as a drop-down would be.
    const labels = [...select.options].slice(0, 80).map((o) => o.textContent);
    const key = labels.join('\u0001');
    if (key !== p.sizedFor) {
      p.sizedFor = key;
      p.sizer.replaceChildren(...labels.map((t) => {
        const s = document.createElement('span');
        s.textContent = t;
        return s;
      }));
    }
    if (open && open.select === select) fill(open);
  }

  function enhance(select) {
    if (select._pick) {
      // Moved, or put back: its button goes with it.
      if (select._pick.button.previousElementSibling !== select) select.after(select._pick.button);
      return;
    }
    if (skip(select)) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'pick';
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    const face = document.createElement('span');
    face.className = 'pick-face';
    const sizer = document.createElement('span');
    sizer.className = 'pick-sizer';
    sizer.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.className = 'pick-text';
    face.append(sizer, text);
    const chev = document.createElement('span');
    chev.className = 'pick-chev';
    chev.innerHTML = CHEVRON;
    button.append(face, chev);
    // Classes on the drop-down (sizes, places) carry over to the button.
    for (const c of select.classList) if (c !== 'pick-native') button.classList.add(c);
    select.classList.add('pick-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    select.after(button);
    select._pick = { button, text, sizer, sizedFor: null };
    button._select = select;

    button.addEventListener('click', () => (open && open.select === select ? close(true) : show(select)));
    button.addEventListener('keydown', (e) => {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' ', 'Home', 'End'].includes(e.key) && !(open && open.select === select)) {
        e.preventDefault();
        show(select);
      }
    });
    // A label tapped, or focus sent to the hidden drop-down, lands on the button.
    select.addEventListener('focus', () => button.focus());
    select.addEventListener('change', () => queue(select));
    new MutationObserver(() => queue(select)).observe(select, {
      childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ['disabled', 'hidden', 'style', 'label', 'title', 'aria-label'],
    });
    refresh(select);
  }

  // --- the list ---------------------------------------------------------------
  const SEARCH_FROM = 8;
  const RECENT = 5;
  const norm = (t) => String(t).toLowerCase().replace(/\s+/g, '');
  const wordsOf = (q) => q.toLowerCase().split(/\s+/).filter(Boolean);
  function hit(text, words) {
    const flat = norm(text);
    return words.every((w) => flat.includes(w));
  }
  /** The choice's words with what was typed marked. */
  function marked(text, words) {
    const span = document.createElement('span');
    if (!words.length) { span.textContent = text; return span; }
    const lower = text.toLowerCase();
    const on = new Array(text.length).fill(false);
    for (const w of words) {
      for (let at = lower.indexOf(w); at >= 0; at = lower.indexOf(w, at + 1)) {
        for (let k = at; k < at + w.length; k += 1) on[k] = true;
      }
    }
    let run = '';
    let lit = false;
    const flush = () => {
      if (!run) return;
      if (lit) { const m = document.createElement('mark'); m.textContent = run; span.append(m); } else span.append(run);
      run = '';
    };
    for (let k = 0; k < text.length; k += 1) {
      if (on[k] !== lit) { flush(); lit = on[k]; }
      run += text[k];
    }
    flush();
    return span;
  }
  /** Which list this is, so its recent picks are its own. */
  function keyOf(select) {
    return `pick-recent:${select.name || select.id || labelOf(select) || [...select.options].slice(0, 3).map((x) => x.value).join('|')}`;
  }
  function recentOf(select) {
    try { return JSON.parse(localStorage.getItem(keyOf(select)) || '[]'); } catch (_) { return []; }
  }
  function remember(select, value) {
    if (select.options.length < SEARCH_FROM || value === '') return;
    try {
      const list = [value, ...recentOf(select).filter((v) => v !== value)].slice(0, RECENT);
      localStorage.setItem(keyOf(select), JSON.stringify(list));
    } catch (_) { /* private window: no recents */ }
  }
  function optionRow(o, opt, i, words, suffix = '') {
    const row = document.createElement('div');
    row.className = 'pick-opt';
    row.id = `${o.list.id}-${i}${suffix}`;
    row.setAttribute('role', 'option');
    row.dataset.index = i;
    const on = i === o.select.selectedIndex;
    row.setAttribute('aria-selected', on ? 'true' : 'false');
    if (opt.disabled || opt.parentElement.disabled) row.setAttribute('aria-disabled', 'true');
    const tick = document.createElement('span');
    tick.className = 'pick-tick';
    tick.innerHTML = TICK;
    row.append(tick, marked(opt.textContent, words));
    return row;
  }
  function heading(text) {
    const h = document.createElement('div');
    h.className = 'pick-group';
    h.setAttribute('role', 'presentation');
    h.textContent = text;
    return h;
  }

  function fill(o) {
    const { select, list } = o;
    list.replaceChildren();
    const words = o.search ? wordsOf(o.search.value) : [];
    if (words.length) {
      const first = words[0];
      const found = [...select.options].map((opt, i) => ({ opt, i }))
        .filter(({ opt }) => !opt.hidden && hit(opt.textContent, words));
      found.sort((a, b) => norm(b.opt.textContent).startsWith(first) - norm(a.opt.textContent).startsWith(first) || a.i - b.i);
      for (const { opt, i } of found) list.append(optionRow(o, opt, i, words));
      if (!found.length) {
        const none = document.createElement('div');
        none.className = 'pick-none';
        none.textContent = 'Nothing matches. Try fewer letters.';
        list.append(none);
      }
      return;
    }
    if (o.search) {
      const values = [...select.options].map((x) => x.value);
      const recent = recentOf(select).map((v) => values.indexOf(v)).filter((i) => i >= 0 && !select.options[i].hidden);
      if (recent.length) {
        list.append(heading('Recent'));
        for (const i of recent) list.append(optionRow(o, select.options[i], i, [], '-r'));
        list.append(heading('All'));
      }
    }
    let group = null;
    [...select.options].forEach((opt, i) => {
      const parent = opt.parentElement;
      if (parent.tagName === 'OPTGROUP' && parent !== group) {
        group = parent;
        const h = document.createElement('div');
        h.className = 'pick-group';
        h.setAttribute('role', 'presentation');
        h.textContent = parent.label;
        list.append(h);
      }
      if (opt.hidden) return;
      list.append(optionRow(o, opt, i, []));
    });
  }

  const rows = (o) => [...o.list.querySelectorAll('.pick-opt:not([aria-disabled="true"])')];
  function mark(o, row) {
    for (const r of o.list.querySelectorAll('.pick-opt.is-on')) r.classList.remove('is-on');
    if (!row) return;
    row.classList.add('is-on');
    o.list.setAttribute('aria-activedescendant', row.id);
    row.scrollIntoView({ block: 'nearest' });
  }

  function place(o) {
    const { button, sheet } = o;
    if (phone()) {
      sheet.classList.add('is-sheet');
      sheet.style.cssText = '';
      return;
    }
    sheet.classList.remove('is-sheet');
    const r = button.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12;
    const above = r.top - 12;
    const goUp = below < 220 && above > below;
    const room = Math.max(160, Math.min(360, goUp ? above : below));
    const width = Math.max(r.width, Math.min(320, window.innerWidth - 24));
    const left = Math.min(Math.max(12, r.left), window.innerWidth - width - 12);
    sheet.style.cssText = `left:${left}px;width:${width}px;max-height:${room}px;` +
      (goUp ? `bottom:${window.innerHeight - r.top + 6}px;` : `top:${r.bottom + 6}px;`);
  }

  function show(select) {
    if (open) close(false);
    const button = select._pick.button;
    const sheet = document.createElement('div');
    sheet.className = 'pick-pop';
    const tone = button.closest('[data-tone]');
    if (tone) sheet.dataset.tone = tone.dataset.tone;
    const list = document.createElement('div');
    list.className = 'pick-list';
    list.id = `pick-${++uid}`;
    list.setAttribute('role', 'listbox');
    list.tabIndex = -1;
    const name = labelOf(select);
    if (name) list.setAttribute('aria-label', name);
    const scrim = document.createElement('div');
    scrim.className = 'pick-scrim';
    if (name && phone()) {
      const title = document.createElement('div');
      title.className = 'pick-title';
      title.textContent = name;
      sheet.append(title);
    }
    let search = null;
    if (select.options.length >= SEARCH_FROM) {
      search = document.createElement('input');
      search.type = 'search';
      search.placeholder = 'Type to find';
      search.autocomplete = 'off';
      search.spellcheck = false;
      search.setAttribute('aria-label', name ? `Find in ${name}` : 'Find');
      search.setAttribute('aria-controls', list.id);
      const box = document.createElement('label');
      box.className = 'pick-search';
      box.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>';
      box.append(search);
      sheet.append(box);
    }
    sheet.append(list);
    document.body.append(scrim, sheet);
    open = { select, button, list, sheet, scrim, search, typed: '', typedAt: 0 };
    fill(open);
    place(open);
    button.setAttribute('aria-expanded', 'true');
    button.setAttribute('aria-controls', list.id);
    // On a phone the keyboard would cover the list: the search box waits for a tap.
    if (search && !phone()) search.focus({ preventScroll: true });
    else list.focus({ preventScroll: true });
    mark(open, list.querySelector('[aria-selected="true"]') || rows(open)[0]);
    if (search) {
      search.addEventListener('input', () => {
        if (!open) return;
        fill(open);
        mark(open, rows(open)[0]);
      });
      search.addEventListener('keydown', (e) => {
        if (e.key.length === 1 || e.key === 'Backspace' || e.key === 'Delete' || e.key === 'Home' || e.key === 'End') return;
        onKey(e);
      });
    }

    list.addEventListener('click', (e) => {
      const row = e.target.closest('.pick-opt');
      if (row && row.getAttribute('aria-disabled') !== 'true') choose(+row.dataset.index);
    });
    list.addEventListener('pointermove', (e) => {
      const row = e.target.closest('.pick-opt');
      if (row && !row.classList.contains('is-on') && row.getAttribute('aria-disabled') !== 'true') mark(open, row);
    });
    list.addEventListener('keydown', onKey);
    scrim.addEventListener('click', () => close(false));
  }

  function onKey(e) {
    const o = open;
    if (!o) return;
    const all = rows(o);
    const at = all.indexOf(o.list.querySelector('.pick-opt.is-on'));
    const go = (i) => { e.preventDefault(); mark(o, all[Math.max(0, Math.min(all.length - 1, i))]); };
    switch (e.key) {
      case 'ArrowDown': return go(at + 1);
      case 'ArrowUp': return go(at - 1);
      case 'Home': return go(0);
      case 'End': return go(all.length - 1);
      case 'PageDown': return go(at + 8);
      case 'PageUp': return go(at - 8);
      case 'Enter': case ' ':
        e.preventDefault();
        if (at >= 0) choose(+all[at].dataset.index);
        return;
      case 'Escape': e.preventDefault(); close(true); return;
      case 'Tab': close(false); return;
      default:
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          const now = Date.now();
          o.typed = (now - o.typedAt < 700 ? o.typed : '') + e.key.toLowerCase();
          o.typedAt = now;
          const hit = all.find((r) => r.textContent.trim().toLowerCase().startsWith(o.typed));
          if (hit) mark(o, hit);
        }
    }
  }

  function choose(index) {
    const { select } = open;
    const changed = select.selectedIndex !== index;
    select.selectedIndex = index;
    remember(select, select.value);
    close(true);
    if (changed) {
      select.dispatchEvent(new Event('input', { bubbles: true }));
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  function close(refocus) {
    if (!open) return;
    const { button, sheet, scrim } = open;
    open = null;
    sheet.remove();
    scrim.remove();
    button.setAttribute('aria-expanded', 'false');
    button.removeAttribute('aria-controls');
    if (refocus && button.isConnected) button.focus({ preventScroll: true });
  }

  window.addEventListener('resize', () => { if (open) place(open); });
  // The page moving under a list placed beside its button closes it; a sheet stays.
  window.addEventListener('scroll', (e) => {
    if (open && !open.sheet.classList.contains('is-sheet') && !open.sheet.contains(e.target)) close(false);
  }, true);

  // --- every drop-down, now and later --------------------------------------------
  function scan(root) {
    if (root.nodeType !== 1) return;
    if (root.tagName === 'SELECT') enhance(root);
    else for (const s of root.querySelectorAll('select')) enhance(s);
  }
  function start() {
    scan(document.body);
    new MutationObserver((records) => {
      for (const r of records) {
        for (const n of r.addedNodes) scan(n);
        for (const n of r.removedNodes) {
          if (n.nodeType !== 1) continue;
          if (open && (n === open.button || n.contains(open.button))) close(false);
          // A drop-down taken out on its own takes its button with it.
          if (n.tagName === 'SELECT' && n._pick && !n.isConnected) n._pick.button.remove();
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
