# Stage 1 — Completed vs Incomplete

**Date:** 19 Nov 2026
**Rule applied throughout:** nothing is marked complete unless it was
actually built and checked. Anything labelled "Stage 2" is not done.

## Completed in Stage 1

- [x] Environment inspected (Node 24.22.1, Python 3.12.3, Git 2.43.0,
      GitHub connected as `qogtrix`, GitHub Pages live at
      `qogtrix.github.io`, `qogtrix.is-a.dev` not yet live — PR #61755 open)
- [x] Technical architecture designed and documented (`docs/ARCHITECTURE.md`)
- [x] Modular project structure created (see `README.md` file map)
- [x] Premium dark-themed dashboard (`index.html`) — responsive
- [x] Navigation (sidebar desktop / hamburger mobile) across all pages
- [x] Six laboratory pages, each dedicated:
      Mechanical, Electrical, Structural, Aerospace, Robotics,
      Materials Science (`labs/*.html`)
- [x] 3D workspace with Three.js 0.160.0 (`workspace.html` + per-lab
      presets) — orbit/zoom/pan, wireframe, grid, auto-rotate, reset,
      preset switch, real geometry stats, screenshot export
- [x] Materials database (12 materials, typical published values,
      searchable / filterable / sortable table, detail view)
- [x] Component library (12 components, filterable by laboratory)
- [x] Projects: create / list / delete / export as JSON, stored in
      the browser (`localStorage`) — real, no server
- [x] System status panel on the dashboard — real runtime checks
      (WebGL, Three.js loaded, data files loaded, localStorage)
- [x] Backend architecture prepared: FastAPI skeleton (`backend/app.py`,
      only `/health` works), API spec (`backend/api-spec.md`)
- [x] Database architecture prepared: `db/schema.sql`
      (materials, components, projects, simulations, agent_runs)
- [x] AI-agent foundation prepared as a written contract
      (`docs/AI_AGENT.md`) — no agent runtime yet
- [x] Dependency list (`docs/DEPENDENCIES.md`)
- [x] Run / deploy instructions (`docs/RUN_DEPLOY.md`)
- [x] Error handling: WebGL fallback, CDN failure message, data-load
      failure state with retry, global error banner
- [x] Responsive desktop + mobile layouts
- [x] Deployed to GitHub Pages (`qogtrix.github.io`)

## Incomplete / explicitly NOT in Stage 1

- [ ] `qogtrix.is-a.dev` live — blocked on is-a.dev maintainer merge
      of PR #61755 (and #61759 for `leadloop.is-a.dev`). After merge:
      set Custom Domain in the repo Pages settings + Enforce HTTPS.
- [ ] Any engineering simulator (stress/FEA, thermal, CFD, circuit,
      dynamics, kinematics). Simulation sections are shown as
      "Stage 2 — Not yet implemented" with disabled controls.
- [ ] Backend server running anywhere (skeleton only; simulation
      endpoints return 501 Not Implemented by design).
- [ ] Server database (schema only; Stage 1 data lives in JSON files
      + browser `localStorage`).
- [ ] AI engineering agent runtime (contract only).
- [ ] User accounts / login.
- [ ] Real solver integration (open-source solver evaluation is Stage 2).

## Known limitations

- Three.js loads from jsDelivr CDN — the 3D workspace needs internet.
  If the CDN is unreachable, the page shows an error instead of a
  frozen canvas.
- Material values are *typical published values*, not certified
  datasheet values. They are labelled as such on every materials page.
  Verify against a datasheet before any design use.
- 3D presets are conceptual geometry previews, not engineering models
  and not simulation results.

---

# Stage 2 — User Accounts and Personal Workspaces (19 Nov 2026)

## Completed in Stage 2

- [x] Registration + login + logout + profile + change password, with
      proper error handling (400/401/409/429) and loading/empty/error states
- [x] Persistent sessions (7-day HMAC-signed tokens, revocable on logout)
- [x] Secure password handling: PBKDF2-HMAC-SHA256, 200k iterations,
      per-user salt; only hashes stored
- [x] Personal workspaces: Dashboard, My Projects, Recent Work (5 latest),
      Laboratories, Account Settings — one workspace per user
- [x] Project management: create (name/description/lab), search, lab
      filter, open + continue, rename, duplicate, delete with confirmation,
      save progress (payload JSON) — all server-side, owner-scoped
- [x] Ownership isolation: owner_id on every project, backend checks on
      every endpoint, other users' projects return 404; Postgres RLS
      policies defined in db/schema.sql
- [x] Muse integration prep: scoped API keys (aielab_…), shown once,
      hash stored, revocable, owner-bound — see docs/MUSE_INTEGRATION.md
- [x] Frontend: auth.html, projects.html, settings.html + auth.js /
      projects.js / config.js, in the existing dark theme, responsive
- [x] Backend implemented for real (stdlib only, SQLite): backend/app.py,
      auth.py, db.py — no pip install needed
- [x] Tests: 34/34 passed with two accounts (Alice/Bob) — see
      docs/TEST_RESULTS_STAGE2.md; plus a live curl check as Karan
- [x] Docs updated: ARCHITECTURE.md (Stage 2), api-spec.md, STATUS.md,
      MUSE_INTEGRATION.md, TEST_RESULTS_STAGE2.md, RUN_DEPLOY.md

## Incomplete / explicitly NOT in Stage 2

- [ ] Simulation solvers (still Stage 3)
- [ ] AI agent runtime connected via API key (contract + keys only)
- [ ] Email verification / password reset by email
- [ ] Live Postgres deployment with RLS executed (policies defined,
      SQLite tested; backend checks are the tested layer)
- [ ] GitHub Pages cannot run the backend — the static site shows the
      Stage 2 frontend with a "backend must be running" state; the
      working authenticated app is the hosted fullstack version

---

# Stage 3 — Private and Public Project Visibility (19 Nov 2026)

## Completed in Stage 3

- [x] Visibility: private (default) / public on every project;
      new projects always private, even if the client asks for public
- [x] Explicit publish / unpublish (dedicated endpoints + PATCH
      visibility + control in the project editor and My Projects list)
- [x] Public gallery (`gallery.html`): recent published projects,
      category filter, search, owner username, read-only detail view
- [x] Unique usernames: required at registration, login by email or
      username, changeable if free, shown in the gallery instead of email
- [x] Security: server-side ownership checks on every mutation,
      public endpoints query visibility='public' only, private projects
      return 404 to everyone else (including via guessed URLs), no
      email/owner_id in any public response
- [x] Tests: backend/test_stage3.py — 34/34 passed (A–G sequence +
      username + leak checks); Stage 2 suite still 34/34
- [x] Docs updated: ARCHITECTURE.md, STATUS.md, api-spec.md,
      TEST_RESULTS_STAGE3.md, README.md, RUN_DEPLOY.md

## Incomplete / explicitly NOT in Stage 3

- [ ] Public sharing links, downloadable designs, version history,
      public comments, collaboration (prepared only, see ARCHITECTURE §18)
- [ ] File attachments (none exist yet; access rule is documented)
- [ ] Project preview images in the gallery (no images exist yet;
      gallery shows published design data instead)
- [ ] Live Postgres RLS execution (policies defined in schema.sql;
      SQLite + backend checks are the tested layers)

---

# Stage 4 — Universal Material Database (19 Nov 2026)

## Completed in Stage 4

- [x] 10 material categories with counts (metals 12, polymers 7,
      ceramics 4, composites 2, electrical 2, magnetic 2,
      thermal-insulation 3, aerospace 2, construction 2, advanced 2)
- [x] 38 graded materials with 16 properties each, standards and
      sources where available; missing values are null, never invented
- [x] Data quality: source/reference, standard, units, test
      conditions, temperature range, confidence (verified/typical/
      estimated), missing-property indicators on every entry
- [x] Library interface: search, category chips, property filters,
      sort, individual material pages, favorites, select-for-project
- [x] Comparison engine: 2–4 materials, 18 rows incl. derived
      strength-to-weight and specific stiffness, best-value
      highlighting, cost and corrosion
- [x] Recommender: hard filters + transparent scoring (50/30/20),
      reasons and trade-offs per candidate
- [x] Normalized DB: materials + material_properties +
      material_favorites; seeded once from materials.json;
      material data separate from user projects
- [x] Tests: backend/test_stage4.py — 42/42 passed; Stage 2 and
      Stage 3 suites still 34/34 each
- [x] Docs: MATERIALS.md (data quality + sources + architecture),
      TEST_RESULTS_STAGE4.md, api-spec.md, MUSE_INTEGRATION.md,
      ARCHITECTURE.md, STATUS.md, README.md

## Honest limits

- [ ] The library is a 38-material **sample**, not a complete
      universal database. Counts are stated on the library page
      itself; do not claim completeness.
- [ ] Some properties are sparse by design: compressive strength
      is recorded for 11/38, fatigue limit for 15/38, fracture
      toughness for 16/38 — the gaps are shown, not filled.
- [ ] Cost is a relative 1–5 index, not a price. No supplier
      pricing is stored.
- [ ] No admin UI for adding materials yet — additions are made
      by appending to data/materials.json (documented).

---

# Stage 5 — 3D Modelling Workspace (19 Nov 2026)

## Completed in Stage 5

- [x] 3D viewport: orbit/zoom/pan, selection + highlighting,
      grid + axes, perspective + orthographic, 6 view angles,
      section view, exploded view, wireframe, fit view
- [x] Geometry: box, cylinder, sphere, cone, torus, rounded box
      (fillet), chamfered box, extrusion with holes, revolve
- [x] Booleans: real CSG union/subtract/intersect (mesh volumes
      verified: subtract really removes the tool volume)
- [x] Holes: boolean subtraction of a cylinder tool
- [x] Dimensional control: length/width/height/diameter/radius/
      angles/thickness/position/tolerance; units mm/cm/m/inches
- [x] Component library: gear, shaft, bearing, bolt, nut, spring,
      piston, pipe, I-beam, motor, enclosure — all parametric
- [x] Assembly: multi-component, positioning, rotation,
      parent-child hierarchy, visibility controls, exploded view;
      constraints stored (align/mate/lock — full constraint
      solving is future work)
- [x] Material integration: Stage 4 material per component,
      mass from density, identity preserved in saved models
- [x] Project integration: save, autosave, reopen, duplicate,
      rename (existing), export, version-aware updates (409 on
      stale base_version), owner-only access
- [x] Import/export: STL, OBJ, GLB, JSON — real, tested
- [x] AI preparation: model schema endpoint + project model API
      (create/modify/assign/assemble/inspect/save/export)
- [x] Tests: shaft, gear, gearbox, beam, multi-component models
      created, saved, reopened, validated; 56/56 backend,
      29/29 JS math, 28/28 headless kernel

## Honest limits

- [ ] Mesh kernel, not B-rep: no STEP/3MF/FCStd, no
      arbitrary-edge fillets/chamfers, simplified gear teeth,
      partial revolves built as full revolves
- [ ] No simulation in the modeller (Stage 1 rule still holds)
- [ ] Constraint solving (mates that stay solved) is future work

---

# Stage 6 — Physics and Simulation Foundation (19 Nov 2026)

## Completed in Stage 6

- [x] Physics foundation: gravity, mass (from mesh volume x
      density), density, velocity, acceleration, force,
      momentum, energy (translational KE), collision
      detection, friction, angular velocity, torque,
      rotational inertia (via Rapier)
- [x] Rigid-body simulation: static / dynamic / kinematic
      bodies, collision shapes, fixed + revolute joints,
      Rapier spring joints, damping, contact counting,
      rotational motion — real Rapier 0.14.0, validated 9/9
- [x] Structural analysis foundation: analytical beam
      (cantilever, simply supported), axial, torsion,
      stress/strain/displacement, safety factor — labelled
      ANALYTICAL, not FEA
- [x] Thermal: steady 1-D conduction + lumped-capacitance
      transient, using Stage 4 k / density / cp
- [x] Fluid preparation: analytical drag/lift, Reynolds
      number; OpenFOAM investigated and documented as not
      installed
- [x] Material integration: solvers read Stage 4 properties;
      missing properties are named errors, never substitutions
- [x] Simulation workspace: select objects, apply forces,
      set gravity, choose duration, run/pause/step, numerical
      results, motion visualisation, error inspection
- [x] Results: force/velocity data, height + energy charts,
      units and assumptions on every result
- [x] Solver architecture: registry + job system, backend
      jobs for analytical work, browser engine for interactive
      rigid-body work
- [x] Validation: free fall, collision, spring-mass, rotating
      body, cantilever beam, heat conduction — all against
      references with documented errors

## Honest limits

- [ ] No FEA (CalculiX / Code_Aster not installed) — jobs
      recorded as not_implemented, never faked
- [ ] No CFD (OpenFOAM not installed) — analytical drag/lift
      only, labelled as such
- [ ] No stress/strain field visualisation (needs FEA)
- [ ] Electrical simulation still a Stage 1 stub (501)
- [ ] Collision shapes are bounding boxes (ball for spheres)
- [ ] KE chart is translational only

---

# Stage 7 — Mechanical Engineering Laboratory (19 Nov 2026)

## Completed in Stage 7

- [x] Mechanical design environment: dedicated workspace with
      assembly inspection, exploded view, hierarchies
- [x] Component library: 11 new editable components (crankshaft,
      connecting rod, flywheel, clutch, brake disc, coupling,
      pulley, sprocket, hydraulic cylinder, valve, pump) plus the
      11 from Stage 5
- [x] Mechanical systems: gearbox, crank-slider engine parts,
      hydraulic lift, rotating machinery — as demo assemblies
      with real geometry
- [x] Motion and kinematics: crank-slider exact kinematics
      (animated + 720° analysis); revolute/fixed/spring joints
      reused from Stage 6
- [x] Engineering calculations: torque, speed, power, gear
      ratios, efficiency, friction (belt), bearing loads, shaft
      stress, bending, fatigue (Goodman), vibration, heat
      (lumped thermal, Stage 6) — formulas, units, inputs and
      assumptions shown
- [x] Simulation integration: mechanical assemblies run on the
      Stage 6 Rapier workspace; analytical results stored as
      jobs
- [x] Optimization preparation: material-alternative comparison
      on real Stage 4 data, checked against the component's
      current requirements
- [x] AI mechanical engineer: structured tools documented in
      docs/MUSE_INTEGRATION.md (build a machine from a
      natural-language request, run calculations, read results,
      propose and test improvements)
- [x] Documentation: BOM (CSV + print), calculation reports,
      simulation reports via the job system
- [x] Testing: 4 demo projects verified (geometry, volumes,
      calculations, API jobs)

## Honest limits

- [ ] No FEA (no stress/strain fields) and no CFD — analytical
      only, labelled as such
- [ ] No constraint solver — gear meshing is a calculation,
      not simulated contact
- [ ] Components are simplified representations (see
      docs/MECHANICAL.md); single-throw crankshaft only
- [ ] Optimisation is a material comparison, not an automated
      designer
- [ ] Nothing here is validated for manufacturing or real-world
      operation — conceptual designs only

---

# Stage 8 — Electrical Engineering Laboratory (19 Nov 2026)

## Completed in Stage 8

- [x] Circuit designer: place, wire, drag, edit, delete,
      save/load JSON, demo circuits, BOM + CSV
- [x] Circuit simulation: real MNA solver — DC, transient,
      AC sweep, voltages/currents/power, frequency response
- [x] Electrical calculations: Ohm's law, KCL/KVL (in the
      solver itself), power, energy, R/C/L, impedance,
      AC power, power factor, efficiency — formulas, units
      and assumptions shown
