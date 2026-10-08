/* My day: an engineer's own day on their own page.
 *
 * Today in order, as the planner lays it out for them, with due dates; one tap
 * to say a task is done, stuck, or that they need help (their lead sees it in
 * Check-ins and on their phone); "I'm off on" for leave; and the ready
 * timesheet, their week by job and phase to copy into BISpark.
 *
 * Built on member.js's helpers (el, $, api, toast, setChildren, fmt, num).
 * The server decides whose day it is from the account, never from here.
 */
'use strict';

const myDay = { unit: null, day: null, sheet: null, date: null, week: null, open: null };

const MD_KIND = {
  task: 'Task', submission: 'Submission', meeting: 'Meeting', request: 'Request',
  management: 'Team', development: 'Development', work: 'Project work', done: 'Done',
};

function mdQuery(extra = {}) {
  const query = new URLSearchParams();
  if (myDay.unit) query.set('unit', myDay.unit);
  for (const [key, value] of Object.entries(extra)) if (value) query.set(key, value);
  const text = query.toString();
  return text ? `?${text}` : '';
}

function mdDate(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  if (!iso) return '';
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, opts);
}

async function loadMyDay(unit) {
  myDay.unit = unit || myDay.unit;
  try {
    const [day, sheet] = await Promise.all([
      api(`/api/me/day${mdQuery({ date: myDay.date })}`, { quiet: true }),
      api(`/api/me/timesheet${mdQuery({ week: myDay.week })}`, { quiet: true }),
    ]);
    myDay.day = day;
    myDay.sheet = sheet;
  } catch (error) {
    $('#myday').hidden = true;
    $('#mytimesheet').hidden = true;
    $('#myoff').hidden = true;
    return;
  }
  $('#myday').hidden = false;
  $('#mytimesheet').hidden = false;
  $('#myoff').hidden = false;
  renderMyDay();
  renderTimeOff();
  renderSheet();
  if (window.planReview) window.planReview.mine($('#myweek'), myDay.unit);
}

async function refreshDay() {
  try {
    myDay.day = await api(`/api/me/day${mdQuery({ date: myDay.date })}`, { quiet: true });
    myDay.sheet = await api(`/api/me/timesheet${mdQuery({ week: myDay.week })}`, { quiet: true });
  } catch (error) {
    toast(error.message, 'bad');
    return;
  }
  renderMyDay();
  renderTimeOff();
  renderSheet();
}

/* ------------------------------------------------------------- today */

function dueChip(task) {
  if (!task || !task.due) return null;
  if (task.done) return null;
  if (task.overdue) return el('span', { class: 'pill pill-bad' }, `Overdue · was due ${mdDate(task.due)}`);
  if (task.due_today) return el('span', { class: 'pill pill-warn' }, 'Due today');
  return el('span', { class: 'pill pill-info' }, `Due ${mdDate(task.due)}`);
}

