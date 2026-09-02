/* Workload — single page front end.
 * The server owns every workbook rule; this file renders state and posts changes.
 */
'use strict';

const state = {
  reference: null,
  status: null,
  overview: null,
  projects: [],
  projectMetrics: [],
  year: null,
  stagedImport: null,
  detail: null,          // the project currently open, with its deliverables
  referenceDraft: null,
  projectSort: { key: null, dir: 1 },   // null = the register's own order
  tasks: null,           // the task list, its settings and the load it makes
  access: null,          // who on the team has a read-only account
  me: null,              // the signed-in account
  units: [],
};

/* ---------------------------------------------------------------- helpers */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** Replace a node's children, treating a null child as nothing at all.
 *
 *  Every render below builds its children with ternaries, and the DOM's own
 *  replaceChildren turns a null into the text "null" on the page.
 */
function setChildren(node, ...children) {
  node.replaceChildren(
    ...children.filter((child) => child !== null && child !== undefined));
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const fmt = {
  mm: (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2)),
  hours: (v) => (v === null || v === undefined ? '—'
    : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })),
  pct: (v) => (v === null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(1)}%`),
  pct0: (v) => (v === null || v === undefined ? '—' : `${Math.round(Number(v) * 100)}%`),
  ratio: (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(2)}×`),
  int: (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString()),
  date: (v) => v || '—',
};

/** Percentages are held as fractions in the workbook and shown as whole numbers. */
const toPercent = (v) => (v === null || v === undefined || v === '' ? ''
  : Math.round(Number(v) * 1000) / 10);
const fromPercent = (v) => (v === null || v === undefined || v === '' ? null
  : Number(v) / 100);

/* ------------------------------------------------------------ tone rules
 *
 * One place decides what counts as bad, so a loss looks the same wherever it
 * appears. Colour is never the only signal: the number itself is always there,
 * and a loss keeps its minus sign.
 */
const tone = {
  /** Money and man-months: below zero is a loss. */
  amount: (v) => (v === null || v === undefined ? ''
    : v < -0.0001 ? 'bad' : v > 0.0001 ? 'ok' : ''),
  /** Earned per man-month spent. Below 1.00 means costing more than it earns. */
  cpi: (v) => (v === null || v === undefined ? ''
    : v >= 1 ? 'ok' : v >= 0.8 ? 'warn' : 'bad'),
  /** Busy-ness against capacity — over is as much a problem as under. */
  utilisation: (v) => (v === null || v === undefined ? ''
    : v > 1.05 ? 'bad' : v >= 0.85 ? 'ok' : v >= 0.7 ? 'warn' : 'bad'),
  /** Distance from a target of 1.00, either side. */
  target: (v, target = 1) => {
    if (v === null || v === undefined) return '';
    const off = Math.abs(v - target) / (target || 1);
    return off <= 0.15 ? 'ok' : off <= 0.3 ? 'warn' : 'bad';
  },
  /** How far a project has got. */
  progress: (v) => (v === null || v === undefined ? ''
    : v >= 1 ? 'ok' : v >= 0.5 ? 'warn' : ''),
  score: (v) => (v === null || v === undefined ? ''
    : v >= 80 ? 'ok' : v >= 60 ? 'warn' : 'bad'),
};

/** A number with its tone applied — as a class, so print keeps it too. */
function toned(value, kind, format = num, ...rest) {
  const cls = typeof kind === 'function' ? kind(value, ...rest) : kind;
  return el('span', { class: cls ? `v-${cls}` : '' }, format(value));
}

/** A progress bar with its percentage beside it. */
function progressCell(value) {
  if (value === null || value === undefined) return '—';
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return el('span', { class: 'progress-cell' },
    el('span', { class: `progress-track ${tone.progress(value)}` },
      el('span', { style: `width:${pct}%` })),
    el('span', { class: 'progress-value' }, `${pct}%`));
}

function toast(message, kind = '') {
  const node = el('div', { class: `toast ${kind}` }, message);
  $('#toasts').append(node);
  setTimeout(() => {
    node.style.opacity = '0';
    node.style.transition = 'opacity .3s';
    setTimeout(() => node.remove(), 320);
  }, kind === 'bad' ? 8000 : 3800);
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
    if (response.status === 401 && !path.startsWith('/api/auth/')) {
      // The session has ended -- somewhere else, or by simply expiring.
      window.location.href = '/login.html';
    }
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.errors = payload.errors || [error.message];
    error.status = response.status;
    throw error;
  }
  return payload;
}

function markSaved(save) {
  const badge = $('#save-state');
  if (!save) return;
  if (save.saved) {
    badge.textContent = 'saved';
    badge.className = 'pill pill-ok';
  } else if (save.pending) {
    badge.textContent = 'unsaved';
    badge.className = 'pill pill-warn';
  }
}

/* ------------------------------------------------------------- chooser */

function showShell(open) {
  $('#chooser').hidden = open;
  for (const id of ['topbar', 'tabs', 'main']) $(`#${id}`).hidden = !open;
}

async function renderChooser() {
  const data = await api('/api/units');
  const units = data.units || [];
  state.units = units;

  $('#chooser-user').textContent = state.me
    ? `Signed in as ${state.me.display_name}` : '';

  const parts = [
    el('h3', {}, units.length ? 'Your units' : 'No units yet'),
    units.length
      ? el('div', { class: 'unit-grid' }, units.map((unit) => el('div', {
          class: `unit-card ${unit.exists ? '' : 'missing'}`,
        },
        el('button', {
          class: 'unit-open', type: 'button', disabled: !unit.exists,
          onclick: () => openUnit(unit),
        },
          el('b', {}, unit.name),
          el('span', { class: 'muted' },
            unit.exists ? `${unit.size_mb} MB` : 'its workbook is missing'),
          el('span', { class: 'muted' },
            unit.opened_at ? `last opened ${String(unit.opened_at).slice(0, 10)}`
              : `created ${String(unit.created_at).slice(0, 10)}`)),
        el('div', { class: 'unit-tools' },
          el('button', {
            class: 'btn btn-ghost btn-sm', type: 'button', title: 'Rename this unit',
            onclick: () => renameUnit(unit),
          }, '✎'),
          el('button', {
            class: 'btn btn-ghost btn-sm', type: 'button',
            title: 'Download a copy of this workbook',
            onclick: () => downloadUnit(unit),
          }, '⭳'),
          el('button', {
            class: 'btn btn-ghost btn-sm', type: 'button',
            title: 'Delete this unit and its workbook',
            onclick: () => deleteUnit(unit),
          }, '✕')))))
      : el('p', { class: 'muted' },
          'Start one below. A blank unit carries the whole model — project '
          + 'types, rules of credit, the scorecard — with none of the data.'),
  ];
  if (units.length >= data.limit) {
    parts.push(el('div', { class: 'msg msg-warn' },
      `An account holds up to ${data.limit} units.`));
  }
  setChildren($('#unit-list'), ...parts);
}

function chooserError(messages) {
  setChildren($('#chooser-error'), 
    ...messages.map((m) => el('div', { class: 'msg msg-bad' }, m)));
}

async function openUnit(unit) {
  try {
    await api(`/api/units/${unit.id}/open`, { method: 'POST' });
    await enterApp();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  }
}

async function newUnit() {
  const name = $('#unit-name').value.trim();
  if (!name) { chooserError(['Give the unit a name first.']); return; }
  const button = $('#btn-new-unit');
  button.disabled = true;
  try {
    await api('/api/units', { method: 'POST', body: { name } });
    await enterApp();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  } finally {
    button.disabled = false;
  }
}

async function uploadUnit() {
  const file = $('#unit-file').files[0];
  if (!file) { chooserError(['Choose a workbook file first.']); return; }
  const name = $('#unit-name').value.trim() || file.name.replace(/\.[^.]+$/, '');
  const button = $('#btn-upload-unit');
  button.disabled = true;
  chooserError([]);
  try {
    const base64 = await readFileBase64(file);
    await api('/api/units/upload', {
      method: 'POST',
      body: { name, filename: file.name, content_base64: base64 },
    });
    await enterApp();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  } finally {
    button.disabled = false;
  }
}

async function renameUnit(unit) {
  const name = window.prompt('Name this unit', unit.name);
  if (!name || name === unit.name) return;
  try {
    await api(`/api/units/${unit.id}`, { method: 'PUT', body: { name } });
    await renderChooser();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  }
}

async function deleteUnit(unit) {
  if (!window.confirm(
    `Delete "${unit.name}"?\n\nIts workbook and every backup of it are `
    + 'removed from the server. Download a copy first if you want one.')) return;
  try {
    await api(`/api/units/${unit.id}`, { method: 'DELETE' });
    await renderChooser();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  }
}

/** Hand the workbook back as a file, so the account is never a trap. */
async function downloadUnit(unit) {
  try {
    const result = await api(`/api/units/${unit.id}/download`);
    const bytes = Uint8Array.from(atob(result.content_base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }));
    const link = el('a', { href: url, download: result.filename });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (error) {
    chooserError(error.errors || [error.message]);
  }
}

function readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('Could not read the file.'));
    reader.readAsDataURL(file);
  });
}

/* ------------------------------------------------------------- account */

async function signOut() {
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } finally {
    window.location.href = '/login.html';
  }
}

function openAccountModal() {
  const me = state.me || {};
  openModal(`Account — ${me.display_name || me.username}`, [
    { name: 'current_password', label: 'Current password', type: 'password',
      full: true },
    { name: 'new_password', label: 'New password', type: 'password', full: true,
      hint: 'at least 10 characters' },
    { name: 'again', label: 'New password again', type: 'password', full: true },
  ], async () => {
    const body = modalValues();
    if ((body.new_password || '') !== (body.again || '')) {
      showModalErrors(['Those two passwords are not the same.']);
      return;
    }
    await api('/api/auth/password', { method: 'POST', body });
    closeModal();
    toast('Password changed. Every other session was signed out.', 'ok');
  }, {});
}

/* -- administration ---------------------------------------------------- */

async function openAdmin() {
  const data = await api('/api/admin/users');
  const body = el('div', {},
    el('p', { class: 'muted' },
      'Accounts can only be made here — there is no public sign-up. A new '
      + 'account starts with no units and sees nothing of anyone else\'s.'),
    el('table', {},
      el('thead', {}, el('tr', {},
        ['Username', 'Name', 'Kind', 'Units', 'Last seen', 'Role', ''].map(
          (h) => el('th', {}, h)))),
      el('tbody', {}, data.users.map((user) => el('tr', {},
        el('td', {}, el('b', {}, user.username)),
        el('td', {}, user.display_name),
        el('td', {}, el('span', {
          class: `pill ${user.role === 'member' ? 'pill-info' : 'pill-ok'}`,
          title: user.role === 'member'
            ? 'Sees one person\'s own figures, read-only'
            : 'Owns units and edits them',
        }, user.role === 'member' ? 'team member' : 'manager')),
        el('td', { class: 'num' }, fmt.int(user.units || 0)),
        el('td', {}, user.last_seen ? String(user.last_seen).slice(0, 10) : 'never'),
        el('td', {}, user.is_admin
          ? el('span', { class: 'pill pill-info' }, 'administrator') : ''),
        el('td', { class: 'row-actions' },
          el('button', { class: 'btn btn-sm', type: 'button',
            onclick: () => resetPassword(user) }, 'Reset password'),
          user.role === 'member' ? null
            : el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
              title: user.is_admin ? 'Take away administrator' : 'Make administrator',
              onclick: () => toggleAdmin(user) }, user.is_admin ? '↓' : '↑'),
          user.id === (state.me || {}).id ? null
            : el('button', { class: 'btn btn-sm btn-danger', type: 'button',
              onclick: () => deleteAccount(user) }, '✕')))))),
    el('div', { class: 'row-actions', style: 'margin-top:14px' },
      el('button', { class: 'btn btn-primary', type: 'button',
        onclick: () => newAccount() }, 'Add an account')));

  openPanel('Accounts', body);
}

async function newAccount() {
  openModal('New account', [
    { name: 'username', label: 'Username', full: true,
      hint: 'letters, digits, dot, dash or underscore' },
    { name: 'display_name', label: 'Name shown in the app', full: true },
    { name: 'role', label: 'Kind of account', type: 'select', full: true,
      hint: 'a manager owns units and edits them; a team member only sees '
        + 'their own figures, and is given them from a manager\'s Team tab',
      options: [{ value: 'manager', label: 'Manager — runs a team' },
        { value: 'member', label: 'Team member — read-only' }] },
    { name: 'password', label: 'Password', type: 'password', full: true,
      hint: 'leave blank and one is generated for you' },
    { name: 'is_admin', label: 'May manage accounts', type: 'checks', full: true,
      options: [{ value: 'yes', label: 'Administrator (managers only)' }] },
  ], async () => {
    const body = modalValues();
    body.is_admin = (body.is_admin || []).length > 0 && body.role !== 'member';
    const result = await api('/api/admin/users', { method: 'POST', body });
    closeModal();
    if (result.password) {
      window.alert(`Account ${result.user.username} created.\n\n`
        + `Password: ${result.password}\n\n`
        + 'Write it down now — it cannot be read back.');
    } else {
      toast(`Account ${result.user.username} created.`, 'ok');
    }
    await openAdmin();
  }, { role: 'manager' });
}

async function resetPassword(user) {
  openModal(`Reset the password for ${user.username}`, [
    { name: 'password', label: 'New password', type: 'password', full: true,
      hint: 'leave blank and one is generated for you' },
  ], async () => {
    const result = await api(`/api/admin/users/${user.id}/password`,
      { method: 'POST', body: modalValues() });
    closeModal();
    if (result.password) {
      window.alert(`Password for ${user.username}:\n\n${result.password}\n\n`
        + 'Write it down now — it cannot be read back.');
    } else {
      toast(`Password changed for ${user.username}.`, 'ok');
    }
    await openAdmin();
  }, {});
}

