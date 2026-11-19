/* Aerospace Engineering Laboratory — Stage 10.
   Designer + 3D view + performance + rocket + assistant + report.
   All analysis runs on the server (backend/aerospace.py). The airfoil
   polar chart is the same thin-airfoil formula computed in the browser
   and is labelled as such. Nothing here is flight-certified. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const API = (window.AIELAB_API_BASE || 'http://127.0.0.1:8001');
const token = () => localStorage.getItem('aielab.token');
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, d) => (v == null || !isFinite(v)) ? '—' : Number(v).toFixed(d == null ? 2 : d);
const GUEST_KEY = 'aielab.aerospace.guest';

// Typical airfoil data (same table as backend/aerospace.py).
const AIRFOIL_TABLE = {
  naca2412: { alpha0: -2.1, cd0: 0.006, k: 0.045, cl_max: 1.6 },
  naca4412: { alpha0: -4.3, cd0: 0.006, k: 0.040, cl_max: 1.7 },
  naca0012: { alpha0: 0.0, cd0: 0.006, k: 0.050, cl_max: 1.5 },
  naca23012: { alpha0: -1.1, cd0: 0.007, k: 0.045, cl_max: 1.8 },
  naca6412: { alpha0: -6.2, cd0: 0.007, k: 0.038, cl_max: 1.8 },
};

const COMP_NAMES = ['Wing', 'Fuselage', 'Tail', 'Battery'];
const S = {
  projectId: '',
  kind: 'aircraft',
  stages: [
    { name: 'stage 1', isp_s: 300, m0_kg: 1000, mf_kg: 300 },
    { name: 'stage 2', isp_s: 320, m0_kg: 300, mf_kg: 100 },
  ],
  lastResults: null,   // last `values` object from an analyze job
  lastKind: null,
  materials: [],
  designVersion: 1,
};

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const t = token();
  if (t) headers['Authorization'] = 'Bearer ' + t;
  const res = await fetch(API + path, { ...opts, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}

function status(msg) { $('aero-status').textContent = msg; }

// ---------------- materials ----------------
async function loadMaterials() {
  try {
    if (window.AIELAB_MATERIALS && window.AIELAB_MATERIALS.list.length) {
      S.materials = window.AIELAB_MATERIALS.list;
    } else {
      const data = await (await fetch('data/materials.json')).json();
      S.materials = (data.materials || []).map((m) => ({
        id: m.id, name: m.name, grade: m.grade || '', properties: m.properties || {},
      }));
    }
  } catch (e) { S.materials = []; }
  const sel = $('ac-spar-mat');
  sel.innerHTML = S.materials.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}${m.grade ? ' — ' + esc(m.grade) : ''}</option>`).join('');
  const alu = S.materials.find((m) => m.id === 'alu-7075-t6');
  if (alu) sel.value = alu.id;
}

// ---------------- projects ----------------
async function loadProjects() {
  const sel = $('project-select');
  if (!token()) { sel.innerHTML = '<option value="">(guest — design saved locally only)</option>'; return; }
  try {
    const data = await api('/api/v1/projects');
    const list = data.projects || [];
    sel.innerHTML = '<option value="">(guest — design saved locally only)</option>' +
      list.map((p) => `<option value="${esc(p.id)}">${esc(p.name || p.id)}</option>`).join('');
  } catch (e) { sel.innerHTML = '<option value="">(could not load projects)</option>'; }
}
async function loadProjectDesign() {
  S.projectId = $('project-select').value;
  S.lastResults = null;
  if (!S.projectId) { loadGuest(); applyDesignToEditors(); renderAll(); return; }
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(S.projectId) + '/aerospace');
    applyDesign(data.design || {});
    status('Loaded design from project (version ' + (S.designVersion || 1) + ').');
  } catch (e) {
    status('No design saved for this project yet — starting from the defaults. (' + e.message + ')');
  }
  saveGuest();
  applyDesignToEditors();
  renderAll();
}
async function saveDesign() {
  const design = buildDesign();
  if (!S.projectId) { saveGuest(); status('Saved locally (guest mode). Sign in and pick a project to save it on the server.'); return; }
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(S.projectId) + '/aerospace', {
      method: 'PUT',
      body: JSON.stringify({ design, base_version: S.designVersion }),
    });
    S.designVersion = data.design.version;
    status('Saved to project (version ' + S.designVersion + ').');
  } catch (e) {
    if (/409/.test(e.message)) status('Save conflict: the design was changed elsewhere. Reload the project and re-apply your change.');
    else status('Save failed: ' + e.message);
  }
}
function loadGuest() {
  try {
    const raw = localStorage.getItem(GUEST_KEY);
    if (raw) applyDesign(JSON.parse(raw));
  } catch (e) { /* ignore */ }
}
function saveGuest() {
  try { localStorage.setItem(GUEST_KEY, JSON.stringify(buildDesign())); } catch (e) { /* ignore */ }
}

