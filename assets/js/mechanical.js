/* AI Engineering Laboratory — Mechanical Engineering Laboratory (Stage 7).
   ES module. Assembly inspection (3D preview + tree + exploded view),
   mechanical component library, gear-train calculator, crank-slider
   animator (exact kinematics), analytical mechanical solvers via the
   backend job API, bill of materials, and material alternatives.
   All calculations are analytical and labelled as such; nothing here
   is validated for manufacturing. See docs/MECHANICAL.md. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { evaluateModel } from './model-kernel.js';

const MATH = window.AIELAB_MODEL_MATH;
const API = window.AIELAB_API_BASE || 'http://127.0.0.1:8001';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, u) => (v == null ? '—' : (Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0) ? v.toExponential(3) : (Math.round(v * 1000) / 1000)) + ' ' + u);
const fmtInt = (v) => (v == null ? '—' : Math.round(v).toLocaleString());

function token() { return localStorage.getItem('aielab.token'); }
async function api(method, path, body) {
  const res = await (window.aielabFetchWithWake || fetch)(API + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token() ? { Authorization: 'Bearer ' + token() } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  }, (attempt) => setStatus('Waking the server… (retry ' + attempt + ')', 'warn'));
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}
function setStatus(msg, kind) {
  const s = $('mech-status');
  if (s) { s.textContent = msg; s.className = 'model-status' + (kind ? ' ' + kind : ''); }
}

let model = null, projectId = null, projectName = '';
let materials = [], materialsById = {};
let scene, camera, renderer, orbit, rootGroup = null, topLevel = [];
let explodeFactor = 0;

// -- tabs ---------------------------------------------------------------------
document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
  b.classList.add('active');
  ['assembly', 'gears', 'crank', 'calc', 'bom'].forEach((t) => { $('tab-' + t).hidden = t !== b.dataset.tab; });
  if (b.dataset.tab === 'bom') renderBOM();
}));

// -- projects & materials -------------------------------------------------------
async function loadProjects() {
  const sel = $('project-select');
  try {
    const data = await api('GET', '/api/v1/projects');
    (data.projects || []).forEach((p) => {
      const o = document.createElement('option'); o.value = p.id; o.textContent = p.name; sel.appendChild(o);
    });
    // Re-open the project this browser used last, when signed in.
    const last = localStorage.getItem('aielab.last_project');
    if (last && [...sel.options].some((o) => o.value === last)) { sel.value = last; projectId = last; }
  } catch (e) { setStatus('Could not reach the backend to load projects — the hosted server sleeps when idle and can take a minute to wake. Sign in and try again.', 'warn'); }
}
async function loadMaterials() {
  try {
    const data = await api('GET', '/api/v1/materials');
    (data.materials || []).forEach((m) => { materialsById[m.id] = m; });
  } catch (e) { /* static fallback */ }
  if (!Object.keys(materialsById).length) {
    try {
      const data = await (await fetch('data/materials.json')).json();
      (data.materials || []).forEach((m) => { materialsById[m.id] = m; });
    } catch (e) { /* no material data */ }
  }
  materials = Object.values(materialsById);
}
function materialDensity(mat) {
  if (!mat) return null;
  if (mat.properties && mat.properties.density_kg_m3 != null) return mat.properties.density_kg_m3;
  return mat.density_kg_m3 != null ? mat.density_kg_m3 : null;
}

