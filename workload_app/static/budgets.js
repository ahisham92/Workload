/* Selecao+ — budgets: BISpark's budget for each job, and the team's part of it.
 *
 * The Budgets tab. Two BISpark files feed it: the Projects list (budget, spent,
 * status) and each job's staff expenditure (who booked the hours, and which
 * unit they sit in). A job's budget in BISpark is the department's, so the
 * team's share of it is worked out from who spent the hours, until the manager
 * sets it. Everything is worked out by the server (workload_app/budgets.py).
 *
 * Built on app.js's helpers (el, api, setChildren, openModal, modalValues,
 * toast, fmt, filesBase64), checkins.js's statCard and growth.js's todoList.
 */
'use strict';

const bud = { data: null, busy: false, open: null };

const BU_STATE = {
  over: { label: 'Over budget', tone: 'bad' },
  short: { label: 'Runs out early', tone: 'warn' },
  ok: { label: 'On track', tone: 'ok' },
  paused: { label: 'On hold', tone: 'info' },
  no_budget: { label: 'No budget yet', tone: 'neutral' },
  closed: { label: 'Closed', tone: 'neutral' },
};
const BU_BASIS = {
  set: 'set by you',
  booked: 'from who booked the hours',
  unknown: 'not known yet: counted as all of it',
};

function buMonth(iso) {
  if (!iso) return '—';
  return new Date(`${iso.length === 7 ? `${iso}-01` : iso}T00:00:00`)
    .toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
}

const buDay = (iso) => dateText(iso, { day: 'numeric', month: 'short', year: 'numeric' });

async function loadBudgets(force = false) {
  if (bud.busy) return;
  if (bud.data && !force) { renderBudgets(); return; }
  bud.busy = true;
  try {
    bud.data = await api('/api/budgets');
  } catch (error) {
    setChildren($('#budgets-body'), el('div', { class: 'msg msg-bad' }, error.message));
    return;
  } finally {
    bud.busy = false;
  }
  renderBudgets();
}

function renderBudgets() {
  const data = bud.data;
  const body = $('#budgets-body');
  if (!data || !body) return;
  const live = data.jobs.filter((j) => j.listed);
  const closed = data.jobs.filter((j) => !j.listed);
  if (!data.jobs.length) {
    setChildren(body, gettingStarted(), automatePanel(data));
    return;
  }
  setChildren(body,
    budgetsTodo(data),
    budgetsStats(data, live),
    buBudgetBars(live),
    jobsPanel(live),
    bud.open ? jobDetail(data.jobs.find((j) => j.job_number === bud.open)) : null,
    peoplePanel(data),
    closed.length ? closedPanel(closed) : null,
    automatePanel(data));
}

/* --------------------------------------------------------- getting started */

function gettingStarted() {
  return el('section', { class: 'panel' },
    el('h3', {}, 'Bring in your budgets from BISpark'),
    el('ol', { class: 'bu-steps' },
      el('li', {}, el('b', {}, 'Projects list. '),
        'BISpark > DD or HoD or GL > Projects. On the table, choose More options (…) > Export data > ',
        el('b', {}, 'Summarized data'), '. That one has the budget column.'),
      el('li', {}, el('b', {}, 'Staff expenditure. '),
        'Open a project, go to MH Expenditure, and export the Staff expenditure table. '
        + 'Do this for the jobs you want split by who booked them.'),
      el('li', {}, 'Press ', el('b', {}, 'Bring in BISpark files'),
        ' above and choose them all at once. Selecao+ tells the two kinds apart.')),
    el('p', { class: 'muted' },
      'Once it works by hand, the manager kit on your laptop can fetch both every night: see the end of this tab.'));
}

/* ------------------------------------------------------------- what to do */

function budgetsTodo(data) {
  if (!data.todo.length) {
    return el('section', { class: 'panel' },
      el('h3', {}, 'What to do'),
      el('p', { class: 'muted' }, 'Nothing needs you: every job is inside its budget at the current pace.'));
  }
  const action = (item) => {
    if (item.people) {
      return el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => { const p = $('#bu-people'); if (p) p.scrollIntoView({ behavior: 'smooth' }); } },
      'Mark them');
    }
    if (item.jobs && item.jobs.length) {
      return el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => openJob(item.jobs[0]) }, item.jobs.length === 1 ? 'Open it' : 'Open the first');
    }
    return null;
  };
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, 'What to do'),
      el('p', { class: 'muted' }, 'Most pressing first.'))),
    todoList(data.todo, action));
}

