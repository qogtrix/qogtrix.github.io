/* Structural Engineering Laboratory — Stage 9.
   Designer + 3D view + analysis + calculations + assistant + report.
   All analysis runs on the server (direct-stiffness solver in
   backend/structure.py). Nothing here is a fake simulation: if the
   server cannot run it, the UI says so. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const API = (window.AIELAB_API_BASE || 'http://127.0.0.1:8001');
const token = () => localStorage.getItem('aielab.token');
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (v, d) => (v == null || !isFinite(v)) ? '—' : Number(v).toFixed(d == null ? 2 : d);
const DOFS = ['ux', 'uy', 'uz', 'rx', 'ry', 'rz'];
const GUEST_KEY = 'aielab.structure.guest';

function blankStructure() {
  return { version: 1, nodes: [], elements: [], supports: [], loads: [], combinations: [] };
}

const S = {
  structure: blankStructure(),
  projectId: '',
  projectName: '',
  results: null,        // last analysis `values` object
  jobId: null,
  selectedMember: null,
  materials: [],
  animating: null,      // { modeIndex, raf }
  deformed: false,
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

function status(msg) { $('struct-status').textContent = msg; }

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
  const sel = $('mem-material');
  sel.innerHTML = S.materials.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}${m.grade ? ' — ' + esc(m.grade) : ''}</option>`).join('');
  const steel = S.materials.find((m) => m.id === 'steel-s355');
  if (steel) sel.value = steel.id;
}
function matName(id) {
  const m = S.materials.find((x) => x.id === id);
  return m ? (m.name + (m.grade ? ' ' + m.grade : '')) : id;
}

// ---------------- projects ----------------
async function loadProjects() {
  const sel = $('project-select');
  if (!token()) { sel.innerHTML = '<option value="">(guest — structure saved locally only)</option>'; return; }
  try {
    const data = await api('/api/v1/projects');
    const list = data.projects || [];
    sel.innerHTML = '<option value="">(guest — structure saved locally only)</option>' +
      list.map((p) => `<option value="${esc(p.id)}">${esc(p.name || p.id)}</option>`).join('');
  } catch (e) { sel.innerHTML = '<option value="">(could not load projects)</option>'; }
}
async function loadProjectStructure() {
  S.projectId = $('project-select').value;
  S.results = null; S.selectedMember = null; hideResults();
  if (!S.projectId) { loadGuest(); renderAll(); return; }
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(S.projectId) + '/structure');
    S.structure = data.structure || blankStructure();
    status('Loaded structure from project (version ' + (S.structure.version || 1) + ').');
  } catch (e) {
    S.structure = blankStructure();
    status('No structure saved for this project yet — starting empty. (' + e.message + ')');
  }
  saveGuest();
  renderAll();
}
async function saveProjectStructure() {
  if (!S.projectId) { saveGuest(); status('Saved locally (guest mode). Sign in and pick a project to save it on the server.'); renderAll(); return; }
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(S.projectId) + '/structure', {
      method: 'PUT',
      body: JSON.stringify({ structure: S.structure, base_version: S.structure.version }),
    });
    S.structure = data.structure;
    status('Saved to project (version ' + S.structure.version + ').');
  } catch (e) {
    if (/409/.test(e.message)) status('Save conflict: the structure was changed elsewhere. Reload the project and re-apply your change.');
    else status('Save failed: ' + e.message);
  }
  renderAll();
}
function loadGuest() {
  try {
    const raw = localStorage.getItem(GUEST_KEY);
    if (raw) S.structure = JSON.parse(raw);
  } catch (e) { /* ignore */ }
}
function saveGuest() {
  try { localStorage.setItem(GUEST_KEY, JSON.stringify(S.structure)); } catch (e) { /* ignore */ }
}

// ---------------- editor ----------------
function nextId(prefix, items) {
  let i = items.length + 1;
  const ids = new Set(items.map((x) => x.id));
  while (ids.has(prefix + i)) i++;
  return prefix + i;
}
function sectionFromForm() {
  const t = $('mem-section-type').value;
  const b = parseFloat($('mem-b').value), h = parseFloat($('mem-h').value), d = parseFloat($('mem-d').value);
  if (t === 'rectangle') return { type: 'rectangle', b_m: b, h_m: h };
  if (t === 'circle') return { type: 'circle', d_m: d };
  if (t === 'ibeam') return { type: 'ibeam', b_m: b, h_m: h, tf_m: Math.max(0.005, h * 0.06), tw_m: Math.max(0.005, b * 0.08) };
  return { type: 'box', b_m: b, h_m: h, t_m: Math.max(0.005, Math.min(b, h) * 0.08) };
}
function sectionLabel(sec) {
  if (!sec) return '—';
  if (sec.type === 'rectangle') return `rect ${fmt(sec.b_m * 1000, 0)}×${fmt(sec.h_m * 1000, 0)} mm`;
  if (sec.type === 'circle') return `⌀ ${fmt(sec.d_m * 1000, 0)} mm`;
  if (sec.type === 'ibeam') return `I ${fmt(sec.b_m * 1000, 0)}×${fmt(sec.h_m * 1000, 0)} mm`;
  if (sec.type === 'box') return `box ${fmt(sec.b_m * 1000, 0)}×${fmt(sec.h_m * 1000, 0)} mm`;
  return sec.type;
}
function dofLabel(sup) { return DOFS.filter((d) => sup[d]).join(', ') || 'none'; }

