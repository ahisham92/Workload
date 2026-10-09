/* Selecao+ — a schedule that behaves like a spreadsheet.
 *
 * Any <table class="gsheet"> whose cells hold boxes (inputs and lists) gets:
 *   - Enter and the arrow keys moving from cell to cell;
 *   - drag, or Shift+click, to pick a block of cells;
 *   - Ctrl+C copying the block, tab-separated, so it pastes into Excel;
 *   - Ctrl+V of a block (from Excel or from here) filling cells from the one
 *     in use, adding rows when the table has a way to (`table.gsheetAddRows`);
 *   - Delete clearing a picked block, Ctrl+D filling it down from its top row.
 * Each box filled is told `input` and `change`, exactly as if typed, so the
 * screen saves it the way it saves anything typed. Loaded after common.js.
 */
'use strict';

const sheetState = { anchor: null, end: null, table: null, dragging: false };

/** The box in a cell, if it has one. */
const cellBox = (td) => (td ? td.querySelector('input:not([type="hidden"]), select, textarea') : null);
const cellOf = (node) => (node && node.closest ? node.closest('table.gsheet td') : null);
const tableOf = (td) => td.closest('table.gsheet');

function cellPos(td) {
  const tr = td.parentElement;
  return [Array.prototype.indexOf.call(tr.parentElement.rows, tr), td.cellIndex];
}

function cellAt(table, r, c) {
  const body = table.tBodies[0];
  if (!body || r < 0 || r >= body.rows.length) return null;
  const tr = body.rows[r];
  return c >= 0 && c < tr.cells.length ? tr.cells[c] : null;
}

/* -- reading and writing a cell ------------------------------------------ */

/** What a cell shows, the way it would be typed. */
function cellText(td) {
  const box = cellBox(td);
  if (!box) return td.textContent.trim();
  if (box.tagName === 'SELECT') {
    const option = box.options[box.selectedIndex];
    return option && option.value !== '' ? option.text : '';
  }
  if (box.type === 'checkbox') return box.checked ? 'yes' : '';
  if (box.classList.contains('dayfield')) return box.value ? dayFirst(box.value) : '';
  return box.value;
}

/** The option a pasted word means: its value, its words, or how they begin. */
function optionFor(select, text) {
  const t = String(text).trim().toLowerCase();
  const options = Array.from(select.options);
  if (!t) return options.find((o) => o.value === '') || null;
  return options.find((o) => o.value.toLowerCase() === t)
    || options.find((o) => o.text.trim().toLowerCase() === t)
    || options.find((o) => o.text.trim().toLowerCase().startsWith(t))
    || options.find((o) => t.startsWith(o.value.toLowerCase()) && o.value !== '')
    || options.find((o) => o.text.toLowerCase().includes(t))
    || null;
}

/** Put text into a cell, as if it had been typed. False when it would not go. */
function setCell(td, text) {
  const box = cellBox(td);
  if (!box || box.disabled || box.readOnly) return false;
  const value = String(text ?? '').trim();
  if (box.tagName === 'SELECT') {
    const option = optionFor(box, value);
    if (!option) return false;
    box.value = option.value;
  } else if (box.type === 'checkbox') {
    box.checked = /^(1|y|yes|true|x|✓|✔)$/i.test(value);
  } else if (box.type === 'number') {
    const n = value.replace(/[%,\s]/g, '');
    if (n !== '' && Number.isNaN(Number(n))) return false;
    box.value = n;
  } else if (box.classList.contains('dayfield')) {
    const day = value ? parseDayFirst(value) : '';
    if (value && !day) return false;
    box.value = day;
  } else {
    box.value = value;
  }
  box.dispatchEvent(new Event('input', { bubbles: true }));
  box.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}

/* -- picking a block ----------------------------------------------------- */

function blockOf() {
  const { anchor, end, table } = sheetState;
  if (!anchor || !table || !table.isConnected) return null;
  const to = end || anchor;
  return {
    table,
    top: Math.min(anchor[0], to[0]), bottom: Math.max(anchor[0], to[0]),
    left: Math.min(anchor[1], to[1]), right: Math.max(anchor[1], to[1]),
  };
}

const blockSize = (b) => (b ? (b.bottom - b.top + 1) * (b.right - b.left + 1) : 0);

function paintBlock() {
  document.querySelectorAll('table.gsheet td.is-sel').forEach((td) => td.classList.remove('is-sel'));
  const b = blockOf();
  if (!b || blockSize(b) < 2) return;
  for (let r = b.top; r <= b.bottom; r += 1) {
    for (let c = b.left; c <= b.right; c += 1) {
      const td = cellAt(b.table, r, c);
      if (td) td.classList.add('is-sel');
    }
  }
}

