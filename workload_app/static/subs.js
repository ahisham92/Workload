/* Selecao+ — submissions and their revisions, as one live sheet.
 *
 * A submission is started with the day it is planned to go; the day it really
 * went is put in; when the client sends it back, the day, the code (A, B or
 * C) and the reason go in, and the next revision is started from there. Every
 * cell saves the moment it is changed, and the same sheet shows on a project's
 * own page and on Planner > Submissions for every project, so whichever is
 * used, both say the same. The server keeps the rules (revisions.py).
 */
'use strict';

const SUB_ORDER = ['late', 'returned', 'comments', 'with_client', 'planned', 'none', 'accepted'];
const SUB_FILTERS = [
  ['open', 'On the go', ['late', 'planned', 'with_client', 'returned', 'comments']],
  ['all', 'Everything', null],
  ['late', 'Late to go', ['late']],
  ['with_client', 'With the client', ['with_client']],
  ['returned', 'Returned', ['returned', 'comments']],
  ['planned', 'Planned', ['planned']],
  ['accepted', 'Accepted', ['accepted']],
  ['none', 'Not started', ['none']],
];
const SUB_WORDS = {
  none: 'Not started', planned: 'Planned', late: 'Late to go', with_client: 'With the client',
  returned: 'Returned: revise', comments: 'Approved with comments', accepted: 'Accepted',
};
const SUB_CODES = [['', '—'], ['A', 'A · Accepted'], ['B', 'B · With comments'], ['C', 'C · Revise']];
const SUB_PURPOSES = ['', 'IFA', 'IFC', 'IFT', 'IFR', 'IFI'];

/** What can be picked as where a sending stands; the dates follow. */
const SUB_PICK = [['planned', 'Planned'], ['with_client', 'Submitted'],
  ['accepted', 'Back: A, accepted'], ['comments', 'Back: B, with comments'], ['returned', 'Back: C, revise']];

/** What picking a status writes: the dates and the code that make it so. A
    submission marked submitted went on its planned day when that has passed,
    else today; the date box is there to put it right. */
function subStatusChange(to, issue, today) {
  const planned = issue.planned || issue.status_date || '';
  const sent = issue.submitted || (planned && planned <= today ? planned : today);
  if (to === 'planned') return { submitted: '', returned: '', code: '' };
  if (to === 'with_client') return { submitted: sent, returned: '', code: '' };
  const back = issue.returned && issue.returned >= sent ? issue.returned : (today >= sent ? today : sent);
  return { submitted: sent, returned: back, code: { accepted: 'A', comments: 'B', returned: 'C' }[to] };
}

/** The status as a box to change: pick Submitted and it is submitted. */
function subStatusBox(status, choices, onPick) {
  const box = el('select', { class: 'sub-pick', 'aria-label': 'Change where it stands' },
    ...choices.map(([value, text]) => el('option', { value }, text)));
  box.value = status === 'late' ? 'planned' : status;
  box.addEventListener('change', () => onPick(box.value));
  return box;
}

/** Where one sending stands; the same rules as revisions.issue_status. */
function subStatus(issue, today) {
  if (issue.code === 'A') return 'accepted';
  if (issue.returned || issue.code === 'B' || issue.code === 'C') return issue.code === 'B' ? 'comments' : 'returned';
  if (issue.submitted) return 'with_client';
  if (issue.planned && issue.planned < today) return 'late';
  return 'planned';
}

function subDays(a, b) {
  return Math.round((new Date(`${b}T00:00:00Z`) - new Date(`${a}T00:00:00Z`)) / 86400000);
}

