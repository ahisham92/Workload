/* Outlook meetings: what both pages say about linking a calendar.
 *
 * Each person publishes their Outlook calendar once with "Can view when I'm
 * busy" and pastes the ICS link. Selecao+ keeps only when they are busy, and
 * their plan, free hours and forecast leave that time out.
 *
 * Uses el() from app.js or member.js, and common.js's dateText.
 */
'use strict';

/** The three steps, the same on every page. */
function calendarSteps() {
  return el('ol', { class: 'cal-steps' },
    el('li', {}, 'Open Outlook on the web (outlook.office.com), then Settings ⚙, Calendar, Shared calendars.'),
    el('li', {}, 'Under "Publish a calendar" pick your Calendar and "Can view when I\'m busy", then Publish.'),
    el('li', {}, 'Copy the ICS link (ends in .ics) and paste it here. Done once.'));
}

const CALENDAR_NOTE = 'Only busy times are read: no titles, no people, no notes. '
  + 'If there is no "Publish a calendar" there, Dar has it turned off.';

/** "read 10 min ago" for a timestamp from the server. */
function calendarRead(person) {
  if (person.problem) return person.problem;
  if (!person.read_at) return 'Not read yet.';
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(person.read_at)) / 60000));
  const when = minutes < 2 ? 'just now' : minutes < 90 ? `${minutes} min ago`
    : `${Math.round(minutes / 60)} h ago`;
  return `${person.meetings} meeting(s), ${person.hours_next_7_days} h in the next 7 days · changed ${when}`;
}

/** A paste box and Save, calling ``save(link)``. */
function calendarPaste(save, label = 'Link my calendar') {
  const input = el('input', { type: 'url', class: 'grow', inputmode: 'url', autocomplete: 'off',
    placeholder: 'https://outlook.office365.com/owa/calendar/…/calendar.ics',
    'aria-label': 'Outlook calendar link' });
  const go = async () => {
    if (!input.value.trim()) { input.focus(); return; }
    await save(input.value.trim());
  };
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') go(); });
  return el('div', { class: 'cal-paste' }, input,
    el('button', { class: 'btn btn-sm btn-primary', type: 'button', onclick: go }, label));
}

/* -- meetings typed in by hand ------------------------------------------- */

const MEETING_KIND = { client: 'Client', trade: 'Other trade', internal: 'Internal' };
const MEETING_REPEAT = { '': 'Once', weekly: 'Every week', fortnightly: 'Every 2 weeks' };

/** The add-a-meeting form. ``people`` (names) shows "Who goes" ticks, with
    ``ticked`` ticked; leave it empty for a person's own page. */
function meetingForm({ day, people = [], ticked = [], add }) {
  const title = el('input', { type: 'text', maxlength: 120, class: 'grow',
    placeholder: 'What, e.g. Design review with the client', 'aria-label': 'What the meeting is' });
  const kind = el('select', { 'aria-label': 'With' },
    ...Object.entries(MEETING_KIND).map(([value, text]) => el('option', { value }, text)));
  const date = el('input', { type: 'date', value: day, 'aria-label': 'Day' });
  const from = el('input', { type: 'time', value: '10:00', step: 900, 'aria-label': 'From' });
  const to = el('input', { type: 'time', value: '11:00', step: 900, 'aria-label': 'To' });
  from.addEventListener('change', () => {
    if (to.value <= from.value) {
      const [h, m] = from.value.split(':').map(Number);
      to.value = `${String(Math.min(23, h + 1)).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
    }
  });
  const repeat = el('select', { 'aria-label': 'Repeat' },
    ...Object.entries(MEETING_REPEAT).map(([value, text]) => el('option', { value }, text)));
  const until = el('input', { type: 'date', 'aria-label': 'Until' });
  const untilLabel = el('label', { class: 'field', hidden: true }, el('span', {}, 'Until'), until);
  repeat.addEventListener('change', () => { untilLabel.hidden = !repeat.value; });
  const boxes = people.map((name) => el('label', { class: 'meet-who' },
    el('input', { type: 'checkbox', value: name, ...(ticked.includes(name) ? { checked: '' } : {}) }),
    ` ${name}`));
  let adding = false;
  const go = async () => {
    // A second tap while the first is on its way would put the meeting (and
    // every repeat of it) in twice.
    if (adding) return;
    adding = true;
    const body = { title: title.value, kind: kind.value, day: date.value, start: from.value,
      end: to.value, repeat: repeat.value, until: until.value || null,
      people: boxes.map((b) => b.querySelector('input')).filter((i) => i.checked).map((i) => i.value) };
    try {
      if (await add(body)) title.value = '';
    } finally {
      adding = false;
    }
  };
  return el('div', { class: 'meet-form' },
    el('div', { class: 'meet-row' }, title,
      el('label', { class: 'field' }, el('span', {}, 'With'), kind)),
    el('div', { class: 'meet-row' },
      el('label', { class: 'field' }, el('span', {}, 'Day'), date),
      el('label', { class: 'field' }, el('span', {}, 'From'), from),
      el('label', { class: 'field' }, el('span', {}, 'To'), to),
      el('label', { class: 'field' }, el('span', {}, 'Repeat'), repeat),
      untilLabel),
    boxes.length ? el('div', { class: 'meet-row meet-people' }, el('span', { class: 'muted small' }, 'Who goes:'), ...boxes) : null,
    el('div', { class: 'meet-row' },
      el('button', { class: 'btn btn-primary', type: 'button', onclick: go }, 'Add meeting')));
}

/** The meetings coming up, each with Remove when ``canRemove(m)``. */
function meetingList(meetings, { remove, canRemove = () => true, showPeople = true }) {
  if (!meetings.length) return el('p', { class: 'muted small' }, 'No meetings put in yet.');
  return el('ul', { class: 'request-list' }, meetings.map((m) => el('li', { class: 'request meet-item' },
    el('span', { class: 'request-time' }, `${dateText(m.next)} ${m.start}–${m.end}`),
    el('span', { class: 'request-what' },
      el('span', { class: `pill meet-${m.kind}` }, MEETING_KIND[m.kind] || m.kind), ' ',
      el('b', {}, m.title || 'Meeting'),
      el('span', { class: 'muted small' },
        [m.repeat ? MEETING_REPEAT[m.repeat].toLowerCase() + (m.until ? ` until ${dateText(m.until)}` : '') : '',
          showPeople ? m.people.join(', ') : ''].filter(Boolean).map((t) => ` · ${t}`).join(''))),
    canRemove(m) ? el('button', { class: 'btn btn-sm btn-ghost', type: 'button',
      onclick: () => remove(m) }, 'Remove') : el('span'))));
}
