/* Workload Input - single page front end.
 * The server owns all workbook logic; this file renders it and posts changes back.
 */
'use strict';

const state = {
  reference: null,
  status: null,
  overview: null,
  projects: [],
  projectMetrics: [],
  deliverables: [],
  deliverableMetrics: [],
  year: null,
  stagedImport: null,
  view: 'overview',
  browseFolder: null,
};

/* --------------------------------------------------------------- chooser */

function showChooser(show) {
  $('#chooser').hidden = !show;
  $('#main').hidden = show;
  $('.tabs').hidden = show;
  for (const id of ['btn-save', 'btn-reload', 'btn-change', 'save-state']) {
    $(`#${id}`).hidden = show;
  }
}

function fileRow(file, onPick) {
  return el('button', { class: 'file-row', type: 'button', onclick: onPick },
    el('span', { class: 'icon' }, '\u{1F4D7}'),
    el('span', { class: 'who' },
      el('b', {}, file.name),
      el('span', { title: file.folder }, file.folder)),
    el('span', { class: 'meta' }, `${file.size_mb} MB · ${file.modified.slice(0, 10)}`));
}

async function renderChooser(folder) {
  const query = folder ? `?folder=${encodeURIComponent(folder)}` : '';
  const data = await api(`/api/workbooks${query}`);
  state.browseFolder = folder || data.cwd;

  $('#chooser-recent').replaceChildren(
    ...(data.recent.length
      ? [el('h3', {}, 'Recently opened'),
         el('div', { class: 'file-list' },
           data.recent.map((f) => fileRow(f, () => openWorkbook(f.path))))]
      : []));

  $('#chooser-suggestions').replaceChildren(
    ...(data.suggestions.length
      ? [el('h3', {}, 'Spreadsheets found nearby'),
         el('div', { class: 'file-list' },
           data.suggestions.map((f) => fileRow(f, () => openWorkbook(f.path))))]
      : [el('p', { class: 'muted' },
          'No spreadsheets found nearby — paste the full path above instead.')]));

  if (data.browse) {
    const b = data.browse;
    $('#chooser-browse').replaceChildren(
      el('p', { class: 'muted' }, b.folder),
      el('div', { class: 'file-list' },
        b.parent
          ? el('button', { class: 'file-row', type: 'button',
              onclick: () => renderChooser(b.parent) },
              el('span', { class: 'icon' }, '\u2B06'),
              el('span', { class: 'who' }, el('b', {}, 'Up one folder')))
          : null,
        b.folders.map((f) => el('button', { class: 'file-row', type: 'button',
          onclick: () => renderChooser(f.path) },
          el('span', { class: 'icon' }, '\u{1F4C1}'),
          el('span', { class: 'who' }, el('b', {}, f.name)))),
        b.files.map((f) => fileRow(f, () => openWorkbook(f.path)))));
  }
}

