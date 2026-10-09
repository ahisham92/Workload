/* Selecao+ — the coming days, drawings, and when to ask for people.
 *
 * The Planner tab: each person's next few working days as their recent pace
 * says they will go, work handed from one person to another to see what it
 * does before anything changes, and the forecast that says which team needs
 * more people, how many, and for how long.
 *
 * Built on app.js's helpers (el, api, state, fmt, tone, openModal...). The
 * server does every sum; this file only draws them and sends the moves.
 */
'use strict';

const plan = {
  view: 'today',      // today | handovers | submissions | people
  date: null,         // the day on show; null is today
  span: 'day',        // day | week
  dayData: null,      // everybody's day (or week), as the server laid it out
  calendars: null,    // whose Outlook calendar is linked (busy times only)
  meetings: null,     // meetings typed in by hand, still to come
  me: '',             // who the manager is on the team, if they said
  calendarsOpen: false,
  submissions: null,  // the drafted submissions plan
  chosen: new Set(),  // submissions ticked to confirm
  edits: {},          // row -> a date somebody changed
  timer: null,        // refreshes Today while it is on screen
  days: 5,
  team: 'all',
  moves: [],          // handovers being tried, not yet committed
  data: null,         // the outlook for those moves
  needs: null,        // the forecast: who needs more people
  open: new Set(),    // people whose work is expanded
  whatIfs: null,      // the what-ifs kept, with their figures
  busy: false,
};

const ROLE_LABEL = { engineering: 'Engineers', drafting: 'Draftsmen' };

function loadTone(load) {
  if (load === null || load === undefined) return '';
  return load > 1.0001 ? 'bad' : load < 0.8 ? 'warn' : 'ok';
}

const shortDate = (iso) => dateText(iso, { day: 'numeric', month: 'short' });

/* ------------------------------------------------------------ loading */

const PLANNER_VIEWS = [['today', 'Today'], ['review', 'Plan vs actual'],
  ['handovers', 'Planning board'],
  ['submissions', 'Submissions'], ['people', 'More people']];

function renderPlannerTabs() {
  setChildren($('#planner-subtabs'), ...PLANNER_VIEWS.map(([key, label]) =>
    el('button', {
      class: `subtab ${plan.view === key ? 'is-active' : ''}`, type: 'button',
      onclick: () => { plan.view = key; openPlanner(); },
    }, label)));
}

/** Whatever the chosen subtab needs, fetched and drawn. */
async function openPlanner({ quiet = false } = {}) {
  renderPlannerTabs();
  clearInterval(plan.timer);
  plan.timer = null;
  $('#planner-team').parentElement.hidden = true;
  if (plan.view === 'today') {
    await loadDay({ quiet });
    // Requests come in all day: keep the page current while it is open.
    plan.timer = setInterval(() => {
      const shown = $('#view-planner').classList.contains('is-active');
      if (shown && plan.view === 'today' && !document.hidden
          && $('#modal-backdrop').hidden) loadDay({ quiet: true });
    }, 60000);
  } else if (plan.view === 'review') {
    await window.planReview.open($('#planner-body'));
  } else if (plan.view === 'submissions') {
    await loadSubmissions({ quiet });
  } else if (plan.view === 'people') {
    try {
      plan.needs = plan.needs || await api('/api/needs');
      showNeeds();
    } catch (error) {
      if (!quiet) toastError(error);
    }
  } else {
    await loadPlanner({ quiet });
  }
}

async function loadPlanner({ quiet = false } = {}) {
  if (plan.busy) return;
  plan.busy = true;
  try {
    const [data, needs] = await Promise.all([
      api('/api/planner', { method: 'POST', body: { days: plan.days, moves: plan.moves } }),
      plan.needs ? Promise.resolve(plan.needs) : api('/api/needs'),
    ]);
    plan.data = data;
    plan.needs = needs;
    renderPlanner();
  } catch (error) {
    if (!quiet) toastError(error);
    // A move that no longer makes sense (somebody removed, a task done) is
    // dropped rather than leaving the tab stuck on an error.
    if (plan.moves.length && error.status === 422) {
      plan.moves = [];
      plan.busy = false;
      await loadPlanner({ quiet: true });
    }
  } finally {
    plan.busy = false;
  }
}

async function tryMoves(moves) {
  plan.moves = moves;
  await loadPlanner();
}

async function suggestMoves() {
  try {
    const data = await api('/api/planner/suggest', {
      method: 'POST', body: { days: plan.days, moves: plan.moves },
    });
    if (!data.suggested.length) {
      toast(data.summary.over_after
        ? 'Nobody doing the same kind of work has room to take any of it. '
          + 'See "More people" above.'
        : 'Nobody is over a full load. Nothing to suggest.');
      return;
    }
    plan.moves = plan.moves.concat(data.suggested);
    plan.data = data;
    renderPlanner();
    toast(`${data.suggested.length} handover(s) suggested. Nothing changes until you commit them.`, 'ok');
  } catch (error) {
    toastError(error);
  }
}

async function commitMoves() {
  if (!plan.moves.length) return;
  try {
    const result = await api('/api/planner/commit', {
      method: 'POST', body: { days: plan.days, moves: plan.moves },
    });
    plan.moves = [];
    plan.data = result.outlook;
    plan.needs = null;
    if (result.tasks_moved && state.tasks) state.tasks = null;
    const parts = [];
    if (result.projects_moved) parts.push(`${result.projects_moved} project handover(s) kept until ${shortDate(result.outlook.to)}`);
    if (result.tasks_moved) parts.push(`${result.tasks_moved} task(s) reassigned`);
    toast(`${parts.join(', ')}.`, 'ok');
    if (result.save) markSaved(result.save);
    await loadPlanner({ quiet: true });
  } catch (error) {
    toastError(error);
  }
}

async function undoSaved(move) {
  try {
    const result = await api(`/api/planner/moves/${move.id}/remove`, {
      method: 'POST', body: { days: plan.days, moves: plan.moves },
    });
    plan.data = result.outlook;
    plan.needs = null;
    await loadPlanner({ quiet: true });
    toast('Handover undone.', 'ok');
  } catch (error) {
    toastError(error);
  }
}

/* ------------------------------------------------------------ the tab */

function renderPlanner() {
  const data = plan.data;
  if (!data) return;
  const host = $('#planner-body');
  const teams = data.teams.filter((t) => t.people);
  if (plan.team !== 'all' && !teams.some((t) => t.id === plan.team)) plan.team = 'all';

  if (plan.view !== 'handovers') return;
  fillTeams(teams.map((t) => ({ id: t.id, name: t.name })));
  const daySelect = el('select', {
    onchange: (e) => { plan.days = Number(e.target.value); loadPlanner(); },
  }, data.day_choices.map((d) => el('option', { value: d }, `Next ${d} working days`)));
  daySelect.value = String(plan.days);

  setChildren(host,
    el('div', { class: 'plan-toolbar' }, daySelect),
    data.stale ? el('div', { class: 'msg msg-warn' },
      `The newest timesheet is from ${dateText(data.pace_to)}. A pace that old is a guess: `
      + 'import this month’s timesheets for an outlook worth acting on.') : null,
    plannerCards(data),
    window.board ? window.board.render(data) : null,
    window.board
      ? el('details', { class: 'more-block' },
        el('summary', {}, 'Each person\u2019s work, as a list'), whoHasWhat(data))
      : whoHasWhat(data),
    movesPanel(data),
    whatIfPanel(data),
    drawingsPanel(data.drawings));
}

function plannerCards(data) {
  const s = data.summary;
  const trying = plan.moves.length > 0;
  const arrow = (before, after, format) => (trying && before !== after
    ? `${format(before)} → ${format(after)}` : format(after));
  const inHand = data.people.reduce((sum, p) => sum + (p.after.drawings || 0), 0);
  return el('div', { class: 'stat-strip' },
    stat('Over a full load', arrow(s.over_before, s.over_after, String),
      s.over_after ? 'bad' : 'ok'),
    stat('With room', arrow(s.room_before, s.room_after, String), s.room_after ? 'warn' : 'ok'),
    stat('Busiest person', arrow(s.peak_before, s.peak_after, fmt.pct0),
      loadTone(s.peak_after)),
    stat('Hours of work', fmt.hours(s.hours), ''),
    stat('Drawings in hand', data.drawings.known ? fmt.int(Math.round(inHand)) : 'not set', ''),
    stat('Each person has', `${fmt.hours(data.capacity)} h`, ''));
}

function stat(label, value, toneName) {
  return el('div', { class: `stat ${toneName ? `stat-${toneName}` : ''}`, role: 'group' },
    el('span', { class: 'stat-value' }, value),
    el('span', { class: 'stat-label' }, label));
}

/* -- who needs more people ------------------------------------------- */

function renderNeeds(needs) {
  if (!needs) return null;
  const alerts = needs.alerts || [];
  const level = { now: 'bad', soon: 'warn', cover: 'warn', room: 'ok', ok: 'ok' };
  const label = { now: 'ask now', soon: 'ask soon', cover: 'hand over', room: 'room', ok: 'fine' };
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, 'More people'),
        el('p', { class: 'muted' },
          `Each team's forecast work against the people it has, week by week to ${shortDate(needs.horizon_end)}. `
          + 'Engineers and draftsmen are counted apart, because one cannot do the other’s work.'))),
    alerts.length
      ? el('div', { class: 'findings' }, alerts.map((a) => el('div', {
          class: `finding finding-${level[a.severity] || 'warn'}`,
        },
        el('div', { class: 'card-head' },
          el('b', {}, dayFirstText(a.title)),
          el('span', { class: `pill pill-${level[a.severity] === 'ok' ? 'ok' : level[a.severity]}` },
            label[a.severity] || a.severity)),
        el('p', { class: 'muted' }, dayFirstText(a.detail)),
        a.kind === 'need' ? needWeeks(needs, a) : null)))
      : el('p', { class: 'muted' }, 'Nobody to forecast for yet.'),
    needsFootnote(needs));
}