/** The words under a status: how long it has been with the client, or late. */
function subWhen(issue, status, today) {
  if (status === 'with_client') {
    const d = subDays(issue.submitted, today);
    return d <= 0 ? 'sent today' : `${d} day${d === 1 ? '' : 's'} with them`;
  }
  if (status === 'late') {
    const d = subDays(issue.planned, today);
    return `${d} day${d === 1 ? '' : 's'} late`;
  }
  if (status === 'planned' && issue.planned) {
    const d = subDays(today, issue.planned);
    return d === 0 ? 'due today' : `in ${d} day${d === 1 ? '' : 's'}`;
  }
  if (status === 'planned') return 'pick the day →';
  if ((status === 'returned' || status === 'comments') && issue.returned) return `back ${dateText(issue.returned, { day: 'numeric', month: 'short' })}`;
  if (status === 'accepted' && issue.returned) return dateText(issue.returned, { day: 'numeric', month: 'short', year: 'numeric' });
  return '';
}

function subChip(status, when) {
  return el('span', { class: `sub-chip st-${status}` },
    el('span', { class: 'sub-dot' }), SUB_WORDS[status],
    when ? el('small', {}, when) : null);
}

/** The revisions so far, as a row of marks: "0 C → 1 A". */
function subTrail(issues, today) {
  if (!issues.length) return null;
  return el('span', { class: 'sub-trail', title: 'Each revision, oldest first' },
    ...issues.map((issue) => el('span', { class: `sub-mark st-${subStatus(issue, today)}` },
      issue.rev || '·', issue.code ? el('b', {}, issue.code) : null)));
}

/**
 * The sheet. `project` limits it to one project's deliverables (its own
 * page); without it every project's are there, with filters (Planner).
 * Returns { node, reload }.
 */