function renderAll() {
  renderNodes(); renderMembers(); renderSupports(); renderLoads(); renderCombos();
  renderNodeSelects(); renderComboSelect(); renderSelectedMember();
  rebuildScene();
  saveGuest();
}
function renderNodes() {
  $('nodes-table').querySelector('tbody').innerHTML = S.structure.nodes.map((n) => {
    return `<tr><td>${esc(n.id)}</td><td>${fmt(n.x_m)}</td><td>${fmt(n.y_m)}</td><td>${fmt(n.z_m)}</td>` +
      `<td><button class="btn" data-del-node="${esc(n.id)}">✕</button></td></tr>`;
  }).join('') || '<tr><td colspan="5" class="muted">No nodes yet.</td></tr>';
}
function renderMembers() {
  $('members-table').querySelector('tbody').innerHTML = S.structure.elements.map((e) => {
    return `<tr><td>${esc(e.id)}</td><td>${esc(e.type)}</td><td>${esc(e.n1)} → ${esc(e.n2)}</td>` +
      `<td>${esc(sectionLabel(e.section))}</td><td>${esc(matName(e.material_id))}</td>` +
      `<td><button class="btn" data-del-member="${esc(e.id)}">✕</button></td></tr>`;
  }).join('') || '<tr><td colspan="6" class="muted">No members yet.</td></tr>';
}
function renderSupports() {
  $('supports-table').querySelector('tbody').innerHTML = S.structure.supports.map((s) => {
    return `<tr><td>${esc(s.node)}</td><td>${esc(dofLabel(s))}</td>` +
      `<td><button class="btn" data-del-support="${esc(s.node)}">✕</button></td></tr>`;
  }).join('') || '<tr><td colspan="3" class="muted">No supports yet — a structure needs at least one.</td></tr>';
}
function renderLoads() {
  $('loads-table').querySelector('tbody').innerHTML = S.structure.loads.map((l, i) => {
    let val = '';
    if (l.type === 'point') val = `(${fmt(l.fx_N, 0)}, ${fmt(l.fy_N, 0)}, ${fmt(l.fz_N, 0)}) N`;
    else if (l.type === 'distributed') val = `w=(${fmt(l.wx_N_m, 0)}, ${fmt(l.wy_N_m, 0)}, ${fmt(l.wz_N_m, 0)}) N/m · ${esc(l.coords || 'global')}`;
    else if (l.type === 'thermal') val = `ΔT ${fmt(l.dT_K, 1)} K`;
    else val = 'self-weight';
    const tgt = l.node || l.element || '—';
    return `<tr><td>${esc(l.case)}</td><td>${esc(l.type)}</td><td>${esc(tgt)}</td><td>${val}</td>` +
      `<td><button class="btn" data-del-load="${i}">✕</button></td></tr>`;
  }).join('') || '<tr><td colspan="5" class="muted">No loads yet.</td></tr>';
}
function renderCombos() {
  $('combos-table').querySelector('tbody').innerHTML = S.structure.combinations.map((c, i) => {
    return `<tr><td>${esc(c.name)}</td><td>${esc(JSON.stringify(c.factors || {}))}</td>` +
      `<td><button class="btn" data-del-combo="${i}">✕</button></td></tr>`;
  }).join('') || '<tr><td colspan="3" class="muted">No combinations — analyses run on all cases, unfactored.</td></tr>';
}
function renderNodeSelects() {
  const opts = S.structure.nodes.map((n) => `<option value="${esc(n.id)}">${esc(n.id)}</option>`).join('');
  ['mem-n1', 'mem-n2', 'sup-node'].forEach((id) => { $(id).innerHTML = opts; });
  const lt = $('load-target');
  const cur = $('load-type').value;
  if (cur === 'point') lt.innerHTML = opts;
  else if (cur === 'distributed' || cur === 'thermal') lt.innerHTML = S.structure.elements.map((e) => `<option value="${esc(e.id)}">${esc(e.id)}</option>`).join('');
  else lt.innerHTML = '<option value="">(whole structure)</option>';
}
function renderComboSelect() {
  const sel = $('analysis-combo');
  sel.innerHTML = '<option value="">All cases (unfactored)</option>' +
    S.structure.combinations.map((c) => `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join('');
}
function renderSelectedMember() {
  const el = S.selectedMember && S.structure.elements.find((e) => e.id === S.selectedMember);
  if (!el) {
    $('selected-member').innerHTML = '<p class="muted">No member selected. Click a member in the 3D view.</p>';
    $('member-diagrams').hidden = true;
    return;
  }
  const n1 = nodeById(el.n1), n2 = nodeById(el.n2);
  const len = (n1 && n2) ? Math.hypot(n2.x_m - n1.x_m, n2.y_m - n1.y_m, n2.z_m - n1.z_m) : null;
  let html = `<p><strong>${esc(el.id)}</strong> — ${esc(el.type)} · ${esc(el.n1)} → ${esc(el.n2)}` +
    (len != null ? ` · length ${fmt(len, 3)} m` : '') + `<br>Section: ${esc(sectionLabel(el.section))} · Material: ${esc(matName(el.material_id))}` +
    (el.k_factor != null ? ` · K = ${fmt(el.k_factor, 2)}` : '') + '</p>';
  const res = elResult(el.id);
  if (res) {
    const ax = elMaxAbs(res, 'axial_N'), mom = Math.max(elMaxAbs(res, 'moment_z_Nm') || 0, elMaxAbs(res, 'moment_y_Nm') || 0);
    const minAx = Math.min(...res.diagrams.map((d) => d.axial_N || 0));
    html += `<p>Axial: <strong>${fmt(ax / 1000, 2)} kN</strong> (${minAx < 0 ? 'compression' : 'tension'}) · ` +
      `Max moment: <strong>${fmt(mom / 1000, 2)} kN·m</strong> · Max stress: <strong>${fmt(res.max_stress_Pa / 1e6, 2)} MPa</strong> · ` +
      `Utilisation: <strong class="${res.utilization > 1 ? 'pill-bad' : res.utilization > 0.8 ? 'pill-warn' : 'pill-ok'}">${fmt(res.utilization, 3)}</strong>`;
    if (res.buckling) {
      html += ` · Buckling: Pcr ${fmt(res.buckling.critical_load_N / 1000, 1)} kN, utilisation ${fmt(res.buckling.utilization, 3)} (${esc(res.buckling.regime)})`;
    }
    html += '</p>';
    $('member-diagrams').hidden = false;
    drawDiagram('chart-axial', res.diagrams, 'axial_N', 'Axial force (N)');
    drawDiagram('chart-shear', res.diagrams, 'shear_y_N', 'Shear force (N)');
    drawDiagram('chart-moment', res.diagrams, 'moment_z_Nm', 'Bending moment (N·m)');
  } else {
    html += '<p class="muted">Run an analysis to see forces for this member.</p>';
    $('member-diagrams').hidden = true;
  }
  $('selected-member').innerHTML = html;
}
function nodeById(id) { return S.structure.nodes.find((n) => n.id === id); }
function elResult(id) { return S.results && Array.isArray(S.results.elements) ? S.results.elements.find((e) => e.id === id) : null; }
function elMaxAbs(el, key) {
  if (!el || !el.diagrams) return null;
  return Math.max(...el.diagrams.map((d) => Math.abs(d[key] || 0)));
}

// ---------------- editor events ----------------
function wireEditor() {
  $('btn-add-node').addEventListener('click', () => {
    const id = nextId('n', S.structure.nodes);
    S.structure.nodes.push({
      id,
      x_m: parseFloat($('node-x').value) || 0,
      y_m: parseFloat($('node-y').value) || 0,
      z_m: parseFloat($('node-z').value) || 0,
      ...( $('node-mass').value ? { mass_kg: parseFloat($('node-mass').value) } : {} ),
    });
    renderAll();
  });
  $('btn-add-member').addEventListener('click', () => {
    const n1 = $('mem-n1').value, n2 = $('mem-n2').value;
    if (!n1 || !n2) { status('Add two nodes first.'); return; }
    if (n1 === n2) { status('A member needs two different nodes.'); return; }
    const id = nextId('e', S.structure.elements);
    S.structure.elements.push({
      id, type: $('mem-type').value, n1, n2,
      material_id: $('mem-material').value,
      section: sectionFromForm(),
      k_factor: parseFloat($('mem-k').value) || 1.0,
    });
    renderAll();
  });
  $('sup-preset').addEventListener('change', () => {
    const p = $('sup-preset').value;
    const map = {
      fixed: { ux: 1, uy: 1, uz: 1, rx: 1, ry: 1, rz: 1 },
      pin: { ux: 1, uy: 1, uz: 1, rx: 1, ry: 0, rz: 0 },
      roller: { ux: 0, uy: 1, uz: 1, rx: 1, ry: 0, rz: 0 },
    };
    if (map[p]) {
      document.querySelectorAll('#sup-dofs input').forEach((cb) => { cb.checked = !!map[p][cb.dataset.dof]; });
    }
  });
  $('btn-add-support').addEventListener('click', () => {
    const node = $('sup-node').value;
    if (!node) { status('Add a node first.'); return; }
    const sup = { node };
    document.querySelectorAll('#sup-dofs input').forEach((cb) => { sup[cb.dataset.dof] = cb.checked; });
    const i = S.structure.supports.findIndex((s) => s.node === node);
    if (i >= 0) S.structure.supports[i] = sup; else S.structure.supports.push(sup);
    renderAll();
  });
  $('load-type').addEventListener('change', renderNodeSelects);
  $('btn-add-load').addEventListener('click', () => {
    const type = $('load-type').value;
    const load = { case: $('load-case').value.trim() || 'dead', type };
    if (type === 'point') {
      load.node = $('load-target').value;
      load.fx_N = parseFloat($('load-fx').value) || 0;
      load.fy_N = parseFloat($('load-fy').value) || 0;
      load.fz_N = parseFloat($('load-fz').value) || 0;
      if (!load.node) { status('Add a node first.'); return; }
    } else if (type === 'distributed') {
      load.element = $('load-target').value;
      load.wx_N_m = 0; load.wy_N_m = parseFloat($('load-w').value) || 0; load.wz_N_m = 0;
      load.coords = $('load-coords').value;
      if (!load.element) { status('Add a member first.'); return; }
    } else if (type === 'thermal') {
      load.element = $('load-target').value;
      load.dT_K = parseFloat($('load-w').value) || 0;
      if (!load.element) { status('Add a member first.'); return; }
    }
    S.structure.loads.push(load);
    renderAll();
  });
  $('btn-add-combo').addEventListener('click', () => {
    let factors;
    try { factors = JSON.parse($('combo-factors').value); } catch (e) { status('Combination factors must be valid JSON, e.g. {"dead": 1.5, "live": 1.5}'); return; }
    const name = $('combo-name').value.trim();
    if (!name) { status('Give the combination a name.'); return; }
    S.structure.combinations.push({ name, factors });
    renderAll();
  });
  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-del-node], button[data-del-member], button[data-del-support], button[data-del-load], button[data-del-combo]');
    if (!b) return;
    if (b.dataset.delNode) {
      const id = b.dataset.delNode;
      S.structure.nodes = S.structure.nodes.filter((n) => n.id !== id);
      S.structure.elements = S.structure.elements.filter((e) => e.n1 !== id && e.n2 !== id);
      S.structure.supports = S.structure.supports.filter((s) => s.node !== id);
      S.structure.loads = S.structure.loads.filter((l) => l.node !== id);
    } else if (b.dataset.delMember) {
      const id = b.dataset.delMember;
      S.structure.elements = S.structure.elements.filter((e) => e.id !== id);
      S.structure.loads = S.structure.loads.filter((l) => l.element !== id);
      if (S.selectedMember === id) S.selectedMember = null;
    } else if (b.dataset.delSupport) {
      S.structure.supports = S.structure.supports.filter((s) => s.node !== b.dataset.delSupport);
    } else if (b.dataset.delLoad != null) {
      S.structure.loads.splice(parseInt(b.dataset.delLoad, 10), 1);
    } else if (b.dataset.delCombo != null) {
      S.structure.combinations.splice(parseInt(b.dataset.delCombo, 10), 1);
    }
    renderAll();
  });
  $('project-select').addEventListener('change', loadProjectStructure);
  $('btn-save-json').addEventListener('click', saveProjectStructure);
  $('btn-load-json').addEventListener('click', () => $('file-json').click());
  $('file-json').addEventListener('change', async (ev) => {
    const f = ev.target.files[0];
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      const st = data.structure || data;
      if (!Array.isArray(st.nodes) || !Array.isArray(st.elements)) throw new Error('Not a structure file');
      S.structure = st; S.results = null; hideResults();
      renderAll();
      status('Loaded structure from file.');
    } catch (e) { status('Could not load file: ' + e.message); }
    ev.target.value = '';
  });
  $('btn-import-model').addEventListener('click', importFromModel);
}

// ---------------- demos ----------------
async function loadDemo(name) {
  try {
    const data = await (await fetch('workspace/test-structures/' + name + '.json')).json();
    const { expected, name: _n, ...rest } = data;
    S.structure = { version: 1, combinations: [], ...rest };
    S.results = null; S.selectedMember = null; hideResults();
    renderAll();
    status('Loaded demo: ' + (data.name || name) + '. Run an analysis to see results.');
  } catch (e) { status('Could not load demo: ' + e.message); }
}

// ---------------- import from 3D model ----------------
async function importFromModel() {
  if (!S.projectId) { status('Pick a project first — the 3D model lives in the project.'); return; }
  try {
    const data = await api('/api/v1/projects/' + encodeURIComponent(S.projectId) + '/model');
    const comps = (data.model && data.model.components) || [];
    let imported = 0, skipped = 0;
    const nodesByKey = new Map();
    const getNode = (x, y, z) => {
      const key = [x, y, z].map((v) => Math.round(v * 1000)).join(',');
      if (nodesByKey.has(key)) return nodesByKey.get(key);
      const id = nextId('n', S.structure.nodes);
      S.structure.nodes.push({ id, x_m: x, y_m: y, z_m: z });
      nodesByKey.set(key, id);
      return id;
    };
    for (const c of comps) {
      const lenMm = c.params && (c.params.length || c.params.barrel_length);
      if (!['beam', 'pipe', 'shaft'].includes(c.kind) || !lenMm) { skipped++; continue; }
      const p = c.position || [0, 0, 0];
      const rot = c.rotation || [0, 0, 0];
      const rad = (deg) => deg * Math.PI / 180;
      const [rx, ry, rz] = rot.map(rad);
      // rotate local +X by Z, then Y, then X (same order as the modeller)
      let v = [lenMm / 1000, 0, 0];
      const cz = Math.cos(rz), sz = Math.sin(rz);
      v = [v[0] * cz - v[1] * sz, v[0] * sz + v[1] * cz, v[2]];
      const cy = Math.cos(ry), sy = Math.sin(ry);
      v = [v[0] * cy + v[2] * sy, v[1], -v[0] * sy + v[2] * cy];
      const cx = Math.cos(rx), sx = Math.sin(rx);
      v = [v[0], v[1] * cx - v[2] * sx, v[1] * sx + v[2] * cx];
      const start = [p[0] / 1000, p[1] / 1000, p[2] / 1000];
      const end = [start[0] + v[0], start[1] + v[1], start[2] + v[2]];
      const n1 = getNode(start[0], start[1], start[2]);
      const n2 = getNode(end[0], end[1], end[2]);
      const dMm = c.params.diameter || c.params.bore_diameter || 50;
      S.structure.elements.push({
        id: nextId('e', S.structure.elements),
        type: 'beam', n1, n2,
        material_id: c.material_id || 'steel-s355',
        section: { type: 'circle', d_m: dMm / 1000 },
        k_factor: 1.0,
      });
      imported++;
    }
    renderAll();
    status(`Imported ${imported} member(s) from the 3D model` + (skipped ? `; ${skipped} component(s) skipped (no length or not a beam/pipe/shaft).` : '.') +
      ' Add supports and loads, then run an analysis.');
  } catch (e) { status('Import failed: ' + e.message); }
}

// ---------------- diagrams (canvas) ----------------
function drawDiagram(canvasId, diagram, key, label) {
  const cv = $(canvasId);
  if (!cv || !diagram) return;
  const ctx = cv.getContext('2d');
  const W = cv.width = cv.clientWidth * 2, H = cv.height = 400;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#888'; ctx.font = '20px sans-serif';
  ctx.fillText(label, 10, 26);
  const pts = diagram.map((d) => [d.x_m, d[key]]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys, 0), y1 = Math.max(...ys, 0);
  if (y1 - y0 < 1e-12) { y0 -= 1; y1 += 1; }
  const px = (x) => 40 + (x - x0) / (x1 - x0 || 1) * (W - 60);
  const py = (y) => H - 30 - (y - y0) / (y1 - y0) * (H - 70);
  ctx.strokeStyle = '#555'; ctx.beginPath(); ctx.moveTo(40, py(0)); ctx.lineTo(W - 20, py(0)); ctx.stroke();
  ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 3; ctx.beginPath();
  pts.forEach(([x, y], i) => { i ? ctx.lineTo(px(x), py(y)) : ctx.moveTo(px(x), py(y)); });
  ctx.stroke();
  ctx.fillStyle = '#ccc'; ctx.fillText(fmt(y1, 1), 6, py(y1) + 6); ctx.fillText(fmt(y0, 1), 6, py(y0) + 6);
  ctx.fillText(fmt(x0, 2) + ' m', 40, H - 6); ctx.fillText(fmt(x1, 2) + ' m', W - 110, H - 6);
}

function hideResults() {
  ['results-summary', 'results-reactions', 'results-members', 'results-modal', 'results-warnings'].forEach((id) => { $(id).hidden = true; });
}

// ---------------- 3D viewport ----------------
let renderer, scene, camera, controls, modelGroup, raycaster, pointer;
const memberMeshes = new Map();
const PALETTE = ['#38bdf8', '#4ade80', '#facc15', '#f472b6', '#a78bfa', '#fb923c', '#2dd4bf', '#f87171'];

function initViewport() {
  const el = $('viewport');
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(el.clientWidth, el.clientHeight);
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0e14);
  camera = new THREE.PerspectiveCamera(45, el.clientWidth / el.clientHeight, 0.01, 1000);
  camera.position.set(6, 5, 8);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dl = new THREE.DirectionalLight(0xffffff, 1.2);
  dl.position.set(5, 10, 5);
  scene.add(dl);
  scene.add(new THREE.GridHelper(20, 20, 0x334155, 0x1e293b));
  const axes = new THREE.AxesHelper(2);
  scene.add(axes);
  modelGroup = new THREE.Group();
  scene.add(modelGroup);
  raycaster = new THREE.Raycaster();
  pointer = new THREE.Vector2();
  renderer.domElement.addEventListener('click', onViewportClick);
  window.addEventListener('resize', () => {
    renderer.setSize(el.clientWidth, el.clientHeight);
    camera.aspect = el.clientWidth / el.clientHeight;
    camera.updateProjectionMatrix();
  });
  (function loop() {
    requestAnimationFrame(loop);
    if (S.animating) animateMode();
    controls.update();
    renderer.render(scene, camera);
  })();
}
function onViewportClick(ev) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects([...memberMeshes.values()], false);
  if (hits.length) {
    S.selectedMember = hits[0].object.userData.elementId;
    renderSelectedMember();
    rebuildScene();
  }
}
function displacedPos(node) {
  if (!S.results || !$('view-deformed').checked) return [node.x_m, node.y_m, node.z_m];
  const d = S.results.nodes && S.results.nodes[node.id];
  const ex = parseFloat($('view-exagg').value) || 100;
  if (!d || !d.displacement_m) return [node.x_m, node.y_m, node.z_m];
  return [node.x_m + d.displacement_m[0] * ex, node.y_m + d.displacement_m[1] * ex, node.z_m + d.displacement_m[2] * ex];
}
function utilColor(util, bucklingUtil) {
  if (bucklingUtil != null && bucklingUtil > 0.8) return '#38bdf8';
  if (util == null) return '#94a3b8';
  if (util > 1) return '#f87171';
  if (util > 0.8) return '#facc15';
  return '#4ade80';
}
function matColor(id) {
  let h = 0;
  for (const c of String(id)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
function rebuildScene() {
  if (!modelGroup) return;
  modelGroup.clear();
  memberMeshes.clear();
  const st = S.structure;
  const mode = $('view-colour').value;
  const pos = {};
  for (const n of st.nodes) pos[n.id] = displacedPos(n);
  for (const e of st.elements) {
    const a = pos[e.n1], b = pos[e.n2];
    if (!a || !b) continue;
    const av = new THREE.Vector3(...a), bv = new THREE.Vector3(...b);
    const dir = bv.clone().sub(av);
    const len = dir.length();
    if (len < 1e-9) continue;
    const mid = av.clone().add(bv).multiplyScalar(0.5);
    let mesh;
    if (e.type === 'truss') {
      const geo = new THREE.CylinderGeometry(0.025, 0.025, len, 10);
      mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x94a3b8 }));
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
    } else {
      const sec = e.section || {};
      const h = Math.max(0.02, (sec.h_m || sec.d_m || 0.1));
      const w = Math.max(0.02, (sec.b_m || sec.d_m || 0.1));
      const geo = new THREE.BoxGeometry(len, h, w);
      mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x94a3b8 }));
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir.clone().normalize());
    }
    let color = '#94a3b8';
    if (mode === 'material') color = matColor(e.material_id);
    else {
      const r = elResult(e.id);
      if (r) color = utilColor(r.utilization, r.buckling ? r.buckling.utilization : null);
    }
    mesh.material.color.set(color);
    if (S.selectedMember === e.id) {
      mesh.material.emissive = new THREE.Color(0x334155);
      mesh.material.emissiveIntensity = 0.8;
    }
    mesh.position.copy(mid);
    mesh.userData.elementId = e.id;
    modelGroup.add(mesh);
    memberMeshes.set(e.id, mesh);
  }
  for (const n of st.nodes) {
    const p = pos[n.id];
    const sph = new THREE.Mesh(
      new THREE.SphereGeometry(0.06, 12, 12),
      new THREE.MeshStandardMaterial({ color: 0xe2e8f0 }));
    sph.position.set(...p);
    modelGroup.add(sph);
    if (st.supports.some((s) => s.node === n.id)) {
      const cone = new THREE.Mesh(
        new THREE.ConeGeometry(0.12, 0.25, 4),
        new THREE.MeshStandardMaterial({ color: 0x4ade80 }));
      cone.position.set(p[0], p[1] - 0.18, p[2]);
      cone.rotation.y = Math.PI / 4;
      modelGroup.add(cone);
    }
  }
  if ($('view-loads').checked) {
    for (const l of st.loads) {
      if (l.type === 'point' && l.node && pos[l.node]) {
        const p = pos[l.node];
        const v = new THREE.Vector3(l.fx_N || 0, l.fy_N || 0, l.fz_N || 0);
        if (v.lengthSq() > 0) {
          const arrow = new THREE.ArrowHelper(v.clone().normalize(), new THREE.Vector3(...p), 0.6, 0xf87171, 0.15, 0.08);
          modelGroup.add(arrow);
        }
      } else if (l.type === 'distributed' && l.element && pos[S.structure.elements.find((e) => e.id === l.element)?.n1]) {
        const e = S.structure.elements.find((x) => x.id === l.element);
        const a = new THREE.Vector3(...pos[e.n1]), b = new THREE.Vector3(...pos[e.n2]);
        for (let i = 1; i <= 3; i++) {
          const p = a.clone().lerp(b, i / 4);
          const w = new THREE.Vector3(l.wx_N_m || 0, l.wy_N_m || 0, l.wz_N_m || 0);
          if (w.lengthSq() > 0) modelGroup.add(new THREE.ArrowHelper(w.clone().normalize(), p, 0.5, 0xfacc15, 0.12, 0.06));
        }
      }
    }
  }
  if (S.animating) applyModeShape();
}
function fitView() {
  if (!S.structure.nodes.length) return;
  const xs = S.structure.nodes.map((n) => n.x_m), ys = S.structure.nodes.map((n) => n.y_m), zs = S.structure.nodes.map((n) => n.z_m);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2, cz = (Math.min(...zs) + Math.max(...zs)) / 2;
  const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), Math.max(...zs) - Math.min(...zs), 1);
  controls.target.set(cx, cy, cz);
  camera.position.set(cx + span * 0.9, cy + span * 0.7, cz + span * 1.1);
  camera.updateProjectionMatrix();
}
function applyModeShape() {
  if (!S.animating || !S.results || !S.results.modes) return;
  const mode = S.results.modes[S.animating.modeIndex];
  if (!mode) return;
  const t = performance.now() / 1000;
  const amp = S.animating.amplitude * Math.sin(2 * Math.PI * t);
  const base = {};
  for (const n of S.structure.nodes) base[n.id] = [n.x_m, n.y_m, n.z_m];
  for (const e of S.structure.elements) {
    const mesh = memberMeshes.get(e.id);
    if (!mesh) continue;
    const a = base[e.n1], b = base[e.n2];
    const sa = mode.shape[e.n1] || [0, 0, 0], sb = mode.shape[e.n2] || [0, 0, 0];
    const av = new THREE.Vector3(a[0] + sa[0] * amp, a[1] + sa[1] * amp, a[2] + sa[2] * amp);
    const bv = new THREE.Vector3(b[0] + sb[0] * amp, b[1] + sb[1] * amp, b[2] + sb[2] * amp);
    const dir = bv.clone().sub(av);
    const len = dir.length();
    if (len < 1e-9) continue;
    mesh.position.copy(av.clone().add(bv).multiplyScalar(0.5));
    if (e.type === 'truss') mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    else mesh.quaternion.setFromUnitVectors(new THREE.Vector3(1, 0, 0), dir.normalize());
  }
}
function animateMode() { applyModeShape(); }

// ---------------- analysis ----------------
async function runAnalysis() {
  if (!S.projectId) { $('analysis-status').textContent = 'Pick a project first (sign in, then select it on the Designer tab).'; return; }
  const atype = $('analysis-type').value;
  const combo = $('analysis-combo').value || undefined;
  $('analysis-status').textContent = 'Running ' + atype + ' analysis…';
  try {
    const job = await api('/api/v1/structures/analyze', {
      method: 'POST',
      body: JSON.stringify({
        project_id: S.projectId,
        structure: S.structure,
        analysis: { type: atype, combination: combo, n_modes: parseInt($('analysis-nmodes').value, 10) || 5 },
      }),
    });
    S.jobId = job.id;
    if (job.status === 'completed' && job.results && job.results.values) {
      S.results = job.results.values;
      $('analysis-status').textContent = 'Completed (job ' + job.id + ').';
      renderResults();
    } else {
      $('analysis-status').textContent = 'Analysis failed: ' + ((job.results && job.results.error) || job.note || 'unknown error');
      hideResults();
    }
    rebuildScene();
    renderSelectedMember();
    await loadJobs();
  } catch (e) {
    $('analysis-status').textContent = 'Analysis failed: ' + e.message;
  }
}
function renderResults() {
  const r = S.results;
  if (!r) return;
  const util = (u) => `<span class="${u > 1 ? 'pill-bad' : u > 0.8 ? 'pill-warn' : 'pill-ok'}">${fmt(u, 3)}</span>`;
  // summary
  const maxStress = Array.isArray(r.elements) && r.elements.length ? Math.max(...r.elements.map((e) => e.max_stress_Pa || 0)) : null;
  let s = `<p>Analysis: <strong>${esc(r.analysis || 'static')}</strong> · Combination: <strong>${esc(r.combination || 'all cases, unfactored')}</strong><br>` +
    `Max displacement: <strong>${fmt(r.max_displacement_m * 1000, 3)} mm</strong> · Max member utilisation: <strong>${r.max_utilization != null ? util(r.max_utilization) : '—'}</strong>` +
    (r.max_buckling_utilization != null ? ` · Max buckling utilisation: <strong>${util(r.max_buckling_utilization)}</strong>` : '') +
    (maxStress != null ? ` · Max stress: <strong>${fmt(maxStress / 1e6, 2)} MPa</strong>` : '') + '</p>';
  if (r.warnings && r.warnings.length) s += `<p class="warn-list">Warnings: ${esc(r.warnings.join('; '))}</p>`;
  $('summary-body').innerHTML = s;
  $('results-summary').hidden = false;
  // reactions + displacements
  const rows = Object.entries(r.nodes || {}).map(([id, n]) => {
    const R = n.reaction || [], d = n.displacement_m || [0, 0, 0];
    const cell = (i) => (R[i] == null ? '—' : fmt(R[i], 1));
    return `<tr><td>${esc(id)}</td><td>${cell(0)}</td><td>${cell(1)}</td><td>${cell(2)}</td><td>${fmt(d[0] * 1000, 3)}</td><td>${fmt(d[1] * 1000, 3)}</td><td>${fmt(d[2] * 1000, 3)}</td></tr>`;
  }).join('');
  $('reactions-table').querySelector('tbody').innerHTML = rows;
  $('results-reactions').hidden = false;
  // members
  const mrows = (Array.isArray(r.elements) ? r.elements : []).map((e) => {
    const b = e.buckling
      ? `Pcr ${fmt(e.buckling.critical_load_N / 1000, 1)} kN · ${util(e.buckling.utilization)} (${esc(e.buckling.regime)})` : '—';
    const ax = elMaxAbs(e, 'axial_N'), sh = elMaxAbs(e, 'shear_y_N');
    const mom = Math.max(elMaxAbs(e, 'moment_z_Nm') || 0, elMaxAbs(e, 'moment_y_Nm') || 0);
    return `<tr><td>${esc(e.id)}</td><td>${fmt(ax / 1000, 2)}</td><td>${fmt(sh / 1000, 2)}</td><td>${fmt(mom / 1000, 2)}</td><td>${fmt(e.max_stress_Pa / 1e6, 2)}</td><td>${util(e.utilization)}</td><td>${b}</td></tr>`;
  }).join('');
  $('members-results-table').querySelector('tbody').innerHTML = mrows;
  $('results-members').hidden = false;
  // modal
  if (r.modes) {
    $('modal-table').querySelector('tbody').innerHTML = r.modes.map((m, i) =>
      `<tr><td>${i + 1}</td><td>${fmt(m.frequency_hz, 3)}</td><td>${m.period_s != null ? fmt(m.period_s, 3) : '—'}</td><td>${m.warning ? '<span class="pill-warn">' + esc(m.warning) + '</span>' : ''}</td></tr>`).join('');
    $('modal-select').innerHTML = r.modes.map((m, i) => `<option value="${i}">Mode ${i + 1} — ${fmt(m.frequency_hz, 2)} Hz</option>`).join('');
    $('results-modal').hidden = false;
  }
  if (r.warnings && r.warnings.length) {
    $('warnings-list').innerHTML = r.warnings.map((w) => `<li>${esc(w)}</li>`).join('');
    $('results-warnings').hidden = false;
  } else { $('results-warnings').hidden = true; }
}
async function loadJobs() {
  if (!S.projectId) { $('jobs-table').querySelector('tbody').innerHTML = '<tr><td colspan="5" class="muted">Pick a project to see jobs.</td></tr>'; return; }
  try {
    const data = await api('/api/v1/simulations?project_id=' + encodeURIComponent(S.projectId));
    const jobs = (data.simulations || []).filter((j) => String(j.solver || '').startsWith('structural_'));
    $('jobs-table').querySelector('tbody').innerHTML = jobs.map((j) =>
      `<tr><td>${esc(j.id)}</td><td>${esc(j.solver)}</td><td>${esc(j.status)}</td><td>${esc(j.created_at || '')}</td>` +
      `<td>${j.status === 'completed' ? `<button class="btn" data-view-job="${esc(j.id)}">View</button>` : ''}</td></tr>`).join('')
      || '<tr><td colspan="5" class="muted">No structural jobs yet.</td></tr>';
    $('jobs-table').dataset.jobs = JSON.stringify(jobs);
  } catch (e) { /* ignore */ }
}
function viewJob(id) {
  const jobs = JSON.parse($('jobs-table').dataset.jobs || '[]');
  const j = jobs.find((x) => x.id === id);
  if (!j || !j.results || !j.results.values) return;
  S.results = j.results.values;
  renderResults();
  rebuildScene();
  renderSelectedMember();
  $('analysis-status').textContent = 'Showing job ' + id + '.';
}

// ---------------- calculations ----------------
const CALC_FIELDS = {
  column_buckling: [
    { key: 'length_m', label: 'Column length (m)', type: 'number', value: 3, step: 0.1 },
    { key: 'k_factor', label: 'K factor (effective length)', type: 'number', value: 1, step: 0.1 },
    { key: 'section', label: 'Cross-section', type: 'section' },
    { key: 'material_id', label: 'Material', type: 'material' },
    { key: 'load_N', label: 'Applied load (N, optional)', type: 'number', value: 100000, step: 1000 },
  ],
  fixed_beam: [
    { key: 'length_m', label: 'Beam length (m)', type: 'number', value: 4, step: 0.1 },
    { key: 'load_N', label: 'Centre point load (N)', type: 'number', value: 10000, step: 100 },
    { key: 'section', label: 'Cross-section', type: 'section' },
    { key: 'material_id', label: 'Material', type: 'material' },
  ],
  natural_frequency_beam: [
    { key: 'length_m', label: 'Beam length (m)', type: 'number', value: 2, step: 0.1 },
    { key: 'section', label: 'Cross-section', type: 'section' },
    { key: 'material_id', label: 'Material', type: 'material' },
    { key: 'support', label: 'Supports', type: 'select', options: [['cantilever', 'Cantilever'], ['simply_supported', 'Simply supported'], ['fixed_fixed', 'Fixed–fixed'], ['free_free', 'Free–free']] },
  ],
  wind_load_is875: [
    { key: 'basic_wind_speed_m_s', label: 'Basic wind speed Vb (m/s)', type: 'number', value: 44, step: 1 },
    { key: 'k1', label: 'k1 — risk coefficient', type: 'number', value: 1, step: 0.01 },
    { key: 'k2', label: 'k2 — terrain/height factor', type: 'number', value: 1, step: 0.01 },
    { key: 'k3', label: 'k3 — topography factor', type: 'number', value: 1, step: 0.01 },
    { key: 'area_m2', label: 'Projected area (m²)', type: 'number', value: 10, step: 0.5 },
    { key: 'force_coefficient', label: 'Force coefficient Cf', type: 'number', value: 1.3, step: 0.05 },
  ],
  seismic_base_shear_is1893: [
    { key: 'seismic_weight_N', label: 'Seismic weight W (N)', type: 'number', value: 1000000, step: 10000 },
    { key: 'zone_factor', label: 'Zone factor Z', type: 'number', value: 0.36, step: 0.01 },
    { key: 'importance_factor', label: 'Importance factor I', type: 'number', value: 1, step: 0.1 },
    { key: 'response_reduction_factor', label: 'Response reduction factor R', type: 'number', value: 5, step: 0.5 },
    { key: 'sa_g', label: 'Sa/g (spectral acceleration)', type: 'number', value: 2.5, step: 0.1 },
  ],
  load_combination: [
    { key: 'combination', label: 'Combination', type: 'select', options: [['1.5(DL+LL)', '1.5(DL+LL)'], ['1.2(DL+LL+WL)', '1.2(DL+LL+WL)'], ['1.2(DL+LL+EL)', '1.2(DL+LL+EL)'], ['1.5(DL+WL)', '1.5(DL+WL)'], ['1.5(DL+EL)', '1.5(DL+EL)'], ['0.9DL+1.5WL', '0.9DL+1.5WL'], ['0.9DL+1.5EL', '0.9DL+1.5EL'], ['1.5(DL+SL)', '1.5(DL+SL)']] },
    { key: 'dead_N', label: 'Dead load (N)', type: 'number', value: 10000, step: 100 },
    { key: 'live_N', label: 'Live load (N)', type: 'number', value: 5000, step: 100 },
    { key: 'wind_N', label: 'Wind load (N)', type: 'number', value: 0, step: 100 },
    { key: 'seismic_N', label: 'Seismic load (N)', type: 'number', value: 0, step: 100 },
    { key: 'snow_N', label: 'Snow load (N)', type: 'number', value: 0, step: 100 },
    { key: 'thermal_N', label: 'Thermal load (N)', type: 'number', value: 0, step: 100 },
  ],
};
function renderCalcForm() {
  const solver = $('calc-select').value;
  const fields = CALC_FIELDS[solver] || [];
  $('calc-form').innerHTML = fields.map((f) => {
    if (f.type === 'section') {
      return `<div class="field-row"><label>Section type</label><select id="calc-section-type">
        <option value="rectangle">Rectangle</option><option value="circle">Circle</option>
        <option value="ibeam">I-beam</option><option value="box">Box</option></select></div>
      <div class="field-row"><label>b (m)</label><input id="calc-b" type="number" step="0.01" value="0.1"></div>
      <div class="field-row"><label>h (m)</label><input id="calc-h" type="number" step="0.01" value="0.2"></div>
      <div class="field-row"><label>d (m)</label><input id="calc-d" type="number" step="0.01" value="0.1"></div>`;
    }
    if (f.type === 'material') {
      return `<div class="field-row"><label>${esc(f.label)}</label><select id="calc-${f.key}">` +
        S.materials.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}${m.grade ? ' — ' + esc(m.grade) : ''}</option>`).join('') + '</select></div>';
    }
    if (f.type === 'select') {
      return `<div class="field-row"><label>${esc(f.label)}</label><select id="calc-${f.key}">` +
        f.options.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('') + '</select></div>';
    }
    return `<div class="field-row"><label>${esc(f.label)}</label><input id="calc-${f.key}" type="number" step="${f.step}" value="${f.value}"></div>`;
  }).join('');
}
function collectCalcInputs() {
  const solver = $('calc-select').value;
  const inputs = {};
  for (const f of CALC_FIELDS[solver]) {
    if (f.type === 'section') {
      const t = $('calc-section-type').value;
      const b = parseFloat($('calc-b').value), h = parseFloat($('calc-h').value), d = parseFloat($('calc-d').value);
      if (t === 'rectangle') inputs.section = { type: 'rectangle', b_m: b, h_m: h };
      else if (t === 'circle') inputs.section = { type: 'circle', d_m: d };
      else if (t === 'ibeam') inputs.section = { type: 'ibeam', b_m: b, h_m: h, tf_m: Math.max(0.005, h * 0.06), tw_m: Math.max(0.005, b * 0.08) };
      else inputs.section = { type: 'box', b_m: b, h_m: h, t_m: Math.max(0.005, Math.min(b, h) * 0.08) };
    } else if (f.type === 'number') {
      const v = parseFloat($('calc-' + f.key).value);
      if (isFinite(v)) inputs[f.key] = v;
    } else {
      inputs[f.key] = $('calc-' + f.key).value;
    }
  }
  return inputs;
}
async function runCalc() {
  const solver = $('calc-select').value;
  if (!S.projectId) { $('calc-result').innerHTML = '<p class="warn-list">Pick a project first (sign in, then select it on the Designer tab) — calculations are stored as simulation jobs.</p>'; return; }
  const inputs = collectCalcInputs();
  $('calc-result').innerHTML = '<p class="muted">Calculating…</p>';
  try {
    const job = await api('/api/v1/simulations', {
      method: 'POST',
      body: JSON.stringify({ project_id: S.projectId, solver, inputs }),
    });
    if (job.status === 'completed' && job.results && job.results.values) {
      const vals = job.results.values;
      const rows = Object.entries(vals).filter(([k]) => !['assumptions'].includes(k)).map(([k, v]) =>
        `<tr><td>${esc(k)}</td><td>${typeof v === 'number' ? fmt(v, 4) : esc(JSON.stringify(v))}</td></tr>`).join('');
      $('calc-result').innerHTML = `<table class="results"><thead><tr><th>Result</th><th>Value</th></tr></thead><tbody>${rows}</tbody></table>` +
        `<p class="small muted">${esc((job.results.assumptions || []).join(' · '))}</p>`;
    } else {
      $('calc-result').innerHTML = '<p class="warn-list">Calculation failed: ' + esc((job.results && job.results.error) || job.note || 'unknown error') + '</p>';
    }
  } catch (e) { $('calc-result').innerHTML = '<p class="warn-list">Calculation failed: ' + esc(e.message) + '</p>'; }
}

