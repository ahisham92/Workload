/* Selecao+ — the weekly report, and notifications on the phone.
 *
 * The Weekly tab. The server puts the report together from what Check-ins,
 * the staffing forecast and the submissions plan already work out
 * (workload_app/weekly.py); nothing here is typed in. Below it, the switch
 * for notifications on this phone (push.js).
 *
 * Built on app.js's helpers (el, api, setChildren, fmt, toast, switchView).
 */
'use strict';

const week = { data: null, busy: false };

const WK_TONE_LABEL = { bad: 'First', warn: 'This week', ok: 'When you can' };

function wkDay(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  if (!iso) return '—';
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, opts);
}

const wkHours = (value) => `${fmt.hours(value)} h`;

async function loadWeekly() {
  if (week.busy) return;
  week.busy = true;
  try {
    week.data = await api('/api/weekly');
  } catch (error) {
    setChildren($('#weekly-body'), el('div', { class: 'msg msg-bad' }, error.message));
    return;
  } finally {
    week.busy = false;
  }
  renderWeekly();
  if (window.selecaoPush) window.selecaoPush.show($('#weekly-push'));
}

/* ------------------------------------------------------------ the report */

function renderWeekly() {
  const r = week.data;
  if (!r) return;
  const last = r.last_week;
  const card = (label, value, tone, sub) => el('div', { class: 'card' },
    el('div', { class: 'label' }, label),
    el('div', { class: `value ${tone ? `v-${tone}` : ''}` }, value),
    el('div', { class: 'sub' }, sub));
  const late = r.this_week.due.filter((d) => d.late).length;
  const loadTone = last.load === null ? '' : last.load > 1.05 ? 'bad' : last.load < 0.75 ? 'warn' : 'ok';
  setChildren($('#weekly-body'),
    r.stale ? el('div', { class: 'msg msg-warn' },
      `The newest timesheet is from ${wkDay(r.through)}, so last week's figures are behind. `
      + 'Upload the latest exports to bring the report up to date.') : null,
    el('section', { class: 'panel wk-head' },
      el('div', { class: 'wk-week' }, `${r.unit} · ${r.title}`),
      el('p', { class: 'wk-headline' }, r.headline)),
    el('section', { class: 'panel' },
      el('div', { class: 'panel-head' }, el('div', {},
        el('h3', {}, 'What to do this week'),
        el('p', { class: 'muted' }, 'Most pressing first. Red is for the start of the week; '
          + 'tap Go to open the tab where you act on it.'))),
      r.todo.length ? el('ol', { class: 'wk-todo' }, r.todo.map((t) => el('li', { class: `wk-${t.tone}` },
        el('span', { class: 'wk-tag' }, WK_TONE_LABEL[t.tone] || ''),
        el('span', { class: 'wk-text' }, t.text),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: () => switchView(t.view) }, 'Go'))))
        : el('div', { class: 'empty' }, 'Nothing needs you this week: the plan holds.'),
      r.more ? el('p', { class: 'muted small' },
        `And ${r.more} more: Check-ins and the Planner list every one.`) : null),
    el('div', { class: 'cards cards-4' },
      card('Booked last week', last.load === null ? '—' : fmt.pct0(last.load), loadTone,
        last.week ? `${wkHours(last.hours)} of ${wkHours(last.capacity)}, week of ${wkDay(last.week)}`
          : 'no timesheets yet'),
      card('Overtime last week', wkHours(last.overtime), last.overtime > 0 ? 'warn' : 'ok',
        last.overtime > 0 ? 'hours past people\'s day' : 'nobody stayed late'),
      card('Due this week', String(r.this_week.due.length), late ? 'bad' : r.this_week.due.length ? 'warn' : 'ok',
        late ? `${late} already late` : 'submissions'),
      card('Free this week', wkHours(r.this_week.free_week), r.this_week.free_week ? 'ok' : 'warn',
        r.this_week.room.length ? `room: ${r.this_week.room.slice(0, 3).map((p) => p.name).join(', ')}`
          : 'everyone is full')),
    lastWeekPanel(r),
    thisWeekPanel(r),
    (r.staffing.length || r.unstaffed.length) ? el('section', { class: 'panel' },
      el('div', { class: 'panel-head' }, el('div', {},
        el('h3', {}, 'People to ask for'),
        el('p', { class: 'muted' }, 'From the staffing forecast: where the work coming needs more people '
          + 'than the team has. Ask early; the date to ask by is in each line.'))),
      r.staffing.map((s) => el('div', { class: `msg ${s.severity === 'now' ? 'msg-bad' : 'msg-warn'}` },
        el('b', {}, s.title), el('div', { class: 'small' }, s.detail))),
      r.unstaffed.length ? el('p', {}, el('b', {}, 'Nobody booked on: '),
        r.unstaffed.map((p) => p.name).join(', '), '.') : null) : null);
}