function renderMyDay() {
  const day = myDay.day;
  const isToday = day.date === day.today;
  const free = day.free_hours >= 0.25 ? `${fmt.hours(day.free_hours)} h free` : 'Full day';
  const head = el('div', { class: 'panel-head' },
    el('div', {},
      el('h3', {}, isToday ? `My day · ${mdDate(day.date)}` : `My day · ${mdDate(day.date, { weekday: 'long', day: 'numeric', month: 'short' })}`),
      el('p', { class: 'muted' },
        day.away ? 'You are off this day.'
          : !day.working_day ? 'Not a working day.'
            : `${fmt.hours(day.hours)} h planned · ${free}`
              + (day.over_hours ? ` · ${fmt.hours(day.over_hours)} h does not fit` : ''))),
    el('div', { class: 'md-nav' },
      el('button', { class: `btn btn-sm${isToday ? ' btn-primary' : ''}`, type: 'button',
        onclick: () => { myDay.date = null; refreshDay(); } }, 'Today'),
      el('button', { class: `btn btn-sm${!isToday ? ' btn-primary' : ''}`, type: 'button',
        onclick: () => { myDay.date = day.next_day; refreshDay(); } },
      'Next day')));

  const items = day.blocks.map((block) => blockItem(block));
  const list = items.length
    ? el('ol', { class: 'md-list' }, ...items)
    : el('div', { class: 'empty' }, day.away || !day.working_day
      ? 'Nothing planned.' : 'Nothing planned yet. Your lead plans from your tasks and timesheets.');

  const later = day.later.length
    ? el('div', { class: 'md-later' },
      el('h4', {}, `Still open (${day.later.length})`),
      el('ol', { class: 'md-list' }, ...day.later.map((task) => blockItem({
        kind: 'task', title: task.name, project: task.project,
        project_name: task.project_name, start: '', end: '', hours: task.hours, task,
      }))))
    : null;

  const asks = day.asks.filter((a) => !a.task_id);
  const help = el('div', { class: 'md-help' },
    ...asks.map((ask) => el('div', { class: 'md-ask' },
      el('span', { class: `pill ${ask.seen ? 'pill-ok' : 'pill-warn'}` },
        ask.seen ? 'Your lead has seen it' : 'Sent to your lead'),
      el('span', {}, ask.note),
      ask.seen ? null : el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
        onclick: () => undo(ask.id) }, 'Undo'))),
    myDay.open === 'help'
      ? noteForm('What do you need help with?', true, async (note) => {
        await api(`/api/me/help${mdQuery()}`, { method: 'POST', body: { note } });
        toast('Sent to your lead.', 'ok');
      })
      : el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => { myDay.open = 'help'; renderMyDay(); } },
      'Need help with something else'));

  setChildren($('#myday'), head, list, later, myGoals(day.goals), help);
}

/* Their own goals for the quarter, set by the manager; worked on in the
   weekly development time. Read only here. */
function myGoals(goals) {
  if (!goals) return null;
  const tone = { met: 'pill-ok', partly: 'pill-warn', not_met: 'pill-bad' };
  return el('div', { class: 'md-later md-goals' },
    el('h4', {}, `My goals · ${goals.label}`),
    goals.items.length
      ? el('ul', { class: 'md-goal-list' }, ...goals.items.map((g) => el('li', {},
        el('span', {}, g.goal),
        g.result ? el('span', { class: `pill ${tone[g.result] || ''}`, style: 'margin-left:6px' }, g.result_label) : null,
        g.measure ? el('div', { class: 'muted' }, `How we will know: ${g.measure}`) : null)))
      : el('p', { class: 'muted' }, 'No goals for this quarter yet. Ask your manager to set them.'),
    el('p', { class: 'muted' }, 'Your development time each week is kept for these.'));
}

function blockItem(block) {
  const task = block.task || null;
  const mark = task && task.mark;
  const done = task && task.done;
  const key = task ? `task-${task.id}` : '';
  const time = block.start ? `${block.start}–${block.end}` : '';
  const project = block.project
    ? el('span', { class: 'md-project', title: block.project_name || '' }, block.project) : null;
  const sub = [MD_KIND[block.kind] || '', block.kind === 'work' ? '' : (block.project_name || '')]
    .filter(Boolean).join(' · ');

  let actions = null;
  if (task) {
    if (done) {
      actions = el('div', { class: 'md-actions' },
        el('span', { class: 'pill pill-ok' }, '✓ Done'),
        mark && mark.kind === 'done'
          ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => undo(mark.id) }, 'Undo')
          : null);
    } else if (mark && mark.kind !== 'done') {
      actions = el('div', { class: 'md-actions' },
        el('span', { class: `pill ${mark.seen ? 'pill-ok' : mark.kind === 'stuck' ? 'pill-bad' : 'pill-warn'}` },
          mark.kind === 'stuck' ? 'Stuck' : 'Help asked',
          mark.seen ? ' · lead has seen it' : ' · sent to your lead'),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: () => markTask(task.id, 'done') }, '✓ Done'),
        el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => undo(mark.id) },
          mark.kind === 'stuck' ? 'Back on track' : 'Undo'));
    } else {
      actions = el('div', { class: 'md-actions' },
        el('button', { class: 'btn btn-sm md-done', type: 'button', onclick: () => markTask(task.id, 'done') }, '✓ Done'),
        el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => { myDay.open = `${key}:stuck`; renderMyDay(); } }, 'Stuck'),
        el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => { myDay.open = `${key}:help`; renderMyDay(); } }, 'Need help'));
    }
  }
  let form = null;
  if (task && myDay.open && myDay.open.startsWith(`${key}:`)) {
    const kind = myDay.open.split(':')[1];
    form = noteForm(kind === 'stuck' ? 'What is holding it up? (optional)' : 'What do you need? (optional)',
      false, (note) => markTask(task.id, kind, note, true));
  }
  return el('li', { class: `md-item md-${block.kind}${done ? ' md-is-done' : ''}` },
    el('div', { class: 'md-time' }, time || (task && task.hours ? `${fmt.hours(task.hours)} h` : '')),
    el('div', { class: 'md-body' },
      el('div', { class: 'md-title' }, block.title, ' ', project),
      el('div', { class: 'md-meta' }, sub ? el('span', { class: 'muted small' }, sub) : null, dueChip(task)),
      actions, form));
}