const COMING_STATUS = {
  'waiting': ['warn', 'starts later'], 'due to start': ['warn', 'nobody booking yet'],
  'started': ['ok', 'being booked'], 'used up': ['muted', 'hours used up — at its pace now'],
  'taken over': ['muted', 'on its own figures now'],
};

/** The More people subtab: the forecast, and the work coming. */
function showNeeds() {
  setChildren($('#planner-body'), renderNeeds(plan.needs), workComing(plan.needs));
}

/** A project just assigned: one line, and the forecast above counts it. */
function workComing(needs) {
  if (!needs) return null;
  const coming = needs.coming || [];
  const today = needs.today;
  const name = el('input', { type: 'text', placeholder: 'Project just assigned, e.g. Safaga berth 3',
    'aria-label': 'Project', class: 'grow' });
  const job = el('input', { type: 'text', placeholder: 'Job no.', 'aria-label': 'Job number',
    class: 'job-input' });
  const team = el('select', { 'aria-label': 'Team' },
    el('option', { value: '' }, (needs.teams || []).length ? 'Which team?' : 'The unit'),
    ...(needs.teams || []).map((t) => el('option', { value: t.id }, t.name)));
  const hours = el('input', { type: 'number', min: '1', step: '10', placeholder: 'Hours',
    'aria-label': 'Rough hours', class: 'num-input' });
  const start = el('input', { type: 'date', 'aria-label': 'Starts', value: today });
  const end = el('input', { type: 'date', 'aria-label': 'Ends' });
  let adding = false;
  const add = async () => {
    if (!name.value.trim() && !job.value.trim()) { name.focus(); return; }
    if (!Number(hours.value)) { hours.focus(); return; }
    if (adding) return;           // a second tap while the first is on its way
    adding = true;
    try {
      const result = await api('/api/planned-work', { method: 'POST', body: {
        name: name.value, job_number: job.value, team_id: team.value,
        hours: hours.value, start: start.value, end: end.value } });
      plan.needs = result.needs;
      toast(`${result.name} is in the forecast from ${shortDate(result.start)} to ${shortDate(result.end)}.`, 'ok');
      showNeeds();
    } catch (error) { toastError(error); } finally { adding = false; }
  };
  name.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  return el('section', { class: 'panel' },
    el('h3', {}, 'Work coming'),
    el('p', { class: 'muted' },
      'A project just assigned, before anybody books to it. Its rough hours are spread from start to end and counted above; '
      + 'what gets booked to its job number is taken off, and once it is confirmed on Projects its own figures take over.'),
    el('div', { class: 'quick-add' }, name,
      el('div', { class: 'quick-add-options' }, job, team, hours,
        el('label', { class: 'inline-date' }, el('span', { class: 'muted small' }, 'from'), start),
        el('label', { class: 'inline-date' }, el('span', { class: 'muted small' }, 'to'), end),
        el('button', { class: 'btn btn-primary', type: 'button', onclick: add }, 'Add'))),
    coming.length ? el('ul', { class: 'request-list' }, coming.map((c) => {
      const [tone, text] = COMING_STATUS[c.status] || ['muted', c.status];
      return el('li', { class: 'request' },
        el('span', { class: 'request-time' }, `${shortDate(c.start)} – ${shortDate(c.end)}`),
        el('span', { class: 'request-what' }, el('b', {}, c.name),
          el('span', { class: 'muted small' }, [c.job_number && c.job_number !== c.name ? c.job_number : '',
            c.team_name, `${fmt.hours(c.hours)} h`, c.booked ? `${fmt.hours(c.booked)} h booked` : '']
            .filter(Boolean).map((t) => ` · ${t}`).join('')),
          ' ', el('span', { class: `pill pill-${tone}` }, text)),
        el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: async () => {
          try {
            const result = await api(`/api/planned-work/${c.id}/remove`, { method: 'POST' });
            plan.needs = result.needs;
            showNeeds();
          } catch (error) { toastError(error); }
        } }, 'Remove'));
    })) : null);
}

/** The weeks behind an ask, as a strip of small bars: work against people. */
function needWeeks(needs, alert) {
  const group = needs.groups.find((g) => g.team_id === alert.team_id && g.role === alert.role);
  if (!group) return null;
  const max = Math.max(1, ...group.weeks.map((w) => Math.max(w.demand_hours, w.capacity_hours)));
  return el('div', { class: 'need-weeks', title: 'Each week: the work forecast (bar) against the hours the team has (line)' },
    group.weeks.map((w) => el('span', {
      class: `need-week ${w.gap_people >= 0.5 ? 'is-short' : ''}`,
      title: `${shortDate(w.from)}: ${fmt.hours(w.demand_hours)} h of work, ${fmt.hours(w.capacity_hours)} h of people`
        + (w.gap_people > 0 ? ` (${w.gap_people.toFixed(1)} short)` : ''),
    },
    el('span', { class: 'need-bar', style: `height:${Math.round((w.demand_hours / max) * 100)}%` }),
    el('span', { class: 'need-cap', style: `bottom:${Math.round((w.capacity_hours / max) * 100)}%` }))));
}

function needsFootnote(needs) {
  const notes = [];
  if (needs.assumed && needs.assumed.length) {
    notes.push(`${needs.assumed.length} project(s) set up from the timesheets are forecast at their recent pace until somebody confirms them on Projects`
      + ` (${needs.assumed.slice(0, 4).map((p) => p.number).join(', ')}${needs.assumed.length > 4 ? '…' : ''}).`);
  }
  if (needs.late && needs.late.length) {
    notes.push(`${needs.late.length} project(s) are past their end date; their remaining work is spread over the next ${needs.rules.late_spread_weeks} weeks.`);
  }
  if (needs.unstaffed && needs.unstaffed.length) {
    notes.push(`${needs.unstaffed.length} project(s) have work left and nobody booking to them.`);
  }
  if (needs.drawings && needs.drawings.drafting_hours_per_drawing) {
    notes.push(`The drawing office's share is drawings left at ${fmt.hours(needs.drawings.drafting_hours_per_drawing)} h a drawing, this unit's own rate.`);
  }
  notes.push(`Ask ${needs.rules.lead_weeks} weeks before somebody is needed. Timesheets run to ${dateText(needs.data_through)}.`);
  return el('p', { class: 'muted small' }, notes.join(' '));
}

/* -- who has what -------------------------------------------------------- */

function whoHasWhat(data) {
  const trying = plan.moves.length > 0;
  const people = data.people.filter((p) => plan.team === 'all'
    || (p.team_id || '__none__') === plan.team);
  const groups = new Map();
  for (const person of people) {
    const key = person.team_id || '__none__';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(person);
  }
  const teamOf = new Map(data.teams.map((t) => [t.id, t]));

  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, `Who has what, ${dateText(data.from)} to ${dateText(data.to)}`),
        el('p', { class: 'muted' },
          `Each person at the pace their timesheets set from ${dateText(data.pace_from)} to ${dateText(data.pace_to)}, `
          + 'with their open tasks where those need more. '
          + (trying ? 'The faint bar is before the handovers you are trying, the solid one after.'
            : 'Open someone to hand some of their work to somebody else.'))),
      el('span', { class: 'legend' },
        ...[['ok', 'full'], ['warn', 'has room'], ['bad', 'over']].map(([key, text]) =>
          el('span', { class: 'legend-item' }, el('span', { class: `swatch plan-swatch-${key}` }), text)))),
    people.length
      ? [...groups.entries()].map(([key, members]) => {
          const team = teamOf.get(key) || {};
          return el('div', { class: 'plan-team' },
            groups.size > 1 || key !== '__none__'
              ? el('div', { class: 'plan-team-head' },
                  el('b', {}, team.name || 'Not in a team'),
                  el('span', { class: 'muted' },
                    ` ${members.length} people · ${fmt.pct0(team.after_load)} of their hours`
                    + (trying && team.before_load !== team.after_load ? ` (was ${fmt.pct0(team.before_load)})` : '')
                    + (team.drawings_after ? ` · ${fmt.int(Math.round(team.drawings_after))} drawings in hand` : '')))
              : null,
            members.sort((a, b) => (b.after.load || 0) - (a.after.load || 0)).map(personRow));
        })
      : el('div', { class: 'empty' }, 'Nobody has booked any project time in the newest timesheets.'));
}

function personRow(person) {
  const trying = plan.moves.length > 0;
  const changed = trying && Math.abs(person.before.hours - person.after.hours) > 0.05;
  const scale = 1.5;                  // the bar runs to 150% of a full load
  const width = (load) => `${Math.min(100, ((load || 0) / scale) * 100)}%`;
  const open = plan.open.has(person.name);
  const toggle = () => {
    if (open) plan.open.delete(person.name); else plan.open.add(person.name);
    renderPlanner();
  };
  return el('div', { class: `plan-person ${open ? 'is-open' : ''}` },
    el('button', { class: 'plan-row', type: 'button', onclick: toggle, 'aria-expanded': String(open) },
      el('span', { class: 'plan-name' },
        el('b', {}, person.name),
        el('span', { class: 'muted small' }, ` ${person.grade_label}`)),
      el('span', { class: 'plan-track' },
        changed ? el('span', { class: 'plan-ghost', style: `width:${width(person.before.load)}` }) : null,
        el('span', { class: `plan-fill plan-${loadTone(person.after.load)}`, style: `width:${width(person.after.load)}` }),
        el('span', { class: 'plan-full', style: `left:${(1 / scale) * 100}%`, title: 'A full load' })),
      el('span', { class: 'plan-figure' },
        el('b', { class: `v-${loadTone(person.after.load)}` }, fmt.pct0(person.after.load)),
        changed ? el('span', { class: 'muted small' }, ` was ${fmt.pct0(person.before.load)}`) : null,
        el('span', { class: 'muted small' }, ` · ${fmt.hours(person.after.hours)} h`
          + (person.after.drawings ? ` · ${fmt.int(Math.round(person.after.drawings))} dwg` : ''))),
      el('span', { class: 'chevron' }, open ? '▾' : '›')),
    open ? personWork(person) : null);
}

