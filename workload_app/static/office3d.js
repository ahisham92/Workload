/* Selecao+ — the next two weeks as an office (WebGL).
 *
 * Each person sits at a desk with a computer. The paper piled on the desk is
 * the work they have lined up for the next two weeks: the more work, the
 * taller the piles; at a full load they reach the top of the screen. The folder on top of the
 * piles takes the load's colour (blue room, green about right, amber heavy,
 * red over). The manager has the big desk at the head of the room. A red note
 * on a desk is somebody who has been over their hours in the last weeks (from
 * the timesheets), so needs a lighter week whatever is piled up ahead.
 * "Show the suggested moves" carries paper from desk to desk.
 *
 * Loaded on demand by showcase.js; shares its palette, stage, lights and
 * drawing loop with load3d.js. Draws only while something moves.
 */
import * as THREE from './vendor/three/three.module.min.js';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import {
  palette, loadColor, makeStage, makeRenderer, addLights, addPlate, viewer,
} from './load3d.js';

const DESK_H = 0.74;      // desk top height
const FULL = 0.55;        // each pile's height at a full load
const MAX_LOAD = 3;       // three times a full load is as tall as it is drawn
const MAX_PILES = 2;      // a pile each side of the computer
const XG = 2.15;          // desk spacing across
const ZG_WIDE = 2.3;      // desk spacing back to front
const ZG_NARROW = 2.8;    // more on a phone, so the names fit between rows

/** How tall each pile stands for a load: the more work, the taller the
 *  tower of paper (Ahmed, 2026-10-12). At a full load both piles reach the
 *  top of the screen; at twice a full load they stand well above it. */
function piles(load) {
  const h = Math.max(0, Math.min(load || 0, MAX_LOAD)) * FULL;
  return Array.from({ length: MAX_PILES }, () => h);
}

/** A CSS colour, var() included, as the browser resolves it. */
function cssColor(value, fallback = '#7a8494') {
  const probe = document.createElement('span');
  probe.style.color = value;
  probe.style.display = 'none';
  document.body.append(probe);
  const rgb = getComputedStyle(probe).color;
  probe.remove();
  return rgb && rgb.startsWith('rgb') ? rgb : fallback;
}

function mat(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.02, ...extra });
}

function box(w, h, d, material) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

/** A desk, its computer, its chair and somebody working at it. ``facing`` is
 *  +1 when they look towards the back of the room, -1 towards the front.
 *  Returns the group and the parts to tap and to fill with paper. */
