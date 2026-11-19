# AI Engineering Laboratory — Stage 1: Foundation

Advanced AI-powered engineering laboratory. Long-term objective: a
platform where an AI agent can independently design, model, simulate,
analyse, test and improve engineering systems.

Hybrid approach: own platform + workflows, own material database and
component library, own AI agent, reliable open-source libraries and
solvers where appropriate, no unnecessary dependence on paid APIs.

**Live site:** https://qogtrix.github.io/
**Custom domain (pending):** https://qogtrix.is-a.dev/ — goes live
after is-a.dev PR #61755 is merged, then set as Custom Domain in
the repo Pages settings (see `docs/RUN_DEPLOY.md`).

## Stage 1 — what is built

- Premium dark-themed dashboard (`index.html`)
- Six laboratories, each with a dedicated page:
  Mechanical, Electrical, Structural, Aerospace, Robotics,
  Materials Science (`labs/*.html`)
- 3D workspace with Three.js 0.160.0 (`workspace.html` + per-lab
  presets) — orbit/zoom/pan, wireframe, grid, auto-rotate, reset,
  PNG export, real geometry statistics
- Materials database — 12 materials, searchable / filterable /
  sortable, with typical published values
  (verify against datasheets before design use)
- Component library — 12 standard components, filterable by lab
- Projects — create / list / delete / export JSON, stored in the
  browser (`localStorage`)
- System status panel — real runtime checks
- Responsive desktop + mobile, error handling throughout

## Stage 1 — what is deliberately NOT built

No simulator, no running backend, no server database, no AI agent
runtime. Simulation controls are disabled and labelled Stage 2.
No hardcoded result is ever presented as a simulation.
See `docs/STATUS.md` for the full completed / incomplete list.

## Run locally

```bash
python3 -m http.server 8000
# open http://localhost:8000/
```

Full instructions: `docs/RUN_DEPLOY.md`

## Docs

- `docs/ARCHITECTURE.md` — technical architecture
- `docs/DEPENDENCIES.md` — dependency list (Three.js only, MIT)
- `docs/STATUS.md` — completed vs incomplete
- `docs/AI_AGENT.md` — AI-agent foundation contract
- `docs/RUN_DEPLOY.md` — run & deploy instructions
- `backend/api-spec.md` — API contract for Stage 2
- `db/schema.sql` — database schema for Stage 2

## File map

```
index.html  workspace.html
labs/*.html (x6)
assets/css/style.css
assets/js/app.js  assets/js/workspace3d.js  assets/js/materials.js
data/labs.json  data/materials.json  data/components.json
backend/app.py  backend/requirements.txt  backend/api-spec.md
db/schema.sql
docs/*.md
```

## Stage 2 — User Accounts and Personal Workspaces (19 Nov 2026)

- Register / sign in / sign out, profile + password change.
  Passwords hashed with PBKDF2; sessions are HMAC-signed tokens
  (7 days, revocable).
- One independent workspace per user: My Projects, Recent Work,
  Account Settings. Create, search, open, rename, duplicate,
  delete (with confirmation), save progress.
- Ownership enforced on every API call — another user's project
  returns 404. Tested with two accounts: **34/34 tests passed**
  (`backend/test_stage2.py`, see `docs/TEST_RESULTS_STAGE2.md`).
- Muse integration prep: scoped API keys (`aielab_…`) in Account
  Settings — see `docs/MUSE_INTEGRATION.md`.
- Run the backend: `cd backend && python3 app.py` (stdlib only,
  no install). GitHub Pages cannot run a backend, so the static
  site shows the Stage 2 frontend with a clear "backend must be
  running" state; the working authenticated app is the hosted
  fullstack version.

## Stage 3 — Private and Public Project Visibility (19 Nov 2026)

- Every user has a **unique username** (3–30 chars, login by email
  or username). The gallery shows `@username`, never email.
