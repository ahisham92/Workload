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
  busy: false,
};

const ROLE_LABEL = { engineering: 'Engineers', drafting: 'Draftsmen' };

function loadTone(load) {
  if (load === null || load === undefined) return '';
  return load > 1.0001 ? 'bad' : load < 0.8 ? 'warn' : 'ok';
}

function dayName(iso) {
  if (!iso) return '—';
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

function shortDate(iso) {
  if (!iso) return '—';
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

/* ------------------------------------------------------------ loading */

const PLANNER_VIEWS = [['today', 'Today'], ['handovers', 'Next days'],
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
  } else if (plan.view === 'submissions') {
    await loadSubmissions({ quiet });
  } else if (plan.view === 'people') {
    try {
      plan.needs = plan.needs || await api('/api/needs');
      setChildren($('#planner-body'), renderNeeds(plan.needs));
    } catch (error) {
      if (!quiet) toast((error.errors || [error.message]).join(' '), 'bad');
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
    if (!quiet) toast((error.errors || [error.message]).join(' '), 'bad');
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
    toast((error.errors || [error.message]).join(' '), 'bad');
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
    toast((error.errors || [error.message]).join(' '), 'bad');
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
    toast((error.errors || [error.message]).join(' '), 'bad');
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
      `The newest timesheet is from ${dayName(data.pace_to)}. A pace that old is a guess: `
      + 'import this month’s timesheets for an outlook worth acting on.') : null,
    plannerCards(data),
    whoHasWhat(data),
    movesPanel(data),
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
  const level = { now: 'bad', soon: 'warn', room: 'ok', ok: 'ok' };
  const label = { now: 'ask now', soon: 'ask soon', room: 'room', ok: 'fine' };
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
          el('b', {}, a.title),
          el('span', { class: `pill pill-${level[a.severity] === 'ok' ? 'ok' : level[a.severity]}` },
            label[a.severity] || a.severity)),
        el('p', { class: 'muted' }, a.detail),
        a.kind === 'need' ? needWeeks(needs, a) : null)))
      : el('p', { class: 'muted' }, 'Nobody to forecast for yet.'),
    needsFootnote(needs));
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
  notes.push(`Ask ${needs.rules.lead_weeks} weeks before somebody is needed. Timesheets run to ${dayName(needs.data_through)}.`);
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
        el('h3', {}, `Who has what, ${dayName(data.from)} to ${dayName(data.to)}`),
        el('p', { class: 'muted' },
          `Each person at the pace their timesheets set from ${dayName(data.pace_from)} to ${dayName(data.pace_to)}, `
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
          + `a share of a project is then kept until ${dayName(data.to)} and lapses by itself; a task is simply reassigned.`)),
      el('div', { class: 'row-actions' },
        el('button', { class: 'btn btn-sm', type: 'button', onclick: suggestMoves }, 'Suggest handovers'),
        trying.length ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => tryMoves([]) }, 'Clear') : null,
        trying.length ? el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: commitMoves },
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
      }, el('b', {}, a.title), el('p', { class: 'muted' }, a.detail))),
      d.known ? el('div', { class: 'finding' },
        el('b', {}, `Drawings: ${fmt.int(Math.round(d.done))} of ${fmt.int(d.total)} done`),
        el('p', { class: 'muted' }, `${fmt.int(Math.round(d.left))} left`
          + (d.hours_per_drawing ? `, at ${fmt.hours(d.hours_per_drawing)} h a drawing so far` : '')
          + (d.deliverables_without ? `. ${d.deliverables_without} deliverable(s) have no count yet.` : '.')))
        : el('div', { class: 'finding' },
          el('b', {}, 'Drawings'),
          el('p', { class: 'muted' }, 'Give each deliverable its number of drawings on Projects, and done, left and hours a drawing follow everywhere.'))));
}

/* -- today ------------------------------------------------------------- */

const KIND_LABEL = { request: 'Request', submission: 'Submission', meeting: 'Meeting',
  task: 'Task', work: '' };