// -- 3D assembly view -------------------------------------------------------------
function initScene() {
  const el = $('viewer');
  // The stats bar (#viewer-stats) lives inside #viewer — remove only
  // the old canvas, never the whole container. innerHTML = '' destroyed
  // the stats element, so the first buildViewer() crashed on
  // "Cannot set properties of null (setting 'textContent')".
  el.querySelectorAll('canvas').forEach((c) => c.remove());
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(el.clientWidth, 520);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0f14);
  camera = new THREE.PerspectiveCamera(50, el.clientWidth / 520, 1, 100000);
  camera.position.set(400, 300, 400);
  orbit = new OrbitControls(camera, renderer.domElement);
  orbit.target.set(0, 0, 0);
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dl = new THREE.DirectionalLight(0xffffff, 1.2);
  dl.position.set(300, 500, 200); scene.add(dl);
  scene.add(new THREE.GridHelper(2000, 40, 0x1f2937, 0x111827));
  scene.add(new THREE.AxesHelper(300));
  (function loop() { requestAnimationFrame(loop); orbit.update(); renderer.render(scene, camera); })();
}
function clearModel() {
  if (rootGroup) { scene.remove(rootGroup); rootGroup = null; topLevel = []; }
}
async function buildViewer() {
  clearModel();
  const res = await evaluateModel(model);
  if (res.errors.length) setStatus('Model has errors: ' + res.errors.join('; '), 'warn');
  rootGroup = new THREE.Group();
  const objects = res.objects;
  model.components.forEach((c) => {
    const obj = objects.get(c.id);
    if (!obj) return;
    if (c.parent_id && objects.get(c.parent_id)) objects.get(c.parent_id).add(obj);
    else { rootGroup.add(obj); topLevel.push(obj); }
  });
  scene.add(rootGroup);
  scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(rootGroup);
  if (!box.isEmpty()) {
    const c = box.getCenter(new THREE.Vector3());
    orbit.target.copy(c);
    camera.position.set(c.x + 400, c.y + 300, c.z + 400);
    const vs = $('viewer-stats');
    if (vs) vs.textContent = model.components.length + ' components · bounding box '
      + fmt(box.getSize(new THREE.Vector3()).x, 'mm') + ' × ' + fmt(box.getSize(new THREE.Vector3()).y, 'mm') + ' × ' + fmt(box.getSize(new THREE.Vector3()).z, 'mm');
  }
  renderTree(); renderSummary(); renderGearSelects(); renderAltSelect(); renderBOM();
}
function applyExplode() {
  if (!rootGroup) return;
  const box = new THREE.Box3().setFromObject(rootGroup);
  const c = box.isEmpty() ? new THREE.Vector3() : box.getCenter(new THREE.Vector3());
  topLevel.forEach((obj) => {
    const oc = new THREE.Box3().setFromObject(obj).getCenter(new THREE.Vector3());
    const dir = oc.clone().sub(c);
    obj.position.copy(obj.userData.basePos).addScaledVector(dir.normalize(), explodeFactor * 2);
  });
  scene.updateMatrixWorld(true);
}
$('explode').addEventListener('input', (e) => {
  explodeFactor = +e.target.value;
  topLevel.forEach((obj) => { if (!obj.userData.basePos) obj.userData.basePos = obj.position.clone(); });
  applyExplode();
});

async function loadModel() {
  if (!projectId) { setStatus('Choose a project first.', 'warn'); return; }
  setStatus('Loading model…');
  try {
    const data = await api('GET', '/api/v1/projects/' + projectId + '/model');
    model = data.model;
    setStatus('Model loaded: ' + model.components.length + ' components (version ' + data.version + ').');
    initSceneIfNeeded(); await buildViewer();
  } catch (e) { setStatus('Could not load the model: ' + e.message, 'warn'); }
}
let sceneReady = false;
function initSceneIfNeeded() { if (!sceneReady) { initScene(); sceneReady = true; } }
$('load-model').addEventListener('click', () => { projectId = $('project-select').value; projectName = $('project-select').selectedOptions[0]?.textContent || ''; loadModel(); });
$('project-select').addEventListener('change', (e) => { projectId = e.target.value; if (e.target.value) localStorage.setItem('aielab.last_project', e.target.value); else localStorage.removeItem('aielab.last_project'); });

// -- demo assemblies ---------------------------------------------------------------
$('load-demo').addEventListener('click', async () => {
  const demo = $('demo-select').value;
  if (!demo) return;
  setStatus('Loading demo ' + demo + '…');
  try {
    const res = await fetch('workspace/test-models/mechanical/' + demo + '.json');
    if (!res.ok) throw new Error('Demo file not found (HTTP ' + res.status + ')');
    model = await res.json();
    projectId = null;
    setStatus('Demo loaded: ' + demo + ' (guest mode — sign in and save it to a project to keep it).');
    initSceneIfNeeded(); await buildViewer();
  } catch (e) { setStatus('Could not load the demo: ' + e.message, 'warn'); }
});

