/* Selecao+ — a picture at the top of every tab.
 *
 * Overview and Reports open on four dials (how busy, how efficient, how close
 * to plan, how much of the plan earned). Projects opens on a map of tiles,
 * one per project, sized by budget and filled to how far along it is.
 * Tasks opens on a timeline of who is doing what until when. Timesheets opens
 * on a heat map of each person's months.
 *
 * Everything is drawn from what app.js already loaded; nothing new is asked
 * of the server. Each picture wraps an app.js render function, so the tables
 * below keep working exactly as before.
 */
(() => {
  const SVG = 'http://www.w3.org/2000/svg';
  const svg = (tag, attrs = {}, ...kids) => {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
    node.append(...kids.filter(Boolean));
    return node;
  };
  const toneVar = (t) => (t === 'ok' ? 'var(--ok)' : t === 'warn' ? 'var(--warn)' : t === 'bad' ? 'var(--bad)' : 'var(--accent)');
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const DAY = 86400000;
  const day = (iso) => new Date(`${iso}T00:00:00`).getTime();
  const todayMs = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };

  /* ------------------------------------------------------------ dials */

  /** A half-circle dial; the shaded band is where it should sit. */
  function dial({ label, value, text, min, max, band, toneName, sub }) {
    const W = 168; const R = 64; const cx = W / 2; const cy = 78; const sw = 13;
    const at = (v) => Math.PI * (1 - (clamp(v, min, max) - min) / (max - min));
    const pt = (a, r = R) => [cx + r * Math.cos(a), cy - r * Math.sin(a)];
    const path = (a0, a1, r = R) => {
      const [x0, y0] = pt(a0, r); const [x1, y1] = pt(a1, r);
      return `M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 0 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
    };
    const known = value !== null && value !== undefined && Number.isFinite(value);
    const arcLen = Math.PI * R;
    const fill = known ? (clamp(value, min, max) - min) / (max - min) : 0;
    const colour = toneVar(toneName);
    const meter = svg('path', {
      d: path(Math.PI, 0), fill: 'none', stroke: colour, 'stroke-width': sw, 'stroke-linecap': 'round',
      'stroke-dasharray': `${arcLen} ${arcLen}`, 'stroke-dashoffset': arcLen, class: 'dl-meter',
    });
    meter.style.setProperty('--to', String(arcLen * (1 - fill)));
    const [nx, ny] = pt(known ? at(value) : Math.PI, R);
    const picture = svg('svg', { viewBox: `0 0 ${W} 96`, class: 'dl-svg', role: 'img', 'aria-label': `${label}: ${text}` },
      svg('path', { d: path(Math.PI, 0), fill: 'none', stroke: 'var(--surface-2)', 'stroke-width': sw, 'stroke-linecap': 'round' }),
      band ? svg('path', { d: path(at(band[0]), at(band[1]), R + sw / 2 + 4), fill: 'none',
        stroke: 'var(--ok)', 'stroke-width': 3, opacity: 0.55, 'stroke-linecap': 'round' }) : null,
      meter,
      known ? svg('circle', { cx: nx, cy: ny, r: 5, fill: 'var(--surface)', stroke: colour, 'stroke-width': 3, class: 'dl-dot' }) : null);
    return el('div', { class: `dl dl-${toneName || 'plain'}` },
      picture,
      el('div', { class: 'dl-value', style: `color:${colour}` }, text),
      el('div', { class: 'dl-label' }, label),
      sub ? el('div', { class: 'dl-sub' }, sub) : null);
  }

  /** The four dials for the team, from a report's team figures. */
  function pulse(t, title) {
    if (!t) return null;
    const earnedShare = t.planned_to_date_mm ? t.earned_mm / t.planned_to_date_mm : null;
    return el('section', { class: 'panel dl-panel' },
      el('div', { class: 'dl-head' },
        el('h3', {}, title || 'How the team is doing'),
        el('p', { class: 'muted' }, 'The green band on each dial is where it should sit.')),
      el('div', { class: 'dl-row' },
        dial({ label: 'Busy', value: t.utilisation, text: fmt.pct(t.utilisation), min: 0, max: 1.3,
          band: [0.85, 1.05], toneName: tone.utilisation(t.utilisation),
          sub: `of ${num(t.capacity_to_date_mm)} MM of hours so far` }),
        dial({ label: 'Earning per hour spent', value: t.cpi, text: fmt.ratio(t.cpi), min: 0.5, max: 1.5,
          band: [1, 1.5], toneName: tone.cpi(t.cpi),
          sub: t.cpi >= 1 ? 'earning more than it costs' : 'costing more than it earns' }),
        dial({ label: 'On plan', value: t.plan_adherence, text: fmt.pct(t.plan_adherence), min: 0, max: 1.5,
          band: [0.85, 1.15], toneName: tone.target(t.plan_adherence),
          sub: `against ${num(t.planned_to_date_mm)} MM planned so far` }),
        dial({ label: 'Plan earned', value: earnedShare, text: earnedShare === null ? '—' : fmt.pct(earnedShare),
          min: 0, max: 1.3, band: [0.9, 1.3], toneName: earnedShare === null ? '' : tone.target(earnedShare),
          sub: `${num(t.earned_mm)} MM earned` })));
  }

  /* ------------------------------------------------------ project map */

  function projectMap() {
    const metrics = new Map((state.projectMetrics || []).map((m) => [m.number, m]));
    const items = (state.projects || [])
      .filter((p) => (p.budget_mm || 0) > 0)
      .map((p) => ({ p, m: metrics.get(p.number) || {} }))
      .sort((a, b) => (b.p.budget_mm || 0) - (a.p.budget_mm || 0));
    if (!items.length) return null;
    const biggest = items[0].p.budget_mm;
    const tiles = items.map(({ p, m }) => {
      const progress = clamp(m.progress || 0, 0, 1);
      const cpiTone = m.cpi === null || m.cpi === undefined ? '' : tone.cpi(m.cpi);
      const size = Math.sqrt(p.budget_mm / biggest);
      const closed = /final|closed|complete/i.test(p.status || '');
      const tile = el('button', {
        type: 'button', class: `pm-tile pm-${cpiTone || 'plain'} ${closed ? 'is-closed' : ''}`,
        style: `flex-grow:${(size * 10).toFixed(2)};flex-basis:${Math.round(110 + size * 170)}px;--fill:${(progress * 100).toFixed(1)}%;`
          + `min-height:${Math.round(86 + size * 64)}px`,
        title: `${p.number} — ${p.name}\n${fmt.pct(progress)} along · budget ${fmt.mm(p.budget_mm)} MM`
          + (m.cpi ? ` · ${fmt.ratio(m.cpi)} earned per MM spent` : ''),
        onclick: () => openProject(p.number),
      },
      el('span', { class: 'pm-water' }),
      el('span', { class: 'pm-top' },
        el('span', { class: 'pm-num' }, p.number),
        el('span', { class: `pill ${statusPill(p.status)}` }, p.status || '—')),
      el('span', { class: 'pm-name' }, p.name),
      el('span', { class: 'pm-foot' },
        el('b', {}, fmt.pct(progress)),
        el('span', {}, ` along · ${fmt.mm(p.budget_mm)} MM`),
        m.cpi ? el('span', { class: `pm-cpi v-${cpiTone}` }, fmt.ratio(m.cpi)) : null));
      return tile;
    });
    return el('section', { class: 'panel pm-panel' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Every project at a glance'),
          el('p', { class: 'muted' }, 'Bigger tiles carry bigger budgets. Each fills up as the project gets further along; '
            + 'the edge is green when it earns more than it costs, amber or red when it does not. Tap one to open it.'))),
      el('div', { class: 'pm-map' }, ...tiles));
  }

  /* --------------------------------------------------------- timeline */

  function taskTimeline(data) {
    const open = (data.tasks || []).filter((t) => !t.done && t.due);
    if (!open.length) return null;
    const today = todayMs();
    const from = Math.min(today - 7 * DAY, ...open.map((t) => day(t.start || t.due)));
    const startAt = Math.max(from, today - 21 * DAY);
    const lastDue = Math.max(...open.map((t) => day(t.due)));
    const endAt = Math.max(today + 21 * DAY, Math.min(lastDue + 3 * DAY, today + 70 * DAY));
    const span = endAt - startAt;
    const x = (ms) => clamp(((ms - startAt) / span) * 100, 0, 100);
    const people = data.engineers.filter((name) => open.some((t) => (t.assignees || []).includes(name)));
    const projectName = new Map((data.projects || []).map((p) => [p.number, p.name]));

    const ticks = [];
    const first = new Date(startAt);
    first.setDate(first.getDate() + ((8 - first.getDay()) % 7));   // next Monday
    // By the calendar, not by 7 x 24 h: across a clock change that would land
    // at 23:00 on the Sunday and label the tick a day early.
    for (const d = first; d.getTime() < endAt; d.setDate(d.getDate() + 7)) {
      ticks.push(el('span', { class: 'tl-tick', style: `left:${x(d.getTime())}%` },
        d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })));
    }

    const rows = people.map((name) => {
      const mine = open.filter((t) => (t.assignees || []).includes(name))
        .sort((a, b) => day(a.start || a.due) - day(b.start || b.due));
      const lanes = [];
      const bars = mine.map((t) => {
        const s = Math.max(day(t.start || t.due), startAt);
        const e = Math.max(day(t.due) + DAY, s + DAY);
        let lane = lanes.findIndex((end) => end <= s);
        if (lane < 0) { lane = lanes.length; lanes.push(e); } else lanes[lane] = e;
        const overdue = day(t.due) < today;
        const state_ = t.status === 'Blocked' ? 'blocked' : overdue ? 'late'
          : t.status === 'In progress' ? 'going' : 'waiting';
        const hours = t.shared ? t.hours_each : t.required_hours;
        return el('span', {
          class: `tl-bar tl-${state_}`,
          style: `left:${x(s)}%;width:${Math.max(1.2, x(e) - x(s))}%;top:${lane * 26 + 4}px;`
            + `--p:${(clamp(t.progress || 0, 0, 1) * 100).toFixed(0)}%`,
          title: `${t.name}\n${t.project_number} ${projectName.get(t.project_number) || ''}\n`
            + `${t.status} · due ${fmt.date(t.due)}${overdue ? ' (overdue)' : ''} · ${fmt.hours(hours)} h`,
        }, el('span', { class: 'tl-text' }, t.name));
      });
      return el('div', { class: 'tl-row' },
        el('div', { class: 'tl-who' },
          el('span', { class: 'swatch', style: `background:${engineerColor(name)}` }), name),
        el('div', { class: 'tl-lane', style: `height:${Math.max(1, lanes.length) * 26 + 8}px` }, ...bars));
    });

    return el('section', { class: 'panel tl-panel' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Who is doing what, until when'),
          el('p', { class: 'muted' }, 'Each bar runs from a task\'s start to its due date and fills as it gets done. '
            + 'Red is overdue or blocked. The blue line is today.')),
        el('div', { class: 'tl-key' },
          el('span', { class: 'tl-k tl-going' }, 'in progress'),
          el('span', { class: 'tl-k tl-waiting' }, 'not started'),
          el('span', { class: 'tl-k tl-late' }, 'overdue or blocked'))),
      el('div', { class: 'tl-scroll' },
        el('div', { class: 'tl' },
          el('div', { class: 'tl-row tl-axis' }, el('div', { class: 'tl-who' }),
            el('div', { class: 'tl-lane' }, ...ticks)),
          ...rows,
          el('div', { class: 'tl-today-wrap' }, el('span', { class: 'tl-today', style: `left:${x(today)}%` },
            el('span', {}, 'today'))))));
  }

  /* ----------------------------------------------------------- heat map */

  function heatColour(u) {
    if (u === null || u === undefined) return 'transparent';
    if (u < 0.7) return 'color-mix(in srgb, var(--series-1) 45%, var(--surface))';
    if (u < 0.85) return 'color-mix(in srgb, var(--series-1) 25%, var(--surface))';
    if (u <= 1.05) return 'color-mix(in srgb, var(--series-3) 55%, var(--surface))';
    if (u <= 1.2) return 'color-mix(in srgb, var(--series-4) 60%, var(--surface))';
    return 'color-mix(in srgb, var(--bad) 60%, var(--surface))';
  }

  function heatMap(overview) {
    const names = Object.keys((overview && overview.engineers) || {});
    if (!names.length) return null;
    const months = teamMonths(overview, 12);
    if (months.length < 2) return null;
    const cells = [el('div', { class: 'hm-corner' })];
    for (const m of months) cells.push(el('div', { class: 'hm-col' }, shortMonth(m)));
    for (const name of names) {
      cells.push(el('div', { class: 'hm-who' },
        el('span', { class: 'swatch', style: `background:${engineerColor(name)}` }), name));
      const byMonth = new Map(monthsOf(overview, name).map((m) => [m.month, m]));
      for (const month of months) {
        const m = byMonth.get(month);
        const u = m && m.capacity ? m.total / m.capacity : null;
        cells.push(el('div', {
          class: 'hm-cell', style: `background:${heatColour(u)}`,
          title: m ? `${name}, ${shortMonth(month)}: ${fmt.hours(m.total)} h of ${fmt.hours(m.capacity)} h`
            + (m.absence ? ` · ${fmt.hours(m.absence)} h away` : '') : `${name}, ${shortMonth(month)}: nothing booked`,
        }, u === null ? '' : `${Math.round(u * 100)}`));
      }
    }
    return el('section', { class: 'panel hm-panel' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Each person\'s months at a glance'),
          el('p', { class: 'muted' }, 'Every square is one person\'s month: the number is how much of their hours they booked.')),
        el('div', { class: 'hm-key' },
          el('span', { style: `background:${heatColour(0.6)}` }, 'room'),
          el('span', { style: `background:${heatColour(0.95)}` }, 'about right'),
          el('span', { style: `background:${heatColour(1.1)}` }, 'heavy'),
          el('span', { style: `background:${heatColour(1.3)}` }, 'over'))),
      el('div', { class: 'hm-scroll' },
        el('div', { class: 'hm', style: `grid-template-columns: minmax(96px, max-content) repeat(${months.length}, minmax(38px, 1fr))` },
          ...cells)));
  }

  /* -------------------------------------------------------------- hooks */

  function place(id, anchor, node, before = true) {
    const old = document.getElementById(id);
    if (old) old.remove();
    if (!node || !anchor) return;
    node.id = id;
    if (before) anchor.before(node); else anchor.after(node);
  }

  function wrapGlobal(name, after) {
    const original = window[name];
    if (typeof original !== 'function') return;
    window[name] = function wrapped(...args) {
      const result = original.apply(this, args);
      try { return after(result, ...args) ?? result; } catch (error) { console.error(error); return result; }
    };
  }

  wrapGlobal('renderOverview', () => {
    if (state.report) place('overview-pulse', $('#overview-cards'), pulse(state.report.team, 'How the team is doing'));
  });
  wrapGlobal('renderDashboard', (node, data) => {
    const dials = pulse(data.team, `How the team is doing — ${data.period.label}`);
    if (node && dials) {
      const title = node.querySelector('.report-title');
      if (title) title.after(dials); else node.prepend(dials);
    }
    return node;
  });
  wrapGlobal('renderProjects', () => place('projects-map', $('#projects-summary'), projectMap()));
  wrapGlobal('renderTaskLoad', (_, data) => {
    const host = $('#task-load');
    const line = taskTimeline(data);
    const old = document.getElementById('tasks-timeline');
    if (old) old.remove();
    if (host && line) {
      line.id = 'tasks-timeline';
      host.prepend(line);
      // on a narrow screen, open the timeline at today rather than at its start
      const scroller = line.querySelector('.tl-scroll');
      const mark = line.querySelector('.tl-today');
      if (scroller && mark && scroller.scrollWidth > scroller.clientWidth) {
        requestAnimationFrame(() => { scroller.scrollLeft = Math.max(0, mark.offsetLeft - scroller.clientWidth * 0.25); });
      }
    }
  });
  wrapGlobal('renderTimesheets', () => {
    if (state.overview) place('ts-heat', $('#ts-cards'), heatMap(state.overview));
  });

  window.tabs = { dial, pulse, projectMap, taskTimeline, heatMap };
})();
