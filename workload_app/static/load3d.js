/* Selecao+ — the team's load as a 3D landscape (WebGL).
 *
 * One block per person (or team) per week, standing on a plate: the height
 * is the load, the sheet of glass is a full load, the colour runs from blue
 * (room) through green (about right) to amber and red (over). Turn it with a
 * finger or the mouse, pinch to zoom, tap a block to read it.
 *
 * Loaded on demand by showcase.js, so three.js (vendored, MIT) is only fetched
 * when Check-ins is opened. It draws only while something moves, so it costs
 * nothing standing still on a phone.
 */
import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';

const UNIT = 1.15;     // height of a full load
const HMAX = 1.9;      // loads above this are drawn at this
const FOOT = 0.74;     // a block's footprint

function token(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function tokenColor(name, fallback) {
  // A token may itself be a var() reference; let the browser resolve it.
  const probe = document.createElement('span');
  probe.style.color = `var(${name}, ${fallback})`;
  probe.style.display = 'none';
  document.body.append(probe);
  const rgb = getComputedStyle(probe).color;
  probe.remove();
  return new THREE.Color(rgb.startsWith('rgb') ? rgb : fallback);
}

function palette() {
  return {
    room: tokenColor('--series-1', '#2a78d6'),
    right: tokenColor('--series-3', '#1baf7a'),
    heavy: tokenColor('--series-4', '#eda100'),
    over: tokenColor('--bad', '#a62828').lerp(new THREE.Color('#ff6b5e'), 0.35),
    plate: tokenColor('--surface', '#ffffff'),
    line: tokenColor('--border', '#dcdfe5'),
    glass: tokenColor('--accent', '#1c5fa8'),
    text: token('--text', '#14181f'),
    dark: matchMedia('(prefers-color-scheme: dark)').matches
      && document.documentElement.dataset.theme !== 'light',
  };
}

/** Load as a colour: room, about right, heavy, over. */
function loadColor(v, p) {
  if (v === null || v === undefined) return p.line.clone();
  const stops = [[0.5, p.room], [0.8, p.room], [0.95, p.right], [1.05, p.right],
    [1.18, p.heavy], [1.32, p.over]];
  if (v <= stops[0][0]) return stops[0][1].clone();
  for (let i = 1; i < stops.length; i += 1) {
    const [x1, c1] = stops[i];
    const [x0, c0] = stops[i - 1];
    if (v <= x1) return c0.clone().lerp(c1, (v - x0) / (x1 - x0 || 1));
  }
  return p.over.clone();
}

/** A rounded square prism, base at 0, height 1, so scale.y sets the height. */
function blockGeometry() {
  const s = FOOT / 2; const r = 0.13;
  const shape = new THREE.Shape();
  shape.moveTo(-s + r, -s);
  shape.lineTo(s - r, -s); shape.quadraticCurveTo(s, -s, s, -s + r);
  shape.lineTo(s, s - r); shape.quadraticCurveTo(s, s, s - r, s);
  shape.lineTo(-s + r, s); shape.quadraticCurveTo(-s, s, -s, s - r);
  shape.lineTo(-s, -s + r); shape.quadraticCurveTo(-s, -s, -s + r, -s);
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false, curveSegments: 5 });
  geo.rotateX(-Math.PI / 2);   // extrude upwards
  geo.computeVertexNormals();
  return geo;
}

/** On a phone, keep the latest weeks so the blocks stay big enough to read and tap. */
function trimmed(model, keep) {
  const off = Math.max(0, model.cols.length - keep);
  if (!off) return model;
  return {
    ...model,
    cols: model.cols.slice(off),
    values: model.values.map((row) => row.slice(off)),
    now: Math.max(0, model.now - off),
    text: (r, c, v) => model.text(r, c + off, v),
    onPick: model.onPick ? (r, c) => model.onPick(r, c + off) : null,
  };
}

