/* Selecao+ — check-ins: who has free hours, who needs to ease off, what to ask.
 *
 * The Check-ins tab, and the short version of it at the top of Overview. The
 * server works out every figure from the timesheets, the task list and the
 * calendar (workload_app/checkins.py); nothing here is typed in.
 *
 * Built on app.js's helpers (el, api, setChildren, engineerColor, fmt) and
 * charts.js's svgEl and hoverable.
 */
'use strict';

const checkin = {
  data: null,
  team: 'all',
  busy: false,
};

const SIGNAL_TONE = { rest: 'bad', busy: 'warn', fresh: 'ok', steady: 'info' };
const LEVEL_TONE = { now: 'bad', soon: 'warn', note: 'info' };
const LEVEL_LABEL = { now: 'Ask now', soon: 'This week', note: 'Good to know' };

function ciDay(iso, opts = { weekday: 'short', day: 'numeric' }) {
  if (!iso) return '—';
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, opts);
}

function ciHours(value) {
  return `${fmt.hours(value)} h`;
}

/* ----------------------------------------------------------- loading */

async function loadCheckins(force = false) {
  if (checkin.busy) return;
  if (checkin.data && !force) { renderCheckins(); return; }
  checkin.busy = true;
  try {
    checkin.data = await api('/api/checkins');
  } catch (error) {
    setChildren($('#checkins-body'), el('div', { class: 'msg msg-bad' }, error.message));
    return;
  } finally {
    checkin.busy = false;
  }
  renderCheckins();
  renderCheckinSummary();
}

function visiblePeople() {
  const people = (checkin.data && checkin.data.people) || [];
  return checkin.team === 'all' ? people
    : people.filter((p) => (p.team_name || 'Not in a team') === checkin.team);
}

/* ------------------------------------------------------------ the tab */

function renderCheckins() {
  const data = checkin.data;
  const body = $('#checkins-body');
  if (!data || !body) return;
  renderCheckinTeams();
  const people = visiblePeople();
  if (!people.length) {
    setChildren(body, el('div', { class: 'empty' },
      'Nobody on the team yet. Import a timesheet export and everyone on it appears here.'));
    return;
  }
  setChildren(body,
    data.stale ? el('div', { class: 'msg msg-warn' },
      `The newest timesheet is from ${ciDay(data.through, { day: 'numeric', month: 'short' })}, `
      + 'so how loaded people are reads from then. Import the latest exports to bring it up to date.')
      : null,
    checkinStats(people),
    el('section', { class: 'panel' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Free hours, the next two weeks'),
          el('p', { class: 'muted' },
            'What is left of each working day once their usual project work, tasks and '
            + 'requests are laid out, the same way the Planner lays out Today. '
            + 'Darker means more free.'))),
      freeGrid(people, data),
      canTake(people)),
    el('section', { class: 'panel' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Each person'),
          el('p', { class: 'muted' },
            `Hours booked each week against the hours they had, over the last `
            + `${data.weeks.length} weeks up to ${ciDay(data.through, { day: 'numeric', month: 'short' })}. `
            + 'Weeks well over the line wear people down; a light spell or leave '
            + 'means they are fresh and can take more.'))),
      el('div', { class: 'ci-grid' }, ...people.map((p) => personCard(p, data)))),
    el('section', { class: 'panel ci-all' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Everything to ask'),
          el('p', { class: 'muted' },
            'Every checkpoint in one list, most pressing first. Each is worked out '
            + 'from the task list, the timesheets and the calendar.'))),
      checkpointTable(people)));
}

function renderCheckinTeams() {
  const select = $('#checkins-team');
  if (!select) return;
  const teams = [...new Set(checkin.data.people.map((p) => p.team_name || 'Not in a team'))].sort();
  select.closest('label').hidden = teams.length < 2;
  setChildren(select,
    el('option', { value: 'all' }, 'Every team'),
    ...teams.map((t) => el('option', { value: t }, t)));
  if (checkin.team !== 'all' && !teams.includes(checkin.team)) checkin.team = 'all';
  select.value = checkin.team;
}

