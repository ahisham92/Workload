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
  browseFolder: null,
  detail: null,          // the project currently open, with its deliverables
  referenceDraft: null,
};

/* ---------------------------------------------------------------- helpers */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

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

function fileRow(file, onPick, icon = '\u{1F4D7}') {
  return el('button', { class: 'file-row', type: 'button', onclick: onPick },
    el('span', { class: 'icon' }, icon),
    el('span', { class: 'who' },
      el('b', {}, file.name),
      el('span', { title: file.folder }, file.folder)),
    el('span', { class: 'meta' },
      file.size_mb ? `${file.size_mb} MB · ${String(file.modified).slice(0, 10)}` : ''));
}

async function renderChooser(folder) {
  const query = folder ? `?folder=${encodeURIComponent(folder)}` : '';
  const data = await api(`/api/units${query}`);
  state.browseFolder = folder || data.cwd;

  const units = data.units || [];
  $('#unit-list').replaceChildren(
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
          el('span', { class: 'muted', title: unit.workbook },
            unit.exists ? `${unit.file_name} · ${unit.folder}`
              : 'workbook not found at this path'),
          el('span', { class: 'muted' },
            unit.opened ? `last opened ${String(unit.opened).slice(0, 10)}` : '')),
        el('button', {
          class: 'btn btn-ghost btn-sm unit-forget', type: 'button',
          title: 'Remove this unit from the list. The workbook is left alone.',
          onclick: () => forgetUnit(unit),
        }, '✕'))))
      : el('p', { class: 'muted' },
          'Add one below: give it a name and point it at its workbook.'));

  if (!units.length) $('#add-unit').open = true;

  $('#chooser-suggestions').replaceChildren(
    ...(data.suggestions && data.suggestions.length
      ? [el('h3', {}, 'Spreadsheets found nearby'),
         el('div', { class: 'file-list' },
           data.suggestions.map((f) => fileRow(f, () => {
             $('#unit-path').value = f.path;
             if (!$('#unit-name').value) $('#unit-name').value = f.name.replace(/\.[^.]+$/, '');
           })))]
      : []));

  if (data.browse) {
    const b = data.browse;
    $('#chooser-browse').replaceChildren(
      el('p', { class: 'muted' }, b.folder),
      el('div', { class: 'file-list' },
        b.parent
          ? el('button', { class: 'file-row', type: 'button',
              onclick: () => renderChooser(b.parent) },
              el('span', { class: 'icon' }, '⬆'),
              el('span', { class: 'who' }, el('b', {}, 'Up one folder')))
          : null,
        b.folders.map((f) => el('button', { class: 'file-row', type: 'button',
          onclick: () => renderChooser(f.path) },
          el('span', { class: 'icon' }, '\u{1F4C1}'),
          el('span', { class: 'who' }, el('b', {}, f.name)))),
        b.files.map((f) => fileRow(f, () => { $('#unit-path').value = f.path; }))));
  }
}

function chooserError(messages) {
  $('#chooser-error').replaceChildren(
    ...messages.map((m) => el('div', { class: 'msg msg-bad' }, m)));
}

async function pickFile() {
  const button = $('#btn-pick');
  button.disabled = true;
  try {
    const result = await api('/api/units/pick', { method: 'POST' });
    if (result.cancelled) return;
    $('#unit-path').value = result.path;
    if (!$('#unit-name').value) {
      $('#unit-name').value = result.path.split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
    }
    $('#chooser-error').replaceChildren();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  } finally {
    button.disabled = false;
  }
}

async function openUnit(unit) {
  try {
    await api('/api/units/open', { method: 'POST', body: { unit_id: unit.id } });
    await enterApp();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  }
}

async function addUnit() {
  const path = $('#unit-path').value.trim();
  const name = $('#unit-name').value.trim();
  if (!path) { chooserError(['Choose a workbook first.']); return; }
  try {
    await api('/api/units/open', { method: 'POST', body: { path, name } });
    await enterApp();
  } catch (error) {
    chooserError(error.errors || [error.message]);
  }
}

