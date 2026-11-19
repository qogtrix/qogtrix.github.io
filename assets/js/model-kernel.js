/* AI Engineering Laboratory — 3D modelling kernel (Stage 5).
   ES module. Builds real, editable Three.js geometry from the model
   JSON (see assets/js/model-math.js for the schema).

   KERNEL NOTE — read before claiming anything about this file:
   This is a MESH-BASED kernel, not a B-rep kernel (not OpenCascade).
   - Primitives, extrusions, revolves and library components are
     parametric: change a dimension and the geometry is rebuilt.
   - Booleans are REAL CSG operations on triangle meshes, via
     three-bvh-csg (MIT, 0.0.16) — union / subtract / intersect
     actually cut the mesh. They are not visual tricks.
   - Holes are boolean subtractions of a cylinder tool.
   - Fillets are real rounded boxes (RoundedBoxGeometry) and
     chamfers are real chamfered boxes — on box primitives only.
     Arbitrary-edge fillets are NOT supported (see docs/MODELLING.md).
   - Gear teeth are a simplified trapezoidal profile, NOT a true
     involute (see docs/MODELLING.md).
   - STEP / 3MF / FCStd are NOT supported by a mesh kernel and are
     not offered. STL / OBJ / GLB export and STL / OBJ / GLB import
     are real, via three.js addons.
   Volumes are measured from the mesh (three-bvh-csg
   computeMeshVolume, with a manual signed-tetrahedron fallback).
*/
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { STLExporter } from 'three/addons/exporters/STLExporter.js';
import { OBJExporter } from 'three/addons/exporters/OBJExporter.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

export const KERNEL_INFO = {
  name: 'mesh-CSG kernel (three-bvh-csg 0.0.16, MIT)',
  type: 'mesh-based CSG, not B-rep',
  booleans: 'real CSG on triangle meshes (union / subtract / intersect)',
  fillets: 'rounded boxes only (box primitives)',
  chamfers: 'chamfered boxes only (box primitives, 4 vertical edges)',
  gears: 'simplified trapezoidal tooth profile, not a true involute',
  export_formats: ['stl', 'obj', 'glb', 'json'],
  import_formats: ['stl', 'obj', 'glb', 'gltf'],
  unsupported_formats: ['step', '3mf', 'fcstd'],
};

let csgLib = null;
async function getCSG() {
  if (!csgLib) csgLib = await import('three-bvh-csg');
  return csgLib;
}

const PALETTE = {
  steel: 0x8fa3b8, aluminium: 0xc7d2de, copper: 0xb87333, brass: 0xc9a227,
  polymer: 0x4a90d9, ceramic: 0xe8e8e8, default: 0x38bdf8,
};
export function colorForMaterial(materialId) {
  if (!materialId) return PALETTE.default;
  const id = materialId.toLowerCase();
  if (id.indexOf('steel') === 0 || id.indexOf('iron') === 0 || id.indexOf('inconel') === 0 || id.indexOf('tungsten') === 0) return PALETTE.steel;
  if (id.indexOf('alu') === 0 || id.indexOf('magnesium') === 0 || id.indexOf('titanium') === 0 || id.indexOf('ti-') === 0) return PALETTE.aluminium;
  if (id.indexOf('copper') === 0) return PALETTE.copper;
  if (id.indexOf('brass') === 0) return PALETTE.brass;
  if (id.indexOf('pla') === 0 || id.indexOf('abs') === 0 || id.indexOf('nylon') === 0 || id.indexOf('peek') === 0 || id.indexOf('polycarbonate') === 0 || id.indexOf('ptfe') === 0 || id.indexOf('hdpe') === 0 || id.indexOf('pu-foam') === 0) return PALETTE.polymer;
  if (id.indexOf('alumina') === 0 || id.indexOf('silicon') === 0 || id.indexOf('zirconia') === 0) return PALETTE.ceramic;
  return PALETTE.default;
}