function noteForm(placeholder, required, send) {
  const input = el('input', { type: 'text', maxlength: 300, placeholder, class: 'md-note' });
  const submit = async () => {
    const note = input.value.trim();
    if (required && !note) { input.focus(); return; }
    try {
      await send(note);
      myDay.open = null;
      await refreshDay();
    } catch (error) {
      toast((error.errors || [error.message]).join(' '), 'bad');
    }
  };
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });
  setTimeout(() => input.focus(), 0);
  return el('div', { class: 'md-form' }, input,
    el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: submit }, 'Send'),
    el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
      onclick: () => { myDay.open = null; renderMyDay(); } }, 'Cancel'));
}

async function markTask(taskId, kind, note = '', fromForm = false) {
  try {
    await api(`/api/me/tasks/${taskId}/mark${mdQuery()}`, { method: 'POST', body: { kind, note } });
  } catch (error) {
    if (fromForm) throw error;
    toast((error.errors || [error.message]).join(' '), 'bad');
    return;
  }
  toast(kind === 'done' ? 'Ticked off.' : 'Sent to your lead.', 'ok');
  if (!fromForm) await refreshDay();
}

async function undo(markId) {
  try {
    await api(`/api/me/marks/${markId}/undo${mdQuery()}`, { method: 'POST' });
  } catch (error) {
    toast(error.message, 'bad');
    return;
  }
  await refreshDay();
}

/* ------------------------------------------------------------ time off */

function renderTimeOff() {
  const day = myDay.day;
  const start = el('input', { type: 'date', id: 'md-off-start', min: day.today, value: day.today });
  const end = el('input', { type: 'date', id: 'md-off-end', min: day.today, value: day.today });
  const note = el('input', { type: 'text', id: 'md-off-note', maxlength: 120, placeholder: 'Annual leave, course, site visit…' });
  start.addEventListener('change', () => { if (end.value < start.value) end.value = start.value; });
  const add = async () => {
    try {
      await api(`/api/me/off${mdQuery()}`, { method: 'POST',
        body: { start: start.value, end: end.value || start.value, note: note.value } });
    } catch (error) {
      toast((error.errors || [error.message]).join(' '), 'bad');
      return;
    }
    toast('Added. Your plan and your lead now leave you out those days.', 'ok');
    await refreshDay();
  };
  const range = (o) => (o.start === o.end ? mdDate(o.start) : `${mdDate(o.start)} to ${mdDate(o.end)}`);
  setChildren($('#myoff'),
    el('h3', {}, "I'm off on"),
    el('p', { class: 'muted' }, 'Leave, a course, a site visit. Your plan leaves you out those days and your lead is told.'),
    el('div', { class: 'md-off-form' },
      el('label', { class: 'field' }, el('span', {}, 'From'), start),
      el('label', { class: 'field' }, el('span', {}, 'To'), end),
      el('label', { class: 'field md-off-note' }, el('span', {}, 'What for (optional)'), note),
      el('button', { class: 'btn btn-primary', type: 'button', onclick: add }, 'Add')),
    day.off.length
      ? el('ul', { class: 'md-off-list' }, ...day.off.map((o) => el('li', {},
        el('b', {}, range(o)), o.note ? el('span', { class: 'muted' }, ` · ${o.note}`) : null,
        o.mine
          ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: async () => {
            try {
              await api(`/api/me/off/${o.mark_id}/remove${mdQuery()}`, { method: 'POST' });
            } catch (error) { toast(error.message, 'bad'); return; }
            await refreshDay();
          } }, 'Take back')
          : el('span', { class: 'muted small' }, ' · entered by your manager'))))
      : el('p', { class: 'muted small' }, 'No days off coming up.'));
}

