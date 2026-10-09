/* Selecao+ — the look: each tab dressed in its path's colour.
 *
 * The four paths (paths.js) each get a colour of their own, and every tab
 * takes the colour of the path it belongs to: its button, its header and its
 * panels. Each tab's header gets the tab's own icon and the path's name above
 * the title, so the tabs no longer all look alike and it is clear at a glance
 * which part of the app one is in. The page's glow follows the tab on show.
 *
 * Nothing here reads or writes data; look.css draws everything. Built on
 * common.js's make and $$, and app.js's switchView.
 */
(function () {
  'use strict';

  // The path each tab belongs to. A tab in two paths takes the one it is
  // mostly used for.
  const TONE = {
    planner: 'plan', checkins: 'plan', resourcing: 'plan', team: 'plan',
    overview: 'workload', weekly: 'workload', tasks: 'workload', projects: 'workload',
    timesheets: 'workload',
    reports: 'results', budgets: 'results', growth: 'results',
    bringin: 'setup', reference: 'setup', guide: 'setup', admin: 'setup', paths: 'setup',
  };
  const NAME = {
    plan: 'Plan people', workload: 'See the workload', results: 'Read the results',
    setup: 'Set up and bring in data',
  };
  const toneOf = (view) => TONE[view] || 'workload';

  // The opening page has no tab of its own: a compass.
  const COMPASS = '<svg class="tab-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/></svg>';

  function iconFor(view) {
    const tab = document.querySelector(`#tabs .tab[data-view="${view}"] .tab-icon`);
    if (tab) return tab.cloneNode(true);
    const holder = make('span');
    holder.innerHTML = COMPASS;
    return holder.firstChild;
  }

  /** A header with the tab's icon and its path's name above the title. */
  function dressHead(head, view) {
    if (!head || head.dataset.dressed) return;
    const title = head.querySelector('h2');
    if (!title) return;
    head.dataset.dressed = '1';
    const tone = toneOf(view);
    head.prepend(make('span', { class: 'vh-icon', 'aria-hidden': 'true' }, iconFor(view)));
    title.before(make('span', { class: 'vh-eyebrow' },
      view === 'paths' ? 'Start' : NAME[tone]));
  }

  function dress() {
    for (const tab of $$('#tabs .tab')) tab.dataset.tone = toneOf(tab.dataset.view);
    for (const section of $$('main .view')) {
      const view = section.id.replace(/^view-/, '');
      section.dataset.tone = toneOf(view);
      dressHead(section.querySelector('.view-head, .report-head'), view);
    }
    const active = document.querySelector('main .view.is-active');
    document.body.dataset.tone = toneOf(active ? active.id.replace(/^view-/, '') : 'overview');
  }

  /* -- cards as wide as they need, no wider ------------------------------ */
  // Ahmed (9 Oct): boxes and cards stretched across the whole screen with
  // little in them. So a grid of cards keeps each card at its own width, at
  // most four to a row with each row centred (six are four and two), and the
  // panel around it is only as wide as its cards, centred on the page: the
  // tab's colour shows either side. On a phone a card takes the screen's
  // width.
  const GRIDS = { 'pc-grid': 272, 'eng-grid': 340, 'day-grid': 320, 'ci-grid': 320,
    'gr-people': 300, 'unit-grid': 300, 'cards-3': 300, findings: 300, 'hero-strip': 300,
    'load-grid': 280, 'bi-kinds': 300, ideas: 300 };
  const SELECTOR = Object.keys(GRIDS).map((c) => `.${c}`).join(',');
  // What keeps a box at full width: things that are drawn to fill it.
  const WIDE = 'table, canvas, svg:not(.tab-icon), .chart, .figure, .bars, textarea, '
    + 'input[type="text"], input[type="search"], input[type="file"], .subtabs, '
    + '.report-grid, .gr-grades, .bu-detail-grid';

  const inGrid = (node) => Boolean(node.closest(SELECTOR));
  const onGridParent = (panel) => /grid/.test(getComputedStyle(panel.parentElement).display);

  /** A box only as wide as what it holds, when nothing in it is drawn to fill it. */
  function fit(panel) {
    const wide = Array.from(panel.querySelectorAll(WIDE)).some((n) => !inGrid(n));
    panel.classList.toggle('fits', !wide && !onGridParent(panel));
  }

  /** Cards at their own width, at most four to a row, each row centred. */
  function balance(grid) {
    const key = Object.keys(GRIDS).find((c) => grid.classList.contains(c));
    if (!key) return;
    // A row that scrolls sideways (the people cards on a phone) keeps its own layout.
    const carousel = getComputedStyle(grid).gridAutoFlow.startsWith('column');
    grid.classList.toggle('card-row', !carousel);
    grid.style.setProperty('--card-w', `${GRIDS[key]}px`);
  }

  const sized = new ResizeObserver((entries) => entries.forEach((e) => balance(e.target)));
  const seen = new WeakSet();
  let queued = false;
  /* -- boxes no taller than what they hold ------------------------------- */
  // A panel with nothing in it yet ("No meetings put in yet.") shrinks to a
  // slim bar: its title, its button and the one line saying it is empty. The
  // longer description waits, as the title's tooltip, until there is
  // something to describe.
  const EMPTY = /\b(no|none)\b[^.]*\byet\b|^nothing\b|not set up yet/i;
  const CONTENT = 'table, svg:not(.tab-icon), canvas, img, li, input, select, textarea, .card, .pc, .eng, details';

  function slim(panel) {
    const notes = $$('.empty, p.muted, p', panel).filter((p) => EMPTY.test(p.textContent.trim()));
    const busy = Array.from(panel.querySelectorAll(CONTENT))
      .some((node) => !node.closest('button, .panel-head, .legend'));
    // Only a panel made of a title, a line or two and a note: not one whose
    // cards each say they are empty.
    const plain = Array.from(panel.children).every((child) =>
      child.matches('h3, p, .panel-head, .empty, .btn, .legend')
      || (child.children.length <= 1 && notes.some((n) => child.contains(n))));
    // Beside another box (Meetings next to Away) it keeps its words: the pair is one height.
    const paired = panel.parentElement && panel.parentElement.classList.contains('panel-pair');
    const on = notes.length === 1 && plain && !busy && !paired;
    panel.classList.toggle('is-slim', on);
    const title = panel.querySelector('h3');
    for (const p of $$('p.muted', panel)) {
      const note = notes.includes(p);
      p.classList.toggle('slim-note', on && note);
      p.classList.toggle('slim-hide', on && !note);
      if (on && !note && title && !title.title) title.title = p.textContent.trim();
    }
    for (const e of $$('.empty', panel)) e.classList.toggle('slim-note', on);
  }

  function findGrids() {
    queued = false;
    for (const panel of $$('main .panel')) { slim(panel); fit(panel); }
    for (const grid of $$(SELECTOR)) {
      if (!seen.has(grid)) { seen.add(grid); sized.observe(grid); }
      balance(grid);
    }
  }
  function watchGrids() {
    const main = document.getElementById('main');
    if (!main) return;
    new MutationObserver(() => {
      if (!queued) { queued = true; requestAnimationFrame(findGrids); }
    }).observe(main, { childList: true, subtree: true });
    // A wider window has room for more cards in a row.
    new ResizeObserver(() => {
      if (!queued) { queued = true; requestAnimationFrame(findGrids); }
    }).observe(main);
    findGrids();
  }

  /* -- the tab bar's gliding pill ---------------------------------------- */
  const glider = make('span', { class: 'tab-glider', 'aria-hidden': 'true' });
  function glide() {
    const nav = document.getElementById('tabs');
    if (!nav || nav.hidden) return;
    if (!glider.isConnected) { nav.prepend(glider); nav.classList.add('has-glider'); }
    const tab = nav.querySelector('.tab.is-active');
    if (!tab || !tab.offsetWidth) { glider.classList.remove('is-on'); return; }
    glider.style.width = `${tab.offsetWidth}px`;
    glider.style.transform = `translateX(${tab.offsetLeft}px)`;
    glider.style.top = `${tab.offsetTop}px`;
    glider.classList.add('is-on');
    const left = tab.offsetLeft - nav.scrollLeft;
    if (left < 0 || left + tab.offsetWidth > nav.clientWidth) {
      nav.scrollTo({ left: tab.offsetLeft - nav.clientWidth / 2 + tab.offsetWidth / 2 });
    }
  }
  function watchTabs() {
    const nav = document.getElementById('tabs');
    if (!nav) return;
    // Paths reorder and hide tabs; the bar shows once signed in.
    new MutationObserver((records) => {
      if (records.some((r) => r.target !== glider)) requestAnimationFrame(glide);
    }).observe(nav,
      { attributes: true, subtree: true, attributeFilter: ['class', 'style', 'hidden'] });
    new ResizeObserver(() => glide()).observe(nav);
    glide();
  }

  function start() {
    dress();
    watchTabs();
    watchGrids();
    const switchTo = window.switchView;
    if (typeof switchTo === 'function') {
      window.switchView = function (view, ...rest) {
        const result = switchTo.call(this, view, ...rest);
        document.body.dataset.tone = toneOf(view);
        requestAnimationFrame(findGrids);
        requestAnimationFrame(glide);
        return result;
      };
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  window.look = { toneOf, dress, balance };
}());