function budgetsStats(data, live) {
  const t = data.totals;
  const used = t.team_budget_mm ? t.team_spent_mm / t.team_budget_mm : null;
  const risky = t.over + t.short;
  return el('div', { class: 'cards cards-4' },
    statCard('Your team\'s budget', `${fmt.mm(t.team_budget_mm)} MM`, '',
      `of ${fmt.mm(t.dept_budget_mm)} MM for the department`),
    statCard('Spent by the team', `${fmt.mm(t.team_spent_mm)} MM`,
      used === null ? '' : used > 1 ? 'bad' : used > 0.85 ? 'warn' : 'ok',
      used === null ? 'no budgets yet' : `${fmt.pct0(used)} of the budget`),
    statCard('Left', `${fmt.mm(t.team_left_mm)} MM`, tone.amount(t.team_left_mm),
      `across ${live.length} live job${live.length === 1 ? '' : 's'}`),
    statCard('Jobs at risk', risky, risky ? 'bad' : 'ok',
      `${t.over} over, ${t.short} running out early`));
}

/* ------------------------------------------------- budget against spend bars */

function elapsed(job) {
  if (!job.start || !job.end) return null;
  const start = new Date(`${job.start}T00:00:00`);
  const end = new Date(`${job.end}T00:00:00`);
  const span = end - start;
  if (span <= 0) return null;
  return Math.max(0, Math.min(1, (Date.now() - start) / span));
}

function buBudgetBars(live) {
  const jobs = live.filter((j) => j.team_budget_mm);
  if (!jobs.length) return null;
  const rows = jobs.slice(0, 12).map((j) => {
    const used = j.team_spent_mm / j.team_budget_mm;
    const time = elapsed(j);
    const state = BU_STATE[j.state] || BU_STATE.ok;
    return el('button', { class: 'bu-bar-row', type: 'button', onclick: () => openJob(j.job_number),
      title: `${j.job_number}: ${fmt.mm(j.team_spent_mm)} of ${fmt.mm(j.team_budget_mm)} MM` },
      el('span', { class: 'bu-bar-name' }, el('b', {}, j.job_number), el('span', { class: 'muted' }, j.title)),
      el('span', { class: 'bu-bar' },
        el('span', { class: `bu-fill bu-${state.tone}`, style: `width:${Math.min(100, used * 100).toFixed(1)}%` }),
        time === null ? null : el('span', { class: 'bu-time', style: `left:${(time * 100).toFixed(1)}%` })),
      el('span', { class: `bu-bar-value v-${state.tone === 'neutral' ? '' : state.tone}` }, fmt.pct0(used)));
  });
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, 'Budget against spend'),
      el('p', { class: 'muted' },
        'One bar per job. The whole bar is your team\'s budget, the coloured part what the team has spent. '
        + 'The thin line is how far through its dates the job is: colour past the line means the money '
        + 'is going faster than the time. Tap a job to see who spent it.'))),
    el('div', { class: 'bu-bars' }, ...rows),
    jobs.length > 12 ? el('p', { class: 'muted' }, `The 12 most pressing of ${jobs.length}; all are in the table below.`) : null);
}

/* -------------------------------------------------------------- the jobs */

/** A job's state tone for a pill or a message, where 'neutral' shows as 'info'. */
function stateTone(job) {
  const tone = (BU_STATE[job.state] || BU_STATE.ok).tone;
  return tone === 'neutral' ? 'info' : tone;
}

function statePill(job) {
  return el('span', { class: `pill pill-${stateTone(job)}` }, (BU_STATE[job.state] || BU_STATE.ok).label);
}

function shareCell(job) {
  return el('button', { class: 'btn btn-sm btn-ghost bu-share', type: 'button',
    title: `Your share, ${BU_BASIS[job.share_basis]}. Tap to change it.`,
    onclick: (event) => { event.stopPropagation(); editShare(job); } },
  fmt.pct0(job.share), job.share_basis === 'set' ? '' : ' ✎');
}