// -- assembly tree & summary ---------------------------------------------------------
function renderTree() {
  const tree = $('assembly-tree'); tree.innerHTML = '';
  if (!model) { tree.innerHTML = '<p class="muted">Load a model to see its assembly.</p>'; return; }
  const byParent = {};
  model.components.forEach((c) => { (byParent[c.parent_id || 'root'] = byParent[c.parent_id || 'root'] || []).push(c); });
  function row(c, depth) {
    const d = document.createElement('div');
    d.className = 'tree-row';
    d.style.paddingLeft = (8 + depth * 16) + 'px';
    d.textContent = (c.visible ? '◉ ' : '○ ') + c.name + ' · ' + (c.kind || '');
    tree.appendChild(d);
    (byParent[c.id] || []).forEach((ch) => row(ch, depth + 1));
  }
  (byParent.root || []).forEach((c) => row(c, 0));
}
function renderSummary() {
  const s = $('assembly-summary');
  if (!model) { s.innerHTML = '<p class="muted">Nothing loaded yet.</p>'; return; }
  let vol = 0, mass = 0, withMass = 0;
  model.components.forEach((c) => {
    const v = MATH.analyticVolume(c);
    if (v.value != null) {
      vol += v.value;
      const rho = materialDensity(materialsById[c.material_id]);
      if (rho != null) { mass += v.value / 1e9 * rho; withMass++; }
    }
  });
  s.innerHTML = '<table class="kv"><tr><td>Components</td><td>' + model.components.length + '</td></tr>'
    + '<tr><td>Total analytic volume</td><td>' + fmt(vol, 'mm³') + '</td></tr>'
    + '<tr><td>Total mass (assigned materials)</td><td>' + (withMass ? mass.toFixed(3) + ' kg' : '—') + '</td></tr>'
    + '<tr><td>Components with a material</td><td>' + withMass + ' / ' + model.components.length + '</td></tr></table>'
    + '<p class="small muted">Mass uses analytic volumes (estimates flagged in the BOM). Open the model in the 3D Workspace for exact mesh volumes.</p>';
}

// -- component library -----------------------------------------------------------------
const MECH_KINDS = {
  gear: { label: 'Gear', params: { module: 2, teeth: 24, thickness: 12, bore_diameter: 10 } },
  shaft: { label: 'Shaft', params: { diameters: [20, 30, 20], lengths: [40, 60, 40] } },
  bearing: { label: 'Bearing', params: { bore_diameter: 20, outer_diameter: 47, width: 14 } },
  spring: { label: 'Spring', params: { coil_diameter: 30, wire_diameter: 3, coils: 6, length: 50 } },
  piston: { label: 'Piston', params: { diameter: 50, height: 40, ring_grooves: 2 } },
  crankshaft: { label: 'Crankshaft', params: { main_diameter: 30, crank_diameter: 24, throw: 25, length: 160, journals: 3 } },
  connecting_rod: { label: 'Connecting rod', params: { big_diameter: 40, small_diameter: 24, length: 120, width: 16 } },
  flywheel: { label: 'Flywheel', params: { diameter: 200, thickness: 24, hub_diameter: 60, bore_diameter: 30 } },
  clutch: { label: 'Clutch', params: { diameter: 180, thickness: 12, bore_diameter: 30, plates: 2 } },
  brake_disc: { label: 'Brake disc', params: { diameter: 220, thickness: 20, bore_diameter: 60, hub_diameter: 100 } },
  coupling: { label: 'Coupling', params: { diameter: 90, length: 60, bore_diameter: 25, bolts: 4 } },
  pulley: { label: 'Pulley', params: { diameter: 120, width: 24, bore_diameter: 25, groove_depth: 4 } },
  sprocket: { label: 'Sprocket', params: { teeth: 18, pitch: 12.7, thickness: 8, bore_diameter: 25 } },
  hydraulic_cylinder: { label: 'Hydraulic cylinder', params: { bore_diameter: 50, rod_diameter: 25, stroke: 100, barrel_length: 160 } },
  valve: { label: 'Valve', params: { body_length: 90, body_width: 60, body_height: 50, bonnet_diameter: 30, handwheel_diameter: 80 } },
  pump: { label: 'Pump', params: { housing_diameter: 120, housing_length: 90, impeller_diameter: 90, vanes: 6 } },
};
(function buildLibrary() {
  const grid = $('mech-library');
  Object.entries(MECH_KINDS).forEach(([kind, def]) => {
    const b = document.createElement('button');
    b.className = 'secondary'; b.textContent = def.label;
    b.addEventListener('click', () => addComponent(kind));
    grid.appendChild(b);
  });
})();
async function addComponent(kind) {
  if (!model || !projectId) { alert('Load a project model first (sign in, choose a project, Load model).'); return; }
  const def = MECH_KINDS[kind];
  const comp = {
    id: kind + '-' + Math.random().toString(36).slice(2, 8),
    name: def.label, type: 'component', kind,
    params: JSON.parse(JSON.stringify(def.params)),
    position: [0, 0, 0], rotation: [0, 0, 0],
    material_id: null, visible: true, parent_id: null, tolerance_mm: 0.1,
  };
  try {
    const data = await api('POST', '/api/v1/projects/' + projectId + '/model/components', { component: comp });
    model = data.model;
    setStatus(def.label + ' added (model version ' + data.version + ').');
    await buildViewer();
  } catch (e) { setStatus('Could not add the component: ' + e.message, 'warn'); }
}