function desk(p, { width, depth, color, facing, big }) {
  const g = new THREE.Group();
  const wood = mat(p.dark ? '#6b5440' : '#b88a5e', { roughness: 0.55 });
  const metal = mat(p.dark ? '#3a4150' : '#6f7787', { roughness: 0.4, metalness: 0.4 });
  const top = box(width, 0.06, depth, wood);
  top.position.y = DESK_H - 0.03;
  g.add(top);
  for (const sx of [-1, 1]) {
    const leg = box(0.06, DESK_H - 0.06, depth - 0.1, metal);
    leg.position.set(sx * (width / 2 - 0.08), (DESK_H - 0.06) / 2, 0);
    g.add(leg);
  }
  if (big) {                               // a modesty panel on the manager's desk
    const panel = box(width - 0.2, DESK_H * 0.6, 0.04, wood);
    panel.position.set(0, DESK_H * 0.45, facing * (depth / 2 - 0.06) * -1);
    g.add(panel);
  }
  // the computer, on the far side of the desk from the person
  const far = -facing * (depth / 2 - 0.18);
  const screenW = big ? 0.78 : 0.62;
  const stand = box(0.06, 0.18, 0.06, metal);
  stand.position.set(0, DESK_H + 0.09, far);
  g.add(stand);
  const foot = box(0.22, 0.02, 0.14, metal);
  foot.position.set(0, DESK_H + 0.01, far);
  g.add(foot);
  const frame = box(screenW, 0.4, 0.04, mat('#1d222b', { roughness: 0.3 }));
  frame.position.set(0, DESK_H + 0.38, far);
  g.add(frame);
  const glow = new THREE.Mesh(new THREE.PlaneGeometry(screenW - 0.06, 0.34),
    new THREE.MeshStandardMaterial({ color: '#6fa8ff', emissive: '#3d7be0', emissiveIntensity: p.dark ? 0.9 : 0.55, roughness: 0.2 }));
  glow.position.set(0, DESK_H + 0.38, far + facing * 0.021);
  if (facing < 0) glow.rotation.y = Math.PI;
  g.add(glow);
  const keys = box(0.42, 0.02, 0.14, mat(p.dark ? '#cfd5df' : '#e9ecf1'));
  keys.position.set(0, DESK_H + 0.01, facing * 0.05);
  g.add(keys);
  // the chair and the person
  const near = facing * (depth / 2 + 0.32);
  const chairMat = mat(p.dark ? '#2b3140' : '#3b4252', { roughness: 0.8 });
  const seat = box(0.46, 0.07, 0.44, chairMat);
  seat.position.set(0, 0.46, near);
  g.add(seat);
  const back = box(0.46, 0.5, 0.06, chairMat);
  back.position.set(0, 0.75, near + facing * 0.22);
  g.add(back);
  const post = box(0.05, 0.42, 0.05, metal);
  post.position.set(0, 0.22, near);
  g.add(post);
  const skin = mat('#d9a77f', { roughness: 0.6 });
  const shirt = mat(color, { roughness: 0.65 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.32, 6, 14), shirt);
  body.position.set(0, 0.82, near + facing * 0.04);
  body.rotation.x = -facing * 0.12;
  body.castShadow = true;
  g.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.135, 20, 16), skin);
  head.position.set(0, 1.2, near - facing * 0.03);
  head.castShadow = true;
  g.add(head);
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.14, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2.2),
    mat('#2a221d', { roughness: 0.9 }));
  hair.position.copy(head.position);
  g.add(hair);
  for (const sx of [-1, 1]) {               // arms out to the keyboard
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.05, 0.3, 4, 8), shirt);
    arm.position.set(sx * 0.2, 0.86, near - facing * 0.2);
    arm.rotation.x = Math.PI / 2.4 * -facing;
    arm.castShadow = true;
    g.add(arm);
  }
  return { group: g, taps: [top, body, head, frame, seat, back], far };
}

/** The paper on a desk: ``MAX_PILES`` piles beside the computer, and a
 *  folder in the load's colour on top of the last one. */
function paper(p, group, width) {
  const sheet = mat(p.dark ? '#e7e3d8' : '#fbfaf5', { roughness: 0.92 });
  const edge = new THREE.LineBasicMaterial({ color: p.dark ? '#9a9486' : '#cfcabd' });
  const spots = [-width / 2 + 0.32, width / 2 - 0.32];
  const order = [0, 1];                     // left and right of the computer
  const stacks = order.map((k, i) => {
    const mesh = box(0.26, 1, 0.34, sheet);
    mesh.position.set(spots[k], DESK_H, (i % 2 ? 0.04 : -0.03));
    mesh.rotation.y = (i % 3 - 1) * 0.07;
    mesh.geometry.translate(0, 0.5, 0);
    mesh.scale.y = 0.001;
    const lines = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), edge);
    mesh.add(lines);
    group.add(mesh);
    return mesh;
  });
  const folder = box(0.29, 0.025, 0.37, mat(p.room, { roughness: 0.5 }));
  folder.visible = false;
  group.add(folder);
  function fill(load) {
    const heights = piles(load);
    let topIndex = -1;
    stacks.forEach((s, i) => {
      s.scale.y = Math.max(0.001, heights[i]);
      s.visible = heights[i] > 0.004;
      if (s.visible) topIndex = i;
    });
    if (topIndex >= 0) {
      const s = stacks[topIndex];
      folder.visible = true;
      folder.position.set(s.position.x, DESK_H + heights[topIndex] + 0.012, s.position.z);
      folder.rotation.y = s.rotation.y;
      folder.material.color.copy(loadColor(load, p));
    } else {
      folder.visible = false;
    }
  }
  return { stacks, folder, fill, top: () => stacks.reduce((h, s) => Math.max(h, s.visible ? s.scale.y : 0), 0) };
}

