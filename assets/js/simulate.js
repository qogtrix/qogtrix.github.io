/* AI Engineering Laboratory — Stage 6 simulation workspace.
   Rigid-body dynamics with Rapier 0.14.0 (real engine, in-browser)
   + analytical solvers via the backend job API.
   Units: the model is in millimetres; Rapier works in metres.
   Rapier lessons applied (see backend/test_stage6_rapier.mjs):
   - lockTranslations() locks ALL axes — use enabledTranslations.
   - Forces/torques accumulate in separate accumulators — reset
     both each step before applying a fresh continuous force.
*/
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { evaluateModel, meshVolume } from './model-kernel.js';
import RAPIER from '@dimforge/rapier3d-compat';

const $ = (id) => document.getElementById(id);
const API = () => window.AIELAB_API_BASE || 'http://127.0.0.1:8001';
const token = () => localStorage.getItem('aielab.token') || '';
async function api(path, opts = {}) {
  const res = await (window.aielabFetchWithWake || fetch)(API() + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(token() ? { Authorization: 'Bearer ' + token() } : {}), ...(opts.headers || {}) },
  }, (attempt) => setStatus('Waking the server… (retry ' + attempt + ')', true));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function setStatus(msg, warn) { const el = $('sim-status'); el.textContent = msg; el.classList.toggle('warn', !!warn); }
function fmt(n, unit) { if (n == null || !isFinite(n)) return '—'; return (Math.abs(n) >= 1000 ? n.toExponential(3) : n.toFixed(4)) + (unit ? ' ' + unit : ''); }

// ---------------------------------------------------------------- tabs
document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
  b.classList.add('active');
  ['rigid', 'analytical', 'jobs'].forEach((t) => { $('tab-' + t).hidden = t !== b.dataset.tab; });
  if (b.dataset.tab === 'jobs') loadJobs();
}));

// ---------------------------------------------------------------- shared state
let projectId = '', projectName = '';
let model = null;             // {version, units, components}
let materialsById = {};       // material id -> {density_kg_m3, ...}
let rapierReady = false;

// ---------------------------------------------------------------- projects
async function loadProjects() {
  try {
    const data = await api('/api/v1/projects');
    const sel = $('project-select');
    (data.projects || []).forEach((p) => {
      const o = document.createElement('option'); o.value = p.id; o.textContent = p.name; sel.appendChild(o);
    });
  } catch (e) { setStatus('Sign in to load your projects. ' + e.message, true); }
}
async function loadMaterials() {
  try {
    const data = await api('/api/v1/materials');
    (data.materials || []).forEach((m) => { materialsById[m.id] = m; });
    if (Object.keys(materialsById).length) return;
  } catch (e) { /* backend not running — fall back to the static file */ }
  try {
    const data = await (await fetch('data/materials.json')).json();
    (data.materials || []).forEach((m) => { materialsById[m.id] = m; });
  } catch (e) { /* no material data available; masses fall back to 1000 kg/m3 */ }
}
function materialDensity(mat) {
  if (!mat) return null;
  if (mat.properties && mat.properties.density_kg_m3 != null) return mat.properties.density_kg_m3;
  return mat.density_kg_m3 != null ? mat.density_kg_m3 : null;
}
$('project-select').addEventListener('change', (e) => { projectId = e.target.value; projectName = e.target.selectedOptions[0]?.textContent || ''; });

// ---------------------------------------------------------------- 3D scene
let renderer, scene, camera, controls, clock;
function initScene() {
  const viewer = $('viewer');
  // #viewer-stats lives inside #viewer — remove only the old canvas,
  // or the stats element is destroyed and later writes crash on it
  // ("Cannot set properties of null (setting 'textContent')").
  viewer.querySelectorAll('canvas').forEach((c) => c.remove());
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(viewer.clientWidth, 520);
  viewer.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0e14);
  camera = new THREE.PerspectiveCamera(50, viewer.clientWidth / 520, 0.1, 100000);
  camera.position.set(800, 600, 900);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 100, 0);
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dl = new THREE.DirectionalLight(0xffffff, 1.2); dl.position.set(500, 900, 400); scene.add(dl);
  const grid = new THREE.GridHelper(2000, 40, 0x2a3348, 0x1a2233); scene.add(grid);
  const axes = new THREE.AxesHelper(300); scene.add(axes);
  clock = new THREE.Clock();
  (function loop() { requestAnimationFrame(loop); if (renderer) { controls.update(); renderer.render(scene, camera); } })();
}

