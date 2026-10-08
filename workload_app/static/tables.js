/* Workload — every table sorts by its headings and starts short.
 *
 * Tables are built all over app.js and member.js; rather than teach each one,
 * this watches the page and fixes up any table that appears:
 *
 *   - click a heading to sort by it, click again to reverse, a third time to
 *     put the table's own order back;
 *   - a long table shows its first rows and a "Show all" button under it.
 *
 * Both survive a re-render: a table that is rebuilt with the same headings in
 * the same place keeps its sort and stays open if it was open.
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
  const DATES = [
    // 08/10/2026, as every date is shown; may be followed by words ("overdue")
    [/^(\d{1,2})\/(\d{1,2})\/(\d{4})\b/, (m) => [m[3], m[2], m[1]]],
    // 2026-10-08 and 2026-10, as a data-sort carries them
    [/^(\d{4})-(\d{2})-(\d{2})\b/, (m) => [m[1], m[2], m[3]]],
    [/^(\d{4})-(\d{2})$/, (m) => [m[1], m[2], 0]],
    // 8 Oct 2026 / Thu 8 Oct 2026
    [new RegExp(`^(?:[a-z]{3},? )?(\\d{1,2}) ${MON},? (\\d{4})\\b`, 'i'),
      (m) => [m[3], MONTHS.indexOf(m[2].toLowerCase()) + 1, m[1]]],
    // Oct 2026 / Oct ’26
    [new RegExp(`^${MON} (\\d{4})$`, 'i'), (m) => [m[2], MONTHS.indexOf(m[1].toLowerCase()) + 1, 0]],
    [new RegExp(`^${MON} ’(\\d{2})$`, 'i'), (m) => [2000 + Number(m[2]), MONTHS.indexOf(m[1].toLowerCase()) + 1, 0]],
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
    if (!memory.has(key)) memory.set(key, { col: null, dir: 1, open: false });
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

  function applyShort(table) {
    const rows = bodyRows(table).filter((r) => !isTotal(r));
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
  }
  function queue() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(sweep);
  }

  function start() {
    new MutationObserver(queue).observe(document.body, { childList: true, subtree: true });
    sweep();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());
