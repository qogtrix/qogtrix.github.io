/* Headless kernel test — Stage 7 mechanical components.
   Runs the REAL model-kernel.js in Node (same /tmp setup as the
   Stage 5 kernel test — see backend/test_stage5_kernel.mjs header):
     mkdir /tmp/kernel-test && cd /tmp/kernel-test
     npm install three@0.160.0 three-bvh-csg@0.0.16 three-mesh-bvh@0.7.0
     cp <repo>/backend/test_stage5_kernel_lib.mjs model-kernel.test.mjs
     cp <repo>/backend/test_stage7_kernel.mjs test-kernel7.mjs
     sed -i "s|from 'three'|from './node_modules/three/build/three.module.js'|; s|from 'three/addons/|from './node_modules/three/examples/jsm/|g; s|await import('three-bvh-csg')|await import('./node_modules/three-bvh-csg/build/index.module.js')|" model-kernel.test.mjs
     node test-kernel7.mjs
   Verifies each new mechanical component builds real geometry with a
   positive mesh volume, and the four Stage 7 demo models evaluate
   with no errors. */
import { evaluateModel, meshVolume, KERNEL_INFO } from './model-kernel.test.mjs';
import fs from 'fs';

let passed = 0, total = 0;
function check(name, ok, detail) {
  total++;
  if (ok) { passed++; console.log('PASS  ' + name); }
  else console.log('FAIL  ' + name + (detail ? ' — ' + detail : ''));
}
function comp(id, kind, params, extra = {}) {
  return { id, name: kind, type: 'component', kind, params, position: [0, 0, 0], rotation: [0, 0, 0], material_id: null, visible: true, parent_id: null, tolerance_mm: 0.1, ...extra };
}
async function volOf(model) {
  const { objects, errors } = await evaluateModel(model);
  if (errors.length) throw new Error(errors.join('; '));
  let t = 0;
  for (const o of objects.values()) if (o.visible !== false) t += await meshVolume(o);
  return t;
}
const approx = (a, b, pct) => Math.abs(a - b) / b < pct;

console.log('kernel:', KERNEL_INFO.name);

const KINDS = {
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
for (const [kind, params] of Object.entries(KINDS)) {
  try {
    const v = await volOf({ version: 1, units: 'mm', components: [comp('c1', kind, params)] });
    check(kind + ' builds with positive mesh volume', v > 0, 'volume=' + v.toFixed(1));
  } catch (e) {
    check(kind + ' builds with positive mesh volume', false, e.message);
  }
}
// Spot-checks against analytic values (exact ones tight, estimates loose).
const fly = await volOf({ version: 1, units: 'mm', components: [comp('c1', 'flywheel', KINDS.flywheel)] });
const flyRef = Math.PI / 4 * (200 * 200 - 30 * 30) * 24 + Math.PI / 4 * 60 * 60 * 16;
check('flywheel mesh volume matches analytic (within 2%)', approx(fly, flyRef, 0.02), 'mesh=' + fly.toFixed(1) + ' analytic=' + flyRef.toFixed(1));
const clu = await volOf({ version: 1, units: 'mm', components: [comp('c1', 'clutch', KINDS.clutch)] });
const cluRef = Math.PI / 4 * (180 * 180 - 30 * 30) * 12;
check('clutch mesh volume matches analytic (within 3%)', approx(clu, cluRef, 0.03), 'mesh=' + clu.toFixed(1) + ' analytic=' + cluRef.toFixed(1));
const hyd = await volOf({ version: 1, units: 'mm', components: [comp('c1', 'hydraulic_cylinder', KINDS.hydraulic_cylinder)] });
const hydRef = Math.PI / 4 * ((50 + 10) ** 2 - 50 * 50) * 160 + Math.PI / 4 * 25 * 25 * 180 + 2 * Math.PI / 4 * 60 * 60 * 6;
check('hydraulic cylinder mesh volume is in range', hyd > hydRef * 0.9 && hyd < hydRef * 1.2, 'mesh=' + hyd.toFixed(1) + ' approx=' + hydRef.toFixed(1));

// Demo models evaluate with no errors and positive total volume.
for (const name of ['gear_transmission', 'crank_slider', 'rotating_shaft', 'hydraulic_lift']) {
  try {
    const d = JSON.parse(fs.readFileSync('/home/hatch/workspace/ai-engineering-lab/workspace/test-models/mechanical/' + name + '.json', 'utf8'));
    const { errors } = await evaluateModel(d);
    check('demo model ' + name + ' evaluates with no errors', errors.length === 0, errors.join('; '));
    const v = await volOf(d);
    check('demo model ' + name + ' has positive mesh volume', v > 0, 'volume=' + v.toFixed(1));
  } catch (e) {
    check('demo model ' + name + ' evaluates', false, e.message);
  }
}

console.log('\n' + passed + '/' + total + ' tests passed');
process.exit(passed === total ? 0 : 1);