/** The room: a floor, a back wall with windows, a rug under the manager's
 *  desk and a plant in each back corner. */
function room(scene, p, w, d, backZ) {
  addPlate(scene, p, w, d);
  const wall = box(w, 1.7, 0.08, mat(p.dark ? '#2a303b' : '#e8ebf0', { roughness: 0.95 }));
  wall.position.set(0, 0.85, backZ);
  wall.castShadow = false;
  scene.add(wall);
  const pane = new THREE.MeshStandardMaterial({ color: '#bcd7f5', emissive: '#9cc4f0',
    emissiveIntensity: p.dark ? 0.35 : 0.15, roughness: 0.1, metalness: 0.1 });
  const count = Math.max(2, Math.round(w / 2.2));
  for (let i = 0; i < count; i += 1) {
    const x = -w / 2 + (w / count) * (i + 0.5);
    const glass = new THREE.Mesh(new THREE.PlaneGeometry(w / count - 0.5, 0.75), pane);
    glass.position.set(x, 1.05, backZ + 0.045);
    scene.add(glass);
  }
  for (const sx of [-1, 1]) {
    const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.13, 0.32, 18), mat('#8c6b52'));
    pot.position.set(sx * (w / 2 - 0.35), 0.16, backZ + 0.35);
    pot.castShadow = true;
    scene.add(pot);
    const leaves = new THREE.Mesh(new THREE.IcosahedronGeometry(0.32, 1), mat('#3f8f5a', { roughness: 0.85 }));
    leaves.position.set(sx * (w / 2 - 0.35), 0.62, backZ + 0.35);
    leaves.scale.set(1, 1.25, 1);
    leaves.castShadow = true;
    scene.add(leaves);
  }
}

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
  renderer.domElement.setAttribute('aria-label', model.summary || 'The team\'s next two weeks, as an office');

  const scene = new THREE.Scene();
  const W = () => stage.clientWidth || 320;
  const H = () => Math.round(Math.min(480, Math.max(narrow ? 340 : 340, W() * (narrow ? 1.15 : 0.45))));
  const camera = new THREE.PerspectiveCamera(narrow ? 40 : 32, W() / H(), 0.1, 200);

  // ---- who sits where: the manager at the head of the room, everybody else
  // in rows facing them
  const ZG = narrow ? ZG_NARROW : ZG_WIDE;
  const bossIndex = model.people.findIndex((x) => x.manager);
  const team = model.people.map((x, i) => i).filter((i) => i !== bossIndex);
  const COLS = Math.max(1, Math.min(narrow ? 2 : 4, team.length));
  const ROWS = Math.max(1, Math.ceil(team.length / COLS));
  const roomW = Math.max(COLS * XG + 0.8, 5);
  const bossZ = bossIndex >= 0 ? -1.2 : 0;
  const firstRowZ = bossIndex >= 0 ? 1.25 : 0;
  const backZ = (bossIndex >= 0 ? bossZ - 1.35 : -1.4);
  const frontZ = firstRowZ + (ROWS - 1) * ZG + 1.45;
  const roomD = frontZ - backZ;
  const where = new Map();
  team.forEach((i, k) => {
    const col = k % COLS; const row = Math.floor(k / COLS);
    const inRow = Math.min(COLS, team.length - row * COLS);
    where.set(i, { x: (col - (inRow - 1) / 2) * XG, z: firstRowZ + row * ZG });
  });
  if (bossIndex >= 0) where.set(bossIndex, { x: 0, z: bossZ });

  // ---- light and room
  const span = Math.max(roomW, roomD);
  addLights(scene, p, span, [-0.35, 1.0, 0.6], 2048);
  const floorCentre = (backZ + frontZ) / 2;
  const roomGroup = new THREE.Group();
  room(roomGroup, p, roomW, roomD, backZ - floorCentre);
  roomGroup.position.z = floorCentre;
  scene.add(roomGroup);
  if (bossIndex >= 0) {
    const rug = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 2.2),
      mat(p.dark ? '#33405a' : '#cfd9ea', { roughness: 1 }));
    rug.rotation.x = -Math.PI / 2;
    rug.position.set(0, 0.002, bossZ - 0.15);
    rug.receiveShadow = true;
    scene.add(rug);
  }

  // ---- the desks
  const desks = model.people.map((person, i) => {
    const big = i === bossIndex;
    const width = big ? 2.3 : 1.6;
    const depth = big ? 1.0 : 0.78;
    // the team looks to the head of the room; the manager looks at the team
    const facing = big ? -1 : 1;
    const built = desk(p, { width, depth, color: cssColor(person.color || 'var(--muted)'), facing, big });
    const at = where.get(i);
    built.group.position.set(at.x, 0, at.z);
    scene.add(built.group);
    const pile = paper(p, built.group, width);
    pile.fill(reduced ? person.now : 0);
    const taps = [...built.taps, ...pile.stacks];
    taps.forEach((m) => { m.userData.i = i; });
    let note = null;
    if (person.rest) {                       // a red note: over their hours lately
      note = box(0.16, 0.005, 0.16, mat(p.over, { roughness: 0.6 }));
      note.position.set(width / 2 - 0.18, DESK_H + 0.004, facing * 0.18);
      note.rotation.y = 0.3;
      built.group.add(note);
      const pin = box(0.012, 0.42, 0.012, mat(p.over));
      pin.position.set(width / 2 - 0.12, DESK_H + 0.21, -facing * (depth / 2 - 0.1));
      built.group.add(pin);
      const flag = box(0.22, 0.14, 0.01, mat(p.over, { emissive: p.over, emissiveIntensity: 0.25 }));
      flag.position.set(width / 2 - 0.12 - 0.11, DESK_H + 0.35, -facing * (depth / 2 - 0.1));
      built.group.add(flag);
      taps.push(flag);
      flag.userData.i = i;
    }
    return { person, at, big, width, pile, taps, group: built.group };
  });

  // ---- the moves: paper carried from the giver's desk to the taker's
  const arcs = new THREE.Group();
  arcs.visible = false;
  scene.add(arcs);
  const arcMat = new THREE.MeshStandardMaterial({ color: p.glass, emissive: p.glass, emissiveIntensity: 0.35, roughness: 0.4 });
  const arcInfo = [];
  const pileTop = (d, load) => DESK_H + Math.max(...piles(load)) + 0.05;
  model.moves.forEach((move, k) => {
    const a = model.people.findIndex((x) => x.name === move.from);
    const b = model.people.findIndex((x) => x.name === move.to);
    if (a < 0 || b < 0) return;
    const da = desks[a]; const db = desks[b];
    const ha = pileTop(da, da.person.now); const hb = pileTop(db, db.person.after);
    const lift = Math.max(ha, hb) + 1.0 + k * 0.3;
    const xa = da.at.x - da.width / 2 + 0.32; const xb = db.at.x - db.width / 2 + 0.32;
    const curve = new THREE.CubicBezierCurve3(
      new THREE.Vector3(xa, ha, da.at.z), new THREE.Vector3(xa, lift, da.at.z),
      new THREE.Vector3(xb, lift, db.at.z), new THREE.Vector3(xb, hb + 0.25, db.at.z));
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 60, 0.04, 8, false), arcMat);
    tube.geometry.setDrawRange(0, 0);
    arcs.add(tube);
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.28, 16), arcMat);
    head.position.copy(curve.getPoint(1));
    head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), curve.getTangent(1).normalize());
    head.visible = false;
    arcs.add(head);
    const sheet = box(0.26, 0.03, 0.34, mat(p.dark ? '#e7e3d8' : '#fbfaf5'));
    sheet.visible = false;
    arcs.add(sheet);
    arcInfo.push({ tube, head, sheet, curve, mid: curve.getPoint(0.5), label: move.label });
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
  desks.forEach((d) => {
    const front = d.big ? d.at.z - 0.95 : d.at.z + 0.95;
    const a = label(d.big ? `${d.person.name} · manager` : d.person.name,
      new THREE.Vector3(d.at.x, d.big ? 1.45 : 0, d.big ? d.at.z - 0.6 : front),
      'scape3d-name', d.big ? 'translate(-50%, calc(-100% - 2px))' : 'translate(-50%, 4px)');
    a.node.style.setProperty('--dot', d.person.color || 'var(--muted)');
    if (d.person.rest) {
      const flag = document.createElement('span');
      flag.className = 'scape3d-rest';
      flag.textContent = narrow ? 'lighter week' : 'needs a lighter week';
      a.node.append(flag);
    }
  });
  const pcts = desks.map((d) => label(`${Math.round(d.person.now * 100)}%`,
    new THREE.Vector3(d.at.x - d.width / 2 + 0.32, DESK_H + 0.1, d.at.z), 'scape3d-pct',
    'translate(-50%, calc(-100% - 6px))'));
  const arcLabels = arcInfo.map((info) => {
    const a = label(info.label, info.mid, 'scape3d-move', 'translate(-50%, -50%)');
    a.node.hidden = true;
    return a;
  });

  // ---- camera: fit the room, centred, from the front and above
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.enablePan = false;
  controls.minPolarAngle = 0.3;
  controls.maxPolarAngle = 1.35;
  controls.rotateSpeed = 0.6;
  const view = viewer({ host, stage, renderer, scene, camera, controls, anchors, W, H });
  const { draw } = view;
  const hull = [];
  for (const x of [-roomW / 2, roomW / 2]) {
    for (const z of [backZ, frontZ]) {
      hull.push(new THREE.Vector3(x, -0.1, z));
    }
    hull.push(new THREE.Vector3(x, 1.75, backZ));
  }
  desks.forEach((d) => hull.push(new THREE.Vector3(d.at.x, DESK_H + 0.2 + Math.max(...piles(Math.max(d.person.now, d.person.after))), d.at.z)));
  if (model.moves.length) desks.forEach((d) => hull.push(new THREE.Vector3(d.at.x, DESK_H + 0.9 + Math.max(...piles(Math.max(d.person.now, d.person.after))), d.at.z)));
  const probe = new THREE.PerspectiveCamera();
  const tilt = narrow ? 0.82 : 0.95;
  const dir = new THREE.Vector3(Math.sin(0.18) * Math.sin(tilt), Math.cos(tilt), Math.cos(0.18) * Math.sin(tilt));
  const home = () => {
    const target = new THREE.Vector3(0, 0.6, floorCentre);
    probe.fov = camera.fov; probe.aspect = W() / H(); probe.near = 0.1; probe.far = 400;
    probe.updateProjectionMatrix();
    const q = new THREE.Vector3();
    const fit = (dist) => {
      probe.position.copy(target).addScaledVector(dir, dist);
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
      const mid = (lo + hi) / 2; const bb = fit(mid);
      if (bb.x1 - bb.x0 <= 1.86 && bb.y1 - bb.y0 <= 1.76) hi = mid; else lo = mid;
    }
    const bb = fit(hi);
    return { target, pos: target.clone().addScaledVector(dir, hi), shift: [(bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2] };
  };
  view.size();
  const start = home();
  view.size(start.shift);
  controls.target.copy(start.target);
  camera.position.copy(start.pos);
  const dist = camera.position.distanceTo(controls.target);
  controls.minDistance = dist * 0.4;
  controls.maxDistance = dist * 2.0;
  camera.lookAt(controls.target);

  const placePct = (d, i, load) => {
    pcts[i].pos.y = DESK_H + Math.max(...piles(load)) + 0.08;
  };

  /** Pile every desk to the given loads, over a moment. */
  function settle(key, ms) {
    const from = desks.map((d) => d.shown ?? 0);
    const to = desks.map((d) => d.person[key]);
    const t0 = performance.now();
    const step = (now) => {
      const k = reduced ? 1 : Math.min(1, (now - t0) / ms);
      const e = 1 - (1 - k) ** 3;
      desks.forEach((d, i) => {
        const v = from[i] + (to[i] - from[i]) * e;
        d.shown = v;
        d.pile.fill(v);
        placePct(d, i, v);
        pcts[i].node.textContent = `${Math.round(Math.max(0, k >= 1 ? to[i] : v) * 100)}%`;
      });
      draw();
      if (k < 1 && renderer.domElement.isConnected) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /** Draw the moves in, one after the other, a sheet riding each. */
  function showArcs(on) {
    arcs.visible = on;
    arcLabels.forEach((a) => { a.node.hidden = true; });
    if (!on) { draw(); return; }
    const t0 = performance.now();
    const step = (now) => {
      let done = true;
      arcInfo.forEach((info, k) => {
        const kk = reduced ? 1 : Math.min(1, Math.max(0, (now - t0 - k * 250) / 800));
        if (kk < 1) done = false;
        const count = info.tube.geometry.index.count;
        info.tube.geometry.setDrawRange(0, Math.floor(count * kk / 6) * 6);
        info.head.visible = kk >= 1;
        info.sheet.visible = kk > 0 && kk < 1;
        if (info.sheet.visible) info.sheet.position.copy(info.curve.getPoint(kk));
        arcLabels[k].node.hidden = kk < 1;
      });
      draw();
      if (!done && renderer.domElement.isConnected) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // the paper piles up, and the view swings in
  desks.forEach((d, i) => placePct(d, i, reduced ? d.person.now : 0));
  if (!reduced) {
    const t0 = performance.now();
    const to = start.pos.clone();
    const from = to.clone().sub(start.target).applyAxisAngle(new THREE.Vector3(0, 1, 0), -0.4)
      .multiplyScalar(1.1).add(start.target);
    camera.position.copy(from);
    const rise = (now) => {
      const k = Math.min(1, (now - t0) / 1100);
      const e = 1 - (1 - k) ** 3;
      desks.forEach((d, i) => {
        const lag = (i / N) * 0.3;
        const kb = Math.min(1, Math.max(0, (k - lag) / (1 - lag)));
        const v = d.person.now * (1 - (1 - kb) ** 3);
        d.shown = v;
        d.pile.fill(v);
        placePct(d, i, v);
      });
      camera.position.lerpVectors(from, to, e);
      camera.lookAt(controls.target);
      draw();
      if (k < 1 && renderer.domElement.isConnected) requestAnimationFrame(rise);
    };
    requestAnimationFrame(rise);
  } else {
    desks.forEach((d) => { d.shown = d.person.now; });
    draw();
  }

  // ---- reading a desk
  let picked = null;
  let showing = 'now';
  function pick(mesh, x, y) {
    if (picked !== null) desks[picked].pile.stacks.forEach((s) => s.material.emissive.setHex(0x000000));
    picked = mesh ? mesh.userData.i : null;
    if (picked === null || picked === undefined) { picked = null; tip.hidden = true; draw(); return; }
    const d = desks[picked];
    d.pile.stacks.forEach((s) => { s.material.emissive = new THREE.Color(p.glass).multiplyScalar(0.25); });
    tip.replaceChildren();
    const b = document.createElement('b'); b.textContent = d.person.name;
    const s = document.createElement('span'); s.textContent = model.text(d.person, showing);
    tip.append(b, s);
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max(4, x + 12), W() - 210)}px`;
    tip.style.top = `${Math.min(Math.max(4, y - 60), H() - 90)}px`;
    draw();
  }
  view.onTap(desks.flatMap((d) => d.taps), pick);
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

export { piles };
