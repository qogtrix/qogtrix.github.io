# Structural Engineering Laboratory — Stage 9

19 Nov 2026. A real structural analysis laboratory built on Stages
1–8: a direct-stiffness (DSM) solver in pure Python stdlib
(`backend/structure.py`), a 3D structural workspace
(`structural.html`), six analytical structural solvers, and six demo
structures. Everything is first-order, linear-elastic analysis.
Nothing here is a code check, and nothing here is safe to build
from.

## Method: direct-stiffness analysis

- **Elements:** 3D truss (axial only, 6 DOF) and 3D
  Euler-Bernoulli beam (12 DOF: axial EA/L, torsion GJ/L,
  bending in both planes). Consistent mass matrices (beam 12×12
  Przemieniecki, truss 6×6) plus lumped point masses for modal
  analysis.
- **Coordinates:** all SI — metres, newtons, pascals. **Y is up**
  (matches the Three.js workspace). Gravity acts in −Y.
- **Local axes:** local x runs along the member; local y is
  taken from global +Y (global +Z for vertical members). For a
  vertical column the in-plane bending moment is therefore the
  local M_y, not M_z. Section height h is along local y, width b
  along local z. Iz = b·h³/12 (bending in the x-y plane),
  Iy = h·b³/12.
- **Section properties** (`section_properties_2d`): rectangle,
  circle, I-beam, box. Torsion constants J are exact for circles
  and approximations for other sections (open-section sum/3 for
  I-beams, Bredt's formula for boxes, Roark's β formula for
  rectangles) — documented as approximations in the code.
- **Solver:** Gaussian elimination with partial pivoting on the
  assembled global stiffness matrix. Modal analysis solves the
  generalised eigenproblem K·φ = λ·M·φ via Cholesky + cyclic
  Jacobi.

## The torsion-restraint convention

A straight beam line on simple supports is a rigid-body mechanism
in torsion: nothing restrains rotation about the member axis. The
solver refuses such a model with an "unstable" error and a pointer
to this document. **Simple supports must restrain torsion about
the member axis** — rx for a beam along X, ry for a vertical
column. The workspace's Pin preset does this (it restrains
translations plus rx); the Roller preset restrains uy, uz and rx.
Fixed restrains all six DOFs.

