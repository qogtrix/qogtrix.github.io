/* Robotics Engineering Laboratory — Stage 10.
   Arm designer (DH + FK/IK) + PID control + mobile robot + assistant.
   All analysis runs on the server (backend/robotics.py). The 3D arm
   view uses client-side forward kinematics (same DH math) so the
   sliders move live; the authoritative FK/IK numbers come from the
   server. Nothing here is validated for a real robot. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const API = (window.AIELAB_API_BASE || 'http://127.0.0.1:8001');
const token = () => localStorage.getItem('aielab.token');
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const fmt = (v, d) => (v == null || !isFinite(v)) ? '—' : Number(v).toFixed(d == null ? 2 : d);
const GUEST_KEY = 'aielab.robot.guest';
const D2R = Math.PI / 180, R2D = 180 / Math.PI;

const S = {
  projectId: '',
  dh: [
    { a: 0, alpha: 90, d: 0.15, theta: 0 },
    { a: 0.4, alpha: 0, d: 0, theta: 0 },
    { a: 0.35, alpha: 0, d: 0, theta: 0 },
    { a: 0.15, alpha: 0, d: 0, theta: 0 },
  ],
  joints: [0.3, 0.5, -0.8, 0.4],   // radians
  limits: [[-3.14, 3.14], [-2.5, 2.5], [-2.5, 2.5], [-3.14, 3.14]],
  lastResults: null,
  lastKind: null,
  materials: [],
  designVersion: 1,
  pose: [0, 0, 0],                 // mobile robot pose
  trail: [[0, 0]],
};

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const t = token();
  if (t) headers['Authorization'] = 'Bearer ' + t;
  const res = await (window.aielabFetchWithWake || fetch)(API + path, { ...opts, headers },
    (attempt) => status('Waking the server… (retry ' + attempt + ')'));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}
function status(msg) { $('robo-status').textContent = msg; }

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
  const sel = $('lk-mat');
  sel.innerHTML = S.materials.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}${m.grade ? ' — ' + esc(m.grade) : ''}</option>`).join('');
  const alu = S.materials.find((m) => m.id === 'alu-6061-t6');
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
    // Re-open the project this browser used last, when signed in.
    const last = localStorage.getItem('aielab.last_project');
    if (last && list.some((p) => p.id === last)) { sel.value = last; loadProjectDesign(); }
  } catch (e) { sel.innerHTML = '<option value="">(could not load projects)</option>'; }
}
async function loadProjectDesign() {
  S.projectId = $('project-select').value;
  if (S.projectId) localStorage.setItem('aielab.last_project', S.projectId);
  else localStorage.removeItem('aielab.last_project');
  S.lastResults = null;
  if (!S.projectId) { loadGuest(); renderDH(); renderSliders(); renderAll(); return; }
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(S.projectId) + '/robot');
    applyDesign(data.design || {});
    status('Loaded design from project (version ' + (S.designVersion || 1) + ').');
  } catch (e) {
    status('No design saved for this project yet — starting from the defaults. (' + e.message + ')');
  }
  saveGuest();
  renderDH(); renderSliders(); renderAll();
}
async function saveDesign() {
  const design = buildDesign();
  if (!S.projectId) { saveGuest(); status('Saved locally (guest mode). Sign in and pick a project to save it on the server.'); return; }
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(S.projectId) + '/robot', {
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

// ---------------- design ----------------
function num(id, def) { const v = parseFloat($(id).value); return isFinite(v) ? v : def; }
function buildDesign() {
  const links = S.dh.map((row, i) => ({
    name: 'link ' + (i + 1), length_m: Math.abs(row.a) || 0.1,
    section: { type: 'circle', d_m: num('lk-d', 0.05) },
    material_id: $('lk-mat').value || 'alu-6061-t6',
    payload_N: num('lk-payload', 5),
  }));
  return {
    version: S.designVersion, kind: 'arm',
    dh: S.dh.map((r) => ({ a: r.a, alpha: r.alpha * D2R, d: r.d, theta: r.theta * D2R, type: 'revolute' })),
    joints: S.joints.slice(),
    limits: S.limits.map(([lo, hi]) => [lo, hi]),
    target_pos: [num('ik-x', 0.45), num('ik-y', 0.35), num('ik-z', 0.45)],
    link_radius_m: 0.05,
    motor: { voltage_V: num('mt-v', 12), resistance_ohm: num('mt-r', 1.5), kt_Nm_per_A: num('mt-kt', 0.05), ke_V_per_rad_s: num('mt-ke', 0.05), load_torque_Nm: num('mt-load', 0.02) },
    links,
    obstacles: [{ type: 'sphere', centre: [0.9, 0.0, 0.3], radius_m: 0.1, name: 'test obstacle' }],
  };
}
function applyDesign(d) {
  if (!d) return;
  if (d.version) S.designVersion = d.version;
  if (Array.isArray(d.dh) && d.dh.length) {
    S.dh = d.dh.map((r) => ({ a: r.a, alpha: (r.alpha || 0) * R2D, d: r.d, theta: (r.theta || 0) * R2D }));
  }
  if (Array.isArray(d.joints) && d.joints.length === S.dh.length) S.joints = d.joints.slice();
  if (Array.isArray(d.limits) && d.limits.length === S.dh.length) S.limits = d.limits.map(([lo, hi]) => [lo, hi]);
  if (Array.isArray(d.target_pos) && d.target_pos.length === 3) {
    $('ik-x').value = d.target_pos[0]; $('ik-y').value = d.target_pos[1]; $('ik-z').value = d.target_pos[2];
  }
  if (d.motor) {
    const set = (id, v) => { if (v != null) $(id).value = v; };
    set('mt-v', d.motor.voltage_V); set('mt-r', d.motor.resistance_ohm);
    set('mt-kt', d.motor.kt_Nm_per_A); set('mt-ke', d.motor.ke_V_per_rad_s);
    set('mt-load', d.motor.load_torque_Nm);
  }
  if (Array.isArray(d.links) && d.links[0]) {
    if (d.links[0].payload_N != null) $('lk-payload').value = d.links[0].payload_N;
    if (d.links[0].section && d.links[0].section.d_m != null) $('lk-d').value = d.links[0].section.d_m;
    if (d.links[0].material_id) $('lk-mat').value = d.links[0].material_id;
  }
}

// ---------------- demos ----------------
const DEMOS = {
  robot_arm: 'workspace/test-robots/robot_arm.json',
  robot_assembly: 'workspace/test-robots/robot_assembly.json',
};
async function loadDemo(key) {
  if (!DEMOS[key]) return;
  try {
    const d = await (await fetch(DEMOS[key])).json();
    delete d.expected; delete d.name; delete d.sensors;
    applyDesign(d);
    if (d.pid) {
      $('pid-kp').value = d.pid.kp; $('pid-ki').value = d.pid.ki; $('pid-kd').value = d.pid.kd;
      $('pid-sp').value = d.pid.setpoint_rad;
    }
    if (d.trajectory) {
      $('tr-q0').value = d.trajectory.q0.map((q) => fmt(q * R2D, 0)).join(', ');
      $('tr-q1').value = d.trajectory.q1.map((q) => fmt(q * R2D, 0)).join(', ');
      $('tr-dur').value = d.trajectory.duration_s;
    }
    saveGuest();
    renderDH(); renderSliders(); renderAll();
    status('Loaded demo: ' + key + '. Run the arm analysis to see its numbers.');
  } catch (e) { status('Could not load demo: ' + e.message); }
}

// ---------------- client-side FK (for the live 3D view) ----------------
function dhMatrix(a, alpha, d, theta) {
  const ct = Math.cos(theta), st = Math.sin(theta), ca = Math.cos(alpha), sa = Math.sin(alpha);
  return [[ct, -st * ca, st * sa, a * ct], [st, ct * ca, -ct * sa, a * st], [0, sa, ca, d], [0, 0, 0, 1]];
}
function matMul(A, B) {
  return A.map((row) => B[0].map((_, j) => row.reduce((s, v, k) => s + v * B[k][j], 0)));
}
function fkClient(dh, joints) {
  let T = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]];
  const positions = [[0, 0, 0]];
  for (let i = 0; i < dh.length; i++) {
    T = matMul(T, dhMatrix(dh[i].a, dh[i].alpha * D2R, dh[i].d, dh[i].theta * D2R + joints[i]));
    positions.push([T[0][3], T[1][3], T[2][3]]);
  }
  return positions;
}

// ---------------- 3D view ----------------
let renderer, scene, camera, controls, armGroup = null;
function initView() {
  const el = $('viewport');
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(el.clientWidth, 440);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0e14);
  camera = new THREE.PerspectiveCamera(45, el.clientWidth / 440, 0.1, 100);
  camera.position.set(1.2, 1.0, 1.4);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0.3, 0.4, 0);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dl = new THREE.DirectionalLight(0xffffff, 1.2);
  dl.position.set(3, 5, 3);
  scene.add(dl);
  scene.add(new THREE.GridHelper(3, 12, 0x334455, 0x223344));
  scene.add(new THREE.AxesHelper(0.5));
  const loop = () => { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
  loop();
}
function buildArm() {
  if (armGroup) scene.remove(armGroup);
  armGroup = new THREE.Group();
  const positions = fkClient(S.dh, S.joints);
  const steel = new THREE.MeshStandardMaterial({ color: 0x9fb3c8, metalness: 0.5, roughness: 0.4 });
  const jointMat = new THREE.MeshStandardMaterial({ color: 0x8b5cf6, metalness: 0.4, roughness: 0.4 });
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.11, 0.08, 20), steel);
  base.position.set(0, 0.04, 0);
  armGroup.add(base);
  for (let i = 0; i < positions.length - 1; i++) {
    const a = new THREE.Vector3(...positions[i]);
    const b = new THREE.Vector3(...positions[i + 1]);
    const dir = b.clone().sub(a);
    const len = dir.length();
    if (len < 1e-6) continue;
    const link = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, len, 14), steel);
    link.position.copy(a).add(b).multiplyScalar(0.5);
    link.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    armGroup.add(link);
    const joint = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 12), jointMat);
    joint.position.copy(a);
    armGroup.add(joint);
  }
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.04, 16, 12), new THREE.MeshBasicMaterial({ color: 0x4ade80 }));
  tip.position.set(...positions[positions.length - 1]);
  armGroup.add(tip);
  // obstacle sphere
  const obs = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xf87171, transparent: true, opacity: 0.4 }));
  obs.position.set(0.9, 0.3, 0);
  armGroup.add(obs);
  scene.add(armGroup);
  const end = positions[positions.length - 1];
  $('fk-readout').innerHTML = `<p class="muted">End effector: (${fmt(end[0], 3)}, ${fmt(end[1], 3)}, ${fmt(end[2], 3)}) m — client-side FK. The server result is authoritative.</p>`;
}
function renderAll() { buildArm(); }

// ---------------- DH editor ----------------
function renderDH() {
  $('dh-rows').innerHTML = S.dh.map((r, i) => `<tr>
    <td>Joint ${i + 1}</td>
    <td><input data-i="${i}" data-f="a" type="number" step="0.01" value="${r.a}"></td>
    <td><input data-i="${i}" data-f="alpha" type="number" step="1" value="${fmt(r.alpha, 1)}"></td>
    <td><input data-i="${i}" data-f="d" type="number" step="0.01" value="${r.d}"></td>
    <td><input data-i="${i}" data-f="theta" type="number" step="1" value="${fmt(r.theta, 1)}"></td>
    <td><input data-i="${i}" data-f="lo" type="number" step="1" value="${fmt((S.limits[i] || [-3.14, 3.14])[0] * R2D, 0)}"></td>
    <td><input data-i="${i}" data-f="hi" type="number" step="1" value="${fmt((S.limits[i] || [-3.14, 3.14])[1] * R2D, 0)}"></td></tr>`).join('');
  document.querySelectorAll('#dh-rows input').forEach((inp) => {
    inp.addEventListener('change', () => {
      const i = +inp.dataset.i, f = inp.dataset.f, v = parseFloat(inp.value);
      if (!isFinite(v)) return;
      if (f === 'lo') S.limits[i][0] = v * D2R;
      else if (f === 'hi') S.limits[i][1] = v * D2R;
      else S.dh[i][f] = v;
      renderSliders(); renderAll(); saveGuest();
    });
  });
}
function renderSliders() {
  $('joint-sliders').innerHTML = S.dh.map((r, i) => {
    const deg = S.joints[i] * R2D;
    const lo = (S.limits[i] || [-3.14, 3.14])[0] * R2D, hi = (S.limits[i] || [-3.14, 3.14])[1] * R2D;
    return `<div class="slider-row"><label>Joint ${i + 1}</label>
      <input type="range" min="${lo}" max="${hi}" step="1" value="${fmt(deg, 0)}" data-j="${i}">
      <span id="jval-${i}">${fmt(deg, 0)}°</span></div>`;
  }).join('');
  document.querySelectorAll('#joint-sliders input').forEach((inp) => {
    inp.addEventListener('input', () => {
      const i = +inp.dataset.j;
      S.joints[i] = parseFloat(inp.value) * D2R;
      $('jval-' + i).textContent = inp.value + '°';
      renderAll();
    });
    inp.addEventListener('change', saveGuest);
  });
}

// ---------------- analyses ----------------
function pill(text, cls) { return `<span class="${cls}">${esc(text)}</span>`; }
async function runArmAnalysis() {
  if (!S.projectId) { $('ik-results').innerHTML = '<p class="muted">Sign in and pick a project first.</p>'; return; }
  $('ik-results').innerHTML = '<p class="muted">Running…</p>';
  try {
    const design = buildDesign();
    const body = await api('/api/v1/robotics/analyze', {
      method: 'POST',
      body: JSON.stringify({ project_id: S.projectId, design, analysis: { type: 'arm' } }),
    });
    if (body.status === 'failed') throw new Error((body.results && body.results.error) || 'analysis failed');
    const v = body.results.values;
    S.lastResults = v; S.lastKind = 'arm';
    let html = '<table class="results"><tbody>';
    const end = v.fk.end_position;
    html += `<tr><th>End effector (server FK)</th><td>(${fmt(end[0], 3)}, ${fmt(end[1], 3)}, ${fmt(end[2], 3)}) m</td></tr>`;
    if (v.limit_violations && v.limit_violations.length) {
      html += `<tr><th>Joint limits</th><td>${pill(v.limit_violations.length + ' violation(s)', 'pill-bad')}</td></tr>`;
    } else html += '<tr><th>Joint limits</th><td>' + pill('within limits', 'pill-ok') + '</td></tr>';
    if (v.ik) {
      html += `<tr><th>IK residual</th><td>${fmt(v.ik.residual_m, 5)} m ${v.ik.converged ? pill('converged', 'pill-ok') : pill('NOT converged', 'pill-bad')}</td></tr>`;
      html += `<tr><th>IK joints</th><td>${v.ik.joints.map((q) => fmt(q * R2D, 1) + '°').join(', ')}</td></tr>`;
      if (v.ik.converged) {
        S.joints = v.ik.joints.slice();
        renderSliders(); renderAll();
      }
    }
    if (v.motor_check) {
      const m = v.motor_check;
      html += `<tr><th>Motor (Stage 8)</th><td>${fmt(m.speed_rpm, 0)} rpm, ${fmt(m.power_out_W, 1)} W out, efficiency ${fmt((m.efficiency || 0) * 100, 1)}%</td></tr>`;
    }
    if (v.link_check) {
      v.link_check.forEach((l) => {
        html += `<tr><th>${esc(l.name)} stress</th><td>${fmt(l.max_stress_Pa / 1e6, 2)} MPa, utilisation ${fmt(l.utilization, 3)} ${l.utilization < 1 ? pill('OK', 'pill-ok') : pill('OVERSTRESSED', 'pill-bad')}</td></tr>`;
      });
    }
    if (v.collisions) {
      html += `<tr><th>Collisions</th><td>${v.collisions.length ? pill(v.collisions.length + ' collision(s)', 'pill-bad') : pill('none', 'pill-ok')}</td></tr>`;
    }
    html += '</tbody></table>';
    $('ik-results').innerHTML = html;
    saveGuest();
  } catch (e) { $('ik-results').innerHTML = '<p class="muted">Failed: ' + esc(e.message) + '</p>'; }
}
async function runIKOnly() {
  if (!S.projectId) { $('ik-results').innerHTML = '<p class="muted">Sign in and pick a project first.</p>'; return; }
  $('ik-results').innerHTML = '<p class="muted">Running IK…</p>';
  try {
    const body = await api('/api/v1/simulations', {
      method: 'POST',
      body: JSON.stringify({
        project_id: S.projectId, solver: 'ik_dls',
        inputs: {
          dh: buildDesign().dh, target_pos: [num('ik-x', 0.45), num('ik-y', 0.35), num('ik-z', 0.45)],
          q0: S.joints.slice(), limits: S.limits,
        },
      }),
    });
    if (body.status === 'failed') throw new Error((body.results && body.results.error) || 'IK failed');
    const v = body.results.values;
    S.lastResults = { ik: v, fk: { end_position: [num('ik-x', 0.45), num('ik-y', 0.35), num('ik-z', 0.45)] } };
    S.lastKind = 'arm';
    $('ik-results').innerHTML = `<table class="results"><tbody>
      <tr><th>IK residual</th><td>${fmt(v.residual_m, 5)} m ${v.converged ? pill('converged', 'pill-ok') : pill('NOT converged', 'pill-bad')}</td></tr>
      <tr><th>Joints</th><td>${v.joints.map((q) => fmt(q * R2D, 1) + '°').join(', ')}</td></tr>
      <tr><th>Iterations</th><td>${v.iterations}</td></tr></tbody></table>`;
    if (v.converged) { S.joints = v.joints.slice(); renderSliders(); renderAll(); }
    saveGuest();
  } catch (e) { $('ik-results').innerHTML = '<p class="muted">Failed: ' + esc(e.message) + '</p>'; }
}

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
  ctx.fillText(fmt(y1, 1), 4, pad + 4); ctx.fillText(fmt(y0, 1), 4, H - pad + 4);
  ctx.fillText(fmt(x0, 1), pad, H - 12); ctx.fillText(fmt(x1, 1), W - pad - 30, H - 12);
  ctx.strokeStyle = '#8b5cf6'; ctx.lineWidth = 2; ctx.beginPath();
  series.forEach((p, i) => { const x = X(p[xKey]), y = Y(p[yKey]); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); });
  ctx.stroke(); ctx.lineWidth = 1;
}

// ---------------- PID + trajectory ----------------
async function runPID() {
  if (!S.projectId) { $('pid-status').textContent = 'Sign in and pick a project first.'; return; }
  $('pid-status').textContent = 'Running…';
  try {
    const body = await api('/api/v1/simulations', {
      method: 'POST',
      body: JSON.stringify({
        project_id: S.projectId, solver: 'pid_control',
        inputs: {
          R_ohm: num('pid-r', 1.5), L_H: num('pid-l', 0.001), Kt_Nm_per_A: num('pid-kt', 0.05),
          Ke_V_per_rad_s: num('pid-ke', 0.05), J_kg_m2: num('pid-j', 0.01), b_Nm_s: num('pid-b', 0.001),
          setpoint_rad: num('pid-sp', 1), kp: num('pid-kp', 2), ki: num('pid-ki', 0.5), kd: num('pid-kd', 1.5),
          voltage_limit_V: num('pid-vmax', 12), dt_s: 0.001, duration_s: num('pid-dur', 5),
          load_torque_Nm: num('pid-load', 0),
        },
      }),
    });
    if (body.status === 'failed') throw new Error((body.results && body.results.error) || 'PID failed');
    const v = body.results.values;
    S.lastResults = { pid: v }; S.lastKind = 'control';
    $('pid-status').textContent = 'Done.';
    $('pid-results').innerHTML = `<table class="results"><tbody>
      <tr><th>Final error</th><td>${fmt(v.final_error_rad, 4)} rad</td></tr>
      <tr><th>Overshoot</th><td>${fmt(v.overshoot_percent, 1)}%</td></tr>
      <tr><th>Settling time (2% band)</th><td>${v.settling_time_s == null ? 'not settled in run' : fmt(v.settling_time_s, 2) + ' s'}</td></tr>
      <tr><th>Max current</th><td>${fmt(v.max_current_A, 2)} A</td></tr></tbody></table>`;
    drawChart($('pid-chart'), v.series, 't_s', 'theta_rad', 'Joint angle (rad) vs time (s)');
  } catch (e) { $('pid-status').textContent = 'Failed: ' + e.message; }
}
async function runTrajectory() {
  if (!S.projectId) { $('traj-status').textContent = 'Sign in and pick a project first.'; return; }
  $('traj-status').textContent = 'Running…';
  try {
    const parse = (s) => s.split(',').map((x) => parseFloat(x.trim()) * D2R);
    const q0 = parse($('tr-q0').value), q1 = parse($('tr-q1').value);
    const body = await api('/api/v1/simulations', {
      method: 'POST',
      body: JSON.stringify({
        project_id: S.projectId, solver: 'cubic_trajectory',
        inputs: { q0, q1, duration_s: num('tr-dur', 2), dt: 0.05 },
      }),
    });
    if (body.status === 'failed') throw new Error((body.results && body.results.error) || 'trajectory failed');
    const v = body.results.values;
    S.lastResults = { trajectory: v }; S.lastKind = 'control';
    $('traj-status').textContent = 'Done.';
    $('traj-results').innerHTML = `<table class="results"><tbody>
      <tr><th>Max joint velocity</th><td>${v.max_velocity.map((x) => fmt(x * R2D, 1) + '°/s').join(', ')}</td></tr>
      <tr><th>Max joint acceleration</th><td>${v.max_acceleration.map((x) => fmt(x * R2D, 1) + '°/s²').join(', ')}</td></tr></tbody></table>`;
    const series = v.t.map((t, i) => ({ t_s: t, q0: v.q[i][0] }));
    drawChart($('traj-chart'), series, 't_s', 'q0', 'Joint 1 angle (rad) vs time (s)');
  } catch (e) { $('traj-status').textContent = 'Failed: ' + e.message; }
}

// ---------------- mobile robot ----------------
function drawMobile() {
  const cv = $('mobile-canvas');
  const ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#111827'; ctx.fillRect(0, 0, W, H);
  const trail = S.trail;
  if (!trail.length) return;
  const xs = trail.map((p) => p[0]), ys = trail.map((p) => p[1]);
  const x0 = Math.min(...xs, -0.2), x1 = Math.max(...xs, 0.2);
  const y0 = Math.min(...ys, -0.2), y1 = Math.max(...ys, 0.2);
  const scale = Math.min((W - 60) / (x1 - x0 || 1), (H - 60) / (y1 - y0 || 1));
  const X = (v) => 30 + (v - x0) * scale;
  const Y = (v) => H - 30 - (v - y0) * scale;
  ctx.strokeStyle = '#8b5cf6'; ctx.lineWidth = 2; ctx.beginPath();
  trail.forEach((p, i) => { if (i === 0) ctx.moveTo(X(p[0]), Y(p[1])); else ctx.lineTo(X(p[0]), Y(p[1])); });
  ctx.stroke();
  const last = trail[trail.length - 1];
  ctx.fillStyle = '#4ade80'; ctx.beginPath(); ctx.arc(X(last[0]), Y(last[1]), 6, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = '#aaa'; ctx.font = '12px sans-serif';
  ctx.fillText('Top view — trail in metres. Green dot = current pose.', 10, 18);
}
async function runDiffDrive() {
  if (!S.projectId) { $('dd-status').textContent = 'Sign in and pick a project first.'; return; }
  try {
    const body = await api('/api/v1/simulations', {
      method: 'POST',
      body: JSON.stringify({
        project_id: S.projectId, solver: 'diff_drive_fk',
        inputs: {
          wheel_radius_m: num('dd-r', 0.05), track_m: num('dd-track', 0.3),
          v_left_m_s: num('dd-vl', 0.5), v_right_m_s: num('dd-vr', 0.5),
          pose: S.pose.slice(), dt_s: num('dd-dt', 1),
        },
      }),
    });
    if (body.status === 'failed') throw new Error((body.results && body.results.error) || 'drive failed');
    const v = body.results.values;
    S.pose = v.pose.slice();
    S.trail.push([S.pose[0], S.pose[1]]);
    S.lastResults = { diff_drive: v }; S.lastKind = 'mobile';
    $('dd-status').textContent = 'Done.';
    $('dd-results').innerHTML = `<p>Pose: (${fmt(S.pose[0], 3)}, ${fmt(S.pose[1], 3)}) m, heading ${fmt(S.pose[2] * R2D, 1)}°. v = ${fmt(v.v_m_s, 2)} m/s, ω = ${fmt(v.omega_rad_s, 2)} rad/s.</p>`;
    drawMobile();
  } catch (e) { $('dd-status').textContent = 'Failed: ' + e.message; }
}
async function runSquare() {
  if (!S.projectId) { $('dd-status').textContent = 'Sign in and pick a project first.'; return; }
  try {
    const left = [10, 10, -3, 3, 10, 10, -3, 3, 10, 10, -3, 3, 10, 10];
    const right = [10, 10, 3, -3, 10, 10, 3, -3, 10, 10, 3, -3, 10, 10];
    const body = await api('/api/v1/simulations', {
      method: 'POST',
      body: JSON.stringify({
        project_id: S.projectId, solver: 'diff_drive_odometry',
        inputs: {
          wheel_radius_m: num('dd-r', 0.05), track_m: num('dd-track', 0.3),
          left_speeds: left, right_speeds: right, dt_s: 1.0, pose0: [0, 0, 0],
        },
      }),
    });
    if (body.status === 'failed') throw new Error((body.results && body.results.error) || 'odometry failed');
    const v = body.results.values;
    S.pose = v.final_pose.slice();
    S.trail = v.trail.map((p) => [p[0], p[1]]);
    S.lastResults = { diff_drive: v }; S.lastKind = 'mobile';
    $('dd-status').textContent = 'Done.';
    $('dd-results').innerHTML = `<p>Square path complete. Final pose: (${fmt(S.pose[0], 3)}, ${fmt(S.pose[1], 3)}) m, heading ${fmt(S.pose[2] * R2D, 1)}°. A perfect square would return to (0, 0) — the residual is the turn geometry of this command set.</p>`;
    drawMobile();
  } catch (e) { $('dd-status').textContent = 'Failed: ' + e.message; }
}

// ---------------- assistant + report ----------------
function runAssistant() {
  const v = S.lastResults;
  const out = $('assist-out');
  if (!v) { out.innerHTML = '<p class="muted">Run an arm, control or mobile analysis first — the assistant only reads real results.</p>'; return; }
  const notes = [];
  if (S.lastKind === 'arm') {
    if (v.ik) notes.push(v.ik.converged
      ? `IK converged to ${fmt(v.ik.residual_m, 5)} m in ${v.ik.iterations} iterations. The target is reachable with the current arm.`
      : `IK did NOT converge (residual ${fmt(v.ik.residual_m, 4)} m). The target may be outside the workspace — check the reach (max ${fmt(S.dh.reduce((s, r) => s + Math.abs(r.a), 0), 2)} m) or seed the solver closer to the target.`);
    if (v.limit_violations && v.limit_violations.length) notes.push(`${v.limit_violations.length} joint(s) outside their limits. Widen the limits or change the target.`);
    if (v.collisions) notes.push(v.collisions.length
      ? `${v.collisions.length} collision(s) with obstacles — move the obstacle or re-plan the pose.`
      : 'No collisions with the test obstacle at this pose.');
    if (v.link_check) {
      const worst = v.link_check.reduce((a, b) => (a.utilization > b.utilization ? a : b));
      notes.push(worst.utilization < 0.5
        ? `The links are lightly loaded (worst utilisation ${fmt(worst.utilization, 3)} on ${worst.name}). A thinner section or lighter material would work.`
        : worst.utilization < 1
          ? `The ${worst.name} is the limiting link (utilisation ${fmt(worst.utilization, 3)}). Consider a larger section.`
          : `The ${worst.name} is OVERSTRESSED (utilisation ${fmt(worst.utilization, 3)}). Do not load this arm.`);
    }
    if (v.motor_check) notes.push(`The motor runs at ${fmt(v.motor_check.speed_rpm, 0)} rpm delivering ${fmt(v.motor_check.power_out_W, 1)} W at ${fmt((v.motor_check.efficiency || 0) * 100, 1)}% efficiency for the given load.`);
  } else if (S.lastKind === 'control') {
    if (v.pid) {
      notes.push(v.pid.overshoot_percent < 10
        ? `Step response is well damped (overshoot ${fmt(v.pid.overshoot_percent, 1)}%, final error ${fmt(v.pid.final_error_rad, 3)} rad).`
        : `Overshoot is ${fmt(v.pid.overshoot_percent, 1)}% — raise Kd or lower Kp to damp it.`);
      if (Math.abs(v.pid.final_error_rad) > 0.05) notes.push('Steady-state error is still visible — raise Ki (slowly) or check for voltage saturation.');
    }
    if (v.trajectory) notes.push(`Trajectory peak joint velocity ${v.trajectory.max_velocity.map((x) => fmt(x * R2D, 0) + '°/s').join(', ')}. Check these against the joint speed limits before running it on hardware.`);
  } else if (S.lastKind === 'mobile') {
    notes.push('Odometry is dead reckoning: the trail is exact only if the wheels never slip. Add encoders + a gyro (or the sensors listed in the demo) for real localisation.');
  }
  out.innerHTML = '<ul>' + notes.map((n) => `<li>${esc(n)}</li>`).join('') + '</ul><p class="muted">Conceptual review only. Nothing here validates a robot for real use.</p>';
}
function buildReport() {
  const v = S.lastResults;
  const out = $('report-out');
  if (!v) { out.innerHTML = '<p class="muted">Run an analysis first.</p>'; return; }
  out.innerHTML = `<h3>Robotics report — ${esc(S.lastKind || '')}</h3>
    <p class="muted">Generated from the last server analysis. Methods: Denavit-Hartenberg FK, damped least-squares IK, DC-motor PID, cubic trajectories, unicycle odometry. Not validated for a real robot.</p>
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
  a.download = 'robotics-results.csv';
  a.click();
}

// ---------------- wiring ----------------
function init() {
  initView();
  loadMaterials();
  loadProjects();
  loadGuest();
  renderDH();
  renderSliders();
  renderAll();
  drawMobile();
  $('project-select').addEventListener('change', loadProjectDesign);
  $('demo-select').addEventListener('change', (e) => { if (e.target.value) loadDemo(e.target.value); });
  $('btn-add-joint').addEventListener('click', () => {
    S.dh.push({ a: 0.2, alpha: 0, d: 0, theta: 0 });
    S.joints.push(0);
    S.limits.push([-3.14, 3.14]);
    renderDH(); renderSliders(); renderAll(); saveGuest();
  });
  $('btn-del-joint').addEventListener('click', () => {
    if (S.dh.length <= 1) return;
    S.dh.pop(); S.joints.pop(); S.limits.pop();
    renderDH(); renderSliders(); renderAll(); saveGuest();
  });
  $('btn-run-ik').addEventListener('click', runIKOnly);
  $('btn-run-arm').addEventListener('click', runArmAnalysis);
  $('btn-save-design').addEventListener('click', saveDesign);
  $('btn-run-pid').addEventListener('click', runPID);
  $('btn-run-traj').addEventListener('click', runTrajectory);
  $('btn-run-dd').addEventListener('click', runDiffDrive);
  $('btn-run-square').addEventListener('click', runSquare);
  $('btn-assist').addEventListener('click', runAssistant);
  $('btn-report').addEventListener('click', buildReport);
  $('btn-csv').addEventListener('click', downloadCSV);
  window.__roboReady = true;
  window.__roboRefresh = () => { if (renderer) buildArm(); };
}
init();