// ---------------- AI assistant ----------------
function assistantReview() {
  const out = $('assistant-output');
  if (!S.results) {
    out.innerHTML = '<p>I have nothing to review yet — run a static analysis first (Analysis tab, needs a signed-in project), then I will read the actual results.</p>';
    return;
  }
  const r = S.results;
  const els = Array.isArray(r.elements) ? r.elements : [];
  let html = `<p>Review of the last <strong>${esc(r.analysis || 'static')}</strong> run${r.combination ? ' (' + esc(r.combination) + ')' : ''}:</p><ul>`;
  if (r.max_utilization != null && els.length) {
    const worst = els.reduce((a, b) => ((b.utilization || 0) > (a.utilization || 0) ? b : a), els[0]);
    html += `<li>Most stressed member: <strong>${esc(worst.id)}</strong> — utilisation ${fmt(worst.utilization, 3)}` +
      (worst.utilization > 1 ? ' — <strong>overstressed</strong>. It fails the preliminary check (stress above the recorded strength). Increase the section depth — bending capacity grows roughly with h² and stiffness with h³ — or use a higher-yield steel grade, then re-run.' :
       worst.utilization > 0.8 ? ' — marginal. Keep an eye on it; a small section increase gives comfortable margin.' :
       ' — within the preliminary check.') + '</li>';
  }
  if (r.max_displacement_m != null) {
    const longest = els.map((el) => {
      const e = S.structure.elements.find((x) => x.id === el.id);
      if (!e) return 0;
      const a = nodeById(e.n1), b = nodeById(e.n2);
      return a && b ? Math.hypot(b.x_m - a.x_m, b.y_m - a.y_m, b.z_m - a.z_m) : 0;
    }).reduce((a, b) => Math.max(a, b), 0);
    const ratio = longest ? (r.max_displacement_m / (longest / 250)) : null;
    html += `<li>Max displacement ${fmt(r.max_displacement_m * 1000, 2)} mm` +
      (ratio != null ? ` — ${ratio > 1 ? '<strong>exceeds</strong>' : 'within'} the L/250 rule of thumb (longest member ${fmt(longest, 2)} m → limit ${fmt(longest / 250 * 1000, 1)} mm). ` : '') +
      (ratio != null && ratio > 1 ? 'Stiffen the structure: deeper sections or added bracing reduce deflection fastest.' : '') + '</li>';
  }
  if (r.max_buckling_utilization != null) {
    const bc = els.filter((e) => e.buckling)
      .reduce((a, b) => ((b.buckling.utilization || 0) > ((a && a.buckling && a.buckling.utilization) || 0) ? b : a), null);
    if (bc) {
      html += `<li>Buckling-critical member: <strong>${esc(bc.id)}</strong> — utilisation ${fmt(bc.buckling.utilization, 3)} (${esc(bc.buckling.regime)}, Pcr ${fmt(bc.buckling.critical_load_N / 1000, 1)} kN). ` +
        (bc.buckling.utilization > 1 ? 'It buckles before it yields under this load. Shorten its effective length (add bracing, reduce K·L) or use a stockier section — buckling load grows with I, i.e. roughly h⁴ for a rectangle.' :
         bc.buckling.utilization > 0.8 ? 'Close to its buckling load — consider bracing or a larger section.' : 'OK for this load.') + '</li>';
    }
  }
  if (r.modes) {
    const f1 = r.modes.find((m) => m.frequency_hz > 0);
    if (f1) html += `<li>First natural frequency: <strong>${fmt(f1.frequency_hz, 2)} Hz</strong>. If a machine or wind load excites the structure near this frequency, resonance is a risk — keep operating frequencies well away from it.</li>`;
  }
  if (r.warnings && r.warnings.length) html += `<li>Warnings from the solver: ${esc(r.warnings.join('; '))}</li>`;
  html += '</ul><p class="small muted">This is a preliminary review of a linear-elastic, first-order analysis. It is not a code check and not a design approval.</p>';
  out.innerHTML = html;
}