function submissionsPanel({ project = null, onChange = null } = {}) {
  const view = { data: null, filter: project ? 'all' : 'open', open: new Set(), queue: new Map() };
  const body = el('div', { class: 'subs-body' }, el('p', { class: 'muted' }, 'Loading the submissions…'));
  const node = el('section', { class: 'panel subs-panel' },
    el('div', { class: 'panel-head' },
      el('div', {},
        el('h3', {}, project ? 'Submissions and revisions' : 'All submissions'),
        el('p', { class: 'muted' },
          'Put in the day a submission is planned to go, or pick Submitted when it has gone. '
          + 'When it comes back, pick its code (or give the day and the reason), and start the next revision. '
          + 'Every change saves as you make it, here and on '
          + (project ? 'Planner › Submissions.' : 'each project’s own page.')))),
    body);

  const reload = async ({ quiet = Boolean(view.data) } = {}) => {
    try {
      view.data = await api(`/api/submission-issues${project ? `?project=${encodeURIComponent(project)}` : ''}`, { quiet });
      draw();
    } catch (error) {
      setChildren(body, el('p', { class: 'v-bad' }, errorText(error)));
    }
  };

  const changed = () => { if (typeof onChange === 'function') onChange(); };

  /* One save at a time for each sending, in the order they were made, so a
     row pasted in (sent, then back) arrives in that order. */
  const send = (key, work) => {
    const before = view.queue.get(key) || Promise.resolve();
    const next = before.then(work, work);
    view.queue.set(key, next.catch(() => {}));
    return next;
  };

  const counts = () => {
    const out = {};
    for (const item of view.data.items) out[item.status] = (out[item.status] || 0) + 1;
    return out;
  };

  function draw() {
    const data = view.data;
    if (!data) return;
    const n = counts();
    const filter = SUB_FILTERS.find((f) => f[0] === view.filter) || SUB_FILTERS[0];
    const items = data.items
      .filter((item) => !filter[2] || filter[2].includes(item.status))
      .slice()
      .sort((a, b) => SUB_ORDER.indexOf(a.status) - SUB_ORDER.indexOf(b.status)
        || String(latestDate(a)).localeCompare(String(latestDate(b))));
    const strip = el('div', { class: 'sub-filters', role: 'tablist' },
      ...SUB_FILTERS.map(([key, words, statuses]) => {
        const count = statuses ? statuses.reduce((a, s) => a + (n[s] || 0), 0) : data.items.length;
        if (statuses && !count && key !== view.filter && key !== 'open') return null;
        return el('button', {
          type: 'button', role: 'tab', class: `sub-filter f-${key}${view.filter === key ? ' is-on' : ''}`,
          'aria-selected': view.filter === key ? 'true' : 'false',
          onclick: () => { view.filter = key; draw(); },
        }, el('b', {}, String(count)), words);
      }));
    const head = el('tr', {},
      el('th', {}, 'Deliverable'), el('th', {}, 'Where it stands'), el('th', {}, 'Revision'),
      el('th', {}, 'For'), el('th', {}, 'Who prepares it'), el('th', {}, 'Planned'), el('th', {}, 'Submitted'),
      el('th', {}, 'Returned'), el('th', {}, 'Review code'), el('th', {}, 'Reason / comments'),
      el('th', {}, ''));
    const rows = [];
    for (const item of items) rows.push(...itemRows(item));
    setChildren(body,
      data.items.length ? strip : null,
      items.length
        ? el('div', { class: 'table-wrap' }, el('table', { class: 'edit-table gsheet subs-table' },
            el('thead', {}, head), el('tbody', {}, rows)))
        : el('div', { class: 'empty' }, data.items.length
          ? (view.filter === 'open' ? 'Nothing on the go: every submission is in, or not started yet.' : 'Nothing here under this filter.')
          : 'No deliverables to submit yet. Add them on the project first.'));
  }

  const latestDate = (item) => {
    const last = item.issues[item.issues.length - 1];
    return last ? (last.returned || last.submitted || last.planned || '9999') : (item.status_date || '9999');
  };

  /** Who prepares it: tap to choose, on the sheet on the right. */
  const whoCell = (item) => {
    const people = item.people || [];
    return el('td', { class: 'sub-who' }, el('button', {
      type: 'button', class: `sub-who-btn${people.length ? '' : ' is-empty'}`,
      title: 'Choose who prepares it',
      onclick: () => openSubmission(item.row, { onChange: () => { changed(); reload(); } }),
    }, people.length ? people.join(', ') : 'Choose who'));
  };

  /** A deliverable's rows: its newest sending, and the earlier ones folded. */
  function itemRows(item) {
    const today = view.data.today;
    const issues = item.issues;
    const older = issues.slice(0, -1);
    const isOpen = view.open.has(item.row);
    const who = el('td', { class: 'sub-what' },
      project ? null : el('span', { class: 'code' }, `${item.project_number} `),
      el('b', {}, item.name),
      el('div', { class: 'sub-meta' },
        subTrail(issues, today),
        item.list ? el('span', { class: 'muted small', title: 'From the drawing list' },
          ` ${item.list.issued}/${item.list.total} drawings out · A ${item.list.code_a} · B ${item.list.code_b} · C ${item.list.code_c}`) : null,
        older.length ? el('button', {
          type: 'button', class: 'sub-fold',
          onclick: () => { if (isOpen) view.open.delete(item.row); else view.open.add(item.row); draw(); },
        }, isOpen ? 'Hide history' : `History (${older.length})`) : null));
    if (!issues.length) return [notStartedRow(item, who)];
    const rows = [issueRow(item, issues[issues.length - 1], who, true)];
    if (isOpen) {
      older.slice().reverse().forEach((issue) => rows.push(issueRow(item, issue,
        el('td', { class: 'sub-what is-old' }, el('span', { class: 'muted small' }, `earlier · Rev ${issue.rev || '—'}`)), false)));
    }
    return rows;
  }

  function notStartedRow(item, who) {
    const today = view.data.today;
    const planned = el('input', { type: 'date', value: item.status_date || '', 'aria-label': 'Planned to go' });
    const submitted = el('input', { type: 'date', 'aria-label': 'Really submitted' });
    const start = async (extra = {}) => {
      try {
        await api('/api/submission-issues', { method: 'POST', quiet: true, body: { row: item.row, ...extra } });
        toast(extra.submitted ? `${item.name}: submitted ${dateText(extra.submitted)}.` : `${item.name}: planned.`, 'ok');
        changed();
        await reload();
      } catch (error) { toastError(error); }
    };
    planned.addEventListener('change', () => { if (planned.value) start({ planned: planned.value }); });
    submitted.addEventListener('change', () => {
      if (submitted.value) start({ ...(planned.value ? { planned: planned.value } : {}), submitted: submitted.value });
    });
    const pick = (to) => {
      if (to === 'none') return;
      const extra = planned.value ? { planned: planned.value } : {};
      if (to === 'planned') { start(extra); return; }
      start({ ...extra, ...subStatusChange(to, { planned: planned.value }, today) });
    };
    return el('tr', { class: 'sub-row is-none' },
      who,
      el('td', {}, subStatusBox('none', [['none', 'Not started'], ...SUB_PICK], pick)),
      el('td', { class: 'sub-hint muted small', colspan: 2 }, 'Put in a date, or pick Submitted'),
      whoCell(item),
      el('td', {}, planned),
      el('td', {}, submitted),
      el('td', { class: 'muted small', colspan: 3 }, item.step_name ? `Step reached: ${item.step_name}` : ''),
      el('td', {}));
  }

  function issueRow(item, issue, who, latest) {
    const today = view.data.today;
    const statusCell = el('td', {});
    const actionCell = el('td', { class: 'sub-actions' });
    const tr = el('tr', { class: `sub-row${latest ? '' : ' is-old'}` });

    const paint = () => {
      const status = subStatus(issue, today);
      tr.dataset.status = status;
      setChildren(statusCell, subChip(status, subWhen(issue, status, today)),
        latest ? subStatusBox(status, SUB_PICK, pickStatus) : null);
      if (latest) {
        item.status = status;
        const again = status === 'returned' || status === 'comments';
        setChildren(actionCell,
          again ? el('button', { type: 'button', class: 'btn btn-sm btn-primary', title: 'Start the next revision',
            onclick: nextRevision }, `Rev ${nextRev(issue.rev)} ›`) : null,
          el('button', { type: 'button', class: 'btn btn-sm btn-ghost sub-x', title: 'Remove this one',
            'aria-label': 'Remove this submission', onclick: remove }, '✕'));
      } else {
        setChildren(actionCell, el('button', { type: 'button', class: 'btn btn-sm btn-ghost sub-x',
          title: 'Remove this one', 'aria-label': 'Remove this submission', onclick: remove }, '✕'));
      }
    };

    const pickStatus = (to) => {
      const change = subStatusChange(to, issue, today);
      tr.classList.add('is-saving');
      send(issue.id, async () => {
        try {
          const result = await api(`/api/submission-issues/${issue.id}`, { method: 'PUT', quiet: true, body: change });
          if (result.save) markSaved(result.save);
          changed();
        } catch (error) { toastError(error); }
        await reload();
      });
    };

    const nextRevision = async () => {
      try {
        await api('/api/submission-issues', { method: 'POST', quiet: true, body: { row: item.row } });
        toast(`${item.name}: Rev ${nextRev(issue.rev)} started. Put in the day it is planned to go.`, 'ok');
        changed();
        await reload();
      } catch (error) { toastError(error); }
    };
    const remove = async () => {
      if (!window.confirm(`Remove Rev ${issue.rev || '—'} of ${item.name}? The other revisions stay.`)) return;
      try {
        await api(`/api/submission-issues/${issue.id}`, { method: 'DELETE', quiet: true });
        changed();
        await reload();
      } catch (error) { toastError(error); }
    };

    /** A cell that saves itself the moment it is changed. */
    const cell = (key, box) => {
      const show = (value) => { box.value = value ?? ''; };
      show(issue[key]);
      box.addEventListener('change', () => {
        const value = box.value;
        if ((issue[key] ?? '') === value) return;
        const was = issue[key];
        issue[key] = value || (key === 'code' || key === 'rev' || key === 'purpose' || key === 'reason' ? '' : null);
        paint();
        tr.classList.add('is-saving');
        send(issue.id, async () => {
          try {
            const result = await api(`/api/submission-issues/${issue.id}`, { method: 'PUT', body: { [key]: value } });
            Object.assign(issue, result.issue);
            if (result.save) markSaved(result.save);
            tr.classList.remove('is-saving');
            tr.classList.add('is-saved');
            setTimeout(() => tr.classList.remove('is-saved'), 900);
            changed();
          } catch (error) {
            issue[key] = was;
            show(was);
            tr.classList.remove('is-saving');
            box.closest('td').classList.add('is-bad');
            setTimeout(() => box.closest('td') && box.closest('td').classList.remove('is-bad'), 2500);
            toastError(error);
          }
          paint();
        });
      });
      return el('td', { class: `sub-${key}` }, box);
    };
    const select = (options, label) => el('select', { 'aria-label': label },
      ...options.map(([value, text]) => el('option', { value }, text)));

    tr.append(
      who, statusCell,
      cell('rev', el('input', { type: 'text', maxlength: 12, 'aria-label': 'Revision', class: 'sub-revbox' })),
      cell('purpose', select(SUB_PURPOSES.map((p) => [p, p || '—']), 'Sent for')),
      latest ? whoCell(item) : el('td', {}),
      cell('planned', el('input', { type: 'date', 'aria-label': 'Planned to go' })),
      cell('submitted', el('input', { type: 'date', 'aria-label': 'Really submitted' })),
      cell('returned', el('input', { type: 'date', 'aria-label': 'Came back' })),
      cell('code', select(SUB_CODES, 'Client code')),
      cell('reason', el('input', { type: 'text', maxlength: 300, 'aria-label': 'Reason or comments',
        placeholder: 'why it came back' })),
      actionCell);
    paint();
    return tr;
  }

  reload();
  return { node, reload };
}

