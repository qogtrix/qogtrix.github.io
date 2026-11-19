/* AI Engineering Laboratory — 3D modelling workspace (Stage 5).
   ES module. Real parametric modelling on the mesh-CSG kernel
   (assets/js/model-kernel.js): primitives, extrusions, revolves,
   library components, real CSG booleans, holes, assemblies,
   material assignment, save/autosave to the user's project, and
   STL/OBJ/GLB export. All dimensions are stored in mm; the UI
   converts to the selected display unit.
   Honest limits (also in docs/MODELLING.md): mesh kernel, not
   B-rep; fillets/chamfers on boxes only; gear teeth simplified;
   STEP/3MF/FCStd not supported. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { evaluateModel, meshVolume, exportModel, importFile, KERNEL_INFO, colorForMaterial } from './model-kernel.js';

const MATH = window.AIELAB_MODEL_MATH;
const PARAM_SPECS = {
  box: [['length', 'Length'], ['width', 'Width'], ['height', 'Height']],
  cylinder: [['radius', 'Radius'], ['height', 'Height']],
  sphere: [['radius', 'Radius']],
  cone: [['radius', 'Radius'], ['height', 'Height']],
  torus: [['radius', 'Ring radius'], ['tube', 'Tube radius']],
  rounded_box: [['length', 'Length'], ['width', 'Width'], ['height', 'Height'], ['radius', 'Fillet radius']],
  chamfered_box: [['length', 'Length'], ['width', 'Width'], ['height', 'Height'], ['chamfer', 'Chamfer']],
  extrude: [['depth', 'Depth']],
  revolve: [['angle', 'Angle (deg)']],
  gear: [['module', 'Module'], ['teeth', 'Teeth'], ['thickness', 'Thickness'], ['bore_diameter', 'Bore diameter']],
  shaft: [],
  bearing: [['bore_diameter', 'Bore diameter'], ['outer_diameter', 'Outer diameter'], ['width', 'Width']],
  bolt: [['diameter', 'Diameter'], ['length', 'Length'], ['head_height', 'Head height']],
  nut: [['diameter', 'Diameter'], ['height', 'Height']],
  spring: [['coil_diameter', 'Coil diameter'], ['wire_diameter', 'Wire diameter'], ['coils', 'Coils'], ['length', 'Length']],
  piston: [['diameter', 'Diameter'], ['height', 'Height'], ['ring_grooves', 'Ring grooves']],
  pipe: [['outer_diameter', 'Outer diameter'], ['inner_diameter', 'Inner diameter'], ['length', 'Length']],
  beam: [['length', 'Length'], ['height', 'Height'], ['flange_width', 'Flange width'], ['flange_thickness', 'Flange thickness'], ['web_thickness', 'Web thickness']],
  motor: [['diameter', 'Diameter'], ['length', 'Length'], ['shaft_diameter', 'Shaft diameter'], ['shaft_length', 'Shaft length']],
  enclosure: [['length', 'Length'], ['width', 'Width'], ['height', 'Height'], ['wall_thickness', 'Wall thickness']],
  crankshaft: [['main_diameter', 'Main journal diameter'], ['crank_diameter', 'Crank pin diameter'], ['throw', 'Crank throw'], ['length', 'Length'], ['journals', 'Main journals']],
  connecting_rod: [['big_diameter', 'Big-end diameter'], ['small_diameter', 'Small-end diameter'], ['length', 'Centre distance'], ['width', 'Width']],
  flywheel: [['diameter', 'Diameter'], ['thickness', 'Thickness'], ['hub_diameter', 'Hub diameter'], ['bore_diameter', 'Bore diameter']],
  clutch: [['diameter', 'Diameter'], ['thickness', 'Thickness'], ['bore_diameter', 'Bore diameter'], ['plates', 'Plates']],
  brake_disc: [['diameter', 'Diameter'], ['thickness', 'Thickness'], ['bore_diameter', 'Bore diameter'], ['hub_diameter', 'Hub diameter']],
  coupling: [['diameter', 'Diameter'], ['length', 'Length'], ['bore_diameter', 'Bore diameter'], ['bolts', 'Bolts']],
  pulley: [['diameter', 'Diameter'], ['width', 'Width'], ['bore_diameter', 'Bore diameter'], ['groove_depth', 'Groove depth']],
  sprocket: [['teeth', 'Teeth'], ['pitch', 'Chain pitch'], ['thickness', 'Thickness'], ['bore_diameter', 'Bore diameter']],
  hydraulic_cylinder: [['bore_diameter', 'Bore diameter'], ['rod_diameter', 'Rod diameter'], ['stroke', 'Stroke'], ['barrel_length', 'Barrel length']],
  valve: [['body_length', 'Body length'], ['body_width', 'Body width'], ['body_height', 'Body height'], ['bonnet_diameter', 'Bonnet diameter'], ['handwheel_diameter', 'Handwheel diameter']],
  pump: [['housing_diameter', 'Housing diameter'], ['housing_length', 'Housing length'], ['impeller_diameter', 'Impeller diameter'], ['vanes', 'Vanes']],
};
const KIND_LABELS = {
  box: 'Box', cylinder: 'Cylinder', sphere: 'Sphere', cone: 'Cone', torus: 'Torus',
  rounded_box: 'Rounded box (fillet)', chamfered_box: 'Chamfered box', extrude: 'Extrusion',
  revolve: 'Revolve', gear: 'Gear', shaft: 'Shaft', bearing: 'Bearing', bolt: 'Bolt',
  nut: 'Nut', spring: 'Spring', piston: 'Piston', pipe: 'Pipe', beam: 'I-beam',
  motor: 'Motor', enclosure: 'Enclosure', crankshaft: 'Crankshaft', connecting_rod: 'Connecting rod',
  flywheel: 'Flywheel', clutch: 'Clutch', brake_disc: 'Brake disc', coupling: 'Coupling',
  pulley: 'Pulley', sprocket: 'Sprocket', hydraulic_cylinder: 'Hydraulic cylinder',
  valve: 'Valve', pump: 'Pump', boolean: 'Boolean', mesh: 'Imported mesh',
};

let scene, perspCam, orthoCam, camera, renderer, orbit, gizmo, grid, axes;
let model = { version: 0, units: 'mm', components: [] };
let projectId = null, projectName = '', baseVersion = 0, dirty = false, autosave = true;
let displayUnit = 'mm';
let selectedId = null, objects = new Map(), materials = [];
let explodeFactor = 0, sectionOn = false, sectionPlane = null;
let saveTimer = null, rebuildTimer = null;

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const fmt = (mm) => { const v = MATH.fromMM(mm, displayUnit); return (Math.round(v * 100) / 100) + ' ' + displayUnit; };
const uid = (p) => p + '-' + Math.random().toString(36).slice(2, 8);

function status(msg, kind) {
  const s = $('model-status');
  if (s) { s.textContent = msg; s.className = 'model-status' + (kind ? ' ' + kind : ''); }
}
function markDirty() {
  dirty = true;
  status('Unsaved changes', 'warn');
  if (autosave) { clearTimeout(saveTimer); saveTimer = setTimeout(() => saveModel(false), 2000); }
}

// -- scene ------------------------------------------------------------------
function initScene() {
  const container = $('viewer');
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0e13);
  perspCam = new THREE.PerspectiveCamera(45, container.clientWidth / 520, 0.1, 100000);
  perspCam.position.set(300, 220, 380);
  orthoCam = new THREE.OrthographicCamera(-300, 300, 200, -200, 0.1, 100000);
  orthoCam.position.copy(perspCam.position);
  camera = perspCam;
  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(container.clientWidth, 520);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.localClippingEnabled = true;
  container.appendChild(renderer.domElement);
  orbit = new OrbitControls(camera, renderer.domElement);
  orbit.enableDamping = true;
  orbit.target.set(0, 0, 0);
  gizmo = new TransformControls(camera, renderer.domElement);
  gizmo.setSize(0.85);
  gizmo.addEventListener('objectChange', onGizmoChange);
  gizmo.addEventListener('dragging-changed', (e) => { orbit.enabled = !e.value; if (!e.value) markDirty(); });
  scene.add(gizmo);
  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dir = new THREE.DirectionalLight(0xffffff, 1.3);
  dir.position.set(500, 800, 500); scene.add(dir);
  grid = new THREE.GridHelper(1000, 20, 0x38bdf8, 0x223047);
  scene.add(grid);
  axes = new THREE.AxesHelper(150);
  scene.add(axes);
  sectionPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0);
  renderer.domElement.addEventListener('pointerdown', onPointerDown);
  window.addEventListener('resize', () => {
    const w = container.clientWidth;
    perspCam.aspect = w / 520; perspCam.updateProjectionMatrix();
    orthoCam.left = -w / 2; orthoCam.right = w / 2; orthoCam.updateProjectionMatrix();
    renderer.setSize(w, 520);
  });
  (function animate() {
    requestAnimationFrame(animate);
    orbit.update();
    renderer.render(scene, camera);
  })();
}

function setView(name) {
  const d = 420;
  const views = {
    iso: [d, d * 0.7, d], front: [0, 0, d], back: [0, 0, -d],
    top: [0, d, 0], right: [d, 0, 0], left: [-d, 0, 0],
  };
  const v = views[name] || views.iso;
  camera.position.set(v[0], v[1], v[2]);
  orbit.target.set(0, 0, 0);
  orbit.update();
}
function toggleOrtho() {
  const useOrtho = camera === perspCam;
  camera = useOrtho ? orthoCam : perspCam;
  camera.position.copy(useOrtho ? perspCam.position : orthoCam.position);
  orbit.object = camera;
  orbit.update();
  $('toggle-ortho').textContent = useOrtho ? 'View: Orthographic' : 'View: Perspective';
}
function fitView() {
  const box = new THREE.Box3();
  objects.forEach((o) => { if (o.visible) box.expandByObject(o); });
  if (box.isEmpty()) { setView('iso'); return; }
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const dist = Math.max(size.x, size.y, size.z) * 1.6 + 50;
  camera.position.set(center.x + dist * 0.7, center.y + dist * 0.55, center.z + dist * 0.7);
  orbit.target.copy(center);
  orbit.update();
}

// -- model rebuild ------------------------------------------------------------
async function rebuild() {
  clearTimeout(rebuildTimer);
  rebuildTimer = setTimeout(async () => {
    // Remove old objects.
    objects.forEach((o) => { scene.remove(o); });
    objects = new Map();
    const { objects: built, errors } = await evaluateModel(model);
    objects = built;
    // Assembly hierarchy: attach children to parents.
    model.components.forEach((c) => {
      const obj = objects.get(c.id);
      if (!obj) return;
      if (c.parent_id && objects.get(c.parent_id)) objects.get(c.parent_id).add(obj);
      else scene.add(obj);
    });
    applyExplode();
    updateTree();
    updateInspector();
    updateStats();
    if (errors.length) status('Build warnings: ' + errors.join('; '), 'warn');
    else if (!dirty) status('Model ready — ' + model.components.length + ' component(s)');
  }, 60);
}

function applyExplode() {
  if (explodeFactor === 0) return;
  const box = new THREE.Box3();
  objects.forEach((o) => { if (o.visible) box.expandByObject(o); });
  if (box.isEmpty()) return;
  const center = new THREE.Vector3();
  box.getCenter(center);
  model.components.forEach((c) => {
    const obj = objects.get(c.id);
    if (!obj || c.parent_id) return;
    const p = new THREE.Vector3(...(c.position || [0, 0, 0]));
    const dir = p.clone().sub(center);
    if (dir.lengthSq() < 1) dir.set(0, 1, 0);
    dir.normalize();
    obj.position.copy(p).addScaledVector(dir, explodeFactor * 80);
  });
}

// -- selection ------------------------------------------------------------------
function onPointerDown(e) {
  if (e.button !== 0) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const mouse = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width) * 2 - 1,
    -((e.clientY - rect.top) / rect.height) * 2 + 1);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(mouse, camera);
  const hits = ray.intersectObjects([...objects.values()].filter((o) => o.visible), true);
  if (hits.length) {
    let o = hits[0].object;
    while (o && !o.userData.componentId) o = o.parent;
    select(o ? o.userData.componentId : null);
  } else select(null);
}
function highlight() {
  objects.forEach((o, id) => {
    o.traverse((m) => {
      if (m.isMesh) {
        m.material.emissive = m.material.emissive || new THREE.Color(0);
        m.material.emissive.setHex(id === selectedId ? 0x1d4ed8 : 0x000000);
        m.material.emissiveIntensity = id === selectedId ? 0.55 : 0;
      }
    });
  });
}
function select(id) {
  selectedId = id;
  highlight();
  const comp = model.components.find((c) => c.id === id);
  gizmo.detach();
  if (comp) {
    const obj = objects.get(id);
    if (obj && obj.visible) gizmo.attach(obj);
  }
  updateInspector();
  updateTree();
}
function onGizmoChange() {
  const comp = model.components.find((c) => c.id === selectedId);
  const obj = objects.get(selectedId);
  if (!comp || !obj) return;
  // TransformControls edits local transform (parent-relative) — correct.
  comp.position = [Math.round(obj.position.x * 100) / 100, Math.round(obj.position.y * 100) / 100, Math.round(obj.position.z * 100) / 100];
  comp.rotation = [Math.round(THREE.MathUtils.radToDeg(obj.rotation.x) * 100) / 100,
    Math.round(THREE.MathUtils.radToDeg(obj.rotation.y) * 100) / 100,
    Math.round(THREE.MathUtils.radToDeg(obj.rotation.z) * 100) / 100];
  renderTransformFields();
  markDirty();
}

// -- adding components --------------------------------------------------------
function defaultParams(kind) {
  const d = {
    box: { length: 50, width: 30, height: 20 },
    cylinder: { radius: 15, height: 40 },
    sphere: { radius: 20 },
    cone: { radius: 20, height: 40 },
    torus: { radius: 25, tube: 8 },
    rounded_box: { length: 50, width: 30, height: 20, radius: 5 },
    chamfered_box: { length: 50, width: 30, height: 20, chamfer: 5 },
    extrude: { profile: [[-20, -15], [20, -15], [20, 15], [-20, 15]], depth: 10, holes: [] },
    revolve: { profile: [[0, -10], [20, -10], [20, 10], [0, 10]], angle: 360 },
    gear: { module: 2, teeth: 24, thickness: 12, bore_diameter: 10, pressure_angle: 20 },
    shaft: { diameters: [20, 30, 20], lengths: [40, 60, 40] },
    bearing: { bore_diameter: 20, outer_diameter: 47, width: 14 },
    bolt: { diameter: 8, length: 20, head_height: 5 },
    nut: { diameter: 10, height: 8 },
    spring: { coil_diameter: 30, wire_diameter: 3, coils: 6, length: 50 },
    piston: { diameter: 50, height: 40, ring_grooves: 2 },
    pipe: { outer_diameter: 20, inner_diameter: 16, length: 100 },
    beam: { length: 500, height: 100, flange_width: 60, flange_thickness: 8, web_thickness: 5 },
    motor: { diameter: 60, length: 90, shaft_diameter: 12, shaft_length: 30 },
    enclosure: { length: 120, width: 80, height: 60, wall_thickness: 4 },
    crankshaft: { main_diameter: 30, crank_diameter: 24, throw: 25, length: 160, journals: 3 },
    connecting_rod: { big_diameter: 40, small_diameter: 24, length: 120, width: 16 },
    flywheel: { diameter: 200, thickness: 24, hub_diameter: 60, bore_diameter: 30 },
    clutch: { diameter: 180, thickness: 12, bore_diameter: 30, plates: 2 },
    brake_disc: { diameter: 220, thickness: 20, bore_diameter: 60, hub_diameter: 100 },
    coupling: { diameter: 90, length: 60, bore_diameter: 25, bolts: 4 },
    pulley: { diameter: 120, width: 24, bore_diameter: 25, groove_depth: 4 },
    sprocket: { teeth: 18, pitch: 12.7, thickness: 8, bore_diameter: 25 },
    hydraulic_cylinder: { bore_diameter: 50, rod_diameter: 25, stroke: 100, barrel_length: 160 },
    valve: { body_length: 90, body_width: 60, body_height: 50, bonnet_diameter: 30, handwheel_diameter: 80 },
    pump: { housing_diameter: 120, housing_length: 90, impeller_diameter: 90, vanes: 6 },
  };
  return JSON.parse(JSON.stringify(d[kind] || {}));
}
function addComponent(type, kind) {
  const comp = {
    id: uid(kind), name: KIND_LABELS[kind] || kind, type, kind,
    params: defaultParams(kind), position: [0, 0, 0], rotation: [0, 0, 0],
    material_id: null, visible: true, parent_id: null, tolerance_mm: 0.1,
  };
  model.components.push(comp);
  markDirty();
  rebuild().then(() => select(comp.id));
}
function addBoolean(op) {
  const vis = model.components.filter((c) => c.type !== 'boolean' && c.visible);
  if (vis.length < 2) { alert('A boolean needs two components in the model. Add two first.'); return; }
  const a = vis[vis.length - 2], b = vis[vis.length - 1];
  const comp = {
    id: uid('bool'), name: op + ': ' + a.name + ' / ' + b.name, type: 'boolean', kind: 'boolean',
    params: { op, operands: [a.id, b.id] }, position: [0, 0, 0], rotation: [0, 0, 0],
    material_id: a.material_id, visible: true, parent_id: null, tolerance_mm: 0.1,
  };
  model.components.push(comp);
  markDirty();
  rebuild().then(() => select(comp.id));
}
function addHole() {
  const target = model.components.find((c) => c.id === selectedId);
  if (!target) { alert('Select a component first, then add a hole.'); return; }
  const tool = {
    id: uid('hole-tool'), name: 'Hole tool Ø10', type: 'primitive', kind: 'cylinder',
    params: { radius: 5, height: 200 }, position: [0, 0, 0], rotation: [90, 0, 0],
    material_id: null, visible: true, parent_id: null, tolerance_mm: 0.1,
  };
  const cut = {
    id: uid('hole'), name: 'Hole in ' + target.name, type: 'boolean', kind: 'boolean',
    params: { op: 'subtract', operands: [target.id, tool.id] },
    position: [0, 0, 0], rotation: [0, 0, 0],
    material_id: target.material_id, visible: true, parent_id: null, tolerance_mm: 0.1,
  };
  model.components.push(tool, cut);
  markDirty();
  rebuild().then(() => select(cut.id));
}

// -- inspector ------------------------------------------------------------------
function updateInspector() {
  const panel = $('inspector');
  if (!panel) return;
  panel.innerHTML = '';
  const comp = model.components.find((c) => c.id === selectedId);
  if (!comp) {
    panel.appendChild(el('p', 'muted', 'Select a component in the viewport or the assembly tree to edit its dimensions, position, material and visibility.'));
    return;
  }
  panel.appendChild(el('h3', null, comp.name));
  panel.appendChild(el('p', 'small muted', (KIND_LABELS[comp.kind] || comp.kind) + ' · id ' + comp.id));
  const nameRow = el('div', 'field-row');
  nameRow.appendChild(el('label', null, 'Name'));
  const nameIn = el('input'); nameIn.value = comp.name;
  nameIn.addEventListener('change', () => { comp.name = nameIn.value || comp.name; markDirty(); updateTree(); });
  nameRow.appendChild(nameIn);
  panel.appendChild(nameRow);
  // Dimension fields.
  const specs = PARAM_SPECS[comp.kind] || [];
  specs.forEach(([key, label]) => {
    const row = el('div', 'field-row');
    row.appendChild(el('label', null, label + (key === 'teeth' || key === 'coils' || key === 'ring_grooves' || key === 'angle' ? '' : ' (' + displayUnit + ')')));
    const input = el('input');
    input.type = 'number'; input.step = 'any';
    const raw = comp.params[key];
    input.value = (key === 'teeth' || key === 'coils' || key === 'ring_grooves' || key === 'angle') ? raw : Math.round(MATH.fromMM(raw, displayUnit) * 100) / 100;
    input.addEventListener('change', () => {
      const v = parseFloat(input.value);
      if (!isFinite(v)) return;
      comp.params[key] = (key === 'teeth' || key === 'coils' || key === 'ring_grooves' || key === 'angle') ? v : MATH.toMM(v, displayUnit);
      markDirty(); rebuild();
    });
    row.appendChild(input);
    panel.appendChild(row);
  });
  if (comp.kind === 'shaft') {
    [['diameters', 'Step diameters (mm, comma-separated)'], ['lengths', 'Step lengths (mm, comma-separated)']].forEach(([key, label]) => {
      const row = el('div', 'field-row');
      row.appendChild(el('label', null, label));
      const input = el('input');
      input.value = (comp.params[key] || []).join(', ');
      input.addEventListener('change', () => {
        const vals = input.value.split(',').map((s) => parseFloat(s.trim())).filter((v) => isFinite(v));
        if (vals.length) { comp.params[key] = vals; markDirty(); rebuild(); }
      });
      row.appendChild(input);
      panel.appendChild(row);
    });
  }
  if (comp.kind === 'extrude' || comp.kind === 'revolve') {
    const row = el('div', 'field-row');
    row.appendChild(el('label', null, 'Profile points [x, y] mm (JSON)'));
    const ta = el('textarea'); ta.rows = 3; ta.value = JSON.stringify(comp.params.profile);
    ta.addEventListener('change', () => {
      try { const pts = JSON.parse(ta.value); if (Array.isArray(pts) && pts.length >= 2) { comp.params.profile = pts; markDirty(); rebuild(); } }
      catch (e) { alert('Profile must be a JSON array like [[0,0],[20,0],[20,10]]'); }
    });
    row.appendChild(ta);
    panel.appendChild(row);
    if (comp.kind === 'revolve') panel.appendChild(el('p', 'small muted', 'Note: the kernel revolves the full 360°. A partial angle is stored but the mesh is built as a full revolve.'));
  }
  if (comp.kind === 'gear') panel.appendChild(el('p', 'small muted', 'Gear teeth use a simplified trapezoidal profile, not a true involute.'));
  if (comp.type === 'boolean') {
    panel.appendChild(el('p', 'small muted', 'Boolean ' + comp.params.op + ' of ' + (comp.params.operands || []).join(' and ') + '. The operands are hidden in the viewport.'));
  }
  // Transform fields.
  const tf = el('div', 'field-row');
  tf.appendChild(el('label', null, 'Position (' + displayUnit + ')'));
  const posIn = el('input');
  posIn.value = (comp.position || [0, 0, 0]).map((v) => Math.round(MATH.fromMM(v, displayUnit) * 100) / 100).join(', ');
  posIn.addEventListener('change', () => {
    const vals = posIn.value.split(',').map((s) => MATH.toMM(parseFloat(s.trim()), displayUnit));
    if (vals.length === 3 && vals.every((v) => isFinite(v))) { comp.position = vals; markDirty(); rebuild(); }
  });
  tf.appendChild(posIn);
  panel.appendChild(tf);
  const rotRow = el('div', 'field-row');
  rotRow.appendChild(el('label', null, 'Rotation (deg)'));
  const rotIn = el('input');
  rotIn.value = (comp.rotation || [0, 0, 0]).join(', ');
  rotIn.addEventListener('change', () => {
    const vals = rotIn.value.split(',').map((s) => parseFloat(s.trim()));
    if (vals.length === 3 && vals.every((v) => isFinite(v))) { comp.rotation = vals; markDirty(); rebuild(); }
  });
  rotRow.appendChild(rotIn);
  panel.appendChild(rotRow);
  // Material.
  const matRow = el('div', 'field-row');
  matRow.appendChild(el('label', null, 'Material (Stage 4)'));
  const matSel = el('select');
  matSel.appendChild(new Option('— none —', ''));
  materials.forEach((m) => matSel.appendChild(new Option(m.name + ' (' + m.grade + ')', m.id)));
  matSel.value = comp.material_id || '';
  matSel.addEventListener('change', () => { comp.material_id = matSel.value || null; markDirty(); rebuild(); });
  matRow.appendChild(matSel);
  panel.appendChild(matRow);
  // Tolerance + visibility + parent.
  const tolRow = el('div', 'field-row');
  tolRow.appendChild(el('label', null, 'Tolerance (mm)'));
  const tolIn = el('input'); tolIn.type = 'number'; tolIn.step = '0.01'; tolIn.value = comp.tolerance_mm != null ? comp.tolerance_mm : 0.1;
  tolIn.addEventListener('change', () => { const v = parseFloat(tolIn.value); if (isFinite(v) && v >= 0) { comp.tolerance_mm = v; markDirty(); } });
  tolRow.appendChild(tolIn);
  panel.appendChild(tolRow);
  const parRow = el('div', 'field-row');
  parRow.appendChild(el('label', null, 'Parent (assembly)'));
  const parSel = el('select');
  parSel.appendChild(new Option('— top level —', ''));
  model.components.filter((c) => c.id !== comp.id && c.type !== 'boolean').forEach((c) => parSel.appendChild(new Option(c.name, c.id)));
  parSel.value = comp.parent_id || '';
  parSel.addEventListener('change', () => {
    comp.parent_id = parSel.value || null;
    const errs = MATH.validateModel(model, materials.map((m) => m.id));
    if (errs.length) { alert('Cannot set parent: ' + errs.join('; ')); comp.parent_id = null; parSel.value = ''; return; }
    markDirty(); rebuild();
  });
  parRow.appendChild(parSel);
  panel.appendChild(parRow);
  const visRow = el('div', 'field-row');
  const visBtn = el('button', 'secondary', comp.visible === false ? 'Show component' : 'Hide component');
  visBtn.addEventListener('click', () => { comp.visible = comp.visible === false; markDirty(); rebuild(); });
  visRow.appendChild(visBtn);
  const dupBtn = el('button', 'secondary', 'Duplicate');
  dupBtn.addEventListener('click', () => {
    const copy = JSON.parse(JSON.stringify(comp));
    copy.id = uid(comp.kind); copy.name = comp.name + ' (copy)';
    copy.position = [(comp.position || [0, 0, 0])[0] + 20, (comp.position || [0, 0, 0])[1], (comp.position || [0, 0, 0])[2]];
    model.components.push(copy); markDirty(); rebuild().then(() => select(copy.id));
  });
  visRow.appendChild(dupBtn);
  const delBtn = el('button', 'danger', 'Delete');
  delBtn.addEventListener('click', () => {
    if (!confirm('Delete ' + comp.name + '?')) return;
    const refs = model.components.filter((c) => c.parent_id === comp.id || (c.type === 'boolean' && (c.params.operands || []).includes(comp.id)));
    if (refs.length) { alert('Cannot delete: still referenced by ' + refs.map((c) => c.name).join(', ')); return; }
    model.components = model.components.filter((c) => c.id !== comp.id);
    select(null); markDirty(); rebuild();
  });
  visRow.appendChild(delBtn);
  panel.appendChild(visRow);
  // Mass / volume for this component.
  const volEl = el('p', 'small muted', 'Measuring volume…');
  panel.appendChild(volEl);
  const obj = objects.get(comp.id);
  if (obj) {
    meshVolume(obj).then((v) => {
      const mat = materials.find((m) => m.id === comp.material_id);
      const density = mat && mat.properties ? mat.properties.density_kg_m3 : null;
      const mass = v != null && density ? MATH.massKg(v, density) : null;
      volEl.textContent = 'Mesh volume: ' + (v != null ? Math.round(v).toLocaleString() + ' mm³' : '—') +
        (mass != null ? ' · Mass: ' + (Math.round(mass * 1000) / 1000) + ' kg (' + mat.name + ', ' + density + ' kg/m³)' : '');
    });
  }
}
function renderTransformFields() { /* position/rotation are re-rendered on rebuild via inspector refresh */ }