function startBlock(td, extend) {
  const table = tableOf(td);
  const pos = cellPos(td);
  if (extend && sheetState.table === table && sheetState.anchor) sheetState.end = pos;
  else Object.assign(sheetState, { table, anchor: pos, end: null });
  paintBlock();
}

function clearBlock() {
  Object.assign(sheetState, { anchor: null, end: null, table: null });
  paintBlock();
}

/* -- moving about -------------------------------------------------------- */

function focusCell(table, r, c, step = 0) {
  // Skip over cells with nothing to type in, in the direction of travel.
  for (let i = 0; i < 40; i += 1) {
    const td = cellAt(table, r, c);
    if (!td) return false;
    if (!step && td.offsetParent === null) {         // a folded-away row: go past it
      r += r > (sheetState.anchor ? sheetState.anchor[0] : r) ? 1 : -1;
      continue;
    }
    const box = cellBox(td);
    if (box && !box.disabled && td.offsetParent !== null) {
      box.focus();
      if (box.select && box.tagName === 'INPUT' && box.type !== 'checkbox') box.select();
      Object.assign(sheetState, { table, anchor: [r, c], end: null });
      paintBlock();
      return true;
    }
    if (!step) return false;
    c += step;
  }
  return false;
}

function caretAtEdge(box, edge) {
  if (box.tagName !== 'INPUT' || box.type === 'checkbox') return true;
  let start; let end;
  try { start = box.selectionStart; end = box.selectionEnd; } catch { return true; }
  if (start === null) return true;              // number boxes say nothing: let it go
  if (start !== end) return start === 0 && end === box.value.length;
  return edge === 'start' ? start === 0 : end === RAW_VALUE.get.call(box).length;
}

/* -- copy and paste ------------------------------------------------------ */

function blockText(b) {
  const lines = [];
  for (let r = b.top; r <= b.bottom; r += 1) {
    const cells = [];
    for (let c = b.left; c <= b.right; c += 1) {
      const td = cellAt(b.table, r, c);
      cells.push(td ? cellText(td).replace(/[\t\n]+/g, ' ') : '');
    }
    lines.push(cells.join('\t'));
  }
  return lines.join('\n');
}

/** Rows and cells out of what was copied: tab-separated, the way Excel and
 *  this app both copy, with Excel's "quoted" cells read whole. */
function parseBlock(text) {
  const rows = [];
  let row = []; let cell = ''; let quoted = false;
  const src = String(text).replace(/\r\n?/g, '\n');
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i += 1; } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"' && cell === '') quoted = true;
    else if (ch === '\t') { row.push(cell); cell = ''; } else if (ch === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; } else cell += ch;
  }
  row.push(cell);
  rows.push(row);
  while (rows.length > 1 && rows[rows.length - 1].every((c) => c === '')) rows.pop();
  return rows;
}

/** Fill from a cell down and across; rows are added when the table can. */
function pasteBlock(table, at, rows) {
  const body = table.tBodies[0];
  const short = at[0] + rows.length - (body ? body.rows.length : 0);
  if (short > 0 && typeof table.gsheetAddRows === 'function') {
    const fresh = table.gsheetAddRows(short);
    if (fresh && fresh !== table) table = fresh;
  }
  let filled = 0; let refused = 0;
  rows.forEach((cells, i) => cells.forEach((text, j) => {
    const td = cellAt(table, at[0] + i, at[1] + j);
    if (!td || !cellBox(td)) return;
    if (setCell(td, text)) filled += 1; else refused += 1;
  }));
  Object.assign(sheetState, {
    table, anchor: at,
    end: [at[0] + rows.length - 1, at[1] + Math.max(...rows.map((r) => r.length)) - 1],
  });
  paintBlock();
  if (typeof toast === 'function') {
    toast(refused
      ? `${filled} cell(s) pasted; ${refused} did not fit their column and were left as they were.`
      : `${filled} cell(s) pasted.`, refused ? 'warn' : 'ok');
  }
}

/* -- wiring -------------------------------------------------------------- */