function isoDay(date) {
  const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 10);
}

function shiftDay(iso, days) {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return isoDay(d);
}

async function loadDay({ quiet = false } = {}) {
  const params = new URLSearchParams({ span: plan.span });
  if (plan.date) params.set('date', plan.date);
  try {
    plan.dayData = await api(`/api/day?${params}`);
    renderDay();
  } catch (error) {
    if (!quiet) toast((error.errors || [error.message]).join(' '), 'bad');
  }
}

function renderDay() {
  const data = plan.dayData;
  if (!data || plan.view !== 'today') return;
  fillTeams(data.teams);
  const shown = (people) => people.filter((p) => plan.team === 'all' || p.team_id === plan.team);
  const step = plan.span === 'week' ? 7 : 1;
  const label = plan.span === 'week'
    ? `Week of ${dayName(data.days[0] ? data.days[0].date : data.date)}`
    : (data.date === data.today ? `Today, ${dayName(data.date)}` : dayName(data.date));

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
    plan.span === 'week' ? weekTable(data, shown) : dayCards(data.days[0], shown));
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
    el('option', { value: shiftDay(data.today, 7) }, 'this week'));
  const who = el('select', { 'aria-label': 'Who' },
    el('option', { value: 'engineering' }, 'Engineer with room'),
    el('option', { value: 'drafting' }, 'Draftsman with room'),
    ...data.people.filter((p) => data.engineers.includes(p.name)).map((p) =>
      el('option', { value: `person:${p.name}` }, p.name)));
  const project = el('select', { 'aria-label': 'Project' },
    el('option', { value: '' }, 'No project'),
    ...data.projects.map((p) => el('option', { value: p.number },
      p.name && p.name !== p.number ? `${p.number} ${p.name}` : p.number)));
  const add = async () => {
    if (!title.value.trim()) { title.focus(); return; }
    const choice = who.value;
    const body = {
      title: title.value.trim(), hours: Number(hours.value), due: due.value,
      project_number: project.value,
      role: choice.startsWith('person:') ? 'engineering' : choice,
      person: choice.startsWith('person:') ? choice.slice(7) : '',
      now: (() => { const d = new Date(); return `${isoDay(d)}T${d.toTimeString().slice(0, 5)}`; })(),
    };
    try {
      const result = await api('/api/requests', { method: 'POST', body });
      if (result.save) markSaved(result.save);
      toast(`${result.person}, ${slotText(result.start, result.end)}`
        + (result.late ? ' — later than wanted' : ''), result.late ? 'bad' : 'ok');
      title.value = '';
      plan.needs = null;
      if (state.tasks) state.tasks = null;
      await loadDay({ quiet: true });
    } catch (error) {
      toast((error.errors || [error.message]).join(' '), 'bad');
    }
  };
  title.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  return el('div', { class: 'quick-add' },
    title,
    el('div', { class: 'quick-add-options' }, hours, due, who, project,
      el('button', { class: 'btn btn-primary', type: 'button', onclick: add }, 'Add')));
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
          } catch (error) { toast((error.errors || [error.message]).join(' '), 'bad'); }
        } }, 'Done')))));
}