async function toggleAdmin(user) {
  try {
    await api(`/api/admin/users/${user.id}/admin`,
      { method: 'POST', body: { is_admin: !user.is_admin } });
    await openAdmin();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

async function deleteAccount(user) {
  if (!window.confirm(
    `Delete the account ${user.username}?\n\nEvery workbook it holds goes `
    + 'with it. This cannot be undone.')) return;
  try {
    await api(`/api/admin/users/${user.id}`, { method: 'DELETE' });
    toast(`${user.username} deleted.`, 'ok');
    await openAdmin();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

async function enterApp() {
  showShell(true);
  state.reference = await api('/api/reference');
  if (state.year === null) state.year = state.reference.plan_year;
  await refreshAll();
  switchView('overview');
}

/* --------------------------------------------------------------- modal */

let modalSubmit = null;

function openModal(title, fields, onSubmit, values = {}) {
  $('#modal-title').textContent = title;
  const form = $('#modal-form');
  form.innerHTML = '';
  $('#modal-errors').innerHTML = '';

  for (const field of fields) {
    const id = `f-${field.name}`;
    let input;
    if (field.type === 'select') {
      input = el('select', { id, name: field.name });
      for (const option of field.options) {
        const value = typeof option === 'string' ? option : option.value;
        const label = typeof option === 'string' ? option : option.label;
        input.append(el('option', { value }, label));
      }
      input.value = values[field.name] ?? field.value ?? '';
    } else if (field.type === 'textarea') {
      input = el('textarea', { id, name: field.name });
      input.value = values[field.name] ?? '';
    } else if (field.type === 'checks') {
      // A task can be shared, so its people are a set rather than a choice.
      const chosen = new Set(values[field.name] ?? field.value ?? []);
      input = el('div', { class: 'check-group', 'data-group': field.name },
        field.options.map((option) => {
          const value = typeof option === 'string' ? option : option.value;
          const label = typeof option === 'string' ? option : option.label;
          const box = el('input', { type: 'checkbox', value });
          box.checked = chosen.has(value);
          return el('label', { class: 'check-chip' }, box, el('span', {}, label));
        }));
    } else {
      input = el('input', {
        id, name: field.name, type: field.type || 'text',
        step: field.step, min: field.min, max: field.max,
        placeholder: field.placeholder,
      });
      const raw = values[field.name];
      input.value = raw === null || raw === undefined ? '' : raw;
    }
    form.append(el('label', { class: `field ${field.full ? 'full' : ''}` },
      el('span', {}, field.label,
        field.hint ? el('span', { class: 'hint' }, ` — ${field.hint}`) : null),
      input));
  }

  modalSubmit = onSubmit;
  $('#modal-submit').hidden = false;
  $('#modal-cancel').textContent = 'Cancel';
  $('#modal-backdrop').hidden = false;
  const first = form.querySelector('input, select, textarea');
  if (first) first.focus();
}

/** The modal, used for a screen rather than a form: no Save button. */
function openPanel(title, content) {
  $('#modal-title').textContent = title;
  const form = $('#modal-form');
  setChildren(form, content);
  $('#modal-errors').innerHTML = '';
  modalSubmit = null;
  $('#modal-submit').hidden = true;
  $('#modal-cancel').textContent = 'Close';
  $('#modal-backdrop').hidden = false;
}

function openAccountPanel() {
  const me = state.me || {};
  openPanel('Account', el('div', { class: 'account-panel' },
    el('p', {}, el('b', {}, me.display_name || me.username),
      me.is_admin ? el('span', { class: 'pill pill-info', style: 'margin-left:8px' },
        'administrator') : null),
    el('p', { class: 'muted' },
      `Signed in as ${me.username}. Your units and their workbooks are yours `
      + 'alone; no other account can open them.'),
    el('div', { class: 'row-actions' },
      el('button', { class: 'btn', type: 'button', onclick: openAccountModal },
        'Change password'),
      me.is_admin
        ? el('button', { class: 'btn', type: 'button', onclick: openAdmin },
            'Accounts')
        : null,
      el('button', { class: 'btn btn-danger', type: 'button', onclick: signOut },
        'Sign out'))));
}

function closeModal() {
  $('#modal-backdrop').hidden = true;
  modalSubmit = null;
}

function modalValues() {
  const out = {};
  for (const node of $$('#modal-form [name]')) {
    out[node.name] = node.value.trim() === '' ? null : node.value.trim();
  }
  for (const group of $$('#modal-form [data-group]')) {
    out[group.dataset.group] = $$('input:checked', group).map((box) => box.value);
  }
  return out;
}

function showModalErrors(errors) {
  setChildren($('#modal-errors'), 
    el('ul', {}, errors.map((e) => el('li', {}, e))));
}

/* ------------------------------------------------------------ overview */

function renderOverview() {
  const data = state.overview;
  const report = state.report;
  if (!data || !report) return;

  const yearSelect = $('#overview-year');
  if (yearSelect.options.length === 0) {
    yearSelect.append(el('option', { value: 'all' }, 'All years'));
    for (const year of (report.periods.years || []).slice().reverse()) {
      yearSelect.append(el('option', { value: year }, year));
    }
    yearSelect.value = state.year === null ? 'all' : String(state.year);
  }

  const t = report.team;
  const inHand = report.by_status
    .filter((s) => s.in_scope)
    .reduce((sum, s) => sum + (s.budget_mm || 0), 0);
  const label = report.period.label;

  // Everything here is for the period chosen above, not life-to-date.
  const cards = [
    ['In-hand budget', num(inHand), '', `active and not started, ${label.toLowerCase()}`],
    ['Planned MM', num(t.planned_mm), '', 'what we said we would burn'],
    ['Actual MM booked', num(t.actual_mm), '',
      `${fmt.hours(t.actual_mm * report.hours_per_man_month)} hours`],
    ['Earned MM', num(t.earned_mm), '', 'value delivered'],
    ['Profit / (loss)', num(t.profit_mm), tone.amount(t.profit_mm), 'earned − actual'],
    ['Utilisation', fmt.pct(t.utilisation), tone.utilisation(t.utilisation),
      `of ${num(t.capacity_to_date_mm)} MM capacity to date`],
    ['Efficiency (CPI)', fmt.ratio(t.cpi), tone.cpi(t.cpi),
      t.cpi >= 1 ? 'earning above cost' : 'earning below cost'],
    ['Active projects', fmt.int(t.projects_active), '',
      `${t.projects_not_started} not started · ${t.projects_live} live in the period`],
  ];
  setChildren($('#overview-cards'), ...cards.map(([label_, value, cls, sub]) =>
    el('div', { class: 'card' },
      el('div', { class: 'label' }, label_),
      el('div', { class: `value ${cls ? `v-${cls}` : ''}` }, value),
      el('div', { class: 'sub' }, sub))));

  renderHeroes(report);

  setChildren($('#engineer-cards'), 
    ...report.engineers.map((name) => engineerBlock(name, report, data)));

  renderDataCheck(data.data_check);
  renderIssues(data.issues || []);
  renderDefinitions(report.definitions || []);
}

/** The month's and the year's top performer, by the same weighted scorecard. */
function renderHeroes(report) {
  const heroes = report.heroes || {};
  const month = heroes.month;
  const year = heroes.year;
  const strip = $('#hero-strip');
  const champion = report.champion;
  if (!month && !year && !champion) { setChildren(strip); return; }

  const wins = heroes.wins || {};
  strip.className = 'hero-strip';
  setChildren(strip, 
    month
      ? el('div', { class: 'hero' },
          el('span', { class: 'medal' }, '🏅'),
          el('div', { class: 'who' },
            el('div', { class: 'label' }, `Hero of ${month.label}`),
            el('div', { class: 'name' }, month.hero || '—'),
            el('div', { class: 'why' },
              `scored ${num(month.hero_score, 1)} of 100 · strongest on `
              + `${(month.hero_strongest || '').toLowerCase()}`)))
      : el('div', { class: 'hero' },
          el('span', { class: 'medal' }, '🏅'),
          el('div', { class: 'who' },
            el('div', { class: 'label' }, 'Hero of the month'),
            el('div', { class: 'hero-empty' },
              'No completed month with booked time in this period yet.'))),
    year
      ? el('div', { class: 'hero hero-year' },
          el('span', { class: 'medal' }, '🏆'),
          el('div', { class: 'who' },
            el('div', { class: 'label' }, `Hero of ${periodName(report.period)}`),
            el('div', { class: 'name' }, year.engineer || '—'),
            el('div', { class: 'why' },
              `scored ${num(year.score, 1)} of 100 · `
              + `won ${year.months_won} of ${heroes.months_scored} month(s) scored`)))
      : null,
    champion
      ? el('div', { class: 'hero hero-project' },
          el('span', { class: 'medal' }, '🎖️'),
          el('div', { class: 'who' },
            el('div', { class: 'label' }, `Project of ${periodName(report.period)}`),
            el('div', { class: 'name' }, champion.number),
            el('div', { class: 'why', title: champion.name },
              `${trim(champion.name, 64)} — finalized, CPI `
              + `${fmt.ratio(champion.cpi)} on ${num(champion.actual_mm)} MM `
              + `spent, best of ${champion.finalists} finished`)))
      : null,
    Object.keys(wins).length
      ? el('div', { class: 'hero', style: 'border-left-color: var(--series-3)' },
          el('span', { class: 'medal' }, '📅'),
          el('div', { class: 'who' },
            el('div', { class: 'label' }, 'Months won'),
            el('div', { class: 'why', style: 'margin-top:4px' },
              Object.entries(wins)
                .sort((a, b) => b[1] - a[1])
                .map(([name, count]) => `${name} ${count}`).join(' · '))))
      : null);
}

/** A period's name, short enough for a card's heading. */
function periodName(period) {
  return period.kind === 'all' ? 'all time' : period.label.toLowerCase();
}

/** Cut a long project name to something a card can hold. */
function trim(text, limit) {
  const value = text || '';
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}

function renderDefinitions(definitions) {
  setChildren($('#definitions-body'), 
    el('div', { class: 'defs' }, definitions.map((d) => el('div', { class: 'def' },
      el('b', {}, d.field),
      el('p', {}, d.means),
      d.how ? el('p', { class: 'how' }, d.how) : null))));
}

/** One engineer's standing in the period, in the workbook's own measures.
 *
 *  Raw hours say very little on their own; man-months against capacity, and
 *  value earned against effort spent, are what the workbook is built on.
 */
function engineerBlock(name, report, overview) {
  const e = report.per_engineer[name];
  const hours = overview.engineers[name] || {};
  const util = e.utilisation;
  const pill = util === null ? 'pill-info'
    : util > 1.05 ? 'pill-bad' : util < 0.7 ? 'pill-warn' : 'pill-ok';
  const won = (report.heroes && report.heroes.wins && report.heroes.wins[name]) || 0;

  const measure = (label, value, hint, cls = '') => el('div', { class: 'measure' },
    el('span', { class: 'measure-label', title: hint }, label),
    el('span', { class: `measure-value ${cls ? `v-${cls}` : ''}` }, value));

  return el('div', { class: 'eng' },
    el('div', { class: 'eng-head' },
      el('span', { class: 'eng-name' },
        el('span', { class: 'swatch', style: `background:${engineerColor(name)}` }),
        name,
        won ? el('span', { class: 'pill pill-info', title: 'months won in this period' },
          `🏅 ${won}`) : null),
      el('span', { class: `pill ${pill}` }, `${fmt.pct(util)} utilised`)),

    el('div', { class: 'meter' },
      el('span', {
        style: `width:${Math.min(100, Math.round((util || 0) * 100))}%;`
          + `background:${util > 1.05 ? 'var(--bad)' : 'var(--ok)'}`,
      })),

    el('div', { class: 'measures' },
      measure('Actual MM', num(e.actual_mm), 'Effort really spent in this period'),
      measure('Capacity MM', num(e.capacity_to_date_mm),
        'Availability × months, pro-rated to the as-at date'),
      measure('Earned MM', num(e.earned_mm), 'Value delivered, budget × progress'),
      measure('CPI', fmt.ratio(e.cpi), 'Earned ÷ actual. Above 1.00 is good',
        tone.cpi(e.cpi)),
      measure('Plan adherence', fmt.pct(e.plan_adherence),
        'Actual against what was planned to date', tone.target(e.plan_adherence)),
      measure('Projects', fmt.int(e.projects_worked), 'Projects booked to in this period')),

    el('div', { class: 'muted', style: 'margin-top:6px' },
      `${fmt.hours(hours.total_hours)} h booked in total`
      + (hours.absence_hours ? ` · ${fmt.hours(hours.absence_hours)} h absence` : '')
      + (hours.overtime_hours ? ` · ${fmt.hours(hours.overtime_hours)} h overtime` : '')));
}

function renderDataCheck(check) {
  const kind = check.all_time_rows === 0 ? 'msg-warn'
    : check.rows_not_matching_pattern ? 'msg-bad' : 'msg-ok';
  const unknown = check.unknown_job_numbers || [];
  // The counts follow the year chosen above; the sheets themselves hold every
  // year at once, so the whole-file totals stay beside them.
  const year = check.year;
  const scope = year ? `in ${year}` : 'all time';
  setChildren($('#data-check'), 
    el('div', { class: `msg ${kind}` }, check.verdict),
    el('dl', { class: 'kv' },
      el('dt', {}, `Rows ${scope}`),
      el('dd', {}, fmt.int(check.rows)
        + (year ? ` · of ${fmt.int(check.all_time_rows)} on the sheets` : '')),
      el('dt', {}, `Hours ${scope}`),
      el('dd', {}, fmt.hours(check.hours)
        + (year ? ` · of ${fmt.hours(check.all_time_hours)} all time` : '')),
      el('dt', {}, 'First date'), el('dd', {}, fmt.date(check.first_date)),
      el('dt', {}, 'Last date'), el('dd', {}, fmt.date(check.last_date)),
      ...Object.entries(check.per_engineer).flatMap(([name, e]) => [
        el('dt', {}, name),
        el('dd', {}, `${fmt.int(e.rows)} rows · ${fmt.hours(e.hours)} h ${scope}`
          + ` · to ${fmt.date(e.last_date)}`),
      ])),
    unknown.length
      ? el('div', { class: 'msg msg-warn', style: 'margin-top:12px' },
          el('strong', {},
            `${unknown.length} job number(s) charged ${scope} but not in the register: `),
          unknown.slice(0, 8).map((u) => `${u.code} (${u.rows})`).join(', ')
            + (unknown.length > 8 ? `, and ${unknown.length - 8} more` : ''))
      : null);
}

function renderIssues(issues) {
  if (issues.length === 0) {
    setChildren($('#issues'), el('div', { class: 'msg msg-ok' },
      'Every project accounts for 100% of its scope, every deliverable splits '
      + '100% between the team, and every deliverable has a TS Phase.'));
    return;
  }
  setChildren($('#issues'), ...issues.map((issue) => {
    const level = issue.level === 'error' ? 'bad' : issue.level === 'warning' ? 'warn' : 'info';
    // Anything that names a project gets a way straight to it.
    const project = issue.project
      || state.projects.find((p) => issue.message.includes(p.number))?.number;
    return el('div', { class: `msg msg-${level} msg-action` },
      el('span', {}, el('strong', {}, `${issue.where}: `), issue.message),
      project
        ? el('button', { class: 'btn btn-sm', type: 'button',
            onclick: () => openProject(project) }, 'Fix')
        : null);
  }));
}

/* ----------------------------------------------------------- timesheets */

function renderTimesheets() {
  const check = state.overview ? state.overview.data_check : null;
  if (!check) return;
  renderCapacity(check);

  setChildren($('#ts-cards'), ...Object.entries(check.per_engineer).map(([name, e]) =>
    el('div', { class: 'card' },
      el('div', { class: 'label' }, `${name} — ${e.sheet}`),
      el('div', { class: 'value' }, fmt.int(e.all_time_rows)),
      el('div', { class: 'sub' },
        `rows · ${fmt.hours(e.all_time_hours)} h · `
        + `${fmt.date(e.first_date)} → ${fmt.date(e.last_date)}`),
      e.rows_not_matching_pattern
        ? el('div', { class: 'msg msg-bad', style: 'margin-top:8px' },
            `${e.rows_not_matching_pattern} row(s) belong to someone else`)
        : null)));

  const select = $('#ts-engineer');
  const chosen = select.value;
  setChildren(select, ...Object.keys(check.per_engineer).map(
    (name) => el('option', { value: name }, name)));
  if (chosen) select.value = chosen;
}

function renderCapacity(check) {
  const cap = check.capacity;
  const target = $('#ts-capacity');
  if (!cap) { setChildren(target); return; }
  const used = cap.rows_used / cap.total_capacity;
  const meter = cap.over_capacity ? 'bad' : cap.low_headroom ? 'warn' : '';
  const warnings = check.capacity_warnings || [];

  setChildren(target, el('div', { class: 'panel' },
    el('h3', {}, 'Room left in the workbook'),
    el('p', { class: 'muted' },
      `Every calculation reads Timesheet Raw rows 4–${cap.raw_last_row.toLocaleString()}, `
      + `stacked from each monthly sheet down to row ${cap.source_last_row.toLocaleString()} `
      + `— ${cap.total_capacity.toLocaleString()} entries in all. An import that `
      + 'would not fit raises the limit itself before writing anything, so no '
      + 'entry is ever left on the sheet unread.'),
    el('div', { class: `meter ${meter}` },
      el('span', { style: `width:${Math.min(100, Math.round(used * 100))}%` })),
    el('p', { class: 'muted' },
      `${cap.rows_used.toLocaleString()} of ${cap.total_capacity.toLocaleString()} rows used`
      + (cap.headroom >= 0
        ? ` — ${cap.headroom.toLocaleString()} left`
        : ` — ${Math.abs(cap.headroom).toLocaleString()} rows are being ignored`)),
    ...warnings.map((w) => el('div', {
      class: `msg msg-${w.level === 'error' ? 'bad' : 'warn'}`,
    }, w.message)),
    el('div', { class: 'row-actions' },
      (cap.over_capacity || cap.low_headroom)
        ? el('button', { class: 'btn btn-primary', type: 'button',
            onclick: () => extendCapacity(cap) },
            `Raise the limit to ${cap.suggested_raw_last_row.toLocaleString()} entries`)
        : null,
      cap.source_is_short
        ? el('button', { class: 'btn', type: 'button',
            onclick: () => raiseSourceLimit(cap) },
            `Read each sheet to row ${cap.suggested_source_last_row.toLocaleString()}`)
        : null),
    cap.source_is_short
      ? el('p', { class: 'muted' },
          `Each monthly sheet is only read to row ${cap.source_last_row.toLocaleString()} `
          + `(${cap.per_sheet_capacity.toLocaleString()} entries). Reading to row `
          + `${cap.suggested_source_last_row.toLocaleString()} leaves room for years of imports.`)
      : el('p', { class: 'muted' },
          `Each monthly sheet is read to row ${cap.source_last_row.toLocaleString()}, `
          + `which is ${cap.per_sheet_capacity.toLocaleString()} entries each — `
          + 'the app widens the stack to that when it opens a workbook, so an '
          + "engineer's own sheet is not the thing that runs out first.")));
}

async function raiseSourceLimit(cap) {
  if (!window.confirm(
    `Read each monthly sheet down to row ${cap.suggested_source_last_row.toLocaleString()} `
    + `instead of ${cap.source_last_row.toLocaleString()}?\n\n`
    + 'This widens the stack that builds Timesheet Raw so a single sheet can hold '
    + 'far more entries. A backup is taken first.')) return;
  try {
    toast('Widening the stack…');
    const result = await api('/api/timesheets/capacity', {
      method: 'POST',
      body: { source_last_row: cap.suggested_source_last_row },
    });
    markSaved(result.save);
    toast(`Each sheet is now read to row ${result.source_last_row.toLocaleString()}.`, 'ok');
    await refreshAll();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

async function extendCapacity(cap) {
  const perSheetNeeded = Math.max(
    ...Object.values(cap.per_sheet).map((s) => s.rows)) + 1500;
  const source = perSheetNeeded > cap.per_sheet_capacity || cap.source_is_short
    ? cap.suggested_source_last_row : null;
  if (!window.confirm(
    `Raise the limit from ${cap.raw_last_row.toLocaleString()} to `
    + `${cap.suggested_raw_last_row.toLocaleString()} entries?\n\n`
    + 'This is a one-off: it rewrites every formula that reads the consolidated '
    + 'timesheet and adds the per-row helper formulas to match, which takes about '
    + 'a minute. A backup is taken first.\n\n'
    + 'Afterwards the whole timesheet has one limit — 25,000 entries — and Excel '
    + 'takes a little longer to recalculate the file.')) return;
  try {
    toast('Rewriting formulas — this takes about a minute…');
    const result = await api('/api/timesheets/capacity', {
      method: 'POST',
      body: { raw_last_row: cap.suggested_raw_last_row, source_last_row: source },
    });
    markSaved(result.save);
    toast(`Limit raised to ${result.raw_last_row.toLocaleString()} rows.`, 'ok');
    await refreshAll();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

async function checkTimesheetFile() {
  const file = $('#ts-file').files[0];
  const engineer = $('#ts-engineer').value;
  if (!file) { toast('Choose an export file first.', 'bad'); return; }

  const result = $('#ts-result');
  setChildren(result, el('p', { class: 'muted' },
    el('span', { class: 'spin' }), ` Reading ${file.name}…`));

  const base64 = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('Could not read the file.'));
    reader.readAsDataURL(file);
  });

  try {
    const parsed = await api('/api/timesheets/stage', {
      method: 'POST',
      body: {
        engineer, filename: file.name, content_base64: base64,
        registered_only: $('#ts-registered').checked,
      },
    });
    state.stagedImport = parsed;
    renderImportResult(parsed);
  } catch (error) {
    setChildren(result, ...(error.errors || [error.message]).map(
      (message) => el('div', { class: 'msg msg-bad' }, message)));
  }
}

function renderImportResult(parsed) {
  const s = parsed.summary || {};
  const blocked = (parsed.errors || []).length > 0;
  const rows = (parsed.preview || []).map((row) => el('tr', {},
    el('td', { class: 'code' }, row.JobNumber ?? '—'),
    el('td', {}, row.FullName ?? '—'),
    el('td', {}, row.Date ?? '—'),
    el('td', { class: 'num' }, row.Phase ?? '—'),
    el('td', { class: 'num' }, fmt.hours(row.RegularHours)),
    el('td', { class: 'num' }, fmt.hours(row.OvertimeHours)),
    el('td', { class: 'num' }, fmt.hours(row.TotalHours))));

  setChildren($('#ts-result'), 
    ...(parsed.errors || []).map((m) => el('div', { class: 'msg msg-bad' }, m)),
    ...(parsed.warnings || []).map((m) => el('div', { class: 'msg msg-warn' }, m)),
    el('div', { class: 'msg msg-info' },
      el('strong', {}, `${fmt.int(parsed.row_count)} rows to import from ${parsed.source_name}. `),
      `${parsed.mapped_columns} of 72 columns matched. `,
      `${fmt.hours(s.hours)} hours, ${fmt.date(s.first_date)} → ${fmt.date(s.last_date)}`,
      s.months && s.months.length ? ` across ${s.months.length} month(s).` : '.',
      parsed.dropped_rows
        ? ` ${fmt.int(parsed.dropped_rows)} unregistered row(s) left out.` : ''),
    (s.people || []).length > 1
      ? el('div', { class: 'msg msg-warn' },
          `More than one person in this file: ${s.people.map((p) => `${p.name} (${p.rows})`).join(', ')}`)
      : null,
    el('div', { class: 'table-wrap' },
      el('table', {},
        el('thead', {}, el('tr', {},
          ['Job number', 'Name', 'Date', 'Phase', 'Regular', 'Overtime', 'Total']
            .map((h, i) => el('th', { class: i >= 3 ? 'num' : '' }, h)))),
        el('tbody', {}, rows))),
    el('p', { class: 'muted', style: 'margin-top:10px' },
      `The sheet currently holds ${fmt.int(parsed.existing_rows)} rows. `
      + 'Replacing is the monthly routine; appending would add '
      + `${fmt.int(parsed.duplicate_rows_if_appended)} row(s) that already look present.`),
    el('div', { class: 'row', style: 'margin-bottom:0' },
      el('button', {
        class: 'btn btn-primary', type: 'button', disabled: blocked,
        onclick: () => applyImport('replace'),
      }, `Replace all rows for ${parsed.engineer}`),
      el('button', {
        class: 'btn', type: 'button', disabled: blocked,
        onclick: () => applyImport('append'),
      }, 'Append'),
      el('button', { class: 'btn btn-ghost', type: 'button', onclick: discardImport },
        'Discard')));
}

async function applyImport(mode) {
  const parsed = state.stagedImport;
  if (!parsed) return;
  const verb = mode === 'replace' ? 'Replace every row for' : 'Append these rows to';
  if (!window.confirm(
    `${verb} ${parsed.engineer} with ${parsed.row_count.toLocaleString()} row(s)?`
    + '\n\nA timestamped backup of the workbook is taken first.')) return;
  try {
    const result = await api('/api/timesheets/apply', {
      method: 'POST', body: { token: parsed.token, mode },
    });
    markSaved(result.save);
    state.stagedImport = null;
    $('#ts-file').value = '';
    const raised = result.capacity_raised;
    setChildren($('#ts-result'),
      el('div', { class: 'msg msg-ok' },
        `${result.engineer} now has ${fmt.int(result.rows)} rows. `
        + `${result.data_check.verdict}`),
      // The app raises the limit itself rather than letting rows land on the
      // sheet where nothing reads them; it should say so when it does.
      raised
        ? el('div', { class: 'msg msg-info' },
            `The workbook now reads ${fmt.int(raised.entries)} entries `
            + `(it read ${fmt.int(raised.entries_from)} before) — raised `
            + `automatically because ${raised.why}, so nothing was missed. `
            + 'Excel will take a little longer to recalculate the file.')
        : null);
    toast(`${result.engineer} updated (${fmt.int(result.rows)} rows).`, 'ok');
    await refreshAll();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

async function discardImport() {
  if (state.stagedImport) {
    await api('/api/timesheets/discard', {
      method: 'POST', body: { token: state.stagedImport.token },
    }).catch(() => {});
  }
  state.stagedImport = null;
  $('#ts-file').value = '';
  setChildren($('#ts-result'));
}

/* -------------------------------------------------------------- projects */

function statusPill(status) {
  if (status === 'Active') return 'pill-ok';
  if (status === 'Not Started') return 'pill-info';
  if (status === 'On Hold') return 'pill-warn';
  if (status === 'Cancelled') return 'pill-bad';
  return '';
}

/** The sortable columns, in the order the table shows them.
 *
 *  Each one knows how to read its own value, so sorting and rendering cannot
 *  disagree about what a column holds.
 */
const PROJECT_COLUMNS = [
  { key: null, label: '#', num: true },
  { key: 'number', label: 'Number', text: true, of: (p) => p.number },
  { key: 'name', label: 'Name', text: true, of: (p) => p.name },
  { key: 'status', label: 'Status', text: true, of: (p) => p.status },
  { key: 'budget_mm', label: 'Budget MM', num: true, of: (p) => p.budget_mm },
  { key: 'progress', label: 'Progress', num: true, of: (p, m) => m.progress },
  { key: 'actual_mm', label: 'Actual MM', num: true, of: (p, m) => m.actual_mm },
  { key: 'earned_mm', label: 'Earned MM', num: true, of: (p, m) => m.earned_mm },
  { key: 'profit_mm', label: 'Profit MM', num: true, of: (p, m) => m.profit_mm },
  { key: 'cpi', label: 'CPI', num: true, of: (p, m) => m.cpi },
  { key: 'deliverables', label: 'Deliverables', num: true,
    of: (p, m) => m.deliverables || 0 },
];

/** Sort the filtered rows in place. Nulls sink, whichever way the sort runs. */
function sortProjects(rows, byNumber) {
  const { key, dir } = state.projectSort;
  const column = PROJECT_COLUMNS.find((c) => c.key === key);
  if (!column || !column.of) return;          // the register's own order
  rows.sort((a, b) => {
    const left = column.of(a, byNumber.get(a.number) || {});
    const right = column.of(b, byNumber.get(b.number) || {});
    const leftMissing = left === null || left === undefined || left === '';
    const rightMissing = right === null || right === undefined || right === '';
    if (leftMissing || rightMissing) return leftMissing - rightMissing;
    if (column.text) return dir * String(left).localeCompare(String(right));
    return dir * (left - right);
  });
}

function projectHeader(column) {
  if (column.key === null) {
    // The row number is the position in the table, so it never sorts itself;
    // clicking it puts the register's own order back.
    const ordered = state.projectSort.key === null;
    return el('th', {
      class: `num sortable${ordered ? ' sorted' : ''}`,
      title: 'Back to the order the register holds them in',
      onclick: () => { state.projectSort = { key: null, dir: 1 }; renderProjects(); },
    }, column.label);
  }
  const active = state.projectSort.key === column.key;
  const arrow = active ? (state.projectSort.dir === 1 ? ' ▲' : ' ▼') : '';
  return el('th', {
    class: `${column.num ? 'num' : ''} sortable${active ? ' sorted' : ''}`,
    'aria-sort': active
      ? (state.projectSort.dir === 1 ? 'ascending' : 'descending')
      : 'none',
    title: `Sort by ${column.label.toLowerCase()}`,
    onclick: () => sortProjectsBy(column),
  }, `${column.label}${arrow}`);
}

/** Click once to sort, again to reverse. Numbers open on their largest. */
function sortProjectsBy(column) {
  const current = state.projectSort;
  state.projectSort = current.key === column.key
    ? { key: column.key, dir: -current.dir }
    : { key: column.key, dir: column.num ? -1 : 1 };
  renderProjects();
}

function renderProjects() {
  const projectSelect = $('#project-filter');
  const chosen = projectSelect.value || 'all';
  setChildren(projectSelect, 
    el('option', { value: 'all' }, `All projects (${state.projects.length})`),
    ...state.projects.map((p) => el('option', { value: p.number },
      `${p.number} — ${p.name}`)));
  projectSelect.value = state.projects.some((p) => p.number === chosen) ? chosen : 'all';

  const statusSelect = $('#project-status-filter');
  const chosenStatus = statusSelect.value || 'all';
  const statuses = (state.reference.statuses || []).filter(
    (name) => state.projects.some((p) => p.status === name));
  setChildren(statusSelect, 
    el('option', { value: 'all' }, 'Any status'),
    ...statuses.map((name) => el('option', { value: name },
      `${name} (${state.projects.filter((p) => p.status === name).length})`)));
  statusSelect.value = statuses.includes(chosenStatus) ? chosenStatus : 'all';

  const filter = $('#project-search').value.trim().toLowerCase();
  const byNumber = new Map(state.projectMetrics.map((m) => [m.number, m]));
  const rows = state.projects.filter((p) => {
    if (projectSelect.value !== 'all' && p.number !== projectSelect.value) return false;
    if (statusSelect.value !== 'all' && p.status !== statusSelect.value) return false;
    return !filter || `${p.number} ${p.name}`.toLowerCase().includes(filter);
  });

  sortProjects(rows, byNumber);

  setChildren($('#projects-table'), 
    el('thead', {}, el('tr', {}, [
      ...PROJECT_COLUMNS.map((column) => projectHeader(column)),
      el('th', {}, ''),
    ])),
    el('tbody', {}, rows.length === 0
      ? el('tr', {}, el('td', { colspan: 12 },
          el('div', { class: 'empty' }, 'No projects match.')))
      : rows.map((project, position) => {
        const m = byNumber.get(project.number) || {};
        return el('tr', { class: 'clickable', onclick: () => openProject(project.number) },
          el('td', { class: 'num muted', title: `Inputs row ${project.row}` }, position + 1),
          el('td', { class: 'code' }, project.number),
          el('td', { class: 'wide' }, project.name),
          el('td', {}, el('span', { class: `pill ${statusPill(project.status)}` },
            project.status || '—')),
          el('td', { class: 'num' }, fmt.mm(project.budget_mm)),
          el('td', { class: 'num' }, progressCell(m.progress)),
          el('td', { class: 'num' }, fmt.mm(m.actual_mm)),
          el('td', { class: 'num' }, fmt.mm(m.earned_mm)),
          el('td', { class: 'num' }, toned(m.profit_mm, tone.amount, fmt.mm)),
          el('td', { class: 'num' }, m.cpi === null || m.cpi === undefined
            ? '—' : toned(m.cpi, tone.cpi, fmt.ratio)),
          el('td', { class: 'num' }, m.deliverables
            ? (m.weight_ok
                ? fmt.int(m.deliverables)
                : el('span', { class: 'pill pill-bad',
                    title: `Phase weights total ${fmt.pct(m.weight_total)}, not 100%` },
                    `${m.deliverables} · ${fmt.pct(m.weight_total)}`))
            : el('span', { class: 'pill pill-warn' }, 'none yet')),
          el('td', {}, el('span', { class: 'chevron' }, '›')));
      })));
}

/* --------------------------------------------------- one project's page */

async function openProject(number) {
  try {
    state.detail = await api(`/api/projects/${encodeURIComponent(number)}`);
  } catch (error) {
    toast(error.message, 'bad');
    return;
  }
  state.detail.draft = {
    project: { ...state.detail.project },
    deliverables: state.detail.deliverables.map((d) => ({ ...d })),
  };
  renderDetail();
  $('#projects-list').hidden = true;
  $('#project-detail').hidden = false;
  window.scrollTo(0, 0);
}

function newProject() {
  state.detail = {
    project: null,
    draft: {
      project: {
        number: '', name: '', budget_mm: null, status: 'Active',
        start: null, end: null, notes: '',
      },
      deliverables: [],
    },
  };
  renderDetail();
  $('#projects-list').hidden = true;
  $('#project-detail').hidden = false;
  window.scrollTo(0, 0);
}

function closeDetail() {
  state.detail = null;
  $('#project-detail').hidden = true;
  $('#projects-list').hidden = false;
}

function weightTotal() {
  return state.detail.draft.deliverables.reduce(
    (sum, d) => sum + (Number(d.phase_weight) || 0), 0);
}

function field(label, name, opts = {}) {
  const draft = state.detail.draft.project;
  const raw = opts.percent ? toPercent(draft[name]) : draft[name];
  const input = el('input', {
    type: opts.type || 'text', value: raw === null || raw === undefined ? '' : raw,
    step: opts.step, min: opts.min, max: opts.max, placeholder: opts.placeholder,
    oninput: (e) => {
      const value = e.target.value.trim() === '' ? null : e.target.value.trim();
      draft[name] = opts.percent ? fromPercent(value)
        : opts.number ? (value === null ? null : Number(value)) : value;
      if (opts.rerender) renderDetail();
    },
  });
  return el('label', { class: `field ${opts.full ? 'full' : ''}` },
    el('span', {}, label, opts.hint ? el('span', { class: 'hint' }, ` — ${opts.hint}`) : null),
    input);
}

function selectField(label, name, options, opts = {}) {
  const draft = state.detail.draft.project;
  const select = el('select', {
    onchange: (e) => { draft[name] = e.target.value || null; },
  }, options.map((o) => {
    const value = typeof o === 'string' ? o : o.value;
    const text = typeof o === 'string' ? o : o.label;
    return el('option', { value }, text);
  }));
  select.value = draft[name] ?? '';
  return el('label', { class: `field ${opts.full ? 'full' : ''}` },
    el('span', {}, label), select);
}

function renderDetail() {
  const { project, draft, metrics: figures } = state.detail;
  const isNew = !project;

  setChildren($('#project-detail'), 
    el('div', { class: 'crumb' },
      el('button', { class: 'btn btn-ghost btn-sm', type: 'button', onclick: closeDetail },
        '‹ All projects'),
      el('span', { class: 'muted' }, isNew ? 'New project' : draft.project.number)),

    el('div', { class: 'view-head' },
      el('div', {},
        el('h2', {}, isNew ? 'Add a project' : (draft.project.name || draft.project.number)),
        el('p', { class: 'muted' }, isNew
          ? 'Enter the project, then the deliverables that make up its scope.'
          : `Inputs row ${project.row} · ${draft.project.number}`)),
      isNew ? null : el('button', {
        class: 'btn btn-danger', type: 'button', onclick: () => removeProject(project),
      }, 'Delete project')),

    figures ? el('div', { class: 'cards' }, [
      ['Progress', fmt.pct(figures.progress), 'weighted by rules of credit'],
      ['Actual MM', fmt.mm(figures.actual_mm), `${fmt.hours(figures.actual_hours)} hours booked`],
      ['Earned MM', fmt.mm(figures.earned_mm), 'budget × progress'],
      ['CPI', fmt.ratio(figures.cpi), figures.cpi >= 1 ? 'earning above cost' : 'earning below cost'],
    ].map(([l, v, s]) => el('div', { class: 'card' },
      el('div', { class: 'label' }, l),
      el('div', { class: 'value' }, v),
      el('div', { class: 'sub' }, s)))) : null,

    el('section', { class: 'panel' },
      el('h3', {}, 'Project'),
      el('div', { class: 'form-grid' },
        field('Project number', 'number', { hint: 'as it appears on the timesheet' }),
        field('Project name', 'name'),
        field('Budget (MM)', 'budget_mm', { type: 'number', step: '0.01', min: '0', number: true }),
        selectField('Status', 'status', state.reference.statuses),
        field('Start', 'start', { type: 'date' }),
        field('End', 'end', { type: 'date' }),
        field('Manual % complete', 'manual_percent', {
          type: 'number', step: '1', min: '0', max: '100', percent: true,
          hint: 'used only until the project has deliverables' }),
        field('Cost at completion override (MM)', 'cac_override', {
          type: 'number', step: '0.01', number: true,
          hint: 'leave blank to let the workbook derive it' }),
        el('label', { class: 'field full' },
          el('span', {}, 'Notes'),
          el('textarea', {
            oninput: (e) => { draft.project.notes = e.target.value; },
          }, draft.project.notes || '')))),

    el('section', { class: 'panel' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Deliverables'),
          el('p', { class: 'muted' },
            'The phase weights are each deliverable’s share of this project’s scope, '
            + 'and have to account for all of it before the project can be saved.')),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: addDeliverable },
          '+ Add deliverable')),
      weightBar(),
      draft.deliverables.length
        ? el('div', { class: 'table-wrap' }, el('table', { class: 'edit-table' },
            el('thead', {}, el('tr', {},
              ['#', 'Deliverable / phase', 'Type', 'Step reached', 'Weight %',
               'TS Phase', ...state.reference.engineers.map((e) => `${e.short_name} %`),
               'Status date', ''].map((h, i) => el('th', {
                class: [0, 4, 5, 6, 7, 8].includes(i) ? 'num' : '',
              }, h)))),
            el('tbody', {}, draft.deliverables.map(deliverableRow))))
        : el('div', { class: 'empty' },
            'No deliverables yet. Add the phases this project is measured by.')),

    el('div', { class: 'sticky-foot' },
      el('div', { class: 'errors', id: 'detail-errors' }),
      el('div', { class: 'foot-actions' },
        el('button', { class: 'btn btn-ghost', type: 'button', onclick: closeDetail }, 'Cancel'),
        el('button', {
          class: 'btn btn-primary', type: 'button', id: 'detail-save',
          onclick: saveDetail,
        }, isNew ? 'Create project' : 'Save project'))));

  refreshTotals();
}

function weightBar() {
  return el('div', { class: 'weight-bar' },
    el('div', { class: 'meter', id: 'weight-meter' }, el('span', {})),
    el('div', { class: 'weight-note', id: 'weight-note' }));
}

/* Recompute the totals without rebuilding the table.
 *
 * Re-rendering on every keystroke would take the focus out of the cell being
 * typed into, so the grid's DOM is left alone and only the parts that depend
 * on the numbers are refreshed.
 */
function refreshTotals() {
  if (!state.detail) return;
  const draft = state.detail.draft;
  const total = weightTotal();
  const complete = draft.deliverables.length === 0 || Math.abs(total - 1) <= 1e-4;

  const meter = $('#weight-meter');
  if (meter) {
    meter.className = `meter ${complete ? '' : total > 1 ? 'bad' : 'warn'}`;
    meter.firstChild.style.width = `${Math.min(100, Math.round(total * 100))}%`;
  }
  const note = $('#weight-note');
  if (note) {
    setChildren(note, 
      el('span', { class: `pill ${complete ? 'pill-ok' : 'pill-bad'}` },
        `${(total * 100).toFixed(1)}%`),
      el('span', { class: 'muted' }, complete
        ? 'the scope is fully accounted for'
        : total > 1
          ? `over by ${((total - 1) * 100).toFixed(1)} points — reduce a weight`
          : `${((1 - total) * 100).toFixed(1)} points unaccounted for`));
  }
  const save = $('#detail-save');
  if (save) {
    save.disabled = !complete;
    save.title = complete ? '' : 'The phase weights have to total 100% first';
  }
  // Each row shows whether its own split adds up.
  $$('#project-detail .edit-table tbody tr').forEach((tr, i) => {
    const shares = draft.deliverables[i] ? draft.deliverables[i].shares || {} : {};
    const sum = Object.values(shares).reduce((a, v) => a + (Number(v) || 0), 0);
    tr.classList.toggle('row-bad', !(sum === 0 || Math.abs(sum - 1) <= 1e-4));
  });
}

function deliverableRow(d, position) {
  const draft = state.detail.draft;
  const set = (key, value) => { d[key] = value; };

  const stepOptions = (code) => [el('option', { value: '' }, '— not started —')]
    .concat(((state.reference.credit_steps || {})[code] || []).map((s) =>
      el('option', { value: s.step_no },
        `${s.step_no}. ${s.step_name} (${Math.round(s.credit * 100)}%)`)));

  const stepSelect = el('select', {
    onchange: (e) => {
      set('step_no', e.target.value === '' ? null : Number(e.target.value));
    },
  }, stepOptions(d.type_code));
  stepSelect.value = d.step_no === null || d.step_no === undefined ? '' : String(d.step_no);

  // Changing the type changes which steps are valid, so only that one list is
  // rebuilt -- the rest of the row keeps whatever is being typed into it.
  const typeSelect = el('select', {
    onchange: (e) => {
      set('type_code', e.target.value);
      set('step_no', null);
      setChildren(stepSelect, ...stepOptions(e.target.value));
      stepSelect.value = '';
    },
  }, state.reference.project_types.map((t) =>
    el('option', { value: t.code }, `${t.code} — ${t.name}`)));
  typeSelect.value = d.type_code || '';

  const num = (key, opts = {}) => el('input', {
    type: 'number', step: opts.step || '1', min: '0', max: opts.max,
    value: opts.percent ? toPercent(d[key]) : (d[key] ?? ''),
    oninput: (e) => {
      const raw = e.target.value.trim() === '' ? null : e.target.value.trim();
      set(key, opts.percent ? fromPercent(raw) : (raw === null ? null : Number(raw)));
      refreshTotals();
    },
  });

  // The split is keyed by engineer name, so it follows whoever this unit's
  // team happens to be rather than three fixed columns.
  const shareInput = (name) => el('input', {
    type: 'number', step: '1', min: '0', max: '100',
    value: toPercent((d.shares || {})[name]),
    oninput: (e) => {
      const raw = e.target.value.trim() === '' ? null : e.target.value.trim();
      d.shares = { ...(d.shares || {}), [name]: fromPercent(raw) };
      refreshTotals();
    },
  });

  return el('tr', {},
    el('td', { class: 'num muted' }, position + 1),
    el('td', {}, el('input', {
      type: 'text', value: d.name || '', placeholder: 'e.g. Detailed Design',
      oninput: (e) => set('name', e.target.value),
    })),
    el('td', {}, typeSelect),
    el('td', {}, stepSelect),
    el('td', { class: 'num' }, num('phase_weight', {
      percent: true, step: '0.1', max: '100' })),
    el('td', { class: 'num' }, num('ts_phase')),
    ...state.reference.engineers.map((e) => el('td', { class: 'num' },
      shareInput(e.short_name))),
    el('td', {}, el('input', {
      type: 'date', value: d.status_date || '',
      oninput: (e) => set('status_date', e.target.value || null),
    })),
    el('td', {}, el('button', {
      class: 'btn btn-sm btn-danger', type: 'button',
      title: 'Remove this deliverable',
      onclick: () => {
        draft.deliverables.splice(position, 1);
        renderDetail();
      },
    }, '✕')));
}

function addDeliverable() {
  const draft = state.detail.draft;
  const remaining = Math.max(0, 1 - weightTotal());
  const shares = {};
  for (const e of state.reference.engineers) shares[e.short_name] = null;
  draft.deliverables.push({
    row: null, name: '', type_code: state.reference.project_types[0].code,
    step_no: null, phase_weight: remaining || null, ts_phase: null,
    status_date: null, notes: '', shares,
  });
  renderDetail();
}

async function saveDetail() {
  const { project, draft } = state.detail;
  const button = $('#detail-save');
  button.disabled = true;
  try {
    const path = project
      ? `/api/projects/${encodeURIComponent(project.number)}/full`
      : '/api/projects/full';
    const result = await api(path, {
      method: project ? 'PUT' : 'POST',
      body: { project: draft.project, deliverables: draft.deliverables },
    });
    markSaved(result.save);
    toast(`${result.project.number} saved with ${result.deliverables.length} deliverable(s).`, 'ok');
    closeDetail();
    await refreshAll();
  } catch (error) {
    setChildren($('#detail-errors'), 
      el('ul', {}, (error.errors || [error.message]).map((e) => el('li', {}, e))));
    button.disabled = false;
  }
}

async function removeProject(project) {
  const count = state.detail.draft.deliverables.length;
  const extra = count ? `\n\nIts ${count} deliverable(s) go with it.` : '';
  if (!window.confirm(`Remove ${project.number} from the register?${extra}`)) return;
  try {
    const result = await api(
      `/api/projects/${encodeURIComponent(project.number)}?cascade=true`,
      { method: 'DELETE' });
    markSaved(result.save);
    toast(`${project.number} removed.`, 'ok');
    closeDetail();
    await refreshAll();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

/* ------------------------------------------------------------ reference */

function renderReference() {
  const unlocked = state.status && state.status.reference_unlocked;
  setChildren($('#reference-lock'), unlocked
    ? el('div', { class: 'row', style: 'margin:0' },
        el('span', { class: 'pill pill-warn' }, 'unlocked for editing'),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: lockReference }, 'Lock'),
        el('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: saveReference },
          'Save changes'))
    : el('button', { class: 'btn', type: 'button', onclick: unlockReference },
        '🔒 Unlock to edit'));

  if (!state.referenceDraft) {
    state.referenceDraft = {
      project_types: (state.reference.project_types || []).map((t) => ({ ...t })),
      credit_steps: Object.entries(state.reference.credit_steps || {})
        .flatMap(([code, steps]) => steps.map((s) => ({ ...s, type_code: code }))),
      scorecard_factors: (state.reference.scorecard_factors || [])
        .map((f) => ({ ...f })),
    };
  }
  const draft = state.referenceDraft;
  const room = state.reference.capacity || {};
  const stepRoom = room.credit_steps || 34;

  const cell = (obj, key, opts = {}) => unlocked
    ? el('input', {
        type: opts.type || 'text', step: opts.step, min: opts.min, max: opts.max,
        value: opts.percent ? toPercent(obj[key]) : (obj[key] ?? ''),
        oninput: (e) => {
          const raw = e.target.value.trim() === '' ? null : e.target.value.trim();
          obj[key] = opts.percent ? fromPercent(raw)
            : opts.number ? (raw === null ? null : Number(raw)) : raw;
        },
      })
    : (opts.percent ? fmt.pct0(obj[key]) : (obj[key] ?? '—'));

  setChildren($('#reference-body'), 
    unlocked
      ? el('div', { class: 'msg msg-warn' },
          'These tables decide how every deliverable earns credit. A change here '
          + 'moves the progress and CPI of every project that uses the type.')
      : el('div', { class: 'msg msg-info' },
          'Read-only. Unlock to change how project types are weighted or how much '
          + 'credit each step earns.'),

    el('section', { class: 'panel' },
      el('h3', {}, 'Project types'),
      el('div', { class: 'table-wrap' }, el('table', { class: unlocked ? 'edit-table' : '' },
        el('thead', {}, el('tr', {},
          ['Code', 'Project type', 'Measurement basis', 'Earning trigger',
           'Portfolio weight', 'In CPI?', 'Notes'].map((h, i) =>
            el('th', { class: i === 4 ? 'num' : '' }, h)))),
        el('tbody', {}, draft.project_types.map((t) => el('tr', {},
          el('td', { class: 'code' }, cell(t, 'code')),
          el('td', {}, cell(t, 'name')),
          el('td', {}, cell(t, 'basis')),
          el('td', {}, cell(t, 'trigger')),
          el('td', { class: 'num' }, cell(t, 'portfolio_weight',
            { type: 'number', step: '0.05', number: true })),
          el('td', {}, cell(t, 'include_in_cpi')),
          el('td', { class: 'wide' }, cell(t, 'notes')))))))),

    el('section', { class: 'panel' },
      el('div', { class: 'panel-head' },
        el('h3', {}, 'Rules of credit'),
        unlocked
          ? el('div', { class: 'row', style: 'margin:0;align-items:center' },
              el('span', { class: 'muted' },
                `${draft.credit_steps.length} of ${stepRoom} rows used`),
              el('button', {
                class: 'btn btn-sm', type: 'button',
                disabled: draft.credit_steps.length >= stepRoom,
                title: draft.credit_steps.length >= stepRoom
                  ? 'The sheet has no room for another step. Remove one first.' : '',
                onclick: () => {
                  draft.credit_steps.push({
                    type_code: draft.project_types[0]?.code || '', step_no: null,
                    step_name: '', credit: null, data_source: '' });
                  renderReference();
                },
              }, '+ Add step'))
          : null),
      el('div', { class: 'table-wrap' }, el('table', { class: unlocked ? 'edit-table' : '' },
        el('thead', {}, el('tr', {},
          ['Type', 'Step', 'Step name', 'Cumulative credit', 'Data source', '']
            .map((h, i) => el('th', { class: [1, 3].includes(i) ? 'num' : '' }, h)))),
        el('tbody', {}, draft.credit_steps.map((s, i) => el('tr', {},
          el('td', { class: 'code' }, cell(s, 'type_code')),
          el('td', { class: 'num' }, cell(s, 'step_no', { type: 'number', number: true })),
          el('td', { class: 'wide' }, cell(s, 'step_name')),
          el('td', { class: 'num' }, cell(s, 'credit',
            { type: 'number', percent: true, step: '1', min: '0', max: '100' })),
          el('td', {}, cell(s, 'data_source')),
          el('td', {}, unlocked
            ? el('button', { class: 'btn btn-sm btn-danger', type: 'button',
                onclick: () => { draft.credit_steps.splice(i, 1); renderReference(); } }, '✕')
            : ''))))))),

    scorecardPanel(draft, unlocked, cell));
}

/** The factors the team scorecard ranks on — weights, scoring and targets. */
function scorecardPanel(draft, unlocked, cell) {
  const factors = draft.scorecard_factors || [];
  const total = factors.reduce((sum, f) => sum + (Number(f.weight) || 0), 0);
  const balanced = Math.abs(total - 1) <= 1e-4;

  const directionCell = (factor) => unlocked
    ? (() => {
        const select = el('select', {
          onchange: (e) => { factor.direction = e.target.value; renderReference(); },
        },
          el('option', { value: 'higher' }, 'vs best performer'),
          el('option', { value: 'target' }, 'vs a target'));
        select.value = factor.direction || 'higher';
        return select;
      })()
    : (factor.direction === 'target' ? 'vs a target' : 'vs best performer');

  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, 'Scorecard factors'),
        el('p', { class: 'muted' },
          'What the team ranking is built from, and how much each factor counts. '
          + 'The weights have to total 100% or one period\u2019s ranking cannot be '
          + 'read against another\u2019s.')),
      el('span', { class: `pill ${balanced ? 'pill-ok' : 'pill-bad'}` },
        `weights ${fmt.pct(total)}`)),
    el('div', { class: 'table-wrap' }, el('table', { class: unlocked ? 'edit-table' : '' },
      el('thead', {}, el('tr', {},
        ['Factor', 'Weight', 'Scored', 'Target', 'Measured on']
          .map((h, i) => el('th', { class: [1, 3].includes(i) ? 'num' : '' }, h)))),
      el('tbody', {}, factors.map((factor) => el('tr', {},
        el('td', { class: 'wide' }, cell(factor, 'factor')),
        el('td', { class: 'num' }, cell(factor, 'weight',
          { type: 'number', percent: true, step: '5', min: '0', max: '100' })),
        el('td', {}, directionCell(factor)),
        el('td', { class: 'num' }, factor.direction === 'target'
          ? cell(factor, 'target', { type: 'number', step: '0.05', number: true })
          : '—'),
        el('td', { class: 'muted' }, factor.key || '—')))))));
}