function personWork(person) {
  const trying = plan.moves.length > 0;
  if (!person.items.length) {
    return el('div', { class: 'plan-work muted' }, 'Nothing booked lately and no tasks due.');
  }
  return el('div', { class: 'plan-work' }, el('div', { class: 'table-wrap' }, el('table', { 'data-plain': '' },
    el('thead', {}, el('tr', {},
      el('th', {}, 'Work'), el('th', { class: 'num' }, 'Hours a day'),
      el('th', { class: 'num' }, 'Hours'), el('th', { class: 'num' }, 'Drawings in hand'),
      el('th', {}, ''))),
    el('tbody', {}, person.items.map((item) => el('tr', {},
      el('td', { class: 'wide' }, item.project ? el('span', { class: 'code' }, `${item.project} `) : null,
        item.name !== item.project ? item.name : '',
        item.task_hours ? el('span', { class: 'muted small' }, ` · ${fmt.hours(item.task_hours)} h of tasks`) : null),
      el('td', { class: 'num' }, item.pace_after ? fmt.hours(item.pace_after) : '—'),
      el('td', { class: 'num' }, trying && item.hours_before !== item.hours_after
        ? `${fmt.hours(item.hours_before)} → ${fmt.hours(item.hours_after)}` : fmt.hours(item.hours_after)),
      el('td', { class: 'num' }, item.drawings_after || item.drawings_before
        ? (trying && item.drawings_before !== item.drawings_after
          ? `${fmt.int(Math.round(item.drawings_before))} → ${fmt.int(Math.round(item.drawings_after))}`
          : fmt.int(Math.round(item.drawings_after))) : '—'),
      el('td', {}, item.hours_after > 0
        ? el('button', { class: 'btn btn-sm', type: 'button', onclick: () => openHandover(person, item) },
          'Hand over')
        : null)))))));
}

function openHandover(person, item) {
  const data = plan.data;
  const tasks = (data.open_tasks || []).filter((t) => item.tasks.includes(t.id)
    && t.assignees.includes(person.name));
  const what = [];
  if (item.project && item.pace_after > 0) {
    what.push({ value: 'pace', label: `A share of their time on ${item.project} (${fmt.hours(item.pace_after)} h a day)` });
  }
  for (const task of tasks) {
    what.push({ value: `task:${task.id}`, label: `Task: ${task.name} (${fmt.hours(task.hours_each)} h, due ${shortDate(task.due)})` });
  }
  if (!what.length) { toast('Nothing here can be handed over.'); return; }
  // Like for like first: an engineer's work to engineers, drawings to draftsmen.
  const others = data.people.filter((p) => p.name !== person.name)
    .sort((a, b) => (a.role !== person.role) - (b.role !== person.role)
      || (a.after.load || 0) - (b.after.load || 0));
  openModal(`Hand over some of ${person.name}'s work`, [
    { name: 'what', label: 'What', type: 'select', options: what, full: true },
    { name: 'to', label: 'To', type: 'select', full: true, options: others.map((p) => ({
      value: p.name,
      label: `${p.name} — ${fmt.pct0(p.after.load)} loaded${p.team_name ? `, ${p.team_name}` : ''}`
        + (p.role !== person.role ? ` (${(ROLE_LABEL[p.role] || '').toLowerCase().replace(/s$/, '')})` : ''),
    })) },
    { name: 'share', label: 'How much of it', type: 'select', hint: 'for a share of their time',
      options: [{ value: '0.25', label: 'A quarter' }, { value: '0.5', label: 'Half' },
        { value: '0.75', label: 'Three quarters' }, { value: '1', label: 'All of it' }], value: '0.5' },
  ], async () => {
    const values = modalValues();
    const move = values.what === 'pace'
      ? { kind: 'project', project: item.project, from: person.name, to: values.to, share: Number(values.share) }
      : { kind: 'task', task_id: Number(values.what.split(':')[1]), from: person.name, to: values.to };
    const next = plan.moves.concat([move]);
    // Checked by the server before the modal closes, so a bad move is
    // explained where it was made.
    const data2 = await api('/api/planner', { method: 'POST', body: { days: plan.days, moves: next } });
    plan.moves = next;
    plan.data = data2;
    plan.open.add(values.to);
    renderPlanner();
  });
}

/* -- the handovers ------------------------------------------------------ */

function moveText(move) {
  if (move.kind === 'extra') return `New work "${move.project}" for ${move.to}, ${fmt.hours(move.hours)} h`;
  if (move.kind === 'task') return `Task "${move.name}" from ${move.from} to ${move.to}`;
  const share = move.share >= 0.999 ? 'All' : `${Math.round(move.share * 100)}%`;
  return `${share} of ${move.from}'s time on ${move.project}${move.name && move.name !== move.project ? ` (${move.name})` : ''} to ${move.to}`;
}

function movesPanel(data) {
  const trying = data.moves || [];
  const saved = data.saved || [];
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, 'Handovers'),
        el('p', { class: 'muted' },
          'Try a handover and every figure above shows its effect. Nothing changes until you commit: '
          + `a share of a project is then kept until ${dateText(data.to)} and lapses by itself; a task is simply reassigned.`)),
      el('div', { class: 'row-actions' },
        el('button', { class: 'btn btn-sm', type: 'button', onclick: suggestMoves }, 'Suggest handovers'),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: () => tryNewWork(data) }, 'Try new work'),
        trying.length ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => tryMoves([]) }, 'Clear') : null,
        trying.length ? el('button', { class: 'btn btn-sm', type: 'button', onclick: keepWhatIf }, 'Keep as a what-if') : null,
        trying.length && !trying.some((m) => m.kind === 'extra')
          ? el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: commitMoves },
            `Commit ${trying.length}`) : null)),
    trying.length
      ? el('ul', { class: 'plan-moves' }, trying.map((move, i) => el('li', {},
          el('span', {}, moveText(move)),
          el('span', { class: 'muted small' }, ` · ${fmt.hours(move.hours)} h`),
          el('button', { class: 'btn btn-sm btn-ghost', type: 'button', title: 'Take this one out',
            onclick: () => tryMoves(plan.moves.filter((_m, j) => j !== i)) }, '✕'))))
      : el('p', { class: 'muted' }, 'None being tried. Open someone above and hand over part of their work, or let the app suggest.'),
    saved.length ? el('div', {},
      el('h4', {}, 'In force'),
      el('ul', { class: 'plan-moves' }, saved.map((move) => el('li', {},
        el('span', {}, moveText(move)),
        el('span', { class: 'muted small' }, ` · ${shortDate(move.start)} to ${shortDate(move.end)}`),
        el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => undoSaved(move) }, 'Undo')))))
      : null);
}

/* -- what-ifs kept to compare ------------------------------------------- */

function tryNewWork(data) {
  const people = data.people.filter((p) => p.capacity || p.after.hours).map((p) => p.name);
  openModal('Try new work', [
    { name: 'project', label: 'What is it', placeholder: 'e.g. New berth, tender' },
    { name: 'to', label: 'Who would do it', type: 'select', options: people },
    { name: 'hours', label: `Hours over the next ${plan.days} working days`, type: 'number', min: 1, step: 1 },
  ], async () => {
    // The modal's Save calls this with nothing: the values are read here.
    const values = modalValues();
    const move = { kind: 'extra', project: String(values.project || '').trim(),
      to: values.to, hours: Number(values.hours) };
    if (!move.project || !move.hours) {
      // Thrown, so the modal stays open with the message in it.
      throw new Error('Say what the work is and roughly how many hours.');
    }
    closeModal();
    await tryMoves([...plan.moves, move]);
  }, { to: people[0], hours: 20 });
}

function keepWhatIf() {
  openModal('Keep this as a what-if', [
    { name: 'name', label: 'Name it', placeholder: 'e.g. Berth tender comes in, Kirolos helps' },
  ], async () => {
    // A refusal is thrown on to the modal's Save, which shows it and keeps
    // the modal open; caught here, the modal closed over it.
    const values = modalValues();
    await api('/api/what-ifs', { method: 'POST',
      body: { name: values.name, days: plan.days, moves: plan.moves } });
    closeModal();
    toast('Kept. Compare it with the others under What-ifs.', 'ok');
    plan.whatIfs = null;
    await loadPlanner({ quiet: true });
  });
}

async function removeWhatIf(item) {
  if (!window.confirm(`Delete the what-if "${item.name}"?`)) return;
  try {
    await api(`/api/what-ifs/${item.id}`, { method: 'DELETE' });
    plan.whatIfs = null;
    renderPlanner();
  } catch (error) {
    toastError(error);
  }
}

function whatIfPanel(data) {
  const host = el('section', { class: 'panel' });
  const draw = (list) => {
    const now = data.summary;
    const baseline = { over: now.over_before, room: now.room_before, peak: now.peak_before };
    const rows = list.what_ifs.map((w) => {
      const s = w.summary || {};
      return el('tr', {},
        el('td', {}, el('b', {}, w.name),
          el('div', { class: 'muted small' }, w.stale ? (w.errors || []).join(' ')
            : w.moves.map(moveText).join('; '))),
        el('td', { class: 'num' }, w.stale ? '—' : String(s.over_after)),
        el('td', { class: 'num' }, w.stale ? '—' : String(s.room_after)),
        el('td', { class: 'num' }, w.stale ? '—' : fmt.pct0(s.peak_after)),
        el('td', { class: 'num' }, w.stale ? '—' : fmt.hours(s.hours)),
        el('td', {}, el('div', { class: 'wi-actions' },
          w.stale ? null : el('button', { class: 'btn btn-sm', type: 'button', onclick: () => {
            plan.days = w.days;
            tryMoves(w.moves.map((m) => ({ ...m })));
          } }, 'Open'),
          el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => removeWhatIf(w) }, 'Delete'))));
    });
    setChildren(host,
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'What-ifs'),
          el('p', { class: 'muted' },
            'Try handovers or new work below, then keep it as a what-if to compare. '
            + 'Each one is worked out again from today\u2019s figures every time you look.'))),
      list.what_ifs.length
        ? el('div', { class: 'table-wrap' }, el('table', { class: 'wi-table' },
          el('thead', {}, el('tr', {}, el('th', {}, 'What-if'), el('th', { class: 'num' }, 'Over a full load'),
            el('th', { class: 'num' }, 'With room'), el('th', { class: 'num' }, 'Busiest'),
            el('th', { class: 'num' }, 'Hours of work'), el('th', {}, ''))),
          el('tbody', {},
            el('tr', { class: 'muted' }, el('td', {}, 'As things are'),
              el('td', { class: 'num' }, String(baseline.over)), el('td', { class: 'num' }, String(baseline.room)),
              el('td', { class: 'num' }, fmt.pct0(baseline.peak)), el('td', { class: 'num' }, ''), el('td', {}, '')),
            ...rows)))
        : el('p', { class: 'muted' }, 'None kept yet. "Try new work" or hand work over, then "Keep as a what-if".'));
  };
  if (plan.whatIfs) draw(plan.whatIfs);
  else {
    setChildren(host, el('div', { class: 'empty' }, 'Loading what-ifs\u2026'));
    api('/api/what-ifs', { quiet: true }).then((list) => { plan.whatIfs = list; draw(list); })
      .catch(() => setChildren(host, el('p', { class: 'muted' }, 'What-ifs could not be loaded.')));
  }
  return host;
}

