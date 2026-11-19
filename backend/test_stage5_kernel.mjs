/* Headless kernel test — runs the REAL model-kernel.js in Node.
   The kernel uses browser import specifiers ('three', 'three/addons/'),
   so to run it:  mkdir /tmp/kernel-test && cd /tmp/kernel-test
     npm install three@0.160.0 three-bvh-csg@0.0.16 three-mesh-bvh@0.7.0
     cp <repo>/backend/test_stage5_kernel_lib.mjs model-kernel.test.mjs
     cp <repo>/backend/test_stage5_kernel.mjs test-kernel.mjs
   then rewrite the lib's imports to node_modules paths:
     sed -i "s|from 'three'|from './node_modules/three/build/three.module.js'|; s|from 'three/addons/|from './node_modules/three/examples/jsm/|g; s|await import('three-bvh-csg')|await import('./node_modules/three-bvh-csg/build/index.module.js')|" model-kernel.test.mjs
   and run:  node test-kernel.mjs
   (GLB export is skipped in Node — it needs the browser's FileReader;
   it is verified in the hosted app instead.)
*/
/* Headless kernel test — runs the REAL model-kernel.js (with import
   specifiers rewritten to /tmp/kernel-test/node_modules) in Node.
   Verifies geometry is actually built, booleans actually cut, and
   mesh volumes match analytic values. */
import { evaluateModel, meshVolume, exportModel, KERNEL_INFO } from './test_stage5_kernel_lib.mjs';
import fs from 'fs';

let passed = 0, total = 0;
function check(name, ok, detail) {
  total++;
  if (ok) { passed++; console.log('PASS  ' + name); }
  else console.log('FAIL  ' + name + (detail ? ' — ' + detail : ''));
}
function comp(id, type, kind, params, extra = {}) {
  return { id, name: kind, type, kind, params, position: [0, 0, 0], rotation: [0, 0, 0], material_id: null, visible: true, parent_id: null, tolerance_mm: 0.1, ...extra };
}
async function volOf(model) {
  const { objects, errors } = await evaluateModel(model);
  if (errors.length) throw new Error(errors.join('; '));
  let total = 0;
  // Boolean operands are hidden by evaluateModel — only visible
  // objects are real solids in the model.
  for (const o of objects.values()) if (o.visible !== false) total += await meshVolume(o);
  return { total, objects, errors };
}
const approx = (a, b, pct) => Math.abs(a - b) / b < pct;

console.log('kernel:', KERNEL_INFO.name);

// 1. Box mesh volume is exact.
let r = await volOf({ version: 1, units: 'mm', components: [comp('b1', 'primitive', 'box', { length: 10, width: 20, height: 30 })] });
check('box mesh volume = 6000 mm3', approx(r.total, 6000, 0.001), 'got ' + r.total);

// 2. Cylinder mesh volume close to analytic (48 segments).
r = await volOf({ version: 1, units: 'mm', components: [comp('c1', 'primitive', 'cylinder', { radius: 5, height: 20 })] });
check('cylinder mesh volume ~ 500pi', approx(r.total, 500 * Math.PI, 0.005), 'got ' + r.total);

// 3. Sphere mesh volume close to analytic.
r = await volOf({ version: 1, units: 'mm', components: [comp('s1', 'primitive', 'sphere', { radius: 10 })] });
check('sphere mesh volume ~ 4000pi/3', approx(r.total, 4000 * Math.PI / 3, 0.01), 'got ' + r.total);

// 4. Boolean subtract REALLY cuts: box 50x30x20 minus a cylinder through it.
// The cylinder tool's axis is Y, so it cuts through the 20 mm height:
// removed volume = pi * r^2 * 20.
const boxVol = 50 * 30 * 20; // 30000
const cutVol = Math.PI * 25 * 20; // cylinder r5, 20mm inside the box
r = await volOf({ version: 1, units: 'mm', components: [
  comp('blk', 'primitive', 'box', { length: 50, width: 30, height: 20 }),
  comp('tool', 'primitive', 'cylinder', { radius: 5, height: 200 }),
  comp('cut', 'boolean', 'boolean', { op: 'subtract', operands: ['blk', 'tool'] }),
] });
check('boolean subtract removes the cylinder volume', approx(r.total, boxVol - cutVol, 0.01), 'got ' + r.total + ' expected ~' + (boxVol - cutVol));

// 5. Boolean union of two overlapping boxes.
r = await volOf({ version: 1, units: 'mm', components: [
  comp('a', 'primitive', 'box', { length: 20, width: 20, height: 20 }),
  comp('b', 'primitive', 'box', { length: 20, width: 20, height: 20 }, { position: [10, 0, 0] }),
  comp('u', 'boolean', 'boolean', { op: 'union', operands: ['a', 'b'] }),
] });
check('boolean union = 8000 + 8000 - overlap 4000', approx(r.total, 12000, 0.01), 'got ' + r.total);

// 6. Boolean intersect.
r = await volOf({ version: 1, units: 'mm', components: [
  comp('a', 'primitive', 'box', { length: 20, width: 20, height: 20 }),
  comp('b', 'primitive', 'box', { length: 20, width: 20, height: 20 }, { position: [10, 0, 0] }),
  comp('i', 'boolean', 'boolean', { op: 'intersect', operands: ['a', 'b'] }),
] });
check('boolean intersect = overlap 4000', approx(r.total, 4000, 0.01), 'got ' + r.total);

