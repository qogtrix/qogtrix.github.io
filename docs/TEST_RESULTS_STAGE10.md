# Stage 10 test results — 19 Nov 2026

`backend/test_stage10.py` — **140/140 tests passed.**

## Aerospace module (vs hand-computed references)

- ISA density: 1.225 kg/m³ at sea level, 0.736 at 5000 m;
  altitudes above 11000 m are rejected.
- NACA 2412: zero-lift angle −2.1° (published), Cl(0°) 0.23,
  Cl(5°) 0.779, Cd(5°) 0.033, stalled at 20°; NACA 0012 α₀ = 0;
  max thickness 0.12 chord. An unknown airfoil code without
  Cd0/k/Clmax raises a named error.
- Finite wing (section Cl 0.5, AR 8, e 0.8): Cl 0.381,
  Cdi 0.0072, Cd 0.0172.
- Aircraft (10 kg UAV): stall speed 10.69 m/s, L/D 11.12,
  power required 176.3 W, endurance 1.69 h, CG 0.59 m, static
  margin 0.286, statically stable. A cruise speed whose Cl
  exceeds Clmax is refused; component masses that do not sum
  to the total mass are refused.
- Multirotor (2 kg quad): thrust per rotor 4.9 N, hover power
  178.9 W, endurance 28.5 min.
- Rocket: single-stage Δv 4735 m/s; two-stage 6990 m/s with
  propellant 700 + 200 kg; a stage with mf ≥ m0 is refused.
  Thrust 29420 N at ṁ = 10 kg/s, Isp 300 s.
- Barrowman: CP 0.636 m, total Cn 6.24, stability 0.86
  calibres — stable, but outside the 1.0–2.5 band, flagged.
- Trajectory: no-drag analytic case, apogee 981 m vs 980 m;
  vertical launch range is 0.
- Centre of gravity: 0.725 m for the two-mass check.

## Robotics module (vs hand-computed references)

- FK 2R: [0,0] → (2,0,0); [90°,0] → (0,2,0);
  [90°,90°] → (−1,1,0). All exact.
- IK 2R: (1,1) elbow up [0°,90°], elbow down [90°,−90°];
  an unreachable target raises with the workspace limits.
- IK 3R round-trips through FK to (1.5, 0.5) exactly.
- DLS IK on a 3-DOF arm: residual < 1e-3, converged in 8
  iterations; FK of the solution matches the target.
- Joint limits: violations listed, clamping exact.
- Cubic trajectory: endpoints exact, max velocity 0.75 /
  0.375 rad/s (= 1.5·Δ/T), max acceleration 1.5 / 0.75 rad/s²
  (= 6·Δ/T²).
- Trapezoidal profile: T = 3 s for 2 m at vmax 1 m/s,
  amax 1 m/s²; a short move is triangular (never reaches vmax).
- Collision: capsule–sphere hit with penetration 0.03 m;
  far obstacle gives no hit; capsule–box hit detected.
- PID: well-damped gains give overshoot 14.1% and final error
  under 0.1 rad. P-only with a 0.05 N·m load holds exactly
  0.75 rad steady-state error (= R·T/(Kt·Kp)); adding the
  integrator removes it (< 0.1 rad).
- Diff drive: straight 0.5 m in 1 s; turn-in-place ω = 1 rad/s;
  IK gives 10 rad/s per wheel for 0.5 m/s; odometry of a
  3 s straight run ends at x = 1.5 m.

## Solvers (through run_solver)

airfoil_lift, stall_speed, rocket_delta_v, ik_2r,
forward_kinematics, collision_check, diff_drive_fk and
pid_control all verified through the real entry point.
`aero_aircraft` and `robot_arm` refuse the scalar endpoint
with a pointer to the analyze endpoints. The registry lists
all 24 Stage 10 solvers.

## Demo projects

All six files analyse to their expected values: fixed-wing
(stall 10.69 m/s, L/D 11.12), quad (178.9 W, 28.5 min),
rocket (6990 m/s, CP 0.636 m, apogee 7211 m), arm (FK
(0.797, 0.247, 0.253) m, IK converges), wheeled robot
(straight pose (0.5, 0, 0) m), assembly (IK converges, PID
overshoot below 20%).

## API (real backend on a temporary database, real HTTP)

Health reports stage 10. Both schemas list their analyses.
Validate accepts a good design and rejects a bad kind.
Aircraft analysis completes with stall speed 10.69 m/s and
the Stage 9 spar check (8.3 MPa, utilisation 0.017).
Multirotor, rocket (6990 m/s, 0.86 calibres) and trajectory
(apogee above 5000 m) complete. An invalid aircraft is
recorded `failed`. Bob gets 404 on Alice's project. Arm
analysis completes with FK, converged IK, the Stage 8 motor
check (2177 rpm), Stage 9 link checks (all below yield), no
collisions and no limit violations. Control analysis
completes with PID and trajectory. Scalar jobs complete
(airfoil_lift, ik_dls, pid_control). `aero_aircraft` via the
simulations endpoint is recorded `failed` with the pointer.
Design documents: aerospace and robot both start at version 1,
save to version 2, round-trip, stale base_version is 409,
Bob PUT is 404.

## Earlier suites re-run

Stage 2 **34/34**, Stage 3 **34/34**, Stage 4 **42/42**,
Stage 5 **56/56** (backend) + **29/29** (JS maths) +
**28/28** (headless kernel), Stage 6 **29/29** (backend) +
**9/9** (Rapier), Stage 7 **99/99** (backend) + **36/36**
(JS maths) + **22/22** (headless kernel), Stage 8 **71/71**,
Stage 9 **80/80**, Stage 10 **140/140**. Health assertions
accept stage 10. All green — **585 Python tests** in total.

## Bugs found and fixed while testing Stage 10

- **Capsule–box collision missed a real hit.** The first
  implementation only measured the distance from the link
  segment to the box's edges, so a segment passing straight
  through the box reported no collision (nearest edge 0.1 m
  away). Fixed with a slab test for centreline penetration;
  the edge-distance check now only handles near-misses.
- **Trajectory design shape.** The frontend's `runAnalyze`
  passed the whole rocket design to the trajectory analysis,
  but the trajectory solver reads top-level mass/diameter
  fields — the design carries them under `trajectory`.
  Fixed in the frontend (passes the trajectory sub-object).

## Not tested

- Browser rendering of `aerospace.html` / `robotics.html`
  (syntax checked with `node --check`; pages served locally
  return 200). The Three.js views, charts and live joint
  sliders were not probed in a live browser from this
  environment.
- XFOIL / AVL / OpenVSP / PyBullet / ROS / MoveIt: not
  installed — the honest result is our own models, which are
  what is tested.