- Every project is **private by default** — even if a client asks
  for public on creation. Owners publish explicitly (Publish button,
  or visibility control in the project editor).
- **Public Gallery** (`gallery.html`): recently published projects,
  category filter, search, read-only detail. Private projects never
  appear in the list, search, or detail — direct URLs return 404.
- Tests: `backend/test_stage3.py`, **34/34 passed** (A–G sequence
  with Alice/Bob + username + leak checks); Stage 2 suite still 34/34.
  See `docs/TEST_RESULTS_STAGE3.md`.
- Future sharing / downloads / version history / comments /
  collaboration are prepared in the architecture only, not built.

## Stage 4 — Universal Material Database (19 Nov 2026)

- **38 materials across 10 categories** — a working sample, not a
  complete universal database. Values are typical published values
  with sources; missing values are null and shown as "—".
- **Library** (`materials.html`): search, category chips, property
  filters, sort, favorites, 2–4 material comparison with
  best-value highlighting, and a requirements recommender with
  transparent scoring (50% strength-to-weight + 30% specific
  stiffness + 20% low cost).
- **Material pages** (`material.html?id=...`): grouped properties,
  data quality (source, standard, test conditions, temperature
  range, confidence), derived metrics, related materials, and
  select-for-project.
- **Backend:** normalized tables (`materials`,
  `material_properties`, `material_favorites`), seeded once from
  `data/materials.json`; API for search/filter/compare/recommend/
  favorites/project selection. See `docs/MATERIALS.md`.
- Tests: `backend/test_stage4.py`, **42/42 passed**; Stage 2 and
  Stage 3 suites still 34/34. See `docs/TEST_RESULTS_STAGE4.md`.
- Add a material by appending one entry to
  `data/materials.json` — no code change needed.

## Stage 5 — 3D Modelling Workspace (19 Nov 2026)

- **Real parametric modeller** (`workspace.html`): primitives,
  extrusions, revolves, 11 library components, real CSG booleans
  (three-bvh-csg), holes, rounded/chamfered boxes, assemblies
  with parent-child hierarchy, section + exploded views,
  perspective/orthographic cameras, gizmos, selection.
- **Materials:** Stage 4 material per component, mesh volume and
  mass in the inspector.
- **Saving:** into the user's project with version-aware updates
  (409 on a stale base_version), autosave, duplicate, reopen.
- **Import/export:** STL, OBJ, GLB, JSON (real). STEP/3MF/FCStd
  are not supported by the mesh kernel — stated in the UI and
  docs. See `docs/MODELLING.md` for the exact limits.
- **AI tools:** `GET /api/v1/model/schema` + project model API
  (create/modify/assign/assemble/inspect/save/export).
- Tests: `backend/test_stage5.py` **56/56**,
  `backend/test_stage5_math.js` **29/29**,
  `backend/test_stage5_kernel.mjs` **28/28** (headless, real
  geometry + real CSG volumes). See `docs/TEST_RESULTS_STAGE5.md`.

## Stage 6 — Physics and Simulation Foundation (19 Nov 2026)

- **Rigid-body dynamics** (`simulate.html`): real Rapier
  0.14.0 engine in the browser — dynamic/static/kinematic
  bodies from your model, gravity, friction, restitution,
  forces (impulse/continuous), Rapier spring joints,
  fixed/revolute joints, live state, height + energy charts,
  results saved to a backend job. Validated headlessly 9/9
  against analytical references.
- **Analytical solvers** (backend, SI units): cantilever and
  simply-supported beams, axial bar, torsion, 1-D conduction,
  lumped thermal, drag/lift, free fall — all labelled
  ANALYTICAL with their assumptions; missing material
  properties are named errors, never substitutions.
- **Job system:** `GET /api/v1/solvers` + the simulations
  API (create/run/list/get/delete/post-results), owner-scoped.