async function unlockReference() {
  const password = window.prompt('Password to edit the reference tables:');
  if (password === null) return;
  try {
    await api('/api/reference/unlock', { method: 'POST', body: { password } });
    state.status = await api('/api/status');
    renderReference();
    toast('Reference tables unlocked.', 'ok');
  } catch (error) {
    toast(error.message, 'bad');
  }
}

async function lockReference() {
  await api('/api/reference/lock', { method: 'POST' });
  state.status = await api('/api/status');
  state.referenceDraft = null;
  state.reference = await api('/api/reference');
  renderReference();
}

async function saveReference() {
  try {
    const result = await api('/api/reference', {
      method: 'PUT', body: state.referenceDraft,
    });
    markSaved(result.save);
    toast(`Saved ${result.project_types} types, ${result.credit_steps} steps `
      + `and ${result.factors} scorecard factor(s).`, 'ok');
    state.referenceDraft = null;
    state.reference = await api('/api/reference');
    await refreshAll();
    renderReference();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

/* ------------------------------------------------------------- wiring */

async function refreshAll() {
  const status = await api('/api/status');
  state.status = status;
  if (!status.open) { showShell(false); await renderChooser(); return; }

  const yearParam = state.year === null ? 'all' : state.year;
  const [overview, projects] = await Promise.all([
    api(`/api/overview?year=${yearParam}`),
    api('/api/projects'),
  ]);
  state.overview = overview;
  state.projects = projects.projects;
  state.projectMetrics = projects.metrics;

  $('#unit-title').textContent = status.unit ? status.unit.name : 'Workload';
  // The file lives on the server now, so its path is nobody's business but
  // the administrator's; what a person needs is which unit they are in.
  $('#workbook-path').textContent =
    `${(state.me || {}).display_name || ''}${state.me ? ' · ' : ''}`
    + `${status.projects} project(s) · ${status.deliverables} deliverable(s)`;
  $('#workbook-path').title = 'Switch unit to open another workbook';
  markSaved({ saved: !status.unsaved_changes, pending: status.unsaved_changes });

  renderTimesheets();
  renderProjects();
  renderReference();
  await setupReports();
  if (state.team) await loadTeam();
  if (state.tasks) await loadTasks();
}

async function setupReports() {
  const periods = state.report ? state.report.periods : null;
  if (!periods) {
    // First load: fetch once to learn which years the workbook covers.
    const first = await api('/api/reports?period=year');
    state.report = first;
    state.year = first.period.year;
    if (!state.reportMember) state.reportMember = first.engineers[0];
    const yearSelect = $('#report-year');
    setChildren(yearSelect, ...first.periods.years.map(
      (y) => el('option', { value: y }, y)));
    yearSelect.value = String(first.periods.plan_year);
    setChildren($('#report-quarter'), ...first.periods.quarters.map(
      (q) => el('option', { value: q }, q)));
    $('#report-quarter-field').hidden = true;
    renderReports();
    renderOverview();
  } else {
    await loadReport();
    renderOverview();
  }
}

function switchView(view) {
  if (view === 'team' && !state.team) loadTeam();
  if (view === 'tasks' && !state.tasks) loadTasks();
  for (const tab of $$('.tab')) tab.classList.toggle('is-active', tab.dataset.view === view);
  for (const section of $$('.view')) {
    section.classList.toggle('is-active', section.id === `view-${view}`);
  }
  if (view !== 'projects') closeDetail();
}

function wire() {
  for (const tab of $$('.tab')) {
    tab.addEventListener('click', () => switchView(tab.dataset.view));
  }
  $('#overview-year').addEventListener('change', async (event) => {
    // One year drives both the portfolio figures and the workload charts, so
    // the page can never show one year's effort beside another's budget.
    const value = event.target.value;
    state.year = value === 'all' ? null : Number(value);
    const query = value === 'all' ? 'period=all' : `period=year&year=${value}`;
    [state.overview, state.report] = await Promise.all([
      api(`/api/overview?year=${value}`),
      api(`/api/reports?${query}`),
    ]);
    $('#report-period').value = value === 'all' ? 'all' : 'year';
    if (value !== 'all') $('#report-year').value = value;
    renderOverview();
    renderTimesheets();
    renderReports();
  });
  $('#project-search').addEventListener('input', renderProjects);
  $('#project-filter').addEventListener('change', renderProjects);
  $('#project-status-filter').addEventListener('change', renderProjects);
  $('#btn-new-project').addEventListener('click', newProject);
  $('#btn-ts-check').addEventListener('click', checkTimesheetFile);
  $('#btn-add-engineer').addEventListener('click', () => openEngineerModal(null));
  $('#btn-add-task').addEventListener('click', () => openTaskModal(null));
  $('#btn-task-settings').addEventListener('click', openWorkingDayModal);
  $('#btn-task-submissions').addEventListener('click', openSubmissionModal);
  $('#btn-task-meeting').addEventListener('click', openMeetingModal);
  for (const id of ['#task-engineer', '#task-project', '#task-status-filter',
    '#task-show-done']) {
    $(id).addEventListener('change', () => renderTaskTable(state.tasks));
  }
  $('#task-search').addEventListener('input', () => renderTaskTable(state.tasks));
  $('#btn-new-unit').addEventListener('click', newUnit);
  $('#btn-upload-unit').addEventListener('click', uploadUnit);
  $('#btn-signout-chooser').addEventListener('click', signOut);
  $('#btn-account-chooser').addEventListener('click', openAccountPanel);
  $('#btn-account').addEventListener('click', openAccountPanel);
  $('#unit-name').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') newUnit();
  });

  $('#btn-save').addEventListener('click', async () => {
    const result = await api('/api/save', { method: 'POST' });
    markSaved(result.saved ? result : { saved: true });
    toast(result.saved ? `Saved. Backup: ${result.backup}` : 'Nothing to save.', 'ok');
  });
  $('#btn-reload').addEventListener('click', async () => {
    if (state.status && state.status.unsaved_changes
      && !window.confirm('Discard unsaved changes and re-read the file from disk?')) return;
    await api('/api/reload', { method: 'POST' });
    state.referenceDraft = null;
    await refreshAll();
    toast('Workbook re-read from disk.', 'ok');
  });
  $('#btn-change').addEventListener('click', async () => {
    await api('/api/units/close', { method: 'POST' });
    state.referenceDraft = null;
    state.detail = null;
    showShell(false);
    await renderChooser();
  });
  // reports
  $('#report-period').addEventListener('change', () => {
    $('#report-quarter-field').hidden = $('#report-period').value !== 'quarter';
    $('#report-year').disabled = $('#report-period').value === 'all';
    loadReport();
  });
  $('#report-year').addEventListener('change', loadReport);
  $('#report-quarter').addEventListener('change', loadReport);
  $('#btn-print').addEventListener('click', () => window.print());

  $('#modal-close').addEventListener('click', closeModal);
  $('#modal-cancel').addEventListener('click', closeModal);
  $('#modal-submit').addEventListener('click', async () => {
    if (!modalSubmit) return;
    const button = $('#modal-submit');
    button.disabled = true;
    try {
      await modalSubmit();
      closeModal();
    } catch (error) {
      showModalErrors(error.errors || [error.message]);
    } finally {
      button.disabled = false;
    }
  });
  $('#modal-form').addEventListener('submit', (e) => e.preventDefault());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#modal-backdrop').hidden) closeModal();
  });
}