function checkinStats(people) {
  const count = (key) => people.filter((p) => p.signal.key === key).length;
  const free = people.reduce((sum, p) => sum + p.free_week, 0);
  const points = people.reduce((sum, p) => sum + p.checkpoints.length, 0);
  const urgent = people.reduce((sum, p) => sum + p.checkpoints
    .filter((c) => c.level === 'now').length, 0);
  const card = (label, value, toneName, sub) => el('div', { class: 'card' },
    el('div', { class: 'label' }, label),
    el('div', { class: `value ${toneName ? `v-${toneName}` : ''}` }, value),
    el('div', { class: 'sub' }, sub));
  const names = (key) => people.filter((p) => p.signal.key === key)
    .map((p) => p.name).join(', ') || 'nobody';
  return el('div', { class: 'cards cards-4' },
    card('Need to ease off', count('rest'), count('rest') ? 'bad' : 'ok', names('rest')),
    card('Fresh, can take more', count('fresh'), count('fresh') ? 'ok' : '', names('fresh')),
    card('Free hours this week', ciHours(free), free ? 'ok' : 'warn',
      free ? 'across the people shown' : 'everyone is full this week'),
    card('Things to ask', points, urgent ? 'bad' : '',
      urgent ? `${urgent} need asking now` : 'nothing urgent'));
}

/* ------------------------------------------------------- free hours */

function freeGrid(people, data) {
  const perDay = data.hours_per_day || 8;
  const head = el('tr', {},
    el('th', {}, 'Person'),
    ...data.days.map((d) => el('th', { class: 'num' },
      el('span', { class: 'ci-dayhead' }, ciDay(d, { weekday: 'short' }),
        el('b', {}, ciDay(d, { day: 'numeric' }))))),
    el('th', { class: 'num' }, 'This week'),
    el('th', { class: 'num' }, 'Two weeks'));
  const rows = people.map((p) => el('tr', {},
    el('td', {}, el('span', { class: 'who-chip' },
      el('span', { class: 'swatch', style: `background:${engineerColor(p.name)}` }), p.name)),
    ...data.days.map((d, i) => {
      const day = p.days[i];
      if (!day) return el('td', {});
      if (day.away) return el('td', { class: 'ci-cell ci-away', 'data-sort': '-1' }, 'away');
      const share = Math.min(1, day.free / perDay);
      const cell = el('td', {
        class: `ci-cell ${day.free >= 0.5 ? 'ci-free' : ''} ${day.over > 0 ? 'ci-over' : ''}`,
        style: `--free:${share.toFixed(2)}`,
        'data-sort': day.free,
      }, day.free >= 0.5 ? fmt.hours(day.free) : day.over > 0 ? `+${fmt.hours(day.over)}` : '·');
      hoverable(cell, `<b>${escapeHtml(p.name)}, ${ciDay(day.date, { weekday: 'long', day: 'numeric', month: 'short' })}</b>`
        + `<br>${fmt.hours(day.free)} h free · ${fmt.hours(day.booked)} h planned`
        + (day.over > 0 ? `<br>${fmt.hours(day.over)} h more than fits the day` : ''));
      return cell;
    }),
    el('td', { class: 'num' }, el('b', {}, fmt.hours(p.free_week))),
    el('td', { class: 'num' }, fmt.hours(p.free_total))));
  const totals = el('tr', { class: 'ci-total' },
    el('td', {}, 'Everyone shown'),
    ...data.days.map((d, i) => el('td', { class: 'num' },
      fmt.hours(people.reduce((s, p) => s + ((p.days[i] && p.days[i].free) || 0), 0)))),
    el('td', { class: 'num' }, el('b', {}, fmt.hours(people.reduce((s, p) => s + p.free_week, 0)))),
    el('td', { class: 'num' }, fmt.hours(people.reduce((s, p) => s + p.free_total, 0))));
  return el('div', { class: 'table-wrap ci-free-wrap' },
    el('table', { class: 'ci-free-table' },
      el('thead', {}, head), el('tbody', {}, ...rows), el('tfoot', {}, totals)));
}