- **Honest limits:** no FEA (CalculiX/Code_Aster) and no CFD
  (OpenFOAM) are installed — those jobs are recorded as
  `not_implemented`, never faked. See `docs/SOLVERS.md` and
  `docs/VALIDATION_STAGE6.md`.
- Tests: `backend/test_stage6.py` **29/29**,
  `backend/test_stage6_rapier.mjs` **9/9**.
  See `docs/TEST_RESULTS_STAGE6.md`.

## Stage 7 — Mechanical Engineering Laboratory (19 Nov 2026)

- **Mechanical workspace** (`mechanical.html`): assembly
  preview with exploded view, 16-component mechanical library,
  gear-train calculator, crank-slider animator with exact
  kinematics, calculation panel, bill of materials (CSV +
  print), material alternatives.
- **11 analytical mechanical solvers** (backend, SI units):
  gear train, combined shaft stress, bearing loads, belt drive,
  helical spring, flywheel, hydraulic cylinder, crank-slider
  (720° series), shaft fatigue (Goodman), 1-DOF vibration,
  power transmission — all labelled ANALYTICAL with their
  assumptions; missing material properties are named errors.
- **4 demo assemblies**: gear transmission (2:1), crank-slider,
  rotating shaft, hydraulic lift — in
  `workspace/test-models/mechanical/`.
- **Honest limits:** conceptual designs only — no FEA/CFD, no
  constraint solver, components are simplified representations.
  See `docs/MECHANICAL.md` and `docs/TEST_RESULTS_STAGE7.md`.
- Tests: `backend/test_stage7.py` **99/99**,
  `backend/test_stage7_math.js` **36/36**,
  `backend/test_stage7_kernel.mjs` **22/22**.

## Stage 8 — Electrical Engineering Laboratory (19 Nov 2026)

- **Real circuit simulator** (`backend/circuit.py`): Modified
  Nodal Analysis — DC operating point (Newton-Raphson),
  transient (backward Euler), AC sweep (small-signal).
  Resistors, capacitors, inductors, sources, diodes, LEDs,
  BJTs, MOSFETs, op-amps, switches, relays, ground.
  ngspice/FEMM/Elmer are not installed on this machine, so
  this is our own solver — documented, not hidden.
- **Electrical workspace** (`electrical.html`): schematic
  editor (place, wire, drag, edit), DC/transient/AC runs
  with real charts, calculations, motors & batteries, BOM.
- **11 analytical electrical solvers**: Ohm's law, series/
  parallel, RC, RLC resonance, AC power, transformer,
  DC motor, battery pack, motor+gearbox (Stage 7 link),
  solenoid, wire resistance from real material data.
- **6 demo circuits**: voltage divider, RC step, RLC
  resonance, half-wave rectifier, DC motor, 4s2p battery.
- **Honest limits:** conceptual designs only — simplified
  device models, no field solver, no distribution or
  protection systems. See `docs/ELECTRICAL.md` and
  `docs/TEST_RESULTS_STAGE8.md`.
- Tests: `backend/test_stage8.py` **71/71**.

## Stage 9 — Structural Engineering Laboratory (19 Nov 2026)

- **Real structural solver** (`backend/structure.py`):
  direct-stiffness analysis for 3D trusses and Euler-Bernoulli
  beams — reactions, displacements, shear/moment/axial
  diagrams, stress and utilisation, Euler/Johnson member
  buckling, modal frequencies and mode shapes. CalculiX,
  Code_Aster and Elmer are not installed on this machine, so
  this is our own solver — documented, not hidden.
- **Structural workspace** (`structural.html`): 3D designer
  (nodes, members, supports, loads, combinations), deformed
  shape and utilisation colouring, member diagrams, analysis
  jobs, calculations, standards status, AI assistant that
  reads only real results, reports (HTML, CSV, print-to-PDF),
  import from the project's 3D model.