function jobsPanel(live) {
  const head = ['Job', 'Status', 'BISpark budget', 'Your share', 'Your budget', 'Spent', 'Left', 'Runs out', ''];
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, 'Every job'),
      el('p', { class: 'muted' },
        'BISpark budget is the department\'s. Your share is set by you, or worked out from who has booked the '
        + 'hours so far. Runs out is when what is left would be used up at the last three months\' pace.'))),
    el('div', { class: 'table-wrap' }, el('table', { class: 'data' },
      el('thead', {}, el('tr', {}, ...head.map((h) => el('th', {}, h)))),
      el('tbody', {}, ...live.map((j) => el('tr', { class: 'clickable', onclick: () => openJob(j.job_number) },
        el('td', {}, el('b', {}, j.job_number), el('div', { class: 'muted bu-title' }, j.title)),
        el('td', {}, j.status || '—'),
        el('td', { class: 'num' }, fmt.mm(j.budget_mm)),
        el('td', { class: 'num' }, shareCell(j)),
        el('td', { class: 'num' }, fmt.mm(j.team_budget_mm)),
        el('td', { class: 'num' }, fmt.mm(j.team_spent_mm)),
        el('td', { class: 'num' }, toned(j.team_left_mm, tone.amount, fmt.mm)),
        el('td', {}, j.runs_out ? buMonth(j.runs_out) : '—'),
        el('td', {}, statePill(j))))))));
}

function openJob(number) {
  bud.open = number;
  renderBudgets();
  const node = $('#bu-detail');
  if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function jobDetail(job) {
  if (!job) return null;
  const peak = Math.max(0.01, ...job.months.map((m) => m.mm));
  const months = el('div', { class: 'bu-months', role: 'img',
    'aria-label': 'Man-months the team spent each month, the last twelve months' },
  ...job.months.map((m) => el('span', { class: 'bu-month', title: `${buMonth(m.month)}: ${fmt.mm(m.mm)} MM` },
    el('span', { class: 'bu-month-bar', style: `height:${Math.round((m.mm / peak) * 100)}%` }),
    el('span', { class: 'bu-month-label' }, buMonth(m.month).slice(0, 3)))));
  const total = (job.people || []).reduce((s, p) => s + p.mm, 0) + (job.other_units_mm || 0);
  const kindLabel = Object.fromEntries((bud.data.kinds || []).map((k) => [k.value, k.label]));
  const next = job.state === 'over'
    ? 'Agree more budget with the project manager, or stop booking to it.'
    : job.state === 'short'
      ? `At ${fmt.mm(job.pace_mm_a_month)} MM a month, what is left runs out on ${buDay(job.runs_out)}, before the job ends on ${buDay(job.end)}. Slow the hours or ask for more now.`
      : job.state === 'no_budget'
        ? 'BISpark has no budget for it in what came in. Bring in the Projects list as Summarized data.'
        : job.state === 'closed'
          ? `No longer on the Projects list since ${buDay(job.last_seen)}. Its last figures are kept here.`
          : job.runs_out
            ? `At ${fmt.mm(job.pace_mm_a_month)} MM a month, what is left lasts to ${buMonth(job.runs_out)}.`
            : 'Nothing to do.';
  return el('section', { class: 'panel bu-detail', id: 'bu-detail' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, `${job.job_number} ${job.title ? `· ${job.title}` : ''}`),
        el('p', { class: 'muted' }, [job.status, job.lead && `led by ${job.lead}`,
          job.end && `ends ${buDay(job.end)}`, job.updated && `updated ${buDay(job.updated)}`]
          .filter(Boolean).join(' · '))),
      el('div', { class: 'row-actions' },
        statePill(job),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: () => editShare(job) }, 'Set your share'),
        el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
          onclick: () => { bud.open = null; renderBudgets(); } }, 'Close'))),
    el('p', { class: `msg msg-${stateTone(job)}` }, next),
    el('div', { class: 'cards cards-4' },
      ...[
        ['BISpark budget', job.budget_mm, `spent ${fmt.mm(job.spent_mm)} by the department`],
        ['Your share', null, BU_BASIS[job.share_basis], fmt.pct0(job.share)],
        ['Your budget', job.team_budget_mm, job.in_register
          ? (job.follows_bispark ? 'Projects tab uses it' : `Projects tab has ${fmt.mm(job.project_budget_mm)} typed by hand`)
          : 'not on the Projects tab'],
        ['Spent by the team', job.team_spent_mm, job.spent_from === 'staff'
          ? 'from the staff expenditure' : 'from your timesheets'],
      ].map(([label, value, sub, shown]) => el('div', { class: 'card' },
        el('div', { class: 'label' }, label),
        el('div', { class: 'value' }, shown || `${fmt.mm(value)} MM`),
        el('div', { class: 'sub' }, sub)))),
    el('div', { class: 'bu-detail-grid' },
      el('div', {},
        whoOnJob(job)),
      el('div', {},
        el('h4', {}, 'The team\'s man-months, month by month'),
        months)));
}

