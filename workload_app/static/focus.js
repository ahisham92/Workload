/* Selecao+ — one question, one answer, only the extras under Show more.
 *
 * Ahmed (9 Oct): too many paths and tabs, and too much on each. Every tab
 * should answer the question the person came with; anything more waits under
 * "Show more".
 *
 * So:
 *   - tabs that answer the same kind of question share one tab in the bar.
 *     Tasks sits with Planner, Resourcing with Check-ins, Budgets with
 *     Projects, Growth with Reports, Timesheets with Bring in data and
 *     Reference with Team. Each keeps its own page: a switch in the header
 *     moves between them, and links to them (#tasks, the guide) still work;
 *   - each page's header asks its question, and an answer card under it
 *     answers it in one sentence from what the page already loaded, with the
 *     one thing to do next;
 *   - each part of a page is headed by the question it answers, and the
 *     important parts stay open (Ahmed, 9 Oct: "important details should be
 *     shown by default"); only the extras on it are
 *     folded under one "Show more" at the bottom, which names what it holds.
 *
 * Nothing is removed and nothing new is asked of the server: the answers are
 * read from the replies the page's own requests got (api() is wrapped to keep
 * the last reply of each read) and from app.js's state. Built on common.js's
 * make and $$, and app.js's switchView, api and state.
 */
