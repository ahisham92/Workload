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
  const box = document.createElement('div');
  box.className = 'legend';
  for (const item of items) {
    const entry = document.createElement('span');
    entry.className = 'legend-item';
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = item.color;
    entry.append(swatch, document.createTextNode(item.label));
    box.append(entry);
  }
  return box;
}

function figure(title, note, ...body) {
  const fig = document.createElement('figure');
  fig.className = 'figure';
  if (title) {
    const caption = document.createElement('figcaption');
    caption.append(Object.assign(document.createElement('b'), { textContent: title }));
    if (note) {
      const small = document.createElement('span');
      small.className = 'muted';
      small.textContent = note;
      caption.append(small);
    }
    fig.append(caption);
  }
  fig.append(...body.filter(Boolean));
  return fig;
}

/* ---------------------------------------------------------------- donut */

/** Part-to-whole at a glance. Six segments at most; anything beyond folds
 *  into "Other", because past that adjacent slices stop being tellable apart. */
function donut(data, { title, note, unit = 'MM', size = 190 } = {}) {
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
  const colorOf = (row, i) => row.color || SERIES[i % SERIES.length];

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
      hoverable(path, `<b>${escape(row.label)}</b><br>${row.value.toFixed(2)} ${unit}`
        + ` · ${((row.value / total) * 100).toFixed(1)}%`);
      svg.append(path);
    }
    angle += sweep;
  });

  svg.append(svgEl('text', {
    x: centre, y: centre - 2, 'text-anchor': 'middle',
    class: 'donut-total',
  }, total.toFixed(total >= 100 ? 0 : 1)));
  svg.append(svgEl('text', {
    x: centre, y: centre + 14, 'text-anchor': 'middle', class: 'donut-unit',
  }, unit));

  const items = shown.map((row, i) => ({
    color: colorOf(row, i),
    label: `${row.label} — ${row.value.toFixed(2)} (${((row.value / total) * 100 || 0).toFixed(0)}%)`,
  }));
  return figure(title, note, wrap('donut-wrap', svg, legend(items)));
}

function wrap(className, ...nodes) {
  const box = document.createElement('div');
  box.className = className;
  box.append(...nodes);
  return box;
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
  const width = Math.max(420, categories.length * (series.length * 40 + 56));
  const padLeft = 46, padBottom = 34, padTop = 12, padRight = 10;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const peak = Math.max(
    ...series.flatMap((s) => s.values.map((v) => v || 0)), target || 0, 1);
  const scale = (v) => plotH - (v / peak) * plotH;

  // Capped at its natural width: a chart with few bars stretched to fill a
  // panel blows the labels up out of all proportion to the rest of the page.
  const svg = svgEl('svg', {
    viewBox: `0 0 ${width} ${height}`, class: 'chart', role: 'img',
    preserveAspectRatio: 'xMinYMin meet',
    style: `width:100%;max-width:${width}px`,
  });
  const plot = svgEl('g', { transform: `translate(${padLeft},${padTop})` });

  for (let i = 0; i <= 4; i += 1) {
    const y = (plotH / 4) * i;
    plot.append(svgEl('line', {
      x1: 0, x2: plotW, y1: y, y2: y, class: 'gridline',
    }));
    plot.append(svgEl('text', {
      x: -8, y: y + 4, 'text-anchor': 'end', class: 'axis-label',
    }, (peak * (1 - i / 4)).toFixed(peak >= 20 ? 0 : 1)));
  }

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
        rx: 4, fill: s.color || SERIES[si % SERIES.length], class: 'bar',
      });
      hoverable(bar, `<b>${escape(category)}</b><br>${escape(s.label)}: `
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
      x: plotW, y: y - 5, 'text-anchor': 'end', class: 'axis-label',
    }, `capacity ${target.toFixed(1)}`));
  }

  svg.append(plot);
  return figure(title, note, wrap('chart-scroll', svg),
    series.length > 1
      ? legend(series.map((s, i) => ({
          color: s.color || SERIES[i % SERIES.length], label: s.label })))
      : null);
}

/* ------------------------------------------------------ stacked columns */

/** Change over time, split by person. Part-to-whole per column. */
function stackedColumns(labels, series, { title, note, unit = 'MM',
  height = 200 } = {}) {
  const width = Math.max(360, labels.length * 46);
  const padLeft = 40, padBottom = 32, padTop = 12, padRight = 8;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const totals = labels.map((_l, i) =>
    series.reduce((sum, s) => sum + (s.values[i] || 0), 0));
  const peak = Math.max(...totals, 1);

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
    }, (peak * (1 - i / 4)).toFixed(0)));
  }

  const slot = plotW / labels.length;
  const barW = Math.min(28, slot - 10);
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
        rx: 2, fill: s.color || SERIES[si % SERIES.length], class: 'bar',
      });
      hoverable(rect, `<b>${escape(label)}</b><br>${escape(s.label)}: `
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
  svg.append(plot);
  return figure(title, note, wrap('chart-scroll', svg),
    legend(series.map((s, i) => ({
      color: s.color || SERIES[i % SERIES.length], label: s.label }))));
}

/* --------------------------------------------------------- score bars */

/** One measure across a few people: emphasis, not eight hues. */
function scoreBars(rows, { title, note, max = 100, suffix = '' } = {}) {
  const box = document.createElement('div');
  box.className = 'score-bars';
  const peak = Math.max(max, ...rows.map((r) => r.value || 0));
  for (const row of rows) {
    const line = document.createElement('div');
    line.className = 'score-row';
    const name = document.createElement('span');
    name.className = 'score-name';
    name.textContent = row.label;
    const track = document.createElement('span');
    track.className = 'score-track';
    const fill = document.createElement('span');
    fill.style.width = `${Math.max(1, ((row.value || 0) / peak) * 100)}%`;
    fill.style.background = row.color || 'var(--series-1)';
    track.append(fill);
    const value = document.createElement('span');
    value.className = 'score-value';
    value.textContent = `${(row.value || 0).toFixed(1)}${suffix}`;
    line.append(name, track, value);
    box.append(line);
  }
  return figure(title, note, box);
}

function escape(text) {
  return String(text).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

window.charts = { donut, groupedBars, stackedColumns, scoreBars, legend, figure, SERIES };
