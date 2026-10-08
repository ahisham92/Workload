/* Selecao+ — people at a glance, and the team's load in 3D.
 *
 * Three pieces, all drawn from figures the server already works out:
 *
 *   - a card for each person (Team tab): their score, the measures behind it,
 *     how loaded they are and what they are on next;
 *   - a profile that opens from any card or from the Overview formation;
 *   - the load landscape (Check-ins tab): everybody's load, week by week, as a
 *     3D block you can turn and tap.
 *
 * Nothing here adds a measure. The score is the scorecard's, the load is
 * Check-ins', the coming work is the Planner's. The 3D is plain canvas, no
 * library, so it stays light on a phone.
 *
 * Built on app.js's helpers (el, api, state, fmt, tone, engineerColor,
 * initials, setChildren) and checkins.js's `checkin`.
 */
'use strict';

(function () {
  const show = {
    checkins: null,   // /api/checkins, shared with the Check-ins tab
    outlook: null,    // /api/planner, the next five working days
    drawings: null,   // /api/drawings
    loading: null,
  };

  const SIGNAL_CLASS = { rest: 'bad', busy: 'warn', fresh: 'ok', steady: 'info' };
  const NS = 'http://www.w3.org/2000/svg';
  const reduced = () => window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function svg(tag, attrs = {}, ...children) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v !== null && v !== undefined) node.setAttribute(k, v);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const pct = (v) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
  const hrs = (v) => `${fmt.hours(v || 0)} h`;

  /* ------------------------------------------------------------- data */

  async function gather(force = false) {
    if (show.loading && !force) return show.loading;
    show.loading = (async () => {
      const shared = typeof checkin !== 'undefined' ? checkin.data : null;
      const [ci, outlook, drawings, me] = await Promise.all([
        shared && !force ? shared : api('/api/checkins', { quiet: true }).catch(() => null),
        api('/api/planner', { method: 'POST', quiet: true, body: { days: 5 } }).catch(() => null),
        api('/api/drawings', { quiet: true }).catch(() => null),
        api('/api/team/me', { quiet: true }).catch(() => null),
      ]);
      if (me) state.myself = me.me || '';
      show.checkins = ci;
      show.outlook = outlook;
      show.drawings = drawings;
    })();
    try { await show.loading; } finally { show.loading = null; }
    return null;
  }

  /** The scorecard's factors as 0..100, the way the scorecard scores them. */
  function factorScores(report) {
    const factors = ((report && report.scorecard) || {}).factors || [];
    return factors.map((f) => {
      const values = f.values || {};
      const nums = Object.values(values).filter((v) => typeof v === 'number');
      const best = nums.length ? Math.max(...nums) : 0;
      const least = nums.length ? Math.min(...nums) : 0;
      const scores = {};
      for (const [name, v] of Object.entries(values)) {
        if (typeof v !== 'number') { scores[name] = null; continue; }
        if (f.direction === 'lower') scores[name] = v > 0 ? clamp((least / v) * 100, 0, 100) : 100;
        else if (f.target) scores[name] = clamp(100 - (Math.abs(v - f.target) / f.target) * 100, 0, 100);
        else scores[name] = best > 0 ? clamp((v / best) * 100, 0, 100) : 0;
      }
      return { label: shortFactor(f.factor || f.key), full: f.factor, key: f.key, scores, values };
    });
  }

  function shortFactor(text) {
    const t = String(text || '');
    if (/cpi|efficien/i.test(t)) return 'Efficiency';
    if (/utili/i.test(t)) return 'Hours used';
    if (/adherence/i.test(t)) return 'Plan kept';
    if (/earned/i.test(t)) return 'Earned';
    if (/actual/i.test(t)) return 'Booked';
    if (/projects/i.test(t)) return 'Projects';
    return t.split(/[ (]/)[0];
  }

  /** Everything one card or profile shows about a person. */
  function personOf(name) {
    const report = state.report || {};
    const e = (report.per_engineer || {})[name] || {};
    const roster = (state.people || []).find((p) => p.name === name) || {};
    const sc = report.scorecard || {};
    const ranking = sc.ranking || [];
    const ranked = ranking.find((r) => r.engineer === name) || {};
    // Ranked only against the same grade: a junior is never set against a manager.
    const totals = sc.totals || {};
    const sameGrade = (state.people || [])
      .filter((x) => (x.grade || '') === (roster.grade || '') && typeof totals[x.name] === 'number')
      .map((x) => x.name)
      .sort((a, b) => totals[b] - totals[a]);
    const gradeRank = sameGrade.indexOf(name) + 1;
    const ci = ((show.checkins || {}).people || []).find((p) => p.name === name) || null;
    const ahead = ((show.outlook || {}).people || []).find((p) => p.name === name) || null;
    const drawn = ((show.drawings || {}).people || []).find((p) => p.name === name) || null;
    return {
      name,
      color: engineerColor(name),
      initials: initials(name),
      grade: roster.grade_label || (ci && ci.grade_label) || '',
      team: roster.team_name || (ci && ci.team_name) || '',
      score: (sc.totals || {})[name],
      rank: gradeRank || ranked.rank || null,
      of: gradeRank ? sameGrade.length : ranking.length,
      among: gradeRank ? (roster.grade_label || 'grade') : 'team',
      strongest: ranked.strongest || '',
      weakest: ranked.weakest || '',
      e,
      ci,
      ahead,
      drawn: show.drawings && show.drawings.known ? drawn : null,
    };
  }

  /* ---------------------------------------------------------- the card */

  function statRow(label, value, fill, toneName, title) {
    return el('div', { class: 'pc-stat', title: title || null },
      el('span', { class: 'pc-stat-label' }, label),
      el('span', { class: 'pc-stat-bar' },
        el('span', { class: toneName ? `t-${toneName}` : '', style: `width:${Math.round(clamp(fill, 0, 1) * 100)}%` })),
      el('span', { class: `pc-stat-value ${toneName ? `v-${toneName}` : ''}` }, value));
  }

  function ring(value, toneName, size = 64, label = null) {
    const r = size / 2 - 4;
    const c = 2 * Math.PI * r;
    const shown = clamp(value || 0, 0, 1);
    return svg('svg', { class: `pc-ring ring-${toneName || 'none'}`, viewBox: `0 0 ${size} ${size}`,
      width: size, height: size, 'aria-hidden': 'true' },
    svg('circle', { cx: size / 2, cy: size / 2, r, class: 'pc-ring-track' }),
    svg('circle', { cx: size / 2, cy: size / 2, r, class: 'pc-ring-fill',
      'stroke-dasharray': `${(shown * c).toFixed(1)} ${c.toFixed(1)}`,
      transform: `rotate(-90 ${size / 2} ${size / 2})` }),
    label ? svg('text', { x: size / 2, y: size / 2 + 4, 'text-anchor': 'middle', class: 'pc-ring-text' }, label) : null);
  }

  function card(name, maxima) {
    const p = personOf(name);
    const e = p.e;
    const signal = p.ci && p.ci.signal;
    const work = p.ahead ? p.ahead.items.filter((i) => i.hours_after > 0.4).slice(0, 3) : [];
    const loadAhead = p.ahead ? p.ahead.after.load : null;
    const scoreTone = tone.score(p.score);
    return el('button', {
      class: 'pc', type: 'button', style: `--pc:${p.color}`,
      'aria-label': `${name}: open their profile`,
      onclick: () => profile(name),
    },
    el('div', { class: 'pc-top' },
      el('div', { class: `pc-score v-${scoreTone || 'none'}` },
        el('b', {}, p.score === undefined || p.score === null ? '—' : Math.round(p.score)),
        el('span', {}, 'score')),
      el('div', { class: 'pc-face' },
        ring(e.utilisation, tone.utilisation(e.utilisation), 76),
        el('span', { class: 'pc-avatar' }, p.initials)),
      el('div', { class: 'pc-rank' },
        p.rank ? el('b', {}, `${p.rank}`) : null,
        p.rank ? el('span', { title: `Ranked among ${p.among} only` }, `of ${p.of}`) : null)),
    el('div', { class: 'pc-name' }, name,
      name === state.myself ? el('span', { class: 'pill pill-ok pc-you' }, 'You') : null),
    el('div', { class: 'pc-sub' }, [p.grade, p.team].filter(Boolean).join(' · ') || 'No grade or team yet'),
    signal ? el('span', { class: `pc-signal pill pill-${SIGNAL_CLASS[signal.key] || 'info'}` }, signal.label) : null,
    el('div', { class: 'pc-stats' },
      statRow('Efficiency', fmt.ratio(e.cpi), (e.cpi || 0) / 1.4, tone.cpi(e.cpi),
        'Earned per man-month spent (CPI)'),
      statRow('Hours used', pct(e.utilisation), (e.utilisation || 0) / 1.2, tone.utilisation(e.utilisation),
        'Hours booked against the hours they had'),
      statRow('Plan kept', pct(e.plan_adherence), (e.plan_adherence || 0) / 1.2, tone.target(e.plan_adherence),
        'Booked against what the plan said, to date'),
      statRow('Earned', `${num(e.earned_mm, 1)} MM`, maxima.earned ? (e.earned_mm || 0) / maxima.earned : 0, '',
        'Man-months of value delivered'),
      statRow('Projects', fmt.int(e.projects_worked), maxima.projects ? (e.projects_worked || 0) / maxima.projects : 0, '',
        'Projects they booked time on'),
      p.drawn
        ? statRow('Drawings', fmt.int(Math.round(p.drawn.done)), maxima.drawings ? p.drawn.done / maxima.drawings : 0, '',
          `${fmt.int(Math.round(p.drawn.done))} done, ${fmt.int(Math.round(p.drawn.left))} still to do`)
        : statRow('Free this week', p.ci ? hrs(p.ci.free_week) : '—',
          p.ci ? clamp(p.ci.free_week / 20, 0, 1) : 0, p.ci && p.ci.free_week > 0 ? 'ok' : '',
          'Hours left this week once their work is laid out')),
    el('div', { class: 'pc-next' },
      el('div', { class: 'pc-next-head' },
        el('span', {}, 'Next 5 days'),
        loadAhead !== null && loadAhead !== undefined
          ? el('b', { class: `v-${loadTone5(loadAhead)}` }, `${pct(loadAhead)} loaded`) : null),
      work.length
        ? work.map((i) => el('div', { class: 'pc-job' },
          el('span', { class: 'pc-job-name' }, i.project ? `${i.project} ` : '', i.project && i.name !== i.project ? el('span', { class: 'muted' }, i.name) : (i.project ? '' : i.name)),
          el('span', { class: 'pc-job-hours' }, hrs(i.hours_after))))
        : el('div', { class: 'muted small' }, 'Nothing lined up.')));
  }

  function loadTone5(load) {
    if (load === null || load === undefined) return '';
    return load > 1.0001 ? 'bad' : load < 0.8 ? 'warn' : 'ok';
  }

  function maximaOf(names) {
    const report = state.report || {};
    const per = report.per_engineer || {};
    const drawn = ((show.drawings || {}).people || []);
    return {
      earned: Math.max(0, ...names.map((n) => (per[n] || {}).earned_mm || 0)),
      projects: Math.max(0, ...names.map((n) => (per[n] || {}).projects_worked || 0)),
      drawings: Math.max(0, ...drawn.map((d) => d.done || 0)),
    };
  }

  /** The cards at the head of the Team tab. */
  async function teamCards() {
    const host = $('#team-cards');
    if (!host) return;
    const names = (state.report && state.report.engineers) || [];
    if (!names.length) { host.hidden = true; return; }
    host.hidden = false;
    if (!host.childElementCount) {
      setChildren(host, el('div', { class: 'empty' }, 'Laying out the team…'));
    }
    await gather();
    const maxima = maximaOf(names);
    const order = names.slice().sort((a, b) => {
      const ra = personOf(a).rank || 99;
      const rb = personOf(b).rank || 99;
      return ra - rb || a.localeCompare(b);
    });
    const period = state.report && state.report.period ? state.report.period.label : '';
    setChildren(host,
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'The team at a glance'),
          el('p', { class: 'muted' },
            `Each person's score and the measures behind it for ${period || 'the period'}, `
            + 'how loaded they are and what they are on next. Ordered by score. Open a card for '
            + 'the whole picture.')),
        el('span', { class: 'legend' },
          el('span', { class: 'legend-item' }, el('span', { class: 'swatch ring-swatch ring-ok' }), 'ring: hours used'))),
      el('div', { class: 'pc-grid' }, order.map((n) => card(n, maxima))));
  }

  /* ------------------------------------------------------ the profile */

  function radar(person, factors, size = 260) {
    if (!factors.length) return null;
    const cx = size / 2;
    const cy = size / 2;
    const r = size / 2 - 46;
    const n = factors.length;
    const at = (i, v) => {
      const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
      return [cx + Math.cos(a) * r * v, cy + Math.sin(a) * r * v];
    };
    const names = (state.report && state.report.engineers) || [];
    const avg = factors.map((f) => {
      const vals = names.map((nm) => f.scores[nm]).filter((v) => typeof v === 'number');
      return vals.length ? vals.reduce((s, v) => s + v, 0) / vals.length / 100 : 0;
    });
    const mine = factors.map((f) => (f.scores[person.name] || 0) / 100);
    const poly = (vals) => vals.map((v, i) => at(i, Math.max(0.04, v)).map((x) => x.toFixed(1)).join(',')).join(' ');
    return svg('svg', { class: 'radar', viewBox: `0 0 ${size} ${size}`, role: 'img',
      'aria-label': `${person.name}'s measures against the best on the team` },
    [0.25, 0.5, 0.75, 1].map((k) => svg('polygon', { class: 'radar-grid', points: poly(factors.map(() => k)) })),
    factors.map((_, i) => {
      const [x, y] = at(i, 1);
      return svg('line', { class: 'radar-axis', x1: cx, y1: cy, x2: x, y2: y });
    }),
    svg('polygon', { class: 'radar-team', points: poly(avg) }),
    svg('polygon', { class: 'radar-me', points: poly(mine), style: `--pc:${person.color}` }),
    mine.map((v, i) => {
      const [x, y] = at(i, Math.max(0.04, v));
      return svg('circle', { class: 'radar-dot', cx: x, cy: y, r: 3.2, style: `--pc:${person.color}` });
    }),
    factors.map((f, i) => {
      const [x, y] = at(i, 1.2);
      const anchor = Math.abs(x - cx) < 6 ? 'middle' : x > cx ? 'start' : 'end';
      return svg('text', { class: 'radar-label', x, y: y + 3, 'text-anchor': anchor },
        svg('title', {}, f.full), `${f.label} ${Math.round(f.scores[person.name] || 0)}`);
    }));
  }

  function weekBars(person) {
    const weeks = (person.ci && person.ci.weeks) || [];
    if (!weeks.length) return null;
    const W = 320; const H = 110; const pad = 18;
    const max = Math.max(1.3, ...weeks.map((w) => w.load || 0));
    const bw = (W - pad) / weeks.length;
    const y = (v) => H - pad - (v / max) * (H - pad - 6);
    return svg('svg', { class: 'pf-weeks', viewBox: `0 0 ${W} ${H}`, role: 'img',
      'aria-label': 'Load over the last weeks' },
    weeks.map((w, i) => {
      const v = w.load || 0;
      const t = v > 1.0001 ? 'bad' : v < 0.8 ? 'warn' : 'ok';
      return svg('rect', { class: `pf-bar t-${t}`, x: pad + i * bw + 3, y: y(v), width: bw - 6,
        height: Math.max(1, H - pad - y(v)), rx: 3 },
      svg('title', {}, `Week of ${w.week}: ${pct(v)} of their hours (${fmt.hours(w.hours)} h)`));
    }),
    svg('line', { class: 'pf-line', x1: pad, x2: W, y1: y(1), y2: y(1) }),
    svg('text', { class: 'pf-axis', x: 0, y: y(1) + 3 }, '100%'),
    svg('text', { class: 'pf-axis', x: pad, y: H - 4 }, weeks[0].week.slice(5)),
    svg('text', { class: 'pf-axis', x: W, y: H - 4, 'text-anchor': 'end' }, weeks[weeks.length - 1].week.slice(5)));
  }

  function dayStrip(person) {
    const days = (person.ci && person.ci.days) || [];
    if (!days.length) return null;
    return el('div', { class: 'pf-days' }, days.map((d) => {
      const t = d.away ? 'away' : d.free > 0.05 ? 'free' : d.over > 0.05 ? 'over' : 'full';
      const label = d.away ? 'away' : d.free > 0.05 ? `+${fmt.hours(d.free)}` : d.over > 0.05 ? `−${fmt.hours(d.over)}` : 'full';
      return el('div', { class: `pf-day pf-${t}`, title: `${d.date}: ${label}` },
        el('span', {}, new Date(`${d.date}T00:00:00`).toLocaleDateString(undefined, { weekday: 'narrow' })),
        el('b', {}, label));
    }));
  }

  let sheet = null;

  function closeProfile() {
    if (!sheet) return;
    const node = sheet;
    sheet = null;
    node.classList.remove('is-open');
    setTimeout(() => node.remove(), reduced() ? 0 : 220);
    document.removeEventListener('keydown', onKey);
  }

  function onKey(event) {
    if (!sheet) return;
    if (event.key === 'Escape') closeProfile();
    if (event.key === 'ArrowRight') step(1);
    if (event.key === 'ArrowLeft') step(-1);
  }

  function step(by) {
    if (!sheet) return;
    const names = (state.report && state.report.engineers) || [];
    const at = names.indexOf(sheet.dataset.name);
    if (at < 0 || names.length < 2) return;
    profile(names[(at + by + names.length) % names.length]);
  }

  /** One person, everything about them, over the page. */
  async function profile(name) {
    if (!show.checkins && !show.outlook) await gather();
    const p = personOf(name);
    const e = p.e;
    const factors = factorScores(state.report);
    const signal = p.ci && p.ci.signal;
    const work = p.ahead ? p.ahead.items.filter((i) => i.hours_after > 0.2) : [];
    const points = (p.ci && p.ci.checkpoints) || [];

    const body = el('div', { class: 'pf' },
      el('div', { class: 'pf-hero', style: `--pc:${p.color}` },
        el('div', { class: 'pf-face' },
          ring(e.utilisation, tone.utilisation(e.utilisation), 96),
          el('span', { class: 'pc-avatar pc-avatar-lg' }, p.initials)),
        el('div', { class: 'pf-who' },
          el('h3', {}, name),
          el('div', { class: 'muted' }, [p.grade, p.team].filter(Boolean).join(' · ')),
          signal ? el('span', { class: `pill pill-${SIGNAL_CLASS[signal.key] || 'info'}` }, signal.label) : null),
        el('div', { class: `pf-score v-${tone.score(p.score) || 'none'}` },
          el('b', {}, p.score === undefined || p.score === null ? '—' : num(p.score, 1)),
          el('span', {}, p.rank ? `score · ${p.rank} of ${p.of} (${p.among})` : 'score'))),
      el('div', { class: 'pf-tiles' },
        tile('Efficiency', fmt.ratio(e.cpi), tone.cpi(e.cpi)),
        tile('Hours used', pct(e.utilisation), tone.utilisation(e.utilisation)),
        tile('Plan kept', pct(e.plan_adherence), tone.target(e.plan_adherence)),
        tile('Booked', `${num(e.actual_mm, 1)} MM`, ''),
        tile('Earned', `${num(e.earned_mm, 1)} MM`, tone.amount(e.profit_mm)),
        p.drawn ? tile('Drawings done', fmt.int(Math.round(p.drawn.done)), '')
          : tile('Free this week', p.ci ? hrs(p.ci.free_week) : '—', p.ci && p.ci.free_week ? 'ok' : '')),
      el('div', { class: 'pf-split' },
        el('section', { class: 'pf-block' },
          el('h4', {}, 'Strengths'),
          el('p', { class: 'muted small' }, 'Each measure against the best on the team (100). The grey shape is the team\'s average.'),
          radar(p, factors),
          p.strongest ? el('p', { class: 'small' }, el('b', {}, 'Strongest: '), p.strongest,
            el('br'), el('b', {}, 'To work on: '), p.weakest) : null),
        el('section', { class: 'pf-block' },
          el('h4', {}, 'Lately'),
          el('p', { class: 'muted small' }, 'Hours booked each week against the hours they had. Over the line wears people down.'),
          weekBars(p) || el('p', { class: 'muted' }, 'No recent weeks.'),
          signal && signal.reasons && signal.reasons.length
            ? el('ul', { class: 'pf-reasons' }, signal.reasons.map((r) => el('li', {}, r))) : null,
          el('h4', {}, 'The next two weeks'),
          dayStrip(p) || el('p', { class: 'muted' }, 'No days laid out.'))),
      el('section', { class: 'pf-block' },
        el('h4', {}, 'Lined up for the next 5 days'),
        work.length
          ? el('div', { class: 'pf-work' }, work.map((i) => {
            const share = p.ahead.capacity ? i.hours_after / p.ahead.capacity : 0;
            return el('div', { class: 'pf-job' },
              el('span', { class: 'pf-job-name' }, i.project ? el('span', { class: 'code' }, i.project) : null,
                ' ', i.name !== i.project ? i.name : ''),
              el('span', { class: 'pf-job-bar' }, el('span', { style: `width:${Math.round(clamp(share, 0, 1) * 100)}%` })),
              el('span', { class: 'pf-job-hours' }, hrs(i.hours_after)));
          }))
          : el('p', { class: 'muted' }, 'Nothing lined up.')),
      points.length
        ? el('section', { class: 'pf-block' },
          el('h4', {}, 'To raise with them'),
          el('ul', { class: 'pf-points' }, points.map((c) => el('li', { class: `pf-point pf-${c.level}` }, c.text))))
        : null,
      el('div', { class: 'pf-actions' },
        el('button', { class: 'btn', type: 'button', onclick: () => step(-1), 'aria-label': 'Previous person' }, '‹'),
        el('button', { class: 'btn', type: 'button', onclick: () => {
          closeProfile();
          state.reportView = 'member';
          state.reportMember = name;
          switchView('reports');
          renderReports();
        } }, 'Full report'),
        el('button', { class: 'btn btn-primary', type: 'button', onclick: () => {
          closeProfile();
          if (window.planner && window.planner.board) window.planner.board();
          else switchView('planner');
        } }, 'Plan their work'),
        el('button', { class: 'btn', type: 'button', onclick: () => step(1), 'aria-label': 'Next person' }, '›')));

    const fresh = !sheet;
    if (fresh) {
      sheet = el('div', { class: 'sheet-backdrop', onclick: (ev) => { if (ev.target === sheet) closeProfile(); } },
        el('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${name}'s profile` },
          el('div', { class: 'sheet-grip' }),
          el('button', { class: 'btn btn-ghost sheet-close', type: 'button', 'aria-label': 'Close', onclick: closeProfile }, '✕'),
          el('div', { class: 'sheet-body' })));
      document.body.append(sheet);
      document.addEventListener('keydown', onKey);
      swipe(sheet.querySelector('.sheet'));
      requestAnimationFrame(() => sheet && sheet.classList.add('is-open'));
    }
    sheet.dataset.name = name;
    setChildren(sheet.querySelector('.sheet-body'), body);
    if (!fresh) sheet.querySelector('.sheet').scrollTop = 0;
  }

  /** Swipe sideways on the profile for the next person. */
  function swipe(node) {
    let x0 = null; let y0 = null;
    node.addEventListener('touchstart', (e) => {
      if (e.touches.length !== 1) return;
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
    }, { passive: true });
    node.addEventListener('touchend', (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      const dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy) * 1.6) step(dx < 0 ? 1 : -1);
    }, { passive: true });
  }

  function tile(label, value, toneName) {
    return el('div', { class: 'pf-tile' },
      el('b', { class: toneName ? `v-${toneName}` : '' }, value),
      el('span', {}, label));
  }

  /* ------------------------------------------------ the 3D landscape */

  /**
   * Blocks on a grid, one row per person (or team), one column per week; the
   * height is the load, 100% is the glass sheet. Drag sideways to turn it,
   * tap a block to read it. Painter's order, flat shading: a few dozen
   * blocks, so it draws in well under a frame on a phone.
   */
  function landscape(host, model) {
    const canvas = el('canvas', { class: 'scape-canvas', role: 'img',
      'aria-label': model.summary || 'Load landscape' });
    const tip = el('div', { class: 'scape-tip', hidden: true });
    const controls = el('div', { class: 'scape-controls' },
      ctl('⟲', 'Turn left', () => turn(-0.35)),
      ctl('⟳', 'Turn right', () => turn(0.35)),
      ctl('▲', 'Look from higher', () => tilt(0.12)),
      ctl('▼', 'Look from lower', () => tilt(-0.12)),
      ctl('+', 'Closer', () => zoom(0.88)),
      ctl('−', 'Further', () => zoom(1.14)),
      ctl('⌂', 'Back to the start', () => reset()));
    const stage = el('div', { class: 'scape-stage' }, canvas, tip, controls);
    setChildren(host, stage);

    const rows = model.rows; const cols = model.cols;
    const R = rows.length; const C = cols.length;
    const narrow = (host.clientWidth || 320) < 520;
    // A phone is narrow: look along the weeks more, from higher, so the rows spread out.
    const view = { yaw: narrow ? -0.32 : -0.62, pitch: narrow ? 0.82 : 0.62, dist: 1,
      grow: reduced() ? 1 : 0, picked: null };
    const start = { ...view };
    let colors = null;
    let boxes = [];
    let drawn = [];  // [{poly, box}] front-most last

    function ctl(text, label, fn) {
      return el('button', { class: 'scape-btn', type: 'button', title: label, 'aria-label': label, onclick: fn }, text);
    }
    function turn(by) { animateTo({ yaw: view.yaw + by }); }
    function tilt(by) { animateTo({ pitch: clamp(view.pitch + by, 0.18, 1.25) }); }
    function zoom(by) { animateTo({ dist: clamp(view.dist * by, 0.6, 1.6) }); }
    function reset() { view.picked = null; tip.hidden = true; animateTo({ yaw: start.yaw, pitch: start.pitch, dist: start.dist }); }

    let anim = null;
    function animateTo(target) {
      if (reduced()) { Object.assign(view, target); draw(); return; }
      const from = { yaw: view.yaw, pitch: view.pitch, dist: view.dist };
      const to = { ...from, ...target };
      const t0 = performance.now();
      cancelAnimationFrame(anim);
      const tick = (now) => {
        const k = clamp((now - t0) / 260, 0, 1);
        const ease = 1 - (1 - k) ** 3;
        for (const key of Object.keys(to)) view[key] = from[key] + (to[key] - from[key]) * ease;
        draw();
        if (k < 1) anim = requestAnimationFrame(tick);
      };
      anim = requestAnimationFrame(tick);
    }

    function readColors() {
      const cs = getComputedStyle(document.documentElement);
      const v = (name, fallback) => (cs.getPropertyValue(name).trim() || fallback);
      colors = {
        bad: v('--bad', '#a62828'), ok: v('--ok', '#16794a'), warn: v('--accent', '#1c5fa8'),
        none: v('--border', '#dcdfe5'), text: v('--text', '#14181f'), muted: v('--muted', '#5d6673'),
        grid: v('--border', '#dcdfe5'), glass: v('--accent', '#1c5fa8'), surface: v('--surface', '#fff'),
      };
    }

    function rgb(hex) {
      const h = hex.replace('#', '');
      const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
      const n = parseInt(full.slice(0, 6), 16);
      return Number.isNaN(n) ? [120, 120, 120] : [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    function shade(hex, k, alpha = 1) {
      const [r, g, b] = rgb(hex);
      const f = (c) => Math.round(clamp(k >= 1 ? c + (255 - c) * (k - 1) : c * k, 0, 255));
      return `rgba(${f(r)},${f(g)},${f(b)},${alpha})`;
    }

    const toneOf = (v) => (v === null || v === undefined ? 'none' : v > 1.0001 ? 'bad' : v < 0.8 ? 'warn' : 'ok');
    const HMAX = 1.8;  // a load of 180% fills the height
    const UNIT = 0.9;  // height of a full load, in grid cells

    function build() {
      boxes = [];
      for (let r = 0; r < R; r += 1) {
        for (let c = 0; c < C; c += 1) {
          const v = model.values[r][c];
          boxes.push({ r, c, v, x: c - (C - 1) / 2, z: r - (R - 1) / 2,
            h: Math.max(0.03, (clamp(v || 0, 0, HMAX)) * UNIT) });
        }
      }
    }

    let W = 0; let H = 0; let dpr = 1;
    let labelW = 60;
    function measure() {
      const ctx = canvas.getContext('2d');
      ctx.font = '600 11px system-ui, sans-serif';
      // A long team name is cut short rather than squeezing the blocks.
      const most = W < 520 ? 110 : 170;
      for (const row of rows) {
        let text = row.label;
        while (text.length > 4 && ctx.measureText(text).width > most) text = text.slice(0, -1);
        row.shown = text === row.label ? text : `${text.trimEnd()}…`;
      }
      labelW = Math.max(40, ...rows.map((row) => ctx.measureText(row.shown).width));
    }
    // Few rows and many weeks would make a thin strip: rows are spread
    // further apart, so the block keeps some depth.
    const ZS = clamp(C / (R * 1.9), 1, 2.2);

    function rawFor(yaw, pitch) {
      const cy = Math.cos(yaw); const sy = Math.sin(yaw);
      const cp = Math.cos(pitch); const sp = Math.sin(pitch);
      const camD = (Math.max(C, R * ZS) + 2) * 3.2;
      return (x, y, zr) => {
        const z = zr * ZS;
        // turn round the vertical axis, then tip towards the viewer
        const x1 = x * cy - z * sy;
        const z1 = x * sy + z * cy;
        const y2 = y * cp - z1 * sp;
        const z2 = -(y * sp + z1 * cp);  // away from the viewer is positive
        const k = camD / (camD + z2);
        return [x1 * k, -y2 * k, z2];
      };
    }

    function bounds(raw) {
      const hx = C / 2 + 0.6; const hz = R / 2 + 0.6 / ZS; const top = UNIT * 1.25;
      const b = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
      for (const x of [-hx, hx]) {
        for (const z of [-hz, hz]) {
          for (const y of [0, top]) {
            const [px, py] = raw(x, y, z);
            b.minX = Math.min(b.minX, px); b.maxX = Math.max(b.maxX, px);
            b.minY = Math.min(b.minY, py); b.maxY = Math.max(b.maxY, py);
          }
        }
      }
      return b;
    }

    const PAD = { r: 24, t: 18, b: 22 };

    function size() {
      W = host.clientWidth || 320;
      measure();
      // As tall as the block needs at the starting angle, no taller.
      const b = bounds(rawFor(start.yaw, start.pitch));
      const across = W - labelW - 22 - PAD.r;
      const tall = (across * (b.maxY - b.minY)) / (b.maxX - b.minX) + PAD.t + PAD.b + 24;
      H = clamp(Math.round(tall), 150, 460);
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
    }

    function projector() {
      const raw = rawFor(view.yaw, view.pitch);
      // Fit the whole block, labels included, into the canvas whatever the
      // angle, so it never runs off a phone's screen.
      const b = bounds(raw);
      const padL = labelW + 22;
      const k0 = Math.min((W - padL - PAD.r) / (b.maxX - b.minX),
        (H - PAD.t - PAD.b) / (b.maxY - b.minY)) / view.dist;
      const ox = padL + (W - padL - PAD.r) / 2 - ((b.minX + b.maxX) / 2) * k0;
      const oy = PAD.t + (H - PAD.t - PAD.b) / 2 - ((b.minY + b.maxY) / 2) * k0;
      return (x, y, z) => {
        const [px, py, d] = raw(x, y, z);
        return [ox + px * k0, oy + py * k0, d];
      };
    }

    function face(P, pts) { return pts.map(([x, y, z]) => P(x, y, z)); }
    function fillPoly(ctx, poly, fill, stroke) {
      ctx.beginPath();
      poly.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.fillStyle = fill; ctx.fill();
      if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1; ctx.stroke(); }
    }

    function draw() {
      if (!colors) readColors();
      const ctx = canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const P = projector();
      const x0 = -C / 2; const x1 = C / 2; const z0 = -R / 2; const z1 = R / 2;

      // the floor and its grid
      fillPoly(ctx, face(P, [[x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1]]), shade(colors.grid, 1, 0.35));
      ctx.strokeStyle = shade(colors.grid, 0.9, 0.9); ctx.lineWidth = 1;
      for (let c = 0; c <= C; c += 1) {
        const a = P(x0 + c, 0, z0); const b = P(x0 + c, 0, z1);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
      for (let r = 0; r <= R; r += 1) {
        const a = P(x0, 0, z0 + r); const b = P(x1, 0, z0 + r);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
      // where the past ends and the coming weeks start
      if (model.now !== null && model.now !== undefined && model.now > 0 && model.now < C) {
        const a = P(x0 + model.now, 0, z0 - 0.2); const b = P(x0 + model.now, 0, z1 + 0.1);
        ctx.save(); ctx.setLineDash([5, 4]); ctx.strokeStyle = colors.text; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); ctx.restore();
      }

      // the blocks, furthest first
      const grow = view.grow;
      const order = boxes.map((b) => ({ b, d: P(b.x, b.h / 2, b.z)[2] })).sort((a, b) => b.d - a.d);
      const glassY = UNIT;
      drawn = [];
      const s = 0.36; const sz = 0.36 / ZS;
      for (const { b } of order) {
        const h = b.h * grow;
        const base = colors[toneOf(b.v)] || colors.none;
        const picked = view.picked && view.picked.r === b.r && view.picked.c === b.c;
        const x = b.x; const z = b.z;
        const faces = [
          { pts: [[x - s, h, z - sz], [x + s, h, z - sz], [x + s, h, z + sz], [x - s, h, z + sz]], k: 1.18 }, // top
          { pts: [[x - s, 0, z + sz], [x + s, 0, z + sz], [x + s, h, z + sz], [x - s, h, z + sz]], k: 0.9 }, // front
          { pts: [[x + s, 0, z - sz], [x - s, 0, z - sz], [x - s, h, z - sz], [x + s, h, z - sz]], k: 0.9 }, // back
          { pts: [[x + s, 0, z + sz], [x + s, 0, z - sz], [x + s, h, z - sz], [x + s, h, z + sz]], k: 0.72 }, // right
          { pts: [[x - s, 0, z - sz], [x - s, 0, z + sz], [x - s, h, z + sz], [x - s, h, z - sz]], k: 0.72 }, // left
        ];
        // A block is convex: its faces drawn furthest first need no culling.
        const polys = faces.map((f) => ({ f, poly: face(P, f.pts) }))
          .map((x) => ({ ...x, d: x.poly.reduce((sum, pt) => sum + pt[2], 0) / x.poly.length }))
          .sort((a, b) => b.d - a.d)
          .map(({ f, poly }) => {
            fillPoly(ctx, poly, picked ? shade(base, f.k * 1.25) : shade(base, f.k),
              picked ? colors.text : shade(base, 0.6, 0.5));
            return poly;
          });
        drawn.push({ b, polys });
      }
      // the sheet of glass at a full load, over everything, faint enough to see through
      fillPoly(ctx, face(P, [[x0, glassY, z0], [x1, glassY, z0], [x1, glassY, z1], [x0, glassY, z1]]),
        shade(colors.glass, 1, 0.08), shade(colors.glass, 1, 0.4));

      // names down the side, weeks along the front
      ctx.font = '600 11px system-ui, sans-serif';
      for (let r = 0; r < R; r += 1) {
        const p = P(x0 - 0.25, 0, z0 + r + 0.5);
        ctx.fillStyle = colors.text; ctx.textAlign = 'right';
        ctx.fillText(rows[r].shown || rows[r].label, p[0] - 4, p[1] + 4);
        if (rows[r].color) {
          const m = /var\((--[\w-]+)\)/.exec(rows[r].color);
          ctx.fillStyle = m ? (getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || colors.muted) : rows[r].color;
          ctx.beginPath(); ctx.arc(p[0] + 2, p[1], 3.5, 0, Math.PI * 2); ctx.fill();
        }
      }
      ctx.font = '10.5px system-ui, sans-serif'; ctx.fillStyle = colors.muted; ctx.textAlign = 'center';
      const every = C > 10 ? 2 : 1;
      for (let c = 0; c < C; c += every) {
        const p = P(x0 + c + 0.5, 0, z1 + 0.5);
        ctx.fillText(cols[c], p[0], p[1] + 4);
      }
      if (model.now !== null && model.now !== undefined && model.now > 0 && model.now < C) {
        const t = P(x0 + model.now, 0, z1 + 0.15);
        ctx.font = '700 11px system-ui, sans-serif'; ctx.textAlign = 'left';
        ctx.fillStyle = colors.text; ctx.fillText('▲ today', t[0] - 6, t[1] + 16);
      }
      const g = P(x1 + 0.1, glassY, z0);
      ctx.fillStyle = colors.glass; ctx.textAlign = 'left'; ctx.font = '600 10.5px system-ui, sans-serif';
      ctx.fillText('100%', g[0] + 4, g[1]);
    }

    function inside(poly, x, y) {
      let hit = false;
      for (let i = 0, j = poly.length - 1; i < poly.length; j = i, i += 1) {
        const [xi, yi] = poly[i]; const [xj, yj] = poly[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
      }
      return hit;
    }

    function pick(x, y) {
      for (let i = drawn.length - 1; i >= 0; i -= 1) {
        if (drawn[i].polys.some((poly) => inside(poly, x, y))) return drawn[i].b;
      }
      return null;
    }

    function showTip(b, x, y) {
      if (!b) { view.picked = null; tip.hidden = true; draw(); return; }
      view.picked = { r: b.r, c: b.c };
      tip.hidden = false;
      setChildren(tip, el('b', {}, rows[b.r].label), el('span', {}, model.text(b.r, b.c, b.v)));
      const left = clamp(x + 12, 4, W - 190);
      tip.style.left = `${left}px`;
      tip.style.top = `${clamp(y - 52, 4, H - 60)}px`;
      draw();
      if (model.onPick) model.onPick(b.r, b.c);
    }

    // drag sideways to turn; a mouse can tip it too; a tap reads a block
    let down = null;
    canvas.addEventListener('pointerdown', (e) => {
      down = { x: e.clientX, y: e.clientY, yaw: view.yaw, pitch: view.pitch, moved: false, id: e.pointerId, type: e.pointerType };
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!down || e.pointerId !== down.id) return;
      const dx = e.clientX - down.x; const dy = e.clientY - down.y;
      if (!down.moved && Math.abs(dx) + Math.abs(dy) > 6) {
        down.moved = true;
        try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* already gone */ }
        tip.hidden = true;
      }
      if (!down.moved) return;
      view.yaw = down.yaw + dx * 0.009;
      if (down.type === 'mouse') view.pitch = clamp(down.pitch + dy * 0.006, 0.18, 1.25);
      cancelAnimationFrame(anim);
      anim = requestAnimationFrame(draw);
    });
    const up = (e) => {
      if (!down || e.pointerId !== down.id) return;
      const was = down; down = null;
      if (!was.moved) {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left; const y = e.clientY - rect.top;
        showTip(pick(x, y), x, y);
      }
    };
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', () => { down = null; });

    readColors(); size(); build(); draw();
    // The blocks rise into place the first time, and the view swings round a
    // little, so it reads as 3D at a glance.
    if (!reduced()) {
      const t0 = performance.now();
      const yaw0 = view.yaw - 0.5;
      const rise = (now) => {
        const k = clamp((now - t0) / 900, 0, 1);
        const ease = 1 - (1 - k) ** 3;
        view.grow = ease;
        view.yaw = yaw0 + 0.5 * ease;
        draw();
        if (k < 1 && canvas.isConnected) anim = requestAnimationFrame(rise);
      };
      anim = requestAnimationFrame(rise);
    }
    if (window.ResizeObserver) {
      let last = host.clientWidth;
      new ResizeObserver(() => {
        if (!canvas.isConnected || host.clientWidth === last) return;
        last = host.clientWidth; size(); draw();
      }).observe(host);
    }
    const scheme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
    if (scheme && scheme.addEventListener) {
      scheme.addEventListener('change', () => { if (canvas.isConnected) { readColors(); draw(); } });
    }
    return { redraw: draw };
  }

  /* -------------------------------------- the landscape on Check-ins */

  const scape = { mode: 'next', outlook: null };

  function shortWeek(iso) {
    return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }

  /** People: the last weeks from the timesheets, then the next two as laid out. */
  function peopleModel(data) {
    const people = (data.people || []).filter((p) => (p.weeks || []).length);
    if (!people.length) return null;
    const past = data.weeks || [];
    // the next two weeks, from the days Check-ins lays out
    const ahead = [];
    for (const p of people) {
      const byWeek = new Map();
      for (const d of p.days || []) {
        const day = new Date(`${d.date}T00:00:00`);
        const monday = new Date(day);
        monday.setDate(day.getDate() - ((day.getDay() + 6) % 7));
        const key = `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, '0')}-${String(monday.getDate()).padStart(2, '0')}`;
        const w = byWeek.get(key) || { booked: 0, cap: 0 };
        if (!d.away) {
          w.booked += (d.booked || 0) + (d.over || 0);
          w.cap += data.hours_per_day || 8;
        }
        byWeek.set(key, w);
      }
      ahead.push(byWeek);
    }
    const aheadKeys = [...new Set(ahead.flatMap((m) => [...m.keys()]))].sort();
    const cols = past.map(shortWeek).concat(aheadKeys.map(shortWeek));
    const values = people.map((p, i) => {
      const back = past.map((wk) => {
        const w = (p.weeks || []).find((x) => x.week === wk);
        return w ? w.load : null;
      });
      const next = aheadKeys.map((k) => {
        const w = ahead[i].get(k);
        return w && w.cap ? w.booked / w.cap : null;
      });
      return back.concat(next);
    });
    return {
      rows: people.map((p) => ({ label: p.name, color: engineerColor(p.name) })),
      cols,
      values,
      now: past.length,
      summary: `Load per person, the last ${past.length} weeks and the next ${aheadKeys.length}`,
      text: (r, c, v) => `${c < past.length ? 'Week of' : 'Coming week of'} ${cols[c]}: `
        + `${v === null || v === undefined ? 'no hours' : `${pct(v)} of their hours`}`,
      onPick: (r) => { scape.picked = people[r].name; },
    };
  }

  /** The next two weeks, one tower per person, before and after the planner's suggestions. */
  function nextModel(data, outlook) {
    const names = new Set((data.people || []).map((p) => p.name));
    const people = (outlook.people || []).filter((p) => names.has(p.name) && p.before)
      .map((p) => ({
        name: p.name, color: engineerColor(p.name), now: p.before.load || 0,
        after: (p.after || p.before).load || 0, hours: p.before.hours, hoursAfter: (p.after || p.before).hours,
        capacity: p.capacity, items: p.items || [],
      }))
      .sort((a, b) => b.now - a.now);
    if (!people.length) return null;
    const byName = new Map(people.map((p) => [p.name, p]));
    const projectName = new Map((outlook.projects || []).map((p) => [p.number, p.name]));
    const moves = (outlook.suggested || []).filter((m) => byName.has(m.from) && byName.has(m.to)).map((m) => {
      const item = (byName.get(m.from).items || []).find((it) => it.project === m.project || it.key === m.project);
      const hours = item && m.share ? item.hours_before * m.share : null;
      return { ...m, hours, name: projectName.get(m.project) || m.project,
        label: `${m.project}${hours ? ` · ${Math.round(hours)} h` : ''}` };
    });
    return {
      people, moves, byName, summary: outlook.summary || {},
      text: (p, which) => (which === 'after'
        ? `After the moves: ${pct(p.after)} of their hours (${hrs(p.hoursAfter)} lined up for ${hrs(p.capacity)}).`
        : `Next two weeks: ${pct(p.now)} of their hours (${hrs(p.hours)} lined up for ${hrs(p.capacity)}).`),
    };
  }

  /** What to do about it, in plain sentences, each with the place to do it. */
  function ideas(data, model) {
    const out = [];
    const go = (label, action) => el('button', { class: 'btn btn-sm', type: 'button', onclick: action }, label);
    const board = () => window.planner && window.planner.board();
    const people = new Map((data.people || []).map((p) => [p.name, p]));
    if (model) {
      for (const m of model.moves) {
        const from = model.byName.get(m.from); const to = model.byName.get(m.to);
        out.push({ tone: 'move', title: `Hand ${m.to} part of ${m.name}`,
          text: `${m.from} is at ${pct(from.now)} over the next two weeks and ${m.to} is at ${pct(to.now)}. `
            + `Moving ${Math.round(m.share * 100)}% of ${m.project}${m.hours ? ` (about ${Math.round(m.hours)} h)` : ''} `
            + `brings ${m.from} to ${pct(from.after)} and ${m.to} to ${pct(to.after)}.`,
          action: go('Plan it on the board', board) });
      }
      const still = model.people.filter((p) => p.after > 1.05);
      if (still.length) {
        out.push({ tone: 'bad', title: `${still.length === 1 ? `${still[0].name} stays` : `${still.length} people stay`} over a full load`,
          text: `${still.map((p) => `${p.name} (${pct(p.after)})`).join(', ')} will still be over even after `
            + 'the handovers, because nobody doing the same kind of work has room. Push a due date back, or ask for more people.',
          action: go('See who to ask for', () => switchView('planner')) });
      }
    }
    for (const p of data.people || []) {
      if (!p.signal || p.signal.key !== 'rest') continue;
      const off = p.last_day_off ? Math.round((Date.now() - new Date(`${p.last_day_off}T00:00:00`)) / 864e5) : null;
      out.push({ tone: 'rest', title: `Give ${p.name} a lighter week`,
        text: `${(p.signal.reasons || []).slice(0, 2).join(', ')}.`
          + (off !== null && off > 20 ? ` Their last day off was ${off} days ago: a day off would help.` : ''),
        action: go('Plan a lighter week', board) });
    }
    const taking = new Set(model ? model.moves.map((m) => m.to) : []);
    for (const c of data.can_take || []) {
      if (taking.has(c.name)) continue;
      out.push({ tone: 'room', title: `${c.name} can take the next job`,
        text: `${hrs(c.free_week)} free this week${c.next_free ? `, from ${new Date(`${c.next_free}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}` : ''}.`,
        action: go('Add a task', () => switchView('tasks')) });
    }
    const urgent = [];
    for (const p of data.people || []) {
      for (const c of p.checkpoints || []) if (c.level === 'now' && c.kind !== 'rest') urgent.push(c);
    }
    for (const c of urgent.slice(0, 2)) {
      out.push({ tone: 'ask', title: 'Ask about this today', text: c.text, action: go('Open Tasks', () => switchView('tasks')) });
    }
    return out.slice(0, 6);
  }

  function ideaList(items) {
    if (!items.length) {
      return el('div', { class: 'idea-none' }, 'Nothing needs you this fortnight: everyone is within their hours.');
    }
    return el('ol', { class: 'ideas' }, ...items.map((it, k) => el('li', { class: `idea idea-${it.tone}` },
      el('span', { class: 'idea-n' }, String(k + 1)),
      el('div', { class: 'idea-body' },
        el('b', {}, it.title),
        el('p', {}, it.text),
        it.action))));
  }

  async function renderScape() {
    const host = $('#checkins-scape');
    if (!host) return;
    const data = typeof checkin !== 'undefined' ? checkin.data : null;
    if (!data || !(data.people || []).length) { host.hidden = true; return; }
    show.checkins = data;
    host.hidden = false;
    let model = null;
    if (!scape.outlook) {
      try {
        scape.outlook = await api('/api/planner/suggest', { quiet: true, method: 'POST', body: { days: 10, moves: [] } });
      } catch (error) { scape.outlook = null; }
    }
    const next = scape.outlook ? nextModel(data, scape.outlook) : null;
    if (scape.mode === 'next' && !next) scape.mode = 'weeks';
    if (scape.mode === 'weeks') model = peopleModel(data);
    if (scape.mode === 'weeks' && !model) { host.hidden = true; return; }
    const stage = el('div', { class: 'scape-host' });
    const pick = (mode, label) => el('button', {
      class: `subtab ${scape.mode === mode ? 'is-active' : ''}`, type: 'button',
      onclick: () => { scape.mode = mode; renderScape(); },
    }, label);
    let instance = null;
    let after = false;
    const toggle = scape.mode === 'next' && next.moves.length
      ? el('button', {
        class: 'btn btn-primary btn-sm scape-toggle', type: 'button',
        onclick: (e) => {
          after = !after;
          e.currentTarget.textContent = after ? 'Back to now' : 'Show the suggested moves';
          if (instance && instance.show) instance.show(after ? 'after' : 'now');
        },
      }, 'Show the suggested moves')
      : null;
    setChildren(host,
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, scape.mode === 'next' ? 'Who is over, who has room: the next two weeks' : 'Week by week, in 3D'),
          el('p', { class: 'muted' },
            scape.mode === 'next'
              ? 'One tower per person: the taller it is, the more work they have lined up for the next two weeks. '
                + 'Above the glass sheet means more than their hours. '
                + (next.moves.length ? 'Press "Show the suggested moves" to see who should hand what to whom.' : '')
              : 'Each block is one person\'s week: its height is how much of their hours they booked, '
                + 'the glass sheet is a full load. Left of the blue line are past weeks, right of it the next two.')),
        el('div', { class: 'subtabs scape-modes' },
          next ? pick('next', 'Next two weeks') : null, pick('weeks', 'Week by week'))),
      toggle ? el('div', { class: 'scape-actions' }, toggle) : null,
      stage,
      el('div', { class: 'legend scape-legend' },
        el('span', { class: 'legend-item' }, el('span', { class: 'swatch', style: 'background:var(--series-1)' }), 'has room'),
        el('span', { class: 'legend-item' }, el('span', { class: 'swatch', style: 'background:var(--series-3)' }), 'about right'),
        el('span', { class: 'legend-item' }, el('span', { class: 'swatch', style: 'background:var(--series-4)' }), 'heavy'),
        el('span', { class: 'legend-item' }, el('span', { class: 'swatch', style: 'background:var(--bad)' }), 'over their hours')),
      el('div', { class: 'ideas-wrap' },
        el('h4', {}, 'What to do'),
        ideaList(ideas(data, next))));
    // The real 3D when the phone can draw it; the flat drawing if not.
    try {
      if (scape.mode === 'next') {
        const three = await import('./team3d.js');
        if (stage.isConnected) instance = three.render(stage, next);
        if (instance) return;
        stage.replaceChildren(el('p', { class: 'muted' }, 'This phone cannot draw 3D; the ideas below say the same thing.'));
        if (toggle) toggle.remove();
        return;
      }
      const three = await import('./load3d.js');
      if (stage.isConnected && three.render(stage, model)) return;
    } catch (error) { /* no WebGL or no modules: fall through */ }
    if (stage.isConnected && model) landscape(stage, model);
  }

  /* ----------------------------------------------------------- wiring */

  function wire() {
    if (window.checkins) {
      const load = window.checkins.load;
      const summary = window.checkins.summary;
      window.checkins.load = async (...args) => { await load(...args); renderScape(); };
      window.checkins.summary = async (...args) => {
        await summary(...args);
        show.checkins = null; show.outlook = null; scape.outlook = null;
        if ($('#view-checkins').classList.contains('is-active')) renderScape();
        if ($('#view-team').classList.contains('is-active')) teamCards();
      };
    }
  }

  window.showcase = { profile, teamCards, landscape, renderScape };
  wire();
}());