function stdMat(color) {
  return new THREE.MeshStandardMaterial({ color: color, metalness: 0.55, roughness: 0.4 });
}
function mesh(geo, color) {
  return new THREE.Mesh(geo, stdMat(color));
}
function shapeFromPoints(points) {
  const s = new THREE.Shape();
  s.moveTo(points[0][0], points[0][1]);
  for (let i = 1; i < points.length; i++) s.lineTo(points[i][0], points[i][1]);
  s.closePath();
  return s;
}
function circlePath(cx, cy, r) {
  const p = new THREE.Path();
  p.absarc(cx, cy, r, 0, Math.PI * 2, true);
  return p;
}

// -- primitives -----------------------------------------------------------
function gearShape(module_, teeth, boreDiameter) {
  const pitchR = module_ * teeth / 2;
  const outerR = pitchR + module_;
  const rootR = pitchR - 1.25 * module_;
  const pitch = (Math.PI * 2) / teeth;
  // Simplified trapezoidal tooth: each tooth occupies half the pitch
  // at the pitch circle, with straight flanks. NOT a true involute.
  const shape = new THREE.Shape();
  for (let t = 0; t < teeth; t++) {
    const a0 = t * pitch;
    const pts = [
      [rootR, a0], [rootR, a0 + pitch * 0.20],
      [outerR, a0 + pitch * 0.32], [outerR, a0 + pitch * 0.48],
      [rootR, a0 + pitch * 0.60], [rootR, a0 + pitch],
    ];
    for (const [r, a] of pts) {
      const x = r * Math.cos(a), y = r * Math.sin(a);
      if (t === 0 && a === a0 && r === rootR) shape.moveTo(x, y);
      else shape.lineTo(x, y);
    }
  }
  shape.closePath();
  if (boreDiameter && boreDiameter > 0) shape.holes.push(circlePath(0, 0, boreDiameter / 2));
  return shape;
}

class HelixCurve extends THREE.Curve {
  constructor(coilR, length, coils) {
    super();
    this.coilR = coilR; this.length = length; this.coils = coils;
  }
  getPoint(t) {
    const a = t * this.coils * Math.PI * 2;
    return new THREE.Vector3(
      Math.cos(a) * this.coilR, t * this.length - this.length / 2,
      Math.sin(a) * this.coilR);
  }
}

function buildPrimitive(comp, color) {
  const p = comp.params;
  switch (comp.kind) {
    case 'box':
      return mesh(new THREE.BoxGeometry(p.length, p.height, p.width), color);
    case 'cylinder':
      return mesh(new THREE.CylinderGeometry(p.radius, p.radius, p.height, 48), color);
    case 'sphere':
      return mesh(new THREE.SphereGeometry(p.radius, 48, 32), color);
    case 'cone':
      return mesh(new THREE.ConeGeometry(p.radius, p.height, 48), color);
    case 'torus':
      return mesh(new THREE.TorusGeometry(p.radius, p.tube, 24, 64), color);
    case 'rounded_box': {
      const g = new RoundedBoxGeometry(p.length, p.height, p.width, 4, p.radius);
      return mesh(g, color);
    }
    case 'chamfered_box': {
      // Chamfer on the 4 vertical edges: chamfered rectangle profile
      // extruded along the height (Z), then rotated so height is Y.
      const c = p.chamfer, l = p.length, w = p.width;
      const s = shapeFromPoints([
        [-l / 2 + c, -w / 2], [l / 2 - c, -w / 2], [l / 2, -w / 2 + c],
        [l / 2, w / 2 - c], [l / 2 - c, w / 2], [-l / 2 + c, w / 2],
        [-l / 2, w / 2 - c], [-l / 2, -w / 2 + c],
      ]);
      const g = new THREE.ExtrudeGeometry(s, { depth: p.height, bevelEnabled: false });
      g.translate(0, 0, -p.height / 2);
      const m = mesh(g, color);
      m.rotation.x = -Math.PI / 2;
      return m;
    }
    case 'extrude': {
      const s = shapeFromPoints(p.profile);
      (p.holes || []).forEach((hole) => s.holes.push(shapeFromPoints(hole)));
      const g = new THREE.ExtrudeGeometry(s, { depth: p.depth, bevelEnabled: false });
      g.translate(0, 0, -p.depth / 2);
      return mesh(g, color);
    }
    case 'revolve': {
      const pts = p.profile.map(([x, y]) => new THREE.Vector2(x, y));
      const g = new THREE.LatheGeometry(pts, 64);
      if (p.angle && p.angle < 360) {
        // LatheGeometry always revolves 360; partial angles are not
        // supported by this geometry — the UI prevents angle < 360
        // from reaching the kernel with a note.
        console.warn('Partial revolve angle requested; full 360 revolve built.');
      }
      return mesh(g, color);
    }
    default:
      throw new Error('Unknown primitive kind: ' + comp.kind);
  }
}