/* -- drawings ---------------------------------------------------------- */

function drawingsPanel(drawings) {
  if (!drawings) return null;
  if (!drawings.known) {
    return el('section', { class: 'panel' },
      el('h3', {}, 'Drawings'),
      el('p', { class: 'muted' },
        'No deliverable has a drawing count yet. It is the one number the timesheets do not carry: '
        + 'open a project on Projects and type how many drawings each deliverable is. '
        + 'Done, left, drawings per person and team, and the hours a drawing takes are all worked out from it.'));
  }
  return el('section', { class: 'panel' },
    el('h3', {}, 'Drawings'),
    el('p', { class: 'muted' },
      'Done is each deliverable’s drawings times how far along it is; a person’s are their share of each deliverable.'),
    kpiCards([
      ['Drawings', fmt.int(drawings.total), 'on deliverables with a count'],
      ['Done', fmt.int(Math.round(drawings.done)), fmt.pct0(drawings.total ? drawings.done / drawings.total : null)],
      ['Left', fmt.int(Math.round(drawings.left)), 'still to produce'],
      ['Hours a drawing', drawings.hours_per_drawing === null ? '—' : fmt.hours(drawings.hours_per_drawing),
        drawings.hours_per_drawing === null
          ? 'measured once a project with drawings is confirmed'
          : drawings.drafting_hours_per_drawing
            ? `${fmt.hours(drawings.drafting_hours_per_drawing)} of them drafting` : 'all hours on confirmed projects'],
    ]),
    el('div', { class: 'split split-even' },
      el('div', {},
        el('h4', {}, 'By team and person'),
        table(['Who', 'Team', 'Done', 'Left'],
          drawings.people.map((p) => ({ cells: [p.name, p.team_name || '—',
            fmt.int(Math.round(p.done)), fmt.int(Math.round(p.left))] })),
          { numeric: [2, 3] })),
      el('div', {},
        el('h4', {}, 'By project'),
        table(['Project', 'Drawings', 'Done', 'Left', 'h / drawing'],
          drawings.projects.map((p) => ({ cells: [
            `${p.number}${p.name && p.name !== p.number ? ` ${p.name}` : ''}`,
            fmt.int(p.total), fmt.int(Math.round(p.done)), fmt.int(Math.round(p.left)),
            p.hours_per_drawing === null ? '—' : fmt.hours(p.hours_per_drawing)] })),
          { numeric: [1, 2, 3, 4] }))));
}

/* -- the Overview's share of it ------------------------------------------ */

async function overviewNeeds() {
  const host = $('#overview-needs');
  if (!host) return;
  try {
    plan.needs = await api('/api/needs');
  } catch {
    host.hidden = true;
    return;
  }
  const needs = plan.needs;
  const asks = needs.alerts.filter((a) => a.kind === 'need');
  const room = needs.alerts.filter((a) => a.kind === 'room');
  const d = needs.drawings || {};
  host.hidden = false;
  setChildren(host,
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, 'Staffing ahead'),
        el('p', { class: 'muted' }, asks.length
          ? `${asks.length} team(s) should ask for more people. The Planner shows the weeks, and can move work between people first.`
          : `No team needs more people before ${shortDate(needs.horizon_end)}.`)),
      el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => { plan.view = 'people'; switchView('planner'); } }, 'See the weeks')),
    el('div', { class: 'findings' },
      [...asks, ...room].slice(0, 4).map((a) => el('div', {
        class: `finding finding-${a.severity === 'now' ? 'bad' : a.severity === 'soon' ? 'warn' : 'ok'}`,
      }, el('b', {}, dayFirstText(a.title)), el('p', { class: 'muted' }, dayFirstText(a.detail)))),
      d.known ? el('div', { class: 'finding' },
        el('b', {}, `Drawings: ${fmt.int(Math.round(d.done))} of ${fmt.int(d.total)} done`),
        el('p', { class: 'muted' }, `${fmt.int(Math.round(d.left))} left`
          + (d.hours_per_drawing ? `, at ${fmt.hours(d.hours_per_drawing)} h a drawing so far` : '')
          + (d.deliverables_without ? `. ${d.deliverables_without} deliverable(s) have no count yet.` : '.')))
        : el('div', { class: 'finding' },
          el('b', {}, 'Drawings'),
          el('p', { class: 'muted' }, 'Upload the team\'s drawing list on Projects (or give each deliverable its count), and done, left and hours a drawing follow everywhere.'))));
}

/* -- today ------------------------------------------------------------- */

const KIND_LABEL = { request: 'Request', submission: 'Submission', meeting: 'Meeting',
  management: 'Team', development: 'Development', task: 'Task', work: '' };

/** A meeting's agenda, folded away under it until it is wanted. */
function agendaList(b) {
  if (!b.agenda || !b.agenda.length) return null;
  return el('details', { class: 'block-agenda' },
    el('summary', {}, `Agenda · ${b.agenda.length}`),
    el('ul', {}, b.agenda.map((line) => el('li', {}, line))));
}

function isoDay(date) {
  const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 10);
}

function shiftDay(iso, days) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return isoDay(d);
}

/** Something changed the days: the forecast is worked out again and the day redrawn. */
async function replanDay() {
  plan.needs = null;
  await loadDay({ quiet: true });
}

async function loadDay({ quiet = false } = {}) {
  const params = new URLSearchParams({ span: plan.span });
  if (plan.date) params.set('date', plan.date);
  try {
    plan.dayData = await api(`/api/day?${params}`, { quiet });
    renderDay();
  } catch (error) {
    if (!quiet) toastError(error);
    return;
  }
  if (!plan.calendars) refreshCalendars();
  if (!plan.meetings) loadMeetings();
}

/* -- meetings typed in --------------------------------------------------- */

async function loadMeetings() {
  try {
    const [list, me] = await Promise.all([api('/api/meetings', { quiet: true }),
      api('/api/team/me', { quiet: true }).catch(() => ({ me: '' }))]);
    plan.meetings = list;
    plan.me = me.me || '';
    renderDay();
  } catch (error) { /* the panel waits for the next load */ }
}

async function addMeeting(body) {
  try {
    await api('/api/meetings', { method: 'POST', body });
  } catch (error) {
    toastError(error);
    return false;
  }
  toast(`Added. ${body.people.length === 1 ? 'Their' : 'Everyone\'s'} day now keeps that time.`, 'ok');
  plan.meetings = null;
  await replanDay();
  return true;
}

async function removeMeeting(m) {
  try {
    await api(`/api/meetings/${m.id}/remove`, { method: 'POST' });
  } catch (error) { toast(error.message, 'bad'); return; }
  plan.meetings = null;
  await replanDay();
}

function meetingsPanel(data) {
  const list = plan.meetings;
  if (!list) return null;
  return el('section', { class: 'panel meet-panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, list.meetings.length ? `Meetings (${list.meetings.length} coming up)` : 'Meetings'),
        el('p', { class: 'muted small' }, 'Client, other trades and internal meetings. Put one in once, with who goes; it comes off their free time, the Planner and the Forecast.')),
      el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => { plan.meetingsOpen = !plan.meetingsOpen; renderDay(); } },
      plan.meetingsOpen ? 'Close' : 'Add a meeting')),
    plan.meetingsOpen ? meetingForm({ day: data.date, people: list.people,
      ticked: plan.me ? [plan.me] : [], add: addMeeting }) : null,
    meetingList(list.meetings.slice(0, plan.meetingsAll ? 200 : 6), { remove: removeMeeting }),
    list.meetings.length > 6 ? el('button', { class: 'linkish', type: 'button',
      onclick: () => { plan.meetingsAll = !plan.meetingsAll; renderDay(); } },
    plan.meetingsAll ? 'Show fewer' : `Show all ${list.meetings.length}`) : null);
}

/* -- Outlook meetings ------------------------------------------------------ */

/** Read the linked calendars that are due (the server keeps each fresh for a
    while), and redraw the day when a meeting came or went. */
async function refreshCalendars(force = false) {
  try {
    const result = await api('/api/calendars/refresh', { method: 'POST', body: { force }, quiet: !force });
    plan.calendars = result;
    if (result.result && result.result.changed) {
      await replanDay();
    } else {
      renderDay();
    }
  } catch (error) {
    if (force) toastError(error);
  }
}

async function saveCalendar(person, link) {
  try {
    plan.calendars = await api('/api/calendars', { method: 'PUT', body: { person, link } });
  } catch (error) {
    toastError(error);
    return;
  }
  const now = plan.calendars.people.find((p) => p.person === person) || {};
  toast(now.problem || `${person}'s meetings are in the plan.`, now.problem ? 'bad' : 'ok');
  await replanDay();
}

