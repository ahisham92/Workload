/* Charts, as inline SVG.
 *
 * No chart library: these are small, they have to print cleanly to PDF, and the
 * shapes needed here are few. Every chart follows the same rules — a legend
 * whenever there is more than one series, direct labels rather than a value on
 * every mark, recessive axes, a 2px surface gap between adjacent fills, and a
 * hover tooltip. Three of the light-mode series colours sit below 3:1 against
 * white, so labels and the table beneath each chart carry the meaning as well
 * as the colour does.
 */
'use strict';

const SVG_NS = 'http://www.w3.org/2000/svg';
const SERIES = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)',
  'var(--series-4)', 'var(--series-5)', 'var(--series-6)'];

/** An HTML element with a class (none when empty) and children. */
function htmlNode(tag, className, ...children) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children);
  return node;
}

/** Each series keeps its own colour, or takes the next of SERIES. */
function seriesColor(series, i) {
  return series.color || SERIES[i % SERIES.length];
}

function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** The top of an axis: the next round number at or above the data, so the
 *  four gridlines read 250, 500, 750, 1,000 rather than 295, 591, 886. */
function niceMax(value) {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10]
    .find((s) => s * power >= value * 1.0001) || 10;
  return step * power;
}

function tick(value) {
  return value >= 1000 ? Math.round(value).toLocaleString()
    : value >= 20 || Number.isInteger(value) ? String(Math.round(value))
      : value.toFixed(1);
}

/* ------------------------------------------------------------- tooltip */

let tip = null;
function tooltip() {
  if (!tip) {
    tip = document.createElement('div');
    tip.className = 'chart-tip';
    tip.hidden = true;
    document.body.append(tip);
  }
  return tip;
}

function hoverable(node, html) {
  node.addEventListener('pointerenter', (event) => {
    const t = tooltip();
    t.innerHTML = html;
    t.hidden = false;
    move(event);
  });
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerleave', () => { tooltip().hidden = true; });
  function move(event) {
    const t = tooltip();
    t.style.left = `${event.clientX + 14}px`;
    t.style.top = `${event.clientY + 14}px`;
  }
  return node;
}

/* -------------------------------------------------------------- legend */

function legend(items) {
  return htmlNode('div', 'legend', ...items.map((item) => legendItem(item.label, 'swatch', item.color)));
}

/** One legend entry; a swatch with no colour is drawn by its class. */
function legendItem(label, swatchClass, color) {
  const swatch = htmlNode('span', swatchClass);
  if (color) swatch.style.background = color;
  return htmlNode('span', 'legend-item', swatch, label);
}

function figure(title, note, ...body) {
  const fig = htmlNode('figure', 'figure');
  if (title) {
    fig.append(htmlNode('figcaption', '', htmlNode('b', '', title), ...(note ? [htmlNode('span', 'muted', note)] : [])));
  }
  fig.append(...body.filter(Boolean));
  return fig;
}

/** A bar chart's frame: the svg, capped at its natural width (a chart with few
 *  bars stretched to fill a panel blows the labels up out of all proportion to
 *  the rest of the page), and its plot with four gridlines up to ``peak``. */
