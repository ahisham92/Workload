/* Selecao+ — Bring in data, and the Start here card on the Overview.
 *
 * One place for every file the app reads: the BISpark timesheet exports, the
 * Projects list and a job's staff expenditure. They are
 * chosen together, in any mix; the server tells them apart by their columns
 * (workload_app/bringin.py), says what each will fill, and only writes when
 * Bring in is tapped. The other tabs' own upload buttons still work, and a
 * drawing list dropped here is still read, though the team no longer keeps
 * one, so the screen does not ask for it.
 *
 * The Start here card leads somebody new through the first setup, in order,
 * ticking off what is done, and goes away once it is all done (or when they
 * hide it).
 *
 * Built on app.js's helpers (el, api, setChildren, toast, fmt, filesBase64,
 * refreshAll, switchView) and checkins.js's statCard.
 */
'use strict';

const bring = { state: null, check: null, files: null, done: null, busy: false };

/** Each kind of file: what it is, where it comes from, and what it fills. */
const BI_KINDS = [
  { key: 'timesheets', title: 'Timesheets', from: 'BISpark timesheet export, one per person or all at once',
    fills: 'The team, the projects, their phases and every hour. Everything else is worked out from these.',
    has: (s) => s.timesheets.rows > 0,
    said: (s) => `${fmt.int(s.timesheets.rows)} rows for ${s.timesheets.people} ${s.timesheets.people === 1 ? 'person' : 'people'}, `
      + `${fmt.date(s.timesheets.first_date)} to ${fmt.date(s.timesheets.last_date)}` },
  { key: 'projects', title: 'Budgets', from: 'BISpark › Projects, exported as Summarized data',
    fills: 'Each job\'s budget, what is spent and what is left, on Budgets and Projects.',
    has: (s) => s.projects.jobs > 0,
    said: (s) => `${fmt.int(s.projects.jobs)} jobs, ${fmt.int(s.projects.with_budget)} with a budget` },
  { key: 'spend', title: 'Who spent each job', from: 'BISpark › a project › MH Expenditure › Staff expenditure',
    fills: 'How much of a job is your team\'s, and the days your team\'s own exports missed.',
    has: (s) => s.spend.jobs > 0,
    said: (s) => `${fmt.int(s.spend.jobs)} job(s)` },
];

const BI_STEP_LABEL = { timesheets: 'Timesheets', budgets: 'Budgets', drawings: 'Drawing list' };

async function loadBringIn() {
  try {
    bring.state = await api('/api/bring-in');
  } catch (error) {
    setChildren($('#bringin-body'), el('div', { class: 'msg msg-bad' }, error.message));
    return;
  }
  renderBringIn();
}

function renderBringIn() {
  const body = $('#bringin-body');
  if (!body || !bring.state) return;
  setChildren(body, chooserPanel(), resultPanel(), whoPanel(bring.state.who),
    holdsPanel(bring.state), keepUpPanel());
}

/* -------------------------------------------------------------- choosing */

function chooserPanel() {
  const input = el('input', { type: 'file', id: 'bringin-files', multiple: true,
    accept: '.xlsx,.xlsm,.csv,.tsv,.txt', hidden: true });
  input.addEventListener('change', () => checkFiles([...input.files]));
  const zone = el('label', { class: 'bi-drop', for: 'bringin-files' },
    el('span', { class: 'bi-drop-icon', 'aria-hidden': 'true' }, '⇪'),
    el('strong', {}, bring.busy ? 'Reading…' : 'Choose your files'),
    el('span', { class: 'muted' }, 'Timesheet exports, the Projects list and staff expenditures: '
      + 'all of them at once, in any mix. Or drop them here.'),
    input);
  for (const name of ['dragenter', 'dragover']) {
    zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add('is-over'); });
  }
  zone.addEventListener('dragleave', () => zone.classList.remove('is-over'));
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    zone.classList.remove('is-over');
    checkFiles([...event.dataTransfer.files]);
  });
  return el('section', { class: 'panel' }, zone);
}

async function checkFiles(files) {
  if (!files.length || bring.busy) return;
  bring.busy = true;
  bring.done = null;
  renderBringIn();
  try {
    bring.check = await voyage.during(`Reading ${files.length} file(s)`, async () => {
      // Kept for Bring in, which sends them again: the server that answers it
      // may not be the one that did the check.
      bring.files = await filesBase64(files);
      return api('/api/bring-in/check', { method: 'POST', body: { files: bring.files } });
    });
  } catch (error) {
    bring.check = null;
    toast(errorText(error), 'bad');
  } finally {
    bring.busy = false;
  }
  renderBringIn();
}