async function unlinkCalendar(person) {
  try {
    plan.calendars = await api('/api/calendars/remove', { method: 'POST', body: { person } });
  } catch (error) {
    toastError(error);
    return;
  }
  toast(`${person}'s Outlook meetings are off the plan.`, 'ok');
  await replanDay();
}

function calendarPanel() {
  const cal = plan.calendars;
  // Only once somebody has a calendar link in: where Outlook cannot publish,
  // meetings are put in by hand above.
  if (!cal || !cal.linked) return null;
  const people = cal.people || [];
  const problems = people.filter((p) => p.linked && p.problem);
  const hours = people.reduce((sum, p) => sum + (p.linked ? p.hours_next_7_days : 0), 0);
  return el('section', { class: 'panel cal-panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, 'Outlook meetings'),
        el('p', { class: 'muted small' },
          `${cal.linked} of ${people.length} people linked · ${fmt.hours(hours)} h of meetings in the next 7 days, already off their free time.`,
          problems.length ? ` ${problems.length} could not be read.` : '')),
      el('div', { class: 'plan-nav' },
        el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => refreshCalendars(true) }, 'Read now'),
        el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => { plan.calendarsOpen = !plan.calendarsOpen; renderDay(); } },
        plan.calendarsOpen ? 'Close' : 'Link calendars'))),
    plan.calendarsOpen ? el('div', {},
      el('p', { class: 'muted small' }, 'Each person does this once on their own Outlook, then pastes the link in My day, or sends it to you to paste here.'),
      calendarSteps(),
      el('p', { class: 'muted small' }, CALENDAR_NOTE),
      el('ul', { class: 'request-list' }, people.map((p) => el('li', { class: 'request cal-person' },
        el('span', { class: 'request-what' },
          el('b', {}, p.person),
          el('span', { class: `muted small${p.problem ? ' cal-problem' : ''}` },
            p.linked ? ` · ${calendarRead(p)}${p.added_by === 'self' ? ' · linked by them' : ''}` : ' · not linked')),
        p.linked
          ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
            onclick: () => unlinkCalendar(p.person) }, 'Unlink')
          : calendarPaste((link) => saveCalendar(p.person, link), 'Save')))))
      : null);
}

/** Whether somebody on the day's plan is in the team chosen above it. The
    day names each person's team (team_name), not its id, so the choice is
    matched by the team's name as well. */
function inChosenTeam(person, data) {
  if (plan.team === 'all') return true;
  if (person.team_id) return person.team_id === plan.team;
  const team = ((data && data.teams) || []).find((t) => t.id === plan.team);
  return Boolean(team) && person.team_name === team.name;
}

/** The last working day of the week ``iso`` is in (Python's weekday numbers
    in ``workDays``: Monday 0 ... Sunday 6), so "this week" means this
    week, Sunday to Thursday or Monday to Friday. On a day off it is the
    end of the coming week. */
function endOfWorkWeek(iso, workDays) {
  const working = new Set(workDays && workDays.length ? workDays : [0, 1, 2, 3, 4]);
  let last = null;
  for (let i = 0; i < 7; i += 1) {
    const day = shiftDay(iso, i);
    const weekday = (new Date(`${day}T00:00:00`).getDay() + 6) % 7;
    if (working.has(weekday)) last = day;
    else if (last) break;
  }
  return last || shiftDay(iso, 6);
}

function renderDay() {
  const data = plan.dayData;
  if (!data || plan.view !== 'today') return;
  fillTeams(data.teams);
  const shown = (people) => people.filter((p) => inChosenTeam(p, data));
  const step = plan.span === 'week' ? 7 : 1;
  const label = plan.span === 'week'
    ? `Week of ${dateText(data.days[0] ? data.days[0].date : data.date)}`
    : (data.date === data.today ? `Today, ${dateText(data.date)}` : dateText(data.date));

  setChildren($('#planner-body'),
    quickAdd(data),
    el('div', { class: 'plan-toolbar' },
      el('div', { class: 'plan-nav' },
        el('button', { class: 'btn btn-sm', type: 'button', title: 'Earlier',
          onclick: () => { plan.date = shiftDay(data.date, -step); loadDay(); } }, '‹'),
        el('b', { class: 'plan-date' }, label),
        el('button', { class: 'btn btn-sm', type: 'button', title: 'Later',
          onclick: () => { plan.date = shiftDay(data.date, step); loadDay(); } }, '›'),
        data.date !== data.today
          ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
              onclick: () => { plan.date = null; loadDay(); } }, 'Today') : null),
      el('div', { class: 'plan-nav' },
        ...[['day', 'Day'], ['week', 'Week']].map(([key, text]) => el('button', {
          class: `subtab ${plan.span === key ? 'is-active' : ''}`, type: 'button',
          onclick: () => { plan.span = key; loadDay(); },
        }, text)),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: () => shareDay(false) }, 'Share'),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: () => shareDay(true) }, 'Print'))),
    requestList(data),
    plan.span === 'week' ? weekTable(data, shown) : dayCards(data.days[0], shown),
    // Meetings and Away side by side, the same height.
    el('div', { class: 'panel-pair' }, meetingsPanel(data), awayPanel(data)),
    calendarPanel());
}

/* -- who is away ---------------------------------------------------------- */

const AWAY_SOURCE = { typed: '', timesheet: 'from their timesheet', workbook: 'unit calendar',
  holiday: 'public holiday' };
const WEEKDAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function weekText(days) {
  if (!days || !days.length) return '';
  // Written from the first day of the run, so Sunday to Thursday reads as such.
  const order = [6, 0, 1, 2, 3, 4, 5];
  const sorted = order.filter((d) => days.includes(d));
  const startsSunday = days.includes(6) && !days.includes(5);
  const list = startsSunday ? sorted : sorted.filter((d) => d !== 6).concat(days.includes(6) ? [6] : []);
  return `${WEEKDAY[list[0]]}–${WEEKDAY[list[list.length - 1]]}`;
}

async function saveHolidays(body, message) {
  try {
    const result = await api('/api/holidays', { method: 'PUT', body });
    if (result.save) markSaved(result.save);
    if (message) toast(message, 'ok');
    await replanDay();
    return result;
  } catch (error) {
    toastError(error);
    return null;
  }
}

/** Public holidays: the unit's country, chosen once, and a team elsewhere. */
async function openHolidays() {
  let view;
  try { view = await api('/api/holidays'); } catch (error) {
    toastError(error); return;
  }
  const options = [{ value: '', label: 'None' },
    ...view.countries.map((c) => ({ value: c.code, label: c.name }))];
  const fields = [{ name: 'unit', label: 'The unit keeps the holidays of', type: 'select',
    options, full: true, value: view.unit || '' }];
  for (const team of view.teams) {
    fields.push({ name: `team:${team.id}`, label: `${team.name}`, type: 'select',
      hint: 'only if it is somewhere else',
      options: [{ value: '', label: 'Same as the unit' }, ...options.slice(1)], value: team.country });
  }
  fields.push({ name: 'use_week', label: 'Working week', type: 'select', full: true,
    options: [{ value: '', label: `Keep ${weekText(view.work_days)}` },
      { value: '1', label: 'Use the country\'s own working week' }] });
  if (view.off.length) {
    fields.push({ name: 'restore', label: 'Days taken off the built-in list', type: 'select', full: true,
      hint: view.off.map(shortDate).join(', '),
      options: [{ value: '', label: 'Keep them off' }, { value: '1', label: 'Put them back' }] });
  }
  openModal('Public holidays', fields, async () => {
    const values = modalValues();
    const teams = {};
    for (const team of view.teams) teams[team.id] = values[`team:${team.id}`] || '';
    const result = await api('/api/holidays', { method: 'PUT', body: {
      unit: values.unit || '', teams, use_week: Boolean(values.use_week),
      restore: Boolean(values.restore) } });
    if (result.save) markSaved(result.save);
    toast(result.holidays.unit ? `Public holidays: ${result.holidays.unit_name}.` : 'No public holidays.', 'ok');
    await replanDay();
  });
}

/** Asked once, until somebody answers: whose public holidays to keep. */
function holidayPrompt(data) {
  const h = data.holidays;
  if (!h || h.chosen) return null;
  const choices = (h.countries || []).map((c) => el('option', { value: c.code }, c.name));
  const pick = el('select', { 'aria-label': 'Country' }, el('option', { value: '' }, 'Choose a country'), ...choices);
  if (h.unit) pick.value = h.unit;
  const week = el('input', { type: 'checkbox', checked: true });
  return el('div', { class: 'holiday-prompt' },
    el('span', {}, h.unit ? `Public holidays look like ${h.unit_name}'s.` : 'Which country\'s public holidays does this unit keep?'),
    pick,
    el('label', { class: 'check-chip' }, week, el('span', {}, 'and its working week')),
    el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: () => {
      if (!pick.value) { pick.focus(); return; }
      saveHolidays({ unit: pick.value, use_week: week.checked },
        `Public holidays: ${pick.options[pick.selectedIndex].text}.`);
    } }, h.unit ? 'Yes' : 'Use'),
    el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => openHolidays() },
      'Teams elsewhere…'));
}


function awayWhen(a) {
  return a.start === a.end ? shortDate(a.start) : `${shortDate(a.start)} – ${shortDate(a.end)}`;
}

function awayText(a) {
  return `${a.person === '*' ? 'Everybody' : a.person} · ${awayWhen(a)}`;
}

/** One line in: who, from, to. Everybody is a public holiday. */
function markAway(data, name) {
  const people = data.people.map((p) => ({ value: p.name, label: p.name }));
  openModal('Away', [
    { name: 'person', label: 'Who', type: 'select', full: true,
      options: [{ value: '*', label: 'Everybody — a public holiday' }, ...people] },
    { name: 'start', label: 'From', type: 'date' },
    { name: 'end', label: 'To', type: 'date', hint: 'blank for one day' },
    { name: 'note', label: 'Why', placeholder: 'Leave, site visit, course…', full: true },
  ], async () => {
    const values = modalValues();
    const result = await api('/api/absences', { method: 'POST', body: values });
    toast(`${awayText(result)} is off the plan.`, 'ok');
    await replanDay();
  }, { person: name || '*', start: data.date, end: '' });
}