function axisFrame(width, height, padLeft, padTop, plotW, plotH, peak) {
  const svg = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`, class: 'chart', role: 'img',
    preserveAspectRatio: 'xMinYMin meet',
    style: `width:100%;max-width:${width}px`,
  });
  const plot = svgEl('g', { transform: `translate(${padLeft},${padTop})` });
  for (let i = 0; i <= 4; i += 1) {
    const y = (plotH / 4) * i;
    plot.append(svgEl('line', { x1: 0, x2: plotW, y1: y, y2: y, class: 'gridline' }));
    plot.append(svgEl('text', {
      x: -8, y: y + 4, 'text-anchor': 'end', class: 'axis-label',
    }, tick(peak * (1 - i / 4))));
  }
  return { svg, plot };
}

/* ---------------------------------------------------------------- donut */

/** Part-to-whole at a glance. Six segments at most; anything beyond folds
 *  into "Other", because past that adjacent slices stop being tellable apart. */
function donut(data, { title, note, unit = 'MM', size = 190, digits = 2 } = {}) {
  const rows = data.filter((d) => (d.value || 0) > 0);
  const total = rows.reduce((sum, d) => sum + d.value, 0);
  const shown = rows.length <= 6 ? rows : rows.slice(0, 5).concat([{
    label: 'Other', value: rows.slice(5).reduce((s, d) => s + d.value, 0),
  }]);

  const radius = size / 2 - 6;
  const inner = radius * 0.62;
  const centre = size / 2;
  const svg = svgEl('svg', {
    viewBox: `0 0 ${size} ${size}`, width: size, height: size,
    role: 'img', class: 'chart chart-donut',
  });

  if (!total) {
    svg.append(svgEl('circle', {
      cx: centre, cy: centre, r: radius, fill: 'none',
      stroke: 'var(--surface-2)', 'stroke-width': radius - inner,
    }));
  }

  // Colour follows the entity, never its position: a status missing from one
  // chart must not repaint the ones that remain in the other.
  const colorOf = seriesColor;

  let angle = -Math.PI / 2;
  const gap = total ? (2 / radius) : 0;      // a 2px gap between neighbours
  shown.forEach((row, i) => {
    const sweep = (row.value / total) * Math.PI * 2;
    const from = angle + gap / 2;
    const to = angle + sweep - gap / 2;
    if (to > from) {
      const path = svgEl('path', {
        d: arc(centre, centre, radius, inner, from, to),
        fill: colorOf(row, i),
        class: 'slice',
      });
      hoverable(path, `<b>${chartEscape(row.label)}</b><br>${row.value.toFixed(digits)} ${unit}`
        + ` · ${((row.value / total) * 100).toFixed(1)}%`);
      svg.append(path);
    }
    angle += sweep;
  });

  svg.append(svgEl('text', {
    x: centre, y: centre - 2, 'text-anchor': 'middle',
    class: 'donut-total',
  }, total.toFixed(total >= 100 || digits === 0 ? 0 : 1)));
  svg.append(svgEl('text', {
    x: centre, y: centre + 14, 'text-anchor': 'middle', class: 'donut-unit',
  }, unit));

  const items = shown.map((row, i) => ({
    color: colorOf(row, i),
    label: `${row.label} — ${row.value.toFixed(digits)} (${((row.value / total) * 100 || 0).toFixed(0)}%)`,
  }));
  return figure(title, note, htmlNode('div', 'donut-wrap', svg, legend(items)));
}

function arc(cx, cy, outer, inner, from, to) {
  const large = to - from > Math.PI ? 1 : 0;
  const p = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const [x1, y1] = p(outer, from);
  const [x2, y2] = p(outer, to);
  const [x3, y3] = p(inner, to);
  const [x4, y4] = p(inner, from);
  return `M${x1} ${y1} A${outer} ${outer} 0 ${large} 1 ${x2} ${y2}`
    + ` L${x3} ${y3} A${inner} ${inner} 0 ${large} 0 ${x4} ${y4} Z`;
}

/* --------------------------------------------------------- grouped bars */

/** Compare a few measures across a few people. One axis, always. */
function groupedBars(categories, series, { title, note, unit = 'MM',
  height = 210, target = null } = {}) {
  // Sized so that, scaled into a half-width panel, the labels stay legible.
  const width = Math.max(420, categories.length * (series.length * 22 + 34));
  const padLeft = 46, padBottom = 34, padTop = 12, padRight = 10;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const peak = niceMax(Math.max(
    ...series.flatMap((s) => s.values.map((v) => v || 0)), target || 0));
  const scale = (v) => plotH - (v / peak) * plotH;
  const { svg, plot } = axisFrame(width, height, padLeft, padTop, plotW, plotH, peak);

  const groupW = plotW / categories.length;
  const barW = Math.min(30, (groupW - 14) / series.length - 2);
  categories.forEach((category, ci) => {
    const base = ci * groupW + (groupW - (barW + 2) * series.length) / 2;
    series.forEach((s, si) => {
      const value = s.values[ci] || 0;
      const y = scale(value);
      const x = base + si * (barW + 2);      // 2px surface gap between bars
      const bar = svgEl('rect', {
        x, y, width: barW, height: Math.max(1, plotH - y),
        rx: 4, fill: seriesColor(s, si), class: 'bar',
      });
      hoverable(bar, `<b>${chartEscape(category)}</b><br>${chartEscape(s.label)}: `
        + `${value.toFixed(2)} ${unit}`);
      plot.append(bar);
    });
    plot.append(svgEl('text', {
      x: ci * groupW + groupW / 2, y: plotH + 20, 'text-anchor': 'middle',
      class: 'axis-label',
    }, category));
  });

  if (target) {
    const y = scale(target);
    plot.append(svgEl('line', {
      x1: 0, x2: plotW, y1: y, y2: y, class: 'target-line',
    }));
    plot.append(svgEl('text', {
      x: plotW, y: y - 5, 'text-anchor': 'end', class: 'axis-label target-label',
    }, `capacity ${target.toFixed(1)}`));
  }

  svg.append(plot);
  return figure(title, note, htmlNode('div', 'chart-scroll', svg),
    series.length > 1 ? legend(series.map((s, i) => ({ color: seriesColor(s, i), label: s.label }))) : null);
}

/* ------------------------------------------------------ stacked columns */

/** Change over time, split by person. Part-to-whole per column. */
function stackedColumns(labels, series, { title, note, unit = 'MM',
  height = 200, target = null, targetLabel = 'capacity', wide = false } = {}) {
  // A wide chart gets room per column so a dozen months fill a full-width
  // panel; otherwise it keeps to its natural size.
  const width = Math.max(wide ? 900 : 360, labels.length * (wide ? 120 : 46));
  const padLeft = 40, padBottom = 32, padTop = 12, padRight = 8;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const totals = labels.map((_l, i) =>
    series.reduce((sum, s) => sum + (s.values[i] || 0), 0));
  const targets = Array.isArray(target) ? target : labels.map(() => target);
  const peak = niceMax(Math.max(...totals, ...targets.map((t) => t || 0)));
  const { svg, plot } = axisFrame(width, height, padLeft, padTop, plotW, plotH, peak);

  const slot = plotW / labels.length;
  const barW = Math.min(wide ? 48 : 28, slot - 10);
  labels.forEach((label, i) => {
    let bottom = plotH;
    series.forEach((s, si) => {
      const value = s.values[i] || 0;
      if (!value) return;
      const barH = (value / peak) * plotH;
      const y = bottom - barH;
      const rect = svgEl('rect', {
        x: i * slot + (slot - barW) / 2, y, width: barW,
        height: Math.max(1, barH - 2),      // 2px gap between segments
        rx: 2, fill: seriesColor(s, si), class: 'bar',
      });
      hoverable(rect, `<b>${chartEscape(label)}</b><br>${chartEscape(s.label)}: `
        + `${value.toFixed(2)} ${unit}`);
      plot.append(rect);
      bottom -= barH;
    });
    if (i % Math.ceil(labels.length / 12) === 0 || labels.length <= 12) {
      plot.append(svgEl('text', {
        x: i * slot + slot / 2, y: plotH + 18, 'text-anchor': 'middle',
        class: 'axis-label',
      }, label));
    }
  });
  // The capacity each column is measured against: one step per column, so a
  // month with less capacity shows it rather than being averaged away.
  if (targets.some((t) => t)) {
    let d = '';
    targets.forEach((t, i) => {
      if (!t) return;
      const y = plotH - (t / peak) * plotH;
      d += `${d ? 'L' : 'M'}${i * slot} ${y} L${(i + 1) * slot} ${y} `;
    });
    plot.append(svgEl('path', { d, class: 'target-line', fill: 'none' }));
  }
  svg.append(plot);
  const box = legend(series.map((s, i) => ({ color: seriesColor(s, i), label: s.label })));
  if (targets.some((t) => t)) box.append(legendItem(targetLabel, 'swatch swatch-line'));
  return figure(title, note, htmlNode('div', 'chart-scroll', svg), box);
}

/* ------------------------------------------------------------ sparkline */

/** A month-by-month trend small enough to sit inside a card. The dashed line
 *  is the capacity; the last point is labelled, the rest is shape. */
function sparkline(values, { labels = [], target = null, unit = 'h',
  width = 220, height = 46, color = 'var(--series-1)' } = {}) {
  const svg = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`, class: 'sparkline', role: 'img',
    preserveAspectRatio: 'none',
  });
  const points = values.map((v) => v || 0);
  if (points.length < 2) return svg;
  const peak = Math.max(...points, target || 0, 1) * 1.08;
  const step = width / (points.length - 1);
  const y = (v) => height - 3 - (v / peak) * (height - 6);
  const line = points.map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  svg.append(svgEl('path', {
    d: `${line} L${width} ${height} L0 ${height} Z`, class: 'spark-area', fill: color,
  }));
  if (target) {
    svg.append(svgEl('line', {
      x1: 0, x2: width, y1: y(target), y2: y(target), class: 'spark-target',
    }));
  }
  svg.append(svgEl('path', { d: line, class: 'spark-line', stroke: color }));
  points.forEach((v, i) => {
    const dot = svgEl('circle', {
      cx: i * step, cy: y(v), r: i === points.length - 1 ? 3 : 6,
      class: i === points.length - 1 ? 'spark-dot' : 'spark-hit', fill: color,
    });
    hoverable(dot, `<b>${chartEscape(labels[i] || '')}</b><br>${v.toLocaleString()} ${unit}`
      + (target ? ` · ${Math.round((v / target) * 100)}% of capacity` : ''));
    svg.append(dot);
  });
  return svg;
}