function canTake(people) {
  const ready = people
    .filter((p) => p.free_week >= 1 && p.signal.key !== 'rest')
    .sort((a, b) => (a.signal.key !== 'fresh') - (b.signal.key !== 'fresh')
      || b.free_week - a.free_week);
  if (!ready.length) {
    return el('p', { class: 'ci-take muted' },
      'Nobody shown has a free hour this week. A new request means moving something: '
      + 'the Planner\'s Next days shows what a handover would do.');
  }
  return el('div', { class: 'ci-take' },
    el('span', { class: 'muted' }, 'Give the next job to'),
    ...ready.slice(0, 5).map((p) => el('span', { class: `pill pill-${p.signal.key === 'fresh' ? 'ok' : 'info'}` },
      `${p.name} · ${fmt.hours(p.free_week)} h this week`
      + (p.next_free ? ` · from ${ciDay(p.next_free)}` : ''))));
}

/* --------------------------------------------------------- per person */

function loadBars(weeks, color) {
  const w = 220, h = 64, pad = 2;
  const peak = Math.max(1.3, ...weeks.map((x) => x.load || 0));
  const step = w / weeks.length;
  const y = (v) => h - (v / peak) * (h - 4);
  const svg = svgEl('svg', { viewBox: `0 0 ${w} ${h}`, class: 'ci-bars', role: 'img',
    preserveAspectRatio: 'none', 'aria-label': 'Load week by week' });
  weeks.forEach((week, i) => {
    const load = week.load;
    const kind = load === null ? 'away' : load >= 1.05 ? 'over' : load < 0.75 ? 'light' : 'on';
    const top = load === null ? h - 3 : y(load);
    const bar = svgEl('rect', {
      x: i * step + pad, y: top, width: step - pad * 2, height: Math.max(3, h - top),
      rx: 2, class: `ci-bar ci-bar-${kind}`,
    });
    hoverable(bar, `<b>Week of ${ciDay(week.week, { day: 'numeric', month: 'short' })}</b><br>`
      + (load === null ? 'away all week'
        : `${fmt.hours(week.hours)} h of ${fmt.hours(week.capacity)} h · ${Math.round(load * 100)}%`
        + (week.overtime ? `<br>${fmt.hours(week.overtime)} h overtime` : '')
        + (week.days_off ? `<br>${week.days_off} day(s) off` : '')));
    svg.append(bar);
  });
  svg.append(svgEl('line', { x1: 0, x2: w, y1: y(1), y2: y(1), class: 'ci-line' }));
  return svg;
}

function personCard(p, data) {
  const s = p.signal;
  const color = engineerColor(p.name);
  const facts = [
    s.load !== null ? `${Math.round(s.load * 100)}% over 4 weeks` : null,
    s.overtime ? `${fmt.hours(s.overtime)} h overtime` : null,
    p.last_day_off ? `last day off ${ciDay(p.last_day_off, { day: 'numeric', month: 'short' })}` : null,
  ].filter(Boolean);
  return el('article', { class: `ci-card ci-${s.key}` },
    el('div', { class: 'ci-head' },
      el('div', { class: 'ci-who' },
        el('div', {},
          el('span', { class: 'swatch', style: `background:${color}` }),
          el('b', { class: 'eng-name' }, p.name)),
        el('div', { class: 'muted' }, `${p.grade_label}${p.team_name ? ` · ${p.team_name}` : ''}`)),
      el('span', { class: `pill pill-${SIGNAL_TONE[s.key]}` }, s.label)),
    el('div', { class: 'ci-chart' },
      loadBars(p.weeks, color),
      el('div', { class: 'eng-trend-labels' },
        el('span', {}, ciDay(data.weeks[0], { day: 'numeric', month: 'short' })),
        el('span', {}, 'line = their hours'),
        el('span', {}, ciDay(data.weeks[data.weeks.length - 1], { day: 'numeric', month: 'short' })))),
    el('p', { class: 'ci-facts' }, facts.join(' · ')),
    el('p', { class: 'ci-free-line' },
      p.free_week >= 0.5
        ? [el('b', {}, ciHours(p.free_week)), ' free this week',
          p.free_total > p.free_week ? `, ${ciHours(p.free_total)} over two weeks` : '']
        : p.free_total >= 0.5
          ? ['Full this week; ', el('b', {}, ciHours(p.free_total)), ' free next week']
          : 'No free hours in the next two weeks'),
    p.checkpoints.length
      ? el('ul', { class: 'ci-points' }, ...p.checkpoints.map((c) => el('li', { class: `ci-point ci-${c.level}` },
        el('span', { class: `pill pill-${LEVEL_TONE[c.level]}` }, LEVEL_LABEL[c.level]),
        el('span', {}, c.text))))
      : el('p', { class: 'muted ci-none' }, 'Nothing to raise. A quick hello will do.'));
}

