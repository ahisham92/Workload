/* Selecao+ — growth: development time, quarterly goals, and KPIs by grade.
 *
 * The Growth tab. Everybody keeps development time every week (it is already
 * in their day on the Planner); the manager sets a few goals per person for
 * each quarter and marks them at the review three months on. The KPIs are
 * worked out by the server (workload_app/growth.py): each grade has its own
 * parts and weights, and people are ranked only against their own grade.
 *
 * Built on app.js's helpers (el, api, setChildren, openModal, modalValues,
 * toast, engineerColor, fmt).
 */
'use strict';

const grow = { data: null, quarter: '', busy: false };

const GR_PART_COLOR = {
  delivery: 'var(--series-1)', own_goals: 'var(--series-3)',
  team_support: 'var(--series-4)', developing: 'var(--series-5)',
};
const GR_RESULT_TONE = { met: 'ok', partly: 'warn', not_met: 'bad', '': 'neutral' };
const GR_LEVEL_TONE = { now: 'bad', soon: 'warn', note: 'info' };

function grDay(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  if (!iso) return '—';
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, opts);
}

async function loadGrowth(force = false) {
  if (grow.busy) return;
  if (grow.data && !force) { renderGrowth(); return; }
  grow.busy = true;
  try {
    const q = grow.quarter ? `?quarter=${encodeURIComponent(grow.quarter)}` : '';
    grow.data = await api(`/api/growth${q}`);
    grow.quarter = grow.data.quarter;
  } catch (error) {
    setChildren($('#growth-body'), el('div', { class: 'msg msg-bad' }, error.message));
    return;
  } finally {
    grow.busy = false;
  }
  renderGrowth();
}

function renderGrowth() {
  const data = grow.data;
  const body = $('#growth-body');
  if (!data || !body) return;
  const select = $('#growth-quarter');
  if (select) {
    const quarters = [...new Set([...data.quarters, data.quarter])].sort();
    setChildren(select, ...quarters.map((q) => el('option', { value: q },
      q === data.current ? `${q.replace('-', ' ')} (this quarter)` : q.replace('-', ' '))));
    select.value = data.quarter;
  }
  if (!data.people.length) {
    setChildren(body, el('div', { class: 'empty' },
      'Nobody on the team yet. Import a timesheet export and everyone on it appears here.'));
    return;
  }
  setChildren(body,
    growthTodo(data),
    growthStats(data),
    kpiPanel(data),
    goalsPanel(data));
}

/* ------------------------------------------------------------ what to do */

function growthTodo(data) {
  if (!data.todo.length) {
    return el('section', { class: 'panel gr-todo' },
      el('h3', {}, 'What to do'),
      el('p', { class: 'muted' }, 'Nothing waiting: every person has goals and nothing is due for review.'));
  }
  const action = (item) => {
    if (item.kind === 'set' && item.people && item.people.length) {
      return el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => addGoal(item.people[0]) }, `Set ${item.people[0]}'s goals`);
    }
    if (item.kind === 'review' && item.quarter && item.quarter !== data.quarter) {
      return el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => { grow.quarter = item.quarter; loadGrowth(true); } }, 'Open that quarter');
    }
    if (item.kind === 'development') {
      return el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => switchView('planner') }, 'See it on the Planner');
    }
    return null;
  };
  return el('section', { class: 'panel gr-todo' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, 'What to do'),
      el('p', { class: 'muted' }, 'Most pressing first. Goals are set at the start of each quarter and reviewed at its end.'))),
    el('ol', { class: 'gr-todo-list' }, ...data.todo.map((item) =>
      el('li', { class: `gr-todo-item gr-${GR_LEVEL_TONE[item.level] || 'info'}` },
        el('span', {}, item.text), action(item)))));
}

function growthStats(data) {
  const people = data.people;
  const withGoals = people.filter((p) => p.goals.length).length;
  const goals = people.flatMap((p) => p.goals);
  const reviewed = goals.filter((g) => g.result);
  const score = { met: 1, partly: 0.5, not_met: 0 };
  const met = reviewed.length
    ? Math.round(100 * reviewed.reduce((s, g) => s + score[g.result], 0) / reviewed.length) : null;
  const hours = people.reduce((s, p) => s + (p.development_hours || 0), 0);
  const card = (label, value, toneName, sub) => el('div', { class: 'card' },
    el('div', { class: 'label' }, label),
    el('div', { class: `value ${toneName ? `v-${toneName}` : ''}` }, value),
    el('div', { class: 'sub' }, sub));
  return el('div', { class: 'cards cards-4' },
    card('Have goals', `${withGoals} of ${people.length}`,
      withGoals === people.length ? 'ok' : 'warn', data.label),
    card('Goals set', goals.length, '', `${reviewed.length} reviewed so far`),
    card('Goals met', met === null ? '—' : `${met}%`,
      met === null ? '' : met >= 70 ? 'ok' : met >= 40 ? 'warn' : 'bad',
      met === null ? 'counted at the review' : 'met = 100, partly = 50'),
    card('Development time', `${fmt.hours(hours)} h a week`, 'ok',
      'kept in everyone\'s plan, nothing booked over it'));
}