(function () {
  'use strict';

  /* -- which pages share a tab ------------------------------------------- */

  // The first page of each group keeps its button in the bar.
  const GROUPS = [
    ['planner', 'tasks'],
    ['checkins', 'resourcing'],
    ['projects', 'budgets'],
    ['reports', 'growth'],
    ['bringin', 'timesheets'],
    ['team', 'reference'],
  ];
  const groupOf = (view) => GROUPS.find((g) => g.includes(view)) || null;
  const headOf = (view) => (groupOf(view) || [view])[0];

  /* -- the question each page answers ------------------------------------ */

  const QUESTION = {
    overview: 'Is the team on track this year?',
    planner: 'Who is doing what today, and who has room?',
    tasks: 'What is due, and is anything late or stuck?',
    checkins: 'Who needs help, and who can take more?',
    resourcing: 'Does each team have the people for its work?',
    weekly: 'What needs doing this week?',
    projects: 'Which jobs need attention?',
    budgets: 'Is any job running out of budget?',
    reports: 'How is each person scoring?',
    growth: 'Is everyone growing?',
    bringin: 'Is the data up to date?',
    timesheets: 'Have the timesheets come in?',
    team: 'Who is on the team, and is everyone set up?',
    reference: 'What are the numbers measured against?',
    guide: 'Where do I start, and where do I find things?',
  };

  /* -- the last reply to each read ---------------------------------------- */

  const replies = {};
  const keyOf = (path) => String(path).split('?')[0];

  function wrapApi() {
    const ask = window.api;
    if (typeof ask !== 'function' || ask.wrappedByFocus) return;
    const wrapped = async function (path, options = {}) {
      const reply = await ask.call(this, path, options);
      const reading = !options.method || options.method === 'GET';
      if (reading && reply && typeof reply === 'object') {
        replies[keyOf(path)] = reply;
        later();
      }
      return reply;
    };
    wrapped.wrappedByFocus = true;
    window.api = wrapped;
  }

  /* -- small words ---------------------------------------------------------- */

  const pct = (v) => `${Math.round(Number(v) * 100)}%`;
  const hrs = (v) => `${Math.round(Number(v) * 10) / 10} h`;
  /** "Mariam", "Mariam and Nour", "Mariam, Nour and Osama"; at most `most` named. */
  function names(list, most = 3) {
    const shown = list.slice(0, most);
    const rest = list.length - shown.length;
    if (rest > 0) return `${shown.join(', ')} and ${rest} more`;
    return shown.length > 1 ? `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}` : (shown[0] || '');
  }
  const isoToday = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  };
  const daysBetween = (a, b) => Math.round(
    (new Date(`${b}T00:00:00`) - new Date(`${a}T00:00:00`)) / 86400000);
  const worst = (...tones) => (tones.includes('bad') ? 'bad' : tones.includes('warn') ? 'warn' : 'ok');
  const app = () => (typeof state !== 'undefined' ? state : {});

  /* -- the answers -----------------------------------------------------------
   * Each returns { say, tone, next, act } or null while its data is not in.
   * say: the answer in one sentence. tone: ok, warn or bad. next: the one
   * thing to do about it. act: a button, as [label, view] or [label, 'more']. */

  const ANSWER = {
    overview() {
      const report = app().report;
      const team = report && report.team;
      if (!team || team.utilisation === undefined) return null;
      const u = team.utilisation; const cpi = team.cpi; const plan = team.plan_adherence;
      const busyTone = u === null ? 'ok' : (u >= 0.85 && u <= 1.05 ? 'ok' : u >= 0.7 ? 'warn' : 'bad');
      const cpiTone = cpi === null ? 'ok' : (cpi >= 1 ? 'ok' : cpi >= 0.9 ? 'warn' : 'bad');
      const planTone = plan === null ? 'ok' : (plan >= 0.9 ? 'ok' : plan >= 0.75 ? 'warn' : 'bad');
      const parts = [];
      if (u !== null) parts.push(`busy at ${pct(u)}`);
      if (cpi !== null) parts.push(`earning ${Number(cpi).toFixed(2)} for each hour spent`);
      if (plan !== null) parts.push(`${pct(plan)} on plan`);
      if (!parts.length) return null;
      const tone = worst(busyTone, cpiTone, planTone);
      let next = 'All three are where they should be.';
      let act = null;
      if (planTone !== 'ok') { next = 'Behind plan: see which jobs are behind.'; act = ['Open Projects', 'projects']; }
      else if (cpiTone !== 'ok') { next = 'Costing more than it earns: see which jobs.'; act = ['Open Projects', 'projects']; }
      else if (busyTone !== 'ok') { next = u > 1.05 ? 'Too much overtime: see who needs a lighter week.' : 'Room to take more work: see who has it.'; act = ['Open Who needs help', 'checkins']; }
      return { say: `The team is ${parts.join(', ')}.`, tone, next, act };
    },

    planner() {
      const data = replies['/api/day'];
      if (!data || !data.days || !data.days.length) return null;
      const day = data.days.find((d) => d.date === data.today) || data.days[0];
      if (!day.working_day) {
        return { say: 'Today is not a working day.', tone: 'ok', next: 'Use the arrows to see the next one.' };
      }
      const people = day.people || [];
      const away = people.filter((p) => p.away).map((p) => p.name);
      const room = people.filter((p) => !p.away && p.free_hours >= 1)
        .sort((a, b) => b.free_hours - a.free_hours);
      const busy = people.length - away.length - room.length;
      let say = room.length
        ? `${names(room.map((p) => `${p.name} (${hrs(p.free_hours)})`))} ${room.length > 1 ? 'have' : 'has'} room today; ${busy} ${busy === 1 ? 'person is' : 'people are'} booked full.`
        : `Everyone in today is booked full${people.length ? ` (${people.length - away.length} people)` : ''}.`;
      if (away.length) say += ` ${names(away)} ${away.length > 1 ? 'are' : 'is'} off today.`;
      return { say, tone: room.length ? 'ok' : 'warn',
        next: room.length ? 'Something new came in? Type it in the box below: it goes to whoever has room.'
          : 'Something new came in? Type it below and "What does it push?" shows what slips.' };
    },

    tasks() {
      const data = app().tasks;
      if (!data || !data.tasks) return null;
      const today = isoToday();
      const open = data.tasks.filter((t) => !t.done);
      const late = open.filter((t) => t.due && t.due < today);
      const stuck = open.filter((t) => /block/i.test(t.status || ''));
      const soon = open.filter((t) => t.due && t.due >= today && daysBetween(today, t.due) <= 7);
      if (!open.length) return { say: 'No open tasks.', tone: 'ok', next: 'Add one with Add task, above.' };
      const bits = [];
      if (late.length) bits.push(`${late.length} late`);
      if (stuck.length) bits.push(`${stuck.length} stuck`);
      bits.push(`${soon.length} due in the next 7 days`);
      const first = late[0] || stuck[0] || soon[0];
      return {
        say: `${open.length} open task${open.length === 1 ? '' : 's'}: ${bits.join(', ')}.`,
        tone: late.length || stuck.length ? 'bad' : 'ok',
        next: first ? `First: ${first.name} (${(first.assignees || []).join(', ') || 'nobody yet'}), due ${dayFirst(first.due)}.` : 'Nothing is late or stuck.',
      };
    },

    checkins() {
      const data = replies['/api/checkins'];
      if (!data || !data.people) return null;
      const rest = data.people.filter((p) => p.signal && p.signal.key === 'rest').map((p) => p.name);
      const take = (data.can_take || []).map((p) => `${p.name} (${hrs(p.free_week)} free)`);
      const bits = [];
      if (rest.length) bits.push(`${names(rest)} ${rest.length > 1 ? 'need' : 'needs'} a lighter week`);
      if (take.length) bits.push(`${names(take)} can take more`);
      const say = bits.length ? `${bits.join('; ')}.` : 'Nobody is over, and nobody has spare hours this week.';
      return {
        say: say.charAt(0).toUpperCase() + say.slice(1),
        tone: rest.length ? 'bad' : 'ok',
        next: data.urgent ? `${data.urgent} thing${data.urgent === 1 ? '' : 's'} to ask today: they are in What to do, below.` : 'Nothing to ask today.',
      };
    },

    resourcing() {
      const data = replies['/api/resourcing'] || app().resourcing;
      if (!data || !data.findings) return null;
      const first = data.findings[0];
      if (!first) return { say: 'Every team has the people for the work it has been doing.', tone: 'ok', next: 'Judged on the last three months of booked hours.' };
      return {
        say: `${first.headline}${data.findings.length > 1 ? `, and ${data.findings.length - 1} more` : ''}.`,
        tone: first.level === 'bad' ? 'bad' : 'warn',
        next: dayFirstText(first.detail),
      };
    },

    weekly() {
      const data = replies['/api/weekly'];
      if (!data || !data.headline) return null;
      const first = (data.todo || [])[0];
      return {
        say: dayFirstText(data.headline),
        tone: (data.todo || []).some((t) => t.tone === 'bad') ? 'warn' : 'ok',
        next: first ? `Start with: ${dayFirstText(first.text)}` : 'Nothing to act on this week.',
      };
    },

    projects() {
      const metrics = app().projectMetrics || [];
      if (!metrics.length) return null;
      const live = metrics.filter((m) => /active/i.test(m.status || ''));
      const losing = live.filter((m) => m.cpi !== null && m.cpi !== undefined && m.cpi < 0.95)
        .sort((a, b) => a.cpi - b.cpi);
      const over = live.filter((m) => m.budget_mm && m.cost_at_completion_mm > m.budget_mm);
      if (!live.length) return { say: 'No job is active.', tone: 'ok', next: 'Every job the timesheets turn up is listed below.' };
      if (!losing.length && !over.length) {
        return { say: `All ${live.length} active jobs earn at least what they cost.`, tone: 'ok', next: 'Tap a job to see its deliverables and who worked on it.' };
      }
      const bits = [];
      if (losing.length) bits.push(`${losing.length} of ${live.length} active jobs cost more than they earn: ${names(losing.map((m) => `${m.number} (${Number(m.cpi).toFixed(2)})`))}`);
      if (over.length) bits.push(`${over.length} will finish over budget`);
      return { say: `${bits.join('; ')}.`, tone: losing.some((m) => m.cpi < 0.9) || over.length ? 'bad' : 'warn',
        next: 'Tap a job to see where its hours went.' };
    },

    budgets() {
      const data = replies['/api/budgets'];
      if (!data || !data.totals) return null;
      if (!(data.jobs || []).length) {
        return { say: 'No budgets in yet.', tone: 'warn',
          next: 'Bring in the BISpark Projects list and each job\'s staff expenditure.', act: ['Bring in data', 'bringin'] };
      }
      const t = data.totals;
      const bits = [];
      if (t.over) bits.push(`${t.over} job${t.over === 1 ? ' is' : 's are'} over budget`);
      if (t.short) bits.push(`${t.short} will run out at the current pace`);
      return {
        say: bits.length ? `${bits.join(', and ')}; ${Number(t.team_left_mm).toFixed(1)} man-months left across ${t.jobs} jobs.`
          : `All ${t.jobs} jobs are within budget, with ${Number(t.team_left_mm).toFixed(1)} man-months left.`,
        tone: t.over ? 'bad' : t.short ? 'warn' : 'ok',
        next: (data.todo || []).length ? dayFirstText(data.todo[0].text || data.todo[0]) : 'Tap a job to see who spent its hours.',
      };
    },

    reports() {
      const report = app().report;
      const totals = report && report.scorecard && report.scorecard.totals;
      if (!totals || !Object.keys(totals).length) return null;
      const ranked = Object.entries(totals).filter(([, v]) => v !== null).sort((a, b) => b[1] - a[1]);
      if (!ranked.length) return null;
      const [top, low] = [ranked[0], ranked[ranked.length - 1]];
      const label = report.period ? report.period.label : '';
      return {
        say: `${top[0]} leads with ${Math.round(top[1])} of 100${ranked.length > 1 ? `; ${low[0]} is lowest at ${Math.round(low[1])}` : ''}${label ? `, ${label.toLowerCase()}` : ''}.`,
        tone: 'ok',
        next: 'Show more, below, has how each score is made up; Each person\'s figures has the numbers behind it.',
      };
    },

    growth() {
      const data = replies['/api/growth'];
      if (!data || !data.people) return null;
      const n = data.people.length;
      const have = data.people.filter((p) => (p.goals || []).length).length;
      const first = (data.todo || [])[0];
      return {
        say: `${have} of ${n} people have goals for ${data.label || 'this quarter'}.`,
        tone: have === n ? 'ok' : have ? 'warn' : 'bad',
        next: first ? first.text : 'Development time is kept in everyone\'s week.',
      };
    },

    bringin() {
      const data = replies['/api/bring-in'];
      if (!data || !data.timesheets) return null;
      const ts = data.timesheets;
      if (!ts.rows) return { say: 'Nothing is in yet.', tone: 'bad', next: 'Choose the team\'s timesheet exports below to start.' };
      const age = ts.last_date ? daysBetween(ts.last_date, isoToday()) : null;
      const bits = [`Timesheets run to ${dayFirst(ts.last_date)}${age !== null ? ` (${age} day${age === 1 ? '' : 's'} ago)` : ''}`];
      const jobs = (data.projects || {}).jobs || 0;
      bits.push(jobs ? `${jobs} job budget${jobs === 1 ? '' : 's'} in` : 'no budgets yet');
      const tone = worst(age > 14 ? 'bad' : age > 7 ? 'warn' : 'ok', jobs ? 'ok' : 'warn');
      return { say: `${bits.join('; ')}.`, tone,
        next: age > 7 ? 'Bring in the latest exports below, or set up the nightly kit on Timesheets.' : 'Drop any new export below; each file is recognised by itself.' };
    },

    timesheets() {
      const data = (app().overview || {}).data_check || replies['/api/timesheets'];
      if (!data || data.rows === undefined) return null;
      if (!data.last_date) return { say: 'No timesheets yet.', tone: 'bad', next: 'Bring them in on Bring in data.', act: ['Bring in data', 'bringin'] };
      const age = daysBetween(data.last_date, isoToday());
      const unmatched = data.rows_not_matching_pattern || 0;
      return {
        say: `They run to ${dayFirst(data.last_date)}, ${age} day${age === 1 ? '' : 's'} ago, for ${Object.keys(data.per_engineer || {}).length} people.`,
        tone: worst(age > 14 ? 'bad' : age > 7 ? 'warn' : 'ok', unmatched ? 'warn' : 'ok'),
        next: unmatched ? `${unmatched} rows did not match anyone: check names on Team.` : 'Set up the nightly kit below once and they keep coming by themselves.',
      };
    },

    team() {
      const people = app().people;
      if (!people || !people.length) return null;
      const teams = new Set(people.filter((p) => p.team_name).map((p) => p.team_name));
      const noGrade = people.filter((p) => !p.grade).map((p) => p.name);
      const noTeam = people.filter((p) => !p.team_name).map((p) => p.name);
      const manager = people.some((p) => p.grade === 'manager');
      const gaps = [];
      if (noGrade.length) gaps.push(`${names(noGrade)} ${noGrade.length > 1 ? 'have' : 'has'} no grade`);
      if (noTeam.length) gaps.push(`${names(noTeam)} ${noTeam.length > 1 ? 'are' : 'is'} in no team`);
      return {
        say: `${people.length} people in ${teams.size} team${teams.size === 1 ? '' : 's'}${gaps.length ? `; ${gaps.join(' and ')}` : ', each with a grade'}.`,
        tone: gaps.length ? 'warn' : 'ok',
        next: manager ? 'Edit on a row changes a grade, a team or an email.'
          : 'Nobody is graded Manager yet: Edit on your own row, Grade Manager and This is me.',
      };
    },

    reference() {
      const ref = app().reference;
      if (!ref || !ref.project_types) return null;
      return {
        say: `${ref.project_types.length} project types, each with its own rules of credit.`,
        tone: 'ok',
        next: 'Every deliverable\'s progress and earned value follow these. They stay locked unless you unlock them.',
      };
    },
  };

  /* -- the answer card ------------------------------------------------------- */

  const viewEl = (view) => document.getElementById(`view-${view}`);
  // Projects keeps its header inside its list, so it hides with the list.
  const hostOf = (section) => section.querySelector(':scope > #projects-list') || section;

  function goTo(view) {
    window.switchView(view);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function drawAnswer(view) {
    const section = viewEl(view);
    const answerFor = ANSWER[view];
    if (!section || !answerFor) return;
    const host = hostOf(section);
    const head = host.querySelector(':scope > .view-head, :scope > .report-head');
    let card = host.querySelector(':scope > .answer');
    let answer = null;
    try { answer = answerFor(); } catch (_) { answer = null; }
    if (!answer) { if (card) card.hidden = true; return; }
    const sign = JSON.stringify(answer);
    if (card && card.dataset.sign === sign) { card.hidden = false; return; }
    const fresh = make('div', { class: 'answer', 'data-answer-tone': answer.tone || 'ok', role: 'status' },
      make('span', { class: 'answer-dot', 'aria-hidden': 'true' }),
      make('div', { class: 'answer-body' },
        make('p', { class: 'answer-say' }, answer.say),
        answer.next ? make('p', { class: 'answer-next' }, answer.next) : null),
      answer.act ? make('button', { type: 'button', class: 'btn btn-sm answer-act',
        onclick: () => (answer.act[1] === 'more' ? openMore(view) : goTo(answer.act[1])) }, answer.act[0]) : null);
    fresh.dataset.sign = sign;
    if (card) card.replaceWith(fresh);
    else if (head) head.after(fresh);
    else host.prepend(fresh);
  }

  /* -- the header: its question, and the pages that share the tab ------------- */

  function labelOf(view) {
    const tab = document.querySelector(`#tabs .tab[data-view="${view}"]`);
    return tab ? tab.textContent.replace(/\s+/g, ' ').trim() : view;
  }

  function dressHead(view) {
    const section = viewEl(view);
    if (!section) return;
    const head = hostOf(section).querySelector(':scope > .view-head, :scope > .report-head');
    if (!head || head.dataset.asked) return;
    head.dataset.asked = '1';
    const words = head.querySelector('p.muted');
    if (words && QUESTION[view]) {
      // The longer description stays as the question's tooltip.
      words.title = words.textContent.trim();
      words.textContent = QUESTION[view];
      words.classList.add('vh-question');
    }
    const group = groupOf(view);
    if (!group) return;
    const title = head.querySelector('h2');
    const pages = make('div', { class: 'vh-pages', role: 'tablist', 'aria-label': 'Pages on this tab' },
      ...group.map((v) => make('button', {
        type: 'button', role: 'tab', class: `vh-page${v === view ? ' is-on' : ''}`,
        'aria-selected': v === view ? 'true' : 'false', title: QUESTION[v] || null,
        onclick: () => { if (v !== view) goTo(v); } }, labelOf(v))));
    (words || title).after(pages);
  }

  /* -- Show more ----------------------------------------------------------------
   * Ahmed (9 Oct): the important details stay open; only the extras wait under
   * Show more. The blocks of a page are its own children, and the children of
   * the boxes the page draws into; extra(block) names the ones that fold away. */

  // A section's title: a heading, or a chart's caption.
  const HEADS = 'h3, h4, figcaption > b';
  /** A block's title: its first heading's own words. */
  function titleOf(block) {
    const found = block.matches(HEADS) ? block : block.querySelector(HEADS);
    if (!found) return '';
    const h = found.cloneNode(true);
    for (const extra of h.querySelectorAll('button, .info, .muted, small, span')) extra.remove();
    return h.textContent.replace(/\s+/g, ' ').trim();
  }
  const titled = (b, ...starts) => {
    const title = titleOf(b);
    return Boolean(title) && starts.some((start) => title.startsWith(start));
  };

  const FOLD = {
    overview: { extra: (b) => b.matches('#overview-cards, #hero-strip, #definitions-panel, .split')
      || titled(b, 'Workload by engineer', 'How is each person doing this year?') },
    checkins: { bodies: ['#checkins-body'], extra: (b) => b.matches('.cards')
      || titled(b, 'Leading the team', 'How much time do the leads', 'Each person', 'How have the last 8 weeks') },
    resourcing: { bodies: ['#resourcing-body'], extra: (b) => titled(b, 'People', 'Who is in which team',
      'Which teams carry which projects', 'Which team carries which job') },
    weekly: { bodies: ['#weekly-body'], extra: (b) => titled(b, 'People to ask for', 'Do we need to ask for more people') },
    projects: { bodies: ['#projects-list'], extra: (b) => b.matches('#projects-summary') },
    // Each report keeps its first three charts and tables; the rest are the detail.
    reports: { bodies: ['#report-body', '#report-body > div'], extra: (b, i, all) => !b.matches(TEXT)
      && all.filter((x) => !x.matches(TEXT)).indexOf(b) >= 3 },
    team: { bodies: ['#team-body'], extra: (b) => b.matches('.msg')
      || titled(b, 'Hours booked against hours available', 'How much of their hours') },
    timesheets: { extra: (b) => b.matches('#ts-cards')
      || titled(b, 'Where the hours went', 'What were the hours spent on', 'Import exports', 'Have an export file') },
  };
  const TEXT = '.report-title, h3, h4, p';

  /* -- every section asks the question it answers ------------------------------- */
  // A section's title, as it was, and the question it now asks. Each one is
  // matched by how the title starts, since some end with a date or a count.
  const ASK = {
    overview: [
      ['Start here', 'New here? Where do I start?'],
      ['This week with the team', 'Who needs help this week?'],
      ['Staffing ahead', 'Do we need more people soon?'],
      ['How the team is doing', 'Is the team busy, earning and on plan?'],
      ['Each person, by grade and team', 'How full is each person\'s timesheet?'],
      ['The team, month by month', 'How many hours did the team book each month?'],
      ['Workload by engineer', 'How is each person doing this year?'],
      ['Data check', 'Are the timesheets complete?'],
      ['Things to fix', 'Is anything wrong in the projects?'],
    ],
    planner: [
      ['Meetings', 'What meetings are coming, and who goes?'],
      ['Days off: leave and holidays', 'Who is off, and when?'],
    ],
    tasks: [
      ['Who is doing what, until when', 'Who is doing what, until when?'],
      ['Who is loaded, and who is not', 'Who has too much task work, and who too little?'],
    ],
    checkins: [
      ['Who is over, who has room: the next two weeks', 'Who is over, and who has room, in the next two weeks?'],
      ['What to do', 'What should I do about it?'],
      ['Leading the team', 'How much time do the leads give their people?'],
      ['Free hours, the next two weeks', 'Who has free hours in the next two weeks?'],
      ['Each person', 'How have the last 8 weeks been for each person?'],
      ['Everything to ask', 'What should I ask each person?'],
    ],
    resourcing: [
      ['What to do about it', 'What should change in the teams?'],
      ['Teams', 'How full is each team?'],
      ['Hours booked by team, month by month', 'How many hours did each team book each month?'],
      ['People', 'Who is in which team?'],
      ['Which teams carry which projects', 'Which team carries which job?'],
    ],
    weekly: [
      ['What to do this week', 'What should I do this week?'],
      ['Last week, person by person', 'How did last week go for each person?'],
      ['This week', 'What is due this week, and who can take more?'],
      ['People to ask for', 'Do we need to ask for more people?'],
      ['Notifications on your phone', 'Can my phone tell me when something needs me?'],
    ],
    projects: [
      ['Every project at a glance', 'How far along is each job, and is it earning?'],
      ['Projects by status', 'How many jobs are in each state?'],
    ],
    budgets: [
      ['Bring in your budgets from BISpark', 'How do I bring in the budgets?'],
    ],
    reports: [
      ['Weighted score', 'Who scores highest, out of 100?'],
      ['Top-weighted factors', 'What is each score made of?'],
      ['Ranking', 'Where does each person rank?'],
      ['How the score is made up', 'How is the score worked out?'],
      ['How the team is doing', 'Is the team busy, earning and on plan?'],
      ['Portfolio by status', 'How do the jobs add up by state?'],
      ['Project detail', 'How is each job doing?'],
    ],
    growth: [
      ['What to do', 'What should I do for the team\'s growth?'],
      ['KPIs by grade', 'How is each person scoring against their own grade?'],
      ['Goals and development time', 'What is each person working towards this quarter?'],
    ],
    bringin: [
      ['What the app holds now', 'What is in the app now?'],
      ['Keeping it up to date', 'How do I keep it up to date?'],
    ],
    timesheets: [
      ['Each person\'s months at a glance', 'How much of each month did each person book?'],
      ['Where the hours went', 'What were the hours spent on?'],
      ['Every night, on its own', 'How do the timesheets come in by themselves?'],
      ['Import exports', 'Have an export file to add by hand?'],
    ],
    team: [
      ['The team at a glance', 'How is each person doing?'],
      ['Hours booked against hours available', 'How much of their hours has each person booked?'],
    ],
    reference: [
      ['Project types', 'What kinds of job are there?'],
      ['Rules of credit', 'How is progress credited on each kind of job?'],
      ['Scorecard factors', 'What is the ranking built from?'],
    ],
  };

  /** Each section's title becomes the question it answers; the old title stays as its tooltip. */
  function ask(view) {
    const pairs = ASK[view];
    const section = viewEl(view);
    if (!pairs || !section) return;
    for (const h of section.querySelectorAll(HEADS)) {
      if (h.closest('.view-head, .report-head, .answer, .fold-more') || h.dataset.asked) continue;
      const text = Array.from(h.childNodes).find((n) => n.nodeType === 3 && n.textContent.trim());
      if (!text) continue;
      const was = text.textContent.trim();
      const pair = pairs.find(([start]) => was.startsWith(start));
      if (!pair) continue;
      h.dataset.asked = '1';
      h.title = h.title || was;
      text.textContent = `${pair[1]} `;
      h.classList.add('is-question');
    }
  }

  // The page's frame, never folded: its header, answer, page switches and the button itself.
  const FRAME = '.view-head, .report-head, .answer, .fold-more, .subtabs, .print-only, script, #project-detail';

  function blocksOf(view, rule) {
    const section = viewEl(view);
    const out = [];
    const bodies = rule.bodies || [];
    const visit = (node) => {
      for (const child of node.children) {
        if (child.matches(FRAME)) continue;
        if (bodies.some((sel) => child.matches(sel))) visit(child);
        else out.push(child);
      }
    };
    visit(section);
    return out;
  }

  function headingOf(block) {
    const found = block.matches('h3, h4') ? block : block.querySelector('h3, h4, summary b, .panel-head b, b');
    if (!found) return '';
    // Only the title's own words: not its "i" button or the line after it.
    const h = found.cloneNode(true);
    for (const extra of h.querySelectorAll('button, .info, .muted, small, span')) extra.remove();
    const text = h.textContent.replace(/\s+/g, ' ').trim();
    return text.length > 56 ? `${text.slice(0, 54).replace(/\s+\S*$/, '')}…` : text;
  }

  function fold(view) {
    const rule = FOLD[view];
    const section = viewEl(view);
    if (!rule || !section) return;
    const blocks = blocksOf(view, rule);
    const extras = [];
    blocks.forEach((b, i) => {
      let keep = true;
      try { keep = !rule.extra(b, i, blocks); } catch (_) { keep = true; }
      b.classList.toggle('fold-extra', !keep);
      if (!keep && !b.hidden && !b.matches('.print-only')) extras.push(b);
    });
    const host = hostOf(section);
    let more = host.querySelector(':scope > .fold-more');
    if (!extras.length) { if (more) more.remove(); return; }
    const open = section.classList.contains('show-all');
    const what = extras.map(headingOf).filter(Boolean);
    const label = open ? 'Show less' : 'Show more';
    const sign = `${label}|${what.join('|')}`;
    if (more && more.dataset.sign === sign && more === host.lastElementChild) return;
    const fresh = make('button', { type: 'button', class: 'fold-more', 'aria-expanded': open ? 'true' : 'false',
      onclick: () => toggle(view) },
    make('span', { class: 'fold-more-label' }, label),
    !open && what.length ? make('span', { class: 'fold-more-what' }, what.slice(0, 4).join(' · ') + (what.length > 4 ? ' …' : '')) : null);
    fresh.dataset.sign = sign;
    if (more) more.remove();
    host.append(fresh);
  }

  function toggle(view) {
    const section = viewEl(view);
    section.classList.toggle('show-all');
    fold(view);
    if (section.classList.contains('show-all')) {
      const first = section.querySelector('.fold-extra:not([hidden])');
      if (first) first.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function openMore(view) {
    const section = viewEl(view);
    if (section && !section.classList.contains('show-all')) toggle(view);
  }

  /* -- keeping it all up to date ------------------------------------------------ */

  const activeView = () => {
    const section = document.querySelector('main .view.is-active');
    return section ? section.id.replace(/^view-/, '') : '';
  };

  let queued = false;
  function later() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      const view = activeView();
      if (!view) return;
      dressHead(view);
      drawAnswer(view);
      ask(view);
      fold(view);
    });
  }

  /** The tab in the bar stays lit for every page that shares it. */
  function lightTab(view) {
    const head = headOf(view);
    for (const tab of $$('#tabs .tab')) tab.classList.toggle('is-active', tab.dataset.view === head);
  }

  function start() {
    wrapApi();
    for (const group of GROUPS) {
      for (const view of group.slice(1)) {
        const tab = document.querySelector(`#tabs .tab[data-view="${view}"]`);
        if (tab) tab.classList.add('in-group');
      }
    }
    for (const view of Object.keys(QUESTION)) dressHead(view);
    const switchTo = window.switchView;
    if (typeof switchTo === 'function') {
      window.switchView = function (view, ...rest) {
        const result = switchTo.call(this, view, ...rest);
        lightTab(view);
        // A page opens folded each time: the answer first, the rest on request.
        const section = viewEl(view);
        if (section) section.classList.remove('show-all');
        later();
        return result;
      };
    }
    const main = document.getElementById('main');
    if (main) new MutationObserver(later).observe(main, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  window.oneAnswer = { GROUPS, QUESTION, headOf, groupOf, openMore };
}());