/* ------------------------------------------------------------ formation */

/** The team laid out on a plane seen in perspective: a row per rank, the most
 *  senior at the back, and a lane per team across it. Each person is a node
 *  whose ring is how much of their capacity they are using; teammates are
 *  joined, so each team reads as its own shape.
 *
 *  rows:   [{ label, nodes: [{ id, name, initials, color, value, tone, group, caption, tip }] }]
 *  groups: [{ id, label }], left to right; a node with no group gets a lane of its own.
 */
function formation(rows, { groups = [], onPick = null } = {}) {
  const R = Math.max(rows.length, 1);
  const W = 1000;
  const H = 150 + R * 92;
  const cx = W / 2;
  const back = 26;                 // where the far edge of the plane sits
  const front = H - 48;            // and the near edge
  const far = 1.75;                // how much further away the far edge is
  const horizon = (back - front / far) / (1 - 1 / far);
  const depth = (v) => 1 + (1 - v) * (far - 1);  // v: 0 back .. 1 front
  const at = (u, v) => {
    const z = depth(v);
    return [cx + (u * 450) / z, horizon + (front - horizon) / z];
  };
  // Room on both sides for the longest row name, which sits off the plane's
  // left edge; both sides so the plane stays in the middle.
  const longest = Math.max(0, ...rows.map((row) => String(row.label || '').length));
  const pad = Math.max(0, Math.ceil(longest * 10 + 24 - (cx - 450)));
  const svg = svgEl('svg', {
    viewBox: `${-pad} 0 ${W + 2 * pad} ${H}`, class: 'chart formation', role: 'img',
    preserveAspectRatio: 'xMidYMid meet',
  });

  // Lanes: one per team, plus one for anyone not in a team yet.
  const lanes = groups.map((g) => ({ id: g.id, label: g.label }));
  if (rows.some((row) => row.nodes.some((n) => !lanes.some((l) => l.id === n.group)))) {
    lanes.push({ id: null, label: lanes.length ? 'No team' : '' });
  }
  const L = Math.max(lanes.length, 1);
  const laneOf = (node) => Math.max(0, lanes.findIndex((l) => l.id === (
    lanes.some((x) => x.id === node.group) ? node.group : null)));
  const laneCentre = (i) => -1 + (2 * i + 1) / L;

  // The plane, its grid, and the lanes and rows marked on it.
  const corners = [at(-1, 0), at(1, 0), at(1, 1), at(-1, 1)];
  svg.append(svgEl('polygon', {
    points: corners.map((p) => p.join(',')).join(' '), class: 'plane',
  }));
  const grid = svgEl('g', { class: 'plane-grid' });
  for (let i = -6; i <= 6; i += 1) {
    const [x1, y1] = at(i / 6, 0);
    const [x2, y2] = at(i / 6, 1);
    grid.append(svgEl('line', { x1, y1, x2, y2 }));
  }
  for (let k = 0; k <= 10; k += 1) {
    const [x1, y1] = at(-1, k / 10);
    const [x2, y2] = at(1, k / 10);
    grid.append(svgEl('line', { x1, y1, x2, y2 }));
  }
  svg.append(grid);
  for (let i = 1; i < L; i += 1) {
    const u = -1 + (2 * i) / L;
    const [x1, y1] = at(u, 0);
    const [x2, y2] = at(u, 1);
    svg.append(svgEl('line', { x1, y1, x2, y2, class: 'lane-line' }));
  }
  lanes.forEach((lane, i) => {
    if (!lane.label) return;
    const [x, y] = at(laneCentre(i), 1);
    svg.append(svgEl('text', { x, y: y + 26, 'text-anchor': 'middle', class: 'lane-label' },
      lane.label));
  });

  // Rows evenly spaced on the screen rather than on the plane, so the far
  // rows, which perspective squeezes together, still have room for names.
  const yOf = (v) => horizon + (front - horizon) / depth(v);
  const vAt = (y) => 1 - ((front - horizon) / (y - horizon) - 1) / (far - 1);
  const vOf = (r) => (R === 1 ? 0.6
    : vAt(yOf(0.1) + ((yOf(0.86) - yOf(0.1)) * r) / (R - 1)));
  const placed = [];
  rows.forEach((row, r) => {
    const v = vOf(r);
    const [lx, ly] = at(-1, v);
    if (row.label) {
      svg.append(svgEl('text', {
        x: lx - 14, y: ly + 4, 'text-anchor': 'end', class: 'row-label',
      }, row.label));
    }
    lanes.forEach((_lane, li) => {
      const here = row.nodes.filter((n) => laneOf(n) === li);
      const width = 2 / L;
      const gap = Math.min(0.34, (width * 0.82) / Math.max(here.length, 1));
      here.forEach((node, i) => {
        const u = laneCentre(li) + (i - (here.length - 1) / 2) * gap;
        const [x, y] = at(u, v);
        placed.push({ node, x, y, scale: 1 / depth(v) });
      });
    });
  });

  // Teammates joined, nearest first, before the people go on top.
  const links = svgEl('g', { class: 'links' });
  lanes.forEach((lane) => {
    if (lane.id === null) return;
    const members = placed.filter((p) => p.node.group === lane.id)
      .sort((a, b) => a.y - b.y || a.x - b.x);
    for (let i = 1; i < members.length; i += 1) {
      const me = members[i];
      const near = members.slice(0, i).reduce((best, p) => (
        Math.hypot(p.x - me.x, p.y - me.y) < Math.hypot(best.x - me.x, best.y - me.y)
          ? p : best));
      links.append(svgEl('line', { x1: near.x, y1: near.y, x2: me.x, y2: me.y, class: 'link' }));
    }
  });
  svg.append(links);

  const people = svgEl('g', {});
  placed.sort((a, b) => a.y - b.y).forEach(({ node, x, y, scale }) => {
    const r = 20 * scale + 9;
    const g = svgEl('g', {
      class: `person${onPick ? ' pickable' : ''}`,
      transform: `translate(${x.toFixed(1)},${y.toFixed(1)})`,
      tabindex: onPick ? 0 : null,
      role: onPick ? 'button' : null,
      'aria-label': node.name,
    });
    g.append(svgEl('ellipse', { cx: 0, cy: r + 4, rx: r * 1.1, ry: r * 0.3, class: 'shadow' }));
    const ring = r + 4;
    const length = 2 * Math.PI * ring;
    const share = Math.max(0, Math.min(1, node.value || 0));
    g.append(svgEl('circle', { r: ring, class: 'ring-track' }));
    g.append(svgEl('circle', {
      r: ring, class: `ring ring-${node.tone || 'none'}`,
      'stroke-dasharray': `${(share * length).toFixed(1)} ${length.toFixed(1)}`,
      transform: 'rotate(-90)',
    }));
    g.append(svgEl('circle', { r, fill: node.color, class: 'disc' }));
    g.append(svgEl('text', {
      y: r * 0.34, 'text-anchor': 'middle', class: 'initials',
      style: `font-size:${(r * 0.85).toFixed(1)}px`,
    }, node.initials));
    g.append(svgEl('text', { y: ring + 16, 'text-anchor': 'middle', class: 'person-name' },
      node.name));
    if (node.caption) {
      g.append(svgEl('text', {
        y: ring + 30, 'text-anchor': 'middle', class: `person-caption v-${node.tone || ''}`,
      }, node.caption));
    }
    if (node.tip) hoverable(g, node.tip);
    if (onPick) {
      g.addEventListener('click', () => onPick(node));
      g.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onPick(node); }
      });
    }
    people.append(g);
  });
  svg.append(people);
  return htmlNode('div', 'formation-wrap', htmlNode('div', 'chart-scroll', svg));
}