function awayPanel(data) {
  const away = data.away || [];
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, away.length ? `Away (${away.length} coming up)` : 'Away'),
        data.holidays && data.holidays.chosen ? el('p', { class: 'muted small' },
          data.holidays.unit ? `Public holidays: ${data.holidays.unit_name}` : 'No public holidays chosen',
          ...(data.holidays.teams || []).filter((t) => t.country).map((t) =>
            `; ${t.name}: ${(data.holidays.countries.find((c) => c.code === t.country) || {}).name || t.country}`),
          '. ',
          el('button', { class: 'linkish', type: 'button', onclick: () => openHolidays() }, 'Change')) : null),
      el('button', { class: 'btn btn-sm', type: 'button', onclick: () => markAway(data) },
        'Someone is away')),
    holidayPrompt(data),
    away.length ? el('ul', { class: 'request-list' }, away.map((a) => el('li', { class: 'request' },
      el('span', { class: 'request-time' }, awayWhen(a)),
      el('span', { class: 'request-what' },
        el('b', {}, a.source === 'holiday' ? a.note : (a.person === '*' ? 'Everybody' : a.person)),
        el('span', { class: 'muted small' },
          (a.source === 'holiday' ? [a.where, AWAY_SOURCE.holiday] : [a.note, AWAY_SOURCE[a.source]])
            .filter(Boolean).map((t) => ` · ${t}`).join(''))),
      a.source === 'holiday' ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
        title: 'Announced for another day? Take this one off, and add the right day for everybody.',
        onclick: () => saveHolidays({ skip: a.dates }, `${a.note} is off the plan.`) }, 'Not a holiday')
      : a.id ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: async () => {
        try {
          await api(`/api/absences/${a.id}/remove`, { method: 'POST' });
          await replanDay();
        } catch (error) { toastError(error); }
      } }, 'Remove') : el('span'))))
      : el('p', { class: 'muted small' },
        'Leave booked on timesheets shows here by itself. Add anything else, or a public holiday, so nobody is planned on a day they are not in.'));
}

function quickAdd(data) {
  const title = el('input', { type: 'text', placeholder: 'What came in? e.g. Check the RFI on piles',
    'aria-label': 'What came in', class: 'grow', spellcheck: 'true' });
  const hours = el('select', { 'aria-label': 'Roughly how long' },
    [['0.5', '½ h'], ['1', '1 h'], ['2', '2 h'], ['4', '½ day'], ['8.5', '1 day']].map(
      ([value, text]) => el('option', { value }, text)));
  hours.value = '1';
  const due = el('select', { 'aria-label': 'Wanted by' },
    el('option', { value: data.today }, 'today'),
    el('option', { value: shiftDay(data.today, 1) }, 'tomorrow'),
    el('option', { value: endOfWorkWeek(data.today, (data.holidays || {}).work_days) }, 'this week'));
  const who = el('select', { 'aria-label': 'Who' },
    el('option', { value: 'engineering' }, 'Engineer with room'),
    el('option', { value: 'drafting' }, 'Draftsman with room'),
    ...data.people.filter((p) => data.engineers.includes(p.name)).map((p) =>
      el('option', { value: `person:${p.name}` }, p.name)));
  const project = el('select', { 'aria-label': 'Project' },
    el('option', { value: '' }, 'No project'),
    ...data.projects.map((p) => el('option', { value: p.number },
      p.name && p.name !== p.number ? `${p.number} ${p.name}` : p.number)));
  const urgency = el('select', { 'aria-label': 'How urgent' },
    el('option', { value: 'urgent' }, 'Urgent: start now'),
    el('option', { value: 'room' }, 'When there is room'));
  const bodyOf = (extra = {}) => {
    const choice = who.value;
    return {
      title: title.value.trim(), hours: Number(hours.value), due: due.value,
      project_number: project.value, urgency: urgency.value,
      role: choice.startsWith('person:') ? 'engineering' : choice,
      person: choice.startsWith('person:') ? choice.slice(7) : '',
      now: (() => { const d = new Date(); return `${isoDay(d)}T${d.toTimeString().slice(0, 5)}`; })(),
      ...extra,
    };
  };
  let adding = false;
  const add = async (extra = {}) => {
    if (!title.value.trim()) { title.focus(); return; }
    // A second tap (or Enter) while the first is on its way would add it twice.
    if (adding) return;
    adding = true;
    try {
      const result = await api('/api/requests', { method: 'POST', body: bodyOf(extra) });
      if (result.save) markSaved(result.save);
      toast(`${result.person}, ${slotText(result.start, result.end)}`
        + (result.late ? ' — later than wanted' : ''), result.late ? 'bad' : 'ok');
      title.value = '';
      plan.needs = null;
      if (state.tasks) state.tasks = null;
      closeModal();
      await loadDay({ quiet: true });
    } catch (error) {
      toastError(error);
    } finally {
      adding = false;
    }
  };
  const preview = async () => {
    if (!title.value.trim()) { title.focus(); return; }
    try {
      const view = await api('/api/requests/preview', { method: 'POST', body: bodyOf() });
      showPushes(view, add);
    } catch (error) {
      toastError(error);
    }
  };
  title.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  return el('div', { class: 'quick-add' },
    title,
    el('div', { class: 'quick-add-options' }, hours, due, who, project, urgency,
      el('button', { class: 'btn', type: 'button', onclick: preview,
        title: 'See what it pushes back and what it costs before adding it' }, 'What does it push?'),
      el('button', { class: 'btn btn-primary', type: 'button', onclick: () => add() }, 'Add')));
}

/* -- what a request pushes, before it is added ----------------------------- */

function pushedList(option) {
  if (option.nothing) return null;
  return el('ul', { class: 'pr-list' }, option.pushed.map((p) => el('li', {},
    p.kind === 'task'
      ? el('span', { class: `pill ${p.late ? 'pill-bad' : 'pill-ok'}` },
        p.late ? `Late by ${p.days_late} day${p.days_late === 1 ? '' : 's'}` : 'Still on time')
      : el('span', { class: 'pill pill-warn' }, 'Slips'),
    el('span', { class: 'pr-what' },
      `${fmt.hours(p.hours)} h of `, el('b', {}, p.title),
      el('span', { class: 'muted small' },
        p.kind === 'task'
          ? `${p.job ? ` · ${p.job}` : ''}${p.due ? ` · due ${dateText(p.due)}` : ''}`
            + `${p.late_until ? `, done about ${dateText(p.late_until)}` : ''}`
          : p.kind === 'job' ? ` · ${p.job} project work moves later` : '')))));
}

function pushOption(option, { heading, best, onAdd }) {
  const tone = option.nothing ? 'is-ok' : option.late_tasks ? 'is-bad' : '';
  const cost = [];
  if (option.pushed_hours) {
    cost.push(`${fmt.hours(option.pushed_hours)} h of planned work`
      + (option.pushed_mm ? ` (${option.pushed_mm.toFixed(2)} man-months)` : ''));
  }
  if (option.overtime_hours) cost.push(`or ${fmt.hours(option.overtime_hours)} h of overtime to keep it all on time`);
  return el('div', { class: `ur-option ${best ? 'is-best' : ''}` },
    el('h4', {}, heading, best ? el('span', { class: 'pill pill-ok' }, 'Costs least') : null),
    el('div', { class: 'muted small' },
      `${option.person} · ${slotText(option.start, option.end)}`
      + (option.late ? ' · later than wanted' : '')),
    el('p', { class: `ur-verdict ${tone}` }, option.verdict),
    cost.length ? el('p', { class: 'small' }, `Cost: ${cost.join(', ')}.`) : null,
    pushedList(option),
    el('div', { class: 'ur-foot' },
      el('button', { class: 'btn btn-primary btn-sm', type: 'button', onclick: onAdd }, 'Add it this way')));
}

function showPushes(view, add) {
  const options = [
    { option: view.urgent, heading: `Urgent, ${view.urgent.person}`,
      body: { person: view.urgent.person, urgency: 'urgent' } },
    { option: view.room, heading: `When ${view.room.person} has room`,
      body: { person: view.room.person, urgency: 'room' } },
    ...view.others.map((o) => ({ option: o, heading: `Urgent, ${o.person} instead`,
      body: { person: o.person, urgency: 'urgent' } })),
  ];
  // Cheapest: on time first, then the fewest hours pushed.
  const score = (o) => (o.late ? 1000 : 0) + o.late_tasks * 100 + o.pushed_hours;
  const best = options.reduce((a, b) => (score(b.option) < score(a.option) ? b : a));
  const r = view.request;
  openPanel(`What "${r.title}" pushes`,
    el('div', {},
      el('p', { class: 'muted' },
        `${fmt.hours(r.hours)} h, wanted by ${dateText(r.due)}${r.project_number ? `, on ${r.project_number}` : ''}. `
        + 'Each way below shows the planned work it would push back and what that costs. Nothing is added until you pick one.'),
      view.budget ? el('p', { class: 'small' },
        `${view.budget.job} has ${view.budget.remaining_mm} man-months of budget left; this uses about ${view.budget.uses_mm} of it.`) : null,
      el('div', { class: 'ur-options' }, options.map((o) => pushOption(o.option, {
        heading: o.heading, best: o === best, onAdd: () => add(o.body) })))));
}

function slotText(start, end) {
  if (!start) return '';
  const sameDay = start.slice(0, 10) === end.slice(0, 10);
  const day = start.slice(0, 10) === isoDay(new Date()) ? '' : `${shortDate(start.slice(0, 10))} `;
  return `${day}${start.slice(11, 16)}–${sameDay ? '' : `${shortDate(end.slice(0, 10))} `}${end.slice(11, 16)}`;
}