async function forgetUnit(unit) {
  if (!window.confirm(
    `Remove "${unit.name}" from the list?\n\nThe workbook itself is not touched.`)) return;
  await api(`/api/units/${unit.id}`, { method: 'DELETE' });
  await renderChooser(state.browseFolder);
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
  $('#modal-backdrop').hidden = false;
  const first = form.querySelector('input, select, textarea');
  if (first) first.focus();
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
  return out;
}

function showModalErrors(errors) {
  $('#modal-errors').replaceChildren(
    el('ul', {}, errors.map((e) => el('li', {}, e))));
}

/* ------------------------------------------------------------ overview */

function renderOverview() {
  const data = state.overview;
  if (!data) return;
  const p = data.portfolio;

  const yearSelect = $('#overview-year');
  if (yearSelect.options.length === 0) {
    yearSelect.append(el('option', { value: 'all' }, 'All years'));
    for (const year of (data.available_years || []).slice().reverse()) {
      yearSelect.append(el('option', { value: year }, year));
    }
    yearSelect.value = state.year === null ? 'all' : String(state.year);
  }

  const cards = [
    ['In-hand budget', fmt.mm(p.budget_mm), `${p.in_scope_projects} active / not started`],
    ['Actual MM booked', fmt.mm(p.actual_mm),
      `${fmt.hours(p.actual_mm * data.hours_per_man_month)} hours`],
    ['Earned MM', fmt.mm(p.earned_mm), 'budget × progress'],
    ['Profit / (loss)', fmt.mm(p.profit_mm), 'earned − actual'],
    ['Efficiency (CPI)', fmt.ratio(p.cpi),
      p.cpi >= 1 ? 'earning above cost' : 'earning below cost'],
    ['Register', `${p.projects} / ${p.deliverables}`, 'projects / deliverables'],
  ];
  $('#overview-cards').replaceChildren(...cards.map(([label, value, sub]) =>
    el('div', { class: 'card' },
      el('div', { class: 'label' }, label),
      el('div', { class: 'value' }, value),
      el('div', { class: 'sub' }, sub))));

  $('#engineer-cards').replaceChildren(
    ...Object.entries(data.engineers).map(([name, e]) => engineerBlock(name, e)));

  renderDataCheck(data.data_check);
  renderIssues(data.issues || []);
}

function engineerBlock(name, e) {
  const months = e.months || [];
  const peak = Math.max(1, ...months.map((m) => m.total || 0),
    e.available_hours_per_month || 0);
  const width = Math.max(14, Math.floor(760 / Math.max(months.length, 1)));
  const bars = el('div', { class: 'bars' }, months.map((m) => {
    const over = (m.utilisation || 0) > 1;
    return el('div', {
      class: `bar ${over ? 'over' : ''}`,
      style: `flex-basis:${width}px;`
        + (m.capacity ? `--cap:${Math.min(100, Math.round((m.capacity / peak) * 100))}%` : ''),
      title: `${m.month}: ${fmt.hours(m.total)} h of ${fmt.hours(m.capacity)} `
        + `(${fmt.pct(m.utilisation)}) — ${fmt.hours(m.projects)} h projects, `
        + `${fmt.hours(m.proposals)} h proposals, ${fmt.hours(m.absence)} h absence`,
    }, el('span', { style: `height:${Math.max(2, Math.round((m.total / peak) * 100))}%` }));
  }));
  const labels = el('div', { class: 'bar-labels' }, months.map((m) => el('div', {
    style: `flex-basis:${width}px`,
  }, months.length > 24 ? m.month.slice(2, 7) : m.month.slice(5))));
  const util = e.average_utilisation;
  const pill = util === null ? 'pill-info'
    : util > 1.05 ? 'pill-bad' : util < 0.7 ? 'pill-warn' : 'pill-ok';
  return el('div', { class: 'eng' },
    el('div', { class: 'eng-head' },
      el('span', { class: 'eng-name' }, name),
      el('span', { class: `pill ${pill}` }, `${fmt.pct(util)} utilised`)),
    el('div', { class: 'muted' },
      `${fmt.hours(e.total_hours)} h total · ${fmt.hours(e.project_hours)} h on projects · `
      + `${fmt.hours(e.proposal_hours)} h proposals · ${fmt.hours(e.absence_hours)} h absence · `
      + `${fmt.hours(e.overtime_hours)} h overtime`),
    months.length
      ? el('div', { class: 'chart' }, bars, labels)
      : el('p', { class: 'muted' }, 'No hours in this period.'),
    months.length
      ? el('div', { class: 'chart-legend' },
          el('span', {}, `bar = hours booked (tallest ${fmt.hours(peak)} h)`),
          el('span', {}, 'dashed line = monthly capacity'),
          el('span', {}, 'red = over capacity'))
      : null);
}