// -- gear train ---------------------------------------------------------------------------
function gearsInModel() { return (model ? model.components.filter((c) => c.kind === 'gear') : []); }
function renderGearSelects() {
  const gears = gearsInModel();
  [$('gear-a'), $('gear-b')].forEach((sel, i) => {
    sel.innerHTML = '';
    if (!gears.length) { const o = document.createElement('option'); o.textContent = '— no gears in the model —'; sel.appendChild(o); return; }
    gears.forEach((g, j) => {
      const o = document.createElement('option'); o.value = g.id;
      o.textContent = g.name + ' (' + g.params.teeth + 'T, module ' + g.params.module + ')';
      if (j === i) o.selected = true;
      sel.appendChild(o);
    });
  });
}
$('run-gear').addEventListener('click', async () => {
  const out = $('gear-results');
  const gears = gearsInModel();
  const ga = gears.find((g) => g.id === $('gear-a').value);
  const gb = gears.find((g) => g.id === $('gear-b').value);
  if (!ga || !gb) { out.innerHTML = '<p class="warn">Load a model with at least two gears, or run the gear train solver in Calculations with manual inputs.</p>'; return; }
  out.innerHTML = '<p class="muted">Calculating…</p>';
  try {
    const job = await api('POST', '/api/v1/simulations', {
      project_id: projectId, solver: 'gear_train',
      inputs: {
        z1: ga.params.teeth, z2: gb.params.teeth, module_mm: ga.params.module,
        input_speed_rpm: +$('gear-speed').value, input_torque_Nm: +$('gear-torque').value,
        efficiency: +$('gear-eff').value, pressure_angle_deg: 20,
      },
    });
    renderCalcResult(out, job, 'Gear train: ' + esc(ga.name) + ' → ' + esc(gb.name));
  } catch (e) { out.innerHTML = '<p class="warn">Calculation failed: ' + esc(e.message) + '</p>'; }
});

