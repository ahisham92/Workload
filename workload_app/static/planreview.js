/* Selecao+ — plan against what happened.
 *
 * Each week's plan is locked (by the daily run or the manager), and then laid
 * beside what the task list and the timesheets say happened: the share of
 * the planned hours kept, the tasks done, the work that came in on top, and
 * each slip with a one-tap reason.
 *
 * Used twice: on the manager's Planner (everybody, "Plan vs actual") and on
 * an engineer's own page ("My week", only theirs). Built on the page's own
 * helpers (el, api, toast, setChildren, fmt) and common.js's toastError and
 * dayLabel; the server does every sum.
 */
'use strict';

(function () {
  const review = { week: null, data: null, host: null, mine: null, unit: null };

  const STATE = {
    done: ['Done', 'ok'], open: ['Still to do', 'info'], late: ['Late', 'bad'],
    not_done: ['Not done', 'bad'], removed: ['Taken off the list', ''],
  };

  const pct = fmt.pct0;
  function hours(v) { return v === null || v === undefined ? '—' : `${fmt.hours(v)} h`; }
  function keptTone(v) { return v === null || v === undefined ? '' : v >= 0.8 ? 'ok' : v >= 0.6 ? 'warn' : 'bad'; }

  function stat(label, value, tone, note) {
    return el('div', { class: `stat ${tone ? `stat-${tone}` : ''}`, role: 'group' },
      el('span', { class: 'stat-value' }, value),
      el('span', { class: 'stat-label' }, label),
      note ? el('span', { class: 'stat-label pr-note' }, note) : null);
  }

  /* -- the trend: plan kept and tasks done, week by week ------------------ */

  function trend(points) {
    const shown = (points || []).filter((p) => p.kept !== null || p.tasks_done_share !== null);
    if (shown.length < 2) return null;
    const W = 320, H = 120, pad = 22, bw = Math.min(14, (W - pad) / shown.length / 2 - 3);
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H + 18}`);
    svg.setAttribute('class', 'pr-trend');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Plan kept and tasks done, week by week');
    const add = (tag, attrs, text) => {
      const node = document.createElementNS(ns, tag);
      for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
      if (text) node.textContent = text;
      svg.append(node);
      return node;
    };
    const line = (v) => H - (H - 8) * v;
    add('line', { x1: pad, x2: W, y1: line(0.8), y2: line(0.8), class: 'pr-goal' });
    add('text', { x: 0, y: line(0.8) + 3, class: 'pr-axis' }, '80%');
    const step = (W - pad) / shown.length;
    shown.forEach((p, i) => {
      const x = pad + i * step + step / 2 - bw;
      if (p.kept !== null) {
        const r = add('rect', { x, y: line(p.kept), width: bw, height: H - line(p.kept), rx: 2, class: 'pr-bar-kept' });
        r.append(Object.assign(document.createElementNS(ns, 'title'), { textContent: `Plan kept ${pct(p.kept)}` }));
      }
      if (p.tasks_done_share !== null) {
        const r = add('rect', { x: x + bw + 2, y: line(p.tasks_done_share), width: bw, height: H - line(p.tasks_done_share), rx: 2, class: 'pr-bar-tasks' });
        r.append(Object.assign(document.createElementNS(ns, 'title'), { textContent: `Tasks done ${pct(p.tasks_done_share)}` }));
      }
      add('text', { x: x + bw, y: H + 14, 'text-anchor': 'middle', class: 'pr-axis' },
        dayLabel(p.week, { day: 'numeric', month: 'short' }));
    });
    return el('figure', { class: 'pr-trend-wrap' }, svg,
      el('figcaption', { class: 'muted small' },
        el('span', { class: 'pr-key pr-key-kept' }), ' Planned hours kept  ',
        el('span', { class: 'pr-key pr-key-tasks' }), ' Planned tasks done  ',
        el('span', { class: 'pr-key pr-key-goal' }), ' Aim: 80% or more'));
  }

  /* -- one person's week --------------------------------------------------- */

  function jobBars(person) {
    const jobs = person.jobs.filter((j) => j.planned || j.booked);
    if (!jobs.length) return null;
    const peak = Math.max(1, ...jobs.map((j) => Math.max(j.planned, j.booked || 0)));
    return el('div', { class: 'pr-jobs' },
      el('div', { class: 'pr-jobs-key muted small' },
        el('span', { class: 'pr-key pr-key-plan' }), ' Planned  ',
        el('span', { class: 'pr-key pr-key-booked' }), ' Booked in the timesheet'),
      ...jobs.map((j) => el('div', { class: `pr-job ${j.short ? 'is-short' : ''} ${j.unplanned ? 'is-unplanned' : ''}` },
        el('div', { class: 'pr-job-name' },
          el('span', { class: 'code' }, j.job || '—'), ' ', el('span', {}, j.name !== j.job ? j.name : ''),
          j.unplanned ? el('span', { class: 'pill pill-warn' }, 'Not in the plan') : null,
          j.short ? el('span', { class: 'pill pill-bad' }, 'Short') : null),
        el('div', { class: 'pr-job-bars' },
          el('span', { class: 'pr-plan', style: `width:${(j.planned / peak) * 100}%` }),
          j.booked !== null ? el('span', { class: 'pr-booked', style: `width:${((j.booked || 0) / peak) * 100}%` }) : null),
        el('div', { class: 'pr-job-figures small' },
          `${fmt.hours(j.planned)} h planned · `,
          j.booked === null ? el('span', { class: 'muted' }, 'timesheet not in') : `${fmt.hours(j.booked)} h booked`))));
  }

  function reasonPicker(item, choices, send) {
    if (!item.id || !send) {
      const label = (choices.find((c) => c.key === item.reason) || {}).label;
      return label ? el('span', { class: 'pill pill-info' }, label) : null;
    }
    const select = el('select', { 'aria-label': 'Why', class: 'pr-reason' },
      el('option', { value: '' }, 'Why? Pick one'),
      ...choices.map((c) => el('option', { value: c.key }, c.label)));
    select.value = item.reason || '';
    select.addEventListener('change', () => send(item, select.value));
    return select;
  }

  function personCard(person, { choices, send, open = false }) {
    const kept = person.kept;
    const slips = person.slips || [];
    const head = el('summary', { class: 'pr-person-head' },
      el('span', { class: 'pr-person-name' }, person.name,
        person.team_name ? el('span', { class: 'muted small' }, ` · ${person.team_name}`) : null),
      el('span', { class: 'pr-chips' },
        person.timesheet_in
          ? el('span', { class: `pill pill-${keptTone(kept) || 'info'}` }, `Plan kept ${pct(kept)}`)
          : el('span', { class: 'pill' }, 'Timesheet not in yet'),
        person.tasks_planned
          ? el('span', { class: `pill pill-${person.tasks_done === person.tasks_planned ? 'ok' : 'info'}` },
            `Tasks ${person.tasks_done} of ${person.tasks_planned} done`) : null,
        person.on_top_hours ? el('span', { class: 'pill pill-warn' }, `${fmt.hours(person.on_top_hours)} h came in on top`) : null,
        slips.length ? el('span', { class: 'pill pill-bad' }, `${slips.length} slip${slips.length === 1 ? '' : 's'}`) : null));

    const tasks = person.tasks.length ? el('div', { class: 'pr-block' },
      el('h4', {}, 'Planned tasks'),
      el('ul', { class: 'pr-list' }, person.tasks.map((t) => {
        const [label, toneName] = STATE[t.state] || [t.state, ''];
        return el('li', {},
          el('span', { class: `pill ${toneName ? `pill-${toneName}` : ''}` }, label),
          el('span', { class: 'pr-what' }, t.title,
            el('span', { class: 'muted small' }, `${t.job ? ` · ${t.job}` : ''} · ${fmt.hours(t.hours)} h`
              + `${t.due ? ` · due ${dayLabel(t.due)}` : ''}`)));
      }))) : null;

    const onTop = person.on_top.length ? el('div', { class: 'pr-block' },
      el('h4', {}, 'Came in on top of the plan'),
      el('ul', { class: 'pr-list' }, person.on_top.map((r) => el('li', {},
        el('span', { class: `pill ${r.done ? 'pill-ok' : 'pill-warn'}` }, r.done ? 'Done' : 'Open'),
        el('span', { class: 'pr-what' }, r.title,
          el('span', { class: 'muted small' }, ` · ${fmt.hours(r.hours)} h · ${dayLabel(r.start)}`)))))) : null;

    const slipList = slips.length ? el('div', { class: 'pr-block pr-slips' },
      el('h4', {}, 'Did not go to plan'),
      el('ul', { class: 'pr-list' }, slips.map((s) => el('li', {},
        el('span', { class: 'pr-what' }, dayFirstText(s.what)),
        reasonPicker(s, choices, send))))) : null;

    return el('details', { class: 'panel pr-person', open: open || null }, head,
      el('div', { class: 'pr-person-body' },
        el('p', { class: 'muted small' },
          `Planned ${hours(person.planned_hours)}`
          + (person.other_planned ? ` (${fmt.hours(person.other_planned)} h of it meetings and team support)` : '')
          + (person.booked_hours !== null ? `. Booked ${hours(person.booked_hours)}.` : '.')),
        jobBars(person), tasks, onTop, slipList));
  }

  /* -- the manager's view ---------------------------------------------------- */

  async function sendReason(item, reason, path) {
    try {
      await api(path, { method: 'POST', body: { id: item.id, reason, unit: review.unit || undefined } });
      item.reason = reason;
      toast(reason ? 'Reason kept.' : 'Reason cleared.', 'ok');
    } catch (error) {
      toastError(error);
      await (review.mine ? loadMine() : load());
    }
  }

  async function load() {
    const query = review.week ? `?week=${review.week}` : '';
    try {
      review.data = await api(`/api/plan-review${query}`);
    } catch (error) {
      toastError(error);
      return;
    }
    render();
  }

  async function lockAgain() {
    try {
      await api('/api/plan-review/lock', { method: 'POST', body: { week: review.data.week } });
      toast('A new copy of this week’s plan is kept. Reasons already given stay.', 'ok');
      await load();
    } catch (error) {
      toastError(error);
    }
  }

  function weekNav(data, go) {
    return el('div', { class: 'pr-nav' },
      el('button', { class: 'btn btn-sm', type: 'button', onclick: () => go(data.previous) }, '‹ Week before'),
      el('b', { class: 'pr-week' }, `${dayLabel(data.week)} to ${dayLabel(data.week_end)}`),
      el('button', { class: 'btn btn-sm', type: 'button', onclick: () => go(data.next) }, 'Week after ›'),
      data.state !== 'current' ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button', onclick: () => go(null) }, 'This week') : null);
  }

  function lockNote(data) {
    if (data.locked) {
      return el('span', { class: 'pill pill-ok' }, `Week’s plan copied${data.locked_at ? ` on ${dayLabel(data.locked_at)}` : ''}`);
    }
    return el('span', { class: 'pill' }, data.state === 'past' ? 'No plan was kept for this week' : 'No copy kept yet: showing the plan as it stands');
  }

  function render() {
    const data = review.data;
    const host = review.host;
    if (!data || !host) return;
    const s = data.summary;
    const choices = data.reason_choices;
    const send = (item, reason) => sendReason(item, reason, '/api/plan-review/reason');
    const order = data.people.slice().sort((a, b) => (b.slips.length - a.slips.length)
      || ((a.kept ?? 2) - (b.kept ?? 2)) || a.name.localeCompare(b.name));
    const reasons = data.reasons.filter((r) => r.count);
    setChildren(host,
      el('section', { class: 'panel pr-top' },
        el('div', { class: 'panel-head' },
          el('div', {},
            el('h3', {}, 'Plan against what happened'),
            el('p', { class: 'muted' },
              'On the first working day the app keeps a copy of the week’s plan. The daily plan still changes every day; the copy is what the week is checked against. '
              + 'At the end of the week it is laid beside the tasks done and the hours in the timesheets. '
              + 'Anything that did not go to plan gets a reason with one tap.')),
          el('div', { class: 'row-actions' }, lockNote(data),
            data.can_lock ? el('button', { class: 'btn btn-sm', type: 'button', onclick: lockAgain,
              title: 'After big changes this week, check the week against the new plan instead' },
            data.locked ? 'Copy the plan again' : 'Copy the plan now') : null)),
        weekNav(data, (week) => { review.week = week; load(); }),
        el('div', { class: 'stat-strip' },
          stat('Planned hours kept', pct(s.kept), keptTone(s.kept),
            s.timesheets_in < s.people ? `${s.timesheets_in} of ${s.people} timesheets in` : null),
          stat('Planned tasks done', s.tasks_planned ? `${s.tasks_done} of ${s.tasks_planned}` : '—',
            keptTone(s.tasks_done_share)),
          stat('Came in on top', hours(s.on_top_hours), s.on_top_hours > 8 ? 'warn' : '',
            s.on_top_count ? `${s.on_top_count} request${s.on_top_count === 1 ? '' : 's'}` : null),
          stat('Booked to jobs not in the plan', hours(s.unplanned_hours), s.unplanned_hours > 8 ? 'warn' : ''),
          stat('Slips', s.slips ? `${s.slips_explained} of ${s.slips} explained` : 'none',
            s.slips && s.slips_explained < s.slips ? 'warn' : 'ok')),
        data.what_next.length ? el('div', { class: 'pr-next' },
          el('h4', {}, 'What to do about it'),
          el('ol', {}, data.what_next.map((line) => el('li', {}, line)))) : null,
        el('div', { class: 'pr-side' },
          trend(data.trend),
          reasons.length ? el('div', { class: 'pr-reasons' },
            el('h4', {}, 'Why things slipped'),
            el('ul', { class: 'pr-list' }, reasons.sort((a, b) => b.count - a.count).map((r) => el('li', {},
              el('b', {}, String(r.count)), ` ${r.label}`)))) : null)),
      ...(order.length
        ? order.map((p, i) => personCard(p, { choices, send, open: i === 0 && p.slips.length > 0 }))
        : [el('div', { class: 'empty' }, 'Nobody has planned work this week yet.')]));
  }

  /* -- an engineer's own week ------------------------------------------------ */

  async function loadMine() {
    const query = new URLSearchParams();
    if (review.unit) query.set('unit', review.unit);
    if (review.week) query.set('week', review.week);
    const text = query.toString();
    try {
      review.data = await api(`/api/me/week${text ? `?${text}` : ''}`, { quiet: true });
    } catch (error) {
      review.host.hidden = true;
      return;
    }
    review.host.hidden = false;
    renderMine();
  }

  function renderMine() {
    const data = review.data;
    const me = data.me;
    const send = (item, reason) => sendReason(item, reason, '/api/me/week/reason');
    setChildren(review.host,
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'My week: planned and done'),
          el('p', { class: 'muted' },
            'What was planned for you this week, what you finished, and what you booked in your timesheet. '
            + 'If something did not go to plan, say why with one tap: it helps plan next week better.')),
        lockNote(data)),
      weekNav(data, (week) => { review.week = week; loadMine(); }),
      me ? personCard(me, { choices: data.reason_choices, send: data.locked ? send : null, open: true })
        : el('div', { class: 'empty' }, 'Nothing was planned for you this week.'),
      trend(data.trend));
  }

  window.planReview = {
    open(host) { review.host = host; review.mine = false; return load(); },
    mine(host, unit) { review.host = host; review.mine = true; review.unit = unit || review.unit; return loadMine(); },
  };
})();