// ---------------- design <-> editors ----------------
function num(id, def) { const v = parseFloat($(id).value); return isFinite(v) ? v : def; }
function readComponents() {
  const out = [];
  document.querySelectorAll('#ac-components tr').forEach((tr, i) => {
    const mass = parseFloat(tr.querySelector('[data-f="mass"]').value);
    const x = parseFloat(tr.querySelector('[data-f="x"]').value);
    out.push({ name: COMP_NAMES[i].toLowerCase(), mass_kg: mass, x_m: x });
  });
  return out;
}
function buildDesign() {
  if (S.kind === 'aircraft') {
    const mass = num('ac-mass', 10);
    return {
      version: S.designVersion, kind: 'aircraft',
      mass_kg: mass, wing_area_m2: num('ac-area', 1), span_m: num('ac-span', 2.828),
      oswald_e: num('ac-e', 0.8), cd0: num('ac-cd0', 0.02), k: num('ac-k', 0.05),
      cl_max: num('ac-clmax', 1.4), cruise_speed_m_s: num('ac-speed', 20),
      altitude_m: num('ac-alt', 0), prop_efficiency: num('ac-eta', 0.7),
      battery_energy_Wh: num('ac-batt', 500), motor_efficiency: 0.85,
      components: readComponents(), mac_m: num('ac-mac', 0.35),
      x_ac_wing_m: num('ac-xac', 0.55), tail_volume: num('ac-tailvol', 0.5),
      airfoil_code: $('ac-airfoil').value,
      spar: {
        length_m: num('ac-spar-len', 1.414),
        section: { type: 'rectangle', b_m: num('ac-spar-b', 0.02), h_m: num('ac-spar-h', 0.05) },
        material_id: $('ac-spar-mat').value || 'alu-7075-t6',
        lift_N: mass * 9.80665 / 2,
      },
    };
  }
  if (S.kind === 'multirotor') {
    return {
      version: S.designVersion, kind: 'multirotor',
      mass_kg: num('mr-mass', 2), n_rotors: Math.max(1, Math.round(num('mr-n', 4))),
      rotor_diameter_m: num('mr-d', 0.25), altitude_m: 0,
      figure_of_merit: num('mr-fom', 0.7), battery_energy_Wh: num('mr-batt', 100),
    };
  }
  return {
    version: S.designVersion, kind: 'rocket',
    stages: S.stages.map((s) => ({ ...s })),
    stability: {
      components: [
        { type: 'nose', shape: 'conical', length_m: 0.3, diameter_m: 0.1, x_base_m: 0.3 },
        { type: 'fins', n: 4, root_chord_m: 0.15, tip_chord_m: 0.07, span_m: 0.08, x_leading_m: 0.85, body_diameter_m: 0.1 },
      ],
      cg_x_m: num('rk-cg', 0.55), diameter_m: num('rk-cgd', 0.1),
    },
    trajectory: {
      mass_kg: num('tr-mass', 50), diameter_m: num('tr-d', 0.15), cd: num('tr-cd', 0.5),
      launch_angle_deg: num('tr-ang', 90),
      thrust_profile: [{ t_start_s: 0, t_end_s: num('tr-burn', 5), thrust_N: num('tr-thrust', 5000), mdot_kg_s: num('tr-mdot', 2) }],
      dt_s: 0.1, t_max_s: 120,
    },
    body_diameter_m: num('rk-d', 0.1), body_length_m: num('rk-len', 1.0),
  };
}
function applyDesign(d) {
  if (!d || !d.kind) return;
  S.kind = d.kind;
  if (d.version) S.designVersion = d.version;
  if (d.kind === 'aircraft') {
    const set = (id, v) => { if (v != null) $(id).value = v; };
    set('ac-mass', d.mass_kg); set('ac-area', d.wing_area_m2); set('ac-span', d.span_m);
    set('ac-e', d.oswald_e); set('ac-cd0', d.cd0); set('ac-k', d.k); set('ac-clmax', d.cl_max);
    set('ac-speed', d.cruise_speed_m_s); set('ac-alt', d.altitude_m); set('ac-eta', d.prop_efficiency);
    set('ac-batt', d.battery_energy_Wh); set('ac-mac', d.mac_m); set('ac-xac', d.x_ac_wing_m);
    set('ac-tailvol', d.tail_volume);
    if (d.airfoil_code) $('ac-airfoil').value = d.airfoil_code;
    if (d.spar) {
      set('ac-spar-len', d.spar.length_m);
      if (d.spar.section) { set('ac-spar-b', d.spar.section.b_m); set('ac-spar-h', d.spar.section.h_m); }
      if (d.spar.material_id) $('ac-spar-mat').value = d.spar.material_id;
    }
    if (Array.isArray(d.components)) {
      d.components.forEach((c, i) => {
        const tr = document.querySelectorAll('#ac-components tr')[i];
        if (!tr) return;
        if (c.mass_kg != null) tr.querySelector('[data-f="mass"]').value = c.mass_kg;
        if (c.x_m != null) tr.querySelector('[data-f="x"]').value = c.x_m;
      });
    }
  } else if (d.kind === 'multirotor') {
    const set = (id, v) => { if (v != null) $(id).value = v; };
    set('mr-mass', d.mass_kg); set('mr-n', d.n_rotors); set('mr-d', d.rotor_diameter_m);
    set('mr-fom', d.figure_of_merit); set('mr-batt', d.battery_energy_Wh);
  } else if (d.kind === 'rocket') {
    if (Array.isArray(d.stages) && d.stages.length) S.stages = d.stages.map((s) => ({ ...s }));
    if (d.stability) { if (d.stability.cg_x_m != null) $('rk-cg').value = d.stability.cg_x_m; if (d.stability.diameter_m != null) $('rk-cgd').value = d.stability.diameter_m; }
    if (d.trajectory) {
      const tr = d.trajectory;
      const set = (id, v) => { if (v != null) $(id).value = v; };
      set('tr-mass', tr.mass_kg); set('tr-d', tr.diameter_m); set('tr-cd', tr.cd);
      set('tr-ang', tr.launch_angle_deg);
      if (Array.isArray(tr.thrust_profile) && tr.thrust_profile[0]) {
        set('tr-thrust', tr.thrust_profile[0].thrust_N);
        set('tr-burn', tr.thrust_profile[0].t_end_s);
        set('tr-mdot', tr.thrust_profile[0].mdot_kg_s);
      }
    }
    if (d.body_diameter_m != null) $('rk-d').value = d.body_diameter_m;
    if (d.body_length_m != null) $('rk-len').value = d.body_length_m;
  }
}
function applyDesignToEditors() {
  $('kind-select').value = S.kind;
  $('editor-aircraft').style.display = S.kind === 'aircraft' ? '' : 'none';
  $('editor-multirotor').style.display = S.kind === 'multirotor' ? '' : 'none';
  $('editor-rocket').style.display = S.kind === 'rocket' ? '' : 'none';
  $('editor-title').textContent = S.kind === 'aircraft' ? 'Aircraft parameters'
    : S.kind === 'multirotor' ? 'Multirotor parameters' : 'Rocket parameters';
  renderStages();
}

