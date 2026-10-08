/* Selecao+ — the next two weeks in 3D: one tower per person.
 *
 * Each tower is how much of their hours a person has lined up for the next two
 * weeks; the sheet of glass is a full load. "Show the moves" lets the towers
 * settle to where the planner's suggested handovers would leave them, with an
 * arc from the person handing work over to the person taking it.
 *
 * Loaded on demand by showcase.js; shares its palette, block shape, stage,
 * lights and drawing loop with load3d.js. Draws only while something moves.
 */
import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import {
  palette, loadColor, blockGeometry, makeStage, makeRenderer, addLights, addPlate, addGlass, viewer,
} from './load3d.js';

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
  const { stage, labels, tip, reset } = makeStage(host);
  const renderer = makeRenderer();
  if (!renderer) return null;
  stage.append(renderer.domElement, labels, tip, reset);
  renderer.domElement.setAttribute('role', 'img');
  renderer.domElement.setAttribute('aria-label', model.summary || 'The team\'s next two weeks');

  const scene = new THREE.Scene();
  const W = () => stage.clientWidth || 320;
  const H = () => Math.round(Math.min(440, Math.max(narrow ? 300 : 320, W() * (narrow ? 1.05 : 0.4))));
  const camera = new THREE.PerspectiveCamera(narrow ? 40 : 32, W() / H(), 0.1, 200);

  // ---- light
  const span = N * GAP;
  addLights(scene, p, span, [-0.4, 0.9, 0.7], 1024);

  // ---- the floor: one row of towers, or rows of three on a phone
  const COLS = narrow ? Math.min(3, N) : N;
  const ROWS = Math.ceil(N / COLS);
  const ZG = 2.5;
  const floorW = COLS * GAP + 0.6; const floorD = ROWS === 1 ? 2.6 : ROWS * ZG + 0.3;
  addPlate(scene, p, floorW, floorD);

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
  addGlass(scene, p, floorW, floorD, UNIT, 0.6);

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
  const pcts = model.people.map((person, i) => label(`${Math.round(person.now * 100)}%`,
    new THREE.Vector3(xOf(i), heightOf(person.now), zOf(i) + 0.55), 'scape3d-pct', 'translate(-50%, calc(-100% - 6px))'));
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
  const view = viewer({ host, stage, renderer, scene, camera, controls, anchors, W, H });
  const { draw } = view;
  const top = Math.max(UNIT, ...model.people.map((x) => heightOf(Math.max(x.now, x.after))));
  const hull = [];
  for (const x of [-floorW / 2, floorW / 2]) for (const z of [-floorD / 2, floorD / 2 + 0.5]) hull.push(new THREE.Vector3(x, -0.16, z));
  model.people.forEach((_, i) => hull.push(new THREE.Vector3(xOf(i), top + 0.45, zOf(i))));
  if (model.moves.length) model.people.forEach((_, i) => hull.push(new THREE.Vector3(xOf(i), top + 1.2, zOf(i) + 0.3)));
  const probe = new THREE.PerspectiveCamera();
  const tilt = ROWS > 1 ? 0.95 : 1.12;
  const dir = new THREE.Vector3(Math.sin(0.1) * Math.sin(tilt), Math.cos(tilt), Math.cos(0.1) * Math.sin(tilt));
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
  view.size();
  const start = home();
  view.size(start.shift);
  controls.target.copy(start.target);
  camera.position.copy(start.pos);
  const dist = camera.position.distanceTo(controls.target);
  controls.minDistance = dist * 0.45;
  controls.maxDistance = dist * 2.2;
  camera.lookAt(controls.target);

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
  let picked = null;
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
  view.onTap(towers, pick);
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

  view.watch();
  const instance = {
    /** 'after' shows where the suggested moves would leave everyone. */
    show(which) {
      showing = which === 'after' ? 'after' : 'now';
      pick(null);
      settle(showing, 900);
      showArcs(showing === 'after');
    },
    dispose: view.dispose,
  };
  host.__scape = instance;
  return instance;
}