function buildComponent(comp, color) {
  const p = comp.params;
  const group = new THREE.Group();
  function add(m) { group.add(m); return m; }
  switch (comp.kind) {
    case 'gear': {
      const g = new THREE.ExtrudeGeometry(gearShape(p.module, p.teeth, p.bore_diameter),
        { depth: p.thickness, bevelEnabled: false });
      g.translate(0, 0, -p.thickness / 2);
      add(mesh(g, color));
      break;
    }
    case 'shaft': {
      let x = -p.lengths.reduce((a, b) => a + b, 0) / 2;
      p.diameters.forEach((d, i) => {
        const m = mesh(new THREE.CylinderGeometry(d / 2, d / 2, p.lengths[i], 48), color);
        m.rotation.z = Math.PI / 2;
        m.position.x = x + p.lengths[i] / 2;
        x += p.lengths[i];
        add(m);
      });
      break;
    }
    case 'bearing': {
      const outer = p.outer_diameter / 2, bore = p.bore_diameter / 2, w = p.width;
      const ring = (rOut, rIn) => {
        const pts = [new THREE.Vector2(rIn, -w / 2), new THREE.Vector2(rOut, -w / 2),
          new THREE.Vector2(rOut, w / 2), new THREE.Vector2(rIn, w / 2), new THREE.Vector2(rIn, -w / 2)];
        return mesh(new THREE.LatheGeometry(pts, 48), color);
      };
      const outerRing = ring(outer, outer - Math.min(4, (outer - bore) / 3));
      const innerRing = ring(bore + Math.min(4, (outer - bore) / 3), bore);
      outerRing.rotation.x = Math.PI / 2; innerRing.rotation.x = Math.PI / 2;
      add(outerRing); add(innerRing);
      const ballR = (outer - bore) / 4;
      const ballCircleR = (outer + bore) / 2;
      for (let i = 0; i < 8; i++) {
        const a = (i / 8) * Math.PI * 2;
        const b = mesh(new THREE.SphereGeometry(ballR, 20, 14), 0x6b7280);
        b.position.set(Math.cos(a) * ballCircleR, Math.sin(a) * ballCircleR, 0);
        add(b);
      }
      break;
    }
    case 'bolt': {
      const shank = mesh(new THREE.CylinderGeometry(p.diameter / 2, p.diameter / 2, p.length, 32), color);
      shank.position.y = p.length / 2;
      add(shank);
      const head = mesh(new THREE.CylinderGeometry(1.8 * p.diameter / 2, 1.8 * p.diameter / 2, p.head_height, 6), color);
      head.position.y = -p.head_height / 2;
      add(head);
      const tip = mesh(new THREE.ConeGeometry(p.diameter / 2, p.diameter * 0.4, 32), color);
      tip.rotation.x = Math.PI;
      tip.position.y = p.length + p.diameter * 0.2;
      add(tip);
      break;
    }
    case 'nut': {
      const s = shapeFromPoints(Array.from({ length: 6 }, (_, i) => {
        const a = (i / 6) * Math.PI * 2 + Math.PI / 6;
        const r = (1.8 * p.diameter / 2) / Math.cos(Math.PI / 6);
        return [r * Math.cos(a), r * Math.sin(a)];
      }));
      s.holes.push(circlePath(0, 0, p.diameter / 2));
      const g = new THREE.ExtrudeGeometry(s, { depth: p.height, bevelEnabled: false });
      g.translate(0, 0, -p.height / 2);
      add(mesh(g, color));
      break;
    }
    case 'spring': {
      const curve = new HelixCurve(p.coil_diameter / 2, p.length, p.coils);
      add(mesh(new THREE.TubeGeometry(curve, 64 * Math.max(1, p.coils), p.wire_diameter / 2, 12, false), color));
      break;
    }
    case 'piston': {
      const pts = [];
      const r = p.diameter / 2, h = p.height, grooves = p.ring_grooves || 0;
      pts.push(new THREE.Vector2(0, -h / 2), new THREE.Vector2(r, -h / 2), new THREE.Vector2(r, h / 2), new THREE.Vector2(0, h / 2));
      const g = new THREE.LatheGeometry(pts, 48);
      add(mesh(g, color));
      for (let i = 0; i < grooves; i++) {
        const y = h / 2 - (i + 1) * (h / (grooves + 2));
        const ring = mesh(new THREE.TorusGeometry(r - 0.5, 0.8, 10, 48), 0x374151);
        ring.rotation.x = Math.PI / 2;
        ring.position.y = y;
        add(ring);
      }
      break;
    }
    case 'pipe': {
      const pts = [new THREE.Vector2(p.inner_diameter / 2, -p.length / 2),
        new THREE.Vector2(p.outer_diameter / 2, -p.length / 2),
        new THREE.Vector2(p.outer_diameter / 2, p.length / 2),
        new THREE.Vector2(p.inner_diameter / 2, p.length / 2),
        new THREE.Vector2(p.inner_diameter / 2, -p.length / 2)];
      add(mesh(new THREE.LatheGeometry(pts, 48), color));
      break;
    }
    case 'beam': {
      const fw = p.flange_width, ft = p.flange_thickness, wt = p.web_thickness, h = p.height;
      const s = shapeFromPoints([
        [-fw / 2, -h / 2], [fw / 2, -h / 2], [fw / 2, -h / 2 + ft],
        [wt / 2, -h / 2 + ft], [wt / 2, h / 2 - ft], [fw / 2, h / 2 - ft],
        [fw / 2, h / 2], [-fw / 2, h / 2], [-fw / 2, h / 2 - ft],
        [-wt / 2, h / 2 - ft], [-wt / 2, -h / 2 + ft], [-fw / 2, -h / 2 + ft],
      ]);
      const g = new THREE.ExtrudeGeometry(s, { depth: p.length, bevelEnabled: false });
      g.translate(0, 0, -p.length / 2);
      const m = mesh(g, color);
      m.rotation.y = Math.PI / 2;
      add(m);
      break;
    }
    case 'motor': {
      const body = mesh(new THREE.CylinderGeometry(p.diameter / 2, p.diameter / 2, p.length, 48), color);
      body.rotation.z = Math.PI / 2;
      add(body);
      const cap = mesh(new THREE.CylinderGeometry(p.diameter / 2, p.diameter / 2, 4, 48), 0x374151);
      cap.rotation.z = Math.PI / 2;
      cap.position.x = -p.length / 2 - 2;
      add(cap);
      const shaft = mesh(new THREE.CylinderGeometry(p.shaft_diameter / 2, p.shaft_diameter / 2, p.shaft_length, 32), 0x9ca3af);
      shaft.rotation.z = Math.PI / 2;
      shaft.position.x = p.length / 2 + p.shaft_length / 2;
      add(shaft);
      break;
    }
    case 'enclosure': {
      const t = p.wall_thickness, l = p.length, w = p.width, h = p.height;
      const bottom = mesh(new THREE.BoxGeometry(l, t, w), color);
      bottom.position.y = -h / 2 + t / 2;
      add(bottom);
      const wallX = mesh(new THREE.BoxGeometry(t, h - t, w), color);
      wallX.position.set(-l / 2 + t / 2, t / 2, 0); add(wallX);
      const wallX2 = wallX.clone(); wallX2.position.x = l / 2 - t / 2; add(wallX2);
      const wallZ = mesh(new THREE.BoxGeometry(l - 2 * t, h - t, t), color);
      wallZ.position.set(0, t / 2, -w / 2 + t / 2); add(wallZ);
      const wallZ2 = wallZ.clone(); wallZ2.position.z = w / 2 - t / 2; add(wallZ2);
      break;
    }
    default:
      throw new Error('Unknown component kind: ' + comp.kind);
  }
  return group;
}