function lastWeekPanel(r) {
  const last = r.last_week;
  if (!last.week) return null;
  const most = Math.max(1.3, ...last.people.map((p) => p.load || 0));
  const toneOf = { rest: 'bad', busy: 'warn', fresh: 'ok', steady: 'info' };
  const projectMax = Math.max(1, ...last.projects.map((p) => p.hours));
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, `Last week, person by person`),
      el('p', { class: 'muted' }, `Week of ${wkDay(last.week)}. Each bar is the hours a person booked `
        + 'against the hours they had; past the line is overtime. Red has been over for weeks and '
        + 'needs a lighter week, green has room for more.'))),
    el('div', { class: 'wk-bars' }, last.people.map((p) => el('div', { class: 'wk-bar-row' },
      el('span', { class: 'wk-bar-name' }, p.name),
      el('span', { class: 'wk-bar-track' },
        el('span', { class: `wk-bar wk-bar-${toneOf[p.signal] || 'info'}`,
          style: `width:${Math.min(100, ((p.load || 0) / most) * 100)}%` }),
        el('span', { class: 'wk-bar-line', style: `left:${(1 / most) * 100}%` })),
      el('span', { class: 'wk-bar-value' }, `${fmt.pct0(p.load)} · ${wkHours(p.hours)}`),
      el('span', { class: 'wk-bar-note muted small' }, p.signal_label)))),
    last.projects.length ? el('div', {},
      el('h4', { class: 'wk-sub' }, 'Where the hours went'),
      el('div', { class: 'wk-bars' }, last.projects.map((p) => el('div', { class: 'wk-bar-row' },
        el('span', { class: 'wk-bar-name', title: p.number }, p.name),
        el('span', { class: 'wk-bar-track' },
          el('span', { class: 'wk-bar wk-bar-info', style: `width:${(p.hours / projectMax) * 100}%` })),
        el('span', { class: 'wk-bar-value' }, wkHours(p.hours))))),
      last.other_projects ? el('p', { class: 'muted small' },
        `And ${last.other_projects} smaller project${last.other_projects === 1 ? '' : 's'}.`) : null) : null);
}

function thisWeekPanel(r) {
  const t = r.this_week;
  const lines = [];
  if (t.ease_off.length) lines.push(['bad', 'Needs to ease off: ', t.ease_off.join(', ')]);
  if (t.heavy.length) lines.push(['warn', 'Heavy, keep an eye: ', t.heavy.join(', ')]);
  if (t.room.length) lines.push(['ok', 'Has room: ', t.room.map((p) => `${p.name} (${wkHours(p.free_week)})`).join(', ')]);
  if (t.meetings) lines.push(['info', 'In the diary: ', `${t.meetings} team meeting${t.meetings === 1 ? '' : 's'} and one-to-ones`]);
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, 'This week'),
      el('p', { class: 'muted' }, 'What is due, and who can take the next piece of work. '
        + 'Late ones need a new date agreed with the client or the team.'))),
    t.due.length ? el('div', { class: 'table-wrap' }, el('table', {},
      el('thead', {}, el('tr', {}, el('th', {}, 'Due'), el('th', {}, 'Submission'),
        el('th', {}, 'Project'), el('th', { class: 'num' }, 'Done'), el('th', {}, 'Who'))),
      el('tbody', {}, t.due.map((d) => el('tr', {},
        el('td', {}, d.late ? el('b', { class: 'v-bad' }, `Late (was ${wkDay(d.was_due, { day: 'numeric', month: 'short' })})`)
          : wkDay(d.date)),
        el('td', {}, d.name),
        el('td', { title: d.project_name }, d.project),
        el('td', { class: 'num' }, d.progress === null || d.progress === undefined ? '—' : fmt.pct0(d.progress)),
        el('td', {}, d.people.join(', ')))))))
      : el('p', { class: 'muted' }, 'No submissions due this week.'),
    lines.length ? el('ul', { class: 'wk-lines' }, lines.map(([tone, label, text]) =>
      el('li', {}, el('span', { class: `wk-dot wk-dot-${tone}` }), el('b', {}, label), text))) : null);
}

async function downloadWeekly() {
  try {
    const result = await api('/api/weekly/download');
    const bytes = Uint8Array.from(atob(result.content_base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: 'text/html' }));
    const link = el('a', { href: url, download: result.filename });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (error) {
    toast(error.message, 'bad');
  }
}

/* ------------------------------------------------------------- wiring */

(function wireWeekly() {
  const refresh = $('#weekly-refresh');
  if (refresh) refresh.addEventListener('click', () => loadWeekly());
  const download = $('#weekly-download');
  if (download) download.addEventListener('click', downloadWeekly);
}());

window.weekly = { load: loadWeekly };