/* ------------------------------------------------- what the files will do */

function resultPanel() {
  if (bring.done) return donePanel(bring.done);
  const check = bring.check;
  if (!check) return null;
  const ts = check.timesheets;
  const known = check.files.filter((f) => f.kind);
  return el('section', { class: 'panel' },
    el('h3', {}, 'What these files are'),
    el('p', { class: 'muted' }, 'Each file was recognised by its columns. Nothing is written yet.'),
    el('ul', { class: 'bi-files' }, ...check.files.map((f) => el('li', {},
      el('span', { class: `pill ${f.kind ? 'pill-ok' : 'pill-bad'}` }, f.label),
      el('span', { class: 'bi-file' }, f.filename),
      f.note && f.kind ? el('span', { class: 'muted' }, ` ${f.note}`) : null,
      f.fills ? el('div', { class: 'muted bi-fills' }, `Fills ${f.fills}.`) : null))),
    ts ? el('div', { class: `msg ${ts.left_out ? 'msg-bad' : 'msg-info'}` },
      ts.left_out
        ? 'The timesheet exports could not be read, so they are left out. The other files can still come in.'
        : `Timesheets: ${fmt.int(ts.rows)} rows, ${fmt.hours(ts.hours)} hours for ${ts.people} ${ts.people === 1 ? 'person' : 'people'}, `
          + `${fmt.date(ts.first_date)} to ${fmt.date(ts.last_date)}.`
          + (ts.new_people.length ? ` New on the team: ${ts.new_people.join(', ')}.` : '')
          + (ts.new_projects ? ` ${ts.new_projects} new project(s) will be set up.` : '')) : null,
    ...(ts ? [...ts.errors, ...ts.warnings] : []).map((m) => el('div', { class: 'msg msg-warn' }, m)),
    ts && !ts.left_out ? el('p', { class: 'muted' },
      'Each person in these exports gets exactly the rows the exports hold for them; '
      + 'anybody not in them is left alone. A dated copy of the unit is kept first.') : null,
    el('div', { class: 'row', style: 'margin-bottom:0' },
      el('button', { class: 'btn btn-primary', type: 'button', disabled: !check.ready,
        onclick: applyFiles },
      `Bring in ${known.length} file${known.length === 1 ? '' : 's'}`),
      el('button', { class: 'btn btn-ghost', type: 'button',
        onclick: () => { bring.check = null; renderBringIn(); } }, 'Start over')));
}

async function applyFiles() {
  const check = bring.check;
  if (!check || bring.busy) return;
  bring.busy = true;
  try {
    bring.done = await voyage.during('Bringing it in', () => api(
      '/api/bring-in/apply', { method: 'POST', body: { token: check.token, files: bring.files } }));
    bring.check = null;
    bring.files = null;
    bring.state = bring.done.state;
    const fine = bring.done.steps.every((s) => s.ok);
    toast(fine ? 'Brought in. Every tab is up to date.' : 'Brought in, with something to look at.',
      fine ? 'ok' : 'bad');
    await refreshAll();
  } catch (error) {
    toast(errorText(error), 'bad');
  } finally {
    bring.busy = false;
  }
  renderBringIn();
}

function donePanel(done) {
  const drawings = done.steps.find((s) => s.kind === 'drawings' && s.ok);
  const proposals = drawings ? drawings.result.proposals || [] : [];
  return el('section', { class: 'panel' },
    el('h3', {}, 'Brought in'),
    ...done.steps.map((s) => el('div', { class: `msg ${s.ok ? 'msg-ok' : 'msg-bad'}` },
      el('strong', {}, `${BI_STEP_LABEL[s.kind]}: `), s.said,
      ...(s.ok ? [] : (s.errors || []).filter((m) => m !== s.said).map((m) => el('div', {}, m))))),
    ...done.steps.filter((s) => s.ok && s.kind === 'budgets')
      .flatMap((s) => s.result.warnings || [])
      .map((m) => el('div', { class: 'msg msg-warn' }, m)),
    proposals.length ? el('div', { class: 'msg msg-action' },
      `The drawing list says ${proposals.length} deliverable(s) have moved on `
      + '(sent to the client, or approved). ',
      el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: applyProposals },
        'Update them')) : null,
    el('div', { class: 'row', style: 'margin-bottom:0' },
      el('button', { class: 'btn btn-primary', type: 'button',
        onclick: () => switchView('overview') }, 'See the Overview'),
      el('button', { class: 'btn', type: 'button',
        onclick: () => { bring.done = null; renderBringIn(); } }, 'Bring in more')));
}

