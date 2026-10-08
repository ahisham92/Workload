/* Selecao+ — emails in, as draft tasks.
 *
 * On the Today page, above the quick add: the emails the senior's own Outlook
 * sent in, each already a draft with its project, hours and date guessed.
 * Pick who and tap Assign, and it is a request like any other. Emails that
 * need nothing (automatic replies, meeting answers, newsletters, thanks,
 * "for information", copied in) are kept to one side and never become tasks.
 *
 * Built on app.js and planner.js (el, api, toast, openPanel, plan, loadDay...).
 */
'use strict';

const inbox = {
  data: null,
  open: new Set(),      // drafts whose whole opening is shown
  all: false,           // every draft shown, not just the first few
  showQuiet: false,     // the emails that needed nothing, shown
  node: null,           // the panel on the page
  loaded: 0,            // when the emails were last asked for
};

const INBOX_FIRST = 4;

async function loadInbox({ quiet = true } = {}) {
  inbox.loaded = Date.now();
  try {
    inbox.data = await api('/api/inbox', { quiet });
  } catch (error) {
    if (!quiet) toast((error.errors || [error.message]).join(' '), 'bad');
  }
  // Never redrawn under somebody choosing who gets a draft.
  if (inbox.node && inbox.node.contains(document.activeElement)
      && document.activeElement !== document.body) return;
  drawInbox();
}

/** The panel's place on the Today page; the same panel each time the day is
 *  drawn again, asked for afresh once a minute at most. */
function inboxPanel() {
  if (!inbox.node) {
    inbox.node = el('section', { class: 'panel inbox-panel', id: 'inbox-panel' });
    drawInbox();
  }
  if (Date.now() - inbox.loaded > 60000) loadInbox();
  return inbox.node;
}

function whenText(iso) {
  if (!iso) return '';
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return '';
  const day = isoDay(moment);
  const time = moment.toTimeString().slice(0, 5);
  return day === isoDay(new Date()) ? time : `${shortDate(day)} ${time}`;
}

function senderName(sender) {
  const text = (sender || '').replace(/<[^>]*>/g, '').replace(/"/g, '').trim();
  return text || sender || '';
}

function drawInbox() {
  const node = inbox.node;
  if (!node) return;
  const data = inbox.data;
  const day = plan.dayData;
  if (!data) {
    setChildren(node, el('div', { class: 'panel-head' },
      el('h3', {}, 'Emails'), inboxButtons(null)));
    return;
  }
  const drafts = data.drafts || [];
  const shown = inbox.all ? drafts : drafts.slice(0, INBOX_FIRST);
  const connected = data.key && data.key.last_used;
  setChildren(node,
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, drafts.length ? `Emails to hand out (${drafts.length})` : 'Emails'),
        el('p', { class: 'muted small' }, drafts.length
          ? 'Each one is a draft task. Pick who, then Assign. No action takes it off the list.'
          : data.key
            ? (connected ? `Nothing waiting. Your Outlook last sent one ${whenText(data.key.last_used)}.`
              : 'Your Outlook link is made. New emails that ask for something show here.')
            : 'Emails that ask for something can show here as draft tasks. Connect your Outlook, or paste one in.')),
      inboxButtons(data)),
    drafts.length ? el('ul', { class: 'inbox-list' },
      shown.map((item) => draftCard(item, day))) : null,
    drafts.length > INBOX_FIRST ? el('button', { class: 'linkish', type: 'button',
      onclick: () => { inbox.all = !inbox.all; drawInbox(); } },
    inbox.all ? 'Show fewer' : `Show all ${drafts.length}`) : null,
    quietList(data));
}

function inboxButtons(data) {
  return el('div', { class: 'row-actions' },
    el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: pasteEmail },
      'Paste an email'),
    el('button', { class: 'btn btn-sm', type: 'button', onclick: () => openOutlookSetup() },
      data && data.key ? 'Outlook link' : 'Connect Outlook'));
}

