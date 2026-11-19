/* Stage 7 maths test — new mechanical component kinds (JS side).
   Node: `cd backend && node test_stage7_math.js`.
   Checks validation, analytic volumes, and JS/Python agreement
   (the Python values are printed by backend/test_stage7.py). */
'use strict';
const fs = require('fs');
require('../assets/js/model-math.js');
const M = global.AIELAB_MODEL_MATH || window.AIELAB_MODEL_MATH;

let passed = 0, failed = 0;
function check(name, ok, detail) {
  if (ok) passed++; else failed++;
  console.log((ok ? 'PASS' : 'FAIL') + '  ' + name + (detail ? ' — ' + detail : ''));
}
function comp(kind, params) {
  return { id: 't1', name: 'T', type: 'component', kind, params,
           position: [0, 0, 0], rotation: [0, 0, 0], material_id: null,
           visible: true, parent_id: null, tolerance_mm: 0.1 };
}
function valid(components) {
  return M.validateModel({ version: 1, units: 'mm', components });
}

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
  const errs = valid([comp(kind, params)]);
  check(kind + ' validates', errs.length === 0, errs.join('; '));
  const v = M.analyticVolume(comp(kind, params));
  check(kind + ' has a positive analytic volume', v.value != null && v.value > 0, String(v.value));
}
check('hydraulic cylinder with rod >= bore is rejected',
  valid([comp('hydraulic_cylinder', { bore_diameter: 25, rod_diameter: 25, stroke: 100, barrel_length: 160 })]).length > 0);
check('sprocket with 3 teeth is rejected',
  valid([comp('sprocket', { teeth: 3, pitch: 12.7, thickness: 8 })]).length > 0);
check('crankshaft with 1 journal is rejected',
  valid([comp('crankshaft', { main_diameter: 30, crank_diameter: 24, throw: 25, length: 160, journals: 1 })]).length > 0);

// Spot values (must match backend/model.py exactly):
const fly = M.analyticVolume(comp('flywheel', KINDS.flywheel)).value;
const flyRef = Math.PI / 4 * (200 * 200 - 30 * 30) * 24 + Math.PI / 4 * 60 * 60 * 16;
check('flywheel volume matches the closed form', Math.abs(fly - flyRef) < 1, String(fly));
const spr = M.analyticVolume(comp('sprocket', KINDS.sprocket)).value;
const pd = 12.7 / Math.sin(Math.PI / 18), outer = pd + 12.7 * 0.6;
const sprRef = Math.PI / 4 * (outer * outer - 25 * 25) * 8 * 0.85;
check('sprocket volume matches the closed form', Math.abs(spr - sprRef) < 1, String(spr));
const hyd = M.analyticVolume(comp('hydraulic_cylinder', KINDS.hydraulic_cylinder)).value;
const hydRef = Math.PI / 4 * ((50 + 10) ** 2 - 50 * 50) * 160 + Math.PI / 4 * 25 * 25 * (100 + 80);
check('hydraulic cylinder volume matches the closed form', Math.abs(hyd - hydRef) < 1, String(hyd));

// Demo models validate in JS with positive volumes.
for (const name of ['gear_transmission', 'crank_slider', 'rotating_shaft', 'hydraulic_lift']) {
  const d = JSON.parse(fs.readFileSync('../workspace/test-models/mechanical/' + name + '.json', 'utf8'));
  const errs = M.validateModel(d);
  check('demo model ' + name + ' validates in JS', errs.length === 0, errs.join('; '));
  const vols = d.components.map((c) => M.analyticVolume(c).value);
  check('demo model ' + name + ' has all positive volumes in JS',
    vols.every((v) => v != null && v > 0), JSON.stringify(vols));
}

console.log('\n' + passed + '/' + (passed + failed) + ' tests passed');
process.exit(failed ? 1 : 0);
