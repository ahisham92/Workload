/* Selecao+ — the planning board.
 *
 * The Planner's "Next days" laid out as a board: one column per project, each
 * person sitting on the work they have lined up, sized by the hours. Drag a
 * person onto somebody else (or tap them and choose) to hand over part of
 * that work; every load on the board shows what it does before anything is
 * kept. Same moves, same server sums as the list below it -- this is only
 * another way to make them.
 *
 * Built on planner.js's `plan`, tryMoves, commitMoves, suggestMoves and loadTone,
 * and app.js's helpers.
 */
'use strict';

(function () {
  const board = {
    picked: null,    // { person, item } chosen by a tap, waiting for a target
    scroll: 0,       // where the columns were scrolled to, kept across redraws
  };
  const MAX_COLUMNS = 10;
  const SHARES = [[0.25, '¼'], [0.5, '½'], [0.75, '¾'], [1, 'All']];

  const pct = (v) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);

  function shown(data) {
    return data.people.filter((p) => plan.team === 'all' || (p.team_id || '__none__') === plan.team);
  }

  /** What dragging this person off this piece of work hands over. */
  function moveFor(person, item, to, share = 0.5) {
    if (item.project && item.pace_after > 0) {
      return { kind: 'project', project: item.project, from: person.name, to, share };
    }
    const taskId = item.key.startsWith('task:') ? Number(item.key.split(':')[1])
      : (item.tasks || [])[0];
    const task = (plan.data.open_tasks || []).find((t) => t.id === taskId
      && t.assignees.includes(person.name));
    return task ? { kind: 'task', task_id: task.id, from: person.name, to } : null;
  }

  async function hand(person, item, to) {
    board.picked = null;
    if (to === person.name) { renderAgain(); return; }
    const move = moveFor(person, item, to);
    if (!move) { toast('Nothing here can be handed over.'); renderAgain(); return; }
    await tryMoves(plan.moves.concat([move]));
  }

  function renderAgain() {
    if (plan.data && typeof renderPlanner === 'function') renderPlanner();
  }

  /* --------------------------------------------------------- drawing */

  function avatar(name, size) {
    return el('span', { class: 'bd-avatar', style: `--pc:${engineerColor(name)};--sz:${size}px` },
      initials(name));
  }

  function personChip(p) {
    const before = p.before.load; const after = p.after.load;
    const moved = plan.moves.length && Math.abs((before || 0) - (after || 0)) > 0.005;
    const fill = Math.min(1, after || 0);
    const target = board.picked && board.picked.person.name !== p.name;
    return el('div', {
      class: `bd-person ${target ? 'is-target' : ''}`,
      'data-drop-person': p.name,
      role: target ? 'button' : null,
      tabindex: target ? '0' : null,
      onclick: target ? () => hand(board.picked.person, board.picked.item, p.name) : null,
    },
    el('span', { class: `bd-ring t-${loadTone(after)}`, style: `--fill:${(fill * 360).toFixed(0)}deg` },
      avatar(p.name, 40)),
    el('span', { class: 'bd-person-name' }, p.name),
    el('span', { class: `bd-person-load v-${loadTone(after)}` },
      moved ? `${pct(before)} → ${pct(after)}` : pct(after)));
  }

  function token(person, item, maxHours) {
    const h = item.hours_after;
    const was = item.hours_before;
    const size = Math.round(30 + 26 * Math.sqrt(Math.min(1, Math.max(h, was) / (maxHours || 1))));
    const delta = plan.moves.length ? h - was : 0;
    const gone = h < 0.05 && was > 0.05;
    const picked = board.picked && board.picked.person.name === person.name
      && board.picked.item.key === item.key;
    const node = el('div', {
      class: `bd-token ${gone ? 'is-gone' : ''} ${picked ? 'is-picked' : ''} ${Math.abs(delta) > 0.05 ? 'is-changed' : ''}`,
      'data-drop-person': person.name,
      role: 'button', tabindex: '0',
      'aria-label': `${person.name}, ${fmt.hours(h)} hours on ${item.project || item.name}. Tap to hand some of it over.`,
      title: `${person.name}: ${fmt.hours(h)} h on ${item.name}`,
    },
    avatar(person.name, size),
    el('span', { class: 'bd-token-name' }, person.name),
    el('span', { class: `bd-token-hours v-${loadTone(person.after.load)}` },
      `${fmt.hours(h)} h`,
      Math.abs(delta) > 0.05 ? el('em', {}, ` ${delta > 0 ? '+' : '−'}${fmt.hours(Math.abs(delta))}`) : null));
    if (!gone) draggable(node, person, item);
    return node;
  }

  function columns(data, people) {
    const byKey = new Map();
    for (const person of people) {
      for (const item of person.items) {
        if (Math.max(item.hours_after, item.hours_before) < 0.4) continue;
        const key = item.project || item.key;
        const col = byKey.get(key) || { key, project: item.project, name: item.name, hours: 0, was: 0, sits: [] };
        col.hours += item.hours_after;
        col.was += item.hours_before;
        col.sits.push({ person, item });
        byKey.set(key, col);
      }
    }
    const cols = [...byKey.values()].sort((a, b) => b.hours - a.hours);
    return cols.slice(0, MAX_COLUMNS).map((c) => ({
      ...c, sits: c.sits.sort((a, b) => b.item.hours_after - a.item.hours_after),
    }));
  }

  function moveChip(move, index) {
    const named = ((plan.data && plan.data.moves) || [])[index] || {};
    if (move.kind === 'task' && !move.name) move = { ...move, name: named.name };
    const label = move.kind === 'task'
      ? `${move.from} → ${move.to}: task ${move.name || ''}`
      : `${move.from} → ${move.to}: ${move.project}`;
    return el('div', { class: 'bd-move' },
      el('span', { class: 'bd-move-text' }, label),
      move.kind === 'project'
        ? el('span', { class: 'bd-shares', role: 'group', 'aria-label': 'How much of it' },
          SHARES.map(([share, text]) => el('button', {
            type: 'button',
            class: `bd-share ${Math.abs((move.share || 1) - share) < 0.01 ? 'is-active' : ''}`,
            onclick: () => tryMoves(plan.moves.map((m, i) => (i === index ? { ...m, share } : m))),
          }, text)))
        : null,
      el('button', { type: 'button', class: 'bd-move-x', 'aria-label': 'Undo this move',
        onclick: () => tryMoves(plan.moves.filter((_, i) => i !== index)) }, '✕'));
  }

  function render(data) {
    if (!data || !data.people) return null;
    const people = shown(data);
    const cols = columns(data, people);
    const maxHours = Math.max(1, ...cols.flatMap((c) => c.sits.map((s) => Math.max(s.item.hours_after, s.item.hours_before))));
    const s = data.summary;
    const trying = plan.moves.length > 0;
    const effect = trying
      ? el('div', { class: 'bd-effect' },
        el('span', {}, 'Over a full load ', el('b', { class: s.over_after < s.over_before ? 'v-ok' : s.over_after > s.over_before ? 'v-bad' : '' },
          `${s.over_before} → ${s.over_after}`)),
        el('span', {}, 'Busiest ', el('b', { class: `v-${loadTone(s.peak_after)}` },
          `${pct(s.peak_before)} → ${pct(s.peak_after)}`)),
        el('span', {}, 'With room ', el('b', {}, `${s.room_before} → ${s.room_after}`)))
      : null;

    const lanes = el('div', { class: 'bd-cols' },
      cols.length ? cols.map((col) => el('div', { class: 'bd-col' },
        el('div', { class: 'bd-col-head', title: col.name },
          el('span', { class: 'code' }, col.project || 'Task'),
          el('span', { class: 'bd-col-name' }, col.name !== col.project ? col.name : ''),
          el('span', { class: 'bd-col-hours' }, `${fmt.hours(col.hours)} h`,
            trying && Math.abs(col.hours - col.was) > 0.05 ? el('em', {}, ` was ${fmt.hours(col.was)}`) : null)),
        el('div', { class: 'bd-col-body' }, col.sits.map((sit) => token(sit.person, sit.item, maxHours)))))
        : el('div', { class: 'empty' }, 'Nothing lined up for these days.'));
    lanes.addEventListener('scroll', () => { board.scroll = lanes.scrollLeft; }, { passive: true });
    requestAnimationFrame(() => { lanes.scrollLeft = board.scroll; });

    const picked = board.picked;
    return el('section', { class: 'panel bd' },
      el('div', { class: 'panel-head' },
        el('div', {},
          el('h3', {}, 'Planning board'),
          el('p', { class: 'muted' },
            'Each column is a piece of work for the days chosen, each person sits on what they have lined up, '
            + 'bigger for more hours. Drag someone onto another person to hand over half of it, or tap them '
            + 'and choose who. Nothing changes until you keep the moves.')),
        el('div', { class: 'row-actions' },
          el('button', { class: 'btn', type: 'button', onclick: suggestMoves }, 'Suggest moves'),
          trying ? el('button', { class: 'btn', type: 'button', onclick: () => tryMoves([]) }, 'Clear') : null,
          trying ? el('button', { class: 'btn btn-primary', type: 'button', onclick: commitMoves },
            `Keep ${plan.moves.length} move${plan.moves.length === 1 ? '' : 's'}`) : null)),
      el('div', { class: 'bd-people' }, people.map(personChip)),
      picked
        ? el('div', { class: 'msg msg-info bd-prompt' },
          el('span', {}, `Hand some of ${picked.person.name}'s ${picked.item.project || picked.item.name} to who? Tap a person above.`),
          el('button', { class: 'btn btn-sm', type: 'button', onclick: () => { board.picked = null; renderAgain(); } }, 'Cancel'))
        : null,
      effect,
      trying ? el('div', { class: 'bd-moves' }, plan.moves.map(moveChip)) : null,
      lanes);
  }

  /* ------------------------------------------------------- dragging */

  function draggable(node, person, item) {
    let start = null;
    let ghost = null;
    let over = null;

    const clear = () => {
      if (ghost) ghost.remove();
      ghost = null;
      if (over) over.classList.remove('is-over');
      over = null;
      document.body.classList.remove('bd-dragging');
    };

    node.addEventListener('pointerdown', (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      start = { x: e.clientX, y: e.clientY, id: e.pointerId, dragging: false };
    });
    node.addEventListener('pointermove', (e) => {
      if (!start || e.pointerId !== start.id) return;
      const dx = e.clientX - start.x; const dy = e.clientY - start.y;
      if (!start.dragging) {
        if (Math.hypot(dx, dy) < 8) return;
        start.dragging = true;
        try { node.setPointerCapture(e.pointerId); } catch (err) { /* gone */ }
        ghost = el('div', { class: 'bd-ghost' }, avatar(person.name, 48),
          el('span', {}, `${person.name} · ${item.project || item.name}`));
        document.body.append(ghost);
        document.body.classList.add('bd-dragging');
      }
      e.preventDefault();
      ghost.style.transform = `translate(${e.clientX - 24}px, ${e.clientY - 24}px)`;
      ghost.hidden = true;
      const under = document.elementFromPoint(e.clientX, e.clientY);
      ghost.hidden = false;
      const target = under && under.closest('[data-drop-person]');
      const valid = target && target.dataset.dropPerson !== person.name ? target : null;
      if (valid !== over) {
        if (over) over.classList.remove('is-over');
        over = valid;
        if (over) over.classList.add('is-over');
      }
    });
    const finish = (e) => {
      if (!start || e.pointerId !== start.id) return;
      const was = start; start = null;
      const target = over ? over.dataset.dropPerson : null;
      clear();
      if (!was.dragging) {
        board.picked = { person, item };
        renderAgain();
        const strip = document.querySelector('.bd-people');
        if (strip && strip.scrollIntoView) strip.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        return;
      }
      if (target) hand(person, item, target);
    };
    node.addEventListener('pointerup', finish);
    node.addEventListener('pointercancel', () => { start = null; clear(); });
    node.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        board.picked = { person, item };
        renderAgain();
      }
    });
  }

  window.board = { render };
}());