/** Who worked on the job, unit by unit, each inside or outside the team on
    this job. One person can be on the team on one job and serving another
    team on the next, so it is set per job; the share follows from it. */
function whoOnJob(job) {
  const groups = job.who || [];
  if (!groups.length) {
    return el('div', {}, el('h4', {}, 'Who worked on it'),
      el('p', { class: 'muted' }, 'No staff expenditure for this job yet. Export it from the job\'s MH Expenditure page.'));
  }
  const total = groups.reduce((s, g) => s + (g.mm || 0), 0);
  const inside = groups.reduce((s, g) => s + (g.inside_mm || 0), 0);
  const outside = Math.max(0, total - inside);
  const save = async (people, value, said) => {
    try {
      bud.data = await api(`/api/budgets/jobs/${encodeURIComponent(job.job_number)}/people`, {
        method: 'PUT', body: { people: people.map((p) => ({ full_name: p.name, unit: p.unit })), inside: value } });
      toast(said, 'ok');
      renderBudgets();
      registerChanged();
    } catch (error) { toastError(error); }
  };
  const choice = (p) => el('span', { class: 'bu-io', role: 'group', 'aria-label': `${p.name} on this job` },
    ...[[true, 'Inside'], [false, 'Outside']].map(([value, text]) => el('button', {
      type: 'button', class: `bu-io-btn${(value ? p.inside : !p.inside && !p.part) ? ' is-on' : ''}`,
      'aria-pressed': (value ? p.inside : !p.inside && !p.part) ? 'true' : 'false',
      onclick: () => save([p], value, `${p.name}: ${value ? 'inside' : 'outside'} your team on ${job.job_number}.`),
    }, text)));
  return el('div', { class: 'bu-onjob' },
    el('h4', {}, 'Who worked on it: inside or outside your team?'),
    el('p', { class: `msg msg-${outside > 0.005 ? 'info' : 'ok'}` },
      `Outside your team: ${fmt.pct0(total ? outside / total : 0)} of the ${fmt.mm(total)} MM spent. `
      + (job.share_basis === 'set'
        ? `Your share is set by hand at ${fmt.pct0(job.share)}.`
        : `So your share of the budget is ${fmt.pct0(job.share)}`
          + (job.team_budget_mm == null ? ' (the job has no budget yet).' : `, and your budget ${fmt.mm(job.team_budget_mm)} MM.`))),
    el('p', { class: 'muted' }, 'Tap a unit to see its people.'),
    ...groups.map((g) => el('details', { class: 'bu-unit', open: g.inside_mm > 0 || groups.length === 1 ? true : null },
      el('summary', {},
        el('b', {}, g.unit_label || 'Unit not known'),
        el('span', { class: 'muted' }, ` · ${fmt.mm(g.mm)} MM, ${fmt.pct0(total ? g.mm / total : 0)} of the job`),
        el('span', { class: 'bu-unit-all' },
          el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
            onclick: (e) => { e.preventDefault(); save(g.people, true, `${g.unit_label}: all inside on ${job.job_number}.`); } }, 'All inside'),
          el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
            onclick: (e) => { e.preventDefault(); save(g.people, false, `${g.unit_label}: all outside on ${job.job_number}.`); } }, 'All outside'))),
      el('ul', { class: 'bu-who' }, ...g.people.map((p) => el('li', {},
        el('span', {}, p.name, el('span', { class: 'muted small' },
          p.by === 'job' ? ' · set for this job' : p.part ? ' · part of the time (on loan or left)' : '')),
        el('b', {}, fmt.mm(p.mm)),
        choice(p)))))));
}

