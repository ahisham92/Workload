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

  function start() {
    dress();
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

  window.look = { toneOf, dress };
}());