- [x] Motors and generators: DC motor design and
      calculation; motor+gearbox integration with Stage 7;
      AC/synchronous/BLDC/stepper/generator models are
      parameter notes, not built
- [x] Battery and energy systems: series/parallel packs,
      capacity, voltage, runtime, energy
- [x] Power systems: ideal transformer; distribution,
      transmission, switchgear and protection are
      architecture notes, not built
- [x] Electromagnetics: analytical solenoid (inductance,
      field, flux, energy); FEMM/Elmer checked not
      installed — no field solver, recorded as not built
- [x] Material integration: wire resistance from recorded
      Stage 4 resistivity; missing values refused
- [x] Mechanical integration: motor+gearbox solver chains
      electrical input to mechanical output
- [x] Documentation: schematic JSON, BOM, calculation
      reports, simulation jobs, wiring list
- [x] Testing: 6 demo circuits verified against analytical
      references; analytical solvers cross-checked against
      the MNA solver

## Honest limits

- [ ] No ngspice / FEMM / Elmer (not installed) — the lab
      uses its own MNA solver and analytical formulas
- [ ] BJT/MOSFET/op-amp models are simplified (see
      docs/ELECTRICAL.md)
- [ ] No distribution, transmission, switchgear or
      protection systems
- [ ] No AC/synchronous/BLDC/stepper motor models yet
- [ ] Nothing here is validated for a real electrical
      installation — conceptual designs only