function draftCard(item, day) {
  const guess = item.guess || {};
  const today = day ? day.today : isoDay(new Date());
  const title = el('input', { type: 'text', class: 'grow', 'aria-label': 'The task',
    value: guess.title || item.subject || '' });
  const hours = el('select', { 'aria-label': 'Roughly how long' },
    [['0.5', '½ h'], ['1', '1 h'], ['2', '2 h'], ['4', '½ day'], ['8.5', '1 day'],
      ['17', '2 days']].map(([value, text]) => el('option', { value }, text)));
  hours.value = String(guess.hours || 1);
  if (!hours.value) hours.value = '1';
  const due = el('input', { type: 'date', 'aria-label': 'Wanted by',
    value: guess.due || shiftDay(today, 2) });
  const people = day ? day.people.filter((p) => day.engineers.includes(p.name)) : [];
  const who = el('select', { 'aria-label': 'Who' },
    el('option', { value: 'engineering' }, 'Engineer with room'),
    el('option', { value: 'drafting' }, 'Draftsman with room'),
    ...people.map((p) => el('option', { value: `person:${p.name}` }, p.name)));
  who.value = guess.role === 'drafting' ? 'drafting' : 'engineering';
  const project = el('select', { 'aria-label': 'Project' },
    el('option', { value: '' }, 'No project'),
    ...(day ? day.projects : []).map((p) => el('option', { value: p.number },
      p.name && p.name !== p.number ? `${p.number} ${p.name}` : p.number)));
  project.value = guess.project_number || '';
  const expanded = inbox.open.has(item.id);
  const assign = async () => {
    const choice = who.value;
    const d = new Date();
    try {
      const result = await api(`/api/inbox/${item.id}/assign`, { method: 'POST', body: {
        title: title.value.trim(), hours: Number(hours.value), due: due.value,
        project_number: project.value,
        role: choice.startsWith('person:') ? 'engineering' : choice,
        person: choice.startsWith('person:') ? choice.slice(7) : '',
        now: `${isoDay(d)}T${d.toTimeString().slice(0, 5)}`,
      } });
      if (result.save) markSaved(result.save);
      toast(`${result.person} has it, ${slotText(result.start, result.end)}`
        + (result.late ? ' — later than wanted' : ''), result.late ? 'bad' : 'ok');
      plan.needs = null;
      if (state.tasks) state.tasks = null;
      await Promise.all([loadInbox(), loadDay({ quiet: true })]);
    } catch (error) { toast((error.errors || [error.message]).join(' '), 'bad'); }
  };
  return el('li', { class: 'inbox-item' },
    el('div', { class: 'inbox-top' },
      el('b', { class: 'inbox-subject' }, item.subject || '(no subject)'),
      el('span', { class: 'muted small' },
        [senderName(item.sender), whenText(item.received_at || item.created_at),
          item.replies ? `${item.replies} more ${item.replies === 1 ? 'reply' : 'replies'}` : '']
          .filter(Boolean).join(' · '))),
    item.snippet ? el('p', {
      class: `inbox-snippet ${expanded ? 'is-open' : ''}`, role: 'button', tabindex: '0',
      title: expanded ? 'Show less' : 'Show more',
      onclick: () => { if (expanded) inbox.open.delete(item.id); else inbox.open.add(item.id); drawInbox(); },
    }, item.snippet) : null,
    el('div', { class: 'quick-add inbox-form' }, title,
      el('div', { class: 'quick-add-options' }, who, project, hours, due,
        el('button', { class: 'btn btn-primary', type: 'button', onclick: assign }, 'Assign'),
        el('button', { class: 'btn btn-ghost', type: 'button',
          onclick: () => setEmail(item.id, 'dismissed', 'Off the list. It needed nothing.') },
        'No action'))),
    item.sender ? el('button', { class: 'linkish small', type: 'button',
      onclick: () => quietSender(item.sender) },
    `Emails from ${senderName(item.sender)} never need a task`) : null);
}