// 7. Gear: volume between root cylinder and outer cylinder.
const gearOuter = Math.PI * Math.pow(2 * 24 / 2 + 2, 2) * 12;
const gearRoot = Math.PI * Math.pow(2 * 24 / 2 - 2.5, 2) * 12;
r = await volOf({ version: 1, units: 'mm', components: [comp('g', 'component', 'gear', { module: 2, teeth: 24, thickness: 12, bore_diameter: 10 })] });
check('gear mesh volume between root and outer cylinder', r.total > gearRoot * 0.8 && r.total < gearOuter, 'got ' + r.total);

// 8. I-beam mesh volume matches analytic 9,240,000 within 1%.
r = await volOf({ version: 1, units: 'mm', components: [comp('bm', 'component', 'beam', { length: 3000, height: 200, flange_width: 100, flange_thickness: 10, web_thickness: 6 })] });
check('I-beam mesh volume ~ 9.24e6', approx(r.total, 9240000, 0.01), 'got ' + r.total);

// 9. Every library component builds with positive volume.
const libCases = [
  ['shaft', { diameters: [20, 30, 20], lengths: [40, 60, 40] }],
  ['bearing', { bore_diameter: 20, outer_diameter: 47, width: 14 }],
  ['bolt', { diameter: 8, length: 20, head_height: 5 }],
  ['nut', { diameter: 10, height: 8 }],
  ['spring', { coil_diameter: 30, wire_diameter: 3, coils: 6, length: 50 }],
  ['piston', { diameter: 50, height: 40, ring_grooves: 2 }],
  ['pipe', { outer_diameter: 20, inner_diameter: 16, length: 100 }],
  ['motor', { diameter: 60, length: 90, shaft_diameter: 12, shaft_length: 30 }],
  ['enclosure', { length: 120, width: 80, height: 60, wall_thickness: 4 }],
];
for (const [kind, params] of libCases) {
  const rr = await volOf({ version: 1, units: 'mm', components: [comp('x', 'component', kind, params)] });
  check('component ' + kind + ' builds, volume > 0', rr.total > 0, 'got ' + rr.total);
}

// 10. Rounded + chamfered boxes build; volumes slightly below the plain box.
r = await volOf({ version: 1, units: 'mm', components: [comp('rb', 'primitive', 'rounded_box', { length: 50, width: 30, height: 20, radius: 5 })] });
check('rounded box volume < plain box, > 90%', r.total < 30000 && r.total > 27000, 'got ' + r.total);
r = await volOf({ version: 1, units: 'mm', components: [comp('cb', 'primitive', 'chamfered_box', { length: 50, width: 30, height: 20, chamfer: 5 })] });
check('chamfered box volume = (50*30 - 2*25) * 20 = 29000', approx(r.total, 29000, 0.01), 'got ' + r.total);

// 11. Extrude + revolve.
r = await volOf({ version: 1, units: 'mm', components: [comp('e', 'primitive', 'extrude', { profile: [[-20, -15], [20, -15], [20, 15], [-20, 15]], depth: 10 })] });
check('extrude 40x30x10 = 12000', approx(r.total, 12000, 0.001), 'got ' + r.total);
r = await volOf({ version: 1, units: 'mm', components: [comp('rv', 'primitive', 'revolve', { profile: [[0, -10], [20, -10], [20, 10], [0, 10]], angle: 360 })] });
check('revolve profile = cylinder r20 h20 ~ 25133', approx(r.total, Math.PI * 400 * 20, 0.01), 'got ' + r.total);

// 12. The 5 test models evaluate with no errors and positive volumes.
for (const name of ['shaft', 'gear', 'gearbox', 'beam', 'multi-component']) {
  const m = JSON.parse(fs.readFileSync('../workspace/test-models/' + name + '.json', 'utf8'));
  const { objects, errors } = await evaluateModel(m);
  let v = 0;
  for (const o of objects.values()) v += await meshVolume(o);
  check('test model ' + name + ' evaluates, volume > 0', errors.length === 0 && v > 0, 'errors=' + errors.join(';') + ' vol=' + Math.round(v));
}

// 13. STL export produces bytes; OBJ export produces text.
{
  const { objects } = await evaluateModel({ version: 1, units: 'mm', components: [comp('b1', 'primitive', 'box', { length: 10, width: 20, height: 30 })] });
  const { Group } = await import('./node_modules/three/build/three.module.js');
  const g = new Group();
  objects.forEach((o) => g.add(o));
  const stl = await exportModel(g, 'stl');
  check('STL export returns a blob', stl.blob.size > 100, 'size=' + stl.blob.size);
  const obj = await exportModel(g, 'obj');
  const text = await obj.blob.text();
  check('OBJ export returns text with vertices', text.includes('v ') && text.includes('f '), '');
  try {
    const glb = await exportModel(g, 'glb');
    check('GLB export returns a blob', glb.blob.size > 100, 'size=' + glb.blob.size);
  } catch (e) {
    // GLTFExporter needs FileReader, which exists in browsers but
    // not in Node — this path is verified in the hosted app instead.
    console.log('SKIP  GLB export in Node (needs browser FileReader): ' + e.message);
  }
}

console.log('\n' + passed + '/' + total + ' kernel tests passed');
process.exit(passed === total ? 0 : 1);