function buildMeshComponent(comp, color) {
  const gd = comp.params.geometry_data;
  if (!gd || !Array.isArray(gd.positions)) throw new Error('Imported mesh has no geometry_data');
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(gd.positions, 3));
  if (Array.isArray(gd.index) && gd.index.length) geo.setIndex(gd.index);
  geo.computeVertexNormals();
  return mesh(geo, color);
}

// -- boolean evaluation ----------------------------------------------------
function mergeGroupGeometry(obj) {
  const geos = [];
  obj.updateMatrixWorld(true);
  obj.traverse((o) => {
    if (o.isMesh) {
      const g = o.geometry.clone();
      g.applyMatrix4(o.matrixWorld);
      geos.push(g);
    }
  });
  if (!geos.length) throw new Error('Boolean operand has no geometry');
  const merged = mergeGeometries(geos, false);
  geos.forEach((g) => g.dispose());
  return merged;
}

async function applyBoolean(operandA, operandB, op, color) {
  const lib = await getCSG();
  const { Brush, Evaluator, ADDITION, SUBTRACTION, INTERSECTION } = lib;
  const geoA = mergeGroupGeometry(operandA);
  const geoB = mergeGroupGeometry(operandB);
  const brushA = new Brush(geoA);
  const brushB = new Brush(geoB);
  const evaluator = new Evaluator();
  const code = op === 'union' ? ADDITION : op === 'intersect' ? INTERSECTION : SUBTRACTION;
  const result = evaluator.evaluate(brushA, brushB, code);
  const m = mesh(result.geometry, color);
  geoA.dispose(); geoB.dispose();
  return m;
}