async function openWorkbook(path) {
  $('#chooser-error').replaceChildren();
  try {
    await api('/api/workbooks/open', { method: 'POST', body: { path } });
    showChooser(false);
    await refreshAll();
    toast(`Opened ${path}`, 'ok');
  } catch (error) {
    $('#chooser-error').replaceChildren(
      ...(error.errors || [error.message]).map(
        (m) => el('div', { class: 'msg msg-bad' }, m)));
  }
}

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
  hours: (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })),
  pct: (v) => (v === null || v === undefined ? '—' : `${(Number(v) * 100).toFixed(1)}%`),
  pct0: (v) => (v === null || v === undefined ? '—' : `${Math.round(Number(v) * 100)}%`),
  ratio: (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(2)}×`),
  date: (v) => v || '—',
  int: (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString()),
};

function toast(message, kind = '') {
  const node = el('div', { class: `toast ${kind}` }, message);
  $('#toasts').append(node);
  setTimeout(() => {
    node.style.opacity = '0';
    node.style.transition = 'opacity .3s';
    setTimeout(() => node.remove(), 320);
  }, kind === 'bad' ? 7000 : 3800);
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
    badge.textContent = 'unsaved changes';
    badge.className = 'pill pill-warn';
  }
}

/* ------------------------------------------------------------------ modal */

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
    if (field.onchange) input.addEventListener('change', () => field.onchange(form));
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
  $('#modal-errors').innerHTML = '';
  $('#modal-errors').append(el('ul', {}, errors.map((e) => el('li', {}, e))));
}

/* --------------------------------------------------------------- overview */

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
    ['Actual MM booked', fmt.mm(p.actual_mm), `${fmt.hours(p.actual_mm * data.hours_per_man_month)} hours`],
    ['Earned MM', fmt.mm(p.earned_mm), 'budget × progress'],
    ['Profit / (loss)', fmt.mm(p.profit_mm), 'earned − actual'],
    ['Efficiency (CPI)', fmt.ratio(p.cpi), p.cpi >= 1 ? 'earning above cost' : 'earning below cost'],
    ['Register', `${p.projects} / ${p.deliverables}`, 'projects / deliverables'],
  ];
  $('#overview-cards').replaceChildren(...cards.map(([label, value, sub]) =>
    el('div', { class: 'card' },
      el('div', { class: 'label' }, label),
      el('div', { class: 'value' }, value),
      el('div', { class: 'sub' }, sub))));

  // engineers
  const engineers = $('#engineer-cards');
  engineers.replaceChildren(...Object.entries(data.engineers).map(([name, e]) => {
    const months = e.months || [];
    const peak = Math.max(1, ...months.map((m) => m.total || 0), e.available_hours_per_month || 0);
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
    const pill = util === null ? 'pill-info' : util > 1.05 ? 'pill-bad' : util < 0.7 ? 'pill-warn' : 'pill-ok';
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
  }));

  // data check
  const check = data.data_check;
  const verdictKind = check.rows === 0 ? 'msg-warn'
    : check.rows_not_matching_pattern ? 'msg-bad' : 'msg-ok';
  const unknown = check.unknown_job_numbers || [];
  $('#data-check').replaceChildren(
    el('div', { class: `msg ${verdictKind}` }, check.verdict),
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

  // issues
  const issues = data.issues || [];
  $('#issues').replaceChildren(
    issues.length === 0
      ? el('div', { class: 'msg msg-ok' }, 'Every project totals 100% phase weight, every deliverable splits 100% between the team, and every deliverable has a TS Phase.')
      : el('div', {}, issues.map((issue) => el('div', {
          class: `msg msg-${issue.level === 'error' ? 'bad' : issue.level === 'warning' ? 'warn' : 'info'}`,
        }, el('strong', {}, `${issue.where}: `), issue.message))));
}

/* -------------------------------------------------------------- timesheets */

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
      + `Rows past that stay on the sheet but reach nothing — and because the sheets stack `
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
    + 'This rewrites every formula that reads the consolidated timesheet — around '
    + '138,000 references — and adds the per-row helper formulas to match. '
    + 'A backup is taken first.\n\n'
    + 'Excel will take noticeably longer to recalculate afterwards: two of the '
    + 'helper columns cost roughly the square of the limit.')) return;
  try {
    toast('Rewriting formulas — this takes a few seconds…');
    const result = await api('/api/timesheets/capacity', {
      method: 'POST',
      body: { raw_last_row: cap.suggested_raw_last_row, source_last_row: source },
    });
    markSaved(result.save);
    toast(`Limit raised to ${result.raw_last_row.toLocaleString()} rows across `
      + `${result.sheets_changed.length} sheets.`, 'ok');
    await refreshAll();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

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
  if (select.options.length === 0) {
    for (const name of Object.keys(check.per_engineer)) {
      select.append(el('option', { value: name }, name));
    }
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
      body: { engineer, filename: file.name, content_base64: base64 },
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
  const target = $('#ts-result');

  const rows = (parsed.preview || []).map((row) => el('tr', {},
    el('td', { class: 'code' }, row.JobNumber ?? '—'),
    el('td', {}, row.FullName ?? '—'),
    el('td', {}, row.Date ?? '—'),
    el('td', { class: 'num' }, row.Phase ?? '—'),
    el('td', { class: 'num' }, fmt.hours(row.RegularHours)),
    el('td', { class: 'num' }, fmt.hours(row.OvertimeHours)),
    el('td', { class: 'num' }, fmt.hours(row.TotalHours))));

  target.replaceChildren(
    ...(parsed.errors || []).map((m) => el('div', { class: 'msg msg-bad' }, m)),
    ...(parsed.warnings || []).map((m) => el('div', { class: 'msg msg-warn' }, m)),
    el('div', { class: 'msg msg-info' },
      el('strong', {}, `${fmt.int(parsed.row_count)} rows read from ${parsed.source_name}. `),
      `${parsed.mapped_columns} of 72 columns matched. `,
      `${fmt.hours(s.hours)} hours, ${fmt.date(s.first_date)} → ${fmt.date(s.last_date)}`,
      s.months && s.months.length ? ` across ${s.months.length} month(s).` : '.'),
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
      + `Replacing is the monthly routine; appending would add `
      + `${fmt.int(parsed.duplicate_rows_if_appended)} row(s) that already look present.`),
    el('div', { class: 'row', style: 'margin-bottom:0' },
      el('button', {
        class: 'btn btn-primary', type: 'button', disabled: blocked,
        onclick: () => applyImport('replace'),
      }, `Replace all rows on TS ${parsed.engineer}`),
      el('button', {
        class: 'btn', type: 'button', disabled: blocked,
        onclick: () => applyImport('append'),
      }, 'Append to existing rows'),
      el('button', {
        class: 'btn btn-ghost', type: 'button',
        onclick: () => { discardImport(); },
      }, 'Discard')));
}

async function applyImport(mode) {
  const parsed = state.stagedImport;
  if (!parsed) return;
  const verb = mode === 'replace' ? 'Replace every row on' : 'Append these rows to';
  if (!window.confirm(
    `${verb} TS ${parsed.engineer} with ${parsed.row_count.toLocaleString()} row(s)?`
    + '\n\nA timestamped backup of the workbook is taken first.')) return;
  try {
    const result = await api('/api/timesheets/apply', {
      method: 'POST', body: { token: parsed.token, mode },
    });
    markSaved(result.save);
    state.stagedImport = null;
    $('#ts-file').value = '';
    $('#ts-result').replaceChildren(el('div', { class: 'msg msg-ok' },
      `TS ${result.engineer} now holds ${fmt.int(result.rows)} rows. `
      + `${result.data_check.verdict}`));
    toast(`TS ${result.engineer} updated (${fmt.int(result.rows)} rows).`, 'ok');
    await refreshAll();
  } catch (error) {
    toast(error.message, 'bad');
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

/* ---------------------------------------------------------------- projects */

const PROJECT_FIELDS = () => [
  { name: 'number', label: 'Project number', hint: 'as it appears on the timesheet' },
  { name: 'name', label: 'Project name' },
  { name: 'budget_mm', label: 'Budget (MM)', type: 'number', step: '0.01', min: '0' },
  { name: 'status', label: 'Status', type: 'select', options: state.reference.statuses },
  { name: 'start', label: 'Start', type: 'date' },
  { name: 'end', label: 'End', type: 'date' },
  { name: 'manual_percent', label: 'Manual % complete', type: 'number', step: '1', min: '0', max: '100',
    hint: 'used only until the project has deliverables' },
  { name: 'cac_override', label: 'Cost at completion override (MM)', type: 'number', step: '0.01',
    hint: 'leave blank to let the workbook derive it' },
  { name: 'manual_share_ahmed', label: 'Fallback share — Ahmed %', type: 'number', step: '1', min: '0', max: '100' },
  { name: 'manual_share_osama', label: 'Fallback share — Osama %', type: 'number', step: '1', min: '0', max: '100' },
  { name: 'manual_share_kirolos', label: 'Fallback share — Kirolos %', type: 'number', step: '1', min: '0', max: '100' },
  { name: 'notes', label: 'Notes', type: 'textarea', full: true },
];

function projectToForm(project) {
  const pct = (v) => (v === null || v === undefined ? '' : Math.round(v * 1000) / 10);
  return {
    ...project,
    manual_percent: pct(project.manual_percent),
    manual_share_ahmed: pct(project.manual_share_ahmed),
    manual_share_osama: pct(project.manual_share_osama),
    manual_share_kirolos: pct(project.manual_share_kirolos),
  };
}

function formToProject(values) {
  const pct = (v) => (v === null || v === undefined || v === '' ? null : Number(v) / 100);
  return {
    ...values,
    manual_percent: pct(values.manual_percent),
    manual_share_ahmed: pct(values.manual_share_ahmed),
    manual_share_osama: pct(values.manual_share_osama),
    manual_share_kirolos: pct(values.manual_share_kirolos),
  };
}

function openProjectModal(project) {
  const editing = Boolean(project);
  openModal(editing ? `Edit ${project.number}` : 'Add project', PROJECT_FIELDS(),
    async () => {
      const body = formToProject(modalValues());
      const path = editing ? `/api/projects/${encodeURIComponent(project.number)}` : '/api/projects';
      const result = await api(path, { method: editing ? 'PUT' : 'POST', body });
      markSaved(result.save);
      toast(`${result.project.number} saved to Inputs row ${result.project.row}.`, 'ok');
      await refreshAll();
    },
    editing ? projectToForm(project) : { status: 'Active' });
}

function renderProjects() {
  // The filters are rebuilt from the register each time so a newly added
  // project appears in them straight away.
  const projectSelect = $('#project-filter');
  const chosen = projectSelect.value || 'all';
  projectSelect.replaceChildren(
    el('option', { value: 'all' }, `All projects (${state.projects.length})`),
    ...state.projects.map((p) => el('option', { value: p.number },
      `${p.number} — ${p.name}`)));
  projectSelect.value = state.projects.some((p) => p.number === chosen)
    ? chosen : 'all';

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

  const table = $('#projects-table');
  table.replaceChildren(
    el('thead', {}, el('tr', {},
      ['#', 'Number', 'Name', 'Status', 'Budget MM', 'Progress', 'Actual MM',
       'Earned MM', 'Profit MM', 'CPI', 'Deliv.', 'Weights', '']
        .map((h, i) => el('th', { class: i === 0 || (i >= 4 && i <= 10) ? 'num' : '' }, h)))),
    el('tbody', {}, rows.length === 0
      ? el('tr', {}, el('td', { colspan: 13 }, el('div', { class: 'empty' }, 'No projects match.')))
      : rows.map((project, position) => {
        const m = byNumber.get(project.number) || {};
        const cpiPill = m.cpi === null || m.cpi === undefined ? ''
          : m.cpi >= 1 ? 'pill-ok' : m.cpi >= 0.8 ? 'pill-warn' : 'pill-bad';
        return el('tr', {},
          el('td', {
            class: 'num muted',
            title: `Inputs row ${project.row} in the workbook`,
          }, position + 1),
          el('td', { class: 'code' }, project.number),
          el('td', { class: 'wide' }, project.name),
          el('td', {}, el('span', { class: `pill ${statusPill(project.status)}` }, project.status || '—')),
          el('td', { class: 'num' }, fmt.mm(project.budget_mm)),
          el('td', { class: 'num' }, fmt.pct(m.progress)),
          el('td', { class: 'num' }, fmt.mm(m.actual_mm)),
          el('td', { class: 'num' }, fmt.mm(m.earned_mm)),
          el('td', { class: 'num' }, fmt.mm(m.profit_mm)),
          el('td', { class: 'num' }, cpiPill
            ? el('span', { class: `pill ${cpiPill}` }, fmt.ratio(m.cpi)) : '—'),
          el('td', { class: 'num' }, m.deliverables ?? 0),
          el('td', {}, m.deliverables
            ? el('span', { class: `pill ${m.weight_ok ? 'pill-ok' : 'pill-bad'}` },
                m.weight_ok ? 'OK' : fmt.pct(m.weight_total))
            : el('span', { class: 'pill pill-info' }, 'none')),
          el('td', {}, el('div', { class: 'row-actions' },
            el('button', { class: 'btn btn-sm', type: 'button',
              onclick: () => openProjectModal(project) }, 'Edit'),
            el('button', { class: 'btn btn-sm btn-danger', type: 'button',
              onclick: () => removeProject(project, m) }, 'Delete'))));
      })));
}

function statusPill(status) {
  if (status === 'Active') return 'pill-ok';
  if (status === 'Not Started') return 'pill-info';
  if (status === 'On Hold') return 'pill-warn';
  if (status === 'Cancelled') return 'pill-bad';
  return '';
}

async function removeProject(project, m) {
  const count = m.deliverables || 0;
  const extra = count
    ? `\n\nThis will also clear its ${count} deliverable(s) from the register.` : '';
  if (!window.confirm(`Remove ${project.number} from Inputs row ${project.row}?${extra}`)) return;
  try {
    const result = await api(
      `/api/projects/${encodeURIComponent(project.number)}?cascade=${count ? 'true' : 'false'}`,
      { method: 'DELETE' });
    markSaved(result.save);
    toast(`${project.number} removed.`, 'ok');
    await refreshAll();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

/* ------------------------------------------------------------ deliverables */

function stepOptions(typeCode) {
  const steps = (state.reference.credit_steps || {})[typeCode] || [];
  return [{ value: '', label: '— not started —' }].concat(steps.map((s) => ({
    value: s.step_no,
    label: `${s.step_no}. ${s.step_name} (${Math.round(s.credit * 100)}%)`,
  })));
}

function deliverableFields(values) {
  const typeCode = values.type_code || state.reference.project_types[0].code;
  return [
    { name: 'project_number', label: 'Project', type: 'select',
      options: state.projects.map((p) => ({ value: p.number, label: `${p.number} — ${p.name}` })) },
    { name: 'name', label: 'Deliverable / phase' },
    { name: 'type_code', label: 'Type', type: 'select',
      options: state.reference.project_types.map((t) => ({ value: t.code, label: `${t.code} — ${t.name}` })),
      onchange: (form) => {
        const select = form.querySelector('[name="step_no"]');
        const current = select.value;
        select.replaceChildren(...stepOptions(form.querySelector('[name="type_code"]').value)
          .map((o) => el('option', { value: o.value }, o.label)));
        select.value = current;
      } },
    { name: 'step_no', label: 'Step reached', type: 'select', options: stepOptions(typeCode),
      hint: 'sets the credit % from Rules of Credit' },
    { name: 'phase_weight', label: 'Phase weight %', type: 'number', step: '0.1', min: '0', max: '100',
      hint: "this deliverable's share of the project's scope" },
    { name: 'status_date', label: 'Status date', type: 'date' },
    { name: 'ts_phase', label: 'TS Phase', type: 'number', step: '1',
      hint: 'the Phase number this work is booked to on the timesheet' },
    { name: 'share_ahmed', label: 'Ahmed %', type: 'number', step: '1', min: '0', max: '100' },
    { name: 'share_osama', label: 'Osama %', type: 'number', step: '1', min: '0', max: '100' },
    { name: 'share_kirolos', label: 'Kirolos %', type: 'number', step: '1', min: '0', max: '100' },
    { name: 'actual_start', label: 'Actual start', type: 'date' },
    { name: 'actual_finish', label: 'Actual finish', type: 'date' },
    { name: 'submitted_to_client', label: 'Submitted to client', type: 'date' },
    { name: 'comments_received', label: 'Comments received', type: 'date' },
    { name: 'resubmitted', label: 'Resubmitted', type: 'date' },
    { name: 'completed', label: 'Completed', type: 'date' },
    { name: 'notes', label: 'Notes', type: 'textarea', full: true },
  ];
}

function deliverableToForm(d) {
  const pct = (v) => (v === null || v === undefined ? '' : Math.round(v * 1000) / 10);
  return {
    ...d,
    phase_weight: pct(d.phase_weight),
    share_ahmed: pct(d.share_ahmed),
    share_osama: pct(d.share_osama),
    share_kirolos: pct(d.share_kirolos),
  };
}

function formToDeliverable(values) {
  const pct = (v) => (v === null || v === undefined || v === '' ? null : Number(v) / 100);
  return {
    ...values,
    phase_weight: pct(values.phase_weight),
    share_ahmed: pct(values.share_ahmed),
    share_osama: pct(values.share_osama),
    share_kirolos: pct(values.share_kirolos),
  };
}

function openDeliverableModal(deliverable) {
  if (state.projects.length === 0) {
    toast('Add a project before adding deliverables.', 'bad');
    return;
  }
  const editing = Boolean(deliverable);
  const chosenProject = $('#deliverable-project-filter').value;
  const values = editing ? deliverableToForm(deliverable) : {
    project_number: chosenProject && chosenProject !== 'all'
      ? chosenProject : state.projects[0].number,
    type_code: state.reference.project_types[0].code,
  };
  openModal(editing ? `Edit deliverable (row ${deliverable.row})` : 'Add deliverable',
    deliverableFields(values),
    async () => {
      const body = formToDeliverable(modalValues());
      const path = editing ? `/api/deliverables/${deliverable.row}` : '/api/deliverables';
      const result = await api(path, { method: editing ? 'PUT' : 'POST', body });
      markSaved(result.save);
      toast(`Deliverable saved to Deliverables row ${result.deliverable.row}.`, 'ok');
      await refreshAll();
    }, values);
}

function renderDeliverables() {
  const select = $('#deliverable-project-filter');
  const chosen = select.value || 'all';
  select.replaceChildren(
    el('option', { value: 'all' }, `All projects (${state.deliverables.length})`),
    ...state.projects.map((p) => el('option', { value: p.number },
      `${p.number} — ${p.name}`)));
  select.value = state.projects.some((p) => p.number === chosen) ? chosen : 'all';

  const filter = $('#deliverable-search').value.trim().toLowerCase();
  const byRow = new Map(state.deliverableMetrics.map((m) => [m.row, m]));
  const rows = state.deliverables.filter((d) => {
    if (select.value !== 'all' && d.project_number !== select.value) return false;
    if (!filter) return true;
    const m = byRow.get(d.row) || {};
    return `${d.project_number} ${d.name} ${d.type_code} ${m.step_name || ''}`
      .toLowerCase().includes(filter);
  });

  // weight warnings for whatever is on screen
  const totals = new Map();
  for (const d of state.deliverables) {
    totals.set(d.project_number, (totals.get(d.project_number) || 0) + (d.phase_weight || 0));
  }
  const offenders = [...totals.entries()].filter(([, total]) => Math.abs(total - 1) > 1e-4);
  $('#weight-warnings').replaceChildren(...offenders.map(([number, total]) =>
    el('div', { class: 'msg msg-bad' },
      el('strong', {}, `${number}: `),
      `phase weights total ${fmt.pct(total)}, not 100%. Progress for this project is not meaningful until they do.`)));

  $('#deliverables-table').replaceChildren(
    el('thead', {}, el('tr', {},
      ['#', 'Project', 'Deliverable', 'Type', 'Weight', 'Step', 'Credit',
       'Progress', 'TS Phase', 'Actual h', 'Last charge', 'A / O / K', '']
        .map((h, i) => el('th', { class: i === 0 || [4, 6, 7, 8, 9].includes(i) ? 'num' : '' }, h)))),
    el('tbody', {}, rows.length === 0
      ? el('tr', {}, el('td', { colspan: 13 }, el('div', { class: 'empty' }, 'No deliverables match.')))
      : rows.map((d, position) => {
        const m = byRow.get(d.row) || {};
        const split = ['share_ahmed', 'share_osama', 'share_kirolos']
          .map((k) => (d[k] === null || d[k] === undefined ? '–' : `${Math.round(d[k] * 100)}`))
          .join(' / ');
        return el('tr', {},
          el('td', {
            class: 'num muted',
            title: `Deliverables row ${d.row} in the workbook`,
          }, position + 1),
          el('td', { class: 'code' }, d.project_number),
          el('td', { class: 'wide' }, d.name),
          el('td', {}, d.type_code),
          el('td', { class: 'num' }, fmt.pct0(d.phase_weight)),
          el('td', { class: 'wide' }, m.step_name || (d.step_no ? `step ${d.step_no}` : '—')),
          el('td', { class: 'num' }, fmt.pct0(m.credit)),
          el('td', { class: 'num' }, fmt.pct(m.weighted_progress)),
          el('td', { class: 'num' }, d.ts_phase === null || d.ts_phase === undefined
            ? el('span', { class: 'pill pill-warn' }, 'not set') : d.ts_phase),
          el('td', { class: 'num' }, fmt.hours(m.actual_hours)),
          el('td', {}, fmt.date(m.last_charge)),
          el('td', {}, el('span', { class: `pill ${m.split_ok ? 'pill-ok' : 'pill-bad'}` }, split)),
          el('td', {}, el('div', { class: 'row-actions' },
            el('button', { class: 'btn btn-sm', type: 'button',
              onclick: () => openDeliverableModal(d) }, 'Edit'),
            el('button', { class: 'btn btn-sm btn-danger', type: 'button',
              onclick: () => removeDeliverable(d) }, 'Delete'))));
      })));
}

async function removeDeliverable(deliverable) {
  if (!window.confirm(
    `Remove "${deliverable.name}" from Deliverables row ${deliverable.row}?`)) return;
  try {
    const result = await api(`/api/deliverables/${deliverable.row}`, { method: 'DELETE' });
    markSaved(result.save);
    toast('Deliverable removed.', 'ok');
    await refreshAll();
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

/* ------------------------------------------------------------------ wiring */

async function refreshAll() {
  const status = await api('/api/status');
  state.status = status;
  if (!status.open) {
    $('#workbook-path').textContent = 'no workbook open';
    showChooser(true);
    await renderChooser(state.browseFolder);
    return;
  }
  showChooser(false);
  if (!state.reference) state.reference = await api('/api/reference');
  if (state.year === null && state.reference) state.year = state.reference.plan_year;
  await loadWorkbookViews();
}

async function loadWorkbookViews() {
  const yearParam = state.year === null ? 'all' : state.year;
  const [overview, projects, deliverables] = await Promise.all([
    api(`/api/overview?year=${yearParam}`),
    api('/api/projects'),
    api('/api/deliverables'),
  ]);
  const status = state.status;
  state.overview = overview;
  state.projects = projects.projects;
  state.projectMetrics = projects.metrics;
  state.deliverables = deliverables.deliverables;
  state.deliverableMetrics = deliverables.metrics;

  $('#workbook-path').textContent = status.workbook;
  $('#workbook-path').title = `${status.workbook} — backups in ${status.backups}`;
  markSaved({ saved: !status.unsaved_changes, pending: status.unsaved_changes });

  renderOverview();
  renderTimesheets();
  renderProjects();
  renderDeliverables();
}

function switchView(view) {
  state.view = view;
  for (const tab of $$('.tab')) tab.classList.toggle('is-active', tab.dataset.view === view);
  for (const section of $$('.view')) {
    section.classList.toggle('is-active', section.id === `view-${view}`);
  }
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
  $('#btn-change').addEventListener('click', async () => {
    if (state.status && state.status.unsaved_changes) {
      await api('/api/save', { method: 'POST' }).catch(() => {});
    }
    await api('/api/workbooks/close', { method: 'POST' });
    showChooser(true);
    await renderChooser(state.browseFolder);
  });
  $('#chooser-open').addEventListener('click',
    () => openWorkbook($('#chooser-path').value.trim()));
  $('#chooser-path').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') openWorkbook($('#chooser-path').value.trim());
  });
  $('#chooser-browse-wrap').addEventListener('toggle', (event) => {
    if (event.target.open) renderChooser(state.browseFolder);
  });
  $('#deliverable-search').addEventListener('input', renderDeliverables);
  $('#deliverable-project-filter').addEventListener('change', renderDeliverables);
  $('#btn-new-project').addEventListener('click', () => openProjectModal(null));
  $('#btn-new-deliverable').addEventListener('click', () => openDeliverableModal(null));
  $('#btn-ts-check').addEventListener('click', checkTimesheetFile);

  $('#btn-save').addEventListener('click', async () => {
    const result = await api('/api/save', { method: 'POST' });
    markSaved(result.saved ? result : { saved: true });
    toast(result.saved ? `Saved. Backup: ${result.backup}` : 'Nothing to save.', 'ok');
  });
  $('#btn-reload').addEventListener('click', async () => {
    if (state.status && state.status.unsaved_changes
      && !window.confirm('Discard unsaved changes and re-read the file from disk?')) return;
    await api('/api/reload', { method: 'POST' });
    await refreshAll();
    toast('Workbook re-read from disk.', 'ok');
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
  $('#modal-form').addEventListener('submit', (event) => event.preventDefault());
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('#modal-backdrop').hidden) closeModal();
  });
}

(async function start() {
  wire();
  try {
    await refreshAll();
  } catch (error) {
    document.body.prepend(el('div', { class: 'msg msg-bad', style: 'margin:20px' },
      `Could not start: ${error.message}`));
  }
})();
