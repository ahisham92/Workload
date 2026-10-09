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
          'Start a submission with the day it is planned to go, then put in the day it really went. '
          + 'When it comes back, give the day, the client’s code and the reason, and start the next revision. '
          + 'Every change saves as you make it, here and on '
          + (project ? 'Planner › Submissions.' : 'each project’s own page.')))),
    body);

  const reload = async () => {
    try {
      view.data = await api(`/api/submission-issues${project ? `?project=${encodeURIComponent(project)}` : ''}`);
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
      el('th', {}, 'For'), el('th', {}, 'Planned'), el('th', {}, 'Submitted'),
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
    const planned = el('input', { type: 'date', value: item.status_date || '', 'aria-label': 'Planned to go' });
    const start = async (extra = {}) => {
      try {
        await api('/api/submission-issues', { method: 'POST', body: { row: item.row, ...extra } });
        toast(`${item.name}: submission started.`, 'ok');
        changed();
        await reload();
      } catch (error) { toastError(error); }
    };
    planned.addEventListener('change', () => { if (planned.value) start({ planned: planned.value }); });
    return el('tr', { class: 'sub-row is-none' },
      who,
      el('td', {}, subChip('none', '')),
      el('td', { class: 'sub-hint muted small', colspan: 2 }, 'Pick the day it is planned to go →'),
      el('td', {}, planned),
      el('td', { class: 'muted small', colspan: 4 }, item.step_name ? `Step reached: ${item.step_name}` : ''),
      el('td', {}, el('button', { type: 'button', class: 'btn btn-sm btn-primary',
        onclick: () => start(planned.value ? { planned: planned.value } : {}) }, 'Start')));
  }

  function issueRow(item, issue, who, latest) {
    const today = view.data.today;
    const statusCell = el('td', {});
    const actionCell = el('td', { class: 'sub-actions' });
    const tr = el('tr', { class: `sub-row${latest ? '' : ' is-old'}` });

    const paint = () => {
      const status = subStatus(issue, today);
      tr.dataset.status = status;
      setChildren(statusCell, subChip(status, subWhen(issue, status, today)));
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

    const nextRevision = async () => {
      try {
        await api('/api/submission-issues', { method: 'POST', body: { row: item.row } });
        toast(`${item.name}: Rev ${nextRev(issue.rev)} started. Put in the day it is planned to go.`, 'ok');
        changed();
        await reload();
      } catch (error) { toastError(error); }
    };
    const remove = async () => {
      if (!window.confirm(`Remove Rev ${issue.rev || '—'} of ${item.name}? The other revisions stay.`)) return;
      try {
        await api(`/api/submission-issues/${issue.id}`, { method: 'DELETE' });
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