/* ----------------------------------------------------------- KPIs by grade */

function kpiPanel(data) {
  const byName = Object.fromEntries(data.people.map((p) => [p.name, p]));
  const legend = el('div', { class: 'gr-legend' }, ...[
    ['delivery', 'Delivery'], ['own_goals', 'Own goals'],
    ['team_support', 'Team support'], ['developing', 'Developing people'],
  ].map(([key, label]) => el('span', {},
    el('i', { style: `background:${GR_PART_COLOR[key]}` }), label)));
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, `KPIs by grade, ${data.label}`),
      el('p', { class: 'muted' },
        'Each grade is measured on its own parts: a manager mostly on supporting and '
        + 'developing the team, a senior partly on the team, an engineer mostly on delivery. '
        + 'People are ranked only against the same grade. Each bar shows what makes up the score; '
        + 'a part with nothing to go on yet is left out rather than scored zero.'),
      data.delivery_from && data.delivery_from !== data.quarter
        ? el('p', { class: 'muted' }, `No project hours are booked in this quarter yet, so Delivery uses ${data.delivery_from.replace('-', ' ')} until they are.`)
        : null),
      legend),
    el('div', { class: 'gr-grades' }, ...data.grades.map((g) => el('div', { class: 'gr-grade' },
      el('div', { class: 'gr-grade-head' },
        el('h4', {}, g.label),
        el('span', { class: 'muted' }, g.weights.map((w) =>
          `${w.label} ${Math.round(w.weight * 100)}%`).join(' · '))),
      el('ol', { class: 'gr-rank' }, ...g.people.map((name) => kpiRow(byName[name])))))));
}

function kpiRow(p) {
  const counted = p.parts.filter((x) => x.score !== null);
  const weight = counted.reduce((s, x) => s + x.weight, 0) || 1;
  const bar = el('div', { class: 'gr-bar', role: 'img',
    'aria-label': `${p.name}: ${p.score === null ? 'no score yet' : Math.round(p.score)}` },
    ...counted.map((x) => el('span', {
      style: `width:${(x.score * x.weight / weight).toFixed(1)}%;background:${GR_PART_COLOR[x.key]}`,
      title: `${x.label}: ${Math.round(x.score)} × ${Math.round(x.weight * 100)}%`,
    })));
  const parts = el('div', { class: 'gr-parts' }, ...p.parts.map((x) =>
    el('span', { class: `gr-part ${x.score === null ? 'gr-part-wait' : ''}`, title: x.why },
      el('i', { style: `background:${GR_PART_COLOR[x.key]}` }),
      `${x.label} ${x.score === null ? '—' : Math.round(x.score)}`)));
  return el('li', { class: 'gr-row' },
    el('span', { class: 'gr-pos' }, p.rank ? `${p.rank}` : '·'),
    el('div', { class: 'gr-who' },
      el('span', { class: 'who-chip' },
        el('span', { class: 'swatch', style: `background:${engineerColor(p.name)}` }), p.name),
      p.leads ? el('span', { class: 'muted' }, ` leads ${p.leads}`) : null,
      parts,
      el('details', { class: 'gr-why' }, el('summary', {}, 'Why this score'),
        el('ul', {}, ...p.parts.map((x) => el('li', {}, el('b', {}, `${x.label}: `), x.why))))),
    el('div', { class: 'gr-score-wrap' }, bar,
      el('b', { class: 'gr-score' }, p.score === null ? '—' : Math.round(p.score)),
      p.complete ? null : el('span', { class: 'muted gr-prov' }, 'so far')));
}

/* ------------------------------------------------------------------ goals */

