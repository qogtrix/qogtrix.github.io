# Stage 6 — Validation and Benchmarks

**Date:** 19 Nov 2026

Every number below was produced by running the real solver,
not by copying a formula into a report.

## A. Rapier rigid-body engine — 9 / 9 passed

`backend/test_stage6_rapier.mjs` runs Rapier 0.14.0 headlessly
in Node and compares it with analytical references.

| Benchmark | Reference | Measured | Error |
|---|---|---|---|
| Free fall, y after 1 s (from 10 m) | 5.095 m | 5.095 m | < 0.05 m |
| Free fall, v after 1 s | −9.81 m/s | −9.81 m/s | < 0.05 m/s |
| Free fall, energy KE + PE | constant | constant | < 0.5% |
| Collision, ball dropped 2 m, restitution 0.5 | bounces, rebound ≈ 0.5 m above floor | bounces, rebound ≈ 0.5 m | within 0.25 m |
| Spring-mass period (m = 0.034 kg, k = 40 N/m) | T = 2π√(m/k) = 0.182 s | 0.184 s | 0.8% |
| Rotating body, ω = 2 rad/s, no damping | stays 2.0 rad/s | 2.0 rad/s | < 0.05 rad/s |
| Torque 0.1 N·m on a sphere (I = 0.0524 kg·m²), 0.5 s | Δω = 0.955 rad/s | 0.955 rad/s | < 0.15 rad/s |
| Static body under gravity | does not move | does not move | 0 |

Two Rapier API facts were learned the hard way and are
recorded in the test file: `RigidBodyDesc.lockTranslations()`
takes no arguments and locks **all** axes (use
`enabledTranslations(x, y, z)` for partial locks), and forces
and torques accumulate in **separate** accumulators — reset
both each step when applying a fresh force per step.

## B. Analytical solvers — 29 / 29 passed

`backend/test_stage6.py` checks every analytical solver
against hand-computed values (formulas in the test file and
in `docs/SOLVERS.md`).

| Solver | Case | Reference | Measured |
|---|---|---|---|
| Cantilever beam | 0.1×0.2 m rectangle, L = 3 m, F = 1000 N, E = 200 GPa | δ = 0.675 mm, σ = 4.5 MPa, SF = 78.9 | exact to 0.1% |
| Simply supported beam | same beam, centre load 1000 N | δ = 0.0422 mm, σ = 1.125 MPa | exact to 0.1% |
| Axial bar | A = 0.001 m², L = 1 m, F = 10 kN | σ = 10 MPa, ΔL = 0.05 mm | exact to 0.1% |
| Torsion shaft | d = 20 mm, L = 1 m, T = 100 N·m | τ = 63.66 MPa, φ = 0.0828 rad | exact to 0.2% |
| Thermal conduction | steel slab 10 mm, A = 1 m², ΔT = 100 K | Q = 500 kW, R = 0.0002 K/W | exact |
| Lumped thermal | steel, V = 0.001 m³, A = 0.06 m², h = 10, 100 → 25 °C, 3600 s | τ = 6411 s, T = 67.8 °C | exact to 0.2% |
| Drag | air, v = 30 m/s, A = 1 m², Cd = 0.5 | Fd = 275.6 N, Re = 2.03×10⁶ | exact to 1% |
| Free fall | h = 10 m, m = 1 kg | t = 1.428 s, v = 14.0 m/s, KE = 98.1 J | exact to 0.1% |
| I-beam section | 200×100×10×6 mm | I = 2.098×10⁻⁵ m⁴ | exact to 0.5% |

Also verified: a missing material property (yield strength)
is rejected with a named error, never substituted; the FEA
solver refuses to run; jobs are owner-scoped (Bob gets 404
on Alice's jobs); results cannot be posted twice.

## C. What was NOT validated

- **FEA / CFD:** no solver is installed, so there is nothing
  to validate. The claim is the absence, stated in the UI
  and in `docs/SOLVERS.md`.
- **Browser rendering of the simulation workspace:** JS
  syntax checked, pages served locally return 200. The
  hosted app's builder verifies its own UI.
- **GLB export in Node** (Stage 5 note, still true): needs
  the browser's FileReader.

## D. How to re-run

```bash
cd backend
python3 test_stage6.py            # analytical + job API: 29/29
node test_stage5_math.js          # Stage 5 maths still green
mkdir /tmp/rapier-test && cd /tmp/rapier-test
npm install @dimforge/rapier3d-compat@0.14.0
cp <repo>/backend/test_stage6_rapier.mjs test-rapier.mjs
node test-rapier.mjs              # Rapier benchmarks: 9/9
```