/** The revision after this one: 0 → 1, A → B, P01 → P02 (revisions.next_rev). */
function nextRev(previous) {
  const text = String(previous || '').trim();
  if (!text) return '0';
  const hit = /(\d+)$/.exec(text);
  if (hit) return text.slice(0, hit.index) + String(Number(hit[1]) + 1).padStart(hit[1].length, '0');
  const last = text[text.length - 1];
  if (/[a-y]/i.test(last)) return text.slice(0, -1) + String.fromCharCode(last.charCodeAt(0) + 1);
  return `${text}1`;
}

/* ---------------------------------------------------------------------------
 * One submission, on the right of the page: a tap on its preparation on
 * Planner › Today opens it. Where it stands, its dates and the client's code,
 * and who prepares it for how long a day. Every box saves as it is changed.
 * ------------------------------------------------------------------------- */

/** The sheet on the right. Opening another one swaps what it shows. */
function openSide(title, content) {
  let sheet = document.getElementById('side-sheet');
  if (!sheet) {
    const close = () => { sheet.hidden = true; document.body.classList.remove('side-open'); };
    sheet = el('aside', { id: 'side-sheet', class: 'side-sheet', 'aria-label': 'Details' },
      el('header', { class: 'side-head' },
        el('h3', { class: 'side-title' }),
        el('button', { type: 'button', class: 'btn btn-ghost side-close', 'aria-label': 'Close', onclick: close }, '✕')),
      el('div', { class: 'side-body' }));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !sheet.hidden) close(); });
    document.body.append(sheet);
  }
  sheet.querySelector('.side-title').textContent = title;
  setChildren(sheet.querySelector('.side-body'), content);
  sheet.hidden = false;
  document.body.classList.add('side-open');
  return sheet;
}