async function applyProposals() {
  try {
    const result = await api('/api/drawing-list/apply', { method: 'POST', body: {} });
    toast(`${result.applied} deliverable(s) updated from the drawing list.`, 'ok');
    const step = bring.done && bring.done.steps.find((s) => s.kind === 'drawings');
    if (step) step.result.proposals = result.proposals || [];
    await refreshAll();
  } catch (error) {
    toastError(error);
  }
  renderBringIn();
}

/* ------------------------------------------------------------ who is who */

const WHO_TONE = { team: 'ok', draftsman: 'ok', loan: 'info', out: 'warn', left: 'neutral', other: 'neutral' };

function whoDays(p) {
  if (p.kind === 'left') return p.to ? `left ${fmt.date(p.to)}` : '';
  if (p.kind !== 'loan' && p.kind !== 'out') return '';
  if (!p.from && !p.to) return 'until you change it';
  return `${p.from ? fmt.date(p.from) : 'from the start'} to ${p.to ? fmt.date(p.to) : 'until you change it'}`;
}

/** Everybody in the files and what each is to the team: set once, kept.
    Only somebody new from another unit is asked about. */
function whoPanel(who) {
  if (!who || !who.people.length) return null;
  const ask = who.people.filter((p) => p.ask);
  const rest = who.people.filter((p) => !p.ask);
  const row = (p) => el('li', { class: 'request bi-who' },
    el('span', { class: 'request-what' },
      el('b', {}, p.name),
      el('span', { class: 'muted small' }, ` · ${p.unit_label || 'unit not known'}`
        + (p.mm ? ` · ${fmt.mm(p.mm)} MM on your jobs` : ''))),
    el('span', {},
      el('span', { class: `pill pill-${WHO_TONE[p.kind] || 'neutral'}` }, p.kind_label),
      whoDays(p) ? el('div', { class: 'muted small' }, whoDays(p)) : null),
    el('button', { class: 'btn btn-sm', type: 'button', onclick: () => editWho(who, p) }, 'Change'));
  const keepAll = async () => {
    try {
      bring.state = await api('/api/bring-in/who/keep', { method: 'POST',
        body: { people: ask.map((p) => ({ name: p.name, unit: p.unit })) } });
      toast('Kept. They will not be asked about again.', 'ok');
      renderBringIn();
      if (typeof refreshAll === 'function') refreshAll().catch(() => {});
    } catch (error) { toastError(error); }
  };
  return el('section', { class: 'panel', id: 'bi-who' },
    el('h3', {}, ask.length ? `Who is who: ${ask.length} new to place` : 'Who is who'),
    el('p', { class: 'muted' },
      'Everybody in your files and what they are to your team. Only your team counts toward your budgets: '
      + 'your own people, draftsmen working for you, and people loaned in for their dates. Somebody loaned out '
      + 'to another unit is left out of your budgets and your planning for those dates. Each person is set once '
      + 'and stays; you are only asked about somebody new.'),
    ask.length ? el('ul', { class: 'request-list' }, ask.map(row)) : null,
    ask.length ? el('div', { class: 'row' },
      el('button', { class: 'btn btn-primary', type: 'button', onclick: keepAll },
        ask.length === 1 ? 'Keep as shown' : `Keep all ${ask.length} as shown`)) : null,
    rest.length ? el('details', { class: 'bi-who-rest', open: ask.length ? null : true },
      el('summary', {}, `Already placed (${rest.length})`),
      el('ul', { class: 'request-list' }, rest.map(row))) : null);
}

function editWho(who, p) {
  openModal(`What is ${p.name} to your team?`, [
    { name: 'kind', label: 'They are', type: 'select', full: true,
      options: [{ value: 'default', label: 'Go by their unit' }, ...who.kinds] },
    { name: 'from', label: 'From', type: 'date', hint: 'loaned in or out' },
    { name: 'to', label: 'Until, or the day they left', type: 'date', hint: 'blank if not known yet' },
  ], async () => {
    const values = modalValues();
    bring.state = await api('/api/bring-in/who', { method: 'PUT',
      body: { full_name: p.name, unit: p.unit, kind: values.kind, from: values.from, to: values.to } });
    closeModal();
    toast(`${p.name}: saved.`, 'ok');
    renderBringIn();
    if (typeof refreshAll === 'function') refreshAll().catch(() => {});
  }, { kind: p.set ? p.kind : 'default', from: p.from || '', to: p.to || '' });
}