(async function start() {
  wire();
  try {
    const who = await api('/api/auth/me');
    if (!who.user) { window.location.href = '/login.html'; return; }
    state.me = who.user;
    const status = await api('/api/status');
    state.status = status;
    if (status.open) await enterApp();
    else { showShell(false); await renderChooser(); }
  } catch (error) {
    document.body.prepend(el('div', { class: 'msg msg-bad', style: 'margin:20px' },
      `Could not start: ${error.message}`));
  }
})();

/* ------------------------------------------------------------- reports */

const REPORT_VIEWS = [
  ['dashboard', 'Dashboard'],
  ['engineers', 'Engineer KPIs'],
  ['member', 'Team Member'],
  ['scorecard', 'Scorecard'],
  ['review', 'Management Review'],
];

state.report = null;
state.reportView = 'dashboard';
state.reportMember = null;

function num(value, digits = 2) {
  return value === null || value === undefined ? '—' : Number(value).toFixed(digits);
}

/** A table under every chart: the light-mode series colours sit below 3:1, so
 *  the numbers have to be readable without relying on the colour. */
function table(headers, rows, opts = {}) {
  const numeric = opts.numeric || [];
  return el('div', { class: 'table-wrap' }, el('table', {},
    el('thead', {}, el('tr', {}, headers.map((h, i) =>
      el('th', { class: numeric.includes(i) ? 'num' : '' }, h)))),
    el('tbody', {}, rows.map((row) => el('tr', { class: row.__class || '' },
      row.cells.map((cell, i) =>
        el('td', { class: numeric.includes(i) ? 'num' : (cell.wide ? 'wide' : '') },
          cell && cell.node ? cell.node : cell)))))));
}