// -- assembly tree ----------------------------------------------------------------
function updateTree() {
  const tree = $('assembly-tree');
  if (!tree) return;
  tree.innerHTML = '';
  const childrenOf = (pid) => model.components.filter((c) => (c.parent_id || null) === pid);
  function addNode(c, depth) {
    const row = el('div', 'tree-row' + (c.id === selectedId ? ' selected' : ''));
    row.style.paddingLeft = (8 + depth * 18) + 'px';
    const eye = el('button', 'tree-eye', c.visible === false ? '👁‍🗨' : '👁');
    eye.title = c.visible === false ? 'Show' : 'Hide';
    eye.addEventListener('click', (e) => { e.stopPropagation(); c.visible = c.visible === false; markDirty(); rebuild(); });
    row.appendChild(eye);
    row.appendChild(el('span', null, (c.visible === false ? '· ' : '') + c.name + ' — ' + (KIND_LABELS[c.kind] || c.kind)));
    row.addEventListener('click', () => select(c.id));
    tree.appendChild(row);
    childrenOf(c.id).forEach((child) => addNode(child, depth + 1));
  }
  childrenOf(null).forEach((c) => addNode(c, 0));
  if (!model.components.length) tree.appendChild(el('p', 'muted', 'No components yet. Add a primitive or a library component.'));
}