export function render(host, fullModel) {
  if (host.__scape) host.__scape.dispose();
  const narrow = host.clientWidth < 520;
  const model = narrow ? trimmed(fullModel, 8) : fullModel;
  const R = model.rows.length; const C = model.cols.length;
  const ZS = Math.min(2, Math.max(narrow ? 1.35 : 1, C / (R * 1.9)));   // spread few rows out
  const p = palette();
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- stage
  const stage = document.createElement('div');
  stage.className = 'scape3d';
  const labels = document.createElement('div');
  labels.className = 'scape3d-labels';
  const tip = document.createElement('div');
  tip.className = 'scape-tip'; tip.hidden = true;
  const reset = document.createElement('button');
  reset.type = 'button'; reset.className = 'scape-btn scape3d-reset';
  reset.title = 'Back to the start'; reset.setAttribute('aria-label', 'Back to the start');
  reset.textContent = '⌂';
  const hint = document.createElement('div');
  hint.className = 'scape3d-hint';
  hint.textContent = narrow ? 'Drag to turn · pinch to zoom · tap a block' : 'Drag to turn · scroll to zoom · click a block';
  host.replaceChildren(stage);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (error) {
    return null;   // no WebGL: the caller falls back to the flat drawing
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  stage.append(renderer.domElement, labels, tip, reset, hint);
  renderer.domElement.setAttribute('role', 'img');
  renderer.domElement.setAttribute('aria-label', model.summary || 'Load landscape');

  const scene = new THREE.Scene();
  const W = () => stage.clientWidth || 320;
  const H = () => Math.round(Math.min(460, Math.max(narrow ? 300 : 320, W() * (narrow ? 0.8 : 0.42))));
  const camera = new THREE.PerspectiveCamera(narrow ? 42 : 34, W() / H(), 0.1, 200);

  // ---- light
  scene.add(new THREE.HemisphereLight(0xffffff, p.dark ? 0x202631 : 0xd9dee6, p.dark ? 0.9 : 1.05));
  const sun = new THREE.DirectionalLight(0xffffff, p.dark ? 2.0 : 2.4);
  const span = Math.max(C, R * ZS);
  sun.position.set(-span * 0.45, span * 0.9, span * 0.6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(narrow ? 1024 : 2048, narrow ? 1024 : 2048);
  const sc = sun.shadow.camera;
  sc.left = -span; sc.right = span; sc.top = span; sc.bottom = -span; sc.near = 0.5; sc.far = span * 4;
  sun.shadow.bias = -0.0008;
  sun.shadow.radius = 4;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(span, span * 0.4, -span);
  scene.add(fill);

  // ---- the plate and its grid
  const plateW = C + 1.2; const plateD = R * ZS + 1.2;
  const plate = new THREE.Mesh(new THREE.BoxGeometry(plateW, 0.16, plateD),
    new THREE.MeshStandardMaterial({ color: p.plate, roughness: 0.85, metalness: 0 }));
  plate.position.y = -0.08;
  plate.receiveShadow = true;
  scene.add(plate);
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(plate.geometry),
    new THREE.LineBasicMaterial({ color: p.line }));
  edge.position.copy(plate.position);
  scene.add(edge);
  const gridPts = [];
  for (let c = 0; c <= C; c += 1) {
    const x = c - C / 2;
    gridPts.push(x, 0.002, -R * ZS / 2, x, 0.002, R * ZS / 2);
  }
  for (let r = 0; r <= R; r += 1) {
    const z = (r - R / 2) * ZS;
    gridPts.push(-C / 2, 0.002, z, C / 2, 0.002, z);
  }
  const gridGeo = new THREE.BufferGeometry();
  gridGeo.setAttribute('position', new THREE.Float32BufferAttribute(gridPts, 3));
  scene.add(new THREE.LineSegments(gridGeo, new THREE.LineBasicMaterial({
    color: p.line, transparent: true, opacity: 0.8 })));

  // where the past ends: a lit strip across the plate
  if (model.now > 0 && model.now < C) {
    const strip = new THREE.Mesh(new THREE.PlaneGeometry(0.05, R * ZS + 0.9),
      new THREE.MeshBasicMaterial({ color: p.glass, transparent: true, opacity: 0.85 }));
    strip.rotation.x = -Math.PI / 2;
    strip.position.set(model.now - C / 2, 0.006, 0);
    scene.add(strip);
  }

  // ---- the blocks
  const geo = blockGeometry();
  const blocks = [];
  for (let r = 0; r < R; r += 1) {
    for (let c = 0; c < C; c += 1) {
      const v = model.values[r][c];
      const mat = new THREE.MeshStandardMaterial({
        color: loadColor(v, p), roughness: 0.38, metalness: 0.04,
        transparent: v === null || v === undefined, opacity: v === null || v === undefined ? 0.35 : 1,
      });
      const mesh = new THREE.Mesh(geo, mat);
      const h = Math.max(0.04, Math.min(v || 0, HMAX) * UNIT);
      mesh.position.set(c - (C - 1) / 2, 0, (r - (R - 1) / 2) * ZS);
      mesh.scale.y = reduced ? h : 0.001;
      mesh.castShadow = true; mesh.receiveShadow = true;
      mesh.userData = { r, c, v, h };
      scene.add(mesh);
      blocks.push(mesh);
    }
  }

  // ---- the glass at a full load
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(C + 0.4, R * ZS + 0.4),
    new THREE.MeshPhysicalMaterial({ color: p.glass, transparent: true, opacity: p.dark ? 0.16 : 0.12,
      roughness: 0.15, metalness: 0, side: THREE.DoubleSide, depthWrite: false }));
  glass.rotation.x = -Math.PI / 2;
  glass.position.y = UNIT;
  glass.renderOrder = 2;
  scene.add(glass);
  const rim = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(C + 0.4, 0.001, R * ZS + 0.4)),
    new THREE.LineBasicMaterial({ color: p.glass, transparent: true, opacity: 0.55 }));
  rim.position.y = UNIT;
  scene.add(rim);

  // ---- labels, in HTML so they stay crisp
  const anchors = [];
  const label = (text, pos, cls, shift) => {
    const node = document.createElement('span');
    node.className = `scape3d-label ${cls}`;
    node.textContent = text;
    node.title = text;
    labels.append(node);
    anchors.push({ node, pos, shift });
    return node;
  };
  model.rows.forEach((row, r) => {
    const node = label(row.label,
      new THREE.Vector3(-C / 2 - 0.45, 0.05, (r - (R - 1) / 2) * ZS), 'scape3d-row', 'translate(-100%, -50%)');
    if (row.color) node.style.setProperty('--dot', row.color);
  });
  const every = narrow ? (C > 10 ? 3 : C > 5 ? 2 : 1) : C > 10 ? 2 : 1;
  model.cols.forEach((col, c) => {
    if (c % every && !(c === C - 1 && c % every >= 2)) return;
    label(col, new THREE.Vector3(c - (C - 1) / 2, 0.02, R * ZS / 2 + 0.75), 'scape3d-col', 'translate(-50%, -50%)');
  });
  if (model.now > 0 && model.now < C) {
    label('today', new THREE.Vector3(model.now - C / 2, 0.02, -R * ZS / 2 - 0.7), 'scape3d-today', 'translate(-50%, -50%)');
  }
  label('full load', new THREE.Vector3(C / 2 + 0.2, UNIT, -R * ZS / 2), 'scape3d-glass', 'translate(0, -50%)');

  // ---- camera and controls
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.enablePan = false;
  controls.minPolarAngle = 0.25;
  controls.maxPolarAngle = 1.32;
  controls.rotateSpeed = narrow ? 0.7 : 0.6;
  controls.zoomSpeed = 0.7;
  const radius = Math.hypot(C, R * ZS, UNIT * 2) / 2;
  const top = Math.max(UNIT, ...blocks.map((b) => b.userData.h));
  // the corners of everything that must stay in view, and the row labels
  const hullPts = [];
  for (const x of [-plateW / 2, plateW / 2]) {
    for (const z of [-plateD / 2, plateD / 2 + 0.6]) hullPts.push(new THREE.Vector3(x, -0.16, z));
  }
  for (const b of blocks) {
    for (const dx of [-FOOT / 2, FOOT / 2]) {
      hullPts.push(new THREE.Vector3(b.position.x + dx, Math.max(b.userData.h, 0.2), b.position.z - FOOT / 2));
    }
  }
  const rowPts = model.rows.map((_, r) => new THREE.Vector3(-C / 2 - 0.45, 0.05, (r - (R - 1) / 2) * ZS));
  const probe = new THREE.PerspectiveCamera();
  const direction = () => {
    const yaw = narrow ? -0.08 : -0.2; const pitch = narrow ? 0.8 : 0.9;
    return new THREE.Vector3(-Math.sin(yaw) * Math.sin(pitch), Math.cos(pitch), Math.cos(yaw) * Math.sin(pitch));
  };
  /** The nearest spot where the whole model and its labels fit, and the sideways
   *  shift (in screen units) that centres them. */
  const home = () => {
    const dir = direction();
    const target = new THREE.Vector3(0, top * 0.3, 0);
    const labelW = Math.max(0, ...anchors.filter((a) => a.node.classList.contains('scape3d-row'))
      .map((a) => a.node.offsetWidth + 14));
    const labelFrac = (2 * Math.min(labelW, W() * 0.42)) / W();
    probe.fov = camera.fov; probe.aspect = camera.aspect; probe.near = 0.1; probe.far = 400;
    probe.updateProjectionMatrix();
    const q = new THREE.Vector3();
    const box = (d) => {
      probe.position.copy(target).addScaledVector(dir, d);
      probe.lookAt(target); probe.updateMatrixWorld();
      const bb = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity, behind: false };
      for (const pt of hullPts) {
        q.copy(pt).project(probe);
        if (q.z > 1) bb.behind = true;
        bb.x0 = Math.min(bb.x0, q.x); bb.x1 = Math.max(bb.x1, q.x);
        bb.y0 = Math.min(bb.y0, q.y); bb.y1 = Math.max(bb.y1, q.y);
      }
      for (const pt of rowPts) bb.x0 = Math.min(bb.x0, q.copy(pt).project(probe).x - labelFrac);
      for (const an of anchors) {
        if (!an.node.classList.contains('scape3d-glass') && !an.node.classList.contains('scape3d-today')) continue;
        q.copy(an.pos).project(probe);
        const half = an.node.offsetHeight / H();
        bb.x1 = Math.max(bb.x1, q.x + (an.node.classList.contains('scape3d-glass') ? (2 * an.node.offsetWidth) / W() : 0));
        bb.y1 = Math.max(bb.y1, q.y + half * 2);
      }
      return bb;
    };
    const fits = (d) => {
      const bb = box(d);
      return !bb.behind && bb.x1 - bb.x0 <= 1.9 && bb.y1 - bb.y0 <= 1.72;
    };
    let lo = radius * 0.3; let hi = radius * 10;
    for (let k = 0; k < 24; k += 1) {
      const mid = (lo + hi) / 2;
      if (fits(mid)) hi = mid; else lo = mid;
    }
    const bb = box(hi);
    return {
      target,
      pos: target.clone().addScaledVector(dir, hi),
      shift: [(bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2 + 0.03],
    };
  };
  let shift = [0, 0];

  function size() {
    const w = W(); const h = H();
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = `${w}px`;
    renderer.domElement.style.height = `${h}px`;
    stage.style.height = `${h}px`;
    camera.aspect = w / h;
    camera.setViewOffset(w, h, (shift[0] * w) / 2, (-shift[1] * h) / 2, w, h);
  }
  size();
  const start = home();
  shift = start.shift; size();
  controls.target.copy(start.target);
  camera.position.copy(start.pos);
  {
    const d = camera.position.distanceTo(controls.target);
    controls.minDistance = Math.min(radius * 0.9, d * 0.45);
    controls.maxDistance = Math.max(radius * 5, d * 2);
  }
  camera.lookAt(controls.target);

  // ---- drawing, only while something moves
  const v3 = new THREE.Vector3();
  function placeLabels() {
    const w = W(); const h = H();
    for (const a of anchors) {
      v3.copy(a.pos).project(camera);
      const hidden = v3.z > 1;
      a.node.style.transform = `translate(${((v3.x + 1) / 2) * w}px, ${((1 - v3.y) / 2) * h}px) ${a.shift}`;
      a.node.style.visibility = hidden ? 'hidden' : '';
    }
  }
  let frame = 0; let busyUntil = 0;
  function draw() {
    renderer.render(scene, camera);
    placeLabels();
  }
  function loop(now) {
    frame = 0;
    const moving = controls.update();
    draw();
    if (moving || now < busyUntil) frame = requestAnimationFrame(loop);
  }
  function wake(ms = 0) {
    busyUntil = Math.max(busyUntil, performance.now() + ms);
    if (!frame) frame = requestAnimationFrame(loop);
  }
  controls.addEventListener('change', () => wake(120));

  // the blocks rise, and the view swings in
  if (!reduced) {
    const t0 = performance.now();
    const to = start.pos;
    const from = to.clone().sub(start.target).applyAxisAngle(new THREE.Vector3(0, 1, 0), -0.55)
      .multiplyScalar(1.12).add(start.target);
    camera.position.copy(from);
    const rise = (now) => {
      const k = Math.min(1, (now - t0) / 1100);
      const ease = 1 - (1 - k) ** 3;
      blocks.forEach((b, i) => {
        const lag = (i % C) / C * 0.35;
        const kb = Math.min(1, Math.max(0, (k - lag) / (1 - lag)));
        b.scale.y = Math.max(0.001, b.userData.h * (1 - (1 - kb) ** 3));
      });
      camera.position.lerpVectors(from, to, ease);
      camera.lookAt(controls.target);
      draw();
      if (k < 1 && renderer.domElement.isConnected) requestAnimationFrame(rise);
    };
    requestAnimationFrame(rise);
    controls.update();
  } else {
    controls.update();
    draw();
  }

  // ---- reading a block
  const ray = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let picked = null;
  let down = null;
  function pick(mesh, x, y) {
    if (picked) picked.material.emissive.setHex(0x000000);
    picked = mesh;
    if (!mesh) { tip.hidden = true; wake(); return; }
    mesh.material.emissive = mesh.material.color.clone().multiplyScalar(0.35);
    const { r, c, v } = mesh.userData;
    tip.replaceChildren();
    const b = document.createElement('b'); b.textContent = model.rows[r].label;
    const s = document.createElement('span'); s.textContent = model.text(r, c, v);
    tip.append(b, s);
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max(4, x + 12), W() - 200)}px`;
    tip.style.top = `${Math.min(Math.max(4, y - 56), H() - 64)}px`;
    if (model.onPick) model.onPick(r, c);
    wake();
  }
  renderer.domElement.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY }; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6) { down = null; return; }
    down = null;
    const rect = renderer.domElement.getBoundingClientRect();
    const x = e.clientX - rect.left; const y = e.clientY - rect.top;
    pointer.set((x / rect.width) * 2 - 1, -(y / rect.height) * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const hit = ray.intersectObjects(blocks, false)[0];
    pick(hit ? hit.object : null, x, y);
  });
  controls.addEventListener('start', () => { tip.hidden = true; hint.classList.add('is-gone'); });

  reset.addEventListener('click', () => {
    const fromPos = camera.position.clone(); const fromTarget = controls.target.clone();
    const back = home();
    const t0 = performance.now();
    const go = (now) => {
      const k = Math.min(1, (now - t0) / 420);
      const e = 1 - (1 - k) ** 3;
      camera.position.lerpVectors(fromPos, back.pos, e);
      controls.target.lerpVectors(fromTarget, back.target, e);
      controls.update(); draw();
      if (k < 1) requestAnimationFrame(go);
    };
    pick(null);
    requestAnimationFrame(go);
  });

  let observer = null;
  if (window.ResizeObserver) {
    let last = W();
    observer = new ResizeObserver(() => {
      if (W() === last) return;
      last = W(); size(); wake();
    });
    observer.observe(stage);
  }

  const instance = {
    dispose() {
      cancelAnimationFrame(frame);
      if (observer) observer.disconnect();
      controls.dispose();
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      });
      renderer.dispose();
      renderer.forceContextLoss();
      host.__scape = null;
    },
  };
  host.__scape = instance;
  return instance;
}