Related: a degree of freedom whose entire stiffness row is zero
(for example a rotation at a truss joint) is **inactive** — held
at zero and listed in the warnings. A load applied to an inactive
DOF is an error, not silently ignored (for example a moment on a
truss joint: "load applied to rz at node C, which has no
stiffness").

## Loads, cases and combinations

- **Point loads** at nodes: forces (fx, fy, fz) and moments
  (mx, my, mz), in newtons / newton-metres.
- **Distributed loads** on members: (wx, wy, wz) N/m, in global
  or local coordinates. Converted to consistent nodal loads
  (fixed-end forces wL/2, wL²/12), not lumped approximations.
- **Self-weight:** ρ·A·g in −Y, from the member's recorded
  material density.
- **Thermal loads:** equivalent nodal forces ±EA·α·ΔT. α comes
  from the material's recorded `thermal_expansion_um_mk`. A
  material without α on record raises a named error — never a
  guess. (In the current database only mineral-wool and
  silica-aerogel lack a recorded α.)
- **Load cases** are named (dead, live, wind, seismic, snow,
  thermal, …). **Combinations** apply factors per case. An
  analysis can run on all cases (unfactored), one case, or one
  named combination. Unknown combinations are rejected.

## Results

Static analysis returns, per node: displacement, rotation,
reaction (a 6-list; `null` for unrestrained DOFs). Per member:
end forces (local), diagrams at 11 stations (axial, shear_y,
shear_z, moment_y, moment_z, torque), max stress (axial +
bending about both axes, from the diagram maxima — not from end
forces alone), von Mises stress with torsion shear, utilisation
against the recorded strength (yield, else the tensile /
compressive pair), and buckling data for compression members.
Summaries: max displacement, max utilisation, max buckling
utilisation, warnings.

**Sign convention for diagrams:** at a member's n1 end the
diagram moment IS the moment exerted on the joint; at its n2 end
it is the negative. Joint equilibrium is checked this way in the
test suite (portal frame, both joints, exactly zero).

**Buckling** is per-member Euler / Johnson: Pcr = π²·E·Imin /
(KL)², with the Johnson parabola when slenderness λ < λc =
√(2π²E/σc). K is the member's `k_factor` (default 1.0).
Buckling is member buckling only — there is no system
(eigenvalue) buckling and no P-delta / second-order analysis.

**Modal analysis** returns frequencies, periods and mode shapes
(normalised to max component 1.0; shapes give all six DOF
components per node). A non-positive eigenvalue is reported as a
rigid-body mode with a warning, not hidden.

## Analytical solvers (Stage 9)

In `backend/solvers.py`, all available through the Stage 6 job
API (`POST /api/v1/simulations`):

- `column_buckling` — Euler/Johnson critical load for a column
  of a given section and material, with utilisation vs an applied
  load.
- `fixed_beam` — fixed-fixed beam, centre point load:
  δ = FL³/192EI, M_end = M_mid = FL/8.
- `natural_frequency_beam` — first natural frequency of a beam
  (cantilever βL = 1.87510407, simply supported π, fixed-fixed /
  free-free 4.73004074), reported for both axes.
- `wind_load_is875` — IS 875-3:2015 formula calculator:
  Vz = Vb·k1·k2·k3, pz = 0.6·Vz², F = pz·A·Cf. The k-factors are
  user inputs, not looked up from the code.
- `seismic_base_shear_is1893` — IS 1893-1:2016 formula
  calculator: Ah = (Z/2)·(I/R)·(Sa/g), Vb = Ah·W. Sa/g is a user
  input, not taken from the response spectrum.
- `load_combination` — factored total for one of eight factor
  sets: 1.5(DL+LL), 1.2(DL+LL+WL), 1.2(DL+LL+EL),
  1.5(DL+WL), 1.5(DL+EL), 0.9DL+1.5WL, 0.9DL+1.5EL,
  1.5(DL+SL). Arithmetic only — not a code compliance check.

`structural_static`, `structural_modal` and
`structural_buckling` are registered in the same registry but
only run through `POST /api/v1/structures/analyze` — posting
them to `/api/v1/simulations` records a failed job explaining
that (same pattern as the Stage 8 circuit solvers).

## API

- `GET /api/v1/structures/schema` — public. The structure JSON
  schema: nodes, elements (beam/truss), supports (6 DOF),
  loads, combinations, and the notes above.
- `POST /api/v1/structures/validate` — auth. Body
  `{structure}`; returns `{valid, errors}`.
- `POST /api/v1/structures/analyze` — auth, owner-scoped
  project. Body `{project_id, structure, analysis}` where
  `analysis` is `{type: "static" | "modal" | "buckling",
  combination?, case?, n_modes?}`. Runs the DSM solver and
  stores the result as a simulation job with solver
  `structural_static`, `structural_modal` or
  `structural_buckling` (201 on success, 200 with status
  `failed` on a solver error). Buckling is a static run whose
  results emphasise the buckling fields.
- `GET / PUT /api/v1/projects/{id}/structure` — auth,
  owner-scoped. The structure document lives in the project
  payload (alongside the 3D model). PUT is version-aware:
  `base_version` must match the stored version or the server
  returns 409; a successful PUT increments the version.

## Workspace (`structural.html`)

Six tabs: **Designer** (nodes / members / supports / loads /
combinations editors + Three.js 3D view with colour-by-material,
colour-by-utilisation, deformed shape with exaggeration slider,
load arrows, support markers, click-to-select member with
axial/shear/moment diagrams), **Analysis & Results** (static /
modal / buckling runs, reactions, displacements, member forces,
buckling table, modal frequencies with animated mode shapes,
jobs list), **Calculations** (the six analytical solvers),
**Standards** (honest status table), **AI Assistant** (reviews
only the last real analysis — weakest member, displacement vs
the L/250 rule of thumb, buckling-critical member), **Report**
(HTML report + member-results CSV + print-to-PDF).

The designer works without signing in (guest structures are
saved in the browser). Analysis and calculations need a
signed-in project, because results are stored as simulation
jobs. **Import from 3D model** turns beam / pipe / shaft
components of the project's 3D model into structural members
(position + length along the component's rotated X axis,
circular section from its diameter, its material if set);
components without a length are skipped and reported.

## Materials

Structural materials in the Stage 4 database: steel-s355
(E 200 GPa, yield 355 MPa), steel-1045, steel-1018,
alu-6061-t6, alu-7075-t6, cf-epoxy (E 70 GPa, tensile 600 MPa),
concrete-c30 (E 30 GPa, compressive 30 MPa), timber-glulam
(E 12 GPa). Every property shows its source, grade, units and
assumptions in the Materials Library; missing values are null,
never invented.

## Demo structures (`workspace/test-structures/`)

- `simply_supported_beam` — 4 m, 10 kN centre load.
- `cantilever` — 2 m, 5 kN tip load.
- `truss_2d` — 6 m Pratt truss, 10 kN at interior top joints.
- `portal_frame` — 4 m span, 3 m high, 10 kN/m UDL + 20 kN
  lateral load, with two load combinations.
- `truss_bridge` — 12 m span, 3 m deep, 20 kN panel loads +
  self-weight. Top-chord buckling utilisation 0.74 — under 1.0
  but the closest to its limit of any demo member, which is
  exactly what the workspace is for.
- `column_buckling` — 3 m, 100×100 mm, 100 kN.

## Honest limits

- **No FEA package is installed** (CalculiX, Code_Aster and
  Elmer were checked — none is on this machine). The solver is
  our own direct-stiffness implementation for beams and trusses
  only. There is no plate / shell / solid finite-element
  analysis.
- **No code compliance.** IS 875 and IS 1893 appear as formula
  calculators with user-supplied factors, not as code checks.
  IS 800, IS 456, AISC 360, ACI 318 and the Eurocodes are not
  implemented. Load-combination factors are arithmetic, not
  compliance. Deflection is reported against an L/250 rule of
  thumb, labelled as such.
- **First-order, linear-elastic only.** No P-delta / second-order
  effects, no system buckling, no connection design, no
  foundation design, no dynamic / time-history analysis
  (wind and seismic are static load cases).
- **Conceptual designs only.** Nothing on this page is validated
  for construction. A completed analysis is not a design
  approval.
