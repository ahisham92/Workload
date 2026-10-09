/* Selecao+ in the pocket.
 *
 * On a phone the app behaves like one:
 *
 *   - it can be kept on the home screen (manifest.json and sw.js) and then
 *     opens on its own, without the browser's bars around it;
 *   - the tabs become a bar along the bottom, in reach of a thumb. The views
 *     used day to day get a button each; everything else, and the top bar's
 *     own buttons (switch unit, account, save, reload), sit under More.
 *
 * The bar is built from the tabs on the page and follows them, so a tab added
 * to index.html appears here by itself: under More, unless it is named in
 * DAILY. Nothing in app.js needs to know the bar exists. Uses common.js's
 * make, isApple and isStandalone (loaded on the sign-in page too).
 */
(function () {
  'use strict';

  // The views a thumb should reach first, best first. The first four that
  // are on the page get a button of their own.
  const DAILY = ['overview', 'planner', 'checkins', 'weekly', 'today', 'tasks', 'timesheets', 'reports'];
  const SLOTS = 4;

  /* -- keeping it on the home screen ------------------------------------ */

  if ('serviceWorker' in navigator && window.isSecureContext) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('sw.js').catch(() => { /* a browser that will not */ });
    });
  }
  // Chrome and Edge offer an install of their own; keep the offer so More
  // can make it too.
  let installOffer = null;
  window.addEventListener('beforeinstallprompt', (event) => { installOffer = event; });
  window.addEventListener('appinstalled', () => { installOffer = null; });

  const tabs = document.getElementById('tabs');
  if (!tabs) return;

  /* -- the bar ------------------------------------------------------------ */

  const MORE_ICON = '<svg class="tab-icon" viewBox="0 0 24 24" aria-hidden="true">'
    + '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/>'
    + '<circle cx="19" cy="12" r="1.6"/></svg>';

  const bar = make('nav', { class: 'thumb-bar', 'aria-label': 'Sections', hidden: true });
  const sheet = make('div', { class: 'thumb-sheet', hidden: true });
  const panel = make('div', { class: 'thumb-sheet-panel', role: 'dialog',
    'aria-modal': 'true', 'aria-label': 'More' });
  sheet.append(make('div', { class: 'thumb-sheet-backdrop', onclick: closeSheet }), panel);
  const moreButton = make('button', { type: 'button', class: 'thumb-more',
    'aria-haspopup': 'dialog', 'aria-expanded': 'false',
    onclick: () => (sheet.hidden ? openSheet() : closeSheet()) });
  moreButton.innerHTML = `${MORE_ICON}<span>More</span>`;

  // A tab off the chosen path (paths.js) is out of the bar as well.
  const visibleTabs = () => Array.from(tabs.querySelectorAll('.tab'))
    .filter((t) => !t.hidden && !t.classList.contains('off-path'));
  const labelOf = (tab) => tab.textContent.replace(/\s+/g, ' ').trim();

  function split() {
    const all = visibleTabs();
    const rank = (tab) => {
      // A chosen path orders its own tabs first (paths.js sets a negative order).
      const order = Number(tab.style.order);
      if (order < 0) return order;
      const i = DAILY.indexOf(tab.dataset.view);
      return i < 0 ? Infinity : i;
    };
    const daily = all.filter((t) => rank(t) < Infinity)
      .sort((a, b) => rank(a) - rank(b)).slice(0, SLOTS);
    return { daily, more: all.filter((t) => !daily.includes(t)) };
  }

  /** Go to a tab's view the way a click on the tab itself would. */
  function go(tab) {
    closeSheet();
    tab.click();
    window.scrollTo({ top: 0 });
  }

  function tabButton(tab, className) {
    const icon = tab.querySelector('.tab-icon');
    return make('button', { type: 'button', class: className, 'data-for': tab.dataset.view,
      onclick: () => go(tab) },
    icon ? icon.cloneNode(true) : null, make('span', {}, labelOf(tab)));
  }

  let built = '';
  function render() {
    const { daily, more } = split();
    const shape = `${daily.map(labelOf)}|${more.map(labelOf)}`;
    if (shape !== built) {
      built = shape;
      bar.replaceChildren(...daily.map((tab) => tabButton(tab, 'thumb-tab')), moreButton);
      if (!sheet.hidden) fillSheet();
    }
    const active = tabs.querySelector('.tab.is-active');
    const view = active ? active.dataset.view : '';
    for (const button of bar.querySelectorAll('[data-for]')) {
      const on = button.dataset.for === view;
      button.classList.toggle('is-active', on);
      if (on) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    moreButton.classList.toggle('is-active', Boolean(active) && more.includes(active));
    bar.hidden = tabs.hidden;
    if (tabs.hidden) closeSheet();
    document.body.classList.toggle('has-thumb-bar', !tabs.hidden);
  }

  /* -- More --------------------------------------------------------------- */

  /** The top bar's own buttons and links, as they stand right now. */
  function topbarActions() {
    const holder = document.querySelector('.topbar-actions');
    if (!holder) return [];
    return Array.from(holder.querySelectorAll('button, a'))
      .filter((node) => !node.hidden && labelOf(node));
  }

  function installRow() {
    if (isStandalone()) return null;
    const hint = make('p', { class: 'thumb-sheet-hint', hidden: true });
    const row = make('button', { type: 'button', class: 'thumb-sheet-row thumb-install',
      onclick: async () => {
        if (installOffer) {
          const offer = installOffer;
          installOffer = null;
          await offer.prompt();
          closeSheet();
          return;
        }
        hint.textContent = isApple()
          ? 'In Safari, tap the Share button, then Add to Home Screen.'
          : 'Open your browser’s menu and choose Install app, or Add to Home screen.';
        hint.hidden = false;
      } }, 'Add Selecao+ to your home screen');
    return [row, hint];
  }

  function fillSheet() {
    const { more } = split();
    const active = tabs.querySelector('.tab.is-active');
    const tiles = more.map((tab) => {
      const tile = tabButton(tab, 'thumb-tile');
      if (tab === active) tile.classList.add('is-active');
      return tile;
    });
    const actions = topbarActions().map((node) => (node.tagName === 'A'
      ? make('a', { class: 'thumb-sheet-row', href: node.href }, labelOf(node))
      : make('button', { type: 'button', class: 'thumb-sheet-row',
        onclick: () => { closeSheet(); node.click(); } }, labelOf(node))));
    panel.replaceChildren(
      make('div', { class: 'thumb-sheet-grip', 'aria-hidden': 'true' }),
      tiles.length ? make('div', { class: 'thumb-sheet-grid' }, ...tiles) : null,
      make('div', { class: 'thumb-sheet-list' }, ...actions, ...(installRow() || [])),
    );
  }

  function openSheet() {
    fillSheet();
    sheet.hidden = false;
    moreButton.setAttribute('aria-expanded', 'true');
    document.body.classList.add('thumb-sheet-open');
    const first = panel.querySelector('button, a');
    if (first) first.focus({ preventScroll: true });
  }

  function closeSheet() {
    if (sheet.hidden) return;
    sheet.hidden = true;
    moreButton.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('thumb-sheet-open');
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSheet();
  });

  /* -- follow the tabs ------------------------------------------------------ */

  let queued = false;
  function queue() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; render(); });
  }

  function start() {
    document.body.append(sheet, bar);
    new MutationObserver(queue).observe(tabs, {
      subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'hidden'],
    });
    render();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}());