// ---------------- demos ----------------
const DEMOS = {
  fixed_wing_aircraft: 'workspace/test-aerospace/fixed_wing_aircraft.json',
  multirotor_drone: 'workspace/test-aerospace/multirotor_drone.json',
  multistage_rocket: 'workspace/test-aerospace/multistage_rocket.json',
};
async function loadDemo(key) {
  if (!DEMOS[key]) return;
  try {
    const d = await (await fetch(DEMOS[key])).json();
    delete d.expected; delete d.name;
    applyDesign(d);
    applyDesignToEditors();
    saveGuest();
    renderAll();
    status('Loaded demo: ' + key + '. Run the analysis to see its numbers.');
  } catch (e) { status('Could not load demo: ' + e.message); }
}

// ---------------- 3D view ----------------
let renderer, scene, camera, controls, vehicleGroup = null, cgMarker = null;
function initView() {
  const el = $('viewport');
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(el.clientWidth, 440);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0e14);
  camera = new THREE.PerspectiveCamera(45, el.clientWidth / 440, 0.1, 100);
  camera.position.set(4, 2.5, 4);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.3, 0);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dl = new THREE.DirectionalLight(0xffffff, 1.2);
  dl.position.set(5, 8, 4);
  scene.add(dl);
  const grid = new THREE.GridHelper(6, 12, 0x334455, 0x223344);
  scene.add(grid);
  const axes = new THREE.AxesHelper(1);
  scene.add(axes);
  const loop = () => { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
  loop();
}
function mat(color) { return new THREE.MeshStandardMaterial({ color, metalness: 0.4, roughness: 0.5 }); }
function buildVehicle() {
  if (vehicleGroup) scene.remove(vehicleGroup);
  if (cgMarker) scene.remove(cgMarker);
  vehicleGroup = new THREE.Group();
  if (S.kind === 'aircraft') {
    const span = num('ac-span', 2.828);
    const fus = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.06, 1.7, 16), mat(0x9fb3c8));
    fus.rotation.z = Math.PI / 2; fus.position.set(0.65, 0.3, 0);
    vehicleGroup.add(fus);
    const wing = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.03, span), mat(0x5b8dd9));
    wing.position.set(0.55, 0.3, 0);
    vehicleGroup.add(wing);
    const tail = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.02, 0.9), mat(0x5b8dd9));
    tail.position.set(1.4, 0.3, 0);
    vehicleGroup.add(tail);
    const fin = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.4, 0.02), mat(0x5b8dd9));
    fin.position.set(1.4, 0.5, 0);
    vehicleGroup.add(fin);
    const prop = new THREE.Mesh(new THREE.CircleGeometry(0.35, 24), new THREE.MeshBasicMaterial({ color: 0x888888, side: THREE.DoubleSide, transparent: true, opacity: 0.35 }));
    prop.position.set(-0.22, 0.3, 0); prop.rotation.y = Math.PI / 2;
    vehicleGroup.add(prop);
  } else if (S.kind === 'multirotor') {
    const d = num('mr-d', 0.25);
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.08, 0.3), mat(0x9fb3c8));
    body.position.set(0, 0.4, 0);
    vehicleGroup.add(body);
    for (const [sx, sz] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.03, 0.03), mat(0x5b8dd9));
      arm.position.set(sx * 0.2, 0.4, sz * 0.2);
      arm.rotation.y = -sx * sz * Math.PI / 4;
      vehicleGroup.add(arm);
      const rotor = new THREE.Mesh(new THREE.CircleGeometry(d / 2, 24), new THREE.MeshBasicMaterial({ color: 0xaaaaaa, side: THREE.DoubleSide, transparent: true, opacity: 0.4 }));
      rotor.rotation.x = -Math.PI / 2;
      rotor.position.set(sx * 0.32, 0.45, sz * 0.32);
      vehicleGroup.add(rotor);
    }
  } else {
    const len = num('rk-len', 1.0);
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.3, 16), mat(0xd94f4f));
    nose.rotation.z = -Math.PI / 2; nose.position.set(-0.15 - len / 2, 0.6, 0);
    vehicleGroup.add(nose);
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, len, 16), mat(0x9fb3c8));
    body.rotation.z = Math.PI / 2; body.position.set(0, 0.6, 0);
    vehicleGroup.add(body);
    for (let i = 0; i < 4; i++) {
      const fin = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.02, 0.12), mat(0x5b8dd9));
      const a = i * Math.PI / 2;
      fin.position.set(len / 2 - 0.05, 0.6 + Math.sin(a) * 0.08, Math.cos(a) * 0.08);
      fin.rotation.x = a;
      vehicleGroup.add(fin);
    }
  }
  scene.add(vehicleGroup);
  // CG marker from the last aircraft analysis.
  if (S.lastKind === 'aircraft' && S.lastResults && S.lastResults.cg_x_m != null) {
    cgMarker = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 12), new THREE.MeshBasicMaterial({ color: 0xff4444 }));
    cgMarker.position.set(S.lastResults.cg_x_m - 0.65, 0.3, 0);
    scene.add(cgMarker);
  }
}
function renderAll() { buildVehicle(); }