document.addEventListener('pointerdown', (e) => {
  const td = cellOf(e.target);
  if (!td) {
    if (!e.target.closest || !e.target.closest('.daypick')) clearBlock();
    return;
  }
  if (e.button !== 0) return;
  if (e.shiftKey && sheetState.anchor) {
    e.preventDefault();
    startBlock(td, true);
    return;
  }
  startBlock(td, false);
  sheetState.dragging = e.pointerType === 'mouse';
});
document.addEventListener('pointerover', (e) => {
  if (!sheetState.dragging) return;
  const td = cellOf(e.target);
  if (!td || tableOf(td) !== sheetState.table) return;
  const pos = cellPos(td);
  const [r, c] = sheetState.anchor;
  if (pos[0] === r && pos[1] === c) return;
  sheetState.end = pos;
  // A drag over cells picks them; it should not also pick the words in a box.
  const sel = window.getSelection && window.getSelection();
  if (sel) sel.removeAllRanges();
  if (document.activeElement && document.activeElement.blur && cellOf(document.activeElement)) {
    document.activeElement.blur();
  }
  paintBlock();
});
document.addEventListener('pointerup', () => { sheetState.dragging = false; });
// Moving into a cell by Tab or by the keyboard makes it the one in use.
document.addEventListener('focusin', (e) => {
  const td = cellOf(e.target);
  if (!td || sheetState.dragging) return;
  const b = blockOf();
  const pos = cellPos(td);
  if (b && blockSize(b) > 1 && b.table === tableOf(td) && pos[0] >= b.top && pos[0] <= b.bottom
      && pos[1] >= b.left && pos[1] <= b.right) return;
  Object.assign(sheetState, { table: tableOf(td), anchor: pos, end: null });
  paintBlock();
});

document.addEventListener('keydown', (e) => {
  const td = cellOf(e.target) || (sheetState.anchor && cellAt(sheetState.table, ...sheetState.anchor));
  if (!td) return;
  const table = tableOf(td);
  const b = blockOf();
  const mod = e.ctrlKey || e.metaKey;
  if (b && blockSize(b) > 1 && b.table === table) {
    if ((e.key === 'Delete' || e.key === 'Backspace') && !mod) {
      e.preventDefault();
      for (let r = b.top; r <= b.bottom; r += 1) {
        for (let c = b.left; c <= b.right; c += 1) setCell(cellAt(table, r, c), '');
      }
      return;
    }
    if (mod && e.key.toLowerCase() === 'd') {
      e.preventDefault();
      for (let c = b.left; c <= b.right; c += 1) {
        const text = cellText(cellAt(table, b.top, c));
        for (let r = b.top + 1; r <= b.bottom; r += 1) setCell(cellAt(table, r, c), text);
      }
      return;
    }
  }
  if (!cellOf(e.target) || mod || e.altKey) return;
  const box = e.target;
  const [r, c] = cellPos(td);
  if (e.key === 'Enter' && box.tagName !== 'TEXTAREA') {
    e.preventDefault();
    box.dispatchEvent(new Event('change', { bubbles: true }));
    focusCell(table, r + (e.shiftKey ? -1 : 1), c);
  } else if (e.key === 'ArrowDown' && box.tagName !== 'SELECT' && box.tagName !== 'TEXTAREA') {
    if (e.shiftKey) { e.preventDefault(); sheetState.end = [r + 1, c]; paintBlock(); return; }
    if (focusCell(table, r + 1, c)) e.preventDefault();
  } else if (e.key === 'ArrowUp' && box.tagName !== 'SELECT' && box.tagName !== 'TEXTAREA') {
    if (focusCell(table, r - 1, c)) e.preventDefault();
  } else if (e.key === 'ArrowRight' && caretAtEdge(box, 'end')) {
    if (focusCell(table, r, c + 1, 1)) e.preventDefault();
  } else if (e.key === 'ArrowLeft' && caretAtEdge(box, 'start')) {
    if (focusCell(table, r, c - 1, -1)) e.preventDefault();
  }
});

document.addEventListener('copy', (e) => {
  const b = blockOf();
  if (!b || blockSize(b) < 2) return;
  e.preventDefault();
  e.clipboardData.setData('text/plain', blockText(b));
  if (typeof toast === 'function') toast(`${blockSize(b)} cells copied. Paste them here or into Excel.`, 'ok');
});

document.addEventListener('paste', (e) => {
  const td = cellOf(e.target) || (sheetState.anchor && sheetState.table && sheetState.table.isConnected
    ? cellAt(sheetState.table, ...sheetState.anchor) : null);
  if (!td) return;
  const text = e.clipboardData ? e.clipboardData.getData('text/plain') : '';
  const rows = parseBlock(text);
  const single = rows.length === 1 && rows[0].length === 1;
  // One value into a box being typed in is the box's own business.
  if (single && cellOf(e.target) && cellBox(td) && cellBox(td).tagName !== 'SELECT') return;
  e.preventDefault();
  const b = blockOf();
  const at = b && b.table === tableOf(td) ? [b.top, b.left] : cellPos(td);
  if (single && b && blockSize(b) > 1) {
    // One value over a picked block fills all of it.
    pasteBlock(b.table, at, Array.from({ length: b.bottom - b.top + 1 },
      () => Array.from({ length: b.right - b.left + 1 }, () => rows[0][0])));
    return;
  }
  pasteBlock(tableOf(td), at, rows);
});
