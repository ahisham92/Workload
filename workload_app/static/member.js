/* A team member's page: their own figures, and no way to change anything.
 *
 * Deliberately its own small script rather than the manager's app with parts
 * hidden. There is one endpoint behind it, /api/me, which returns only this
 * person's data -- so there is nothing here to hide in the first place.
 */

const state = { data: null, unit: null, year: null, me: null, chosen: false };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'class') node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function setChildren(node, ...children) {
  node.replaceChildren(
    ...children.filter((child) => child !== null && child !== undefined));
}

const num = (v, digits = 2) => (v === null || v === undefined || Number.isNaN(v)
  ? '—' : Number(v).toLocaleString(undefined, {
    minimumFractionDigits: digits, maximumFractionDigits: digits }));
const fmt = {
  int: (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString()),
  hours: (v) => (v === null || v === undefined ? '—'
    : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })),
  pct: (v) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`),
  pct0: (v) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`),
  ratio: (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(2)}×`),
  date: (v) => (v ? String(v).slice(0, 10) : '—'),
};

/* The same colour rules as the manager's app: below target reads red. */
const tone = {
  amount: (v) => (v === null || v === undefined ? ''
    : v < -0.0001 ? 'bad' : v > 0.0001 ? 'ok' : ''),
  cpi: (v) => (v === null || v === undefined ? ''
    : v >= 1 ? 'ok' : v >= 0.8 ? 'warn' : 'bad'),
  utilisation: (v) => (v === null || v === undefined ? ''
    : v > 1.05 ? 'bad' : v >= 0.85 ? 'ok' : v >= 0.7 ? 'warn' : 'bad'),
  target: (v) => {
    if (v === null || v === undefined) return '';
    const off = Math.abs(v - 1);
    return off <= 0.15 ? 'ok' : off <= 0.3 ? 'warn' : 'bad';
  },
  score: (v) => (v === null || v === undefined ? ''
    : v >= 80 ? 'ok' : v >= 60 ? 'warn' : 'bad'),
};

function toned(value, kind, format = num) {
  const cls = typeof kind === 'function' ? kind(value) : kind;
  return el('span', { class: cls ? `v-${cls}` : '' }, format(value));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let payload = {};
  try { payload = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    if (response.status === 401) window.location.href = '/login.html';
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.errors = payload.errors || [error.message];
    throw error;
  }
  return payload;
}

function toast(message, kind = '') {
  const node = el('div', { class: `toast ${kind}` }, message);
  $('#toasts').append(node);
  setTimeout(() => node.remove(), 5000);
}

/* ------------------------------------------------------------- rendering */

async function load() {
  const query = new URLSearchParams();
  if (state.unit) query.set('unit', state.unit);
  if (!state.chosen) {
    // First look: the workbook's own plan year, which is what the manager is
    // looking at. All time is a decade of months and nobody wants it by default.
    query.set('period', 'year');
  } else if (state.year) {
    query.set('period', 'year');
    query.set('year', state.year);
  } else {
    query.set('period', 'all');
  }
  state.data = await api(`/api/me?${query.toString()}`);
  if (!state.chosen) {
    state.year = state.data.period.year;
    state.chosen = true;
  }
  render();
}

function render() {
  const data = state.data;
  $('#member-name').textContent = data.engineer;
  $('#member-unit').textContent = data.unit
    ? `${data.unit.name}${data.unit.manager ? ` · ${data.unit.manager}'s team` : ''}`
    : '';
  $('#member-title').textContent = `My workload — ${data.period.label}`;

  fillUnits(data);
  fillYears(data);

  if (!data.known) {
    setChildren($('#member-message'), el('div', { class: 'msg msg-warn' }, data.message));
    for (const id of ['member-cards', 'member-projects', 'member-months',
      'member-timesheet', 'member-tasks']) setChildren($(`#${id}`));
    return;
  }
  setChildren($('#member-message'));

  renderCards(data);
  renderProjects(data);
  renderMonths(data);
  renderTimesheet(data);
  renderTasks(data);
  renderDefinitions(data);
}

function fillUnits(data) {
  const select = $('#member-unit-select');
  const units = data.units || [];
  select.parentElement.hidden = units.length < 2;
  if (select.options.length !== units.length) {
    setChildren(select, ...units.map((u) => el('option', { value: u.id }, u.name)));
  }
  select.value = data.unit ? data.unit.id : '';
}

function fillYears(data) {
  const select = $('#member-year');
  const years = (data.periods && data.periods.years) || [];
  if (select.options.length !== years.length + 1) {
    setChildren(select,
      el('option', { value: 'all' }, 'All years'),
      ...years.slice().reverse().map((y) => el('option', { value: y }, y)));
  }
  select.value = state.year === null ? 'all' : String(state.year);
}