function goalsPanel(data) {
  const reviewing = data.quarter < data.current || data.todo.some((t) => t.kind === 'review' && t.quarter === data.quarter);
  return el('section', { class: 'panel' },
    el('div', { class: 'panel-head' }, el('div', {},
      el('h3', {}, `Goals and development time, ${data.label}`),
      el('p', { class: 'muted' },
        `Up to ${data.most_goals} goals each: what they will be able to do by the end of the quarter, `
        + 'and how you will know. Each person sees their own on My day, and their weekly development '
        + 'time carries them as what to work on. '
        + (reviewing ? 'Mark each one at the review.' : 'Mark each one at the review, three months on.')))),
    el('div', { class: 'gr-people' }, ...data.people.map((p) => personGoals(p, data))));
}

function personGoals(p, data) {
  return el('article', { class: 'gr-person', style: `--pc:${engineerColor(p.name)}` },
    el('header', {},
      el('div', {}, el('b', {}, p.name),
        el('div', { class: 'muted' }, [p.grade_label, p.team_name].filter(Boolean).join(' · '))),
      el('span', { class: 'pill pill-ok', title: 'Kept in their plan every week' },
        `${fmt.hours(p.development_hours)} h a week`
        + (p.development_day && data.quarter === data.current ? ` · ${grDay(p.development_day, { weekday: 'short' })}` : ''))),
    p.goals.length
      ? el('ul', { class: 'gr-goals' }, ...p.goals.map(goalItem))
      : el('p', { class: 'muted gr-none' }, 'No goals for this quarter yet.'),
    p.goals.length < data.most_goals
      ? el('button', { class: 'btn btn-sm', type: 'button', onclick: () => addGoal(p.name) }, 'Add a goal')
      : null);
}

function goalItem(g) {
  const mark = (result, label) => el('button', {
    class: `btn btn-sm ${g.result === result ? `gr-on gr-on-${GR_RESULT_TONE[result]}` : ''}`,
    type: 'button', 'aria-pressed': g.result === result ? 'true' : 'false',
    onclick: () => reviewGoal(g, g.result === result ? '' : result),
  }, label);
  return el('li', { class: 'gr-goal' },
    el('div', {},
      el('span', {}, g.goal),
      g.result ? el('span', { class: `pill pill-${GR_RESULT_TONE[g.result]} gr-result` }, g.result_label) : null),
    g.measure ? el('div', { class: 'muted gr-measure' }, `How we will know: ${g.measure}`) : null,
    g.note ? el('div', { class: 'muted gr-measure' }, `Review: ${g.note}`) : null,
    el('div', { class: 'gr-goal-actions' },
      mark('met', 'Met'), mark('partly', 'Partly'), mark('not_met', 'Not met'),
      el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => editGoal(g) }, 'Edit'),
      el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => removeGoal(g) }, 'Remove')));
}

function addGoal(name) {
  const data = grow.data;
  openModal(`A goal for ${name}, ${data.label}`, [
    { name: 'goal', label: 'The goal', full: true,
      placeholder: 'e.g. Design a pile cap on their own',
      hint: 'what they will be able to do by the end of the quarter' },
    { name: 'measure', label: 'How we will know', full: true,
      placeholder: 'e.g. One design checked with no mark-ups' },
  ], async () => {
    const values = modalValues();
    await api('/api/growth/goals', { method: 'POST',
      body: { person: name, quarter: data.quarter, goal: values.goal, measure: values.measure } });
    toast(`Goal set for ${name}.`, 'ok');
    loadGrowth(true);
  });
}

function editGoal(g) {
  openModal(`${g.person}'s goal`, [
    { name: 'goal', label: 'The goal', full: true },
    { name: 'measure', label: 'How we will know', full: true },
  ], async () => {
    await api(`/api/growth/goals/${g.id}`, { method: 'PUT', body: modalValues() });
    loadGrowth(true);
  }, { goal: g.goal, measure: g.measure });
}

async function reviewGoal(g, result) {
  try {
    await api(`/api/growth/goals/${g.id}/review`, { method: 'POST', body: { result, note: g.note || '' } });
    loadGrowth(true);
  } catch (error) {
    toast(error.message, 'bad');
  }
}

async function removeGoal(g) {
  if (!window.confirm(`Remove "${g.goal}" from ${g.person}'s goals?`)) return;
  try {
    await api(`/api/growth/goals/${g.id}`, { method: 'DELETE' });
    loadGrowth(true);
  } catch (error) {
    toast(error.message, 'bad');
  }
}

/* ------------------------------------------------------------------ wiring */

(function wireGrowth() {
  const refresh = $('#growth-refresh');
  if (refresh) refresh.addEventListener('click', () => loadGrowth(true));
  const select = $('#growth-quarter');
  if (select) {
    select.addEventListener('change', () => { grow.quarter = select.value; loadGrowth(true); });
  }
}());

window.growth = { load: loadGrowth };