function requestList(data) {
  const open = data.requests.filter((r) => !r.done);
  const done = data.requests.filter((r) => r.done);
  if (!data.requests.length) return null;
  return el('section', { class: 'panel' },
    el('h3', {}, `Requests (${open.length} open${done.length ? `, ${done.length} done today` : ''})`),
    el('ul', { class: 'request-list' }, data.requests.map((r) => el('li', {
      class: `request ${r.done ? 'is-done' : ''} ${r.late ? 'is-late' : ''}`,
    },
    el('span', { class: 'request-time' }, slotText(r.start, r.end)),
    el('span', { class: 'request-what' }, el('b', {}, r.title),
      el('span', { class: 'muted small' }, ` ${r.person}`
        + (r.project_number ? ` · ${r.project_number}` : '')
        + ` · ${fmt.hours(r.hours)} h${r.late ? ' · later than wanted' : ''}`)),
    r.done ? el('span', { class: 'pill pill-ok' }, 'done')
      : el('button', { class: 'btn btn-sm', type: 'button', onclick: async () => {
          try {
            const result = await api(`/api/requests/${r.id}/done`, { method: 'POST' });
            if (result.save) markSaved(result.save);
            await loadDay({ quiet: true });
          } catch (error) { toastError(error); }
        } }, 'Done')))));
}

function dayCards(day, shown) {
  if (!day) return null;
  if (!day.working_day) {
    return el('div', { class: 'empty' }, `${dateText(day.date)} is not a working day.`);
  }
  const people = shown(day.people).filter((p) => p.blocks.length || p.over_hours);
  const away = shown(day.people).filter((p) => p.away);
  const idle = shown(day.people).filter((p) => !p.away && !p.blocks.length && !p.over_hours);
  return el('div', {},
    el('div', { class: 'day-grid' }, people
      .sort((a, b) => (a.team_name || '').localeCompare(b.team_name || '') || a.name.localeCompare(b.name))
      .map((p) => el('article', { class: `day-card ${p.over_hours ? 'is-over' : ''}` },
        el('header', {},
          el('b', {}, p.name),
          el('span', { class: 'muted small' }, [p.grade_label, p.team_name].filter(Boolean).join(' · ')),
          el('span', { class: `pill ${p.away || p.over_hours ? 'pill-bad' : p.free_hours >= 1 ? 'pill-warn' : 'pill-ok'}` },
            p.away ? 'away — hand these on'
              : p.over_hours ? `${fmt.hours(p.over_hours)} h over`
              : p.free_hours >= 1 ? `${fmt.hours(p.free_hours)} h free` : 'full')),
        el('ol', { class: 'day-blocks' }, p.blocks.map((b) => el('li', {
          class: `block block-${b.kind} ${b.done ? 'is-done' : ''}`,
        },
        el('span', { class: 'block-time' }, `${b.start}–${b.end}`),
        el('span', { class: 'block-what' },
          KIND_LABEL[b.kind] ? el('span', { class: 'block-kind' }, KIND_LABEL[b.kind]) : null,
          b.project && b.title !== b.project ? el('span', { class: 'code' }, `${b.project} `) : null,
          b.title,
          agendaList(b))))),
        p.away ? null : el('button', { class: 'linkish day-away', type: 'button',
          onclick: () => markAway(plan.dayData, p.name) }, 'Mark away')))),
    away.length ? el('p', { class: 'small' },
      el('b', {}, 'Away: '), away.map((p) => p.name).join(', '), '.') : null,
    idle.length ? el('p', { class: 'muted small' },
      `Nothing booked lately and nothing planned: ${idle.map((p) => p.name).join(', ')}.`) : null);
}

function weekTable(data, shown) {
  const names = shown(data.days[0] ? data.days[0].people : []).map((p) => p.name);
  const cell = (day, name) => {
    const p = day.people.find((x) => x.name === name);
    if (!day.working_day || !p) return el('td', { class: 'muted' }, '—');
    if (p.away && !p.blocks.length) return el('td', { class: 'muted' }, 'away');
    const load = (p.hours + p.over_hours) / (day.hours_per_day || 1);
    return el('td', {
      class: 'num week-cell clickable', 'data-sort': String(load),
      title: p.blocks.map((b) => `${b.start}–${b.end} ${b.title}`).join('\n'),
      onclick: () => { plan.span = 'day'; plan.date = day.date; loadDay(); },
    }, el('span', { class: `v-${loadTone(load)}` }, fmt.pct0(load)),
    p.requests ? el('span', { class: 'muted small' }, ` · ${p.requests} req`) : null);
  };
  return el('section', { class: 'panel' },
    el('h3', {}, 'The week'),
    el('p', { class: 'muted' }, 'Each day as a share of a working day. Choose a day to see it hour by hour.'),
    el('div', { class: 'table-wrap' }, el('table', {},
      el('thead', {}, el('tr', {}, el('th', {}, 'Who'),
        ...data.days.map((d) => el('th', { class: 'num' }, dateText(d.date))))),
      el('tbody', {}, names.map((name) => el('tr', {},
        el('td', {}, name), ...data.days.map((d) => cell(d, name))))))));
}

/** The plan as plain text: what Share sends and Print prints. */
function dayText(data) {
  const unit = data.unit ? ` — ${data.unit}` : '';
  const lines = [];
  for (const day of data.days) {
    lines.push(`${dateText(day.date)}${unit}`);
    if (!day.working_day) { lines.push('  Not a working day.', ''); continue; }
    const off = day.people.filter((p) => p.away && inChosenTeam(p, data)).map((p) => p.name);
    if (off.length) lines.push(`  Away: ${off.join(', ')}`);
    for (const p of day.people) {
      if (!inChosenTeam(p, data)) continue;
      if (p.away || (!p.blocks.length && !p.over_hours)) continue;
      lines.push(`${p.name}${p.team_name ? ` (${p.team_name})` : ''}`
        + (p.over_hours ? ` — ${fmt.hours(p.over_hours)} h over` : ''));
      for (const b of p.blocks) {
        lines.push(`  ${b.start}–${b.end}  ${KIND_LABEL[b.kind] ? `${KIND_LABEL[b.kind]}: ` : ''}`
          + `${b.project && b.title !== b.project ? `${b.project} ` : ''}${b.title}`);
        for (const line of b.agenda || []) lines.push(`      - ${line}`);
      }
    }
    lines.push('');
  }
  return lines.join('\n').trim();
}

async function shareDay(printIt) {
  const data = plan.dayData;
  if (!data) return;
  const text = dayText(data);
  const title = `Plan for ${plan.span === 'week' ? 'the week of ' : ''}${dateText(data.days[0] ? data.days[0].date : data.date)}`;
  if (printIt) {
    const page = window.open('', '_blank');
    if (!page) { toast('Allow pop-ups to print the plan.', 'bad'); return; }
    const escapeHtml = (t) => t.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    page.document.write(`<!doctype html><meta charset="utf-8"><title>${escapeHtml(title)}</title>`
      + '<style>body{font:13px/1.5 system-ui,sans-serif;margin:24px;color:#111}'
      + 'h1{font-size:18px}pre{font:inherit;white-space:pre-wrap}</style>'
      + `<h1>${escapeHtml(title)}</h1><pre>${escapeHtml(text)}</pre>`);
    page.document.close();
    page.focus();
    page.print();
    return;
  }
  if (navigator.share) {
    try { await navigator.share({ title, text }); return; } catch { /* cancelled */ return; }
  }
  try {
    await navigator.clipboard.writeText(`${title}\n\n${text}`);
    toast('The plan is copied. Paste it into a message or an email.', 'ok');
  } catch {
    openPanel(title, el('pre', { class: 'share-text' }, text));
  }
}

/* -- submissions --------------------------------------------------------- */

async function loadSubmissions({ quiet = false } = {}) {
  try {
    plan.submissions = await api('/api/submissions');
    plan.chosen = new Set(plan.submissions.items
      .filter((i) => i.date && i.basis !== 'set').map((i) => i.row));
    plan.edits = {};
    renderSubmissions();
  } catch (error) {
    if (!quiet) toastError(error);
  }
}

const BASIS = {
  set: ['pill-ok', 'in the register'],
  estimated: ['pill-info', 'estimated'],
  typical: ['pill-info', 'usual length'],
  far: ['pill-neutral', 'over a year away'],
  overdue: ['pill-bad', 'date passed'],
  idle: ['pill-neutral', 'nobody on it'],
};

