/* Selecao+ — notifications on this phone.
 *
 * The same panel on the manager's Weekly tab and on a team member's own page:
 * turn notifications on for this phone, send a test, see what was sent. The
 * server decides what each account is told about (workload_app/notify.py) and
 * seals each message for this phone; sw.js shows it.
 *
 * Any phone: on Android the browser itself can be told (Chrome, Edge, Firefox,
 * Samsung Internet); on an iPhone, Apple only allows it for the app kept on
 * the home screen.
 *
 * Uses the page's own helpers: el, api, setChildren, toast.
 */
(function () {
  'use strict';

  const push = { data: null, subscription: null, fingerprint: null, box: null };

  const supported = () => 'serviceWorker' in navigator && 'PushManager' in window
    && 'Notification' in window && window.isSecureContext;
  const apple = () => /iphone|ipad|ipod/i.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const homeScreen = () => window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;

  function day(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
    if (!iso) return '';
    return new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString(undefined, opts);
  }

  function keyBytes(text) {
    const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
    return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
  }

  function deviceLabel() {
    const ua = navigator.userAgent;
    if (/iphone/i.test(ua)) return 'iPhone';
    if (/ipad/i.test(ua)) return 'iPad';
    const kind = /android/i.test(ua) ? 'Android phone' : /windows/i.test(ua) ? 'Windows PC'
      : /mac/i.test(ua) ? 'Mac' : 'Browser';
    const browser = /samsungbrowser/i.test(ua) ? 'Samsung Internet' : /edg/i.test(ua) ? 'Edge'
      : /firefox|fxios/i.test(ua) ? 'Firefox' : /chrome|crios/i.test(ua) ? 'Chrome'
        : /safari/i.test(ua) ? 'Safari' : '';
    return browser ? `${kind}, ${browser}` : kind;
  }

  async function currentSubscription() {
    if (!supported()) return null;
    try {
      const registration = await navigator.serviceWorker.getRegistration();
      return registration ? await registration.pushManager.getSubscription() : null;
    } catch (error) {
      return null;
    }
  }

  async function fingerprintOf(subscription) {
    if (!subscription || !window.crypto || !crypto.subtle) return null;
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(subscription.endpoint));
    return [...new Uint8Array(digest)].slice(0, 6).map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  async function refresh() {
    try {
      push.data = await api('/api/push', { quiet: true });
    } catch (error) {
      push.data = null;
    }
    push.subscription = await currentSubscription();
    push.fingerprint = await fingerprintOf(push.subscription);
    render();
  }

  function unsupportedMessage() {
    if (apple() && !homeScreen()) {
      return 'On an iPhone, Apple only lets the home-screen app show notifications: tap Share, '
        + 'then "Add to Home Screen", open Selecao+ from there and come back here.';
    }
    if (apple()) {
      return 'This iPhone is too old for notifications from web apps. Update it to iOS 16.4 '
        + 'or later in Settings > General > Software Update.';
    }
    return 'This browser cannot show notifications. On Android, open Selecao+ in Chrome.';
  }

  function render() {
    const box = push.box;
    const p = push.data;
    if (!box) return;
    if (!p) { setChildren(box); box.hidden = true; return; }
    box.hidden = false;
    const here = push.subscription
      && p.devices.some((d) => d.fingerprint && d.fingerprint === push.fingerprint);
    let action;
    if (!supported()) {
      action = el('div', { class: 'msg msg-warn' }, unsupportedMessage());
    } else if (here) {
      action = el('div', { class: 'row-actions' },
        el('span', { class: 'pill pill-ok' }, 'On for this phone'),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: test }, 'Send a test'),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: check }, 'Check now'),
        el('button', { class: 'btn btn-sm', type: 'button', onclick: disable }, 'Turn off'));
    } else {
      action = el('div', { class: 'row-actions' },
        el('button', { class: 'btn btn-primary', type: 'button', onclick: enable },
          'Turn on notifications on this phone'));
    }
    const devices = p.devices.length ? el('ul', { class: 'wk-lines' }, p.devices.map((d) => el('li', {},
      el('span', { class: `wk-dot wk-dot-${d.failures ? 'warn' : 'ok'}` }),
      el('b', {}, d.label || 'A phone'),
      d.fingerprint === push.fingerprint ? ' (this one)' : '',
      `, on since ${day(d.added_at)}`,
      d.last_ok_at ? `, last reached ${day(d.last_ok_at)}` : '',
      d.failures ? el('span', { class: 'v-warn' },
        `. Not reached the last ${d.failures} time${d.failures === 1 ? '' : 's'}: ${d.last_error || ''}`) : ''))) : null;
    const sent = p.messages.length ? el('details', { class: 'wk-sent' },
      el('summary', {}, `Sent lately (${p.messages.length})`),
      el('ul', { class: 'wk-lines' }, p.messages.map((m) => el('li', {},
        el('span', { class: 'muted small' }, `${day(m.created_at, { day: 'numeric', month: 'short' })} `),
        el('b', {}, m.title), m.body ? el('div', { class: 'small muted' }, m.body) : null)))) : null;
    setChildren(box,
      el('div', { class: 'panel-head' }, el('div', {},
        el('h3', {}, 'Notifications on your phone'),
        el('p', { class: 'muted' }, `${p.about} Each thing once, never twice. Works on Android `
          + 'and iPhone; nothing goes by email.'))),
      action,
      devices,
      p.task && p.devices.length ? el('div', { class: 'wk-task' },
        el('p', { class: 'small' }, el('b', {}, 'So they arrive on their own every morning, for you and the team: '),
          'on PythonAnywhere open the Tasks tab, set a daily time before work (04:00 UTC is 7 am '
          + 'in Riyadh, 6 or 7 am in Cairo), paste this line, and press Create. Once is enough.'),
        el('div', { class: 'wk-task-line' },
          el('code', {}, p.task),
          el('button', { class: 'btn btn-sm', type: 'button', onclick: () => copy(p.task) }, 'Copy'))) : null,
      sent);
  }

  async function enable() {
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        toast('Notifications were not allowed. Allow them for Selecao+ in the phone\'s settings, then try again.', 'bad');
        return;
      }
      await navigator.serviceWorker.register('sw.js');
      const registration = await navigator.serviceWorker.ready;
      const key = keyBytes(push.data.public_key);
      let subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        // Made with another server key (or another installation): start again.
        const held = subscription.options && subscription.options.applicationServerKey;
        const same = held && new Uint8Array(held).join() === key.join();
        if (!same) { await subscription.unsubscribe(); subscription = null; }
      }
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true, applicationServerKey: key });
      }
      await api('/api/push/devices', { method: 'POST', body: {
        ...subscription.toJSON(), label: deviceLabel(), site: window.location.origin } });
      toast('Notifications are on. A test is on its way.', 'ok');
      await test();
    } catch (error) {
      toast(error.message || 'Notifications could not be turned on.', 'bad');
      await refresh();
    }
  }

  async function disable() {
    const mine = push.data.devices.find((d) => d.fingerprint === push.fingerprint);
    try {
      if (push.subscription) await push.subscription.unsubscribe();
      if (mine) await api(`/api/push/devices/${mine.id}`, { method: 'DELETE' });
      toast('Notifications are off on this phone.', 'ok');
    } catch (error) {
      toast(error.message, 'bad');
    }
    await refresh();
  }

  async function test() {
    try {
      const result = await api('/api/push/test', { method: 'POST' });
      const failed = result.results.filter((r) => !r.ok);
      if (failed.length) toast(`Not sent to ${failed.map((f) => f.label || 'a phone').join(', ')}: ${failed[0].error}`, 'bad');
      else toast('Test sent. It should show on the phone in a few seconds.', 'ok');
    } catch (error) {
      toast(error.message, 'bad');
    }
    await refresh();
  }

  async function check() {
    try {
      const result = await api('/api/push/check', { method: 'POST' });
      toast(result.new ? `${result.new} new thing${result.new === 1 ? '' : 's'} sent to your phone.`
        : 'Nothing new since the last notification.', result.failed ? 'bad' : 'ok');
    } catch (error) {
      toast(error.message, 'bad');
    }
    await refresh();
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('Copied. Paste it on the PythonAnywhere Tasks tab.', 'ok');
    } catch (error) {
      toast('Select the line and copy it.', 'bad');
    }
  }

  window.selecaoPush = {
    /* Fill ``box`` with the panel, and keep it up to date. */
    show(box) {
      if (!box) return;
      push.box = box;
      refresh();
    },
  };
}());