// -- stats ----------------------------------------------------------------------
async function updateStats() {
  const elStats = $('viewer-stats');
  if (!elStats) return;
  let tris = 0, verts = 0;
  objects.forEach((o) => {
    o.traverse((m) => {
      if (m.isMesh && m.visible) {
        const p = m.geometry.attributes.position;
        if (p) verts += p.count;
        if (m.geometry.index) tris += m.geometry.index.count / 3; else if (p) tris += p.count / 3;
      }
    });
  });
  const errs = MATH.validateModel(model, materials.map((m) => m.id));
  elStats.textContent = 'Components: ' + model.components.length +
    ' · Triangles: ' + Math.round(tris).toLocaleString() +
    ' · Vertices: ' + Math.round(verts).toLocaleString() +
    ' · Units: ' + displayUnit + ' (stored mm)' +
    (errs.length ? ' · ⚠ ' + errs[0] : ' · Model valid');
}

// -- persistence ------------------------------------------------------------------
function apiBase() { return window.AIELAB_API_BASE || 'http://127.0.0.1:8001'; }
async function api(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const res = await (window.aielabFetchWithWake || fetch)(apiBase() + path, { method, headers, body: body ? JSON.stringify(body) : undefined },
    (attempt) => status('Waking the server… (retry ' + attempt + ')', 'warn'));
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(data.error || ('HTTP ' + res.status)); e.status = res.status; throw e; }
  return data;
}
function authToken() { return (window.AIELAB_AUTH && window.AIELAB_AUTH.token()) || localStorage.getItem('aielab.token') || null; }