/* --------------------------------------------------------- budget bars */

/** Spend against budget, one project to a row: the track is the budget, the
 *  bar what has been booked, the tick what has been earned. A bar past its
 *  tick is costing more than it earns. */
function budgetBars(rows, { title, note, unit = 'MM' } = {}) {
  const box = htmlNode('div', 'budget-bars');
  const peak = Math.max(1, ...rows.map((r) => Math.max(r.budget || 0, r.actual || 0)));
  for (const row of rows) {
    const name = htmlNode('span', 'budget-name', row.label);
    name.title = row.title || row.label;
    const budget = htmlNode('span', 'budget-budget');
    budget.style.width = `${((row.budget || 0) / peak) * 100}%`;
    const over = (row.actual || 0) > (row.earned || 0) + 0.005;
    const actual = htmlNode('span', `budget-actual${over ? ' over' : ''}`);
    actual.style.width = `${Math.max(0.5, ((row.actual || 0) / peak) * 100)}%`;
    const earned = htmlNode('span', 'budget-earned');
    earned.style.left = `${((row.earned || 0) / peak) * 100}%`;
    const track = htmlNode('span', 'budget-track', budget, actual, earned);
    hoverable(track, `<b>${chartEscape(row.title || row.label)}</b><br>`
      + `Budget ${(row.budget || 0).toFixed(2)} ${unit}<br>`
      + `Booked ${(row.actual || 0).toFixed(2)} ${unit}<br>`
      + `Earned ${(row.earned || 0).toFixed(2)} ${unit}`);
    const value = htmlNode('span', 'budget-value', row.budget
      ? `${Math.round(((row.actual || 0) / row.budget) * 100)}% spent` : '—');
    box.append(htmlNode('div', 'budget-row', name, track, value));
  }
  const key = legend([
    { color: 'var(--surface-2)', label: 'budget' },
    { color: 'var(--series-1)', label: 'booked, at or under earned' },
    { color: 'var(--series-2)', label: 'booked, past earned' },
  ]);
  key.append(legendItem('earned', 'swatch swatch-tick'));
  return figure(title, note, box, key);
}

/* --------------------------------------------------------- score bars */

/** One measure across a few people: emphasis, not eight hues. */
function scoreBars(rows, { title, note, max = 100, suffix = '' } = {}) {
  const box = htmlNode('div', 'score-bars');
  const peak = Math.max(max, ...rows.map((r) => r.value || 0));
  for (const row of rows) {
    const fill = document.createElement('span');
    fill.style.width = `${Math.max(1, ((row.value || 0) / peak) * 100)}%`;
    fill.style.background = row.color || 'var(--series-1)';
    box.append(htmlNode('div', 'score-row', htmlNode('span', 'score-name', row.label),
      htmlNode('span', 'score-track', fill),
      htmlNode('span', 'score-value', `${(row.value || 0).toFixed(1)}${suffix}`)));
  }
  return figure(title, note, box);
}

function chartEscape(text) {
  return String(text).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

window.charts = {
  donut, groupedBars, stackedColumns, scoreBars, sparkline, budgetBars, formation, escape: chartEscape,
};