function renderCards(data) {
  const me = data.me;
  const cards = [
    ['Actual MM booked', num(me.actual_mm), '',
      `${fmt.hours(me.actual_mm * data.hours_per_man_month)} hours`],
    ['Earned MM', num(me.earned_mm), '', 'value you delivered'],
    ['Profit / (loss)', num(me.profit_mm), tone.amount(me.profit_mm),
      'earned − actual'],
    ['Utilisation', fmt.pct(me.utilisation), tone.utilisation(me.utilisation),
      `of ${num(me.capacity_to_date_mm)} MM capacity to date`],
    ['Efficiency (CPI)', fmt.ratio(me.cpi), tone.cpi(me.cpi),
      me.cpi >= 1 ? 'earning above cost' : 'earning below cost'],
    ['Plan adherence', fmt.pct(me.plan_adherence), tone.target(me.plan_adherence),
      `vs ${num(me.planned_to_date_mm)} MM planned to date`],
    ['Remaining on hand', num(me.remaining_mm), '', 'still to deliver'],
    ['My score', num(me.score, 1), tone.score(me.score), 'out of 100'],
  ];
  setChildren($('#member-cards'), ...cards.map(([label, value, cls, sub]) =>
    el('div', { class: 'card' },
      el('div', { class: 'label' }, label),
      el('div', { class: `value ${cls ? `v-${cls}` : ''}` }, value),
      el('div', { class: 'sub' }, sub))));
}

function table(headers, rows, numeric = [], wide = []) {
  const cellClass = (i) => (numeric.includes(i) ? 'num' : wide.includes(i) ? 'wide' : '');
  return el('div', { class: 'table-wrap' },
    el('table', {},
      el('thead', {}, el('tr', {}, headers.map((h, i) =>
        el('th', { class: numeric.includes(i) ? 'num' : '' }, h)))),
      el('tbody', {}, rows.length
        ? rows.map((cells) => el('tr', {}, cells.map((cell, i) =>
            el('td', { class: cellClass(i) }, cell))))
        : el('tr', {}, el('td', { colspan: headers.length },
            el('div', { class: 'empty' }, 'Nothing here for this period.'))))));
}

function renderProjects(data) {
  setChildren($('#member-projects'), table(
    ['Project', 'Name', 'Status', 'My share', 'Progress', 'My budget MM',
     'My actual MM', 'My earned MM', 'CPI'],
    data.projects.map((p) => [
      el('span', { class: 'code' }, p.number),
      p.name,
      el('span', { class: `pill ${statusPill(p.status)}` }, p.status || '—'),
      fmt.pct0(p.share),
      fmt.pct0(p.progress),
      num(p.budget_mm),
      num(p.actual_mm),
      num(p.earned_mm),
      p.cpi === null ? '—' : toned(p.cpi, tone.cpi, fmt.ratio),
    ]), [3, 4, 5, 6, 7, 8], [1]));
}

function statusPill(status) {
  if (status === 'Active') return 'pill-ok';
  if (status === 'Not Started') return 'pill-info';
  if (status === 'On Hold') return 'pill-warn';
  if (status === 'Cancelled') return 'pill-bad';
  return '';
}

function renderMonths(data) {
  setChildren($('#member-months'), table(
    ['Month', 'Actual MM', 'Earned MM', 'Utilisation', 'CPI', 'Score'],
    data.months.map((m) => [
      el('span', {}, m.label, m.won ? el('span', { title: 'best in the team that month' }, ' 🏅') : null),
      num(m.actual_mm),
      num(m.earned_mm),
      toned(m.utilisation, tone.utilisation, fmt.pct),
      toned(m.cpi, tone.cpi, fmt.ratio),
      toned(m.score, tone.score, (v) => num(v, 1)),
    ]), [1, 2, 3, 4, 5]));
}

function renderTimesheet(data) {
  const t = data.timesheet;
  const scope = t.year ? `in ${t.year}` : 'all time';
  setChildren($('#member-timesheet'),
    el('dl', { class: 'kv' },
      el('dt', {}, `Rows ${scope}`),
      el('dd', {}, `${fmt.int(t.rows)} · of ${fmt.int(t.all_time_rows)} on your sheet`),
      el('dt', {}, `Hours ${scope}`),
      el('dd', {}, `${fmt.hours(t.hours)} · of ${fmt.hours(t.all_time_hours)} all time`),
      el('dt', {}, 'First date'), el('dd', {}, fmt.date(t.first_date)),
      el('dt', {}, 'Last date'), el('dd', {}, fmt.date(t.last_date))),
    el('p', { class: 'muted' },
      'Your manager uploads the timesheet; this is what has reached the '
      + 'workbook so far.'));
}

