/* Workload — every table sorts by its headings and starts short.
 *
 * Tables are built all over app.js and member.js; rather than teach each one,
 * this watches the page and fixes up any table that appears:
 *
 *   - click a heading to sort by it, click again to reverse, a third time to
 *     put the table's own order back;
 *   - a long table shows its first rows and a "Show all" button under it.
 *
 *   - a long table (eight rows or more) gets a filter on each heading, as in
 *     Excel: tap the funnel, untick what to hide (with a search box for long
 *     lists), and a line over the table says how many rows show and clears
 *     each filter in one tap.
 *
 * All three survive a re-render: a table that is rebuilt with the same headings
 * in the same place keeps its sort and filters, and stays open if it was open.
 *
 * Tables opt out with data-plain. A table whose headings already sort
 * themselves (the project register) keeps its own sorting and only gets the
 * short view. Editable tables (.edit-table) keep every row in view, so a row
 * someone has just added is never hidden.
 */
(function () {
  'use strict';

  const SHORT = 10;          // rows shown before "Show all"
  const SLACK = 3;           // never hide just one or two rows
  const memory = new Map();  // signature -> { col, dir, open }

  const EMPTY = new Set(['', '—', '-', '–', 'n/a']);
  const NUMBER = /^[-−+]?\d[\d,]*(\.\d+)?\s*(%|×|x|h|mm)?$|^[-−+]?\.\d+\s*(%|×|x|h)?$/i;

  /** What a cell sorts by: a form field's value, else what it reads. */
  function cellValue(cell) {
    if (!cell) return '';
    if (cell.dataset.sort !== undefined) return cell.dataset.sort;
    const field = cell.querySelector('input, select, textarea');
    if (field) {
      if (field.type === 'checkbox') return field.checked ? '1' : '0';
      if (field.tagName === 'SELECT') {
        const option = field.options[field.selectedIndex];
        return option ? option.text.trim() : '';
      }
      return String(field.value).trim();
    }
    return cell.textContent.replace(/\s+/g, ' ').trim();
  }

  const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
    'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  const MON = '(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?';
  const monthNo = (name) => MONTHS.indexOf(name.toLowerCase()) + 1;
  const DATES = [
    // 08/10/2026, as every date is shown; may be followed by words ("overdue")
    [/^(\d{1,2})\/(\d{1,2})\/(\d{4})\b/, (m) => [m[3], m[2], m[1]]],
    // 2026-10-08 and 2026-10, as a data-sort carries them
    [/^(\d{4})-(\d{2})-(\d{2})\b/, (m) => [m[1], m[2], m[3]]],
    [/^(\d{4})-(\d{2})$/, (m) => [m[1], m[2], 0]],
    // 8 Oct 2026 / Thu 8 Oct 2026
    [new RegExp(`^(?:[a-z]{3},? )?(\\d{1,2}) ${MON},? (\\d{4})\\b`, 'i'),
      (m) => [m[3], monthNo(m[2]), m[1]]],
    // Oct 2026 / Oct ’26
    [new RegExp(`^${MON} (\\d{4})$`, 'i'), (m) => [m[2], monthNo(m[1]), 0]],
    [new RegExp(`^${MON} ’(\\d{2})$`, 'i'), (m) => [2000 + Number(m[2]), monthNo(m[1]), 0]],
  ];

  /** A day-first date (or an ISO one) as a number that sorts by the real date. */
  function dateKey(text) {
    for (const [re, parts] of DATES) {
      const m = re.exec(text);
      if (!m) continue;
      const [y, mo, d] = parts(m).map(Number);
      if (mo < 1 || mo > 12 || d > 31) return null;
      return y * 10000 + mo * 100 + d;
    }
    return null;
  }
  window.tablesDateKey = dateKey;   // for the tests

  function parse(text) {
    if (EMPTY.has(text.toLowerCase())) return null;
    const day = dateKey(text);
    if (day !== null) return { n: day };
    if (NUMBER.test(text)) {
      return { n: Number(text.replace(/[,\s%×xXhHmM+]/g, '').replace('−', '-')) };
    }
    return { s: text };
  }

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

  /** Blanks sink whichever way the sort runs. */
  function compare(a, b, dir) {
    if (a === null || b === null) return (a === null) - (b === null);
    if (a.n !== undefined && b.n !== undefined) return dir * (a.n - b.n);
    const left = a.n !== undefined ? String(a.n) : a.s;
    const right = b.n !== undefined ? String(b.n) : b.s;
    return dir * collator.compare(left, right);
  }

  function headerCells(table) {
    const row = table.tHead && table.tHead.rows[0];
    return row ? Array.from(row.cells) : [];
  }

  function bodyRows(table) {
    const body = table.tBodies[0];
    return body ? Array.from(body.rows) : [];
  }

  /** "No tasks match" and the like: one cell spanning the table. */
  function isPlaceholder(rows) {
    return rows.length === 1 && rows[0].cells.length === 1 && rows[0].cells[0].colSpan > 1;
  }

  function headingText(th) {
    return (th.dataset.label || th.textContent).replace(/[▲▼]/g, '').trim();
  }

  function signature(table) {
    const host = table.closest('[id]');
    const id = table.id || (host ? host.id : '');
    const heads = headerCells(table).map(headingText).join('|');
    const siblings = host
      ? Array.from(host.querySelectorAll('table')).filter(
        (t) => headerCells(t).map(headingText).join('|') === heads)
      : [table];
    return `${id}#${siblings.indexOf(table)}#${heads}`;
  }

  function remembered(table) {
    const key = table._autoKey;
    if (!memory.has(key)) memory.set(key, { col: null, dir: 1, open: false, filters: {} });
    return memory.get(key);
  }

  /** Total rows stay at the foot, whatever the sort. */
  const isTotal = (row) => row.classList.contains('total-row');

  function applySort(table) {
    const state = remembered(table);
    const body = table.tBodies[0];
    const rows = bodyRows(table);
    if (!body || isPlaceholder(rows)) return;
    const movable = rows.filter((r) => !isTotal(r));
    const totals = rows.filter(isTotal);
    if (state.col === null) {
      movable.sort((a, b) => a._autoOrder - b._autoOrder);
    } else {
      const keyed = movable.map((row) => ({ row, v: parse(cellValue(row.cells[state.col])) }));
      keyed.sort((a, b) => compare(a.v, b.v, state.dir) || a.row._autoOrder - b.row._autoOrder);
      movable.splice(0, movable.length, ...keyed.map((k) => k.row));
    }
    const ordered = movable.concat(totals);
    if (ordered.some((row, i) => body.rows[i] !== row)) body.append(...ordered);
    headerCells(table).forEach((th, i) => {
      if (!th._autoSort) return;
      const on = state.col === i;
      th.classList.toggle('sorted', on);
      th.setAttribute('aria-sort', on ? (state.dir === 1 ? 'ascending' : 'descending') : 'none');
      th.dataset.sortDir = on ? (state.dir === 1 ? 'asc' : 'desc') : '';
    });
  }

  /** Numbers open on their largest, words on A. */
  function looksNumeric(table, col) {
    const th = headerCells(table)[col];
    if (th && th.classList.contains('num')) return true;
    const values = bodyRows(table).map((r) => parse(cellValue(r.cells[col]))).filter(Boolean);
    return values.length > 0 && values.filter((v) => v.n !== undefined).length / values.length > 0.6;
  }

  function onHeaderClick(table, col) {
    const state = remembered(table);
    if (state.col !== col) {
      state.col = col;
      state.dir = looksNumeric(table, col) ? -1 : 1;
    } else if (state.dir === (looksNumeric(table, col) ? -1 : 1)) {
      state.dir = -state.dir;
    } else {
      state.col = null;
      state.dir = 1;
    }
    applySort(table);
    applyShort(table);
  }

  function bindSorting(table) {
    const heads = headerCells(table);
    const rows = bodyRows(table);
    if (!heads.length) return;
    // Let a table that sorts itself keep doing so.
    if (heads.some((th) => th.classList.contains('sortable') && !th._autoSort)) return;
    // Headings that do not line up with the cells cannot say what they sort.
    if (heads.some((th) => th.colSpan > 1)) return;
    if (rows.length && !isPlaceholder(rows)
        && rows.some((r) => !isTotal(r) && r.cells.length !== heads.length)) return;
    heads.forEach((th, i) => {
      if (!headingText(th) || th._autoSort) return;
      th._autoSort = true;
      th.classList.add('sortable', 'auto-sort');
      th.tabIndex = 0;
      th.title = th.title || `Sort by ${headingText(th).toLowerCase()}`;
      th.addEventListener('click', () => onHeaderClick(table, i));
      th.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onHeaderClick(table, i);
        }
      });
    });
  }

  /* -- filters on the headings ------------------------------------------------ */
  const FILTER_FROM = 8;     // rows before a table gets filters
  const FUNNEL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h18l-7 8.5V19l-4 2v-8.5z"/></svg>';
  const BLANK = '(empty)';
  const shown = (r) => !r.classList.contains('row-filtered');
  const keyFor = (row, col) => cellValue(row.cells[col]) || BLANK;

  function filterable(table) {
    if (table.classList.contains('edit-table') || table.hasAttribute('data-no-filter')) return false;
    const heads = headerCells(table);
    if (!heads.length || heads.some((th) => th.colSpan > 1)) return false;
    const rows = bodyRows(table).filter((r) => !isTotal(r));
    return !isPlaceholder(rows) && rows.length >= FILTER_FROM
      && rows.every((r) => r.cells.length === heads.length);
  }

  function columnValues(table, col) {
    const counts = new Map();
    for (const row of bodyRows(table)) {
      if (isTotal(row)) continue;
      const k = keyFor(row, col);
      counts.set(k, (counts.get(k) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => compare(parse(a[0] === BLANK ? '' : a[0]), parse(b[0] === BLANK ? '' : b[0]), 1));
  }

  function bindFilters(table) {
    const on = filterable(table);
    headerCells(table).forEach((th, i) => {
      if (!headingText(th)) return;
      let btn = th.querySelector(':scope > .tf-btn');
      if (!on) { if (btn) btn.remove(); return; }
      if (btn) { btn._col = i; return; }
      const distinct = columnValues(table, i).length;
      if (distinct < 2 || distinct > 120) return;
      btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tf-btn';
      btn.innerHTML = FUNNEL;
      btn._col = i;
      btn.setAttribute('aria-haspopup', 'dialog');
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('aria-label', `Filter ${headingText(th).toLowerCase()}`);
      btn.title = `Show only some ${headingText(th).toLowerCase()}`;
      btn.addEventListener('click', (e) => { e.stopPropagation(); openFilter(table, btn._col, btn); });
      btn.addEventListener('keydown', (e) => e.stopPropagation());
      th.append(btn);
    });
  }

  function applyFilter(table) {
    const state = remembered(table);
    const cols = Object.keys(state.filters).filter((c) => state.filters[c] && state.filters[c].size);
    const rows = bodyRows(table).filter((r) => !isTotal(r));
    if (isPlaceholder(rows)) return;
    for (const row of rows) {
      const out = cols.some((c) => state.filters[c].has(keyFor(row, +c)));
      row.classList.toggle('row-filtered', out);
    }
    headerCells(table).forEach((th, i) => {
      const btn = th.querySelector(':scope > .tf-btn');
      if (btn) btn.classList.toggle('is-on', Boolean(state.filters[i] && state.filters[i].size));
    });
    drawNote(table, cols, rows);
  }

  /** "Showing 6 of 32 rows" and a chip per filter, over the table. */
  function drawNote(table, cols, rows) {
    const anchor = table.parentElement && table.parentElement.classList.contains('table-wrap')
      ? table.parentElement : table;
    let note = table._tfNote;
    if (!cols.length) { if (note) { note.remove(); table._tfNote = null; } return; }
    if (!note) {
      note = document.createElement('div');
      note.className = 'tf-note';
      note.setAttribute('role', 'status');
      table._tfNote = note;
    }
    if (note.nextElementSibling !== anchor) anchor.before(note);
    const state = remembered(table);
    const showing = rows.filter(shown).length;
    note.replaceChildren(document.createTextNode(`Showing ${showing} of ${rows.length} rows.`));
    const heads = headerCells(table);
    for (const c of cols) {
      const chip = document.createElement('span');
      chip.className = 'k-chip';
      chip.textContent = `${headingText(heads[+c])}: ${state.filters[c].size} hidden`;
      const x = document.createElement('button');
      x.type = 'button';
      x.setAttribute('aria-label', `Show every ${headingText(heads[+c]).toLowerCase()} again`);
      x.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>';
      x.addEventListener('click', () => { delete state.filters[c]; refilter(table); });
      chip.append(x);
      note.append(chip);
    }
    if (cols.length > 1) {
      const all = document.createElement('button');
      all.type = 'button';
      all.className = 'btn btn-sm btn-ghost';
      all.textContent = 'Show every row';
      all.addEventListener('click', () => { state.filters = {}; refilter(table); });
      note.append(all);
    }
  }

  function refilter(table) {
    applyFilter(table);
    applyShort(table);
    if (pop && pop.table === table) drawPop();
  }

  let pop = null; // { table, col, btn, box, scrim, list, search }
  const phone = () => window.matchMedia('(max-width: 700px)').matches;

  function closeFilter(refocus) {
    if (!pop) return;
    const { box, scrim, btn } = pop;
    pop = null;
    box.remove();
    scrim.remove();
    btn.setAttribute('aria-expanded', 'false');
    if (refocus && btn.isConnected) btn.focus({ preventScroll: true });
  }

  function openFilter(table, col, btn) {
    if (pop) { const same = pop.btn === btn; closeFilter(false); if (same) return; }
    const th = headerCells(table)[col];
    const scrim = document.createElement('div');
    scrim.className = `tf-scrim${phone() ? ' is-dim' : ''}`;
    const box = document.createElement('div');
    box.className = `tf-pop${phone() ? ' is-sheet' : ''}`;
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', `Filter ${headingText(th).toLowerCase()}`);
    const tone = table.closest('[data-tone]');
    if (tone) box.dataset.tone = tone.dataset.tone;
    const head = document.createElement('div');
    head.className = 'tf-head';
    head.textContent = `Show which ${headingText(th).toLowerCase()}?`;
    box.append(head);
    const values = columnValues(table, col);
    let search = null;
    if (values.length > 8) {
      const label = document.createElement('label');
      label.className = 'pick-search';
      label.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>';
      search = document.createElement('input');
      search.type = 'search';
      search.placeholder = 'Type to find';
      search.setAttribute('aria-label', 'Find a value');
      label.append(search);
      box.append(label);
      search.addEventListener('input', drawPop);
    }
    const list = document.createElement('div');
    list.className = 'tf-list';
    box.append(list);
    const foot = document.createElement('div');
    foot.className = 'tf-foot';
    const clear = document.createElement('button');
    clear.type = 'button';
    clear.className = 'btn btn-sm btn-ghost';
    clear.textContent = 'Show all';
    clear.addEventListener('click', () => { delete remembered(table).filters[col]; refilter(table); });
    const done = document.createElement('button');
    done.type = 'button';
    done.className = 'btn btn-sm btn-primary';
    done.textContent = 'Done';
    done.addEventListener('click', () => closeFilter(true));
    foot.append(clear, done);
    box.append(foot);
    document.body.append(scrim, box);
    scrim.addEventListener('click', () => closeFilter(false));
    pop = { table, col, btn, box, scrim, list, search, values };
    btn.setAttribute('aria-expanded', 'true');
    drawPop();
    if (!phone()) {
      const r = btn.getBoundingClientRect();
      const w = 280;
      const left = Math.min(Math.max(12, r.right - w), window.innerWidth - w - 12);
      const below = window.innerHeight - r.bottom;
      box.style.left = `${left}px`;
      if (below < 300 && r.top > below) box.style.bottom = `${window.innerHeight - r.top + 6}px`;
      else box.style.top = `${r.bottom + 6}px`;
    }
    (search || list.querySelector('input') || done).focus({ preventScroll: true });
  }

  function drawPop() {
    if (!pop) return;
    const { table, col, list, search, values } = pop;
    const state = remembered(table);
    const out = state.filters[col] || new Set();
    const words = search ? search.value.toLowerCase().split(/\s+/).filter(Boolean) : [];
    const flat = (t) => t.toLowerCase().replace(/\s+/g, '');
    const seen = values.filter(([v]) => words.every((w) => flat(v).includes(w)));
    const row = (text, count, checked, onChange, cls = '') => {
      const label = document.createElement('label');
      label.className = `tf-row ${cls}`;
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = checked;
      box.indeterminate = checked === null;
      box.addEventListener('change', () => onChange(box.checked));
      const t = document.createElement('span');
      t.textContent = text;
      label.append(box, t);
      if (count !== null) { const n = document.createElement('small'); n.textContent = count; label.append(n); }
      return label;
    };
    const had = document.activeElement && list.contains(document.activeElement)
      ? [...list.querySelectorAll('input')].indexOf(document.activeElement) : -1;
    list.replaceChildren();
    const allOn = seen.every(([v]) => !out.has(v));
    const noneOn = seen.every(([v]) => out.has(v));
    list.append(row(words.length ? 'Every one found' : 'Select all', null, allOn ? true : (noneOn ? false : null), (on) => {
      const set = state.filters[col] || new Set();
      for (const [v] of seen) { if (on) set.delete(v); else set.add(v); }
      state.filters[col] = set;
      refilter(table);
    }, 'tf-all'));
    for (const [v, n] of seen) {
      list.append(row(v, n, !out.has(v), (on) => {
        const set = state.filters[col] || new Set();
        if (on) set.delete(v); else set.add(v);
        state.filters[col] = set;
        refilter(table);
      }));
    }
    if (had >= 0) { const again = list.querySelectorAll('input')[had]; if (again) again.focus({ preventScroll: true }); }
  }


  function applyShort(table) {
    const rows = bodyRows(table).filter((r) => !isTotal(r) && shown(r));
    const long = !table.classList.contains('edit-table')
      && !isPlaceholder(rows) && rows.length > SHORT + SLACK;
    const anchor = table.parentElement && table.parentElement.classList.contains('table-wrap')
      ? table.parentElement : table;
    let toggle = table._autoToggle;

    if (!long) {
      rows.forEach((r) => r.classList.remove('row-more'));
      table.classList.remove('is-short');
      if (toggle) { toggle.remove(); table._autoToggle = null; }
      return;
    }
    const state = remembered(table);
    rows.forEach((r, i) => r.classList.toggle('row-more', i >= SHORT));
    table.classList.toggle('is-short', !state.open);

    if (!toggle) {
      toggle = document.createElement('div');
      toggle.className = 'table-more';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-sm btn-ghost';
      button.addEventListener('click', () => {
        const s = remembered(table);
        s.open = !s.open;
        applyShort(table);
        if (!s.open) anchor.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      });
      toggle.append(button);
      table._autoToggle = toggle;
    }
    if (toggle.previousElementSibling !== anchor) anchor.after(toggle);
    const button = toggle.firstChild;
    button.textContent = state.open
      ? 'Show fewer'
      : `Show all ${rows.length.toLocaleString()} rows`;
    button.setAttribute('aria-expanded', String(state.open));
  }

  function enhance(table) {
    if (table.hasAttribute('data-plain')) return;
    const body = table.tBodies[0] || null;
    const count = body ? body.rows.length : 0;
    if (table._autoBody === body && table._autoHead === table.tHead
        && table._autoCount === count) return;
    const fresh = table._autoBody !== body || table._autoHead !== table.tHead;
    table._autoBody = body;
    table._autoHead = table.tHead;
    table._autoCount = count;
    table._autoKey = signature(table);
    if (fresh) bodyRows(table).forEach((row, i) => { row._autoOrder = i; });
    else bodyRows(table).forEach((row, i) => { if (row._autoOrder === undefined) row._autoOrder = 1e6 + i; });
    bindSorting(table);
    if (headerCells(table).some((th) => th._autoSort)) applySort(table);
    bindFilters(table);
    applyFilter(table);
    applyShort(table);
  }

  let queued = false;
  function sweep() {
    queued = false;
    document.querySelectorAll('table').forEach(enhance);
    // A toggle whose table has gone goes with it.
    document.querySelectorAll('.table-more').forEach((toggle) => {
      const prev = toggle.previousElementSibling;
      const table = prev && (prev.tagName === 'TABLE' ? prev : prev.querySelector('table'));
      if (!table || table._autoToggle !== toggle) toggle.remove();
    });
    document.querySelectorAll('.tf-note').forEach((note) => {
      const next = note.nextElementSibling;
      const table = next && (next.tagName === 'TABLE' ? next : next.querySelector('table'));
      if (!table || table._tfNote !== note) note.remove();
    });
    if (pop && (!pop.table.isConnected || !pop.table.offsetParent)) closeFilter(false);
  }
  function queue() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(sweep);
  }

  function start() {
    if (typeof window.addEventListener === 'function') {
      window.addEventListener('resize', () => closeFilter(false));
      window.addEventListener('keydown', (e) => {
        if (pop && e.key === 'Escape') { e.preventDefault(); closeFilter(true); }
      });
    }
    new MutationObserver(queue).observe(document.body, { childList: true, subtree: true });
    sweep();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());