- **6 analytical structural solvers**: column buckling, fixed
  beam, natural frequency, IS 875 wind and IS 1893 seismic
  formula calculators, load combinations.
- **6 demo structures**: SS beam, cantilever, 2D truss, portal
  frame, truss bridge, column buckling — all verified against
  analytical references.
- **Honest limits:** first-order, linear-elastic only; no
  plate/shell/solid FEA; no code compliance (IS 800 / IS 456 /
  AISC / Eurocodes not implemented); nothing validated for
  construction. See `docs/STRUCTURAL.md` and
  `docs/TEST_RESULTS_STAGE9.md`.
- Tests: `backend/test_stage9.py` **80/80**.

## Stage 10 — Aerospace & Robotics Engineering Laboratory (19 Nov 2026)

- **Real aerospace models** (`backend/aerospace.py`): NACA
  4-digit airfoils + thin-airfoil theory, lifting-line wing
  corrections, aircraft performance (stall speed, L/D,
  Breguet range, static margin), multirotor hover
  (momentum theory), Tsiolkovsky multi-stage delta-v,
  Barrowman stability, 2-D point-mass trajectories.
  XFOIL / AVL / OpenVSP are not installed on this machine,
  so these are our own models — documented, not hidden.
- **Real robotics models** (`backend/robotics.py`):
  Denavit-Hartenberg FK, analytic 2R/3R IK, damped
  least-squares IK with joint limits, cubic and trapezoidal
  trajectories, capsule collision detection, PID control of
  a DC motor, differential-drive kinematics and odometry.
  PyBullet / ROS / MoveIt are not installed.
- **Workspaces** (`aerospace.html`, `robotics.html`): 3D
  vehicle and arm views, parameter editors, performance /
  rocket / control panels, AI assistants that read only
  real results, reports (HTML, CSV, print-to-PDF).
- **Cross-lab integration:** wing spar (Stage 9), robot
  motor (Stage 8), robot links (Stage 9) — through the
  real engines, not copies.
- **6 demo projects**: fixed-wing aircraft, multirotor
  drone, multi-stage rocket, 4-DOF robot arm, wheeled
  robot, robot assembly with motors and sensors.
- **Honest limits:** no panel method or CFD; no full robot
  dynamics; nothing flight-certified or validated for a
  real robot. See `docs/AEROSPACE_ROBOTICS.md` and
  `docs/TEST_RESULTS_STAGE10.md`.
- Tests: `backend/test_stage10.py` **140/140**.

## Stage 11 — AI Engineering Assistant (19 Nov 2026)

- **A lightweight per-user AI assistant** (`assistant.html`):
  chat with the laboratory's real engines — ask in plain
  language, get a verified calculation, a solved circuit, a
  material lookup, or an explanation, with the provenance of
  every result labelled.
- **27 tools** across materials, mechanical, electrical,
  structural, aerospace, robotics and projects — each a thin
  wrapper around an existing solver. Nothing is duplicated,
  and no large model is trained or hosted.
- **Unit-aware understanding** ("gear train 20 and 40 teeth,
  1000 rpm, 10 Nm", "voltage divider 10 V, R1 1k, R2 1k"):
  missing values are asked for, never invented, and a solver
  refusal is reported honestly.
- **Project assistance with approval:** attach one of your
  projects, ask the assistant to inspect it or propose a
  change — the change is applied only after you approve it.
- **Isolation and cost control:** every conversation, message,
  proposal and usage row belongs to one user (owner-verified
  on the backend); rate limits per user; usage and estimated
  cost tracked per user (local engine: $0). External AI
  providers are supported through server-side configuration
  only — no key is configured by default.
- **Honest limits:** the local engine is a deterministic
  intent parser, not a general AI; proposals cover two change
  types only. See `docs/ASSISTANT.md` and
  `docs/TEST_RESULTS_STAGE11.md`.
- Tests: `backend/test_stage11.py` **45/45** (all 12 required
  categories).