function quietList(data) {
  const quiet = (data.no_action || []).concat(data.dismissed || [])
    .sort((a, b) => (b.received_at || b.created_at || '').localeCompare(a.received_at || a.created_at || ''));
  if (!quiet.length && !(data.quiet || []).length) return null;
  return el('div', { class: 'inbox-quiet' },
    el('button', { class: 'linkish small', type: 'button',
      onclick: () => { inbox.showQuiet = !inbox.showQuiet; drawInbox(); } },
    inbox.showQuiet ? 'Hide the emails that needed nothing'
      : `${quiet.length} ${quiet.length === 1 ? 'email' : 'emails'} needed nothing (kept ${data.keep_days} days)`),
    inbox.showQuiet ? el('table', { class: 'inbox-quiet-table' },
      el('thead', {}, el('tr', {}, el('th', {}, 'Email'), el('th', {}, 'Why no task'), el('th', {}, ''))),
      el('tbody', {}, quiet.map((item) => el('tr', {},
        el('td', {}, el('b', {}, item.subject || '(no subject)'),
          el('div', { class: 'muted small' },
            [senderName(item.sender), whenText(item.received_at || item.created_at)]
              .filter(Boolean).join(' · '))),
        el('td', { class: 'small' }, item.reason),
        el('td', {}, el('button', { class: 'btn btn-sm', type: 'button',
          onclick: () => setEmail(item.id, 'draft', 'Back on the list as a draft.') },
        'Make it a task')))))) : null,
    inbox.showQuiet && (data.quiet || []).length ? el('p', { class: 'small' },
      el('b', {}, 'Never a task: '),
      ...(data.quiet || []).map((address) => el('span', { class: 'pill' }, address, ' ',
        el('button', { class: 'linkish', type: 'button', title: 'Take off',
          onclick: () => saveInboxSettings({ quiet_remove: [address] }) }, '×')))) : null);
}

async function setEmail(id, status, message) {
  try {
    inbox.data = await api(`/api/inbox/${id}/status`, { method: 'POST', body: { status } });
    toast(message, 'ok');
    drawInbox();
  } catch (error) { toast((error.errors || [error.message]).join(' '), 'bad'); }
}

async function saveInboxSettings(body, message) {
  try {
    inbox.data = await api('/api/inbox/settings', { method: 'POST', body });
    if (message) toast(message, 'ok');
    drawInbox();
    return true;
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
    return false;
  }
}

function quietSender(sender) {
  saveInboxSettings({ quiet_add: [sender] },
    `Emails from ${senderName(sender)} will not become tasks.`);
}

/** The one-tap way in: the email copied on the phone, pasted here. */
async function pasteEmail() {
  let text = '';
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      text = await navigator.clipboard.readText();
    }
  } catch { /* the browser said no: the box below takes it instead */ }
  if (text && text.trim().length > 3) {
    await sendPaste(text);
    return;
  }
  const box = el('textarea', { rows: '8', placeholder: 'Paste the email here', class: 'inbox-paste' });
  openPanel('Paste an email', el('div', {},
    el('p', { class: 'muted small' },
      'In Outlook, open the email, select its text and copy it. Paste it here and it becomes a draft task.'),
    box,
    el('div', { class: 'row-actions' },
      el('button', { class: 'btn btn-primary', type: 'button', onclick: async () => {
        if (!box.value.trim()) { box.focus(); return; }
        if (await sendPaste(box.value)) closeModal();
      } }, 'Make a draft'))));
  box.focus();
}

async function sendPaste(text) {
  try {
    inbox.data = await api('/api/inbox/paste', { method: 'POST', body: { text } });
    toast('A draft task is on the list.', 'ok');
    drawInbox();
    return true;
  } catch (error) {
    toast((error.errors || [error.message]).join(' '), 'bad');
    return false;
  }
}

function copyButton(text, label = 'Copy') {
  return el('button', { class: 'btn btn-sm', type: 'button', onclick: async (event) => {
    try {
      await navigator.clipboard.writeText(text);
      event.target.textContent = 'Copied';
    } catch { toast('Select the text and copy it.', 'bad'); }
  } }, label);
}