// ---------------- report ----------------
function buildReport() {
  const st = S.structure, r = S.results;
  const mats = [...new Set(st.elements.map((e) => e.material_id))];
  let html = `<h3>Structural Analysis Report</h3>
  <p class="small muted">Generated ${new Date().toISOString().slice(0, 10)} · AI Engineering Laboratory, Stage 9 · Method: direct-stiffness, linear-elastic, first-order (no P-delta, no system buckling, no plate/shell FEA).</p>
  <h4>Structure</h4><p>${st.nodes.length} nodes, ${st.elements.length} members (${st.elements.filter((e) => e.type === 'beam').length} beams, ${st.elements.filter((e) => e.type === 'truss').length} truss), ${st.supports.length} supports, ${st.loads.length} loads, ${st.combinations.length} combinations.</p>
  <p>Materials: ${mats.map((m) => esc(matName(m))).join(', ') || '—'}</p>
  <h4>Loads</h4><ul>${st.loads.map((l) => `<li>${esc(l.case)} — ${esc(l.type)} — ${esc(l.node || l.element || 'whole structure')}</li>`).join('') || '<li>None</li>'}</ul>
  <h4>Combinations</h4><ul>${st.combinations.map((c) => `<li>${esc(c.name)}: ${esc(JSON.stringify(c.factors))}</li>`).join('') || '<li>None — unfactored cases</li>'}</ul>`;
  if (r) {
    const rMaxStress = Array.isArray(r.elements) && r.elements.length ? Math.max(...r.elements.map((e) => e.max_stress_Pa || 0)) : null;
    html += `<h4>Results (${esc(r.analysis || 'static')}${r.combination ? ' · ' + esc(r.combination) : ''})</h4>
    <p>Max displacement ${fmt(r.max_displacement_m * 1000, 3)} mm · Max utilisation ${r.max_utilization != null ? fmt(r.max_utilization, 3) : '—'}` +
      (r.max_buckling_utilization != null ? ` · Max buckling utilisation ${fmt(r.max_buckling_utilization, 3)}` : '') +
      (rMaxStress != null ? ` · Max stress ${fmt(rMaxStress / 1e6, 2)} MPa` : '') + '</p>' +
      `<table class="results"><thead><tr><th>Member</th><th>Axial (kN)</th><th>Moment (kN·m)</th><th>Stress (MPa)</th><th>Utilisation</th></tr></thead><tbody>` +
      (Array.isArray(r.elements) ? r.elements : []).map((e) => {
        const ax = elMaxAbs(e, 'axial_N'), mom = Math.max(elMaxAbs(e, 'moment_z_Nm') || 0, elMaxAbs(e, 'moment_y_Nm') || 0);
        return `<tr><td>${esc(e.id)}</td><td>${fmt(ax / 1000, 2)}</td><td>${fmt(mom / 1000, 2)}</td><td>${fmt(e.max_stress_Pa / 1e6, 2)}</td><td>${fmt(e.utilization, 3)}</td></tr>`;
      }).join('') + '</tbody></table>';
    if (r.modes) html += `<h4>Natural frequencies</h4><ul>${r.modes.map((m, i) => `<li>Mode ${i + 1}: ${fmt(m.frequency_hz, 3)} Hz</li>`).join('')}</ul>`;
    if (r.warnings && r.warnings.length) html += `<h4>Warnings</h4><ul class="warn-list">${r.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>`;
  } else {
    html += '<p class="warn-list">No analysis has been run for this report.</p>';
  }
  html += `<h4>Limitations</h4><p class="small muted">Preliminary, educational analysis only. No code compliance (IS 800 / IS 456 / AISC / Eurocodes not implemented — see the Standards tab), no connection or foundation design, no second-order effects. Nothing here makes a structure safe to build.</p>`;
  $('report-body').innerHTML = html;
}
function downloadCSV() {
  if (!S.results || !S.results.elements) { status('Run an analysis first — there are no member results to download.'); return; }
  const rows = [['member', 'max_axial_N', 'max_shear_N', 'max_moment_Nm', 'max_stress_Pa', 'utilization', 'buckling_utilization', 'critical_load_N'].join(',')];
  for (const e of S.results.elements) {
    const ax = elMaxAbs(e, 'axial_N'), sh = elMaxAbs(e, 'shear_y_N');
    const mom = Math.max(elMaxAbs(e, 'moment_z_Nm') || 0, elMaxAbs(e, 'moment_y_Nm') || 0);
    rows.push([e.id, ax, sh, mom, e.max_stress_Pa, e.utilization,
      e.buckling ? e.buckling.utilization : '', e.buckling ? e.buckling.critical_load_N : ''].join(','));
  }
  const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'structural-member-results.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------- init ----------------
async function init() {
  initViewport();
  wireEditor();
  await loadMaterials();
  await loadProjects();
  loadGuest();
  if (!S.projectId) renderAll();
  $('demo-select').addEventListener('change', (ev) => { if (ev.target.value) loadDemo(ev.target.value); });
  $('view-colour').addEventListener('change', rebuildScene);
  $('view-deformed').addEventListener('change', rebuildScene);
  $('view-exagg').addEventListener('change', rebuildScene);
  $('view-loads').addEventListener('change', rebuildScene);
  $('btn-fit-view').addEventListener('click', fitView);
  $('btn-run-analysis').addEventListener('click', runAnalysis);
  $('btn-animate-mode').addEventListener('click', () => {
    if (S.animating) { S.animating = null; rebuildScene(); $('btn-animate-mode').textContent = 'Play / stop'; return; }
    if (!S.results || !S.results.modes) return;
    const idx = parseInt($('modal-select').value, 10) || 0;
    const span = Math.max(...S.structure.nodes.map((n) => Math.abs(n.x_m)).concat([1]), ...S.structure.nodes.map((n) => Math.abs(n.y_m)).concat([1]));
    S.animating = { modeIndex: idx, amplitude: span * 0.05 };
    $('btn-animate-mode').textContent = 'Stop';
  });
  $('calc-select').addEventListener('change', renderCalcForm);
  $('btn-run-calc').addEventListener('click', runCalc);
  $('btn-assistant-review').addEventListener('click', assistantReview);
  $('btn-build-report').addEventListener('click', buildReport);
  $('btn-download-csv').addEventListener('click', downloadCSV);
  $('btn-print-report').addEventListener('click', () => { buildReport(); window.print(); });
  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-view-job]');
    if (b) viewJob(b.dataset.viewJob);
  });
  renderCalcForm();
  loadJobs();
}
init();
