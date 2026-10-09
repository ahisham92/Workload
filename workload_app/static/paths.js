/* Selecao+ — paths: what do you want to do?
 *
 * Sixteen tabs are a wall to somebody opening the app. So it opens on four
 * paths, by what the person came to do: plan people, see the workload, read
 * the results, or set up and bring data in. Choosing one leads to its first
 * tab and keeps only that path's tabs in the bar (and in the phone's bottom
 * bar); "Everything" brings them all back. The path chosen is kept on this
 * device, and opening the app again offers it first.
 *
 * Nothing here reads or writes data. Built on common.js's make and $, and
 * app.js's switchView and state. pocket.js puts a path's tabs on the phone's
 * bottom bar first.
 */
(function () {
  'use strict';

  const PATHS = [
    { key: 'plan', title: 'Plan people', icon: '⇄',
      say: 'Who does what today and this week, who has room, who needs help, and moving work between people.',
      tabs: ['planner', 'checkins', 'tasks', 'resourcing', 'team'] },
    { key: 'workload', title: 'See the workload', icon: '▤',
      say: 'How busy the team is, what is due, the projects, and how each week went.',
      tabs: ['overview', 'weekly', 'tasks', 'projects', 'timesheets'] },
    { key: 'results', title: 'Read the results', icon: '%',
      say: 'The numbers at the end: budgets, efficiency, KPIs by grade and each person\'s growth.',
      tabs: ['reports', 'budgets', 'growth', 'projects', 'overview'] },
    { key: 'setup', title: 'Set up and bring in data', icon: '⇪',
      say: 'Bring in the files, set grades and teams, the nightly kit, and how to use the app.',
      tabs: ['bringin', 'team', 'timesheets', 'reference'] },
  ];
  // Always in the bar, whichever path: help, and the administrator's tab.
  const ALWAYS = ['guide', 'admin'];
  const KEY = 'selecao.path';
  const SKIP = 'selecao.path.skipWelcome';

  const read = (key) => { try { return localStorage.getItem(key) || ''; } catch (_) { return ''; } };
  const write = (key, value) => {
    try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch (_) { /* nothing kept */ }
  };
  const byKey = (key) => PATHS.find((p) => p.key === key) || null;

  let current = byKey(read(KEY));

  /* -- the bar of paths, above the tabs -------------------------------------- */

  const bar = make('div', { class: 'path-bar', id: 'path-bar', role: 'toolbar',
    'aria-label': 'Paths', hidden: true });

  function drawBar() {
    bar.replaceChildren(
      make('span', { class: 'path-bar-label' }, 'Show'),
      ...[{ key: '', title: 'Everything' }, ...PATHS].map((p) => make('button', {
        type: 'button', class: `path-chip${(current ? current.key : '') === p.key ? ' is-on' : ''}`,
        'data-path': p.key || null, onclick: () => choose(p.key, false) }, p.key ? p.title : 'Everything')),
      make('button', { type: 'button', class: 'path-chip path-chip-ghost', onclick: welcome },
        'Paths'));
    const on = bar.querySelector('.path-chip.is-on');
    if (on && !bar.hidden) on.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  /** Only the path's tabs in the bar; the phone's bar follows by itself. */
  function filterTabs() {
    const keep = current ? new Set([...current.tabs, ...ALWAYS]) : null;
    for (const tab of document.querySelectorAll('#tabs .tab')) {
      tab.classList.toggle('off-path', Boolean(keep) && !keep.has(tab.dataset.view));
    }
    // The tabs follow the path's own order, so it reads top-down.
    const nav = $('#tabs');
    if (nav) {
      const order = current ? current.tabs : [];
      for (const tab of nav.querySelectorAll('.tab')) {
        const at = order.indexOf(tab.dataset.view);
        tab.style.order = at < 0 ? '' : String(at - 100);
      }
    }
    drawBar();
  }

  function choose(key, go = true) {
    current = byKey(key);
    write(KEY, current ? current.key : '');
    filterTabs();
    const active = document.querySelector('#tabs .tab.is-active');
    const stranded = !active || active.classList.contains('off-path')
      || $('#view-paths').classList.contains('is-active');
    if (go || stranded) {
      window.switchView(current ? current.tabs[0] : 'overview');
      window.scrollTo({ top: 0 });
    }
  }

  /* -- the welcome: four paths, on opening ------------------------------------ */

  function isNew() {
    // app.js's state is a global of its own, not a property of window.
    const status = (typeof state !== 'undefined' && state.status) || {};
    return !status.timesheet_rows;
  }

  function card(path, hint) {
    const icon = document.querySelector(`#tabs .tab[data-view="${path.tabs[0]}"] .tab-icon`);
    return make('button', { type: 'button', class: `path-card${current && current.key === path.key ? ' is-last' : ''}`,
      'data-path': path.key, onclick: () => choose(path.key) },
    make('span', { class: 'path-card-icon', 'aria-hidden': 'true' },
      icon ? icon.cloneNode(true) : path.icon),
    make('span', { class: 'path-card-title' }, path.title),
    hint ? make('span', { class: 'pill pill-info' }, hint) : null,
    make('span', { class: 'path-card-say' }, path.say),
    make('span', { class: 'path-card-tabs' }, path.tabs.map(labelOf).join(' · ')));
  }

  function labelOf(view) {
    const tab = document.querySelector(`#tabs .tab[data-view="${view}"]`);
    return tab ? tab.textContent.replace(/\s+/g, ' ').trim() : view;
  }

  function welcome() {
    const host = $('#paths-body');
    if (!host) return;
    const skip = make('input', { type: 'checkbox', id: 'paths-skip' });
    skip.checked = read(SKIP) === '1';
    skip.addEventListener('change', () => write(SKIP, skip.checked ? '1' : ''));
    setChildren(host,
      current ? make('button', { type: 'button', class: 'btn btn-primary path-carry',
        onclick: () => choose(current.key) }, `Carry on: ${current.title}`) : null,
      make('div', { class: 'path-cards' }, ...PATHS.map((p) => card(p,
        p.key === 'setup' && isNew() ? 'Start here if you are new'
          : current && current.key === p.key ? 'Last time' : ''))),
      make('div', { class: 'path-foot' },
        make('button', { type: 'button', class: 'btn btn-ghost', onclick: () => choose('') },
          'Show everything'),
        make('label', { class: 'path-skip', for: 'paths-skip' }, skip,
          ' Next time, open straight on my last path')));
    window.switchView('paths');
    window.scrollTo({ top: 0 });
  }

  /** On opening: the paths, unless a link names a view or they asked to skip them. */
  function opened() {
    filterTabs();
    if (window.location.hash) return;
    if (current && read(SKIP) === '1') { window.switchView(current.tabs[0]); return; }
    welcome();
  }

  function start() {
    const nav = $('#tabs');
    if (!nav) return;
    nav.after(bar);
    const follow = () => { bar.hidden = nav.hidden; };
    new MutationObserver(follow).observe(nav, { attributes: true, attributeFilter: ['hidden'] });
    follow();
    filterTabs();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  window.paths = { opened, welcome, choose, PATHS };
}());