// -- crank-slider animator --------------------------------------------------------------------
let crankAnim = null, crankAngle = 0, crankLast = 0;
function crankKinematics(theta, r, l) {
  const s = Math.sin(theta), c = Math.cos(theta);
  const root = Math.sqrt(Math.max(l * l - r * r * s * s, 1e-12));
  const x = r * c + root;
  const ds = -r * s - (r * r * s * c) / root;
  const d2s = -r * c - ((r * r * (2 * c * c - 1)) / root + (r ** 4 * s * s * c * c) / (root ** 3));
  return { x, ds, d2s };
}
function drawCrank() {
  const cv = $('crank-canvas'), ctx = cv.getContext('2d');
  const r = +$('crank-r').value / 1000, l = +$('crank-l').value / 1000;
  const rpm = +$('crank-rpm').value;
  const w = rpm * 2 * Math.PI / 60;
  const k = crankKinematics(crankAngle, r, l);
  const W = cv.width, H = cv.height;
  const scale = (H * 0.32) / (r + l);
  const cx = W * 0.30, cy = H * 0.55;
  ctx.clearRect(0, 0, W, H);
  ctx.strokeStyle = '#374151'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, H); ctx.stroke();
  // crank circle
  ctx.strokeStyle = '#6b7280'; ctx.beginPath(); ctx.arc(cx, cy, r * scale, 0, Math.PI * 2); ctx.stroke();
  // crank arm
  const pinX = cx + r * scale * Math.cos(crankAngle), pinY = cy - r * scale * Math.sin(crankAngle);
  ctx.strokeStyle = '#4ade80'; ctx.lineWidth = 4;
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(pinX, pinY); ctx.stroke();
  ctx.fillStyle = '#4ade80'; ctx.beginPath(); ctx.arc(cx, cy, 5, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.arc(pinX, pinY, 5, 0, Math.PI * 2); ctx.fill();
  // rod + piston (piston slides along the vertical line through the crank centre)
  const pistonY = cy - k.x * scale;
  ctx.strokeStyle = '#e5e7eb'; ctx.lineWidth = 4;
  ctx.beginPath(); ctx.moveTo(pinX, pinY); ctx.lineTo(cx, pistonY); ctx.stroke();
  ctx.fillStyle = '#9ca3af'; ctx.fillRect(cx - 30, pistonY - 14, 60, 28);
  ctx.fillStyle = '#e5e7eb'; ctx.font = '13px sans-serif';
  const tdc = (r + l - k.x) * 1000;
  $('crank-live').innerHTML = '<table class="kv">'
    + '<tr><td>Crank angle</td><td>' + Math.round((crankAngle * 180 / Math.PI) % 360) + '°</td></tr>'
    + '<tr><td>Piston position from TDC</td><td>' + fmt(tdc, 'mm') + '</td></tr>'
    + '<tr><td>Piston velocity</td><td>' + fmt(w * k.ds, 'm/s') + '</td></tr>'
    + '<tr><td>Piston acceleration</td><td>' + fmt(w * w * k.d2s, 'm/s²') + '</td></tr></table>';
}
function crankLoop(ts) {
  if (!crankAnim) return;
  const rpm = +$('crank-rpm').value;
  const dt = (ts - crankLast) / 1000; crankLast = ts;
  crankAngle += (rpm * 2 * Math.PI / 60) * dt;
  drawCrank();
  crankAnim = requestAnimationFrame(crankLoop);
}
$('crank-play').addEventListener('click', () => {
  if (crankAnim) return;
  crankLast = performance.now();
  crankAnim = requestAnimationFrame(crankLoop);
});
$('crank-pause').addEventListener('click', () => { cancelAnimationFrame(crankAnim); crankAnim = null; });
$('crank-run-solver').addEventListener('click', async () => {
  const out = $('crank-solver-results');
  out.innerHTML = '<p class="muted">Running…</p>';
  try {
    const job = await api('POST', '/api/v1/simulations', {
      project_id: projectId, solver: 'crank_slider',
      inputs: { crank_r_m: +$('crank-r').value / 1000, rod_l_m: +$('crank-l').value / 1000, speed_rpm: +$('crank-rpm').value },
    });
    renderCalcResult(out, job, 'Crank-slider, 720° analysis');
  } catch (e) { out.innerHTML = '<p class="warn">Analysis failed: ' + esc(e.message) + '</p>'; }
});