/* ---------------------------------------------------- ready timesheet */

const SOURCE_LABEL = {
  booked: 'In BISpark', plan: 'From your plan', plan_past: 'From your plan', off: 'Off',
};

function renderSheet() {
  const sheet = myDay.sheet;
  const dates = sheet.days.map((d) => d.date);
  const copy = async (text, what) => {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} copied. Paste it into BISpark.`, 'ok');
    } catch (error) {
      window.prompt('Copy this:', text);
    }
  };
  // Quarter hours exactly, as they go into BISpark.
  const quarters = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const cell = (hours) => (hours ? quarters(hours) : '');
  const head = el('tr', {},
    el('th', {}, 'Job'), el('th', {}, 'Phase'),
    ...sheet.days.map((d) => el('th', { class: 'num' },
      mdDate(d.date, { weekday: 'short', day: 'numeric' }),
      el('div', { class: `md-src md-src-${d.source}` }, SOURCE_LABEL[d.source] || ''))),
    el('th', { class: 'num' }, 'Total'), el('th', {}, ''));
  const rows = sheet.lines.map((line) => {
    const text = [line.job, line.phase === null ? '' : line.phase,
      ...dates.map((d) => cell(line.hours[d]))].join('\t');
    return el('tr', { class: `md-line md-line-${line.kind}` },
      el('td', {}, el('div', { class: 'code' }, line.job || '—'),
        el('div', { class: 'muted small md-line-name' }, line.name)),
      el('td', {}, line.phase === null ? '—' : String(line.phase),
        line.phase_name ? el('div', { class: 'muted small' }, line.phase_name) : null),
      ...dates.map((d) => el('td', { class: 'num' }, cell(line.hours[d]))),
      el('td', { class: 'num' }, el('b', {}, quarters(line.total))),
      el('td', {}, el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
        title: 'Copy this line', onclick: () => copy(text, 'Line') }, 'Copy')));
  });
  const totals = el('tr', { class: 'md-total' },
    el('td', {}, 'Day total'), el('td', {}, ''),
    ...sheet.days.map((d) => el('td', { class: 'num' }, cell(d.total))),
    el('td', { class: 'num' }, el('b', {}, quarters(sheet.total))), el('td', {}, ''));
  const range = `${mdDate(sheet.week_start)} to ${mdDate(sheet.week_end)}`;
  setChildren($('#mytimesheet'),
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, 'Ready timesheet'),
        el('p', { class: 'muted' },
          `${range}. Your hours by job and phase from your plan and tasks, ready to copy `
          + 'into BISpark. Days already in BISpark show what you booked. Nothing is sent '
          + 'to BISpark; check each line before you enter it.')),
      el('div', { class: 'md-nav' },
        el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => { myDay.week = sheet.previous; refreshDay(); } }, '‹ Week before'),
        sheet.this_week ? null : el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => { myDay.week = null; refreshDay(); } }, 'This week'),
        el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => { myDay.week = sheet.next; refreshDay(); } }, 'Week after ›'),
        el('button', { class: 'btn btn-sm btn-primary', type: 'button',
          onclick: () => copy(sheet.copy, 'Timesheet') }, 'Copy all'))),
    sheet.lines.length
      ? el('div', { class: 'table-wrap md-sheet' },
        el('table', { 'data-plain': '' }, el('thead', {}, head), el('tbody', {}, ...rows, totals)))
      : el('div', { class: 'empty' }, 'Nothing for this week yet.'));
}

window.myDay = { load: loadMyDay };