function renderSubmissions() {
  const data = plan.submissions;
  if (!data || plan.view !== 'submissions') return;
  const dateOf = (item) => plan.edits[item.row] ?? item.date;
  const toConfirm = data.items.filter((i) => plan.chosen.has(i.row) && dateOf(i));
  const confirm = async () => {
    try {
      const result = await api('/api/submissions/confirm', {
        method: 'POST',
        body: { items: toConfirm.map((i) => ({ row: i.row, date: dateOf(i) })), prepare: true },
      });
      if (result.save) markSaved(result.save);
      toast(`${result.confirmed} submission date(s) set; ${result.tasks_added} run-up task(s) added to the days before.`, 'ok');
      if (state.tasks) state.tasks = null;
      plan.needs = null;
      await loadSubmissions({ quiet: true });
    } catch (error) {
      toastError(error);
    }
  };
  const counts = data.counts;
  setChildren($('#planner-body'),
    proposalsBlock(data.from_list, () => loadSubmissions({ quiet: true })),
    el('section', { class: 'panel' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Submissions plan'),
          el('p', { class: 'muted' },
            'Drafted by the app: a date for every deliverable not yet submitted, from how much is left before it can go '
            + 'and how fast it is being done. Tick the ones that are right, change any date, and confirm. Each confirmed '
            + `date goes on the deliverable, and its run-up (${fmt.hours(data.hours_a_day)} h a day over the ${data.lead_days} days before) `
            + 'goes into the right people’s days. '
            + (counts.typical
              ? `Projects nobody has confirmed yet are dated by how long this unit’s phases usually take (${data.typical_days} days`
                + `${data.typical_from ? `, from ${data.typical_from} finished phase(s)` : ', a default until some finish'}).`
              : ''))),
        el('button', { class: 'btn btn-primary', type: 'button', disabled: !toConfirm.length || null,
          onclick: confirm }, toConfirm.length ? `Confirm ${toConfirm.length}` : 'Confirm')),
      el('div', { class: 'stat-strip' },
        stat('Dates in the register', String(counts.set), 'ok'),
        stat('Drafted', String(counts.estimated + counts.typical), ''),
        stat('Date passed', String(counts.overdue), counts.overdue ? 'bad' : 'ok'),
        stat('Nobody on it', String(counts.idle), counts.idle ? 'warn' : 'ok')),
      data.items.length
        ? el('div', { class: 'table-wrap' }, el('table', { class: 'edit-table submissions-table' },
            el('thead', {}, el('tr', {},
              el('th', {}, ''), el('th', {}, 'Due'), el('th', {}, 'Deliverable'),
              el('th', {}, 'Date from'), el('th', { class: 'num' }, 'Hours left'),
              el('th', { class: 'num' }, 'Drawings'), el('th', {}, 'Who'))),
            el('tbody', {}, data.items.map((item) => {
              const box = el('input', { type: 'checkbox', 'aria-label': 'Confirm this date',
                disabled: !dateOf(item) || null,
                onchange: (e) => { if (e.target.checked) plan.chosen.add(item.row); else plan.chosen.delete(item.row); renderSubmissions(); } });
              box.checked = plan.chosen.has(item.row);
              const date = el('input', { type: 'date', value: dateOf(item) || '',
                onchange: (e) => { plan.edits[item.row] = e.target.value || null; if (e.target.value) plan.chosen.add(item.row); renderSubmissions(); } });
              const [pill, text] = BASIS[item.basis] || ['pill-neutral', item.basis];
              return el('tr', {},
                el('td', {}, box),
                el('td', {}, date),
                el('td', { class: 'wide' }, el('span', { class: 'code' }, `${item.project_number} `), item.name,
                  item.prepared ? el('span', { class: 'pill pill-ok', style: 'margin-left:6px' }, 'run-up planned') : null),
                el('td', {}, el('span', { class: `pill ${pill}`,
                  title: item.basis === 'overdue' ? `The register said ${fmt.date(item.register_date)}` : '' }, text),
                  item.step_name ? el('span', { class: 'muted small' }, ` ${item.step_name}`) : null),
                el('td', { class: 'num' }, item.hours_left === null ? '—' : fmt.hours(item.hours_left)),
                el('td', { class: 'num' }, item.list ? `${fmt.int(item.list.issued)} of ${fmt.int(item.list.total)} out`
                  : item.drawings === null || item.drawings === undefined ? '—' : fmt.int(item.drawings)),
                el('td', {}, item.people.join(', ') || '—'));
            }))))
        : el('div', { class: 'empty' }, 'Every deliverable has been submitted. Nothing to plan.')),
    waitingPanel(data));
}

/** Sent and nothing back yet: the client's turn, oldest first, to chase. */
function waitingPanel(data) {
  const waiting = data.waiting || [];
  if (!waiting.length) return null;
  return el('section', { class: 'panel' },
    el('h3', {}, `Waiting for comments (${waiting.length})`),
    el('p', { class: 'muted' }, 'Sent to the client and nothing back yet. The oldest are the ones to chase.'),
    el('ul', { class: 'request-list' }, waiting.map((w) => el('li', { class: `request ${w.days > 21 ? 'is-late' : ''}` },
      el('span', { class: 'request-time' }, `sent ${shortDate(w.sent)}`),
      el('span', { class: 'request-what' }, el('span', { class: 'code' }, `${w.project_number} `), el('b', {}, w.name),
        el('span', { class: 'muted small' }, ` · ${w.days} day${w.days === 1 ? '' : 's'}`
          + (w.list ? ` · ${w.list.issued} drawing(s)` : w.drawings ? ` · ${w.drawings} drawing(s)` : ''))),
      el('span')))));
}

/* -- the drawing list --------------------------------------------------- */

function changeText(change) {
  const parts = [];
  if (change.submitted_to_client) parts.push(`sent ${shortDate(change.submitted_to_client)}`);
  if (change.comments_received) parts.push(`comments back ${shortDate(change.comments_received)}`);
  if (change.completed) parts.push(`accepted ${shortDate(change.completed)}`);
  if (change.step_name) parts.push(`step: ${change.step_name}`);
  return parts.join(' · ');
}

/** What the drawing list says the register should, and one tap to apply it. */
function proposalsBlock(proposals, after) {
  if (!proposals || !proposals.length) return null;
  return el('div', { class: 'list-proposals' },
    el('div', { class: 'panel-head' },
      el('b', {}, `The drawing list moves ${proposals.length} deliverable(s) on`),
      el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: async () => {
        try {
          const result = await api('/api/drawing-list/apply', { method: 'POST',
            body: { rows: proposals.map((p) => p.row) } });
          if (result.save) markSaved(result.save);
          toast(`${result.applied} deliverable(s) updated from the drawing list.`, 'ok');
          plan.submissions = null;
          if (after) await after();
        } catch (error) { toastError(error); }
      } }, 'Apply')),
    el('ul', { class: 'plain-list' }, proposals.map((p) => el('li', {},
      el('span', { class: 'code' }, `${p.project_number} `), el('b', {}, p.name), ': ',
      changeText(p.change), el('span', { class: 'muted small' }, ` — ${p.why}`)))));
}

/** Projects > Drawing list: the template, the upload, and what it changed. */
function openDrawingList() {
  const results = el('div', { class: 'list-results' });
  const input = el('input', { type: 'file', accept: '.xlsx,.xlsm', multiple: true });
  const show = (result) => {
    const d = result.drawings || {};
    setChildren(results,
      el('p', {}, el('b', {}, `${fmt.int(result.matched)} drawing(s) on ${result.deliverables.length} deliverable(s).`),
        ` ${fmt.int(Math.round(d.done || 0))} of ${fmt.int(d.total || 0)} done across the unit`
        + (d.hours_per_drawing ? `, ${fmt.hours(d.hours_per_drawing)} h a drawing.` : '.')),
      result.deliverables.length ? el('div', { class: 'table-wrap' }, el('table', {},
        el('thead', {}, el('tr', {}, el('th', {}, 'Deliverable'), el('th', { class: 'num' }, 'Drawings'),
          el('th', { class: 'num' }, 'Gone out'), el('th', { class: 'num' }, 'A'),
          el('th', { class: 'num' }, 'B'), el('th', { class: 'num' }, 'C'))),
        el('tbody', {}, result.deliverables.map((e) => el('tr', {},
          el('td', {}, el('span', { class: 'code' }, `${e.project_number} `), e.name),
          el('td', { class: 'num' }, fmt.int(e.total)), el('td', { class: 'num' }, fmt.int(e.issued)),
          el('td', { class: 'num' }, fmt.int(e.code_a)), el('td', { class: 'num' }, fmt.int(e.code_b)),
          el('td', { class: 'num' }, fmt.int(e.code_c))))))) : null,
      result.unmatched.length ? el('p', { class: 'muted small' },
        'Not matched to a deliverable: ', result.unmatched.map((u) =>
          `${u.job_number}${u.deliverable ? ` / ${u.deliverable}` : ''} (${u.drawings})`).join(', '),
        '. Check the job number, and give the deliverable\'s name as on Projects or its phase number.') : null,
      proposalsBlock(result.proposals, async () => {
        setChildren(results, el('p', {}, 'Applied. The register and the submissions plan are up to date.'));
        if (typeof refreshAll === 'function') await refreshAll();
      }));
  };
  input.addEventListener('change', async () => {
    if (!input.files.length) return;
    setChildren(results, el('p', { class: 'muted' }, 'Reading…'));
    try {
      const result = await api('/api/drawing-list', { method: 'POST',
        body: { files: await filesBase64([...input.files]) } });
      show(result);
      if (typeof refreshAll === 'function') refreshAll();
    } catch (error) {
      setChildren(results, el('p', { class: 'v-bad' }, (error.errors || [error.message]).join(' ')));
    }
    input.value = '';
  });
  openPanel('Drawing list', el('div', { class: 'drawing-list' },
    el('p', {}, 'Upload the drawing list the team keeps — one row a drawing — and each deliverable\'s drawing count, '
      + 'how many have gone to the client and the codes that came back are read from it. '
      + 'Any list with headings like Job Number, Drawing No., Status, Issued and Code will do.'),
    el('div', { class: 'row' },
      el('button', { class: 'btn', type: 'button', onclick: async () => {
        try {
          const file = await api('/api/drawing-list/template');
          downloadBase64(file.content_base64, file.filename);
        } catch (error) {
          toastError(error); }
      } }, 'Download the template'),
      el('label', { class: 'btn btn-primary file-btn' }, 'Upload a drawing list', input)),
    results));
}

/* -- wiring -------------------------------------------------------------- */

function fillTeams(teams) {
  const select = $('#planner-team');
  if (plan.team !== 'all' && !teams.some((t) => t.id === plan.team)) plan.team = 'all';
  setChildren(select, el('option', { value: 'all' }, 'Every team'),
    ...teams.map((t) => el('option', { value: t.id }, t.name)));
  select.value = plan.team;
  select.parentElement.hidden = teams.length < 2;
}

function wirePlanner() {
  const listButton = $('#btn-drawing-list');
  if (listButton) listButton.addEventListener('click', openDrawingList);
  const team = $('#planner-team');
  if (!team) return;
  team.addEventListener('change', (e) => {
    plan.team = e.target.value;
    if (plan.view === 'today') renderDay();
    else renderPlanner();
  });
}

window.planner = {
  load: () => { plan.needs = null; plan.submissions = null; return openPlanner(); },
  board: () => { plan.view = 'handovers'; switchView('planner'); },
  open: (view) => { plan.view = view; switchView('planner'); },
  afterRefresh: () => {
    plan.needs = null;
    plan.submissions = null;
    overviewNeeds();
    if ($('#view-planner').classList.contains('is-active')) openPlanner({ quiet: true });
  },
};

wirePlanner();