// -- calculations -------------------------------------------------------------------------------
const UNIT_LABELS = {
  gear_ratio: '', output_speed_rpm: 'rpm', output_torque_Nm: 'N·m',
  power_in_W: 'W', power_out_W: 'W', pitch_diameter_1_m: 'm', pitch_diameter_2_m: 'm',
  centre_distance_m: 'm', tangential_force_N: 'N', radial_force_N: 'N',
  bending_stress_Pa: 'Pa', shear_stress_Pa: 'Pa', von_mises_stress_Pa: 'Pa',
  safety_factor: '', angle_of_twist_rad: 'rad', deflection_m: 'm',
  equivalent_load_N: 'N', life_million_rev: 'M rev', required_rating_N: 'N',
  belt_speed_m_s: 'm/s', belt_length_m: 'm', wrap_angle_rad: 'rad',
  tension_ratio: '', tight_tension_N: 'N', slack_tension_N: 'N',
  spring_rate_N_m: 'N/m', deflection_m: 'm', wahl_factor: '',
  mass_kg: 'kg', inertia_kg_m2: 'kg·m²', energy_J: 'J', rim_speed_m_s: 'm/s', rim_stress_Pa: 'Pa',
  extend_force_N: 'N', retract_force_N: 'N', extend_speed_m_s: 'm/s', retract_speed_m_s: 'm/s',
  stroke_m: 'm', max_velocity_m_s: 'm/s', max_acceleration_m_s2: 'm/s²', mean_piston_speed_m_s: 'm/s',
  alternating_stress_Pa: 'Pa', mean_stress_Pa: 'Pa', goodman_safety_factor: '', static_safety_factor: '',
  natural_frequency_Hz: 'Hz', natural_frequency_rad_s: 'rad/s', period_s: 's', critical_speed_rpm: 'rpm',
  angular_velocity_rad_s: 'rad/s', power_W: 'W', power_kW: 'kW', power_hp: 'hp',
};
const SOLVER_FIELDS = {
  gear_train: [['z1', 'Driving teeth', 'number', 20], ['z2', 'Driven teeth', 'number', 40], ['module_mm', 'Module (mm)', 'number', 2], ['input_speed_rpm', 'Input speed (rpm)', 'number', 1500], ['input_torque_Nm', 'Input torque (N·m)', 'number', 10], ['efficiency', 'Mesh efficiency (0–1)', 'number', 0.95], ['pressure_angle_deg', 'Pressure angle (deg)', 'number', 20]],
  shaft_combined: [['diameter_m', 'Shaft diameter (m)', 'number', 0.02], ['length_m', 'Length (m)', 'number', 1], ['torque_Nm', 'Torque (N·m)', 'number', 100], ['bending_moment_Nm', 'Bending moment (N·m)', 'number', 50], ['material_id', 'Material', 'material', 'steel-1045']],
  bearing_load: [['radial_load_N', 'Radial load (N)', 'number', 5000], ['axial_load_N', 'Axial load (N)', 'number', 1000], ['speed_rpm', 'Speed (rpm)', 'number', 1500], ['life_h', 'Required life (h)', 'number', 10000]],
  belt_drive: [['d1_m', 'Driver pulley diameter (m)', 'number', 0.1], ['d2_m', 'Driven pulley diameter (m)', 'number', 0.2], ['centre_m', 'Centre distance (m)', 'number', 0.5], ['input_speed_rpm', 'Input speed (rpm)', 'number', 1500], ['power_W', 'Power (W)', 'number', 2000], ['mu', 'Friction coefficient', 'number', 0.3]],
  spring_helical: [['wire_d_m', 'Wire diameter (m)', 'number', 0.003], ['coil_d_m', 'Coil diameter (m)', 'number', 0.03], ['coils', 'Active coils', 'number', 6], ['load_N', 'Load (N)', 'number', 100], ['material_id', 'Material', 'material', 'steel-1045']],
  flywheel: [['outer_d_m', 'Outer diameter (m)', 'number', 0.2], ['inner_d_m', 'Inner diameter (m, 0 = solid)', 'number', 0], ['thickness_m', 'Thickness (m)', 'number', 0.024], ['speed_rpm', 'Speed (rpm)', 'number', 3000], ['material_id', 'Material', 'material', 'steel-1045']],
  hydraulic_cylinder: [['bore_d_m', 'Bore diameter (m)', 'number', 0.05], ['rod_d_m', 'Rod diameter (m)', 'number', 0.025], ['pressure_Pa', 'Pressure (Pa)', 'number', 10000000], ['flow_m3_s', 'Flow (m³/s)', 'number', 0.001]],
  crank_slider: [['crank_r_m', 'Crank radius (m)', 'number', 0.025], ['rod_l_m', 'Rod length (m)', 'number', 0.12], ['speed_rpm', 'Speed (rpm)', 'number', 3000]],
  fatigue_shaft: [['diameter_m', 'Shaft diameter (m)', 'number', 0.02], ['bending_moment_Nm', 'Bending moment (N·m)', 'number', 50], ['torque_Nm', 'Torque (N·m)', 'number', 100], ['material_id', 'Material', 'material', 'steel-1045']],
  vibration_1dof: [['stiffness_N_m', 'Stiffness (N/m)', 'number', 4807], ['mass_kg', 'Mass (kg)', 'number', 1]],
  power_transmission: [['torque_Nm', 'Torque (N·m)', 'number', 10], ['speed_rpm', 'Speed (rpm)', 'number', 1500]],
};
let solvers = {};
async function loadSolvers() {
  const sel = $('solver-select');
  try {
    const data = await api('GET', '/api/v1/solvers');
    solvers = data.solvers || {};
    Object.entries(solvers).forEach(([id, s]) => {
      if (s.method !== 'analytical' || !SOLVER_FIELDS[id]) return;
      const o = document.createElement('option'); o.value = id; o.textContent = s.label; sel.appendChild(o);
    });
    renderSolverForm();
  } catch (e) { $('solver-inputs').innerHTML = '<p class="warn">Backend not running — solvers need it.</p>'; }
}
function renderSolverForm() {
  const id = $('solver-select').value;
  const s = solvers[id];
  const wrap = $('solver-inputs'); wrap.innerHTML = '';
  if (!s) return;
  (SOLVER_FIELDS[id] || []).forEach(([key, label, type, def]) => {
    const row = document.createElement('div'); row.className = 'field-row';
    const lab = document.createElement('label'); lab.textContent = label; row.appendChild(lab);
    let input;
    if (type === 'material') {
      input = document.createElement('select');
      materials.forEach((m) => { const o = document.createElement('option'); o.value = m.id; o.textContent = m.name + ' (' + m.id + ')'; input.appendChild(o); });
      input.value = def;
    } else {
      input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.value = def;
    }
    input.id = 'in-' + key; row.appendChild(input); wrap.appendChild(row);
  });
  $('solver-meta').innerHTML = '<p><span class="badge">ANALYTICAL</span> ' + esc(s.label) + '</p><p>' + (s.assumptions || []).map(esc).join('<br>') + '</p>';
}
$('solver-select').addEventListener('change', renderSolverForm);
$('run-calc').addEventListener('click', async () => {
  const id = $('solver-select').value;
  const out = $('calc-results');
  const inputs = {};
  (SOLVER_FIELDS[id] || []).forEach(([key, , type]) => {
    const el = $('in-' + key);
    inputs[key] = type === 'material' ? el.value : +el.value;
  });
  out.innerHTML = '<p class="muted">Running…</p>';
  try {
    const job = await api('POST', '/api/v1/simulations', { project_id: projectId, solver: id, inputs });
    renderCalcResult(out, job, solvers[id].label);
  } catch (e) { out.innerHTML = '<p class="warn">Calculation failed: ' + esc(e.message) + '</p>'; }
});
function renderCalcResult(el, job, title) {
  const res = job.results || {};
  if (job.status === 'failed') {
    el.innerHTML = '<h4>' + esc(title) + '</h4><p class="warn">Solver failed: ' + esc(res.error || 'unknown error') + '</p>'
      + '<p class="small muted">A missing material property stops the run — the property named in the error is not on record for that material. Nothing was guessed.</p>';
    return;
  }
  const vals = res.values || res;
  let rows = '';
  Object.entries(vals).forEach(([k, v]) => {
    if (k === 'series' || typeof v === 'object') return;
    rows += '<tr><td>' + esc(k.replace(/_/g, ' ')) + '</td><td>' + esc(typeof v === 'number' ? fmt(v, UNIT_LABELS[k] || '') : v) + '</td></tr>';
  });
  if (vals.series) rows += '<tr><td>Series points</td><td>' + vals.series.length + ' (0–720°, every 10°)</td></tr>';
  let verdict = '';
  const sf = vals.safety_factor ?? vals.goodman_safety_factor;
  if (typeof sf === 'number') {
    verdict = sf < 1 ? '<p class="warn"><b>FAILS</b> — safety factor ' + sf.toFixed(2) + ' is below 1: the load exceeds the material limit.</p>'
      : sf < 1.5 ? '<p class="warn"><b>Marginal</b> — safety factor ' + sf.toFixed(2) + ' is below the usual 1.5 rule of thumb.</p>'
      : '<p><b>OK</b> — safety factor ' + sf.toFixed(2) + ' meets the usual 1.5 rule of thumb (not a code check).</p>';
  }
  el.innerHTML = '<h4>' + esc(title) + '</h4><p><span class="badge">ANALYTICAL</span> <span class="small muted">' + esc(res.engine || '') + '</span></p>'
    + verdict + '<table class="kv">' + rows + '</table>'
    + '<p class="small muted">Assumptions: ' + esc((res.assumptions || []).join('; ')) + '</p>';
}