function kpiCards(items) {
  return el('div', { class: 'cards' }, items.map(([label, value, sub, cls]) =>
    el('div', { class: 'card' },
      el('div', { class: 'label' }, label),
      el('div', { class: `value ${cls ? `v-${cls}` : ''}` }, value),
      el('div', { class: 'sub' }, sub))));
}

async function loadReport() {
  const period = $('#report-period').value;
  const year = $('#report-year').value;
  const quarter = $('#report-quarter').value;
  const query = period === 'all' ? 'period=all'
    : `period=${period}&year=${year}${period === 'quarter' ? `&quarter=${quarter}` : ''}`;
  state.report = await api(`/api/reports?${query}`);
  if (!state.reportMember) state.reportMember = state.report.engineers[0];
  renderReports();
}

function renderReports() {
  const data = state.report;
  if (!data) return;

  setChildren($('#report-subtabs'), ...REPORT_VIEWS.map(([key, label]) =>
    el('button', {
      class: `subtab ${state.reportView === key ? 'is-active' : ''}`, type: 'button',
      onclick: () => { state.reportView = key; renderReports(); },
    }, label)));

  setChildren($('#report-header'), 
    el('div', { class: 'print-head' },
      el('h1', {}, data.unit ? data.unit.name : 'Workload'),
      el('p', {}, `${REPORT_VIEWS.find(([k]) => k === state.reportView)[1]}`
        + ` · ${data.period.label} · as at ${data.as_at}`)));

  const body = $('#report-body');
  const views = {
    dashboard: renderDashboard, engineers: renderEngineerKpis,
    member: renderTeamMember, scorecard: renderScorecard, review: renderReview,
  };
  setChildren(body, views[state.reportView](data));
}