function renderTasks(data) {
  const block = data.tasks || { tasks: [] };
  const open = block.tasks.filter((t) => !t.done);
  setChildren($('#member-tasks'),
    el('p', { class: 'muted' },
      `${fmt.int(open.length)} open · ${fmt.hours(block.open_hours)} h of work`
      + (block.hours_per_day
        ? ` · about ${num(block.open_hours / block.hours_per_day, 1)} working day(s)`
        : '')
      + (block.overdue ? ` · ${fmt.int(block.overdue)} overdue` : '')),
    table(['Task', 'For', 'Hours', 'Due', 'Status'],
      block.tasks.map((t) => [
        el('div', {},
          el('div', { class: 'task-name' }, t.name),
          t.definition ? el('div', { class: 'muted small' }, t.definition) : null,
          t.shared_with
            ? el('div', { class: 'muted small' },
                `shared with ${t.shared_with} other(s) — ${num(t.hours_each)} h is yours`)
            : null),
        t.deliverable_name || t.project_number || '—',
        num(t.hours_each),
        el('span', { class: t.overdue ? 'v-bad' : '' }, fmt.date(t.due)),
        el('span', { class: `pill ${taskPill(t.status)}` }, t.status),
      ]), [2], [0]));
}

function taskPill(status) {
  if (status === 'Done') return 'pill-ok';
  if (status === 'Blocked') return 'pill-bad';
  if (status === 'In progress') return 'pill-warn';
  return 'pill-info';
}

function renderDefinitions(data) {
  setChildren($('#member-definitions'),
    el('div', { class: 'defs' }, (data.definitions || []).map((d) =>
      el('div', { class: 'def' },
        el('b', {}, d.field),
        el('p', {}, d.means),
        d.how ? el('p', { class: 'how' }, d.how) : null))));
}

/* --------------------------------------------------------------- account */

function openPasswordModal() {
  $('#modal-title').textContent = 'Change my password';
  const form = $('#modal-form');
  const fields = [
    ['current_password', 'Current password'],
    ['new_password', 'New password'],
    ['again', 'New password again'],
  ];
  setChildren(form, ...fields.map(([name, label]) =>
    el('label', { class: 'field full' },
      el('span', {}, label),
      el('input', { type: 'password', id: `f-${name}`, name }))));
  setChildren($('#modal-errors'));
  $('#modal-backdrop').hidden = false;
}

async function submitPassword() {
  const values = {};
  for (const node of $$('#modal-form [name]')) values[node.name] = node.value;
  if (values.new_password !== values.again) {
    setChildren($('#modal-errors'),
      el('div', { class: 'msg msg-bad' }, 'Those two passwords are not the same.'));
    return;
  }
  try {
    await api('/api/auth/password', { method: 'POST', body: values });
    $('#modal-backdrop').hidden = true;
    toast('Password changed.', 'ok');
  } catch (error) {
    setChildren($('#modal-errors'),
      ...(error.errors || [error.message]).map(
        (m) => el('div', { class: 'msg msg-bad' }, m)));
  }
}

/* ------------------------------------------------------------------ boot */

(async function start() {
  $('#btn-signout').addEventListener('click', async () => {
    try { await api('/api/auth/logout', { method: 'POST' }); } finally {
      window.location.href = '/login.html';
    }
  });
  $('#btn-print').addEventListener('click', () => window.print());
  $('#btn-password').addEventListener('click', openPasswordModal);
  $('#modal-close').addEventListener('click', () => { $('#modal-backdrop').hidden = true; });
  $('#modal-cancel').addEventListener('click', () => { $('#modal-backdrop').hidden = true; });
  $('#modal-submit').addEventListener('click', submitPassword);
  $('#modal-form').addEventListener('submit', (e) => e.preventDefault());
  $('#member-year').addEventListener('change', (event) => {
    const value = event.target.value;
    state.year = value === 'all' ? null : Number(value);
    load();
  });
  $('#member-unit-select').addEventListener('change', (event) => {
    state.unit = event.target.value;
    load();
  });

  try {
    const who = await api('/api/auth/me');
    if (!who.user) { window.location.href = '/login.html'; return; }
    state.me = who.user;
    await load();
  } catch (error) {
    document.body.prepend(el('div', { class: 'msg msg-bad', style: 'margin:20px' },
      (error.errors || [error.message]).join(' ')));
  }
})();
