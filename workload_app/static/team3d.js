/* Selecao+ — the next two weeks in 3D: one tower per person.
 *
 * Each tower is how much of their hours a person has lined up for the next two
 * weeks; the sheet of glass is a full load. "Show the moves" lets the towers
 * settle to where the planner's suggested handovers would leave them, with an
 * arc from the person handing work over to the person taking it.
 *
 * Loaded on demand by showcase.js; shares its palette and block shape with
 * load3d.js. Draws only while something moves.
 */
import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { palette, loadColor, blockGeometry } from './load3d.js';

const UNIT = 1.4;     // height of a full load
const CAP = 2.0;      // loads above this are drawn at this
const GAP = 1.75;     // distance between towers

const heightOf = (v) => Math.max(0.06, Math.min(v || 0, CAP) * UNIT);

export function render(host, model) {
  if (host.__scape) host.__scape.dispose();
  const N = model.people.length;
  if (!N) return null;
  const p = palette();
  const narrow = host.clientWidth < 520;
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
  host.replaceChildren(stage);

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  } catch (error) {
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  stage.append(renderer.domElement, labels, tip, reset);
  renderer.domElement.setAttribute('role', 'img');
  renderer.domElement.setAttribute('aria-label', model.summary || 'The team\'s next two weeks');

  const scene = new THREE.Scene();
  const W = () => stage.clientWidth || 320;
  const H = () => Math.round(Math.min(440, Math.max(narrow ? 300 : 320, W() * (narrow ? 1.05 : 0.4))));
  const camera = new THREE.PerspectiveCamera(narrow ? 40 : 32, W() / H(), 0.1, 200);

  // ---- light
  const span = N * GAP;
  scene.add(new THREE.HemisphereLight(0xffffff, p.dark ? 0x202631 : 0xd9dee6, p.dark ? 0.9 : 1.05));
  const sun = new THREE.DirectionalLight(0xffffff, p.dark ? 2.0 : 2.4);
  sun.position.set(-span * 0.4, span * 0.9, span * 0.7);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, { left: -span, right: span, top: span, bottom: -span, near: 0.5, far: span * 4 });
  sun.shadow.bias = -0.0008;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.set(span, span * 0.4, -span);
  scene.add(fill);

  // ---- the floor: one row of towers, or rows of three on a phone
  const COLS = narrow ? Math.min(3, N) : N;
  const ROWS = Math.ceil(N / COLS);
  const ZG = 2.5;
  const floorW = COLS * GAP + 0.6; const floorD = ROWS === 1 ? 2.6 : ROWS * ZG + 0.3;
  const floor = new THREE.Mesh(new THREE.BoxGeometry(floorW, 0.16, floorD),
    new THREE.MeshStandardMaterial({ color: p.plate, roughness: 0.85 }));
  floor.position.y = -0.08;
  floor.receiveShadow = true;
  scene.add(floor);
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(floor.geometry), new THREE.LineBasicMaterial({ color: p.line }));
  edge.position.copy(floor.position);
  scene.add(edge);

  // ---- the towers
  const geo = blockGeometry();
  const xOf = (i) => ((i % COLS) - (COLS - 1) / 2) * GAP;
  const zOf = (i) => (Math.floor(i / COLS) - (ROWS - 1) / 2) * ZG;
  const towers = model.people.map((person, i) => {
    const mat = new THREE.MeshStandardMaterial({ color: loadColor(person.now, p), roughness: 0.36, metalness: 0.04 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.scale.set(1.45, reduced ? heightOf(person.now) : 0.001, 1.45);
    mesh.position.set(xOf(i), 0, zOf(i));
    mesh.castShadow = true; mesh.receiveShadow = true;
    mesh.userData = { i, h: heightOf(person.now) };
    scene.add(mesh);
    return mesh;
  });

  // ---- the glass at a full load
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(floorW, floorD),
    new THREE.MeshPhysicalMaterial({ color: p.glass, transparent: true, opacity: p.dark ? 0.16 : 0.12,
      roughness: 0.15, side: THREE.DoubleSide, depthWrite: false }));
  glass.rotation.x = -Math.PI / 2;
  glass.position.y = UNIT;
  glass.renderOrder = 2;
  scene.add(glass);
  const rim = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(floorW, 0.001, floorD)),
    new THREE.LineBasicMaterial({ color: p.glass, transparent: true, opacity: 0.6 }));
  rim.position.y = UNIT;
  scene.add(rim);

  // ---- the moves: an arc from the giver's tower to the taker's
  const arcs = new THREE.Group();
  arcs.visible = false;
  scene.add(arcs);
  const arcMat = new THREE.MeshStandardMaterial({ color: p.glass, emissive: p.glass, emissiveIntensity: 0.35, roughness: 0.4 });
  const arcInfo = [];
  model.moves.forEach((move, k) => {
    const a = model.people.findIndex((x) => x.name === move.from);
    const b = model.people.findIndex((x) => x.name === move.to);
    if (a < 0 || b < 0) return;
    const ha = heightOf(model.people[a].now); const hb = heightOf(model.people[b].after);
    const lift = Math.max(ha, hb) + 0.9 + k * 0.35;
    const za = zOf(a) + 0.25 + k * 0.22; const zb = zOf(b) + 0.25 + k * 0.22;
    const curve = new THREE.CubicBezierCurve3(
      new THREE.Vector3(xOf(a), ha + 0.05, za), new THREE.Vector3(xOf(a), lift, za),
      new THREE.Vector3(xOf(b), lift, zb), new THREE.Vector3(xOf(b), hb + 0.32, zb));
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 60, 0.045, 8, false), arcMat);
    tube.geometry.setDrawRange(0, 0);
    arcs.add(tube);
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.32, 16), arcMat);
    head.position.copy(curve.getPoint(1));
    head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), curve.getTangent(1).normalize());
    head.visible = false;
    arcs.add(head);
    arcInfo.push({ tube, head, mid: curve.getPoint(0.22), label: move.label });
  });

  // ---- labels, in HTML so they stay crisp
  const anchors = [];
  const label = (text, pos, cls, shift) => {
    const node = document.createElement('span');
    node.className = `scape3d-label ${cls}`;
    node.textContent = text;
    labels.append(node);
    const a = { node, pos, shift };
    anchors.push(a);
    return a;
  };
  model.people.forEach((person, i) => {
    const a = label(person.name, new THREE.Vector3(xOf(i), 0, ROWS === 1 ? floorD / 2 + 0.05 : zOf(i) + 0.95), 'scape3d-name', 'translate(-50%, 4px)');
    a.node.style.setProperty('--dot', person.color || 'var(--muted)');
  });
  const pcts = model.people.map((person, i) => {
    const a = label(`${Math.round(person.now * 100)}%`, new THREE.Vector3(xOf(i), heightOf(person.now), zOf(i) + 0.55),
      'scape3d-pct', 'translate(-50%, calc(-100% - 6px))');
    return a;
  });
  label('full load', new THREE.Vector3(floorW / 2 - 0.1, UNIT, -floorD / 2), 'scape3d-glass', 'translate(-100%, -130%)');
  const arcLabels = arcInfo.map((info) => {
    const a = label(info.label, info.mid, 'scape3d-move', 'translate(-50%, -50%)');
    a.node.hidden = true;
    return a;
  });

  // ---- camera: fit everything, centred
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.enablePan = false;
  controls.minPolarAngle = 0.35;
  controls.maxPolarAngle = 1.4;
  controls.rotateSpeed = 0.6;
  const top = Math.max(UNIT, ...model.people.map((x) => heightOf(Math.max(x.now, x.after))));
  const hull = [];
  for (const x of [-floorW / 2, floorW / 2]) for (const z of [-floorD / 2, floorD / 2 + 0.5]) hull.push(new THREE.Vector3(x, -0.16, z));
  model.people.forEach((_, i) => hull.push(new THREE.Vector3(xOf(i), top + 0.45, zOf(i))));
  if (model.moves.length) model.people.forEach((_, i) => hull.push(new THREE.Vector3(xOf(i), top + 1.2, zOf(i) + 0.3)));
  const probe = new THREE.PerspectiveCamera();
  const tilt = ROWS > 1 ? 0.95 : 1.12;
  const dir = new THREE.Vector3(Math.sin(0.1) * Math.sin(tilt), Math.cos(tilt), Math.cos(0.1) * Math.sin(tilt));
  let shift = [0, 0];
  const home = () => {
    const target = new THREE.Vector3(0, top * 0.4, 0);
    probe.fov = camera.fov; probe.aspect = W() / H(); probe.near = 0.1; probe.far = 400;
    probe.updateProjectionMatrix();
    const q = new THREE.Vector3();
    const box = (d) => {
      probe.position.copy(target).addScaledVector(dir, d);
      probe.lookAt(target); probe.updateMatrixWorld();
      const bb = { x0: Infinity, x1: -Infinity, y0: Infinity, y1: -Infinity };
      for (const pt of hull) {
        q.copy(pt).project(probe);
        bb.x0 = Math.min(bb.x0, q.x); bb.x1 = Math.max(bb.x1, q.x);
        bb.y0 = Math.min(bb.y0, q.y); bb.y1 = Math.max(bb.y1, q.y);
      }
      return bb;
    };
    let lo = 1; let hi = span * 8 + 20;
    for (let k = 0; k < 24; k += 1) {
      const mid = (lo + hi) / 2; const bb = box(mid);
      if (bb.x1 - bb.x0 <= 1.84 && bb.y1 - bb.y0 <= 1.74) hi = mid; else lo = mid;
    }
    const bb = box(hi);
    return { target, pos: target.clone().addScaledVector(dir, hi), shift: [(bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2] };
  };
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
  const dist = camera.position.distanceTo(controls.target);
  controls.minDistance = dist * 0.45;
  controls.maxDistance = dist * 2.2;
  camera.lookAt(controls.target);

  // ---- drawing, only while something moves
  const v3 = new THREE.Vector3();
  function placeLabels() {
    const w = W(); const h = H();
    for (const a of anchors) {
      v3.copy(a.pos).project(camera);
      a.node.style.transform = `translate(${((v3.x + 1) / 2) * w}px, ${((1 - v3.y) / 2) * h}px) ${a.shift}`;
      a.node.style.visibility = v3.z > 1 ? 'hidden' : '';
    }
  }
  function draw() { renderer.render(scene, camera); placeLabels(); }
  let frame = 0; let busyUntil = 0;
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

  /** Move every tower (and its % label) to the given loads, over a moment. */
  function settle(key, ms) {
    const from = towers.map((t) => t.scale.y);
    const to = model.people.map((x) => heightOf(x[key]));
    const t0 = performance.now();
    const step = (now) => {
      const k = reduced ? 1 : Math.min(1, (now - t0) / ms);
      const e = 1 - (1 - k) ** 3;
      towers.forEach((t, i) => {
        t.scale.y = Math.max(0.001, from[i] + (to[i] - from[i]) * e);
        const v = t.scale.y / UNIT;
        t.material.color.copy(loadColor(v, p));
        pcts[i].pos.y = t.scale.y;
        pcts[i].node.textContent = `${Math.round(Math.max(0, v) * 100)}%`;
      });
      // the % shown is the real figure once settled (heights stop at CAP)
      if (k >= 1) model.people.forEach((x, i) => { pcts[i].node.textContent = `${Math.round(x[key] * 100)}%`; });
      draw();
      if (k < 1 && renderer.domElement.isConnected) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /** Draw the arcs in, one after the other. */
  function showArcs(on) {
    arcs.visible = on;
    arcLabels.forEach((a) => { a.node.hidden = true; });
    if (!on) { draw(); return; }
    const t0 = performance.now();
    const step = (now) => {
      let done = true;
      arcInfo.forEach((info, k) => {
        const kk = reduced ? 1 : Math.min(1, Math.max(0, (now - t0 - k * 250) / 700));
        if (kk < 1) done = false;
        const count = info.tube.geometry.index.count;
        info.tube.geometry.setDrawRange(0, Math.floor(count * kk / 6) * 6);
        info.head.visible = kk >= 1;
        arcLabels[k].node.hidden = kk < 1;
      });
      draw();
      if (!done && renderer.domElement.isConnected) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // the towers rise, and the view swings in
  if (!reduced) {
    const t0 = performance.now();
    const to = start.pos.clone();
    const from = to.clone().sub(start.target).applyAxisAngle(new THREE.Vector3(0, 1, 0), -0.45)
      .multiplyScalar(1.1).add(start.target);
    camera.position.copy(from);
    const rise = (now) => {
      const k = Math.min(1, (now - t0) / 1000);
      const e = 1 - (1 - k) ** 3;
      towers.forEach((t, i) => {
        const lag = (i / N) * 0.3;
        const kb = Math.min(1, Math.max(0, (k - lag) / (1 - lag)));
        t.scale.y = Math.max(0.001, t.userData.h * (1 - (1 - kb) ** 3));
        pcts[i].pos.y = t.scale.y;
      });
      camera.position.lerpVectors(from, to, e);
      camera.lookAt(controls.target);
      draw();
      if (k < 1 && renderer.domElement.isConnected) requestAnimationFrame(rise);
    };
    requestAnimationFrame(rise);
  } else {
    draw();
  }

  // ---- reading a tower
  const ray = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let picked = null; let down = null;
  let showing = 'now';
  function pick(mesh, x, y) {
    if (picked) picked.material.emissive.setHex(0x000000);
    picked = mesh;
    if (!mesh) { tip.hidden = true; draw(); return; }
    mesh.material.emissive = mesh.material.color.clone().multiplyScalar(0.3);
    const person = model.people[mesh.userData.i];
    tip.replaceChildren();
    const b = document.createElement('b'); b.textContent = person.name;
    const s = document.createElement('span'); s.textContent = model.text(person, showing);
    tip.append(b, s);
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max(4, x + 12), W() - 210)}px`;
    tip.style.top = `${Math.min(Math.max(4, y - 60), H() - 80)}px`;
    draw();
  }
  renderer.domElement.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY }; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6) { down = null; return; }
    down = null;
    const rect = renderer.domElement.getBoundingClientRect();
    const x = e.clientX - rect.left; const y = e.clientY - rect.top;
    pointer.set((x / rect.width) * 2 - 1, -(y / rect.height) * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const hit = ray.intersectObjects(towers, false)[0];
    pick(hit ? hit.object : null, x, y);
  });
  controls.addEventListener('start', () => { tip.hidden = true; });

  reset.addEventListener('click', () => {
    const fromPos = camera.position.clone(); const t0 = performance.now();
    const go = (now) => {
      const k = Math.min(1, (now - t0) / 420);
      camera.position.lerpVectors(fromPos, start.pos, 1 - (1 - k) ** 3);
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
    /** 'after' shows where the suggested moves would leave everyone. */
    show(which) {
      showing = which === 'after' ? 'after' : 'now';
      pick(null);
      settle(showing, 900);
      showArcs(showing === 'after');
    },
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