function dayCards(day, shown) {
  if (!day) return null;
  if (!day.working_day) {
    return el('div', { class: 'empty' }, `${dayName(day.date)} is not a working day.`);
  }
  const people = shown(day.people).filter((p) => p.blocks.length || p.over_hours);
  const idle = shown(day.people).filter((p) => !p.blocks.length && !p.over_hours);
  return el('div', {},
    el('div', { class: 'day-grid' }, people
      .sort((a, b) => (a.team_name || '').localeCompare(b.team_name || '') || a.name.localeCompare(b.name))
      .map((p) => el('article', { class: `day-card ${p.over_hours ? 'is-over' : ''}` },
        el('header', {},
          el('b', {}, p.name),
          el('span', { class: 'muted small' }, [p.grade_label, p.team_name].filter(Boolean).join(' · ')),
          el('span', { class: `pill ${p.over_hours ? 'pill-bad' : p.free_hours >= 1 ? 'pill-warn' : 'pill-ok'}` },
            p.over_hours ? `${fmt.hours(p.over_hours)} h over`
              : p.free_hours >= 1 ? `${fmt.hours(p.free_hours)} h free` : 'full')),
        el('ol', { class: 'day-blocks' }, p.blocks.map((b) => el('li', {
          class: `block block-${b.kind} ${b.done ? 'is-done' : ''}`,
        },
        el('span', { class: 'block-time' }, `${b.start}–${b.end}`),
        el('span', { class: 'block-what' },
          KIND_LABEL[b.kind] ? el('span', { class: 'block-kind' }, KIND_LABEL[b.kind]) : null,
          b.project && b.title !== b.project ? el('span', { class: 'code' }, `${b.project} `) : null,
          b.title))))))),
    idle.length ? el('p', { class: 'muted small' },
      `Nothing booked lately and nothing planned: ${idle.map((p) => p.name).join(', ')}.`) : null);
}

function weekTable(data, shown) {
  const names = shown(data.days[0] ? data.days[0].people : []).map((p) => p.name);
  const cell = (day, name) => {
    const p = day.people.find((x) => x.name === name);
    if (!day.working_day || !p) return el('td', { class: 'muted' }, '—');
    const load = data.days[0] ? (p.hours + p.over_hours) / (day.hours_per_day || 1) : null;
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
        ...data.days.map((d) => el('th', { class: 'num' }, dayName(d.date))))),
      el('tbody', {}, names.map((name) => el('tr', {},
        el('td', {}, name), ...data.days.map((d) => cell(d, name))))))));
}

/** The plan as plain text: what Share sends and Print prints. */
function dayText(data) {
  const unit = data.unit ? ` — ${data.unit}` : '';
  const lines = [];
  for (const day of data.days) {
    lines.push(`${dayName(day.date)}${unit}`);
    if (!day.working_day) { lines.push('  Not a working day.', ''); continue; }
    for (const p of day.people) {
      if (plan.team !== 'all' && p.team_id !== plan.team) continue;
      if (!p.blocks.length && !p.over_hours) continue;
      lines.push(`${p.name}${p.team_name ? ` (${p.team_name})` : ''}`
        + (p.over_hours ? ` — ${fmt.hours(p.over_hours)} h over` : ''));
      for (const b of p.blocks) {
        lines.push(`  ${b.start}–${b.end}  ${KIND_LABEL[b.kind] ? `${KIND_LABEL[b.kind]}: ` : ''}`
          + `${b.project && b.title !== b.project ? `${b.project} ` : ''}${b.title}`);
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
  const title = `Plan for ${plan.span === 'week' ? 'the week of ' : ''}${dayName(data.days[0] ? data.days[0].date : data.date)}`;
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
    if (!quiet) toast((error.errors || [error.message]).join(' '), 'bad');
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
      toast((error.errors || [error.message]).join(' '), 'bad');
    }
  };
  const counts = data.counts;
  setChildren($('#planner-body'),
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
                  title: item.basis === 'overdue' ? `The register said ${item.register_date}` : '' }, text),
                  item.step_name ? el('span', { class: 'muted small' }, ` ${item.step_name}`) : null),
                el('td', { class: 'num' }, item.hours_left === null ? '—' : fmt.hours(item.hours_left)),
                el('td', { class: 'num' }, item.drawings === null || item.drawings === undefined ? '—' : fmt.int(item.drawings)),
                el('td', {}, item.people.join(', ') || '—'));
            }))))
        : el('div', { class: 'empty' }, 'Every deliverable has been submitted. Nothing to plan.')));
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
  afterRefresh: () => {
    plan.needs = null;
    plan.submissions = null;
    overviewNeeds();
    if ($('#view-planner').classList.contains('is-active')) openPlanner({ quiet: true });
  },
};

wirePlanner();
