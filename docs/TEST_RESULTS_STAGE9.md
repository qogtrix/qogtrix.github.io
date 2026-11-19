# Stage 9 test results — 19 Nov 2026

`backend/test_stage9.py` — **80/80 tests passed.**

## DSM benchmarks (module level, vs hand-computed references)

- SS beam, 4 m, 10 kN centre load, rect 0.1×0.2 steel: reactions
  5000 N each, midspan deflection 1.0 mm, midspan moment
  10000 N·m, max stress 15 MPa, utilisation 0.0423. Exact.
- SS beam, 5 kN/m UDL: reactions 10000 N each, midspan
  deflection 1.25 mm, midspan moment 10000 N·m. Exact.
- Cantilever, 2 m, 5 kN tip: tip deflection 1.0 mm,
  fixed-end moment −10000 N·m. Exact.
- Fixed-fixed beam, 5 kN/m UDL: end moments −6666.7 N·m,
  midspan moment +3333.3 N·m. Exact.
- Self-weight SS beam (steel 0.1×0.2): reactions 3080.3 N,
  midspan deflection 0.385 mm. Exact.
- Modal, cantilever: f1 20.481 Hz (weak axis), f2 40.963 Hz
  (strong axis) — ~0.5% above the analytical 20.38 / 40.77 Hz,
  the expected consistent-mass discretisation error with one
  element per member.
- Thermal, restrained bar, ΔT 50 K: stress 120 MPa = E·α·ΔT.
  Exact. A thermal load on a material with no recorded α
  raises a named error ("has no thermal expansion coefficient
  on record — refusing to guess one").
- Column, 3 m, 100×100 mm, K=1: Pcr 1827.7 kN, buckling
  utilisation 0.055. Regime Johnson (λ 103.9 < λc 105.9).
- Torsion, cantilever with end torque: twist 0.002648 rad =
  TL/GJ. Exact.
- 3-member truss, 10 kN at apex: diagonals −7071 N
  (compression), bottom chord +5000 N (tension), reactions
  5000 N each. Exact.
- Portal frame, 4 m span, 3 m columns, fixed bases, 10 kN/m
  UDL + 20 kN lateral: ΣFx −20000 N, ΣFy +40000 N exactly;
  joint moment balance 0 at both joints (in-plane moment is
  local M_y for columns, local M_z for beams; n1-end diagram
  moments are joint moments, n2-end ones are their negative);
  top drift C 7.826 mm, D 7.813 mm.

## Load combinations

- 1.2(DL+WL) reactions are exactly 1.2× the unfactored
  reactions. Unknown combination names are rejected.

## Validation errors

No supports, duplicate node id, unused node, unknown material
(with ids supplied), a moment applied to a truss joint, and an
unrestrained-torsion mechanism (straight beam, no torsional
restraint anywhere → "structure is unstable") are all caught
and reported. The mechanism error names the torsion-restraint
convention and points at `docs/STRUCTURAL.md`.

## Analytical solvers (vs references)

- column_buckling: Pcr 1827.7 kN.
- fixed_beam: deflection 0.25 mm, end/mid moment 5000 N·m.
- natural_frequency_beam (2 m cantilever): weak 20.385 Hz,
  strong 40.769 Hz — agreeing with the DSM modal run (20.481 /
  40.963 Hz) within the 0.5% discretisation gap.
- wind_load_is875 (Vb 44, k=1, A 10, Cf 1.3): pz 1161.6 Pa,
  F 15100.8 N.
- seismic_base_shear_is1893 (W 1e6, Z 0.36, I 1, R 5, Sa/g
  2.5): Ah 0.09, Vb 90000 N.
- load_combination 1.5(DL+LL): 22500 N.
- `structural_static` through `run_solver` refuses with the
  pointer to `POST /api/v1/structures/analyze`.

## Demo structures

All six files in `workspace/test-structures/` validate and
analyse to their reference values: SS beam (5000 N, 1.0 mm),
cantilever (1.0 mm), truss (b0 reaction 10000 N), portal frame
(equilibrium −20000 / +40000 N), truss bridge (live-only
reaction d0 30 kN; max buckling utilisation 0.741 < 1.0),
column (Pcr 1827.7 kN, utilisation 0.055).

## API (real backend on a temporary database, real HTTP)

Health reports stage 9. Schema lists beam/truss element types.
Validate accepts a valid structure and rejects one with no
supports. Static and modal jobs complete via the API with
correct values. An invalid structure is recorded `failed`.
Bob gets 404 on Alice's project. Structure document: starts
empty, saves to version 2, round-trips, stale `base_version`
is rejected with 409, Bob gets 404 saving to Alice's project.
`column_buckling` completes via `/api/v1/simulations`;
`structural_static` via the same endpoint is recorded `failed`
with the pointer message. The solvers registry lists
`structural_static`, `column_buckling`, `wind_load_is875` and
`seismic_base_shear_is1893`.

## Earlier suites re-run

Stage 2 **34/34**, Stage 3 **34/34**, Stage 4 **42/42**,
Stage 5 **56/56** (backend) + **29/29** (JS maths) +
**28/28** (headless kernel), Stage 6 **29/29** (backend) +
**9/9** (Rapier), Stage 7 **99/99** (backend) + **36/36**
(JS maths) + **22/22** (headless kernel), Stage 8 **71/71**.
Health assertions accept stage 9. All green.

## Bugs found and fixed while testing Stage 9

- The structural solver branches in `solvers.py` were first
  inserted between two fallthrough raises, so they were
  unreachable (`no implementation for solver: column_buckling`).
  Moved above the first raise; all six solvers then verified.
- `GET/PUT /api/v1/projects/{id}/structure` was dispatched
  after the generic projects route, so every call 404'd.
  Moved before it (next to the model route).
- The joint-balance test originally read moment_z for vertical
  columns; the in-plane moment for a column is local M_y, and
  n2-end diagram moments are the negative of the joint moment.
  The solver was right; the test was fixed, and the convention
  is now documented in `docs/STRUCTURAL.md`.
- `approx()` with a zero reference has zero tolerance, so the
  joint-balance checks (residual ~1e-12 N·m, floating-point
  noise) now use an absolute tolerance of 1e-6.

## Not tested

- Browser rendering of `structural.html` (syntax checked with
  `node --check`; pages served locally return 200). The
  Three.js viewport, diagram canvases and mode-shape animation
  were not probed in a live browser from this environment.
- CalculiX / Code_Aster / Elmer: not installed — the honest
  result is our own DSM solver, which is what is tested.