// -- bill of materials -----------------------------------------------------------------------
function renderBOM() {
  const el = $('bom-table');
  if (!model) { el.innerHTML = '<p class="muted">Load a model to generate its bill of materials.</p>'; return; }
  let rows = '', totalMass = 0, totalVol = 0;
  model.components.forEach((c) => {
    const v = MATH.analyticVolume(c);
    const mat = materialsById[c.material_id];
    const rho = materialDensity(mat);
    const mass = (v.value != null && rho != null) ? v.value / 1e9 * rho : null;
    if (v.value != null) totalVol += v.value;
    if (mass != null) totalMass += mass;
    rows += '<tr><td>' + esc(c.name) + '</td><td>' + esc(c.kind || '') + '</td><td>' + esc(mat ? mat.name : '—') + '</td>'
      + '<td>' + (v.value != null ? fmt(v.value, 'mm³') + (v.exact ? '' : ' *') : '—') + '</td>'
      + '<td>' + (mass != null ? mass.toFixed(3) + ' kg' : '—') + '</td></tr>';
  });
  el.innerHTML = '<table class="kv"><tr><th>Component</th><th>Kind</th><th>Material</th><th>Volume</th><th>Mass</th></tr>' + rows
    + '<tr><td colspan="3"><b>Total</b></td><td><b>' + fmt(totalVol, 'mm³') + '</b></td><td><b>' + totalMass.toFixed(3) + ' kg</b></td></tr></table>'
    + '<p class="small muted">* Volume is an estimate (see docs/MECHANICAL.md). Total mass covers only components with a material assigned.</p>';
}
$('bom-csv').addEventListener('click', () => {
  if (!model) return;
  let csv = 'Component,Kind,Material,Volume_mm3,Mass_kg\n';
  model.components.forEach((c) => {
    const v = MATH.analyticVolume(c);
    const mat = materialsById[c.material_id];
    const rho = materialDensity(mat);
    const mass = (v.value != null && rho != null) ? (v.value / 1e9 * rho).toFixed(4) : '';
    csv += '"' + (c.name || '').replace(/"/g, '""') + '",' + (c.kind || '') + ',"' + (mat ? mat.name : '') + '",' + (v.value != null ? v.value.toFixed(1) : '') + ',' + mass + '\n';
  });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = (projectName || 'assembly').replace(/\W+/g, '-') + '-bom.csv';
  a.click();
});
$('bom-print').addEventListener('click', () => window.print());

// -- material alternatives ---------------------------------------------------------------------
function renderAltSelect() {
  const sel = $('alt-component'); sel.innerHTML = '';
  (model ? model.components : []).forEach((c) => {
    const o = document.createElement('option'); o.value = c.id; o.textContent = c.name + ' (' + (c.kind || '') + ')'; sel.appendChild(o);
  });
}
$('find-alternatives').addEventListener('click', async () => {
  const out = $('alternatives');
  const c = model ? model.components.find((x) => x.id === $('alt-component').value) : null;
  if (!c) { out.innerHTML = '<p class="muted">Load a model first.</p>'; return; }
  const mat = materialsById[c.material_id];
  if (!mat) { out.innerHTML = '<p class="muted">Assign a material to this component first (in the 3D Workspace) — alternatives are compared against what it is made of now.</p>'; return; }
  const props = mat.properties || {};
  out.innerHTML = '<p class="muted">Searching…</p>';
  try {
    const req = {};
    if (props.yield_strength_mpa != null) req.min_yield_mpa = props.yield_strength_mpa;
    if (props.density_kg_m3 != null) req.max_density_kg_m3 = props.density_kg_m3;
    const data = await api('POST', '/api/v1/materials/recommend', { ...req, limit: 4 });
    const list = (data.recommendations || []).filter((r) => r.id !== mat.id);
    if (!list.length) { out.innerHTML = '<p class="muted">No lighter alternative meets the current yield strength. The current material may already be the best trade-off.</p>'; return; }
    const v = MATH.analyticVolume(c);
    out.innerHTML = '<p class="small muted">Alternatives at least as strong as <b>' + esc(mat.name) + '</b> and no denser:</p>'
      + list.map((r) => {
        const m = v.value != null && r.properties && r.properties.density_kg_m3 ? (v.value / 1e9 * r.properties.density_kg_m3).toFixed(3) + ' kg' : '—';
        return '<p>• <b>' + esc(r.name) + '</b> — ' + esc(r.score != null ? 'score ' + r.score.toFixed(2) : '') + ' · mass if used here: ' + m + '</p>';
      }).join('')
      + '<p class="small muted">Ranked by the same 50/30/20 scoring as the Materials Library (strength-to-weight / stiffness / low cost).</p>';
  } catch (e) { out.innerHTML = '<p class="warn">Could not search: ' + esc(e.message) + '</p>'; }
});

// -- init -----------------------------------------------------------------------------------------
(async function init() {
  await loadMaterials();
  await loadProjects();
  await loadSolvers();
  drawCrank();
})();
