/* Stage 5 — Node test for assets/js/model-math.js (pure JS, no browser).
   Mirrors backend/test_stage5.py's math checks so the JS and Python
   implementations stay in agreement.
   Run:  cd workspace/ai-engineering-lab && node backend/test_stage5_math.js
*/
'use strict';
const M = require('../assets/js/model-math.js');
const assert = require('assert');

let passed = 0, total = 0;
function check(name, ok, detail) {
  total++;
  if (ok) { passed++; console.log('PASS  ' + name); }
  else console.log('FAIL  ' + name + (detail ? ' — ' + detail : ''));
}

check('unit: 1 inch = 25.4 mm', Math.abs(M.convert(1, 'in', 'mm') - 25.4) < 1e-9);
check('unit: 100 mm = 10 cm', Math.abs(M.convert(100, 'mm', 'cm') - 10) < 1e-9);
check('unit: 2 m = 2000 mm', Math.abs(M.convert(2, 'm', 'mm') - 2000) < 1e-9);
check('volume: box 10x20x30 = 6000', M.analyticVolume({ kind: 'box', params: { length: 10, width: 20, height: 30 } }).value === 6000);
check('volume: cylinder r5 h20 = 500pi', Math.abs(M.analyticVolume({ kind: 'cylinder', params: { radius: 5, height: 20 } }).value - 500 * Math.PI) < 0.01);
check('volume: sphere r10 = 4000pi/3', Math.abs(M.analyticVolume({ kind: 'sphere', params: { radius: 10 } }).value - 4000 * Math.PI / 3) < 0.01);
check('volume: extrude 10x10x5 = 500', M.analyticVolume({ kind: 'extrude', params: { profile: [[0, 0], [10, 0], [10, 10], [0, 10]], depth: 5 } }).value === 500);
check('volume: revolve square = 1000pi (Pappus)', Math.abs(M.analyticVolume({ kind: 'revolve', params: { profile: [[0, 0], [10, 0], [10, 10], [0, 10]], angle: 360 } }).value - 1000 * Math.PI) < 0.01);
check('volume: boolean is null (needs mesh)', M.analyticVolume({ kind: 'boolean', params: { op: 'subtract', operands: ['a', 'b'] } }).value === null);
check('volume: pipe D20 d16 L120', Math.abs(M.analyticVolume({ kind: 'pipe', params: { outer_diameter: 20, inner_diameter: 16, length: 120 } }).value - Math.PI / 4 * (400 - 256) * 120) < 0.01);
check('volume: I-beam matches Python (9240000)', Math.abs(M.analyticVolume({ kind: 'beam', params: { length: 3000, height: 200, flange_width: 100, flange_thickness: 10, web_thickness: 6 } }).value - 9240000) < 1);
check('mass: 6000 mm3 steel = 0.0471 kg', Math.abs(M.massKg(6000, 7850) - 0.0471) < 1e-9);

const box = { version: 1, units: 'mm', components: [{ id: 'b1', name: 'Block', type: 'primitive', kind: 'box', params: { length: 10, width: 20, height: 30 }, material_id: 'steel-s355' }] };
check('validate: good model passes', M.validateModel(box, ['steel-s355']).length === 0);
const bad1 = JSON.parse(JSON.stringify(box)); bad1.components[0].params.length = -5;
check('validate: negative dimension rejected', M.validateModel(bad1).length > 0);
const bad2 = JSON.parse(JSON.stringify(box)); bad2.components[0].kind = 'pyramid';
check('validate: unknown kind rejected', M.validateModel(bad2).length > 0);
const bad3 = JSON.parse(JSON.stringify(box)); bad3.components[0].material_id = 'unobtainium';
check('validate: unknown material rejected', M.validateModel(bad3, ['steel-s355']).length > 0);
const bad4 = JSON.parse(JSON.stringify(box));
bad4.components.push({ id: 'bool1', name: 'Cut', type: 'boolean', kind: 'boolean', params: { op: 'subtract', operands: ['b1', 'missing'] } });
check('validate: boolean missing operand rejected', M.validateModel(bad4).length > 0);
const bad5 = JSON.parse(JSON.stringify(box)); bad5.components[0].parent_id = 'b1';
check('validate: parent cycle rejected', M.validateModel(bad5).length > 0);
const bad6 = JSON.parse(JSON.stringify(box)); bad6.units = 'furlongs';
check('validate: bad unit rejected', M.validateModel(bad6).length > 0);

// The 5 test-model files must validate in JS exactly as in Python.
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, '..', 'workspace', 'test-models');
for (const name of ['shaft', 'gear', 'gearbox', 'beam', 'multi-component']) {
  const m = JSON.parse(fs.readFileSync(path.join(dir, name + '.json'), 'utf8'));
  const errs = M.validateModel(m, null);
  check('test model ' + name + ' validates in JS', errs.length === 0, errs.join('; '));
  const vols = m.components.map(c => M.analyticVolume(c).value);
  check('test model ' + name + ' volumes all positive', vols.every(v => v != null && v > 0), JSON.stringify(vols));
}

console.log('\n' + passed + '/' + total + ' tests passed');
process.exit(passed === total ? 0 : 1);
