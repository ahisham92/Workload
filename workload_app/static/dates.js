/* Selecao+ — every date box is day first: 30/08/2026, never 08/30/2026.
 *
 * The browser's own date box writes the date the way the phone or laptop is
 * set up, which on a US-English machine is month first. So every
 * <input type="date"> on the page, however it was made, is turned into a
 * plain box that shows and takes DD/MM/YYYY, with a small calendar to pick
 * from. Its `.value` still reads and takes "2026-08-30", so nothing that uses
 * it has to change. Loaded straight after common.js.
 */
'use strict';

const DAY_MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

const isoOf = (y, m, d) => `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;

/** What somebody typed, as "2026-08-30"; '' when it is not a date.
 *  Always day first: "30/8/26", "30-08-2026", "30.8", "30082026",
 *  "30 Aug 2026" and "2026-08-30" all read the same. */
function parseDayFirst(text, today = new Date()) {
  const t = String(text || '').trim().toLowerCase();
  if (!t) return '';
  let y; let m; let d;
  let hit = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(t);
  if (hit) [, y, m, d] = hit.map(Number);
  else if ((hit = /^(\d{1,2})\s*[/.\-\s]\s*(\d{1,2})(?:\s*[/.\-\s]\s*(\d{2}|\d{4}))?$/.exec(t))) {
    d = Number(hit[1]); m = Number(hit[2]);
    y = hit[3] === undefined ? today.getFullYear() : Number(hit[3]);
  } else if ((hit = /^(\d{1,2})[\s\-/.]*([a-z]{3,})[a-z]*\.?(?:[\s\-/.,]*(\d{2}|\d{4}))?$/.exec(t))) {
    d = Number(hit[1]); m = DAY_MONTHS.indexOf(hit[2].slice(0, 3)) + 1;
    y = hit[3] === undefined ? today.getFullYear() : Number(hit[3]);
  } else if ((hit = /^(\d{2})(\d{2})(\d{4}|\d{2})$/.exec(t))) {
    d = Number(hit[1]); m = Number(hit[2]); y = Number(hit[3]);
  } else return '';
  if (y < 100) y += 2000;
  if (!(m >= 1 && m <= 12 && d >= 1 && y >= 1900 && y <= 2200)) return '';
  const check = new Date(Date.UTC(y, m - 1, d));
  if (check.getUTCMonth() !== m - 1) return '';      // 31/02 is not a day
  return isoOf(y, m, d);
}

/* -- the box ------------------------------------------------------------- */

const RAW_VALUE = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');

/** Turn one browser date box into a day-first one, in place: the same node,
 *  with whatever is already listening to it, so the page notices nothing. */
function upgradeDateInput(input) {
  if (input.dataset.dayfirst) return;
  const iso = RAW_VALUE.get.call(input);
  input.dataset.dayfirst = '1';
  input.type = 'text';
  input.classList.add('dayfield');
  input.setAttribute('inputmode', 'numeric');
  input.setAttribute('autocomplete', 'off');
  input.setAttribute('maxlength', '11');
  if (!input.placeholder) input.placeholder = 'dd/mm/yyyy';
  Object.defineProperty(input, 'value', {
    configurable: true,
    get() { return parseDayFirst(RAW_VALUE.get.call(this)); },
    set(v) {
      const day = parseDayFirst(v);
      RAW_VALUE.set.call(this, day ? dayFirst(day) : '');
      this.classList.remove('is-bad');
    },
  });
  input.value = iso;
  input.addEventListener('input', (e) => {
    // Slashes put in as the digits go in: "3008" reads "30/08".
    if (e.inputType && e.inputType.startsWith('delete')) return;
    const raw = RAW_VALUE.get.call(input);
    if (/^\d{2}$/.test(raw) || /^\d{1,2}\/\d{2}$/.test(raw)) RAW_VALUE.set.call(input, `${raw}/`);
    input.classList.remove('is-bad');
  });
  input.addEventListener('blur', () => {
    const raw = RAW_VALUE.get.call(input).trim();
    const day = parseDayFirst(raw);
    if (day) RAW_VALUE.set.call(input, dayFirst(day));
    input.classList.toggle('is-bad', Boolean(raw) && !day);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeDayPicker();
    if ((e.key === 'ArrowDown' && e.altKey) || (e.key === ' ' && !RAW_VALUE.get.call(input))) {
      e.preventDefault();
      openDayPicker(input);
    }
  });
  input.addEventListener('click', () => openDayPicker(input));
}

function upgradeDatesIn(root) {
  if (!root || !root.querySelectorAll) return;
  if (root.matches && root.matches('input[type="date"]')) upgradeDateInput(root);
  root.querySelectorAll('input[type="date"]').forEach(upgradeDateInput);
}

/* -- the calendar -------------------------------------------------------- */

const dayPicker = { node: null, input: null, month: null };

function closeDayPicker() {
  if (dayPicker.node) dayPicker.node.remove();
  dayPicker.node = null;
  dayPicker.input = null;
}

/** Put a picked day into the box, and tell whatever listens to it. */
function pickDay(input, iso) {
  input.value = iso;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  closeDayPicker();
  input.focus();
}

function openDayPicker(input) {
  if (input.disabled || input.readOnly) return;
  if (dayPicker.input === input && dayPicker.node) return;
  closeDayPicker();
  const chosen = input.value;
  const start = chosen || new Date().toISOString().slice(0, 10);
  dayPicker.input = input;
  dayPicker.month = [Number(start.slice(0, 4)), Number(start.slice(5, 7)) - 1];
  const node = make('div', { class: 'daypick', role: 'dialog', 'aria-label': 'Pick a day' });
  // A tap inside the calendar must not take the focus out of the box first.
  node.addEventListener('pointerdown', (e) => e.preventDefault());
  dayPicker.node = node;
  document.body.append(node);
  drawDayPicker();
  placeDayPicker();
}

function drawDayPicker() {
  const { node, input } = dayPicker;
  if (!node) return;
  const [y, m] = dayPicker.month;
  const today = new Date();
  const todayIso = isoOf(today.getFullYear(), today.getMonth() + 1, today.getDate());
  const chosen = input.value;
  const min = input.getAttribute('min') || '';
  const max = input.getAttribute('max') || '';
  const move = (step) => {
    const at = new Date(y, m + step, 1);
    dayPicker.month = [at.getFullYear(), at.getMonth()];
    drawDayPicker();
  };
  const first = new Date(y, m, 1).getDay();              // the week opens on Sunday
  const days = new Date(y, m + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < first; i += 1) cells.push(make('span', { class: 'dp-blank' }));
  for (let d = 1; d <= days; d += 1) {
    const iso = isoOf(y, m + 1, d);
    const off = (min && iso < min) || (max && iso > max);
    const weekend = [5, 6].includes(new Date(y, m, d).getDay());
    cells.push(make('button', {
      type: 'button', disabled: off,
      class: `dp-day${iso === chosen ? ' is-on' : ''}${iso === todayIso ? ' is-today' : ''}${weekend ? ' is-weekend' : ''}`,
      'aria-label': dateText(iso, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }),
      onclick: () => pickDay(input, iso),
    }, String(d)));
  }
  node.replaceChildren(
    make('div', { class: 'dp-head' },
      make('button', { type: 'button', class: 'dp-nav', 'aria-label': 'Month before', onclick: () => move(-1) }, '‹'),
      make('b', {}, new Date(y, m, 1).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })),
      make('button', { type: 'button', class: 'dp-nav', 'aria-label': 'Month after', onclick: () => move(1) }, '›')),
    make('div', { class: 'dp-grid' },
      ...['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((w) => make('span', { class: 'dp-wd' }, w)),
      ...cells),
    make('div', { class: 'dp-foot' },
      make('button', { type: 'button', class: 'dp-link', onclick: () => pickDay(input, todayIso) }, 'Today'),
      make('span', { class: 'dp-hint' }, 'or type 30/08/2026'),
      make('button', { type: 'button', class: 'dp-link', onclick: () => pickDay(input, '') }, 'Clear')));
}

function placeDayPicker() {
  const { node, input } = dayPicker;
  if (!node || !input) return;
  const box = input.getBoundingClientRect();
  const width = node.offsetWidth;
  const height = node.offsetHeight;
  const left = clamp(box.left, 8, window.innerWidth - width - 8);
  const below = box.bottom + 6;
  const top = below + height > window.innerHeight - 8 && box.top - height - 6 > 8
    ? box.top - height - 6 : below;
  node.style.left = `${left + window.scrollX}px`;
  node.style.top = `${top + window.scrollY}px`;
}

document.addEventListener('pointerdown', (e) => {
  if (!dayPicker.node) return;
  if (dayPicker.node.contains(e.target) || e.target === dayPicker.input) return;
  closeDayPicker();
}, true);
document.addEventListener('focusin', (e) => {
  if (dayPicker.node && e.target !== dayPicker.input && !dayPicker.node.contains(e.target)) closeDayPicker();
});
window.addEventListener('resize', placeDayPicker);
document.addEventListener('scroll', (e) => {
  // Scrolling the page moves the box with it; scrolling a table the box sits
  // in would leave the calendar behind, so it follows.
  if (dayPicker.node && !dayPicker.node.contains(e.target)) placeDayPicker();
}, true);

/* Every date box, now and whenever one is added. */
upgradeDatesIn(document);
new MutationObserver((changes) => {
  for (const change of changes) change.addedNodes.forEach(upgradeDatesIn);
}).observe(document.documentElement, { childList: true, subtree: true });