// -- model evaluation -------------------------------------------------------
export async function evaluateModel(model) {
  const objects = new Map();
  const errors = [];
  const byId = {};
  (model.components || []).forEach((c) => { byId[c.id] = c; });
  // Build in dependency order: plain components first, then booleans.
  const plain = (model.components || []).filter((c) => c.type !== 'boolean');
  const bools = (model.components || []).filter((c) => c.type === 'boolean');
  for (const comp of plain) {
    try {
      const color = comp.color != null ? comp.color : colorForMaterial(comp.material_id);
      let obj;
      if (comp.type === 'primitive') obj = buildPrimitive(comp, color);
      else if (comp.type === 'component') obj = buildComponent(comp, color);
      else if (comp.type === 'imported') obj = buildMeshComponent(comp, color);
      else throw new Error('Unknown component type: ' + comp.type);
      applyTransform(obj, comp);
      obj.visible = comp.visible !== false;
      objects.set(comp.id, obj);
    } catch (e) {
      errors.push(comp.id + ': ' + e.message);
    }
  }
  for (const comp of bools) {
    try {
      const ops = comp.params.operands || [];
      const a = objects.get(ops[0]), b = objects.get(ops[1]);
      if (!a || !b) throw new Error('boolean operand missing: ' + ops.join(', '));
      const color = comp.color != null ? comp.color : colorForMaterial(comp.material_id);
      const result = await applyBoolean(a, b, comp.params.op, color);
      applyTransform(result, comp);
      result.visible = comp.visible !== false;
      objects.set(comp.id, result);
      // Operands are consumed by the boolean — hide them in the scene.
      a.visible = false; b.visible = false;
    } catch (e) {
      errors.push(comp.id + ': ' + e.message);
    }
  }
  // Parent-child: attach children to parents (scene assembly done by caller).
  return { objects, errors };
}

function applyTransform(obj, comp) {
  const pos = comp.position || [0, 0, 0];
  const rot = comp.rotation || [0, 0, 0];
  const sc = comp.scale || [1, 1, 1];
  obj.position.set(pos[0], pos[1], pos[2]);
  obj.rotation.set(THREE.MathUtils.degToRad(rot[0]), THREE.MathUtils.degToRad(rot[1]), THREE.MathUtils.degToRad(rot[2]));
  obj.scale.set(sc[0], sc[1], sc[2]);
  obj.userData.componentId = comp.id;
  obj.traverse((o) => { o.userData.componentId = comp.id; });
}