/* -- Dashboard ---------------------------------------------------------- */

/** A colour per status, fixed by the register's own status order so a status
 *  keeps the same colour across every chart and period. */
function statusColor(status) {
  const order = (state.reference && state.reference.statuses) || [];
  const index = order.indexOf(status);
  return `var(--series-${(index < 0 ? 0 : index % 6) + 1})`;
}

/** A colour per engineer, fixed by the team's order on Work Calendar. */
function engineerColor(name) {
  const index = (state.report ? state.report.engineers : []).indexOf(name);
  return `var(--series-${(index < 0 ? 0 : index % 6) + 1})`;
}

function renderDashboard(data) {
  const t = data.team;
  const statuses = data.by_status;
  return el('div', {},
    el('h3', { class: 'report-title' }, `Portfolio dashboard — ${data.period.label}`),
    kpiCards([
      ['Planned MM', num(t.planned_mm), 'full period plan'],
      ['Actual MM', num(t.actual_mm), 'what was burned'],
      ['Earned MM', num(t.earned_mm), 'value delivered'],
      ['Profit / (loss)', num(t.profit_mm), 'earned − actual', tone.amount(t.profit_mm)],
      ['Utilisation', fmt.pct(t.utilisation), `vs ${num(t.capacity_to_date_mm)} MM capacity to date`,
        tone.utilisation(t.utilisation)],
      ['Efficiency (CPI)', fmt.ratio(t.cpi),
        t.cpi >= 1 ? 'earning above cost' : 'earning below cost', tone.cpi(t.cpi)],
      ['Plan adherence', fmt.pct(t.plan_adherence),
        `vs ${num(t.planned_to_date_mm)} MM planned to date`,
        tone.target(t.plan_adherence)],
      ['Active projects', fmt.int(t.projects_active),
        `${t.projects_not_started} not started · ${t.projects_live} live`],
    ]),

    el('div', { class: 'report-grid' },
      el('section', { class: 'panel' },
        charts.donut(statuses.map((s) => ({
          label: s.status, value: s.budget_mm, color: statusColor(s.status) })), {
          title: 'Budget by project status',
          note: 'projects live in this period', unit: 'MM',
        })),
      el('section', { class: 'panel' },
        charts.donut(statuses.map((s) => ({
          label: s.status, value: s.actual_mm, color: statusColor(s.status) })), {
          title: 'Effort spent by project status',
          note: 'actual MM booked in this period', unit: 'MM',
        }))),

    el('section', { class: 'panel' },
      el('h3', {}, 'Portfolio by status'),
      el('p', { class: 'muted' },
        'Only projects live in this period, which is why these total less than '
        + 'the headline figures above — those cover every project in the register, '
        + 'as the workbook reports them.'),
      table(['Status', 'Projects', 'Budget MM', 'Planned MM', 'Actual MM',
             'Earned MM', 'Remaining MM', 'In scope?'],
        statuses.map((s) => ({
          cells: [s.status, fmt.int(s.projects), num(s.budget_mm), num(s.planned_mm),
                  num(s.actual_mm), num(s.earned_mm), num(s.remaining_mm),
                  s.in_scope ? 'Yes' : '—'],
        })).concat([{
          __class: 'total-row',
          cells: ['TOTAL (live in period)',
            fmt.int(statuses.reduce((a, s) => a + s.projects, 0)),
            num(statuses.reduce((a, s) => a + s.budget_mm, 0)),
            num(statuses.reduce((a, s) => a + s.planned_mm, 0)),
            num(statuses.reduce((a, s) => a + s.actual_mm, 0)),
            num(statuses.reduce((a, s) => a + s.earned_mm, 0)),
            num(statuses.reduce((a, s) => a + s.remaining_mm, 0)), ''],
        }]), { numeric: [1, 2, 3, 4, 5, 6] })),

    el('section', { class: 'panel' },
      el('h3', {}, 'Project detail'),
      el('p', { class: 'muted' }, 'Projects live in the selected period.'),
      table(['Project', 'Status', 'Budget', '% compl.', 'Planned', 'Actual',
             'Earned', 'CPI', 'Cost at compl.', 'Remaining', 'Profit'],
        data.projects.filter((p) => p.live)
          .sort((a, b) => (b.actual_mm || 0) - (a.actual_mm || 0))
          .map((p) => ({
            cells: [p.number, p.status, num(p.budget_mm),
              { node: progressCell(p.progress) },
              num(p.planned_mm), num(p.actual_mm), num(p.earned_mm),
              p.cpi === null ? '—' : toned(p.cpi, tone.cpi, fmt.ratio),
              num(p.cost_at_completion_mm), num(p.remaining_mm),
              toned(p.lifetime_profit_mm, tone.amount, num)],
          })), { numeric: [2, 3, 4, 5, 6, 7, 8, 9, 10] })));
}

/* -- Engineer KPIs ------------------------------------------------------ */

function renderEngineerKpis(data) {
  const names = data.engineers;
  const per = data.per_engineer;
  const rows = [
    ['Actual MM booked', 'actual_mm', num, null],
    ['Planned MM to date', 'planned_to_date_mm', num, null],
    ['Earned MM', 'earned_mm', num, null],
    ['Profit / (loss) MM', 'profit_mm', num, tone.amount],
    ['Capacity MM to date', 'capacity_to_date_mm', num, null],
    ['Utilisation', 'utilisation', fmt.pct, tone.utilisation],
    ['Plan adherence', 'plan_adherence', fmt.pct, tone.target],
    ['Efficiency (CPI)', 'cpi', fmt.ratio, tone.cpi],
    ['Type-weighted earned MM', 'type_weighted_earned_mm', num, null],
    ['Type-weighted CPI', 'type_weighted_cpi', fmt.ratio, tone.cpi],
    ['Share of team time', 'share_of_team_time', fmt.pct, null],
    ['Remaining on hand', 'remaining_mm', num, null],
    ['Projects worked', 'projects_worked', (v) => fmt.int(v), null],
    ['Average MM per project', 'average_mm_per_project', num, null],
  ];

  const worked = {};
  for (const name of names) {
    for (const project of per[name].projects) {
      worked[project.number] = worked[project.number]
        || { number: project.number, name: project.name, status: project.status, by: {} };
      worked[project.number].by[name] = project.actual_mm;
    }
  }
  const workedRows = Object.values(worked)
    .map((p) => ({ ...p, total: names.reduce((s, n) => s + (p.by[n] || 0), 0) }))
    .sort((a, b) => b.total - a.total);

  return el('div', {},
    el('h3', { class: 'report-title' }, `Engineer KPIs — ${data.period.label}`),
    el('div', { class: 'report-grid' },
      el('section', { class: 'panel' },
        charts.groupedBars(names, [
          { label: 'Planned to date', values: names.map((n) => per[n].planned_to_date_mm) },
          { label: 'Actual', values: names.map((n) => per[n].actual_mm) },
          { label: 'Earned', values: names.map((n) => per[n].earned_mm) },
        ], { title: 'Planned, actual and earned', note: 'man-months' })),
      el('section', { class: 'panel' },
        charts.groupedBars(names, [
          { label: 'Actual MM', values: names.map((n) => per[n].actual_mm) },
        ], {
          title: 'Effort against capacity',
          note: 'the dashed line is capacity to date',
          target: Math.max(...names.map((n) => per[n].capacity_to_date_mm || 0)),
        }))),

    el('section', { class: 'panel' },
      el('h3', {}, 'KPIs by engineer'),
      kpiTable(data, rows, { scores: true })),

    el('section', { class: 'panel' },
      el('h3', {}, 'Who worked on what'),
      el('p', { class: 'muted' }, 'Actual MM booked in the period.'),
      table(['Project', 'Status', ...names, 'Total'],
        workedRows.map((p) => ({
          cells: [p.number, p.status, ...names.map((n) => num(p.by[n] || 0)),
            num(p.total)],
        })), { numeric: names.map((_n, i) => i + 2).concat([names.length + 2]) })));
}

/** The KPI grid used by both Engineer KPIs and Management Review.
 *
 *  ``scores`` adds the weighted scorecard total as a closing row, so the table
 *  ends on who is ahead rather than leaving the reader to work it out.
 */
function kpiTable(data, rows, { scores = false } = {}) {
  const names = data.engineers;
  const per = data.per_engineer;
  const body = rows.map(([label, key, format, toneOf]) => ({
    cells: [label,
      ...names.map((n) => (toneOf
        ? toned(per[n][key], toneOf, format)
        : format(per[n][key]))),
      (toneOf ? toned(teamValue(data, key), toneOf, format)
        : format(teamValue(data, key)))],
  }));

  if (scores) {
    const totals = (data.scorecard && data.scorecard.totals) || {};
    const best = Math.max(...names.map((n) => totals[n] || 0));
    body.push({
      __class: 'total-row',
      cells: ['Weighted score (out of 100)',
        ...names.map((n) => el('span', {
          class: `v-${tone.score(totals[n])}`,
          title: (totals[n] || 0) >= best ? 'best in the team' : '',
        }, `${num(totals[n], 1)}${(totals[n] || 0) >= best ? ' \u2605' : ''}`)),
        '—'],
    });
  }
  return table(['KPI', ...names, 'Team'], body,
    { numeric: names.map((_n, i) => i + 1).concat([names.length + 1]) });
}

function teamValue(data, key) {
  const per = data.per_engineer;
  const names = data.engineers;
  const sum = (k) => names.reduce((a, n) => a + (per[n][k] || 0), 0);
  if (['utilisation', 'plan_adherence'].includes(key)) {
    return key === 'utilisation'
      ? data.team.utilisation : data.team.plan_adherence;
  }
  if (key === 'cpi') return data.team.cpi;
  if (key === 'type_weighted_cpi') {
    return sum('actual_mm') ? sum('type_weighted_earned_mm') / sum('actual_mm') : null;
  }
  if (key === 'share_of_team_time') return 1;
  if (key === 'projects_worked') {
    return new Set(names.flatMap((n) => per[n].projects.map((p) => p.number))).size;
  }
  if (key === 'average_mm_per_project') {
    const projects = new Set(names.flatMap((n) => per[n].projects.map((p) => p.number))).size;
    return projects ? sum('actual_mm') / projects : null;
  }
  return sum(key);
}

/* -- Team Member -------------------------------------------------------- */

function renderTeamMember(data) {
  const names = data.engineers;
  const chosen = names.includes(state.reportMember) ? state.reportMember : names[0];
  const person = data.per_engineer[chosen];
  const quarters = data.quarterly;

  return el('div', {},
    el('div', { class: 'report-head' },
      el('h3', { class: 'report-title' }, `${chosen} — ${data.period.label}`),
      el('div', { class: 'subtabs no-print' }, names.map((name) =>
        el('button', {
          class: `subtab ${name === chosen ? 'is-active' : ''}`, type: 'button',
          onclick: () => { state.reportMember = name; renderReports(); },
        }, name)))),

    kpiCards([
      ['Actual MM', num(person.actual_mm), `${person.projects_worked} project(s) worked`],
      ['Earned MM', num(person.earned_mm), 'value delivered'],
      ['Utilisation', fmt.pct(person.utilisation),
        `of ${num(person.capacity_to_date_mm)} MM capacity`,
        tone.utilisation(person.utilisation)],
      ['Efficiency (CPI)', fmt.ratio(person.cpi), 'earned ÷ actual',
        tone.cpi(person.cpi)],
      ['Plan adherence', fmt.pct(person.plan_adherence),
        `vs ${num(person.planned_to_date_mm)} MM planned`,
        tone.target(person.plan_adherence)],
      ['Remaining on hand', num(person.remaining_mm), 'still allocated'],
    ]),

    el('div', { class: 'report-grid' },
      el('section', { class: 'panel' },
        charts.donut(person.projects.map((p) => ({ label: p.number, value: p.actual_mm })), {
          title: `Where ${chosen}'s time went`, note: 'actual MM by project', unit: 'MM',
        })),
      el('section', { class: 'panel' },
        charts.stackedColumns(quarters.map((q) => q.label),
          names.map((name) => ({
            label: name, color: engineerColor(name),
            values: quarters.map((q) => q[name]),
          })),
          { title: 'Team effort by quarter', note: 'actual MM booked' }))),

    el('section', { class: 'panel' },
      el('h3', {}, `Projects ${chosen} worked on`),
      person.projects.length
        ? table(['Project', 'Name', 'Status', 'Actual MM', 'Share of their time'],
            person.projects.map((p) => ({
              cells: [p.number, { node: el('span', {}, p.name), wide: true }, p.status,
                num(p.actual_mm),
                fmt.pct(person.actual_mm ? p.actual_mm / person.actual_mm : null)],
            })), { numeric: [3, 4] })
        : el('div', { class: 'empty' }, `No hours booked by ${chosen} in this period.`)));
}