// ---------------- charts ----------------
function drawChart(canvas, series, xKey, yKey, label) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!series || series.length < 2) { ctx.fillStyle = '#888'; ctx.fillText('No data yet.', 10, 20); return; }
  const xs = series.map((p) => p[xKey]), ys = series.map((p) => p[yKey]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = 36;
  const X = (v) => pad + (v - x0) / (x1 - x0 || 1) * (W - pad * 2);
  const Y = (v) => H - pad - (v - y0) / (y1 - y0 || 1) * (H - pad * 2);
  ctx.strokeStyle = '#555'; ctx.beginPath();
  ctx.moveTo(pad, pad); ctx.lineTo(pad, H - pad); ctx.lineTo(W - pad, H - pad); ctx.stroke();
  ctx.fillStyle = '#aaa'; ctx.font = '12px sans-serif';
  ctx.fillText(label, pad + 4, pad - 8);
  ctx.fillText(fmt(y1, 0), 4, pad + 4); ctx.fillText(fmt(y0, 0), 4, H - pad + 4);
  ctx.fillText(fmt(x0, 0), pad, H - 12); ctx.fillText(fmt(x1, 0), W - pad - 30, H - 12);
  ctx.strokeStyle = '#5b8dd9'; ctx.lineWidth = 2; ctx.beginPath();
  series.forEach((p, i) => { const x = X(p[xKey]), y = Y(p[yKey]); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
  ctx.stroke(); ctx.lineWidth = 1;
}

// ---------------- analyses ----------------
async function runAnalyze(type) {
  if (!S.projectId) { $('perf-status').textContent = 'Sign in and pick a project first.'; return null; }
  let design = buildDesign();
  // The trajectory analysis takes the trajectory config itself.
  if (type === 'trajectory') design = { ...design.trajectory, kind: 'trajectory' };
  const body = await api('/api/v1/aerospace/analyze', {
    method: 'POST',
    body: JSON.stringify({ project_id: S.projectId, design, analysis: { type } }),
  });
  if (body.status === 'failed') throw new Error((body.results && body.results.error) || 'analysis failed');
  return body.results.values;
}
function pill(v, good, warn) {
  if (v == null) return '<span>—</span>';
  const cls = good(v) ? 'pill-ok' : warn(v) ? 'pill-warn' : 'pill-bad';
  return `<span class="${cls}">${esc(String(v))}</span>`;
}
async function runPerformance() {
  $('perf-status').textContent = 'Running…';
  try {
    const values = await runAnalyze(S.kind === 'multirotor' ? 'multirotor' : 'aircraft');
    S.lastResults = values; S.lastKind = S.kind;
    $('perf-status').textContent = 'Done.';
    renderPerf(values);
    saveGuest(); renderAll(); loadJobs();
  } catch (e) { $('perf-status').textContent = 'Failed: ' + e.message; }
}
function renderPerf(v) {
  let html = '<table class="results"><tbody>';
  if (S.kind === 'multirotor') {
    html += `<tr><th>Thrust per rotor</th><td>${fmt(v.thrust_per_rotor_N, 2)} N</td></tr>`;
    html += `<tr><th>Disk loading</th><td>${fmt(v.disk_loading_N_m2, 1)} N/m²</td></tr>`;
    html += `<tr><th>Induced velocity</th><td>${fmt(v.induced_velocity_m_s, 2)} m/s</td></tr>`;
    html += `<tr><th>Hover power</th><td>${fmt(v.hover_power_W, 1)} W</td></tr>`;
    if (v.hover_endurance_min != null) html += `<tr><th>Hover endurance</th><td>${fmt(v.hover_endurance_min, 1)} min</td></tr>`;
  } else {
    html += `<tr><th>Cl (cruise)</th><td>${fmt(v.cl_cruise, 3)}</td></tr>`;
    html += `<tr><th>Cd (cruise)</th><td>${fmt(v.cd_cruise, 4)}</td></tr>`;
    html += `<tr><th>Lift / drag</th><td>${fmt(v.lift_to_drag, 2)}</td></tr>`;
    html += `<tr><th>Stall speed</th><td>${fmt(v.stall_speed_m_s, 2)} m/s (${fmt(v.stall_speed_kmh, 1)} km/h)</td></tr>`;
    html += `<tr><th>Thrust required</th><td>${fmt(v.thrust_required_N, 1)} N</td></tr>`;
    html += `<tr><th>Power required</th><td>${fmt(v.power_required_W, 1)} W</td></tr>`;
    if (v.range_km != null) html += `<tr><th>Range</th><td>${fmt(v.range_km, 1)} km</td></tr>`;
    if (v.endurance_h != null) html += `<tr><th>Endurance</th><td>${fmt(v.endurance_h, 2)} h</td></tr>`;
    if (v.cg_x_m != null) html += `<tr><th>Centre of gravity</th><td>${fmt(v.cg_x_m, 3)} m from nose</td></tr>`;
    if (v.static_margin != null) {
      html += `<tr><th>Static margin</th><td>${fmt(v.static_margin, 3)} ${v.statically_stable ? pill('stable', () => true, () => false) : pill('UNSTABLE — CG behind neutral point', () => false, () => false)}</td></tr>`;
    }
    if (v.spar_check) {
      const sc = v.spar_check;
      html += `<tr><th>Spar stress (Stage 9)</th><td>${fmt(sc.max_stress_Pa / 1e6, 2)} MPa, utilisation ${fmt(sc.utilization, 3)} ${sc.utilization < 1 ? pill('OK', () => true, () => false) : pill('OVERSTRESSED', () => false, () => false)}</td></tr>`;
      html += `<tr><th>Spar tip deflection</th><td>${fmt(sc.max_displacement_m * 1000, 2)} mm</td></tr>`;
    }
  }
  html += '</tbody></table>';
  html += '<p class="muted">Thin-airfoil + lifting-line theory, ISA atmosphere, Breguet / momentum theory. Not a CFD or flight-test result.</p>';
  $('perf-results').innerHTML = html;
}
function drawPolar() {
  const code = $('polar-airfoil').value;
  const t = AIRFOIL_TABLE[code];
  const series = [];
  for (let a = -5; a <= 15; a += 1) {
    const cl = 2 * Math.PI * (a - t.alpha0) * Math.PI / 180;
    const cd = t.cd0 + t.k * cl * cl;
    series.push({ alpha: a, cl, cd });
  }
  drawChart($('polar-chart'), series, 'alpha', 'cl', 'Cl vs angle of attack (deg) — ' + code);
  const cl0 = 2 * Math.PI * (0 - t.alpha0) * Math.PI / 180;
  $('polar-results').innerHTML = `<p class="muted">Zero-lift angle ${t.alpha0}°, Cl at 0° ${fmt(cl0, 2)}, Clmax ${t.cl_max} (typical). Stall is flagged when |Cl| exceeds Clmax.</p>`;
}

// ---------------- rocket ----------------
function renderStages() {
  $('stage-rows').innerHTML = S.stages.map((s, i) => `<tr>
    <td><input data-i="${i}" data-f="name" value="${esc(s.name || 'stage ' + (i + 1))}"></td>
    <td><input data-i="${i}" data-f="isp_s" type="number" step="1" value="${s.isp_s}"></td>
    <td><input data-i="${i}" data-f="m0_kg" type="number" step="1" value="${s.m0_kg}"></td>
    <td><input data-i="${i}" data-f="mf_kg" type="number" step="1" value="${s.mf_kg}"></td>
    <td><button class="button" data-del="${i}">✕</button></td></tr>`).join('');
  document.querySelectorAll('#stage-rows input').forEach((inp) => {
    inp.addEventListener('change', () => {
      const i = +inp.dataset.i, f = inp.dataset.f;
      S.stages[i][f] = f === 'name' ? inp.value : parseFloat(inp.value);
    });
  });
  document.querySelectorAll('#stage-rows [data-del]').forEach((b) => {
    b.addEventListener('click', () => { S.stages.splice(+b.dataset.del, 1); renderStages(); });
  });
}
async function runRocket() {
  $('rocket-status').textContent = 'Running…';
  try {
    const values = await runAnalyze('rocket');
    S.lastResults = values; S.lastKind = 'rocket';
    $('rocket-status').textContent = 'Done.';
    const dv = values.delta_v, st = values.stability;
    let html = '<table class="results"><tbody>';
    html += `<tr><th>Total delta-v</th><td>${fmt(dv.total_delta_v_m_s, 0)} m/s (${fmt(dv.total_delta_v_km_s, 2)} km/s)</td></tr>`;
    dv.stages.forEach((s) => { html += `<tr><th>${esc(s.name)}</th><td>${fmt(s.delta_v_m_s, 0)} m/s, mass ratio ${fmt(s.mass_ratio, 2)}, propellant ${fmt(s.propellant_kg, 1)} kg</td></tr>`; });
    if (st) {
      html += `<tr><th>Centre of pressure</th><td>${fmt(st.cp_x_m, 3)} m from nose</td></tr>`;
      html += `<tr><th>Stability margin</th><td>${fmt(st.stability_calibres, 2)} calibres ${st.margin_ok ? pill('in the 1.0–2.5 band', () => true, () => false) : pill(st.stable ? 'stable but outside the usual band' : 'UNSTABLE', () => false, () => true)}</td></tr>`;
    }
    html += '</tbody></table><p class="muted">Tsiolkovsky (no gravity or drag losses) + Barrowman (subsonic, small angles). The trajectory tab adds gravity and drag.</p>';
    $('rocket-results').innerHTML = html;
    saveGuest(); loadJobs();
  } catch (e) { $('rocket-status').textContent = 'Failed: ' + e.message; }
}
async function runTrajectory() {
  $('traj-status').textContent = 'Running…';
  try {
    const values = await runAnalyze('trajectory');
    S.lastResults = values; S.lastKind = 'trajectory';
    $('traj-status').textContent = 'Done.';
    $('traj-results').innerHTML = `<table class="results"><tbody>
      <tr><th>Apogee</th><td>${fmt(values.apogee_m, 0)} m</td></tr>
      <tr><th>Max velocity</th><td>${fmt(values.max_velocity_m_s, 1)} m/s</td></tr>
      <tr><th>Range</th><td>${fmt(values.range_m, 0)} m</td></tr>
      <tr><th>Flight time</th><td>${fmt(values.flight_time_s, 1)} s</td></tr>
      </tbody></table><p class="muted">2-D point-mass: gravity, ISA drag, thrust profile, mass loss. No wind, no guidance.</p>`;
    drawChart($('traj-chart'), values.series, 't_s', 'y_m', 'Altitude (m) vs time (s)');
    saveGuest(); loadJobs();
  } catch (e) { $('traj-status').textContent = 'Failed: ' + e.message; }
}

// ---------------- jobs ----------------
async function loadJobs() {
  if (!S.projectId) { $('jobs-list').innerHTML = '<p class="muted">No project selected.</p>'; return; }
  try {
    const data = await api('/api/v1/simulations?project_id=' + encodeURIComponent(S.projectId));
    const jobs = (data.simulations || []).filter((j) => j.solver && j.solver.startsWith('aero_'));
    if (!jobs.length) { $('jobs-list').innerHTML = '<p class="muted">No aerospace jobs yet for this project.</p>'; return; }
    $('jobs-list').innerHTML = '<table class="results"><thead><tr><th>Solver</th><th>Status</th><th>When</th></tr></thead><tbody>' +
      jobs.map((j) => `<tr><td>${esc(j.solver)}</td><td>${esc(j.status)}</td><td>${esc(j.created_at || '')}</td></tr>`).join('') + '</tbody></table>';
  } catch (e) { $('jobs-list').innerHTML = '<p class="muted">Could not load jobs: ' + esc(e.message) + '</p>'; }
}

// ---------------- assistant + report ----------------
function runAssistant() {
  const v = S.lastResults;
  const out = $('assist-out');
  if (!v) { out.innerHTML = '<p class="muted">Run a performance, rocket or trajectory analysis first — the assistant only reads real results.</p>'; return; }
  const notes = [];
  if (S.lastKind === 'aircraft') {
    if (v.static_margin != null) {
      notes.push(v.statically_stable
        ? `Statically stable: the centre of gravity (${fmt(v.cg_x_m, 3)} m) sits ahead of the neutral point, static margin ${fmt(v.static_margin, 3)} MAC.`
        : `UNSTABLE: the centre of gravity is behind the neutral point (static margin ${fmt(v.static_margin, 3)}). Move mass forward or enlarge the tail.`);
    }
    if (v.spar_check) {
      notes.push(v.spar_check.utilization < 0.5
        ? `The wing spar is lightly loaded (utilisation ${fmt(v.spar_check.utilization, 3)}). You could thin the section or use a lighter material — but check deflection too (${fmt(v.spar_check.max_displacement_m * 1000, 1)} mm tip deflection).`
        : v.spar_check.utilization < 1
          ? `The wing spar is the limiting part (utilisation ${fmt(v.spar_check.utilization, 3)}). Consider a deeper section or a stronger alloy.`
          : `The wing spar is OVERSTRESSED (utilisation ${fmt(v.spar_check.utilization, 3)}). Do not fly this. Increase the section or change the material.`);
    }
    if (v.lift_to_drag != null) notes.push(`Cruise L/D is ${fmt(v.lift_to_drag, 1)}. Most of the drag at cruise is ${v.cd_cruise ? 'parasite + induced' : ''} — a higher aspect ratio or cleaner airframe raises range.`);
    if (v.endurance_h != null) notes.push(`Endurance ${fmt(v.endurance_h, 2)} h and range ${fmt(v.range_km, 1)} km on the given battery, at the given cruise speed.`);
    if (v.cl_cruise > 0.9 * num('ac-clmax', 1.4)) notes.push('Cruise Cl is close to Clmax — the margin to stall is thin at this speed.');
  } else if (S.lastKind === 'rocket') {
    const dv = v.delta_v, st = v.stability;
    notes.push(`Total delta-v ${fmt(dv.total_delta_v_m_s, 0)} m/s across ${dv.stages.length} stage(s). For low Earth orbit you need roughly 9,400 m/s including gravity and drag losses — this vehicle ${dv.total_delta_v_m_s >= 9400 ? 'reaches that on paper' : 'does not reach orbit on paper'}.`);
    if (st) notes.push(st.margin_ok
      ? `Stability margin ${fmt(st.stability_calibres, 2)} calibres — inside the usual 1.0–2.5 band.`
      : st.stable
        ? `Stable but the margin (${fmt(st.stability_calibres, 2)} calibres) is outside the usual 1.0–2.5 band — move the CG forward or enlarge the fins.`
        : `UNSTABLE: the centre of pressure is ahead of the centre of gravity. The rocket would tumble. Move mass forward or add fin area.`);
  } else if (S.lastKind === 'trajectory') {
    notes.push(`Apogee ${fmt(v.apogee_m, 0)} m, max velocity ${fmt(v.max_velocity_m_s, 1)} m/s, flight time ${fmt(v.flight_time_s, 1)} s. This is a point-mass model with no wind or guidance — treat the numbers as a first estimate.`);
  } else if (S.lastKind === 'multirotor') {
    notes.push(`Hover needs ${fmt(v.hover_power_W, 0)} W; the battery gives about ${fmt(v.hover_endurance_min, 1)} minutes of hover. Disk loading ${fmt(v.disk_loading_N_m2, 0)} N/m² — larger rotors would cut the power.`);
  }
  out.innerHTML = '<ul>' + notes.map((n) => `<li>${esc(n)}</li>`).join('') + '</ul><p class="muted">Conceptual review only. Nothing here certifies a design for flight.</p>';
}
function buildReport() {
  const v = S.lastResults;
  const out = $('report-out');
  if (!v) { out.innerHTML = '<p class="muted">Run an analysis first.</p>'; return; }
  out.innerHTML = `<h3>Aerospace report — ${esc(S.lastKind || '')}</h3>
    <p class="muted">Generated from the last server analysis. Methods: thin-airfoil theory, lifting-line corrections, Tsiolkovsky, Barrowman, 2-D point-mass trajectory. Not flight-certified.</p>
    <pre>${esc(JSON.stringify(v, null, 2))}</pre>`;
}
function downloadCSV() {
  const v = S.lastResults;
  if (!v) return;
  const rows = [];
  const walk = (obj, prefix) => {
    for (const [k, val] of Object.entries(obj)) {
      if (val != null && typeof val === 'object' && !Array.isArray(val)) walk(val, prefix + k + '.');
      else if (typeof val !== 'object') rows.push([prefix + k, val]);
    }
  };
  walk(v, '');
  const csv = 'key,value\n' + rows.map(([k, val]) => `"${k}","${val}"`).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = 'aerospace-results.csv';
  a.click();
}

// ---------------- wiring ----------------
function init() {
  initView();
  loadMaterials();
  loadProjects();
  loadGuest();
  applyDesignToEditors();
  renderAll();
  $('kind-select').addEventListener('change', (e) => { S.kind = e.target.value; applyDesignToEditors(); saveGuest(); renderAll(); });
  $('project-select').addEventListener('change', loadProjectDesign);
  $('demo-select').addEventListener('change', (e) => { if (e.target.value) loadDemo(e.target.value); });
  $('btn-save-design').addEventListener('click', saveDesign);
  $('btn-refresh-view').addEventListener('click', () => { saveGuest(); renderAll(); });
  $('btn-run-perf').addEventListener('click', runPerformance);
  $('btn-polar').addEventListener('click', drawPolar);
  $('btn-add-stage').addEventListener('click', () => { S.stages.push({ name: 'stage ' + (S.stages.length + 1), isp_s: 300, m0_kg: 500, mf_kg: 200 }); renderStages(); });
  $('btn-run-rocket').addEventListener('click', runRocket);
  $('btn-run-traj').addEventListener('click', runTrajectory);
  $('btn-assist').addEventListener('click', runAssistant);
  $('btn-report').addEventListener('click', buildReport);
  $('btn-csv').addEventListener('click', downloadCSV);
  drawPolar();
  window.__aeroReady = true;
  window.__aeroRefresh = () => { if (renderer) buildVehicle(); };
}
init();