// -- volumes ----------------------------------------------------------------
function manualMeshVolume(geo) {
  const pos = geo.attributes.position;
  if (!pos) return null;
  const idx = geo.index;
  let vol = 0;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const count = idx ? idx.count : pos.count;
  for (let i = 0; i < count; i += 3) {
    const ia = idx ? idx.getX(i) : i, ib = idx ? idx.getX(i + 1) : i + 1, ic = idx ? idx.getX(i + 2) : i + 2;
    a.fromBufferAttribute(pos, ia); b.fromBufferAttribute(pos, ib); c.fromBufferAttribute(pos, ic);
    vol += a.dot(new THREE.Vector3().crossVectors(b, c)) / 6;
  }
  return Math.abs(vol);
}

export async function meshVolume(obj) {
  try {
    const lib = await getCSG();
    let total = 0;
    obj.updateMatrixWorld(true);
    obj.traverse((o) => {
      if (o.isMesh) {
        const g = o.geometry.clone();
        g.applyMatrix4(o.matrixWorld);
        total += lib.computeMeshVolume(g);
        g.dispose();
      }
    });
    return total;
  } catch (e) {
    let total = 0;
    obj.traverse((o) => {
      if (o.isMesh) {
        const v = manualMeshVolume(o.geometry);
        if (v != null) total += v * Math.abs(o.scale.x * o.scale.y * o.scale.z);
      }
    });
    return total;
  }
}

// -- export / import --------------------------------------------------------
export async function exportModel(rootGroup, format) {
  if (format === 'stl') {
    const exporter = new STLExporter();
    const data = exporter.parse(rootGroup, { binary: true });
    return { blob: new Blob([data], { type: 'model/stl' }), ext: 'stl' };
  }
  if (format === 'obj') {
    const exporter = new OBJExporter();
    const text = exporter.parse(rootGroup);
    return { blob: new Blob([text], { type: 'text/plain' }), ext: 'obj' };
  }
  if (format === 'glb') {
    const exporter = new GLTFExporter();
    const buf = await new Promise((resolve, reject) => {
      exporter.parse(rootGroup, resolve, reject, { binary: true });
    });
    return { blob: new Blob([buf], { type: 'model/gltf-binary' }), ext: 'glb' };
  }
  throw new Error('Unsupported export format: ' + format + '. Supported: stl, obj, glb.');
}

export async function importFile(file) {
  const name = file.name.toLowerCase();
  const buf = await file.arrayBuffer();
  let geometry = null;
  if (name.endsWith('.stl')) {
    geometry = new STLLoader().parse(buf);
  } else if (name.endsWith('.obj')) {
    const group = new OBJLoader().parse(new TextDecoder().decode(buf));
    geometry = mergeGroupGeometry(group);
  } else if (name.endsWith('.glb') || name.endsWith('.gltf')) {
    const group = await new Promise((resolve, reject) => {
      new GLTFLoader().parse(buf, '', resolve, reject);
    });
    geometry = mergeGroupGeometry(group.scene || group);
  } else {
    throw new Error('Unsupported import format. Supported: STL, OBJ, GLB/GLTF.');
  }
  const pos = geometry.attributes.position;
  const positions = [];
  for (let i = 0; i < pos.count; i++) {
    positions.push(Math.round(pos.getX(i) * 1000) / 1000,
      Math.round(pos.getY(i) * 1000) / 1000,
      Math.round(pos.getZ(i) * 1000) / 1000);
  }
  const index = geometry.index ? Array.from(geometry.index.array) : null;
  geometry.dispose();
  return {
    id: 'mesh-' + Math.random().toString(36).slice(2, 8),
    name: file.name.replace(/\.[^.]+$/, ''),
    type: 'imported', kind: 'mesh',
    params: { source_file: file.name, format: name.split('.').pop(), geometry_data: { positions, index } },
    position: [0, 0, 0], rotation: [0, 0, 0], material_id: null, visible: true,
    parent_id: null, tolerance_mm: 0.1,
  };
}