function checkpointTable(people) {
  const rank = { now: 0, soon: 1, note: 2 };
  const rows = people.flatMap((p) => p.checkpoints.map((c) => ({ ...c, name: p.name })))
    .sort((a, b) => rank[a.level] - rank[b.level] || a.name.localeCompare(b.name));
  if (!rows.length) return el('div', { class: 'empty' }, 'Nothing to ask anybody this week.');
  return el('div', { class: 'table-wrap' },
    el('table', {},
      el('thead', {}, el('tr', {},
        el('th', {}, 'When'), el('th', {}, 'Person'), el('th', {}, 'What to ask'))),
      el('tbody', {}, ...rows.map((c) => el('tr', {},
        el('td', { 'data-sort': rank[c.level] },
          el('span', { class: `pill pill-${LEVEL_TONE[c.level]}` }, LEVEL_LABEL[c.level])),
        el('td', {}, el('span', { class: 'who-chip' },
          el('span', { class: 'swatch', style: `background:${engineerColor(c.name)}` }), c.name)),
        el('td', { class: 'ci-ask' }, c.text))))));
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* ------------------------------------------- the strip on Overview */

function renderCheckinSummary() {
  const host = $('#overview-checkins');
  const data = checkin.data;
  if (!host) return;
  if (!data || !data.people.length) { host.hidden = true; return; }
  host.hidden = false;
  const by = (key) => data.people.filter((p) => p.signal.key === key);
  const urgent = data.people.flatMap((p) => p.checkpoints
    .filter((c) => c.level === 'now' && c.kind !== 'rest').map((c) => ({ ...c, name: p.name })));
  const take = data.can_take.slice(0, 3);
  const item = (toneName, title, text) => el('div', { class: `ci-sum ci-sum-${toneName}` },
    el('b', {}, title), el('span', {}, text));
  setChildren(host,
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, 'This week with the team'),
        el('p', { class: 'muted' }, 'Who needs a lighter week, who has room, and what to ask. Worked out from the timesheets and tasks.')),
      el('button', { class: 'btn btn-sm', type: 'button', onclick: () => switchView('checkins') },
        'Open check-ins')),
    el('div', { class: 'ci-sums' },
      item('bad', by('rest').length ? `${by('rest').map((p) => p.name).join(', ')}` : 'Nobody overloaded',
        by('rest').length ? `${by('rest').length > 1 ? 'need' : 'needs'} to ease off: move or hold some of their work` : 'nobody has been over their hours for weeks'),
      item('ok', take.length ? take.map((p) => `${p.name} ${fmt.hours(p.free_week)} h`).join(', ') : 'No free hours',
        take.length ? 'free this week: give the next job here' : 'everyone is full this week'),
      item(urgent.length ? 'warn' : 'info', urgent.length ? `${urgent.length} to ask now` : 'Nothing else urgent',
        urgent.length ? urgent.slice(0, 2).map((c) => `${c.name}: ${c.text.split('. ')[0]}`).join(' · ')
          : 'nothing late or blocked')));
}

/* ---------------------------------------------------------- wiring */

(function wireCheckins() {
  const select = $('#checkins-team');
  if (select) {
    select.addEventListener('change', (event) => {
      checkin.team = event.target.value;
      renderCheckins();
    });
  }
  const refresh = $('#checkins-refresh');
  if (refresh) refresh.addEventListener('click', () => loadCheckins(true));
})();

window.checkins = {
  load: loadCheckins,
  summary: () => loadCheckins(true),
  reset: () => { checkin.data = null; },
};