/* -- Scorecard ---------------------------------------------------------- */

function renderScorecard(data) {
  const board = data.scorecard;
  const names = data.engineers;
  const medal = ['🥇', '🥈', '🥉'];

  return el('div', {},
    el('h3', { class: 'report-title' }, `Team scorecard — ${data.period.label}`),
    el('p', { class: 'muted' },
      'A weighted ranking. "Higher is better" factors score against the best '
      + 'performer; target factors score 100 on target and fall away either side.'),

    el('div', { class: 'report-grid' },
      el('section', { class: 'panel' },
        charts.scoreBars(board.ranking.map((r) => ({
          label: r.engineer, value: r.score, color: engineerColor(r.engineer),
        })), { title: 'Weighted score', note: 'out of 100' })),
      el('section', { class: 'panel' },
        charts.groupedBars(names, board.factors.map((f) => ({
          label: f.factor.replace(/\s*\(.*\)/, ''),
          values: names.map((n) => f.scores[n]),
        })).slice(0, 3), { title: 'Top-weighted factors', note: 'normalised score', unit: '' }))),

    el('section', { class: 'panel' },
      el('h3', {}, 'Ranking'),
      table(['Rank', 'Engineer', 'Weighted score', 'Strongest factor', 'Weakest factor'],
        board.ranking.map((r) => ({
          cells: [`${medal[r.rank - 1] || ''} ${r.rank}`, r.engineer,
            toned(r.score, tone.score, (v) => num(v, 1)),
            { node: el('span', {}, r.strongest), wide: true },
            { node: el('span', {}, r.weakest), wide: true }],
        })), { numeric: [0, 2] })),

    el('section', { class: 'panel' },
      el('h3', {}, 'How the score is made up'),
      table(['Factor', 'Weight', 'Scored', ...names.map((n) => `${n} value`),
             ...names.map((n) => `${n} score`)],
        board.factors.map((f) => ({
          cells: [f.factor, fmt.pct0(f.weight),
            f.direction === 'higher' ? 'vs best' : `target ${f.target}`,
            ...names.map((n) => num(f.values[n])),
            ...names.map((n) => num(f.scores[n], 1))],
        })), { numeric: [1, ...names.map((_n, i) => i + 3),
                         ...names.map((_n, i) => i + 3 + names.length)] })));
}

/* -- Management Review -------------------------------------------------- */

function renderReview(data) {
  const t = data.team;
  const names = data.engineers;
  const per = data.per_engineer;
  const mix = data.delivery_mix;
  const issues = data.issues || [];

  return el('div', {},
    el('h3', { class: 'report-title' }, `Management review — ${data.period.label}`),
    kpiCards([
      ['Planned MM', num(t.planned_mm), 'what we said we would burn'],
      ['Actual MM', num(t.actual_mm), 'what we actually burned'],
      ['Earned MM', num(t.earned_mm), 'value delivered'],
      ['Profit / (loss)', num(t.profit_mm), 'earned − actual', tone.amount(t.profit_mm)],
      ['Utilisation', fmt.pct(t.utilisation), 'actual vs capacity to date',
        tone.utilisation(t.utilisation)],
      ['Plan adherence', fmt.pct(t.plan_adherence), 'actual vs planned to date',
        tone.target(t.plan_adherence)],
    ]),

    el('div', { class: 'report-grid' },
      el('section', { class: 'panel' },
        charts.donut(names.map((n) => ({
          label: n, value: per[n].actual_mm, color: engineerColor(n) })), {
          title: 'Share of team time booked', note: 'actual MM by engineer', unit: 'MM',
        })),
      el('section', { class: 'panel' },
        charts.groupedBars(names, [
          { label: 'Actual MM', values: names.map((n) => per[n].actual_mm) },
          { label: 'Earned MM', values: names.map((n) => per[n].earned_mm) },
        ], { title: 'Effort against value delivered', note: 'man-months' }))),

    el('section', { class: 'panel' },
      el('h3', {}, 'Team KPIs'),
      kpiTable(data, [
        ['Actual MM booked', 'actual_mm', num, null],
        ['Planned MM to date', 'planned_to_date_mm', num, null],
        ['Earned MM', 'earned_mm', num, null],
        ['Profit / (loss) MM', 'profit_mm', num, tone.amount],
        ['Utilisation', 'utilisation', fmt.pct, tone.utilisation],
        ['Plan adherence', 'plan_adherence', fmt.pct, tone.target],
        ['Type-weighted CPI', 'type_weighted_cpi', fmt.ratio, tone.cpi],
        ['Average type factor', 'average_type_factor', (v) => num(v, 2), null],
        ['Remaining on hand', 'remaining_mm', num, null],
      ], { scores: true })),

    el('section', { class: 'panel' },
      el('h3', {}, 'Delivery mix'),
      el('p', { class: 'muted' },
        `Where the delivered hours came from over ${data.period.label.toLowerCase()}. `
        + 'Support figures are the plan totals from the Support Plan sheet, which '
        + 'the workbook does not date, so they are not cut to the period.'),
      table(['Source', 'Hours', 'Man-months', 'Share'],
        mix.map((row) => ({
          cells: [row.source, fmt.hours(row.hours), num(row.man_months),
            fmt.pct(row.share)],
        })), { numeric: [1, 2, 3] })),

    el('section', { class: 'panel' },
      el('h3', {}, 'Register health'),
      issues.length
        ? el('div', {}, issues.map((issue) => el('div', {
            class: `msg msg-${issue.level === 'error' ? 'bad' : issue.level === 'warning' ? 'warn' : 'info'}`,
          }, el('strong', {}, `${issue.where}: `), issue.message)))
        : el('div', { class: 'msg msg-ok' },
            'Every project accounts for 100% of its scope and every deliverable '
            + 'splits 100% between the team.')));
}

/* ---------------------------------------------------------------- team */

state.team = null;

async function loadTeam() {
  const [team, access] = await Promise.all([
    api('/api/team'),
    api('/api/team/access').catch(() => ({ members: [] })),
  ]);
  state.team = team;
  state.access = access;
  renderTeam();
}

function renderTeam() {
  const data = state.team;
  if (!data) return;
  const years = data.years || [];
  const room = data.max_engineers - data.engineers.length;

  $('#btn-add-engineer').disabled = room <= 0;
  $('#btn-add-engineer').title = room > 0 ? ''
    : `A unit can hold ${data.max_engineers} engineers.`;

  setChildren($('#team-body'), 
    el('div', { class: 'msg msg-info' },
      'Adding someone gives them a timesheet sheet of their own, a place in the '
      + 'stack that builds Timesheet Raw, a column for their share of every '
      + 'deliverable, and a row in the availability table. '
      + `Room for ${room} more.`),

    el('div', { class: 'table-wrap' }, el('table', {},
      el('thead', {}, el('tr', {},
        ['#', 'Engineer', 'Timesheet name pattern', 'Hours / month',
         ...years.map(String), 'Timesheet rows', 'Their sign-in', ''].map((h, i) =>
          el('th', { class: i === 0 || (i >= 3 && i < years.length + 5) ? 'num' : '' }, h)))),
      el('tbody', {}, data.engineers.map(
        (person, position) => engineerRow(person, position, years))))),

    el('p', { class: 'muted' },
      'A sign-in lets that person see their own workload, projects, hours and '
      + 'tasks — and nothing else in the unit. They cannot change anything.'));
}

function engineerRow(person, position, years) {
  const actions = el('div', { class: 'row-actions' },
    el('button', {
      class: 'btn btn-sm', type: 'button',
      onclick: () => openEngineerModal(person),
    }, 'Edit'),
    el('button', {
      class: 'btn btn-sm btn-danger', type: 'button',
      onclick: () => removeEngineer(person),
    }, 'Remove'));

  return el('tr', {},
    el('td', { class: 'num muted', title: `slot ${person.slot}` }, position + 1),
    el('td', {}, el('span', { class: 'eng-name' },
      el('span', {
        class: 'swatch',
        style: `background:var(--series-${(person.slot % 6) + 1})`,
      }),
      el('b', {}, person.short_name))),
    el('td', { class: 'code' }, person.pattern),
    el('td', { class: 'num' }, fmt.int(person.available_hours)),
    ...years.map((year) => el('td', { class: 'num' },
      fmt.pct0((person.availability || {})[year]))),
    el('td', { class: 'num' },
      el('span', {}, fmt.int(person.rows)),
      el('span', { class: 'slot-note' }, ` · ${person.sheet || 'no sheet'}`)),
    el('td', {}, accessCell(person)),
    el('td', {}, actions));
}

/** Who, if anyone, signs in as this engineer. */
function accessCell(person) {
  const granted = ((state.access || {}).members || []).find(
    (m) => m.engineer === person.short_name);
  if (!granted) {
    return el('button', {
      class: 'btn btn-sm', type: 'button',
      onclick: () => openAccessModal(person),
    }, 'Give access');
  }
  return el('div', { class: 'who' },
    el('span', { class: 'who-chip', title: `signs in as ${granted.username}` },
      granted.display_name || granted.username),
    el('button', {
      class: 'btn btn-sm btn-ghost', type: 'button', title: 'Take the access away',
      onclick: () => revokeAccess(person, granted),
    }, '✕'));
}

function openAccessModal(person) {
  openModal(`Give ${person.short_name} a sign-in`, [
    { name: 'username', label: 'Username', full: true,
      hint: 'what they type to sign in — letters, digits, dot, dash, underscore' },
    { name: 'display_name', label: 'Their name', full: true },
    { name: 'password', label: 'Password', type: 'password', full: true,
      hint: 'leave blank and one is generated for you' },
  ], async () => {
    const body = { ...modalValues(), engineer: person.short_name };
    const result = await api('/api/team/access', { method: 'POST', body });
    closeModal();
    if (result.password) {
      window.alert(`${person.short_name} can now sign in.\n\n`
        + `Username: ${result.user.username}\nPassword: ${result.password}\n\n`
        + 'Write it down now — it cannot be read back. They see only their own '
        + 'figures, and can change nothing.');
    } else {
      toast(`${result.user.username} now signs in as ${person.short_name}.`, 'ok');
    }
    await loadTeam();
  }, {
    username: person.short_name.toLowerCase().replace(/[^a-z0-9._-]/g, ''),
    display_name: person.short_name,
  });
}

