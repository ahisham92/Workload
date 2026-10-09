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

  /* -- rows that fill the width ------------------------------------------ */
  // A grid of cards fills its row: as many columns as fit, then balanced so
  // the rows hold the same number (six cards are three and three, not five
  // and one), and a short last row stretches its last card to the edge. So
  // no grid leaves a blank stretch of panel beside it.
  const GRIDS = { 'pc-grid': 232, 'eng-grid': 320, 'day-grid': 280, 'ci-grid': 320,
    'gr-people': 300, 'unit-grid': 280, 'cards-3': 230, findings: 300, 'hero-strip': 280,
    'load-grid': 260, 'report-grid': 340, 'bi-kinds': 220, ideas: 280, 'gr-grades': 420,
    'bu-detail-grid': 320 };
  const SELECTOR = Object.keys(GRIDS).map((c) => `.${c}`).join(',');

  function balance(grid) {
    const key = Object.keys(GRIDS).find((c) => grid.classList.contains(c));
    const items = Array.from(grid.children).filter((n) => !n.hidden);
    const width = grid.clientWidth;
    if (!key || !items.length || !width) return;
    // A row that scrolls sideways (the people cards on a phone) keeps its own layout.
    if (getComputedStyle(grid).gridAutoFlow.startsWith('column')) {
      grid.style.gridTemplateColumns = '';
      items.forEach((item) => { item.style.gridColumn = ''; });
      return;
    }
    const gap = parseFloat(getComputedStyle(grid).columnGap) || 12;
    const fit = Math.max(1, Math.floor((width + gap) / (GRIDS[key] + gap)));
    const rows = Math.ceil(items.length / fit);
    const cols = Math.ceil(items.length / rows);
    grid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
    const short = cols * rows - items.length;
    items.forEach((item, i) => {
      item.style.gridColumn = short && i === items.length - 1 ? `span ${short + 1}` : '';
    });
  }

  const sized = new ResizeObserver((entries) => entries.forEach((e) => balance(e.target)));
  const seen = new WeakSet();
  let queued = false;
  function findGrids() {
    queued = false;
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
    findGrids();
  }

  function start() {
    dress();
    watchGrids();
    const switchTo = window.switchView;
    if (typeof switchTo === 'function') {
      window.switchView = function (view, ...rest) {
        const result = switchTo.call(this, view, ...rest);
        document.body.dataset.tone = toneOf(view);
        return result;
      };
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  window.look = { toneOf, dress, balance };
}());