async function loadProject(pid) {
  const token = authToken();
  if (!token) { status('Not signed in — modelling in guest mode. Sign in to save to a project.', 'warn'); return false; }
  try {
    const res = await api('GET', '/api/v1/projects/' + pid + '/model', null, token);
    model = res.model && res.model.components ? res.model : { version: 0, units: 'mm', components: [] };
    baseVersion = model.version || 0;
    projectId = pid;
    dirty = false;
    status('Model loaded — version ' + baseVersion);
    rebuild();
    return true;
  } catch (e) {
    status('Could not load model: ' + e.message, 'warn');
    return false;
  }
}
async function saveModel(manual) {
  if (!projectId) {
    if (manual) alert('Sign in and open a project to save. Your model is kept in this browser tab for now.');
    localStorage.setItem('aielab.model.guest', JSON.stringify(model));
    status('Guest mode — model saved in this browser only', 'warn');
    return;
  }
  const token = authToken();
  if (!token) { status('Sign in to save.', 'warn'); return; }
  const errs = MATH.validateModel(model, materials.map((m) => m.id));
  if (errs.length) { status('Cannot save: ' + errs[0], 'warn'); if (manual) alert('Cannot save:\n' + errs.join('\n')); return; }
  try {
    const res = await api('PUT', '/api/v1/projects/' + projectId + '/model',
      { model: { version: model.version, units: model.units, components: model.components }, base_version: baseVersion }, token);
    model = res.model; baseVersion = model.version; dirty = false;
    status('Saved — version ' + baseVersion + ' · ' + new Date().toLocaleTimeString());
    updateStats();
  } catch (e) {
    if (e.status === 409) {
      status('Save conflict: the model changed elsewhere. Reload or overwrite.', 'warn');
      if (confirm('This model was changed elsewhere (newer version on the server).\n\nOK = reload the server version (your changes are lost)\nCancel = overwrite the server version with yours')) {
        await loadProject(projectId);
      } else {
        baseVersion = (await api('GET', '/api/v1/projects/' + projectId + '/model', null, token)).model.version;
        await saveModel(false);
      }
    } else {
      status('Save failed: ' + e.message, 'warn');
      if (manual) alert('Save failed: ' + e.message);
    }
  }
}
async function loadProjectsIntoSelect() {
  const sel = $('project-select');
  if (!sel) return;
  const token = authToken();
  sel.innerHTML = '';
  sel.appendChild(new Option('— guest mode (no project) —', ''));
  if (!token) return;
  try {
    const res = await api('GET', '/api/v1/projects', null, token);
    (res.projects || []).forEach((p) => sel.appendChild(new Option(p.name + (p.visibility === 'public' ? ' (public)' : ''), p.id)));
    // Re-open the project this browser used last, when signed in.
    const last = localStorage.getItem('aielab.last_project');
    if (last && (res.projects || []).some((p) => p.id === last)) sel.value = last;
  } catch (e) { /* backend may not be running; guest mode still works */ }
}
async function loadMaterials() {
  try {
    const res = await fetch(apiBase() + '/api/v1/materials').then((r) => r.json());
    materials = res.materials || [];
  } catch (e) {
    try {
      const data = await fetch('data/materials.json').then((r) => r.json());
      materials = data.materials || [];
    } catch (e2) { materials = []; }
  }
}