async function revokeAccess(person, granted) {
  if (!window.confirm(
    `Take away ${granted.username}'s sign-in for ${person.short_name}?\n\n`
    + 'The account stays, but it can no longer see this unit.')) return;
  try {
    await api(`/api/team/access/${granted.user_id}`, { method: 'DELETE' });
    toast('Access taken away.', 'ok');
    await loadTeam();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

function openEngineerModal(person) {
  const years = state.team.years || [];
  const editing = Boolean(person);
  const fields = [
    { name: 'short_name', label: 'Short name',
      hint: 'also names their timesheet sheet' },
    { name: 'pattern', label: 'Timesheet name pattern',
      hint: 'matched against FullName in the export, e.g. *Nadia*' },
    { name: 'available_hours', label: 'Available hours per month',
      type: 'number', step: '1', min: '1' },
    ...years.map((year) => ({
      name: `availability_${year}`, label: `Availability ${year} %`,
      type: 'number', step: '5', min: '0', max: '200',
    })),
  ];
  const values = editing ? {
    short_name: person.short_name, pattern: person.pattern,
    available_hours: person.available_hours,
    ...Object.fromEntries(years.map((y) => [
      `availability_${y}`, toPercent((person.availability || {})[y])])),
  } : {
    available_hours: 185,
    ...Object.fromEntries(years.map((y) => [`availability_${y}`, 100])),
  };

  openModal(editing ? `Edit ${person.short_name}` : 'Add engineer', fields,
    async () => {
      const raw = modalValues();
      const body = {
        short_name: raw.short_name, pattern: raw.pattern,
        available_hours: raw.available_hours,
        availability: Object.fromEntries(years.map((y) => [
          y, fromPercent(raw[`availability_${y}`])])),
      };
      const result = editing
        ? await api(`/api/team/${encodeURIComponent(person.short_name)}`,
            { method: 'PUT', body })
        : await api('/api/team', { method: 'POST', body });
      markSaved(result.save);
      toast(editing
        ? `${result.engineer} updated.`
        : `${result.engineer} added, with ${result.sheet}.`, 'ok');
      state.reportMember = null;
      await refreshAll();
      await loadTeam();
    }, values);
}

async function removeEngineer(person) {
  if (!window.confirm(
    `Remove ${person.short_name} from this unit?\n\n`
    + `Their ${person.sheet} sheet goes with them, along with their column of `
    + `every deliverable's split (${fmt.int(person.rows)} timesheet rows).\n\n`
    + 'A backup of the workbook is taken first.')) return;
  try {
    const result = await api(`/api/team/${encodeURIComponent(person.short_name)}`,
      { method: 'DELETE' });
    markSaved(result.save);
    toast(`${result.engineer} removed (${result.deliverables_cleared} `
      + 'deliverable split(s) cleared).', 'ok');
    state.reportMember = null;
    await refreshAll();
    await loadTeam();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

/* --------------------------------------------------------------- tasks */
/*
 * The one tab that stands apart. Nothing here is read by the workbook: no
 * actual MM, no progress, no CPI. It is the plan — what has to be done, who
 * shares it, and whether it fits in the hours the days actually hold.
 */

async function loadTasks() {
  state.tasks = await api('/api/tasks');
  renderTasks();
}

function renderTasks() {
  const data = state.tasks;
  if (!data) return;

  fillFilter($('#task-engineer'), 'Everyone',
    data.engineers.map((name) => ({ value: name, label: name })));
  fillFilter($('#task-project'), 'Every project',
    data.projects.map((p) => ({ value: p.number, label: `${p.number} — ${p.name}` })));
  fillFilter($('#task-status-filter'), 'Any status',
    data.statuses.map((name) => ({ value: name, label: name })));

  renderTaskLoad(data);
  renderTaskTable(data);
}

/** Keep a filter's chosen value across a re-render. */
function fillFilter(select, allLabel, options) {
  const chosen = select.value;
  setChildren(select, 
    el('option', { value: 'all' }, allLabel),
    ...options.map((o) => el('option', { value: o.value }, o.label)));
  select.value = options.some((o) => o.value === chosen) ? chosen : 'all';
}

/** Who is overloaded, against the hours a working day actually holds. */
function renderTaskLoad(data) {
  const load = data.load;
  const settings = data.settings;
  const window_ = `${fmt.date(load.from)} → ${fmt.date(load.to)}`;
  const verdictTone = { overloaded: 'bad', 'on plan': 'ok', underloaded: 'warn' };

  setChildren($('#task-load'), el('section', { class: 'panel' },
    el('h3', {}, 'Who is loaded, and who is not'),
    el('p', { class: 'muted' },
      `Open work due in the next ${load.weeks} week(s) — ${window_} — against `
      + `${fmt.int(load.working_days)} working days of `
      + `${num(load.hours_per_day)} hours (${settings.day_start}–${settings.day_end}), `
      + `so ${fmt.hours(load.capacity_hours)} hours each. A shared task counts `
      + 'only its share against each person. Overdue work is counted too; '
      + 'anything past the window is not.'),
    el('div', { class: 'load-grid' },
      data.engineers.map((name) => {
        const e = load.per_engineer[name] || {};
        const pct = Math.round((e.load || 0) * 100);
        const tone_ = verdictTone[e.verdict] || '';
        return el('div', { class: 'load-card' },
          el('div', { class: 'load-head' },
            el('span', { class: 'eng-name' },
              el('span', { class: 'swatch', style: `background:${engineerColor(name)}` }),
              name),
            el('span', { class: `pill pill-${tone_ || 'info'}` }, e.verdict || '—')),
          el('span', { class: `progress-track ${tone_}`,
            style: 'width:100%;height:9px' },
            el('span', { style: `width:${Math.min(100, pct)}%` })),
          el('div', { class: 'load-figures' },
            el('span', {}, el('b', { class: tone_ ? `v-${tone_}` : '' },
              `${pct}%`), ' of capacity'),
            el('span', {}, `${fmt.hours(e.hours + e.overdue_hours)} h · `
              + `${num(e.days)} day(s)`)),
          el('div', { class: 'load-detail' },
            e.overtime_hours
              ? el('div', { class: 'v-bad' },
                  `${fmt.hours(e.overtime_hours)} h beyond the working day — `
                  + 'overtime, or work that has to move')
              : el('div', { class: 'muted' },
                  `${fmt.hours(e.spare_hours)} h still free`),
            el('div', { class: 'muted' },
              `${fmt.int(e.tasks)} due · ${fmt.int(e.overdue_tasks)} overdue`
              + ` · ${fmt.int(e.undated_tasks)} with no date`
              + ` · ${fmt.hours(e.later_hours)} h later on`),
            e.actual_hours
              ? el('div', { class: 'muted' },
                  `${fmt.hours(e.actual_hours)} h actually spent so far`)
              : null));
      })),
    load.unassigned.tasks
      ? el('div', { class: 'msg msg-warn' },
          `${fmt.int(load.unassigned.tasks)} task(s) worth `
          + `${fmt.hours(load.unassigned.hours)} h belong to nobody yet.`)
      : null));
}

function taskFilters() {
  return {
    engineer: $('#task-engineer').value,
    project: $('#task-project').value,
    status: $('#task-status-filter').value,
    search: $('#task-search').value.trim().toLowerCase(),
    showDone: $('#task-show-done').checked,
  };
}

function renderTaskTable(data) {
  const f = taskFilters();
  const rows = data.tasks.filter((t) => {
    if (!f.showDone && t.done) return false;
    if (f.engineer !== 'all' && !t.assignees.includes(f.engineer)) return false;
    if (f.project !== 'all' && t.project_number !== f.project) return false;
    if (f.status !== 'all' && t.status !== f.status) return false;
    if (!f.search) return true;
    return `${t.name} ${t.definition} ${t.deliverable_name} ${t.project_number}`
      .toLowerCase().includes(f.search);
  }).sort(taskOrder);

  const hidden = data.tasks.filter((t) => t.done).length;
  const statusPillFor = (status) => (
    status === 'Done' ? 'pill-ok'
      : status === 'Blocked' ? 'pill-bad'
        : status === 'In progress' ? 'pill-warn' : 'pill-info');

  setChildren($('#task-body'), 
    el('p', { class: 'muted' },
      `${fmt.int(rows.length)} task(s) shown`
      + (f.showDone || !hidden ? '' : ` · ${fmt.int(hidden)} done and hidden`)),
    el('table', { class: 'tasks-table' },
      el('thead', {}, el('tr', {},
        ['Task', 'For', 'Assigned to', 'Required (h)', 'Actual (h)', 'Due',
          'Status', '']
          .map((h, i) => el('th', { class: i >= 3 && i <= 4 ? 'num' : '' }, h)))),
      el('tbody', {}, rows.length === 0
        ? el('tr', {}, el('td', { colspan: 8 },
            el('div', { class: 'empty' },
              data.tasks.length ? 'No task matches these filters.'
                : 'No tasks yet. Add one, or let a deliverable date fill in its week.')))
        : rows.map((task) => el('tr', {
            class: `clickable ${task.done ? 'row-done' : ''}`,
            onclick: () => openTaskModal(task),
          },
          el('td', {},
            el('div', { class: 'task-name' }, task.name,
              task.kind !== 'Task'
                ? el('span', { class: 'pill pill-info tag' }, task.kind) : null),
            task.definition
              ? el('div', { class: 'muted small' }, task.definition) : null),
          el('td', { class: 'wide' },
            task.project_number
              ? el('div', { class: 'code' }, task.project_number) : null,
            task.deliverable_name
              ? el('div', { class: 'muted small' }, task.deliverable_name) : null),
          el('td', {},
            el('div', { class: 'who' }, task.assignees.length
              ? task.assignees.map((name) => el('span', { class: 'who-chip' },
                  el('span', { class: 'swatch', style: `background:${engineerColor(name)}` }),
                  name))
              : el('span', { class: 'pill pill-warn' }, 'nobody')),
            task.shared
              ? el('div', { class: 'muted small' },
                  `shared — ${num(task.hours_each)} h each`)
              : null),
          el('td', { class: 'num' }, task.required_hours === null
            ? '—' : fmt.hours(task.required_hours)),
          // Actual against required only means something once the work is
          // finished; until then it is simply how far along it is.
          el('td', { class: 'num' }, task.actual_hours === null ? '—'
            : (task.done && task.required_hours
              ? toned(task.actual_hours - task.required_hours,
                (v) => (v > 0.01 ? 'bad' : 'ok'),
                () => fmt.hours(task.actual_hours))
              : fmt.hours(task.actual_hours))),
          el('td', {}, dueCell(task)),
          el('td', {}, el('span', { class: `pill ${statusPillFor(task.status)}` },
            task.status)),
          el('td', { class: 'row-actions' },
            el('button', {
              class: 'btn btn-sm', type: 'button',
              onclick: (event) => { event.stopPropagation(); toggleTaskDone(task); },
            }, task.done ? 'Reopen' : 'Done'),
            el('button', {
              class: 'btn btn-sm btn-ghost', type: 'button',
              onclick: (event) => { event.stopPropagation(); deleteTask(task); },
            }, '✕'))))))); 
}

/** Overdue first, then by date, then the undated. */
function taskOrder(a, b) {
  if (a.done !== b.done) return a.done ? 1 : -1;
  if (!a.due && !b.due) return a.id - b.id;
  if (!a.due) return 1;
  if (!b.due) return -1;
  return a.due < b.due ? -1 : a.due > b.due ? 1 : a.id - b.id;
}

function dueCell(task) {
  if (!task.due) return el('span', { class: 'muted' }, 'no date');
  const today = new Date().toISOString().slice(0, 10);
  const late = !task.done && task.due < today;
  return el('span', { class: late ? 'v-bad' : '' }, fmt.date(task.due),
    late ? el('span', { class: 'muted small' }, ' overdue') : null);
}

/* -- editing ----------------------------------------------------------- */

function taskFields(data, task) {
  const deliverables = data.deliverables.map((d) => ({
    value: String(d.row),
    label: `${d.project_number} — ${d.name}${d.date ? ` (${d.date})` : ''}`,
  }));
  return [
    { name: 'name', label: 'Task', full: true },
    { name: 'definition', label: 'What it is', type: 'textarea', full: true,
      hint: 'the definition of the task' },
    { name: 'assignees', label: 'Assigned to', type: 'checks', full: true,
      options: data.engineers,
      hint: 'more than one shares the hours between them' },
    { name: 'required_hours', label: 'Required hours', type: 'number', step: '0.5',
      min: '0' },
    { name: 'actual_hours', label: 'Actual hours taken', type: 'number', step: '0.5',
      min: '0', hint: 'typed here, not from the timesheet' },
    { name: 'project_number', label: 'Project', type: 'select',
      options: [{ value: '', label: '—' },
        ...data.projects.map((p) => ({ value: p.number, label: p.number }))] },
    { name: 'deliverable_row', label: 'Feeds deliverable', type: 'select',
      options: [{ value: '', label: '—' }, ...deliverables] },
    { name: 'start', label: 'Start', type: 'date' },
    { name: 'due', label: 'Due', type: 'date' },
    { name: 'status', label: 'Status', type: 'select', options: data.statuses },
    { name: 'kind', label: 'Kind', type: 'select', options: data.kinds },
    { name: 'notes', label: 'Notes', type: 'textarea', full: true },
  ];
}

function openTaskModal(task) {
  const data = state.tasks;
  const values = task ? {
    ...task,
    deliverable_row: task.deliverable_row === null ? '' : String(task.deliverable_row),
    project_number: task.project_number || '',
  } : { status: data.statuses[0], kind: data.kinds[0] };

  openModal(task ? `Task ${task.id}` : 'New task', taskFields(data, task),
    async () => {
      const body = modalValues();
      const chosen = data.deliverables.find(
        (d) => String(d.row) === String(body.deliverable_row));
      body.deliverable_name = chosen ? chosen.name : '';
      if (chosen && !body.project_number) body.project_number = chosen.project_number;
      const path = task ? `/api/tasks/${task.id}` : '/api/tasks';
      const result = await api(path, { method: task ? 'PUT' : 'POST', body });
      markSaved(result.save);
      closeModal();
      toast(task ? 'Task updated.' : 'Task added.', 'ok');
      await loadTasks();
    }, values);
}

async function toggleTaskDone(task) {
  try {
    const result = await api(`/api/tasks/${task.id}`, {
      method: 'PUT',
      body: { ...task, status: task.done ? 'In progress' : 'Done' },
    });
    markSaved(result.save);
    await loadTasks();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

async function deleteTask(task) {
  const series = task.series
    && window.confirm(
      `${task.name}\n\nThis task is part of a generated series `
      + `(${task.series}). Delete the whole series?\n\n`
      + 'Cancel deletes only this one.');
  try {
    const result = series
      ? await api('/api/tasks/series/delete',
        { method: 'POST', body: { series: task.series } })
      : await api(`/api/tasks/${task.id}`, { method: 'DELETE' });
    markSaved(result.save);
    toast(series ? `${result.deleted} task(s) deleted.` : 'Task deleted.', 'ok');
    await loadTasks();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

/* -- the things nobody should type fifty times ------------------------- */

function openWorkingDayModal() {
  const data = state.tasks;
  const settings = data.settings;
  openModal('The working day', [
    { name: 'day_start', label: 'Day starts', type: 'time' },
    { name: 'day_end', label: 'Day ends', type: 'time',
      hint: 'anything past this is overtime, so it is not counted as capacity' },
    { name: 'work_days', label: 'Working days', type: 'checks', full: true,
      options: data.weekdays.map((name, index) => ({ value: String(index), label: name })) },
    { name: 'horizon_weeks', label: 'Load window (weeks)', type: 'number', min: '1',
      max: '52' },
    { name: 'submission_lead_days', label: 'Run-up to a deliverable (days)',
      type: 'number', min: '1', max: '60' },
    { name: 'submission_hours_per_day', label: 'Submission hours a day',
      type: 'number', step: '0.5', min: '0' },
    { name: 'meeting_hours', label: 'Weekly meeting hours', type: 'number',
      step: '0.5', min: '0' },
    { name: 'meeting_weeks', label: 'Meeting series (weeks)', type: 'number',
      min: '1', max: '104' },
  ], async () => {
    const body = modalValues();
    body.work_days = (body.work_days || []).map(Number);
    const result = await api('/api/tasks/settings', { method: 'PUT', body });
    markSaved(result.save);
    closeModal();
    toast('Working day saved.', 'ok');
    await loadTasks();
  }, { ...settings, work_days: (settings.work_days || []).map(String) });
}

function openSubmissionModal() {
  const data = state.tasks;
  const dated = data.deliverables.filter((d) => d.date);
  openModal('Submission tasks', [
    { name: 'deliverable_row', label: 'Deliverable', type: 'select', full: true,
      hint: 'or leave on every deliverable still ahead',
      options: [{ value: '', label: 'Every deliverable still ahead' },
        ...dated.map((d) => ({
          value: String(d.row), label: `${d.project_number} — ${d.name} (${d.date})`,
        }))] },
    { name: 'include_past', label: 'Include dates already past', type: 'checks',
      full: true, options: [{ value: 'yes', label: 'Yes, generate for past dates too' }] },
  ], async () => {
    const body = modalValues();
    body.include_past = (body.include_past || []).length > 0;
    const result = await api('/api/tasks/generate/submissions',
      { method: 'POST', body });
    markSaved(result.save);
    closeModal();
    toast(result.added
      ? `${result.added} task(s) added across ${result.deliverables} deliverable(s).`
      : (result.past_deliverables
        ? `Nothing to add — every dated deliverable is already past `
          + `(${result.past_deliverables} of them). Tick the box to include those.`
        : 'Nothing to add — every dated deliverable already has its week.'),
    result.added ? 'ok' : 'warn');
    await loadTasks();
  }, { deliverable_row: '' });
}

function openMeetingModal() {
  const data = state.tasks;
  const settings = data.settings;
  const monday = new Date();
  openModal('Weekly meeting', [
    { name: 'project_number', label: 'For', type: 'select', full: true,
      options: [{ value: '', label: 'The unit as a whole' },
        ...data.projects.map((p) => ({
          value: p.number, label: `${p.number} — ${p.name}`,
        }))] },
    { name: 'weekday', label: 'Every', type: 'select',
      options: data.weekdays.map((name, index) => ({
        value: String(index), label: name,
      })) },
    { name: 'hours', label: 'Hours', type: 'number', step: '0.5', min: '0' },
    { name: 'weeks', label: 'For how many weeks', type: 'number', min: '1',
      max: '104' },
    { name: 'start', label: 'Starting', type: 'date',
      hint: 'the series starts on the first such day from here' },
  ], async () => {
    const result = await api('/api/tasks/generate/meetings',
      { method: 'POST', body: modalValues() });
    markSaved(result.save);
    closeModal();
    toast(result.added
      ? `${result.added} weekly meeting(s) added from ${fmt.date(result.from)}.`
      : 'That series is already in the list.', result.added ? 'ok' : 'warn');
    await loadTasks();
  }, {
    project_number: '',
    weekday: String(settings.meeting_weekday),
    hours: settings.meeting_hours,
    weeks: settings.meeting_weeks,
    start: monday.toISOString().slice(0, 10),
  });
}