function editShare(job) {
  openModal(`Your team's share of ${job.job_number}`, [
    { name: 'share_percent', label: 'Share of the BISpark budget, %', type: 'number', min: 0, max: 100, step: 1,
      hint: job.share_guess === null || job.share_guess === undefined
        ? 'no staff expenditure yet to work it out from'
        : `${fmt.pct0(job.share_guess)} from who booked the hours; leave empty to use that` },
  ], async () => {
    const values = modalValues();
    bud.data = await api(`/api/budgets/jobs/${encodeURIComponent(job.job_number)}`,
      { method: 'PUT', body: { share_percent: values.share_percent } });
    closeModal();
    toast(values.share_percent === null ? 'Back to the share from who booked the hours.' : 'Share saved.', 'ok');
    renderBudgets();
    registerChanged();
  }, { share_percent: job.share_basis === 'set' ? Math.round(job.share * 1000) / 10 : '' });
}

/** A share, a person or a new file moves the team's budget on the Projects
    tab (where it follows BISpark) and the days the staff expenditure fills
    in: the rest of the app is read again so it does not show the old ones. */
function registerChanged() {
  if (typeof refreshAll === 'function') refreshAll().catch(() => {});
}

/* ------------------------------------------------------- people on the jobs */

function peoplePanel(data) {
  if (!data.people.length) return null;
  return el('section', { class: 'panel', id: 'bu-people' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, 'People on your jobs'),
      el('p', { class: 'muted' },
        'Everybody on the staff expenditures. Only your team counts toward your share and your spend: '
        + 'your own unit, your draftsmen, people loaned in for their dates, and people who left up to the day they left. '
        + 'Somebody loaned out to another unit is not counted for those dates. '
        + 'Everybody else is one line, other units. Set each person once; it stays.'))),
    el('div', { class: 'table-wrap' }, el('table', { class: 'data' },
      el('thead', {}, el('tr', {}, ...['Name', 'Unit', 'MM on your jobs', 'Jobs', 'What they are', ''].map((h) => el('th', {}, h)))),
      el('tbody', {}, ...data.people.map((p) => el('tr', {},
        el('td', {}, p.name),
        el('td', {}, p.unit_label || '—'),
        el('td', { class: 'num' }, fmt.mm(p.mm)),
        el('td', { class: 'num' }, p.jobs),
        el('td', {}, el('span', { class: `pill pill-${p.kind === 'other' ? 'info' : 'ok'}` }, p.kind_label),
          p.kind === 'loan' || p.kind === 'out' ? el('div', { class: 'muted' }, `${buDay(p.from)} to ${buDay(p.to)}`) : null,
          p.kind === 'left' ? el('div', { class: 'muted' }, `left ${buDay(p.to)}`) : null,
          p.set ? null : el('div', { class: 'muted' }, 'from their unit')),
        el('td', {}, el('button', { class: 'btn btn-sm', type: 'button', onclick: () => editPerson(p) }, 'Change'))))))));
}

function editPerson(p) {
  const kinds = (bud.data.kinds || []).map((k) => ({ value: k.value, label: k.label }));
  openModal(`What is ${p.name} to the team?`, [
    { name: 'kind', label: 'They are', type: 'select', options: [{ value: 'default', label: 'Go by their unit' }, ...kinds] },
    { name: 'from', label: 'From', type: 'date', hint: 'loaned in or out' },
    { name: 'to', label: 'Until, or the day they left', type: 'date', hint: 'loaned in or out, or left the team' },
  ], async () => {
    const values = modalValues();
    bud.data = await api('/api/budgets/people', { method: 'PUT',
      body: { full_name: p.name, unit: p.unit, kind: values.kind, from: values.from, to: values.to } });
    closeModal();
    toast(`${p.name} saved.`, 'ok');
    renderBudgets();
    registerChanged();
  }, { kind: p.set ? p.kind : 'default', from: p.from || '', to: p.to || '' });
}

/* ------------------------------------------------------------ closed jobs */

