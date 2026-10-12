/* Selecao+ — the summary video.
 *
 * The Video tab turns the app's own results into a short film: our week
 * (the desks and the paper piled on them, what goes out, where the hours go,
 * whether there are people enough, the week's to-do list), how we're doing
 * (busy on real work, earned against spent, keeping up with the plan, last
 * week's hours, the jobs, the budgets), or both in one.
 *
 * The server only picks the figures (GET /api/video, workload_app/video.py).
 * Every frame is drawn here on a canvas, and the browser records it while it
 * plays (MediaRecorder): MP4 on an iPhone and in most browsers, WebM where
 * MP4 is not offered. Nothing is uploaded; the file is made on the device.
 *
 * Built on common.js's make, setChildren and $, and app.js's api and toast.
 */
(function () {
  'use strict';

  const host = document.getElementById('video-body');
  if (!host) return;

  /* -- what can be made ------------------------------------------------------ */

  const PARTS = [
    { key: 'week', title: 'Our week', say: 'Who has what on their desk, what goes out, where the hours go and what to do.' },
    { key: 'doing', title: 'How we\'re doing', say: 'Busy on real work, earned against spent, the plan, last week and the jobs.' },
    { key: 'both', title: 'Both', say: 'The week first, then how the year is going, in one video.' },
  ];
  const SHAPES = [
    { key: 'tall', title: 'Tall, for a phone', w: 1080, h: 1920 },
    { key: 'wide', title: 'Wide, for a screen', w: 1920, h: 1080 },
  ];
  const KEEP = 'selecao.video';
  const read = () => { try { return JSON.parse(localStorage.getItem(KEEP) || '{}'); } catch (_) { return {}; } };
  const keep = () => { try { localStorage.setItem(KEEP, JSON.stringify({ part: vid.part, shape: vid.shape })); } catch (_) { /* not kept */ } };

  const saved = read();
  const vid = {
    data: null, loadedAt: 0, loading: null,
    part: PARTS.some((p) => p.key === saved.part) ? saved.part : 'both',
    shape: SHAPES.some((s) => s.key === saved.shape) ? saved.shape : 'tall',
    scenes: [], total: 0,
    playing: false, recorder: null, frame: 0, url: null, file: null,
  };

  /* -- colours and type ------------------------------------------------------- */

  const C = {
    navy: '#101B2D', navy2: '#1a2a45', deep: '#0b1322',
    ink: '#ffffff', soft: 'rgba(255,255,255,.74)', dim: 'rgba(255,255,255,.46)',
    line: 'rgba(255,255,255,.16)', card: 'rgba(255,255,255,.07)', card2: 'rgba(255,255,255,.12)',
    star: '#FF5A1F', blue: '#4f9cf0', green: '#33c48d', amber: '#f2b33d', red: '#f0605d',
    violet: '#9b8cff', teal: '#2fc2b4', paper: '#f4f1ea', paper2: '#e3ddd0', wood: '#c9a27a', wood2: '#a8825c',
  };
  const PEOPLE = ['#4f9cf0', '#ff8a4c', '#33c48d', '#f2b33d', '#ef86b0', '#9b8cff', '#2fc2b4', '#e0e36a'];
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
  const font = (size, weight = 400) => `${weight} ${Math.round(size)}px ${FONT}`;
  const TONE = { bad: C.red, warn: C.amber, ok: C.green, room: C.blue };

  /* -- small helpers ----------------------------------------------------------- */

  const clamp01 = (t) => Math.max(0, Math.min(1, t));
  const seg = (t, a, b) => clamp01((t - a) / (b - a));
  const ease = (t) => 1 - Math.pow(1 - clamp01(t), 3);
  const pop = (t) => {
    const x = clamp01(t); const c = 1.70158;
    return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2);
  };
  const lerp = (a, b, t) => a + (b - a) * t;
  const num = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v));
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const LONG_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December'];
  const day = (iso) => {
    if (!iso) return '';
    const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number);
    return `${d} ${MONTHS[m - 1]}`;
  };
  const dayYear = (iso) => (iso ? `${day(iso)} ${String(iso).slice(0, 4)}` : '');
  const monthOf = (iso) => (iso ? MONTHS[Number(String(iso).slice(5, 7)) - 1] : '');
  const longMonth = (iso) => (iso ? LONG_MONTHS[Number(String(iso).slice(5, 7)) - 1] : '');
  const h = (v) => `${Math.round(num(v) || 0).toLocaleString()} h`;
  const pct = (v) => `${Math.round((num(v) || 0) * 100)}%`;
  const mm = (v) => `${(num(v) || 0).toFixed(1)} MM`;
  const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || `${one}s`)}`;
  const names = (list, most = 3) => {
    const shown = list.slice(0, most); const rest = list.length - shown.length;
    if (rest > 0) return `${shown.join(', ')} and ${rest} more`;
    return shown.length > 1 ? `${shown.slice(0, -1).join(', ')} and ${shown[shown.length - 1]}` : (shown[0] || '');
  };
  const initials = (name) => String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2)
    .map((w) => w[0].toUpperCase()).join('');
  const busyTone = (u) => (u === null ? C.dim : u >= 0.85 && u <= 1.05 ? C.green : u >= 0.7 && u < 0.85 ? C.amber : C.red);
  const loadTone = (l) => (l === null ? C.dim : l > 1.05 ? C.red : l > 0.95 ? C.amber : l >= 0.75 ? C.green : C.blue);
  const cpiTone = (c) => (c === null ? C.dim : c >= 1 ? C.green : c >= 0.9 ? C.amber : C.red);

  function personColour(name) {
    const team = ((vid.data && vid.data.week.desks) || []).map((d) => d.name);
    const at = team.indexOf(name);
    let i = at;
    if (at < 0) { i = 0; for (const ch of String(name)) i = (i * 31 + ch.charCodeAt(0)) >>> 0; }
    return PEOPLE[i % PEOPLE.length];
  }

  function roundRect(ctx, x, y, w, hh, r) {
    const rr = Math.max(0, Math.min(r, w / 2, hh / 2));
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + hh, rr);
    ctx.arcTo(x + w, y + hh, x, y + hh, rr);
    ctx.arcTo(x, y + hh, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  }
  function fillRound(ctx, x, y, w, hh, r, colour) {
    if (w <= 0 || hh <= 0) return;
    roundRect(ctx, x, y, w, hh, r); ctx.fillStyle = colour; ctx.fill();
  }

  /** Lines of text that fit a width; the last one cut with … when there are too many. */
  function wrap(ctx, text, width, most = 99) {
    const words = String(text || '').split(/\s+/).filter(Boolean);
    const lines = []; let line = '';
    for (const word of words) {
      const next = line ? `${line} ${word}` : word;
      if (ctx.measureText(next).width <= width || !line) line = next;
      else { lines.push(line); line = word; }
    }
    if (line) lines.push(line);
    if (lines.length > most) {
      const kept = lines.slice(0, most);
      let last = kept[most - 1];
      while (last && ctx.measureText(`${last}…`).width > width) last = last.slice(0, -1);
      kept[most - 1] = `${last.trimEnd()}…`;
      return kept;
    }
    return lines;
  }
  function fit(ctx, text, width) { return wrap(ctx, text, width, 1)[0] || ''; }
  function text(ctx, value, x, y, { size = 32, weight = 400, colour = C.ink, align = 'left', base = 'alphabetic' } = {}) {
    ctx.font = font(size, weight); ctx.fillStyle = colour; ctx.textAlign = align; ctx.textBaseline = base;
    ctx.fillText(value, x, y);
  }
  function para(ctx, value, x, y, width, { size = 32, weight = 400, colour = C.ink, lead = 1.25, most = 99, align = 'left' } = {}) {
    ctx.font = font(size, weight);
    const lines = wrap(ctx, value, width, most);
    ctx.fillStyle = colour; ctx.textAlign = align; ctx.textBaseline = 'alphabetic';
    lines.forEach((line, i) => ctx.fillText(line, x, y + i * size * lead));
    return lines.length * size * lead;
  }

  /* -- the logo -------------------------------------------------------------------- */

  /** The Selecao+ mark: nine dots in a pyramid and the star on top; t builds it. */
  function logo(ctx, cx, cy, size, t = 1, tile = true) {
    const k = size / 64;
    ctx.save();
    ctx.translate(cx - size / 2, cy - size / 2);
    if (tile) fillRound(ctx, 0, 0, size, size, 14 * k, C.navy);
    const dots = [[12.5, 50], [25.5, 50], [38.5, 50], [51.5, 50], [19, 38.5], [32, 38.5], [45, 38.5], [25.5, 27], [38.5, 27]];
    dots.forEach(([x, y], i) => {
      const p = pop(seg(t, i * 0.05, i * 0.05 + 0.35));
      if (p <= 0) return;
      ctx.beginPath(); ctx.arc(x * k, (y - (1 - Math.min(1, p)) * 20) * k, 3.8 * k * Math.max(0, p), 0, Math.PI * 2);
      ctx.fillStyle = '#fff'; ctx.fill();
    });
    const s = pop(seg(t, 0.55, 0.95));
    if (s > 0) {
      ctx.save();
      ctx.translate(32 * k, 14.5 * k); ctx.rotate((1 - Math.min(1, s)) * -2.4); ctx.scale(1.05 * k * s, 1.05 * k * s);
      const pts = [0, -7, 1.65, -2.27, 6.66, -2.16, 2.66, 0.87, 4.11, 5.66, 0, 2.8, -4.11, 5.66, -2.66, 0.87, -6.66, -2.16, -1.65, -2.27];
      ctx.beginPath();
      for (let i = 0; i < pts.length; i += 2) (i ? ctx.lineTo : ctx.moveTo).call(ctx, pts[i], pts[i + 1]);
      ctx.closePath(); ctx.fillStyle = C.star; ctx.shadowColor = C.star; ctx.shadowBlur = 12; ctx.fill();
      ctx.restore();
    }
    ctx.restore();
  }

  /* -- the backdrop -------------------------------------------------------------- */

  let backdrop = null;
  function drawBackdrop(ctx, W, H, sec) {
    if (!backdrop || backdrop.width !== W || backdrop.height !== H) {
      backdrop = document.createElement('canvas');
      backdrop.width = W; backdrop.height = H;
      const b = backdrop.getContext('2d');
      const g = b.createLinearGradient(0, 0, W, H);
      g.addColorStop(0, C.navy); g.addColorStop(0.6, C.navy2); g.addColorStop(1, C.deep);
      b.fillStyle = g; b.fillRect(0, 0, W, H);
      b.fillStyle = 'rgba(255,255,255,.045)';
      for (let y = 24; y < H; y += 48) for (let x = 24; x < W; x += 48) { b.beginPath(); b.arc(x, y, 1.6, 0, Math.PI * 2); b.fill(); }
    }
    ctx.drawImage(backdrop, 0, 0);
    // Three soft lights drifting slowly behind everything.
    const glows = [[C.star, 0.16, 0.2, 0.15], [C.blue, 0.2, 0.8, 0.55], [C.teal, 0.13, 0.35, 0.9]];
    glows.forEach(([colour, alpha, gx, gy], i) => {
      const x = W * (gx + 0.08 * Math.sin(sec * 0.25 + i * 2));
      const y = H * (gy + 0.06 * Math.cos(sec * 0.2 + i));
      const r = Math.max(W, H) * 0.45;
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, hexA(colour, alpha)); g.addColorStop(1, hexA(colour, 0));
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    });
  }
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  /* -- the frame around each scene ------------------------------------------------- */

  function layout(W, H) {
    if (W < H) {
      return { tall: true, pad: 72, head: 120, eyebrowY: 250, titleX: 72, titleW: 936, titleSize: 68,
        captionSize: 34, box: { x: 72, y: 760, w: 936, h: 960 }, footY: 1826 };
    }
    return { tall: false, pad: 80, head: 96, eyebrowY: 290, titleX: 96, titleW: 660, titleSize: 58,
      captionSize: 30, box: { x: 840, y: 200, w: 990, h: 760 }, footY: 1012 };
  }

  function chrome(ctx, W, H, L, sec, index) {
    // The logo and the unit, top left; the part, top right.
    logo(ctx, L.pad + 36, L.head - 22, 72, 1);
    text(ctx, 'Selecao+', L.pad + 92, L.head - 30, { size: 34, weight: 700 });
    text(ctx, fit(ctx, vid.data.unit || '', W * 0.4), L.pad + 92, L.head + 6, { size: 24, colour: C.dim });
    const scene = vid.scenes[index];
    if (scene && scene.part) {
      ctx.font = font(24, 600);
      const label = scene.part === 'week' ? 'Our week' : 'How we\'re doing';
      const w = ctx.measureText(label).width + 44;
      fillRound(ctx, W - L.pad - w, L.head - 46, w, 50, 25, scene.part === 'week' ? hexA(C.violet, 0.3) : hexA(C.star, 0.28));
      text(ctx, label, W - L.pad - w / 2, L.head - 13, { size: 24, weight: 600, align: 'center' });
    }
    // Where we are in the video: one segment per scene.
    const gap = 8; const n = vid.scenes.length;
    const width = (W - 2 * L.pad - gap * (n - 1)) / n;
    let start = 0;
    vid.scenes.forEach((s, i) => {
      const x = L.pad + i * (width + gap);
      fillRound(ctx, x, L.footY, width, 8, 4, C.line);
      const done = i < index ? 1 : i > index ? 0 : clamp01((sec - start) / s.dur);
      fillRound(ctx, x, L.footY, width * done, 8, 4, C.ink);
      start += s.dur;
    });
    const made = `Made ${dayYear(vid.data.made)} from the team's timesheets and plans`
      + (vid.data.through ? `, counted to ${day(vid.data.through)}` : '');
    text(ctx, made, L.pad, L.footY + 46, { size: 22, colour: C.dim });
  }

  function heading(ctx, L, scene, local) {
    const enter = ease(seg(local, 0, 0.7));
    ctx.save();
    ctx.globalAlpha *= enter;
    ctx.translate(0, (1 - enter) * 30);
    text(ctx, scene.eyebrow.toUpperCase(), L.titleX, L.eyebrowY, { size: 26, weight: 700, colour: scene.part === 'doing' ? '#ffb08f' : '#c6bdff' });
    let y = L.eyebrowY + L.titleSize * 1.15;
    y += para(ctx, scene.title, L.titleX, y, L.titleW, { size: L.titleSize, weight: 800, lead: 1.1, most: 3 });
    ctx.restore();
    const cap = ease(seg(local, 0.35, 1.1));
    ctx.save();
    ctx.globalAlpha *= cap;
    para(ctx, scene.caption, L.titleX, y + 22, L.titleW, { size: L.captionSize, colour: C.soft, lead: 1.32, most: L.tall ? 5 : 8 });
    ctx.restore();
  }

  /** Where the scene's picture goes: below its words on a tall video, beside them on a wide one. */
  function boxFor(ctx, L, scene) {
    if (!L.tall || scene.full) return L.box;
    ctx.font = font(L.titleSize, 800);
    const titleLines = Math.min(3, wrap(ctx, scene.title, L.titleW).length);
    ctx.font = font(L.captionSize);
    const capLines = Math.min(5, wrap(ctx, scene.caption, L.titleW).length);
    const end = L.eyebrowY + L.titleSize * 1.15 + titleLines * L.titleSize * 1.1 + 22 + capLines * L.captionSize * 1.32;
    const y = Math.max(560, end + 40);
    return { x: L.box.x, y, w: L.box.w, h: L.footY - 50 - y };
  }

  /* -- the scenes ------------------------------------------------------------------ */
  // Each scene: { part, eyebrow, title, caption, dur, full, draw(ctx, box, t, local, L) }.
  // t is 0..1 through the scene, local its seconds.

  function introScene(part, d) {
    const week = d.week; const doing = d.doing;
    const chips = [];
    if (part !== 'doing') {
      if (week.due.late) chips.push([plural(week.due.late, 'submission') + ' late', C.red]);
      else chips.push([`${plural(week.due.soon, 'submission')} in 2 weeks`, C.violet]);
      if (week.month) chips.push([`${h(week.month.hours)} planned in ${longMonth(week.month.month)}`, C.blue]);
      if (week.people.people_needed) chips.push([`${plural(week.people.people_needed, 'more engineer')} to ask for`, C.amber]);
      else chips.push(['Enough people for the plan', C.green]);
    }
    if (part !== 'week') {
      if (doing.busy !== null) chips.push([`${pct(doing.busy)} busy on real work`, busyTone(doing.busy)]);
      if (doing.cpi !== null) chips.push([`${doing.cpi.toFixed(2)} earned per 1 spent`, cpiTone(doing.cpi)]);
    }
    const title = part === 'week' ? 'Our week' : part === 'doing' ? 'How we\'re doing' : 'Our week, and how we\'re doing';
    const sub = part === 'doing' ? (doing.label || '') : (week.title || '');
    return {
      part: null, full: true, dur: 4.2, eyebrow: '', title, caption: '',
      draw(ctx, box, t, local, L, W, H) {
        const cy = L.tall ? H * 0.34 : H * 0.36;
        logo(ctx, W / 2, cy, L.tall ? 240 : 200, seg(local, 0, 1.6));
        const a = ease(seg(local, 1.0, 1.8));
        ctx.save(); ctx.globalAlpha *= a; ctx.translate(0, (1 - a) * 30);
        text(ctx, 'Selecao+', W / 2, cy + (L.tall ? 230 : 180), { size: L.tall ? 64 : 56, weight: 800, align: 'center' });
        text(ctx, d.unit || '', W / 2, cy + (L.tall ? 290 : 232), { size: 30, colour: C.soft, align: 'center' });
        ctx.restore();
        const b = ease(seg(local, 1.5, 2.3));
        ctx.save(); ctx.globalAlpha *= b; ctx.translate(0, (1 - b) * 40);
        ctx.font = font(L.tall ? 84 : 76, 800);
        const lines = wrap(ctx, title, W - 2 * L.pad, 2);
        const ty = cy + (L.tall ? 440 : 340);
        lines.forEach((line, i) => text(ctx, line, W / 2, ty + i * (L.tall ? 92 : 84), { size: L.tall ? 84 : 76, weight: 800, align: 'center' }));
        text(ctx, sub, W / 2, ty + lines.length * (L.tall ? 92 : 84) + 10, { size: 34, colour: '#ffb08f', weight: 600, align: 'center' });
        ctx.restore();
        // A row of chips: the headlines to come.
        const chipY = cy + (L.tall ? 700 + (lines.length - 1) * 92 : 470 + (lines.length - 1) * 84);
        ctx.font = font(28, 600);
        const widths = chips.map(([label]) => ctx.measureText(label).width + 64);
        const rows = []; let row = []; let rw = 0; const most = W - 2 * L.pad;
        widths.forEach((w, i) => { if (rw + w > most && row.length) { rows.push(row); row = []; rw = 0; } row.push(i); rw += w + 16; });
        if (row.length) rows.push(row);
        rows.forEach((r, ri) => {
          const total = r.reduce((s, i) => s + widths[i] + 16, -16);
          let x = (W - total) / 2;
          r.forEach((i) => {
            const p = pop(seg(local, 2.2 + i * 0.18, 2.7 + i * 0.18));
            if (p > 0) {
              ctx.save();
              ctx.translate(x + widths[i] / 2, chipY + ri * 78 + 28); ctx.scale(p, p);
              fillRound(ctx, -widths[i] / 2, -30, widths[i], 60, 30, hexA(chips[i][1], 0.24));
              ctx.beginPath(); ctx.arc(-widths[i] / 2 + 26, 0, 7, 0, Math.PI * 2); ctx.fillStyle = chips[i][1]; ctx.fill();
              text(ctx, chips[i][0], 10, 10, { size: 28, weight: 600, align: 'center' });
              ctx.restore();
            }
            x += widths[i] + 16;
          });
        });
      },
    };
  }

  function dividerScene(d) {
    return {
      part: null, full: true, dur: 2.4, eyebrow: '', title: '', caption: '',
      draw(ctx, box, t, local, L, W, H) {
        const a = ease(seg(local, 0, 0.8));
        ctx.save(); ctx.globalAlpha *= a;
        text(ctx, 'NEXT', W / 2, H * 0.42, { size: 30, weight: 700, colour: '#ffb08f', align: 'center' });
        ctx.translate(0, (1 - a) * 40);
        text(ctx, 'How we\'re doing', W / 2, H * 0.42 + 110, { size: L.tall ? 96 : 88, weight: 800, align: 'center' });
        text(ctx, d.doing.label || '', W / 2, H * 0.42 + 180, { size: 34, colour: C.soft, align: 'center' });
        ctx.restore();
        const w = (W - 2 * L.pad) * 0.5 * ease(seg(local, 0.3, 1.6));
        fillRound(ctx, W / 2 - w / 2, H * 0.42 + 220, w, 6, 3, C.star);
      },
    };
  }

  function outroScene(d) {
    return {
      part: null, full: true, dur: 3.4, eyebrow: '', title: '', caption: '',
      draw(ctx, box, t, local, L, W, H) {
        logo(ctx, W / 2, H * 0.4, L.tall ? 200 : 170, seg(local, 0, 1.4));
        const a = ease(seg(local, 0.8, 1.6));
        ctx.save(); ctx.globalAlpha *= a;
        text(ctx, 'Made with Selecao+', W / 2, H * 0.4 + (L.tall ? 190 : 160), { size: L.tall ? 60 : 54, weight: 800, align: 'center' });
        para(ctx, `Every number here comes from the team's own timesheets and plans${d.unit ? ` in ${d.unit}` : ''}`
          + (d.through ? `, counted to ${dayYear(d.through)}.` : '.'),
        W / 2, H * 0.4 + (L.tall ? 260 : 220), Math.min(W - 2 * L.pad, 900), { size: 32, colour: C.soft, align: 'center', lead: 1.3 });
        ctx.restore();
      },
    };
  }

  /* The desks: paper piled up for the next two weeks. */
  function desksScene(d) {
    const w = d.week; const desks = w.desks;
    if (!desks.length) return null;
    const heavy = w.ease_off; const room = desks.filter((x) => x.load !== null && x.load < 0.75).map((x) => x.name);
    let title = 'Everyone has a full desk for the next two weeks';
    if (heavy.length && room.length) title = `${names(room)} ${room.length === 1 ? 'has' : 'have'} room; ${names(heavy)} ${heavy.length === 1 ? 'needs' : 'need'} a lighter week`;
    else if (heavy.length) title = `${names(heavy)} ${heavy.length === 1 ? 'needs' : 'need'} a lighter week`;
    else if (room.length) title = `${names(room)} ${room.length === 1 ? 'has' : 'have'} room for more work`;
    return {
      part: 'week', dur: 6.5, eyebrow: 'What is on our desks', title,
      caption: `The paper on each desk is the work planned for that person over the next ${w.desk_days || 10} working days. A full pile is as much as they can do; a red note means their recent timesheets show too many hours.`,
      draw(ctx, box, t, local) {
        const n = desks.length;
        let best = null;
        for (let cols = 1; cols <= n; cols += 1) {
          const rows = Math.ceil(n / cols);
          const cw = box.w / cols; const ch = box.h / rows;
          const score = Math.abs(Math.log((ch / cw) / 1.15)) + (cw < 220 ? 5 : 0);
          if (!best || score < best.score) best = { cols, rows, cw, ch, score };
        }
        desks.forEach((desk, i) => {
          const col = i % best.cols; const row = Math.floor(i / best.cols);
          const inRow = Math.min(best.cols, n - row * best.cols);
          const offset = (box.w - inRow * best.cw) / 2;
          drawDesk(ctx, box.x + offset + col * best.cw, box.y + row * best.ch, best.cw, best.ch, desk, seg(local, 0.6 + i * 0.18, 3.6 + i * 0.18), local);
        });
      },
    };
  }

  function drawDesk(ctx, x, y, cw, ch, desk, grow, local) {
    const s = Math.min(cw / 300, ch / 330);
    const cx = x + cw / 2;
    const floor = y + ch - 78 * s;
    const deskW = (desk.manager ? 250 : 220) * s; const deskTop = floor - 70 * s;
    const appear = ease(seg(grow, 0, 0.25));
    ctx.save();
    ctx.globalAlpha *= appear;
    // The person behind the desk.
    const colour = personColour(desk.name);
    ctx.fillStyle = colour;
    ctx.beginPath(); ctx.arc(cx, deskTop - 38 * s, 34 * s, Math.PI, 0); ctx.fill();
    ctx.beginPath(); ctx.arc(cx, deskTop - 92 * s, 22 * s, 0, Math.PI * 2); ctx.fill();
    text(ctx, initials(desk.name), cx, deskTop - 84 * s, { size: 18 * s, weight: 700, colour: C.navy, align: 'center' });
    // The computer.
    fillRound(ctx, cx - 34 * s, deskTop - 62 * s, 68 * s, 46 * s, 5 * s, '#d9e2f0');
    fillRound(ctx, cx - 29 * s, deskTop - 57 * s, 58 * s, 36 * s, 3 * s, '#2a3c5c');
    ctx.fillStyle = '#d9e2f0'; ctx.fillRect(cx - 4 * s, deskTop - 16 * s, 8 * s, 16 * s);
    // The desk.
    fillRound(ctx, cx - deskW / 2, deskTop, deskW, 14 * s, 4 * s, desk.manager ? C.wood : '#8fa3c2');
    ctx.fillStyle = desk.manager ? C.wood2 : '#6b7f9f';
    ctx.fillRect(cx - deskW / 2 + 12 * s, deskTop + 14 * s, 8 * s, floor - deskTop - 14 * s);
    ctx.fillRect(cx + deskW / 2 - 20 * s, deskTop + 14 * s, 8 * s, floor - deskTop - 14 * s);
    ctx.restore();
    // Two piles of paper, one each side of the computer, rising with the load.
    const load = Math.max(0, Math.min(desk.load || 0, 1.6));
    const full = Math.max(60 * s, deskTop - y - 40 * s);
    const pileH = full * load * 0.62 * ease(seg(grow, 0.15, 1));
    const sheet = 7 * s;
    [-1, 1].forEach((side) => {
      const px = cx + side * (deskW / 2 - 40 * s) - 26 * s;
      const count = Math.floor(pileH / sheet);
      for (let k = 0; k < count; k += 1) {
        const wob = Math.sin(k * 1.7 + side) * 3 * s;
        ctx.fillStyle = k % 2 ? C.paper : C.paper2;
        ctx.fillRect(px + wob, deskTop - (k + 1) * sheet, 52 * s, sheet - 1);
      }
      if (count) fillRound(ctx, px - 3 * s, deskTop - count * sheet - 8 * s, 58 * s, 9 * s, 3 * s, loadTone(desk.load));
    });
    // The name and the hours under the desk.
    const label = ease(seg(grow, 0.4, 0.9));
    ctx.save(); ctx.globalAlpha *= label;
    ctx.font = font(26 * s, 700);
    text(ctx, fit(ctx, desk.name, cw - 16), cx, floor + 34 * s, { size: 26 * s, weight: 700, align: 'center' });
    text(ctx, `${h(desk.hours)} of ${h(desk.capacity)}`, cx, floor + 64 * s, { size: 21 * s, colour: C.soft, align: 'center' });
    if (desk.manager) text(ctx, 'Manager', cx, deskTop + 40 * s, { size: 16 * s, weight: 700, colour: C.navy, align: 'center' });
    ctx.restore();
    if (desk.ease_off) {
      const p = pop(seg(grow, 0.8, 1));
      if (p > 0) {
        ctx.save();
        ctx.translate(cx + deskW / 2 - 8 * s, deskTop - 108 * s); ctx.rotate(0.12); ctx.scale(p, p);
        fillRound(ctx, -62 * s, -26 * s, 124 * s, 52 * s, 6 * s, C.red);
        text(ctx, 'Needs a', 0, -3 * s, { size: 17 * s, weight: 700, align: 'center' });
        text(ctx, 'lighter week', 0, 17 * s, { size: 17 * s, weight: 700, align: 'center' });
        ctx.restore();
      }
    }
  }

  /* What goes out: the late ones first, then the next two weeks. */
  function dueScene(d) {
    const due = d.week.due;
    const title = due.late && due.soon
      ? `${plural(due.late, 'submission')} late, ${due.soon} more due in 2 weeks`
      : due.late ? `${plural(due.late, 'submission')} ${due.late === 1 ? 'is' : 'are'} late`
        : due.soon ? `${plural(due.soon, 'submission')} go${due.soon === 1 ? 'es' : ''} out in the next 2 weeks`
          : 'Nothing is due in the next 2 weeks';
    return {
      part: 'week', dur: 6.5, eyebrow: 'What goes out', title,
      caption: due.late
        ? 'Late means its planned date has passed and it has not gone. Each one shows the date it was due, the date it is now expected, how far along it is and who prepares it.'
        : 'Each one shows its date, how far along it is and who prepares it.',
      draw(ctx, box, t, local) {
        const items = due.items;
        if (!items.length) { bigTick(ctx, box, local, 'All clear'); return; }
        const gap = 18; const rows = Math.max(items.length, 4);
        const rh = Math.min(150, (box.h - gap * (rows - 1) - (due.more ? 50 : 0)) / rows);
        items.forEach((item, i) => {
          const p = ease(seg(local, 0.7 + i * 0.25, 1.4 + i * 0.25));
          if (p <= 0) return;
          const y = box.y + i * (rh + gap);
          ctx.save(); ctx.globalAlpha *= p; ctx.translate((1 - p) * 120, 0);
          fillRound(ctx, box.x, y, box.w, rh, 22, C.card);
          if (item.late) fillRound(ctx, box.x, y, 8, rh, 4, C.red);
          // The date: the old one crossed out when it is late.
          const dx = box.x + 30; const dw = 150;
          fillRound(ctx, dx, y + 16, dw, rh - 32, 16, item.late ? hexA(C.red, 0.22) : hexA(C.violet, 0.24));
          const shown = item.late ? item.was_due : item.date;
          const [, mo, dd] = String(shown).split('-');
          text(ctx, String(Number(dd)), dx + dw / 2, y + rh / 2 + 4, { size: Math.min(52, rh * 0.38), weight: 800, align: 'center' });
          text(ctx, MONTHS[Number(mo) - 1].toUpperCase(), dx + dw / 2, y + rh / 2 + 36, { size: 20, weight: 700, colour: C.soft, align: 'center' });
          if (item.late) {
            ctx.strokeStyle = C.red; ctx.lineWidth = 4;
            ctx.beginPath(); ctx.moveTo(dx + 24, y + rh / 2 - 8); ctx.lineTo(dx + dw - 24, y + rh / 2 - 8); ctx.stroke();
          }
          const tx = dx + dw + 28; const ring = rh * 0.32; const tw = box.x + box.w - tx - ring * 2 - 50;
          const nameY = y + rh * 0.36; const big = Math.min(32, rh * 0.27);
          const small = Math.min(23, rh * 0.2); const tiny = Math.min(22, rh * 0.19);
          text(ctx, fit((ctx.font = font(big, 700), ctx), item.name, tw), tx, nameY, { size: big, weight: 700 });
          ctx.font = font(small);
          text(ctx, fit(ctx, `${item.job}  ${item.job_name}`, tw), tx, nameY + rh * 0.25, { size: small, colour: C.soft });
          const note = item.late ? `Was due ${day(item.was_due)}, now ${day(item.date)}` : `Due ${day(item.date)}`;
          text(ctx, note, tx, nameY + rh * 0.5, { size: tiny, weight: 600, colour: item.late ? '#ff9b98' : '#c6bdff' });
          const noteW = ctx.measureText(note).width;
          // Who prepares it.
          item.people.slice(0, 4).forEach((name, k) => {
            const r = 15; const px = tx + noteW + 34 + k * (r * 2 - 6);
            if (rh < 120 || px > box.x + box.w - ring * 2 - 60) return;
            ctx.beginPath(); ctx.arc(px, nameY + rh * 0.5 - 8, r, 0, Math.PI * 2); ctx.fillStyle = personColour(name); ctx.fill();
            ctx.lineWidth = 2; ctx.strokeStyle = C.navy; ctx.stroke();
            text(ctx, initials(name), px, nameY + rh * 0.5 - 2, { size: 12, weight: 700, colour: C.navy, align: 'center' });
          });
          // How far along it is.
          const done = (item.progress || 0) * ease(seg(local, 1.2 + i * 0.25, 2.6 + i * 0.25));
          ring2(ctx, box.x + box.w - ring - 30, y + rh / 2, ring, done, item.late ? C.red : C.green);
          text(ctx, pct(done), box.x + box.w - ring - 30, y + rh / 2 + 8, { size: Math.max(18, ring * 0.5), weight: 700, align: 'center' });
          ctx.restore();
        });
        if (due.more) {
          const p = ease(seg(local, 0.7 + items.length * 0.25, 1.4 + items.length * 0.25));
          ctx.save(); ctx.globalAlpha *= p;
          text(ctx, `and ${due.more} more in Planner › Submissions`, box.x + box.w / 2, box.y + items.length * (rh + gap) + 30, { size: 26, colour: C.soft, align: 'center' });
          ctx.restore();
        }
      },
    };
  }

  function ring2(ctx, x, y, r, value, colour) {
    ctx.lineWidth = Math.max(6, r * 0.22); ctx.lineCap = 'round';
    ctx.strokeStyle = C.line; ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.stroke();
    if (value > 0) {
      ctx.strokeStyle = colour; ctx.beginPath();
      ctx.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * clamp01(value)); ctx.stroke();
    }
    ctx.lineCap = 'butt';
  }

  function bigTick(ctx, box, local, label) {
    const p = pop(seg(local, 0.6, 1.4));
    const cx = box.x + box.w / 2; const cy = box.y + box.h * 0.4; const r = Math.min(box.w, box.h) * 0.22;
    ctx.save(); ctx.translate(cx, cy); ctx.scale(p, p);
    ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.fillStyle = hexA(C.green, 0.25); ctx.fill();
    ctx.strokeStyle = C.green; ctx.lineWidth = r * 0.14; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.beginPath(); ctx.moveTo(-r * 0.42, 0); ctx.lineTo(-r * 0.1, r * 0.32); ctx.lineTo(r * 0.45, -r * 0.3); ctx.stroke();
    ctx.restore();
    ctx.save(); ctx.globalAlpha *= ease(seg(local, 1.2, 1.8));
    text(ctx, label, cx, cy + r + 70, { size: 40, weight: 700, align: 'center' });
    ctx.restore();
  }

  /* Where the month's submission hours go, job by job. */
  function monthScene(d) {
    const m = d.week.month;
    if (!m || !m.jobs.length) return null;
    const share = m.capacity_hours ? m.hours / m.capacity_hours : null;
    return {
      part: 'week', dur: 5.5, eyebrow: 'Where the hours go',
      title: `${h(m.hours)} of submission work planned for ${longMonth(m.month)}`,
      caption: `The hours planned to prepare submissions from today to the end of ${longMonth(m.month)}, job by job`
        + (m.capacity_hours ? `, against the ${h(m.capacity_hours)} the team can work in that time (${pct(share)} of it).` : '.'),
      draw(ctx, box, t, local) {
        // The month as one bar, filling up.
        const fill = ease(seg(local, 0.6, 2.2));
        const top = box.y + 20;
        text(ctx, 'Planned', box.x, top + 30, { size: 26, weight: 600, colour: C.soft });
        text(ctx, `${h(m.hours * fill)}${m.capacity_hours ? ` of ${h(m.capacity_hours)}` : ''}`, box.x + box.w, top + 30, { size: 30, weight: 700, align: 'right' });
        fillRound(ctx, box.x, top + 50, box.w, 44, 22, C.line);
        const whole = m.capacity_hours ? Math.min(1.2, share) / Math.max(1, Math.min(1.2, share)) : 1;
        fillRound(ctx, box.x, top + 50, box.w * whole * fill, 44, 22, share !== null && share > 1 ? C.red : share !== null && share > 0.95 ? C.amber : C.blue);
        // Each job's part of it.
        const most = Math.max(...m.jobs.map((j) => j.hours || 0), 1);
        const rows = m.jobs.length; const y0 = top + 150; const gap = 22;
        const rh = Math.min(140, (box.y + box.h - y0 - gap * (rows - 1)) / rows);
        m.jobs.forEach((job, i) => {
          const p = ease(seg(local, 1.2 + i * 0.25, 2.8 + i * 0.25));
          const y = y0 + i * (rh + gap);
          ctx.save(); ctx.globalAlpha *= Math.min(1, p * 2);
          fillRound(ctx, box.x, y, box.w, rh, 20, C.card);
          const colour = PEOPLE[i % PEOPLE.length];
          text(ctx, job.job, box.x + 28, y + 44, { size: 30, weight: 800, colour });
          ctx.font = font(26);
          text(ctx, fit(ctx, job.name || '', box.w - 260), box.x + 28 + ctx.measureText(`${job.job}    `).width + 30, y + 44, { size: 26, colour: C.soft });
          text(ctx, h((job.hours || 0) * p), box.x + box.w - 28, y + 44, { size: 30, weight: 700, align: 'right' });
          fillRound(ctx, box.x + 28, y + rh - 46, box.w - 56, 20, 10, C.line);
          fillRound(ctx, box.x + 28, y + rh - 46, (box.w - 56) * ((job.hours || 0) / most) * p, 20, 10, colour);
          ctx.restore();
        });
      },
    };
  }

  /* People needed, month by month. */
  function peopleScene(d) {
    const pp = d.week.people;
    const months = pp.months;
    if (!months.length) return null;
    const ask = pp.asks[0];
    const title = ask ? ask.title
      : pp.people_needed ? `Ask for ${plural(pp.people_needed, 'more engineer')}`
        : 'We have the people for the work planned';
    return {
      part: 'week', dur: 6, eyebrow: 'Do we have enough people?', title,
      caption: `The bars are the engineers the whole unit's planned submission work needs each month, against the ${pp.engineers || 0} we have (the white line). Up to the dashed line, ${pct(pp.well_used || 0.85)} of them, is the right amount of busy.`
        + (ask ? ' The ask is for one team, for the weeks it is short.' : ''),
      draw(ctx, box, t, local) {
        const most = Math.max(pp.engineers || 0, ...months.map((m) => m.needed || 0), 1) * 1.15;
        const base = box.y + box.h - 70; const tall = box.h - 150;
        const n = months.length; const slot = box.w / n; const bw = Math.min(120, slot * 0.72);
        const y = (v) => base - (v / most) * tall;
        // The engineers we have, and the well-used line.
        const have = pp.engineers || 0;
        const lineIn = ease(seg(local, 0.5, 1.5));
        ctx.save(); ctx.globalAlpha *= lineIn;
        ctx.strokeStyle = C.ink; ctx.lineWidth = 4;
        ctx.beginPath(); ctx.moveTo(box.x, y(have)); ctx.lineTo(box.x + box.w * lineIn, y(have)); ctx.stroke();
        text(ctx, `${have} we have`, box.x + box.w, y(have) - 14, { size: 24, weight: 700, align: 'right' });
        ctx.setLineDash([12, 10]); ctx.strokeStyle = C.green; ctx.lineWidth = 3;
        const well = have * (pp.well_used || 0.85);
        ctx.beginPath(); ctx.moveTo(box.x, y(well)); ctx.lineTo(box.x + box.w * lineIn, y(well)); ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();
        months.forEach((m, i) => {
          const cx = box.x + slot * (i + 0.5);
          const p = ease(seg(local, 1 + i * 0.2, 2.4 + i * 0.2));
          text(ctx, monthOf(m.month), cx, base + 44, { size: 28, weight: 700, align: 'center', colour: C.soft });
          if (m.nothing_planned) {
            ctx.save(); ctx.globalAlpha *= p;
            ctx.setLineDash([8, 8]); ctx.strokeStyle = C.dim; ctx.lineWidth = 2;
            roundRect(ctx, cx - bw / 2, base - 70, bw, 70, 12); ctx.stroke(); ctx.setLineDash([]);
            text(ctx, 'none yet', cx, base - 28, { size: 18, colour: C.dim, align: 'center' });
            ctx.restore();
            return;
          }
          const v = (m.needed || 0) * p;
          const colour = (m.needed || 0) > have ? C.red : (m.needed || 0) > well ? C.amber : C.blue;
          fillRound(ctx, cx - bw / 2, y(v), bw, base - y(v), 14, colour);
          text(ctx, v.toFixed(1), cx, Math.min(y(v) + 44, base - 12), { size: 30, weight: 800, align: 'center', colour: C.navy });
        });
      },
    };
  }

  /* The week's to-do list. */
  function todoScene(d) {
    const todo = d.week.todo;
    if (!todo.length) return null;
    const first = todo.filter((x) => x.tone === 'bad').length;
    return {
      part: 'week', dur: 6, eyebrow: 'What to do this week',
      title: `${plural(todo.length + (d.week.todo_more || 0), 'thing')} to act on${first ? `, ${first} of them first` : ''}`,
      caption: 'From the weekly report: red ones first, amber this week, green when you can.',
      draw(ctx, box, t, local) {
        const gap = 20; const rows = Math.max(todo.length, 4);
        const rh = Math.min(170, (box.h - gap * (rows - 1)) / rows);
        todo.forEach((item, i) => {
          const at = 0.6 + i * 0.45;
          const p = ease(seg(local, at, at + 0.6));
          if (p <= 0) return;
          const y = box.y + i * (rh + gap);
          ctx.save(); ctx.globalAlpha *= p; ctx.translate(0, (1 - p) * 40);
          fillRound(ctx, box.x, y, box.w, rh, 22, C.card);
          const colour = TONE[item.tone] || C.green;
          const r = 26; const cx = box.x + 30 + r; const cy = y + rh / 2;
          ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = hexA(colour, 0.25); ctx.fill();
          ctx.lineWidth = 4; ctx.strokeStyle = colour; ctx.stroke();
          text(ctx, String(i + 1), cx, cy + 10, { size: 28, weight: 800, align: 'center' });
          ctx.font = font(30, 600);
          const lines = wrap(ctx, item.text, box.w - 140, 3);
          const lh = 38; const top = cy - (lines.length * lh) / 2 + 28;
          lines.forEach((line, li) => text(ctx, line, box.x + 110, top + li * lh, { size: 30, weight: 600 }));
          ctx.restore();
        });
      },
    };
  }

  /* Busy on real work: a gauge with the right band in green. */
  function busyScene(d) {
    const g = d.doing;
    if (g.busy === null) return null;
    const verdict = g.busy > 1.05 ? 'too much overtime' : g.busy >= 0.85 ? 'about right' : g.busy >= 0.7 ? 'room for more' : 'not enough real work';
    return {
      part: 'doing', dur: 6.5, eyebrow: 'Busy on real work', title: `${pct(g.busy)}: ${verdict}`,
      caption: `Hours on projects and proposals out of the hours there were to work in ${String(g.label || 'the year').replace(/^Full year /, '')}${g.counted_to ? `, counted to ${day(g.counted_to)}` : ''}, after leave and holidays. 85% to 105% is right.`
        + (g.days_not_filled ? ` ${plural(g.days_not_filled, 'timesheet day')} not filled in yet pull it down.` : ''),
      draw(ctx, box, t, local, L) {
        const peopleH = g.people.length ? (L.tall ? 330 : 250) : 0;
        const r = Math.min(box.w * 0.42, (box.h - peopleH) * 0.78);
        const cx = box.x + box.w / 2; const cy = box.y + r + 30;
        const span = 1.3; const angle = (v) => Math.PI + Math.PI * clamp01(v / span);
        const bands = [[0, 0.7, C.red], [0.7, 0.85, C.amber], [0.85, 1.05, C.green], [1.05, span, C.red]];
        ctx.lineWidth = r * 0.16;
        const draw = ease(seg(local, 0.3, 1.2));
        bands.forEach(([a, b, colour]) => {
          ctx.strokeStyle = hexA(colour, 0.85);
          ctx.beginPath(); ctx.arc(cx, cy, r, angle(a), angle(a + (b - a) * draw)); ctx.stroke();
        });
        [0, 0.5, 0.85, 1.05, 1.3].forEach((v) => {
          const a = angle(v);
          text(ctx, `${Math.round(v * 100)}%`, cx + Math.cos(a) * (r + r * 0.2), cy + Math.sin(a) * (r + r * 0.2) + 8, { size: 20, colour: C.dim, align: 'center' });
        });
        const v = g.busy * ease(seg(local, 0.9, 2.6));
        const a = angle(v);
        ctx.strokeStyle = C.ink; ctx.lineWidth = 10; ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.cos(a) * r * 0.86, cy + Math.sin(a) * r * 0.86); ctx.stroke();
        ctx.lineCap = 'butt';
        ctx.beginPath(); ctx.arc(cx, cy, 18, 0, Math.PI * 2); ctx.fillStyle = C.ink; ctx.fill();
        ctx.font = font(r * 0.3, 800);
        const tw = ctx.measureText(pct(v)).width + r * 0.16;
        fillRound(ctx, cx - tw / 2, cy - r * 0.6, tw, r * 0.38, r * 0.12, hexA(C.navy, 0.92));
        text(ctx, pct(v), cx, cy - r * 0.32, { size: r * 0.3, weight: 800, align: 'center', colour: busyTone(v) });
        // Each person, a dot on the same scale.
        if (!g.people.length) return;
        const top = cy + 70; const lane = box.y + box.h - top;
        const n = g.people.length; const slot = box.w / n; const bh = lane - 90;
        g.people.forEach((p, i) => {
          const k = ease(seg(local, 2.2 + i * 0.12, 3.6 + i * 0.12));
          const x = box.x + slot * (i + 0.5); const bw = Math.min(64, slot * 0.5);
          const val = (p.busy || 0) * k;
          fillRound(ctx, x - bw / 2, top, bw, bh, bw / 2, C.line);
          const fh = bh * clamp01(val / span);
          fillRound(ctx, x - bw / 2, top + bh - fh, bw, fh, bw / 2, busyTone(val));
          ctx.save(); ctx.globalAlpha *= Math.min(1, k * 2);
          text(ctx, pct(val), x, top + bh - fh - 12, { size: 22, weight: 700, align: 'center' });
          ctx.font = font(22, 600);
          text(ctx, fit(ctx, p.name, slot - 8), x, top + bh + 36, { size: 22, weight: 600, align: 'center', colour: C.soft });
          ctx.restore();
        });
        // The 85% to 105% band behind the people.
        ctx.save(); ctx.globalAlpha *= 0.18 * ease(seg(local, 2, 2.8));
        const yA = top + bh - bh * (1.05 / span); const yB = top + bh - bh * (0.85 / span);
        ctx.fillStyle = C.green; ctx.fillRect(box.x, yA, box.w, yB - yA);
        ctx.restore();
      },
    };
  }

  /* Earned against spent. */
  function earnScene(d) {
    const g = d.doing;
    if (g.cpi === null || !g.actual_mm) return null;
    const verdict = g.cpi >= 1 ? 'the work earns what it costs' : g.cpi >= 0.9 ? 'close, keep an eye on it' : 'the work costs more than it earns';
    return {
      part: 'doing', dur: 5.5, eyebrow: 'Are we earning what we spend?',
      title: `${g.cpi.toFixed(2)} earned for every 1 spent: ${verdict}`,
      caption: 'Earned is each job\'s budget times how far it has got. Spent is what the timesheets booked to projects. Both in man-months (MM); 1.00 or more is good.',
      draw(ctx, box, t, local) {
        const most = Math.max(g.earned_mm || 0, g.actual_mm || 0, 1) * 1.1;
        const base = box.y + box.h - 80; const tall = box.h - 200;
        const bars = [['Earned', g.earned_mm || 0, C.green], ['Spent', g.actual_mm || 0, C.blue]];
        const bw = Math.min(220, box.w * 0.26);
        bars.forEach(([label, value, colour], i) => {
          const cx = box.x + box.w * (i ? 0.7 : 0.3);
          const p = ease(seg(local, 0.6 + i * 0.4, 2.4 + i * 0.4));
          const hh = tall * (value / most) * p;
          fillRound(ctx, cx - bw / 2, base - hh, bw, hh, 22, colour);
          text(ctx, mm(value * p), cx, base - hh - 20, { size: 40, weight: 800, align: 'center' });
          text(ctx, label, cx, base + 48, { size: 32, weight: 700, align: 'center', colour: C.soft });
        });
        const k = pop(seg(local, 2.8, 3.4));
        if (k > 0 && g.profit_mm !== null) {
          ctx.save(); ctx.translate(box.x + box.w / 2, box.y + 50); ctx.scale(k, k);
          const label = `${g.profit_mm >= 0 ? '+' : '−'}${Math.abs(g.profit_mm).toFixed(2)} MM ${g.profit_mm >= 0 ? 'ahead' : 'behind'}`;
          ctx.font = font(30, 700);
          const w = ctx.measureText(label).width + 60;
          fillRound(ctx, -w / 2, -34, w, 68, 34, hexA(g.profit_mm >= 0 ? C.green : C.red, 0.3));
          text(ctx, label, 0, 10, { size: 30, weight: 700, align: 'center' });
          ctx.restore();
        }
      },
    };
  }

  /* Keeping up with the plan. */
  function planScene(d) {
    const g = d.doing;
    if (!g.planned_to_date_mm || g.plan_done === null) return null;
    const verdict = g.plan_done >= 0.9 ? 'keeping up' : 'falling behind';
    return {
      part: 'doing', dur: 5.5, eyebrow: 'Are we keeping up with the plan?',
      title: `${pct(g.plan_done)} of the work planned so far is done: ${verdict}`,
      caption: `Planned is each job's budget spread from its start to its end, up to today: ${mm(g.planned_to_date_mm)}. Done is the value earned; spent is the effort booked. 90% done or more is keeping up.`,
      draw(ctx, box, t, local) {
        const most = Math.max(g.planned_to_date_mm, g.earned_mm || 0, g.actual_mm || 0) * 1.08;
        const rows = [['Planned so far', g.planned_to_date_mm, C.violet], ['Done (earned)', g.earned_mm || 0, g.plan_done >= 0.9 ? C.green : C.amber], ['Spent', g.actual_mm || 0, C.blue]];
        const rh = Math.min(200, box.h / 3.4); const gap = (box.h - rh * 3) / 3;
        rows.forEach(([label, value, colour], i) => {
          const y = box.y + gap / 2 + i * (rh + gap);
          const p = ease(seg(local, 0.6 + i * 0.4, 2.2 + i * 0.4));
          text(ctx, label, box.x, y + 36, { size: 32, weight: 700, colour: C.soft });
          text(ctx, mm(value * p), box.x + box.w, y + 36, { size: 34, weight: 800, align: 'right' });
          fillRound(ctx, box.x, y + 64, box.w, rh - 84, (rh - 84) / 2, C.line);
          fillRound(ctx, box.x, y + 64, box.w * (value / most) * p, rh - 84, (rh - 84) / 2, colour);
        });
        // A marker where today's plan stands.
        const x = box.x + box.w * (g.planned_to_date_mm / most);
        const k = ease(seg(local, 2.6, 3.4));
        ctx.save(); ctx.globalAlpha *= k;
        ctx.setLineDash([10, 10]); ctx.strokeStyle = C.ink; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(x, box.y + gap / 2 + 50); ctx.lineTo(x, box.y + box.h - gap / 2); ctx.stroke(); ctx.setLineDash([]);
        ctx.restore();
      },
    };
  }

  /* Last week's hours, person by person. */
  function lastWeekScene(d) {
    const lw = d.doing.last_week;
    if (!lw || !lw.people.length) return null;
    return {
      part: 'doing', dur: 5.5, eyebrow: 'How did last week go?',
      title: `${h(lw.hours)} booked of ${h(lw.capacity)}: ${pct(lw.load)} of the team's hours`,
      caption: `Hours each person booked in the week of ${day(lw.week)}, against the hours they had that week (the white line). Above the line is overtime${lw.overtime ? `: ${h(lw.overtime)} in all` : ''}.`,
      draw(ctx, box, t, local) {
        const people = lw.people;
        const most = Math.max(...people.map((p) => Math.max(p.hours || 0, p.capacity || 0)), 1) * 1.15;
        const base = box.y + box.h - 70; const tall = box.h - 120;
        const n = people.length; const slot = box.w / n; const bw = Math.min(100, slot * 0.6);
        people.forEach((p, i) => {
          const cx = box.x + slot * (i + 0.5);
          const k = ease(seg(local, 0.6 + i * 0.15, 2.2 + i * 0.15));
          const cap = (p.capacity || 0) / most * tall; const all = (p.hours || 0) / most * tall * k;
          const under = Math.min(all, cap);
          fillRound(ctx, cx - bw / 2, base - under, bw, under, 12, personColour(p.name));
          if (all > cap) fillRound(ctx, cx - bw / 2, base - all, bw, all - cap + 6, 12, C.amber);
          ctx.strokeStyle = C.ink; ctx.lineWidth = 4;
          ctx.beginPath(); ctx.moveTo(cx - bw / 2 - 10, base - cap); ctx.lineTo(cx + bw / 2 + 10, base - cap); ctx.stroke();
          text(ctx, h((p.hours || 0) * k), cx, base - all - (all > cap - 30 && all < cap + 30 ? Math.max(0, cap - all) + 16 : 16), { size: 24, weight: 700, align: 'center' });
          ctx.font = font(24, 600);
          text(ctx, fit(ctx, p.name, slot - 6), cx, base + 40, { size: 24, weight: 600, align: 'center', colour: C.soft });
        });
      },
    };
  }

  /* The jobs with the most hours this year. */
  function jobsScene(d) {
    const jobs = d.doing.jobs;
    if (!jobs.length) return null;
    return {
      part: 'doing', dur: 6, eyebrow: 'Where did the hours go?',
      title: `${plural(d.doing.projects_active, 'active job')}; these took the most hours`,
      caption: `The jobs with the most booked this year: how far along each is (the bar), its effort in MM and what it earns for each 1 spent (green 1.00 or more).`,
      draw(ctx, box, t, local) {
        const gap = 18; const rh = Math.min(170, (box.h - gap * (jobs.length - 1)) / jobs.length);
        jobs.forEach((job, i) => {
          const p = ease(seg(local, 0.6 + i * 0.3, 1.4 + i * 0.3));
          if (p <= 0) return;
          const y = box.y + i * (rh + gap);
          ctx.save(); ctx.globalAlpha *= p; ctx.translate((1 - p) * -100, 0);
          fillRound(ctx, box.x, y, box.w, rh, 22, C.card);
          const chipW = 150;
          text(ctx, job.job, box.x + 28, y + 46, { size: 30, weight: 800, colour: PEOPLE[i % PEOPLE.length] });
          ctx.font = font(26);
          text(ctx, fit(ctx, job.name, box.w - chipW - 240), box.x + 200, y + 46, { size: 26, colour: C.soft });
          const cpi = job.cpi;
          fillRound(ctx, box.x + box.w - chipW - 24, y + 16, chipW, 44, 22, hexA(cpiTone(cpi), 0.3));
          text(ctx, cpi === null ? 'no CPI' : `CPI ${cpi.toFixed(2)}`, box.x + box.w - chipW / 2 - 24, y + 47, { size: 24, weight: 700, align: 'center' });
          const k = ease(seg(local, 1.0 + i * 0.3, 2.4 + i * 0.3));
          const bx = box.x + 28; const bw = box.w - 56; const by = y + rh - 52;
          fillRound(ctx, bx, by, bw, 22, 11, C.line);
          fillRound(ctx, bx, by, bw * clamp01(job.progress || 0) * k, 22, 11, cpiTone(cpi));
          text(ctx, `${pct((job.progress || 0) * k)} along · ${mm(job.actual_mm)} spent`, bx, by - 12, { size: 22, colour: C.soft });
          ctx.restore();
        });
      },
    };
  }

  /* The budgets, when they have been brought in. */
  function budgetScene(d) {
    const b = d.doing.budgets;
    if (!b || !b.team_budget_mm) return null;
    const spent = (b.team_spent_mm || 0) / b.team_budget_mm;
    const title = b.over ? `${plural(b.over, 'job')} over budget` : b.short ? `${plural(b.short, 'job')} running short` : 'Every job is within its budget';
    return {
      part: 'doing', dur: 5.5, eyebrow: 'Is any job running out of budget?', title,
      caption: `Our team's share of the budgets from BISpark: ${mm(b.team_spent_mm)} spent of ${mm(b.team_budget_mm)} across ${plural(b.jobs, 'job')}. Running short means it runs out before the job ends at today's pace.`,
      draw(ctx, box, t, local, L) {
        const r = Math.min(box.w, box.h) * (L.tall ? 0.28 : 0.3);
        const cx = L.tall ? box.x + box.w / 2 : box.x + r + 30; const cy = box.y + r + 40;
        const k = ease(seg(local, 0.6, 2.4));
        ring2(ctx, cx, cy, r, spent * k, spent > 1 ? C.red : spent > 0.9 ? C.amber : C.teal);
        text(ctx, pct(spent * k), cx, cy + 10, { size: r * 0.42, weight: 800, align: 'center' });
        text(ctx, 'spent', cx, cy + r * 0.38, { size: 28, colour: C.soft, align: 'center' });
        const listX = L.tall ? box.x : box.x + 2 * r + 90; const listW = box.x + box.w - listX;
        let y = L.tall ? cy + r + 90 : box.y + 40;
        b.worst.forEach((job, i) => {
          const p = ease(seg(local, 2 + i * 0.3, 2.8 + i * 0.3));
          ctx.save(); ctx.globalAlpha *= p;
          fillRound(ctx, listX, y, listW, 110, 20, C.card);
          fillRound(ctx, listX, y, 8, 110, 4, job.state === 'over' ? C.red : C.amber);
          text(ctx, job.job, listX + 28, y + 44, { size: 28, weight: 800 });
          ctx.font = font(24);
          text(ctx, fit(ctx, job.name, listW - 56), listX + 28, y + 80, { size: 24, colour: C.soft });
          ctx.restore();
          y += 130;
        });
      },
    };
  }

  function buildScenes(d, part) {
    const week = [desksScene, dueScene, monthScene, peopleScene, todoScene].map((f) => f(d)).filter(Boolean);
    const doing = [busyScene, earnScene, planScene, lastWeekScene, jobsScene, budgetScene].map((f) => f(d)).filter(Boolean);
    let scenes;
    if (part === 'week') scenes = [introScene('week', d), ...week, outroScene(d)];
    else if (part === 'doing') scenes = [introScene('doing', d), ...doing, outroScene(d)];
    else {
      // Both in one: a little quicker, so it stays about a minute.
      [...week, ...doing].forEach((s) => { s.dur *= 0.85; });
      scenes = [introScene('both', d), ...week, dividerScene(d), ...doing, outroScene(d)];
    }
    return scenes;
  }

  /* -- one frame ------------------------------------------------------------------ */

  function render(ctx, W, H, sec) {
    drawBackdrop(ctx, W, H, sec);
    const L = layout(W, H);
    let start = 0; let index = vid.scenes.length - 1;
    for (let i = 0; i < vid.scenes.length; i += 1) {
      if (sec < start + vid.scenes[i].dur) { index = i; break; }
      start += vid.scenes[i].dur;
    }
    if (index === vid.scenes.length - 1 && sec >= vid.total) start = vid.total - vid.scenes[index].dur;
    const scene = vid.scenes[index];
    const local = Math.min(sec - start, scene.dur);
    const t = local / scene.dur;
    const last = index === vid.scenes.length - 1;
    const fade = ease(seg(local, 0, 0.45)) * (last ? 1 : 1 - seg(local, scene.dur - 0.35, scene.dur));
    ctx.save();
    ctx.globalAlpha = fade;
    if (!scene.full) heading(ctx, L, scene, local);
    scene.draw(ctx, boxFor(ctx, L, scene), t, local, L, W, H);
    ctx.restore();
    if (!scene.full) chrome(ctx, W, H, L, sec - start, index);
  }

  /* -- the page ------------------------------------------------------------------- */

  const canvas = make('canvas', { class: 'vd-canvas', role: 'img', 'aria-label': 'The summary video' });
  const ctx = canvas.getContext('2d');
  const stage = make('div', { class: 'vd-stage' }, canvas);
  const player = make('video', { class: 'vd-player', controls: true, playsinline: true, hidden: true });
  player.setAttribute('playsinline', '');
  stage.append(player);

  function shape() { return SHAPES.find((s) => s.key === vid.shape) || SHAPES[0]; }

  function prepare() {
    if (!vid.data) return;
    const { w, h: hh } = shape();
    canvas.width = w; canvas.height = hh;
    stage.dataset.shape = vid.shape;
    vid.scenes = buildScenes(vid.data, vid.part);
    vid.total = vid.scenes.reduce((s, x) => s + x.dur, 0);
    // A still from the first scene, so the box is never empty.
    render(ctx, w, hh, Math.min(3.4, vid.total));
    drawControls();
  }

  function mimeType() {
    if (typeof MediaRecorder === 'undefined' || !canvas.captureStream) return null;
    const wanted = ['video/mp4;codecs=avc1.42E01E', 'video/mp4;codecs=avc1', 'video/mp4',
      'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
    return wanted.find((m) => { try { return MediaRecorder.isTypeSupported(m); } catch (_) { return false; } }) || null;
  }

  function fileName(type) {
    const part = { week: 'our-week', doing: 'how-we-are-doing', both: 'our-week-and-how-we-are-doing' }[vid.part];
    return `selecao-${part}-${vid.data.made}.${/mp4/.test(type) ? 'mp4' : 'webm'}`;
  }

  function forget() {
    if (vid.url) URL.revokeObjectURL(vid.url);
    vid.url = null; vid.file = null;
    player.hidden = true; player.removeAttribute('src'); canvas.hidden = false;
  }

  async function play() {
    if (vid.playing || !vid.data) return;
    forget();
    prepare();
    const { w, h: hh } = shape();
    const type = mimeType();
    let chunks = [];
    let recorder = null;
    if (type) {
      try {
        const stream = canvas.captureStream(30);
        recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 8000000 });
        recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      } catch (_) { recorder = null; }
    }
    vid.playing = true; vid.recorder = recorder;
    drawControls();
    if (recorder) recorder.start(500);
    const t0 = performance.now();
    await new Promise((done) => {
      const tick = (now) => {
        const sec = (now - t0) / 1000;
        render(ctx, w, hh, Math.min(sec, vid.total));
        progress.value = Math.min(1, sec / vid.total);
        if (sec >= vid.total + 0.4 || !vid.playing) { done(); return; }
        vid.frame = requestAnimationFrame(tick);
      };
      vid.frame = requestAnimationFrame(tick);
    });
    const stopped = !vid.playing;
    vid.playing = false;
    if (recorder) {
      await new Promise((done) => { recorder.onstop = done; try { recorder.stop(); } catch (_) { done(); } });
      vid.recorder = null;
      if (!stopped && chunks.length) {
        const blob = new Blob(chunks, { type: type.split(';')[0] });
        vid.url = URL.createObjectURL(blob);
        vid.file = { blob, name: fileName(type) };
        player.src = vid.url; player.hidden = false; canvas.hidden = true;
      }
      chunks = [];
    }
    drawControls();
  }

  function stop() { vid.playing = false; cancelAnimationFrame(vid.frame); }

  async function share() {
    if (!vid.file) return;
    const file = new File([vid.file.blob], vid.file.name, { type: vid.file.blob.type });
    try {
      await navigator.share({ files: [file], title: 'Selecao+ video' });
    } catch (error) {
      if (error && error.name !== 'AbortError' && typeof toast === 'function') toast('Could not share it; use Save the video instead.', 'bad');
    }
  }

  const progress = make('progress', { class: 'vd-progress', max: '1', value: '0' });
  const controls = make('div', { class: 'vd-controls' });

  function drawControls() {
    const canRecord = Boolean(mimeType());
    const len = Math.round(vid.total || 0);
    const buttons = [];
    if (vid.playing) {
      buttons.push(make('button', { type: 'button', class: 'btn', onclick: stop }, 'Stop'));
    } else {
      buttons.push(make('button', { type: 'button', class: 'btn btn-primary', onclick: play },
        vid.file ? 'Make it again' : canRecord ? 'Make the video' : 'Play the video'));
      if (vid.file) {
        buttons.push(make('a', { class: 'btn', href: vid.url, download: vid.file.name }, 'Save the video'));
        const file = new File([vid.file.blob], vid.file.name, { type: vid.file.blob.type });
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          buttons.push(make('button', { type: 'button', class: 'btn', onclick: share }, 'Share or save to Photos'));
        }
      }
    }
    const note = vid.playing
      ? (vid.recorder ? `Making it: keep this page open until it ends (about ${len} seconds).` : 'Playing.')
      : vid.file ? `Ready: ${vid.file.name}. Play it above, or save it.`
        : canRecord ? `About ${len} seconds. It plays here while it is made, then you can save it or share it. Nothing is sent anywhere: the video is made on this phone or computer.`
          : `About ${len} seconds. This browser can play it here but cannot save it as a file; Safari on an iPhone and Chrome on a computer can.`;
    setChildren(controls, make('div', { class: 'vd-buttons' }, ...buttons),
      vid.playing ? progress : null, make('p', { class: 'muted vd-note' }, note));
  }

  function choices() {
    const partRow = make('div', { class: 'vd-choices', role: 'radiogroup', 'aria-label': 'What the video shows' },
      ...PARTS.map((p) => make('button', {
        type: 'button', role: 'radio', 'aria-checked': String(vid.part === p.key),
        class: `vd-choice${vid.part === p.key ? ' is-on' : ''}`, 'data-part': p.key,
        onclick: () => { if (vid.playing) return; vid.part = p.key; keep(); forget(); draw(); },
      }, make('span', { class: 'vd-choice-title' }, p.title), make('span', { class: 'vd-choice-say' }, p.say))));
    const shapeRow = make('div', { class: 'vd-shapes', role: 'radiogroup', 'aria-label': 'Shape of the video' },
      make('span', { class: 'muted' }, 'Shape:'),
      ...SHAPES.map((s) => make('button', {
        type: 'button', role: 'radio', 'aria-checked': String(vid.shape === s.key),
        class: `path-chip${vid.shape === s.key ? ' is-on' : ''}`,
        onclick: () => { if (vid.playing) return; vid.shape = s.key; keep(); forget(); draw(); },
      }, s.title)));
    return make('section', { class: 'panel vd-pick' },
      make('h3', {}, 'What should the video show?'), partRow, shapeRow);
  }

  function draw() {
    if (!vid.data) return;
    setChildren(host, choices(),
      make('section', { class: 'panel vd-panel' }, make('h3', {}, 'The video'), stage, controls));
    prepare();
  }

  async function load() {
    if (vid.playing) return;
    const fresh = vid.data && Date.now() - vid.loadedAt < 60000;
    if (fresh) { draw(); return; }
    if (!vid.loading) {
      if (!vid.data) setChildren(host, make('div', { class: 'empty' }, 'Gathering the results…'));
      vid.loading = (async () => {
        try {
          vid.data = await api('/api/video');
          vid.loadedAt = Date.now();
          forget();
        } catch (error) {
          if (!vid.data) setChildren(host, make('div', { class: 'msg msg-bad' }, error.message || 'Could not gather the results.'));
        } finally { vid.loading = null; }
      })();
    }
    await vid.loading;
    draw();
  }

  /** One frame, at a second of the video: for a quick look without playing it. */
  function still(sec) { const { w, h: hh } = shape(); render(ctx, w, hh, Math.max(0, Math.min(sec, vid.total))); }

  window.video = { load, still, length: () => vid.total, scenes: () => vid.scenes.map((s) => s.eyebrow || s.title) };
}());
