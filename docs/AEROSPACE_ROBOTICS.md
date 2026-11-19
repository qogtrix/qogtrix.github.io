# Aerospace & Robotics Engineering Laboratory — Stage 10

19 Nov 2026. Two laboratories built on Stages 1–9: an aerospace
workspace (`aerospace.html`) and a robotics workspace
(`robotics.html`), backed by two new pure-Python-stdlib modules
(`backend/aerospace.py`, `backend/robotics.py`) and 24 new
analytical solvers. XFOIL, AVL, OpenVSP, PyBullet, ROS, MoveIt,
SciPy and NumPy were checked — none is installed on this machine —
so every model here is our own implementation, documented as such.
Nothing here is flight-certified, and nothing is validated for a
real robot.

## Aerospace

### Airfoils and wings
- **NACA 4-digit geometry** (standard ordinate equations).
- **Thin-airfoil theory:** Cl = 2π(α − α₀); α₀ from a numerical
  thin-airfoil integral of the camber-line slope for codes
  outside the table, published values for the five table
  airfoils (NACA 2412, 4412, 0012, 23012, 6412). Verified:
  NACA 2412 α₀ = −2.1°, Cl(0°) = 0.23, max thickness 0.12.
- **Drag polar** Cd = Cd₀ + k·Cl². Cd₀/k/Clmax are typical
  published values for table airfoils; for other sections they
  are required inputs — never guessed.
- **Finite wing (lifting line):** slope
  a = a₀/(1 + a₀/(π·e·AR)), induced drag Cdi = Cl²/(π·e·AR).
  Rectangular wing, no twist or taper correction.

### Aircraft performance
Steady level flight, ISA atmosphere: lift, drag, L/D, stall
speed, thrust and power required, wing loading, Breguet range
(fuel) or battery range/endurance (electric), centre of gravity
from component masses, and the static margin from the wing
aerodynamic centre plus a tail-volume shift. Component masses
must sum to the total mass within 5%, or the run is refused.
Verified against hand computation (10 kg UAV: stall 10.69 m/s,
L/D 11.12, power 176 W, CG 0.59 m, static margin 0.286).

### Multirotor
Momentum theory: thrust per rotor, disk loading, induced
velocity, hover power (ideal power / figure of merit), hover
endurance from battery energy. Verified (2 kg quad: 179 W,
28.5 min).

### Rockets
- **Tsiolkovsky delta-v**, serial multi-stage, with per-stage
  mass ratios and propellant masses. Verified: 300 s / 1000→200 kg
  gives 4735 m/s; the two-stage demo gives 6990 m/s.
- **Thrust:** ṁ·ve + (pe − pa)·Ae.
- **Barrowman centre of pressure** (subsonic, small angles;
  nose + fins only, body lift ignored, straight fin leading
  edges). Stability margin in calibres; 1.0–2.5 is the usual
  rule of thumb, labelled as such. Verified: demo rocket
  CP 0.636 m, margin 0.86 calibres — stable but outside the
  band, correctly flagged.
- **Trajectory:** 2-D point-mass, RK2 integration, gravity,
  ISA drag, thrust profile, mass loss. No wind, no guidance,
  no attitude dynamics. Verified against the no-drag analytic
  case (apogee 981 m vs 980 m).

### Cross-lab: wing spar
An aircraft design can carry a `spar` (length, section,
material, lift). The analysis runs a **Stage 9 structural
check**: the spar as a cantilever beam carrying one wing's
lift at its tip, returning stress, utilisation and tip
deflection. The demo spar (alu-7075-t6, 0.02×0.05 m section)
sees 8.3 MPa, utilisation 0.017.

## Robotics

### Kinematics
- **Denavit-Hartenberg forward kinematics** (standard DH),
  geometric Jacobian, link positions per joint frame.
- **Analytic IK:** planar 2R (elbow up/down) and planar 3R
  (with end-effector orientation). Unreachable targets raise
  an error naming the workspace limits.
- **Damped least-squares IK** for general arms: iterates
  Δq = Jᵀ(JJᵀ + λ²I)⁻¹e with joint-limit clamping, a capped
  step, and a reported residual. A non-converged result is
  reported with its residual, never hidden.
- **Joint limits:** violations listed, clamping available.
- **Workspace reach:** analytic for planar arms.

### Trajectories
- **Cubic** joint-space trajectories (zero end velocities),
  with per-joint max velocity/acceleration.
  Verified: 1 rad in 2 s → max velocity 0.75 rad/s, max
  acceleration 1.5 rad/s².
- **Trapezoidal** velocity profile for one joint, triangular
  when the distance is too short to reach vmax.

### Collision detection
Links are capsules (segment + radius); obstacles are spheres
or axis-aligned boxes. Sphere: point-segment distance.
Box: slab test for centreline penetration, edge distances
for near-misses. The first implementation missed a segment
passing through a box (edge distances only) — fixed with the
slab test and covered by a test.

