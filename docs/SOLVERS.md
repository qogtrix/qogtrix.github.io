# Solver Architecture (Stage 6)

## The rule

Every simulation result carries its method and its engine.
Three kinds exist, and the UI labels them:

| Method | Meaning | Examples in Stage 6 |
|---|---|---|
| **Analytical** | Closed-form formula, exact for its idealised model | Cantilever / simply-supported beam, axial bar, torsion, 1-D conduction, lumped thermal, drag/lift, free fall |
| **Numerical (validated)** | A real solver, checked against analytical benchmarks | Rapier rigid-body dynamics (9/9 headless benchmarks) |
| **Not implemented** | No solver installed — the job system records the request and refuses to fake a result | FEA (CalculiX / Code_Aster), CFD (OpenFOAM) |

Nothing is ever presented as validated FEA when it is not.

## Solver registry

`backend/solvers.py` holds `SOLVER_REGISTRY`: every solver's
label, method, engine, status (`available` / `browser` /
`not_implemented`), inputs, outputs, required material
properties and assumptions. The API exposes it at
`GET /api/v1/solvers` (public). Adding a solver means adding
one registry entry and one implementation — the job API, the
frontend and the docs all read the registry.

## Engines in use

- **Rapier 0.14.0** (MIT/Apache) — rigid-body dynamics, in the
  browser via `@dimforge/rapier3d-compat` from jsDelivr CDN.
  Fixed timestep 1/60 s. Bodies are the model's top-level
  components; children move rigidly with their parent.
  Collision shapes are bounding boxes (ball for spheres) —
  an approximation, stated in the results. Mass comes from
  mesh volume × Stage 4 material density (1000 kg/m³ when no
  material is assigned). Springs use Rapier's native spring
  joints; joints are fixed (weld) or revolute (hinge).
  Validated headlessly: `backend/test_stage6_rapier.mjs`,
  9/9 against analytical references.
- **Python analytical solvers** (`backend/solvers.py`, stdlib
  only) — Euler-Bernoulli beam theory, axial deformation,
  torsion, Fourier conduction, lumped capacitance, steady
  drag/lift, free-fall kinematics. All in SI units. Section
  properties are computed from the section (rectangle, circle,
  I-beam, hollow box), not guessed.

## Job system

`simulations` table (from Stage 1, now used for real): id,
project_id, owner_id, solver, solver_version, status
(`queued` / `running` / `completed` / `failed` /
`not_implemented`), inputs, results (NULL until a real solver
writes it — the Stage 1 rule, now honoured by real solvers),
created_at.

- Analytical solvers run synchronously on job creation
  (they are milliseconds) and the job is stored `completed`
  with method, engine, assumptions and values — or `failed`
  with the error.
- `rigid_body` jobs are created `queued`; the browser runs
  Rapier and posts the time series + summary to
  `POST /api/v1/simulations/{id}/results`.
- `fea` / `cfd` jobs are created `not_implemented` with no
  results and an explanation.
- All job endpoints are owner-scoped: another user's project
  or job returns 404.

## FEA / CFD investigation (19 Nov 2026)

Checked on this machine: `ccx` (CalculiX), Code_Aster and
OpenFOAM (`openfoam`, `blockMesh`) are **not installed**, and
neither are scipy/numpy. That is why Stage 6 ships analytical
structural/thermal/fluid calculations and a real rigid-body
engine, and explicitly does not claim FEA or CFD.

What adding FEA would take: install CalculiX (`ccx`) or
Code_Aster on the machine that runs the backend, add a
`fea` engine to `solvers.py` that (1) meshes the model
(tetrahedral mesh from the STL export), (2) writes the
solver input deck with material properties from Stage 4 and
the loads/constraints from the simulation job, (3) runs the
solver as a background job (not in the request — minutes to
hours), (4) parses nodal displacements/stresses into the
job's results. Same pattern for OpenFOAM (blockMesh + solver
+ post-processing). The job system already has the
`running` status and the results slot for this; the work is
the solver installation and the deck writer, not a redesign.

## Material integration

Solvers read properties from the Stage 4 database through
`_material_props()` (density, elastic modulus, Poisson's
ratio, thermal conductivity, specific heat, yield strength).
A required property that is null is an **error naming the
property** — the job is stored `failed` and the UI says so.
Nothing is substituted, estimated or defaulted.

## What is NOT in Stage 6

- No finite-element stress/strain fields (no solver installed).
- No CFD velocity/pressure fields (no solver installed).
- No thermal distribution maps beyond the 1-D conduction
  profile and the lumped-capacitance curve.
- No deformation visualisation from simulation (the modeller
  shows geometry, not deformed results).
- Electrical simulation is still the Stage 1 stub (501).
