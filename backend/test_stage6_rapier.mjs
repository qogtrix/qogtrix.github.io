/* Headless Rapier benchmarks — Stage 6 validation.
   Runs the REAL Rapier engine (@dimforge/rapier3d-compat 0.14.0)
   in Node and compares it with known analytical solutions.
   Run:  mkdir /tmp/rapier-test && cd /tmp/rapier-test
     npm install @dimforge/rapier3d-compat@0.14.0
     cp <repo>/backend/test_stage6_rapier.mjs test-rapier.mjs
     node test-rapier.mjs
   Rapier API notes learned while writing this test:
   - RigidBodyDesc.lockTranslations() takes NO arguments and locks
     ALL axes; use enabledTranslations(x, y, z) for partial locks.
   - Forces and torques accumulate in separate accumulators:
     call resetForces(true) AND resetTorques(true) each step when
     applying a fresh force/torque per step.
*/
/* Headless Rapier benchmarks — runs the REAL Rapier engine
   (@dimforge/rapier3d-compat 0.14.0) in Node and compares it with
   known analytical solutions. These are the Stage 6 validation
   benchmarks for the rigid-body engine the browser workspace uses.
   Run:  cd /tmp/rapier-test && npm install @dimforge/rapier3d-compat@0.14.0 && node test-rapier.mjs
*/
import RAPIER from '@dimforge/rapier3d-compat';

let passed = 0, total = 0;
function check(name, ok, detail) {
  total++;
  if (ok) { passed++; console.log('PASS  ' + name); }
  else console.log('FAIL  ' + name + (detail ? ' — ' + detail : ''));
}
const approx = (a, b, tol) => Math.abs(a - b) <= tol;

await RAPIER.init();
const DT = 1 / 60;
function step(world, seconds) {
  const n = Math.round(seconds / DT);
  for (let i = 0; i < n; i++) world.step();
}

// 1. Free fall: dropped from 10 m, g = 9.81.
//    After 1.0 s: y = 10 - 4.905 = 5.095 m, v = -9.81 m/s.
{
  const world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
  world.timestep = DT;
  const body = world.createRigidBody(RAPIER.RigidBodyDesc.dynamic().setTranslation(0, 10, 0));
  world.createCollider(RAPIER.ColliderDesc.ball(0.5).setDensity(1), body);
  step(world, 1.0);
  const y = body.translation().y, v = body.linvel().y;
  check('free fall: y after 1 s = 5.095 m', approx(y, 5.095, 0.05), 'got ' + y.toFixed(3));
  check('free fall: v after 1 s = -9.81 m/s', approx(v, -9.81, 0.05), 'got ' + v.toFixed(3));
  // Energy: KE + PE constant (PE = m g y, KE = 1/2 m v^2).
  const m = body.mass();
  const ke = 0.5 * m * v * v, pe = m * 9.81 * y;
  check('free fall: energy conserved (KE+PE = 98.1 J per kg-ish)',
    approx(ke + pe, m * 9.81 * 10, m * 0.5), 'KE+PE=' + (ke + pe).toFixed(2) + ' initial=' + (m * 98.1).toFixed(2));
  world.free();
}

// 2. Collision: ball dropped 2 m onto a fixed floor, restitution 0.5.
//    It must bounce (velocity reverses) and rise to ~0.25 x the drop height.
{
  const world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
  world.timestep = DT;
  const floor = world.createRigidBody(RAPIER.RigidBodyDesc.fixed().setTranslation(0, -0.5, 0));
  world.createCollider(RAPIER.ColliderDesc.cuboid(50, 0.5, 50).setRestitution(0.5), floor);
  const body = world.createRigidBody(RAPIER.RigidBodyDesc.dynamic().setTranslation(0, 2.5, 0));
  world.createCollider(RAPIER.ColliderDesc.ball(0.5).setDensity(1).setRestitution(0.5), body);
  let maxYAfterBounce = 0, bounced = false, prevV = 0;
  for (let i = 0; i < 180; i++) {
    world.step();
    const v = body.linvel().y, y = body.translation().y;
    if (prevV < 0 && v > 0) bounced = true;
    if (bounced && y > maxYAfterBounce) maxYAfterBounce = y;
    prevV = v;
  }
  check('collision: ball bounces (velocity reverses)', bounced, '');
  // Drop height above floor contact = 2.5 - 0.5 = 2.0 m; rebound ~0.25 * 2 = 0.5 m above contact.
  check('collision: rebound height ~0.5 m above floor', approx(maxYAfterBounce, 1.0, 0.25), 'got ' + maxYAfterBounce.toFixed(2) + ' (floor top y=0, ball centre = 0.5 + height)');
  world.free();
}