// -- export / import ---------------------------------------------------------------
function downloadBlob(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
async function exportModelFile(format) {
  if (!model.components.length) { alert('Nothing to export yet.'); return; }
  if (format === 'json') {
    const blob = new Blob([JSON.stringify(model, null, 2)], { type: 'application/json' });
    downloadBlob(blob, (projectName || 'model') + '-v' + model.version + '.json');
    return;
  }
  if (format === 'step' || format === '3mf' || format === 'fcstd') {
    alert(format.toUpperCase() + ' export is not supported by the mesh kernel. Use STL, OBJ or GLB — or export the model as JSON.');
    return;
  }
  const group = new THREE.Group();
  objects.forEach((o) => { if (o.visible) group.add(o.clone()); });
  try {
    const { blob, ext } = await exportModel(group, format);
    downloadBlob(blob, (projectName || 'model') + '-v' + model.version + '.' + ext);
    status('Exported ' + ext.toUpperCase());
  } catch (e) { alert('Export failed: ' + e.message); }
}
async function importModelFile(file) {
  try {
    const comp = await importFile(file);
    model.components.push(comp);
    markDirty();
    await rebuild();
    select(comp.id);
    status('Imported ' + file.name + ' as ' + comp.name);
  } catch (e) { alert('Import failed: ' + e.message); }
}

// -- init ---------------------------------------------------------------------------
async function init() {
  const container = $('viewer');
  if (!container) return;
  if (typeof THREE === 'undefined' || !window.AIELAB_MODEL_MATH) {
    container.innerHTML = '<div class="viewer-fallback"><b>Three.js could not be loaded.</b><br>Check your internet connection and reload.</div>';
    return;
  }
  try {
    const test = document.createElement('canvas');
    if (!(test.getContext('webgl') || test.getContext('experimental-webgl'))) throw new Error('WebGL unavailable');
  } catch (e) {
    container.innerHTML = '<div class="viewer-fallback"><b>WebGL is not available in this browser.</b><br>Try another browser to use the 3D modeller.</div>';
    return;
  }
  initScene();
  await loadMaterials();
  await loadProjectsIntoSelect();
  // Guest model from a previous tab, if any.
  const guest = localStorage.getItem('aielab.model.guest');
  if (guest) {
    try { const g = JSON.parse(guest); if (g && Array.isArray(g.components) && g.components.length) { model = g; baseVersion = g.version || 0; } } catch (e) { /* ignore */ }
  }
  const params = new URLSearchParams(location.search);
  const pid = params.get('project');
  if (pid) { projectName = params.get('name') || ''; localStorage.setItem('aielab.last_project', pid); await loadProject(pid); const sel = $('project-select'); if (sel) sel.value = pid; }
  else {
    // No ?project= in the URL — re-open the last-used project.
    const sel = $('project-select');
    if (sel && sel.value) await loadProject(sel.value);
  }
  const example = params.get('example');
  if (example && !pid) {
    try {
      const m = await fetch('workspace/test-models/' + example + '.json').then((r) => r.json());
      model = m; baseVersion = m.version || 0; dirty = false;
      status('Example loaded: ' + example + ' — save it to a project to keep it');
    } catch (e) { status('Could not load example ' + example, 'warn'); }
  }
  // Toolbar wiring.
  document.querySelectorAll('[data-add-primitive]').forEach((b) => b.addEventListener('click', () => addComponent('primitive', b.dataset.addPrimitive)));
  document.querySelectorAll('[data-add-component]').forEach((b) => b.addEventListener('click', () => addComponent('component', b.dataset.addComponent)));
  document.querySelectorAll('[data-boolean]').forEach((b) => b.addEventListener('click', () => addBoolean(b.dataset.boolean)));
  const holeBtn = $('add-hole'); if (holeBtn) holeBtn.addEventListener('click', addHole);
  const viewSel = $('view-select'); if (viewSel) viewSel.addEventListener('change', () => setView(viewSel.value));
  const orthoBtn = $('toggle-ortho'); if (orthoBtn) orthoBtn.addEventListener('click', toggleOrtho);
  const fitBtn = $('fit-view'); if (fitBtn) fitBtn.addEventListener('click', fitView);
  const wireBtn = $('toggle-wireframe'); if (wireBtn) wireBtn.addEventListener('click', () => {
    let on = false;
    objects.forEach((o) => o.traverse((m) => { if (m.isMesh) { m.material.wireframe = !m.material.wireframe; on = m.material.wireframe; } }));
    wireBtn.textContent = on ? 'Wireframe: On' : 'Wireframe: Off';
  });
  const gridBtn = $('toggle-grid'); if (gridBtn) gridBtn.addEventListener('click', () => {
    grid.visible = !grid.visible; axes.visible = grid.visible;
    gridBtn.textContent = grid.visible ? 'Grid: On' : 'Grid: Off';
  });
  const gizmoSel = $('gizmo-mode'); if (gizmoSel) gizmoSel.addEventListener('change', () => gizmo.setMode(gizmoSel.value));
  const explode = $('explode-range'); if (explode) explode.addEventListener('input', () => { explodeFactor = parseFloat(explode.value); applyExplode(); });
  const section = $('section-toggle'); if (section) section.addEventListener('click', () => {
    sectionOn = !sectionOn;
    renderer.clippingPlanes = sectionOn ? [sectionPlane] : [];
    section.textContent = sectionOn ? 'Section: On' : 'Section: Off';
    const off = $('section-offset'); if (off) off.disabled = !sectionOn;
  });
  const sectionOff = $('section-offset'); if (sectionOff) sectionOff.addEventListener('input', () => { sectionPlane.constant = parseFloat(sectionOff.value); });
  const unitSel = $('unit-select'); if (unitSel) unitSel.addEventListener('change', () => { displayUnit = unitSel.value; updateStats(); updateInspector(); });
  const saveBtn = $('save-model'); if (saveBtn) saveBtn.addEventListener('click', () => saveModel(true));
  const autoBtn = $('toggle-autosave'); if (autoBtn) autoBtn.addEventListener('click', () => {
    autosave = !autosave; autoBtn.textContent = autosave ? 'Autosave: On' : 'Autosave: Off';
    if (autosave && dirty) saveModel(false);
  });
  const projSel = $('project-select'); if (projSel) projSel.addEventListener('change', async () => {
    if (dirty && !confirm('Switch project? Unsaved changes to the current model will be lost.')) { projSel.value = projectId || ''; return; }
    if (projSel.value) localStorage.setItem('aielab.last_project', projSel.value);
    else localStorage.removeItem('aielab.last_project');
    projectName = projSel.selectedOptions[0] ? projSel.selectedOptions[0].textContent : '';
    if (projSel.value) await loadProject(projSel.value);
    else { projectId = null; model = { version: 0, units: 'mm', components: [] }; baseVersion = 0; rebuild(); status('Guest mode'); }
  });
  document.querySelectorAll('[data-export]').forEach((b) => b.addEventListener('click', () => exportModelFile(b.dataset.export)));
  const importInput = $('import-file');
  if (importInput) importInput.addEventListener('change', () => { if (importInput.files[0]) importModelFile(importInput.files[0]); importInput.value = ''; });
  const exSel = $('example-select'); if (exSel) exSel.addEventListener('change', async () => {
    if (!exSel.value) return;
    if (dirty && !confirm('Load example ' + exSel.value + '? Unsaved changes will be lost.')) { exSel.value = ''; return; }
    try {
      const m = await fetch('workspace/test-models/' + exSel.value + '.json').then((r) => r.json());
      model = m; baseVersion = m.version || 0; projectId = null; dirty = false;
      select(null); rebuild();
      status('Example loaded: ' + exSel.value + ' — open a project and save to keep it');
    } catch (e) { status('Could not load example: ' + e.message, 'warn'); }
    exSel.value = '';
  });
  const shot = $('export-shot'); if (shot) shot.addEventListener('click', () => {
    renderer.render(scene, camera);
    const a = document.createElement('a'); a.href = renderer.domElement.toDataURL('image/png');
    a.download = 'aielab-model.png'; a.click();
  });
  rebuild();
}
document.addEventListener('DOMContentLoaded', init);