function closedPanel(closed) {
  return el('details', { class: 'panel bu-closed' },
    el('summary', {}, el('b', {}, `Closed jobs (${closed.length})`),
      el('span', { class: 'muted' }, ' · no longer on the Projects list; their last figures are kept')),
    el('div', { class: 'table-wrap' }, el('table', { class: 'data' },
      el('thead', {}, el('tr', {}, ...['Job', 'Last seen', 'BISpark budget', 'Your budget', 'Spent', 'Left'].map((h) => el('th', {}, h)))),
      el('tbody', {}, ...closed.map((j) => el('tr', { class: 'clickable', onclick: () => openJob(j.job_number) },
        el('td', {}, el('b', {}, j.job_number), el('div', { class: 'muted bu-title' }, j.title)),
        el('td', {}, buDay(j.last_seen)),
        el('td', { class: 'num' }, fmt.mm(j.budget_mm)),
        el('td', { class: 'num' }, fmt.mm(j.team_budget_mm)),
        el('td', { class: 'num' }, fmt.mm(j.team_spent_mm)),
        el('td', { class: 'num' }, toned(j.team_left_mm, tone.amount, fmt.mm))))))));
}

/* --------------------------------------------------------- automate it */

function automatePanel(data) {
  const r = data.requests || {};
  const line = (ok, text) => el('li', {}, el('span', { class: `pill pill-${ok ? 'ok' : 'info'}` }, ok ? 'Saved' : 'Not yet'), ' ', text);
  return el('details', { class: 'panel bu-auto', open: !(r.projects && r.spend) && data.jobs.length ? true : null },
    el('summary', {}, el('b', {}, 'Fetch them every night'),
      el('span', { class: 'muted' }, ' · the manager kit on your laptop, the same way as the timesheets')),
    el('ul', { class: 'bu-steps' },
      line(r.projects, 'The Projects list request'),
      line(r.spend, r.spend ? `The staff expenditure request (copied on ${r.spend_job})` : 'The staff expenditure request')),
    el('p', { class: 'muted' },
      'Copy each request the way you did for the timesheets: open the page in Edge, press F12, open Network, export, '
      + 'then right-click the export entry > Copy > Copy as PowerShell, and paste it here. '
      + `For the staff expenditure, do it from any one project's MH Expenditure page: the kit asks the same of each job on your list (at most ${data.max_spend_exports} a night). `
      + 'Then download a new manager kit on the Timesheets tab and run its setup.bat again. Every request it makes is written in its log.'),
    el('div', { class: 'row-actions' },
      el('button', { class: 'btn', type: 'button', onclick: () => pasteRequest('projects') }, 'Paste the Projects list request'),
      el('button', { class: 'btn', type: 'button', onclick: () => pasteRequest('spend') }, 'Paste the staff expenditure request')));
}

function pasteRequest(which) {
  openModal(which === 'projects' ? 'The Projects list request' : 'The staff expenditure request', [
    { name: 'capture', label: 'Paste what Copy as PowerShell gave', type: 'textarea', full: true },
  ], async () => {
    const values = modalValues();
    await api('/api/budgets/requests', { method: 'PUT',
      body: { [`${which}_capture`]: values.capture || '' } });
    closeModal();
    toast('Saved. Download a new manager kit on the Timesheets tab to use it.', 'ok');
    loadBudgets(true);
  });
}

/* ------------------------------------------------------------- bringing in */

async function bringInFiles(input) {
  const files = Array.from(input.files || []);
  input.value = '';
  if (!files.length) return;
  try {
    const result = await api('/api/budgets/import', { method: 'POST', body: { files: await filesBase64(files) } });
    const parts = [];
    if (result.jobs_listed) parts.push(`${result.jobs_listed} jobs from the Projects list`);
    if (result.spend_jobs.length) parts.push(`staff expenditure for ${result.spend_jobs.length} job${result.spend_jobs.length === 1 ? '' : 's'}`);
    if (result.rows_filled) parts.push(`${result.rows_filled} missing days of your team filled in`);
    toast(parts.length ? `Brought in ${parts.join(', ')}.` : 'Nothing new in those files.', 'ok');
    for (const message of [...result.warnings, ...result.errors]) toast(message, 'bad');
    loadBudgets(true);
    if ((result.projects_updated || []).length || result.rows_filled) registerChanged();
  } catch (error) {
    toast(errorText(error), 'bad');
  }
}

/* ------------------------------------------------------------------ wiring */

(function wireBudgets() {
  const refresh = $('#budgets-refresh');
  if (refresh) refresh.addEventListener('click', () => loadBudgets(true));
  const input = $('#budgets-files');
  if (input) input.addEventListener('change', () => bringInFiles(input));
}());

window.budgets = { load: loadBudgets };
