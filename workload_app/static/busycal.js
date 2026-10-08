/* Outlook meetings: what both pages say about linking a calendar.
 *
 * Each person publishes their Outlook calendar once with "Can view when I'm
 * busy" and pastes the ICS link. Selecao+ keeps only when they are busy, and
 * their plan, free hours and forecast leave that time out.
 *
 * Uses el() from app.js or member.js.
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