// 3. Spring-mass: mass 1 kg, k = 40 N/m, no gravity, no damping.
//    Period T = 2*pi*sqrt(m/k) = 0.993 s. Measure zero crossings.
{
  const world = new RAPIER.World({ x: 0, y: 0, z: 0 });
  world.timestep = DT;
  // Free along X only (the spring acts along X); lock Y and Z.
  // NOTE: RigidBodyDesc.lockTranslations() takes no args and locks
  // ALL axes — use enabledTranslations(x, y, z) instead.
  const body = world.createRigidBody(RAPIER.RigidBodyDesc.dynamic().setTranslation(1, 0, 0).enabledTranslations(true, false, false));
  world.createCollider(RAPIER.ColliderDesc.ball(0.2).setDensity(1), body);
  body.setBodyType(RAPIER.RigidBodyType.Dynamic, true);
  const k = 40, m = 1;
  let prevX = 1, crossings = [];
  for (let i = 0; i < 600; i++) {
    const x = body.translation().x;
    const F = -k * x; // spring force
    // Rapier keeps separate force and torque accumulators —
    // reset both each step so exactly F applies this step.
    body.resetForces(true);
    body.resetTorques(true);
    body.addForce({ x: F, y: 0, z: 0 }, true);
    world.step();
    const nx = body.translation().x;
    if (prevX > 0 && nx <= 0) crossings.push(i * DT);
    prevX = nx;
  }
  // Two successive downward zero-crossings are one period apart.
  const measuredMass = body.mass();
  const expectedT = 2 * Math.PI * Math.sqrt(measuredMass / k);
  const period = crossings.length >= 2 ? crossings[1] - crossings[0] : null;
  check('spring-mass: oscillates with period 2*pi*sqrt(m/k)',
    period != null && approx(period, expectedT, 0.15),
    'measured T=' + (period ? period.toFixed(3) : 'none') + ' expected=' + expectedT.toFixed(3) + ' (mass ' + measuredMass.toFixed(3) + ' kg)');
  world.free();
}

// 4. Rotating body: angular velocity conserved with no damping, no gravity.
{
  const world = new RAPIER.World({ x: 0, y: 0, z: 0 });
  world.timestep = DT;
  const body = world.createRigidBody(RAPIER.RigidBodyDesc.dynamic()
    .setTranslation(0, 0, 0).setAngvel({ x: 0, y: 0, z: 2.0 })
    .setAngularDamping(0).setLinearDamping(0));
  world.createCollider(RAPIER.ColliderDesc.ball(0.5).setDensity(1), body);
  step(world, 1.0);
  const w = body.angvel();
  check('rotation: angular velocity conserved (2.0 rad/s, no damping)',
    approx(w.z, 2.0, 0.05), 'got ' + w.z.toFixed(3));
  // Torque: apply a known torque for 0.5 s and check angular velocity change.
  // I for a solid sphere r=0.5, m = 4/3 pi r^3 * 1 = 0.524 kg: I = 0.4 m r^2 = 0.0524 kg m^2.
  // Torque 0.1 N m -> alpha = 1.909 rad/s^2 -> dw = 0.954 rad/s over 0.5 s.
  const I = 0.4 * body.mass() * 0.25;
  body.setAngvel({ x: 0, y: 0, z: 0 }, true);
  for (let i = 0; i < 30; i++) {
    body.resetForces(true);
    body.resetTorques(true);
    body.addTorque({ x: 0, y: 0, z: 0.1 }, true);
    world.step();
  }
  const w2 = body.angvel().z;
  check('rotation: torque produces alpha = T/I',
    approx(w2, 0.1 / I * 0.5, 0.15), 'got ' + w2.toFixed(3) + ' expected ' + (0.1 / I * 0.5).toFixed(3));
  world.free();
}

// 5. Static vs dynamic vs kinematic: a static body never moves under gravity.
{
  const world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
  world.timestep = DT;
  const fixed = world.createRigidBody(RAPIER.RigidBodyDesc.fixed().setTranslation(0, 5, 0));
  world.createCollider(RAPIER.ColliderDesc.ball(0.5), fixed);
  step(world, 1.0);
  check('static body does not fall', approx(fixed.translation().y, 5, 1e-6), 'got ' + fixed.translation().y);
  world.free();
}

console.log('\n' + passed + '/' + total + ' Rapier benchmark tests passed');
process.exit(passed === total ? 0 : 1);