### PID control
DC-motor plant (the Stage 8 motor model): L di/dt + R i =
V − Ke·ω; J dω/dt + b·ω = Kt·i − load. Discrete PID with
voltage saturation and integral anti-windup. Step-response
metrics: final error, overshoot, settling time, max current.
Verified against theory: P-only with a 0.05 N·m load holds a
steady-state error of exactly R·T/(Kt·Kp) = 0.75 rad; adding
the integrator removes it.

### Mobile robots
Differential drive: forward kinematics (unicycle, one step),
inverse kinematics (wheel speeds for a desired v, ω), and
odometry (dead reckoning — labelled as drifting in the real
world). Verified: 10 rad/s on both wheels, 0.05 m radius,
1 s → 0.5 m straight; turn-in-place ω = 1 rad/s.

### Cross-lab: motor and links
A robot design can carry a `motor` (Stage 8 `dc_motor`
steady-state check: speed, power, efficiency — the demo
motor runs at 2177 rpm) and `links` (Stage 9 structural
check: each link as a cantilever beam carrying the payload
at its tip — demo links see 0.16–0.28 MPa, utilisation
≈ 0.001). Sensors in demo files are descriptive only; no
sensor model is simulated.

## API

- `GET /api/v1/aerospace/schema`, `GET /api/v1/robotics/schema` — public.
- `POST /api/v1/aerospace/validate`, `POST /api/v1/robotics/validate` — auth.
- `POST /api/v1/aerospace/analyze` — auth, owner-scoped project.
  Body `{project_id, design, analysis}`; types `aircraft`,
  `rocket`, `trajectory`, `multirotor`. Stores a job with
  solver `aero_aircraft`, `aero_rocket`, `aero_trajectory` or
  `aero_multirotor`.
- `POST /api/v1/robotics/analyze` — auth, owner-scoped project.
  Types `arm` (FK, limit check, DLS IK, motor check, link
  check, collisions) and `control` (PID + trajectory). Stores
  a job with solver `robot_arm` or `robot_control`.
- `GET / PUT /api/v1/projects/{id}/aerospace` and
  `.../robot` — version-aware design documents (409 on a stale
  `base_version`), mirroring the model/structure documents.
- 24 scalar solvers through the Stage 6 job API
  (`POST /api/v1/simulations`): airfoil_lift, wing_lift_drag,
  stall_speed, aircraft_performance, multirotor_hover,
  rocket_delta_v, rocket_thrust, rocket_stability, aircraft_cg,
  forward_kinematics, ik_2r, ik_3r, ik_dls, cubic_trajectory,
  trapezoidal_profile, collision_check, pid_control,
  diff_drive_fk, diff_drive_ik, diff_drive_odometry.
  The design solvers (`aero_*`, `robot_*`) refuse the scalar
  endpoint with a pointer to the analyze endpoints.

## Workspaces

- **aerospace.html:** Designer (aircraft / multirotor / rocket
  editors + Three.js 3D view with a CG marker), Performance
  (server analysis + airfoil polar chart + jobs), Rocket
  (stage editor, Barrowman stability, trajectory + altitude
  chart), AI Assistant (reads only the last real result),
  Report (HTML + CSV + print).
- **robotics.html:** Arm Designer (DH table, joint sliders
  with live client-side FK, IK target, motor/link checks),
  Control (PID form + step-response chart, cubic trajectory),
  Mobile Robot (diff-drive + odometry trail on a top-view
  canvas), AI Assistant, Report.
- Both workspaces work as guests (local save); server analysis
  and project saving need a signed-in project. The designer
  works offline; the analysis tabs say so when they cannot run.

## Demo projects

- `workspace/test-aerospace/fixed_wing_aircraft.json` — 10 kg
  electric UAV (stall 10.69 m/s, L/D 11.12, spar utilisation 0.017).
- `workspace/test-aerospace/multirotor_drone.json` — 2 kg quad
  (179 W hover, 28.5 min).
- `workspace/test-aerospace/multistage_rocket.json` — two-stage
  rocket (6990 m/s, CP 0.636 m, apogee 7211 m).
- `workspace/test-robots/robot_arm.json` — 4-DOF arm, FK end
  (0.797, 0.247, 0.253) m, IK converges to 0 residual.
- `workspace/test-robots/wheeled_robot.json` — diff-drive robot
  with a straight-line test and a square-path odometry run.
- `workspace/test-robots/robot_assembly.json` — arm + motors +
  PID + trajectory + sensors (sensors descriptive only).

## Honest limits

- **No XFOIL / AVL / OpenVSP** (not installed): no panel
  method, no CFD, no vortex-lattice analysis. Thin-airfoil +
  lifting-line theory only, small angles, attached flow,
  incompressible.
- **No PyBullet / ROS / MoveIt** (not installed): no full
  robot dynamics, no motion planning, no simulated sensors.
  PID is a single-joint motor model, not whole-arm dynamics.
- **Rockets:** point-mass trajectory only; no 6-DOF flight
  dynamics, no guidance, no staging separation dynamics.
- **Structures:** spar/link checks are single cantilever beams
  (conservative), not a full airframe or arm assembly analysis.
- **Nothing here is flight-certified or validated for a real
  robot.** A completed calculation is never a flight or
  safety approval.