function renderDataCheck(check) {
  const kind = check.rows === 0 ? 'msg-warn'
    : check.rows_not_matching_pattern ? 'msg-bad' : 'msg-ok';
  const unknown = check.unknown_job_numbers || [];
  $('#data-check').replaceChildren(
    el('div', { class: `msg ${kind}` }, check.verdict),
    el('dl', { class: 'kv' },
      el('dt', {}, 'Rows'), el('dd', {}, fmt.int(check.rows)),
      el('dt', {}, 'Hours'), el('dd', {}, fmt.hours(check.hours)),
      el('dt', {}, 'First date'), el('dd', {}, fmt.date(check.first_date)),
      el('dt', {}, 'Last date'), el('dd', {}, fmt.date(check.last_date)),
      ...Object.entries(check.per_engineer).flatMap(([name, e]) => [
        el('dt', {}, name),
        el('dd', {}, `${fmt.int(e.rows)} rows · ${fmt.hours(e.hours)} h · to ${fmt.date(e.last_date)}`),
      ])),
    unknown.length
      ? el('div', { class: 'msg msg-warn', style: 'margin-top:12px' },
          el('strong', {}, `${unknown.length} job number(s) charged but not in the register: `),
          unknown.slice(0, 8).map((u) => `${u.code} (${u.rows})`).join(', ')
            + (unknown.length > 8 ? `, and ${unknown.length - 8} more` : ''))
      : null);
}

