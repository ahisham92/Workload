/* Selecao+ — How to use.
 *
 * One guide for the manager (the "How to use" tab on index.html) and a short
 * one for engineers (the top of member.html). Each has a diagram drawn as
 * inline SVG: the first setup, done once, and the everyday routine after it.
 * Every box in a diagram, and every "Go" button, opens the place it names, so
 * someone who doesn't know where to go is taken there.
 *
 * The diagrams are drawn for the width they have: one column on a phone, up
 * to four side by side on a wide screen. Nothing here reads or writes data.
 * Elements are made with common.js's make.
 */
(function () {
  'use strict';

  /* -- what the guide says ---------------------------------------------- */

  // where: the tab, as its button reads. go: [view, planner subtab] for the
  // manager page, or the id of a panel on the engineer's page.
  const MANAGER = {
    intro: 'The app opens on three questions: plan the week, see how we\'re doing, or set up. Each keeps only its own tabs; Show tabs for, above the tabs, changes it. Every tab opens on its answer, each part of it is headed by the question it answers, and only the extras sit under Show more at the bottom, and some tabs hold two pages (Projects and Budgets, for one): switch between them in the tab\'s header. New here? Start with Bring in data, then do the rest of the first setup once, top to bottom. After that the everyday routine '
      + 'below is all you need. Tap any box to go there.',
    setup: [
      { title: 'Bring in your files', do: 'Timesheets and budgets together, in one place',
        where: 'Bring in data', go: ['bringin'] },
      { title: 'Check your team', do: 'Grade and team for each person. On your own row: Grade Manager, This is me Yes',
        where: 'Team', go: ['team'] },
      { title: 'Give each engineer a sign-in', do: 'Give a sign-in on their row, so they get their own My day page',
        where: 'Team', go: ['team'] },
      { title: 'Days off: leave and holidays', do: 'Pick the holiday country once; add a day off for anyone on leave',
        where: 'Planner › Today', go: ['planner', 'today'] },
      { title: 'Meetings', do: 'Put in client, other trade and internal meetings once, with who goes',
        where: 'Planner › Today', go: ['planner', 'today'] },
      { title: 'Submissions and drawings', do: 'Confirm the due dates the timesheets suggest',
        where: 'Planner › Submissions', go: ['planner', 'submissions'] },
      { title: 'Budgets', do: 'Map people from other units once; check each job\'s share',
        where: 'Projects › Budgets', go: ['budgets'] },
      { title: 'Keep it coming by itself', do: 'Set up the BISpark kit once; it sends the team\'s rows every 6 hours',
        where: 'Bring in data › Timesheets', go: ['timesheets'] },
      { title: 'Notifications and goals', do: 'Turn on phone alerts; set each person\'s goals for the quarter',
        where: 'Weekly report, Reports › Goals and growth', go: ['weekly'] },
    ],
    routine: [
      { lane: 'Every day', note: 'about 10 minutes, on the phone', steps: [
        { title: 'Look at Who needs help', do: 'The answer at the top says who needs a lighter week and who has room; What to do lists the rest', where: 'Who needs help', go: ['checkins'] },
        { title: 'See each person\'s day', do: 'The app lays out today from their real pace', where: 'Planner › Today', go: ['planner', 'today'] },
        { title: 'Answer Stuck and Need help', do: 'Tap Seen, then sort it out with them; the full list is under Show more', where: 'Who needs help', go: ['checkins'] },
      ] },
      { lane: 'Every week', note: 'Sunday to Thursday', steps: [
        { title: 'Sunday: set the week', do: 'Look at what is due in the next two weeks', where: 'Planner › Submissions', go: ['planner', 'submissions'] },
        { title: 'Sunday: copy of the plan', do: 'The app keeps a copy of the week\'s plan by itself; copy again after big changes', where: 'Planner › Plan vs actual', go: ['planner', 'review'] },
        { title: 'Thursday: kept and slipped', do: 'Plan against tasks done and timesheets; one tap on why each slip happened', where: 'Planner › Plan vs actual', go: ['planner', 'review'] },
        { title: 'Thursday: look back', do: 'Is the team on track? Overview answers it; Weekly report\'s Show more has how last week went', where: 'Overview, Weekly report', go: ['overview'] },
        { title: 'Ask for people early', do: 'Staffing ahead says how many, from when, for how long', where: 'Planner › People needed', go: ['planner', 'people'] },
      ] },
      { lane: 'When something comes up', note: 'as it happens, in any order', chain: false, steps: [
        { title: 'A request lands', do: 'Quick add it; "What does it push?" shows what slips and the cost first', where: 'Planner › Today', go: ['planner', 'today'] },
        { title: 'Try a what-if', do: 'New work or a handover, kept to compare before you decide', where: 'Planner › Move work', go: ['planner', 'handovers'] },
        { title: 'A new meeting', do: 'Add it once with who goes; it comes off their time', where: 'Planner › Today', go: ['planner', 'today'] },
        { title: 'Month or quarter end', do: 'Budget against spend, KPIs by grade, reports', where: 'Projects › Budgets, Reports › Goals and growth', go: ['budgets'] },
      ] },
    ],
    find: [
      ['What does a % or number mean?', 'Tap the i beside it, on any tab', ['overview']],
      ['There was more here before', 'Show more, at the bottom of the tab', ['overview']],
      ['Who is free next week?', 'Who needs help', ['checkins']],
      ['What is each person doing today?', 'Planner › Today', ['planner', 'today']],
      ['Who is stuck or needs help?', 'Who needs help', ['checkins']],
      ['Which jobs need attention?', 'Projects', ['projects']],
      ['Is a job over its budget?', 'Projects › Budgets', ['budgets']],
      ['What is due, and what came back with A, B or C?', 'Planner › Submissions', ['planner', 'submissions']],
      ['Record a submission, its return and the next revision', 'Planner › Submissions, or the project on Projects', ['planner', 'submissions']],
      ['Do we need more people?', 'Planner › People needed, or Who needs help › Team staffing', ['planner', 'people']],
      ['Move work from one person to another', 'Planner › Move work', ['planner', 'handovers']],
      ['How did last week go?', 'Weekly report › Show more', ['weekly']],
      ['Did we keep to the plan?', 'Planner › Plan vs actual', ['planner', 'review']],
      ['How is each person scoring?', 'Reports', ['reports']],
      ['How is each person growing?', 'Reports › Goals and growth', ['growth']],
      ['Have the timesheets come in?', 'Bring in data, or Bring in data › Timesheets', ['bringin']],
      ['Bring in a new export', 'Bring in data', ['bringin']],
      ['A project\'s hours and progress', 'Projects', ['projects']],
      ['Change someone\'s grade or team', 'Team › Edit on their row', ['team']],
      ['Tasks: who has what, until when', 'Planner › Tasks', ['tasks']],
      ['Project types and rules of credit', 'Team › Scoring rules', ['reference']],
    ],
  };

  const MEMBER = {
    intro: 'Your page has your day, your timesheet and your leave. Set it up once, then it takes a '
      + 'minute a day. Tap any box to go there.',
    setup: [
      { title: 'Keep it on your phone', do: 'Share › Add to Home Screen (iPhone) or Install (Android)', where: 'Phone' },
      { title: 'Turn on notifications', do: 'So you hear about late work and your week', where: 'Below', go: 'member-push' },
      { title: 'Say when you are off', do: 'I\'m off on: your leave, so nobody plans you in', where: 'My day', go: 'myoff' },
      { title: 'Add your meetings', do: 'They come off your free time in the plan', where: 'My day', go: 'mymeetings' },
    ],
    routine: [
      { lane: 'Every day', note: 'about a minute', steps: [
        { title: 'Open My day', do: 'Today\'s work in order, with due dates', where: 'My day', go: 'myday' },
        { title: 'Done, Stuck or Need help', do: 'One tap on each task; your lead sees it', where: 'My day', go: 'myday' },
      ] },
      { lane: 'End of the week', note: 'Thursday', steps: [
        { title: 'My week', do: 'Planned, done and booked; one tap on why anything slipped', where: 'My week', go: 'myweek' },
        { title: 'Ready timesheet', do: 'Your hours by job and phase, ready to copy', where: 'My day', go: 'mytimesheet' },
        { title: 'Copy into BISpark', do: 'Copy all, paste line by line; nothing is sent for you', where: 'BISpark' },
      ] },
    ],
  };

  /* -- small helpers ------------------------------------------------------ */

  const SVG = 'http://www.w3.org/2000/svg';

  function svg(tag, attrs, ...children) {
    const node = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    for (const child of children) if (child) node.append(child);
    return node;
  }

  /** Words into lines of at most `max` characters, never more than `most` lines. */
  function wrap(text, max, most) {
    const lines = [];
    let line = '';
    for (const word of text.split(/\s+/)) {
      if (line && (line + ' ' + word).length > max) { lines.push(line); line = word; } else {
        line = line ? `${line} ${word}` : word;
      }
    }
    if (line) lines.push(line);
    if (lines.length > most) {
      lines.length = most;
      lines[most - 1] = `${lines[most - 1].replace(/[\s,.;]+\S*$/, '')}…`;
    }
    return lines;
  }

  /* -- going where a step says -------------------------------------------- */

  function goManager(target) {
    if (!target || typeof window.switchView !== 'function') return;
    const [view, sub] = target;
    if (view === 'planner' && sub && window.planner && window.planner.open) window.planner.open(sub);
    else window.switchView(view);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function goMember(id) {
    const spot = id && document.getElementById(id);
    if (!spot || spot.hidden) return;     // not on this page (yet): nothing to show
    spot.scrollIntoView({ behavior: 'smooth', block: 'start' });
    spot.classList.remove('hg-flash');
    void spot.offsetWidth;      // restart the highlight
    spot.classList.add('hg-flash');
  }

  /* -- the diagram ---------------------------------------------------------- */

  /**
   * Boxes in reading order, joined by arrows. A row that ends turns down and
   * back to the start of the next row, so the path never needs explaining.
   */
  function flow(steps, { width, numbered, go, label, chain = true }) {
    const gap = 26;
    const rowGap = 34;
    const cols = Math.max(1, Math.min(4, steps.length, Math.floor((width + gap) / (220 + gap))));
    const boxW = Math.floor((width - gap * (cols - 1)) / cols);
    const chars = Math.max(18, Math.floor((boxW - (numbered ? 46 : 22)) / 7));
    const laid = steps.map((s) => ({ ...s, lines: wrap(s.do, chars, 3) }));
    const boxH = 58 + 16 * Math.max(...laid.map((s) => s.lines.length));
    const rows = Math.ceil(steps.length / cols);
    const height = rows * boxH + (rows - 1) * rowGap + 4;

    const root = svg('svg', { class: 'hg-flow', viewBox: `0 0 ${width} ${height}`,
      width: String(width), height: String(height), role: 'img', 'aria-label': label });
    const defs = svg('defs');
    const marker = svg('marker', { id: `hg-arrow-${label.replace(/\W+/g, '')}`, viewBox: '0 0 10 10',
      refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse' },
    svg('path', { d: 'M0 0L10 5L0 10z', class: 'hg-arrowhead' }));
    defs.append(marker);
    root.append(defs);
    const arrow = `url(#${marker.id})`;

    const at = (i) => ({ x: (i % cols) * (boxW + gap), y: Math.floor(i / cols) * (boxH + rowGap) + 2 });

    for (let i = 0; chain && i < laid.length - 1; i += 1) {
      const a = at(i);
      const b = at(i + 1);
      let d;
      if (b.y === a.y) {
        d = `M${a.x + boxW} ${a.y + boxH / 2}H${b.x - 2}`;
      } else {
        const mid = a.y + boxH + rowGap / 2;
        d = `M${a.x + boxW / 2} ${a.y + boxH}V${mid}H${b.x + boxW / 2}V${b.y - 2}`;
      }
      root.append(svg('path', { d, class: 'hg-link', 'marker-end': arrow }));
    }

    laid.forEach((step, i) => {
      const { x, y } = at(i);
      const target = step.go;
      const node = svg('g', { class: `hg-node${target ? ' hg-can-go' : ''}`, transform: `translate(${x} ${y})` });
      const text = `${numbered ? `Step ${i + 1}: ` : ''}${step.title}. ${step.do}. Where: ${step.where}.`;
      node.append(svg('title', {}, document.createTextNode(text)));
      node.append(svg('rect', { width: String(boxW), height: String(boxH), rx: '10', class: 'hg-box' }));
      let left = 12;
      if (numbered) {
        node.append(svg('circle', { cx: '24', cy: '24', r: '13', class: 'hg-num' }));
        node.append(svg('text', { x: '24', y: '28.5', 'text-anchor': 'middle', class: 'hg-num-text' },
          document.createTextNode(String(i + 1))));
        left = 46;
      }
      node.append(svg('text', { x: String(left), y: '29', class: 'hg-title' },
        document.createTextNode(wrap(step.title, Math.floor((boxW - left - 10) / 7.6), 1)[0])));
      step.lines.forEach((line, n) => {
        node.append(svg('text', { x: String(left), y: String(48 + n * 16), class: 'hg-do' },
          document.createTextNode(line)));
      });
      node.append(svg('text', { x: String(boxW - 10), y: String(boxH - 9), 'text-anchor': 'end', class: 'hg-where' },
        document.createTextNode(target ? `${step.where} ›` : step.where)));
      if (target) {
        node.setAttribute('tabindex', '0');
        node.setAttribute('role', 'link');
        node.setAttribute('aria-label', text);
        node.addEventListener('click', () => go(target));
        node.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(target); }
        });
      }
      root.append(node);
    });
    return root;
  }

  /* -- the page ------------------------------------------------------------ */

  function render(host, guide, go, { compact } = {}) {
    const width = Math.max(260, Math.floor(host.clientWidth || 0) - 2);
    if (!host.clientWidth) return false;     // not on screen yet; drawn when shown

    const setup = make('section', { class: 'panel hg-panel' },
      make('div', { class: 'hg-head' },
        make('h3', {}, compact ? 'First time' : 'First setup, once'),
        make('p', { class: 'muted' }, compact
          ? 'Four things, a couple of minutes. Follow the arrows.'
          : 'This shows the order to set Selecao+ up. Start at 1 and follow the arrows; each step '
            + 'needs what came before it. Tap a box to go there.')));
    const setupHost = make('div', { class: 'hg-diagram' });
    setup.append(setupHost);

    const routine = make('section', { class: 'panel hg-panel' },
      make('div', { class: 'hg-head' },
        make('h3', {}, compact ? 'After that' : 'After setup, every day and week'),
        make('p', { class: 'muted' }, compact
          ? 'What to do each day and at the end of the week.'
          : 'This shows the routine once you are set up. Follow the arrows in the first row every '
            + 'day and the second once a week; the last row is for whenever it happens.')));
    const lanes = guide.routine.map((lane) => {
      const box = make('div', { class: 'hg-diagram' });
      routine.append(make('div', { class: 'hg-lane' },
        make('div', { class: 'hg-lane-name' }, make('b', {}, lane.lane), make('span', { class: 'muted' }, ` · ${lane.note}`)),
        box));
      return [box, lane];
    });

    const parts = [make('p', { class: 'hg-intro' }, guide.intro), setup, routine];
    if (guide.find) {
      parts.push(make('section', { class: 'panel hg-panel' },
        make('div', { class: 'hg-head' },
          make('h3', {}, 'Where do I find…'),
          make('p', { class: 'muted' }, 'Pick your question; Go takes you to the answer.')),
        make('ul', { class: 'hg-find' }, ...guide.find.map(([question, where, target]) =>
          make('li', {},
            make('span', {}, question, make('span', { class: 'muted hg-find-where' }, where)),
            make('button', { class: 'btn btn-sm', type: 'button', onclick: () => go(target) }, 'Go'))))));
    }
    host.replaceChildren(...parts);

    const inner = (box) => Math.max(240, Math.floor(box.clientWidth || width));
    setupHost.append(flow(guide.setup, { width: inner(setupHost), numbered: true, go, label: 'First setup' }));
    for (const [box, lane] of lanes) {
      box.append(flow(lane.steps, { width: inner(box), numbered: false, go, label: lane.lane,
        chain: lane.chain !== false }));
    }
    host.dataset.drawnAt = String(width);
    return true;
  }

  function keepFitted(host, draw) {
    let timer = null;
    window.addEventListener('resize', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const width = String(Math.max(260, Math.floor(host.clientWidth || 0) - 2));
        if (host.clientWidth && host.dataset.drawnAt !== width) draw();
      }, 150);
    });
  }

  /* -- wiring -------------------------------------------------------------- */

  const managerHost = document.getElementById('guide-body');
  if (managerHost) {
    const draw = () => render(managerHost, MANAGER, goManager);
    window.guide = { load: () => requestAnimationFrame(draw) };
    keepFitted(managerHost, draw);
  }

  const memberHost = document.getElementById('member-guide');
  if (memberHost) {
    const holder = memberHost.closest('details');
    const draw = () => render(memberHost, MEMBER, goMember, { compact: true });
    if (holder) {
      holder.addEventListener('toggle', () => {
        if (!holder.open) return;
        draw();
        try { localStorage.setItem('selecao-guide-seen', '1'); } catch { /* private window */ }
      });
      // Open by itself the first time someone comes to the page.
      let seen = false;
      try { seen = localStorage.getItem('selecao-guide-seen') === '1'; } catch { seen = true; }
      if (!seen) holder.open = true;
    } else draw();
    keepFitted(memberHost, draw);
  }
}());