// ---------------------------------------------------------------- rigid-body sim
let world = null, rapierBodies = new Map(), bodyMeshes = new Map();
let running = false, simT = 0, series = [], contactsSeen = 0, continuousForces = [];
let selectedBodyId = null;
let groundCollider = null;

async function ensureRapier() {
  if (!rapierReady) { await RAPIER.init(); rapierReady = true; }
}
function massOf(comp, volMm3) {
  const mat = comp.material_id ? materialsById[comp.material_id] : null;
  const rho = materialDensity(mat) || 1000;
  return { rho, massKg: (volMm3 / 1e9) * rho };
}
async function loadModel() {
  projectId = $('project-select').value;
  if (!projectId) { setStatus('Choose a project first.', true); return; }
  await ensureRapier();
  try {
    const res = await api('/api/v1/projects/' + projectId + '/model');
    model = res.model;
    await loadMaterials();
    await buildSceneAndWorld();
    setStatus('Model loaded: ' + model.components.length + ' components, version ' + model.version + '. Set body types, then Run.');
  } catch (e) { setStatus('Could not load the model: ' + e.message, true); }
}
$('load-model').addEventListener('click', loadModel);

async function buildSceneAndWorld() {
  initScene();
  if (world) { try { world.free(); } catch (e) {} }
  world = new RAPIER.World({ x: 0, y: -parseFloat($('gravity').value || 9.81), z: 0 });
  world.timestep = 1 / 60;
  rapierBodies = new Map(); bodyMeshes = new Map(); series = []; simT = 0; contactsSeen = 0; continuousForces = [];
  running = false; $('run-sim').disabled = false; $('pause-sim').disabled = true; $('step-sim').disabled = true; $('save-results').disabled = true;
  const { objects, errors } = await evaluateModel(model);
  if (errors.length) { setStatus('Model errors: ' + errors.join('; '), true); }
  const restitution = parseFloat($('restitution').value || 0.3);
  const friction = parseFloat($('friction').value || 0.5);
  const topLevel = model.components.filter((c) => !c.parent_id);
  // Assembly hierarchy, as in the modeller: children attach to parents.
  model.components.forEach((c) => {
    const obj = objects.get(c.id);
    if (!obj) return;
    if (c.parent_id && objects.get(c.parent_id)) objects.get(c.parent_id).add(obj);
    else scene.add(obj);
  });
  scene.updateMatrixWorld(true);
  // World bounding box of each top-level component (children included).
  let minY = Infinity;
  const boxes = new Map();
  for (const comp of topLevel) {
    const mesh = objects.get(comp.id);
    if (!mesh) continue;
    const box = new THREE.Box3().setFromObject(mesh);
    if (box.isEmpty()) continue;
    boxes.set(comp.id, box);
    minY = Math.min(minY, box.min.y);
  }
  const liftM = isFinite(minY) ? -minY / 1000 : 0; // metres to lift so the lowest point rests on y = 0
  if ($('ground').value === 'on') {
    const groundBody = world.createRigidBody(RAPIER.RigidBodyDesc.fixed().setTranslation(0, -0.05, 0));
    groundCollider = world.createCollider(RAPIER.ColliderDesc.cuboid(50, 0.05, 50).setRestitution(restitution).setFriction(friction), groundBody);
    const floor = new THREE.Mesh(new THREE.BoxGeometry(4000, 20, 4000), new THREE.MeshStandardMaterial({ color: 0x1c2436 }));
    floor.position.y = -10; scene.add(floor);
  }
  for (const comp of topLevel) {
    const mesh = objects.get(comp.id);
    if (!mesh) continue;
    const box = boxes.get(comp.id);
    if (!box) continue;
    const vol = meshVolume(mesh);
    const { rho } = massOf(comp, vol);
    const size = new THREE.Vector3().subVectors(box.max, box.min);
    const centre = new THREE.Vector3().addVectors(box.min, box.max).multiplyScalar(0.5);
    // The mesh's geometry centre relative to its own origin (mm).
    // The Rapier body sits at the world centre; each step the mesh is
    // placed at body - rotated(local centre) so the two stay aligned.
    const localCentre = centre.clone().sub(mesh.position);
    const q = mesh.quaternion;
    const desc = RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(centre.x / 1000, centre.y / 1000 + liftM, centre.z / 1000)
      .setRotation({ x: q.x, y: q.y, z: q.z, w: q.w });
    const rb = world.createRigidBody(desc);
    let collider;
    if (comp.kind === 'sphere') {
      collider = RAPIER.ColliderDesc.ball(Math.max(Math.max(size.x, size.y, size.z) / 2000, 0.001));
    } else {
      // Bounding-box cuboid for everything else (stated approximation).
      collider = RAPIER.ColliderDesc.cuboid(Math.max(size.x / 2000, 0.001), Math.max(size.y / 2000, 0.001), Math.max(size.z / 2000, 0.001));
    }
    collider.setDensity(rho).setRestitution(restitution).setFriction(friction);
    world.createCollider(collider, rb);
    rapierBodies.set(comp.id, { rb, collider, comp, volMm3: vol, density: rho });
    bodyMeshes.set(comp.id, mesh);
    mesh.userData.bodyOffset = localCentre;
  }
  renderBodiesList();
  const vs = $('viewer-stats');
  if (vs) vs.textContent = topLevel.length + ' bodies · gravity ' + $('gravity').value + ' m/s² · timestep 1/60 s';
}
function renderBodiesList() {
  const list = $('bodies-list');
  list.innerHTML = '';
  const mk = (selId, label) => {
    const sel = $(selId); sel.innerHTML = '';
    rapierBodies.forEach((b, id) => { const o = document.createElement('option'); o.value = id; o.textContent = b.comp.name || id; sel.appendChild(o); });
  };
  mk('force-body'); mk('spring-body'); mk('joint-a'); mk('joint-b');
  rapierBodies.forEach((b, id) => {
    const row = document.createElement('div');
    row.className = 'field-row';
    row.innerHTML = '<label>' + esc(b.comp.name || id) + '<br><span class="small muted">mass ' + fmt(b.rb.mass(), 'kg') + ' · ' + esc(b.comp.kind) + '</span></label>';
    const sel = document.createElement('select');
    sel.dataset.body = id;
    sel.innerHTML = '<option value="dynamic">Dynamic</option><option value="fixed">Static</option><option value="kinematic">Kinematic</option>';
    sel.addEventListener('change', () => {
      const type = sel.value === 'fixed' ? RAPIER.RigidBodyType.Fixed : sel.value === 'kinematic' ? RAPIER.RigidBodyType.KinematicPosition : RAPIER.RigidBodyType.Dynamic;
      b.rb.setBodyType(type, true);
    });
    row.appendChild(sel);
    list.appendChild(row);
  });
}
function countContacts() {
  let n = 0;
  const cols = [...rapierBodies.values()].map((b) => b.collider);
  for (let i = 0; i < cols.length; i++) for (let j = i + 1; j < cols.length; j++) {
    world.contactPair(cols[i], cols[j], (manifold) => { if (manifold.numContacts() > 0) n++; });
  }
  if (groundCollider) for (const c of cols) {
    world.contactPair(c, groundCollider, (manifold) => { if (manifold.numContacts() > 0) n++; });
  }
  return n;
}
function syncMeshes() {
  rapierBodies.forEach((b, id) => {
    const mesh = bodyMeshes.get(id);
    if (!mesh) return;
    const t = b.rb.translation(), r = b.rb.rotation();
    const quat = new THREE.Quaternion(r.x, r.y, r.z, r.w);
    const off = (mesh.userData.bodyOffset || new THREE.Vector3()).clone().applyQuaternion(quat);
    // Rendered centre = mesh.position + rotated local centre = body position.
    mesh.position.set(t.x * 1000 - off.x, t.y * 1000 - off.y, t.z * 1000 - off.z);
    mesh.quaternion.copy(quat);
  });
}
function totalKE() {
  // Translational kinetic energy only (rotational KE needs the
  // body's inertia tensor, which is not read here — labelled as such).
  let ke = 0;
  rapierBodies.forEach((b) => { const v = b.rb.linvel(); ke += 0.5 * b.rb.mass() * (v.x ** 2 + v.y ** 2 + v.z ** 2); });
  return ke;
}
function recordStep() {
  const first = [...rapierBodies.values()].find((b) => b.rb.bodyType() === RAPIER.RigidBodyType.Dynamic);
  const y = first ? first.rb.translation().y : 0;
  series.push({ t: +simT.toFixed(3), y: +y.toFixed(4), ke: +totalKE().toFixed(3) });
}
function drawChart(canvas, data, key, label) {
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#2a3348'; ctx.beginPath(); ctx.moveTo(30, 10); ctx.lineTo(30, 120); ctx.lineTo(510, 120); ctx.stroke();
  if (!data.length) { ctx.fillStyle = '#8b93a7'; ctx.fillText('No data yet', 40, 60); return; }
  const xs = data.map((d) => d.t), ys = data.map((d) => d[key]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, 0.001), y0 = Math.min(...ys), y1 = Math.max(...ys, y0 + 1e-9);
  ctx.strokeStyle = '#4f8cff'; ctx.lineWidth = 2; ctx.beginPath();
  data.forEach((d, i) => { const x = 30 + ((d.t - x0) / (x1 - x0)) * 470; const y = 120 - ((d[key] - y0) / (y1 - y0)) * 105; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke(); ctx.lineWidth = 1;
  ctx.fillStyle = '#8b93a7'; ctx.fillText(label + '  min ' + y0.toFixed(2) + '  max ' + y1.toFixed(2), 34, 16);
}
function updateLive() {
  drawChart($('chart-height'), series, 'y', 'height (m)');
  drawChart($('chart-energy'), series, 'ke', 'KE (J)');
  const rows = [];
  rapierBodies.forEach((b, id) => {
    const t = b.rb.translation(), v = b.rb.linvel();
    rows.push('<tr><td>' + esc(b.comp.name || id) + '</td><td>' + fmt(t.x, 'm') + ', ' + fmt(t.y, 'm') + ', ' + fmt(t.z, 'm') + '</td><td>' + fmt(Math.hypot(v.x, v.y, v.z), 'm/s') + '</td><td>' + fmt(b.rb.mass(), 'kg') + '</td></tr>');
  });
  $('live-results').innerHTML = '<table><tr><th>Body</th><th>Position</th><th>Speed</th><th>Mass</th></tr>' + rows.join('') + '</table><p class="small muted">t = ' + simT.toFixed(2) + ' s · contacts: ' + contactsSeen + ' · translational KE ' + fmt(totalKE(), 'J') + '</p>';
}
function stepOnce() {
  // Apply continuous forces fresh each step (reset accumulators first).
  for (const f of continuousForces) {
    const b = rapierBodies.get(f.bodyId); if (!b) continue;
    b.rb.resetForces(true); b.rb.resetTorques(true);
    b.rb.addForce({ x: f.fx, y: f.fy, z: f.fz }, true);
  }
  world.step();
  simT += 1 / 60;
  if (Math.round(simT * 60) % 30 === 0) contactsSeen = countContacts();
  recordStep();
  syncMeshes();
  updateLive();
}
function simLoop() {
  if (!running) return;
  const dur = parseFloat($('duration').value || 5);
  if (simT >= dur) { running = false; $('run-sim').disabled = false; $('pause-sim').disabled = true; $('step-sim').disabled = true; finishSummary(); return; }
  stepOnce();
  requestAnimationFrame(simLoop);
}
function finishSummary() {
  const first = [...rapierBodies.values()].find((b) => b.rb.bodyType() === RAPIER.RigidBodyType.Dynamic);
  const summary = {
    duration_s: +simT.toFixed(2), timestep_s: 1 / 60, gravity_m_s2: parseFloat($('gravity').value || 9.81),
    bodies: [...rapierBodies.values()].map((b) => {
      const t = b.rb.translation(), v = b.rb.linvel();
      return { id: b.comp.id, name: b.comp.name, mass_kg: +b.rb.mass().toFixed(4),
               final_position_m: [+t.x.toFixed(3), +t.y.toFixed(3), +t.z.toFixed(3)],
               final_speed_m_s: +Math.hypot(v.x, v.y, v.z).toFixed(3) };
    }),
    contacts: contactsSeen, final_translational_ke_J: +totalKE().toFixed(3),
  };
  window.__lastSimSummary = { summary, series };
  $('sim-summary').innerHTML = '<table><tr><th>Body</th><th>Final position (m)</th><th>Final speed</th></tr>' +
    summary.bodies.map((b) => '<tr><td>' + esc(b.name) + '</td><td>' + b.final_position_m.join(', ') + '</td><td>' + b.final_speed_m_s + ' m/s</td></tr>').join('') +
    '</table><p class="small muted">Duration ' + summary.duration_s + ' s · contacts ' + contactsSeen + ' · final translational KE ' + summary.final_translational_ke_J + ' J · collision shapes: bounding boxes (ball for spheres) · engine Rapier 0.14.0, timestep 1/60 s.</p>';
  $('save-results').disabled = false;
  setStatus('Simulation finished at t = ' + simT.toFixed(2) + ' s.');
}
$('run-sim').addEventListener('click', () => {
  if (!world) { setStatus('Load a model first.', true); return; }
  if (simT >= parseFloat($('duration').value || 5)) { resetSim(); }
  running = true; $('run-sim').disabled = true; $('pause-sim').disabled = false; $('step-sim').disabled = true;
  requestAnimationFrame(simLoop);
});
$('pause-sim').addEventListener('click', () => { running = false; $('run-sim').disabled = false; $('pause-sim').disabled = true; $('step-sim').disabled = false; });
$('step-sim').addEventListener('click', () => { if (!world) return; stepOnce(); });
async function resetSim() { if (!world) return; running = false; try { await buildSceneAndWorld(); } catch (e) { setStatus('Could not rebuild the scene: ' + e.message, true); } $('live-results').innerHTML = '<p class="muted">Nothing running yet.</p>'; $('sim-summary').innerHTML = '<p class="muted">Run a simulation to see its summary.</p>'; }
$('reset-sim').addEventListener('click', resetSim);
$('apply-force').addEventListener('click', () => {
  const b = rapierBodies.get($('force-body').value);
  if (!b) { setStatus('Load a model first.', true); return; }
  const [fx, fy, fz] = $('force-vec').value.split(',').map((s) => parseFloat(s.trim()) || 0);
  if ($('force-mode').value === 'impulse') { b.rb.applyImpulse({ x: fx, y: fy, z: fz }, true); setStatus('Impulse applied to ' + (b.comp.name || b.comp.id) + '.'); }
  else { continuousForces.push({ bodyId: b.comp.id, fx, fy, fz }); setStatus('Continuous force ' + fx + ', ' + fy + ', ' + fz + ' N applied to ' + (b.comp.name || b.comp.id) + ' (re-applied every step).'); }
});
$('add-spring').addEventListener('click', () => {
  const b = rapierBodies.get($('spring-body').value);
  if (!b) { setStatus('Load a model first.', true); return; }
  const [ax, ay, az] = $('spring-anchor').value.split(',').map((s) => parseFloat(s.trim()) || 0);
  const k = parseFloat($('spring-k').value || 40), c = parseFloat($('spring-c').value || 1);
  const anchorBody = world.createRigidBody(RAPIER.RigidBodyDesc.fixed().setTranslation(ax, ay, az));
  const p = b.rb.translation();
  const rest = Math.hypot(p.x - ax, p.y - ay, p.z - az);
  world.createImpulseJoint(RAPIER.JointData.spring(rest, k, c, { x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 0 }), b.rb, anchorBody, true);
  setStatus('Spring added: k = ' + k + ' N/m, damping ' + c + ', rest length ' + rest.toFixed(2) + ' m.');
});
$('add-joint').addEventListener('click', () => {
  const a = rapierBodies.get($('joint-a').value), b = rapierBodies.get($('joint-b').value);
  if (!a || !b || a === b) { setStatus('Pick two different bodies.', true); return; }
  const id = { x: 0, y: 0, z: 0, w: 1 };
  const data = $('joint-type').value === 'fixed'
    ? RAPIER.JointData.fixed({ x: 0, y: 0, z: 0 }, id, { x: 0, y: 0, z: 0 }, id)
    : RAPIER.JointData.revolute({ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: 1 });
  world.createImpulseJoint(data, a.rb, b.rb, true);
  setStatus($('joint-type').value + ' joint added between ' + (a.comp.name || a.comp.id) + ' and ' + (b.comp.name || b.comp.id) + '.');
});
$('save-results').addEventListener('click', async () => {
  if (!window.__lastSimSummary) return;
  try {
    const job = await api('/api/v1/simulations', { method: 'POST', body: JSON.stringify({ project_id: projectId, solver: 'rigid_body', inputs: { gravity_m_s2: parseFloat($('gravity').value || 9.81), duration_s: parseFloat($('duration').value || 5) } }) });
    const done = await api('/api/v1/simulations/' + job.id + '/results', { method: 'POST', body: JSON.stringify({ results: window.__lastSimSummary }) });
    setStatus('Results saved as job ' + done.id + ' (status ' + done.status + ').');
  } catch (e) { setStatus('Could not save results: ' + e.message, true); }
});

// ---------------------------------------------------------------- analytical solvers
let solvers = {};
const SOLVER_FIELDS = {
  cantilever_beam: [
    { key: 'length_m', label: 'Length (m)', type: 'number', value: 3 },
    { key: 'load_N', label: 'Point load at free end (N)', type: 'number', value: 1000 },
    { key: 'section', label: 'Cross-section', type: 'section' },
    { key: 'material_id', label: 'Material', type: 'material' },
  ],
  simply_supported_beam: [
    { key: 'length_m', label: 'Length (m)', type: 'number', value: 3 },
    { key: 'load_N', label: 'Centre point load (N)', type: 'number', value: 1000 },
    { key: 'section', label: 'Cross-section', type: 'section' },
    { key: 'material_id', label: 'Material', type: 'material' },
  ],
  axial_bar: [
    { key: 'length_m', label: 'Length (m)', type: 'number', value: 1 },
    { key: 'force_N', label: 'Axial force (N, + tension)', type: 'number', value: 10000 },
    { key: 'section', label: 'Cross-section', type: 'section' },
    { key: 'material_id', label: 'Material', type: 'material' },
  ],
  torsion_shaft: [
    { key: 'length_m', label: 'Length (m)', type: 'number', value: 1 },
    { key: 'torque_Nm', label: 'Torque (N·m)', type: 'number', value: 100 },
    { key: 'diameter_m', label: 'Diameter (m)', type: 'number', value: 0.02 },
    { key: 'material_id', label: 'Material', type: 'material' },
  ],
  thermal_conduction: [
    { key: 'thickness_m', label: 'Thickness (m)', type: 'number', value: 0.01 },
    { key: 'area_m2', label: 'Area (m²)', type: 'number', value: 1 },
    { key: 't_hot_C', label: 'Hot side (°C)', type: 'number', value: 100 },
    { key: 't_cold_C', label: 'Cold side (°C)', type: 'number', value: 0 },
    { key: 'material_id', label: 'Material', type: 'material' },
  ],
  lumped_thermal: [
    { key: 'volume_m3', label: 'Volume (m³)', type: 'number', value: 0.001 },
    { key: 'area_m2', label: 'Surface area (m²)', type: 'number', value: 0.06 },
    { key: 'h_W_m2K', label: 'Heat-transfer coefficient h (W/m²K)', type: 'number', value: 10 },
    { key: 't0_C', label: 'Initial temperature (°C)', type: 'number', value: 100 },
    { key: 't_inf_C', label: 'Surroundings (°C)', type: 'number', value: 25 },
    { key: 'duration_s', label: 'Duration (s)', type: 'number', value: 3600 },
    { key: 'material_id', label: 'Material', type: 'material' },
  ],
  drag: [
    { key: 'velocity_m_s', label: 'Velocity (m/s)', type: 'number', value: 30 },
    { key: 'area_m2', label: 'Reference area (m²)', type: 'number', value: 1 },
    { key: 'cd', label: 'Drag coefficient Cd', type: 'number', value: 0.5 },
    { key: 'cl', label: 'Lift coefficient Cl', type: 'number', value: 0 },
    { key: 'fluid', label: 'Fluid', type: 'select', options: [['air', 'Air'], ['water', 'Water']] },
    { key: 'length_m', label: 'Reference length (m)', type: 'number', value: 1 },
  ],
  free_fall: [
    { key: 'height_m', label: 'Drop height (m)', type: 'number', value: 10 },
    { key: 'mass_kg', label: 'Mass (kg)', type: 'number', value: 1 },
    { key: 'g_m_s2', label: 'Gravity (m/s²)', type: 'number', value: 9.81 },
  ],
};
function renderSolverForm(name) {
  const meta = solvers[name];
  $('solver-meta').innerHTML = meta ? '<b>Method:</b> ' + esc(meta.method) + ' · <b>Engine:</b> ' + esc(meta.engine) + '<br><b>Assumptions:</b><ul>' + meta.assumptions.map((a) => '<li>' + esc(a) + '</li>').join('') + '</ul>' : '';
  const host = $('solver-inputs'); host.innerHTML = '';
  (SOLVER_FIELDS[name] || []).forEach((f) => {
    const row = document.createElement('div'); row.className = 'field-row';
    if (f.type === 'material') {
      row.innerHTML = '<label>' + esc(f.label) + '</label>';
      const sel = document.createElement('select'); sel.id = 'in-' + f.key;
      Object.keys(materialsById).sort().forEach((id) => { const o = document.createElement('option'); o.value = id; o.textContent = materialsById[id].name || id; sel.appendChild(o); });
      row.appendChild(sel);
    } else if (f.type === 'select') {
      row.innerHTML = '<label>' + esc(f.label) + '</label>';
      const sel = document.createElement('select'); sel.id = 'in-' + f.key;
      f.options.forEach(([v, l]) => { const o = document.createElement('option'); o.value = v; o.textContent = l; sel.appendChild(o); });
      row.appendChild(sel);
    } else if (f.type === 'section') {
      row.innerHTML = '<label>' + esc(f.label) + '</label>';
      const sel = document.createElement('select'); sel.id = 'in-section-type';
      sel.innerHTML = '<option value="rectangle">Rectangle</option><option value="circle">Circle</option><option value="ibeam">I-beam</option><option value="box">Hollow box</option>';
      row.appendChild(sel);
      const dims = document.createElement('div'); dims.id = 'section-dims';
      row.appendChild(dims);
      sel.addEventListener('change', () => renderSectionDims(sel.value));
      host.appendChild(row);
      renderSectionDims('rectangle');
      return;
    } else {
      row.innerHTML = '<label>' + esc(f.label) + '</label><input type="number" id="in-' + f.key + '" value="' + f.value + '" step="any">';
    }
    host.appendChild(row);
  });
}
function renderSectionDims(type) {
  const host = $('section-dims'); if (!host) return;
  const fields = {
    rectangle: [['b_m', 'Width b (mm)', 100], ['h_m', 'Height h (mm)', 200]],
    circle: [['d_m', 'Diameter d (mm)', 50]],
    ibeam: [['height_m', 'Height (mm)', 200], ['flange_width_m', 'Flange width (mm)', 100], ['flange_thickness_m', 'Flange thickness (mm)', 10], ['web_thickness_m', 'Web thickness (mm)', 6]],
    box: [['b_m', 'Width b (mm)', 100], ['h_m', 'Height h (mm)', 100], ['t_m', 'Wall thickness (mm)', 5]],
  }[type] || [];
  host.innerHTML = fields.map(([k, l, v]) => '<div class="field-row"><label>' + l + '</label><input type="number" data-sec="' + k + '" value="' + v + '" step="any"></div>').join('');
}
function collectInputs(name) {
  const inputs = {};
  (SOLVER_FIELDS[name] || []).forEach((f) => {
    if (f.type === 'section') {
      const type = $('in-section-type').value;
      const sec = { type };
      document.querySelectorAll('[data-sec]').forEach((el) => { sec[el.dataset.sec] = parseFloat(el.value) / 1000; });
      inputs.section = sec;
    } else if (f.type === 'material' || f.type === 'select') {
      inputs[f.key] = $('in-' + f.key).value;
    } else {
      inputs[f.key] = parseFloat($('in-' + f.key).value);
    }
  });
  return inputs;
}
const UNIT_LABELS = { deflection_m: 'm', slope_rad: 'rad', max_stress_Pa: 'Pa', safety_factor: '', bending_moment_Nm: 'N·m', stress_Pa: 'Pa', strain: '', elongation_m: 'm', shear_stress_Pa: 'Pa', angle_rad: 'rad', shear_modulus_Pa: 'Pa', heat_flow_W: 'W', thermal_resistance_K_W: 'K/W', fall_time_s: 's', impact_velocity_m_s: 'm/s', impact_kinetic_energy_J: 'J', drag_N: 'N', lift_N: 'N', reynolds: '', dynamic_pressure_Pa: 'Pa', time_constant_s: 's', final_temperature_C: '°C', section_area_m2: 'm²', second_moment_m4: 'm⁴' };
$('run-analytical').addEventListener('click', async () => {
  const name = $('solver-select').value;
  if (!projectId) { $('analytical-results').innerHTML = '<p class="warn">Choose a project first — jobs are stored per project.</p>'; return; }
  const inputs = collectInputs(name);
  $('analytical-results').innerHTML = '<p class="muted">Running…</p>';
  try {
    const job = await api('/api/v1/simulations', { method: 'POST', body: JSON.stringify({ project_id: projectId, solver: name, inputs }) });
    if (job.status === 'not_implemented') {
      $('analytical-results').innerHTML = '<p class="warn"><b>Not implemented.</b> ' + esc(job.note || 'No solver is installed for this type.') + '</p>';
      return;
    }
    if (job.status === 'failed') {
      $('analytical-results').innerHTML = '<p class="warn"><b>Solver failed:</b> ' + esc(job.results?.error || 'unknown error') + '</p><p class="small muted">Missing material properties are never guessed — pick a material that has the required property on record, or add the property in Stage 4 data.</p>';
      return;
    }
    const vals = job.results.values;
    let html = '<p><span class="badge">ANALYTICAL</span> ' + esc(job.results.engine) + ' · job ' + esc(job.id) + '</p><table>';
    for (const [k, v] of Object.entries(vals)) {
      if (Array.isArray(v)) continue;
      html += '<tr><td>' + esc(k) + '</td><td><b>' + fmt(v, UNIT_LABELS[k] || '') + '</b></td></tr>';
    }
    html += '</table>';
    if (vals.safety_factor != null) {
      const sf = vals.safety_factor;
      html += '<p><b>Safety factor ' + sf.toFixed(2) + ':</b> ' + (sf < 1 ? '<span class="warn">FAILS — stress exceeds yield.</span>' : sf < 1.5 ? 'Marginal — below the usual 1.5 rule of thumb.' : 'OK by the usual 1.5 rule of thumb (not a code check).') + '</p>';
    }
    if (vals.temperature_profile_C) {
      html += '<p class="small muted">Temperature profile: ' + vals.temperature_profile_C.map((p) => p.t_C.toFixed(1) + '°C @ ' + (p.x_m * 1000).toFixed(0) + ' mm').join(' · ') + '</p>';
    }
    html += '<p class="small muted"><b>Assumptions:</b> ' + job.results.assumptions.map(esc).join(' · ') + '</p>';
    $('analytical-results').innerHTML = html;
  } catch (e) { $('analytical-results').innerHTML = '<p class="warn">Error: ' + esc(e.message) + '</p>'; }
});

// ---------------------------------------------------------------- jobs
async function loadJobs() {
  if (!projectId) { $('jobs-list').innerHTML = '<p class="muted">Choose a project first.</p>'; return; }
  try {
    const data = await api('/api/v1/simulations?project_id=' + projectId);
    if (!data.simulations.length) { $('jobs-list').innerHTML = '<p class="muted">No simulation jobs yet for this project.</p>'; return; }
    $('jobs-list').innerHTML = '<table><tr><th>Solver</th><th>Status</th><th>Created</th><th></th></tr>' + data.simulations.map((j) =>
      '<tr><td>' + esc(j.solver) + '</td><td>' + esc(j.status) + '</td><td>' + esc(j.created_at) + '</td><td><button class="secondary" data-view="' + j.id + '">View</button> <button class="secondary" data-del="' + j.id + '">Delete</button></td></tr>'
    ).join('') + '</table><div id="job-detail"></div>';
    document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', async () => {
      const j = await api('/api/v1/simulations/' + b.dataset.view);
      $('job-detail').innerHTML = '<h4>' + esc(j.solver) + ' — ' + esc(j.status) + '</h4><pre>' + esc(JSON.stringify(j.results || j.inputs, null, 2)) + '</pre>';
    }));
    document.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
      if (!confirm('Delete this simulation job?')) return;
      await api('/api/v1/simulations/' + b.dataset.del, { method: 'DELETE' });
      loadJobs();
    }));
  } catch (e) { $('jobs-list').innerHTML = '<p class="warn">' + esc(e.message) + '</p>'; }
}

// ---------------------------------------------------------------- init
(async function init() {
  await loadMaterials();
  try {
    const data = await api('/api/v1/solvers');
    solvers = data.solvers || {};
    const sel = $('solver-select');
    Object.entries(solvers).forEach(([name, meta]) => {
      if (meta.status === 'browser') return;
      const o = document.createElement('option'); o.value = name;
      o.textContent = meta.label + (meta.status === 'not_implemented' ? ' — not installed' : '');
      sel.appendChild(o);
    });
    sel.addEventListener('change', () => renderSolverForm(sel.value));
    renderSolverForm(sel.value);
  } catch (e) { $('solver-meta').textContent = 'Solver registry unavailable (backend not running?): ' + e.message; }
  await loadProjects();
})();