function openSubmission(row, { onChange = null } = {}) {
  const body = el('div', { class: 'sub-card' }, el('p', { class: 'muted' }, 'Opening the submission…'));
  openSide('Submission', body);
  const changed = () => { if (typeof onChange === 'function') onChange(); };
  let queue = Promise.resolve();
  const later = (work) => { queue = queue.then(work, work); return queue; };

  const load = async () => {
    try {
      draw(await api(`/api/submissions/${row}`, { quiet: true }));
    } catch (error) {
      setChildren(body, el('p', { class: 'v-bad' }, errorText(error)));
    }
  };

  const field = (label, box, hint) => el('label', { class: 'sub-field' },
    el('span', { class: 'sub-label' }, label), box, hint ? el('small', { class: 'muted' }, hint) : null);

  function draw(data) {
    const item = data.item;
    if (!item) {
      setChildren(body, el('p', { class: 'muted' }, 'This submission is not on the list any more.'));
      return;
    }
    const today = data.today;
    const sheet = document.getElementById('side-sheet');
    if (sheet) sheet.querySelector('.side-title').textContent = item.name;
    const issues = item.issues || [];
    const issue = issues[issues.length - 1];
    const chip = el('div', { class: 'sub-card-chip' });
    const paintChip = () => {
      const status = issue ? subStatus(issue, today) : 'none';
      setChildren(chip, subChip(status, issue ? subWhen(issue, status, today) : ''));
      return status;
    };

    const pickStatus = async (to) => {
      try {
        if (!issue) {
          await api('/api/submission-issues', { method: 'POST', quiet: true,
            body: { row: item.row, ...(to === 'planned' ? {} : subStatusChange(to, { planned: item.status_date }, today)) } });
        } else {
          const result = await api(`/api/submission-issues/${issue.id}`, { method: 'PUT', quiet: true,
            body: subStatusChange(to, issue, today) });
          if (result.save) markSaved(result.save);
        }
        changed();
      } catch (error) { toastError(error); }
      await load();
    };
    const parts = [
      el('p', { class: 'sub-card-job' }, el('span', { class: 'code' }, `${item.project_number} `), item.project_name),
      el('div', { class: 'sub-card-status' }, chip,
        subStatusBox(issue ? subStatus(issue, today) : 'none',
          issue ? SUB_PICK : [['none', 'Not started'], ...SUB_PICK], (to) => { if (to !== 'none') pickStatus(to); })),
    ];

    if (!issue) {
      const planned = el('input', { type: 'date', value: item.status_date || '' });
      const start = async () => {
        try {
          await api('/api/submission-issues', { method: 'POST', quiet: true,
            body: { row: item.row, ...(planned.value ? { planned: planned.value } : {}) } });
          toast(`${item.name}: submission started.`, 'ok');
          changed();
          await load();
        } catch (error) { toastError(error); }
      };
      planned.addEventListener('change', () => { if (planned.value) start(); });
      parts.push(el('section', { class: 'sub-card-part' },
        el('h4', {}, 'When is it planned to go?'),
        field('Planned to go', planned, 'Pick the day: the submission starts with it.')));
    } else {
      /** A box that saves itself the moment it is changed. */
      const box = (key, input) => {
        input.value = issue[key] ?? '';
        input.addEventListener('change', () => {
          const value = input.value;
          if ((issue[key] ?? '') === value) return;
          const was = issue[key];
          issue[key] = value;
          paintChip();
          later(async () => {
            try {
              const result = await api(`/api/submission-issues/${issue.id}`, { method: 'PUT', quiet: true, body: { [key]: value } });
              Object.assign(issue, result.issue);
              if (result.save) markSaved(result.save);
              input.classList.add('is-saved');
              setTimeout(() => input.classList.remove('is-saved'), 900);
              paintChip();
              changed();
              if (key === 'planned') await load();      // its preparation days move with it
            } catch (error) {
              issue[key] = was;
              input.value = was ?? '';
              paintChip();
              toastError(error);
            }
          });
        });
        return input;
      };
      const select = (options) => el('select', {}, ...options.map(([value, text]) => el('option', { value }, text)));
      const status = paintChip();
      const again = status === 'returned' || status === 'comments';
      parts.push(el('section', { class: 'sub-card-part' },
        el('h4', {}, `Revision ${issue.rev || '—'}: its dates`),
        el('div', { class: 'sub-card-grid' },
          field('Planned to go', box('planned', el('input', { type: 'date' }))),
          field('Really sent', box('submitted', el('input', { type: 'date' })), 'Put the day in once it has gone.'),
          field('Came back', box('returned', el('input', { type: 'date' }))),
          field('Client’s code', box('code', select(SUB_CODES))),
          field('Revision', box('rev', el('input', { type: 'text', maxlength: 12 }))),
          field('Sent for', box('purpose', select(SUB_PURPOSES.map((p) => [p, p || '—']))))),
        field('Reason or comments', box('reason', el('input', { type: 'text', maxlength: 300, placeholder: 'why it came back' }))),
        again ? el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
          try {
            await api('/api/submission-issues', { method: 'POST', quiet: true, body: { row: item.row } });
            toast(`${item.name}: Rev ${nextRev(issue.rev)} started. Put in the day it is planned to go.`, 'ok');
            changed();
            await load();
          } catch (error) { toastError(error); }
        } }, `Start revision ${nextRev(issue.rev)}`) : null,
        issues.length > 1 ? el('p', { class: 'muted small' }, 'Revisions so far: ', subTrail(issues, today)) : null));
    }
    parts.push(prepPart(data));
    setChildren(body, ...parts);
  }

  /** Who prepares it, how long a day, and on which days. */
  function prepPart(data) {
    const prep = data.prep;
    const ahead = prep.days.filter((d) => !d.done && d.date >= data.today);
    const issues = (data.item && data.item.issues) || [];
    const last = issues[issues.length - 1];
    const planned = last ? (!last.submitted && last.planned) : null;
    if (!ahead.length && !(planned && planned >= data.today)) {
      return el('section', { class: 'sub-card-part' },
        el('h4', {}, 'Who prepares it?'),
        el('p', { class: 'muted' }, last && last.submitted
          ? 'It has gone: nothing left to prepare.'
          : 'Put in the day it is planned to go first: the preparation goes on the days before it.'));
    }
    const chosen = new Set(prep.people.length ? prep.people : (data.item.people || []));
    const save = (change, done) => later(async () => {
      try {
        const result = await api(`/api/submissions/${row}/prep`, { method: 'PUT', quiet: true, body: change });
        if (result.save) markSaved(result.save);
        if (done) done();
        changed();
      } catch (error) { toastError(error); await load(); }
    });
    const people = el('div', { class: 'sub-people' }, data.engineers.map((name) => {
      const chip = el('button', { type: 'button', class: `sub-person${chosen.has(name) ? ' is-on' : ''}`,
        'aria-pressed': chosen.has(name) ? 'true' : 'false' }, name);
      chip.addEventListener('click', () => {
        if (chosen.has(name) && chosen.size === 1) { toast('Somebody has to prepare it.', 'warn'); return; }
        if (chosen.has(name)) chosen.delete(name); else chosen.add(name);
        chip.classList.toggle('is-on', chosen.has(name));
        chip.setAttribute('aria-pressed', chosen.has(name) ? 'true' : 'false');
        save({ people: data.engineers.filter((n) => chosen.has(n)) }, ahead.length ? null : load);
      });
      return chip;
    }));
    const hours = el('input', { type: 'number', min: '0.25', max: '12', step: '0.25', value: String(prep.hours ?? '') });
    hours.addEventListener('change', () => {
      const value = Number(hours.value);
      if (!(value > 0)) return;
      save({ hours: value }, () => {
        hours.classList.add('is-saved');
        setTimeout(() => hours.classList.remove('is-saved'), 900);
      });
    });
    return el('section', { class: 'sub-card-part' },
      el('h4', {}, 'Who prepares it?'),
      el('p', { class: 'muted small' }, 'Tap a name to add or take them off. It applies from today to the planned day.'),
      people,
      field('Hours a day, each person', hours, 'Their whole day unless you change it.'),
      ahead.length
        ? el('p', { class: 'muted small' }, `Preparation days left: ${ahead.map((d) => dateText(d.date, { day: 'numeric', month: 'short' })).join(', ')}.`)
        : el('p', { class: 'muted small' }, 'Choose who, and the preparation goes on their days before it.'));
  }

  load();
}