/* ------------------------------------------------------- what is in now */

function holdsPanel(s) {
  return el('section', { class: 'panel' },
    el('h3', {}, 'What the app holds now'),
    el('p', { class: 'muted' }, 'Timesheets are the one thing it needs; the other two add to them.'),
    el('div', { class: 'bi-kinds' }, ...BI_KINDS.map((k) => {
      const has = k.has(s);
      return el('div', { class: `bi-kind ${has ? 'is-in' : ''}` },
        el('div', { class: 'bi-kind-head' },
          el('span', { class: `pill ${has ? 'pill-ok' : 'pill-muted'}` }, has ? 'In the app' : 'Not yet'),
          el('strong', {}, k.title)),
        el('div', {}, has ? k.said(s) : k.fills),
        el('div', { class: 'muted bi-from' }, `From: ${k.from}`));
    })));
}

function keepUpPanel() {
  return el('section', { class: 'panel' },
    el('h3', {}, 'Keeping it up to date'),
    el('p', { class: 'muted' },
      'Bring the same files in again whenever you like: each person\'s rows are replaced, never doubled. '
      + 'To have the timesheets arrive by themselves every 6 hours, set up the BISpark kit once.'),
    el('button', { class: 'btn', type: 'button', onclick: () => switchView('timesheets') },
      'Set up the kit on Timesheets'));
}

/* ------------------------------------------------- Start here, on Overview */

const START_HIDDEN = 'selecao.startHere.hidden';

function startHidden(unitId) {
  try { return localStorage.getItem(`${START_HIDDEN}.${unitId}`) === '1'; } catch (_) { return false; }
}

function hideStart(unitId) {
  try { localStorage.setItem(`${START_HIDDEN}.${unitId}`, '1'); } catch (_) { /* nothing kept */ }
  const host = $('#overview-start');
  if (host) host.hidden = true;
}

async function startHere() {
  const host = $('#overview-start');
  const unit = state.status && state.status.unit;
  if (!host || !unit) return;
  if (startHidden(unit.id)) { host.hidden = true; return; }
  let held;
  let me;
  try {
    [held, me] = await Promise.all([
      api('/api/bring-in', { quiet: true }),
      api('/api/team/me', { quiet: true }).catch(() => ({ me: '' })),
    ]);
  } catch (_) {
    host.hidden = true;
    return;
  }
  bring.state = held;
  const steps = [
    { title: 'Bring in your files', do: 'Timesheets and budgets, all in one place',
      done: held.timesheets.rows > 0 && held.projects.jobs > 0, go: 'bringin' },
    { title: 'Say which row is you', do: 'Team › Edit on your own row: your grade, and This is me',
      done: Boolean(me.me), go: 'team' },
    { title: 'Check your team', do: 'Each person\'s grade and team, so the numbers compare like with like',
      done: false, go: 'team', optional: true },
    { title: 'Learn the routine', do: 'Ten minutes a day: what to look at, and in what order',
      done: false, go: 'guide', optional: true },
  ];
  if (steps.filter((s) => !s.optional).every((s) => s.done)) { host.hidden = true; return; }
  host.hidden = false;
  setChildren(host,
    el('div', { class: 'bi-start-head' },
      el('div', {},
        el('h3', {}, 'Start here'),
        el('p', { class: 'muted' }, 'New to Selecao+? Four steps, top to bottom. This card goes once they are done.')),
      el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
        onclick: () => hideStart(unit.id) }, 'Hide')),
    el('ol', { class: 'bi-steps' }, ...steps.map((s) => el('li', { class: s.done ? 'is-done' : '' },
      el('span', { class: 'bi-tick', 'aria-hidden': 'true' }, s.done ? '✓' : ''),
      el('div', { class: 'bi-step-text' }, el('strong', {}, s.title), el('span', { class: 'muted' }, s.do)),
      s.done ? null : el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => { switchView(s.go); window.scrollTo({ top: 0 }); } }, 'Go')))));
}

window.bringin = { load: loadBringIn, startHere };