/** Connecting a senior's own Outlook: a Power Automate flow on their account. */
function openOutlookSetup(made) {
  const data = inbox.data || {};
  const address = `${window.location.origin}${BASE}/api/inbox/email`;
  const me = el('input', { type: 'email', value: data.me || '', placeholder: 'you@company.com',
    'aria-label': 'Your work email' });
  const status = data.key
    ? (data.key.last_used
      ? `Connected. Last email ${whenText(data.key.last_used)}`
        + (data.key.last_result && data.key.last_result.ok === false
          ? ` (refused: ${data.key.last_result.error})` : '') + '.'
      : 'The link is made; no email has come through it yet.')
    : 'Not connected yet.';
  openPanel('Connect your Outlook', el('div', { class: 'outlook-setup' },
    el('p', {}, el('b', {}, status)),
    el('p', { class: 'muted small' },
      'Your Outlook sends each new email here by itself, through a flow on your own Microsoft 365 account. '
      + 'Nothing is installed and Selecao+ never signs in to your mailbox. Only the first lines of each '
      + `email are kept, for ${data.keep_days || 30} days. Use it only if your company allows flows like this.`),
    el('label', { class: 'field full' }, el('span', {}, 'Your work email',
      el('span', { class: 'hint' }, ' — emails you were only copied on stay out')),
    el('div', { class: 'row-actions' }, me,
      el('button', { class: 'btn btn-sm', type: 'button',
        onclick: () => saveInboxSettings({ me: me.value.trim() }, 'Saved.') }, 'Save'))),
    made ? el('div', {},
      el('ol', { class: 'outlook-steps' },
        el('li', {}, 'On your laptop, open ', el('b', {}, 'make.powerautomate.com'),
          ' and sign in with your work account.'),
        el('li', {}, el('b', {}, 'Create'), ' → ', el('b', {}, 'Automated cloud flow'),
          '. Name it Selecao+ emails. Pick the trigger ', el('b', {}, 'When a new email arrives (V3)'),
          ' (Office 365 Outlook), then ', el('b', {}, 'Create'), '. Leave its folder as Inbox.'),
        el('li', {}, el('b', {}, 'New step'), ' → search ', el('b', {}, 'HTTP'),
          ' → pick HTTP. Method ', el('b', {}, 'POST'), '. URI:',
          el('pre', { class: 'code-block' }, address), copyButton(address, 'Copy the URI')),
        el('li', {}, 'Headers: ', el('b', {}, 'Content-Type'), ' = ', el('b', {}, 'application/json'),
          '. Body: paste this, exactly:',
          el('pre', { class: 'code-block' }, made.flow_body), copyButton(made.flow_body, 'Copy the body')),
        el('li', {}, el('b', {}, 'Save'), '. Send yourself an email that asks for something; it shows on the Today page.')),
      el('p', { class: 'muted small' },
        'The body holds your private key: it is shown this once. If HTTP is marked Premium or your company blocks it, '
        + 'use Paste an email instead.'))
      : el('div', { class: 'row-actions' },
        el('button', { class: 'btn btn-primary', type: 'button', onclick: async () => {
          try {
            const result = await api('/api/inbox-key', { method: 'POST', body: {} });
            await loadInbox();
            openOutlookSetup(result);
          } catch (error) { toast((error.errors || [error.message]).join(' '), 'bad'); }
        } }, data.key ? 'Make a new link (the old one stops)' : 'Make my Outlook link'),
        data.key ? el('button', { class: 'btn btn-danger', type: 'button', onclick: async () => {
          try {
            await api('/api/inbox-key', { method: 'DELETE' });
            await loadInbox();
            toast('Your Outlook link is stopped.', 'ok');
            openOutlookSetup();
          } catch (error) { toast((error.errors || [error.message]).join(' '), 'bad'); }
        } }, 'Stop it') : null)));
}
