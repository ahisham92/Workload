/* The portfolio map: projects as circles, people as the threads between them.
 *
 * A circle is a project and its area is the budget still to spend, so the big
 * ones are the work still to do and the finished ones shrink away. Its colour
 * is whether the effort going in matches the work left: crowded, steady,
 * starved. A person sits at the centre of gravity of the projects they charge
 * to, which puts anybody on two of them between the two circles -- and because
 * projects that share people pull towards each other, the circles overlap and
 * that person ends up in the overlap, where set theory says they belong.
 *
 * The simulation is Verlet integration in about forty lines. Nothing is loaded
 * from a CDN here or anywhere in this app, and a layout this small does not
 * need a library to do it.
 */

(function () {
  const PROJECT_MIN_R = 16;
  const PROJECT_MAX_R = 58;
  const PERSON_R = 9;

  const STATE_TONE = {
    crowded: 'bad',
    starved: 'warn',
    steady: 'ok',
    finished: 'done',
  };
  const STATE_WORD = {
    crowded: 'more effort than its share of the work left',
    starved: 'less effort than the work left needs',
    steady: 'effort about matched to the work left',
    finished: 'nothing left to spend',
  };

  /** Area proportional to the budget left, so twice the circle is twice the work. */
  function radiusFor(value, biggest) {
    if (!biggest || value <= 0) return PROJECT_MIN_R;
    const scaled = Math.sqrt(value / biggest);
    return PROJECT_MIN_R + scaled * (PROJECT_MAX_R - PROJECT_MIN_R);
  }

  function teamColours(teams) {
    const palette = ['--series-1', '--series-2', '--series-3', '--series-4',
      '--series-5', '--series-6'];
    const out = {};
    teams.forEach((team, index) => {
      out[team.id] = `var(${palette[index % palette.length]})`;
    });
    return out;
  }

  /* ---------------------------------------------------------- simulation */

  function build(data, width, height) {
    const biggest = Math.max(
      ...data.projects.map((p) => p.remaining_mm || 0), 0.0001);
    const nodes = [];
    const byKey = new Map();

    // Phyllotaxis: the golden angle with radius growing as the square root of
    // the index puts equal area between successive points, so the circles
    // start spread evenly over the canvas instead of piled at the middle. It
    // is also deterministic -- the same portfolio looks the same way twice,
    // which matters for a picture people are meant to recognise.
    const count = Math.max(1, data.projects.length);
    const reach = Math.min(width, height) * 0.42;
    data.projects.forEach((project, index) => {
      const angle = index * 2.399963;               // the golden angle
      const distance = reach * Math.sqrt((index + 0.5) / count);
      const node = {
        kind: 'project',
        key: `p:${project.number}`,
        data: project,
        r: radiusFor(project.remaining_mm || 0, biggest),
        x: width / 2 + Math.cos(angle) * distance,
        y: height / 2 + Math.sin(angle) * distance,
      };
      node.px = node.x; node.py = node.y;
      nodes.push(node); byKey.set(node.key, node);
    });

    data.people.forEach((person, index) => {
      if (!person.projects.length) return;          // nobody charging: no thread
      const angle = index * 2.399963 + 0.7;
      const node = {
        kind: 'person',
        key: `u:${person.name}`,
        data: person,
        r: PERSON_R,
        x: width / 2 + Math.cos(angle) * 40,
        y: height / 2 + Math.sin(angle) * 40,
      };
      node.px = node.x; node.py = node.y;
      nodes.push(node); byKey.set(node.key, node);
    });

    // How many people two projects have in common: what pulls them together,
    // and so what makes their circles overlap.
    const shared = new Map();
    data.people.forEach((person) => {
      for (let i = 0; i < person.projects.length; i += 1) {
        for (let j = i + 1; j < person.projects.length; j += 1) {
          const key = [person.projects[i], person.projects[j]].sort().join('|');
          shared.set(key, (shared.get(key) || 0) + 1);
        }
      }
    });

    return { nodes, byKey, shared, width, height };
  }

  function step(sim) {
    const { nodes, byKey, shared, width, height } = sim;
    const cx = width / 2, cy = height / 2;

    for (const node of nodes) {
      if (node.fixed) continue;
      // Verlet: where it was going, damped.
      const vx = (node.x - node.px) * 0.82;
      const vy = (node.y - node.py) * 0.82;
      node.px = node.x; node.py = node.y;
      node.x += vx; node.y += vy;
    }

    // Everything drifts to the middle, so the picture stays in one piece.
    for (const node of nodes) {
      if (node.fixed) continue;
      node.x += (cx - node.x) * 0.012;
      node.y += (cy - node.y) * 0.012;
    }

    // Projects push apart, but only enough to stay distinguishable: they are
    // meant to overlap where they share people.
    const projects = nodes.filter((n) => n.kind === 'project');
    for (let i = 0; i < projects.length; i += 1) {
      for (let j = i + 1; j < projects.length; j += 1) {
        const a = projects[i], b = projects[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let distance = Math.hypot(dx, dy) || 0.01;
        const together = shared.get(
          [a.data.number, b.data.number].sort().join('|')) || 0;
        // Sharing people shortens the distance they settle at, so the circles
        // meet; sharing nobody keeps them clear of each other.
        const want = together
          ? (a.r + b.r) * (0.92 - Math.min(0.35, together * 0.12))
          : a.r + b.r + 18;
        // Pushing apart is firmer than pulling together: circles that share
        // nobody must not end up looking as though they do.
        const strength = (distance < want && !together) ? 0.22 : 0.07;
        const push = ((want - distance) / distance) * strength;
        dx *= push; dy *= push;
        if (!a.fixed) { a.x -= dx; a.y -= dy; }
        if (!b.fixed) { b.x += dx; b.y += dy; }
      }
    }

    // A person is pulled to every project they charge to, so somebody on two
    // settles between them.
    for (const node of nodes) {
      if (node.kind !== 'person' || node.fixed) continue;
      let tx = 0, ty = 0, count = 0;
      for (const number of node.data.projects) {
        const project = byKey.get(`p:${number}`);
        if (!project) continue;
        tx += project.x; ty += project.y; count += 1;
      }
      if (!count) continue;
      node.x += (tx / count - node.x) * 0.09;
      node.y += (ty / count - node.y) * 0.09;
    }

    // People do not sit on top of each other.
    const folk = nodes.filter((n) => n.kind === 'person');
    for (let i = 0; i < folk.length; i += 1) {
      for (let j = i + 1; j < folk.length; j += 1) {
        const a = folk[i], b = folk[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        const distance = Math.hypot(dx, dy) || 0.01;
        // Wide enough for the names beneath them, not just the dots.
        const want = PERSON_R * 2 + 44;
        if (distance >= want) continue;
        const push = ((want - distance) / distance) * 0.5;
        dx *= push; dy *= push;
        if (!a.fixed) { a.x -= dx; a.y -= dy; }
        if (!b.fixed) { b.x += dx; b.y += dy; }
      }
    }

    // A loose fence rather than the edge of the canvas: the view is fitted to
    // whatever the layout settles into, so pinning nodes to the border only
    // stretched the bounding box and zoomed the picture back out again.
    for (const node of nodes) {
      node.x = Math.max(-width, Math.min(width * 2, node.x));
      node.y = Math.max(-height, Math.min(height * 2, node.y));
    }
  }

  /* ------------------------------------------------------------- drawing */

  function svgEl(tag, attrs = {}, ...children) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value !== null && value !== undefined) node.setAttribute(key, value);
    }
    for (const child of children) {
      if (child === null || child === undefined) continue;
      node.appendChild(typeof child === 'string'
        ? document.createTextNode(child) : child);
    }
    return node;
  }

  function shortName(name) {
    return name.length <= 11 ? name : `${name.slice(0, 10)}…`;
  }

  function draw(sim, data, colours, onPick) {
    const { width, height } = sim;
    const svg = svgEl('svg', {
      class: 'portfolio-map', viewBox: `0 0 ${width} ${height}`,
      preserveAspectRatio: 'xMidYMid meet', role: 'img',
      'aria-label': 'Projects as circles, sized by the budget left, with the '
        + 'people who charge to them between them',
    });

    // One group holds the drawing so the fit can be a transform on it. The
    // viewBox stays put: zooming it would scale the type along with the
    // circles, and a label is meant to stay the size a label is.
    const root = svgEl('g', { class: 'map-root' });
    svg.appendChild(root);
    const threads = svgEl('g', { class: 'map-threads' });
    const circles = svgEl('g', { class: 'map-circles' });
    const folk = svgEl('g', { class: 'map-people' });
    root.appendChild(threads); root.appendChild(circles); root.appendChild(folk);
    svg.__root = root;

    for (const node of sim.nodes) {
      if (node.kind === 'project') {
        const state = node.data.state || 'steady';
        const group = svgEl('g', {
          class: `map-project map-${STATE_TONE[state] || 'ok'}`,
          'data-key': node.key, tabindex: '0',
        });
        group.appendChild(svgEl('circle', { class: 'map-disc', r: node.r }));
        // A code written across a circle too small to hold it is noise, and
        // eighteen of them are unreadable. The small ones keep their tooltip.
        if (node.r >= 26) {
          group.appendChild(svgEl('text', { class: 'map-code', y: 4 },
            node.data.number.split('-')[0]));
        }
        group.appendChild(svgEl('title', {},
          `${node.data.number} — ${node.data.name}\n`
          + `${node.data.remaining_mm} MM left of ${node.data.budget_mm}\n`
          + `${node.data.recent_hours} h recently — `
          + `${STATE_WORD[state] || ''}`));
        node.el = group;
        circles.appendChild(group);
      } else {
        const group = svgEl('g', {
          class: `map-person${node.data.shared ? ' is-shared' : ''}`,
          'data-key': node.key, tabindex: '0',
        });
        group.appendChild(svgEl('circle', {
          class: 'map-dot', r: PERSON_R,
          style: `fill:${colours[node.data.team_id] || 'var(--muted)'}`,
        }));
        group.appendChild(svgEl('text', { class: 'map-who', y: PERSON_R + 12 },
          shortName(node.data.name)));
        group.appendChild(svgEl('title', {},
          `${node.data.name} — ${node.data.grade_label}`
          + `${node.data.team_name ? `, ${node.data.team_name}` : ''}\n`
          + `on ${node.data.projects.length} project(s): `
          + node.data.projects.join(', ')));
        node.el = group;
        folk.appendChild(group);

        for (const number of node.data.projects) {
          const line = svgEl('line', { class: 'map-thread' });
          threads.appendChild(line);
          (node.threads = node.threads || []).push({ line, number });
        }
      }
      node.el.addEventListener('click', () => onPick && onPick(node));
    }
    return svg;
  }

  /** Frame the drawing on whatever it settled into, so it fills the panel.
   *
   *  A fixed viewBox leaves a small portfolio as a cluster in the middle of a
   *  lot of nothing, and a large one crammed. Following the bounding box means
   *  the picture is always as big as it can be -- eased, so it glides rather
   *  than snapping about while the layout is still moving.
   */
  function frame(sim, svg) {
    let lo = { x: Infinity, y: Infinity }, hi = { x: -Infinity, y: -Infinity };
    for (const node of sim.nodes) {
      const pad = node.kind === 'person' ? node.r + 16 : node.r;
      lo.x = Math.min(lo.x, node.x - pad); lo.y = Math.min(lo.y, node.y - pad);
      hi.x = Math.max(hi.x, node.x + pad); hi.y = Math.max(hi.y, node.y + pad);
    }
    if (!Number.isFinite(lo.x)) return;
    const margin = 14;
    const w = Math.max(60, hi.x - lo.x + margin * 2);
    const h = Math.max(60, hi.y - lo.y + margin * 2);
    // Never bigger than life: past 1:1 a handful of projects would be blown up
    // into wall art, and the circles are meant to be compared, not admired.
    const want = {
      k: Math.min(1.25, Math.min(sim.width / w, sim.height / h)),
      cx: (lo.x + hi.x) / 2,
      cy: (lo.y + hi.y) / 2,
    };
    const at = sim.view || (sim.view = { ...want });
    for (const key of ['k', 'cx', 'cy']) at[key] += (want[key] - at[key]) * 0.12;
    at.tx = sim.width / 2 - at.cx * at.k;
    at.ty = sim.height / 2 - at.cy * at.k;
    svg.__root.setAttribute(
      'transform',
      `translate(${at.tx.toFixed(1)},${at.ty.toFixed(1)}) scale(${at.k.toFixed(3)})`);
    // Type and strokes are told to ignore it, so they stay their own size.
    svg.style.setProperty('--map-k', at.k.toFixed(3));
  }

  function place(sim) {
    for (const node of sim.nodes) {
      if (!node.el) continue;
      node.el.setAttribute('transform', `translate(${node.x.toFixed(1)},${node.y.toFixed(1)})`);
      for (const thread of node.threads || []) {
        const project = sim.byKey.get(`p:${thread.number}`);
        if (!project) continue;
        thread.line.setAttribute('x1', node.x.toFixed(1));
        thread.line.setAttribute('y1', node.y.toFixed(1));
        thread.line.setAttribute('x2', project.x.toFixed(1));
        thread.line.setAttribute('y2', project.y.toFixed(1));
      }
    }
  }

  /* ------------------------------------------------------------- dragging */

  function draggable(svg, sim) {
    let held = null;
    const point = (event) => {
      const box = svg.getBoundingClientRect();
      // The viewBox follows the layout, so a screen point has to come back
      // through whatever framing is current, not through the original size.
      const view = sim.view || { k: 1, tx: 0, ty: 0 };
      const scale = sim.width / box.width;
      return {
        x: ((event.clientX - box.left) * scale - view.tx) / view.k,
        y: ((event.clientY - box.top) * scale - view.ty) / view.k,
      };
    };
    svg.addEventListener('pointerdown', (event) => {
      const group = event.target.closest('[data-key]');
      if (!group) return;
      held = sim.byKey.get(group.getAttribute('data-key'));
      if (!held) return;
      held.fixed = true;
      svg.setPointerCapture(event.pointerId);
      svg.classList.add('is-dragging');
    });
    svg.addEventListener('pointermove', (event) => {
      if (!held) return;
      const at = point(event);
      held.x = at.x; held.y = at.y;
      held.px = at.x; held.py = at.y;
    });
    const drop = () => {
      if (held) held.fixed = false;
      held = null;
      svg.classList.remove('is-dragging');
    };
    svg.addEventListener('pointerup', drop);
    svg.addEventListener('pointercancel', drop);
  }

  /* ---------------------------------------------------------------- entry */

  /** Render into ``host`` and keep the layout moving until it settles. */
  function render(host, data, { onPick } = {}) {
    if (host.__mapStop) host.__mapStop();

    const width = 900;
    const height = Math.max(380, Math.min(560, 240 + data.projects.length * 11));
    const colours = teamColours(data.teams || []);
    const sim = build(data, width, height);
    const svg = draw(sim, data, colours, onPick);

    host.replaceChildren(svg);
    draggable(svg, sim);

    // Settled after a few hundred frames, but a drag wakes it again -- which
    // is what makes it feel live rather than like a picture of a layout.
    let frames = 0;
    let running = true;
    const tick = () => {
      if (!running) return;
      const dragging = svg.classList.contains('is-dragging');
      if (dragging) frames = 0;
      if (frames < 260) {
        step(sim);
        place(sim);
        frame(sim, svg);
        frames += 1;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    host.__mapStop = () => { running = false; };
    return { colours };
  }

  window.portfolioMap = { render, STATE_TONE, STATE_WORD, teamColours };
}());