function renderIssues(issues) {
  if (issues.length === 0) {
    $('#issues').replaceChildren(el('div', { class: 'msg msg-ok' },
      'Every project accounts for 100% of its scope, every deliverable splits '
      + '100% between the team, and every deliverable has a TS Phase.'));
    return;
  }
  $('#issues').replaceChildren(...issues.map((issue) => {
    const tone = issue.level === 'error' ? 'bad' : issue.level === 'warning' ? 'warn' : 'info';
    // Anything that names a project gets a way straight to it.
    const project = issue.project
      || state.projects.find((p) => issue.message.includes(p.number))?.number;
    return el('div', { class: `msg msg-${tone} msg-action` },
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

  $('#ts-cards').replaceChildren(...Object.entries(check.per_engineer).map(([name, e]) =>
    el('div', { class: 'card' },
      el('div', { class: 'label' }, `${name} — ${e.sheet}`),
      el('div', { class: 'value' }, fmt.int(e.rows)),
      el('div', { class: 'sub' },
        `rows · ${fmt.hours(e.hours)} h · ${fmt.date(e.first_date)} → ${fmt.date(e.last_date)}`),
      e.rows_not_matching_pattern
        ? el('div', { class: 'msg msg-bad', style: 'margin-top:8px' },
            `${e.rows_not_matching_pattern} row(s) belong to someone else`)
        : null)));

  const select = $('#ts-engineer');
  const chosen = select.value;
  select.replaceChildren(...Object.keys(check.per_engineer).map(
    (name) => el('option', { value: name }, name)));
  if (chosen) select.value = chosen;
}

function renderCapacity(check) {
  const cap = check.capacity;
  const target = $('#ts-capacity');
  if (!cap) { target.replaceChildren(); return; }
  const used = cap.rows_used / cap.total_capacity;
  const tone = cap.over_capacity ? 'bad' : cap.low_headroom ? 'warn' : '';
  const warnings = check.capacity_warnings || [];

  target.replaceChildren(el('div', { class: 'panel' },
    el('h3', {}, 'Room left in the workbook'),
    el('p', { class: 'muted' },
      `Every calculation reads Timesheet Raw rows 4–${cap.raw_last_row.toLocaleString()}. `
      + 'Rows past that stay on the sheet but reach nothing — and because the sheets stack '
      + `${cap.stack_order.join(' then ')}, they are ${cap.stack_order[cap.stack_order.length - 1]}'s first.`),
    el('div', { class: `meter ${tone}` },
      el('span', { style: `width:${Math.min(100, Math.round(used * 100))}%` })),
    el('p', { class: 'muted' },
      `${cap.rows_used.toLocaleString()} of ${cap.total_capacity.toLocaleString()} rows used`
      + (cap.headroom >= 0
        ? ` — ${cap.headroom.toLocaleString()} left`
        : ` — ${Math.abs(cap.headroom).toLocaleString()} rows are being ignored`)),
    ...warnings.map((w) => el('div', {
      class: `msg msg-${w.level === 'error' ? 'bad' : 'warn'}`,
    }, w.message)),
    (cap.over_capacity || cap.low_headroom)
      ? el('button', { class: 'btn btn-primary', type: 'button',
          onclick: () => extendCapacity(cap) },
          `Raise the limit to ${cap.suggested_raw_last_row.toLocaleString()} rows`)
      : null));
}

async function extendCapacity(cap) {
  const perSheetNeeded = Math.max(
    ...Object.values(cap.per_sheet).map((s) => s.rows)) + 1500;
  const source = perSheetNeeded > cap.per_sheet_capacity
    ? Math.min(cap.source_last_row + 3000, cap.suggested_raw_last_row) : null;
  if (!window.confirm(
    `Raise the limit from ${cap.raw_last_row.toLocaleString()} to `
    + `${cap.suggested_raw_last_row.toLocaleString()} rows?\n\n`
    + 'This rewrites every formula that reads the consolidated timesheet and adds '
    + 'the per-row helper formulas to match. A backup is taken first.\n\n'
    + 'Excel will take noticeably longer to recalculate afterwards. Importing with '
    + '"only rows for projects in the register" may free up enough room without this.')) return;
  try {
    toast('Rewriting formulas — this takes a few seconds…');
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
  result.replaceChildren(el('p', { class: 'muted' },
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
    result.replaceChildren(...(error.errors || [error.message]).map(
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

  $('#ts-result').replaceChildren(
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
    $('#ts-result').replaceChildren(el('div', { class: 'msg msg-ok' },
      `${result.engineer} now has ${fmt.int(result.rows)} rows. ${result.data_check.verdict}`));
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
  $('#ts-result').replaceChildren();
}

/* -------------------------------------------------------------- projects */

function statusPill(status) {
  if (status === 'Active') return 'pill-ok';
  if (status === 'Not Started') return 'pill-info';
  if (status === 'On Hold') return 'pill-warn';
  if (status === 'Cancelled') return 'pill-bad';
  return '';
}

function renderProjects() {
  const projectSelect = $('#project-filter');
  const chosen = projectSelect.value || 'all';
  projectSelect.replaceChildren(
    el('option', { value: 'all' }, `All projects (${state.projects.length})`),
    ...state.projects.map((p) => el('option', { value: p.number },
      `${p.number} — ${p.name}`)));
  projectSelect.value = state.projects.some((p) => p.number === chosen) ? chosen : 'all';

  const statusSelect = $('#project-status-filter');
  const chosenStatus = statusSelect.value || 'all';
  const statuses = (state.reference.statuses || []).filter(
    (name) => state.projects.some((p) => p.status === name));
  statusSelect.replaceChildren(
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

  $('#projects-table').replaceChildren(
    el('thead', {}, el('tr', {},
      ['#', 'Number', 'Name', 'Status', 'Budget MM', 'Progress', 'Actual MM',
       'Earned MM', 'Profit MM', 'CPI', 'Deliverables', '']
        .map((h, i) => el('th', {
          class: i === 0 || (i >= 4 && i <= 9) ? 'num' : '',
        }, h)))),
    el('tbody', {}, rows.length === 0
      ? el('tr', {}, el('td', { colspan: 12 },
          el('div', { class: 'empty' }, 'No projects match.')))
      : rows.map((project, position) => {
        const m = byNumber.get(project.number) || {};
        const cpiPill = m.cpi === null || m.cpi === undefined ? ''
          : m.cpi >= 1 ? 'pill-ok' : m.cpi >= 0.8 ? 'pill-warn' : 'pill-bad';
        return el('tr', { class: 'clickable', onclick: () => openProject(project.number) },
          el('td', { class: 'num muted', title: `Inputs row ${project.row}` }, position + 1),
          el('td', { class: 'code' }, project.number),
          el('td', { class: 'wide' }, project.name),
          el('td', {}, el('span', { class: `pill ${statusPill(project.status)}` },
            project.status || '—')),
          el('td', { class: 'num' }, fmt.mm(project.budget_mm)),
          el('td', { class: 'num' }, fmt.pct(m.progress)),
          el('td', { class: 'num' }, fmt.mm(m.actual_mm)),
          el('td', { class: 'num' }, fmt.mm(m.earned_mm)),
          el('td', { class: 'num' }, fmt.mm(m.profit_mm)),
          el('td', { class: 'num' }, cpiPill
            ? el('span', { class: `pill ${cpiPill}` }, fmt.ratio(m.cpi)) : '—'),
          el('td', {}, m.deliverables
            ? el('span', { class: `pill ${m.weight_ok ? 'pill-ok' : 'pill-bad'}` },
                m.weight_ok ? `${m.deliverables} · 100%` : `${m.deliverables} · ${fmt.pct(m.weight_total)}`)
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

  $('#project-detail').replaceChildren(
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
    note.replaceChildren(
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
      stepSelect.replaceChildren(...stepOptions(e.target.value));
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
    $('#detail-errors').replaceChildren(
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
  $('#reference-lock').replaceChildren(unlocked
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

  $('#reference-body').replaceChildren(
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
            : ''))))))));
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
    toast(`Saved ${result.project_types} types and ${result.credit_steps} steps.`, 'ok');
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
  if (!status.open) { showShell(false); await renderChooser(state.browseFolder); return; }

  const yearParam = state.year === null ? 'all' : state.year;
  const [overview, projects] = await Promise.all([
    api(`/api/overview?year=${yearParam}`),
    api('/api/projects'),
  ]);
  state.overview = overview;
  state.projects = projects.projects;
  state.projectMetrics = projects.metrics;

  $('#unit-title').textContent = status.unit ? status.unit.name : 'Workload';
  $('#workbook-path').textContent = status.workbook;
  $('#workbook-path').title = `${status.workbook} — backups in ${status.backups}`;
  markSaved({ saved: !status.unsaved_changes, pending: status.unsaved_changes });

  renderOverview();
  renderTimesheets();
  renderProjects();
  renderReference();
}

function switchView(view) {
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
    state.year = event.target.value === 'all' ? null : Number(event.target.value);
    state.overview = await api(`/api/overview?year=${event.target.value}`);
    renderOverview();
    renderTimesheets();
  });
  $('#project-search').addEventListener('input', renderProjects);
  $('#project-filter').addEventListener('change', renderProjects);
  $('#project-status-filter').addEventListener('change', renderProjects);
  $('#btn-new-project').addEventListener('click', newProject);
  $('#btn-ts-check').addEventListener('click', checkTimesheetFile);
  $('#btn-pick').addEventListener('click', pickFile);
  $('#btn-add-unit').addEventListener('click', addUnit);
  $('#unit-path').addEventListener('keydown', (e) => { if (e.key === 'Enter') addUnit(); });

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
    await renderChooser(state.browseFolder);
  });
  $('#chooser-browse-wrap').addEventListener('toggle', (event) => {
    if (event.target.open) renderChooser(state.browseFolder);
  });

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
    const status = await api('/api/status');
    state.status = status;
    if (status.open) await enterApp();
    else { showShell(false); await renderChooser(); }
  } catch (error) {
    document.body.prepend(el('div', { class: 'msg msg-bad', style: 'margin:20px' },
      `Could not start: ${error.message}`));
  }
})();
